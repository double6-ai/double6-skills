"""保护身份中的原生分离重音：依源字形/墨迹及明确TeX宏核对Unicode组合。"""
from __future__ import annotations
import hashlib
import re
import unicodedata
from pathlib import Path
import fitz
from qa_source_contract import file_ref, read_bound_json, text_digest
from native_line_spacing import glyphs, identity
from glyph_ink_geometry import EmbeddedGlyphInk
from translation_coverage import normalized

PROTOCOL = 'source_glyph_tex_canonical_accent_identity_v1'
SPACING_MARKS = {0x00b4: '\u0301', 0x0060: '\u0300', 0x02c6: '\u0302', 0x00a8: '\u0308', 0x02dc: '\u0303'}
TEX_MARKS = {"'": '\u0301', '`': '\u0300', '^': '\u0302', '"': '\u0308', '~': '\u0303'}


def canonical_protected_binding(binding, rows, *, review_ref, source_ref, target_ref,
                                standard_ref, reviewer_id, role_review_verified):
    """只处理真实保护bibliography；不重写原文，不接受目标词串别名。"""
    try:
        review = read_bound_json(review_ref)
        if (not role_review_verified or review.get('protocol') != PROTOCOL or
                review.get('source') != source_ref or review.get('target') != target_ref or
                review.get('standard') != standard_ref or review.get('reviewer_id') != reviewer_id):
            raise ValueError('canonical_source_independent_role_or_identity_changed')
        decisions = [r for r in review.get('bindings', []) if r.get('id') == binding['id']]
        if len(decisions) != 1:
            raise ValueError('canonical_source_binding_missing_or_duplicate')
        decision = decisions[0]
        own = [r for r in rows if r['id'] in binding['source_line_ids']]
        if (not own or len(own) != len(binding['source_line_ids']) or
                any(r.get('role') != 'bibliographic_record' or r.get('status') != 'protected' for r in own) or
                decision.get('source_line_ids') != binding['source_line_ids'] or
                decision.get('decision') != 'accepted' or not decision.get('rationale')):
            raise ValueError('canonical_complete_protected_source_role_required')
        by_id = {r['id']: r for r in own}
        events = decision['events']
        if not events or len(events) > 128 or len({(e['line_id'], e['source_offset']) for e in events}) != len(events):
            raise ValueError('canonical_accent_event_scope')
        bbl_ref = decision['source_tex_record_ref']
        path = bbl_ref['path']
        if file_ref(path) != bbl_ref or not str(path).endswith('.bbl'):
            raise ValueError('canonical_original_tex_bibliography_identity_changed')
        if Path(path).stat().st_size > 4*1024**2:
            raise ValueError('canonical_tex_source_budget')
        data = Path(path).read_bytes()
        if len(data) > 4*1024**2:
            raise ValueError('canonical_tex_source_budget')
        text = data.decode('utf-8')
        records = list(re.finditer(r'\\bibitem\{([^{}]+)\}', text))
        found = [n for n, match in enumerate(records) if match.group(1) == decision['source_tex_record_id']]
        if len(found) != 1:
            raise ValueError('canonical_unique_tex_bibliographic_record_required')
        n = found[0]; record = text[records[n].start():records[n+1].start() if n+1 < len(records) else len(text)]
        if hashlib.sha256(record.encode()).hexdigest() != decision['source_tex_record_sha256']:
            raise ValueError('canonical_complete_tex_record_changed')
        macro_chars = []
        for match in re.finditer(r'''\\(['`^"~])(?:\{([A-Za-z])\}|([A-Za-z]))''', record):
            macro_chars.append(unicodedata.normalize('NFC', (match.group(2) or match.group(3))+TEX_MARKS[match.group(1)]))
        replacements = {}; composed = []
        with fitz.open(source_ref['path']) as doc:
            if len(doc) > 5:
                raise ValueError('canonical_source_page_budget')
            current_page = None; native = None; engine = None
            for event in events:
                row = by_id[event['line_id']]; offset = event['source_offset']
                if type(offset) is not int or not 0 <= offset < len(row['source_text'])-1:
                    raise ValueError('canonical_source_offset')
                accent = event['accent_glyph']; base = event['base_glyph']
                mark = SPACING_MARKS.get(accent['unicode'])
                if (mark is None or row['source_text'][offset:offset+2] != chr(accent['unicode'])+chr(base['unicode']) or
                        not chr(base['unicode']).isascii() or not chr(base['unicode']).isalpha()):
                    raise ValueError('canonical_spacing_accent_and_base_not_original_text')
                if current_page != row['page']:
                    page = doc[row['page']-1]; native = glyphs(page)
                    if len(native) > 50000:
                        raise ValueError('canonical_source_glyph_budget')
                    engine = EmbeddedGlyphInk(doc, page,
                        required_font_xrefs={r[0] for r in page.get_fonts(full=True) if r[-1] == 0})
                    current_page = row['page']
                matches = [i for i, g in enumerate(native) if g == accent]
                if len(matches) != 1 or matches[0]+1 >= len(native) or native[matches[0]+1] != base:
                    raise ValueError('canonical_actual_accent_base_glyph_sequence_changed')
                box = fitz.Rect(row['bbox'])
                if any(not box.contains(fitz.Point(g['origin'])) or g['type'] == 3 or g.get('opacity',1) <= 0 for g in (accent,base)):
                    raise ValueError('canonical_actual_source_role_geometry_changed')
                # Unicode偏移也须对应该源行中同码点的实际出现次数，不能重用另一重音。
                in_line = [g for g in native[:matches[0]] if box.contains(fitz.Point(g['origin'])) and g['unicode'] == accent['unicode']]
                if len(in_line) != row['source_text'][:offset].count(chr(accent['unicode'])):
                    raise ValueError('canonical_source_text_glyph_occurrence_changed')
                if (accent['font'] != base['font'] or abs(accent['size']-base['size']) > .001 or
                        accent['color'] != base['color'] or accent['direction'] != [1.,0.] or base['direction'] != [1.,0.] or
                        abs(accent['origin'][0]-base['origin'][0]) > .12*base['size'] or
                        abs(accent['origin'][1]-base['origin'][1]) > .12*base['size']):
                    raise ValueError('canonical_accent_base_not_same_source_typographic_host')
                ai = engine.describe(accent); bi = engine.describe(base)
                # 当前原font/GID墨迹须为同一字母上的上重音，不按词形猜测。
                if ai != event['accent_ink'] or bi != event['base_ink']:
                    # JSON数组与运行时tuple采用相同规范后比较。
                    import json
                    if json.dumps([ai,bi],sort_keys=True) != json.dumps([event['accent_ink'],event['base_ink']],sort_keys=True):
                        raise ValueError('canonical_original_font_or_ink_evidence_changed')
                ab = ai.get('ink_bounds'); bb = bi.get('ink_bounds')
                if (not ab or not bb or not ai.get('font_file_identity_unique') or not bi.get('font_file_identity_unique') or
                        ab[1] >= bb[1] or ab[3] > bb[3]-.15*base['size'] or
                        min(ab[2],bb[2]) <= max(ab[0],bb[0])):
                    raise ValueError('canonical_accent_ink_not_overlapping_original_base')
                value = unicodedata.normalize('NFC', chr(base['unicode'])+mark)
                if len(value) != 1 or value != event['canonical_character']:
                    raise ValueError('canonical_unicode_composition_not_derived_from_source')
                replacements[(row['id'], offset)] = value; composed.append(value)
        if composed != macro_chars:
            raise ValueError('canonical_actual_source_accents_do_not_match_complete_tex_record')
        outputs = []
        for key in binding['source_line_ids']:
            literal = by_id[key]['source_text']; chars = []; index = 0
            while index < len(literal):
                if (key,index) in replacements:
                    chars.append(replacements[(key,index)]); index += 2
                else:
                    chars.append(literal[index]); index += 1
            outputs.append(''.join(chars))
        canonical = ' '.join(outputs)
        if normalized(canonical) != normalized(binding['target_text']):
            raise ValueError('canonical_complete_identity_differs_beyond_source_accent')
        if file_ref(source_ref['path']) != source_ref or file_ref(target_ref['path']) != target_ref or file_ref(bbl_ref['path']) != bbl_ref:
            raise ValueError('canonical_artifacts_changed_during_audit')
        return {'status':'pass','source_canonical_text_sha256':text_digest(canonical),'event_count':len(events),'quality_pass':False}
    except (ValueError,OSError,KeyError,TypeError,RuntimeError,IndexError,UnicodeError) as error:
        return {'status':'unverified','reason':str(error),'quality_pass':False}
