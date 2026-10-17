"""完整单元恢复的正反控制；仅用合成输入和合成模型响应。"""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import independent_latex as latex
import latex_unit_review as review
from latex_resume import validate_resume


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return review.ref(path)


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();tex=source/'main.tex'
    tex.write_text(r'\documentclass{article}\date{}\begin{document}A sequence $f$ has \emph{local period} $p$.\end{document}')
    output=tmp_path/'candidate';latex.prepare(tex,output)
    plan=json.loads((output/'latex_plan.json').read_text());unit=plan['units'][0]
    fingerprint=tmp_path/'model.json';save(fingerprint,{'model_id':'synthetic-model','api_contract':'lmstudio_native_chat_v1'})
    monkeypatch.setattr(latex,'service_identity',lambda *a:{'model':'synthetic-model','source':'unit-test fixture; no HTTP'})
    identity=latex.cache_identity(output,plan,unit,'synthetic-model','http://fixture.invalid/v1',fingerprint)
    tokens=latex.TOKEN.findall(unit['masked_text']);assert len(tokens)==4
    good='序列 '+tokens[0]+' 具有 '+tokens[1]+'局部周期'+tokens[2]+' '+tokens[3]+'。'
    bad=good.replace(tokens[0],'TEMP').replace(tokens[3],tokens[0]).replace('TEMP',tokens[3])
    raw={'source_sha256':unit['source_sha256'],'model':'synthetic-model','base_url':'http://fixture.invalid/v1',
         'cache_identity':identity,'response':{'model_instance_id':'synthetic-model','output':[{'type':'message','content':bad}],
         'stats':{'input_tokens':100,'total_output_tokens':40,'reasoning_output_tokens':0}},'quality_accepted':False}
    rawref=save(output/'units'/(unit['id']+'.raw.json'),raw)
    rp=tmp_path/'source-review.json';rr=save(rp,{'unit_source_sha256':unit['source_sha256'],'complete_source_text':unit['source_text'],
        'status':'complete_unit_reviewed','reviewer':'synthetic fixture reviewer','complete_masked_translation_sha256':latex.digest(good)})
    contract={'schema_version':1,'protocol':review.PROTOCOL,'output_directory':str(output),'plan_ref':review.ref(output/'latex_plan.json'),
        'unit_id':unit['id'],'source_unit_sha256':unit['source_sha256'],'failed_raw_ref':rawref,'source_review_ref':rr,
        'model_fingerprint_ref':review.ref(fingerprint),'reviewer':'synthetic fixture reviewer','complete_source_unit_reviewed':True,
        'complete_masked_translation':good}
    cp=tmp_path/'contract.json';save(cp,contract)
    return SimpleNamespace(output=output,plan=plan,unit=unit,good=good,bad=bad,contract=contract,contract_path=cp,review_path=rp,fingerprint=fingerprint)


def test_review_appends_candidate_and_preserves_failed_raw(case):
    before=(case.output/'units'/(case.unit['id']+'.raw.json')).read_bytes()
    result=review.apply_review(case.contract_path)
    assert result['new_model_calls']==0 and result['original_raw_unchanged']
    path=case.output/'units'/(case.unit['id']+'.json');row=json.loads(path.read_text())
    assert row['translation']=='序列 $f$ 具有 \\emph{局部周期} $p$。'
    assert row['status']=='reviewed_complete_unit_candidate' and row['human_accepted'] is False
    assert (case.output/'units'/(case.unit['id']+'.raw.json')).read_bytes()==before
    review.verify_reviewed_unit(case.output,case.plan,case.unit,row)
    with pytest.raises(ValueError,match='already_exists'):review.apply_review(case.contract_path)


@pytest.mark.parametrize('mutation',['source','raw','target','review','fragment','markers'])
def test_changed_or_incomplete_review_is_rejected(case,mutation):
    c=case.contract
    if mutation=='source':c['source_unit_sha256']='0'*64
    elif mutation=='raw':c['failed_raw_ref']['sha256']='0'*64
    elif mutation=='target':c['complete_masked_translation']=case.good+'改动'
    elif mutation=='review':c['source_review_ref']['sha256']='0'*64
    elif mutation=='fragment':c['complete_source_unit_reviewed']=False
    else:c['complete_masked_translation']=case.bad
    save(case.contract_path,c)
    with pytest.raises(ValueError):review.apply_review(case.contract_path)
    assert not(case.output/'units'/(case.unit['id']+'.json')).exists()


def resume_case(case,tmp_path):
    source={'path':str(tmp_path/'source.pdf'),'sha256':'synthetic-fixture'}
    freeze={'input':source,'latex_source':case.plan['input_tex']};fp=tmp_path/'freeze.json';fr=save(fp,freeze)
    prev=tmp_path/'previous.json';save(prev,{'status':'failed','route':'latex_verified','input_ref':source,'freeze_ref':fr,
        'stages':[{'status':'succeeded','operation':'prepare','command':{'argv':['python','prepare','--output',str(case.output)]}}]})
    args=SimpleNamespace(output=case.output,previous_result=prev,previous_result_sha256=latex.file_sha(prev),freeze=fp)
    return args,freeze


def test_resume_requires_exact_failure_and_current_plan(case,tmp_path):
    args,freeze=resume_case(case,tmp_path);assert validate_resume(args,freeze)['unit_count']==1
    args.previous_result.write_text('{}')
    with pytest.raises(ValueError,match='previous_result_changed'):validate_resume(args,freeze)


def test_reviewed_candidate_provenance_is_rechecked_before_compile(case):
    review.apply_review(case.contract_path)
    path=case.output/'units'/(case.unit['id']+'.json');row=json.loads(path.read_text());row['masked_translation']+='另加内容'
    with pytest.raises(ValueError,match='provenance_changed'):review.verify_reviewed_unit(case.output,case.plan,case.unit,row)
