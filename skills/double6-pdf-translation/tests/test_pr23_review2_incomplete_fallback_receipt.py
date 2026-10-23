"""独立核不完整排版回执：不能抹掉降级声明后当成没有fallback。"""
import json,sys
from pathlib import Path
import pytest
R=Path(__file__).resolve().parent
S=R.parent
sys.path.insert(0,str(S/'scripts'))
import qa_pipeline as qa
import chunked_translation as ct

@pytest.mark.parametrize('case',['declared_count_without_rows','malformed_json'])
def test_unverifiable_fallback_receipt_blocks_document(tmp_path,case):
    work=tmp_path/'out/_backend_working/c001';work.mkdir(parents=True)
    receipt={'stage':'post_typesetting','status':'needs_review','failures':[],
             'source_fallback_count':4,'source_fallbacks':[],
             'source_fallback_cap':{'count':4,'status':'applied','document_cap_scope':'chunk_merge',
                                    'paragraphs_per_page':{'0':5,'1':5,'2':5,'3':5},'segment_count':20}}
    (work/'typesetting_writeback_report.json').write_text(json.dumps(receipt)if case!='malformed_json'else'{broken')
    audit=qa.audit_overflow_source_fallbacks(tmp_path/'out')
    quality={'status':'unverified','quality_pass':False,'issues':[],
             'pending':audit['pending'],
             'overflow_source_fallback_check':{'count':audit['count'],'receipts':audit['receipts']}}
    result=ct.aggregate_quality([{'chunk':{'id':'c001','start':1,'end':4,'pages':4},'quality':quality}],[])
    (tmp_path/'INCOMPLETE_AUDIT.json').write_text(json.dumps({'case':case,'backend_receipt':receipt if case!='malformed_json'else'{broken','audit':audit,'aggregate':result},ensure_ascii=False,indent=2)+'\n')
    assert result['status']=='fail',result
    assert any(x.get('id')=='overflow_source_fallback_receipt_incomplete'for x in result['issues']),result

def test_valid_zero_fallback_receipt_keeps_ordinary_document(tmp_path):
    work=tmp_path/'out/_backend_working/c001';work.mkdir(parents=True)
    (work/'typesetting_writeback_report.json').write_text(json.dumps({'status':'passed','failures':[],
        'source_fallback_count':0,'source_fallbacks':[],
        'source_fallback_cap':{'count':0,'paragraphs_per_page':{'0':5},'segment_count':5,'document_cap_scope':'chunk_merge'}}))
    audit=qa.audit_overflow_source_fallbacks(tmp_path/'out')
    result=ct.aggregate_quality([{'chunk':{'id':'c001','start':1,'end':1,'pages':1},'quality':{
        'status':'unverified','quality_pass':False,'issues':[],'pending':audit['pending'],
        'overflow_source_fallback_check':{'count':audit['count'],'receipts':audit['receipts']}}}],[])
    assert result['status']=='unverified' and result['overflow_source_fallback_document_cap']['status']=='none'
