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


# ---------- 评审要求的变体与正例（每个都做原页、单层包装、双层包装） ----------

def _variants(d, tmp_path, name):
    """保存原页、单层整页包装、双层整页包装三个版本，返回路径列表。"""
    paths = [tmp_path / f'{name}-plain.pdf', tmp_path / f'{name}-once.pdf', tmp_path / f'{name}-twice.pdf']
    d.save(paths[0])
    once = wrap_page(d)
    once.save(paths[1])
    twice = wrap_page(once)
    twice.save(paths[2])
    once.close()
    twice.close()
    return paths


def _inspect(path):
    from pdf_input_preflight import inspect_pdf
    report = inspect_pdf(path, target_language='en', require_digital=True)
    return report, report['inline_object_math'][0]


def _gate(source, tmp_path):
    from render_residue_check import check_render_residue
    target = tmp_path / 'target-no-variable.pdf'
    english_target_without_variable(target)
    return check_render_residue(source, target, target_language='en')


def _formula_form(parts):
    """parts: [(x, text, fontname, size)]，生成 60x16pt 的公式 Form 源文档。

    PyMuPDF 的 show_pdf_page 生成“外层容器 Form + 页面 Form”两层，所以每放一次公式，hosted_cjk_forms 记 2。
    """
    f = fitz.open()
    fp = f.new_page(width=60, height=16)
    for x, text, font, size in parts:
        fp.insert_text((x, 12), text, fontname=font, fontsize=size)
    return f


def _text_block(width, height, lines, size=10.5, latin=None):
    """中文正文/图注块 Form 源文档：lines 为中文行；latin 为 [(行号, x, 文本)]，插入同行英文术语。"""
    f = fitz.open()
    fp = f.new_page(width=width, height=height)
    for i, line in enumerate(lines):
        fp.insert_text((2, 2 + size * 1.4 * (i + 1)), line, fontname='china-s', fontsize=size)
    for i, x, text in latin or []:
        fp.insert_text((x, 2 + size * 1.4 * (i + 1)), text, fontname='tiro', fontsize=size)
    return f


def test_multiple_variables_with_chinese_subscript_are_blocked_plain_and_wrapped(tmp_path):
    """多个变量 + 中文下标（'M×N' + '最大'，以及 'x' + '最优' + 'y'）：原页与包装后都拦截，成品门判丢失。"""
    cases = {
        'mxn': ([(2, 'M×N', 'tiro', 11), (26, '最大', 'china-s', 7)], 3),
        'xy': ([(2, 'x', 'tiro', 11), (8, '最优', 'china-s', 7), (24, 'y', 'tiro', 11)], 2),
    }
    for name, (parts, n_latin) in cases.items():
        d = fitz.open()
        p = b._inline_page(d)
        f = _formula_form(parts)
        p.show_pdf_page(fitz.Rect(GAP, 108, GAP + 30, 123), f, 0)
        for path in _variants(d, tmp_path, name):
            report, page = _inspect(path)
            assert report['error_code'] == 'zh2en_inline_object_math_unsupported', (name, path.name)
            assert page['xobject_text_glyphs'] == n_latin and page['needs_review_forms'] >= 1, (name, path.name, page)
            gate = _gate(path, tmp_path)
            damage = gate['pages'][0]['inline_object_damage']
            assert damage['located'] == n_latin and damage['lost'] == n_latin and gate['quality_fail'], (name, path.name)
        d.close()
        f.close()


