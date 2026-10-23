"""生产入口的综合质量门；缺少完整、独立、绑定身份的证据时保留未验证。"""
from __future__ import annotations
import json
from pathlib import Path
import fitz
from qa_source_contract import file_ref,read_bound_json,independent_source_inventory
from qa_gate_summary import aggregate_quality,REQUIRED_GATES
from qa_source_contract import validate_role_review
from qa_actual_pdf import measure_unit_texts,close_unit_texts,audit_target_content_roles
from qa_semantic_review import validate_semantic_review
from qa_visual_risk import close_visual_risks
from qa_native_links import audit_native_link_batch
from translation_coverage import assess_translation_coverage,normalized
from qa_mixed_source_treatment import audit_bound_mixed_treatment
from qa_script_styles import audit_packet_script_styles

STANDARD_PATH=Path(__file__).resolve().parents[1]/'references/hardening-qa-contract.md'

def _pending(rule, **extra):
    return {'schema_version':1,'status':'unverified','quality_pass':False,
            'issues':[],'pending':[{'rule':rule}], 'strict_delivery':False,
            'human_acceptance':False,'promotion_performed':False,**extra}

def component_freeze(freeze, component, *, source_ref, target_ref, standard_ref):
    """具名委托仅作用于该组件；不会把总包署名改成另一执行者。"""
    refs=freeze.get('component_reviewer_authorizations',{})
    if component not in refs:return freeze
    authority=read_bound_json(refs[component])
    reviewer=authority.get('reviewer_id')
    if (not reviewer or reviewer==freeze.get('producer_id') or
        authority.get('source')!=source_ref or authority.get('target')!=target_ref or
        authority.get('standard')!=standard_ref or
        authority.get('scope')!='complete_document_quality_repair_rereview' or
        component not in authority.get('component_scopes',[])):
        raise ValueError('quality_component_authority_scope_changed')
    return {**freeze,'reviewer_id':reviewer,'reviewer_authorization_ref':refs[component]}

def _inventory_signature(value):
    def box(row):return tuple(round(float(v),2) for v in row['bbox'])
    lines={(e['id'],e['page'],e['source_text_sha256'],box(e)) for e in value['elements']}
    assets={(a['id'],a['page'],a['kind'],box(a)) for a in value['assets']}
    if len(lines)!=len(value['elements']) or len(assets)!=len(value['assets']):
        raise ValueError('quality_source_inventory_duplicate')
    return lines,assets

def verify_source_inventory(inventory, *, source_ref, expected_pages):
    """重新枚举实际源PDF，避免被缩减的生产清单或手工JSON误导。扫描内容仍待OCR/视觉证明。"""
    issues=[];pending=[];fresh={'elements':[],'assets':[]}
    if inventory.get('source')!=source_ref or inventory.get('enumeration_dependencies')!=['source_pdf']:
        issues.append({'rule':'quality_source_inventory_identity_or_dependency'})
    if sorted(p['page'] for p in inventory.get('pages',[]))!=expected_pages:
        issues.append({'rule':'quality_source_inventory_page_scope_incomplete'})
    for start in range(0,len(expected_pages),1):
        batch=independent_source_inventory(source_ref['path'],pages=expected_pages[start:start+1])
        fresh['elements']+=batch['elements'];fresh['assets']+=batch['assets']
        for row in batch['pages']:
            if row['ocr_or_blank_review_required']:
                pending.append({'page':row['page'],'rule':'source_scan_or_blank_page_requires_independent_review'})
    if _inventory_signature(inventory)!=_inventory_signature(fresh):
        issues.append({'rule':'quality_source_inventory_does_not_equal_actual_pdf'})
    return {'status':'fail' if issues else 'unverified' if pending else 'pass',
            'issues':issues,'pending':pending,'checked_source_lines':len(fresh['elements']),
            'checked_source_assets':len(fresh['assets']),'quality_pass':False}

