#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by check_translation.py for term policy, entity map, document memory, and repair plan builders."

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_report_runtime import *  # noqa: F401,F403


def build_document_memory(
    manifest: dict[str, Any],
    glossary: list[dict[str, str]],
    *,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocks = manifest.get("blocks")
    blocks = blocks if isinstance(blocks, list) else []
    sections: dict[str, dict[str, Any]] = {}
    block_index: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        if block_id:
            block_index[block_id] = block
        section = str(block.get("section") or "(未分节)")
        item = sections.setdefault(section, {"section": section, "block_ids": [], "pages": [], "char_count": 0, "summary": ""})
        item["block_ids"].append(block.get("block_id"))
        if block.get("page") not in item["pages"]:
            item["pages"].append(block.get("page"))
        item["char_count"] += int(block.get("char_count") or 0)
        if not item["summary"]:
            item["summary"] = excerpt(str(block.get("text") or ""), 180)
    terms = [
        {
            "source_term": row.get("source_term", ""),
            "translation": row.get("translation", ""),
            "review_status": row.get("review_status", ""),
            "first_seen_block": row.get("first_seen_block", ""),
            "action": row.get("action", ""),
            "term_type": row.get("term_type", ""),
        }
        for row in glossary
        if row.get("source_term")
    ]
    term_policy_payload = term_policy or build_term_policy(glossary)
    entity_payload = entity_map or build_entity_map(manifest, glossary)
    source_blocks_text = [
        (str(block.get("block_id") or ""), str(block.get("text") or ""))
        for block in blocks
        if isinstance(block, dict)
    ]

    def related_blocks_for_terms(terms_to_match: list[str]) -> list[str]:
        related: list[str] = []
        for block_id, text in source_blocks_text:
            if block_id and any(contains_term(text, term) for term in terms_to_match if term):
                related.append(block_id)
        return related

    term_decisions = []
    for item in term_policy_payload.get("terms", []) if isinstance(term_policy_payload.get("terms"), list) else []:
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        source_term = str(item.get("source_term") or "")
        related = related_blocks_for_terms([source_term, *[str(alias) for alias in aliases]])
        term_decisions.append(
            {
                "source_term": source_term,
                "translation": item.get("translation") or "",
                "action": item.get("action") or "decide",
                "term_type": item.get("term_type") or "",
                "policy_source": item.get("policy_source") or "",
                "first_seen_block": item.get("first_seen_block") or (related[0] if related else ""),
                "related_block_ids": related,
                "forbidden_translations": item.get("forbidden_translations") if isinstance(item.get("forbidden_translations"), list) else [],
                "provenance": {
                    "source": item.get("policy_source") or "unknown",
                    "confidence": item.get("confidence") or "",
                    "note": item.get("note") or "",
                },
            }
        )
    entity_chains = []
    for item in entity_payload.get("entities", []) if isinstance(entity_payload.get("entities"), list) else []:
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        source_term = str(item.get("source_term") or "")
        related = related_blocks_for_terms([source_term, *[str(alias) for alias in aliases]])
        if not related and item.get("first_seen_block"):
            related = [str(item.get("first_seen_block"))]
        entity_chains.append(
            {
                "source_term": source_term,
                "translation": item.get("translation") or "",
                "entity_type": item.get("entity_type") or "",
                "active": bool(item.get("active")),
                "first_seen_block": item.get("first_seen_block") or (related[0] if related else ""),
                "related_block_ids": related,
                "source_location": item.get("source_location") or "",
            }
        )
    cross_chunk_links = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        if not block_id:
            continue
        text = str(block.get("text") or "")
        matched_terms = [
            item["source_term"]
            for item in term_decisions
            if item.get("source_term") and contains_term(text, str(item.get("source_term")))
        ][:12]
        matched_entities = [
            item["source_term"]
            for item in entity_chains
            if item.get("source_term") and contains_term(text, str(item.get("source_term")))
        ][:12]
        neighbor_ids = [
            str(blocks[position].get("block_id") or "")
            for position in (index - 1, index + 1)
            if 0 <= position < len(blocks) and isinstance(blocks[position], dict) and blocks[position].get("block_id")
        ]
        if matched_terms or matched_entities or neighbor_ids:
            cross_chunk_links.append(
                {
                    "block_id": block_id,
                    "section": block.get("section") or "",
                    "page": block.get("page"),
                    "neighbor_block_ids": neighbor_ids,
                    "matched_terms": matched_terms,
                    "matched_entities": matched_entities,
                    "context_policy": "inject_same_section_neighbors_and_matched_term_entity_chains",
                }
            )
    human_edits = [
        {
            "source_term": item.get("source_term"),
            "translation": item.get("translation"),
            "related_block_ids": item.get("related_block_ids", []),
            "status": "candidate_for_propagation",
            "reason": "该术语跨多个 block 出现；人工修订时应生成受影响 block 清单。",
        }
        for item in term_decisions
        if len(item.get("related_block_ids", [])) > 1
    ]
    return {
        "version": 1,
        "source_status": manifest.get("status"),
        "source_input": manifest.get("input"),
        "coverage_gate": manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else build_coverage_gate(manifest),
        "sections": list(sections.values()),
        "glossary_terms": terms,
        "term_policy": term_policy_payload,
        "entity_map": entity_payload,
        "shared_state": {
            "term_decisions": term_decisions,
            "entity_chains": entity_chains,
            "cross_chunk_links": cross_chunk_links,
            "human_edits": human_edits,
            "affected_by_human_edit_candidates": human_edits,
        },
        "notes": [
            "该文件是共享 document memory，用于后续分块翻译时注入章节、术语、实体、人工修订传播和相关邻域上下文。",
            "默认只注入当前 block 的同节邻居、命中术语链和实体链，避免把整篇摘要硬塞进 prompt。",
            "PDFMathTranslate-next CLITranslator 暂不暴露稳定 block_id，因此 PDF 强路径仍以全局术语/实体约束为主，待 block_bridge 稳定后再做 block 级邻域注入。",
        ],
    }


def build_qa_checks(issues: list[Issue]) -> dict[str, Any]:
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
