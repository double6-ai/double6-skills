"""P2-7：同一行普通拉丁词界不能在送模型前丢失（get_char_unicode_string）。

原件不编码空格字形、只用字形位移表达词间距时，旧规则只在间隙不小于“第二小的不同正间隙”时补空格，
较小的真实词间距（例：arXiv:2501.00659 第 5 页标题 “Excursion: Metascience Perspectives” 的 eP 间隙
2.9888 pt = 0.25 em）被吞掉。新规则 `_is_latin_word_gap` 只按原字形几何补判：同基线、同字号、
拉丁字母/数字（及句末标点、左引号）之间、间隙 ≥ LATIN_WORD_GAP_EM 个字号并扣除本串字距基线。

真实几何夹具 tests/fixtures/word_boundaries/real_lines.json 取自许可明确的论文（CC BY 4.0，PDF 不入库）；
其余用例以 PyMuPDF 生成的真实 PDF（base14 字体、TJ 位移/Tc 字距/Ts 升降）逐字形读回。
“旧行为”用同一函数并关闭新判定得到（等价于 7112c8c 的 helper），用于证明测试能区分前后。
"""
import json
import sys
import unicodedata
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'vendor/babeldoc'))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.utils import layout_helper as lh  # noqa: E402

REAL = json.loads((SKILL / 'tests/fixtures/word_boundaries/real_lines.json').read_text(encoding='utf-8'))['lines']
ZH = json.loads((SKILL / 'tests/fixtures/zh2en/arxiv2512.18979_p5_chars.json').read_text(encoding='utf-8'))
ZH_JUSTIFIED = json.loads((SKILL / 'tests/fixtures/zh2en/arxiv2510.26803_p3_chars.json').read_text(encoding='utf-8'))['justified_lines']


def char(u, x, y, x2, y2, size, font='F1', **kw):
    box = il.Box(x=x, y=y, x2=x2, y2=y2)
    return il.PdfCharacter(char_unicode=u, box=box, visual_bbox=il.VisualBbox(box=box), vertical=kw.pop('vertical', False),
                           pdf_style=il.PdfStyle(font_id=font, font_size=size), scale=1, advance=x2 - x, **kw)


def both(chars):
    """(旧 helper 结果, 新 helper 结果)。"""
    new = lh.get_char_unicode_string(chars)
    keep = lh._is_latin_word_gap
    lh._is_latin_word_gap = lambda *a, **k: False
    try:
        old = lh.get_char_unicode_string(chars)
    finally:
        lh._is_latin_word_gap = keep
    return old, new


def pdf_chars(tmp_path, content, fonts=('tibo',)):
    """把原始内容流写成真实 PDF，再按审稿测试的方式读回 texttrace 字形（真实空格字形保留为字符）。"""
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    for name in fonts:
        page.insert_font(fontname=name)
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, content.encode('latin-1'))
    page.set_contents(xref)
    path = tmp_path / 'line.pdf'
    doc.save(path)
    page = fitz.open(path)[0]
    out = []
    for sp in page.get_texttrace():
        for c in sp['chars']:
            out.append(char(chr(c[0]), *c[3], sp['size'], sp['font']))
    return out


# ---------- 冻结原件几何（审稿 P2-7 用例）----------

def test_frozen_heading_from_original_glyphs_keeps_both_word_boundaries():
    line = next(x for x in REAL if x['frozen_case'])
    assert line['source_sha256'] == 'cd3604e020f8e74d2014e91a9eb88df6d93a6b3cf2d0cd6dccde7c062384f255' and line['page'] == 5
    chars = [char(*row) for row in line['rows']]
    assert not [c for c in chars if c.char_unicode == ' ']  # 原件无空格字形，只有位移
    gaps = {a.char_unicode + b.char_unicode: round(b.box.x - a.box.x2, 4) for a, b in zip(chars, chars[1:]) if b.box.x - a.box.x2 > 1}
    assert gaps == {':M': 3.7061, 'eP': 2.9888}
    old, new = both(chars)
    assert old == 'Excursion: MetasciencePerspectives'
    assert new == 'Excursion: Metascience Perspectives' == line['mupdf_text']
    for word in ('Metascience', 'Perspectives'):  # 同一字形逐词提取不拆字
        start = new.replace(' ', '').index(word)
        assert lh.get_char_unicode_string(chars[start:start + len(word)]) == word


