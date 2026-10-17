"""将已核定的译文链接标签绑定到实际字形，生成逐行装饰和点击范围。"""
from __future__ import annotations

import unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace())


def bind_link_labels(glyphs, links, base_color):
    """glyphs 须按阅读顺序排列；标签必须唯一且不得重叠。"""
    text = ''.join(normalized(g['text']) for g in glyphs)
    offsets = []
    for i, glyph in enumerate(glyphs):
        offsets.extend([i] * len(normalized(glyph['text'])))
    result = [dict(g, color=list(base_color), link_index=None) for g in glyphs]
    occupied = set()
    for link_index, link in enumerate(links):
        label = normalized(link['label'])
        if not label or text.count(label) != 1:
            raise ValueError('translated_link_label_missing_or_ambiguous')
        start = text.index(label)
        indices = sorted(set(offsets[start:start + len(label)]))
        for i in indices:
            if i in occupied:
                raise ValueError('translated_link_labels_overlap')
            occupied.add(i)
            result[i].update(color=list(link['color']), link_index=link_index)
        suffix = link.get('suffix_style')
        if suffix:
            tail = normalized(suffix['text'])
            if not tail or not label.endswith(tail):
                raise ValueError('translated_link_suffix_not_verified')
            for i in set(offsets[start + len(label) - len(tail):start + len(label)]):
                result[i]['color'] = list(suffix['color'])
        excluded = link.get('suffix_decoration_excluded')
        if excluded:
            tail = normalized(excluded)
            if not tail or not label.endswith(tail):
                raise ValueError('translated_link_decoration_suffix_not_verified')
            for i in set(offsets[start + len(label) - len(tail):start + len(label)]):
                result[i]['link_index'] = None
    return result


def project_link_rows(glyphs, links, baseline_tolerance=.1):
    """点击区覆盖标签字形；下划线继承源偏移/线宽，并按实际行及颜色分段。"""
    rows = []
    for li, link in enumerate(links):
        selected = [g for g in glyphs if g['link_index'] == li]
        if not selected:
            raise ValueError('translated_link_has_no_glyphs')
        groups = []
        for g in selected:
            baseline = g['origin'][1]
            if not groups or abs(groups[-1][0]['origin'][1] - baseline) > baseline_tolerance:
                groups.append([])
            groups[-1].append(g)
        for group in groups:
            rect = [min(g['bbox'][0] for g in group), min(g['bbox'][1] for g in group),
                    max(g['bbox'][2] for g in group), max(g['bbox'][3] for g in group)]
            segments = []
            for g in group:
                if not segments or segments[-1]['color'] != g['color']:
                    segments.append({'x0': g['bbox'][0], 'x1': g['bbox'][2], 'color': g['color']})
                else:
                    segments[-1]['x1'] = g['bbox'][2]
            rows.append({'link_index': li, 'uri': link['uri'], 'rect': rect,
                         'baseline': group[0]['origin'][1],
                         'underline_y': group[0]['origin'][1] + link['underline_offset_pt'],
                         'underline_width': link['underline_width_pt'], 'segments': segments})
    return rows
