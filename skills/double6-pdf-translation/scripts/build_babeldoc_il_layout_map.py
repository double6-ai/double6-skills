#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def iter_tracking_paragraphs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_name in ["page", "cross_page", "cross_column"]:
        groups = payload.get(group_name)
        if not isinstance(groups, list):
            continue
        for page_index, group in enumerate(groups, start=1):
            paragraphs = group.get("paragraph") if isinstance(group, dict) else None
            if not isinstance(paragraphs, list):
                continue
            for paragraph in paragraphs:
                if not isinstance(paragraph, dict):
                    continue
                row = dict(paragraph)
                row.setdefault("tracking_group", group_name)
                if row.get("page") is None and group_name == "page":
                    row["page"] = page_index
                rows.append(row)
    return rows


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip().lower()


def infer_inline_toc_page_number(toc_row_group: dict[str, Any] | None, *, role: str | None = None) -> dict[str, Any] | None:
    if not isinstance(toc_row_group, dict):
        return toc_row_group
    if toc_row_group.get("page_number") and toc_row_group.get("page_number_bbox"):
        return toc_row_group
    if str(role or "").lower() not in {"toc_entry", "chapter_index_entry"}:
        return toc_row_group

    title_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(toc_row_group.get("title_text") or ""))).strip()
    match = re.search(r"(?:^|\s)(\d{1,3})$", title_text)
    if not match:
        return toc_row_group

    row_bbox = toc_row_group.get("row_bbox") if isinstance(toc_row_group.get("row_bbox"), dict) else None
    title_bbox = toc_row_group.get("title_bbox") if isinstance(toc_row_group.get("title_bbox"), dict) else None
    bbox_source = row_bbox or title_bbox
    if not bbox_source:
        return {**toc_row_group, "page_number": match.group(1), "page_number_source": "inline_title_text"}

    try:
        x2 = float(bbox_source["x2"])
        y = float(bbox_source["y"])
        y2 = float(bbox_source["y2"])
    except (KeyError, TypeError, ValueError):
        return {**toc_row_group, "page_number": match.group(1), "page_number_source": "inline_title_text"}

    width = max(10.0, min(28.0, 5.8 * len(match.group(1)) + 4.0))
    page_bbox = {
        "x": round(x2 - width, 3),
        "y": y,
        "x2": x2,
        "y2": y2,
        "source": "inline_title_text",
    }
    updated = dict(toc_row_group)
    updated["page_number"] = match.group(1)
    updated["page_number_bbox"] = page_bbox
    updated["page_number_source"] = "inline_title_text"
    if title_bbox and not toc_row_group.get("page_number_bbox"):
        adjusted_title = dict(title_bbox)
        try:
            adjusted_title["x2"] = min(float(adjusted_title["x2"]), page_bbox["x"] - 2.0)
            updated["title_bbox"] = adjusted_title
            updated["title_bbox_source"] = "inline_title_text_without_page_number"
        except (KeyError, TypeError, ValueError):
            pass
    return updated


def tracker_has_fallback(paragraph: dict[str, Any]) -> bool:
    trackers = paragraph.get("llm_translate_trackers")
    if not isinstance(trackers, list):
        return False
    return any(isinstance(item, dict) and item.get("fallback_to_translate") for item in trackers)


def fallback_status(paragraph: dict[str, Any]) -> str:
    source = str(paragraph.get("input") or paragraph.get("pdf_unicode") or "").strip()
    output = str(paragraph.get("output") or "").strip()
    if tracker_has_fallback(paragraph):
        return "fallback_to_translate"
    if source and output and normalize_text(source) == normalize_text(output):
        return "same_as_input"
    if re.search(r"[\u4e00-\u9fff]", output) and re.search(r"[A-Za-z]{3,}", output):
        return "mixed_or_partial_output"
    return "translated_or_passthrough"


def build_engine_block_id(row: dict[str, Any], order: int) -> str:
    page = row.get("page")
    debug_id = row.get("debug_id") or row.get("paragraph_debug_id")
    layout_id = row.get("layout_id")
    group = row.get("tracking_group") or "tracking"
    if debug_id:
        return f"{group}:p{page}:debug:{debug_id}"
    if layout_id:
        return f"{group}:p{page}:layout:{layout_id}"
    return f"{group}:p{page}:order:{order:04d}"


