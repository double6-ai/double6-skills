# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation memory：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def detect_domain_term_seeds(manifest: dict[str, Any] | None = None, source: str = "") -> list[dict[str, Any]]:
    from check_translation_core import manifest_source_text
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
    from check_translation_core import first_seen_block_for_policy, manifest_source_text, policy_source_location, policy_source_present
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


def build_document_memory(
    manifest: dict[str, Any],
    glossary: list[dict[str, str]],
    *,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from check_translation_core import contains_term, excerpt
    from check_translation_fidelity import build_coverage_gate
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


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
