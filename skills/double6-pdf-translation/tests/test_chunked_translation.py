"""rc.9 长文档分块（chunked-candidate）：成对正/负例，断言真实结果。

划分、合并、导航恢复、页面指纹、质量聚合、术语一致性都在真实 PDF 上运行；编排测试里计划与合并
是真实的有界子进程（run_bounded），只把“单块 candidate”替换为写出真实 PDF 产物的确定性执行器
（真实翻译链路由端到端运行覆盖）；遗留进程回收用真实的 setsid 进程树。"""
import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import fitz
import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import chunked_translation as ct  # noqa: E402
import chunked_workflow as cw  # noqa: E402
import paper_translation_workflow as wf  # noqa: E402

GIB = 1024 ** 3
BODY = 'Risk management of artificial intelligence systems requires measurement and governance today.'


def text_pdf(path, pages, *, lines=None, header='Report Header 2026', image_on=(), links=(), toc=None, labels=None):
    """每页：页眉（重复）、正文、页脚页码；lines[i] 覆盖第 i 页正文最后一行。"""
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 40), header, fontsize=9)
        y = 120
        for _ in range(8):
            page.insert_text((72, y), BODY, fontsize=10)
            y += 14
        last = (lines or {}).get(index, 'The page closes with a full sentence.')
        page.insert_text((72, y), last, fontsize=10)
        page.insert_text((290, 820), str(index + 1), fontsize=9)
        if index in image_on:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pix.set_rect(pix.irect, ((index * 37) % 255, 90, 160))
            page.insert_image(fitz.Rect(400, 500, 480, 580), pixmap=pix)
    for page_no, target in links:
        doc[page_no - 1].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(72, 110, 200, 124), 'page': target - 1,
                                      'to': fitz.Point(72, 100)})
    if toc:
        doc.set_toc(toc)
    if labels:
        doc.set_page_labels(labels)
    doc.save(str(path))
    doc.close()
    return Path(path)


def signals_of(path):
    with fitz.open(path) as doc:
        return ct.document_signals(doc)


# ------------------------------------------------------------------ 划分
def test_plan_covers_every_page_once_within_limits():
    routes = ['digital_pdf'] * 11
    signals = [{'after_page': i + 1, 'hard_unsafe': False, 'safe': True} for i in range(10)]
    chunks = ct.plan_chunks(signals, routes, ct.CHUNKING_CONTRACT)
    pages = [p for c in chunks for p in range(c['start'], c['end'] + 1)]
    assert pages == list(range(1, 12))
    assert [c['pages'] for c in chunks] == [4, 4, 3]
    assert [c['id'] for c in chunks] == ['c001', 'c002', 'c003']


def test_plan_moves_boundary_off_a_continued_table_but_not_off_a_clean_page(tmp_path):
    clean = text_pdf(tmp_path / 'clean.pdf', 8)
    chunks = ct.plan_chunks(signals_of(clean), ['digital_pdf'] * 8, ct.CHUNKING_CONTRACT)
    assert [(c['start'], c['end']) for c in chunks] == [(1, 4), (5, 8)]
    # 第 4 页末“continued on next page”：4|5 是 hard 边界，划分改在 3|4
    tabled = text_pdf(tmp_path / 'tabled.pdf', 8, lines={3: 'Table 2: Measured values (continued on next page)'})
    signals = signals_of(tabled)
    assert signals[3]['continued_caption'] and signals[3]['hard_unsafe']
    chunks = ct.plan_chunks(signals, ['digital_pdf'] * 8, ct.CHUNKING_CONTRACT)
    assert [(c['start'], c['end']) for c in chunks][0] == (1, 3)
    assert all(not (c['boundary_after'] or {}).get('hard_unsafe') for c in chunks)


def test_formula_and_paragraph_continuation_signals(tmp_path):
    pdf = text_pdf(tmp_path / 'f.pdf', 4, lines={0: 'where the loss is L = a + b +', 1: 'the measurement of exam-',
                                                 2: 'which is summarised in the following'})
    signals = signals_of(pdf)
    assert signals[0]['formula_continues'] and signals[0]['hard_unsafe']
    # 连字符断词不是公式；段落未结束是软信号（记录续接，不阻止切分）
    assert not signals[1]['formula_continues'] and signals[1]['paragraph_continues'] and not signals[1]['hard_unsafe']
    assert signals[2]['paragraph_continues'] and not signals[2]['safe']
    # 正常句号结尾 + 页眉页脚（重复行）被识别并忽略
    clean = signals_of(text_pdf(tmp_path / 'c.pdf', 4))
    assert all(s['safe'] for s in clean)
    assert all('Report Header' not in s['head_text'] for s in clean)


def test_per_chunk_routing_keeps_chunks_route_homogeneous():
    kinds = ['native_text', 'native_text', 'sparse_text', 'native_text', 'native_text']
    routes = ct.page_routes(kinds, 'per_chunk')
    assert routes == ['digital_pdf'] * 5
    signals = [{'after_page': i + 1, 'hard_unsafe': False, 'safe': True} for i in range(4)]
    chunks = ct.plan_chunks(signals, routes, ct.CHUNKING_CONTRACT)
    assert [(c['start'], c['end'], c['route']) for c in chunks] == [(1, 4, 'digital_pdf'), (5, 5, 'digital_pdf')]
    # 显式路线：所有页同一路线（不合格页由该路线既有门拒绝，不在这里改路线）
    assert ct.page_routes(kinds, 'digital_pdf') == ['digital_pdf'] * 5
    with pytest.raises(ValueError):
        ct.page_routes(kinds, 'latex_verified')


def test_split_range_bisects_down_to_single_pages():
    chunk = {'id': 'c003', 'start': 9, 'end': 12, 'route': 'digital_pdf', 'pages': 4}
    left, right = ct.split_range(chunk)
    assert (left['id'], left['start'], left['end']) == ('c003a', 9, 10)
    assert (right['id'], right['start'], right['end']) == ('c003b', 11, 12)
    a, b = ct.split_range(right)
    assert (a['pages'], b['pages']) == (1, 1) and ct.split_range(a) == []


