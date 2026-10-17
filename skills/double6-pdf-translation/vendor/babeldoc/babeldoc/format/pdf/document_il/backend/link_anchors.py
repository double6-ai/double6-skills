# Double6 Skills 维护版本（2026-10-17）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""只重定位能由段落、独立文字颜色和原下划线共同证明的 URI 链接。"""
from __future__ import annotations

import pymupdf as fitz


def _color(value):
    return int(value) & 0xFFFFFF


def _chars(page):
    rows = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            if tuple(line.get('dir', (1, 0))) != (1, 0):
                continue
            for span in line['spans']:
                for c in span['chars']:
                    if c['c'].isspace():
                        continue
                    rect = fitz.Rect(c['bbox'])
                    rows.append({'text': c['c'], 'rect': rect, 'center': (rect.tl + rect.br) / 2,
                                 'color': _color(span['color']), 'baseline': c['origin'][1],
                                 'size': span['size']})
    return rows


def _near_color(rgb, colors):
    if not rgb or len(rgb) != 3:
        return False
    return any(all(abs(round(v * 255) - ((c >> shift) & 255)) <= 2
                   for v, shift in zip(rgb, (16, 8, 0))) for c in colors)


def capture(page, il_page):
    """在原页内容被替换前冻结候选；歧义范围只登记 deferred，不猜测 URL。"""
    links = [x for x in page.get_links() if x.get('kind') == fitz.LINK_URI and x.get('uri')]
    if not links:
        return [], []
    if page.rotation or page.cropbox.x0 or page.cropbox.y0:
        return [], [{'reason': 'rotated_or_offset_page', 'links': len(links)}]
    height = page.rect.height
    paragraphs = []
    for p in il_page.pdf_paragraph:
        b = p.box
        if b and not p.vertical:
            paragraphs.append((p, fitz.Rect(b.x, height-b.y2, b.x2, height-b.y)))
    assigned = {}
    deferred = []
    for link in links:
        rect = link['from']
        center = (rect.tl + rect.br) / 2
        hits = [i for i, (_, b) in enumerate(paragraphs) if (b + (-1, -1, 1, 1)).contains(center)]
        if len(hits) != 1:
            deferred.append({'reason': 'paragraph_ambiguous', 'uri': link['uri']})
            continue
        assigned.setdefault(hits[0], []).append(link)
    chars = _chars(page)
    drawings = page.get_drawings()
    plans = []
    for index, group in assigned.items():
        paragraph, rect = paragraphs[index]
        uris = {x['uri'] for x in group}
        if len(uris) != 1:
            deferred.append({'reason': 'multiple_uris_in_paragraph', 'uris': sorted(uris)})
            continue
        scope = rect + (-1, -2, 1, 2)
        source_chars = [c for c in chars if scope.contains(c['center'])]
        anchor = [c for c in source_chars if any(x['from'].contains(c['center']) for x in group)]
        others = [c for c in source_chars if not any(x['from'].contains(c['center']) for x in group)]
        colors = {c['color'] for c in anchor}
        # 原注释可排除紧邻句末标点，但它仍与链接共用颜色；只纳入同行贴邻标点。
        trailing = [c for c in others if c['color'] in colors and c['text'] in '.,;:!?。'
                    and any(abs(c['baseline']-a['baseline']) < .5
                            and -.25 <= c['rect'].x0-a['rect'].x1 <= .5 for a in anchor)]
        if trailing:
            anchor.extend(trailing)
            others = [c for c in others if c not in trailing]
        if not anchor or not others or colors & {c['color'] for c in others}:
            deferred.append({'reason': 'link_color_not_distinct', 'uri': group[0]['uri']})
            continue
        strokes = []
        # Only standalone, thin, horizontal strokes wholly inside the old link rectangles.
        for d in drawings:
            r = fitz.Rect(d['rect'])
            if (d['type'] != 's' or not 0 < d.get('width', 0) <= 1
                or len(d['items']) != 1 or d['items'][0][0] != 'l'
                or abs(r.y1-r.y0) > .02 or r.width <= 0
                or not _near_color(d.get('color'), colors)):
                continue
            if not any(x['from'].x0-.05 <= r.x0 and r.x1 <= x['from'].x1+.05
                       and x['from'].y0 <= r.y0 <= x['from'].y1 for x in group):
                continue
            matches = []
            for i, curve in enumerate(il_page.pdf_curve):
                path = curve.pdf_path
                b = curve.box
                if (not b or not curve.stroke_path or curve.fill_background or len(path) != 2
                    or [z.op for z in path] != ['m', 'l'] or abs(b.y2-b.y) > .02):
                    continue
                if max(abs(a-b) for a,b in zip((b.x,height-b.y2,b.x2,height-b.y),r)) < .05:
                    matches.append(i)
            if len(matches) == 1:
                strokes.append({'curve_index': matches[0], 'rect': list(r),
                                'width': d['width'], 'color': list(d['color'])})
        # Every old annotation must have an identified underline; partial replacement is forbidden.
        if not strokes or any(not any(x['from'].x0-.05 <= s['rect'][0] and s['rect'][2] <= x['from'].x1+.05
            and x['from'].y0 <= s['rect'][1] <= x['from'].y1 for s in strokes) for x in group):
            deferred.append({'reason': 'underline_not_uniquely_bound', 'uri': group[0]['uri']})
            continue
        plans.append({'uri': group[0]['uri'], 'links': group, 'scope': list(scope),
                      'colors': sorted(colors), 'source_text': ''.join(c['text'] for c in anchor),
                      'strokes': strokes, 'paragraph_id': paragraph.debug_id})
    return plans, deferred


