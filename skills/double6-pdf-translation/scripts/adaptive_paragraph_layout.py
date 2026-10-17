"""根据译文实测高度换栏/分页，完整段落及标题分隔线分别布局。"""
from __future__ import annotations
from typing import Any
import math


def vertical_heading_separators(page: Any, bbox: Any) -> list[dict]:
    """零宽竖线的Rect是empty，不能用Rect.intersects把它排除。"""
    import fitz
    box=fitz.Rect(bbox);result=[]
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]!='l':continue
            a,b=item[1:3]
            if abs(a.x-b.x)>.05 or not 3<=abs(a.y-b.y)<=24:continue
            ink=fitz.Rect(min(a.x,b.x),min(a.y,b.y),max(a.x,b.x),max(a.y,b.y))+(-.6,-.6,.6,.6)
            if not ink.intersects(box):continue
            result.append({'x':a.x,'y0':min(a.y,b.y),'y1':max(a.y,b.y),'width':drawing['width'],'color':drawing['color'],'source_empty_rect':drawing['rect'].is_empty})
    return result


def pack_whole_items(items: list[dict], frames: list[dict], *, gap: float=8., maximum_frames: int=20) -> list[dict]:
    """只拆换栏/页的位置；完整段落放不下当前框时整体换框，超大项拒绝。"""
    if not frames or len(frames)>maximum_frames:raise ValueError('frame_limit_or_missing')
    groups=[];i=0
    while i<len(items):
        group=[items[i]];i+=1
        if group[0].get('kind')=='heading' and i<len(items):group.append(items[i]);i+=1
        if i<len(items) and items[i].get('attach_previous'):group.append(items[i]);i+=1
        groups.append(group)
    placements=[];fi=0;y=frames[0]['bbox'][1]
    for group in groups:
        height=sum(x['height'] for x in group)+gap*(len(group)-1)
        while True:
            if fi>=len(frames):raise ValueError('declared_frames_exhausted')
            frame=frames[fi];box=frame['bbox'];before=gap if y>box[1]+.001 else 0.
            if y+before+height<=box[3]+.001:break
            fi+=1
            if fi<len(frames):y=frames[fi]['bbox'][1]
        y+=before
        for j,item in enumerate(group):
            if j:y+=gap
            frame=frames[fi];width=item['width'];x=frame['bbox'][0]+(frame['bbox'][2]-frame['bbox'][0]-width)/2 if item.get('center') else frame['bbox'][0]
            if item.get('align_right'):x=frame['bbox'][2]-width
            if x+width>frame['bbox'][2]+.01:raise ValueError('item_width_exceeds_frame')
            if item.get('native_clip'):
                # 原生图形的144dpi网格按半点平移，避免重排引入采样变化。
                origin=item['native_clip'];x=origin[0]+round((x-origin[0])*2)/2;y=origin[1]+round((y-origin[1])*2)/2
                if y+item['height']>frame['bbox'][3]+.25:raise ValueError('asset_grid_rounding_overflow')
            placements.append({**item,'frame_index':fi,'page':frame['page'],'column':frame['column'],'bbox':[x,y,x+width,y+item['height']],'paragraph_parts':1})
            y+=item['height']
    return placements


