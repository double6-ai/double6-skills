# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline runtime：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *
from scanned_raster.pipeline_translation import _default_translate
from scanned_raster.pipeline_ocr import run_rapidocr_page

def _extract_text(path: Path) -> str:
    import fitz

    document = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") or "" for page in document)
    finally:
        document.close()

def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

def run_scanned_translation(
    input_pdf: Path,
    output_dir: Path,
    route_manifest: dict[str, Any],
    args: Any,
    *,
    rapidocr_runner: RapidOCRRunner = run_rapidocr_page,
    mineru_runner: MinerURunner = parse_with_mineru,
    translator: Translator = _default_translate,
) -> dict[str, Any]:
    from .checkpoint import enable_default_scanned_reuse
    enable_default_scanned_reuse(args)
    parse_root = getattr(args, 'scanned_parse_checkpoint_dir', None)
    if not parse_root or bool(getattr(args, 'ignore_translation_cache', False)):
        return _run_with_response_checkpoint(input_pdf, output_dir, route_manifest, args,
                                              rapidocr_runner=rapidocr_runner, mineru_runner=mineru_runner,
                                              translator=translator)
    from .checkpoint import implementation_digest
    from .parse_checkpoint import ParseCheckpoint, parse_identity
    if any((output_dir / name).exists() for name in ['scan_parse_manifest.json', 'scan_regions.jsonl',
                                                    'translated_scanned.pdf', 'scan_parse_checkpoint_receipt.json']):
        raise ValueError('parse checkpoint resume requires a fresh output attempt')
    identity = parse_identity(sha256_file(input_pdf), args, implementation_digest(Path(__file__).resolve().parent.parent))
    with ParseCheckpoint(Path(parse_root), identity) as checkpoint:
        def rapid(pdf, page, dpi):
            def produce():
                regions, info = rapidocr_runner(pdf, page, dpi)
                return {'regions': regions, 'page_info': info}
            value = checkpoint.capture({'provider': 'rapidocr', 'page': page, 'dpi': dpi}, produce, source_pdf=pdf)
            return value['regions'], value['page_info']

        def mineru(pdf, **kwargs):
            request = {k: v for k, v in kwargs.items() if k != 'output_dir'}
            request['provider'] = 'mineru'
            # Earlier selected pages do not alter this page's parsing identity.
            page = int(kwargs['page_range'])
            request['page_image_hashes'] = {str(page): kwargs['page_image_hashes'][page]}
            call_kwargs = dict(kwargs)
            # Each tier must retain its own candidates; the upstream renderer uses fixed filenames.
            call_kwargs['output_dir'] = kwargs['output_dir'] / ('checkpoint-' + kwargs['tier'])
            return checkpoint.capture(request, lambda: mineru_runner(pdf, **call_kwargs), source_pdf=pdf)

        try:
            result = _run_with_response_checkpoint(input_pdf, output_dir, route_manifest, args,
                                                    rapidocr_runner=rapid, mineru_runner=mineru, translator=translator)
            result['parse_checkpoint'] = checkpoint.report()
            manifest_path = Path(result['render_manifest'])
            render = json.loads(manifest_path.read_text(encoding='utf-8'))
            render['parse_checkpoint'] = checkpoint.report()
            render['parse_checkpoint_receipt'] = str(output_dir / 'scan_parse_checkpoint_receipt.json')
            _write_json(manifest_path, render)
            return result
        finally:
            _write_json(output_dir / 'scan_parse_checkpoint_receipt.json', checkpoint.report())

