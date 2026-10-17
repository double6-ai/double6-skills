"""区域外像素检查：只从实际源/译字形建立有限的墨迹允许范围。

保留度量框检查结果。真实轮廓扩展只能解释具名字形的变化，不能授予保护接受。
"""
from stable_page_raster import stable_get_pixmap
from collections import Counter, defaultdict
import json
import math
import numpy as np


FIELDS = ('unicode', 'gid', 'font', 'size', 'color', 'type', 'direction',
          'opacity', 'origin', 'bbox')


def native_key(glyph):
    """包括 bbox、绘制状态和方向；不能仅凭字符/GID/原点复用造出的边界。"""
    values = {k: glyph[k] for k in FIELDS}
    if not isinstance(values['font'], str) or not values['font']:
        raise ValueError('native_glyph_font_identity_invalid')
    if isinstance(values['unicode'], int) and 0xD800 <= values['unicode'] <= 0xDFFF:
        raise ValueError('native_glyph_unicode_scalar_invalid')
    for k, counts in [('color', (1, 3)), ('direction', (2,)), ('origin', (2,)), ('bbox', (4,))]:
        v = values[k]
        if not isinstance(v, (list, tuple)) or len(v) not in counts or not all(
                isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in v):
            raise ValueError('native_glyph_geometry_invalid')
    if isinstance(values['size'], bool) or not isinstance(values['size'], (int, float)) or not math.isfinite(values['size']) or values['size'] <= 0:
        raise ValueError('native_glyph_size_invalid')
    for field in ('unicode', 'gid', 'type'):
        if not isinstance(values[field], int) or isinstance(values[field], bool):
            raise ValueError('native_glyph_identity_invalid')
    if (not 0 <= values['unicode'] <= 0x10ffff or values['gid'] < -1
            or not 0 <= values['type'] <= 3 or isinstance(values['opacity'], bool) or not isinstance(values['opacity'], (int, float))
            or not math.isfinite(values['opacity']) or not 0 <= values['opacity'] <= 1):
        raise ValueError('native_glyph_identity_invalid')
    b = values['bbox']
    if b[0] > b[2] or b[1] > b[3]:
        raise ValueError('native_glyph_bbox_invalid')
    return json.dumps(values, sort_keys=True, separators=(',', ':'))


def bind_source_ownership(actual_glyphs, owned, protected):
    """全页实际原生字段完整对应后，返回实际记录，不信任计划里的几何替身。"""
    if max(len(actual_glyphs), len(owned)+len(protected)) > 50000:
        raise ValueError('source_glyph_limit')
    actual = Counter(native_key(v) for v in actual_glyphs)
    owned_keys = Counter(native_key(v) for v in owned)
    protected_keys = Counter(native_key(v) for v in protected)
    if owned_keys+protected_keys != actual:
        raise ValueError('actual_source_ownership_mismatch')
    result = []
    for glyph in actual_glyphs:
        key = native_key(glyph)
        if owned_keys[key]:
            result.append(glyph)
            owned_keys[key] -= 1
    return result


def bind_saved_target(actual_glyphs, inserted, protected, *, coordinate_tolerance_pt=.003):
    """保存后按实际完整原生记录重绑插入/保护两类，仅允许声明的坐标误差。"""
    if not 0 <= coordinate_tolerance_pt <= .003 or max(len(actual_glyphs), len(inserted)+len(protected)) > 50000:
        raise ValueError('target_binding_limit')
    def style(g):
        native_key(g)
        return (g['unicode'], g['gid'], g['font'], g['size'], tuple(g['color']),
                g['type'], tuple(g['direction']), g['opacity'])
    buckets = defaultdict(list)
    for glyph in actual_glyphs:
        buckets[style(glyph)].append(glyph)
    result = []
    for expected, is_inserted in [(g, True) for g in inserted]+[(g, False) for g in protected]:
        bucket = buckets.get(style(expected), [])
        matches = [(i, g) for i, g in enumerate(bucket)
                   if max(abs(a-b) for field in ('origin', 'bbox')
                          for a, b in zip(expected[field], g[field])) <= coordinate_tolerance_pt]
        if not matches or len({native_key(g) for i, g in matches}) != 1:
            raise ValueError('saved_target_glyph_missing_or_ambiguous')
        i, glyph = matches[0]
        bucket.pop(i)
        if is_inserted:
            result.append(glyph)
    if any(buckets.values()):
        raise ValueError('saved_target_glyph_unowned')
    return result


def _boxes(glyphs, ink_model, page_size, *, maximum_outline_extension_pt=8.):
    if not 0 <= maximum_outline_extension_pt <= 32:
        raise ValueError('outline_extension_limit')
    boxes = []
    for index, glyph in enumerate(glyphs):
        native_key(glyph)
        box = ink_model.ink(glyph)
        if box is None:
            continue
        if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[0] > box[2] or box[1] > box[3]:
            raise ValueError('actual_ink_bounds_invalid')
        metric = glyph['bbox']
        extension = max(metric[0]-box[0], metric[1]-box[1], box[2]-metric[2], box[3]-metric[3], 0)
        if extension > maximum_outline_extension_pt:
            raise ValueError('actual_ink_extension_exceeds_bound')
        if (box[0] < -maximum_outline_extension_pt or box[1] < -maximum_outline_extension_pt
                or box[2] > page_size[0]+maximum_outline_extension_pt
                or box[3] > page_size[1]+maximum_outline_extension_pt):
            raise ValueError('actual_ink_outside_page_bound')
        boxes.append({'native_index_in_owned_list': index, 'native_glyph': glyph,
                      'ink_bbox': list(box), 'outline_extension_pt': extension})
    return boxes


