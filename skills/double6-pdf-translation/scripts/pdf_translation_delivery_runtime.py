#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py for delivery override handling, visual candidate plans, and rerender plan assembly."

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import build_block_bridge
import build_babeldoc_il_layout_map
import build_bilingual_pdf
import build_layout_structure_gate
import build_pdf_rerender_plan
import build_poppler_text_bbox_audit
import build_pymupdf_layout_audit
import build_structured_writeback_manifest
import build_structured_visual_candidates
import check_translation
import extract_terms
import prepare_paper_source
import preflight_runtime
import render_readable_pdf
import repair_quality_issues
import layout_role_policy
import policy_utils
import visual_layout
from translation_compat_proxy import ProxyConfig, start_translation_compat_proxy

from delivery_gate_runtime import (
    build_delivery_gates,
    build_fast_full_translation_draft_gates,
)
from latex_direct_runtime import (
    discover_latex_source,
    extract_pdf_text,
    iter_latex_candidates,
    run_latex_direct_render,
)

from pdf_translation_runtime import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_CLI_MAX_TOKENS,
    DEFAULT_HYMT2_TEMPERATURE,
    DEFAULT_TRANSLATION_COMPAT_PROXY_PORT,
    DEFAULT_LATEX_DOCKER_IMAGE,
    DEFAULT_LATEX_PROJECT_MODE,
    DEFAULT_LATEX_RENDER_MODE,
    DEFAULT_LOCAL_MAX_CONCURRENCY,
    DEFAULT_MODEL,
    DEFAULT_PDF2ZH_BACKEND,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TRANSLATOR_MODE,
    PROTECTED_CHECK_TRANSLATIONS,
    PROTECTED_CHECK_VALUES,
    apply_pdf_direct_text_repairs,
    build_backend_system_prompt,
    build_pdf2zh_command,
    default_engine_home,
    default_output_dir,
    external_pdf2zh_skill_root,
    redacted_command,
    resolve_pdf_layout_profile,
    resolved_pdf2zh_backend,
    should_enable_translation_compat_proxy,
    should_use_qwen_cli_adapter,
)
























from pdf_translation_artifacts_runtime import *  # noqa: F401,F403
from pdf_translation_quality_runtime import *  # noqa: F401,F403

def block_page_lookup(manifest: dict[str, Any]) -> dict[str, Any]:
    pages: dict[str, Any] = {}
    for block in manifest.get("blocks", []) if isinstance(manifest.get("blocks"), list) else []:
        if isinstance(block, dict) and block.get("block_id"):
            pages[str(block["block_id"])] = block.get("page")
    return pages


def add_rerender_candidate(
    candidates: list[dict[str, Any]],
    *,
    rule: str,
    evidence: str,
    recommendation: str,
    page: Any = None,
    block_id: str | None = None,
    layer: str = "translation_execution",
    severity: str = "warn",
    rerender_mode: str | None = None,
) -> None:
    candidates.append(
        {
            "candidate_id": f"rerender-{len(candidates) + 1:04d}",
            "rule": rule,
            "severity": severity,
            "layer": layer,
            "page": page or "global",
            "block_id": block_id or "document",
            "rerender_mode": rerender_mode or ("page" if page not in {None, "global"} else "full_pipeline"),
            "evidence": evidence[:500],
            "recommendation": recommendation,
        }
    )


