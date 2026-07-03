#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by visual_layout.py and visual layout modules for shared text, bbox, and page-role helpers."

import json
import re
from pathlib import Path
from typing import Any


VISIBLE_LATEX_COMMAND_RE = re.compile(r"\\(?:section|subsection|subsubsection|begin|end|cite|ref|url|texttt|emph|caption)\b")


def _load_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception:
        try:
            import pymupdf as fitz  # type: ignore

            return fitz
        except Exception as exc:  # noqa: BLE001 - optional dependency failure is reported in QA manifests
            raise RuntimeError(f"PyMuPDF unavailable: {exc}") from exc


def normalize_lines(text: str) -> list[str]:
    text = text.replace("\x03", " ")
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def ascii_word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z-]{1,}\b", text))


def extract_key_texts(source_pages: list[dict[str, Any]], limit: int = 12) -> list[str]:
    keys: list[str] = []
    for page in source_pages[:3]:
        text = str(page.get("text") or "")
        for year in re.findall(r"\b20\d{2}\b", text):
            if year not in keys:
                keys.append(year)
        for line in normalize_lines(text):
            if 8 <= len(line) <= 80 and (line.istitle() or line.isupper()):
                if line not in keys:
                    keys.append(line)
            if len(keys) >= limit:
                return keys
    return keys


def dominant_color_ratio(page: dict[str, Any], color: int) -> float:
    spans = page.get("spans")
    spans = spans if isinstance(spans, list) else []
    if not spans:
        return 0.0
    matches = sum(1 for span in spans if isinstance(span, dict) and int(span.get("color") or 0) == color)
    return matches / len(spans)


def nonblack_color_ratio(page: dict[str, Any]) -> float:
    spans = page.get("spans")
    spans = spans if isinstance(spans, list) else []
    if not spans:
        return 0.0
    matches = sum(1 for span in spans if isinstance(span, dict) and int(span.get("color") or 0) != 0)
    return matches / len(spans)


def bbox_overlap_ratio(box_a: list[float], box_b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax1, bx1)
    y1 = min(ay1, by1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = max((ax1 - ax0) * (ay1 - ay0), 1.0)
    area_b = max((bx1 - bx0) * (by1 - by0), 1.0)
    return inter / min(area_a, area_b)


def bbox_overlap_area(box_a: list[float], box_b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax1, bx1)
    y1 = min(ay1, by1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return round((x1 - x0) * (y1 - y0), 3)


def is_code_placeholder_span_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if stripped in {"...", "…"}:
        return True
    if VISIBLE_LATEX_COMMAND_RE.search(stripped):
        return True
    if re.fullmatch(r"\\[A-Za-z@]+\*?(?:\{[^{}]*\})?", stripped):
        return True
    return False


def should_ignore_overlap_pair(span_a: dict[str, Any], span_b: dict[str, Any]) -> bool:
    text_a = re.sub(r"\s+", " ", str(span_a.get("text") or "")).strip()
    text_b = re.sub(r"\s+", " ", str(span_b.get("text") or "")).strip()
    if is_code_placeholder_span_text(text_a) and is_code_placeholder_span_text(text_b):
        return True
    # Visual repair can repaint a short section heading over a stale text layer.
    # The text layer then contains overlapping identical heading spans, but the
    # visible page is not a paragraph collision.
    if text_a == text_b and len(text_a) <= 24 and HEADING_TEXT_RE.fullmatch(text_a):
        return True
    return False


def count_overlapping_spans(page: dict[str, Any], threshold: float = 0.55) -> int:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    count = 0
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) == 4 and bbox_overlap_ratio(box_a, box_b) >= threshold and not should_ignore_overlap_pair(span, other):
                count += 1
                break
    return count


def total_overlapping_area(page: dict[str, Any], threshold: float = 0.55) -> float:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    total = 0.0
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) == 4 and bbox_overlap_ratio(box_a, box_b) >= threshold and not should_ignore_overlap_pair(span, other):
                total += bbox_overlap_area(box_a, box_b)
    return round(total, 3)


