# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline ocr：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def run_rapidocr_page(input_pdf: Path, page_number: int, dpi: int = DEFAULT_SCAN_DPI) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from scanned_raster.pipeline_ocr_groups import _coalesce_rapidocr_line_fragments
    from scanned_raster.pipeline_resources import _config_sha256, _polygon_bbox, _sha256_bytes, render_page_png
    from rapidocr_onnxruntime import RapidOCR

    png, page_width, page_height, page_rotation = render_page_png(input_pdf, page_number, dpi=dpi)
    engine = RapidOCR()
    output, timing = engine(png)
    from .column_ocr import recognize_columns
    output,column_plan,column_timings=recognize_columns(png,output or [],engine)
    scale = dpi / 72.0
    source_sha = sha256_file(input_pdf)
    image_sha = _sha256_bytes(png)
    from PIL import Image, ImageStat

    grayscale = Image.open(BytesIO(png)).convert("L")
    page_stats = ImageStat.Stat(grayscale)
    mean_luma = float(page_stats.mean[0])
    luma_stddev = float(page_stats.stddev[0])
    nonblank = mean_luma < 250.0 or luma_stddev > 2.0
    config_sha = _config_sha256(
        {
            "engine": "rapidocr",
            "engine_version": "1.4.4",
            "column_policy": column_plan["policy"],
            "dpi": dpi,
            "colorspace": "rgb",
            "page_rotation": page_rotation,
        }
    )
    regions: list[dict[str, Any]] = []
    for order, item in enumerate(output or []):
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        raw_points, text, score = item[0], item[1], item[2]
        column_evidence=item[3] if len(item)>3 and isinstance(item[3],dict) else {}
        if not isinstance(raw_points, (list, tuple)) or len(raw_points) < 4:
            continue
        polygon = [[float(point[0]) / scale, float(point[1]) / scale] for point in raw_points]
        bbox = _polygon_bbox(polygon)
        region_id = f"p{page_number:04d}-r{order:04d}"
        confidence = float(score) if isinstance(score, (int, float)) else None
        regions.append(
            {
                "region_id": region_id,
                "page": page_number,
                "source_page_idx": page_number - 1,
                "bbox": bbox,
                "polygon": polygon,
                "layout_role": "text",
                "reading_order": order,
                "source_column": column_evidence.get('column'),
                "source_column_kind": column_evidence.get('kind'),
                "source_column_policy": column_evidence.get('policy'),
                "ocr_crop_evidence": column_evidence,
                "ocr_text": str(text or ""),
                "normalized_text": " ".join(str(text or "").split()),
                "confidence": confidence,
                "confidence_source": "rapidocr_recognition_score" if confidence is not None else "rapidocr_not_provided",
                "engine": "rapidocr",
                "engine_version": "1.4.4",
                "model": "PP-OCRv4-onnx",
                "tier": None,
                "source_pdf_sha256": source_sha,
                "source_page_image_sha256": image_sha,
                "config_sha256": config_sha,
                "preprocess": {
                    "dpi": dpi,
                    "colorspace": "rgb",
                    "page_width": page_width,
                    "page_height": page_height,
                    "page_rotation": page_rotation,
                },
                "translation_group_id": f"p{page_number:04d}-g{order:04d}",
                "status": "skipped_with_reason",
                "translation": None,
                "skip_reason": "translation_pending",
                "in_destroke_mask": False,
                "mask_geometry": {"type": "polygon", "points": polygon},
                "mask_overlap_ratio": 0.0,
                "overflow": False,
                "occluded": False,
                "overlap": False,
            }
        )
    _annotate_rapidocr_regions(regions, page_width=page_width, page_height=page_height)
    column_assessment=assess_rapidocr_page(regions,page_width=page_width,nonblank=nonblank)
    unresolved=(column_plan['status']=='ambiguous_spanning_line' or
                ('multi_column_layout' in column_assessment['reasons'] and column_plan['status']!='verified_simple_two_column'))
    if unresolved:
        for region in regions:
            if region.get('layout_role') not in PROTECTED_LAYOUT_ROLES:
                region['source_column_ambiguity']=True
    regions = _coalesce_rapidocr_line_fragments(regions)
    return regions, {
        "page": page_number,
        "page_width": page_width,
        "page_height": page_height,
        "page_rotation": page_rotation,
        "page_image_sha256": image_sha,
        "timing": timing,
        "column_recognition": column_plan,
        "column_crop_timings": column_timings,
        "nonblank": nonblank,
        "mean_luma": round(mean_luma, 4),
        "luma_stddev": round(luma_stddev, 4),
    }


