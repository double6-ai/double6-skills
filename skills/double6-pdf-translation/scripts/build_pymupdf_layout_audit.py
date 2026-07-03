#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import build_babeldoc_il_layout_map
import visual_layout


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip().lower()


def compact_tracking_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalize_text(value))


def tracking_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalize_text(value))
        if len(token) > 1 or re.search(r"[\u4e00-\u9fff]", token)
    ]


def extract_pdf_spans(path: Path | None, *, max_pages: int | None = None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    fitz = visual_layout._load_fitz()
    rows: list[dict[str, Any]] = []
    with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
        for page_index, page in enumerate(doc):
            if max_pages is not None and page_index >= max_pages:
                break
            page_height = float(page.rect.height)
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if not isinstance(block, dict):
                    continue
                for line_index, line in enumerate(block.get("lines", []) or []):
                    if not isinstance(line, dict):
                        continue
                    line_text_parts: list[str] = []
                    for span_index, span in enumerate(line.get("spans", []) or []):
                        if not isinstance(span, dict):
                            continue
                        text = str(span.get("text") or "")
                        if text.strip():
                            line_text_parts.append(text)
                        rows.append(
                            {
                                "page": page_index + 1,
                                "block_index": block.get("number"),
                                "line_index": line_index,
                                "span_index": span_index,
                                "text": text,
                                "normalized_text": normalize_text(text),
                                "bbox": span.get("bbox"),
                                "font": span.get("font"),
                                "size": span.get("size"),
                                "color": span.get("color"),
                                "flags": span.get("flags"),
                                "page_height": page_height,
                            }
                        )
                    if line_text_parts:
                        rows.append(
                            {
                                "page": page_index + 1,
                                "block_index": block.get("number"),
                                "line_index": line_index,
                                "span_index": None,
                                "text": "".join(line_text_parts),
                                "normalized_text": normalize_text("".join(line_text_parts)),
                                "bbox": line.get("bbox"),
                                "font": None,
                                "size": None,
                                "color": None,
                                "flags": None,
                                "row_type": "line",
                                "page_height": page_height,
                            }
                        )
    return rows


def tracking_text_blob(tracking_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for row in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        for key in ["input", "output", "pdf_unicode"]:
            value = normalize_text(str(row.get(key) or ""))
            if value:
                chunks.append(value)
    return "\n".join(chunks)


def text_is_covered_by_tracking(normalized: str, tracking_chunks: list[str]) -> bool:
    if normalized in "\n".join(tracking_chunks):
        return True
    if len(normalized) >= 20 and any(normalized[:20] in chunk or chunk[:20] in normalized for chunk in tracking_chunks):
        return True

    compact = compact_tracking_key(normalized)
    if len(compact) >= 20:
        for chunk in tracking_chunks:
            chunk_compact = compact_tracking_key(chunk)
            if not chunk_compact:
                continue
            if compact in chunk_compact or chunk_compact in compact:
                return True

    source_tokens = set(tracking_tokens(normalized))
    if len(source_tokens) >= 6:
        for chunk in tracking_chunks:
            chunk_tokens = set(tracking_tokens(chunk))
            if len(chunk_tokens) < 6:
                continue
            overlap = len(source_tokens & chunk_tokens)
            if overlap >= 6 and overlap / max(len(source_tokens), 1) >= 0.6:
                return True
    return False


def is_meaningful_visible_text(text: str) -> bool:
    if len(text) < 4:
        return False
    if re.fullmatch(r"[\d\s.,:;()%/\-]+", text):
        return False
    if re.fullmatch(r"https?://\S+|\S+@\S+", text, flags=re.I):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]{3,}", text))


def visible_line_role(text: str) -> str:
    normalized = normalize_text(text)
    if normalized in {"sub-corpus", "number of texts", "tokens", "mean length"}:
        return "table_header"
    if re.search(r"\b(?:number of notable ai models|notable ai models \(% of total\)|by national affiliation|by sector and organization)\b", normalized, re.I):
        return "chart_label"
    if re.search(r"\b(?:stanford university|sri international|information sciences institute|northeastern|minnesota)\b", normalized, re.I):
        return "institution_label"
    if re.search(r"\b(?:doi\.org|humanities and social sciences|email:|@)\b", normalized, re.I):
        return "metadata_or_footer"
    return "unknown_visible_line"


def is_ai_index_policy_passthrough_visible_line(text: str, page: int | None) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    normalized = normalize_text(stripped)
    if not stripped:
        return False
    page_number = int(page or 0)
    if page_number in {5, 6}:
        if re.search(r"\b(?:LEAD AND EDITOR-IN-CHIEF|RESEARCH MANAGER|AFFILIATED RESEARCHERS|UNDERGRADUATE|GRADUATE)\b", stripped):
            return True
        if re.search(r"\b(?:Stanford University|IMT School|Advanced Studies Lucca|Northeastern|Minnesota|Washington)\b", stripped):
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}", stripped):
            return True
    if page_number in {8, 9}:
        if stripped in {"McKinsey & Company", "Quid", "Lightcast", "Zeki", "LinkedIn", "Epoch AI", "GitHub"}:
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5}(?:,\s*[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,4})*", stripped):
            return True
    if page_number in {11, 12, 18, 19, 20} and re.search(
        r"\b(?:TO P TA K E AWAY S|A I I N D E X R E P O R T|N OTA B L E A I M O D E L S|R E S E A R C H A N D D E V E LO P M E N T)\b",
        stripped,
    ):
        return True
    if page_number == 11 and re.fullmatch(r"\d{1,2}\s+estimated", normalized):
        return True
    if page_number == 14 and re.search(
        r"\b1\.[1-8]\s+(?:notable ai ?models|compute ?and infrastructure|data centers|energy and environmental impact|open-source ai software|publications|patents|ai authors and inventors)\b",
        normalized,
    ):
        return True
    if page_number in {17, 18, 19, 20}:
        if re.fullmatch(r"(?:Canada|France|Hong Kong|Singapore|United Kingdom)\s+\d+", stripped):
            return True
        if re.fullmatch(r"Figure\s+1\.1\.\d+\s*\d?", stripped):
            return True
        if re.search(r"\b(?:Epoch AI|AI Index 2026|DeepMind|OpenAI|Google|Alibaba|Anthropic|xAI|LG AI Research|Meta|Tsinghua University|ByteDance|Moonshot|Nvidia|University of Illinois|Z\.ai|Zhipu AI|MiniMax|Shanghai AI Lab|Allen Institute for AI|Ai2|Ant Group|Baidu|CUHK Shenzhen Research Institute)\b", stripped):
            return True
        if normalized in {"nonpro t", "nonprofit", "industry", "academia"} or re.fullmatch(r"nonpro.t", normalized):
            return True
        if re.search(r"\b(?:notable ai models|models \(% of total\)|national affiliation|sector and organization)\b", normalized):
            return True
    return False


