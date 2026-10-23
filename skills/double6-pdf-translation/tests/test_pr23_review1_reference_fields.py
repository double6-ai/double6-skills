"""PR #23 review-1 P1 修复的相邻正反例：题名动词豁免先证明条目字段结构（作者 / 题名 / 出处），
只对题名字段内的动词放行；作者开头或编号开头的叙述正文照常计数。阈值不变。"""
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests')]

import render_residue_check as rrc  # noqa: E402
from test_rc3_review_round2 import EN_PARA, ZH_PARA, Page, flow, save  # noqa: E402
from test_reference_residue_exclusion import STRONG_ENTRIES, TITLE_VERB_ENTRY  # noqa: E402

NARRATIVE = ('J. Smith trained neural networks during 2024, evaluated multilingual results at ICML, '
             'and reported robust language modeling performance across multiple benchmark datasets, domains, '
             'architectures, tokenizers, context lengths, training schedules, and multilingual evaluation tasks.')
NUMBERED_NARRATIVE = '[7] ' + NARRATIVE
NUMBERED_TITLE_VERB = ('[12] Teven Le Scao, Thomas Wang, Daniel Hesslow, Stas Bekman, M. Saiful Bari, Stella Biderman, '
                       'and Iz Beltagy. What language model to train if you have one million GPU hours? In Proc. Findings '
                       'of EMNLP, pages 765-782, Abu Dhabi, UAE, 2022.')
NUMBERED_REFS = [
    '[1] Ashish Vaswani, Noam Shazeer, Niki Parmar, and Illia Polosukhin. Attention is all you need. In Advances in '
    'Neural Information Processing Systems, volume 30, pages 5998-6008, 2017.',
    '[2] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition. '
    'In Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition, pages 770-778, 2016.',
]


def waived(text):
    veto = rrc.prose_veto(text)
    return rrc.title_verb_waiver(text, veto, rrc.entry_lead(text), rrc.citation_features(text))


def check(tmp_path, refs, tail):
    def doc(translated):
        body = Page(); flow(body, 50, 545, 50, [(ZH_PARA if translated else EN_PARA, 'china-s' if translated else 'helv')] * 5)
        page = Page(); flow(page, 50, 545, 50, [('References', 'hebo')] + [(r, 'helv') for r in refs] + [(t, 'helv') for t in tail])
        return [body, page]
    return rrc.check_render_residue(save(tmp_path / 's.pdf', doc(False)), save(tmp_path / 't.pdf', doc(True)))


def test_entry_fields_split_real_entries():
    f = rrc.entry_fields(TITLE_VERB_ENTRY)
    assert f['style'] == 'author_year' and f['title'].startswith('What language model') and f['title'].endswith('?')
    assert f['rest'].startswith('2022') and 'Proc.' in f['rest']
    f = rrc.entry_fields(NUMBERED_TITLE_VERB)
    assert f['style'] == 'author_title' and f['authors'].endswith('and Iz Beltagy')
    assert rrc.entry_fields(NUMBERED_REFS[0])['title'] == 'Attention is all you need.'


def test_entry_fields_reject_narratives():
    assert rrc.entry_fields(NARRATIVE) is None
    assert rrc.entry_fields(NUMBERED_NARRATIVE) is None
    assert rrc.entry_fields('[12] J. Smith. Trained networks in 2024 at ICML. Then reported robust performance.') is None


def test_waiver_only_for_verbs_inside_title_field():
    assert waived(TITLE_VERB_ENTRY) and waived(NUMBERED_TITLE_VERB)
    assert not waived(NARRATIVE) and not waived(NUMBERED_NARRATIVE)
    # 题名之外出现谓语（出处字段里写了叙述）不放行。
    assert not waived('[3] J. Smith and A. Lee. What models learn. In ICML, 2024, and evaluated it on many tasks.')


def test_numbered_narrative_on_references_page_stays_counted(tmp_path):
    result = check(tmp_path, NUMBERED_REFS, [NUMBERED_NARRATIVE] * 3)
    rows = result['excluded']['reference_region_entries']['target']
    counted = [r for r in rows if r['decision'] != 'excluded']
    assert len(counted) == 3 and all(r['reason'] != 'strong_entry_title_verbs_waived' for r in counted), rows
    assert result['quality_fail'] and result['severity'] == 'high', result['pages']


def test_numbered_title_verb_entry_on_references_page_excluded(tmp_path):
    result = check(tmp_path, NUMBERED_REFS + [NUMBERED_TITLE_VERB], [])
    rows = result['excluded']['reference_region_entries']['target']
    assert any(r['reason'] == 'strong_entry_title_verbs_waived' and r['decision'] == 'excluded' for r in rows), rows
    assert all(r['decision'] == 'excluded' for r in rows), rows
