"""Lightweight per-page PDF routing. No OCR writeback, no hy-mt, no PDF backend."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import (
    DOCUMENT_ROUTE_LATEX_BLOCKED,
    DOCUMENT_ROUTE_LATEX_DIRECT,
    DOCUMENT_ROUTE_MIXED_REVIEW,
    DOCUMENT_ROUTE_MIXED_COVER,
    DOCUMENT_ROUTE_PDF_BACKEND,
    DOCUMENT_ROUTE_SCANNED_RASTER,
    HIDDEN_OCR_IMAGE_COVERAGE,
    LATEX_STATUS_AMBIGUOUS,
    LATEX_STATUS_EXPECTED_BUT_MISSING,
    LATEX_STATUS_VERIFIED_MATCH,
    MAX_ABNORMAL_CHAR_RATE,
    MIN_DIGITAL_SPAN_COUNT,
    MIN_DIGITAL_TEXT_CHARS,
    PAGE_DECISION_DIGITAL,
    PAGE_DECISION_NEEDS_REVIEW,
    PAGE_DECISION_SCANNED,
    SCANNED_IMAGE_COVERAGE,
    SCANNED_TEXT_CHAR_CEILING,
    SCHEMA_VERSION,
    SKILL_VERSION,
    ROUTE_STATUS_BLOCKED,
    ROUTE_STATUS_ERROR,
    ROUTE_STATUS_NEEDS_REVIEW,
    ROUTE_STATUS_READY,
)
from .latex_identity import resolve_latex_identity, extract_pdf_identity
from .schema import validate_route_manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _area(bbox: tuple[float, float, float, float] | list[float]) -> float:
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))


def _intersection_area(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Return exact axis-aligned union area without double-counting overlaps."""
    normalized = [
        (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        for x0, y0, x1, y1 in boxes
        if x0 != x1 and y0 != y1
    ]
    if not normalized:
        return 0.0
    xs = sorted({value for box in normalized for value in (box[0], box[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (y0, y1) for x0, y0, x1, y1 in normalized if x0 < right and x1 > left
        )
        covered = 0.0
        start: float | None = None
        end: float | None = None
        for y0, y1 in intervals:
            if start is None:
                start, end = y0, y1
            elif y0 <= float(end):
                end = max(float(end), y1)
            else:
                covered += float(end) - start
                start, end = y0, y1
        if start is not None and end is not None:
            covered += end - start
        total += (right - left) * covered
    return total


def _is_abnormal_char(char: str) -> bool:
    code = ord(char)
    if char == "\ufffd":
        return True
    if 0xE000 <= code <= 0xF8FF:
        return True
    if 0xF0000 <= code <= 0xFFFFD:
        return True
    return False


def inspect_page(page: Any) -> dict[str, Any]:
    page_rect = page.rect
    page_area = float(page_rect.width * page_rect.height) or 1.0
    text = page.get_text("text") or ""
    extracted_text_chars = len(text.strip())
    visible_text=[];hidden_text=[];visibility_trace_available=True
    try:
        for span in page.get_texttrace():
            chars=''.join(chr(c[0]) for c in span['chars'])
            if span['type']==3 or span.get('opacity',1)<=0:hidden_text.append(chars)
            else:visible_text.append(chars)
    except (AttributeError,RuntimeError,ValueError,KeyError,TypeError):
        visibility_trace_available=False
    painted_text=''.join(visible_text)
    hidden_text_chars=len(''.join(hidden_text).strip())
    text_chars=len(painted_text.strip()) if visibility_trace_available else extracted_text_chars
    payload = page.get_text("dict") or {}
    span_count = 0
    fonts: set[str] = set()
    text_area = 0.0
    text_inside_image = 0.0
    image_boxes: list[tuple[float, float, float, float]] = []
    for info in page.get_image_info() or []:
        bbox = info.get("bbox")
        if not bbox:
            continue
        box = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        image_boxes.append(box)
    image_area = _union_area(image_boxes)
    full_page_image_coverage = min(1.0, image_area / page_area)
    for block in payload.get("blocks") or []:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                span_count += 1
                font = span.get("font")
                if font:
                    fonts.add(str(font))
                bbox = span.get("bbox") or (0, 0, 0, 0)
                span_box = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                span_area = _area(span_box)
                text_area += span_area
                if image_boxes:
                    overlap = max(_intersection_area(span_box, image_box) for image_box in image_boxes)
                    text_inside_image += overlap
    images = page.get_images(full=True) or []
    abnormal = sum(1 for char in painted_text if _is_abnormal_char(char))
    abnormal_char_rate = (abnormal / len(painted_text)) if painted_text else 0.0
    text_inside_ratio = (text_inside_image / text_area) if text_area else 0.0
    strong_native_text = (
        text_chars >= MIN_DIGITAL_TEXT_CHARS
        and span_count >= MIN_DIGITAL_SPAN_COUNT
        and abnormal_char_rate <= MAX_ABNORMAL_CHAR_RATE
    )
    hidden = (
        full_page_image_coverage >= HIDDEN_OCR_IMAGE_COVERAGE
        and extracted_text_chars > 0
        and not strong_native_text
        and (len(fonts) <= 1 or text_inside_ratio >= 0.85)
    )
    text_bbox_vs_image = {
        "text_area_ratio": round(min(1.0, text_area / page_area), 4),
        "image_area_ratio": round(full_page_image_coverage, 4),
        "text_inside_full_page_image_ratio": round(min(1.0, text_inside_ratio), 4),
        "hidden_text_layer_suspected": hidden,
    }
    reasons: list[str] = []
    decision = PAGE_DECISION_NEEDS_REVIEW
    confidence = 0.45
    if not visibility_trace_available:
        reasons.append("printable_text_trace_unverified")
    elif hidden:
        decision = PAGE_DECISION_SCANNED
        confidence = 0.86
        reasons.append("full_page_image_with_hidden_or_dumped_text_layer")
    elif text_chars <= SCANNED_TEXT_CHAR_CEILING and (
        full_page_image_coverage >= SCANNED_IMAGE_COVERAGE or (len(images) >= 1 and span_count == 0)
    ):
        decision = PAGE_DECISION_SCANNED
        confidence = 0.94 if text_chars == 0 else 0.8
        reasons.append("low_text_high_image_coverage")
    elif (
        strong_native_text
        and full_page_image_coverage < 0.85
    ):
        decision = PAGE_DECISION_DIGITAL
        confidence = 0.9
        reasons.append("native_text_layer")
    elif strong_native_text:
        decision = PAGE_DECISION_DIGITAL
        confidence = 0.82
        reasons.append("native_text_layer_over_full_page_background")
    elif text_chars >= MIN_DIGITAL_TEXT_CHARS and full_page_image_coverage < 0.35:
        decision = PAGE_DECISION_DIGITAL
        confidence = 0.75
        reasons.append("text_layer_without_full_page_scan")
    else:
        reasons.append("mixed_or_weak_signals")
        if text_chars <= SCANNED_TEXT_CHAR_CEILING:
            decision = PAGE_DECISION_SCANNED
            confidence = 0.6
            reasons.append("near_empty_text_layer")
    return {
        "page": int(page.number) + 1,
        "text_chars": text_chars,
        "extracted_text_chars": extracted_text_chars,
        "hidden_text_chars": hidden_text_chars,
        "printable_trace_available": visibility_trace_available,
        "visibility_scope": "绘制模式与opacity；clip/遮挡和白字像素仍需源视觉复核",
        "font_count": len(fonts),
        "span_count": span_count,
        "image_count": len(images),
        "full_page_image_coverage": round(full_page_image_coverage, 4),
        "abnormal_char_rate": round(abnormal_char_rate, 4),
        "text_bbox_vs_image": text_bbox_vs_image,
        "decision": decision,
        "confidence": confidence,
        "reasons": reasons,
    }


def inspect_pdf_pages(input_pdf: Path) -> list[dict[str, Any]]:
    import fitz

    document = fitz.open(input_pdf)
    try:
        return [inspect_page(page) for page in document]
    finally:
        document.close()


def aggregate_document_route(
    pages: list[dict[str, Any]],
    latex_source: dict[str, Any],
    *, mixed_cover_mode: str = "off", mixed_max_pages: int = 5,
) -> dict[str, Any]:
    latex_status = latex_source.get("status")
    if latex_status == LATEX_STATUS_VERIFIED_MATCH:
        return {
            "document_route": DOCUMENT_ROUTE_LATEX_DIRECT,
            "route_status": ROUTE_STATUS_READY,
            "dispatch_allowed": True,
            "intended_render_source": DOCUMENT_ROUTE_LATEX_DIRECT,
            "review_reasons": [],
            "mixed_reason": None,
            "stop_reason": None,
        }
    if latex_status in {LATEX_STATUS_AMBIGUOUS, LATEX_STATUS_EXPECTED_BUT_MISSING}:
        reason = (
            "latex_source_ambiguous"
            if latex_status == LATEX_STATUS_AMBIGUOUS
            else "latex_source_expected_but_missing"
        )
        return {
            "document_route": DOCUMENT_ROUTE_LATEX_BLOCKED,
            "route_status": ROUTE_STATUS_BLOCKED,
            "dispatch_allowed": False,
            "intended_render_source": None,
            "review_reasons": [reason],
            "mixed_reason": None,
            "stop_reason": reason,
        }

    if mixed_cover_mode == "translate":
        from .mixed_cover import cover_plan
        plan = cover_plan(pages, max_pages=mixed_max_pages)
        if plan:
            return {"document_route": DOCUMENT_ROUTE_MIXED_COVER, "route_status": ROUTE_STATUS_READY,
                    "dispatch_allowed": True, "intended_render_source": DOCUMENT_ROUTE_MIXED_COVER,
                    "review_reasons": [], "mixed_reason": "explicit_image_cover_policy",
                    "stop_reason": None, "raster_candidate_pages": [1], "mixed_cover_plan": plan}

    decisions = {str(page.get("decision")) for page in pages}
    raster_pages = [
        int(page["page"])
        for page in pages
        if page.get("decision") == PAGE_DECISION_SCANNED
    ]
    review_pages = [int(page["page"]) for page in pages if page.get("decision") == PAGE_DECISION_NEEDS_REVIEW]
    if review_pages:
        reason = "page_route_needs_review:" + ",".join(str(page) for page in review_pages)
        return {
            "document_route": DOCUMENT_ROUTE_MIXED_REVIEW,
            "route_status": ROUTE_STATUS_NEEDS_REVIEW,
            "dispatch_allowed": False,
            "intended_render_source": None,
            "review_reasons": [reason],
            "mixed_reason": "page_route_needs_review",
            "stop_reason": "page_route_needs_review",
            "raster_candidate_pages": raster_pages,
        }
    has_scanned = PAGE_DECISION_SCANNED in decisions
    has_digital = PAGE_DECISION_DIGITAL in decisions
    if has_scanned and has_digital:
        return {
            "document_route": DOCUMENT_ROUTE_MIXED_REVIEW,
            "route_status": ROUTE_STATUS_NEEDS_REVIEW,
            "dispatch_allowed": False,
            "intended_render_source": None,
            "review_reasons": ["scanned_and_digital_pages_coexist"],
            "mixed_reason": "scanned_and_digital_pages_coexist",
            "stop_reason": "mixed_requires_review",
            "raster_candidate_pages": raster_pages,
        }
    if has_scanned and not has_digital:
        return {
            "document_route": DOCUMENT_ROUTE_SCANNED_RASTER,
            "route_status": ROUTE_STATUS_READY,
            "dispatch_allowed": True,
            "intended_render_source": DOCUMENT_ROUTE_SCANNED_RASTER,
            "review_reasons": [],
            "mixed_reason": None,
            "stop_reason": None,
            "raster_candidate_pages": raster_pages or [int(page["page"]) for page in pages],
        }
    return {
        "document_route": DOCUMENT_ROUTE_PDF_BACKEND,
        "route_status": ROUTE_STATUS_READY,
        "dispatch_allowed": True,
        "intended_render_source": DOCUMENT_ROUTE_PDF_BACKEND,
        "review_reasons": [],
        "mixed_reason": None,
        "stop_reason": None,
        "raster_candidate_pages": [],
    }


def route_pdf(
    input_pdf: Path,
    *,
    args: argparse.Namespace | None = None,
    explicit_override: Path | None = None,
    adjacent_candidate: Path | None = None,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    pdf_path = Path(input_pdf).expanduser().resolve()
    pdf_only=bool(getattr(args,'pdf_backend_only',False))
    override = explicit_override
    if override is None and args is not None:
        raw = getattr(args, "source_override", None)
        if raw:
            override = Path(str(raw)).expanduser().resolve()
    if pdf_only:
        if override is not None:raise ValueError('explicit PDF-only route cannot consume TeX override')
        identity=extract_pdf_identity(pdf_path)
        key=('arxiv:'+identity['arxiv_id']) if identity['arxiv_id'] else ('doi:'+identity['doi'] if identity['doi'] else None)
        latex_source={'policy':'explicit_pdf_backend_only','status':'not_found_unknown','source_path':None,
                      'match_method':None,'candidate_count':0,'searched_roots':[],'expected_key':key,
                      'discovery_skipped':True,'pdf_identity_expected_latex':identity['expected_latex'],
                      'notes':['显式电子PDF路线跳过TeX发现；arXiv/DOI身份保留，所有实际源页必须通过native digital分类。']}
    else:
        latex_source = resolve_latex_identity(
            pdf_path, explicit_override=override, adjacent_candidate=adjacent_candidate, cache_root=cache_root)
    try:
        pages = inspect_pdf_pages(pdf_path)
        status = "ok"
        notes = list(latex_source.get("notes") or [])
    except Exception as exc:  # noqa: BLE001
        pages = []
        status = "error"
        notes = [*list(latex_source.get("notes") or []), f"page_inspect_failed: {exc}"]
        latex_source = dict(latex_source)
        latex_source["notes"] = notes

    aggregated = aggregate_document_route(pages, latex_source,
        mixed_cover_mode=getattr(args, "mixed_cover_mode", "off"),
        mixed_max_pages=getattr(args, "mixed_max_pages", 5)) if pages else {
        "document_route": DOCUMENT_ROUTE_MIXED_REVIEW,
        "route_status": ROUTE_STATUS_ERROR,
        "dispatch_allowed": False,
        "intended_render_source": None,
        "review_reasons": ["page_inspect_failed"],
        "mixed_reason": None,
        "stop_reason": "page_inspect_failed",
        "raster_candidate_pages": [],
    }
    if pdf_only and (not pages or any(page['decision']!=PAGE_DECISION_DIGITAL for page in pages)):
        aggregated.update(document_route=DOCUMENT_ROUTE_MIXED_REVIEW,route_status=ROUTE_STATUS_BLOCKED,
                          dispatch_allowed=False,intended_render_source=None,
                          review_reasons=['explicit_pdf_only_requires_all_native_digital_pages'],
                          stop_reason='explicit_pdf_only_requires_all_native_digital_pages')
    raster_pages = aggregated.get("raster_candidate_pages")
    if raster_pages is None:
        raster_pages = [
            int(page["page"]) for page in pages if page.get("decision") == PAGE_DECISION_SCANNED
        ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "route_status": aggregated["route_status"],
        "dispatch_allowed": bool(aggregated["dispatch_allowed"]),
        "input_pdf": str(pdf_path),
        "input_sha256": _sha256_file(pdf_path),
        "document_route": aggregated["document_route"],
        "intended_render_source": aggregated.get("intended_render_source"),
        "actual_render_source": None,
        "review_reasons": list(aggregated.get("review_reasons") or []),
        "latex_source": latex_source,
        "pages": pages,
        "raster_candidate_pages": raster_pages,
        "mixed_reason": aggregated.get("mixed_reason"),
        "stop_reason": aggregated.get("stop_reason"),
        "mixed_cover_plan": aggregated.get("mixed_cover_plan"),
        "experimental": True,
        "notes": notes + [
            "experimental scanned route / scan smoke; not production scan translation",
            "route-only does not call PDF backend, OCR writeback, or hy-mt",
        ],
        'route_selection':'explicit_pdf_backend_only' if pdf_only else 'auto',
        'complete_native_page_gate':all(p['decision']==PAGE_DECISION_DIGITAL for p in pages) if pages else False,
    }
    schema_errors = validate_route_manifest(manifest)
    if schema_errors:
        manifest["status"] = "error"
        manifest["route_status"] = ROUTE_STATUS_ERROR
        manifest["dispatch_allowed"] = False
        manifest["actual_render_source"] = None
        manifest["schema_errors"] = schema_errors
        manifest["stop_reason"] = manifest.get("stop_reason") or "route_manifest_schema"
    return manifest


def write_route_manifest(output_dir: Path, manifest: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "route_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_route_only_result(
    input_pdf: Path,
    output_dir: Path,
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    manifest = route_pdf(input_pdf, args=args)
    path = write_route_manifest(output_dir, manifest)
    result = {
        "status": "route_only",
        "route_manifest": str(path),
        "document_route": manifest.get("document_route"),
        "route_status": manifest.get("route_status"),
        "dispatch_allowed": manifest.get("dispatch_allowed"),
        "intended_render_source": manifest.get("intended_render_source"),
        "actual_render_source": None,
        "experimental": True,
        "backend_invoked": False,
        "ocr_writeback": False,
        "hymt_invoked": False,
        "route": manifest,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write route_manifest.json only.")
    parser.add_argument("input_pdf")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-override")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = write_route_only_result(Path(args.input_pdf), Path(args.output_dir), args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("route", {}).get("status") != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
