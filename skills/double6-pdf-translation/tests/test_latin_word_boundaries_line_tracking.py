"""第十三轮复核 P2：字距基线逐物理行计算，段落里的其它行不能稀释加字距行的基线。

cb3c445 的 `_latin_tracking_em` 对整串（段落把多条 PdfLine 拼成一串）取一个中位数：Tc 2 pt 的加字距标题行
单独为 0.1667 em，与一条普通字距行合并后被稀释为 0，标题字内 2 pt 间隙于是被当成词间距，
“SPACED HEADING TEXT” 变成 “S P A C E D …”。现在 `_latin_line_tracking_ems` 先按相邻字形的物理行连续性
（字框竖向重叠、没有回到行首）切段，各段单独取基线。

“旧行为”取 7112c8c 的完整原 helper 文件（tests/fixtures/word_boundaries/layout_helper_7112c8c.py，
SHA 347ba2d7…，与审稿冻结的 old_helper_7112.py 相同），不是关闭新函数模拟。
输入是 PyMuPDF 写出的真实 PDF（base14 字体、Tc/TJ），逐字形读回；坐标分别按 texttrace（自上而下）
和后端使用的 PDF 坐标（自下而上）两种方向检查。
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'vendor/babeldoc'))

from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.utils import layout_helper as lh  # noqa: E402

OLD_PATH = SKILL / 'tests/fixtures/word_boundaries/layout_helper_7112c8c.py'
OLD_SHA256 = '347ba2d748f5ad760f7a30c2d92b4463b097c10b827bc292a06be2ce61b60a16'
REAL = json.loads((SKILL / 'tests/fixtures/word_boundaries/real_lines.json').read_text(encoding='utf-8'))['lines']
PAGE_H = 200

SPACED = 'BT /tibo 12 Tf 2 Tc 20 {y} Td [(SPACED) -250 (HEADING) -250 (TEXT)] TJ ET'
NORMAL = 'BT /tibo 12 Tf 0 Tc 20 {y} Td (ordinary words along the following line remain normally spaced and readable) Tj ET'
# 普通字距、但词间只有 TJ 位移没有空格字形：需要本次词界补判
DISPLACED = 'BT /tibo 12 Tf 0 Tc 20 {y} Td [(7) -250 (Excursion:) -310 (Metascience) -250 (Perspectives)] TJ ET'


def old_helper():
    assert hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() == OLD_SHA256
    spec = importlib.util.spec_from_file_location('layout_helper_7112c8c', OLD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = old_helper()


def char(u, x, y, x2, y2, size, font='F1'):
    box = il.Box(x=x, y=y, x2=x2, y2=y2)
    return il.PdfCharacter(char_unicode=u, box=box, visual_bbox=il.VisualBbox(box=box), pdf_style=il.PdfStyle(font_id=font, font_size=size),
                           scale=1, advance=x2 - x)


def pdf_lines(tmp_path, *streams, bottom_up=False):
    """每个内容流写成一行；返回按行分组的字形（真实 PDF 读回）。bottom_up=True 时换成后端的 PDF 坐标。"""
    doc = fitz.open()
    page = doc.new_page(width=500, height=PAGE_H)
    page.insert_font(fontname='tibo')
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, ' '.join(streams).encode('latin-1'))
    page.set_contents(xref)
    path = tmp_path / 'lines.pdf'
    doc.save(path)
    lines = []
    for sp in fitz.open(path)[0].get_texttrace():
        row = []
        for c in sp['chars']:
            x0, y0, x1, y1 = c[3]
            if bottom_up:
                y0, y1 = PAGE_H - y1, PAGE_H - y0
            row.append(char(chr(c[0]), x0, y0, x1, y1, sp['size'], sp['font']))
        lines.append(row)
    assert len(lines) == len(streams)
    return lines


def flat(lines):
    return [c for line in lines for c in line]


def paragraph(lines):
    comps = [il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=line)) for line in lines]
    return il.PdfParagraph(pdf_paragraph_composition=comps)


def only_spaces_added(old, new):
    if old.replace(' ', '') != new.replace(' ', ''):
        return False
    i = 0
    for ch in new:  # old 是 new 去掉若干空格后的子序列
        if i < len(old) and ch == old[i]:
            i += 1
        elif ch != ' ':
            return False
    return i == len(old)


ORIENT = pytest.mark.parametrize('bottom_up', [False, True], ids=['texttrace', 'pdf-coords'])


@ORIENT
@pytest.mark.parametrize('order', ['spaced-first', 'normal-first'])
def test_mixed_tracking_lines_keep_letter_spaced_words_in_either_order(tmp_path, bottom_up, order):
    spaced, normal = SPACED.format(y=150), NORMAL.format(y=100)
    streams = (spaced, normal) if order == 'spaced-first' else (NORMAL.format(y=150), SPACED.format(y=100))
    lines = pdf_lines(tmp_path, *streams, bottom_up=bottom_up)
    chars = flat(lines)
    new, old = lh.get_char_unicode_string(chars), OLD.get_char_unicode_string(chars)
    assert 'SPACED HEADING TEXT' in new
    assert 'ordinary words along the following line remain normally spaced and readable' in new
    assert new == old  # 两行都没有只靠位移的词间距：合并输入与 7112 原 helper（含第二小间隙规则与行间处理）完全一致
    spaced_index = 0 if order == 'spaced-first' else 1
    tracking = lh._latin_line_tracking_ems(chars)
    spaced_range = range(len(lines[0])) if spaced_index == 0 else range(len(lines[0]), len(chars))
    normal_range = range(len(lines[0]), len(chars)) if spaced_index == 0 else range(len(lines[0]))
    assert {round(tracking[i], 4) for i in spaced_range} == {round(2 / 12, 4)}
    assert {tracking[i] for i in normal_range} == {0.0}


@ORIENT
def test_several_letter_spaced_lines_with_one_normal_line(tmp_path, bottom_up):
    # 三条 Tc 2 pt 的加字距行（12/10/11 pt，基线 0.167/0.2/0.18 em）+ 一条普通行：cb3c445 把三行全部拆成单字母
    streams = (
        'BT /tibo 12 Tf 2 Tc 20 170 Td [(SPACED) -250 (HEADING) -250 (TEXT)] TJ ET',
        'BT /tibo 10 Tf 2 Tc 20 140 Td [(WIDE) -250 (TRACKED) -250 (LINE)] TJ ET',
        'BT /tibo 11 Tf 2 Tc 20 110 Td [(SECOND) -250 (HEADING)] TJ ET',
        NORMAL.format(y=80),
    )
    lines = pdf_lines(tmp_path, *streams, bottom_up=bottom_up)
    chars = flat(lines)
    new, old = lh.get_char_unicode_string(chars), OLD.get_char_unicode_string(chars)
    assert new == old  # 与 7112 原 helper 完全一致（包括原有整串第二小间隙规则自身的结果）
    for words in ('SPACED HEADING TEXT', 'WIDE TRACKED LINE', 'ordinary words along the following line'):
        assert words in new, new
    for word in ('SPACED', 'HEADING', 'TEXT', 'WIDE', 'TRACKED', 'LINE'):
        assert ' '.join(word) not in new
    tracking = lh._latin_line_tracking_ems(chars)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    expected = [2 / 12, 2 / 10, 2 / 11, 0.0]
    for k, value in enumerate(expected):
        assert set(round(v, 4) for v in tracking[starts[k]:starts[k + 1]]) == {round(value, 4)}


@ORIENT
def test_legacy_whole_string_split_is_neither_introduced_nor_hidden(tmp_path, bottom_up):
    """不同 Tc 的多行加字距：7112 原有“整串第二小正间隙”规则本身就会拆字（既有行为，本项不改），
    新 helper 与 7112 完全一致，既不新增拆分也不改原规则。"""
    streams = (
        'BT /tibo 12 Tf 2 Tc 20 170 Td [(SPACED) -250 (HEADING) -250 (TEXT)] TJ ET',
        'BT /tibo 10 Tf 3 Tc 20 140 Td [(WIDE) -250 (TRACKED) -250 (LINE)] TJ ET',
        'BT /tibo 14 Tf 1.5 Tc 20 110 Td [(SECOND) -250 (HEADING)] TJ ET',
        NORMAL.format(y=80),
    )
    chars = flat(pdf_lines(tmp_path, *streams, bottom_up=bottom_up))
    old = OLD.get_char_unicode_string(chars)
    assert 'S P A C E D' in old
    assert lh.get_char_unicode_string(chars) == old


@ORIENT
def test_word_boundary_repair_still_fires_on_a_normal_line_next_to_a_spaced_line(tmp_path, bottom_up):
    lines = pdf_lines(tmp_path, SPACED.format(y=150), DISPLACED.format(y=100), bottom_up=bottom_up)
    chars = flat(lines)
    new, old = lh.get_char_unicode_string(chars), OLD.get_char_unicode_string(chars)
    assert 'SPACED HEADING TEXT' in new
    assert '7 Excursion: Metascience Perspectives' in new
    # 7112 对这条普通行单独抽取时漏掉 eP 词界；合并后新 helper 仍保留它（补判没有被关掉）
    assert 'MetasciencePerspectives' in OLD.get_char_unicode_string(lines[1])
    assert only_spaces_added(old, new)


@ORIENT
def test_single_line_controls_are_unchanged(tmp_path, bottom_up):
    spaced, normal, displaced = pdf_lines(tmp_path, SPACED.format(y=150), NORMAL.format(y=100), DISPLACED.format(y=50), bottom_up=bottom_up)
    assert lh.get_char_unicode_string(spaced) == OLD.get_char_unicode_string(spaced) == 'SPACED HEADING TEXT'
    assert lh.get_char_unicode_string(normal) == OLD.get_char_unicode_string(normal)
    assert lh.get_char_unicode_string(displaced) == '7 Excursion: Metascience Perspectives'
    assert lh._latin_line_tracking_ems(spaced) == [pytest.approx(lh._latin_tracking_em(spaced))] * len(spaced)


@ORIENT
@pytest.mark.parametrize('order', ['spaced-first', 'normal-first'])
def test_real_paragraph_pipeline_combines_lines_without_splitting(tmp_path, bottom_up, order):
    streams = (SPACED.format(y=150), NORMAL.format(y=100)) if order == 'spaced-first' else (NORMAL.format(y=150), SPACED.format(y=100))
    lines = pdf_lines(tmp_path, *streams, bottom_up=bottom_up)
    para = paragraph(lines)
    new, old = lh.get_paragraph_unicode(para), OLD.get_paragraph_unicode(para)
    assert new == old
    assert 'SPACED HEADING TEXT' in new and 'S P A C E D' not in new
    para = paragraph(pdf_lines(tmp_path, SPACED.format(y=150), DISPLACED.format(y=100), bottom_up=bottom_up))
    new = lh.get_paragraph_unicode(para)
    assert 'SPACED HEADING TEXT' in new and 'Metascience Perspectives' in new


def test_real_corpus_lines_combined_keep_each_lines_own_tracking():
    """真实几何夹具：同一页的多条真实行拼成一串时，每个字的基线等于它所在行单独计算的基线，
    合并结果与逐行结果的差别只来自原有的整串第二小间隙规则与行间处理（与 7112 helper 一致）。"""
    groups = {}
    for line in REAL:
        if line.get('frozen_case'):
            continue
        groups.setdefault((line['source'], line['page']), []).append(line)
    checked = 0
    for (_, _), group in groups.items():
        group = sorted(group, key=lambda x: -x['rows'][0][2])  # 自上而下（PDF 坐标 y 大者在上）
        rows = [[char(*r) for r in line['rows']] for line in group]
        tops = [(min(c.box.y for c in r), max(c.box.y2 for c in r)) for r in rows]
        if len(rows) < 2 or any(a[0] < b[1] for a, b in zip(tops, tops[1:])):
            continue  # 只用竖向不重叠的不同物理行
        chars = flat(rows)
        tracking = lh._latin_line_tracking_ems(chars)
        expected = [lh._latin_tracking_em(r) for r in rows for _ in r]
        assert tracking == pytest.approx(expected)
        new, old = lh.get_char_unicode_string(chars), OLD.get_char_unicode_string(chars)
        assert only_spaces_added(old, new)
        checked += 1
    assert checked >= 3
