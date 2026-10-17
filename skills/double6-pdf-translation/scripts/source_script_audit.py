"""逐引用基线/字号检查；未知与实际失败分别返回。"""
from pathlib import Path
import hashlib,importlib.util

_path=Path(__file__).resolve().parent/'source_script_binding.py'
_sha='4001e02107b587401497b0c3ac9eed718ec5a5d1f23ef9646bc285319e6a60ff'
if hashlib.sha256(_path.read_bytes()).hexdigest()!=_sha:raise ValueError('script_audit_binding_runtime_changed')
_spec=importlib.util.spec_from_file_location('script_audit_binding709',_path)
core=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(core)

def assess_bound_script_styles(source_native,target_native,bindings,*,required_source_ids,normalized_tolerance,size_ratio_tolerance,policy_scope_id):
    """调用方冻结适用容差、源清单及PDF身份；此组件仅判断已绑定字形的脚本样式。"""
    rows=[]
    try:
        if not core._number(normalized_tolerance,0,.02,open_minimum=True)or not core._number(size_ratio_tolerance,0,.01,open_minimum=True):
            raise ValueError('script_audit_declared_tolerance_invalid')
        if not isinstance(policy_scope_id,str)or not policy_scope_id:raise ValueError('script_audit_policy_scope_missing')
        if not isinstance(source_native,list)or not isinstance(target_native,list)or not source_native or not target_native:
            raise ValueError('script_audit_native_inventory_missing')
        if max(len(source_native),len(target_native))>50000:raise ValueError('script_audit_native_count_limit')
        for glyph in(*source_native,*target_native):core._native(glyph)
        if not isinstance(required_source_ids,list)or not 0<len(required_source_ids)<=256 or any(not isinstance(i,str)or not i for i in required_source_ids)or len(set(required_source_ids))!=len(required_source_ids):
            raise ValueError('script_audit_source_inventory_invalid')
        if not isinstance(bindings,list)or len(bindings)!=len(required_source_ids)or any(not isinstance(b,dict)or set(b)!=core.BINDING_FIELDS for b in bindings):
            raise ValueError('script_audit_binding_coverage_or_schema_invalid')
        if any(not isinstance(b['source_id'],str)for b in bindings)or {b['source_id']for b in bindings}!=set(required_source_ids):
            raise ValueError('script_audit_source_identity_mismatch')
        source_used=set();target_used=set();prepared=[]
        for b in bindings:
            si=core._indices(b['source_label_indices'],len(source_native));ti=core._indices(b['target_label_indices'],len(target_native))
            if source_used.intersection(si)or target_used.intersection(ti):raise ValueError('script_audit_duplicate_label_ownership')
            source_used.update(si);target_used.update(ti)
            sh=core._indices([b['source_host_anchor_index']],len(source_native))[0]
            th=core._indices([b['target_host_anchor_index']],len(target_native))[0]
            literal=b['label']
            if not isinstance(literal,str)or not literal:raise ValueError('script_audit_label_text_invalid')
            query=core.unicodedata.normalize('NFKC',literal)
            if core._text(source_native,si)!=query or core._text(target_native,ti)!=query:raise ValueError('script_audit_label_text_mismatch')
            for g in(source_native[sh],target_native[th],*[source_native[i]for i in si],*[target_native[i]for i in ti]):core._supported(g)
            if chr(source_native[sh]['unicode']).isspace()or chr(target_native[th]['unicode']).isspace():raise ValueError('script_audit_host_whitespace')
            sy=source_native[si[0]]['origin'][1];ty=target_native[ti[0]]['origin'][1]
            if any(abs(source_native[i]['origin'][1]-sy)>.003 for i in si):
                raise ValueError('script_audit_label_spans_multiple_baselines')
            sr=[source_native[i]['size']/source_native[sh]['size']for i in si]
            if max(sr)-min(sr)>.002:raise ValueError('script_audit_source_label_size_ambiguous')
            source_offset=(source_native[sh]['origin'][1]-sy)/source_native[sh]['size']
            if abs(source_offset)<=normalized_tolerance and abs(sr[0]-1)<=size_ratio_tolerance:category='normal'
            elif .05<abs(source_offset)<.8 and .3<sr[0]<.85:category='superscript'if source_offset>0 else'subscript'
            else:raise ValueError('script_audit_source_style_requires_adapter')
            if b['source_script']!=category:raise ValueError('script_audit_declared_source_style_mismatch')
            tr=[target_native[i]['size']/target_native[th]['size']for i in ti]
            target_offsets=[(target_native[th]['origin'][1]-target_native[i]['origin'][1])/target_native[th]['size']for i in ti]
            target_offset=target_offsets[0]
            baseline_spread=max(target_native[i]['origin'][1]for i in ti)-min(target_native[i]['origin'][1]for i in ti)
            errors={'normalized_baseline_error':max(abs(v-source_offset)for v in target_offsets),'size_ratio_error':max(abs(r-sr[0])for r in tr)}
            reasons=[]
            if baseline_spread>.003:reasons.append('target_script_label_spans_multiple_baselines')
            if errors['normalized_baseline_error']>normalized_tolerance:reasons.append('source_local_baseline_mismatch')
            if errors['size_ratio_error']>size_ratio_tolerance:reasons.append('source_local_size_ratio_mismatch')
            prepared.append((sh,th))
            rows.append({'source_id':b['source_id'],'label':literal,'source_script':category,'source_actual_normalized_offset':source_offset,
                'target_actual_normalized_offset':target_offset,'target_actual_normalized_offsets':target_offsets,
                'target_label_baseline_spread_pt':baseline_spread,'source_size_ratio':sr[0],'target_size_ratios':tr,
                **errors,'component_decision':'fail'if reasons else'pass','failure_reasons':reasons})
        if any(sh in source_used or th in target_used for sh,th in prepared):raise ValueError('script_audit_host_owned_as_label')
    except(ValueError,TypeError,KeyError)as error:
        return {'component_decision':'unverified','reason':str(error),'rows':[],
            'unknown_is_not_error_detected':True,'quality_pass':False}
    return {'component_decision':'fail'if any(r['component_decision']=='fail'for r in rows)else'pass','rows':rows,
        'policy_scope_id':policy_scope_id,'normalized_tolerance':normalized_tolerance,'size_ratio_tolerance':size_ratio_tolerance,
        'source_native_sha256':core._digest(source_native),'target_native_sha256':core._digest(target_native),
        'source_inventory_sha256':core._digest(required_source_ids),'binding_sha256':core._digest(bindings),
        'actual_pdf_identity_source_inventory_and_visual_review_still_required':True,'quality_pass':False}