def overlap_pair_samples(page: dict[str, Any], threshold: float = 0.55, limit: int = 12) -> list[dict[str, Any]]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    pairs: list[dict[str, Any]] = []
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) != 4:
                continue
            ratio = bbox_overlap_ratio(box_a, box_b)
            if ratio >= threshold and not should_ignore_overlap_pair(span, other):
                pairs.append(
                    {
                        "text_a": str(span.get("text") or "")[:80],
                        "text_b": str(other.get("text") or "")[:80],
                        "bbox_a": box_a,
                        "bbox_b": box_b,
                        "overlap_ratio": round(ratio, 3),
                        "overlap_area": bbox_overlap_area(box_a, box_b),
                    }
                )
                if len(pairs) >= limit:
                    return pairs
    return pairs


def infer_failure_stage(rule: str, category: str, message: str = "") -> str:
    value = " ".join([rule, category, message]).lower()
    if any(token in value for token in ["extract", "text_layer", "glyph", "tounicode", "ocr"]):
        return "parse"
    if any(token in value for token in ["reading_order", "toc", "role", "header", "footer", "caption", "section_heading"]):
        return "layout"
    if any(token in value for token in ["untranslated", "translated", "terminology", "example", "references_body"]):
        return "translate"
    if any(token in value for token in ["overlap", "bbox", "tiny_font", "page_count", "drift", "reflow"]):
        return "typeset"
    if any(token in value for token in ["color", "contrast", "font"]):
        return "paint"
    if any(token in value for token in ["dual", "left", "right", "composite"]):
        return "composite"
    return "unknown"


def infer_layout_role(rule: str, message: str = "") -> str:
    value = " ".join([rule, message]).lower()
    if "table" in value or "chart" in value:
        return "table_or_chart"
    if "formula" in value or "latex" in value:
        return "formula_or_tex"
    if "caption" in value:
        return "caption"
    if "foot" in value or "affiliation" in value or "email" in value:
        return "footnote_or_footer"
    if "header" in value:
        return "header"
    if "reference" in value:
        return "references"
    if "title" in value or "heading" in value:
        return "heading"
    if "example" in value or "st/" in value or "ht/" in value:
        return "example_or_parallel_text"
    return "main_text"


def infer_cause_category(rule: str, message: str = "", failure_stage: str = "") -> str:
    value = " ".join([rule, message, failure_stage]).lower()
    if any(
        token in value
        for token in [
            "person_name",
            "citation",
            "running_header",
            "signature",
            "references",
            "example",
            "st/",
            "ht/",
            "llm",
            "chart_title",
            "role",
        ]
    ):
        return "backend_role_classification"
    if any(token in value for token in ["tiny_font", "font_size", "overflow", "wrap", "line_break", "reflow", "bbox", "overlap"]):
        return "typeset_reflow"
    if any(
        token in value
        for token in [
            "image",
            "background",
            "portrait",
            "avatar",
            "rule_line",
            "underline",
            "link",
            "annotation",
            "color",
            "paint",
            "composite",
            "right_page",
            "dual",
        ]
    ):
        return "paint_composite"
    if any(token in value for token in ["artifact", "manifest", "report", "stale", "cached", "delivery_pdf", "source_of_truth"]):
        return "artifact_selection_report_drift"
    if failure_stage == "translate":
        return "backend_role_classification"
    if failure_stage == "typeset":
        return "typeset_reflow"
    if failure_stage in {"paint", "composite"}:
        return "paint_composite"
    return "needs_local_verification"


def infer_user_feedback_layout_role(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ["人名", "姓名", "citation", "引用", "作者"]):
        return "citation_or_person_names"
    if any(token in value for token in ["图表标题", "图题", "figure", "chart title"]):
        return "chart_title"
    if any(token in value for token in ["图像", "图片", "头像", "背景"]):
        return "background_or_image"
    if any(token in value for token in ["链接", "下划线", "uri", "url"]):
        return "link_or_annotation"
    if any(token in value for token in ["页眉", "header"]):
        return "running_header"
    if any(token in value for token in ["页脚", "脚注", "横线", "footer", "footnote"]):
        return "footnote_or_footer"
    if any(token in value for token in ["署名", "签名", "co-chair", "主席"]):
        return "signature"
    if any(token in value for token in ["目录", "contents", "toc"]):
        return "toc_or_chapter_index"
    if any(token in value for token in ["字体", "字号", "加粗", "颜色", "换行", "溢出"]):
        return "body_or_heading_text"
    return "main_text"


