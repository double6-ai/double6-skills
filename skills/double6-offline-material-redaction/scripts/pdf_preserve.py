"""PDF原生删改：保留未选区域的文字和页面；使用外部AGPL-3.0 PyMuPDF引擎。"""
import io
import math
from collections import Counter

from PIL import Image, ImageChops
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


def _counts_as_hidden(rect, area, selected):
    """落在批注里、且没有被框选盖住的对象，才算揭开后仍会留下的内容。"""
    if not rect.intersects(area):
        return False
    return not any(rect.intersects(sel) for sel in selected)


def _glyphs_under(page, area):
    """去掉批注后，落在这个矩形里的文字层字符。不把这些字符写进报错。"""
    if page is None or area is None or area.is_empty or area.is_infinite:
        return ''
    fitz = backend()
    chars = []
    for span in page.get_texttrace():
        for char in span['chars']:
            text = chr(char[0])
            if text.strip() and fitz.Rect(char[3]).intersects(area):
                chars.append(text)
    return ''.join(chars)


def _graphics_under(page, area, selected):
    """批注下面还有没有未框选的矢量或图片。文字改由边缘判断，这里不再把文字当遮盖。"""
    if page is None or area is None or area.is_empty or area.is_infinite:
        return False
    fitz = backend()
    page_box = _content_bounds(page)
    if not page_box.intersects(area):
        return False
    for image in page.get_image_info():
        if _counts_as_hidden(fitz.Rect(image['bbox']), area, selected):
            return True
    for drawing in page.get_drawings():
        bounds = fitz.Rect(drawing['rect'])
        if bounds.contains(page_box):
            continue
        if bounds.width > page_box.width * 0.9 and bounds.height > page_box.height * 0.9:
            continue
        if _counts_as_hidden(bounds, area, selected):
            return True
    return False


_ANNOT_LABELS = {
    'Text': '便签',
    'Link': '链接',
    'FreeText': '自由文本',
    'Line': '直线',
    'Square': '方形',
    'Circle': '圆形',
    'Polygon': '多边形',
    'PolyLine': '折线',
    'Highlight': '高亮',
    'Underline': '下划线',
    'Squiggly': '波浪线',
    'StrikeOut': '删除线',
    'Stamp': '图章',
    'Ink': '墨迹',
    'Popup': '弹出框',
    'FileAttachment': '附件',
}


def _annot_label(name):
    """报错里用来指认是哪一块。类型名不参与放行。"""
    if not name:
        return '批注'
    key = name[1:] if name.startswith('/') else name
    return _ANNOT_LABELS.get(key, '批注')


def _pdf_rect_values(value):
    tokens = value.replace('[', ' ').replace(']', ' ').split()
    if len(tokens) != 4:
        return None
    try:
        return tuple(float(token) for token in tokens)
    except ValueError:
        return None


def _grow_pixel_box(box, image, pad=2):
    """多取 2 个预览像素，把描边的抗锯齿收进比较范围。这不是忽略差异的容差。"""
    if box is None:
        return None
    x0, y0, x1, y1 = box
    grown = (max(0, x0 - pad), max(0, y0 - pad), min(image.width, x1 + pad), min(image.height, y1 + pad))
    if grown[2] <= grown[0] or grown[3] <= grown[1]:
        return None
    return grown


def _visual_bound(annot):
    """批注矩形，并在外观框与它同一坐标系且相交时并进外观框。"""
    fitz = backend()
    visual = fitz.Rect(annot.rect)
    appearance = annot.apn_bbox
    if appearance is not None:
        appearance = fitz.Rect(appearance)
        if not appearance.is_empty and not appearance.is_infinite and appearance.intersects(visual):
            visual.include_rect(appearance)
    return visual


