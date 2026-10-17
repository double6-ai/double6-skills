# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf drawing：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x03", " ")).strip()

def ai_index_chart_label_repair_skip_reason(source: str, *, hit_count: int | None = None) -> str | None:
    normalized = normalize_text(source)
    if normalized in AI_INDEX_CHART_LABEL_BROAD_SOURCE_BLOCKLIST:
        return "broad_short_label_requires_page_specific_repair"
    if hit_count is not None and hit_count > AI_INDEX_CHART_LABEL_MAX_HITS:
        return "too_many_visible_hits_requires_narrow_repair_profile"
    return None

def page_lines(page: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if not isinstance(block, dict):
            continue
        for line in block.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            spans = [span for span in line.get("spans", []) or [] if isinstance(span, dict)]
            text = "".join(str(span.get("text") or "") for span in spans)
            if not text.strip():
                continue
            sizes = [float(span.get("size") or 0) for span in spans if float(span.get("size") or 0) > 0]
            rows.append(
                {
                    "text": text,
                    "normalized": normalize_text(text),
                    "bbox": line.get("bbox"),
                    "size": max(sizes) if sizes else None,
                    "spans": spans,
                    "origin_y": spans[0].get("origin", [None, None])[1] if spans and isinstance(spans[0].get("origin"), (list, tuple)) else None,
                }
            )
    return rows

def expanded_rect(fitz: Any, bbox: Any, page: Any, *, pad: float = 1.5, min_width: float = 18.0) -> Any | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        rect = fitz.Rect([float(value) for value in bbox[:4]])
    except Exception:
        return None
    if rect.width < min_width:
        rect.x1 = rect.x0 + min_width
    rect.x0 = max(0, rect.x0 - pad)
    rect.y0 = max(0, rect.y0 - pad)
    rect.x1 = min(page.rect.width, rect.x1 + pad)
    rect.y1 = min(page.rect.height, rect.y1 + pad)
    return rect

def sampled_background_color(page: Any, rect: Any) -> tuple[float, float, float]:
    pix = stable_get_pixmap(page, clip=rect, alpha=False, dpi=36)
    if not pix.samples:
        raise ValueError('background_sample_has_no_pixels')
    stride = pix.n
    samples = []
    coords = [(0, 0), (max(0, pix.width - 1), 0), (0, max(0, pix.height - 1)), (max(0, pix.width - 1), max(0, pix.height - 1))]
    for x, y in coords:
        offset = (y * pix.width + x) * stride
        samples.append(tuple((channel / 255 for channel in pix.samples[offset:offset + 3])))
    return tuple((sum((color[i] for color in samples)) / len(samples) for i in range(3)))

def fit_textbox(page: Any, rect: Any, text: str, *, fontsize: float, rotate: int = 0, color: tuple[float, float, float] = (0, 0, 0)) -> float:
    size = max(5.2, fontsize)
    while size >= 5.2:
        result = page.insert_textbox(rect, text, fontname="china-s", fontsize=size, color=color, rotate=rotate, overlay=True)
        if result >= -0.1:
            return round(size, 2)
        size -= 0.4
    page.insert_textbox(rect, text, fontname="china-s", fontsize=5.2, color=color, rotate=rotate, overlay=True)
    return 5.2

def fit_source_han_textbox(
    page: Any,
    rect: Any,
    text: str,
    *,
    fontsize: float,
    rotate: int = 0,
    color: tuple[float, float, float] = (0, 0, 0),
) -> float:
    size = max(4.8, fontsize)
    fontname = source_han_sans_fontname(page)
    while size >= 4.8:
        kwargs = {
            "fontname": fontname,
            "fontsize": size,
            "color": color,
            "rotate": rotate,
            "overlay": True,
        }
        if fontname == "source-han-sans-cn" and SOURCE_HAN_SANS_CN_REGULAR.exists():
            kwargs["fontfile"] = str(SOURCE_HAN_SANS_CN_REGULAR)
        result = page.insert_textbox(rect, text, **kwargs)
        if result >= -0.1:
            return round(size, 2)
        size -= 0.3
    kwargs = {
        "fontname": fontname,
        "fontsize": 4.8,
        "color": color,
        "rotate": rotate,
        "overlay": True,
    }
    if fontname == "source-han-sans-cn" and SOURCE_HAN_SANS_CN_REGULAR.exists():
        kwargs["fontfile"] = str(SOURCE_HAN_SANS_CN_REGULAR)
    page.insert_textbox(rect, text, **kwargs)
    return 4.8

def replace_rect(page: Any, rect: Any, text: str, *, fontsize: float, rotate: int = 0) -> dict[str, Any]:
    fill = sampled_background_color(page, rect)
    try:
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions()
    except Exception:
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
    used = fit_textbox(page, rect, text, fontsize=fontsize, rotate=rotate)
    return {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": used, "fill_strategy": "sampled_region_background"}

def replace_rect_source_han(
    page: Any,
    rect: Any,
    text: str,
    *,
    fontsize: float,
    rotate: int = 0,
    fill: tuple[float, float, float] | None = None,
    color: tuple[float, float, float] = (0, 0, 0),
) -> dict[str, Any]:
    fill = fill or sampled_background_color(page, rect)
    try:
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions()
    except Exception:
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
    used = fit_source_han_textbox(page, rect, text, fontsize=fontsize, rotate=rotate, color=color)
    return {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": used, "fill_strategy": "sampled_region_background"}

def overlay_rect_source_han(
    page: Any,
    rect: Any,
    text: str,
    *,
    fontsize: float,
    rotate: int = 0,
    fill: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    fill = fill or sampled_background_color(page, rect)
    page.draw_rect(rect, color=fill, fill=fill, overlay=True)
    used = fit_source_han_textbox(page, rect, text, fontsize=fontsize, rotate=rotate)
    return {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": used, "fill_strategy": "sampled_background_overlay_no_redaction"}

def replace_highlight_label(page: Any, rect: Any, text: str, *, fontsize: float = 6.8) -> dict[str, Any]:
    fill = (0.82, 0.9, 0.38)
    try:
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions()
    except Exception:
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
    insert_source_han_sans_fake_bold(page, (rect.x0 + 4.0, rect.y1 - 3.0), text, fontsize=fontsize, color=(0, 0, 0))
    return {
        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
        "fontsize": fontsize,
        "fill_strategy": "sampled_highlight_label_background_redraw",
    }

def pdf_color_to_rgb(value: Any, fallback: tuple[float, float, float] = (0.95, 0.97, 1.0)) -> tuple[float, float, float]:
    if not isinstance(value, int):
        return fallback
    rgb = value & 0xFFFFFF
    return (((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255)

def first_line_color(page: Any, *, y_max: float = 45.0, fallback: tuple[float, float, float] = (0, 0, 0)) -> tuple[float, float, float]:
    for block in page.get_text("dict").get("blocks", []):
        if not isinstance(block, dict):
            continue
        for line in block.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            bbox = line.get("bbox")
            if not bbox or float(bbox[1]) > y_max:
                continue
            spans = [span for span in line.get("spans", []) or [] if isinstance(span, dict) and str(span.get("text") or "").strip()]
            if not spans:
                continue
            return pdf_color_to_rgb(spans[0].get("color"), fallback=fallback)
    return fallback

def adjacent_background_color(page: Any, rect: Any, *, dx: float = 8.0) -> tuple[float, float, float]:
    sample = rect + (dx, 0, dx, 0)
    if sample.x1 <= page.rect.width:
        return sampled_background_color(page, sample)
    sample = rect + (-dx, 0, -dx, 0)
    if sample.x0 >= 0:
        return sampled_background_color(page, sample)
    return sampled_background_color(page, rect)

def copy_adjacent_background_region(page: Any, rect: Any, *, dx: float = 10.0) -> bool:
    doc = getattr(page, "parent", None)
    page_number = getattr(page, "number", 0)
    if doc is None:
        return False
    clip = rect + (dx, 0, dx, 0)
    if clip.x1 > page.rect.width:
        clip = rect + (-dx, 0, -dx, 0)
    if clip.x0 < 0 or clip.x1 > page.rect.width:
        return False
    try:
        page.show_pdf_page(rect, doc, page_number, clip=clip, overlay=True, keep_proportion=False)
    except Exception:
        return False
    return True

def cover_text_rect(page: Any, rect: Any) -> None:
    if copy_adjacent_background_region(page, rect):
        return
    fill = adjacent_background_color(page, rect)
    page.draw_rect(rect, color=fill, fill=fill, overlay=True)

def draw_solid_cover(page: Any, rect: Any, *, fill: tuple[float, float, float] = AI_INDEX_FOOTER_BG) -> None:
    page.draw_rect(rect, color=fill, fill=fill, overlay=True)

def source_han_serif_fontname(page: Any) -> str:
    if SOURCE_HAN_SERIF_CN_REGULAR.exists():
        fontname = "source-han-serif-cn"
        try:
            page.insert_font(fontname=fontname, fontfile=str(SOURCE_HAN_SERIF_CN_REGULAR))
            return fontname
        except Exception:
            return "china-s"
    return "china-s"

def source_han_sans_fontname(page: Any) -> str:
    if SOURCE_HAN_SANS_CN_REGULAR.exists():
        fontname = "source-han-sans-cn"
        try:
            page.insert_font(fontname=fontname, fontfile=str(SOURCE_HAN_SANS_CN_REGULAR))
            return fontname
        except Exception:
            return "china-s"
    return "china-s"

def cjk_text_width(fitz: Any, text: str, *, fontsize: float) -> float:
    # PyMuPDF's built-in ``china-s`` width treats ASCII in mixed CJK strings as
    # fullwidth. That creates large false gaps after blue link text on AI Index
    # footer lines, so use a small mixed-script estimate for manual redraws.
    width = 0.0
    for char in text:
        codepoint = ord(char)
        if "\u4e00" <= char <= "\u9fff" or 0x3000 <= codepoint <= 0x303F or 0xFF00 <= codepoint <= 0xFFEF:
            width += fontsize
        elif char.isspace():
            width += fontsize * 0.32
        elif char in "ilI.,:;!|":
            width += fontsize * 0.28
        elif char in "()[]{}'\"`":
            width += fontsize * 0.34
        elif char in "-–—/":
            width += fontsize * 0.38
        else:
            width += fontsize * 0.56
    return width

def draw_cjk_text(fitz: Any, page: Any, x: float, baseline: float, text: str, *, fontsize: float, color: tuple[float, float, float]) -> float:
    fontname = source_han_sans_fontname(page)
    if fontname == "source-han-sans-cn" and SOURCE_HAN_SANS_CN_REGULAR.exists():
        page.insert_text((x, baseline), text, fontname=fontname, fontfile=str(SOURCE_HAN_SANS_CN_REGULAR), fontsize=fontsize, color=color, overlay=True)
    else:
        page.insert_text((x, baseline), text, fontname=fontname, fontsize=fontsize, color=color, overlay=True)
    return x + cjk_text_width(fitz, text, fontsize=fontsize)

def insert_source_han_sans(page: Any, point: tuple[float, float], text: str, *, fontsize: float, color: tuple[float, float, float]) -> None:
    fontname = source_han_sans_fontname(page)
    if fontname == "source-han-sans-cn" and SOURCE_HAN_SANS_CN_REGULAR.exists():
        page.insert_text(point, text, fontname=fontname, fontfile=str(SOURCE_HAN_SANS_CN_REGULAR), fontsize=fontsize, color=color, overlay=True)
    else:
        page.insert_text(point, text, fontname=fontname, fontsize=fontsize, color=color, overlay=True)

def insert_source_han_sans_fake_bold(page: Any, point: tuple[float, float], text: str, *, fontsize: float, color: tuple[float, float, float]) -> None:
    insert_source_han_sans(page, point, text, fontsize=fontsize, color=color)
    insert_source_han_sans(page, (point[0] + 0.16, point[1]), text, fontsize=fontsize, color=color)

def insert_mixed_source_han_sans(
    fitz: Any,
    page: Any,
    point: tuple[float, float],
    segments: list[tuple[str, str]],
    *,
    fontsize: float,
    color: tuple[float, float, float],
) -> None:
    x, baseline = point
    for text, font_kind in segments:
        if not text:
            continue
        if font_kind == "latin":
            page.insert_text((x, baseline), text, fontname="helv", fontsize=fontsize, color=color, overlay=True)
            try:
                x += fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
            except Exception:
                x += len(text) * fontsize * 0.48
        else:
            insert_source_han_sans(page, (x, baseline), text, fontsize=fontsize, color=color)
            x += cjk_text_width(fitz, text, fontsize=fontsize)

def insert_mixed_source_han_sans_fake_bold(
    fitz: Any,
    page: Any,
    point: tuple[float, float],
    segments: list[tuple[str, str]],
    *,
    fontsize: float,
    color: tuple[float, float, float],
) -> None:
    insert_mixed_source_han_sans(fitz, page, point, segments, fontsize=fontsize, color=color)
    insert_mixed_source_han_sans(fitz, page, (point[0] + 0.16, point[1]), segments, fontsize=fontsize, color=color)

def insert_ai_figure_label_fake_bold(
    fitz: Any,
    page: Any,
    point: tuple[float, float],
    label: str,
    *,
    fontsize: float,
    color: tuple[float, float, float],
) -> float:
    """Draw AI Index figure labels with Latin digits so decimals do not spread out."""

    x, baseline = point
    if label.startswith("图 "):
        cjk_part = "图 "
        latin_part = label[2:]
    else:
        cjk_part = label
        latin_part = ""

    def draw_once(dx: float = 0.0) -> float:
        cursor = x + dx
        insert_source_han_sans(page, (cursor, baseline), cjk_part, fontsize=fontsize, color=color)
        cursor += cjk_text_width(fitz, cjk_part, fontsize=fontsize) + 0.6
        if latin_part:
            page.insert_text((cursor, baseline), latin_part, fontname="helv", fontsize=fontsize, color=color, overlay=True)
            try:
                cursor += fitz.get_text_length(latin_part, fontname="helv", fontsize=fontsize)
            except Exception:
                cursor += len(latin_part) * fontsize * 0.48
        return cursor

    end_x = draw_once()
    draw_once(0.16)
    return end_x

def insert_ai_figure_label(
    fitz: Any,
    page: Any,
    point: tuple[float, float],
    label: str,
    *,
    fontsize: float,
    color: tuple[float, float, float],
) -> float:
    """Draw AI Index figure labels once, keeping numeric decimals compact."""

    x, baseline = point
    if label.startswith("图 "):
        cjk_part = "图 "
        latin_part = label[2:]
    else:
        cjk_part = label
        latin_part = ""

    cursor = x
    insert_source_han_sans(page, (cursor, baseline), cjk_part, fontsize=fontsize, color=color)
    cursor += cjk_text_width(fitz, cjk_part, fontsize=fontsize) + 0.6
    if latin_part:
        page.insert_text((cursor, baseline), latin_part, fontname="helv", fontsize=fontsize, color=color, overlay=True)
        try:
            cursor += fitz.get_text_length(latin_part, fontname="helv", fontsize=fontsize)
        except Exception:
            cursor += len(latin_part) * fontsize * 0.48
    return cursor

def split_numeric_prefix_label(text: str) -> list[tuple[str, str]] | None:
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?%?)([，,].+)$", text)
    if not match:
        return None
    return [(match.group(1), "latin"), (match.group(2), "cjk")]

def mixed_source_han_sans_width(fitz: Any, segments: list[tuple[str, str]], *, fontsize: float) -> float:
    width = 0.0
    for text, kind in segments:
        if kind == "latin":
            try:
                width += fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
            except Exception:
                width += len(text) * fontsize * 0.48
        else:
            width += cjk_text_width(fitz, text, fontsize=fontsize)
    return width

def insert_source_han_serif(page: Any, point: tuple[float, float], text: str, *, fontsize: float, color: tuple[float, float, float]) -> None:
    fontname = source_han_serif_fontname(page)
    if fontname == "source-han-serif-cn" and SOURCE_HAN_SERIF_CN_REGULAR.exists():
        page.insert_text(point, text, fontname=fontname, fontfile=str(SOURCE_HAN_SERIF_CN_REGULAR), fontsize=fontsize, color=color, overlay=True)
    else:
        page.insert_text(point, text, fontname=fontname, fontsize=fontsize, color=color, overlay=True)

def insert_source_han_serif_fake_bold(page: Any, point: tuple[float, float], text: str, *, fontsize: float, color: tuple[float, float, float]) -> None:
    insert_source_han_serif(page, point, text, fontsize=fontsize, color=color)
    insert_source_han_serif(page, (point[0] + 0.18, point[1]), text, fontsize=fontsize, color=color)

def draw_cjk_linked_line(
    fitz: Any,
    page: Any,
    *,
    x: float,
    baseline: float,
    prefix: str,
    link_text: str,
    suffix: str = "",
    uri: str,
    fontsize: float,
    text_color: tuple[float, float, float] = (1, 1, 1),
) -> dict[str, Any]:
    link_start = draw_cjk_text(fitz, page, x, baseline, prefix, fontsize=fontsize, color=text_color)
    link_end = draw_cjk_text(fitz, page, link_start, baseline, link_text, fontsize=fontsize, color=LINK_BLUE)
    if suffix:
        draw_cjk_text(fitz, page, link_end, baseline, suffix, fontsize=fontsize, color=text_color)
    link_rect = fitz.Rect(link_start, baseline - fontsize * 1.28, link_end, baseline + fontsize * 0.4)
    page.insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": uri})
    return {
        "uri": uri,
        "link_text": link_text,
        "link_bbox": [round(v, 2) for v in [link_rect.x0, link_rect.y0, link_rect.x1, link_rect.y1]],
    }

def replace_cover_year_rect(page: Any, rect: Any, text: str, *, fontsize: float) -> dict[str, Any]:
    fill = sampled_background_color(page, rect)
    try:
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions()
    except Exception:
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
    size = min(max(18.0, fontsize), max(18.0, rect.width / 2.25))
    baseline = min(page.rect.height - 4, rect.y0 + size * 1.08)
    page.insert_text((rect.x0, baseline), text, fontname="helv", fontsize=size, color=(0, 0, 0), overlay=True)
    return {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": round(size, 2), "fill_strategy": "sampled_region_background"}

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
