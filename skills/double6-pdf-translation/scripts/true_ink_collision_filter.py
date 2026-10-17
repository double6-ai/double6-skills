"""碰撞片段先绑定成品原生字段，仅用实际嵌入字体排除度量框误报。"""
from collections import defaultdict
import fitz
from actual_ink_change_mask import native_key
from glyph_ink_geometry import EmbeddedGlyphInk
from native_line_spacing import glyphs


def _style(g):
    native_key(g)
    return (g['unicode'],g['gid'],g['font'],g['size'],tuple(g['color']),
            g['type'],tuple(g['direction']),g['opacity'])


def _bind_indexed(page,indexed):
    if len(indexed)>50000:raise ValueError('collision_indexed_glyph_limit')
    actual=glyphs(page)
    if len(actual)>50000:raise ValueError('collision_actual_glyph_limit')
    buckets=defaultdict(list)
    for i,g in enumerate(actual):buckets[_style(g)].append((i,g))
    saved=[];used=set()
    for uid,expected in indexed:
        matches=[(i,g) for i,g in buckets[_style(expected)] if i not in used and
            max(abs(x-y) for field in ('origin','bbox') for x,y in zip(expected[field],g[field]))<=.003]
        if not matches or len({native_key(g) for i,g in matches})!=1:
            raise ValueError('collision_indexed_glyph_not_actual_or_ambiguous')
        i,g=matches[0];used.add(i);saved.append((uid,g))
    return saved


def filter_metric_collisions(document,page,collisions,indexed):
    if len(collisions)>64:raise ValueError('true_ink_collision_candidate_limit')
    if not collisions:return [],[]
    actual=_bind_indexed(page,indexed)
    model=EmbeddedGlyphInk(document,page);remaining=[];cleared=[]
    for collision in collisions:
        left_ids=[i for i,(uid,g) in enumerate(indexed) if uid==collision['unit'] and chr(g['unicode'])==collision['chars'][0]]
        right_ids=[i for i,(uid,g) in enumerate(indexed) if uid==collision['other'] and chr(g['unicode'])==collision['chars'][1]]
        pairs=[(i,j) for i in left_ids for j in right_ids if max(abs(x-y) for x,y in
            zip(list(fitz.Rect(indexed[i][1]['bbox'])&fitz.Rect(indexed[j][1]['bbox'])),collision['overlap']))<.001]
        if len(pairs)!=1:raise ValueError('true_ink_collision_pair_identity_ambiguous')
        i,j=pairs[0];a,b=actual[i][1],actual[j][1]
        first,second=model.describe(a),model.describe(b)
        if first.get('ink_bounds') is None or second.get('ink_bounds') is None:
            raise ValueError('true_ink_collision_outline_missing')
        intersection=fitz.Rect(first['ink_bounds'])&fitz.Rect(second['ink_bounds'])
        if intersection.is_empty:
            cleared.append({'metric_collision':collision,'first_actual_native_glyph':a,'second_actual_native_glyph':b,
                'first_outline':first,'second_outline':second,'true_ink_bbox_intersection_area_pt2':0.,
                'actual_native_binding_verified':True,'binding_coordinate_tolerance_pt':.003,'bounding_ink_separated':True})
        else:remaining.append(collision)
    return remaining,cleared
