"""源段落的几何和行内样式证据；推断值保留置信度，不替代原生样式声明。"""
from __future__ import annotations

import hashlib
import re
import statistics
import unicodedata
from pathlib import Path
from typing import Any


def normalized_text(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', value).lower() if c.isalnum())


def infer_paragraph_geometry(
    lines: list[dict[str, Any]], *, frame: list[float] | None = None,
    font_size: float | None = None, continuation: bool = False,
) -> dict[str, Any]:
    """从至少三条印刷行判断对齐；首行/末行分别处理，短行不冒称两端对齐。"""
    usable = sorted((dict(l) for l in lines if isinstance(l.get('bbox'), (list, tuple))
                     and len(l['bbox']) == 4 and l['bbox'][2] > l['bbox'][0]),
                    key=lambda l: (l['bbox'][1], l['bbox'][0]))
    if not usable:
        return {'alignment': 'unknown', 'confidence': 'low', 'reason': 'no_printed_lines',
                'line_count': 0, 'first_line_indent_pt': None, 'baseline_step_pt': None}
    sizes = [float(l['font_size']) for l in usable if l.get('font_size')]
    size = float(font_size or (statistics.median(sizes) if sizes else
                              statistics.median(l['bbox'][3]-l['bbox'][1] for l in usable)))
    native = all('baseline' in l for l in usable)
    # PDF字体的逻辑框会有光学悬挂及子像素舍入；小于0.22em的端点差
    # 不能直接解释为有意参差。OCR则允许1.5pt定位误差。
    tolerance = max(.75, size*.22) if native else max(1.5,size*.18)
    if native:
        merged=[]
        for l in usable:
            owner=next((m for m in reversed(merged) if abs(m['baseline']-l['baseline'])<=.35
                        and l['bbox'][0]-m['bbox'][2]<=size*4 and m['bbox'][0]-l['bbox'][2]<=size*4),None)
            if owner:
                owner['bbox']=[min(owner['bbox'][0],l['bbox'][0]),min(owner['bbox'][1],l['bbox'][1]),max(owner['bbox'][2],l['bbox'][2]),max(owner['bbox'][3],l['bbox'][3])]
                owner['text']=owner.get('text','')+' '+l.get('text','')
            else:merged.append(l)
        usable=merged
    boxes = [l['bbox'] for l in usable]
    left = [float(b[0]) for b in boxes];right = [float(b[2]) for b in boxes]
    centers = [(a+b)/2 for a,b in zip(left,right)]
    spread = lambda v: max(v)-min(v) if v else 0.
    # Continuations do not repeat a paragraph's first-line indent.
    indent = 0. if continuation else left[0]-(statistics.median(left[1:]) if len(left)>1 else (frame[0] if frame else left[0]))
    if abs(indent)<tolerance:indent=0.
    baseline_values = [float(l.get('baseline', (l['bbox'][1]+l['bbox'][3])/2)) for l in usable]
    steps = [b-a for a,b in zip(baseline_values,baseline_values[1:]) if b-a>size*.5]
    step = statistics.median(steps) if steps else None
    alignment='unknown';confidence='low';reason='short_or_ambiguous_paragraph'
    if len(usable)>=3:
        left_stable=spread(left[1:])<=tolerance
        right_nonfinal_stable=spread(right[:-1])<=tolerance
        if left_stable and right_nonfinal_stable and spread(right)>tolerance:
            alignment='justify';confidence='high';reason='stable_nonfinal_right_and_continuation_left_edges'
        elif spread(centers)<=tolerance and spread(left)>size and spread(right)>size:
            alignment='center';confidence='high';reason='stable_centers_and_variable_line_widths'
        elif not left_stable and spread(right)<=tolerance and spread(left)>size:
            alignment='right';confidence='high';reason='stable_all_right_edges_and_variable_left_edges'
        elif left_stable and spread(right[:-1])>tolerance:
            alignment='left';confidence='high';reason='stable_left_edges_and_ragged_nonfinal_right_edges'
        elif left_stable and right_nonfinal_stable:
            alignment='justify';confidence='medium';reason='all_lines_full_width_final_line_not_distinguishable'
    elif len(usable)==2 and frame and abs(right[0]-frame[2])<=tolerance and right[0]-right[1]>size*2:
        alignment='justify';confidence='medium';reason='full_first_line_short_final_line_only_two_lines'
    # 居中及右对齐的行首随行宽变化，不构成首行缩进或悬挂缩进。
    if alignment in {'center','right'}:indent=0.
    return {'alignment':alignment,'confidence':confidence,'reason':reason,'line_count':len(usable),
            'first_line_indent_pt':round(indent,4),'baseline_step_pt':round(step,4) if step else None,
            'line_height_ratio':round(step/size,4) if step else None,'font_size_pt':round(size,4),
            'baseline_measurement':'native_glyph_origins' if all('baseline' in l for l in usable) else 'ocr_line_centers_estimate',
            'nonfinal_right_spread_pt':round(spread(right[:-1]),4),'continuation_left_spread_pt':round(spread(left[1:]),4),
            'continuation_left_pt':round(statistics.median(left[1:]) if len(left)>1 else left[0],4),
            'nonfinal_right_pt':round(statistics.median(right[:-1]) if len(right)>1 else right[0],4),
            'tolerance_pt':round(tolerance,4),'source_lines':usable}


def page_native_blocks(page: Any) -> list[dict[str, Any]]:
    """原生PDF逐页读取字形、RGB、粗斜体和链接，排除图片字节。"""
    import fitz
    blocks=[];links=page.get_links()
    for block in page.get_text('dict',flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        if not block.get('lines'):continue
        lines=[];runs=[];offset=0
        for line in block['lines']:
            spans=line['spans'];text=''.join(s['text'] for s in spans)
            if not text.strip():continue
            sizes=[float(s['size']) for s in spans if s['text'].strip()]
            primary=statistics.median(sizes) if sizes else 0.
            origins=[float(s['origin'][1]) for s in spans if s['text'].strip() and s['size']>=primary*.85]
            lines.append({'text':text,'bbox':list(line['bbox']),'baseline':statistics.median(origins),
                          'font_size':primary,'direction':list(line.get('dir',(1,0)))})
            for span in spans:
                value=span['text'];runs.append({'text':value,'start':offset,'end':offset+len(value),
                    'bbox':list(span['bbox']),'font':span['font'],'font_size':float(span['size']),
                    'rgb':int(span['color'])&0xffffff,'bold':bool(span['flags']&16),
                    'italic':bool(span['flags']&2),'superscript':bool(span['flags']&1)})
                offset+=len(value)
            offset+=1
        if not lines:continue
        box=list(block['bbox']);text='\n'.join(l['text'] for l in lines)
        geometry=infer_paragraph_geometry(lines,frame=box)
        anchors=[]
        for link in links:
            if not fitz.Rect(box).intersects(link['from']):continue
            labels=[r['text'] for r in runs if fitz.Rect(r['bbox']).intersects(link['from'])]
            anchors.append({'kind':link['kind'],'uri':link.get('uri'),'target_page':link.get('page'),
                            'bbox':list(link['from']),'source_label':''.join(labels)})
        citations=[]
        plain=text.replace('\n',' ')
        patterns=[('numeric',r'\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]'),
                  ('author_year',r'\b[A-Z][A-Za-z\-]+(?:\s+et\s+al\.)?,?\s*\(?\s*(?:19|20)\d{2}[a-z]?\b')]
        for kind,pattern in patterns:
            citations.extend({'kind':kind,'text':m.group(),'source_start':m.start(),'source_end':m.end()}
                             for m in re.finditer(pattern,plain))
        blocks.append({'block_number':block.get('number'),'bbox':box,'text':text,
                       'geometry':geometry,'inline_runs':runs,'links':anchors,'citations':citations})
    return blocks


def locate_region_formatting(page: Any, text: str, *, hint: list[float],
                             font_size: float | None = None) -> dict[str, Any]:
    """将冻结源段文字绑定到实际字形；跟踪边界落在行中时标为续文。"""
    import fitz
    chars=[];norm='';indices=[];line_ids=[];line_rows={}
    for block in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        for li,line in enumerate(block.get('lines',[])):
            key=(block.get('number'),li);line_rows[key]=line
            for span in line['spans']:
                for c in span['chars']:
                    i=len(chars);chars.append({**c,'size':float(span['size']),'font':span['font'],
                                             'flags':span['flags'],'rgb':int(span['color'])&0xffffff})
                    line_ids.append(key)
                    for v in normalized_text(c['c']):norm+=v;indices.append(i)
    query=normalized_text(text);matches=[m.start() for m in re.finditer(re.escape(query),norm)] if query else []
    if not matches:raise ValueError('source_formatting_region_text_not_found')
    def box_for(pos):
        selected=chars[indices[pos]:indices[pos+len(query)-1]+1]
        rect=fitz.Rect(selected[0]['bbox'])
        for c in selected[1:]:rect|=c['bbox']
        return rect
    if len(matches)>1:
        box=fitz.Rect(hint);ranked=sorted((abs(box_for(p).x0-box.x0)+abs(box_for(p).y0-box.y0),p) for p in matches)
        if len(ranked)>1 and abs(ranked[0][0]-ranked[1][0])<.5:raise ValueError('source_formatting_region_text_ambiguous')
        pos=ranked[0][1]
    else:pos=matches[0]
    first=indices[pos];last=indices[pos+len(query)-1]+1
    leading=re.match(r'^[\W_]*',text).group().strip()
    trailing=re.search(r'[\W_]*$',text).group().strip()
    while first>0 and chars[first-1]['c'] in leading and line_ids[first-1]==line_ids[first]:first-=1
    while last<len(chars) and chars[last]['c'] in trailing and line_ids[last]==line_ids[last-1]:last+=1
    chosen=chars[first:last];lines=[];primary=font_size or statistics.median(c['size'] for c in chosen if c['c'].strip())
    baseline_clusters=[]
    for y in sorted({c['origin'][1] for c in chosen if c['c'].strip() and primary*.85<=c['size']<=primary*1.2}):
        if not baseline_clusters or y-baseline_clusters[-1]>.35:baseline_clusters.append(y)
    if not baseline_clusters:baseline_clusters=sorted({c['origin'][1] for c in chosen if c['c'].strip()})
    for y in baseline_clusters:
        cs=[c for c in chosen if c['c'].strip() and c['size']<=primary*1.5
            and min(baseline_clusters,key=lambda v:abs(v-c['origin'][1]))==y]
        if not cs:continue
        rect=fitz.Rect(cs[0]['bbox'])
        for c in cs[1:]:rect|=c['bbox']
        lines.append({'text':''.join(c['c'] for c in cs),'bbox':list(rect),'baseline':y,'font_size':primary})
    first_line=line_ids[first];line_prefix=[c['c'] for i,c in enumerate(chars[:first])
        if (line_ids[i]==first_line or abs(c['origin'][1]-chars[first]['origin'][1])<.35)
        and c['bbox'][0]>=hint[0]-primary*.2 and c['bbox'][0]<chars[first]['bbox'][0]]
    continuation=bool(normalized_text(''.join(line_prefix)))
    geometry=infer_paragraph_geometry(lines,frame=hint,font_size=font_size,continuation=continuation)
    runs=[];offset=0
    for c in chosen:
        style={'rgb':c['rgb'],'font':c['font'],'font_size':c['size'],
               'bold':bool(c['flags']&16),'italic':bool(c['flags']&2),'superscript':bool(c['flags']&1)}
        if runs and all(runs[-1][k]==v for k,v in style.items()):runs[-1]['text']+=c['c'];runs[-1]['end']=offset+len(c['c'])
        else:runs.append({**style,'text':c['c'],'start':offset,'end':offset+len(c['c'])})
        offset+=len(c['c'])
    citations=[]
    flat=''.join(c['c'] for c in chosen)
    for kind,pattern in [('numeric',r'\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]'),
                         ('author_year',r'\b[A-Z][A-Za-z\-]+(?:\s+et\s+al\.)?,?\s*\(?\s*(?:19|20)\d{2}[a-z]?\b')]:
        citations.extend({'kind':kind,'text':m.group(),'start':m.start(),'end':m.end()} for m in re.finditer(pattern,flat))
    return {'geometry':geometry,'inline_runs':runs,'citations':citations,
            'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'binding':'normalized_native_glyphs_with_geometric_hint','starts_inside_printed_line':continuation}


def extract_pdf_formatting(source: Path, *, page_limit: int = 500) -> dict[str, Any]:
    """固定页数上限，逐页提取；扫描页明确待OCR，不凭空生成颜色或字体。"""
    import fitz
    if not 1<=page_limit<=500:raise ValueError('source_formatting_page_limit_out_of_range')
    pages=[]
    with fitz.open(source) as doc:
        for i in range(min(len(doc),page_limit)):
            blocks=page_native_blocks(doc[i]);pages.append({'page':i+1,'blocks':blocks,
                'status':'native_geometry_and_spans' if blocks else 'needs_ocr_line_geometry_and_visual_style_review'})
        total=len(doc)
    return {'schema_version':1,'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'pages':pages,'total_pages':total,'page_limit':page_limit,'scope_complete':total<=page_limit,
            'style_inference_policy':'Source geometry and inline spans retained with confidence; unknown is not automatically justified.',
            'color_space':'PDF text RGB integer; scanned colors require separate pixel evidence',
            'status':'ok' if total<=page_limit else 'partial_page_limit'}
