"""复审里白底加笔画、框外小块和 UserUnit 组合。只在测试里生成，不提交 PDF。号码是虚构的。"""
import pymupdf as fitz

KEEP = "整理活动反馈"
SIDE = "DELETEME"
SECRET = "13800006661"
NEIGHBOR = "KEEPME"


def preview_box(page, text_rect):
    """用未缩放的显示页乘 2 得到预览框。不经过产品自己的旋转函数。"""
    crop = page.cropbox
    cw = abs(crop.x1 - crop.x0)
    ch = abs(crop.y1 - crop.y0)
    unit = page.rect.width / (ch if page.rotation in (90, 270) else cw)
    unscaled = fitz.Rect(text_rect.x0 / unit, text_rect.y0 / unit, text_rect.x1 / unit, text_rect.y1 / unit)
    mapped = unscaled * page.rotation_matrix
    return [mapped.x0 * 2 - 2, mapped.y0 * 2 - 2, mapped.x1 * 2 + 2, mapped.y1 * 2 + 2]


def _fresh(width=520, height=300, userunit=None, rotation=0, crop=None):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    if userunit is not None:
        doc.xref_set_key(page.xref, "UserUnit", str(userunit))
    if crop:
        page.set_cropbox(fitz.Rect(*crop))
    if rotation:
        page.set_rotation(rotation)
    return doc, page


def _to_pdf(page, rect):
    return fitz.Rect(rect) * ~page.transformation_matrix


def _write_square_ap(doc, page, annot, parts, bbox):
    ap = doc.xref_get_key(annot.xref, "AP")[1]
    tokens = ap.replace("<<", " ").replace(">>", " ").split()
    form = int(tokens[tokens.index("/N") + 1])
    doc.update_stream(form, ("\n".join(parts) + "\n").encode())
    box = _to_pdf(page, bbox)
    doc.xref_set_key(form, "BBox", "[%.3f %.3f %.3f %.3f]" % (box.x0, box.y0, box.x1, box.y1))
    doc.xref_set_key(form, "Matrix", "[1 0 0 1 0 0]")


def _black_rect_cmd(page, rect, gray=0):
    box = _to_pdf(page, rect)
    return "q %.3f g %.2f %.2f %.2f %.2f re f Q" % (gray, box.x0, box.y0, box.width, box.height)


def _add_digits(page, origin, size, text=SECRET):
    x, y = origin
    rects = []
    for char in text:
        page.insert_text((x, y), char, fontname="helv", fontsize=size)
        rects.append((char, fitz.Rect(page.get_texttrace()[-1]["chars"][-1][3])))
        x += max(size * 0.62, rects[-1][1].width + size * 0.08)
    return rects


def _ink_box(page, rect, threshold=70):
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), annots=False, alpha=False)
    samples = pix.samples
    width = pix.width
    x0 = max(0, int(rect.x0 * 2))
    y0 = max(0, int(rect.y0 * 2))
    x1 = min(width, int(rect.x1 * 2) + 1)
    y1 = min(pix.height, int(rect.y1 * 2) + 1)
    minx = miny = 10**9
    maxx = maxy = -1
    for y in range(y0, y1):
        row = y * width * pix.n
        for x in range(x0, x1):
            i = row + x * pix.n
            if samples[i] < threshold and samples[i + 1] < threshold and samples[i + 2] < threshold:
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return None
    return fitz.Rect(minx / 2, miny / 2, (maxx + 1) / 2, (maxy + 1) / 2)


def _page_chrome(page, phone_y, size):
    page.insert_text((16, 28), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 50), SIDE, fontname="helv", fontsize=12)
    y = 72
    for index in range(4):
        page.insert_text((16, y), "活动安排第%s行请核对名单与座位" % "甲乙丙丁戊己庚辛"[index], fontname="china-s", fontsize=11)
        y += 16
    return _add_digits(page, (18, phone_y), size)


def _annot_over(page, union, parts):
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=None)
    annot.update()
    _write_square_ap(page.parent, page, annot, parts, union)


def _wide_union(page, rects, width):
    return fitz.Rect(8, 60, min(width - 8, 500), rects[-1][1].y1 + 8)


def _row(name, group, raw, box, params, expect, keep=None):
    return {
        "name": name,
        "group": group,
        "raw": raw,
        "box": [float(value) for value in box],
        "params": params,
        "expect": expect,
        "keep": keep if keep is not None else [KEEP],
    }


