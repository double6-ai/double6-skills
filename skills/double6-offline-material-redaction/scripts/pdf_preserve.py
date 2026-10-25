"""PDF原生删改：保留未选区域的文字和页面；使用外部AGPL-3.0 PyMuPDF引擎。"""
import io
import math
import re
from collections import Counter
from xml.etree import ElementTree as ET

from PIL import ImageChops
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
    tokens = value.replace('[', ' ').replace(']', ' ').replace('<', ' ').replace('>', ' ').split()
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


def _positive_number(text, key):
    parts = text.split(key, 1)
    if len(parts) != 2:
        return 0.0
    number = ''
    started = False
    for char in parts[1].lstrip():
        if char.isdigit() or char == '.':
            number += char
            started = True
            continue
        if started or char not in ' \n\r\t':
            break
    if not number or number == '.':
        return 0.0
    return abs(float(number))


def _xref_pad(doc, xref):
    """边框宽度和 /RD。单位与批注矩形相同，用来把描边收进外接矩形。"""
    pad = 0.0
    kind, value = doc.xref_get_key(xref, 'RD')
    if kind == 'array':
        numbers = _pdf_rect_values(value)
        if numbers:
            pad = max(pad, max(abs(number) for number in numbers))
    kind, value = doc.xref_get_key(xref, 'BS')
    if kind == 'dict':
        pad = max(pad, _positive_number(value, '/W'))
    kind, value = doc.xref_get_key(xref, 'Border')
    if kind == 'array':
        tokens = value.replace('[', ' ').replace(']', ' ').split()
        if len(tokens) >= 3:
            try:
                pad = max(pad, abs(float(tokens[2])))
            except ValueError:
                pass
    return pad


def _grow_area(area, pad):
    if area is None or pad <= 0:
        return area
    fitz = backend()
    return fitz.Rect(area.x0 - pad, area.y0 - pad, area.x1 + pad, area.y1 + pad)


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
    """每条批注，含 PyMuPDF 不列出的 /Annots。返回 (文字坐标矩形或 None, 报错用的称呼, xref 或 None)。"""
    seen = set()
    areas = []
    for annot in page.annots() or []:
        seen.add(annot.xref)
        border = annot.border or {}
        pad = max(float(border.get('width') or 0), _xref_pad(page.parent, annot.xref))
        delta = annot.rect_delta
        if delta:
            pad = max(pad, max(abs(float(value)) for value in delta))
        area = _grow_area(_annot_area_from_bound(_visual_bound(annot), page), pad)
        areas.append((area, _annot_label(annot.type[1]), annot.xref))
    raw = _annots_array(page)
    if not raw:
        return areas
    refs = _xref_numbers(raw)
    if not refs:
        areas.append((None, '批注', None))
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
            areas.append((None, label, xref))
            continue
        bound = _bound_from_pdf_rect(page, pdf_rect)
        areas.append((_grow_area(_annot_area_from_bound(bound, page), _xref_pad(doc, xref)), label, xref))
    return areas


def _box_changed(diff, box):
    if box is None:
        return True
    return diff.crop(box).getbbox() is not None


def _annot_problem(page_number, label, box, changed, under):
    where = ''
    if box is not None:
        where = f'预览范围大约是 {box[0]},{box[1]} 到 {box[2]},{box[3]}。'
    name = label or '批注'
    if changed and under:
        return f'第{page_number}页有一处{name}。{where}去掉之后，这个范围里的画面变了，底下还有没框选的文字、线条或图片。请先去掉这块批注。'
    if changed:
        return f'第{page_number}页有一处{name}。{where}去掉之后，这个范围里的画面变了。请先去掉这块批注。'
    if under:
        return f'第{page_number}页有一处{name}。{where}它盖住了还没框选的文字、线条或图片。请先去掉这块批注。'
    return ''


