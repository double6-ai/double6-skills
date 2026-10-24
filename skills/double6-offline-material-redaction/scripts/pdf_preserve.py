"""PDF原生删改：保留未选区域的文字和页面；使用外部AGPL-3.0 PyMuPDF引擎。"""
import io
import math
from collections import Counter

from PIL import Image, ImageChops, ImageStat
import engine


def backend():
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise engine.Rejected('缺少PDF原生处理依赖，请重新执行安装和验收。') from exc
    fitz.TOOLS.set_small_glyph_heights(True)
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    return fitz


def open_pdf(data, inspect_image_visibility=True):
    fitz = backend()
    try:
        doc = fitz.open(stream=data, filetype='pdf')
        if doc.is_encrypted or doc.needs_pass or doc.is_repaired:
            raise engine.Rejected('加密或需要修复的PDF不进入原生脱敏。')
        if doc.get_ocgs():
            raise engine.Rejected('PDF含可选图层，无法确认全部隐藏内容；原生路线停止。')
        if any(page.rotation and page.cropbox != page.mediabox for page in doc):
            raise engine.Rejected('PDF同时含裁剪框和旋转，当前原生坐标尚未验证，已停止；不自动图像化。')
        if any(page.first_widget for page in doc):
            raise engine.Rejected('PDF含表单/签名域，原生路线暂不安全处理；请明确选择图像化副本或先处理表单。')
        if inspect_image_visibility:
            import pdf_visibility
            for page in doc:
                pdf_visibility.validate(page)
                images=page.get_image_info(xrefs=True)
                if not images:continue
                if any(not image.get('xref')or image.get('has-mask')for image in images):
                    raise engine.Rejected('PDF含行内图片或图片遮罩，隐藏像素尚不能安全清理，原生路线停止。')
                # 原图中被裁剪、透明或后来遮盖的像素不应随新容器交付。
                bounds=_content_bounds(page)
                if any(not bounds.contains(fitz.Rect(image['bbox'])) for image in images):
                    raise engine.Rejected('PDF图片超出可见页面，可能保留隐藏像素，原生路线停止。')
                if any(row[1] for row in page.get_images(full=True)):
                    raise engine.Rejected('PDF图片含透明遮罩，隐藏像素尚不能安全清理，原生路线停止。')
                bboxlog=page.get_bboxlog()
                for seq,(kind,bbox)in enumerate(bboxlog):
                    if kind!='fill-image':continue
                    rect=fitz.Rect(bbox)
                    if any(other_kind in {'fill-path','stroke-path','fill-image','fill-text','stroke-text'} and fitz.Rect(other).intersects(rect)for other_kind,other in bboxlog[seq+1:]):
                        raise engine.Rejected('PDF图片被后绘制对象遮住，可能保留隐藏像素，原生路线停止。')
        return doc
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF原生结构无法安全读取。') from exc


def areas(plan, sizes):
    import formats
    return formats.pdf_boxes(plan, sizes)


def _annots_array(page):
    """页面 /Annots 的原文。PyMuPDF 不列出的链接和弹出框也在这里。"""
    kind, value = page.parent.xref_get_key(page.xref, 'Annots')
    if kind == 'null' or value in ('null', '[]', ''):
        return ''
    return value


def _xref_numbers(value):
    numbers = []
    tokens = value.replace('[', ' ').replace(']', ' ').split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isdigit() and index + 2 < len(tokens) and tokens[index + 1].isdigit() and tokens[index + 2] == 'R':
            numbers.append(int(token))
            index += 3
            continue
        index += 1
    return numbers


