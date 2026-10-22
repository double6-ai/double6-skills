"""PR #19 评审第 6 轮：包装不改变判定；文字层公式由成品门核对；与中文同属一个视觉顺序文本流的字母/斜体词准入。

依据（report/pr19-review6 端到端回放证据，905dbf3 与预检旁路两条路径）：
- 页面等价 Form（整页外壳）：原页与包装后的后端请求逐字相同、成品逐像素相同 —— 包装不改变后端行为，也不得改变判定；
- 文字层 'M×N'（页面级或页面等价 Form 自身绘制）：后端把它整个丢掉（原页与包装后都丢），905dbf3 却以退出码 0 交付；
  现在两者都由成品门 text_layer_math_loss 判失败（退出码 3），预检判定也一致（都不拦）；
- 孤立字母/斜体词：与同行中文同属一个按视觉顺序绘制的文本流（绘制顺序与 x 顺序一致、与最近汉字同字号；
  单字母还须同字体）时，后端成品完整保留在原位；事后补画（乱序）的字母被挪到行尾或丢失，另一字体的单字母仍按数学变量处理。
真实 PyMuPDF 原生文字层 PDF，直接调用 inspect_pdf 与 check_render_residue，无模型调用。
"""
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review_boundaries as b  # noqa: E402

ZH = '本文给出了阵列远场指向性的数学框架，并推导了解析表达式，系统分析了各种因素对指向性的影响。' * 3


def wrap_page(d):
    out = fitz.open()
    op = out.new_page(width=d[0].rect.width, height=d[0].rect.height)
    op.show_pdf_page(op.rect, d, 0)
    return out


def variants(d, tmp_path, name):
    paths = [tmp_path / f'{name}-plain.pdf', tmp_path / f'{name}-once.pdf', tmp_path / f'{name}-twice.pdf']
    d.save(paths[0])
    once = wrap_page(d)
    once.save(paths[1])
    twice = wrap_page(once)
    twice.save(paths[2])
    once.close()
    twice.close()
    return paths


def inspect(path):
    from pdf_input_preflight import inline_object_math, inspect_pdf
    report = inspect_pdf(path, target_language='en', require_digital=True)
    with fitz.open(path) as src:
        detail = inline_object_math(src, 0, with_objects=True)
    return report, report['inline_object_math'][0], detail


def english(path, lines):
    out = fitz.open()
    op = out.new_page()
    for i, text in enumerate(lines):
        op.insert_text((72, 100 + 14 * i), text, fontname='helv', fontsize=11)
    out.save(path)
    out.close()


def gate(source, target):
    from render_residue_check import check_render_residue
    return check_render_residue(source, target, target_language='en')


def _advance(text, font, size):
    m = fitz.open()
    mp = m.new_page(width=2000, height=50)
    mp.insert_text((0, 30), text + '|', fontname=font, fontsize=size)
    bar = [c for blk in mp.get_text('rawdict')['blocks'] for ln in blk['lines'] for sp in ln['spans']
           for c in sp['chars'] if c['c'] == '|'][-1]
    m.close()
    return bar['origin'][0]


def runs_form(width, height, runs, size=10.5, order='visual', sizes=None):
    """单行 Form：runs=[(文字, 字体)]。order='visual' 按视觉顺序逐段绘制；'latin_last' 先画中文段、最后补画拉丁段。"""
    ops, x = [], 2
    for i, (text, font) in enumerate(runs):
        fs = (sizes or {}).get(i, size)
        ops.append((font != 'china-s', (x, 2 + size * 1.4), text, font, fs))
        x += _advance(text, font, fs)
    if order == 'latin_last':
        ops.sort(key=lambda o: o[0])
    f = fitz.open()
    p = f.new_page(width=width, height=height)
    for _, pos, text, font, fs in ops:
        p.insert_text(pos, text, fontname=font, fontsize=fs)
    return f


