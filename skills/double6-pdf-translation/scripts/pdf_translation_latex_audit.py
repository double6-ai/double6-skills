# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation latex audit：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def default_latex_baseline_pdf(source_tex: Path | None) -> Path | None:
    from pdf_translation_paths import paper_translation_run_root
    if source_tex is None:
        return None
    if source_tex.name != "acl_latex.tex":
        return None
    candidate = (
        paper_translation_run_root()
        / "04_eval"
        / "translation_final_2026-05-23_hymt_deepseek"
        / "outputs"
        / "arxiv-paper-translator"
        / "full_latex"
        / "latextrans"
        / "paper_cn"
        / "acl_latex.pdf"
    )
    return candidate if candidate.is_file() else None


def summarize_pdf_for_baseline(path: Path | None, preview_dir: Path, prefix: str) -> dict[str, Any]:
    from pdf_translation_artifacts import extract_pdf_text
    if path is None or not path.is_file():
        return {"path": str(path) if path else None, "exists": False}
    text, method = extract_pdf_text(path)
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "page_count": visual_layout.pdf_page_count(path),
        "text_extraction_method": method,
        "text_chars": len(text),
        "cjk_char_count": sum(1 for char in text if "\u4e00" <= char <= "\u9fff"),
    }
    try:
        pages = visual_layout.extract_pdf_pages(path, preview_dir, prefix, max_pages=3)
        summary["preview_pages"] = [{"page": item["page"], "preview_path": item["preview_path"]} for item in pages]
        summary["text_layer_health"] = visual_layout.text_layer_health(pages)
        page_report = visual_layout.analyze_visual_pages(pages, pages, key_texts=[])
        summary["visual_token_profile"] = {
            "page_metrics": page_report.get("page_metrics", []),
            "visible_latex_command_count": sum(
                int((metric.get("text_layer_health") or {}).get("visible_latex_command_count") or 0)
                for metric in page_report.get("page_metrics", [])
                if isinstance(metric, dict)
            ),
            "overlap_pages": [
                item.get("page")
                for item in page_report.get("findings", [])
                if isinstance(item, dict) and item.get("rule") == "text_overlap"
            ],
        }
    except Exception as exc:
        summary["preview_error"] = repr(exc)
    return summary


def latex_page_drift_tokens(text: str) -> set[str]:
    value = re.sub(r"\s+", " ", str(text or "")).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{3,}", value))
    cjk_chars = [char for char in value if "\u4e00" <= char <= "\u9fff"]
    tokens.update("".join(cjk_chars[index : index + 2]) for index in range(max(0, len(cjk_chars) - 1)))
    return {token for token in tokens if token.strip()}