def dilution(size=4, mode="wide", userunit=None, rotation=0, crop=None, width=520):
    doc, page = _fresh(width, 360, userunit, rotation, crop)
    page.insert_text((16, 28), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 50), SIDE, fontname="helv", fontsize=12)
    y = 72
    for index in range(5):
        page.insert_text((16, y), "活动安排第%s行请核对名单与座位" % "甲乙丙丁"[index % 4], fontname="china-s", fontsize=11)
        y += 16
    pairs = _add_digits(page, (16, y + 28), size)
    rects = [rect for _ch, rect in pairs]
    if mode == "tight":
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union.include_rect(rect)
        union = fitz.Rect(union.x0 - 0.4, union.y0 - 0.4, union.x1 + 0.4, union.y1 + 0.4)
    elif mode == "outside":
        union = fitz.Rect(width - 80, 16, width - 16, 56)
    else:
        union = fitz.Rect(8, 60, min(width - 8, 500), rects[-1].y1 + 6)
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=(0.85, 0.85, 0.85) if mode == "outside" else None)
    annot.update()
    parts = []
    if mode == "outside":
        gray = _to_pdf(page, union)
        parts.append("q 0.85 g %.2f %.2f %.2f %.2f re f Q" % (gray.x0, gray.y0, gray.width, gray.height))
    targets = rects if mode != "one" else rects[:1]
    pad = max(0.15, size * 0.04)
    if mode == "split":
        for rect in rects:
            mid = (rect.y0 + rect.y1) / 2
            parts.append(_black_rect_cmd(page, fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, mid - 0.3)))
            parts.append(_black_rect_cmd(page, fitz.Rect(rect.x0 - pad, mid + 0.3, rect.x1 + pad, rect.y1 + pad)))
    else:
        for rect in targets:
            parts.append(_black_rect_cmd(page, fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)))
    _write_square_ap(doc, page, annot, parts, union)
    side = page.search_for(SIDE)[0]
    box = preview_box(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def disguise(kind, hairline_pt=0.35):
    """在原来是白的地方加黑，位置按渲染出来的字迹框计算。"""
    doc, page = _fresh(640, 320)
    pairs = _page_chrome(page, 230, 36)
    inks = []
    for char, rect in pairs:
        inks.append((char, rect, _ink_box(page, rect)))
    parts = []
    for char, rect, ink in inks:
        if ink is None:
            continue
        width = ink.width
        height = ink.height
        if kind == "close3" and char == "3":
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 - 0.02 * width, ink.y0 + 0.08 * height, ink.x0 + 0.22 * width, ink.y1 - 0.08 * height)))
        elif kind == "hairline" and char == "3":
            parts.append(_black_rect_cmd(page, fitz.Rect(
                ink.x0 + 0.02 * width,
                ink.y0 + 0.08 * height,
                ink.x0 + 0.02 * width + hairline_pt,
                ink.y1 - 0.08 * height,
            )))
        elif kind == "flag1" and char == "1":
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 - 0.15 * width, ink.y0 - 0.02 * height, ink.x1 + 0.55 * width, ink.y0 + 0.20 * height)))
        elif kind == "counters" and char in "0689":
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 + 0.22 * width, ink.y0 + 0.16 * height, ink.x1 - 0.22 * width, ink.y1 - 0.16 * height)))
        elif kind == "center" and char != "1":
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 + 0.35 * width, ink.y0 + 0.35 * height, ink.x1 - 0.35 * width, ink.y1 - 0.35 * height)))
        elif kind == "inset" and char != "1":
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 + 0.28 * width, ink.y0 + 0.22 * height, ink.x1 - 0.28 * width, ink.y1 - 0.22 * height)))
        elif kind == "all":
            if char == "3":
                parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 - 0.04 * width, ink.y0 + 0.06 * height, ink.x0 + 0.28 * width, ink.y1 - 0.06 * height)))
            elif char == "1":
                parts.append(_black_rect_cmd(page, fitz.Rect(ink.x1 - 0.05 * width, ink.y0 - 0.02 * height, ink.x1 + 0.85 * width, ink.y0 + 0.18 * height)))
            else:
                parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 + 0.18 * width, ink.y0 + 0.12 * height, ink.x1 - 0.18 * width, ink.y1 - 0.12 * height)))
    if kind == "gap":
        for index in range(len(inks) - 1):
            left = inks[index][2]
            right = inks[index + 1][2]
            if left is None or right is None:
                continue
            gap = fitz.Rect(left.x1 + 0.4, left.y0, right.x0 - 0.4, left.y1)
            if gap.width > 1:
                mid = fitz.Rect(gap.x0, gap.y0 + gap.height * 0.35, gap.x1, gap.y0 + gap.height * 0.65)
                parts.append(_black_rect_cmd(page, mid))
    if kind == "low":
        for _char, _rect, ink in inks:
            if ink is None:
                continue
            parts.append(_black_rect_cmd(page, fitz.Rect(ink.x0 - 1, ink.y0 - 1, ink.x1 + 1, ink.y1 + 1), gray=0.55))
    union = _wide_union(page, [(char, rect) for char, rect, _ink in inks], 640)
    if parts:
        _annot_over(page, union, parts)
    side = page.search_for(SIDE)[0]
    box = preview_box(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def plain_phone(userunit=None, cover=False, rotation=0, crop=None, neighbor=NEIGHBOR):
    doc, page = _fresh(420, 300, userunit, rotation=0, crop=None)
    page.insert_text((24, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((24, 240), neighbor, fontname="helv", fontsize=14)
    page.insert_text((24, 120), SECRET, fontname="helv", fontsize=16)
    if crop:
        page.set_cropbox(fitz.Rect(*crop))
    if rotation:
        page.set_rotation(rotation)
    phone = page.search_for(SECRET)
    if cover and phone:
        pad = fitz.Rect(phone[0].x0 - 2, phone[0].y0 - 2, phone[0].x1 + 2, phone[0].y1 + 2)
        annot = page.add_rect_annot(pad)
        annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        annot.set_border(width=0)
        annot.update()
    target = page.search_for(SECRET if not cover else neighbor)
    if not target:
        target = page.search_for(KEEP)
    box = preview_box(page, target[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def tiny_glyph(size, cover):
    doc, page = _fresh(420, 240)
    page.insert_text((16, 36), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 58), SIDE, fontname="helv", fontsize=12)
    page.insert_text((16, 150), "活动安排核对名单", fontname="china-s", fontsize=12)
    page.insert_text((16, 190), SECRET, fontname="helv", fontsize=size)
    union = fitz.Rect(8, 120, 400, 220)
    if cover:
        pairs = []
        for span in page.get_texttrace():
            for char in span["chars"]:
                if chr(char[0]).isdigit():
                    pairs.append(fitz.Rect(char[3]))
        parts = [_black_rect_cmd(page, fitz.Rect(rect.x0 - 0.3, rect.y0 - 0.3, rect.x1 + 0.3, rect.y1 + 0.3)) for rect in pairs]
        _annot_over(page, union, parts)
    else:
        annot = page.add_highlight_annot(fitz.Rect(8, 130, 200, 170))
        annot.update()
    box = preview_box(page, page.search_for(SIDE)[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def outside_tiles(tile):
    """批注矩形留在页边。外观试图在号码上画黑块，但画在外观框以外。"""
    doc, page = _fresh(520, 300)
    pairs = _page_chrome(page, 200, 28)
    union = fitz.Rect(430, 16, 500, 70)
    gray = _to_pdf(page, union)
    parts = ["q 0.8 g %.2f %.2f %.2f %.2f re f Q" % (gray.x0, gray.y0, gray.width, gray.height)]
    for _ch, rect in pairs:
        if tile == "4pt":
            mark = fitz.Rect(rect.x0, rect.y0, rect.x0 + 2, rect.y0 + 4)
        elif tile == "10px":
            mark = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + 4)
        else:
            mark = fitz.Rect(rect.x0 - 0.4, rect.y0 - 0.4, rect.x1 + 0.4, rect.y1 + 0.4)
        parts.append(_black_rect_cmd(page, mark))
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=(0.8, 0.8, 0.8))
    annot.update()
    _write_square_ap(doc, page, annot, parts, union)
    box = preview_box(page, page.search_for(SIDE)[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def tz_case(scale=0.45, rise=0, spacing=0):
    """用 Tz / Ts / Tc 画出号码，高亮只盖在上面的正文上。"""
    doc, page = _fresh(520, 280)
    page.insert_text((16, 28), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 52), SIDE, fontname="helv", fontsize=12)
    page.insert_text((16, 90), "活动安排请核对名单", fontname="china-s", fontsize=12)
    pdf_y = 280 - 170
    stream = "BT /helv 32 Tf %.2f Tc %.2f Tz %.2f Ts 1 0 0 1 18 %.2f Tm (%s) Tj ET" % (
        spacing, scale * 100, rise, pdf_y, SECRET,
    )
    xref = page.get_contents()[-1]
    existing = doc.xref_stream(xref)
    doc.update_stream(xref, existing + b"\n" + stream.encode())
    annot = page.add_highlight_annot(fitz.Rect(16, 78, 220, 108))
    annot.update()
    box = preview_box(page, page.search_for(SIDE)[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def shifted_draw(dx, dy):
    doc, page = _fresh(560, 300)
    page.insert_text((16, 28), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 52), SIDE, fontname="helv", fontsize=12)
    page.insert_text((16, 90), "活动安排请核对名单", fontname="china-s", fontsize=12)
    writer = fitz.TextWriter(page.rect)
    writer.append((18, 300 - 180), SECRET, font=fitz.Font("helv"), fontsize=34)
    writer.write_text(page)
    pairs = []
    for span in page.get_texttrace():
        for char in span["chars"]:
            if chr(char[0]).isdigit():
                pairs.append(fitz.Rect(char[3]))
    parts = []
    for rect in pairs:
        ink = _ink_box(page, fitz.Rect(rect.x0 - 8, rect.y0 - 8, rect.x1 + 20, rect.y1 + 12))
        target = ink or rect
        moved = fitz.Rect(target.x0 + dx, target.y0 + dy, target.x1 + dx, target.y1 + dy)
        parts.append(_black_rect_cmd(page, moved))
    _annot_over(page, fitz.Rect(8, 70, 540, 230), parts)
    box = preview_box(page, page.search_for(SIDE)[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def _light_page(level=None, render_mode=0, white_square=False):
    doc, page = _fresh(400, 280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 80), SIDE, fontname="helv", fontsize=14)
    kwargs = {"fontname": "helv", "fontsize": 16}
    if level is not None:
        kwargs["color"] = (level, level, level)
    if render_mode:
        kwargs["render_mode"] = render_mode
    page.insert_text((20, 160), SECRET, **kwargs)
    if white_square:
        phone = page.search_for(SECRET)[0]
        annot = page.add_rect_annot(fitz.Rect(phone.x0 - 1, phone.y0 - 1, phone.x1 + 1, phone.y1 + 1))
        annot.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
        annot.set_border(width=0)
        annot.update()
    box = preview_box(page, page.search_for(SIDE)[0])
    raw = doc.tobytes()
    doc.close()
    return raw, box


def _selection_of(page, rect):
    return preview_box(page, rect)


def strikeout_on_selected_word():
    """删除线只画在被选词上。这些字形会随涂黑去掉。"""
    doc, page = _fresh(420, 280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 100), SIDE, fontname="helv", fontsize=16)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=16)
    side = page.search_for(SIDE)[0]
    page.add_strikeout_annot(side).update()
    box = _selection_of(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def strikeout_extends_outside():
    """删除线从被选词延伸到同一行选区外的词上。"""
    doc, page = _fresh(520, 280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 120), SIDE, fontname="helv", fontsize=16)
    side = page.search_for(SIDE)[0]
    page.insert_text((side.x1 + 4, 120), NEIGHBOR, fontname="helv", fontsize=16)
    page.insert_text((20, 200), SECRET, fontname="helv", fontsize=16)
    neighbor = page.search_for(NEIGHBOR)[0]
    union = fitz.Rect(side.x0, min(side.y0, neighbor.y0), neighbor.x1, max(side.y1, neighbor.y1))
    page.add_strikeout_annot(union).update()
    box = _selection_of(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def strikeout_rewrites_outside_digit():
    """删除线的外观在选区外的 3 左侧加一竖，把字形改掉。"""
    doc, page = _fresh(640, 320)
    pairs = _page_chrome(page, 230, 36)
    parts = []
    for char, rect in pairs:
        ink = _ink_box(page, rect)
        if ink is None or char != "3":
            continue
        parts.append(_black_rect_cmd(page, fitz.Rect(
            ink.x0 - 0.02 * ink.width,
            ink.y0 + 0.08 * ink.height,
            ink.x0 + 0.22 * ink.width,
            ink.y1 - 0.08 * ink.height,
        )))
    union = _wide_union(page, pairs, 640)
    annot = page.add_strikeout_annot(union)
    annot.update()
    _write_square_ap(doc, page, annot, parts, union)
    side = page.search_for(SIDE)[0]
    box = _selection_of(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def strikeout_cut_through_glyph():
    """选区右边界切在被删除线穿过的字形中间。"""
    doc, page = _fresh(520, 280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=28)
    phone = page.search_for(SECRET)[0]
    page.add_strikeout_annot(phone).update()
    first = None
    for span in page.get_texttrace():
        for char in span["chars"]:
            if chr(char[0]).isdigit():
                first = fitz.Rect(char[3])
                break
        if first is not None:
            break
    full = _selection_of(page, first)
    mid = (full[0] + full[2]) / 2
    box = [full[0], full[1], mid, full[3]]
    raw = doc.tobytes()
    doc.close()
    return raw, box


def _stem_on_three(page, pairs, gray=0, rgb=None):
    parts = []
    for char, rect in pairs:
        if char != "3":
            continue
        ink = _ink_box(page, rect, threshold=40)
        if ink is None:
            continue
        bar = fitz.Rect(
            ink.x0 - 0.02 * ink.width,
            ink.y0 + 0.08 * ink.height,
            ink.x0 + 0.28 * ink.width,
            ink.y1 - 0.08 * ink.height,
        )
        if rgb:
            box = _to_pdf(page, bar)
            parts.append(
                "q %.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f Q"
                % (rgb[0], rgb[1], rgb[2], box.x0, box.y0, box.width, box.height)
            )
        else:
            parts.append(_black_rect_cmd(page, bar, gray))
    return parts


def _blend_stem_parts(page, pairs, rgb=None, gray=0.0, width_ratio=0.22):
    """用字形框而不是墨迹框，在「3」左侧开口上画一条会走 ExtGState 的竖条。"""
    parts = []
    color = rgb if rgb is not None else (gray, gray, gray)
    for char, rect in pairs:
        if char != "3":
            continue
        bar = fitz.Rect(
            rect.x0,
            rect.y0 + rect.height * 0.08,
            rect.x0 + max(rect.width * width_ratio, 0.4),
            rect.y1 - rect.height * 0.08,
        )
        box = _to_pdf(page, bar)
        parts.append(
            "q /GS1 gs %.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f Q"
            % (color[0], color[1], color[2], box.x0, box.y0, box.width, box.height)
        )
    return parts


def _install_extgstate(doc, annot, opacity):
    """外观流里的真半透明。批注字典上的 CA 同时写上，和复审漏脱是同一份构造。

    只写批注字典、外观仍是不透明墨时，现有检查会拒绝。绕过中点的是这里的 ExtGState。
    """
    ap = doc.xref_get_key(annot.xref, "AP")[1]
    tokens = ap.replace("<<", " ").replace(">>", " ").split()
    form = int(tokens[tokens.index("/N") + 1])
    gs = doc.get_new_xref()
    doc.update_object(gs, "<< /Type /ExtGState /ca %.3f /CA %.3f >>" % (opacity, opacity))
    doc.xref_set_key(form, "Resources", "<< /ExtGState << /GS1 %d 0 R >> >>" % gs)
    doc.xref_set_key(annot.xref, "CA", str(opacity))
    doc.xref_set_key(annot.xref, "ca", str(opacity))


def opening_seal(size, opacity=1.0, width_ratio=0.08, x_pad=1.2, segments=1, char="3"):
    """在号码某个字的开口上画细竖条。几何和复审漏脱一致。

    起点比字形框左缘再往右 x_pad 点，宽度至少 0.35 点、否则按字宽的 width_ratio。
    竖向两端各让出字高的 8%。不透明度写在外观流的 ExtGState 里，1 也写，和复审样例同一份构造。
    segments 大于 1 时把这一条拆成几段短线，段与段之间留一条缝。缝本身很短，拼起来仍是封口。
    """
    doc, page = _fresh(640, 360)
    pairs = _page_chrome(page, 250, size)
    union = _wide_union(page, pairs, 640)
    parts = []
    for text, rect in pairs:
        if text != char:
            continue
        full = fitz.Rect(
            rect.x0 + x_pad,
            rect.y0 + rect.height * 0.08,
            rect.x0 + max(rect.width * width_ratio, 0.35) + x_pad,
            rect.y1 - rect.height * 0.08,
        )
        bars = [full]
        if segments > 1 and full.height > 0:
            gap = full.height * 0.06
            piece = (full.height - gap * (segments - 1)) / segments
            if piece > 0.15:
                bars = []
                top = full.y0
                for _index in range(segments):
                    bars.append(fitz.Rect(full.x0, top, full.x1, top + piece))
                    top += piece + gap
        for bar in bars:
            box = _to_pdf(page, bar)
            parts.append(
                "q /GS1 gs 0 0 0 rg %.2f %.2f %.2f %.2f re f Q"
                % (box.x0, box.y0, box.width, box.height)
            )
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=None)
    annot.update()
    _write_square_ap(doc, page, annot, parts, union)
    _install_extgstate(doc, annot, opacity)
    side = page.search_for(SIDE)[0]
    preview = preview_box(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, preview


def small_seal_cases():
    """复审漏掉的小字封口，再加上 5–12 pt 细线和贴边多段短线。"""
    rows = []
    named = (
        ("小字6pt封口", 6, 1.0, 0.12, 1.2, 1),
        ("小字9pt封口", 9, 1.0, 0.08, 1.2, 1),
        ("小字9pt略宽", 9, 1.0, 0.08, 0.8, 1),
        ("细线小字过2px-0.80", 8, 0.80, 0.12, 1.6, 1),
    )
    for name, size, opacity, ratio, pad, segments in named:
        raw, box = opening_seal(size, opacity, ratio, pad, segments)
        rows.append(_row(
            name,
            "small-seal",
            raw,
            box,
            {"size": size, "opacity": opacity, "width_ratio": ratio, "x_pad": pad, "segments": segments},
            "tamper",
        ))
    for size in range(5, 13):
        raw, box = opening_seal(size, 1.0, 0.08, 1.2, 1)
        rows.append(_row(
            "小字%dpt不透明细线" % size,
            "small-seal",
            raw,
            box,
            {"size": size, "opacity": 1.0, "width_ratio": 0.08, "x_pad": 1.2, "segments": 1},
            "tamper",
        ))
        raw, box = opening_seal(size, 0.80, 0.12, 1.6, 1)
        rows.append(_row(
            "小字%dpt半透明0.80细线" % size,
            "small-seal",
            raw,
            box,
            {"size": size, "opacity": 0.80, "width_ratio": 0.12, "x_pad": 1.6, "segments": 1},
            "tamper",
        ))
        raw, box = opening_seal(size, 0.45, 0.12, 1.2, 1)
        rows.append(_row(
            "小字%dpt半透明0.45细线" % size,
            "small-seal",
            raw,
            box,
            {"size": size, "opacity": 0.45, "width_ratio": 0.12, "x_pad": 1.2, "segments": 1},
            "tamper",
        ))
    for size, segments in ((6, 4), (9, 4), (12, 5)):
        raw, box = opening_seal(size, 1.0, 0.08, 1.2, segments)
        rows.append(_row(
            "小字%dpt-%d段短线拼封口" % (size, segments),
            "small-seal",
            raw,
            box,
            {"size": size, "opacity": 1.0, "width_ratio": 0.08, "x_pad": 1.2, "segments": segments},
            "tamper",
        ))
    raw, box = opening_seal(8, 0.80, 0.12, 1.2, 4)
    rows.append(_row(
        "小字8pt-4段半透明短线",
        "small-seal",
        raw,
        box,
        {"size": 8, "opacity": 0.80, "width_ratio": 0.12, "x_pad": 1.2, "segments": 4},
        "tamper",
    ))
    return rows


def _annot_bars(doc, page, pairs, bars, rgb, opacity, tight):
    """把若干矩形写进一条批注的外观。tight 时批注框就是这些矩形，否则用盖住号码行的宽框。"""
    union = fitz.Rect(bars[0])
    for bar in bars[1:]:
        union.include_rect(bar)
    if not tight:
        union = _wide_union(page, pairs, max(page.rect.width, union.x1 + 8))
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=None)
    annot.update()
    parts = []
    for bar in bars:
        box = _to_pdf(page, bar)
        parts.append(
            "q /GS1 gs %.4f %.4f %.4f rg %.2f %.2f %.2f %.2f re f Q"
            % (rgb[0], rgb[1], rgb[2], box.x0, box.y0, box.width, box.height)
        )
    _write_square_ap(doc, page, annot, parts, union)
    _install_extgstate(doc, annot, opacity)
    side = page.search_for(SIDE)[0]
    return doc.tobytes(), preview_box(page, side)


def _erase_rect(rect, part):
    """字框上要抹掉的一块。左竖笔和复审漏脱用同一份 42% 宽的白矩形。"""
    if part == "left":
        return fitz.Rect(
            rect.x0 - 0.2,
            rect.y0 + rect.height * 0.05,
            rect.x0 + rect.width * 0.42,
            rect.y1 - rect.height * 0.05,
        )
    if part == "right":
        return fitz.Rect(
            rect.x0 + rect.width * 0.55,
            rect.y0 + rect.height * 0.05,
            rect.x1 + 0.2,
            rect.y1 - rect.height * 0.05,
        )
    if part == "top":
        return fitz.Rect(
            rect.x0 - 0.1,
            rect.y0 - 0.1,
            rect.x1 + 0.1,
            rect.y0 + rect.height * 0.32,
        )
    if part == "middle":
        return fitz.Rect(
            rect.x0 + rect.width * 0.05,
            rect.y0 + rect.height * 0.40,
            rect.x1 - rect.width * 0.05,
            rect.y0 + rect.height * 0.62,
        )
    raise ValueError(part)


def whiteout_page(size, char, part, rgb=(1, 1, 1), opacity=1.0, tight=False):
    """在号码或旁边的字母上涂一块，用来抹掉笔画。宽批注盖住整行，紧批注只盖这块。"""
    doc, page = _fresh(640, 360)
    pairs = _page_chrome(page, 250, size)
    target = None
    for text, rect in pairs:
        if text == char:
            target = rect
            break
    if target is None:
        page.insert_text((220, 250), char, fontname="helv", fontsize=size)
        target = fitz.Rect(page.get_texttrace()[-1]["chars"][-1][3])
        pairs = list(pairs) + [(char, target)]
    bar = _erase_rect(target, part)
    raw, box = _annot_bars(doc, page, pairs, [bar], rgb, opacity, tight)
    doc.close()
    return raw, box


def whiteout_cases():
    """复审漏掉的小号涂白，再加上 8 的其它部位、B 改成 3 或 8、半透明白和浅灰。"""
    rows = []

    def add(name, size, char, part, rgb=(1, 1, 1), opacity=1.0, tight=False, expect="tamper"):
        raw, box = whiteout_page(size, char, part, rgb, opacity, tight)
        rows.append(_row(
            name,
            "whiteout",
            raw,
            box,
            {
                "size": size,
                "char": char,
                "part": part,
                "rgb": [round(value, 3) for value in rgb],
                "opacity": opacity,
                "tight": tight,
            },
            expect,
        ))

    for size in (7, 9, 10):
        add("擦左8-%dpt" % size, size, "8", "left")
    # 紧框和盖住大半个字的白块，存活率或两种渲染会先拒绝。变亮计数仍然要达到 6。
    add("擦左8-9pt-紧框", 9, "8", "left", tight=True, expect="refuse")
    add("擦右8-9pt", 9, "8", "right", expect="refuse")
    add("擦顶8-9pt", 9, "8", "top", expect="refuse")
    add("擦中8-9pt", 9, "8", "middle")
    add("涂白B左竖改成3-9pt", 9, "B", "left")
    add("涂白B左竖改成3-9pt-紧框", 9, "B", "left", tight=True, expect="refuse")
    add("涂白B中横改成8-9pt", 9, "B", "middle")
    add("涂白B中横改成8-9pt-紧框", 9, "B", "middle", tight=True, expect="refuse")
    add("半透明白0.45擦左8-9pt", 9, "8", "left", opacity=0.45)
    add("半透明白0.70擦左8-9pt", 9, "8", "left", opacity=0.70)
    gray180 = (180 / 255.0,) * 3
    gray210 = (210 / 255.0,) * 3
    add("浅灰180擦左8-9pt", 9, "8", "left", rgb=gray180)
    add("浅灰210擦左8-9pt", 9, "8", "left", rgb=gray210)
    add("浅灰180擦左8-9pt-紧框", 9, "8", "left", rgb=gray180, tight=True)
    return rows


def contrast_page(bg=None, gray=0, rgb=None, opacity=None, paint="stem", fill_after_text=False, blend=False):
    """整页底色、中灰或彩色竖条、半透明，以及铺色画在字前还是字后。选区只框 DELETEME。

    blend 为真时，竖条的不透明度写在外观流的 ExtGState 里，不靠 annot.set_opacity。
    """
    doc, page = _fresh(640, 340)
    if bg is not None and not fill_after_text:
        level = bg / 255.0
        page.draw_rect(page.rect, color=None, fill=(level, level, level))
    pairs = _page_chrome(page, 250, 36)
    if fill_after_text:
        level = (bg if bg is not None else 40) / 255.0
        page.draw_rect(page.rect, color=None, fill=(level, level, level))
        # 页边便签让复检真的去看这条铺色。铺色本身不是批注。
        page.add_text_annot(fitz.Point(600, 28), "核对").update()
    parts = []
    if paint == "stem" and blend:
        parts = _blend_stem_parts(page, pairs, rgb=rgb, gray=0.0 if rgb is not None else gray)
    elif paint == "stem":
        parts = _stem_on_three(page, pairs, gray, rgb)
    elif paint == "appearance-fill":
        level = (bg if bg is not None else 40) / 255.0
        box = _to_pdf(page, page.rect)
        parts.append("q %.3f g %.2f %.2f %.2f %.2f re f Q" % (level, box.x0, box.y0, box.width, box.height))
    elif paint == "highlight":
        page.add_highlight_annot(page.search_for(KEEP)[0]).update()
    union = _wide_union(page, pairs, 640)
    if parts:
        annot = page.add_rect_annot(union)
        annot.set_border(width=0)
        annot.set_colors(stroke=None, fill=None)
        annot.update()
        if blend:
            _write_square_ap(doc, page, annot, parts, union)
            _install_extgstate(doc, annot, opacity)
        else:
            if opacity is not None:
                annot.set_opacity(opacity)
                annot.update()
            _write_square_ap(doc, page, annot, parts, union)
            if opacity is not None:
                doc.xref_set_key(annot.xref, "CA", str(opacity))
                doc.xref_set_key(annot.xref, "ca", str(opacity))
    side = page.search_for(SIDE)[0]
    box = preview_box(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def attack_cases():
    """复审第二轮的额外样例，再加上一条 0.35 磅细线封口。"""
    rows = []
    for size in (1.5, 2, 3, 4, 22):
        raw, box = dilution(size=size, mode="wide")
        expect = "invalid" if size < 3 else "cover"
        rows.append(_row("稀释-整字黑块-%spt" % size, "p1", raw, box, {"size": size, "mode": "wide"}, expect))
    for mode, label, expect in (
        ("split", "对半切开", "cover"),
        ("one", "只盖第一字", "cover"),
        ("tight", "框就等于黑块", "cover"),
        ("outside", "框在页边黑块在字上", "visible"),
    ):
        raw, box = dilution(size=8, mode=mode)
        rows.append(_row("稀释-%s" % label, "p1", raw, box, {"size": 8, "mode": mode}, expect))
    raw, box = dilution(size=8, mode="wide", rotation=90, width=420)
    rows.append(_row("稀释-旋转90", "p1", raw, box, {"size": 8, "rotation": 90}, "cover"))
    raw, box = dilution(size=8, mode="wide", userunit=2)
    rows.append(_row("稀释-UserUnit2", "p1", raw, box, {"size": 8, "userunit": 2}, "cover"))
    raw, box = dilution(size=8, mode="wide", userunit=2.5)
    rows.append(_row("稀释-UserUnit2.5", "p1", raw, box, {"size": 8, "userunit": 2.5}, "cover"))
    raw, box = dilution(size=8, mode="wide", width=1200)
    rows.append(_row("稀释-页宽1200", "p1", raw, box, {"size": 8, "width": 1200}, "cover"))
    raw, box = dilution(size=8, mode="wide", crop=(10, 10, 500, 340), width=520)
    rows.append(_row("稀释-CropBox", "p1", raw, box, {"size": 8, "crop": [10, 10, 500, 340]}, "cover"))
    for kind, name, expect in (
        ("close3", "改字-3左侧封口", "tamper"),
        ("flag1", "改字-1加顶横", "tamper"),
        ("counters", "改字-填孔", "tamper"),
        ("all", "改字-封口加顶横再填孔", "tamper"),
        ("center", "只涂字形中心", "tamper"),
        ("gap", "字间黑块", "tamper"),
        ("inset", "只涂内部留边缘", "tamper"),
        ("hairline", "改字-细线封口", "tamper"),
        ("low", "低对比灰0.55整字", "cover"),
    ):
        raw, box = disguise(kind)
        rows.append(_row(name, "glyph", raw, box, {"kind": kind}, expect))
    for size, cover, name, expect in (
        (1.2, True, "没法对齐-1.2pt盖住", "invalid"),
        (2, True, "没法对齐-2pt盖住", "invalid"),
        (3, True, "没法对齐-3pt盖住", "cover"),
        (1.2, False, "没法对齐-1.2pt高亮在旁边", "aside"),
        (8, True, "没法对齐-对照8pt盖住", "cover"),
    ):
        raw, box = tiny_glyph(size, cover)
        rows.append(_row(name, "align", raw, box, {"size": size, "cover": cover}, expect))
    for unit in (1.25, 1.5, 2.5, 3, 0.5, 2):
        for rotation, crop, tag in (
            (0, None, "无旋转"),
            (90, None, "旋转90"),
            (0, (12, 12, 400, 280), "CropBox"),
            (90, (12, 12, 400, 280), "旋转加CropBox"),
        ):
            keep = [KEEP, NEIGHBOR]
            params = {"userunit": unit, "rotation": rotation, "crop": crop, "cover": False}
            raw, box = plain_phone(userunit=unit, cover=False, rotation=rotation, crop=crop)
            if tag == "旋转加CropBox":
                expect = "crop-rotation"
            elif unit < 1:
                expect = "userunit-low"
            else:
                expect = "redact"
            rows.append(_row("UserUnit%s-%s-框住号码" % (unit, tag), "userunit", raw, box, params, expect, keep))
            raw, box = plain_phone(userunit=unit, cover=True, rotation=rotation, crop=crop)
            covered = dict(params, cover=True)
            covered_expect = "crop-rotation" if tag == "旋转加CropBox" else "cover"
            rows.append(_row("UserUnit%s-%s-黑框盖住号码" % (unit, tag), "userunit", raw, box, covered, covered_expect, keep))
    for tile, name in (("4pt", "框外-4pt黑块"), ("10px", "框外-长边约8px"), ("full", "框外-整字黑块")):
        raw, box = outside_tiles(tile)
        rows.append(_row(name, "outside", raw, box, {"tile": tile}, "visible"))
    raw, box = tz_case(0.45, 0, 0)
    rows.append(_row("字形框-Tz45", "desync", raw, box, {"tz": 45}, "visible"))
    raw, box = tz_case(1.8, 0, 0)
    rows.append(_row("字形框-Tz180", "desync", raw, box, {"tz": 180}, "visible"))
    raw, box = tz_case(1, 8, 0)
    rows.append(_row("字形框-Ts上升8", "desync", raw, box, {"ts": 8}, "visible"))
    raw, box = tz_case(1, 0, 6)
    rows.append(_row("字形框-字距6", "desync", raw, box, {"tc": 6}, "visible"))
    # Windows 上这两处仍拒绝，但说法可能是两种渲染看不一致，不要求必须写成盖住了或加了深色。
    raw, box = shifted_draw(0, -6)
    rows.append(_row("字形框-黑块上移6pt", "desync", raw, box, {"dy": -6}, "refuse"))
    raw, box = shifted_draw(4, 0)
    rows.append(_row("字形框-黑块右移4pt", "desync", raw, box, {"dx": 4}, "refuse"))
    raw, box = _light_page(level=0.985)
    rows.append(_row("旧-浅色字-0.985", "old", raw, box, {"level": 0.985}, "light"))
    raw, box = _light_page(level=0.99)
    rows.append(_row("旧-浅色字-0.99", "old", raw, box, {"level": 0.99}, "invisible"))
    raw, box = _light_page(render_mode=3)
    rows.append(_row("旧-不可见文字层", "old", raw, box, {"render_mode": 3}, "invisible"))
    raw, box = _light_page(white_square=True)
    rows.append(_row("旧-白方块盖号码", "old", raw, box, {"fill": "white"}, "cover"))
    for bg in (150, 160, 175, 200):
        raw, box = contrast_page(bg=bg, gray=0)
        rows.append(_row("灰底%d黑封口" % bg, "contrast", raw, box, {"bg": bg, "ink": "black"}, "tamper"))
        raw, box = contrast_page(bg=bg, gray=110 / 255)
        rows.append(_row("灰底%d中灰封口" % bg, "contrast", raw, box, {"bg": bg, "ink": 110}, "tamper"))
    for level in (97, 110, 120, 140):
        raw, box = contrast_page(gray=level / 255)
        rows.append(_row("白纸墨色%d" % level, "contrast", raw, box, {"ink": level}, "tamper"))
    raw, box = contrast_page(rgb=(220 / 255, 50 / 255, 40 / 255))
    rows.append(_row("白纸暗红封口", "contrast", raw, box, {"rgb": [220, 50, 40]}, "tamper"))
    raw, box = contrast_page(rgb=(200 / 255, 90 / 255, 40 / 255))
    rows.append(_row("白纸橙色封口", "contrast", raw, box, {"rgb": [200, 90, 40]}, "tamper"))
    for opacity in (0.40, 0.55, 0.75):
        raw, box = contrast_page(gray=0, opacity=opacity)
        rows.append(_row("半透明%.2f黑封口" % opacity, "contrast", raw, box, {"opacity": opacity}, "tamper"))
    for opacity in (0.25, 0.35, 0.45, 0.50, 0.55):
        raw, box = contrast_page(gray=0, opacity=opacity, blend=True)
        rows.append(_row(
            "真半透明%.2f" % opacity,
            "contrast",
            raw,
            box,
            {"opacity": opacity, "blend": "ExtGState", "width_ratio": 0.22},
            "tamper",
        ))
    raw, box = contrast_page(gray=110 / 255, opacity=0.45, blend=True)
    rows.append(_row("半透明灰竖条", "contrast", raw, box, {"ink": 110, "opacity": 0.45, "blend": "ExtGState"}, "tamper"))
    raw, box = contrast_page(rgb=(220 / 255, 50 / 255, 40 / 255), opacity=0.45, blend=True)
    rows.append(_row("半透明红竖条", "contrast", raw, box, {"rgb": [220, 50, 40], "opacity": 0.45, "blend": "ExtGState"}, "tamper"))
    raw, box = contrast_page(bg=160, gray=0, opacity=0.45, blend=True)
    rows.append(_row("整页灰底半透明黑竖条", "contrast", raw, box, {"bg": 160, "opacity": 0.45, "blend": "ExtGState"}, "tamper"))
    raw, box = contrast_page(bg=160, gray=0, opacity=0.25, blend=True)
    rows.append(_row("整页灰底半透明黑竖条0.25", "contrast", raw, box, {"bg": 160, "opacity": 0.25, "blend": "ExtGState"}, "tamper"))
    raw, box = contrast_page(bg=160, paint="highlight")
    rows.append(_row("灰底160上的高亮", "contrast", raw, box, {"bg": 160, "paint": "highlight"}, "light"))
    raw, box = contrast_page(bg=40, fill_after_text=True, paint="none")
    rows.append(_row("铺色画在文字之后", "contrast", raw, box, {"order": "after-text"}, "later-fill"))
    raw, box = contrast_page(bg=40, paint="appearance-fill")
    rows.append(_row("外观铺满并压过中点", "contrast", raw, box, {"paint": "appearance"}, "refuse"))
    return rows
