"""完整引用/脚本样式接入生产质检：源审校范围冻结，目标字形现场重算。"""
from pathlib import Path
import json
import fitz
from qa_source_contract import file_ref,read_bound_json
from native_line_spacing import glyphs
from source_script_audit import assess_bound_script_styles
from source_script_report_gate import validate_bound_script_report,RUNTIME,SCHEMA
from source_scope_membership import audit_frozen_source_members

def _might_have_script(native):
    for i,g in enumerate(native):
        code=g['unicode']
        if code in {0xb2,0xb3,0xb9} or 0x2070<=code<=0x209f:
            return True
        for host in native[max(0,i-6):i]+native[i+1:i+7]:
            if not chr(host['unicode']).isspace() and .3<g['size']/host['size']<.85:
                rise=(host['origin'][1]-g['origin'][1])/host['size']
                if .05<abs(rise)<.8 and abs(host['origin'][0]-g['origin'][0])<50:
                    return True
    return False

def audit_packet_script_styles(packet,freeze,*,source_ref,target_ref,standard_ref,expected_pages):
    issues=[];pending=[];reports=[]
    result={'status':'unverified','issues':issues,'pending':pending,'reports':reports,'quality_pass':False}
    try:
        if file_ref(source_ref['path'])!=source_ref or file_ref(target_ref['path'])!=target_ref:
            raise ValueError('script_style_actual_pdf_identity_changed')
        scope=read_bound_json(freeze['script_styles_scope_ref'])
        if (scope.get('source')!=source_ref or scope.get('standard')!=standard_ref or
            scope.get('reviewer_id')!=freeze['reviewer_id'] or scope.get('method')!='source_first' or
            scope.get('pages')!=expected_pages):
            raise ValueError('source_script_scope_identity_or_complete_pages_changed')
        rows=scope['items']
        if not isinstance(rows,list) or len(rows)>2048 or len({r['id'] for r in rows})!=len(rows):
            raise ValueError('source_script_scope_items_invalid')
        # 全文容量与单页预算分别约束；所有源标记成员必须唯一归属。
        source_owned=set();source_page_counts={}
        for row in rows:
            page=row['page']
            if type(page) is not int or page not in expected_pages:
                raise ValueError('source_script_page_outside_scope')
            source_page_counts[page]=source_page_counts.get(page,0)+1
            if source_page_counts[page]>256:raise ValueError('source_script_single_page_item_budget')
            for index in row['source_label_indices']:
                key=(page,index)
                if key in source_owned:raise ValueError('source_script_member_duplicate_scope_binding')
                source_owned.add(key)
        if not rows:
            if not isinstance(scope.get('not_applicable_reason'),str) or not scope['not_applicable_reason'].strip():
                raise ValueError('source_script_empty_scope_requires_review_reason')
            for page in expected_pages:
                with fitz.open(source_ref['path']) as doc:native=glyphs(doc[page-1])
                if not native or len(native)>50000 or _might_have_script(native):
                    pending.append({'page':page,'rule':'source_script_empty_scope_contradicted_or_scan_requires_adapter'})
            result['status']='unverified' if pending else 'not_applicable'
            return result
        # 非空标记范围也须与独立完整源枚举核对，不能以自行裁小的清单通过。
        membership=audit_frozen_source_members(scope,freeze,source_ref=source_ref,
            standard_ref=standard_ref,expected_pages=expected_pages)
        result['source_membership_check']=membership
        issues.extend(membership['issues']);pending.extend(membership['pending'])
        if scope.get('typed_routes_ref'):
            from qa_typed_script_styles import audit_packet_typed_styles
            typed=audit_packet_typed_styles(scope,freeze,source_ref=source_ref,target_ref=target_ref,
                standard_ref=standard_ref,expected_pages=expected_pages)
            typed['source_membership_check']=membership
            typed['issues']+=issues;typed['pending']+=pending
            typed['status']='fail' if typed['issues'] else 'unverified' if typed['pending'] else 'pass'
            return typed
        for path,key in ((RUNTIME,'runtime_ref'),(SCHEMA,'schema_ref')):
            if scope.get(key)!=file_ref(path):raise ValueError('source_script_frozen_runtime_or_schema_changed')
        inputs=read_bound_json(packet['script_styles_bindings_ref'])
        if inputs.get('source')!=source_ref or inputs.get('target')!=target_ref:
            raise ValueError('script_style_target_binding_identity_changed')
        bindings=inputs['items']
        if not isinstance(bindings,list) or len(bindings)!=len(rows) or {b['id'] for b in bindings}!={r['id'] for r in rows}:
            raise ValueError('complete_source_script_binding_scope_changed')
        by_id={b['id']:b for b in bindings}
        target_owned=set()
        for target in bindings:
            for index in target['target_label_indices']:
                key=(target['page'],index)
                if key in target_owned:raise ValueError('target_script_member_duplicate_scope_binding')
                target_owned.add(key)
        # 同一物理页对仅枚举一次；PDF句柄仍逐个关闭，缓存只保留当前页的字形数据。
        source_page=None;target_page=None;source_native=None;target_native=None
        grouped={}
        for row in rows:
            key=(row['page'],by_id[row['id']]['page'],row['normalized_tolerance'],row['size_ratio_tolerance'],row['policy_scope_id'])
            grouped.setdefault(key,[]).append(row)
        result['checked_source_item_ids']=[]
        result['source_page_reads']=[];result['target_page_reads']=[]
        for key,group in sorted(grouped.items()):
            row=group[0];target=by_id[row['id']]
            # 同时仅持有一页；源片段和目标片段分别读取，跨页范围须先经显式适配。
            if source_page!=row['page']:
                source_native=None
                with fitz.open(source_ref['path']) as doc:source_native=glyphs(doc[row['page']-1])
                source_page=row['page']
                result['source_page_reads'].append(source_page)
            if target_page!=target['page']:
                target_native=None
                with fitz.open(target_ref['path']) as doc:
                    if type(target['page']) is not int or not 1<=target['page']<=len(doc):
                        raise ValueError('script_target_page_outside_document')
                    target_native=glyphs(doc[target['page']-1])
                target_page=target['page']
                result['target_page_reads'].append(target_page)
            def assess_group(members):
                bindings=[]
                for item in members:
                    actual=by_id[item['id']]
                    bindings.append({'source_id':item['id'],'label':item['label'],'source_script':item['source_script'],
                        'source_label_indices':item['source_label_indices'],'source_host_anchor_index':item['source_host_anchor_index'],
                        'target_label_indices':actual['target_label_indices'],'target_host_anchor_index':actual['target_host_anchor_index']})
                kwargs={'source_native':source_native,'target_native':target_native,'bindings':bindings,
                    'required_source_ids':[item['id'] for item in members],'normalized_tolerance':row['normalized_tolerance'],
                    'size_ratio_tolerance':row['size_ratio_tolerance'],'policy_scope_id':row['policy_scope_id']}
                report=assess_bound_script_styles(**kwargs)
                gate=validate_bound_script_report(report,**kwargs,expected_runtime_sha256=scope['runtime_ref']['sha256'],
                    expected_schema_sha256=scope['schema_ref']['sha256'])
                return report,gate
            report,gate=assess_group(group)
            # 一个未知标签不能使同批的真实失败变为未知；保留原逐项语义。
            evaluations=[(group,report,gate)] if report['component_decision']!='unverified' or len(group)==1 else [
                ([item],*assess_group([item])) for item in group]
            for members,report,gate in evaluations:
                ids=[item['id'] for item in members];result['checked_source_item_ids']+=ids
                reports.append({'id':ids[0] if len(ids)==1 else 'batch:'+','.join(ids),'item_ids':ids,
                    'source_page':row['page'],'target_page':target['page'],'actual_report':report,'recalculation_gate':gate})
                if report['component_decision']=='fail':
                    for actual_row in report['rows']:
                        if actual_row['component_decision']=='fail':issues.append({'id':actual_row['source_id'],
                            'rule':'actual_complete_source_script_style_mismatch','rows':[actual_row]})
                elif report['component_decision']=='unverified':pending.append({'id':ids[0],
                    'rule':'actual_source_script_style_requires_adapter','reason':report['reason']})
    except (KeyError,TypeError,ValueError,OSError,json.JSONDecodeError) as error:
        pending.append({'rule':'quality_source_script_scope_or_bindings_missing_invalid_changed','reason':str(error)})
    result['status']='fail' if issues else 'unverified' if pending else 'pass'
    return result
