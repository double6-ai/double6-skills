"""独立真实PDF反例：References区里的作者开头叙述句不能作为参考文献题名剔除。"""
import sys,json,importlib.util
from pathlib import Path
R=Path(__file__).resolve().parent
S=R.parent
sys.path[:0]=[str(S/'scripts'),str(S/'tests')]
import render_residue_check as current
from test_rc3_review_round2 import Page,flow,save,EN_PARA,ZH_PARA
from test_reference_residue_exclusion import STRONG_ENTRIES,TITLE_VERB_ENTRY
NARRATIVE=('J. Smith trained neural networks during 2024, evaluated multilingual results at ICML, '
           'and reported robust language modeling performance across multiple benchmark datasets, domains, '
           'architectures, tokenizers, context lengths, training schedules, and multilingual evaluation tasks.')

def pages(translated=False):
    body=Page();flow(body,50,545,50,[(ZH_PARA if translated else EN_PARA,'china-s' if translated else 'helv')]*5)
    refs=Page();items=[('References','hebo'),(STRONG_ENTRIES[0],'helv'),(STRONG_ENTRIES[1],'helv')]
    items += [(NARRATIVE,'helv')]*3
    flow(refs,50,545,50,items)
    return [body,refs]

def test_reference_region_narrative_stays_counted(tmp_path):
    source=save(tmp_path/'source.pdf',pages())
    target=save(tmp_path/'target.pdf',pages(translated=True))
    spec=importlib.util.spec_from_file_location('baseline_residue',S/'tests/fixtures/pr23_review1/baseline_render_residue_check.py')
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    before=baseline.check_render_residue(source,target)
    after=current.check_render_residue(source,target)
    (tmp_path/'REFERENCE_AUDIT.json').write_text(json.dumps({'narrative':NARRATIVE,'before':before,'after':after},ensure_ascii=False,indent=2)+'\n')
    assert before['quality_fail'] and before['severity']=='high',before['pages']
    assert after['quality_fail'] and after['severity']=='high',after['pages']

def test_real_title_verb_entry_remains_excluded(tmp_path):
    p=Page();flow(p,50,545,50,[('References','hebo'),(STRONG_ENTRIES[0],'helv'),(TITLE_VERB_ENTRY,'helv')])
    doc=save(tmp_path/'true-references.pdf',[p])
    result=current.check_render_residue(doc,doc)
    rows=result['excluded']['reference_region_entries']['target']
    assert any(x['reason']=='strong_entry_title_verbs_waived' and x['decision']=='excluded' for x in rows),rows
