"""评审23 P2：源文占位符外已有分隔符（ASCII、全角或其它标点）时，新边界去重不能把回答的
分隔符当成"回答新增"静默删除。前 3 项移植自评审冻结 test_source_boundary_punctuation.py（断言不变），
其余为合成边界：来源未知（源中无该占位符）或任一出现后跟标点时保守保留回答原样。无模型、网络或渲染。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pr25_review22_citation_boundary_comma import apply, formula  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator import (  # noqa: E402
    PROTECTED_BOUNDARY_DELIMITER_DEDUPLICATED,
    dedupe_protected_boundary_delimiters,
)


# ---------- 冻结 3 项（断言与评审原件一致） ----------

def test_source_fullwidth_outer_comma_is_not_proven_answer_only_duplicate(tmp_path):
    source = '参见 {v1}，后文说明。'
    output = 'See {v1}, then the explanation.'
    accepted, text, tracker = apply(source, output, [formula('[7],', 1)], tmp_path)
    assert not accepted or re.search(r'\[7\]\s*,\s*,\s*then', text), text
    if not accepted:
        assert tracker.writeback_status and tracker.writeback_reason


def test_source_ascii_outer_comma_keeps_both_sources(tmp_path):
    accepted, text, _ = apply('参见 {v1}, 后文说明。', 'See {v1}, then the explanation.', [formula('[7],', 1)], tmp_path)
    assert accepted and re.search(r'\[7\]\s*,\s*,\s*then', text), text


def test_source_without_outer_comma_still_deduplicates(tmp_path):
    accepted, text, tracker = apply('参见 {v1}后文说明。', 'See {v1}, then the explanation.', [formula('[7],', 1)], tmp_path)
    assert not accepted or re.search(r'\[7\]\s*,\s*then', text) and not re.search(r',\s*,', text), text
    if not accepted:
        assert tracker.writeback_status and tracker.writeback_reason


# ---------- 新增边界 ----------

def _helper(source, output, literal='[7],'):
    return dedupe_protected_boundary_delimiters(source, output, [formula(literal, 1)])


def test_fullwidth_outer_comma_keeps_answer_unchanged_with_normal_reason(tmp_path):
    ok, text, tracker = apply('参见 {v1}，后文说明。', 'See {v1}, then the explanation.', [formula('[7],', 1)], tmp_path)
    assert ok and tracker.writeback_reason == 'normal' and tracker.writeback_reason != PROTECTED_BOUNDARY_DELIMITER_DEDUPLICATED


def test_other_outer_separators_are_independent_sources():
    for sep in ('、', '；', ';', '：', '。', '﹐', ')', '）'):
        text, removed = _helper(f'参见 {{v1}}{sep}后文', 'See {v1}, then')
        assert text == 'See {v1}, then' and removed == [], sep


def test_whitespace_before_outer_fullwidth_comma_still_counts():
    text, removed = _helper('参见 {v1} ，后文', 'See {v1}, then')
    assert text == 'See {v1}, then' and removed == []


def test_unknown_source_occurrence_is_not_deduplicated():
    text, removed = _helper('参见后文', 'See {v1}, then')
    assert text == 'See {v1}, then' and removed == []


def test_any_occurrence_with_outer_punctuation_blocks_the_whole_placeholder():
    text, removed = _helper('见 {v1}后文，再见 {v1}，结尾', 'See {v1}, then again {v1}, end')
    assert text == 'See {v1}, then again {v1}, end' and removed == []


def test_letters_or_end_of_source_after_placeholder_still_deduplicate():
    for source in ('参见 {v1}后文', '参见 {v1} 后文', 'see {v1} then', '参见 {v1}'):
        text, removed = _helper(source, 'See {v1}, then')
        assert text == 'See {v1} then' and removed == ['{v1}'], source