def _rapidocr_geometry_fragments(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the finest available RapidOCR boxes for source typography evidence."""
    fragments: list[dict[str, Any]] = []
    for region in regions:
        candidates = region.get("source_fragments") or [region]
        for candidate in candidates:
            bbox = candidate.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            fragments.append(
                {
                    "region_id": candidate.get("region_id") or region.get("region_id"),
                    "bbox": [float(value) for value in bbox],
                    "polygon": candidate.get("polygon"),
                    "ocr_text": candidate.get("ocr_text") or region.get("ocr_text"),
                    "confidence": candidate.get("confidence", region.get("confidence")),
                    "source_fragments": [],
                }
            )
    return fragments

def _annotate_mineru_regions_with_rapidocr_geometry(
    mineru_regions: list[dict[str, Any]], rapidocr_regions: list[dict[str, Any]]
) -> int:
    """Add source line boxes and line height to MinerU blocks.

    MinerU MiddleJSON exposes block geometry but not a stable printed line height.
    RapidOCR has weaker structure but much finer line boxes, so it is used only as
    source typography and destroking evidence here. MinerU remains authoritative
    for block role, reading order, and translated text grouping.
    """
    rapid_lines = _rapidocr_geometry_fragments(rapidocr_regions)
    annotated = 0
    for region in mineru_regions:
        if str(region.get("layout_role") or "") in PROTECTED_LAYOUT_ROLES:
            continue
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in bbox)
        matches: list[dict[str, Any]] = []
        for line in rapid_lines:
            lx0, ly0, lx1, ly1 = line["bbox"]
            line_area = max(1.0, (lx1 - lx0) * (ly1 - ly0))
            overlap = max(0.0, min(x1, lx1) - max(x0, lx0)) * max(
                0.0, min(y1, ly1) - max(y0, ly0)
            )
            center_x = (lx0 + lx1) / 2.0
            center_y = (ly0 + ly1) / 2.0
            center_inside = x0 - 3.0 <= center_x <= x1 + 3.0 and y0 - 3.0 <= center_y <= y1 + 3.0
            if center_inside or overlap / line_area >= 0.35:
                matches.append(line)
        if not matches:
            continue
        matches.sort(key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
        heights = [max(1.0, float(item["bbox"][3]) - float(item["bbox"][1])) for item in matches]
        region.update(
            source_line_evidence=matches,
            source_line_count=len(matches),
            source_line_height=round(float(statistics.median(heights)), 3),
            source_geometry_source="rapidocr_line_overlap",
        )
        annotated += 1
    return annotated

def _annotate_rapidocr_regions(
    regions: list[dict[str, Any]], *, page_width: float, page_height: float
) -> None:
    """Add lightweight roles and paragraph groups without loading MinerU."""
    from scanned_raster.pipeline_ocr_groups import _ends_terminal_punctuation
    ordered = sorted(regions, key=lambda item: int(item.get("reading_order") or 0))
    line_heights = [
        max(1.0, float(item["bbox"][3]) - float(item["bbox"][1]))
        for item in ordered
        if isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4
    ]
    median_height = statistics.median(line_heights) if line_heights else 12.0
    chapter_tops = [
        float(item["bbox"][1])
        for item in ordered
        if isinstance(item.get("bbox"), list)
        and len(item["bbox"]) == 4
        and re.fullmatch(
            r"(?:CHAPTER|BOOK|PART)\s+[IVXLCDM\d. -]+",
            " ".join(str(item.get("ocr_text") or "").split()),
            flags=re.IGNORECASE,
        )
    ]
    first_chapter_top = min(chapter_tops) if chapter_tops else None
    previous: dict[str, Any] | None = None
    group_index = -1
    for item in ordered:
        text = str(item.get("ocr_text") or "").strip()
        bbox = item.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        x0, y0, x1, y1 = [float(value) for value in bbox]
        normalized = " ".join(text.split())
        if re.search(r"copyright|版权所有", normalized, flags=re.IGNORECASE):
            item["layout_role"] = "copyright"
        elif first_chapter_top is not None and y1 < first_chapter_top:
            item["layout_role"] = "illustration_text"
        elif re.fullmatch(r"[-–—\s]*\d+[-–—\s]*", normalized) and (
            y0 <= page_height * 0.10 or y1 >= page_height * 0.90
        ):
            item["layout_role"] = "page_number"
        elif y0 <= page_height * 0.065 and len(normalized) <= 100:
            item["layout_role"] = "header"
        elif y1 >= page_height * 0.94 and len(normalized) <= 120:
            item["layout_role"] = "footer"

        starts_quote = bool(re.match(r'^["“‘]', normalized))
        heading = bool(re.fullmatch(r"(?:CHAPTER|BOOK|PART)\s+[IVXLCDM\d. -]+", normalized, flags=re.IGNORECASE))
        if heading:
            item["layout_role"] = "chapter_heading"
        role = str(item.get("layout_role") or "text")
        new_group = previous is None
        boundary_reason = "page_start" if previous is None else "continued_paragraph"
        if previous is not None:
            previous_bbox = previous.get("bbox") or [0.0, 0.0, 0.0, 0.0]
            previous_x0 = float(previous_bbox[0])
            previous_y0 = float(previous_bbox[1])
            previous_y1 = float(previous_bbox[3])
            same_line = abs(((y0 + y1) / 2.0) - ((previous_y0 + previous_y1) / 2.0)) <= median_height * 0.55
            vertical_gap = y0 - previous_y1
            previous_role = str(previous.get("layout_role") or "text")
            previous_text = " ".join(str(previous.get("ocr_text") or "").split())
            previous_heading = bool(
                re.fullmatch(r"(?:CHAPTER|BOOK|PART)\s+[IVXLCDM\d. -]+", previous_text, flags=re.IGNORECASE)
            )
            protected_boundary = role in PROTECTED_LAYOUT_ROLES or previous_role in PROTECTED_LAYOUT_ROLES
            heading_boundary = heading or previous_heading
            quote_boundary = starts_quote and not same_line
            large_structural_gap = vertical_gap > median_height * 3.0
            previous_ends_sentence = _ends_terminal_punctuation(previous_text)
            paragraph_gap = vertical_gap > median_height * 1.25
            paragraph_indent = x0 - previous_x0 > median_height * 0.75
            punctuation_layout_boundary = previous_ends_sentence and (paragraph_gap or paragraph_indent)
            column_changed=item.get('source_column') != previous.get('source_column')
            confirmed_continuation=(previous.get('source_column_kind')=='body_left' and item.get('source_column_kind')=='body_right'
                                    and previous.get('source_column_policy')==item.get('source_column_policy')
                                    and item.get('source_column_policy') is not None and not previous_ends_sentence)
            column_boundary=column_changed and not confirmed_continuation
            new_group = any(
                (
                    column_boundary,
                    protected_boundary,
                    heading_boundary,
                    quote_boundary,
                    large_structural_gap,
                    punctuation_layout_boundary,
                )
            )
            if column_boundary:
                boundary_reason = "source_column_boundary"
            elif confirmed_continuation:
                item["source_continuation_evidence"]="same_page_left_column_end_to_right_column_start_unfinished_sentence"
            elif protected_boundary:
                boundary_reason = "protected_role_boundary"
            elif heading_boundary:
                boundary_reason = "heading_boundary"
            elif quote_boundary:
                boundary_reason = "opening_quote_boundary"
            elif large_structural_gap:
                boundary_reason = "large_structural_gap"
            elif punctuation_layout_boundary:
                boundary_reason = "terminal_punctuation_with_layout_break"
        if new_group:
            group_index += 1
            item["paragraph_boundary_reason"] = boundary_reason
        item["translation_group_id"] = f"p{int(item.get('page') or 1):04d}-rg{group_index:04d}"
        previous = item


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
