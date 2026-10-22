"""PR #19 评审第 5 轮反例：带中文的公式 Form 不能因高度、宽度、间隙等尺寸原因被当作正文而漏掉变量证据。

第 1 项移植自评审的 test_tall_formula_form.py（竖式分数 M/总数）；其余是上一轮自报局限的对应反例：
超宽行内公式、与宿主文字间隙 > 1.5 字高、带上下限的求和、公式字形与正文画在同一个 Form 内容流里。
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
ENGLISH = 'Consider an array of antennas arranged along the axis.'


def wrap_page(d):
    """把 d 的第 1 页按原尺寸再包进一层 Form（show_pdf_page），返回新文档。"""
    out = fitz.open()
    op = out.new_page(width=d[0].rect.width, height=d[0].rect.height)
    op.show_pdf_page(op.rect, d, 0)
    return out


def save_variants(d, tmp_path, name):
    """原页与整页包装两个版本。"""
    plain, wrapped = tmp_path / f'{name}-plain.pdf', tmp_path / f'{name}-wrapped.pdf'
    d.save(plain)
    w = wrap_page(d)
    w.save(wrapped)
    w.close()
    return plain, wrapped


def english_target(path):
    out = fitz.open()
    op = out.new_page()
    op.insert_text((72, 100), ENGLISH, fontname='helv', fontsize=11)
    out.save(path)
    out.close()


def both_gates(src, tmp_path):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    target = tmp_path / f'target-{src.stem}.pdf'
    english_target(target)
    pre = inspect_pdf(src, target_language='en', require_digital=True)
    quality = check_render_residue(src, target, target_language='en')
    (tmp_path / f'{src.stem}.json').write_text(json.dumps({'preflight': pre, 'quality': quality},
                                                          ensure_ascii=False, indent=2, default=str))
    return pre, quality


def host_line(page, left, right, gap_left, width, gap_right, y=120, size=10.5):
    """一行中文：左段 + 空位（放公式）+ 右段；返回公式空位的 x 起点。"""
    page.insert_text((72, y), left, fontname='china-s', fontsize=size)
    x = 72 + size * len(left) + gap_left
    page.insert_text((x + width + gap_right, y), right, fontname='china-s', fontsize=size)
    page.insert_textbox(fitz.Rect(72, 150, 520, 400), b.ZH_FILL, fontname='china-s', fontsize=size)
    return x


@pytest.mark.parametrize('wrapped', [False, True])
def test_tall_inline_fraction_with_chinese_denominator_cannot_lose_variable(tmp_path, wrapped):
    """评审反例（移植）：竖式分数 M / 总数（0.6pt 分数线，中文分母）。"""
    d = fitz.open()
    p = b._inline_page(d)
    formula = fitz.open()
    fp = formula.new_page(width=36, height=36)
    fp.insert_text((2, 14), 'M', fontname='tiro', fontsize=11)
    fp.draw_line((1, 19), (21, 19), color=(0, 0, 0), width=0.6)
    fp.insert_text((2, 31), '总数', fontname='china-s', fontsize=7)
    p.show_pdf_page(fitz.Rect(GAP, 103, GAP + 36, 139), formula, 0)
    plain, wrapped_path = save_variants(d, tmp_path, 'tall')
    src = wrapped_path if wrapped else plain
    pre, quality = both_gates(src, tmp_path)
    assert pre['status'] == 'blocked' or quality['quality_fail'], 'Tall inline fraction loses M while preflight and output gate both pass'


def _formula(width, height, parts, rule=None):
    f = fitz.open()
    fp = f.new_page(width=width, height=height)
    for (x, y), text, font, size in parts:
        fp.insert_text((x, y), text, fontname=font, fontsize=size)
    if rule:
        fp.draw_line(rule[0], rule[1], color=(0, 0, 0), width=0.6)
    return f


def _assert_blocked_and_gate_fails(src, tmp_path, label):
    pre, quality = both_gates(src, tmp_path)
    assert pre['status'] == 'blocked' and pre['error_code'] == 'zh2en_inline_object_math_unsupported', (label, pre['findings'])
    damage = quality['pages'][0]['inline_object_damage']
    assert damage['located'] >= 1 and damage['lost'] >= 1 and quality['quality_fail'], (label, damage)


def test_wide_inline_formula_with_chinese_subscript(tmp_path):
    """超宽行内公式（约 140pt，超过上一轮 max(4 字高, 宿主行跨度一半) 的宽度上限）+ 中文下标。"""
    d = fitz.open()
    p = d.new_page()
    x = host_line(p, '考虑一个由', '组成的阵列。', 4, 150, 4)
    f = _formula(150, 16, [((2, 12), 'a1+a2+a3+a4+a5+a6+a7', 'tiro', 11), ((128, 12), '最大', 'china-s', 7)])
    p.show_pdf_page(fitz.Rect(x, 108, x + 150, 124), f, 0)
    for src in save_variants(d, tmp_path, 'wide'):
        _assert_blocked_and_gate_fails(src, tmp_path, src.name)


def test_inline_formula_with_large_gap_to_host_text(tmp_path):
    """与左右宿主汉字的间隙约 3 个字高（> 上一轮的 1.5 字高）。"""
    d = fitz.open()
    p = d.new_page()
    x = host_line(p, b.ZH_LINE_A, '个单极化全向天线组成的阵列。', 32, 30, 32)
    f = _formula(40, 16, [((2, 12), 'M', 'tiro', 11), ((12, 12), '最大', 'china-s', 7)])
    p.show_pdf_page(fitz.Rect(x, 108, x + 30, 123), f, 0)
    for src in save_variants(d, tmp_path, 'gap'):
        _assert_blocked_and_gate_fails(src, tmp_path, src.name)


def test_stacked_fraction_and_summation_with_limits(tmp_path):
    """上下堆叠：分数 x / 样本数（分数线），以及带上下限的求和 ∑（上限 n，下限 i∈集合）后接 x。"""
    d = fitz.open()
    p = d.new_page()
    x = host_line(p, b.ZH_LINE_A, '个单极化全向天线组成的阵列。', 4, 70, 4)
    frac = _formula(30, 36, [((8, 14), 'x', 'tiro', 11), ((2, 31), '样本数', 'china-s', 7)], rule=((1, 19), (27, 19)))
    p.show_pdf_page(fitz.Rect(x, 103, x + 30, 139), frac, 0)
    summ = _formula(36, 40, [((8, 8), 'n', 'tiro', 7), ((4, 26), '∑', 'china-s', 16), ((1, 37), 'i∈集合', 'china-s', 7),
                             ((24, 24), 'x', 'tiro', 11)])
    p.show_pdf_page(fitz.Rect(x + 34, 100, x + 70, 140), summ, 0)
    for src in save_variants(d, tmp_path, 'stacked'):
        _assert_blocked_and_gate_fails(src, tmp_path, src.name)


def test_formula_glyphs_in_same_form_stream_as_chinese_body(tmp_path):
    """公式字形与中文正文画在同一个 Form 内容流里（不是子 Form）：行内孤立变量 x、运算符 =、分数线。"""
    for name, extra in (('variable', 'var'), ('fraction', 'rule')):
        block = fitz.open()
        bp = block.new_page(width=450, height=60)
        bp.insert_text((2, 16), '设阵元间距为', fontname='china-s', fontsize=10.5)
        if extra == 'var':
            bp.insert_text((68, 16), 'x = 2', fontname='tiro', fontsize=11)
            bp.insert_text((98, 16), '，则远场指向性随阵元数单调增加。', fontname='china-s', fontsize=10.5)
        else:
            bp.insert_text((70, 11), 'λ', fontname='china-s', fontsize=8)
            bp.draw_line((68, 13), (80, 13), color=(0, 0, 0), width=0.5)
            bp.insert_text((70, 21), '2', fontname='tiro', fontsize=8)
            bp.insert_text((86, 16), '，则远场指向性随阵元数单调增加。', fontname='china-s', fontsize=10.5)
        bp.insert_text((2, 32), '本文给出了阵列远场指向性的数学框架并推导了解析表达式。', fontname='china-s', fontsize=10.5)
        d = fitz.open()
        page = d.new_page()
        page.insert_textbox(fitz.Rect(72, 60, 520, 130), b.ZH_FILL, fontname='china-s', fontsize=10.5)
        page.show_pdf_page(fitz.Rect(72, 150, 522, 210), block, 0)
        for src in save_variants(d, tmp_path, f'same-stream-{name}'):
            _assert_blocked_and_gate_fails(src, tmp_path, src.name)


# ---------- 正文准入：正例与“不确定即拒绝”的边界 ----------

def _inspect(path):
    from pdf_input_preflight import inspect_pdf
    report = inspect_pdf(path, target_language='en', require_digital=True)
    return report, report['inline_object_math'][0]


def _variants3(d, tmp_path, name):
    """原页、单层整页包装、双层整页包装。"""
    plain, once = save_variants(d, tmp_path, name)
    with fitz.open(once) as o:
        twice = wrap_page(o)
    path = tmp_path / f'{name}-twice.pdf'
    twice.save(path)
    twice.close()
    return [plain, once, path]


def _block(width, height, lines, size=10.5, latin=()):
    f = fitz.open()
    fp = f.new_page(width=width, height=height)
    for i, line in enumerate(lines):
        fp.insert_text((2, 2 + size * 1.4 * (i + 1)), line, fontname='china-s', fontsize=size)
    for i, x, text in latin:
        fp.insert_text((x, 2 + size * 1.4 * (i + 1)), text, fontname='tiro', fontsize=size)
    return f


def _assert_not_blocked(path, tmp_path):
    report, page = _inspect(path)
    assert report['status'] != 'blocked', (path.name, report['findings'])
    assert page['needs_review_forms'] == 0 and page['xobject_text_glyphs'] == 0, (path.name, page)
    _, quality = both_gates(path, tmp_path)
    assert quality['pages'][0]['inline_object_damage']['located'] == 0, path.name
    return page


def test_chinese_body_form_with_english_words_and_numbers_is_body(tmp_path):
    """正例：中文正文段落 Form 里有普通英文单词与数字（Transformer、MIMO、2024、5G），
    与正文同字体同字号、不是孤立单字母——正面确认为正文；原页、单层、双层包装与页面级正文混排都不拦。"""
    para = _block(450, 60, ['本文提出的 模型在 年的基准上取得最好结果，', '并在 与 场景下验证了泛化能力。'],
                  latin=[(0, 54, 'Transformer'), (0, 136, '2024'), (1, 44, 'MIMO'), (1, 80, '5G')])
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(72, 60, 520, 130), b.ZH_FILL, fontname='china-s', fontsize=10.5)  # 页面级正文
    page.show_pdf_page(fitz.Rect(72, 150, 522, 210), para, 0)
    caption = _block(300, 20, ['图 1 整体结构示意图'], size=9, latin=[(0, 30, 'Transformer')])
    page.show_pdf_page(fitz.Rect(150, 330, 450, 350), caption, 0)
    for path in _variants3(d, tmp_path, 'words'):
        info = _assert_not_blocked(path, tmp_path)
        assert info['body_forms'] >= 2, (path.name, info)


def test_two_column_figure_form_with_chinese_labels_is_not_in_body_lines(tmp_path):
    """正例：双栏页。右栏是中文正文段落 Form（含英文单词）；左栏是图 Form（坐标轴、曲线、刻度数字、
    中文轴标题、单字母轴标签 x/y、希腊字母 θ），与右栏正文同高但不在正文行里：记 standalone_mixed，不拦。"""
    fig = fitz.open()
    fp = fig.new_page(width=220, height=160)
    fp.draw_line((30, 130), (210, 130), color=(0, 0, 0), width=0.8)
    fp.draw_line((30, 130), (30, 10), color=(0, 0, 0), width=0.8)
    fp.draw_polyline([(30, 120), (80, 80), (130, 60), (200, 30)], color=(0, 0, 0), width=1)
    for i, x in enumerate((30, 90, 150, 210)):
        fp.insert_text((x - 3, 142), str(i * 10), fontname='tiro', fontsize=7)
    fp.insert_text((95, 156), '时间', fontname='china-s', fontsize=8)
    fp.insert_text((120, 156), 'x', fontname='tiro', fontsize=8)
    fp.insert_text((4, 70), '幅度', fontname='china-s', fontsize=8)
    fp.insert_text((4, 82), 'y', fontname='tiro', fontsize=8)
    fp.insert_text((140, 50), 'θ', fontname='china-s', fontsize=8)
    right = _block(240, 200, ['右栏正文介绍实验设置与评价指标，', '模型在多个数据集上训练并测试，', '结果表明方法稳定有效。'] * 3,
                   latin=[(1, 170, 'MIMO')])
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(40, 60, 280, 120), b.ZH_FILL[:60], fontname='china-s', fontsize=10.5)  # 左栏页面级正文
    page.show_pdf_page(fitz.Rect(40, 130, 260, 290), fig, 0)
    page.show_pdf_page(fitz.Rect(300, 60, 540, 260), right, 0)
    for path in _variants3(d, tmp_path, 'two-column'):
        info = _assert_not_blocked(path, tmp_path)
        assert info['standalone_mixed_forms'] >= 1 and info['body_forms'] >= 1, (path.name, info)


@pytest.mark.parametrize('case', ['caption_variable', 'note_variable'])
def test_uncertain_mixed_form_in_body_line_is_needs_review(tmp_path, case):
    """不确定即拒绝：图注 Form 里出现孤立变量 N（“N 为阵元数”），或紧邻正文行的旁注 Form 里出现孤立字母 a，
    都不能确认为正文，判 needs_review（exit 2），其字形计入成品门。第 4 轮的正例里这两处曾是 N 与 a，第 5 轮改为
    年份/编号，并在这里作为 needs_review 反例单独测试。"""
    d = fitz.open()
    page = d.new_page()
    page.insert_textbox(fitz.Rect(72, 60, 520, 130), b.ZH_FILL, fontname='china-s', fontsize=10.5)
    if case == 'caption_variable':
        page.draw_rect(fitz.Rect(150, 230, 400, 330), color=(0, 0, 0))
        f = _block(300, 20, ['图 1 均匀线阵的方向图（ 为阵元数）'], size=9, latin=[(0, 85, 'N')])
        page.show_pdf_page(fitz.Rect(150, 335, 450, 355), f, 0)
        expected = 'N'
    else:
        page.insert_text((72, 470), '旁注所在行的正文内容。', fontname='china-s', fontsize=10.5)
        f = _block(30, 34, ['注一', '见上'], size=9, latin=[(1, 20, 'a')])
        page.show_pdf_page(fitz.Rect(180, 450, 210, 484), f, 0)
        expected = 'a'
    for src in save_variants(d, tmp_path, case):
        report, info = _inspect(src)
        assert report['error_code'] == 'zh2en_inline_object_math_unsupported', src.name
        assert info['needs_review_forms'] == 1 and info['reasons'] == ['mixed_form_needs_review'], (src.name, info)
        assert [o['char'] for o in info['samples']] == [expected]
        _, quality = both_gates(src, tmp_path)
        assert quality['pages'][0]['inline_object_damage']['lost'] == 1 and quality['quality_fail'], src.name
