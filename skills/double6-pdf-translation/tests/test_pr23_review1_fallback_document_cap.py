"""PR #23 review-1 P2：原文保留降级的整份文档上限在分块合并时统一执行。

分母是各块排版回执记录的原始每页段落数（按整份页码）；整份上限 max(4, ceil(10% × 整份段落数))、
每页上限 max(3, ceil(20% × 该页段落数))；每块各自的最低额度不得放大整份上限。超限或回执不完整时
整份结果阻断（失败关闭），首次运行、续跑复用与不同块大小得到同一结论。"""
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]

import chunked_translation as ct  # noqa: E402
import chunked_workflow as cw  # noqa: E402
import paper_translation_workflow as wf  # noqa: E402
import qa_pipeline  # noqa: E402
from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf  # noqa: E402
from test_chunked_translation import FakeChunkRunner, _main, chunked_args, long_doc  # noqa: E402,F401


def write_receipt(out, chunk_id, per_page, fallback_pages, *, scope='chunk_merge', drop=None):
    """按后端真实格式写排版回执（_backend_working/<id>/typesetting_writeback_report.json）。"""
    work = Path(out) / '_backend_working' / chunk_id
    work.mkdir(parents=True, exist_ok=True)
    rows = [{'code': 'overflow_source_fallback', 'page_index': p, 'paragraph_id': f'{chunk_id}-p{p}-{i}',
             'role': 'table_cell', 'category': 'table_cell', 'source_text': '物理科学', 'translated_text': 'Physical Sciences'}
            for i, p in enumerate(fallback_pages)]
    cap = osf.cap_violations(list(fallback_pages), dict(per_page))
    cap.update(status='applied' if rows else 'none', document_cap_scope=scope)
    if drop == 'segment_counts':
        cap.pop('paragraphs_per_page')
    receipt = {'stage': 'post_typesetting', 'status': 'needs_review' if rows else 'passed', 'failures': [],
               'source_fallbacks': rows, 'source_fallback_count': len(rows), 'source_fallback_cap': cap}
    (work / 'typesetting_writeback_report.json').write_text(json.dumps(receipt), encoding='utf-8')


def chunk_quality(out, chunk_id, per_page, fallback_pages, *, drop=None):
    """真实 qa_pipeline 审计回执 → 与块综合质量相同的 pending / overflow_source_fallback_check 字段。"""
    write_receipt(out, chunk_id, per_page, fallback_pages, drop=drop)
    audit = qa_pipeline.audit_overflow_source_fallbacks(out)
    quality = {'status': 'unverified' if audit['pending'] else 'pass', 'quality_pass': False, 'issues': [],
               'pending': list(audit['pending']),
               'overflow_source_fallback_check': {'count': audit['count'], 'receipts': audit['receipts']}}
    if drop == 'fallback_records':
        quality['overflow_source_fallback_check']['receipts'][0]['fallbacks'] = []
    if drop == 'receipt':
        quality.pop('overflow_source_fallback_check')
    return quality


def chunked(tmp_path, sizes, segments, fallbacks, drop=None):
    """segments：整份文档每页段落数（1 起页码 → 数）；fallbacks：整份页码列表；sizes：块页数列表。"""
    rows, start = [], 1
    for index, size in enumerate(sizes):
        cid = f'c{index + 1:03d}'
        per_page = {p - start: segments[p] for p in range(start, start + size)}
        local = [p - start for p in fallbacks if start <= p < start + size]
        quality = chunk_quality(tmp_path / f'{"-".join(map(str, sizes))}-{cid}', cid, per_page, local,
                                drop=drop if index == 0 else None)
        rows.append({'chunk': {'id': cid, 'start': start, 'end': start + size - 1, 'pages': size}, 'quality': quality})
        start += size
    return ct.aggregate_quality(rows, [])


EIGHT = {p: 5 for p in range(1, 9)}          # 8 页 × 5 段 = 40 段 → 整份上限 max(4, 4) = 4


def test_within_document_cap_stays_unverified_never_pass(tmp_path):
    result = chunked(tmp_path, [4, 4], EIGHT, [1, 3, 6])
    cap = result['overflow_source_fallback_document_cap']
    assert cap['status'] == 'within_cap' and cap['document_cap'] == 4 and cap['segment_count'] == 40 and cap['count'] == 3
    assert result['status'] == 'unverified' and result['quality_pass'] is False
    assert [(f['chunk'], f['document_page'], f['paragraph_id']) for f in cap['fallbacks']] == [
        ('c001', 1, 'c001-p0-0'), ('c001', 3, 'c001-p2-1'), ('c002', 6, 'c002-p1-0')]
    assert cap['chunk_denominators'] == {'c001': {'pages': [1, 4], 'segment_count': 20},
                                         'c002': {'pages': [5, 8], 'segment_count': 20}}