def audit_packet_content(packet, freeze, inventory, *, source_ref, target_ref, standard_ref, expected_pages):
    """覆盖和语义组件重新执行，正面汇总JSON不能代替实际源/成品绑定。"""
    issues=[];pending=[]
    try:
        inputs=packet['content_inputs']
        elements=read_bound_json(inputs['elements_ref'])
        translations=read_bound_json(inputs['translations_ref'])
        bindings=read_bound_json(inputs['bindings_ref'])
        protected=read_bound_json(inputs['protected_bindings_ref'])
        if elements.get('source')!=source_ref or any(d.get('source')!=source_ref or d.get('target')!=target_ref for d in (translations,bindings,protected)):
            raise ValueError('content_input_identity_changed')
        rows=elements['elements'];units=translations['units'];bound=bindings['bindings']
        protected_bound=protected['bindings']
        if {u['id'] for u in units}!={b['id'] for b in bound}:raise ValueError('actual_unit_binding_scope_changed')
    except (KeyError,TypeError,ValueError,OSError,json.JSONDecodeError):
        return {'status':'unverified','issues':[],'pending':[{'rule':'quality_content_inputs_missing_or_changed'}],'quality_pass':False}
    role=validate_role_review(rows,review_ref=inputs.get('role_review_ref'),source_ref=source_ref,inventory_ref=packet['source_inventory_ref'])
    if role['status']=='fail':issues+=role['issues']
    elif role['status']=='unverified':pending+=role['issues']
    source_by_id={e['id']:e for e in inventory['elements']}
    for unit in units:
        context=[r['id'] for f in unit.get('fragments',[]) for r in f.get('source_line_refs',[])]
        if not context or any(key not in source_by_id for key in context) or normalized(unit.get('source_text',''))!=normalized(' '.join(source_by_id[key]['source_text'] for key in context if key in source_by_id)):
            issues.append({'id':unit['id'],'rule':'translation_unit_source_context_does_not_match_independent_lines'})
    with fitz.open(target_ref['path']) as doc:target_pages=list(range(1,len(doc)+1))
    all_bound=bound+protected_bound
    batches=[measure_unit_texts(target_ref,all_bound,pages=target_pages[n:n+1]) for n in range(0,len(target_pages),1)]
    actual=close_unit_texts(bound,batches,target_ref=target_ref);issues+=actual['issues']
    mixed=audit_bound_mixed_treatment(rows,units,actual['actual_texts'],
        review_ref=inputs.get('mixed_review_ref'),source_ref=source_ref,target_ref=target_ref,
        standard_ref=standard_ref,producer_id=freeze.get('producer_id'),
        authorized_reviewer_id=freeze.get('reviewer_id'),
        source_role_review_ref=inputs.get('role_review_ref'),
        reviewer_authorization_ref=freeze.get('reviewer_authorization_ref'),
        inventory_ref=packet['source_inventory_ref'])
    issues+=mixed['issues'];pending+=mixed['pending']
    mixed_ids=set(mixed['accepted_source_ids'])
    protected_source={e['id']:e for e in rows if e.get('status')=='protected' and e['id'] not in mixed_ids}
    protected_ids=[]
    canonical_identity_checks=[]
    for binding in protected_bound:
        context=binding.get('source_line_ids',[]);protected_ids+=context
        identity_equal=bool(context) and not any(key not in protected_source for key in context) and normalized(binding.get('target_text',''))==normalized(' '.join(protected_source[key]['source_text'] for key in context if key in protected_source))
        if not identity_equal and inputs.get('canonical_identity_ref'):
            from qa_protected_identity import canonical_protected_binding
            check=canonical_protected_binding(binding,rows,review_ref=inputs['canonical_identity_ref'],
                source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,
                reviewer_id=freeze['reviewer_id'],role_review_verified=role['status']=='pass')
            canonical_identity_checks.append({'id':binding.get('id'),**check})
            identity_equal=check['status']=='pass'
        if not identity_equal:issues.append({'id':binding.get('id'),'rule':'target_protected_binding_not_verified_source_role'})
    if len(protected_ids)!=len(set(protected_ids)) or set(protected_ids)!=set(protected_source):
        pending.append({'rule':'target_protected_source_role_binding_scope_incomplete'})
    protected_actual=close_unit_texts(protected_bound,batches,target_ref=target_ref)
    issues+=protected_actual['issues']
    content_roles=[audit_target_content_roles(target_ref,all_bound,units,pages=target_pages[n:n+1]) for n in range(0,len(target_pages),1)]
    for result in content_roles:issues+=result['issues'];pending+=result['pending']
    coverage=assess_translation_coverage(rows,units,declared_pages=expected_pages,expected_pages=expected_pages,
        actual_targets=actual['actual_texts'],independent_role_review=role['status']=='pass',require_source_bindings=True,
        role_review_ref=inputs.get('role_review_ref'),source_ref=source_ref,inventory_ref=packet['source_inventory_ref'],
        mixed_review_ref=inputs.get('mixed_review_ref'),target_ref=target_ref,standard_ref=standard_ref,
        producer_id=freeze.get('producer_id'),authorized_reviewer_id=freeze.get('reviewer_id'),
        reviewer_authorization_ref=freeze.get('reviewer_authorization_ref'))
    absent={'independent_role_evidence_missing_or_changed','independent_role_review_required'}|{r['rule'] for r in mixed['pending']}
    for row in coverage['issues']:
        (pending if row['rule'] in absent else issues).append(row)
    semantic_units=[{**u,'source_line_ids':[r['id'] for f in u.get('fragments',[]) for r in f.get('source_line_refs',[])]} for u in units]
    semantic=validate_semantic_review(semantic_units,review_ref=inputs.get('semantic_review_ref'),source_ref=source_ref,
        target_ref=target_ref,standard_sha256=standard_ref['sha256'],producer_id=freeze.get('producer_id'))
    issues+=semantic['issues'];pending+=semantic['pending']
    for name in ('role_review_ref','semantic_review_ref'):
        try:
            review=read_bound_json(inputs[name])
            if review.get('reviewer_id')!=freeze['reviewer_id']:pending.append({'rule':'quality_component_reviewer_outside_authorized_scope','component':name})
        except (KeyError,ValueError,OSError,TypeError,json.JSONDecodeError):pass
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,
            'role_audit':role,'coverage':coverage,'mixed_treatment_audit':mixed,'actual_text_status':actual['status'],
            'actual_units':len(actual['actual_texts']),'semantic_audit':semantic,'target_content_roles':content_roles,'protected_actual_status':protected_actual['status'],
            'canonical_identity_checks':canonical_identity_checks,'quality_pass':False}

