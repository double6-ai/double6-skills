"""用原始页像素核定持续栏沟，然后分别识别列；不拆分已有OCR字符串。"""
from __future__ import annotations
from io import BytesIO
import hashlib
import statistics
from PIL import Image
import numpy as np

POLICY='source_pixel_gutter_column_recognition_v2'

def column_crop_plan(png: bytes, output: list) -> dict:
    image=Image.open(BytesIO(png)).convert('L');w,h=image.size
    if w*h>24000000 or len(output)>2000:raise ValueError('column_ocr_bounds')
    ink=np.asarray(image)<185
    rows=[];narrow=[]
    for item in output:
        if not isinstance(item,(list,tuple)) or len(item)<3:continue
        points=item[0]
        if not isinstance(points,(list,tuple)) or len(points)<4:continue
        xs=[float(p[0]) for p in points];ys=[float(p[1]) for p in points]
        x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
        if not 5<=y1-y0<=h*.04 or len(str(item[1]).strip())<12:continue
        r=(max(0,int(x0)),max(0,int(y0)),min(w,int(x1)+1),min(h,int(y1)+1))
        if x1-x0>=w*.5:rows.append(r)
        elif w*.16<=x1-x0<=w*.5:narrow.append(r)
    result={'policy':POLICY,'source_image_sha256':hashlib.sha256(png).hexdigest(),'status':'single_or_unresolved','candidate_wide_lines':len(rows),'crops':[]}
    left=[r for r in narrow if (r[0]+r[2])/2<=w*.45];right=[r for r in narrow if (r[0]+r[2])/2>=w*.55]
    if min(len(left),len(right))<4:return result
    median=statistics.median(r[3]-r[1] for r in left+right)
    ly0,ly1=min(r[1]for r in left),max(r[3]for r in left);ry0,ry1=min(r[1]for r in right),max(r[3]for r in right)
    overlap=max(0,min(ly1,ry1)-max(ly0,ry0));y0,y1=max(ly0,ry0),max(ly1,ry1)
    if y1-y0<median*3 or overlap/max(1,min(ly1-ly0,ry1-ry0))<.6:return result
    left_edge=float(np.quantile([r[2]for r in left if r[3]>=y0 and r[1]<=y1],.8))
    right_edge=float(np.quantile([r[0]for r in right if r[3]>=y0 and r[1]<=y1],.2))
    gap=right_edge-left_edge
    if not median*.20<=gap<=median*3.5:return result
    cut=int((left_edge+right_edge)/2);half=max(2,int(gap*.35))
    paired=sum(any(abs((l[1]+l[3]-r[1]-r[3])/2)<=median*1.5 for r in right)for l in left)
    if paired<4:return result
    # 将紧邻栏区的合并OCR行纳入；标题和其它远离栏区的通栏行仍独立。
    supported=[r for r in rows if r[1]<=y1+median*.75 and r[3]>=y0-median*.75]
    if supported:y0=min(y0,min(r[1]for r in supported));y1=max(y1,max(r[3]for r in supported))
    # 跨至少五行的连续窄组件才作为分隔线候选；短竖字形不能获豁免。
    import cv2
    sy0,sy1=int(y0),int(y1)
    full_strip=ink[sy0:sy1,cut-half:cut+half].astype(np.uint8)
    _,labels,stats,_=cv2.connectedComponentsWithStats(full_strip,8)
    separator_mask=np.zeros_like(ink,dtype=bool);separators=[]
    for label in range(1,len(stats)):
        x,y,cw,ch,area=stats[label]
        component=labels==label
        row_coverage=float(np.count_nonzero(component.any(axis=1))/ch)
        if cw<=max(2,int(median*.15)) and ch>=median*5 and row_coverage>=.9:
            separator_mask[sy0:sy1,cut-half:cut+half]|=component
            separators.append({'bbox':[int(cut-half+x),int(sy0+y),int(cut-half+x+cw),int(sy0+y+ch)],
                               'role':'persistent_narrow_vertical_separator_candidate',
                               'row_coverage':row_coverage,'height_in_median_lines':float(ch/median),
                               'width_px':int(cw),'source_pixels_preserved':True})
    # 弱扫描墨迹可有短断点；只核定同一长轴上的原像素组件，不补画或去字。
    axes=cv2.HoughLinesP(full_strip,1,np.pi/180,threshold=max(12,int(median*3)),
                        minLineLength=int(median*5),maxLineGap=max(1,int(median*.5)))
    for values in (axes if axes is not None else []):
        ax,ay,bx,by=map(int,values[0]);dy=by-ay
        if abs(dy)<median*5 or abs(bx-ax)>abs(dy)*.025:continue
        lo,hi=sorted((ay,by));band=max(2,int(median*.10));matched=[];axis_mask=np.zeros_like(labels,dtype=bool)
        for label in range(1,len(stats)):
            x,y,cw,ch,area=stats[label]
            if cw>max(2,int(median*.15)) or y>hi or y+ch<lo:continue
            yy,xx=np.where(labels==label)
            expected=ax+(yy-ay)*(bx-ax)/dy
            if np.max(np.abs(xx-expected))>band:continue
            inside=(yy>=lo)&(yy<=hi)
            axis_mask[yy[inside],xx[inside]]=True;matched.append((label,int(ch)))
        row_support=float(np.count_nonzero(axis_mask.any(axis=1))/max(1,hi-lo+1))
        # 重复短竖字形不会因上下对齐而变为分隔线。
        if row_support<.7 or max([ch for _,ch in matched]+[0])<median*3:continue
        new_pixels=axis_mask & ~separator_mask[sy0:sy1,cut-half:cut+half]
        if not new_pixels.any():continue
        separator_mask[sy0:sy1,cut-half:cut+half]|=axis_mask
        separators.append({'bbox':[int(cut-half+min(ax,bx)-band),int(sy0+lo),int(cut-half+max(ax,bx)+band+1),int(sy0+hi+1)],
                           'axis_px':[[int(cut-half+ax),int(sy0+ay)],[int(cut-half+bx),int(sy0+by)]],
                           'role':'persistent_broken_narrow_vertical_separator_candidate',
                           'row_coverage':row_support,'height_in_median_lines':float((hi-lo+1)/median),
                           'original_component_max_height_in_lines':float(max(ch for _,ch in matched)/median),
                           'source_pixels_preserved':True})
    checks=[]
    for r in supported:
        x0,by0,x1,by1=r
        strip=ink[by0:by1,cut-half:cut+half]
        analysis=(strip & ~separator_mask[by0:by1,cut-half:cut+half]).astype(np.uint8)
        excluded=[s for s in separators if s['bbox'][1]<by1 and s['bbox'][3]>by0]
        _,_,residual_stats,_=cv2.connectedComponentsWithStats(analysis,8)
        significant_residual=any(ch>=median*.3 and area>=median*.5 for _,_,_,ch,area in residual_stats[1:])
        gutter=float(analysis.mean())
        l=float(ink[by0:by1,x0:cut-half].mean());rr=float(ink[by0:by1,cut+half:x1].mean())
        checks.append({'bbox':list(r),'gutter_ink_ratio':gutter,'left_ink_ratio':l,'right_ink_ratio':rr,'separator_candidates':excluded,'significant_residual_ink':significant_residual})
        # 允许源栏沟中的细竖线，不能把普通通栏文字强拆成两列。
        if significant_residual or gutter>.15 or gutter>min(l,rr)*.6:
            return {**result,'status':'ambiguous_spanning_line','blocking_reason':'column_crop_intersects_spanning_text','gutter_checks':checks}
    result.update(left_column_lines=len(left),right_column_lines=len(right),paired_lines=paired,gutter_checks=checks,persistent_separator_candidates=separators)
    pad=max(3,int(median*.15));y0=max(0,y0-pad);y1=min(h,y1+pad)
    crops=[]
    if y0:crops.append({'kind':'top','column':None,'bbox':[0,0,w,y0]})
    crops.extend([{'kind':'body_left','column':0,'bbox':[0,y0,cut,y1]}, {'kind':'body_right','column':1,'bbox':[cut,y0,w,y1]}])
    if y1<h:crops.append({'kind':'bottom','column':None,'bbox':[0,y1,w,h]})
    return {**result,'status':'verified_simple_two_column','cut_px':cut,'gutter_half_width_px':half,'supported_wide_lines':len(supported),'median_line_height_px':median,'body_bbox':[0,y0,w,y1],'crops':crops,'independent_layout_acceptance':False}

def recognize_columns(png: bytes, output: list, engine):
    plan=column_crop_plan(png,output)
    if plan['status']!='verified_simple_two_column':return output,plan,[]
    image=Image.open(BytesIO(png)).convert('RGB');recognized=[];timings=[]
    for crop in plan['crops']:
        x0,y0,x1,y1=crop['bbox'];part=image.crop((x0,y0,x1,y1));buf=BytesIO();part.save(buf,format='PNG');payload=buf.getvalue()
        values,timing=engine(payload);timings.append(timing)
        crop['image_sha256']=hashlib.sha256(payload).hexdigest();crop['recognized_regions']=len(values or [])
        for item in values or []:
            if not isinstance(item,(list,tuple)) or len(item)<3:continue
            points=[[float(p[0])+x0,float(p[1])+y0] for p in item[0]]
            recognized.append([points,item[1],item[2],{'crop_bbox_px':crop['bbox'],'crop_image_sha256':crop['image_sha256'],'column':crop['column'],'kind':crop['kind'],'policy':POLICY}])
    if len(recognized)>2000:raise ValueError('column_ocr_output_bounds')
    plan['initial_ocr_regions']=len(output);plan['recognized_regions']=len(recognized)
    return recognized,plan,timings
