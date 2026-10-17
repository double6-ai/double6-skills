"""PR #2：双栏数学论文行内公式跨行折断后被合并、错位、占位符丢失的回归测试。

夹具来自真实论文（CC BY 4.0，见 tests/fixtures/inline_math/README.md）：用官方入口跑到
BabelDOC「Parse Formulas and Styles」阶段之前，导出受影响段落的逐字符几何、字体名与
目标字体 has_char 结果。这里不提交 PDF（沿用仓库约定），只提交几十 KB 的几何 JSON。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/babeldoc'))
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.styles_and_formulas import StylesAndFormulas  # noqa: E402

FIXTURES = sorted((ROOT / 'tests/fixtures/inline_math').glob('*.json'))


class _FontMapper:
    """记录真实 FontMapper.has_char 结果的替身（CI 中没有下载字体资源）。"""

    def __init__(self, table):
        self.table = table

    def has_char(self, char):
        return self.table.get(char, True)


def _config():
    return NS(formular_font_pattern=None, formular_char_pattern=None, skip_formula_offset_calculation=False,
              ocr_workaround=False, remove_non_formula_lines=False)


def _stage(table):
    stage = StylesAndFormulas.__new__(StylesAndFormulas)
    stage.translation_config = _config()
    stage.font_mapper = _FontMapper(table)
    return stage


def _box(v):
    return il.Box(x=v[0], y=v[1], x2=v[2], y2=v[3])


def _char(row, serial):
    u, *g, font_id, size, vertical, formula_layout_id = row
    return il.PdfCharacter(pdf_style=il.PdfStyle(font_id=font_id, font_size=size, graphic_state=il.GraphicState()),
                           box=_box(g[:4]), visual_bbox=il.VisualBbox(box=_box(g[4:8])), vertical=vertical,
                           scale=1.0, pdf_character_id=serial, char_unicode=u, formula_layout_id=formula_layout_id)


def _line(chars):
    return il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars, box=il.Box(
        x=min(c.box.x for c in chars), y=min(c.box.y for c in chars),
        x2=max(c.box.x2 for c in chars), y2=max(c.box.y2 for c in chars))))


def load(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    serial = 0
    compositions = []
    for row_line in data['lines']:
        chars = []
        for row in row_line:
            chars.append(_char(row, serial))
            serial += 1
        compositions.append(_line(chars))
    paragraph = il.PdfParagraph(box=_box(data['box']), pdf_paragraph_composition=compositions,
                                xobj_id=data['xobj_id'], debug_id=data['debug_id'],
                                layout_label=data['layout_label'], layout_id=data['layout_id'])
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id=f['font_id'], name=f['name']) for f in data['fonts']],
                   pdf_paragraph=[paragraph])
    return data, page


def flatten(composition):
    for name in ('pdf_line', 'pdf_formula', 'pdf_same_style_characters'):
        part = getattr(composition, name)
        if part is not None:
            return list(part.pdf_character)
    if composition.pdf_character is not None:
        return [composition.pdf_character]
    return []


def wrap_count(chars, left, right):
    """独立于实现的折行判据：下一个字形回到栏左缘且整体落到上一字形下方。"""
    width = right - left
    count, prev = 0, None
    for char in chars:
        if (char.char_unicode or '').isspace():
            continue
        if prev is not None:
            centre = (char.box.y + char.box.y2) / 2
            if (prev.box.x - char.box.x > max(20.0, 0.35 * width) and centre < prev.box.y
                    and char.box.x - left <= 0.25 * width and prev.box.x2 - left >= 0.6 * width):
                count += 1
        prev = char
    return count


def run(path):
    data, page = load(path)
    original = [c.pdf_character_id for comp in page.pdf_paragraph[0].pdf_paragraph_composition
                for c in flatten(comp) if (c.char_unicode or '').strip()]
    _stage(data['has_char']).process_page(page)
    return data, page, original


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_fixture_reproduces_a_visual_line_wrap_inside_a_merged_line(path):
    data, page = load(path)
    left, right = data['box'][0], data['box'][2]
    assert any(wrap_count(flatten(comp), left, right) for comp in page.pdf_paragraph[0].pdf_paragraph_composition)


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_no_formula_spans_a_visual_line_wrap(path):
    data, page, _ = run(path)
    left, right = data['box'][0], data['box'][2]
    bad = [''.join(c.char_unicode or '' for c in comp.pdf_formula.pdf_character)
           for comp in page.pdf_paragraph[0].pdf_paragraph_composition
           if comp.pdf_formula is not None and wrap_count(comp.pdf_formula.pdf_character, left, right)]
    assert bad == []


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: p.stem)
def test_formula_and_text_keep_source_reading_order(path):
    """合并跨行公式会把后文公式字符整体搬到第一个公式处：译文里只剩一个 {vN}，其余位置留下空洞。"""
    _, page, original = run(path)
    after = [c.pdf_character_id for comp in page.pdf_paragraph[0].pdf_paragraph_composition
             for c in flatten(comp) if (c.char_unicode or '').strip()]
    assert sorted(after) == sorted(original)  # 不丢字形
    assert after == original  # 不重排


def _formulas(page):
    return [''.join(c.char_unicode or '' for c in comp.pdf_formula.pdf_character).replace(' ', '')
            for comp in page.pdf_paragraph[0].pdf_paragraph_composition if comp.pdf_formula is not None]


def test_doc02_non_autoregressive_paragraph_keeps_each_inline_formula():
    _, page, _ = run(ROOT / 'tests/fixtures/inline_math/arxiv2501.00659-p2-nonautoregressive.json')
    formulas = _formulas(page)
    # 原文："removing the mask M, i.e., by setting Mi,j = 1 for all i, j ∈ {1, ..., T}. We denote such M as M = 𝟙."
    assert 'Mi,j=1' in formulas
    assert 'M=1' in formulas
    assert not any('∈' in f and '{' in f and f.index('{') < f.index('∈') for f in formulas)
    assert sum(1 for f in formulas if f.startswith('M')) >= 4


# ---- 合成边界：保守判据，不误拆真正的二维公式 ----

def _synthetic(rows, box=(300.0, 100.0, 520.0, 140.0)):
    """rows: [(text, x, y_bottom, font)]，每个字形宽 5pt、高 8pt。"""
    chars, serial = [], 0
    for text, x, y, font in rows:
        for i, ch in enumerate(text):
            chars.append(_char([ch, x + 5 * i, y, x + 5 * i + 5, y + 8, x + 5 * i, y, x + 5 * i + 5, y + 8,
                                font, 10.0, False, None], serial))
            serial += 1
    paragraph = il.PdfParagraph(box=il.Box(x=box[0], y=box[1], x2=box[2], y2=box[3]),
                                pdf_paragraph_composition=[_line(chars)], debug_id='syn', layout_label='plain text')
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id='T', name='NimbusRomNo9L-Regu'),
                                            il.PdfFont(font_id='M', name='CMMI10')], pdf_paragraph=[paragraph])
    _stage({}).process_page(page)
    return _formulas(page)


def test_inline_fraction_stays_one_formula():
    # 分子在上、分母左移到下方，但只左移了分子宽度，不是回到栏左缘。
    formulas = _synthetic([('see ', 300, 120, 'T'), ('ab', 480, 124, 'M'), ('cd', 480, 114, 'M'), (' ok', 492, 120, 'T')])
    assert formulas == ['abcd']


def test_centred_two_row_formula_stays_one_formula():
    # 第二行回退很多但并不回到栏左缘（居中排版），不是折行。
    formulas = _synthetic([('let ', 300, 130, 'T'), ('xxxxxxxxxxxxxxxxxxxx', 400, 130, 'M'),
                           ('yyyyyyyyyyyyyyyy', 380, 118, 'M'), (' end', 470, 118, 'T')])
    assert formulas == ['xxxxxxxxxxxxxxxxxxxxyyyyyyyyyyyyyyyy']


def test_wrapped_inline_formula_is_split_at_the_line_break():
    formulas = _synthetic([('for all ', 300, 130, 'T'), ('ij', 505, 130, 'M'), ('kl', 300, 118, 'M'), (' end', 310, 118, 'T')])
    assert formulas == ['ij', 'kl']


def test_non_adjacent_formulas_with_text_between_are_not_merged():
    # 第二个公式的虚高外框完全包含第一个公式（CMEX 大括号偏移外框），但二者之间有正文。
    chars, serial = [], 0
    rows = [('3', 353.6, 229.0, 358.1, 236.0, 'M'), ('.', 358.4, 229.1, 360.9, 239.1, 'T'),
            (' ', 360.9, 229.1, 362.1, 239.1, 'T'), ('a', 362.1, 229.1, 367.0, 239.1, 'T'),
            ('(', 336.8, 207.8, 342.0, 235.3, 'M'), ('v', 342.2, 210.8, 346.2, 225.1, 'M'),
            (')', 358.0, 207.8, 364.5, 235.3, 'M'), (' ', 364.5, 214.2, 365.0, 224.2, 'T'),
            ('b', 365.0, 214.2, 370.0, 224.2, 'T')]
    for u, x, y, x2, y2, font in rows:
        chars.append(_char([u, x, y, x2, y2, x, y, x2, y2, font, 10.0, False, None], serial))
        serial += 1
    paragraph = il.PdfParagraph(box=il.Box(x=312.0, y=195.0, x2=565.0, y2=241.0),
                                pdf_paragraph_composition=[_line(chars)], debug_id='syn', layout_label='plain text')
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id='T', name='NimbusRomNo9L-Regu'),
                                            il.PdfFont(font_id='M', name='CMMI10')], pdf_paragraph=[paragraph])
    _stage({}).process_page(page)
    order = [c.pdf_character_id for comp in page.pdf_paragraph[0].pdf_paragraph_composition for c in flatten(comp)
             if (c.char_unicode or '').strip()]
    assert order == sorted(order)
    assert not any('3' in f and '(' in f for f in _formulas(page))


def test_subscript_comma_does_not_split_formula():
    chars, serial = [], 0
    rows = [('s', 300, 120, 305, 128, 'T', 10.0), (' ', 305, 120, 307, 128, 'T', 10.0),
            ('M', 307, 120, 316, 128, 'M', 10.0), ('i', 316, 118, 319, 124, 'M', 7.0),
            (',', 319, 118, 321, 124, 'M', 7.0), ('j', 321, 118, 324, 124, 'M', 7.0),
            ('=', 326, 120, 333, 128, 'M', 10.0), ('1', 335, 120, 340, 128, 'M', 10.0),
            (' ', 340, 120, 342, 128, 'T', 10.0), ('o', 342, 120, 347, 128, 'T', 10.0)]
    for u, x, y, x2, y2, font, size in rows:
        chars.append(_char([u, x, y, x2, y2, x, y, x2, y2, font, size, False, None], serial))
        serial += 1
    paragraph = il.PdfParagraph(box=il.Box(x=300.0, y=100.0, x2=520.0, y2=140.0),
                                pdf_paragraph_composition=[_line(chars)], debug_id='syn', layout_label='plain text')
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id='T', name='NimbusRomNo9L-Regu'),
                                            il.PdfFont(font_id='M', name='CMMI10')], pdf_paragraph=[paragraph])
    _stage({}).process_page(page)
    assert _formulas(page) == ['Mi,j=1']