def audit_packet_visual(packet, freeze, *, source_ref, target_ref, standard_ref, expected_pages):
    """逐区重绘验证像素；正面视觉汇总不能替代裁图、源先行范围和全页审查。"""
    try:
        inputs=packet['visual_inputs']
        registry=read_bound_json(inputs['regions_ref']);review=read_bound_json(inputs['review_ref'])
        for value in (registry,review):
            if value.get('source')!=source_ref or value.get('target')!=target_ref or value.get('standard_sha256')!=standard_ref['sha256'] or value.get('reviewer_id')!=freeze['reviewer_id']:
                raise ValueError('visual_packet_identity_or_reviewer_changed')
        if registry.get('method')!='source_first' or registry.get('source_pages_checked')!=expected_pages or review.get('full_page_sweep')!=expected_pages:
            raise ValueError('visual_source_first_or_full_page_scope_missing')
        regions=registry['regions'];decisions=review['reviews']
        expected=next(r['expected_items'] for r in freeze['requirements'] if r['id']=='visual')
        if not regions or len(regions)>1000 or len({r['id'] for r in regions})!=len(regions) or set(expected)!={r['id'] for r in regions}:
            raise ValueError('visual_required_region_scope_changed')
        if any(r.get('source')!=source_ref or r.get('target')!=target_ref for r in regions) or any(r.get('reviewer_id')!=freeze['reviewer_id'] for r in decisions):
            raise ValueError('visual_region_or_decision_identity_changed')
    except (KeyError,ValueError,TypeError,OSError,json.JSONDecodeError):
        return {'status':'unverified','issues':[],'pending':[{'rule':'quality_visual_inputs_missing_or_changed'}],'quality_pass':False}
    result=close_visual_risks(regions,decisions,source_ref=source_ref,target_ref=target_ref,standard_sha256=standard_ref['sha256'],producer_id=freeze['producer_id'])
    result.update(source_first_registry=inputs['regions_ref'],independent_visual_review=inputs['review_ref'],full_page_sweep=expected_pages)
    return result

