"""Typed contracts for route manifests, scan regions, and quality gates."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from .constants import (
    DOCUMENT_ROUTES,
    LATEX_STATUSES,
    PAGE_DECISIONS,
    REGION_STATUSES,
    RENDER_SOURCES,
    ROUTE_STATUSES,
    SCHEMA_VERSION,
    SKILL_VERSION,
)


class TextBBoxVsImage(TypedDict):
    text_area_ratio: float
    image_area_ratio: float
    text_inside_full_page_image_ratio: float
    hidden_text_layer_suspected: bool


class PageRouteRecord(TypedDict):
    page: int
    text_chars: int
    font_count: int
    span_count: int
    image_count: int
    full_page_image_coverage: float
    abnormal_char_rate: float
    text_bbox_vs_image: TextBBoxVsImage
    decision: Literal["digital", "scanned", "needs_review"]
    confidence: float
    reasons: list[str]


class LatexSourceRecord(TypedDict, total=False):
    status: Literal[
        "not_applicable",
        "not_found_unknown",
        "expected_but_missing",
        "ambiguous",
        "verified_match",
    ]
    source_path: str | None
    match_method: str | None
    policy: str
    candidate_count: int
    searched_roots: list[str]
    expected_key: str | None
    notes: list[str]


class RouteManifest(TypedDict, total=False):
    route_selection: Literal['auto', 'explicit_pdf_backend_only']
    complete_native_page_gate: bool
    schema_version: int
    skill_version: str
    generated_at: str
    status: str
    route_status: Literal["ready", "needs_review", "blocked", "error"]
    dispatch_allowed: bool
    input_pdf: str
    input_sha256: str
    document_route: Literal[
        "latex_direct",
        "pdf_backend",
        "scanned_raster",
        "mixed_requires_review",
        "mixed_cover_digital",
        "latex_identity_blocked",
    ]
    intended_render_source: str | None
    actual_render_source: str | None
    review_reasons: list[str]
    latex_source: LatexSourceRecord
    pages: list[PageRouteRecord]
    raster_candidate_pages: list[int]
    mixed_reason: str | None
    stop_reason: str | None
    experimental: bool
    notes: list[str]


class ScanRegionRecord(TypedDict, total=False):
    region_id: str
    page: int
    bbox: list[float]
    original_layout_bbox: list[float]
    source_geometry_expansion: dict[str, Any]
    reading_order: int
    ocr_text: str
    normalized_text: str
    source_page_idx: int
    polygon: list[list[float]]
    layout_role: str
    confidence: float | None
    confidence_source: str
    engine: str
    engine_version: str
    model: str | None
    tier: str | None
    source_pdf_sha256: str
    source_page_image_sha256: str
    config_sha256: str
    preprocess: dict[str, Any]
    translation_group_id: str
    status: Literal["translated", "protected", "skipped_with_reason", "failed"]
    translation: str | None
    skip_reason: str | None
    in_destroke_mask: bool
    mask_geometry: dict[str, Any]
    mask_overlap_ratio: float
    font_size: float | None
    overflow: bool
    occluded: bool
    overlap: bool
    source_formatting: dict[str, Any]
    text_alignment: Literal["left", "center", "right", "justify"]
    first_line_indent_pt: float
    first_line_indent_em: float
    lineheight: float


class QualityGateIssue(TypedDict, total=False):
    rule: str
    severity: Literal["blocking", "warn", "info"]
    region_id: str | None
    page: int | None
    evidence: str


class ScanQualityGate(TypedDict, total=False):
    schema_version: int
    status: Literal["ok", "partial", "blocking", "not_applicable"]
    searchable_text: Literal["cjk_ok", "raster_only", "unknown"]
    issues: list[QualityGateIssue]
    region_count: int
    experimental: bool


ROUTE_MANIFEST_SCHEMA: dict[str, Any] = {
    "$id": "paper-translation/scanned_raster/route_manifest.json",
    "type": "object",
    "required": [
        "schema_version",
        "skill_version",
        "generated_at",
        "status",
        "route_status",
        "dispatch_allowed",
        "input_pdf",
        "input_sha256",
        "document_route",
        "intended_render_source",
        "actual_render_source",
        "review_reasons",
        "latex_source",
        "pages",
        "raster_candidate_pages",
        "experimental",
    ],
    "properties": {
        'route_selection':{'enum':['auto','explicit_pdf_backend_only']},
        'complete_native_page_gate':{'type':'boolean'},
        "schema_version": {"type": "integer", "const": SCHEMA_VERSION},
        "skill_version": {"type": "string", "const": SKILL_VERSION},
        "route_status": {"enum": list(ROUTE_STATUSES)},
        "dispatch_allowed": {"type": "boolean"},
        "document_route": {"enum": list(DOCUMENT_ROUTES)},
        "intended_render_source": {"enum": [*RENDER_SOURCES, None]},
        "actual_render_source": {"enum": [*RENDER_SOURCES, None]},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "page",
                    "text_chars",
                    "font_count",
                    "span_count",
                    "full_page_image_coverage",
                    "abnormal_char_rate",
                    "text_bbox_vs_image",
                    "decision",
                    "confidence",
                ],
                "properties": {"decision": {"enum": list(PAGE_DECISIONS)}},
            },
        },
        "latex_source": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"enum": list(LATEX_STATUSES)}},
        },
    },
}

SCAN_REGION_SCHEMA: dict[str, Any] = {
    "$id": "paper-translation/scanned_raster/scan_region.json",
    "type": "object",
    "required": [
        "region_id",
        "page",
        "bbox",
        "reading_order",
        "source_page_idx",
        "polygon",
        "layout_role",
        "ocr_text",
        "normalized_text",
        "confidence",
        "confidence_source",
        "engine",
        "engine_version",
        "source_pdf_sha256",
        "source_page_image_sha256",
        "config_sha256",
        "preprocess",
        "translation_group_id",
        "status",
        "in_destroke_mask",
        "mask_geometry",
        "mask_overlap_ratio",
    ],
    "properties": {
        "status": {"enum": list(REGION_STATUSES)},
        "bbox": {"type": "array", "minItems": 4, "maxItems": 4},
        "polygon": {"type": "array", "minItems": 4},
        "confidence": {"type": ["number", "null"]},
    },
}

SCAN_QUALITY_GATE_SCHEMA: dict[str, Any] = {
    "$id": "paper-translation/scanned_raster/quality_gate.json",
    "type": "object",
    "required": ["schema_version", "status", "searchable_text", "issues"],
    "properties": {
        "status": {"enum": ["ok", "partial", "blocking", "not_applicable"]},
        "searchable_text": {"enum": ["cjk_ok", "raster_only", "unknown"]},
    },
}


def _require(payload: dict[str, Any], keys: list[str], prefix: str) -> list[str]:
    errors: list[str] = []
    for key in keys:
        if key not in payload:
            errors.append(f"{prefix}missing {key}")
    return errors


def validate_route_manifest(payload: dict[str, Any]) -> list[str]:
    errors = _require(
        payload,
        [
            "schema_version",
            "skill_version",
            "generated_at",
            "status",
            "route_status",
            "dispatch_allowed",
            "input_pdf",
            "input_sha256",
            "document_route",
            "intended_render_source",
            "actual_render_source",
            "review_reasons",
            "latex_source",
            "pages",
            "raster_candidate_pages",
            "experimental",
        ],
        "route_manifest: ",
    )
    if payload.get("document_route") not in DOCUMENT_ROUTES:
        errors.append(f"route_manifest: unknown document_route {payload.get('document_route')!r}")
    if payload.get('route_selection','auto') not in {'auto','explicit_pdf_backend_only'}:
        errors.append('route_manifest: unknown route_selection')
    if 'complete_native_page_gate' in payload and not isinstance(payload['complete_native_page_gate'],bool):
        errors.append('route_manifest: complete_native_page_gate must be boolean')
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"route_manifest: schema_version must be {SCHEMA_VERSION}")
    if payload.get("skill_version") != SKILL_VERSION:
        errors.append(f"route_manifest: skill_version must be {SKILL_VERSION}")
    if payload.get("route_status") not in ROUTE_STATUSES:
        errors.append("route_manifest: route_status is invalid")
    if not isinstance(payload.get("dispatch_allowed"), bool):
        errors.append("route_manifest: dispatch_allowed must be boolean")
    if payload.get("actual_render_source") is not None:
        errors.append("route_manifest: routing cannot claim an actual render source")
    if not isinstance(payload.get("review_reasons"), list):
        errors.append("route_manifest: review_reasons must be a list")
    latex = payload.get("latex_source")
    if not isinstance(latex, dict) or latex.get("status") not in LATEX_STATUSES:
        errors.append("route_manifest: latex_source.status is invalid")
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("route_manifest: pages must be a non-empty list")
        return errors
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            errors.append(f"route_manifest.pages[{index}]: not an object")
            continue
        errors.extend(
            _require(
                page,
                [
                    "page",
                    "text_chars",
                    "font_count",
                    "span_count",
                    "full_page_image_coverage",
                    "abnormal_char_rate",
                    "text_bbox_vs_image",
                    "decision",
                    "confidence",
                ],
                f"route_manifest.pages[{index}]: ",
            )
        )
        if page.get("decision") not in PAGE_DECISIONS:
            errors.append(f"route_manifest.pages[{index}]: unknown decision")
    return errors


def validate_scan_region(payload: dict[str, Any]) -> list[str]:
    errors = _require(
        payload,
        [
            "region_id",
            "page",
            "bbox",
            "reading_order",
            "source_page_idx",
            "polygon",
            "layout_role",
            "ocr_text",
            "normalized_text",
            "confidence",
            "confidence_source",
            "engine",
            "engine_version",
            "source_pdf_sha256",
            "source_page_image_sha256",
            "config_sha256",
            "preprocess",
            "translation_group_id",
            "status",
            "in_destroke_mask",
            "mask_geometry",
            "mask_overlap_ratio",
        ],
        "scan_region: ",
    )
    if payload.get("status") not in REGION_STATUSES:
        errors.append(f"scan_region: unknown status {payload.get('status')!r}")
    bbox = payload.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        errors.append("scan_region: bbox must have 4 numbers")
    polygon = payload.get("polygon")
    if not isinstance(polygon, list) or len(polygon) < 4:
        errors.append("scan_region: polygon must have at least 4 points")
    confidence = payload.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        errors.append("scan_region: confidence must be numeric or null")
    return errors


def validate_quality_gate(payload: dict[str, Any]) -> list[str]:
    errors = _require(payload, ["schema_version", "status", "searchable_text", "issues"], "quality_gate: ")
    if payload.get("status") not in {"ok", "partial", "blocking", "not_applicable"}:
        errors.append(f"quality_gate: unknown status {payload.get('status')!r}")
    if not isinstance(payload.get("issues"), list):
        errors.append("quality_gate: issues must be a list")
    return errors
