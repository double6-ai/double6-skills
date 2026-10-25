"""PR #25 第十五轮：源准备规范化不能错删有源文证据的真复合词连字符。

只覆盖现有 prepare_paper_source.normalize_pdf_extracted_text / prepare CLI；原生 digital_pdf
后端不调用这个 normalizer，这里不声称、也不新增原生后端的全局去连字符。

成对正负：
- 相邻真复合词：续行片段自身仍带连字符（mixture-|of-experts），或同文档别处行内出现同一
  带连字符词形（self-attention），保留连字符。
- 普通断词：无复合词证据时保持原有拼接（re-|current → recurrent，proces-|sors → processors）。
- 证据矛盾：同文档同时出现带连字符与拼接两种词形，不猜，保留原连字符并计入待审。
- 原有大写 / 缩写保护不变（pre-|LLM、AI-|based），大写开头普通断词仍拼接（Trans-|former）。
不依赖模型、网络或真实密钥。
"""
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

from prepare_paper_source import normalize_pdf_extracted_text  # noqa: E402

# 来自 arxiv-2501.00659（sha256 cd3604e0…）第 6 / 8 页的真实抽取行（review15 冻结 raw-source.txt）。
REAL_EXCERPT = (
    'A contrastive/positive example is the case of “re-\n'
    'current dropout”: early versions of Zaremba et al.\n'
    'Ge et al. (2024)); or the strategy to build mixture-\n'
    'of-experts language models by pre-training com-\n'
    'ponent experts separately.\n'
    '2024. Branch-train-MiX: Mixing expert llms into a\n'
    'mixture-of-experts llm. Preprint arXiv:2403.07816.\n'
    'with recurrent neural network language models\n'
)


def normalize(text):
    # 计数键用 .get 读取，便于同一测试在修复前 b36f 上成对运行（普通断词应同样通过）。
    return normalize_pdf_extracted_text(text)


def test_review15_real_excerpt_keeps_compound_and_repairs_ordinary_wrap():
    new, changes = normalize(REAL_EXCERPT)
    assert 'strategy to build mixture-of-experts language models' in new
    assert 'mixtureof-experts' not in new
    assert 'recurrent dropout' in new
    assert 'by pre-training component experts' in new.replace('\n', ' ')
    assert changes.get('hyphenated_compound_preservations', 0) == 1
    assert changes.get('hyphenated_line_break_review_needed', 0) == 0


def test_continuation_fragment_with_hyphen_is_a_multi_part_compound():
    # 只有续行带连字符这一结构线索（同文档无行内词形）：保留原连字符，但计入待审而不当作已证实。
    new, changes = normalize('a sparse mixture-\nof-experts layer\n')
    assert 'mixture-of-experts layer' in new
    assert changes.get('hyphenated_compound_preservations', 0) == 0
    assert changes.get('hyphenated_line_break_review_needed', 0) == 1


def test_continuation_hyphen_that_may_be_a_dash_is_kept_for_review_not_guessed():
    # NACA 1135 真实抽取：adiabati-|cally-that（续行连字符其实是破折号）。不猜拼接，原样保留并待审。
    new, changes = normalize('take place adiabati-\ncally-that is, without heat\n')
    assert 'adiabati-cally-that' in new
    assert changes.get('hyphenated_compound_preservations', 0) == 0
    assert changes.get('hyphenated_line_break_review_needed', 0) == 1


def test_multi_part_compound_with_attested_pair_is_kept():
    new, changes = normalize('a single-mode-\nsqueezing term and a two-mode-squeezing term\n')
    assert 'a single-mode-squeezing term' in new
    assert changes.get('hyphenated_compound_preservations', 0) == 1


def test_hyphenated_form_attested_elsewhere_in_same_document_is_kept():
    new, changes = normalize('the self-\nattention block.\nEach self-attention head is small.\n')
    assert 'the self-attention block.' in new
    assert 'selfattention' not in new
    assert changes.get('hyphenated_compound_preservations', 0) == 1


@pytest.mark.parametrize('broken,joined', [
    ('re-\ncurrent dropout', 'recurrent dropout'),
    ('proces-\nsors are fast', 'processors are fast'),
    ('the in-\nformation flow', 'the information flow'),
    ('Trans-\nformer layers', 'Transformer layers'),
])
def test_ordinary_wraps_without_compound_evidence_are_still_joined(broken, joined):
    new, changes = normalize(broken + '\n')
    assert joined in new
    assert changes.get('hyphenated_compound_preservations', 0) == 0
    assert changes.get('hyphenated_line_break_review_needed', 0) == 0


def test_ordinary_wrap_is_not_kept_because_of_unrelated_compounds():
    # 文档里有别的复合词（re-ranking、current-limiting），但没有 re-current 这一词形。
    text = 'a re-\ncurrent cell.\nWe use re-ranking and current-limiting.\n'
    new, changes = normalize(text)
    assert 'a recurrent cell.' in new
    assert changes.get('hyphenated_compound_preservations', 0) == 0


def test_conflicting_evidence_keeps_original_hyphen_and_flags_review():
    text = 'they co-\noperate here.\nSome co-operate, others cooperate.\n'
    new, changes = normalize(text)
    assert 'they co-operate here.' in new
    assert changes.get('hyphenated_line_break_review_needed', 0) == 1
    assert changes.get('hyphenated_compound_preservations', 0) == 0


def test_continuation_compound_contradicted_by_joined_word_is_not_guessed():
    # 续行带连字符（像复合词），但同文档又出现拼接词 information：矛盾，保留原样并待审。
    text = 'an in-\nformation-theoretic bound.\nThe information is lost.\n'
    new, changes = normalize(text)
    assert 'an in-formation-theoretic bound.' in new
    assert changes.get('hyphenated_line_break_review_needed', 0) == 1


def test_existing_capital_and_acronym_protection_unchanged():
    new, _ = normalize('the pre-\nLLM era and AI-\nbased tools\n')
    assert 'pre-LLM era' in new
    assert 'AI-based tools' in new


def test_hyphen_counter_semantics_unchanged():
    _, changes = normalize('mod-\nels and mixture-\nof-experts\n')
    assert changes['hyphenated_line_break_repairs'] == 2
    assert changes['changed'] is True


def test_prepare_cli_keeps_compound_from_a_generated_pdf(tmp_path):
    pymupdf = pytest.importorskip('pymupdf')
    pdf = tmp_path / 'compound.pdf'
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        'Ge et al. (2024)); or the strategy to build mixture-',
        'of-experts language models by pre-training com-',
        'ponent experts. A contrastive example is re-',
        'current dropout in early recurrent networks.',
    ]
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 14 * i), line, fontsize=11)
    doc.save(pdf)
    doc.close()
    out = tmp_path / 'prepared'
    subprocess.run(
        [sys.executable, str(SKILL / 'scripts' / 'prepare_paper_source.py'), str(pdf),
         '--no-ocr', '--keep-pdf-noise', '--output-dir', str(out)],
        check=True, timeout=60, capture_output=True,
    )
    text = (out / 'source.md').read_text(encoding='utf-8')
    assert 'strategy to build mixture-of-experts language models' in text
    assert 'mixtureof-experts' not in text
    assert 'recurrent dropout' in text
