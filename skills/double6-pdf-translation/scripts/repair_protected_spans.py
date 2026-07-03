#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


STRICT_KINDS = {"url", "doi", "citation", "inline_math", "latex_command", "inline_code", "code_block"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_translation_blocks(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def write_translation_blocks(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def spans_by_block(protected_spans: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    spans = protected_spans.get("spans")
    if not isinstance(spans, list):
        return grouped
    for span in spans:
        if not isinstance(span, dict):
            continue
        kind = str(span.get("kind") or "")
        value = str(span.get("value") or "")
        block_id = str(span.get("block_id") or "")
        if kind in STRICT_KINDS and value and block_id:
            grouped.setdefault(block_id, []).append(span)
    return grouped


def restore_translation(translation: str, missing_spans: list[dict[str, Any]]) -> str:
    values = [str(item.get("value") or "") for item in missing_spans if item.get("value")]
    if not values:
        return translation
    marker = "受保护元素恢复："
    unique_values = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    suffix = f"\n\n（{marker}{'；'.join(unique_values)}）"
    return translation.rstrip() + suffix


def repair_records(
    records: list[dict[str, Any]],
    protected_spans: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped = spans_by_block(protected_spans)
    repaired_records: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        block_id = str(item.get("block_id") or "")
        translation = str(item.get("translation") or "")
        missing = [span for span in grouped.get(block_id, []) if str(span.get("value") or "") not in translation]
        if missing and item.get("status") == "ok":
            item["translation"] = restore_translation(translation, missing)
            item["protected_span_repair_status"] = "auto_restored"
            item["restored_protected_spans"] = [
                {
                    "kind": span.get("kind"),
                    "value": span.get("value"),
                    "span_id": span.get("span_id"),
                    "page": span.get("page"),
                }
                for span in missing
            ]
            repairs.append(
                {
                    "block_id": block_id,
                    "status": "auto_restored",
                    "restored_count": len(missing),
                    "restored_spans": item["restored_protected_spans"],
                    "previous_translation": translation,
                    "repaired_translation": item["translation"],
                }
            )
        repaired_records.append(item)
    return repaired_records, repairs


def merge_translation(records: list[dict[str, Any]]) -> str:
    parts = []
    for record in records:
        block_id = str(record.get("block_id") or "")
        translation = str(record.get("translation") or "").strip()
        status = str(record.get("status") or "ok")
        if status != "ok" and not translation:
            translation = f"<!-- 翻译失败：{record.get('error') or 'unknown error'} -->"
        parts.append(f"<!-- block:{block_id} -->\n\n{translation}".rstrip())
    return "\n\n".join(parts).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair missing protected spans in translation blocks.")
    parser.add_argument("--translation-blocks", required=True, help="translation_blocks.jsonl path.")
    parser.add_argument("--protected-spans", required=True, help="protected_spans.json path.")
    parser.add_argument("--output-blocks", help="Output repaired translation blocks JSONL.")
    parser.add_argument("--output", help="Output repaired translation Markdown.")
    parser.add_argument("--plan", help="Output protected span repair plan JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    translation_blocks_path = Path(args.translation_blocks)
    protected_spans_path = Path(args.protected_spans)
    output_blocks_path = Path(args.output_blocks) if args.output_blocks else translation_blocks_path.with_name("translation_blocks.repaired.jsonl")
    output_path = Path(args.output) if args.output else translation_blocks_path.with_name("translation.repaired.md")
    plan_path = Path(args.plan) if args.plan else translation_blocks_path.with_name("protected_span_repair_plan.json")

    records = load_translation_blocks(translation_blocks_path)
    protected_spans = load_json(protected_spans_path)
    repaired_records, repairs = repair_records(records, protected_spans)
    write_translation_blocks(output_blocks_path, repaired_records)
    output_path.write_text(merge_translation(repaired_records), encoding="utf-8")
    payload = {
        "version": 1,
        "status": "repaired" if repairs else "ok",
        "repair_count": len(repairs),
        "input_translation_blocks": str(translation_blocks_path),
        "protected_spans": str(protected_spans_path),
        "output_translation_blocks": str(output_blocks_path),
        "output_translation": str(output_path),
        "repairs": repairs,
    }
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "output_blocks": str(output_blocks_path), "plan": str(plan_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
