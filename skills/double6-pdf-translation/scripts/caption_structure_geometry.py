"""经核定的同一图注：同页并排源片段共用一条跨栏排版带。"""
import math

def caption_band(fragments, *, right_edge, lower_rule, clearance=2.):
    if not fragments or len(fragments)>4:raise ValueError('caption_fragment_bounds')
    if len({f['source_page']for f in fragments})!=1:raise ValueError('caption_cross_page_requires_adapter')
    boxes=[f['bbox']for f in fragments]
    if any(not all(math.isfinite(v)for v in b)or b[2]<=b[0]or b[3]<=b[1]for b in boxes):raise ValueError('caption_invalid_source_box')
    if len(boxes)>1:
        if max(f['source_baseline']for f in fragments)-min(f['source_baseline']for f in fragments)>2:raise ValueError('caption_nonparallel_source_fragments')
        if any(a[2]>b[0]+2 for a,b in zip(boxes,boxes[1:])):raise ValueError('caption_source_columns_overlap_or_reversed')
    x=min(b[0]for b in boxes);top=min(b[1]for b in boxes)-2
    wide=len(boxes)>1 or any(f.get('whole_width')for f in fragments)
    edge=right_edge if wide else min(right_edge,x+256.)
    bottom=lower_rule-clearance
    if edge<=x or bottom<=max(b[3]for b in boxes):raise ValueError('caption_rule_does_not_bound_band')
    return {'source_page':fragments[0]['source_page'],'column':0,'id':fragments[0]['id'],
            'source_fragment_id':fragments[0]['id'],'source_fragment_ids':[f['id']for f in fragments],
            'bbox':[x,top,edge,bottom],'first_baseline':fragments[0]['source_baseline'],
            'source_column_span':2 if wide else 1,'source_layout':'parallel_columns'if len(boxes)>1 else'full_width'if wide else'single_column',
            'target_layout':'one_spanning_band'if wide else'single_column','source_bboxes':boxes,'lower_rule_y':lower_rule,'clearance_pt':clearance}

def verify_caption_span(frame,placements, *, tolerance=.002):
    if len(placements)!=1:raise ValueError('caption_requires_one_band')
    p=placements[0]
    if p['source_page']!=frame['source_page']:raise ValueError('caption_page_changed')
    if any(abs(p['destination'][j]-frame['bbox'][j])>tolerance for j in (0,2)):raise ValueError('caption_target_span_changed')
    if p['destination'][1]<frame['bbox'][1]-tolerance or p['destination'][3]>frame['bbox'][3]+tolerance:raise ValueError('caption_band_overflow')
    return True