def normalize_user_visual_feedback(text: str, *, default_page: int | str = "global") -> dict[str, Any]:
    page_match = re.search(r"第\s*(\d+)\s*页|p(?:age)?\.?\s*(\d+)", text, flags=re.I)
    page: int | str = int(next(group for group in page_match.groups() if group)) if page_match else default_page
    layout_role = infer_user_feedback_layout_role(text)
    if layout_role in {"citation_or_person_names", "signature", "running_header", "chart_title"}:
        cause_category = "backend_role_classification"
    elif layout_role in {"background_or_image", "link_or_annotation", "footnote_or_footer"}:
        cause_category = "paint_composite"
    elif any(token in text for token in ["字号", "字体", "换行", "溢出", "加粗"]):
        cause_category = "typeset_reflow"
    elif any(token in text.lower() for token in ["manifest", "artifact", "报告", "旧候选", "最终交付"]):
        cause_category = "artifact_selection_report_drift"
    else:
        cause_category = "needs_local_verification"
    repair_target = {
        "backend_role_classification": "layout_role_policy / backend tracking / visible repair rule",
        "typeset_reflow": "BabelDOC typesetting / paragraph reflow / visible candidate bbox",
        "paint_composite": "PDF paint/composite / annotations / source region copy",
        "artifact_selection_report_drift": "artifact index / render manifest / report source-of-truth",
        "needs_local_verification": "screenshot + PyMuPDF local audit",
    }[cause_category]
    return {
        "version": 1,
        "page": page,
        "region": None,
        "layout_role": layout_role,
        "symptom": text,
        "expected": "与源 PDF 对应区域的结构、字体、颜色、图层和 protected text policy 保持一致。",
        "cause_category": cause_category,
        "repair_target": repair_target,
        "verification": ["source_vs_candidate_screenshot", "pymupdf_text_bbox_font_color", "manifest_rule_check"],
    }


def normalize_finding(finding: dict[str, Any] | str, default_page: int | str = "global") -> dict[str, Any]:
    if isinstance(finding, str):
        item: dict[str, Any] = {"rule": "visual_layout_note", "message": finding}
    else:
        item = dict(finding)
    rule = str(item.get("rule") or item.get("category") or "visual_layout_issue")
    severity = str(item.get("severity") or "")
    if severity in {"high", "critical"}:
        severity = "blocking"
    elif severity in {"medium", "low"}:
        severity = "warn" if severity == "medium" else "cosmetic"
    if not severity:
        severity = "blocking" if rule in {"text_overlap", "page_count_drift", "key_text_missing"} else "warn"
    item["severity"] = severity
    item["layer"] = item.get("layer") or "pdf_rendering"
    item["page"] = item.get("page") or default_page
    category = str(item.get("category") or "")
    message = str(item.get("message") or item.get("evidence") or "")
    item["failure_stage"] = item.get("failure_stage") or infer_failure_stage(rule, category, message)
    item["layout_role"] = item.get("layout_role") or infer_layout_role(rule, message)
    item["cause_category"] = item.get("cause_category") or infer_cause_category(rule, message, str(item["failure_stage"]))
    item["repair_target"] = item.get("repair_target") or {
        "parse": "PDF text extraction / OCR / ToUnicode layer",
        "layout": "LayoutParser / ParagraphFinder / role classification",
        "translate": "layout_role_policy / translator prompt / protected passthrough",
        "typeset": "BabelDOC Typesetting / paragraph split / bbox fit",
        "paint": "FontMapper / color / contrast",
        "composite": "bilingual composer / final PDF assembly",
        "unknown": "manual triage",
    }.get(str(item["failure_stage"]), "manual triage")
    item["evidence"] = item.get("evidence") or item.get("message") or json.dumps({k: v for k, v in item.items() if k not in {"evidence", "recommendation"}}, ensure_ascii=False)
    item["recommendation"] = item.get("recommendation") or {
        "key_text_missing": "对照源页截图确认标题或关键年份是否被遮挡；必要时重渲染该页。",
        "color_palette_shift_to_black": "检查中文字体和颜色映射；必要时切换字体或回退为可读版 PDF。",
        "text_overlap": "重渲染该页并降低字号或调整段落 bbox 拆分。",
        "toc_line_count_dropped": "重新检查目录块顺序和页码行，必要时局部重渲染目录页。",
        "toc_page_number_count_dropped": "重新检查目录页右侧页码列是否被合并或丢失，必要时局部重渲染目录页。",
        "toc_numeric_order_unstable": "重新检查目录页阅读顺序和页码对齐。",
        "toc_alignment_drift": "重新检查目录页章节标题和页码列的左右对齐关系，必要时局部重渲染目录页。",
        "font_size_regression": "禁止通过过度缩小字号把译文硬塞回原 bbox；需重排段落或降低文本密度。",
        "header_footer_fragmented": "页眉页脚、邮箱或机构脚注应保护或整体处理，避免碎片化翻译。",
        "page_count_drift": "确认源译 PDF 页数是否漂移；漂移时不应判定渲染通过。",
    }.get(rule, "复核该视觉 finding 对应页，并决定局部重渲染或可读降级交付。")
    return item


