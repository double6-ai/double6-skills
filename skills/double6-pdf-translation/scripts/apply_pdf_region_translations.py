"""按冻结源图和有界区域写入译文；区域之外必须逐像素不变，输出仍待审。"""
from __future__ import annotations
from stable_page_raster import stable_get_pixmap
import argparse
import hashlib
import json
import math
import io
import re
from pathlib import Path
import unicodedata

import fitz
from PIL import Image, ImageChops, ImageDraw

DPI = 144
MAX_PAGES = 20
MAX_REGIONS = 100
MAX_PAGE_PIXELS = 16_000_000
ROLES = {'chart_title', 'table_header', 'table_label', 'comparison_connector', 'word_equation_term'}


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def crop_sha(page, rect) -> str:
    # 始终先按同一全页网格渲染再裁像素。MuPDF直接clip栅格图的采样
    # 可受先前整页/局部渲染影响，不可混用这两种采样结果作为身份。
    pix=stable_get_pixmap(page, matrix=fitz.Matrix(2,2), alpha=False)
    im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    box=(math.floor(rect.x0*2)-pix.x,math.floor(rect.y0*2)-pix.y,
         math.ceil(rect.x1*2)-pix.x,math.ceil(rect.y1*2)-pix.y)
    return hashlib.sha256(im.crop(box).tobytes()).hexdigest()


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text) if not c.isspace() and not unicodedata.category(c).startswith('C'))


def region_text(page, rect):
    # 字体的全局ascender/descender框可大于实际CJK墨迹；用可绘制字符的
    # 中心定位文字，另以栅格墨迹/区域外像素检查约束真实可见边界。
    values=[]
    for span in page.get_texttrace():
        if span.get('type') != 0 or span.get('opacity',1)<=0:
            continue
        for code, glyph, origin, bounds in span['chars']:
            box=fitz.Rect(bounds)
            if rect.contains(fitz.Point((box.x0+box.x1)/2,(box.y0+box.y1)/2)):
                values.append(chr(code))
    return ''.join(values)


def label_layout(region, font_path):
    rect=fitz.Rect(region['rect']);size=region['font_size'];lines=region['target_text'].splitlines()
    if len(lines)>10 or any(not line.strip() for line in lines):
        raise ValueError('label has unsupported blank/excessive lines')
    font=fitz.Font(fontfile=str(font_path))
    widths=[font.text_length(line,fontsize=size) for line in lines]
    if max(widths)>rect.width-.5:
        raise ValueError(f"region {region['id']} does not fit at declared readable size")
    if any(not font.has_glyph(ord(c)) for c in region['target_text'] if not c.isspace()):
        raise ValueError('font lacks required glyph')
    # 用真实字体先绘制到带留白的独立试排页，再按实际墨迹居中。
    points=[(20+(max(widths)-w)*region.get('align',0)/2,20+size+i*size*1.1) for i,w in enumerate(widths)]
    with fitz.open() as trial:
        page=trial.new_page(width=max(widths)+40,height=40+len(lines)*size*1.1)
        for point,line in zip(points,lines):page.insert_text(point,line,fontname='region-cjk',fontfile=str(font_path),fontsize=size)
        pix=stable_get_pixmap(page, matrix=fitz.Matrix(2,2),alpha=False)
        im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        box=ImageChops.difference(im,Image.new('RGB',im.size,'white')).getbbox()
    if box is None:raise ValueError('label rendered no ink')
    ink=fitz.Rect(*(v/2 for v in box))
    if ink.width>rect.width-.5 or ink.height>rect.height-.5:
        raise ValueError(f"region {region['id']} does not fit at declared readable size")
    dx=rect.x0+.25+(rect.width-.5-ink.width)*region.get('align',0)/2-ink.x0
    dy=rect.y0+(rect.height-ink.height)/2-ink.y0
    return [(x+dx,y+dy,line) for (x,y),line in zip(points,lines)]


