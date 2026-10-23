"""PR #23 review-2：排版回执的声明计数、逐条数组、状态、上限、作用域与原始分母必须一致。

不可核对（损坏、缺字段、自相矛盾、文件在质量审计后被改动、某块缺回执）时，整份失败关闭，
稳定代码 overflow_source_fallback_receipt_incomplete；首次运行与续跑一致。没有旧格式兼容规则。"""
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]

import chunked_translation as ct  # noqa: E402
import chunked_workflow as cw  # noqa: E402
import paper_translation_workflow as wf  # noqa: E402
import qa_pipeline as qa  # noqa: E402
from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf  # noqa: E402
from test_chunked_translation import FakeChunkRunner, _main, chunked_args, long_doc  # noqa: E402,F401

CODE = 'overflow_source_fallback_receipt_incomplete'


def receipt(rows=2, pages=4, per_page=5, scope='chunk_merge', **override):
    fallbacks = [{'code': 'overflow_source_fallback', 'page_index': i % pages, 'paragraph_id': f'p{i}', 'role': 'toc_entry',
                  'category': 'toc_entry', 'source_text': f'Page {i}', 'translated_text': f'第 {i} 页'} for i in range(rows)]
    ppp = {str(i): per_page for i in range(pages)}
    data = {'stage': 'post_typesetting', 'status': 'needs_review' if rows else 'passed', 'page_count': pages, 'failures': [],
            'source_fallbacks': fallbacks, 'source_fallback_count': rows,
            'source_fallback_cap': {'document_cap': 4, 'count': rows, 'violations': [], 'paragraphs_per_page': ppp,
                                    'segment_count': per_page * pages, 'status': 'applied' if rows else 'none',
                                    'document_cap_scope': scope}}
    for key, value in override.items():
        if key.startswith('cap_'):
            data['source_fallback_cap'][key[4:]] = value
        else:
            data[key] = value
    return data


def write(out, chunk_id, data):
    work = Path(out) / '_backend_working' / chunk_id
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'typesetting_writeback_report.json'
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
    return path


def quality_of(out):
    audit = qa.audit_overflow_source_fallbacks(out)
    return {'status': 'unverified' if audit['pending'] else 'pass', 'quality_pass': False, 'issues': [], 'pending': audit['pending'],
            'overflow_source_fallback_check': {'count': audit['count'], 'receipts': audit['receipts'],
                                               'invalid': audit['invalid'], 'count_verifiable': audit['count_verifiable']}}


def aggregate(*qualities):
    rows = [{'chunk': {'id': f'c{i + 1:03d}', 'start': 4 * i + 1, 'end': 4 * i + 4, 'pages': 4}, 'quality': q}
            for i, q in enumerate(qualities)]
    return ct.aggregate_quality(rows, [])


# ------------------------------------------------------------------ 回执自身一致性
CONTRADICTIONS = {
    'declared_count_above_array': dict(source_fallback_count=3),
    'array_above_declared_count': dict(source_fallback_count=1),
    'cap_count_mismatch': dict(cap_count=5),
    'needs_review_with_zero_declared': dict(rows=0, status='needs_review'),
    'passed_while_rows_present': dict(status='passed'),
    'declared_count_missing': dict(source_fallback_count=None),
    'cap_missing': dict(source_fallback_cap=None),
    'segment_counts_missing': dict(cap_paragraphs_per_page=None),
    'segment_total_mismatch': dict(cap_segment_count=99),
    'scope_invalid': dict(cap_document_cap_scope='whatever'),
    'cap_status_invalid': dict(cap_status='bogus'),
    'record_page_outside_receipt': dict(rows=1, pages=1, source_fallbacks=[{'page_index': 7, 'paragraph_id': 'x'}]),
    'record_without_paragraph_id': dict(rows=1, source_fallbacks=[{'page_index': 0}]),
    'revoked_without_failures': dict(rows=0, cap_status='revoked_cap_exceeded', cap_count=4),
    'legacy_receipt_without_fallback_fields': 'legacy',
}


def build(name):
    spec = CONTRADICTIONS[name]
    if spec == 'legacy':
        return {'stage': 'post_typesetting', 'status': 'passed', 'failures': []}
    spec = dict(spec)
    rows, pages = spec.pop('rows', 2), spec.pop('pages', 4)
    data = receipt(rows=rows, pages=pages, **{k: v for k, v in spec.items() if v is not None})
    for key, value in spec.items():
        if value is None:
            (data['source_fallback_cap'] if key.startswith('cap_') else data).pop(key[4:] if key.startswith('cap_') else key, None)
    if 'source_fallback_cap' in spec and spec['source_fallback_cap'] is None:
        data.pop('source_fallback_cap', None)
    return data


