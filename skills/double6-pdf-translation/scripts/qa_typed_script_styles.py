"""五类脚本样式：现场核对冻结实例，普通几何重算，有限审校结论按原范围继承。"""
from collections import Counter
import json
import inspect,sys
from pathlib import Path
import fitz
from qa_source_contract import file_ref, read_bound_json
from native_line_spacing import glyphs
from source_script_local_adapter import audit_local_binding

ROUTES = {'ordinary_0.001', 'finite_typographic_adaptation', 'intrinsic_font_and_ink',
          'semantic_rendering', 'composite_fraction'}

def _index(rows):
    if not isinstance(rows,list) or len(rows)>2048:
        raise ValueError('typed_style_item_budget')
    out={r['id']:r for r in rows}
    if len(out)!=len(rows):raise ValueError('typed_style_duplicate_id')
    return out

def _identity(value, manifest):
    if any(value.get(k)!=manifest[k] for k in ('source','target','standard','reviewer_id')):
        raise ValueError('typed_independent_evidence_identity_changed')
    if value.get('producer_id')==manifest['reviewer_id']:
        raise ValueError('typed_style_review_not_independent')
    return value

def verify_loaded_adapter():
    """冻结文件和实际调用函数必须来自同一文件；同名模块不能替代它。"""
    if Path(inspect.getfile(audit_local_binding)).resolve()!=Path(__file__).with_name('source_script_local_adapter.py').resolve():
        raise ValueError('typed_loaded_adapter_outside_frozen_runtime')

