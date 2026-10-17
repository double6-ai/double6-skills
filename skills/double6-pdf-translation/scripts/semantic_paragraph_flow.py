"""已核定的完整语义段只试排一次，按实际印刷行连续进入有序栏框。"""
from __future__ import annotations

import math


def canonical_paragraph(fragments, target_text):
    """源片段仅保留来源身份；译文没有源框强制分隔符。"""
    if not fragments or len(fragments) > 20 or not target_text.strip():
        raise ValueError('logical_paragraph_bounds')
    if '{break' in target_text:
        raise ValueError('forced_source_fragment_break')
    ids = [v['id'] for v in fragments]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_source_fragment')
    logical = {v['logical_paragraph_id'] for v in fragments}
    if len(logical) != 1 or any(not v.get('boundary_evidence') for v in fragments):
        raise ValueError('verified_logical_boundary_required')
    pages = [v['source_page'] for v in fragments]
    if any(b < a or b - a > 1 for a, b in zip(pages, pages[1:])):
        raise ValueError('source_page_gap_or_order')
    return {'id': next(iter(logical)), 'source_text': ' '.join(v['source_text'] for v in fragments),
            'target_text': target_text, 'source_fragments': ids,
            'source_origins': [{'source_page': v['source_page'], 'id': v['id'],
                                'bbox': v['bbox']} for v in fragments]}


def plan_line_flow(glyphs, frames, *, width, font_size, lineheight,
                   minimum_fragment_lines=2,maximum_script_offset_em=.5):
    """按框的可用高度选行，栏尾仍属于同一段；仅全段末行自然收尾。"""
    if not glyphs or not frames or len(frames) > 20:
        raise ValueError('flow_bounds')
    if minimum_fragment_lines not in (1, 2):
        raise ValueError('flow_minimum_lines')
    if not .1<=maximum_script_offset_em<=.8:
        raise ValueError('flow_script_offset_bound')
    if not all(math.isfinite(v) and v > 0 for v in (width, font_size, lineheight)):
        raise ValueError('flow_nonfinite_metrics')
    for a, b in zip(frames, frames[1:]):
        previous, current = (a['source_page'], a['column']), (b['source_page'], b['column'])
        if current < previous:
            raise ValueError('flow_frame_reading_order')
        if current == previous:
            # 绕图上下框保留真实栏号，只接受向下、同宽且不相交的显式框。
            if (b['first_baseline'] <= a['first_baseline'] or
                    b['bbox'][1] < a['bbox'][3] or
                    abs(b['bbox'][0] - a['bbox'][0]) > .002 or
                    abs(b['bbox'][2] - a['bbox'][2]) > .002):
                raise ValueError('flow_frame_reading_order')
    # PDF序列化可使同一宿主行的字形坐标相差千分之几点。
    # 每簇完整跨度限制为.003pt，避免链式聚类合并真实偏移。
    host_y = sorted(c['origin'][1] for c in glyphs
                    if abs(c['size'] - font_size) < .001)
    clusters = []
    for y in host_y:
        if not clusters or y - clusters[-1][0] > .003:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    ys = [sum(values) / len(values) for values in clusters]
    if not ys:
        raise ValueError('flow_host_baseline_missing')
    step = font_size * lineheight
    if any(abs(b - a - step) > .03 for a, b in zip(ys, ys[1:])):
        raise ValueError('flow_nonuniform_baseline')
    lines = [[] for _ in ys]
    for c in glyphs:
        n = min(range(len(ys)), key=lambda i: abs(c['origin'][1] - ys[i]))
        if abs(c['origin'][1] - ys[n]) > font_size * maximum_script_offset_em:
            raise ValueError('flow_inline_style_binding')
        lines[n].append(c)
    # 字形中心用于无隐藏文字的裁片；全部上下标随宿主印刷行移动。
    centers = [[(c['bbox'][1] + c['bbox'][3]) / 2 for c in line] for line in lines]
    boundaries = [min(c['bbox'][1] for c in lines[0]) - .25]
    for a, b in zip(centers, centers[1:]):
        if max(a) >= min(b):
            raise ValueError('flow_line_center_overlap')
        boundaries.append((max(a) + min(b)) / 2)
    boundaries.append(max(c['bbox'][3] for c in lines[-1]) + .25)
    placements = []
    start = 0
    for frame in frames:
        x0, y0, x1, y1 = frame['bbox']
        baseline = frame['first_baseline']
        if not all(math.isfinite(v) for v in (*frame['bbox'], baseline)) or x1 <= x0 or y1 <= y0:
            raise ValueError('flow_invalid_frame')
        if width > x1 - x0 + .002:
            raise ValueError('flow_width_exceeds_frame')
        end = start
        while end < len(lines):
            dy = baseline - ys[start]
            if min(c['bbox'][1] + dy for c in lines[end]) < y0 - .002:
                break
            if max(c['bbox'][3] + dy for c in lines[end]) > y1 + .002:
                break
            end += 1
        if end < len(lines) and end - start < minimum_fragment_lines:
            raise ValueError('flow_insufficient_first_frame')
        if len(lines) - end == 1 and end - start > 2 and minimum_fragment_lines == 2:
            end -= 1
        if end == start:
            raise ValueError('flow_empty_frame')
        dy = baseline - ys[start]
        placements.append({**frame, 'line_range': [start, end],
                           'bank_clip': [0, boundaries[start], width, boundaries[end]],
                           'destination': [x0, boundaries[start] + dy,
                                           x0 + width, boundaries[end] + dy],
                           'glyphs': [c for line in lines[start:end] for c in line],
                           'first_baseline_drift_pt': 0., 'fit_scale': 1.})
        start = end
        if start == len(lines):
            break
    if start != len(lines):
        raise ValueError('flow_declared_frames_exhausted')
    return placements
