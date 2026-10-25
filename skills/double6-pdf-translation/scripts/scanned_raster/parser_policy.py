"""轻量识别先看整页。清晰单栏留在 RapidOCR；版面困难再升级 MinerU。"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

from .constants import (
    FORMULA_LAYOUT_ROLES,
    MINERU_MIN_TEXT_RECALL,
    RAPIDOCR_MIN_MEDIAN_CONFIDENCE,
    RAPIDOCR_MIN_REGION_CONFIDENCE,
)

FORMULA_RE = re.compile(r"(?:[=∑∫√±×÷]|\b(?:sin|cos|log|lim)\b|[A-Za-z]\s*[₀-₉²³^])")

# 单栏页上只有置信度偏低时，轻量识别已经够用，不再为此升级版面模型。
# 没读出字、旋转、双栏、阅读顺序、表格、公式和已有质量失败仍要升级。
CONFIDENCE_ONLY_REASONS = frozenset({
    "region_confidence_below_0.75",
    "median_confidence_below_0.90",
})


def _is_two_column(regions: list[dict[str, Any]], page_width: float) -> bool:
    """Detect sustained body-text columns, not equations or running metadata."""
    if page_width <= 0:
        return False

    candidates: list[tuple[dict[str, Any], float]] = []
    for item in regions:
        bbox = item.get("bbox") or []
        text = str(item.get("ocr_text") or "").strip()
        if len(bbox) != 4 or len(re.sub(r"\W", "", text, flags=re.UNICODE)) < 12:
            continue
        x0, _y0, x1, _y1 = [float(value) for value in bbox]
        width_ratio = max(0.0, x1 - x0) / page_width
        if not 0.16 <= width_ratio <= 0.58:
            continue
        candidates.append((item, (x0 + x1) / (2.0 * page_width)))

    left = [item for item, center_ratio in candidates if center_ratio <= 0.45]
    right = [item for item, center_ratio in candidates if center_ratio >= 0.55]
    if len(left) < 3 or len(right) < 3:
        return False

    def vertical_span(items: list[dict[str, Any]]) -> tuple[float, float]:
        y0 = min(float(item["bbox"][1]) for item in items)
        y1 = max(float(item["bbox"][3]) for item in items)
        return y0, y1

    left_y0, left_y1 = vertical_span(left)
    right_y0, right_y1 = vertical_span(right)
    overlap = max(0.0, min(left_y1, right_y1) - max(left_y0, right_y0))
    shorter_span = max(1.0, min(left_y1 - left_y0, right_y1 - right_y0))
    if overlap / shorter_span < 0.35:
        return False

    paired_rows = 0
    for left_item in left:
        left_bbox = [float(value) for value in left_item["bbox"]]
        left_center_y = (left_bbox[1] + left_bbox[3]) / 2.0
        left_height = max(1.0, left_bbox[3] - left_bbox[1])
        if any(
            abs(
                left_center_y
                - (float(right_item["bbox"][1]) + float(right_item["bbox"][3])) / 2.0
            )
            <= max(
                left_height,
                float(right_item["bbox"][3]) - float(right_item["bbox"][1]),
            )
            * 1.5
            for right_item in right
        ):
            paired_rows += 1
    return paired_rows >= 2


def _looks_tabular(regions: list[dict[str, Any]]) -> bool:
    if len(regions) < 6:
        return False
    x_starts = [round(float(item["bbox"][0]) / 20.0) for item in regions]
    repeated = max((x_starts.count(value) for value in set(x_starts)), default=0)
    numeric = sum(bool(re.search(r"\b\d+(?:[.,]\d+)?\b", str(item.get("ocr_text") or ""))) for item in regions)
    return repeated >= 3 and numeric >= 3


def _rotated(regions: list[dict[str, Any]], page_width: float) -> bool:
    oblique_candidates = 0
    for item in regions:
        polygon = item.get("polygon") or []
        bbox = item.get("bbox") or []
        text = str(item.get("ocr_text") or "").strip()
        meaningful_chars = len(re.sub(r"\W", "", text, flags=re.UNICODE))
        if len(polygon) < 2 or len(bbox) != 4 or meaningful_chars < 6:
            continue
        dx = float(polygon[1][0]) - float(polygon[0][0])
        dy = float(polygon[1][1]) - float(polygon[0][1])
        if dx == 0 and dy == 0:
            continue
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        angle = min(angle, 180.0 - angle)
        x0, y0, x1, y1 = [float(value) for value in bbox]
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        width_ratio = width / page_width if page_width > 0 else 0.0

        if angle >= 45.0 or (height > width * 1.35 and meaningful_chars >= 8):
            return True
        if angle >= 8.0 and width_ratio >= 0.12:
            if width_ratio >= 0.35 and meaningful_chars >= 20:
                return True
            oblique_candidates += 1
    return oblique_candidates >= 2


def _reading_order_conflict(regions: list[dict[str, Any]], page_width: float) -> bool:
    ordered = sorted(regions, key=lambda item: int(item.get("reading_order") or 0))
    previous_by_column: dict[int, tuple[float, float]] = {}
    for item in ordered:
        bbox = item.get("bbox") or []
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = [float(value) for value in bbox]
        center_x = (x0 + x1) / 2.0
        column = 0 if center_x < page_width / 2.0 else 1
        previous = previous_by_column.get(column)
        if previous is not None:
            previous_y, previous_height = previous
            tolerance = max(4.0, previous_height * 0.5)
            if y0 + tolerance < previous_y:
                return True
        previous_by_column[column] = (y0, max(1.0, y1 - y0))
    return False


def assess_rapidocr_page(
    regions: list[dict[str, Any]],
    *,
    page_width: float,
    nonblank: bool = True,
    existing_gate_failed: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []
    text_regions = [item for item in regions if str(item.get("ocr_text") or "").strip()]
    confidences = [float(item["confidence"]) for item in text_regions if isinstance(item.get("confidence"), (int, float))]
    if nonblank and not text_regions:
        reasons.append("nonblank_page_without_ocr_text")
    if confidences and min(confidences) < RAPIDOCR_MIN_REGION_CONFIDENCE:
        reasons.append("region_confidence_below_0.75")
    if confidences and statistics.median(confidences) < RAPIDOCR_MIN_MEDIAN_CONFIDENCE:
        reasons.append("median_confidence_below_0.90")
    if _rotated(text_regions, page_width):
        reasons.append("rotated_text")
    if _is_two_column(text_regions, page_width):
        reasons.append("multi_column_layout")
    if _reading_order_conflict(text_regions, page_width):
        reasons.append("reading_order_conflict")
    if _looks_tabular(text_regions):
        reasons.append("table_candidate")
    if any(FORMULA_RE.search(str(item.get("ocr_text") or "")) for item in text_regions):
        reasons.append("formula_candidate")
    if existing_gate_failed:
        reasons.append("rapidocr_quality_gate_failed")
    reasons = sorted(set(reasons))
    escalation_reasons = [reason for reason in reasons if reason not in CONFIDENCE_ONLY_REASONS]
    return {
        "escalate": bool(escalation_reasons),
        "reasons": reasons,
        "escalation_reasons": escalation_reasons,
        "region_count": len(text_regions),
        "minimum_confidence": min(confidences) if confidences else None,
        "median_confidence": statistics.median(confidences) if confidences else None,
    }


def assess_mineru_result(
    regions: list[dict[str, Any]],
    *,
    rapidocr_regions: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    reasons = list(warnings or [])
    mineru_chars = sum(len(str(item.get("normalized_text") or "")) for item in regions)
    rapidocr_chars = sum(len(str(item.get("normalized_text") or "")) for item in rapidocr_regions)
    recall = 1.0 if rapidocr_chars == 0 else mineru_chars / rapidocr_chars
    if not regions:
        reasons.append("mineru_no_regions")
    if recall < MINERU_MIN_TEXT_RECALL:
        reasons.append("mineru_text_recall_below_0.80")
    if any(not item.get("bbox") or not item.get("polygon") for item in regions):
        reasons.append("mineru_geometry_missing")
    reading_orders = [item.get("reading_order") for item in regions]
    if any(not isinstance(value, int) for value in reading_orders) or len(set(reading_orders)) != len(reading_orders):
        reasons.append("mineru_reading_order_unresolved")
    asset_missing = any(
        item.get("layout_role") in {"table", "image", "chart"} and not item.get("asset_refs")
        for item in regions
    )
    if asset_missing:
        reasons.append("mineru_required_asset_missing")
    if any(
        item.get("layout_role") in FORMULA_LAYOUT_ROLES
        and not str(item.get("normalized_text") or "").strip()
        for item in regions
    ):
        reasons.append("mineru_formula_unresolved")
    unresolved_roles = {
        str(item.get("layout_role"))
        for item in regions
        if item.get("layout_role") in {"unknown", "discarded"}
    }
    if unresolved_roles:
        reasons.append("mineru_unresolved_layout_role")
    return {
        "accepted": not reasons,
        "reasons": sorted(set(reasons)),
        "text_recall": round(recall, 4),
        "mineru_chars": mineru_chars,
        "rapidocr_chars": rapidocr_chars,
    }
