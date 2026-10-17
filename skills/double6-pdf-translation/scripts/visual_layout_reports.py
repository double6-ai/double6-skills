# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout reports：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def build_dual_visual_report(
    source_pdf: Path | None,
    mono_translated_pdf: Path | None,
    standard_dual_pdf: Path | None,
    backend_dual_pdf: Path | None,
    output_dir: Path,
) -> dict[str, Any]:
    from visual_layout_core import normalize_finding, pdf_identity
    from visual_layout_extract import _load_fitz, _page_region_metrics
    from visual_layout_semantic import build_semantic_layout_report
    if not source_pdf or not mono_translated_pdf or not standard_dual_pdf or not source_pdf.exists() or not mono_translated_pdf.exists() or not standard_dual_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_source_mono_or_standard_dual_pdf", "findings": []}
    fitz = _load_fitz()
    identities = {'source_pdf_sha256': pdf_identity(source_pdf),
                  'candidate_pdf_sha256': pdf_identity(mono_translated_pdf),
                  'standard_dual_pdf_sha256': pdf_identity(standard_dual_pdf)}
    findings: list[dict[str, Any]] = []
    page_metrics: list[dict[str, Any]] = []

    def inspect_dual(path: Path, role: str, delivery_blocking: bool) -> None:
        with fitz.open(str(source_pdf)) as source_doc, fitz.open(str(mono_translated_pdf)) as mono_doc, fitz.open(str(path)) as dual_doc:  # type: ignore[attr-defined]
            for page_index in range(min(len(source_doc), len(mono_doc), len(dual_doc))):
                source_full = _page_region_metrics(source_doc, page_index, "full")
                mono_full = _page_region_metrics(mono_doc, page_index, "full")
                left = _page_region_metrics(dual_doc, page_index, "left")
                right = _page_region_metrics(dual_doc, page_index, "right")
                page_metrics.append(
                    {
                        "role": role,
                        "page": page_index + 1,
                        "source_full": source_full,
                        "mono_translated_full": mono_full,
                        "dual_left": left,
                        "dual_right": right,
                    }
                )
                source_nonempty = source_full["text_chars"] >= 30 or source_full["nonwhite_ratio"] >= 0.025
                translated_nonempty = mono_full["text_chars"] >= 20 or mono_full["cjk_count"] >= 8
                right_low = (
                    right["text_chars"] < max(20, int(mono_full["text_chars"] * 0.08))
                    and right["cjk_count"] < 8
                    and right["nonwhite_ratio"] < max(0.012, float(mono_full["nonwhite_ratio"]) * 0.25)
                )
                if source_nonempty and translated_nonempty and right_low:
                    findings.append(
                        normalize_finding(
                            {
                                "severity": "blocking" if delivery_blocking else "warn",
                                "category": "rendering",
                                "rule": "blank_or_low_content_page",
                                "page": page_index + 1,
                                "target_pdf_role": role,
                                "delivery_blocking": delivery_blocking,
                                "message": "双语 PDF 中文侧文本/CJK 覆盖极低，疑似中文侧空白。",
                                "evidence": json.dumps(
                                    {
                                        "mono_text_chars": mono_full["text_chars"],
                                        "mono_cjk_count": mono_full["cjk_count"],
                                        "right_text_chars": right["text_chars"],
                                        "right_cjk_count": right["cjk_count"],
                                        "right_nonwhite_ratio": right["nonwhite_ratio"],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    )
                left_delta = abs(float(left["nonwhite_ratio"]) - float(source_full["nonwhite_ratio"]))
                mean_delta = max(abs(float(left["mean_rgb"][idx]) - float(source_full["mean_rgb"][idx])) for idx in range(3))
                if source_nonempty and (left_delta >= 0.18 or mean_delta >= 55):
                    findings.append(
                        normalize_finding(
                            {
                                "severity": "blocking" if delivery_blocking else "warn",
                                "category": "rendering",
                                "rule": "dual_background_shift",
                                "page": page_index + 1,
                                "target_pdf_role": role,
                                "delivery_blocking": delivery_blocking,
                                "message": "双语 PDF 英文侧背景/像素分布与源页差异过大，可能出现背景漂移或侧栏异常。",
                                "evidence": json.dumps(
                                    {
                                        "source_nonwhite_ratio": source_full["nonwhite_ratio"],
                                        "left_nonwhite_ratio": left["nonwhite_ratio"],
                                        "source_mean_rgb": source_full["mean_rgb"],
                                        "left_mean_rgb": left["mean_rgb"],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    )

    try:
        inspect_dual(standard_dual_pdf, "standard_delivery", True)
        if backend_dual_pdf and backend_dual_pdf.exists() and backend_dual_pdf != standard_dual_pdf:
            inspect_dual(backend_dual_pdf, "backend_intermediate", False)
        semantic = build_semantic_layout_report(mono_translated_pdf, target_pdf_role="mono_translated_pdf")
        if semantic.get("findings"):
            findings.extend(semantic["findings"])
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"dual_visual_check_unavailable: {exc}", "findings": []}
    delivery_findings = [item for item in findings if item.get("delivery_blocking") and item.get("severity") == "blocking"]
    if identities != {'source_pdf_sha256': pdf_identity(source_pdf),
                      'candidate_pdf_sha256': pdf_identity(mono_translated_pdf),
                      'standard_dual_pdf_sha256': pdf_identity(standard_dual_pdf)}:
        return {'version': 1, 'status': 'unavailable', 'reason': 'input_changed_during_visual_check', 'findings': []}
    return {
        **identities,
        "version": 1,
        "status": "warn" if findings else "ok",
        "delivery_status": "blocking" if delivery_findings else "ok",
        "standard_dual_pdf": str(standard_dual_pdf),
        "backend_dual_pdf": str(backend_dual_pdf) if backend_dual_pdf else None,
        "page_metrics": page_metrics,
        "semantic_layout_report": semantic,
        "findings": findings,
    }


def build_paragraph_label_audit(translated_pdf: Path | None, output_dir: Path, pages: list[int] | None = None) -> dict[str, Any]:
    from visual_layout_core import overlap_pair_samples
    from visual_layout_density import is_allowed_compact_label, is_neutral_compact_label
    from visual_layout_extract import extract_pdf_pages
    if not translated_pdf or not translated_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_translated_pdf", "paragraphs": [], "overlap_pairs": []}
    preview_dir = output_dir / "visual_pages"
    try:
        extracted = extract_pdf_pages(translated_pdf, preview_dir, "audit_translated", max_pages=5, pages=pages)
    except Exception as exc:  # noqa: BLE001 - 审计产物不能让主流程在测试/降级 PDF 上失败
        return {
            "version": 1,
            "status": "unavailable",
            "reason": f"paragraph_label_audit_unavailable: {exc}",
            "translated_pdf": str(translated_pdf),
            "paragraphs": [],
            "overlap_pairs": [],
        }
    paragraphs: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    for page in extracted:
        page_number = page.get("page")
        for span in page.get("spans", []):
            if not isinstance(span, dict):
                continue
            text = str(span.get("text") or "")
            label = "ordinary_text"
            if is_allowed_compact_label(text) or is_neutral_compact_label(text):
                label = "allowed_compact_label"
            elif re.search(r"(?:\\[A-Za-z]+|[A-Za-z]+_[A-Za-z0-9_]+)", text):
                label = "code_like_span"
            elif 0 < float(span.get("size") or 0) < 6:
                label = "small_font_span"
            paragraphs.append(
                {
                    "page": page_number,
                    "bbox": span.get("bbox"),
                    "layout_label": label,
                    "xobj_id": None,
                    "debug_id": None,
                    "unicode_sample": text[:120],
                    "scale": None,
                    "participates_translation": label != "allowed_compact_label",
                    "participates_typesetting": True,
                    "source": "pymupdf_post_render",
                }
            )
        for pair in overlap_pair_samples(page):
            pair["page"] = page_number
            overlaps.append(pair)
    return {
        "version": 1,
        "status": "warn" if overlaps else "ok",
        "audit_source": "pymupdf_post_render",
        "translated_pdf": str(translated_pdf),
        "pages": pages or "auto",
        "paragraph_count": len(paragraphs),
        "overlap_pair_count": len(overlaps),
        "paragraphs": paragraphs[:1000],
        "overlap_pairs": overlaps[:200],
    }


def build_visual_layout_report(
    source_pdf: Path | None,
    translated_pdf: Path | None,
    output_dir: Path,
    *,
    max_pages: int = 3,
    pages: list[int] | None = None,
) -> dict[str, Any]:
    from visual_layout_core import normalize_finding, pdf_identity
    from visual_layout_density import analyze_visual_pages
    from visual_layout_extract import build_full_document_coverage_report, extract_pdf_full_text, extract_pdf_pages, infer_default_visual_check_pages, pdf_page_count, text_layer_health
    from visual_layout_semantic import build_semantic_layout_report
    if not source_pdf or not translated_pdf or not source_pdf.exists() or not translated_pdf.exists():
        return {
            "version": 1,
            "status": "unavailable",
            "reason": "missing_source_or_translated_pdf",
            "findings": [],
        }
    preview_dir = output_dir / "visual_pages"
    try:
        identities = {'source_pdf_sha256': pdf_identity(source_pdf),
                      'candidate_pdf_sha256': pdf_identity(translated_pdf)}
        effective_pages = pages or infer_default_visual_check_pages(source_pdf, max_pages=max_pages)
        source_pages = extract_pdf_pages(source_pdf, preview_dir, "source", max_pages=max_pages, pages=effective_pages)
        translated_pages = extract_pdf_pages(translated_pdf, preview_dir, "translated", max_pages=max_pages, pages=effective_pages)
        report = analyze_visual_pages(
            source_pages,
            translated_pages,
            full_translated_text=extract_pdf_full_text(translated_pdf),
        )
        source_page_count = pdf_page_count(source_pdf)
        translated_page_count = pdf_page_count(translated_pdf)
        if source_page_count is not None and translated_page_count is not None and source_page_count != translated_page_count:
            report["findings"].append(
                normalize_finding(
                    {
                        "severity": "blocking",
                        "category": "rendering",
                        "rule": "page_count_drift_full_pdf",
                        "page": "document",
                        "source_page_count": source_page_count,
                        "translated_page_count": translated_page_count,
                        "message": "源/译 PDF 总页数不一致，主版式交付存在页数漂移风险。",
                    }
                )
            )
            report["status"] = "warn"
        health = text_layer_health(translated_pages)
        if health["status"] != "ok":
            report["findings"].append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "rendering",
                        "rule": "text_layer_glyph_risk",
                        "page": "document",
                        "evidence": json.dumps(health, ensure_ascii=False),
                        "message": "译文 PDF 文本层存在可疑乱码或 ToUnicode 抽取风险。",
                    }
                )
            )
            report["status"] = "warn"
        coverage = build_full_document_coverage_report(source_pdf, translated_pdf)
        if coverage.get("findings"):
            report["findings"].extend(coverage["findings"])
            report["status"] = "warn"
        semantic = build_semantic_layout_report(translated_pdf, target_pdf_role="translated_pdf")
        if semantic.get("findings"):
            report["findings"].extend(semantic["findings"])
            report["status"] = "warn"
        report.update(
            {
                **identities,
                'generator_sha256': pdf_identity(Path(__file__)),
                "source_pdf": str(source_pdf),
                "translated_pdf": str(translated_pdf),
                "source_page_count": source_page_count,
                "translated_page_count": translated_page_count,
                "text_layer_health": health,
                "full_document_coverage": coverage,
                "semantic_layout_report": semantic,
                "visual_check_pages": effective_pages or "auto",
                "preview_dir": str(preview_dir),
                "source_pages": [{"page": item["page"], "preview_path": item["preview_path"]} for item in source_pages],
                "translated_pages": [{"page": item["page"], "preview_path": item["preview_path"]} for item in translated_pages],
            }
        )
        if identities != {'source_pdf_sha256': pdf_identity(source_pdf),
                          'candidate_pdf_sha256': pdf_identity(translated_pdf)}:
            return {'version': 1, 'status': 'unavailable', 'reason': 'input_changed_during_visual_check', 'findings': []}
        return report
    except Exception as exc:  # noqa: BLE001 - 视觉检查不能阻断翻译主路径
        return {
            "version": 1,
            "status": "unavailable",
            "reason": f"visual_check_unavailable: {exc}",
            "findings": [],
        }


def main() -> int:
    from visual_layout_structure import parse_page_selection
    import argparse

    parser = argparse.ArgumentParser(description="Build visual regression report for translated PDFs.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--pages", default="auto", help="Pages to inspect, e.g. 1,2,5,8-10. Default auto checks the first pages.")
    parser.add_argument("--standard-dual-pdf", help="Also refresh the standard bilingual report from these current PDFs.")
    args = parser.parse_args()
    report = build_visual_layout_report(
        Path(args.source_pdf),
        Path(args.translated_pdf),
        Path(args.output_dir),
        max_pages=args.max_pages,
        pages=parse_page_selection(args.pages),
    )
    output_path = Path(args.output_dir) / "visual_layout_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.standard_dual_pdf:
        dual = build_dual_visual_report(Path(args.source_pdf), Path(args.translated_pdf),
                                       Path(args.standard_dual_pdf), None, Path(args.output_dir))
        (Path(args.output_dir) / 'dual_visual_report.json').write_text(json.dumps(dual, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(str(output_path))
    return 0


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
