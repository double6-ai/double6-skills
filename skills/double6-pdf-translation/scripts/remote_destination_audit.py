"""以冻结文件、实际页对象和原生 XYZ 核对 GoTo → GoToR；伴随文件统一补齐。"""
from __future__ import annotations
import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import fitz
from pypdf.generic import read_object, IndirectObject, NullObject
from paragraph_link_rebind import checked_ref, reference
from raw_link_actions import _parsed_action

POLICY = {'id': 'frozen-remote-xyz-dependency-v1', 'maximum_pages': 20,
          'maximum_annotations': 1000, 'coordinate_tolerance_pt': .001,
          'zoom_zero_equals_null': True, 'case_overrides_allowed': False}

def safe_basename(name):
    if not isinstance(name, str) or name in ('', '.', '..') or Path(name).name != name or '\\' in name or '\x00' in name:
        raise ValueError('remote_dependency_simple_basename_required')
    return name

def xyz(destination, page_xrefs=None):
    if not isinstance(destination, list) or len(destination) != 5 or str(destination[1]) != '/XYZ':
        raise ValueError('remote_only_explicit_xyz_supported')
    first = destination[0]
    if page_xrefs is not None:
        if not isinstance(first, IndirectObject) or first.generation != 0 or first.idnum not in page_xrefs:
            raise ValueError('remote_source_actual_page_object_required')
        page = page_xrefs[first.idnum]
    else:
        if isinstance(first, (IndirectObject, bool)) or float(first) != int(first) or int(first) < 0:
            raise ValueError('remote_actual_zero_based_page_required')
        page = int(first)
    values = []
    for value in destination[2:]:
        if isinstance(value, NullObject): values.append(None)
        elif isinstance(value, (bool, IndirectObject)) or not math.isfinite(float(value)):
            raise ValueError('remote_finite_xyz_required')
        else: values.append(float(value))
    # Adobe PDF Reference table 8.2: 0 and null zoom both retain the current zoom.
    if values[2] == 0: values[2] = None
    return {'page_index': page, 'view': 'XYZ', 'left': values[0], 'top': values[1], 'zoom': values[2]}

def equivalent(a, b):
    if a['page_index'] != b['page_index'] or a['view'] != b['view']: return False
    for key in ('left', 'top', 'zoom'):
        if a[key] is None or b[key] is None:
            if a[key] is not b[key]: return False
        elif abs(a[key] - b[key]) > POLICY['coordinate_tolerance_pt']: return False
    return True

def named_xyz(doc, name, page_xrefs):
    """限定名称树预算，读取原生 D 数组；公共 nameddest 的编码不作替代。"""
    from pypdf.generic import ArrayObject, DictionaryObject
    count = [0]; matched = []
    def parse(raw):
        if len(raw.encode()) > 1024*1024: raise ValueError('remote_named_object_budget')
        return read_object(BytesIO((raw+' ').encode()), object())
    def deref(value, ancestors=()):
        if not isinstance(value, IndirectObject): return value
        if value.generation != 0 or value.idnum in ancestors or len(ancestors) >= 16: raise ValueError('remote_named_cycle_or_depth')
        count[0] += 1
        if count[0] > 256: raise ValueError('remote_named_object_budget')
        return deref(parse(doc.xref_object(value.idnum, compressed=True)), ancestors+(value.idnum,))
    def visit(node, ancestors=()):
        if len(ancestors) >= 16: raise ValueError('remote_named_tree_depth')
        key = node.idnum if isinstance(node,IndirectObject) else id(node)
        if key in ancestors: raise ValueError('remote_named_tree_cycle')
        node = deref(node)
        if not isinstance(node,DictionaryObject): raise ValueError('remote_named_dictionary_required')
        entries = deref(node.get('/Names',ArrayObject())); kids = deref(node.get('/Kids',ArrayObject()))
        if not isinstance(entries,ArrayObject) or len(entries)%2 or len(entries)>4096 or not isinstance(kids,ArrayObject) or len(kids)>256: raise ValueError('remote_named_tree_shape_or_budget')
        for i in range(0,len(entries),2):
            if str(entries[i]).lstrip('/') == name.lstrip('/'):
                value=deref(entries[i+1])
                if isinstance(value,DictionaryObject): value=deref(value.get('/D'))
                matched.append(xyz(value,page_xrefs))
        for child in kids: visit(child,ancestors+(key,))
    for field in ('Names/Dests','Dests'):
        kind,raw=doc.xref_get_key(doc.pdf_catalog(),field)
        if kind=='null': continue
        value=parse(raw)
        if field=='Names/Dests': visit(value)
        else:
            values=deref(value)
            if not isinstance(values,DictionaryObject): raise ValueError('remote_legacy_dests_dictionary_required')
            for key,value in values.items():
                if str(key).lstrip('/')==name.lstrip('/'):
                    value=deref(value)
                    if isinstance(value,DictionaryObject): value=deref(value.get('/D'))
                    matched.append(xyz(value,page_xrefs))
    if not matched or any(r!=matched[0] for r in matched): raise ValueError('remote_named_missing_or_ambiguous')
    return matched[0]

def source_destination(doc, xref, page_xrefs):
    if doc.xref_get_key(xref, 'AA') != ('null', 'null'): raise ValueError('remote_source_additional_action')
    kind, raw = doc.xref_get_key(xref, 'Dest')
    if kind == 'null':
        if doc.xref_get_key(xref, 'A/S') != ('name', '/GoTo') or doc.xref_get_key(xref, 'A/Next') != ('null', 'null'):
            raise ValueError('remote_source_single_goto_required')
        kind, raw = doc.xref_get_key(xref, 'A/D')
    if kind in ('string','name'): return named_xyz(doc,raw,page_xrefs)
    if kind != 'array' or len(raw.encode()) > 65536: raise ValueError('remote_source_explicit_destination_required')
    return xyz(read_object(BytesIO(raw.encode()), object()), page_xrefs)