def text_run_page(order, letter_font):
    """C 部分固定页面：图注（括号里的 N）、'A 公司' 标签、'方案 B' 正文 Form、斜体物种名正文 Form。"""
    d = fitz.open()
    pg = d.new_page()
    pg.insert_textbox(fitz.Rect(72, 60, 520, 130), ZH, fontname='china-s', fontsize=10.5)
    pg.draw_rect(fitz.Rect(150, 150, 400, 240), color=(0, 0, 0))
    single = order == 'single_run'
    o = 'visual' if single else order

    def form(runs, **kw):
        if single and all(font == 'china-s' for _, font in runs):
            return runs_form(kw.pop('width'), kw.pop('height'), [(''.join(t for t, _ in runs), 'china-s')], **kw)
        return runs_form(kw.pop('width'), kw.pop('height'), runs, order=o, **kw)
    L = letter_font
    pg.show_pdf_page(fitz.Rect(150, 245, 570, 265), form([('图 1 均匀线阵的方向图（', 'china-s'), ('N', L), (' 为阵元数）', 'china-s')],
                                                        width=420, height=20, size=9), 0)
    pg.show_pdf_page(fitz.Rect(72, 290, 272, 310), form([('A', L), (' 公司的营收增长', 'china-s')], width=200, height=20), 0)
    pg.insert_text((72, 340), '两种方案的比较如下所示，其中', fontname='china-s', fontsize=10.5)
    pg.show_pdf_page(fitz.Rect(72, 350, 492, 370), form([('采用方案 ', 'china-s'), ('B', L), (' 的系统吞吐量更高，时延更低。', 'china-s')],
                                                       width=420, height=20), 0)
    pg.show_pdf_page(fitz.Rect(72, 390, 512, 410), form([('人类（', 'china-s'), ('Homo sapiens', 'tiit'), ('）的基因组已经完成测序。', 'china-s')],
                                                       width=440, height=20), 0)
    return d


# ---------- 1. 文字层公式：包装不改变判定，丢失由成品门判失败 ----------

def text_formula_page():
    """评审第 3 轮冻结正例的原始页面：页面级文字层 'M×N' 位于中文正文行内，另有行外图形 XObject。"""
    d = fitz.open()
    page = b._inline_page(d, figure_xobject=True)
    x = 72 + 10.5 * len(b.ZH_LINE_A) + 4
    page.insert_text((x + 2, 120), 'M×N', fontname='tiro', fontsize=11)
    return d


def test_text_layer_formula_same_verdict_plain_and_wrapped_and_loss_fails_output_gate(tmp_path):
    d = text_formula_page()
    lost, kept = tmp_path / 'lost.pdf', tmp_path / 'kept.pdf'
    # 真实后端成品（905dbf3 / 本轮旁路）就是这句：M×N 被整个丢掉。
    english(lost, ['Consider an array of single-polarized omnidirectional antennas, uniformly spaced along two directions.'])
    english(kept, ['Consider an array of M \u00d7 N single-polarized omnidirectional antennas.'])
    verdicts = []
    for path in variants(d, tmp_path, 'text-formula'):
        report, info, detail = inspect(path)
        assert report['status'] != 'blocked' and info['xobject_text_glyphs'] == 0, (path.name, info)
        assert sorted(o['char'] for o in detail['text_layer_math']) == ['M', 'N', '\u00d7'], (path.name, detail['text_layer_math'])
        g_lost, g_kept = gate(path, lost), gate(path, kept)
        assert g_lost['quality_fail'] and g_lost['text_layer_math_loss_pages'] == [1], path.name
        assert g_lost['pages'][0]['text_layer_math_loss']['lost'] == 3
        assert g_kept['text_layer_math_loss_pages'] == [] and g_kept['pages'][0]['text_layer_math_loss']['lost'] == 0
        verdicts.append((report['status'], info['xobject_text_glyphs'], g_lost['severity'], tuple(g_kept['text_layer_math_loss_pages'])))
    assert len(set(verdicts)) == 1, verdicts
    d.close()


