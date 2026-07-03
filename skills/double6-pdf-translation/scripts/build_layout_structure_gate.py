#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


BACKMATTER_MARKERS = (
    "acknowledgements",
    "acknowledgments",
    "author contributions",
    "competing interests",
    "ethics approval",
    "informed consent",
    "additional information",
    "supplementary information",
    "correspondence and requests for materials",
    "reprints and permission information",
    "publisher's note",
    "publisher’s note",
    "this research was supported",
    "the authors declare no competing interests",
    "did not require ethical approval",
    "informed consent was therefore not required",
)


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def visual_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    return [item for item in findings if isinstance(item, dict)]


def add_issue(issues: list[dict[str, Any]], rule: str, severity: str, evidence: Any, recommendation: str) -> None:
    issues.append(
        {
            "rule": rule,
            "severity": severity,
            "evidence": evidence,
            "recommendation": recommendation,
        }
    )


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def has_backmatter_marker(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in BACKMATTER_MARKERS)


def toc_row_requires_page_number_group(item: dict[str, Any]) -> bool:
    role = str(item.get("layout_role") or item.get("layout_label") or "").lower()
    if role not in {"toc_entry", "chapter_index_entry"}:
        return False
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(item.get("input") or item.get("source_text") or item.get("pdf_unicode") or ""))).strip()
    if not text:
        return False
    if re.fullmatch(r"chapter\s+\d{1,2}", text, flags=re.I):
        return False
    if role == "chapter_index_entry" and not re.search(r"\s\d{1,3}$", text):
        return False
    return bool(re.search(r"\s\d{1,3}$", text))


