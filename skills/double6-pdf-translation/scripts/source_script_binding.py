"""逐引用使用实际源宿主，生成基线返修计划；缺绑定时阻断。"""
from __future__ import annotations
import copy, hashlib, json, math, unicodedata

FIELDS=('unicode','gid','font','size','color','type','direction','opacity','origin','bbox')
BINDING_FIELDS={'source_id','label','source_script','source_label_indices','target_label_indices','source_host_anchor_index','target_host_anchor_index'}

def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _number(value,minimum,maximum,*,open_minimum=False):
    return (not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
            and (value>minimum if open_minimum else value>=minimum) and value<=maximum)

def _native(g):
    if not isinstance(g,dict) or set(g)!=set(FIELDS):raise ValueError('script_native_complete_fields_required')
    if not isinstance(g['font'],str) or not g['font']:raise ValueError('script_font_identity_missing')
    for key in ('unicode','gid','type'):
        if isinstance(g[key],bool) or not isinstance(g[key],int):raise ValueError('script_native_integer_required')
    if not 0<=g['unicode']<=0x10ffff or 0xd800<=g['unicode']<=0xdfff or g['gid']< -1 or not 0<=g['type']<=3:
        raise ValueError('script_native_identity_invalid')
    for key,counts in (('origin',(2,)),('bbox',(4,)),('direction',(2,)),('color',(1,3))):
        if not isinstance(g[key],(list,tuple)) or len(g[key])not in counts or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in g[key]):
            raise ValueError('script_native_geometry_invalid')
    for key in ('size','opacity'):
        if isinstance(g[key],bool)or not isinstance(g[key],(int,float))or not math.isfinite(g[key]):raise ValueError('script_native_scalar_invalid')
    if g['size']<=0 or not 0<=g['opacity']<=1 or g['bbox'][0]>g['bbox'][2] or g['bbox'][1]>g['bbox'][3]:
        raise ValueError('script_native_scalar_or_bbox_invalid')

def _supported(g):
    if g['gid']<0:raise ValueError('script_bound_glyph_identity_unknown')
    if tuple(g['direction'])!=(1.,0.):raise ValueError('script_rotated_text_requires_adapter')

def _indices(values,count):
    if not isinstance(values,list)or not values or any(isinstance(i,bool)or not isinstance(i,int)or not 0<=i<count for i in values):
        raise ValueError('script_label_indices_invalid')
    if len(set(values))!=len(values)or values!=sorted(values):raise ValueError('script_label_indices_duplicate_or_unordered')
    return values

def _text(glyphs,indices):return ''.join(unicodedata.normalize('NFKC',chr(glyphs[i]['unicode']))for i in indices)