def without_annotation_appearance(data):
    """删掉批注和链接后再按与正式导出相同的新容器重绘。

    只在原件确有批注、链接或 /Annots 数组时返回字节。框外复检拿它当基准，这样批注图标消失不算正文被改；没有批注时仍直接对比原页面，避免放宽其它框外差异。
    PyMuPDF 枚举不到的链接和弹出框也从数组里去掉，否则基准仍带着外观，正式导出却把外观删了。
    """
    fitz = backend()
    with open_pdf(data) as doc:
        changed = False
        for page in doc:
            annotations = list(page.annots() or [])
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in annotations):
                raise engine.Rejected('PDF已有未应用的涂黑标记，请先在原软件完成或移除后再检查。')
            links = list(page.get_links())
            if annotations or links or _annots_array(page):
                changed = True
            for annot in annotations:
                page.delete_annot(annot)
            for link in links:
                page.delete_link(link)
            if _annots_array(page):
                page.parent.xref_set_key(page.xref, 'Annots', 'null')
        if not changed:
            return None
        fresh = fitz.open()
        fresh.insert_pdf(doc, links=False, annots=False, widgets=False)
        fresh.set_metadata({})
        output = fresh.tobytes(garbage=4, clean=True, deflate=True, no_new_id=True)
        fresh.close()
        return output


def _pixel_scale(page, pixel_size):
    """预览像素相对于页面显示矩形的比例。旋转、裁剪框和 UserUnit 都体现在这两个尺寸里。"""
    width = float(page.rect.width)
    height = float(page.rect.height)
    if width <= 0 or height <= 0 or pixel_size[0] <= 0 or pixel_size[1] <= 0:
        raise engine.Rejected('PDF页面尺寸无法对应到预览。')
    return pixel_size[0] / width, pixel_size[1] / height


def _display_unit(page):
    """PyMuPDF 文字坐标相对 PDF 用户空间的倍数。

    page.rect 已经乘过 UserUnit。内置旋转矩阵的平移仍用未缩放的裁剪框宽高，两者不能直接相乘。
    """
    crop = page.cropbox
    cw = abs(float(crop.x1 - crop.x0))
    ch = abs(float(crop.y1 - crop.y0))
    if cw <= 0 or ch <= 0:
        raise engine.Rejected('PDF页面尺寸无法对应到预览。')
    if page.rotation in (90, 270):
        unit = float(page.rect.width) / ch
    else:
        unit = float(page.rect.width) / cw
    if unit <= 0:
        raise engine.Rejected('PDF页面尺寸无法对应到预览。')
    return unit


def _display_matrix(page):
    """未旋转的文字坐标转到预览上的显示矩形。平移按 UserUnit 放大，和 page.rect 同一单位。"""
    fitz = backend()
    unit = _display_unit(page)
    raw = page.rotation_matrix
    return fitz.Matrix(raw.a, raw.b, raw.c, raw.d, raw.e * unit, raw.f * unit)


def _text_matrix(page):
    """显示矩形回到未旋转文字坐标，是 _display_matrix 的逆。"""
    return ~_display_matrix(page)


def _content_bounds(page):
    """未旋转文字坐标里的可见页面。裁剪框偏移已经折进 page.rect，这里再乘上同一套反向旋转。"""
    fitz = backend()
    return fitz.Rect(page.rect) * _text_matrix(page)


def _annot_area_from_bound(bound, page):
    """和 annot.rect 同一坐标系的矩形，回到文字、涂黑使用的未旋转坐标。

    有 UserUnit 时，PyMuPDF 先用未缩放的反向旋转处理批注，得到的 rect 会偏到页面外。
    先乘回它的旋转，得到预览上的位置，再用含 UserUnit 的逆矩阵回到文字坐标。
    """
    fitz = backend()
    display = fitz.Rect(bound) * page.rotation_matrix
    return display * _text_matrix(page)


def _annot_area(annot, page):
    return _annot_area_from_bound(annot.rect, page)


def _bound_from_pdf_rect(page, pdf_rect):
    """PDF 用户空间的 /Rect 转到和 annot.rect 相同的坐标。"""
    fitz = backend()
    return fitz.Rect(pdf_rect) * page.transformation_matrix * page.derotation_matrix


def _to_page_rect(pixel_box, page, pixel_size):
    """框选像素转成涂黑用的页面坐标。先除掉渲染比例，再乘反向旋转。"""
    fitz = backend()
    sx, sy = _pixel_scale(page, pixel_size)
    rect = fitz.Rect(pixel_box[0] / sx, pixel_box[1] / sy, pixel_box[2] / sx, pixel_box[3] / sy)
    return rect * _text_matrix(page)


