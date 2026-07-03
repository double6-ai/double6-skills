#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TABLE_HEADER_TRANSLATIONS: dict[str, str] = {
    "Sub-corpus": "子语料库",
    "Number of texts": "文本数量",
    "Tokens": "词数",
    "Mean length": "平均长度",
}


def toc_row_requires_page_number_group(block: dict[str, Any]) -> bool:
    role = str(block.get("layout_role") or block.get("layout_label") or "").lower()
    if role not in {"toc_entry", "chapter_index_entry"}:
        return False
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(block.get("input") or block.get("source_text") or block.get("pdf_unicode") or ""))).strip()
    if not text:
        return False
    if re.fullmatch(r"chapter\s+\d{1,2}", text, flags=re.I):
        return False
    if role == "chapter_index_entry" and not re.search(r"\s\d{1,3}$", text):
        return False
    return bool(re.search(r"\s\d{1,3}$", text))


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def toc_rows_from_layout(layout_map: dict[str, Any]) -> dict[str, Any]:
    blocks = layout_map.get("blocks") if isinstance(layout_map.get("blocks"), list) else []
    rows: list[dict[str, Any]] = []
    unpaired_page_numbers: list[dict[str, Any]] = []
    missing_groups: list[dict[str, Any]] = []
    writeback_failures: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        role = str(block.get("layout_role") or block.get("layout_label") or "").lower()
        if role == "toc_page_number":
            unpaired_page_numbers.append(block)
            continue
        if role not in {"toc_entry", "chapter_index_entry"}:
            continue
        group = block.get("toc_row_group") if isinstance(block.get("toc_row_group"), dict) else None
        row_id = (group or {}).get("row_id") or block.get("paragraph_debug_id") or block.get("engine_block_id") or block.get("block_id")
        title_bbox = block.get("title_bbox") or (group or {}).get("title_bbox")
        page_number_bbox = block.get("page_number_bbox") or (group or {}).get("page_number_bbox")
        page_number = (group or {}).get("page_number")
        if toc_row_requires_page_number_group(block) and (not group or not row_id or not title_bbox or not page_number or not page_number_bbox):
            missing_groups.append(block)
        if str(block.get("writeback_status") or "").lower() == "structured_toc_writeback_failed":
            writeback_failures.append(block)
        rows.append(
            {
                "page": block.get("page"),
                "row_id": row_id,
                "engine_block_id": block.get("engine_block_id") or block.get("block_id"),
                "paragraph_debug_id": block.get("paragraph_debug_id"),
                "role": role,
                "source_text": block.get("source_text") or block.get("input"),
                "translated_text": block.get("translated_text") or block.get("output"),
                "title_bbox": title_bbox,
                "page_number_bbox": page_number_bbox,
                "page_number": page_number,
                "writeback_status": block.get("writeback_status"),
            }
        )
    status = "partial" if missing_groups or unpaired_page_numbers or writeback_failures else "ok"
    return {
        "version": 1,
        "status": status,
        "row_count": len(rows),
        "missing_row_group_count": len(missing_groups),
        "unpaired_page_number_count": len(unpaired_page_numbers),
        "structured_toc_writeback_failed_count": len(writeback_failures),
        "rows": rows,
        "missing_row_groups": missing_groups[:20],
        "unpaired_page_numbers": unpaired_page_numbers[:20],
        "writeback_failures": writeback_failures[:20],
    }


def metadata_yband_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    footer_in_header = audit.get("footer_in_header_band") if isinstance(audit.get("footer_in_header_band"), list) else []
    mismatch = audit.get("metadata_yband_mismatch") if isinstance(audit.get("metadata_yband_mismatch"), list) else []
    def normalize_entry(item: Any) -> dict[str, Any]:
        row = item if isinstance(item, dict) else {}
        actual_bbox = row.get("actual_bbox") or row.get("translated_bbox") or row.get("bbox")
        return {
            **row,
            "expected_bbox": row.get("expected_bbox") or row.get("source_bbox"),
            "actual_bbox": actual_bbox,
            "source_band": row.get("source_band") or "footer",
            "target_band": row.get("target_band") or row.get("actual_band"),
            "expected_band": row.get("expected_band") or "footer",
            "actual_band": row.get("actual_band") or row.get("target_band"),
        }

    footer_in_header_rows = [normalize_entry(item) for item in footer_in_header]
    mismatch_rows = [normalize_entry(item) for item in mismatch]
    return {
        "version": 1,
        "status": "partial" if footer_in_header or mismatch else "ok",
        "footer_in_header_band_count": len(footer_in_header),
        "metadata_yband_mismatch_count": len(mismatch),
        "footer_in_header_band": footer_in_header_rows,
        "metadata_yband_mismatch": mismatch_rows,
    }


