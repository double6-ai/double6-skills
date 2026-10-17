"""从重新匹配的实际PDF字形计算印刷行、字号、墨迹和栏边界。"""
from __future__ import annotations
from collections import Counter,defaultdict
import math
from statistics import median

def measure_part_geometry(part, *, baseline_tolerance_pt=.025, explicit_space_positions=None):
    glyphs=part.get('glyphs',[])
    if not glyphs or not 0<baseline_tolerance_pt<=.05:raise ValueError('geometry_actual_glyphs_required')
    if any(not all(math.isfinite(v) for v in g['origin']+g['bbox']+[g['size']]) for g in glyphs):
        raise ValueError('geometry_actual_glyph_nonfinite')
    # 主字体按实际绘制记录的字号众数确定，脚注/上下标另行核对。
    size=Counter(round(g['size'],3) for g in glyphs).most_common(1)[0][0]
    main=[g for g in glyphs if abs(g['size']-size)<=.001]
    rows=[]
    for g in sorted(main,key=lambda c:(c['origin'][1],c['origin'][0])):
        if not rows or abs(g['origin'][1]-rows[-1]['baseline'])>baseline_tolerance_pt:
            rows.append({'baseline':g['origin'][1],'glyphs':[]})
        rows[-1]['glyphs'].append(g)
    attached=[[] for _ in rows]
    for g in glyphs:
        index=min(range(len(rows)),key=lambda i:abs(g['origin'][1]-rows[i]['baseline']))
        attached[index].append(g)
    lines=[]
    for index,row in enumerate(rows):
        gs=sorted(row['glyphs'],key=lambda g:g['origin'][0]);full=attached[index];cjk_steps=[]
        for a,b in zip(gs,gs[1:]):
            explicit_space=any(a['origin'][0]+.001<x<b['origin'][0]-.001 and abs(y-row['baseline'])<baseline_tolerance_pt for x,y in (explicit_space_positions or []))
            if 0x3400<=a['unicode']<=0x9fff and 0x3400<=b['unicode']<=0x9fff and a['font']==b['font'] and not explicit_space and not any(a['origin'][0]+.001<c['origin'][0]<b['origin'][0]-.001 for c in full if c not in gs):
                cjk_steps.append(b['origin'][0]-a['origin'][0])
        lines.append({'baseline':median(g['origin'][1] for g in gs),
            'origin_left':min(g['origin'][0] for g in gs),
            'ink_left':min(g['bbox'][0] for g in full),'ink_right':max(g['bbox'][2] for g in full),
            'cjk_advance_min_pt':min(cjk_steps) if cjk_steps else None,
            'cjk_advance_max_pt':max(cjk_steps) if cjk_steps else None,
            'cjk_advance_median_pt':median(cjk_steps) if cjk_steps else None})
    steps=[b['baseline']-a['baseline'] for a,b in zip(lines,lines[1:])]
    return {'id':part['id'],'page':part['page'],'part_index':part['part_index'],
            'font_size_pt':size,'line_count':len(lines),'lines':lines,'baseline_steps_pt':steps,
            'first_baseline':lines[0]['baseline'],
            'ink_bbox':[min(g['bbox'][0] for g in glyphs),min(g['bbox'][1] for g in glyphs),
                        max(g['bbox'][2] for g in glyphs),max(g['bbox'][3] for g in glyphs)],
            'measurement_source':'freshly_matched_actual_pdf_glyphs','explicit_space_exclusion_count':len(explicit_space_positions or []),
            'bbox_method':'native_painted_character_boxes; pixel_ink_requires_visual_review','quality_pass':False}

def measure_bank_transform(actual, bank_glyphs, *, bank_width, tolerance_pt=.003):
    """不可见排版框由冻结bank宽度和实际平移共同证明，不能仅信任声明destination。"""
    # 空格可被PDF编码为TJ位移，字形绑定清单也可能排除空白；完整可印刷字形仍须逐项一致。
    actual=[g for g in actual if not chr(g['unicode']).isspace()]
    bank_glyphs=[g for g in bank_glyphs if not chr(g['unicode']).isspace()]
    if len(actual)!=len(bank_glyphs) or not actual or not math.isfinite(bank_width) or bank_width<=0:
        raise ValueError('actual_bank_binding_incomplete')
    xs=[];ys=[]
    for a,b in zip(actual,bank_glyphs):
        if (a['unicode'],a['gid'],a['font'],round(a['size'],3))!=(b['unicode'],b['gid'],b['font'],round(b['size'],3)):
            raise ValueError('actual_bank_glyph_style_or_order_changed')
        xs.append(a['origin'][0]-b['origin'][0]);ys.append(a['origin'][1]-b['origin'][1])
    dx,dy=median(xs),median(ys)
    if max(abs(v-dx) for v in xs)>tolerance_pt or max(abs(v-dy) for v in ys)>tolerance_pt:
        raise ValueError('actual_bank_not_one_to_one_translation_or_shrunk')
    return {'frame_left':dx,'frame_right':dx+bank_width,'translation_y':dy,'fit_scale':1,
            'maximum_translation_error_pt':max(*(abs(v-dx) for v in xs),*(abs(v-dy) for v in ys))}

def audit_measured_class_spacing(policies, rows, *, required_part_ids):
    """统一参数逐实际行核验；两端对齐的实际字距作为分布记录。"""
    issues=[];pending=[];ids=[r['part_id'] for r in rows]
    if len(set(ids))!=len(ids) or set(ids)!=set(required_part_ids):
        pending.append({'rule':'measured_typography_complete_part_scope_required'})
    for row in rows:
        policy=policies.get(row['class']);g=row['geometry']
        if not policy:pending.append({'id':row['id'],'rule':'typography_class_without_policy'});continue
        if abs(g['font_size_pt']-policy['font_size_pt'])>policy['tolerance_pt']:
            issues.append({'id':row['id'],'rule':'same_class_typography_not_uniform','field':'font_size_pt'})
        if any(abs(v-policy['baseline_step_pt'])>policy['tolerance_pt'] for v in g['baseline_steps_pt']):
            issues.append({'id':row['id'],'rule':'same_class_typography_not_uniform','field':'baseline_step_pt'})
        left,right=row['frame_left'],row['frame_right']
        if g['ink_bbox'][0]<left-policy['edge_tolerance_pt'] or g['ink_bbox'][2]>right+policy['edge_tolerance_pt']:
            issues.append({'id':row['id'],'rule':'reading_region_overflow'})
        for index,line in enumerate(g['lines']):
            # 连续段落跨栏时，该栏末行可能仍为非段末行。
            last=row['line_offset']+index==row['complete_line_count']-1
            if row['alignment']=='justify' and not last and abs(line['ink_right']-right)>policy['right_ink_tolerance_pt']:
                issues.append({'id':row['id'],'rule':'actual_nonfinal_justified_line_endpoint'})
            if line['cjk_advance_max_pt'] is not None and line['cjk_advance_max_pt']>policy['maximum_cjk_advance_pt']:
                issues.append({'id':row['id'],'rule':'actual_character_spacing_exceeds_declared_limit'})
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,
            'measured_parts':len(rows),'quality_pass':False,
            'tracking_scope':'记录实际中文字形起点差；字号/行距统一，字距在声明两端对齐上限内逐行核验。'}
