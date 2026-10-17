# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation gates：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def gate_status(render_manifest: dict[str, Any] | None, name: str) -> str:
    gates = ((render_manifest or {}).get("validation") or {}).get("gates")
    gate_items = gates.get("gates") if isinstance(gates, dict) else []
    for gate in gate_items if isinstance(gate_items, list) else []:
        if isinstance(gate, dict) and gate.get("name") == name:
            return str(gate.get("status") or "")
    return ""

def check_translation_blocks(
    manifest: dict[str, Any],
    translation_blocks: list[dict[str, Any]],
    *,
    render_manifest: dict[str, Any] | None = None,
    latex_block_bridge_path: Path | None = None,
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
            latex_route = (render_manifest or {}).get("actual_render_source") == "latex_direct"
            bridge = None
            bridge_error = None
            if latex_block_bridge_path is not None:
                try:
                    from build_latex_block_bridge import validate_for_quality
                    bridge = validate_for_quality(latex_block_bridge_path, manifest, render_manifest or {})
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    bridge_error = str(exc)
            if bridge is not None:
                issues.append(Issue(
                    "medium", "LaTeX 文本已桥接，PDF 覆盖待审",
                    f"{bridge['mapped_block_count']} 个旧文本块已重放核对至最终 TeX；"
                    f"{len(bridge['segments_not_in_legacy_block_projection'])} 个历史分段不在旧文本抽取视图中。"
                    "PDF 定位、图表内容和语义忠实度仍需独立审查。",
                    category="structure", block_id="document", source_evidence=str(latex_block_bridge_path),
                    suggestion="完成最终 PDF 覆盖、公式数字、图表及全页视觉审查；不得据此设置 engine_block_bridge=ok 或晋升 strict。"))
            elif bridge_error is not None:
                issues.append(Issue("high", "LaTeX 桥接证据失效", bridge_error,
                                    category="structure", block_id="document",
                                    suggestion="按当前输入重新生成并核对桥接；保留既有缺口警告。"))
            if bridge is None:
                issues.append(
                    Issue(
                        "medium",
                        "LaTeX 分段证据待桥接" if latex_route else "PDF direct 分块证据待桥接",
                        "translation_blocks 已明确标记为 needs_block_alignment，表示缺少 block-local target；该问题应归类为 traceability/block_bridge，不应作为可见译文漏译证据。",
                        category="structure",
                        block_id="document",
                        suggestion=("补齐源 TeX 文件、segment_id、最终 TeX 返修与 PDF 页面的映射；旧分段译文不能替代最终 PDF 覆盖检查。" if latex_route else
                                    "补齐 block_bridge/layout_map 的 page/debug_id 映射；可见漏译另由 visual/report finding 和 PDF 文本层证据判断。"),
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
    latex_block_bridge_path: Path | None = None,
) -> list[Issue]:
    from check_translation_core import enrich_issue_locations
    from check_translation_fidelity import build_coverage_gate, check_block_faithfulness, check_protected_spans, check_source_coverage, check_source_extraction_quality
    from check_translation_memory import build_entity_map, build_term_policy
    from check_translation_residue import check_sections, check_translation_metadata_leak, check_untranslated_english
    from check_translation_terms import check_bad_acronym_translation_blocks, check_entity_map_policies, check_glossary_by_blocks, check_term_policy
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
    issues.extend(check_translation_metadata_leak(source, translation))
    issues.extend(check_block_faithfulness(source, translation, translation_blocks or []))
    issues.extend(check_source_coverage(effective_manifest))
    issues.extend(check_source_extraction_quality(effective_manifest))
    issues.extend(check_protected_spans(translation, protected_spans or {}, translation_blocks or []))
    issues.extend(check_translation_blocks(effective_manifest, translation_blocks or [], render_manifest=render_manifest or {}, latex_block_bridge_path=latex_block_bridge_path))
    issues.extend(check_render_manifest(render_manifest or {}))
    return enrich_issue_locations(issues, effective_manifest)


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
