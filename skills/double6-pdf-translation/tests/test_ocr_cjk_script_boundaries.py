"""PR #20 review 2：汉字旁的数学上下标在覆盖原图之前按图像几何拒绝（不按“最近 OCR 词是汉字”跳过）。

- 真实 tesseract（不在时 skip，绝不 mock）：生成 300 dpi 栅格页 → 完整 ocr_route.py（5 GiB / 120 s，bounded_execution）。
  汉字 + 上标数字/字母、汉字 + 下标数字/字母、与汉字分离/像素粘连的上下标、汉字后的上标脚注号、带圈序号①、
  拉丁行粘连的 10³ / H₂O 必须拒绝（ocr_formula_unsupported，details.evidence='image_geometry'，带可疑框）；
  中文标点（，。、；：“”‘’（）《》，全/半角混排，行内数字与拉丁字母）、常用字段落、［1］式序号必须原样重建。
- 纯函数：汉字之间的全角逗号可作解释；带圈序号的圆环判定不把“每”“细”“回”当成圆圈。"""
import sys
from pathlib import Path

import numpy as np
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_math_pages as pages  # noqa: E402
import ocr_route  # noqa: E402
from test_ocr_route import needs_engine  # noqa: E402


def test_fullwidth_comma_between_han_explains_a_lowered_mark():
    assert ocr_route._mark_zone('文献，此处', 'lowered') == '，'
    assert ocr_route._mark_zone('H,O', 'lowered') == ''


def _ring(size=46, thick=3):
    yy, xx = np.mgrid[:size, :size]
    r = np.hypot(xx - (size - 1) / 2, yy - (size - 1) / 2)
    return ((r <= size / 2) & (r >= size / 2 - thick)).astype(np.uint8)


def test_enclosed_numeral_needs_a_round_ring_with_a_glyph_inside():
    ink = np.zeros((60, 60), np.uint8)
    ink[7:53, 7:53] = _ring()
    ink[18:43, 26:35] = 1                                   # 圈内的“1”
    comps = ocr_route._components(ink)
    assert [f['kind'] for f in ocr_route._enclosed_numerals(comps, ink, (0, 0), 50.0)] == ['enclosed']
    box = np.zeros((60, 60), np.uint8)                       # 方框（口/回）：四角有墨
    box[7:53, 7:53] = 1
    box[10:50, 10:50] = 0
    box[18:43, 26:35] = 1
    assert ocr_route._enclosed_numerals(ocr_route._components(box), box, (0, 0), 50.0) == []
    empty = np.zeros((60, 60), np.uint8)                     # 〇：圆环里没有字形
    empty[7:53, 7:53] = _ring()
    assert ocr_route._enclosed_numerals(ocr_route._components(empty), empty, (0, 0), 50.0) == []


@needs_engine
@pytest.mark.parametrize('case', pages.CASES_REVIEW2)
def test_real_engine_cjk_adjacent_script_boundaries(case, tmp_path):
    row = pages.run_case(case, tmp_path)
    status, code = pages.EXPECTED_REVIEW2[case]
    assert row['job_status'] == 'succeeded' and not row['actual_alive'], row
    assert row['ocr_status'] == status, (case, row['error_code'], row['text'])
    if status == 'blocked':
        assert row['error_code'] == 'ocr_formula_unsupported', (case, row['error_code'], row['findings'])
        geometry = [f for f in row['findings'] if f['code'] == 'ocr_formula_unsupported'
                    and f['details'].get('evidence') == pages.GEOM]
        assert geometry and geometry[0]['details']['samples'][0]['suspects'][0]['box_px'], (case, row['findings'])
        assert not row.get('reconstructed_text'), case   # 拒绝 = 不产出覆盖了原图的重建页
    else:
        assert row.get('reconstructed_text'), case