def test_plain_chinese_page_text_has_no_text_layer_math(tmp_path):
    """纯中文页面（含英文术语、年份）：没有文字层数学字形，成品门不因英文译文误判。"""
    d = fitz.open()
    p = d.new_page()
    p.insert_textbox(fitz.Rect(72, 60, 520, 200), '本节基于 Transformer 模型，在 2024 年的数据集上评估。' + ZH,
                     fontname='china-s', fontsize=10.5)
    target = tmp_path / 't.pdf'
    english(target, ['This section evaluates the Transformer model on the 2024 dataset.'])
    for path in variants(d, tmp_path, 'plain-zh'):
        report, info, detail = inspect(path)
        assert report['status'] != 'blocked' and detail['text_layer_math'] == [], (path.name, detail['text_layer_math'])
        assert gate(path, target)['text_layer_math_loss_pages'] == []
    d.close()


# ---------- 2. 页面等价 Form：每个结构的判定与包装层数无关 ----------

@pytest.mark.parametrize('structure', ['text_formula', 'run_letters', 'out_of_order_letters', 'formula_form'])
def test_wrapping_never_changes_verdict(tmp_path, structure):
    if structure == 'text_formula':
        d = text_formula_page()
    elif structure == 'run_letters':
        d = text_run_page('single_run', 'china-s')
    elif structure == 'out_of_order_letters':
        d = text_run_page('latin_last', 'tiro')
    else:
        d = fitz.open()
        p = b._inline_page(d)
        f = runs_form(40, 16, [('M', 'tiro'), ('最大', 'china-s')], sizes={0: 11, 1: 7})
        gap = 72 + 10.5 * len(b.ZH_LINE_A) + 4
        p.show_pdf_page(fitz.Rect(gap, 108, gap + 30, 123), f, 0)
    seen = []
    for path in variants(d, tmp_path, structure):
        report, info, detail = inspect(path)
        seen.append((report['status'] == 'blocked', sorted(o.get('char', '|') for o in detail['objects']),
                     sorted(o['char'] for o in detail['text_layer_math'])))
    assert len(set(map(repr, seen))) == 1, seen
    d.close()


# ---------- 3. 视觉顺序文本流里的字母 / 斜体词：配对正例与反例 ----------

def test_letters_and_italic_word_in_chinese_text_run_are_body(tmp_path):
    """正例：'图 1 …（N 为阵元数）'、'A 公司…'、'采用方案 B …' 用与中文相同的字体在同一文本流里按视觉顺序绘制；
    斜体物种名 'Homo sapiens' 按视觉顺序夹在中文之间。真实后端成品：字母与斜体词都在原位（见第 6 轮证据 c1）。"""
    d = text_run_page('single_run', 'china-s')
    target = tmp_path / 'target.pdf'
    english(target, ['Fig. 1 Pattern of the uniform linear array (N is the number of elements)'])
    for path in variants(d, tmp_path, 'run-letters'):
        report, info, detail = inspect(path)
        assert report['status'] != 'blocked', (path.name, info)
        assert info['needs_review_forms'] == 0 and info['xobject_text_glyphs'] == 0 and info['body_forms'] >= 4, (path.name, info)
        assert gate(path, target)['pages'][0]['inline_object_damage']['located'] == 0
    d.close()


@pytest.mark.parametrize('case', ['latin_last', 'other_font_single_letter'])
def test_letters_not_in_chinese_text_run_stay_needs_review(tmp_path, case):
    """反例：事后补画（绘制顺序与视觉顺序不一致）的字母与斜体词 —— 后端把它们挪到行尾或丢失（第 6 轮证据 c3）；
    另一字体（Times）的孤立单字母即使按视觉顺序绘制也仍按数学变量处理。两者都拒绝，字形逐个计入成品门。"""
    d = text_run_page('latin_last', 'tiro') if case == 'latin_last' else text_run_page('visual', 'tiro')
    expected = sorted('NABHomosapiens') if case == 'latin_last' else sorted('NAB')
    for path in variants(d, tmp_path, case):
        report, info, detail = inspect(path)
        assert report['status'] == 'blocked', (path.name, info)
        assert sorted(o['char'] for o in detail['objects']) == expected, (path.name, detail['objects'])
    d.close()