def _to_pixel_box(page_rect, page, image):
    """文字坐标里的矩形转成渲染像素。乘与涂黑相反的旋转，再乘同一渲染比例，取样盖到矩形外沿。"""
    fitz = backend()
    sx, sy = _pixel_scale(page, image.size)
    mapped = fitz.Rect(page_rect) * _display_matrix(page)
    mapped = fitz.Rect(mapped.x0 * sx, mapped.y0 * sy, mapped.x1 * sx, mapped.y1 * sy)
    if mapped.is_empty or mapped.is_infinite:
        return None
    x0 = max(0, math.floor(mapped.x0))
    y0 = max(0, math.floor(mapped.y0))
    x1 = min(image.width, math.ceil(mapped.x1))
    y1 = min(image.height, math.ceil(mapped.y1))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return (int(x0), int(y0), int(x1), int(y1))


def _luma(image, box):
    crop = image.crop(box).convert('L')
    low, high = crop.getextrema()
    return high - low, ImageStat.Stat(crop).mean[0]


def _aa_interior(box):
    """判断盖子本身是不是平色时，丢掉最外 2 像素抗锯齿。去盖后的页面仍按外沿整块取样。"""
    x0, y0, x1, y1 = box
    pad = 2 if x1 - x0 >= 8 and y1 - y0 >= 8 else 0
    if pad == 0:
        return box
    return (x0 + pad, y0 + pad, x1 - pad, y1 - pad)


def _counts_as_hidden(rect, area, selected):
    """落在批注里、且没有被框选盖住的对象，才算揭开后仍会留下的内容。"""
    if not rect.intersects(area):
        return False
    return not any(rect.intersects(sel) for sel in selected)


def _objects_under(page, area, selected):
    """去掉批注后的页面上，文字、矢量或图片是否落在这个矩形里。整页底色和已框选的对象不算。"""
    if page is None:
        return False
    fitz = backend()
    page_box = _content_bounds(page)
    if not page_box.intersects(area):
        return False
    for span in page.get_texttrace():
        for char in span['chars']:
            glyph = fitz.Rect(char[3])
            if chr(char[0]).strip() and _counts_as_hidden(glyph, area, selected):
                return True
    for image in page.get_image_info():
        if _counts_as_hidden(fitz.Rect(image['bbox']), area, selected):
            return True
    for drawing in page.get_drawings():
        bounds = fitz.Rect(drawing['rect'])
        if bounds.contains(page_box):
            continue
        if _counts_as_hidden(bounds, area, selected):
            return True
    return False


def _markup_types():
    """这些类型的自身墨迹可以消失，但只在渲染没有揭开原来看不见的内容时。名字本身不是放行理由。"""
    fitz = backend()
    return {
        fitz.PDF_ANNOT_TEXT,
        fitz.PDF_ANNOT_POPUP,
        fitz.PDF_ANNOT_LINK,
        fitz.PDF_ANNOT_HIGHLIGHT,
        fitz.PDF_ANNOT_UNDERLINE,
        fitz.PDF_ANNOT_SQUIGGLY,
        fitz.PDF_ANNOT_STRIKE_OUT,
    }


_MARKUP_NAMES = {'/Text', '/Popup', '/Link', '/Highlight', '/Underline', '/Squiggly', '/StrikeOut'}


def _appearance_hides(orig_span, orig_mean, base_span, base_mean):
    """这块外观去掉之后，有没有露出原来看不见的页面结构。

    底下本来是空白，或原来已经能读到字，都不算揭开。
    """
    if base_span < 8:
        return False
    if orig_span < 8:
        return True
    if abs(orig_mean - base_mean) >= 80 and min(orig_mean, base_mean) <= 40:
        return True
    return False


def _selection_covers(area, selected):
    """选区是否把这块批注整块框住。允许 1pt 的取整误差。"""
    target = backend().Rect(area)
    if target.is_empty or target.is_infinite:
        return False
    for sel in selected:
        if sel.x0 <= target.x0 + 1 and sel.y0 <= target.y0 + 1 and sel.x1 >= target.x1 - 1 and sel.y1 >= target.y1 - 1:
            return True
    return False


