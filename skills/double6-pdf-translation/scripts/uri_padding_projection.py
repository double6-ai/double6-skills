"""冻结源的统一URI留白投影；原位只改Rect，歧义组停止。"""
from collections import defaultdict
from pathlib import Path
import argparse, json, math, unicodedata
import fitz
from native_line_spacing import glyphs, compare_glyphs
from paragraph_link_rebind import checked_ref, reference, centre, union
from raw_link_actions import _parsed_action

POLICY = {'id': 'uniform-literal-uri-padding-v1', 'maximum_pages': 20,
          'maximum_annotations_per_page': 1000, 'maximum_padding_pt': 3.,
          'source_uniformity_pt': .5, 'repair_threshold_pt': .5,
          'saved_geometry_tolerance_pt': .001, 'case_overrides_allowed': False}

def normalized(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())

def printable(gs):
    return [(i, g) for i, g in enumerate(gs)
            if g['type'] == 0 and g.get('opacity', 1) > 0 and normalized(chr(g['unicode']))]

def members(gs, rect):
    return [i for i, g in printable(gs) if fitz.Rect(rect).contains(centre(g))]

def padding(gs, ids, rect):
    if not ids:
        raise ValueError('nontext_or_empty_host')
    b = union([gs[i] for i in ids])
    r = fitz.Rect(rect)
    return [b.x0-r.x0, b.y0-r.y0, r.x1-b.x1, r.y1-b.y1]

def proposed_rect(gs, ids, pad, page_rect):
    b = union([gs[i] for i in ids])
    rect = fitz.Rect(b.x0-pad[0], b.y0-pad[1], b.x1+pad[2], b.y1+pad[3])
    if not all(math.isfinite(x) for x in rect) or rect.is_empty or not fitz.Rect(page_rect).contains(rect):
        raise ValueError('new_rect_outside_page_or_invalid')
    # 固定留白若改变实际宿主，即停止本组；不截断留白来制造通过。
    if members(gs, rect) != ids:
        raise ValueError('new_rect_misses_member_or_contains_neighbour')
    return list(rect)

def uri_action(doc, link):
    xref = link['xref']
    if doc.xref_get_key(xref, 'AA') != ('null', 'null') or doc.xref_get_key(xref, 'Dest') != ('null', 'null'):
        raise ValueError('uri_additional_action_or_dest')
    kind, value = doc.xref_get_key(xref, 'A')
    if kind == 'xref':
        action_xref = int(value.split()[0])
        value = doc.xref_object(action_xref, compressed=False)
    elif kind != 'dict':
        raise ValueError('uri_action_missing')
    obj = _parsed_action(value)
    if '/Next' in obj or str(obj.get('/S')) != '/URI' or str(obj.get('/URI')) != link['uri']:
        raise ValueError('uri_action_chained_or_identity_changed')

def group_rows(doc, page, gs):
    links = page.get_links()
    if len(links) > POLICY['maximum_annotations_per_page']:
        raise ValueError('annotation_budget')
    groups = defaultdict(list)
    for link in links:
        if link['kind'] != fitz.LINK_URI:
            continue
        uri_action(doc, link)
        groups[link['uri']].append({'xref': link['xref'], 'rect': list(link['from']),
                                     'indices': members(gs, link['from'])})
    return groups

def annotation_fields(doc, page):
    return {l['xref']: {key: list(doc.xref_get_key(l['xref'], key))
                        for key in doc.xref_get_keys(l['xref']) if key != 'Rect'}
            for l in page.get_links()}

def decide_group(source_glyphs, target_glyphs, source_parts, target_parts, page_rect):
    def ordered(gs, parts):
        ids = [i for p in parts for i in p['indices']]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('nontext_or_shared_host')
        ids.sort(key=lambda i: (round(gs[i]['origin'][1], 2), gs[i]['origin'][0]))
        return ids
    si = ordered(source_glyphs, source_parts)
    ti = ordered(target_glyphs, target_parts)
    left = normalized(''.join(chr(source_glyphs[i]['unicode']) for i in si))
    right = normalized(''.join(chr(target_glyphs[i]['unicode']) for i in ti))
    if left != right:
        raise ValueError('literal_label_changed_or_ambiguous')
    pads = [padding(source_glyphs, p['indices'], p['rect']) for p in source_parts]
    if any(abs(v) > POLICY['maximum_padding_pt'] for p in pads for v in p):
        raise ValueError('source_padding_unbounded')
    if any(max(p[k] for p in pads)-min(p[k] for p in pads) > POLICY['source_uniformity_pt'] for k in range(4)):
        raise ValueError('source_padding_nonuniform')
    average = [sum(p[k] for p in pads)/len(pads) for k in range(4)]
    error = max(abs(a-b) for p in target_parts for a, b in
                zip(padding(target_glyphs, p['indices'], p['rect']), average))
    if error <= POLICY['repair_threshold_pt']:
        return {'status': 'unchanged_within_tolerance', 'maximum_before_padding_error_pt': error}
    rectangles = [proposed_rect(target_glyphs, p['indices'], average, page_rect) for p in target_parts]
    return {'status': 'proposed', 'source_average_padding_pt': average,
            'maximum_before_padding_error_pt': error, 'new_rectangles': rectangles}

