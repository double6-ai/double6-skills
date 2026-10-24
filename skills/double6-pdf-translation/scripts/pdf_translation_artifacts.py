# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation artifacts：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def write_glossary(output_dir: Path, manifest: dict[str, Any]) -> Path:
    source_path = output_dir / "source.md"
    glossary_path = output_dir / "glossary.tsv"
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    rows = extract_terms.extract_candidate_terms(
        source_text,
        blocks=manifest.get("blocks") if isinstance(manifest.get("blocks"), list) else [],
    )
    extract_terms.write_glossary(rows, glossary_path)
    extract_terms.write_extraction_report(source_text, rows, output_dir / "glossary.extraction.json")
    return glossary_path

def enrich_quality_artifacts(output_dir: Path, manifest: dict[str, Any], glossary_path: Path) -> dict[str, Any]:
    coverage_gate = check_translation.build_coverage_gate(manifest)
    manifest["coverage_gate"] = coverage_gate
    (output_dir / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    glossary = check_translation.load_glossary(glossary_path)
    term_policy = check_translation.build_term_policy(glossary, manifest=manifest)
    entity_map = check_translation.build_entity_map(manifest, glossary)
    document_memory = check_translation.build_document_memory(
        manifest,
        glossary,
        entity_map=entity_map,
        term_policy=term_policy,
    )
    (output_dir / "term_policy.json").write_text(json.dumps(term_policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "entity_map.json").write_text(json.dumps(entity_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "document_memory.json").write_text(
        json.dumps(document_memory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "coverage_gate": coverage_gate,
        "term_policy": term_policy,
        "entity_map": entity_map,
        "document_memory": document_memory,
    }

def collect_pdfs(output_dir: Path) -> list[Path]:
    ignored_parts = {"_backend_working", "_intermediate_backend_dual"}
    return sorted(
        path
        for path in output_dir.rglob("*.pdf")
        if path.is_file() and not (set(path.relative_to(output_dir).parts) & ignored_parts)
    )

def select_pdf_outputs(paths: list[Path]) -> dict[str, str | None]:
    dual = next((path for path in paths if "dual" in path.name.lower() or "bilingual" in path.name.lower()), None)
    mono = next((path for path in paths if "mono" in path.name.lower() or ".zh.mono." in path.name.lower()), None)
    selected = mono or dual or (paths[0] if paths else None)
    return {
        "translated_pdf": str(selected) if selected else None,
        "mono_pdf": str(mono) if mono else None,
        "dual_pdf": str(dual) if dual else None,
    }

def resolve_bilingual_source_pdf(input_pdf: Path) -> Path:
    from pdf_translation_paths import paper_translation_run_root
    if input_pdf.exists():
        return input_pdf

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    candidate_roots = [
        input_pdf.parent,
        paper_translation_run_root() / "04_eval" / "materials",
    ]
    seen_roots: set[Path] = set()
    source_stem = normalized(input_pdf.stem)
    for root in candidate_roots:
        root = root.expanduser().resolve()
        if root in seen_roots or not root.exists():
            continue
        seen_roots.add(root)
        exact = root / input_pdf.name
        if exact.exists():
            return exact
        for candidate in sorted(root.glob("*.pdf")):
            candidate_stem = normalized(candidate.stem)
            if source_stem and source_stem in candidate_stem:
                return candidate
    return input_pdf


def build_standard_bilingual_output(
    input_pdf: Path,
    output_dir: Path,
    selected_outputs: dict[str, str | None],
    *,
    enabled: bool,
    render_mode: str = "pypdf-vector",
    raster_dpi: int = 144,
    source_language: str | None = None,
    target_language: str | None = None,
    direction_basis: str | None = None,
) -> dict[str, Any]:
    """标准双语 PDF：左页为源文页、右页为译文页（页序固定）。

    文件名与清单语言标注只来自调用方传入的本次任务方向；未传入时不猜，
    使用中性名称 `<stem>.source-left.translation-right.dual.pdf`，清单记 unknown。
    """
    if not enabled:
        return {"status": "skipped", "reason": "dual_output_disabled", "layout": None}
    direction = build_bilingual_pdf.bilingual_direction(source_language, target_language, basis=direction_basis)
    fields = build_bilingual_pdf.direction_fields(direction)
    right_pdf_value = selected_outputs.get("mono_pdf") or selected_outputs.get("translated_pdf")
    if not right_pdf_value:
        return {"status": "skipped", "reason": "missing_mono_translated_pdf", **fields}
    right_pdf = Path(right_pdf_value)
    if not right_pdf.exists():
        return {"status": "skipped", "reason": "translated_pdf_not_found", **fields, "translated_pdf": str(right_pdf)}
    source_pdf = resolve_bilingual_source_pdf(input_pdf)
    output_pdf = output_dir / f"{input_pdf.stem}.{direction['name_infix']}.dual.pdf"
    manifest = build_bilingual_pdf.build_manifest(source_pdf, right_pdf, output_pdf, mode=render_mode, raster_dpi=raster_dpi,
                                                  direction=direction)
    if source_pdf != input_pdf:
        manifest["requested_source_pdf"] = str(input_pdf)
        manifest["resolved_source_pdf"] = str(source_pdf)
    manifest_path = output_dir / "bilingual_pdf_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if manifest.get("status") == "ok":
        selected_outputs["dual_pdf"] = str(output_pdf)
        selected_outputs["standard_bilingual_pdf"] = str(output_pdf)
    return {**manifest, "manifest_path": str(manifest_path)}

def maybe_build_visual_repair_output(
    args: argparse.Namespace,
    input_pdf: Path,
    output_dir: Path,
    selected_outputs: dict[str, str | None],
    tracking_path: Path,
) -> dict[str, Any]:
    mode = str(getattr(args, "visual_repair_mode", "auto") or "auto")
    if mode == "off":
        return {"version": 1, "status": "skipped", "reason": "visual_repair_off", "selected_as_delivery": False}
    translated = Path(str(selected_outputs.get("mono_pdf") or selected_outputs.get("translated_pdf") or ""))
    if not translated.is_file():
        return {"version": 1, "status": "skipped", "reason": "missing_translated_pdf", "selected_as_delivery": False}
    # 候选页是译文单语页：语言标注取本次目标语言（英译中仍为 .zh.mono.pdf）。
    candidate_language = "en" if str(getattr(args, "target_language", "zh") or "zh") == "en" else "zh"
    structured_output_pdf = output_dir / f"{input_pdf.stem}.round38-structured-candidates.{candidate_language}.mono.pdf"
    structured_manifest_path = output_dir / "structured_visual_candidates_manifest.json"
    human_review_path = output_dir / "human_visual_review.json"
    try:
        structured_manifest = build_structured_visual_candidates.build_structured_visual_candidates(
            source_pdf=input_pdf,
            translated_pdf=translated,
            output_pdf=structured_output_pdf,
            manifest_path=structured_manifest_path,
            human_review_path=human_review_path,
        )
    except Exception as exc:  # noqa: BLE001 - 测试/降级路径可能只有占位 PDF，视觉修复不能阻断主链路
        structured_manifest = {
            "version": 1,
            "status": "unavailable",
            "reason": f"structured_visual_candidate_failed: {exc}",
            "candidate_count": 0,
            "safe_for_auto_delivery": False,
            "human_review_required": False,
            "human_review_status": "unavailable",
        }
        structured_manifest_path.write_text(json.dumps(structured_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "version": 1,
        "status": "skipped",
        "reason": "round38_redaction_repairs_disabled_by_default",
        "mode": mode,
        "repair_count": 0,
        "safe_for_auto_delivery": False,
        "human_review_required": True,
        "human_review_status": "pending",
        "selected_as_delivery": False,
        "legacy_visual_repair_policy": "redaction_or_gray_region_repairs_are_rejected_candidates_only",
        "structured_visual_candidates_manifest": str(structured_manifest_path),
        "structured_visual_candidates_status": structured_manifest.get("status"),
        "structured_visual_candidate_pdf": structured_manifest.get("output_pdf"),
        "human_visual_review": str(human_review_path) if human_review_path.exists() else None,
        "delivery_note": "Round38 does not let redaction/gray-region visual repairs enter delivery; structured candidates require human accepted status first.",
    }
    manifest["manifest_path"] = str(output_dir / "visual_repair_manifest.json")
    manifest["selected_as_delivery"] = False
    if structured_output_pdf.exists():
        selected_outputs["structured_visual_candidate_pdf"] = str(structured_output_pdf)
        selected_outputs["structured_visual_candidates_manifest"] = str(structured_manifest_path)
        selected_outputs["human_visual_review"] = str(human_review_path) if human_review_path.exists() else None
    if mode == "auto" and structured_manifest.get("status") == "candidate_pending_human_review":
        manifest["auto_delivery_blocked_reason"] = (
            "structured visual candidates are pending human review and are not selected as the bilingual right page"
        )
    (output_dir / "visual_repair_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

def mirror_latex_direct_bilingual_output(
    bilingual_manifest: dict[str, Any],
    latex_direct_manifest: dict[str, Any],
    selected_outputs: dict[str, str | None],
) -> str | None:
    if bilingual_manifest.get("status") != "ok" or not bilingual_manifest.get("output_pdf"):
        return None
    latex_pdf_value = latex_direct_manifest.get("translated_pdf")
    if not latex_pdf_value:
        return None
    latex_pdf = Path(str(latex_pdf_value))
    if not latex_pdf.exists():
        return None
    target = latex_pdf.with_name(f"{latex_pdf.stem}.{build_bilingual_pdf.name_infix_for(bilingual_manifest)}.dual.pdf")
    source = Path(str(bilingual_manifest["output_pdf"]))
    try:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    except OSError:
        return None
    selected_outputs["latex_direct_dual_pdf"] = str(target)
    return str(target)

def relocate_backend_dual_intermediate(
    output_dir: Path,
    backend_dual_pdf: str | None,
    standard_dual_pdf: str | None,
) -> str | None:
    if not backend_dual_pdf:
        return None
    source = Path(backend_dual_pdf)
    if not source.exists():
        return str(source)
    if standard_dual_pdf and source.resolve() == Path(standard_dual_pdf).resolve():
        return str(source)
    target_dir = output_dir / "_intermediate_backend_dual"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if source.resolve() != target.resolve():
        source.replace(target)
    return str(target)

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

def write_layout_map(
    output_dir: Path,
    manifest: dict[str, Any],
    render_manifest: dict[str, Any],
    backend_tracking_path: Path | None = None,
) -> Path:
    translated_pdf = render_manifest.get("outputs", {}).get("translated_pdf") if isinstance(render_manifest.get("outputs"), dict) else None
    if backend_tracking_path and backend_tracking_path.exists():
        babeldoc_map = build_babeldoc_il_layout_map.build_from_file(
            backend_tracking_path,
            translated_pdf=str(translated_pdf) if translated_pdf else None,
        )
        babeldoc_path = output_dir / "babeldoc_il_layout_map.json"
        babeldoc_path.write_text(json.dumps(babeldoc_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if babeldoc_map.get("blocks"):
            babeldoc_map["coverage_gate"] = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else check_translation.build_coverage_gate(manifest)
            babeldoc_map["source_manifest_block_count"] = len(manifest.get("blocks", []) if isinstance(manifest.get("blocks"), list) else [])
            babeldoc_map["layout_source_candidates"].append(
                {
                    "source": "source_manifest_ir_adapter",
                    "status": "fallback_available",
                    "block_count": len(manifest.get("blocks", []) if isinstance(manifest.get("blocks"), list) else []),
                }
            )
            path = output_dir / "layout_map.json"
            path.write_text(json.dumps(babeldoc_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return path
    blocks = manifest.get("blocks") if isinstance(manifest.get("blocks"), list) else []
    mappings = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or f"block-{index:04d}")
        element_type = str(block.get("element_type") or "paragraph")
        bbox = block.get("bbox")
        role = str(block.get("layout_role") or block.get("role") or element_type)
        placeholders = []
        for key in ["protected_spans", "placeholders"]:
            value = block.get(key)
            if isinstance(value, list):
                placeholders.extend(value)
        mappings.append(
            {
                "block_id": block_id,
                "page": block.get("page"),
                "element_type": element_type,
                "layout_role": role,
                "section": block.get("section"),
                "reading_order": index,
                "bbox": bbox,
                "span_count": len(block.get("spans", [])) if isinstance(block.get("spans"), list) else None,
                "font": block.get("font"),
                "font_size": block.get("font_size"),
                "placeholder_count": len(placeholders),
                "placeholders": placeholders[:20],
                "engine_block_id": block.get("engine_block_id"),
                "char_count": block.get("char_count"),
                "translated_block_id": block_id,
                "reanchor_status": "engine_block_missing" if not block.get("engine_block_id") else "engine_block_available",
                "backfill_status": "external_engine_unaligned" if not block.get("engine_block_id") else "engine_block_reanchor_pending",
                "failure_stage": "layout" if bbox is None else "unknown",
            }
        )
    layout_map = {
        "version": 1,
        "status": "ok" if mappings else "warn",
        "layout_source": "source_manifest_ir_adapter",
        "ir_contract": {
            "fields": ["page", "block", "span/font", "bbox", "role", "placeholder", "engine_block", "reanchor_status"],
            "stable_engine_block_required_for_direct_pdf_patch": True,
        },
        "engine": render_manifest.get("engine"),
        "translated_pdf": render_manifest.get("outputs", {}).get("translated_pdf"),
        "coverage_gate": manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else check_translation.build_coverage_gate(manifest),
        "blocks": mappings,
        "notes": [
            "PDF 强路径默认由 PDFMathTranslate-next 完成版面重排；本文件提供本 skill 可回查的最小 block 映射。",
            "外部引擎未暴露稳定 block 坐标时，bbox 允许为空，但 page、reading_order 和回填状态必须保留。",
        ],
    }
    path = output_dir / "layout_map.json"
    path.write_text(json.dumps(layout_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

def write_translation_artifacts(
    output_dir: Path,
    translated_text: str,
    extraction_method: str,
    manifest: dict[str, Any],
    model: str,
    *,
    executor_provider: str = "pdfmathtranslate-next",
) -> Path:
    translation_path = output_dir / "translation.md"
    blocks_path = output_dir / "translation_blocks.jsonl"
    source_blocks = manifest.get("blocks") if isinstance(manifest.get("blocks"), list) else []
    translation_path.write_text(translated_text.rstrip() + "\n", encoding="utf-8")
    with blocks_path.open("w", encoding="utf-8") as handle:
        if source_blocks:
            for block in source_blocks:
                if not isinstance(block, dict):
                    continue
                block_translation = translated_text if len(source_blocks) == 1 else ""
                alignment_status = "aligned" if len(source_blocks) == 1 else "external_pdf_text_unaligned_no_block_local_target"
                handle.write(
                    json.dumps(
                        {
                            "block_id": block.get("block_id"),
                            "status": "ok" if len(source_blocks) == 1 else "needs_block_alignment",
                            "source_text": block.get("text", ""),
                            "translation": block_translation,
                            "translation_ref": "translation.md" if len(source_blocks) != 1 else None,
                            "translation_note": "external_pdf_text_unaligned_no_block_local_target" if len(source_blocks) != 1 else None,
                            "section": block.get("section"),
                            "page": block.get("page"),
                            "element_type": block.get("element_type"),
                            "executor_provider": executor_provider,
                            "executor_model": model,
                            "text_extraction_method": extraction_method,
                            "alignment_status": alignment_status,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        else:
            handle.write(
                json.dumps(
                    {
                        "block_id": "document",
                        "status": "ok",
                        "source_text": "",
                        "translation": translated_text,
                        "executor_provider": executor_provider,
                        "executor_model": model,
                        "text_extraction_method": extraction_method,
                        "alignment_status": "external_pdf_text_unaligned",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return translation_path

def run_quality_check(output_dir: Path, render_manifest: dict[str, Any]) -> Path:
    source_path = output_dir / "source.md"
    translation_path = output_dir / "translation.md"
    glossary_path = output_dir / "glossary.tsv"
    manifest_path = output_dir / "source_manifest.json"
    protected_spans_path = output_dir / "protected_spans.json"
    translation_blocks_path = output_dir / "translation_blocks.jsonl"
    quality_path = output_dir / "quality_report.md"

    source = source_path.read_text(encoding="utf-8", errors="replace")
    translation = translation_path.read_text(encoding="utf-8", errors="replace")
    repair_manifest = policy_utils.load_json(output_dir / "pdf_direct_text_repair_manifest.json")
    if repair_manifest.get("status") == "repaired":
        outputs = render_manifest.get("outputs") if isinstance(render_manifest.get("outputs"), dict) else {}
        repaired_pdf = Path(str(outputs.get("translated_pdf") or outputs.get("mono_pdf") or ""))
        repaired_text, repaired_text_method = extract_pdf_text(repaired_pdf if repaired_pdf.exists() else None)
        if repaired_text.strip():
            translation = repaired_text
            render_manifest["quality_report_translation_source"] = {
                "type": "repaired_pdf_text",
                "method": repaired_text_method,
                "pdf": str(repaired_pdf),
                "repair_manifest": str(output_dir / "pdf_direct_text_repair_manifest.json"),
            }
    # 通用 QA 只评最终可见译文。TeX 注释、宏和编译提示不是待译正文；
    # 命令、公式及 URL 的源码完整性由 latex_direct_quality_gate 单独检查。
    glossary = check_translation.load_glossary(glossary_path)
    manifest = check_translation.load_json(manifest_path)
    protected_spans = check_translation.load_json(protected_spans_path)
    translation_blocks = check_translation.load_translation_blocks(translation_blocks_path)
    manifest["coverage_gate"] = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else check_translation.build_coverage_gate(manifest, translation)
    term_policy = check_translation.build_term_policy(glossary, manifest=manifest, source=source)
    entity_map = check_translation.build_entity_map(manifest, glossary)
    if str(render_manifest.get("target_language") or "") == "en":
        from check_translation_gates import policies_for_target
        term_policy, entity_map = policies_for_target(term_policy, entity_map, "en")
    # 文字 QA 按本次任务记录的目标语言选择（render_manifest.target_language）；
    # 中译英不把正常英文译文当“未译英文”，也不做英→中残留替换。
    qa_target = str(render_manifest.get("target_language") or "") or None
    issues = check_translation.collect_issues(
        source,
        translation,
        glossary,
        manifest=manifest,
        protected_spans=protected_spans,
        translation_blocks=translation_blocks,
        render_manifest=render_manifest,
        target_language=qa_target,
    )
    report_text = check_translation.render_quality_report(issues)
    visual_repair = policy_utils.load_json(output_dir / "visual_repair_manifest.json")
    if visual_repair.get("status") == "repaired":
        report_text += (
            "\n\n## 可见 PDF 修复证据\n\n"
            f"- 状态：`{visual_repair.get('status')}`\n"
            f"- 修复页/区域数：`{visual_repair.get('repair_count', 0)}`\n"
            f"- 修复 PDF：`{visual_repair.get('output_pdf')}`\n"
            f"- 双语交付是否采用：`{visual_repair.get('selected_as_delivery', False)}`\n"
            "- 说明：该层优先修复肉眼可见质量；局部修复页可能牺牲部分可复制文本层，不能伪装为完整矢量写回。\n"
        )
    structured_visual = policy_utils.load_json(output_dir / "structured_visual_candidates_manifest.json")
    if structured_visual.get("status") == "candidate_pending_human_review":
        report_text += (
            "\n\n## Round38 非破坏式视觉候选\n\n"
            f"- 状态：`{structured_visual.get('status')}`\n"
            f"- 候选页/项数：`{structured_visual.get('candidate_count', 0)}`\n"
            f"- 候选 PDF：`{structured_visual.get('output_pdf')}`\n"
            f"- 人工视觉门：`{structured_visual.get('human_review_status')}`\n"
            "- 说明：这些页面只作为干净候选页或修复计划，不会进入标准双语 PDF 右页，除非 `human_visual_review.json` 明确 accepted。\n"
        )
    quality_path.write_text(report_text, encoding="utf-8")
    quality_path.with_name("alignment_report.json").write_text(
        json.dumps(check_translation.build_alignment_report(manifest, translation_blocks), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    quality_path.with_name("document_memory.json").write_text(
        json.dumps(
            check_translation.build_document_memory(
                manifest,
                glossary,
                entity_map=entity_map,
                term_policy=term_policy,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    quality_path.with_name("term_policy.json").write_text(
        json.dumps(term_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    quality_path.with_name("entity_map.json").write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    quality_path.with_name("qa_checks.json").write_text(
        json.dumps(check_translation.build_qa_checks(issues), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    affected_blocks = check_translation.build_affected_blocks(issues, manifest, translation_blocks)
    quality_path.with_name("affected_blocks.json").write_text(
        json.dumps(affected_blocks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    quality_path.with_name("confirmed_repair_plan.json").write_text(
        json.dumps(
            check_translation.build_confirmed_repair_plan(
                check_translation.load_json(quality_path.with_name("manual_confirmations.json")),
                affected_blocks,
                manifest,
                translation_blocks,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    repaired_translation, qa_repair_plan = repair_quality_issues.repair_translation(
        translation,
        affected_blocks,
        {} if qa_target == "en" else repair_quality_issues.DEFAULT_RESIDUE_TRANSLATIONS,
    )
    repaired_path = quality_path.with_name("translation.qa_repaired.md")
    qa_repair_plan_path = quality_path.with_name("qa_repair_plan.json")
    repaired_path.write_text(repaired_translation, encoding="utf-8")
    qa_repair_plan.update(
        {
            "input_translation": str(translation_path),
            "affected_blocks": str(quality_path.with_name("affected_blocks.json")),
            "output_translation": str(repaired_path),
        }
    )
    qa_repair_plan_path.write_text(json.dumps(qa_repair_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    layout_map = check_translation.load_json(output_dir / "layout_map.json")
    pdf_rerender_plan = build_pdf_rerender_plan.build_plan(
        source_manifest=manifest,
        layout_map=layout_map,
        affected_blocks=affected_blocks,
        qa_repair_plan=qa_repair_plan,
        render_manifest=render_manifest,
        term_policy=term_policy,
        entity_map=entity_map,
    )
    quality_path.with_name("pdf_rerender_plan.json").write_text(
        json.dumps(pdf_rerender_plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return quality_path

def render_qa_repaired_pdf(output_dir: Path, args: argparse.Namespace, translated_pdf: str | Path | None = None) -> dict[str, Any]:
    mode = str(getattr(args, "post_qa_repair", "auto") or "auto")
    repaired_path = output_dir / "translation.qa_repaired.md"
    final_pdf = output_dir / "final_readable.pdf"
    final_manifest_path = output_dir / "final_pdf_manifest.json"
    if mode == "off":
        return {"status": "skipped", "reason": "post_qa_repair_off"}
    if not repaired_path.exists():
        return {"status": "skipped", "reason": "missing_translation_qa_repaired"}
    input_pdf = getattr(args, "input_pdf", None)
    source_pdf = Path(str(input_pdf)).expanduser() if input_pdf else None
    # 标题取原文件名（不再用输出目录名，曾导致可读版标题为 "out"）。
    title = source_pdf.stem if source_pdf is not None else output_dir.name
    math_source = Path(str(translated_pdf)) if translated_pdf else None
    manifest = render_readable_pdf.render_pdf(
        repaired_path,
        final_pdf,
        title=title,
        # 显式路径原样传入：不可用由 render_pdf 稳定拒绝，不在这里折成“未提供”（review-4）。
        math_source_pdf=math_source,
        source_pdf=source_pdf,
        original_markdown_path=output_dir / "translation.md",
    )
    manifest.update(
        {
            "source": str(repaired_path),
            "output": str(final_pdf) if manifest.get("status") == "ok" else None,
            "manifest_path": str(final_manifest_path),
            "delivery_boundary": "QA 修复可读 PDF 只同步文本修复和 protected span 恢复清单，不替代主版式 PDF。",
        }
    )
    final_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
