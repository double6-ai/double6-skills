# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation render：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def _run_render(args: argparse.Namespace) -> dict[str, Any]:
    from pdf_translation_artifacts import build_standard_bilingual_output, collect_pdfs, enrich_quality_artifacts, extract_pdf_text, maybe_build_visual_repair_output, mirror_latex_direct_bilingual_output, relocate_backend_dual_intermediate, render_qa_repaired_pdf, run_quality_check, select_pdf_outputs, write_glossary, write_layout_map, write_translation_artifacts
    from pdf_translation_backend_quality import annotate_backend_quality_origin, copy_backend_tracking_artifact, enrich_translation_cache_stats, fallback_to_text_path, maybe_run_cloud_layout, parse_backend_quality, parse_translation_cache_stats, refine_backend_quality_with_retry_failures, resolve_backend_quality_with_pdf_direct_repairs
    from pdf_translation_commands import build_backend_system_prompt, build_pdf2zh_command, redacted_command
    from pdf_translation_delivery import build_delivery_gates, build_fast_full_translation_draft_gates
    from pdf_translation_latex_render import discover_latex_source, prepare_source, run_latex_direct_render
    from pdf_translation_overrides import add_rerender_candidate, append_visual_rerender_candidates, append_visual_rerender_plan, build_rerender_candidates
    from pdf_translation_paths import default_engine_home, default_output_dir, resolve_pdf_layout_profile, should_enable_hymt_compat_proxy, should_use_qwen_cli_adapter, vendored_babeldoc_root
    from pdf_translation_runtime import run
    from pdf_translation_text_repair import apply_pdf_direct_text_repairs
    from pdf_translation_tracking import build_dropped_text_audit_from_files, write_backend_retry_failures
    started = time.monotonic()
    if getattr(args,'translation_transport','openai_compatible')=='lmstudio_native_chat_v1' and args.translator_mode!='openai':
        raise ValueError('native source-bound transport requires explicit --translator-mode openai')
    input_pdf = Path(args.input_pdf).expanduser().resolve()
    args.input_pdf = str(input_pdf)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(input_pdf).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if bool(getattr(args, "route_only", False)):
        from scanned_raster.route_pdf import write_route_only_result

        return write_route_only_result(input_pdf, output_dir, args)

    if bool(getattr(args,'pdf_backend_only',False)):
        if args.source_override or args.latex_render_mode!='off':
            raise ValueError('explicit PDF-only route requires --latex-render-mode off and no TeX override')
        source_override=None
        source_selection={'policy':'explicit_pdf_backend_only','status':'discovery_skipped','source_path':None}
    else:
        source_override, source_selection = discover_latex_source(input_pdf, args)
    if source_override is not None and source_selection.get("identity_status") != "verified_match":
        source_selection = {
            **source_selection,
            "latex_direct_blocked": True,
            "blocked_source_path": str(source_override),
            "reason": "unverified_latex_identity",
        }
        source_override = None

    from scanned_raster.route_pdf import route_pdf, write_route_manifest

    route_manifest = route_pdf(
        input_pdf,
        args=args,
        explicit_override=(source_override if source_selection.get("identity_status") == "verified_match" else None),
    )
    route_manifest_path = write_route_manifest(output_dir, route_manifest)
    if not route_manifest.get("dispatch_allowed"):
        return {
            "schema_version": route_manifest.get("schema_version"),
            "skill_version": route_manifest.get("skill_version"),
            "status": route_manifest.get("route_status") or "needs_review",
            "document_route": route_manifest.get("document_route"),
            "route_manifest": str(route_manifest_path),
            "intended_render_source": route_manifest.get("intended_render_source"),
            "actual_render_source": None,
            "review_reasons": route_manifest.get("review_reasons") or [],
        }
    if route_manifest.get("document_route") == "mixed_cover_digital":
        from scanned_raster.mixed_cover import run_mixed_cover

        return run_mixed_cover(input_pdf, output_dir, route_manifest, args, body_runner=run)
    if route_manifest.get("document_route") == "scanned_raster":
        from scanned_raster.pipeline import run_scanned_translation

        return run_scanned_translation(input_pdf, output_dir, route_manifest, args)
    if route_manifest.get("document_route") == "pdf_backend":
        source_override = None
        source_selection = {
            "policy": "explicit_pdf_backend_only" if getattr(args,'pdf_backend_only',False) else "three_layer_route_v2",
            "status": "pdf_backend",
            "identity_status": route_manifest.get("latex_source", {}).get("status"),
            'latex_discovery_skipped':bool(getattr(args,'pdf_backend_only',False)),
            'source_expected_key':route_manifest.get('latex_source',{}).get('expected_key'),
        }
    elif route_manifest.get("document_route") == "latex_direct":
        routed_source = route_manifest.get("latex_source", {}).get("source_path")
        if routed_source:
            source_override = Path(str(routed_source)).expanduser().resolve()
            source_selection = {
                "policy": "three_layer_route_v2",
                "status": "found",
                "identity_status": "verified_match",
                "source_path": str(source_override),
                "match_method": route_manifest.get("latex_source", {}).get("match_method"),
            }
    engine_home = Path(args.engine_home).expanduser().resolve() if args.engine_home else default_engine_home()
    engine_home.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "pdf2zh-next.log"
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
        'adapter':'source_bound_native' if getattr(args,'translation_transport','openai_compatible')=='lmstudio_native_chat_v1' else 'hymt_compat',
        'transport':getattr(args,'translation_transport','openai_compatible'),
    }
    if should_enable_hymt_compat_proxy(args) and not skip_pdf_backend:
        proxy_config = ProxyConfig(
            model=args.model,
            upstream_base_url=original_base_url.rstrip("/"),
            api_key=args.api_key,
            port=int(getattr(args, "hymt_compat_proxy_port", DEFAULT_HYMT_COMPAT_PROXY_PORT)),
            policy_context_path=str(context_file),
            transport=getattr(args,'translation_transport','openai_compatible'),
            trace_dir=str(output_dir/'native_transport') if getattr(args,'translation_transport','openai_compatible')=='lmstudio_native_chat_v1' else None,
            source_cache_context_ref={'path':str(args.source_cache_context.resolve()),'sha256':args.source_cache_context_sha256} if getattr(args,'source_cache_mode',None) else None,
            source_cache_mode=getattr(args,'source_cache_mode',None),
            source_cache_render_id=getattr(args,'source_cache_render_id',None),
        )
        try:
            proxy_server = start_hymt_compat_proxy(proxy_config)
            args.base_url = proxy_config.base_url
            proxy_info.update({"enabled": True, "proxy_base_url": proxy_config.base_url})
        except OSError as exc:
            if getattr(args, "hymt_compat_proxy", "auto") == "on":
                raise
            proxy_info.update({"enabled": False, "error": f"proxy_start_failed: {exc}"})
    if getattr(args,'source_cache_mode',None):
        from pdf_source_cache import source_cache
        cache=source_cache(proxy_config.source_cache_context_ref,args.source_cache_mode)
        if not args.pdf_backend_only or args.translation_transport!='lmstudio_native_chat_v1' or not proxy_server:
            raise ValueError('source cache requires explicit native proxy PDF-only route')
        args.ignore_translation_cache=True
        env['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT']=proxy_config.source_cache_context_ref['path']
        env['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']=proxy_config.source_cache_context_ref['sha256']
        env['PAPER_TRANSLATION_SOURCE_CACHE_MODE']=args.source_cache_mode
        if cache.context.get('source_style_contract_ref') is not None:
            from pdf_group_editorial_revision import checked_ref
            declared=cache.context['source_style_contract_ref'];checked_ref(declared)
            env['PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT']=declared['path']
            env['PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT_SHA']=declared['sha256']
        if getattr(args,'source_cache_render_id',None):
            env['PAPER_TRANSLATION_SOURCE_CACHE_RENDER_ID']=args.source_cache_render_id
            proxy_info['source_cache_render_id']=args.source_cache_render_id
        del cache
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

    if getattr(args,'source_cache_mode',None)=='collect':
        import fitz
        from pdf_source_cache import file_ref,write_new as cache_write
        directory=Path(cache.context['collection_file']).parent
        boundary=directory/'COLLECTION_BOUNDARY.json'
        if not boundary.is_file() or (directory/'TYPESET_VIOLATION.json').exists():
            raise ValueError('source-only collector did not stop at required boundary')
        evidence=json.loads(boundary.read_text())
        with fitz.open(input_pdf) as source_doc:source_pages=list(range(1,len(source_doc)+1))
        if evidence['context_ref']!=proxy_config.source_cache_context_ref or evidence['pages']!=source_pages:
            raise ValueError('source-only full page boundary identity changed')
        if proxy_info['stats'].get('actual_provider_calls',0)!=0 or any(output_dir.glob('*.zh*.pdf')):
            raise ValueError('source-only collector produced provider calls or target PDF')
        result={'status':'source_only_collected','source_collection_ref':file_ref(cache.collection),
                'boundary_ref':file_ref(boundary),'proxy_stats':proxy_info['stats'],
                'actual_provider_calls':0,'candidate_generated':False,'backend_cache_ignored':True}
        cache_write(directory/'SOURCE_ONLY_RESULT.json',result)
        return result
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
        'route_selection':route_manifest.get('route_selection','auto'),
        'complete_native_page_gate':route_manifest.get('complete_native_page_gate'),
        'route_manifest':str(route_manifest_path),
        "status": status,
        "engine": "latex-direct-vendored-pdf2zh-skill" if latex_direct_manifest.get("status") == "ok" else "pdfmathtranslate-next",
        "engine_role": "latex_source_primary" if latex_direct_manifest.get("status") == "ok" else "default_strong_pdf_backend",
        "pdf_backend": "pdfmathtranslate-next",
        "engine_source": args.pdf2zh_backend if not args.pdf2zh_binary else "explicit_binary",
        "vendored_backend": str(Path(__file__).resolve().parents[1] / "vendor" / "pdfmathtranslate_next"),
        "vendored_babeldoc": str(vendored_babeldoc_root()),
        "babeldoc_vendor_enabled": args.pdf2zh_backend == DEFAULT_PDF2ZH_BACKEND and not args.pdf2zh_binary,
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
        "translation_cache": translation_cache,
        "model": args.model,
        "base_url": original_base_url,
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
        'route_selection':route_manifest.get('route_selection','auto'),
        'complete_native_page_gate':route_manifest.get('complete_native_page_gate'),
        "status": status,
        "backend": "pdfmathtranslate-next",
        "backend_source": args.pdf2zh_backend if not args.pdf2zh_binary else "explicit_binary",
        "vendored_backend": str(Path(__file__).resolve().parents[1] / "vendor" / "pdfmathtranslate_next"),
        "vendored_babeldoc": str(vendored_babeldoc_root()),
        "babeldoc_vendor_enabled": args.pdf2zh_backend == DEFAULT_PDF2ZH_BACKEND and not args.pdf2zh_binary,
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
        "base_url": original_base_url,
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
    write_translation_artifacts(output_dir, translated_text, translated_text_method, prepare_manifest, args.model,
                                executor_provider="latex_direct" if render_manifest.get("actual_render_source") == "latex_direct"
                                else str(render_manifest.get("engine") or "unknown"))
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
    if status != "error" and delivery_gates.get("status") == "partial":
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
    backend_manifest["route_manifest"] = str(route_manifest_path)
    backend_manifest["route_status"] = route_manifest.get("route_status")
    backend_manifest["intended_render_source"] = route_manifest.get("intended_render_source")
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
    render_path.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    backend_manifest["qa_repaired_pdf"] = readable_manifest
    backend_manifest["delivery_gates"] = render_manifest["validation"]["gates"]
    (output_dir / "backend_run_manifest.json").write_text(
        json.dumps(backend_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if status == "error":
        fallback_to_text_path(output_dir, prepare_manifest)
    return backend_manifest


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
