#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import layout_role_policy

SCRIPT_INTERFACE = "internal-module"


EXTRA_TOC_TRANSLATIONS = {
    "appendix": "附录",
    "chapter highlights": "章节亮点",
    "top takeaways": "核心要点",
    "introduction": "引言",
    "research and development": "研究与开发",
    "technical performance": "技术性能",
    "ai development activity overview": "AI开发活动概览",
    "notable ai models": "知名AI模型",
    "parameter and compute trends": "参数与计算趋势",
    "compute and infrastructure": "计算与基础设施",
    "performance and efficiency": "性能与效率",
    "global computing capacity": "全球计算能力",
    "hardware for notable models": "知名模型硬件",
    "data center power capacity": "数据中心供电能力",
    "data center usage": "数据中心使用",
    "data centers": "数据中心",
    "ai infrastructure beyond gpus": "GPU之外的AI基础设施",
    "ai conference proceedings": "AI会议论文",
    "ai journal publications": "AI期刊论文",
    "ai patents": "AI专利",
    "ai policy": "AI政策",
    "economy": "经济",
    "science and medicine": "科学与医学",
    "education": "教育",
    "policy and governance": "政策与治理",
    "diversity": "多样性",
    "public opinion": "公众舆论",
    "projects": "项目",
    "stars": "星标",
    "by national affiliation": "按国家/地区归属划分",
    "by sector and organization": "按部门与组织划分",
    "by sector": "按部门划分",
    "top 100 publications": "前100篇论文",
    "forward citations flow": "前向引用流向",
    "speed of knowledge diffusion": "知识扩散速度",
    "technological proximity": "技术接近度",
    "highlight: will models run out of data?": "专题：模型会耗尽数据吗？",
    "highlight: will models run out of data": "专题：模型会耗尽数据吗？",
    "highlight: ai patent examples": "专题：AI专利示例",
    "ai authors and inventors": "AI作者与发明者",
    "open-source ai software": "开源AI软件",
    "publications": "出版物",
}


def _load_fitz():
    import fitz  # type: ignore

    return fitz


def _rect_to_list(rect: Any) -> list[float]:
    return [round(float(rect.x0), 3), round(float(rect.y0), 3), round(float(rect.x1), 3), round(float(rect.y1), 3)]