def annotation_change_reason(page, baseline_page, pixel_boxes, original_image, baseline_image, page_number=1):
    """删除前后逐像素比较。外接矩形里任何变化都拒绝，没有颜色或亮度门槛。

    比较的两张图都由同一渲染器、同一比例画出。链接和隐藏便签这类不改像素的批注，整页差分为空，
    所以没被批注碰到的正文不会产生抗锯齿噪声。因此这里不设容差：差一个像素也拒绝。
    外接矩形含边框、与矩形相交的外观框，并外扩 2 个预览像素，只为把描边边缘收进来。
    矩形里若有未框选的文字、矢量或图片，同样拒绝。类型名、颜色和线宽都不作为放行条件。
    """
    areas = _areas_to_judge(page)
    if not areas:
        return ''
    if original_image.size != baseline_image.size:
        return f'第{page_number}页去掉批注后无法与原渲染对齐。请先去掉这块批注。'
    selected = [_to_page_rect(box, page, original_image.size) for box in pixel_boxes]
    diff = ImageChops.difference(original_image, baseline_image)
    problems = []
    claimed = []
    for area, label, _xref in areas:
        box = None
        if area is not None and not area.is_empty and not area.is_infinite:
            box = _grow_pixel_box(_to_pixel_box(area, page, original_image), original_image)
        changed = _box_changed(diff, box)
        under = False if area is None else _objects_under(baseline_page, area, selected)
        problem = _annot_problem(page_number, label, box, changed, under)
        if problem:
            problems.append(problem)
        if box is not None:
            claimed.append(box)
    remain = diff.copy()
    for box in claimed:
        remain.paste((0, 0, 0), box)
    if remain.getbbox() is not None:
        bounds = remain.getbbox()
        problems.append(
            f'第{page_number}页去掉批注后，还有画面和原来不一样。预览范围大约是 {bounds[0]},{bounds[1]} 到 {bounds[2]},{bounds[3]}。请先去掉这块批注。'
        )
    if not problems:
        return ''
    if len(problems) == 1:
        return problems[0]
    return problems[0] + '同一页还有别处批注同样要先去掉。'


_UNREADABLE_SUBTYPES = {'FileAttachment', 'Sound', 'Movie', 'Screen', 'RichMedia', '3D', 'TrapNet'}


def wants_clear_annotations(plan):
    """一并清除批注。缺省或 false 都表示保留批注。"""
    if 'clear_annotations' not in plan:
        return False
    value = plan.get('clear_annotations')
    if value is True or value is False:
        return value
    raise engine.Rejected('「一并清除批注」只能选择打开或关闭。')


def selected_terms(page, boxes):
    """框选范围内的正文，按出现顺序收成补选词。框外的字不算。"""
    if not boxes:
        return []
    fitz = backend()
    terms = []
    seen = set()
    for span in page.get_texttrace():
        chars = []
        for char in span['chars']:
            glyph = fitz.Rect(char[3])
            if chr(char[0]).strip() and any(glyph.intersects(box) for box in boxes):
                chars.append(chr(char[0]))
                continue
            if chars:
                term = ''.join(chars).strip()
                if term and term not in seen:
                    seen.add(term)
                    terms.append(term)
                chars = []
        if chars:
            term = ''.join(chars).strip()
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def _text_hits(blob, terms):
    """补选词只要出现在批注文字里就算命中。数字的另一种写法和大小写都算，避免漏掉。"""
    if not blob or not terms:
        return False
    folded = blob.casefold()
    for term in terms:
        if engine.term_remains(blob, term):
            return True
        if term.casefold() in folded:
            return True
    return False


def _decode_pdf_bytes(raw):
    if raw.startswith(b'\xfe\xff'):
        return raw[2:].decode('utf-16-be')
    if raw.startswith(b'\xff\xfe'):
        return raw[2:].decode('utf-16-le')
    if any(byte >= 128 for byte in raw):
        raise ValueError('外观文字编码无法确认')
    return raw.decode('ascii')