def _areas_to_judge(page):
    """每条会被删掉的批注，含 PyMuPDF 不列出的 /Annots。返回 (文字坐标矩形或 None, 报错用的称呼)。

    取样用批注矩形本身，并在外观框与它相交时并进外观框。不再按线宽把矩形撑大，
    否则旁边仍可读的字会把真正的遮盖判成没盖住。矩形外多画出来的部分另做差分。
    """
    seen = set()
    areas = []
    for annot in page.annots() or []:
        seen.add(annot.xref)
        visual = _visual_bound(annot)
        area = None if visual is None or visual.is_empty or visual.is_infinite else _annot_area_from_bound(visual, page)
        areas.append((area, _annot_label(annot.type[1])))
    raw = _annots_array(page)
    if not raw:
        return areas
    refs = _xref_numbers(raw)
    if not refs:
        areas.append((None, '批注'))
        return areas
    doc = page.parent
    for xref in refs:
        if xref in seen:
            continue
        kind, subtype = doc.xref_get_key(xref, 'Subtype')
        label = _annot_label(subtype if kind == 'name' else '')
        rect_kind, rect_value = doc.xref_get_key(xref, 'Rect')
        pdf_rect = _pdf_rect_values(rect_value) if rect_kind == 'array' else None
        if pdf_rect is None:
            areas.append((None, label))
            continue
        bound = _bound_from_pdf_rect(page, pdf_rect)
        areas.append((_annot_area_from_bound(bound, page), label))
    return areas


