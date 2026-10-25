"""评审22 原P3-5：公式/引用占位符边界的重复分隔符。

受保护公式字面已以逗号结尾（例如 `14],`），源输入中该占位符后没有逗号，回答却在占位符后再写一个
逗号时，恢复后会出现 `[12–14],, offer`。前 5 个用例移植自评审冻结的 test_citation_punctuation.py
（断言不变，只改为读取本仓库无路径夹具）；其余为合成边界：只去掉有源证据的译文侧重复，
公式内部、源文本自带、其它标点、非结尾逗号、富文本均不改动。无模型、网络或渲染。
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'vendor/babeldoc')]
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator import (  # noqa: E402
    PROTECTED_BOUNDARY_DELIMITER_DEDUPLICATED,
    FormulaPlaceholder,
    ILTranslator,
    ParagraphTranslateTracker,
    RichTextPlaceholder,
    dedupe_protected_boundary_delimiters,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import get_paragraph_unicode  # noqa: E402

F = json.loads((SKILL / 'tests/fixtures/zh2en/pr25_review22_citation_comma.json').read_text(encoding='utf-8'))


def formula(text, i, token=None, pattern=None):
    style = il.PdfStyle(font_id='fixed-reconstruction', font_size=10, graphic_state=il.GraphicState())
    chars = [il.PdfCharacter(char_unicode=c, box=il.Box(x=j * 5, y=0, x2=j * 5 + 5, y2=10), pdf_style=style, scale=1, advance=5) for j, c in enumerate(text)]
    return FormulaPlaceholder(i, il.PdfFormula(pdf_character=chars), token or '{v' + str(i) + '}', pattern or r'\{\s*v\s*' + str(i) + r'\s*\}')


def apply(source, output, placeholders, tmp_path):
    t = ILTranslator.__new__(ILTranslator)
    t.translation_config = NS(lang_in='zh', lang_out='en')
    t._formula_placeholder_pattern = re.compile(r'\{\s*v\s*\d+\s*\}', re.I)
    t._style_left_placeholder_pattern = re.compile(r'<style\b[^>]*>', re.I)
    t._style_right_placeholder_pattern = re.compile(r'</style>', re.I)
    style = il.PdfStyle(font_id='fixed-reconstruction', font_size=10, graphic_state=il.GraphicState())
    p = il.PdfParagraph(unicode=source, pdf_style=style, layout_label='plain text', pdf_paragraph_composition=[])
    tracker = ParagraphTranslateTracker()
    tracker.new_llm_translate_tracker()
    inp = ILTranslator.TranslateInput(source, placeholders, style)
    accepted = t.post_translate_paragraph(p, tracker, inp, output)
    restored = get_paragraph_unicode(p) if accepted else None
    audit = {'source': source, 'fixed_output': output, 'accepted': accepted, 'restored': restored,
             'writeback_status': tracker.writeback_status, 'writeback_reason': tracker.writeback_reason,
             'tracker_output': tracker.output, 'placeholders': [x.to_dict() for x in placeholders]}
    (tmp_path / 'PUNCT_AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    return accepted, restored, tracker


def actual_placeholders():
    return [formula(x['formula_chars'], x['id'], x['placeholder'], x['regex_pattern']) for x in F['placeholders']]


# ---------- 冻结 5 项（断言与评审原件一致） ----------

def test_actual_citation_edge_cannot_silently_accept_duplicate_comma(tmp_path):
    assert F['source_citation_last_glyph'] == ','
    assert F['output'].count('{v9}–{v10}, offer') == 1
    assert next(x['formula_chars'] for x in F['placeholders'] if x['id'] == 10) == '14],'
    accepted, text, tracker = apply(F['input'], F['output'], actual_placeholders(), tmp_path)
    assert not accepted or not re.search(r'\[12[–-]14\]\s*,\s*,\s*offer', text), text
    if not accepted:
        assert tracker.writeback_status and tracker.writeback_reason


def test_same_real_answer_without_extra_edge_comma_keeps_source_delimiter(tmp_path):
    out = F['output'].replace('{v9}–{v10}, offer', '{v9}–{v10} offer')
    assert out != F['output']
    ok, text, _ = apply(F['input'], out, actual_placeholders(), tmp_path)
    assert ok
    assert re.search(r'\[12[–-]14\]\s*,\s*offer', text)


def test_mathematical_tuple_and_its_trailing_comma_are_preserved(tmp_path):
    ok, text, _ = apply('考虑 {v1}的后续。', 'Consider {v1} next.', [formula('(x,y),', 1)], tmp_path)
    assert ok and '(x,y),' in text


def test_intentional_double_comma_inside_protected_math_is_not_collapsed(tmp_path):
    ok, text, _ = apply('给定 {v1}表达式。', 'Given {v1} expression.', [formula('f(x,,y)', 1)], tmp_path)
    assert ok and 'f(x,,y)' in text


def test_two_separate_citations_are_not_deduplicated(tmp_path):
    ok, text, _ = apply('参见 {v1}和 {v2}。', 'See {v1} and {v2}.', [formula('[12–14],', 1), formula('[12–14]', 2)], tmp_path)
    assert ok and text.count('[12–14]') == 2 and text.count(',') == 1


# ---------- 新增边界 ----------

def test_actual_answer_is_applied_with_visible_reason_and_raw_answer_kept(tmp_path):
    ok, text, tracker = apply(F['input'], F['output'], actual_placeholders(), tmp_path)
    assert ok and tracker.writeback_status == 'applied'
    assert tracker.writeback_reason == PROTECTED_BOUNDARY_DELIMITER_DEDUPLICATED
    assert tracker.output == F['output']  # 固定回答原样留在 tracking，不改写
    assert not re.search(r',\s*,', text)
    # 每个受保护引用逗号恰好一个；引用身份与数量不变
    for x in F['placeholders']:
        assert x['formula_chars'] in text
    assert text.count('[12–14], offer') == 1


def test_synthetic_split_citation_boundary_comma(tmp_path):
    ph = [formula('[3', 1), formula('5],', 2)]
    ok, text, tracker = apply('前人工作 {v1}–{v2}提供了思路', 'Prior work {v1}–{v2}, offers ideas', ph, tmp_path)
    assert ok and '[3–5], offers' in text and ',,' not in text.replace(' ', '')
    assert tracker.writeback_reason == PROTECTED_BOUNDARY_DELIMITER_DEDUPLICATED


def test_whitespace_between_placeholder_and_answer_comma(tmp_path):
    ok, text, _ = apply('见 {v1}后文', 'See {v1} , then', [formula('[7],', 1)], tmp_path)
    assert ok and '[7], then' in text.replace('  ', ' ') and not re.search(r',\s*,', text)


def test_source_that_already_has_comma_after_placeholder_is_untouched(tmp_path):
    ok, text, tracker = apply('见 {v1}, 后文', 'See {v1}, then', [formula('[7],', 1)], tmp_path)
    assert ok and re.search(r'\[7\],\s*,', text)
    assert tracker.writeback_reason == 'normal'


def test_non_trailing_comma_literal_keeps_answer_comma(tmp_path):
    ok, text, tracker = apply('见 {v1}后文', 'See {v1}, then', [formula('[3, 4]', 1)], tmp_path)
    assert ok and '[3, 4], then' in text and tracker.writeback_reason == 'normal'


def test_other_punctuation_after_protected_comma_is_not_rewritten(tmp_path):
    ok, text, tracker = apply('载体 {v1}如近年来', 'vehicle {v1}. For instance', [formula('[9],', 1)], tmp_path)
    assert ok and '[9],. For' in text and tracker.writeback_reason == 'normal'
    # 全角逗号是另一种标点（替换合同未立），助手不动；get_paragraph_unicode 的 NFKC 只用于抽取比较
    text, removed = dedupe_protected_boundary_delimiters('载体 {v1}如近年来', '载体 {v1}，如近年来', [formula('[9],', 1)])
    assert text == '载体 {v1}，如近年来' and removed == []


def test_literal_ending_in_intentional_double_comma_is_left_alone(tmp_path):
    ok, text, tracker = apply('给定 {v1}表达式', 'Given {v1}, expression', [formula('g(x),,', 1)], tmp_path)
    assert ok and 'g(x),,,' in text.replace(' ', '') and tracker.writeback_reason == 'normal'


def test_placeholder_ids_do_not_alias(tmp_path):
    ph = [formula('[1],', 1), formula('[10]', 10)]
    ok, text, _ = apply('见 {v1}与 {v10}后文', 'See {v1} and {v10}, then', ph, tmp_path)
    assert ok and '[1], and [10], then' in text and text.count(',') == 2


def test_only_the_answer_side_duplicate_is_removed_each_occurrence(tmp_path):
    ok, text, _ = apply('见 {v1}后文 {v1}结尾', 'See {v1}, then {v1}, end', [formula('[2],', 1)], tmp_path)
    assert ok and text.count('[2], ') == 2 and not re.search(r',\s*,', text)


def test_helper_ignores_rich_text_and_missing_formula_chars():
    style = il.PdfStyle(font_id='x', font_size=10, graphic_state=il.GraphicState())
    rich = RichTextPlaceholder(1, il.PdfSameStyleCharacters(pdf_style=style, pdf_character=[]), '<style id="1">', '</style>', r'<style\s*id="1">', r'</style>')
    empty = FormulaPlaceholder(2, il.PdfFormula(pdf_character=[]), '{v2}', r'\{\s*v\s*2\s*\}')
    text, removed = dedupe_protected_boundary_delimiters('a <style id="1">b</style> {v2} c', 'A <style id="1">B,</style>, {v2}, C', [rich, empty])
    assert text == 'A <style id="1">B,</style>, {v2}, C' and removed == []