def is_ai_index_policy_passthrough_source_visible(text: str, page: int | None) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    page_number = int(page or 0)
    if page_number == 4 and re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+(?:and\s+)?[A-Z][A-Za-z'’.-]+){2,5}", stripped):
        return True
    if page_number in {8, 9} and re.search(r"\b(?:Loredana Fattorini|Yolanda Gil|Vanessa Parli|Ray(?:mond)? Perrault|Sha Sajadieh)\b", stripped):
        return True
    return False


def is_nature_policy_passthrough_source_visible(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    normalized = normalize_text(stripped)
    if re.search(r"\bhumanities and social sciences communications\b", normalized) and "doi.org/10.1057/s41599-026-06630-4" in normalized:
        return True
    return False


def visible_text_not_tracked(source_spans: list[dict[str, Any]], tracking_payload: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    blob = tracking_text_blob(tracking_payload)
    tracking_chunks = blob.splitlines()
    findings: list[dict[str, Any]] = []
    for row in source_spans:
        if row.get("row_type") != "line":
            continue
        normalized = str(row.get("normalized_text") or "")
        if not is_meaningful_visible_text(normalized):
            continue
        if is_ai_index_policy_passthrough_visible_line(str(row.get("text") or ""), row.get("page")):
            continue
        if text_is_covered_by_tracking(normalized, tracking_chunks):
            continue
        findings.append(
            {
                "page": row.get("page"),
                "text": str(row.get("text") or "")[:240],
                "bbox": row.get("bbox"),
                "rule": "visible_text_not_tracked",
                "failure_stage": "paragraph_finder",
                "layout_role": visible_line_role(str(row.get("text") or "")),
            }
        )
        if len(findings) >= limit:
            break
    return findings


def tracking_translated_but_source_visible(
    translated_spans: list[dict[str, Any]],
    tracking_payload: dict[str, Any],
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    visible_lines = [row for row in translated_spans if row.get("row_type") == "line" and is_meaningful_visible_text(str(row.get("normalized_text") or ""))]
    findings: list[dict[str, Any]] = []
    for tracked in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        source = str(tracked.get("input") or tracked.get("pdf_unicode") or "")
        output = str(tracked.get("output") or "")
        source_norm = normalize_text(source)
        tracked_page = tracked.get("page")
        engine_id = str(tracked.get("engine_block_id") or tracked.get("block_id") or "")
        layout_role = tracked.get("layout_role") or tracked.get("layout_label") or visible_line_role(source)
        min_source_length = 20 if str(layout_role).lower() in {"chart_label", "axis", "axis_label", "fallback_line", "table_header"} else 40
        if len(source_norm) < min_source_length or not re.search(r"[\u4e00-\u9fff]", output):
            continue
        if normalize_text(output) == source_norm:
            continue
        for line in visible_lines:
            if not pages_compatible_for_tracking(tracked_page, line.get("page"), engine_id):
                continue
            line_norm = str(line.get("normalized_text") or "")
            min_line_length = 20 if str(layout_role).lower() in {"chart_label", "axis", "axis_label", "fallback_line", "table_header"} else 30
            if len(line_norm) < min_line_length:
                continue
            visible_text = str(line.get("text") or "")
            if is_ai_index_policy_passthrough_source_visible(visible_text, line.get("page")):
                continue
            if is_nature_policy_passthrough_source_visible(visible_text):
                continue
            line_anchor = line_norm[: min(60, len(line_norm))]
            source_anchor = source_norm[: min(60, len(source_norm))]
            token_overlap = len(set(line_norm.split()[:12]) & set(source_norm.split()[:18]))
            if line_norm in source_norm or source_norm.startswith(line_anchor[:40]) or source_anchor in line_norm or token_overlap >= 5:
                rule = (
                    "chart_axis_original_text_visible"
                    if str(layout_role).lower() in {"chart_label", "axis", "axis_label", "fallback_line"}
                    else "tracking_translated_but_source_visible"
                )
                findings.append(
                    {
                        "page": line.get("page"),
                        "paragraph_debug_id": tracked.get("debug_id") or tracked.get("paragraph_debug_id"),
                        "layout_role": layout_role,
                        "visible_text": str(line.get("text") or "")[:240],
                        "tracking_output": output[:240],
                        "bbox": line.get("bbox"),
                        "rule": rule,
                        "failure_stage": "paint",
                    }
                )
                break
        if len(findings) >= limit:
            break
    return findings


def pages_compatible_for_tracking(tracked_page: Any, visible_page: Any, engine_id: str = "") -> bool:
    if tracked_page in (None, "") or visible_page in (None, ""):
        return True
    try:
        tracked = int(tracked_page)
        visible = int(visible_page)
    except (TypeError, ValueError):
        return str(tracked_page) == str(visible_page)
    if tracked == visible:
        return True
    return engine_id.startswith("cross_page:") and visible in {tracked - 1, tracked + 1}


def _first_line_matching(spans: list[dict[str, Any]], pattern: str, *, page: int | None = None) -> dict[str, Any] | None:
    for row in spans:
        if row.get("row_type") != "line":
            continue
        if page is not None and int(row.get("page") or 0) != page:
            continue
        text = str(row.get("text") or "")
        normalized = normalize_text(text)
        if re.search(pattern, text, re.I) or re.search(pattern, normalized, re.I):
            return row
    return None


def _bbox_center(row: dict[str, Any]) -> tuple[float, float] | None:
    bbox = row.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def cover_year_position_findings(
    source_spans: list[dict[str, Any]],
    translated_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_year = _first_line_matching(source_spans, r"^(?:20\d{2}|2\s+0\s+2\s+6)$", page=1)
    if not source_year:
        return []
    translated_year = _first_line_matching(translated_spans, r"^(?:20\d{2}|2\s+0\s+2\s+6)$", page=1)
    if not translated_year:
        return [
            {
                "page": 1,
                "rule": "cover_year_missing_from_translation",
                "failure_stage": "typesetting",
                "source_bbox": source_year.get("bbox"),
                "source_text": source_year.get("text"),
            }
        ]
    source_center = _bbox_center(source_year)
    translated_center = _bbox_center(translated_year)
    if not source_center or not translated_center:
        return []
    dx = abs(source_center[0] - translated_center[0])
    dy = abs(source_center[1] - translated_center[1])
    if dx > 80 or dy > 40:
        return [
            {
                "page": 1,
                "rule": "cover_year_position_drift",
                "failure_stage": "typesetting",
                "source_text": source_year.get("text"),
                "translated_text": translated_year.get("text"),
                "source_bbox": source_year.get("bbox"),
                "translated_bbox": translated_year.get("bbox"),
                "delta": {"x": round(dx, 2), "y": round(dy, 2)},
            }
        ]
    return []


def numbered_list_merge_findings(
    source_spans: list[dict[str, Any]],
    translated_spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_items = [
        row
        for row in source_spans
        if row.get("row_type") == "line" and re.match(r"^\s*[1-9][.)]\s+", str(row.get("text") or ""))
    ]
    if len(source_items) < 2:
        return []
    findings: list[dict[str, Any]] = []
    for row in translated_spans:
        if row.get("row_type") != "line":
            continue
        text = str(row.get("text") or "")
        markers = re.findall(r"(?:^|\s)([1-9][.)])\s+", text)
        if len(set(markers)) >= 2:
            findings.append(
                {
                    "page": row.get("page"),
                    "rule": "numbered_list_merge",
                    "failure_stage": "paragraph_finder",
                    "visible_text": text[:240],
                    "bbox": row.get("bbox"),
                }
            )
            break
    return findings


def _metadata_footer_signal(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(
        re.search(r"(?:doi\.org|s41599|humanities and social sciences|www\.nature\.com|email:|@)", normalized, re.I)
    )


BACKMATTER_EN_MARKERS = (
    "Acknowledgements",
    "Author contributions",
    "Competing interests",
    "Ethics approval",
    "Informed consent",
    "Additional information",
    "Supplementary information",
    "Correspondence and requests for materials",
    "Reprints and permission information",
    "Publisher's note",
    "Publisher’s note",
    "This research was supported",
    "The authors declare no competing interests",
    "did not require ethical approval",
    "informed consent was therefore not required",
)


BACKMATTER_CJK_MARKERS = (
    "致谢",
    "作者贡献",
    "利益冲突",
    "伦理批准",
    "知情同意",
    "附加信息",
    "补充信息",
    "通讯及材料请求",
    "转载与授权",
    "出版方声明",
    "不存在利益冲突",
    "无需伦理",
    "无需取得知情同意",
)


def backmatter_visibility_summary(translated_spans: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        str(row.get("text") or "")
        for row in translated_spans
        if row.get("row_type") == "line" and int(row.get("page") or 0) >= 10
    ]
    visible_text = "\n".join(lines)
    english_visible = [marker for marker in BACKMATTER_EN_MARKERS if re.search(re.escape(marker), visible_text, re.I)]
    cjk_visible = [marker for marker in BACKMATTER_CJK_MARKERS if marker in visible_text]
    if english_visible and cjk_visible:
        status = "mixed"
    elif english_visible:
        status = "english_visible"
    elif len(cjk_visible) >= 3:
        status = "translated_visible"
    else:
        status = "unknown"
    return {
        "status": status,
        "english_marker_count": len(english_visible),
        "cjk_marker_count": len(cjk_visible),
        "english_markers": english_visible,
        "cjk_markers": cjk_visible,
    }


def _line_y_band(row: dict[str, Any]) -> str | None:
    bbox = row.get("bbox")
    page_height = float(row.get("page_height") or 0)
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4 or page_height <= 0:
        return None
    try:
        y1 = float(bbox[1])
        y2 = float(bbox[3])
    except (TypeError, ValueError):
        return None
    if y2 <= page_height * 0.22:
        return "header"
    if y1 >= page_height * 0.78:
        return "footer"
    return "body"


def _metadata_text_similarity(left: str, right: str) -> float:
    left_tokens = set(tracking_tokens(left))
    right_tokens = set(tracking_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    jaccard = overlap / max(len(left_tokens | right_tokens), 1)
    coverage = overlap / max(min(len(left_tokens), len(right_tokens)), 1)
    left_compact = compact_tracking_key(left)
    right_compact = compact_tracking_key(right)
    substring_bonus = 0.0
    if len(left_compact) >= 16 and len(right_compact) >= 16:
        if left_compact in right_compact or right_compact in left_compact:
            substring_bonus = 0.35
    return max(jaccard, coverage * 0.75, substring_bonus)


def _best_metadata_source_match(row: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    row_text = str(row.get("text") or "")
    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in candidates:
        score = _metadata_text_similarity(row_text, str(candidate.get("text") or ""))
        if score > best_score:
            best = candidate
            best_score = score
    return best, best_score


def metadata_yband_findings(
    source_spans: list[dict[str, Any]],
    translated_spans: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_metadata = [
        row
        for row in source_spans
        if row.get("row_type") == "line" and _metadata_footer_signal(str(row.get("text") or ""))
    ]
    source_footer_metadata = [
        row
        for row in source_metadata
        if _line_y_band(row) == "footer"
    ]
    if not source_footer_metadata:
        return [], []
    footer_in_header: list[dict[str, Any]] = []
    yband_mismatch: list[dict[str, Any]] = []
    for row in translated_spans:
        if row.get("row_type") != "line" or not _metadata_footer_signal(str(row.get("text") or "")):
            continue
        band = _line_y_band(row)
        same_page_metadata = [item for item in source_metadata if item.get("page") == row.get("page")]
        same_band_metadata = [item for item in same_page_metadata if _line_y_band(item) == band]
        same_band_row, same_band_score = _best_metadata_source_match(row, same_band_metadata)
        if same_band_row and same_band_score >= 0.45:
            continue

        same_page_footer = [item for item in source_footer_metadata if item.get("page") == row.get("page")]
        source_row, source_score = _best_metadata_source_match(row, same_page_footer or source_footer_metadata)
        if source_row is None or source_score < 0.45:
            continue
        source_band = _line_y_band(source_row)
        base_evidence = {
            "source_text": str(source_row.get("text") or "")[:240],
            "source_bbox": source_row.get("bbox"),
            "source_band": source_band,
            "match_score": round(source_score, 3),
            "expected_bbox": source_row.get("bbox"),
            "expected_band": "footer",
            "visible_text": str(row.get("text") or "")[:240],
            "translated_bbox": row.get("bbox"),
            "actual_bbox": row.get("bbox"),
            "actual_band": band,
            "page_height": row.get("page_height"),
        }
        if band == "header":
            footer_in_header.append(
                {
                    "page": row.get("page"),
                    "rule": "footer_in_header_band",
                    "failure_stage": "paint",
                    **base_evidence,
                }
            )
        if band and band != "footer":
            yband_mismatch.append(
                {
                    "page": row.get("page"),
                    "rule": "metadata_yband_mismatch",
                    "failure_stage": "paint",
                    **base_evidence,
                }
            )
    return footer_in_header[:20], yband_mismatch[:20]


def line_order_signature(spans: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    signature: list[tuple[int, int, str]] = []
    for row in spans:
        if row.get("row_type") != "line":
            continue
        normalized = str(row.get("normalized_text") or "")
        if is_meaningful_visible_text(normalized):
            signature.append((int(row.get("page") or 0), int(row.get("line_index") or 0), normalized[:40]))
    return signature


def build_pymupdf_layout_audit(
    *,
    source_pdf: Path | None = None,
    translated_pdf: Path | None = None,
    tracking_payload: dict[str, Any] | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    try:
        source_spans = extract_pdf_spans(source_pdf, max_pages=max_pages)
        translated_spans = extract_pdf_spans(translated_pdf, max_pages=max_pages)
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"pymupdf_audit_unavailable: {exc}", "findings": []}
    tracking = tracking_payload if isinstance(tracking_payload, dict) else {}
    visible_missing = visible_text_not_tracked(source_spans, tracking) if tracking else []
    visible_source_after_translation = tracking_translated_but_source_visible(translated_spans, tracking) if tracking else []
    cover_year_position = cover_year_position_findings(source_spans, translated_spans)
    numbered_list_merge = numbered_list_merge_findings(source_spans, translated_spans)
    footer_in_header, metadata_yband_mismatch = metadata_yband_findings(source_spans, translated_spans)
    backmatter_visibility = backmatter_visibility_summary(translated_spans)
    source_lines = line_order_signature(source_spans)
    tracked_lines = [
        normalize_text(str(row.get("input") or row.get("pdf_unicode") or ""))[:40]
        for row in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking)
        if normalize_text(str(row.get("input") or row.get("pdf_unicode") or ""))
    ]
    reading_order_risk = bool(source_lines and tracked_lines and len(visible_missing) / max(len(source_lines), 1) > 0.18)
    cross_block_merge_risk = any(len(str(row.get("text") or "")) > 500 for row in source_spans if row.get("row_type") == "line")
    findings = [
        {
            "severity": "warn",
            "category": "layout_mapping",
            "rule": "visible_text_not_tracked",
            "failure_stage": "paragraph_finder",
            "message": "源 PDF 可见文本未进入 BabelDOC tracking，后续翻译/写回链路无法修复该文本。",
            "samples": visible_missing[:10],
        }
    ] if visible_missing else []
    if visible_source_after_translation:
        findings.append(
            {
                "severity": "blocking",
                "category": "pdf_rendering",
                "rule": "tracking_translated_but_source_visible",
                "failure_stage": "paint",
                "message": "BabelDOC tracking 中已有中文输出，但译文 PDF 仍可见对应英文源文，说明写回/清除原文本失败。",
                "samples": visible_source_after_translation[:10],
            }
        )
        chart_axis_samples = [item for item in visible_source_after_translation if item.get("rule") == "chart_axis_original_text_visible"]
        if chart_axis_samples:
            findings.append(
                {
                    "severity": "blocking",
                    "category": "pdf_rendering",
                    "rule": "chart_axis_original_text_visible",
                    "failure_stage": "paint",
                    "message": "旋转/竖排图表轴标签已有中文输出，但译文 PDF 仍可见英文源标签，需 region rerender 或修复原 glyph 替换。",
                    "samples": chart_axis_samples[:10],
                }
            )
    if reading_order_risk:
        findings.append(
            {
                "severity": "warn",
                "category": "layout_mapping",
                "rule": "reading_order_risk",
                "failure_stage": "paragraph_finder",
                "message": "PyMuPDF 可见行与 BabelDOC tracking 差异较大，需复核阅读顺序或段落构造。",
            }
        )
    if cross_block_merge_risk:
        findings.append(
            {
                "severity": "warn",
                "category": "layout_mapping",
                "rule": "cross_block_merge_risk",
                "failure_stage": "paragraph_finder",
                "message": "存在异常长可见行，可能由跨块合并或目录/表格行串联导致。",
            }
        )
    if cover_year_position:
        findings.append(
            {
                "severity": "blocking",
                "category": "pdf_rendering",
                "rule": cover_year_position[0].get("rule") or "cover_year_position_drift",
                "failure_stage": "typesetting",
                "message": "AI Index 封面年份必须作为独立 cover_year item 保持原 bbox/位置，不能并入标题或漂移。",
                "samples": cover_year_position[:10],
            }
        )
    if numbered_list_merge:
        findings.append(
            {
                "severity": "blocking",
                "category": "layout_mapping",
                "rule": "numbered_list_merge",
                "failure_stage": "paragraph_finder",
                "message": "源 PDF 多个有序列表项在译后文本层合并为一行，需按编号拆成独立 paragraph。",
                "samples": numbered_list_merge[:10],
            }
        )
    if footer_in_header:
        findings.append(
            {
                "severity": "blocking",
                "category": "pdf_rendering",
                "rule": "footer_in_header_band",
                "failure_stage": "paint",
                "message": "源页脚 metadata 在译后进入页眉 band，修复点是 BabelDOC y-band role 与 XObject paint。",
                "samples": footer_in_header[:10],
            }
        )
    if metadata_yband_mismatch:
        findings.append(
            {
                "severity": "blocking",
                "category": "pdf_rendering",
                "rule": "metadata_yband_mismatch",
                "failure_stage": "paint",
                "message": "metadata 源/译 y-band 不一致，不能用后处理遮盖修复。",
                "samples": metadata_yband_mismatch[:10],
            }
        )
    has_blocking = any(item.get("severity") == "blocking" for item in findings)
    return {
        "version": 1,
        "status": "partial" if has_blocking else "warn" if findings else "ok",
        "source_pdf": str(source_pdf) if source_pdf else None,
        "translated_pdf": str(translated_pdf) if translated_pdf else None,
        "source_span_count": len(source_spans),
        "translated_span_count": len(translated_spans),
        "tracked_paragraph_count": len(build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking)),
        "visible_text_not_tracked_count": len(visible_missing),
        "tracking_translated_but_source_visible_count": len(visible_source_after_translation),
        "cover_year_position_issue_count": len(cover_year_position),
        "numbered_list_merge_count": len(numbered_list_merge),
        "footer_in_header_band_count": len(footer_in_header),
        "metadata_yband_mismatch_count": len(metadata_yband_mismatch),
        "backmatter_visibility": backmatter_visibility,
        "reading_order_risk": reading_order_risk,
        "cross_block_merge_risk": cross_block_merge_risk,
        "findings": findings,
        "visible_text_not_tracked": visible_missing,
        "tracking_translated_but_source_visible": visible_source_after_translation,
        "cover_year_position_issues": cover_year_position,
        "numbered_list_merge": numbered_list_merge,
        "footer_in_header_band": footer_in_header,
        "metadata_yband_mismatch": metadata_yband_mismatch,
        "source_spans": source_spans[:1000],
        "translated_spans": translated_spans[:1000],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a PyMuPDF side-channel layout audit.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf")
    parser.add_argument("--tracking")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_pymupdf_layout_audit(
        source_pdf=Path(args.source_pdf),
        translated_pdf=Path(args.translated_pdf) if args.translated_pdf else None,
        tracking_payload=build_babeldoc_il_layout_map.load_json(Path(args.tracking)) if args.tracking else {},
        max_pages=args.max_pages,
    )
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": payload.get("status")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
