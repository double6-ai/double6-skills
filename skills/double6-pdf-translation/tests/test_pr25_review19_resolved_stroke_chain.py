"""评审19 窄项：已解析描边信息链（解释器 ExtGState /LW、q/Q、Form 资源作用域 → IL → 行带）。

用实际 PDFPageInterpreterEx + TranslateConverter + ILCreater.on_lt_curve 解析本地生成的小 PDF
（pymupdf 写入原始内容流与资源，合成，不读取任何文档、文字或坐标常量），再把 frontend 产出的
IL 曲线交给行带扩框。未知/非法/矛盾一律不走行带。
"""
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pr25_review17_table_header_band as band  # noqa: E402
from test_pr25_review17_table_header_band import BOTTOM, TOP, il  # noqa: E402

from babeldoc.format.pdf.converter import TranslateConverter  # noqa: E402
from babeldoc.format.pdf.document_il.frontend.il_creater import ILCreater  # noqa: E402
from babeldoc.format.pdf.pdfinterp import PDFPageInterpreterEx  # noqa: E402
from babeldoc.pdfminer.pdfdocument import PDFDocument  # noqa: E402
from babeldoc.pdfminer.pdfinterp import PDFResourceManager  # noqa: E402
from babeldoc.pdfminer.pdfpage import PDFPage  # noqa: E402
from babeldoc.pdfminer.pdfparser import PDFParser  # noqa: E402


def _pdf(pages, resources, forms=()):
    """pages: 每页内容流；resources: 页面 Resources 字典文本，{GW}/{F0}... 替换为间接对象号。"""
    doc = pymupdf.open()
    refs = {}
    wide = doc.get_new_xref()
    doc.update_object(wide, '<</Type/ExtGState/LW 4>>')
    refs['GW'] = f'{wide} 0 R'
    for i, (form_resources, content) in enumerate(forms):
        x = doc.get_new_xref()
        doc.update_object(x, f'<</Type/XObject/Subtype/Form/BBox[0 0 400 400]{form_resources}>>')
        doc.update_stream(x, content.encode())
        refs[f'F{i}'] = f'{x} 0 R'
    for content in pages:
        page = doc.new_page(width=400, height=400)
        c = doc.get_new_xref()
        doc.update_object(c, '<<>>')
        doc.update_stream(c, content.encode())
        doc.xref_set_key(page.xref, 'Contents', f'{c} 0 R')
        doc.xref_set_key(page.xref, 'Resources', resources.format(**refs))
    return doc.tobytes()


def _frontend_curves(data):
    """实际 frontend：PDFPageInterpreterEx + TranslateConverter + ILCreater（不加载模型/分词器）。"""
    ilc = ILCreater.__new__(ILCreater)
    for name, value in dict(progress=SimpleNamespace(advance=lambda *_: None), current_page=None, mupdf=None, model=None,
                            docs=il.Document(page=[]), stroking_color_space_name=None, non_stroking_color_space_name=None,
                            passthrough_per_char_instruction=[], translation_config=SimpleNamespace(enable_graphic_element_process=True),
                            passthrough_per_char_instruction_stack=[], xobj_id=0, xobj_inc=0, xobj_map={}, xobj_stack=[],
                            current_page_font_name_id_map={}, current_page_font_char_bounding_box_map={}, current_available_fonts={},
                            mupdf_font_map={}, graphic_state_pool={}, enable_graphic_element_process=True, render_order=0,
                            current_clip_paths=[], clip_paths_stack=[], _page_valid_chars_buffer=None).items():
        setattr(ilc, name, value)
    rsrcmgr = PDFResourceManager()
    device = TranslateConverter(rsrcmgr, il_creater=ilc)
    interpreter = PDFPageInterpreterEx(rsrcmgr, device, {}, ilc)
    for pageno, page in enumerate(PDFPage.create_pages(PDFDocument(PDFParser(io.BytesIO(data))))):
        page.pageno = pageno
        interpreter.process_page(page)
    return [sorted(p.pdf_curve, key=lambda c: -c.box.y) for p in ilc.docs.page]


RES = '<</ExtGState<</GA<</Type/ExtGState/CA 1/ca 1>>/GW {GW}/GBad<</LW/Foo>>/GNeg<</LW -1>>>>/XObject<</Fm {F0}/Fp {F1}>>>>'
FORMS = [('/Resources<</ExtGState<</GL<</LW 3>>>>>>',
          '50 360 m 300 360 l S /GL gs 50 350 m 300 350 l S /GW gs 50 340 m 300 340 l S 0.7 w 50 330 m 300 330 l S'),
         ('', '/GW gs 50 320 m 300 320 l S')]


def _state(c):
    return (c.line_width, c.line_width_source)


