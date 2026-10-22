"""PR #19 第 9 轮：枚举失败后不能只靠 not_covered 备注就声明整树已清理。
- 未被发现的脱组后代：能用独立的完整枚举 + 正面归属核验（启动 nonce / 祖先链 / 原进程组）找到时真正回收；
  找不到时必须 cleanup_unconfirmed、unverified 非空、tree_scope.whole_tree_verified=False。
- 只有组回收能覆盖的场景（同组成员从未被发现、完整枚举也失败）单独构造，验证它真实死亡。
- 负例：无关进程（包括运行期间新起、同一用户、带别的 nonce 或不带 nonce 的进程）不被回收；归属读不到的进程只记未核实、不发信号。
每个用例都检查真实进程死亡（PID + create_time + os.kill(pid,0)）、停止写入与回执。"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import bounded_execution as be  # noqa: E402

GIB = 1024 ** 3
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='process-group / recovery reclaim is POSIX only')

WORKER = '''
import sys, os, time, json, subprocess
from pathlib import Path
import psutil
mode, r, kind = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
p = psutil.Process()
(r / (mode + ".json")).write_text(json.dumps({"pid": p.pid, "created_at": p.create_time(), "pgid": os.getpgrp()}))
if mode == "root":
    detached = kind == "detached"
    subprocess.Popen([sys.executable, __file__, "child", str(r), kind], start_new_session=detached,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while not (r / "child.json").exists(): time.sleep(0.01)
    (r / "ready").touch()
for _ in range(3000):
    with (r / (mode + ".ticks")).open("a") as f: f.write("tick\\n")
    time.sleep(0.02)
'''


def _alive(ident):
    try:
        p = psutil.Process(ident['pid'])
        if abs(p.create_time() - ident['created_at']) > 0.01 or p.status() == psutil.STATUS_ZOMBIE:
            return False
    except psutil.NoSuchProcess:
        return False
    try:
        os.kill(ident['pid'], 0)
    except ProcessLookupError:
        return False
    return True


def _kill(idents):
    for ident in idents:
        if ident and _alive(ident):
            proc = psutil.Process(ident['pid'])
            proc.kill()
            try:
                proc.wait(timeout=3)
            except psutil.Error:
                pass


def _growth(paths, wait=0.3):
    a = [p.stat().st_size if p.exists() else 0 for p in paths]
    time.sleep(wait)
    b = [p.stat().st_size if p.exists() else 0 for p in paths]
    return [y - x for x, y in zip(a, b)]


def _spawn_unrelated(tmp_path, name, *, new_session, env=None):
    d = tmp_path / name
    d.mkdir()
    worker = tmp_path / 'worker.py'
    proc = subprocess.Popen([sys.executable, str(worker), 'unrelated', str(d), 'unrelated'], start_new_session=new_session,
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(300):
        if (d / 'unrelated.json').exists():
            break
        time.sleep(0.01)
    return proc, d


def _inject(monkeypatch, tmp_path, *, recovery):
    """子进程确实存在（ready）后才进行第一次发现；之后 children()/pids() 全部失败。
    recovery=False 时连独立的完整枚举也失败（只剩已核验身份与原进程组可用）。"""
    ready = tmp_path / 'ready'
    real_pids, real_children, real_discover = be.psutil.pids, be.psutil.Process.children, be.launched_members

    def pids():
        if ready.exists():
            raise SystemError('pid list unavailable after task started (injected)')
        return real_pids()

    def children(self, *a, **k):
        if ready.exists():
            raise SystemError('child tree unavailable after task started (injected)')
        return real_children(self, *a, **k)

    def discover(*a, **k):
        limit = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < limit:
            time.sleep(0.01)
        return real_discover(*a, **k)

    monkeypatch.setattr(be.psutil, 'pids', pids)
    monkeypatch.setattr(be.psutil.Process, 'children', children)
    monkeypatch.setattr(be, 'launched_members', discover)
    if not recovery:
        def no_enumeration():
            raise SystemError('full process enumeration unavailable (injected)')
        monkeypatch.setattr(be, '_enumerate_all_pids', no_enumeration, raising=False)


def _run(tmp_path, kind):
    worker = tmp_path / 'worker.py'
    return be.run_bounded([sys.executable, str(worker), 'root', str(tmp_path), kind], cwd=tmp_path,
                          receipt_dir=tmp_path / 'receipts', operation='tree', timeout_seconds=15,
                          interval_seconds=0.1, rss_limit=GIB, memory_metric='rss')


def _records(tmp_path):
    return [json.loads((tmp_path / f'{n}.json').read_text()) if (tmp_path / f'{n}.json').exists() else None
            for n in ('root', 'child')]


@pytest.fixture
def worker(tmp_path):
    (tmp_path / 'worker.py').write_text(WORKER)
    return tmp_path / 'worker.py'


def test_unseen_detached_child_without_enumeration_is_unconfirmed(monkeypatch, tmp_path, worker):
    """评审复现：子进程 setsid 脱组、DEVNULL、持续写；首次发现前已存在；之后所有枚举失败。
    它仍活着，因此回执必须是 cleanup_unconfirmed、unverified 非空、整树未核实；已确认成员与原进程组的回收分别记录。"""
    _inject(monkeypatch, tmp_path, recovery=False)
    unrelated, ud = _spawn_unrelated(tmp_path, 'u1', new_session=True)
    root = child = None
    try:
        result = _run(tmp_path, 'detached')
        root, child = _records(tmp_path)
        assert child['pgid'] != root['pgid']
        assert not _alive(root)
        assert result['status'] == 'cleanup_unconfirmed', result
        cleanup = result['cleanup']
        assert cleanup['confirmed'] is False and cleanup['status'] == 'unconfirmed'
        assert cleanup['unverified'], cleanup
        scope = cleanup['tree_scope']
        assert scope['whole_tree_verified'] is False and scope['reason'] == 'descendant_enumeration_incomplete', scope
        assert scope['known_members_reclaimed'] is True and scope['original_group_empty_verified'] is True, scope
        assert scope['enumeration_failed_during_run'] is True
        assert any(row.get('scope') == 'whole_tree' and row.get('reason') == 'descendant_enumeration_incomplete'
                   for row in cleanup['unverified']), cleanup
        assert root['pid'] in [row['pid'] for row in cleanup['verified_dead']]
        assert 'not_covered' not in cleanup
        receipt = json.loads(Path(result['failure_receipt']).read_text())
        assert receipt['failure_code'] == 'owned_tree_cleanup_unconfirmed'
        assert receipt['metadata']['cleanup']['tree_scope']['whole_tree_verified'] is False
        assert unrelated.poll() is None and _growth([ud / 'unrelated.ticks'])[0] > 0
    finally:
        _kill([root, child])
        unrelated.kill(); unrelated.wait(timeout=3)


def test_unseen_detached_child_reclaimed_by_verified_recovery_scan(monkeypatch, tmp_path, worker):
    """同一场景，但独立的完整枚举可用：按启动 nonce / 祖先链正面核验归属后回收，真实死亡、停止写入、整树已核实。"""
    _inject(monkeypatch, tmp_path, recovery=True)
    unrelated, ud = _spawn_unrelated(tmp_path, 'u1', new_session=True)
    same_group, sd = _spawn_unrelated(tmp_path, 'u2', new_session=False)
    root = child = None
    try:
        result = _run(tmp_path, 'detached')
        root, child = _records(tmp_path)
        assert child['pgid'] != root['pgid']
        assert not _alive(root) and not _alive(child)
        assert _growth([tmp_path / 'root.ticks', tmp_path / 'child.ticks']) == [0, 0]
        cleanup = result['cleanup']
        assert result['status'] == 'stopped' and cleanup['confirmed'] is True, cleanup
        scope = cleanup['tree_scope']
        assert scope['whole_tree_verified'] is True and scope['basis'] == 'recovery_enumeration_after_discovery_failure', scope
        assert scope['enumeration_failed_during_run'] is True
        found = [row for scan in scope['recovery_enumeration']['scans'] for row in scan['owned_found']]
        assert any(row['pid'] == child['pid'] and row['match'] in ('launch_nonce', 'ancestry') for row in found), scope
        assert child['pid'] in [row['pid'] for row in cleanup['verified_dead']]
        assert unrelated.poll() is None and same_group.poll() is None
        assert all(g > 0 for g in _growth([ud / 'unrelated.ticks', sd / 'unrelated.ticks']))
    finally:
        _kill([root, child])
        for proc in (unrelated, same_group):
            proc.kill(); proc.wait(timeout=3)


def test_group_only_reclaim_kills_undiscovered_member(monkeypatch, tmp_path, worker):
    """只有组回收能覆盖：同组子进程从未被发现、完整枚举也失败，不在任何已知列表里。它必须真实死亡、停止写入；
    原进程组核实为空；但整树仍无法核实（枚举失败），所以状态是 cleanup_unconfirmed。"""
    _inject(monkeypatch, tmp_path, recovery=False)
    unrelated, ud = _spawn_unrelated(tmp_path, 'u1', new_session=False)
    root = child = None
    try:
        result = _run(tmp_path, 'same_group')
        root, child = _records(tmp_path)
        assert child['pgid'] == root['pgid'] == root['pid']
        known = {row['pid'] for row in result['observed_owned_identities']}
        assert child['pid'] not in known, 'scenario requires the child to be undiscovered'
        assert not _alive(child) and not _alive(root)
        assert _growth([tmp_path / 'root.ticks', tmp_path / 'child.ticks']) == [0, 0]
        cleanup = result['cleanup']
        assert cleanup['tree_scope']['original_group_empty_verified'] is True, cleanup
        assert cleanup['tree_scope']['whole_tree_verified'] is False
        assert result['status'] == 'cleanup_unconfirmed'
        assert unrelated.poll() is None and _growth([ud / 'unrelated.ticks'])[0] > 0
    finally:
        _kill([root, child])
        unrelated.kill(); unrelated.wait(timeout=3)


def _setsid_root(tmp_path, nonce):
    """直接构造一个“本次启动”的根：自己的会话/进程组，环境里带启动 nonce，再起一个脱组子进程（继承 nonce）。"""
    env = dict(os.environ, PAPER_TRANSLATION_BOUNDED_OWNERS=nonce)
    root = subprocess.Popen([sys.executable, str(tmp_path / 'worker.py'), 'root', str(tmp_path), 'detached'],
                            start_new_session=True, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=root.wait, daemon=True).start()   # 与 run_command 一样及时回收根进程（不留僵尸占着进程组）
    for _ in range(500):
        if (tmp_path / 'ready').exists():
            break
        time.sleep(0.01)
    r, c = _records(tmp_path)
    identity = {'pid': r['pid'], 'created_at': r['created_at'], 'process_group': r['pid'], 'nonce': nonce}
    return root, r, c, identity


def test_recovery_scan_kills_only_positively_owned(tmp_path, worker):
    """运行期间新起、同一用户的进程：带别的 nonce、不带 nonce、与测试同组，都不是本任务——不得被回收。
    带本次 nonce 的脱组子进程才被回收。"""
    nonce = 'feedfacecafebeef0123456789abcdef'
    root, r, c, identity = _setsid_root(tmp_path, nonce)
    other_env = dict(os.environ, PAPER_TRANSLATION_BOUNDED_OWNERS='0' * 32)
    plain_env = {k: v for k, v in os.environ.items() if k != 'PAPER_TRANSLATION_BOUNDED_OWNERS'}
    lookalikes = [_spawn_unrelated(tmp_path, 'other_nonce', new_session=True, env=other_env),
                  _spawn_unrelated(tmp_path, 'no_nonce', new_session=True, env=plain_env),
                  _spawn_unrelated(tmp_path, 'pytest_group', new_session=False, env=plain_env)]
    try:
        report = be.reclaim_owned_tree(identity, {r['pid']: r['created_at']}, discovery_failed=True, nonce=nonce)
        assert not _alive(r) and not _alive(c)
        assert _growth([tmp_path / 'root.ticks', tmp_path / 'child.ticks']) == [0, 0]
        for proc, d in lookalikes:
            assert proc.poll() is None, f'unrelated {d.name} was signalled'
        assert all(g > 0 for g in _growth([d / 'unrelated.ticks' for _, d in lookalikes]))
        lookalike_pids = {proc.pid for proc, _ in lookalikes}
        signalled = {row['pid'] for row in report['signalled']}
        assert not (signalled & lookalike_pids), report
        assert report['confirmed'] is True and report['tree_scope']['whole_tree_verified'] is True, report
    finally:
        _kill([r, c])
        root.wait(timeout=3)
        for proc, _ in lookalikes:
            proc.kill(); proc.wait(timeout=3)


def test_unreadable_ownership_stays_unverified_and_unsignalled(monkeypatch, tmp_path, worker):
    """归属读不到（environ 无权限）的同用户新进程：不发信号，记为 ownership_unknown，整树未核实。"""
    nonce = 'abad1deaabad1deaabad1deaabad1dea'
    real = be._owner_markers   # 修复前此函数不存在：在启动任何进程之前就失败，不留下进程
    root, r, c, identity = _setsid_root(tmp_path, nonce)
    stranger, sd = _spawn_unrelated(tmp_path, 'stranger', new_session=True)

    def markers(proc):
        if proc.pid == stranger.pid:
            raise psutil.AccessDenied(proc.pid)
        return real(proc)
    monkeypatch.setattr(be, '_owner_markers', markers)
    try:
        report = be.reclaim_owned_tree(identity, {r['pid']: r['created_at']}, discovery_failed=True, nonce=nonce)
        assert not _alive(r) and not _alive(c)
        assert stranger.poll() is None and _growth([sd / 'unrelated.ticks'])[0] > 0
        assert stranger.pid not in {row['pid'] for row in report['signalled']}
        assert any(row.get('pid') == stranger.pid and row['reason'] == 'ownership_unknown' for row in report['unverified']), report
        assert report['confirmed'] is False and report['tree_scope']['whole_tree_verified'] is False
        assert report['tree_scope']['reason'] == 'ownership_unverifiable'
    finally:
        _kill([r, c])
        root.wait(timeout=3)
        stranger.kill(); stranger.wait(timeout=3)
