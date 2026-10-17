"""Blocking quality gates for the experimental scanned-raster writeback path.

Step 0 only ships the checks and fixtures. OCR writeback is not allowed until
later steps produce a real region table.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .constants import (
    REGION_STATUS_FAILED,
    REGION_STATUS_PROTECTED,
    REGION_STATUS_SKIPPED,
    REGION_STATUS_TRANSLATED,
    REGION_STATUSES,
    SCHEMA_VERSION,
)
from .schema import ScanQualityGate, validate_scan_region
from .scientific_integrity import scientific_integrity_findings


MIN_FONT_SIZE = 5.5
CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
)
VISIBLE_LATEX_RE = re.compile(r"(?:\\[A-Za-z]+|\\[()\[\]]|_\s*(?:\{|[0-9])|\^\s*\{)")
TRANSLATION_ALTERNATIVE_RE = re.compile(r"[\u3400-\u9fff]{1,40}/[\u3400-\u9fff]{1,40}")
QUOTED_CJK_RATIO_RE = re.compile(r"[“「][\u3400-\u9fff]{1,20}/[\u3400-\u9fff]{1,20}[”」]")


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in CJK_RANGES)


def _issue(rule: str, evidence: str, *, region_id: str | None = None, page: int | None = None, severity: str = "blocking") -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "region_id": region_id,
        "page": page,
        "evidence": evidence,
    }


def count_cjk(text: str) -> int:
    return sum(1 for char in text if _is_cjk(char))


def _source_keeps_slash_ratio(source: str) -> bool:
    return "/" in source or "／" in source


def translation_has_unresolved_alternatives(source: str, translation: str) -> bool:
    """Flag CJK/CJK hedges, but keep source ratios and quoted index pairs."""
    if not TRANSLATION_ALTERNATIVE_RE.search(translation):
        return False
    if _source_keeps_slash_ratio(source):
        return False
    unquoted = QUOTED_CJK_RATIO_RE.sub("", translation)
    return bool(TRANSLATION_ALTERNATIVE_RE.search(unquoted))


def resolve_translation_alternatives(source: str, translation: str) -> str:
    """Pick the left CJK hedge unless the source (or quotes) already encodes a ratio."""
    if not TRANSLATION_ALTERNATIVE_RE.search(translation):
        return translation
    if _source_keeps_slash_ratio(source):
        return translation
    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00RATIO{len(protected) - 1}\x00"

    stashed = QUOTED_CJK_RATIO_RE.sub(stash, translation)
    resolved = TRANSLATION_ALTERNATIVE_RE.sub(lambda match: match.group(0).split("/", 1)[0], stashed)
    for index, original in enumerate(protected):
        resolved = resolved.replace(f"\x00RATIO{index}\x00", original)
    return resolved


def _polygon_points(value: Any) -> list[tuple[float, float]] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    try:
        points = [(float(point[0]), float(point[1])) for point in value]
    except (TypeError, ValueError, IndexError):
        return None
    return points


def _polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(points, [*points[1:], points[0]])
        )
    ) / 2.0


def _signed_polygon_area(points: list[tuple[float, float]]) -> float:
    return sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(points, [*points[1:], points[0]])
    ) / 2.0


def _convex_polygon_intersection_area(
    subject: list[tuple[float, float]], clip: list[tuple[float, float]]
) -> float:
    """Clip a region polygon against a convex mask/quad and return exact area."""
    output = list(subject)
    orientation = 1.0 if _signed_polygon_area(clip) >= 0 else -1.0

    def inside(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> bool:
        cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
        return orientation * cross >= -1e-7

    def intersection(
        left: tuple[float, float], right: tuple[float, float],
        start: tuple[float, float], end: tuple[float, float],
    ) -> tuple[float, float]:
        dx1, dy1 = right[0] - left[0], right[1] - left[1]
        dx2, dy2 = end[0] - start[0], end[1] - start[1]
        denominator = dx1 * dy2 - dy1 * dx2
        if abs(denominator) < 1e-9:
            return right
        t = ((start[0] - left[0]) * dy2 - (start[1] - left[1]) * dx2) / denominator
        return left[0] + t * dx1, left[1] + t * dy1

    for start, end in zip(clip, [*clip[1:], clip[0]]):
        source = output
        output = []
        if not source:
            break
        previous = source[-1]
        for current in source:
            current_inside = inside(current, start, end)
            previous_inside = inside(previous, start, end)
            if current_inside:
                if not previous_inside:
                    output.append(intersection(previous, current, start, end))
                output.append(current)
            elif previous_inside:
                output.append(intersection(previous, current, start, end))
            previous = current
    return _polygon_area(output) if len(output) >= 3 else 0.0


def _geometry_points(geometry: Any) -> list[tuple[float, float]] | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "polygon":
        return None
    return _polygon_points(geometry.get("points"))


def _points_bbox(points: list[tuple[float, float]]) -> list[float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_points(bbox: list[float]) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = bbox
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _accepted_visual_receipt(receipt: dict[str, Any] | None) -> bool:
    if not isinstance(receipt, dict) or receipt.get("conclusion") != "accepted":
        return False
    required_strings = ("reviewer", "reviewed_at", "source_sha256", "candidate_sha256")
    if any(not str(receipt.get(key) or "").strip() for key in required_strings):
        return False
    pages = receipt.get("pages")
    standards = receipt.get("standards")
    return isinstance(pages, list) and bool(pages) and isinstance(standards, list) and bool(standards)


def evaluate_scan_quality_gate(
    *,
    regions: Iterable[dict[str, Any]],
    page_count: int | None = None,
    source_page_count: int | None = None,
    source_sizes: list[tuple[float, float]] | None = None,
    translated_sizes: list[tuple[float, float]] | None = None,
    rotations: list[int] | None = None,
    bilingual_left_right_consistent: bool | None = None,
    extracted_text: str = "",
    font_embedding: dict[str, Any] | None = None,
    human_visual_accepted: bool = False,
    human_visual_review: dict[str, Any] | None = None,
) -> ScanQualityGate:
    from semantic_invariants import invariant_findings
    region_list = [dict(item) for item in regions]
    issues: list[dict[str, Any]] = []

    if not region_list:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "not_applicable",
            "searchable_text": "unknown",
            "issues": [_issue("no_regions", "扫描区域表为空；第 0 步路由不写回。", severity="info")],
            "region_count": 0,
            "experimental": True,
        }

    destroke_ids: set[str] = set()
    translated_masks: list[tuple[str, int | None, list[tuple[float, float]]]] = []
    protected_regions: list[tuple[str, int | None, list[tuple[float, float]]]] = []
    for region in region_list:
        schema_errors = validate_scan_region(region)
        region_id = str(region.get("region_id") or "")
        page = region.get("page") if isinstance(region.get("page"), int) else None
        if schema_errors:
            issues.append(_issue("region_schema", "; ".join(schema_errors), region_id=region_id or None, page=page))
            continue
        status = region.get("status")
        if status not in REGION_STATUSES:
            issues.append(_issue("region_status_missing", "高置信区域缺少四态之一。", region_id=region_id, page=page))
        if status == REGION_STATUS_SKIPPED and not region.get("skip_reason"):
            issues.append(_issue("skip_reason_missing", "skipped_with_reason 必须带原因。", region_id=region_id, page=page))
        if status == REGION_STATUS_FAILED and not region.get("skip_reason"):
            issues.append(_issue("failed_reason_missing", "failed 区域必须可回查原因。", region_id=region_id, page=page))
        if region.get("in_destroke_mask"):
            destroke_ids.add(region_id)
            geometry_points = _geometry_points(region.get("mask_geometry"))
            region_bbox = region.get("bbox")
            if geometry_points is None:
                issues.append(_issue("mask_geometry_invalid", "去字 mask 缺少有效 polygon。", region_id=region_id, page=page))
            elif isinstance(region_bbox, list) and len(region_bbox) == 4:
                normalized_bbox = [float(value) for value in region_bbox]
                geometry_bbox = _points_bbox(geometry_points)
                outside = max(
                    normalized_bbox[0] - geometry_bbox[0],
                    normalized_bbox[1] - geometry_bbox[1],
                    geometry_bbox[2] - normalized_bbox[2],
                    geometry_bbox[3] - normalized_bbox[3],
                )
                if outside > 1.0:
                    issues.append(
                        _issue(
                            "mask_geometry_outside_region",
                            f"mask 超出 region bbox {outside:.2f}pt。",
                            region_id=region_id,
                            page=page,
                        )
                    )
                translated_masks.append((region_id, page, geometry_points))
            if status in {REGION_STATUS_PROTECTED, REGION_STATUS_SKIPPED, REGION_STATUS_FAILED}:
                issues.append(
                    _issue(
                        "untranslated_or_protected_in_destroke_mask",
                        f"status={status} 的区域进入了去字 mask，未译/受保护字不能擦。",
                        region_id=region_id,
                        page=page,
                    )
                )
        if status in {REGION_STATUS_PROTECTED, REGION_STATUS_SKIPPED, REGION_STATUS_FAILED}:
            raw_bbox = region.get("bbox")
            if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
                normalized_bbox = [float(value) for value in raw_bbox]
                region_points = _polygon_points(region.get("polygon")) or _bbox_points(normalized_bbox)
                protected_regions.append((region_id, page, region_points))
        if status == REGION_STATUS_TRANSLATED and region.get("in_destroke_mask") and not str(region.get("translation") or "").strip():
            issues.append(
                _issue(
                    "translated_without_text_in_mask",
                    "标记 translated 但没有译文的区域不能去字。",
                    region_id=region_id,
                    page=page,
                )
            )
        translation_text = str(region.get("translation") or "")
        if region.get("source_column_ambiguity"):
            issues.append(_issue("source_column_order_unresolved", "源OCR栏序无法由几何和像素确认；保留源图并停止该区域翻译与去字。", region_id=region_id, page=page))
        if region.get("name_column_ambiguity"):
            issues.append(_issue("unresolved_scientific_name_column", "已识别名称表，但跨栏文字缺少可靠拆分几何；保留原图并停止该区域写回。", region_id=region_id, page=page))
        if status == REGION_STATUS_FAILED and region.get("skip_reason") == "scientific_integrity_failed":
            issues.append(_issue("scientific_integrity_failed", str(region.get("scientific_integrity_findings")), region_id=region_id, page=page))
        if status == REGION_STATUS_TRANSLATED and VISIBLE_LATEX_RE.search(translation_text):
            issues.append(
                _issue(
                    "visible_latex_syntax",
                    "正文译文仍含无法由扫描写回层排版的 LaTeX 语法。",
                    region_id=region_id,
                    page=page,
                )
            )
        source_text = str(region.get("ocr_text") or region.get("normalized_text") or "")
        if status == REGION_STATUS_TRANSLATED:
            for finding in scientific_integrity_findings(source_text, translation_text):
                issues.append(_issue(finding["rule"], str(finding), region_id=region_id, page=page))
            for finding in invariant_findings(source_text, translation_text):
                issues.append(_issue(finding['rule'], str(finding), region_id=region_id, page=page, severity='warn'))
        if status == REGION_STATUS_TRANSLATED and translation_has_unresolved_alternatives(
            source_text, translation_text
        ):
            issues.append(
                _issue(
                    "translation_alternative_marker",
                    "正文译文包含未裁决的中文备选表达。",
                    region_id=region_id,
                    page=page,
                )
            )
        if region.get("search_layer_required") and region.get("search_layer_status") != "committed_invisible":
            issues.append(
                _issue(
                    "protected_search_layer_missing",
                    f"受保护区域的中文搜索层状态为 {region.get('search_layer_status')!r}。",
                    region_id=region_id,
                    page=page,
                )
            )
        if region.get("overflow"):
            issues.append(_issue("overflow", "写回溢出。", region_id=region_id, page=page))
        if region.get("occluded"):
            issues.append(_issue("occlusion", "写回遮挡。", region_id=region_id, page=page))
        if region.get("overlap"):
            issues.append(_issue("overlap", "写回框重叠。", region_id=region_id, page=page))
        font_size = region.get("font_size")
        if isinstance(font_size, (int, float)) and float(font_size) < MIN_FONT_SIZE:
            issues.append(_issue("tiny_font", f"字号 {font_size} 过小。", region_id=region_id, page=page))

    for mask_id, mask_page, mask_polygon in translated_masks:
        for protected_id, protected_page, protected_polygon in protected_regions:
            if mask_page != protected_page or mask_id == protected_id:
                continue
            intersection = _convex_polygon_intersection_area(protected_polygon, mask_polygon)
            # Clipped axis-aligned masks can retain sub-pixel floating-point
            # contact at a shared boundary. It has no visible covered area.
            if intersection <= 0.01:
                continue
            denominator = _polygon_area(protected_polygon) or 1.0
            issues.append(
                _issue(
                    "protected_mask_geometry_overlap",
                    f"mask {mask_id} 与受保护区域 {protected_id} 相交 {intersection / denominator:.4f}。",
                    region_id=protected_id,
                    page=protected_page,
                )
            )

    if page_count is not None and source_page_count is not None and page_count != source_page_count:
        issues.append(_issue("page_count_mismatch", f"源 {source_page_count} 页，译 {page_count} 页。"))
    if source_sizes and translated_sizes and len(source_sizes) == len(translated_sizes):
        for index, (source_size, translated_size) in enumerate(zip(source_sizes, translated_sizes), start=1):
            if abs(source_size[0] - translated_size[0]) > 2 or abs(source_size[1] - translated_size[1]) > 2:
                issues.append(_issue("page_size_mismatch", f"第 {index} 页尺寸不一致。", page=index))
    if rotations:
        for index, rotation in enumerate(rotations, start=1):
            if int(rotation) % 360 != 0:
                issues.append(_issue("unexpected_rotation", f"第 {index} 页旋转 {rotation}。", page=index))
    if bilingual_left_right_consistent is False:
        issues.append(_issue("bilingual_left_right_mismatch", "双语左右页不一致。"))
    if font_embedding is not None and font_embedding.get("embedded") is not True:
        issues.append(_issue("cjk_font_not_embedded", "中文回写字体没有嵌入候选 PDF。"))

    cjk_count = count_cjk(extracted_text)
    if cjk_count >= 8:
        searchable_text: str = "cjk_ok"
    elif extracted_text.strip():
        searchable_text = "raster_only"
        issues.append(_issue("searchable_cjk_missing", "译页没有可搜索中文文本层。", severity="warn"))
    else:
        searchable_text = "raster_only"
        issues.append(_issue("searchable_cjk_missing", "译页没有可复制文本层。", severity="warn"))

    blocking = [item for item in issues if item.get("severity") == "blocking"]
    if blocking:
        status = "blocking"
    elif searchable_text == "raster_only":
        status = "partial"
    elif not _accepted_visual_receipt(human_visual_review):
        status = "partial"
        evidence = "人工视觉验收回执缺失或字段不完整。"
        if human_visual_accepted:
            evidence = "仅有 human_visual_accepted 布尔值；需要带来源 SHA、候选 SHA、页码、标准和审查人的回执。"
        issues.append(_issue("human_visual_pending", evidence, severity="warn"))
    else:
        status = "ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "searchable_text": searchable_text,
        "issues": issues,
        "region_count": len(region_list),
        "destroke_region_ids": sorted(destroke_ids),
        "font_embedding": font_embedding,
        "human_visual_review": human_visual_review,
        "experimental": True,
    }