@pytest.mark.parametrize('line', [x for x in REAL if not x['frozen_case']],
                         ids=lambda x: f"{x['source'][:12]}-p{x['page']}-{x['line_bbox'][1]:.0f}")
def test_other_real_lines_only_gain_word_spaces_or_stay_identical(line):
    chars = [char(*row) for row in line['rows']]
    old, new = both(chars)
    assert (old, new) == (line['expected_legacy'], line['expected_new'])
    assert new.replace(' ', '') == old.replace(' ', '')  # 只增减空格，不改任何字形文字
    assert len(new) >= len(old)  # 只补空格，不删既有空格
    if old != new:
        assert new == line['mupdf_text']  # 补出的词界与 MuPDF 独立抽取一致


# ---------- 真实 PDF：位移、字距、整体加字距 ----------

def test_displacement_only_word_gaps_in_a_real_pdf(tmp_path):
    chars = pdf_chars(tmp_path, 'BT /tibo 12 Tf 20 150 Td [(Excursion:) -310 (Metascience) -250 (Perspectives)] TJ ET')
    old, new = both(chars)
    assert old == 'Excursion: MetasciencePerspectives'
    assert new == 'Excursion: Metascience Perspectives'


@pytest.mark.parametrize('tj,expected', [
    ('[(W) 80 (a) -80 (ter) -60 (fall) -250 (and) -250 (of) -80 (f) (ice)]', 'Waterfall and office'),  # 字内正字距 ≤ 0.08 em
    ('[(A) 120 (V) -70 (A) (T) 90 (ype) -250 (Lo) -50 (gic)]', 'AVAType Logic'),
])
def test_intra_word_kerning_is_not_split(tmp_path, tj, expected):
    chars = pdf_chars(tmp_path, f'BT /tibo 12 Tf 20 150 Td {tj} TJ ET')
    old, new = both(chars)
    assert new == old == expected
    assert not any(lh._is_latin_word_gap(a, b) for a, b in zip(chars, chars[1:]) if 0 < b.box.x - a.box.x2 < 1.0)


def test_letter_spaced_heading_keeps_letters_together_but_splits_words(tmp_path):
    # Tc 2 pt = 0.167 em 整体加字距：每个字内间隙都超过 0.15 em，按本串字距基线扣除后不拆字。
    chars = pdf_chars(tmp_path, 'BT /tibo 12 Tf 2 Tc 20 150 Td [(SPACED) -250 (HEADING) -250 (TEXT)] TJ ET')
    assert lh._latin_tracking_em(chars) == pytest.approx(2 / 12, abs=1e-3)
    assert lh.get_char_unicode_string(chars) == 'SPACED HEADING TEXT'


def test_threshold_is_relative_to_font_size_and_tracking():
    def pair(gap, size=10.0):
        return char('a', 0, 0, 5, size, size), char('b', 5 + gap, 0, 10 + gap, size, size)
    assert not lh._is_latin_word_gap(*pair(0.149 * 10))
    assert lh._is_latin_word_gap(*pair(0.151 * 10))
    assert not lh._is_latin_word_gap(*pair(1.51, size=20))  # 同样 1.51 pt 在 20 pt 字号下只是 0.0755 em
    assert not lh._is_latin_word_gap(*pair(0.2 * 10), tracking_em=0.1)  # 扣除字距基线


# ---------- 保护：连字符、代码、上下标、符号/公式、CJK ----------