def _rect_from_list(fitz: Any, value: list[float]) -> Any:
    return fitz.Rect(float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def _union_rect(fitz: Any, rects: list[Any]) -> Any | None:
    if not rects:
        return None
    result = fitz.Rect(rects[0])
    for rect in rects[1:]:
        result |= fitz.Rect(rect)
    return result


def _clip_rect(fitz: Any, rect: Any, page_rect: Any) -> Any:
    return fitz.Rect(
        max(page_rect.x0, rect.x0),
        max(page_rect.y0, rect.y0),
        min(page_rect.x1, rect.x1),
        min(page_rect.y1, rect.y1),
    )


def _parse_page_selection(selection: str | None) -> set[int] | None:
    if not selection:
        return None
    pages: set[int] = set()
    for chunk in str(selection).split(","):
        item = chunk.strip()
        if not item:
            continue
        if "-" in item:
            start, end = [int(part.strip()) for part in item.split("-", 1)]
            pages.update(range(min(start, end), max(start, end) + 1))
        else:
            pages.add(int(item))
    return {page for page in pages if page > 0}


def _line_fragments(page: Any) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    words = page.get_text("words")
    for word in words:
        if len(word) < 5:
            continue
        text = str(word[4] or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = [float(v) for v in word[:4]]
        fragments.append(
            {
                "text": re.sub(r"\s+", " ", text),
                "bbox": [x0, y0, x1, y1],
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "cx": (x0 + x1) / 2.0,
                "cy": (y0 + y1) / 2.0,
                "size": max(6.5, y1 - y0),
            }
        )
    return sorted(fragments, key=lambda item: (round(float(item["y0"]), 1), float(item["x0"])))


def _numeric_fragments(fragments: list[dict[str, Any]], page_width: float, page_height: float) -> list[dict[str, Any]]:
    result = []
    for fragment in fragments:
        text = fragment["text"].strip()
        if not re.fullmatch(r"\d{1,3}", text):
            continue
        if fragment["cy"] < 55 or fragment["cy"] > page_height - 70:
            continue
        if fragment["cx"] < page_width * 0.35:
            continue
        result.append(fragment)
    return result


def _title_fragments_for_number(
    fragments: list[dict[str, Any]],
    number_fragment: dict[str, Any],
    previous_number_y: float,
    page_width: float,
    heading_bottom: float,
    role: str,
) -> list[dict[str, Any]]:
    num_x = float(number_fragment["x0"])
    num_y = float(number_fragment["cy"])
    if role != "global_toc" and num_x >= page_width * 0.65:
        title_min_x = page_width * 0.49
        title_max_x = num_x - 12
    else:
        title_min_x = 0.0
        title_max_x = num_x - 12
    lower_y = max(previous_number_y + 3, heading_bottom + 8, 58)
    upper_y = num_y + 7
    title_parts: list[dict[str, Any]] = []
    for fragment in fragments:
        text = fragment["text"].strip()
        if re.fullmatch(r"\d{1,3}", text):
            continue
        if re.fullmatch(r"(?i)contents|ai index report 20\d{2}", text):
            continue
        if fragment["cy"] < lower_y or fragment["cy"] > upper_y:
            continue
        if fragment["x0"] < title_min_x or fragment["x1"] > title_max_x:
            continue
        title_parts.append(fragment)
    return sorted(title_parts, key=lambda item: (round(float(item["y0"]), 1), float(item["x0"])))


def _group_numbers_by_column(numbers: list[dict[str, Any]], page_width: float) -> list[list[dict[str, Any]]]:
    if not numbers:
        return []
    left = [item for item in numbers if item["x0"] < page_width * 0.65]
    right = [item for item in numbers if item["x0"] >= page_width * 0.65]
    groups = []
    for group in (left, right):
        if group:
            groups.append(sorted(group, key=lambda item: (float(item["cy"]), float(item["x0"]))))
    return groups


def _page_role(page_number: int, fragments: list[dict[str, Any]], numbers: list[dict[str, Any]], page_width: float) -> str | None:
    texts = [item["text"] for item in fragments]
    joined = " ".join(texts)
    has_contents = any(re.fullmatch(r"(?i)contents", item) for item in texts)
    has_chapter = bool(re.search(r"(?i)\bchapter highlights\b", joined))
    right_numbers = [item for item in numbers if item["x0"] >= page_width * 0.65]
    if has_contents and page_number <= 5 and len(numbers) >= 5:
        return "global_toc"
    if has_chapter and len(numbers) >= 4:
        return "chapter_highlights_index"
    if (has_contents or has_chapter) and len(numbers) >= 4 and (right_numbers or has_chapter):
        return "chapter_index"
    return None


def _background_evidence(fitz: Any, page: Any, region: Any) -> dict[str, Any]:
    image_intersects = False
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1:
            continue
        bbox = block.get("bbox")
        if bbox and region.intersects(fitz.Rect(bbox)):
            image_intersects = True
            break
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(0.35, 0.35), clip=region, colorspace=fitz.csRGB, alpha=False)
        samples = pix.samples
        channels = max(1, int(pix.n))
        total = max(1, pix.width * pix.height)
        nonwhite = 0
        colored = 0
        brightness_sum = 0
        buckets: dict[tuple[int, int, int], int] = {}
        for offset in range(0, len(samples), channels):
            r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
            brightness = (r + g + b) / 3
            brightness_sum += brightness
            if brightness < 245:
                nonwhite += 1
            if brightness > 70 and max(r, g, b) - min(r, g, b) > 18:
                colored += 1
            bucket = (round(r / 16) * 16, round(g / 16) * 16, round(b / 16) * 16)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        average_brightness = brightness_sum / total
        nonwhite_ratio = nonwhite / total
        colored_ratio = colored / total
        dominant_rgb, dominant_count = max(buckets.items(), key=lambda item: item[1]) if buckets else ((255, 255, 255), 0)
        dominant_ratio = dominant_count / total
    except Exception as exc:  # pragma: no cover - depends on renderer internals
        return {
            "status": "unknown",
            "image_intersects": image_intersects,
            "error": repr(exc),
            "safe": not image_intersects,
        }
    return {
        "status": "ok",
        "image_intersects": image_intersects,
        "average_brightness": round(average_brightness, 3),
        "nonwhite_ratio": round(nonwhite_ratio, 5),
        "colored_ratio": round(colored_ratio, 5),
        "dominant_rgb": [int(max(0, min(255, value))) for value in dominant_rgb],
        "dominant_ratio": round(dominant_ratio, 5),
        "safe": (not image_intersects) and (average_brightness >= 230 or dominant_ratio >= 0.28),
    }


def extract_toc_plan(source_pdf: Path, *, pages_selection: str | None = None, max_auto_pages: int = 24) -> dict[str, Any]:
    fitz = _load_fitz()
    selected_pages = _parse_page_selection(pages_selection)
    plan: dict[str, Any] = {
        "version": 1,
        "status": "ok",
        "source_pdf": str(source_pdf),
        "pages_selection": pages_selection,
        "pages": [],
        "candidate_page_count": 0,
        "row_count": 0,
    }
    try:
        doc = fitz.open(source_pdf)
    except Exception as exc:
        plan.update({"status": "failed", "error": repr(exc)})
        return plan
    try:
        page_range = selected_pages or set(range(1, min(len(doc), max_auto_pages) + 1))
        for page_number in sorted(page_range):
            if page_number < 1 or page_number > len(doc):
                continue
            page = doc[page_number - 1]
            fragments = _line_fragments(page)
            numbers = _numeric_fragments(fragments, float(page.rect.width), float(page.rect.height))
            role = _page_role(page_number, fragments, numbers, float(page.rect.width))
            if not role:
                continue
            heading_fragments = [
                item for item in fragments if re.fullmatch(r"(?i)contents", item["text"].strip())
            ]
            heading_bottom = max([float(item["y1"]) for item in heading_fragments], default=55.0)
            rows: list[dict[str, Any]] = []
            for column_index, group in enumerate(_group_numbers_by_column(numbers, float(page.rect.width))):
                previous_y = heading_bottom
                for number in group:
                    title_parts = _title_fragments_for_number(
                        fragments,
                        number,
                        previous_y,
                        float(page.rect.width),
                        heading_bottom,
                        role,
                    )
                    previous_y = float(number["cy"])
                    if not title_parts:
                        continue
                    title_text = " ".join(part["text"] for part in title_parts)
                    title_text = re.sub(r"\s+", " ", title_text).strip()
                    title_rect = _union_rect(fitz, [fitz.Rect(part["bbox"]) for part in title_parts])
                    number_rect = fitz.Rect(number["bbox"])
                    row_rect = _union_rect(fitz, [title_rect, number_rect]) if title_rect else number_rect
                    rows.append(
                        {
                            "page": page_number,
                            "row_index": len(rows) + 1,
                            "source_title": title_text,
                            "source_page_number": number["text"],
                            "title_bbox": _rect_to_list(title_rect),
                            "page_number_bbox": _rect_to_list(number_rect),
                            "row_bbox": _rect_to_list(row_rect),
                            "column_index": column_index,
                            "confidence": 0.94 if title_text and number["text"] else 0.5,
                            "source_font_size": round(float(max(part["size"] for part in title_parts)), 3),
                        }
                    )
            if not rows:
                continue
            repair_rects = [fitz.Rect(row["row_bbox"]) for row in rows]
            repair_rects.extend(fitz.Rect(item["bbox"]) for item in heading_fragments)
            region = _union_rect(fitz, repair_rects)
            if region:
                region = _clip_rect(fitz, fitz.Rect(region.x0 - 8, region.y0 - 8, region.x1 + 8, region.y1 + 8), page.rect)
            background = _background_evidence(fitz, page, region) if region else {"safe": False}
            page_entry = {
                "page": page_number,
                "role": role,
                "row_count": len(rows),
                "repair_region_bbox": _rect_to_list(region),
                "heading_bboxes": [_rect_to_list(fitz.Rect(item["bbox"])) for item in heading_fragments],
                "background": background,
                "rows": rows,
            }
            plan["pages"].append(page_entry)
            plan["row_count"] += len(rows)
        plan["candidate_page_count"] = len(plan["pages"])
        if not plan["pages"]:
            plan["status"] = "no_candidates"
    finally:
        doc.close()
    return plan


def _split_prefix(title: str) -> tuple[str, str]:
    match = re.match(r"^\s*((?:\d+\.)+\d*|\d+)\s+(.+)$", title)
    if not match:
        return "", title.strip()
    return match.group(1).rstrip("."), match.group(2).strip()


def translate_toc_title(title: str, role: str) -> tuple[str, str]:
    prefix, body = _split_prefix(title)
    normalized = layout_role_policy.normalized_heading(body or title)
    direct = layout_role_policy.direct_output_for_role(role, f"{title} 999")
    if direct:
        direct = re.sub(r"\s+999\s*$", "", direct).strip()
        if direct and direct != title:
            return direct, "layout_role_policy"
    translated = (
        layout_role_policy.SECTION_HEADING_TRANSLATIONS.get(normalized)
        or layout_role_policy.CHART_LABEL_TRANSLATIONS.get(normalized)
        or EXTRA_TOC_TRANSLATIONS.get(normalized)
    )
    if translated:
        return (f"{prefix} {translated}".strip() if prefix else translated), "dictionary"
    chart = layout_role_policy.direct_output_for_role("chart_label", body or title)
    if chart and chart != body:
        return (f"{prefix} {chart}".strip() if prefix else chart), "chart_label"
    return title, "untranslated"


def _font_candidates(engine_home: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    env_font = os.environ.get("PAPER_TRANSLATION_CJK_FONT")
    if env_font:
        candidates.append(Path(env_font).expanduser())
    if engine_home:
        candidates.extend(
            [
                engine_home / "fonts" / "SourceHanSansCN-Regular.otf",
                engine_home / "fonts" / "SourceHanSerifCN-Regular.otf",
                engine_home / "fonts" / "NotoSansCJK-Regular.ttc",
            ]
        )
    candidates.extend(
        [
            Path("/System/Library/Fonts/STHeiti Light.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ]
    )
    return [path for path in candidates if path.exists()]


def _draw_textbox(page: Any, rect: Any, text: str, *, fontsize: float, fontname: str, fontfile: str | None, align: int, color: tuple[float, float, float]) -> float:
    kwargs: dict[str, Any] = {
        "fontsize": fontsize,
        "fontname": fontname,
        "color": color,
        "align": align,
        "lineheight": 1.05,
    }
    if fontfile:
        kwargs["fontfile"] = fontfile
    return float(page.insert_textbox(rect, text, **kwargs))


def _fit_and_draw(
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
    color: tuple[float, float, float] = (0.05, 0.05, 0.05),
) -> dict[str, Any]:
    fontsize = max(min_size, min(start_size, 12.0))
    attempts = []
    while fontsize >= min_size:
        trial = _draw_textbox(page, rect, text, fontsize=fontsize, fontname=fontname, fontfile=fontfile, align=align, color=color)
        attempts.append({"fontsize": round(fontsize, 3), "result": round(trial, 3)})
        if trial >= 0:
            return {"status": "ok", "fontsize": round(fontsize, 3), "attempts": attempts}
        fontsize -= 0.5
    fallback = _draw_textbox(page, rect, text, fontsize=min_size, fontname=fontname, fontfile=fontfile, align=align, color=color)
    return {"status": "overflow", "fontsize": round(min_size, 3), "result": round(fallback, 3), "attempts": attempts}


def _pdf_color_from_rgb(rgb: list[int] | None) -> tuple[float, float, float]:
    values = rgb if rgb and len(rgb) == 3 else [255, 255, 255]
    return tuple(max(0.0, min(1.0, float(value) / 255.0)) for value in values)  # type: ignore[return-value]


def _dominant_rgb_for_rect(fitz: Any, page: Any, rect: Any, *, fallback: list[int] | None = None) -> list[int]:
    try:
        clipped = _clip_rect(fitz, rect, page.rect)
        if clipped.is_empty:
            return fallback or [255, 255, 255]
        pix = page.get_pixmap(matrix=fitz.Matrix(0.7, 0.7), clip=clipped, colorspace=fitz.csRGB, alpha=False)
        samples = pix.samples
        channels = max(1, int(pix.n))
        buckets: dict[tuple[int, int, int], int] = {}
        for offset in range(0, len(samples), channels):
            r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
            # Coarse buckets intentionally ignore thin text strokes and rules.
            bucket = (round(r / 8) * 8, round(g / 8) * 8, round(b / 8) * 8)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        if not buckets:
            return fallback or [255, 255, 255]
        dominant, _ = max(buckets.items(), key=lambda item: item[1])
        return [int(max(0, min(255, value))) for value in dominant]
    except Exception:
        return fallback or [255, 255, 255]


def _text_color_for_background(fill_color: tuple[float, float, float]) -> tuple[float, float, float]:
    luminance = 0.2126 * fill_color[0] + 0.7152 * fill_color[1] + 0.0722 * fill_color[2]
    return (0.97, 0.97, 0.97) if luminance < 0.55 else (0.05, 0.05, 0.05)


def _blend_color(
    base: tuple[float, float, float],
    overlay: tuple[float, float, float],
    overlay_ratio: float,
) -> tuple[float, float, float]:
    ratio = max(0.0, min(1.0, overlay_ratio))
    return tuple(max(0.0, min(1.0, base[index] * (1.0 - ratio) + overlay[index] * ratio)) for index in range(3))  # type: ignore[return-value]


def _draw_row_rule(fitz: Any, page: Any, row: dict[str, Any], *, color: tuple[float, float, float]) -> dict[str, Any]:
    title_rect = _rect_from_list(fitz, row["title_bbox"])
    number_rect = _rect_from_list(fitz, row["page_number_bbox"])
    row_rect = _rect_from_list(fitz, row["row_bbox"])
    y = min(page.rect.y1 - 1, max(row_rect.y1, title_rect.y1, number_rect.y1) + 1.0)
    x0 = max(page.rect.x0, title_rect.x0)
    x1 = min(page.rect.x1, number_rect.x1 + 3.0)
    if x1 <= x0:
        return {"status": "skipped", "reason": "invalid_rule_geometry"}
    page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=color, width=0.35, overlay=True)
    return {"status": "ok", "bbox": [round(x0, 3), round(y, 3), round(x1, 3), round(y, 3)]}


def _heading_already_localized(fitz: Any, page: Any, heading_bboxes: list[list[float]]) -> bool:
    if not heading_bboxes:
        return False
    for bbox in heading_bboxes:
        rect = _rect_from_list(fitz, bbox)
        probe = _clip_rect(fitz, fitz.Rect(rect.x0 - 4, rect.y0 - 4, rect.x1 + 48, rect.y1 + 12), page.rect)
        text = re.sub(r"\s+", "", page.get_textbox(probe) or "")
        if "目录" in text:
            return True
    return False


def _toc_redaction_rects(fitz: Any, page: Any, page_plan: dict[str, Any], *, include_heading: bool = True) -> list[Any]:
    rects: list[Any] = []
    if include_heading:
        for bbox in page_plan.get("heading_bboxes") or []:
            rect = _rect_from_list(fitz, bbox)
            rects.append(_clip_rect(fitz, fitz.Rect(rect.x0 - 3, rect.y0 - 2, rect.x1 + 28, rect.y1 + 5), page.rect))
    for row in page_plan.get("rows", []):
        row_rect = _rect_from_list(fitz, row["row_bbox"])
        rects.append(_clip_rect(fitz, fitz.Rect(row_rect.x0 - 2, row_rect.y0 - 2, row_rect.x1 + 5, row_rect.y1 + 5), page.rect))
    return rects


def apply_toc_repair(
    *,
    source_pdf: Path,
    translated_pdf: Path | None,
    output_dir: Path,
    pages_selection: str | None = None,
    mode: str = "auto",
    engine_home: Path | None = None,
) -> dict[str, Any]:
    manifest_path = output_dir / "toc_repair_manifest.json"
    manifest: dict[str, Any] = {
        "version": 1,
        "status": "skipped",
        "mode": mode,
        "source_pdf": str(source_pdf),
        "input_translated_pdf": str(translated_pdf) if translated_pdf else None,
        "output_pdf": None,
        "manifest_path": str(manifest_path),
        "pages_selection": pages_selection,
        "plan": None,
        "applied_page_count": 0,
        "row_count": 0,
        "untranslated_title_count": 0,
        "background_unsafe_count": 0,
        "pages": [],
    }
    if mode == "off":
        manifest["reason"] = "toc_repair_off"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    if not translated_pdf or not translated_pdf.exists():
        manifest["reason"] = "missing_translated_pdf"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    fitz = _load_fitz()
    plan = extract_toc_plan(source_pdf, pages_selection=pages_selection)
    manifest["plan"] = plan
    if plan.get("status") in {"failed", "no_candidates"}:
        manifest["status"] = "skipped"
        manifest["reason"] = plan.get("status")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    font_paths = _font_candidates(engine_home)
    fontfile = str(font_paths[0]) if font_paths else None
    fontname = "toc-cjk" if fontfile else "china-s"
    manifest["font"] = {"fontname": fontname, "fontfile": fontfile, "status": "ok" if fontfile else "builtin_cjk_fallback"}
    output_pdf = output_dir / f"{source_pdf.stem}.toc-repaired.zh.mono.pdf"
    applied_any = False
    try:
        doc = fitz.open(translated_pdf)
        for page_plan in plan.get("pages", []):
            page_number = int(page_plan["page"])
            if page_number < 1 or page_number > len(doc):
                continue
            safe = bool(page_plan.get("background", {}).get("safe"))
            page = doc[page_number - 1]
            region = _rect_from_list(fitz, page_plan["repair_region_bbox"])
            translated_background = _background_evidence(fitz, page, region)
            if mode == "auto" and (not safe or not translated_background.get("safe")):
                manifest["background_unsafe_count"] += 1
                manifest["pages"].append(
                    {
                        "page": page_number,
                        "status": "skipped_background_unsafe",
                        "source_background": page_plan.get("background"),
                        "translated_background": translated_background,
                    }
                )
                continue
            fill_rgb = translated_background.get("dominant_rgb") or page_plan.get("background", {}).get("dominant_rgb")
            fill_color = _pdf_color_from_rgb(fill_rgb)
            text_color = _text_color_for_background(fill_color)
            rule_color = _blend_color(fill_color, text_color, 0.28)
            heading_bboxes = page_plan.get("heading_bboxes") or []
            heading_already_localized = _heading_already_localized(fitz, page, heading_bboxes)
            redaction_rects = _toc_redaction_rects(fitz, page, page_plan, include_heading=not heading_already_localized)
            for redaction_rect in redaction_rects or [region]:
                local_fill_rgb = _dominant_rgb_for_rect(fitz, page, redaction_rect, fallback=fill_rgb)
                page.add_redact_annot(redaction_rect, fill=_pdf_color_from_rgb(local_fill_rgb))
            page.apply_redactions()
            if heading_bboxes and not heading_already_localized:
                heading_rect = _rect_from_list(fitz, heading_bboxes[0])
                heading_rect = fitz.Rect(heading_rect.x0, heading_rect.y0 - 1, min(page.rect.x1 - 24, heading_rect.x1 + 32), heading_rect.y1 + 8)
                _fit_and_draw(
                    fitz,
                    page,
                    heading_rect,
                    "目录",
                    start_size=18.0 if page_plan.get("role") == "global_toc" else 13.0,
                    min_size=9.0,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=fitz.TEXT_ALIGN_LEFT,
                    color=text_color,
                )
            page_result = {
                "page": page_number,
                "status": "applied",
                "role": page_plan.get("role"),
                "source_background": page_plan.get("background"),
                "translated_background": translated_background,
                "fill_rgb": fill_rgb,
                "redaction_mode": "row_regions",
                "redaction_rect_count": len(redaction_rects),
                "heading_already_localized": heading_already_localized,
                "rows": [],
            }
            for row in page_plan.get("rows", []):
                role = "toc_entry" if page_plan.get("role") == "global_toc" else "chapter_index_entry"
                translated_title, method = translate_toc_title(row["source_title"], role)
                if method == "untranslated":
                    manifest["untranslated_title_count"] += 1
                rule_draw = _draw_row_rule(fitz, page, row, color=rule_color)
                title_rect = _rect_from_list(fitz, row["title_bbox"])
                num_rect = _rect_from_list(fitz, row["page_number_bbox"])
                title_rect = fitz.Rect(title_rect.x0, title_rect.y0 - 1, min(num_rect.x0 - 10, title_rect.x1 + 120), title_rect.y1 + 6)
                num_rect = fitz.Rect(max(num_rect.x0 - 28, title_rect.x1 + 4), num_rect.y0 - 1, num_rect.x1 + 2, num_rect.y1 + 6)
                start_size = float(row.get("source_font_size") or 9.0)
                title_draw = _fit_and_draw(
                    fitz,
                    page,
                    title_rect,
                    translated_title,
                    start_size=start_size,
                    min_size=6.5,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=fitz.TEXT_ALIGN_LEFT,
                    color=text_color,
                )
                page_draw = _fit_and_draw(
                    fitz,
                    page,
                    num_rect,
                    str(row["source_page_number"]),
                    start_size=start_size,
                    min_size=6.5,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=fitz.TEXT_ALIGN_RIGHT,
                    color=text_color,
                )
                page_result["rows"].append(
                    {
                        "row_index": row.get("row_index"),
                        "source_title": row.get("source_title"),
                        "translated_title": translated_title,
                        "source_page_number": row.get("source_page_number"),
                        "translation_method": method,
                        "row_rule_draw": rule_draw,
                        "title_draw": title_draw,
                        "page_number_draw": page_draw,
                    }
                )
                manifest["row_count"] += 1
            manifest["pages"].append(page_result)
            manifest["applied_page_count"] += 1
            applied_any = True
        if applied_any:
            doc.save(output_pdf, garbage=4, deflate=True)
            manifest["output_pdf"] = str(output_pdf)
            manifest["status"] = "applied_with_untranslated_titles" if manifest["untranslated_title_count"] else "applied"
        else:
            manifest["status"] = "skipped"
            manifest["reason"] = "no_safe_candidate_pages"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = repr(exc)
    finally:
        try:
            doc.close()  # type: ignore[name-defined]
        except Exception:
            pass
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
