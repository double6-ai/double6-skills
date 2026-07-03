#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import policy_utils
import toc_repair_runtime

SCRIPT_INTERFACE = "internal-module"


def _load_fitz():
    return toc_repair_runtime._load_fitz()


def _rect_to_list(rect: Any) -> list[float]:
    return toc_repair_runtime._rect_to_list(rect)


def _union_rect(fitz: Any, rects: list[Any]) -> Any | None:
    return toc_repair_runtime._union_rect(fitz, rects)


def _background_evidence(fitz: Any, page: Any, region: Any) -> dict[str, Any]:
    return toc_repair_runtime._background_evidence(fitz, page, region)


def _pdf_color_from_rgb(rgb: list[int] | None) -> tuple[float, float, float]:
    return toc_repair_runtime._pdf_color_from_rgb(rgb)


def _text_color_for_background(fill_color: tuple[float, float, float]) -> tuple[float, float, float]:
    return toc_repair_runtime._text_color_for_background(fill_color)


def _font(fallback: str, engine_home: Path | None = None) -> tuple[str, str | None, str]:
    paths = toc_repair_runtime._font_candidates(engine_home)
    if paths:
        return "metadata-cjk", str(paths[0]), "ok"
    return fallback, None, "builtin_fallback"


def _words(page: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for word in page.get_text("words"):
        if len(word) < 5:
            continue
        text = str(word[4] or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = [float(value) for value in word[:4]]
        result.append({"text": text, "bbox": [x0, y0, x1, y1], "x0": x0, "y0": y0, "x1": x1, "y1": y1, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2})
    return result


def _line_groups(page: Any, *, y_tolerance: float = 4.0) -> list[dict[str, Any]]:
    words = sorted(_words(page), key=lambda item: (round(float(item["cy"]) / y_tolerance), item["x0"]))
    groups: list[list[dict[str, Any]]] = []
    for word in words:
        for group in groups:
            if abs(float(group[0]["cy"]) - float(word["cy"])) <= y_tolerance:
                group.append(word)
                break
        else:
            groups.append([word])
    result: list[dict[str, Any]] = []
    fitz = _load_fitz()
    for group in groups:
        ordered = sorted(group, key=lambda item: item["x0"])
        text = " ".join(str(item["text"]) for item in ordered)
        rect = _union_rect(fitz, [fitz.Rect(item["bbox"]) for item in ordered])
        if rect:
            result.append({"text": text, "words": ordered, "rect": rect, "cy": sum(float(item["cy"]) for item in ordered) / len(ordered)})
    return sorted(result, key=lambda item: item["cy"])


def _expanded(fitz: Any, rect: Any, margins: tuple[float, float, float, float], page_rect: Any) -> Any:
    left, top, right, bottom = margins
    return fitz.Rect(
        max(page_rect.x0, rect.x0 - left),
        max(page_rect.y0, rect.y0 - top),
        min(page_rect.x1, rect.x1 + right),
        min(page_rect.y1, rect.y1 + bottom),
    )


def _draw_textbox(
    page: Any,
    rect: Any,
    text: str,
    *,
    fontsize: float,
    fontname: str,
    fontfile: str | None,
    align: int,
    rotate: int = 0,
    color: tuple[float, float, float] = (0.05, 0.05, 0.05),
) -> float:
    kwargs: dict[str, Any] = {
        "fontsize": fontsize,
        "fontname": fontname,
        "color": color,
        "align": align,
        "rotate": rotate,
        "lineheight": 1.05,
    }
    if fontfile:
        kwargs["fontfile"] = fontfile
    return float(page.insert_textbox(rect, text, **kwargs))


def _fit_draw(
    fitz: Any,
    page: Any,
    rect: Any,
    text: str,
    *,
    start_size: float,
    min_size: float,
    fontname: str,
    fontfile: str | None,
    align: int,
    rotate: int = 0,
    color: tuple[float, float, float] = (0.05, 0.05, 0.05),
) -> dict[str, Any]:
    size = start_size
    attempts = []
    while size >= min_size:
        result = _draw_textbox(page, rect, text, fontsize=size, fontname=fontname, fontfile=fontfile, align=align, rotate=rotate, color=color)
        attempts.append({"fontsize": round(size, 3), "result": round(result, 3)})
        if result >= 0:
            return {"status": "ok", "fontsize": round(size, 3), "attempts": attempts}
        size -= 0.5
    result = _draw_textbox(page, rect, text, fontsize=min_size, fontname=fontname, fontfile=fontfile, align=align, rotate=rotate, color=color)
    return {"status": "overflow", "fontsize": round(min_size, 3), "result": round(result, 3), "attempts": attempts}


def _safe_fill(fitz: Any, page: Any, rect: Any, mode: str) -> tuple[bool, dict[str, Any], tuple[float, float, float], tuple[float, float, float]]:
    background = _background_evidence(fitz, page, rect)
    safe = bool(background.get("safe")) or mode == "force"
    fill = _pdf_color_from_rgb(background.get("dominant_rgb"))
    text = _text_color_for_background(fill)
    return safe, background, fill, text


def _redact(page: Any, rect: Any, fill: tuple[float, float, float]) -> None:
    page.add_redact_annot(rect, fill=fill)
    page.apply_redactions()


def _cover_year_plan(fitz: Any, source_doc: Any) -> dict[str, Any] | None:
    if len(source_doc) < 1:
        return None
    page = source_doc[0]
    words = [item for item in _words(page) if re.fullmatch(r"[206]", item["text"]) and item["x0"] > page.rect.width * 0.72 and item["y0"] < 240]
    if len(words) < 4:
        return None
    words = sorted(words[:4], key=lambda item: item["y0"])
    text = "".join(item["text"] for item in words)
    if text != "2026":
        return None
    rect = _union_rect(fitz, [fitz.Rect(item["bbox"]) for item in words])
    return {
        "kind": "cover_year",
        "page": 1,
        "source_text": "2026",
        "source_bbox": _rect_to_list(rect),
        "target_bbox": _rect_to_list(_expanded(fitz, rect, (8, 4, 8, 4), page.rect)),
    }


def _replacement_for_email_line(line_text: str) -> str:
    emails = re.findall(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", line_text)
    email = emails[0] if emails else ""
    lowered = line_text.lower()
    if "shahed@stanford.edu" in lowered:
        return "人工智能指数欢迎反馈和明年的新想法。请通过 shahed@stanford.edu 联系我们。"
    if "polyu.edu.hk" in lowered or "hong kong polytechnic" in lowered:
        return f"香港理工大学语言科学与技术系，中国香港。邮箱：{email or 'andrew.cheung@polyu.edu.hk'}"
    if email:
        return re.sub(r"\s+", " ", line_text).strip()
    return line_text


def _email_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for page_index, page in enumerate(source_doc):
        for line in _line_groups(page):
            line_text = str(line.get("text") or "")
            if not re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", line_text):
                continue
            rect = line["rect"]
            plans.append(
                {
                    "kind": "contact_email",
                    "page": page_index + 1,
                    "source_text": line_text,
                    "replacement_text": _replacement_for_email_line(line_text),
                    "source_bbox": _rect_to_list(rect),
                    "target_bbox": _rect_to_list(_expanded(fitz, rect, (10, 4, 10, 4), page.rect)),
                }
            )
    return plans


def _journal_header_footer_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()
    for page_index, page in enumerate(source_doc):
        for line in _line_groups(page):
            text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
            if not text:
                continue
            y = float(line.get("cy") or 0)
            is_y_band = y < 90 or y > page.rect.height - 90
            is_journal_line = bool(re.search(r"HUMANITIES\s+AND\s+SOCIAL\s+SCIENCES|doi\.org/10\.1057/s41599", text, re.I))
            if not (is_y_band and is_journal_line):
                continue
            key = (page_index + 1, text, int(round(y)))
            if key in seen:
                continue
            seen.add(key)
            rect = line["rect"]
            plans.append(
                {
                    "kind": "journal_header_footer",
                    "page": page_index + 1,
                    "source_text": text,
                    "replacement_text": text,
                    "source_bbox": _rect_to_list(rect),
                    "target_bbox": _rect_to_list(_expanded(fitz, rect, (12, 3, 12, 3), page.rect)),
                }
            )
    return plans


def _chart_axis_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for page_number in (18, 19):
        if len(source_doc) < page_number:
            continue
        page = source_doc[page_number - 1]
        words = _words(page)
        vertical = [
            item
            for item in words
            if item["text"].lower() in {"number", "notable", "models"}
            and item["x0"] < 70
            and 150 < item["cy"] < 520
        ]
        if len(vertical) < 3:
            continue
        rect = _union_rect(fitz, [fitz.Rect(item["bbox"]) for item in vertical])
        plans.append(
            {
                "kind": "chart_axis_label",
                "page": page_number,
                "source_text": "Number of notable AI models",
                "replacement_text": "知名人工智能模型数量",
                "source_bbox": _rect_to_list(rect),
                "target_bbox": _rect_to_list(_expanded(fitz, rect, (6, 8, 6, 8), page.rect)),
            }
        )
    return plans


def _publisher_badge_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    if len(source_doc) < 1:
        return plans
    page = source_doc[0]
    text = page.get_text("text")
    if "HUMANITIES AND SOCIAL SCIENCES COMMUNICATIONS" not in text:
        return plans
    rect = fitz.Rect(465.0, 112.0, 575.0, 165.0)
    plans.append(
        {
            "kind": "source_region_clone",
            "role": "nature_publisher_check_for_updates_badge",
            "page": 1,
            "source_text": "Check for updates",
            "source_bbox": _rect_to_list(rect),
            "target_bbox": _rect_to_list(rect),
        }
    )
    return plans


def _table_caption_replacement(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    match = re.match(r"Table\s+(\d+)\s*(.*)", value, flags=re.I)
    if not match:
        return value
    number = match.group(1)
    tail = match.group(2).strip(" .")
    lowered = tail.lower()
    if "descriptive statistics" in lowered and "translation corpora" in lowered:
        return f"表 {number} 翻译语料库描述性统计。"
    if "significant differences" in lowered or ("signi" in lowered and "differences" in lowered):
        return f"表 {number} 显著差异数量。"
    return f"表 {number} {tail}".strip()


def _table_caption_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for page_index, page in enumerate(source_doc):
        used_rects: list[list[float]] = []
        for line in _line_groups(page):
            text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
            if not re.match(r"^Table\s+\d+\b", text, flags=re.I):
                continue
            if re.match(r"^Table\s+\d+\s+details\b", text, flags=re.I):
                continue
            rect = line["rect"]
            used_rects.append(_rect_to_list(rect))
            plans.append(
                {
                    "kind": "table_caption",
                    "page": page_index + 1,
                    "source_text": text,
                    "replacement_text": _table_caption_replacement(text),
                    "source_bbox": _rect_to_list(rect),
                    "target_bbox": _rect_to_list(_expanded(fitz, rect, (8, 3, 160, 3), page.rect)),
                }
            )
        words = _words(page)
        for word in words:
            if str(word.get("text") or "").lower() != "table":
                continue
            number_words = [
                item
                for item in words
                if re.fullmatch(r"\d{1,2}", str(item.get("text") or ""))
                and abs(float(item["cy"]) - float(word["cy"])) <= 8
                and 0 <= float(item["x0"]) - float(word["x1"]) <= 18
            ]
            if not number_words:
                continue
            line_words = [item for item in words if abs(float(item["cy"]) - float(word["cy"])) <= 8 and item["x0"] >= word["x0"] - 2 and item["x0"] <= page.rect.width - 45]
            rect = _union_rect(fitz, [fitz.Rect(item["bbox"]) for item in line_words]) or fitz.Rect(word["bbox"])
            rect_list = _rect_to_list(rect)
            if any(abs(rect_list[0] - old[0]) < 2 and abs(rect_list[1] - old[1]) < 2 for old in used_rects):
                continue
            text = " ".join(str(item["text"]) for item in sorted(line_words, key=lambda item: item["x0"]))
            if re.match(r"^Table\s+\d+\s+details\b", text, flags=re.I):
                continue
            plans.append(
                {
                    "kind": "table_caption",
                    "page": page_index + 1,
                    "source_text": text,
                    "replacement_text": _table_caption_replacement(text),
                    "source_bbox": rect_list,
                    "target_bbox": _rect_to_list(_expanded(fitz, rect, (8, 3, 160, 3), page.rect)),
                }
            )
    return plans


def _looks_like_reference_text(text: str) -> bool:
    years = len(re.findall(r"(?:19|20)\d{2}", text))
    urls = len(re.findall(r"https?://|doi\.org|arXiv", text, flags=re.I))
    authors = len(re.findall(r"\b[A-Z][A-Za-z'’-]+,\s+[A-Z]|\bet\s+al\.?", text))
    venues = len(re.findall(r"\b(?:Transl|Linguist|Commun|Comput|Survey|Press|Journal|Review|Proc)\b", text, flags=re.I))
    return years >= 4 and (urls >= 1 or authors >= 3 or venues >= 3)


def _references_region_clone_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    in_references = False
    for page_index, page in enumerate(source_doc):
        heading_words = [word for word in _words(page) if str(word.get("text") or "").strip().lower() in {"references", "参考文献"}]
        heading = min(heading_words, key=lambda item: float(item["y0"])) if heading_words else None
        page_text = page.get_text("text")
        if heading:
            in_references = True
            start_y = max(page.rect.y0 + 30, float(heading["y0"]) - 6)
        elif in_references and _looks_like_reference_text(page_text):
            start_y = page.rect.y0 + 35
        else:
            if in_references and not _looks_like_reference_text(page_text):
                in_references = False
            continue
        rect = fitz.Rect(page.rect.x0 + 30, start_y, page.rect.x1 - 30, page.rect.y1 - 48)
        plans.append(
            {
                "kind": "source_region_clone",
                "role": "references_region",
                "page": page_index + 1,
                "source_text": "References",
                "source_bbox": _rect_to_list(rect),
                "target_bbox": _rect_to_list(rect),
                "redact_before_clone": True,
            }
        )
    return plans


def _example_block_clone_plans(fitz: Any, source_doc: Any) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for page_index, page in enumerate(source_doc):
        marker_lines = [
            line
            for line in _line_groups(page)
            if re.search(r"\b(?:Example\s+\d+|ST|HT|NMT-GT|LLM-[A-Za-z0-9-]+)\s*[:：]", str(line.get("text") or ""), re.I)
        ]
        if not marker_lines:
            continue
        min_y = min(float(line["rect"].y0) for line in marker_lines)
        max_y = max(float(line["rect"].y1) for line in marker_lines)
        rect = fitz.Rect(page.rect.x0 + 35, max(page.rect.y0 + 35, min_y - 10), page.rect.x1 - 35, min(page.rect.y1 - 55, max_y + 150))
        plans.append(
            {
                "kind": "source_region_clone",
                "role": "example_block_region",
                "page": page_index + 1,
                "source_text": "Example block",
                "source_bbox": _rect_to_list(rect),
                "target_bbox": _rect_to_list(rect),
                "redact_before_clone": True,
            }
        )
    return plans


def build_repair_plan(source_pdf: Path) -> dict[str, Any]:
    fitz = _load_fitz()
    manifest: dict[str, Any] = {"version": 1, "status": "ok", "source_pdf": str(source_pdf), "actions": []}
    try:
        source_doc = fitz.open(source_pdf)
    except Exception as exc:
        manifest.update({"status": "failed", "error": repr(exc)})
        return manifest
    try:
        for action in [_cover_year_plan(fitz, source_doc)]:
            if action:
                manifest["actions"].append(action)
        manifest["actions"].extend(_email_plans(fitz, source_doc))
        manifest["actions"].extend(_journal_header_footer_plans(fitz, source_doc))
        manifest["actions"].extend(_publisher_badge_plans(fitz, source_doc))
        manifest["actions"].extend(_table_caption_plans(fitz, source_doc))
        manifest["actions"].extend(_example_block_clone_plans(fitz, source_doc))
        manifest["actions"].extend(_references_region_clone_plans(fitz, source_doc))
        manifest["actions"].extend(_chart_axis_plans(fitz, source_doc))
        manifest["action_count"] = len(manifest["actions"])
        if not manifest["actions"]:
            manifest["status"] = "no_candidates"
    finally:
        source_doc.close()
    return manifest


def _apply_cover_year(fitz: Any, page: Any, action: dict[str, Any], mode: str) -> dict[str, Any]:
    rect = fitz.Rect(action["target_bbox"])
    safe, background, fill, color = _safe_fill(fitz, page, rect, mode)
    result = {"kind": action["kind"], "page": action["page"], "status": "skipped_background_unsafe", "background": background}
    if not safe:
        return result
    _redact(page, rect, fill)
    fontname, fontfile, font_status = _font("helv")
    draw = _fit_draw(fitz, page, rect, "2026", start_size=32.0, min_size=18.0, fontname=fontname, fontfile=fontfile, align=fitz.TEXT_ALIGN_CENTER, rotate=90, color=color)
    result.update({"status": "applied", "font_status": font_status, "draw": draw, "target_bbox": action["target_bbox"]})
    return result


def _apply_email(fitz: Any, page: Any, action: dict[str, Any], mode: str, engine_home: Path | None) -> dict[str, Any]:
    rect = fitz.Rect(action["target_bbox"])
    safe, background, fill, color = _safe_fill(fitz, page, rect, mode)
    result = {"kind": action["kind"], "page": action["page"], "status": "skipped_background_unsafe", "background": background}
    if not safe:
        return result
    _redact(page, rect, fill)
    fontname, fontfile, font_status = _font("china-s", engine_home)
    draw = _fit_draw(
        fitz,
        page,
        rect,
        action["replacement_text"],
        start_size=8.8,
        min_size=6.0,
        fontname=fontname,
        fontfile=fontfile,
        align=fitz.TEXT_ALIGN_LEFT,
        color=color,
    )
    result.update({"status": "applied", "font_status": font_status, "draw": draw, "target_bbox": action["target_bbox"], "replacement_text": action["replacement_text"]})
    return result


def _apply_chart_axis(fitz: Any, page: Any, action: dict[str, Any], mode: str, engine_home: Path | None) -> dict[str, Any]:
    rect = fitz.Rect(action["target_bbox"])
    safe, background, fill, color = _safe_fill(fitz, page, rect, mode)
    result = {"kind": action["kind"], "page": action["page"], "status": "skipped_background_unsafe", "background": background}
    if not safe:
        return result
    _redact(page, rect, fill)
    fontname, fontfile, font_status = _font("china-s", engine_home)
    text = action["replacement_text"]
    draw = _fit_draw(
        fitz,
        page,
        rect,
        text,
        start_size=8.0,
        min_size=5.5,
        fontname=fontname,
        fontfile=fontfile,
        align=fitz.TEXT_ALIGN_CENTER,
        rotate=90,
        color=color,
    )
    result.update({"status": "applied", "font_status": font_status, "draw": draw, "target_bbox": action["target_bbox"], "replacement_text": text})
    return result


def _apply_journal_header_footer(fitz: Any, page: Any, action: dict[str, Any], mode: str) -> dict[str, Any]:
    rect = fitz.Rect(action["target_bbox"])
    safe, background, fill, color = _safe_fill(fitz, page, rect, mode)
    result = {"kind": action["kind"], "page": action["page"], "status": "skipped_background_unsafe", "background": background}
    if not safe:
        return result
    _redact(page, rect, fill)
    draw = _fit_draw(
        fitz,
        page,
        rect,
        action["replacement_text"],
        start_size=7.2,
        min_size=4.8,
        fontname="helv",
        fontfile=None,
        align=fitz.TEXT_ALIGN_LEFT,
        color=color,
    )
    result.update({"status": "applied", "font_status": "builtin", "draw": draw, "target_bbox": action["target_bbox"], "replacement_text": action["replacement_text"]})
    return result


def _apply_source_region_clone(fitz: Any, source_page: Any, target_page: Any, action: dict[str, Any]) -> dict[str, Any]:
    source_rect = fitz.Rect(action["source_bbox"])
    target_rect = fitz.Rect(action["target_bbox"])
    pixmap = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=source_rect, alpha=False)
    if action.get("redact_before_clone"):
        target_page.add_redact_annot(target_rect, fill=(1, 1, 1))
        target_page.apply_redactions()
    target_page.insert_image(target_rect, pixmap=pixmap, keep_proportion=False)
    return {"kind": action["kind"], "role": action.get("role"), "page": action["page"], "status": "applied", "target_bbox": action["target_bbox"], "source_bbox": action["source_bbox"]}


def _apply_table_caption(fitz: Any, page: Any, action: dict[str, Any], mode: str, engine_home: Path | None) -> dict[str, Any]:
    rect = fitz.Rect(action["target_bbox"])
    safe, background, fill, color = _safe_fill(fitz, page, rect, mode)
    result = {"kind": action["kind"], "page": action["page"], "status": "skipped_background_unsafe", "background": background}
    if not safe:
        return result
    _redact(page, rect, fill)
    fontname, fontfile, font_status = _font("china-s", engine_home)
    draw = _fit_draw(
        fitz,
        page,
        rect,
        action["replacement_text"],
        start_size=8.2,
        min_size=5.5,
        fontname=fontname,
        fontfile=fontfile,
        align=fitz.TEXT_ALIGN_LEFT,
        color=color,
    )
    result.update({"status": "applied", "font_status": font_status, "draw": draw, "target_bbox": action["target_bbox"], "replacement_text": action["replacement_text"]})
    return result


def _style_tag_cleanup_actions(fitz: Any, doc: Any, mode: str, engine_home: Path | None) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    tag_re = re.compile(r"</?style\b[^>]*>", re.I)
    for page_index, page in enumerate(doc):
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if not isinstance(block, dict):
                continue
            for line in block.get("lines", []):
                if not isinstance(line, dict):
                    continue
                spans = [span for span in line.get("spans", []) if isinstance(span, dict)]
                line_text = "".join(str(span.get("text") or "") for span in spans)
                if not tag_re.search(line_text):
                    continue
                rects = [fitz.Rect(span.get("bbox")) for span in spans if isinstance(span.get("bbox"), (list, tuple)) and len(span.get("bbox")) == 4]
                rect = _union_rect(fitz, rects)
                if not rect:
                    continue
                target = _expanded(fitz, rect, (6, 3, 90, 3), page.rect)
                safe, background, fill, color = _safe_fill(fitz, page, target, mode)
                action = {"kind": "style_tag_cleanup", "page": page_index + 1, "status": "skipped_background_unsafe", "background": background, "target_bbox": _rect_to_list(target)}
                if not safe:
                    actions.append(action)
                    continue
                cleaned = tag_re.sub("", line_text)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                _redact(page, target, fill)
                fontname, fontfile, font_status = _font("china-s", engine_home)
                draw = _fit_draw(
                    fitz,
                    page,
                    target,
                    cleaned,
                    start_size=max(6.0, min(9.0, float(spans[0].get("size") or 8.0))),
                    min_size=5.0,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=fitz.TEXT_ALIGN_LEFT,
                    color=color,
                )
                action.update({"status": "applied", "font_status": font_status, "draw": draw, "replacement_text": cleaned})
                actions.append(action)
    return actions


def _policy_literal_cleanup_actions(fitz: Any, doc: Any, mode: str, engine_home: Path | None) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    replacements: list[tuple[str, str, str]] = []
    for term, pairs in policy_utils.TERM_REPLACEMENT_HINTS.items():
        for source_text, replacement_text in pairs:
            if source_text == replacement_text:
                continue
            if not re.search(r"[\u4e00-\u9fff]", source_text):
                continue
            replacements.append((str(term), str(source_text), str(replacement_text)))
    seen: set[tuple[int, str, tuple[float, float, float, float]]] = set()
    for page_index, page in enumerate(doc):
        for term, source_text, replacement_text in replacements:
            try:
                matches = page.search_for(source_text)
            except Exception:
                matches = []
            for rect in matches:
                key = (page_index, source_text, tuple(round(float(value), 2) for value in rect))
                if key in seen:
                    continue
                seen.add(key)
                target = _expanded(fitz, rect, (1.5, 1.0, 1.5, 1.0), page.rect)
                safe, background, fill, color = _safe_fill(fitz, page, target, mode)
                if (
                    not safe
                    and float(background.get("average_brightness") or 0) >= 220
                    and float(background.get("colored_ratio") or 0) <= 0.02
                    and list(background.get("dominant_rgb") or []) == [255, 255, 255]
                ):
                    safe = True
                    background = {**background, "policy_literal_white_region_override": True}
                action = {
                    "kind": "policy_literal_cleanup",
                    "term": term,
                    "page": page_index + 1,
                    "status": "skipped_background_unsafe",
                    "background": background,
                    "source_text": source_text,
                    "replacement_text": replacement_text,
                    "target_bbox": _rect_to_list(target),
                }
                if not safe:
                    actions.append(action)
                    continue
                _redact(page, target, fill)
                fontname, fontfile, font_status = _font("china-s", engine_home)
                draw = _fit_draw(
                    fitz,
                    page,
                    target,
                    replacement_text,
                    start_size=max(6.0, min(9.5, float(rect.height) * 0.9)),
                    min_size=5.0,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=fitz.TEXT_ALIGN_CENTER,
                    color=color,
                )
                action.update({"status": "applied", "font_status": font_status, "draw": draw})
                actions.append(action)
    return actions


def apply_metadata_label_repair(
    *,
    source_pdf: Path,
    translated_pdf: Path | None,
    output_dir: Path,
    mode: str = "auto",
    engine_home: Path | None = None,
) -> dict[str, Any]:
    manifest_path = output_dir / "metadata_label_repair_manifest.json"
    manifest: dict[str, Any] = {
        "version": 1,
        "status": "skipped",
        "mode": mode,
        "source_pdf": str(source_pdf),
        "input_translated_pdf": str(translated_pdf) if translated_pdf else None,
        "output_pdf": None,
        "manifest_path": str(manifest_path),
        "plan": None,
        "applied_action_count": 0,
        "skipped_action_count": 0,
        "actions": [],
    }
    if mode == "off":
        manifest["reason"] = "metadata_label_repair_off"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    if not translated_pdf or not translated_pdf.exists():
        manifest["reason"] = "missing_translated_pdf"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    fitz = _load_fitz()
    plan = build_repair_plan(source_pdf)
    manifest["plan"] = plan
    if plan.get("status") in {"failed", "no_candidates"}:
        manifest["reason"] = plan.get("status")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    output_pdf = output_dir / f"{source_pdf.stem}.metadata-label-repaired.zh.mono.pdf"
    try:
        doc = fitz.open(translated_pdf)
        source_doc = fitz.open(source_pdf)
        for action in plan.get("actions", []):
            page_number = int(action.get("page") or 0)
            if page_number < 1 or page_number > len(doc):
                outcome = {"kind": action.get("kind"), "page": page_number, "status": "skipped_page_missing"}
            else:
                page = doc[page_number - 1]
                if action.get("kind") == "cover_year":
                    outcome = _apply_cover_year(fitz, page, action, mode)
                elif action.get("kind") == "contact_email":
                    outcome = _apply_email(fitz, page, action, mode, engine_home)
                elif action.get("kind") == "chart_axis_label":
                    outcome = _apply_chart_axis(fitz, page, action, mode, engine_home)
                elif action.get("kind") == "journal_header_footer":
                    outcome = _apply_journal_header_footer(fitz, page, action, mode)
                elif action.get("kind") == "source_region_clone":
                    outcome = _apply_source_region_clone(fitz, source_doc[page_number - 1], page, action)
                elif action.get("kind") == "table_caption":
                    outcome = _apply_table_caption(fitz, page, action, mode, engine_home)
                else:
                    outcome = {"kind": action.get("kind"), "page": page_number, "status": "skipped_unknown_kind"}
            manifest["actions"].append(outcome)
            if outcome.get("status") == "applied":
                manifest["applied_action_count"] += 1
            else:
                manifest["skipped_action_count"] += 1
        for outcome in _style_tag_cleanup_actions(fitz, doc, mode, engine_home):
            manifest["actions"].append(outcome)
            if outcome.get("status") == "applied":
                manifest["applied_action_count"] += 1
            else:
                manifest["skipped_action_count"] += 1
        for outcome in _policy_literal_cleanup_actions(fitz, doc, mode, engine_home):
            manifest["actions"].append(outcome)
            if outcome.get("status") == "applied":
                manifest["applied_action_count"] += 1
            else:
                manifest["skipped_action_count"] += 1
        if manifest["applied_action_count"]:
            doc.save(output_pdf, garbage=4, deflate=True)
            manifest["output_pdf"] = str(output_pdf)
            manifest["status"] = "applied" if not manifest["skipped_action_count"] else "partial"
        else:
            manifest["status"] = "skipped"
            manifest["reason"] = "no_actions_applied"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = repr(exc)
    finally:
        try:
            doc.close()  # type: ignore[name-defined]
        except Exception:
            pass
        try:
            source_doc.close()  # type: ignore[name-defined]
        except Exception:
            pass
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
