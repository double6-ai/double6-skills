#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIELDS = [
    "source_term",
    "translation",
    "action",
    "note",
    "confidence",
    "first_seen_block",
    "review_status",
    "term_type",
    "noise_reason",
    "notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_glossary(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return [{field: row.get(field, "") for field in FIELDS} for row in rows]


def write_glossary(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def parse_inline_edit(value: str) -> dict[str, str]:
    if "=" not in value:
        raise ValueError(f"Invalid --edit value, expected source=translation: {value}")
    source_term, translation = value.split("=", 1)
    source_term = source_term.strip()
    translation = translation.strip()
    if not source_term or not translation:
        raise ValueError(f"Invalid --edit value, expected non-empty source and translation: {value}")
    return {"source_term": source_term, "translation": translation}


def load_edits(args: argparse.Namespace) -> list[dict[str, str]]:
    edits = [parse_inline_edit(item) for item in (args.edit or [])]
    if args.edits_json:
        data = json.loads(Path(args.edits_json).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("edits", [])
        if not isinstance(data, list):
            raise ValueError("--edits-json must contain a list or an object with edits")
        for item in data:
            if not isinstance(item, dict):
                continue
            source_term = str(item.get("source_term") or item.get("term") or "").strip()
            translation = str(item.get("translation") or item.get("target_term") or "").strip()
            if source_term and translation:
                edits.append({"source_term": source_term, "translation": translation, "note": str(item.get("note") or "")})
    if not edits:
        raise ValueError("Provide at least one --edit source=translation or --edits-json")
    return edits


def load_blocks(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = data.get("blocks")
    return blocks if isinstance(blocks, list) else []


def affected_blocks_for_term(term: str, blocks: list[dict[str, Any]]) -> list[str]:
    affected = []
    for block in blocks:
        text = str(block.get("text") or "")
        if term and term in text:
            affected.append(str(block.get("block_id") or ""))
    return [item for item in affected if item]


def apply_edits(
    rows: list[dict[str, str]],
    edits: list[dict[str, str]],
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    by_term = {row.get("source_term", ""): row for row in rows}
    log: list[dict[str, Any]] = []
    for edit in edits:
        term = edit["source_term"]
        translation = edit["translation"]
        row = by_term.get(term)
        if row is None:
            row = {
                "source_term": term,
                "translation": "",
                "action": "translate",
                "note": "人工新增术语。",
                "confidence": "high",
                "first_seen_block": "",
                "review_status": "needs_review",
                "term_type": "concept",
                "noise_reason": "",
                "notes": "",
            }
            rows.append(row)
            by_term[term] = row
        previous = row.get("translation", "")
        affected_blocks = affected_blocks_for_term(term, blocks)
        row["translation"] = translation
        row["review_status"] = "reviewed"
        row["confidence"] = row.get("confidence") or "high"
        if not row.get("first_seen_block") and affected_blocks:
            row["first_seen_block"] = affected_blocks[0]
        note = edit.get("note") or "人工修订译法。"
        existing_notes = row.get("notes", "")
        row["notes"] = f"{existing_notes}; {note}".strip("; ")
        log.append(
            {
                "source_term": term,
                "previous_translation": previous,
                "new_translation": translation,
                "affected_blocks": affected_blocks,
                "note": note,
            }
        )
    return rows, log


def build_retranslation_plan(log: list[dict[str, Any]], translation_blocks_path: Path | None) -> list[dict[str, Any]]:
    if not translation_blocks_path or not translation_blocks_path.exists():
        return []
    affected_terms_by_block: dict[str, list[str]] = {}
    for item in log:
        for block_id in item["affected_blocks"]:
            affected_terms_by_block.setdefault(block_id, []).append(item["source_term"])
    plan = []
    for line in translation_blocks_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        block_id = str(record.get("block_id") or "")
        if block_id in affected_terms_by_block:
            plan.append(
                {
                    "block_id": block_id,
                    "status": "needs_retranslation",
                    "affected_terms": affected_terms_by_block[block_id],
                    "source_text": record.get("source_text", ""),
                    "previous_translation": record.get("translation", ""),
                }
            )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply human glossary edits and produce affected block retranslation plan.")
    parser.add_argument("--glossary", required=True, help="Input glossary.tsv path.")
    parser.add_argument("--source-manifest", help="source_manifest.json path for affected block lookup.")
    parser.add_argument("--translation-blocks", help="translation_blocks.jsonl path for retranslation plan.")
    parser.add_argument("--edit", action="append", help="Inline edit in source_term=translation form. Can repeat.")
    parser.add_argument("--edits-json", help="JSON file containing edits.")
    parser.add_argument("--output", help="Output glossary TSV. Defaults to glossary.reviewed.tsv beside input.")
    parser.add_argument("--log", help="Output human_edit_log.json. Defaults beside output.")
    parser.add_argument("--affected-blocks", help="Output affected_blocks.json. Defaults beside output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    glossary_path = Path(args.glossary)
    output_path = Path(args.output) if args.output else glossary_path.with_name("glossary.reviewed.tsv")
    log_path = Path(args.log) if args.log else output_path.with_name("human_edit_log.json")
    affected_path = Path(args.affected_blocks) if args.affected_blocks else output_path.with_name("affected_blocks.json")
    rows = load_glossary(glossary_path)
    edits = load_edits(args)
    blocks = load_blocks(Path(args.source_manifest) if args.source_manifest else None)
    rows, log = apply_edits(rows, edits, blocks)
    retranslation_plan = build_retranslation_plan(log, Path(args.translation_blocks) if args.translation_blocks else None)

    write_glossary(rows, output_path)
    payload = {
        "status": "ok",
        "created_at": utc_now(),
        "input_glossary": str(glossary_path),
        "output_glossary": str(output_path),
        "edits": log,
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    affected_payload = {
        "status": "ok",
        "created_at": payload["created_at"],
        "affected_blocks": retranslation_plan,
        "affected_block_count": len(retranslation_plan),
    }
    affected_path.write_text(json.dumps(affected_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"glossary": str(output_path), "log": str(log_path), "affected_blocks": str(affected_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