def sampled_row_background(page, rect):
    """仅对两侧逐行颜色接近的空白背景插值；纹理、边线或边缘文字须拒绝。"""
    bounds=[v*2 for v in rect]
    if any(abs(v-round(v))>1e-6 for v in bounds):
        raise ValueError('sampled row background requires half-point grid')
    x0,y0,x1,y1=map(round,bounds)
    if x1-x0<4 or y1-y0<4:raise ValueError('sampled row background too small')
    pix=stable_get_pixmap(page, matrix=fitz.Matrix(2,2),alpha=False)
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    patch=Image.new('RGB',(x1-x0,y1-y0));pixels=patch.load()
    for y in range(y0,y1):
        left=image.getpixel((x0,y));right=image.getpixel((x1-1,y))
        if max(abs(a-b) for a,b in zip(left,right))>16:
            raise ValueError('sampled row background edges disagree')
        for x in range(x1-x0):
            t=x/(x1-x0-1)
            pixels[x,y-y0]=tuple(round(a*(1-t)+b*t) for a,b in zip(left,right))
    stream=io.BytesIO();patch.save(stream,format='PNG');return stream.getvalue()


def image_coverage_area(rect, images):
    """多个栅格文字行的覆盖面积取并集，重叠图片不能重复计数。"""
    boxes=[rect & fitz.Rect(image['bbox']) for image in images]
    boxes=[b for b in boxes if not b.is_empty]
    xs=sorted({x for b in boxes for x in (b.x0,b.x1)});area=0
    for left,right in zip(xs,xs[1:]):
        intervals=sorted((b.y0,b.y1) for b in boxes if b.x0<right and b.x1>left)
        end=None;height=0
        for lo,hi in intervals:
            height+=max(0,hi-max(lo,end if end is not None else lo));end=max(hi,end if end is not None else hi)
        area+=(right-left)*height
    return area


def repair_generated_unicode_cmap(data):
    """修正本脚本新建字体的非 BMP 标量；PDF 目标字符串须为 UTF-16BE。

    只改 MuPDF 生成的 5/6 位标量。范围改成显式数组，避免跨代理对
    边界时按十六进制字符串递增得到错误映射；既有合法映射原样保留。
    """
    repaired = 0
    def scalar(value):
        number = int(value, 16)
        if not 0x10000 <= number <= 0x10ffff:
            raise ValueError('invalid supplementary Unicode scalar in generated CMap')
        return chr(number).encode('utf-16-be').hex().upper()
    def block(match):
        nonlocal repaired
        kind = match.group(2)
        lines = match.group(3).splitlines()
        result = []
        for line in lines:
            pattern = (r'(\s*<[0-9a-fA-F]{4}>\s+)<([0-9a-fA-F]{5,6})>(\s*)' if kind == 'bfchar'
                       else r'(\s*<([0-9a-fA-F]{4})>\s+<([0-9a-fA-F]{4})>\s+)<([0-9a-fA-F]{5,6})>(\s*)')
            row = re.fullmatch(pattern, line)
            if row is None:
                result.append(line)
                continue
            if kind == 'bfchar':
                result.append(row.group(1) + '<' + scalar(row.group(2)) + '>' + row.group(3))
            else:
                start, end = int(row.group(2), 16), int(row.group(3), 16)
                if end < start:
                    raise ValueError('invalid generated CMap range')
                base = int(row.group(4), 16)
                values = ['<' + scalar(format(base + i, 'x')) + '>' for i in range(end-start+1)]
                result.append(row.group(1) + '[' + ' '.join(values) + ']' + row.group(5))
            repaired += 1
        return match.group(1) + '\n'.join(result) + match.group(4)
    text = data.decode('ascii')
    text = re.sub(r'(\d+ begin(bfchar|bfrange)\n)(.*?)(\nend\2)', block, text, flags=re.S)
    return text.encode('ascii'), repaired


def repair_owned_font_cmaps(doc):
    result = []
    seen = set()
    for page in doc:
        for font in page.get_fonts():
            if font[4] != 'region-cjk' or font[0] in seen:
                continue
            seen.add(font[0])
            kind, value = doc.xref_get_key(font[0], 'ToUnicode')
            if kind != 'xref':
                raise ValueError('generated region font lacks ToUnicode')
            xref = int(value.split()[0])
            old = doc.xref_stream(xref)
            new, count = repair_generated_unicode_cmap(old)
            if count:
                doc.update_stream(xref, new)
            result.append({'font_xref_before_save':font[0], 'repaired_mapping_rows':count})
    return result


