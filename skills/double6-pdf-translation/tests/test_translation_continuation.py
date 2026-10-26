"""续译行为：局部问题不扩大为整篇失败，严重故障停止，正式正文不插说明。"""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from urllib.error import HTTPError

import fitz
import pytest

S=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(S/'scripts'),str(S/'vendor/babeldoc'),str(S/'vendor/pdfmathtranslate_next')]
import translation_continuation as continuation
import ocr_local_preservation as local


def fixture(tmp_path,n=3):
    source=tmp_path/'source.pdf'
    with fitz.open() as doc:
        for i in range(n):
            page=doc.new_page(width=400,height=500)
            page.insert_textbox(fitz.Rect(30,40,370,460),f'Page {i+1}. '+('This paragraph contains reliable source text for translation and ordinary reading. '*8),fontsize=12)
        doc.save(source)
    args=NS(input=source,output=tmp_path/'out',receipts=None,model='unit-model',base_url='http://127.0.0.1:1234/v1',
            target_language='zh',local_max_concurrency=2,resume=False,
            resource_limits={'task_rss_bytes':5*1024**3,'per_job_seconds':120,'memory_metric':'rss','max_total_fraction':.25})
    return args


def fake_worker(calls,fail=None,fatal=None):
    def worker(source,directory,args,closure):
        calls.append(args.document_page)
        if args.document_page==fatal:
            return {'status':'original_preserved','issues':['auth'],'fatal':'provider_authentication_failed'}
        if args.document_page==fail:
            return {'status':'original_preserved','issues':['whole_job_deadline_exceeded']}
        directory.mkdir(parents=True)
        target=directory/'mono.pdf'
        with fitz.open() as d:
            p=d.new_page(width=400,height=500);p.insert_text((30,60),f'Translated page {args.document_page}');d.save(target)
        return {'status':'translated','issues':[],'target':continuation.reference(target)}
    return worker


def test_bad_middle_page_preserves_source_and_later_page_translates(tmp_path):
    args=fixture(tmp_path);calls=[]
    result=continuation.run(args,page_runner=fake_worker(calls,fail=2))
    assert calls==[1,2,3]
    assert result['status']=='completed_with_warnings' and result['original_preserved_pages']==1
    assert result['translated_pages']==2 and result['translation_complete'] is False
    with fitz.open(result['translated_pdf']['path']) as doc:
        assert len(doc)==3 and 'Translated page 3' in doc[2].get_text()
        assert 'Page 2.' in doc[1].get_text()
        assert all('warning' not in p.get_text().lower() for p in doc)


def test_resume_retries_only_failed_page_and_revalidates_saved_output(tmp_path):
    args=fixture(tmp_path);continuation.run(args,page_runner=fake_worker([],fail=2))
    args.resume=True;calls=[]
    result=continuation.run(args,page_runner=fake_worker(calls))
    assert calls==[2] and result['status']=='completed'
    saved=Path(result['pages'][0]['target']['path']);saved.write_bytes(b'changed')
    calls=[];result=continuation.run(args,page_runner=fake_worker(calls))
    assert calls==[1] and result['status']=='completed'


def test_changed_resume_settings_create_new_run_instead_of_blocking(tmp_path):
    args=fixture(tmp_path);first=continuation.run(args,page_runner=fake_worker([]))
    args.resume=True;args.model='changed-model';calls=[]
    result=continuation.run(args,page_runner=fake_worker(calls))
    assert calls==[1,2,3] and result['status']=='completed'
    assert result['output']!=first['output'] and Path(first['translated_pdf']['path']).is_file()


def test_fatal_authentication_stops_scheduling_and_saves_progress(tmp_path):
    args=fixture(tmp_path);calls=[];result=continuation.run(args,page_runner=fake_worker(calls,fatal=2))
    assert calls==[1,2] and result['status']=='blocked'
    assert result['error_code']=='provider_authentication_failed'
    assert len(json.loads(Path(result['state']).read_text())['pages'])==2


def test_zero_translated_pages_never_claims_success(tmp_path):
    args=fixture(tmp_path,1);result=continuation.run(args,page_runner=fake_worker([],fail=1))
    assert result['status']=='blocked' and result['error_code']=='no_pages_translated'
    assert result['translated_pages']==0 and result['translation_complete'] is False
    assert result['translated_pdf'] is None
    assert Path(result['preserved_pdf']['path']).name=='原文保留稿.pdf'


def test_completed_resume_does_not_require_model_online(tmp_path,monkeypatch):
    import paper_translation_workflow as workflow
    args=fixture(tmp_path,1);continuation.run(args,page_runner=fake_worker([]));args.resume=True
    def no_probe(*a,**kw):raise AssertionError('completed resume must not probe the model')
    monkeypatch.setattr(workflow,'doctor',no_probe)
    result=continuation.run(args)
    assert result['status']=='completed'


