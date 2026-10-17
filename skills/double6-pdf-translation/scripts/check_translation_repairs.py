# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation repairs：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def build_qa_checks(issues: list[Issue]) -> dict[str, Any]:
    from check_translation_reports import build_science_qa_review_items
    checks = []
    for issue in issues:
        if issue.severity not in {"high", "medium"}:
            continue
        checks.append(
            {
                "status": "needs_review",
                "severity": issue.severity,
                "category": issue.category,
                "rule": issue.rule or issue.category,
                "block_id": issue.block_id or "document",
                "page": issue.page or "global",
                "question": f"译文是否正确处理了：{issue.title}？",
                "source_context": issue.source_evidence,
                "translation_context": issue.translation_evidence,
                "source_evidence": issue.source_evidence,
                "translation_evidence": issue.translation_evidence,
                "suggestion": issue.suggestion,
                "repair_type": repair_type_for_issue(issue),
            }
        )
    checks.extend(build_science_qa_review_items(issues))
    return {
        "version": 1,
        "status": "warn" if checks else "ok",
        "check_count": len(checks),
        "science_qa_count": sum(1 for item in checks if item.get("check_type") == "science_information_qa"),
        "checks": checks,
    }


def repair_type_for_issue(issue: Issue) -> str:
    if issue.rule in {"modality_drift", "negation_drift", "causality_drift", "evidence_strength_drift", "citation_context_drift", "figure_table_claim_drift"}:
        return "claim_drift_review"
    if issue.rule == "protected_citation_missing":
        return "repair_protected_span"
    if issue.category == "protected_span":
        return "repair_protected_span"
    if issue.category == "accuracy" and ("百分比" in issue.title or "数值" in issue.title):
        return "repair_quantitative_fact"
    if issue.category == "source_quality":
        return "review_source_extraction"
    if issue.category == "terminology":
        return "review_terminology"
    if issue.category in {"omission", "addition", "structure"}:
        return "retranslate_or_realign_block"
    return "review_block"

def build_affected_blocks(
    issues: list[Issue],
    manifest: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    block_info: dict[str, dict[str, Any]] = {}
    blocks = manifest.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("block_id") or "")
            if not block_id:
                continue
            block_info[block_id] = {
                "page": block.get("page"),
                "section": block.get("section"),
                "element_type": block.get("element_type"),
                "source_text": block.get("text", ""),
            }
    translation_by_block = {
        str(record.get("block_id") or ""): record
        for record in translation_blocks
        if isinstance(record, dict)
    }
    affected_by_block: dict[str, dict[str, Any]] = {}
    for issue in issues:
        if issue.severity not in {"high", "medium"}:
            continue
        block_id = issue.block_id or "document"
        item = affected_by_block.setdefault(
            block_id,
            {
                "block_id": block_id,
                "status": "needs_repair",
                "repair_types": [],
                "issues": [],
                "page": issue.page or block_info.get(block_id, {}).get("page") or "global",
                "section": block_info.get(block_id, {}).get("section", ""),
                "source_text": block_info.get(block_id, {}).get("source_text", ""),
                "previous_translation": str(translation_by_block.get(block_id, {}).get("translation") or ""),
            },
        )
        repair_type = repair_type_for_issue(issue)
        if repair_type not in item["repair_types"]:
            item["repair_types"].append(repair_type)
        item["issues"].append(
            {
                "severity": issue.severity,
                "category": issue.category,
                "title": issue.title,
                "source_evidence": issue.source_evidence,
                "translation_evidence": issue.translation_evidence,
                "suggestion": issue.suggestion,
            }
        )
    affected_blocks = sorted(
        affected_by_block.values(),
        key=lambda item: (str(item.get("block_id") == "document"), str(item.get("block_id"))),
    )
    return {
        "version": 1,
        "status": "warn" if affected_blocks else "ok",
        "affected_block_count": len(affected_blocks),
        "affected_blocks": affected_blocks,
        "notes": [
            "该文件由 check_translation.py 生成，用于局部修复、局部重译或人工复核。",
            "protected_span 问题可优先运行 repair_protected_spans.py；数字事实和术语问题建议局部重译或人工修订。",
        ],
    }

