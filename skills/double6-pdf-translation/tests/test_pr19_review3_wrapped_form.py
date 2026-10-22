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


# ---------- 评审要求的变体与正例 ----------

def _inspect(path):
    from pdf_input_preflight import inspect_pdf
    report = inspect_pdf(path, target_language='en', require_digital=True)
    return report, report['inline_object_math'][0]


def _gate(source, tmp_path):
    from render_residue_check import check_render_residue
    target = tmp_path / 'target.pdf'
    english_target(target)
    return check_render_residue(source, target, target_language='en')


def test_pure_body_full_page_form_is_not_blocked(tmp_path):
    import fitz as _f
    plain, wrapped = tmp_path / 'plain.pdf', tmp_path / 'wrapped.pdf'
    d = _f.open()
    sparse.b._inline_page(d)
    d.save(plain)
    wrap(plain, wrapped)
    report, page = _inspect(wrapped)
    assert report['status'] != 'blocked' and page['page_in_form'] and page['body_forms'] >= 1
    assert page['xobject_text_glyphs'] == 0 and page['vector_glyphs'] == 0 and page['cjk_rows'] > 0
    gate = _gate(wrapped, tmp_path)
    assert gate['pages'][0]['inline_object_damage']['located'] == 0 and gate['inline_object_damage_pages'] == []


def _body_block(path, with_variable):
    """一个中文正文块（宽 470、高 40），行内留空隙；with_variable 时空隙里嵌一个 Form XObject 变量 M。

    PyMuPDF 的 show_pdf_page 会生成“外层容器 Form + 页面 Form”两层，所以正文载体 Form 数 >= 1。
    """
    d = fitz.open()
    p = d.new_page(width=470, height=40)
    p.insert_text((4, 24), sparse.b.ZH_LINE_A, fontname='china-s', fontsize=10.5)
    gap = 4 + 10.5 * len(sparse.b.ZH_LINE_A) + 4
    p.insert_text((gap + 34, 24), '个单极化全向天线组成的阵列。', fontname='china-s', fontsize=10.5)
    if with_variable:
        f = fitz.open()
        fp = f.new_page(width=40, height=16)
        fp.insert_text((2, 12), 'M', fontname='tiro', fontsize=11)
        p.show_pdf_page(fitz.Rect(gap, 12, gap + 30, 27), f, 0)
    d.save(path)


def _mixed_page(tmp_path, with_variable):
    block = tmp_path / f'block-{with_variable}.pdf'
    _body_block(block, with_variable)
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(72, 80, 520, 300), sparse.b.ZH_FILL, fontname='china-s', fontsize=10.5)  # 页面级正文
    page.show_pdf_page(fitz.Rect(72, 400, 542, 440), fitz.open(block), 0)  # Form 中的正文块
    path = tmp_path / f'mixed-{with_variable}.pdf'
    d.save(path)
    return path


def test_mixed_page_and_form_body_with_and_without_nested_variable(tmp_path):
    clean = _mixed_page(tmp_path, False)
    report, page = _inspect(clean)
    assert report['status'] != 'blocked' and page['body_forms'] >= 1 and page['inline_forms'] == 0 and page['xobject_text_glyphs'] == 0
    assert _gate(clean, tmp_path)['inline_object_damage_pages'] == []
    nested = _mixed_page(tmp_path, True)
    report, page = _inspect(nested)
    assert report['error_code'] == 'zh2en_inline_object_math_unsupported'
    assert page['body_forms'] >= 1 and page['inline_forms'] >= 1 and page['xobject_text_glyphs'] == 1
    gate = _gate(nested, tmp_path)
    assert gate['pages'][0]['inline_object_damage']['lost'] == 1 and gate['quality_fail']


def test_doubly_wrapped_page_keeps_nested_variable_and_vector_glyph(tmp_path):
    for kind, key in (('xobject', 'xobject_text_glyphs'), ('vector', 'vector_glyphs')):
        plain, once, twice = (tmp_path / f'{kind}-{n}.pdf' for n in ('plain', 'once', 'twice'))
        sparse.write_source(1, kind, plain)
        wrap(plain, once)
        wrap(once, twice)
        for path in (once, twice):
            report, page = _inspect(path)
            assert report['error_code'] == 'zh2en_inline_object_math_unsupported', (kind, path.name)
            assert page[key] == 1 and page['page_in_form'] and page['body_forms'] >= 1
            gate = _gate(path, tmp_path)
            damage = gate['pages'][0]['inline_object_damage']
            assert damage['located'] == 1 and damage['lost'] == 1 and gate['severity'] == 'high' and gate['quality_fail']


def test_wrapped_figure_outside_lines_and_text_formula_still_pass(tmp_path):
    """整页外壳里的行外图形 XObject 与文字层公式：不拦（正例在外壳内同样成立）。"""
    d = fitz.open()
    page = sparse.b._inline_page(d, figure_xobject=True)
    x = 72 + 10.5 * len(sparse.b.ZH_LINE_A) + 4
    page.insert_text((x + 2, 120), 'M×N', fontname='tiro', fontsize=11)
    plain, wrapped = tmp_path / 'plain.pdf', tmp_path / 'wrapped.pdf'
    d.save(plain)
    wrap(plain, wrapped)
    for path in (plain, wrapped):
        report, page = _inspect(path)
        assert report['status'] != 'blocked', (path.name, report['findings'])
        assert page['xobject_text_glyphs'] == 0 and page['vector_glyphs'] == 0