def plan_source_script_bindings(source_native,target_native,bindings,*,required_source_ids,maximum_delta_pt=.2):
    """仅支持横排、字号已正确的逐引用小幅基线修正；调用方另核验实际PDF身份。"""
    if not _number(maximum_delta_pt,0,.2,open_minimum=True):raise ValueError('script_delta_limit_invalid')
    if not isinstance(source_native,list)or not isinstance(target_native,list)or not source_native or not target_native:
        raise ValueError('script_native_inventory_missing')
    if max(len(source_native),len(target_native))>50000:raise ValueError('script_native_count_limit')
    for g in (*source_native,*target_native):_native(g)
    if not isinstance(required_source_ids,list)or not required_source_ids or len(required_source_ids)>256:
        raise ValueError('script_required_source_inventory_missing_or_oversize')
    if any(not isinstance(v,str)or not v for v in required_source_ids)or len(set(required_source_ids))!=len(required_source_ids):
        raise ValueError('script_required_source_inventory_invalid')
    if not isinstance(bindings,list)or len(bindings)!=len(required_source_ids):raise ValueError('script_binding_coverage_incomplete')
    if any(not isinstance(b,dict)or set(b)!=BINDING_FIELDS for b in bindings):raise ValueError('script_binding_schema_invalid')
    if any(not isinstance(b['source_id'],str)or not b['source_id']for b in bindings):raise ValueError('script_binding_source_identity_mismatch')
    if {b['source_id']for b in bindings}!=set(required_source_ids):raise ValueError('script_binding_source_identity_mismatch')
    if len({b['source_id']for b in bindings})!=len(bindings):raise ValueError('script_duplicate_source_binding')
    target_used=set();source_used=set();rows=[];changes=[];hosts=[]
    for binding in bindings:
        source_indices=_indices(binding['source_label_indices'],len(source_native));target_indices=_indices(binding['target_label_indices'],len(target_native))
        if source_used.intersection(source_indices)or target_used.intersection(target_indices):raise ValueError('script_label_owned_by_multiple_bindings')
        source_used.update(source_indices);target_used.update(target_indices)
        sh=_indices([binding['source_host_anchor_index']],len(source_native))[0]
        th=_indices([binding['target_host_anchor_index']],len(target_native))[0]
        if sh in source_indices or th in target_indices:raise ValueError('script_host_is_label')
        hosts.append((sh,th))
        source_host=source_native[sh];target_host=target_native[th]
        for g in(source_host,target_host,*[source_native[i]for i in source_indices],*[target_native[i]for i in target_indices]):_supported(g)
        if chr(source_host['unicode']).isspace()or chr(target_host['unicode']).isspace():raise ValueError('script_host_is_whitespace')
        source_y=source_native[source_indices[0]]['origin'][1];target_y=target_native[target_indices[0]]['origin'][1]
        if any(abs(source_native[i]['origin'][1]-source_y)>.003 for i in source_indices)or any(abs(target_native[i]['origin'][1]-target_y)>.003 for i in target_indices):
            raise ValueError('script_label_not_one_actual_baseline')
        literal=binding['label']
        if not isinstance(literal,str)or not literal:raise ValueError('script_actual_label_text_mismatch')
        query=unicodedata.normalize('NFKC',literal)
        if not query or _text(source_native,source_indices)!=query or _text(target_native,target_indices)!=query:
            raise ValueError('script_actual_label_text_mismatch')
        offset=(source_host['origin'][1]-source_y)/source_host['size']
        if not .05<abs(offset)<.8:raise ValueError('script_source_not_small_supported_script')
        script='superscript'if offset>0 else 'subscript'
        if binding['source_script']!=script:raise ValueError('script_source_category_mismatch')
        ratios=[source_native[i]['size']/source_host['size']for i in source_indices]
        if any(not .3<ratio<.85 for ratio in ratios)or max(ratios)-min(ratios)>.002:
            raise ValueError('script_source_size_ratio_ambiguous')
        for i in target_indices:
            if abs(target_native[i]['size']/target_host['size']-ratios[0])>.002:
                raise ValueError('script_target_size_requires_separate_adapter')
        expected=target_host['origin'][1]-offset*target_host['size'];delta=expected-target_y
        if abs(delta)>maximum_delta_pt:raise ValueError('script_target_delta_exceeds_declared_range')
        for i in target_indices:changes.append({'glyph_index':i,'y_delta_pt':delta,'source_id':binding['source_id']})
        rows.append({'source_id':binding['source_id'],'label':literal,'source_script':script,
            'source_host_anchor_index':sh,'target_host_anchor_index':th,'source_label_indices':list(source_indices),'target_label_indices':list(target_indices),
            'source_actual_normalized_offset':offset,'source_host_size_pt':source_host['size'],
            'target_host_baseline_pt':target_host['origin'][1],'expected_target_label_baseline_pt':expected,'target_y_delta_pt':delta})
    if any(sh in source_used or th in target_used for sh,th in hosts):raise ValueError('script_host_is_another_label')
    plan={'schema_version':1,'rows':rows,'changes':changes,'required_source_ids':list(required_source_ids),
        'source_native_sha256':_digest(source_native),'target_native_sha256':_digest(target_native),
        'maximum_delta_pt':maximum_delta_pt,
        'binding_coverage_complete':True,'median_or_fallback_used':False,'scope':'declared_horizontal_small_script_baseline_only',
        'pdf_identity_and_actual_saved_verification_still_required':True,'quality_pass':False}
    plan['plan_sha256']=_digest(plan)
    return plan

