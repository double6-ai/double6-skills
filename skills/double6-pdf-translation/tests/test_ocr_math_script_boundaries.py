"""PR #20 review 1：扫描页上下标 / 叠排分式在覆盖原图之前按图像几何拒绝。

- 拒绝复用稳定错误码 ocr_formula_unsupported，details.evidence='image_geometry' 标明证据来自图像几何（不是 OCR 文字）。
- 真实 tesseract（不在时 skip，绝不 mock）：生成 300 dpi 栅格页 → 完整 ocr_route.py（5 GiB / 120 s，bounded_execution）；
  上标 x² / 10⁻³ / 脚注号 / 上标序数词、下标 H₂O / x_i、叠排分式 a/b、中文行 m² / H₂O 必须拒绝；
  普通段落、标点密集段落、行内 a/b 与 M/N、非上标序数词、中文普通段落必须原样重建。
- 纯函数：标点解释区（逗号夹在两个字母数字之间不算）。"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_math_pages as pages  # noqa: E402
import ocr_route  # noqa: E402
from test_ocr_route import needs_engine  # noqa: E402


def test_lowered_marks_only_explain_commas_not_between_alphanumerics():
    assert ocr_route._mark_zone('H,O', 'lowered') == ''
    assert ocr_route._mark_zone('a,b', 'lowered') == ''
    assert ocr_route._mark_zone('here,', 'lowered') == ','
    assert ocr_route._mark_zone('communication,(1947)', 'lowered') == ','
    assert ocr_route._mark_zone("don't", 'raised') == "don't"


def test_math_script_reuses_the_stable_formula_code():
    assert 'ocr_formula_unsupported' in ocr_route.CODES and 'ocr_math_script_unsupported' not in ocr_route.CODES


@needs_engine
@pytest.mark.parametrize('case', pages.CASES)
def test_real_engine_script_and_fraction_boundaries(case, tmp_path):
    row = pages.run_case(case, tmp_path)
    status, code = pages.EXPECTED[case]
    assert row['job_status'] == 'succeeded' and not row['actual_alive'], row
    assert row['ocr_status'] == status, (case, row['error_code'], row['text'])
    if status == 'blocked':
        assert row['error_code'] == 'ocr_formula_unsupported', (case, row['error_code'], row['findings'])
        evidence = {f['details'].get('evidence', 'text') for f in row['findings'] if f['code'] == 'ocr_formula_unsupported'}
        assert (pages.GEOM if code == pages.GEOM else 'text') in evidence, (case, row['findings'])
    if status == 'ok':
        assert row.get('reconstructed_text'), case
    else:
        assert not row.get('reconstructed_text'), case   # 拒绝 = 不产出覆盖了原图的重建页