def test_chinese_paragraph_caption_and_label_forms_are_body_plain_and_wrapped(tmp_path):
    """905dbf3 的原始输入，逐字保留（评审第 6 轮冻结正例）。原断言“整页不拦截、成品门不定位对象”被真实后端证伪，
    改为拒绝（证据：report/pr19-review6，905dbf3 与预检旁路的端到端回放成品）：
    - 图注 '图 1 均匀线阵的方向图（ 为阵元数）' 的 N 是在整行中文画完之后才另起一段画上去的（绘制顺序与视觉顺序不一致）。
      后端按内容流抽取成 '…( 为阵元数)N'，成品为 '(is the number of elements)N'：变量从括号里被挪到行尾，语义错误；
    - 旁注 '注一/见上' 的 a 同样是事后补画的另一字体单字母，成品里落在 Form 裁剪框外，只剩一个点；
    两个 Form 都被判 needs_review（整页拒绝），定位的数学字形恰为 N 与 a，成品门据此核对。
    其余 Form（正文段与右栏的 MIMO、图内标签、续表标签）仍不定位对象。
    同样的字母若与中文同属一个按视觉顺序绘制的文本流（同字体、同字号），后端成品完整，见
    test_pr19_review6_text_runs.py 的配对正例。"""
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(72, 60, 520, 130), b.ZH_FILL, fontname='china-s', fontsize=10.5)  # 页面级正文
    para = _text_block(450, 60, ['本节介绍基于 的阵列模型，并给出远场指向性', '的解析表达式与数值结果，讨论天线间距的影响。',
                                 '实验表明该方法在多种配置下都稳定。'], latin=[(0, 54, 'MIMO')])
    page.show_pdf_page(fitz.Rect(72, 150, 522, 210), para, 0)                                  # 整段正文 Form
    page.draw_rect(fitz.Rect(150, 230, 400, 330), color=(0, 0, 0))                            # 图
    caption = _text_block(300, 20, ['图 1 均匀线阵的方向图（ 为阵元数）'], size=9, latin=[(0, 85, 'N')])
    page.show_pdf_page(fitz.Rect(150, 335, 450, 355), caption, 0)                              # 图注块 Form
    label = _text_block(60, 20, ['主瓣'], size=9, latin=[(0, 22, 'θ0')])
    page.show_pdf_page(fitz.Rect(330, 240, 390, 260), label, 0)                                # 图内/行外标签 Form
    page.insert_text((72, 400), '左栏正文：阵列增益随阵元数增加。', fontname='china-s', fontsize=10.5)
    right = _text_block(230, 16, ['右栏正文： 信道容量随天线数增长。'], latin=[(0, 58, 'MIMO')])
    page.show_pdf_page(fitz.Rect(238, 388, 468, 404), right, 0)  # 与左栏同高、间隙小于 1.5 字高的右栏行 Form（按宽度判为正文）
    page.insert_text((72, 470), '旁注所在行的正文内容。', fontname='china-s', fontsize=10.5)
    note = _text_block(30, 34, ['注一', '见上'], size=9, latin=[(1, 20, 'a')])
    page.show_pdf_page(fitz.Rect(180, 450, 210, 484), note, 0)                                 # 紧邻正文行的两行旁注 Form（按行数判为正文）
    page.insert_text((72, 530), '表格续页说明。', fontname='china-s', fontsize=10.5)
    tag = _text_block(50, 16, ['续表'], size=10.5, latin=[(0, 26, 'A')])
    page.show_pdf_page(fitz.Rect(450, 518, 500, 534), tag, 0)                                  # 同一纵向带但远离正文的行外标签 Form（按紧邻判为正文）
    from pdf_input_preflight import inline_object_math
    for path in _variants(d, tmp_path, 'body-forms'):
        report, page_info = _inspect(path)
        assert report['status'] == 'blocked', (path.name, page_info)
        assert page_info['needs_review_forms'] == 2 and page_info['xobject_text_glyphs'] == 2, (path.name, page_info)
        with fitz.open(path) as src:
            located = inline_object_math(src, 0, with_objects=True)['objects']
        assert sorted(o['char'] for o in located) == ['N', 'a'], (path.name, located)
        assert page_info['body_forms'] + page_info['standalone_mixed_forms'] >= 4, (path.name, page_info)
        gate = _gate(path, tmp_path)
        assert gate['pages'][0]['inline_object_damage']['located'] == 2 and gate['quality_fail'], path.name
    d.close()


def test_formula_with_chinese_label_nested_inside_body_block_form(tmp_path):
    """正文块 Form 内嵌 'M最大' 公式 Form（再包一层整页）：外层是正文载体，内层仍是行内对象并被拦截。"""
    block = fitz.open()
    bp = block.new_page(width=470, height=40)
    bp.insert_text((4, 24), b.ZH_LINE_A, fontname='china-s', fontsize=10.5)
    gap = 4 + 10.5 * len(b.ZH_LINE_A) + 4
    bp.insert_text((gap + 34, 24), '个单极化全向天线组成的阵列。', fontname='china-s', fontsize=10.5)
    f = _formula_form([(2, 'M', 'tiro', 11), (12, '最大', 'china-s', 7)])
    bp.show_pdf_page(fitz.Rect(gap, 12, gap + 45, 27), f, 0)
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(72, 80, 520, 300), b.ZH_FILL, fontname='china-s', fontsize=10.5)
    page.show_pdf_page(fitz.Rect(72, 400, 542, 440), block, 0)
    for path in _variants(d, tmp_path, 'nested-label-formula'):
        report, page_info = _inspect(path)
        assert report['error_code'] == 'zh2en_inline_object_math_unsupported', path.name
        assert page_info['xobject_text_glyphs'] == 1 and page_info['needs_review_forms'] >= 1 and page_info['body_forms'] >= 1
        gate = _gate(path, tmp_path)
        assert gate['pages'][0]['inline_object_damage']['lost'] == 1 and gate['quality_fail'], path.name
    d.close()
