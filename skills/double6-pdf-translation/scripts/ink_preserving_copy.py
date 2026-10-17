"""按嵌入字体轮廓复制具名文字片段；候选未安装，真实PDF运行待窗口释放。"""
from __future__ import annotations
import math

def _rect(value):
    if len(value)!=4 or any(type(v)not in (int,float)or not math.isfinite(v)for v in value):raise ValueError('ink_copy_finite_rect_required')
    x0,y0,x1,y1=map(float,value)
    if x0>=x1 or y0>=y1:raise ValueError('ink_copy_positive_rect_required')
    return x0,y0,x1,y1

def region_matrix(clip,destination,rotation=0,*,maximum_scale_error=.00001):
    """原复制变换必须保持尺寸；扩展后仍使用同一变换。"""
    x0,y0,x1,y1=_rect(clip);a0,b0,a1,b1=_rect(destination)
    if type(rotation)is not int or rotation%90:raise ValueError('ink_copy_right_angle_required')
    rotation%=360
    if type(maximum_scale_error)not in(int,float)or not math.isfinite(maximum_scale_error)or not 0<=maximum_scale_error<=.0001:raise ValueError('ink_copy_scale_tolerance_bound')
    sx=(b1-b0)/(x1-x0)if rotation in(90,270)else(a1-a0)/(x1-x0)
    sy=(a1-a0)/(y1-y0)if rotation in(90,270)else(b1-b0)/(y1-y0)
    if max(abs(sx-1),abs(sy-1))>maximum_scale_error:raise ValueError('ink_copy_scale_change_forbidden')
    if rotation==0:return sx,0.,0.,sy,a0-sx*x0,b0-sy*y0
    if rotation==90:return 0.,-sx,sy,0.,a0-sy*y0,b0+sx*x1
    if rotation==180:return -sx,0.,0.,-sy,a0+sx*x1,b0+sy*y1
    return 0.,sx,-sy,0.,a0+sy*y1,b0-sx*x0

def project_point(point,matrix):
    x,y=point;a,b,c,d,e,f=matrix;return x*a+y*c+e,x*b+y*d+f

def project_rect(rect,matrix):
    x0,y0,x1,y1=_rect(rect);points=[project_point(p,matrix)for p in[(x0,y0),(x0,y1),(x1,y0),(x1,y1)]]
    return[min(p[0]for p in points),min(p[1]for p in points),max(p[0]for p in points),max(p[1]for p in points)]

def expand_ink_region(clip,destination,ink_boxes,*,rotation=0,padding_pt=.5,maximum_bleed_pt=8.,page_rect=None):
    """仅改变裁区边界；目标边界由旧变换投影，禁止平移段首或缩放字形。"""
    if type(padding_pt)not in(int,float)or not math.isfinite(padding_pt)or not 0<=padding_pt<=2:raise ValueError('ink_copy_padding_bound')
    if type(maximum_bleed_pt)not in(int,float)or not math.isfinite(maximum_bleed_pt)or not .01<=maximum_bleed_pt<=32:raise ValueError('ink_copy_bleed_bound')
    if not ink_boxes or len(ink_boxes)>50000:raise ValueError('ink_copy_outline_scope_bound')
    original=_rect(clip);boxes=[_rect(v)for v in ink_boxes]
    expanded=[min(original[0],min(b[0]for b in boxes)-padding_pt),min(original[1],min(b[1]for b in boxes)-padding_pt),max(original[2],max(b[2]for b in boxes)+padding_pt),max(original[3],max(b[3]for b in boxes)+padding_pt)]
    bleed=[original[0]-expanded[0],original[1]-expanded[1],expanded[2]-original[2],expanded[3]-original[3]]
    if max(bleed)>maximum_bleed_pt:raise ValueError('ink_copy_true_outline_exceeds_declared_bleed')
    matrix=region_matrix(clip,destination,rotation);target=project_rect(expanded,matrix)
    if page_rect is not None:
        page=_rect(page_rect)
        if target[0]<page[0]or target[1]<page[1]or target[2]>page[2]or target[3]>page[3]:raise ValueError('ink_copy_expanded_destination_outside_page')
    return {'original_clip':list(original),'expanded_clip':expanded,'original_destination':list(destination),'expanded_destination':target,'original_matrix':list(matrix),'bleed_pt':bleed,'rotation':rotation%360,'glyph_scale_preserved':True,'baseline_preserved':True,'quality_pass':False}

def _style(c):
    return(c['unicode'],c['gid'],c['font'],round(c['size'],5),tuple(c['color']),c['type'],c['opacity'],tuple(c['direction']))

