"""PR #25 next item：后端失败根因上浮，确定性失败不重试（首次与续跑都不重跑）。

成对：确定性（排版上限、可读下限溢出、子任务合同拒绝、预检拒绝） vs 非确定性（5xx/断连/无结构化根因 →
root_cause_unavailable，按既有瞬时失败重试一次）；资源停止仍二分；cleanup_unconfirmed 仍停止调度；
启动身份竞态仍重试；伪造/过期/非本尝试/被改动的根因回执一律不采信。"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests')]

import chunked_translation as ct  # noqa: E402
import chunked_workflow as cw  # noqa: E402
import failure_root_cause as frc  # noqa: E402
import paper_translation_workflow as wf  # noqa: E402
from test_chunked_translation import FakeChunkRunner, _main, chunked_args, long_doc  # noqa: E402,F401

C = ct.CHUNKING_CONTRACT


# ------------------------------------------------------------------ 排版回执样例（与真实回执同结构）
def cap_report(pages=2, count=14, cap=12):
    failures = [{'page_index': 0, 'paragraph_id': f'p{i}', 'role': 'fallback_line', 'status': 'chart_region_rerender_required',
                 'reason': 'hard_readable_floor_overflow', 'source_fallback_rejected': 'overflow_source_fallback_cap_exceeded'}
                for i in range(count)] + [{'page_index': 1, 'paragraph_id': 'q', 'role': 'text',
                                           'status': 'chart_region_rerender_required', 'reason': 'hard_readable_floor_overflow',
                                           'source_fallback_rejected': 'overflow_source_fallback_cap_exceeded'}] * 3
    return {'stage': 'post_typesetting', 'status': 'blocked', 'page_count': pages, 'failures': failures,
            'source_fallbacks': [], 'source_fallback_count': 0,
            'source_fallback_cap': {'document_cap': 19, 'page_caps': {'0': cap}, 'count': count + 3,
                                    'violations': [{'scope': 'page', 'page_index': 0, 'count': count, 'cap': cap}],
                                    'paragraphs_per_page': {'0': 60, '1': 40}, 'segment_count': 100,
                                    'status': 'revoked_cap_exceeded', 'document_cap_scope': 'chunk_merge',
                                    'deferred_violations': []},
            'scope': 'explicit_native_writeback_failures_only'}


def overflow_report(pages=4, page_index=3):
    return {'stage': 'post_typesetting', 'status': 'blocked', 'page_count': pages,
            'failures': [{'page_index': page_index, 'paragraph_id': 'x', 'role': 'formula_caption', 'status': 'writeback_failed',
                          'reason': 'hard_readable_floor_overflow', 'source_fallback_rejected': 'not_short_structural'}],
            'source_fallbacks': [], 'source_fallback_count': 0,
            'source_fallback_cap': {'document_cap': 8, 'count': 0, 'violations': [], 'status': 'none',
                                    'document_cap_scope': 'chunk_merge', 'deferred_violations': []},
            'scope': 'explicit_native_writeback_failures_only'}


def write_report(out, report, stem='c001'):
    path = out / '_backend_working' / stem / frc.TYPESETTING_REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report))
    return path


# ------------------------------------------------------------------ derive：只读本尝试输出目录内的结构化产物
def test_derive_cap_exceeded_reports_page_count_cap_and_stage(tmp_path):
    started = time.time() - 1
    write_report(tmp_path, cap_report())
    cause = frc.derive(tmp_path, {'errors': [{'error_type': 'nonzero_exit', 'returncode': 1}]}, expected_pages=2, started_at=started)
    assert cause['code'] == 'typesetting_source_fallback_cap_exceeded' and cause['retry'] == 'deterministic'
    assert cause['stage'] == 'post_typesetting'
    assert cause['details']['violations'] == [{'scope': 'page', 'page_index': 0, 'page': 1, 'count': 14, 'cap': 12}]
    assert cause['details']['document_cap']['count'] == 17 and cause['details']['document_cap']['cap'] == 19
    assert cause['details']['failure_count'] == 17 and cause['evidence'][0]['sha256']


def test_derive_floor_overflow_reports_page(tmp_path):
    write_report(tmp_path, overflow_report(), 'c002')
    cause = frc.derive(tmp_path, {'errors': []}, expected_pages=4, started_at=time.time() - 1)
    assert cause['code'] == 'typesetting_readable_floor_overflow' and cause['retry'] == 'deterministic'
    assert cause['details']['pages'] == [4] and cause['details']['reasons'] == {'hard_readable_floor_overflow': 1}


def test_derive_passed_report_is_not_a_cause(tmp_path):
    report = overflow_report()
    report.update(status='passed', failures=[])
    write_report(tmp_path, report)
    cause = frc.derive(tmp_path, {'errors': [{'error_type': 'missing_translated_pdf'}], 'returncode': 0},
                       expected_pages=4, started_at=None)
    assert cause['code'] == frc.UNAVAILABLE and cause['retry'] == 'unknown' and cause['problem'] == 'no_structured_cause'


@pytest.mark.parametrize('case', ['older_than_attempt', 'outside_attempt', 'unreadable', 'page_count', 'ambiguous'])
def test_derive_untrustworthy_evidence_is_explicitly_unavailable(tmp_path, case):
    out = tmp_path / 'out'
    out.mkdir()
    started = time.time()
    if case == 'older_than_attempt':
        path = write_report(out, cap_report())
        os.utime(path, (started - 100, started - 100))
    elif case == 'outside_attempt':
        other = tmp_path / 'other-attempt' / 'out'
        real = write_report(other, cap_report())
        (out / '_backend_working' / 'c001').mkdir(parents=True)
        (out / '_backend_working' / 'c001' / frc.TYPESETTING_REPORT).symlink_to(real)
    elif case == 'unreadable':
        write_report(out, cap_report()).write_text('{not json')
    elif case == 'page_count':
        write_report(out, cap_report(pages=3))
    else:
        write_report(out, cap_report(), 'a')
        write_report(out, cap_report(), 'b')
    cause = frc.derive(out, {'errors': []}, expected_pages=2, started_at=started - 1 if case != 'older_than_attempt' else started)
    assert cause['code'] == frc.UNAVAILABLE and cause['retry'] == 'unknown'
    assert cause['problem'] == {'older_than_attempt': 'typesetting_report_older_than_attempt',
                                'outside_attempt': 'typesetting_report_outside_attempt',
                                'unreadable': 'typesetting_report_unreadable',
                                'page_count': 'typesetting_report_page_count_mismatch',
                                'ambiguous': 'ambiguous_typesetting_reports'}[case]


def test_derive_backend_timeout_is_resource_not_deterministic(tmp_path):
    (tmp_path / 'render_manifest.json').write_text('{}')
    cause = frc.derive(tmp_path, {'errors': [{'error_type': 'timeout', 'timeout_seconds': 110}]}, expected_pages=1, started_at=None)
    assert cause['code'] == 'pdf_backend_timeout' and cause['retry'] == 'resource'


# ------------------------------------------------------------------ 子任务 → 父任务：真实结构化行与回执核对
def attempt_fixture(tmp_path, monkeypatch, report=None, nonce='n-current', name='attempt-1'):
    attempt = tmp_path / name
    out, freeze = attempt / 'out', attempt / 'freeze' / 'FREEZE.json'
    out.mkdir(parents=True)
    freeze.parent.mkdir(parents=True)
    freeze.write_text(json.dumps({'pages': [1, 2]}))
    launch = attempt / 'receipts' / 'candidate' / 'launch-identity.json'   # 不叫 *.launch.json：不进回收扫描
    launch.parent.mkdir(parents=True)
    launch.write_text(json.dumps({'nonce': nonce, 'pid': 1, 'created_at': 0}))
    started = time.time() - 1
    if report is not None:
        write_report(out, report)
    monkeypatch.setenv('PAPER_TRANSLATION_BOUNDED_OWNERS', f'outer,{nonce}')
    args = SimpleNamespace(output_dir=str(out), attempt_freeze_path=freeze, attempt_started_at=started, source_cache_mode=None)
    (out / 'render_manifest.json').write_text(json.dumps({'actual_render_source': 'pdf_backend', 'outputs': {},
                                                          'errors': [{'error_type': 'nonzero_exit', 'returncode': 1}]}))
    (out / 'hymt_proxy_stats.json').write_text(json.dumps({'proxy': {}, 'stats': {}}))
    return attempt, out, freeze, launch, args


def child_output(args, capsys, monkeypatch):
    """真实子任务出口：finish_digital_result 抛 BackendFailure → main 的结构化失败输出（stdout 全文 + 结构化行）。"""
    freeze = {'pages': [1, 2], 'proxy_quality_contract': {'required': False, 'adapter': 'none'}}
    with pytest.raises(wf.BackendFailure) as excinfo:
        wf.finish_digital_result(freeze, args, {}, None)
    monkeypatch.setattr(wf, 'dispatch', lambda ns: (_ for _ in ()).throw(excinfo.value))
    code = wf.main(['_execute-digital', '--freeze', str(args.attempt_freeze_path), '--', 'x.pdf'])
    return code, capsys.readouterr().out, excinfo.value


def bounded_result(stdout, out, freeze, launch, returncode=2):
    summary = {'char_count': len(stdout), 'sha256': hashlib.sha256(stdout.encode()).hexdigest(),
               'excerpt': stdout[-2048:], 'truncated': len(stdout) > 2048}
    return {'status': 'failed', 'stop_reason': None, 'launch_receipt': str(launch),
            'command': {'argv': ['python', 'bounded_launch.py', str(launch), 'n', 'python', 'paper_translation_workflow.py',
                                 '_execute-digital', '--freeze', str(freeze), '--', 'c.pdf', '--output-dir', str(out)],
                        'returncode': returncode, 'stdout_summary': summary, 'failure_code': 'nonzero_exit'}}


def test_child_failure_reaches_parent_as_verified_root_cause(tmp_path, monkeypatch, capsys):
    _, out, freeze, launch, args = attempt_fixture(tmp_path, monkeypatch, cap_report())
    code, stdout, exc = child_output(args, capsys, monkeypatch)
    assert code == wf.EXIT_BLOCKED and exc.root_cause['code'] == 'typesetting_source_fallback_cap_exceeded'
    marker = stdout.strip().splitlines()[-1]
    assert marker.startswith(wf.CHILD_RESULT_MARKER) and len(marker) < 2048
    receipt = json.loads((out / frc.RECEIPT_NAME).read_text())
    assert receipt['attempt']['owner_nonce'] == 'n-current' and receipt['attempt']['output_dir'] == str(out.resolve())
    result = wf.attach_root_cause(bounded_result(stdout, out, freeze, launch))
    assert result['status'] == 'failed'                          # 状态与退出码语义不变，只补原因
    assert result['error_code'] == 'typesetting_source_fallback_cap_exceeded'
    assert result['root_cause']['verified'] is True and result['root_cause']['details']['violations'][0]['count'] == 14
    assert result['findings'][0]['code'] == 'typesetting_source_fallback_cap_exceeded'
    assert cw.classify(result, C) == 'blocked'


def test_child_failure_without_structured_cause_is_unavailable_and_retried(tmp_path, monkeypatch, capsys):
    _, out, freeze, launch, args = attempt_fixture(tmp_path, monkeypatch, None)   # 例：5xx/断连后后端退出、无排版回执
    _, stdout, _ = child_output(args, capsys, monkeypatch)
    result = wf.attach_root_cause(bounded_result(stdout, out, freeze, launch))
    assert result['error_code'] == frc.UNAVAILABLE and result['root_cause']['verified'] is True
    assert result['root_cause']['problem'] == 'no_structured_cause'
    assert cw.classify(result, C) == 'transient'                 # 不把未知当确定：沿用重试一次


@pytest.mark.parametrize('forgery', ['stale_nonce', 'other_attempt_receipt', 'receipt_edited', 'evidence_edited',
                                     'freeze_changed', 'unknown_code', 'no_launch_receipt', 'ref_not_dict'])
def test_forged_or_stale_root_cause_receipts_are_not_trusted(tmp_path, monkeypatch, capsys, forgery):
    _, out, freeze, launch, args = attempt_fixture(tmp_path, monkeypatch, cap_report())
    _, stdout, exc = child_output(args, capsys, monkeypatch)
    result = bounded_result(stdout, out, freeze, launch)
    receipt_path = out / frc.RECEIPT_NAME
    if forgery == 'stale_nonce':
        launch.write_text(json.dumps({'nonce': 'n-newer-attempt'}))     # 回执来自更早的一次启动
    elif forgery == 'other_attempt_receipt':
        _, out2, _, _, _ = attempt_fixture(tmp_path, monkeypatch, None, name='attempt-2')
        result['command']['argv'][-1] = str(out2)                       # 本尝试是 attempt-2，回执在 attempt-1
    elif forgery == 'receipt_edited':
        receipt_path.write_text(receipt_path.read_text().replace('"count": 14', '"count": 15'))
    elif forgery == 'evidence_edited':
        report = next(out.glob('_backend_working/*/' + frc.TYPESETTING_REPORT))
        report.write_text(report.read_text() + ' ')
    elif forgery == 'freeze_changed':
        freeze.write_text(json.dumps({'pages': [1, 2, 3]}))
    elif forgery == 'unknown_code':
        data = json.loads(receipt_path.read_text())
        data['root_cause']['code'] = 'made_up_deterministic'
        receipt_path.write_text(json.dumps(data))
        marker = json.loads(stdout.strip().splitlines()[-1][len(wf.CHILD_RESULT_MARKER):])
        marker['root_cause_ref'] = frc._ref(receipt_path)
        stdout = stdout.rsplit('\n', 2)[0] + '\n' + wf.CHILD_RESULT_MARKER + json.dumps(marker) + '\n'
        result = bounded_result(stdout, out, freeze, launch)
    elif forgery == 'no_launch_receipt':
        result.pop('launch_receipt')
    else:
        marker = json.loads(stdout.strip().splitlines()[-1][len(wf.CHILD_RESULT_MARKER):])
        marker['root_cause_ref'] = str(receipt_path)
        stdout = stdout.rsplit('\n', 2)[0] + '\n' + wf.CHILD_RESULT_MARKER + json.dumps(marker) + '\n'
        result = bounded_result(stdout, out, freeze, launch)
    result = wf.attach_root_cause(result)
    assert result['root_cause']['code'] == frc.UNAVAILABLE and result['root_cause']['verified'] is False
    assert cw.classify(result, C) == 'transient'


# ------------------------------------------------------------------ classify：成对
def legacy_child_result(code='input_or_contract_invalid', message='ValueError: PDF backend failed or changed route; no fallback delivery',
                        returncode=2, truncate=False, tamper=False):
    envelope = {'schema_version': 1, 'status': 'blocked', 'error_code': code, 'warnings': [],
                'findings': [{'code': code, 'severity': 'error', 'message': message, 'details': {}}], 'action': '_execute-digital'}
    stdout = json.dumps(envelope, ensure_ascii=False, indent=2) + '\n'
    summary = {'char_count': len(stdout), 'sha256': hashlib.sha256(stdout.encode()).hexdigest(),
               'excerpt': stdout.replace('blocked', 'blocked ') if tamper else stdout, 'truncated': truncate}
    return {'status': 'failed', 'command': {'returncode': returncode, 'stdout_summary': summary, 'failure_code': 'nonzero_exit'}}


def test_classify_deterministic_vs_not_pairs():
    det = {'status': 'failed', 'error_code': 'typesetting_readable_floor_overflow',
           'root_cause': {'code': 'typesetting_readable_floor_overflow', 'retry': 'deterministic', 'verified': True}}
    assert cw.classify(det, C) == 'blocked'
    assert cw.classify(dict(det, root_cause=dict(det['root_cause'], verified=False)), C) == 'transient'
    unavailable = {'status': 'failed', 'error_code': frc.UNAVAILABLE, 'root_cause': dict(frc.unavailable('x'), verified=True)}
    assert cw.classify(unavailable, C) == 'transient'
    timeout = {'status': 'failed', 'error_code': 'pdf_backend_timeout',
               'root_cause': {'code': 'pdf_backend_timeout', 'retry': 'resource', 'verified': True}}
    assert cw.classify(timeout, C) == 'resource_stop'
    # 子任务自身的合同/输入拒绝（结构化 stdout 全文，退出码 2）= 确定；环境性质的锁/I/O 码、截断或被改动的摘录不算
    assert cw.classify(legacy_child_result(), C) == 'blocked'
    assert cw.failure_root_cause(legacy_child_result())['backend_root_cause']['code'] == frc.UNAVAILABLE
    assert cw.classify(legacy_child_result(code='project_lock_busy', message='RuntimeError: busy'), C) == 'transient'
    assert cw.classify(legacy_child_result(code='io_error', message='OSError: disk'), C) == 'transient'
    assert cw.classify(legacy_child_result(truncate=True), C) == 'transient'
    assert cw.classify(legacy_child_result(tamper=True), C) == 'transient'
    assert cw.classify(legacy_child_result(returncode=1), C) == 'transient'
    # 既有：真实瞬时（无结构化原因）、资源停止、cleanup_unconfirmed、启动身份竞态
    assert cw.classify({'status': 'failed', 'error_code': 'internal_error'}, C) == 'transient'
    assert cw.classify({'status': 'stopped', 'stop_reason': 'task_memory_limit', 'error_code': 'task_memory_limit'}, C) == 'resource_stop'
    assert cw.classify({'status': 'stopped', 'stop_reason': 'task_timeout'}, C) == 'resource_stop'
    assert cw.classify(dict(det, status='cleanup_unconfirmed'), C) == 'cleanup_unconfirmed'
    race = dict(wf.blocked_result([wf.finding('input_or_contract_invalid', 'ValueError: bounded launch PID was reused')]),
                error_code='input_or_contract_invalid')
    assert cw.classify(race, C) == 'transient'


# ------------------------------------------------------------------ 编排：首次与续跑
def deterministic_outcome(code='typesetting_source_fallback_cap_exceeded'):
    def outcome(chunk):
        return {'status': 'failed', 'error_code': code,
                'findings': [wf.finding(code, 'typesetting receipt')],
                'root_cause': {'code': code, 'retry': 'deterministic', 'stage': 'post_typesetting', 'verified': True,
                               'details': {'violations': [{'scope': 'page', 'page_index': 0, 'page': 1, 'count': 14, 'cap': 12}]}}}
    return outcome


def unavailable_outcome(chunk):
    return {'status': 'failed', 'error_code': frc.UNAVAILABLE, 'findings': [],
            'root_cause': dict(frc.unavailable('no_structured_cause'), verified=True)}


def test_deterministic_chunk_failure_one_attempt_root_cause_on_top_and_resume_does_not_rerun(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner(outcomes={'c002': deterministic_outcome()})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and first['error_code'] == 'chunk_failed' and first['merged'] is False
    assert runner.calls == ['c001', 'c002', 'c003']                       # 只 1 次尝试
    assert first['root_cause']['code'] == 'typesetting_source_fallback_cap_exceeded'
    assert first['root_cause']['chunk'] == 'c002' and first['root_cause']['details']['violations'][0]['cap'] == 12
    c002 = next(c for c in first['chunks'] if c['id'] == 'c002')
    assert c002['attempts'] == 1 and c002['error_code'] == 'typesetting_source_fallback_cap_exceeded'
    assert first['findings'][0]['details']['chunks'][0]['root_cause']['code'] == 'typesetting_source_fallback_cap_exceeded'
    assert 'outputs' not in first and not list((tmp_path / 'out').glob('merged-*'))
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls == []                 # 续跑：不重跑确定性失败
    assert second['deterministic_failures_not_reexecuted'] == ['c002'] and second['reused_chunks'] == ['c001', 'c003']
    assert second['root_cause']['code'] == 'typesetting_source_fallback_cap_exceeded' and second['root_cause']['invocation'] == 1
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    entry = state['chunk_table']['c002']
    assert len(entry['attempts']) == 1 and entry['not_reexecuted_by_invocations'] == [2]
    assert entry['failure']['first_root_cause']['code'] == 'typesetting_source_fallback_cap_exceeded'
    assert not list((tmp_path / 'out').glob('merged-*'))                  # 不部分交付


def test_deterministic_failure_reruns_on_resume_when_its_recorded_identity_changed(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c002': deterministic_outcome()}))
    assert _main(chunked_args(tmp_path, pdf, freeze_path), capsys)[0] == wf.EXIT_BLOCKED
    state_path = tmp_path / 'rc' / cw.STATE_NAME
    state = json.loads(state_path.read_text())
    state['chunk_table']['c002']['failure']['identity']['implementation']['scripts/failure_root_cause.py'] = 'older'
    state_path.write_text(json.dumps(state))
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == 0 and runner.calls == ['c002'] and second['deterministic_failures_not_reexecuted'] == []


def test_unavailable_root_cause_is_retried_once_and_rerun_on_resume(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner(outcomes={'c001': unavailable_outcome})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls[:2] == ['c001', 'c001']
    assert first['root_cause']['code'] == frc.UNAVAILABLE and first['chunks'][0]['attempts'] == 2
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == 0 and runner.calls == ['c001'] and second['deterministic_failures_not_reexecuted'] == []


def test_transient_then_success_and_legacy_contract_refusal_not_retried(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    seen = {'n': 0}

    def once(chunk):
        seen['n'] += 1
        return unavailable_outcome(chunk) if seen['n'] == 1 else None
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c001': once}))
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == 0 and result['chunks'][0]['attempts'] == 2 and result['merged'] is True
    runner = FakeChunkRunner(outcomes={'c003': lambda chunk: legacy_child_result()})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path / 'b', pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls == ['c001', 'c002', 'c003']
    assert result['root_cause']['code'] == 'input_or_contract_invalid' and result['root_cause']['stage'] == 'child_contract_refusal'


def test_cleanup_unconfirmed_still_stops_scheduling_with_deterministic_cause(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner(outcomes={'c001': deterministic_outcome()})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    monkeypatch.setattr(cw, 'post_attempt_guard', lambda attempt: {'live_after_attempt': [], 'confirmed': False,
                                                                   'reason_codes': ['reclaim_unconfirmed'],
                                                                   'reclaim': {'reclaimed': []}, 'unverified': [{}]})
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls == ['c001']           # 停止调度后续块
    assert result['chunks'][0]['error_code'] == 'chunk_cleanup_unconfirmed'
    assert result['root_cause']['code'] == 'typesetting_source_fallback_cap_exceeded'   # 原根因仍保留


def test_resource_stop_bisection_unchanged_and_reports_budget_root_cause(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc

    def stop(chunk):
        return {'status': 'stopped', 'stop_reason': 'task_timeout', 'elapsed_seconds': 120.4} if chunk['start'] <= 5 <= chunk['end'] else None
    runner = FakeChunkRunner(outcomes={k: stop for k in ('c002', 'c002a', 'c002aa')})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls[:4] == ['c001', 'c002', 'c002a', 'c002aa']
    assert result['root_cause']['code'] == 'chunk_page_exceeds_task_budget' and result['root_cause']['retry'] == 'resource'