# ------------------------------------------------------------------ 合并
def _plan_for(tmp_path, pdf, bounds, route='digital_pdf'):
    with fitz.open(pdf) as doc:
        chunks = []
        for index, (start, end) in enumerate(bounds):
            chunk = {'id': f'c{index + 1:03d}', 'start': start, 'end': end, 'pages': end - start + 1, 'route': route}
            chunk['source_ref'] = ct.write_chunk_pdf(doc, chunk, tmp_path / 'chunks' / f"{chunk['id']}.pdf")
            chunks.append(chunk)
        navigation = ct.source_navigation(doc)
        count = len(doc)
    context = tmp_path / 'ctx.json'
    context.write_text(json.dumps({'protocol': ct.TERM_CONTEXT_PROTOCOL, 'term_policy': {'terms': []},
                                   'entity_map': {'entities': []}}))
    return {'page_count': count, 'navigation': navigation, 'chunks': chunks, 'document_term_context_ref': ct.file_ref(context)}


def zero_fallback_quality(out, chunk_id, pages, status='pass', issues=None):
    """真实后端格式的“0 条原文保留降级”排版回执（分块作用域、原始分母齐全）+ 真实 qa 审计生成的综合质量字段。
    PR #23 review-2：分块合并要求每块都有可核对的回执，缺失即失败关闭。"""
    import qa_pipeline
    work = Path(out) / '_backend_working' / chunk_id
    work.mkdir(parents=True, exist_ok=True)
    per_page = {str(i): 3 for i in range(pages)}
    (work / 'typesetting_writeback_report.json').write_text(json.dumps({
        'stage': 'post_typesetting', 'status': 'passed', 'page_count': pages, 'failures': [],
        'source_fallbacks': [], 'source_fallback_count': 0,
        'source_fallback_cap': {'document_cap': 4, 'page_caps': {}, 'count': 0, 'violations': [],
                                'paragraphs_per_page': per_page, 'segment_count': 3 * pages, 'status': 'none',
                                'document_cap_scope': 'chunk_merge', 'deferred_violations': []}}), encoding='utf-8')
    audit = qa_pipeline.audit_overflow_source_fallbacks(out)
    return {'status': status, 'issues': list(issues or []), 'pending': audit['pending'],
            'overflow_source_fallback_check': {'count': audit['count'], 'receipts': audit['receipts'],
                                               'invalid': audit['invalid'], 'count_verifiable': audit['count_verifiable']}}


def _rows(tmp_path, plan, statuses=None, drop_page_in=None):
    rows = []
    for chunk in plan['chunks']:
        out = tmp_path / 'outs' / chunk['id']
        out.mkdir(parents=True, exist_ok=True)
        mono = out / f"{chunk['id']}.mono.pdf"
        with fitz.open(chunk['source_ref']['path']) as doc:
            if drop_page_in == chunk['id']:
                doc.delete_page(len(doc) - 1)
            doc.save(str(mono))
        quality = out / 'comprehensive_quality.json'
        quality.write_text(json.dumps(zero_fallback_quality(out, chunk['id'], chunk['pages'],
                                                            (statuses or {}).get(chunk['id'], 'pass'))))
        rows.append({'chunk': chunk, 'outputs': {'translated_pdf': ct.file_ref(mono)},
                     'quality_ref': ct.file_ref(quality), 'quality_status': None})
    return rows


def test_merge_restores_order_links_toc_labels_and_page_identity(tmp_path):
    toc = [[1, 'Intro', 1], [1, 'Method', 3], [2, 'Detail', 5], [1, 'End', 6]]
    labels = [{'startpage': 0, 'prefix': '', 'style': 'r', 'firstpagenum': 1},
              {'startpage': 2, 'prefix': '', 'style': 'D', 'firstpagenum': 1}]
    pdf = text_pdf(tmp_path / 'src.pdf', 6, image_on=(1, 4), links=[(1, 6), (2, 3), (5, 1)], toc=toc, labels=labels)
    plan = _plan_for(tmp_path, pdf, [(1, 3), (4, 6)])
    # 拆块丢掉跨块内部链接（真实后端同样如此）
    with fitz.open(plan['chunks'][0]['source_ref']['path']) as part:
        assert not any(l.get('page') == 5 for l in part[0].get_links())
    report = ct.merge_outputs(plan, _rows(tmp_path, plan), tmp_path / 'merged', target_language='zh', input_pdf=pdf)
    assert report['issues'] == [] and report['quality_status'] == 'pass'
    merged = fitz.open(report['outputs']['translated_pdf']['path'])
    assert len(merged) == 6
    assert [row[:3] for row in merged.get_toc()] == toc
    assert merged.get_page_labels() == labels and merged[2].get_label() == '1'
    assert any(l.get('page') == 5 for l in merged[0].get_links())   # 跨块 1→6 已恢复
    assert any(l.get('page') == 0 for l in merged[4].get_links())   # 跨块 5→1 已恢复
    assert report['links']['cross_chunk'] == 2 and report['links']['source_internal'] == 3
    assert all(c['image_identity_ok'] and c['size_ok'] for c in report['page_checks'])
    assert [c['page'] for c in report['page_checks']] == [1, 2, 3, 4, 5, 6]


def test_merge_fails_closed_on_missing_page_in_a_chunk(tmp_path):
    pdf = text_pdf(tmp_path / 'src.pdf', 6, image_on=(4,))
    plan = _plan_for(tmp_path, pdf, [(1, 3), (4, 6)])
    report = ct.merge_outputs(plan, _rows(tmp_path, plan, drop_page_in='c002'), tmp_path / 'merged',
                              target_language='zh', input_pdf=pdf)
    ids = {i['id'] for i in report['issues']}
    assert {'chunk_page_count_mismatch', 'merged_page_count_mismatch'} <= ids
    quality = json.loads((tmp_path / 'merged/comprehensive_quality.json').read_text())
    assert quality['status'] == 'fail' and quality['worst_chunk_status'] == 'pass'


