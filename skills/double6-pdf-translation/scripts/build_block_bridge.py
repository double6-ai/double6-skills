#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip().lower()


def canonical_bridge_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalize_text(value))).strip()


def bridge_tokens(value: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "within",
        "report",
        "chapter",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", normalize_text(value))
        if (len(token) > 1 or re.search(r"[\u4e00-\u9fff]", token)) and token not in stopwords
    }


def block_text(block: dict[str, Any]) -> str:
    for key in ["text", "source_text", "input", "content", "raw_text"]:
        value = str(block.get(key) or "").strip()
        if value:
            return value
    return ""


def page_matches(source_page: Any, layout_page: Any) -> bool:
    if source_page is None or layout_page is None:
        return True
    return str(source_page) == str(layout_page)


def match_section_heading_block(
    source_block: dict[str, Any],
    layout_blocks: list[dict[str, Any]],
    used_layout_indexes: set[int],
    *,
    allow_used: bool = False,
) -> tuple[dict[str, Any], str, float]:
    source_text = canonical_bridge_text(block_text(source_block))
    if (
        str(source_block.get("element_type") or "") != "heading"
        or not source_text
        or len(source_text) > 48
    ):
        return {}, "unmatched", 0.0
    for index, layout in enumerate(layout_blocks):
        if not allow_used and index in used_layout_indexes:
            continue
        layout_role = str(layout.get("layout_role") or layout.get("layout_label") or "")
        if "heading" not in layout_role:
            continue
        layout_text = canonical_bridge_text(str(layout.get("source_text") or layout.get("input") or layout.get("pdf_unicode") or layout.get("text") or ""))
        if layout_text != source_text:
            continue
        if not allow_used:
            used_layout_indexes.add(index)
        method = "shared_section_heading_text_exact" if allow_used else "section_heading_text_exact"
        return layout, method, 1.0
    return {}, "unmatched", 0.0


def match_layout_block(
    source_block: dict[str, Any],
    layout_blocks: list[dict[str, Any]],
    used_layout_indexes: set[int],
    *,
    allow_used: bool = False,
) -> tuple[dict[str, Any], str, float]:
    source_id = str(source_block.get("block_id") or "")
    for index, layout in enumerate(layout_blocks):
        if not allow_used and index in used_layout_indexes:
            continue
        if source_id and str(layout.get("block_id") or "") == source_id:
            if not allow_used:
                used_layout_indexes.add(index)
            return layout, "block_id", 1.0

    source_norm = normalize_text(block_text(source_block))
    source_page = source_block.get("page")
    best_index: int | None = None
    best_score = 0.0
    for index, layout in enumerate(layout_blocks):
        if (not allow_used and index in used_layout_indexes) or not page_matches(source_page, layout.get("page")):
            continue
        layout_norm = normalize_text(
            str(layout.get("source_text") or layout.get("input") or layout.get("pdf_unicode") or layout.get("text") or "")
        )
        if not source_norm or not layout_norm:
            continue
        shorter = min(len(source_norm), len(layout_norm))
        source_canonical = canonical_bridge_text(source_norm)
        layout_canonical = canonical_bridge_text(layout_norm)
        if len(source_canonical) >= 32 and source_canonical in layout_canonical:
            score = 0.72
        elif shorter >= 24 and (source_norm[:shorter] in layout_norm or layout_norm[:shorter] in source_norm):
            score = 0.92
        elif source_norm in layout_norm or layout_norm in source_norm:
            coverage = shorter / max(len(source_norm), len(layout_norm), 1)
            score = 0.88 if coverage >= 0.45 else 0.0
        else:
            score = difflib.SequenceMatcher(None, source_norm[:600], layout_norm[:600]).ratio()
        if score > best_score:
            best_index = index
            best_score = score
    if best_index is not None and best_score >= 0.52:
        if not allow_used:
            used_layout_indexes.add(best_index)
        method = "shared_page_text_similarity" if allow_used else "page_text_similarity"
        return layout_blocks[best_index], method, round(best_score, 3)
    return {}, "unmatched", 0.0


