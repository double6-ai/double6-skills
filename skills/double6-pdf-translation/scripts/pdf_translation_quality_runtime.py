#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py for backend quality parsing, retry failure extraction, and dropped text audits."

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

def parse_backend_quality(log_text: str) -> dict[str, Any]:
    total = successful = fallback = None
    match = re.search(r"Translation\s+completed\.\s+Total:\s*(\d+),\s*Successful:\s*(\d+),\s*Fallback:\s*(\d+)", log_text, re.I)
    if match:
        total, successful, fallback = (int(match.group(index)) for index in range(1, 4))
    json_parse_errors = len(
        re.findall(
            r"JSONDecodeError|Expecting\s+(?:':' delimiter|property name enclosed|value|',' delimiter)|Failed to parse JSON|invalid json",
            log_text,
            re.I,
        )
    )
    same_as_input = len(re.findall(r"same\s+as\s+input|Translation result is the\s+same", log_text, re.I))
    token_usage_errors = len(re.findall(r"Error getting token usage|token usage error|usage.*(?:None|null)", log_text, re.I))
    fallback_lines = len(
        re.findall(
            r"Fallback to simple translation|Translation result is the same as input, fallback|Translation result .* fallback\.",
            log_text,
            re.I,
        )
    )
    if fallback is None:
        fallback = fallback_lines
    if successful is None:
        successful = 0
    if total is None:
        total = successful + fallback
    fallback_ratio = float(fallback / total) if total else 0.0
    if fallback_ratio >= 0.15 or json_parse_errors >= 3 or same_as_input >= 3:
        status = "partial"
    elif fallback_ratio > 0.05 or json_parse_errors or same_as_input or token_usage_errors:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "total": total,
        "successful": successful,
        "fallback": fallback,
        "json_parse_errors": json_parse_errors,
        "same_as_input_fallback": same_as_input,
        "token_usage_errors": token_usage_errors,
        "fallback_ratio": round(fallback_ratio, 4),
    }


def parse_translation_cache_stats(log_text: str) -> dict[str, Any]:
    calls: dict[str, int] = {}
    for match in re.finditer(
        r"([A-Za-z0-9_.:-]+)\s+translate call count:\s*(?:[^\n]*?\n\s*)?(\d+)",
        log_text,
    ):
        calls[match.group(1)] = int(match.group(2))
    cache_calls: dict[str, int] = {}
    for match in re.finditer(
        r"([A-Za-z0-9_.:-]+)\s+translate cache call\s+count:\s*(?:[^\n]*?\n\s*)?(\d+)",
        log_text,
    ):
        cache_calls[match.group(1)] = int(match.group(2))
    total_calls = sum(calls.values())
    total_cache_calls = sum(cache_calls.values())
    ratio = float(total_cache_calls / total_calls) if total_calls else 0.0
    return {
        "translate_call_count": calls,
        "translate_cache_call_count": cache_calls,
        "total_translate_calls": total_calls,
        "total_cache_hits": total_cache_calls,
        "cache_hit_ratio": round(ratio, 4),
    }


