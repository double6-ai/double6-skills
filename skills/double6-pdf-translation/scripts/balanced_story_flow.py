"""在完整段落内选择满足字距上限的印刷行；保留原字体、CID及科学行内项。"""
from __future__ import annotations
from html.parser import HTMLParser
from io import BytesIO
import math,re,unicodedata

def norm(text):return ''.join(c for c in unicodedata.normalize('NFKC',text) if not c.isspace() and c not in '\u200b\u2028')
def cjk(code):
    return (0x3400<=code<=0x9fff or 0x3000<=code<=0x303f or 0xff00<=code<=0xffef or
            any(0x3400<=ord(c)<=0x9fff for c in unicodedata.normalize('NFKC',chr(code))))

class Paragraphs(HTMLParser):
    def __init__(self,alignment):
        super().__init__(convert_charrefs=True);self.alignment=alignment;self.rows=[];self.current=None;self.stack=[]
    def handle_starttag(self,tag,attrs):
        style=dict(attrs).get('style','')
        if tag=='p':
            if self.current is not None:raise ValueError('balanced_nested_paragraph')
            match=re.search(r'text-align\s*:\s*(left|right|center|justify)',style)
            self.current={'text':'','alignment':match[1] if match else self.alignment,'protected':[]};self.stack=[]
        if self.current is not None:
            if tag=='br':raise ValueError('balanced_explicit_break_requires_separate_adapter')
            start=len(norm(self.current['text'])) if re.search(r'white-space\s*:\s*nowrap',style) else None
            self.stack.append((tag,start))
    def handle_endtag(self,tag):
        if self.current is None:return
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                for _,start in self.stack[i:]:
                    if start is not None:self.current['protected'].append((start,len(norm(self.current['text']))))
                del self.stack[i:];break
        if tag=='p':self.rows.append(self.current);self.current=None
    def handle_data(self,data):
        if self.current is not None:self.current['text']+=data

def plan_balanced_lines(tokens, *, width, indent, maximum_added_spacing, maximum_tokens=2048, maximum_compression=0.):
    """动态规划只选择合法token断点，末行自然收尾，非末行逐间隙约束。"""
    if not tokens or len(tokens)>maximum_tokens or not all(math.isfinite(v) for v in (width,indent,maximum_added_spacing,maximum_compression)) or not 0<=indent<width or not 0<maximum_added_spacing<=10 or not 0<=maximum_compression<=maximum_added_spacing:
        raise ValueError('balanced_flow_bounds')
    n=len(tokens);cost=[math.inf]*(n+1);next_line=[None]*n;cost[n]=0
    closing=set('，。、：；？！)]}〉》」』】…');opening=set('（([{〈《「『【')
    def boundary(a,b):return not a['text'][-1] in opening and not b['text'][0] in closing
    for i in range(n-1,-1,-1):
        available=width-(indent if i==0 else 0);used=0;count=0
        for j in range(i,n):
            used+=tokens[j]['width'];count+=tokens[j].get('internal_gaps',0)
            visible_used=used-tokens[j].get('trailing_space_width',0.)
            if j>i and boundary(tokens[j-1],tokens[j]):count+=1
            if visible_used>available+count*maximum_compression+.001:break
            if j+1<n and not boundary(tokens[j],tokens[j+1]):continue
            extra=available-visible_used;last=j==n-1
            if last and extra>=0:extra=0.
            if (not last or extra<0) and (not count or extra>count*maximum_added_spacing+.001 or -extra>count*maximum_compression+.001):continue
            score=100+(0 if last else 10*(extra/(count*(maximum_added_spacing if extra>=0 else maximum_compression)))**2)+cost[j+1]
            if score<cost[i]:cost[i]=score;next_line[i]=(j+1,extra/count if (not last or extra<0) else 0.,visible_used)
    if next_line[0] is None:raise ValueError('balanced_flow_no_legal_solution_within_spacing_limit')
    rows=[];i=0
    while i<n:
        end,increment,used=next_line[i];rows.append({'start':i,'end':end,'increment_pt':increment,'used_width_pt':used,'last_line':end==n});i=end
    return rows,boundary

