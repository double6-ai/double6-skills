"""参考文献条目从残留指标中剔除（2026-10-23，修复 realmodel-r1 评测问题 2：arxiv2501 第 8 页误判）。

只剔除已确认的参考文献条目：位于检测到的 References 标题区域内、具备文献条目结构、按策略保留原文。
含糊内容照常计数：参考文献页上的正文段、只出现 "References" 一词的普通页、看似引用的未翻译正文。
所有用例都调用真实的 render_residue_check，PDF 由 PyMuPDF 按显式坐标生成。阈值不变。
"""
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'tests'))

import render_residue_check as rrc  # noqa: E402
from render_residue_check import check_render_residue  # noqa: E402
from test_rc3_review_round2 import EN_PARA, ZH_PARA, Page, flow, save  # noqa: E402

# 真实论文参考文献页的条目形态（作者-年份、无编号）：其中三条在旧规则下被计数——
# 标题含普通动词（"What language model to train if you have ..."）、无出处的预印本/网页条目。
TITLE_VERB_ENTRY = ('Teven Le Scao, Thomas Wang, Daniel Hesslow, Stas Bekman, M. Saiful Bari, Stella Biderman, '
                    'Hady Elsahar, Niklas Muennighoff, Jason Phang, Ofir Press, Colin Raffel, and Iz Beltagy. 2022. '
                    'What language model to train if you have one million GPU hours? In Proc. Findings of Conf. on '
                    'Empirical Methods in Natural Language Processing (EMNLP-Findings), pages 765-782, Abu Dhabi, UAE.')
NO_VENUE_ENTRY = ('Alec Radford, Jeffrey Wu, Rewon Child, David Luan, Dario Amodei, and Ilya Sutskever. 2019. '
                  'Language models are unsupervised multitask learners.')
NO_VENUE_ENTRY_2 = ('Jianlin Su, Murtadha Ahmed, Yu Lu, Shengfeng Pan, Wen Bo, and Yunfeng Liu. 2024. '
                    'Roformer: Enhanced transformer with rotary position embedding.')
STRONG_ENTRIES = [
    'William Merrill, Jackson Petty, and Ashish Sabharwal. 2024. The illusion of state in state-space models. '
    'In Proc. Int. Conf. on Machine Learning (ICML), Vienna, Austria.',
    'Tomas Mikolov, Martin Karafiat, Lukas Burget, Jan Cernocky, and Sanjeev Khudanpur. 2010. Recurrent neural '
    'network based language model. In Proc. Interspeech, pages 1045-1048, Makuhari, Japan.',
    'Ankur P. Parikh, Oscar Tackstrom, Dipanjan Das, and Jakob Uszkoreit. 2016. A decomposable attention model '
    'for natural language inference. In Proc. Conf. on Empirical Methods in Natural Language Processing (EMNLP), '
    'pages 2249-2255, Austin, TX, USA.',
    'Zhen Qin, Songlin Yang, and Yiran Zhong. 2023. Hierarchically gated recurrent neural network for sequence '
    'modeling. In Proc. Advances in Neural Information Processing Systems (NeurIPS), New Orleans, LA, USA.',
    'Imanol Schlag, Kazuki Irie, and Jurgen Schmidhuber. 2021. Linear Transformers are secretly fast weight '
    'programmers. In Proc. Int. Conf. on Machine Learning (ICML), Virtual only.',
    'Baptiste Roziere, Jonas Gehring, Fabian Gloeckle, Sten Sootla, Itai Gat, and Tal Remez. 2023. Code Llama: '
    'Open foundation models for code. Preprint arXiv:2308.12950.',
]
REF_PAGE = [STRONG_ENTRIES[0], STRONG_ENTRIES[1], STRONG_ENTRIES[2], STRONG_ENTRIES[3], NO_VENUE_ENTRY,
            STRONG_ENTRIES[5], TITLE_VERB_ENTRY, STRONG_ENTRIES[4], NO_VENUE_ENTRY_2]
# 看似引用、但实为正文叙述（作者开头、含年份），且未翻译：必须计数。
CITATION_LIKE_BODY = ('Radford et al. (2019) showed that we can train a much larger model on more data and that '
                      'the model then learns many tasks without any explicit supervision, which is why our method '
                      'is evaluated in the same zero-shot setting throughout the experiments that we describe here.')


def _doc(items_by_page):
    pages = []
    for items in items_by_page:
        page = Page(); y = 50
        for text, font in items:
            y = flow(page, 50, 545, y, [(text, font)])
        pages.append(page)
    return pages


def run(tmp_path, source_pages, target_pages):
    return check_render_residue(save(tmp_path / 's.pdf', _doc(source_pages)), save(tmp_path / 't.pdf', _doc(target_pages)))


def ref_pages(extra_target=None, extra_source=None):
    body_src = [(EN_PARA, 'helv')] * 5
    body_tgt = [(ZH_PARA, 'china-s')] * 5
    refs = [('References', 'hebo')] + [(r, 'helv') for r in REF_PAGE]
    return ([body_src, refs + (extra_source or [])], [body_tgt, refs + (extra_target or [])])


def target_rows(result):
    return result['excluded']['reference_region_entries']['target']