def has_toc_heading(lines: list[str]) -> bool:
    joined = "\n".join(lines[:40]).lower()
    return bool(re.search(r"\b(contents|table of contents)\b|目录", joined))


def looks_like_chapter_highlights_page(lines: list[str]) -> bool:
    joined = "\n".join(lines[:40]).lower()
    return bool(re.search(r"\bchapter\s+highlights\b|章节要点", joined))


def looks_like_toc_page(lines: list[str]) -> bool:
    if not lines:
        return False
    if has_toc_heading(lines):
        return True
    if looks_like_chapter_highlights_page(lines):
        return False
    numbered_lines = [line for line in lines if re.search(r"\b\d{1,3}\b", line)]
    if len(numbered_lines) < 6:
        return False
    toc_markers = 0
    for line in numbered_lines:
        if re.search(r"\.{2,}\s*\d{1,3}\s*$", line):
            toc_markers += 1
        elif re.search(r"\s\d{1,3}\s*$", line) and len(line) <= 90:
            toc_markers += 1
    page_numbers = toc_page_numbers(lines, include_standalone=False)
    return (
        toc_markers >= 4
        and toc_markers / max(len(numbered_lines), 1) >= 0.45
        and len(page_numbers) >= 4
        and page_numbers == sorted(page_numbers)
    )


def numeric_toc_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if re.search(r"\b\d{1,3}\b", line)]


def toc_page_numbers(lines: list[str], *, include_standalone: bool = True) -> list[int]:
    numbers: list[int] = []
    for line in lines:
        compact = line.strip()
        if include_standalone and re.fullmatch(r"\d{1,3}", compact):
            numbers.append(int(compact))
            continue
        if re.fullmatch(r"(?i)chapter\s+\d{1,3}", compact):
            continue
        match = re.search(r"(?:\.{2,}|\s)(\d{1,3})\s*$", compact)
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def parse_page_selection(selection: str | None) -> list[int] | None:
    if selection is None:
        return None
    raw = str(selection).strip()
    if not raw or raw.lower() == "auto":
        return None
    pages: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start_raw, end_raw = item.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            if start <= 0 or end <= 0 or end < start:
                raise ValueError(f"invalid page range: {item}")
            pages.extend(range(start, end + 1))
        else:
            page = int(item)
            if page <= 0:
                raise ValueError(f"invalid page number: {item}")
            pages.append(page)
    deduped: list[int] = []
    seen: set[int] = set()
    for page in pages:
        if page not in seen:
            deduped.append(page)
            seen.add(page)
    return deduped


