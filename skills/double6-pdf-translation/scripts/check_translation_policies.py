#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by check_translation.py for glossary, term, entity, and acronym validation rules."

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_core import *  # noqa: F401,F403

def check_glossary(source: str, translation: str, glossary: list[dict[str, str]]) -> list[Issue]:
    issues: list[Issue] = []
    for row in glossary:
        term = (row.get("source_term") or "").strip()
        expected = (row.get("translation") or "").strip()
        action = (row.get("action") or "").strip()
        block_id = (row.get("first_seen_block") or "").strip()
        if not term or not contains_term(source, term):
            continue
        if not expected:
            issues.append(
                Issue(
                    "low",
                    f"术语待确认: {term}",
                    "术语表尚未填写推荐译法。",
                    category="terminology",
                    source_evidence=term,
                    suggestion="翻译前补全术语译法、保留策略和 review_status。",
                    block_id=block_id,
                )
            )
            continue
        if action.startswith("keep"):
            ok = contains_term(translation, term) or any(
                contains_term(translation, item) for item in expected_translation_alternatives(expected)
            )
        else:
            ok = policy_translation_ok(translation, expected)
        if not ok:
            issues.append(
                Issue(
                    "medium",
                    f"术语译法未命中: {term}",
                    f"术语表期望译法为“{expected}”，但译文中未找到对应表达。",
                    category="terminology",
                    source_evidence=term,
                    translation_evidence=excerpt(translation),
                    suggestion=f"按术语表统一为“{expected}”。",
                    block_id=block_id,
                )
            )
    return issues


def check_glossary_by_blocks(
    source: str,
    translation: str,
    glossary: list[dict[str, str]],
    translation_blocks: list[dict[str, Any]],
) -> list[Issue]:
    if not translation_blocks:
        return check_glossary(source, translation, glossary)
    issues: list[Issue] = []
    for row in glossary:
        term = (row.get("source_term") or "").strip()
        expected = (row.get("translation") or "").strip()
        action = (row.get("action") or "").strip()
        preferred_block_id = (row.get("first_seen_block") or "").strip()
        if not term:
            continue
        matching_blocks = [
            record
            for record in translation_blocks
            if isinstance(record, dict)
            and contains_term(str(record.get("source_text") or ""), term)
            and (not preferred_block_id or str(record.get("block_id") or "") == preferred_block_id)
        ]
        if not matching_blocks:
            matching_blocks = [
                record
                for record in translation_blocks
                if isinstance(record, dict) and contains_term(str(record.get("source_text") or ""), term)
            ]
        if not matching_blocks and contains_term(source, term):
            matching_blocks = [{"block_id": preferred_block_id, "source_text": term, "translation": translation}]
        for record in matching_blocks:
            block_id = str(record.get("block_id") or preferred_block_id)
            block_translation = block_translation_or_document(record, translation)
            if not expected:
                issues.append(
                    Issue(
                        "low",
                        f"术语待确认: {term}",
                        "术语表尚未填写推荐译法。",
                        category="terminology",
                        source_evidence=term,
                        suggestion="翻译前补全术语译法、保留策略和 review_status。",
                        block_id=block_id,
                    )
                )
                continue
            if action.startswith("keep"):
                ok = contains_term(block_translation, term) or any(
                    contains_term(block_translation, item) for item in expected_translation_alternatives(expected)
                )
            else:
                ok = policy_translation_ok(block_translation, expected)
            if not ok:
                issues.append(
                    Issue(
                        "medium",
                        f"术语译法未命中: {term}",
                        f"术语表期望译法为“{expected}”，但该 block 译文中未找到对应表达。",
                        category="terminology",
                        source_evidence=term,
                        translation_evidence=excerpt(block_translation),
                        suggestion=f"按术语表统一为“{expected}”。",
                        block_id=block_id,
                    )
                )
    return issues


def check_default_term_policies(source: str, translation: str, *, manifest: dict[str, Any] | None = None) -> list[Issue]:
    term_policy = build_term_policy([], manifest=manifest or {})
    return check_term_policy(source, translation, term_policy, manifest=manifest or {})


