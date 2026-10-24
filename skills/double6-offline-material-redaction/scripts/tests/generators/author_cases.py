"""虚构作者复测样例。只在测试里生成，不提交 PDF。"""
"""比较 f99a84b、当前严格规则、main（v0.7.0）对同一批虚构 PDF 的交付结果。

号码是虚构的 13800006661。只框旁边的 DELETEME，除非参数写明框住号码、批注或整页。
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
import pypdfium2 as pdfium
KEEP = "整理120条活动反馈"
COVERED = "13800006661"
SIDE = "DELETEME"
HERE = Path(__file__).resolve()
OUT_DIR = Path("/tmp/author-out")
TREES = {
    "f99a84b": "/workspace/skills/double6-offline-material-redaction/scripts",
    "new": "/tmp/tree-new/skills/double6-offline-material-redaction/scripts",
    "main": "/tmp/tree-main/skills/double6-offline-material-redaction/scripts",
}


def plan_for(box, keep=True):
    return {
        "version": 1,
        "kind": "pdf",
        "reviewed": True,
        "reviewed_pages": [1],
        "keep": [KEEP] if keep else [],
        "pages": [{"page": 1, "rectangles": [[float(v) for v in box]]}],
    }


def side_box(rect):
    return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]


def preview_box(page, text_rect):
    crop = page.cropbox
    cw = abs(crop.x1 - crop.x0)
    ch = abs(crop.y1 - crop.y0)
    if page.rotation in (90, 270):
        unit = page.rect.width / ch
    else:
        unit = page.rect.width / cw
    unscaled = fitz.Rect(text_rect.x0 / unit, text_rect.y0 / unit, text_rect.x1 / unit, text_rect.y1 / unit)
    mapped = unscaled * page.rotation_matrix
    return [mapped.x0 * 2 - 2, mapped.y0 * 2 - 2, mapped.x1 * 2 + 2, mapped.y1 * 2 + 2]


def interior_luma(raw, phone):
    box = (int(phone.x0 * 2 + 4), int(phone.y0 * 2 + 4), int(phone.x1 * 2 - 4), int(phone.y1 * 2 - 4))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    with pdfium.PdfDocument(raw) as doc:
        doc.init_forms()
        page = doc[0]
        bitmap = page.render(scale=2, may_draw_forms=True, draw_annots=True)
        image = bitmap.to_pil().convert("L")
        bitmap.close()
        page.close()
    if box[2] > image.width or box[3] > image.height:
        return None
    crop = image.crop(box)
    low, high = crop.getextrema()
    raw_bytes = crop.tobytes()
    return {"span": high - low, "mean": round(sum(raw_bytes) / len(raw_bytes), 1)}


def forge(raw, subtype):
    doc = fitz.open(stream=raw, filetype="pdf")
    value = doc.xref_get_key(doc[0].xref, "Annots")[1]
    tokens = value.replace("[", " ").replace("]", " ").split()
    refs = [int(tokens[i]) for i in range(0, len(tokens), 3) if i + 2 < len(tokens) and tokens[i + 2] == "R"]
    if len(refs) != 1:
        doc.close()
        raise RuntimeError("expected one annot, got " + value)
    doc.xref_set_key(refs[0], "Subtype", subtype)
    renamed = doc.tobytes()
    doc.close()
    return renamed


def base_page():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), COVERED, fontname="helv", fontsize=14)
    phone = page.search_for(COVERED)[0]
    other = page.search_for(SIDE)[0]
    return doc, page, phone, other


def add_square(page, phone, gray, border, opacity=1, fill=True, pad=8):
    rect = fitz.Rect(phone.x0 - pad, phone.y0 - pad, phone.x1 + pad, phone.y1 + pad)
    annot = page.add_rect_annot(rect)
    if fill:
        annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
    else:
        annot.set_colors(stroke=(gray, gray, gray))
    annot.set_border(width=border)
    annot.set_opacity(opacity)
    annot.update()
    return annot


def paint(doc, annot, kind):
    value = doc.xref_get_key(annot.xref, "AP")[1]
    tokens = value.replace("<<", " ").replace(">>", " ").split()
    xref = int(tokens[tokens.index("/N") + 1])
    _kind, bbox = doc.xref_get_key(xref, "BBox")
    x0, y0, x1, y1 = (float(token) for token in bbox.replace("[", " ").replace("]", " ").split())
    width = x1 - x0
    height = y1 - y0
    parts = []
    if kind == "gradient":
        steps = 8
        band = height / steps
        for index in range(steps):
            level = 0.2 + 0.65 * index / (steps - 1)
            parts.append(f"{level:.3f} {level:.3f} {level:.3f} rg")
            parts.append(f"{x0:.3f} {y0 + index * band:.3f} {width:.3f} {band + 0.4:.3f} re f")
    elif kind == "two-color":
        mid = y0 + height / 2
        parts.append(f"0.280 0.280 0.280 rg {x0:.3f} {y0:.3f} {width:.3f} {height / 2 + 0.3:.3f} re f")
        parts.append(f"0.720 0.450 0.300 rg {x0:.3f} {mid:.3f} {width:.3f} {height / 2 + 0.3:.3f} re f")
    elif kind == "texture":
        cell = 3.5
        row = 0
        top = y0
        while top < y1 - 0.05:
            col = 0
            left = x0
            while left < x1 - 0.05:
                level = 0.22 if (row + col) % 2 == 0 else 0.78
                parts.append(
                    f"{level:.2f} {level:.2f} {level:.2f} rg {left:.2f} {top:.2f} {min(cell, x1 - left):.2f} {min(cell, y1 - top):.2f} re f"
                )
                left += cell
                col += 1
            top += cell
            row += 1
    else:
        raise AssertionError(kind)
    parts.append(f"1 1 1 RG\n2 w\n{x0:.3f} {y0:.3f} {width:.3f} {height:.3f} re S")
    doc.update_stream(xref, "\n".join(parts).encode("ascii"))


def finish(doc, other, raw_override=None):
    raw = raw_override if raw_override is not None else doc.tobytes()
    if raw_override is None:
        doc.close()
    return raw, side_box(other)


def record(samples, name, params, raw, box, keep=True, phone=None):
    # phone 只留给调用方标明覆盖对象。测试生成不再为每份做预览亮度，PDF 字节不变。
    del phone
    samples.append({"name": name, "params": params, "pdf": base64.b64encode(raw).decode("ascii"), "plan": plan_for(box, keep)})


def build_samples():
    samples = []
    native = []
    for kind in ("square", "circle", "polygon"):
        for gray, border in ((0.4, 1), (0.4, 6), (0.7, 1), (0.7, 6), (0.92, 2)):
            native.append((kind, gray, border))
    for kind, gray, border in native:
        doc, page, phone, other = base_page()
        if kind == "square":
            add_square(page, phone, gray, border)
        elif kind == "circle":
            cx = (phone.x0 + phone.x1) / 2
            cy = (phone.y0 + phone.y1) / 2
            radius = max(phone.width, phone.height) / 2 + 18
            annot = page.add_circle_annot(fitz.Rect(cx - radius, cy - radius, cx + radius, cy + radius))
            annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
            annot.set_border(width=border)
            annot.set_opacity(1)
            annot.update()
        else:
            rect = fitz.Rect(phone.x0 - 8, phone.y0 - 8, phone.x1 + 8, phone.y1 + 8)
            annot = page.add_polygon_annot([rect.tl, rect.tr, rect.br, rect.bl])
            annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
            annot.set_border(width=border)
            annot.set_opacity(1)
            annot.update()
        raw = doc.tobytes()
        doc.close()
        record(samples, f"灰底白边-{kind}", {"kind": kind, "gray": gray, "border": border, "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    for subtype in ("/FreeText", "/Stamp", "/Highlight", "/Ink", "/Underline", "/Squiggly", "/StrikeOut", "/Text", "/Link", "/Popup", "/Circle"):
        for gray, border in ((0.45, 6), (0.7, 1), (0.85, 8)):
            doc, page, phone, other = base_page()
            add_square(page, phone, gray, border)
            raw = forge(doc.tobytes(), subtype)
            doc.close()
            record(
                samples,
                f"灰底白边-伪造{subtype}",
                {"kind": "square-ap", "subtype": subtype, "gray": gray, "border": border, "selection": "旁边文字"},
                raw,
                side_box(other),
                phone=phone,
            )

    doc, page, phone, other = base_page()
    rect = fitz.Rect(phone.x0 - 6, phone.y0 - 6, phone.x1 + 6, phone.y1 + 6)
    lines = []
    y = rect.y0
    while y <= rect.y1:
        lines.append([(rect.x0, y), (rect.x1, y)])
        y += 2.2
    annot = page.add_ink_annot(lines)
    annot.set_colors(stroke=(0.45, 0.45, 0.45))
    annot.set_border(width=3)
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "灰笔画-墨迹", {"kind": "ink", "gray": 0.45, "border": 3, "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    for kind in ("gradient", "two-color", "texture"):
        doc, page, phone, other = base_page()
        annot = add_square(page, phone, 0.5, 2)
        paint(doc, annot, kind)
        raw = doc.tobytes()
        doc.close()
        record(samples, f"外观-{kind}", {"kind": kind, "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    doc, page, phone, other = base_page()
    add_square(page, phone, 0.45, 3, opacity=0.45)
    raw = doc.tobytes()
    doc.close()
    record(samples, "半透明灰底白边", {"kind": "square", "gray": 0.45, "border": 3, "opacity": 0.45, "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    for label, gray, fill in (("描边-灰", 0.25, False), ("描边-白", 1, False)):
        doc, page, phone, other = base_page()
        add_square(page, phone, gray, 4, fill=fill)
        raw = doc.tobytes()
        doc.close()
        record(samples, label, {"kind": "square", "stroke": gray, "border": 4, "fill": False, "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    for angle in (90, 180, 270):
        doc, page, phone, other = base_page()
        add_square(page, phone, 0.45, 4)
        page.set_rotation(angle)
        box = preview_box(page, other)
        raw = doc.tobytes()
        doc.close()
        record(samples, f"旋转{angle}-灰底白边", {"kind": "square", "gray": 0.45, "border": 4, "rotation": angle, "selection": "旁边文字"}, raw, box)

    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    page.set_cropbox(fitz.Rect(40, 20, 440, 320))
    page.insert_text((80, 80), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((80, 150), SIDE, fontname="helv", fontsize=14)
    page.insert_text((80, 230), COVERED, fontname="helv", fontsize=14)
    phone = page.search_for(COVERED)[0]
    other = page.search_for(SIDE)[0]
    add_square(page, phone, 0.5, 5)
    box = preview_box(page, other)
    raw = doc.tobytes()
    doc.close()
    record(samples, "CropBox偏移-灰底白边", {"kind": "square", "gray": 0.5, "border": 5, "crop": [40, 20, 440, 320], "selection": "旁边文字"}, raw, box)

    doc, page, phone, other = base_page()
    page.add_highlight_annot(phone).update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "原生高亮盖在号码上", {"kind": "highlight", "selection": "旁边文字"}, raw, side_box(other), phone=phone)

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), COVERED, fontname="helv", fontsize=16, color=(0.985, 0.985, 0.985))
    phone = page.search_for(COVERED)[0]
    other = page.search_for(SIDE)[0]
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "浅灰字上的黑方块", {"text": [0.985, 0.985, 0.985], "cover": "black", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "深色黑方块", {"cover": "black", "opacity": 1, "selection": "旁边文字"}, raw, side_box(other))
    record(samples, "框住被盖号码", {"cover": "black", "opacity": 1, "selection": "号码"}, raw, side_box(phone))
    width, height = 800, 600
    record(samples, "整页框选仍留黑方块", {"cover": "black", "selection": "整页"}, raw, [0, 0, width, height], keep=False)

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(0.08)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "低透明度黑方块", {"cover": "black", "opacity": 0.08, "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "白方块", {"cover": "white", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    y = (phone.y0 + phone.y1) / 2
    annot = page.add_line_annot(fitz.Point(phone.x0 - 6, y), fitz.Point(phone.x1 + 18, y))
    annot.set_border(width=12)
    annot.set_colors(stroke=(0, 0, 0))
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "直线盖住号码", {"kind": "line", "width": 12, "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    y = (phone.y0 + phone.y1) / 2
    annot = page.add_polyline_annot([
        fitz.Point(phone.x0 - 4, y - 3),
        fitz.Point((phone.x0 + phone.x1) / 2, y + 4),
        fitz.Point(phone.x1 + 14, y - 2),
    ])
    annot.set_border(width=10)
    annot.set_colors(stroke=(0, 0, 0))
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "折线盖住号码", {"kind": "polyline", "width": 10, "selection": "旁边文字"}, raw, side_box(other))

    doc = fitz.open()
    page = doc.new_page(width=400, height=280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 230), SIDE, fontname="helv", fontsize=14)
    shape = page.new_shape()
    for dx in range(0, 120, 8):
        shape.draw_line(fitz.Point(30 + dx, 100), fitz.Point(32 + dx, 140))
    shape.finish(color=(0, 0, 0), width=1.5)
    shape.commit()
    annot = page.add_rect_annot(fitz.Rect(24, 92, 160, 148))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    other = page.search_for(SIDE)[0]
    raw = doc.tobytes()
    doc.close()
    record(samples, "黑方块盖住矢量笔画", {"kind": "square", "under": "vector-strokes", "selection": "旁边文字"}, raw, side_box(other))

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    square = fitz.Rect(30, 140, 340, 270)
    page.insert_text((48, 141.2), "9", fontname="helv", fontsize=1)
    other = page.search_for(SIDE)[0]
    annot = page.add_rect_annot(square)
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "贴边1pt字", {"kind": "square", "glyph": "1pt-top-edge", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    add_square(page, phone, 0, 1)
    page.set_rotation(90)
    box = preview_box(page, other)
    raw = doc.tobytes()
    doc.close()
    record(samples, "旋转90-黑方块", {"kind": "square", "cover": "black", "rotation": 90, "selection": "旁边文字"}, raw, box)

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = forge(doc.tobytes(), "/Highlight")
    doc.close()
    record(samples, "黑外观伪造高亮", {"subtype": "/Highlight", "cover": "black", "selection": "旁边文字"}, raw, side_box(other))

    for kind, draw in (
        ("高亮", lambda page: page.add_highlight_annot(page.search_for(KEEP)[0]).update()),
        ("下划线", lambda page: page.add_underline_annot(page.search_for(KEEP)[0]).update()),
        ("删除线", lambda page: page.add_strikeout_annot(page.search_for(KEEP)[0]).update()),
        ("波浪线", lambda page: page.add_squiggly_annot(page.search_for(KEEP)[0]).update()),
        ("可见便签", lambda page: page.add_text_annot(fitz.Point(320, 50), "便签甲乙丙").update()),
    ):
        doc, page, phone, other = base_page()
        draw(page)
        raw = doc.tobytes()
        doc.close()
        record(samples, f"普通{kind}", {"kind": kind, "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(300, 30, 360, 80))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "空白处黑方块", {"kind": "square", "place": "blank", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    stamp = fitz.Rect(250, 200, 360, 270)
    page.add_stamp_annot(stamp).update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "图章整块框住", {"kind": "stamp", "selection": "图章矩形"}, raw, side_box(stamp))

    doc, page, phone, other = base_page()
    rect = fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2)
    annot = page.add_rect_annot(rect)
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "线宽0黑方块整块框住", {"kind": "square", "border": 0, "selection": "批注矩形"}, raw, side_box(rect))

    doc, page, phone, other = base_page()
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(20, 28, 160, 44), "uri": "https://example.com/note"})
    annot = page.add_text_annot(fitz.Point(300, 230), "隐藏便签甲乙丙")
    annot.set_flags(fitz.PDF_ANNOT_IS_HIDDEN | fitz.PDF_ANNOT_IS_NO_VIEW)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "链接和弹出框压住未选文字", {"kind": "link+hidden-note", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(250, 150, 370, 190), "uri": "https://example.com/note"})
    annot = page.add_text_annot(fitz.Point(340, 40), "隐藏便签甲乙丙")
    annot.set_flags(fitz.PDF_ANNOT_IS_HIDDEN | fitz.PDF_ANNOT_IS_NO_VIEW)
    annot.update()
    value = doc.xref_get_key(page.xref, "Annots")[1]
    tokens = value.replace("[", " ").replace("]", " ").split()
    for index in range(0, len(tokens), 3):
        if index + 2 < len(tokens) and tokens[index + 2] == "R" and doc.xref_get_key(int(tokens[index]), "Subtype")[1] == "/Popup":
            doc.xref_set_key(int(tokens[index]), "Rect", "[220 140 390 220]")
    raw = doc.tobytes()
    doc.close()
    record(samples, "隐藏便签和链接不压文字", {"kind": "link+hidden-note", "selection": "旁边文字", "covers_text": False}, raw, side_box(other))

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(0, 0, 400, 36))
    shape.finish(fill=(0.12, 0.14, 0.2), color=None, width=0)
    shape.commit()
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(30, 70, 200, 110))
    shape.finish(fill=(0.93, 0.93, 0.86), color=(0.7, 0.7, 0.7), width=0.6)
    shape.commit()
    page.insert_text((36, 96), "CELL", fontname="helv", fontsize=12)
    page.insert_text((20, 170), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 230), KEEP, fontname="china-s", fontsize=14)
    other = page.search_for(SIDE)[0]
    raw = doc.tobytes()
    doc.close()
    record(samples, "页眉和表格底色", {"kind": "page-content", "selection": "旁边文字"}, raw, side_box(other))

    doc, page, phone, other = base_page()
    raw = doc.tobytes()
    doc.close()
    record(samples, "没有批注", {"kind": "none", "selection": "旁边文字"}, raw, side_box(other))

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    doc.xref_set_key(page.xref, "UserUnit", "2")
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), COVERED, fontname="helv", fontsize=14)
    phone = page.search_for(COVERED)[0]
    box = preview_box(page, phone)
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_opacity(1)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    record(samples, "UserUnit框住被盖号码", {"userunit": 2, "cover": "black", "selection": "号码", "note": "已知误拒，本轮不修"}, raw, box)
    return samples


