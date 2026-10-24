"""虚构第七轮样例。只在测试里生成，不提交 PDF。"""
"""第七轮独立复审样例。虚构号码，不改仓库。

用法：
  PYTHONPATH=/tmp/redact-py python3 round7_generate.py
产出：
  /opt/cursor/artifacts/round7-generated.jsonl
  /opt/cursor/artifacts/round7-generated.tsv
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
from PIL import Image

KEEP = "整理活动反馈"
SECRET = "13800006661"
SIDE = "DELETEME"
NEW = "/tmp/tree-new/skills/double6-offline-material-redaction/scripts"
MAIN = "/tmp/tree-main/skills/double6-offline-material-redaction/scripts"
OUT_JSONL = Path("/opt/cursor/artifacts/round7-generated.jsonl")
OUT_TSV = Path("/opt/cursor/artifacts/round7-generated.tsv")


def preview_box(page, rect):
    crop = page.cropbox
    cw, ch = abs(crop.x1 - crop.x0), abs(crop.y1 - crop.y0)
    unit = page.rect.width / (ch if page.rotation in (90, 270) else cw)
    unscaled = fitz.Rect(rect.x0 / unit, rect.y0 / unit, rect.x1 / unit, rect.y1 / unit)
    mapped = unscaled * page.rotation_matrix
    box = [mapped.x0 * 2 - 2, mapped.y0 * 2 - 2, mapped.x1 * 2 + 2, mapped.y1 * 2 + 2]
    xs = sorted((box[0], box[2]))
    ys = sorted((box[1], box[3]))
    return [xs[0], ys[0], xs[1], ys[1]]


def side_box(rect):
    return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]


def watch_box(page, rect):
    if rect is None:
        return None
    crop = page.cropbox
    cw, ch = abs(crop.x1 - crop.x0), abs(crop.y1 - crop.y0)
    unit = page.rect.width / (ch if page.rotation in (90, 270) else cw)
    unscaled = fitz.Rect(rect.x0 / unit, rect.y0 / unit, rect.x1 / unit, rect.y1 / unit)
    mapped = unscaled * page.rotation_matrix
    box = [mapped.x0 * 2 + 3, mapped.y0 * 2 + 3, mapped.x1 * 2 - 3, mapped.y1 * 2 - 3]
    xs = sorted((box[0], box[2]))
    ys = sorted((box[1], box[3]))
    if xs[1] - xs[0] < 2 or ys[1] - ys[0] < 2:
        return None
    return [xs[0], ys[0], xs[1], ys[1]]


def luma(image, box):
    if image is None or box is None:
        return None
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, x1 = sorted((max(0, x0), min(image.width, x1)))
    y0, y1 = sorted((max(0, y0), min(image.height, y1)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = image.crop((x0, y0, x1, y1)).convert("L")
    low, high = crop.getextrema()
    raw = crop.tobytes()
    return {"mean": round(sum(raw) / len(raw), 1), "min": low, "max": high, "span": high - low}


def pdfium_image(raw):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(raw) as doc:
        doc.init_forms()
        page = doc[0]
        bitmap = page.render(scale=2, may_draw_forms=True, draw_annots=True)
        image = bitmap.to_pil().convert("RGB")
        bitmap.close()
        page.close()
    return image


def mupdf_image(raw):
    with fitz.open(stream=raw, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), annots=True, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def hidden(stats):
    return bool(stats and stats["span"] < 8 and stats["mean"] < 40)


def visible(stats):
    return bool(stats and stats["span"] >= 8 and stats["mean"] > 60)


def base_page(width=400, height=300):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14)
    phone = page.search_for(SECRET)[0]
    other = page.search_for(SIDE)[0]
    return doc, page, phone, other


def gray_square(page, phone, gray, border, opacity=1, fill=True, pad=8):
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


def forge(raw, subtype):
    doc = fitz.open(stream=raw, filetype="pdf")
    value = doc.xref_get_key(doc[0].xref, "Annots")[1]
    tokens = value.replace("[", " ").replace("]", " ").split()
    refs = [int(tokens[i]) for i in range(0, len(tokens), 3) if i + 2 < len(tokens) and tokens[i + 2] == "R"]
    doc.xref_set_key(refs[0], "Subtype", subtype)
    renamed = doc.tobytes()
    doc.close()
    return renamed


def ap_xref(doc, annot):
    value = doc.xref_get_key(annot.xref, "AP")[1]
    tokens = value.replace("<<", " ").replace(">>", " ").split()
    return int(tokens[tokens.index("/N") + 1])


def cases():
    rows = []

    def add(name, group, params, doc, box, phone, raw=None):
        if raw is None:
            watch = None if phone is None else watch_box(doc[0], phone)
            raw = doc.tobytes()
            doc.close()
        else:
            watch = None
            if phone is not None:
                tmp = fitz.open(stream=raw, filetype="pdf")
                found = tmp[0].search_for(SECRET)
                target = found[0] if found else phone
                watch = watch_box(tmp[0], target)
                tmp.close()
        # 测试只需要 PDF 本身。预览亮度留给证据脚本，避免生成阶段把每份再渲染两遍。
        rows.append({
            "name": name,
            "group": group,
            "params": params,
            "pdf_hex": raw.hex(),
            "box": [float(v) for v in box],
            "keep": params.get("keep", True),
            "kind": "pdf",
            "watch": watch,
            "src_pdfium": None,
            "src_mupdf": None,
        })

    # --- 用户指出的 P1：灰底白边挂到各种类型 ---
    for subtype in ("/Highlight", "/Underline", "/StrikeOut", "/Squiggly", "/Text", "/Link", "/Popup",
                    "/Square", "/Circle", "/FreeText", "/Stamp", "/Ink", "/Caret", "/Line"):
        for gray, border in ((0.45, 6), (0.7, 1), (0.92, 2)):
            doc, page, phone, other = base_page()
            gray_square(page, phone, gray, border)
            raw = forge(doc.tobytes(), subtype)
            doc.close()
            add(f"灰底白边伪造{subtype}", "p1-gray-border",
                {"subtype": subtype, "gray": gray, "border": border, "selection": "旁边文字"},
                None, side_box(other), phone, raw=raw)

    for kind in ("square", "circle", "polygon"):
        for gray, border in ((0.4, 1), (0.4, 6), (0.7, 6)):
            doc, page, phone, other = base_page()
            if kind == "square":
                gray_square(page, phone, gray, border)
            elif kind == "circle":
                cx, cy = (phone.x0 + phone.x1) / 2, (phone.y0 + phone.y1) / 2
                radius = max(phone.width, phone.height) / 2 + 16
                annot = page.add_circle_annot(fitz.Rect(cx - radius, cy - radius, cx + radius, cy + radius))
                annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
                annot.set_border(width=border)
                annot.update()
            else:
                rect = fitz.Rect(phone.x0 - 8, phone.y0 - 8, phone.x1 + 8, phone.y1 + 8)
                annot = page.add_polygon_annot([rect.tl, rect.tr, rect.br, rect.bl])
                annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
                annot.set_border(width=border)
                annot.update()
            add(f"灰底白边-{kind}", "native-cover",
                {"kind": kind, "gray": gray, "border": border, "selection": "旁边文字"},
                doc, side_box(other), phone)

    # 框住号码、整页、只框遮盖
    doc, page, phone, other = base_page()
    annot = gray_square(page, phone, 0.45, 6)
    cover = fitz.Rect(annot.rect)
    raw = forge(doc.tobytes(), "/Highlight")
    doc.close()
    add("灰高亮伪造-框号码", "selection", {"subtype": "/Highlight", "gray": 0.45, "border": 6, "selection": "号码"},
        None, side_box(phone), phone, raw=raw)
    add("灰高亮伪造-整页", "selection", {"subtype": "/Highlight", "gray": 0.45, "border": 6, "selection": "整页", "keep": False},
        None, [0, 0, 800, 600], phone, raw=raw)
    add("灰高亮伪造-框批注", "selection", {"subtype": "/Highlight", "gray": 0.45, "border": 6, "selection": "批注矩形"},
        None, side_box(cover), phone, raw=raw)

    # 外观：渐变、双色、纹理、半透明、只描边
    for kind, stream_kind in (("gradient", "gradient"), ("two-color", "two-color"), ("texture", "texture")):
        doc, page, phone, other = base_page()
        annot = gray_square(page, phone, 0.5, 2)
        xref = ap_xref(doc, annot)
        _k, bbox = doc.xref_get_key(xref, "BBox")
        x0, y0, x1, y1 = (float(t) for t in bbox.replace("[", " ").replace("]", " ").split())
        w, h = x1 - x0, y1 - y0
        if stream_kind == "gradient":
            parts = []
            for i in range(8):
                level = 0.15 + 0.7 * i / 7
                parts.append(f"{level:.3f} {level:.3f} {level:.3f} rg {x0:.2f} {y0 + i * h / 8:.2f} {w:.2f} {h / 8 + 0.4:.2f} re f")
        elif stream_kind == "two-color":
            parts = [
                f"0.25 0.25 0.55 rg {x0:.2f} {y0:.2f} {w:.2f} {h / 2:.2f} re f",
                f"0.85 0.45 0.20 rg {x0:.2f} {y0 + h / 2:.2f} {w:.2f} {h / 2:.2f} re f",
            ]
        else:
            parts = []
            cell = 4
            row = 0
            top = y0
            while top < y1:
                col = 0
                left = x0
                while left < x1:
                    level = 0.2 if (row + col) % 2 == 0 else 0.75
                    parts.append(f"{level:.2f} {level:.2f} {level:.2f} rg {left:.2f} {top:.2f} {min(cell, x1 - left):.2f} {min(cell, y1 - top):.2f} re f")
                    left += cell
                    col += 1
                top += cell
                row += 1
        parts.append(f"1 1 1 RG 2 w {x0:.2f} {y0:.2f} {w:.2f} {h:.2f} re S")
        doc.update_stream(xref, "\n".join(parts).encode())
        add(f"外观-{kind}", "appearance", {"kind": kind, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 0.45, 4, opacity=0.35)
    add("半透明灰底白边", "appearance", {"opacity": 0.35, "gray": 0.45, "border": 4, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 1, 5, fill=False)
    add("只描白边", "appearance", {"fill": False, "stroke": 1, "border": 5, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 0, 0, opacity=0)
    add("完全透明方块压住号码", "appearance", {"opacity": 0, "selection": "旁边文字"}, doc, side_box(other), phone)

    # 旋转、裁剪
    for angle in (90, 180, 270):
        doc, page, phone, other = base_page()
        gray_square(page, phone, 0.45, 5)
        raw = forge(doc.tobytes(), "/Underline")
        doc.close()
        doc = fitz.open(stream=raw, filetype="pdf")
        doc[0].set_rotation(angle)
        page = doc[0]
        phone = page.search_for(SECRET)[0]
        other = page.search_for(SIDE)[0]
        add(f"旋转{angle}-灰下划线伪造", "geometry", {"rotation": angle, "subtype": "/Underline", "selection": "旁边文字"},
            doc, preview_box(page, other), phone)

    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    page.set_cropbox(fitz.Rect(40, 20, 440, 320))
    page.insert_text((80, 70), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((80, 140), SIDE, fontname="helv", fontsize=14)
    page.insert_text((80, 220), SECRET, fontname="helv", fontsize=14)
    phone = page.search_for(SECRET)[0]
    other = page.search_for(SIDE)[0]
    gray_square(page, phone, 0.5, 5)
    raw = forge(doc.tobytes(), "/Text")
    doc.close()
    doc = fitz.open(stream=raw, filetype="pdf")
    page = doc[0]
    phone = page.search_for(SECRET)[0]
    other = page.search_for(SIDE)[0]
    add("裁剪框偏移-灰便签伪造", "geometry", {"crop": [40, 20, 440, 320], "subtype": "/Text", "selection": "旁边文字"},
        doc, preview_box(page, other), phone)

    # --- 绕过严格比较 ---
    doc, page, phone, other = base_page()
    corner = fitz.Rect(250, 30, 330, 70)
    annot = page.add_rect_annot(corner)
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    xref = ap_xref(doc, annot)
    # 在外观流里用负坐标画一块能盖住号码的黑，BBox 仍是小矩形。
    doc.update_stream(xref, b"0 0 0 rg -220 -80 160 40 re f")
    doc.xref_set_key(xref, "BBox", "[0 0 80 40]")
    add("外观流负坐标画出矩形", "bypass", {"ap": "negative", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = gray_square(page, phone, 0.4, 1, pad=6)
    xref = ap_xref(doc, annot)
    doc.xref_set_key(annot.xref, "BS", "<</W 0 /S /S>>")
    doc.xref_set_key(annot.xref, "Border", "[0 0 28]")
    add("BS线宽0但Border为28", "bypass", {"bs": 0, "border": 28, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    above = fitz.Rect(phone.x0, phone.y0 - 18, phone.x1, phone.y0 - 2)
    annot = page.add_rect_annot(above)
    annot.set_colors(stroke=(0.3, 0.3, 0.3))
    annot.set_border(width=1)
    annot.update()
    doc.xref_set_key(annot.xref, "BS", "<</W 0 /S /S>>")
    doc.xref_set_key(annot.xref, "Border", "[0 0 30]")
    add("矩形在号码上方-Border30", "bypass", {"border": 30, "bs": 0, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(250, 40, 340, 90))
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.update()
    xref = ap_xref(doc, annot)
    doc.update_stream(xref, b"q 0 0 20 20 re W n 0 0 0 rg -300 -200 500 400 re f Q")
    doc.xref_set_key(xref, "BBox", "[-400 -400 400 400]")
    add("外观流clip后仍画大黑块", "bypass", {"ap": "clip", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 0.45, 4)
    # 把外观框改到与 Rect 不相交的远处，再把子类型改成高亮。
    raw = doc.tobytes()
    doc.close()
    doc = fitz.open(stream=raw, filetype="pdf")
    annot = doc[0].first_annot
    xref = ap_xref(doc, annot)
    doc.xref_set_key(xref, "BBox", "[400 400 480 460]")
    doc.xref_set_key(annot.xref, "Subtype", "/Highlight")
    raw = doc.tobytes()
    phone = doc[0].search_for(SECRET)[0]
    other = doc[0].search_for(SIDE)[0]
    doc.close()
    add("外观框与Rect不相交", "bypass", {"bbox": "disjoint", "subtype": "/Highlight", "selection": "旁边文字"},
        None, side_box(other), phone, raw=raw)

    for flags, label in (
        (2, "Hidden"),
        (32, "NoView"),
        (4, "Print"),
        (2 | 4, "Hidden+Print"),
        (32 | 4, "NoView+Print"),
        (32 | 256, "NoView+ToggleNoView"),
    ):
        doc, page, phone, other = base_page()
        annot = gray_square(page, phone, 0.45, 4)
        annot.set_flags(flags)
        annot.update()
        add(f"标志{label}-灰底白边", "flags", {"flags": flags, "label": label, "selection": "旁边文字"},
            doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    try:
        oc = doc.add_ocg("FictionalLayer", on=False)
        annot = gray_square(page, phone, 0.45, 4)
        doc.xref_set_key(annot.xref, "OC", f"{oc} 0 R")
        add("可选内容层上的灰方块", "bypass", {"oc": True, "selection": "旁边文字"}, doc, side_box(other), phone)
    except Exception as exc:
        rows.append({"name": "可选内容层上的灰方块", "group": "bypass", "params": {"setup": str(exc)[:120]}, "kind": "setup-failed"})

    doc, page, phone, other = base_page()
    annot = gray_square(page, phone, 0.4, 3)
    xref = ap_xref(doc, annot)
    doc.xref_set_key(xref, "Group", "<</S /Transparency /CS /DeviceRGB /I true>>")
    add("外观透明组", "bypass", {"group": "Transparency", "selection": "旁边文字"}, doc, side_box(other), phone)

    # 与底色同色：先铺一块灰底，再用同样的灰盖住黑字
    doc, page, phone, other = base_page()
    page.draw_rect(fitz.Rect(phone.x0 - 10, phone.y0 - 8, phone.x1 + 10, phone.y1 + 8), color=None, fill=(0.45, 0.45, 0.45))
    gray_square(page, phone, 0.45, 0, pad=4)
    add("与底色同灰的方块", "bypass", {"fill": 0.45, "background": 0.45, "selection": "旁边文字"}, doc, side_box(other), phone)

    # 弹出框矩形在空白角，外观流试图盖住号码
    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 4, phone.y0 - 4, phone.x1 + 4, phone.y1 + 4))
    annot.set_colors(fill=(0.4, 0.4, 0.4), stroke=(1, 1, 1))
    annot.set_border(width=6)
    annot.update()
    doc.xref_set_key(annot.xref, "Subtype", "/Popup")
    doc.xref_set_key(annot.xref, "Open", "true")
    doc.xref_set_key(annot.xref, "Rect", "[250 220 340 280]")
    raw = doc.tobytes()
    doc.close()
    doc = fitz.open(stream=raw, filetype="pdf")
    page = doc[0]
    add("弹出框Rect在角落-原外观盖号码", "bypass", {"subtype": "/Popup", "rect": "corner", "selection": "旁边文字"},
        doc, side_box(page.search_for(SIDE)[0]), page.search_for(SECRET)[0])

    # 多个批注
    doc, page, phone, other = base_page()
    gray_square(page, phone, 0.45, 5)
    page.add_highlight_annot(other).update()
    add("灰方块加高亮-只框旁边", "stack", {"annots": 2, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 0.45, 5)
    stamp = fitz.Rect(250, 40, 350, 100)
    page.add_stamp_annot(stamp).update()
    add("灰方块加图章-只框图章", "stack", {"selection": "图章"}, doc, side_box(stamp), phone)

    doc, page, phone, other = base_page()
    gray_square(page, phone, 0.45, 4)
    black = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
    black.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    black.set_border(width=0)
    black.update()
    add("灰方块上再叠黑方块", "stack", {"selection": "旁边文字"}, doc, side_box(other), phone)

    # 其它类型
    doc, page, phone, other = base_page()
    y = (phone.y0 + phone.y1) / 2
    annot = page.add_line_annot(fitz.Point(phone.x0 - 4, y), fitz.Point(phone.x1 + 8, y))
    annot.set_colors(stroke=(0.35, 0.35, 0.35))
    annot.set_border(width=14)
    annot.update()
    add("灰粗线", "kinds", {"kind": "line", "width": 14, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = page.add_polyline_annot([
        fitz.Point(phone.x0 - 2, phone.y0),
        fitz.Point(phone.x1, (phone.y0 + phone.y1) / 2),
        fitz.Point(phone.x0, phone.y1),
    ])
    annot.set_colors(stroke=(0.3, 0.3, 0.3))
    annot.set_border(width=10)
    annot.update()
    add("灰折线", "kinds", {"kind": "polyline", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    rect = fitz.Rect(phone.x0 - 4, phone.y0 - 4, phone.x1 + 4, phone.y1 + 4)
    strokes = []
    y = rect.y0
    while y <= rect.y1:
        strokes.append([(rect.x0, y), (rect.x1, y)])
        y += 2.4
    annot = page.add_ink_annot(strokes)
    annot.set_colors(stroke=(0.42, 0.42, 0.42))
    annot.set_border(width=2)
    annot.update()
    add("灰墨迹铺满号码", "kinds", {"kind": "ink", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = page.add_freetext_annot(fitz.Rect(phone.x0 - 6, phone.y0 - 6, phone.x1 + 6, phone.y1 + 8), "注", fontsize=10, fill_color=(0.45, 0.45, 0.45), text_color=(1, 1, 1))
    annot.update()
    add("灰底自由文本", "kinds", {"kind": "freetext", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    try:
        page.add_caret_annot(fitz.Point(phone.x0, phone.y1)).update()
        add("插字号压在号码旁", "kinds", {"kind": "caret", "selection": "旁边文字"}, doc, side_box(other), phone)
    except Exception as exc:
        doc.close()
        rows.append({"name": "插字号压在号码旁", "group": "kinds", "params": {"setup": str(exc)[:80]}, "kind": "setup-failed"})

    doc, page, phone, other = base_page()
    try:
        page.add_file_annot(fitz.Point(300, 80), b"FICTIONAL13800009991", filename="a.txt").update()
        add("文件附件批注", "kinds", {"kind": "file", "selection": "旁边文字", "marker": "FICTIONAL13800009991"}, doc, side_box(other), phone)
    except Exception as exc:
        doc.close()
        rows.append({"name": "文件附件批注", "group": "kinds", "params": {"setup": str(exc)[:80]}, "kind": "setup-failed"})

    doc, page, phone, other = base_page()
    page.add_redact_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2), fill=(0, 0, 0))
    add("未应用涂黑标记", "kinds", {"kind": "redact", "selection": "旁边文字"}, doc, side_box(other), phone)

    # --- 修复方声称仍可交付 / 会误拒 ---
    doc, page, phone, other = base_page()
    raw = doc.tobytes()
    doc.close()
    add("没有批注", "expect-deliver", {"kind": "none", "selection": "旁边文字"}, None, side_box(other), phone, raw=raw)

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(0, 0, 400, 32), color=None, fill=(0.08, 0.1, 0.16))
    page.insert_text((12, 22), "活动标题", fontname="china-s", fontsize=12, color=(1, 1, 1))
    page.draw_rect(fitz.Rect(16, 150, 260, 190), color=None, fill=(0.93, 0.94, 0.96))
    page.insert_text((20, 70), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((22, 176), "13800001111", fontname="helv", fontsize=12)
    page.insert_text((20, 120), SIDE, fontname="helv", fontsize=14)
    phone = page.search_for("13800001111")[0]
    other = page.search_for(SIDE)[0]
    add("页眉和表格底色-框号码", "expect-deliver", {"kind": "page-content", "selection": "号码", "secret": "13800001111"},
        doc, side_box(phone), phone)

    for label, draw in (
        ("普通高亮", lambda p: p.add_highlight_annot(p.search_for(KEEP)[0]).update()),
        ("普通下划线", lambda p: p.add_underline_annot(p.search_for(KEEP)[0]).update()),
        ("普通删除线", lambda p: p.add_strikeout_annot(p.search_for(KEEP)[0]).update()),
        ("普通波浪线", lambda p: p.add_squiggly_annot(p.search_for(KEEP)[0]).update()),
        ("可见便签", lambda p: p.add_text_annot(fitz.Point(320, 50), "便签甲乙丙").update()),
    ):
        doc, page, phone, other = base_page()
        draw(page)
        add(label, "expect-reject-visible", {"kind": label, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    page.add_underline_annot(other).update()
    add("下划线只画在被选词上", "expect-reject-visible", {"kind": "underline-on-selection", "selection": "旁边文字"},
        doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(300, 40, 360, 90))
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("空白处线宽0黑方块", "expect-reject-visible", {"place": "blank", "border": 0, "selection": "旁边文字"},
        doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    stamp = fitz.Rect(250, 200, 360, 270)
    page.add_stamp_annot(stamp).update()
    add("图章整块框住", "expect-reject-visible", {"kind": "stamp", "selection": "图章矩形"}, doc, side_box(stamp), phone)

    doc, page, phone, other = base_page()
    rect = fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2)
    annot = page.add_rect_annot(rect)
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("线宽0黑方块整块框住", "expect-reject-visible", {"border": 0, "selection": "批注矩形"}, doc, side_box(rect), phone)

    doc, page, phone, other = base_page()
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(250, 150, 370, 190), "uri": "https://example.invalid/note"})
    annot = page.add_text_annot(fitz.Point(340, 40), "隐藏便签甲乙丙")
    annot.set_flags(fitz.PDF_ANNOT_IS_HIDDEN | fitz.PDF_ANNOT_IS_NO_VIEW)
    annot.update()
    add("隐藏便签和链接不压文字", "expect-deliver", {"covers_text": False, "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(phone.x0, phone.y0, phone.x1, phone.y1), "uri": "https://example.invalid/secret"})
    add("链接矩形压住号码", "expect-reject-visible", {"kind": "link-over-text", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(260, 30, 300, 50))
    annot.set_colors(fill=(1, 1, 1), stroke=(1, 1, 1))
    annot.set_border(width=0)
    annot.set_opacity(0)
    annot.update()
    add("空白处完全透明白方块", "expect-deliver", {"opacity": 0, "place": "blank", "selection": "旁边文字"}, doc, side_box(other), phone)

    # 黑方块、浅字、矢量、贴边：旧反例
    doc, page, phone, other = base_page()
    annot = page.add_rect_annot(fitz.Rect(phone.x0 - 3, phone.y0 - 3, phone.x1 + 3, phone.y1 + 3))
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.update()
    add("黑方块盖号码-框旁边", "prior", {"cover": "black", "selection": "旁边文字"}, doc, side_box(other), phone)

    doc, page, phone, other = base_page()
    page.insert_text((20, 230), "13800007771", fontname="helv", fontsize=12, color=(0.985, 0.985, 0.985))
    pale = page.search_for("13800007771")[0]
    annot = page.add_rect_annot(fitz.Rect(pale.x0 - 2, pale.y0 - 2, pale.x1 + 2, pale.y1 + 2))
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.update()
    add("浅灰字上的黑方块", "prior", {"text": 0.985, "selection": "旁边文字", "secret": "13800007771"}, doc, side_box(other), pale)

    doc = fitz.open()
    page = doc.new_page(width=400, height=280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 230), SIDE, fontname="helv", fontsize=14)
    for dx in range(0, 110, 8):
        page.draw_line(fitz.Point(30 + dx, 100), fitz.Point(32 + dx, 140), color=(0, 0, 0), width=1.4)
    annot = page.add_rect_annot(fitz.Rect(24, 92, 160, 148))
    annot.set_colors(fill=(0, 0, 0), stroke=(0, 0, 0))
    annot.update()
    other = page.search_for(SIDE)[0]
    add("黑方块盖住矢量笔画", "prior", {"under": "vector", "selection": "旁边文字"}, doc, side_box(other), fitz.Rect(30, 100, 140, 140))

    # 文字路线旧反例
    def text_case(name, body, terms, keep):
        rows.append({
            "name": name,
            "group": "text-prior",
            "params": {"terms": terms, "keep": keep},
            "kind": "text",
            "body": body,
            "terms": terms,
            "keep": keep,
        })

    text_case("只选普通号码旁边有空格写法", f"电话{SECRET}\n另一种138 0000 6661\n{KEEP}\n", [SECRET], [KEEP])
    text_case("只选普通号码旁边夹FE0E", f"电话{SECRET}\n另一种138\ufe0e00006661\n{KEEP}\n", [SECRET], [KEEP])
    text_case("短编号隔下划线", f"ID_0000\n{KEEP}\n", ["0000"], [KEEP])
    text_case("伪造标记不能原样交付", f"联系人甲【已隐去1】\n{KEEP}\n", ["联系人甲"], [KEEP])

    # UserUnit：只记录，不纳入误拒结论
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    doc.xref_set_key(page.xref, "UserUnit", "2")
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14)
    phone = page.search_for(SECRET)[0]
    add("UserUnit2框住被盖号码-不计误拒", "userunit-out-of-scope",
        {"userunit": 2, "selection": "号码", "note": "本轮不把误拒算问题"},
        doc, preview_box(page, phone), phone)
    return rows