def _pdf_rect_values(value):
    tokens = value.replace('[', ' ').replace(']', ' ').split()
    if len(tokens) != 4:
        return None
    try:
        return tuple(float(token) for token in tokens)
    except ValueError:
        return None


def _areas_to_judge(page):
    """每条会被删掉的批注，连同 PyMuPDF 不列出的 /Annots。返回 (文字坐标矩形或 None, 是否为标记类)。"""
    seen = set()
    areas = []
    markup_types = _markup_types()
    for annot in page.annots() or []:
        seen.add(annot.xref)
        areas.append((_annot_area(annot, page), annot.type[0] in markup_types))
    raw = _annots_array(page)
    if not raw:
        return areas
    refs = _xref_numbers(raw)
    if not refs:
        areas.append((None, False))
        return areas
    doc = page.parent
    for xref in refs:
        if xref in seen:
            continue
        kind, subtype = doc.xref_get_key(xref, 'Subtype')
        markup = kind == 'name' and subtype in _MARKUP_NAMES
        rect_kind, rect_value = doc.xref_get_key(xref, 'Rect')
        pdf_rect = _pdf_rect_values(rect_value) if rect_kind == 'array' else None
        if pdf_rect is None:
            areas.append((None, markup))
            continue
        bound = _bound_from_pdf_rect(page, pdf_rect)
        areas.append((_annot_area_from_bound(bound, page), markup))
    return areas


def annotation_change_reason(page, baseline_page, pixel_boxes, original_image, baseline_image, darkening=None):
    """每条被删批注都做同一套去盖比较，不按类型整段跳过。

    返回 revealed、annot 或空字符串。比较两张渲染在批注外沿内的像素，并看去掉批注后的文字、矢量、图片是否落在矩形里。
    平色盖在平色空白上可以去掉。盖子底下只要去盖后多出任何深浅差别，或有对象落在矩形里，就拒绝。
    高亮、下划线、删除线、波浪线、便签、弹出框和链接的自身墨迹，只有在去掉后没有揭开原来看不见的内容时才可以消失。
    图章这类自身有可见内容的批注，选区把整块矩形框住、且矩形里没有未选中的对象时，可以去掉。
    选区先抹掉，避免把已经框住的正文算成露出。已经放行的批注矩形从变深图里抹掉，避免下划线本身的颜色被当成揭开的正文。
    """
    areas = _areas_to_judge(page)
    if not areas:
        return ''
    selected = [_to_page_rect(box, page, original_image.size) for box in pixel_boxes]
    outside = baseline_image.copy()
    for box in pixel_boxes:
        x0, y0, x1, y1 = (int(v) for v in box)
        span = (max(0, x0 - 2), max(0, y0 - 2), min(outside.width, x1 + 2), min(outside.height, y1 + 2))
        outside.paste((255, 255, 255), span)
    reason = ''
    cleared = []
    for area, markup in areas:
        box = None
        if area is None or area.is_empty or area.is_infinite:
            found = 'revealed'
        else:
            under = _objects_under(baseline_page, area, selected)
            box = _to_pixel_box(area, page, original_image)
            if box is None:
                found = 'revealed'
            else:
                _base_span, base_mean = _luma(baseline_image, box)
                outside_span, _outside_mean = _luma(outside, box)
                interior = _aa_interior(box)
                orig_span, orig_mean = _luma(original_image, interior)
                full_span, _full_mean = _luma(original_image, box)
                flat_cover = orig_span < 8
                if flat_cover and not under and outside_span == 0:
                    # 外圈不平和、内圈却与页面同色：描边或细线。实心色块内圈和页面颜色不同，可以去掉。
                    found = 'annot' if full_span >= 8 and abs(orig_mean - base_mean) < 8 else ''
                elif flat_cover and (under or outside_span >= 1):
                    found = 'revealed'
                elif not flat_cover:
                    found = 'annot'
                else:
                    found = ''
                if found == 'annot' and _selection_covers(area, selected) and not under:
                    found = ''
                elif found == 'annot' and markup:
                    base_inner_span, base_inner_mean = _luma(baseline_image, interior)
                    if _appearance_hides(orig_span, orig_mean, base_inner_span, base_inner_mean):
                        found = 'revealed'
                    else:
                        found = ''
        if found == '' and box is not None:
            cleared.append(box)
        if found == 'revealed':
            reason = 'revealed'
        elif found == 'annot' and reason != 'revealed':
            reason = 'annot'
    if darkening is not None and reason != 'revealed':
        for box in cleared:
            darkening.paste(0, box)
    return reason