def load_typed_plan(scope, freeze, *, source_ref, target_ref, standard_ref, expected_pages):
    """只读已接受证据，不自行生成审校范围或扩大容差。"""
    m=read_bound_json(scope['typed_routes_ref'])
    expected={'source':source_ref,'target':target_ref,'standard':standard_ref,
              'reviewer_id':freeze['reviewer_id']}
    if any(m.get(k)!=v for k,v in expected.items()) or m.get('pages')!=expected_pages:
        raise ValueError('typed_manifest_identity_or_pages_changed')
    for name in ('qa_typed_script_styles.py','source_script_local_adapter.py'):
        if m['runtime_refs'].get(name)!=file_ref(Path(__file__).with_name(name)):
            raise ValueError('typed_style_runtime_changed')
    # 核对实际调用函数的来源，不能只核对一个未被加载的同名文件。
    verify_loaded_adapter()
    functions={'qa_source_contract.py':[file_ref,read_bound_json],
               'native_line_spacing.py':[glyphs],
               'source_script_binding.py':[audit_local_binding.__globals__[name] for name in ('_native','_indices','_number')]}
    for name,loaded in functions.items():
        identity=m['runtime_refs'][name]
        if file_ref(identity['path'])!=identity:
            raise ValueError('typed_loaded_dependency_file_changed')
        for function in loaded:
            if Path(inspect.getfile(function)).resolve()!=Path(identity['path']).resolve():
                raise ValueError('typed_loaded_dependency_outside_frozen_runtime:'+name)
    entry=sys.modules.get('qa_script_styles')
    if entry is not None and Path(inspect.getfile(entry.audit_packet_script_styles)).resolve()!=Path(__file__).with_name('qa_script_styles.py').resolve():
        raise ValueError('typed_loaded_entry_outside_frozen_runtime')
    def evidence(key):return _identity(read_bound_json(m[key]),m)
    summary=evidence('acceptance_ref')
    source_scope=evidence('source_scope_ref')
    if (summary.get('finite_style_scope_status')!='pass' or summary['source_scope_ref']!=m['source_scope_ref'] or
        source_scope.get('source_scope_membership_status')!='pass' or
        source_scope.get('source_scope_independently_frozen') is not True or
        source_scope.get('method')!='source_first' or source_scope.get('pages')!=expected_pages):
        raise ValueError('typed_style_complete_independent_scope_not_accepted')
    candidates=read_bound_json(source_scope['candidate_ref'])
    if any(candidates.get(k)!=m[k] for k in ('source','target','standard')):
        raise ValueError('typed_style_candidate_identity_changed')
    rows=_index(candidates['rows']); decisions=_index(summary['decisions'])
    accepted=_index(source_scope['decisions']); executed=_index(scope['items'])
    if not rows or rows.keys()!=decisions.keys() or rows.keys()!=accepted.keys() or rows.keys()!=executed.keys():
        raise ValueError('typed_style_complete_item_set_changed')
    members=read_bound_json(scope['source_members_ref'])
    if members.get('independent_source_scope_ref')!=m['source_scope_ref']:
        raise ValueError('typed_member_manifest_not_bound_to_independent_scope')
    required=sorted([[a['page'],i] for a in accepted.values() for i in a['source_label_indices']]+[
        [a['page'],i] for a in source_scope['excluded_source_items'] for i in a['indices']])
    if sorted(members['required_members'])!=required or members['excluded_source_items']!=source_scope['excluded_source_items']:
        raise ValueError('typed_complete_source_members_or_exclusions_changed')
    for key,row in rows.items():
        a=accepted[key];e=executed[key];d=decisions[key]
        if a.get('source_membership_decision')!='pass' or d.get('decision')!='pass' or d.get('route') not in ROUTES:
            raise ValueError('typed_style_item_or_route_not_accepted')
        for field in ('page','source_label_indices','source_host_anchor_index','source_script'):
            if e[field]!=a[field]:raise ValueError('typed_actual_scope_binding_changed:'+key)
        if row['page']!=a['page'] or row['source_label_indices']!=a['source_label_indices'] or row.get('complete_owner_id')!=d.get('complete_owner_id'):
            raise ValueError('typed_candidate_binding_or_complete_owner_changed:'+key)
        if e['normalized_tolerance']!=.001 or e['size_ratio_tolerance']!=.001:
            raise ValueError('ordinary_tolerance_must_remain_0.001')
    policy=evidence('ordinary_policy_ref'); measurements=_index(policy['measurements'])
    if {k:policy['approved_finite_measurement_policy'][k] for k in ('normalized_tolerance','size_ratio_tolerance')}!={
        'normalized_tolerance':.001,'size_ratio_tolerance':.001}:
        raise ValueError('typed_ordinary_policy_changed')
    finite=_index(evidence('typography_ref')['decisions'])
    for key,v in _index(evidence('typography_overlay_ref')['decisions']).items():
        if key not in finite or finite[key].get('finite_typographic_adaptation_decision')!='unverified':
            raise ValueError('typed_typography_overlay_outside_unknown_scope')
        finite[key]=v
    intrinsic=_index(evidence('intrinsic_ref')['decisions'])
    semantic=_index(evidence('semantic_ref')['decisions'])
    composite=evidence('composite_ref');fraction=evidence('fraction_ref')
    if len(source_scope['serial_page_evidence'])!=len(expected_pages) or [r['page'] for r in source_scope['serial_page_evidence']]!=expected_pages:
        raise ValueError('typed_style_actual_page_evidence_incomplete')
    return dict(manifest=m,rows=rows,accepted=accepted,decisions=decisions,measurements=measurements,
                finite=finite,intrinsic=intrinsic,semantic=semantic,composite=composite,fraction=fraction,
                page_evidence=source_scope['serial_page_evidence'])

def _literal(native,indices):
    if not isinstance(indices,list) or not indices or len(set(indices))!=len(indices) or any(
        type(i) is not int or not 0<=i<len(native) for i in indices):
        raise ValueError('typed_label_indices_invalid')
    return ''.join(chr(native[i]['unicode']) for i in indices)