def _parse_literal(data, index):
    if index >= len(data) or data[index] != ord('('):
        return '', index, False
    index += 1
    out = bytearray()
    depth = 1
    mapping = {ord('n'): b'\n', ord('r'): b'\r', ord('t'): b'\t', ord('b'): b'\b', ord('f'): b'\f', ord('('): b'(', ord(')'): b')', ord('\\'): b'\\'}
    while index < len(data) and depth:
        char = data[index]
        if char == ord('\\'):
            if index + 1 >= len(data):
                return '', index, False
            nxt = data[index + 1]
            if nxt in mapping:
                out.extend(mapping[nxt])
                index += 2
                continue
            if nxt in b'\r\n':
                index += 2
                if nxt == ord('\r') and index < len(data) and data[index] == ord('\n'):
                    index += 1
                continue
            octal = bytearray()
            cursor = index + 1
            while cursor < len(data) and len(octal) < 3 and data[cursor] in b'01234567':
                octal.append(data[cursor])
                cursor += 1
            if not octal:
                return '', index, False
            out.append(int(octal, 8) & 0xFF)
            index = cursor
            continue
        if char == ord('('):
            depth += 1
            out.append(char)
            index += 1
            continue
        if char == ord(')'):
            depth -= 1
            if depth:
                out.append(char)
            index += 1
            continue
        out.append(char)
        index += 1
    if depth:
        return '', index, False
    try:
        return _decode_pdf_bytes(bytes(out)), index, True
    except (UnicodeDecodeError, ValueError):
        return '', index, False


def _parse_hex_string(data, index):
    end = data.find(b'>', index + 1)
    if end < 0:
        return '', index, False
    body = re.sub(br'\s+', b'', data[index + 1:end])
    if not re.fullmatch(br'[0-9A-Fa-f]*', body):
        return '', index, False
    if len(body) % 2:
        body += b'0'
    try:
        text = _decode_pdf_bytes(bytes.fromhex(body.decode('ascii')))
    except (UnicodeDecodeError, ValueError):
        return '', end + 1, False
    return text, end + 1, True


def _parse_string_array(data, index):
    index += 1
    strings = []
    while index < len(data):
        while index < len(data) and data[index] in b' \t\r\n':
            index += 1
        if index >= len(data):
            return [], index, False
        if data[index] == ord(']'):
            return strings, index + 1, True
        if data[index] == ord('('):
            text, index, ok = _parse_literal(data, index)
            if not ok:
                return [], index, False
            strings.append(text)
            continue
        if data[index] == ord('<'):
            text, index, ok = _parse_hex_string(data, index)
            if not ok:
                return [], index, False
            strings.append(text)
            continue
        if data[index] in b'+-.0123456789':
            while index < len(data) and data[index] in b'+-.0123456789':
                index += 1
            continue
        return [], index, False
    return [], index, False


def _scan_text_ops(data):
    """只取出真正画出来的文字。路径坐标不算批注内容。读不完整就视为无法确认。"""
    index = 0
    texts = []
    pending = []
    do_names = []
    last_name = None
    while index < len(data):
        char = data[index]
        if char in b' \t\r\n\x00':
            index += 1
            continue
        if char == ord('%'):
            while index < len(data) and data[index] not in b'\r\n':
                index += 1
            continue
        if char == ord('('):
            text, index, ok = _parse_literal(data, index)
            if not ok:
                return '', [], True
            pending.append(text)
            continue
        if char == ord('<'):
            if index + 1 < len(data) and data[index + 1] == ord('<'):
                return '', [], True
            text, index, ok = _parse_hex_string(data, index)
            if not ok:
                return '', [], True
            pending.append(text)
            continue
        if char == ord('['):
            strings, index, ok = _parse_string_array(data, index)
            if not ok:
                return '', [], True
            pending.append(strings)
            continue
        if char == ord('/'):
            index += 1
            start = index
            while index < len(data) and data[index] not in b' \t\r\n()<>[]{}/%':
                index += 1
            last_name = data[start:index].decode('ascii', 'replace')
            continue
        start = index
        while index < len(data) and data[index] not in b' \t\r\n()<>[]{}/%':
            index += 1
        token = data[start:index]
        if token in (b'Tj', b"'"):
            if not pending or isinstance(pending[-1], list):
                return '', [], True
            texts.append(pending[-1])
            pending.clear()
            continue
        if token == b'"':
            if not pending or isinstance(pending[-1], list):
                return '', [], True
            texts.append(pending[-1])
            pending.clear()
            continue
        if token == b'TJ':
            if not pending or not isinstance(pending[-1], list):
                return '', [], True
            texts.extend(pending[-1])
            pending.clear()
            continue
        if token == b'Do':
            if not last_name:
                return '', [], True
            do_names.append(last_name)
            last_name = None
            pending.clear()
            continue
        # 行内图片和无法辨认的字典都可能藏着文字，不能当成空白批注。
        if token in (b'BI', b'ID', b'EI'):
            return '', [], True
        pending.clear()
    return ''.join(texts), do_names, False