def copy_text_with_true_ink(page,document,index,clip,destination,*,rotation=0,padding_pt=.5,maximum_bleed_pt=8.,declared_font_aliases=()):
    """删除非本片段字符，扩展真实墨迹边界，核对原字形和坐标后再绘制。"""
    import fitz
    from glyph_ink_geometry import EmbeddedGlyphInk
    from native_line_spacing import glyphs
    original_clip=fitz.Rect(_rect(clip));region_matrix(clip,destination,rotation)
    source_page=document[index]
    if source_page.get_images(full=True):raise ValueError('ink_copy_raster_bank_requires_separate_review')
    if not (source_page.rect+(-.002,-.002,.002,.002)).contains(original_clip):raise ValueError('ink_copy_original_clip_outside_source')
    original_clip&=source_page.rect
    source=glyphs(source_page)
    if len(source)>50000:raise ValueError('ink_copy_character_limit')
    selected=[i for i,c in enumerate(source)if original_clip.contains(fitz.Point((c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2))]
    painting=[i for i in selected if not chr(source[i]['unicode']).isspace()]
    if not painting:raise ValueError('ink_copy_empty_text_fragment')
    if any(source[i]['type']!=0 or source[i]['opacity']!=1 for i in painting):raise ValueError('ink_copy_nonfill_or_translucent_text_requires_review')
    model=EmbeddedGlyphInk(document,source_page)
    for alias in declared_font_aliases:model.bind_declared_alias(alias['trace_name'],alias['postscript_name'],alias['font_sha256'])
    boxes=[model.ink(source[i])for i in painting];boxes=[b for b in boxes if b is not None]
    record=expand_ink_region(list(original_clip),destination,boxes,rotation=rotation,padding_pt=padding_pt,maximum_bleed_pt=maximum_bleed_pt,page_rect=list(page.rect))
    selected_set=set(selected);links=source_page.get_links();target_before=glyphs(page)
    roots_before={r[0] for r in page.get_xobjects() if r[2]==0}
    with fitz.open()as clean:
        clean.insert_pdf(document,from_page=index,to_page=index,links=False);cp=clean[0]
        before=glyphs(cp)
        if len(before)!=len(source)or any(_style(a)!=_style(b)or max(abs(a['origin'][j]-b['origin'][j])for j in(0,1))>.002 for a,b in zip(before,source)):raise ValueError('ink_copy_bank_copy_changed')
        pad=max(3.,max(record['bleed_pt'])+1)
        cp.set_mediabox(cp.mediabox+(-pad,-pad,pad,pad));after=glyphs(cp)
        if len(after)!=len(before)or any(_style(a)!=_style(b)for a,b in zip(before,after)):raise ValueError('ink_copy_mediabox_glyph_identity_changed')
        dx=after[0]['origin'][0]-before[0]['origin'][0];dy=after[0]['origin'][1]-before[0]['origin'][1]
        if any(max(abs(after[i]['origin'][j]-before[i]['origin'][j]-(dx,dy)[j])for j in(0,1))>.002 for i in range(len(before))):raise ValueError('ink_copy_nonuniform_mediabox_translation')
        shifted_clip=original_clip+(dx,dy,dx,dy);full=cp.rect
        for box in [fitz.Rect(0,0,full.width,shifted_clip.y0),fitz.Rect(0,shifted_clip.y1,full.width,full.height),fitz.Rect(0,shifted_clip.y0,shifted_clip.x0,shifted_clip.y1),fitz.Rect(shifted_clip.x1,shifted_clip.y0,full.width,shifted_clip.y1)]:
            if not box.is_empty:cp.add_redact_annot(box,fill=False)
        cp.apply_redactions(images=0,graphics=1,text=1);cp=clean.reload_page(cp)
        # 字符归属按原片段确定；墨迹扩展不能吞入邻行字符。
        kept=glyphs(cp)
        if len(kept)!=len(after):raise ValueError('ink_copy_graphics_cleanup_changed_text')
        for i,c in enumerate(kept):
            if i not in selected_set:
                x,y=(c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2
                cp.add_redact_annot(fitz.Rect(x-.02,y-.02,x+.02,y+.02),fill=False)
        cp.apply_redactions(images=0,graphics=0,text=0);cp=clean.reload_page(cp)
        cleaned=glyphs(cp);expected=[after[i]for i in selected if not chr(after[i]['unicode']).isspace()];actual=[c for c in cleaned if not chr(c['unicode']).isspace()]
        if len(expected)!=len(actual)or any(_style(a)!=_style(b)or max(abs(a['origin'][j]-b['origin'][j])for j in(0,1))>.002 for a,b in zip(expected,actual)):raise ValueError('ink_copy_selected_glyphs_changed')
        expanded=fitz.Rect(record['expanded_clip'])+(dx,dy,dx,dy)
        if not cp.rect.contains(expanded):raise ValueError('ink_copy_expanded_bank_region_unavailable')
        page.show_pdf_page(fitz.Rect(record['expanded_destination']),clean,0,clip=expanded,rotate=rotation%360,keep_proportion=False)
    expected_origins=[project_point(source[i]['origin'],record['original_matrix'])for i in painting]
    target_after=glyphs(page)
    if len(target_after)-len(target_before)!=len(cleaned):raise ValueError('ink_copy_target_glyph_count_changed')
    added=[c for c in target_after[len(target_before):]if not chr(c['unicode']).isspace()]
    if len(added)!=len(painting):raise ValueError('ink_copy_target_fragment_scope_changed')
    # MuPDF生成裁片包装矩阵的序列化可能引入统一的微小平移。
    # 只允许校正统一平移，所有字形最终仍逐项遵守原.003pt门。
    errors=[(want[0]-got['origin'][0],want[1]-got['origin'][1]) for want,got in zip(expected_origins,added)]
    correction=[sum(e[j] for e in errors)/len(errors) for j in (0,1)]
    residual=max(abs(e[j]-correction[j]) for e in errors for j in (0,1))
    record['wrapper_translation_correction_pt']=[0.,0.]
    if max(abs(v) for v in correction)>.0005:
        if max(abs(v) for v in correction)>.02 or residual>.0002:raise ValueError('ink_copy_nonuniform_or_large_transform_error')
        roots={r[0] for r in page.get_xobjects() if r[2]==0}-roots_before
        if len(roots)!=1:raise ValueError('ink_copy_wrapper_identity_ambiguous')
        root=next(iter(roots));kind,value=page.parent.xref_get_key(root,'Matrix')
        import re
        if kind!='array':raise ValueError('ink_copy_wrapper_matrix_missing')
        values=[float(v) for v in re.findall(r'[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?',value)]
        if len(values)!=6 or any(not math.isfinite(v) for v in values):raise ValueError('ink_copy_wrapper_matrix_invalid')
        inverse=~page.transformation_matrix;zero=fitz.Point(0,0)*inverse;delta=fitz.Point(*correction)*inverse
        values[4]+=delta.x-zero.x;values[5]+=delta.y-zero.y
        page.parent.xref_set_key(root,'Matrix','['+' '.join(f'{v:.12f}' for v in values)+']')
        target_after=glyphs(page)
        if len(target_after)-len(target_before)!=len(cleaned):raise ValueError('ink_copy_corrected_glyph_count_changed')
        added=[c for c in target_after[len(target_before):]if not chr(c['unicode']).isspace()]
        if len(added)!=len(painting):raise ValueError('ink_copy_corrected_fragment_scope_changed')
        record['wrapper_translation_correction_pt']=correction
        record['wrapper_translation_residual_pt']=residual
    maximum_error=0.
    for i,c,origin in zip(painting,added,expected_origins):
        before=source[i]
        if (c['unicode'],c['gid'],c['font'],tuple(c['color']))!=(before['unicode'],before['gid'],before['font'],tuple(before['color']))or abs(c['size']-before['size'])>.001:raise ValueError('ink_copy_target_style_changed')
        a,b,cc,d,_,_=record['original_matrix'];vx,vy=before['direction'];direction=(a*vx+cc*vy,b*vx+d*vy);length=math.hypot(*direction);direction=[v/length for v in direction]
        if c['type']!=before['type']or c['opacity']!=before['opacity']or max(abs(c['direction'][j]-direction[j])for j in(0,1))>.001:raise ValueError('ink_copy_target_direction_or_opacity_changed')
        error=max(abs(c['origin'][j]-origin[j])for j in(0,1));maximum_error=max(maximum_error,error)
        if error>.003:
            import json
            raise ValueError('ink_copy_target_origin_changed:'+json.dumps({'unicode':c['unicode'],'gid':c['gid'],'rotation':rotation,'error_pt':error,'expected_origin':origin,'actual_origin':c['origin'],'source_origin':before['origin'],'source_size':before['size'],'target_size':c['size'],'matrix':record['original_matrix'],'original_clip':record['original_clip'],'expanded_clip':record['expanded_clip'],'expanded_destination':record['expanded_destination'],'mediabox_shift':[dx,dy]},ensure_ascii=False))
    matrix=record['original_matrix']
    for link in links:
        own=link['from']&original_clip
        if link.get('uri')and not own.is_empty:page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(project_rect(list(own),matrix)),'uri':link['uri']})
    record.update(selected_nonspace_glyphs=len(painting),source_true_ink_boxes=boxes,projected_target_true_ink_boxes=[project_rect(b,record['original_matrix']) for b in boxes],maximum_origin_error_pt=maximum_error,mediabox_translation_pt=[dx,dy],actual_glyph_runtime_verified=True,actual_pixel_visibility_proved=False)
    return record