def test_merge_detects_swapped_pages_by_image_fingerprint(tmp_path):
    pdf = text_pdf(tmp_path / 'src.pdf', 4, image_on=(0, 1, 2, 3))
    plan = _plan_for(tmp_path, pdf, [(1, 2), (3, 4)])
    rows = _rows(tmp_path, plan)
    mono = Path(rows[1]['outputs']['translated_pdf']['path'])
    with fitz.open(mono) as doc:
        doc.move_page(1, 0)
        doc.save(str(mono.with_name('swapped.pdf')))
    rows[1]['outputs']['translated_pdf'] = ct.file_ref(mono.with_name('swapped.pdf'))
    report = ct.merge_outputs(plan, rows, tmp_path / 'merged', target_language='zh', input_pdf=pdf)
    bad = [i for i in report['issues'] if i['id'] == 'merged_page_identity_mismatch']
    assert bad and bad[0]['pages'] == [3, 4]
    # 对照：未交换的同一输入没有该问题
    clean = ct.merge_outputs(plan, _rows(tmp_path / 'b', plan), tmp_path / 'merged2', target_language='zh', input_pdf=pdf)
    assert clean['issues'] == []


def test_merge_rejects_tampered_output_and_broken_coverage(tmp_path):
    pdf = text_pdf(tmp_path / 'src.pdf', 4)
    plan = _plan_for(tmp_path, pdf, [(1, 2), (3, 4)])
    rows = _rows(tmp_path, plan)
    Path(rows[0]['outputs']['translated_pdf']['path']).write_bytes(b'%PDF-1.4 tampered')
    with pytest.raises(ValueError, match='changed after its receipt'):
        ct.merge_outputs(plan, rows, tmp_path / 'm1', target_language='zh', input_pdf=pdf)
    rows = _rows(tmp_path / 'b', plan)
    with pytest.raises(ValueError, match='order/coverage'):
        ct.merge_outputs(plan, [rows[1], rows[0]], tmp_path / 'm2', target_language='zh', input_pdf=pdf)
    with pytest.raises(ValueError, match='cover the document'):
        ct.merge_outputs(plan, rows[:1], tmp_path / 'm3', target_language='zh', input_pdf=pdf)


# ------------------------------------------------------------------ 质量
def test_merged_quality_is_never_better_than_the_worst_chunk(tmp_path):
    def chunk(i):
        return {'id': f'c{i}', 'start': i, 'end': i, 'pages': 1}

    def quality(i, s, tag):
        return zero_fallback_quality(tmp_path / f'{tag}-{i}', f'c{i}', 1, s)
    for n, combo in enumerate(itertools.product(['pass', 'unverified', 'fail', None, 'bogus'], repeat=3)):
        rows = [{'chunk': chunk(i), 'quality': (quality(i, s, n) if s else None)} for i, s in enumerate(combo)]
        result = ct.aggregate_quality(rows, [])
        effective = ['fail' if s not in ct.QUALITY_ORDER else s for s in combo]
        worst = max(effective, key=ct.QUALITY_ORDER.get)
        assert result['status'] == worst and ct.QUALITY_ORDER[result['status']] >= ct.QUALITY_ORDER[worst]
    rows = [{'chunk': chunk(1), 'quality': quality(1, 'pass', 'single')}]
    assert ct.aggregate_quality(rows, [])['status'] == 'pass'
    assert ct.aggregate_quality(rows, [{'id': 'x', 'severity': 'high'}])['status'] == 'fail'
    pending = [{'chunk': chunk(1), 'quality': dict(quality(1, 'pass', 'pending'), pending=[{'id': 'p'}])}]
    assert ct.aggregate_quality(pending, [])['status'] == 'unverified'


def test_ocr_capped_chunk_status_is_kept_in_the_merged_verdict(tmp_path):
    pdf = text_pdf(tmp_path / 'src.pdf', 4)
    plan = _plan_for(tmp_path, pdf, [(1, 2), (3, 4)])
    rows = _rows(tmp_path, plan)
    rows[1]['quality_status'] = 'unverified'          # 回执里 OCR 封顶为 unverified，文件写的是 pass
    report = ct.merge_outputs(plan, rows, tmp_path / 'merged', target_language='zh', input_pdf=pdf)
    assert report['quality_status'] == 'unverified'
    report = ct.merge_outputs(plan, _rows(tmp_path / 'b', plan), tmp_path / 'merged2', target_language='zh', input_pdf=pdf)
    assert report['quality_status'] == 'pass'


def test_cross_chunk_terminology_inconsistency_is_high():
    context = {'term_policy': {'terms': [{'source_term': 'risk tolerance', 'translation': '风险容忍度'}]}}
    consistent = [{'chunk': 'c001', 'source': 'risk tolerance here', 'translation': '这里的风险容忍度'},
                  {'chunk': 'c002', 'source': 'Risk tolerance again', 'translation': '再次提到风险容忍度'}]
    assert ct.terminology_report(context, consistent)['issues'] == []
    drifted = [consistent[0], {'chunk': 'c002', 'source': 'risk tolerance again', 'translation': '再次提到风险承受度'}]
    issues = ct.terminology_report(context, drifted)['issues']
    assert issues and issues[0]['severity'] == 'high' and issues[0]['chunks'] == ['c002']


