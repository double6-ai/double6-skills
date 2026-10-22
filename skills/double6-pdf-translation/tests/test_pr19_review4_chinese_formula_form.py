"""PR #19 评审第 4 轮反例（移植自评审的 test_chinese_formula_form.py）：
行内公式 Form 带中文下标/短标签（如 'M最大'）时，不能因 Form 内同行 >=2 个汉字就当作正文载体而漏掉变量。

真实 PyMuPDF 原生文字层 PDF，直接调用 inspect_pdf 与 check_render_residue，无模型调用。
"""
import json
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review_boundaries as b  # noqa: E402

GAP = 72 + 10.5 * len(b.ZH_LINE_A) + 4


def wrap_page(d):
    """把 d 的第 1 页按原尺寸再包进一层 Form（show_pdf_page），返回新文档。"""
    out = fitz.open()
    op = out.new_page(width=d[0].rect.width, height=d[0].rect.height)
    op.show_pdf_page(op.rect, d, 0)
    return out


def english_target_without_variable(path):
    out = fitz.open()
    op = out.new_page()
    op.insert_text((72, 100), 'Consider an array of antennas arranged along the axis.', fontname='helv', fontsize=11)
    out.save(path)
    out.close()


@pytest.mark.parametrize('wrapped', [False, True])
def test_inline_formula_with_chinese_subscript_cannot_hide_lost_variable(tmp_path, wrapped):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    src, target = tmp_path / f'source-{wrapped}.pdf', tmp_path / f'missing-variable-{wrapped}.pdf'
    d = fitz.open()
    p = b._inline_page(d)
    formula = fitz.open()
    fp = formula.new_page(width=40, height=16)
    fp.insert_text((2, 12), 'M', fontname='tiro', fontsize=11)
    fp.insert_text((12, 12), '最大', fontname='china-s', fontsize=7)
    p.show_pdf_page(fitz.Rect(GAP, 108, GAP + 30, 123), formula, 0)
    if wrapped:
        out = wrap_page(d)
        out.save(src)
        out.close()
    else:
        d.save(src)
    d.close()
    formula.close()
    english_target_without_variable(target)
    pre = inspect_pdf(src, target_language='en', require_digital=True)
    quality = check_render_residue(src, target, target_language='en')
    (tmp_path / f'CHINESE_FORMULA_{wrapped}.json').write_text(
        json.dumps({'preflight': pre, 'quality': quality}, ensure_ascii=False, indent=2, default=str))
    assert pre['status'] == 'blocked' or quality['quality_fail'], \
        'Two Chinese subscript characters classify an actual formula Form as body and erase variable evidence'