def word_rows(page, boxes):
    fitz = backend()
    result = []
    for span in page.get_texttrace():
        for char in span['chars']:
            rect=fitz.Rect(char[3])
            if chr(char[0]).strip()and not any(rect.intersects(box)for box in boxes):
                result.append((char[0],*(round(x,1)for x in char[3])))
    return Counter(result)


def export(data, plan, _verify=True):
    import formats
    import pdf_visibility
    fitz = backend()
    plan=effective_plan(data,plan)
    sizes = formats.pdf_info(data)
    selected = areas(plan, sizes)
    try:
        with open_pdf(data) as doc:
            pdf_visibility.check_object_carriers(doc,clean=True)
            for index, page in enumerate(doc):
                # 注释中的附件/原词不移入正文；已存在的待应用涂黑标记不能直接删除。
                annotations = list(page.annots() or [])
                if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in annotations):
                    raise engine.Rejected('PDF已有未应用的涂黑标记，请先在原软件完成或移除后再检查。')
                for annot in annotations:
                    page.delete_annot(annot)
                for link in page.get_links():
                    page.delete_link(link)
                boxes = [_to_page_rect(box, page, sizes[index]) for box in selected.get(index + 1, [])]
                # 对不可见/半透明文字停止，避免把隐藏层变成普通可搜索正文。
                visible_bounds=_content_bounds(page)
                for span in page.get_texttrace():
                    if any(chr(char[0]).strip() and not visible_bounds.contains(fitz.Rect(char[3]))for char in span['chars']):
                        raise engine.Rejected('PDF文字超出可见页面或裁剪边界，存在隐藏原文，原生路线停止。')
                    if span.get('type') == 3 or span.get('opacity', 1) < .999 or span.get('size',1)<.5 or (isinstance(span.get('color'),tuple) and all(c>=.99 for c in span['color']) and not pdf_visibility.white_text_visible(page,span)):
                        raise engine.Rejected('PDF含不可见或半透明文字，原生路线无法保证隐藏层清理，已停止。')
                covers=[(seq,fitz.Rect(rect))for seq,(kind,rect)in enumerate(page.get_bboxlog())if kind in {'fill-path','stroke-path','fill-image'}]
                for span in page.get_texttrace():
                    for char in span['chars']:
                        if chr(char[0]).strip() and any(seq>span.get('seqno',-1) and rect.intersects(fitz.Rect(char[3])) for seq,rect in covers):
                            raise engine.Rejected('PDF文字被后绘制的图形/图片遮住，存在可恢复的隐藏内容；原生路线停止。')
                pdf_visibility.redaction_graphics(page,boxes)
                for box in boxes:
                    page.add_redact_annot(box, fill=(0, 0, 0), cross_out=False)
                if boxes:
                    page.apply_redactions(images=2, graphics=1, text=0)
            # 新建容器，不保存增量历史，不导入链接、注释、书签和文档级脚本。
            fresh = fitz.open()
            fresh.insert_pdf(doc, links=False, annots=False, widgets=False)
            fresh.set_metadata({})
            output = fresh.tobytes(garbage=4, clean=True, deflate=True, no_new_id=True)
            fresh.close()
        if _verify:verify(output, plan, data)
        return output
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF原生删改或复检未完成，未退回图像化。') from exc


