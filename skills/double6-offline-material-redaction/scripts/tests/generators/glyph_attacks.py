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
    raw, box = shifted_draw(0, -6)
    rows.append(_row("字形框-黑块上移6pt", "desync", raw, box, {"dy": -6}, "cover"))
    raw, box = shifted_draw(4, 0)
    rows.append(_row("字形框-黑块右移4pt", "desync", raw, box, {"dx": 4}, "tamper"))
    raw, box = _light_page(level=0.985)
    rows.append(_row("旧-浅色字-0.985", "old", raw, box, {"level": 0.985}, "light"))
    raw, box = _light_page(level=0.99)
    rows.append(_row("旧-浅色字-0.99", "old", raw, box, {"level": 0.99}, "invisible"))
    raw, box = _light_page(render_mode=3)
    rows.append(_row("旧-不可见文字层", "old", raw, box, {"render_mode": 3}, "invisible"))
    raw, box = _light_page(white_square=True)
    rows.append(_row("旧-白方块盖号码", "old", raw, box, {"fill": "white"}, "cover"))
    return rows
