#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import policy_utils
import prepare_paper_source
import visual_layout
from delivery_gate_runtime import (
    build_latex_direct_quality_gate,
    build_latex_segment_window_coverage,
    estimated_column_lines,
    is_line_estimate_eligible,
    latex_prose_for_line_estimate,
    load_latex_direct_segments_for_gate,
    strip_latex_comments,
    write_latex_paragraph_structure_repair_manifest,
    write_latex_segment_repair_plan,
)
from hymt_compat_proxy import ProxyConfig, start_hymt_compat_proxy
from pdf_translation_runtime import (
    DEFAULT_HYMT_COMPAT_PROXY_PORT,
    DEFAULT_LATEX_DOCKER_IMAGE,
    DEFAULT_LATEX_PROJECT_MODE,
    DEFAULT_LATEX_RENDER_MODE,
    LATEX_BAD_NAME_HINTS,
    LATEX_MAIN_NAME_HINTS,
    LATEX_REFLOW_LINES_PER_PAGE,
    LATEX_SOURCE_HINT_ENV,
    LATEX_SOURCE_ROOTS_ENV,
    external_pdf2zh_skill_root,
    redacted_command,
    should_enable_hymt_compat_proxy,
)

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py for LaTeX source discovery, direct rendering, baseline audit, and reflow planning."
ARXIV_SOURCE_AUTODOWNLOAD_ENV = "PAPER_TRANSLATION_ARXIV_SOURCE_AUTODOWNLOAD"
ARXIV_ID_PATTERNS = (
    re.compile(r"arXiv\s*:\s*([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.IGNORECASE),
    re.compile(r"arxiv\.org/(?:abs|pdf|e-print)/([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?(?:\.pdf)?", re.IGNORECASE),
    re.compile(r"arXiv\s*:\s*([a-z-]+(?:\.[A-Z]{2})?/[0-9]{7}(?:v[0-9]+)?)", re.IGNORECASE),
    re.compile(r"arxiv\.org/(?:abs|pdf|e-print)/([a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})(?:v[0-9]+)?(?:\.pdf)?", re.IGNORECASE),
)

def build_latex_direct_requirement(output_dir: Path) -> str:
    def compact_term_policy(payload: dict[str, Any]) -> dict[str, Any]:
        terms = payload.get("terms") if isinstance(payload, dict) else []
        compact_terms = []
        for term in terms if isinstance(terms, list) else []:
            if not isinstance(term, dict):
                continue
            source = term.get("source_term")
            if not source:
                continue
            row = {
                "source": source,
                "translation": term.get("translation", ""),
                "action": term.get("action", ""),
            }
            forbidden = term.get("forbidden_translations")
            if forbidden:
                row["forbidden"] = forbidden[:3] if isinstance(forbidden, list) else forbidden
            compact_terms.append(row)
            if len(compact_terms) >= 20:
                break
        return {"terms": compact_terms, "note": "仅列核心术语；未列出的专名按源文和上下文谨慎处理。"}

    def compact_entity_map(payload: dict[str, Any]) -> dict[str, Any]:
        entities = payload.get("entities") if isinstance(payload, dict) else []
        compact_entities = []
        for entity in entities if isinstance(entities, list) else []:
            if not isinstance(entity, dict):
                continue
            source = entity.get("source_term")
            if not source:
                continue
            if not (entity.get("active") or entity.get("source_location") == "body" or entity.get("translation")):
                continue
            compact_entities.append(
                {
                    "source": source,
                    "translation": entity.get("translation", ""),
                    "type": entity.get("entity_type", ""),
                    "forbidden": (entity.get("forbidden_translations") or [])[:2],
                }
            )
            if len(compact_entities) >= 12:
                break
        return {"entities": compact_entities}

    def compact_protected_spans(payload: dict[str, Any]) -> dict[str, Any]:
        spans = payload.get("spans") if isinstance(payload, dict) else []
        compact_spans = []
        important_kinds = {"url", "doi", "email", "citation", "reference"}
        for span in spans if isinstance(spans, list) else []:
            if not isinstance(span, dict):
                continue
            kind = str(span.get("kind") or "")
            value = str(span.get("value") or "")
            if kind not in important_kinds and len(compact_spans) >= 8:
                continue
            if not value:
                continue
            compact_spans.append({"kind": kind, "value": value[:160]})
            if len(compact_spans) >= 16:
                break
        return {
            "protected_spans": compact_spans,
            "note": "LaTeX 命令、公式、引用键、URL、DOI、文件名、占位符和环境结构必须原样保留。",
        }

    parts = [
        "将英文论文 LaTeX 源码翻译为自然、准确的简体中文。保留所有 LaTeX 命令、公式、引用键、标签、URL、DOI、文件名、占位符和环境结构。",
        "禁止把 \\section{...}、\\subsection{...}、\\begin{...}、\\end{...}、\\caption{...}、\\footnote{...} 等 LaTeX 结构命令作为普通可见正文输出；只能保留命令结构，并翻译其中人类可读的自然语言参数。只有 URL、DOI、代码、引用键、文件名、公式和占位符可以原样保留。",
        "URL/DOI/inline code 必须在翻译后仍可按原值追踪；TeX 中可因语法需要转义下划线，但不得省略、改写或翻译。",
    ]
    for name, title, compactor in [
        ("term_policy.json", "术语策略", compact_term_policy),
        ("entity_map.json", "实体策略", compact_entity_map),
        ("protected_spans.json", "不可翻译元素", compact_protected_spans),
    ]:
        path = output_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        compact = json.dumps(compactor(payload), ensure_ascii=False, separators=(",", ":"))
        parts.append(f"{title}：{compact[:1800]}")
    return "\n\n".join(parts)

def build_latex_direct_command(
    args: argparse.Namespace,
    input_pdf: Path,
    source_tex: Path,
    output_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-c",
        "from pdf2zh_skill.cli import main; raise SystemExit(main())",
        "run",
        "--project",
        str(source_tex.parent),
        "--source-pdf",
        str(input_pdf),
        "--output-dir",
        str(output_dir),
        "--translation-api-key",
        args.api_key,
        "--translation-base-url",
        args.base_url,
        "--translation-model",
        args.model,
        "--workers",
        str(args.local_max_concurrency),
        "--translate-timeout-seconds",
        str(args.latex_translate_timeout),
        "--compile-timeout-seconds",
        str(args.latex_compile_timeout),
        "--retry-untranslated",
        str(args.latex_retry_untranslated),
        "--auto-repair-passes",
        str(args.latex_auto_repair_passes),
        "--project-mode",
        str(getattr(args, "latex_project_mode", DEFAULT_LATEX_PROJECT_MODE)),
        "--requirement",
        build_latex_direct_requirement(output_dir.parent),
        "--glossary-max-candidates",
        "30",
        "--glossary-max-terms",
        "20",
        "--force-prepare",
    ]
    if args.latex_compiler:
        command.extend(["--compiler", args.latex_compiler])
    if args.latex_skip_glossary:
        command.append("--skip-glossary")
    if args.latex_skip_consistency_review:
        command.append("--skip-consistency-review")
    return command

def has_local_latex_compiler() -> bool:
    return any(shutil.which(name) for name in ("xelatex", "lualatex", "pdflatex"))

def ensure_tex_docker_wrappers(wrapper_dir: Path) -> Path:
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    template = """#!/bin/sh
set -eu
image="${{PDF2ZH_TEX_DOCKER_IMAGE:-paper-translation-tex:2026-05-21}}"
work="$(pwd)"
exec docker run --rm -v "$work:/workspace" -w /workspace "$image" {tool} "$@"
"""
    for tool in ("xelatex", "lualatex", "pdflatex", "bibtex", "latexmk"):
        path = wrapper_dir / tool
        path.write_text(template.format(tool=tool), encoding="utf-8")
        path.chmod(0o755)
    return wrapper_dir

def select_latex_compile_runtime(args: argparse.Namespace) -> dict[str, Any]:
    requested = getattr(args, "latex_compile_runtime", "auto")
    local_available = has_local_latex_compiler()
    docker_available = shutil.which("docker") is not None
    if requested == "local":
        selected = "local"
    elif requested == "docker":
        selected = "docker"
    elif local_available:
        selected = "local"
    elif docker_available:
        selected = "docker"
    else:
        selected = "missing"
    return {
        "requested": requested,
        "selected": selected,
        "local_compiler_available": local_available,
        "docker_available": docker_available,
        "docker_image": getattr(args, "latex_docker_image", DEFAULT_LATEX_DOCKER_IMAGE),
    }

def infer_latex_direct_failure_stage(log_text: str, manifest: dict[str, Any]) -> dict[str, str | None]:
    if manifest.get("status") == "ok":
        return {"failure_stage": None, "api_stage_status": "ok", "compile_stage_status": "ok"}
    lowered = log_text.lower()
    if "translation api request failed" in lowered or "httperror" in lowered or "400 client error" in lowered:
        if re.search(r"(?m)^Glossary:", log_text) and not re.search(r"(?m)^Translate:", log_text):
            return {"failure_stage": "glossary_api", "api_stage_status": "error", "compile_stage_status": "not_started"}
        if re.search(r"(?m)^Translate:", log_text):
            return {"failure_stage": "translation_api", "api_stage_status": "error", "compile_stage_status": "not_started"}
        return {"failure_stage": "api", "api_stage_status": "error", "compile_stage_status": "not_started"}
    if "compile" in lowered or "latexmk" in lowered or "tectonic" in lowered:
        return {"failure_stage": "compile", "api_stage_status": "ok", "compile_stage_status": "error"}
    if manifest.get("returncode") not in {0, None}:
        return {"failure_stage": "process_exit", "api_stage_status": "unknown", "compile_stage_status": "unknown"}
    return {"failure_stage": "missing_output", "api_stage_status": "unknown", "compile_stage_status": "unknown"}

def default_latex_baseline_pdf(source_tex: Path | None) -> Path | None:
    return None

def summarize_pdf_for_baseline(path: Path | None, preview_dir: Path, prefix: str) -> dict[str, Any]:
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

def run_latex_direct_render(
    args: argparse.Namespace,
    input_pdf: Path,
    output_dir: Path,
    source_tex: Path | None,
    env: dict[str, str],
) -> dict[str, Any]:
    mode = getattr(args, "latex_render_mode", DEFAULT_LATEX_RENDER_MODE)
    manifest_path = output_dir / "direct_latex_render_manifest.json"
    manifest: dict[str, Any] = {
        "version": 1,
        "mode": mode,
        "status": "skipped",
        "source_tex": str(source_tex) if source_tex else None,
        "latex_project_mode": getattr(args, "latex_project_mode", DEFAULT_LATEX_PROJECT_MODE),
        "backend": "external_pdf2zh_skill_latex",
        "pdf2zh_skill_path": str(external_pdf2zh_skill_root()) if external_pdf2zh_skill_root() else None,
        "output_dir": str(output_dir / "latex_direct"),
        "command": None,
        "translated_pdf": None,
        "translated_tex": None,
        "english_tex": None,
        "run_summary": None,
        "log_path": str(output_dir / "latex_direct.log"),
        "errors": [],
        "hymt_compat_proxy": {
            "mode": getattr(args, "hymt_compat_proxy", "auto"),
            "enabled": False,
            "upstream_base_url": args.base_url,
            "proxy_base_url": None,
            "stats": {},
        },
        "latex_direct_proxy_stats": {},
        "api_stage_status": "not_started",
        "compile_stage_status": "not_started",
        "failure_stage": None,
        "compile_runtime": None,
        "paper_source_dir": None,
        "paper_cn_dir": None,
        "main_tex": None,
        "translated_files": [],
        "compile_command": None,
        "translated_pdf_kind": None,
        "project_pdf": None,
        "latex_baseline_audit": None,
    }
    if mode == "off" or source_tex is None or source_tex.suffix.lower() != ".tex":
        reason = "disabled" if mode == "off" else "no_latex_source"
        manifest["reason"] = reason
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest

    latex_output_dir = output_dir / "latex_direct"
    latex_output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "latex_direct.log"
    original_base_url = args.base_url
    proxy_server = None
    if should_enable_hymt_compat_proxy(args):
        proxy_config = ProxyConfig(
            model=args.model,
            upstream_base_url=original_base_url.rstrip("/"),
            api_key=args.api_key,
            port=int(getattr(args, "hymt_compat_proxy_port", DEFAULT_HYMT_COMPAT_PROXY_PORT)),
            policy_context_path=str(output_dir / "document_memory.json"),
        )
        try:
            proxy_server = start_hymt_compat_proxy(proxy_config)
            args.base_url = proxy_config.base_url
            manifest["hymt_compat_proxy"] = {
                "mode": getattr(args, "hymt_compat_proxy", "auto"),
                "enabled": True,
                "upstream_base_url": original_base_url,
                "proxy_base_url": proxy_config.base_url,
                "stats": {},
            }
        except OSError as exc:
            if getattr(args, "hymt_compat_proxy", "auto") == "on":
                raise
            manifest["hymt_compat_proxy"] = {
                "mode": getattr(args, "hymt_compat_proxy", "auto"),
                "enabled": False,
                "upstream_base_url": original_base_url,
                "proxy_base_url": None,
                "error": f"proxy_start_failed: {exc}",
                "stats": {},
            }
    command = build_latex_direct_command(args, input_pdf, source_tex, latex_output_dir)
    latex_env = env.copy()
    external_root = external_pdf2zh_skill_root()
    existing_pythonpath = latex_env.get("PYTHONPATH", "")
    if external_root:
        latex_env["PYTHONPATH"] = str(external_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    compile_runtime = select_latex_compile_runtime(args)
    manifest["compile_runtime"] = compile_runtime
    if compile_runtime["selected"] == "docker":
        wrapper_dir = ensure_tex_docker_wrappers(output_dir / "_tex_docker_wrappers")
        latex_env["PATH"] = str(wrapper_dir) + os.pathsep + latex_env.get("PATH", "")
        latex_env["PDF2ZH_TEX_DOCKER_IMAGE"] = str(compile_runtime["docker_image"])
        compile_runtime["wrapper_dir"] = str(wrapper_dir)
    elif compile_runtime["selected"] == "missing":
        compile_runtime["error"] = "no local LaTeX compiler and docker is not available"
    manifest["command"] = redacted_command(command, args.api_key)

    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write("COMMAND: " + " ".join(redacted_command(command, args.api_key)) + "\n")
            log.write(f"MODEL: {args.model}\n")
            log.write(f"BASE_URL: {args.base_url}\n")
            log.write(f"LATEX_DIRECT_HYMT_COMPAT_PROXY: {json.dumps(manifest['hymt_compat_proxy'], ensure_ascii=False)}\n")
            log.write(f"LOCAL_MAX_CONCURRENCY: {args.local_max_concurrency}\n")
            log.write(f"LATEX_COMPILE_RUNTIME: {json.dumps(compile_runtime, ensure_ascii=False)}\n")
            log.flush()
            try:
                proc = subprocess.run(
                    command,
                    cwd=output_dir,
                    env=latex_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=args.latex_render_timeout,
                    check=False,
                )
                manifest["returncode"] = int(proc.returncode)
            except subprocess.TimeoutExpired:
                manifest["returncode"] = 124
                manifest["status"] = "error"
                manifest["errors"].append({"error_type": "timeout", "timeout_seconds": args.latex_render_timeout})
                log.write(f"\nTIMEOUT: exceeded {args.latex_render_timeout} seconds\n")
    finally:
        if proxy_server is not None:
            stats = dict(getattr(proxy_server, "stats", {}) or {})
            manifest["latex_direct_proxy_stats"] = stats
            if isinstance(manifest.get("hymt_compat_proxy"), dict):
                manifest["hymt_compat_proxy"]["stats"] = stats
            proxy_server.shutdown()
        args.base_url = original_base_url

    summary_path = latex_output_dir / "run_summary.json"
    manifest["run_summary"] = str(summary_path) if summary_path.exists() else None
    if manifest.get("returncode") not in {0, None}:
        manifest["status"] = "error"
        manifest["errors"].append({"error_type": "nonzero_exit", "returncode": manifest.get("returncode")})
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            manifest["run_summary_status"] = summary.get("status")
            manifest["translated_pdf"] = summary.get("pdf")
            manifest["translated_tex"] = summary.get("tex")
            manifest["english_tex"] = summary.get("english_tex")
            manifest["quality_report_json"] = summary.get("quality_report_json")
            manifest["quality_report_md"] = summary.get("quality_report_md")
            manifest["quality_issue_count"] = summary.get("quality_issue_count")
            manifest["auto_repairs"] = summary.get("auto_repairs")
            for key in [
                "latex_project_mode",
                "paper_source_dir",
                "paper_cn_dir",
                "main_tex",
                "translated_files",
                "compile_command",
                "translated_pdf_kind",
                "project_pdf",
            ]:
                if key in summary:
                    manifest[key] = summary.get(key)
            if summary.get("status") not in {None, "ok", "succeeded"}:
                manifest["status"] = "error"
                manifest["errors"].append({"error_type": "latex_run_summary_status", "status": summary.get("status")})
        except Exception as exc:
            manifest["status"] = "error"
            manifest["errors"].append({"error_type": "invalid_run_summary", "message": repr(exc)})

    translated_pdf = Path(str(manifest.get("translated_pdf") or ""))
    if manifest.get("status") != "error" and translated_pdf.is_file():
        manifest["status"] = "ok"
    elif manifest.get("status") != "error":
        manifest["status"] = "error"
        manifest["errors"].append({"error_type": "missing_latex_translated_pdf"})
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    manifest.update(infer_latex_direct_failure_stage(log_text, manifest))
    baseline_arg = Path(args.latex_baseline_pdf).expanduser().resolve() if getattr(args, "latex_baseline_pdf", None) else None
    baseline_pdf = baseline_arg if baseline_arg and baseline_arg.is_file() else default_latex_baseline_pdf(source_tex)
    current_pdf = Path(str(manifest.get("project_pdf") or manifest.get("translated_pdf") or ""))
    if baseline_pdf or current_pdf.is_file():
        manifest["latex_baseline_audit"] = write_latex_baseline_audit(
            output_dir,
            baseline_pdf=baseline_pdf,
            current_pdf=current_pdf if current_pdf.is_file() else None,
            source_tex=source_tex,
            summary=summary if "summary" in locals() and isinstance(summary, dict) else None,
        )
    gate_segments = load_latex_direct_segments_for_gate(summary) if "summary" in locals() and isinstance(summary, dict) else []
    quality_gate = build_latex_direct_quality_gate(
        source_segments=gate_segments,
        latex_baseline_audit=manifest.get("latex_baseline_audit"),
    )
    quality_gate_path = output_dir / "latex_direct_quality_gate.json"
    quality_gate_path.write_text(json.dumps(quality_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    segment_repair_plan = write_latex_segment_repair_plan(output_dir, quality_gate, gate_segments)
    paragraph_structure_manifest = write_latex_paragraph_structure_repair_manifest(output_dir, quality_gate)
    manifest["latex_direct_quality_gate"] = str(quality_gate_path)
    manifest["latex_direct_quality_gate_status"] = quality_gate.get("status")
    manifest["latex_segment_repair_plan"] = segment_repair_plan.get("path")
    manifest["latex_segment_repair_plan_status"] = segment_repair_plan.get("status")
    manifest["latex_paragraph_structure_repair_manifest"] = paragraph_structure_manifest.get("path")
    manifest["latex_paragraph_structure_repair_status"] = paragraph_structure_manifest.get("status")
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

def prepare_source(input_pdf: Path, output_dir: Path, source_override: Path | None = None) -> dict[str, Any]:
    source_input = source_override or input_pdf
    manifest = prepare_paper_source.prepare_source(
        SimpleNamespace(
            input=str(source_input),
            output_dir=str(output_dir),
            text=None,
            stdin=False,
            no_ocr=True,
            keep_pdf_noise=False,
        )
    )
    if source_override:
        manifest["render_input_pdf"] = str(input_pdf)
        manifest["source_override"] = {
            "path": str(source_override),
            "input_type": manifest.get("input_type"),
            "extraction_method": manifest.get("extraction_method"),
            "reason": "LaTeX source is the translation source of truth; render path is recorded separately in render_manifest.json.",
        }
        (output_dir / "source_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest

def latex_candidate_score(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1
    name = path.stem.lower()
    score = 0
    if name in LATEX_MAIN_NAME_HINTS:
        score += 80
    if name in LATEX_BAD_NAME_HINTS or name.startswith("test_"):
        score -= 120
    if "\\begin{document}" in text:
        score += 200
    if "\\title" in text:
        score += 50
    if "\\section" in text:
        score += 30
    if "\\documentclass" in text:
        score += 50
    score += min(len(text) // 5000, 20)
    return score

def iter_latex_candidates(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".tex":
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in root.rglob("*.tex"):
        parts = {part.lower() for part in path.parts}
        if parts & {".venv", "node_modules", "__pycache__", ".git"}:
            continue
        candidates.append(path)
    return candidates


def extract_arxiv_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for pattern in ARXIV_ID_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).rstrip(".").strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
    return ids


def _safe_write_archive_member(target_root: Path, member_name: str, data: bytes) -> None:
    name = member_name.lstrip("/")
    parts = Path(name).parts
    if not name or any(part in {"", ".", ".."} for part in parts):
        return
    target = (target_root / name).resolve()
    if not str(target).startswith(str(target_root.resolve()) + os.sep):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _unpack_arxiv_source(archive_path: Path, extract_dir: Path) -> dict[str, Any]:
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            extracted = 0
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                fileobj = tar.extractfile(member)
                if fileobj is None:
                    continue
                _safe_write_archive_member(extract_dir, member.name, fileobj.read())
                extracted += 1
            return {"format": "tar", "extracted_file_count": extracted}
    except tarfile.TarError:
        pass
    try:
        with zipfile.ZipFile(archive_path) as archive:
            extracted = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                _safe_write_archive_member(extract_dir, info.filename, archive.read(info))
                extracted += 1
            return {"format": "zip", "extracted_file_count": extracted}
    except zipfile.BadZipFile:
        pass
    raw = archive_path.read_bytes()
    try:
        raw = gzip.decompress(raw)
        format_name = "gzip-single-file"
    except OSError:
        format_name = "single-file"
    sample = raw[:4096].decode("utf-8", errors="ignore")
    suffix = ".tex" if "\\documentclass" in sample or "\\begin{document}" in sample else ".src"
    (extract_dir / f"source{suffix}").write_bytes(raw)
    return {"format": format_name, "extracted_file_count": 1}


def _download_arxiv_source(arxiv_id: str, output_dir: Path, timeout: int = 60) -> dict[str, Any]:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", arxiv_id)
    source_root = output_dir / "arxiv_source" / safe_id
    extract_dir = source_root / "extracted"
    archive_path = source_root / "source.e-print"
    source_root.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    manifest: dict[str, Any] = {
        "arxiv_id": arxiv_id,
        "url": url,
        "status": "attempted",
        "source_root": str(source_root),
        "extract_dir": str(extract_dir),
    }
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "double6-pdf-translation/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            manifest["http_status"] = getattr(response, "status", None)
            manifest["content_type"] = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        manifest.update({"status": "failed", "error_type": "http_error", "error": str(exc), "http_status": exc.code})
        return manifest
    except urllib.error.URLError as exc:
        manifest.update({"status": "failed", "error_type": "url_error", "error": str(exc)})
        return manifest
    except TimeoutError as exc:
        manifest.update({"status": "failed", "error_type": "timeout", "error": str(exc)})
        return manifest
    if not data or data[:256].lstrip().lower().startswith(b"<!doctype html") or data[:256].lstrip().lower().startswith(b"<html"):
        manifest.update({"status": "failed", "error_type": "non_source_response", "bytes": len(data)})
        return manifest
    archive_path.write_bytes(data)
    manifest["bytes"] = len(data)
    try:
        unpack = _unpack_arxiv_source(archive_path, extract_dir)
    except Exception as exc:  # noqa: BLE001 - record and fall back to PDF path
        manifest.update({"status": "failed", "error_type": "unpack_failed", "error": str(exc)})
        return manifest
    scored = []
    for candidate in iter_latex_candidates(extract_dir):
        score = latex_candidate_score(candidate)
        if score >= 120:
            scored.append((score, candidate.resolve()))
    if not scored:
        manifest.update({"status": "failed", "error_type": "no_main_tex_found", **unpack})
        return manifest
    scored.sort(key=lambda item: (item[0], -len(str(item[1]))), reverse=True)
    manifest.update(
        {
            "status": "ok",
            **unpack,
            "source_path": str(scored[0][1]),
            "candidate_count": len(scored),
        }
    )
    return manifest


def _arxiv_autodownload_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "disable_arxiv_source_autodownload", False):
        return False
    return os.environ.get(ARXIV_SOURCE_AUTODOWNLOAD_ENV, "1") not in {"0", "false", "False"}


def discover_latex_source(input_pdf: Path, args: argparse.Namespace, output_dir: Path | None = None) -> tuple[Path | None, dict[str, Any]]:
    if getattr(args, "disable_latex_autodiscovery", False):
        return None, {"policy": "latex_first_auto", "status": "disabled"}
    explicit = getattr(args, "source_override", None)
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path, {"policy": "manual_compat_override", "status": "manual", "source_path": str(path)}
    roots: list[Path] = []
    hint = os.environ.get(LATEX_SOURCE_HINT_ENV, "").strip()
    if hint:
        hinted = Path(hint).expanduser().resolve()
        if hinted.exists():
            if hinted.is_file() and hinted.suffix.lower() == ".tex":
                return hinted, {"policy": "latex_first_auto", "status": "env_hint_file", "source_path": str(hinted)}
            roots.append(hinted)
    for raw in os.environ.get(LATEX_SOURCE_ROOTS_ENV, "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw).expanduser().resolve())
    for raw in getattr(args, "latex_source_root", []) or []:
        roots.append(Path(raw).expanduser().resolve())
    pdf_parent = input_pdf.parent
    roots.extend(
        [
            pdf_parent,
            pdf_parent / "source",
            pdf_parent / "paper_source",
            pdf_parent / "latex",
            pdf_parent / "arxiv",
        ]
    )
    seen: set[Path] = set()
    scored: list[tuple[int, Path]] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        for candidate in iter_latex_candidates(root):
            score = latex_candidate_score(candidate)
            if score >= 120:
                scored.append((score, candidate.resolve()))
    if not scored:
        selection: dict[str, Any] = {"policy": "latex_first_auto", "status": "not_found", "searched_roots": [str(root) for root in roots]}
        if output_dir is not None and _arxiv_autodownload_enabled(args):
            text, method = extract_pdf_text(input_pdf)
            arxiv_ids = extract_arxiv_ids(text)
            selection["arxiv_pdf_inspection"] = {"method": method, "ids": arxiv_ids}
            attempts = []
            for arxiv_id in arxiv_ids[:3]:
                attempt = _download_arxiv_source(arxiv_id, output_dir)
                attempts.append(attempt)
                if attempt.get("status") == "ok" and attempt.get("source_path"):
                    source = Path(str(attempt["source_path"]))
                    selection.update(
                        {
                            "status": "arxiv_downloaded",
                            "source_path": str(source),
                            "source_of_truth": "latex_source",
                            "arxiv_id": arxiv_id,
                            "arxiv_source_attempts": attempts,
                        }
                    )
                    return source, selection
            selection["arxiv_source_attempts"] = attempts
        elif output_dir is not None:
            selection["arxiv_pdf_inspection"] = {"status": "disabled"}
        return None, selection
    scored.sort(key=lambda item: (item[0], -len(str(item[1]))), reverse=True)
    source = scored[0][1]
    return source, {
        "policy": "latex_first_auto",
        "status": "found",
        "source_path": str(source),
        "candidate_count": len(scored),
        "searched_roots": [str(root) for root in roots],
    }

def extract_pdf_text(path: Path | None) -> tuple[str, str]:
    if not path or not path.exists():
        return "", "missing_pdf"
    candidates: list[tuple[int, str, str]] = []
    for method, extractor in [
        ("pymupdf", prepare_paper_source.try_pymupdf),
        ("pypdf", prepare_paper_source.try_pypdf),
        ("pdftotext", prepare_paper_source.try_pdftotext),
    ]:
        try:
            text, _pages = extractor(path)
            if text.strip():
                quality = prepare_paper_source.analyze_extraction_quality(text, prepare_paper_source.build_blocks(text))
                glued_penalty = int(quality.get("long_alpha_token_count") or 0) * 300
                page_bonus = text.count("<!-- page:") * 800
                cjk_bonus = len([char for char in text if "\u4e00" <= char <= "\u9fff"]) * 2
                poppler_visible_text_bonus = 12000 if method == "pdftotext" else 0
                score = len(text.strip()) + page_bonus + cjk_bonus + poppler_visible_text_bonus - glued_penalty
                candidates.append((score, text.strip(), method))
        except Exception:
            continue
    if not candidates:
        return "", "text_extraction_failed"
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1], f"{candidates[0][2]}_voted"
