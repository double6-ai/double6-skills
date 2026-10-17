"""完整原生动作的独立绑定审计；实际动作、宿主及目标锚点均重新读取。"""
from __future__ import annotations
import hashlib
import json
import math
from io import BytesIO
import fitz
from pypdf.generic import read_object, DictionaryObject
from qa_source_contract import file_ref, read_bound_json, text_digest
from native_line_spacing import glyphs, identity
from remote_destination_audit import source_destination
from glyph_ink_geometry import EmbeddedGlyphInk
from qa_visual_risk import audit_crop
from translation_coverage import normalized

PROTOCOL = 'independent_complete_native_actions_v1'
MAX_PAGES, MAX_ACTIONS, MAX_GLYPHS = 5, 1000, 50000


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def _finite_rect(value, page):
    if (not isinstance(value, list) or len(value) != 4 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                not math.isfinite(v) for v in value)):
        raise ValueError('action_finite_rectangle_required')
    rect = fitz.Rect(value)
    if rect.is_empty or not page.rect.contains(rect):
        raise ValueError('action_rectangle_outside_actual_page')
    return rect


def actual_action(doc, page_number, xref):
    """禁止链式或附加动作；GoTo读取原生名称树/XYZ而非公共to摘要。"""
    if type(page_number) is not int or not 1 <= page_number <= len(doc):
        raise ValueError('action_page_scope')
    candidates = [a for a in doc[page_number-1].get_links() if a['xref'] == xref]
    if len(candidates) != 1:
        raise ValueError('action_actual_annotation_missing_or_duplicate')
    if doc.xref_get_key(xref, 'AA') != ('null', 'null') or doc.xref_get_key(xref, 'A/Next') != ('null', 'null'):
        raise ValueError('action_chained_or_additional_rejected')
    fields = {k: list(doc.xref_get_key(xref, k)) for k in
              ('Dest', 'A', 'A/S', 'A/D', 'A/URI', 'A/Next', 'AA')}
    if any(len(str(v).encode()) > 65536 for v in fields.values()):
        raise ValueError('action_raw_object_budget')
    if doc.xref_get_key(xref,'AP') != ('null','null'):
        raise ValueError('action_annotation_appearance_requires_adapter')
    link = candidates[0]
    result = {'page': page_number, 'xref': xref, 'rectangle': list(link['from']),
              'raw_fields': fields}
    _finite_rect(result['rectangle'], doc[page_number-1])
    if fields['Dest'] != ['null', 'null']:
        if fields['A'] != ['null', 'null']:
            raise ValueError('action_multiple_destination_actions_rejected')
    else:
        if fields['A'][0] != 'dict':
            raise ValueError('action_direct_dictionary_required')
        action = read_object(BytesIO(fields['A'][1].encode()), object())
        allowed = {'/S', '/D', '/Type'} if str(action.get('/S')) == '/GoTo' else {'/S', '/URI', '/Type'}
        if not isinstance(action, DictionaryObject) or set(action)-allowed:
            raise ValueError('action_unknown_or_chained_dictionary_keys_rejected')
    if link['kind'] == fitz.LINK_URI:
        if fields['Dest'] != ['null', 'null'] or fields['A/S'] != ['name', '/URI']:
            raise ValueError('action_single_uri_required')
        kind, uri = doc.xref_get_key(xref, 'A/URI')
        if kind != 'string' or not uri or uri != link.get('uri'):
            raise ValueError('action_raw_uri_disagrees')
        result.update(kind='URI', uri=uri)
    elif link['kind'] in (fitz.LINK_GOTO, fitz.LINK_NAMED):
        destination = source_destination(doc, xref,
            {doc.page_xref(i): i for i in range(len(doc))})
        if destination['left'] is None or destination['top'] is None:
            raise ValueError('action_destination_without_specific_anchor_requires_adapter')
        page = doc[destination['page_index']]
        point = fitz.Point(destination['left'], destination['top']) * page.transformation_matrix
        if not page.rect.contains(point):
            raise ValueError('action_actual_destination_outside_page')
        result.update(kind='GoTo', destination=destination,
                      destination_point_top_origin=list(point))
    else:
        raise ValueError('action_unsupported_requires_adapter')
    return result