def verify(data, plan, source):
    import formats
    fitz = backend()
    if source is None:
        raise engine.Rejected('PDF复检需要原件，才能检查框外页面及文字。')
    plan=effective_plan(source,plan)
    sizes = formats.pdf_info(source)
    selected = areas(plan, sizes)
    pixel_source = without_annotation_appearance(source) or source
    expected=export(source,plan,_verify=False)
    if data != expected:
        raise engine.Rejected('PDF实际副本与本工具按同一原件和计划重新生成的结果不一致，未接受外部覆盖或额外载体。')
    checks = {'deterministic_pdf_matches_source_plan': True, 'pdf_not_rasterized': True, 'selected_text_removed': True,
              'outside_text_positions_preserved': True, 'outside_page_pixels_preserved': True,
              'covered_text_not_revealed': True, 'selected_regions_solid': True, 'pdf_hidden_objects_absent': True}
    try:
        stripped = open_pdf(pixel_source) if pixel_source != source else None
        try:
            with open_pdf(source) as before, open_pdf(data, inspect_image_visibility=False) as after:
                if len(before) != len(after) or (stripped is not None and len(stripped) != len(before)):
                    raise engine.Rejected('PDF页数发生变化。')
                import pdf_visibility
                pdf_visibility.check_used_xobjects(data)
                pdf_visibility.check_object_carriers(after)
                if after.embfile_count() or after.get_toc() or any(after.metadata.get(k) for k in ('title','author','subject','keywords','creator','producer')) or after.get_xml_metadata():
                    checks['pdf_hidden_objects_absent'] = False
                cover_reason = ''
                for index, (original, page) in enumerate(zip(before, after)):
                    if original.rect != page.rect or original.rotation != page.rotation:
                        raise engine.Rejected('PDF页面尺寸或旋转发生变化。')
                    pixel_boxes = selected.get(index + 1, [])
                    boxes = [_to_page_rect(b, original, sizes[index]) for b in pixel_boxes]
                    if word_rows(original, boxes) != word_rows(page, boxes):
                        checks['outside_text_positions_preserved'] = False
                    for span in page.get_texttrace():
                        for char in span['chars']:
                            if chr(char[0]).strip() and any(fitz.Rect(char[3]).intersects(b) for b in boxes):
                                checks['selected_text_removed'] = False
                    used_images={image['xref']for image in page.get_image_info(xrefs=True)}
                    if any(row[0]not in used_images for row in page.get_images(full=True)):
                        checks['pdf_hidden_objects_absent'] = False
                    if page.first_annot or page.first_widget or page.get_links():
                        checks['pdf_hidden_objects_absent'] = False
                    # 有批注/链接时，基准是“只去掉这些对象、还没涂黑”的页面。图标消失因此不计入框外破坏；涂黑波及框外字形时，仍和这份基准不一致。
                    old = formats.pdf_image(pixel_source, index)
                    new = formats.pdf_image(data, index)
                    delta = ImageChops.difference(old, new)
                    for box in pixel_boxes:
                        # 仅容许边缘的两像素抗锯齿差异；切到字形时框外变化会明确失败。
                        x0,y0,x1,y1=box
                        delta.paste((0,0,0),(max(0,x0-2),max(0,y0-2),min(new.width,x1+2),min(new.height,y1+2)))
                        inner=(x0+2,y0+2,x1-2,y1-2)
                        if inner[0] >= inner[2] or inner[1] >= inner[3] or new.crop(inner).getbbox() is not None:
                            checks['selected_regions_solid'] = False
                    if delta.getbbox() is not None:
                        checks['outside_page_pixels_preserved'] = False
                    # 与带批注的原页面再比一次。去掉浅色盖子后，框外若多出深色像素，就是被揭开的内容。
                    source_image = formats.pdf_image(source, index)
                    revealed = ImageChops.subtract(source_image.convert('L'), new.convert('L'))
                    for box in pixel_boxes:
                        x0, y0, x1, y1 = box
                        revealed.paste(0, (max(0, x0 - 2), max(0, y0 - 2), min(new.width, x1 + 2), min(new.height, y1 + 2)))
                    baseline_page = stripped[index] if stripped is not None else None
                    found = annotation_change_reason(original, baseline_page, pixel_boxes, source_image, old, darkening=revealed)
                    if revealed.getextrema()[1] > 0 and found != 'annot':
                        found = 'revealed'
                    if found:
                        checks['outside_page_pixels_preserved'] = False
                        checks['covered_text_not_revealed'] = False
                        if found == 'revealed' or cover_reason != 'revealed':
                            cover_reason = found
                keep = engine.keep_checked(plan.get('keep', []))
                if keep:
                    all_text = '\n'.join(p.get_text() for p in after)
                    checks['keep_phrases_preserved'] = all(x in all_text for x in keep)
                if not all(checks.values()):
                    failed = {name for name, ok in checks.items() if not ok}
                    if failed == {'keep_phrases_preserved'}:
                        raise engine.Rejected('保留项没有对上：原文里没有这项，或副本里没有留下。未交付副本。')
                    if cover_reason == 'annot':
                        detail = '批注本身有可见内容。请先去掉这块方块或批注，或把被盖住的内容一起框进选区。'
                    elif cover_reason == 'revealed':
                        detail = '去掉批注后，原本看不见的内容变得可见。请先去掉这块方块或批注，或把被盖住的内容一起框进选区。'
                    elif cover_reason == '':
                        detail = ''
                    else:
                        raise engine.Rejected('PDF原生复检未通过：可能切到字形、影响框外内容或存在隐藏对象；请扩大框选或检查格式，不自动图像化。')
                    raise engine.Rejected('PDF原生复检未通过：可能切到字形、影响框外内容或存在隐藏对象；' + detail + '请扩大框选或检查格式，不自动图像化。')
                return {'checks': checks, 'not_checked': [] if keep else ['keep_phrases_preserved'],
                        'effective_pages':plan.get('pages',[]),'output_sha256': engine.digest(data), 'scope': 'PDF原生删改；保留框外可搜索文字、位置和页面。仅核对已选区域及支持的隐藏载体。'}
        finally:
            if stripped is not None:
                stripped.close()
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF实际副本原生复检失败。') from exc