def latex_page_content_drift_from_text_pages(
    baseline_pages: list[dict[str, Any]],
    current_pages: list[dict[str, Any]],
    *,
    max_pages: int = 3,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    baseline_token_pages = [
        latex_page_drift_tokens(str(page.get("text") or ""))
        for page in baseline_pages
    ]
    for index in range(min(max_pages, len(baseline_pages), len(current_pages))):
        baseline_text = str(baseline_pages[index].get("text") or "")
        current_text = str(current_pages[index].get("text") or "")
        baseline_tokens = baseline_token_pages[index]
        current_tokens = latex_page_drift_tokens(current_text)
        union = baseline_tokens | current_tokens
        similarity = round(len(baseline_tokens & current_tokens) / len(union), 3) if union else 1.0
        best_window_match: dict[str, Any] | None = None
        for candidate_index in range(max(0, index - 1), min(len(baseline_token_pages), index + 2)):
            if candidate_index == index:
                continue
            candidate_tokens = baseline_token_pages[candidate_index]
            candidate_union = candidate_tokens | current_tokens
            candidate_similarity = round(len(candidate_tokens & current_tokens) / len(candidate_union), 3) if candidate_union else 1.0
            candidate = {
                "baseline_page": candidate_index + 1,
                "page_delta": (candidate_index + 1) - (index + 1),
                "token_jaccard": candidate_similarity,
            }
            if best_window_match is None or candidate_similarity > float(best_window_match.get("token_jaccard") or 0):
                best_window_match = candidate
        item = {
            "page": index + 1,
            "baseline_text_chars": len(baseline_text),
            "current_text_chars": len(current_text),
            "token_jaccard": similarity,
        }
        if best_window_match is not None:
            item["best_adjacent_baseline_match"] = best_window_match
        comparisons.append(item)
        if len(baseline_text) >= 500 and len(current_text) >= 500 and similarity < 0.28:
            accepted_reflow = bool(best_window_match and float(best_window_match.get("token_jaccard") or 0) >= 0.55)
            findings.append(
                {
                    "rule": "latex_baseline_page_content_drift",
                    "severity": "info" if accepted_reflow else "warn",
                    "page": index + 1,
                    "evidence": item,
                    "accepted_page_reflow": accepted_reflow,
                    "message": (
                        "当前 LaTeX 主 PDF 与历史参考相邻页匹配度较高，判定为可接受的 float/分页重排。"
                        if accepted_reflow
                        else "当前 LaTeX 主 PDF 与历史参考在同页文本内容差异过大，可能存在 float/分页位置漂移或内容提前/后移。"
                    ),
                }
            )
    active_findings = [
        item for item in findings
        if isinstance(item, dict) and item.get("severity") in {"blocking", "warn"}
    ]
    return {
        "version": 1,
        "status": "warn" if active_findings else "accepted_reflow" if findings else "ok",
        "method": "page_text_token_jaccard_against_historical_baseline",
        "pages_checked": len(comparisons),
        "comparisons": comparisons,
        "findings": findings,
    }

def build_latex_page_content_drift_report(baseline_pdf: Path | None, current_pdf: Path | None) -> dict[str, Any]:
    if not baseline_pdf or not current_pdf or not baseline_pdf.is_file() or not current_pdf.is_file():
        return {"version": 1, "status": "unavailable", "reason": "missing_baseline_or_current_pdf", "findings": []}
    try:
        return latex_page_content_drift_from_text_pages(
            visual_layout.extract_pdf_text_pages(baseline_pdf),
            visual_layout.extract_pdf_text_pages(current_pdf),
        )
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"page_content_drift_unavailable: {exc}", "findings": []}

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

def latex_content_loss_evidence(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or segment.get("block_id") or "document")
        source = str(segment.get("source") or segment.get("text") or "")
        translation = str(segment.get("translation") or segment.get("target") or "")
        if segment.get("status") in {"empty", "fallback"} or not translation.strip():
            evidence.append({"rule": "segment_empty_or_fallback", "segment_id": segment_id})
        if translation.count("{") != translation.count("}"):
            evidence.append({"rule": "brace_balance", "segment_id": segment_id})
        for value in policy_utils.protected_values(source):
            if re.match(r"(?i)^https?://|^10\.", value) and not policy_utils.protected_value_present(value, translation):
                evidence.append({"rule": "missing_protected_url_or_doi", "segment_id": segment_id, "value": value[:120]})
    return evidence[:20]

def count_latex_headings(tex_path: Path | None) -> int:
    if not tex_path or not tex_path.is_file():
        return 0
    text = strip_latex_comments(tex_path.read_text(encoding="utf-8", errors="replace"))
    return len(re.findall(r"\\(?:section|subsection|subsubsection|paragraph)\*?\{", text))

