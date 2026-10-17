"""只对具有报告与作者资历线索的稀疏首页继承源文居中布局。"""
from __future__ import annotations

import copy
import re
import statistics


def prepare_centered_frontmatter(regions: list[dict]) -> list[dict]:
    result = copy.deepcopy(regions)
    rows = [r for r in result if r.get("page") == 1 and r.get("layout_role") == "text"
            and r.get("status") not in {"protected", "failed"}]
    rows = [r for r in rows if (w := r.get("preprocess", {}).get("page_width", 0))
            and .4 * w <= sum((r.get("original_layout_bbox") or r["bbox"])[::2]) / 2 <= .6 * w]
    if not 8 <= len(rows) <= 20:
        return result
    text = lambda r: str(r.get("normalized_text") or r.get("ocr_text") or "")
    if not any(re.fullmatch(r"(?:An?\s+)?(?:Interim\s+|Final\s+|Technical\s+)?Report", text(r).strip(), re.I) for r in rows):
        return result
    if sum(bool(re.search(r"\b(?:Ph\.?\s*D\.?|M\.?\s*S\.?)\b", text(r))) for r in rows) < 2:
        return result
    pre = rows[0].get("preprocess", {})
    width, height = pre.get("page_width", 0), pre.get("page_height", 0)
    if not width or not height:
        return result
    boxes = [r.get("original_layout_bbox") or r["bbox"] for r in rows]
    centers = [(b[0] + b[2]) / 2 for b in boxes]
    axis = statistics.median(centers)
    if not .4 * width <= axis <= .6 * width or max(centers) - min(centers) > .04 * width:
        return result
    if max(b[3] for b in boxes) - min(b[1] for b in boxes) < .5 * height:
        return result
    if any(len(text(r)) > 180 or not 1 <= len(r.get("source_line_evidence", [])) <= 4
           or b[2] - b[0] > .6 * width or b[3] - b[1] > .1 * height
           for r, b in zip(rows, boxes, strict=True)):
        return result
    for row in rows:
        row["frontmatter_alignment_policy"] = "sparse_report_author_fields_centered_v1"
        row["frontmatter_source_axis"] = axis
        row["translation_group_id"] = row["region_id"] + "-centered-field"
    return result