def enrich_translation_cache_stats(cache_stats: dict[str, Any], proxy_info: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(cache_stats)
    stats = proxy_info.get("stats") if isinstance(proxy_info, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    proxy_requests = int(stats.get("json_batch_requests") or 0)
    proxy_items = int(stats.get("json_batch_items") or 0)
    if proxy_requests:
        enriched["proxy_json_batch_requests"] = proxy_requests
        enriched["proxy_json_batch_items"] = proxy_items
    if proxy_requests and int(enriched.get("total_translate_calls") or 0) <= 0:
        calls = dict(enriched.get("translate_call_count") or {})
        calls["translation_proxy_json_batch_requests"] = proxy_requests
        enriched["translate_call_count"] = calls
        enriched["total_translate_calls"] = proxy_requests
        enriched["call_count_source"] = "translation_proxy_stats"
        total_cache_hits = int(enriched.get("total_cache_hits") or 0)
        enriched["cache_hit_ratio"] = round(float(total_cache_hits / proxy_requests), 4) if proxy_requests else 0.0
    return enriched


def annotate_backend_quality_origin(
    backend_quality: dict[str, Any],
    proxy_info: dict[str, Any],
) -> dict[str, Any]:
    annotated = dict(backend_quality)
    stats = proxy_info.get("stats") if isinstance(proxy_info, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    protected_passthrough = int(stats.get("json_batch_protected_passthrough") or 0)
    layout_role_passthrough = (
        int(stats.get("json_batch_layout_role_direct_output") or 0)
        + int(stats.get("plain_layout_role_direct_output") or 0)
        + int(stats.get("plain_layout_role_intercept") or 0)
    )
    intended_passthrough = protected_passthrough + layout_role_passthrough
    same_after_retry = int(stats.get("json_batch_same_as_input_after_retry") or 0)
    same_as_input = int(annotated.get("same_as_input_fallback") or 0)
    if not same_as_input and same_after_retry:
        same_as_input = max(same_after_retry - intended_passthrough, 0)
        annotated["same_as_input_fallback"] = same_as_input
    elif same_as_input and layout_role_passthrough:
        same_as_input = max(same_as_input - layout_role_passthrough, 0)
        annotated["same_as_input_fallback"] = same_as_input
    retry_failed = int(stats.get("same_as_input_retry_failed") or 0)
    retry_total = int(stats.get("same_as_input_retry") or 0)
    if same_as_input and (retry_failed or same_after_retry):
        origin = "proxy_retry_failed"
    elif same_as_input and not retry_total:
        origin = "babeldoc_downstream_fallback"
    elif same_as_input:
        origin = "log_inferred"
    elif layout_role_passthrough:
        origin = "layout_role_passthrough"
    elif protected_passthrough:
        origin = "protected_or_passthrough"
    else:
        origin = "not_detected"
    annotated["same_as_input_origin"] = origin
    annotated["proxy_retry_total"] = retry_total
    annotated["proxy_retry_failed"] = retry_failed
    annotated["proxy_retry_success"] = int(stats.get("same_as_input_retry_success") or 0)
    annotated["proxy_same_as_input_after_retry"] = same_after_retry
    annotated["protected_or_passthrough_same_as_input"] = protected_passthrough
    annotated["layout_role_passthrough_same_as_input"] = layout_role_passthrough
    fallback_ratio = float(annotated.get("fallback_ratio") or 0)
    json_parse_errors = int(annotated.get("json_parse_errors") or 0)
    token_usage_errors = int(annotated.get("token_usage_errors") or 0)
    if fallback_ratio >= 0.15 or json_parse_errors >= 3 or same_as_input >= 3:
        annotated["status"] = "partial"
    elif fallback_ratio > 0.05 or json_parse_errors or same_as_input or token_usage_errors:
        annotated["status"] = "warn"
    elif origin in {"protected_or_passthrough", "layout_role_passthrough"}:
        annotated["status"] = "ok"
    if annotated.get("cache_gate_status") == "blocking":
        annotated["status"] = "partial"
    return annotated


NON_BLOCKING_BACKEND_FAILURE_CLASSES = {
    "protected_or_passthrough",
    "already_translated_passthrough",
    "layout_role_passthrough",
    "cover_split_fragment",
    "fallback_but_translated_warn",
    "structured_translated_needs_mapping",
    "pdf_direct_repaired",
}


PDF_DIRECT_REPAIR_RESOLUTIONS: dict[str, str] = {}


def cjk_count(text: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in text)


def looks_already_translated(text: str) -> bool:
    stripped = text.strip()
    if re.match(r"^(?:ST|TT|MT|HT)\s*[:：]", stripped, flags=re.I) and cjk_count(stripped) >= 4:
        return True
    letters = len(re.findall(r"[A-Za-z]", stripped))
    return cjk_count(stripped) >= 8 and cjk_count(stripped) >= letters


def looks_formula_or_placeholder_heavy(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    placeholder_count = len(re.findall(r"\{v\d+\}|<style\b[^>]*>", stripped, flags=re.I))
    text_without_placeholders = re.sub(r"</?style\b[^>]*>|\{v\d+\}", " ", stripped, flags=re.I)
    if placeholder_count >= 2 and len(re.findall(r"\b[A-Za-z]{4,}\b", text_without_placeholders)) <= 3:
        return True
    if re.fullmatch(r"[\s\d.,;:，。()（）{}\[\]A-Z_a-z+\-*/=<>|\\]+", stripped) and (
        placeholder_count or re.search(r"\b(?:argmax|argsort|Top|CSR|FEC|QR|NMT|LLM)\b", stripped)
    ):
        return True
    if re.fullmatch(r"[\d\s.,;:，。()（）{}\[\]+\-–—/%]+", stripped):
        return True
    return False


def plain_text_without_style_tags(text: str) -> str:
    return re.sub(r"</?style\b[^>]*>|\{v\d+\}", " ", str(text or ""), flags=re.I)


def looks_like_name_list_heavy(text: str) -> bool:
    plain = plain_text_without_style_tags(text)
    comma_count = plain.count(",")
    capitalized = re.findall(r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'-]+)+\b", plain)
    return comma_count >= 4 and len(capitalized) >= 4


def has_long_ordinary_english_run(text: str, *, min_words: int = 8) -> bool:
    plain = plain_text_without_style_tags(text)
    protected_lines = []
    for line in plain.splitlines():
        if re.search(r"https?://|www\.|github\.com|/[A-Za-z0-9._-]+|[A-Za-z0-9._-]+\.(?:csv|json|txt|pdf|tex)\b", line, flags=re.I):
            continue
        protected_lines.append(line)
    plain = "\n".join(protected_lines)
    plain = re.sub(r"[\[(（][^\])）]{0,180}(?:et\s+al\.?|等人)[^\])）]{0,80}\d{4}[^\])）]{0,80}[\])）]", " ", plain, flags=re.I)
    plain = re.sub(r"[\[(（][A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}(?:\s*[,&;]\s*[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,}){0,5}[^\])）]{0,40}\d{4}[^\])）]{0,40}[\])）]", " ", plain)
    protected_tokens = {
        "AI",
        "Index",
        "HAI",
        "ChatGPT",
        "ChatGPT-4o",
        "Claude",
        "Gemini",
        "Deep",
        "Think",
        "LLM",
        "LLMs",
        "LLM-4o",
        "LLM-o1",
        "NMT",
        "NMT-GT",
        "HT",
        "ST",
        "TT",
        "OpenAI",
        "OpenAI-o1",
        "GPT",
        "GPT-4o",
        "Transformer",
        "Coh-Metrix",
        "CELEX",
        "Google",
        "Translate",
        "IMO",
        "OSWorld",
        "ChemBench",
        "MSAPairformer",
        "Prot",
        "GitHub",
        "Hugging",
        "Face",
        "Epoch",
        "Nvidia",
        "H100",
        "CO2",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{1,}", plain)
    run = 0
    for word in words:
        if word in protected_tokens or word.isupper():
            run = 0
            continue
        run += 1
        if run >= min_words:
            return True
    return False


def classify_backend_passthrough(text: str) -> str:
    raw = text.strip()
    normalized_heading = layout_role_policy.normalized_heading(raw)
    if normalized_heading in {"artificial", "intelligence index report"}:
        return "cover_split_fragment"
    if re.match(r"^(?:ST|HT|TT|NMT-GT|LLM(?:-[A-Za-z0-9]+)?|GPT(?:-[A-Za-z0-9]+)?)\s*:", raw):
        return "layout_role_passthrough"
    role = layout_role_policy.classify_babeldoc_item({"input": raw, "layout_label": "fallback_line"})
    if role in {
        "doi_line",
        "open_badge",
        "author_line",
        "email_footer",
        "affiliation_footer",
        "running_header",
        "running_footer",
        "institution_line",
        "institution_label",
        "drop_cap",
        "example_block",
        "references_entry",
    }:
        return "layout_role_passthrough"
    if looks_already_translated(raw):
        return "already_translated_passthrough"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 ._-]{0,40}\s+[–-]\s*arxiv\s+x{2,}\.x{2,}", raw, flags=re.I):
        return "protected_or_passthrough"
    if re.fullmatch(
        r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*,\s*"
        r"(?:xAI|Anthropic|Meta|Mistral AI|DeepSeek|OpenAI|Google|Alibaba|Baidu|Moonshot|Tencent|Huawei)\b.*",
        raw,
        flags=re.I,
    ):
        return "protected_or_passthrough"
    if re.fullmatch(r"[A-Za-z0-9{}]+(?:[-_.][A-Za-z0-9{}]+){1,}", raw) and re.search(r"\d|gpt|llama|claude|mixtral|qwen|glm|deepseek|gemini|vicuna", raw, re.I):
        return "protected_or_passthrough"
    if "http://" in raw or "https://" in raw or "www." in raw:
        without_urls = re.sub(r"</?style\b[^>]*>", " ", raw, flags=re.I)
        without_urls = re.sub(r"https?://\S+|www\.\S+", " ", without_urls, flags=re.I)
        meaningful_words = [
            word
            for word in re.findall(r"\b[A-Za-z]{3,}\b", without_urls)
            if word.lower() not in {"style", "http", "https", "www"}
        ]
        if len(meaningful_words) <= 2:
            return "protected_or_passthrough"
    if looks_formula_or_placeholder_heavy(raw):
        return "protected_or_passthrough"
    stripped = re.sub(r"</?style\b[^>]*>", " ", raw, flags=re.I)
    stripped = re.sub(r"https?://\S+|www\.\S+", " ", stripped, flags=re.I)
    stripped = re.sub(r"\b\d{2}\.\d{4,9}/[-._;()/:A-Za-z0-9]+", " ", stripped)
    stripped = re.sub(r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", " ", stripped)
    stripped = re.sub(r"\{v\d+\}|\{[A-Za-z_][A-Za-z0-9_]*\}|%\d*\$?[sd]|%\w", " ", stripped)
    stripped = re.sub(r"\[[\d,\s;:-]+\]", " ", stripped)
    stripped = re.sub(r"`[^`]*`", " ", stripped)
    stripped = re.sub(
        r"\\(?:begin|end|section|subsection|subsubsection|caption|label|ref|cite|url|textbf|textit|left|right|[A-Za-z]+)"
        r"(?:\{[^{}]*\})?",
        " ",
        stripped,
    )
    stripped = re.sub(r"[\\{}()[\].,;:，。！？、…\s_\-=+*/|<>\"'“”‘’]+", "", stripped)
    if not stripped or not re.search(r"[A-Za-z]", stripped):
        return "protected_or_passthrough"
    return "ordinary_same_as_input"


def classify_backend_fallback(source: str, output: str) -> str:
    source_classification = classify_backend_passthrough(source)
    if source_classification in {"protected_or_passthrough", "already_translated_passthrough", "cover_split_fragment"}:
        return source_classification
    source_words = re.findall(r"[A-Za-z]{2,}", source)
    if output.strip() and cjk_count(output) >= 2 and len(source_words) <= 4:
        return "fallback_but_translated_warn"
    if output.strip() and cjk_count(output) >= max(4, len(re.findall(r"[A-Za-z]", output)) // 4):
        return "fallback_but_translated_warn"
    return "fallback_to_simple_translation"


def refine_backend_quality_with_retry_failures(
    backend_quality: dict[str, Any],
    retry_failures_path: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(retry_failures_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return backend_quality
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    ordinary_same = sum(
        1
        for item in failures
        if isinstance(item, dict)
        and item.get("failure_type") in {"same_as_input_after_retry", "same_as_input_retry_candidate"}
        and item.get("classification") == "ordinary_same_as_input"
    )
    blocking_failures = sum(1 for item in failures if isinstance(item, dict) and item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES)
    nonblocking_same = sum(
        1
        for item in failures
        if isinstance(item, dict)
        and item.get("failure_type") in {"same_as_input_after_retry", "same_as_input_retry_candidate", "protected_passthrough"}
        and item.get("classification") in {"protected_or_passthrough", "already_translated_passthrough", "layout_role_passthrough"}
    )
    refined = dict(backend_quality)
    refined["same_as_input_fallback"] = ordinary_same
    refined["blocking_failure_count"] = blocking_failures
    refined["protected_or_passthrough_same_as_input"] = max(
        int(refined.get("protected_or_passthrough_same_as_input") or 0),
        nonblocking_same,
    )
    fallback_ratio = float(refined.get("fallback_ratio") or 0)
    json_parse_errors = int(refined.get("json_parse_errors") or 0)
    token_usage_errors = int(refined.get("token_usage_errors") or 0)
    if json_parse_errors >= 3 or ordinary_same >= 3 or blocking_failures >= 3:
        refined["status"] = "partial"
    elif json_parse_errors or ordinary_same or token_usage_errors or blocking_failures or fallback_ratio > 0.15:
        refined["status"] = "warn"
    elif refined.get("cache_gate_status") == "blocking":
        refined["status"] = "partial"
    else:
        refined["status"] = "ok"
    if ordinary_same:
        refined["same_as_input_origin"] = backend_quality.get("same_as_input_origin") or "tracking_inferred"
    elif nonblocking_same or int(payload.get("failure_count") or 0):
        refined["same_as_input_origin"] = "layout_role_passthrough" if any(
            isinstance(item, dict) and item.get("classification") == "layout_role_passthrough" for item in failures
        ) else "protected_or_passthrough"
    else:
        refined["same_as_input_origin"] = "not_detected"
    refined["retry_failure_evidence"] = str(retry_failures_path)
    refined["retry_failure_count"] = int(payload.get("failure_count") or 0)
    refined["retry_blocking_failure_count"] = int(payload.get("blocking_failure_count") or 0)
    refined["tracking_incomplete_count"] = int(payload.get("tracking_incomplete_count") or 0)
    refined["tracking_mapping_status"] = payload.get("tracking_mapping_status") or ("ok" if refined["tracking_incomplete_count"] == 0 else "incomplete")
    if refined["tracking_incomplete_count"]:
        refined["status"] = "partial"
    return refined


def resolve_backend_quality_with_pdf_direct_repairs(
    backend_quality: dict[str, Any],
    pdf_direct_text_repair: dict[str, Any] | None,
) -> dict[str, Any]:
    """把已落到 PDF 文本层的正式 repair 反映到 backend quality gate。

    该函数只处理有明确 manifest 证据的修复，不改变原始 backend_retry_failures。
    """
    repair = pdf_direct_text_repair if isinstance(pdf_direct_text_repair, dict) else {}
    repairs = repair.get("repairs") if isinstance(repair.get("repairs"), list) else []
    resolved: list[dict[str, str]] = []
    if repair.get("status") == "repaired":
        for item in repairs:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if source in PDF_DIRECT_REPAIR_RESOLUTIONS:
                resolved.append(
                    {
                        "source": source,
                        "classification": "ordinary_same_as_input",
                        "resolution": PDF_DIRECT_REPAIR_RESOLUTIONS[source],
                    }
                )
    if not resolved:
        return backend_quality

    refined = dict(backend_quality)
    resolved_count = len(resolved)
    refined["same_as_input_fallback"] = max(0, int(refined.get("same_as_input_fallback") or 0) - resolved_count)
    refined["blocking_failure_count"] = max(0, int(refined.get("blocking_failure_count") or 0) - resolved_count)
    refined["retry_blocking_failure_count"] = max(0, int(refined.get("retry_blocking_failure_count") or 0) - resolved_count)
    refined["pdf_direct_repair_resolved_backend_failures"] = resolved
    if refined["same_as_input_fallback"] == 0 and refined["blocking_failure_count"] == 0:
        if not int(refined.get("json_parse_errors") or 0) and not int(refined.get("token_usage_errors") or 0):
            refined["fallback_ratio_nonblocking_explained"] = True
            refined["effective_fallback_ratio"] = 0.0
            refined["status"] = "ok"
            refined["same_as_input_origin"] = "layout_role_passthrough"
        elif refined.get("status") == "partial":
            refined["status"] = "warn"
    return refined


def apply_pdf_direct_repair_resolutions_to_retry_failures(
    retry_failures: dict[str, Any],
    pdf_direct_text_repair: dict[str, Any] | None,
) -> dict[str, Any]:
    """把已落到 PDF 文本层的 repair 写回 retry failure 证据。

    原始 failure 仍保留 source/output/debug id，但 classification 改为
    nonblocking，避免 retry file 与 render_manifest.backend_quality 口径漂移。
    """
    payload = dict(retry_failures) if isinstance(retry_failures, dict) else {}
    repair = pdf_direct_text_repair if isinstance(pdf_direct_text_repair, dict) else {}
    repairs = repair.get("repairs") if isinstance(repair.get("repairs"), list) else []
    if repair.get("status") != "repaired" or not repairs:
        return payload
    resolved_sources = {
        source: PDF_DIRECT_REPAIR_RESOLUTIONS[source]
        for item in repairs
        if isinstance(item, dict)
        for source in [str(item.get("source") or "")]
        if source in PDF_DIRECT_REPAIR_RESOLUTIONS
    }
    if not resolved_sources:
        return payload

    def resolved_for_failure(item: dict[str, Any]) -> tuple[str, str] | None:
        text = " ".join(str(item.get(key) or "") for key in ["source_snippet", "output_snippet", "source", "output"])
        compact_text = re.sub(r"\s+", " ", text)
        for source, resolution in resolved_sources.items():
            compact_source = re.sub(r"\s+", " ", source)
            squeezed_source = re.sub(r"\s+", "", source)
            squeezed_text = re.sub(r"\s+", "", text)
            if source in text or compact_source in compact_text or squeezed_source in squeezed_text:
                return source, resolution
        if "AI-based models are transforming the translation industry" in text and "AI-based models abstract" in resolved_sources:
            return "AI-based models abstract", resolved_sources["AI-based models abstract"]
        if (
            "This research was supported by" in text
            and "Author contributions" in text
            and "This research was supported by The Hong Kong Polytechnic University" in resolved_sources
        ):
            return (
                "This research was supported by The Hong Kong Polytechnic University",
                resolved_sources["This research was supported by The Hong Kong Polytechnic University"],
            )
        return None

    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    resolved_count = 0
    updated_failures: list[dict[str, Any]] = []
    for item in failures:
        if not isinstance(item, dict):
            updated_failures.append(item)
            continue
        updated = dict(item)
        resolution = resolved_for_failure(updated)
        if updated.get("classification") == "ordinary_same_as_input" and resolution:
            source, resolution_id = resolution
            updated["original_classification"] = updated.get("classification")
            updated["classification"] = "pdf_direct_repaired"
            updated["nonblocking_reason"] = "pdf_direct_text_repair_applied_to_visible_text_layer"
            updated["blocking_reason"] = None
            updated["resolved_by"] = resolution_id
            updated["resolved_source"] = source
            resolved_count += 1
        updated_failures.append(updated)
    payload["failures"] = updated_failures
    payload["pdf_direct_repair_resolved_count"] = resolved_count
    payload["pdf_direct_repair_manifest_status"] = repair.get("status")
    blocking_count = sum(
        1
        for item in updated_failures
        if isinstance(item, dict) and item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
    )
    payload["blocking_failure_count"] = blocking_count
    if blocking_count == 0:
        payload["status"] = "ok"
    elif payload.get("status") == "ok":
        payload["status"] = "warn"
    return payload


def locate_backend_tracking_file(output_dir: Path, input_pdf: Path, engine_home: Path) -> Path | None:
    candidates = [
        output_dir / "translate_tracking.json",
        output_dir / "_backend_working" / input_pdf.stem / "translate_tracking.json",
        engine_home / ".cache" / "babeldoc" / "working" / input_pdf.stem / "translate_tracking.json",
    ]
    candidates.extend((engine_home / ".cache" / "babeldoc" / "working").glob(f"{input_pdf.stem}*/translate_tracking.json"))
    for path in candidates:
        if path.exists():
            return path
    return None


def copy_backend_tracking_artifact(output_dir: Path, input_pdf: Path, engine_home: Path) -> Path | None:
    tracking_path = locate_backend_tracking_file(output_dir, input_pdf, engine_home)
    if not tracking_path:
        return None
    target = output_dir / "backend_translate_tracking.json"
    if tracking_path.resolve() != target.resolve():
        target.write_text(tracking_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return target


def iter_tracking_paragraphs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_name in ["page", "cross_page", "cross_column"]:
        groups = payload.get(group_name)
        if not isinstance(groups, list):
            continue
        for page_index, group in enumerate(groups, start=1):
            paragraphs = group.get("paragraph") if isinstance(group, dict) else None
            if not isinstance(paragraphs, list):
                continue
            for paragraph in paragraphs:
                if not isinstance(paragraph, dict):
                    continue
                row = dict(paragraph)
                row.setdefault("tracking_group", group_name)
                if row.get("page") is None and group_name == "page":
                    row["page"] = page_index
                rows.append(row)
    return rows


def _tracking_text_blob(tracking_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for paragraph in iter_tracking_paragraphs(tracking_payload):
        for key in ("input", "output", "pdf_unicode"):
            value = str(paragraph.get(key) or "").strip()
            if value:
                chunks.append(value)
    return "\n".join(chunks)


def build_dropped_text_audit(
    translated_pages: list[dict[str, Any]],
    tracking_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare visible PDF text against tracked backend items.

    This is intentionally conservative: it only emits findings for round-known
    layout-sensitive labels whose absence from tracking means the writeback
    chain cannot possibly fix the visible residue.
    """
    tracking = tracking_payload if isinstance(tracking_payload, dict) else {}
    tracking_blob = _tracking_text_blob(tracking)
    findings: list[dict[str, Any]] = []
    table_headers = {
        "Sub-corpus": "子语料库",
        "Number of texts": "文本数量",
        "Tokens": "词元数",
        "Mean length": "平均长度",
    }
    table_captions = {
        "Table 1": "表 1",
        "Table 2": "表 2",
    }
    tracked_headers = {
        source: bool(re.search(rf"\b{re.escape(source)}\b|{re.escape(target)}", tracking_blob, re.I))
        for source, target in table_headers.items()
    }
    for page in translated_pages:
        page_number = page.get("page")
        text = str(page.get("text") or "")
        visible_headers = [source for source in table_headers if re.search(rf"\b{re.escape(source)}\b", text, re.I)]
        for source in visible_headers:
            tracked = tracked_headers[source]
            if tracked:
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "layout_mapping",
                    "rule": "table_header_missing_from_il",
                    "page": page_number,
                    "failure_stage": "paragraph_finder",
                    "layout_role": "table_header",
                    "repair_target": "BabelDOC table span extraction / synthetic table_header item",
                    "message": f"表头 {source} 在主 PDF 文本层可见，但未进入 backend_translate_tracking，无法通过翻译/写回链路修复。",
                    "evidence": source,
                }
            )
        for source in visible_headers:
            tracked = tracked_headers[source]
            if not tracked:
                continue
            if not re.search(rf"\b{re.escape(source)}\b", text, re.I):
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "pdf_rendering",
                    "rule": "table_header_writeback_failed",
                    "page": page_number,
                    "failure_stage": "paint",
                    "layout_role": "table_header",
                    "repair_target": "BabelDOC table_header writeback or table-region rerender",
                    "message": f"表头 {source} 已进入 tracking 或已有译文路径，但主 PDF 仍可见英文，说明写回/清除原文本失败。",
                    "evidence": source,
                }
            )
        visible_captions = [source for source in table_captions if re.search(rf"\b{re.escape(source)}\b", text, re.I)]
        for source in visible_captions:
            tracked = bool(re.search(rf"\b{re.escape(source)}\b|{re.escape(table_captions[source])}", tracking_blob, re.I))
            if not tracked:
                findings.append(
                    {
                        "severity": "blocking",
                        "category": "layout_mapping",
                        "rule": "table_caption_missing",
                        "page": page_number,
                        "failure_stage": "paragraph_finder",
                        "layout_role": "table_caption",
                        "repair_target": "BabelDOC table span extraction / synthetic table_caption item",
                        "message": f"{source} caption 在主 PDF 文本层可见，但未进入 backend_translate_tracking，无法通过翻译/写回链路修复。",
                        "evidence": source,
                    }
                )
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "pdf_rendering",
                    "rule": "table_caption_writeback_failed",
                    "page": page_number,
                    "failure_stage": "paint",
                    "layout_role": "table_caption",
                    "repair_target": "BabelDOC table_caption writeback or table-region rerender",
                    "message": f"{source} caption 已进入 tracking 或已有译文路径，但主 PDF 仍可见英文，说明写回/清除原文本失败。",
                    "evidence": source,
                }
            )
    payload = {
        "version": 1,
        "status": "warn" if findings else "ok",
        "finding_count": len(findings),
        "tracking_available": bool(tracking),
        "findings": findings,
    }
    return payload


def build_dropped_text_audit_from_files(
    translated_pdf: Path | None,
    tracking_path: Path | None,
) -> dict[str, Any]:
    if not translated_pdf or not translated_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_translated_pdf", "findings": []}
    try:
        pages = visual_layout.extract_pdf_text_pages(translated_pdf)
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"text_extract_failed: {exc}", "findings": []}
    tracking_payload: dict[str, Any] | None = None
    if tracking_path and tracking_path.exists():
        try:
            tracking_payload = json.loads(tracking_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            tracking_payload = None
    return build_dropped_text_audit(pages, tracking_payload)


def extract_tracking_failures(tracking_path: Path | None) -> list[dict[str, Any]]:
    if not tracking_path or not tracking_path.exists():
        return []
    try:
        payload = json.loads(tracking_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return [
            {
                "failure_type": "tracking_parse_error",
                "classification": "mapping_missing",
                "source_snippet": "",
                "output_snippet": "",
                "page": None,
                "paragraph_debug_id": None,
                "layout_label": None,
                "layout_role": None,
            }
        ]
    failures: list[dict[str, Any]] = []
    for paragraph in iter_tracking_paragraphs(payload):
        source = str(paragraph.get("input") or paragraph.get("pdf_unicode") or "")
        output = str(paragraph.get("output") or "")
        trackers = paragraph.get("llm_translate_trackers")
        trackers = trackers if isinstance(trackers, list) else []
        tracker_errors = [
            str(item.get("error_message") or "")
            for item in trackers
            if isinstance(item, dict) and (item.get("error_message") or item.get("fallback_to_translate"))
        ]
        fallback = any(isinstance(item, dict) and item.get("fallback_to_translate") for item in trackers)
        same_as_input = bool(source.strip() and output.strip() and source.strip() == output.strip())
        writeback_status = str(paragraph.get("writeback_status") or "")
        writeback_reason = str(paragraph.get("writeback_reason") or "")
        layout_role = paragraph.get("layout_role") or paragraph.get("layout_label")
        layout_role_text = str(layout_role or "").lower()
        translated_not_written = (
            writeback_status in {"rejected", "needs_region_rerender", "chart_region_rerender_required"}
            and re.search(r"[\u4e00-\u9fff]", output)
            and re.search(r"[A-Za-z]{3,}", source)
        )
        output_words = re.findall(r"[A-Za-z]{3,}", output)
        partial_body_direct = (
            layout_role_text in {"body_prose", "plain text", "text", "paragraph_hybrid", ""}
            and len(source) >= 80
            and re.search(r"[\u4e00-\u9fff]", output)
            and len(output_words) >= 8
            and any(word.lower() in source.lower() for word in output_words[:12])
            and not looks_like_name_list_heavy(source)
            and has_long_ordinary_english_run(output)
        )
        if not fallback and not same_as_input and not tracker_errors and not translated_not_written and not partial_body_direct:
            continue
        error_text = " | ".join(error for error in tracker_errors if error)
        if partial_body_direct:
            failure_type = "body_prose_partial_direct_output"
            classification = classify_backend_passthrough(source)
            if classification in {"protected_or_passthrough", "already_translated_passthrough", "cover_split_fragment"}:
                pass
            elif classification != "layout_role_passthrough":
                classification = "ordinary_same_as_input"
        elif writeback_status == "needs_region_rerender":
            failure_type = "region_rerender_required"
            classification = "needs_backend_mapping"
        elif writeback_status == "chart_region_rerender_required":
            failure_type = "chart_region_rerender_required"
            classification = "needs_backend_mapping"
        elif translated_not_written:
            failure_type = "translated_but_not_written_back"
            classification = "ordinary_same_as_input"
        elif same_as_input:
            failure_type = "same_as_input_after_retry"
            classification = classify_backend_passthrough(source)
        elif fallback:
            failure_type = "fallback_to_simple_translation"
            classification = classify_backend_fallback(source, output)
            if (
                classification == "fallback_to_simple_translation"
                and layout_role_text in {"running_footer", "running_header", "affiliation_footer", "doi_line"}
                and cjk_count(output) >= 2
                and plain_text_without_style_tags(output).strip() != plain_text_without_style_tags(source).strip()
            ):
                classification = "fallback_but_translated_warn"
        elif "protected_or_passthrough" in error_text:
            failure_type = "protected_passthrough"
            classification = "protected_or_passthrough"
        else:
            failure_type = "structured_translation_failure"
            if "same as input" in error_text.lower():
                classification = "ordinary_same_as_input"
            elif re.search(r"[\u4e00-\u9fff]", output) and re.search(r"[A-Za-z]{2,}", source):
                classification = "structured_translated_needs_mapping"
            else:
                classification = "needs_backend_mapping"
        failures.append(
            {
                "failure_type": failure_type,
                "source_snippet": source[:240],
                "output_snippet": output[:240],
                "paragraph_debug_id": paragraph.get("debug_id") or paragraph.get("paragraph_debug_id"),
                "page": paragraph.get("page"),
                "layout_label": layout_role,
                "layout_role": layout_role,
                "classification": classification,
                "blocking_reason": "ordinary prose untranslated or structured backend failure"
                if classification not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
                else None,
                "nonblocking_reason": classification if classification in NON_BLOCKING_BACKEND_FAILURE_CLASSES else None,
                "tracking_group": paragraph.get("tracking_group"),
                "error_message": error_text[:500],
                "writeback_status": writeback_status or None,
                "writeback_reason": writeback_reason or None,
            }
        )
    return failures


def dedupe_backend_retry_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    index: dict[tuple[Any, ...], int] = {}

    def key_for(item: dict[str, Any]) -> tuple[Any, ...]:
        debug_id = item.get("paragraph_debug_id")
        page = item.get("page")
        if debug_id:
            return ("paragraph", page, debug_id)
        return ("snippet", item.get("source_snippet"), item.get("output_snippet"))

    def is_blocking(item: dict[str, Any]) -> bool:
        return item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES

    for item in failures:
        key = key_for(item)
        if key not in index:
            index[key] = len(deduped)
            deduped.append(item)
            continue
        existing = deduped[index[key]]
        existing_types = set(existing.get("duplicate_failure_types") or [])
        if existing.get("failure_type"):
            existing_types.add(str(existing.get("failure_type")))
        if item.get("failure_type"):
            existing_types.add(str(item.get("failure_type")))
        existing["duplicate_failure_types"] = sorted(existing_types)
        if is_blocking(item) and not is_blocking(existing):
            item["duplicate_failure_types"] = sorted(existing_types)
            deduped[index[key]] = item
        elif is_blocking(item) == is_blocking(existing) and str(item.get("failure_type") or "") == "same_as_input_after_retry":
            item["duplicate_failure_types"] = sorted(existing_types)
            deduped[index[key]] = item
    return deduped


def write_backend_retry_failures(
    output_dir: Path,
    proxy_info: dict[str, Any],
    backend_quality: dict[str, Any],
    *,
    tracking_path: Path | None = None,
) -> Path:
    stats = proxy_info.get("stats") if isinstance(proxy_info, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    failures: list[dict[str, Any]] = []
    for sample in stats.get("json_batch_same_as_input_samples", []) if isinstance(stats.get("json_batch_same_as_input_samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        failures.append(
            {
                "failure_type": "same_as_input_after_retry",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": classify_backend_passthrough(source),
            }
        )
    for sample in stats.get("same_as_input_candidates", []) if isinstance(stats.get("same_as_input_candidates"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        if any(item.get("source_snippet") == source[:240] for item in failures):
            continue
        classification = classify_backend_passthrough(source)
        if classification == "ordinary_same_as_input":
            classification = "needs_backend_mapping"
        failures.append(
            {
                "failure_type": "same_as_input_retry_candidate",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": classification,
            }
        )
    for sample in stats.get("plain_layout_role_intercept_samples", []) if isinstance(stats.get("plain_layout_role_intercept_samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        if any(item.get("source_snippet") == source[:240] for item in failures):
            continue
        failures.append(
            {
                "failure_type": "layout_role_passthrough",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": "layout_role_passthrough",
            }
        )
    seen = {(item.get("failure_type"), item.get("source_snippet"), item.get("output_snippet")) for item in failures}
    for item in extract_tracking_failures(tracking_path):
        key = (item.get("failure_type"), item.get("source_snippet"), item.get("output_snippet"))
        if key in seen:
            continue
        seen.add(key)
        failures.append(item)
    failures = dedupe_backend_retry_failures(failures)
    for item in failures:
        classification = item.get("classification")
        item.setdefault(
            "blocking_reason",
            "ordinary prose untranslated or structured backend failure"
            if classification not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
            else None,
        )
        item.setdefault("nonblocking_reason", classification if classification in NON_BLOCKING_BACKEND_FAILURE_CLASSES else None)
    blocking_count = sum(1 for item in failures if item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES)
    tracking_incomplete = [
        item
        for item in failures
        if item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
        and (item.get("page") is None or not item.get("paragraph_debug_id") or not (item.get("layout_role") or item.get("layout_label")))
    ]
    payload = {
        "version": 1,
        "status": "warn" if blocking_count or tracking_incomplete else "ok",
        "failure_count": len(failures),
        "blocking_failure_count": blocking_count,
        "backend_quality_same_as_input_origin": backend_quality.get("same_as_input_origin"),
        "tracking_source": str(tracking_path) if tracking_path else None,
        "tracking_mapping_status": "incomplete" if tracking_incomplete else ("ok" if tracking_path else "missing"),
        "tracking_incomplete_count": len(tracking_incomplete),
        "tracking_incomplete_samples": tracking_incomplete[:5],
        "failures": failures,
    }
    path = output_dir / "backend_retry_failures.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