def measured_glyph_binding(doc, page_number, expected):
    """冻结字形必须唯一对应actual trace；字体文件/轮廓由当前PDF重新审计。"""
    page = doc[page_number-1]
    native = glyphs(page)
    if not native or len(native) > MAX_GLYPHS or not expected or len(expected) > MAX_GLYPHS:
        raise ValueError('action_glyph_scope_or_budget')
    by_id = {}
    for g in native:
        by_id.setdefault(identity(g), []).append(g)
    actual = []
    seen = set()
    for row in expected:
        key = identity(row)
        matches = by_id.get(key, [])
        if len(matches) != 1 or key in seen or matches[0] != row:
            raise ValueError('action_actual_glyph_missing_ambiguous_or_mutated')
        seen.add(key); actual.append(matches[0])
    if any(g['type'] == 3 or g.get('opacity', 1) <= 0 for g in actual):
        raise ValueError('action_hidden_glyph_not_ink_proof')
    return actual


def actual_ink(doc, page_number, actual):
    page = doc[page_number-1]
    engine = EmbeddedGlyphInk(doc, page,
        required_fonts={g['font'] for g in actual},
        required_font_xrefs={r[0] for r in page.get_fonts(full=True) if r[-1] == 0})
    # 先核整批字体身份，避免底层字形选择覆盖action的明确拒绝原因。
    if any(len(engine.names.get(g['font'],set()))!=1 for g in actual):
        raise ValueError('action_host_actual_font_file_identity_ambiguous')
    records=engine.describe_many(actual)
    if len(records)!=len(actual):
        raise ValueError('action_actual_paint_batch_scope_incomplete')
    for glyph,record in zip(actual,records):
        candidates=engine.names.get(glyph['font'],set())
        if len(candidates)!=1:
            raise ValueError('action_host_actual_font_file_identity_ambiguous')
        if record.get('gid')!=glyph['gid']:
            raise ValueError('action_actual_paint_gid_mutated')
        if glyph['gid']<0 and (record.get('kind')!='shared_painted_ligature' or
                record.get('independent_painted_glyph') is not False or
                type(record.get('primary_gid')) is not int or record['primary_gid']<0 or
                record.get('nonpainting_outline') is True):
            raise ValueError('action_negative_gid_requires_actual_complete_painted_cluster')
        if record.get('nonpainting_outline') is True:
            digest,equivalent=engine._select(glyph)
            if len(equivalent)!=1 or engine.bounds[(digest,glyph['gid'])][0] is not None:
                raise ValueError('action_nonpainting_requires_actual_empty_font_outline')
            record.update(font_sha256=digest,font_file_identity_unique=True,
                          empty_actual_font_outline_verified=True)
        record['actual_host_font_resource_xrefs']=sorted(xref for xref,digest in engine.resource_digests.items()
                                                       if digest in candidates)
        if not record['actual_host_font_resource_xrefs']:
            raise ValueError('action_host_actual_font_resource_missing')
    return records


def _inside_ink(box, records, tolerance=.05):
    rect = fitz.Rect(box) + (-tolerance, -tolerance, tolerance, tolerance)
    for record in records:
        ink = record.get('ink_bounds')
        if ink is None:
            if record.get('nonpainting_outline') is not True or record.get('empty_actual_font_outline_verified') is not True:
                raise ValueError('action_current_ink_geometry_requires_adapter')
            continue
        if (not isinstance(ink,(tuple,list)) or len(ink)!=4 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in ink) or
            fitz.Rect(ink).is_empty or not fitz.Rect(ink).is_valid):
            raise ValueError('action_current_ink_geometry_requires_adapter')
        if not rect.contains(fitz.Rect(ink)):
            raise ValueError('action_host_ink_outside_click_rectangle')


