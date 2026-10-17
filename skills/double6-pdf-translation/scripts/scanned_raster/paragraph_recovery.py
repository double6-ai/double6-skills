"""将同页同栏的 MinerU 单行正文归并为有界段落，保留原区域身份和遮罩依据。"""
from __future__ import annotations

import copy
import re
import statistics


def coalesce_mineru_text_lines(regions: list[dict], *, max_lines: int = 16, max_chars: int = 1800) -> list[dict]:
    if not 2 <= max_lines <= 32 or not 100 <= max_chars <= 4000:
        raise ValueError("bounded paragraph limits required")
    ordered = sorted(copy.deepcopy(regions), key=lambda r: (r.get('page', 0), r.get('reading_order', 0)))
    heights = [r.get('source_line_height') or r['bbox'][3] - r['bbox'][1] for r in ordered if r.get('engine') == 'mineru' and r.get('layout_role') == 'text' and len(r.get('bbox', [])) == 4]
    if not heights:
        return ordered
    line_height = statistics.median(heights)
    protected = [r for r in ordered if r.get('layout_role') != 'text' and len(r.get('bbox', [])) == 4]
    def eligible(row):
        box = row.get('bbox', [])
        return (row.get('engine') == 'mineru' and row.get('layout_role') == 'text' and len(box) == 4
                and not row.get('structured_name_column')
                and not row.get('frontmatter_alignment_policy')
                and not row.get('name_column_ambiguity')
                and 0 < box[3] - box[1] <= line_height * 1.6
                and box[3] - box[1] <= (row.get('preprocess', {}).get('page_height') or 1000) * .035
                and box[2] - box[0] > line_height * 5)
    def union(rows):
        return [min(r['bbox'][0] for r in rows), min(r['bbox'][1] for r in rows),
                max(r['bbox'][2] for r in rows), max(r['bbox'][3] for r in rows)]
    def allowed(group, row):
        prev = group[-1]
        if not eligible(prev) or not eligible(row) or row.get('page') != prev.get('page') or row.get('source_pdf_sha256') != prev.get('source_pdf_sha256') or len(group) >= max_lines:
            return False
        if sum(len(r.get('ocr_text', '')) for r in [*group, row]) > max_chars:
            return False
        a, b = prev['bbox'], row['bbox']
        # 不穿过并排栏、反向阅读序、明显段间空白或另起的缩进段。
        gap = b[1] - a[3]
        terminal = bool(re.search(r'[.!?。！？][\)\]”\"\s]*$', prev.get('ocr_text', '')))
        if gap < 0 or gap > line_height * 1.65 or abs(b[0] - a[0]) > line_height * 2:
            return False
        if terminal and (b[0] - a[0] > line_height * .6 or a[2] - a[0] < (b[2] - b[0]) * .8):
            return False
        box = union([*group, row])
        return not any(p.get('page') == row.get('page') and min(box[2], p['bbox'][2]) > max(box[0], p['bbox'][0]) and min(box[3], p['bbox'][3]) > max(box[1], p['bbox'][1]) for p in protected)
    groups = []
    for row in ordered:
        if groups and allowed(groups[-1], row):
            groups[-1].append(row)
        else:
            groups.append([row])
    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue
        merged = dict(group[0]); box = union(group)
        rid = group[0]['region_id'] + '-paragraph'
        text = ' '.join(r.get('ocr_text', '').strip() for r in group)
        source_regions = [{k: r.get(k) for k in ['region_id', 'bbox', 'polygon', 'ocr_text', 'confidence']} for r in group]
        lines = [line for r, original in zip(group, source_regions, strict=True) for line in (r.get('source_line_evidence') or [original])]
        merged.update(region_id=rid, bbox=box, polygon=[[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
                      ocr_text=text, normalized_text=' '.join(text.split()), translation_group_id=rid,
                      render_unit='paragraph_band', paragraph_source_text=text, paragraph_band_index=0, paragraph_band_count=1,
                      source_regions=source_regions, source_region_ids=[r['region_id'] for r in group],
                      source_line_evidence=lines, source_line_count=len(lines), source_line_height=line_height,
                      grouping_policy='mineru_same_page_column_lines_v1', status='pending', translation=None, in_destroke_mask=False)
        # 输入可能来自旧候选；旧文字和渲染几何不能冒充新段落的产物。
        for key in ['render_bbox', 'original_layout_bbox', 'source_geometry_expansion', 'source_bbox', 'mask_geometry', 'destroke_boxes', 'translation_raw', 'font_size', 'writeback_status', 'overflow', 'occluded', 'overlap']:
            merged.pop(key, None)
        merged['mask_geometry'] = {'type': 'polygon', 'points': merged['polygon']}
        result.append(merged)
    for order, row in enumerate(result):
        row['reading_order'] = order
    return result
