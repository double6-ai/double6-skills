"""同一完整图注只试排一次，再按完整行平衡写入原生并排两栏。"""
from copy import deepcopy
import math

from caption_structure_geometry import caption_band
from semantic_paragraph_flow import plan_line_flow


def caption_columns(fragments, *, column_width, right_edge, lower_rule, clearance=2.):
    """只接受经核定的同页双栏；保留源左右起点和下方原生分隔线。"""
    band = caption_band(fragments, right_edge=right_edge, lower_rule=lower_rule,
                        clearance=clearance)
    if len(fragments) != 2 or band['source_layout'] != 'parallel_columns':
        raise ValueError('caption_two_source_columns_required')
    if not math.isfinite(column_width) or column_width <= 0:
        raise ValueError('caption_column_width_invalid')
    if fragments[0]['bbox'][0] + column_width > fragments[1]['bbox'][0] - clearance:
        raise ValueError('caption_column_gutter_exhausted')
    if fragments[1]['bbox'][0] + column_width > right_edge + .002:
        raise ValueError('caption_column_right_edge_exceeded')
    return [{**band, 'column': i, 'id': f['id'], 'source_fragment_id': f['id'],
             'bbox': [f['bbox'][0], f['bbox'][1] - 2,
                      f['bbox'][0] + column_width, band['bbox'][3]],
             'first_baseline': f['source_baseline'],
             'target_layout': 'balanced_parallel_columns'}
            for i, f in enumerate(fragments)]


def verify_caption_columns(frames, placements, *, number_of_lines=None, tolerance=.002):
    if len(frames) != 2 or len(placements) != 2:
        raise ValueError('caption_two_target_columns_required')
    cursor = 0
    for f, p in zip(frames, placements):
        if (p['source_page'], p['column'], p['source_fragment_id']) != (
                f['source_page'], f['column'], f['source_fragment_id']):
            raise ValueError('caption_column_identity_changed')
        if p.get('fit_scale') != 1:
            raise ValueError('caption_column_scale_changed')
        if any(abs(p['destination'][j] - f['bbox'][j]) > tolerance for j in (0, 2)):
            raise ValueError('caption_column_span_changed')
        if p['destination'][1] < f['bbox'][1] - tolerance or p['destination'][3] > f['bbox'][3] + tolerance:
            raise ValueError('caption_column_overflow')
        start, end = p['line_range']
        if start != cursor or end <= start:
            raise ValueError('caption_column_line_gap_or_duplicate')
        cursor = end
    if number_of_lines is not None and cursor != number_of_lines:
        raise ValueError('caption_column_missing_lines')
    return True


def plan_caption_columns(glyphs, frames, *, width, font_size, lineheight,
                         maximum_script_offset_em=.5):
    """选择最接近平分的可容纳断行；不按源列拆译，不改字号或间距。"""
    if len(frames) != 2:
        raise ValueError('caption_two_frames_required')
    ys = sorted({round(c['origin'][1], 4) for c in glyphs
                 if abs(c['size'] - font_size) < .001})
    if len(ys) < 2:
        raise ValueError('caption_too_few_lines_for_two_columns')
    lines = [[] for _ in ys]
    for c in glyphs:
        index = min(range(len(ys)), key=lambda i: abs(c['origin'][1] - ys[i]))
        lines[index].append(c)
    attempts = []
    for cut in sorted(range(1, len(ys)), key=lambda k: (abs(2 * k - len(ys)), -k)):
        trial = deepcopy(frames)
        dy = trial[0]['first_baseline'] - ys[0]
        trial[0]['bbox'][3] = min(trial[0]['bbox'][3],
                                  max(c['bbox'][3] for c in lines[cut - 1]) + dy + .004)
        try:
            placements = plan_line_flow(
                glyphs, trial, width=width, font_size=font_size, lineheight=lineheight,
                minimum_fragment_lines=1, maximum_script_offset_em=maximum_script_offset_em)
            if len(placements) != 2 or placements[0]['line_range'] != [0, cut]:
                raise ValueError('caption_requested_balance_not_applied')
            for f, p in zip(frames, placements):
                p['planning_bottom_y'] = p['bbox'][3]
                p['bbox'] = list(f['bbox'])
                p['balance_line_counts'] = [cut, len(ys) - cut]
                p['declared_baseline_drift_pt'] = 0.
                # 行中心之间的裁片可带较宽空白，尤其续栏首行含上标时。
                # 只收紧到完整字形度量框外的白边，逆平移保持所有字形原点。
                dy = p['destination'][1] - p['bank_clip'][1]
                top = max(p['bank_clip'][1], min(c['bbox'][1] for c in p['glyphs']) - .25)
                bottom = min(p['bank_clip'][3], max(c['bbox'][3] for c in p['glyphs']) + .25)
                p['bank_clip'][1], p['bank_clip'][3] = top, bottom
                p['destination'][1], p['destination'][3] = top + dy, bottom + dy
            verify_caption_columns(frames, placements, number_of_lines=len(ys))
            return placements
        except ValueError as error:
            attempts.append({'left_lines': cut, 'error': str(error)})
    raise ValueError('caption_two_column_capacity_exhausted:' + repr(attempts))