def _balanced_dict(text, key):
    token = '/' + key
    start = text.find(token)
    if start < 0:
        return None
    rest = text[start + len(token):].lstrip()
    if rest.startswith('<<'):
        depth = 0
        for index, char in enumerate(rest):
            if rest.startswith('<<', index):
                depth += 1
            elif rest.startswith('>>', index):
                depth -= 1
                if depth == 0:
                    return rest[:index + 2]
        return None
    return rest.split('>>', 1)[0].strip()


def _xobject_map(doc, xref):
    kind, resources = doc.xref_get_key(xref, 'Resources')
    block = None
    if kind == 'xref':
        resource_xref = int(resources.split()[0])
        xkind, block = doc.xref_get_key(resource_xref, 'XObject')
        if xkind == 'null':
            return {}
        if xkind == 'xref':
            block = doc.xref_object(int(block.split()[0]))
        elif xkind != 'dict':
            return None
    elif kind == 'dict':
        block = _balanced_dict(resources, 'XObject')
        if block is None:
            return {}
    elif kind == 'null':
        return {}
    else:
        return None
    if block is None:
        return None
    names = re.findall(r'/([^\s/<>\[\]()]+)\s+(\d+)\s+\d+\s+R', block)
    return {name: int(number) for name, number in names}


def _appearance_text(doc, xref, seen):
    if xref in seen:
        return '', True
    seen.add(xref)
    kind, subtype = doc.xref_get_key(xref, 'Subtype')
    if kind == 'name' and subtype in {'/Image', 'Image'}:
        return '', True
    try:
        stream = doc.xref_stream(xref) or b''
    except Exception:
        return '', True
    text, do_names, bad = _scan_text_ops(stream) if stream else ('', [], False)
    if bad:
        return '', True
    if not do_names:
        return text, False
    mapping = _xobject_map(doc, xref)
    if mapping is None:
        return '', True
    parts = [text]
    for name in do_names:
        child = mapping.get(name)
        if child is None:
            return '', True
        child_text, child_bad = _appearance_text(doc, child, seen)
        if child_bad:
            return '', True
        parts.append(child_text)
    return ''.join(parts), False


def _rich_text(value):
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return '', False
    parts = []
    for element in root.iter():
        if element.text:
            parts.append(element.text)
        if element.tail:
            parts.append(element.tail)
        parts.extend(element.attrib.values())
    return ''.join(parts), True


def _object_text(doc, xref):
    """间接对象里的文字。是字符串就读字符串，是流就读流；两种都不是就视为无法确认。"""
    try:
        raw = doc.xref_object(xref, compressed=True).strip()
    except Exception:
        return '', True
    try:
        raw_bytes = raw.encode('latin1')
    except UnicodeEncodeError:
        return '', True
    if raw_bytes.startswith(b'('):
        text, _index, ok = _parse_literal(raw_bytes, 0)
        return (text, False) if ok else ('', True)
    if raw_bytes.startswith(b'<'):
        text, _index, ok = _parse_hex_string(raw_bytes, 0)
        return (text, False) if ok else ('', True)
    length_kind, _length = doc.xref_get_key(xref, 'Length')
    if length_kind == 'null':
        return '', True
    try:
        stream = doc.xref_stream(xref) or b''
    except Exception:
        return '', True
    try:
        return _decode_pdf_bytes(stream), False
    except (UnicodeDecodeError, ValueError):
        return '', True