def audit_packet_native_links(packet,freeze,*,source_ref,target_ref,standard_ref,expected_pages):
    """重新测量可点击URI；未核定的内部目标继续待审，不能由汇总覆盖。"""
    try:
        inputs=packet['assets_links_inputs'];registry=read_bound_json(inputs['native_links_ref'])
        if registry.get('source')!=source_ref or registry.get('target')!=target_ref or registry.get('standard_sha256')!=standard_ref['sha256'] or registry.get('reviewer_id')!=freeze['reviewer_id'] or registry.get('method')!='source_first' or registry.get('source_pages_checked')!=expected_pages:
            raise ValueError('native_links_registry_identity_or_scope_changed')
        regions=registry['regions']
        if not isinstance(regions,list) or len(regions)>1000 or len({r['id'] for r in regions})!=len(regions):raise ValueError('native_link_region_registry_invalid')
        with fitz.open(target_ref['path']) as doc:target_pages=list(range(1,len(doc)+1))
        if registry.get('target_pages_checked')!=target_pages:raise ValueError('native_link_target_page_scope_incomplete')
        page_map=registry['target_page_map']
        if set(page_map)!={str(p) for p in expected_pages} or set(p for values in page_map.values() for p in values)!=set(target_pages):raise ValueError('native_link_actual_page_map_incomplete')
        if any(not values or len(values)!=len(set(values)) or any(type(v)is not int or v not in target_pages for v in values) for values in page_map.values()):raise ValueError('native_link_page_map_invalid')
        issues=[];pending=[];batches=[]
        # 按源页和映射目标各至多5页划批；超出可核验映射时保持未知。
        for start in range(0,len(expected_pages),1):
            pages=expected_pages[start:start+1];own=[r for r in regions if r['source_page'] in pages]
            mapped=sorted({p for n in pages for p in page_map[str(n)]})
            if len(mapped)>5 or any(r['target_page'] not in page_map[str(r['source_page'])] for r in own):raise ValueError('native_link_mapping_outside_batch')
            result=audit_native_link_batch(source_ref,target_ref,own,source_pages=pages,target_pages=mapped,
                action_binding_ref=inputs.get('action_bindings_ref'),standard_ref=standard_ref,
                reviewer_id=freeze['reviewer_id'],producer_id=freeze['producer_id'],
                authorization_ref=freeze['reviewer_authorization_ref'])
            issues+=result['issues'];pending+=result['pending'];batches.append(result)
        return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,'batches':batches,'quality_pass':False}
    except (KeyError,ValueError,TypeError,OSError,json.JSONDecodeError):
        return {'status':'unverified','issues':[],'pending':[{'rule':'quality_native_links_inputs_missing_or_changed'}],'quality_pass':False}