def test_interpreter_resolves_extgstate_lw_with_q_Q_and_form_scope():
    content = ('0.48 w /GA gs 50 390 m 300 390 l S '
               'q /GW gs 50 380 m 300 380 l S Q 50 370 m 300 370 l S '
               'q /Fm Do Q q /Fp Do Q '
               '/GMissing gs 50 300 m 300 300 l S /GBad gs 50 290 m 300 290 l S '
               '/GNeg gs 50 280 m 300 280 l S 0.3 w 50 270 m 300 270 l S '
               '0.3 w /GW gs 0.25 w 50 260 m 300 260 l S')
    (curves,) = _frontend_curves(_pdf([content], RES, FORMS))
    got = [(round(c.box.y), _state(c)) for c in curves]
    assert got == [
        (390, (0.48, 'w')),                       # 无 /LW 的 ExtGState 不改线宽（真实文档形态）
        (380, (4.0, 'ExtGState')),                # 明确 /LW（间接对象）生效
        (370, (0.48, 'w')),                       # Q 恢复 q 之前的线宽与来源
        (360, (None, 'unset')),                   # Form 内未设线宽：不继承为可靠值
        (350, (3.0, 'ExtGState')),                # Form 自身 Resources 中的 /LW
        (340, (None, 'unknown:extgstate_unresolved')),  # Form 有自己的 Resources，不再看页面资源
        (330, (0.7, 'w')),
        (320, (4.0, 'ExtGState')),                # 无 Resources 的 Form 使用页面资源
        (300, (None, 'unknown:extgstate_unresolved')),
        (290, (None, 'unknown:invalid_extgstate_lw')),
        (280, (None, 'unknown:invalid_extgstate_lw')),
        (270, (0.3, 'w')),                        # 之后显式 w 重新可靠
        (260, (0.25, 'w')),                       # gs 之后再 w 覆盖
    ]
    # gs 仍保留在 passthrough 中（未删除）。
    assert '/GA gs' in curves[0].graphic_state.passthrough_per_char_instruction


def test_page_default_width_is_not_trusted():
    (curves,) = _frontend_curves(_pdf(['50 390 m 300 390 l S'], RES, FORMS))
    assert _state(curves[0]) == (None, 'unset')


def _rules_page(prefix):
    return f'{prefix} 40 {TOP} m 300 {TOP} l S 40 {BOTTOM} m 300 {BOTTOM} l S'


def _band_for(curves):
    para, page, style = band._material(rules=False, extra_curves=curves)
    stage = band._stage()
    units = band._units('Research field', style)
    box = stage._latin_ruled_row_band_box(para.box, para.box, page, para, units)
    para, page, style = band._material(rules=False, extra_curves=curves)
    scale, laid = band._stage()._find_optimal_scale_and_layout(para, page, band._units('Research field', style), apply_layout=True)
    return box, laid


@pytest.mark.parametrize('prefix,width,expect_band', [
    ('0.48 w /GA gs', 0.48, True),          # 真实形态：w 后接无 /LW 的 gs => 已解析 0.48，恢复行带
    ('0.48 w /GW gs', 4.0, False),          # 明确 /LW=4 => 粗线，拒绝
    ('0.48 w /GMissing gs', None, False),   # 解析不到 => 未知，拒绝
    ('0.48 w /GBad gs', None, False),       # 非法 /LW => 未知，拒绝
    ('', None, False),                      # 从未设置 => 未知，拒绝
])
def test_frontend_resolved_width_drives_ruled_band(prefix, width, expect_band):
    (curves,) = _frontend_curves(_pdf([_rules_page(prefix)], RES, FORMS))
    assert [c.line_width for c in curves] == [width, width]
    box, laid = _band_for(curves)
    assert (box is not None) is expect_band
    if expect_band:
        assert laid
    w = width if width is not None else 4.0
    for x0, y0, x1, y1 in band._ink(laid or []):
        for y in (TOP, BOTTOM):
            assert not (y0 < y + w / 2 and y1 > y - w / 2), '已接受字形墨迹进入实际描边'


def test_resolved_width_contradicting_passthrough_is_rejected():
    (curves,) = _frontend_curves(_pdf([_rules_page('0.48 w /GA gs')], RES, FORMS))
    for c in curves:
        c.graphic_state = il.GraphicState(passthrough_per_char_instruction='0.25 w 0 G')
    assert _band_for(curves)[0] is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0.0, -1.0, True, 'x'])
def test_invalid_resolved_width_is_rejected(value):
    (curves,) = _frontend_curves(_pdf([_rules_page('0.48 w /GA gs')], RES, FORMS))
    for c in curves:
        c.line_width = value
    assert _band_for(curves)[0] is None


@pytest.mark.parametrize('source', ['unset', 'unknown:extgstate_unresolved', 'unknown:invalid_w', 'other'])
def test_unreliable_source_is_rejected_even_with_width(source):
    (curves,) = _frontend_curves(_pdf([_rules_page('0.48 w /GA gs')], RES, FORMS))
    for c in curves:
        c.line_width_source = source
    assert _band_for(curves)[0] is None


def test_unknown_curve_elsewhere_from_frontend_still_blocks_band():
    content = _rules_page('0.48 w /GA gs') + ' /GMissing gs 320 50 m 380 50 l S'
    (curves,) = _frontend_curves(_pdf([content], RES, FORMS))
    assert {c.line_width_source for c in curves} == {'w', 'unknown:extgstate_unresolved'}
    assert _band_for(curves)[0] is None


def test_invalid_w_operand_marks_unknown():
    (curves,) = _frontend_curves(_pdf(['0.48 w /Foo w 50 390 m 300 390 l S'], RES, FORMS))
    assert _state(curves[0]) == (None, 'unknown:invalid_w')