def _dict_string(doc, xref, key):
    kind, value = doc.xref_get_key(xref, key)
    if kind == 'null':
        return '', False
    if kind == 'string':
        return value, False
    if kind == 'xref':
        return _object_text(doc, int(value.split()[0]))
    return '', True


def _action_uri(doc, xref):
    kind, value = doc.xref_get_key(xref, 'A')
    if kind == 'null':
        direct, bad = _dict_string(doc, xref, 'URI')
        return direct, bad
    if kind == 'xref':
        return _dict_string(doc, int(value.split()[0]), 'URI')
    if kind != 'dict':
        return '', True
    match = re.search(r'/URI\s*(\((?:\\.|[^\\)])*\)|<[^>]*>)', value)
    if not match:
        if '/URI' in value or '/S /JavaScript' in value or '/JS' in value:
            return '', True
        return '', False
    token = match.group(1)
    if token.startswith('('):
        text, _index, ok = _parse_literal(token, 0)
        return (text, False) if ok else ('', True)
    text, _index, ok = _parse_hex_string(token, 0)
    return (text, False) if ok else ('', True)


def annotation_text(doc, xref, annot):
    """能完整读出的批注文字。读不完时第二项为 True，调用方应整份拒绝。"""
    kind, subtype = doc.xref_get_key(xref, 'Subtype')
    name = subtype[1:] if kind == 'name' and subtype.startswith('/') else ''
    if kind != 'name' or name in _UNREADABLE_SUBTYPES:
        return '', True
    file_kind, _file_value = doc.xref_get_key(xref, 'FS')
    if file_kind != 'null':
        return '', True
    parts = []
    for key in ('Contents', 'Subj', 'T'):
        text, bad = _dict_string(doc, xref, key)
        if bad:
            return '', True
        if text:
            parts.append(text)
    rich_kind, rich_value = doc.xref_get_key(xref, 'RC')
    if rich_kind != 'null':
        if rich_kind == 'xref':
            rich_value, bad = _object_text(doc, int(rich_value.split()[0]))
            if bad:
                return '', True
        elif rich_kind != 'string':
            return '', True
        rich_text, ok = _rich_text(rich_value)
        if not ok:
            return '', True
        parts.append(rich_text)
    uri, bad = _action_uri(doc, xref)
    if bad:
        return '', True
    if uri:
        parts.append(uri)
    if annot is not None:
        try:
            shown = annot.get_text('text') or ''
        except Exception:
            return '', True
        if shown:
            parts.append(shown)
        link_uri = getattr(annot, 'uri', None)
        if link_uri:
            parts.append(str(link_uri))
    ap_kind, ap_value = doc.xref_get_key(xref, 'AP')
    if ap_kind == 'null':
        return '\n'.join(parts), False
    if ap_kind == 'xref':
        targets = [int(ap_value.split()[0])]
    elif ap_kind == 'dict':
        targets = _xref_numbers(ap_value)
        if not targets:
            return '', True
    else:
        return '', True
    seen = set()
    for target in targets:
        text, bad = _appearance_text(doc, target, seen)
        if bad:
            return '', True
        if text:
            parts.append(text)
    return '\n'.join(parts), False


def _popup_xref(doc, xref):
    kind, value = doc.xref_get_key(xref, 'Popup')
    if kind != 'xref':
        return None
    return int(value.split()[0])


def _uncertain_message(page_number, label, more):
    message = f'第{page_number}页有一处{label}。没法确认里面的文字有没有这次要隐去的内容，已停止。请先处理这条批注。'
    if more:
        message += '同一页还有别处批注同样没法确认。'
    return message


