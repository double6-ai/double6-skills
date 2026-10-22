"""PR #19 第 8 轮：所属进程树发现失败时，必须用经过身份核验的后备路径真正回收已启动的任务。
每个用例都检查真实进程死亡（PID + create_time）、停止后文件不再增长、回执完整；并验证不误杀无关进程。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import bounded_execution as be  # noqa: E402

GIB = 1024 ** 3
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='process-group reclaim is POSIX only')

# 任务脚本：写文件循环（每 50 ms 追加一行），marker 里登记 pid 与 create_time。
WRITER = '''
import os, sys, time, json, subprocess
from pathlib import Path
import psutil
mode, marker, log = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
def loop(tag):
    while True:
        with log.open("a") as f: f.write(tag + "\\n")
        time.sleep(0.05)
def me(): p = psutil.Process(); return {"pid": p.pid, "created_at": p.create_time()}
def spawn(role):
    return subprocess.Popen([sys.executable, __file__, role, str(marker), str(log)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if mode == "tree":            # 根 + 同组孙进程，都写文件
    spawn("grandchild")
    while not Path(str(marker) + ".grandchild").exists(): time.sleep(0.01)
    data = {"root": me(), "grandchild": json.loads(Path(str(marker) + ".grandchild").read_text())}
    marker.write_text(json.dumps(data)); loop("root")
elif mode == "grandchild":
    Path(str(marker) + ".grandchild").write_text(json.dumps(me())); loop("grandchild")
elif mode == "root_exits":    # 根进程启动孙进程后立即退出，孙进程继续写
    spawn("grandchild")
    while not Path(str(marker) + ".grandchild").exists(): time.sleep(0.01)
    data = {"root": me(), "grandchild": json.loads(Path(str(marker) + ".grandchild").read_text())}
    marker.write_text(json.dumps(data)); sys.exit(0)
elif mode == "reparent":      # 中间进程启动孙进程后退出（孙进程被重新挂到 init/subreaper，仍在同组），根继续写
    mid = spawn("middle"); mid.wait()
    while not Path(str(marker) + ".grandchild").exists(): time.sleep(0.01)
    data = {"root": me(), "grandchild": json.loads(Path(str(marker) + ".grandchild").read_text())}
    marker.write_text(json.dumps(data)); loop("root")
elif mode == "middle":
    spawn("grandchild"); sys.exit(0)
'''


def _alive(ident):
    """真实存活检查：PID 存在、create_time 相同、不是僵尸；另用 os.kill(pid, 0) 交叉核对。"""
    try:
        p = psutil.Process(ident['pid'])
        if abs(p.create_time() - ident['created_at']) > 0.01:
            return False
        if p.status() == psutil.STATUS_ZOMBIE:
            return False
    except psutil.NoSuchProcess:
        return False
    try:
        os.kill(ident['pid'], 0)
    except ProcessLookupError:
        return False
    return True


def _cleanup(idents):
    for ident in idents:
        if _alive(ident):
            psutil.Process(ident['pid']).kill()


def _writer(tmp_path):
    script = tmp_path / 'writer.py'
    script.write_text(WRITER)
    return script


def _break_after_marker(monkeypatch, marker, *, where='pids', after_samples=0, receipt=None):
    """marker 出现（任务确实已 exec 并启动孙进程）之后才让发现失败；after_samples>0 时再等资源回执里已有这么多样本。"""
    def ready():
        if not marker.exists():
            return False
        if after_samples:
            path = receipt / 'disc.resource.jsonl'
            return path.exists() and len(path.read_text().splitlines()) >= after_samples + 1
        return True
    if where == 'pids':
        real = be.psutil.pids
        def pids():
            if ready():
                raise SystemError('pid list unavailable after task started')
            return real()
        monkeypatch.setattr(be.psutil, 'pids', pids)
    else:
        real = psutil.Process.children
        def children(self, recursive=False):
            if ready():
                raise SystemError('children unavailable after task started (macOS KERN_PROCARGS2 style)')
            return real(self, recursive=recursive)
        monkeypatch.setattr(psutil.Process, 'children', children)


def _run(tmp_path, mode, **kw):
    script = _writer(tmp_path)
    marker, log = tmp_path / 'started.json', tmp_path / 'writes.log'
    return be.run_bounded([sys.executable, str(script), mode, str(marker), str(log)], cwd=tmp_path,
                          receipt_dir=tmp_path / 'receipts', operation='disc', timeout_seconds=kw.get('timeout', 20),
                          interval_seconds=0.1, rss_limit=GIB, memory_metric='rss'), marker, log


def _no_growth(log, wait=0.6):
    before = log.stat().st_size if log.exists() else 0
    time.sleep(wait)
    after = log.stat().st_size if log.exists() else 0
    return before, after


def _check_receipt(result, root):
    cleanup = result['cleanup']
    assert cleanup['confirmed'] is True and cleanup['status'] == 'confirmed', cleanup
    assert result['owned_tree_alive'] == [] and cleanup['unverified'] == [], cleanup
    assert cleanup['process_group']['pgid'] == root['pid']
    assert cleanup['process_group']['empty_verified'] is True, cleanup
    assert any(row['pid'] == root['pid'] and abs(row['created_at'] - root['created_at']) < 0.01
               for row in result['observed_owned_identities']), result['observed_owned_identities']
    assert result['launch_identity']['pid'] == root['pid']
    receipt = json.loads(Path(result['failure_receipt']).read_text())
    assert receipt['metadata']['cleanup']['confirmed'] is True
    return cleanup


@pytest.mark.parametrize('where', ['pids', 'children'])
def test_first_discovery_failure_reclaims_tree(monkeypatch, tmp_path, where):
    marker = tmp_path / 'started.json'
    _break_after_marker(monkeypatch, marker, where=where)
    idents = []
    try:
        result, marker, log = _run(tmp_path, 'tree')
        data = json.loads(marker.read_text())
        idents = [data['root'], data['grandchild']]
        assert result['status'] == 'stopped' and result['stop_reason'] == 'owned_process_monitor_unavailable', result
        assert not _alive(data['root']) and not _alive(data['grandchild'])
        before, after = _no_growth(log)
        assert before == after and before > 0
        cleanup = _check_receipt(result, data['root'])
        assert data['root']['pid'] in [row['pid'] for row in cleanup['verified_dead']]
    finally:
        _cleanup(idents)


def test_discovery_failure_after_samples_reclaims_tree(monkeypatch, tmp_path):
    marker = tmp_path / 'started.json'
    _break_after_marker(monkeypatch, marker, after_samples=3, receipt=tmp_path / 'receipts')
    idents = []
    try:
        result, marker, log = _run(tmp_path, 'tree')
        data = json.loads(marker.read_text())
        idents = [data['root'], data['grandchild']]
        samples = [json.loads(l) for l in (tmp_path / 'receipts/disc.resource.jsonl').read_text().splitlines()]
        assert sum('task_rss' in s for s in samples) >= 4
        assert result['stop_reason'] == 'owned_process_monitor_unavailable', result
        assert not _alive(data['root']) and not _alive(data['grandchild'])
        before, after = _no_growth(log)
        assert before == after
        cleanup = _check_receipt(result, data['root'])
        dead = {row['pid'] for row in cleanup['verified_dead']}
        assert {data['root']['pid'], data['grandchild']['pid']} <= dead, cleanup
    finally:
        _cleanup(idents)


def test_root_exited_descendant_in_group_reclaimed(monkeypatch, tmp_path):
    marker = tmp_path / 'started.json'
    _break_after_marker(monkeypatch, marker)
    idents = []
    try:
        # 评审第 9 轮 P2：只断言安全结果（真实死亡、停止写入、原进程组为空、无关进程存活），
        # 不再要求必须走“整组发信号”这一步（逐 PID 终止后组已空时不发组信号是正确行为）。
        own = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        same = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        others = [{'pid': p.pid, 'created_at': psutil.Process(p.pid).create_time()} for p in (own, same)]
        result, marker, log = _run(tmp_path, 'root_exits')
        data = json.loads(marker.read_text())
        idents = [data['grandchild']] + others
        assert result['stop_reason'] in ('owned_process_monitor_unavailable', 'owned_descendants_after_command'), result
        assert not _alive(data['grandchild'])
        before, after = _no_growth(log)
        assert before == after and before > 0
        cleanup = result['cleanup']
        assert result['status'] == 'stopped' and cleanup['confirmed'] is True, cleanup
        assert cleanup['process_group']['empty_verified'] is True, cleanup
        assert all(_alive(o) for o in others), 'unrelated process was signalled'
        assert data['grandchild']['pid'] not in [row.get('pid') for row in cleanup['unverified']], cleanup
    finally:
        _cleanup(idents)


def test_reparented_grandchild_in_group_reclaimed(monkeypatch, tmp_path):
    marker = tmp_path / 'started.json'
    _break_after_marker(monkeypatch, marker)
    idents = []
    try:
        result, marker, log = _run(tmp_path, 'reparent')
        data = json.loads(marker.read_text())
        idents = [data['root'], data['grandchild']]
        assert psutil.Process(os.getpid()).pid != data['grandchild']['pid']
        assert result['stop_reason'] == 'owned_process_monitor_unavailable', result
        assert not _alive(data['root']) and not _alive(data['grandchild'])
        before, after = _no_growth(log)
        assert before == after
        _check_receipt(result, data['root'])
    finally:
        _cleanup(idents)


def test_unrelated_processes_survive_group_reclaim(monkeypatch, tmp_path):
    """同时运行的无关进程（自己的会话/进程组）不会被回收。"""
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])  # 与测试进程同组
    try:
        o = {'pid': other.pid, 'created_at': psutil.Process(other.pid).create_time()}
        s = {'pid': sibling.pid, 'created_at': psutil.Process(sibling.pid).create_time()}
        marker = tmp_path / 'started.json'
        _break_after_marker(monkeypatch, marker)
        idents = []
        try:
            result, marker, log = _run(tmp_path, 'tree')
            data = json.loads(marker.read_text())
            idents = [data['root'], data['grandchild']]
            assert not _alive(data['root']) and not _alive(data['grandchild'])
            assert _alive(o) and _alive(s)
        finally:
            _cleanup(idents)
    finally:
        other.kill(); sibling.kill(); other.wait(); sibling.wait()


def test_reused_pid_identity_is_never_signalled(tmp_path):
    """伪造身份：pid 指向一个无关进程但 create_time 不符（PID 复用）。回收不得发信号，并据内核规则判原进程/进程组已不存在。"""
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    try:
        real = psutil.Process(other.pid).create_time()
        identity = {'pid': other.pid, 'created_at': real - 1000.0, 'process_group': other.pid, 'nonce': 'x'}
        report = be.reclaim_owned_tree(identity, {other.pid: real - 1000.0}, deadline=time.monotonic() + 5)
        assert _alive({'pid': other.pid, 'created_at': real}), 'unrelated process was signalled'
        assert report['process_group']['signalled'] == []
        assert report['process_group']['leader'] == 'pid_reused'
        assert all(row['evidence'] == 'pid_reused' for row in report['verified_dead']), report
        assert report['confirmed'] is True
    finally:
        other.kill(); other.wait()


def test_cleanup_that_cannot_be_confirmed_has_distinct_status(monkeypatch, tmp_path):
    """信号发不出去（权限拒绝）时：不得报告为空且已清理；status/stop_reason/failure_code 显式区分，并列出未核实对象。"""
    marker = tmp_path / 'started.json'
    _break_after_marker(monkeypatch, marker)

    def denied(*a, **k):
        raise PermissionError('signal denied (test)')
    monkeypatch.setattr(be, '_signal_pid', denied)
    monkeypatch.setattr(be, '_signal_group', denied)
    idents = []
    try:
        result, marker, log = _run(tmp_path, 'tree', timeout=12)
        data = json.loads(marker.read_text())
        idents = [data['root'], data['grandchild']]
        assert result['status'] == 'cleanup_unconfirmed', result
        assert result['stop_reason'] == 'owned_process_monitor_unavailable'
        cleanup = result['cleanup']
        assert cleanup['confirmed'] is False and cleanup['status'] == 'unconfirmed'
        assert data['root']['pid'] in [row.get('pid') for row in cleanup['unverified']], cleanup
        assert result['owned_tree_alive'], result
        receipt = json.loads(Path(result['failure_receipt']).read_text())
        assert receipt['failure_code'] == 'owned_tree_cleanup_unconfirmed'
        assert receipt['metadata']['stop_reason'] == 'owned_process_monitor_unavailable'
    finally:
        _cleanup(idents)


def test_normal_run_reports_confirmed_cleanup(tmp_path):
    outcome = be.run_bounded([sys.executable, '-c', 'print(1)'], cwd=tmp_path, receipt_dir=tmp_path / 'r', operation='ok',
                             timeout_seconds=20, interval_seconds=0.1, rss_limit=GIB, memory_metric='rss')
    assert outcome['status'] == 'succeeded', outcome
    assert outcome['cleanup']['confirmed'] is True and outcome['cleanup']['process_group']['empty_verified'] is True


def test_workflow_maps_cleanup_unconfirmed_to_error_code(monkeypatch, tmp_path):
    import paper_translation_workflow as wf
    monkeypatch.setattr(wf, 'run_bounded', lambda *a, **k: {'status': 'cleanup_unconfirmed',
                                                           'stop_reason': 'owned_process_monitor_unavailable', 'command': None})
    monkeypatch.setattr(wf, 'job_limits', lambda args: {'per_job_seconds': 60, 'task_rss_bytes': GIB,
                                                        'memory_metric': 'rss', 'max_total_fraction': .25})
    args = type('A', (), {'lock_path': tmp_path / 'lock', 'receipts': tmp_path / 'r'})()
    assert wf.run_job(args, ['true'], 'candidate')['error_code'] == 'owned_tree_cleanup_unconfirmed'
