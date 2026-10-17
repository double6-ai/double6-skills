# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation terms：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def extract_percentages(text: str) -> list[str]:
    from check_translation_core import normalize_percent
    values: list[str] = []
    for match in PERCENT_RE.finditer(text):
        value = normalize_percent(match.group(0))
        if value not in values:
            values.append(value)
    return values


def check_bad_acronym_translation(source: str, translation: str, *, block_id: str = "") -> list[Issue]:
    issues: list[Issue] = []
    if re.search(r"\bLLMs?\b", source) and "法学硕士" in translation:
        issues.append(
            Issue(
                "high",
                "LLM/LLMs 缩写误译",
                "源文包含 LLM/LLMs，但译文出现“法学硕士”。在大模型论文中应保留缩写并解释为大语言模型。",
                category="terminology",
                source_evidence="LLM/LLMs",
                translation_evidence="法学硕士",
                suggestion="改为 LLM/LLMs（大语言模型）或按上下文写作“大语言模型”。",
                block_id=block_id,
            )
        )
    if "Literature Review" in source and "文学评论" in translation:
        issues.append(
            Issue(
                "medium",
                "Literature Review 语境误译风险",
                "学术论文语境下 Literature Review 通常应译为“文献综述”，不是“文学评论”。",
                category="terminology",
                source_evidence="Literature Review",
                translation_evidence="文学评论",
                suggestion="在论文语境中改为“文献综述”。",
                block_id=block_id,
            )
        )
    return issues

def check_bad_acronym_translation_blocks(source: str, translation: str, translation_blocks: list[dict[str, Any]]) -> list[Issue]:
    if not translation_blocks:
        return check_bad_acronym_translation(source, translation)
    issues: list[Issue] = []
    for record in translation_blocks:
        if not isinstance(record, dict):
            continue
        issues.extend(
            check_bad_acronym_translation(
                str(record.get("source_text") or ""),
                str(record.get("translation") or ""),
                block_id=str(record.get("block_id") or ""),
            )
        )
    return issues

def check_glossary(source: str, translation: str, glossary: list[dict[str, str]]) -> list[Issue]:
    from check_translation_core import contains_term, excerpt, expected_translation_alternatives, policy_translation_ok
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
    from check_translation_core import block_translation_or_document, contains_term, excerpt, expected_translation_alternatives, policy_translation_ok
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
    from check_translation_memory import build_term_policy
    term_policy = build_term_policy([], manifest=manifest or {})
    return check_term_policy(source, translation, term_policy, manifest=manifest or {})


def check_term_policy(
    source: str,
    translation: str,
    term_policy: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    from check_translation_core import excerpt, first_seen_block_for_policy, manifest_source_text, policy_source_present, policy_translation_ok
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
    from check_translation_memory import build_entity_map
    entity_map = build_entity_map(manifest or {}, [])
    return check_entity_map_policies(source, translation, entity_map, manifest=manifest or {})


def check_entity_map_policies(
    source: str,
    translation: str,
    entity_map: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    from check_translation_core import excerpt, first_seen_block_for_policy, manifest_source_text, policy_source_present, policy_translation_ok
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


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