def test_page_resource_limit_local_but_unconfirmed_cleanup_global():
    assert continuation.fatal_reason({}, {'stop_reason':'task_memory_limit','cleanup':{'confirmed':True}}) is None
    assert continuation.fatal_reason({}, {'cleanup':{'confirmed':False}})=='owned_tree_cleanup_unconfirmed'
    assert continuation.fatal_reason({}, {'stop_reason':'system_memory_pressure'})=='system_memory_pressure'
    assert continuation.fatal_reason({'message':'HTTP 401 unauthorized'}, {})=='provider_authentication_failed'
    assert continuation.fatal_reason({'message':'see page 401 of the source'}, {}) is None
    assert continuation.fatal_reason({'message':'Unknown model unit-absent'}, {})=='configured_model_unavailable'


def test_inventory_missing_endpoint_warns_but_authentication_still_blocks(monkeypatch):
    import paper_translation_workflow as workflow
    monkeypatch.setenv('LOCAL_TRANSLATION_API_KEY','SYNTHETIC-TEST-ONLY')
    monkeypatch.setattr(workflow,'snapshot',lambda *a,**kw:{'codex':[],'total':32*1024**3,'available':20*1024**3,'swap_used':0})
    def http404(*a,**kw):raise HTTPError('https://example.invalid/models',404,'missing',{},None)
    monkeypatch.setattr(workflow.urllib.request,'urlopen',http404)
    assert not workflow.doctor('https://example.invalid','unit',permissive_inventory=True)['blockers']
    assert workflow.doctor('https://example.invalid','unit')['blockers']
    def http401(*a,**kw):raise HTTPError('https://example.invalid/models',401,'unauthorized',{},None)
    monkeypatch.setattr(workflow.urllib.request,'urlopen',http401)
    assert workflow.doctor('https://example.invalid','unit',permissive_inventory=True)['blockers']


def line(key,text,cls='text',math=False):
    return {'key':[*key,1],'text':text,'class':cls,'math':math,'bbox_px':[10,key[1]*30,100,key[1]*30+20]}


def test_unreliable_line_preserves_whole_source_paragraph_not_half_sentence():
    rows=[line([1,1],'reliable start'),line([1,1],'uncertain ending','uncertain'),line([1,2],'next reliable paragraph')]
    record={'findings':[{'code':'ocr_low_confidence','severity':'error'}]}
    selected=local.select_lines(record,rows,[],[])
    assert selected==[rows[2]] and record['findings']==[]
    assert record['preserved_regions'][0]['source_ocr_for_review_only']=='reliable start\nuncertain ending'
    assert record['warnings'][0]['action']=='preserve_local_source_and_continue'


def test_unlocatable_formula_or_table_remains_page_fallback():
    rows=[line([1,1],'body')]
    record={'findings':[{'code':'ocr_table_unsupported'}]};before=copy.deepcopy(record)
    assert local.select_lines(record,rows,[],[]) is None and record==before
    record={'findings':[{'code':'ocr_formula_unsupported'}]}
    assert local.select_lines(record,rows,[],[{'bar':'unknown geometry'}]) is None


def test_protected_source_residue_is_exempt_only_inside_bound_region():
    regions=[{'bbox_px':[20,20,50,50]}]
    assert local.residue_is_preserved({'left':25,'top':25,'width':10,'height':10},regions)
    assert not local.residue_is_preserved({'left':80,'top':80,'width':10,'height':10},regions)


def test_target_cannot_overprint_preserved_original_region(tmp_path):
    directory=tmp_path/'output';directory.mkdir();p=directory/'page.no_watermark.en.mono.pdf'
    with fitz.open() as d:
        page=d.new_page();page.insert_text((30,60),'Translation');d.save(p)
    manifest={'render_dpi':72,'pages':[{'preserved_regions':[{'bbox_px':[20,30,150,70]}]}]}
    target,error=continuation.usable_candidate(directory,manifest)
    assert target is None and error=='translated_text_over_preserved_source'


def test_white_background_cannot_erase_preserved_source(tmp_path):
    directory=tmp_path/'output';directory.mkdir();source=tmp_path/'rebuilt.pdf'
    with fitz.open() as d:
        page=d.new_page();page.draw_rect(fitz.Rect(20,30,150,70),color=(0,0,0),fill=(0,0,0));d.save(source)
    target=directory/'page.no_watermark.en.mono.pdf'
    with fitz.open() as d:
        page=d.new_page();page.insert_text((30,200),'Translation away from preserved area');d.save(target)
    manifest={'render_dpi':72,'reconstructed_source':continuation.reference(source),
              'pages':[{'preserved_regions':[{'bbox_px':[20,30,150,70]}]}]}
    p,error=continuation.usable_candidate(directory,manifest)
    assert p is None and error=='preserved_source_damaged'