def match_composite_layout_blocks(
    source_block: dict[str, Any],
    layout_blocks: list[dict[str, Any]],
    used_layout_indexes: set[int],
    *,
    allow_used: bool = False,
) -> tuple[dict[str, Any], str, float]:
    source_page = source_block.get("page")
    source_tokens = bridge_tokens(block_text(source_block))
    if len(source_tokens) < 6:
        return {}, "unmatched", 0.0

    candidates: list[tuple[int, dict[str, Any], set[str]]] = []
    for index, layout in enumerate(layout_blocks):
        if (not allow_used and index in used_layout_indexes) or not page_matches(source_page, layout.get("page")):
            continue
        layout_text = str(layout.get("source_text") or layout.get("input") or layout.get("pdf_unicode") or layout.get("text") or "")
        overlap = source_tokens & bridge_tokens(layout_text)
        if overlap:
            candidates.append((index, layout, overlap))
    candidates.sort(key=lambda item: len(item[2]), reverse=True)

    selected: list[tuple[int, dict[str, Any], set[str]]] = []
    covered: set[str] = set()
    for index, layout, overlap in candidates:
        new_tokens = overlap - covered
        if not new_tokens:
            continue
        selected.append((index, layout, overlap))
        covered.update(overlap)
        if len(covered) / max(len(source_tokens), 1) >= 0.85:
            break
    coverage = round(len(covered) / max(len(source_tokens), 1), 3)
    if len(selected) < 2 or coverage < 0.45:
        return {}, "unmatched", 0.0

    for index, _layout, _overlap in selected:
        if not allow_used:
            used_layout_indexes.add(index)
    selected_layouts = [layout for _index, layout, _overlap in selected]
    engine_ids = [str(item.get("engine_block_id") or item.get("block_id") or "") for item in selected_layouts if item.get("engine_block_id") or item.get("block_id")]
    debug_ids = [str(item.get("paragraph_debug_id") or "") for item in selected_layouts if item.get("paragraph_debug_id")]
    page = source_page if source_page is not None else selected_layouts[0].get("page")
    return (
        {
            "page": page,
            "layout_role": selected_layouts[0].get("layout_role") or selected_layouts[0].get("layout_label"),
            "reading_order": selected_layouts[0].get("reading_order"),
            "engine_block_id": engine_ids[0] if engine_ids else None,
            "engine_block_ids": engine_ids,
            "paragraph_debug_id": debug_ids[0] if debug_ids else None,
            "paragraph_debug_ids": debug_ids,
            "translated_block_id": f"composite:p{page}:{source_block.get('block_id') or 'source'}",
            "reanchor_status": "composite_engine_blocks_available",
            "backfill_status": "writeback_composite",
            "failure_stage": "unknown",
        },
        "shared_page_composite_text_coverage" if allow_used else "page_composite_text_coverage",
        coverage,
    )


def should_try_composite_first(source_block: dict[str, Any]) -> bool:
    text = block_text(source_block)
    return text.count("\n") >= 2 and len(bridge_tokens(text)) >= 8


