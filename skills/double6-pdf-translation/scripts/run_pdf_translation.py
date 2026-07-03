#!/usr/bin/env python3
from __future__ import annotations

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
import metadata_label_repair_runtime
import policy_utils
import toc_repair_runtime
import visual_layout
from hymt_compat_proxy import ProxyConfig, start_hymt_compat_proxy

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
    DEFAULT_HYMT_COMPAT_PROXY_PORT,
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
    resolve_api_key,
    resolve_base_url,
    resolve_base_url_inference,
    redacted_command,
    resolve_pdf_layout_profile,
    resolved_pdf2zh_backend,
    should_enable_hymt_compat_proxy,
    should_use_qwen_cli_adapter,
)
























from pdf_translation_artifacts_runtime import *  # noqa: F401,F403
from pdf_translation_quality_runtime import *  # noqa: F401,F403
from pdf_translation_delivery_runtime import *  # noqa: F401,F403

def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    raw_base_url = getattr(args, "base_url", "")
    args.provider = getattr(args, "provider", os.environ.get("LOCAL_TRANSLATION_PROVIDER", ""))
    args.base_url = resolve_base_url(args.provider, raw_base_url)
    args.api_key = resolve_api_key(args.provider, getattr(args, "api_key", ""))
    if not hasattr(args, "inferred_translation_provider"):
        args.inferred_translation_provider = resolve_base_url_inference(args.provider, raw_base_url)
    input_pdf = Path(args.input_pdf).expanduser().resolve()
    args.input_pdf = str(input_pdf)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(input_pdf).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    engine_home = Path(args.engine_home).expanduser().resolve() if args.engine_home else default_engine_home()
    engine_home.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "pdf2zh-next.log"
    preflight_path = output_dir / "preflight_report.json"
    preflight_report: dict[str, Any]
    if bool(getattr(args, "skip_preflight", False)):
        preflight_report = {
            "schema_version": "1.0",
            "ok": True,
            "strict": False,
            "skipped": True,
            "reason": "skip_preflight_requested",
            "backend": resolved_pdf2zh_backend(args),
        }
        preflight_path.write_text(json.dumps(preflight_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        preflight_args = SimpleNamespace(
            strict=True,
            output=str(preflight_path),
            pdf2zh_binary=getattr(args, "pdf2zh_binary", None),
            pdf2zh_backend=getattr(args, "pdf2zh_backend", DEFAULT_PDF2ZH_BACKEND),
            provider=getattr(args, "provider", ""),
            base_url=getattr(args, "base_url", DEFAULT_BASE_URL),
            model=getattr(args, "model", DEFAULT_MODEL),
            api_key=getattr(args, "api_key", DEFAULT_API_KEY),
            inferred_translation_provider=getattr(args, "inferred_translation_provider", None),
            hymt_compat_proxy_port=getattr(args, "hymt_compat_proxy_port", DEFAULT_HYMT_COMPAT_PROXY_PORT),
            command_timeout=10.0,
            endpoint_timeout=3.0,
            skip_endpoint_check=False,
            engine_home=str(engine_home),
        )
        preflight_report = preflight_runtime.build_report(preflight_args)
        preflight_path.write_text(json.dumps(preflight_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if bool(getattr(args, "preflight_only", False)) or not preflight_report.get("ok"):
            status = "ok" if preflight_report.get("ok") else "preflight_failed"
            render_manifest = {
                "version": 1,
                "status": status,
                "engine": "pdfmathtranslate-next",
                "pdf_backend": "pdfmathtranslate-next",
                "backend_resolution": preflight_report.get("backend"),
                "backend_health": preflight_report,
                "preflight": {"status": status, "report": str(preflight_path), "skipped": False},
                "input_pdf": str(input_pdf),
                "outputs": {
                    "translated_pdf": None,
                    "mono_pdf": None,
                    "dual_pdf": None,
                    "backend_dual_pdf": None,
                    "backend_dual_pdf_role": None,
                },
                "validation": {
                    "translated_text_chars": 0,
                    "translated_text_extraction_method": "preflight_only" if preflight_report.get("ok") else "preflight_failed",
                    "cjk_char_count": 0,
                    "has_translated_pdf": False,
                    "gates": {
                        "version": 1,
                        "status": "ok" if preflight_report.get("ok") else "partial",
                        "strict": bool(getattr(args, "strict_delivery_gates", False)),
                        "worst_gate": "ok" if preflight_report.get("ok") else "blocking",
                        "gates": [] if preflight_report.get("ok") else [
                            {
                                "name": "runtime_preflight",
                                "status": "blocking",
                                "evidence": str(preflight_path),
                                "recommendation": "修复 preflight_report.json 中的 required runtime failures 后重跑。",
                            }
                        ],
                    },
                },
                "returncode": 0 if preflight_report.get("ok") else 2,
                "duration_seconds": round(time.monotonic() - started, 3),
                "errors": [] if preflight_report.get("ok") else [{"error_type": "runtime_preflight_failed", "report": str(preflight_path)}],
            }
            render_path = output_dir / "render_manifest.json"
            render_path.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            backend_manifest = {
                "version": 1,
                "status": status,
                "backend": "pdfmathtranslate-next",
                "backend_source": preflight_report.get("backend", {}).get("source"),
                "render_manifest": str(render_path),
                "preflight": render_manifest["preflight"],
                "backend_health": preflight_report,
                "fallback": "runtime_preflight" if not preflight_report.get("ok") else None,
            }
            (output_dir / "backend_run_manifest.json").write_text(
                json.dumps(backend_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return backend_manifest
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(engine_home),
            "XDG_CACHE_HOME": str(engine_home / ".cache"),
            "HF_HOME": str(engine_home / ".hf-home"),
            "UV_CACHE_DIR": str(engine_home / ".uv-cache"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    for key in ["XDG_CACHE_HOME", "HF_HOME", "UV_CACHE_DIR"]:
        Path(env[key]).mkdir(parents=True, exist_ok=True)

    source_override, source_selection = discover_latex_source(input_pdf, args, output_dir=output_dir)
    prepare_manifest = prepare_source(input_pdf, output_dir, source_override=source_override)
    prepare_manifest["source_selection"] = {
        **source_selection,
        "source_of_truth": "latex_source" if source_override and source_override.suffix.lower() == ".tex" else "pdf_direct",
        "render_input_pdf": str(input_pdf),
        "user_flag_required": False,
    }
    if source_override and source_override.suffix.lower() == ".tex":
        prepare_manifest["source_of_truth"] = "latex_source"
    else:
        prepare_manifest["source_of_truth"] = "pdf_direct"
    (output_dir / "source_manifest.json").write_text(
        json.dumps(prepare_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    glossary_path = write_glossary(output_dir, prepare_manifest)
    quality_artifacts = enrich_quality_artifacts(output_dir, prepare_manifest, glossary_path)
    context_file = output_dir / "document_memory.json"
    args.custom_system_prompt = build_backend_system_prompt(args.custom_system_prompt, output_dir)
    args.resolved_pdf_layout_profile = resolve_pdf_layout_profile(args, input_pdf)
    original_base_url = args.base_url
    skip_pdf_backend = (
        bool(getattr(args, "skip_pdf_backend_when_latex_direct", False))
        and source_override is not None
        and source_override.suffix.lower() == ".tex"
        and getattr(args, "latex_render_mode", DEFAULT_LATEX_RENDER_MODE) != "off"
    )
    proxy_server = None
    proxy_info: dict[str, Any] = {
        "mode": getattr(args, "hymt_compat_proxy", "auto"),
        "enabled": False,
        "upstream_base_url": original_base_url,
        "proxy_base_url": None,
    }
    if should_enable_hymt_compat_proxy(args) and not skip_pdf_backend:
        proxy_config = ProxyConfig(
            model=args.model,
            upstream_base_url=original_base_url.rstrip("/"),
            api_key=args.api_key,
            port=int(getattr(args, "hymt_compat_proxy_port", DEFAULT_HYMT_COMPAT_PROXY_PORT)),
            policy_context_path=str(context_file),
        )
        try:
            proxy_server = start_hymt_compat_proxy(proxy_config)
            args.base_url = proxy_config.base_url
            proxy_info.update({"enabled": True, "proxy_base_url": proxy_config.base_url})
        except OSError as exc:
            if getattr(args, "hymt_compat_proxy", "auto") == "on":
                raise
            proxy_info.update({"enabled": False, "error": f"proxy_start_failed: {exc}"})
    command = build_pdf2zh_command(args, output_dir, context_file=context_file)
    cloud_layout = maybe_run_cloud_layout(args, output_dir)

    errors: list[dict[str, Any]] = []
    returncode = 0
    status = "ok"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write("COMMAND: " + " ".join(redacted_command(command, args.api_key)) + "\n")
            log.write(f"MODEL: {args.model}\n")
            log.write(f"BASE_URL: {args.base_url}\n")
            log.write(f"HYMT_COMPAT_PROXY: {json.dumps(proxy_info, ensure_ascii=False)}\n")
            log.write(f"LOCAL_MAX_CONCURRENCY: {args.local_max_concurrency}\n")
            log.write(f"OPENAI_JSON_MODE: {args.openai_json_mode}\n")
            log.write(f"PDF_LAYOUT_PROFILE: {args.resolved_pdf_layout_profile}\n")
            log.write(f"TIMEOUT_SEC: {args.timeout}\n")
            log.write(f"ENGINE_HOME: {engine_home}\n")
            log.flush()
            if skip_pdf_backend:
                log.write("SKIPPED_PDF_BACKEND: latex direct render is required for this source case.\n")
            else:
                try:
                    proc = subprocess.run(
                        command,
                        cwd=output_dir,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=args.timeout,
                        check=False,
                    )
                    returncode = int(proc.returncode)
                    if returncode != 0:
                        status = "error"
                        errors.append({"error_type": "nonzero_exit", "returncode": returncode})
                except subprocess.TimeoutExpired:
                    returncode = 124
                    status = "error"
                    errors.append({"error_type": "timeout", "timeout_seconds": args.timeout})
                    log.write(f"\nTIMEOUT: exceeded {args.timeout} seconds\n")
    finally:
        if proxy_server is not None:
            proxy_info["stats"] = dict(getattr(proxy_server, "stats", {}) or {})
        if proxy_server is not None:
            proxy_server.shutdown()
        args.base_url = original_base_url

    backend_quality = parse_backend_quality(log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "")
    translation_cache = parse_translation_cache_stats(log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "")
    translation_cache = enrich_translation_cache_stats(translation_cache, proxy_info)
    if bool(getattr(args, "ignore_translation_cache", False)) and translation_cache.get("total_cache_hits", 0):
        backend_quality["cache_gate_status"] = "blocking"
        backend_quality["cache_gate_reason"] = "ignore_translation_cache_requested_but_cache_hits_detected"
        backend_quality["status"] = "partial"
        if status == "ok":
            status = "partial"
    backend_quality = annotate_backend_quality_origin(backend_quality, proxy_info)
    backend_tracking_path = copy_backend_tracking_artifact(output_dir, input_pdf, engine_home)
    hymt_proxy_stats_path = output_dir / "hymt_proxy_stats.json"
    hymt_proxy_stats_path.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "ok" if proxy_info.get("enabled") else "skipped",
                "proxy": proxy_info,
                "stats": proxy_info.get("stats") if isinstance(proxy_info.get("stats"), dict) else {},
                "backend_quality_same_as_input_origin": backend_quality.get("same_as_input_origin"),
                "stats_owner": "run_pdf_translation.py",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    backend_retry_failures_path = write_backend_retry_failures(output_dir, proxy_info, backend_quality, tracking_path=backend_tracking_path)
    backend_quality = refine_backend_quality_with_retry_failures(backend_quality, backend_retry_failures_path)
    if status == "ok" and backend_quality.get("status") == "partial":
        status = "partial"

    pdfs = [] if bool(source_override and source_override.suffix.lower() == ".tex" and args.skip_pdf_backend_when_latex_direct) else collect_pdfs(output_dir)
    selected_outputs = select_pdf_outputs(pdfs)
    pdf_backend_outputs = dict(selected_outputs)
    latex_direct_manifest = run_latex_direct_render(
        args,
        input_pdf,
        output_dir,
        source_override if source_override and source_override.suffix.lower() == ".tex" else None,
        env,
    )
    if latex_direct_manifest.get("status") == "ok" and latex_direct_manifest.get("translated_pdf"):
        selected_outputs = {
            **selected_outputs,
            "translated_pdf": latex_direct_manifest["translated_pdf"],
            "mono_pdf": latex_direct_manifest["translated_pdf"],
            "latex_direct_pdf": latex_direct_manifest["translated_pdf"],
            "pdf_backend_translated_pdf": pdf_backend_outputs.get("translated_pdf"),
            "pdf_backend_mono_pdf": pdf_backend_outputs.get("mono_pdf"),
            "pdf_backend_dual_pdf": pdf_backend_outputs.get("dual_pdf"),
        }
    elif source_override and source_override.suffix.lower() == ".tex" and args.latex_render_mode != "off":
        if args.latex_render_mode == "required":
            status = "error"
            errors.append({"error_type": "latex_direct_render_failed", "manifest": str(output_dir / "direct_latex_render_manifest.json")})
        elif status == "ok":
            status = "partial"
            errors.append({"error_type": "latex_direct_render_unavailable_pdf_backend_fallback", "manifest": str(output_dir / "direct_latex_render_manifest.json")})
    pdf_direct_text_repair = apply_pdf_direct_text_repairs(
        Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None,
        input_pdf,
        output_dir,
        apply_overlay=bool(getattr(args, "allow_pdf_direct_text_overlay", False)),
    )
    quality_artifacts["pdf_direct_text_repair"] = pdf_direct_text_repair
    backend_quality = resolve_backend_quality_with_pdf_direct_repairs(backend_quality, pdf_direct_text_repair)
    if status == "partial" and backend_quality.get("status") == "ok" and not errors:
        status = "ok"
    visual_repair_manifest = maybe_build_visual_repair_output(
        args,
        input_pdf,
        output_dir,
        selected_outputs,
        backend_tracking_path,
    )
    quality_artifacts["visual_repair"] = visual_repair_manifest
    toc_repair_manifest = toc_repair_runtime.apply_toc_repair(
        source_pdf=input_pdf,
        translated_pdf=Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None,
        output_dir=output_dir,
        pages_selection=getattr(args, "toc_repair_pages", None),
        mode=getattr(args, "toc_repair", "auto"),
        engine_home=engine_home,
    )
    quality_artifacts["toc_repair"] = toc_repair_manifest
    if toc_repair_manifest.get("status") in {"applied", "applied_with_untranslated_titles"} and toc_repair_manifest.get("output_pdf"):
        repaired_pdf = Path(str(toc_repair_manifest["output_pdf"]))
        if repaired_pdf.exists():
            selected_outputs["translated_pdf"] = str(repaired_pdf)
            selected_outputs["mono_pdf"] = str(repaired_pdf)
            selected_outputs["toc_repaired_pdf"] = str(repaired_pdf)
    metadata_label_repair_manifest = metadata_label_repair_runtime.apply_metadata_label_repair(
        source_pdf=input_pdf,
        translated_pdf=Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None,
        output_dir=output_dir,
        mode=getattr(args, "metadata_label_repair", "auto"),
        engine_home=engine_home,
    )
    quality_artifacts["metadata_label_repair"] = metadata_label_repair_manifest
    if metadata_label_repair_manifest.get("status") in {"applied", "partial"} and metadata_label_repair_manifest.get("output_pdf"):
        repaired_pdf = Path(str(metadata_label_repair_manifest["output_pdf"]))
        if repaired_pdf.exists():
            selected_outputs["translated_pdf"] = str(repaired_pdf)
            selected_outputs["mono_pdf"] = str(repaired_pdf)
            selected_outputs["metadata_label_repaired_pdf"] = str(repaired_pdf)
    pdfs = collect_pdfs(output_dir)
    bilingual_manifest = build_standard_bilingual_output(
        input_pdf,
        output_dir,
        selected_outputs,
        enabled=bool(args.dual and args.bilingual_layout == "en-left-zh-right"),
        render_mode=args.bilingual_render_mode,
        raster_dpi=args.bilingual_raster_dpi,
    )
    if bilingual_manifest.get("status") == "ok" and bilingual_manifest.get("output_pdf"):
        selected_outputs["dual_pdf"] = str(bilingual_manifest["output_pdf"])
        selected_outputs["standard_bilingual_pdf"] = str(bilingual_manifest["output_pdf"])
        latex_direct_dual = mirror_latex_direct_bilingual_output(bilingual_manifest, latex_direct_manifest, selected_outputs)
        if latex_direct_dual:
            bilingual_manifest["latex_direct_dual_pdf"] = latex_direct_dual
    backend_dual_intermediate = relocate_backend_dual_intermediate(
        output_dir,
        pdf_backend_outputs.get("dual_pdf"),
        selected_outputs.get("standard_bilingual_pdf") or selected_outputs.get("dual_pdf"),
    )
    selected_outputs["backend_dual_pdf"] = backend_dual_intermediate
    selected_outputs["backend_dual_pdf_role"] = "intermediate" if backend_dual_intermediate else None
    if bilingual_manifest.get("status") == "ok":
        pdfs = collect_pdfs(output_dir)
    if status == "ok" and not selected_outputs["translated_pdf"]:
        status = "error"
        errors.append(
            {
                "error_type": "missing_translated_pdf",
                "message": "pdf2zh-next exited with code 0 but no translated PDF was found in the output directory.",
            }
        )
    translated_text, translated_text_method = extract_pdf_text(
        Path(selected_outputs["translated_pdf"]) if selected_outputs["translated_pdf"] else None
    )
    quality_artifacts["coverage_gate"] = check_translation.build_coverage_gate(prepare_manifest, translated_text)
    prepare_manifest["coverage_gate"] = quality_artifacts["coverage_gate"]
    (output_dir / "source_manifest.json").write_text(
        json.dumps(prepare_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    visual_check_pages = visual_layout.parse_page_selection(getattr(args, "visual_check_pages", "auto"))
    skip_visual_eval = bool(getattr(args, "skip_visual_eval", False))
    visual_report_path = output_dir / "visual_layout_report.json"
    dropped_text_audit_path = output_dir / "dropped_text_audit.json"
    paragraph_audit_path = output_dir / "paragraph_label_audit.json"
    dual_visual_report_path = output_dir / "dual_visual_report.json"
    if skip_visual_eval:
        visual_report = {
            "version": 1,
            "status": "skipped",
            "reason": "skip_visual_eval_requested",
            "findings": [],
            "source_pdf": str(input_pdf),
            "translated_pdf": selected_outputs["translated_pdf"],
            "visual_check_pages": [],
        }
        dropped_text_audit = {"version": 1, "status": "skipped", "reason": "skip_visual_eval_requested", "findings": []}
        paragraph_audit = {"version": 1, "status": "skipped", "reason": "skip_visual_eval_requested", "pages": []}
        dual_visual_report = {
            "version": 1,
            "status": "skipped",
            "delivery_status": "skipped",
            "reason": "skip_visual_eval_requested",
            "findings": [],
        }
        visual_report_path.write_text(json.dumps(visual_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dropped_text_audit_path.write_text(json.dumps(dropped_text_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paragraph_audit_path.write_text(json.dumps(paragraph_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dual_visual_report_path.write_text(json.dumps(dual_visual_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        visual_report = visual_layout.build_visual_layout_report(
            input_pdf,
            Path(selected_outputs["translated_pdf"]) if selected_outputs["translated_pdf"] else None,
            output_dir,
            pages=visual_check_pages,
        )
        dropped_text_audit = build_dropped_text_audit_from_files(
            Path(selected_outputs["translated_pdf"]) if selected_outputs["translated_pdf"] else None,
            backend_tracking_path,
        )
        dropped_text_audit_path.write_text(json.dumps(dropped_text_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if dropped_text_audit.get("findings"):
            visual_report.setdefault("findings", [])
            visual_report["findings"].extend(dropped_text_audit["findings"])
            visual_report["status"] = "warn"
            visual_report["dropped_text_audit"] = str(dropped_text_audit_path)
        visual_report_path.write_text(json.dumps(visual_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    standard_dual_pdf = Path(selected_outputs["standard_bilingual_pdf"]) if selected_outputs.get("standard_bilingual_pdf") else None
    backend_dual_pdf = Path(selected_outputs["backend_dual_pdf"]) if selected_outputs.get("backend_dual_pdf") else None
    mono_pdf = Path(selected_outputs["mono_pdf"]) if selected_outputs.get("mono_pdf") else (Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None)
    if not skip_visual_eval:
        dual_visual_report = visual_layout.build_dual_visual_report(
            input_pdf,
            mono_pdf,
            standard_dual_pdf,
            backend_dual_pdf,
            output_dir,
        )
        dual_visual_report_path.write_text(json.dumps(dual_visual_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paragraph_audit = visual_layout.build_paragraph_label_audit(
            Path(selected_outputs["translated_pdf"]) if selected_outputs["translated_pdf"] else None,
            output_dir,
            pages=visual_check_pages,
        )
        paragraph_audit_path.write_text(json.dumps(paragraph_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latex_direct_primary = latex_direct_manifest.get("status") == "ok"
    if latex_direct_primary:
        rerender_candidates = {
            "version": 1,
            "status": "ok",
            "candidate_count": 0,
            "render_status": status,
            "candidates": [],
            "scope": "latex_direct_primary_render",
            "pdf_backend_candidates_skipped": True,
        }
    else:
        rerender_candidates = build_rerender_candidates(output_dir, prepare_manifest, translated_text, backend_quality, {})
    append_visual_rerender_candidates(
        rerender_candidates,
        visual_report,
        latex_baseline_audit=latex_direct_manifest.get("latex_baseline_audit"),
    )
    append_visual_rerender_plan(output_dir, visual_report)
    latex_quality_gate = policy_utils.load_json(latex_direct_manifest.get("latex_direct_quality_gate"))
    if isinstance(latex_quality_gate, dict) and latex_quality_gate.get("status") in {"blocking", "warn"}:
        for issue in latex_quality_gate.get("issues", []) if isinstance(latex_quality_gate.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            repair_type = str(issue.get("repair_type") or "")
            rerender_mode = (
                "latex_reflow_patch_plan"
                if repair_type == "latex_reflow_patch_plan"
                else "coverage_diff_review"
                if repair_type == "coverage_diff_review"
                else "full_pipeline"
            )
            recommendation = (
                "LaTeX direct 页数差异需先复核 latex_reflow_plan 或内容覆盖差异，不默认全量重跑。"
                if rerender_mode in {"latex_reflow_patch_plan", "coverage_diff_review"}
                else "LaTeX direct 质量门未通过；需修复对应 segment 后重新编译主 PDF。"
            )
            rule = str(issue.get("rule") or "latex_direct_quality_gate")
            layer = (
                "translation_execution"
                if rule in {"partial_segment_translation", "untranslated_english_section", "ordinary_english_residue", "segment_empty_or_fallback"}
                else "protected_elements"
                if rule in {"missing_protected_url_or_doi", "missing_latex_command"}
                else "layout_mapping"
                if rule == "latex_paragraph_structure_drift"
                else "pdf_rendering"
            )
            add_rerender_candidate(
                rerender_candidates.setdefault("candidates", []),
                rule=rule,
                layer=layer,
                severity=str(issue.get("severity") or "warn"),
                block_id=str(issue.get("segment_id") or "document"),
                evidence=str(issue.get("evidence") or ""),
                recommendation=recommendation,
                rerender_mode=rerender_mode,
            )
        rerender_candidates["candidate_count"] = len(rerender_candidates.get("candidates", []))
        rerender_candidates["status"] = "warn" if rerender_candidates.get("candidates") else "ok"
    (output_dir / "rerender_candidates.json").write_text(
        json.dumps(rerender_candidates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pipeline_status_for_gates = (
        "ok"
        if status == "partial"
        and not errors
        and backend_quality.get("status") == "ok"
        and bool(selected_outputs["translated_pdf"])
        else status
    )
    delivery_gates = build_delivery_gates(
        visual_report=visual_report,
        dual_visual_report=dual_visual_report,
        backend_quality=backend_quality,
        rerender_candidates=rerender_candidates,
        translated_text=translated_text,
        strict=bool(getattr(args, "strict_delivery_gates", False)),
        pipeline_status=pipeline_status_for_gates,
        has_translated_pdf=bool(selected_outputs["translated_pdf"]),
        latex_baseline_audit=latex_direct_manifest.get("latex_baseline_audit"),
        actual_render_source="latex_direct" if latex_direct_primary else None,
        latex_direct_quality_gate=latex_quality_gate,
        quality_report_text=(output_dir / "quality_report.md").read_text(encoding="utf-8", errors="replace") if (output_dir / "quality_report.md").exists() else "",
        pdf_rerender_plan=policy_utils.load_json(output_dir / "pdf_rerender_plan.json"),
        pdf_direct_text_repair=pdf_direct_text_repair,
    )
    if skip_visual_eval:
        delivery_gates = build_fast_full_translation_draft_gates(
            pipeline_status=status,
            has_translated_pdf=bool(selected_outputs["translated_pdf"]),
            bilingual_manifest=bilingual_manifest,
            backend_quality=backend_quality,
            previous_gates=delivery_gates,
        )
        if status != "error" and delivery_gates.get("status") == "ok":
            status = "ok"
    if status == "ok" and delivery_gates["status"] == "partial":
        status = "partial"

    render_manifest = {
        "version": 1,
        "status": status,
        "engine": "latex-direct-external-pdf2zh-skill" if latex_direct_manifest.get("status") == "ok" else "pdfmathtranslate-next",
        "engine_role": "latex_source_primary" if latex_direct_manifest.get("status") == "ok" else "default_strong_pdf_backend",
        "pdf_backend": "pdfmathtranslate-next",
        "engine_source": args.pdf2zh_backend if not args.pdf2zh_binary else "explicit_binary",
        "backend_resolution": resolved_pdf2zh_backend(args),
        "backend_health": preflight_report,
        "preflight": {
            "status": "skipped" if preflight_report.get("skipped") else "ok" if preflight_report.get("ok") else "failed",
            "report": str(preflight_path),
            "skipped": bool(preflight_report.get("skipped")),
        },
        "backend_wrapper": str(Path(__file__).resolve().with_name("pdf2zh_backend.py")) if args.pdf2zh_backend == "module" and not args.pdf2zh_binary else None,
        "external_pdf2zh_skill_path": str(external_pdf2zh_skill_root()) if external_pdf2zh_skill_root() else None,
        "command": redacted_command(command, args.api_key),
        "pdf_backend_skipped": skip_pdf_backend,
        "engine_home": str(engine_home),
        "engine_home_scope": "shared",
        "cache_dirs": {
            "HF_HOME": env["HF_HOME"],
            "UV_CACHE_DIR": env["UV_CACHE_DIR"],
            "babeldoc_working_dir": str(output_dir / "_backend_working" / input_pdf.stem),
        },
        "ignore_translation_cache": bool(getattr(args, "ignore_translation_cache", False)),
        "backend_debug_artifacts": bool(getattr(args, "backend_debug_artifacts", True)),
        "backend_unsupported_options": list(getattr(args, "backend_unsupported_options", []) or []),
        "translation_cache": translation_cache,
        "model": args.model,
        "provider": getattr(args, "provider", ""),
        "base_url": original_base_url,
        "base_url_inference": getattr(args, "inferred_translation_provider", None),
        "backend_base_url": proxy_info["proxy_base_url"] or original_base_url,
        "openai_reasoning_effort": args.openai_reasoning_effort,
        "translator_mode": "qwen-cli" if should_use_qwen_cli_adapter(args) else "openai",
        "pdf_layout_profile": getattr(args, "resolved_pdf_layout_profile", getattr(args, "pdf_layout_profile", "auto")),
        "local_max_concurrency": args.local_max_concurrency,
        "openai_json_mode": args.openai_json_mode,
        "disable_same_text_fallback": bool(getattr(args, "disable_same_text_fallback", True)),
        "hymt_compat_proxy": proxy_info,
        "backend_quality": backend_quality,
        "backend_retry_failures": str(backend_retry_failures_path),
        "pdf_backend_skipped": skip_pdf_backend,
        "cli_max_tokens": args.cli_max_tokens if should_use_qwen_cli_adapter(args) else None,
        "translation_context_file": str(context_file) if should_use_qwen_cli_adapter(args) else None,
        "input_pdf": str(input_pdf),
        "render_source_of_truth": "latex_direct" if latex_direct_manifest.get("status") == "ok" else "pdf_backend",
        "actual_render_source": (
            "latex_direct"
            if latex_direct_manifest.get("status") == "ok"
            else "pdf_backend_fallback"
            if source_override and source_override.suffix.lower() == ".tex" and args.latex_render_mode != "off"
            else "pdf_backend"
        ),
        "intended_source_of_truth": prepare_manifest.get("source_of_truth"),
        "latex_direct_render": latex_direct_manifest,
        "source_override": str(source_override) if source_override else None,
        "source_selection": prepare_manifest.get("source_selection"),
        "source_of_truth": prepare_manifest.get("source_of_truth"),
        "outputs": selected_outputs,
        "pdf_backend_outputs": pdf_backend_outputs,
        "all_pdf_outputs": [str(path) for path in pdfs],
        "bilingual_pdf": bilingual_manifest,
        "visual_repair": visual_repair_manifest,
        "visual_repair_manifest": str(output_dir / "visual_repair_manifest.json"),
        "toc_repair": toc_repair_manifest,
        "toc_repair_manifest": str(output_dir / "toc_repair_manifest.json"),
        "metadata_label_repair": metadata_label_repair_manifest,
        "metadata_label_repair_manifest": str(output_dir / "metadata_label_repair_manifest.json"),
        "bilingual_layout": args.bilingual_layout,
        "skip_visual_eval": skip_visual_eval,
        "log_path": str(log_path),
        "returncode": returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "errors": errors,
        "cloud_layout": cloud_layout,
        "coverage_gate": quality_artifacts["coverage_gate"],
        "term_policy": str(output_dir / "term_policy.json"),
        "entity_map": str(output_dir / "entity_map.json"),
        "document_memory": str(output_dir / "document_memory.json"),
        "visual_layout_report": visual_report,
        "visual_layout_report_path": str(visual_report_path),
        "dropped_text_audit": str(dropped_text_audit_path),
        "dual_visual_report": dual_visual_report,
        "dual_visual_report_path": str(dual_visual_report_path),
        "paragraph_label_audit": str(paragraph_audit_path),
        "hymt_proxy_stats": str(hymt_proxy_stats_path),
        "backend_retry_failures": str(backend_retry_failures_path),
        "backend_translate_tracking": str(backend_tracking_path) if backend_tracking_path else None,
        "validation": {
            "translated_text_chars": len(translated_text),
            "translated_text_extraction_method": translated_text_method,
            "cjk_char_count": len([char for char in translated_text if "\u4e00" <= char <= "\u9fff"]),
            "has_translated_pdf": bool(selected_outputs["translated_pdf"]),
            "gates": delivery_gates,
        },
    }
    rerender_candidates["render_status"] = render_manifest.get("status")
    (output_dir / "rerender_candidates.json").write_text(json.dumps(rerender_candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render_manifest["rerender_candidates"] = str(output_dir / "rerender_candidates.json")
    render_manifest["rerender_candidate_count"] = rerender_candidates["candidate_count"]
    render_path = output_dir / "render_manifest.json"
    render_path.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    backend_manifest = {
        "version": 1,
        "status": status,
        "backend": "pdfmathtranslate-next",
        "backend_source": args.pdf2zh_backend if not args.pdf2zh_binary else "explicit_binary",
        "backend_resolution": resolved_pdf2zh_backend(args),
        "backend_health": preflight_report,
        "preflight": render_manifest["preflight"],
        "backend_wrapper": str(Path(__file__).resolve().with_name("pdf2zh_backend.py")) if args.pdf2zh_backend == "module" and not args.pdf2zh_binary else None,
        "external_pdf2zh_skill_path": str(external_pdf2zh_skill_root()) if external_pdf2zh_skill_root() else None,
        "source_manifest": str(output_dir / "source_manifest.json"),
        "source_override": str(source_override) if source_override else None,
        "source_selection": prepare_manifest.get("source_selection"),
        "source_of_truth": prepare_manifest.get("source_of_truth"),
        "glossary": str(glossary_path),
        "term_policy": str(output_dir / "term_policy.json"),
        "entity_map": str(output_dir / "entity_map.json"),
        "document_memory": str(output_dir / "document_memory.json"),
        "render_manifest": str(render_path),
        "model": args.model,
        "provider": getattr(args, "provider", ""),
        "base_url": original_base_url,
        "base_url_inference": getattr(args, "inferred_translation_provider", None),
        "backend_base_url": proxy_info["proxy_base_url"] or original_base_url,
        "local_max_concurrency": args.local_max_concurrency,
        "pdf_layout_profile": getattr(args, "resolved_pdf_layout_profile", getattr(args, "pdf_layout_profile", "auto")),
        "openai_json_mode": args.openai_json_mode,
        "disable_same_text_fallback": bool(getattr(args, "disable_same_text_fallback", True)),
        "ignore_translation_cache": bool(getattr(args, "ignore_translation_cache", False)),
        "backend_debug_artifacts": bool(getattr(args, "backend_debug_artifacts", True)),
        "translation_cache": translation_cache,
        "hymt_compat_proxy": proxy_info,
        "hymt_proxy_stats": str(hymt_proxy_stats_path),
        "backend_retry_failures": str(backend_retry_failures_path),
        "backend_translate_tracking": str(backend_tracking_path) if backend_tracking_path else None,
        "backend_quality": backend_quality,
        "actual_render_source": render_manifest.get("actual_render_source"),
        "intended_source_of_truth": render_manifest.get("intended_source_of_truth"),
        "latex_direct_render": latex_direct_manifest,
        "visual_layout_report": str(visual_report_path),
        "dual_visual_report": str(dual_visual_report_path),
        "paragraph_label_audit": str(paragraph_audit_path),
        "bilingual_pdf": bilingual_manifest,
        "visual_repair": visual_repair_manifest,
        "visual_repair_manifest": str(output_dir / "visual_repair_manifest.json"),
        "toc_repair": toc_repair_manifest,
        "toc_repair_manifest": str(output_dir / "toc_repair_manifest.json"),
        "metadata_label_repair": metadata_label_repair_manifest,
        "metadata_label_repair_manifest": str(output_dir / "metadata_label_repair_manifest.json"),
        "bilingual_layout": args.bilingual_layout,
        "rerender_candidates": str(output_dir / "rerender_candidates.json"),
        "block_bridge": str(output_dir / "block_bridge.json"),
        "confirmed_repair_plan": str(output_dir / "confirmed_repair_plan.json"),
        "qa_repair_plan": str(output_dir / "qa_repair_plan.json"),
        "pdf_rerender_plan": str(output_dir / "pdf_rerender_plan.json"),
        "policy_context": str(context_file),
        "delivery_gates": delivery_gates,
        "fallback": "text_extraction_path" if status == "error" else None,
    }
    (output_dir / "backend_run_manifest.json").write_text(
        json.dumps(backend_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    layout_map_path = write_layout_map(output_dir, prepare_manifest, render_manifest, backend_tracking_path)
    write_translation_artifacts(output_dir, translated_text, translated_text_method, prepare_manifest, args.model)
    block_bridge = build_block_bridge.build_bridge(
        prepare_manifest,
        check_translation.load_json(layout_map_path),
        check_translation.load_translation_blocks(output_dir / "translation_blocks.jsonl"),
        render_manifest,
    )
    (output_dir / "block_bridge.json").write_text(json.dumps(block_bridge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pymupdf_layout_audit_path = output_dir / "pymupdf_layout_audit.json"
    poppler_text_bbox_audit_path = output_dir / "poppler_text_bbox_audit.json"
    layout_structure_gate_path = output_dir / "layout_structure_gate.json"
    if skip_visual_eval:
        pymupdf_layout_audit = {"version": 1, "status": "skipped", "reason": "skip_visual_eval_requested"}
        poppler_text_bbox_audit = {"version": 1, "status": "skipped", "reason": "skip_visual_eval_requested"}
        layout_structure_gate = {
            "version": 1,
            "status": "skipped",
            "reason": "skip_visual_eval_requested",
            "issues": [],
        }
        structured_writeback_manifest = {
            "version": 1,
            "status": "skipped",
            "reason": "skip_visual_eval_requested",
            "toc_row_map": {},
            "metadata_yband_audit": {},
            "table_region_map": {},
        }
    else:
        pymupdf_layout_audit = build_pymupdf_layout_audit.build_pymupdf_layout_audit(
            source_pdf=input_pdf,
            translated_pdf=Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None,
            tracking_payload=policy_utils.load_json(backend_tracking_path),
        )
        poppler_text_bbox_audit = build_poppler_text_bbox_audit.build_poppler_text_bbox_audit(
            source_pdf=input_pdf,
            translated_pdf=Path(selected_outputs["translated_pdf"]) if selected_outputs.get("translated_pdf") else None,
            tracking_payload=policy_utils.load_json(backend_tracking_path),
        )
        layout_structure_gate = build_layout_structure_gate.build_layout_structure_gate(
            layout_map=check_translation.load_json(layout_map_path),
            pymupdf_audit=pymupdf_layout_audit,
            poppler_audit=poppler_text_bbox_audit,
            visual_report=visual_report,
        )
        structured_writeback_manifest = build_structured_writeback_manifest.build_structured_writeback_manifest(
            check_translation.load_json(layout_map_path),
            pymupdf_layout_audit,
        )
    pymupdf_layout_audit_path.write_text(json.dumps(pymupdf_layout_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    poppler_text_bbox_audit_path.write_text(json.dumps(poppler_text_bbox_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    layout_structure_gate_path.write_text(json.dumps(layout_structure_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "toc_row_map.json").write_text(
        json.dumps(structured_writeback_manifest.get("toc_row_map", {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "metadata_yband_audit.json").write_text(
        json.dumps(structured_writeback_manifest.get("metadata_yband_audit", {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "table_region_map.json").write_text(
        json.dumps(structured_writeback_manifest.get("table_region_map", {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "structured_writeback_manifest.json").write_text(
        json.dumps(structured_writeback_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for issue in [] if latex_direct_primary else layout_structure_gate.get("issues", []) if isinstance(layout_structure_gate.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("rule") or "") in {"layout_label_coverage_low", "heading_bold_style_drift"}:
            continue
        add_rerender_candidate(
            rerender_candidates.setdefault("candidates", []),
            rule=str(issue.get("rule") or "layout_structure_gate"),
            layer="layout_mapping" if str(issue.get("rule") or "").endswith("_risk") or "tracking" in str(issue.get("rule") or "") else "pdf_rendering",
            severity=str(issue.get("severity") or "warn"),
            block_id="document",
            evidence=json.dumps(issue.get("evidence"), ensure_ascii=False),
            recommendation=str(issue.get("recommendation") or "按 layout_structure_gate 定位并局部重排。"),
            rerender_mode="page_rerender" if str(issue.get("rule") or "") in {"chapter_index_merge", "toc_row_renderer_failed", "role_font_floor_caused_overlap"} else "targeted_rerender",
        )
    rerender_candidates["candidate_count"] = len(rerender_candidates.get("candidates", []))
    rerender_candidates["status"] = "warn" if rerender_candidates.get("candidates") else "ok"
    rerender_candidates["layout_structure_gate"] = str(layout_structure_gate_path)
    (output_dir / "rerender_candidates.json").write_text(json.dumps(rerender_candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    delivery_gates = build_delivery_gates(
        visual_report=visual_report,
        dual_visual_report=dual_visual_report,
        backend_quality=backend_quality,
        rerender_candidates=rerender_candidates,
        translated_text=translated_text,
        strict=bool(getattr(args, "strict_delivery_gates", False)),
        pipeline_status=status,
        has_translated_pdf=bool(selected_outputs["translated_pdf"]),
        latex_baseline_audit=latex_direct_manifest.get("latex_baseline_audit"),
        quality_report_text=(output_dir / "quality_report.md").read_text(encoding="utf-8", errors="replace") if (output_dir / "quality_report.md").exists() else "",
        pdf_rerender_plan=policy_utils.load_json(output_dir / "pdf_rerender_plan.json"),
        pdf_direct_text_repair=pdf_direct_text_repair,
        block_bridge=block_bridge,
        pymupdf_layout_audit=pymupdf_layout_audit,
        layout_structure_gate=layout_structure_gate,
        actual_render_source="latex_direct" if latex_direct_primary else None,
        latex_direct_quality_gate=latex_quality_gate,
    )
    if skip_visual_eval:
        delivery_gates = build_fast_full_translation_draft_gates(
            pipeline_status=status,
            has_translated_pdf=bool(selected_outputs["translated_pdf"]),
            bilingual_manifest=bilingual_manifest,
            backend_quality=backend_quality,
            previous_gates=delivery_gates,
        )
        if status != "error" and delivery_gates.get("status") == "ok":
            status = "ok"
            render_manifest["status"] = "ok"
    render_manifest["validation"]["gates"] = delivery_gates
    if status != "error" and delivery_gates.get("status") == "ok":
        status = "ok"
        render_manifest["status"] = "ok"
    elif status != "error" and delivery_gates.get("status") == "partial":
        status = "partial"
        render_manifest["status"] = "partial"
    render_manifest["pymupdf_layout_audit"] = str(pymupdf_layout_audit_path)
    render_manifest["poppler_text_bbox_audit"] = str(poppler_text_bbox_audit_path)
    render_manifest["layout_structure_gate"] = str(layout_structure_gate_path)
    render_manifest["toc_row_map"] = str(output_dir / "toc_row_map.json")
    render_manifest["metadata_yband_audit"] = str(output_dir / "metadata_yband_audit.json")
    render_manifest["table_region_map"] = str(output_dir / "table_region_map.json")
    render_manifest["structured_writeback_manifest"] = str(output_dir / "structured_writeback_manifest.json")
    render_manifest["block_bridge"] = str(output_dir / "block_bridge.json")
    if skip_visual_eval:
        render_manifest["delivery_mode"] = "fast_full_translation_draft"
        backend_manifest["delivery_mode"] = "fast_full_translation_draft"
    backend_manifest["delivery_gates"] = delivery_gates
    backend_manifest["pymupdf_layout_audit"] = str(pymupdf_layout_audit_path)
    backend_manifest["poppler_text_bbox_audit"] = str(poppler_text_bbox_audit_path)
    backend_manifest["layout_structure_gate"] = str(layout_structure_gate_path)
    backend_manifest["structured_writeback_manifest"] = str(output_dir / "structured_writeback_manifest.json")
    backend_manifest["table_region_map"] = str(output_dir / "table_region_map.json")
    backend_manifest["block_bridge"] = str(output_dir / "block_bridge.json")
    backend_manifest["status"] = status
    render_path.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "backend_run_manifest.json").write_text(
        json.dumps(backend_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run_quality_check(output_dir, render_manifest)
    readable_manifest = render_qa_repaired_pdf(output_dir, args)
    render_manifest["outputs"]["readable_repaired_pdf"] = readable_manifest.get("output") if readable_manifest.get("status") == "ok" else None
    render_manifest["outputs"]["readable_repaired_pdf_manifest"] = readable_manifest.get("manifest_path") if readable_manifest.get("status") == "ok" else None
    render_manifest["qa_repaired_pdf"] = readable_manifest
    cleanup_candidates = list(render_manifest.get("all_pdf_outputs", []) or [])
    if readable_manifest.get("output"):
        cleanup_candidates.append(str(readable_manifest["output"]))
    delivery_pdf_outputs = finalize_delivery_pdf_outputs(
        input_pdf,
        output_dir,
        selected_outputs,
        candidate_pdfs=cleanup_candidates,
    )
    if readable_manifest.get("output") and not Path(str(readable_manifest["output"])).exists():
        readable_manifest["status"] = "pruned"
        readable_manifest["reason"] = "delivery_pdf_contract_keeps_only_two_pdfs"
        render_manifest["outputs"]["readable_repaired_pdf"] = None
        render_manifest["outputs"]["readable_repaired_pdf_manifest"] = None
    render_manifest["outputs"].update(selected_outputs)
    render_manifest["all_pdf_outputs"] = [
        path
        for path in (
            selected_outputs.get("mono_pdf"),
            selected_outputs.get("standard_bilingual_pdf"),
        )
        if path
    ]
    render_manifest["delivery_pdf_outputs"] = delivery_pdf_outputs
    render_path.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    backend_manifest["qa_repaired_pdf"] = readable_manifest
    backend_manifest["delivery_gates"] = render_manifest["validation"]["gates"]
    backend_manifest["outputs"] = dict(selected_outputs)
    backend_manifest["delivery_pdf_outputs"] = delivery_pdf_outputs
    (output_dir / "backend_run_manifest.json").write_text(
        json.dumps(backend_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if status == "error":
        fallback_to_text_path(output_dir, prepare_manifest)
    return backend_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the strong PDF-first paper translation pipeline.")
    parser.add_argument("input_pdf", help="Input PDF path.")
    parser.add_argument("--output-dir", help="Output artifact directory. Defaults to <pdf-stem>-zh.")
    parser.add_argument("--pdf2zh-binary", default=os.environ.get("PAPER_TRANSLATION_PDF2ZH_BINARY"), help="pdf2zh executable path. Defaults to PAPER_TRANSLATION_PDF2ZH_BINARY, then PATH lookup.")
    parser.add_argument(
        "--pdf2zh-backend",
        choices=["path", "module"],
        default=os.environ.get("PAPER_TRANSLATION_PDF2ZH_BACKEND", DEFAULT_PDF2ZH_BACKEND),
        help="PDF backend source. path uses a pdf2zh executable; module uses scripts/pdf2zh_backend.py with an installed pdf2zh_next module.",
    )
    parser.add_argument("--preflight-only", action="store_true", help="Run runtime dependency preflight, write preflight/render manifests, and exit before translation.")
    parser.add_argument("--skip-preflight", action="store_true", help="Diagnostic only: skip strict runtime preflight before translation.")
    parser.add_argument("--provider", default=os.environ.get("LOCAL_TRANSLATION_PROVIDER", ""), help="可选厂商别名，用于按候选表推断 base URL，例如 deepseek、openai、qwen、kimi、siliconflow、glm、openrouter、ark。")
    parser.add_argument("--model", default=os.environ.get("LOCAL_TRANSLATION_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--base-url", default=os.environ.get("LOCAL_TRANSLATION_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=os.environ.get("LOCAL_TRANSLATION_API_KEY") or DEFAULT_API_KEY)
    parser.add_argument("--translator-mode", choices=["auto", "openai", "qwen-cli"], default=os.environ.get("PDF_TRANSLATION_TRANSLATOR_MODE", DEFAULT_TRANSLATOR_MODE))
    parser.add_argument(
        "--hymt-compat-proxy",
        choices=["auto", "on", "off"],
        default=os.environ.get("PAPER_TRANSLATION_HYMT_COMPAT_PROXY", "auto"),
        help="hy-mt JSON 兼容代理开关；auto 会在 hy-mt OpenAI 模式下自动启用。",
    )
    parser.add_argument(
        "--hymt-compat-proxy-port",
        type=int,
        default=int(os.environ.get("PAPER_TRANSLATION_HYMT_COMPAT_PROXY_PORT", str(DEFAULT_HYMT_COMPAT_PROXY_PORT))),
        help="hy-mt JSON 兼容代理本地端口。",
    )
    parser.add_argument("--local-max-concurrency", type=int, default=int(os.environ.get("LOCAL_MODEL_MAX_CONCURRENCY", str(DEFAULT_LOCAL_MAX_CONCURRENCY))))
    parser.add_argument("--openai-json-mode", action=argparse.BooleanOptionalAction, default=os.environ.get("PDF_TRANSLATION_OPENAI_JSON_MODE", "1") not in {"0", "false", "False"})
    parser.add_argument(
        "--disable-same-text-fallback",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_DISABLE_SAME_TEXT_FALLBACK", "1") not in {"0", "false", "False"},
        help="默认禁用 BabelDOC 的 same-as-input 原文 fallback；普通英文同文返回会作为 retry/failure 证据记录。",
    )
    parser.add_argument(
        "--ignore-translation-cache",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_IGNORE_CACHE", "0") in {"1", "true", "True"},
        help="诊断用：向 PDFMathTranslate-next/BabelDOC 传入 --ignore-cache，强制绕过翻译缓存。",
    )
    parser.add_argument(
        "--backend-debug-artifacts",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_BACKEND_DEBUG_ARTIFACTS", "1") not in {"0", "false", "False"},
        help="默认打开后端 debug 产物，以便回收 translate_tracking.json 生成 item 级 fallback 证据。",
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PDF_TRANSLATION_TIMEOUT_SEC", "3600")))
    parser.add_argument("--openai-timeout", type=int, default=int(os.environ.get("PDF_TRANSLATION_OPENAI_TIMEOUT_SEC", "7200")))
    parser.add_argument("--openai-reasoning-effort", default=os.environ.get("PDF_TRANSLATION_OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT))
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("PDF_TRANSLATION_TEMPERATURE", str(DEFAULT_HYMT2_TEMPERATURE))))
    parser.add_argument("--cli-max-tokens", type=int, default=int(os.environ.get("PDF_TRANSLATION_CLI_MAX_TOKENS", str(DEFAULT_CLI_MAX_TOKENS))))
    parser.add_argument("--custom-system-prompt", default=os.environ.get("PDF_TRANSLATION_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT))
    parser.add_argument("--source-override", "--latex-source", dest="source_override", help="Compatibility/debug override. Normal runs auto-discover LaTeX source and do not require this flag.")
    parser.add_argument("--latex-source-root", action="append", default=[], help="Additional root to scan for LaTeX source; auto-discovery still applies without this when .tex files are adjacent.")
    parser.add_argument("--no-latex-autodiscovery", dest="disable_latex_autodiscovery", action="store_true", help="Disable LaTeX-first auto source selection for diagnostics.")
    parser.add_argument("--no-arxiv-source-autodownload", dest="disable_arxiv_source_autodownload", action="store_true", help="Disable arXiv e-print source download fallback after local LaTeX source discovery misses.")
    parser.add_argument(
        "--latex-render-mode",
        choices=["auto", "required", "off"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_RENDER_MODE", DEFAULT_LATEX_RENDER_MODE),
        help="LaTeX source case 的主渲染策略；auto/required 会优先用外部 pdf2zh-skill 兼容路径生成主 PDF。",
    )
    parser.add_argument(
        "--latex-project-mode",
        choices=["in-place", "merged"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_PROJECT_MODE", DEFAULT_LATEX_PROJECT_MODE),
        help="LaTeX direct 项目模式；in-place 保留 paper_source -> paper_cn -> <main>.pdf，merged 保留旧 merge_中文 诊断路径。",
    )
    parser.add_argument("--latex-render-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_RENDER_TIMEOUT_SEC", "7200")))
    parser.add_argument("--latex-translate-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_TRANSLATE_TIMEOUT_SEC", "7200")))
    parser.add_argument("--latex-compile-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_COMPILE_TIMEOUT_SEC", "300")))
    parser.add_argument("--latex-retry-untranslated", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_RETRY_UNTRANSLATED", "4")))
    parser.add_argument("--latex-auto-repair-passes", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_AUTO_REPAIR_PASSES", "2")))
    parser.add_argument("--latex-compiler", choices=["lualatex", "xelatex", "pdflatex"], default=os.environ.get("PAPER_TRANSLATION_LATEX_COMPILER"))
    parser.add_argument(
        "--latex-compile-runtime",
        choices=["auto", "local", "docker"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_COMPILE_RUNTIME", "auto"),
        help="LaTeX direct 编译运行时。auto 优先本机 TeX，缺失时自动使用 Docker TeX Live wrapper。",
    )
    parser.add_argument(
        "--latex-docker-image",
        default=os.environ.get("PAPER_TRANSLATION_TEX_DOCKER_IMAGE", DEFAULT_LATEX_DOCKER_IMAGE),
        help="LaTeX direct 使用 Docker 编译时的 TeX Live 镜像。",
    )
    parser.add_argument("--latex-baseline-pdf", default=os.environ.get("PAPER_TRANSLATION_LATEX_BASELINE_PDF"), help="可选历史/外部最佳 LaTeX PDF，用于生成 latex_baseline_audit.json。")
    parser.add_argument("--latex-skip-glossary", action="store_true", help="调试用：LaTeX 直译路径跳过术语抽取。")
    parser.add_argument("--latex-skip-consistency-review", action="store_true", help="调试用：LaTeX 直译路径跳过一致性复审。")
    parser.add_argument("--skip-pdf-backend-when-latex-direct", action="store_true", help="LaTeX direct case 只重跑 LaTeX 主路径，PDFMathTranslate-next 旧产物仅作为 fallback/对照。")
    parser.add_argument("--post-qa-repair", choices=["auto", "off"], default=os.environ.get("PAPER_TRANSLATION_POST_QA_REPAIR", "off"), help="是否额外渲染 QA 修复后的可读 PDF；默认关闭，普通交付只保留中文单语和双语 PDF。")
    parser.add_argument("--strict-delivery-gates", action="store_true", default=os.environ.get("PAPER_TRANSLATION_STRICT_DELIVERY_GATES", "0") in {"1", "true", "True"}, help="启用评测级交付 gate；warn 级问题也会把主交付标为 partial。")
    parser.add_argument(
        "--pdf-layout-profile",
        choices=["auto", "default", "toc-safe"],
        default=os.environ.get("PAPER_TRANSLATION_PDF_LAYOUT_PROFILE", "auto"),
        help="PDF 后端版式配置；auto 会在检测到目录页时启用 split-short-lines。",
    )
    parser.add_argument(
        "--visual-check-pages",
        default=os.environ.get("PAPER_TRANSLATION_VISUAL_CHECK_PAGES", "auto"),
        help="视觉检查页码，支持 auto 或 1,2,5,8-10。auto 保持旧的前三页检查。",
    )
    parser.add_argument(
        "--skip-visual-eval",
        action="store_true",
        default=os.environ.get("PAPER_TRANSLATION_SKIP_VISUAL_EVAL", "0") in {"1", "true", "True"},
        help="长报告快速交付模式：跳过 visual_layout、dual_visual 和 paragraph label 评估，只生成明确的 skipped 报告。",
    )
    parser.add_argument(
        "--allow-pdf-direct-text-overlay",
        action="store_true",
        default=os.environ.get("PAPER_TRANSLATION_ALLOW_PDF_DIRECT_TEXT_OVERLAY", "0") in {"1", "true", "True"},
        help="调试用：允许 PDF direct text repair 原地覆盖主 PDF。默认关闭，避免白底 redaction 污染主交付。",
    )
    parser.add_argument(
        "--visual-repair-mode",
        choices=["auto", "off", "candidate"],
        default=os.environ.get("PAPER_TRANSLATION_VISUAL_REPAIR_MODE", "auto"),
        help="可见质量候选层；auto/candidate 只生成候选和人工复核清单，不自动替换标准双语右页。",
    )
    parser.add_argument(
        "--toc-repair",
        choices=["auto", "off", "force"],
        default=os.environ.get("PAPER_TRANSLATION_TOC_REPAIR", "auto"),
        help="目录/章节索引确定性重绘；auto 仅在源/译页背景安全时应用，force 跳过背景安全限制，off 关闭。",
    )
    parser.add_argument(
        "--toc-repair-pages",
        default=os.environ.get("PAPER_TRANSLATION_TOC_REPAIR_PAGES"),
        help="可选目录修复页码列表，如 2,14；默认自动检测前若干页。",
    )
    parser.add_argument(
        "--metadata-label-repair",
        choices=["auto", "off", "force"],
        default=os.environ.get("PAPER_TRANSLATION_METADATA_LABEL_REPAIR", "auto"),
        help="封面年份、联系邮箱和当前已知图表轴标签的确定性修复；auto 仅在安全背景区域应用。",
    )
    parser.add_argument("--engine-home", help="Shared pdf2zh/BabelDOC asset cache. Defaults to ~/.cache/double6-pdf-translation/pdf2zh-home.")
    parser.add_argument("--allow-cloud-layout", action="store_true", help="Allow cloud layout/OCR backends such as MinerU.")
    parser.add_argument("--dual", action=argparse.BooleanOptionalAction, default=True, help="Request dual PDF output when supported.")
    parser.add_argument(
        "--bilingual-layout",
        choices=["en-left-zh-right", "backend-default", "off"],
        default=os.environ.get("PAPER_TRANSLATION_BILINGUAL_LAYOUT", "en-left-zh-right"),
        help="Final bilingual PDF layout. Default rebuilds dual PDF as original English left, Chinese translation right.",
    )
    parser.add_argument(
        "--bilingual-render-mode",
        choices=["vector", "raster", "pypdf-vector"],
        default=os.environ.get("PAPER_TRANSLATION_BILINGUAL_RENDER_MODE", "pypdf-vector"),
        help="标准双语 PDF 合成模式；pypdf-vector 默认用于兼顾 macOS Preview 兼容性、清晰度和文本层，vector 使用 PyMuPDF Form XObject，raster 仅作最后兼容兜底。",
    )
    parser.add_argument(
        "--bilingual-raster-dpi",
        type=int,
        default=int(os.environ.get("PAPER_TRANSLATION_BILINGUAL_RASTER_DPI", "144")),
        help="--bilingual-render-mode=raster 时的页面栅格化 DPI。",
    )
    parser.add_argument("--pages", help="Optional pdf2zh page range for smoke tests or partial PDF translation.")
    return parser


def build_console_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    render_manifest = str(manifest.get("render_manifest") or "")
    output_dir = str(Path(render_manifest).parent) if render_manifest else None
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    delivery = manifest.get("delivery_pdf_outputs") if isinstance(manifest.get("delivery_pdf_outputs"), dict) else {}
    delivery_outputs = delivery.get("outputs") if isinstance(delivery.get("outputs"), dict) else {}
    pdfs = {
        "chinese_pdf": delivery_outputs.get("mono_pdf") or outputs.get("mono_pdf") or outputs.get("translated_pdf"),
        "bilingual_pdf": delivery_outputs.get("bilingual_pdf") or outputs.get("standard_bilingual_pdf") or outputs.get("dual_pdf"),
    }
    summary = {
        "status": manifest.get("status"),
        "output_dir": output_dir,
        "pdfs": {key: value for key, value in pdfs.items() if value},
        "manifest": render_manifest or None,
    }
    preflight = manifest.get("preflight") if isinstance(manifest.get("preflight"), dict) else {}
    if manifest.get("status") == "preflight_failed":
        summary["message"] = "运行前配置或依赖检查未通过；请先查看 preflight_report.json。"
        summary["preflight_report"] = preflight.get("report")
    elif manifest.get("status") in {"ok", "partial"}:
        summary["message"] = "翻译流程已结束；普通用户只需要打开 pdfs 中的两份交付 PDF。"
    else:
        summary["message"] = "翻译流程未完成；详细错误见 manifest。"
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = run(args)
    print(json.dumps(build_console_summary(manifest), ensure_ascii=False, indent=2))
    if manifest.get("status") == "preflight_failed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
