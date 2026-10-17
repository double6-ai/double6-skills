"""按源先行核定的标签，复查实际PDF字色、逐行下划线和URI点击区。

此模块不认证审校人员，也不以没有可点击URI证明图像、内部目标或图中文字通过。
"""
from __future__ import annotations
import math
import fitz
from qa_source_contract import file_ref
from native_line_spacing import glyphs
from inline_link_styles import bind_link_labels,project_link_rows

def _close(a,b,tolerance):
    return len(a)==len(b) and all(math.isfinite(v) for v in (*a,*b)) and max((abs(x-y) for x,y in zip(a,b)),default=0)<=tolerance

def _box(value,page):
    if not isinstance(value,list) or len(value)!=4 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in value):raise ValueError('link_finite_region_required')
    rect=fitz.Rect(value)
    if rect.is_empty or not page.rect.contains(rect):raise ValueError('link_region_outside_page')
    return rect

def audit_native_link_batch(source_ref,target_ref,regions,*,source_pages,target_pages=None,geometry_tolerance_pt=.5,maximum_glyphs=100000,
        action_binding_ref=None,standard_ref=None,reviewer_id=None,producer_id=None,authorization_ref=None):
    """一次最多5源页和5译页；每个非空URI注释必须恰好被一个核定区域覆盖。"""
    if not source_pages or len(source_pages)>5 or source_pages!=sorted(set(source_pages)) or not 0<geometry_tolerance_pt<=.75 or not 1<=maximum_glyphs<=200000:raise ValueError('native_link_batch_limits')
    for ref in (source_ref,target_ref):
        if file_ref(ref['path'])!=ref:raise ValueError('native_link_pdf_identity_changed')
    if len(regions)>1000 or len({r['id'] for r in regions})!=len(regions):raise ValueError('native_link_region_count_or_duplicate')
    issues=[];pending=[];measured=[];counter=0;covered={'source':set(),'target':set()}
    action_audit=None;action_closed={'source':set(),'target':set()};protected_uris={'source':set(),'target':set()}
    if action_binding_ref is not None:
        from qa_action_bindings import audit_action_bindings
        action_audit=audit_action_bindings(action_binding_ref,source_ref=source_ref,target_ref=target_ref,
            standard_ref=standard_ref,reviewer_id=reviewer_id,producer_id=producer_id,authorization_ref=authorization_ref)
        issues+=action_audit['issues'];pending+=action_audit['pending']
        if action_audit['status']=='pass':
            action_closed={side:{tuple(v) for v in action_audit['accepted_annotations'][side]} for side in ('source','target')}
            protected_uris={side:{tuple(v) for v in action_audit['protected_uri_annotations'][side]} for side in ('source','target')}
    target_pages=sorted({r['target_page'] for r in regions}) or source_pages if target_pages is None else target_pages
    if not target_pages or target_pages!=sorted(set(target_pages)):raise ValueError('native_link_target_page_scope_invalid')
    if len(target_pages)>5:raise ValueError('native_link_target_page_batch_limit')
    def issue(rule,rid,side):issues.append({'rule':rule,'id':rid,'side':side})
    with fitz.open(source_ref['path']) as source,fitz.open(target_ref['path']) as target:
        if any(type(p)is not int or not 1<=p<=len(source) for p in source_pages) or any(type(p)is not int or not 1<=p<=len(target) for p in target_pages):raise ValueError('native_link_page_scope_invalid')
        for region in regions:
            if region['source_page'] not in source_pages or region['target_page'] not in target_pages:raise ValueError('native_link_region_outside_batch')
            links=region['links']
            if not links:raise ValueError('native_link_nonempty_region_required')
            for link in links:
                # 标签可翻译；继承的颜色、URI、线宽、偏移和点击框padding不能由译文另定。
                for field in ('color','underline_width_pt','underline_offset_pt','click_padding_pt','underlined'):
                    if link['source'].get(field)!=link['target'].get(field):raise ValueError('native_link_source_target_style_contract_changed')
            if region['source_base_color']!=region['target_base_color']:raise ValueError('native_link_base_color_contract_changed')
            for side,doc in (('source',source),('target',target)):
                page_no=region[side+'_page'];page=doc[page_no-1];rect=_box(region[side+'_bbox'],page)
                actual=[{**g,'text':chr(g['unicode'])} for g in glyphs(page) if g['type']!=3 and g.get('opacity',1)>0 and rect.contains(fitz.Point(g['origin']))]
                actual=[{**g,'color':g['color']*3 if len(g['color'])==1 else g['color']} for g in actual]
                counter+=len(actual)
                if counter>maximum_glyphs:raise ValueError('native_link_glyph_limit')
                projected_specs=[{**link[side],'uri':link['uri']} for link in links]
                try:expected=bind_link_labels(actual,projected_specs,region[side+'_base_color']);rows=project_link_rows(expected,projected_specs)
                except ValueError as exc:
                    issue('native_link_label_missing_ambiguous_or_overlap',region['id'],side);continue
                for a,e in zip(actual,expected):
                    if not _close(a['color'],e['color'],.01):
                        issue('native_link_color_scope_or_source_style',region['id'],side);break
                annots=[a for a in page.get_links() if a['kind']==fitz.LINK_URI and rect.intersects(a['from'])]
                matched=set();segments=[]
                for drawing in page.get_drawings():
                    if drawing.get('color') is None:continue
                    for item in drawing['items']:
                        if item[0]=='l' and abs(item[1].y-item[2].y)<=.02:
                            segments.append({'x0':min(item[1].x,item[2].x),'x1':max(item[1].x,item[2].x),'y':(item[1].y+item[2].y)/2,
                                             'color':drawing['color'],'width':drawing['width']})
                for row in rows:
                    spec=projected_specs[row['link_index']];padding=spec.get('click_padding_pt',[0,0,0,0])
                    if len(padding)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>3 for v in padding):raise ValueError('native_link_padding_not_bounded')
                    box=[row['rect'][0]-padding[0],row['rect'][1]-padding[1],row['rect'][2]+padding[2],row['rect'][3]+padding[3]]
                    candidates=[(i,a) for i,a in enumerate(annots) if a.get('uri')==row['uri'] and _close(list(a['from']),box,geometry_tolerance_pt)]
                    if len(candidates)!=1 or candidates[0][0] in matched:issue('native_link_uri_click_rect_scope_or_duplicate',region['id'],side)
                    else:
                        identity=(page_no,candidates[0][1]['xref'])
                        if identity in covered[side]:issue('native_link_annotation_bound_to_multiple_regions',region['id'],side)
                        matched.add(candidates[0][0]);covered[side].add(identity)
                    if spec.get('underlined'):
                        for segment in row['segments']:
                            nearby=[s for s in segments if abs(s['y']-row['underline_y'])<=geometry_tolerance_pt and s['x1']>segment['x0'] and s['x0']<segment['x1']]
                            good=[s for s in nearby if _close([s['x0'],s['x1']],[segment['x0'],segment['x1']],geometry_tolerance_pt)
                                  and _close(s['color'],segment['color'],.01) and abs(s['width']-row['underline_width'])<=.05]
                            if len(good)!=1 or len(nearby)!=1:issue('native_link_underline_missing_or_outside_label',region['id'],side)
                if len(matched)!=len(annots):issue('native_link_extra_or_unbound_click_rect',region['id'],side)
                measured.append({'id':region['id'],'side':side,'page':page_no,'glyphs':len(actual),'link_rows':len(rows),'uri_annotations':len(annots)})
        for side,doc,pages in (('source',source,source_pages),('target',target,target_pages)):
            for number in pages:
                for annot in doc[number-1].get_links():
                    if annot['kind']!=fitz.LINK_URI and (number,annot['xref']) not in action_closed[side]:
                        pending.append({'page':number,'side':side,'rule':'non_uri_destination_requires_independent_binding'})
                    elif annot['kind']==fitz.LINK_URI and (number,annot['xref']) not in covered[side]|protected_uris[side]:
                        pending.append({'page':number,'side':side,'rule':'native_uri_annotation_not_in_source_first_registry'})
        if action_audit and action_audit['status']=='pass':
            own={r['id'] for r in regions}
            for binding in action_audit['native_uri_style_bindings']:
                if binding['source'][0] not in source_pages:continue
                if binding['region_id'] not in own or any(tuple(binding[side]) not in covered[side] for side in ('source','target')):
                    pending.append({'rule':'native_uri_action_style_binding_incomplete','region_id':binding['region_id']})
    for ref in (source_ref,target_ref):
        if file_ref(ref['path'])!=ref:raise ValueError('native_link_pdf_changed_during_audit')
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,
            'measurements':measured,'source_pages':source_pages,'target_pages':target_pages,'quality_pass':False,
            'independent_action_check':action_audit}