def evaluate_quality_packet(source, target, *, review_ref=None, standard_path=None):
    """review_ref必须由已获授权的独立复核者冻结。该接口验证合同，不认证人员身份。"""
    source_ref=file_ref(source)
    standard_ref=file_ref(standard_path or STANDARD_PATH)
    if target is None or not Path(target).is_file():
        return _pending('quality_final_pdf_missing',source=source_ref,standard=standard_ref)
    target_ref=file_ref(target)
    with fitz.open(source) as doc:expected_pages=list(range(1,len(doc)+1))
    base={'source':source_ref,'target':target_ref,'standard':standard_ref,'expected_pages':expected_pages}
    if review_ref is None:return _pending('complete_independent_quality_packet_required',**base)
    try:
        packet=read_bound_json(review_ref)
        freeze=read_bound_json(packet['requirements_ref'])
        inventory=read_bound_json(packet['source_inventory_ref'])
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        return _pending('quality_packet_evidence_missing_or_changed',**base)
    if (packet.get('source')!=source_ref or packet.get('target')!=target_ref or
        packet.get('standard')!=standard_ref or freeze.get('source')!=source_ref or
        freeze.get('standard')!=standard_ref):
        return _pending('quality_packet_source_target_or_standard_changed',**base)
    if (freeze.get('method')!='source_first' or not freeze.get('reviewer_id') or
        freeze.get('reviewer_id')==freeze.get('producer_id') or
        not freeze.get('reviewer_authorization_ref') or
        packet.get('reviewer_id')!=freeze.get('reviewer_id')):
        return _pending('authorized_independent_requirements_review_required',**base)
    try:
        authority=read_bound_json(freeze['reviewer_authorization_ref'])
        if authority.get('reviewer_id')!=freeze['reviewer_id'] or authority.get('source')!=source_ref or authority.get('standard')!=standard_ref or authority.get('scope') not in {'complete_document_quality','complete_document_quality_repair_rereview'} or authority.get('target',target_ref)!=target_ref:
            return _pending('quality_reviewer_authority_scope_changed',**base)
        if authority.get('scope')=='complete_document_quality_repair_rereview' and authority.get('target')!=target_ref:
            return _pending('quality_reviewer_rereview_target_scope_changed',**base)
        requirements=freeze['requirements']
        if {r['id'] for r in requirements}!=REQUIRED_GATES:
            return _pending('mandatory_quality_contract_checks_missing',**base)
        if freeze.get('expected_pages')!=expected_pages:
            return _pending('quality_frozen_document_scope_incomplete',**base)
        native=verify_source_inventory(inventory,source_ref=source_ref,expected_pages=expected_pages)
        if native['issues']:
            rejected=_pending('quality_source_inventory_comparison_failed',**base)
            rejected.update(status='fail',issues=native['issues'],pending=native['pending'],source_inventory_check=native)
            return rejected
        expected_lines=[e['id'] for e in inventory['elements']];expected_assets=[a['id'] for a in inventory['assets']]
        if sorted(freeze.get('source_line_ids',[]))!=sorted(expected_lines) or sorted(freeze.get('source_asset_ids',[]))!=sorted(expected_assets):
            return _pending('quality_requirements_omit_independent_source_elements',**base)
        by_gate={r['id']:r for r in requirements}
        for gate,items in [('source_inventory',expected_lines+expected_assets),('roles',expected_lines),('coverage',expected_lines)]:
            if set(by_gate[gate].get('expected_items',[]))!=set(items):
                return _pending('quality_required_check_source_items_incomplete',**base)
        with fitz.open(source_ref['path']) as doc:
            source_link_ids=[f'source-link-p{p}-xref{link["xref"]}' for p in expected_pages for link in doc[p-1].get_links()]
        asset_link_items=expected_assets+source_link_ids or ['no_source_native_assets_or_links']
        if set(by_gate['assets_links'].get('expected_items',[]))!=set(asset_link_items):
            return _pending('quality_assets_links_requirements_omit_actual_source_items',**base)
        result=aggregate_quality(requirements,packet.get('results',[]),source_ref=source_ref,
            target_ref=target_ref,expected_pages=expected_pages,
            declared_pages=packet.get('declared_pages',[]),standard_sha256=standard_ref['sha256'])
        for row in packet.get('results',[]):
            if row.get('status') in {'pass','not_applicable'}:
                for ref in row.get('evidence',[]):
                    if read_bound_json(ref).get('reviewer_id')!=freeze['reviewer_id']:
                        result['pending'].append({'id':row['id'],'rule':'quality_proof_reviewer_outside_authorized_scope'})
        content_freeze=component_freeze(freeze,'content',source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref)
        styles_freeze=component_freeze(freeze,'script_styles',source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref)
        content=audit_packet_content(packet,content_freeze,inventory,source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,expected_pages=expected_pages)
        visual=audit_packet_visual(packet,freeze,source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,expected_pages=expected_pages)
        links=audit_packet_native_links(packet,freeze,source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,expected_pages=expected_pages)
        styles=audit_packet_script_styles(packet,styles_freeze,source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,expected_pages=expected_pages)
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        return _pending('quality_packet_contract_invalid',**base)
    result['issues']+=native['issues']+content['issues']+visual['issues']+links['issues']+styles['issues'];result['pending']+=native['pending']+content['pending']+visual['pending']+links['pending']+styles['pending']
    result['quality_pass']=not result['issues'] and not result['pending']
    result['status']='fail' if result['issues'] else 'unverified' if result['pending'] else 'pass'
    result.update(standard=standard_ref,review=review_ref,requirements=packet['requirements_ref'],
                  source_inventory_check=native,content_check=content,visual_check=visual,native_links_check=links,script_styles_check=styles)
    return result

