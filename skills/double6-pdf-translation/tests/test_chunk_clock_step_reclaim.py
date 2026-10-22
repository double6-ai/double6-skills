"""chunk-r2 实测：虚拟机暂停/墙钟校正后（Linux create_time = btime + 启动 jiffies，btime 前跳数百到数千秒），
同一进程报告的 create_time 与 launch 回执不符。旧逻辑按 PID + create_time 判为 pid_reused、不发信号，
post_attempt_guard 只能失败关闭（chunk_cleanup_unconfirmed），而遗留树继续运行到自行结束（孤儿）。
修复：恢复扫描中以本次启动 nonce（环境变量，正面所属证据）核验到的进程，若记录身份已判为 pid_reused，
以观测 create_time 刷新身份并回收；没有 nonce 的复用号码仍按复用处理，绝不发信号。成对正/负用例。"""
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
import chunked_workflow as cw  # noqa: E402
from test_pr19_review10_ancestry_identity import Table  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='recovery scan is POSIX only')
NONCE = 'feedface' * 4
STEP = 481.0   # chunk-r1 观测到的 btime 前跳（02:43→03:19）
ROOT = 92000001
IDENTITY = {'pid': ROOT, 'created_at': 100.0, 'process_group': ROOT, 'nonce': NONCE}


def test_fake_clock_step_root_with_nonce_is_refreshed_and_reclaimed(monkeypatch):
    t = Table({ROOT: {'created_at': 100.0 + STEP, 'ppid': 1, 'env': {be.OWNER_ENV: NONCE}},
               92000002: {'created_at': 101.0 + STEP, 'ppid': ROOT, 'env': {be.OWNER_ENV: NONCE}}}).install(monkeypatch)
    monkeypatch.setattr(be, '_group_empty', lambda pgid: ROOT not in t.rows and 92000002 not in t.rows)
    report = be.reclaim_owned_tree(IDENTITY, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signalled() == {ROOT, 92000002}, t.signals
    assert report['confirmed'] is True, report
    assert report['identity_refreshed'] == [{'pid': ROOT, 'recorded_created_at': 100.0,
                                             'observed_created_at': 100.0 + STEP, 'evidence': 'launch_nonce'}]
    assert report['process_group']['identity_refreshed_by_nonce'] is True


def test_fake_reused_root_without_nonce_is_still_not_signalled(monkeypatch):
    # 负例：同样的 create_time 偏移，但进程环境里没有本次 nonce（真正的 PID 复用）→ 不刷新、不发信号。
    t = Table({ROOT: {'created_at': 100.0 + STEP, 'ppid': 1, 'env': {be.OWNER_ENV: 'other' * 6}}}).install(monkeypatch)
    monkeypatch.setattr(be, '_group_empty', lambda pgid: False)
    report = be.reclaim_owned_tree(IDENTITY, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signals == [], t.signals
    assert 'identity_refreshed' not in report
    assert any(r['pid'] == ROOT and r['evidence'] == 'pid_reused' for r in report['verified_dead']), report


def _spawn(env_nonce):
    env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}
    if env_nonce:
        env[be.OWNER_ENV] = env_nonce
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=proc.wait, daemon=True).start()
    for _ in range(200):
        try:
            if env_nonce is None or env_nonce in psutil.Process(proc.pid).environ().get(be.OWNER_ENV, ''):
                break
        except psutil.Error:
            pass
        time.sleep(0.01)
    return proc


def _receipt(attempt: Path, proc, nonce):
    # 模拟时钟前跳：回执里的 create_time 比当前观测值早 STEP 秒（与 btime 前跳时 psutil 的表现一致）。
    d = attempt / 'receipts' / 'candidate'
    d.mkdir(parents=True)
    observed = psutil.Process(proc.pid).create_time()
    (d / 'candidate.launch.json').write_text(json.dumps(
        {'pid': proc.pid, 'created_at': observed - STEP, 'process_group': proc.pid, 'nonce': nonce}))


def _gone(proc):
    try:
        p = psutil.Process(proc.pid)
        return p.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def test_real_post_attempt_guard_reclaims_tree_after_clock_step(tmp_path):
    proc = _spawn(NONCE)
    try:
        _receipt(tmp_path, proc, NONCE)
        report = cw.post_attempt_guard(tmp_path)
        assert report['live_after_attempt'] == [NONCE]
        assert report['confirmed'] is True, report
        assert report['reclaim']['reclaimed'][0]['root_state'] == 'pid_reused'
        for _ in range(100):
            if _gone(proc):
                break
            time.sleep(0.02)
        assert _gone(proc)
    finally:
        if not _gone(proc):
            proc.kill()


def test_real_unrelated_process_with_shifted_identity_is_not_touched(tmp_path):
    # 负例：回执指向的 PID 上是无本次 nonce 的进程（真正复用）——守卫看不到存活 nonce，回收也不得发信号。
    proc = _spawn(None)
    try:
        _receipt(tmp_path, proc, NONCE)
        report = cw.post_attempt_guard(tmp_path)
        assert report['live_after_attempt'] == [] and report['confirmed'] is True
        identity = json.loads(next(tmp_path.rglob('*.launch.json')).read_text())
        direct = be.reclaim_owned_tree(identity, {}, time.monotonic() + 5, discovery_failed=True, nonce=NONCE)
        assert 'identity_refreshed' not in direct
        assert not direct['signalled'] and not direct['process_group']['signalled']
        time.sleep(0.2)
        assert not _gone(proc), 'unrelated process was signalled'
    finally:
        proc.kill()
