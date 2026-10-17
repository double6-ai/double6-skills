# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline ocr groups：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def _ends_terminal_punctuation(text: str) -> bool:
    """Return whether an OCR line ends like a completed sentence.

    Closing quotation marks and brackets are ignored. This signal is only used
    together with a layout break, so abbreviations such as ``Mr.`` at the end
    of an ordinary printed line do not split the paragraph by themselves.
    """
    normalized = " ".join(str(text or "").split()).rstrip()
    return bool(re.search(r"[.!?。！？…][\"'”’）)\]\}»›]*$", normalized))

def _join_ocr_group_text(regions: list[dict[str, Any]]) -> str:
    text = " ".join(str(item.get("ocr_text") or "").strip() for item in regions).strip()
    text = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", text)

def _coalesce_rapidocr_line_fragments(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent OCR fragments that belong to one printed line.

    RapidOCR can split a drop-cap line into several boxes. Keeping those boxes
    separate makes paragraph-level translations render as isolated syllables.
    The original boxes remain in ``source_fragments`` for auditability.
    """
    ordered = sorted(regions, key=lambda item: int(item.get("reading_order") or 0))
    heights = [
        max(1.0, float(item["bbox"][3]) - float(item["bbox"][1]))
        for item in ordered
        if isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4
    ]
    median_height = statistics.median(heights) if heights else 12.0
    merged: list[dict[str, Any]] = []

    def fragment(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "region_id": item.get("region_id"),
            "bbox": item.get("bbox"),
            "polygon": item.get("polygon"),
            "ocr_text": item.get("ocr_text"),
            "confidence": item.get("confidence"),
        }

    for item in ordered:
        if not merged:
            merged.append(dict(item))
            continue
        previous = merged[-1]
        bbox = item.get("bbox")
        previous_bbox = previous.get("bbox")
        can_merge = False
        if (
            isinstance(bbox, list)
            and len(bbox) == 4
            and isinstance(previous_bbox, list)
            and len(previous_bbox) == 4
            and item.get("translation_group_id") == previous.get("translation_group_id")
            and item.get("source_column") == previous.get("source_column")
            and item.get("layout_role") == previous.get("layout_role")
        ):
            x0, y0, x1, y1 = [float(value) for value in bbox]
            px0, py0, px1, py1 = [float(value) for value in previous_bbox]
            center_delta = abs(((y0 + y1) / 2.0) - ((py0 + py1) / 2.0))
            horizontal_gap = x0 - px1
            same_line = (
                center_delta <= median_height * 0.55
                and -median_height * 0.25 <= horizontal_gap <= median_height * 2.5
            )
            previous_width = max(1.0, px1 - px0)
            current_width = max(1.0, x1 - x0)
            vertical_gap = y0 - py1
            short_wrapped_tail = (
                current_width <= previous_width * 0.22
                and abs(x0 - px0) <= median_height * 1.5
                and -median_height * 0.15 <= vertical_gap <= median_height * 0.40
            )
            can_merge = same_line or short_wrapped_tail
        if not can_merge:
            merged.append(dict(item))
            continue

        fragments = list(previous.get("source_fragments") or [fragment(previous)])
        fragments.extend(item.get("source_fragments") or [fragment(item)])
        previous["source_fragments"] = fragments
        previous["source_region_ids"] = [str(value.get("region_id")) for value in fragments]
        previous["bbox"] = [
            min(float(previous_bbox[0]), float(bbox[0])),
            min(float(previous_bbox[1]), float(bbox[1])),
            max(float(previous_bbox[2]), float(bbox[2])),
            max(float(previous_bbox[3]), float(bbox[3])),
        ]
        bx0, by0, bx1, by1 = previous["bbox"]
        previous["polygon"] = [[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1]]
        previous["mask_geometry"] = {"type": "polygon", "points": previous["polygon"]}
        previous["ocr_text"] = " ".join(
            value for value in [str(previous.get("ocr_text") or "").strip(), str(item.get("ocr_text") or "").strip()] if value
        )
        previous["normalized_text"] = " ".join(previous["ocr_text"].split())
        confidences = [value.get("confidence") for value in fragments if isinstance(value.get("confidence"), (int, float))]
        previous["confidence"] = min(confidences) if confidences else None

    for order, item in enumerate(merged):
        item["reading_order"] = order
    return merged

def _coalesce_rapidocr_paragraph_bands(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse OCR lines into paragraph-shaped render bands.

    Translation groups stay intact for one model call per paragraph. A group is
    split into more than one render band only when its left edge changes enough
    to show text wrapping around an illustration or another protected object.
    Original line geometry is retained in ``source_regions``.
    """
    ordered = sorted(regions, key=lambda item: int(item.get("reading_order") or 0))
    heights = [
        max(1.0, float(item["bbox"][3]) - float(item["bbox"][1]))
        for item in ordered
        if isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4
    ]
    median_height = statistics.median(heights) if heights else 12.0
    paragraph_groups: list[list[dict[str, Any]]] = []
    for item in ordered:
        if (
            paragraph_groups
            and item.get("translation_group_id") == paragraph_groups[-1][-1].get("translation_group_id")
            and item.get("layout_role") == paragraph_groups[-1][-1].get("layout_role")
        ):
            paragraph_groups[-1].append(item)
        else:
            paragraph_groups.append([item])

    collapsed: list[dict[str, Any]] = []

    def source_region(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "region_id": item.get("region_id"),
            "bbox": item.get("bbox"),
            "polygon": item.get("polygon"),
            "ocr_text": item.get("ocr_text"),
            "confidence": item.get("confidence"),
            "source_fragments": item.get("source_fragments") or [],
        }

    for group in paragraph_groups:
        role = str(group[0].get("layout_role") or "text")
        if role in PROTECTED_LAYOUT_ROLES or group[0].get("structured_name_column") or group[0].get("frontmatter_alignment_policy"):
            collapsed.extend(dict(item) for item in group)
            continue
        bands: list[list[dict[str, Any]]] = []
        for item in group:
            bbox = item.get("bbox")
            if not bands or not isinstance(bbox, list) or len(bbox) != 4:
                bands.append([item])
                continue
            previous_bbox = bands[-1][-1].get("bbox")
            if not isinstance(previous_bbox, list) or len(previous_bbox) != 4:
                bands.append([item])
                continue
            left_edge_shift = abs(float(bbox[0]) - float(previous_bbox[0]))
            if left_edge_shift > max(96.0, median_height * 2.5):
                bands.append([item])
            else:
                bands[-1].append(item)

        group_text = _join_ocr_group_text(group)
        for band_index, band in enumerate(bands):
            bboxes = [item["bbox"] for item in band if isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4]
            if not bboxes:
                collapsed.extend(dict(item) for item in band)
                continue
            x0 = min(float(value[0]) for value in bboxes)
            y0 = min(float(value[1]) for value in bboxes)
            x1 = max(float(value[2]) for value in bboxes)
            y1 = max(float(value[3]) for value in bboxes)
            source_lines = [source_region(item) for item in band]
            line_heights = [max(1.0, float(value[3]) - float(value[1])) for value in bboxes]
            source_line_height = float(statistics.median(line_heights))
            horizontal_padding = max(3.0, source_line_height)
            page_width = float((band[0].get("preprocess") or {}).get("page_width") or x1 + horizontal_padding)
            render_x0 = max(0.0, x0 - horizontal_padding * 0.15)
            render_x1 = min(page_width, x1 + horizontal_padding)
            confidences = [
                item.get("confidence")
                for item in band
                if isinstance(item.get("confidence"), (int, float))
            ]
            merged = dict(band[0])
            merged.update(
                region_id=f"{band[0].get('translation_group_id')}-pb{band_index:02d}",
                source_bbox=[x0, y0, x1, y1],
                bbox=[render_x0, y0, render_x1, y1],
                polygon=[[render_x0, y0], [render_x1, y0], [render_x1, y1], [render_x0, y1]],
                mask_geometry={
                    "type": "polygon",
                    "points": [[render_x0, y0], [render_x1, y0], [render_x1, y1], [render_x0, y1]],
                },
                ocr_text=_join_ocr_group_text(band),
                normalized_text=" ".join(_join_ocr_group_text(band).split()),
                confidence=min(confidences) if confidences else None,
                render_unit="paragraph_band",
                paragraph_source_text=group_text,
                paragraph_band_index=band_index,
                paragraph_band_count=len(bands),
                source_line_count=len(source_lines),
                source_line_height=round(source_line_height, 3),
                render_horizontal_padding=round(horizontal_padding, 3),
                source_region_ids=[str(item.get("region_id")) for item in band],
                source_regions=source_lines,
            )
            collapsed.append(merged)

    for order, item in enumerate(collapsed):
        item["reading_order"] = order
    return collapsed

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
