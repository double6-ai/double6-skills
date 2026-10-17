"""流式身份必须与既有canonical字节一致，并保留磁盘/内存篡改拒绝。"""
import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pdf_source_groups as groups
import pdf_source_cache as cache

@pytest.mark.parametrize('value',[{'数学':'α≤β','n':[1,-0.0,True,None,{'z':'\\n\"'}]},[],{'letters':'𝕏汉字'*10000},'原字符串',{'tuple':(1,2)}])
def test_streaming_digest_preserves_canonical_bytes(value):
    text=value if isinstance(value,str)else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    assert groups.digest(value)==hashlib.sha256(text.encode()).hexdigest()

def test_nonfinite_is_rejected():
    with pytest.raises(ValueError):groups.digest({'x':float('nan')})

@pytest.fixture
def ledger_cache(tmp_path,monkeypatch):
    ledger={'groups':[{'group_id':'G1','marker':'original'}]};ledger['source_ledger_sha256']=groups.digest(ledger)
    path=tmp_path/'ledger.json';path.write_text(json.dumps(ledger));obj=cache.GroupProjectionCache.__new__(cache.GroupProjectionCache)
    obj.ledger=ledger;obj._original_ledger_digest=ledger['source_ledger_sha256'];obj.context={'source_ledger_ref':cache.file_ref(path)};obj.groups={'G1':ledger['groups'][0]};obj.identity='fixture'
    monkeypatch.setattr(groups,'build_group_input',lambda g:{'source_literal':'A sequence '+g['marker'],'system_control':'Translate the complete source'})
    return obj,path

def test_unchanged_ledger_request_passes(ledger_cache):
    obj,path=ledger_cache;assert obj.group_request('G1')['source_literal']=='A sequence original'
    path.touch();assert obj.group_request('G1')['source_literal']=='A sequence original'

def test_resigned_memory_mutation_is_rejected(ledger_cache):
    obj,_=ledger_cache;obj.ledger['groups'][0]['marker']='changed'
    obj.ledger['source_ledger_sha256']=groups.digest({k:v for k,v in obj.ledger.items()if k!='source_ledger_sha256'})
    with pytest.raises(ValueError,match='caller changed'):obj.group_request('G1')

def test_disk_replacement_is_rejected(ledger_cache):
    obj,path=ledger_cache;path.write_text('{}')
    with pytest.raises(ValueError,match='caller changed'):obj.group_request('G1')