def table_region_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    findings = audit.get("visible_text_not_tracked") if isinstance(audit.get("visible_text_not_tracked"), list) else []
    synthetic_headers: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        if str(item.get("layout_role") or "").lower() != "table_header":
            continue
        source = str(item.get("text") or "").strip()
        target = TABLE_HEADER_TRANSLATIONS.get(source)
        if not target:
            continue
        synthetic_headers.append(
            {
                "page": item.get("page"),
                "source_text": source,
                "target_text": target,
                "bbox": item.get("bbox"),
                "layout_role": "table_header",
                "failure_stage": "paragraph_finder",
                "repair_target": "synthetic_table_header_item_or_table_region_rerender",
                "source_rule": item.get("rule") or "visible_text_not_tracked",
            }
        )
    return {
        "version": 1,
        "status": "partial" if synthetic_headers else "ok",
        "synthetic_table_header_candidate_count": len(synthetic_headers),
        "synthetic_table_header_candidates": synthetic_headers[:20],
    }


def build_structured_writeback_manifest(layout_map: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    toc = toc_rows_from_layout(layout_map)
    metadata = metadata_yband_from_audit(audit)
    table_region = table_region_from_audit(audit)
    blockers: list[dict[str, Any]] = []
    if toc["missing_row_group_count"]:
        blockers.append({"rule": "toc_row_group_missing", "count": toc["missing_row_group_count"], "repair_target": "babeldoc_structured_toc_writeback"})
    if toc["unpaired_page_number_count"]:
        blockers.append({"rule": "toc_page_number_column_unpaired", "count": toc["unpaired_page_number_count"], "repair_target": "babeldoc_structured_toc_writeback"})
    if toc["structured_toc_writeback_failed_count"]:
        blockers.append({"rule": "structured_toc_writeback_failed", "count": toc["structured_toc_writeback_failed_count"], "repair_target": "babeldoc_structured_toc_writeback"})
    if metadata["footer_in_header_band_count"]:
        blockers.append({"rule": "footer_in_header_band", "count": metadata["footer_in_header_band_count"], "repair_target": "metadata_yband_role_paint"})
    if metadata["metadata_yband_mismatch_count"]:
        blockers.append({"rule": "metadata_yband_mismatch", "count": metadata["metadata_yband_mismatch_count"], "repair_target": "metadata_yband_role_paint"})
    if table_region["synthetic_table_header_candidate_count"]:
        blockers.append(
            {
                "rule": "synthetic_table_header_candidate_required",
                "count": table_region["synthetic_table_header_candidate_count"],
                "repair_target": "synthetic_table_header_item_or_table_region_rerender",
            }
        )
    return {
        "version": 1,
        "status": "partial" if blockers else "ok",
        "visual_overlay_policy": "disabled_for_toc_metadata_and_table_headers",
        "repair_layers": {
            "toc": "babeldoc_structured_toc_writeback",
            "metadata": "metadata_yband_role_paint",
            "table_region": "synthetic_table_header_item_or_table_region_rerender",
        },
        "blockers": blockers,
        "toc_row_map": toc,
        "metadata_yband_audit": metadata,
        "table_region_map": table_region,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Round41 structured writeback diagnostics.")
    parser.add_argument("--layout-map", required=True)
    parser.add_argument("--pymupdf-audit", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_structured_writeback_manifest(
        load_json(Path(args.layout_map)),
        load_json(Path(args.pymupdf_audit)),
    )
    write_json(output_dir / "toc_row_map.json", manifest["toc_row_map"])
    write_json(output_dir / "metadata_yband_audit.json", manifest["metadata_yband_audit"])
    write_json(output_dir / "table_region_map.json", manifest["table_region_map"])
    write_json(output_dir / "structured_writeback_manifest.json", manifest)
    print(json.dumps({"output_dir": str(output_dir), "status": manifest["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
