"""扫描显示区域的显式同类参数及全输入成员核验；源角色接受由独立QA负责。"""
from pathlib import Path
import hashlib,math

def validate_uniform_typography(input_pdf, regions):
    active=[r for r in regions if r.get('status')=='translated' and r.get('in_destroke_mask')]
    if not any('uniform_typography' in r for r in regions):return {}
    ids=[r.get('region_id')for r in regions]
    if any(not isinstance(i,str)or not i for i in ids)or len(ids)!=len(set(ids)):
        raise ValueError('uniform_typography_region_identity_invalid')
    source={'path':str(Path(input_pdf).resolve()),'sha256':hashlib.sha256(Path(input_pdf).read_bytes()).hexdigest()}
    policies={};classes={};evidence_cache={}
    for r in active:
        p=r.get('uniform_typography')
        if not isinstance(p,dict):raise ValueError('uniform_typography_scope_incomplete')
        cid=p.get('class_id');members=p.get('member_ids')
        if not isinstance(cid,str)or not cid or not isinstance(members,list)or any(not isinstance(i,str)or not i for i in members)or len(members)!=len(set(members)):
            raise ValueError('uniform_typography_class_invalid')
        fs=p.get('font_size_pt');step=p.get('baseline_step_pt')
        if any(isinstance(v,bool)or not isinstance(v,(float,int))or not math.isfinite(v)for v in (fs,step))or not 3<=fs<=40 or not 1<=step/fs<=3:
            raise ValueError('uniform_typography_parameters_invalid')
        if p.get('source_ref')!=source:raise ValueError('uniform_typography_source_identity_changed')
        ref=p.get('role_evidence_ref')
        if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:raise ValueError('uniform_typography_role_evidence_missing')
        key=(ref['path'],ref['sha256'])
        if key not in evidence_cache:
            f=Path(ref['path'])
            if not f.is_file()or hashlib.sha256(f.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('uniform_typography_role_evidence_changed')
            evidence_cache[key]=True
        comparable=(float(fs),float(step),tuple(sorted(members)),key)
        if cid in classes and classes[cid]!=comparable:raise ValueError('uniform_typography_class_not_uniform')
        classes[cid]=comparable;policies[r['region_id']]=p
    for cid,p in classes.items():
        actual=sorted(r['region_id']for r in active if r['uniform_typography']['class_id']==cid)
        if actual!=list(p[2]):raise ValueError('uniform_typography_class_membership_incomplete')
    return policies