def snap_region(data,number,region):
    """在预览中对齐完整字符；仅返回范围，不返回原文。"""
    import formats
    sizes=formats.pdf_info(data)
    if type(number)is not int or not 1<=number<=len(sizes):raise engine.Rejected('PDF页码无效。')
    target=list(engine.rectangles([region],sizes[number-1])[0]);fitz=backend()
    with fitz.open(stream=data,filetype='pdf')as doc:
        page=doc[number-1];glyphs=[]
        for span in page.get_texttrace():
            for char in span['chars']:
                if chr(char[0]).strip():
                    r=fitz.Rect(char[3])*_display_matrix(page)
                    sx,sy=_pixel_scale(page,sizes[number-1]);glyphs.append(fitz.Rect(r.x0*sx,r.y0*sy,r.x1*sx,r.y1*sy))
        if len(glyphs)>200000:raise engine.Rejected('PDF字形超出对齐范围。')
        for _ in range(64):
            previous=target[:];rect=fitz.Rect(target)
            for glyph in glyphs:
                if glyph.intersects(rect):target=[min(target[0],math.floor(glyph.x0)),min(target[1],math.floor(glyph.y0)),max(target[2],math.ceil(glyph.x1)),max(target[3],math.ceil(glyph.y1))]
            if target==previous:return list(engine.rectangles([target],sizes[number-1])[0])
    raise engine.Rejected('整字范围无法稳定对齐，请在预览调整框选。')


def effective_plan(data,plan):
    if not isinstance(plan.get('snap_to_text',False),bool):raise engine.Rejected('整字对齐选项必须为布尔值。')
    if plan.get('snap_to_text')is not True or plan.get('pdf_mode','preserve')!='preserve':return plan
    import formats
    original=areas(plan,formats.pdf_info(data))
    return {**plan,'snap_to_text':False,'pages':[{'page':number,'rectangles':[snap_region(data,number,list(region))for region in rows]}for number,rows in original.items()]}
