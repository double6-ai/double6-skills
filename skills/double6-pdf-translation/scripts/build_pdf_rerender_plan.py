#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def block_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    blocks = manifest.get("blocks") if isinstance(manifest.get("blocks"), list) else []
    return {
        str(block.get("block_id") or ""): block
        for block in blocks
        if isinstance(block, dict) and block.get("block_id")
    }


def layout_index(layout_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    blocks = layout_map.get("blocks") if isinstance(layout_map.get("blocks"), list) else []
    return {
        str(block.get("block_id") or ""): block
        for block in blocks
        if isinstance(block, dict) and block.get("block_id")
    }


def iter_affected_issues(affected_blocks: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in affected_blocks.get("affected_blocks", []) if isinstance(affected_blocks.get("affected_blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        for issue in block.get("issues", []) if isinstance(block.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            items.append(
                {
                    "source": "affected_blocks",
                    "block_id": str(block.get("block_id") or issue.get("block_id") or "document"),
                    "page": block.get("page") or issue.get("page") or "global",
                    "section": block.get("section") or "",
                    "category": issue.get("category"),
                    "severity": issue.get("severity"),
                    "title": issue.get("title"),
                    "source_evidence": issue.get("source_evidence"),
                    "translation_evidence": issue.get("translation_evidence"),
                    "suggestion": issue.get("suggestion"),
                    "repair_types": block.get("repair_types") or [],
                }
            )
    return items


def iter_qa_repairs(qa_repair_plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for repair in qa_repair_plan.get("repairs", []) if isinstance(qa_repair_plan.get("repairs"), list) else []:
        if not isinstance(repair, dict):
            continue
        items.append(
            {
                "source": "qa_repair_plan",
                "block_id": str(repair.get("block_id") or "document"),
                "page": repair.get("page") or "global",
                "category": repair.get("repair_type"),
                "severity": "medium",
                "title": repair.get("repair_type"),
                "source_evidence": repair.get("source"),
                "translation_evidence": repair.get("target"),
                "suggestion": f"{repair.get('source', '')} -> {repair.get('target', '')}".strip(" ->"),
                "repair_types": [repair.get("repair_type")],
            }
        )
    return items


def rerender_scope(item: dict[str, Any], layout: dict[str, Any], has_stable_engine_blocks: bool) -> str:
    if has_stable_engine_blocks and layout.get("engine_block_id"):
        return "engine_block"
    if item.get("page") not in (None, "", "global"):
        return "page"
    return "full_document"


def diagnostic_item(
    item: dict[str, Any],
    *,
    note: str,
    block_id: str,
    source_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "source": item.get("source"),
        "block_id": block_id,
        "page": item.get("page"),
        "section": item.get("section") or (source_block or {}).get("section") or "",
        "category": item.get("category"),
        "severity": item.get("severity"),
        "source_evidence": item.get("source_evidence"),
        "translation_evidence": item.get("translation_evidence"),
        "suggestion": item.get("suggestion"),
        "note": note,
    }
    return {key: value for key, value in diagnostic.items() if value not in (None, "")}


def is_document_level_diagnostic(block_id: str, category: str) -> bool:
    if block_id != "document":
        return False
    return category in {
        "coverage",
        "source_quality",
        "omission",
        "structure",
        "auto_text_residue_replacement",
        "policy_literal_replacement",
    }


def is_reference_passthrough_diagnostic(category: str, source_block: dict[str, Any]) -> bool:
    section = str(source_block.get("section") or "").lower()
    source_text = str(source_block.get("text") or "")
    if section != "references":
        return False
    if category not in {"terminology", "entity_accuracy", "policy_literal_replacement"}:
        return False
    reference_markers = ("doi.org/", "10.", "et al", "proc ", "journal", "press", "university")
    return any(marker in source_text.lower() for marker in reference_markers)


def build_plan(
    *,
    source_manifest: dict[str, Any],
    layout_map: dict[str, Any],
    affected_blocks: dict[str, Any],
    qa_repair_plan: dict[str, Any],
    render_manifest: dict[str, Any],
    term_policy: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocks = block_index(source_manifest)
    layouts = layout_index(layout_map)
    layout_blocks = layout_map.get("blocks") if isinstance(layout_map.get("blocks"), list) else []
    has_stable_engine_blocks = any(isinstance(block, dict) and block.get("engine_block_id") for block in layout_blocks)
    raw_items = iter_affected_issues(affected_blocks) + iter_qa_repairs(qa_repair_plan)
    tasks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(raw_items, start=1):
        block_id = str(item.get("block_id") or "document")
        category = str(item.get("category") or "")
        source_block = blocks.get(block_id, {})
        if is_document_level_diagnostic(block_id, category):
            diagnostics.append(
                diagnostic_item(
                    item,
                    block_id=block_id,
                    source_block=source_block,
                    note=(
                        "Document-level QA diagnostics are retained for review but do not define "
                        "an executable PDF rerender task without stable page/block evidence."
                    ),
                )
            )
            continue
        if is_reference_passthrough_diagnostic(category, source_block):
            diagnostics.append(
                diagnostic_item(
                    item,
                    block_id=block_id,
                    source_block=source_block,
                    note=(
                        "References entries are source-language passthrough by layout policy; "
                        "term/entity hits inside citation bodies stay diagnostic unless a visual gate "
                        "confirms they should be localized."
                    ),
                )
            )
            continue
        layout = layouts.get(block_id, {})
        key = (block_id, str(item.get("category") or ""), str(item.get("suggestion") or item.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        scope = rerender_scope(item, layout, has_stable_engine_blocks)
        tasks.append(
            {
                "task_id": f"rerender-{len(tasks) + 1:04d}",
                "status": "planned",
                "source": item.get("source"),
                "category": item.get("category"),
                "severity": item.get("severity"),
                "source_block_id": block_id,
                "engine_block_id": layout.get("engine_block_id"),
                "page": item.get("page") or source_block.get("page") or layout.get("page") or "global",
                "section": item.get("section") or source_block.get("section") or layout.get("section") or "",
                "rerender_scope": scope,
                "backend_target": "pdfmathtranslate-next",
                "can_apply_to_primary_pdf_directly": scope == "engine_block",
                "requires_full_pipeline_rerun": scope == "full_document",
                "source_evidence": item.get("source_evidence"),
                "translation_evidence": item.get("translation_evidence"),
                "suggestion": item.get("suggestion"),
                "source_text": source_block.get("text", ""),
                "layout_reading_order": layout.get("reading_order"),
                "repair_types": item.get("repair_types") or [],
            }
        )
    primary_pdf = (render_manifest.get("outputs") if isinstance(render_manifest.get("outputs"), dict) else {}).get("translated_pdf")
    return {
        "version": 1,
        "status": "needs_rerender" if tasks else "ok",
        "backend": "pdfmathtranslate-next",
        "primary_pdf": primary_pdf,
        "input_pdf": render_manifest.get("input_pdf"),
        "source_override": render_manifest.get("source_override"),
        "stable_engine_block_ids": has_stable_engine_blocks,
        "rerender_strategy": "engine_block" if has_stable_engine_blocks else "page_or_full_pipeline",
        "task_count": len(tasks),
        "diagnostic_count": len(diagnostics),
        "tasks": tasks,
        "diagnostics": diagnostics,
        "policy_inputs": {
            "term_policy": term_policy.get("term_count") if isinstance(term_policy, dict) else None,
            "entity_map": entity_map.get("entity_count") if isinstance(entity_map, dict) else None,
        },
        "command_hint": {
            "full_pipeline": "run_pdf_translation.py <input_pdf> --output-dir <new_output_dir> --source-override <source_override_if_any>",
            "note": "当前没有稳定 engine_block_id 时，不要原地编辑主 PDF；应带修复后的 term_policy/document_memory 重跑强 PDF 路径。",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert QA/policy issues into a PDFMathTranslate-next rerender plan.")
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--layout-map", required=True)
    parser.add_argument("--affected-blocks", required=True)
    parser.add_argument("--qa-repair-plan", required=True)
    parser.add_argument("--render-manifest", required=True)
    parser.add_argument("--term-policy")
    parser.add_argument("--entity-map")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = build_plan(
        source_manifest=load_json(Path(args.source_manifest)),
        layout_map=load_json(Path(args.layout_map)),
        affected_blocks=load_json(Path(args.affected_blocks)),
        qa_repair_plan=load_json(Path(args.qa_repair_plan)),
        render_manifest=load_json(Path(args.render_manifest)),
        term_policy=load_json(Path(args.term_policy)) if args.term_policy else {},
        entity_map=load_json(Path(args.entity_map)) if args.entity_map else {},
    )
    output_path = Path(args.output)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "status": plan["status"], "task_count": plan["task_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
