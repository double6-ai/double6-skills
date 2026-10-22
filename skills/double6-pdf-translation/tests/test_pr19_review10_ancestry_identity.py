"""PR #19 第 10 轮：恢复扫描的祖先链必须逐环核实身份（PID + create_time）。
- 已知成员只有在“当前 PID 的 create_time 与记录一致”时才能作祖先起点；
- 已复用 / 无法核实 / 已退出的旧号码不能把归属授予以它为 ppid 的新进程：没有独立 nonce / 进程组证据时，
  这类进程记为 ownership_unknown（整树未核实），且绝不发信号；
- 有效的同身份多跳父链、本次 nonce 仍正常回收。
模拟用例只模拟进程查询，并以 spy 截获 _signal_pid / os.kill / os.killpg（不会真的发信号）；另有真实进程多跳链用例。"""
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

NONCE = 'c0ffee00c0ffee00c0ffee00c0ffee00'
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='recovery scan is POSIX only')


class Table:
    """模拟进程表：pid -> {created_at, ppid, env, status}。spy 发信号时把进程标为已退出（不真的发信号）。"""

    def __init__(self, rows):
        self.rows = {pid: dict(row) for pid, row in rows.items()}
        self.signals = []

    def install(self, monkeypatch):
        table = self

        class FakeProcess:
            def __init__(self, pid):
                if pid not in table.rows:
                    raise psutil.NoSuchProcess(pid)
                self.pid = pid

            def _row(self):
                if self.pid not in table.rows:
                    raise psutil.NoSuchProcess(self.pid)
                return table.rows[self.pid]

            def create_time(self):
                return self._row()['created_at']

            def status(self):
                return self._row().get('status', psutil.STATUS_RUNNING)

            def ppid(self):
                return self._row()['ppid']

            def environ(self):
                env = self._row().get('env', {})
                if env is None:
                    raise psutil.AccessDenied(self.pid)
                return env

            def uids(self):
                return type('UID', (), {'real': os.getuid()})()

        def signal_pid(proc, created_at, sig):
            row = table.rows.get(proc.pid)
            if row is None or abs(row['created_at'] - created_at) > be.IDENTITY_TOLERANCE:
                raise psutil.NoSuchProcess(proc.pid)
            table.signals.append(('pid', proc.pid, int(sig)))
            table.rows.pop(proc.pid)   # 模拟目标退出

        def fake_kill(pid, sig):
            table.signals.append(('os.kill', pid, int(sig)))
            raise AssertionError(f'os.kill must not be called directly (pid {pid})')

        def fake_killpg(pgid, sig):
            table.signals.append(('os.killpg', pgid, int(sig)))
            raise ProcessLookupError(pgid)

        monkeypatch.setattr(be.psutil, 'Process', FakeProcess)
        monkeypatch.setattr(be, '_enumerate_all_pids', lambda: (sorted(table.rows), 'fake-table', [{'method': 'fake-table', 'ok': True}]))
        monkeypatch.setattr(be, '_signal_pid', signal_pid)
        monkeypatch.setattr(be.os, 'kill', fake_kill)
        monkeypatch.setattr(be.os, 'killpg', fake_killpg)
        return self

    def signalled(self):
        return {pid for kind, pid, _ in self.signals if kind == 'pid'}


ROOT = 91000001
IDENTITY = {'pid': ROOT, 'created_at': 100.0, 'process_group': None, 'nonce': NONCE}   # 无进程组证据（group_trusted=False）


def _owned(scan):
    return {row['pid']: row['match'] for row in scan['owned_found']}


def _unknown(scan):
    return {row['pid'] for row in scan['ownership_unknown']}