def verify_native_baseline_changes(before,after,plan,*,source_native=None,bindings=None,required_source_ids=None,verification_context=None,coordinate_tolerance_pt=.003):
    """保存后全银行核对，未拥有字形不得因返修而改字号、颜色或坐标。"""
    if not _number(coordinate_tolerance_pt,0,.003):raise ValueError('script_coordinate_tolerance_invalid')
    if not isinstance(before,list)or not isinstance(after,list)or not before or len(before)>50000:
        raise ValueError('script_saved_native_inventory_invalid')
    if len(before)!=len(after):raise ValueError('script_saved_count_changed')
    if not isinstance(plan,dict)or 'plan_sha256'not in plan:raise ValueError('script_plan_identity_missing')
    if _digest({k:v for k,v in plan.items()if k!='plan_sha256'})!=plan['plan_sha256']:
        raise ValueError('script_plan_identity_changed')
    # 外部冻结的源/目标/绑定/范围及计划身份，不能由待验证plan自认证。
    if not _number(plan.get('maximum_delta_pt'),0,.2,open_minimum=True):raise ValueError('script_plan_delta_limit_invalid')
    context_fields={'source_native_sha256','target_native_sha256','bindings_sha256','source_inventory_sha256','plan_sha256'}
    if not isinstance(verification_context,dict)or set(verification_context)!=context_fields:
        raise ValueError('script_external_verification_context_required')
    if any(not isinstance(v,str)or len(v)!=64 or any(c not in '0123456789abcdef'for c in v)for v in verification_context.values()):
        raise ValueError('script_external_verification_identity_invalid')
    actual_context={'source_native_sha256':_digest(source_native),'target_native_sha256':_digest(before),
        'bindings_sha256':_digest(bindings),'source_inventory_sha256':_digest(required_source_ids),'plan_sha256':plan['plan_sha256']}
    if actual_context!=verification_context:raise ValueError('script_external_verification_identity_changed')
    recomputed=plan_source_script_bindings(source_native,before,bindings,required_source_ids=required_source_ids,maximum_delta_pt=plan['maximum_delta_pt'])
    if plan!=recomputed:raise ValueError('script_plan_not_derived_from_frozen_source')
    if _digest(before)!=plan['target_native_sha256']:raise ValueError('script_plan_target_inventory_changed')
    if plan['scope']!='declared_horizontal_small_script_baseline_only'or plan['quality_pass']is not False:
        raise ValueError('script_plan_scope_invalid')
    expected_changes=[{'glyph_index':i,'y_delta_pt':r['target_y_delta_pt'],'source_id':r['source_id']}for r in plan['rows']for i in r['target_label_indices']]
    if expected_changes!=plan['changes']:raise ValueError('script_plan_change_ownership_mismatch')
    changes={}
    for change in plan['changes']:
        i=_indices([change['glyph_index']],len(before))[0];delta=change['y_delta_pt']
        if i in changes or not _number(delta,-plan['maximum_delta_pt'],plan['maximum_delta_pt']):
            raise ValueError('script_plan_change_duplicate_or_invalid')
        changes[i]=delta
    for i,(old,new)in enumerate(zip(before,after)):
        _native(old);_native(new);expected=copy.deepcopy(old)
        if i in changes:
            expected['origin'][1]+=changes[i];expected['bbox'][1]+=changes[i];expected['bbox'][3]+=changes[i]
        for key in FIELDS:
            if i in changes and key in ('origin','bbox'):
                for j,(a,b)in enumerate(zip(expected[key],new[key])):
                    if j in ((1,)if key=='origin'else(1,3)):
                        if abs(a-b)>coordinate_tolerance_pt:raise ValueError('script_saved_coordinate_changed_outside_plan')
                    elif a!=b:raise ValueError('script_saved_coordinate_changed_outside_plan')
            elif expected[key]!=new[key]:raise ValueError('script_saved_native_field_changed:'+key)
    return {'all_saved_bank_native_fields_bound':True,'unowned_fields_unchanged':True,'modified_glyph_count':len(changes),
        'plan_sha256':plan['plan_sha256'],'scope':plan['scope'],'external_source_bindings_and_plan_frozen':True,'source_relation_recomputed':True,'quality_pass':False}