def test_over_document_cap_fails_closed_even_when_each_chunk_is_within_its_own_cap(tmp_path):
    result = chunked(tmp_path, [4, 4], EIGHT, [1, 2, 3, 4, 5, 6, 7, 8])
    cap = result['overflow_source_fallback_document_cap']
    assert cap['status'] == 'exceeded' and cap['document_cap'] == 4 and cap['count'] == 8
    assert result['status'] == 'fail'
    issue = [i for i in result['issues'] if i['id'] == 'overflow_source_fallback_cap_exceeded'][0]
    assert issue['severity'] == 'blocker' and issue['violations'] == [{'scope': 'document', 'count': 8, 'cap': 4}]


def test_page_cap_uses_original_page_numbering(tmp_path):
    segs = {**EIGHT, 6: 10, 1: 100, 2: 100, 3: 100, 4: 100}
    result = chunked(tmp_path, [4, 4], segs, [6, 6, 6, 6])
    cap = result['overflow_source_fallback_document_cap']
    assert {'scope': 'page', 'page_index': 6, 'count': 4, 'cap': 3} in cap['violations']
    assert result['status'] == 'fail'


@pytest.mark.parametrize('fallbacks,expected', [([1, 3, 6], 'within_cap'), ([1, 2, 3, 4, 5, 6, 7, 8], 'exceeded'),
                                                ([2, 5, 7, 8], 'within_cap'), ([1, 2, 5, 6, 8], 'exceeded')])
def test_different_chunk_sizes_give_the_same_verdict(tmp_path, fallbacks, expected):
    verdicts = set()
    for sizes in ([4, 4], [2, 2, 2, 2], [1] * 8, [3, 5], [8]):
        result = chunked(tmp_path / f'case-{"-".join(map(str, fallbacks))}', sizes, EIGHT, fallbacks)
        cap = result['overflow_source_fallback_document_cap']
        verdicts.add((cap['status'], cap['document_cap'], cap['segment_count'], cap['count'], result['status']))
    assert len(verdicts) == 1, verdicts
    assert next(iter(verdicts))[0] == expected


@pytest.mark.parametrize('drop', ['segment_counts', 'fallback_records', 'receipt'])
def test_missing_or_incomplete_receipts_fail_closed(tmp_path, drop):
    # 第一块有降级（c001 第 2 页）；第二块的降级（第 6 页）记录完整。缺分母、缺逐条记录、缺回执都失败关闭。
    result = chunked(tmp_path, [4, 4], EIGHT, [2, 6], drop=drop)
    cap = result['overflow_source_fallback_document_cap']
    assert cap['status'] == 'incomplete' and cap['code'] == 'overflow_source_fallback_receipt_incomplete'
    assert cap['problems'][0]['chunk'] == 'c001'
    assert result['status'] == 'fail'
    assert any(i['id'] == 'overflow_source_fallback_receipt_incomplete' and i['severity'] == 'blocker' for i in result['issues'])


@pytest.mark.parametrize('drop', ['segment_counts', 'receipt'])
def test_chunk_without_fallbacks_but_missing_denominators_still_fails_closed(tmp_path, drop):
    # 第一块没有降级但缺原始段落数：整份分母不完整，无法核对整份上限，失败关闭。
    result = chunked(tmp_path, [4, 4], EIGHT, [6], drop=drop)
    assert result['overflow_source_fallback_document_cap']['status'] == 'incomplete' and result['status'] == 'fail'


def test_no_fallbacks_anywhere_is_not_blocked_by_this_gate(tmp_path):
    result = chunked(tmp_path, [4, 4], EIGHT, [])
    assert result['overflow_source_fallback_document_cap']['status'] == 'none'
    assert not any(i['id'].startswith('overflow_source_fallback') for i in result['issues'])