def _run_with_response_checkpoint(
    input_pdf: Path, output_dir: Path, route_manifest: dict[str, Any], args: Any, *,
    rapidocr_runner: RapidOCRRunner, mineru_runner: MinerURunner, translator: Translator,
) -> dict[str, Any]:
    checkpoint_root = getattr(args, 'scanned_checkpoint_dir', None)
    if not checkpoint_root or bool(getattr(args, 'ignore_translation_cache', False)):
        return _run_scanned_translation(input_pdf, output_dir, route_manifest, args, rapidocr_runner=rapidocr_runner, mineru_runner=mineru_runner, translator=translator)
    from .checkpoint import ResponseCheckpoint, execution_identity, implementation_digest
    import copy
    if any((output_dir / name).exists() for name in ['scan_parse_manifest.json','scan_regions.jsonl','translated_scanned.pdf','scan_checkpoint_receipt.json']):
        raise ValueError('checkpoint resume requires a fresh output attempt; reuse only the checkpoint directory')
    identity = execution_identity(sha256_file(input_pdf), args, implementation_digest(Path(__file__).resolve().parent.parent))
    args = copy.deepcopy(args)
    with ResponseCheckpoint(Path(checkpoint_root), identity) as checkpoint:
        try:
            result = _run_scanned_translation(input_pdf, output_dir, route_manifest, args, rapidocr_runner=rapidocr_runner, mineru_runner=mineru_runner,
                                             translator=lambda text, call_args: checkpoint.translate(text, call_args, translator))
            result['translation_checkpoint'] = checkpoint.report()
            manifest_path = Path(result['render_manifest'])
            render = json.loads(manifest_path.read_text(encoding='utf-8'))
            render['translation_checkpoint'] = checkpoint.report()
            render['checkpoint_receipt'] = str(output_dir / 'scan_checkpoint_receipt.json')
            _write_json(manifest_path, render)
            return result
        finally:
            _write_json(output_dir / 'scan_checkpoint_receipt.json', checkpoint.report())

def _render_isolated_writeback(source, target, regions, *, dpi):
    """在有界冷进程中写回多页分列OCR，避免OCR与PDF原生库共用热运行时。"""
    import sys,uuid
    from bounded_execution import run_bounded
    from qa_source_contract import file_ref,read_bound_json
    root=Path(target).parent/('writeback-worker-'+uuid.uuid4().hex[:12]);root.mkdir(exist_ok=False)
    input_path=root/'regions.jsonl';write_jsonl(input_path,regions);source_ref=file_ref(source);result_path=root/'result.json'
    command=[sys.executable,str(Path(__file__).with_name('render_worker.py')),'--source',str(source),
             '--source-sha',source_ref['sha256'],'--target',str(target),'--regions',str(input_path),
             '--result',str(result_path),'--dpi',str(dpi)]
    outcome=run_bounded(command,cwd=Path(__file__).resolve().parents[1],receipt_dir=root/'execution',
        operation='scanned_isolated_writeback',timeout_seconds=90,interval_seconds=5,rss_limit=4*1024**3,max_processes=16)
    _write_json(root/'outcome.json',outcome)
    if outcome['status']!='succeeded':raise RuntimeError('isolated_writeback_failed:'+str(root/'outcome.json'))
    result=read_bound_json(file_ref(result_path))
    if result['source']!=file_ref(source) or result['target']!=file_ref(target):raise ValueError('isolated_writeback_result_identity')
    ref=result['rendered_regions'];path=Path(ref['path'])
    if file_ref(path)!=ref or path.stat().st_size>64*1024**2:raise ValueError('isolated_writeback_regions_changed')
    actual=[json.loads(l)for l in path.read_text().splitlines()]
    if [r['region_id']for r in actual]!=[r['region_id']for r in regions]:raise ValueError('isolated_writeback_region_scope_changed')
    regions[:]=actual
    return {**result['font_embedding'],'writeback_isolation':{'worker_result':file_ref(result_path),'outcome':file_ref(root/'outcome.json'),'quality_pass':False}}