def _check_bound_ink(doc, page_number, binding, rectangle=None, *, source_original=False, page_paint=None):
    current = measured_glyph_binding(doc, page_number, binding['glyphs'])
    if text_digest(''.join(chr(g['unicode']) for g in current)) != binding['text_sha256']:
        raise ValueError('action_bound_text_mutated')
    ink = actual_ink(doc, page_number, current)
    for record in ink:
        bounds=record.get('ink_bounds')
        if bounds is None:
            if record.get('nonpainting_outline') is not True or record.get('empty_actual_font_outline_verified') is not True:
                raise ValueError('action_current_ink_geometry_requires_adapter')
        elif (not isinstance(bounds,(tuple,list)) or len(bounds)!=4 or
              any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in bounds) or
              fitz.Rect(bounds).is_empty or not fitz.Rect(bounds).is_valid or
              not math.isfinite(record.get('actual_x_scale_pt_per_font_unit',float('nan'))) or
              not math.isfinite(record.get('actual_y_scale_pt_per_font_unit',float('nan')))):
            raise ValueError('action_current_ink_geometry_requires_adapter')
    if any(not record.get('nonpainting_outline') and not record.get('font_file_identity_unique') for record in ink):
        raise ValueError('action_embedded_font_identity_requires_adapter')
    if _digest(ink) != _digest(binding['ink']):
        raise ValueError('action_font_or_current_ink_evidence_changed')
    if rectangle is not None:
        # 源原框可触及原邻字；目标按完整页真实墨迹核定，不用未绘制baseline选宿主。
        if not source_original:
            paint_log=doc[page_number-1].get_bboxlog()
            if len(paint_log)>MAX_GLYPHS:
                raise ValueError('action_target_complete_paint_budget')
            for kind,bounds in paint_log:
                if kind in {'fill-text','ignore-text'}:continue
                # 实际paint bbox包含stroke扩展；零面积原path不得静默省略。
                if fitz.Rect(rectangle).intersects(fitz.Rect(bounds)):
                    raise ValueError('action_target_nontext_or_stroked_paint_requires_adapter')
            if page_paint is None:
                native = [g for g in glyphs(doc[page_number-1])
                          if g['type'] != 3 and g.get('opacity',1) > 0]
                page_paint = list(zip(native, actual_ink(doc, page_number, native)))
            host = [g for g,record in page_paint if record.get('ink_bounds') is not None and
                    fitz.Rect(rectangle).intersects(fitz.Rect(record['ink_bounds']))]
            expected = [g for g,record in zip(current,ink) if record.get('ink_bounds') is not None]
            if {identity(g) for g in host} != {identity(g) for g in expected}:
                raise ValueError('action_target_painted_neighbor_or_missing_host')
        _inside_ink(rectangle, ink)
    return current


def measured_anchor_region(doc, page_number, actual):
    """从当前完整原生印刷行推导锚点；输入bbox不参与选行或扩大范围。"""
    page=doc[page_number-1];native=glyphs(page)
    wanted={identity(g) for g in actual if not chr(g['unicode']).isspace()}
    if not wanted:
        raise ValueError('action_complete_native_anchor_line_required')
    candidates=[]
    for block in page.get_text('rawdict',flags=fitz.TEXTFLAGS_DICT)['blocks']:
        if block['type']!=0:continue
        for line in block['lines']:
            positions={tuple(round(x,3) for x in c['origin']) for span in line['spans'] for c in span['chars']}
            members=[g for g in native if tuple(round(x,3) for x in g['origin']) in positions and
                     g['type']!=3 and g.get('opacity',1)>0 and not chr(g['unicode']).isspace()]
            keys={identity(g) for g in members}
            if keys==wanted and len(keys)==len(members):candidates.append(members)
    if len(candidates)!=1:
        raise ValueError('action_anchor_not_one_complete_actual_printed_line')
    members=candidates[0]
    ink=actual_ink(doc,page_number,members)
    _inside_ink(list(page.rect),ink)
    boxes=[fitz.Rect(g['bbox']) for g in members]
    boxes += [fitz.Rect(v['ink_bounds']) for v in ink if v.get('ink_bounds') is not None]
    rectangle=boxes[0]
    for box in boxes[1:]:rectangle|=box
    return list(rectangle)