@pytest.mark.parametrize('name', sorted(CONTRADICTIONS))
def test_contradictory_or_incomplete_receipt_is_not_counted_as_zero_and_blocks(tmp_path, name):
    data = build(name)
    assert osf.validate_receipt(data), name
    write(tmp_path / 'c1', 'c001', data)
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    q1 = quality_of(tmp_path / 'c1')
    assert q1['overflow_source_fallback_check']['count_verifiable'] is False and not q1['overflow_source_fallback_check']['receipts']
    assert [p['rule'] for p in q1['pending']] == ['overflow_source_fallback_receipt_invalid']
    result = aggregate(q1, quality_of(tmp_path / 'c2'))
    cap = result['overflow_source_fallback_document_cap']
    assert cap['status'] == 'incomplete' and cap['code'] == CODE and cap['count'] is None
    assert result['status'] == 'fail' and any(i['id'] == CODE and i['severity'] == 'blocker' for i in result['issues'])


def test_corrupted_json_receipt_blocks(tmp_path):
    write(tmp_path / 'c1', 'c001', '{broken')
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    result = aggregate(quality_of(tmp_path / 'c1'), quality_of(tmp_path / 'c2'))
    assert result['overflow_source_fallback_document_cap']['problems'][0]['reason'] == 'receipt_invalid'
    assert result['status'] == 'fail' and any(i['id'] == CODE for i in result['issues'])


def test_consistent_receipts_are_valid():
    assert osf.validate_receipt(receipt(rows=0)) == []
    assert osf.validate_receipt(receipt(rows=3)) == []
    revoked = receipt(rows=0, status='blocked', failures=[{'reason': 'hard_readable_floor_overflow'}],
                      cap_status='revoked_cap_exceeded', cap_count=6)
    assert osf.validate_receipt(revoked) == []          # 后端撤销后整份失败的回执本身是一致的
    no_status = receipt(rows=0); no_status['source_fallback_cap'].pop('status')
    assert osf.validate_receipt(no_status) == []        # 未写上限状态：按“无降级”核对，计数仍须一致


def test_valid_zero_fallback_receipts_stay_ordinary(tmp_path):
    write(tmp_path / 'c1', 'c001', receipt(rows=0))
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    result = aggregate(quality_of(tmp_path / 'c1'), quality_of(tmp_path / 'c2'))
    assert result['status'] == 'pass' and result['overflow_source_fallback_document_cap']['status'] == 'none'
    assert result['overflow_source_fallback_document_cap']['segment_count'] == 40


def test_within_and_over_cap_positives_still_hold(tmp_path):
    write(tmp_path / 'a1', 'c001', receipt(rows=2))
    write(tmp_path / 'a2', 'c002', receipt(rows=1))
    within = aggregate(quality_of(tmp_path / 'a1'), quality_of(tmp_path / 'a2'))
    assert within['status'] == 'unverified' and within['overflow_source_fallback_document_cap']['status'] == 'within_cap'
    write(tmp_path / 'b1', 'c001', receipt(rows=3))
    write(tmp_path / 'b2', 'c002', receipt(rows=3))
    over = aggregate(quality_of(tmp_path / 'b1'), quality_of(tmp_path / 'b2'))
    assert over['status'] == 'fail' and over['overflow_source_fallback_document_cap']['status'] == 'exceeded'


def test_missing_receipt_in_a_chunk_that_had_fallbacks_blocks(tmp_path):
    path = write(tmp_path / 'c1', 'c001', receipt(rows=2))
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    q1 = quality_of(tmp_path / 'c1')
    path.unlink()                                       # 质量审计后回执消失（例如续跑前被删）
    result = aggregate(q1, quality_of(tmp_path / 'c2'))
    assert [p['reason'] for p in result['overflow_source_fallback_document_cap']['problems']] == ['receipt_file_missing']
    assert result['status'] == 'fail'


def test_chunk_without_any_receipt_blocks_even_without_declared_fallbacks(tmp_path):
    """没有旧格式兼容规则：没有回执就没有“0 条降级”的正面证据。"""
    (tmp_path / 'c1').mkdir()
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    result = aggregate(quality_of(tmp_path / 'c1'), quality_of(tmp_path / 'c2'))
    assert result['overflow_source_fallback_document_cap']['problems'] == [{'chunk': 'c001', 'reason': 'typesetting_receipt_missing'}]
    assert result['status'] == 'fail'


def test_receipt_changed_after_quality_audit_blocks(tmp_path):
    path = write(tmp_path / 'c1', 'c001', receipt(rows=2))
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    q1 = quality_of(tmp_path / 'c1')
    path.write_text(json.dumps(receipt(rows=0)), encoding='utf-8')      # 改成“0 条”的一致回执也不行
    result = aggregate(q1, quality_of(tmp_path / 'c2'))
    assert result['overflow_source_fallback_document_cap']['problems'][0]['reason'] == 'receipt_file_changed'
    assert result['status'] == 'fail'


