"""PR #24 review-2：数据行里按列锚点堆叠的值记号（数字、布尔量）是列证据，词间对齐空白不是。

真实几何正例取自 17b 表 2（arXiv:2512.18979v1 第 5 页，只含表 2 表头与一行数据的逐字符几何，
见 fixtures/layout_fragments/README.md）；反例与合成正例用构造几何。直接运行真实的 ParagraphFinder.process_page。
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_layout_line_fragments import FIXTURES, _char, _page, _process, _word_chars, text, texts  # noqa: E402
from babeldoc.format.pdf.document_il.midend.paragraph_finder import ParagraphFinder  # noqa: E402
import test_table_figure_text as tft  # noqa: E402

TABLE2 = 'arxiv2512.18979-p5-table2-header.json'


def _run_fixture(name, default_config=False):
    saved = tft.FIXTURES
    tft.FIXTURES = FIXTURES
    try:
        data, page = tft.load_page(name)
    finally:
        tft.FIXTURES = saved
    finder = ParagraphFinder.__new__(ParagraphFinder)
    config = dict(data['config'])
    if default_config:
        config.update(split_short_lines=False, short_line_split_factor=0.8, merge_alternating_line_numbers=True)
    finder.translation_config = NS(**config)
    finder.process_page(page)
    return page


def _row(page, y0, y1):
    return sorted((p.box.x, text(p)) for p in page.pdf_paragraph if y0 <= p.box.y <= y1)


def test_real_17b_table2_header_binds_all_seven_fields_to_their_data_columns():
    for default_config in (False, True):
        page = _run_fixture(TABLE2, default_config)
        header = _row(page, 80.0, 86.0)
        data = _row(page, 60.0, 68.0)
        assert [t for _, t in header] == ['组 1', '组 2', '均差*', '校正 p', '下限', '上限', '拒绝原假设'], texts(page)
        assert [t for _, t in data] == ['健康科学', '生命科学', '-0.018', '0.000', '-0.027', '-0.008', 'TRUE'], texts(page)
        # 每个表头字段的左锚点与它下面数据列的左锚点一致（源 PDF 实测相差 ≤0.15 pt）。
        for (hx, _), (dx, _) in zip(header, data):
            assert abs(hx - dx) <= 0.5, (header, data)


def _spaced_rows(rows, xs, y0=600.0, size=9.0, step=4.5):
    """每行词之间用空格字形连到下一个词：行聚类把一行聚成一个 fallback_line。"""
    chars = []
    for r, words in enumerate(rows):
        y = y0 - 18.0 * r
        for i, (x, word) in enumerate(zip(xs[r] if isinstance(xs[0], tuple) else xs, words)):
            row_xs = xs[r] if isinstance(xs[0], tuple) else xs
            word_chars, end = _word_chars(word, x, y, size, step)
            chars += word_chars
            if i + 1 < len(words):
                chars.append(_char(' ', end, y, row_xs[i + 1] - end))
    return chars


def test_header_over_stacked_numeric_columns_is_split_without_cells_or_rules():
    # 表头与两行数据各自聚成一整行；没有单元格框、表格线，也没有已分开的行。数据行的数值左锚点与表头字段堆叠在同一列。
    xs = (100.0, 160.0, 220.0)
    page = _process(_page(_spaced_rows((('Count', 'Mean', 'SD'), ('8509', '0.561', '0.157'), ('5101', '0.538', '0.118')), xs),
                          [('table', (90, 560, 280, 615))]))
    header = [t for _, t in sorted((p.box.x, text(p)) for p in page.pdf_paragraph if p.box.y >= 599.0)]
    assert header == ['Count', 'Mean', 'SD'], texts(page)


def test_numeric_pair_without_a_stacked_column_anchor_is_not_column_evidence():
    # 数据行两个数值之间有空白，但右边的数值与其他行任何片段都不在同一列锚点上：不算列证据，两行都不拆。
    page = _process(_page(_spaced_rows((('Name', 'Value'), ('7', '8')), ((100.0, 200.0), (100.0, 160.0))),
                          [('table', (90, 570, 280, 615))]))
    assert sorted(texts(page)) == ['7 8', 'Name Value'], texts(page)


def test_word_rows_with_aligned_gaps_stay_whole():
    # 词行（“New York USA”）的对齐空白仍不算列证据（与 test_layout_boundaries_adjacent 的反例同一规则）。
    xs = (100.0, 155.0, 210.0)
    page = _process(_page(_spaced_rows((('New', 'York', 'USA'), ('San', 'Jose', 'USA')), xs), [('table', (90, 570, 280, 615))]))
    assert sorted(texts(page)) == ['New York USA', 'San Jose USA'], texts(page)


def test_numeric_values_inside_a_trusted_cell_are_not_split():
    # 两个数值在同一个版面单元格框里（如 “12 34” 是一个格的值）：可信单元格不拆；单元格框横跨的空白也不因数值证据变成列边界。
    xs = (100.0, 160.0)
    page = _process(_page(_spaced_rows((('Code', 'Note'), ('12', '34')), xs),
                          [('table', (90, 570, 280, 615)), ('table_cell', (95, 580, 200, 592))]))
    assert sorted(texts(page)) == ['12 34', 'Code Note'], texts(page)