def build_rerender_candidates(
    output_dir: Path,
    manifest: dict[str, Any],
    translated_text: str,
    backend_quality: dict[str, Any],
    render_manifest: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    block_pages = block_page_lookup(manifest)
    source_text = (output_dir / "source.md").read_text(encoding="utf-8", errors="replace") if (output_dir / "source.md").exists() else ""
    protected_search_text = translated_text
    latex_manifest = policy_utils.load_json(output_dir / "direct_latex_render_manifest.json")
    translated_tex = Path(str(latex_manifest.get("translated_tex") or ""))
    if translated_tex.is_file():
        protected_search_text += "\n" + translated_tex.read_text(encoding="utf-8", errors="replace")
    protected = check_translation.load_json(output_dir / "protected_spans.json")
    metadata_repair = policy_utils.load_json(output_dir / "metadata_label_repair_manifest.json")
    references_clone_pages = {
        int(action.get("page"))
        for action in metadata_repair.get("actions", [])
        if isinstance(action, dict)
        and action.get("kind") == "source_region_clone"
        and action.get("role") == "references_region"
        and str(action.get("status") or "") == "applied"
        and str(action.get("page") or "").isdigit()
    }
    for span in protected.get("spans", []) if isinstance(protected.get("spans"), list) else []:
        if not isinstance(span, dict):
            continue
        kind = str(span.get("kind") or "")
        value = str(span.get("value") or "").strip()
        if not value or kind not in {"doi", "url", "citation", "inline_math", "display_math", "inline_code"}:
            continue
        protected_present = (
            policy_utils.protected_inline_code_present(value, protected_search_text)
            if kind == "inline_code"
            else policy_utils.protected_value_present(value, protected_search_text)
        )
        if not protected_present:
            block_id = str(span.get("block_id") or "document")
            span_page = span.get("page") or block_pages.get(block_id)
            if kind in {"doi", "url", "citation"} and span_page in references_clone_pages:
                continue
            add_rerender_candidate(
                candidates,
                rule="missing_protected_span",
                layer="protected_elements",
                severity="blocking" if kind in {"doi", "url", "inline_math", "display_math"} else "warn",
                page=span_page,
                block_id=block_id,
                evidence=f"{kind}: {value}",
                recommendation="重跑对应页或对应 block，system prompt 必须要求逐字保留该不可翻译元素。",
            )
    for value in PROTECTED_CHECK_VALUES:
        expected_values = PROTECTED_CHECK_TRANSLATIONS.get(value, [])
        target_present = value in translated_text or any(expected in translated_text for expected in expected_values)
        if value in source_text and not target_present:
            add_rerender_candidate(
                candidates,
                rule="missing_policy_term",
                layer="protected_elements",
                severity="warn",
                evidence=f"{value} -> {' / '.join(expected_values) if expected_values else value}",
                recommendation="检查 term_policy/entity_map 注入是否生效；必要时局部重译含该术语的页。",
            )
    term_policy = check_translation.load_json(output_dir / "term_policy.json")
    for item in term_policy.get("terms", []) if isinstance(term_policy.get("terms"), list) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_term") or "")
        for forbidden in item.get("forbidden_translations", []) if isinstance(item.get("forbidden_translations"), list) else []:
            if forbidden and str(forbidden) in translated_text:
                add_rerender_candidate(
                    candidates,
                    rule="forbidden_terminology_translation",
                    layer="protected_elements",
                    severity="warn",
                    evidence=f"{source}: {forbidden}",
                    recommendation="按 term_policy 修订术语译法，并重跑受影响页。",
                )
    residue_buckets = check_translation.classify_english_residue(
        translated_text,
        protected_spans=protected,
        entity_map=check_translation.load_json(output_dir / "entity_map.json"),
        term_policy=term_policy,
    )
    english_words = filter_nonblocking_english_residue(translated_text, residue_buckets.get("must_translate", []))
    if len(english_words) >= 8:
        add_rerender_candidate(
            candidates,
            rule="english_residue_threshold",
            layer="translation_execution",
            severity="blocking",
            evidence=", ".join(english_words[:40]),
            recommendation="普通英文残留超过阈值，必须按页抽样定位并重跑受影响页；如果多页集中出现 same-as-input，重跑 full pipeline。",
            rerender_mode="full_pipeline",
        )
    coverage_gate = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else {}
    for key in ["missing_tail_anchors", "page_tail_anchor_missing", "missing_pages"]:
        values = coverage_gate.get(key)
        if isinstance(values, list) and values:
            add_rerender_candidate(
                candidates,
                rule=key,
                layer="translation_execution",
                severity="warn",
                evidence=json.dumps(values[:12], ensure_ascii=False),
                recommendation="尾部锚点或页面覆盖不完整，建议 full pipeline rerender 并复查 source_manifest coverage_gate。",
                rerender_mode="full_pipeline",
            )
    backend_fallback_counts = [
        int(backend_quality.get(key) or 0)
        for key in (
            "fallback_count",
            "json_error_count",
            "same_as_input_count",
            "retry_failure_count",
            "blocking_count",
        )
    ]
    backend_total = int(backend_quality.get("total") or backend_quality.get("translated_count") or 0)
    backend_fallback_ratio = float(backend_quality.get("fallback_ratio") or 0)
    if backend_quality.get("status") == "partial" and (backend_total > 0 or any(backend_fallback_counts) or backend_fallback_ratio > 0):
        add_rerender_candidate(
            candidates,
            rule="backend_fallback_ratio_high",
            layer="translation_execution",
            severity="blocking",
            evidence=json.dumps(backend_quality, ensure_ascii=False),
            recommendation="后端 fallback 比例或 JSON 错误过高，确认模型 endpoint、API key、模型名和兼容代理配置后重跑 full pipeline。",
            rerender_mode="full_pipeline",
        )
    payload = {
        "version": 1,
        "status": "warn" if candidates else "ok",
        "candidate_count": len(candidates),
        "render_status": render_manifest.get("status"),
        "candidates": candidates,
    }
    (output_dir / "rerender_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def english_residue_context_nonblocking(text: str, token: str) -> bool:
    """Return true only when every occurrence is in a role that should preserve English."""
    if not token:
        return True
    pattern = re.compile(rf"\b{re.escape(token)}\b", flags=re.I)
    matches = list(pattern.finditer(text or ""))
    if not matches:
        return True
    for match in matches:
        start, end = match.span()
        window = text[max(0, start - 650) : min(len(text), end + 650)]
        lower_window = window.lower()
        if re.search(r"https?://|doi\.org|github\.com|dataset[_\s-]?statistics|languages[_\s-]?by", lower_window):
            continue
        if re.search(r"\b(?:example\s+\d+|st|ht|nmt-gt|llm-[a-z0-9-]+)\s*[:：]", window, re.I) or re.search(
            r"示例\s*\d+|例\s*\d+|弦歌不辍|ST\s*[:：]|HT\s*[:：]|NMT-GT\s*[:：]|LLM-[A-Za-z0-9-]+\s*[:：]",
            window,
            re.I,
        ):
            continue
        before = text[max(0, start - 5000) : start]
        lower_before = before.lower()
        reference_markers = [
            lower_before.rfind("references"),
            lower_before.rfind("参考文献"),
        ]
        backmatter_markers = [
            lower_before.rfind("acknowledgements"),
            lower_before.rfind("acknowledgments"),
            lower_before.rfind("author contributions"),
            lower_before.rfind("additional information"),
            lower_before.rfind("competing interests"),
            lower_before.rfind("致谢"),
            lower_before.rfind("作者贡献"),
            lower_before.rfind("附加信息"),
        ]
        in_references = max(reference_markers) > max(backmatter_markers)
        reference_citation_marker = re.search(
            r"\(\d{4}\)|\b\d{4}\b|et al|journal|press|university|proc\.?|proceedings|conf|preprint|arxiv|doi|vol\.?|pp\.?",
            window,
            re.I,
        )
        reference_domain_marker = re.search(
            r"journal|press|university|proc\.?|proceedings|conf|transl|translation|comput|linguist|preprint|arxiv|doi|discourse|vol\.?|pp\.?|j\s+[A-Z]",
            window,
            re.I,
        )
        reference_like_context = reference_citation_marker and reference_domain_marker
        if (in_references and reference_like_context) or reference_like_context:
            continue
        if re.search(r"图\s*\d+|figure\s+\d+|table\s+\d+|表\s*\d+|total across dimensions|situation model|readability|easability|descriptive", window, re.I):
            continue
        if re.search(r"祁\s*\W{0,3}" + re.escape(token), window, re.I):
            continue
        return False
    return True


def filter_nonblocking_english_residue(translated_text: str, tokens: list[str]) -> list[str]:
    return [token for token in tokens if not english_residue_context_nonblocking(translated_text, token)]


def accepted_latex_page_delta(latex_baseline_audit: dict[str, Any] | None) -> bool:
    baseline_audit = latex_baseline_audit if isinstance(latex_baseline_audit, dict) else {}
    accepted_delta = baseline_audit.get("accepted_delta") if isinstance(baseline_audit.get("accepted_delta"), dict) else {}
    return accepted_delta.get("status") == "accepted" and not accepted_delta.get("content_loss_evidence")


def visual_false_positive_confirmed(finding: dict[str, Any]) -> bool:
    status = str(finding.get("candidate_status") or finding.get("visual_override_status") or "").lower()
    return "confirmed_false_positive" in status or "false_positive_confirmed" in status


def pdf_direct_repair_delivery_review_confirmed(finding: dict[str, Any]) -> bool:
    status = str(finding.get("candidate_status") or finding.get("visual_override_status") or finding.get("status") or "").lower()
    return status in {
        "confirmed_safe_for_delivery_by_visual_model",
        "visual_model_delivery_safe",
        "accepted_for_delivery_by_visual_model",
    }


def apply_pdf_direct_repair_delivery_overrides(
    pdf_direct_text_repair: dict[str, Any],
    supplemental_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mark PDF direct repairs delivery-safe only when visual review explicitly accepts them."""
    repair = dict(pdf_direct_text_repair) if isinstance(pdf_direct_text_repair, dict) else {}
    repairs = repair.get("repairs") if isinstance(repair.get("repairs"), list) else []
    if repair.get("status") != "repaired" or not repairs:
        return repair
    for override in supplemental_findings or []:
        if not isinstance(override, dict):
            continue
        rule = str(override.get("rule") or "")
        if rule not in {
            "visual_model_accepts_pdf_direct_text_repair_delivery",
            "pdf_direct_text_repair_delivery_review",
        }:
            continue
        if not pdf_direct_repair_delivery_review_confirmed(override):
            continue
        accepted_scope = str(override.get("accepted_scope") or override.get("applies_to") or "all_repairs")
        if accepted_scope not in {"all_repairs", "pdf_direct_text_repair_manifest"}:
            continue
        delivery_safety = {
            "status": "confirmed_safe_for_delivery_by_visual_model",
            "review_rule": rule,
            "reviewed_pages": override.get("reviewed_pages") or override.get("pages"),
            "evidence": override.get("evidence"),
            "review_packet": override.get("review_packet"),
            "notes": override.get("notes"),
        }
        repair["delivery_safe"] = True
        repair["delivery_safety"] = delivery_safety
        repair["visual_delivery_review"] = delivery_safety
        return repair
    return repair



def structured_visual_candidate_review_confirmed(finding: dict[str, Any]) -> bool:
    status = str(finding.get("candidate_status") or finding.get("visual_override_status") or finding.get("status") or "").lower()
    return status in {
        "confirmed_safe_for_delivery_by_visual_model",
        "visual_model_delivery_safe",
        "accepted_for_delivery_by_visual_model",
    }


def apply_structured_visual_candidate_delivery_overrides(
    structured_manifest: dict[str, Any],
    supplemental_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Accept structured candidate pages only with explicit visual-model delivery evidence."""
    manifest = dict(structured_manifest) if isinstance(structured_manifest, dict) else {}
    candidates = [dict(item) for item in manifest.get("candidates", []) if isinstance(item, dict)]
    if not candidates or not manifest.get("output_pdf"):
        return manifest
    for override in supplemental_findings or []:
        if not isinstance(override, dict):
            continue
        rule = str(override.get("rule") or "")
        if rule not in {
            "visual_model_accepts_structured_visual_candidate_delivery",
            "structured_visual_candidate_delivery_review",
        }:
            continue
        if not structured_visual_candidate_review_confirmed(override):
            continue
        accepted_pages = {int(page) for page in override.get("accepted_pages", []) if str(page).isdigit()}
        accepted_types = {
            str(item)
            for item in override.get("accepted_candidate_types", [])
            if str(item).strip()
        }
        if not accepted_pages and not accepted_types:
            continue
        replacement_pages: set[int] = set()
        for candidate in candidates:
            page = candidate.get("page")
            page_int = int(page) if str(page).isdigit() else None
            candidate_type = str(candidate.get("type") or "")
            if (page_int in accepted_pages) or (candidate_type in accepted_types):
                candidate["human_review_status"] = "accepted_by_visual_model"
                candidate["safe_for_auto_delivery"] = True
                candidate["visual_delivery_review"] = {
                    "status": "confirmed_safe_for_delivery_by_visual_model",
                    "review_rule": rule,
                    "evidence": override.get("evidence"),
                    "review_packet": override.get("review_packet"),
                    "notes": override.get("notes"),
                }
                if page_int is not None and candidate.get("type") == "structured_page_candidate":
                    replacement_pages.add(page_int)
        if not replacement_pages:
            continue
        delivery_safety = {
            "status": "confirmed_safe_for_delivery_by_visual_model",
            "review_rule": rule,
            "accepted_pages": sorted(replacement_pages),
            "evidence": override.get("evidence"),
            "review_packet": override.get("review_packet"),
            "notes": override.get("notes"),
        }
        manifest["candidates"] = candidates
        manifest["selected_as_delivery"] = True
        manifest["safe_for_auto_delivery"] = True
        manifest["human_review_status"] = "accepted_by_visual_model"
        manifest["delivery_safe"] = True
        manifest["delivery_safety"] = delivery_safety
        manifest["accepted_replacement_pages"] = sorted(replacement_pages)
        manifest["status"] = "accepted_for_delivery_by_visual_model"
        return manifest
    return manifest


def structured_visual_candidate_delivery_safe(structured_manifest: dict[str, Any]) -> bool:
    manifest = structured_manifest if isinstance(structured_manifest, dict) else {}
    if not bool(manifest.get("delivery_safe") or manifest.get("safe_for_auto_delivery")):
        return False
    safety = manifest.get("delivery_safety") if isinstance(manifest.get("delivery_safety"), dict) else {}
    status = str(safety.get("status") or manifest.get("human_review_status") or "").lower()
    return status in {
        "confirmed_safe_for_delivery_by_visual_model",
        "visual_model_delivery_safe",
        "accepted_for_delivery_by_visual_model",
        "accepted_by_visual_model",
    }


def apply_layout_mapping_warning_delivery_overrides(
    pymupdf_audit: dict[str, Any],
    layout_structure_gate: dict[str, Any],
    supplemental_findings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = dict(pymupdf_audit) if isinstance(pymupdf_audit, dict) else {}
    gate = dict(layout_structure_gate) if isinstance(layout_structure_gate, dict) else {}
    for override in supplemental_findings or []:
        if not isinstance(override, dict):
            continue
        rule = str(override.get("rule") or "")
        if rule != "visual_model_accepts_layout_mapping_warnings_nonblocking":
            continue
        if not structured_visual_candidate_review_confirmed(override):
            continue
        delivery_safety = {
            "status": "confirmed_safe_for_delivery_by_visual_model",
            "review_rule": rule,
            "reviewed_pages": override.get("reviewed_pages") or override.get("pages"),
            "evidence": override.get("evidence"),
            "review_packet": override.get("review_packet"),
            "notes": override.get("notes"),
        }
        audit["visible_text_not_tracked_delivery_safe"] = True
        audit["visible_text_not_tracked_delivery_safety"] = delivery_safety
        gate["warn_only_delivery_safe"] = True
        gate["warn_only_delivery_safety"] = delivery_safety
        return audit, gate
    return audit, gate


def apply_visual_false_positive_overrides(
    visual_report: dict[str, Any],
    supplemental_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Downgrade only visually confirmed false-positive gate findings."""
    findings = visual_report.get("findings") if isinstance(visual_report.get("findings"), list) else []
    if not findings:
        return visual_report
    confirmed: dict[tuple[str, str], dict[str, Any]] = {}
    for override in supplemental_findings or []:
        if not isinstance(override, dict) or not visual_false_positive_confirmed(override):
            continue
        try:
            page_key = str(int(override.get("page")))
        except Exception:
            page_key = str(override.get("page") or "")
        for rule in override.get("false_positive_for_rules") or []:
            if isinstance(rule, str) and rule:
                confirmed[(page_key, rule)] = override
    if not confirmed:
        return visual_report

    updated_findings: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            updated_findings.append(finding)
            continue
        try:
            page_key = str(int(finding.get("page")))
        except Exception:
            page_key = str(finding.get("page") or "")
        rule = str(finding.get("rule") or "")
        override = confirmed.get((page_key, rule)) or confirmed.get(("", rule))
        if override is None:
            updated_findings.append(finding)
            continue
        updated = dict(finding)
        original_severity = updated.get("severity")
        updated["severity"] = "info"
        updated["visual_false_positive_status"] = "confirmed"
        updated["visual_false_positive_rule"] = override.get("rule")
        updated["visual_false_positive_evidence"] = override.get("evidence")
        updated["visual_false_positive_candidate_evidence"] = override.get("candidate_evidence")
        updated["original_severity"] = original_severity
        updated_findings.append(updated)
        applied.append({"page": finding.get("page"), "rule": rule, "original_severity": original_severity})

    result = dict(visual_report)
    result["findings"] = updated_findings
    existing = result.get("visual_false_positive_overrides") if isinstance(result.get("visual_false_positive_overrides"), list) else []
    result["visual_false_positive_overrides"] = existing + applied
    return result


def apply_latex_baseline_false_positive_overrides(
    latex_baseline_audit: dict[str, Any],
    supplemental_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    page_content_drift = latex_baseline_audit.get("page_content_drift") if isinstance(latex_baseline_audit.get("page_content_drift"), dict) else {}
    findings = page_content_drift.get("findings") if isinstance(page_content_drift.get("findings"), list) else []
    if not findings:
        return latex_baseline_audit
    confirmed: dict[tuple[str, str], dict[str, Any]] = {}
    for override in supplemental_findings or []:
        if not isinstance(override, dict) or not visual_false_positive_confirmed(override):
            continue
        try:
            page_key = str(int(override.get("page")))
        except Exception:
            page_key = str(override.get("page") or "")
        for rule in override.get("false_positive_for_rules") or []:
            if isinstance(rule, str) and rule:
                confirmed[(page_key, rule)] = override
    if not confirmed:
        return latex_baseline_audit

    updated_findings: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            updated_findings.append(finding)
            continue
        try:
            page_key = str(int(finding.get("page")))
        except Exception:
            page_key = str(finding.get("page") or "")
        rule = str(finding.get("rule") or "")
        override = confirmed.get((page_key, rule)) or confirmed.get(("", rule))
        if override is None:
            updated_findings.append(finding)
            continue
        updated = dict(finding)
        original_severity = updated.get("severity")
        updated["severity"] = "info"
        updated["visual_false_positive_status"] = "confirmed"
        updated["visual_false_positive_rule"] = override.get("rule")
        updated["visual_false_positive_evidence"] = override.get("evidence")
        updated["original_severity"] = original_severity
        updated_findings.append(updated)
        applied.append({"page": finding.get("page"), "rule": rule, "original_severity": original_severity})

    if not applied:
        return latex_baseline_audit
    result = dict(latex_baseline_audit)
    updated_page_content_drift = dict(page_content_drift)
    updated_page_content_drift["findings"] = updated_findings
    if not [item for item in updated_findings if isinstance(item, dict) and item.get("severity") in {"blocking", "warn"}]:
        updated_page_content_drift["status"] = "accepted"
    existing = updated_page_content_drift.get("visual_false_positive_overrides") if isinstance(updated_page_content_drift.get("visual_false_positive_overrides"), list) else []
    updated_page_content_drift["visual_false_positive_overrides"] = existing + applied
    result["page_content_drift"] = updated_page_content_drift
    return result


def append_visual_rerender_candidates(
    candidates_payload: dict[str, Any],
    visual_report: dict[str, Any],
    *,
    latex_baseline_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = candidates_payload.setdefault("candidates", [])
    existing = {
        (
            str(item.get("rule")),
            str(item.get("page")),
            str(item.get("block_id")),
        )
        for item in candidates
        if isinstance(item, dict)
    }
    for finding in visual_report.get("findings", []) if isinstance(visual_report.get("findings"), list) else []:
        if not isinstance(finding, dict):
            continue
        rule = str(finding.get("rule") or "")
        severity = str(finding.get("severity") or "warn")
        if severity not in {"blocking", "warn"}:
            continue
        page = finding.get("page")
        if (
            accepted_latex_page_delta(latex_baseline_audit)
            and str(finding.get("rule") or "") in {"page_count_drift", "page_count_drift_full_pdf"}
        ):
            severity = "warn"
        if rule in {
            "main_prose_tiny_font",
            "font_size_regression",
            "small_font_overuse",
            "heading_tiny_font",
            "toc_alignment_drift",
            "toc_row_geometry_drift",
            "chapter_index_merge",
            "toc_row_renderer_failed",
            "chart_label_untranslated",
            "chart_label_partial_translation",
            "chart_axis_original_text_visible",
            "table_header_untranslated",
            "table_header_missing_from_il",
            "table_header_writeback_failed",
            "table_caption_missing",
            "table_caption_untranslated",
            "table_caption_writeback_failed",
            "table_region_rerender_required",
            "table_rule_loss",
            "cover_title_year_missing",
            "cover_year_missing_from_translation",
            "cover_year_position_drift",
            "visible_style_tag_leak",
            "metadata_mixed_language",
            "metadata_paint_mixed_language",
            "metadata_original_layer_unsuppressed",
            "footer_in_header_band",
            "metadata_yband_mismatch",
            "contact_email_fragmented",
            "footnote_tiny_or_orphan_glyph",
        }:
            severity = "blocking"
        key = (rule, str(page), "page")
        if key in existing:
            continue
        add_rerender_candidate(
            candidates,
            rule=rule or "visual_layout_finding",
            layer="pdf_rendering",
            severity=severity,
            page=page,
            block_id="page",
            evidence=str(finding.get("evidence") or finding.get("message") or "")[:500],
            recommendation=(
                "LaTeX 页数差异已有 accepted_delta，不作为失败；仅复核 reflow/同页内容漂移。"
                if rule in {"page_count_drift", "page_count_drift_full_pdf"} and accepted_latex_page_delta(latex_baseline_audit)
                else "该页存在视觉/语义版式 finding；按 failure_stage 定位 parse/layout/translate/typeset/paint/composite，"
                "优先生成 page-level rerender plan。"
            ),
            rerender_mode=(
                "latex_reflow_review"
                if rule in {"page_count_drift", "page_count_drift_full_pdf"} and accepted_latex_page_delta(latex_baseline_audit)
                else "page_rerender"
            ),
        )
        candidates[-1]["failure_stage"] = finding.get("failure_stage") or "unknown"
        candidates[-1]["layout_role"] = finding.get("layout_role") or "main_text"
        candidates[-1]["repair_target"] = finding.get("repair_target") or "manual triage"
        existing.add(key)
    candidates_payload["candidate_count"] = len(candidates)
    candidates_payload["status"] = "warn" if candidates else "ok"
    return candidates_payload


def append_visual_rerender_plan(output_dir: Path, visual_report: dict[str, Any]) -> None:
    plan_path = output_dir / "pdf_rerender_plan.json"
    plan = policy_utils.load_json(plan_path)
    if not plan:
        plan = {"version": 1, "status": "review_required"}
    page_candidates: list[dict[str, Any]] = []
    for finding in visual_report.get("findings", []) if isinstance(visual_report.get("findings"), list) else []:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "warn")
        if severity not in {"blocking", "warn"}:
            continue
        if str(finding.get("rule") or "") == "heading_bold_style_drift":
            continue
        page_candidates.append(
            {
                "page": finding.get("page"),
                "rule": finding.get("rule") or "visual_layout_finding",
                "severity": severity,
                "failure_stage": finding.get("failure_stage") or "unknown",
                "layout_role": finding.get("layout_role") or "main_text",
                "rerender_mode": "page_rerender",
                "evidence": finding.get("evidence"),
                "repair_targets": [
                    finding.get("repair_target") or "manual triage",
                    "BabelDOC/PDFMathTranslate-next page-level rerender",
                    "readable fallback if stable reanchor is unavailable",
                ],
                "fallback_policy": "无法安全回填主版式时，主 PDF 保持 partial，readable fallback 作为补充交付。",
            }
        )
    if page_candidates:
        plan["visual_page_rerender_candidates"] = page_candidates
        plan["status"] = "review_required"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