def test_valid_multi_hop_chain_is_recovered_and_signalled(monkeypatch):
    t = Table({ROOT: {'created_at': 100.0, 'ppid': 1},
               91000002: {'created_at': 110.0, 'ppid': ROOT},
               91000003: {'created_at': 120.0, 'ppid': 91000002},
               91000004: {'created_at': 130.0, 'ppid': 91000003}}).install(monkeypatch)
    scan = be._recovery_scan(IDENTITY, {ROOT: 100.0}, NONCE, False, 'positive')
    assert _owned(scan) == {91000002: 'ancestry', 91000003: 'ancestry', 91000004: 'ancestry'}, scan
    assert not scan['ownership_unknown']
    report = be.reclaim_owned_tree(IDENTITY, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signalled() == {ROOT, 91000002, 91000003, 91000004}, t.signals
    assert report['confirmed'] is True and report['tree_scope']['whole_tree_verified'] is True, report


def test_reused_root_grants_no_ownership_and_receives_no_signal(monkeypatch):
    # 旧根 100 已退出，号码被无关进程（create_time 200）复用；它的子孙（201、202）无 nonce。
    t = Table({ROOT: {'created_at': 200.0, 'ppid': 1, 'env': {}},
               91000002: {'created_at': 201.0, 'ppid': ROOT, 'env': {}},
               91000003: {'created_at': 202.0, 'ppid': 91000002, 'env': {}}}).install(monkeypatch)
    scan = be._recovery_scan(IDENTITY, {ROOT: 100.0}, NONCE, False, 'reused-root')
    assert not scan['owned_found'], scan
    assert {91000002, 91000003} <= _unknown(scan), scan
    report = be.reclaim_owned_tree(IDENTITY, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signals == [], t.signals
    assert any(r['pid'] == ROOT and r['evidence'] == 'pid_reused' for r in report['verified_dead']), report
    unverified = {r.get('pid'): r for r in report['unverified'] if r.get('pid')}
    assert unverified[91000002]['reason'] == 'ownership_unknown' and unverified[91000003]['reason'] == 'ownership_unknown'
    assert report['confirmed'] is False and report['tree_scope']['whole_tree_verified'] is False
    assert report['tree_scope']['reason'] == 'ownership_unverifiable'
    assert not report['recovered_members']


def test_reused_known_intermediate_grants_no_ownership(monkeypatch):
    # 根仍是原进程；已知中间成员 91000005（create_time 110）已退出，号码被无关进程（300）复用，它有孩子 91000006。
    # 根的真孩子 91000002 仍要回收；复用号码及其孩子不得收到信号。
    t = Table({ROOT: {'created_at': 100.0, 'ppid': 1},
               91000002: {'created_at': 120.0, 'ppid': ROOT},
               91000005: {'created_at': 300.0, 'ppid': 1, 'env': {}},
               91000006: {'created_at': 301.0, 'ppid': 91000005, 'env': {}}}).install(monkeypatch)
    known = {ROOT: 100.0, 91000005: 110.0}
    scan = be._recovery_scan(IDENTITY, known, NONCE, False, 'reused-intermediate')
    assert _owned(scan) == {91000002: 'ancestry'}, scan
    assert 91000006 in _unknown(scan) and 91000005 not in _owned(scan)
    report = be.reclaim_owned_tree(IDENTITY, known, discovery_failed=True, nonce=NONCE)
    assert t.signalled() == {ROOT, 91000002}, t.signals
    assert not any(kind != 'pid' for kind, _, _ in t.signals), t.signals
    assert any(r['pid'] == 91000005 and r['evidence'] == 'pid_reused' for r in report['verified_dead'])
    assert any(r.get('pid') == 91000006 and r['reason'] == 'ownership_unknown' for r in report['unverified']), report
    assert report['confirmed'] is False


def test_dead_known_member_is_not_an_ancestor_root(monkeypatch):
    # 已知成员 91000007 已退出（表中不存在）；仍有进程的 ppid 指向这个号码（父进程刚退出的瞬间）。
    t = Table({ROOT: {'created_at': 100.0, 'ppid': 1},
               91000008: {'created_at': 150.0, 'ppid': 91000007, 'env': {}}}).install(monkeypatch)
    known = {ROOT: 100.0, 91000007: 105.0}
    scan = be._recovery_scan(IDENTITY, known, NONCE, False, 'dead-member')
    assert 91000008 not in _owned(scan) and 91000008 in _unknown(scan), scan
    report = be.reclaim_owned_tree(IDENTITY, known, discovery_failed=True, nonce=NONCE)
    assert 91000008 not in t.signalled(), t.signals
    assert any(r['pid'] == 91000007 and r['evidence'] == 'dead' for r in report['verified_dead'])
    assert report['confirmed'] is False


def test_unknown_known_member_is_not_an_ancestor_root(monkeypatch):
    # 已知成员的当前身份无法查询（create_time 读取失败）：不能作祖先起点。
    t = Table({ROOT: {'created_at': 100.0, 'ppid': 1},
               91000009: {'created_at': 110.0, 'ppid': ROOT},
               91000010: {'created_at': 160.0, 'ppid': 91000009, 'env': {}}}).install(monkeypatch)
    real_identity_state = be._identity_state

    def identity_state(pid, created_at):
        if pid == 91000009:
            return 'unknown', None
        return real_identity_state(pid, created_at)
    monkeypatch.setattr(be, '_identity_state', identity_state)
    scan = be._recovery_scan(IDENTITY, {ROOT: 100.0, 91000009: 110.0}, NONCE, False, 'unknown-member')
    assert 91000010 not in _owned(scan) and 91000010 in _unknown(scan), scan


def test_nonce_evidence_still_recovers_child_of_reused_number(monkeypatch):
    # 独立证据：环境里带本次 nonce 的进程即使 ppid 指向复用号码，也按 launch_nonce 回收。
    t = Table({ROOT: {'created_at': 200.0, 'ppid': 1, 'env': {}},
               91000002: {'created_at': 201.0, 'ppid': ROOT, 'env': {be.OWNER_ENV: NONCE}}}).install(monkeypatch)
    scan = be._recovery_scan(IDENTITY, {ROOT: 100.0}, NONCE, False, 'nonce')
    assert _owned(scan) == {91000002: 'launch_nonce'}, scan
    be.reclaim_owned_tree(IDENTITY, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signalled() == {91000002}, t.signals


def test_reused_number_examined_as_candidate_for_own_evidence(monkeypatch):
    # 已知成员号码被复用；复用者本身带本次 nonce（本任务后来起的进程恰好拿到这个号码）——按 nonce 回收，而不是因号码在已知列表里被跳过。
    t = Table({ROOT: {'created_at': 100.0, 'ppid': 1},
               91000005: {'created_at': 300.0, 'ppid': ROOT, 'env': {be.OWNER_ENV: NONCE}}}).install(monkeypatch)
    scan = be._recovery_scan(IDENTITY, {ROOT: 100.0, 91000005: 110.0}, NONCE, False, 'reused-own')
    assert _owned(scan) == {91000005: 'launch_nonce'}, scan


# ---- 真实进程：多跳父链（脱组、无 nonce、无进程组证据）仍被回收；运行期间新起的无关进程存活 ----
CHAIN = '''
import os, sys, time, json, subprocess
from pathlib import Path
import psutil
level, d = int(sys.argv[1]), Path(sys.argv[2])
p = psutil.Process()
(d / f"l{level}.json").write_text(json.dumps({"pid": p.pid, "created_at": p.create_time(), "ppid": p.ppid()}))
if level < 3:
    subprocess.Popen([sys.executable, __file__, str(level + 1), str(d)], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(3000):
    with (d / f"l{level}.ticks").open("a") as f: f.write("t\\n")
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


def test_real_multi_hop_chain_recovered_unrelated_survives(tmp_path):
    script = tmp_path / 'chain.py'
    script.write_text(CHAIN)
    env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}   # 无 nonce：只能靠父链
    root = subprocess.Popen([sys.executable, str(script), '0', str(tmp_path)], start_new_session=True, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=root.wait, daemon=True).start()
    for _ in range(500):
        if (tmp_path / 'l3.json').exists():
            break
        time.sleep(0.01)
    chain = [json.loads((tmp_path / f'l{i}.json').read_text()) for i in range(4)]
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True, env=env)
    u_ident = {'pid': unrelated.pid, 'created_at': psutil.Process(unrelated.pid).create_time()}
    try:
        identity = {'pid': chain[0]['pid'], 'created_at': chain[0]['created_at'], 'process_group': None}
        report = be.reclaim_owned_tree(identity, {chain[0]['pid']: chain[0]['created_at']}, discovery_failed=True, nonce=NONCE)
        assert all(not _alive(c) for c in chain), chain
        ticks = [tmp_path / f'l{i}.ticks' for i in range(4)]
        a = [p.stat().st_size for p in ticks]; time.sleep(0.3); b = [p.stat().st_size for p in ticks]
        assert a == b
        assert _alive(u_ident), 'unrelated process was signalled'
        found = {row['pid']: row['match'] for row in report['recovered_members']}
        assert all(found.get(c['pid']) == 'ancestry' for c in chain[1:]), report['recovered_members']
        assert unrelated.pid not in {row['pid'] for row in report['signalled']}
        assert report['confirmed'] is True, report
    finally:
        for c in chain + [u_ident]:
            if _alive(c):
                psutil.Process(c['pid']).kill()
        unrelated.wait(timeout=3)
