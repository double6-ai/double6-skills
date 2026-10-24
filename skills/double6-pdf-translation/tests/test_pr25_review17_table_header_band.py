"""评审17 原P1-1窄项：表头行上下真实横线之间已确认空白的搜索（拉丁目标语言 stage 2）。

全部为合成几何与合成字体（fontTools 生成，字形轮廓已知），不读取任何文档、文字或坐标常量；
只验证：两条横跨本框的细横线 + 行带内无占用 + 字形墨迹在带内 才借用上方空白，其余保守拒绝。
"""
import io
import sys
from pathlib import Path

import pymupdf
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'vendor/babeldoc')]
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting, TypesettingUnit  # noqa: E402

DESCENDERS = set('gjpqy')
LONG_DESCENDER = 'Q'  # 合成：墨迹下伸 0.6em，用来验证墨迹核对


def _rect(pen, x0, y0, x1, y1):
    pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()


def _font_bytes():
    chars = [chr(c) for c in range(ord('A'), ord('Z') + 1)] + [chr(c) for c in range(ord('a'), ord('z') + 1)]
    order = ['.notdef', 'space'] + [f'g{ord(c)}' for c in chars]
    glyphs, metrics, cmap = {}, {}, {ord(' '): 'space'}
    pen = TTGlyphPen(None); _rect(pen, 50, 0, 450, 700); glyphs['.notdef'] = pen.glyph(); metrics['.notdef'] = (500, 50)
    glyphs['space'] = TTGlyphPen(None).glyph(); metrics['space'] = (250, 0)
    for c in chars:
        pen = TTGlyphPen(None)
        low = -600 if c == LONG_DESCENDER else (-200 if c in DESCENDERS else 0)
        _rect(pen, 40, low, 460, 520 if c.islower() else 700)
        name = f'g{ord(c)}'; glyphs[name] = pen.glyph(); metrics[name] = (500, 40); cmap[ord(c)] = name
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs); fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({'familyName': 'BandSynthetic', 'styleName': 'Regular'})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200); fb.setupPost()
    out = io.BytesIO(); fb.save(out); return out.getvalue()


FONT = pymupdf.Font(fontbuffer=_font_bytes())
FONT.font_id = 'band-synthetic'

# 合成表头行：上横线 TOP、下横线 BOTTOM，源字框在两线之间偏下；下一列从 NEXT_X 开始。
TOP, BOTTOM, NEXT_X = 208.2, 190.9, 100.0


def _stage(cjk=False):
    stage = Typesetting.__new__(Typesetting)
    stage.is_cjk = cjk
    stage.font_mapper = type('M', (), {'base_font': FONT})()
    return stage


def _material(*, rules=True, top=TOP, extra_curves=(), extra_paras=(), layouts=(), forms=(), figures=(), label='fallback_line', rule_x=(40.0, 300.0)):
    style = il.PdfStyle(font_id=FONT.font_id, font_size=9.0, graphic_state=il.GraphicState())
    para = il.PdfParagraph(box=il.Box(60.0, 194.8, 85.0, 205.0), unicode='源', layout_label=label,
                           first_line_indent=False, pdf_style=style, pdf_paragraph_composition=[])
    neighbour = il.PdfParagraph(box=il.Box(NEXT_X, 194.8, 125.0, 205.0), unicode='邻', layout_label=label,
                                first_line_indent=False, pdf_style=style, pdf_paragraph_composition=[])
    curves = [il.PdfCurve(box=il.Box(rule_x[0], top, rule_x[1], top)), il.PdfCurve(box=il.Box(rule_x[0], BOTTOM, rule_x[1], BOTTOM))] if rules else []
    page = il.Page(page_number=1, cropbox=il.Cropbox(box=il.Box(0, 0, 400, 400)), pdf_paragraph=[para, neighbour, *extra_paras],
                   pdf_character=[], pdf_figure=list(figures), pdf_form=list(forms), page_layout=list(layouts),
                   pdf_curve=[*curves, *extra_curves])
    return para, page, style


def _units(text, style):
    return [TypesettingUnit(unicode=c, font=FONT, font_size=style.font_size, style=style, xobj_id=0) for c in text]


def _run(text, cjk=False, **kw):
    para, page, style = _material(**kw)
    stage = _stage(cjk)
    scale, laid = stage._find_optimal_scale_and_layout(para, page, _units(text, style), apply_layout=True)
    return stage, para, page, scale, laid


def _ink(laid):
    out = []
    for u in laid:
        c = u.try_get_unicode()
        if c.isspace():
            continue
        low = -0.6 if c == LONG_DESCENDER else (-0.2 if c in DESCENDERS else 0.0)
        out.append((u.box.x + 0.04 * u.font_size, u.box.y + low * u.font_size, u.box.x + 0.46 * u.font_size,
                    u.box.y + (0.52 if c.islower() else 0.7) * u.font_size))
    return out


