"""PR #25 review27：独立脚注号之后回到正文基线/字号的逗号不应被锁进脚注公式。

冻结的 4 条断言（review27 test_footnote_separator_portable.py，源快照 sha256 ae2a157f…8d63）在这里用
单段几何夹具（tests/fixtures/footnote_separator，非 pickle、非 PDF）原样移植；其余为边界/相邻控制：
脚注号本身、角标内逗号、数学字体元组、数字引用、公式基字上的角标、下标、同基线小字、行尾、
其后紧跟数学字形、公式布局、调用方字符模式等情形仍保持原保护。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/babeldoc'))
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.styles_and_formulas import StylesAndFormulas  # noqa: E402

FIXTURE = ROOT / 'tests/fixtures/footnote_separator/arxiv2501.00659-p1-footnote1.json'


class _FontMapper:
    """记录真实 FontMapper.has_char 结果的替身（CI 中没有下载字体资源）。"""

    def __init__(self, table):
        self.table = table

    def has_char(self, char):
        return self.table.get(char, True)


def _stage(table=None, **config):
    stage = StylesAndFormulas.__new__(StylesAndFormulas)
    stage.translation_config = NS(**{'formular_font_pattern': None, 'formular_char_pattern': None,
                                     'primary_font_family': None, 'lang_out': 'zh', **config})
    stage.font_mapper = _FontMapper(table or {})
    return stage


def _box(v):
    return il.Box(x=v[0], y=v[1], x2=v[2], y2=v[3])


def _char(row):
    u, *g, font_id, size, vertical, formula_layout_id, char_id = row
    return il.PdfCharacter(pdf_style=il.PdfStyle(font_id=font_id, font_size=size, graphic_state=il.GraphicState()),
                           box=_box(g[:4]), visual_bbox=il.VisualBbox(box=_box(g[4:8])), vertical=vertical,
                           scale=1.0, pdf_character_id=char_id, char_unicode=u, formula_layout_id=formula_layout_id)


def _load():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    compositions = [il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=[_char(r) for r in line]))
                    for line in data['lines']]
    paragraph = il.PdfParagraph(box=_box(data['box']), pdf_paragraph_composition=compositions,
                                xobj_id=data['xobj_id'], debug_id=data['debug_id'],
                                layout_label=data['layout_label'], layout_id=data['layout_id'])
    page = il.Page(page_number=0, pdf_font=[il.PdfFont(font_id=f['font_id'], name=f['name']) for f in data['fonts']],
                   pdf_paragraph=[paragraph])
    return data, page


def classify_original():
    data, page = _load()
    _stage(data['has_char']).process_page_formulas(page)
    p = page.pdf_paragraph[0]
    assert 'LLM-era' in ''.join(c.char_unicode or '' for comp in p.pdf_paragraph_composition
                                for obj in [comp.pdf_formula or comp.pdf_line] if obj for c in obj.pdf_character)
    rows = []
    for c in p.pdf_paragraph_composition:
        kind = 'formula' if c.pdf_formula else 'line' if c.pdf_line else 'other'
        obj = c.pdf_formula or c.pdf_line
        for ch in obj.pdf_character if obj else []:
            if 202 < ch.box.x < 221 and 138 < ch.box.y < 155:
                rows.append({'char': ch.char_unicode, 'kind': kind, 'x': ch.box.x, 'y': ch.box.y,
                             'size': ch.pdf_style.font_size, 'id': ch.pdf_character_id})
    return rows


# ---- 冻结 4 条（原样移植） ----

def test_native_footnote_baseline_comma_is_not_locked_in_marker_formula():
    rows = classify_original()
    comma = next(x for x in rows if x['char'] == ',' and x['id'] == 44)
    assert comma['kind'] != 'formula', comma


def test_native_footnote_number_remains_protected():
    rows = classify_original()
    marker = next(x for x in rows if x['char'] == '1' and x['id'] == 49)
    assert marker['kind'] == 'formula'


def math_tags(text):
    t = _stage()
    style = il.PdfStyle(font_id='M', font_size=10, graphic_state=il.GraphicState())
    chars = [il.PdfCharacter(char_unicode=c, pdf_style=style, box=il.Box(x=i * 6, y=0, x2=i * 6 + 6, y2=10),
                             visual_bbox=il.VisualBbox(box=il.Box(x=i * 6, y=0, x2=i * 6 + 6, y2=10)),
                             pdf_character_id=ord(c), scale=1, advance=6) for i, c in enumerate(text)]
    tagged, _ = t._classify_characters_in_composition(
        il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars)), {'M'}, False, 0)
    return [(c.char_unicode, isformula) for c, isformula, _ in tagged]


def test_math_font_tuple_commas_stay_protected():
    assert all(tag for _, tag in math_tags('(x,y),'))


def test_numeric_citation_commas_stay_protected():
    assert all(tag for _, tag in math_tags('[12–14],'))


# ---- 原段其余字符与整段只变这一处 ----

def test_only_separator_and_its_synthetic_space_leave_marker_formula():
    rows = classify_original()
    kinds = [(r['char'], r['id'], r['kind']) for r in rows if r['y'] < 145]
    assert kinds == [('a', 97, 'line'), ('1', 49, 'formula'), (',', 44, 'line'), (' ', None, 'line'),
                     ('n', 110, 'line')]


# ---- 合成边界：只看几何/字体/公式布局信号，不认具体字符或坐标 ----

BODY, MATH = 'T', 'M'


def _g(u, x, y, size, font=BODY, layout=None, w=None):
    w = w or size * 0.5
    h = size
    return il.PdfCharacter(char_unicode=u, pdf_style=il.PdfStyle(font_id=font, font_size=size,
                           graphic_state=il.GraphicState()), box=il.Box(x=x, y=y, x2=x + w, y2=y + h),
                           visual_bbox=il.VisualBbox(box=il.Box(x=x, y=y, x2=x + w, y2=y + h)),
                           pdf_character_id=None if u == ' ' and size == 0 else ord(u[0]), scale=1, advance=w,
                           formula_layout_id=layout)


def _seq(spec, x0=300.0, y0=500.0):
    """spec: (unicode, role) 列表；role ∈ body/sup/sub/small/math/supcomma/layoutcomma/space。"""
    out, x = [], x0
    for u, role in spec:
        size, y, font, layout = 10.0, y0, BODY, None
        if role == 'sup':
            size, y = 7.0, y0 + 3.6
        elif role == 'supcomma':
            size, y = 7.0, y0 + 3.6
        elif role == 'sub':
            size, y = 7.0, y0 - 2.5
        elif role == 'small':
            size, y = 7.0, y0
        elif role == 'math':
            font = MATH
        elif role == 'layoutcomma':
            layout = 7
        c = _g(u, x, y, size, font, layout)
        if role == 'space':
            c.pdf_character_id = None
        out.append(c)
        x = c.box.x2
    return out


def _tags(spec, formula_fonts=frozenset({MATH}), **config):
    chars = _seq(spec)
    tagged, _ = _stage(**config)._classify_characters_in_composition(
        il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars)), set(formula_fonts), False, 0)
    return [(c.char_unicode, bool(f)) for c, f, _ in tagged]


def _word(text, role='body'):
    return [(c, role) for c in text]


FOOTNOTE = _word('word') + [('*', 'sup'), ('2', 'sup'), (',', 'body'), (' ', 'space')] + _word('next')


def test_generic_superscript_marker_separator_is_text_not_tied_to_glyph_or_position():
    tags = dict(enumerate(_tags(FOOTNOTE)))
    assert tags[4] == ('*', True) and tags[5] == ('2', True)
    assert tags[6] == (',', False) and tags[7] == (' ', False)
    assert not any(f for u, f in _tags(FOOTNOTE)[8:])


def test_multiple_markers_keep_inner_script_comma_and_release_body_separator():
    # ¹,², next：角标字号的内部逗号仍属脚注公式；其后回到正文基线/字号的逗号才是分隔符
    spec = _word('word') + [('1', 'sup'), (',', 'supcomma'), ('2', 'sup'), (',', 'body'), (' ', 'space')] + _word('n')
    tags = _tags(spec)
    assert tags[4:9] == [('1', True), (',', True), ('2', True), (',', False), (' ', False)]


@pytest.mark.parametrize('spec', [
    # 下标后的基线逗号（如 H₂, …）：不是脚注号形态，保持原保护
    _word('H') + [('2', 'sub'), (',', 'body'), (' ', 'space')] + _word('next'),
    # 同基线的小字号（非抬升）：保持原保护
    _word('word') + [('1', 'small'), (',', 'body'), (' ', 'space')] + _word('next'),
    # 行尾逗号（其后无正文字形可证分隔）：保守保持
    _word('word') + [('1', 'sup'), (',', 'body')],
    # 其后紧跟数学字体字形：未知混合，保守保持
    _word('word') + [('1', 'sup'), (',', 'body'), (' ', 'space'), ('x', 'math')],
    # 逗号自带公式布局信号：保持
    _word('word') + [('1', 'sup'), (',', 'layoutcomma'), (' ', 'space')] + _word('next'),
])
def test_marker_comma_without_body_separator_evidence_stays_protected(spec):
    tags = _tags(spec)
    comma_positions = [i for i, (u, _) in enumerate(tags) if u == ',']
    assert tags[comma_positions[-1]][1] is True, tags


def test_math_base_superscript_comma_stays_protected():
    # x² , y：基字本身为数学字体公式，逗号仍属该公式
    spec = [('x', 'math'), ('2', 'sup'), (',', 'body'), (' ', 'space')] + _word('next')
    tags = _tags(spec)
    assert tags[2] == (',', True)


def test_math_font_comma_after_marker_stays_protected():
    spec = _word('word') + [('1', 'sup'), (',', 'math'), (' ', 'space')] + _word('next')
    assert _tags(spec)[5] == (',', True)


def test_caller_char_pattern_comma_stays_protected():
    assert _tags(FOOTNOTE, formular_char_pattern=',')[6] == (',', True)


def test_target_font_without_comma_stays_protected():
    chars = _seq(FOOTNOTE)
    stage = _stage({',': False})
    tagged, _ = stage._classify_characters_in_composition(
        il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars)), {MATH}, False, 0)
    assert bool(tagged[6][1]) is True
