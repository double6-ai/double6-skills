"""回环兼容代理背后的真实上游身份进入翻译缓存身份（PR #25 review-1 P1 回归）。

复现（用户独立审查 probe_proxy_cache.py）：两个真实本机 HTTP 上游甲/乙，真实 start_hymt_compat_proxy 同一端口、同一模型，
真实命令构建 + vendored ConfigManager/OpenAITranslator + 真实 cache.v1.db（子进程、隔离 HOME）。修复前第二次只发健康检查，
文本 cache_hit=1 并返回甲的译文。这里覆盖：同端口换上游必须未命中并得到乙；同上游仅凭据轮换必须命中；
模型/方向/提示词变化必须未命中；运行中代理被换到另一上游必须失败关闭；qwen-cli 适配器经代理的同类情形；
缓存库与工作目录扫描合成标记为 0。只用合成标记 SYNTHETIC-NONCREDENTIAL，只连本机测试服务，无真实模型或密钥。
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SKILL / 'vendor/babeldoc')]

import pdf_translation_commands as pc  # noqa: E402
import run_pdf_translation as rpt  # noqa: E402
import upstream_identity as ui  # noqa: E402
from hymt_compat_proxy import ProxyConfig, start_hymt_compat_proxy  # noqa: E402

MARKER = 'SYNTHETIC-NONCREDENTIAL'
MODEL = 'hy-mt-synthetic'
TEXT = 'This is an independent cache identity test sentence.'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _no_inherited_credentials(monkeypatch):
    for name in ('LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY', 'PDF2ZH_OPENAI_API_KEY', 'PDF2ZH_DEBUG'):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------- 本机真实上游

class Upstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, answer: str, host: str = '127.0.0.1'):
        super().__init__((host, 0), _UpstreamHandler)
        self.answer = answer
        self.calls: list[dict] = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f'http://{self.server_address[0]}:{self.server_address[1]}/v1'

    def posts(self) -> list[dict]:
        return [call for call in self.calls if call['method'] == 'POST']


class _UpstreamHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _record(self, body: bytes | None) -> None:
        auth = self.headers.get('Authorization')
        row = {'method': self.command, 'path': self.path, 'auth_sha256': sha(auth) if auth else None}
        if body:
            row['model'] = json.loads(body).get('model')
        self.server.calls.append(row)

    def do_GET(self):  # 与常见 OpenAI 兼容服务一样：任意 GET 回模型列表（不是本项目身份合同）
        self._record(None)
        self._json({'object': 'list', 'data': [{'id': MODEL, 'object': 'model'}]})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self._record(body)
        self._json({'id': 'up', 'object': 'chat.completion', 'created': 0, 'model': MODEL,
                    'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': self.server.answer}}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def upstreams():
    made: list[Upstream] = []

    def make(answer: str, host: str = '127.0.0.1') -> Upstream:
        try:
            server = Upstream(answer, host)
        except OSError as exc:  # macOS 默认未配置 127.0.0.2
            pytest.skip(f'cannot bind {host}: {exc}')
        made.append(server)
        return server
    yield make
    for server in made:
        server.shutdown()
        server.server_close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Proxy:
    """同一固定本机端口上先后启动的真实兼容代理（停旧起新，模拟代理重启/端口复用）。"""

    def __init__(self, port: int):
        self.port = port
        self.server = None

    def start(self, upstream: Upstream, *, model: str = MODEL, key: str = MARKER + '-PROXY-ONE'):
        self.stop()
        config = ProxyConfig(model=model, upstream_base_url=upstream.base_url, api_key=key, port=self.port)
        self.server = start_hymt_compat_proxy(config)
        assert config.port == self.port and 'port_fallback_to' not in config.stats  # 确实是同一端口
        return self

    @property
    def base_url(self) -> str:
        return f'http://127.0.0.1:{self.port}/v1'

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


@pytest.fixture
def proxy():
    made = Proxy(free_port())
    yield made
    made.stop()


# ---------------------------------------------------------------- 真实子进程后端（同一隔离 HOME → 同一真实缓存库）

def probe(tmp_path: Path, name: str, *, mode: str, base: str, model: str = MODEL, key: str = 'local-no-auth',
          texts=(TEXT,), timeout: int = 10, extra: dict | None = None, wait: bool = True):
    work = tmp_path / name
    work.mkdir()
    spec = {'mode': mode, 'base_url': base, 'model': model, 'openai_timeout': timeout, 'texts': list(texts),
            'work': str(work), 'log': str(work / 'backend.log'), 'result': str(work / 'result.json'), **(extra or {})}
    (work / 'spec.json').write_text(json.dumps(spec))
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8', 'HOME': str(home),
           'PAPER_TRANSLATION_WORKSPACE': str(tmp_path / 'ws'), 'PAPER_TRANSLATION_ENGINE_HOME': str(tmp_path / 'engine-home'),
           'PYTHONDONTWRITEBYTECODE': '1', 'LOCAL_TRANSLATION_API_KEY': key}
    child = subprocess.Popen([sys.executable, str(SKILL / 'tests/credential_probe_backend.py'), str(work / 'spec.json')],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if not wait:
        return child, work
    return finish(child, work)


def finish(child, work: Path):
    try:
        _, stderr = child.communicate(timeout=110)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    assert child.returncode == 0, stderr[-2000:]
    return json.loads((work / 'result.json').read_text())


def rows(tmp_path: Path) -> list[tuple]:
    db = tmp_path / 'home/.cache/pdf2zh_next/cache.v1.db'
    if not db.exists():
        return []
    with sqlite3.connect(db) as connection:
        return connection.execute('select translate_engine, translate_engine_params, original_text, translation '
                                  'from _translationcache').fetchall()


def scan(root: Path, needle: str) -> list[str]:
    return [str(path) for path in sorted(Path(root).rglob('*')) if path.is_file() and needle.encode() in path.read_bytes()]


def cli_command(result: dict) -> str:
    """CLITranslator 的缓存身份就是这条命令串（翻译器初始化失败时取自实际后端 argv）。"""
    if 'cache_params' in result:
        return json.loads(result['cache_params'])['clitranslator_command']
    argv = result['argv']
    return argv[argv.index('--clitranslator-command') + 1]


def identity_of(result: dict) -> dict | None:
    params = json.loads(result['cache_params']) if 'cache_params' in result else {}
    if 'upstream_identity' in params:
        return params['upstream_identity']
    import shlex
    parts = shlex.split(cli_command(result))
    return json.loads(parts[parts.index('--upstream-identity') + 1]) if '--upstream-identity' in parts else None


# ---------------------------------------------------------------- 身份合同（单元）

def test_identity_normalization_strips_credentials_and_keeps_endpoint_semantics():
    noisy = f'HTTP://user:{MARKER}-URL@LocalHost:80/v1/?api-key={MARKER}-Q&api-version=2024-10&access_token={MARKER}#frag'
    assert ui.normalize_endpoint(noisy) == 'http://localhost/v1?api-version=2024-10'
    assert ui.normalize_endpoint('https://api.example.test:443/v1/') == 'https://api.example.test/v1'
    assert ui.normalize_endpoint('http://127.0.0.1:8001/v1') != ui.normalize_endpoint('http://127.0.0.1:8002/v1')
    identity = ui.build_identity(noisy, 'm', None)
    encoded = ui.encode_identity(identity)
    assert MARKER not in encoded and ui.decode_identity(encoded) == identity
    assert identity['transport'] == 'openai_compatible'
    for bad in ('', '{}', '[1]', json.dumps({**identity, 'kind': 'other'}), json.dumps({**identity, 'version': 2}),
                json.dumps({**identity, 'upstream_base_url': ''})):
        assert ui.decode_identity(bad) is None
    ui.verify_header(None, None)
    ui.verify_header(identity, encoded)
    other = ui.encode_identity(ui.build_identity('http://127.0.0.1:9/v1', 'm', None))
    for bound, header in ((identity, None), (None, encoded), (identity, other), (identity, 'not-json')):
        with pytest.raises(ui.UpstreamIdentityMismatch):
            ui.verify_header(bound, header)


def test_proxy_declares_identity_on_get_and_on_every_response(upstreams, proxy):
    upstream = upstreams('甲')
    proxy.start(upstream, key=MARKER + '-PROXY')
    with urllib.request.urlopen(ui.identity_url(proxy.base_url), timeout=5) as response:
        body, header = response.read().decode(), response.headers.get(ui.IDENTITY_HEADER)
    expected = ui.build_identity(upstream.base_url, MODEL, 'openai_compatible')
    assert ui.decode_identity(body) == expected and ui.decode_identity(header) == expected
    assert MARKER not in body and MARKER not in header
    for method, path in (('GET', '/v1/models'), ('POST', '/v1/unknown')):
        request = urllib.request.Request(proxy.base_url.removesuffix('/v1') + path, data=b'{}' if method == 'POST' else None, method=method)
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        assert caught.value.code == 404 and ui.decode_identity(caught.value.headers.get(ui.IDENTITY_HEADER)) == expected
    assert ui.discover(proxy.base_url) == expected
    assert upstream.calls == []  # 身份查询不触达真实上游


def test_discover_trusts_only_loopback_double6_identity(upstreams):
    plain = upstreams('直连')
    assert ui.discover(plain.base_url) is None  # 回环但不是本项目代理（GET 回模型列表）：按直连处理
    assert [call['path'] for call in plain.calls] == ['/v1/double6/upstream-identity']
    remote_style = upstreams('远端', host='127.0.0.2')
    assert ui.discover(remote_style.base_url) is None and remote_style.calls == []  # 非回环：不探测
    assert ui.discover(f'http://127.0.0.1:{free_port()}/v1', timeout=1) is None  # 连不上


def test_qwen_command_unchanged_for_direct_endpoint(upstreams):
    plain = upstreams('直连')
    args = rpt.build_parser().parse_args(['/tmp/in.pdf', '--model', 'qwen-x', '--base-url', plain.base_url,
                                          '--translator-mode', 'qwen-cli'])
    args.api_key, args.custom_system_prompt = None, 'p'
    assert '--upstream-identity' not in pc.build_qwen_cli_command(args)


# ---------------------------------------------------------------- OpenAI 路线经真实兼容代理

def test_openai_proxy_upstream_swap_same_port_misses_then_rotation_hits(tmp_path, upstreams, proxy):
    a, b = upstreams('甲服务结果'), upstreams('乙服务结果')
    first = probe(tmp_path, 'a1', mode='openai', base=proxy.start(a).base_url)
    assert first['error'] is None and first['outputs'] == ['甲服务结果'] and first['translate_cache_call_count'] == 0
    assert len(a.posts()) == 2  # 健康检查 + 实际文本

    second = probe(tmp_path, 'b1', mode='openai', base=proxy.start(b).base_url)  # 同端口、同模型、同缓存库，换上游
    assert second['error'] is None, second['error']
    assert second['outputs'] == ['乙服务结果'] and second['translate_cache_call_count'] == 0
    assert len(b.posts()) == 2 and second['cache_params'] != first['cache_params']
    assert identity_of(first)['upstream_base_url'] == a.base_url and identity_of(second)['upstream_base_url'] == b.base_url
    assert json.loads(first['cache_params'])['base_url'] == json.loads(second['cache_params'])['base_url'] == proxy.base_url

    # 同一上游/模型/方向/提示词，仅凭据轮换（代理持有的上游凭据与子进程占位都换）：必须命中甲的条目。
    rotated = probe(tmp_path, 'a2', mode='openai', base=proxy.start(a, key=MARKER + '-PROXY-TWO').base_url, key='local-no-auth')
    assert rotated['error'] is None and rotated['outputs'] == ['甲服务结果'] and rotated['translate_cache_call_count'] == 1
    assert rotated['cache_params'] == first['cache_params'] and len(a.posts()) == 3  # 只多一次健康检查
    assert a.posts()[-1]['auth_sha256'] == sha('Bearer ' + MARKER + '-PROXY-TWO')
    assert a.posts()[0]['auth_sha256'] == sha('Bearer ' + MARKER + '-PROXY-ONE')
    back = probe(tmp_path, 'b2', mode='openai', base=proxy.start(b).base_url)
    assert back['outputs'] == ['乙服务结果'] and back['translate_cache_call_count'] == 1 and len(b.posts()) == 3

    translations = {row[3] for row in rows(tmp_path) if row[2] == TEXT}
    assert translations == {'甲服务结果', '乙服务结果'}
    assert not [row for row in rows(tmp_path) if MARKER in row[1] or MARKER in row[3]]
    assert scan(tmp_path / 'home', MARKER) == [] and scan(tmp_path, MARKER) == []


def test_openai_proxy_model_direction_and_prompt_changes_miss(tmp_path, upstreams, proxy):
    a = upstreams('甲服务结果')
    base = probe(tmp_path, 'base', mode='openai', base=proxy.start(a).base_url)
    assert base['translate_cache_call_count'] == 0
    other_model = probe(tmp_path, 'model', mode='openai', base=proxy.start(a, model='hy-mt-other').base_url, model='hy-mt-other')
    assert other_model['translate_cache_call_count'] == 0 and other_model['cache_params'] != base['cache_params']
    assert a.posts()[-1]['model'] == 'hy-mt-other'
    proxy.start(a)
    direction = probe(tmp_path, 'en', mode='openai', base=proxy.base_url, extra={'extra_args': ['--target-language', 'en']})
    assert direction['translate_cache_call_count'] == 0 and direction['cache_params'] != base['cache_params']
    assert json.loads(direction['cache_params'])['lang_out'] == 'en'
    # 文档级提示词经 llm_translate 的完整提示进入缓存键：同一源文、不同提示词必须重新请求。
    prompts = [f'{prompt}\nNow translate the following text:\n{TEXT}' for prompt in ('Style: formal.', 'Style: casual.')]
    before = len(a.posts())
    first_prompt = probe(tmp_path, 'p1', mode='openai', base=proxy.base_url, texts=(), extra={'llm_texts': prompts[:1]})
    second_prompt = probe(tmp_path, 'p2', mode='openai', base=proxy.base_url, texts=(), extra={'llm_texts': prompts})
    assert first_prompt['error'] is None and second_prompt['error'] is None, (first_prompt['error'], second_prompt['error'])
    assert first_prompt['translate_cache_call_count'] == 0 and second_prompt['translate_cache_call_count'] == 1
    assert len(a.posts()) == before + 2 + 2  # 两次健康检查 + p1 一次 + p2 只为新提示词请求一次
    assert scan(tmp_path, MARKER) == []


def test_openai_upstream_swapped_mid_run_fails_closed(tmp_path, upstreams, proxy):
    a, b = upstreams('甲服务结果'), upstreams('乙服务结果')
    ready, go = tmp_path / 'ready', tmp_path / 'go'
    child, work = probe(tmp_path, 'mid', mode='openai', base=proxy.start(a).base_url,
                        extra={'pause': {'ready': str(ready), 'go': str(go)}}, wait=False)
    deadline = time.monotonic() + 60
    while not ready.exists() and time.monotonic() < deadline and child.poll() is None:
        time.sleep(0.05)
    assert ready.exists()
    proxy.start(b)  # 绑定甲之后，同一端口被换成代理到乙
    go.write_text('go')
    result = finish(child, work)
    assert result['error'] is not None and result['outputs'] == []
    assert ui.UPSTREAM_IDENTITY_MISMATCH in (work / 'backend.log').read_text()
    assert not [row for row in rows(tmp_path) if row[2] == TEXT]  # 乙的回答未写入甲的缓存身份
    assert scan(tmp_path, MARKER) == []


# ---------------------------------------------------------------- qwen-cli 适配器路线

def test_qwen_adapter_via_real_compat_proxy_binds_identity_and_never_reuses(tmp_path, upstreams, proxy):
    """兼容代理只接受后端的源文边界协议，适配器请求被其拒绝（既有失败关闭，400）；这里证明身份仍按真实上游区分、
    换上游后不会出现跨服务复用（没有任何译文被写入缓存）。"""
    a, b = upstreams('甲服务结果'), upstreams('乙服务结果')
    first = probe(tmp_path, 'qa', mode='qwen-cli', base=proxy.start(a).base_url)
    second = probe(tmp_path, 'qb', mode='qwen-cli', base=proxy.start(b).base_url)
    assert identity_of(first)['upstream_base_url'] == a.base_url and identity_of(second)['upstream_base_url'] == b.base_url
    assert cli_command(first) != cli_command(second)
    assert 'Qwen CLI translator HTTP 400' in (tmp_path / 'qa/backend.log').read_text()
    assert first['error'] is not None and second['error'] is not None and first['outputs'] == second['outputs'] == []
    assert a.posts() == [] and b.posts() == [] and rows(tmp_path) == []
    assert scan(tmp_path, MARKER) == []


class Relay(ThreadingHTTPServer):
    """按本项目身份合同工作的透传回环中间层（测试侧实现）：同一固定端口先后转发到不同真实上游。"""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, upstream: Upstream, model: str):
        super().__init__(('127.0.0.1', port), _RelayHandler)
        self.upstream = upstream
        self.identity = ui.encode_identity(ui.build_identity(upstream.base_url, model, 'openai_compatible'))
        threading.Thread(target=self.serve_forever, daemon=True).start()


class _RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def end_headers(self):
        self.send_header(ui.IDENTITY_HEADER, self.server.identity)
        super().end_headers()

    def _send(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith(ui.IDENTITY_PATH):
            return self._send(200, self.server.identity.encode())
        self._send(404, b'{}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        headers = {'Content-Type': 'application/json'}
        if self.headers.get('Authorization'):
            headers['Authorization'] = self.headers['Authorization']
        url = self.server.upstream.base_url + self.path.removeprefix('/v1')
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method='POST'), timeout=10) as response:
            self._send(response.status, response.read())


@pytest.fixture
def relay():
    state = {'server': None, 'port': free_port()}

    def start(upstream: Upstream, model: str = MODEL) -> str:
        if state['server'] is not None:
            state['server'].shutdown()
            state['server'].server_close()
        state['server'] = Relay(state['port'], upstream, model)
        return f'http://127.0.0.1:{state["port"]}/v1'
    yield start
    if state['server'] is not None:
        state['server'].shutdown()
        state['server'].server_close()


def test_qwen_adapter_via_identity_relay_swap_rotation_model_prompt(tmp_path, upstreams, relay):
    a, b = upstreams('甲服务结果'), upstreams('乙服务结果')
    first = probe(tmp_path, 'a1', mode='qwen-cli', base=relay(a), key=MARKER + '-ONE')
    assert first['error'] is None and first['outputs'] == ['甲服务结果'] and first['translate_cache_call_count'] == 0
    second = probe(tmp_path, 'b1', mode='qwen-cli', base=relay(b), key=MARKER + '-ONE')  # 同端口换上游
    assert second['error'] is None and second['outputs'] == ['乙服务结果'] and second['translate_cache_call_count'] == 0
    assert len(b.posts()) == 2 and second['cache_params'] != first['cache_params']
    rotated = probe(tmp_path, 'a2', mode='qwen-cli', base=relay(a), key=MARKER + '-TWO')  # 仅凭据轮换
    assert rotated['outputs'] == ['甲服务结果'] and rotated['translate_cache_call_count'] == 1
    assert rotated['cache_params'] == first['cache_params'] and len(a.posts()) == 3
    assert a.posts()[-1]['auth_sha256'] == sha('Bearer ' + MARKER + '-TWO')
    model = probe(tmp_path, 'm', mode='qwen-cli', base=relay(a, 'hy-mt-other'), model='hy-mt-other', key=MARKER + '-ONE')
    assert model['translate_cache_call_count'] == 0 and a.posts()[-1]['model'] == 'hy-mt-other'
    prompt = probe(tmp_path, 'p', mode='qwen-cli', base=relay(a), key=MARKER + '-ONE',
                   extra={'custom_system_prompt': 'Translate to Simplified Chinese, formal register.'})
    assert prompt['translate_cache_call_count'] == 0 and prompt['cache_params'] != first['cache_params']
    direction = probe(tmp_path, 'en', mode='qwen-cli', base=relay(a), key=MARKER + '-ONE',
                      extra={'extra_args': ['--target-language', 'en']})
    assert direction['translate_cache_call_count'] == 0 and direction['cache_params'] != first['cache_params']
    assert not [row for row in rows(tmp_path) if MARKER in row[1] or MARKER in row[3]]
    assert scan(tmp_path / 'home', MARKER) == [] and scan(tmp_path, MARKER) == []


def test_qwen_adapter_upstream_swapped_mid_run_fails_closed(tmp_path, upstreams, relay):
    a, b = upstreams('甲服务结果'), upstreams('乙服务结果')
    ready, go = tmp_path / 'ready', tmp_path / 'go'
    child, work = probe(tmp_path, 'mid', mode='qwen-cli', base=relay(a), timeout=5,
                        extra={'pause': {'ready': str(ready), 'go': str(go)}}, wait=False)
    deadline = time.monotonic() + 60
    while not ready.exists() and time.monotonic() < deadline and child.poll() is None:
        time.sleep(0.05)
    assert ready.exists()
    relay(b)
    go.write_text('go')
    result = finish(child, work)
    assert result['error'] is not None and result['outputs'] == []
    assert ui.UPSTREAM_IDENTITY_MISMATCH in (work / 'backend.log').read_text()
    assert not [row for row in rows(tmp_path) if row[2] == TEXT]