def audit_typed_page(plan, page, source_native, target_native, *, target_page=None):
    """输入为当前一页；所有非普通路线只能继承同 PDF/SHA/字形实例的具名裁决。"""
    target_page=page if target_page is None else target_page
    m=plan['manifest']; result={'page':page,'status':'unverified','issues':[],'pending':[],
                              'reports':[],'quality_pass':False}
    for side,actual in (('source',source_native),('target',target_native)):
        physical_page=page if side=='source' else target_page
        evidence=next(r for r in plan['page_evidence'] if r['page']==physical_page)
        snapshot=read_bound_json(evidence[side+'_ref'])
        if snapshot.get('pdf')!=m[side] or snapshot.get('page')!=physical_page or snapshot.get('independent_capture') is not True:
            raise ValueError('typed_independent_page_identity_changed')
        if actual!=snapshot['native']:
            result['issues'].append({'rule':'actual_native_differs_from_independently_accepted_instance','side':side,'page':page})
    if result['issues']:result['status']='fail';return result
    for key,row in plan['rows'].items():
        if row['page']!=page or row.get('target_page',page)!=target_page:continue
        route=plan['decisions'][key]['route'];a=plan['accepted'][key]
        report={'id':key,'route':route,'component_decision':'unverified','quality_pass':False,
                'source_page':page,'target_page':target_page,
                'complete_owner_id':row.get('complete_owner_id'),'actual_native_instance_verified':True}
        try:
            si=a['source_label_indices'];ti=row.get('target_label_indices',[])
            source_literal=_literal(source_native,si)
            target_literal=_literal(target_native,ti) if ti else None
            if route=='ordinary_0.001':
                measure=plan['measurements'].get(key)
                hosts=measure['target_host_indices'] if measure else [row['target_host_anchor_index']]*len(ti)
                if len(hosts)!=len(ti) and len(set(hosts))==1:
                    # 源范围接受包含已补齐完整标签；同一实际宿主覆盖全部完整目标成员。
                    hosts=[hosts[0]]*len(ti)
                alias='exact'; role=None
                if source_literal!=target_literal:
                    sem=plan['semantic'].get(key,{})
                    if sem.get('semantic_binding_status')!='pass':raise ValueError('literal_alias_not_independently_accepted')
                    adapter=sem['adapter_kind']
                    if adapter=='scientific_minus_character_alias':alias='scientific_minus';role='unit_exponent'
                    elif adapter=='figure_reference_localized_prefix_or_separator':alias='figure_separator';role='figure_reference'
                    else:raise ValueError('ordinary_literal_alias_not_supported')
                binding=dict(source_id=key,source_label_indices=si,source_host_anchor_index=a['source_host_anchor_index'],
                    source_script=a['source_script'],target_label_indices=ti,target_host_indices=hosts,
                    source_literal=source_literal,target_literal=target_literal,literal_adapter=alias,semantic_role=role)
                ordinary=audit_local_binding(source_native,target_native,binding,normalized_tolerance=.001,
                    size_ratio_tolerance=.001,policy_scope_id='independent_complete_scope_ordinary_0.001')
                report.update(component_decision=ordinary['component_decision'],actual_report=ordinary)
            elif route=='finite_typographic_adaptation':
                proof=plan['finite'][key]
                if (proof['finite_typographic_adaptation_decision']!='pass' or
                    proof['acceptance_scope']!='exact_immutable_current_binding_and_geometry_only' or
                    proof['source_label_indices']!=si or proof['target_label_indices']!=ti or
                    proof['source_host_index']!=a['source_host_anchor_index'] or proof['target_page']!=target_page or
                    proof.get('complete_owner_id')!=row.get('complete_owner_id')):
                    raise ValueError('finite_typographic_instance_not_accepted')
                report.update(component_decision='pass',ordinary_rounding_status='not_applied_to_finite_typographic_adaptation',
                    accepted_normalized_baseline_error=proof['normalized_baseline_error'],
                    accepted_size_ratio_error=proof['size_ratio_error'],finite_instance_only=True)
            elif route=='intrinsic_font_and_ink':
                proof=plan['intrinsic'][key]
                if (proof['font_character_curve_status']!='pass' or proof['semantic_script_equivalence_status']!='pass' or
                    not proof['finite_readability_status'].startswith('pass') or proof['source_literal']!=source_literal or
                    proof['target_literal']!=target_literal):raise ValueError('intrinsic_font_identity_or_readability_not_accepted')
                for check in proof['checks']:
                    native=source_native if check['side']=='source' else target_native
                    owned=si if check['side']=='source' else ti
                    if check['native_index'] not in owned or native[check['native_index']]['gid']!=check['GID']:
                        raise ValueError('intrinsic_actual_glyph_identity_changed')
                    read_bound_json(check['complete_outline_ref'])
                read_bound_json(proof['readability_acceptance_ref'])
                report.update(component_decision='pass',finite_instance_only=True,
                    font_outline_acceptance_inherited=True,native_font_size_used_as_ink_size=False)
            elif route=='semantic_rendering':
                proof=plan['semantic'][key]
                if (ti or proof['semantic_binding_status']!='pass' or proof.get('complete_owner_id')!=row.get('complete_owner_id') or
                    proof['source_label_indices']!=si or proof['adapter_kind'] not in {
                        'semantic_reference_without_new_target_glyph','scientific_unit_rendered_as_chinese_words'}):
                    raise ValueError('semantic_route_ownership_or_acceptance_invalid')
                read_bound_json(proof['complete_semantic_acceptance_ref'])
                report.update(component_decision='pass',finite_instance_only=True,
                              target_script_glyph_ownership='not_applicable_semantic_rendering')
            elif route=='composite_fraction':
                proof=plan['composite'];bar=plan['fraction']
                if (proof['id']!=key or proof['native_glyph_parent_identity']!='pass' or bar['decision']!='pass' or
                    bar['finite_status']!='pass' or bar['page']!=page or bar['vector_identity_excluding_paint_sequence']!='pass' or
                    bar['PNG_and_decoded_pixel_identity']!='pass'):raise ValueError('composite_fraction_native_or_vector_not_accepted')
                source_parent=row['complete_source_indices'];target_parent=row['complete_target_indices']
                if [source_native[i] for i in source_parent]!=[target_native[i] for i in target_parent]:
                    raise ValueError('composite_fraction_complete_parent_changed')
                read_bound_json(bar['evidence_ref'])
                report.update(component_decision='pass',finite_instance_only=True,
                              ordinary_single_baseline_policy_applied=False,vector_acceptance_inherited=True)
        except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as error:
            report['reason']=str(error)
        result['reports'].append(report)
        if report['component_decision']=='fail':result['issues'].append({'id':key,'rule':'ordinary_actual_style_mismatch','report':report})
        elif report['component_decision']!='pass':result['pending'].append({'id':key,'rule':'typed_style_adapter_unverified','reason':report.get('reason',report.get('actual_report',{}).get('pending'))})
    result['status']='fail' if result['issues'] else 'unverified' if result['pending'] else 'pass'
    return result