def final_pdf_from_manifest(manifest, *, source=None):
    outputs=manifest.get('outputs') or {}
    # 审查中文最终读者稿；双语文件必须另行声明其页映射。
    for value in (outputs.get('translated_pdf'),outputs.get('mono_pdf'),
                  manifest.get('translated_pdf'),manifest.get('output_pdf'),manifest.get('path')):
        if value and Path(str(value)).is_file() and Path(str(value)).suffix.lower()=='.pdf':return Path(value)
    # 正式原生后端返回backend manifest，主PDF身份保存在它明确引用的render manifest。
    # 只跟随这一层具名入口；不得按目录文件名猜主产物或借用其它source的旧文件。
    child_path=manifest.get('render_manifest')
    if source is not None and isinstance(child_path,str) and Path(child_path).is_file():
        try:
            path=Path(child_path)
            if path.stat().st_size>8*1024**2:return None
            before=file_ref(path);child=json.loads(path.read_text())
            if file_ref(path)!=before or not child.get('input_pdf') or Path(child['input_pdf']).resolve()!=Path(source).resolve():return None
            return final_pdf_from_manifest({k:v for k,v in child.items() if k!='render_manifest'})
        except (OSError,TypeError,ValueError,KeyError,json.JSONDecodeError):return None
    return None

def audit_technical_receipt(manifest, *, source_ref, target_ref):
    """仅接受当前源/成品和实际机器报告绑定的失败；技术成功不授予综合通过。"""
    ref=manifest.get('technical_quality_ref')
    if not ref:
        pending=[{'rule':'quality_blocking_render_evidence_missing'}] if manifest.get('status')=='blocking' else []
        return {'issues':[],'pending':pending}
    try:
        proof=read_bound_json(ref)
        if proof.get('source')!=source_ref or proof.get('target')!=target_ref:
            raise ValueError('technical_artifact_mismatch')
        gate=read_bound_json(proof['gate_ref'])
        if gate.get('status') not in {'blocking','partial','warn','ok','not_applicable'} or not isinstance(gate.get('issues'),list) or len(gate['issues'])>20000 or any(not isinstance(i,dict) for i in gate['issues']):
            raise ValueError('technical_gate_schema_invalid')
        blocking=[i for i in gate.get('issues',[]) if i.get('severity')=='blocking']
        if (proof.get('producer')!='scanned_raster_quality_gate' or
                gate.get('status')!='blocking' and blocking or proof.get('blocking_issues')!=blocking):
            raise ValueError('technical_report_claim_mismatch')
        if gate.get('status')=='blocking':
            if not blocking:raise ValueError('technical_block_without_specific_issue')
            return {'issues':[{'id':'technical_render','rule':i['rule'],'evidence':ref,'region_id':i.get('region_id'),'page':i.get('page')}for i in blocking], 'pending':[]}
        return {'issues':[],'pending':[]}
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        return {'issues':[],'pending':[{'rule':'quality_technical_evidence_missing_changed_or_invalid'}]}

OVERFLOW_SOURCE_FALLBACK='overflow_source_fallback'