def _run_scanned_translation(
    input_pdf: Path, output_dir: Path, route_manifest: dict[str, Any], args: Any, *,
    rapidocr_runner: RapidOCRRunner, mineru_runner: MinerURunner, translator: Translator,
) -> dict[str, Any]:
    from scanned_raster.pipeline_ocr import _annotate_mineru_regions_with_rapidocr_geometry
    from scanned_raster.pipeline_ocr_groups import _coalesce_rapidocr_paragraph_bands
    from scanned_raster.pipeline_rendering import _render_translated_pdf
    from scanned_raster.pipeline_resources import _check_memory_limit, _config_sha256
    from scanned_raster.pipeline_translation import _selected_pages, _translate_regions
    from .checkpoint import CheckpointError
    selected_pages = _selected_pages(route_manifest, getattr(args, "pages", None))
    max_pages = int(getattr(args, "scanned_max_pages", 5))
    if not 1 <= max_pages <= 20:
        raise ValueError("--scanned-max-pages must be between 1 and 20")
    parse_manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "input_pdf": str(input_pdf),
        "input_sha256": sha256_file(input_pdf),
        "scanned_parser": args.scanned_parser,
        "mineru_version": MINERU_VERSION,
        "mineru_runtime": args.mineru_runtime,
        "requested_mineru_tier": args.mineru_tier,
        "scanned_max_pages": max_pages,
        "config_sha256": _config_sha256(
            {
                "scanned_parser": args.scanned_parser,
                "mineru_runtime": args.mineru_runtime,
                "mineru_tier": args.mineru_tier,
                "dpi": DEFAULT_SCAN_DPI,
                "emit_mineru_render_candidates": bool(args.emit_mineru_render_candidates),
                "pages": getattr(args, "pages", None),
                "scanned_max_pages": max_pages,
            }
        ),
        "pages": [],
        "fallback_or_escalation_reasons": [],
        "credentials_recorded": False,
    }
    all_regions: list[dict[str, Any]] = []
    page_hashes: dict[int, str] = {}
    blocking = False
    if len(selected_pages) > max_pages:
        parse_manifest["status"] = "needs_review"
        parse_manifest["fallback_or_escalation_reasons"].append(
            f"scanned_page_limit_exceeded:{len(selected_pages)}>{max_pages}"
        )
        selected_pages = []
        blocking = True

    for page_number in selected_pages:
        _check_memory_limit()
        rapid_regions, page_info = rapidocr_runner(input_pdf, page_number, DEFAULT_SCAN_DPI)
        page_hashes[page_number] = str(page_info.get("page_image_sha256") or "")
        assessment = assess_rapidocr_page(
            rapid_regions,
            page_width=float(page_info.get("page_width") or 1.0),
            nonblank=bool(page_info.get("nonblank", True)),
        )
        page_record: dict[str, Any] = {
            "page": page_number,
            "rapidocr": assessment,
            "column_recognition": page_info.get("column_recognition"),
            "selected_provider": "rapidocr",
            "selected_tier": None,
            "attempts": [{"provider": "rapidocr", "status": "ok", "region_count": len(rapid_regions)}],
        }
        chosen = rapid_regions
        should_use_mineru = args.scanned_parser == "mineru" or (
            args.scanned_parser == "auto" and assessment["escalate"]
        )
        if should_use_mineru:
            requested = args.mineru_tier
            tiers = [requested] if requested in {"basic", "standard", "advanced"} else ["basic", "standard", "advanced"]
            mineru_selected = False
            for tier in tiers:
                attempt_dir = output_dir / "scanned_parse" / f"page-{page_number:04d}"
                try:
                    result = mineru_runner(
                        input_pdf,
                        output_dir=attempt_dir,
                        tier=tier,
                        runtime=args.mineru_runtime,
                        page_range=str(page_number),
                        allow_cloud_layout=bool(args.allow_cloud_layout),
                        emit_render_candidates=bool(args.emit_mineru_render_candidates),
                        page_image_hashes=page_hashes,
                    )
                except CheckpointError:
                    raise
                except (MinerUUnavailableError, PermissionError, ImportError) as exc:
                    code = "mineru_unavailable" if not isinstance(exc, PermissionError) else "mineru_remote_not_authorized"
                    page_record["attempts"].append({"provider": "mineru", "tier": tier, "status": code, "error": str(exc)})
                    parse_manifest["fallback_or_escalation_reasons"].append(f"page_{page_number}:{code}")
                    blocking = args.scanned_parser == "mineru" or args.scanned_parser == "auto"
                    break
                except Exception as exc:  # noqa: BLE001
                    page_record["attempts"].append({"provider": "mineru", "tier": tier, "status": "error", "error": str(exc)})
                    parse_manifest["fallback_or_escalation_reasons"].append(f"page_{page_number}:mineru_{tier}_error")
                    if tier == tiers[-1]:
                        blocking = True
                    continue
                mineru_regions = [item for item in result.get("regions") or [] if int(item.get("page", -1)) == page_number]
                geometry_count = _annotate_mineru_regions_with_rapidocr_geometry(
                    mineru_regions,
                    rapid_regions,
                )
                gate = assess_mineru_result(
                    mineru_regions,
                    rapidocr_regions=rapid_regions,
                    warnings=list(result.get("warnings") or []),
                )
                page_record["attempts"].append(
                    {
                        "provider": "mineru",
                        "tier": tier,
                        "status": result.get("status"),
                        "region_count": len(mineru_regions),
                        "quality_gate": gate,
                        "raw_output_dir": result.get("raw_output_dir"),
                        "render_candidates": result.get("render_candidates") or [],
                        "rapidocr_geometry_enriched_regions": geometry_count,
                    }
                )
                if gate["accepted"] or requested == tier:
                    chosen = mineru_regions
                    page_record.update(selected_provider="mineru", selected_tier=tier)
                    mineru_selected = gate["accepted"]
                    if not gate["accepted"]:
                        blocking = True
                    break
                parse_manifest["fallback_or_escalation_reasons"].extend(
                    f"page_{page_number}:{reason}" for reason in gate["reasons"]
                )
            if not mineru_selected and page_record["selected_provider"] != "mineru":
                blocking = True
        elif args.scanned_parser == "rapidocr" and assessment["escalate"]:
            page_record["forced_rapidocr_warnings"] = assessment["reasons"]
        if getattr(args, 'scanned_page_profile', None) == 'image_cover':
            from .cover_layout import prepare_cover_regions
            chosen = prepare_cover_regions(chosen, page_width=float(page_info['page_width']), page_height=float(page_info['page_height']))
            page_record['paragraph_grouping'] = {'policy':'image_cover_title_and_protected_fields_v1'}
        elif page_record["selected_provider"] == "rapidocr":
            source_region_count = len(chosen)
            chosen = prepare_centered_frontmatter(prepare_name_columns(chosen))
            chosen = _coalesce_rapidocr_paragraph_bands(chosen)
            page_record["rapidocr"]["source_region_count"] = source_region_count
            page_record["rapidocr"]["render_region_count"] = len(chosen)
        elif page_record["selected_provider"] == "mineru":
            from .paragraph_recovery import coalesce_mineru_text_lines
            source_region_count = len(chosen)
            chosen = prepare_centered_frontmatter(prepare_name_columns(chosen))
            chosen = coalesce_mineru_text_lines(chosen)
            page_record["paragraph_grouping"] = {"policy": "mineru_same_page_column_lines_v1", "source_region_count": source_region_count, "render_region_count": len(chosen)}
        all_regions.extend(chosen)
        parse_manifest["pages"].append(page_record)

    if not selected_pages:
        blocking = True
        parse_manifest["fallback_or_escalation_reasons"].append("no_scanned_pages_selected")
    if blocking:
        parse_manifest["status"] = "needs_review"

    translation_failures = _translate_regions(all_regions, args, translator) if all_regions else []
    if translation_failures:
        parse_manifest["status"] = "partial"
        parse_manifest["translation_failures"] = translation_failures
    parse_manifest["region_count"] = len(all_regions)
    parse_manifest_path = _write_json(output_dir / "scan_parse_manifest.json", parse_manifest)
    regions_path = output_dir / "scan_regions.jsonl"
    write_jsonl(regions_path, all_regions)

    translated_pdf: Path | None = None
    font_embedding: dict[str, Any] | None = None
    if all_regions:
        translated_pdf = output_dir / "translated_scanned.pdf"
        column_pages={r['page'] for r in all_regions if r.get('source_column_policy')}
        if column_pages and len({r['page']for r in all_regions})>1:
            font_embedding = _render_isolated_writeback(input_pdf, translated_pdf, all_regions, dpi=DEFAULT_SCAN_DPI)
        else:
            font_embedding = _render_translated_pdf(input_pdf, translated_pdf, all_regions, dpi=DEFAULT_SCAN_DPI)
        parse_manifest["render_font"] = font_embedding
        _write_json(parse_manifest_path, parse_manifest)
        write_jsonl(regions_path, all_regions)
    extracted_text = _extract_text(translated_pdf) if translated_pdf and translated_pdf.exists() else ""
    bilingual_pdf: Path | None = None
    bilingual_check: dict[str, Any] | None = None
    bilingual_requested = bool(getattr(args, 'dual', True)) and getattr(args, 'bilingual_layout', 'en-left-zh-right') != 'off'
    if translated_pdf and bilingual_requested:
        from build_bilingual_pdf import bilingual_direction, build_manifest
        from assess_delivery import check_bilingual_sides
        bilingual_target = output_dir / 'bilingual_scanned.pdf'
        # scanned_raster 路线只接受英译中（中译英在入口即拒绝），方向由路线合同确定。
        bilingual_manifest = build_manifest(input_pdf, translated_pdf, bilingual_target,
                                            direction=bilingual_direction('en', 'zh', basis='route_contract_scanned_raster_en_to_zh'))
        if bilingual_manifest['status'] == 'ok':
            bilingual_check = check_bilingual_sides(input_pdf, translated_pdf, bilingual_target, max_pages=20)
            bilingual_manifest['side_verification'] = bilingual_check
            if bilingual_check['status'] == 'ok':
                bilingual_pdf = bilingual_target
            else:
                bilingual_manifest['status'] = 'error'
        else:
            bilingual_check = {'status':'error', 'reason':'bilingual_build_failed'}
        _write_json(output_dir / 'bilingual_pdf_manifest.json', bilingual_manifest)
    gate = evaluate_scan_quality_gate(
        regions=all_regions,
        extracted_text=extracted_text,
        font_embedding=font_embedding,
        human_visual_review=None,
        bilingual_left_right_consistent=(bilingual_check.get('status') == 'ok' if bilingual_check else None),
    )
    if blocking and gate.get("status") != "blocking":
        gate["status"] = "blocking"
        gate.setdefault("issues", []).append(
            {
                "rule": "mineru_escalation_unresolved",
                "severity": "blocking",
                "region_id": None,
                "page": None,
                "evidence": "; ".join(parse_manifest["fallback_or_escalation_reasons"]),
            }
        )
    gate_path = _write_json(output_dir / "scan_quality_gate.json", dict(gate))
    if sha256_file(input_pdf) != parse_manifest['input_sha256']:
        raise ValueError('source PDF changed during scanned translation')
    status = "ok" if gate.get("status") == "ok" else str(gate.get("status") or "partial")
    from qa_source_contract import file_ref
    technical={'schema_version':1,'producer':'scanned_raster_quality_gate','source':file_ref(input_pdf),
               'target':file_ref(translated_pdf) if translated_pdf and translated_pdf.exists() else None,
               'gate_ref':file_ref(gate_path),
               'blocking_issues':[i for i in gate.get('issues',[]) if i.get('severity')=='blocking'],
               'quality_pass':False,'independent_acceptance':False}
    technical_path=_write_json(output_dir/'technical_quality.json',technical)
    technical_ref=file_ref(technical_path)
    render_path = _write_json(output_dir / 'render_manifest.json', {
        'status':status, 'actual_render_source':'scanned_raster' if translated_pdf else None,
        'delivery_mode':'experimental_candidate_pending_review', 'input_sha256':parse_manifest['input_sha256'],
        'outputs':{'translated_pdf':str(translated_pdf) if translated_pdf else None,
                   'standard_bilingual_pdf':str(bilingual_pdf) if bilingual_pdf else None},
        'candidate_sha256':sha256_file(translated_pdf) if translated_pdf else None,
        'bilingual_requested':bilingual_requested, 'bilingual_verification':bilingual_check,
        'scan_quality_gate':str(gate_path), 'technical_quality_ref':technical_ref, 'strict_delivery':False, 'human_visual_accepted':False})
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "status": status,
        "route_status": route_manifest.get("route_status"),
        "document_route": "scanned_raster",
        "route_manifest": route_manifest,
        "scan_parse_manifest": str(parse_manifest_path),
        "scan_regions": str(regions_path),
        "scan_quality_gate": str(gate_path),
        "technical_quality_ref": technical_ref,
        "translated_pdf": str(translated_pdf) if translated_pdf else None,
        "standard_bilingual_pdf": str(bilingual_pdf) if bilingual_pdf else None,
        "render_manifest": str(render_path),
        "font_embedding": font_embedding,
        "intended_render_source": "scanned_raster",
        "actual_render_source": "scanned_raster" if translated_pdf else None,
        "strict_delivery": False,
        "human_visual_accepted": False,
        "experimental": True,
    }


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