def balance_story_document(doc, html_text, *, font_size, lineheight, default_alignment='justify', maximum_added_spacing_em=.3, inline_attachment_policy=None, source_glyph_styles=None):
    """只写Story原生水平文字流；不合规格即停止，调用者须保留候选状态。"""
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject,ByteStringObject,ContentStream,FloatObject,NumberObject
    from inline_attachment import POLICY_ID, attachment_groups
    if inline_attachment_policy not in (None,POLICY_ID):
        raise ValueError('unknown_inline_attachment_policy')
    if len(doc)!=1 or not .1<=maximum_added_spacing_em<=.4 or not 1<=font_size<=30 or not 1<=lineheight<=2:
        raise ValueError('balanced_story_limits')
    page=doc[0];glyphs=[]
    if page.get_links():raise ValueError('balanced_annotations_require_label_rebinding')
    for span in page.get_texttrace():
        if span['type']!=0 or span['wmode']!=0 or tuple(round(v,6) for v in span['dir'])!=(1.,0.):
            raise ValueError('balanced_story_visible_horizontal_text_required')
        for c in span['chars']:
            glyphs.append({'unicode':c[0],'gid':c[1],'origin':list(c[2]),'bbox':list(c[3]),'size':span['size'],'color':span['color'],
                           'font':span['font'],'opacity':span['opacity'],'desired':list(c[2])})
    if len(glyphs)>10000:raise ValueError('balanced_story_glyph_budget')
    source_style_count=0
    if source_glyph_styles is not None:
        if not isinstance(source_glyph_styles,list) or len(source_glyph_styles)>10000:
            raise ValueError('balanced_source_style_budget')
        original=[g for g in source_glyph_styles if norm(chr(g['unicode']))]
        printed=[g for g in glyphs if norm(chr(g['unicode']))]
        if len(original)!=len(printed):raise ValueError('balanced_source_style_count_changed')
        source_hosts=sorted({round(g['origin'][1],3) for g in original if abs(g['size']-font_size)<.002 and 'origin' in g})
        for src,g in zip(original,printed):
            color=src['color']
            if (src['unicode']!=g['unicode'] or src['gid']!=g['gid'] or src['font']!=g['font'] or
                abs(src['size']-g['size'])>.002 or src.get('opacity',1.)!=g['opacity'] or
                len(color)!=3 or not all(math.isfinite(v) and 0<=v<=1 for v in color)):
                raise ValueError('balanced_source_style_identity_changed')
            g['color']=tuple(color)
            if src['size']<font_size*.85 and 'origin' in src:
                if not source_hosts:raise ValueError('balanced_source_style_host_missing')
                g['source_script_offset']=src['origin'][1]-min(source_hosts,key=lambda y:abs(y-src['origin'][1]))
        source_style_count=len(original)
    parser=Paragraphs(default_alignment);parser.feed(html_text)
    if parser.current is not None:raise ValueError('balanced_unclosed_paragraph')
    full='';indices=[]
    for i,g in enumerate(glyphs):
        text=norm(chr(g['unicode']));full+=text;indices.extend([i]*len(text))
    cursor=0;reports=[]
    for para in parser.rows:
        query=norm(para['text'])
        if not query:continue
        pos=full.find(query,cursor)
        if pos!=cursor:raise ValueError('balanced_complete_paragraph_text_binding')
        cursor=pos+len(query);first,last=indices[pos],indices[cursor-1]+1
        if para['alignment']!='justify':reports.append({'status':'not_applicable','reason':'source_alignment','glyphs':[first,last]});continue
        if any(g['size']>font_size*1.2 for g in glyphs[first:last]):raise ValueError('balanced_floating_initial_requires_adapter')
        hosts=sorted({round(g['origin'][1],3) for g in glyphs[first:last] if abs(g['size']-font_size)<.002 and not unicodedata.combining(chr(g['unicode']))})
        if not hosts:raise ValueError('balanced_host_baselines_missing')
        protected={}
        for start,end in sorted(para['protected'],key=lambda r:(r[0],-r[1])):
            if end<=start:continue
            a,b=indices[pos+start],indices[pos+end-1]+1
            if any(a>=left and b<=right for left,right in protected.items()):continue
            if any(a<right and b>left for left,right in protected.items()):raise ValueError('balanced_crossing_atomic_spans')
            protected[a]=b
        automatic=[]
        if inline_attachment_policy is not None:
            automatic=attachment_groups(glyphs[first:last],font_size)
            intervals=list(protected.items())+[(first+g['start'],first+g['end']) for g in automatic]
            merged=[]
            for a,b in sorted(intervals):
                if merged and a<merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else:merged.append((a,b))
            protected=dict(merged)
        url_indices=set()
        native_text=''.join(chr(c['unicode']) for c in glyphs[first:last])
        for match in re.finditer(r'https?://[A-Za-z0-9_:/?=&%.#~+\-]+',native_text):
            url_indices.update(range(first+match.start(),first+match.end()))
        tokens=[];i=first
        while i<last:
            g=glyphs[i];char=chr(g['unicode'])
            if char.isspace() or char=='\u200b':
                if not tokens:raise ValueError('balanced_leading_unbound_whitespace')
                tokens[-1]['indices'].append(i);i+=1;continue
            if g['size']<font_size*.85 or unicodedata.combining(char):
                if not tokens:raise ValueError('balanced_script_without_preceding_host')
                tokens[-1]['indices'].append(i);i+=1;continue
            end=protected.get(i)
            if end is None:
                end=i+1
                if not cjk(g['unicode']):
                    url=i in url_indices
                    while end<last and end not in protected and not chr(glyphs[end]['unicode']).isspace() and not cjk(glyphs[end]['unicode']):
                        if url and chr(glyphs[end-1]['unicode']) in '/.-':break
                        end+=1
            tokens.append({'indices':list(range(i,end))});i=end
        for token in tokens:
            own=[glyphs[i] for i in token['indices']];relative=[];x=0;previous=None
            for g in own:
                host=min(hosts,key=lambda y:abs(g['origin'][1]-y))
                if previous is not None:
                    previous_host=min(hosts,key=lambda y:abs(previous['origin'][1]-y))
                    x+=g['origin'][0]-previous['origin'][0] if abs(host-previous_host)<.01 else previous['bbox'][2]-previous['bbox'][0]
                relative.append((x,g.get('source_script_offset',g['origin'][1]-host)));previous=g
            internal_gaps=[n for n,c in enumerate(own[:-1]) if chr(c['unicode']).isspace() and not chr(own[n+1]['unicode']).isspace()]
            token['internal_gap_positions']=internal_gaps;token['internal_gaps']=len(internal_gaps)
            token.update(relative=relative,text=''.join(chr(g['unicode']) for g in own).strip(),
                         width=max(x+g['bbox'][2]-g['bbox'][0] for (x,_),g in zip(relative,own)))
            visible_width=max(x+g['bbox'][2]-g['bbox'][0] for (x,_),g in zip(relative,own) if not chr(g['unicode']).isspace())
            token['trailing_space_width']=max(0.,token['width']-visible_width)
            if token['width']<0 or not math.isfinite(token['width']):raise ValueError('balanced_token_width_invalid')
        indent=max(0.,glyphs[first]['origin'][0]);rows,boundary=plan_balanced_lines(tokens,width=page.rect.width,indent=indent,
            maximum_added_spacing=font_size*maximum_added_spacing_em,maximum_compression=font_size*.05)
        for line_no,row in enumerate(rows):
            x=indent if line_no==0 else 0.;baseline=hosts[0]+line_no*font_size*lineheight
            for tindex in range(row['start'],row['end']):
                token=tokens[tindex]
                for n,(index,(dx,dy)) in enumerate(zip(token['indices'],token['relative'])):
                    shift=sum(k<n for k in token['internal_gap_positions'])*row['increment_pt']
                    glyphs[index]['desired']=[x+dx+shift,baseline+dy]
                x+=token['width']+token['internal_gaps']*row['increment_pt']
                if tindex+1<row['end'] and boundary(token,tokens[tindex+1]):x+=row['increment_pt']
        reports.append({'status':'planned','glyphs':[first,last],'original_host_lines':len(hosts),'planned_host_lines':len(rows),
                        'maximum_added_spacing_pt':max(r['increment_pt'] for r in rows),'rows':rows,'protected_items':len(protected),
                        'automatic_attachment_groups':automatic})
    if cursor!=len(full):raise ValueError('balanced_unbound_printed_text')
    reader=PdfReader(BytesIO(doc.tobytes()));p=reader.pages[0];stream=ContentStream(p.get_contents(),reader);fonts=p['/Resources']['/Font']
    new=[];font=None;matrix=None;at=0;leading=0.
    for operands,operator in stream.operations:
        if operator==b'Tf':font=operands[0]
        if operator==b'Tm':
            if tuple(round(float(v),6) for v in operands[:4])!=(1.,0.,0.,-1.):raise ValueError('balanced_text_matrix_requires_adapter')
            matrix=[float(v) for v in operands]
        if operator==b'TL':leading=float(operands[0])
        if operator in {b'Td',b'TD',b'T*'}:
            if matrix is None:raise ValueError('balanced_relative_matrix_without_origin')
            tx,ty=(0.,-leading) if operator==b'T*' else (float(operands[0]),float(operands[1]))
            if operator==b'TD':leading=-ty
            matrix[4]+=tx*matrix[0]+ty*matrix[2];matrix[5]+=tx*matrix[1]+ty*matrix[3]
        if operator not in {b'Tj',b'TJ'}:new.append((operands,operator));continue
        if font is None or matrix is None or str(fonts[font].get('/Encoding'))!='/Identity-H':raise ValueError('balanced_font_encoding_requires_adapter')
        values=operands[0] if operator==b'TJ' else operands
        for value in values:
            if not isinstance(value,(bytes,str)):continue
            raw=bytes(value) if isinstance(value,bytes) else value.original_bytes
            if len(raw)%2:raise ValueError('balanced_cid_length')
            for offset in range(0,len(raw),2):
                if at>=len(glyphs):raise ValueError('balanced_glyph_count_exceeded')
                g=glyphs[at];code=raw[offset:offset+2]
                if int.from_bytes(code,'big')!=g['gid']:raise ValueError('balanced_cid_order_changed')
                # Story的页面/文字翻转共同映射到原生顶部坐标。写后逐字形核对实际位置。
                m=ArrayObject([NumberObject(1),NumberObject(0),NumberObject(0),NumberObject(-1),
                    FloatObject(g['desired'][0]),FloatObject(matrix[5]+g['desired'][1]-g['origin'][1])])
                new.append((m,b'Tm'));new.append(([ArrayObject([ByteStringObject(code)])],b'TJ'));at+=1
                if source_glyph_styles is not None:
                    new.insert(len(new)-1,([FloatObject(v) for v in g['color']],b'rg'))
    if at!=len(glyphs):raise ValueError('balanced_glyph_count_incomplete')
    streams=page.get_contents()
    if len(streams)!=1:raise ValueError('balanced_multiple_streams_requires_adapter')
    stream.operations=new;doc.update_stream(streams[0],stream.get_data())
    after=[(c,s) for s in doc[0].get_texttrace() for c in s['chars']]
    if len(after)!=len(glyphs):raise ValueError('balanced_actual_glyph_count_changed')
    color_tolerance=.000001 if source_glyph_styles is not None else 0.
    maximum_rgb_error=0.
    for g,(c,s) in zip(glyphs,after):
        rgb_error=max(abs(a-b) for a,b in zip(s['color'],g['color']))
        maximum_rgb_error=max(maximum_rgb_error,rgb_error)
        if c[0]!=g['unicode'] or c[1]!=g['gid'] or s['font']!=g['font'] or s['opacity']!=g['opacity'] or rgb_error>color_tolerance or abs(s['size']-g['size'])>.001 or max(abs(c[2][i]-g['desired'][i]) for i in (0,1))>.03:
            raise ValueError('balanced_actual_text_style_or_position_not_verified')
    return {'paragraphs':reports,'glyph_count':len(glyphs),'glyph_identity_size_color_preserved':True,
            'maximum_added_spacing_em':maximum_added_spacing_em,'maximum_compression_em':.05,
            'inline_attachment_policy':inline_attachment_policy,'font_and_opacity_preserved':True,
            'source_rgb_restored_glyph_count':source_style_count,'maximum_source_rgb_roundtrip_error':maximum_rgb_error,
            'source_rgb_roundtrip_tolerance':color_tolerance,'quality_pass':False}