def audit_overflow_source_fallbacks(output_dir):
    """读取本次后端排版回执（_backend_working/*/typesetting_writeback_report.json）中的原文保留降级。

    每条降级都是待复核项（pending，稳定代码 overflow_source_fallback），综合质量因此不可能为 pass；
    回执存在但无法解析时同样记 pending，不当作没有降级。"""
    receipts,pending,count=[],[],0
    for path in sorted(Path(output_dir).glob('_backend_working/*/typesetting_writeback_report.json')):
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            rows=data.get('source_fallbacks') or []
            if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
                raise ValueError('source_fallbacks_not_list')
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            pending.append({'id':OVERFLOW_SOURCE_FALLBACK,'rule':'overflow_source_fallback_receipt_invalid','evidence':str(path)})
            continue
        ref=file_ref(path)
        receipts.append({'receipt':ref,'count':len(rows),'cap':data.get('source_fallback_cap')})
        if rows:
            count+=len(rows)
            pending.append({'id':OVERFLOW_SOURCE_FALLBACK,'rule':OVERFLOW_SOURCE_FALLBACK,'severity':'needs_review',
                            'count':len(rows),'pages':sorted({int(r['page_index'])+1 for r in rows if isinstance(r.get('page_index'),int)}),
                            'segments':[{k:r.get(k) for k in ('page_index','paragraph_id','role','category','source_text','translated_text')}
                                        for r in rows[:200]],
                            'message':'译文在可读字号下限仍放不下，该短结构片段保留了原文，需人工复核',
                            'evidence':ref})
    return {'count':count,'receipts':receipts,'pending':pending}


def attach_pipeline_quality(manifest, *, source, output_dir, review_ref=None, target_language='zh',
                            region_open_at_start=False):
    """每条渲染路线都会写综合结果；技术渲染status单独保留。"""
    result=evaluate_quality_packet(source,final_pdf_from_manifest(manifest,source=source),review_ref=review_ref)
    technical=audit_technical_receipt(manifest,source_ref=file_ref(source),target_ref=result.get('target'))
    result['technical_check']=technical
    if technical['issues'] or technical['pending']:
        result.setdefault('issues',[]).extend(technical['issues']);result.setdefault('pending',[]).extend(technical['pending'])
        result['quality_pass']=False
        result['status']='fail' if result.get('status')=='fail' or result['issues'] else 'unverified'
    output_dir=Path(output_dir)
    overflow=audit_overflow_source_fallbacks(output_dir)
    result['overflow_source_fallback_check']={'count':overflow['count'],'receipts':overflow['receipts']}
    if overflow['pending']:
        # 原文保留降级永远不是通过：至少 unverified（待复核）；已有 fail 保持 fail。
        result.setdefault('pending',[]).extend(overflow['pending'])
        result['quality_pass']=False
        result['status']='fail' if result.get('status')=='fail' or result.get('issues') else 'unverified'
    residue=render_residue_gate(source,final_pdf_from_manifest(manifest,source=source),output_dir,target_language=target_language,
                                region_open_at_start=region_open_at_start)
    result['render_residue_check']=residue
    if residue.get('severity')=='high':
        # 基于实际成品的大面积源语言残留（英译中=英文，中译英=中文）属于高风险失败，不能只记为 warn。
        rule=residue.get('check','render_english_residue')
        structural={'retained_glyph_overlap':residue.get('retained_glyph_overlap_pages'),
                    'vector_glyph_loss':residue.get('vector_glyph_loss_pages'),
                    'inline_object_damage':residue.get('inline_object_damage_pages')}
        if residue.get('high_pages') or not any(structural.values()):
            result.setdefault('issues',[]).append({'id':rule,'rule':rule+'_high',
                'severity':'high','pages':residue.get('high_pages'),'overall_residue_ratio':residue.get('overall_residue_ratio'),
                'evidence':residue.get('report_ref')})
        # 中译英结构性失败（源文保留字形与译文压叠、矢量路径公式字形丢失）各自给出独立规则码。
        for name,pages in structural.items():
            if pages:
                result.setdefault('issues',[]).append({'id':name,'rule':name+'_high','severity':'high','pages':pages,
                    'evidence':residue.get('report_ref')})
        result['quality_pass']=False
        result['status']='fail'
    path=output_dir/'comprehensive_quality.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    fields={'quality_status':result['status'],'quality_pass':result['quality_pass'],
            'overflow_source_fallback_count':overflow['count'],
            'reference_exclusion':{k:v for k,v in (((residue.get('excluded') or {}).get('reference_exclusion_summary') or {}).get('target') or {}).items()
                                   if k in ('excluded_entries','excluded_words','counted_entries','by_reason','excluded_words_by_page')},
            'quality_delivery_blocked':not result['quality_pass'],'comprehensive_quality':file_ref(path),
            'render_residue':{k:residue.get(k) for k in ('severity','overall_residue_ratio','high_pages','medium_pages',
                                                         'retained_glyph_overlap_pages','vector_glyph_loss_pages','inline_object_damage_pages')
                              if k not in ('retained_glyph_overlap_pages','vector_glyph_loss_pages','inline_object_damage_pages') or k in residue}}
    manifest.update(fields)
    for name in ('render_manifest.json','backend_run_manifest.json'):
        existing=output_dir/name
        if existing.is_file():
            value=json.loads(existing.read_text());value.update(fields)
            existing.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    report=output_dir/'quality_report.md'
    text=report.read_text() if report.is_file() else ''
    prefix='<!-- comprehensive-quality -->';ending='<!-- /comprehensive-quality -->'
    if text.startswith(prefix):
        if ending in text:
            text=text.split(ending,1)[1].lstrip('\n')
        else:
            lines=text.splitlines(keepends=True)
            # 迁移本接口旧版的两行前缀；不丢弃非本接口生成的正文。
            if len(lines)>=2 and lines[1].startswith('综合质量状态：'):
                text=''.join(lines[2:]).lstrip('\n')
    residue_line=render_residue_summary(residue)
    report.write_text(f'{prefix}\n综合质量状态：{result["status"]}；交付门：{"通过" if result["quality_pass"] else "阻止晋升"}。完整证据见 comprehensive_quality.json。\n{residue_line}\n{ending}\n\n'+text)
    return manifest