def repair_decision(category: str, suggestion: str) -> dict[str, bool | str]:
    if category in {"rendering", "structure"} or "rendering" in category or "structure" in category:
        return {
            "auto_fixable": False,
            "requires_rerender": True,
            "repair_action": "rerender_or_readable_fallback",
        }
    if category in {"terminology", "entity_accuracy", "omission"} and suggestion:
        return {
            "auto_fixable": False,
            "requires_rerender": True,
            "repair_action": "local_retranslation_or_policy_repair",
        }
    return {
        "auto_fixable": bool(suggestion),
        "requires_rerender": False,
        "repair_action": "text_patch_review",
    }

def normalize_manual_confirmations(manual_confirmations: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = manual_confirmations.get("confirmations")
    if raw_items is None:
        raw_items = manual_confirmations.get("manual_confirmations")
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    if not isinstance(raw_items, list):
        return []
    items = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or item.get("mqm_category") or "accuracy")
        suggestion = str(item.get("suggested_repair") or item.get("suggestion") or item.get("repair") or item.get("repair_policy") or "")
        decision = repair_decision(category, suggestion)
        items.append(
            {
                "confirmation_id": str(item.get("confirmation_id") or item.get("id") or f"manual-{index:04d}"),
                "case_id": str(item.get("case_id") or item.get("case") or ""),
                "status": str(item.get("status") or "confirmed"),
                "category": category,
                "block_id": str(item.get("block_id") or item.get("block") or "document"),
                "page": str(item.get("page") or "global"),
                "source_evidence": str(item.get("source_evidence") or item.get("source") or ""),
                "translation_evidence": str(item.get("translation_evidence") or item.get("translation") or ""),
                "suggested_repair": suggestion,
                "reason": str(item.get("reason") or item.get("note") or item.get("issue") or item.get("confirmation") or ""),
                **decision,
                "source": "manual_confirmation",
            }
        )
    return items