def _unsafe_hit_message(page_number, label, more):
    message = f'第{page_number}页有一处{label}。它的文字里有这次要隐去的内容，去掉之后会露出还没框选的文字、线条或图片。请先去掉这块批注。'
    if more:
        message += '同一页还有别处批注同样要先去掉。'
    return message


def _open_content_page(page):
    """同一页的正文副本，不含批注外观。

    批注图标自己的笔画不能算成「底下的内容」，高亮也不能被当成把正文盖住的后绘图。
    """
    fitz = backend()
    scratch = fitz.open()
    scratch.insert_pdf(page.parent, from_page=page.number, to_page=page.number, annots=False, links=False, widgets=False)
    return scratch


def _content_image(data, index):
    """去掉批注后再渲染。用来确认框内已经涂实，不被留在上面的删除线、高亮干扰。"""
    import formats
    fitz = backend()
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[index]
        if not (list(page.annots() or []) or _annots_array(page)):
            return None
        scratch = fitz.open()
        try:
            scratch.insert_pdf(doc, from_page=index, to_page=index, annots=False, links=False, widgets=False)
            raw = scratch.tobytes(garbage=1, deflate=True, no_new_id=True)
        finally:
            scratch.close()
    return formats.pdf_image(raw, 0)


def _content_hides_text(page):
    """正文流里后画的图形或图片盖住了文字。只看正文，不把批注外观算进去。"""
    fitz = backend()
    scratch = _open_content_page(page)
    try:
        content = scratch[0]
        covers = [(seq, fitz.Rect(rect)) for seq, (kind, rect) in enumerate(content.get_bboxlog()) if kind in {'fill-path', 'stroke-path', 'fill-image'}]
        for span in content.get_texttrace():
            for char in span['chars']:
                if chr(char[0]).strip() and any(seq > span.get('seqno', -1) and rect.intersects(fitz.Rect(char[3])) for seq, rect in covers):
                    return True
        return False
    finally:
        scratch.close()


def annotations_to_drop(page, boxes, page_number, terms):
    """默认路径：命中补选词且删掉不会揭开未框选对象的批注。读不准则拒绝。

    terms 是整份材料里全部框选正文，不限于本页。某一页的便签写着另一页框选的词，同样算命中。
    是否会揭开内容，只看正文里的文字、线条和图片，不把批注图标自己的笔画算进去。
    """
    listed = {annot.xref: annot for annot in page.annots() or []}
    uncertain = []
    unsafe = []
    drop = set()
    scratch = _open_content_page(page)
    try:
        content = scratch[0]
        for area, label, xref in _areas_to_judge(page):
            if xref is None:
                uncertain.append(label or '批注')
                continue
            blob, bad = annotation_text(page.parent, xref, listed.get(xref))
            if bad:
                uncertain.append(label or '批注')
                continue
            if not _text_hits(blob, terms):
                continue
            covered = area is None or area.is_empty or area.is_infinite or _objects_under(content, area, boxes)
            if covered:
                unsafe.append(label or '批注')
                continue
            drop.add(xref)
            popup = _popup_xref(page.parent, xref)
            if popup:
                drop.add(popup)
    finally:
        scratch.close()
    if uncertain:
        raise engine.Rejected(_uncertain_message(page_number, uncertain[0], len(uncertain) > 1))
    if unsafe:
        raise engine.Rejected(_unsafe_hit_message(page_number, unsafe[0], len(unsafe) > 1))
    return drop


def _drop_xrefs(page, xrefs):
    if not xrefs:
        return
    for annot in list(page.annots() or []):
        if annot.xref in xrefs:
            page.delete_annot(annot)
    for link in list(page.get_links()):
        if link.get('xref') in xrefs:
            page.delete_link(link)
    raw = _annots_array(page)
    if not raw:
        return
    numbers = _xref_numbers(raw)
    remain = [number for number in numbers if number not in xrefs]
    if len(remain) == len(numbers):
        return
    if not remain:
        page.parent.xref_set_key(page.xref, 'Annots', 'null')
        return
    page.parent.xref_set_key(page.xref, 'Annots', '[' + ' '.join(f'{number} 0 R' for number in remain) + ']')


