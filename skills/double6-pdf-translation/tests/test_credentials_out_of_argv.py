"""凭据不进入子进程 argv 与任何输出（日志、回执、清单、异常、翻译缓存）。

只用合成标记 SYNTHETIC-NONCREDENTIAL（及其变体），从不读取真实密钥环境变量：子进程环境从零构造，进程内用例
只 delenv。只连本机测试 HTTP 服务（127.0.0.1；127.0.0.2 为“非回环名单”的远端样式地址，仍在本机回环网段）。

覆盖：真实子进程 argv（/proc/self/cmdline）与后端原生环境变量（只记 sha256）、真实 qwen 适配器 stdin 调用与
Authorization 的 sha256、真实 vendored CLITranslator/OpenAITranslator 及其 cache.v1.db 扫描、失败/超时/重试日志、
run_bounded 回执与 stderr_summary、WORKFLOW_INTERNAL_ERROR.json、缓存身份隔离、远端缺凭据先于子进程失败、
本地占位、doctor 不再采用 OPENAI_API_KEY、LaTeX 直连（外部后端缺失 → 结构化错误；假后端 → 回环转发器）。
边界：同用户 /proc/<pid>/environ 可读，环境变量不是保密隔离边界；这里只验证不进 argv/输出。
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SKILL / 'tests')]

import credential_env as ce  # noqa: E402
import credential_forwarder as cf  # noqa: E402
import paper_translation_workflow as wf  # noqa: E402
import pdf_translation_commands as pc  # noqa: E402
import run_pdf_translation as rpt  # noqa: E402
from bounded_execution import run_bounded  # noqa: E402
from daily_skill_research.execution import _redacted_argv  # noqa: E402

MARKER = 'SYNTHETIC-NONCREDENTIAL'
HAS_PROC = Path('/proc/self/cmdline').exists()
needs_proc = pytest.mark.skipif(not HAS_PROC, reason='/proc/<pid>/cmdline 仅 Linux')


def _make_pdf(path: Path) -> Path:
    import fitz
    document = fitz.open()
    page = document.new_page()
    sentence = 'This synthetic English paragraph exists only to exercise the translation pipeline in tests.'
    for row in range(12):
        page.insert_text((72, 72 + 18 * row), sentence, fontsize=10)
    document.save(path)
    return path


@pytest.fixture(scope='session')
def _pdf(tmp_path_factory) -> Path:
    return _make_pdf(tmp_path_factory.mktemp('pdf') / 'in.pdf')


@pytest.fixture(autouse=True)
def _bind_pdf(_pdf):
    globals()['TEST_PDF'] = _pdf


TEST_PDF: Path


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def scan(root: Path, *needles: str) -> list[str]:
    """逐字节扫描目录下全部文件（含 sqlite 主库、-wal、-shm）。"""
    hits = []
    for path in sorted(Path(root).rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            if any(needle.encode() in data for needle in needles if needle):
                hits.append(str(path))
    return hits


def child_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """从零构造子进程环境：不继承调用者的任何凭据变量。"""
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8', 'HOME': str(home),
           'PAPER_TRANSLATION_WORKSPACE': str(tmp_path / 'ws'), 'PAPER_TRANSLATION_ENGINE_HOME': str(tmp_path / 'engine-home'),
           'PYTHONDONTWRITEBYTECODE': '1'}
    env.update(extra)
    return env


@pytest.fixture(autouse=True)
def _no_inherited_credentials(monkeypatch):
    for name in ('LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY', 'PDF2ZH_OPENAI_API_KEY', 'PDF2ZH_DEBUG'):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------- 本机记录服务

class Recorder(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, mode: str = 'ok'):
        super().__init__((host, 0), _RecorderHandler)
        self.mode = mode
        self.calls: list[dict] = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f'http://{self.server_address[0]}:{self.server_address[1]}/v1'


class _RecorderHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _record(self, body: bytes | None):
        auth = self.headers.get('Authorization')
        row = {'method': self.command, 'path': self.path, 'auth_present': auth is not None,
               'auth_sha256': sha(auth) if auth is not None else None}
        if body:
            try:
                row['model'] = json.loads(body).get('model')
            except ValueError:
                row['model'] = None
        self.server.calls.append(row)

    def _json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._record(None)
        self._json(200, {'object': 'list', 'data': [{'id': 'm-a', 'object': 'model'}, {'id': 'm-b', 'object': 'model'}]})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self._record(body)
        mode = self.server.mode
        if mode == 'fail500':
            return self._json(500, {'error': {'message': 'synthetic upstream failure'}})
        if mode == 'trickle':  # 每 0.4 s 发 1 字节：套接字单次读取不超时，整体远超 CLITranslator 时限
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', '100000')
            self.end_headers()
            try:
                for _ in range(15):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    time.sleep(0.4)
            except OSError:
                pass
            return
        self._json(200, {'id': 'rec', 'object': 'chat.completion', 'created': 0, 'model': 'x',
                         'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '你好，世界。'}}],
                         'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})


def recorder(host: str, mode: str = 'ok') -> Recorder:
    try:
        return Recorder(host, mode)
    except OSError as exc:  # macOS 默认未配置 127.0.0.2
        pytest.skip(f'cannot bind {host}: {exc}')


@pytest.fixture
def servers():
    made = []

    def make(host='127.0.0.1', mode='ok'):
        server = recorder(host, mode)
        made.append(server)
        return server
    yield make
    for server in made:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- 命令构建与原生通道

def parsed(*extra: str, key: str | None = MARKER, base='http://127.0.0.2:9/v1', mode='openai', model='m'):
    args = rpt.build_parser().parse_args(['/tmp/in.pdf', '--model', model, '--base-url', base, '--translator-mode', mode, *extra])
    args.api_key = key
    args.custom_system_prompt = 'p'
    return args


@pytest.mark.parametrize('mode,native', [('openai', ce.PDF_BACKEND_CREDENTIAL_ENV), ('qwen-cli', ce.CREDENTIAL_ENV)])
def test_backend_commands_carry_no_credential_and_use_native_env(tmp_path, mode, native):
    args = parsed(mode=mode)
    command = pc.build_pdf2zh_command(args, tmp_path)
    assert not [item for item in command if MARKER in item]
    assert '--openai-api-key' not in command
    if mode == 'qwen-cli':
        adapter = shlex.split(command[command.index('--clitranslator-command') + 1])
        assert '--api-key' not in adapter and not [item for item in adapter if MARKER in item]
        assert args.base_url in adapter and args.model in adapter  # 端点/模型仍在命令串（缓存身份）
    assert pc.backend_credential_env(args) == {native: MARKER}
    assert pc.backend_credential_env(args, via_loopback_proxy=True) == {native: ce.LOCAL_NO_AUTH_PLACEHOLDER}


def test_latex_direct_command_never_takes_the_upstream_credential(tmp_path):
    args = parsed()
    with pytest.raises(ValueError, match='latex_direct_credential_requires_loopback_forwarder'):
        pc.build_latex_direct_command(args, tmp_path / 'in.pdf', tmp_path / 'main.tex', tmp_path / 'o')
    command = pc.build_latex_direct_command(args, tmp_path / 'in.pdf', tmp_path / 'main.tex', tmp_path / 'o', translation_api_key='fwd-token')
    assert MARKER not in ' '.join(command) and command[command.index('--translation-api-key') + 1] == 'fwd-token'
    local = parsed(key=None, base='http://127.0.0.1:9/v1')
    command = pc.build_latex_direct_command(local, tmp_path / 'in.pdf', tmp_path / 'main.tex', tmp_path / 'o')
    assert command[command.index('--translation-api-key') + 1] == ce.LOCAL_NO_AUTH_PLACEHOLDER


@pytest.mark.parametrize('base', ['http://127.0.0.2:9/v1', 'https://remote.invalid/v1'])
def test_remote_without_credential_has_stable_error_and_no_value(tmp_path, base):
    args = parsed(key=None, base=base)
    for call in (lambda: pc.build_pdf2zh_command(args, tmp_path), lambda: pc.backend_credential_env(args),
                 lambda: pc.build_qwen_cli_command(args),
                 lambda: pc.build_latex_direct_command(args, tmp_path / 'a.pdf', tmp_path / 'm.tex', tmp_path)):
        with pytest.raises(ValueError) as caught:
            call()
        assert str(caught.value) in {ce.REMOTE_REQUIRES_KEY}
    for host in ('localhost', '127.0.0.1', '[::1]'):
        assert ce.resolve_credential(None, f'http://{host}:1/v1') == ce.LOCAL_NO_AUTH_PLACEHOLDER


def test_receipt_redactor_also_hides_flag_followed_values():
    """纵深防御，不是修复本身：命令已不含凭据。"""
    argv = ['x', '--openai-api-key', MARKER, '--api-key', MARKER + '2', '--translation-api-key', MARKER + '3', '--model', 'm']
    out = _redacted_argv(argv, frozenset())
    assert MARKER not in ' '.join(out) and out[-1] == 'm' and out.count('<redacted>') == 3


# ---------------------------------------------------------------- 真实子进程：PDF 后端（假后端）

FAKE_BACKEND = r'''#!/usr/bin/env python3
import hashlib, json, os, shlex, subprocess, sys, time
NAMES = ('PDF2ZH_OPENAI_API_KEY', 'LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY', 'PDF2ZH_DEBUG')
def proc_record(pid):
    try:
        argv = [a.decode() for a in open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\0') if a]
        raw = open(f'/proc/{pid}/environ', 'rb').read().split(b'\0')
    except OSError:
        return {'argv': None}
    env = dict(item.decode().split('=', 1) for item in raw if b'=' in item)
    return {'argv': argv, 'env_sha256': {k: hashlib.sha256(env[k].encode()).hexdigest() for k in NAMES if k in env}}
record = {'backend': proc_record(os.getpid())}
argv = sys.argv[1:]
if '--clitranslator-command' in argv:
    adapter = shlex.split(argv[argv.index('--clitranslator-command') + 1])
    child = subprocess.Popen(adapter, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.3)
    record['adapter'] = proc_record(child.pid)
    out, err = child.communicate('Hello world.', timeout=60)
    record['adapter_result'] = {'rc': child.returncode, 'stdout': out, 'stderr': err}
    print('adapter stderr:', err, file=sys.stderr)
open(os.environ['FAKE_BACKEND_DUMP'], 'w').write(json.dumps(record))
print('fake backend argv:', ' '.join(sys.argv))
print('fake backend argv:', ' '.join(sys.argv), file=sys.stderr)
sys.exit(int(os.environ.get('FAKE_BACKEND_RC', '0')))
'''


def fake_backend(tmp_path: Path) -> Path:
    path = tmp_path / 'fake_pdf2zh.py'
    path.write_text(FAKE_BACKEND)
    path.chmod(0o755)
    return path


def run_translation(tmp_path, *, base, key, mode='openai', rc='0', extra_env=None, bounded=False):
    out = tmp_path / 'out'
    argv = [sys.executable, str(SCRIPTS / 'run_pdf_translation.py'), str(TEST_PDF), '--output-dir', str(out),
            '--model', 'm', '--base-url', base, '--translator-mode', mode, '--pdf2zh-binary', str(fake_backend(tmp_path)),
            '--pdf-backend-only', '--latex-render-mode', 'off', '--openai-timeout', '30']
    env = child_env(tmp_path, FAKE_BACKEND_DUMP=str(tmp_path / 'dump.json'), FAKE_BACKEND_RC=rc, **(extra_env or {}))
    if key is not None:
        env[ce.CREDENTIAL_ENV] = key
    if bounded:
        result = run_bounded(argv, cwd=SKILL, receipt_dir=tmp_path / 'receipts', operation='credential-probe',
                             timeout_seconds=110, env=env)
        return result, out
    proc = subprocess.run(argv, cwd=SKILL, env=env, capture_output=True, text=True, timeout=110)
    return proc, out


@needs_proc
@pytest.mark.parametrize('rc', ['0', '3'])
def test_pdf_backend_real_child_argv_env_logs_manifests_and_receipts(tmp_path, rc):
    # 继承的同名/调试变量必须被清除，不能借道进入后端。
    result, out = run_translation(tmp_path, base='http://127.0.0.2:9/v1', key=MARKER, rc=rc, bounded=True,
                                  extra_env={'PDF2ZH_DEBUG': '1', 'OPENAI_API_KEY': MARKER + '-INHERITED'})
    dump = json.loads((tmp_path / 'dump.json').read_text())
    backend = dump['backend']
    assert not [item for item in backend['argv'] if MARKER in item]
    assert backend['env_sha256'] == {ce.PDF_BACKEND_CREDENTIAL_ENV: sha(MARKER)}
    log = (out / 'pdf2zh-next.log').read_text()
    assert 'fake backend argv:' in log  # 对照：后端把完整 argv 打进日志，日志确实被采集
    manifest = json.loads((out / 'render_manifest.json').read_text())
    assert '--openai-model' in manifest['command'] and MARKER not in json.dumps(manifest)
    assert result['command']['argv'] and MARKER not in json.dumps(result)  # run_bounded 回执与 stdout/stderr_summary
    assert scan(out, MARKER) == [] and scan(tmp_path / 'receipts', MARKER) == []
    assert scan(tmp_path / 'engine-home', MARKER) == [] and scan(tmp_path / 'ws', MARKER) == []


@needs_proc
def test_remote_without_credential_fails_before_any_child(tmp_path):
    proc, out = run_translation(tmp_path, base='http://127.0.0.2:9/v1', key=None)
    assert proc.returncode != 0 and ce.REMOTE_REQUIRES_KEY in proc.stderr
    assert not (tmp_path / 'dump.json').exists()


@needs_proc
def test_local_without_credential_uses_placeholder_via_native_env(tmp_path):
    proc, out = run_translation(tmp_path, base='http://127.0.0.1:9/v1', key=None)
    dump = json.loads((tmp_path / 'dump.json').read_text())
    assert dump['backend']['env_sha256'] == {ce.PDF_BACKEND_CREDENTIAL_ENV: sha(ce.LOCAL_NO_AUTH_PLACEHOLDER)}


@needs_proc
def test_qwen_route_real_adapter_reads_credential_from_inherited_env(tmp_path, servers):
    server = servers('127.0.0.2')
    proc, out = run_translation(tmp_path, base=server.base_url, key=MARKER, mode='qwen-cli')
    dump = json.loads((tmp_path / 'dump.json').read_text())
    assert not [item for item in dump['backend']['argv'] if MARKER in item]
    assert dump['backend']['env_sha256'] == {ce.CREDENTIAL_ENV: sha(MARKER)}
    adapter = dump['adapter']
    assert adapter['argv'][1].endswith('qwen_pdf2zh_cli_translator.py') and not [a for a in adapter['argv'] if MARKER in a]
    assert adapter['env_sha256'] == {ce.CREDENTIAL_ENV: sha(MARKER)}
    assert dump['adapter_result']['rc'] == 0 and dump['adapter_result']['stdout'].strip() == '你好，世界。'
    posts = [call for call in server.calls if call['method'] == 'POST']
    assert posts and all(call['auth_sha256'] == sha('Bearer ' + MARKER) for call in posts)
    assert scan(out, MARKER) == [] and scan(tmp_path / 'engine-home', MARKER) == []


def test_internal_error_receipt_from_actual_command_has_no_credential(tmp_path, monkeypatch):
    """最坏情形：异常消息直接携带实际后端命令；WORKFLOW_INTERNAL_ERROR.json（含 traceback）仍不含凭据。"""
    import pdf_translation_render as render
    monkeypatch.setenv(ce.CREDENTIAL_ENV, MARKER)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('PAPER_TRANSLATION_WORKSPACE', str(tmp_path / 'ws'))
    monkeypatch.setenv('PAPER_TRANSLATION_ENGINE_HOME', str(tmp_path / 'eh'))

    def exploding_run(command, **kwargs):
        raise OSError('spawn failed for ' + repr(command) + ' env-keys=' + ','.join(sorted(kwargs.get('env', {}))))
    monkeypatch.setattr(render.subprocess, 'run', exploding_run)
    args = rpt.build_parser().parse_args([str(TEST_PDF), '--output-dir', str(tmp_path / 'out'), '--model', 'm',
                                          '--base-url', 'http://127.0.0.2:9/v1', '--translator-mode', 'openai',
                                          '--pdf2zh-binary', '/bin/true', '--pdf-backend-only', '--latex-render-mode', 'off'])
    assert args.api_key == MARKER
    try:
        rpt.run(args)
    except OSError as exc:
        caught = exc
    else:  # pragma: no cover
        pytest.fail('expected spawn failure')
    assert '--openai-model' in str(caught) and MARKER not in str(caught)
    ns = SimpleNamespace(action='candidate', receipts=tmp_path / 'receipts')
    try:
        raise caught
    except OSError as exc:
        result = wf.unexpected_failure(ns, exc)
    receipt = tmp_path / 'receipts/WORKFLOW_INTERNAL_ERROR.json'
    assert receipt.is_file() and 'spawn failed' in receipt.read_text() and MARKER not in json.dumps(result)
    assert scan(tmp_path / 'receipts', MARKER) == [] and scan(tmp_path / 'out', MARKER) == []


# ---------------------------------------------------------------- 真实 vendored 后端与缓存库

def probe(tmp_path: Path, name: str, *, mode, base, model='m-a', key=MARKER, texts=('Hello world.',), timeout=30):
    work = tmp_path / name
    work.mkdir()
    spec = {'mode': mode, 'base_url': base, 'model': model, 'openai_timeout': timeout, 'texts': list(texts),
            'work': str(work), 'log': str(work / 'backend.log'), 'result': str(work / 'result.json')}
    (work / 'spec.json').write_text(json.dumps(spec))
    env = child_env(tmp_path)  # 同一 tmp HOME → 同一合成 cache.v1.db（便于验证复用/不复用）
    if key is not None:
        env[ce.CREDENTIAL_ENV] = key
    proc = subprocess.run([sys.executable, str(SKILL / 'tests/credential_probe_backend.py'), str(work / 'spec.json')],
                          env=env, capture_output=True, text=True, timeout=110)
    assert proc.returncode == 0, proc.stderr[-2000:]
    (work / 'stderr.txt').write_text(proc.stderr)
    return json.loads((work / 'result.json').read_text()), work


def cache_rows(tmp_path: Path) -> list[tuple]:
    db = tmp_path / 'home/.cache/pdf2zh_next/cache.v1.db'
    with sqlite3.connect(db) as connection:
        return connection.execute('select translate_engine, translate_engine_params, original_text, translation from _translationcache').fetchall()


@pytest.mark.parametrize('mode', ['openai', 'qwen-cli'])
def test_real_vendored_translator_auth_and_cache_db_scan(tmp_path, servers, mode):
    server = servers('127.0.0.2')
    result, work = probe(tmp_path, 'first', mode=mode, base=server.base_url, texts=('Hello world.', 'Hello world.'))
    assert result['error'] is None, result['error']
    assert result['outputs'] == ['你好，世界。', '你好，世界。'] and result['translate_cache_call_count'] >= 1
    assert result['translator'] == ('OpenAITranslator' if mode == 'openai' else 'CLITranslatorTranslator')
    posts = [call for call in server.calls if call['method'] == 'POST']
    assert posts and all(call['auth_sha256'] == sha('Bearer ' + MARKER) for call in posts)
    rows = cache_rows(tmp_path)
    assert rows and any(row[2] == 'Hello world.' for row in rows)  # 对照：缓存库确有本次写入
    assert MARKER not in result['cache_params'] and not [row for row in rows if MARKER in row[1]]
    assert MARKER not in json.dumps(result['argv'])
    assert scan(tmp_path / 'home', MARKER) == [] and scan(work, MARKER) == []


@pytest.mark.parametrize('mode', ['openai', 'qwen-cli'])
def test_cache_identity_ignores_credential_but_not_model(tmp_path, servers, mode):
    server = servers('127.0.0.1')
    first, _ = probe(tmp_path, 'k1', mode=mode, base=server.base_url, key=MARKER + '-ONE')
    posts_after_first = len([c for c in server.calls if c['method'] == 'POST'])
    same, _ = probe(tmp_path, 'k2', mode=mode, base=server.base_url, key=MARKER + '-TWO')
    assert same['cache_params'] == first['cache_params'] and same['translate_cache_call_count'] == 1
    other, _ = probe(tmp_path, 'model-b', mode=mode, base=server.base_url, model='m-b', key=MARKER + '-ONE')
    assert other['cache_params'] != first['cache_params'] and other['translate_cache_call_count'] == 0
    posts = [c for c in server.calls if c['method'] == 'POST']
    # 仅凭据不同：命中缓存，只多一次健康检查（ignore_cache=True）；模型不同：重新请求，不复用答案。
    assert len(posts) == posts_after_first + 1 + 2
    assert [c['model'] for c in posts[-2:]] == ['m-b', 'm-b']
    assert not [row for row in cache_rows(tmp_path) if MARKER in row[1]]


@pytest.mark.parametrize('mode', ['openai', 'qwen-cli'])
def test_cache_identity_isolated_by_endpoint(tmp_path, servers, mode):
    one, two = servers('127.0.0.1'), servers('127.0.0.1')
    first, _ = probe(tmp_path, 'e1', mode=mode, base=one.base_url)
    second, _ = probe(tmp_path, 'e2', mode=mode, base=two.base_url)
    assert first['cache_params'] != second['cache_params'] and second['translate_cache_call_count'] == 0
    assert len([c for c in two.calls if c['method'] == 'POST']) == 2  # 健康检查 + 实际翻译，未复用另一服务答案


@pytest.mark.parametrize('mode', ['fail500', 'trickle'])
def test_qwen_failure_timeout_and_retry_logs_have_no_credential(tmp_path, servers, mode):
    server = servers('127.0.0.2', mode)
    result, work = probe(tmp_path, mode, mode='qwen-cli', base=server.base_url, timeout=1)
    error = result['error']
    assert error is not None
    expected = 'CalledProcessError' if mode == 'fail500' else 'TimeoutExpired'
    log = (work / 'backend.log').read_text()
    # 对照：上游重试日志、异常与 DEBUG 日志确实带出完整适配器命令，而命令里没有凭据。
    assert expected in error['cause'] and 'qwen_pdf2zh_cli_translator.py' in error['cause']
    assert 'Retrying' in log and expected in log and 'Executing CLI command' in log and '--base-url' in log
    assert len([c for c in server.calls if c['method'] == 'POST']) >= 3
    assert MARKER not in json.dumps(error) and scan(work, MARKER) == [] and scan(tmp_path / 'home', MARKER) == []


# ---------------------------------------------------------------- doctor

def test_doctor_reads_only_local_translation_api_key(tmp_path, servers, monkeypatch):
    server = servers('127.0.0.1')
    monkeypatch.setenv('OPENAI_API_KEY', MARKER + '-OPENAI')
    report = wf.doctor(server.base_url, 'm-a')
    assert server.calls[-1]['path'].endswith('/models') and server.calls[-1]['auth_present'] is False
    assert report['credential']['source'] == 'none' and report['credential']['ignored_variables_present'] == ['OPENAI_API_KEY']
    monkeypatch.setenv(ce.CREDENTIAL_ENV, MARKER)
    report = wf.doctor(server.base_url, 'm-a')
    assert server.calls[-1]['auth_sha256'] == sha('Bearer ' + MARKER)
    assert report['credential']['source'] == 'env:' + ce.CREDENTIAL_ENV and MARKER not in json.dumps(report)


def test_doctor_remote_without_credential_blocks_before_request(servers, monkeypatch):
    server = servers('127.0.0.2')
    report = wf.doctor(server.base_url, 'm-a')
    assert ce.REMOTE_REQUIRES_KEY in report['blockers'] and server.calls == []


# ---------------------------------------------------------------- LaTeX 直连（pdf2zh_skill 未随仓库分发）

def latex_args(tmp_path, base, key):
    args = rpt.build_parser().parse_args([str(TEST_PDF), '--output-dir', str(tmp_path / 'out'), '--model', 'm-a',
                                          '--base-url', base, '--latex-render-mode', 'required', '--hymt-compat-proxy', 'off'])
    args.api_key = key
    return args


def latex_source(tmp_path) -> Path:
    tex = tmp_path / 'src/main.tex'
    tex.parent.mkdir(parents=True)
    tex.write_text('\\documentclass{article}\\begin{document}Hello.\\end{document}\n')
    return tex


def test_latex_direct_missing_backend_structured_error_without_child(tmp_path, monkeypatch):
    import pdf_translation_latex_render as lr
    import pdf_translation_paths as paths
    if paths.latex_direct_backend_status()['available']:
        pytest.skip('pdf2zh_skill 在本环境可用；此用例验证仓库默认（未分发）状态')
    launched = []
    monkeypatch.setattr(lr.subprocess, 'run', lambda *a, **k: launched.append(a) or pytest.fail('child launched'))
    out = tmp_path / 'out'
    out.mkdir()
    manifest = lr.run_latex_direct_render(latex_args(tmp_path, 'http://127.0.0.2:9/v1', MARKER), TEST_PDF, out,
                                          latex_source(tmp_path), {'PATH': os.environ.get('PATH', '')})
    assert launched == [] and manifest['status'] == 'error' and manifest['child_launched'] is False
    assert manifest['failure_stage'] == 'backend_unavailable' and manifest['command'] is None
    assert manifest['errors'][0]['error_type'] == 'latex_direct_backend_unavailable' and manifest['errors'][0]['end_to_end'] == 'not_run'
    assert scan(out, MARKER) == []


FAKE_LATEX_CLI = r'''import hashlib, json, os, sys, urllib.request
def main():
    argv = [a.decode() for a in open('/proc/self/cmdline', 'rb').read().split(b'\0') if a]
    args = sys.argv[1:]
    value = lambda flag: args[args.index(flag) + 1]
    body = json.dumps({'model': value('--translation-model'), 'messages': [{'role': 'user', 'content': 'Hello.'}]}).encode()
    request = urllib.request.Request(value('--translation-base-url').rstrip('/') + '/chat/completions', data=body,
                                     headers={'Authorization': 'Bearer ' + value('--translation-api-key'), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        reply = json.load(response)
    names = ('PDF2ZH_OPENAI_API_KEY', 'LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY')
    json.dump({'argv': argv, 'reply': reply['choices'][0]['message']['content'], 'base_url': value('--translation-base-url'),
               'env_names': [n for n in names if n in os.environ]}, open(os.environ['FAKE_LATEX_DUMP'], 'w'))
    print('fake latex argv:', ' '.join(argv))
    return 3
'''


@needs_proc
@pytest.mark.parametrize('remote', [True, False])
def test_latex_direct_fake_backend_gets_forwarder_token_or_placeholder(tmp_path, monkeypatch, servers, remote):
    import pdf_translation_latex_render as lr
    import pdf_translation_paths as paths
    root = tmp_path / 'fake-vendor'
    (root / 'pdf2zh_skill').mkdir(parents=True)
    (root / 'pdf2zh_skill/__init__.py').write_text('')
    (root / 'pdf2zh_skill/cli.py').write_text(FAKE_LATEX_CLI)
    monkeypatch.setattr(paths, 'vendored_pdf2zh_skill_root', lambda: root)
    monkeypatch.setattr(lr, 'vendored_pdf2zh_skill_root', lambda: root, raising=False)
    server = servers('127.0.0.2' if remote else '127.0.0.1')
    out = tmp_path / 'out'
    out.mkdir()
    env = child_env(tmp_path, FAKE_LATEX_DUMP=str(tmp_path / 'latex.json'), PDF2ZH_OPENAI_API_KEY=MARKER + '-STALE')
    args = latex_args(tmp_path, server.base_url, MARKER if remote else None)
    manifest = lr.run_latex_direct_render(args, TEST_PDF, out, latex_source(tmp_path), env)
    dump = json.loads((tmp_path / 'latex.json').read_text())
    assert not [a for a in dump['argv'] if MARKER in a] and dump['env_names'] == []
    assert dump['reply'] == '你好，世界。' and args.base_url == server.base_url  # 原地址已恢复
    post = [c for c in server.calls if c['method'] == 'POST'][-1]
    assert post['model'] == 'm-a'  # 用户显式模型原样转发
    channel = manifest['credential_channel']
    if remote:
        assert channel['mode'] == 'loopback_credential_forwarder' and channel['bind_host'] == '127.0.0.1'
        assert channel['upstream_base_url'] == server.base_url.rstrip('/') and channel['stats']['forwarded_requests'] == 1
        assert post['auth_sha256'] == sha('Bearer ' + MARKER) and dump['base_url'].startswith('http://127.0.0.1:')
        token = dump['argv'][dump['argv'].index('--translation-api-key') + 1]
        # 本项目写出的清单/日志行不含令牌；外部后端自身回显 argv 时令牌会出现在其日志中——令牌只对本次
        # 回环转发器有效、子进程结束即随转发器关闭失效，不是上游凭据。
        log = (out / 'latex_direct.log').read_text()
        command_line = next(line for line in log.splitlines() if line.startswith('COMMAND: '))
        assert token.startswith('fwd-') and token not in command_line and '<API_KEY>' in command_line
        assert scan(out, token) == [str(out / 'latex_direct.log')]
        port = int(dump['base_url'].rsplit(':', 1)[1].split('/')[0])
        with pytest.raises(OSError):  # 生命周期：子进程结束后转发器已关闭
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
    else:
        assert channel['mode'] == 'local_no_auth_placeholder' and post['auth_sha256'] == sha('Bearer ' + ce.LOCAL_NO_AUTH_PLACEHOLDER)
    assert manifest['returncode'] == 3 and 'fake latex argv:' in (out / 'latex_direct.log').read_text()
    assert scan(out, MARKER) == []


def test_latex_direct_forwarder_unavailable_is_stable_error_without_child(tmp_path, monkeypatch):
    import pdf_translation_latex_render as lr
    import pdf_translation_paths as paths
    monkeypatch.setattr(paths, 'latex_direct_backend_status', lambda: {'available': True, 'module': 'pdf2zh_skill'})
    import credential_forwarder

    def refuse(*a, **k):
        raise OSError('bind refused')
    monkeypatch.setattr(credential_forwarder, 'start_credential_forwarder', refuse)
    monkeypatch.setattr(lr.subprocess, 'run', lambda *a, **k: pytest.fail('child launched'))
    out = tmp_path / 'out'
    out.mkdir()
    manifest = lr.run_latex_direct_render(latex_args(tmp_path, 'http://127.0.0.2:9/v1', MARKER), TEST_PDF, out,
                                          latex_source(tmp_path), {})
    assert manifest['errors'][0]['error_type'] == cf.FORWARDER_UNAVAILABLE and manifest['child_launched'] is False
    assert manifest['failure_stage'] == 'credential_channel_unavailable' and scan(out, MARKER) == []


def test_forwarder_loopback_only_requires_token_and_forwards_verbatim(servers):
    server = servers('127.0.0.2')
    forwarder = cf.start_credential_forwarder(server.base_url, MARKER, timeout=10)
    try:
        assert forwarder.server_address[0] == '127.0.0.1'
        body = json.dumps({'model': 'm-a', 'messages': []}).encode()
        bad = urllib.request.Request(forwarder.base_url + '/chat/completions', data=body, headers={'Authorization': 'Bearer ' + MARKER})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=5)
        assert caught.value.code == 401 and server.calls == []
        good = urllib.request.Request(forwarder.base_url + '/chat/completions', data=body,
                                      headers={'Authorization': 'Bearer ' + forwarder.access_token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(good, timeout=5) as response:
            assert json.load(response)['choices'][0]['message']['content'] == '你好，世界。'
        assert server.calls[-1]['auth_sha256'] == sha('Bearer ' + MARKER) and server.calls[-1]['model'] == 'm-a'
        assert MARKER not in json.dumps(forwarder.describe()) and forwarder.access_token not in json.dumps(forwarder.describe())
    finally:
        forwarder.stop()


def test_latex_direct_with_existing_compat_proxy_gives_child_only_placeholder(tmp_path, monkeypatch, servers):
    import pdf_translation_latex_render as lr
    import pdf_translation_paths as paths
    monkeypatch.setattr(paths, 'latex_direct_backend_status', lambda: {'available': True, 'module': 'pdf2zh_skill'})
    monkeypatch.setattr(paths, 'should_enable_hymt_compat_proxy', lambda args: True)
    seen = {}

    def fake_run(command, **kwargs):
        seen['command'] = command
        seen['env'] = sorted(kwargs['env'])
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(lr.subprocess, 'run', fake_run)
    server = servers('127.0.0.2')
    out = tmp_path / 'out'
    out.mkdir()
    args = latex_args(tmp_path, server.base_url, MARKER)
    args.hymt_compat_proxy_port = 0
    manifest = lr.run_latex_direct_render(args, TEST_PDF, out, latex_source(tmp_path), {'PDF2ZH_OPENAI_API_KEY': MARKER})
    command = seen['command']
    assert command[command.index('--translation-api-key') + 1] == ce.LOCAL_NO_AUTH_PLACEHOLDER
    assert command[command.index('--translation-base-url') + 1].startswith('http://127.0.0.1:')
    assert MARKER not in ' '.join(command) and 'PDF2ZH_OPENAI_API_KEY' not in seen['env']
    assert manifest['credential_channel']['mode'] == 'hymt_compat_proxy' and scan(out, MARKER) == []
