"""图片封面的标题组与品牌/旋转数字保护；不依赖具体报告名称。"""
from __future__ import annotations
import copy
import re
import statistics


def prepare_cover_regions(regions: list[dict], *, page_width: float, page_height: float) -> list[dict]:
    titles, protected = [], []
    for item in regions:
        item = copy.deepcopy(item)
        x0,y0,x1,y1 = item['bbox']
        text = str(item.get('ocr_text') or '').strip()
        rotated = y1-y0 > (x1-x0)*1.5
        # 封面底部品牌文字、独立数字和竖排字段保持源图，不拼入标题。
        if y0 >= page_height*.45 or rotated or re.fullmatch(r'[\d\s.,/-]+',text) or item.get('layout_role') in {'image','chart','formula','equation'}:
            item.update(layout_role='illustration_text',translation_group_id=item['region_id'],
                        cover_policy='preserve_brand_or_numeric_or_rotated')
            protected.append(item)
        else:
            titles.append(item)
    if not titles:
        return protected
    titles.sort(key=lambda r:(r['bbox'][1],r['bbox'][0]))
    # 只合并相邻且左边缘一致的标题行；多栏/远隔标题保持独立。
    groups = []
    for item in titles:
        previous = groups[-1][-1] if groups else None
        if (previous and abs(item['bbox'][0]-previous['bbox'][0]) <= page_width*.08
            and 0 <= item['bbox'][1]-previous['bbox'][3] <= max(item['bbox'][3]-item['bbox'][1],previous['bbox'][3]-previous['bbox'][1])*1.3):
            groups[-1].append(item)
        else:
            groups.append([item])
    result=[]
    for group in groups:
        item=copy.deepcopy(group[0])
        boxes=[g['bbox'] for g in group]
        box=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
        lines=[]
        for g in group:
            lines.extend(g.get('source_fragments') or [g])
        text=' '.join(str(g.get('ocr_text') or '').strip() for g in group)
        item.update(bbox=box,polygon=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]],
                    ocr_text=text,normalized_text=text,paragraph_source_text=text,layout_role='cover_title',
                    translation_group_id=item['region_id'],source_line_evidence=copy.deepcopy(lines),
                    source_line_height=statistics.median(float(g['bbox'][3]-g['bbox'][1]) for g in lines),
                    cover_policy='adjacent_title_lines_with_source_boxes',render_surface='cover_title')
        result.append(item)
    return sorted(result+protected,key=lambda r:r['reading_order'])