def test_document_term_context_is_shared_first_and_local_terms_follow(tmp_path):
    from pdf_translation_commands import build_backend_system_prompt
    (tmp_path / 'term_policy.json').write_text(json.dumps({'terms': [
        {'source_term': 'AI RMF', 'translation': '本地译法'},
        # 此例检查整篇/分块策略优先级，使用明确译法；待审空译法另有拒绝注入测试。
        {'source_term': 'chunk-only term', 'translation': '分块专用术语'}]}))
    plain = build_backend_system_prompt('BASE', tmp_path)
    shared = build_backend_system_prompt('BASE', tmp_path, document_context={
        'term_policy': {'terms': [{'source_term': 'AI RMF', 'translation': '人工智能风险管理框架'}]},
        'entity_map': {'entities': []}})
    assert '本地译法' in plain
    assert '人工智能风险管理框架' in shared and '本地译法' not in shared and 'chunk-only term' in shared
    assert shared.index('AI RMF') < shared.index('chunk-only term')
    assert build_backend_system_prompt('BASE', tmp_path) == plain     # 不传文档上下文：输出不变


def test_document_term_context_binding_requires_exact_sha(tmp_path):
    import pdf_translation_render as render
    path = tmp_path / 'ctx.json'
    path.write_text(json.dumps({'protocol': 'document_term_context_v1', 'term_policy': {'terms': []}}))
    ok = argparse.Namespace(document_term_context=path, document_term_context_sha256=wf.sha(path))
    assert render.load_document_term_context(ok)['protocol'] == 'document_term_context_v1'
    assert render.load_document_term_context(argparse.Namespace()) is None
    with pytest.raises(ValueError, match='changed'):
        render.load_document_term_context(argparse.Namespace(document_term_context=path, document_term_context_sha256='0' * 64))
    with pytest.raises(ValueError, match='together'):
        render.load_document_term_context(argparse.Namespace(document_term_context=path, document_term_context_sha256=None))


# ------------------------------------------------------------------ FREEZE
def parent_freeze(tmp_path, pdf, route='digital_pdf', **overrides):
    scope = tmp_path / 'SCOPE.json'
    scope.write_text('{"note": "complete document"}')
    fingerprint = tmp_path / 'FP.json'
    fingerprint.write_text(json.dumps({'model_id': 'm', 'api_contract': None}))
    impl = [wf.ref(SKILL / 'scripts' / name) for name in ('run_pdf_translation.py', 'chunked_translation.py', 'chunked_workflow.py')]
    with fitz.open(pdf) as doc:
        count = len(doc)
    freeze = {'input': wf.ref(pdf), 'pages': list(range(1, count + 1)), 'complete_semantic_scope': True,
              'scope_evidence': wf.ref(scope), 'route': route, 'model': 'm',
              'routing_contract': {'digital_pdf': wf.DIGITAL_ROUTING,
                                   'per_chunk': wf.PER_CHUNK_ROUTING}[route],
              'chunking_contract': ct.CHUNKING_CONTRACT, 'model_fingerprint_ref': wf.ref(fingerprint),
              'proxy_quality_contract': {'adapter': 'none', 'required': False},
              'resource_contract': {'task_rss_bytes': 5 * GIB, 'per_job_seconds': 120, 'concurrency': 1, 'memory_metric': 'rss'},
              'entrypoint': wf.ref(SKILL / 'scripts/paper_translation_workflow.py'),
              'rules': wf.ref(SKILL / 'references/academic-translation-policy.md'),
              'standard': wf.ref(SKILL / 'references/quality-and-delivery-contract.md'),
              'implementation_refs': impl, 'backend_environment': {}}
    freeze.update(overrides)
    return freeze


def test_chunked_freeze_accepts_long_documents_plain_candidate_still_rejects(tmp_path):
    pdf = text_pdf(tmp_path / 'long.pdf', 12)
    freeze = parent_freeze(tmp_path, pdf)
    assert wf.validate_freeze(freeze, pdf, 'digital_pdf', 'm', chunked=True) == list(range(1, 13))
    with pytest.raises(wf.PreflightError) as excinfo:
        wf.validate_freeze(freeze, pdf, 'digital_pdf', 'm')     # 普通 candidate：仍然 1–5 页
    assert excinfo.value.code == 'page_limit_exceeded'
    assert wf.validate_freeze(parent_freeze(tmp_path, pdf, 'per_chunk'), pdf, 'per_chunk', 'm', chunked=True)
    with pytest.raises(ValueError, match='route outside'):
        wf.validate_freeze(parent_freeze(tmp_path, pdf, 'per_chunk'), pdf, 'per_chunk', 'm')


@pytest.mark.parametrize('change, message', [
    ({'chunking_contract': None}, 'chunking contract'),
    ({'chunking_contract': {**ct.CHUNKING_CONTRACT, 'max_pages_per_chunk': {'digital_pdf': 40}}}, 'chunking contract'),
    ({'pages': [1, 2, 4]}, None),
    ({'implementation_refs': [{'path': str(SKILL / 'scripts/run_pdf_translation.py'), 'sha256': ''}]}, 'chunked_translation.py'),
    ({'source_cache_contract': {'protocol': 'x'}}, 'source cache'),
    ({'routing_contract': dict(wf.DIGITAL_ROUTING, scan_or_mixed='ocr')}, 'routing contract'),
])
def test_chunked_freeze_negative_cases(tmp_path, change, message):
    pdf = text_pdf(tmp_path / 'long.pdf', 12)
    freeze = parent_freeze(tmp_path, pdf, **change)
    with pytest.raises((ValueError, wf.PreflightError)) as excinfo:
        wf.validate_freeze(freeze, pdf, 'digital_pdf', 'm', chunked=True)
    if message:
        assert message in str(excinfo.value)
    else:
        assert excinfo.value.code == 'page_limit_exceeded'


def test_chunked_freeze_rejects_more_than_500_pages(tmp_path):
    pdf = tmp_path / 'huge.pdf'
    doc = fitz.open()
    for _ in range(501):
        doc.new_page()
    doc.save(str(pdf))
    with pytest.raises(wf.PreflightError) as excinfo:
        wf.validate_freeze(parent_freeze(tmp_path, pdf), pdf, 'digital_pdf', 'm', chunked=True)
    assert excinfo.value.code == 'page_limit_exceeded'