def check_term_policy(
    source: str,
    translation: str,
    term_policy: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    combined_source = source or manifest_source_text(manifest or {})
    policies = term_policy.get("terms") if isinstance(term_policy.get("terms"), list) else []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        if not policy_source_present(combined_source, policy):
            continue
        expected = str(policy.get("translation") or "")
        block_id = first_seen_block_for_policy(policy, manifest or {})
        forbidden = [str(item) for item in policy.get("forbidden_translations") or [] if item]
        forbidden_hits = [item for item in forbidden if item in translation]
        if forbidden_hits:
            issues.append(
                Issue(
                    "high",
                    f"术语禁用译法命中: {policy['source_term']}",
                    f"译文出现禁用译法“{'、'.join(forbidden_hits)}”。",
                    category="terminology",
                    source_evidence=str(policy["source_term"]),
                    translation_evidence="、".join(forbidden_hits),
                    suggestion=f"统一为“{expected}”。{policy.get('note') or ''}".strip(),
                    block_id=block_id,
                )
            )
            continue
        if expected and not policy_translation_ok(translation, expected):
            issues.append(
                Issue(
                    "medium",
                    f"高优先级术语未按策略呈现: {policy['source_term']}",
                    f"源文包含该术语，但译文未命中推荐译法“{expected}”。",
                    category="terminology",
                    source_evidence=str(policy["source_term"]),
                    translation_evidence=excerpt(translation),
                    suggestion=f"统一为“{expected}”。{policy.get('note') or ''}".strip(),
                    block_id=block_id,
                )
            )
    return issues


def check_entity_policies(source: str, translation: str, *, manifest: dict[str, Any] | None = None) -> list[Issue]:
    entity_map = build_entity_map(manifest or {}, [])
    return check_entity_map_policies(source, translation, entity_map, manifest=manifest or {})


def check_entity_map_policies(
    source: str,
    translation: str,
    entity_map: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    combined_source = source or manifest_source_text(manifest or {})
    policies = entity_map.get("entities") if isinstance(entity_map.get("entities"), list) else []
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        source_has_policy = policy_source_present(combined_source, policy) or bool(policy.get("active"))
        expected = str(policy.get("translation") or "")
        forbidden = [str(item) for item in policy.get("forbidden_translations") or [] if item]
        forbidden_hits = [item for item in forbidden if item in translation]
        if not source_has_policy and not (expected and expected in translation and forbidden_hits):
            continue
        block_id = first_seen_block_for_policy(policy, manifest or {})
        if forbidden_hits:
            issues.append(
                Issue(
                    "high",
                    f"专名实体误译: {policy['source_term']}",
                    f"译文出现禁用译法“{'、'.join(forbidden_hits)}”，可能把不同机构或专名混淆。",
                    category="entity_accuracy",
                    source_evidence=str(policy["source_term"]),
                    translation_evidence="、".join(forbidden_hits),
                    suggestion=f"改为“{expected}”。{policy.get('note') or ''}".strip(),
                    block_id=block_id,
                )
            )
            continue
        if expected and not policy_translation_ok(translation, expected):
            issues.append(
                Issue(
                    "medium",
                    f"专名实体未按策略呈现: {policy['source_term']}",
                    f"源文包含该实体，但译文未命中推荐译名“{expected}”。",
                    category="entity_accuracy",
                    source_evidence=str(policy["source_term"]),
                    translation_evidence=excerpt(translation),
                    suggestion=f"统一为“{expected}”。{policy.get('note') or ''}".strip(),
                    block_id=block_id,
                )
            )
    return issues


def protected_values(protected_spans: dict[str, Any] | None) -> set[str]:
    spans = (protected_spans or {}).get("spans")
    values: set[str] = set()
    if isinstance(spans, list):
        for item in spans:
            if isinstance(item, dict) and item.get("value"):
                values.add(str(item["value"]))
    return values


def term_policy_terms(term_policy: dict[str, Any] | None) -> set[str]:
    terms: set[str] = set()
    items = (term_policy or {}).get("terms")
    if not isinstance(items, list):
        return terms
    for item in items:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term") or "")
        if source_term:
            terms.add(source_term.lower())
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            terms.update(str(alias).lower() for alias in aliases if alias)
    return terms


def entity_policy_terms(entity_map: dict[str, Any] | None) -> set[str]:
    terms: set[str] = set()
    items = (entity_map or {}).get("entities")
    if not isinstance(items, list):
        return terms
    for item in items:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term") or "")
        if source_term:
            terms.add(source_term.lower())
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            terms.update(str(alias).lower() for alias in aliases if alias)
    return terms
