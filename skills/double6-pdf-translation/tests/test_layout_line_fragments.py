"""realmodel-r1 问题 #3/#4/#5 的回归测试：行边缘英文残片、带样式行内片段重叠、目录/表头结构塌陷。

真实几何夹具来自 NIST AI 100-1（AI RMF 1.0，美国联邦政府作品，公有领域），见
tests/fixtures/layout_fragments/README.md：用 BabelDOC 调试输出导出 ParagraphFinder 入口的逐字符几何与
版面检测框（保留整页版面框，R-tree 的插入顺序与真实运行一致）。表格列与行距用例为按实测数值构造的
合成几何。测试直接运行真实的 ParagraphFinder.process_page 与 Typesetting._layout_typesetting_units，
不依赖模型、网络或字体下载。
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/babeldoc'))
sys.path.insert(0, str(ROOT / 'tests'))
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder  # noqa: E402
import test_table_figure_text as tft  # noqa: E402

FIXTURES = ROOT / 'tests/fixtures/layout_fragments'
PASSTHROUGH = {'compact_label', 'code_label', 'code_passthrough_label', 'latex_structure_fragment', 'cover_year'}


def run(name):
    saved = tft.FIXTURES
    tft.FIXTURES = FIXTURES
    try:
        data, page = tft.load_page(name)
    finally:
        tft.FIXTURES = saved
    finder = ParagraphFinder.__new__(ParagraphFinder)
    finder.translation_config = NS(**data['config'])
    finder.process_page(page)
    return page


def text(paragraph):
    return re.sub(r'\s+', ' ', paragraph.unicode or '').strip()


def texts(page):
    return [text(p) for p in page.pdf_paragraph]


# ---------------------------------------------------------------- #3 行边缘残片

def test_body_line_wider_than_layout_box_is_one_translation_unit():
    # 版面框 x=126..498 比实际行 90..504 窄：行首 "The Arti" 和行尾 "t." 不能被切成紧凑标签留英文。
    page = run('nist-ai100-1-p2-update-schedule.json')
    found = [p for p in page.pdf_paragraph if text(p).startswith('The Artificial Intelligence')]
    assert len(found) == 1, texts(page)
    assert text(found[0]).endswith('living document.'), text(found[0])
    assert found[0].layout_label not in PASSTHROUGH
    assert not any(t in {'The Arti', 't.'} for t in texts(page)), texts(page)


def test_toc_title_wider_than_layout_box_keeps_whole_title_and_page_number():
    page = run('nist-ai100-1-p3-toc-top.json')
    assert 'Executive S' not in texts(page) and 'ummary' not in texts(page), texts(page)
    title = [p for p in page.pdf_paragraph if text(p) == 'Executive Summary']
    assert len(title) == 1 and title[0].layout_label == 'toc_entry', texts(page)
    assert [p for p in page.pdf_paragraph if p.layout_label == 'toc_page_number' and text(p) == '1']


# ---------------------------------------------------------------- #5 目录塌陷

def test_list_of_tables_keeps_four_rows_with_separate_page_numbers():
    # 两个重叠的同类正文框：末行曾被 R-tree 顺序分到内框，切成 "Table 4 Cate" / "gories ... 32"，
    # 其余三行凑不够目录行数并成一段，页码混入正文。
    page = run('nist-ai100-1-p3-list-of-tables.json')
    rows = [p for p in page.pdf_paragraph if p.layout_label == 'toc_entry']
    assert [text(p).split(' Categories')[0] for p in rows] == ['Table 1', 'Table 2', 'Table 3', 'Table 4'], texts(page)
    assert all(not re.search(r'\d{2}\s*$', text(p)) for p in rows), texts(page)
    numbers = [text(p) for p in page.pdf_paragraph if p.layout_label == 'toc_page_number']
    assert numbers == ['22', '26', '29', '32'], texts(page)


def test_table_caption_outside_a_contents_page_keeps_caption_role_and_number():
    # 反例：不在目录里的表题（无目录拆行证据）仍是表题，结尾数字不拆成页码。
    chars, x = _word_chars('Table', 90, 400, 11.0, 5.5)
    for word in ('2', 'Results', 'by', 'field', 'in', '2022'):
        more, x = _word_chars(word, x + 3.0, 400, 11.0, 5.5)
        chars += more
    page = _process(_page(chars, [('table_caption', (88, 396, 300, 414))]))
    captions = [p for p in page.pdf_paragraph if p.layout_label == 'table_caption']
    assert [text(p) for p in captions] == ['Table 2 Results by field in 2022'], texts(page)
    assert not [p for p in page.pdf_paragraph if p.layout_label == 'toc_page_number'], texts(page)


# ---------------------------------------------------------------- #3 反例：其他角色不动

def _char(u, x, y, w, size=9.0, font='F1'):
    box = il.Box(x=x, y=y, x2=x + w, y2=y + size)
    return il.PdfCharacter(pdf_style=il.PdfStyle(font_id=font, font_size=size, graphic_state=il.GraphicState()),
                           box=box, visual_bbox=il.VisualBbox(box=il.Box(x=x, y=y + 0.5, x2=x + w, y2=y + size - 1)),
                           vertical=False, scale=1.0, pdf_character_id=ord(u[0]), char_unicode=u, xobj_id=0,
                           render_order=0)


def _word_chars(word, x, y, size=9.0, step=None):
    step = step or size * 0.5
    out = []
    for u in word:
        out.append(_char(u, x, y, step * 0.9, size))
        x += step
    return out, x


def _page(chars, layouts):
    return il.Page(page_number=0, cropbox=il.Cropbox(box=il.Box(0, 0, 612, 792)),
                   mediabox=il.Mediabox(box=il.Box(0, 0, 612, 792)), pdf_font=[il.PdfFont(font_id='F1', name='Times')],
                   pdf_xobject=[], page_layout=[il.PageLayout(id=i + 1, class_name=c, box=il.Box(*b), conf=1.0)
                                                for i, (c, b) in enumerate(layouts)],
                   pdf_character=chars, pdf_curve=[], pdf_paragraph=[])


def _add_fallback_lines(page):
    # 与 LayoutParser.generate_fallback_line_layout_for_page 相同：按字符几何聚出物理行。
    from babeldoc.format.pdf.document_il.utils import extract_char
    clusters = extract_char.process_page_chars_to_lines(extract_char.convert_page_to_char_boxes(page))
    for cluster in clusters:
        boxes = [c[0] for c in cluster.chars]
        page.page_layout.append(il.PageLayout(
            id=len(page.page_layout) + 1, class_name='fallback_line', conf=1,
            box=il.Box(min(b.x for b in boxes), min(b.y for b in boxes), max(b.x2 for b in boxes), max(b.y2 for b in boxes))))


def _process(page):
    _add_fallback_lines(page)
    finder = ParagraphFinder.__new__(ParagraphFinder)
    finder.translation_config = NS(formular_font_pattern=None, ocr_workaround=False, debug=False, split_short_lines=False,
                                   short_line_split_factor=0.8, merge_alternating_line_numbers=True)
    finder.process_page(page)
    return page


def test_line_partly_inside_a_table_cell_box_is_not_regrouped():
    # 行的一部分落在表格单元格框：表格角色不参与统一，旧行为不变。
    chars, _ = _word_chars('Totalsample', 100, 400)
    page = _process(_page(chars, [('table_cell', (120, 395, 200, 412))]))
    labels = {(p.layout_label, text(p)) for p in page.pdf_paragraph}
    assert any(label == 'table_cell' for label, _ in labels), labels
    assert not any(t == 'Totalsample' for _, t in labels), labels


def test_box_covering_only_the_top_of_a_line_does_not_absorb_it():
    # 正文框只擦到行顶（纵向覆盖 < 60%）：这行属于别的段落，不并入该框。
    chars, _ = _word_chars('Elsewhere', 100, 400)
    page = _process(_page(chars, [('plain text', (100, 407, 300, 460))]))
    assert all(p.layout_label != 'plain text' or text(p) != 'Elsewhere' for p in page.pdf_paragraph), texts(page)


# ---------------------------------------------------------------- #5 表头按全表列间空白拆分

COLUMNS = (156.0, 204.5, 243.5, 283.5)


def _table_chars(rows=(('Alpha', '8509', '0.561', '0.157'), ('Beta', '5101', '0.538', '0.118'))):
    """按实测表头几何构造：表头单元格之间用空格字形填满到下一列起点（行聚类因此聚成一整行），
    数据行各单元格之间没有空格字形。"""
    chars = []
    y = 200.0
    words = ('Region', 'Count', 'Mean', 'Spread')
    for i, (col, word) in enumerate(zip(COLUMNS, words)):
        word_chars, x = _word_chars(word, col, y, 9.0, 4.5)
        chars += word_chars
        if i + 1 < len(COLUMNS):
            chars.append(_char(' ', x, y, COLUMNS[i + 1] - x))
    for r, row in enumerate(rows):
        y = 182.0 - 16.0 * r
        for col, value in zip(COLUMNS, row):
            if value:
                chars += _word_chars(value, col, y, 9.0, 4.5)[0]
    return chars


def _header(page):
    return sorted((p.box.x, text(p)) for p in page.pdf_paragraph if p.box.y >= 199.0)


def test_table_header_row_is_split_at_gutters_shared_by_every_row():
    page = _process(_page(_table_chars(), [('table', (149, 120, 446, 212))]))
    assert [t for _, t in _header(page)] == ['Region', 'Count', 'Mean', 'Spread'], texts(page)
    for (x, _), col in zip(_header(page), COLUMNS):
        assert abs(x - col) < 1.0


def test_table_header_is_not_split_where_a_data_cell_spans_the_gap():
    # 数据行在表头空白处有字（跨列单元格）：该位置不是全表共有的列间空白，不拆。
    rows = (('Alpha', '8509', '0.561', '0.157'), ('Beta-spanning-a-very-wide-cell-x', '', '', ''))
    page = _process(_page(_table_chars(rows), [('table', (149, 120, 446, 212))]))
    header = [t for _, t in _header(page)]
    assert 'Region' not in header and any(t.startswith('Region Count') for t in header), texts(page)


def test_header_like_line_outside_any_table_is_not_split():
    page = _process(_page(_table_chars(), []))
    assert [t for _, t in _header(page)] == ['Region Count Mean Spread'], texts(page)


# ---------------------------------------------------------------- #4 原文字形行的行距

class _Font:
    def char_lengths(self, text, size):
        return [size for _ in text]


def _typesetter():
    from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
    stage = Typesetting.__new__(Typesetting)
    stage.font_mapper = NS(base_font=_Font())
    stage.is_cjk = True
    return stage


def _cjk_units(chars, size):
    from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
    style = il.PdfStyle(font_id='base', font_size=size, graphic_state=il.GraphicState())
    return [TypesettingUnit(unicode=c, font=_Font(), font_size=size, style=style, xobj_id=0) for c in chars]


def _source_glyph_units(word, size):
    """原文字形（链接/引用样式原样保留）：逻辑框一个字号高，可见墨迹框只有小写字母高。"""
    from babeldoc.format.pdf.document_il.midend.typesetting import TypesettingUnit
    out = []
    for u in word:
        ink = 0.45 * size if u.islower() else (0.11 * size if u in '.,;' else 0.68 * size)
        char = il.PdfCharacter(pdf_style=il.PdfStyle(font_id='F163', font_size=size, graphic_state=il.GraphicState()),
                               box=il.Box(x=0, y=0, x2=0.5 * size, y2=size),
                               visual_bbox=il.VisualBbox(box=il.Box(x=0, y=0, x2=0.5 * size, y2=ink)),
                               vertical=False, scale=1.0, pdf_character_id=1, char_unicode=u, xobj_id=0)
        out.append(TypesettingUnit(char=char))
    return out


def _baselines(units):
    rows = sorted({round(u.box.y, 2) for u in units if (u.try_get_unicode() or '').strip()}, reverse=True)
    return rows


def test_line_of_source_glyph_citations_keeps_full_line_pitch():
    size = 10.91
    units = (_cjk_units('线性循环网络' * 2, size) + _source_glyph_units('al.,2018; Li et al.,2018; Balduzzi', size)
             + _source_glyph_units('Ghifary,2016; Gu and Dao,2024; Qin', size) + _cjk_units('即便它们本身就有能力编码位置', size))
    box = il.Box(x=70.0, y=400.0, x2=290.0, y2=500.0)
    paragraph = il.PdfParagraph(box=box, layout_label='plain text', first_line_indent=False)
    placed, fit = _typesetter()._layout_typesetting_units(units, box, 1.0, 1.5, paragraph)
    assert placed
    rows = _baselines(placed)
    assert len(rows) >= 4, rows
    pitches = [a - b for a, b in zip(rows, rows[1:])]
    # 每一行至少一个字号的行距（不重叠），且与纯中文行的行距一致。
    assert min(pitches) >= size * 1.45, pitches
    assert max(pitches) - min(pitches) < 0.5, pitches


def test_cjk_only_paragraph_line_pitch_is_unchanged():
    size = 10.0
    units = _cjk_units('这是一个只有中文字符的普通段落用于检查行距保持不变' * 2, size)
    box = il.Box(x=0.0, y=0.0, x2=100.0, y2=200.0)
    paragraph = il.PdfParagraph(box=box, layout_label='plain text', first_line_indent=False)
    placed, fit = _typesetter()._layout_typesetting_units(units, box, 1.0, 1.5, paragraph)
    rows = _baselines(placed)
    pitches = {round(a - b, 3) for a, b in zip(rows, rows[1:])}
    assert pitches == {15.0}, pitches
