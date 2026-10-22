"""PR #19 评审第 2 轮反例（移植自评审的 test_sparse_math.py）：中文正文行内只有 1–2 个结构对象
（填充矢量公式字形、Form XObject 变量）时，必须被中译英预检拦下，或由成品门判 fail。

真实 PyMuPDF 原生文字层 PDF，直接调用 inspect_pdf 与 check_render_residue，无模型调用。
译文页优先使用 babeldoc 实际排版用的 NotoSans-Regular.ttf（本机缓存）；不存在时（例如 CI）退回内置 Helvetica。
"""
import json
import os
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review_boundaries as b  # noqa: E402

ENGLISH = 'Consider an array of antennas arranged along the axis.'


def noto_font() -> str | None:
    for base in (os.environ.get('HOME', ''), '/home/box'):
        path = Path(base) / '.cache/babeldoc/fonts/NotoSans-Regular.ttf'
        if path.is_file():
            return str(path)
    return None


def write_source(n, kind, path):
    d = fitz.open()
    p = b._inline_page(d)
    x = 72 + 10.5 * len(b.ZH_LINE_A) + 4
    y = 120
    if kind == 'vector':
        for k in range(n):
            xx = x + 2 + 7 * k
            p.draw_polyline([(xx, y), (xx + 3, y - 8), (xx + 6, y), (xx, y)], color=None, fill=(0, 0, 0))
    else:
        f = fitz.open()
        fp = f.new_page(width=40, height=16)
        fp.insert_text((2, 12), 'MN'[:n], fontname='tiro', fontsize=11)
        p.show_pdf_page(fitz.Rect(x, y - 12, x + 30, y + 3), f, 0)
    d.save(path)
    d.close()


def write_english(page, text=ENGLISH, point=(72, 100)):
    font = noto_font()
    if font:
        page.insert_text(point, text, fontname='Noto', fontfile=font, fontsize=11)
    else:
        page.insert_text(point, text, fontname='helv', fontsize=11)


@pytest.mark.parametrize('kind', ['vector', 'xobject'])
@pytest.mark.parametrize('n', [1, 2])
def test_sparse_inline_math_cannot_escape_both_gates(kind, n, tmp_path):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    src = tmp_path / f'{kind}{n}-source.pdf'
    tgt = tmp_path / f'{kind}{n}-target.pdf'
    write_source(n, kind, src)
    d = fitz.open()
    p = d.new_page()
    write_english(p)
    if kind == 'xobject':
        p.insert_text((72, 100), 'MN'[:n], fontname='tiro', fontsize=11)
    d.save(tgt)
    d.close()
    pre = inspect_pdf(src, target_language='en', require_digital=True)
    qa = check_render_residue(src, tgt, target_language='en')
    (tmp_path / f'SPARSE_{kind}{n}.json').write_text(json.dumps({'preflight': pre, 'quality': qa}, ensure_ascii=False, indent=2, default=str))
    assert pre['status'] == 'blocked' or qa['quality_fail'], 'Sparse unsupported inline math passes preflight and rendered residue/structural gate'


@pytest.mark.parametrize('kind', ['vector', 'xobject'])
@pytest.mark.parametrize('n', [1, 2])
def test_sparse_inline_math_blocked_by_preflight_and_output_gate_independently(kind, n, tmp_path):
    """两道门各自都要拦：预检定位到 >= 1 个行内结构对象即拒绝；绕过预检时，成品中该对象丢失或压叠也判 fail。"""
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    src = tmp_path / 'src.pdf'
    write_source(n, kind, src)
    pre = inspect_pdf(src, target_language='en', require_digital=True)
    assert pre['status'] == 'blocked' and pre['error_code'] == 'zh2en_inline_object_math_unsupported'
    page = next(f for f in pre['findings'] if f['code'] == 'zh2en_inline_object_math_unsupported')['details']['pages'][0]
    assert page[{'vector': 'vector_glyphs', 'xobject': 'xobject_text_glyphs'}[kind]] == n
    tgt = tmp_path / 'tgt.pdf'
    d = fitz.open()
    p = d.new_page()
    write_english(p)
    if kind == 'xobject':
        p.insert_text((72, 100), 'MN'[:n], fontname='tiro', fontsize=11)
    d.save(tgt)
    d.close()
    qa = check_render_residue(src, tgt, target_language='en')
    damage = qa['pages'][0]['inline_object_damage']
    assert damage['located'] == n and damage['lost'] + damage['collided'] >= 1
    assert qa['inline_object_damage_pages'] == [1] and qa['severity'] == 'high' and qa['quality_fail']


def test_retained_inline_object_without_overlap_passes_output_gate(tmp_path):
    from render_residue_check import page_inline_object_damage
    src = tmp_path / 'src.pdf'
    write_source(2, 'vector', src)
    # 合法保留：对象在原位，英文不压叠
    d = fitz.open(src)
    page = d[0]
    with fitz.open(src) as s:
        clean = page_inline_object_damage(s, 0, page)
    assert clean == {'located': 2, 'lost': 0, 'collided': 0, 'samples': [], 'flagged': False}
    # 同一对象被英文压住：压叠判定
    write_english(page, point=(72 + 10.5 * len(b.ZH_LINE_A), 120))
    tgt = tmp_path / 'tgt.pdf'
    d.save(tgt)
    with fitz.open(src) as s, fitz.open(tgt) as t:
        hit = page_inline_object_damage(s, 0, t[0])
    assert hit['collided'] >= 1 and hit['flagged']


def test_preflight_positive_cases_icon_figure_and_text_formula(tmp_path):
    """不在中文行内的小图标、行外图形 XObject、页面级文字公式（变量是普通文字层）都不拦。"""
    from pdf_input_preflight import inspect_pdf
    doc = fitz.open()
    page = b._inline_page(doc, figure_xobject=True)
    page.draw_rect(fitz.Rect(530, 60, 538, 68), color=None, fill=(0.8, 0.1, 0.1))  # 页边小图标，不在任何中文行内
    page.draw_rect(fitz.Rect(60, 136, 66, 142), color=None, fill=(0, 0, 0))  # 行首左侧的项目符号
    x = 72 + 10.5 * len(b.ZH_LINE_A) + 4
    page.insert_text((x + 2, 120), 'M×N', fontname='tiro', fontsize=11)  # 文字层行内公式
    path = tmp_path / 'positive.pdf'
    doc.save(path)
    report = inspect_pdf(path, target_language='en', require_digital=True)
    assert report['status'] != 'blocked', report['findings']
    inline = report['inline_object_math'][0]
    assert inline['xobject_text_glyphs'] == 0 and inline['vector_glyphs'] == 0


def test_page_wrapped_in_form_still_locates_vector_glyphs(tmp_path):
    """整页包进 Form XObject 时，Form 内中文是正文本身：不把正文当行内对象，但行内矢量字形仍要定位并拦下。"""
    from pdf_input_preflight import inspect_pdf
    inner = tmp_path / 'inner.pdf'
    write_source(1, 'vector', inner)
    outer = fitz.open()
    page = outer.new_page()
    page.show_pdf_page(page.rect, fitz.open(inner), 0)
    path = tmp_path / 'wrapped.pdf'
    outer.save(path)
    report = inspect_pdf(path, target_language='en', require_digital=True)
    inline = report['inline_object_math'][0]
    assert inline['page_in_form'] and inline['xobject_text_glyphs'] == 0 and inline['vector_glyphs'] == 1
    assert report['error_code'] == 'zh2en_inline_object_math_unsupported'