def _protected_pixels(row, docs, source_ref, target_ref, reviewer_id):
    """原生竖排或其它保护角色使用源像素与实际字形；不推测水平印刷行。"""
    region = row['protected_role']
    if region.get('reviewer_id') != reviewer_id or region.get('decision') != 'pass' or not region.get('source_role_reason'):
        raise ValueError('action_protected_role_independent_source_decision_required')
    expected = {'id': row['id'], 'source': source_ref, 'target': target_ref,
                'source_page': row['source']['page'], 'target_page': row['target']['page'],
                'source_bbox': region['source_bbox'], 'target_bbox': region['target_bbox']}
    if row['source']['kind'] != 'URI' or row['source']['uri'] != row['target'].get('uri'):
        raise ValueError('action_protected_uri_identity_changed')
    pairs = []
    for side in ('source', 'target'):
        crop = region[side+'_crop']
        result = audit_crop(expected, crop, side=side)
        if result['status'] != 'pass':
            raise ValueError('action_protected_pixels_not_actual_source_target')
        current = measured_glyph_binding(docs[side], row[side]['page'], row[side+'_host']['glyphs'])
        font_records=[]
        for font in docs[side][row[side]['page']-1].get_fonts(full=True):
            font_records.append({'basefont':font[3], 'resource':font[4],
                'object_sha256':hashlib.sha256(docs[side].xref_object(font[0],compressed=True).encode()).hexdigest()})
        if font_records != row[side+'_host'].get('font_resources'):
            raise ValueError('action_protected_font_resources_changed')
        rect = fitz.Rect(row[side]['rectangle'])
        page_native = glyphs(docs[side][row[side]['page']-1])
        host = [g for g in page_native if not chr(g['unicode']).isspace() and
                g['type'] != 3 and g.get('opacity', 1) > 0 and rect.contains(fitz.Point(g['origin']))]
        if {identity(g) for g in host} != {identity(g) for g in current}:
            raise ValueError('action_protected_host_scope_incomplete')
        pairs.append(current)
    # 本适配只证明原角色同坐标、同方向与同像素保护；变换须另行适配。
    if pairs[0] != pairs[1] or region['source_bbox'] != region['target_bbox']:
        raise ValueError('action_protected_role_geometry_or_glyph_changed')
    if region['source_crop']['pixel_sha256'] != region['target_crop']['pixel_sha256']:
        raise ValueError('action_protected_role_pixels_changed')