def build_latex_reflow_plan(
    *,
    output_dir: Path,
    estimate: dict[str, Any],
    summary: dict[str, Any] | None,
    eligible_segment_count: int,
) -> dict[str, Any]:
    required = int(estimate.get("required_lines_for_page_delta") or 0)
    translated_line_count = int(estimate.get("translated_line_count") or 0)
    tex_path = Path(str(summary.get("tex") or "")) if isinstance(summary, dict) and summary.get("tex") else None
    heading_count = count_latex_headings(tex_path)
    paragraph_count = max(eligible_segment_count, 1)
    options: list[dict[str, Any]] = []

    def add_option(name: str, risk: str, added_lines: float, snippet: str, note: str) -> None:
        options.append(
            {
                "name": name,
                "risk": risk,
                "estimated_added_lines": round(added_lines, 2),
                "gap_to_target_lines": round(abs(required - added_lines), 2),
                "snippet": snippet,
                "note": note,
            }
        )

    if required <= 0:
        return {
            "version": 1,
            "status": "not_needed",
            "target_added_lines": 0,
            "options": [],
            "recommendation": "页数未缩短或无需补偿；不生成 reflow patch。",
        }

    for spacing in [0.25, 0.5, 0.75, 1.0]:
        add_option(
            "A_heading_before_vspace",
            "medium",
            heading_count * spacing,
            "\\pretocmd{\\section}{\\vspace{%.2f\\baselineskip}}{}{}\n"
            "\\pretocmd{\\subsection}{\\vspace{%.2f\\baselineskip}}{}{}" % (spacing, spacing),
            f"在 {heading_count} 个章节/段落标题前增加约 {spacing} 行空间。",
        )
    for spacing in [0.12, 0.25, 0.5]:
        add_option(
            "B_paragraph_spacing",
            "medium",
            paragraph_count * spacing,
            "\\setlength{\\parskip}{%.2f\\baselineskip}" % spacing,
            f"按 {paragraph_count} 个可翻译正文段落估算段间距补偿。",
        )
    if not options or min(item["gap_to_target_lines"] for item in options) > required * 0.25:
        for scale in [1.02, 1.04, 1.06]:
            added = translated_line_count * max(scale - 1.0, 0)
            add_option(
                "C_cjk_font_scale",
                "high",
                added,
                "将中文正文字号按 %.2fx 放大；仅作为人工复核候选，不自动应用。" % scale,
                "字号放大会影响公式、表格和双栏排版，默认不应自动采用。",
            )

    options.sort(key=lambda item: (item["gap_to_target_lines"], {"medium": 0, "high": 1}.get(item["risk"], 2)))
    plan = {
        "version": 1,
        "status": "review_required",
        "target_added_lines": required,
        "heading_count": heading_count,
        "paragraph_count": paragraph_count,
        "options": options,
        "recommendation": options[0] if options else None,
        "applies_patch": False,
    }
    plan_path = output_dir / "latex_reflow_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(plan_path), **plan}

