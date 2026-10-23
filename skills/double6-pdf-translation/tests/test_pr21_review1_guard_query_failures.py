"""PR #21 review-1：进程属性/枚举查询失败不能被当作“已清理”。

* 审稿复现（root / orphan × 正常查询 / 本任务 PID 的 environ AccessDenied）：查询失败时 post_attempt_guard 与
  reclaim_stale 必须 confirmed=False、unverified 非空，且不对归属未知的进程发信号；正常查询仍回收本任务进程，
  无关进程继续写。
* 相邻同类缺口：run_bounded 运行期组外孤儿 environ 读不到（不再静默跳过）、恢复扫描 ppid/create_time 查询失败、
  墙钟回拨后带本次 nonce 但 create_time 早于根进程的后代、僵尸/其它用户进程不计为未知、回执缺字段、
  全机 nonce 扫描不完整时守卫不受影响、resume 遇未核实失败关闭。
* PR #19 第 10 轮真实多跳父链用例的加固副本（原文件属于原 34 项独立测试，不改动）：标记文件原子发布、
  只读完整 JSON；启动后每一步都在 try/finally 内；真实覆盖未知时接受严格 unconfirmed（unverified 非空）。"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'tests'))
import bounded_execution as be  # noqa: E402
import chunked_workflow as cw  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='process groups / recovery scan are POSIX only')
GIB = 1024 ** 3

# ---------------------------------------------------------------- 共用：原子标记文件
PUBLISH = '''
def publish(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)
'''


def read_marker(path, timeout=10.0):
    """只读完整 JSON：文件由写入方原子替换发布；读到不完整内容视为尚未发布。"""
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
    raise AssertionError(f'marker not published: {path}')


def alive(ident):
    try:
        p = psutil.Process(ident['pid'])
        return abs(p.create_time() - ident['created_at']) < be.IDENTITY_TOLERANCE and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def growth(path, wait=0.25):
    a = path.stat().st_size if path.exists() else 0
    time.sleep(wait)
    return (path.stat().st_size if path.exists() else 0) - a


def reap_all(idents, popens):
    for i in idents:
        if i and alive(i):
            try:
                psutil.Process(i['pid']).kill()
            except psutil.NoSuchProcess:
                pass
    for p in popens:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=5)
    end = time.monotonic() + 3
    while any(i and alive(i) for i in idents) and time.monotonic() < end:
        time.sleep(0.01)
    assert not any(i and alive(i) for i in idents), idents


WRITER = '''import json,os,sys,time
from pathlib import Path
import psutil
''' + PUBLISH + '''
p=Path(sys.argv[1]);q=psutil.Process()
publish(p.with_suffix('.json'),{'pid':q.pid,'created_at':q.create_time()})
for _ in range(3000):
    with p.with_suffix('.ticks').open('a') as f: f.write('tick\\n')
    time.sleep(.01)
'''

LAUNCHER = '''import json,os,sys,subprocess,time
from pathlib import Path
import psutil
''' + PUBLISH + '''
r=Path(sys.argv[1]);p=psutil.Process()
publish(r/'root.json',{'pid':p.pid,'created_at':p.create_time(),'process_group':p.pid,'nonce':os.environ['PAPER_TRANSLATION_BOUNDED_OWNERS']})
subprocess.Popen([sys.executable,str(r/'writer.py'),str(r/'owned')],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while not (r/'owned.json').exists(): time.sleep(.01)
'''


def _deny_environ(monkeypatch, pids):
    original = psutil.Process.environ

    def environ(proc):
        if proc.pid in pids():
            raise psutil.AccessDenied(proc.pid)
        return original(proc)
    monkeypatch.setattr(psutil.Process, 'environ', environ)


# ---------------------------------------------------------------- 1) 审稿复现：root / orphan × 正常 / environ 拒绝
@pytest.mark.parametrize('shape', ['root', 'orphan'])
@pytest.mark.parametrize('deny', [False, True], ids=['normal', 'owned-environ-denied'])
def test_review1_owned_query_failure_is_not_clean(tmp_path, monkeypatch, shape, deny):
    (tmp_path / 'writer.py').write_text(WRITER)
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    nonce = 'independent-' + uuid.uuid4().hex
    env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}
    quiet = dict(start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    popens, ids = [], []
    try:
        popens.append(subprocess.Popen([sys.executable, str(tmp_path / 'writer.py'), str(tmp_path / 'unrelated')], env=env, **quiet))
        unrelated = read_marker(tmp_path / 'unrelated.json'); ids.append(unrelated)
        if shape == 'root':
            owner = subprocess.Popen([sys.executable, str(tmp_path / 'writer.py'), str(tmp_path / 'owned')],
                                     env={**env, be.OWNER_ENV: nonce}, **quiet)
            popens.append(owner)
            owned = read_marker(tmp_path / 'owned.json'); ids.append(owned)
            identity = {**owned, 'process_group': owner.pid, 'nonce': nonce}
        else:
            (tmp_path / 'launcher.py').write_text(LAUNCHER)
            owner = subprocess.Popen([sys.executable, str(tmp_path / 'launcher.py'), str(tmp_path)],
                                     env={**env, be.OWNER_ENV: nonce}, **quiet)
            popens.append(owner)
            identity = read_marker(tmp_path / 'root.json'); ids.append(identity)
            owned = read_marker(tmp_path / 'owned.json'); ids.append(owned)
            owner.wait(timeout=5)
            assert not alive(identity)                       # 根已退出、原组空，孤儿脱组且标准流已关闭
            assert be._group_empty(identity['process_group']) is True
        (attempt / 'candidate.launch.json').write_text(json.dumps(identity))
        assert alive(owned)
        if deny:
            _deny_environ(monkeypatch, lambda: {owned['pid']})
        result = cw.post_attempt_guard(attempt) if shape == 'root' else cw.reclaim_stale([attempt])
        monkeypatch.undo()
        time.sleep(0.03)
        audit = {'shape': shape, 'deny': deny, 'guard': result, 'owned_alive': alive(owned),
                 'owned_growth': growth(tmp_path / 'owned.ticks', 0), 'unrelated_alive': alive(unrelated)}
        own_g, other_g = growth(tmp_path / 'owned.ticks'), growth(tmp_path / 'unrelated.ticks')
        audit.update(owned_growth=own_g, unrelated_growth=other_g, owned_alive=alive(owned))
        (tmp_path / 'GUARD_AUDIT.json').write_text(json.dumps(audit, indent=2, default=str))
        assert audit['unrelated_alive'] and other_g > 0, audit                  # 无关进程不受影响
        assert not (result['confirmed'] and (audit['owned_alive'] or own_g > 0)), audit
        if result['confirmed'] is False:
            assert result['unverified'], audit                                  # 未核实必须写明原因
        if not deny:
            assert not audit['owned_alive'] and own_g == 0, audit              # 正常查询：真实回收
        elif shape == 'root':
            # 已知可信根仍按 PID + create_time 回收（不依赖环境变量）
            assert not audit['owned_alive'] and own_g == 0, audit
        else:
            # 归属未知的孤儿：不发信号（不扩大误杀范围），整树未核实，失败关闭
            assert result['confirmed'] is False and 'ownership_unknown' in result['reason_codes'], audit
            assert audit['owned_alive'] and own_g > 0, audit
    finally:
        reap_all(ids, popens)


# ---------------------------------------------------------------- 2) run_bounded：运行期组外孤儿 environ 读不到
ORPHAN_TASK = '''import json,os,sys,subprocess,time
from pathlib import Path
d=Path(sys.argv[1])
# 双重 fork：中间进程启动孤儿后立即退出，孤儿脱离会话/进程组、标准流关闭、被重新收养。
mid="import subprocess,sys; subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],start_new_session=True,close_fds=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
subprocess.Popen([sys.executable,'-c',mid,str(d/'writer.py'),str(d/'orphan')],start_new_session=True,close_fds=True,
                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).wait()
while not (d/'orphan.json').exists(): time.sleep(.01)
'''


def _orphan_pids(marker):
    try:
        return {json.loads(marker.read_text())['pid']}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    found = set()   # 标记尚未发布时按命令行识别（只用于注入拒绝，不用于断言）
    for proc in psutil.process_iter():
        try:
            if str(marker.with_suffix('')) in ' '.join(proc.cmdline()):
                found.add(proc.pid)
        except psutil.Error:
            continue
    return found


@pytest.mark.parametrize('deny', [False, True], ids=['normal', 'orphan-environ-denied'])
def test_run_bounded_detached_orphan_with_unreadable_environ_is_unconfirmed(tmp_path, monkeypatch, deny):
    (tmp_path / 'writer.py').write_text(WRITER)
    (tmp_path / 'task.py').write_text(ORPHAN_TASK)
    marker = tmp_path / 'orphan.json'
    ids = []
    try:
        if deny:
            _deny_environ(monkeypatch, lambda: _orphan_pids(marker))
        outcome = be.run_bounded([sys.executable, str(tmp_path / 'task.py'), str(tmp_path)], cwd=tmp_path,
                                 receipt_dir=tmp_path / 'receipts', operation='orphan', timeout_seconds=20,
                                 interval_seconds=0.1, rss_limit=GIB, memory_metric='rss')
        monkeypatch.undo()
        orphan = read_marker(marker); ids.append(orphan)
        cleanup = outcome['cleanup']
        (tmp_path / 'OUTCOME.json').write_text(json.dumps(outcome, indent=2, default=str))
        orphan_alive, orphan_growth = alive(orphan), growth(tmp_path / 'orphan.ticks')
        assert not (cleanup['confirmed'] and (orphan_alive or orphan_growth > 0)), outcome     # 绝不误报已清理
        if not deny:
            assert cleanup['confirmed'] is True and not orphan_alive, cleanup
            assert outcome['ownership_unknown_during_run'] == []
        elif cleanup['confirmed']:
            # 运行期采样恰在孤儿仍挂在父链上时取到：作为已确认成员按身份回收（合法路径，必须真的已死）。
            observed = {row['pid'] for row in outcome['observed_owned_identities']}
            assert orphan['pid'] in observed and not orphan_alive, outcome
        else:
            assert outcome['status'] == 'cleanup_unconfirmed', outcome
            assert any(r.get('reason') == 'ownership_unknown' and r.get('pid') == orphan['pid']
                       for r in cleanup['unverified']), cleanup['unverified']
            assert orphan['pid'] not in {r['pid'] for r in cleanup['signalled']}   # 不对归属未知的进程发信号
            assert orphan_alive and orphan_growth > 0
            assert json.loads(Path(outcome['failure_receipt']).read_text())['failure_code'] == 'owned_tree_cleanup_unconfirmed'
    finally:
        monkeypatch.undo()
        reap_all(ids, [])


# ---------------------------------------------------------------- 3) 恢复扫描：逐项查询失败（模拟进程表，spy 截获信号）
class FakeTable:
    """pid -> {created_at, ppid, env, status, uid, fail: {method: exc}}；spy 发信号时标记退出。"""

    def __init__(self, rows):
        self.rows = {pid: dict(row) for pid, row in rows.items()}
        self.signals = []

    def install(self, monkeypatch):
        table = self

        class P:
            def __init__(self, pid):
                if pid not in table.rows:
                    raise psutil.NoSuchProcess(pid)
                self.pid = pid

            def _get(self, method, field, default):
                row = table.rows.get(self.pid)
                if row is None:
                    raise psutil.NoSuchProcess(self.pid)
                fail = row.get('fail', {}).get(method)
                if fail is not None:
                    raise fail(self.pid)
                return row.get(field, default)

            def create_time(self):
                return self._get('create_time', 'created_at', 0.0)

            def status(self):
                return self._get('status', 'status', psutil.STATUS_RUNNING)

            def ppid(self):
                return self._get('ppid', 'ppid', 1)

            def environ(self):
                return self._get('environ', 'env', {})

            def uids(self):
                return type('U', (), {'real': self._get('uids', 'uid', os.getuid())})()

        def signal_pid(proc, created_at, sig):
            table.signals.append(proc.pid)
            table.rows.pop(proc.pid, None)

        monkeypatch.setattr(be.psutil, 'Process', P)
        monkeypatch.setattr(be, '_enumerate_all_pids', lambda: (sorted(table.rows), 'fake', [{'method': 'fake', 'ok': True}]))
        monkeypatch.setattr(be, '_signal_pid', signal_pid)
        monkeypatch.setattr(be.os, 'killpg', lambda pgid, sig: (_ for _ in ()).throw(ProcessLookupError(pgid)))
        return self


NONCE = 'abad1dea' * 4
ROOT = 93000001
IDENT = {'pid': ROOT, 'created_at': 100.0, 'process_group': None, 'nonce': NONCE}


def _scan(rows, monkeypatch, known=None):
    FakeTable(rows).install(monkeypatch)
    return be._recovery_scan(IDENT, known or {ROOT: 100.0}, NONCE, False, 'review1')


def _unknown(scan):
    return {row['pid'] for row in scan['ownership_unknown']}


def test_scan_ppid_access_denied_is_ownership_unknown(monkeypatch):
    scan = _scan({ROOT: {'created_at': 100.0},
                  93000002: {'created_at': 110.0, 'env': {}, 'fail': {'ppid': psutil.AccessDenied}}}, monkeypatch)
    assert _unknown(scan) == {93000002} and scan['owned_found'] == []


def test_scan_readable_ppid_to_unrelated_parent_is_not_unknown(monkeypatch):
    scan = _scan({ROOT: {'created_at': 100.0}, 93000002: {'created_at': 110.0, 'env': {}, 'ppid': 1}}, monkeypatch)
    assert _unknown(scan) == set() and scan['owned_found'] == []


@pytest.mark.parametrize('uid_offset,expect', [(0, {93000002}), (1, set())], ids=['same-user', 'other-user'])
def test_scan_create_time_denied_counts_only_for_same_user(monkeypatch, uid_offset, expect):
    scan = _scan({ROOT: {'created_at': 100.0},
                  93000002: {'uid': os.getuid() + uid_offset, 'fail': {'create_time': psutil.AccessDenied}}}, monkeypatch)
    assert _unknown(scan) == expect


@pytest.mark.parametrize('status,expect', [(psutil.STATUS_RUNNING, {93000002}), (psutil.STATUS_ZOMBIE, set())],
                         ids=['running', 'zombie'])
def test_scan_environ_denied_zombie_is_not_unknown(monkeypatch, status, expect):
    scan = _scan({ROOT: {'created_at': 100.0},
                  93000002: {'created_at': 110.0, 'ppid': 1, 'status': status, 'fail': {'environ': psutil.AccessDenied}}},
                 monkeypatch)
    assert _unknown(scan) == expect


def test_clock_step_back_descendant_with_nonce_is_owned_and_reclaimed(monkeypatch):
    # 墙钟回拨：本次后代 create_time 看起来早于根进程（btime 后移），但环境里有本次 nonce → 正面所属。
    t = FakeTable({93000002: {'created_at': 40.0, 'ppid': 1, 'env': {be.OWNER_ENV: NONCE}}}).install(monkeypatch)
    report = be.reclaim_owned_tree(IDENT, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signals == [93000002] and report['confirmed'] is True, report


@pytest.mark.parametrize('env', [{be.OWNER_ENV: 'other' * 6}, None], ids=['older-other-nonce', 'older-unreadable'])
def test_older_process_without_this_nonce_is_neither_owned_nor_unknown(monkeypatch, env):
    row = {'created_at': 40.0, 'ppid': 1, 'env': env or {}}
    if env is None:
        row['fail'] = {'environ': psutil.AccessDenied}
    t = FakeTable({93000002: row}).install(monkeypatch)
    report = be.reclaim_owned_tree(IDENT, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signals == [] and report['confirmed'] is True, report


def test_launched_members_reports_unreadable_out_of_group_process(monkeypatch, tmp_path):
    ident = {'pid': ROOT, 'created_at': 100.0, 'process_group': ROOT, 'nonce': NONCE, 'parent_pid': os.getpid()}
    path = tmp_path / 'op.launch.json'; path.write_text(json.dumps(ident))
    FakeTable({ROOT: {'created_at': 100.0},
               93000002: {'created_at': 110.0, 'env': {be.OWNER_ENV: NONCE}},                 # 组外、带 nonce：成员
               93000003: {'created_at': 110.0, 'fail': {'environ': psutil.AccessDenied}},      # 组外、读不到：未知
               93000004: {'created_at': 110.0, 'env': {}},                                      # 无关
               93000005: {'created_at': 110.0, 'status': psutil.STATUS_ZOMBIE, 'fail': {'environ': psutil.AccessDenied}},
               93000006: {'created_at': 110.0, 'uid': os.getuid() + 1, 'fail': {'environ': psutil.AccessDenied}}},
              ).install(monkeypatch)
    monkeypatch.setattr(be.psutil, 'pids', lambda: [ROOT, 93000002, 93000003, 93000004, 93000005, 93000006])
    monkeypatch.setattr(be.psutil.Process, 'children', lambda self, recursive=False: [], raising=False)
    monkeypatch.setattr(be.os, 'getpgid', lambda pid: pid)
    unknown = []
    _, members = be.launched_members(path, NONCE, unknown)
    assert {p.pid for p in members} == {ROOT, 93000002}
    assert [row['pid'] for row in unknown] == [93000003]


# ---------------------------------------------------------------- 4) 分块守卫 / resume
def test_reclaim_stale_receipt_missing_fields_is_unverified(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'a/candidate.launch.json').write_text(json.dumps({'nonce': NONCE}))
    report = cw.reclaim_stale([tmp_path])
    assert report['confirmed'] is False and report['unverified']
    assert report['reason_codes'] == ['receipt_verification_error']


def test_post_attempt_guard_does_not_depend_on_the_global_nonce_scan(tmp_path, monkeypatch):
    # 全机 nonce 扫描不完整/为空（例如读不到环境）时，守卫仍逐张回执核实并回收带本次 nonce 的真实孤儿。
    (tmp_path / 'writer.py').write_text(WRITER); (tmp_path / 'launcher.py').write_text(LAUNCHER)
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    nonce = 'independent-' + uuid.uuid4().hex
    env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}
    ids, popens = [], []
    try:
        owner = subprocess.Popen([sys.executable, str(tmp_path / 'launcher.py'), str(tmp_path)], env={**env, be.OWNER_ENV: nonce},
                                 start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        popens.append(owner)
        identity = read_marker(tmp_path / 'root.json'); ids.append(identity)
        owned = read_marker(tmp_path / 'owned.json'); ids.append(owned)
        owner.wait(timeout=5)
        (attempt / 'candidate.launch.json').write_text(json.dumps(identity))
        monkeypatch.setattr(cw, 'owner_nonce_scan', lambda: {'complete': False, 'nonces': set(), 'unreadable': 0, 'method': None})
        report = cw.post_attempt_guard(attempt)
        assert report['confirmed'] is True and report['unverified'] == [], report
        assert not alive(owned) and growth(tmp_path / 'owned.ticks') == 0
        assert report['reclaim']['reclaimed'][0]['root_state'] == 'dead'
    finally:
        reap_all(ids, popens)


def test_post_attempt_guard_unconfirmed_always_carries_unverified(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, 'reclaim_stale', lambda roots: {'confirmed': False, 'reclaimed': [], 'receipts_scanned': 1, 'already_gone': 0})
    report = cw.post_attempt_guard(tmp_path)
    assert report['confirmed'] is False and report['unverified'] and report['reason_codes'] == ['reclaim_unconfirmed']


from test_chunked_translation import FakeChunkRunner, _main, chunked_args, long_doc, wf  # noqa: E402,F401


def test_resume_fails_closed_when_stale_tree_is_unverifiable(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    blocked = dict(wf.blocked_result([wf.finding('x', 'transient env problem')]), error_code='x')
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c002': blocked}))
    assert _main(chunked_args(tmp_path, pdf, freeze_path), capsys)[0] == wf.EXIT_BLOCKED
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    unverified = [{'pid': 1234, 'reason': 'ownership_unknown', 'error': 'AccessDenied'}]
    monkeypatch.setattr(cw, 'reclaim_stale', lambda roots: {'protocol': cw.GUARD_PROTOCOL, 'confirmed': False, 'receipts_scanned': 3,
                                                            'reclaimed': [], 'already_gone': 2, 'unverified': unverified,
                                                            'reason_codes': ['ownership_unknown']})
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == wf.EXIT_BLOCKED and result['error_code'] == 'owned_tree_cleanup_unconfirmed' and runner.calls == []
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    assert state['invocations'][-1]['stale_reclaim']['unverified'] == 1
    assert state['invocations'][-1]['stale_reclaim']['reason_codes'] == ['ownership_unknown']


def test_resume_proceeds_after_a_verified_clean_stale_scan(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    blocked = dict(wf.blocked_result([wf.finding('x', 'transient env problem')]), error_code='x')
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c002': blocked}))
    assert _main(chunked_args(tmp_path, pdf, freeze_path), capsys)[0] == wf.EXIT_BLOCKED
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)   # 真实 reclaim_stale
    assert code == 0 and runner.calls == ['c002']
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    stale = state['invocations'][-1]['stale_reclaim']
    assert stale['confirmed'] is True and stale['unverified'] == 0 and stale['receipts_scanned'] == stale['already_gone']


# ---------------------------------------------------------------- 5) PR #19 第 10 轮真实多跳父链：加固副本
CHAIN = '''import os, sys, time, json, subprocess
from pathlib import Path
import psutil
''' + PUBLISH + '''
level, d = int(sys.argv[1]), Path(sys.argv[2])
p = psutil.Process()
publish(d / f"l{level}.json", {"pid": p.pid, "created_at": p.create_time(), "ppid": p.ppid()})
if level < 3:
    subprocess.Popen([sys.executable, __file__, str(level + 1), str(d)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(3000):
    with (d / f"l{level}.ticks").open("a") as f: f.write("t\\n")
    time.sleep(0.02)
'''


def test_real_multi_hop_chain_hardened_handshake(tmp_path):
    (tmp_path / 'chain.py').write_text(CHAIN)
    env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}   # 无 nonce：只能靠父链
    chain, popens, u_ident = [], [], None
    try:
        root = subprocess.Popen([sys.executable, str(tmp_path / 'chain.py'), '0', str(tmp_path)], start_new_session=True,
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        popens.append(root)
        threading.Thread(target=root.wait, daemon=True).start()
        for i in range(4):
            chain.append(read_marker(tmp_path / f'l{i}.json'))
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True, env=env)
        popens.append(unrelated)
        u_ident = {'pid': unrelated.pid, 'created_at': psutil.Process(unrelated.pid).create_time()}
        identity = {'pid': chain[0]['pid'], 'created_at': chain[0]['created_at'], 'process_group': None}
        report = be.reclaim_owned_tree(identity, {chain[0]['pid']: chain[0]['created_at']}, discovery_failed=True, nonce=NONCE)
        assert all(not alive(c) for c in chain), chain                                   # 真实死亡
        ticks = [tmp_path / f'l{i}.ticks' for i in range(4)]
        a = [p.stat().st_size for p in ticks]; time.sleep(0.3); b = [p.stat().st_size for p in ticks]
        assert a == b                                                                     # 停止写入
        assert alive(u_ident), 'unrelated process was signalled'                          # 无关隔离
        found = {row['pid']: row['match'] for row in report['recovered_members']}
        assert all(found.get(c['pid']) == 'ancestry' for c in chain[1:]), report['recovered_members']   # 父链归属
        assert unrelated.pid not in {row['pid'] for row in report['signalled']}
        if report['confirmed'] is not True:
            # 真实覆盖未知（例如机器上其它同用户进程 environ 读不到）：接受严格 unconfirmed，但必须写明原因，
            # 且未核实项不能是链上仍存活的进程。
            assert report['unverified'], report
            chain_pids = {c['pid'] for c in chain}
            assert not any(r.get('pid') in chain_pids and r.get('reason') == 'still_alive' for r in report['unverified']), report
            assert {r.get('reason') for r in report['unverified']} <= {'ownership_unknown', 'ownership_unverifiable'}, report
    finally:
        reap_all(chain + ([u_ident] if u_ident else []), [p for p in popens if p is not popens[0]] if popens else [])