def build_layout_structure_gate(
    *,
    layout_map: dict[str, Any] | None = None,
    pymupdf_audit: dict[str, Any] | None = None,
    poppler_audit: dict[str, Any] | None = None,
    visual_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = layout_map if isinstance(layout_map, dict) else {}
    audit = pymupdf_audit if isinstance(pymupdf_audit, dict) else {}
    poppler = poppler_audit if isinstance(poppler_audit, dict) else {}
    visual = visual_report if isinstance(visual_report, dict) else {}
    blocks = layout.get("blocks") if isinstance(layout.get("blocks"), list) else []
    issues: list[dict[str, Any]] = []

    coverage = float(layout.get("engine_block_coverage_ratio") or 0.0)
    label_coverage = float(layout.get("layout_label_coverage") or 0.0)
    if layout.get("layout_source") == "babeldoc_translate_tracking" and coverage < 0.8:
        add_issue(issues, "engine_block_coverage_low", "blocking", {"engine_block_coverage_ratio": coverage}, "BabelDOC tracking 存在时必须能建立稳定 engine block 覆盖。")
    if blocks and label_coverage < 0.6:
        add_issue(issues, "layout_label_coverage_low", "warn", {"layout_label_coverage": label_coverage}, "layout label 覆盖不足会降低目录、机构和页脚的角色化修复能力。")

    if int(audit.get("visible_text_not_tracked_count") or 0):
        add_issue(
            issues,
            "visible_text_not_tracked",
            "warn",
            {"count": audit.get("visible_text_not_tracked_count"), "samples": audit.get("visible_text_not_tracked", [])[:5]},
            "可见文本未进入 tracking 时，需修 paragraph finder 或生成合成 tracking item。",
        )
    poppler_status = str(poppler.get("status") or "")
    poppler_warning = None
    if poppler_status in {"skipped", "error"}:
        poppler_warning = {
            "rule": "poppler_text_bbox_audit_unavailable",
            "status": poppler.get("status"),
            "reason": poppler.get("reason"),
            "severity": "warn",
            "message": "Poppler bbox 旁路审计不可用，仅保留现有 PyMuPDF/visual gate 结论。",
        }
    pymupdf_rules = set()
    for finding in audit.get("findings", []) if isinstance(audit.get("findings"), list) else []:
        if isinstance(finding, dict):
            pymupdf_rules.add(str(finding.get("rule") or ""))
    if int(audit.get("tracking_translated_but_source_visible_count") or 0):
        pymupdf_rules.add("tracking_translated_but_source_visible")
    if int(audit.get("visible_text_not_tracked_count") or 0):
        pymupdf_rules.add("visible_text_not_tracked")
    poppler_findings = [item for item in poppler.get("findings", []) if isinstance(item, dict)] if isinstance(poppler.get("findings"), list) else []
    for finding in poppler_findings:
        rule = str(finding.get("rule") or "")
        if rule not in {
            "poppler_tracking_translated_but_source_visible",
            "poppler_visible_text_not_tracked",
            "poppler_toc_page_number_unpaired",
        }:
            continue
        severity = str(finding.get("severity") or "warn")
        if severity not in {"blocking", "warn"}:
            severity = "warn"
        cross_validated: list[str] = []
        equivalent_rule = rule.removeprefix("poppler_")
        if equivalent_rule in pymupdf_rules:
            cross_validated.append("pymupdf_layout_audit")
        evidence = {
            "finding": finding,
            "cross_validated_by": cross_validated,
            "evidence_source": finding.get("evidence_source") or "poppler_pdftotext_bbox_layout",
        }
        if not cross_validated and rule == "poppler_tracking_translated_but_source_visible":
            evidence["needs_local_verification"] = True
        add_issue(
            issues,
            rule,
            severity,
            evidence,
            str(finding.get("recommendation") or "按 Poppler bbox 旁路审计定位 page/region，并回到 BabelDOC writeback/paint 层修复。"),
        )
    if int(audit.get("tracking_translated_but_source_visible_count") or 0):
        add_issue(
            issues,
            "tracking_translated_but_source_visible",
            "blocking",
            {
                "count": audit.get("tracking_translated_but_source_visible_count"),
                "samples": audit.get("tracking_translated_but_source_visible", [])[:5],
            },
            "tracking 中已有中文输出但主 PDF 仍显示英文，修复点在 writeback/paint 或原文本清除。",
        )
    for finding in audit.get("findings", []) if isinstance(audit.get("findings"), list) else []:
        if not isinstance(finding, dict):
            continue
        rule = str(finding.get("rule") or "")
        if rule == "chart_axis_original_text_visible":
            add_issue(
                issues,
                "chart_axis_original_text_visible",
                "blocking",
                {"samples": finding.get("samples", [])[:5]},
                "旋转/竖排图表标签不能只在 tracking 中翻译，需替换原 glyph 或转入 chart region rerender。",
            )
    if audit.get("reading_order_risk"):
        add_issue(issues, "reading_order_risk", "warn", True, "阅读顺序风险需要进入 layout_mapping partial。")
    if audit.get("cross_block_merge_risk"):
        add_issue(issues, "cross_block_merge_risk", "warn", True, "跨块合并风险需要触发页级或结构级 rerender。")
    for issue in audit.get("cover_year_position_issues", []) if isinstance(audit.get("cover_year_position_issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        rule = str(issue.get("rule") or "cover_year_position_drift")
        add_issue(
            issues,
            rule,
            "blocking",
            issue,
            "AI Index 封面年份必须作为独立 cover_year item 保持原 bbox/方向，不能并入标题或位置漂移。",
        )
    if int(audit.get("numbered_list_merge_count") or 0):
        add_issue(
            issues,
            "numbered_list_merge",
            "blocking",
            {"count": audit.get("numbered_list_merge_count"), "samples": audit.get("numbered_list_merge", [])[:5]},
            "Nature 有序列表必须按编号拆分为独立 paragraph，不能合并成一段写回。",
        )
    toc_blocks = [
        item
        for item in blocks
        if str(item.get("layout_role") or item.get("layout_label") or "").lower()
        in {"toc_entry", "chapter_index_entry"}
    ]
    toc_blocks_requiring_group = [item for item in toc_blocks if toc_row_requires_page_number_group(item)]
    if toc_blocks_requiring_group and any(not item.get("toc_row_group") for item in toc_blocks_requiring_group):
        add_issue(
            issues,
            "toc_row_group_missing",
            "blocking",
            {
                "count": sum(1 for item in toc_blocks_requiring_group if not item.get("toc_row_group")),
                "samples": [item for item in toc_blocks_requiring_group if not item.get("toc_row_group")][:5],
            },
            "AI 目录/章节索引必须在 BabelDOC IL 层形成 row item，绑定 title bbox 与 page-number bbox，不能再后渲染覆盖。",
        )
    unpaired_page_numbers = [
        item
        for item in blocks
        if str(item.get("layout_role") or item.get("layout_label") or "").lower() == "toc_page_number"
    ]
    if unpaired_page_numbers or int(audit.get("toc_page_number_column_unpaired_count") or 0):
        add_issue(
            issues,
            "toc_page_number_column_unpaired",
            "blocking",
            {"count": len(unpaired_page_numbers) or audit.get("toc_page_number_column_unpaired_count"), "samples": unpaired_page_numbers[:5]},
            "页码列必须与对应标题 row 绑定；孤立页码不能作为普通段落翻译或写回。",
        )
    structured_failures = [
        item
        for item in blocks
        if str(item.get("writeback_status") or "").lower() == "structured_toc_writeback_failed"
    ]
    if structured_failures or int(audit.get("structured_toc_writeback_failed_count") or 0):
        add_issue(
            issues,
            "structured_toc_writeback_failed",
            "blocking",
            {"count": len(structured_failures) or audit.get("structured_toc_writeback_failed_count"), "samples": structured_failures[:5]},
            "结构化 TOC 原位写回失败时只能保持 strict partial 或重跑 BabelDOC structured writeback，不能生成白块/overlay 候选。",
        )
    if int(audit.get("footer_in_header_band_count") or 0):
        add_issue(
            issues,
            "footer_in_header_band",
            "blocking",
            {"count": audit.get("footer_in_header_band_count"), "samples": audit.get("footer_in_header_band", [])[:5]},
            "Nature 页脚文本在译后进入页眉 band，修复点是 metadata y-band role / XObject paint，不是视觉遮盖。",
        )
    if int(audit.get("metadata_yband_mismatch_count") or 0):
        add_issue(
            issues,
            "metadata_yband_mismatch",
            "blocking",
            {"count": audit.get("metadata_yband_mismatch_count"), "samples": audit.get("metadata_yband_mismatch", [])[:5]},
            "metadata 源 bbox 与译后可见 y-band 不一致，必须在 BabelDOC role/writeback 层整体处理。",
        )

    active_visual_findings = [
        item
        for item in visual_findings(visual)
        if str(item.get("severity") or "warn") in {"blocking", "warn"}
    ]
    rules = {str(item.get("rule") or ""): item for item in active_visual_findings}
    cause_categories: dict[str, list[dict[str, Any]]] = {}
    for finding in active_visual_findings:
        cause = str(finding.get("cause_category") or "")
        if cause == "typeset_reflow" and str(finding.get("rule") or "") == "heading_bold_style_drift":
            continue
        if cause:
            cause_categories.setdefault(cause, []).append(finding)
    for cause, severity, recommendation in [
        ("backend_role_classification", "blocking", "角色分类错误会导致人名、citation、页眉、签名、References、Example 或图表标题被错误翻译/透传。"),
        ("typeset_reflow", "blocking", "字号、换行、溢出或 bbox 问题应进入 typesetting/reflow 修复，不能只靠缩小字号。"),
        ("paint_composite", "blocking", "图像、背景、链接、下划线、横线或双语合成问题应检查 paint/composite 和 annotations。"),
        ("artifact_selection_report_drift", "blocking", "报告、manifest、gate 与最终交付 PDF 不一致时，必须先修 source-of-truth 漂移。"),
        ("needs_local_verification", "warn", "该用户视觉反馈需要截图和 PyMuPDF 文本层本地核验后再决定修复层。"),
    ]:
        if cause in cause_categories:
            add_issue(
                issues,
                f"cause_{cause}",
                severity,
                {"count": len(cause_categories[cause]), "samples": cause_categories[cause][:5]},
                recommendation,
            )
    for rule, severity, recommendation in [
        ("metadata_cluster_fragmented", "blocking", "Nature 页脚/机构/邮箱 metadata cluster 需整体保护或整体归一。"),
        ("contact_email_fragmented", "blocking", "邮箱和联系方式不能碎片化翻译或断裂。"),
        ("metadata_paint_mixed_language", "blocking", "metadata 不能局部中文、局部英文叠加；需整体 passthrough 或整体重绘。"),
        ("metadata_original_layer_unsuppressed", "blocking", "metadata 原文本层不能和中文回填同时可见；修 writeback/paint。"),
        ("toc_alignment_drift", "blocking", "目录行数量、顺序或页码列漂移时需目录页重排。"),
        ("chapter_index_merge", "blocking", "章节索引标题、续行和页码列必须分离渲染。"),
        ("toc_row_renderer_failed", "blocking", "目录/章节索引 renderer 失败时不能提交重叠主 PDF。"),
        ("role_font_floor_caused_overlap", "blocking", "字号下限导致 overlap 时必须转入局部/页级重排。"),
        ("heading_tiny_font", "blocking", "标题字号不能被压到正文/脚注级别；需按 heading role 重排。"),
        ("font_size_regression", "blocking", "译文字号相对原文明显退化时不能作为 strict ok。"),
        ("heading_bold_style_drift", "warn", "标题/加粗样式漂移需保留原 heading/bold 层级或标记人工修复。"),
        ("cover_year_position_drift", "blocking", "封面年份位置漂移时需修 cover_year bbox 或页级重排。"),
        ("cover_year_missing_from_translation", "blocking", "封面年份不能被标题吞掉或从可见译文消失。"),
        ("toc_line_count_dropped", "blocking", "目录子标题行数下降说明 row preservation 失败，需目录专用 renderer。"),
        ("table_caption_missing", "blocking", "Table 1/2 caption 不能从主 PDF 或 tracking 中消失。"),
        ("table_caption_untranslated", "blocking", "Table 1/2 caption 不能残留英文或被跳过。"),
        ("table_caption_writeback_failed", "blocking", "表格 caption tracking 已有但主 PDF 不可见时，需修 table region writeback。"),
        ("table_header_missing_from_il", "blocking", "表格 header 可见但未进 tracking 时，需生成 synthetic table_header item。"),
        ("table_header_writeback_failed", "blocking", "表格 header tracking 已有但主 PDF 仍英文时，修 table region writeback。"),
        ("table_region_rerender_required", "blocking", "caption/header/row label/数字单元格无法同区写回时，必须标记 table-region rerender。"),
        ("chart_label_writeback_failed", "blocking", "图表标签已有翻译路径但仍可见英文，需 region rerender 或原 glyph 替换。"),
        ("chart_label_coverage_low", "blocking", "图表标题/轴标题覆盖不足时需进入 chart region rerender。"),
        ("chart_axis_original_text_visible", "blocking", "旋转/竖排轴标签原英文仍可见，需 chart region rerender。"),
        ("chart_axis_label_malformed", "blocking", "坐标轴标签碎片化、过小或缺少完整轴标题时，需进入 chart region rerender。"),
        ("chart_title_missing", "blocking", "源页小节/图表标题不能在译文页消失；需修 chart_label/section heading writeback。"),
        ("protected_person_name_translation_drift", "blocking", "AI Index 人员名单、citation 和作者名应保留英文原样，不能大面积音译。"),
        ("person_name_passthrough_coverage_low", "blocking", "人员名单英文姓名保留率不足时，需回到 protected span / roster role policy 修复。"),
        ("person_name_translated_with_parenthetical_english", "blocking", "人员名单、作者和委员姓名默认保留英文原样，不能音译为中文名加括号英文。"),
        ("publisher_badge_background_drift", "blocking", "出版商 badge / UI 控件应整体保护；若需要翻译，也必须继承源区域渐变和图标背景。"),
        ("source_region_image_background_loss", "blocking", "图像型源区域背景被洗白或擦除时，需 source-region passthrough 或背景保持重绘。"),
        ("institution_label_untranslated", "warn", "机构标签应由实体策略整体翻译或明确保留。"),
    ]:
        if rule in rules:
            add_issue(issues, rule, severity, rules[rule], recommendation)

    joined_blocks = "\n".join(str(item.get("source_text") or item.get("input") or "") for item in blocks)
    translated_blocks = "\n".join(str(item.get("translated_text") or item.get("output") or "") for item in blocks)
    backmatter_blocks = [
        item
        for item in blocks
        if any(
            has_backmatter_marker(str(item.get(key) or ""))
            for key in ("source_text", "input", "translated_text", "output", "pdf_unicode")
        )
    ]
    backmatter_visibility = audit.get("backmatter_visibility") if isinstance(audit.get("backmatter_visibility"), dict) else {}
    backmatter_translated_visible = (
        str(backmatter_visibility.get("status") or "") == "translated_visible"
        and int(backmatter_visibility.get("english_marker_count") or 0) == 0
        and int(backmatter_visibility.get("cjk_marker_count") or 0) >= 3
    )
    untranslated_backmatter = [
        {
            "page": item.get("page"),
            "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
            "layout_role": item.get("layout_role") or item.get("layout_label"),
            "input": str(item.get("input") or item.get("source_text") or "")[:240],
            "output": str(item.get("output") or item.get("translated_text") or "")[:240],
        }
        for item in backmatter_blocks
        if has_backmatter_marker(str(item.get("output") or item.get("translated_text") or ""))
    ]
    if untranslated_backmatter and not backmatter_translated_visible:
        add_issue(
            issues,
            "backmatter_section_passthrough",
            "blocking",
            {"count": len(untranslated_backmatter), "samples": untranslated_backmatter[:5]},
            "Nature 致谢、作者贡献、利益冲突、伦理/知情同意、补充信息等 backmatter 不能按 footer passthrough 原样输出；需走 backmatter_section role direct output 后重跑后端。",
        )
    backmatter_writeback_failed = [
        {
            "page": item.get("page"),
            "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
            "layout_role": item.get("layout_role") or item.get("layout_label"),
            "output": str(item.get("output") or item.get("translated_text") or "")[:240],
            "pdf_unicode": str(item.get("pdf_unicode") or "")[:240],
        }
        for item in backmatter_blocks
        if has_backmatter_marker(str(item.get("pdf_unicode") or ""))
        and has_cjk(str(item.get("output") or item.get("translated_text") or ""))
    ]
    if backmatter_writeback_failed and not backmatter_translated_visible:
        add_issue(
            issues,
            "backmatter_section_writeback_failed",
            "blocking",
            {"count": len(backmatter_writeback_failed), "samples": backmatter_writeback_failed[:5]},
            "Nature backmatter tracking 已有中文输出但主 PDF 仍显示英文，修复点在 BabelDOC writeback/paint 或原文本清除，不能只靠 visible candidate。",
        )
    if re.search(r"\bGenerative AI\b", translated_blocks):
        add_issue(issues, "term_policy_unmet_generative_ai", "warn", "Generative AI", "Generative AI 应统一译为“生成式人工智能”。")
    if re.search(r"\bStanford University\b", translated_blocks):
        add_issue(issues, "entity_policy_unmet_stanford", "warn", "Stanford University", "Stanford University 应统一译为“斯坦福大学”。")
    if re.search(r"\bMachine translation \(MT\) refers to computerized systems", translated_blocks):
        add_issue(
            issues,
            "must_translate_source_machine_translation",
            "blocking",
            "Machine translation (MT) refers to computerized systems",
            "普通正文英文残留必须进入 item-level retry 或写回修复。",
        )
    if re.search(r"email:.*@|HUMANITIES AND SOCIAL SCIENCES COMMUNICATIONS", joined_blocks, flags=re.I):
        affiliation_blocks = [item for item in blocks if str(item.get("layout_role") or item.get("layout_label") or "").lower() == "affiliation_footer"]
        if not affiliation_blocks:
            add_issue(issues, "metadata_cluster_missing_affiliation_footer_role", "warn", "page footer metadata", "Nature 页脚 metadata 应标成 affiliation_footer 以便整体保护。")

    worst = "ok"
    if any(item.get("severity") == "blocking" for item in issues):
        worst = "blocking"
    elif issues:
        worst = "warn"
    warn_only_delivery_safe = (
        worst == "warn"
        and issues
        and all(item.get("rule") == "layout_label_coverage_low" for item in issues)
        and str(visual.get("status") or "") == "ok"
    )
    return {
        "version": 1,
        "status": "partial" if worst == "blocking" else "warn" if worst == "warn" else "ok",
        "worst_gate": worst,
        "issue_count": len(issues),
        "issues": issues,
        "warn_only_delivery_safe": warn_only_delivery_safe,
        "warn_only_delivery_safety": "only_layout_label_coverage_low_and_visual_qa_ok" if warn_only_delivery_safe else None,
        "inputs": {
            "layout_source": layout.get("layout_source"),
            "engine_block_coverage_ratio": layout.get("engine_block_coverage_ratio"),
            "layout_label_coverage": layout.get("layout_label_coverage"),
            "pymupdf_status": audit.get("status"),
            "visual_status": visual.get("status"),
            "poppler_status": poppler.get("status"),
            "poppler_warning": poppler_warning,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build PDF layout structure gate from layout map, PyMuPDF audit and visual report.")
    parser.add_argument("--layout-map", required=True)
    parser.add_argument("--pymupdf-audit")
    parser.add_argument("--poppler-audit")
    parser.add_argument("--visual-report")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_layout_structure_gate(
        layout_map=load_json(Path(args.layout_map)),
        pymupdf_audit=load_json(Path(args.pymupdf_audit)) if args.pymupdf_audit else {},
        poppler_audit=load_json(Path(args.poppler_audit)) if args.poppler_audit else {},
        visual_report=load_json(Path(args.visual_report)) if args.visual_report else {},
    )
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": payload.get("status")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