def without_dropped_annotations(data, drops):
    """只去掉计划中点名的批注，留下其余批注，供默认路径做框外像素基准。"""
    if not drops or not any(drops.values()):
        return None
    fitz = backend()
    with open_pdf(data) as doc:
        for index, page in enumerate(doc):
            _drop_xrefs(page, drops.get(index) or set())
        fresh = fitz.open()
        fresh.insert_pdf(doc, links=True, annots=True, widgets=False)
        fresh.set_metadata({})
        output = fresh.tobytes(garbage=4, clean=True, deflate=True, no_new_id=True)
        fresh.close()
        return output


def kept_annotation_problem(page, terms, page_number):
    """副本里留下的批注仍然带着补选词，或文字读不全，就不能交付。"""
    listed = {annot.xref: annot for annot in page.annots() or []}
    uncertain = []
    hits = []
    for _area, label, xref in _areas_to_judge(page):
        if xref is None:
            uncertain.append(label or '批注')
            continue
        blob, bad = annotation_text(page.parent, xref, listed.get(xref))
        if bad:
            uncertain.append(label or '批注')
            continue
        if _text_hits(blob, terms):
            hits.append(label or '批注')
    if uncertain:
        return _uncertain_message(page_number, uncertain[0], len(uncertain) > 1)
    if hits:
        return _unsafe_hit_message(page_number, hits[0], len(hits) > 1)
    return ''


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
    clearing = wants_clear_annotations(plan)
    sizes = formats.pdf_info(data)
    selected = areas(plan, sizes)
    try:
        with open_pdf(data) as doc:
            pdf_visibility.check_object_carriers(doc,clean=True)
            page_boxes = {}
            all_terms = []
            seen_terms = set()
            for index, page in enumerate(doc):
                boxes = [_to_page_rect(box, page, sizes[index]) for box in selected.get(index + 1, [])]
                page_boxes[index] = boxes
                if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots() or []):
                    raise engine.Rejected('PDF已有未应用的涂黑标记，请先在原软件完成或移除后再检查。')
                if not clearing:
                    for term in selected_terms(page, boxes):
                        if term not in seen_terms:
                            seen_terms.add(term)
                            all_terms.append(term)
            planned_drops = {}
            if not clearing:
                for index, page in enumerate(doc):
                    planned_drops[index] = annotations_to_drop(page, page_boxes[index], index + 1, all_terms)
            for index, page in enumerate(doc):
                # 注释中的附件/原词不移入正文；已存在的待应用涂黑标记不能直接删除。
                boxes = page_boxes[index]
                if clearing:
                    for annot in list(page.annots() or []):
                        page.delete_annot(annot)
                    for link in page.get_links():
                        page.delete_link(link)
                    if _annots_array(page):
                        page.parent.xref_set_key(page.xref, 'Annots', 'null')
                else:
                    _drop_xrefs(page, planned_drops[index])
                # 对不可见/半透明文字停止，避免把隐藏层变成普通可搜索正文。
                visible_bounds=_content_bounds(page)
                for span in page.get_texttrace():
                    if any(chr(char[0]).strip() and not visible_bounds.contains(fitz.Rect(char[3]))for char in span['chars']):
                        raise engine.Rejected('PDF文字超出可见页面或裁剪边界，存在隐藏原文，原生路线停止。')
                    if span.get('type') == 3 or span.get('opacity', 1) < .999 or span.get('size',1)<.5 or (isinstance(span.get('color'),tuple) and all(c>=.99 for c in span['color']) and not pdf_visibility.white_text_visible(page,span)):
                        raise engine.Rejected('PDF含不可见或半透明文字，原生路线无法保证隐藏层清理，已停止。')
                if _content_hides_text(page):
                    raise engine.Rejected('PDF文字被后绘制的图形/图片遮住，存在可恢复的隐藏内容；原生路线停止。')
                pdf_visibility.redaction_graphics(page,boxes)
                for box in boxes:
                    page.add_redact_annot(box, fill=(0, 0, 0), cross_out=False)
                if boxes:
                    page.apply_redactions(images=2, graphics=1, text=0)
            # 新建容器，不保存增量历史，不导入表单、书签和文档级脚本。
            # 默认保留批注和链接。只有明确选择一并清除批注时才不导入它们。
            fresh = fitz.open()
            fresh.insert_pdf(doc, links=not clearing, annots=not clearing, widgets=False)
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
    clearing = wants_clear_annotations(plan)
    sizes = formats.pdf_info(source)
    selected = areas(plan, sizes)
    all_terms = []
    if clearing:
        pixel_source = without_annotation_appearance(source) or source
    else:
        drops = {}
        with open_pdf(source) as doc:
            page_boxes = {}
            seen_terms = set()
            for index, page in enumerate(doc):
                boxes = [_to_page_rect(box, page, sizes[index]) for box in selected.get(index + 1, [])]
                page_boxes[index] = boxes
                for term in selected_terms(page, boxes):
                    if term not in seen_terms:
                        seen_terms.add(term)
                        all_terms.append(term)
            for index, page in enumerate(doc):
                drops[index] = annotations_to_drop(page, page_boxes[index], index + 1, all_terms)
        pixel_source = without_dropped_annotations(source, drops) or source
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
                    if page.first_widget or (clearing and (page.first_annot or page.get_links() or _annots_array(page))):
                        checks['pdf_hidden_objects_absent'] = False
                    # 明确清除批注时，基准仍是去掉批注、尚未涂黑的页面，用来看涂黑有没有切到框外字形。
                    # 默认保留批注时，基准就是原页面（只提前去掉因命中补选词而删除的那几条）。
                    old = formats.pdf_image(pixel_source, index)
                    new = formats.pdf_image(data, index)
                    # 默认留下的删除线、高亮画在涂黑上面。框内是否涂实，要看拿掉这些批注后的正文。
                    solid = _content_image(data, index) if not clearing else None
                    if solid is not None and solid.size != new.size:
                        checks['selected_regions_solid'] = False
                        solid = new
                    if solid is None:
                        solid = new
                    delta = ImageChops.difference(old, new)
                    for box in pixel_boxes:
                        # 仅容许涂黑边缘的两像素抗锯齿差异；切到字形时框外变化会明确失败。批注自身不走这份额外容差。
                        x0,y0,x1,y1=box
                        delta.paste((0,0,0),(max(0,x0-2),max(0,y0-2),min(new.width,x1+2),min(new.height,y1+2)))
                        inner=(x0+2,y0+2,x1-2,y1-2)
                        if inner[0] >= inner[2] or inner[1] >= inner[3] or solid.crop(inner).getbbox() is not None:
                            checks['selected_regions_solid'] = False
                    if delta.getbbox() is not None:
                        checks['outside_page_pixels_preserved'] = False
                    if clearing:
                        source_image = formats.pdf_image(source, index)
                        baseline_page = stripped[index] if stripped is not None else None
                        detail = annotation_change_reason(original, baseline_page, pixel_boxes, source_image, old, page_number=index + 1)
                    else:
                        detail = kept_annotation_problem(page, all_terms, index + 1)
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
                scope = 'PDF原生删改；默认保留批注，只删除框选正文。' if not clearing else 'PDF原生删改；已按明确选择清除批注，并做了严格像素复检。'
                return {'checks': checks, 'not_checked': [] if keep else ['keep_phrases_preserved'],
                        'effective_pages':plan.get('pages',[]),'output_sha256': engine.digest(data), 'scope': scope + '保留框外可搜索文字、位置和页面。仅核对已选区域及支持的隐藏载体。'}
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