def resolve(page, plans):
    """读取真实已渲染译文；一旦冻结的可修复链接失去样式映射即失败。"""
    chars = _chars(page)
    resolved = []
    for plan in plans:
        scope = fitz.Rect(plan['scope'])
        selected = [c for c in chars if scope.contains(c['center']) and c['color'] in plan['colors']]
        if not selected:
            raise ValueError('link anchor color missing after translation')
        lines = {}
        for c in selected:
            lines.setdefault(round(c['baseline'], 1), []).append(c)
        targets = []
        for baseline, row in sorted(lines.items()):
            row.sort(key=lambda c:c['rect'].x0)
            for a,b in zip(row,row[1:]):
                if b['rect'].x0-a['rect'].x1 > max(a['size'],b['size']):
                    raise ValueError('link anchor split by non-link content')
            rect = fitz.Rect(row[0]['rect'])
            for c in row[1:]:
                rect |= c['rect']
            # Any differently colored text between anchor glyphs makes the association ambiguous.
            if any(c['color'] not in plan['colors'] and rect.contains(c['center']) for c in chars):
                raise ValueError('link anchor overlaps unrelated text')
            targets.append({'rect':list(rect),'baseline':baseline,'text':''.join(c['text'] for c in row)})
        resolved.append({**plan,'targets':targets})
    return resolved


def apply(page, plans):
    """调用者已重新渲染并仅去掉绑定的旧曲线；此处重建 URL 和逐行下划线。"""
    reports = []
    for plan in plans:
        for link in plan['links']:
            page.delete_link(link)
        style = max(plan['strokes'], key=lambda s:s['rect'][2]-s['rect'][0])
        for target in plan['targets']:
            rect = fitz.Rect(target['rect'])
            page.insert_link({'kind':fitz.LINK_URI,'from':rect,'uri':plan['uri']})
            y = target['baseline'] + max(.7, style['width'])
            page.draw_line((rect.x0,y),(rect.x1,y),color=style['color'],width=style['width'],overlay=True)
        reports.append({'uri':plan['uri'],'paragraph_id':plan['paragraph_id'],'source_anchor':plan['source_text'],
                        'removed_underline_count':len(plan['strokes']),
                        'old_rects':[list(x['from']) for x in plan['links']], 'new_targets':plan['targets']})
    return reports
