"""评审18 窄项：行带扩框（拉丁目标语言 stage 2）按横线/阻挡物的实际绘制范围判断。

零高路径框不代表零粗细：描边宽来自 graphic_state 的 w 指令并经 CTM 变换；描边宽、CTM 或
绘制标记不能确定时不走行带（未知不当安全）。几何与字体全部合成（复用评审17 合成字体夹具）。
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_pr25_review17_table_header_band as band  # noqa: E402
from test_pr25_review17_table_header_band import BOTTOM, NEXT_X, TOP, il  # noqa: E402

IDENTITY = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def _curve(x0, y0, x1, y1, gs='0.5 w 0 G', stroke=True, fill=False, ctm=IDENTITY):
    return il.PdfCurve(box=il.Box(x0, y0, x1, y1), graphic_state=il.GraphicState(passthrough_per_char_instruction=gs),
                       stroke_path=stroke, fill_background=fill, ctm=list(ctm) if ctm is not None else None)


def _rules(**kw):
    return [_curve(40.0, TOP, 300.0, TOP, **kw), _curve(40.0, BOTTOM, 300.0, BOTTOM, **kw)]


def _band(curves, extra=()):
    para, page, style = band._material(rules=False, extra_curves=[*curves, *extra])
    return band._stage()._latin_ruled_row_band_box(para.box, para.box, page, para, band._units('Research field', style))


def _layout(curves, extra=()):
    para, page, style = band._material(rules=False, extra_curves=[*curves, *extra])
    stage = band._stage()
    scale, laid = stage._find_optimal_scale_and_layout(para, page, band._units('Research field', style), apply_layout=True)
    return stage, para, scale, laid


def _collisions(laid, width, centers=(TOP, BOTTOM)):
    half = width / 2
    return [ink for ink in band._ink(laid or []) for y in centers
            if ink[1] < y + half - 0.01 and ink[3] > y - half + 0.01]


def test_real_thin_stroke_with_known_width_still_uses_band():
    # 与真实文档同形：0.48pt 描边、Y 翻转 CTM 不改变线宽。
    rules = _rules(gs='0.480000 w 2 M 2 j 0 0 0 RG', ctm=[1.0, 0.0, 0.0, -1.0, 0.0, 400.0])
    assert _band(rules) is not None
    stage, para, scale, laid = _layout(rules)
    assert laid and scale >= stage._readable_scale_floor(para)
    assert not _collisions(laid, 0.48)
    for x0, y0, x1, y1 in band._ink(laid):
        # 行带边界离路径中心 1pt，离实际描边边缘 >= 0.25pt。
        assert BOTTOM + 0.24 + 0.25 <= y0 and y1 <= TOP - 0.24 - 0.25
        assert x1 <= NEXT_X


@pytest.mark.parametrize('width', [1.6, 4.0])
def test_thick_stroke_on_zero_height_path_is_not_a_thin_rule(width):
    rules = _rules(gs=f'{width} w 0 G')
    assert _band(rules) is None
    _, _, _, laid = _layout(rules)
    assert not _collisions(laid, width)


def test_scaled_ctm_widens_stroke_beyond_thin_rule():
    # 用户空间 0.5pt，CTM 放大 4 倍 => 设备空间 2pt。
    assert _band(_rules(gs='0.5 w 0 G', ctm=[4.0, 0.0, 0.0, 4.0, 0.0, 0.0])) is None


def test_shear_ctm_uses_conservative_upper_bound():
    # 错切 [1 0 3 1] 谱范数约 3.30，0.5pt => 约 1.65pt > 1.5，按可靠上界拒绝。
    assert _band(_rules(gs='0.5 w 0 G', ctm=[1.0, 0.0, 3.0, 1.0, 0.0, 0.0])) is None


def test_rotation_ctm_keeps_known_width():
    # 90° 旋转不改变线宽：0.5pt 仍是可靠细线。
    assert _band(_rules(gs='0.5 w 0 G', ctm=[0.0, 1.0, -1.0, 0.0, 400.0, 0.0])) is not None


@pytest.mark.parametrize('gs', ['0 G', '0.48 w 0 G /GS1 gs', '0 w 0 G', 'abc w 0 G', 'nan w', 'inf w', ''])
def test_unknown_stroke_width_is_rejected(gs):
    assert _band(_rules(gs=gs)) is None


def test_width_set_after_extgstate_is_known():
    assert _band(_rules(gs='/GS1 gs 0.48 w 0 G')) is not None


@pytest.mark.parametrize('ctm', [None, [1.0, 0.0, 0.0], [1.0, 0.0, 0.0, float('nan'), 0.0, 0.0], ['x', 0, 0, 1, 0, 0]])
def test_unknown_transform_is_rejected(ctm):
    assert _band(_rules(ctm=ctm)) is None


def test_unknown_paint_flags_are_rejected():
    rules = [il.PdfCurve(box=il.Box(40.0, y, 300.0, y), graphic_state=il.GraphicState(passthrough_per_char_instruction='0.5 w'),
                         ctm=list(IDENTITY)) for y in (TOP, BOTTOM)]
    assert _band(rules) is None


def test_unknown_curve_elsewhere_on_page_is_rejected():
    far = _curve(320.0, 50.0, 380.0, 50.0, gs='0 G')
    assert _band(_rules()) is not None
    assert _band(_rules(), extra=[far]) is None


def test_thick_stroke_reaching_into_band_is_an_obstacle():
    # 路径框在行带外（207.6），0.5pt 时实际绘制也在带外；1.4pt 时下缘 206.9 进入行带。
    near_thin = _curve(70.0, 207.6, 90.0, 207.6, gs='0.5 w 0 G')
    near_thick = _curve(70.0, 207.6, 90.0, 207.6, gs='1.4 w 0 G')
    assert _band(_rules(), extra=[near_thin]) is not None
    assert _band(_rules(), extra=[near_thick]) is None


def test_filled_thin_rule_uses_its_path_box():
    rules = [_curve(40.0, TOP - 0.25, 300.0, TOP + 0.25, gs='0 g', stroke=False, fill=True),
             _curve(40.0, BOTTOM - 0.25, 300.0, BOTTOM + 0.25, gs='0 g', stroke=False, fill=True)]
    assert _band(rules) is not None
    thick = [_curve(40.0, TOP - 1.0, 300.0, TOP + 1.0, gs='0 g', stroke=False, fill=True),
             _curve(40.0, BOTTOM - 1.0, 300.0, BOTTOM + 1.0, gs='0 g', stroke=False, fill=True)]
    assert _band(thick) is None


def test_extent_helper_values():
    T = band.Typesetting
    assert T._ruled_band_stroke_width('1 w 0 G 0.25 w') == 0.25
    assert T._ruled_band_stroke_width('0.25 w /A gs') is None
    ext = T._ruled_band_curve_extent(_curve(10.0, 20.0, 30.0, 20.0, gs='0.5 w', ctm=[2.0, 0.0, 0.0, 2.0, 0.0, 0.0]))
    assert (ext.x, ext.y, ext.x2, ext.y2) == pytest.approx((9.5, 19.5, 30.5, 20.5))
    # 没有任何绘制状态的几何框（评审17 合成夹具）按路径框本身。
    legacy = il.PdfCurve(box=il.Box(1.0, 2.0, 3.0, 2.0))
    assert T._ruled_band_curve_extent(legacy) is legacy.box
    assert math.isclose(T._ruled_band_curve_extent(_curve(0, 0, 1, 0, ctm=[0.0, 1.0, -1.0, 0.0, 0.0, 0.0])).y, -0.25)
