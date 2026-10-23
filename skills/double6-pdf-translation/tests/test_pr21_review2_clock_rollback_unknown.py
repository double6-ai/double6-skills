"""PR #21 review-2：墙钟回拨 + 本任务进程 environ 读不到，不能被当作“已清理”。

审稿复现（42bd58c）：真实脱组 orphan 仍在写，只把它的 create_time 改成“根进程记录时间 - 60 s”并对它的
environ 注入 AccessDenied，reclaim_stale 却给出 already_gone=1 / confirmed=True / unverified=[]。根因：
_recovery_scan（以及运行期 launched_members）在“按墙钟早于根进程”的分支读 nonce 失败后直接丢弃该进程。

修复：早于根进程且读不到 nonce 的进程，只有单调启动证据（Linux /proc starttime 滴答、macOS
ri_proc_start_abstime，同一次开机）证明它启动早于根进程才排除；否则记为归属未知
（code=older_than_root_nonce_unreadable），不发信号、unverified 非空、守卫/续跑失败关闭。
create_time 看似复用、但单调启动读数与回执一致的根进程记为 root_identity_clock_shifted（不当作已退出）。

本文件：审稿组合的反例（root / orphan × 有无回执单调证据），有效 nonce 回拨正例，较早无关进程
（有证据 → 排除、不误杀；无证据 → 严格未知、不误杀），以及审计 except/pass/continue 后补的相邻用例。"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import warnings
from pathlib import Path

import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import bounded_execution as be  # noqa: E402
import chunked_workflow as cw  # noqa: E402
import launch_clock  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='process groups / recovery scan are POSIX only')
CODE = be.OLDER_NONCE_UNREADABLE
AMBIENT = {'ownership_unknown', 'ownership_unverifiable'}

WRITER = r'''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import psutil
p = Path(sys.argv[1]); q = psutil.Process()
ident = {'pid': q.pid, 'created_at': q.create_time()}
if len(sys.argv) > 3 and sys.argv[3] == 'evidence':
    from launch_clock import start_evidence
    ident['start_evidence'] = start_evidence()
tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(ident)); os.replace(tmp, p.with_suffix('.json'))
for _ in range(3000):
    with p.with_suffix('.ticks').open('a') as f:
        f.write('tick\n')
    time.sleep(.01)
'''
LAUNCHER = r'''
import json, os, sys, subprocess, time
from pathlib import Path
scripts = sys.argv[3]
sys.path.insert(0, scripts)
import psutil
r = Path(sys.argv[1]); mode = sys.argv[2]; p = psutil.Process()
ident = {'pid': p.pid, 'created_at': p.create_time(), 'process_group': os.getpgrp(),
         'nonce': os.environ['PAPER_TRANSLATION_BOUNDED_OWNERS']}
if 'evidence' in mode:
    from launch_clock import start_evidence
    ident['start_evidence'] = start_evidence()
tmp = r / 'root.tmp'; tmp.write_text(json.dumps(ident)); os.replace(tmp, r / 'root.json')
env = dict(os.environ)
if 'clear-nonce' in mode:
    env.pop('PAPER_TRANSLATION_BOUNDED_OWNERS')
subprocess.Popen([sys.executable, str(r / 'writer.py'), str(r / 'owned'), scripts],
                 start_new_session='same-group' not in mode, env=env,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
while not (r / 'owned.json').exists():
    time.sleep(.01)
'''


def read_json(path, timeout=10.0):
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(.01)
    raise AssertionError(f'marker not published: {path}')


def live(i):
    try:
        p = psutil.Process(i['pid'])
        return abs(p.create_time() - i['created_at']) < .01 and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def growth(path, wait=.25):
    time.sleep(.03); a = path.stat().st_size; time.sleep(wait); return path.stat().st_size - a


def confirmed_or_ambient(report, own_pids):
    """正例：confirmed=True；或机器上其它同用户进程读不到导致的严格 unconfirmed（原因只能是归属未知，
    unverified 非空，未知项不是本例进程）。"""
    if report['confirmed'] is True:
        return True
    rows = report['unverified']
    assert rows and set(report.get('reason_codes') or ()) <= AMBIENT, rows
    assert not ({r.get('pid') for r in rows} & set(own_pids)), rows
    warnings.warn(f'strict unconfirmed (ambient ownership unknown): {rows}'[:2000])
    return False


class Scenario:
    """真实进程：较早启动的无关写入进程 + 本次根（root 形态：根自己写；orphan 形态：根启动脱组写入进程后退出）。"""

    def __init__(self, tmp_path, shape, evidence, mode_extra=''):
        self.tmp, self.shape = tmp_path, shape
        self.children, self.ids = [], []
        (tmp_path / 'writer.py').write_text(WRITER)
        (tmp_path / 'launcher.py').write_text(LAUNCHER)
        self.attempt = tmp_path / 'attempt'; self.attempt.mkdir()
        self.nonce = 'review2-' + uuid.uuid4().hex
        env = {k: v for k, v in os.environ.items() if k != be.OWNER_ENV}
        own_env = {**env, be.OWNER_ENV: self.nonce}
        scripts = str(SKILL / 'scripts')
        self.other = self._spawn([sys.executable, str(tmp_path / 'writer.py'), str(tmp_path / 'unrelated'), scripts], env)
        self.unrelated = read_json(tmp_path / 'unrelated.json'); self.ids.append(self.unrelated)
        time.sleep(.05)   # 根进程严格晚于无关进程启动（单调读数可区分）
        if shape == 'root':
            argv = [sys.executable, str(tmp_path / 'writer.py'), str(tmp_path / 'owned'), scripts] + (['evidence'] if evidence else [])
            owner = self._spawn(argv, own_env)
            self.owned = read_json(tmp_path / 'owned.json')
            self.identity = {**self.owned, 'process_group': owner.pid, 'nonce': self.nonce}
        else:
            mode = shape + ('+evidence' if evidence else '') + mode_extra
            owner = self._spawn([sys.executable, str(tmp_path / 'launcher.py'), str(tmp_path), mode, scripts], own_env)
            self.identity = read_json(tmp_path / 'root.json')
            self.owned = read_json(tmp_path / 'owned.json')
            owner.wait(timeout=10)
            assert not live(self.identity)
        self.ids.append(self.owned)
        (self.attempt / 'candidate.launch.json').write_text(json.dumps(self.identity))
        assert live(self.owned)

    def _spawn(self, argv, env):
        p = subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(p)
        # 立即回收退出的子进程（真实流程由 run_bounded 回收）；否则测试进程留下的僵尸会让原进程组看起来非空。
        threading.Thread(target=p.wait, daemon=True).start()
        return p

    def patch(self, monkeypatch, *, shift=None, deny=()):
        """只对指定 PID：create_time 改为“根记录时间 + shift”，environ 注入 AccessDenied。"""
        orig_ct, orig_env = psutil.Process.create_time, psutil.Process.environ
        root_ct = self.identity['created_at']

        def create_time(proc):
            if shift and proc.pid in shift:
                return root_ct + shift[proc.pid]
            return orig_ct(proc)

        def environ(proc):
            if proc.pid in deny:
                raise psutil.AccessDenied(proc.pid)
            return orig_env(proc)
        monkeypatch.setattr(psutil.Process, 'create_time', create_time)
        monkeypatch.setattr(psutil.Process, 'environ', environ)

    def run(self):
        return cw.post_attempt_guard(self.attempt) if self.shape == 'root' else cw.reclaim_stale([self.attempt])

    def close(self):
        for i in self.ids:
            if live(i):
                psutil.Process(i['pid']).kill()
        for p in self.children:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
        end = time.monotonic() + 3
        while any(live(i) for i in self.ids) and time.monotonic() < end:
            time.sleep(.01)
        assert not any(live(i) for i in self.ids)


# ---------------------------------------------------------------- 1) 审稿组合：回拨 + environ 读不到
@pytest.mark.parametrize('evidence', [False, True], ids=['no-receipt-evidence', 'receipt-start-evidence'])
@pytest.mark.parametrize('shape', ['orphan', 'root'])
def test_clock_rollback_with_unreadable_environ_is_unconfirmed(tmp_path, monkeypatch, shape, evidence):
    s = Scenario(tmp_path, shape, evidence)
    try:
        target = s.owned['pid']
        with monkeypatch.context() as m:
            s.patch(m, shift={target: -60}, deny={target})
            result = s.run()
        audit = {'guard': result, 'owned_alive': live(s.owned), 'owned_growth': growth(tmp_path / 'owned.ticks'),
                 'unrelated_alive': live(s.unrelated), 'unrelated_growth': growth(tmp_path / 'unrelated.ticks')}
        (tmp_path / 'AUDIT.json').write_text(json.dumps(audit, indent=2, default=str))
        assert result['confirmed'] is False and result['unverified'], audit
        assert 'ownership_unknown' in result['reason_codes'] and CODE in result['detail_codes'], audit
        assert target in {r.get('pid') for r in result['unverified']}, audit
        if shape == 'root' and evidence:
            assert 'root_identity_clock_shifted' in result['reason_codes'], audit
        if shape == 'orphan':
            assert result['already_gone'] == 0, audit
        # 归属未知的进程不发信号；无关进程不受影响
        assert audit['owned_alive'] and audit['owned_growth'] > 0, audit
        assert audit['unrelated_alive'] and audit['unrelated_growth'] > 0, audit
    finally:
        s.close()


# ---------------------------------------------------------------- 2) 有效 nonce 的回拨正例
@pytest.mark.parametrize('shape', ['orphan', 'root'])
def test_clock_rollback_with_readable_nonce_is_reclaimed(tmp_path, monkeypatch, shape):
    s = Scenario(tmp_path, shape, evidence=True)
    try:
        target = s.owned['pid']
        with monkeypatch.context() as m:
            s.patch(m, shift={target: -60})
            result = s.run()
            gone = not psutil.pid_exists(target) or psutil.Process(target).status() == psutil.STATUS_ZOMBIE
        assert gone, result
        assert live(s.unrelated) and growth(tmp_path / 'unrelated.ticks') > 0
        confirmed_or_ambient(result, {target, s.unrelated['pid']})
    finally:
        s.close()


# ---------------------------------------------------------------- 3) 较早启动的无关进程（无 nonce 证据）
@pytest.mark.parametrize('evidence', [True, False], ids=['excluded-by-start-clock', 'no-evidence-strict-unknown'])
def test_older_unrelated_unreadable_process_is_never_signalled(tmp_path, monkeypatch, evidence):
    s = Scenario(tmp_path, 'orphan', evidence)
    try:
        other = s.unrelated['pid']
        with monkeypatch.context() as m:
            s.patch(m, deny={other})
            result = s.run()
        assert not live(s.owned)                                   # 本任务 orphan 按 nonce 回收
        assert live(s.unrelated) and growth(tmp_path / 'unrelated.ticks') > 0   # 无关进程不误杀
        if evidence:
            assert other not in {r.get('pid') for r in result['unverified']}, result
            confirmed_or_ambient(result, {s.owned['pid'], other})
        else:
            # 无单调证据：较早、读不到的同用户进程无法排除 → 严格未知（成本：守卫更常 unconfirmed）
            assert result['confirmed'] is False and CODE in result['detail_codes'], result
            assert other in {r.get('pid') for r in result['unverified'] if r.get('code') == CODE}, result
    finally:
        s.close()


def test_launcher_receipt_records_start_evidence_on_this_platform(tmp_path):
    receipt = tmp_path / 'op.launch.json'
    nonce = 'review2-' + uuid.uuid4().hex
    subprocess.run([sys.executable, str(SKILL / 'scripts/bounded_launch.py'), str(receipt), nonce, sys.executable, '-c', 'pass'],
                   check=True, timeout=30)
    ident = json.loads(receipt.read_text())
    if sys.platform.startswith('linux') or sys.platform == 'darwin':
        ev = ident['start_evidence']
        assert ev['boot'] == launch_clock.boot_key() and isinstance(ev['start'], int) and ev['start'] > 0
        assert launch_clock.started_before(os.getpid(), ev) is True   # 本测试进程早于该启动
    else:
        assert 'start_evidence' not in ident


# ---------------------------------------------------------------- 4) 审计后补的相邻用例（假进程表）
class FakeTable:
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

            def children(self, recursive=False):
                return []

        def signal_pid(proc, created_at, sig):
            table.signals.append(proc.pid)
            table.rows.pop(proc.pid, None)
        monkeypatch.setattr(be.psutil, 'Process', P)
        monkeypatch.setattr(be.psutil, 'pids', lambda: sorted(table.rows))
        monkeypatch.setattr(be, '_enumerate_all_pids', lambda: (sorted(table.rows), 'fake', [{'method': 'fake', 'ok': True}]))
        monkeypatch.setattr(be, '_signal_pid', signal_pid)
        monkeypatch.setattr(be.os, 'killpg', lambda pgid, sig: (_ for _ in ()).throw(ProcessLookupError(pgid)))
        return self


NONCE = 'c0ffee00' * 4
ROOT = 94000001
IDENT = {'pid': ROOT, 'created_at': 100.0, 'process_group': None, 'nonce': NONCE}
EVIDENCE = {'clock': 'fake', 'boot': 'fake', 'start': 1000}


@pytest.mark.parametrize('started_before,expect_unknown', [(None, True), (False, True), (True, False)],
                         ids=['no-evidence', 'evidence-says-after-root', 'evidence-says-before-root'])
def test_scan_older_unreadable_needs_start_clock_proof_to_be_excluded(monkeypatch, started_before, expect_unknown):
    FakeTable({94000002: {'created_at': 40.0, 'fail': {'environ': psutil.AccessDenied}}}).install(monkeypatch)
    monkeypatch.setattr(be, '_started_before', lambda pid, ref: started_before)
    ident = dict(IDENT, start_evidence=EVIDENCE)
    scan = be._recovery_scan(ident, {ROOT: 100.0}, NONCE, False, 'review2')
    unknown = [r for r in scan['ownership_unknown'] if r['pid'] == 94000002]
    assert bool(unknown) is expect_unknown, scan
    if expect_unknown:
        assert unknown[0]['code'] == CODE
    else:
        assert scan['older_excluded_by_start_clock'] == 1


def test_scan_older_process_with_nonce_but_unreadable_status_is_still_owned(monkeypatch):
    # 旧代码：nonce 匹配后 status() 抛 AccessDenied → except: pass → 该所属进程被丢弃。
    t = FakeTable({94000002: {'created_at': 40.0, 'env': {be.OWNER_ENV: NONCE}, 'fail': {'status': psutil.AccessDenied}}}).install(monkeypatch)
    report = be.reclaim_owned_tree(IDENT, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert 94000002 in t.signals, report


def test_reclaim_reports_older_unreadable_process_with_code(monkeypatch):
    t = FakeTable({94000002: {'created_at': 40.0, 'fail': {'environ': psutil.AccessDenied}}}).install(monkeypatch)
    report = be.reclaim_owned_tree(IDENT, {ROOT: 100.0}, discovery_failed=True, nonce=NONCE)
    assert t.signals == [] and report['confirmed'] is False, report
    assert any(r.get('pid') == 94000002 and r.get('code') == CODE for r in report['unverified']), report


@pytest.mark.parametrize('started_before,expect_unknown', [(None, True), (True, False)], ids=['no-evidence', 'proved-older'])
def test_launched_members_older_unreadable_process(monkeypatch, tmp_path, started_before, expect_unknown):
    ident = {'pid': ROOT, 'created_at': 100.0, 'process_group': ROOT, 'nonce': NONCE, 'parent_pid': os.getpid(),
             'start_evidence': EVIDENCE}
    path = tmp_path / 'op.launch.json'; path.write_text(json.dumps(ident))
    FakeTable({ROOT: {'created_at': 100.0},
               94000002: {'created_at': 40.0, 'fail': {'environ': psutil.AccessDenied}},   # 墙钟上更早、读不到
               94000003: {'created_at': 40.0, 'env': {be.OWNER_ENV: NONCE}}}).install(monkeypatch)       # 回拨、带 nonce
    monkeypatch.setattr(be.os, 'getpgid', lambda pid: pid)
    monkeypatch.setattr(be, '_started_before', lambda pid, ref: started_before)
    unknown = []
    _, members = be.launched_members(path, NONCE, unknown)
    assert {p.pid for p in members} == {ROOT, 94000003}
    assert ([r['pid'] for r in unknown] == [94000002]) is expect_unknown, unknown


def test_verify_receipt_keeps_precheck_unknown_when_reclaim_scan_misses_it(monkeypatch, tmp_path):
    # 审计：预检发现的、仍存活的归属未知进程，不能因回收端再次扫描没看到而变成 confirmed。
    me = psutil.Process()
    pre = {'complete': True, 'owned_found': [], 'ownership_unknown': [{'pid': me.pid, 'created_at': me.create_time(), 'error': 'x', 'code': CODE}]}
    monkeypatch.setattr(be, '_recovery_scan', lambda *a, **k: dict(pre))
    monkeypatch.setattr(be, 'reclaim_owned_tree', lambda *a, **k: {'confirmed': True, 'status': 'confirmed', 'unverified': []})
    (tmp_path / 'a').mkdir()
    (tmp_path / 'a/x.launch.json').write_text(json.dumps({'pid': 2 ** 22 + 7, 'created_at': 1.0, 'process_group': None, 'nonce': 'n'}))
    report = cw.reclaim_stale([tmp_path])
    assert report['confirmed'] is False and CODE in report['detail_codes'], report


def test_group_member_with_unreadable_pgid_and_cleared_nonce_is_reclaimed_by_group(tmp_path, monkeypatch):
    # 审计：getpgid 读不到 + 已清掉 nonce 的组内成员不会被静默丢弃——killpg(pgid, 0) 独立探测到组非空，按组回收。
    s = Scenario(tmp_path, 'orphan', evidence=True, mode_extra='+same-group+clear-nonce')
    try:
        target = s.owned['pid']
        real_getpgid = os.getpgid
        with monkeypatch.context() as m:
            m.setattr(be.os, 'getpgid', lambda pid: (_ for _ in ()).throw(PermissionError(pid)) if pid == target else real_getpgid(pid))
            result = s.run()
        assert not live(s.owned), result
        assert live(s.unrelated) and growth(tmp_path / 'unrelated.ticks') > 0
        confirmed_or_ambient(result, {target, s.unrelated['pid']})
    finally:
        s.close()
