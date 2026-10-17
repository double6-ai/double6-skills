# Double6 Skills 维护版本（2026-10-17）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""按小型填充节点与绘制顺序组合流程图文字；可见性仍需最终图审。"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from collections import defaultdict
from babeldoc.format.pdf.document_il import Box, PdfLine, PdfParagraphComposition
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string


def _inside(a, b, xpad=0):
    return a.x >= b.x-xpad and a.x2 <= b.x2+xpad and a.y >= b.y and a.y2 <= b.y2


def group_diagram_nodes(finder, page, paragraphs):
    # 只处理嵌入Form中的多个彩色/浅灰填充节点；普通正文、箭头与大底板不进入。
    nodes=[]
    for curve in page.pdf_curve:
        b=curve.box
        if not b or not curve.fill_background or curve.xobj_id in (None,-1,0):continue
        colors=re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) rg\b",getattr(curve.graphic_state,'passthrough_per_char_instruction','') or '')
        rgb=tuple(map(float,colors[-1])) if colors else ()
        if (not rgb or not .1 < min(rgb) < .99 or not 20 <= b.x2-b.x <= 160
                or not 15 <= b.y2-b.y <= 60 or curve.render_order is None):continue
        nodes.append({'curve':curve,'chars':[],'owners':[]})
    by_object=defaultdict(list)
    for n in nodes:by_object[n['curve'].xobj_id].append(n)
    by_object={k:v for k,v in by_object.items() if 3<=len(v)<=40}
    if not by_object:return []
    for p in paragraphs:
        candidates=by_object.get(p.xobj_id,[])
        if not candidates:continue
        for line in finder._paragraph_lines(p):
            for c in line.pdf_character:
                size=float(getattr(c.pdf_style,'font_size',0) or 0)
                if c.render_order is None or not c.visual_bbox or not 3<=size<=9 or c.vertical:continue
                possible=[n for n in candidates if n['curve'].render_order<c.render_order
                          and _inside(c.visual_bbox.box,n['curve'].box,size)]
                if possible:
                    n=max(possible,key=lambda n:n['curve'].render_order)
                    n['chars'].append(c);n['owners'].append(p)
    prepared=[]
    for ns in by_object.values():
        for n in ns:
            cs=n['chars'];letters=[c for c in cs if (c.char_unicode or '').strip()]
            if not letters or len(letters)>150 or not any((c.char_unicode or '').isalpha() for c in letters):continue
            label=unicodedata.normalize('NFKC',''.join(c.char_unicode or '' for c in cs))
            if not re.fullmatch(r"[A-Za-z0-9 +/&.,:()'’\-\s]+",label):continue
            hidden=[any(later['curve'].render_order>c.render_order and _inside(c.visual_bbox.box,later['curve'].box)
                        for later in ns) for c in letters]
            # 局部遮挡不猜测词义和删字；保留旧路径并由现有质量门处理。
            if any(hidden) and not all(hidden):continue
            n['hidden']=all(hidden);prepared.append(n)
    visible=[n for n in prepared if not n['hidden']]
    if len(visible)<3:return []
    removed=set();new=[];receipts=[]
    for n in prepared:
        cs=n['chars'];curve=n['curve'];p=copy.deepcopy(n['owners'][0]);p.debug_id=f'diagram-{curve.xobj_id}-{curve.render_order}'
        # 按原始行基线重新分组，不能把同一旧段落中的两张卡片拼成一个词。
        lines=[]
        for c in sorted(cs,key=lambda c:(-c.box.y,c.box.x)):
            line=next((line for line in lines if abs(line[0].box.y-c.box.y)<=.8),None)
            if line is None:lines.append([c])
            else:line.append(c)
        lines.sort(key=lambda line:-line[0].box.y)
        for line in lines:line.sort(key=lambda c:c.box.x)
        p.pdf_paragraph_composition=[PdfParagraphComposition(pdf_line=PdfLine(pdf_character=line)) for line in lines]
        p.layout_label='diagram_occluded_source' if n['hidden'] else 'diagram_node'
        finder.update_paragraph_data(p,update_unicode=True)
        p.first_line_indent=False
        p.unicode=' '.join(get_char_unicode_string(line).strip() for line in lines).strip()
        b=curve.box
        payload={'source':'filled_form_node_and_paint_order','curve_render_order':curve.render_order,
                 'node_bbox':[b.x,b.y,b.x2,b.y2],'layout_bbox':[b.x+2,b.y+2,b.x2-2,b.y2-2],
                 'source_text':p.unicode,'source_character_count':len(cs),
                 'visibility':'later_filled_bbox_covers_source_glyphs' if n['hidden'] else 'no_later_node_bbox_cover',
                 'visual_acceptance':False}
        p.diagram_node_json=json.dumps(payload,ensure_ascii=False)
        new.append(p);removed.update(id(c) for c in cs);receipts.append(payload|{'role':p.layout_label})
    if not removed:return []
    kept=[]
    for p in paragraphs:
        if not any(id(c) in removed for line in finder._paragraph_lines(p) for c in line.pdf_character):kept.append(p);continue
        comps=[]
        for comp in p.pdf_paragraph_composition:
            if comp.pdf_line:
                cs=[c for c in comp.pdf_line.pdf_character if id(c) not in removed]
                if any((c.char_unicode or '').strip() for c in cs):
                    comps.append(PdfParagraphComposition(pdf_line=PdfLine(pdf_character=cs)))
            else:comps.append(comp)
        if comps:
            p.pdf_paragraph_composition=comps;finder.update_paragraph_data(p,update_unicode=True);kept.append(p)
    paragraphs[:]=kept+new
    return receipts