def _clamp_pixel_box(box, image):
    if not box:
        return None
    x0, y0, x1, y1 = (int(round(value)) for value in box)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(image.width, x1)
    y1 = min(image.height, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return (x0, y0, x1, y1)


def _sample_box(area, page, image):
    """文字坐标矩形转到预览像素，再外扩 2 像素，把描边收进覆盖区。"""
    if area is None or area.is_empty or area.is_infinite:
        return None
    return _clamp_pixel_box(_grow_pixel_box(_to_pixel_box(area, page, image), image), image)


def _ink_stats(base_px, covered_px, width, height):
    """3×3 局部最大值减去本点，差值至少 8 才算文字边缘。只统计去掉批注后的画面。"""
    count = 0
    survived = 0
    for y in range(height):
        row = y * width
        y0 = y - 1 if y else 0
        y1 = y + 1 if y + 1 < height else height - 1
        for x in range(width):
            center = base_px[row + x]
            local = center
            x0 = x - 1 if x else 0
            x1 = x + 1 if x + 1 < width else width - 1
            for yy in (y0, y, y1):
                sample = yy * width
                for xx in (x0, x, x1):
                    value = base_px[sample + xx]
                    if value > local:
                        local = value
            if local - center < 8:
                continue
            count += 1
            if abs(int(covered_px[row + x]) - int(center)) <= 28:
                survived += 1
    return count, survived


def _judge_crop(base_img, covered_img, box):
    """覆盖区里，去掉批注后才有的文字边缘还在不在。批注自己的图标底下是空白，不算遮盖。"""
    box = _clamp_pixel_box(box, base_img)
    if box is None or base_img.size != covered_img.size:
        return 'invalid'
    base = base_img.crop(box)
    covered = covered_img.crop(box)
    base_px = base.tobytes()
    covered_px = covered.tobytes()
    width, height = base.size
    if width < 4 or height < 4 or len(base_px) != len(covered_px):
        return 'invalid'
    low, high = base.getextrema()
    covered_low, covered_high = covered.getextrema()
    span_base = int(high - low)
    span_covered = int(covered_high - covered_low)
    mean_base = sum(base_px) / len(base_px)
    mean_covered = sum(covered_px) / len(covered_px)
    count, survived = _ink_stats(base_px, covered_px, width, height)
    survival = None if count < 8 else survived / count
    no_underlying = count < 8 and span_base < 12
    solid = span_covered <= 12 and (span_base >= 8 or abs(mean_base - mean_covered) >= 20)
    if no_underlying and not solid:
        return 'empty'
    if solid or (survival is not None and survival <= 0.35 and span_covered <= 50):
        return 'opaque'
    if survival is not None and survival >= 0.55 and span_covered >= 60:
        return 'readable'
    if no_underlying:
        return 'empty'
    return 'partial'


def _worst_kind(kinds):
    order = {'opaque': 4, 'partial': 3, 'invalid': 3, 'readable': 1, 'empty': 0}
    return max(kinds, key=lambda kind: order.get(kind, 2))


def _kinds_disagree(left, right):
    if left == right or 'invalid' in (left, right):
        return False
    hard = {'opaque', 'partial'}
    soft = {'readable', 'empty'}
    return (left in hard or right in hard) and (left in soft or right in soft)


def _garbled_text(text):
    """文字层对不上画面：替换字符、未映射字形。正常汉字和数字不是这类。"""
    for char in text:
        code = ord(char)
        if char == '\ufffd' or code == 0 or 0xE000 <= code <= 0xF8FF:
            return True
    return False


def _occlusion_reason(left, right, glyphs, graphics, outside=False):
    """pdfium 与 MuPDF 只要有一个判盖住或判不了，就不放行。空白上的图标不是遮盖。

    矩形外的小块差异里，pdfium 仍能看见字、MuPDF 只是重绘发虚时，不当成遮盖。
    pdfium 自己判成盖住或看不清，或者 MuPDF 判成完全盖住，仍然拒绝。
    """
    if 'invalid' in (left, right):
        return 'invalid'
    if glyphs and 'empty' in (left, right):
        return 'mismatch'
    if _garbled_text(glyphs):
        return 'mismatch'
    if graphics:
        return 'vector'
    if outside:
        if left in {'opaque', 'partial'} or right == 'opaque' or (right == 'partial' and left not in {'readable', 'empty'}):
            if 'opaque' in (left, right) or left == 'partial':
                return 'opaque'
            return 'disagree'
        return ''
    if _kinds_disagree(left, right):
        return 'disagree'
    if _worst_kind((left, right)) in {'opaque', 'partial'}:
        return 'opaque'
    return ''


_OCCLUSION_DETAIL = {
    'opaque': '这块批注把底下的字盖住了，去掉之后字才会露出来。请先去掉这块批注。',
    'invalid': '这块批注盖住的范围没法对齐，不能确认底下的字还在不在。请先去掉这块批注。',
    'disagree': '两种渲染对底下的字看不一致，不能确认字还在不在。请先去掉这块批注。',
    'mismatch': '文字层里有字，画面上却看不到这些字的边缘。请先去掉这块批注。',
    'vector': '这块批注下面有线条或图片，没法确认去掉之后会不会露出来。请先去掉这块批注。',
}


def _occlusion_message(page_number, label, box, reason):
    detail = _OCCLUSION_DETAIL.get(reason)
    if not detail:
        return ''
    where = ''
    if box is not None:
        where = f'预览范围大约是 {box[0]},{box[1]} 到 {box[2]},{box[3]}。'
    return f'第{page_number}页有一处{label or "批注"}。{where}{detail}'


def _mupdf_gray(page, size):
    """按 pdfium 同一像素尺寸渲染。对不齐就当判不了。"""
    if page is None:
        return None
    fitz = backend()
    sx, sy = _pixel_scale(page, size)
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(sx, sy), annots=True, alpha=False)
    except Exception:
        return None
    if pix.width != size[0] or pix.height != size[1] or pix.n < 3:
        return None
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')


def _outside_change_is_noise(box):
    """矩形外比一颗字还短的差分，是换一次渲染留下的毛边，不是遮盖。

    普通高亮在 Windows 上会让页面另一处的字边重画大约 4×9 个预览像素，这块小窗会被误判成涂平。
    能盖住号码的框外外观长边远大于 12 个预览像素，仍然要判断。
    """
    return max(box[2] - box[0], box[3] - box[1]) < 12