def apply_plan(plan_path: Path, output_dir: Path) -> dict:
    if output_dir.exists():
        raise ValueError('output directory must be fresh')
    if plan_path.stat().st_size>2*1024**2:raise ValueError('plan size budget exceeded')
    implementation_sha=sha(Path(__file__))
    plan_sha=sha(plan_path)
    plan=json.loads(plan_path.read_text())
    if (plan.get('schema_version')!=1 or plan.get('dpi')!=DPI
            or plan.get('crop_sampling')!='full_page_144dpi_then_integer_pixel_crop'):
        raise ValueError('unsupported plan schema or crop DPI')
    paths={name:Path(plan[name]['path']).resolve() for name in ['source_pdf','base_pdf','font']}
    for name,path in paths.items():
        if sha(path)!=plan[name]['sha256']:
            raise ValueError(f'{name} identity mismatch')
    regions=plan.get('regions',[])
    if not 1<=len(regions)<=MAX_REGIONS:
        raise ValueError('region budget exceeded or empty')
    if len({r['id'] for r in regions})!=len(regions):
        raise ValueError('duplicate region id')
    before=fitz.open(paths['base_pdf']);source=fitz.open(paths['source_pdf'])
    previous_glyph_heights=fitz.TOOLS.set_small_glyph_heights()
    try:
        if type(plan.get('small_glyph_heights',False)) is not bool:
            raise ValueError('small glyph heights flag must be boolean')
        if plan.get('small_glyph_heights',False):fitz.TOOLS.set_small_glyph_heights(True)
        if len(before)!=len(source) or not 1<=len(before)<=MAX_PAGES:
            raise ValueError('page count or budget mismatch')
        by_page={};background_patches={};protected_patches={}
        for i in range(len(before)):
            if before[i].rect!=source[i].rect or before[i].rotation or source[i].rotation:
                raise ValueError('page geometry mismatch or unsupported page rotation')
            if math.ceil(before[i].rect.width*2)*math.ceil(before[i].rect.height*2)>MAX_PAGE_PIXELS:
                raise ValueError('page raster budget exceeded')
        for r in regions:
            if type(r['page']) is not int or not 1<=r['page']<=len(before) or r['role'] not in ROLES:
                raise ValueError('invalid page or region role')
            values=r['rect']
            if len(values)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
                raise ValueError('invalid region rectangle')
            rect=fitz.Rect(values);page=before[r['page']-1]
            if rect.is_empty or not page.rect.contains(rect):
                raise ValueError('region outside page or empty')
            if not 7.5<=r['font_size']<=24 or r.get('align',0) not in [0,1,2]:
                raise ValueError('font size or alignment outside contract')
            if not r.get('source_text','').strip() or not r.get('target_text','').strip() or len(r['target_text'])>300:
                raise ValueError('missing/oversized region text')
            if r.get('source_kind') not in ['pdf_text','embedded_image_label']:
                raise ValueError('source evidence kind missing')
            background = r.get('background', {'mode':'solid', 'rgb':[1,1,1]})
            if background.get('mode') not in {'solid','preserve_pdf_graphics','sampled_row_edges'}:
                raise ValueError('unsupported region background')
            if background['mode']=='preserve_pdf_graphics' and r['source_kind']!='pdf_text':
                raise ValueError('raster labels require solid background evidence')
            if background['mode']=='sampled_row_edges':
                background_patches[r['id']]=sampled_row_background(page,rect)
            for color in [r.get('text_rgb',[0,0,0])] + ([background.get('rgb')] if background['mode']=='solid' else []):
                if (not isinstance(color,list) or len(color)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in color)):
                    raise ValueError('invalid region color')
            if background['mode']=='solid' and background.get('rgb') != [1,1,1]:
                # 彩色填充必须有冻结的均匀边缘证据，不能推测背景颜色。
                pix=stable_get_pixmap(page, matrix=fitz.Matrix(2,2),alpha=False)
                image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                coords=[(math.ceil(rect.x0*2)+1,math.ceil(rect.y0*2)+1),
                        (math.floor(rect.x1*2)-2,math.ceil(rect.y0*2)+1),
                        (math.ceil(rect.x0*2)+1,math.floor(rect.y1*2)-2),
                        (math.floor(rect.x1*2)-2,math.floor(rect.y1*2)-2)]
                expected=tuple(round(v*255) for v in background['rgb'])
                if any(max(abs(a-b) for a,b in zip(image.getpixel(xy),expected))>2 for xy in coords):
                    raise ValueError('solid background corner evidence mismatch')
            if crop_sha(source[r['page']-1],rect)!=r['source_crop_sha256'] or crop_sha(page,rect)!=r['base_crop_sha256']:
                raise ValueError('source/base crop identity mismatch')
            if r['source_kind']=='embedded_image_label':
                images=source[r['page']-1].get_image_info()
                if image_coverage_area(rect,images)<rect.get_area()*.5:
                    raise ValueError('raster label lacks source image coverage')
            geometry=r.get('source_text_geometry','full_bbox')
            if geometry not in {'full_bbox','glyph_centers'}:
                raise ValueError('unknown source text geometry')
            actual=region_text(page,rect) if geometry=='glyph_centers' else page.get_text(clip=rect)
            if r['source_kind']=='pdf_text' and normalize(actual)!=normalize(r['source_text']):
                raise ValueError('base text region does not match frozen source label')
            for peer in by_page.get(r['page'],[]):
                if rect.intersects(fitz.Rect(peer['rect'])):
                    raise ValueError('overlapping approved regions')
            by_page.setdefault(r['page'],[]).append(r)
        protected=plan.get('protected_regions',[])
        if len({r['id'] for r in protected})!=len(protected):raise ValueError('duplicate protected region id')
        if len(protected)>MAX_REGIONS:
            raise ValueError('protected region budget exceeded')
        chart_pages={r['page'] for r in regions if r['role']=='chart_title'}
        if not chart_pages.issubset({r['page'] for r in protected}):
            raise ValueError('chart page requires explicit protected plot regions')
        equation_pages={r['page'] for r in regions if r['role']=='word_equation_term'}
        if not equation_pages.issubset({r['page'] for r in protected}):
            raise ValueError('word equation page requires explicit protected operator regions')
        for r in protected:
            if type(r['page']) is not int or not 1<=r['page']<=len(before):
                raise ValueError('invalid protected page')
            rect=fitz.Rect(r['rect'])
            if rect.is_empty or not all(math.isfinite(v) for v in rect) or not before[r['page']-1].rect.contains(rect):
                raise ValueError('invalid protected rectangle')
            if any(rect.intersects(fitz.Rect(x['rect'])) for x in by_page.get(r['page'],[])):
                raise ValueError('translation rectangle overlaps protected data')
            a=crop_sha(source[r['page']-1],rect);b=crop_sha(before[r['page']-1],rect)
            if a!=r['source_crop_sha256'] or b!=r['base_crop_sha256'] or a!=b:
                raise ValueError('protected plot differs from source')
            if r.get('restore_after_text_redaction'):
                if (r.get('restoration_role') not in {'source_code','math_expression'}
                        or any(abs(v*2-round(v*2))>1e-6 for v in rect)):
                    raise ValueError('protected restoration requires code/math and half-point grid')
                pix=stable_get_pixmap(source[r['page']-1], matrix=fitz.Matrix(2,2),alpha=False)
                image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                crop=image.crop(tuple(round(v*2) for v in rect));stream=io.BytesIO();crop.save(stream,format='PNG')
                protected_patches[r['id']]=stream.getvalue()
        layouts={r['id']:label_layout(r,paths['font']) for r in regions}
        output_dir.mkdir(parents=True,exist_ok=False)
        with fitz.open(paths['base_pdf']) as target:
            for n,items in by_page.items():
                page=target[n-1]
                # 全部移除旧文字后才写入新文字，防止后续redaction抹掉相邻译文。
                for r in items:page.add_redact_annot(fitz.Rect(r['rect']),fill=False,cross_out=False)
                page.apply_redactions(images=0,graphics=0,text=0)
                # 字体逻辑框可能侵入相邻代码；只恢复已声明且与译文框不重叠的源像素。
                for protected_region in protected:
                    if protected_region['page']==n and protected_region['id'] in protected_patches:
                        page.insert_image(fitz.Rect(protected_region['rect']),stream=protected_patches[protected_region['id']],overlay=True)
                for r in items:
                    # redact默认白框有1pt描边，会越过许可区域；自行仅填充。
                    background=r.get('background',{'mode':'solid','rgb':[1,1,1]})
                    if background['mode']=='solid':
                        page.draw_rect(fitz.Rect(r['rect']),color=None,fill=background['rgb'],width=0,overlay=True)
                    elif background['mode']=='sampled_row_edges':
                        page.insert_image(fitz.Rect(r['rect']),stream=background_patches[r['id']],overlay=True)
                    for x,y,line in layouts[r['id']]:
                        page.insert_text((x,y),line,fontname='region-cjk',fontfile=str(paths['font']),fontsize=r['font_size'],color=r.get('text_rgb',[0,0,0]),overlay=True)
            # 临时文件不能被误认为已验证的candidate；验证后才命名交付候选。
            temporary=output_dir/'unverified.pdf'
            font_mapping_repairs=repair_owned_font_cmaps(target)
            target.save(temporary,garbage=3,deflate=True)
        checks=[];outside=[];protected_checks=[]
        with fitz.open(temporary) as target:
            for i in range(len(before)):
                a=stable_get_pixmap(before[i], matrix=fitz.Matrix(2,2),alpha=False)
                b=stable_get_pixmap(target[i], matrix=fitz.Matrix(2,2),alpha=False)
                if (a.width,a.height)!=(b.width,b.height):raise ValueError('render dimensions changed')
                diff=ImageChops.difference(Image.frombytes('RGB',(a.width,a.height),a.samples),Image.frombytes('RGB',(b.width,b.height),b.samples))
                draw=ImageDraw.Draw(diff)
                for r in by_page.get(i+1,[]):
                    rect=fitz.Rect(r['rect']);draw.rectangle((math.floor(rect.x0*2),math.floor(rect.y0*2),math.ceil(rect.x1*2)-1,math.ceil(rect.y1*2)-1),fill=(0,0,0))
                    text=normalize(region_text(target[i],rect));ok=text==normalize(r['target_text'])
                    checks.append({'id':r['id'],'target_exact':ok,'font_size':r['font_size'],'output_crop_sha256':crop_sha(target[i],rect)})
                    if not ok:raise ValueError(f"final target mismatch: {r['id']}")
                box=diff.getbbox();outside.append({'page':i+1,'unchanged_outside_regions':box is None,'difference_bbox':box})
                if box is not None:raise ValueError(f'pixel changes outside approved regions on page {i+1}: {box}')
            for r in protected:
                current=crop_sha(target[r['page']-1],fitz.Rect(r['rect']))
                same=current==r['source_crop_sha256']
                protected_checks.append({'id':r['id'],'page':r['page'],'source_pixels_equal':same,'pixel_sha256':current})
                if not same:raise ValueError('protected plot changed during writeback')
        for name,path in paths.items():
            if sha(path)!=plan[name]['sha256']:raise ValueError('input changed during writeback')
        if sha(Path(__file__))!=implementation_sha:raise ValueError('implementation changed during writeback')
        if sha(plan_path)!=plan_sha:raise ValueError('plan changed during writeback')
        output=output_dir/'candidate.zh.mono.pdf';temporary.rename(output)
        result={'schema_version':1,'status':'candidate_needs_review','candidate_pdf':str(output.resolve()),'candidate_sha256':sha(output),'plan_sha256':plan_sha,'implementation_sha256':implementation_sha,'pymupdf_version':fitz.VersionBind,'inputs':plan|{'regions_count':len(regions)},'checks':checks,'outside_region_checks':outside,'protected_region_checks':protected_checks,'mechanical_region_writeback':'passed','semantic_acceptance':False,'visual_acceptance':False,'human_acceptance':False,'model_calls':0,'limitation':'Raster source labels remain inside preserved embedded images under the visible overlay. Target labels are real visible PDF text; pixel identity excludes only approved rectangles. Region source/translation decisions need review.'}
        result['font_mapping_repairs']=font_mapping_repairs
        (output_dir/'region_writeback_receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return result
    finally:
        fitz.TOOLS.set_small_glyph_heights(previous_glyph_heights)
        before.close();source.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('plan',type=Path);p.add_argument('--output-dir',required=True,type=Path);a=p.parse_args()
    r=apply_plan(a.plan,a.output_dir);print(json.dumps({'status':r['status'],'candidate_pdf':r['candidate_pdf'],'regions':len(r['checks'])},ensure_ascii=False))

if __name__=='__main__':main()
