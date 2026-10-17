"""MuPDF Story中文非末行的实际两端对齐，保留字形、颜色及非中文词内间距。"""
from __future__ import annotations

import html.parser
import re
import statistics
import unicodedata
from io import BytesIO
from typing import Any

from source_formatting import normalized_text


class _Paragraphs(html.parser.HTMLParser):
    def __init__(self,alignment: str):
        super().__init__(convert_charrefs=True);self.alignment=alignment;self.rows=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='p':
            if self.current is not None:raise ValueError('nested_paragraph_not_supported')
            style=dict(attrs).get('style','');match=re.search(r'text-align\s*:\s*(left|right|center|justify)',style)
            self.current={'text':'','alignment':match.group(1) if match else self.alignment}
        elif tag=='br' and self.current is not None:self.current['text']+='\u2028'
    def handle_endtag(self,tag):
        if tag=='p' and self.current is not None:
            self.rows.extend({**self.current,'text':part} for part in self.current['text'].split('\u2028'))
            self.current=None
    def handle_data(self,data):
        if self.current is not None:self.current['text']+=data


def _is_cjk(value: int) -> bool:
    return 0x3400<=value<=0x9fff or 0x3000<=value<=0x303f or 0xff00<=value<=0xffef


def justify_story_document(doc: Any, html_text: str, *, default_alignment: str = 'justify') -> dict[str, Any]:
    """只处理Story生成的水平Identity-H字形；不支持的流在提交前失败。"""
    import fitz
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject,ByteStringObject,ContentStream,FloatObject,NumberObject
    if len(doc)!=1:raise ValueError('cjk_justification_requires_single_story_page')
    page=doc[0];trace=page.get_texttrace();glyphs=[]
    for span in trace:
        if tuple(round(float(x),6) for x in span['dir'])!=(1.,0.) or span['wmode']!=0 or span['type']!=0:
            raise ValueError('cjk_justification_requires_horizontal_visible_text')
        for c in span['chars']:glyphs.append({'unicode':c[0],'gid':c[1],'origin':c[2],'bbox':c[3],'size':span['size'],'color':span['color'],'shift':0.})
    parser=_Paragraphs(default_alignment);parser.feed(html_text)
    if parser.current is not None:raise ValueError('unclosed_source_paragraph')
    normalized='';indices=[]
    for i,g in enumerate(glyphs):
        for c in normalized_text(chr(g['unicode'])):normalized+=c;indices.append(i)
    cursor=0;paragraphs=[]
    for para in parser.rows:
        query=normalized_text(para['text'])
        if not query:continue
        pos=normalized.find(query,cursor)
        if pos<0:raise ValueError('story_paragraph_text_binding_failed')
        first=indices[pos];last=indices[pos+len(query)-1]+1;cursor=pos+len(query)
        # Trailing punctuation belongs to this paragraph; the next paragraph starts
        # with its first non-space printable glyph on a later line.
        while last<len(glyphs) and not chr(glyphs[last]['unicode']).isalnum() and (abs(glyphs[last]['origin'][1]-glyphs[last-1]['origin'][1])<2 or unicodedata.combining(chr(glyphs[last]['unicode']))):last+=1
        paragraphs.append({**para,'first':first,'last':last})
    records=[]
    for para in paragraphs:
        gs=glyphs[para['first']:para['last']];sizes=[g['size'] for g in gs if chr(g['unicode']).strip()]
        main=statistics.median(sizes);ys=sorted({round(g['origin'][1],2) for g in gs if main*.85<=g['size']<=main*1.2 and not unicodedata.combining(chr(g['unicode']))})
        if not ys:continue
        lines={y:[] for y in ys}
        for i in range(para['first'],para['last']):
            g=glyphs[i];y=min(ys,key=lambda v:abs(v-g['origin'][1]));lines[y].append(i)
        for n,(y,ids) in enumerate(sorted(lines.items())):
            visible=[i for i in ids if chr(glyphs[i]['unicode']).strip()]
            if not visible:continue
            ordered=sorted(visible,key=lambda i:glyphs[i]['origin'][0]);right=max(glyphs[i]['bbox'][2] for i in ordered)
            row={'paragraph_alignment':para['alignment'],'baseline':y,'last_line':n==len(lines)-1,'right_before':round(right,4),'right_target':round(page.rect.width,4),'applied':False}
            if para['alignment']!='justify' or row['last_line']:
                row['reason']='source_alignment_or_natural_final_line';records.append(row);continue
            if any(glyphs[i]['size']>main*1.2 for i in ordered):
                row['reason']='floating_initial_glyph_line';records.append(row);continue
            boundaries=[]
            base_ordered=[i for i in ordered if not unicodedata.combining(chr(glyphs[i]['unicode']))]
            for a,b in zip(base_ordered,base_ordered[1:]):
                ga,gb=glyphs[a],glyphs[b]
                if (_is_cjk(ga['unicode']) or _is_cjk(gb['unicode'])) and not unicodedata.combining(chr(gb['unicode'])):
                    boundaries.append((ga['origin'][0],gb['origin'][0]))
            extra=page.rect.width-right
            if extra<-.75:raise ValueError('story_line_already_outside_source_frame')
            if not boundaries or extra<=.02:
                row['reason']='no_cjk_boundary_or_already_aligned';records.append(row);continue
            increment=extra/len(boundaries)
            if increment>main*.8:raise ValueError('cjk_justification_excessive_gap_requires_review')
            for i in ids:
                x=glyphs[i]['origin'][0];glyphs[i]['shift']=increment*sum(b<=x+.001 for a,b in boundaries)
            previous_base=None
            for i in ids:
                if unicodedata.combining(chr(glyphs[i]['unicode'])):
                    if previous_base is None:raise ValueError('combining_mark_without_same_line_base')
                    glyphs[i]['shift']=glyphs[previous_base]['shift']
                else:previous_base=i
            row.update(applied=True,added_per_boundary_pt=round(increment,5),boundaries=len(boundaries));records.append(row)
    if not any(g['shift'] for g in glyphs):return {'lines':records,'glyph_count':len(glyphs),'modified':False,'glyph_unicode_size_color_and_baseline_preserved':True}
    reader=PdfReader(BytesIO(doc.tobytes()));p=reader.pages[0];stream=ContentStream(p.get_contents(),reader)
    fonts=p['/Resources']['/Font'];new=[];at=0;font=None;applied_shift=0.
    for operands,operator in stream.operations:
        if operator==b'Tf':font=operands[0]
        if operator in {b'Tm',b'Td',b'TD',b'T*'}:
            if operator==b'Tm' and any(abs(float(x)-expected)>1e-5 for x,expected in zip(operands[:4],(1.,0.,0.,-1.))):raise ValueError('unsupported_story_text_matrix '+str(operands))
            applied_shift=0.
        if operator in {b'BT',b'ET'}:applied_shift=0.
        if operator not in {b'TJ',b'Tj'}:new.append((operands,operator));continue
        if font is None or str(fonts[font].get('/Encoding'))!='/Identity-H':raise ValueError('unsupported_story_font_encoding')
        values=operands[0] if operator==b'TJ' else operands;array=ArrayObject();buffer=bytearray()
        def flush():
            if buffer:array.append(ByteStringObject(bytes(buffer)));buffer.clear()
        for value in values:
            if not isinstance(value,(bytes,str)):
                flush();array.append(value);continue
            raw=bytes(value) if isinstance(value,bytes) else value.original_bytes
            if len(raw)%2:raise ValueError('invalid_story_cid_sequence')
            for offset in range(0,len(raw),2):
                if at>=len(glyphs):raise ValueError('story_glyph_count_exceeded')
                g=glyphs[at];code=raw[offset:offset+2]
                if int.from_bytes(code,'big')!=g['gid']:raise ValueError('story_cid_glyph_identity_mismatch')
                delta=g['shift']-applied_shift
                if abs(delta)>1e-7:
                    flush();array.append(FloatObject(-delta*1000/g['size']))
                buffer.extend(code);applied_shift=g['shift'];at+=1
        flush();new.append(([array],b'TJ'))
    if at!=len(glyphs):raise ValueError('story_glyph_count_incomplete')
    contents=page.get_contents()
    if len(contents)!=1:raise ValueError('unsupported_story_multiple_content_streams')
    stream.operations=new;doc.update_stream(contents[0],stream.get_data())
    after=[(c,span) for span in doc[0].get_texttrace() for c in span['chars']]
    if len(after)!=len(glyphs):raise ValueError('justified_glyph_count_changed')
    for g,(c,span) in zip(glyphs,after):
        if c[0]!=g['unicode'] or c[1]!=g['gid'] or abs(c[2][1]-g['origin'][1])>.02 or abs(c[2][0]-g['origin'][0]-g['shift'])>.03 or abs(span['size']-g['size'])>.001 or span['color']!=g['color']:
            raise ValueError('justified_text_style_or_position_changed_unexpectedly')
    return {'lines':records,'glyph_count':len(glyphs),'modified':True,'glyph_unicode_size_color_and_baseline_preserved':True}


