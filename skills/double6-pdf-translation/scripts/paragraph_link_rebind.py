"""完整段落层回写：按实际字形迁移注释矩形，原对象图和动作原位保留。"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import argparse, hashlib, json, math
import fitz
from native_line_spacing import glyphs, identity, compare_glyphs
from inline_attachment import normalized

POLICY = {'id':'glyph-centre-annotation-v1','probe_half_size_pt':.012,
          'glyph_position_tolerance_pt':.03,'maximum_changed_pages':8,
          'maximum_paragraph_glyphs':10000,'case_overrides_allowed':False}

def reference(path):
    path=Path(path).resolve()
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return {'path':str(path),'sha256':digest.hexdigest()}

def checked_ref(ref):
    p=Path(ref['path'])
    if not p.is_absolute() or not p.is_file() or reference(p)['sha256']!=ref['sha256']:
        raise ValueError('paragraph_link_input_identity_changed')
    return p

def centre(g):
    b=g['bbox'];return fitz.Point((b[0]+b[2])/2,(b[1]+b[3])/2)

def union(gs):
    if not gs:raise ValueError('empty_link_glyph_members')
    return fitz.Rect(min(g['bbox'][0] for g in gs),min(g['bbox'][1] for g in gs),
                     max(g['bbox'][2] for g in gs),max(g['bbox'][3] for g in gs))

def nonspace(gs):return [g for g in gs if normalized(chr(g['unicode']))]

def same_sequence(a,b):
    a,b=nonspace(a),nonspace(b)
    if len(a)!=len(b):raise ValueError('paragraph_complete_glyph_count_changed')
    for x,y in zip(a,b):
        if (x['unicode'],x['gid'],x['font'])!=(y['unicode'],y['gid'],y['font']) or abs(x['size']-y['size'])>.002 or abs(x['opacity']-y['opacity'])>1e-6 or len(x['color'])!=len(y['color']) or max(abs(i-j) for i,j in zip(x['color'],y['color']))>1e-6:
            raise ValueError('paragraph_font_gid_size_colour_changed')
    return a,b

def annotation_bindings(all_glyphs,owned,links):
    """只能完整拥有源标签；无成员、多段所有权、跨行和误点相邻字形均停止。"""
    keys={identity(g) for g in owned};bindings=[]
    for link in links:
        box=fitz.Rect(link['from'])
        members=[g for g in nonspace(all_glyphs) if g['type']==0 and box.contains(centre(g))]
        hit=[g for g in members if identity(g) in keys]
        touches=any(box.intersects(fitz.Rect(g['bbox'])) for g in nonspace(owned))
        if not hit:
            if touches:raise ValueError('link_intersects_paragraph_without_unambiguous_host')
            continue
        if len(hit)!=len(members):raise ValueError('link_label_mixed_paragraph_ownership')
        if len({identity(g) for g in members})!=len(members):raise ValueError('link_duplicate_member_identity')
        offsets=[i for i,g in enumerate(nonspace(owned)) if identity(g) in {identity(c) for c in members}]
        if offsets!=list(range(min(offsets),max(offsets)+1)):
            raise ValueError('link_label_members_not_contiguous')
        bindings.append({'source_xref':link['xref'],'offsets':offsets,'old_rect':list(box),
                         'old_member_bbox':list(union(members)),'label':''.join(chr(g['unicode']) for g in members)})
    return bindings

def rebound_rect(binding,new_owned,all_after):
    gs=[nonspace(new_owned)[i] for i in binding['offsets']]
    if max(g['origin'][1] for g in gs)-min(g['origin'][1] for g in gs)>.03:
        raise ValueError('link_label_split_requires_multiple_annotations')
    old=fitz.Rect(binding['old_rect']);bb=fitz.Rect(binding['old_member_bbox']);new=union(gs)
    padding=[old[i]-bb[i] for i in range(4)]
    if any(not math.isfinite(x) or abs(x)>max(g['size'] for g in gs)*2 for x in padding):
        raise ValueError('link_original_padding_unbounded')
    rect=fitz.Rect([new[i]+padding[i] for i in range(4)])
    keys={identity(g) for g in gs}
    if rect.is_empty or not all(rect.contains(centre(g)) for g in gs):raise ValueError('link_new_rectangle_misses_member')
    if any(rect.contains(centre(g)) and identity(g) not in keys for g in nonspace(all_after) if g['type']==0):
        raise ValueError('link_new_rectangle_contains_unrelated_glyph')
    return rect

def apply_plan(plan,output):
    if plan.get('schema_version')!='paragraph-link-rebind@1' or plan.get('policy')!=POLICY:
        raise ValueError('paragraph_link_policy_not_frozen')
    if set(plan)!={'schema_version','source','policy','units'}:raise ValueError('paragraph_link_unknown_plan_option')
    source=checked_ref(plan['source']);units=plan['units']
    if any(set(u)!={'id','page','body_size','glyphs','layer'} for u in units):raise ValueError('paragraph_link_unknown_unit_option')
    if not units or len({u['page'] for u in units})>POLICY['maximum_changed_pages'] or len({u['id'] for u in units})!=len(units):
        raise ValueError('paragraph_link_scope_budget')
    output=Path(output);output.mkdir(exist_ok=False)
    report={'schema_version':'paragraph-link-rebind-result@1','source':reference(source),'policy':POLICY,
            'rows':[],'case_overrides':0,'quality_pass':False,'human_acceptance':False}
    with fitz.open(source) as doc:
        original_pages=len(doc);original_link_total=sum(len(doc[i].get_links()) for i in range(len(doc)))
        for page_index in sorted({u['page']-1 for u in units}):
            page=doc[page_index]
            if page.rotation!=0:raise ValueError('paragraph_link_rotated_page_not_supported')
            before=glyphs(page);original_links=page.get_links()
            original_annots=doc.xref_get_key(page.xref,'Annots')
            annot_objects={l['xref']:doc.xref_object(l['xref'],compressed=False) for l in original_links}
            prepared=[];all_owned=[]
            for unit in [u for u in units if u['page']==page_index+1]:
                owned=json.loads(checked_ref(unit['glyphs']).read_text());layer=checked_ref(unit['layer'])
                if not 1<=len(owned)<=POLICY['maximum_paragraph_glyphs']:raise ValueError('paragraph_link_glyph_budget')
                count=Counter(identity(g) for g in owned);actual=Counter(identity(g) for g in before)
                if count-actual or any(actual[k]!=v for k,v in count.items()):raise ValueError('paragraph_source_glyph_identity_not_unique')
                for g in owned:
                    g.setdefault('type',0);g.setdefault('direction',[1.,0.]);g.setdefault('opacity',1.)
                if any(g['type']!=0 or g['direction']!=[1.,0.] or g['opacity']!=1 for g in owned):raise ValueError('paragraph_nonstandard_glyph_not_supported')
                with fitz.open(layer) as ld:
                    if len(ld)!=1 or ld[0].get_links():raise ValueError('paragraph_layer_requires_one_unannotated_page')
                    fresh=glyphs(ld[0]);same_sequence(owned,fresh)
                    body_before=[g for g in nonspace(owned) if abs(g['size']-unit['body_size'])<.003]
                    body_after=[g for g in nonspace(fresh) if abs(g['size']-unit['body_size'])<.003]
                    dx=min(g['origin'][0] for g in body_before)-min(g['origin'][0] for g in body_after)
                    dy=body_before[0]['origin'][1]-body_after[0]['origin'][1]
                    rect=ld[0].rect+(dx,dy,dx,dy)
                    if not page.rect.contains(rect):raise ValueError('paragraph_layer_outside_source_page')
                    moved=[]
                    for g in fresh:
                        c=dict(g);c['origin']=[g['origin'][0]+dx,g['origin'][1]+dy];c['bbox']=list(fitz.Rect(g['bbox'])+(dx,dy,dx,dy));moved.append(c)
                bindings=annotation_bindings(before,owned,original_links)
                prepared.append((unit,owned,layer,rect,moved,bindings));all_owned.extend(owned)
            if len({identity(g) for g in all_owned})!=len(all_owned):raise ValueError('paragraph_overlap_or_duplicate')
            keys={identity(g) for g in all_owned};protected=[g for g in before if identity(g) not in keys]
            for c in all_owned:
                p=centre(c);h=POLICY['probe_half_size_pt'];page.add_redact_annot(fitz.Rect(p.x-h,p.y-h,p.x+h,p.y+h),fill=False)
            page.apply_redactions(images=0,graphics=0,text=0);page=doc.reload_page(page)
            compare_glyphs(glyphs(page),protected,tolerance=.03)
            # redaction可能移除与探针相交的链接。复用原注释对象，恢复原引用数组。
            doc.xref_set_key(page.xref,'Annots',original_annots[1]);page=doc.reload_page(page)
            for xref,obj in annot_objects.items():
                if doc.xref_object(xref,compressed=False)!=obj:raise ValueError('annotation_object_changed_during_redaction')
            expected=list(protected)
            for unit,owned,layer,rect,moved,bindings in prepared:
                with fitz.open(layer) as ld:page.show_pdf_page(rect,ld,0,keep_proportion=False,overlay=True)
                expected.extend(moved)
            page=doc.reload_page(page);actual=glyphs(page);error=compare_glyphs(actual,expected,tolerance=.03)
            for unit,owned,layer,rect,moved,bindings in prepared:
                # 保存前的实际字形按完整位置/身份再次绑定；不能以预测几何代替产物。
                current=[]
                for g in moved:
                    hits=[a for a in actual if a['unicode']==g['unicode'] and a['gid']==g['gid'] and a['font']==g['font'] and max(abs(a['origin'][i]-g['origin'][i]) for i in (0,1))<.03]
                    if len(hits)!=1:raise ValueError('paragraph_actual_after_glyph_not_unique')
                    current.append(hits[0])
                links=[]
                for b in bindings:
                    newrect=rebound_rect(b,current,actual);pdfrect=newrect*~page.transformation_matrix
                    doc.xref_set_key(b['source_xref'],'Rect','['+' '.join(format(v,'.9f') for v in pdfrect)+']')
                    links.append({**b,'new_rect':list(newrect),'raw_action':doc.xref_get_key(b['source_xref'],'A'),'target_preserved':True})
                report['rows'].append({'id':unit['id'],'page':unit['page'],'glyphs':len(nonspace(current)),
                    'first_body_baseline_drift_pt':0.,'all_unaffected_glyphs_preserved':True,'maximum_position_error_pt':error,
                    'links':links,'actual_layer_rect':list(rect)})
            changed={b['source_xref'] for *_,bindings in prepared for b in bindings}
            for xref,obj in annot_objects.items():
                # 用对象副本逐键删除Rect后比较，动作/依赖xref/所有其它字段须原样保留。
                old=fitz.open();old.new_page();ox=old.get_new_xref();old.update_object(ox,obj)
                doc.xref_set_key(xref,'Rect',old.xref_get_key(ox,'Rect')[1]);now=doc.xref_object(xref,compressed=False)
                if now!=obj:raise ValueError('annotation_non_rect_field_changed')
                if xref in changed:
                    bound=next(b for row in report['rows'] if row['page']==page_index+1 for b in row['links'] if b['source_xref']==xref)
                    pdfrect=fitz.Rect(bound['new_rect'])*~page.transformation_matrix
                    doc.xref_set_key(xref,'Rect','['+' '.join(format(v,'.9f') for v in pdfrect)+']')
                old.close()
            report.setdefault('page_checks',[]).append({'page':page_index+1,'glyph_count_before':len(before),'glyph_count_after':len(actual),'link_count':len(original_links),'all_non_rect_annotation_fields_exact':True})
        candidate=output/'candidate.pdf';doc.save(candidate,garbage=0,deflate=True)
    with fitz.open(source) as before,fitz.open(candidate) as after:
        if len(after)!=original_pages:raise ValueError('paragraph_full_document_pages_changed')
        if sum(len(after[i].get_links()) for i in range(len(after)))!=original_link_total:raise ValueError('paragraph_saved_annotation_count_changed')
        rows_by_page={p:[r for r in report['rows'] if r['page']==p+1] for p in range(len(after))}
        for p in range(len(after)):
            aa,bb=before[p].get_links(),after[p].get_links()
            if [l['xref'] for l in aa]!=[l['xref'] for l in bb]:raise ValueError('paragraph_saved_annotation_order_or_xref_changed')
            for a,b in zip(aa,bb):
                x=a['xref'];old_obj=before.xref_object(x,compressed=False)
                oldrect=before.xref_get_key(x,'Rect')[1];newrect=after.xref_get_key(x,'Rect')[1]
                after.xref_set_key(x,'Rect',oldrect)
                if after.xref_object(x,compressed=False)!=old_obj:raise ValueError('paragraph_saved_non_rect_annotation_changed')
                after.xref_set_key(x,'Rect',newrect)
                changed=[l for r in rows_by_page[p] for l in r['links'] if l['source_xref']==x]
                wanted=changed[0]['new_rect'] if changed else list(a['from'])
                if max(abs(i-j) for i,j in zip(wanted,b['from']))>.03:raise ValueError('paragraph_saved_link_rectangle_changed')
            if not rows_by_page[p]:compare_glyphs(glyphs(after[p]),glyphs(before[p]),tolerance=.03)
        report.update(candidate=reference(candidate),pages=original_pages,source_annotations=original_link_total,
                      saved_annotations=original_link_total,saved_full_object_actions_exact=True,saved_unmodified_pages_glyphs_exact=True)
    (output/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

# Explicit source-authored annotation-only route; the original paragraph route above
# retains its own policy. This route never rewrites text or page content.
RECT_FIT_POLICY={'id':'source-authored-typed-annotation-rect-fit-v2','goto_padding_pt':0,
    'uri_padding':'original_source_native_row_bbox_four_sides','maximum_uri_padding_pt':3,
    'maximum_pages':5,'maximum_annotations':200,'raster_dpi':144,
    'pdf_decimal_digits':9,'serialization_tolerance_pt':.001,
    'case_overrides_allowed':False,'maximum_new_candidates':1}


def _rect_ref_json(evidence):
    from independent_latex import reject_symlink_ancestors
    path=reject_symlink_ancestors(evidence['path'])
    checked_ref(evidence)
    return json.loads(path.read_text())


def _rect_positive(box):
    r=fitz.Rect(box)
    if len(box)!=4 or any(not math.isfinite(v) for v in box) or r.is_empty or r.is_infinite:
        raise ValueError('annotation_rect_supported_positive_paint_bounds_required')
    return r


def _rect_intersects(a,b):
    overlap=fitz.Rect(a)&fitz.Rect(b)
    return overlap.width>0 and overlap.height>0


def _rect_nontext_paint(page,protected_regions):
    # MuPDF's executed bboxlog includes stroked width/cap/CTM, unlike the
    # centre-line rect from get_drawings(). Zero-area paint remains unsupported.
    bounds=[]
    for kind,box in page.get_bboxlog():
        if kind=='fill-text':continue
        if kind not in {'fill-path','stroke-path'}:
            raise ValueError('annotation_rect_unsupported_image_or_paint')
        bounds.append({'kind':kind,'bounds':list(_rect_positive(list(box)))})
    for drawing in page.get_drawings(extended=True):
        if drawing['type']=='clip':
            clip=_rect_positive(list(drawing['scissor']))
            if not any(fitz.Rect(role).contains(clip) for role in protected_regions):
                raise ValueError('annotation_rect_unsupported_clip_scope')
        elif drawing['type'] not in {'s','f','fs'}:
            raise ValueError('annotation_rect_unsupported_drawing_group')
    if page.first_annot is not None or page.first_widget is not None:
        raise ValueError('annotation_rect_visible_annotation_or_widget_unsupported')
    return bounds


def _rect_union_and_clean(host,records,whole,protected_regions,nontext,proposed=None):
    keys={identity(g) for g in host}
    if len(keys)!=len(host) or not host or len(records)!=len(host):
        raise ValueError('annotation_rect_complete_unique_host_required')
    painted=[]
    for g,row in zip(host,records):
        if row.get('gid')!=g['gid']:raise ValueError('annotation_rect_actual_host_gid_changed')
        box=row.get('ink_bounds')
        if box is None:
            if row.get('nonpainting_outline') is not True or row.get('empty_actual_font_outline_verified') is not True:
                raise ValueError('annotation_rect_host_outline_unknown')
        else:painted.append(_rect_positive(box))
    if not painted:raise ValueError('annotation_rect_no_actual_painted_host')
    ink_union=fitz.Rect(min(r.x0 for r in painted),min(r.y0 for r in painted),max(r.x1 for r in painted),max(r.y1 for r in painted))
    rect=ink_union if proposed is None else _rect_positive(list(proposed))
    if not rect.contains(ink_union):raise ValueError('annotation_rect_source_padding_misses_actual_host_ink')
    for member in whole:
        if identity(member['glyph']) in keys:continue
        ink=member['ink'];box=ink.get('ink_bounds')
        if box is None:
            if ink.get('nonpainting_outline') is not True or ink.get('empty_actual_font_outline_verified') is not True:
                raise ValueError('annotation_rect_foreign_paint_unknown')
        elif _rect_intersects(rect,_rect_positive(box)):
            raise ValueError('annotation_rect_foreign_glyph_paint_intersection')
    if any(_rect_intersects(rect,box) for box in protected_regions):
        raise ValueError('annotation_rect_protected_role_intersection')
    if any(_rect_intersects(rect,row['bounds']) for row in nontext):
        raise ValueError('annotation_rect_foreign_nontext_paint_intersection')
    return rect


def _rect_native_uri_projection(original,doc,row):
    from qa_action_bindings import actual_action,measured_glyph_binding
    from inline_link_styles import project_link_rows
    a,b=row['source_action'],row['target_action']
    if a['kind']!='URI' or a.get('uri')!=b.get('uri') or actual_action(original,a['page'],a['xref'])!=a:
        raise ValueError('annotation_rect_source_uri_action_changed')
    source=measured_glyph_binding(original,a['page'],row['source_intended_host']['glyphs'])
    target=measured_glyph_binding(doc,b['page'],row['target_intended_host']['glyphs'])
    def native_row(gs):
        rows=project_link_rows([{**g,'link_index':0} for g in gs],[{'uri':a['uri'],'underline_offset_pt':0,'underline_width_pt':0}])
        if len(rows)!=1:raise ValueError('annotation_rect_complete_single_native_uri_row_required')
        return rows[0]['rect']
    src=native_row(source);dst=native_row(target);old=a['rectangle']
    padding=[src[0]-old[0],src[1]-old[1],old[2]-src[2],old[3]-src[3]]
    if any(not math.isfinite(v) or abs(v)>RECT_FIT_POLICY['maximum_uri_padding_pt'] for v in padding):
        raise ValueError('annotation_rect_original_uri_padding_unbounded')
    derived=[dst[0]-padding[0],dst[1]-padding[1],dst[2]+padding[2],dst[3]+padding[3]]
    return derived,{'rule':'original_source_native_row_bbox_four_sides','source_row_bbox':src,
        'source_original_rect':old,'source_padding_pt':padding,'target_row_bbox':dst}


def _rect_complete_literal(row,host):
    call=row['source_authored_call']
    expected=call.get('literal_label') if call['command']=='href' else call.get('displayed_label_from_actual_author_metadata')
    # This finite producer supports identity URI labels and source-author
    # generated reference labels. Translated arbitrary URI prose is unsupported.
    if not isinstance(expected,str) or not expected or ''.join(chr(g['unicode']) for g in host)!=expected:
        raise ValueError('annotation_rect_complete_source_authored_label_mismatch')


def _rect_protected_rows(ledger,exclusion,docs):
    from qa_action_bindings import measured_glyph_binding
    if exclusion is None:
        if any('source_protected_distribution_role_ref' in row for row in ledger['bindings']):
            raise ValueError('annotation_rect_protected_role_evidence_required')
        return {}
    if exclusion['source']!=ledger['source'] or exclusion['target']!=ledger['target']:
        raise ValueError('annotation_rect_protected_input_changed')
    if any(exclusion.get(k) is not True for k in ('same_current_pixels','same_actual_glyphs','disjoint_from_all_ordinary_actions','outline_identity_unknown_retained')):
        raise ValueError('annotation_rect_protected_role_scope_unverified')
    protected={};digests=[]
    for row in exclusion['stamp']:
        role=_rect_ref_json(row['source_role_ref']);side=row['side'];doc=docs[side]
        page=doc[row['page']-1];measured_glyph_binding(doc,row['page'],row['glyphs'])
        box=_rect_positive(row['crop'])
        if not page.rect.contains(box):raise ValueError('annotation_rect_protected_crop_outside_page')
        pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=box,annots=False)
        digest=hashlib.sha256(pix.samples).hexdigest()
        if digest!=row['pixel_digest'] or [pix.width,pix.height,pix.n]!=row['dimensions']:
            raise ValueError('annotation_rect_current_protected_pixels_changed')
        resources=[{'xref':f[0],'basefont':f[3],'resource':f[4],
            'object_sha256':hashlib.sha256(doc.xref_object(f[0],compressed=True).encode()).hexdigest()} for f in page.get_fonts(full=True)]
        if resources!=row['resources']:raise ValueError('annotation_rect_protected_resources_changed')
        digests.append((digest,row['dimensions']))
        if side=='target':protected[row['page']]=row
    if len(digests)!=2 or digests[0]!=digests[1]:raise ValueError('annotation_rect_protected_pixel_pair_changed')
    for row in ledger['bindings']:
        if 'source_protected_distribution_role_ref' in row:
            item=protected.get(row['target_action']['page'])
            if item is None or item['source_role_ref']!=row['source_protected_distribution_role_ref']:
                raise ValueError('annotation_rect_protected_source_role_mismatch')
    return protected


def _rect_page_paint(doc,page_number,protected):
    from qa_action_bindings import actual_ink,measured_glyph_binding
    page=doc[page_number-1];native=glyphs(page);exclusion=protected.get(page_number)
    excluded=[];regions=[]
    if exclusion:
        excluded=measured_glyph_binding(doc,page_number,exclusion['glyphs']);regions=[exclusion['crop']]
    keys={identity(g) for g in excluded};actual=[g for g in native if identity(g) not in keys]
    if len(native)-len(actual)!=len(excluded):raise ValueError('annotation_rect_protected_glyphs_not_unique')
    if any(g['type']!=0 or g.get('opacity')!=1 for g in actual):
        raise ValueError('annotation_rect_hidden_or_stroked_text_unsupported')
    records=actual_ink(doc,page_number,actual)
    return [{'glyph':g,'ink':row} for g,row in zip(actual,records)],regions,_rect_nontext_paint(page,regions)


def apply_rect_only_plan(plan,output):
    from independent_latex import reject_symlink_ancestors
    from qa_action_bindings import actual_action,measured_glyph_binding
    fields={'schema_version','source','host_ledger_ref','protected_role_exclusion_ref','proposal_ref','approval_ref','implementation_refs','policy'}
    if set(plan)!=fields or plan['schema_version']!='annotation-rect-fit@1' or plan['policy']!=RECT_FIT_POLICY:
        raise ValueError('annotation_rect_frozen_plan_required')
    for item in plan['implementation_refs']:checked_ref(item)
    if reference(__file__) not in plan['implementation_refs']:raise ValueError('annotation_rect_actual_producer_source_missing')
    proposal=_rect_ref_json(plan['proposal_ref']);approval=_rect_ref_json(plan['approval_ref']);ledger=_rect_ref_json(plan['host_ledger_ref'])
    if (proposal['input_pdf_ref']!=plan['source'] or proposal['source_authored_host_ledger_ref']!=plan['host_ledger_ref']
        or proposal.get('protocol')!='source_authored_typed_annotation_rect_fit_v2'
        or approval['proposal_ref']!=plan['proposal_ref'] or approval['status']!='typed_source_derived_rule_approved_before_only_candidate'):
        raise ValueError('annotation_rect_approved_input_mismatch')
    if (ledger['target']!=plan['source'] or ledger['kind']!='finite_source_authored_action_host_roles'
        or ledger['status']!='pass_finite_source_authored_action_semantics_only'):
        raise ValueError('annotation_rect_independent_source_authored_roles_required')
    for name in ('source','target','standard','source_tex_ref','source_aux_ref','target_aux_ref','source_bbl_ref','source_mapping_ref'):
        checked_ref(ledger[name])
    target=reject_symlink_ancestors(checked_ref(plan['source']));source=reject_symlink_ancestors(checked_ref(ledger['source']))
    output=reject_symlink_ancestors(output);output.mkdir(parents=True,exist_ok=False)
    exclusion=_rect_ref_json(plan['protected_role_exclusion_ref']) if plan['protected_role_exclusion_ref'] else None
    changes=[];unknown=[];objects={};before_pages=[]
    with fitz.open(target) as doc,fitz.open(source) as original:
        if doc.is_encrypted or not 1<=len(doc)<=RECT_FIT_POLICY['maximum_pages']:
            raise ValueError('annotation_rect_document_scope_unsupported')
        actual={(p.number+1,l['xref']) for p in doc for l in p.get_links()}
        declared={(r['target_action']['page'],r['target_action']['xref']) for r in ledger['bindings']}
        if len(actual)>RECT_FIT_POLICY['maximum_annotations'] or actual!=declared or len(declared)!=len(ledger['bindings']):
            raise ValueError('annotation_rect_complete_action_inventory_required')
        protected=_rect_protected_rows(ledger,exclusion,{'source':original,'target':doc})
        all_paint={}
        for page in doc:
            if page.rotation!=0:raise ValueError('annotation_rect_rotation_unsupported')
            all_paint[page.number+1]=_rect_page_paint(doc,page.number+1,protected)
            for link in page.get_links():
                if doc.xref_get_key(link['xref'],'AP')!=('null','null'):
                    raise ValueError('annotation_rect_visible_appearance_unsupported')
            before_pages.append({'geometry':[list(page.mediabox),list(page.cropbox),page.rotation],
                'text':page.get_text('rawdict'),'glyphs':glyphs(page),'fonts':page.get_fonts(full=True),
                'images':page.get_images(full=True),'drawings':page.get_drawings(extended=True),
                'annots':doc.xref_get_key(page.xref,'Annots')})
        # Capture every actual xref stream, not only page Contents; preserving
        # font/image/Forms compressed bytes is part of the Rect-only boundary.
        before_objects={x:doc.xref_object(x,compressed=False) for x in range(1,doc.xref_length())}
        before_streams={x:hashlib.sha256(doc.xref_stream_raw(x)).hexdigest() for x in range(1,doc.xref_length()) if doc.xref_is_stream(x)}
        before_decoded={x:hashlib.sha256(doc.xref_stream(x)).hexdigest() for x in before_streams}
        before_trailer=doc.xref_object(-1,compressed=False);before_id=doc.xref_get_key(-1,'ID')
        for row in ledger['bindings']:
            action=row['target_action'];page=doc[action['page']-1];xref=action['xref']
            if actual_action(doc,action['page'],xref)!=action:raise ValueError('annotation_rect_actual_action_changed')
            objects[xref]=doc.xref_get_key(xref,'Rect')
            if 'source_protected_distribution_role_ref' in row:
                unknown.append({'page':action['page'],'xref':xref,'role':'source_protected_distribution_identity','rect_changed':False,'outline_fit':'unverified_not_attempted'})
                continue
            call=row.get('source_authored_call')
            if not isinstance(call,dict) or call.get('command') not in {'cite','ref','eqref','href'}:
                raise ValueError('annotation_rect_source_authored_host_purpose_missing')
            host=measured_glyph_binding(doc,action['page'],row['target_intended_host']['glyphs'])
            _rect_complete_literal(row,host)
            whole,regions,nontext=all_paint[action['page']];by_id={identity(m['glyph']):m['ink'] for m in whole}
            records=[by_id[identity(g)] for g in host]
            for old,new in zip(row['target_intended_host']['ink'],records):
                for key in ('gid','font_sha256','ink_bounds','origin','direction'):
                    if old.get(key)!=new.get(key):raise ValueError('annotation_rect_reviewed_host_actual_ink_changed')
            uri_evidence=None;proposed=None
            if action['kind']=='URI':proposed,uri_evidence=_rect_native_uri_projection(original,doc,row)
            elif action['kind']!='GoTo':raise ValueError('annotation_rect_actual_action_kind_unsupported')
            rect=_rect_union_and_clean(host,records,whole,regions,nontext,proposed=proposed)
            if not page.rect.contains(rect):raise ValueError('annotation_rect_derived_rect_outside_page')
            pdfrect=rect*~page.transformation_matrix
            doc.xref_set_key(xref,'Rect','['+' '.join(format(v,'.9f') for v in pdfrect)+']')
            changes.append({'page':action['page'],'xref':xref,'old_rect':action['rectangle'],'derived_rect':list(rect),
                'geometry_rule':'source_native_uri_padding' if uri_evidence else 'goto_actual_ink_union_zero_padding',
                'uri_source_projection':uri_evidence,'goto_padding_pt':None if uri_evidence else 0,'complete_host_glyphs':len(host),'source_authored_call':call})
        candidate=output/'candidate.pdf'
        doc.save(candidate,garbage=0,clean=False,deflate=False,deflate_images=False,deflate_fonts=False,
                 no_new_id=True,encryption=fitz.PDF_ENCRYPT_KEEP,appearance=False)
    page_checks=[]
    with fitz.open(target) as before,fitz.open(candidate) as after:
        if before.xref_length()!=after.xref_length():raise ValueError('annotation_rect_saved_xref_count_changed')
        if after.xref_get_key(-1,'ID')!=before_id:raise ValueError('annotation_rect_saved_trailer_id_changed')
        streams={x:hashlib.sha256(after.xref_stream_raw(x)).hexdigest() for x in range(1,after.xref_length()) if after.xref_is_stream(x)}
        decoded={x:hashlib.sha256(after.xref_stream(x)).hexdigest() for x in streams}
        if streams!=before_streams or decoded!=before_decoded:raise ValueError('annotation_rect_saved_raw_or_decoded_stream_changed')
        # Compare dictionary objects with only the old Rect restored in memory.
        # The comparison document is never saved or used as the new candidate.
        for x,value in before_objects.items():
            current=after.xref_get_key(x,'Rect') if x in objects else None
            if x in objects:after.xref_set_key(x,'Rect',objects[x][1])
            if after.xref_object(x,compressed=False)!=value:raise ValueError('annotation_rect_saved_non_rect_object_changed')
            if x in objects:after.xref_set_key(x,'Rect',current[1])
        for index in range(len(before)):
            a,b=before[index],after[index];snapshot=before_pages[index]
            current={'geometry':[list(b.mediabox),list(b.cropbox),b.rotation],'text':b.get_text('rawdict'),
                'glyphs':glyphs(b),'fonts':b.get_fonts(full=True),'images':b.get_images(full=True),
                'drawings':b.get_drawings(extended=True),'annots':after.xref_get_key(b.xref,'Annots')}
            if current!=snapshot:raise ValueError('annotation_rect_saved_page_evidence_changed')
            aa,bb=a.get_links(),b.get_links()
            if [l['xref'] for l in aa]!=[l['xref'] for l in bb]:raise ValueError('annotation_rect_saved_action_order_changed')
            for change in [r for r in changes if r['page']==index+1]:
                link=next(l for l in bb if l['xref']==change['xref']);saved=fitz.Rect(link['from'])
                if max(abs(u-v) for u,v in zip(saved,change['derived_rect']))>RECT_FIT_POLICY['serialization_tolerance_pt']:
                    raise ValueError('annotation_rect_saved_numerical_roundtrip_exceeded')
                whole,regions,nontext=all_paint[index+1]
                host=next(r['target_intended_host']['glyphs'] for r in ledger['bindings'] if r['target_action']['xref']==change['xref'])
                keys={identity(g) for g in host}
                if any(m['ink'].get('ink_bounds') and identity(m['glyph']) not in keys and _rect_intersects(saved,m['ink']['ink_bounds']) for m in whole):
                    raise ValueError('annotation_rect_saved_foreign_glyph_intersection')
                if any(_rect_intersects(saved,box) for box in regions) or any(_rect_intersects(saved,r['bounds']) for r in nontext):
                    raise ValueError('annotation_rect_saved_foreign_paint_intersection')
                host_bounds=fitz.Rect(change['derived_rect']);tol=RECT_FIT_POLICY['serialization_tolerance_pt']
                if not (saved+(-tol,-tol,tol,tol)).contains(host_bounds):
                    raise ValueError('annotation_rect_saved_complete_host_not_contained')
                change['saved_rect']=list(saved)
            pa=a.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False,annots=True)
            pb=b.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False,annots=True)
            if (pa.width,pa.height,pa.n,pa.samples)!=(pb.width,pb.height,pb.n,pb.samples):
                raise ValueError('annotation_rect_saved_full_page_pixels_changed')
            page_checks.append({'page':index+1,'dpi':144,'width':pa.width,'height':pa.height,
                'samples_sha256':hashlib.sha256(pa.samples).hexdigest(),'pixels_exact':True,'glyphs_fonts_content_actions_exact':True})
    result={'protocol':'source_authored_typed_annotation_rect_fit_v2','status':'candidate','input_ref':plan['source'],
        'host_ledger_ref':plan['host_ledger_ref'],'candidate_ref':reference(candidate),'producer_ref':reference(__file__),
        'policy':RECT_FIT_POLICY,'changes':changes,'unverified_roles':unknown,'page_checks':page_checks,
        'raw_and_decoded_streams_exact':True,'all_xref_objects_except_rect_exact':True,'original_trailer':before_trailer,
        'trailer_id_exact':True,'container_serialization_byte_identity_claimed':False,
        'quality_pass':False,'human_acceptance':False,'model_calls':0}
    (output/'REPORT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('plan',type=Path);p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--annotation-only',action='store_true');args=p.parse_args()
    result=(apply_rect_only_plan if args.annotation_only else apply_plan)(json.loads(args.plan.read_text()),args.output_dir)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','page_checks')},ensure_ascii=False))
if __name__=='__main__':main()
