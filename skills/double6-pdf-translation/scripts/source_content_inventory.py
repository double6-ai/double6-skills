"""逐页检查原生文字绘制记录归属；裁剪/遮挡/实际可见性须另审，不授予全页质量。"""
from __future__ import annotations
import hashlib
from pathlib import Path
import fitz
import unicodedata

def bind_native_line_glyphs(glyphs: list[dict], line: dict, *, tolerance_pt: float=.02) -> list[dict]:
    """绑定实际绘制字形；dict字号与trace字号在非等比文字矩阵下不能直接相等。

    以字体、印刷行法向基线和源span几何绑定，再核对完整可见文字；不准剩余普通字形落入保护兜底。
    """
    if not 0<tolerance_pt<=.1:raise ValueError('native_line_binding_tolerance')
    dx,dy=line['dir'];nx,ny=-dy,dx
    def anchored(c,s):
        if 'character_origins'in s:
            return any(abs(c['origin'][0]-p[0])<=tolerance_pt and abs(c['origin'][1]-p[1])<=tolerance_pt for p in s['character_origins'])
        return abs((c['origin'][0]-s['origin'][0])*nx+(c['origin'][1]-s['origin'][1])*ny)<=tolerance_pt
    def contains(c,s):
        x,y=(c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2
        x0,y0,x1,y1=s['bbox']
        # Combining scientific marks can have a zero-width actual span.
        return x0-tolerance_pt<=x<=x1+tolerance_pt and y0-tolerance_pt<=y<=y1+tolerance_pt
    result=[c for c in glyphs if any(c['font']==s['font'] and anchored(c,s) and contains(c,s)
        for s in line['spans'])]
    def normalized(v):return ''.join(unicodedata.normalize('NFKC',v).split())
    expected=normalized(''.join(s['text']for s in line['spans']))
    actual=normalized(''.join(c.get('native_logical_text',chr(c['unicode'])) for c in result))
    if expected!=actual:raise ValueError('native_line_glyph_text_incomplete:'+expected[:80]+':'+actual[:80])
    return result

def read_native_glyph_lines(page, *, unmapped_scientific_bindings=None) -> dict[tuple[int,int],list[dict]]:
    """实际源PDF的trace GID及rawdict字符位置；不重写源编码或判定翻译角色。"""
    traces=[]
    for span in page.get_texttrace():
        if span['type']==3:continue
        for char in span['chars']:
            traces.append({'unicode':char[0],'native_gid':char[1],
                'origin':list(char[2]),'bbox':list(char[3]),'font':span['font'],
                'size':span['size'],'direction':list(span['dir'])})
    for binding in unmapped_scientific_bindings or []:
        if binding.get('source_role')!='scientific_object':raise ValueError('ordinary unmapped Unicode forbidden')
        xref=binding['font_xref'];font_bytes=page.parent.extract_font(xref)[3]
        if hashlib.sha256(font_bytes).hexdigest()!=binding['font_program_sha256']:raise ValueError('scientific fontprogram changed')
        candidates=[c for c in traces if c['unicode']==65533 and c['native_gid']==binding['native_gid']
            and c['font']==binding['font_name'] and max(abs(c['origin'][i]-binding['origin'][i]) for i in (0,1))<=.02]
        if len(candidates)!=1:raise ValueError('unmapped scientific native glyph unknown/ambiguous')
        import freetype,io
        if freetype.Face(io.BytesIO(font_bytes)).get_glyph_name(binding['native_gid']).decode()!=binding['font_program_glyph_name']:
            raise ValueError('scientific physical glyph name changed')
        candidates[0]['native_logical_text']=binding['rawdict_logical_text']
        candidates[0]['unmapped_scientific_binding']=binding
    font_resources=[{'xref_id':row[0],'name':row[3],'font_id':row[4]}
                    for row in page.get_fonts(full=True)]
    result={}
    for bi,block in enumerate(page.get_text('rawdict')['blocks']):
        for li,line in enumerate(block.get('lines',[])):
            spans=[{**span,'text':''.join(c['c'] for c in span['chars']),
                    'character_origins':[list(c['origin']) for c in span['chars']]}
                   for span in line['spans']]
            text=''.join(s['text'] for s in spans)
            positions=[]
            for i,char in enumerate(text):
                positions.extend(i for c in unicodedata.normalize('NFKC',char) if not c.isspace())
            bound=bind_native_line_glyphs(traces,{**line,'spans':spans})
            records=[];cursor=0
            for char in bound:
                normal=''.join(unicodedata.normalize('NFKC',char.get('native_logical_text',chr(char['unicode']))).split())
                if not normal:continue
                offsets=positions[cursor:cursor+len(normal)]
                if len(offsets)!=len(normal):raise ValueError('native_glyph_offset_incomplete')
                records.append({**char,'native_character_range':[offsets[0],offsets[-1]+1],
                    'font_resources':[f for f in font_resources
                        if f['name'].split('+',1)[-1]==char['font']],
                    'source_page_height':float(page.rect.height)})
                cursor+=len(normal)
            if cursor!=len(positions):raise ValueError('native_glyph_offset_incomplete')
            result[(bi,li)]=records
    return result

def build_source_inventory(source: Path, assignments: list[dict], *, maximum_pages: int = 5,
                           maximum_glyphs: int = 150000, blank_bands: list[dict] | None = None) -> dict:
    if not 1 <= maximum_pages <= 500 or not 1 <= maximum_glyphs <= 2000000:
        raise ValueError('inventory_limit_invalid')
    source = Path(source)
    with source.open('rb') as f: digest = hashlib.file_digest(f, 'sha256').hexdigest()
    keys = [(r['page'], r['id']) for r in assignments]
    if len(set(keys)) != len(keys): raise ValueError('duplicate_assignment_ids')
    if any(r.get('role') not in {'translated','protected'} or not fitz.Rect(r['bbox']).is_valid or fitz.Rect(r['bbox']).is_empty for r in assignments):
        raise ValueError('assignment_role_or_geometry_invalid')
    glyphs=[]; uncovered=[]; duplicates=[]; assets=[]; pages=[]; nonpainting=[]
    with fitz.open(source) as doc:
        if len(doc) > maximum_pages: raise ValueError('inventory_page_limit')
        if any(not 1 <= r['page'] <= len(doc) for r in assignments): raise ValueError('assignment_page_outside_source')
        for i, pg in enumerate(doc):
            rows=[r for r in assignments if r['page']==i+1]
            count=0
            for span in pg.get_texttrace():
                kind=span['type']
                known_invisible=(kind==3 or kind==0 and span.get('opacity',span.get('fill_opacity',1))<=0
                                 or kind==1 and span.get('opacity',span.get('stroke_opacity',1))<=0)
                if known_invisible:
                    nonpainting.append({'page':i+1,'type':kind,'opacity':span.get('opacity'),
                                        'bbox':list(span['bbox']),'nonblank_characters':sum(not chr(c[0]).isspace()for c in span['chars'])})
                    continue
                for c in span['chars']:
                    text=chr(c[0])
                    if text.isspace(): continue
                    if len(glyphs) >= maximum_glyphs: raise ValueError('inventory_glyph_limit')
                    point=fitz.Point((c[3][0]+c[3][2])/2,(c[3][1]+c[3][3])/2)
                    owners=[r for r in rows if fitz.Rect(r['bbox']).contains(point)]
                    item={'page':i+1,'text':text,'bbox':list(c[3]),'origin':list(c[2]),
                          'font':span['font'],'size':span['size'],
                          'assignment_ids':[r['id'] for r in owners],'roles':[r['role'] for r in owners]}
                    glyphs.append(item);count+=1
                    if not owners: uncovered.append(item)
                    if len(owners)>1: duplicates.append(item)
            pages.append({'page':i+1,'native_trace_glyphs':count,'visibility_review_required':True,
                          'ocr_or_blank_page_review_required':count==0,'rect':list(pg.rect)})
            assets.extend({'page':i+1,'kind':'image','bbox':list(x['bbox']),
                           'review_status':'pending'} for x in pg.get_image_info())
            assets.extend({'page':i+1,'kind':'drawing','bbox':list(x['rect']),
                           'review_status':'pending'} for x in pg.get_drawings())
        bands=[]
        for r in blank_bands or []:
            if not 1 <= r['page'] <= len(doc) or not doc[r['page']-1].rect.contains(fitz.Rect(r['bbox'])):
                raise ValueError('blank_band_geometry_invalid')
            bands.append({**r,'review_status':'pending_source_and_target_geometry_review'})
    complete=bool(glyphs) and not uncovered and not duplicates
    return {'schema_version':2,'source':{'path':str(source),'sha256':digest},'pages':pages,
            'glyphs':glyphs,'uncovered_glyphs':uncovered,'duplicate_ownership':duplicates,
            'native_trace_ownership_complete':complete,'native_text_ownership_complete':complete,
            'native_text_ownership_complete_compatibility_meaning':'仅符合绘制记录筛选的文字归属，不证明实际可见',
            'known_nonpainting_text':nonpainting,'visibility_proven':False,
            'translation_coverage_complete':False,
            'translation_coverage_required':'独立核定自然语言角色、源行绑定、完整目标译文及最终PDF实际可见文字；保护归属不能豁免普通正文',
            'assets':assets,'blank_bands':bands,'full_page_quality_accepted':False,
            'scope':'原生文字绘制记录归属，排除已知透明/非绘制文字；clip/form/后绘制遮挡及实际可见性、扫描/OCR、图内字、图片/绘图、空白和语义均须独立复核'}
