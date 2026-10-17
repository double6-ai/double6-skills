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
