"""复审用的稀释遮盖和 UserUnit 样例。只在测试里生成，不提交 PDF。号码是虚构的。"""
import pymupdf as fitz

KEEP = "整理活动反馈"
SIDE = "DELETEME"
SECRET = "13800006661"
NEIGHBOR = "KEEPME"


def preview_box(page, text_rect):
    """用 pdfium 的未缩放显示页乘 2 得到预览框。不经过产品自己的旋转函数。"""
    crop = page.cropbox
    cw = abs(crop.x1 - crop.x0)
    ch = abs(crop.y1 - crop.y0)
    unit = page.rect.width / (ch if page.rotation in (90, 270) else cw)
    unscaled = fitz.Rect(text_rect.x0 / unit, text_rect.y0 / unit, text_rect.x1 / unit, text_rect.y1 / unit)
    mapped = unscaled * page.rotation_matrix
    return [mapped.x0 * 2 - 2, mapped.y0 * 2 - 2, mapped.x1 * 2 + 2, mapped.y1 * 2 + 2]


def _fresh(width=420, height=320, userunit=None, rotation=0, crop=None):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    if userunit:
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
    doc.xref_set_key(form, "BBox", "[%.2f %.2f %.2f %.2f]" % (box.x0, box.y0, box.x1, box.y1))
    doc.xref_set_key(form, "Matrix", "[1 0 0 1 0 0]")


def _add_digits(page, origin, size):
    x, y = origin
    rects = []
    for char in SECRET:
        page.insert_text((x, y), char, fontname="helv", fontsize=size)
        rects.append(fitz.Rect(page.get_texttrace()[-1]["chars"][-1][3]))
        x += max(size * 0.75, rects[-1].width + 1.2)
    return rects


def _black_tile(page, rect, pad=0.45):
    tile = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    box = _to_pdf(page, tile)
    return "q 0 g %.2f %.2f %.2f %.2f re f Q" % (box.x0, box.y0, box.width, box.height)


def dilution(size=4, lines=6, mode="wide", userunit=None, rotation=0, crop=None, width=420):
    """大方块批注里留着大段可读文字，外观只在数字上盖互不连通的小黑块。"""
    doc, page = _fresh(width, 340, userunit, rotation, crop)
    page.insert_text((16, 28), KEEP, fontname="china-s", fontsize=13)
    page.insert_text((16, 50), SIDE, fontname="helv", fontsize=12)
    y = 72
    for index in range(lines):
        page.insert_text(
            (16, y),
            "活动安排第%s行请核对名单与座位" % "甲乙丙丁戊己庚辛"[index % 8],
            fontname="china-s",
            fontsize=11,
        )
        y += 16
    rects = _add_digits(page, (16, y + 24), size)
    if mode == "tight":
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union.include_rect(rect)
        union = fitz.Rect(union.x0 - 0.6, union.y0 - 0.6, union.x1 + 0.6, union.y1 + 0.6)
    elif mode == "outside":
        union = fitz.Rect(300, 18, 360, 58)
    else:
        union = fitz.Rect(8, 60, min(width - 8, 400), rects[-1].y1 + 6)
    annot = page.add_rect_annot(union)
    annot.set_border(width=0)
    annot.set_colors(stroke=None, fill=(0.85, 0.85, 0.85) if mode == "outside" else None)
    annot.update()
    parts = []
    if mode == "outside":
        gray = _to_pdf(page, union)
        parts.append("q 0.85 g %.2f %.2f %.2f %.2f re f Q" % (gray.x0, gray.y0, gray.width, gray.height))
    targets = rects if mode != "one" else rects[:1]
    if mode == "split":
        for rect in rects:
            mid = (rect.y0 + rect.y1) / 2
            parts.append(_black_tile(page, fitz.Rect(rect.x0, rect.y0, rect.x1, mid - 0.35), 0.2))
            parts.append(_black_tile(page, fitz.Rect(rect.x0, mid + 0.35, rect.x1, rect.y1), 0.2))
    else:
        for rect in targets:
            parts.append(_black_tile(page, rect))
    _write_square_ap(doc, page, annot, parts, union)
    side = page.search_for(SIDE)[0]
    box = preview_box(page, side)
    raw = doc.tobytes()
    doc.close()
    return raw, box


def plain_phone(userunit=None, cover=False, neighbor=NEIGHBOR):
    doc, page = _fresh(userunit=userunit)
    page.insert_text((24, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((24, 240), neighbor, fontname="helv", fontsize=14)
    page.insert_text((24, 90), SECRET, fontname="helv", fontsize=14)
    phone = page.search_for(SECRET)[0]
    if cover:
        pad = fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2)
        annot = page.add_rect_annot(pad)
        annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        annot.set_border(width=0)
        annot.update()
    box = preview_box(page, phone)
    raw = doc.tobytes()
    doc.close()
    return raw, box


# 复审里会把藏住的号码交付出去的构造。浅色 0.985 不在这里，那是 main 上已有的交付。
DILUTION_SPECS = (
    ("稀释-4pt-六行可读", dict(size=4, lines=6, mode="wide")),
    ("稀释-3pt-六行可读", dict(size=3, lines=6, mode="wide")),
    ("稀释-2pt-六行可读", dict(size=2, lines=6, mode="wide")),
    ("稀释-1.5pt-六行可读", dict(size=1.5, lines=6, mode="wide")),
    ("稀释-4pt-两行可读", dict(size=4, lines=2, mode="wide")),
    ("稀释-4pt-只盖一个数字", dict(size=4, lines=6, mode="one")),
    ("稀释-4pt-每个数字拆两块", dict(size=4, lines=6, mode="split")),
    ("稀释-4pt-紧贴数字应拒绝", dict(size=4, lines=6, mode="tight")),
    ("稀释-2pt-紧贴数字应拒绝", dict(size=2, lines=0, mode="tight")),
    ("稀释-旋转90", dict(size=4, lines=4, mode="wide", rotation=90)),
    ("稀释-UserUnit2", dict(size=4, lines=4, mode="wide", userunit=2)),
    ("稀释-UserUnit2.5", dict(size=4, lines=4, mode="wide", userunit=2.5)),
    ("稀释-页宽1200", dict(size=4, lines=4, mode="wide", width=1200)),
    ("稀释-CropBox", dict(size=4, lines=3, mode="wide", crop=(10, 8, 400, 320))),
)

OUTSIDE_SPECS = (
    ("框外BBox外-4pt", dict(size=4, lines=2, mode="outside")),
    ("框外BBox外-2pt", dict(size=2, lines=2, mode="outside")),
)
