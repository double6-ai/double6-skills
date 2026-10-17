"""依据明确双列表头与 OCR 几何保护植物学名；不把普通英文猜成学名。"""
from __future__ import annotations

import copy
import re


POLICY = "explicit_common_scientific_name_columns_v1"


def _text(row: dict) -> str:
    return str(row.get("normalized_text") or row.get("ocr_text") or "").strip()


def _heading(row: dict, label: str) -> bool:
    return re.sub(r"[\s_:]+", "", _text(row)).casefold() == label


def _scientific(text: str) -> bool:
    # 下划线/开头孤立 OCR 数字只用于识别，不改原文或原图中的拼写。
    value = re.sub(r"^[\W\d_]+", "", text).replace("_", " ").strip()
    return bool(re.fullmatch(
        r"[A-Z][a-z]{2,}(?:\s+[a-z][a-z-]{2,}(?:\s*[\"“][A-Za-z][A-Za-z '\-]+[\"”])?"
        r"|\s*[\"“][A-Za-z][A-Za-z '\-]+[\"”])", value))


def preserve_source_region(row: dict, reason: str) -> None:
    row.update(status="protected", skip_reason=reason, translation=None, in_destroke_mask=False)
    stale_render_fields = {"translation_raw", "writeback_status", "render_bbox", "font_size", "initial_font_size",
                           "destroke_boxes", "destroke_strategy", "destroke_mask_pixels", "background_fill_strategy",
                           "paragraph_style", "text_alignment", "first_line_indent_em", "lineheight"}
    for key in [key for key in row if key in stale_render_fields or key.startswith("search_layer_")]:
        row.pop(key, None)


def vertical_margin_reason(row: dict) -> str | None:
    box = row.get("original_layout_bbox") or row.get("bbox")
    if not isinstance(box, list) or len(box) != 4:
        return None
    width, height = box[2] - box[0], box[3] - box[1]
    if width <= 0 or height <= 2 * width:
        return None
    if row.get("layout_role") == "aside_text":
        return "protected_vertical_aside"
    page_width = row.get("preprocess", {}).get("page_width", 0)
    if row.get("layout_role") != "text" or not page_width or width > .12 * page_width:
        return None
    if not (box[2] <= .20 * page_width or box[0] >= .80 * page_width):
        return None
    lines = [line for line in row.get("source_line_evidence", [])
             if len(re.sub(r"[^A-Za-z]", "", str(line.get("ocr_text", "")))) >= 3
             and len(line.get("bbox", [])) == 4]
    if len(lines) < 2:
        return None
    rotated = sum(line["bbox"][3] - line["bbox"][1] > 1.5 * (line["bbox"][2] - line["bbox"][0]) for line in lines)
    return "protected_vertical_margin_geometry" if rotated >= .75 * len(lines) else None


