#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by check_translation.py for issue models, loaders, and shared policy helpers."

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_policy_data import *  # noqa: F401,F403


@dataclass
class Issue:
    severity: str
    title: str
    detail: str
    category: str = "accuracy"
    source_evidence: str = ""
    translation_evidence: str = ""
    suggestion: str = ""
    block_id: str = ""
    page: str = ""
    rule: str = ""


def load_glossary(path: Path | None) -> list[dict[str, str]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_translation_blocks(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
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


def contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    text = normalize_quality_text(text)
    term = normalize_quality_text(term)
    if re.fullmatch(r"[A-Za-z0-9+-]+", term):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text))
    return term in text


def normalize_quality_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "")


def should_use_document_translation(record: dict[str, Any]) -> bool:
    status = " ".join(
        str(record.get(key) or "")
        for key in ["status", "alignment_status", "translation_note"]
    )
    return "external_pdf_text_unaligned" in status or "repaired_full_text_unaligned" in status


def block_translation_or_document(record: dict[str, Any], document_translation: str) -> str:
    block_translation = str(record.get("translation") or "")
    if not block_translation and should_use_document_translation(record):
        return document_translation
    return block_translation


def policy_source_present(text: str, policy: dict[str, Any]) -> bool:
    terms = [str(policy.get("source_term") or "")]
    aliases = policy.get("aliases")
    if isinstance(aliases, list):
        terms.extend(str(item) for item in aliases)
    return any(contains_term(text, term) for term in terms if term)


def policy_translation_ok(translation: str, expected: str) -> bool:
    return any(item and contains_term(translation, item) for item in expected_translation_alternatives(expected))


def manifest_source_text(manifest: dict[str, Any]) -> str:
    parts: list[str] = []
    blocks = manifest.get("blocks")
    if isinstance(blocks, list):
        parts.extend(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
    metadata_blocks = manifest.get("metadata_blocks")
    if isinstance(metadata_blocks, list):
        parts.extend(str(block.get("text") or "") for block in metadata_blocks if isinstance(block, dict))
    return "\n".join(item for item in parts if item)


def metadata_source_text(manifest: dict[str, Any]) -> str:
    metadata_blocks = manifest.get("metadata_blocks")
    if not isinstance(metadata_blocks, list):
        return ""
    return "\n".join(str(block.get("text") or "") for block in metadata_blocks if isinstance(block, dict))


def policy_source_location(manifest: dict[str, Any], policy: dict[str, Any]) -> str:
    body_text = "\n".join(
        str(block.get("text") or "")
        for block in manifest.get("blocks", [])
        if isinstance(block, dict)
    )
    metadata_text = metadata_source_text(manifest)
    if policy_source_present(body_text, policy):
        return "body"
    if policy_source_present(metadata_text, policy):
        return "metadata"
    return "absent"


def first_seen_block_for_policy(policy: dict[str, Any], manifest: dict[str, Any]) -> str:
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return ""
    terms = [str(policy.get("source_term") or "")]
    aliases = policy.get("aliases")
    if isinstance(aliases, list):
        terms.extend(str(item) for item in aliases)
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "")
        if any(contains_term(text, term) for term in terms if term):
            return str(block.get("block_id") or "")
    metadata_blocks = manifest.get("metadata_blocks")
    if isinstance(metadata_blocks, list):
        for block in metadata_blocks:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            if any(contains_term(text, term) for term in terms if term):
                return str(block.get("metadata_id") or "metadata")
    return ""


def expected_translation_alternatives(expected: str) -> list[str]:
    alternatives = [expected]
    paren_match = re.search(r"[（(]([^）)]+)[）)]", expected)
    if paren_match:
        alternatives.append(paren_match.group(1).strip())
        alternatives.append(expected[: paren_match.start()].strip())
    return [item for item in alternatives if item]



def detect_domain_term_seeds(manifest: dict[str, Any] | None = None, source: str = "") -> list[dict[str, Any]]:
    text = "\n".join([source, manifest_source_text(manifest or {})]).lower()
    matched = []
    for seed in DOMAIN_TERM_SEEDS:
        terms = seed.get("match_terms")
        if not isinstance(terms, list):
            continue
        if any(str(term).lower() in text for term in terms):
            matched.append(seed)
    return matched

def merge_policy_row(
    policies: dict[str, dict[str, Any]],
    row: dict[str, Any],
    *,
    source_label: str,
    override: bool = True,
) -> None:
    term = str(row.get("source_term") or "").strip()
    if not term:
        return
    current = policies.get(term, {})
    merged = dict(current)
    for key, value in row.items():
        if value in (None, ""):
            continue
        if override or key not in merged or merged.get(key) in (None, ""):
            merged[key] = value
    if current:
        previous = str(current.get("policy_source") or "")
        merged["policy_source"] = f"{previous}+{source_label}" if previous else source_label
    else:
        merged["policy_source"] = source_label
    merged["source_term"] = term
    policies[term] = merged