def audit_changed_pixels(changed, source_owned, target_inserted, source_model, target_model,
                         *, page_size, pixels_per_pt=2., raster_margin_pt=1.):
    """在调用端独立取得并绑定实际源/译记录后计算 mask。

    target_inserted 必须来自保存后成品，保护字形不得加入允许 mask。
    源/译轮廓均从各自实际嵌入字体取得，不复用 producer 提交的投影 bounds。
    """
    if (not isinstance(changed, np.ndarray) or changed.dtype != np.bool_ or changed.ndim != 2
            or changed.size > 16000000 or len(source_owned)+len(target_inserted) > 50000):
        raise ValueError('pixel_or_glyph_limit')
    if (len(page_size) != 2 or not all(math.isfinite(v) and v > 0 for v in page_size)
            or not math.isfinite(pixels_per_pt) or not 1 <= pixels_per_pt <= 4
            or not math.isfinite(raster_margin_pt) or not 0 <= raster_margin_pt <= 1):
        raise ValueError('raster_parameters_invalid')
    if abs(changed.shape[1]-page_size[0]*pixels_per_pt) > 1 or abs(changed.shape[0]-page_size[1]*pixels_per_pt) > 1:
        raise ValueError('raster_page_geometry_mismatch')
    source_boxes = _boxes(source_owned, source_model, page_size)
    target_boxes = _boxes(target_inserted, target_model, page_size)
    metric_mask = np.zeros(changed.shape, dtype=bool)
    true_mask = np.zeros(changed.shape, dtype=bool)
    def paint(mask, box):
        # 与 MuPDF IRect 一致的向外取整；保持原1pt栅格缓冲上限。
        x0, y0 = (math.floor((box[i]-raster_margin_pt)*pixels_per_pt) for i in (0, 1))
        x1, y1 = (math.ceil((box[i]+raster_margin_pt)*pixels_per_pt) for i in (2, 3))
        x0, y0 = max(0, min(mask.shape[1], x0)), max(0, min(mask.shape[0], y0))
        x1, y1 = max(0, min(mask.shape[1], x1)), max(0, min(mask.shape[0], y1))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    for glyph in source_owned+target_inserted:
        paint(metric_mask, glyph['bbox'])
    true_mask |= metric_mask
    for row in source_boxes+target_boxes:
        paint(true_mask, row['ink_bbox'])
    old_outside = changed & ~metric_mask
    remaining = changed & ~true_mask
    return {'metric_outside_changed_pixels': int(np.count_nonzero(old_outside)),
            'true_ink_outside_changed_pixels': int(np.count_nonzero(remaining)),
            'metric_pixels_explained_by_true_ink': int(np.count_nonzero(old_outside & true_mask)),
            'outside_pixel_positions_yx': np.argwhere(remaining).tolist()[:100],
            'source_actual_true_ink': source_boxes, 'target_actual_true_ink': target_boxes,
            'pixels_per_pt': pixels_per_pt, 'raster_margin_pt': raster_margin_pt,
            'outside_change_check_pass': not np.any(remaining), 'quality_pass': False}


def audit_pdf_changed_pixels(source_document, source_page, target_document, target_page,
                             *, source_owned, source_protected, target_inserted, target_protected):
    """重开实际PDF后逐页调用；全原生归属绑定先于真实字体及有界像素检查。"""
    import fitz
    from native_line_spacing import glyphs
    from glyph_ink_geometry import EmbeddedGlyphInk
    before=source_document[source_page];after=target_document[target_page]
    if before.rect!=after.rect or before.rotation or after.rotation:
        raise ValueError('ink_change_same_unrotated_page_required')
    width,height=math.ceil(before.rect.width*2),math.ceil(before.rect.height*2)
    if min(width,height)<=0 or width*height>16000000:
        raise ValueError('ink_change_pixel_budget')
    owned=bind_source_ownership(glyphs(before),source_owned,source_protected)
    inserted=bind_saved_target(glyphs(after),target_inserted,target_protected)
    a=stable_get_pixmap(before, matrix=fitz.Matrix(2,2),alpha=False,colorspace=fitz.csRGB)
    b=stable_get_pixmap(after, matrix=fitz.Matrix(2,2),alpha=False,colorspace=fitz.csRGB)
    if (a.width,a.height)!=(b.width,b.height):raise ValueError('ink_change_raster_size_changed')
    changed=np.any(np.frombuffer(a.samples,np.uint8).reshape(a.height,a.width,3)!=
                   np.frombuffer(b.samples,np.uint8).reshape(b.height,b.width,3),axis=2)
    result=audit_changed_pixels(changed,owned,inserted,EmbeddedGlyphInk(source_document,before),
                              EmbeddedGlyphInk(target_document,after),page_size=[after.rect.width,after.rect.height])
    result.update(source_full_native_ownership_verified=True,saved_target_full_native_partition_verified=True,
                  actual_pdf_raster_compared=True,quality_pass=False,strict_delivery=False)
    return result