def test_single_document_receipt_with_deferred_cap_fails_closed(tmp_path, monkeypatch):
    """单份翻译里出现“整份上限推迟到分块合并”的回执：整份上限没有在任何地方执行，失败关闭。"""
    write_receipt(tmp_path, 'doc', {0: 5}, [0], scope='chunk_merge')
    audit = qa_pipeline.audit_overflow_source_fallbacks(tmp_path)
    assert audit['receipts'][0]['document_cap_scope'] == 'chunk_merge'
    assert audit['receipts'][0]['paragraphs_per_page'] == {'0': 5}
    monkeypatch.setattr(qa_pipeline, 'evaluate_quality_packet', lambda *a, **k: {'status': 'pass', 'quality_pass': True, 'issues': []})
    monkeypatch.setattr(qa_pipeline, 'final_pdf_from_manifest', lambda *a, **k: tmp_path / 'x.pdf')
    monkeypatch.setattr(qa_pipeline, 'audit_technical_receipt', lambda *a, **k: {'issues': [], 'pending': []})
    monkeypatch.setattr(qa_pipeline, 'render_residue_gate', lambda *a, **k: {'severity': 'none'})
    (tmp_path / 's.pdf').write_bytes(b'%PDF-1.4 stub')
    (tmp_path / 'x.pdf').write_bytes(b'%PDF-1.4 stub')
    qa_pipeline.attach_pipeline_quality({}, source=tmp_path / 's.pdf', output_dir=tmp_path)
    single = json.loads((tmp_path / 'comprehensive_quality.json').read_text())
    assert single['status'] == 'fail' and single['quality_pass'] is False
    assert any(i['id'] == 'overflow_source_fallback_cap_scope_mismatch' and i['severity'] == 'blocker' for i in single['issues'])
    qa_pipeline.attach_pipeline_quality({}, source=tmp_path / 's.pdf', output_dir=tmp_path, chunk_mode=True)
    chunk = json.loads((tmp_path / 'comprehensive_quality.json').read_text())
    assert chunk['status'] == 'unverified' and chunk['quality_pass'] is False   # 分块：待合并时统一核对，块内永不 pass


def test_document_cap_scope_env(monkeypatch):
    monkeypatch.delenv(osf.DOCUMENT_CAP_SCOPE_ENV, raising=False)
    assert osf.document_cap_scope() == 'document'
    monkeypatch.setenv(osf.DOCUMENT_CAP_SCOPE_ENV, 'chunk_merge')
    assert osf.document_cap_scope() == 'chunk_merge'
    monkeypatch.setenv(osf.DOCUMENT_CAP_SCOPE_ENV, 'anything-else')
    assert osf.document_cap_scope() == 'document'


# ------------------------------------------------------------------ 编排：首次运行 / 续跑复用 走同一整份上限
class FallbackChunkRunner(FakeChunkRunner):
    """在 FakeChunkRunner 的真实产物之上，按后端格式写排版回执，并用真实 qa 审计生成块综合质量字段。"""

    def __init__(self, fallbacks, per_page=5, **kw):
        super().__init__(**kw)
        self.fallbacks, self.per_page = fallbacks, per_page

    def __call__(self, wf_module, args, freeze_path, chunk, attempt, context_path):
        result = super().__call__(wf_module, args, freeze_path, chunk, attempt, context_path)
        out = attempt / 'out'
        if not (out / 'comprehensive_quality.json').is_file():
            return result
        local = [p - chunk['start'] for p in self.fallbacks if chunk['start'] <= p <= chunk['end']]
        quality = chunk_quality(out, chunk['id'], {i: self.per_page for i in range(chunk['pages'])}, local)
        (out / 'comprehensive_quality.json').write_text(json.dumps(quality))
        result['quality_status'] = quality['status']
        (attempt / 'receipts' / 'WORKFLOW_CANDIDATE.json').write_text(json.dumps(result))
        return result


def test_workflow_blocks_over_document_cap_on_first_run_and_on_resume(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc                     # 10 页 × 5 段 = 50 段 → 整份上限 5
    over = [1, 2, 3, 5, 6, 7]                       # 每块各 3 条：块内（20 段，块上限 4）都不超
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FallbackChunkRunner(over))
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and first['status'] == 'blocked'
    assert first['error_code'] == 'overflow_source_fallback_cap_exceeded' and 'outputs' not in first
    cap = first['overflow_source_fallback_document_cap']
    assert cap['document_cap'] == 5 and cap['segment_count'] == 50 and cap['count'] == 6
    # 续跑：所有块逐 sha 复用，重新合并，结论相同。
    runner = FallbackChunkRunner(over)
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert runner.calls == [] and second['reused_chunks'] == ['c001', 'c002', 'c003']
    assert code == wf.EXIT_BLOCKED and second['error_code'] == 'overflow_source_fallback_cap_exceeded'
    assert second['overflow_source_fallback_document_cap']['document_cap'] == 5
    assert (tmp_path / 'rc/WORKFLOW_CHUNKED_CANDIDATE.invocation-2.json').is_file()


def test_workflow_within_document_cap_first_run_and_resume_stay_unverified(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    within = [1, 6, 9]
    blocked = dict(wf.blocked_result([wf.finding('x', 'transient env problem')]), error_code='x')
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FallbackChunkRunner(within, outcomes={'c003': blocked}))
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and first['error_code'] == 'chunk_failed'
    runner = FallbackChunkRunner(within)
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == 0 and runner.calls == ['c003'] and second['reused_chunks'] == ['c001', 'c002']
    assert second['quality_status'] == 'unverified' and second['overflow_source_fallback_count'] == 3
    cap = second['overflow_source_fallback_document_cap']
    assert cap['status'] == 'within_cap' and cap['document_cap'] == 5 and cap['count'] == 3