def build_confirmed_repair_plan(
    manual_confirmations: dict[str, Any],
    affected_blocks: dict[str, Any],
    manifest: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    block_info: dict[str, dict[str, Any]] = {}
    for block in manifest.get("blocks", []) if isinstance(manifest.get("blocks"), list) else []:
        if isinstance(block, dict) and block.get("block_id"):
            block_info[str(block["block_id"])] = block
    translations = {
        str(record.get("block_id") or ""): str(record.get("translation") or "")
        for record in translation_blocks
        if isinstance(record, dict)
    }
    repairs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in normalize_manual_confirmations(manual_confirmations):
        block_id = str(item.get("block_id") or "document")
        if block_id in block_info:
            item["page"] = str(item.get("page") or block_info[block_id].get("page") or "global")
            item["source_text"] = str(block_info[block_id].get("text") or "")
            item["previous_translation"] = translations.get(block_id, "")
        key = (block_id, str(item.get("category")), str(item.get("translation_evidence") or item.get("source_evidence")))
        repairs[key] = item
    for block in affected_blocks.get("affected_blocks", []) if isinstance(affected_blocks.get("affected_blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "document")
        for issue in block.get("issues", []) if isinstance(block.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            category = str(issue.get("category") or "accuracy")
            translation_evidence = str(issue.get("translation_evidence") or "")
            key = (block_id, category, translation_evidence or str(issue.get("source_evidence") or ""))
            if key in repairs:
                continue
            suggestion = str(issue.get("suggestion") or "")
            repairs[key] = {
                "confirmation_id": "",
                "case_id": "",
                "status": "qa_detected",
                "category": category,
                "block_id": block_id,
                "page": str(block.get("page") or "global"),
                "source_evidence": str(issue.get("source_evidence") or ""),
                "translation_evidence": translation_evidence,
                "suggested_repair": suggestion,
                "reason": str(issue.get("title") or ""),
                **repair_decision(category, suggestion),
                "source_text": str(block.get("source_text") or ""),
                "previous_translation": str(block.get("previous_translation") or ""),
                "source": "affected_blocks",
            }
    items = sorted(repairs.values(), key=lambda item: (str(item.get("source") != "manual_confirmation"), str(item.get("block_id")), str(item.get("category"))))
    return {
        "version": 1,
        "status": "warn" if items else "ok",
        "repair_count": len(items),
        "manual_confirmation_count": sum(1 for item in items if item.get("source") == "manual_confirmation"),
        "repairs": items,
        "notes": [
            "confirmed_repair_plan.json 合并人工确认和 QA 高/中风险问题；人工确认优先。",
            "PDF 视觉/版式问题只生成重渲染或可读降级建议，不自动修改 PDF。",
        ],
    }

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check an academic paper translation for terminology and structure risks.")
    parser.add_argument("--source", required=True, help="Source Markdown/text path.")
    parser.add_argument("--translation", required=True, help="Translation Markdown/text path.")
    parser.add_argument("--glossary", help="Glossary TSV path.")
    parser.add_argument("--source-manifest", help="source_manifest.json path. Defaults to beside source.")
    parser.add_argument("--protected-spans", help="protected_spans.json path. Defaults to beside source.")
    parser.add_argument("--translation-blocks", help="translation_blocks.jsonl path. Defaults to beside translation.")
    parser.add_argument("--render-manifest", help="render_manifest.json path. Defaults to beside translation.")
    parser.add_argument("--latex-block-bridge", type=Path, help="Optional reproducible final-TeX bridge; does not grant PDF acceptance.")
    parser.add_argument("--output", help="Quality report path. Defaults to quality_report.md beside the translation.")
    return parser

def main(argv: list[str] | None = None) -> int:
    from check_translation_core import load_glossary, load_json, load_translation_blocks
    from check_translation_fidelity import build_coverage_gate
    from check_translation_gates import collect_issues
    from check_translation_memory import build_document_memory, build_entity_map, build_term_policy
    from check_translation_reports import build_alignment_report, render_quality_report
    args = build_parser().parse_args(argv)
    source_path = Path(args.source)
    translation_path = Path(args.translation)
    glossary_path = Path(args.glossary) if args.glossary else None
    manifest_path = Path(args.source_manifest) if args.source_manifest else source_path.with_name("source_manifest.json")
    protected_spans_path = Path(args.protected_spans) if args.protected_spans else source_path.with_name("protected_spans.json")
    translation_blocks_path = Path(args.translation_blocks) if args.translation_blocks else translation_path.with_name("translation_blocks.jsonl")
    render_manifest_path = Path(args.render_manifest) if args.render_manifest else translation_path.with_name("render_manifest.json")
    output_path = Path(args.output) if args.output else translation_path.with_name("quality_report.md")

    source = source_path.read_text(encoding="utf-8", errors="replace")
    translation = translation_path.read_text(encoding="utf-8", errors="replace")
    glossary = load_glossary(glossary_path)
    manifest = load_json(manifest_path)
    manifest["coverage_gate"] = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else build_coverage_gate(manifest, translation)
    protected_spans = load_json(protected_spans_path)
    translation_blocks = load_translation_blocks(translation_blocks_path)
    render_manifest = load_json(render_manifest_path)
    term_policy = build_term_policy(glossary, manifest=manifest, source=source)
    entity_map = build_entity_map(manifest, glossary)
    issues = collect_issues(
        source,
        translation,
        glossary,
        manifest=manifest,
        protected_spans=protected_spans,
        translation_blocks=translation_blocks,
        render_manifest=render_manifest,
        latex_block_bridge_path=args.latex_block_bridge,
    )
    report = render_quality_report(issues)
    output_path.write_text(report, encoding="utf-8")
    output_path.with_name("alignment_report.json").write_text(
        json.dumps(build_alignment_report(manifest, translation_blocks), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("document_memory.json").write_text(
        json.dumps(
            build_document_memory(manifest, glossary, entity_map=entity_map, term_policy=term_policy),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    output_path.with_name("term_policy.json").write_text(
        json.dumps(term_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("entity_map.json").write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("qa_checks.json").write_text(
        json.dumps(build_qa_checks(issues), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    affected_blocks = build_affected_blocks(issues, manifest, translation_blocks)
    output_path.with_name("affected_blocks.json").write_text(
        json.dumps(affected_blocks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("confirmed_repair_plan.json").write_text(
        json.dumps(
            build_confirmed_repair_plan(
                load_json(output_path.with_name("manual_confirmations.json")),
                affected_blocks,
                manifest,
                translation_blocks,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    repaired_translation, qa_repair_plan = repair_quality_issues.repair_translation(
        translation,
        affected_blocks,
        repair_quality_issues.DEFAULT_RESIDUE_TRANSLATIONS,
    )
    repaired_path = output_path.with_name("translation.qa_repaired.md")
    qa_repair_plan_path = output_path.with_name("qa_repair_plan.json")
    repaired_path.write_text(repaired_translation, encoding="utf-8")
    qa_repair_plan.update(
        {
            "input_translation": str(translation_path),
            "affected_blocks": str(output_path.with_name("affected_blocks.json")),
            "output_translation": str(repaired_path),
        }
    )
    qa_repair_plan_path.write_text(json.dumps(qa_repair_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