def _expand_sample(box, image):
    """不足 4 像素的差分块向外补到能取样。补完仍不够就保持原样，交给后面判为对齐不了。"""
    def grow(start, end, limit):
        if end - start >= 4:
            return start, end
        extra = 4 - (end - start)
        start = max(0, start - extra // 2)
        end = min(limit, end + extra - extra // 2)
        if end - start < 4:
            start = max(0, end - 4)
            end = min(limit, start + 4)
        return start, end

    x0, y0, x1, y1 = (int(value) for value in box)
    x0, x1 = grow(x0, x1, image.width)
    y0, y1 = grow(y0, y1, image.height)
    return (x0, y0, x1, y1)


def _changed_components(covered, base, claimed):
    """已核对矩形之外，还有哪些成片的画面差异。空白上的小毛边不到 8 个像素就忽略。"""
    diff = ImageChops.difference(covered, base)
    for box in claimed:
        diff.paste(0, box)
    pixels = diff.tobytes()
    width, height = diff.size
    seen = bytearray(width * height)
    boxes = []
    for start, value in enumerate(pixels):
        if not value or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        count = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        while stack:
            index = stack.pop()
            count += 1
            x = index % width
            y = index // width
            if x < min_x:
                min_x = x
            elif x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            elif y > max_y:
                max_y = y
            if x > 0 and pixels[index - 1] and not seen[index - 1]:
                seen[index - 1] = 1
                stack.append(index - 1)
            if x + 1 < width and pixels[index + 1] and not seen[index + 1]:
                seen[index + 1] = 1
                stack.append(index + 1)
            if y > 0 and pixels[index - width] and not seen[index - width]:
                seen[index - width] = 1
                stack.append(index - width)
            if y + 1 < height and pixels[index + width] and not seen[index + width]:
                seen[index + width] = 1
                stack.append(index + width)
        if count >= 8:
            boxes.append((min_x, min_y, max_x + 1, max_y + 1))
    return boxes


def annotation_change_reason(page, baseline_page, pixel_boxes, original_image, baseline_image, page_number=1):
    """看每条被删批注有没有把底下的字盖住，不看像素变没变。

    每条批注都用 pdfium 和 MuPDF 各渲染有批注、无批注两张图。覆盖区里只认去掉批注之后还在的文字边缘。
    便签、图章、签名自己的图标，底下是空白时不算遮盖。两个渲染器只要有一个判盖住或判不了，就拒绝。
    文字层有字、画面上却没有这些字的边缘，也拒绝。批注下面的矢量或图片无法用文字边缘判断，继续拒绝。
    类型名、颜色和线宽都不是放行条件。矩形外多画出来的差异另判；判不了同样拒绝。
    """
    areas = _areas_to_judge(page)
    if not areas:
        return ''
    if original_image.size != baseline_image.size:
        return _occlusion_message(page_number, '批注', None, 'invalid')
    selected = [_to_page_rect(box, page, original_image.size) for box in pixel_boxes]
    covered = original_image.convert('L')
    base = baseline_image.convert('L')
    mupdf_covered = _mupdf_gray(page, original_image.size)
    mupdf_base = _mupdf_gray(baseline_page, original_image.size)
    if mupdf_covered is None or mupdf_base is None:
        return _occlusion_message(page_number, areas[0][1], None, 'invalid')
    problems = []
    claimed = []
    for area, label in areas:
        box = _sample_box(area, page, covered)
        glyphs = _glyphs_under(baseline_page, area)
        graphics = _graphics_under(baseline_page, area, selected)
        if box is None:
            reason = 'invalid'
        else:
            reason = _occlusion_reason(
                _judge_crop(base, covered, box),
                _judge_crop(mupdf_base, mupdf_covered, box),
                glyphs,
                graphics,
            )
            claimed.append(box)
        if reason:
            problems.append(_occlusion_message(page_number, label, box, reason))
    for source_covered, source_base in ((covered, base), (mupdf_covered, mupdf_base)):
        for box in _changed_components(source_covered, source_base, claimed):
            if _outside_change_is_noise(box):
                continue
            box = _expand_sample(box, covered)
            area = _to_page_rect(box, page, original_image.size)
            reason = _occlusion_reason(
                _judge_crop(base, covered, box),
                _judge_crop(mupdf_base, mupdf_covered, box),
                _glyphs_under(baseline_page, area),
                _graphics_under(baseline_page, area, selected),
                outside=True,
            )
            if reason:
                problems.append(_occlusion_message(page_number, '批注', box, reason))
                break
        if problems:
            break
    if not problems:
        return ''
    if len(problems) == 1:
        return problems[0]
    return problems[0] + '同一页还有别处批注同样要先去掉。'


def _stored_user_unit(page):
    """页面上不是 1 的 UserUnit 原文。没有或就是 1 时不改这一页。"""
    kind, value = page.parent.xref_get_key(page.xref, 'UserUnit')
    if kind not in ('real', 'int'):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    # 只处理大于 1 的 UserUnit。等于 1 不用改。小于 1 时同一写法会把黑块缩小，尚未证明不会留住字形，所以保持拒绝。
    if number <= 1.0:
        return None
    return value


def _apply_redactions(page):
    """涂黑时暂时把 UserUnit 写成 1。

    PyMuPDF 的 apply_redactions 会把已经按 UserUnit 放大过的宽高再乘一次，黑块超出选区，
    复检就误以为切到了框外。矩形本身先按文字坐标记好，这里只避免第二次放大；涂完再写回原值。
    把选区缩小来迁就这次放大会留下正文，不能那样做。
    """
    saved = _stored_user_unit(page)
    if saved is not None:
        page.parent.xref_set_key(page.xref, 'UserUnit', '1')
    try:
        page.apply_redactions(images=2, graphics=1, text=0)
    finally:
        if saved is not None:
            page.parent.xref_set_key(page.xref, 'UserUnit', saved)


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
                    _apply_redactions(page)
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
                    # 图章、便签的外观文字不算页面正文。有批注时跟去掉批注、尚未涂黑的页面比位置。
                    text_before = stripped[index] if stripped is not None else original
                    if word_rows(text_before, boxes) != word_rows(page, boxes):
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
                    # 有批注时，基准仍是去掉批注、尚未涂黑的页面，用来看涂黑有没有切到框外字形。
                    old = formats.pdf_image(pixel_source, index)
                    new = formats.pdf_image(data, index)
                    delta = ImageChops.difference(old, new)
                    for box in pixel_boxes:
                        # 仅容许涂黑边缘的两像素抗锯齿差异；切到字形时框外变化会明确失败。批注自身不走这份额外容差。
                        x0,y0,x1,y1=box
                        delta.paste((0,0,0),(max(0,x0-2),max(0,y0-2),min(new.width,x1+2),min(new.height,y1+2)))
                        inner=(x0+2,y0+2,x1-2,y1-2)
                        if inner[0] >= inner[2] or inner[1] >= inner[3] or new.crop(inner).getbbox() is not None:
                            checks['selected_regions_solid'] = False
                    if delta.getbbox() is not None:
                        checks['outside_page_pixels_preserved'] = False
                    source_image = formats.pdf_image(source, index)
                    baseline_page = stripped[index] if stripped is not None else None
                    detail = annotation_change_reason(original, baseline_page, pixel_boxes, source_image, old, page_number=index + 1)
                    if detail:
                        checks['outside_page_pixels_preserved'] = False
                        checks['covered_text_not_revealed'] = False
                        if not cover_reason:
                            cover_reason = detail
                keep = engine.keep_checked(plan.get('keep', []))
                if keep:
                    all_text = '\n'.join(p.get_text() for p in after)
                    checks['keep_phrases_preserved'] = all(x in all_text for x in keep)
                if not all(checks.values()):
                    failed = {name for name, ok in checks.items() if not ok}
                    if failed == {'keep_phrases_preserved'}:
                        raise engine.Rejected('保留项没有对上：原文里没有这项，或副本里没有留下。未交付副本。')
                    if cover_reason:
                        raise engine.Rejected('PDF原生复检未通过：' + cover_reason)
                    raise engine.Rejected('PDF原生复检未通过：可能切到字形、影响框外内容或存在隐藏对象；请扩大框选或检查格式，不自动图像化。')
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