def audit_packet_typed_styles(scope,freeze,*,source_ref,target_ref,standard_ref,expected_pages):
    result={'status':'unverified','issues':[],'pending':[],'reports':[],'quality_pass':False,
            'checked_source_item_ids':[],'source_page_reads':[],'target_page_reads':[]}
    try:
        if any(file_ref(r['path'])!=r for r in (source_ref,target_ref,standard_ref)):
            raise ValueError('typed_actual_file_identity_changed')
        plan=load_typed_plan(scope,freeze,source_ref=source_ref,target_ref=target_ref,
                             standard_ref=standard_ref,expected_pages=expected_pages)
        owned=set()
        for row in plan['rows'].values():
            for i in row.get('target_label_indices',[]):
                member=(row.get('target_page',row['page']),i)
                if member in owned:raise ValueError('typed_target_glyph_owned_more_than_once')
                owned.add(member)
        pairs=sorted({(r['page'],r.get('target_page',r['page'])) for r in plan['rows'].values()})
        source_cached=None;target_cached=None;source_native=None;target_native=None
        for page,target_page in pairs:
            # 只缓存当前物理页的源/译字形，下一页前释放；各PDF句柄立即关闭。
            if page!=source_cached:
                source_native=None
                with fitz.open(source_ref['path']) as doc:source_native=glyphs(doc[page-1])
                source_cached=page;result['source_page_reads'].append(page)
            if target_page!=target_cached:
                target_native=None
                with fitz.open(target_ref['path']) as doc:target_native=glyphs(doc[target_page-1])
                target_cached=target_page;result['target_page_reads'].append(target_page)
            checked=audit_typed_page(plan,page,source_native,target_native,target_page=target_page)
            result['reports']+=checked['reports'];result['issues']+=checked['issues'];result['pending']+=checked['pending']
        del source_native,target_native
        result['checked_source_item_ids']=[r['id'] for r in result['reports']]
        if set(result['checked_source_item_ids'])!=set(plan['rows']):
            result['pending'].append({'rule':'typed_style_all_items_not_recalculated'})
        for r in (source_ref,target_ref,standard_ref):
            if file_ref(r['path'])!=r:raise ValueError('typed_actual_file_changed_during_recalculation')
        result['route_counts']=dict(Counter(r['route'] for r in result['reports']))
    except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError,StopIteration) as error:
        result['pending'].append({'rule':'typed_style_frozen_evidence_invalid','reason':str(error)})
    result['status']='fail' if result['issues'] else 'unverified' if result['pending'] else 'pass'
    return result
