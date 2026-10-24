# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation delivery：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

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
    from pdf_translation_overrides import pdf_direct_text_repair_delivery_safe
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

    if pipeline_status == "error":
        add("render_status", "blocking", "render_manifest.status=error", "渲染链路失败时不能把 strict delivery 标为通过。")
    elif has_translated_pdf is False:
        add("render_status", "blocking", "no translated_pdf selected", "没有主 PDF 产物时不能把 strict delivery 标为通过。")
    else:
        add("render_status", "ok", f"render_manifest.status={pipeline_status or 'unknown'}", "无需额外动作。")

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
    warn_visual = [item for item in visual_findings if isinstance(item, dict) and item.get("severity") == "warn"]
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
    visual_rule_gate("toc_alignment", {"toc_alignment_drift"}, "目录标题与页码列不能漂移、合并或乱序；需局部重渲染目录页。")
    visual_rule_gate("toc_row_geometry", {"toc_row_geometry_drift", "chapter_index_merge", "toc_row_renderer_failed"}, "目录/章节索引行应保持标题列和页码列分离，不能合并为长行。")
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
        add("dual_visual", "blocking", json.dumps(delivery_dual_blocking[:3], ensure_ascii=False), "标准双语 PDF 存在译文侧（右）空白或原文侧（左）背景漂移，不能作为合格双语交付。")
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
            add("engine_block_bridge", "warn", "bridge_status=order_only", "当前只能页/顺序级桥接，局部 PDF 修复需保持保守。")
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
        if structure_gate.get("status") == "partial" or any(isinstance(item, dict) and item.get("severity") == "blocking" for item in issues):
            add("layout_structure_gate", "blocking", json.dumps(issues[:5], ensure_ascii=False), "结构质量门存在阻断项，必须局部重排、重译或保持 partial。")
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
    plan_tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    visual_tasks = plan.get("visual_page_rerender_candidates") if isinstance(plan.get("visual_page_rerender_candidates"), list) else []
    task_count = len(plan_tasks) + len(visual_tasks)
    if is_latex_direct:
        add("pdf_rerender_plan", "ok", "skipped_for_latex_direct_primary_render", "LaTeX 主路径不使用 PDF rerender plan 阻断；需看 latex_segment_repair_plan。")
    elif plan_status in {"needs_rerender", "partial", "blocking"} or task_count:
        add(
            "pdf_rerender_plan",
            "blocking",
            json.dumps({"status": plan_status, "task_count": task_count, "sample": (plan_tasks + visual_tasks)[:3]}, ensure_ascii=False),
            "pdf_rerender_plan 存在待重渲染任务时，主 PDF 不能标记为已修复或完全通过。",
        )
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
        add("rerender_candidates", "warn", json.dumps(forbidden_candidates[:5], ensure_ascii=False), "存在术语或 protected span 风险，需 QA 修复或重跑。")
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
        "fast draft 仍要求生成源文左/译文右双语 PDF。",
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
        "skip_visual_eval requested; DeepSeek evaluation not run",
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

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
