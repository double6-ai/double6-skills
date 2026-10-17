"""按具名源页证据合并被OCR/样式切开的同段；不自动猜测段落边界。"""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import fitz

def merge_verified_fragments(plan: dict, fragment_ids: list[str], evidence: dict) -> dict:
    """仅同页、同类、同字体片段；保留来源/译文身份，不翻译、不授予语义通过。"""
    path = Path(evidence.get('path', ''))
    if evidence.get('decision') != 'same_source_paragraph' or not path.is_file():
        raise ValueError('verified_paragraph_evidence_required')
    with path.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != evidence.get('sha256'):
            raise ValueError('verified_paragraph_evidence_changed')
    if len(fragment_ids) < 2 or len(set(fragment_ids)) != len(fragment_ids):
        raise ValueError('distinct_fragment_ids_required')
    regions = plan['regions']
    byid = {r['id']: r for r in regions}
    if len(byid) != len(regions): raise ValueError('duplicate_region_ids')
    parts = [byid[i] for i in fragment_ids]
    if len({r['page'] for r in parts}) != 1: raise ValueError('cross_page_requires_flow_plan')
    if [r['source_rect'][1] for r in parts] != sorted(r['source_rect'][1] for r in parts):
        raise ValueError('source_reading_order_required')
    for key in ['role', 'typography_class', 'source_bold', 'source_italic']:
        if len({r.get(key) for r in parts}) != 1: raise ValueError('mixed_paragraph_style:' + key)
    alignment = evidence.get('paragraph_alignment')
    if alignment is not None and alignment not in {'left','right','center','justify'}:
        raise ValueError('invalid_verified_paragraph_alignment')
    if len({r.get('alignment') for r in parts}) != 1 and alignment is None:
        raise ValueError('mixed_paragraph_style:alignment')
    if parts[0]['role'] != 'plain text': raise ValueError('only_body_paragraph_fragments')
    merged = copy.deepcopy(parts[0])
    if alignment is not None: merged['alignment'] = alignment
    box = fitz.Rect(parts[0]['source_rect'])
    for r in parts[1:]: box |= fitz.Rect(r['source_rect'])
    for protected in plan.get('protected_regions', []):
        if protected['page'] == parts[0]['page'] and box.intersects(fitz.Rect(protected['bbox'])):
            raise ValueError('protected_region_requires_structure_adapter')
    merged.update(id='+'.join(fragment_ids), source_rect=list(box), source_original_bbox=list(box),
        source=' '.join(r['source'].strip() for r in parts),
        translation=''.join(r['translation'] for r in parts),
        previous_translation=''.join(r.get('previous_translation') or r['translation'] for r in parts),
        verified_paragraph_evidence=copy.deepcopy(evidence),
        source_fragment_provenance=[{'id':r['id'],'page':r['page'],'bbox':r['source_rect'],
            'source':r['source'],'translation':r['translation']} for r in parts],
        semantic_review='pending_current_complete_paragraph_review')
    for key in ['source_text_sha256', 'translation_sha256']:
        merged[key] = hashlib.sha256(merged['source' if key.startswith('source') else 'translation'].encode()).hexdigest()
    for key in ['color_anchors','formulas','source_math_subscripts','link_anchor_styles','superscript_anchors','italic_literals']:
        if any(r.get(key) for r in parts):
            raise ValueError('styled_span_merge_requires_explicit_adapter:' + key)
    if merged.get('source_formatting', {}).get('geometry'):
        geometry = merged['source_formatting']['geometry']
        geometry['source_lines'] = [line for r in parts for line in r.get('source_formatting',{}).get('geometry',{}).get('source_lines',[])]
        geometry['fragment_merge_requires_same_printed_line_review'] = True
    result = copy.deepcopy(plan)
    result['regions'] = [merged if r['id'] == fragment_ids[0] else copy.deepcopy(r)
                         for r in regions if r['id'] == fragment_ids[0] or r['id'] not in fragment_ids]
    result.setdefault('verified_fragment_merges', []).append({'ids':fragment_ids,'merged_id':merged['id'],'evidence':evidence})
    result['human_acceptance'] = False; result['strict_delivery'] = False
    return result
