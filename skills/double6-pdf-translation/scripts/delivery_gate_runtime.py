#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import check_translation
import policy_utils
from pdf_translation_runtime import LATEX_REFLOW_LINE_WIDTH_CJK, latex_translation_after_writeback_repair

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py and latex_direct_runtime.py for delivery gates and LaTeX segment quality checks."

def strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        cut = len(raw_line)
        index = 0
        while index < len(raw_line):
            pos = raw_line.find("%", index)
            if pos < 0:
                break
            if pos > 0 and raw_line[pos - 1] == "\\":
                index = pos + 1
                continue
            cut = pos
            break
        lines.append(raw_line[:cut])
    return "\n".join(lines)

def latex_prose_for_line_estimate(text: str) -> str:
    cleaned = strip_latex_comments(text)
    cleaned = re.sub(r"\\(?:url|href)\{[^{}]*\}(?:\{[^{}]*\})?", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\\(?:cite|citep|citet|ref|label)\*?(?:\[[^\]]*\])?\{[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"(?<!\\)\$[^$\n]{0,240}(?<!\\)\$", " ", cleaned)
    cleaned = re.sub(r"\\\[[\s\S]*?\\\]", " ", cleaned)
    cleaned = re.sub(r"\\begin\{[^{}]*\}|\\end\{[^{}]*\}", " ", cleaned)
    for _ in range(3):
        cleaned = re.sub(
            r"\\(?:section|subsection|subsubsection|paragraph|caption|title|textbf|textit|emph|texttt)\*?\{([^{}]*)\}",
            r"\1",
            cleaned,
        )
    cleaned = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", cleaned)
    cleaned = re.sub(r"[{}]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()

def is_line_estimate_eligible(source: str, translation: str) -> bool:
    source_prose = latex_prose_for_line_estimate(source)
    translated_prose = latex_prose_for_line_estimate(translation)
    if len(source_prose) < 24 or len(translated_prose) < 8:
        return False
    return bool(re.search(r"[A-Za-z]{3,}|[\u4e00-\u9fff]", source_prose + translated_prose))

def cjk_width_units(text: str) -> float:
    width = 0.0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            width += 1.0
        elif char.isspace():
            width += 0.28
        elif char.isascii() and char.isalnum():
            width += 0.55
        elif char.isascii():
            width += 0.35
        else:
            width += 0.8
    return width

def estimated_column_lines(text: str, *, line_width: float = LATEX_REFLOW_LINE_WIDTH_CJK) -> int:
    prose = latex_prose_for_line_estimate(text)
    if not prose:
        return 0
    return max(1, int(math.ceil(cjk_width_units(prose) / line_width)))

def build_delivery_gates(
    *,
    visual_report: dict[str, Any],
    dual_visual_report: dict[str, Any] | None = None,
    backend_quality: dict[str, Any],
    rerender_candidates: dict[str, Any],
    translated_text: str,
    strict: bool,
    pipeline_status: str | None = None,
    has_translated_pdf: bool | None = None,
    latex_baseline_audit: dict[str, Any] | None = None,
    quality_report_text: str | None = None,
    pdf_rerender_plan: dict[str, Any] | None = None,
    pdf_direct_text_repair: dict[str, Any] | None = None,
    block_bridge: dict[str, Any] | None = None,
    pymupdf_layout_audit: dict[str, Any] | None = None,
    layout_structure_gate: dict[str, Any] | None = None,
    actual_render_source: str | None = None,
    latex_direct_quality_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []
    is_latex_direct = actual_render_source == "latex_direct"

    def add(name: str, status: str, evidence: str, recommendation: str) -> None:
        gates.append(
            {
                "name": name,
                "status": status,
                "evidence": evidence[:500],
                "recommendation": recommendation,
            }
        )

    pdf_text_cache: dict[str, str | None] = {}

    def primary_pdf_text() -> str | None:
        plan = pdf_rerender_plan if isinstance(pdf_rerender_plan, dict) else {}
        pdf_path = str(plan.get("primary_pdf") or "")
        if not pdf_path:
            return None
        if pdf_path in pdf_text_cache:
            return pdf_text_cache[pdf_path]
        try:
            import fitz  # type: ignore

            with fitz.open(pdf_path) as doc:  # type: ignore[attr-defined]
                text = "\n".join(page.get_text() or "" for page in doc)
        except Exception:
            text = None
        pdf_text_cache[pdf_path] = text
        return text

    def is_nonblocking_rerender_task(task: Any) -> bool:
        if not isinstance(task, dict):
            return False
        rule = str(task.get("rule") or "")
        if rule == "heading_bold_style_drift":
            return True
        category = str(task.get("category") or "")
        section = str(task.get("section") or "").lower()
        evidence_text = " ".join(
            str(task.get(key) or "")
            for key in ("source_evidence", "translation_evidence", "suggestion", "source_text")
        )
        if category in {"protected_span", "protected_span_readable_fallback_append"} and section == "references":
            return True
        if category == "rendering" and "heading_bold_style_drift" in evidence_text:
            return True
        if category in {"terminology", "policy_literal_replacement"}:
            text = primary_pdf_text()
            if text is None:
                return False
            if ("文本基础" in evidence_text or "textbase" in evidence_text) and "文本基础" not in text and "文本基模" not in text:
                return True
            if "translation profile" in evidence_text and "translation profile" not in text:
                return True
        return False

    if pipeline_status == "error":
        add("render_status", "blocking", "render_manifest.status=error", "渲染链路失败时不能把 strict delivery 标为通过。")
    elif pipeline_status == "partial" and strict:
        add("render_status", "blocking", "render_manifest.status=partial", "strict delivery / release 回放不能接受 partial 主渲染状态。")
    elif has_translated_pdf is False:
        add("render_status", "blocking", "no translated_pdf selected", "没有主 PDF 产物时不能把 strict delivery 标为通过。")
    else:
        add("render_status", "ok", f"render_manifest.status={pipeline_status or 'unknown'}", "无需额外动作。")

    visual_status = str(visual_report.get("status") or "")
    if visual_status == "unavailable" and strict:
        add(
            "visual_qa_available",
            "blocking",
            json.dumps({"status": visual_status, "reason": visual_report.get("reason")}, ensure_ascii=False),
            "严格诊断模式需要运行 visual_layout；安装 PyMuPDF/reportlab 后重跑。",
        )
    elif visual_status == "unavailable":
        add(
            "visual_qa_available",
            "warn",
            json.dumps({"status": visual_status, "reason": visual_report.get("reason")}, ensure_ascii=False),
            "visual_layout 不可用时仍可运行主翻译路径，但自动版式诊断会降级。",
        )
    else:
        add("visual_qa_available", "ok", f"visual_layout.status={visual_status or 'unknown'}", "无需额外动作。")

    visual_findings = visual_report.get("findings") if isinstance(visual_report.get("findings"), list) else []
    baseline_audit = latex_baseline_audit if isinstance(latex_baseline_audit, dict) else {}
    accepted_delta = baseline_audit.get("accepted_delta") if isinstance(baseline_audit.get("accepted_delta"), dict) else {}
    latex_page_delta_accepted = accepted_delta.get("status") == "accepted" and not accepted_delta.get("content_loss_evidence")
    if latex_page_delta_accepted:
        visual_findings = [
            {
                **item,
                "severity": "info",
                "accepted_delta": accepted_delta,
                "message": "LaTeX source 页数差异已由行数压缩估算解释，不作为 page drift blocker。",
            }
            if isinstance(item, dict) and str(item.get("rule") or "") in {"page_count_drift", "page_count_drift_full_pdf"}
            else item
            for item in visual_findings
        ]
    blocking_visual = [item for item in visual_findings if isinstance(item, dict) and item.get("severity") == "blocking"]
    nonblocking_warn_rules = {"heading_bold_style_drift"}
    warn_visual = [
        item
        for item in visual_findings
        if isinstance(item, dict)
        and item.get("severity") == "warn"
        and str(item.get("rule") or "") not in nonblocking_warn_rules
    ]
    if blocking_visual:
        add("visual_layout", "blocking", json.dumps(blocking_visual[:3], ensure_ascii=False), "主版式 PDF 存在阻断级视觉风险，必须重渲染或交付可读降级 PDF。")
    elif warn_visual:
        add("visual_layout", "warn", json.dumps(warn_visual[:3], ensure_ascii=False), "主版式 PDF 有视觉风险，评测模式下应视为 partial。")
    else:
        add("visual_layout", "ok", "no blocking visual finding", "无需额外动作。")

    def visual_rule_gate(name: str, rules: set[str], recommendation: str) -> None:
        matched = [item for item in visual_findings if isinstance(item, dict) and str(item.get("rule") or "") in rules]
        if not matched:
            add(name, "ok", "no banned pattern finding", "无需额外动作。")
            return
        critical_warn_rules = {
            "main_prose_tiny_font",
            "font_size_regression",
            "heading_tiny_font",
            "toc_alignment_drift",
            "toc_line_count_dropped",
            "toc_page_number_count_dropped",
            "toc_numeric_order_unstable",
            "toc_row_geometry_drift",
            "chart_label_untranslated",
            "chart_label_partial_translation",
            "chart_label_writeback_failed",
            "chart_axis_original_text_visible",
            "table_header_untranslated",
            "table_header_missing_from_il",
            "table_header_writeback_failed",
            "table_rule_loss",
            "cover_title_year_missing",
            "cover_year_missing_from_tracking",
            "cover_year_missing_from_translation",
            "cover_year_position_drift",
            "visible_style_tag_leak",
            "metadata_mixed_language",
            "metadata_paint_mixed_language",
            "metadata_original_layer_unsuppressed",
            "metadata_cluster_fragmented",
            "contact_email_fragmented",
            "footer_in_header_band",
            "metadata_yband_mismatch",
            "chapter_index_merge",
            "toc_row_renderer_failed",
            "body_prose_partial_direct_output",
            "person_name_translated_with_parenthetical_english",
            "role_font_floor_caused_overlap",
            "footnote_tiny_or_orphan_glyph",
        }
        critical_matched = [
            item
            for item in matched
            if item.get("severity") in {"blocking", "warn"} and str(item.get("rule") or "") in critical_warn_rules
        ]
        if any(item.get("severity") == "blocking" for item in matched) or critical_matched:
            status = "blocking"
        elif any(item.get("severity") == "warn" for item in matched):
            status = "warn"
        else:
            status = "ok"
        info_recommendation = "仅为诊断信息，不阻断 LaTeX source 主路径交付。" if status == "ok" else recommendation
        add(name, status, json.dumps(matched[:3], ensure_ascii=False), info_recommendation)

    visual_rule_gate("no_text_overlap", {"text_overlap"}, "禁止文本块重叠；需定位 bbox/字号/段落拆分并重渲染。")
    visual_rule_gate("font_floor_overlap", {"role_font_floor_caused_overlap"}, "字号下限放大后不能产生重叠；需转入局部/页级重渲染。")
    visual_rule_gate(
        "no_unexplained_page_drift",
        {"page_count_drift", "page_count_drift_full_pdf"},
        "禁止无解释页数漂移；需对照源 PDF、历史参考或 manifest 解释差异。",
    )
    visual_rule_gate(
        "no_visible_latex_commands",
        {"visible_latex_command"},
        "禁止 LaTeX 结构命令作为可见正文；需清理 TeX 翻译输出或重跑 LaTeX direct。",
    )
    visual_rule_gate("no_bbox_overflow", {"bbox_overflow"}, "禁止译文 bbox 越界；需调整排版、拆分文本或局部重渲染。")
    visual_rule_gate("no_main_prose_tiny_font", {"main_prose_tiny_font"}, "禁止主文极小字号硬塞；需降低文本密度或重排主文。")
    visual_rule_gate("no_font_size_regression", {"font_size_regression"}, "禁止翻译后字号明显退化；需重排文本而不是硬塞进原 bbox。")
    visual_rule_gate("heading_font_readability", {"heading_tiny_font"}, "章节标题不能被压成极小字号；需按 heading role 重新回流。")
    visual_rule_gate("visible_style_tags", {"visible_style_tag_leak"}, "禁止 rich-text placeholder 标签作为可见文本写入主 PDF；需阻断该 item 写回并重试。")
    visual_rule_gate(
        "toc_alignment",
        {"toc_alignment_drift", "toc_line_count_dropped", "toc_page_number_count_dropped", "toc_numeric_order_unstable"},
        "目录标题与页码列不能漂移、合并、丢行或乱序；需局部重渲染目录页。",
    )
    visual_rule_gate(
        "toc_row_geometry",
        {"toc_row_geometry_drift", "chapter_index_merge", "toc_row_renderer_failed", "toc_line_count_dropped", "toc_page_number_count_dropped"},
        "目录/章节索引行应保持标题列和页码列分离，不能合并为长行。",
    )
    visual_rule_gate("table_rules", {"table_rule_loss"}, "表格线不能退化成短下划线；需保留表格结构或走可读表格重排。")
    visual_rule_gate(
        "table_headers",
        {
            "table_header_untranslated",
            "table_header_missing_from_il",
            "table_header_writeback_failed",
            "table_caption_missing",
            "table_caption_untranslated",
            "table_caption_writeback_failed",
            "table_region_rerender_required",
        },
        "表格 caption/header/row label 不能消失或残留英文；需进入 table role 翻译并写回。",
    )
    visual_rule_gate("chart_labels", {"chart_label_untranslated", "chart_label_partial_translation", "chart_label_writeback_failed", "chart_axis_original_text_visible"}, "图表标题、轴标签、国家名和脚注 marker 必须整体翻译，不能局部残留英文。")
    visual_rule_gate(
        "cover_year_tracking",
        {"cover_year_missing_from_tracking", "cover_title_year_missing", "cover_year_missing_from_translation", "cover_year_position_drift"},
        "AI Index 封面年份必须进入 cover_year tracking 并写回主 PDF。",
    )
    visual_rule_gate("header_footer_integrity", {"header_footer_fragmented"}, "页眉页脚、邮箱和机构脚注不能碎片化；需保护或整体归一。")
    visual_rule_gate(
        "metadata_integrity",
        {
            "metadata_mixed_language",
            "metadata_paint_mixed_language",
            "metadata_original_layer_unsuppressed",
            "contact_email_fragmented",
            "metadata_cluster_fragmented",
            "footer_in_header_band",
            "metadata_yband_mismatch",
        },
        "页眉页脚、DOI、邮箱和联系信息不能中英混排、断裂或漂移到错误 y-band。",
    )
    visual_rule_gate("body_prose_direct_output", {"body_prose_partial_direct_output"}, "普通正文不能只做短标签局部替换；需完整翻译或阻断写回。")
    visual_rule_gate(
        "person_name_passthrough",
        {"protected_person_name_translation_drift", "person_name_passthrough_coverage_low", "person_name_translated_with_parenthetical_english"},
        "人员名单、作者和委员姓名默认保留英文；不能音译为中文名加括号英文。",
    )
    visual_rule_gate("footnote_readability", {"footnote_tiny_or_orphan_glyph"}, "脚注编号和说明不能产生孤立 glyph 或极小字号硬塞。")

    dual_report = dual_visual_report if isinstance(dual_visual_report, dict) else {}
    dual_findings = dual_report.get("findings") if isinstance(dual_report.get("findings"), list) else []
    delivery_dual_blocking = [
        item
        for item in dual_findings
        if isinstance(item, dict) and item.get("delivery_blocking") and item.get("severity") == "blocking"
    ]
    delivery_dual_warn = [
        item
        for item in dual_findings
        if isinstance(item, dict) and item.get("delivery_blocking") and item.get("severity") == "warn"
    ]
    if delivery_dual_blocking:
        add("dual_visual", "blocking", json.dumps(delivery_dual_blocking[:3], ensure_ascii=False), "标准双语 PDF 存在中文侧空白或英文侧背景漂移，不能作为合格双语交付。")
    elif delivery_dual_warn:
        add("dual_visual", "warn", json.dumps(delivery_dual_warn[:3], ensure_ascii=False), "标准双语 PDF 有轻度视觉风险，需抽样复查。")
    else:
        add("dual_visual", "ok", "standard dual delivery has no blocking dual-side finding", "无需额外动作。")

    latex_gate = latex_direct_quality_gate if isinstance(latex_direct_quality_gate, dict) else {}
    if is_latex_direct:
        latex_gate_status = str(latex_gate.get("status") or "missing")
        if latex_gate_status in {"ok", "pass"}:
            add("latex_direct_quality_gate", "ok", "latex_direct_quality_gate.status=ok", "无需额外动作。")
        elif latex_gate_status in {"warn"}:
            add("latex_direct_quality_gate", "warn", json.dumps(latex_gate.get("issues", [])[:5], ensure_ascii=False), "LaTeX direct 质量门存在风险，需抽样复核。")
        else:
            add("latex_direct_quality_gate", "blocking", json.dumps(latex_gate.get("issues", [])[:5], ensure_ascii=False), "LaTeX direct 质量门未通过时不能标为 strict ok。")
        add("backend_quality", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF backend retry/fallback 质量门阻断交付。")
    elif backend_quality.get("status") == "partial":
        add("backend_quality", "blocking", json.dumps(backend_quality, ensure_ascii=False), "后端 fallback 或 JSON 错误过高，需重跑 full pipeline。")
    elif backend_quality.get("status") == "warn":
        add("backend_quality", "warn", json.dumps(backend_quality, ensure_ascii=False), "后端存在 fallback 或 JSON 错误，需抽样复查。")
    else:
        add("backend_quality", "ok", json.dumps(backend_quality, ensure_ascii=False), "无需额外动作。")

    if not is_latex_direct and int(backend_quality.get("tracking_incomplete_count") or 0):
        add(
            "tracking_incomplete",
            "blocking",
            json.dumps(
                {
                    "tracking_mapping_status": backend_quality.get("tracking_mapping_status"),
                    "tracking_incomplete_count": backend_quality.get("tracking_incomplete_count"),
                },
                ensure_ascii=False,
            ),
            "backend retry/visual finding 必须能回溯 page、debug_id 和 layout_role；缺失时不能标为 strict 通过。",
        )

    bridge = block_bridge if isinstance(block_bridge, dict) else {}
    if is_latex_direct:
        add("engine_block_bridge", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径以 source segment / LaTeX quality gate 追踪，不使用 PDF backend engine block bridge 阻断。")
    elif bridge:
        bridge_status = str(bridge.get("status") or "")
        coverage = bridge.get("engine_block_coverage_ratio")
        if bridge_status in {"partial", "empty"}:
            add(
                "engine_block_bridge",
                "blocking",
                json.dumps(
                    {
                        "status": bridge_status,
                        "engine_block_coverage_ratio": coverage,
                        "unmatched_source_block_count": bridge.get("unmatched_source_block_count"),
                        "unmatched_engine_block_count": bridge.get("unmatched_engine_block_count"),
                    },
                    ensure_ascii=False,
                ),
                "BabelDOC tracking 存在时必须提供可追踪 engine block 映射；缺失时不能把 layout_mapping 标为完全通过。",
            )
        elif bridge_status == "order_only":
            add("engine_block_bridge", "ok", "bridge_status=order_only", "当前只能页/顺序级桥接；作为诊断保留，不在视觉/结构 gate 已通过时降低主交付状态。")
        else:
            add("engine_block_bridge", "ok", f"engine_block_coverage_ratio={coverage}", "无需额外动作。")

    pymupdf_audit = pymupdf_layout_audit if isinstance(pymupdf_layout_audit, dict) else {}
    if is_latex_direct:
        add("pymupdf_writeback_audit", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF backend tracking_translated_but_source_visible 阻断。")
    elif pymupdf_audit:
        if int(pymupdf_audit.get("tracking_translated_but_source_visible_count") or 0):
            add(
                "pymupdf_writeback_audit",
                "blocking",
                json.dumps(
                    {
                        "tracking_translated_but_source_visible_count": pymupdf_audit.get("tracking_translated_but_source_visible_count"),
                        "samples": pymupdf_audit.get("tracking_translated_but_source_visible", [])[:3],
                    },
                    ensure_ascii=False,
                ),
                "tracking 中已有中文输出但主 PDF 仍显示英文，修复点在 writeback/paint 或原文本清除。",
            )
        elif int(pymupdf_audit.get("visible_text_not_tracked_count") or 0):
            if pymupdf_audit.get("visible_text_not_tracked_delivery_safe"):
                add(
                    "pymupdf_visible_text_audit",
                    "ok",
                    json.dumps(
                        {
                            "visible_text_not_tracked_count": pymupdf_audit.get("visible_text_not_tracked_count"),
                            "delivery_safety": pymupdf_audit.get("visible_text_not_tracked_delivery_safety"),
                        },
                        ensure_ascii=False,
                    ),
                    "可见文本未进入 tracking 的 warn 已由视觉模型复核为不影响当前交付；后端 sink-down 仍作为诊断保留。",
                )
            else:
                add(
                    "pymupdf_visible_text_audit",
                    "warn",
                    json.dumps(
                        {
                            "visible_text_not_tracked_count": pymupdf_audit.get("visible_text_not_tracked_count"),
                            "reading_order_risk": pymupdf_audit.get("reading_order_risk"),
                            "cross_block_merge_risk": pymupdf_audit.get("cross_block_merge_risk"),
                        },
                        ensure_ascii=False,
                    ),
                    "PyMuPDF 发现可见文本未进入 BabelDOC tracking；需修 paragraph finder 或生成合成 tracking item。",
                )
        elif pymupdf_audit.get("status") == "unavailable":
            add("pymupdf_visible_text_audit", "warn", str(pymupdf_audit.get("reason") or "unavailable"), "旁路审计不可用时需人工抽样复查。")
        else:
            add("pymupdf_visible_text_audit", "ok", "visible text covered by tracking", "无需额外动作。")

    structure_gate = layout_structure_gate if isinstance(layout_structure_gate, dict) else {}
    if is_latex_direct:
        add("layout_structure_gate", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF backend layout_structure_gate 阻断；视觉 finding 仍由 visual_layout gate 覆盖。")
    elif structure_gate:
        issues = structure_gate.get("issues") if isinstance(structure_gate.get("issues"), list) else []
        nonblocking_structure_warn_rules = {"layout_label_coverage_low", "heading_bold_style_drift"}
        blocking_structure_issues = [
            item
            for item in issues
            if isinstance(item, dict)
            and (
                item.get("severity") == "blocking"
                or str(item.get("rule") or "") not in nonblocking_structure_warn_rules
            )
        ]
        if structure_gate.get("status") == "partial" or any(isinstance(item, dict) and item.get("severity") == "blocking" for item in issues):
            add("layout_structure_gate", "blocking", json.dumps(issues[:5], ensure_ascii=False), "结构质量门存在阻断项，必须局部重排、重译或保持 partial。")
        elif structure_gate.get("status") == "warn" and not blocking_structure_issues:
            add(
                "layout_structure_gate",
                "ok",
                json.dumps(
                    {
                        "status": "warn",
                        "ignored_warn_rules": sorted(nonblocking_structure_warn_rules),
                        "issue_count": structure_gate.get("issue_count"),
                    },
                    ensure_ascii=False,
                ),
                "结构质量门仅剩非阻断诊断项，不影响主 PDF 交付。",
            )
        elif structure_gate.get("status") == "warn":
            if structure_gate.get("warn_only_delivery_safe"):
                add(
                    "layout_structure_gate",
                    "ok",
                    json.dumps(
                        {
                            "status": "warn",
                            "issue_count": structure_gate.get("issue_count"),
                            "delivery_safety": structure_gate.get("warn_only_delivery_safety"),
                        },
                        ensure_ascii=False,
                    ),
                    "结构质量门仅剩 warn，且当前交付页已由视觉模型复核无字体、字号、背景块、遮挡或溢出问题；后端 tracking 待办保留为诊断。",
                )
            else:
                add("layout_structure_gate", "warn", json.dumps(issues[:5], ensure_ascii=False), "结构质量门存在风险，需抽样复查。")
        else:
            add("layout_structure_gate", "ok", "structure gate ok", "无需额外动作。")

    repair_manifest = pdf_direct_text_repair if isinstance(pdf_direct_text_repair, dict) else {}
    repair_status = str(repair_manifest.get("status") or "")
    repair_items = repair_manifest.get("repairs") if isinstance(repair_manifest.get("repairs"), list) else []
    if is_latex_direct:
        add("pdf_direct_text_repair", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF direct text repair manifest 阻断。")
    elif repair_status == "repaired" and repair_items:
        if pdf_direct_text_repair_delivery_safe(repair_manifest):
            add(
                "pdf_direct_text_repair",
                "ok",
                json.dumps(
                    {
                        "status": repair_status,
                        "repair_count": len(repair_items),
                        "delivery_safety": repair_manifest.get("delivery_safety"),
                    },
                    ensure_ascii=False,
                ),
                "PDF direct text repair 已有显式视觉复核接受证据；继续保留 repair manifest 作为交付边界证据。",
            )
        else:
            add(
                "no_white_redaction_overlay_in_delivery",
                "blocking",
                json.dumps({"status": repair_status, "repairs": repair_items[:5]}, ensure_ascii=False),
                "PDF direct text repair 已原地覆盖主 PDF，存在白底块状背景风险；需改为后端重渲染或独立诊断产物。",
            )
            add(
                "white_redaction_block",
                "blocking",
                json.dumps({"status": repair_status, "repairs": repair_items[:5]}, ensure_ascii=False),
                "主交付 PDF 命中过原地 redaction/overlay 风险，按白色块状背景污染处理。",
            )
    elif repair_status == "needs_rerender" and repair_items:
        add(
            "pdf_direct_text_repair_requires_rerender",
            "blocking",
            json.dumps({"status": repair_status, "repairs": repair_items[:5]}, ensure_ascii=False),
            "PDF direct text repair 仅记录为重渲染候选，主 PDF 还没有真实修复；必须后端重渲染或保持 diagnostic/partial。",
        )
    else:
        add("pdf_direct_text_repair", "ok", repair_status or "no repair manifest", "无需额外动作。")

    quality_text = quality_report_text or ""
    quality_failed = bool(re.search(r"状态：`?fail`?|status[:：]\s*fail", quality_text, flags=re.I))
    high_medium_hits = len(re.findall(r"\b(?:high|medium)\b|高风险|中风险", quality_text, flags=re.I))
    if is_latex_direct and str(latex_gate.get("status") or "") == "ok":
        add("quality_report", "ok", "latex_direct_quality_gate.status=ok", "LaTeX 主路径以 latex_direct_quality_gate 为质量事实源。")
    elif quality_failed:
        add(
            "quality_report",
            "blocking" if high_medium_hits >= 1 else "warn",
            f"quality_report indicates fail; high_or_medium_markers={high_medium_hits}",
            "quality_report 未通过时 strict delivery 必须降级，直到对应修复进入主 PDF 或明确降权。",
        )
    else:
        add("quality_report", "ok", "quality_report not failing", "无需额外动作。")

    plan = pdf_rerender_plan if isinstance(pdf_rerender_plan, dict) else {}
    plan_status = str(plan.get("status") or "")
    plan_tasks_raw = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    visual_tasks_raw = plan.get("visual_page_rerender_candidates") if isinstance(plan.get("visual_page_rerender_candidates"), list) else []
    plan_tasks = [
        task
        for task in plan_tasks_raw
        if not is_nonblocking_rerender_task(task)
    ]
    visual_tasks = [
        task
        for task in visual_tasks_raw
        if not is_nonblocking_rerender_task(task)
    ]
    task_count = len(plan_tasks) + len(visual_tasks)
    only_nonblocking_tasks = bool(plan_tasks_raw or visual_tasks_raw) and not task_count
    if is_latex_direct:
        add("pdf_rerender_plan", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF rerender plan 阻断；需看 latex_segment_repair_plan。")
    elif plan_status in {"needs_rerender", "partial", "blocking"} or task_count:
        add(
            "pdf_rerender_plan",
            "blocking",
            json.dumps({"status": plan_status, "task_count": task_count, "sample": (plan_tasks + visual_tasks)[:3]}, ensure_ascii=False),
            "pdf_rerender_plan 存在待重渲染任务时，主 PDF 不能标记为已修复或完全通过。",
        )
    elif only_nonblocking_tasks:
        add("pdf_rerender_plan", "ok", "only_nonblocking_heading_style_warn_tasks", "标题加粗样式 warning 不作为 release 阻断。")
    else:
        add("pdf_rerender_plan", "ok", plan_status or "no rerender task", "无需额外动作。")

    baseline_pdf = baseline_audit.get("baseline_pdf") if isinstance(baseline_audit.get("baseline_pdf"), dict) else {}
    current_pdf = baseline_audit.get("current_pdf") if isinstance(baseline_audit.get("current_pdf"), dict) else {}
    if baseline_pdf.get("exists") and current_pdf.get("exists"):
        baseline_pages = baseline_pdf.get("page_count")
        current_pages = current_pdf.get("page_count")
        if baseline_pages is not None and current_pages is not None and baseline_pages != current_pages:
            accepted = accepted_delta.get("status") == "accepted" and not accepted_delta.get("content_loss_evidence")
            evidence = {
                "baseline_pdf": baseline_pdf.get("path"),
                "current_pdf": current_pdf.get("path"),
                "baseline_page_count": baseline_pages,
                "current_page_count": current_pages,
                "accepted_delta": accepted_delta,
            }
            if accepted:
                add(
                    "latex_baseline_page_count",
                    "ok",
                    json.dumps(evidence, ensure_ascii=False),
                    "LaTeX 主 PDF 页数差异已有明确 accepted_delta，且无内容丢失证据。",
                )
            else:
                add(
                    "latex_baseline_page_count",
                    "blocking",
                    json.dumps(evidence, ensure_ascii=False),
                    "LaTeX 主 PDF 与历史最佳参考页数不一致；需先复核 line_reflow_estimate、latex_reflow_plan 或内容覆盖差异。",
                )
        else:
            add("latex_baseline_page_count", "ok", f"page_count={current_pages}", "LaTeX 主 PDF 页数与历史参考一致。")
        page_content_drift = baseline_audit.get("page_content_drift") if isinstance(baseline_audit.get("page_content_drift"), dict) else {}
        drift_findings = page_content_drift.get("findings") if isinstance(page_content_drift.get("findings"), list) else []
        active_drift_findings = [
            item for item in drift_findings if isinstance(item, dict) and item.get("severity") in {"blocking", "warn"}
        ]
        if active_drift_findings:
            add(
                "latex_baseline_page_content_drift",
                "warn",
                json.dumps(active_drift_findings[:3], ensure_ascii=False),
                "LaTeX 主 PDF 与历史参考同页内容分布差异较大；需复核 float 位置、分页和 include graph，而不只看页数压缩。",
            )
        elif page_content_drift:
            add("latex_baseline_page_content_drift", "ok", json.dumps(page_content_drift, ensure_ascii=False), "LaTeX 主 PDF 同页内容分布未发现明显漂移。")

    candidates = rerender_candidates.get("candidates") if isinstance(rerender_candidates.get("candidates"), list) else []
    if is_latex_direct:
        candidates = [
            item
            for item in candidates
            if isinstance(item, dict) and str(item.get("layer") or "") == "pdf_rendering"
        ]
    blocking_candidates = [item for item in candidates if isinstance(item, dict) and item.get("severity") == "blocking"]
    forbidden_candidates = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("rule") in {"forbidden_terminology_translation", "missing_protected_span"}
    ]
    protected_span_candidates = [item for item in candidates if isinstance(item, dict) and item.get("rule") == "missing_protected_span"]
    if protected_span_candidates:
        status = "blocking" if any(item.get("severity") == "blocking" for item in protected_span_candidates) else "warn"
        add("no_protected_span_loss", status, json.dumps(protected_span_candidates[:5], ensure_ascii=False), "禁止 protected span 缺失；需恢复引用、公式、URL、DOI 或代码后重跑。")
    else:
        add("no_protected_span_loss", "ok", "no missing protected span candidate", "无需额外动作。")
    if blocking_candidates:
        add("rerender_candidates", "blocking", json.dumps(blocking_candidates[:5], ensure_ascii=False), "重跑候选中存在 blocking 问题，主版式 PDF 不能标记为合格。")
    elif forbidden_candidates:
        add("rerender_candidates", "ok", json.dumps(forbidden_candidates[:5], ensure_ascii=False), "仅剩术语一致性候选，作为诊断保留；无 protected span 丢失或视觉阻断时不降低主交付状态。")
    else:
        add("rerender_candidates", "ok", "no blocking rerender candidate", "无需额外动作。")

    cjk_count = len([char for char in translated_text if "\u4e00" <= char <= "\u9fff"])
    if translated_text and cjk_count <= 0:
        add("text_layer", "blocking", "translated PDF has no extractable CJK text", "主 PDF 文本层疑似不可复制或乱码，需重渲染。")
    else:
        add("text_layer", "ok", f"cjk_char_count={cjk_count}", "无需额外动作。")

    status_order = {"ok": 0, "warn": 1, "blocking": 2}
    worst = max((gate["status"] for gate in gates), key=lambda value: status_order.get(value, 0), default="ok")
    delivery_status = "partial" if worst == "blocking" or (strict and worst == "warn") else "ok"
    return {
        "version": 1,
        "status": delivery_status,
        "strict": strict,
        "worst_gate": worst,
        "gates": gates,
    }

def build_fast_full_translation_draft_gates(
    *,
    pipeline_status: str,
    has_translated_pdf: bool,
    bilingual_manifest: dict[str, Any],
    backend_quality: dict[str, Any],
    previous_gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fast long-report mode: gate only basic generation, not strict visual/semantic acceptance."""

    gates: list[dict[str, Any]] = []

    def add(name: str, status: str, evidence: str, recommendation: str) -> None:
        gates.append({"name": name, "status": status, "evidence": evidence, "recommendation": recommendation})

    add(
        "render_process",
        "ok" if pipeline_status != "error" else "blocking",
        f"pipeline_status={pipeline_status}",
        "fast draft 仍要求翻译流程不能 error。",
    )
    add(
        "translated_pdf",
        "ok" if has_translated_pdf else "blocking",
        f"has_translated_pdf={has_translated_pdf}",
        "fast draft 仍要求生成单语中文 PDF。",
    )
    add(
        "standard_bilingual_pdf",
        "ok" if bilingual_manifest.get("status") == "ok" and bilingual_manifest.get("output_pdf") else "blocking",
        json.dumps(
            {
                "status": bilingual_manifest.get("status"),
                "output_pdf": bilingual_manifest.get("output_pdf"),
                "page_count": bilingual_manifest.get("page_count"),
            },
            ensure_ascii=False,
        ),
        "fast draft 仍要求生成英文左/中文右双语 PDF。",
    )
    backend_status = str(backend_quality.get("status") or "unknown")
    add(
        "backend_quality",
        "warn" if backend_status == "partial" else "ok",
        json.dumps(
            {
                "status": backend_quality.get("status"),
                "fallback_ratio": backend_quality.get("fallback_ratio"),
                "blocking_failure_count": backend_quality.get("blocking_failure_count"),
            },
            ensure_ascii=False,
        ),
        "fast draft 将 backend partial 记录为已知风险，不因 strict visual/semantic rerender candidates 阻断整本草稿。",
    )
    add(
        "strict_visual_semantic_acceptance",
        "skipped",
        "skip_visual_eval requested; strict visual acceptance was not run",
        "这是 fast_full_translation_draft，不是逐页 strict visual accepted 版本。",
    )
    if previous_gates:
        add(
            "strict_gate_evidence_retained",
            "skipped",
            f"previous_gate_status={previous_gates.get('status')}; previous_worst_gate={previous_gates.get('worst_gate')}",
            "原 strict/rerender 候选仍保存在 manifest/rerender_candidates 中，供后续定点修复使用。",
        )

    blocking = [gate for gate in gates if gate["status"] == "blocking"]
    return {
        "version": 1,
        "status": "partial" if blocking else "ok",
        "strict": False,
        "mode": "fast_full_translation_draft",
        "worst_gate": "blocking" if blocking else "ok",
        "gates": gates,
    }

def build_latex_direct_quality_gate(
    *,
    source_segments: list[dict[str, Any]],
    latex_baseline_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    command_inventory: list[dict[str, Any]] = []
    segment_completeness_rows: list[dict[str, Any]] = []
    paragraph_structure_rows: list[dict[str, Any]] = []
    auto_repairs: list[dict[str, Any]] = []

    def add(rule: str, severity: str, segment_id: str, evidence: str, repair_type: str) -> None:
        issues.append(
            {
                "rule": rule,
                "severity": severity,
                "segment_id": segment_id,
                "evidence": evidence[:500],
                "repair_type": repair_type,
            }
        )

    def latex_command_inventory(source: str, translation: str) -> dict[str, Any]:
        command_patterns = {
            "cite": r"\\cite\w*\*?(?:\[[^\]]*\])?\{[^{}]*\}",
            "ref": r"\\(?:ref|autoref|cref|Cref)\*?\{[^{}]*\}",
            "label": r"\\label\{[^{}]*\}",
            "url": r"\\url\{[^{}]*\}",
            "href": r"\\href\{[^{}]*\}\{[^{}]*\}",
            "caption": r"\\caption(?:\[[^\]]*\])?\{",
            "begin_env": r"\\begin\{[^{}]*\}",
            "end_env": r"\\end\{[^{}]*\}",
        }
        rows = []
        missing = []
        for command_type, pattern in command_patterns.items():
            source_items = re.findall(pattern, source)
            translation_items = re.findall(pattern, translation)
            source_norm = [re.sub(r"\s+", "", item) for item in source_items]
            translation_norm = [re.sub(r"\s+", "", item) for item in translation_items]
            for item in source_norm:
                if item not in translation_norm:
                    missing.append({"command_type": command_type, "command": item})
            rows.append(
                {
                    "command_type": command_type,
                    "source_count": len(source_items),
                    "translation_count": len(translation_items),
                    "missing_count": sum(1 for item in missing if item["command_type"] == command_type),
                }
            )
        return {
            "source_command_count": sum(item["source_count"] for item in rows),
            "translation_command_count": sum(item["translation_count"] for item in rows),
            "missing_command_count": len(missing),
            "by_type": rows,
            "missing_commands": missing,
        }

    def latex_residue_buckets(source: str, translation: str) -> dict[str, list[str]]:
        prose = latex_prose_for_line_estimate(translation)
        buckets = check_translation.classify_english_residue(prose)
        protected_source = " ".join(re.findall(r"\\(?:label|ref|cite|citep|citet|url|href)\*?(?:\[[^\]]*\])?\{[^{}]*\}", source))
        allowed = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", protected_source)}
        latex_allowed = {
            "paragraph",
            "placeholder",
            "footnote",
            "caption",
            "subcaption",
            "section",
            "subsection",
            "subsubsection",
            "textbackslash",
            "newcolumntype",
            "centering",
            "arraybackslash",
        }
        filtered = []
        for token in buckets.get("must_translate", []):
            lower = token.lower()
            if lower in latex_allowed or lower in allowed or "-" in lower or "_" in lower:
                continue
            filtered.append(token)
        buckets["must_translate"] = filtered
        return buckets

    def target_language_char_count(text: str) -> int:
        return sum(
            "\u4e00" <= ch <= "\u9fff"
            or "\u3040" <= ch <= "\u30ff"
            or "\uac00" <= ch <= "\ud7af"
            for ch in text
        )

    def source_sentences_left_untranslated(source: str, translation: str) -> list[str]:
        source_prose = latex_prose_for_line_estimate(source)
        translated_compact = re.sub(r"\s+", " ", translation).strip()
        findings: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", source_prose):
            sentence = sentence.strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", sentence)
            if len(sentence) < 70 or len(words) < 8:
                continue
            if sentence in translated_compact and sentence not in findings:
                findings.append(sentence)
            if len(findings) >= 5:
                break
        return findings

    def long_english_sections_in_translation(translation: str) -> list[str]:
        prose = latex_prose_for_line_estimate(translation)
        findings: list[str] = []
        for match in re.finditer(r"\b[A-Za-z][^。！？\u4e00-\u9fff]{80,}[.!?]", prose):
            candidate = re.sub(r"\s+", " ", match.group(0)).strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", candidate)
            if len(words) >= 12:
                findings.append(candidate)
            if len(findings) >= 5:
                return findings
        for sentence in re.split(r"(?<=[.!?])\s+", prose):
            sentence = sentence.strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", sentence)
            if len(sentence) >= 90 and len(words) >= 12 and not re.search(r"[\u4e00-\u9fff]", sentence):
                findings.append(sentence)
            if len(findings) >= 5:
                break
        return findings

    def segment_completeness(source: str, translation: str) -> dict[str, Any]:
        source_prose = latex_prose_for_line_estimate(source)
        translated_prose = latex_prose_for_line_estimate(translation)
        source_words = len(re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", source_prose))
        source_letters = sum("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in source_prose)
        target_chars = target_language_char_count(translated_prose)
        untranslated_sentences = source_sentences_left_untranslated(source, translation)
        untranslated_residue_sections = long_english_sections_in_translation(translation)
        expected_min_target_chars = max(80, int(source_words * 0.22))
        partial = (
            source_letters >= 600
            and source_words >= 90
            and target_chars < expected_min_target_chars
            and len(translated_prose) < max(120, int(len(source_prose) * 0.22))
        )
        status = "blocking" if untranslated_sentences or untranslated_residue_sections or partial else "ok"
        return {
            "status": status,
            "source_chars": len(source_prose),
            "target_chars": len(translated_prose),
            "source_word_count": source_words,
            "target_language_chars": target_chars,
            "expected_min_target_language_chars": expected_min_target_chars if source_words >= 90 else None,
            "untranslated_sentences": untranslated_sentences,
            "untranslated_residue_sections": untranslated_residue_sections,
            "partial_segment_translation": partial,
        }

    def latex_paragraph_count(text: str) -> int:
        stripped = re.sub(r"(?m)^\s*%.*$", "", text).strip()
        if not stripped:
            return 0
        return len([part for part in re.split(r"\n\s*\n+", stripped) if part.strip()])

    def latex_environment_sequence(text: str) -> list[tuple[str, str]]:
        return [
            (kind, name)
            for kind, name in re.findall(r"\\(begin|end)\{([^{}]+)\}", text)
            if name.strip()
        ]

    def paragraph_sensitive_segment(segment_id: str, source: str) -> bool:
        lower_id = segment_id.lower()
        return bool(
            "abstract" in lower_id
            or re.search(r"\\begin\{abstract\}|\\caption(?:\[[^\]]*\])?\{|\\footnote\{|\\item\b", source)
        )

    def repair_paragraph_structure(source: str, translation: str) -> tuple[str, dict[str, Any]]:
        source_count = latex_paragraph_count(source)
        target_count = latex_paragraph_count(translation)
        env_source = latex_environment_sequence(source)
        env_target = latex_environment_sequence(translation)
        repaired = translation
        repair_applied = False
        if source_count <= 1 and target_count > 1:
            repaired = re.sub(r"\n\s*\n+", "\n", translation).strip()
            repair_applied = repaired != translation
        repaired_count = latex_paragraph_count(repaired)
        return repaired, {
            "source_paragraph_count": source_count,
            "translation_paragraph_count": target_count,
            "repaired_paragraph_count": repaired_count,
            "environment_sequence_match": env_source == env_target,
            "source_environment_sequence": env_source,
            "translation_environment_sequence": env_target,
            "repair_applied": repair_applied,
        }

    for segment in source_segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or segment.get("block_id") or "document")
        source = str(segment.get("source") or segment.get("text") or "")
        translation = str(segment.get("translation") or segment.get("target") or "")
        gate_translation = latex_translation_after_writeback_repair(source, translation)
        paragraph_repaired_translation, paragraph_structure = repair_paragraph_structure(source, gate_translation)
        paragraph_structure_rows.append({"segment_id": segment_id, "sensitive_segment": paragraph_sensitive_segment(segment_id, source), **paragraph_structure})
        if paragraph_structure["repair_applied"]:
            auto_repairs.append(
                {
                    "rule": "latex_paragraph_structure_drift",
                    "segment_id": segment_id,
                    "source_paragraph_count": paragraph_structure["source_paragraph_count"],
                    "translation_paragraph_count_before": paragraph_structure["translation_paragraph_count"],
                    "translation_paragraph_count_after": paragraph_structure["repaired_paragraph_count"],
                    "repair_type": "collapse_inserted_blank_lines",
                }
            )
        if paragraph_sensitive_segment(segment_id, source) and (
            paragraph_structure["source_paragraph_count"] != paragraph_structure["repaired_paragraph_count"]
            or not paragraph_structure["environment_sequence_match"]
        ):
            add(
                "latex_paragraph_structure_drift",
                "blocking",
                segment_id,
                json.dumps(paragraph_structure, ensure_ascii=False),
                "restore_latex_paragraph_boundaries",
            )
        gate_translation = paragraph_repaired_translation
        if translation.count(r"\footnote") > gate_translation.count(r"\footnote"):
            auto_repairs.append(
                {
                    "rule": "duplicate_footnote_payload",
                    "segment_id": segment_id,
                    "source_footnote_count": source.count(r"\footnote"),
                    "translation_footnote_count_before": translation.count(r"\footnote"),
                    "translation_footnote_count_after": gate_translation.count(r"\footnote"),
                    "repair_type": "deduplicate_repeated_footnote_payload",
                }
            )
        inventory = latex_command_inventory(source, gate_translation)
        if inventory["source_command_count"] or inventory["translation_command_count"]:
            command_inventory.append({"segment_id": segment_id, **inventory})
        for missing in inventory.get("missing_commands", []):
            command_type = str(missing.get("command_type") or "command")
            severity = "blocking" if command_type in {"cite", "ref", "label", "url", "href", "begin_env", "end_env"} else "warn"
            add(
                "missing_latex_command",
                severity,
                segment_id,
                json.dumps(missing, ensure_ascii=False),
                "restore_latex_command_inventory",
            )
        if segment.get("status") in {"empty", "fallback"} or not translation.strip():
            add("segment_empty_or_fallback", "blocking", segment_id, source[:200], "retry_segment_or_restore_source")
        completeness = segment_completeness(source, gate_translation)
        segment_completeness_rows.append({"segment_id": segment_id, **completeness})
        for sentence in completeness.get("untranslated_sentences", []) if isinstance(completeness.get("untranslated_sentences"), list) else []:
            add(
                "untranslated_english_section",
                "blocking",
                segment_id,
                sentence,
                "split_segment_and_retry_translation",
            )
        for sentence in completeness.get("untranslated_residue_sections", []) if isinstance(completeness.get("untranslated_residue_sections"), list) else []:
            add(
                "untranslated_english_section",
                "blocking",
                segment_id,
                sentence,
                "split_segment_and_retry_translation",
            )
        if completeness.get("partial_segment_translation"):
            add(
                "partial_segment_translation",
                "blocking",
                segment_id,
                json.dumps(
                    {
                        "source_chars": completeness.get("source_chars"),
                        "target_chars": completeness.get("target_chars"),
                        "source_word_count": completeness.get("source_word_count"),
                        "target_language_chars": completeness.get("target_language_chars"),
                        "expected_min_target_language_chars": completeness.get("expected_min_target_language_chars"),
                    },
                    ensure_ascii=False,
                ),
                "split_segment_and_retry_translation",
            )
        if re.search(r"\\(?:section|subsection|subsubsection|paragraph|caption)\s+[A-Za-z]", gate_translation):
            add("visible_structural_command_as_prose", "blocking", segment_id, gate_translation[:200], "restore_latex_command_argument")
        if gate_translation.count("{") != gate_translation.count("}"):
            add("brace_balance", "blocking", segment_id, gate_translation[:200], "restore_original_segment")
        for value in policy_utils.protected_values(source):
            if re.match(r"(?i)^https?://|^10\.", value) and not policy_utils.protected_value_present(value, gate_translation):
                add("missing_protected_url_or_doi", "blocking", segment_id, value, "restore_protected_span")
        buckets = latex_residue_buckets(source, gate_translation)
        if buckets.get("must_translate"):
            add(
                "ordinary_english_residue",
                "warn",
                segment_id,
                ", ".join(buckets["must_translate"][:12]),
                "retry_segment_with_term_policy",
            )

    baseline_audit = latex_baseline_audit if isinstance(latex_baseline_audit, dict) else {}
    baseline_pdf = baseline_audit.get("baseline_pdf") if isinstance(baseline_audit.get("baseline_pdf"), dict) else {}
    current_pdf = baseline_audit.get("current_pdf") if isinstance(baseline_audit.get("current_pdf"), dict) else {}
    accepted_delta = baseline_audit.get("accepted_delta") if isinstance(baseline_audit.get("accepted_delta"), dict) else {}
    if baseline_pdf.get("exists") and current_pdf.get("exists"):
        baseline_pages = baseline_pdf.get("page_count")
        current_pages = current_pdf.get("page_count")
        segment_coverage = baseline_audit.get("segment_window_coverage") if isinstance(baseline_audit.get("segment_window_coverage"), dict) else {}
        coverage_ok = segment_coverage.get("status") in {"ok", "warn"} and not segment_coverage.get("blocking_coverage_loss")
        delta_ok = accepted_delta.get("status") == "accepted" and not accepted_delta.get("content_loss_evidence") and coverage_ok
        if baseline_pages is not None and current_pages is not None and baseline_pages != current_pages and not delta_ok:
            line_estimate = baseline_audit.get("line_reflow_estimate") if isinstance(baseline_audit.get("line_reflow_estimate"), dict) else {}
            repair_type = (
                "latex_reflow_patch_plan"
                if line_estimate.get("required_line_coverage") is not None
                else "coverage_diff_review"
            )
            add(
                "latex_baseline_page_drift",
                "blocking",
                "document",
                json.dumps(
                    {
                        "baseline_page_count": baseline_pages,
                        "current_page_count": current_pages,
                        "line_reflow_estimate": line_estimate,
                    },
                    ensure_ascii=False,
                ),
                repair_type,
            )
    worst = "blocking" if any(item["severity"] == "blocking" for item in issues) else ("warn" if issues else "ok")
    inventory_summary = {
        "segment_count": len(command_inventory),
        "source_command_count": sum(int(item.get("source_command_count") or 0) for item in command_inventory),
        "translation_command_count": sum(int(item.get("translation_command_count") or 0) for item in command_inventory),
        "missing_command_count": sum(int(item.get("missing_command_count") or 0) for item in command_inventory),
        "segments": command_inventory[:200],
    }
    return {
        "version": 1,
        "status": worst,
        "issues": issues,
        "command_inventory": inventory_summary,
        "auto_repairs": {
            "count": len(auto_repairs),
            "items": auto_repairs[:200],
        },
        "segment_completeness": {
            "checked_count": len(segment_completeness_rows),
            "blocking_count": sum(1 for item in segment_completeness_rows if item.get("status") == "blocking"),
            "segments": segment_completeness_rows[:200],
        },
        "paragraph_structure": {
            "checked_count": len(paragraph_structure_rows),
            "drift_count": sum(
                1
                for item in paragraph_structure_rows
                if item.get("source_paragraph_count") != item.get("repaired_paragraph_count")
                or not item.get("environment_sequence_match", True)
            ),
            "auto_repair_count": sum(1 for item in paragraph_structure_rows if item.get("repair_applied")),
            "segments": paragraph_structure_rows[:200],
        },
        "segment_window_coverage": build_latex_segment_window_coverage(source_segments),
    }

def write_latex_segment_repair_plan(output_dir: Path, quality_gate: dict[str, Any], source_segments: list[dict[str, Any]]) -> dict[str, Any]:
    segment_lookup = {
        str(item.get("id") or item.get("block_id") or ""): item
        for item in source_segments
        if isinstance(item, dict) and (item.get("id") or item.get("block_id"))
    }
    actionable_rules = {
        "partial_segment_translation",
        "untranslated_english_section",
        "segment_empty_or_fallback",
        "ordinary_english_residue",
        "missing_protected_url_or_doi",
        "brace_balance",
        "missing_latex_command",
        "latex_paragraph_structure_drift",
    }
    tasks: list[dict[str, Any]] = []
    for issue in quality_gate.get("issues", []) if isinstance(quality_gate.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        rule = str(issue.get("rule") or "")
        if rule not in actionable_rules:
            continue
        segment_id = str(issue.get("segment_id") or "")
        segment = segment_lookup.get(segment_id, {})
        source = str(segment.get("source") or segment.get("text") or "")
        translation = str(segment.get("translation") or segment.get("target") or "")
        tasks.append(
            {
                "task_id": f"latex-segment-repair-{len(tasks)+1:04d}",
                "segment_id": segment_id or "document",
                "rule": rule,
                "severity": issue.get("severity") or "warn",
                "repair_type": issue.get("repair_type") or "retry_segment",
                "source_excerpt": latex_prose_for_line_estimate(source)[:500],
                "target_excerpt": latex_prose_for_line_estimate(translation)[:500],
                "evidence": issue.get("evidence"),
                "recommended_action": (
                    "按句群或 LaTeX 安全边界拆分该 segment 后局部重译；重译后必须重新运行 "
                    "segment_completeness_check、protected span 和 command inventory gate。"
                    if rule in {"partial_segment_translation", "untranslated_english_section"}
                    else "局部修复该 segment 后重新运行 LaTeX direct quality gate。"
                ),
            }
        )
    payload = {
        "version": 1,
        "status": "blocking" if any(item.get("severity") == "blocking" for item in tasks) else ("warn" if tasks else "ok"),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    path = output_dir / "latex_segment_repair_plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(path)
    return payload

def write_latex_paragraph_structure_repair_manifest(output_dir: Path, quality_gate: dict[str, Any]) -> dict[str, Any]:
    paragraph_structure = quality_gate.get("paragraph_structure") if isinstance(quality_gate.get("paragraph_structure"), dict) else {}
    segments = paragraph_structure.get("segments") if isinstance(paragraph_structure.get("segments"), list) else []
    repairs = [
        item
        for item in segments
        if isinstance(item, dict)
        and (
            item.get("repair_applied")
            or item.get("source_paragraph_count") != item.get("repaired_paragraph_count")
            or not item.get("environment_sequence_match", True)
        )
    ]
    payload = {
        "version": 1,
        "status": "partial" if repairs else "ok",
        "repair_count": len(repairs),
        "repairs": repairs[:200],
        "policy": "abstract/caption/footnote/item 段落边界漂移必须在 LaTeX direct 写回前阻断或保守合并。",
    }
    path = output_dir / "latex_paragraph_structure_repair_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(path)
    return payload

def build_latex_segment_window_coverage(source_segments: list[dict[str, Any]], window_size: int = 20) -> dict[str, Any]:
    if not source_segments:
        return {
            "version": 1,
            "status": "unavailable",
            "reason": "missing_latex_segments",
            "segment_count": 0,
            "windows": [],
        }
    windows: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    fallback_ids: list[str] = []
    for offset in range(0, len(source_segments), window_size):
        window = source_segments[offset : offset + window_size]
        missing = []
        fallback = []
        ok = 0
        for segment in window:
            segment_id = str(segment.get("id") or segment.get("block_id") or f"segment-{offset}")
            translation = str(segment.get("translation") or segment.get("target") or "")
            status = str(segment.get("status") or "ok")
            if not translation.strip():
                missing.append(segment_id)
            elif status in {"empty", "fallback", "error"}:
                fallback.append(segment_id)
            else:
                ok += 1
        missing_ids.extend(missing)
        fallback_ids.extend(fallback)
        windows.append(
            {
                "window_id": f"segments-{offset + 1}-{offset + len(window)}",
                "start_index": offset + 1,
                "end_index": offset + len(window),
                "segment_count": len(window),
                "ok_count": ok,
                "missing_segment_ids": missing,
                "fallback_segment_ids": fallback,
                "coverage_ratio": round(ok / max(len(window), 1), 3),
                "status": "warn" if missing or fallback else "ok",
            }
        )
    blocking_loss = len(missing_ids) > max(2, int(len(source_segments) * 0.03))
    return {
        "version": 1,
        "status": "blocking" if blocking_loss else ("warn" if missing_ids or fallback_ids else "ok"),
        "segment_count": len(source_segments),
        "missing_segment_count": len(missing_ids),
        "fallback_segment_count": len(fallback_ids),
        "blocking_coverage_loss": blocking_loss,
        "windows": windows,
    }

def load_latex_direct_segments_for_gate(summary: dict[str, Any]) -> list[dict[str, Any]]:
    segments_path = Path(str(summary.get("segments_english") or ""))
    translations_path = Path(str(summary.get("reviewed_translations") or summary.get("translations") or ""))
    if not segments_path.is_file() or not translations_path.is_file():
        return []
    segments: dict[str, dict[str, Any]] = {}
    for line in segments_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        segment_id = str(row.get("id") or row.get("segment_id") or "")
        if not segment_id:
            continue
        segments[segment_id] = {
            "id": segment_id,
            "source": str(row.get("text") or row.get("source") or ""),
            "status": str(row.get("status") or "ok"),
        }
    for line in translations_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        segment_id = str(row.get("id") or row.get("segment_id") or "")
        if not segment_id or segment_id not in segments:
            continue
        segments[segment_id]["translation"] = str(row.get("translation") or row.get("target") or "")
        if row.get("status"):
            segments[segment_id]["status"] = str(row.get("status"))
    return list(segments.values())

def pdf_direct_text_repair_delivery_safe(pdf_direct_text_repair: dict[str, Any]) -> bool:
    repair = pdf_direct_text_repair if isinstance(pdf_direct_text_repair, dict) else {}
    if not bool(repair.get("delivery_safe")):
        return False
    safety = repair.get("delivery_safety") if isinstance(repair.get("delivery_safety"), dict) else {}
    status = str(safety.get("status") or repair.get("visual_delivery_review_status") or "").lower()
    return status in {
        "confirmed_safe_for_delivery_by_visual_model",
        "visual_model_delivery_safe",
        "accepted_for_delivery_by_visual_model",
    }
