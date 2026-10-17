"""从成品嵌入字体的真实轮廓测墨迹；trace度量框不一定包含大型数学字形。"""
from __future__ import annotations
import hashlib,json,math
from io import BytesIO
import fitz
from fontTools.ttLib import TTFont
from fontTools.cffLib import CFFFontSet
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen

def postscript_name(value):
    return value.split('+',1)[1]if '+'in value and len(value.split('+',1)[0])==6 else value

class EmbeddedGlyphInk:
    """支持TTF/OTF与原始CFF；PS身份歧义、复杂字体矩阵或无数据均阻断。"""
    def __init__(self,document,page,*,maximum_fonts=200,required_fonts=None,required_font_xrefs=None):
        self.required_fonts=None if required_fonts is None else frozenset(required_fonts)
        if self.required_fonts is not None and (not self.required_fonts or any(not isinstance(n,str)or not n for n in self.required_fonts)):
            raise ValueError('ink_required_font_scope_invalid')
        self.document=document;self.page=page;self.resources=page.get_fonts(full=True);self.zero_scales={};self.resource_digests={}
        self.required_font_xrefs=None if required_font_xrefs is None else frozenset(required_font_xrefs)
        if self.required_font_xrefs is not None and (not self.required_font_xrefs or any(type(n)is not int or n<=0 for n in self.required_font_xrefs)):
            raise ValueError('ink_required_font_xref_scope_invalid')
        self.excluded_resources=[]
        self.names={};self.fonts={};self.bounds={};self.chosen={};self.declared_aliases=[];refs={r[0]:r[3]for r in self.resources}
        if len(refs)>maximum_fonts:raise ValueError('ink_font_limit')
        if self.required_font_xrefs is not None and not self.required_font_xrefs<=set(refs):raise ValueError('ink_required_font_xref_missing')
        for xref,base in refs.items():
            if self.required_font_xrefs is not None and xref not in self.required_font_xrefs:
                self.excluded_resources.append({'xref':xref,'basefont':base,'reason':'outside_requested_xref_scope'})
                continue
            name,ext,kind,data=document.extract_font(xref)
            if not data:
                if self.required_fonts is None or postscript_name(base)in self.required_fonts:raise ValueError('ink_embedded_font_missing:'+base)
                self.excluded_resources.append({'xref':xref,'basefont':base,'reason':'outside_requested_font_scope_unembedded'})
                continue
            digest=hashlib.sha256(data).hexdigest();self.resource_digests[xref]=digest;aliases={postscript_name(base)}
            if digest not in self.fonts:
                if ext in('cff','cid'):
                    collection=CFFFontSet();collection.decompile(BytesIO(data),None);font=collection.topDictIndex[0]
                    matrix=font.FontMatrix
                    if matrix[0]<=0 or abs(matrix[0]-matrix[3])>1e-12 or any(abs(matrix[i])>1e-12 for i in(1,2,4,5)):raise ValueError('ink_font_matrix_unsupported')
                    model={'kind':'cff','font':font,'units':1/matrix[0],'names':set(postscript_name(n)for n in collection.fontNames)}
                else:
                    font=TTFont(BytesIO(data),lazy=True);model={'kind':'sfnt','font':font,'units':font['head'].unitsPerEm,
                        'names':{postscript_name(n.toUnicode())for n in font['name'].names if n.nameID==6}}
                self.fonts[digest]=model
            aliases|=self.fonts[digest]['names']
            if self.required_fonts is not None and not aliases&self.required_fonts:
                self.excluded_resources.append({'xref':xref,'basefont':base,'font_sha256':digest,'reason':'outside_requested_font_scope'})
                continue
            for alias in aliases:
                if self.required_fonts is None or alias in self.required_fonts:self.names.setdefault(alias,set()).add(digest)
        if self.required_fonts is not None:
            missing=self.required_fonts-set(self.names)
            if missing:raise ValueError('ink_required_font_identity_missing:'+','.join(sorted(missing)))

    def bind_declared_alias(self,trace_name,postscript_name,font_sha256):
        if self.required_fonts is not None and trace_name not in self.required_fonts:raise ValueError('ink_alias_outside_requested_font_scope')
        if font_sha256 not in self.names.get(postscript_name,set()):raise ValueError('ink_alias_font_identity_missing')
        if trace_name in self.names and self.names[trace_name]!={font_sha256}:raise ValueError('ink_alias_overlaps_existing_identity')
        self.names[trace_name]={font_sha256};self.declared_aliases.append({'trace_name':trace_name,'postscript_name':postscript_name,'font_sha256':font_sha256})

    def _glyph(self,digest,gid):
        key=(digest,gid)
        if key in self.bounds:return self.bounds[key]
        model=self.fonts[digest];font=model['font']
        if model['kind']=='cff':
            cid_name=f'cid{gid:05d}'
            if hasattr(font,'ROS'):
                if cid_name not in font.CharStrings.charStrings:
                    raise ValueError('ink_CID_charstring_namespace_missing')
                name=cid_name
            else:name=font.charset[gid]
            glyphs=font.CharStrings;char=glyphs[name];pen=BoundsPen(glyphs);char.draw(pen);advance=char.width
        else:
            name=font.getGlyphOrder()[gid]
            if 'glyph_set'not in model:model['glyph_set']=font.getGlyphSet()
            glyphs=model['glyph_set'];char=glyphs[name];pen=BoundsPen(glyphs);char.draw(pen);advance=font['hmtx'][name][0]
        recording=DecomposingRecordingPen(glyphs);char.draw(recording);u=model['units']
        def normalized(v):
            if isinstance(v,(tuple,list)):return[normalized(x)for x in v]
            return round(v/u,10)if isinstance(v,(float,int))else v
        shape=hashlib.sha256(json.dumps([normalized(recording.value),advance/u],separators=(',',':')).encode()).hexdigest()
        self.bounds[key]=(pen.bounds,advance,shape);return self.bounds[key]

    def _pdf_value(self,xref,key):
        """只读实际PDF的有限字体/变换值；不借字体 cmap 推导PDF字符码。"""
        from pypdf.generic import read_object,IndirectObject,ArrayObject,NullObject
        kind,raw=self.document.xref_get_key(xref,key)
        if kind=='null':return None
        value=read_object(BytesIO(raw.encode()+b'\n'),object())
        def resolve(v,active=frozenset()):
            if isinstance(v,IndirectObject):
                if v.generation or v.idnum in active or len(active)>=16:raise ValueError('ink_pdf_reference_unsupported')
                return resolve(read_object(BytesIO(self.document.xref_object(v.idnum).encode()+b'\n'),object()),active|{v.idnum})
            if isinstance(v,ArrayObject):return [resolve(x,active)for x in v]
            if isinstance(v,NullObject):return None
            if isinstance(v,(int,float)):return float(v)
            return str(v)
        return resolve(value)

    def _encoded_gid_width(self,xref,raw,digest):
        """仅接受有实际PDF编码/GID证据的单个首字形；未知编码保持阻断。"""
        model=self.fonts[digest];font=model['font'];subtype=self._pdf_value(xref,'Subtype')
        if subtype=='/Type0':
            if self._pdf_value(xref,'Encoding')!='/Identity-H' or len(raw)<2 or len(raw)%2:raise ValueError('ink_zero_advance_encoding_unsupported')
            cid=int.from_bytes(raw[:2],'big')
            kind,desc=self.document.xref_get_key(xref,'DescendantFonts')
            from pypdf.generic import read_object,IndirectObject
            children=read_object(BytesIO(desc.encode()+b'\n'),object())
            if len(children)!=1 or not isinstance(children[0],IndirectObject):raise ValueError('ink_zero_advance_descendant_unsupported')
            child=children[0].idnum;map_kind,map_raw=self.document.xref_get_key(child,'CIDToGIDMap')
            if map_kind=='xref':
                table=self.document.xref_stream(int(map_raw.split()[0]))
                if len(table)>2*65536 or cid*2+2>len(table):raise ValueError('ink_zero_advance_gid_map_missing')
                gid=int.from_bytes(table[cid*2:cid*2+2],'big')
            elif map_kind=='name' and map_raw=='/Identity':gid=cid
            # PDF Reference 1.6 表5.14：嵌入CIDFontType2缺省CIDToGIDMap为Identity。
            elif map_kind=='null' and self._pdf_value(child,'Subtype')=='/CIDFontType2' and model['kind']=='sfnt':gid=cid
            else:raise ValueError('ink_zero_advance_gid_map_unsupported')
            width=self._pdf_value(child,'DW');width=1000 if width is None else width
            widths=self._pdf_value(child,'W') or [];i=0
            while i<len(widths):
                start=int(widths[i]);second=widths[i+1]
                if isinstance(second,list):
                    if start<=cid<start+len(second):width=second[cid-start]
                    i+=2
                else:
                    end=int(second)
                    if start<=cid<=end:width=widths[i+2]
                    i+=3
            return gid,width,raw[:2].hex(),len(raw)==2
        if subtype=='/Type1' and self._pdf_value(xref,'Encoding') is not None:
            from pdf_glyph_paint_evidence import explicit_type1_gid_width
            return explicit_type1_gid_width(self,xref,raw,digest)
        if subtype!='/Type1' or model['kind']!='cff' or not raw:
            raise ValueError('ink_zero_advance_encoding_unsupported')
        encoding=font.Encoding
        if encoding=='StandardEncoding':
            from fontTools.encodings.StandardEncoding import StandardEncoding
            encoding=StandardEncoding
        if not isinstance(encoding,list):raise ValueError('ink_zero_advance_encoding_unsupported')
        code=raw[0];name=encoding[code]
        if name not in font.charset:raise ValueError('ink_zero_advance_encoded_gid_missing')
        widths=self._pdf_value(xref,'Widths');first=self._pdf_value(xref,'FirstChar')
        if not isinstance(widths,list) or first is None or not 0<=code-int(first)<len(widths):raise ValueError('ink_zero_advance_pdf_width_missing')
        return font.charset.index(name),widths[code-int(first)],raw[:1].hex(),len(raw)==1

    def _zero_advance_scale(self,c,digest):
        """零advance仍绘制轮廓；以实际字符码、PDF宽度及文本矩阵绑定横向缩放。

        当前只证明页面直接资源且可定位的show首字形。Form同字体、非正交
        变换、无法恢复的文本位置或编码均阻断，不用字号代替横向缩放证据。
        """
        key=(digest,c['gid'],tuple(c['origin']),c['size'],tuple(c.get('direction',[1.,0.])))
        if key in self.zero_scales:return self.zero_scales[key]
        from pypdf.generic import ContentStream,DecodedStreamObject
        page=self.page
        if not hasattr(page,'get_contents') or page.rotation or tuple(page.cropbox)!=tuple(page.mediabox) or page.mediabox.x0 or page.mediabox.y0:
            raise ValueError('ink_zero_advance_page_geometry_unsupported')
        direct={};forms=[]
        for r in self.resources:
            if r[0] not in self.resource_digests:
                data=self.document.extract_font(r[0])[3]
                self.resource_digests[r[0]]=hashlib.sha256(data).hexdigest() if data else None
            if self.resource_digests[r[0]]!=digest:continue
            if r[-1]!=0:forms.append(r[0])
            else:
                if r[4]in direct and direct[r[4]]!=r[0]:raise ValueError('ink_zero_advance_resource_ambiguous')
                direct[r[4]]=r[0]
        if forms or not direct:raise ValueError('ink_zero_advance_form_scope_unsupported')
        contents=b'\n'.join(self.document.xref_stream(x)for x in page.get_contents())
        if len(contents)>2*1024**2:raise ValueError('ink_zero_advance_content_budget')
        stream=DecodedStreamObject();stream.set_data(contents);ops=ContentStream(stream,None).operations
        if len(ops)>30000:raise ValueError('ink_zero_advance_operator_budget')
        def mul(a,b):
            return [a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]]
        identity=[1.,0.,0.,1.,0.,0.];ctm=identity[:];tm=lm=None;stack=[];inside=False
        font=None;size=0.;horizontal=1.;rise=leading=char_space=word_space=0.;found=[]
        def show(value):
            nonlocal tm
            raw=bytes(value) if isinstance(value,bytes) else getattr(value,'original_bytes',None)
            if raw is None:raise ValueError('ink_zero_advance_raw_show_unavailable')
            if tm is None or font not in direct:tm=None;return
            gid,width,code,single=self._encoded_gid_width(direct[font],raw,digest)
            matrix=mul(ctm,tm);u=self.fonts[digest]['units']
            if not all(math.isfinite(v)for v in [*matrix,size,horizontal,rise,width]):raise ValueError('ink_zero_advance_nonfinite_transform')
            origin=[matrix[4]+matrix[2]*rise,page.rect.height-matrix[5]-matrix[3]*rise]
            xvec=[matrix[0]*size*horizontal,-matrix[1]*size*horizontal];yvec=[-matrix[2]*size,matrix[3]*size]
            xlen=math.hypot(*xvec);ylen=math.hypot(*yvec)
            if gid==c['gid'] and max(abs(origin[i]-c['origin'][i])for i in(0,1))<.003:
                # PyMuPDF jm_trace_text_span 的 size 是变换后横向向量长度；
                # 非等比缩放时不能把它当作真实竖向字号。两轴均取实际PDF矩阵。
                if width!=0 or xlen<=0 or ylen<=0 or abs(xlen-c['size'])>.003 or abs(xvec[0]*yvec[0]+xvec[1]*yvec[1])>1e-5*xlen*ylen:
                    raise ValueError('ink_zero_advance_actual_transform_unsupported')
                direction=[xvec[0]/xlen,xvec[1]/xlen];normal=[-direction[1],direction[0]]
                if max(abs(direction[i]-c.get('direction',[1.,0.])[i])for i in(0,1))>.0001 or sum(normal[i]*yvec[i]for i in(0,1))<=0:
                    raise ValueError('ink_zero_advance_actual_direction_mismatch')
                found.append((xlen/u,ylen/u,{'source':'actual_pdf_code_width_text_matrix','font_resource_xref':direct[font],
                    'font_sha256':digest,'pdf_character_code_hex':code,'actual_gid':gid,'pdf_declared_width_1000_units':width,
                    'text_size_pt':size,'horizontal_scale':horizontal,'effective_pdf_text_matrix':matrix,'text_rise_pt':rise,
                    'page_xref':page.xref,'page_content_sha256':hashlib.sha256(contents).hexdigest()}))
            # 仅单个已核定零宽字符可以继续保留位置；其它show的后续位置保持未知。
            if single and width==0:tm=mul(tm,[1.,0.,0.,1.,char_space*horizontal,0.])
            else:tm=None
        for args,op in ops:
            if op==b'q':
                if inside:raise ValueError('ink_zero_advance_nested_text_graphics_unsupported')
                stack.append((ctm[:],font,size,horizontal,rise,leading,char_space,word_space))
            elif op==b'Q':
                if inside or not stack:raise ValueError('ink_zero_advance_graphics_stack_unsupported')
                ctm,font,size,horizontal,rise,leading,char_space,word_space=stack.pop()
            elif op==b'cm':ctm=mul(ctm,list(map(float,args)))
            elif op==b'BT':
                if inside or args:raise ValueError('ink_zero_advance_text_state_unsupported')
                inside=True;tm=lm=identity[:]
            elif op==b'ET':
                if not inside or args:raise ValueError('ink_zero_advance_text_state_unsupported')
                inside=False;tm=lm=None
            elif op==b'Tf':font=str(args[0]).lstrip('/');size=float(args[1])
            elif op==b'Tm':tm=lm=list(map(float,args))
            elif op in(b'Td',b'TD'):
                if lm is None:raise ValueError('ink_zero_advance_text_position_unsupported')
                if op==b'TD':leading=-float(args[1])
                tm=lm=mul(lm,[1.,0.,0.,1.,float(args[0]),float(args[1])])
            elif op==b'T*':tm=lm=mul(lm,[1.,0.,0.,1.,0.,-leading])
            elif op==b'Tz':horizontal=float(args[0])/100
            elif op==b'Ts':rise=float(args[0])
            elif op==b'TL':leading=float(args[0])
            elif op==b'Tc':char_space=float(args[0])
            elif op==b'Tw':word_space=float(args[0])
            elif op==b'Tj':show(args[0])
            elif op==b'TJ':
                for part in args[0]:
                    if isinstance(part,(int,float)):
                        if tm is not None:tm=mul(tm,[1.,0.,0.,1.,-float(part)*size*horizontal/1000,0.])
                    else:show(part)
            elif op==b'gs':
                from pdf_glyph_paint_evidence import metric_neutral_extgstate
                metric_neutral_extgstate(self.document,page,args[0])
            elif op in(b"'",b'"'):raise ValueError('ink_zero_advance_operator_unsupported')
        if inside or stack:raise ValueError('ink_zero_advance_unbalanced_content')
        if not found or len({(round(x,10),round(y,10))for x,y,_ in found})!=1:raise ValueError('ink_zero_advance_transform_unproved_or_ambiguous')
        self.zero_scales[key]=found[0];return found[0]

    def _select(self,c):
        key=(c['font'],c['gid'],c['unicode'],c.get('font_sha256'))
        if key in self.chosen:return self.chosen[key]
        choices=self.names.get(c['font'])
        if not choices:raise ValueError('ink_postscript_identity_missing:'+c['font'])
        if c.get('font_sha256') is not None:
            if c['font_sha256'] not in choices:raise ValueError('ink_requested_font_sha_missing')
            choices={c['font_sha256']}
        found=[]
        for digest in choices:
            try:found.append((digest,self._glyph(digest,c['gid'])))
            except IndexError:continue
        unicode_matches=[]
        for digest,value in found:
            model=self.fonts[digest]
            if model['kind']=='sfnt':
                # PDF ToUnicode 不等于字体 cmap；合法子集字体可仅保存 GID 和真实轮廓。
                # 没有 cmap 时保持实际 GID/嵌入字体身份依据，绝不补造 Unicode 映射。
                font=model['font'];cmap=font.getBestCmap() if 'cmap' in font else None
                name=(cmap or {}).get(c['unicode'])
                if name is not None and font.getGlyphID(name)==c['gid']:unicode_matches.append((digest,value))
        if unicode_matches:found=unicode_matches
        signatures={(tuple(round(x/self.fonts[h]['units'],10)for x in value[0])if value[0]is not None else None,round(value[1]/self.fonts[h]['units'],10))for h,value in found}
        if not found or len(signatures)!=1:raise ValueError('ink_font_glyph_bounds_ambiguous:'+c['font'])
        # 完整与精简字体的轮廓指令可不同；只在所有候选GID的真实极值和advance相同才授予边界等价。
        # 不声称字体文件或完整轮廓相同；碰撞使用保守边界，实际显示仍按原PDF/银行身份独立核验。
        digests=sorted(v[0]for v in found);self.chosen[key]=(digests[0],digests);return self.chosen[key]

    def ink(self,c):
        if c['gid']<0:
            raise ValueError('ink_negative_gid_requires_complete_painted_cluster_batch')
        digest,equivalent=self._select(c)
        key=(digest,c['gid']);model=self.fonts[digest];font=model['font']
        bounds,advance,shape=self.bounds[key]
        if bounds is None:return None
        dx,dy=c.get('direction',[1.,0.]);length=math.hypot(dx,dy)
        if abs(length-1)>.001 or advance<0:raise ValueError('ink_glyph_geometry_unsupported')
        dx/=length;dy/=length;nx,ny=-dy,dx;b=c['bbox']
        projections=[x*dx+y*dy for x,y in((b[0],b[1]),(b[0],b[3]),(b[2],b[1]),(b[2],b[3]))]
        if advance==0:sx,sy,_=self._zero_advance_scale(c,digest)
        else:
            sy=c['size']/model['units'];sx=(max(projections)-min(projections))/advance
            if not math.isfinite(sx) or sx<=0:raise ValueError('ink_glyph_geometry_unsupported')
        x0,y0,x1,y1=bounds;x,y=c['origin']
        points=[(x+dx*u*sx-nx*v*sy,y+dy*u*sx-ny*v*sy)for u,v in((x0,y0),(x0,y1),(x1,y0),(x1,y1))]
        return[min(p[0]for p in points),min(p[1]for p in points),max(p[0]for p in points),max(p[1]for p in points)]

    def describe(self,c):
        box=self.ink(c)
        if box is None:return{'font':c['font'],'gid':c['gid'],'ink_bounds':None,'nonpainting_outline':True}
        digest,equivalent=self._select(c);bounds,advance,shape=self.bounds[(digest,c['gid'])];model=self.fonts[digest]
        dx,dy=c.get('direction',[1.,0.]);b=c['bbox'];values=[x*dx+y*dy for x,y in((b[0],b[1]),(b[0],b[3]),(b[2],b[1]),(b[2],b[3]))]
        candidates=[{'font_sha256':h,'outline_bounds_font_units':self.bounds[(h,c['gid'])][0],'advance_font_units':self.bounds[(h,c['gid'])][1],'units_per_em':self.fonts[h]['units'],'normalized_outline_and_advance_sha256':self.bounds[(h,c['gid'])][2]}for h in equivalent]
        sx,sy,proof=self._zero_advance_scale(c,digest) if advance==0 else ((max(values)-min(values))/advance,c['size']/model['units'],None)
        unicode_evidence=[]
        for h in equivalent:
            m=self.fonts[h];f=m['font'];cmap=f.getBestCmap() if m['kind']=='sfnt' and 'cmap'in f else None
            name=(cmap or {}).get(c['unicode'])
            unicode_evidence.append({'font_sha256':h,'font_cmap_available':bool(cmap),
                'unicode_maps_to_actual_gid':f.getGlyphID(name)==c['gid'] if name is not None else None})
        return{'font':c['font'],'font_sha256':digest,'equivalent_ink_bounds_font_candidates':candidates,'font_file_identity_unique':len(equivalent)==1,'gid':c['gid'],'outline_bounds_font_units':bounds,'advance_font_units':advance,
            'units_per_em':model['units'],'actual_x_scale_pt_per_font_unit':sx,'actual_y_scale_pt_per_font_unit':sy,
            'actual_transform_evidence':proof,'font_unicode_cmap_evidence':unicode_evidence,
            'origin':c['origin'],'direction':[dx,dy],'ink_bounds':box}

    def describe_many(self,actual):
        """完整批次保留 trace GID；Unicode 续字共享真实 ligature 绘制证明。"""
        from pdf_glyph_paint_evidence import ActualPDFGlyphPaintEvidence
        if not hasattr(self,'paint_evidence'):
            self.paint_evidence=ActualPDFGlyphPaintEvidence(self)
        return self.paint_evidence.describe_many(actual)