def test_real_hyphens_and_dashes_are_unchanged(tmp_path):
    chars = pdf_chars(tmp_path, 'BT /tibo 12 Tf 20 150 Td [(state) -200 (-) -200 (of) -40 (-the-art) -250 (co) (-) -300 (operation)] TJ ET')
    old, new = both(chars)
    assert new == old
    assert 'state' in new and 'operation' in new and new.count('-') == 4


def test_code_tokens_are_unchanged(tmp_path):
    chars = pdf_chars(tmp_path, r'BT /cour 10 Tf 20 150 Td [(foo) -40 (_bar) -30 (\(x\)) -40 (.baz) -20 ([0]) -40 (->) (next)] TJ ET', fonts=('cour',))
    old, new = both(chars)
    assert new == old == 'foo_bar(x).baz[0]->next'


def test_superscript_and_subscript_runs_are_unchanged(tmp_path):
    content = ('BT /tibo 12 Tf 20 150 Td (word) Tj /tibo 7 Tf 5 Ts [-200 (12)] TJ /tibo 12 Tf 0 Ts [-250 (next)] TJ ET '
               'BT /tibo 12 Tf 20 100 Td (x) Tj /tibo 7 Tf -3 Ts [-200 (ij)] TJ /tibo 12 Tf 0 Ts (y) Tj ET')
    chars = pdf_chars(tmp_path, content)
    assert not any(lh._is_latin_word_gap(a, b) for a, b in zip(chars, chars[1:]) if a.pdf_style.font_size != b.pdf_style.font_size)
    old, new = both(chars)
    assert new == old
    assert {c.pdf_style.font_size for c in chars} == {12.0, 7.0}


def test_symbol_and_formula_runs_are_unchanged():
    size = 10.0
    def run(text, gap, **kw):
        out, x = [], 0.0
        for u in text:
            out.append(char(u, x, 0, x + 5, size, size, **kw))
            x += 5 + gap
        return out
    for text in ('a+b=c', 'x∈R', 'f(x)', '(i,j)'):
        old, new = both(run(text, 0.25 * size))
        assert new == old  # 符号/括号不在判定字符集里，新规则不改变
    formula = run('xlogx', 0.2 * size, formula_layout_id=7)
    assert both(formula)[0] == both(formula)[1]  # 公式版面区域内的字形不参与
    vertical = run('word', 0.3 * size, vertical=True)
    assert both(vertical)[0] == both(vertical)[1]
    nosize = [char(c.char_unicode, c.box.x, c.box.y, c.box.x2, c.box.y2, 0.0) for c in run('ab', 0.3 * size)]
    assert both(nosize)[0] == both(nosize)[1]


def _zh_chars(rows, size=10.5):
    return [char(u, x, y, x2, y2, size) for (u, x, y, x2, y2) in rows]


@pytest.mark.parametrize('rows', [ZH['prose_lines'][0] + ZH['prose_lines'][1], *ZH_JUSTIFIED,
                                  [c for cell in ZH['table_rows'][:7] for c in cell], [c for cell in ZH['table_rows'][7:16] for c in cell]])
def test_cjk_real_lines_get_no_space_between_cjk_characters(rows):
    chars = _zh_chars(rows)
    old, new = both(chars)
    assert new.replace(' ', '') == old.replace(' ', '')
    assert not any(lh._is_latin_word_gap(a, b) for a, b in zip(chars, chars[1:])
                   if lh._is_cjk_no_space_char(a.char_unicode) or lh._is_cjk_no_space_char(b.char_unicode))
    if new != old:  # 表 1 数据行：相邻数字单元格 0.561|0.157 由间隙分开（原规则粘连），汉字之间不受影响
        assert '0.561 0.157' in new and '0.5610.157' in old


def test_cjk_runs_with_wide_gaps_get_no_new_spaces():
    chars, x = [], 0.0
    for u in '研究领域样本量':
        chars.append(char(u, x, 0, x + 10, 10, 10))
        x += 10 + 3.0  # 0.3 em 字距（两端对齐）
    old, new = both(chars)
    assert new == old and ' ' not in new
    assert not unicodedata.name(new[0]).startswith('LATIN')