def test_true_reference_list_is_excluded_and_recorded(tmp_path):
    source, target = ref_pages()
    result = run(tmp_path, source, target)
    assert result['severity'] == 'ok' and not result['quality_fail'], result['pages']
    rows = target_rows(result)
    assert rows and all(r['decision'] == 'excluded' for r in rows), rows
    reasons = {r['reason'] for r in rows}
    assert 'strong_entry_title_verbs_waived' in reasons, reasons
    assert 'author_year_sequence' in reasons, reasons
    summary = result['excluded']['reference_exclusion_summary']['target']
    assert summary['excluded_entries'] == len(rows) and summary['counted_entries'] == 0
    assert summary['excluded_words'] > 0 and summary['excluded_words_by_page'].get('2', 0) > 0
    assert summary['by_reason'].get('author_year_sequence', 0) >= 1


def test_body_paragraph_on_references_page_still_counted(tmp_path):
    source, target = ref_pages(extra_source=[(EN_PARA, 'helv')] * 2, extra_target=[(EN_PARA, 'helv')] * 2)
    result = run(tmp_path, source, target)
    counted = [r for r in target_rows(result) if r['decision'] != 'excluded']
    assert counted, target_rows(result)
    page2 = [p for p in result['pages'] if p['page'] == 2][0]
    assert page2['residue_ratio'] > 0.15 and page2['severity'] != 'ok', page2


def test_citation_like_untranslated_body_on_references_page_still_counted(tmp_path):
    source, target = ref_pages(extra_source=[(CITATION_LIKE_BODY, 'helv')] * 3,
                               extra_target=[(CITATION_LIKE_BODY, 'helv')] * 3)
    result = run(tmp_path, source, target)
    counted = [r for r in target_rows(result) if r['decision'] != 'excluded']
    assert len(counted) >= 3, target_rows(result)
    assert all(r['reason'] != 'author_year_sequence' for r in counted)
    assert result['severity'] != 'ok', result['pages']


def test_word_references_on_normal_page_is_not_excluded(tmp_path):
    mention = ('References to earlier systems are given in the appendix, and the model we train here keeps the same '
               'tokenizer, the same optimizer settings and the same evaluation protocol as the baseline that we compare.')
    source = [[(EN_PARA, 'helv')] * 4, [(mention, 'helv')] + [(EN_PARA, 'helv')] * 3]
    target = [[(ZH_PARA, 'china-s')] * 4, [(mention, 'helv')] + [(EN_PARA, 'helv')] * 3]
    result = run(tmp_path, source, target)
    assert result['severity'] == 'high' and result['quality_fail'], result['pages']
    summary = result['excluded']['reference_exclusion_summary']['target']
    assert summary['excluded_entries'] == 0 and summary['excluded_words'] == 0


def test_new_rules_do_not_apply_without_heading(tmp_path):
    """新规则只在 References 标题区域内生效：无标题时同样的条目不会以新理由剔除（沿用原规则）。"""
    body_src = [(EN_PARA, 'helv')] * 5
    body_tgt = [(ZH_PARA, 'china-s')] * 5
    refs = [(r, 'helv') for r in REF_PAGE]
    result = run(tmp_path, [body_src, refs], [body_tgt, refs])
    rows = []
    for side in ('source', 'target'):
        for run_ in result['excluded']['headingless_runs'][side]:
            rows += run_.get('entries_detail') or []
        assert not result['excluded']['reference_region_entries'][side]
    assert all(r['reason'] not in {'author_year_sequence', 'strong_entry_title_verbs_waived'} for r in rows), rows


def test_title_verb_waiver_needs_full_citation_evidence():
    features = {'year': True, 'venue': True}
    assert rrc.title_verb_waiver(TITLE_VERB_ENTRY, ['sentence_like'], True, features)
    assert not rrc.title_verb_waiver(TITLE_VERB_ENTRY, ['sentence_like'], None, features)
    assert not rrc.title_verb_waiver(TITLE_VERB_ENTRY, ['sentence_like'], True, {'year': True, 'venue': False})
    assert not rrc.title_verb_waiver(TITLE_VERB_ENTRY, ['sentence_like', 'metric'], True, features)
    assert not rrc.title_verb_waiver(CITATION_LIKE_BODY, ['sentence_like'], True, features)


def test_author_year_slot_matches_entries_not_narrative():
    assert rrc.author_year_slot(NO_VENUE_ENTRY) and rrc.author_year_slot(NO_VENUE_ENTRY_2)
    assert rrc.author_year_slot(TITLE_VERB_ENTRY)
    # 复审者第 4 轮的叙述段（作者开头、括号年份、低虚词比例）与看似引用的正文不匹配。
    assert not rrc.author_year_slot('Lin, Y. (2024) ran sixty sequence lengths between four thousand and one million '
                                    'tokens on eight GPUs, sweeping chunk sizes and learning rates.')
    assert not rrc.author_year_slot(CITATION_LIKE_BODY)
    # 日期位之后的“题名”过长（实为正文）不匹配；作者段里出现普通小写词不匹配。
    assert not rrc.author_year_slot('Alec Radford. 2019. ' + ' '.join(['Language models learn tasks'] * 9) + '.')
    assert not rrc.author_year_slot('Our results with Radford, 2019. Language models are unsupervised learners.')