def build_bridge(
    source_manifest: dict[str, Any],
    layout_map: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
    render_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_blocks = source_manifest.get("blocks") if isinstance(source_manifest.get("blocks"), list) else []
    layout_blocks = layout_map.get("blocks") if isinstance(layout_map.get("blocks"), list) else []
    layout_by_block = {
        str(item.get("block_id") or ""): item
        for item in layout_blocks
        if isinstance(item, dict) and item.get("block_id")
    }
    translation_by_block = {
        str(item.get("block_id") or ""): item
        for item in translation_blocks
        if isinstance(item, dict) and item.get("block_id")
    }
    has_engine_block_ids = any(
        isinstance(item, dict) and item.get("engine_block_id")
        for item in layout_blocks
    )
    mappings: list[dict[str, Any]] = []
    page_windows: dict[str, dict[str, Any]] = {}
    used_layout_indexes: set[int] = set()
    for order, block in enumerate(source_blocks, start=1):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or f"block-{order:04d}")
        layout = layout_by_block.get(block_id, {})
        match_method = "block_id" if layout else "unmatched"
        match_score = 1.0 if layout else 0.0
        if not layout and should_try_composite_first(block):
            layout, match_method, match_score = match_composite_layout_blocks(block, layout_blocks, used_layout_indexes)
        if not layout:
            layout, match_method, match_score = match_layout_block(block, layout_blocks, used_layout_indexes)
        if not layout:
            layout, match_method, match_score = match_composite_layout_blocks(block, layout_blocks, used_layout_indexes)
        if not layout and has_engine_block_ids:
            layout, match_method, match_score = match_layout_block(block, layout_blocks, used_layout_indexes, allow_used=True)
        if not layout and has_engine_block_ids:
            layout, match_method, match_score = match_section_heading_block(block, layout_blocks, used_layout_indexes, allow_used=True)
        if not layout and has_engine_block_ids:
            layout, match_method, match_score = match_composite_layout_blocks(block, layout_blocks, used_layout_indexes, allow_used=True)
        translation = translation_by_block.get(block_id, {})
        page = block.get("page")
        page_key = str(page if page is not None else layout.get("page", "global"))
        window = page_windows.setdefault(
            page_key,
            {
                "window_id": f"page-{page_key}",
                "pages": [page],
                "source_block_count": 0,
                "bridged_block_count": 0,
                "engine_block_count": 0,
                "missing_engine_block_ids": [],
            },
        )
        window["source_block_count"] += 1
        if layout:
            window["bridged_block_count"] += 1
        if layout.get("engine_block_id") or layout.get("engine_block_ids"):
            window["engine_block_count"] += 1
        else:
            window["missing_engine_block_ids"].append(block_id)
        mappings.append(
            {
                "source_block_id": block_id,
                "source_page": page,
                "source_section": block.get("section"),
                "source_element_type": block.get("element_type"),
                "layout_role": layout.get("layout_role") or block.get("layout_role") or block.get("element_type"),
                "bbox": layout.get("bbox") or block.get("bbox"),
                "placeholder_count": layout.get("placeholder_count"),
                "source_reading_order": order,
                "layout_reading_order": layout.get("reading_order"),
                "layout_page": layout.get("page"),
                "engine_block_id": layout.get("engine_block_id"),
                "engine_block_ids": layout.get("engine_block_ids"),
                "paragraph_debug_id": layout.get("paragraph_debug_id"),
                "paragraph_debug_ids": layout.get("paragraph_debug_ids"),
                "match_method": match_method,
                "match_score": match_score,
                "translated_block_id": layout.get("translated_block_id") or translation.get("block_id"),
                "bridge_status": (
                    "shared_engine_block"
                    if str(match_method).startswith("shared_") and (layout.get("engine_block_id") or layout.get("engine_block_ids"))
                    else "stable_engine_block"
                    if layout.get("engine_block_id")
                    else ("composite_engine_block" if layout.get("engine_block_ids") else "source_order_only")
                ),
                "translation_alignment_status": translation.get("alignment_status") or layout.get("backfill_status") or "unknown",
                "reanchor_status": layout.get("reanchor_status") or ("shared_engine_block_available" if str(match_method).startswith("shared_") and (layout.get("engine_block_id") or layout.get("engine_block_ids")) else ("engine_block_available" if layout.get("engine_block_id") else "engine_block_missing")),
                "failure_stage": layout.get("failure_stage") or ("layout" if not layout.get("engine_block_id") else "unknown"),
            }
        )
    engine_mapped = sum(1 for item in mappings if item.get("engine_block_id") or item.get("engine_block_ids"))
    engine_block_coverage_ratio = round(engine_mapped / max(len(mappings), 1), 3)
    tracking_available = layout_map.get("layout_source") in {"babeldoc_translate_tracking", "babeldoc_il_debug_json"} or has_engine_block_ids
    if has_engine_block_ids and engine_block_coverage_ratio >= 0.98:
        status = "ok"
    elif has_engine_block_ids or tracking_available:
        status = "partial"
    else:
        status = "order_only"
    if not mappings:
        status = "empty"
    window_items = []
    for item in page_windows.values():
        source_count = int(item.get("source_block_count") or 0)
        bridged_count = int(item.get("bridged_block_count") or 0)
        engine_count = int(item.get("engine_block_count") or 0)
        item["bridge_coverage_ratio"] = round(bridged_count / max(source_count, 1), 3)
        item["engine_block_coverage_ratio"] = round(engine_count / max(source_count, 1), 3)
        item["status"] = "ok" if item["bridge_coverage_ratio"] >= 1 and (has_engine_block_ids or item["engine_block_coverage_ratio"] == 0) else "warn"
        window_items.append(item)
    return {
        "version": 1,
        "status": status,
        "bridge_type": "stable_engine_block" if has_engine_block_ids else "source_layout_order_bridge",
        "source_input_type": source_manifest.get("input_type"),
        "source_override": source_manifest.get("source_override"),
        "render_engine": (render_manifest or {}).get("engine"),
        "primary_pdf": ((render_manifest or {}).get("outputs") or {}).get("translated_pdf"),
        "mapping_count": len(mappings),
        "engine_block_coverage_ratio": engine_block_coverage_ratio,
        "stable_engine_block_count": engine_mapped,
        "unmatched_source_block_count": sum(1 for item in mappings if item.get("match_method") == "unmatched"),
        "unmatched_engine_block_count": max(0, len(layout_blocks) - len(used_layout_indexes)),
        "mappings": mappings,
        "page_windows": sorted(window_items, key=lambda item: str(item.get("window_id"))),
        "coverage_interpretation": {
            "block_id_missing_is_coverage_failure": bool(has_engine_block_ids),
            "note": (
                "PDFMathTranslate-next/BabelDOC 当前未暴露稳定 block id 时，只能用 page/order 级桥接；"
                "不要把 Markdown/LaTeX source block id 未出现在 PDF 可复制文本记录中直接判为正文漏译。"
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a source-to-PDF block bridge for paper-translation artifacts.")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--layout-map", required=True)
    parser.add_argument("--translation-blocks", required=True)
    parser.add_argument("--render-manifest")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bridge = build_bridge(
        load_json(Path(args.source_manifest)),
        load_json(Path(args.layout_map)),
        load_jsonl(Path(args.translation_blocks)),
        load_json(Path(args.render_manifest)) if args.render_manifest else {},
    )
    output_path = Path(args.output)
    output_path.write_text(json.dumps(bridge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "status": bridge["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