def pack_source_anchored_items(items: list[dict], frames: list[dict], *,
                               maximum_drift_pt: float=54., maximum_frames: int=20,
                               minimum_fragment_lines: int=2,
                               preserve_complete_source_page: bool=False) -> list[dict]:
    """优先源页/基线，必要时沿真实行间空隙跨页；逻辑段落与字号不变。"""
    if not frames or len(frames)>maximum_frames or not 0<=maximum_drift_pt<=100:
        raise ValueError('anchored_frame_or_drift_budget')
    if minimum_fragment_lines not in (1,2):raise ValueError('anchored_fragment_line_budget')
    if any(frames[i]['page']>=frames[i+1]['page']for i in range(len(frames)-1)):
        raise ValueError('anchored_single_column_frames_required')
    placements=[];fi=0;cursor=frames[0]['bbox'][1]
    for item in items:
        anchor=item.get('anchor',{});ap=anchor.get('page');ay=anchor.get('baseline_y')
        lines=item.get('line_records',[])
        if not isinstance(ap,int)or not isinstance(ay,(int,float))or not math.isfinite(ay)or not lines:
            raise ValueError('anchored_source_or_lines_missing')
        source_pages={o.get('source_page')for o in item.get('source_origins',[])}
        if preserve_complete_source_page and (not source_pages or
                any(not isinstance(p,int)or p<1 for p in source_pages)or min(source_pages)!=ap):
            raise ValueError('complete_source_page_evidence_missing')
        complete_source_paragraph=preserve_complete_source_page and len(source_pages)==1
        if item.get('fixed'):
            y=ay-lines[0]['baseline'];x=item.get('fixed_x',frames[0]['bbox'][0])
            placements.append({**item,'page':ap,'column':0,'bbox':[x,y,x+item['width'],y+item['height']],
                'bank_clip':[0,0,item['width'],item['height']],'paragraph_parts':1,
                'baseline_drift_pt':0.,'line_range':[0,len(lines)]})
            continue
        while fi<len(frames)and frames[fi]['page']<ap:
            fi+=1
            if fi<len(frames):cursor=frames[fi]['bbox'][1]
        start=0;parts=[]
        preferred=[]
        for boundary in item.get('preferred_page_breaks',[]):
            if len(lines)>1:
                stop=min(range(1,len(lines)),key=lambda k:abs(lines[k-1]['text_end_offset']-boundary['text_offset']))
                preferred.append((boundary['next_page'],stop))
        while start<len(lines):
            if fi>=len(frames):raise ValueError('anchored_declared_frames_exhausted')
            frame=frames[fi];box=frame['bbox'];clip_top=lines[start]['clip_top']
            if complete_source_paragraph and frame['page']!=ap:
                raise ValueError('complete_source_paragraph_page_changed')
            x=box[0]+float(item.get('x_offset_pt',0))
            if not math.isfinite(x)or x<box[0]-.001 or x+item['width']>box[2]+.001:
                raise ValueError('anchored_item_horizontal_bounds')
            desired=ay if start==0 and frame['page']==ap else box[1]+frame.get('baseline_offset',lines[start]['baseline']-clip_top)
            top=max(cursor,desired-(lines[start]['baseline']-clip_top))
            if start==0 and frame['page']==ap:
                drift=top+lines[0]['baseline']-ay
                if drift>maximum_drift_pt+.001:raise ValueError('anchored_drift_budget_exceeded')
            if item['width']>box[2]-box[0]+.001:raise ValueError('anchored_item_too_wide')
            end=start
            while end<len(lines)and top+lines[end].get('ink_bottom',lines[end]['clip_bottom'])+.25-clip_top<=box[3]+.001:end+=1
            for next_page,stop in preferred:
                if frame['page']<next_page and start<stop<end:end=stop
            if end<len(lines)and end-start<minimum_fragment_lines:
                end=start
            elif end<len(lines)and len(lines)-end==1 and end-start>2:
                end-=1
            if end==start:
                fi+=1
                if fi<len(frames):cursor=frames[fi]['bbox'][1]
                continue
            if complete_source_paragraph and end<len(lines):
                raise ValueError('complete_source_paragraph_would_split')
            clip_bottom=min(lines[end-1]['clip_bottom'],box[3]-top+clip_top)
            bottom=top+clip_bottom-clip_top
            parts.append({**item,'frame_index':fi,'page':frame['page'],'column':frame['column'],
                'bbox':[x,top,x+item['width'],bottom],
                'bank_clip':[0,clip_top,item['width'],clip_bottom],
                'line_range':[start,end],'baseline_drift_pt':top+lines[start]['baseline']-clip_top-ay if start==0 and frame['page']==ap else None})
            parts[-1]['source_page_delta']=frame['page']-ap if start==0 else None
            cursor=bottom;start=end
            if start<len(lines):
                fi+=1
                if fi<len(frames):cursor=frames[fi]['bbox'][1]
        for row in parts:row['paragraph_parts']=len(parts)
        placements.extend(parts)
    return placements