def test_quality_summary_must_agree_with_receipt(tmp_path):
    write(tmp_path / 'c1', 'c001', receipt(rows=2))
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    q1 = quality_of(tmp_path / 'c1')
    q1['pending'] = []                                   # 综合质量里抹掉降级待复核项
    q1['overflow_source_fallback_check']['count'] = 0
    result = aggregate(q1, quality_of(tmp_path / 'c2'))
    assert result['overflow_source_fallback_document_cap']['problems'][0]['reason'] == 'quality_summary_disagrees_with_receipt'
    assert result['status'] == 'fail'


def test_document_scope_receipt_in_chunk_merge_blocks(tmp_path):
    write(tmp_path / 'c1', 'c001', receipt(rows=0, scope='document'))
    write(tmp_path / 'c2', 'c002', receipt(rows=0))
    result = aggregate(quality_of(tmp_path / 'c1'), quality_of(tmp_path / 'c2'))
    assert result['overflow_source_fallback_document_cap']['problems'][0]['reason'] == 'receipt_scope_not_chunk_merge'


def _stub_attach(monkeypatch, tmp_path):
    monkeypatch.setattr(qa, 'evaluate_quality_packet', lambda *a, **k: {'status': 'pass', 'quality_pass': True, 'issues': []})
    monkeypatch.setattr(qa, 'final_pdf_from_manifest', lambda *a, **k: tmp_path / 'x.pdf')
    monkeypatch.setattr(qa, 'audit_technical_receipt', lambda *a, **k: {'issues': [], 'pending': []})
    monkeypatch.setattr(qa, 'render_residue_gate', lambda *a, **k: {'severity': 'none'})
    (tmp_path / 's.pdf').write_bytes(b'%PDF-1.4 stub')
    (tmp_path / 'x.pdf').write_bytes(b'%PDF-1.4 stub')


@pytest.mark.parametrize('chunk_mode', [False, True])
def test_comprehensive_quality_fails_with_stable_code_on_invalid_receipt(tmp_path, monkeypatch, chunk_mode):
    _stub_attach(monkeypatch, tmp_path)
    write(tmp_path, 'doc', receipt(rows=0, source_fallback_count=4, cap_count=4, status='needs_review'))
    qa.attach_pipeline_quality({}, source=tmp_path / 's.pdf', output_dir=tmp_path, chunk_mode=chunk_mode)
    result = json.loads((tmp_path / 'comprehensive_quality.json').read_text())
    assert result['status'] == 'fail' and result['quality_pass'] is False
    issue = [i for i in result['issues'] if i['id'] == CODE][0]
    assert issue['severity'] == 'blocker' and issue['evidence'][0]['declared_count'] == 4
    assert result['overflow_source_fallback_check']['count_verifiable'] is False


# ------------------------------------------------------------------ 编排：首次运行 / 续跑
class CorruptingRunner(FakeChunkRunner):
    """chunk 指定的块：后端回执声明 4 条降级但数组为空（复审 Case A），真实 qa 审计写综合质量。"""

    def __init__(self, bad, monkeypatch, tmp_path, **kw):
        super().__init__(**kw)
        self.bad = bad
        _stub_attach(monkeypatch, tmp_path)

    def __call__(self, wf_module, args, freeze_path, chunk, attempt, context_path):
        result = super().__call__(wf_module, args, freeze_path, chunk, attempt, context_path)
        out = attempt / 'out'
        if chunk['id'] in self.bad and (out / 'comprehensive_quality.json').is_file():
            write(out, chunk['id'], receipt(rows=0, pages=chunk['pages'], source_fallback_count=4, cap_count=4, status='needs_review'))
            qa.attach_pipeline_quality({}, source=Path(chunk['source_ref']['path']), output_dir=out, chunk_mode=True)
            result['quality_status'] = json.loads((out / 'comprehensive_quality.json').read_text())['status']
            (attempt / 'receipts' / 'WORKFLOW_CANDIDATE.json').write_text(json.dumps(result))
        return result


def test_workflow_first_run_with_contradictory_receipt_is_blocked(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', CorruptingRunner({'c002'}, monkeypatch, tmp_path))
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and result['status'] == 'blocked' and result['error_code'] == CODE
    assert result['merged'] is False and 'outputs' not in result


def test_workflow_resume_with_receipt_corrupted_after_completion_is_blocked(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner())
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == 0 and first['overflow_source_fallback_document_cap']['status'] == 'none'
    receipt_path = next((tmp_path / 'out/chunks/c002').glob('attempt-*/out/_backend_working/c002/typesetting_writeback_report.json'))
    receipt_path.write_text('{broken', encoding='utf-8')
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert runner.calls == [] and second['reused_chunks'] == ['c001', 'c002', 'c003']
    assert code == wf.EXIT_BLOCKED and second['error_code'] == CODE and 'outputs' not in second
    problems = second['overflow_source_fallback_document_cap']['problems']
    assert problems == [{'chunk': 'c002', 'reason': 'receipt_file_changed', 'path': str(receipt_path)}]
    # 再续跑一次：结论不变（稳定代码、不交付）。
    code, third = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == wf.EXIT_BLOCKED and third['error_code'] == CODE