def audit(plan, *, package=False):
    if set(plan) != {'schema_version', 'source', 'target', 'bindings', 'dependencies', 'policy'} or plan['schema_version'] != 'remote-destination-audit@1' or plan['policy'] != POLICY:
        raise ValueError('remote_frozen_policy_required')
    source_path = checked_ref(plan['source']); target_path = checked_ref(plan['target'])
    rows = plan['bindings']
    if not rows or len(rows) > POLICY['maximum_annotations']: raise ValueError('remote_annotation_budget')
    allowed={'id','source_page','source_xref','target_page','target_xref','before_target_xref','bridge_action_and_NM_exact','previous_actual_ref'}
    if any(set(r)-allowed for r in rows) or not 0<len(plan['dependencies'])<=8: raise ValueError('remote_unknown_binding_option_or_dependency_budget')
    dependencies = {}
    for name, ref in plan['dependencies'].items():
        name = safe_basename(name); original = checked_ref(ref); destination = target_path.parent / name
        if any(p.is_symlink() for p in (destination,*destination.parents)): raise ValueError('remote_dependency_symlink_rejected')
        if package and not destination.exists():
            with original.open('rb') as src, destination.open('xb') as dst: shutil.copyfileobj(src, dst, 1024*1024)
        actual = reference(destination) if destination.is_file() else None
        if actual is None or actual['sha256'] != ref['sha256']: raise ValueError('remote_dependency_missing_or_identity_changed')
        dependencies[name] = {'declared': ref, 'packaged': actual}
    issues = []; measured = []
    with fitz.open(source_path) as source, fitz.open(target_path) as target:
        if max(len(source), len(target)) > POLICY['maximum_pages']: raise ValueError('remote_page_budget')
        page_xrefs = {source.page_xref(n): n for n in range(len(source))}
        source_ids = {(n+1, a['xref']) for n in range(len(source)) for a in source[n].get_links() if a['kind'] in (fitz.LINK_GOTO,fitz.LINK_NAMED)}
        target_ids = {(n+1, a['xref']) for n in range(len(target)) for a in target[n].get_links() if a['kind'] == fitz.LINK_GOTOR}
        if len({(r['source_page'],r['source_xref']) for r in rows}) != len(rows) or len({(r['target_page'],r['target_xref']) for r in rows}) != len(rows): raise ValueError('remote_duplicate_binding')
        if source_ids != {(r['source_page'], r['source_xref']) for r in rows} or target_ids != {(r['target_page'], r['target_xref']) for r in rows}:
            raise ValueError('remote_complete_source_target_scope_required')
        for row in rows:
            expected = source_destination(source, row['source_xref'], page_xrefs)
            kind, raw = target.xref_get_key(row['target_xref'], 'A')
            if kind != 'dict' or target.xref_get_key(row['target_xref'], 'AA') != ('null','null'): raise ValueError('remote_direct_single_action_required')
            action = _parsed_action(raw)
            if str(action.get('/S')) != '/GoToR' or '/Next' in action: raise ValueError('remote_single_gotor_required')
            filespec = action.get('/F'); name = safe_basename(str(filespec.get('/F')) if isinstance(filespec, dict) else str(filespec))
            if isinstance(filespec, dict) and '/UF' in filespec and str(filespec['/UF']) != name: raise ValueError('remote_unicode_filename_disagrees')
            if name not in dependencies or dependencies[name]['declared']['sha256'] != plan['source']['sha256']:
                raise ValueError('remote_destination_document_identity_disagrees')
            actual = xyz(action.get('/D'))
            with fitz.open(dependencies[name]['packaged']['path']) as dependency:
                if not 0 <= actual['page_index'] < len(dependency): raise ValueError('remote_destination_page_out_of_range')
                page = dependency[actual['page_index']]
                # PDF 原生坐标与 PyMuPDF 页坐标采用实际 transformation_matrix 转换。
                inside = True
                if actual['left'] is not None and actual['top'] is not None:
                    point = fitz.Point(actual['left'], actual['top']) * page.transformation_matrix
                    inside = page.rect.contains(point)
            match = equivalent(expected, actual)
            if not match or not inside: issues.append({'id':row.get('id'), 'rule':'remote_xyz_mismatch_or_outside_page'})
            measured.append({**row, 'file':name, 'source_destination':expected, 'actual_destination':actual,
                             'destination_identity_verified':True, 'xyz_semantically_equivalent':match,
                             'destination_point_inside_page':inside})
    if reference(target_path) != plan['target']: raise ValueError('remote_pdf_changed_during_audit')
    return {'schema_version':'remote-destination-audit-result@1', 'source':plan['source'], 'target':plan['target'],
            'policy':POLICY, 'dependencies':dependencies, 'rows':measured, 'issues':issues,
            'status':'fail' if issues else 'pass', 'annotation_count':len(rows),
            'pdf_bytes_changed':False, 'reader_ui_navigation_verified':False,
            'click_host_style_acceptance':False, 'quality_pass':False}

def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('plan',type=Path); p.add_argument('--output',type=Path,required=True); p.add_argument('--package',action='store_true'); a=p.parse_args()
    if a.output.exists(): raise ValueError('remote_output_already_exists')
    if a.plan.stat().st_size>16*1024*1024: raise ValueError('remote_plan_size_limit')
    result = audit(json.loads(a.plan.read_text()), package=a.package)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status':result['status'],'annotation_count':result['annotation_count'],'output':str(a.output)}))

if __name__ == '__main__': main()
