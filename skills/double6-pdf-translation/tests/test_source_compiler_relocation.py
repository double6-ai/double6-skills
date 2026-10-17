"""迁移源码目录只改变来源描述，不得掩盖实际源组件或输入变化。"""
from pathlib import Path
import copy,sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pdf_source_groups import _rebind_compiler_identity

def fixture():
    old={'source_il_ref':{'path':'/source/il.json','sha256':'exact'},
         'implementation_refs':[{'path':'/old/compiler.py','sha256':'old'},
                                {'path':'/old/cache.py','sha256':'old-cache'}]}
    group={'source_origin_refs':copy.deepcopy(old),'components':[{'source':'原始科学内容','immutable':False}]}
    group['source_origin_refs']['implementation_refs']=[{'path':'/new/compiler.py','sha256':'new'},
                                                       {'path':'/new/cache.py','sha256':'new-cache'}]
    return group,old

def test_relocation_retains_current_recompiled_components():
    group,old=fixture();components=copy.deepcopy(group['components'])
    _rebind_compiler_identity(group,old)
    assert group['source_origin_refs']==old
    assert group['components']==components
    group['components'][0]['immutable']=True
    assert group['components']!=components

def test_relocated_input_change_is_rejected():
    group,old=fixture();old['source_il_ref']['sha256']='changed'
    with pytest.raises(ValueError,match='inputs changed'):_rebind_compiler_identity(group,old)

@pytest.mark.parametrize('mutation',['missing','duplicate','unknown'])
def test_relocated_compiler_membership_change_is_rejected(mutation):
    group,old=fixture()
    if mutation=='missing':old['implementation_refs'].pop()
    elif mutation=='duplicate':old['implementation_refs'][1]=old['implementation_refs'][0]
    else:old['implementation_refs'][0]['path']='/old/other.py'
    with pytest.raises(ValueError,match='membership changed'):_rebind_compiler_identity(group,old)
