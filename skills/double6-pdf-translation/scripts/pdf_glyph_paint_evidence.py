"""直接 PDF 字符码的有限绘制证明；不把 Unicode 展开续字当作空字形。"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import hashlib,json,math,re
from pypdf.generic import (ContentStream,DecodedStreamObject,read_object,
                          IndirectObject,DictionaryObject)

def _object(document,xref,key):
    kind,raw=document.xref_get_key(xref,key)
    if kind=='null':return None
    value=read_object(BytesIO(raw.encode()+b'\n'),object())
    if isinstance(value,IndirectObject):
        if value.generation:raise ValueError('paint_pdf_reference_unsupported')
        value=read_object(BytesIO(document.xref_object(value.idnum).encode()+b'\n'),object())
    return value

def explicit_type1_gid_width(engine,xref,raw,digest):
    """只有实际 Differences 的显式码名映射可新增；不猜 BaseEncoding。"""
    model=engine.fonts[digest]
    if not raw or model['kind']!='cff' or hasattr(model['font'],'ROS'):
        raise ValueError('ink_zero_advance_encoding_unsupported')
    encoding=_object(engine.document,xref,'Encoding')
    if not isinstance(encoding,DictionaryObject) or '/Differences' not in encoding:
        raise ValueError('ink_zero_advance_encoding_unsupported')
    if set(encoding)-{'/Type','/BaseEncoding','/Differences'}:
        raise ValueError('ink_zero_advance_encoding_unsupported')
    names={};current=None
    for item in encoding['/Differences']:
        if isinstance(item,int) and not isinstance(item,bool):current=int(item)
        else:
            if current is None or not 0<=current<=255 or not str(item).startswith('/') or current in names:
                raise ValueError('ink_zero_advance_differences_invalid')
            names[current]=str(item)[1:];current+=1
    name=names.get(raw[0]);font=model['font']
    if name is None or name not in font.CharStrings.charStrings or font.charset.count(name)!=1:
        raise ValueError('ink_zero_advance_explicit_character_mapping_missing')
    first=engine._pdf_value(xref,'FirstChar');widths=engine._pdf_value(xref,'Widths')
    if first is None or not isinstance(widths,list) or not 0<=raw[0]-int(first)<len(widths):
        raise ValueError('ink_zero_advance_pdf_width_missing')
    return font.charset.index(name),widths[raw[0]-int(first)],raw[:1].hex(),len(raw)==1

def metric_neutral_extgstate(document,page,name):
    """仅 OPM 字段且 OP/op 从初态 false 未改变；其余字段全部阻断。"""
    kind,raw=document.xref_get_key(page.xref,'Resources/ExtGState/'+str(name).lstrip('/'))
    if kind!='xref':raise ValueError('paint_extgstate_resource_unsupported')
    xref=int(raw.split()[0]);text=document.xref_object(xref)
    value=read_object(BytesIO(text.encode()+b'\n'),object())
    if (not isinstance(value,DictionaryObject) or set(value)-{'/Type','/OPM'} or
        str(value.get('/Type','/ExtGState'))!='/ExtGState' or
        isinstance(value.get('/OPM',0),bool) or not isinstance(value.get('/OPM',0),int) or
        value.get('/OPM',0) not in (0,1)):
        raise ValueError('paint_extgstate_fields_unsupported')
    return {'resource_name':str(name).lstrip('/'),'xref':xref,'object':text,
            'OPM':int(value.get('/OPM',0)),'tracked_OP':False,'tracked_op':False,
            'font_or_transparency_change_present':False}

def parse_tounicode(raw,*,maximum_mappings=65536):
    """有界完整 bfchar/bfrange 与码空间；外部 usecmap 不受支持。"""
    if len(raw)>262144:raise ValueError('paint_ToUnicode_byte_budget')
    text=re.sub(r'%[^\r\n]*','',raw.decode('latin1'))
    begins=list(re.finditer(r'\bbegincmap\b',text));ends=list(re.finditer(r'\bendcmap\b',text))
    if ('usecmap' in text or len(begins)!=1 or len(ends)!=1 or begins[0].end()>ends[0].start()):
        raise ValueError('paint_ToUnicode_external_or_structure_unsupported')
    outside=text[:begins[0].start()]+text[ends[0].end():]
    marker=r'\b(?:begin|end)(?:codespacerange|bfchar|bfrange|cidchar|cidrange|notdefchar|notdefrange)\b'
    if re.search(marker,outside):raise ValueError('paint_ToUnicode_mapping_outside_CMap')
    text=text[begins[0].end():ends[0].start()]
    consumed=[]
    for section in ('codespacerange','bfchar','bfrange'):
        matches=list(re.finditer(r'(\d+)\s+begin'+section+r'\b(.*?)end'+section+r'\b',text,re.S))
        if (len(re.findall(r'\bbegin'+section+r'\b',text))!=len(matches) or
            len(re.findall(r'\bend'+section+r'\b',text))!=len(matches)):
            raise ValueError('paint_ToUnicode_unconsumed_mapping_section')
        consumed.extend((m.start(),m.end()) for m in matches)
    ordered=sorted(consumed)
    if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise ValueError('paint_ToUnicode_nested_mapping_sections')
    remainder=text
    for start,end in reversed(ordered):remainder=remainder[:start]+remainder[end:]
    remainder=re.sub(r'/CIDSystemInfo\s*<<\s*/Registry\s*\([^()]*\)\s*/Ordering\s*\([^()]*\)\s*/Supplement\s+\d+\s*>>\s*def','',remainder)
    remainder=re.sub(r'/CMapName\s*/[A-Za-z0-9_.+\-]+\s+def','',remainder)
    remainder=re.sub(r'/CMapType\s+2\s+def|/WMode\s+[01]\s+def','',remainder)
    if remainder.strip():raise ValueError('paint_ToUnicode_unknown_mapping_operator_or_metadata')
    mapping={};spaces=[]
    def code(value):
        if len(value)%2:raise ValueError('paint_ToUnicode_hex_invalid')
        result=bytes.fromhex(value)
        if len(result) not in (1,2):raise ValueError('paint_ToUnicode_code_width_unsupported')
        return result
    def unicode(value):
        data=bytes.fromhex(value)
        if not data or len(data)%2 or len(data)>32:raise ValueError('paint_ToUnicode_unicode_invalid')
        try:return data.decode('utf-16-be')
        except UnicodeDecodeError as error:raise ValueError('paint_ToUnicode_unicode_invalid') from error
    def add(key,value):
        if key in mapping or len(mapping)>=maximum_mappings:raise ValueError('paint_ToUnicode_duplicate_or_budget')
        mapping[key]=value
    pair=re.compile(r'<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>')
    for count,body in re.findall(r'(\d+)\s+begincodespacerange(.*?)endcodespacerange',text,re.S):
        rows=list(pair.finditer(body))
        if len(rows)!=int(count) or pair.sub('',body).strip():raise ValueError('paint_ToUnicode_codespace_invalid')
        for row in rows:
            lo,hi=map(code,row.groups())
            if len(lo)!=len(hi) or lo>hi:raise ValueError('paint_ToUnicode_codespace_invalid')
            spaces.append((lo,hi))
    if not spaces:raise ValueError('paint_ToUnicode_codespace_missing')
    for count,body in re.findall(r'(\d+)\s+beginbfchar(.*?)endbfchar',text,re.S):
        rows=list(pair.finditer(body))
        if len(rows)!=int(count) or pair.sub('',body).strip():raise ValueError('paint_ToUnicode_bfchar_invalid')
        for row in rows:
            key,value=row.groups();add(code(key),unicode(value))
    ranges=re.compile(r'<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(\[[^\]]*\]|<[0-9a-fA-F]+>)',re.S)
    for count,body in re.findall(r'(\d+)\s+beginbfrange(.*?)endbfrange',text,re.S):
        rows=list(ranges.finditer(body))
        if len(rows)!=int(count) or ranges.sub('',body).strip():raise ValueError('paint_ToUnicode_bfrange_invalid')
        for row in rows:
            first,last,target=row.groups();lo,hi=code(first),code(last);n=int.from_bytes(hi,'big')-int.from_bytes(lo,'big')+1
            if len(lo)!=len(hi) or not 0<n<=maximum_mappings:raise ValueError('paint_ToUnicode_bfrange_invalid')
            if target.startswith('['):
                values=re.findall(r'<([0-9a-fA-F]+)>',target)
                if len(values)!=n or re.sub(r'<[0-9a-fA-F]+>|\[|\]','',target).strip():raise ValueError('paint_ToUnicode_array_invalid')
                values=[unicode(v) for v in values]
            else:
                data=bytes.fromhex(target[1:-1]);base=int.from_bytes(data,'big');values=[]
                for i in range(n):
                    try:values.append(unicode((base+i).to_bytes(len(data),'big').hex()))
                    except OverflowError as error:raise ValueError('paint_ToUnicode_bfrange_overflow') from error
            for i,value in enumerate(values):add((int.from_bytes(lo,'big')+i).to_bytes(len(lo),'big'),value)
    if any(not any(len(k)==len(lo) and lo<=k<=hi for lo,hi in spaces) for k in mapping):
        raise ValueError('paint_ToUnicode_mapping_outside_codespace')
    return mapping

def _mul(a,b):
    return [a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],
            a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]]

class ActualPDFGlyphPaintEvidence:
    """懒读一页直接资源，只证明完整单次 CID CFF Unicode 展开簇。"""
    def __init__(self,engine):
        self.engine=engine;self.document=engine.document;self.page=engine.page
        self._native=None;self._ops=None;self._proofs={};self._widths={};self._maps={}
        self._initial_file_identity=self._file_identity()

    def _file_identity(self):
        path=Path(self.document.name) if self.document.name else None
        if path and path.is_file():
            if path.stat().st_size>64*1024**2:raise ValueError('paint_current_PDF_identity_or_budget')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            return {'path':str(path.resolve()),'sha256':digest}
        return None

    def _current_guard(self):
        if self.document.is_dirty:raise ValueError('paint_current_PDF_modified_after_load')
        if self._file_identity()!=self._initial_file_identity:
            raise ValueError('paint_current_PDF_file_identity_changed')

    def _read(self):
        self._current_guard()
        if self._native is not None:
            ids=self.page.get_contents();raw=b'\n'.join(self.document.xref_stream(x) for x in ids)
            resources=self.document.xref_get_key(self.page.xref,'Resources')
            if (ids!=self._page_identity['page_content_xrefs'] or
                hashlib.sha256(raw).hexdigest()!=self._page_identity['page_content_sha256'] or
                resources!=self._resource_identity):
                raise ValueError('paint_current_page_content_or_resources_changed')
            return
        from native_line_spacing import glyphs
        p=self.page
        if p.rotation or tuple(p.cropbox)!=tuple(p.mediabox) or p.mediabox.x0 or p.mediabox.y0:
            raise ValueError('paint_page_geometry_unsupported')
        native=glyphs(p)
        if not native or len(native)>20000 or sum(g['gid']<0 for g in native)>40:
            raise ValueError('paint_native_glyph_budget')
        spans=[];offset=0
        for span in p.get_texttrace():
            spans.append((offset,offset+len(span['chars']),span['seqno']));offset+=len(span['chars'])
        content_xrefs=p.get_contents();raw=b'\n'.join(self.document.xref_stream(x) for x in content_xrefs)
        if len(raw)>2097152:raise ValueError('paint_content_byte_budget')
        stream=DecodedStreamObject();stream.set_data(raw);ops=ContentStream(stream,None).operations
        if len(ops)>30000:raise ValueError('paint_content_operator_budget')
        resources={}
        for resource in p.get_fonts(full=True):
            if resource[-1]!=0:continue
            if resource[4] in resources and resources[resource[4]]!=resource[0]:raise ValueError('paint_resource_name_ambiguous')
            resources[resource[4]]=resource[0]
        if len(resources)>200:raise ValueError('paint_font_resource_budget')
        self._page_identity={'page_xref':p.xref,'page_number':p.number+1,'page_content_xrefs':content_xrefs,
            'page_content_sha256':hashlib.sha256(raw).hexdigest()}
        path=Path(self.document.name) if self.document.name else None
        if path and path.is_file():
            if self.document.is_dirty or path.stat().st_size>64*1024**2:raise ValueError('paint_current_PDF_identity_or_budget')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            self._page_identity['PDF_ref']={'path':str(path.resolve()),'sha256':digest}
        else:
            if len(self.document)>5:raise ValueError('paint_memory_PDF_page_budget')
            self._page_identity['PDF_ref']={'path':None,'sha256':hashlib.sha256(self.document.tobytes()).hexdigest()}
        self._resource_identity=self.document.xref_get_key(p.xref,'Resources')
        self._native=native;self._spans=spans;self._ops=ops;self._resources=resources

    def _width(self,resource,code):
        key=(resource,code)
        if key in self._widths:return self._widths[key]
        engine=self.engine;xref=self._resources[resource];subtype=engine._pdf_value(xref,'Subtype')
        if subtype=='/Type0':
            if engine._pdf_value(xref,'Encoding')!='/Identity-H':raise ValueError('paint_position_encoding_unsupported')
            children=_object(self.document,xref,'DescendantFonts')
            if len(children)!=1 or not isinstance(children[0],IndirectObject):raise ValueError('paint_descendant_unsupported')
            child=children[0].idnum;cid=int.from_bytes(code,'big');width=engine._pdf_value(child,'DW');width=1000 if width is None else width
            values=engine._pdf_value(child,'W') or [];i=0
            while i<len(values):
                start=int(values[i]);second=values[i+1]
                if isinstance(second,list):
                    if start<=cid<start+len(second):width=second[cid-start]
                    i+=2
                else:
                    if start<=cid<=int(second):width=values[i+2]
                    i+=3
        elif subtype=='/Type1' and len(code)==1:
            first=engine._pdf_value(xref,'FirstChar');values=engine._pdf_value(xref,'Widths')
            if first is None or not isinstance(values,list) or not 0<=code[0]-int(first)<len(values):
                return None
            width=values[code[0]-int(first)]
        else:raise ValueError('paint_position_font_type_unsupported')
        if not math.isfinite(width) or width<0:raise ValueError('paint_width_invalid')
        self._widths[key]=float(width);return float(width)

    def _mapping(self,xref):
        if xref not in self._maps:
            kind,raw=self.document.xref_get_key(xref,'ToUnicode')
            if kind!='xref':self._maps[xref]=None
            else:
                tx=int(raw.split()[0]);data=self.document.xref_stream(tx)
                self._maps[xref]=(parse_tounicode(data),tx,hashlib.sha256(data).hexdigest())
        return self._maps[xref]

    def _matches(self,primary,digest,expansion):
        e=self.engine;matches=[];identity=[1.,0.,0.,1.,0.,0.]
        ctm=identity[:];tm=lm=None;active=None;size=0.;horizontal=1.;rise=leading=tc=tw=0.;inside=False;stack=[];states=[];render=0
        def show(part,index,part_index):
            nonlocal tm
            raw=bytes(part) if isinstance(part,bytes) else getattr(part,'original_bytes',None)
            if raw is None:raise ValueError('paint_original_show_bytes_unavailable')
            if active not in self._resources:raise ValueError('paint_show_resource_unsupported')
            if tm is None:return
            fx=self._resources[active];subtype=e._pdf_value(fx,'Subtype');length=2 if subtype=='/Type0' else 1
            if len(raw)%length:raise ValueError('paint_show_code_width_invalid')
            for offset in range(0,len(raw),length):
                code=raw[offset:offset+length];width=self._width(active,code)
                if width is None:tm=None;return
                matrix=_mul(ctm,tm)
                if not all(math.isfinite(v) for v in [*matrix,size,horizontal,rise,width,tc,tw]):raise ValueError('paint_transform_nonfinite')
                origin=[matrix[4]+matrix[2]*rise,self.page.rect.height-matrix[5]-matrix[3]*rise]
                if max(abs(origin[i]-primary['origin'][i]) for i in (0,1))<.003:
                    candidate=e.resource_digests.get(fx)
                    if candidate==digest:
                        model=e.fonts[digest];font=model['font']
                        if (subtype!='/Type0' or e._pdf_value(fx,'Encoding')!='/Identity-H' or
                            model['kind']!='cff' or not hasattr(font,'ROS')):raise ValueError('paint_ligature_CID_CFF_branch_unsupported')
                        children=_object(self.document,fx,'DescendantFonts')
                        if len(children)!=1 or not isinstance(children[0],IndirectObject) or e._pdf_value(children[0].idnum,'Subtype')!='/CIDFontType0':
                            raise ValueError('paint_ligature_descendant_unsupported')
                        cid=int.from_bytes(code,'big');name=f'cid{cid:05d}';mapping=self._mapping(fx)
                        if (cid!=primary['gid'] or name not in font.CharStrings.charStrings or font.charset.count(name)!=1 or
                            mapping is None or mapping[0].get(code)!=expansion):raise ValueError('paint_code_CID_ToUnicode_cluster_mismatch')
                        if render!=0:raise ValueError('paint_ligature_render_mode_unsupported')
                        xvec=[matrix[0]*size*horizontal,-matrix[1]*size*horizontal];yvec=[-matrix[2]*size,matrix[3]*size]
                        xlen=math.hypot(*xvec);ylen=math.hypot(*yvec)
                        if (xlen<=0 or ylen<=0 or abs(xlen-primary['size'])>.003 or
                            abs(xvec[0]*yvec[0]+xvec[1]*yvec[1])>1e-5*xlen*ylen or
                            max(abs(xvec[i]/xlen-primary['direction'][i]) for i in (0,1))>.0001 or
                            sum([-xvec[1]/xlen*yvec[0],xvec[0]/xlen*yvec[1]])<=0):raise ValueError('paint_actual_axes_unsupported')
                        bounds,advance,shape=e._glyph(digest,primary['gid'])
                        if bounds is None or advance<=0 or abs(width-advance*1000/model['units'])>.001:
                            raise ValueError('paint_ligature_outline_or_advance_mismatch')
                        if abs(width*size*horizontal/1000-(primary['bbox'][2]-primary['bbox'][0]))>.003:
                            raise ValueError('paint_ligature_trace_advance_mismatch')
                        matches.append({**self._page_identity,'operation_index':index,'operator':'TJ' if part_index is not None else 'Tj',
                            'TJ_part_index':part_index,'character_byte_offset':offset,'show_raw_bytes_hex':raw.hex(),
                            'pdf_character_code_hex':code.hex(),'font_resource_xref':fx,'font_sha256':digest,
                            'ToUnicode_xref':mapping[1],'ToUnicode_stream_sha256':mapping[2],'Unicode_expansion':expansion,
                            'actual_trace_GID_CID_namespace':cid,'CFF_charstring_name':name,'CFF_physical_charset_index':font.charset.index(name),
                            'pdf_declared_width_1000_units':width,'font_advance_units':advance,'outline_bounds_font_units':bounds,
                            'normalized_outline_and_advance_sha256':shape,'CTM':ctm[:],'text_matrix':tm[:],
                            'effective_matrix':matrix,'text_font_size':size,'horizontal_scale':horizontal,'text_rise':rise,
                            'predicted_origin':origin,'x_scale_pt_per_font_unit':xlen/model['units'],'y_scale_pt_per_font_unit':ylen/model['units'],
                            'ExtGState_records':list(states),'source_unicode_font_cmap_status':'unknown_not_used'})
                tm=_mul(tm,[1.,0.,0.,1.,(width*size/1000+tc+(tw if length==1 and code==b' ' else 0))*horizontal,0.])
        for index,(args,op) in enumerate(self._ops):
            arity={b'q':0,b'Q':0,b'cm':6,b'BT':0,b'ET':0,b'Tf':2,b'Tm':6,b'Td':2,b'TD':2,
                   b'T*':0,b'Tz':1,b'Ts':1,b'TL':1,b'Tc':1,b'Tw':1,b'Tr':1,b'Tj':1,b'TJ':1,b'gs':1}
            if op in arity and len(args)!=arity[op]:raise ValueError('paint_content_operator_arity_invalid')
            if op in (b'Tm',b'Td',b'TD',b'T*',b'Tj',b'TJ') and not inside:raise ValueError('paint_text_operator_outside_BT')
            if op==b'q':
                if inside:raise ValueError('paint_nested_text_graphics_unsupported')
                stack.append((ctm[:],active,size,horizontal,rise,leading,tc,tw,render,list(states)))
            elif op==b'Q':
                if inside or not stack:raise ValueError('paint_graphics_stack_unsupported')
                ctm,active,size,horizontal,rise,leading,tc,tw,render,states=stack.pop()
            elif op==b'cm':ctm=_mul(ctm,list(map(float,args)))
            elif op==b'BT':
                if inside:raise ValueError('paint_nested_BT_unsupported')
                inside=True;tm=lm=identity[:]
            elif op==b'ET':
                if not inside:raise ValueError('paint_ET_outside_BT')
                inside=False;tm=lm=None
            elif op==b'Tf':active=str(args[0]).lstrip('/');size=float(args[1])
            elif op==b'Tm':tm=lm=list(map(float,args))
            elif op in (b'Td',b'TD'):
                if lm is None:raise ValueError('paint_text_position_unsupported')
                if op==b'TD':leading=-float(args[1])
                tm=lm=_mul(lm,[1.,0.,0.,1.,float(args[0]),float(args[1])])
            elif op==b'T*':tm=lm=_mul(lm,[1.,0.,0.,1.,0.,-leading])
            elif op==b'Tz':horizontal=float(args[0])/100
            elif op==b'Ts':rise=float(args[0])
            elif op==b'TL':leading=float(args[0])
            elif op==b'Tc':tc=float(args[0])
            elif op==b'Tw':tw=float(args[0])
            elif op==b'Tr':render=int(args[0])
            elif op==b'Tj':show(args[0],index,None)
            elif op==b'TJ':
                for part_index,part in enumerate(args[0]):
                    if isinstance(part,(int,float)):
                        if tm is not None:tm=_mul(tm,[1.,0.,0.,1.,-float(part)*size*horizontal/1000,0.])
                    else:show(part,index,part_index)
            elif op==b'gs':states.append({'operation_index':index,**metric_neutral_extgstate(self.document,self.page,args[0])})
            elif op in (b"'",b'"',b'Do',b'BDC'):
                raise ValueError('paint_content_operator_unsupported:'+op.decode())
        if inside or stack or len(matches)!=1:raise ValueError('paint_cluster_position_unproved_or_ambiguous')
        return matches[0]

    def resolve_unicode_expansion_cluster(self,negative):
        self._read()
        found=[i for i,g in enumerate(self._native) if g==negative]
        if len(found)!=1 or negative['gid']!=-1:raise ValueError('paint_negative_trace_identity_invalid')
        index=found[0];start,end,seqno=next(r for r in self._spans if r[0]<=index<r[1]);primary_index=index
        while primary_index>start and self._native[primary_index]['gid']<0:primary_index-=1
        last=primary_index+1
        while last<end and self._native[last]['gid']<0:last+=1
        indices=list(range(primary_index,last));members=self._native[primary_index:last];primary=members[0]
        if len(members)<2 or len(members)>16 or primary['gid']<0:raise ValueError('paint_complete_cluster_missing')
        if primary_index in self._proofs:return self._proofs[primary_index]
        for glyph in members[1:]:
            if (glyph['gid']!=-1 or any(glyph[k]!=primary[k] for k in ('font','size','origin','direction','color','opacity','type')) or
                glyph['bbox'][0]!=glyph['bbox'][2] or glyph['bbox'][0]!=primary['origin'][0] or
                glyph['bbox'][1]!=primary['bbox'][1] or glyph['bbox'][3]!=primary['bbox'][3]):raise ValueError('paint_expansion_trace_relationship_invalid')
        if primary['opacity']!=1 or primary['type']!=0:raise ValueError('paint_ligature_hidden_or_stroked_unsupported')
        digest,equivalent=self.engine._select(primary)
        if len(equivalent)!=1:raise ValueError('paint_font_file_identity_ambiguous')
        expansion=''.join(chr(g['unicode']) for g in members)
        proof=self._matches(primary,digest,expansion)
        proof.update(page_native_indices=indices,primary_page_native_index=primary_index,
                     actual_trace_members=members,span_seqno=seqno)
        proof['cluster_id']=hashlib.sha256(json.dumps(proof,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self._proofs[primary_index]=proof;return proof

    def describe_many(self,actual):
        if not isinstance(actual,list) or not actual or len(actual)>20000:raise ValueError('paint_actual_batch_budget')
        self._current_guard()
        records=[];proofs={}
        for glyph in actual:
            if glyph['gid']<0:
                proof=self.resolve_unicode_expansion_cluster(glyph);proofs[proof['cluster_id']]=proof
        if proofs:
            self._read();seen=[]
            for glyph in actual:
                matches=[i for i,g in enumerate(self._native) if g==glyph]
                if len(matches)!=1 or matches[0] in seen:raise ValueError('paint_actual_batch_identity_or_duplicate')
                seen.append(matches[0])
            for proof in proofs.values():
                if not set(proof['page_native_indices'])<=set(seen):raise ValueError('paint_complete_cluster_absent_from_batch')
        membership={json.dumps(g,sort_keys=True):proof for proof in proofs.values() for g in proof['actual_trace_members']}
        for glyph in actual:
            proof=membership.get(json.dumps(glyph,sort_keys=True))
            if proof is None:
                if glyph['gid']<0:raise ValueError('paint_negative_cluster_unproved')
                records.append(self.engine.describe(glyph));continue
            primary=proof['actual_trace_members'][0];record=self.engine.describe(primary)
            dx,dy=primary['direction'];nx,ny=-dy,dx;x,y=proof['predicted_origin']
            sx=proof['x_scale_pt_per_font_unit'];sy=proof['y_scale_pt_per_font_unit']
            x0,y0,x1,y1=proof['outline_bounds_font_units']
            points=[(x+dx*a*sx-nx*b*sy,y+dy*a*sx-ny*b*sy) for a,b in ((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
            ink=[min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]
            if abs(sx-sy)<1e-10 and max(abs(ink[i]-record['ink_bounds'][i]) for i in range(4))>.003:
                raise ValueError('paint_matrix_and_engine_ink_disagree')
            record.update(gid=glyph['gid'],primary_gid=primary['gid'],kind='shared_painted_ligature' if glyph['gid']<0 else 'painted_ligature_primary',
                independent_painted_glyph=glyph['gid']>=0,cluster_id=proof['cluster_id'],cluster_proof=proof,
                ink_bounds=ink,actual_matrix_ink_recomputed=True,
                actual_x_scale_pt_per_font_unit=proof['x_scale_pt_per_font_unit'],actual_y_scale_pt_per_font_unit=proof['y_scale_pt_per_font_unit'])
            records.append(record)
        return records
