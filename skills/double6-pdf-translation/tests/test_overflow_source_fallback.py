"""可读字号下限溢出的“保留原文”降级（2026-10-23，修复 realmodel-r1 评测问题 1）。

只有短的、结构已确认的片段（表头/表格单元格、目录项/页码标签、图内标签）在可读下限仍放不下时
才保留原文；正文和含糊片段照旧整份失败；降级超过按页/按文档上限时整批撤销、照旧失败；
每条降级写入回执（overflow_source_fallback），综合质量最多 unverified，永不 pass。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/babeldoc'))
sys.path.insert(0, str(ROOT / 'scripts'))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402


def box(x, y, x2, y2):
    return il.Box(x=x, y=y, x2=x2, y2=y2)


def chars(text, x=100.0, y=500.0, size=9.0):
    out = []
    for i, ch in enumerate(text):
        out.append(il.PdfCharacter(
            pdf_style=il.PdfStyle(font_id='F1', font_size=size, graphic_state=il.GraphicState()),
            box=box(x + i * size * 0.6, y, x + (i + 1) * size * 0.6, y + size),
            visual_bbox=il.VisualBbox(box=box(x + i * size * 0.6, y, x + (i + 1) * size * 0.6, y + size)),
            vertical=False, scale=1.0, pdf_character_id=i, char_unicode=ch, render_order=i))
    return out


def backup_of(text, size=9.0, as_line=True):
    cs = chars(text, size=size)
    if as_line:
        return [il.PdfParagraphComposition(pdf_line=il.PdfLine(box=box(100, 500, 300, 500 + size), pdf_character=cs))]
    return [il.PdfParagraphComposition(pdf_character=c) for c in cs]


def paragraph(label, text, height=11.0, size=9.0, x=100.0, y=500.0, backup=True, unicode=None):
    p = il.PdfParagraph(box=box(x, y, x + 60, y + height),
                        pdf_style=il.PdfStyle(font_id='F1', font_size=size, graphic_state=il.GraphicState()),
                        unicode=unicode or text, layout_label=label, debug_id=f'{label}-{text[:6]}')
    if backup:
        p.overflow_source_backup = backup_of(text, size=size)
    return p


def page(paragraphs=(), layouts=(), number=0):
    return il.Page(page_number=number, cropbox=il.Cropbox(box=box(0, 0, 595, 842)),
                   mediabox=il.Mediabox(box=box(0, 0, 595, 842)), page_layout=list(layouts),
                   pdf_paragraph=list(paragraphs), pdf_curve=[])


def table_layout():
    return il.PageLayout(id=1, class_name='table', box=box(80, 400, 520, 700), conf=1.0)


# ---------------- admission：正向 ----------------

@pytest.mark.parametrize('label,source,translated,category', [
    ('table_header', '组内占比 (%)', 'Share within group (%)', 'table_cell'),
    ('table_cell', '物理科学', 'Physical Sciences', 'table_cell'),
    ('toc_entry', 'Page 12', '第 12 页', 'toc_entry'),
    ('chapter_index_entry', '5.3 Measure', '5.3 测量', 'toc_entry'),
    ('axis_label', 'Throughput', '吞吐量（每秒令牌数）', 'figure_label'),
])
def test_fallback_admitted_for_confirmed_short_structure(label, source, translated, category):
    p = paragraph(label, source)
    ok, detail = osf.admission(p, page([p]), source, translated, p.overflow_source_backup)
    assert ok and detail == category


def test_generic_line_admitted_only_inside_detected_table_region():
    inside = paragraph('fallback_line', '物理科学', x=120, y=500)
    outside = paragraph('fallback_line', '物理科学', x=120, y=100)
    pg = page([inside, outside], layouts=[table_layout()])
    assert osf.admission(inside, pg, '物理科学', 'Physical Sciences', inside.overflow_source_backup) == (True, 'table_cell')
    assert osf.admission(outside, pg, '物理科学', 'Physical Sciences', outside.overflow_source_backup) == (False, 'role_not_admitted')


# ---------------- admission：反向（照旧失败） ----------------

@pytest.mark.parametrize('label', ['plain text', 'text', 'title', 'paragraph_hybrid', 'figure_caption', 'footnote',
                                   'list_item', 'abstract', None])
def test_body_and_ambiguous_roles_rejected(label):
    p = paragraph(label, 'Results')
    assert osf.admission(p, page([p], layouts=[table_layout()]), 'Results', '结果', p.overflow_source_backup) == \
        (False, 'role_not_admitted')


def test_long_multi_sentence_formula_or_multiline_sources_rejected():
    long_src = 'Share of all respondents who reported using the tool weekly in group'
    p = paragraph('table_header', long_src)
    assert osf.admission(p, page([p]), long_src, '每周使用', p.overflow_source_backup) == (False, 'source_too_long')
    multi = 'Total. See note'
    p = paragraph('table_cell', multi)
    assert osf.admission(p, page([p]), multi, '合计。见注', p.overflow_source_backup) == (False, 'source_multi_sentence')
    p = paragraph('table_cell', 'x2 rate')
    formula = [il.PdfParagraphComposition(pdf_formula=il.PdfFormula(box=box(100, 500, 120, 509), pdf_character=chars('x2')))]
    assert osf.admission(p, page([p]), 'x2 rate', 'x2 比率', formula) == (False, 'source_not_plain_text')
    p = paragraph('table_cell', '{v1} share')
    assert osf.admission(p, page([p]), '{v1} share', '{v1} 占比', p.overflow_source_backup) == (False, 'source_has_placeholder')
    p = paragraph('table_cell', 'Share', height=40.0)
    assert osf.admission(p, page([p]), 'Share', '占比', p.overflow_source_backup) == (False, 'source_not_single_line')
    p = paragraph('table_cell', 'Share', backup=False)
    assert osf.admission(p, page([p]), 'Share', '占比', []) == (False, 'source_backup_missing')
    p = paragraph('table_cell', 'Share')
    assert osf.admission(p, page([p]), 'Share', '', p.overflow_source_backup) == (False, 'translation_length_out_of_range')


# ---------------- 上限 ----------------

def test_cap_limits():
    assert osf.page_cap(4) == 3 and osf.page_cap(40) == 8
    assert osf.doc_cap(10) == 4 and osf.doc_cap(100) == 10
    ok = osf.cap_violations([0, 0, 1], {0: 20, 1: 20})
    assert ok['violations'] == [] and ok['count'] == 3
    bad_page = osf.cap_violations([0, 0, 0, 0], {0: 10, 1: 200})
    assert [v['scope'] for v in bad_page['violations']] == ['page']
    bad_doc = osf.cap_violations([0, 1, 2, 3, 4], {i: 4 for i in range(5)})
    assert [v['scope'] for v in bad_doc['violations']] == ['document']


# ---------------- 排版器：应用、拒绝、撤销、回执 ----------------

class Unit:
    can_passthrough = True


def typesetter(tmp_path, passthrough=True):
    ts = Typesetting.__new__(Typesetting)
    ts._overflow_fallbacks, ts._overflow_fallback_rejections = [], {}
    unit = Unit(); unit.can_passthrough = passthrough
    ts.create_typesetting_units = lambda paragraph, fonts: [unit]
    ts.create_passthrough_composition = lambda units: list(units_backup.pop())
    units_backup = []
    original = ts.create_typesetting_units

    def units(paragraph, fonts):
        units_backup.append(list(paragraph.pdf_paragraph_composition))
        return original(paragraph, fonts)
    ts.create_typesetting_units = units
    ts.translation_config = NS(get_working_file_path=lambda name: tmp_path / name, progress_monitor=None)
    return ts


def overflowed(p, status='table_region_rerender_required', translated='Share within group (%)'):
    p.unicode = translated
    p.pdf_paragraph_composition = []
    p.writeback_status = status
    p.writeback_reason = 'hard_readable_floor_overflow'
    return p


def test_table_header_fallback_applied_keeps_source_glyphs(tmp_path):
    ts = typesetter(tmp_path)
    p = overflowed(paragraph('table_header', '组内占比 (%)'))
    pg = page([p])
    assert ts._apply_overflow_source_fallback(p, pg, {}) is True
    assert p.writeback_status == osf.CODE and p.unicode == '组内占比 (%)' and p.scale == 1.0
    assert p.pdf_paragraph_composition and p.pdf_paragraph_composition[0].pdf_line.pdf_character[0].char_unicode == '组'
    # 原位置、原字号：字形坐标与字号保持源备份（不缩字、不裁切）。
    first = p.pdf_paragraph_composition[0].pdf_line.pdf_character[0]
    assert first.pdf_style.font_size == 9.0 and first.box.x == 100.0
    cap = ts._enforce_overflow_fallback_cap(il.Document(page=[pg], total_pages=1))
    assert cap['status'] == 'applied' and not ts._writeback_failures(il.Document(page=[pg], total_pages=1))


def test_body_paragraph_overflow_still_fails(tmp_path):
    ts = typesetter(tmp_path)
    p = overflowed(paragraph('plain text', 'Results'), status='paragraph_writeback_failed', translated='结果')
    pg = page([p])
    assert ts._apply_overflow_source_fallback(p, pg, {}) is False
    assert p.pdf_paragraph_composition == [] and p.writeback_status == 'paragraph_writeback_failed'
    failures = ts._writeback_failures(il.Document(page=[pg], total_pages=1))
    assert failures and failures[0]['reason'] == 'hard_readable_floor_overflow'
    assert failures[0]['source_fallback_rejected'] == 'role_not_admitted'


def test_non_passthrough_source_rejected(tmp_path):
    ts = typesetter(tmp_path, passthrough=False)
    p = overflowed(paragraph('table_header', 'Share'))
    pg = page([p])
    assert ts._apply_overflow_source_fallback(p, pg, {}) is False
    assert p.pdf_paragraph_composition == [] and p.writeback_status == 'table_region_rerender_required'
    assert ts._overflow_fallback_rejections[id(p)] == 'source_not_passthrough'


def test_fallback_cap_exceeded_revokes_all_and_fails(tmp_path):
    ts = typesetter(tmp_path)
    cells = [overflowed(paragraph('table_cell', f'Cell {i}', y=420 + 20 * i), translated=f'单元格 {i}')
             for i in range(4)]
    pg = page(cells)
    assert all(ts._apply_overflow_source_fallback(p, pg, {}) for p in cells)
    doc = il.Document(page=[pg], total_pages=1)
    cap = ts._enforce_overflow_fallback_cap(doc)
    assert cap['status'] == 'revoked_cap_exceeded' and cap['violations']
    for p in cells:
        assert p.pdf_paragraph_composition == [] and p.writeback_status == 'table_region_rerender_required'
        assert p.unicode.startswith('单元格')
    failures = ts._writeback_failures(doc)
    assert len(failures) == 4 and {f['source_fallback_rejected'] for f in failures} == {osf.CAP_CODE}


def test_receipt_records_fallbacks_and_is_needs_review(tmp_path):
    ts = typesetter(tmp_path)
    p = overflowed(paragraph('toc_entry', 'Page 12'), status='structured_toc_writeback_failed', translated='第 12 页')
    body = [paragraph('plain text', f'Body {i}') for i in range(12)]
    pg = page([p] + body)
    ts._apply_overflow_source_fallback(p, pg, {})
    doc = il.Document(page=[pg], total_pages=1)
    fallbacks = ts._overflow_fallbacks
    # 走真实的回执写入路径：_typesetting_document 开头会重置状态，渲染页时重放上面的降级记录。
    ts.render_page = lambda page_: ts._overflow_fallbacks.extend(fallbacks)
    ts.translation_config.raise_if_cancelled = lambda: None
    ts._typesetting_document(doc)
    receipt = json.loads((tmp_path / 'typesetting_writeback_report.json').read_text(encoding='utf-8'))
    assert receipt['status'] == 'needs_review' and receipt['failures'] == []
    assert receipt['source_fallback_count'] == 1
    row = receipt['source_fallbacks'][0]
    assert row['code'] == 'overflow_source_fallback' and row['category'] == 'toc_entry'
    assert row['source_text'] == 'Page 12' and row['translated_text'] == '第 12 页'
    assert not any(k.startswith('_') for k in row)


# ---------------- 综合质量：降级永不 pass ----------------

def test_qa_pipeline_fallback_pending_never_pass(tmp_path):
    import qa_pipeline
    work = tmp_path / '_backend_working' / 'doc'
    work.mkdir(parents=True)
    (work / 'typesetting_writeback_report.json').write_text(json.dumps({
        'status': 'needs_review', 'failures': [], 'source_fallback_count': 2,
        'source_fallbacks': [{'code': 'overflow_source_fallback', 'page_index': 0, 'paragraph_id': 'a', 'role': 'table_cell',
                              'category': 'table_cell', 'source_text': '物理科学', 'translated_text': 'Physical Sciences'},
                             {'code': 'overflow_source_fallback', 'page_index': 2, 'paragraph_id': 'b', 'role': 'toc_entry',
                              'category': 'toc_entry', 'source_text': 'Page 3', 'translated_text': '第 3 页'}]}),
        encoding='utf-8')
    audit = qa_pipeline.audit_overflow_source_fallbacks(tmp_path)
    assert audit['count'] == 2 and audit['pending'][0]['rule'] == 'overflow_source_fallback'
    assert audit['pending'][0]['pages'] == [1, 3] and audit['pending'][0]['severity'] == 'needs_review'


def test_qa_pipeline_invalid_receipt_is_pending(tmp_path):
    import qa_pipeline
    work = tmp_path / '_backend_working' / 'doc'
    work.mkdir(parents=True)
    (work / 'typesetting_writeback_report.json').write_text('{not json', encoding='utf-8')
    audit = qa_pipeline.audit_overflow_source_fallbacks(tmp_path)
    assert audit['pending'] and audit['pending'][0]['rule'] == 'overflow_source_fallback_receipt_invalid'


def test_chunk_aggregate_keeps_fallback_pending_and_counts():
    import chunked_translation as ct
    chunk = {'id': 'c002', 'start': 5, 'end': 8}
    quality = {'status': 'unverified', 'issues': [], 'pending': [{'id': 'overflow_source_fallback',
               'rule': 'overflow_source_fallback', 'count': 2, 'pages': [1, 3]}]}
    result = ct.aggregate_quality([{'chunk': chunk, 'quality': quality}], [])
    assert result['status'] == 'unverified' and result['overflow_source_fallback_count'] == 2
    row = [p for p in result['pending'] if p.get('rule') == 'overflow_source_fallback'][0]
    assert row['document_pages'] == [5, 7] and row['chunk'] == 'c002'
