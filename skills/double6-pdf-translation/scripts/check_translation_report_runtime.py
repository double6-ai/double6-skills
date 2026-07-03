#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by check_translation.py for render manifest checks and quality report assembly."

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_residue import *  # noqa: F401,F403

def check_translation_blocks(
    manifest: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
    *,
    render_manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    if not translation_blocks:
        return issues
    source_blocks = manifest.get("blocks")
    expected_ids = [str(item.get("block_id")) for item in source_blocks if isinstance(item, dict) and item.get("block_id")] if isinstance(source_blocks, list) else []
    seen: dict[str, int] = {}
    alignment_statuses = {str(record.get("alignment_status") or "") for record in translation_blocks if isinstance(record, dict)}
    seen_ids = {str(record.get("block_id") or "") for record in translation_blocks if isinstance(record, dict)}
    external_unaligned = any("unaligned" in status or "full_text" in status for status in alignment_statuses) or bool(
        seen_ids & {"document", "final-readable", "final_readable", "repaired-full-text"}
    )
    engine_bridge_ok = gate_status(render_manifest, "engine_block_bridge") == "ok"
    if expected_ids and external_unaligned and not (set(expected_ids) & seen_ids):
        if engine_bridge_ok:
            return []
        return [
            Issue(
                "medium",
                "分块桥接未建立",
                "译文来自 PDF 后端可复制文本或 QA 修复后的全文文本，translation_blocks 没有稳定对应 source_manifest 的 block_id；这应归因到 block_bridge 缺失，而不是直接判定正文漏译。",
                category="structure",
                block_id="document",
                suggestion="生成 block_bridge.json，并使用 layout/order/page 级桥接解释覆盖关系；若需要局部重译，再用 pdf_rerender_plan.json 指向可重渲染范围。",
            )
        ]
    external_alignment_pending = [
        record
        for record in translation_blocks
        if isinstance(record, dict)
        and str(record.get("status") or "") == "needs_block_alignment"
        and "external_pdf_text_unaligned" in str(record.get("alignment_status") or record.get("translation_note") or "")
    ]
    if external_alignment_pending:
        if not engine_bridge_ok:
            issues.append(
                Issue(
                    "medium",
                    "PDF direct 分块证据待桥接",
                    "translation_blocks 已明确标记为 needs_block_alignment，表示缺少 block-local target；该问题应归类为 traceability/block_bridge，不应作为可见译文漏译证据。",
                    category="structure",
                    block_id="document",
                    suggestion="补齐 block_bridge/layout_map 的 page/debug_id 映射；可见漏译另由 visual/report finding 和 PDF 文本层证据判断。",
                )
            )
    for record in translation_blocks:
        block_id = str(record.get("block_id") or "")
        if block_id:
            seen[block_id] = seen.get(block_id, 0) + 1
        if record in external_alignment_pending:
            continue
        if record.get("status") != "ok":
            issues.append(
                Issue(
                    "medium",
                    f"分块翻译状态异常: {block_id or '(unknown)'}",
                    f"translation_blocks 中该分块状态为 `{record.get('status')}`。",
                    category="omission",
                    block_id=block_id,
                    suggestion="重跑该分块或手动补译。",
                )
            )
    for block_id in expected_ids:
        if block_id not in seen:
            issues.append(
                Issue(
                    "medium",
                    f"分块译文缺失: {block_id}",
                    "source_manifest 中存在该 block，但 translation_blocks 中没有对应记录。",
                    category="omission",
                    block_id=block_id,
                    suggestion="补译该 block 并重新生成 translation_blocks.jsonl。",
                )
            )
        elif seen[block_id] > 1:
            issues.append(
                Issue(
                    "medium",
                    f"分块译文重复: {block_id}",
                    f"translation_blocks 中该 block 出现 {seen[block_id]} 次。",
                    category="addition",
                    block_id=block_id,
                    suggestion="去重后重新合并译文。",
                )
            )
    return issues


def check_render_manifest(render_manifest: dict[str, Any]) -> list[Issue]:
    if not render_manifest:
        return []
    issues: list[Issue] = []
    status = str(render_manifest.get("status") or "")
    if status and status != "ok":
        errors = render_manifest.get("errors")
        validation = render_manifest.get("validation") if isinstance(render_manifest.get("validation"), dict) else {}
        raw_gates = validation.get("gates")
        gates = raw_gates.get("gates") if isinstance(raw_gates, dict) else raw_gates if isinstance(raw_gates, list) else []
        gate_summary = [
            f"{gate.get('name')}={gate.get('status')}"
            for gate in gates
            if isinstance(gate, dict) and gate.get("status") in {"warn", "blocking"}
        ]
        has_pdf = bool((render_manifest.get("outputs") or {}).get("translated_pdf") or validation.get("has_translated_pdf"))
        if not (has_pdf and status != "error"):
            title = "PDF strict delivery gate 未通过" if has_pdf else "PDF 渲染后端失败"
            detail = (
                f"render_manifest 状态为 `{status}`，译文 PDF 已生成但 strict delivery gate 仍有风险："
                + ("；".join(gate_summary[:8]) if gate_summary else "未提供 gate 明细。")
                if has_pdf
                else f"render_manifest 显示 PDF 强路径状态为 `{status}`。"
            )
            issues.append(
                Issue(
                    "high",
                    title,
                    detail,
                    category="rendering",
                    source_evidence=json.dumps(errors, ensure_ascii=False) if isinstance(errors, list) else "",
                    suggestion="先区分 strict gate partial、visual semantic warn 与 backend_quality warn；只有缺少 PDF 或后端错误时才按渲染失败处理。",
                )
            )
    validation = render_manifest.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    if not validation.get("has_translated_pdf"):
        issues.append(
            Issue(
                "high",
                "缺少译文 PDF",
                "PDF 强路径未产生可定位的译文 PDF 输出。",
                category="rendering",
                suggestion="确认 PDFMathTranslate-next 输出目录和文件命名，并检查 render_manifest 的 all_pdf_outputs。",
            )
        )
    translated_text_chars = int(validation.get("translated_text_chars") or 0)
    cjk_char_count = int(validation.get("cjk_char_count") or 0)
    if validation and translated_text_chars == 0:
        issues.append(
            Issue(
                "high",
                "译文 PDF 缺少可抽取文本",
                "译文 PDF 未能抽取出可用于复查的文本，可能是渲染失败、字体缺字或输出 PDF 不可复制。",
                category="rendering",
                suggestion="用 PyMuPDF/pdftotext 复查译文 PDF；若为字体问题，修复 CJK 字体 fallback 后重新渲染。",
            )
        )
    elif translated_text_chars > 0 and cjk_char_count == 0:
        issues.append(
            Issue(
                "medium",
                "译文 PDF 缺少中文可复制文本",
                "译文 PDF 有可抽取文本，但未检测到 CJK 字符，可能仍是英文文本层或中文字体渲染异常。",
                category="rendering",
                suggestion="检查 PDFMathTranslate-next 输出模式、中文字体嵌入和文本层。",
            )
        )
    visual_report = render_manifest.get("visual_layout_report")
    if isinstance(visual_report, dict):
        visual_status = str(visual_report.get("status") or "")
        if visual_status == "warn":
            findings = visual_report.get("findings")
            issues.append(
                Issue(
                    "medium",
                    "PDF 视觉回归风险",
                    "视觉检查发现关键文本可见性、目录顺序、颜色对比或遮挡风险。",
                    category="rendering",
                    source_evidence=json.dumps(findings[:5], ensure_ascii=False) if isinstance(findings, list) else "",
                    suggestion="对照 visual_layout_report.json 的页级截图和 findings；必要时重渲染或提供可读 HTML/Markdown 降级交付。",
                )
            )
        elif visual_status == "unavailable":
            issues.append(
                Issue(
                    "low",
                    "PDF 视觉回归未执行",
                    "当前环境未能完成截图级视觉检查。",
                    category="rendering",
                    source_evidence=str(visual_report.get("reason") or ""),
                    suggestion="安装或修复 PyMuPDF 后重新运行视觉检查；文本 QA 结果仍可使用。",
                )
            )
    return issues


def collect_issues(
    source: str,
    translation: str,
    glossary: list[dict[str, str]],
    *,
    manifest: dict[str, Any] | None = None,
    protected_spans: dict[str, Any] | None = None,
    translation_blocks: list[dict[str, Any]] | None = None,
    render_manifest: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    effective_manifest = manifest or {}
    term_policy = build_term_policy(glossary, manifest=effective_manifest, source=source)
    entity_map = build_entity_map(effective_manifest, glossary)
    if translation and isinstance(effective_manifest, dict):
        current_gate = effective_manifest.get("coverage_gate")
        if not isinstance(current_gate, dict) or current_gate.get("intra_page_continuity", {}).get("status") == "not_checked":
            effective_manifest = {**effective_manifest, "coverage_gate": build_coverage_gate(effective_manifest, translation)}
    issues.extend(check_bad_acronym_translation_blocks(source, translation, translation_blocks or []))
    issues.extend(check_glossary_by_blocks(source, translation, glossary, translation_blocks or []))
    issues.extend(check_term_policy(source, translation, term_policy, manifest=effective_manifest))
    issues.extend(check_entity_map_policies(source, translation, entity_map, manifest=effective_manifest))
    issues.extend(
        check_untranslated_english(
            translation,
            protected_spans=protected_spans or {},
            entity_map=entity_map,
            term_policy=term_policy,
        )
    )
    issues.extend(check_sections(source, translation))
    issues.extend(check_block_faithfulness(source, translation, translation_blocks or []))
    issues.extend(check_source_coverage(effective_manifest))
    issues.extend(check_source_extraction_quality(effective_manifest))
    issues.extend(check_protected_spans(translation, protected_spans or {}, translation_blocks or []))
    issues.extend(check_translation_blocks(effective_manifest, translation_blocks or [], render_manifest=render_manifest or {}))
    issues.extend(check_render_manifest(render_manifest or {}))
    return enrich_issue_locations(issues, effective_manifest)


def render_quality_report(issues: list[Issue]) -> str:

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
