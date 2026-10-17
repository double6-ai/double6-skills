"""2.0.0-rc.3 评审修复第三轮：无标题参考文献识别过宽导致的漏判（PR #16 第三次复审）。

复审发现：带人名、年份、编号和指标的英文实验正文被当作“无标题参考文献”整段剔除，源与译文两侧
同样剔除，译文侧上限也拦不住。原则：宁可误报，不可漏判。这里的“模仿”用例都必须计入残留。
"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'tests'))

from render_residue_check import check_render_residue  # noqa: E402
from test_rc3_review_round2 import (AUTHOR_YEAR_REFS, EN_PARA, REFS, ZH_PARA, Page, flow,  # noqa: E402
                                    save)

ZH_INTRO = '本文研究长上下文建模中的测试时训练。我们分析了大块更新的硬件效率，并在语言建模、图像和视频任务上进行实验。'
EN_INTRO = ('This paper studies test-time training for long-context modeling. We analyze the hardware efficiency '
            'of large chunk updates and run experiments on language, image and video tasks with several baselines.')

# 复审者对照 PDF 的复刻：三段编号的实验正文，含研究者姓名、年份、会议名和枚举的指标。
EXPERIMENT_PARAS = [
    '1. Zhang, Wei, and Kumar (2021) reported top-1 accuracy of 84.7% on ImageNet-1K with ResNet-50, '
    'Proc. CVPR, pp. 1120-1129.',
    '2. Garcia, M. and Chen, L. (2022) obtained 41.3 BLEU on WMT14 En-De, NeurIPS 2022, vol. 35, std 0.2.',
    '3. Okafor, Ivanova, and Brown, 2023: F1 of 91.2 on SQuAD v2.0, arXiv:2301.01234, ACL Findings.',
]
FINDINGS_BRACKETED = [
    '[1] In 2020, Brown et al. showed that scaling to 175B parameters raises few-shot accuracy from 45.2% to '
    '71.8% on TriviaQA (NeurIPS).',
    '[2] Hoffmann et al. (2022) trained Chinchilla on 1.4T tokens and matched Gopher with 4x fewer parameters, '
    'ICML 2022, pp. 30016-30030.',
    '[3] Touvron et al. (2023) released Llama 2 models from 7B to 70B, improving MMLU by 6.8 points, arXiv preprint.',
    '[4] Sun, Y., Li, X. (2024) evaluated TTT layers up to 32k context, perplexity 10.2 vs 11.0, ICML Workshop.',
]
AUTHOR_YEAR_PROSE = [
    'Devlin et al. (2019), Liu et al. (2019), Raffel et al. (2020) and Brown et al. (2020) pre-trained Transformer '
    'encoders and decoders on web corpora; Kaplan et al. (2020) and Hoffmann et al. (2022) fit scaling laws (ICLR, NeurIPS).',
    'Schlag, Irie, Schmidhuber (2021), Sun et al. (2024), Yang et al. (2024) and Behrouz et al. (2025) cast linear '
    'attention as fast weights, ICML, NeurIPS, arXiv:2501.00663, pp. 9355-9366.',
    'Gu and Dao (2023), Dao and Gu (2024), Peng et al. (2023) and Orvieto et al. (2023) propose recurrent state '
    'space layers, Proc. ICML, vol. 202, NeurIPS 2023, COLM 2024.',
]
RESULTS_LIST = [
    '1. Smith et al. (2020) achieved 85.2% accuracy on CIFAR-10, NeurIPS 2020, pp. 1-12.',
    '2. Lee, K. and Park, J. (2021) reached 79.4% top-1 on ImageNet, CVPR 2021, pp. 100-110.',
    '3. Kumar et al. (2022) reported 92.1 F1 on CoNLL-2003, ACL 2022, vol. 1, pp. 50-60.',
    '4. Novak, P. (2023) obtained 33.5 BLEU on WMT16 En-Ro, EMNLP 2023, pp. 7-15.',
]
SURNAME_INITIAL_PROSE = [
    'Smith, J. and Lee, K. (2020) proposed a contrastive objective that we adopt here; Wang, H. (2021) extended '
    'it to video, Proc. CVPR 2021, pp. 1-9.',
    'Garcia, M., Chen, L. (2022) were the first to train on 1M tokens, and our setup follows them, NeurIPS 2022, vol. 35.',
    'Okafor, A. (2023) is closest to our method; it has a similar chunk size, ICLR 2023, arXiv:2302.00001.',
]
TABLE_ROWS = [
    '[1] ResNet-50 (He et al., 2016): 76.1 / 92.9, CVPR 2016, pp. 770-778.',
    '[2] ViT-B/16 (Dosovitskiy et al., 2021): 81.8 / 95.6, ICLR 2021, arXiv:2010.11929.',
    '[3] ConvNeXt-T (Liu et al., 2022): 82.1 / 95.9, CVPR 2022, pp. 11976-11986.',
    '[4] Swin-T (Liu et al., 2021): 81.3 / 95.5, ICCV 2021, pp. 10012-10022.',
]
REFS_WITH_PROSE = [r + ' We build directly on this work and reuse its training recipe for all experiments.' for r in REFS[:4]]


def zh_intro_en_tail(tail, *, intro_en=EN_INTRO, two_column=False):
    """源文：英文引言 + 英文尾段；译文：中文引言 + 原样英文尾段（复审者对照 PDF 的结构）。"""
    def doc(intro, font):
        page = Page()
        if two_column:
            flow(page, 50, 290, 50, [(intro, font)] * 2)
            flow(page, 305, 545, 50, [(t, 'helv') for t in tail])
        else:
            y = flow(page, 50, 545, 50, [(intro, font)])
            flow(page, 50, 545, y + 8, [(t, 'helv') for t in tail])
        return [page]
    return doc(intro_en, 'helv'), doc(ZH_INTRO, 'china-s')


def run(tmp_path, source_pages, target_pages):
    return check_render_residue(save(tmp_path / 's.pdf', source_pages), save(tmp_path / 't.pdf', target_pages))


def headingless_words(result):
    return sum(p['excluded_source_breakdown'].get('reference_entries_headingless', 0) for p in result['pages'])


def assert_counted(result):
    assert headingless_words(result) == 0, result['pages']
    assert result['severity'] == 'high' and result['quality_fail'], result['pages']


# ---------- 复现复审者的对照用例 ----------

def test_round3_reviewer_case_numbered_experiment_paragraphs_fail(tmp_path):
    source, target = zh_intro_en_tail(EXPERIMENT_PARAS)
    result = run(tmp_path, source, target)
    assert_counted(result)
    assert result['overall_residue_ratio'] >= 0.4


def test_round3_reviewer_case_two_column_fails(tmp_path):
    source, target = zh_intro_en_tail(EXPERIMENT_PARAS + RESULTS_LIST, two_column=True)
    assert_counted(run(tmp_path, source, target))


# ---------- 模仿参考文献的英文正文：都必须计入 ----------

@pytest.mark.parametrize('tail', [FINDINGS_BRACKETED, AUTHOR_YEAR_PROSE, RESULTS_LIST, SURNAME_INITIAL_PROSE,
                                  TABLE_ROWS * 2, REFS_WITH_PROSE],
                         ids=['bracketed_findings', 'author_year_dense_prose', 'results_list',
                              'surname_initial_prose', 'table_rows', 'refs_with_appended_prose'])
def test_round3_mimic_suite_is_counted(tmp_path, tail):
    source, target = zh_intro_en_tail(tail)
    result = run(tmp_path, source, target)
    assert headingless_words(result) == 0, result['pages']
    # 表格行里的作者-年份引用本身按规则剔除，剩余英文词仍须让该页至少判 medium；其余变体判 high。
    expected = ('medium', 'high') if tail[0].startswith('[1] ResNet') else ('high',)
    assert result['severity'] in expected, result['pages']


def test_round3_mimic_on_last_page_of_long_document_is_counted(tmp_path):
    # 位于文末、正文很长（不触发文档比例上限）时，模仿条目仍须被逐条否决。
    def doc(body, font):
        pages = []
        for _ in range(2):
            page = Page(); flow(page, 50, 545, 50, [(body, font)] * 5); pages.append(page)
        last = Page(); flow(last, 50, 545, 50, [(t, 'helv') for t in EXPERIMENT_PARAS + RESULTS_LIST + FINDINGS_BRACKETED])
        return pages + [last]
    result = run(tmp_path, doc(EN_PARA, 'helv'), doc(ZH_PARA, 'china-s'))
    assert headingless_words(result) == 0, result['pages']
    assert result['pages'][2]['severity'] == 'high'


def test_round3_reference_heading_then_numbered_results_is_counted(tmp_path):
    def doc(intro, font):
        page = Page(); y = flow(page, 50, 545, 50, [(intro, font)])
        y = flow(page, 50, 545, y + 6, [('References', 'hebo')])
        flow(page, 50, 545, y, [(t, 'helv') for t in RESULTS_LIST + EXPERIMENT_PARAS])
        return [page]
    result = run(tmp_path, doc(EN_INTRO, 'helv'), doc(ZH_INTRO, 'china-s'))
    assert sum(p['excluded_source_breakdown'].get('reference_section', 0) for p in result['pages']) <= 2, result['pages']
    assert result['severity'] == 'high'


def test_round3_bibliography_like_list_not_at_end_is_counted(tmp_path):
    # 真正的文献格式列表，但后面还有英文正文（不在文末/节末）：不作无标题参考文献剔除。
    def doc(intro, font):
        page = Page(); y = flow(page, 50, 545, 50, [(intro, font)])
        y = flow(page, 50, 545, y + 8, [(r, 'helv') for r in REFS[:4]])
        flow(page, 50, 545, y + 8, [(intro, font)] * 2)
        return [page]
    result = run(tmp_path, doc(EN_INTRO, 'helv'), doc(ZH_INTRO, 'china-s'))
    assert headingless_words(result) == 0, result['pages']
    runs = result['excluded']['headingless_runs']['source']
    assert runs and runs[0]['reason'] == 'not_at_document_or_section_end', runs
    assert result['severity'] != 'ok'


def test_round3_headingless_refs_dominating_document_are_counted(tmp_path):
    # 无标题“参考文献”占文档英文词一半以上：退回计数（宁可误报），并在 JSON 中记录原因。
    source, target = zh_intro_en_tail(REFS)
    result = run(tmp_path, source, target)
    assert headingless_words(result) == 0, result['pages']
    runs = result['excluded']['headingless_runs']['source']
    assert runs and not runs[0]['accepted'] and runs[0]['reason'] == 'exceeds_document_fraction', runs
    assert result['severity'] == 'high'


def test_round3_inconsistent_left_margin_is_not_a_bibliography(tmp_path):
    def doc(body, font):
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 5)
        second = Page(); y = 50
        for i, r in enumerate(REFS):
            y = flow(second, 50 + (i % 3) * 30, 545, y, [(r, 'helv')])
        return [first, second]
    result = run(tmp_path, doc(EN_PARA, 'helv'), doc(ZH_PARA, 'china-s'))
    assert headingless_words(result) == 0, result['pages']


# ---------- 真正的无标题参考文献仍然通过，且可审计 ----------

@pytest.mark.parametrize('refs', [REFS, AUTHOR_YEAR_REFS], ids=['numbered', 'author_year'])
def test_round3_genuine_headingless_bibliography_still_passes_and_is_audited(tmp_path, refs):
    def doc(body, font):
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 5)
        second = Page(); flow(second, 50, 545, 50, [(r, 'helv') for r in refs])
        return [first, second]
    result = run(tmp_path, doc(EN_PARA, 'helv'), doc(ZH_PARA, 'china-s'))
    assert result['severity'] == 'ok', result['pages']
    runs = result['excluded']['headingless_runs']['source']
    assert len(runs) == 1 and runs[0]['accepted'] and runs[0]['pages'] == [2], runs
    assert runs[0]['entries'] >= 3 and runs[0]['excluded_words'] > 80 and runs[0]['first_entry']
    assert result['excluded']['headingless_runs']['target'][0]['accepted']
