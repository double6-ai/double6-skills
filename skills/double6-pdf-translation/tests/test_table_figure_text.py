"""PR #3：表格文字与图内文字的识别、翻译范围和回写位置回归测试。

夹具来自真实文档（USGS 公有领域与 CC BY 4.0 arXiv 论文，见
tests/fixtures/table_figure_text/README.md）：用官方入口跑到 ParagraphFinder 之前导出的逐字符几何。
测试直接运行真实的 ParagraphFinder.process_page，不依赖模型、网络或字体下载。
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/babeldoc'))
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder  # noqa: E402
from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_pure_numeric_paragraph  # noqa: E402

FIXTURES = ROOT / 'tests/fixtures/table_figure_text'
PASSTHROUGH = {'compact_label', 'code_label', 'code_passthrough_label', 'latex_structure_fragment', 'cover_year'}


def _box(v):
    return il.Box(x=v[0], y=v[1], x2=v[2], y2=v[3])


def load_page(name):
    data = json.loads((FIXTURES / name).read_text(encoding='utf-8'))
    chars = []
    for serial, row in enumerate(data['chars']):
        u, *g, font_id, size, vertical, xobj_id, render_order = row
        chars.append(il.PdfCharacter(
            pdf_style=il.PdfStyle(font_id=font_id, font_size=size, graphic_state=il.GraphicState()),
            box=_box(g[:4]), visual_bbox=il.VisualBbox(box=_box(g[4:8])), vertical=vertical, scale=1.0,
            pdf_character_id=serial, char_unicode=u, xobj_id=xobj_id, render_order=render_order))
    fonts = lambda rows: [il.PdfFont(font_id=f['font_id'], name=f['name']) for f in rows]  # noqa: E731
    page = il.Page(
        page_number=data['page_number'], cropbox=il.Cropbox(box=_box(data['cropbox'])),
        mediabox=il.Mediabox(box=_box(data['mediabox'])), pdf_font=fonts(data['fonts']),
        pdf_xobject=[il.PdfXobject(xobj_id=x['xobj_id'], pdf_font=fonts(x['fonts'])) for x in data['xobjects']],
        page_layout=[il.PageLayout(id=l['id'], class_name=l['class_name'], box=_box(l['box']), conf=l['conf'] or 1.0)
                     for l in data['layouts']],
        pdf_character=chars,
        pdf_curve=[il.PdfCurve(box=_box(c['box']), fill_background=c['fill'], xobj_id=c['xobj'], render_order=c['ro'],
                               graphic_state=il.GraphicState(passthrough_per_char_instruction=c['gs']))
                   for c in data['curves']],
        pdf_paragraph=[])
    return data, page


_CACHE = {}


def run(name):
    if name not in _CACHE:
        data, page = load_page(name)
        finder = ParagraphFinder.__new__(ParagraphFinder)
        finder.translation_config = NS(**data['config'])
        finder.process_page(page)
        _CACHE[name] = page
    return _CACHE[name]


def text(paragraph):
    return re.sub(r'\s+', ' ', paragraph.unicode or '').strip()


def by_text(page, wanted):
    found = [p for p in page.pdf_paragraph if text(p) == wanted]
    assert found, f'{wanted!r} not found in {[text(p) for p in page.pdf_paragraph]}'
    return found


def translatable(paragraph):
    return paragraph.layout_label not in PASSTHROUGH and not is_pure_numeric_paragraph(paragraph)


# ---------------------------------------------------------------- 表格文字

USGS_TABLE = 'usgs-mcs2024-p4-table1.json'
ISAC_TABLE = 'arxiv2610.21653-p8-table1.json'
NAMES_TABLE = 'arxiv2610.20087-p16-tables.json'


@pytest.mark.parametrize('label', ['Metals', 'Industrial minerals', 'Coal'])
def test_usgs_table_row_labels_are_translated_with_their_siblings(label):
    # 同一列的兄弟行（Total mine production…、Employment…）会被翻译；这些行若留作英文，
    # 表格就成了中英混排（基线报告 F2）。
    for paragraph in by_text(run(USGS_TABLE), label):
        assert translatable(paragraph), (label, paragraph.layout_label)


def test_usgs_table_year_headers_are_not_cover_years():
    # 第 4 页表头的年份不是封面年份；按 cover_year 处理会送去翻译并以 0.7 倍字号重排。
    page = run(USGS_TABLE)
    years = [p for p in page.pdf_paragraph if re.fullmatch(r'20\d{2}', text(p))]
    assert len(years) >= 4
    assert all(p.layout_label != 'cover_year' for p in years), [p.layout_label for p in years]


@pytest.mark.parametrize('value', ['26,900', '1,617', '27,356', '-1,200.5', '102'])
def test_grouped_numbers_are_pure_numeric(value):
    # 带千分位的数字也要原样保留，不能进入翻译后以回退字体和缩小字号重排。
    assert is_pure_numeric_paragraph(NS(unicode=value))


@pytest.mark.parametrize('value', ['$10.6 billion', '2023e', '1.3×104', 'v1.2.3'])
def test_non_numeric_cells_are_not_pure_numeric(value):
    assert not is_pure_numeric_paragraph(NS(unicode=value))


def test_usgs_table_single_line_rows_record_source_baseline():
    # 译文首行应落在原文基线上（源字框下沿含下伸部，按它排版会整行下移 ~2.7pt 压到下一行）。
    page = run(USGS_TABLE)
    row = by_text(page, 'Total mine production (million dollars):')[0]
    baseline = getattr(row, 'source_baseline', None)
    assert baseline is not None
    # PyMuPDF 读出的原文 span origin 为 714.66（PDF 坐标）。
    assert abs(baseline - 714.66) <= 0.4, baseline
    assert baseline > row.box.y + 1.5


def test_usgs_table_keeps_deliberate_passthrough_tokens():
    page = run(USGS_TABLE)
    assert all(p.layout_label == 'compact_label' for p in by_text(page, '2023e'))


@pytest.mark.parametrize('label', ['Method', 'Memory', 'Cost', 'Codec', 'Time cost', 'Sidelobe', 'Controllability',
                                   'Rate', 'Loss', 'Fixed ISLR', 'but uncontrollable', 'ISLR controllable', 'Only EISL'])
def test_isac_table_header_and_natural_cells_are_translated(label):
    for paragraph in by_text(run(ISAC_TABLE), label):
        assert translatable(paragraph), (label, paragraph.layout_label)


@pytest.mark.parametrize('label', ['CCDM', 'JHM-ESS', 'S-ESS', '1D-ESS'])
def test_isac_table_method_names_stay_source(label):
    for paragraph in by_text(run(ISAC_TABLE), label):
        assert paragraph.layout_label == 'compact_label'


@pytest.mark.parametrize('label', ['MNIST', 'EMNIST', 'BCGC', 'GFRC', 'i.i.d.', 'non-i.i.d.'])
def test_dataset_and_scheme_names_stay_source(label):
    for paragraph in by_text(run(NAMES_TABLE), label):
        assert paragraph.layout_label == 'compact_label'


def test_isac_formula_cells_record_source_baseline():
    page = run(ISAC_TABLE)
    cells = [p for p in page.pdf_paragraph if text(p).startswith('O(N') and p.layout_label == 'fallback_line']
    assert cells
    for cell in cells:
        baseline = getattr(cell, 'source_baseline', None)
        assert baseline is not None and cell.box.y <= baseline < cell.box.y2


# ---------------------------------------------------------------- 图内文字

USGS_FIGURE = 'usgs-mcs2024-p2-figure1.json'


@pytest.mark.parametrize('wanted', [
    'Net Exports of Mineral Raw Materials',
    'Domestically Mined Mineral Raw Materials',
    'Domestically Processed Mineral Materials',
    'Value Added to Gross Domestic Product by Major Industries That Consume Processed Mineral Materials1',
    'Aluminum, Brick, Cement, Copper, Fertilizers, Steel, and so forth',
])
def test_usgs_figure_node_lines_are_one_translation_unit(wanted):
    # 图 1 每个填充节点里的多行标题/说明原先逐行成段，半数被当作紧凑标签留英文（基线报告 F3）。
    paragraphs = by_text(run(USGS_FIGURE), wanted)
    assert all(translatable(p) for p in paragraphs), [p.layout_label for p in paragraphs]


@pytest.mark.parametrize('label', ['Exports:', 'Imports:', 'Value of shipments:', 'U.S. Economy', 'Gross Domestic Product:'])
def test_usgs_figure_short_labels_are_translated(label):
    for paragraph in by_text(run(USGS_FIGURE), label):
        assert translatable(paragraph), (label, paragraph.layout_label)


def test_usgs_figure_amounts_stay_separate_cells():
    # 「Exports: $10.6 billion」是同一基线上的两格，不能被合成一段而改变对齐。
    page = run(USGS_FIGURE)
    assert by_text(page, '$10.6 billion') and by_text(page, 'Exports:')


def test_usgs_figure_has_no_untranslated_english_phrase_left():
    page = run(USGS_FIGURE)
    left = [text(p) for p in page.pdf_paragraph
            if p.layout_label == 'compact_label' and re.search(r'[A-Za-z]{3,}', text(p))]
    assert left == []


@pytest.mark.parametrize('name,wanted', [
    ('arxiv2610.21759-p2-fig1.json', 'Fig. 1. System Model.'),
    ('arxiv2610.21759-p4-fig2.json', 'Fig. 2. Proposed Binary Quantizer.'),
    ('arxiv2610.21759-p4-fig2.json', 'Binary Quantizer'),
])
def test_arxiv_figure_captions_and_block_labels_are_translated(name, wanted):
    for paragraph in by_text(run(name), wanted):
        assert translatable(paragraph), (wanted, paragraph.layout_label)


# ---------------------------------------------------------------- 回写位置

class _Font:
    def char_lengths(self, text, size):
        return [size * 0.5 for _ in text]


def _typesetter():
    from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
    stage = Typesetting.__new__(Typesetting)
    stage.font_mapper = NS(base_font=_Font())
    stage.is_cjk = True
    return stage


def _units(chars, size):
    import pymupdf
    from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
    font = pymupdf.Font('helv')
    style = il.PdfStyle(font_id='helv', font_size=size, graphic_state=il.GraphicState())
    return [TypesettingUnit(unicode=c, font=font, font_size=size, style=style, xobj_id=0) for c in chars]


def test_single_line_translation_is_anchored_to_source_baseline():
    box = il.Box(x=51.0, y=711.4, x2=218.9, y2=722.0)
    paragraph = il.PdfParagraph(box=box, layout_label='fallback_line', first_line_indent=False)
    paragraph.source_baseline = 714.66
    units, fit = _typesetter()._layout_typesetting_units(_units('Coal mining', 10.02), box, 1.0, 1.5, paragraph)
    assert fit and units
    assert abs(min(u.box.y for u in units) - 714.66) <= 0.05


def test_baseline_anchor_never_moves_text_down_or_far_up():
    box = il.Box(x=51.0, y=711.4, x2=218.9, y2=722.0)
    paragraph = il.PdfParagraph(box=box, layout_label='fallback_line', first_line_indent=False)
    plain, _ = _typesetter()._layout_typesetting_units(_units('Coal', 10.02), box, 1.0, 1.5, paragraph)
    for anchor in (box.y - 3.0, box.y2 + 20.0):
        paragraph.source_baseline = anchor
        units, _ = _typesetter()._layout_typesetting_units(_units('Coal', 10.02), box, 1.0, 1.5, paragraph)
        assert [u.box.y for u in units] == [u.box.y for u in plain]


# ---------------------------------------------------------------- 短词翻译范围

@pytest.mark.parametrize('label,value,expected', [
    ('fallback_line', 'Coal', True),    # USGS Table 1 行名
    ('fallback_line', 'Rate', True),    # arXiv:2610.21653 Table I 表头第一行
    ('fallback_line', 'Loss', True),
    ('fallback_line', 'Cost', True),
    ('fallback_line', 'ESS', False),    # 全大写缩写仍按最短长度跳过
    ('fallback_line', '2019', False),
    ('fallback_line', '(a)', False),
    ('plain text', 'Coal', False),      # 正文角色不放宽
    ('compact_label', 'Coal', False),
    ('cover_year', '2025', True),
    ('diagram_node', 'AI', True),
])
def test_short_table_words_bypass_min_text_length(label, value, expected):
    from babeldoc.format.pdf.document_il.utils import paragraph_helper
    bypass = getattr(paragraph_helper, 'bypasses_min_text_length', None)
    assert bypass is not None, 'bypasses_min_text_length helper missing'
    assert bypass(NS(layout_label=label, unicode=value)) is expected


def test_released_usgs_coal_row_reaches_translation():
    from babeldoc.format.pdf.document_il.utils import paragraph_helper
    bypass = getattr(paragraph_helper, 'bypasses_min_text_length', None)
    assert bypass is not None
    coal = by_text(run(USGS_TABLE), 'Coal')[0]
    assert translatable(coal) and bypass(coal)


# ---------------------------------------------------------------- 放开范围

LEGEND = 'arxiv2505.23884-p3-fig1-legend.json'


@pytest.mark.parametrize('label', ['Ours Linear', 'Ours Nonlinear', 'Original TTT-Linear', 'Mamba2'])
def test_chart_legend_entries_outside_tables_and_nodes_keep_source(label):
    # 白底绘图区里的图例多是方法名，且排得很紧；第一次真实回归中把它们送去翻译，
    # 译文在硬可读下限下放不下，整份文档被阻断。只在表格区与有色填充节点内放开。
    for paragraph in by_text(run(LEGEND), label):
        assert paragraph.layout_label == 'compact_label'


def test_coloured_fill_detection_ignores_white_plot_areas():
    from babeldoc.format.pdf.document_il.midend.table_figure_text import figure_nodes
    assert figure_nodes(load_page(LEGEND)[1]) == []
    assert len(figure_nodes(load_page('arxiv2610.21759-p4-fig2.json')[1])) >= 2


# ---------------------------------------------------------------- 评审第 1 轮（33918b3）

def relabelled(name, *pairs):
    """在真实夹具几何上把一行文字换成不长于它的另一段文字（逐字复用原字框，多余的字删去）。"""
    data = json.loads((FIXTURES / name).read_text(encoding='utf-8'))
    for old, new in pairs:
        assert len(new) <= len(old), (old, new)
        stream = ''.join(row[0] for row in data['chars'])
        start = stream.find(old)
        assert start >= 0, old
        rows = [list(row) for row in data['chars'][start:start + len(new)]]
        for row, ch in zip(rows, new):
            row[0] = ch
        data['chars'][start:start + len(old)] = rows
    chars = []
    for serial, row in enumerate(data['chars']):
        u, *g, font_id, size, vertical, xobj_id, render_order = row
        chars.append(il.PdfCharacter(
            pdf_style=il.PdfStyle(font_id=font_id, font_size=size, graphic_state=il.GraphicState()),
            box=_box(g[:4]), visual_bbox=il.VisualBbox(box=_box(g[4:8])), vertical=vertical, scale=1.0,
            pdf_character_id=serial, char_unicode=u, xobj_id=xobj_id, render_order=render_order))
    _, page = load_page(name)
    page.pdf_character = chars
    finder = ParagraphFinder.__new__(ParagraphFinder)
    finder.translation_config = NS(**data['config'])
    finder.process_page(page)
    return page


# P1：基线锚定不得让译文排版单元侵入相邻行；侵入时 fit 不能报 True。

def _anchored(box, anchor=None, label='fallback_line'):
    paragraph = il.PdfParagraph(box=box, layout_label=label, first_line_indent=False, debug_id=str(box.y))
    if anchor is not None:
        paragraph.source_baseline = anchor
    return paragraph


def _assign_ceilings(page):
    from babeldoc.format.pdf.document_il.midend import table_figure_text
    assign = getattr(table_figure_text, 'assign_baseline_ceilings', None)
    if assign is not None:
        assign(page)


def _layout(paragraph, text='煤炭开采', size=10.02):
    return _typesetter()._layout_typesetting_units(_units(text, size), paragraph.box, 1.0, 1.5, paragraph)


def _intersects(a, b):
    return any(min(u.box.x2, v.box.x2) - max(u.box.x, v.box.x) > 0.01
               and min(u.box.y2, v.box.y2) - max(u.box.y, v.box.y) > 0.01 for u in a for v in b)


def _dense_page(paragraphs):
    return il.Page(page_number=1, cropbox=il.Cropbox(box=il.Box(0, 0, 612, 792)),
                   mediabox=il.Mediabox(box=il.Box(0, 0, 612, 792)), pdf_paragraph=paragraphs,
                   pdf_character=[], pdf_curve=[], page_layout=[])


def test_baseline_lift_never_intrudes_into_dense_previous_line():
    # 自造几何：两行源框只隔 0.71 pt（与评审复现的密集行相同量级）。上一行没有锚点（多行段/普通行），
    # 下一行要上移约 2.9 pt 才落到原文基线。
    upper = _anchored(il.Box(x=51.0, y=700.0, x2=219.0, y2=710.55))
    lower = _anchored(il.Box(x=51.0, y=688.74, x2=219.0, y2=699.29), anchor=692.0)
    _assign_ceilings(_dense_page([upper, lower]))
    up_units, up_fit = _layout(upper)
    low_units, low_fit = _layout(lower)
    assert up_units and low_units
    assert not (up_fit and low_fit and _intersects(up_units, low_units)), (
        min(u.box.y for u in up_units), max(u.box.y2 for u in low_units))
    # 上移被夹住时仍要上移到夹住的位置，而不是退回框底
    assert max(u.box.y2 for u in low_units) <= upper.box.y + 0.01


def test_baseline_lift_clamp_propagates_through_a_stack_of_anchored_rows():
    # 三行等距密排，三行都有锚点：每一行的上移量都受上一行（已夹住后的）实际下沿限制。
    rows = [_anchored(il.Box(x=51.0, y=700.0 - 11.26 * k, x2=219.0, y2=710.55 - 11.26 * k),
                      anchor=703.26 - 11.26 * k) for k in range(3)]
    rows.insert(0, _anchored(il.Box(x=51.0, y=711.26, x2=219.0, y2=721.81)))   # 顶上一行无锚点
    _assign_ceilings(_dense_page(rows))
    laid = [_layout(row) for row in rows]
    for (a, fa), (b, fb) in zip(laid, laid[1:]):
        assert not (fa and fb and _intersects(a, b))


def test_usgs_rows_keep_source_baseline_after_neighbour_clamp():
    # 夹住上移不能把已修好的 USGS 表格行重新压回框底：上一行同样上移，空间够。
    page = run(USGS_TABLE)
    _assign_ceilings(page)
    for label in ('Metals', 'Industrial minerals'):
        row = by_text(page, label)[0]
        units, fit = _layout(row, '金属')
        assert fit and abs(min(u.box.y for u in units) - row.source_baseline) <= 0.05, label


# P2a：上下文放行不能吃掉专名保护；模型原样返回专名时不能判为未翻译。

def test_capitalised_name_next_to_lowercase_text_is_not_context_released():
    # 评审复现：小写的 dataset 与 Amazon 相邻。小写词不是同类行标签；紧挨小写文字的首字母大写词
    # 更像专名（英文里普通名词不在小写短语旁大写），不能借它的上下文放行。
    page = relabelled(USGS_TABLE, ('Total mine production (million dollars):', 'dataset'),
                      ('Industrial minerals', 'dataset'), ('Metals', 'Amazon'))
    amazon = by_text(page, 'Amazon')
    assert all(p.layout_label == 'compact_label' for p in amazon), [p.layout_label for p in amazon]


def _post_translate_identity(paragraph):
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator, ParagraphTranslateTracker
    translator = ILTranslator.__new__(ILTranslator)
    tracker = ParagraphTranslateTracker()
    tracker.new_llm_translate_tracker()
    source = text(paragraph)
    before = list(paragraph.pdf_paragraph_composition)
    applied = translator.post_translate_paragraph(paragraph, tracker, NS(unicode=source, placeholders=[]), source)
    return applied, tracker, before


def test_identical_answer_for_context_released_name_keeps_source_without_rejection():
    # Amazon 在一列首字母大写的普通行名里（真实几何），按上下文送去翻译；模型正确地原样返回时，
    # 应当保留原文字形，不记为 rejected / same_as_input 失败。
    page = relabelled(USGS_TABLE, ('Metals', 'Amazon'))
    amazon = by_text(page, 'Amazon')[0]
    assert translatable(amazon)
    applied, tracker, before = _post_translate_identity(amazon)
    assert applied is True
    assert getattr(tracker, 'writeback_status', None) != 'rejected', getattr(tracker, 'writeback_reason', None)
    assert amazon.pdf_paragraph_composition == before


def test_identical_answer_for_context_released_name_is_not_a_tracking_failure(tmp_path):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from pdf_translation_tracking import extract_tracking_failures
    page = relabelled(USGS_TABLE, ('Metals', 'Amazon'))
    amazon = by_text(page, 'Amazon')[0]
    _, tracker, _ = _post_translate_identity(amazon)
    row = {'input': 'Amazon', 'output': tracker.output or 'Amazon', 'pdf_unicode': 'Amazon', 'page': 1,
           'layout_role': amazon.layout_label, 'writeback_status': getattr(tracker, 'writeback_status', None),
           'writeback_reason': getattr(tracker, 'writeback_reason', None),
           'llm_translate_trackers': [t.to_dict() for t in tracker.llm_translate_trackers]}
    path = tmp_path / 'translate_tracking.json'
    path.write_text(json.dumps({'page': [{'paragraph': [row]}]}), encoding='utf-8')
    assert extract_tracking_failures(path) == []


def test_ordinary_identical_answer_is_still_rejected():
    # 收窄：只有「仅凭上下文放行」的标签允许原样返回；自身就是自然短语的行名原样返回仍是失败。
    page = run(USGS_TABLE)
    row = by_text(page, 'Industrial minerals')[0]
    applied, tracker, _ = _post_translate_identity(row)
    assert applied is False and tracker.writeback_status == 'rejected'


# P2b：普通表头里的 Group/Company 等普通名词不能被当成机构名直通。

@pytest.mark.parametrize('label', ['Control Group', 'Treatment Group'])
def test_generic_group_headers_are_translated(label):
    page = relabelled(USGS_TABLE, ('Total mine production (million dollars):', 'Control Group'),
                      ('Industrial minerals', 'Treatment Group'))
    for paragraph in by_text(page, label):
        assert translatable(paragraph), (label, paragraph.layout_label)


@pytest.mark.parametrize('label,expected', [
    ('Control Group', True), ('Treatment Group', True), ('Age Group', True), ('Research Institute', True),
    ('Acme Inc.', False), ('Globex Corp', False), ('Initech LLC', False), ('Siemens GmbH', False),
    ('Umbrella Ltd', False), ('Meta AI', False),
])
def test_institution_rule_only_fires_on_legal_entity_suffixes(label, expected):
    from babeldoc.format.pdf.document_il.midend.table_figure_text import is_natural_label
    assert is_natural_label(label) is expected