# ------------------------------------------------------------------ 编排（真实计划/合并有界任务）
class FakeChunkRunner:
    """写出真实产物：主版式 = 块 PDF 原样（图片指纹一致），综合质量按配置；记录调用。"""

    def __init__(self, statuses=None, outcomes=None):
        self.statuses, self.outcomes, self.calls = statuses or {}, outcomes or {}, []

    def __call__(self, wf_module, args, freeze_path, chunk, attempt, context_path):
        self.calls.append(chunk['id'])
        self.attempt = attempt
        freeze = json.loads(Path(freeze_path).read_text())
        assert freeze['input'] == chunk['source_ref'] and freeze['pages'] == list(range(1, chunk['pages'] + 1))
        assert freeze['document_term_context_ref'] == wf.ref(context_path) and 'chunking_contract' not in freeze
        context = json.loads(Path(context_path).read_text())
        assert context['chunk'] == {k: chunk[k] for k in ('id', 'start', 'end')}
        assert context['reference_region_open_at_start'] is (chunk.get('reference_region_open_at_start') is True)
        outcome = self.outcomes.get(chunk['id'])
        if callable(outcome):
            outcome = outcome(chunk)
        if outcome:
            return outcome
        out, receipts = attempt / 'out', attempt / 'receipts'
        out.mkdir(parents=True, exist_ok=True)
        receipts.mkdir(parents=True, exist_ok=True)
        mono = out / f"{chunk['id']}.no_watermark.zh.mono.pdf"
        shutil.copyfile(chunk['source_ref']['path'], mono)
        status = self.statuses.get(chunk['id'], 'pass')
        (out / 'comprehensive_quality.json').write_text(json.dumps(zero_fallback_quality(out, chunk['id'], chunk['pages'], status)))
        (out / 'render_manifest.json').write_text(json.dumps({'outputs': {'translated_pdf': str(mono)}}))
        working = out / '_backend_working' / chunk['id']
        working.mkdir(parents=True, exist_ok=True)
        (working / 'temp_subset_output_mono.pdf').write_bytes(b'x' * 1000)
        result = {'status': 'succeeded', 'quality_status': status}
        (receipts / 'WORKFLOW_CANDIDATE.json').write_text(json.dumps(result))
        return result


def chunked_args(tmp_path, pdf, freeze_path, resume=False):
    return ['chunked-candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'),
            '--freeze', str(freeze_path), '--route', 'digital_pdf', '--model', 'm', '--base-url', 'http://127.0.0.1:9/v1',
            '--lock-path', str(tmp_path / 'wf.lock')] + (['--resume'] if resume else [])


@pytest.fixture
def long_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(wf, 'doctor', lambda *a, **k: {'blockers': [], 'latex_ready': False})
    pdf = text_pdf(tmp_path / 'long.pdf', 10, image_on=(0, 4, 9), links=[(1, 10)], toc=[[1, 'A', 1], [1, 'B', 6]])
    freeze_path = tmp_path / 'FREEZE.json'
    freeze_path.write_text(json.dumps(parent_freeze(tmp_path, pdf)))
    return pdf, freeze_path


