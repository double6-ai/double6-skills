"""有限源样式/宿主元数据消费；范围来自完整源与有效目标的独立审校。"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import threading
from io import BytesIO
from pathlib import Path

from pdf_group_editorial_revision import checked_ref, load, source_semantics
from pdf_source_cache import digest

STYLE_PROTOCOL = 'reviewed_source_target_style_ranges_v1'
HOST_PROTOCOL = 'source_authored_effective_target_hosts_v1'
CONTRACT_PROTOCOL = 'reviewed_pdf_group_source_style_contract_v1'
NATURAL_FONT_SCALE = {'title': 1.0, 'funding_acknowledgment': 1.0, 'footnote': 1.0}
CJK_BODY_SCALE = 0.95
LINE_HEIGHT_RATIO = 1.30
FONT_FILES = {'regular': 'SourceHanSerifCN-Regular.ttf', 'bold': 'SourceHanSerifCN-Bold.ttf',
              'italic_cjk': 'LXGWWenKaiGB-Regular.1.520.ttf', 'italic_latin': 'NotoSerif-Italic.ttf'}
_FONT_ALIASES = {}
_FONT_ALIAS_OWNERS = {}
_RUNTIMES = {}
_RUNTIME_LOCK = threading.RLock()
_EVIDENCE_DOCUMENTS = {}
STYLE_UNIT_FIELDS = {'group_id', 'component_id', 'source_original_character_range',
    'source_paragraph_sha256', 'source_page', 'source_role', 'source_native_font_resource_refs',
    'source_line_evidence_refs', 'alignment', 'first_line_indent_pt', 'hanging_indent_pt',
    'source_modal_font_size', 'source_first_baseline', 'source_style_runs',
    'target_component_sha256', 'target_natural_style_ranges'}
HOST_ACTION_FIELDS = {'action_id', 'source_page', 'source_annotation_xref', 'source_raw_action_ref',
    'source_destination_ref', 'source_full_group_ref', 'source_complete_context_unicode_range',
    'source_printed_full_label', 'source_intent_evidence_refs', 'target_group_id',
    'target_component_id', 'target_component_sha256', 'projection_selector'}


def finite_number(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError('finite source typography number required')
    return value


def exact_range(value, length):
    if (not isinstance(value, list) or len(value) != 2 or any(type(x) is not int for x in value)
            or not 0 <= value[0] < value[1] <= length):
        raise ValueError('complete Unicode range outside bound component')
    return tuple(value)


def checked_evidence(ref):
    allowed={'path','sha256','pointer','source_resource_xrefs','source_line_id'}
    if not isinstance(ref,dict) or not {'path','sha256'}.issubset(ref) or set(ref)-allowed:
        raise ValueError('unsupported source evidence selector fields')
    core={k:ref[k] for k in ('path','sha256')};checked_ref(core)
    if 'pointer' in ref:
        key=(core['path'],core['sha256'])
        if key not in _EVIDENCE_DOCUMENTS:_EVIDENCE_DOCUMENTS[key]=load(core)
        value=_EVIDENCE_DOCUMENTS[key]
        for part in ref['pointer'].split('/')[1:]:
            part=part.replace('~1','/').replace('~0','~')
            try:value=value[int(part)] if isinstance(value,list) else value[part]
            except (KeyError,IndexError,ValueError,TypeError) as exc:
                raise ValueError('source evidence JSON selector absent') from exc
        return value
    return None


def validate_native_member_inventory(metadata, unit):
    if 'source_native_members' not in unit:return  # component-only controls; load_contract requires full ledger
    evidence=checked_evidence({**metadata['source_native_style_evidence_ref'],'pointer':''})
    rows=[r for r in evidence['components'] if (r['group_id'],r['component_id'])==
          (unit['group_id'],unit['component_id'])]
    if len(rows)!=1:raise ValueError('complete source native component inventory missing')
    ledger=load(metadata['source_ledger_ref'])
    group=next(g for g in ledger['groups'] if g['group_id']==unit['group_id'])
    original=next(c for c in group['components'] if c['component_id']==unit['component_id'])
    if unit.get('source_scientific_ids')!=original['scientific_ids']:
        raise ValueError('source style SCI inventory differs from source compiler')
    expected={}
    for line in rows[0]['lines']:
        for char in line['actual_chars']:
            index=char.get('source_native_index')
            if type(index) is not int:continue  # rawdict inferred gaps are not native painted members
            key=f"source-p{unit['source_page']}-native-{index}"
            if key in expected:raise ValueError('original native component member duplicate')
            expected[key]=(line,char)
    if not rows[0]['lines']:
        if not original['immutable'] or not original['scientific_ids']:
            raise ValueError('source component with no natural inventory is not fixed SCI identity')
        bindings=checked_evidence({**metadata['source_science_bindings_ref'],'pointer':''})
        for object_index,obj in enumerate(bindings['items']):
            if obj['scientific_id'] not in original['scientific_ids']:continue
            actual_source=next(x for x in group['scientific_objects'] if x['scientific_id']==obj['scientific_id'])
            if obj['qualified_source_object_sha256']!=actual_source['source_object_sha256']:
                raise ValueError('display original scientific object identity changed')
            for member_index,member in enumerate(obj['members']):
                index=member['actual_native_index']
                if type(index) is not int:continue
                key=f"source-p{unit['source_page']}-native-{index}"
                if key in expected:raise ValueError('duplicate original display native member')
                ref={**metadata['source_science_bindings_ref'],'pointer':f'/items/{object_index}/members/{member_index}'}
                expected[key]=({'source_binding_ref':ref},member)
    members={};layouts={}; roles={'natural','scientific_object','scientific_syntax','source_identity','layout_whitespace'}
    for member in unit['source_native_members']:
        key=member['member_id'];selector=member['source_native_glyph_selector']
        if member['role']=='layout_whitespace' and selector is None:
            if key in layouts or member.get('original_IL_code_is_physical_GID') is not False:
                raise ValueError('layout source member must not claim a physical painted GID')
            layout_proof=checked_evidence(member['source_member_ref'])
            if (layout_proof.get('source_IL_character_code') is not None or layout_proof.get('actual_glyph') is not None
                    or layout_proof.get('source_IL_code_is_actual_MuPDF_GID') is not False):
                raise ValueError('layout namespace source is actually a painted member')
            layouts[key]=member;continue
        if key in members or key not in expected or member['role'] not in roles:
            raise ValueError('source native member duplicate/unknown/origin role')
        line,char=expected[key]
        if 'source_binding_ref' in line:
            if (member['role']!='source_identity' or selector['page']!=unit['source_page']
                    or selector['native_index']!=char['actual_native_index']
                    or selector.get('source_actual_binding_ref')!=line['source_binding_ref']
                    or member['source_member_ref']!=line['source_binding_ref']):
                raise ValueError('fixed display actual source member selector changed')
            checked_evidence(member['source_member_ref']);members[key]=member;continue
        if (member['source_member_ref']['source_line_id']!=line['source_line_id']
                or member['source_member_ref']['pointer']!=char['rawdict_char_pointer']
                or selector['page']!=unit['source_page'] or selector['native_index']!=char['source_native_index']
                or selector['source_resource_xref']!=char['source_font_resource_xref']
                or selector['source_font_sha256']!=char['source_font_sha256']
                or selector['source_physical_GID']!=char['source_physical_GID']):
            raise ValueError('native source member line/resource/code identity differs')
        if not original['immutable'] and char.get('science_member') is True and member['role']!='scientific_object':
            proof_ref=member.get('source_formula_role_ref')
            if proof_ref is None:raise ValueError('original source scientific member cannot become ordinary style')
            proof=checked_evidence(proof_ref)
            if (not ((member['role']=='natural' and proof.get('role')=='natural_formula')
                         or (member['role']=='source_identity' and proof.get('role')=='source_identity'
                             and proof.get('identity_source_object_sha256') in {o['source_object_sha256'] for o in group.get('identity_objects',[])}))
                    or proof.get('source_object_sha256') not in original.get('natural_formula_object_shas',[])
                    or key not in proof.get('source_native_member_ids',[])):
                raise ValueError('natural formula role lacks exact source object/member approval')
        checked_evidence(member['source_member_ref'])
        checked_evidence(selector['source_actual_show_ref'])
        members[key]=member
    if set(members)!=set(expected):raise ValueError('original source native member omission')
    natural=[mid for run in unit['source_style_runs'] for mid in run.get('source_native_member_ids',[])]
    syntax=[mid for run in unit.get('scientific_syntax_ranges',[]) for mid in run['source_native_member_ids']]
    punct=[mid for run in unit.get('source_punctuation_adaptations',[]) for mid in run['source_native_member_ids']]
    for ids,role in [(natural,'natural'),(syntax,'scientific_syntax'),(punct,'punctuation_adaptation')]:
        expected_role={key for key,row in members.items() if
            (bool(row.get('named_source_punctuation_adaptation')) if role=='punctuation_adaptation'
             else row['role']==role and not row.get('named_source_punctuation_adaptation')
                  and not row.get('source_whitespace'))}
        if len(ids)!=len(set(ids)) or set(ids)!=expected_role:
            raise ValueError('complete source style/syntax/adaptation member partition differs')
    expected_layout={f"original-IL-{obj['scientific_id']}-glyph-{index}":glyph.get('glyph',glyph)
        for obj in group['scientific_objects'] if obj['scientific_id'] in original['scientific_ids']
        for index,glyph in enumerate(obj['glyphs']) if glyph.get('glyph',glyph)['gid'] is None}
    if set(layouts)!=set(expected_layout):raise ValueError('source layout member namespace omission')
    for key,row in layouts.items():
        proof=checked_evidence(row['source_member_ref'])
        if proof['source_unicode_field']!=expected_layout[key]['unicode']:
            raise ValueError('original IL layout source bytes changed')
    return members


def component_packet(mapping_ref):
    mapping = load(mapping_ref)
    if mapping.get('protocol') != 'finite_source_style_effective_full_group_mapping_v1':
        raise ValueError('explicit complete effective source-target mapping required')
    groups = {}; components = {}
    for row in mapping['groups']:
        source = load(row['source_ref']); target = load(row['effective_target_ref'])
        gid = row['group_id']
        if gid in groups or source['group_id'] != gid or target['group_id'] != gid:
            raise ValueError('duplicate or mismatched complete source-target group')
        if target['source_ref'] != row['source_ref'] or target['target_masked_sha256'] != digest(target['target_masked_text']):
            raise ValueError('effective target source/full digest changed')
        groups[gid] = {'source': source['source_group'], 'target': target, 'row': row}
        for child in target['components']:
            key = (gid, child['component_id'])
            lo, hi = child['target_full_group_unicode_range']
            value = child['target_masked_text']
            if (key in components or target['target_masked_text'][lo:hi] != value
                    or child['target_masked_sha256'] != digest(value)):
                raise ValueError('effective component range/digest differs')
            components[key] = child
    return mapping, groups, components


def review_metadata(ref, expected_status, expected_refs):
    report = load(ref)
    if (report.get('status') != expected_status or report.get('unresolved') not in ([], 0)
            or not report.get('reviewer_id') or report.get('reviewer_id') == report.get('producer_id')
            or not isinstance(report.get('input_refs'), dict)):
        raise ValueError('independent finite metadata review unresolved or absent')
    for name, expected in expected_refs.items():
        if report['input_refs'].get(name) != expected:
            raise ValueError('metadata review input identity differs:'+name)
        checked_ref(expected)
    return report


def validate_style_metadata(metadata_ref, mapping_ref, current_source_ledger_ref):
    metadata = load(metadata_ref)
    if metadata.get('protocol') != STYLE_PROTOCOL:
        raise ValueError('unknown source-target style metadata protocol')
    mapping, groups, components = component_packet(mapping_ref)
    source_ledger = load(metadata['source_ledger_ref'])
    current = load(current_source_ledger_ref)
    if (metadata['effective_targets_ref'] != mapping_ref or metadata['source_pdf_ref'] != mapping['source_pdf_ref']
            or source_semantics(source_ledger) != source_semantics(current)):
        raise ValueError('source style metadata complete source/effective target identity differs')
    for ref in metadata['source_native_evidence_refs']:
        checked_ref(ref)
    units = {}
    for unit in metadata['units']:
        if not STYLE_UNIT_FIELDS.issubset(unit):
            raise ValueError('source style unit fields missing')
        key = (unit['group_id'], unit['component_id'])
        if key in units or key not in components:
            raise ValueError('duplicate or unknown complete style component')
        component = components[key]; original = component['source_component']
        group = groups[key[0]]['source']; text = component['target_masked_text']
        if (unit['source_original_character_range'] != original.get('source_range')
                or unit['source_paragraph_sha256'] != original.get('source_paragraph_sha256')
                or unit['source_page'] != original['source_page'] or unit['source_role'] != group['source_role']
                or unit['target_component_sha256'] != digest(text)):
            raise ValueError('style source range/role/page or full target changed')
        for ref in unit['source_native_font_resource_refs'] + unit['source_line_evidence_refs']:
            checked_evidence(ref)
        validate_native_member_inventory(metadata,unit)
        if original['immutable'] or original['kind'] != 'source_fragment':
            if unit.get('preserved_source_identity') is not True or unit['target_natural_style_ranges']:
                raise ValueError('immutable/display source is not natural style output')
            units[key] = unit; continue
        if unit['alignment'] not in ('left', 'right', 'center', 'justified'):
            raise ValueError('unknown source alignment')
        for name in ('first_line_indent_pt', 'hanging_indent_pt', 'source_first_baseline'):
            finite_number(unit[name])
        finite_number(unit['source_modal_font_size'], positive=True)
        source_runs = {}
        for run in unit['source_style_runs']:
            if not run.get('run_id') or run['run_id'] in source_runs:
                raise ValueError('duplicate source style run')
            for name in ('bold', 'italic'):
                if type(run.get(name)) is not bool:
                    raise ValueError('explicit source style flag required')
            checked_evidence(run['font_resource_ref']); checked_evidence(run['source_style_definition_ref'])
            source_runs[run['run_id']] = run
        science_positions = {i for match in re.finditer(r'\[\[(?:PTS|PTI):[^\]]+\]\]', text)
                             for i in range(match.start(), match.end())}
        covered = set();special=set()
        for kind,items in [('syntax',unit.get('scientific_syntax_ranges',[])),
                           ('punctuation',unit.get('source_punctuation_adaptations',[]))]:
            for item in items:
                lo,hi=exact_range(item['target_unicode_range'],len(text));positions=set(range(lo,hi))
                if positions & (special|science_positions) or text[lo:hi]!=item['target_literal']:
                    raise ValueError('reviewed syntax/adaptation overlaps or target bytes differ')
                special|=positions
                if kind=='syntax':
                    if (item['font_scale']!=1.0 or item['bold'] is not False or item['italic'] is not False
                            or item['source_literal']!=item['target_literal']):
                        raise ValueError('original upright scientific syntax identity changed')
                    checked_evidence(item['source_font_resource_ref']);checked_ref(item['source_syntax_review_ref'])
                else:checked_ref(item['source_adaptation_review_ref'])
                review_name='source_syntax_review_ref' if kind=='syntax' else 'source_adaptation_review_ref'
                if item[review_name]!=metadata['source_syntax_and_punctuation_review_ref']:
                    raise ValueError('source syntax/adaptation lacks the named independent role approval')
        for target_run in unit['target_natural_style_ranges']:
            lo, hi = exact_range(target_run['range'], len(text))
            ids = target_run['source_style_run_ids']
            if not ids or any(sid not in source_runs for sid in ids):
                raise ValueError('target natural style has no source run')
            if type(target_run.get('bold')) is not bool or type(target_run.get('italic')) is not bool:
                raise ValueError('explicit target style flag required')
            if target_run['bold'] and target_run['italic']:
                raise ValueError('combined bold-italic is outside finite CJK font profile')
            if any((source_runs[sid]['bold'], source_runs[sid]['italic'], source_runs[sid]['color']) !=
                   (target_run['bold'], target_run['italic'], target_run['color']) for sid in ids):
                raise ValueError('source/target semantic style correspondence differs')
            positions = set(range(lo, hi))
            if positions & (science_positions|special) or positions & covered:
                raise ValueError('natural style overlaps science or another target run')
            covered |= positions
        expected = {i for i, char in enumerate(text) if not char.isspace() and i not in science_positions|special}
        if not expected.issubset(covered) or covered - expected - {i for i,c in enumerate(text) if c.isspace()}:
            raise ValueError('complete natural target style coverage missing')
        if set(source_runs) != {sid for run in unit['target_natural_style_ranges'] for sid in run['source_style_run_ids']}:
            raise ValueError('ordinary source style span silently uncovered')
        units[key] = unit
    if set(units) != set(components):
        raise ValueError('full source component style inventory incomplete')
    return metadata, units


def validate_host_metadata(metadata_ref, mapping_ref, source_ledger_ref):
    metadata = load(metadata_ref)
    mapping, groups, components = component_packet(mapping_ref)
    if (metadata.get('protocol') != HOST_PROTOCOL or metadata['effective_targets_ref'] != mapping_ref
            or metadata['source_pdf_ref'] != mapping['source_pdf_ref']
            or source_semantics(load(metadata['source_ledger_ref'])) != source_semantics(load(source_ledger_ref))):
        raise ValueError('authored host full source/effective target identity differs')
    for ref in metadata['source_action_evidence_refs']:
        checked_ref(ref)
    seen = set()
    for action in metadata['actions']:
        selector = action['projection_selector']; kind = selector.get('kind')
        required=HOST_ACTION_FIELDS-{'source_intent_evidence_refs'} if kind=='protected_source_role' else HOST_ACTION_FIELDS
        if not required.issubset(action) or action['action_id'] in seen:
            raise ValueError('complete unique authored source action required')
        seen.add(action['action_id'])
        for ref in (action['source_raw_action_ref'], action['source_destination_ref'], *action.get('source_intent_evidence_refs',[])):
            checked_evidence(ref)
        if kind == 'protected_source_role':
            if any(action[name] is not None for name in ('target_group_id','target_component_id','target_component_sha256',
                                                        'source_full_group_ref','source_complete_context_unicode_range')):
                raise ValueError('protected identity must not claim a translated target unit')
            checked_ref(selector['source_role_ref']); checked_ref(selector['source_pixel_action_proof_ref'])
            continue
        checked_ref(action['source_full_group_ref'])
        key = (action['target_group_id'], action['target_component_id'])
        if key not in components or action['target_component_sha256'] != components[key]['target_masked_sha256']:
            raise ValueError('authored host effective complete target differs')
        source_group = load(action['source_full_group_ref'])
        source_group = source_group.get('source_group', source_group)
        if source_semantics(source_group) != source_semantics(groups[key[0]]['source']):
            raise ValueError('action bound to another source group')
        text = components[key]['target_masked_text']
        if kind == 'scientific_members':
            objects = [obj for obj in groups[key[0]]['source']['scientific_objects']
                       if obj['scientific_id'] == selector['scientific_id']]
            if len(objects) != 1:
                raise ValueError('unknown source scientific action host')
            obj = objects[0]; members = selector['source_original_member_indices']
            if (obj['source_object_sha256'] != selector['source_scientific_object_sha256']
                    or selector['scientific_id'] not in components[key]['source_component']['scientific_ids']
                    or not isinstance(members, list) or not members or members != sorted(set(members))
                    or any(type(n) is not int or not 0 <= n < len(obj['glyphs']) for n in members)):
                raise ValueError('complete source scientific member selector differs')
            for ref in selector['source_member_actual_binding_refs']:
                checked_evidence(ref)
        elif kind == 'natural_target_span':
            science = [(m.start(), m.end()) for m in re.finditer(r'\[\[(?:PTS|PTI):[^\]]+\]\]', text)]
            if not selector['target_unicode_ranges'] or not selector['source_original_character_ranges']:
                raise ValueError('complete original/effective natural host ranges required')
            used = set()
            for value in selector['target_unicode_ranges']:
                lo, hi = exact_range(value, len(text)); positions = set(range(lo, hi))
                if used & positions or any(lo < b and hi > a for a,b in science):
                    raise ValueError('natural action host crosses source science or duplicate span')
                used |= positions
        else:
            raise ValueError('unknown or nearest-number action projection forbidden')
    return metadata


def natural_size(unit):
    return finite_number(unit['source_modal_font_size'], positive=True) * NATURAL_FONT_SCALE.get(unit['source_role'], CJK_BODY_SCALE)


def role_for_span(run):
    return 'bold' if run['bold'] else 'italic' if run['italic'] else 'regular'


def alias_font(original, role):
    if role not in ('regular', 'bold', 'italic'):
        raise ValueError('unknown reviewed natural font role')
    font = copy.deepcopy(original)
    font.font_id = 'paper-reviewed-'+role
    font.bold = int(role == 'bold'); font.italic = int(role == 'italic')
    # Generated IL dataclasses have slots. Do not attach unrecorded fields or
    # pretend a resource name can authorize an alias from an input PDF.
    _FONT_ALIASES[id(font)] = (font, role)
    owner=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_RENDER_ID')
    _FONT_ALIAS_OWNERS[id(font)]=owner if owner in _RUNTIMES else None
    return font


def reviewed_font(mapper, original_font, char):
    """自然目标alias选择明确font；原SCI字体不进入该alias分支。"""
    entry = _FONT_ALIASES.get(id(original_font))
    if entry is None:
        return None
    if entry[0] is not original_font:raise ValueError('reviewed font alias object changed')
    role = entry[1]
    cjk = bool(re.match(r'[\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff01-\uff60\uffe0-\uffe6]', char))
    name = FONT_FILES['italic_cjk' if cjk else 'italic_latin'] if role == 'italic' else FONT_FILES[role]
    if name not in mapper.fonts or not mapper.fonts[name].has_glyph(ord(char)):
        raise ValueError('declared reviewed style font/glyph unavailable; regular fallback forbidden')
    return mapper.fonts[name]


def install_reviewed_fonts(mapper):
    try:return _install_reviewed_fonts(mapper)
    except BaseException:
        release_current_runtime('reviewed_font_initialization_failure')
        raise


def _install_reviewed_fonts(mapper):
    registry=current_registry()
    if registry is None:return
    import pymupdf
    for ref in registry.style['fonts']:
        path=Path(checked_ref(ref)['path']);name=path.name
        if name not in FONT_FILES.values():continue
        if name in mapper.fonts:
            if Path(mapper.fontid2fontpath[name]).resolve()!=path.resolve():
                raise ValueError('declared target style font path aliases another asset')
            continue
        font=pymupdf.Font(fontfile=str(path))
        font.font_id=name;font.font_path=path;font.encoding_length=2
        font.ascent_fontmap=font.ascender*1000;font.descent_fontmap=font.descender*1000
        mapper.fonts[name]=font;mapper.fontid2font[name]=font;mapper.fontid2fontpath[name]=path


class RenderRegistry:
    """当前调用的对象传播与真正emit/streamcommit；对象ID仅进程内使用。"""
    def __init__(self, render_id, directory):
        from pdf_source_cache import render_invocation_id
        self.render_id = render_invocation_id(render_id)
        self.directory = Path(directory)
        self.objects = {}; self.staged = {}; self.committed = {}; self.generations = {}
        self.expected = set(); self.layout_unknowns = {}
        self.lock = threading.RLock()

    def bind(self, obj, facts):
        if not isinstance(facts, dict) or not facts:
            raise ValueError('explicit source-bound object facts required')
        with self.lock:
            old = self.objects.get(id(obj))
            if old is not None and (old[0] is not obj or old[1] != facts):
                raise ValueError('current object metadata collision')
            self.objects[id(obj)] = (obj, copy.deepcopy(facts))
            if type(obj).__name__=='PdfCharacter' and facts.get('source_il_code') is None and facts.get('scientific_members'):
                self.layout_unknowns[facts['source_glyph_sha256']]=copy.deepcopy(facts)
            elif type(obj).__name__=='PdfCharacter':self.expected.update(self.coverage_keys(facts))
            elif facts.get('origin')=='reviewed_complete_target_natural_span' and hasattr(obj,'unicode'):
                if obj.unicode and not obj.unicode.isspace():self.expected.update(self.coverage_keys(facts))

    @staticmethod
    def coverage_keys(facts):
        keys={('science',m['group_id'],m['scientific_id'],m['source_member_index']) for m in facts.get('scientific_members',[])}
        if facts.get('origin')=='reviewed_complete_target_natural_span':
            a,b=facts['target_unicode_range']
            keys.update(('natural',facts['group_id'],facts['component_id'],i)for i in range(a,b))
        if facts.get('preserved_source_identity'):
            keys.add(('source_identity',facts['source_glyph_sha256']))
        return keys

    def facts(self, obj):
        row = self.objects.get(id(obj))
        if row is None:return None
        if row[0] is not obj:raise ValueError('object reference recycled')
        return copy.deepcopy(row[1])

    def transfer(self, old, new):
        facts = self.facts(old)
        if facts is not None:self.bind(new,facts)

    def extend(self, obj, extras):
        facts=self.facts(obj)
        if facts is None or any(k in facts and facts[k]!=v for k,v in extras.items()):
            raise ValueError('source object extension changes existing provenance')
        with self.lock:self.objects[id(obj)]=(obj,{**facts,**copy.deepcopy(extras)})

    def start_stream(self, page, xobj):
        key = (page,xobj)
        with self.lock:
            generation = self.generations.get(key,0)+1
            self.generations[key] = generation
            self.staged[(page,xobj,generation)] = []
        return generation

    def emitted(self, char, page, xobj, generation, offset, operation, code, font_id, matrix):
        facts = self.facts(char)
        if facts is None:
            raise ValueError('actual character has no current source/style provenance')
        if (not isinstance(operation,bytes) or not operation.endswith(b' Tj ET Q \n')
                or offset < 0 or type(generation) is not int):
            raise ValueError('successful exact Tj emission required')
        key = (page,xobj,generation)
        with self.lock:
            if self.generations.get((page,xobj)) != generation or key not in self.staged:
                raise ValueError('stale/uncommitted stream generation')
            self.staged[key].append({'render_id':self.render_id,'page_number':page,'xobject_id':xobj,
                'generation':generation,'byte_offset':offset,'operation_length':len(operation),
                'operation_sha256':hashlib.sha256(operation).hexdigest(),'encoded_hex':code,
                'font_resource':font_id,'font_size':char.pdf_style.font_size,
                'text_matrix':list(matrix),'graphic_state_sha256':digest(repr(char.pdf_style.graphic_state)),
                'unicode':char.char_unicode,'source_binding':facts,
                'physical_gid':None,'stage':'actual_Tj_before_final_subset_reopen'})

    def commit(self, page, xobj, generation, stream_xref, stream):
        key = (page,xobj,generation)
        with self.lock:
            if self.generations.get((page,xobj)) != generation or key not in self.staged:
                raise ValueError('wrong stream commit generation')
            rows = self.staged.pop(key)
            for row in rows:
                data=stream[row['byte_offset']:row['byte_offset']+row['operation_length']]
                if hashlib.sha256(data).hexdigest()!=row['operation_sha256']:
                    raise ValueError('actual committed stream differs from successful emit')
            old=self.committed.get((page,xobj))
            if old is not None:self.append('DISCARDED_WRITER_GENERATIONS.jsonl',old)
            current={'render_id':self.render_id,'page_number':page,'xobject_id':xobj,'generation':generation,
                'stream_xref':stream_xref,'decoded_stream_sha256':hashlib.sha256(stream).hexdigest(),'rows':rows}
            self.committed[(page,xobj)]=current
            self.append('COMMITTED_WRITER_GENERATIONS.jsonl',current)

    def append(self, name, value):
        self.directory.mkdir(parents=True,exist_ok=True)
        with (self.directory/name).open('a',encoding='utf-8') as file:
            file.write(json.dumps(value,ensure_ascii=False)+'\n')


def current_registry():
    """只有显式source-style合同启动写时证据；普通历史路线不进入。"""
    path = os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT')
    if not path:return None
    from pdf_source_cache import render_invocation_id, source_cache
    render_id = render_invocation_id()
    contract_ref = {'path':path,'sha256':os.environ['PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT_SHA']}
    checked_ref(contract_ref)
    context_ref = {'path':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT'],
                   'sha256':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']}
    with _RUNTIME_LOCK:
        if render_id in _RUNTIMES:
            registry=_RUNTIMES[render_id]
            if registry.contract_ref!=contract_ref or registry.context_ref!=context_ref:
                raise ValueError('current writer invocation contract/context changed')
            return registry
        cache=source_cache(context_ref,'read')
        if cache.context.get('source_style_contract_ref') != contract_ref:
            raise ValueError('style contract is not bound into current renderer context')
        registry=RenderRegistry(render_id,cache.collection.parent/'writer'/render_id)
        registry.contract_ref=contract_ref;registry.context_ref=context_ref
        registry.style=load_contract(contract_ref,cache)
        _RUNTIMES[render_id]=registry
        return registry


def tag_source_document(docs):
    registry=current_registry()
    if registry is None:return
    from dataclasses import asdict, is_dataclass, fields
    from pdf_source_cache import source_cache
    from pdf_source_groups import _glyph
    cache=source_cache(registry.context_ref,'read')
    science={}
    for group in cache.groups.values():
        for obj in group['scientific_objects']:
            for index,glyph in enumerate(obj['glyphs']):
                key=digest(json.dumps(glyph.get('glyph',glyph),sort_keys=True))
                science.setdefault(key,[]).append({'group_id':group['group_id'],
                    'scientific_id':obj['scientific_id'],'source_member_index':index,
                    'source_object_sha256':obj['source_object_sha256']})
    def walk(obj):
        if type(obj).__name__=='PdfCharacter':yield obj
        elif isinstance(obj,list):
            for child in obj:yield from walk(child)
        elif is_dataclass(obj):
            for field in fields(obj):yield from walk(getattr(obj,field.name))
    for page in docs.page:
        fonts={f.font_id:asdict(f) for f in page.pdf_font}
        for form in page.pdf_xobject:
            for font in form.pdf_font:fonts.setdefault(font.font_id,asdict(font))
        for char in walk(page):
            glyph=_glyph(page.page_number+1,asdict(char),fonts)
            key=digest(json.dumps(glyph,sort_keys=True))
            science_members=science.get(key,[])
            action_ids=[row['action_id'] for row in registry.style['hosts']['actions']
                if row['projection_selector']['kind']=='scientific_members' and any(
                    member['scientific_id']==row['projection_selector']['scientific_id']
                    and member['source_member_index'] in row['projection_selector']['source_original_member_indices']
                    for member in science_members)]
            registry.bind(char,{'origin':'original_source_IL_member','source_pdf_ref':cache.context['input_ref'],
                'source_glyph_sha256':key,'source_il_code':char.pdf_character_id,
                'scientific_members':science_members,'source_authored_action_ids':action_ids,
                'layout_origin':'source_il_code_missing' if char.pdf_character_id is None else 'source_IL_encoded',
                'source_physical_gid':None})
        from pdf_source_cache import group_fragment_roles
        from pdf_source_groups import _paragraph
        _,immutable=group_fragment_roles(cache)
        protected={row['source_object_sha256'] for row in cache.ledger['protected_source_objects']}|set(immutable)
        for paragraph in page.pdf_paragraph:
            active=dict(fonts)
            for form in page.pdf_xobject:
                if form.xobj_id==paragraph.xobj_id:active.update({f.font_id:asdict(f) for f in form.pdf_font})
            source=_paragraph(page.page_number+1,asdict(paragraph),active,cache.context['input_ref']['sha256'])
            registry.bind(paragraph,{'mode':'preserve_original' if source['sha256'] in protected else 'original_pending_projection',
                'source_paragraph_sha256':source['sha256'],'source_page':page.page_number+1})
            if source['sha256'] in protected:
                for char in walk(paragraph):
                    registry.extend(char,{'preserved_source_identity':True})
                    if char.pdf_character_id is not None:registry.expected.update(registry.coverage_keys(registry.facts(char)))


def original_position_members(paragraph):
    """沿用源编译器的NFKC顺序绑定；保留实际字形并拒绝歧义。"""
    from pdf_source_groups import _compact_map
    compact,positions=_compact_map(paragraph.unicode);cursor=0;result={}
    for composition in paragraph.pdf_paragraph_composition:
        if composition.pdf_character:chars=[composition.pdf_character]
        elif composition.pdf_same_style_characters:chars=composition.pdf_same_style_characters.pdf_character
        elif composition.pdf_line:chars=composition.pdf_line.pdf_character
        elif composition.pdf_formula:chars=composition.pdf_formula.pdf_character
        else:raise ValueError('unknown original source composition in reviewed projection')
        for char in chars:
            value,_=_compact_map(char.char_unicode or '')
            if compact[cursor:cursor+len(value)]!=value:
                raise ValueError('original source glyph sequence disagrees with full paragraph Unicode')
            for index in range(cursor,cursor+len(value)):
                position=positions[index]
                if position in result and result[position] is not char:
                    raise ValueError('ambiguous original source glyph position')
                result[position]=char
            cursor+=len(value)
    if cursor!=len(compact):raise ValueError('original source member omission')
    return result


def reviewed_component_projection(translator, original, translate_input, source_fact, page, fonts, actual_http_output):
    """一个完整源宿主HTTP之后按已审组分开显示；不改变provider输入或历史RAW。"""
    registry=current_registry()
    if registry is None:return None
    from pdf_source_cache import source_cache
    from babeldoc.format.pdf.document_il import il_version_1 as il
    cache=source_cache(registry.context_ref,'read')
    from pdf_source_cache import GROUP_RENDER_CONTROL
    expected,_=cache.render_literal(source_fact['source_literal'],GROUP_RENDER_CONTROL,
        source_paragraph_sha256=source_fact['source_sha256'])
    if actual_http_output!=expected:
        raise ValueError('actual complete HTTP projection differs from reviewed current target')
    members=[(g,c) for g in cache.groups.values() for c in g['components']
        if c['kind']=='source_fragment' and c['source_paragraph_sha256']==source_fact['source_sha256']
        and not c['immutable']]
    members.sort(key=lambda row:row[1]['source_range'])
    if not members:raise ValueError('ordinary current source has no reviewed complete target component')
    _,_,targets=component_packet(registry.style['contract']['effective_targets_ref'])
    positioned=original_position_members(original);copies=[]
    for group,component in members:
        key=(group['group_id'],component['component_id']);metadata=registry.style['units'][key]
        target=targets[key]['target_masked_text'];size=natural_size(metadata)
        selected={row['scientific_id']:row['placeholder'] for row in component['backend_placeholder_map']
                  if row['in_component'] and row['scientific_id'] is not None}
        if set(selected)!=set(component['scientific_ids']):raise ValueError('reviewed component SCI mapping incomplete')
        original_placeholders={p.placeholder:p for p in translate_input.placeholders if hasattr(p,'placeholder')}
        compositions=[];cursor=0
        tokens=list(re.finditer(r'\[\[(PTS|PTI):([^\]]+)\]\]',target))
        for token in tokens+[None]:
            end=token.start() if token else len(target)
            natural_cursor=cursor
            while natural_cursor<end:
                syntax=next((r for r in metadata.get('scientific_syntax_ranges',[])
                             if r['target_unicode_range'][0]==natural_cursor),None)
                if syntax is not None:
                    lo,hi=syntax['target_unicode_range'];a,b=syntax['source_original_character_range']
                    chars=[]
                    for index in range(a,b):
                        char=positioned.get(index)
                        if char is None and original.unicode[index].isspace():continue
                        if char is None:raise ValueError('scientific syntax source member absent')
                        if char not in chars:chars.append(char)
                    if ''.join(c.char_unicode for c in chars)!=target[lo:hi]:
                        raise ValueError('source scientific syntax bytes differ from complete target range')
                    for char in chars:
                        registry.extend(char,{'reviewed_scientific_syntax_id':syntax['syntax_id'],
                            'source_syntax_review_ref':syntax['source_syntax_review_ref']})
                    compositions.append(il.PdfParagraphComposition(pdf_same_style_characters=il.PdfSameStyleCharacters(
                        pdf_character=chars,pdf_style=chars[0].pdf_style)))
                    natural_cursor=hi;continue
                run=next((r for r in metadata['target_natural_style_ranges'] if r['range'][0]<=natural_cursor<r['range'][1]),None)
                if run is None:
                    adaptation=next((r for r in metadata.get('source_punctuation_adaptations',[])
                        if r['target_unicode_range'][0]==natural_cursor),None)
                    if adaptation is None:raise ValueError('unreviewed natural target span')
                    run={'range':adaptation['target_unicode_range'],'bold':adaptation['target_body_bold'],
                         'italic':adaptation['target_body_italic'],'color':[0,0,0],
                         'source_punctuation_adaptation_id':adaptation['adaptation_id']}
                hi=min(run['range'][1],end)
                future=[r['target_unicode_range'][0] for r in metadata.get('scientific_syntax_ranges',[])
                        if natural_cursor<r['target_unicode_range'][0]<hi]
                if future:hi=min(future)
                copied_style=copy.deepcopy(translate_input.base_style)
                alias=alias_font(fonts[copied_style.font_id],role_for_span(run))
                registry.font_aliases=getattr(registry,'font_aliases',{})
                registry.font_aliases[alias.font_id]=alias
                copied_style.font_id=alias.font_id;copied_style.font_size=size
                comp=il.PdfParagraphComposition(pdf_same_style_unicode_characters=il.PdfSameStyleUnicodeCharacters(
                    unicode=target[natural_cursor:hi],pdf_style=copied_style))
                registry.bind(comp,{'origin':'reviewed_complete_target_natural_span','group_id':key[0],
                    'component_id':key[1],'component_sha256':digest(target),'target_unicode_range':[natural_cursor,hi],
                    'source_paragraph_sha256':source_fact['source_sha256']})
                compositions.append(comp);natural_cursor=hi
            if token:
                sid=token.group(2)
                if token.group(1)=='PTI':
                    obj=next((o for o in group.get('identity_objects',[]) if o['identity_id']==sid),None)
                    if obj is None or sid not in component.get('identity_ids',[]):
                        raise ValueError('component identity typed source missing')
                    chars=[]
                    for index in range(*obj['range']):
                        char=positioned.get(index)
                        if char is None and original.unicode[index].isspace():continue
                        if char is None:raise ValueError('identity original glyph missing')
                        if char not in chars:chars.append(char)
                    if not chars:raise ValueError('empty identity original glyphs')
                    from pdf_source_groups import _compact_map
                    if _compact_map(''.join(c.char_unicode for c in chars))[0]!=_compact_map(obj['source_unicode'])[0]:
                        raise ValueError('identity original glyph bytes changed')
                    box=il.Box(x=min(c.box.x for c in chars),y=min(c.box.y for c in chars),
                               x2=max(c.box.x2 for c in chars),y2=max(c.box.y2 for c in chars))
                    for char in chars:registry.extend(char,{'reviewed_source_identity_id':sid,
                        'source_identity_object_sha256':obj['source_object_sha256']})
                    compositions.append(il.PdfParagraphComposition(pdf_formula=il.PdfFormula(box=box,pdf_character=chars)))
                    cursor=token.end();continue
                if sid not in selected or selected[sid] not in original_placeholders:
                    raise ValueError('component SCI cannot restore original source placeholder')
                placeholder=original_placeholders[selected[sid]]
                parsed=translator.parse_translate_output(translator.TranslateInput(selected[sid],[placeholder],translate_input.base_style),selected[sid])
                if len(parsed)!=1 or not parsed[0].pdf_formula:
                    raise ValueError('source SCI placeholder did not restore complete original formula')
                compositions.extend(parsed)
                cursor=token.end()
        paragraph=copy.deepcopy(original)
        matrices=[c.source_text_matrix for c in positioned.values() if c.source_text_matrix is not None]
        if matrices:
            frame=[float(v) for v in matrices[0].split()]
            if any(max(abs(float(m.split()[i])-frame[i]) for i in range(4))>1e-5 for m in matrices):
                raise ValueError('mixed original rotated paragraph frames')
            paragraph.source_text_matrix=matrices[0]
            a,b,c,d,e,f=frame;det=a*d-b*c;points=[]
            for char in {id(c):c for c in positioned.values()}.values():
                if char.source_text_matrix is None:
                    if (char.char_unicode or '').strip():raise ValueError('mixed rotated/unrotated original paragraph')
                    continue
                aa,bb,cc,dd,ee,ff=(float(v) for v in char.source_text_matrix.split())
                x,y,x2,y2=(float(v) for v in char.source_local_bbox.split())
                for xx in (x,x2):
                    for yy in (y,y2):
                        gx=aa*xx+cc*yy+ee;gy=bb*xx+dd*yy+ff
                        points.append(((d*(gx-e)-c*(gy-f))/det,(-b*(gx-e)+a*(gy-f))/det))
            paragraph.source_local_bbox=' '.join(format(v,'.12g') for v in
                (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)))
        paragraph.pdf_paragraph_composition=compositions
        paragraph.unicode=target;paragraph.optimal_scale=1.0;paragraph.scale=1.0
        paragraph.box=il.Box(**component['source_box'])
        registry.bind(paragraph,{'mode':'reviewed_fixed_layout','source_paragraph_sha256':source_fact['source_sha256'],
            'group_id':key[0],'component_id':key[1],'metadata':metadata,'page_height':page.cropbox.box.y2-page.cropbox.box.y,
            'component_source_ref':component,'target_component_sha256':digest(target)})
        copies.append(paragraph)
    registry.pending_paragraphs=getattr(registry,'pending_paragraphs',{})
    registry.pending_paragraphs[id(original)]=(original,copies)
    registry.append('REVIEWED_RENDER_COMPONENTS.jsonl',{'render_id':registry.render_id,
        'source_paragraph_sha256':source_fact['source_sha256'],'components':[
            {'group_id':registry.facts(p)['group_id'],'component_id':registry.facts(p)['component_id'],
             'effective_target_component_sha256':registry.facts(p)['target_component_sha256']}for p in copies],
        'new_provider_calls':0})
    return copies


def apply_pending_component_paragraphs(docs):
    registry=current_registry()
    if registry is None:return
    pending=getattr(registry,'pending_paragraphs',{});found=set()
    for page in docs.page:
        result=[]
        for paragraph in page.pdf_paragraph:
            row=pending.get(id(paragraph))
            if row is None:result.append(paragraph);continue
            if row[0] is not paragraph:raise ValueError('source paragraph object recycled')
            result.extend(row[1]);found.add(id(paragraph))
        page.pdf_paragraph=result
    if found!=set(pending):raise ValueError('reviewed complete component replacement missing original paragraph')


def bind_natural_typesetting_units(composition, units):
    registry=current_registry()
    if registry is None:return
    facts=registry.facts(composition)
    if facts is None:raise ValueError('natural composition lost complete reviewed target range')
    lo,hi=facts['target_unicode_range']
    if len(units)!=hi-lo:raise ValueError('natural typesetting changed bound complete Unicode range')
    for offset,unit in enumerate(units,lo):
        action_ids=[row['action_id'] for row in registry.style['hosts']['actions']
            if row['target_group_id']==facts['group_id'] and row['target_component_id']==facts['component_id']
            and row['projection_selector']['kind']=='natural_target_span'
            and any(a<=offset<b for a,b in row['projection_selector']['target_unicode_ranges'])]
        registry.bind(unit,{**facts,'target_unicode_range':[offset,offset+1],
                            'source_authored_action_ids':action_ids})


def reviewed_paragraph_facts(paragraph):
    registry=current_registry()
    return registry.facts(paragraph) if registry is not None else None


def source_font_inventory(doc, require_eligible=True):
    """原资源图和实际字体program/mapping；不从字体技术名称猜subset资格。"""
    seen={}; resources=[]
    for page in doc:
        for row in page.get_fonts(full=True):
            xref,ext,_,name,alias,encoding,referencer=row
            resources.append({'page':page.number,'referencer':referencer,'alias':alias,'font_xref':xref})
            if not xref:continue
            if xref in seen:continue
            name,actual_ext,_,program=doc.extract_font(xref)
            if require_eligible and actual_ext in {'otf','ttf','woff','woff2'} and not re.match(r'^[A-Z]{6}\+',name):
                raise ValueError('eligible original source font lacks exact subset prefix')
            reachable={}; queue=[xref]
            while queue:
                member=queue.pop()
                if member in reachable:continue
                obj=doc.xref_object(member,compressed=False)
                stream=doc.xref_stream(member) if doc.xref_is_stream(member) else None
                reachable[member]={'object_sha256':digest(obj),
                    'decoded_stream_sha256':hashlib.sha256(stream).hexdigest() if stream is not None else None}
                # Font graph contains mappings/descriptors/programs, not page tree.
                queue.extend(int(n) for n in re.findall(r'(\d+)\s+0\s+R\b',obj) if int(n) not in reachable)
            seen[xref]={'actual_extension':actual_ext,'name':name,
                'program_sha256':hashlib.sha256(program).hexdigest(),'program_bytes':len(program),'graph':reachable}
    return {'fonts':seen,'resources':resources}


def verify_source_fonts(doc, before):
    after=source_font_inventory(doc,False)
    for xref,row in before['fonts'].items():
        if after['fonts'].get(xref)!=row:
            raise ValueError('original source font program/mapping/descriptor changed')
    for row in before['resources']:
        if row not in after['resources']:
            raise ValueError('original source font resource alias changed')
    return after


def decoded_show_gid(engine, xref, raw, font_sha):
    """有限PDF资源编码→实际fontprogram GID；从已审源show解析规则复用。"""
    if engine._pdf_value(xref,'Subtype')!='/Type1':
        return engine._encoded_gid_width(xref,raw,font_sha)
    from pdf_glyph_paint_evidence import _object
    from pypdf.generic import DictionaryObject,NameObject
    from reportlab.pdfbase import _fontdata
    font=engine.fonts[font_sha]['font']
    if engine.fonts[font_sha]['kind']!='cff' or hasattr(font,'ROS') or len(raw)!=1:
        raise ValueError('final Type1 source program/encoding unsupported')
    value=_object(engine.document,xref,'Encoding')
    if isinstance(value,NameObject):base=str(value).lstrip('/');differences=[]
    elif isinstance(value,DictionaryObject):
        if set(value)-{'/Type','/BaseEncoding','/Differences'}:
            raise ValueError('final source Encoding fields unsupported')
        base=str(value.get('/BaseEncoding','/StandardEncoding')).lstrip('/')
        differences=value.get('/Differences',[])
    elif value is None:
        encoding=font.Encoding;differences=[]
        if isinstance(encoding,list):base=None;names=list(encoding)
        elif encoding=='StandardEncoding':base='StandardEncoding'
        else:raise ValueError('final builtin source encoding unsupported')
    else:raise ValueError('final source Encoding object unsupported')
    if base is not None:
        if base not in {'WinAnsiEncoding','MacRomanEncoding','MacExpertEncoding','StandardEncoding'}:
            raise ValueError('final predefined source encoding unsupported')
        names=list(_fontdata.encodings[base])
    position=None;used=set()
    for entry in differences:
        if isinstance(entry,int) and not isinstance(entry,bool):position=int(entry)
        else:
            if position is None or not 0<=position<=255 or not isinstance(entry,NameObject) or position in used:
                raise ValueError('final actual Differences malformed')
            used.add(position);names[position]=str(entry)[1:];position+=1
    name=names[raw[0]]
    if name is None or font.charset.count(name)!=1 or name not in font.CharStrings.charStrings:
        raise ValueError('final encoded source charstring absent or ambiguous')
    first=engine._pdf_value(xref,'FirstChar');widths=engine._pdf_value(xref,'Widths')
    if first is None or not isinstance(widths,list) or not 0<=raw[0]-int(first)<len(widths):
        raise ValueError('final source declared code width missing')
    return font.charset.index(name),widths[raw[0]-int(first)],raw.hex(),True


def saved_show_operations(doc,page,stream):
    """仅当前writer的单字符Tf/Tm/Tj路径；保存后重读全部实际矩阵。"""
    from pypdf.generic import ContentStream,DecodedStreamObject
    from pdf_glyph_paint_evidence import _mul,metric_neutral_extgstate
    raw=DecodedStreamObject();raw.set_data(stream);operations=ContentStream(raw,None).operations
    identity=[1.,0.,0.,1.,0.,0.];ctm=identity[:];tm=None;active=None;size=0.;inside=False
    horizontal=1.;rise=0.;render=0;charspace=wordspace=0.;stack=[];states=[];shows=[]
    resources={f[4]:f[0] for f in page.get_fonts(full=True) if f[-1]==0}
    for number,(args,op) in enumerate(operations):
        if op==b'q':stack.append((ctm[:],tm,active,size,horizontal,rise,render,charspace,wordspace,list(states)))
        elif op==b'Q':
            if inside or not stack:raise ValueError('final graphics/text stack invalid')
            ctm,tm,active,size,horizontal,rise,render,charspace,wordspace,states=stack.pop()
        elif op==b'cm':ctm=_mul(ctm,list(map(float,args)))
        elif op==b'BT':
            if inside:raise ValueError('nested final text object')
            inside=True;tm=identity[:]
        elif op==b'ET':inside=False;tm=None
        elif op==b'Tf':active=str(args[0]).lstrip('/');size=float(args[1])
        elif op==b'Tm':tm=list(map(float,args))
        elif op==b'Tz':horizontal=float(args[0])/100
        elif op==b'Ts':rise=float(args[0])
        elif op==b'Tr':render=int(args[0])
        elif op==b'Tc':charspace=float(args[0])
        elif op==b'Tw':wordspace=float(args[0])
        elif op==b'gs':states.append(metric_neutral_extgstate(doc,page,str(args[0])))
        elif op==b'Tj':
            if (not inside or tm is None or active not in resources or render!=0 or charspace or wordspace
                    or horizontal!=1 or rise!=0):raise ValueError('final source-style text transform unsupported')
            value=args[0];code=bytes(value) if isinstance(value,bytes) else getattr(value,'original_bytes',None)
            if code is None:raise ValueError('final original show bytes unavailable')
            matrix=_mul(ctm,tm)
            shows.append({'operation_index':number,'font_resource':active,'font_xref':resources[active],
                'encoded_hex':code.hex().upper(),'font_size':size,'text_matrix':tm[:],
                'CTM':ctm[:],'effective_matrix':matrix,'ExtGState_records':list(states),
                'predicted_origin':[matrix[4],page.rect.height-matrix[5]]})
            # Current writer emits one Tj then ET; multi-show advance is out of this route.
            tm=None
        elif op in {b'TJ',b'Td',b'TD',b'T*',b'\'',b'"',b'Do',b'W',b'W*'}:
            raise ValueError('final source-style show/clip/Form operation unsupported')
    if inside or stack:raise ValueError('final source-style graphics stack incomplete')
    return shows


def prepare_owned_unicode_and_action_rects(registry, doc):
    """由本次真实提交写新字体Unicode与动作宿主；原字体和动作对象保留。"""
    import pymupdf
    from owned_font_unicode import bind_owned_font_unicode
    source_xrefs=set(registry.source_fonts['fonts'])
    maps={}; page_fonts={}
    for (number,xobj),committed in registry.committed.items():
        if xobj is not None:raise ValueError('reviewed final host Form unsupported')
        fonts={f[4]:f[0] for f in doc[number].get_fonts(full=True) if f[6]==0}
        page_fonts[number]=fonts
        for row in committed['rows']:
            if row['source_binding'].get('origin')!='reviewed_complete_target_natural_span':continue
            resource=row['font_resource'];xref=fonts.get(resource)
            if resource not in FONT_FILES.values() or xref is None or xref in source_xrefs:
                raise ValueError('reviewed natural Unicode font is not exclusively owned')
            raw=bytes.fromhex(row['encoded_hex'])
            if len(raw)!=2:raise ValueError('owned natural font requires actual two-byte CID')
            code=int.from_bytes(raw,'big');mapping=maps.setdefault(xref,{})
            if code in mapping and mapping[code]!=row['unicode']:
                raise ValueError('owned actual CID has ambiguous complete target Unicode')
            mapping[code]=row['unicode']
    for xref,mapping in maps.items():
        bind_owned_font_unicode(doc,xref,mapping,owned_font_xrefs=set(maps))
    reports=[]
    for number in page_fonts:
        page=doc[number];committed=registry.committed[(number,None)]
        trace=[(span,char) for span in page.get_texttrace() for char in span['chars']]
        actions=[a for a in registry.style['hosts']['actions'] if a['source_page']==number+1]
        actual_links={a['xref']:a for a in page.get_links()}
        annots_before=doc.xref_get_key(page.xref,'Annots')
        for action in actions:
            xref=action['source_annotation_xref']
            if xref not in actual_links:raise ValueError('reviewed original source action xref missing')
            if action['projection_selector']['kind']=='protected_source_role':continue
            members=[r for r in committed['rows'] if action['action_id'] in r['source_binding'].get('source_authored_action_ids',[])]
            if not members:raise ValueError('reviewed source action has no actual emitted host')
            boxes=[];used=set()
            for row in members:
                origin=[row['text_matrix'][4],page.rect.height-row['text_matrix'][5]]
                matches=[(i,char) for i,(span,char) in enumerate(trace) if i not in used
                    and abs(span['size']-row['font_size'])<=.001
                    and max(abs(char[2][n]-origin[n]) for n in range(2))<=.001]
                if len(matches)!=1:raise ValueError('reviewed action actual host glyph missing or ambiguous')
                index,char=matches[0];used.add(index);boxes.append(pymupdf.Rect(char[3]))
            rect=pymupdf.Rect(min(b.x0 for b in boxes),min(b.y0 for b in boxes),max(b.x1 for b in boxes),max(b.y1 for b in boxes))
            if rect.is_empty or not page.rect.contains(rect):raise ValueError('reviewed action host rectangle outside actual page')
            before={k:doc.xref_get_key(xref,k) for k in ('A','Dest')}
            pdf_rect=rect*~page.transformation_matrix
            doc.xref_set_key(xref,'Rect','[%s]'%' '.join(f'{v:.6f}' for v in pdf_rect))
            if any(doc.xref_get_key(xref,k)!=v for k,v in before.items()) or doc.xref_get_key(page.xref,'Annots')!=annots_before:
                raise ValueError('reviewed action rectangle write changed action or annotation identity')
            reports.append({'action_id':action['action_id'],'page':number+1,'annotation_xref':xref,'actual_host_glyphs':len(members),'target_rect':list(rect),'action_preserved':True})
    verify_source_fonts(doc,registry.source_fonts)
    registry.append('OWNED_UNICODE_AND_ACTION_REBIND.jsonl',{'render_id':registry.render_id,'owned_natural_fonts':sorted(maps),'actions':reports,'quality_pass':False})


def verify_saved_writer(registry, saved_path, source_fonts):
    """saved reopen真实stream/资源/字形；预subset code不作physicalGID证明。"""
    import pymupdf
    from glyph_ink_geometry import EmbeddedGlyphInk
    from pdf_source_cache import source_cache, file_ref
    source_cache(registry.context_ref,'read')  # actual current source/code guard again
    result={'render_id':registry.render_id,'saved_pdf_ref':file_ref(saved_path),
        'stage':'saved_reopen_actual_stream_resource_glyph','pages':[],
        'source_font_graph_exact':False,'physical_glyphs_complete':False,'physical_glyphs_unknown':0}
    from collections import Counter
    coverage=Counter(key for current in registry.committed.values() for row in current['rows']
                     for key in registry.coverage_keys(row['source_binding']))
    if set(coverage)!=registry.expected or any(n!=1 for n in coverage.values()):
        raise ValueError('final generation source SCI/target natural/identity coverage missing extra or duplicate')
    result['expected_member_exact_once']=True
    result['source_missing_il_code_layout_unknowns']=list(registry.layout_unknowns.values())
    with pymupdf.open(saved_path) as doc:
        verify_source_fonts(doc,source_fonts);result['source_font_graph_exact']=True
        for (page_number,xobj), committed in sorted(registry.committed.items(),key=lambda row:repr(row[0])):
            if xobj is not None:raise ValueError('final source-style writer Form reconciliation unsupported')
            page=doc[page_number];contents=page.get_contents()
            if contents!=[committed['stream_xref']]:raise ValueError('final saved stream reference changed')
            stream=doc.xref_stream(contents[0])
            if hashlib.sha256(stream).hexdigest()!=committed['decoded_stream_sha256']:
                raise ValueError('final saved actual show stream changed')
            trace=[(span,char) for span in page.get_texttrace() for char in span['chars']]
            used=set();glyphs=[];engines={}
            unicode_maps={}
            fonts={f[4]:f for f in page.get_fonts(full=True) if f[6]==0}
            shows=saved_show_operations(doc,page,stream)
            if len(shows)!=len(committed['rows']):raise ValueError('saved show event coverage missing or extra')
            for row,show in zip(committed['rows'],shows):
                resource=row['font_resource']
                if resource not in fonts:raise ValueError('final actual font resource missing')
                xref=fonts[resource][0]
                program=doc.extract_font(xref)[3]
                if program and xref not in engines:
                    engines[xref]=EmbeddedGlyphInk(doc,page,required_font_xrefs={xref})
                actual_names=set(engines[xref].names) if program else {fonts[resource][3].split('+')[-1]}
                if (show['font_resource']!=resource or show['encoded_hex']!=row['encoded_hex']
                        or abs(show['font_size']-row['font_size'])>.001
                        or show['text_matrix']!=row['text_matrix']):
                    raise ValueError('actual saved code/Tf/Tm differs from successful emit')
                # MuPDF origin is the actual PDF Tm transformed into its page coordinates.
                matrix=show['effective_matrix'];origin=show['predicted_origin']
                matches=[(i,span,char) for i,(span,char) in enumerate(trace) if i not in used
                    and span['font'] in actual_names
                    and abs(span['size']-row['font_size'])<=.001
                    and max(abs(char[2][n]-origin[n]) for n in range(2))<=.001]
                if len(matches)!=1:raise ValueError('final actual emitted glyph/position is missing or ambiguous')
                i,span,char=matches[0];used.add(i)
                glyph={'unicode':char[0],'gid':char[1],'font':span['font'],'size':span['size'],
                       'origin':list(char[2]),'bbox':list(char[3]),'flags':span['flags'],
                       'direction':list(span['dir'])}
                # Physical outline engine receives an actual trace GID and exact current resource.
                if program:
                    ink=engines[xref].describe_many([glyph])[0]
                    font_sha=engines[xref].resource_digests[xref]
                    gid,width,code,single=decoded_show_gid(engines[xref],xref,bytes.fromhex(show['encoded_hex']),font_sha)
                    if gid!=glyph['gid'] or code.upper()!=show['encoded_hex'] or not single:
                        raise ValueError('actual saved resource code does not decode to trace physical GID')
                    direction=[matrix[0],-matrix[1]]
                    if max(abs(glyph['direction'][n]-direction[n])for n in range(2))>.0001:
                        raise ValueError('actual saved CTM/Tm direction differs from trace')
                    show.update(actual_physical_gid=gid,pdf_declared_width_1000=width,font_program_sha256=font_sha)
                    if row['source_binding'].get('origin')=='reviewed_complete_target_natural_span':
                        from pdf_glyph_paint_evidence import parse_tounicode
                        if xref not in unicode_maps:
                            kind,value=doc.xref_get_key(xref,'ToUnicode')
                            if kind!='xref':raise ValueError('new natural font actual ToUnicode resource missing')
                            unicode_maps[xref]=parse_tounicode(doc.xref_stream(int(value.split()[0])))
                        mapping=unicode_maps[xref]
                        raw_code=bytes.fromhex(show['encoded_hex'])
                        if mapping.get(raw_code)!=row['unicode']:
                            raise ValueError('new natural encoded code actual ToUnicode differs from full target')
                        show['actual_ToUnicode']=mapping[raw_code]
                else:
                    ink={'status':'unknown_nonembedded_source_identity','font_xref':xref,
                         'actual_trace_preserved':True,'outline_proven':False}
                    result['physical_glyphs_unknown']+=1
                glyphs.append({'source_binding':row['source_binding'],'encoded_hex':row['encoded_hex'],
                    'final_font_xref':xref,'actual_trace':glyph,'actual_ink':ink,
                    'actual_transform_evidence':show,
                    'final_font_program_sha256':hashlib.sha256(program).hexdigest()})
            if len(trace)!=len(used):raise ValueError('saved PDF has extra/unbound native glyphs')
            result['pages'].append({'page_number':page_number,'stream_ref':committed,
                'final_actual_glyphs':glyphs,'unmatched_trace_count':len(trace)-len(used)})
    result['physical_glyphs_complete']=result['physical_glyphs_unknown']==0
    registry.append('FINAL_SAVED_WRITER_RECONCILIATION.jsonl',result)
    return result


def release_current_runtime(reason):
    value=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_RENDER_ID')
    if not value:return
    with _RUNTIME_LOCK:
        registry=_RUNTIMES.pop(value,None)
        if registry is None:return
        registry.append('RUNTIME_RELEASE.jsonl',{'render_id':value,'reason':reason,
            'retained_sidecar_only':True,'object_count_released':len(registry.objects)})
        for key,(obj,_) in list(_FONT_ALIASES.items()):
            if _FONT_ALIAS_OWNERS.get(key)==value:
                _FONT_ALIASES.pop(key);_FONT_ALIAS_OWNERS.pop(key,None)
        registry.objects.clear();registry.staged.clear();registry.committed.clear()
        if hasattr(registry,'pending_paragraphs'):registry.pending_paragraphs.clear()


def load_contract(contract_ref, cache):
    contract = load(contract_ref)
    if contract.get('protocol') != CONTRACT_PROTOCOL:
        raise ValueError('unknown finite source-style host contract')
    for name in ('policy_ref', 'approval_ref', 'font_assets_ref'):
        checked_ref(contract[name])
    approval = load(contract['approval_ref'])
    if approval.get('policy_ref') != contract['policy_ref']:
        raise ValueError('frozen source style/host approval differs')
    _, groups, _ = component_packet(contract['effective_targets_ref'])
    if set(groups) != set(cache.groups):
        raise ValueError('effective style groups incomplete')
    for gid, group in groups.items():
        if source_semantics(group['source']) != source_semantics(cache.groups[gid]):
            raise ValueError('style metadata has different current source')
        if group['target']['target_masked_text'] != cache.read_group(gid)[0]['whole_group_text']:
            raise ValueError('style metadata changes current effective complete target')
    metadata, units = validate_style_metadata(contract['source_style_metadata_ref'],
        contract['effective_targets_ref'], cache.context['source_ledger_ref'])
    if any('source_native_members' not in unit for unit in units.values()):
        raise ValueError('production source style requires complete native member inventory')
    hosts = validate_host_metadata(contract['source_authored_hosts_ref'],
        contract['effective_targets_ref'], cache.context['source_ledger_ref'])
    common = {'source_pdf_ref': cache.context['input_ref'], 'source_ledger_ref': metadata['source_ledger_ref'],
              'effective_targets_ref': contract['effective_targets_ref']}
    review_metadata(contract['style_review_ref'], 'pass_finite_complete_source_target_style_metadata',
        {**common, 'source_style_metadata_ref': contract['source_style_metadata_ref']})
    review_metadata(contract['host_review_ref'], 'pass_finite_source_authored_effective_target_host_metadata',
        {**common, 'source_authored_hosts_ref': contract['source_authored_hosts_ref']})
    assets = load(contract['font_assets_ref'])
    for ref in assets['fonts']:
        checked_ref(ref)
    if not set(FONT_FILES.values()).issubset({Path(ref['path']).name for ref in assets['fonts']}):
        raise ValueError('finite reviewed style font assets incomplete')
    _EVIDENCE_DOCUMENTS.clear()
    return {'contract': contract, 'units': units, 'hosts': hosts, 'fonts': assets['fonts']}
