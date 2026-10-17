# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation reports：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def render_quality_report(issues: list[Issue]) -> str:

    from check_translation_core import excerpt
    high_count = sum(1 for item in issues if item.severity == "high")
    medium_count = sum(1 for item in issues if item.severity == "medium")
    status = "fail" if high_count else "warn" if medium_count or issues else "pass"
    category_counts = {category: sum(1 for item in issues if item.category == category) for category in MQM_CATEGORIES}
    actionable_metrics = {
        "entity_error_count": category_counts.get("entity_accuracy", 0),
        "terminology_issue_count": category_counts.get("terminology", 0),
        "english_residue_count": sum(1 for item in issues if item.title in {"疑似大段英文未翻译", "疑似英文单词残留"}),
        "coverage_warn_fail_count": sum(1 for item in issues if item.category == "coverage" and item.severity in {"high", "medium"}),
        "source_quality_warn_fail_count": sum(1 for item in issues if item.category == "source_quality" and item.severity in {"high", "medium"}),
    }

    lines = [
        "# Paper Translation Quality Report",
        "",
        f"- 状态：`{status}`",
        f"- 高风险问题：{high_count}",
        f"- 中风险问题：{medium_count}",
        f"- 总问题数：{len(issues)}",
        "",
        "## MQM 问题类型统计",
        "",
    ]
    for category in sorted(MQM_CATEGORIES):
        lines.append(f"- `{category}`：{category_counts[category]}")
    lines.extend(
        [
            "",
            "## 可行动指标",
            "",
        ]
    )
    for key, value in actionable_metrics.items():
        lines.append(f"- `{key}`：{value}")
    focus_items = build_review_focus(issues)
    science_qa_items = build_science_qa_review_items(issues)
    lines.extend(
        [
            "",
            "## 困难翻译决策/审校重点",
            "",
        ]
    )
    if focus_items:
        lines.extend(f"- {item}" for item in focus_items)
    else:
        lines.append("- 未发现需要单独记录的困难翻译决策。")
    lines.extend(
        [
            "",
            "## 科学信息 QA 反查",
            "",
        ]
    )
    if science_qa_items:
        lines.extend(f"- {item['question']} 证据：{excerpt(item.get('source_context', '') or item.get('translation_context', ''), 180)}" for item in science_qa_items[:12])
    else:
        lines.append("- 未发现需要 science QA 反查的高/中风险科学信息问题。")
    lines.extend(
        [
            "",
            "## 检查项",
            "",
            "- 术语表一致性",
            "- LLM/LLMs 等缩写误译",
            "- 疑似大段英文未翻译",
            "- Markdown 章节结构缺失",
            "- 数字事实、百分比和比较关系一致性",
            "- 源文本抽取质量风险",
            "- 源文覆盖和评测样本边界",
            "- 专名实体误译和高优先级术语策略",
            "- protected spans 恢复状态",
            "- translation blocks 完整性",
            "",
            "## 问题明细",
            "",
        ]
    )
    if not issues:
        lines.append("- 未发现明显问题。")
    else:
        lines.append("| 严重度 | MQM 类型 | Block | Page | 问题 | 源文证据 | 译文证据 | 建议 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for issue in issues:
            lines.append(
                "| "
                + " | ".join(
                    [
                        issue.severity,
                        issue.category,
                        issue.block_id or "-",
                        issue.page or "-",
                        f"{issue.title}：{issue.detail}",
                        excerpt(issue.source_evidence) or "-",
                        excerpt(issue.translation_evidence) or "-",
                        issue.suggestion or "-",
                    ]
                )
                + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def build_review_focus(issues: list[Issue]) -> list[str]:
    focus: list[str] = []
    if any(issue.rule in {"modality_drift", "negation_drift", "causality_drift", "evidence_strength_drift"} for issue in issues):
        focus.append("模态/否定/证据强度：复核 may/suggest/association/cannot conclude 等表达是否被强化或反转。")
    if any(issue.rule in {"citation_context_drift", "figure_table_claim_drift", "protected_citation_missing"} for issue in issues):
        focus.append("引用/图表引用：复核 citation/ref/DOI/arXiv/Figure/Table 周边句是否改变 claim 支持关系。")
    if any(issue.category == "terminology" for issue in issues):
        focus.append("术语策略：复核 glossary、term_policy 和首次双语/保留英文策略是否一致。")
    if any(issue.category == "protected_span" for issue in issues):
        focus.append("protected span：复核公式、引用、DOI、URL、代码等不可翻译元素是否完整恢复。")
    if any(issue.category == "accuracy" and ("百分比" in issue.title or "数值" in issue.title) for issue in issues):
        focus.append("数字事实：复核百分比、倍数、范围和单一指标是否被新增、拆分或漏译。")
    return focus

def build_science_qa_review_items(issues: list[Issue]) -> list[dict[str, str]]:
    from check_translation_repairs import repair_type_for_issue
    science_rules = {
        "modality_drift",
        "negation_drift",
        "causality_drift",
        "evidence_strength_drift",
        "citation_context_drift",
        "figure_table_claim_drift",
        "protected_citation_missing",
    }
    science_categories = {"accuracy", "coverage", "omission", "addition", "terminology", "entity_accuracy", "protected_span"}
    items: list[dict[str, str]] = []
    for issue in issues:
        if issue.severity not in {"high", "medium"}:
            continue
        if issue.rule not in science_rules and issue.category not in science_categories:
            continue
        question = "译文是否仍能支持源文中的科学主张、限制条件或图表结论？"
        if issue.category == "terminology":
            question = "译文是否保持关键科学术语的固定译名、首次双语或保留英文策略？"
        elif issue.category in {"omission", "coverage"}:
            question = "只读译文时，是否仍能回答源文对应段落的关键信息？"
        elif issue.rule in {"modality_drift", "negation_drift", "evidence_strength_drift"}:
            question = "译文是否保留 may/suggest/cannot conclude 等不确定性和限制语气？"
        elif issue.rule in {"citation_context_drift", "figure_table_claim_drift", "protected_citation_missing"}:
            question = "译文是否保留引用、图表或 DOI 周边句对原主张的支持关系？"
        items.append(
            {
                "check_type": "science_information_qa",
                "rule": issue.rule or issue.category,
                "category": issue.category,
                "block_id": issue.block_id or "document",
                "page": issue.page or "global",
                "question": question,
                "source_context": issue.source_evidence,
                "translation_context": issue.translation_evidence,
                "repair_type": repair_type_for_issue(issue),
            }
        )
    return items


def build_quality_report(
    source: str,
    translation: str,
    glossary: list[dict[str, str]],
    *,
    manifest: dict[str, Any] | None = None,
    protected_spans: dict[str, Any] | None = None,
    translation_blocks: list[dict[str, Any]] | None = None,
    render_manifest: dict[str, Any] | None = None,
) -> str:
    from check_translation_gates import collect_issues
    return render_quality_report(
        collect_issues(
            source,
            translation,
            glossary,
            manifest=manifest,
            protected_spans=protected_spans,
            translation_blocks=translation_blocks,
            render_manifest=render_manifest,
        )
    )


def build_alignment_report(manifest: dict[str, Any], translation_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    source_blocks = manifest.get("blocks")
    source_blocks = source_blocks if isinstance(source_blocks, list) else []
    by_translation: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, int] = {}
    unstable_evidence_records: list[str] = []
    for record in translation_blocks:
        block_id = str(record.get("block_id") or "")
        if block_id:
            seen[block_id] = seen.get(block_id, 0) + 1
            by_translation.setdefault(block_id, []).append(record)
        alignment_note = " ".join(
            str(record.get(key) or "")
            for key in ("alignment_status", "translation_note", "status")
        ).lower()
        if "external_pdf_text_unaligned" in alignment_note or "full_text" in alignment_note:
            unstable_evidence_records.append(block_id or "document")
    mappings = []
    page_windows: dict[str, dict[str, Any]] = {}
    for block in source_blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        records = by_translation.get(block_id, [])
        record = records[0] if records else {}
        page = block.get("page")
        page_key = str(page if page is not None else "global")
        window = page_windows.setdefault(
            page_key,
            {
                "window_id": f"page-{page_key}",
                "pages": [page],
                "source_block_count": 0,
                "translated_block_count": 0,
                "missing_block_ids": [],
                "duplicated_block_ids": [],
                "errored_block_ids": [],
            },
        )
        window["source_block_count"] += 1
        if records:
            window["translated_block_count"] += 1
        if not records:
            window["missing_block_ids"].append(block_id)
        if len(records) > 1:
            window["duplicated_block_ids"].append(block_id)
        if record and record.get("status") != "ok":
            window["errored_block_ids"].append(block_id)
        source_chars = len(str(block.get("text") or ""))
        translation_chars = sum(len(str(item.get("translation") or "")) for item in records)
        alignment_status = "aligned"
        if not records:
            alignment_status = "omitted"
        elif len(records) > 1:
            alignment_status = "one_to_many_or_duplicate"
        elif record.get("status") != "ok":
            alignment_status = "errored"
        elif "external_pdf_text_unaligned" in str(record.get("alignment_status") or ""):
            alignment_status = "unstable_external_pdf_text"
        mappings.append(
            {
                "block_id": block_id,
                "page": page,
                "section": block.get("section"),
                "element_type": block.get("element_type"),
                "source_chars": source_chars,
                "translation_chars": translation_chars,
                "translation_status": record.get("status") if record else "missing",
                "duplicate_count": seen.get(block_id, 0),
                "alignment_status": alignment_status,
                "coverage_ratio": round(translation_chars / max(source_chars, 1), 3) if records else 0,
                "translation_note": record.get("translation_note") if record else None,
            }
        )
    missing = [item["block_id"] for item in mappings if item["translation_status"] == "missing"]
    duplicated = [block_id for block_id, count in seen.items() if count > 1]
    errored = [str(record.get("block_id") or "") for record in translation_blocks if record.get("status") != "ok"]
    merged_records = [
        {
            "translation_block_id": str(record.get("block_id") or ""),
            "source_block_ids": record.get("source_block_ids"),
        }
        for record in translation_blocks
        if isinstance(record.get("source_block_ids"), list) and len(record.get("source_block_ids")) > 1
    ]
    window_items = []
    for item in page_windows.values():
        source_count = int(item.get("source_block_count") or 0)
        translated_count = int(item.get("translated_block_count") or 0)
        item["coverage_ratio"] = round(translated_count / max(source_count, 1), 3)
        item["status"] = "warn" if item["missing_block_ids"] or item["duplicated_block_ids"] or item["errored_block_ids"] else "ok"
        window_items.append(item)
    repeated_targets: dict[str, int] = {}
    for record in translation_blocks:
        translation = str(record.get("translation") or "").strip()
        if len(translation) >= 120:
            repeated_targets[translation] = repeated_targets.get(translation, 0) + 1
    repeated_full_text_count = sum(count for count in repeated_targets.values() if count >= 3)
    coverage_status = "warn" if missing or duplicated or errored or merged_records or unstable_evidence_records or repeated_full_text_count else "ok"
    return {
        "version": 1,
        "status": coverage_status,
        "method": "align_then_slide_block_window",
        "source_block_count": len(source_blocks),
        "translation_block_count": len(translation_blocks),
        "missing_block_ids": missing,
        "duplicated_block_ids": duplicated,
        "errored_block_ids": errored,
        "many_to_one_records": merged_records,
        "unstable_external_evidence_block_ids": sorted(set(unstable_evidence_records)),
        "repeated_full_text_translation_count": repeated_full_text_count,
        "window_count": len(window_items),
        "page_windows": sorted(window_items, key=lambda item: str(item.get("window_id"))),
        "coverage_summary": {
            "missing_count": len(missing),
            "duplicate_count": len(duplicated),
            "errored_count": len(errored),
            "many_to_one_count": len(merged_records),
            "unstable_external_evidence_count": len(set(unstable_evidence_records)),
            "repeated_full_text_translation_count": repeated_full_text_count,
        },
        "mappings": mappings,
    }

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