def _main(argv, capsys):
    code = wf.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_chunked_run_merges_all_chunks_and_prunes_only_backend_temporaries(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner(statuses={'c002': 'unverified'})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == 0 and result['status'] == 'candidate' and result['merged'] is True
    assert runner.calls == ['c001', 'c002', 'c003'] and result['chunk_count'] == 3
    assert result['quality_status'] == 'unverified'               # 不好于最差的一块
    merged = fitz.open(result['outputs']['translated_pdf']['path'])
    assert len(merged) == 10 and any(l.get('page') == 9 for l in merged[0].get_links())
    assert (tmp_path / 'rc/WORKFLOW_CHUNKED_CANDIDATE.json').is_file()
    pruned = json.loads((tmp_path / 'out/chunks/c001/attempt-1/CHUNK_PRUNED.json').read_text())
    assert pruned['bytes'] == 1000 and not list((tmp_path / 'out/chunks/c001/attempt-1/out').rglob('temp_subset_*'))
    assert (tmp_path / 'out/chunks/c001/attempt-1/out/c001.no_watermark.zh.mono.pdf').is_file()
    assert result['merge_job']['status'] == 'succeeded' and result['merge_job']['cleanup_status'] == 'confirmed'
    for job in ('chunk-plan', 'chunk-merge'):
        assert (tmp_path / 'rc/invocation-1' / job / f'{job}.launch.json').is_file()


def test_one_failed_chunk_fails_the_whole_delivery_closed(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    blocked = dict(wf.blocked_result([wf.finding('non_digital_pages', 'route gate')]), error_code='non_digital_pages')
    runner = FakeChunkRunner(outcomes={'c002': blocked})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and result['status'] == 'blocked' and result['error_code'] == 'chunk_failed'
    assert result['merged'] is False and 'outputs' not in result
    assert runner.calls == ['c001', 'c002', 'c003']                # 其余块照常执行（一次看到全部失败）
    assert not list((tmp_path / 'out').glob('merged-*'))
    failed = result['findings'][0]['details']['chunks']
    assert [c['id'] for c in failed] == ['c002'] and failed[0]['error_code'] == 'non_digital_pages'


def test_quality_fail_in_one_chunk_makes_merged_quality_fail(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(statuses={'c003': 'fail'}))
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_QUALITY_FAIL and result['quality_status'] == 'fail'


def test_resource_stop_bisects_and_single_page_stop_fails_closed(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc

    def stop(chunk):
        if chunk['pages'] > 1 or chunk['start'] == 5:
            return {'status': 'stopped', 'stop_reason': 'task_timeout', 'elapsed_seconds': 120.4}
        return None
    runner = FakeChunkRunner(outcomes={k: stop for k in ('c002', 'c002a', 'c002b', 'c002aa', 'c002ab')})
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert runner.calls[:4] == ['c001', 'c002', 'c002a', 'c002aa']
    failed = result['findings'][0]['details']['chunks']
    assert [(c['id'], c['error_code']) for c in failed] == [('c002aa', 'chunk_page_exceeds_task_budget')]
    assert code == wf.EXIT_BLOCKED
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    assert state['chunk_table']['c002']['split_into'] == ['c002a', 'c002b']
    assert [state['chunk_table'][c]['status'] for c in ('c002ab', 'c002ba', 'c002bb')] == ['completed'] * 3


def test_transient_failure_is_retried_once(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    flaky = {'n': 0}

    def once(chunk):
        flaky['n'] += 1
        return {'status': 'failed', 'error_code': 'internal_error'} if flaky['n'] == 1 else None
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c001': once}))
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == 0 and result['chunks'][0]['attempts'] == 2
    always = {'status': 'failed', 'error_code': 'internal_error'}
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c001': always}))
    code, result = _main(chunked_args(tmp_path / 'b', pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and result['chunks'][0]['attempts'] == 2


def test_resume_reuses_verified_chunks_and_reruns_tampered_or_missing(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    blocked = dict(wf.blocked_result([wf.finding('x', 'transient env problem')]), error_code='x')
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner(outcomes={'c003': blocked}))
    code, first = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, second = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == 0 and runner.calls == ['c003'] and second['reused_chunks'] == ['c001', 'c002']
    assert second['invocation'] == 2 and (tmp_path / 'rc/WORKFLOW_CHUNKED_CANDIDATE.invocation-2.json').is_file()
    # 篡改一块已登记的产物：续跑时核对失败，该块重跑，其余复用
    mono = tmp_path / 'out/chunks/c002/attempt-1/out/c002.no_watermark.zh.mono.pdf'
    mono.write_bytes(mono.read_bytes() + b'\n% tampered')
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, third = _main(chunked_args(tmp_path, pdf, freeze_path, resume=True), capsys)
    assert code == 0 and runner.calls == ['c002'] and third['reused_chunks'] == ['c001', 'c003']
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    assert state['chunk_table']['c002']['completed']['attempt'] == 2
    assert state['chunk_table']['c002']['invalidated']['changed'] == ['translated_pdf']
    assert (tmp_path / 'out/merged-2').is_dir() and (tmp_path / 'out/merged-3').is_dir()


def test_resume_refuses_changed_freeze_and_new_run_refuses_existing_dirs(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', FakeChunkRunner())
    assert _main(chunked_args(tmp_path, pdf, freeze_path), capsys)[0] == 0
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and 'new --output' in json.dumps(result)
    changed = tmp_path / 'FREEZE2.json'
    changed.write_text(json.dumps(json.loads(freeze_path.read_text()), indent=2))
    code, result = _main(chunked_args(tmp_path, pdf, changed, resume=True), capsys)
    assert code == wf.EXIT_BLOCKED and 'resume identity differs' in json.dumps(result)
    code, result = _main(chunked_args(tmp_path / 'fresh', pdf, freeze_path, resume=True), capsys)
    assert code == wf.EXIT_BLOCKED and 'resume requires' in json.dumps(result)


# ------------------------------------------------------------------ 遗留进程回收（真实进程）
@pytest.mark.skipif(os.name != 'posix', reason='process groups are POSIX only')
def test_resume_reclaims_orphaned_chunk_tree_and_spares_unrelated(tmp_path):
    receipts = tmp_path / 'rc/attempt/receipts/candidate'
    receipts.mkdir(parents=True)
    nonce = 'chunk-test-' + os.urandom(6).hex()
    env = dict(os.environ, PAPER_TRANSLATION_BOUNDED_OWNERS=nonce)
    script = ('import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); '
              'time.sleep(120)')
    # 真实孤儿：中间进程（相当于被 SIGKILL 的编排进程）启动有界任务后立即退出，任务树被重新收养。
    launch = [sys.executable, str(SKILL / 'scripts/bounded_launch.py'), str(receipts / 'candidate.launch.json'),
              nonce, sys.executable, '-c', script]
    orphan = subprocess.Popen([sys.executable, '-c', f'import subprocess; subprocess.Popen({launch!r})'], env=env)
    orphan.wait(timeout=10)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    try:
        deadline = time.time() + 10
        while not (receipts / 'candidate.launch.json').is_file() and time.time() < deadline:
            time.sleep(0.05)
        identity = json.loads((receipts / 'candidate.launch.json').read_text())
        root = psutil.Process(identity['pid'])
        while not root.children() and time.time() < deadline:
            time.sleep(0.05)
        members = [root] + root.children(recursive=True)
        assert len(members) >= 2
        report = cw.reclaim_stale([tmp_path / 'rc'])
        assert report['confirmed'] is True and len(report['reclaimed']) == 1
        assert report['reclaimed'][0]['root_state'] == 'alive'
        for proc in members:
            assert not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
        assert unrelated.poll() is None                               # 无关进程不受影响
        again = cw.reclaim_stale([tmp_path / 'rc'])                   # 再扫一次：无存活成员，不再发信号
        assert again['confirmed'] and again['reclaimed'] == [] and again['already_gone'] == 1
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
            unrelated.wait()
        for proc in locals().get('members', []):
            try:
                proc.kill()
            except psutil.Error:
                pass


def test_verify_completed_detects_every_registered_artifact_change(tmp_path):
    files = {}
    for name in ('chunk.pdf', 'freeze.json', 'q.json', 'm.json', 'r.json', 'mono.pdf'):
        (tmp_path / name).write_text(name)
        files[name] = wf.ref(tmp_path / name)
    entry = {'source_ref': files['chunk.pdf'], 'completed': {
        'freeze_ref': files['freeze.json'], 'quality_ref': files['q.json'], 'render_manifest_ref': files['m.json'],
        'receipt_ref': files['r.json'], 'outputs': {'translated_pdf': files['mono.pdf']}}}
    assert cw.verify_completed(entry) == []
    for name, role in (('q.json', 'quality'), ('mono.pdf', 'translated_pdf'), ('freeze.json', 'freeze')):
        original = (tmp_path / name).read_text()
        (tmp_path / name).write_text(original + 'x')
        assert cw.verify_completed(entry) == [role]
        (tmp_path / name).write_text(original)
    (tmp_path / 'r.json').unlink()
    assert cw.verify_completed(entry) == ['receipt']


def test_classify_chunk_outcomes():
    c = ct.CHUNKING_CONTRACT
    assert cw.classify({'status': 'succeeded', 'quality_status': 'fail'}, c) == 'completed'
    assert cw.classify({'status': 'stopped', 'stop_reason': 'task_memory_limit'}, c) == 'resource_stop'
    assert cw.classify({'status': 'stopped', 'ocr': {'job': {'stop_reason': 'task_timeout'}}}, c) == 'resource_stop'
    assert cw.classify({'status': 'blocked', 'error_code': 'ocr_table_unsupported'}, c) == 'blocked'
    assert cw.classify({'status': 'cleanup_unconfirmed', 'error_code': 'owned_tree_cleanup_unconfirmed'}, c) == 'cleanup_unconfirmed'
    assert cw.classify({'status': 'failed', 'error_code': 'internal_error'}, c) == 'transient'
    # 墙钟跳变下既有启动身份核验抛错：瞬时（重试一次）；同一错误码的其它合同问题仍是确定拦截
    race = dict(wf.blocked_result([wf.finding('input_or_contract_invalid', 'ValueError: bounded launch PID was reused')]),
                error_code='input_or_contract_invalid')
    assert cw.classify(race, c) == 'transient'
    other = dict(wf.blocked_result([wf.finding('input_or_contract_invalid', 'ValueError: frozen input identity changed')]),
                 error_code='input_or_contract_invalid')
    assert cw.classify(other, c) == 'blocked'


# ------------------------------------------------------------------ rc.9 第 2 轮（真实长文档运行发现）
def _backend_manifest(attempt, errors):
    (attempt / 'out').mkdir(parents=True, exist_ok=True)
    (attempt / 'out' / 'render_manifest.json').write_text(json.dumps({'status': 'error', 'errors': errors}))


def test_backend_internal_timeout_bisects_like_a_task_timeout(tmp_path, long_doc, monkeypatch, capsys):
    # 实测：后端内部 110 s 超时后以 owned_descendants_after_command 结束，原先按瞬时失败重试（靠缓存过关）。
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner()

    def timeout(chunk):
        if chunk['pages'] > 2:
            _backend_manifest(runner.attempt, [{'error_type': 'timeout', 'timeout_seconds': 110}])
            return {'status': 'stopped', 'stop_reason': 'owned_descendants_after_command', 'elapsed_seconds': 111.0}
        return None
    runner.outcomes = {'c002': timeout}
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == 0 and runner.calls == ['c001', 'c002', 'c002a', 'c002b', 'c003']
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    first = state['chunk_table']['c002']['attempts'][0]
    assert first['classification'] == 'resource_stop' and first['stop_reason'] == 'backend_timeout'
    assert state['chunk_table']['c002']['split_into'] == ['c002a', 'c002b']


def test_backend_nonzero_exit_without_timeout_is_still_only_retried(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner = FakeChunkRunner()

    def crash(chunk):
        _backend_manifest(runner.attempt, [{'error_type': 'nonzero_exit', 'returncode': 2}])
        return {'status': 'stopped', 'stop_reason': 'owned_descendants_after_command'}
    runner.outcomes = {'c002': crash}
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert code == wf.EXIT_BLOCKED and runner.calls == ['c001', 'c002', 'c002', 'c003']
    state = json.loads((tmp_path / 'rc' / cw.STATE_NAME).read_text())
    assert [a['classification'] for a in state['chunk_table']['c002']['attempts']] == ['transient', 'transient']
    assert 'split_into' not in state['chunk_table']['c002']


def _leave_live_tree(attempt):
    """真实遗留：有界启动的任务树在尝试“结束”后仍存活（实测：墙钟跳变使身份核验抛错、未回收）。"""
    receipts = attempt / 'receipts' / 'candidate'
    receipts.mkdir(parents=True, exist_ok=True)
    nonce = 'chunk-guard-' + os.urandom(6).hex()
    env = dict(os.environ, PAPER_TRANSLATION_BOUNDED_OWNERS=nonce)
    script = ('import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); '
              'time.sleep(120)')
    launch = [sys.executable, str(SKILL / 'scripts/bounded_launch.py'), str(receipts / 'candidate.launch.json'),
              nonce, sys.executable, '-c', script]
    subprocess.Popen([sys.executable, '-c', f'import subprocess; subprocess.Popen({launch!r})'], env=env).wait(timeout=10)
    deadline = time.time() + 10
    while not (receipts / 'candidate.launch.json').is_file() and time.time() < deadline:
        time.sleep(0.05)
    root = psutil.Process(json.loads((receipts / 'candidate.launch.json').read_text())['pid'])
    while not root.children() and time.time() < deadline:
        time.sleep(0.05)
    return [root] + root.children(recursive=True)


def _dead(proc):
    try:
        return not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
    except psutil.Error:
        return True


@pytest.mark.skipif(os.name != 'posix', reason='process groups are POSIX only')
def test_post_attempt_guard_reclaims_a_live_tree_before_the_next_chunk(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner, members = FakeChunkRunner(), []

    def leaves_tree(chunk):
        members.extend(_leave_live_tree(runner.attempt))
        return dict(wf.blocked_result([wf.finding('input_or_contract_invalid', 'ValueError: bounded launch PID was reused')]),
                    error_code='input_or_contract_invalid')
    runner.outcomes = {'c001': leaves_tree}
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    try:
        code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
        assert len(members) >= 4 and all(_dead(p) for p in members)       # 每次在下一次启动前已回收
        assert runner.calls == ['c001', 'c001', 'c002', 'c003']             # 身份核验抛错：瞬时，重试一次
        for n in (1, 2):
            guard = json.loads((tmp_path / f'out/chunks/c001/attempt-{n}/POST_ATTEMPT_GUARD.json').read_text())
            assert guard['live_after_attempt'] and guard['confirmed'] is True and guard['still_live'] == []
        assert code == wf.EXIT_BLOCKED                                      # 重试后仍失败：整份照常失败关闭
    finally:
        for proc in members:
            try:
                proc.kill()
            except psutil.Error:
                pass


@pytest.mark.skipif(os.name != 'posix', reason='process groups are POSIX only')
def test_post_attempt_guard_unconfirmed_stops_scheduling_and_fails_closed(tmp_path, long_doc, monkeypatch, capsys):
    pdf, freeze_path = long_doc
    runner, members = FakeChunkRunner(), []

    def leaves_tree(chunk):
        members.extend(_leave_live_tree(runner.attempt))
        return None                                                         # 块本身“成功”，但留下存活进程
    runner.outcomes = {'c001': leaves_tree}
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    monkeypatch.setattr(cw, 'reclaim_stale', lambda roots: {'confirmed': False, 'reclaimed': [], 'receipts_scanned': 1,
                                                            'already_gone': 0})
    try:
        code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
        assert runner.calls == ['c001']                                     # 不再启动任何块
        assert code == wf.EXIT_BLOCKED and result['error_code'] == 'chunk_failed' and result.get('merged') is not True
        failed = {c['id']: c for c in result['findings'][0]['details']['chunks']}
        assert failed['c001']['error_code'] == 'chunk_cleanup_unconfirmed'
        assert failed['c002']['status'] == failed['c003']['status'] == 'pending'
    finally:
        for proc in members:
            try:
                proc.kill()
            except psutil.Error:
                pass


def test_reference_region_carry_in_matches_the_whole_document_check(tmp_path):
    from render_residue_check import check_render_residue, reference_region_open_pages
    sys.path.insert(0, str(SKILL / 'tests'))
    from test_rc3_review_round2 import AUTHOR_YEAR_REFS, EN_PARA, ZH_PARA, Page, flow, save

    def doc(body, font, tail=()):
        first = Page(); y = flow(first, 50, 545, 50, [(body, font)] * 4)
        y = flow(first, 50, 545, y + 6, [('References', 'hebo')])
        flow(first, 50, 545, y, [(r, 'helv') for r in AUTHOR_YEAR_REFS[:2]])
        second = Page(); flow(second, 50, 545, 50, [(t, 'helv') for t in list(tail) + AUTHOR_YEAR_REFS * 2])
        return [first, second]
    full_s, full_t = save(tmp_path / 's.pdf', doc(EN_PARA, 'helv')), save(tmp_path / 't.pdf', doc(ZH_PARA, 'china-s'))
    with fitz.open(full_s) as d:
        assert reference_region_open_pages(d) == [False, True]
    whole = check_render_residue(full_s, full_t)
    assert whole['pages'][1]['severity'] in ('ok', 'not_evaluated') and whole['severity'] != 'high'

    def page2(src, name):
        with fitz.open(src) as d:
            out = fitz.open(); out.insert_pdf(d, from_page=1, to_page=1); out.save(str(tmp_path / name)); out.close()
        return tmp_path / name
    chunk_s, chunk_t = page2(full_s, 'cs.pdf'), page2(full_t, 'ct.pdf')
    alone = check_render_residue(chunk_s, chunk_t)                         # 无带入：与整份检查结论不同（原缺陷）
    assert alone['pages'][0]['severity'] == 'high' and 'reference_region_open_at_start' not in alone['excluded']
    carried = check_render_residue(chunk_s, chunk_t, region_open_at_start=True)
    assert carried['excluded']['reference_region_open_at_start'] is True
    row = dict(carried['pages'][0]); row['page'] = 2
    assert row == whole['pages'][1]                                         # 带入后与整份检查逐项相同
    # 负例：带入的参考文献区里未翻译的英文正文照常计数（区内逐条规则不放宽）
    prose_s = save(tmp_path / 'ps.pdf', doc(EN_PARA, 'helv', tail=[EN_PARA] * 3))
    prose_t = save(tmp_path / 'pt.pdf', doc(ZH_PARA, 'china-s', tail=[EN_PARA] * 3))
    carried_prose = check_render_residue(page2(prose_s, 'cps.pdf'), page2(prose_t, 'cpt.pdf'), region_open_at_start=True)
    assert carried_prose['pages'][0]['severity'] == 'high'


def test_chunked_run_creates_a_missing_workspace_root(tmp_path, long_doc, monkeypatch, capsys):
    # CI：PAPER_TRANSLATION_WORKSPACE 指向尚不存在的目录；有界任务以它为 cwd，须先建好再启动 chunk-plan。
    pdf, freeze_path = long_doc
    root = tmp_path / 'fresh-workspace' / 'nested'
    monkeypatch.setattr(wf, 'ROOT', root)
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code, result = _main(chunked_args(tmp_path, pdf, freeze_path), capsys)
    assert root.is_dir()
    assert code == 0 and result['merged'] is True and runner.calls == ['c001', 'c002', 'c003']


def test_chunked_run_fails_closed_when_workspace_root_is_a_file(tmp_path, long_doc, monkeypatch, capsys):
    # 负例：工作区路径被普通文件占用——不得改写该文件，不启动任何块，非零退出。
    pdf, freeze_path = long_doc
    root = tmp_path / 'occupied'
    root.write_text('not a directory')
    monkeypatch.setattr(wf, 'ROOT', root)
    runner = FakeChunkRunner()
    monkeypatch.setattr(cw, 'CHUNK_RUNNER', runner)
    code = wf.main(chunked_args(tmp_path, pdf, freeze_path))
    capsys.readouterr()
    assert code != 0 and runner.calls == [] and root.read_text() == 'not a directory'
