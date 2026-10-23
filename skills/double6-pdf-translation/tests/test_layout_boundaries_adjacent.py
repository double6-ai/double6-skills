"""PR #24 review-1 相邻边界：嵌套正文框只合并同一文字流、表格只在有可信列证据处拆分。

与 test_pr24_review1_layout_boundaries.py（评审给出的两个独立 PDF 用例）互补：这里用合成字符几何覆盖
同一规则两侧的正反例，直接运行真实的 ParagraphFinder.process_page，不依赖模型、网络或字体下载。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_layout_line_fragments import _page, _process, _word_chars, il, text, texts  # noqa: E402


def _words(line, x, y, size=9.0, step=4.5):
    chars = []
    for word in line.split(' '):
        word_chars, x = _word_chars(word, x, y, size, step)
        chars += word_chars
        x += step
    return chars


def _paragraph_with(page, needle):
    return [p for p in page.pdf_paragraph if needle in text(p)]


# ------------------------------------------------ 嵌套正文框：只合并同一文字流的重复检测

def test_wide_main_column_and_boxed_sidebar_in_one_container_stay_separate():
    # 外框把正文栏和侧栏一起框住；正文栏框覆盖外框 70% 宽，但侧栏有自己的框与它并排：是两栏。
    chars = (_words('Main column first line', 60, 700) + _words('Main column second line', 60, 684)
             + _words('Side note one', 440, 700) + _words('Side note two', 440, 684))
    layouts = [('plain text', (55, 680, 420, 712)), ('plain text', (435, 680, 555, 712)),
               ('plain text', (50, 675, 560, 716))]
    page = _process(_page(chars, layouts))
    main, side = _paragraph_with(page, 'Main column first'), _paragraph_with(page, 'Side note one')
    assert main and side and main[0] is not side[0], texts(page)
    assert 'Side' not in text(main[0]) and 'Main' not in text(side[0]), texts(page)


def test_unboxed_text_beyond_a_column_gutter_is_not_merged_into_the_column():
    # 侧栏没有自己的框、只在外框里，与正文栏隔着栏间空白：内框不是外框的重复检测，不并。
    chars = (_words('Main column first line', 60, 700) + _words('Main column second line', 60, 684)
             + _words('Side note one', 440, 700) + _words('Side note two', 440, 684))
    layouts = [('plain text', (55, 680, 420, 712)), ('plain text', (50, 675, 560, 716))]
    page = _process(_page(chars, layouts))
    main = _paragraph_with(page, 'Main column first')
    assert main and 'Side' not in text(main[0]), texts(page)
    assert 'second line' in text(main[0]), texts(page)


def test_nested_duplicate_box_that_truncates_lines_is_merged_into_one_paragraph():
    # 内框比外框窄一截，把两行行首截在框外（同一行连续跨过内框左边缘）；第三行整行在内框里。
    # 这是同一段的重复检测：三行归外框，成为一个段落，没有内框小段。
    chars = (_words('Alpha beta gamma delta epsilon zeta', 90, 420)
             + _words('Theta iota kappa lambda mu nu xi', 90, 406)
             + _words('omicron pi rho sigma', 140, 392))
    layouts = [('plain text', (87, 388, 300, 432)), ('plain text', (130, 389, 298, 431))]
    page = _process(_page(chars, layouts))
    hit = _paragraph_with(page, 'Alpha beta')
    assert hit and 'omicron pi rho sigma' in text(hit[0]) and 'Theta iota' in text(hit[0]), texts(page)
    assert hit[0].layout_id == 1, (hit[0].layout_id, texts(page))


def test_line_crossing_a_gutter_into_unboxed_text_keeps_the_far_part_out():
    # 同一物理高度上，左栏有框、右侧文字无框且隔着很宽的空白：右侧不并入左栏框。
    chars = _words('Left column words here', 60, 500) + _words('Far right words', 400, 500)
    page = _process(_page(chars, [('plain text', (55, 496, 200, 512))]))
    left = _paragraph_with(page, 'Left column')
    assert left and 'Far right' not in text(left[0]), texts(page)


# ------------------------------------------------ 表格：只在有可信列证据处拆分

def _value_rows(rows, y0=600.0, xs=(100.0, 155.0, 210.0)):
    """每行的词之间用空格字形连到下一个词（行聚类因此把一行聚成一个 fallback_line），各行词位对齐。"""
    from test_layout_line_fragments import _char
    chars = []
    for r, words in enumerate(rows):
        y = y0 - 18.0 * r
        for i, (x, word) in enumerate(zip(xs, words)):
            word_chars, end = _word_chars(word, x, y, 9.0, 4.5)
            chars += word_chars
            if i + 1 < len(words):
                chars.append(_char(' ', end, y, xs[i + 1] - end))
    return chars


def _curve(x, y, x2, y2):
    return il.PdfCurve(box=il.Box(x, y, x2, y2), graphic_state=il.GraphicState())


def test_aligned_word_gaps_without_cells_or_rules_are_not_column_evidence():
    # 每行只有一个段落，词间空白在各行对齐，但没有单元格框、表格线或已分开的行：不拆。
    page = _process(_page(_value_rows((('New', 'York', 'USA'), ('San', 'Jose', 'USA'))),
                          [('table', (90, 570, 280, 615))]))
    assert sorted(texts(page)) == ['New York USA', 'San Jose USA'], texts(page)


def test_vertical_table_rules_in_the_gutters_are_column_evidence():
    # 同样的行，但每条列间空白都有竖直表格线穿过：按列拆开。
    page = _page(_value_rows((('New', 'York', 'USA'), ('San', 'Jose', 'USA'))), [('table', (90, 570, 280, 615))])
    page.pdf_curve = [_curve(140, 572, 140.5, 613), _curve(190, 572, 190.5, 613)]
    page = _process(page)
    assert sorted(texts(page)) == sorted(['New', 'York', 'USA', 'San', 'Jose', 'USA']), texts(page)


def test_cell_box_spanning_a_gutter_keeps_that_gutter_inside_the_cell():
    # 表头前两列是一个合并单元格（单元格框横跨它们之间的空白）：那里不拆，其余列照常按数据行证据拆。
    from test_layout_line_fragments import _table_chars
    page = _process(_page(_table_chars(), [('table', (149, 120, 446, 212)), ('table_cell', (150, 198, 238, 211))]))
    header = [t for t in sorted((p.box.x, text(p)) for p in page.pdf_paragraph if p.box.y >= 199.0)]
    assert [t for _, t in header] == ['Region Count', 'Mean', 'Spread'], texts(page)


def test_multi_column_cell_grid_still_splits_the_unboxed_header():
    # 数据行每格都有单元格框（可信多列网格）；表头整行聚成一行、不在任何单元格框里：在单元格分界处拆开。
    from test_layout_line_fragments import COLUMNS, _table_chars
    rows = (('Alpha', '8509', '0.561', '0.157'), ('Beta', '5101', '0.538', '0.118'))
    edges = list(COLUMNS) + [320.0]
    cells = []
    for r in range(len(rows)):
        y = 182.0 - 16.0 * r
        cells += [('table_cell', (edges[i] - 1, y - 1, edges[i + 1] - 4, y + 10)) for i in range(len(COLUMNS))]
    page = _process(_page(_table_chars(rows), [('table', (149, 120, 446, 212))] + cells))
    header = [t for _, t in sorted((p.box.x, text(p)) for p in page.pdf_paragraph if p.box.y >= 199.0)]
    assert header == ['Region', 'Count', 'Mean', 'Spread'], texts(page)
    assert 'Alpha' in texts(page) and '0.157' in texts(page), texts(page)
