"""单栏原生章节结构：按标题与实际首行缩进恢复完整段落，跨页保留来源。"""
from __future__ import annotations
import html
import re
import statistics
from pathlib import Path

import fitz

from adaptive_document_renderer import sha
from source_formatting import infer_paragraph_geometry, normalized_text
from text_projection_protocol import encode


def atom_source_html(value, lines):
    for line in lines:
        spans = line['spans']
        text = ''.join(s['text'] for s in spans)
        start = text.find(value)
        if start < 0:
            continue
        result = []
        offset = 0
        for span in spans:
            end = offset+len(span['text'])
            a, b = max(start, offset), min(start+len(value), end)
            if b > a:
                fragment = html.escape(span['text'][a-offset:b-offset])
                if span['size'] < line['font_size']*.85:
                    shift = span['origin'][1]-line['baseline']
                    tag = 'sub' if shift > .35 else 'sup' if shift < -.35 or span['flags'] & 1 else None
                    if tag:
                        fragment = f'<{tag} style="font-size:{span["size"]/line["font_size"]*100:.3f}%">{fragment}</{tag}>'
                result.append(fragment)
            offset = end
        return ''.join(result)
    return html.escape(value)


def prepare_chapter(path, start_heading, end_heading, *, maximum_pages=5, search_pages=40):
    path = Path(path).resolve()
    if path.stat().st_size > 128*1024**2 or not 1 <= maximum_pages <= 5:
        raise ValueError('input_bounds')
    rows = []
    selected_pages = []
    active = False
    ended = False
    with fitz.open(path) as document:
        for index in range(min(len(document), search_pages)):
            page = document[index]
            lines = []
            for block in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
                for line in block.get('lines', []):
                    spans = [s for s in line['spans'] if s['text'].strip()]
                    if not spans:
                        continue
                    box = fitz.Rect(spans[0]['bbox'])
                    for s in spans[1:]:
                        box |= s['bbox']
                    size = max(s['size'] for s in spans)
                    base = statistics.median(s['origin'][1] for s in spans if s['size'] >= size*.85)
                    lines.append({'text': ''.join(s['text'] for s in line['spans']).strip(),
                                  'bbox': list(box), 'baseline': base, 'font_size': size,
                                  'spans': spans, 'page': index+1})
            lines.sort(key=lambda v: (v['baseline'], v['bbox'][0]))
            for line in lines:
                key = normalized_text(line['text'])
                is_heading = any(s['flags'] & 16 for s in line['spans'])
                if key == normalized_text(start_heading) and is_heading:
                    if active:
                        raise ValueError('duplicate_start_heading')
                    active = True
                    start = line
                    page_size = [page.rect.width, page.rect.height]
                    start_index = index
                    continue
                if active and key == normalized_text(end_heading) and is_heading:
                    ended = True
                    ending = line
                    break
                if not active:
                    continue
                # 页码、孤立符号不参与正文；来源全文页仍另存供核验。
                if re.fullmatch(r'[-–]?\s*\d+\s*[-–]?', line['text']):
                    continue
                if line['bbox'][1] < page.rect.height*.05 or line['bbox'][3] > page.rect.height*.91:
                    raise ValueError('unexpected_header_or_footer_in_chapter')
                if is_heading:
                    raise ValueError('unhandled_internal_heading')
                if line['page'] not in selected_pages:
                    selected_pages.append(line['page'])
                if len(selected_pages) > maximum_pages:
                    raise ValueError('chapter_page_limit')
                rows.append(line)
            if ended:
                break
    if not ended or not rows:
        raise ValueError('chapter_boundary_missing')
    with fitz.open(path) as document:
        for source_page in selected_pages:
            p = document[source_page-1]
            same = [v for v in rows if v['page'] == source_page]
            scope = fitz.Rect(0, min(v['bbox'][1] for v in same), p.rect.width,
                              max(v['bbox'][3] for v in same))
            if any(fitz.Rect(image['bbox']).intersects(scope) for image in p.get_image_info()):
                raise ValueError('chapter_image_requires_structural_adapter')
            if any(fitz.Rect(drawing['rect']).intersects(scope) for drawing in p.get_drawings()):
                raise ValueError('chapter_drawing_requires_structural_adapter')
    body_size = statistics.median(v['font_size'] for v in rows)
    left = min(v['bbox'][0] for v in rows)
    right = max(v['bbox'][2] for v in rows)
    # 同一基线有两个远离的正文行意味着多栏，拒绝按单栏排序。
    for a, b in zip(rows, rows[1:]):
        if a['page'] == b['page'] and abs(a['baseline']-b['baseline']) < body_size*.4:
            raise ValueError('multicolumn_or_fragmented_line_requires_adapter')
    if not any(v['bbox'][0]-left > body_size*.5 for v in rows[1:]):
        raise ValueError('paragraph_boundary_evidence_missing')
    groups = []
    for line in rows:
        if not groups or line['bbox'][0]-left > body_size*.5:
            groups.append([])
        groups[-1].append(line)
    units = []
    paragraph_gaps = []
    for previous, following in zip(groups, groups[1:]):
        if previous[-1]['page'] == following[0]['page'] and len(previous) > 1:
            steps = [b['baseline']-a['baseline'] for a,b in zip(previous, previous[1:])
                     if a['page'] == b['page'] and b['baseline'] > a['baseline']]
            if steps:
                paragraph_gaps.append(max(0., following[0]['baseline']-previous[-1]['baseline']-statistics.median(steps)))
    atom = re.compile(r'\[\d+(?:\s*[,–-]\s*\d+)*\]|\b[A-Z][a-z]+ et al\.|\b(?:[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+)(?:/[A-Z][a-z]?)?\b|\bLi(?:\+|-In)(?=\W|$)')
    for i, lines in enumerate(groups):
        text = ''
        joins = []
        for line in lines:
            value = line['text']
            if text.endswith('-') and value[:1].islower():
                text = text[:-1]+value
                joins.append({'type': 'printed_line_hyphen', 'page': line['page']})
            else:
                text += (' ' if text else '')+value
        spans = []
        at = 0
        for match in atom.finditer(text):
            if match.start() > at:
                spans.append({'type': 'text', 'content': text[at:match.start()]})
            value = match.group()
            # 化学式和引用原样保护；只对实际源span已为上标的引用继承样式。
            spans.append({'type': 'equation_inline', 'content': value,
                          'source_html': atom_source_html(value, lines)})
            at = match.end()
        if at < len(text):
            spans.append({'type': 'text', 'content': text[at:]})
        origins = []
        for page in dict.fromkeys(v['page'] for v in lines):
            same = [v for v in lines if v['page'] == page]
            box = fitz.Rect(same[0]['bbox'])
            for line in same[1:]:
                box |= line['bbox']
            origins.append({'source_page': page, 'source_bbox': list(box),
                            'printed_lines': len(same)})
        first_page_lines = [v for v in lines if v['page'] == lines[0]['page']]
        geometry = infer_paragraph_geometry(first_page_lines, frame=[left, 0, right, 0], font_size=body_size)
        geometry['cross_page_baselines_excluded'] = len(lines) != len(first_page_lines)
        units.append({'id': f'paragraph-{i+1:03d}', 'source': text,
                      'source_origins': origins, 'source_geometry': geometry,
                      'binding': encode(spans), 'printed_line_operations': joins})
    return {'schema_version': 1, 'status': 'chapter_candidate_structure',
            'source': {'path': str(path), 'sha256': sha(path)},
            'selected_pages': selected_pages, 'start_heading': start, 'end_heading': ending,
            'scope': '连续完整章节；源页中章节以外内容不在翻译范围',
            'units': units, 'body_font_size': body_size,
            'source_paragraph_gap_pt': round(statistics.median(paragraph_gaps), 4) if paragraph_gaps else None,
            'source_frame': [left, start['bbox'][3]+body_size*.5, right, page_size[1]*.89],
            'page_size': page_size,
            'columns': 1, 'automatic_target_coordinates': True}