def directory_order_findings(source_page: dict[str, Any], translated_page: dict[str, Any]) -> list[dict[str, Any]]:
    source_lines = normalize_lines(str(source_page.get("text") or ""))
    translated_lines = normalize_lines(str(translated_page.get("text") or ""))
    if looks_like_chapter_highlights_page(source_lines) or looks_like_chapter_highlights_page(translated_lines):
        return []
    if not looks_like_toc_page(source_lines) and not looks_like_toc_page(translated_lines):
        return []
    source_numbers = numeric_toc_lines(source_lines)
    translated_numbers = numeric_toc_lines(translated_lines)
    source_page_numbers = toc_page_numbers(source_lines)
    translated_page_numbers = toc_page_numbers(translated_lines)
    evidence = {
        "source_numeric_line_count": len(source_numbers),
        "translated_numeric_line_count": len(translated_numbers),
        "toc_line_preservation_ratio": round(len(translated_numbers) / max(len(source_numbers), 1), 3),
        "source_page_number_count": len(source_page_numbers),
        "translated_page_number_count": len(translated_page_numbers),
        "source_page_number_samples": source_page_numbers[:12],
        "translated_page_number_samples": translated_page_numbers[:12],
        "source_numeric_line_samples": source_numbers[:8],
        "translated_numeric_line_samples": translated_numbers[:8],
    }
    if len(source_numbers) >= 4 and len(translated_numbers) < max(2, len(source_numbers) // 2):
        return [{"rule": "toc_line_count_dropped", **evidence}, {"rule": "toc_alignment_drift", **evidence}]
    if (
        len(source_page_numbers) >= 4
        and len(translated_page_numbers) < max(2, len(source_page_numbers) // 2)
    ):
        return [{"rule": "toc_page_number_count_dropped", **evidence}, {"rule": "toc_alignment_drift", **evidence}]
    if len(translated_page_numbers) >= 3 and translated_page_numbers != sorted(translated_page_numbers):
        return [{"rule": "toc_numeric_order_unstable", **evidence}, {"rule": "toc_alignment_drift", **evidence}]
    return []


def directory_order_warnings(source_page: dict[str, Any], translated_page: dict[str, Any]) -> list[str]:
    return [item["rule"] for item in directory_order_findings(source_page, translated_page)]


def _local_bbox_center(span: dict[str, Any]) -> tuple[float, float] | None:
    bbox = span.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return ((float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0)
    except (TypeError, ValueError):
        return None


def has_near_acceptable_duplicate_span(
    text: str,
    small_span: dict[str, Any],
    spans: list[dict[str, Any]],
    threshold: float,
) -> bool:
    small_center = _local_bbox_center(small_span)
    if small_center is None:
        return False
    for candidate in spans:
        if candidate is small_span:
            continue
        candidate_text = re.sub(r"\s+", " ", str(candidate.get("text") or "")).strip()
        if candidate_text != text or float(candidate.get("size") or 0) < threshold:
            continue
        candidate_center = _local_bbox_center(candidate)
        if candidate_center is None:
            continue
        if abs(candidate_center[0] - small_center[0]) <= 45 and abs(candidate_center[1] - small_center[1]) <= 10:
            return True
    return False


def is_allowed_compact_label(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "@" in stripped or "://" in stripped or stripped.lower().startswith(("doi", "http")):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?%?", stripped):
        return True
    if re.fullmatch(r"[A-Za-z0-9_.%+-]+\.[A-Za-z]{2,}(?:\.[A-Za-z]{2,})?", stripped):
        return True
    if re.fullmatch(r"(?:AI|ML|NLP|GPU|CPU|API|LLM|GPT|R&D|EU|US|UK|OECD|UN|GDP|STEM)", stripped):
        return True
    if re.fullmatch(r"(?:OpenAI|GPT|ChatGPT)\s+o?\d+[A-Za-z]*", stripped):
        return True
    return False


def is_neutral_compact_label(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if re.fullmatch(r"[A-Z][A-Za-z'’.-]{1,24}", stripped):
        return True
    if re.search(r"\bvs\.?\b", stripped, re.IGNORECASE) and re.search(
        r"\b(?:HT|MT|NMT|LLM|GPT|AI)\b",
        stripped,
        re.IGNORECASE,
    ):
        return True
    return False


def small_font_stats(page: dict[str, Any], threshold: float = 6.0) -> dict[str, Any]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict)]
    small = []
    ignored = []
    for span in spans:
        text = str(span.get("text") or "").strip()
        if not (
            isinstance(span.get("size"), (int, float))
            and float(span.get("size") or 0) > 0
            and float(span.get("size") or 0) < threshold
            and text
        ):
            continue
        if (
            text == "\x03"
            or re.fullmatch(r"\d{1,3}", text)
            or is_allowed_compact_label(text)
            or is_neutral_compact_label(text)
            or has_near_acceptable_duplicate_span(text, span, spans, threshold)
        ):
            ignored.append(span)
        else:
            small.append(span)
    total_chars = sum(len(str(span.get("text") or "")) for span in spans)
    small_chars = sum(len(str(span.get("text") or "")) for span in small)
    return {
        "threshold": threshold,
        "span_count": len(spans),
        "small_font_span_count": len(small),
        "ignored_small_font_span_count": len(ignored),
        "small_font_char_ratio": round(small_chars / max(total_chars, 1), 3),
        "small_font_samples": [str(span.get("text") or "")[:40] for span in small[:8]],
        "ignored_small_font_samples": [str(span.get("text") or "")[:40] for span in ignored[:8]],
    }


HEADING_TEXT_RE = re.compile(
    r"^(?:摘要|引言|文献综述|方法|结果|讨论|结论|参考文献|目录|贡献者|概览|章节要点|"
    r"数据可用性|注释|致谢|作者贡献|利益冲突|伦理批准|知情同意|附加信息|"
    r"第一章|第二章|第三章|第四章|第五章|第六章|第七章|研究与开发|技术性能|负责任的人工智能|经济|科学|医学|教育|"
    r"Abstract|Introduction|Literature Review|Methods?|Results?|Discussion|Conclusions?|References|Contents|"
    r"Data availability|Notes|Acknowledgements|Author contributions|Competing interests|Ethics approval|Informed consent|Additional information|"
    r"Contributors|Overview|Chapter Highlights|Chapter\s+\d+|Research and Development|Technical Performance|Responsible AI|Economy|Science|Medicine|Education)$",
    re.I,
)


def tiny_heading_spans(page: dict[str, Any], threshold: float = 6.0) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    spans = page.get("spans", []) if isinstance(page.get("spans"), list) else []
    for span in spans:
        if not isinstance(span, dict):
            continue
        text = re.sub(r"\s+", " ", str(span.get("text") or "")).strip()
        size = float(span.get("size") or 0)
        if text and 0 < size < threshold and HEADING_TEXT_RE.fullmatch(text):
            if has_near_acceptable_duplicate_span(text, span, spans, threshold):
                continue
            samples.append({"text": text, "size": round(size, 2), "bbox": span.get("bbox")})
    return samples


HEADING_TRANSLATION_PAIRS = {
    "abstract": "摘要",
    "introduction": "引言",
    "literature review": "文献综述",
    "methods": "方法",
    "method": "方法",
    "results": "结果",
    "result": "结果",
    "discussion": "讨论",
    "conclusion": "结论",
    "conclusions": "结论",
    "references": "参考文献",
    "chapter 1": "第一章",
    "chapter 2": "第二章",
    "chapter 3": "第三章",
    "chapter 4": "第四章",
    "chapter 5": "第五章",
    "chapter 6": "第六章",
    "chapter 7": "第七章",
    "research and development": "研究与开发",
    "technical performance": "技术性能",
    "responsible ai": "负责任的人工智能",
    "economy": "经济",
    "science": "科学",
    "medicine": "医学",
    "education": "教育",
}

LATIN_PERSON_NAME_RE = re.compile(r"^(?:[A-Z][A-Za-z'’.-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'’.-]+|[A-Z]\.)){1,4}$")
LATIN_NAME_EXCLUDE_WORDS = {
    "chapter",
    "research",
    "development",
    "introduction",
    "science",
    "medicine",
    "education",
    "economy",
    "responsible",
    "technical",
    "performance",
    "public",
    "opinion",
    "policy",
    "governance",
    "ai",
    "index",
    "report",
    "contributors",
    "the",
    "of",
    "and",
    "by",
    "national",
    "affiliation",
    "sector",
    "organization",
    "geographic",
    "distribution",
    "north",
    "south",
    "east",
    "west",
    "central",
    "latin",
    "america",
    "australia",
    "brazil",
    "canada",
    "denmark",
    "europe",
    "finland",
    "france",
    "germany",
    "india",
    "israel",
    "italy",
    "japan",
    "netherlands",
    "asia",
    "africa",
    "middle",
    "united",
    "states",
    "kingdom",
    "arab",
    "emirates",
    "saudi",
    "arabia",
    "singapore",
    "spain",
    "sweden",
    "switzerland",
    "korea",
    "zeki",
    "data",
    "using",
}
LATIN_PERSON_NAME_EXCLUDE_PHRASES = {
    "Geographic Distribution",
    "North America",
    "Latin America",
    "United States",
    "United Kingdom",
    "United Arab",
    "United Arab Emirates",
    "Arab Emirates",
    "Saudi Arabia",
    "South Korea",
    "Australia",
    "Brazil",
    "Canada",
    "Denmark",
    "Finland",
    "France",
    "Germany",
    "India",
    "Israel",
    "Italy",
    "Japan",
    "Netherlands",
    "Singapore",
    "Spain",
    "Sweden",
    "Switzerland",
    "Zeki Data",
    "Using Zeki",
}

CHART_TITLE_TRANSLATION_REQUIREMENTS = {
    "by sector and organization": ["部门", "组织"],
    "by national affiliation": ["国家", "地区"],
}

NATURE_PUBLISHER_BADGE_REGION = [465.0, 112.0, 575.0, 165.0]
