"""分块不能把整份文档的原文降级上限重置为每块一个最低额度。"""
import sys,json
from pathlib import Path
R=Path(__file__).resolve().parent
S=R.parent
sys.path[:0]=[str(S/'scripts'),str(S/'vendor/babeldoc')]
import chunked_translation as ct
from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf

def test_merged_document_must_enforce_document_fallback_cap(tmp_path):
    chunks=[];chunk_caps=[]
    for i in range(2):
        cap=osf.cap_violations([0,1,2,3],{0:5,1:5,2:5,3:5})
        assert not cap['violations'] and cap['document_cap']==4
        chunk_caps.append(cap)
        quality={'status':'unverified','quality_pass':False,'issues':[],
                 'pending':[{'id':'overflow_source_fallback','rule':'overflow_source_fallback',
                             'count':4,'pages':[1,2,3,4]}]}
        chunks.append({'chunk':{'id':f'c{i+1:03d}','start':i*4+1,'end':i*4+4},'quality':quality})
    expected=osf.cap_violations(list(range(8)),{i:5 for i in range(8)})
    assert expected['document_cap']==4 and expected['violations'][0]['scope']=='document'
    actual=ct.aggregate_quality(chunks,[])
    (tmp_path/'DOCUMENT_CAP_AUDIT.json').write_text(json.dumps({'chunk_caps':chunk_caps,'whole_document_cap':expected,'actual_aggregate':actual},ensure_ascii=False,indent=2)+'\n')
    assert actual['status']=='fail',actual