def _check_authored_host_role(review, row, source_ref, target_ref, standard_ref, reviewer_id):
    ref = review.get('host_role_review_ref')
    if ref is None:
        # 原生保护身份夹具/路线只允许完整同一literal宿主与目的，不冒作者Tex能力。
        semantics = row.get('semantic_destination', {})
        if semantics.get('semantic_kind') != 'protected_anchor_identity':
            raise ValueError('action_complete_source_authored_host_role_required')
        for side in ('source','target'):
            literal = ''.join(chr(g['unicode']) for g in row[side+'_host']['glyphs'])
            if normalized(literal) != normalized(semantics['complete_'+side+'_context']):
                raise ValueError('action_source_native_protected_host_purpose_changed')
        return
    role_review = read_bound_json(ref)
    if (role_review.get('source') != source_ref or role_review.get('target') != target_ref or
            role_review.get('standard') != standard_ref or role_review.get('reviewer_id') != reviewer_id or
            role_review.get('status') != 'pass_finite_source_authored_action_semantics_only'):
        raise ValueError('action_source_authored_host_role_identity_changed')
    authored = [r for r in role_review['bindings'] if r['source_action'] == row['source']]
    if len(authored) != 1 or authored[0]['target_action'] != row['target']:
        raise ValueError('action_source_authored_host_action_not_exact')
    authored = authored[0]
    for side in ('source','target'):
        declared=authored[side+'_intended_host']
        if (_digest(declared['glyphs']) != _digest(row[side+'_host']['glyphs']) or
                _digest(declared['ink']) != _digest(row[side+'_host']['ink'])):
            raise ValueError('action_source_authored_host_glyph_or_ink_changed')
    source_tex_ref=role_review['source_tex_ref']
    if file_ref(source_tex_ref['path'])!=source_tex_ref:
        raise ValueError('action_source_authored_original_changed')
    source_bytes=__import__('pathlib').Path(source_tex_ref['path']).read_bytes()
    call=authored['source_authored_call'];span=call.get('source_author_byte_range',call.get('byte_range'))
    literal=call.get('source_author_command_literal',call.get('literal'))
    if (not isinstance(span,list) or len(span)!=2 or any(type(n) is not int for n in span) or
            not 0 <= span[0] < span[1] <= len(source_bytes) or
            source_bytes[span[0]:span[1]] != literal.encode()):
        raise ValueError('action_source_authored_command_bytes_changed')
    if call.get('command') in ('cite','ref','eqref'):
        command=call['command'];key=call.get('key')
        if (not isinstance(key,str) or not literal.startswith('\\'+command) or
                not literal.endswith('}') or key not in [k.strip() for k in literal.rsplit('{',1)[-1][:-1].split(',')]):
            raise ValueError('action_source_authored_command_key_changed')
        if command=='cite':
            raw=row['source']['raw_fields']
            name=raw['Dest'] if raw['Dest'][0]!='null' else raw['A/D']
            if name != ['string','cite.'+key]:
                raise ValueError('action_source_authored_citation_raw_identity_changed')
    else:
        raise ValueError('action_source_authored_command_requires_adapter')
    # 作者实际编译标签逐字绑定完整宿主；多位标签不能只挑一位。
    for side in ('source','target'):
        aux_ref=role_review[side+'_aux_ref']
        if file_ref(aux_ref['path'])!=aux_ref:
            raise ValueError('action_source_authored_label_metadata_changed')
        aux=__import__('pathlib').Path(aux_ref['path']).read_text()
        prefix=('\\bibcite{' if call['command']=='cite' else '\\newlabel{')+call['key']+'}{'
        if call['command']!='cite':prefix+='{' 
        if len(aux.encode())>1048576 or aux.count(prefix)!=1:
            raise ValueError('action_source_authored_label_metadata_unique_required')
        label=aux.split(prefix,1)[1].split('}',1)[0]
        actual_literal=''.join(chr(g['unicode'])for g in row[side+'_host']['glyphs'])
        if (label!=call.get('displayed_label_from_actual_author_metadata') or
                normalized(label)!=normalized(actual_literal)):
            raise ValueError('action_complete_source_authored_label_host_changed')
    if call.get('source_unit_sha256') and text_digest(call['complete_source_unit']) != call['source_unit_sha256']:
        raise ValueError('action_source_authored_complete_unit_changed')
    evidence=authored.get('source_authored_destination_evidence',{})
    if evidence.get('source_bbl_ref'):
        if (evidence.get('source_key')!=call['key'] or
                ('\\bibitem{'+call['key']+'}') not in evidence['source_record_original_bytes']):
            raise ValueError('action_source_bibliographic_key_changed')
        bbl=evidence['source_bbl_ref']
        if file_ref(bbl['path'])!=bbl:raise ValueError('action_source_bibliographic_original_changed')
        raw=__import__('pathlib').Path(bbl['path']).read_bytes();span=evidence['source_record_byte_range']
        if raw[span[0]:span[1]]!=evidence['source_record_original_bytes'].encode():
            raise ValueError('action_source_bibliographic_record_bytes_changed')
    if call['command'] in ('ref','eqref'):
        mapping_ref=role_review['source_mapping_ref'];mapping=read_bound_json(mapping_ref)
        units=[u for u in mapping['units'] if u['unit_id']==evidence.get('label_host_source_unit_id')]
        label='\\label{'+call['key']+'}'
        if (len(units)!=1 or units[0]['source_text']!=evidence.get('label_host_complete_source_unit') or
                units[0]['source_sha256']!=evidence.get('label_host_source_unit_sha256') or
                label!=evidence.get('source_label_original') or label not in units[0]['source_text'] or
                units[0]['unit_id']!=authored.get('destination_semantic_unit_id')):
            raise ValueError('action_source_authored_label_destination_changed')
    if row.get('semantic_destination') and authored.get('destination_semantic_unit_id')!=row['semantic_destination'].get('unit_id'):
        raise ValueError('action_source_authored_destination_purpose_changed')