def build_term_policy(
    glossary: list[dict[str, str]],
    *,
    manifest: dict[str, Any] | None = None,
    source: str = "",
    manual_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policies: dict[str, dict[str, Any]] = {
        str(item["source_term"]): dict(item, policy_source="default")
        for item in DEFAULT_TERM_POLICIES
        if item.get("source_term")
    }
    matched_domains = detect_domain_term_seeds(manifest, source)
    for seed in matched_domains:
        for row in seed.get("terms", []):
            if isinstance(row, dict):
                merge_policy_row(
                    policies,
                    {**row, "domain_id": seed.get("domain_id"), "domain_label": seed.get("label")},
                    source_label=f"domain:{seed.get('domain_id')}",
                    override=True,
                )
    for row in glossary:
        term = (row.get("source_term") or "").strip()
        if not term:
            continue
        current = policies.get(term, {})
        merge_policy_row(
            policies,
            {
                **current,
            "source_term": term,
            "translation": row.get("translation") or current.get("translation", ""),
            "action": row.get("action") or current.get("action", "decide"),
            "term_type": row.get("term_type") or current.get("term_type", ""),
            "confidence": row.get("confidence") or current.get("confidence", "medium"),
            "first_seen_block": row.get("first_seen_block") or current.get("first_seen_block", ""),
            "review_status": row.get("review_status") or current.get("review_status", "needs_review"),
            "note": row.get("note") or current.get("note", ""),
            },
            source_label="glossary",
            override=True,
        )
    manual_terms = (manual_policy or {}).get("terms")
    if isinstance(manual_terms, list):
        for row in manual_terms:
            if isinstance(row, dict):
                merge_policy_row(policies, row, source_label="manual", override=True)
    return {
        "version": 1,
        "status": "ok" if policies else "empty",
        "matched_domain_seeds": [
            {"domain_id": seed.get("domain_id"), "label": seed.get("label")}
            for seed in matched_domains
        ],
        "term_count": len(policies),
        "terms": sorted(policies.values(), key=lambda item: str(item.get("source_term", "")).lower()),
        "notes": [
            "term_policy.json 是翻译前注入 Qwen 的术语策略；合并顺序为 default < domain seed < glossary.tsv < manual policy。",
            "字段 forbidden_translations 用于 QA 阶段发现禁用译法。",
        ],
    }

def build_entity_map(manifest: dict[str, Any], glossary: list[dict[str, str]] | None = None) -> dict[str, Any]:
    source_text = manifest_source_text(manifest)
    entities: dict[str, dict[str, Any]] = {}
    for policy in DEFAULT_ENTITY_POLICIES:
        term = str(policy.get("source_term") or "")
        location = policy_source_location(manifest, policy)
        entities[term] = {
            **policy,
            "active": policy_source_present(source_text, policy),
            "source_location": location,
            "activation_policy": "if_seen",
            "first_seen_block": first_seen_block_for_policy(policy, manifest),
            "source_evidence": term,
            "policy_source": "default",
            "note": f"{policy.get('note', '')} 若源文或 PDF 页脚/机构块出现该实体，必须使用该译名。".strip(),
        }
    for row in glossary or []:
        term_type = (row.get("term_type") or "").strip()
        term = (row.get("source_term") or "").strip()
        if term_type not in {"organization", "name", "publication"} or not term:
            continue
        entities.setdefault(
            term,
            {
                "source_term": term,
                "aliases": [],
                "translation": row.get("translation") or "",
                "entity_type": term_type,
                "confidence": row.get("confidence") or "medium",
                "forbidden_translations": [],
                "first_seen_block": row.get("first_seen_block") or first_seen_block_for_policy({"source_term": term}, manifest),
                "source_evidence": term,
                "source_location": policy_source_location(manifest, {"source_term": term}),
                "activation_policy": "if_seen",
                "policy_source": "glossary",
            },
        )
    return {
        "version": 1,
        "status": "ok" if entities else "empty",
        "entity_count": len(entities),
        "entities": sorted(
            entities.values(),
            key=lambda item: (
                0 if item.get("active") else 1,
                {"body": 0, "metadata": 1, "absent": 2}.get(str(item.get("source_location") or "absent"), 2),
                str(item.get("source_term", "")).lower(),
            ),
        ),
        "notes": [
            "entity_map.json 记录论文中的机构、专名和出版物，QA 会用它区分专名误译与普通术语问题。",
        ],
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


def excerpt(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def block_page_map(manifest: dict[str, Any]) -> dict[str, str]:
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return {}
    pages: dict[str, str] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        page = block.get("page")
        if block_id and page is not None:
            pages[block_id] = str(page)
    return pages


def enrich_issue_locations(issues: list[Issue], manifest: dict[str, Any]) -> list[Issue]:
    pages = block_page_map(manifest)
    for issue in issues:
        if issue.block_id and not issue.page:
            issue.page = pages.get(issue.block_id, "")
        if issue.severity in {"high", "medium"}:
            if not issue.block_id:
                issue.block_id = "document"
            if not issue.page:
                issue.page = "global"
    return issues


def normalize_percent(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("％", "%")


def extract_percentages(text: str) -> list[str]:
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