def test_two_line_header_uses_ruled_band_at_readable_floor():
    stage, para, page, scale, laid = _run('Research field')
    floor = stage._readable_scale_floor(para)
    assert laid, '两条真实横线之间有空白，完整译文在下限可排，却被拒绝'
    assert scale >= floor
    assert ''.join(u.try_get_unicode() for u in laid).replace(' ', '') == 'Researchfield'
    lines = sorted({round(u.box.y, 3) for u in laid})
    assert len(lines) == 2
    for x0, y0, x1, y1 in _ink(laid):
        assert BOTTOM + 1 - 0.01 <= y0 < y1 <= TOP - 1 + 0.01, '字形墨迹越过表格横线'
        assert para.box.x - 0.01 <= x0 < x1 <= NEXT_X, '字形进入下一列'
    assert para.box.y2 <= TOP - 1 + 1e-6 and para.box.y >= BOTTOM + 1 - 1e-6


def test_short_header_keeps_existing_path():
    stage, para, page, scale, laid = _run('Mean')
    assert laid and scale >= stage._readable_scale_floor(para)
    assert para.box.y2 == pytest.approx(205.0), '短表头不应进入行带扩框'


@pytest.mark.parametrize('where', ['above', 'below'])
def test_occupied_band_is_rejected(where):
    box = il.Box(60.0, 205.2, 95.0, 207.0) if where == 'above' else il.Box(60.0, 191.5, 95.0, 194.5)
    other = il.PdfParagraph(box=box, unicode='X', layout_label='plain text', first_line_indent=False)
    _, _, _, _, laid = _run('Research field', extra_paras=[other])
    assert not laid, '行带内有相邻文字时不得借用'


def test_vector_inside_band_is_rejected():
    tick = il.PdfCurve(box=il.Box(70.0, 205.5, 72.0, 206.5))
    _, _, _, _, laid = _run('Research field', extra_curves=[tick])
    assert not laid, '行带内有矢量图形时不得借用'


def test_vertical_rule_crossing_band_is_rejected():
    # 只在源字框上方的竖线（与源框无纵向重叠，不影响既有向右扩框），但穿过行带。
    rule = il.PdfCurve(box=il.Box(75.0, 205.5, 75.0, TOP))
    _, _, _, _, laid = _run('Research field', extra_curves=[rule])
    assert not laid


def test_missing_rule_is_unknown_and_rejected():
    para, page, style = _material(rules=False)
    assert _stage()._latin_ruled_row_band_box(para.box, para.box, page, para, _units('Research field', style)) is None
    # 只有下横线、上方没有横线证据：向下仍被下横线挡住，上方未知，整体保守拒绝。
    bottom_only = il.PdfCurve(box=il.Box(40.0, BOTTOM, 300.0, BOTTOM))
    _, _, _, _, laid = _run('Research field', rules=False, extra_curves=[bottom_only])
    assert not laid, '没有真实横线证据（未知）时不得借用上方空白'


def test_rule_not_spanning_box_is_rejected():
    _, _, _, _, laid = _run('Research field', rule_x=(70.0, 300.0))
    assert not laid


def test_far_rule_is_not_a_row_band():
    _, _, _, _, laid = _run('Research field', top=260.0)
    assert not laid, '横线远超一行高度时不是本行行带'


@pytest.mark.parametrize('kind', ['form', 'figure', 'figure_region', 'label'])
def test_in_figure_text_is_rejected(kind):
    cover = il.Box(30.0, 150.0, 350.0, 250.0)
    kw = {'form': {'forms': [il.PdfForm(box=cover)]},
          'figure': {'figures': [il.PdfFigure(box=cover)]},
          'figure_region': {'layouts': [il.PageLayout(box=cover, class_name='figure', id=1, conf=1.0)]},
          'label': {'label': 'chart_label'}}[kind]
    _, _, _, _, laid = _run('Research field', **kw)
    assert not laid, '图内文字不借用行带'


def test_unrelated_layout_region_in_band_is_rejected():
    region = il.PageLayout(box=il.Box(60.0, 205.5, 95.0, 207.0), class_name='plain text', id=1, conf=1.0)
    _, _, _, _, laid = _run('Research field', layouts=[region])
    assert not laid


def test_table_region_containing_header_is_allowed():
    region = il.PageLayout(box=il.Box(30.0, 120.0, 350.0, 210.0), class_name='table', id=1, conf=1.0)
    _, _, _, _, laid = _run('Research field', layouts=[region])
    assert laid


def test_descender_ink_crossing_rule_is_rejected():
    _, _, _, _, laid = _run('Research fielQ')
    assert not laid, '字形墨迹越出行带（越过下横线）必须拒绝'


def test_unknown_glyph_outline_is_rejected():
    stage = _stage()
    helv = pymupdf.Font('helv')
    style = il.PdfStyle(font_id='helv', font_size=9.0, graphic_state=il.GraphicState())
    units = [TypesettingUnit(unicode=c, font=helv, font_size=9.0, style=style, xobj_id=0) for c in 'Ab']
    laid, fit = stage._layout_typesetting_units(units, il.Box(0, 0, 100, 50), 1.0, 1.3, il.PdfParagraph(box=il.Box(0, 0, 100, 50), first_line_indent=False))
    assert fit and not stage._ink_inside_box(laid, il.Box(0, 0, 100, 50)), '拿不到字形轮廓时是未知，不能当作墨迹在带内'


def test_cjk_target_never_uses_band():
    para, page, style = _material()
    assert _stage(cjk=True)._latin_ruled_row_band_box(para.box, para.box, page, para, _units('Research field', style)) is None