def render_residue_gate(source, target, output_dir, target_language='zh', region_open_at_start=False):
    """最小版渲染成品英文残留检查；检查本身出错时记为未评估，不伪造通过。
    region_open_at_start 只由分块翻译传入（块从整份文档的参考文献区中间开始）。"""
    try:
        from render_residue_check import check_render_residue
        residue=(check_render_residue(source,target,target_language=target_language,region_open_at_start=True)
                 if region_open_at_start else check_render_residue(source,target,target_language=target_language))
    except Exception as exc:  # 解析器异常类型不固定
        residue={'status':'not_evaluated','severity':'ok','reason':f'{type(exc).__name__}: {exc}'[:300]}
    path=Path(output_dir)/'render_residue_check.json'
    path.write_text(json.dumps(residue,ensure_ascii=False,indent=2)+'\n')
    residue['report_ref']=file_ref(path)
    return residue


def render_residue_summary(residue):
    severity=residue.get('severity')
    name='渲染中文残留检查' if residue.get('check')=='render_chinese_residue' else '渲染英文残留检查'
    if residue.get('status')!='evaluated':
        return f'{name}：未评估（{residue.get("reason","")}）。'
    label={'high':'高风险（判定失败）','medium':'中风险','ok':'正常'}.get(severity,severity)
    text = (f'{name}：{label}；整体残留率 {residue.get("overall_residue_ratio")}；'
            f'高风险页 {residue.get("high_pages") or "无"}；中风险页 {residue.get("medium_pages") or "无"}。')
    if residue.get('retained_glyph_overlap_pages'):
        text += f'源文保留字形（未翻译公式碎片）与译文压叠页 {residue["retained_glyph_overlap_pages"]}（判定失败）。'
    if residue.get('vector_glyph_loss_pages'):
        text += f'矢量路径公式字形丢失页 {residue["vector_glyph_loss_pages"]}（判定失败）。'
    if residue.get('inline_object_damage_pages'):
        text += f'中文正文行内结构对象（矢量公式字形、Form XObject 变量）丢失或与译文压叠页 {residue["inline_object_damage_pages"]}（判定失败）。'
    return text