def audit_action_bindings(review_ref, *, source_ref, target_ref, standard_ref,
                          reviewer_id, producer_id, authorization_ref):
    """验证独立复核的完整动作映射；pass-only声明、漏项和不支持动作继续阻断。"""
    issues, pending, measured = [], [], []
    base = {'source': source_ref, 'target': target_ref, 'quality_pass': False,
            'human_acceptance': False, 'issues': issues, 'pending': pending,
            'accepted_annotations': {'source': [], 'target': []}, 'measurements': measured}
    base['protected_uri_annotations'] = {'source': [], 'target': []}
    base['native_uri_style_bindings'] = []
    try:
        authority = read_bound_json(authorization_ref)
        review = read_bound_json(review_ref)
        if (review.get('protocol') != PROTOCOL or review.get('source') != source_ref or
                review.get('target') != target_ref or review.get('standard') != standard_ref or
                review.get('reviewer_id') != reviewer_id or reviewer_id == producer_id or
                review.get('producer_id') != producer_id or review.get('method') != 'source_first' or
                review.get('authorization_ref') != authorization_ref or
                authority.get('reviewer_id') != reviewer_id or authority.get('source') != source_ref or
                authority.get('standard') != standard_ref or
                authority.get('scope') not in {'complete_document_quality', 'complete_document_quality_repair_rereview'} or
                authority.get('target', target_ref) != target_ref):
            raise ValueError('action_independent_review_identity_or_authority_changed')
        if any(file_ref(ref['path']) != ref for ref in (source_ref, target_ref, standard_ref)):
            raise ValueError('action_actual_file_identity_changed')
        rows = review['bindings']
        if not rows or len(rows) > MAX_ACTIONS or len({r['id'] for r in rows}) != len(rows):
            raise ValueError('action_binding_scope_or_duplicate')
        with fitz.open(source_ref['path']) as source, fitz.open(target_ref['path']) as target:
            docs = {'source': source, 'target': target}
            for side, doc in docs.items():
                pages = list(range(1, len(doc)+1))
                if not pages or len(pages) > MAX_PAGES or review.get(side+'_pages_checked') != pages:
                    raise ValueError('action_complete_document_page_scope_required')
                actual_ids = {(p, a['xref']) for p in pages for a in doc[p-1].get_links()}
                declared = [(r[side]['page'], r[side]['xref']) for r in rows]
                if len(set(declared)) != len(declared) or set(declared) != actual_ids:
                    raise ValueError('action_source_target_exact_once_annotation_scope_required')
            protected_rows=[r for r in rows if r.get('host_route')=='protected_pixels']
            exclusions={side:{} for side in docs};paint_cache={}
            for protected in protected_rows:
                _protected_pixels(protected,docs,source_ref,target_ref,reviewer_id)
                for side,doc in docs.items():
                    number=protected[side]['page'];box=fitz.Rect(protected['protected_role'][side+'_bbox'])
                    if any(r.get('host_route')!='protected_pixels' and r[side]['page']==number and
                           box.intersects(fitz.Rect(r[side]['rectangle'])) for r in rows):
                        raise ValueError('action_protected_unknown_role_not_disjoint')
                    current=[g for g in glyphs(doc[number-1]) if box.contains(fitz.Point(g['origin']))]
                    if not current or any(not box.contains(fitz.Rect(g['bbox'])) for g in current):
                        raise ValueError('action_protected_complete_role_region_not_bound')
                    exclusions[side].setdefault(number,set()).update(identity(g) for g in current)
            def page_paint(side,number):
                key=(side,number)
                if key not in paint_cache:
                    native=[g for g in glyphs(docs[side][number-1]) if g['type']!=3 and g.get('opacity',1)>0 and
                            identity(g) not in exclusions[side].get(number,set())]
                    paint_cache[key]=list(zip(native,actual_ink(docs[side],number,native)))
                return paint_cache[key]
            for row in rows:
                for side, doc in docs.items():
                    current = actual_action(doc, row[side]['page'], row[side]['xref'])
                    if current != row[side]:
                        raise ValueError('action_actual_raw_destination_or_rectangle_changed')
                if row['source']['kind'] != row['target']['kind']:
                    raise ValueError('action_kind_changed')
                if row['source']['kind'] == 'URI':
                    if row['source']['uri'] != row['target']['uri']:
                        raise ValueError('action_source_uri_changed')
                    if row.get('host_route') == 'protected_pixels':
                        _protected_pixels(row, docs, source_ref, target_ref, reviewer_id)
                        for side in docs:
                            base['protected_uri_annotations'][side].append([row[side]['page'], row[side]['xref']])
                    elif row.get('host_route') == 'native_uri_style':
                        # URI颜色/下划线/padding继续交原有实测模块，不在此豁免。
                        if not row.get('uri_style_region_id'):
                            raise ValueError('action_uri_native_style_registry_required')
                        for side, doc in docs.items():
                            _check_bound_ink(doc, row[side]['page'], row[side+'_host'], row[side]['rectangle'],
                                             source_original=side=='source',page_paint=page_paint(side,row[side]['page']))
                        base['native_uri_style_bindings'].append({'region_id':row['uri_style_region_id'],
                            'source':[row['source']['page'],row['source']['xref']],
                            'target':[row['target']['page'],row['target']['xref']]})
                    else:
                        raise ValueError('action_uri_host_route_requires_adapter')
                else:
                    _check_authored_host_role(review,row,source_ref,target_ref,standard_ref,reviewer_id)
                    semantics = row['semantic_destination']
                    if (semantics.get('decision') != 'accepted' or semantics.get('reviewer_id') != reviewer_id or
                            not semantics.get('semantic_id') or not semantics.get('role') or
                            not semantics.get('complete_source_context') or not semantics.get('complete_target_context') or
                            not semantics.get('rationale')):
                        raise ValueError('action_complete_independent_semantic_destination_required')
                    # 语义证据独立冻结，且必须绑定当前两个真实锚点；不是名字字符串等价声明。
                    proof = read_bound_json(semantics['independent_review_ref'])
                    if (proof.get('source') != source_ref or proof.get('target') != target_ref or
                            proof.get('standard') != standard_ref or proof.get('reviewer_id') != reviewer_id):
                        raise ValueError('action_semantic_proof_identity_changed')
                    decisions = [d for d in proof.get('decisions', []) if d.get('id') == row['id']]
                    expected_decision = {k: v for k, v in semantics.items() if k != 'independent_review_ref'}
                    if len(decisions) != 1 or decisions[0] != {'id': row['id'], **expected_decision}:
                        raise ValueError('action_semantic_proof_not_exact_frozen_binding')
                    semantic_kind = semantics.get('semantic_kind')
                    if semantic_kind == 'protected_anchor_identity':
                        if normalized(semantics['complete_source_context']) != normalized(semantics['complete_target_context']):
                            raise ValueError('action_protected_destination_semantic_identity_changed')
                    elif semantic_kind == 'reviewed_complete_unit':
                        complete = read_bound_json(semantics['complete_unit_review_ref'])
                        complete_reviewer=reviewer_id
                        if semantics.get('complete_unit_authority_ref'):
                            complete_authority=read_bound_json(semantics['complete_unit_authority_ref'])
                            if (complete_authority.get('source')!=source_ref or complete_authority.get('target')!=target_ref or
                                complete_authority.get('standard')!=standard_ref or
                                complete_authority.get('scope')!='complete_document_quality_repair_rereview' or
                                'content' not in complete_authority.get('component_scopes',[]) or
                                not complete_authority.get('reviewer_id') or complete_authority['reviewer_id']==producer_id):
                                raise ValueError('action_complete_unit_reviewer_authority_changed')
                            complete_reviewer=complete_authority['reviewer_id']
                        if (complete.get('source') != source_ref or complete.get('target') != target_ref or
                                complete.get('standard_sha256') != standard_ref['sha256'] or
                                complete.get('reviewer_id') != complete_reviewer):
                            raise ValueError('action_complete_unit_semantic_review_identity_changed')
                        units = [u for u in complete.get('decisions', []) if u.get('id') == semantics.get('unit_id')]
                        if (len(units) != 1 or units[0].get('decision') != 'accepted' or
                                units[0].get('source_text_sha256') != semantics['source_context_sha256'] or
                                units[0].get('target_text_sha256') != semantics['target_context_sha256'] or
                                set(units[0].get('aspects', {})) != {'completeness','conditions','negation','comparisons','entities','numbers','units','references'} or
                                any(a.get('status') not in {'accepted','not_applicable'} or not a.get('rationale') for a in units[0]['aspects'].values())):
                            raise ValueError('action_complete_unit_semantic_decision_not_bound')
                    else:
                        raise ValueError('action_semantic_destination_kind_requires_adapter')
                    for side, doc in docs.items():
                        _check_bound_ink(doc, row[side]['page'], row[side+'_host'], row[side]['rectangle'],
                                             source_original=side=='source',page_paint=page_paint(side,row[side]['page']))
                        dest = row[side]['destination']; anchor = row[side+'_anchor']
                        if anchor['page'] != dest['page_index']+1 or _digest(anchor) != semantics[side+'_anchor_sha256']:
                            raise ValueError('action_semantic_anchor_identity_changed')
                        actual = _check_bound_ink(doc, anchor['page'], anchor)
                        if anchor.get('span_selection')!='complete_native_printed_line':
                            raise ValueError('action_complete_native_anchor_line_required')
                        derived=measured_anchor_region(doc,anchor['page'],actual)
                        if (len(anchor['bbox'])!=4 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or
                            not math.isfinite(v) for v in anchor['bbox']) or
                            max(abs(a-b) for a,b in zip(derived,anchor['bbox']))>.001):
                            raise ValueError('action_anchor_bbox_not_derived_from_current_complete_glyphs')
                        context = semantics['complete_'+side+'_context']
                        text = ''.join(chr(g['unicode']) for g in actual)
                        if text_digest(context) != semantics[side+'_context_sha256'] or normalized(text) not in normalized(context):
                            raise ValueError('action_semantic_full_context_or_anchor_changed')
                        rect = _finite_rect(anchor['bbox'], doc[anchor['page']-1])
                        if any(not rect.contains(fitz.Point(g['origin'])) for g in actual):
                            raise ValueError('action_semantic_anchor_glyph_outside_region')
                        point = fitz.Point(row[side]['destination_point_top_origin'])
                        distance = max(rect.x0-point.x, point.x-rect.x1, rect.y0-point.y, point.y-rect.y1, 0)
                        if distance > 16:
                            raise ValueError('action_destination_does_not_reach_reviewed_anchor')
                source_neighbours=[];source_nontext=[]
                if row.get('host_route')!='protected_pixels':
                    rect=fitz.Rect(row['source']['rectangle']);intended={identity(g)for g in row['source_host']['glyphs']}
                    source_neighbours=[{'glyph':g,'ink':record}for g,record in page_paint('source',row['source']['page'])
                        if identity(g)not in intended and record.get('ink_bounds') is not None and
                        rect.intersects(fitz.Rect(record['ink_bounds']))]
                    source_nontext=[{'kind':kind,'bounds':list(bounds)}for kind,bounds in docs['source'][row['source']['page']-1].get_bboxlog()
                        if kind not in {'fill-text','ignore-text'} and rect.intersects(fitz.Rect(bounds))]
                measured.append({'id': row['id'], 'kind': row['source']['kind'],
                                 'source_original_paint_neighbours':source_neighbours,
                                 'source_original_nontext_paint_neighbours':source_nontext,
                                 'source': row['source'], 'target': row['target'],
                                 'host_route': row.get('host_route', 'embedded_ink'),
                                 'source_original_rectangle_clean_not_claimed':True,
                                 'target_complete_page_paint_checked':row.get('host_route')!='protected_pixels'})
            for side in docs:
                base['accepted_annotations'][side] = [[r[side]['page'], r[side]['xref']] for r in rows]
        if any(file_ref(ref['path']) != ref for ref in (source_ref, target_ref, standard_ref)):
            raise ValueError('action_file_changed_during_actual_audit')
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, IndexError, json.JSONDecodeError) as error:
        base['accepted_annotations'] = {'source': [], 'target': []}
        base['protected_uri_annotations'] = {'source': [], 'target': []}
        base['native_uri_style_bindings'] = []
        pending.append({'rule': 'independent_action_binding_missing_invalid_or_changed', 'reason': str(error)})
    base['status'] = 'fail' if issues else 'unverified' if pending else 'pass'
    return base
