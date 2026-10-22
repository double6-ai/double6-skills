"""PR #19 评审第 3 轮反例（移植自评审的 test_wrapped_form.py）：整页 Form 外壳不得隐藏内层行内 Form 变量。

真实 PyMuPDF 原生文字层 PDF，直接调用 inspect_pdf 与 check_render_residue，无模型调用。
"""
import hashlib
import json
import sys
from pathlib import Path

import fitz

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review2_sparse_math as sparse  # noqa: E402


def wrap(src_path, dst_path):
    with fitz.open(src_path) as src:
        d = fitz.open()
        p = d.new_page(width=src[0].rect.width, height=src[0].rect.height)
        p.show_pdf_page(p.rect, src, 0)
        d.save(dst_path)
        d.close()


def english_target(path):
    d = fitz.open()
    p = d.new_page()
    sparse.write_english(p)
    d.save(path)
    d.close()


def test_wrapping_full_page_must_not_hide_nested_inline_form_variable(tmp_path):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    plain, wrapped, target = tmp_path / 'plain-source.pdf', tmp_path / 'wrapped-source.pdf', tmp_path / 'missing-variable-target.pdf'
    sparse.write_source(1, 'xobject', plain)
    wrap(plain, wrapped)
    with fitz.open(plain) as a, fitz.open(wrapped) as b:
        pa = a[0].get_pixmap(matrix=fitz.Matrix(1, 1))
        pb = b[0].get_pixmap(matrix=fitz.Matrix(1, 1))
        assert (pa.width, pa.height, pa.samples) == (pb.width, pb.height, pb.samples)
        pixel_sha = hashlib.sha256(pa.samples).hexdigest()
    english_target(target)
    pp = inspect_pdf(plain, target_language='en', require_digital=True)
    pw = inspect_pdf(wrapped, target_language='en', require_digital=True)
    quality = check_render_residue(wrapped, target, target_language='en')
    (tmp_path / 'WRAPPED_FORM.json').write_text(json.dumps({'source_pixel_sha256': pixel_sha, 'pixel_identical': True,
                                                           'plain_preflight': pp, 'wrapped_preflight': pw, 'quality': quality},
                                                          ensure_ascii=False, indent=2, default=str))
    assert pp['status'] == 'blocked'
    assert pw['status'] == 'blocked' or quality['quality_fail'], 'Lossless full-page Form wrapper hides nested variable from both gates'