@pytest.mark.parametrize('case', ['size', 'greek', 'italic_single', 'out_of_order_same_font'])
def test_run_admission_requires_same_size_font_and_order(tmp_path, case):
    """准入的每个条件单独拿掉都必须拒绝：字号不同（上下标）、希腊字母、斜体单字母变量、同字体但事后补画。"""
    d = fitz.open()
    p = d.new_page()
    p.insert_textbox(fitz.Rect(72, 60, 520, 130), ZH, fontname='china-s', fontsize=10.5)
    p.insert_text((72, 160), '其中参数的取值如下所示，并且', fontname='china-s', fontsize=10.5)
    runs = {'size': ([('设阵元数为 ', 'china-s'), ('N', 'china-s'), (' 时增益最大。', 'china-s')], 'visual', {1: 7}),
            'greek': ([('设波长为 ', 'china-s'), ('\u03bb', 'china-s'), (' 时增益最大。', 'china-s')], 'visual', None),
            'italic_single': ([('设阵元数为 ', 'china-s'), ('N', 'tiit'), (' 时增益最大。', 'china-s')], 'visual', None),
            'out_of_order_same_font': ([('设阵元数为 ', 'china-s'), ('N', 'china-s'), (' 时增益最大。', 'china-s')], 'late', None)}
    parts, order, sizes = runs[case]
    if order == 'late':
        f = runs_form(420, 20, parts)
        fp = fitz.open()
        page = fp.new_page(width=420, height=20)
        x2 = 2 + _advance(parts[0][0], 'china-s', 10.5)
        page.insert_text((2, 2 + 10.5 * 1.4), parts[0][0], fontname='china-s', fontsize=10.5)
        page.insert_text((x2 + _advance('N', 'china-s', 10.5), 2 + 10.5 * 1.4), parts[2][0], fontname='china-s', fontsize=10.5)
        page.insert_text((x2, 2 + 10.5 * 1.4), 'N', fontname='china-s', fontsize=10.5)
        f.close()
        f = fp
    else:
        f = runs_form(420, 20, parts, sizes=sizes)
    p.show_pdf_page(fitz.Rect(72, 170, 492, 190), f, 0)
    for path in variants(d, tmp_path, case):
        report, info, detail = inspect(path)
        assert report['status'] == 'blocked' and info['needs_review_forms'] == 1, (path.name, info)
    d.close()


@pytest.mark.parametrize('order', ['visual', 'latin_last'])
def test_italic_words_admitted_only_in_visual_order(tmp_path, order):
    """配对：斜体物种名与书名（多字母斜体词）按视觉顺序夹在中文之间 → 正文，不拦（第 6 轮证据 c4：成品词句完整、位置正确，
    斜体样式不保留）；同样的词事后补画 → needs_review（证据 c3：词被挪到句末或丢失、后端排版失败）。"""
    d = fitz.open()
    pg = d.new_page()
    pg.insert_textbox(fitz.Rect(72, 60, 520, 130), ZH, fontname='china-s', fontsize=10.5)
    pg.insert_text((72, 160), '下面给出两个例子，说明斜体词的处理方式：', fontname='china-s', fontsize=10.5)
    sp = runs_form(440, 20, [('人类（', 'china-s'), ('Homo sapiens', 'tiit'), ('）的基因组已经完成测序。', 'china-s')], order=order)
    pg.show_pdf_page(fitz.Rect(72, 170, 512, 190), sp, 0)
    bk = runs_form(440, 20, [('该算法最早见于 ', 'china-s'), ('The Art of Computer Programming', 'tiit'), (' 一书。', 'china-s')], order=order)
    pg.show_pdf_page(fitz.Rect(72, 200, 512, 220), bk, 0)
    for path in variants(d, tmp_path, f'italic-{order}'):
        report, info, detail = inspect(path)
        if order == 'visual':
            assert report['status'] != 'blocked' and info['needs_review_forms'] == 0, (path.name, info)
        else:
            assert report['status'] == 'blocked' and info['needs_review_forms'] == 2, (path.name, info)
    d.close()