def insert_source_htmlbox(page: Any, rect: Any, text: str, *, css: str, archive: Any,
                          default_alignment: str = 'justify', balanced_line_flow: dict[str,Any] | None = None) -> tuple[float,float,dict[str,Any]]:
    """固定scale=1的Story试排，成功后将真实两端对齐的文字层写回。"""
    import fitz
    rect=fitz.Rect(rect);local=fitz.Rect(0,0,rect.width,rect.height)
    # Story原生justify会先放大Latin词间空格；先左对齐试排，再按中文边界推进。
    story_markup=re.sub(r'(text-align\s*:\s*)justify\b',r'\1left',text)
    story_css=re.sub(r'(text-align\s*:\s*)justify\b',r'\1left',css)
    story=fitz.Story(html=story_markup,user_css='body{margin:1px;}'+story_css,archive=archive)
    more,filled=story.place(local)
    if more or not (local+(-.002,-.002,.002,.002)).contains(fitz.Rect(filled)):
        return -1.,1.,{'modified':False,'lines':[],'fit':False,'filled':list(filled),
                      'reason':'actual_story_unfinished_or_filled_exceeds_frame'}
    story.reset()
    def rectangles(number,*args):
        if number:raise ValueError('fixed_source_frame_requires_second_page')
        return local,local,fitz.Identity
    doc=story.write_with_links(rectangles)
    try:
        balanced=None
        if balanced_line_flow is not None:
            from balanced_story_flow import balance_story_document
            balanced=balance_story_document(doc,text,font_size=float(balanced_line_flow['font_size']),
                lineheight=float(balanced_line_flow['lineheight']),default_alignment=default_alignment,
                maximum_added_spacing_em=float(balanced_line_flow.get('maximum_added_spacing_em',.3)),
                inline_attachment_policy=balanced_line_flow.get('inline_attachment_policy'),
                source_glyph_styles=balanced_line_flow.get('source_glyph_styles'))
            boxes=[c[3] for span in doc[0].get_texttrace() for c in span['chars'] if not chr(c[0]).isspace()]
            if any(b[0]<-.25 or b[1]<-.25 or b[2]>local.width+.25 or b[3]>local.height+.25 for b in boxes):
                raise ValueError('balanced_source_frame_overflow')
            filled=fitz.Rect(0,0,local.width,max(b[3] for b in boxes)+.25)
        report=justify_story_document(doc,text,default_alignment=default_alignment)
        if balanced is not None:report['balanced_line_flow']=balanced
        page.show_pdf_page(rect,doc,0)
        for link in doc[0].get_links():
            link['from']*=fitz.Matrix(1,0,0,1,rect.x0,rect.y0);page.insert_link(link)
    finally:doc.close()
    return max(0.,local.y1-filled[3]),1.,report
