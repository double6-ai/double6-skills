# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout structure：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

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
    from visual_layout_core import normalize_lines
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

def small_font_stats(page: dict[str, Any], threshold: float = 6.0) -> dict[str, Any]:
    from visual_layout_density import is_allowed_compact_label, is_neutral_compact_label
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

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