def prepare_name_columns(regions: list[dict]) -> list[dict]:
    """最多识别每页一个明确名称表；保留拆分来源并使重复执行幂等。"""
    result = copy.deepcopy(regions)
    for page in sorted({r.get("page", 0) for r in result}):
        rows = [r for r in result if r.get("page", 0) == page]
        if len(rows) > 2000 or any(r.get("name_column_policy") == POLICY for r in rows):
            continue
        common = [r for r in rows if _heading(r, "commonname")]
        science = [r for r in rows if _heading(r, "scientificname")]
        if len(common) != 1 or len(science) != 1:
            continue
        left, right = common[0], science[0]
        a, z = left["bbox"], right["bbox"]
        line_height = max(a[3] - a[1], z[3] - z[1])
        if line_height <= 0 or a[2] >= z[0] or abs(a[1] - z[1]) > line_height:
            continue
        next_headings = [r["bbox"][1] for r in rows if r.get("layout_role") in {"paragraph_title", "chapter_heading"}
                         and r["bbox"][1] > max(a[3], z[3])]
        bottom = min(next_headings, default=float("inf"))
        candidates = []
        for row in rows:
            box = row["bbox"]
            if row.get("layout_role") != "text" or not max(a[3], z[3]) < box[1] < bottom:
                continue
            if box[3] - box[1] > 2 * line_height:
                continue
            if box[0] > a[2] + .5 * line_height and box[2] <= z[2] + 2 * line_height and _scientific(_text(row)):
                candidates.append((row, None))
                continue
            # 跨两栏的解析块必须有两份独立印刷行几何；无此证据不猜拆分点。
            fragments = row.get("source_line_evidence") or []
            lf = [f for f in fragments if len(f.get("bbox", [])) == 4 and f["bbox"][2] <= a[2] + line_height]
            rf = [f for f in fragments if len(f.get("bbox", [])) == 4 and f["bbox"][0] > a[2] + .5 * line_height
                  and f["bbox"][2] <= z[2] + 2 * line_height and _scientific(str(f.get("ocr_text", "")))]
            if len(fragments) == 2 and len(lf) == len(rf) == 1 and lf[0]["bbox"][2] < rf[0]["bbox"][0]:
                if abs(lf[0]["bbox"][1] - rf[0]["bbox"][1]) <= line_height:
                    candidates.append((row, (lf[0], rf[0])))
        if len(candidates) < 3:
            continue
        replacements = {}
        last_y = max(row["bbox"][3] for row, _ in candidates)
        candidate_ids = {row["region_id"] for row, _ in candidates}
        for row in rows:
            if (row is left or row is right or
                max(a[3], z[3]) < row["bbox"][1] <= last_y and row["bbox"][0] < a[2] and row["bbox"][2] <= a[2] + 6 * line_height):
                row.update(name_column_policy=POLICY, structured_name_column="common")
                row["translation_group_id"] = row["region_id"] + "-name-field"
            if (row["region_id"] not in candidate_ids and row.get("layout_role") == "text"
                and max(a[3], z[3]) < row["bbox"][1] <= last_y
                and row["bbox"][0] <= a[2] and row["bbox"][2] >= z[0]
                and row["bbox"][3] - row["bbox"][1] <= 2 * line_height):
                row.update(name_column_policy=POLICY, name_column_ambiguity=True,
                           status="failed", skip_reason="unresolved_scientific_name_column", in_destroke_mask=False)
        for row, split in candidates:
            if split is None:
                row.update(name_column_policy=POLICY, structured_name_column="scientific")
                row["translation_group_id"] = row["region_id"] + "-name-field"
                preserve_source_region(row, "protected_scientific_name_column")
                continue
            children = []
            for column, fragment in zip(["common", "scientific"], split, strict=True):
                child = copy.deepcopy(row)
                box = list(fragment["bbox"])
                child.update(region_id=row["region_id"] + "-" + column,
                             split_from_region_id=row["region_id"], split_source_text=_text(row),
                             name_column_policy=POLICY, structured_name_column=column,
                             bbox=box, polygon=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]],
                             ocr_text=fragment["ocr_text"], normalized_text=" ".join(fragment["ocr_text"].split()),
                             source_line_evidence=[copy.deepcopy(fragment)], source_line_count=1,
                             source_line_height=box[3]-box[1], translation=None, status="pending", in_destroke_mask=False,
                             translation_group_id=row["region_id"] + "-" + column)
                for key in ["render_bbox", "original_layout_bbox", "source_geometry_expansion", "source_bbox", "mask_geometry",
                            "destroke_boxes", "font_size", "translation_raw", "writeback_status", "overflow", "overlap", "occluded"]:
                    child.pop(key, None)
                child["mask_geometry"] = {"type": "polygon", "points": child["polygon"]}
                if column == "scientific":
                    preserve_source_region(child, "protected_scientific_name_column")
                children.append(child)
            replacements[row["region_id"]] = children
        result = [child for row in result for child in replacements.get(row["region_id"], [row])]
        # 独立排版边界不扩大去字区域；右边界由最靠左的学名和一行高的栏距确定。
        scientific = [r for r in result if r.get("page") == page and r.get("structured_name_column") == "scientific"]
        common_right = min(r["bbox"][0] for r in scientific) - line_height
        for row in result:
            if row.get("page") != page or row.get("structured_name_column") != "common" or row is left or row is right:
                continue
            box = row.get("original_layout_bbox") or row["bbox"]
            if box[2] < common_right and not row.get("name_column_ambiguity"):
                row["name_column_layout_bbox"] = [box[0], box[1], common_right, box[3]]
    for order, row in enumerate(result):
        row["reading_order"] = order
    return result
