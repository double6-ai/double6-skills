# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：流式身份校验与有界内存维护；详见MODIFICATIONS.md。
"""编译独立审定的电子 PDF 完整语义组；只准备源，不调用模型或写 PDF。"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import sys
import copy
import threading

from pdf_source_cache import bound_json, file_ref

_COMPILED_SOURCE = None
_COMPILED_SOURCE_LOCK = threading.RLock()

PROTOCOL = 'pdf_reviewed_whole_group_projection_v1'
WHITESPACE_PROTOCOL = 'pdf_source_native_whitespace_restoration_v1'
SCIENTIFIC_REGION_PROTOCOL = 'pdf_complete_scientific_component_regions_v1'
GROUP_KIND = 'input_specific_source_only_semantic_group_plan'
ROLE_TYPES = {'arxiv_identifier', 'author', 'figure_math_label', 'figure_panel_label', 'page_number'}
GROUP_ROLES = {'title', 'abstract', 'body', 'caption', 'body_with_display_math',
              'funding_acknowledgment', 'footnote', 'theorem', 'explanation', 'bridge',
              'lemma', 'proof', 'acknowledgment', 'references_heading', 'bibliography_identity'}
CONTROL = ('Translate the complete source-reviewed English semantic group into Simplified Chinese. '
           'Source-only independent review assisted grouping; this is not blind source discovery. '
           'Keep every PTC boundary in its exact order and every PTS scientific identity exactly once '
           'inside its original component. Keep immutable components verbatim. '
           'Translate all ordinary prose, captions, headings and continuations. '
           'Output only the component sequence, without commentary. '
           'Original scientific glyphs are restored by the backend, never redraw or rewrite them.')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    if isinstance(value, str):
        return hashlib.sha256(value.encode()).hexdigest()
    # 保持原canonical字节顺序；流式哈希避免完整JSON和UTF-8副本同时驻留。
    result = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False)
    for part in encoder.iterencode(value):
        result.update(part.encode())
    return result.hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _english(value):
    _require(isinstance(value, str) and not re.search(r'[\u3400-\u9fff]', value),
             'Chinese expectation or target exposure in source packet')
    _require(not re.search(r'\[\[(?:/?PTC|PTS|PTI):', value), 'reserved source boundary collision')
    return value


def _compact_map(text):
    result, positions = [], []
    for index, char in enumerate(text):
        for normal in unicodedata.normalize('NFKC', char):
            if not normal.isspace():
                result.append(normal)
                positions.append(index)
    return ''.join(result), positions


def restore_source_whitespace(source, native_lines, *, scientific_ranges=()):
    """由唯一实际源范围恢复空白；所有原非空白字符与科学对象保持原字节。"""
    _english(source)
    compact, source_positions = _compact_map(source)
    _require(compact, 'empty non-whitespace source range')
    native = '\n'.join(line['text'] for line in native_lines)
    native_compact, native_positions = _compact_map(native)
    hits, at = [], 0
    while (found := native_compact.find(compact, at)) >= 0:
        hits.append(found)
        at = found + 1
    if not hits:
        covered = {i for lo, hi in scientific_ranges for i in range(lo, hi)}
        _require(scientific_ranges and all(i in covered for i, char in enumerate(source) if not char.isspace()),
                 'source native range missing; prose cannot use glyph-only identity')
        return source, list(range(len(source) + 1)), {
            'protocol': WHITESPACE_PROTOCOL, 'kind': 'bound_source_glyph_only',
            'non_whitespace_sha256': digest(''.join(c for c in source if not c.isspace())),
            'whitespace_changes': [], 'native_source_line_ids': []}
    _require(len(hits) == 1, 'source native whitespace range ambiguous or duplicated')
    offset = hits[0]
    selected = native_positions[offset:offset + len(compact)]
    boundaries = {}
    for i in range(1, len(compact)):
        gap = native[selected[i-1] + 1:selected[i]]
        if gap and any(char.isspace() for char in gap):
            _require(all(char.isspace() for char in gap), 'native whitespace mapping crosses a source character')
            _require(source_positions[i-1] != source_positions[i], 'native word boundary splits an original source glyph')
            boundaries[source_positions[i]] = {
                'native_character_offset': selected[i], 'native_gap': gap,
                'kind': 'source_line_break' if '\n' in gap else 'source_word_space',
                'after_source_hyphen': native[selected[i-1]] == '-'}
    restored, original_map, changes, length = [], [0] * (len(source) + 1), [], 0
    visible = [i for i, char in enumerate(source) if not char.isspace()]
    for previous, index in zip(visible, visible[1:]):
        old_gap = source[previous+1:index]
        desired_gap = ' ' if index in boundaries else ''
        if old_gap != desired_gap:
            changes.append({'original_character_offset': index, 'original_gap': old_gap, 'restored_gap': desired_gap,
                            'operation': 'insert_source_space' if not old_gap else 'remove_unmatched_il_space' if not desired_gap else 'canonicalize_source_whitespace',
                            **boundaries.get(index, {})})
    for index, char in enumerate(source):
        if char.isspace():
            original_map[index] = length
            continue
        if index in boundaries and restored:
            restored.append(' ')
            length += 1
        original_map[index] = length
        restored.append(char)
        length += len(char)
    original_map[len(source)] = length
    result = ''.join(restored)
    _require(''.join(c for c in source if not c.isspace()) == ''.join(c for c in result if not c.isspace()),
             'restoration changed original non-whitespace source bytes')
    span_start, span_end = selected[0], selected[-1] + 1
    source_line_ids, cursor = [], 0
    for line in native_lines:
        end = cursor + len(line['text'])
        if cursor < span_end and end > span_start:
            _require(not line['role'].startswith('display_math'), 'prose source range crosses a fixed display role')
            source_line_ids.append(line['id'])
        cursor = end + 1
    return result, original_map, {'protocol': WHITESPACE_PROTOCOL, 'kind': 'unique_actual_native_source_range',
                                'native_compact_range': [offset, offset + len(compact)],
                                'native_source_line_ids': source_line_ids,
                                'native_selected_text': native[span_start:span_end],
                                'non_whitespace_sha256': digest(''.join(c for c in source if not c.isspace())),
                                'restored_source_sha256': digest(result),
                                'original_to_restored_character_map': original_map,
                                'native_whitespace_boundaries': [{'original_character_offset': k, **v} for k, v in boundaries.items()],
                                'whitespace_changes': changes}


def _restore_bound_glyph_whitespace(source, native_lines, glyph_ranges, scientific_ranges):
    """从实际字体资源和基线唯一绑定恢复空白；只有既有科学角色容许logical Unicode差异。"""
    source_compact,source_positions=_compact_map(source)
    native='\n'.join(line['text'] for line in native_lines)
    native_glyphs=[];cursor=0
    for line in native_lines:
        for glyph in line['native_glyphs']:
            lo,hi=glyph['native_character_range']
            native_glyphs.append({**glyph,'offset_range':[cursor+lo,cursor+hi],'line_id':line['id']})
        cursor+=len(line['text'])+1
    covered=set();bindings=[];original_to_native={}
    for item in glyph_ranges:
        lo,hi=item['range'];glyph=item['glyph']
        if not ''.join(glyph['unicode'].split()):continue
        font=glyph['font'];box=glyph['box']
        matches=[g for g in native_glyphs
            if any(f['font_id']==font['font_id'] and f['xref_id']==font['xref_id']
                   and f['name']==font['name'] for f in g['font_resources'])
            and abs(g['origin'][0]-box['x'])<=.02
            and abs(g['origin'][1]-(g['source_page_height']-box['y']))<=.02]
        _require(len(matches)==1,'source glyph native font/baseline binding missing or ambiguous')
        actual=matches[0];a,b=actual['offset_range'];logical=native[a:b]
        scientific=any(s<=lo<hi<=e for s,e in scientific_ranges)
        _require(scientific or _compact_map(glyph['unicode'])[0]==_compact_map(logical)[0],
                 'ordinary source glyph native Unicode differs')
        _require(not covered.intersection(range(lo,hi)),'source glyph range duplicate')
        covered.update(range(lo,hi))
        normal,positions=_compact_map(source[lo:hi])
        native_normal,native_positions=_compact_map(logical)
        if scientific:
            for p in positions:original_to_native[lo+p]=a
        else:
            _require(normal==native_normal,'ordinary source range native Unicode differs')
            for p,np in zip(positions,native_positions):original_to_native[lo+p]=a+np
        bindings.append({'source_unicode_range':[lo,hi],'source_encoded_character_id':glyph['gid'],
            'source_font_resource':{'font_id':font['font_id'],'xref_id':font['xref_id'],'name':font['name']},
            'native_gid':actual['native_gid'],'native_font':actual['font'],
            'native_origin':actual['origin'],'native_character_range':[a,b],
            'native_line_id':actual['line_id'],'native_logical_text':logical,
            'scientific_role':scientific,'logical_unicode_differs':_compact_map(glyph['unicode'])[0]!=_compact_map(logical)[0]})
    _require(all(i in covered for i,c in enumerate(source) if not c.isspace()),'source glyph native binding incomplete')
    _require(all(bindings[i]['native_character_range'][0]<=bindings[i+1]['native_character_range'][0]
                 for i in range(len(bindings)-1)),'source native glyph order changed')
    boundaries={}
    for left,right in zip(bindings,bindings[1:]):
        a=left['native_character_range'][1];b=right['native_character_range'][0]
        _require(a<=b,'source native glyph binding overlaps')
        gap=native[a:b]
        _require(not gap or gap.isspace(),'source native glyph binding skips a source character')
        if gap:boundaries[right['source_unicode_range'][0]]=gap
    restored=[];remap=[0]*(len(source)+1);length=0
    for i,char in enumerate(source):
        if char.isspace():remap[i]=length;continue
        if i in boundaries and restored:restored.append(' ');length+=1
        remap[i]=length;restored.append(char);length+=len(char)
    remap[len(source)]=length;result=''.join(restored)
    _require(_compact_map(result)[0]==source_compact,'source glyph restoration changed original bytes')
    return result,remap,{'protocol':WHITESPACE_PROTOCOL,'kind':'unique_actual_native_font_baseline_glyph_bindings',
        'native_source_line_ids':list(dict.fromkeys(b['native_line_id'] for b in bindings)),
        'glyph_bindings':bindings,'scientific_logical_unicode_differences':[b for b in bindings if b['logical_unicode_differs']],
        'non_whitespace_sha256':digest(''.join(c for c in source if not c.isspace())),
        'restored_source_sha256':digest(result),'original_to_restored_character_map':remap}


def _chars(composition):
    active = [(key, value) for key, value in composition.items() if value is not None]
    _require(len(active) == 1, 'unknown or ambiguous source composition')
    key, value = active[0]
    _require(key in {'pdf_line', 'pdf_formula', 'pdf_same_style_characters', 'pdf_character'},
             'unsupported source composition kind')
    return key, [value] if key == 'pdf_character' else value['pdf_character']


def _source_fonts(page):
    """绑定原页与Form字体命名空间；Form同名资源不覆盖原页字体。"""
    result={font['font_id']:font for font in page['pdf_font']}
    _require(len(result)==len(page['pdf_font']),'ambiguous source font')
    seen=set()
    for obj in page.get('pdf_xobject',[]):
        xobj=obj['xobj_id']
        _require(xobj not in seen,'ambiguous original Form namespace')
        seen.add(xobj)
        for font in obj.get('pdf_font',[]):
            key=str(xobj)+'/'+font['font_id']
            _require(key not in result,'ambiguous original Form font')
            result[key]=font
    return result


def _glyph(page, char, fonts):
    style = char['pdf_style']
    key=str(char.get('xobj_id'))+'/'+style['font_id']
    if key not in fonts:key=style['font_id']
    _require(key in fonts, 'unknown source font')
    # Full font metadata includes the original glyph bbox/GID and xref identity.
    result={'page': page, 'unicode': char['char_unicode'], 'gid': char['pdf_character_id'],
            'font': fonts[key], 'style': style, 'box': char['box'],
            'visual_bbox': char.get('visual_bbox'), 'vertical': char.get('vertical'),
            'advance': char.get('advance'), 'xobj_id': char.get('xobj_id'),
            'render_order': char.get('render_order'), 'sub_render_order': char.get('sub_render_order')}
    for key in ('source_text_matrix','source_local_bbox'):
        if char.get(key) is not None:result[key]=char[key]
    return result


def _canonical_source_metadata(value):
    """与XMLConverter一致：只省略两项不存在的可选原源矩阵字段。"""
    if isinstance(value, dict):
        return {k: _canonical_source_metadata(v) for k, v in value.items()
                if not (k in {'source_text_matrix', 'source_local_bbox'} and v is None)}
    if isinstance(value, list):
        return [_canonical_source_metadata(v) for v in value]
    return value


def _paragraph(page, para, fonts, pdf_sha):
    # Use the actual vendored source reconstruction primitive, including glyph gaps.
    vendor = str(Path(__file__).resolve().parents[1] / 'vendor' / 'babeldoc')
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    from babeldoc.format.pdf.document_il.il_version_1 import Box, PdfCharacter
    from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
    compact, positions = _compact_map(para['unicode'])
    cursor, formulas, glyphs, backend, glyph_ranges = 0, [], [], [], []
    for composition in para['pdf_paragraph_composition']:
        kind, chars = _chars(composition)
        text = ''.join(char['char_unicode'] for char in chars)
        normal, _ = _compact_map(text)
        _require(compact[cursor:cursor + len(normal)] == normal,
                 'source Unicode and original glyph composition disagree')
        start = positions[cursor] if normal else (positions[cursor - 1] + 1 if cursor else 0)
        end = positions[cursor + len(normal) - 1] + 1 if normal else start
        objects = [_glyph(page, char, fonts) for char in chars]
        glyphs.extend(objects)
        gcursor=cursor
        for obj in objects:
            gn,_=_compact_map(obj['unicode'])
            if gn:
                gs=positions[gcursor];ge=positions[gcursor+len(gn)-1]+len(para['unicode'][positions[gcursor+len(gn)-1]])
                glyph_ranges.append({'range':[gs,ge],'glyph':obj})
            gcursor+=len(gn)
        if kind == 'pdf_formula':
            formulas.append({'range': [start, end], 'source_unicode': text,
                             'box': composition[kind]['box'], 'glyphs': objects,
                             'source_object_sha256': digest({'pdf': pdf_sha, 'page': page,
                                                            'formula': _canonical_source_metadata(composition[kind]), 'fonts': fonts})})
            backend.append('{v' + str(len(formulas)) + '}')
        else:
            backend.extend(PdfCharacter(box=Box(**char['box']), char_unicode=char['char_unicode'],
                                        pdf_character_id=char['pdf_character_id']) for char in chars)
        cursor += len(normal)
    _require(cursor == len(compact), 'source paragraph glyph omission')
    identity = {'pdf_sha256': pdf_sha, 'page': page, 'unicode': para['unicode'],
                'box': para['box'], 'style': para['pdf_style'], 'glyphs': glyphs,
                'formulas': formulas, 'vertical': para.get('vertical'),
                'first_line_indent': para.get('first_line_indent'), 'xobj_id': para.get('xobj_id')}
    return {'identity': identity, 'sha256': digest(identity), 'formulas': formulas,
            'unicode': para['unicode'], 'box': para['box'], 'coverage': Counter(), 'glyph_ranges':glyph_ranges,
            'source_composition_masked_literal': (para['unicode'] if len(para['pdf_paragraph_composition']) == 1 and not formulas
                                                 else get_char_unicode_string(backend))}


def _review_formula(obj, number):
    return {'marker': '{v' + str(number) + '}', 'source_unicode_raw': obj['source_unicode'],
            'box': obj['box'], 'glyphs': [{'char_unicode': glyph['unicode'],
                                        'font_id': glyph['style']['font_id'],
                                        'font_size': glyph['style']['font_size'], 'gid': glyph['gid'],
                                        'box': glyph['box'], 'render_order': glyph['render_order']}
                                       for glyph in obj['glyphs']]}


def _same_box(left, right):
    return left == right


def _native_roles(pdf_path, evidence, groups, il=None):
    import fitz
    from source_content_inventory import read_native_glyph_lines
    expected = evidence['all_94_independent_native_roles']
    actual = []
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, 1):
            bindings=[b for b in evidence.get('unmapped_scientific_bindings',[]) if b['page']==page_index]
            for binding in bindings:
                source_page=il['page'][page_index-1];char=source_page['pdf_character'][binding['top_level_index']]
                font=_source_fonts(source_page).get(str(char.get('xobj_id'))+'/'+char['pdf_style']['font_id'],
                        _source_fonts(source_page).get(char['pdf_style']['font_id']))
                _require(binding['source_role']=='scientific_object' and char['pdf_character_id']==binding['original_encoded_id']
                    and font['xref_id']==binding['font_xref'] and char['box']==binding['original_IL_box']
                    and abs(char['box']['x']-binding['origin'][0])<=.02
                    and abs(char['box']['y']-(page.rect.height-binding['origin'][1]))<=.02,
                    'unmapped binding is not exact original typed scientific source')
            glyph_lines=read_native_glyph_lines(page,unmapped_scientific_bindings=bindings)
            for block_index, block in enumerate(page.get_text('dict')['blocks']):
                if 'lines' not in block:
                    continue
                for line_index, line in enumerate(block['lines']):
                    spans = line['spans']
                    actual.append({'id': f'digital-replacement-p{page_index}-b{block_index}-l{line_index}',
                                   'page': page_index, 'text': ''.join(span['text'] for span in spans),
                                   'bbox': list(line['bbox']), 'native_glyphs':glyph_lines[(block_index,line_index)],
                                   'fonts': [{'text': span['text'], 'font': span['font'],
                                              'size': span['size'], 'origin': list(span['origin'])} for span in spans]})
    by_id = {row['id']: row for row in actual}
    _require(len(by_id) == len(actual) == len(expected), 'native source role omission or duplicate')
    seen, roles = set(), []
    membership = {group['group_id']: {line['id'] for line in group['source_native_line_ranges']} for group in groups}
    for row in expected:
        key = row['source_line_id']
        _require(key in by_id and key not in seen, 'unknown or duplicate native role')
        seen.add(key)
        live = by_id[key]
        _require(live['page'] == row['page'] and live['text'] == row['source_text']
                 and digest(live['text']) == row['source_text_sha256']
                 and live['bbox'] == row['bbox'] and live['fonts'] == row['native_fonts'],
                 'actual PDF native source role/font/geometry changed')
        members = row['semantic_groups']
        _require(len(members) <= 1 and all(key in membership.get(member, set()) for member in members),
                 'native role semantic membership unknown or ambiguous')
        if not members:
            _require(row['independent_source_role'] in ROLE_TYPES, 'unsupported protected native role')
        else:
            _require([g for g, ids in membership.items() if key in ids] == members,
                     'native source group role omitted or duplicated')
        roles.append({'source_object_sha256': digest(live), 'source': live,
                      'source_role': row['independent_source_role'], 'group_ids': members})
    _require(set().union(*membership.values()) <= seen, 'group native role absent from actual PDF')
    return roles


def compile_groups(reviewed_plan_ref, source_il_ref, context_ref, *, evidence_ref=None,
                   policy_ref=None, approval_ref=None, whitespace_policy_ref=None, whitespace_approval_ref=None,
                   scientific_region_policy_ref=None, scientific_region_approval_ref=None):
    """Strong source ledger. Source-only review of this new ledger is still required before warming."""
    _require(all(Path(ref['path']).stat().st_size <= 32 * 1024**2 for ref in (reviewed_plan_ref, source_il_ref, context_ref)),
             'bounded source JSON size exceeded')
    plan, il, context = map(bound_json, (reviewed_plan_ref, source_il_ref, context_ref))
    _require(1 <= len(il['page']) <= 10 and il['total_pages'] == len(il['page']), 'bounded complete PDF page scope required')
    _require(plan.get('kind') == GROUP_KIND and plan.get('schema_version') == 1, 'unsupported reviewed source plan')
    _require(plan['source_il_ref'] == source_il_ref and plan['input_ref'] == context['input_ref'], 'stale source PDF or IL binding')
    input_ref = plan['input_ref']
    _require(file_ref(input_ref['path']) == input_ref, 'source PDF SHA changed')
    evidence_ref = evidence_ref or file_ref(Path(reviewed_plan_ref['path']).with_name('SOURCE_EVIDENCE.json'))
    evidence = bound_json(evidence_ref)
    if scientific_region_policy_ref is not None or scientific_region_approval_ref is not None:
        _require(scientific_region_policy_ref is not None and scientific_region_approval_ref is not None,
                 'scientific region policy and approval both required')
        region_policy = bound_json(scientific_region_policy_ref)
        region_approval = bound_json(scientific_region_approval_ref)
        _require(region_policy.get('protocol') == SCIENTIFIC_REGION_PROTOCOL
                 and region_approval.get('proposal_ref') == scientific_region_policy_ref
                 and region_approval.get('status') == 'implementation_authorized_after_before_snapshot_audit',
                 'scientific region policy not approved')
    if whitespace_policy_ref is not None or whitespace_approval_ref is not None:
        _require(whitespace_policy_ref is not None and whitespace_approval_ref is not None,
                 'source whitespace policy and approval both required')
        whitespace_policy, whitespace_approval = bound_json(whitespace_policy_ref), bound_json(whitespace_approval_ref)
        _require(whitespace_policy.get('protocol') == WHITESPACE_PROTOCOL
                 and whitespace_approval.get('policy_ref') == whitespace_policy_ref
                 and whitespace_approval.get('status') == 'coordinator_approved_bounded_source_whitespace_implementation',
                 'source whitespace policy not approved')
        refs = whitespace_policy['source_refs']
        _require(refs['input'] == input_ref and refs['source_il'] == source_il_ref
                 and refs['scope'] == plan['scope_ref'] and refs['native_evidence'] == evidence_ref
                 and refs['reviewed_plan'] == reviewed_plan_ref, 'source whitespace policy source identity changed')
    _require(all(ref in evidence['source_refs'] for ref in (context_ref, source_il_ref, input_ref, plan['scope_ref'])),
             'independent source evidence binding incomplete')
    for ref in (plan['scope_ref'], plan['source_collection_ref']):
        _require(file_ref(ref['path']) == ref, 'source scope/collection changed')
    collection_rows = [json.loads(line) for line in Path(plan['source_collection_ref']['path']).read_text().splitlines()]
    collection_by_key = {}
    for row in collection_rows:
        _require(row.get('origin') == 'source_only_nontranslation' and row.get('context_ref') == context_ref,
                 'source collection contains response/target or foreign context')
        request = row['request']
        _require(digest(request['source_literal']) == request['source_sha256']
                 and digest(request['system_control']) == request['system_sha256'], 'source request control SHA changed')
        existing = collection_by_key.setdefault(request['key'], request)
        _require(existing == request, 'ambiguous original source request identity')
    if policy_ref is not None or approval_ref is not None:
        _require(policy_ref is not None and approval_ref is not None, 'policy and approval both required')
        policy, approval = bound_json(policy_ref), bound_json(approval_ref)
        _require(policy.get('protocol') == PROTOCOL and policy['reviewed_group_plan_ref'] == reviewed_plan_ref
                 and policy['actual_collection_ref'] == context_ref
                 and approval.get('proposal') == policy_ref
                 and approval.get('status') == 'coordinator_approved_bounded_implementation', 'projection policy not approved')
    groups = plan['groups']
    _require(groups and len(groups) <= 64 and len({g['group_id'] for g in groups}) == len(groups), 'duplicate/empty/unbounded semantic group')
    roles = _native_roles(input_ref['path'], evidence, groups,il)
    paragraphs, diagnostics, top_glyphs = {}, {}, {}
    for number, page in enumerate(il['page'], 1):
        _require(page['page_number'] == number - 1, 'source page order changed')
        fonts = _source_fonts(page)
        for para in page['pdf_paragraph']:
            bound = _paragraph(number, para, fonts, input_ref['sha256'])
            _require(bound['sha256'] not in paragraphs, 'ambiguous source paragraph identity')
            paragraphs[bound['sha256']] = bound
            diagnostics[(number, para['debug_id'])] = bound
        for index, char in enumerate(page['pdf_character']):
            obj = _glyph(number, char, fonts)
            sha = digest({'pdf': input_ref['sha256'], 'glyph': obj})
            _require(sha not in top_glyphs, 'ambiguous display glyph source identity')
            top_glyphs[sha] = {'source_object_sha256': sha, 'glyph': obj, 'index': index, 'used': 0}
    result = []
    for original in groups:
        gid = original['group_id']
        _require(re.fullmatch(r'[A-Za-z0-9_-]+', gid) and original['source_role'] in GROUP_ROLES, 'unsupported source group role/id')
        _english(original['source_full_semantic_text'])
        _require(_compact_map(original['source_full_semantic_text'])[0] ==
                 _compact_map(''.join(line['text'] for line in original['source_native_line_ranges']))[0],
                 'complete source English differs from actual native source lines')
        live_roles = {item['source']['id']: item['source'] for item in roles}
        for line in original['source_native_line_ranges']:
            _require(line['id'] in live_roles and line['text'] == live_roles[line['id']]['text']
                     and line['bbox'] == live_roles[line['id']]['bbox'], 'group source line changed')
        _require(original['same_paragraph_continuation']['cross_page'] is False
                 and original['same_paragraph_continuation']['source_pages'] == [original['source_page']],
                 'unsupported or forged cross-page continuation')
        components, scientific = [], []
        identities=[]
        for fragment in original['il_source_fragments']:
            # Diagnostic IDs never select the source: Unicode/range/box must match uniquely.
            start, end = fragment['il_unicode_character_range']
            matches = [p for p in paragraphs.values() if p['identity']['page'] == fragment['page']
                       and p['box'] == fragment['il_box'] and 0 <= start < end <= len(p['unicode'])
                       and p['unicode'][start:end] == fragment['il_unicode_selected']]
            _require(len(matches) == 1, 'unknown or ambiguous source fragment range/geometry')
            para = matches[0]
            expected_formulas = [_review_formula(obj, index) for index, obj in enumerate(para['formulas'], 1)]
            _require(fragment['inline_scientific_objects'] == expected_formulas,
                     'reviewed scientific glyph/font/range evidence changed')
            _require(fragment['page'] == original['source_page'], 'new paragraph source page changed')
            _require(diagnostics.get((fragment['page'], fragment['il_paragraph_id'])) is para, 'diagnostic IL ID contradicts actual source')
            for index in range(start, end):
                para['coverage'][index] += 1
            cid = gid + '-c' + str(len(components) + 1)
            selected = []
            natural_formula_shas=set(fragment.get('natural_formula_object_shas',[]))
            _require(natural_formula_shas<={f['source_object_sha256'] for f in para['formulas']},
                     'natural formula role lacks exact original source object')
            for formula in para['formulas']:
                lo, hi = formula['range']
                if hi <= start or lo >= end:
                    continue
                _require(start <= lo < hi <= end, 'scientific object crosses fixed fragment boundary')
                if formula['source_object_sha256'] in natural_formula_shas:continue
                sid = gid + 's' + str(len(scientific) + len(selected) + 1)
                selected.append({**formula, 'scientific_id': sid})
            selected_identity=[]
            for declaration in fragment.get('source_identity_ranges',[]):
                lo,hi=declaration['range']
                _require(declaration['kind'] in {'email','name','date','classification_code'}
                         and start<=lo<hi<=end,'unknown or outside source identity range')
                _require(not any(max(lo,o['range'][0])<min(hi,o['range'][1]) for o in selected),
                         'source identity overlaps existing mathematical object')
                chars=[g['glyph'] for g in para['glyph_ranges'] if lo<=g['range'][0]<g['range'][1]<=hi]
                _require(chars and _compact_map(''.join(g['unicode'] for g in chars))[0]==_compact_map(para['unicode'][lo:hi])[0],
                         'source identity glyph range incomplete')
                iid=gid+'i'+str(len(identities)+len(selected_identity)+1)
                obj={'identity_id':iid,'identity_kind':declaration['kind'],'range':[lo,hi],
                     'source_unicode':para['unicode'][lo:hi],'glyphs':chars,
                     'source_object_sha256':digest({'pdf':input_ref,'paragraph':para['sha256'],'range':[lo,hi],
                                                    'kind':declaration['kind'],'glyphs':chars})}
                selected_identity.append(obj)
            scientific_ranges=[(obj['range'][0]-start,obj['range'][1]-start) for obj in selected]
            try:
                text, remap, restoration = restore_source_whitespace(
                    para['unicode'][start:end], original['source_native_line_ranges'],scientific_ranges=scientific_ranges)
            except ValueError as exc:
                if str(exc) not in {'source native range missing; prose cannot use glyph-only identity',
                                    'source native whitespace range ambiguous or duplicated'}:raise
                native_lines=[{**line,'native_glyphs':live_roles[line['id']]['native_glyphs']}
                              for line in original['source_native_line_ranges']]
                glyph_ranges=[{'range':[g['range'][0]-start,g['range'][1]-start],'glyph':g['glyph']}
                              for g in para['glyph_ranges'] if start<=g['range'][0]<g['range'][1]<=end]
                text,remap,restoration=_restore_bound_glyph_whitespace(
                    para['unicode'][start:end],native_lines,glyph_ranges,scientific_ranges)
            restored_source = text
            for obj in sorted(selected+selected_identity,key=lambda o:o['range'][0],reverse=True):
                lo, hi = obj['range']
                mapped_lo = remap[lo-start]
                # The end excludes whitespace inserted before the next original character.
                last_original = max(i for i in range(lo-start, hi-start) if not para['unicode'][start:end][i].isspace())
                mapped_hi = remap[last_original] + len(para['unicode'][start:end][last_original])
                _require(_compact_map(restored_source[mapped_lo:mapped_hi])[0] ==
                         _compact_map(para['unicode'][lo:hi])[0], 'scientific source range remapping changed identity')
                obj['input_restored_range'] = [mapped_lo, mapped_hi]
                marker='[[PTS:'+obj['scientific_id']+']]' if 'scientific_id' in obj else '[[PTI:'+obj['identity_id']+']]'
                text = text[:mapped_lo] + marker + text[mapped_hi:]
            _english(para['unicode'][start:end])
            component = {'component_id': cid, 'kind': 'source_fragment', 'source_page': fragment['page'],
                         'source_paragraph_sha256': para['sha256'], 'source_range': [start, end],
                         'source_box': para['box'], 'source_literal': para['unicode'][start:end],
                         'restored_source_literal': restored_source, 'source_whitespace_restoration': restoration,
                         'input_text': text, 'scientific_ids': [o['scientific_id'] for o in selected],
                         'identity_ids':[o['identity_id'] for o in selected_identity],
                         'natural_formula_object_shas':sorted(natural_formula_shas),
                         'immutable': original['source_role'] == 'bibliography_identity' or para['unicode'][start:end] == '(cid:3)',
                         'backend_paragraph_source_literal': para['source_composition_masked_literal'],
                         'backend_placeholder_map': [{'placeholder': '{v' + str(i) + '}',
                                                      'scientific_id': next((item['scientific_id'] for item in selected
                                                                             if item['source_object_sha256'] == obj['source_object_sha256']), None),
                                                      'source_object_sha256': obj['source_object_sha256'],
                                                      'source_range': obj['range'],
                                                      'source_role':'natural_formula' if obj['source_object_sha256'] in natural_formula_shas else 'scientific_object',
                                                      'in_component': obj in para['formulas'] and start <= obj['range'][0] < obj['range'][1] <= end}
                                                     for i, obj in enumerate(para['formulas'], 1)],
                         'backend_source_aliases': []}
            if not selected_identity:component.pop('identity_ids')
            if not natural_formula_shas:component.pop('natural_formula_object_shas')
            for item in component['backend_placeholder_map']:
                if item['source_role']=='scientific_object':item.pop('source_role')
            # Original source requests are diagnostic aliases only, never entries or native events.
            for request in fragment.get('original_requests', []):
                _english(request['source_literal'])
                _require(digest(request['source_literal']) == request['source_sha256'], 'original source alias SHA changed')
                _require(request['source_literal'] == para['source_composition_masked_literal'],
                         'original source alias is not the exact backend paragraph reconstruction')
                _require(request['key'] in collection_by_key, 'unknown original source request alias')
                actual_request = collection_by_key[request['key']]
                _require(actual_request['source_literal'] == request['source_literal']
                         and actual_request['source_sha256'] == request['source_sha256']
                         and actual_request['retry'] is False, 'source alias is partial/retry or changed')
                component['backend_source_aliases'].append({k: actual_request[k] for k in
                                                           ('key', 'source_literal', 'source_sha256', 'system_control', 'system_sha256')})
            components.append(component)
            scientific.extend(selected)
            identities.extend(selected_identity)
        display = original['interleaved_display_math']
        if display['il_top_level_source_glyphs']:
            recovered = []
            for glyph in display['il_top_level_source_glyphs']:
                matches = [obj for obj in top_glyphs.values() if obj['glyph']['page'] == glyph['page']
                           and obj['glyph']['unicode'] == glyph['char_unicode'] and obj['glyph']['gid'] == glyph['gid']
                           and obj['glyph']['style']['font_id'] == glyph['font_id']
                           and obj['glyph']['style']['font_size'] == glyph['font_size']
                           and obj['glyph']['box'] == glyph['box'] and obj['glyph']['render_order'] == glyph['render_order']]
                _require(len(matches) == 1, 'display glyph missing or ambiguous')
                obj = matches[0]
                _require(obj['index'] == glyph['top_level_index'] and obj['glyph']['font']['name'] == glyph['font_name'], 'display font/index changed')
                obj['used'] += 1
                recovered.append({'source_object_sha256': obj['source_object_sha256'], 'glyph': obj['glyph']})
            sha = digest(recovered)
            sid = gid + 's' + str(len(scientific) + 1)
            # Source logical reading is declared reviewed transcription, never original TeX.
            reading = _english(display['logical_reading_if_display'])
            scientific.append({'scientific_id': sid, 'source_object_sha256': sha, 'glyphs': recovered,
                               'reviewed_logical_reading': reading, 'original_tex': False})
            comp = {'component_id': gid + '-display', 'kind': 'fixed_display', 'source_page': original['source_page'],
                    'input_text': '[[PTS:' + sid + ']]', 'scientific_ids': [sid], 'immutable': True,
                    'source_object_sha256': sha, 'backend_source_aliases': []}
            # Source geometry fixes the position between text fragments. No target coordinates.
            display_y = max(obj['glyph']['box']['y2'] for obj in recovered)
            position = next((i for i, item in enumerate(components) if item['source_box']['y2'] < display_y), len(components))
            components.insert(position, comp)
        result.append({'group_id': gid, 'source_page': original['source_page'], 'source_role': original['source_role'],
                       'source_full_semantic_text': original['source_full_semantic_text'], 'components': components,
                       'scientific_objects': scientific, 'identity_objects':identities,'source_review_assisted': True})
        if not identities:result[-1].pop('identity_objects')
    metadata = plan['metadata_and_protected_roles']
    protected = []
    selectors = []
    for name, role in (('author', 'author'), ('stamp', 'stamp_identity_class_date')):
        if name in metadata:
            entries=metadata[name] if isinstance(metadata[name],list) else [metadata[name]]
            _require(entries,'empty protected source role selector')
            for entry in entries:
                selectors.append((entry.get('page',1),entry['il_id'],role))
    selectors += [(i + 1, key, 'page_number') for i, key in enumerate(metadata.get('page_numbers', {}).get('il_ids', []))]
    labels = metadata.get('figure_scientific_labels', {})
    for key, ids in labels.items():
        if key.endswith('_il_ids'):
            page = int(re.search(r'page(\d+)', key).group(1))
            selectors += [(page, item, 'figure_scientific_identity') for item in ids]
    for page, key, role in selectors:
        _require((page, key) in diagnostics, 'unknown protected source object')
        para = diagnostics[(page, key)]
        for index in range(len(para['unicode'])):
            para['coverage'][index] += 1
        protected.append({'source_role': role, 'source_object_sha256': para['sha256'], 'source': para['identity']})
    for para in paragraphs.values():
        _require(all(para['coverage'][i] == 1 for i, char in enumerate(para['unicode']) if not char.isspace()),
                 'source paragraph range omitted or duplicated')
    _require(all(obj['used'] == 1 for obj in top_glyphs.values()), 'display source glyph omitted or duplicated')
    _require(len(top_glyphs) == len(evidence['all_107_top_level_scientific_glyphs']), 'display glyph evidence count differs')
    ledger = {'protocol': PROTOCOL, 'status': 'prepared_source_ledger_independent_review_required',
              'reviewed_plan_ref': reviewed_plan_ref, 'source_il_ref': source_il_ref, 'context_ref': context_ref,
              'input_ref': input_ref, 'evidence_ref': evidence_ref, 'policy_ref': policy_ref, 'approval_ref': approval_ref,
              'source_collection_ref': plan['source_collection_ref'],
              'source_whitespace_policy_ref': whitespace_policy_ref, 'source_whitespace_approval_ref': whitespace_approval_ref,
              'scientific_region_policy_ref': scientific_region_policy_ref,
              'scientific_region_approval_ref': scientific_region_approval_ref,
              'implementation_refs': [file_ref(Path(__file__)),
                                      file_ref(Path(__file__).with_name('source_content_inventory.py')),
                                      file_ref(Path(__file__).with_name('pdf_source_cache.py')),
                                      file_ref(Path(__file__).resolve().parents[1] / 'vendor/babeldoc/babeldoc/format/pdf/document_il/utils/layout_helper.py'),
                                      file_ref(Path(__file__).resolve().parents[1] / 'vendor/babeldoc/babeldoc/format/pdf/document_il/midend/il_translator.py'),
                                      file_ref(Path(__file__).resolve().parents[1] / 'vendor/babeldoc/babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py')],
              'groups': result, 'protected_source_objects': protected, 'native_roles': roles,
              'source_coverage': {'native_roles': len(roles), 'paragraphs': len(paragraphs), 'display_glyphs': len(top_glyphs),
                                  'groups': len(result), 'exact_unique_source_coverage': True},
              'actual_provider_calls': 0, 'actual_target_pdf': None, 'warming_allowed': False,
              'semantic_accepted': False, 'glyph_writeback_accepted': False, 'human_accepted': False}
    # 外存来源资格；这些字段不进入模型 packet，不能用 caller kind 授予重排。
    origin = {'reviewed_plan_ref': reviewed_plan_ref, 'source_il_ref': source_il_ref, 'context_ref': context_ref,
              'evidence_ref': evidence_ref, 'policy_ref': policy_ref, 'approval_ref': approval_ref,
              'whitespace_policy_ref': whitespace_policy_ref, 'whitespace_approval_ref': whitespace_approval_ref,
              'scientific_region_policy_ref': scientific_region_policy_ref,
              'scientific_region_approval_ref': scientific_region_approval_ref,
              'implementation_refs': ledger['implementation_refs']}
    for group in result:
        group['source_origin_refs'] = origin
        group['scientific_regions'] = []
        for component in group['components']:
            objects = [obj for obj in group['scientific_objects'] if obj['scientific_id'] in component['scientific_ids']]
            region = {'region_id': component['component_id'] + '-science',
                      'component_id': component['component_id'],
                      'mode': 'permutation_exact_once' if component['kind'] == 'source_fragment' and not component['immutable'] else 'fixed_exact',
                      'original_scientific_id_order': component['scientific_ids'],
                      'source_component_sha256': digest(component), 'complete_source_atoms_sha256': digest(objects)}
            region['source_region_sha256'] = digest(region)
            group['scientific_regions'].append(region)
    ledger['source_ledger_sha256'] = digest(ledger)
    return ledger


def build_group_input(group):
    """Recursive source whitelist: no QA/Chinese expected text or old responses in native input."""
    components = group['components']
    _require(components and len({c['component_id'] for c in components}) == len(components), 'duplicate source component')
    text = '\n'.join('[[PTC:' + c['component_id'] + ']]' + c['input_text'] + '[[/PTC:' + c['component_id'] + ']]' for c in components)
    packet = {'protocol': PROTOCOL, 'group_id': group['group_id'], 'source_page': group['source_page'],
              'source_review_assisted': True, 'complete_source_english': _english(group['source_full_semantic_text']),
              'source_math_transcription': 'source-reviewed logical reading; not original TeX',
              'scientific_source_readings': [{'scientific_id': obj['scientific_id'],
                                            'source_unicode': _english(obj.get('source_unicode', obj.get('reviewed_logical_reading', '')))}
                                           for obj in group['scientific_objects']],
              'identity_source_readings':[{'identity_id':o['identity_id'],'kind':o['identity_kind'],
                                           'source_unicode':_english(o['source_unicode'])}
                                          for o in group.get('identity_objects',[])],
              'immutable_components': [c['component_id'] for c in components if c['immutable']],
              'component_sequence': text}
    literal = canonical(packet)
    if not group.get('identity_objects'):
        packet.pop('identity_source_readings',None)
        literal=canonical(packet)
    _require(not re.search(r'[\u3400-\u9fff]', literal), 'Chinese exposure in native source packet')
    control=CONTROL
    if group.get('identity_objects'):
        control+=' Keep every PTI identity marker exactly once in its component; original identity glyphs and values are restored verbatim.'
    return {'source_literal': literal, 'source_sha256': digest(literal), 'system_control': control,
            'system_sha256': digest(control), 'protocol': PROTOCOL, 'group_id': group['group_id']}


def _compiled_origin_group(origin, group_id):
    """单份源解析复用；每次重哈全部实际输入，返回独立组副本。"""
    global _COMPILED_SOURCE
    arguments = {key: value for key, value in origin.items() if key != 'implementation_refs'}
    key = digest(origin)
    with _COMPILED_SOURCE_LOCK:
        if _COMPILED_SOURCE is None or _COMPILED_SOURCE[0] != key:
            actual = compile_groups(**arguments)
            plan = bound_json(origin['reviewed_plan_ref'])
            dependencies = [ref for ref in arguments.values() if ref is not None]
            dependencies += origin['implementation_refs'] + actual['implementation_refs'] + [actual['input_ref'],
                plan['scope_ref'], plan['source_collection_ref']]
            # 编译后的再核验也阻止并发变更混入解析结果。
            for ref in dependencies:
                _require(file_ref(ref['path']) == ref, 'compiled source dependency changed')
            _COMPILED_SOURCE = (key, copy.deepcopy(dependencies), actual)
        _, dependencies, actual = _COMPILED_SOURCE
        for ref in dependencies:
            _require(file_ref(ref['path']) == ref, 'compiled source dependency changed')
        matches = [candidate for candidate in actual['groups'] if candidate['group_id'] == group_id]
        _require(len(matches) == 1, 'actual source compiler group missing or ambiguous')
        result = copy.deepcopy(matches[0])
        _rebind_compiler_identity(result, origin)
        return result


def _rebind_compiler_identity(actual_group, historical_origin):
    """同一源重编译后仅沿用历史来源描述；两套源码身份均参与逐次校验。

    实际内容、组件及科学区域继续由当前编译器生成并完整比较。
    安装目录变化不应迫使相同源文重新调用模型。
    """
    current = actual_group['source_origin_refs']
    _require({k:v for k,v in current.items() if k != 'implementation_refs'} ==
             {k:v for k,v in historical_origin.items() if k != 'implementation_refs'},
             'replayed source compiler inputs changed')
    before = historical_origin['implementation_refs']
    after = current['implementation_refs']
    names = lambda refs: [Path(ref['path']).name for ref in refs]
    _require(len(before) == len(after) and len(set(names(before))) == len(before)
             and sorted(names(before)) == sorted(names(after)),
             'actual source compiler membership changed during replay')
    current['implementation_refs'] = copy.deepcopy(before)


def validate_group_response(group, text):
    """Structural validation only; semantic/actual PDF review remains a separate gate."""
    _require(isinstance(text, str) and text.strip(), 'empty whole-group response')
    origin = group.get('source_origin_refs')
    _require(isinstance(origin, dict), 'actual source compiler origin required')
    _require(set(origin) == {'reviewed_plan_ref', 'source_il_ref', 'context_ref', 'evidence_ref',
                            'policy_ref', 'approval_ref', 'whitespace_policy_ref', 'whitespace_approval_ref',
                            'scientific_region_policy_ref', 'scientific_region_approval_ref', 'implementation_refs'},
             'actual source compiler origin fields required')
    for ref in origin.get('implementation_refs', []):
        _require(file_ref(ref['path']) == ref, 'source compiler implementation changed')
    # 解析复用仍逐次重哈真实源输入，并逐组完整比较，不信任caller重哈的ledger。
    actual = _compiled_origin_group(origin, group.get('group_id'))
    _require(actual == group, 'caller group differs from actual source compiler')
    position, projections = 0, []
    for component, region in zip(group['components'], group['scientific_regions']):
        cid = component['component_id']
        opening, closing = '[[PTC:' + cid + ']]', '[[/PTC:' + cid + ']]'
        while position < len(text) and text[position].isspace():
            position += 1
        _require(text.startswith(opening, position), 'fixed component boundary missing/reordered/unknown')
        start = position + len(opening)
        end = text.find(closing, start)
        _require(end >= 0, 'fixed closing component boundary missing')
        value = text[start:end]
        _require(not re.search(r'\[\[/?PTC:', value), 'duplicate or crossed fixed component boundary')
        ids = re.findall(r'\[\[PTS:([^\]]+)\]\]', value)
        original_ids = region['original_scientific_id_order']
        _require(Counter(ids) == Counter(original_ids) and len(ids) == len(set(ids)),
                 'scientific substitution/missing/duplicate/cross-boundary')
        identity_ids=re.findall(r'\[\[PTI:([^\]]+)\]\]',value)
        _require(Counter(identity_ids)==Counter(component.get('identity_ids',[]))
                 and len(identity_ids)==len(set(identity_ids)), 'identity substitution/missing/duplicate/cross-boundary')
        _require(not re.search(r'\[\[/?PTI:',re.sub(r'\[\[PTI:[^\]]+\]\]','',value)), 'malformed identity marker')
        _require(not re.search(r'\[\[/?PTS:', re.sub(r'\[\[PTS:[^\]]+\]\]', '', value)),
                 'malformed scientific marker')
        if region['mode'] == 'fixed_exact':
            _require(ids == original_ids, 'fixed scientific object order changed')
        _require(value.strip(), 'empty source component projection')
        if component['immutable']:
            _require(value == component['input_text'], 'immutable source scientific or identity bytes changed')
        _require('SOURCE_ONLY_COLLECTION_COMPLETE' not in value, 'collector sentinel in target')
        permutation = {'region_id': region['region_id'], 'source_region_sha256': region['source_region_sha256'],
                       'mode': region['mode'], 'original_scientific_id_order': original_ids,
                       'actual_scientific_id_order': ids,
                       'permutation_original_indices': [original_ids.index(sid) for sid in ids],
                       'reordered': ids != original_ids}
        projections.append({'component_id': cid, 'target_text': value, 'target_sha256': digest(value),
                            'scientific_region_evidence': permutation,
                            'origin': 'derived_whole_group_projection', 'actual_provider_calls': 0,
                            'parent_response_sha256': digest(text), 'source_page': component['source_page']})
        position = end + len(closing)
    _require(not text[position:].strip(), 'unknown whole-group response suffix/boundary')
    return {'group_id': group['group_id'], 'whole_group_text': text, 'response_sha256': digest(text),
            'scientific_region_evidence': [p['scientific_region_evidence'] for p in projections],
            'projections': projections, 'structural_valid': True, 'semantic_accepted': False,
            'human_accepted': False}