def paragraph_to_block(row: dict[str, Any], order: int) -> dict[str, Any]:
    source = str(row.get("input") or row.get("pdf_unicode") or "")
    output = str(row.get("output") or "")
    debug_id = row.get("debug_id") or row.get("paragraph_debug_id")
    layout_label = row.get("layout_label") or row.get("layout_role")
    engine_block_id = build_engine_block_id(row, order)
    toc_row_group = None
    if row.get("toc_row_group_json"):
        try:
            toc_row_group = json.loads(str(row.get("toc_row_group_json")))
        except json.JSONDecodeError:
            toc_row_group = {"parse_error": True, "raw": str(row.get("toc_row_group_json"))[:500]}
    toc_row_group = infer_inline_toc_page_number(toc_row_group, role=row.get("layout_role") or layout_label)
    block = {
        "block_id": engine_block_id,
        "engine_block_id": engine_block_id,
        "paragraph_debug_id": debug_id,
        "page": row.get("page"),
        "layout_label": layout_label,
        "layout_role": row.get("layout_role") or layout_label,
        "layout_id": row.get("layout_id"),
        "bbox": row.get("bbox") or row.get("box"),
        "render_order": row.get("render_order"),
        "reading_order": order,
        "tracking_group": row.get("tracking_group"),
        "input": source,
        "source_text": source,
        "output": output,
        "translated_text": output,
        "pdf_unicode": row.get("pdf_unicode"),
        "normalized_source_text": normalize_text(source)[:500],
        "normalized_output_text": normalize_text(output)[:500],
        "writeback_status": row.get("writeback_status"),
        "writeback_reason": row.get("writeback_reason"),
        "fallback_status": fallback_status(row),
        "placeholder_count": len(row.get("placeholders", [])) if isinstance(row.get("placeholders"), list) else None,
        "translated_block_id": engine_block_id,
        "reanchor_status": "engine_block_available",
        "backfill_status": "writeback_" + str(row.get("writeback_status") or "unknown"),
        "failure_stage": "paint" if row.get("writeback_status") == "rejected" else "unknown",
    }
    if toc_row_group:
        block["toc_row_group"] = toc_row_group
        block["title_bbox"] = toc_row_group.get("title_bbox")
        block["page_number_bbox"] = toc_row_group.get("page_number_bbox")
        block["page_number"] = toc_row_group.get("page_number")
    return block


def build_babeldoc_il_layout_map(
    tracking_payload: dict[str, Any],
    *,
    tracking_path: str | None = None,
    translated_pdf: str | None = None,
) -> dict[str, Any]:
    paragraphs = iter_tracking_paragraphs(tracking_payload)
    blocks = [paragraph_to_block(row, index) for index, row in enumerate(paragraphs, start=1)]
    with_label = [item for item in blocks if item.get("layout_label") or item.get("layout_role")]
    fallback_blocks = [
        item
        for item in blocks
        if item.get("fallback_status") in {"fallback_to_translate", "same_as_input", "mixed_or_partial_output"}
    ]
    coverage_denominator = max(len(blocks), 1)
    return {
        "version": 1,
        "status": "ok" if blocks else "unavailable",
        "layout_source": "babeldoc_translate_tracking",
        "tracking_path": tracking_path,
        "translated_pdf": translated_pdf,
        "engine": "pdfmathtranslate-next",
        "block_count": len(blocks),
        "engine_block_coverage_ratio": 1.0 if blocks else 0.0,
        "layout_label_coverage": round(len(with_label) / coverage_denominator, 3),
        "fallback_line_ratio": round(len(fallback_blocks) / coverage_denominator, 3),
        "fallback_line_count": len(fallback_blocks),
        "layout_source_candidates": [
            {
                "source": "babeldoc_translate_tracking",
                "status": "ok" if blocks else "missing",
                "path": tracking_path,
                "block_count": len(blocks),
            }
        ],
        "blocks": blocks,
        "notes": [
            "本文件把 BabelDOC translate_tracking 外显为 paper-translation 可消费的结构证据。",
            "若后续可保留完整 BabelDOC IL/debug JSON，应在同一 schema 中补齐 bbox、layout_id 和 render_order。",
        ],
    }


def build_from_file(tracking_path: Path, *, translated_pdf: str | None = None) -> dict[str, Any]:
    return build_babeldoc_il_layout_map(
        load_json(tracking_path),
        tracking_path=str(tracking_path),
        translated_pdf=translated_pdf,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build BabelDOC IL-style layout map from translate_tracking.json.")
    parser.add_argument("--tracking", required=True)
    parser.add_argument("--translated-pdf")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_from_file(Path(args.tracking), translated_pdf=args.translated_pdf)
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": payload.get("status")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
