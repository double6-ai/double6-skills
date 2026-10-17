"""具名绑定的文字局部基线检查候选；不改写字形，不授予完整视觉/独立接受。"""
from __future__ import annotations
import hashlib,json,math,re,unicodedata,sys
from pathlib import Path
from source_script_binding import _native,_indices,_number

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def audit_local_binding(source_native,target_native,binding,*,normalized_tolerance,size_ratio_tolerance,policy_scope_id):
    """调用方须另外冻结完整源范围、宿主及字符等价政策；本组件仅重算具名原生几何。"""
    result={'component_decision':'unverified','issues':[],'pending':[],'quality_pass':False,
      'actual_font_outline_and_visual_acceptance_proved':False,'independent_scope_acceptance_proved':False}
    try:
        if not _number(normalized_tolerance,0,.02,open_minimum=True) or not _number(size_ratio_tolerance,0,.01,open_minimum=True):raise ValueError('declared_tolerance_invalid')
        if not isinstance(policy_scope_id,str) or not policy_scope_id:raise ValueError('frozen_policy_scope_missing')
        if not source_native or not target_native or max(len(source_native),len(target_native))>50000:raise ValueError('native_inventory_missing_or_oversized')
        for native in (source_native,target_native):
            for g in native:_native(g)
        si=_indices(binding['source_label_indices'],len(source_native));ti=_indices(binding['target_label_indices'],len(target_native))
        sh=_indices([binding['source_host_anchor_index']],len(source_native))[0]
        hosts=binding['target_host_indices']
        if not isinstance(hosts,list) or len(hosts)!=len(ti):raise ValueError('each_target_glyph_requires_explicit_host')
        for host in hosts:_indices([host],len(target_native))
        if sh in si or any(h in ti for h in hosts):raise ValueError('host_owned_as_label')
        source_text=''.join(chr(source_native[i]['unicode']) for i in si)
        target_text=''.join(chr(target_native[i]['unicode']) for i in ti)
        if any(0x2070<=ord(c)<=0x209f or ord(c) in (0xb2,0xb3,0xb9) for c in source_text+target_text):raise ValueError('intrinsic_script_requires_actual_font_outline_adapter')
        expected_source=binding['source_literal'];expected_target=binding['target_literal']
        if source_text!=expected_source or target_text!=expected_target:
            result['issues'].append({'rule':'actual_bound_label_identity_changed'})
        source_n=unicodedata.normalize('NFKC',source_text);target_n=unicodedata.normalize('NFKC',target_text)
        alias=binding.get('literal_adapter','exact')
        if alias=='exact':equivalent=source_n==target_n
        elif alias=='scientific_minus':
            if binding.get('semantic_role')!='unit_exponent' or binding['source_script']!='superscript':raise ValueError('scientific_minus_context_not_declared')
            equivalent=bool(re.fullmatch(r'[–−][0-9]+',source_n)) and source_n.replace('–','−')==target_n
        elif alias=='figure_separator':
            if binding.get('semantic_role')!='figure_reference' or binding['source_script']!='normal':raise ValueError('figure_reference_context_not_declared')
            equivalent=bool(re.fullmatch(r'[1-9][0-9]*[a-z](?:,[a-z])+',source_n)) and source_n.replace(',','、')==target_n
        else:raise ValueError('literal_adapter_unqualified')
        if not equivalent:result['issues'].append({'rule':'bound_literal_semantic_identity_mismatch'})
        def relative(native,index,host):
            g=native[index];h=native[host]
            if g['gid']<0 or h['gid']<0 or chr(h['unicode']).isspace():raise ValueError('host_or_glyph_identity_missing')
            dx,dy=h['direction'];length=math.hypot(dx,dy)
            if abs(length-1)>.001 or max(abs(a-b) for a,b in zip(g['direction'],h['direction']))>.00001:raise ValueError('nonrigid_or_mismatched_text_direction')
            dx/=length;dy/=length
            rise=(-dy*(h['origin'][0]-g['origin'][0])+dx*(h['origin'][1]-g['origin'][1]))/h['size']
            return rise,g['size']/h['size']
        sources=[relative(source_native,i,sh) for i in si];targets=[relative(target_native,i,h) for i,h in zip(ti,hosts)]
        if max(r for r,s in sources)-min(r for r,s in sources)>.003/source_native[sh]['size'] or max(s for r,s in sources)-min(s for r,s in sources)>.002:raise ValueError('source_label_baseline_or_size_ambiguous')
        offset,ratio=sources[0]
        if abs(offset)<=normalized_tolerance and abs(ratio-1)<=size_ratio_tolerance:category='normal'
        elif .05<abs(offset)<.8 and .3<ratio<.85:category='superscript' if offset>0 else 'subscript'
        else:raise ValueError('source_style_requires_qualified_adapter')
        if binding['source_script']!=category:raise ValueError('declared_source_style_mismatch')
        baseline_error=max(abs(r-offset) for r,s in targets);size_error=max(abs(s-ratio) for r,s in targets)
        if baseline_error>normalized_tolerance:result['issues'].append({'rule':'source_local_baseline_mismatch'})
        if size_error>size_ratio_tolerance:result['issues'].append({'rule':'source_local_size_ratio_mismatch'})
        result.update(source_id=binding['source_id'],source_literal=source_text,target_literal=target_text,
          source_actual_normalized_offset=offset,source_size_ratio=ratio,target_actual_relations=targets,
          normalized_baseline_error=baseline_error,size_ratio_error=size_error,
          source_native_sha256=digest(source_native),target_native_sha256=digest(target_native),binding_sha256=digest(binding),
          policy_scope_id=policy_scope_id,normalized_tolerance=normalized_tolerance,size_ratio_tolerance=size_ratio_tolerance)
    except (ValueError,KeyError,TypeError) as error:
        result['pending'].append({'rule':'local_script_adapter_unverified','reason':str(error)})
    result['component_decision']='fail' if result['issues'] else 'unverified' if result['pending'] else 'pass'
    return result

def validate_local_report(report,source_native,target_native,binding,**policy):
    actual=audit_local_binding(source_native,target_native,binding,**policy)
    if report!=actual:raise ValueError('local_script_report_not_derived_from_bound_inputs')
    return {'actual_component_recalculated':True,'component_decision':actual['component_decision'],'quality_pass':False}