def build_latex_line_reflow_estimate(
    *,
    output_dir: Path,
    baseline_pdf: dict[str, Any],
    current_pdf: dict[str, Any],
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    from pdf_translation_latex_quality import load_latex_direct_segments_for_gate
    segments = load_latex_direct_segments_for_gate(summary or {})
    eligible_rows: list[dict[str, Any]] = []
    source_lines_total = 0
    translated_lines_total = 0
    for segment in segments:
        source = str(segment.get("source") or "")
        translation = str(segment.get("translation") or "")
        if not is_line_estimate_eligible(source, translation):
            continue
        source_lines = estimated_column_lines(source)
        translated_lines = estimated_column_lines(translation)
        source_lines_total += source_lines
        translated_lines_total += translated_lines
        eligible_rows.append(
            {
                "segment_id": str(segment.get("id") or "document"),
                "source_estimated_lines": source_lines,
                "translated_estimated_lines": translated_lines,
                "removed_lines": max(0, source_lines - translated_lines),
            }
        )
    baseline_pages = baseline_pdf.get("page_count")
    current_pages = current_pdf.get("page_count")
    page_delta = (current_pages - baseline_pages) if isinstance(baseline_pages, int) and isinstance(current_pages, int) else None
    required_lines = abs(page_delta) * LATEX_REFLOW_LINES_PER_PAGE if isinstance(page_delta, int) and page_delta < 0 else 0
    removed_lines = max(0, source_lines_total - translated_lines_total)
    coverage = round(removed_lines / required_lines, 3) if required_lines else None
    content_loss = latex_content_loss_evidence(segments)
    confidence = "low"
    if len(eligible_rows) >= 12 and (coverage or 0) >= 1.0:
        confidence = "high"
    elif len(eligible_rows) >= 6 and (coverage or 0) >= 0.75:
        confidence = "medium"
    accepted = bool(page_delta and page_delta < 0 and required_lines and (coverage or 0) >= 0.75 and not content_loss)
    estimate = {
        "version": 1,
        "status": "accepted" if accepted else ("review_required" if page_delta else "not_applicable"),
        "method": "rough_cjk_width_column_line_estimate",
        "line_width_cjk_units": LATEX_REFLOW_LINE_WIDTH_CJK,
        "assumed_lines_per_page_delta": LATEX_REFLOW_LINES_PER_PAGE,
        "baseline_page_count": baseline_pages,
        "current_page_count": current_pages,
        "page_delta": page_delta,
        "source_line_count": source_lines_total,
        "translated_line_count": translated_lines_total,
        "estimated_removed_lines": removed_lines,
        "required_lines_for_page_delta": required_lines,
        "required_line_coverage": coverage,
        "eligible_segment_count": len(eligible_rows),
        "confidence": confidence,
        "content_loss_evidence": bool(content_loss),
        "content_loss_details": content_loss,
        "segment_samples": eligible_rows[:20],
    }
    estimate["latex_reflow_plan"] = build_latex_reflow_plan(
        output_dir=output_dir,
        estimate=estimate,
        summary=summary,
        eligible_segment_count=len(eligible_rows),
    )
    return estimate


def write_latex_baseline_audit(
    output_dir: Path,
    *,
    baseline_pdf: Path | None,
    current_pdf: Path | None,
    source_tex: Path | None,
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    from pdf_translation_latex_quality import build_latex_segment_window_coverage, load_latex_direct_segments_for_gate
    audit_path = output_dir / "latex_baseline_audit.json"
    preview_dir = output_dir / "latex_baseline_audit_pages"
    baseline = summarize_pdf_for_baseline(baseline_pdf, preview_dir, "baseline")
    current = summarize_pdf_for_baseline(current_pdf, preview_dir, "current")
    deltas: dict[str, Any] = {}
    if baseline.get("exists") and current.get("exists"):
        for field in ["page_count", "size_bytes", "text_chars", "cjk_char_count"]:
            if baseline.get(field) is not None and current.get(field) is not None:
                deltas[f"{field}_delta"] = current.get(field) - baseline.get(field)
    page_count_match = None
    if baseline.get("exists") and current.get("exists"):
        if baseline.get("page_count") is not None and current.get("page_count") is not None:
            page_count_match = baseline.get("page_count") == current.get("page_count")
    line_reflow_estimate = build_latex_line_reflow_estimate(
        output_dir=output_dir,
        baseline_pdf=baseline,
        current_pdf=current,
        summary=summary,
    )
    segment_window_coverage = build_latex_segment_window_coverage(
        load_latex_direct_segments_for_gate(summary) if isinstance(summary, dict) else []
    )
    page_content_drift = build_latex_page_content_drift_report(baseline_pdf, current_pdf)
    reflow_plan = line_reflow_estimate.get("latex_reflow_plan")
    accepted_delta = {
        "status": line_reflow_estimate.get("status"),
        "reason": (
            "LaTeX source 翻译为中文后的自然行数压缩足以解释页数减少。"
            if line_reflow_estimate.get("status") == "accepted"
            else "LaTeX source 页数差异需要 reflow patch plan 或内容覆盖复核。"
        ),
        "content_loss_evidence": bool(line_reflow_estimate.get("content_loss_evidence")),
        "estimated_removed_lines": line_reflow_estimate.get("estimated_removed_lines"),
        "required_lines_for_page_delta": line_reflow_estimate.get("required_lines_for_page_delta"),
        "confidence": line_reflow_estimate.get("confidence"),
        "latex_reflow_plan": reflow_plan.get("path") if isinstance(reflow_plan, dict) else None,
    }
    payload = {
        "version": 1,
        "status": "ok" if baseline.get("exists") and current.get("exists") else "partial",
        "source_tex": str(source_tex) if source_tex else None,
        "baseline_pdf": baseline,
        "current_pdf": current,
        "main_tex": summary.get("main_tex") if summary else None,
        "compile_command": summary.get("compile_command") if summary else None,
        "include_graph_summary": summary.get("include_graph") if summary else None,
        "differences": deltas,
        "page_count_match": page_count_match,
        "line_reflow_estimate": line_reflow_estimate,
        "segment_window_coverage": segment_window_coverage,
        "page_content_drift": page_content_drift,
        "accepted_delta": accepted_delta,
        "latex_reflow_plan": reflow_plan,
    }
    audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(audit_path), **payload}


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