def apply_plan(plan, output, *, dry_run=False):
    if set(plan) != {'schema_version', 'source', 'target', 'pages', 'policy'} or plan['schema_version'] != 'uri-padding-projection@1' or plan['policy'] != POLICY:
        raise ValueError('frozen_plan_required')
    src, target = checked_ref(plan['source']), checked_ref(plan['target'])
    pages = plan['pages']
    if not pages or pages != sorted(set(pages)) or len(pages) > POLICY['maximum_pages'] or any(type(n) is not int or n < 1 for n in pages):
        raise ValueError('page_budget')
    output = Path(output)
    output.mkdir(exist_ok=False)
    rows, changed, old_fields, old_arrays = [], {}, {}, {}
    with fitz.open(src) as source, fitz.open(target) as doc:
        if len(source) != len(doc) or pages[-1] > len(doc):
            raise ValueError('page_count_or_scope_changed')
        for number in pages:
            sp, page = source[number-1], doc[number-1]
            if sp.rotation or page.rotation:
                raise ValueError('rotated_page_not_supported')
            sg, tg = glyphs(sp), glyphs(page)
            a, b = group_rows(source, sp, sg), group_rows(doc, page, tg)
            if set(a) != set(b):
                raise ValueError('source_target_uri_set_changed')
            old_fields[number] = annotation_fields(doc, page)
            old_arrays[number] = doc.xref_get_key(page.xref, 'Annots')
            for uri in sorted(a):
                record = {'page': number, 'uri': uri, 'source_parts': a[uri], 'target_parts': b[uri]}
                try:
                    result = decide_group(sg, tg, a[uri], b[uri], page.rect)
                except ValueError as exc:
                    result = {'status': 'stopped_group', 'reason': str(exc)}
                record.update(result)
                rows.append(record)
                if result['status'] == 'proposed':
                    for part, rect in zip(b[uri], result['new_rectangles']):
                        changed[part['xref']] = {'page': number, 'rect': rect, 'indices': part['indices'],
                                                 'padding': result['source_average_padding_pt']}
                        if not dry_run:
                            pdfrect = fitz.Rect(rect) * ~page.transformation_matrix
                            doc.xref_set_key(part['xref'], 'Rect', '['+' '.join(format(x, '.9f') for x in pdfrect)+']')
            if not dry_run:
                compare_glyphs(glyphs(doc.reload_page(page)), tg, .001)
            del sg, tg
        candidate = output / 'candidate.pdf'
        if not dry_run:
            doc.save(candidate, garbage=0, deflate=True)
    saved_rows = []
    if not dry_run:
        with fitz.open(target) as before, fitz.open(candidate) as after:
            for number in pages:
                bp, ap = before[number-1], after[number-1]
                bg, ag = glyphs(bp), glyphs(ap)
                compare_glyphs(ag, bg, .001)
                if annotation_fields(after, ap) != old_fields[number] or after.xref_get_key(ap.xref, 'Annots') != old_arrays[number]:
                    raise ValueError('saved_annotation_fields_or_order_changed')
                for a, b in zip(bp.get_links(), ap.get_links()):
                    if a['xref'] != b['xref'] or {k:v for k,v in a.items() if k != 'from'} != {k:v for k,v in b.items() if k != 'from'}:
                        raise ValueError('saved_link_action_changed')
                    item = changed.get(b['xref'])
                    if item:
                        if max(abs(x-y) for x,y in zip(b['from'], item['rect'])) > .001 or members(ag, b['from']) != item['indices']:
                            raise ValueError('saved_host_or_geometry_changed')
                        err = max(abs(x-y) for x,y in zip(padding(ag, item['indices'], b['from']), item['padding']))
                        if err > .001:
                            raise ValueError('saved_padding_not_projected')
                        saved_rows.append({'page': number, 'xref': b['xref'], 'maximum_padding_error_pt': err})
                    elif list(a['from']) != list(b['from']):
                        raise ValueError('unselected_rectangle_changed')
                del bg, ag
    report = {'schema_version': 'uri-padding-projection-result@1', 'source': plan['source'],
              'before': plan['target'], 'candidate': reference(candidate) if not dry_run else None,
              'policy': POLICY, 'pages': pages, 'dry_run': dry_run, 'rows': rows,
              'counts': {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})},
              'changed_annotations': len(changed), 'saved_checks': saved_rows,
              'all_glyphs_preserved': not dry_run, 'all_annotation_fields_except_selected_rects_preserved': not dry_run,
              'case_overrides': 0, 'quality_pass': False, 'strict_delivery': False, 'human_acceptance': False}
    (output / 'REPORT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report

def main():
    p = argparse.ArgumentParser()
    p.add_argument('plan', type=Path)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if args.plan.stat().st_size > 16*1024**2:
        raise ValueError('plan_json_budget')
    result = apply_plan(json.loads(args.plan.read_text()), args.output_dir, dry_run=args.dry_run)
    print(json.dumps({k:result[k] for k in ['counts', 'changed_annotations', 'dry_run', 'candidate', 'quality_pass']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
