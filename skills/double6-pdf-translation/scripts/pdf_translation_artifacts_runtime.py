#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py for source preparation, PDF artifact selection, layout maps, and QA artifact writing."

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import build_babeldoc_il_layout_map
import build_bilingual_pdf
import build_pdf_rerender_plan
import build_structured_visual_candidates
import check_translation
import extract_terms
import prepare_paper_source
import render_readable_pdf
import repair_quality_issues
import policy_utils

from latex_direct_runtime import (
    extract_pdf_text,
)

























def prepare_source(input_pdf: Path, output_dir: Path, source_override: Path | None = None) -> dict[str, Any]:
    source_input = source_override if source_override is not None else input_pdf
    return prepare_paper_source.prepare_source(
        SimpleNamespace(
            input=str(source_input),
            output_dir=str(output_dir),
            text=None,
            stdin=False,
            no_ocr=False,
            keep_pdf_noise=False,
        )
    )


def write_glossary(output_dir: Path, manifest: dict[str, Any]) -> Path:
    source_path = output_dir / "source.md"
    glossary_path = output_dir / "glossary.tsv"
    rows = extract_terms.extract_candidate_terms(
        source_path.read_text(encoding="utf-8", errors="replace"),
        blocks=manifest.get("blocks") if isinstance(manifest.get("blocks"), list) else [],
    )
    extract_terms.write_glossary(rows, glossary_path)
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
    if input_pdf.exists():
        return input_pdf

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    candidate_roots = [
        input_pdf.parent,
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
    layout: str,
    backend_dual_pdf: str | None,
    mono_changed: bool,
    render_mode: str = "vector",
    raster_dpi: int = 144,
) -> dict[str, Any]:
    manifest_path = output_dir / "bilingual_pdf_manifest.json"
    normalized_layout = layout.replace("-", "_") if layout != "off" else None
    backend_dual = Path(backend_dual_pdf) if backend_dual_pdf else None
    backend_available = bool(backend_dual and backend_dual.is_file())
    if layout == "off":
        selected_outputs["dual_pdf"] = None
        selected_outputs["standard_bilingual_pdf"] = None
        manifest = {
            "version": 1,
            "status": "skipped",
            "reason": "dual_output_disabled",
            "layout": None,
            "source": None,
            "content_sync": None,
            "layout_verification": None,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    if layout == "backend-default":
        manifest = {
            "version": 1,
            "status": "ok" if backend_available and not mono_changed else ("partial" if backend_available else "error"),
            "reason": None if backend_available else "backend_dual_pdf_missing",
            "layout": "backend_default",
            "source": "backend_native" if backend_available else None,
            "content_sync": "final_mono" if backend_available and not mono_changed else ("backend_snapshot" if backend_available else "unknown"),
            "layout_verification": "backend_contract" if backend_available else "unavailable",
            "output_pdf": str(backend_dual) if backend_available else None,
        }
        selected_outputs["dual_pdf"] = str(backend_dual) if backend_available else None
        selected_outputs["standard_bilingual_pdf"] = None
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    if layout == "zh-left-en-right" and backend_available and not mono_changed:
        selected_outputs["dual_pdf"] = str(backend_dual)
        selected_outputs["standard_bilingual_pdf"] = None
        manifest = {
            "version": 1,
            "status": "ok",
            "layout": "zh_left_en_right",
            "source": "backend_native",
            "content_sync": "final_mono",
            "layout_verification": "backend_contract",
            "output_pdf": str(backend_dual),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    translated_pdf_value = selected_outputs.get("mono_pdf") or selected_outputs.get("translated_pdf")
    if not translated_pdf_value:
        manifest = {
            "version": 1,
            "status": "error",
            "reason": "missing_mono_translated_pdf",
            "layout": normalized_layout,
            "source": None,
            "content_sync": "unknown",
            "layout_verification": "unavailable",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    translated_pdf = Path(translated_pdf_value)
    if not translated_pdf.exists():
        manifest = {
            "version": 1,
            "status": "error",
            "reason": "translated_pdf_not_found",
            "layout": normalized_layout,
            "source": None,
            "content_sync": "unknown",
            "layout_verification": "unavailable",
            "translated_pdf": str(translated_pdf),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {**manifest, "manifest_path": str(manifest_path)}
    source_pdf = resolve_bilingual_source_pdf(input_pdf)
    output_pdf = output_dir / f"{input_pdf.stem}.{layout}.dual.pdf"
    manifest = build_bilingual_pdf.build_manifest(
        source_pdf,
        translated_pdf,
        output_pdf,
        layout=layout,
        mode=render_mode,
        raster_dpi=raster_dpi,
    )
    if manifest.get("status") != "ok" and layout == "zh-left-en-right" and backend_available:
        manifest = {
            **manifest,
            "status": "partial",
            "reason": "pymupdf_rebuild_unavailable_backend_snapshot_used",
            "source": "backend_native",
            "content_sync": "backend_snapshot",
            "layout_verification": "backend_contract",
            "output_pdf": str(backend_dual),
        }
    if source_pdf != input_pdf:
        manifest["requested_source_pdf"] = str(input_pdf)
        manifest["resolved_source_pdf"] = str(source_pdf)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if manifest.get("status") in {"ok", "partial"} and manifest.get("output_pdf"):
        selected_outputs["dual_pdf"] = str(manifest["output_pdf"])
        selected_outputs["standard_bilingual_pdf"] = str(manifest["output_pdf"]) if manifest.get("source") == "pymupdf_rebuilt" else None
    return {**manifest, "manifest_path": str(manifest_path)}


def _copy_pdf_for_delivery(source: Path, target: Path) -> str | None:
    if not source.is_file():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return str(target)


def finalize_delivery_pdf_outputs(
    input_pdf: Path,
    output_dir: Path,
    selected_outputs: dict[str, str | None],
    candidate_pdfs: list[str] | None = None,
    bilingual_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mono_source = Path(str(selected_outputs.get("mono_pdf") or selected_outputs.get("translated_pdf") or ""))
    bilingual_source = Path(
        str(
            selected_outputs.get("standard_bilingual_pdf")
            or selected_outputs.get("dual_pdf")
            or ""
        )
    )
    mono_target = output_dir / f"{input_pdf.stem}.zh.pdf"
    bilingual_target = output_dir / f"{input_pdf.stem}.bilingual.pdf"
    delivery: dict[str, str | None] = {
        "mono_pdf": _copy_pdf_for_delivery(mono_source, mono_target),
        "bilingual_pdf": _copy_pdf_for_delivery(bilingual_source, bilingual_target),
    }
    kept = {Path(path).resolve() for path in delivery.values() if path}
    input_resolved = input_pdf.resolve() if input_pdf.exists() else None
    removed: list[str] = []
    preserved: list[str] = []
    cleanup_candidates = {Path(path).expanduser() for path in candidate_pdfs or [] if path}
    cleanup_candidates.update(Path(str(value)) for value in selected_outputs.values() if value and str(value).endswith(".pdf"))
    for pdf in sorted(cleanup_candidates):
        if not pdf.is_absolute():
            pdf = output_dir / pdf
        if not pdf.is_file():
            continue
        try:
            resolved = pdf.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(output_dir.resolve())
        except ValueError:
            preserved.append(str(pdf))
            continue
        if resolved in kept:
            continue
        if input_resolved and resolved == input_resolved:
            preserved.append(str(pdf))
            continue
        try:
            pdf.unlink()
            removed.append(str(pdf))
        except OSError as exc:
            preserved.append(f"{pdf} ({exc})")
    standard_bilingual = (
        delivery["bilingual_pdf"]
        if isinstance(bilingual_manifest, dict) and bilingual_manifest.get("source") == "pymupdf_rebuilt"
        else None
    )
    selected_outputs.update(
        {
            "translated_pdf": delivery["mono_pdf"],
            "mono_pdf": delivery["mono_pdf"],
            "dual_pdf": delivery["bilingual_pdf"],
            "standard_bilingual_pdf": standard_bilingual,
            "backend_dual_pdf": None,
            "backend_dual_pdf_role": None,
        }
    )
    bilingual_status = str((bilingual_manifest or {}).get("status") or "")
    bilingual_disabled = (
        bilingual_status == "skipped"
        and (bilingual_manifest or {}).get("reason") == "dual_output_disabled"
    )
    delivery_ok = bool(delivery["mono_pdf"]) and (
        bilingual_disabled
        or bool(delivery["bilingual_pdf"]) and bilingual_status != "partial"
    )
    return {
        "version": 1,
        "status": "ok" if delivery_ok else "partial",
        "contract": "current-run PDF artifacts are collapsed to the Chinese monolingual PDF and bilingual PDF; unrelated pre-existing PDFs are preserved.",
        "outputs": delivery,
        "bilingual": dict(bilingual_manifest or {}),
        "removed_pdf_count": len(removed),
        "removed_pdfs": removed,
        "preserved_pdfs": preserved,
    }


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
    structured_output_pdf = output_dir / f"{input_pdf.stem}.structured-candidates.zh.mono.pdf"
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
        "reason": "document_specific_visual_repairs_disabled_by_default",
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
    target = latex_pdf.with_name(f"{latex_pdf.stem}.en-left.zh-right.dual.pdf")
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
                            "executor_provider": "pdfmathtranslate-next",
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
                        "executor_provider": "pdfmathtranslate-next",
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
    latex_manifest = policy_utils.load_json(output_dir / "direct_latex_render_manifest.json")
    translated_tex = Path(str(latex_manifest.get("translated_tex") or ""))
    if translated_tex.is_file():
        translation += "\n" + translated_tex.read_text(encoding="utf-8", errors="replace")
    glossary = check_translation.load_glossary(glossary_path)
    manifest = check_translation.load_json(manifest_path)
    protected_spans = check_translation.load_json(protected_spans_path)
    translation_blocks = check_translation.load_translation_blocks(translation_blocks_path)
    manifest["coverage_gate"] = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else check_translation.build_coverage_gate(manifest, translation)
    term_policy = check_translation.build_term_policy(glossary, manifest=manifest, source=source)
    entity_map = check_translation.build_entity_map(manifest, glossary)
    issues = check_translation.collect_issues(
        source,
        translation,
        glossary,
        manifest=manifest,
        protected_spans=protected_spans,
        translation_blocks=translation_blocks,
        render_manifest=render_manifest,
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
        repair_quality_issues.DEFAULT_RESIDUE_TRANSLATIONS,
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


def render_qa_repaired_pdf(output_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    mode = str(getattr(args, "post_qa_repair", "auto") or "auto")
    repaired_path = output_dir / "translation.qa_repaired.md"
    final_pdf = output_dir / "final_readable.pdf"
    final_manifest_path = output_dir / "final_pdf_manifest.json"
    if mode == "off":
        return {"status": "skipped", "reason": "post_qa_repair_off"}
    if not repaired_path.exists():
        return {"status": "skipped", "reason": "missing_translation_qa_repaired"}
    try:
        manifest = render_readable_pdf.render_pdf(repaired_path, final_pdf, title=output_dir.name)
    except ModuleNotFoundError as exc:
        return {
            "status": "skipped",
            "reason": "missing_optional_render_dependency",
            "error": str(exc),
            "source": str(repaired_path),
            "output": str(final_pdf),
            "delivery_boundary": "QA 修复可读 PDF 是附加审校产物；缺少可读 PDF 渲染依赖不替代主版式 PDF gate。",
        }
    manifest.update(
        {
            "source": str(repaired_path),
            "output": str(final_pdf),
            "manifest_path": str(final_manifest_path),
            "delivery_boundary": "QA 修复可读 PDF 只同步文本修复和 protected span 恢复清单，不替代主版式 PDF。",
        }
    )
    final_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest









def maybe_run_cloud_layout(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    token_present = bool(os.environ.get("MINERU_TOKEN", "").strip())
    if not args.allow_cloud_layout:
        return {
            "status": "skipped",
            "reason": "cloud_layout_requires_explicit_allow",
            "token_present": token_present,
        }
    if not token_present:
        return {
            "status": "skipped",
            "reason": "missing_mineru_token",
            "token_present": False,
        }
    marker = output_dir / "mineru_layout_request.json"
    marker.write_text(
        json.dumps(
            {
                "status": "not_run",
                "reason": "MinerU cloud layout is gated; adapter integration point is explicit and token is not logged.",
                "input_pdf": str(args.input_pdf),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "status": "not_run",
        "reason": "adapter_placeholder",
        "token_present": True,
        "request_manifest": str(marker),
    }


def fallback_to_text_path(output_dir: Path, manifest: dict[str, Any]) -> None:
    write_glossary(output_dir, manifest)
    translation_path = output_dir / "translation.md"
    if not translation_path.exists():
        translation_path.write_text("", encoding="utf-8")
    blocks_path = output_dir / "translation_blocks.jsonl"
    if not blocks_path.exists():
        blocks_path.write_text("", encoding="utf-8")
    render_manifest = json.loads((output_dir / "render_manifest.json").read_text(encoding="utf-8"))
    render_manifest["fallback"] = "text_extraction_path"
    (output_dir / "render_manifest.json").write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run_quality_check(output_dir, render_manifest)
