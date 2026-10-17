# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout core：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def pdf_identity(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def graphic_paint_profile(page: Any) -> dict[str, Any]:
    """图像/路径的绘制边界是否落在页面内；不证明遮挡、裁剪或内容完整。"""
    from visual_layout_extract import _load_fitz
    fitz = _load_fitz()
    kinds = {"fill-path", "stroke-path", "fill-image", "fill-shade"}
    counts = {kind: {"significant": 0, "outside": 0, "outside_area": 0.0} for kind in sorted(kinds)}
    samples = []
    try:
        log = page.get_bboxlog()
        if len(log) > 50000:
            return {"status": "unavailable", "reason": "paint_operation_limit", "limit": 50000}
        # bboxlog按未旋转页坐标返回，页面旋转后再与可见页比较；容忍2pt出血边。
        visible = page.rect + (-2, -2, 2, 2)
        for item in log:
            kind, values = item[:2]
            if kind not in kinds:
                continue
            if len(values) != 4 or not all(math.isfinite(float(v)) for v in values):
                return {"status": "unavailable", "reason": "invalid_paint_bbox"}
            box = fitz.Rect(values) * page.rotation_matrix
            area = float(box.get_area())
            if not all(math.isfinite(v) for v in [*box, area]):
                return {"status": "unavailable", "reason": "nonfinite_transformed_paint_bbox"}
            if box.width < 1 or box.height < 1 or area < 36:
                continue
            counts[kind]["significant"] += 1
            if (box & visible).get_area() <= 0:
                counts[kind]["outside"] += 1
                counts[kind]["outside_area"] += area
                if len(samples) < 12:
                    samples.append({"kind": kind, "bbox": list(box), "area": area})
        return {"status": "ok", "counts": counts, "outside_samples": samples,
                "page_area": float(page.rect.get_area()), "operation_count": len(log),
                "scope": "significant paint bboxes entirely outside page plus 2pt tolerance; not occlusion or clipping acceptance"}
    except Exception as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}


def graphic_visibility_findings(source: dict, target: dict, page_number: int | str) -> list[dict]:
    a, b = source.get("graphic_paint"), target.get("graphic_paint")
    if a is None and b is None:
        return []  # 兼容已有只含文字的单元输入，不把缺少测量当作通过证据。
    if not a or not b or a.get("status") != "ok" or b.get("status") != "ok":
        return [{"severity": "warn", "category": "rendering", "rule": "graphic_visibility_unavailable",
                 "page": page_number, "message": "未取得完整图形绘制边界，不能确认整图仍在可见页内。"}]
    increases = []
    for kind, row in b["counts"].items():
        baseline = a["counts"].get(kind, {})
        count_delta = row["outside"] - baseline.get("outside", 0)
        area_delta = row["outside_area"] - baseline.get("outside_area", 0)
        if count_delta > 0 and area_delta >= 36:
            increases.append({"kind": kind, "additional_outside_count": count_delta, "additional_outside_area": area_delta})
    if not increases:
        return []
    substantial = sum(x["additional_outside_area"] for x in increases) >= max(36, b["page_area"] * .0025)
    return [{"severity": "blocking" if substantial else "warn", "category": "rendering",
             "rule": "graphics_moved_outside_page", "page": page_number,
             "message": "译文新增完全位于页外的图像或路径；对象计数及文字完整不能证明图仍可见，须核对Form坐标变换与页面。",
             "increases": increases, "outside_samples": b["outside_samples"],
             "limitation": "paint bbox comparison; does not detect every deleted, occluded, clipped or partially displaced figure"}]

def normalize_lines(text: str) -> list[str]:
    text = text.replace("\x03", " ")
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]

def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))

def ascii_word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z-]{1,}\b", text))

def extract_key_texts(source_pages: list[dict[str, Any]], limit: int = 12) -> list[str]:
    keys: list[str] = []
    for page in source_pages[:3]:
        text = str(page.get("text") or "")
        for year in re.findall(r"\b20\d{2}\b", text):
            if year not in keys:
                keys.append(year)
        for line in normalize_lines(text):
            if 8 <= len(line) <= 80 and (line.istitle() or line.isupper()):
                if line not in keys:
                    keys.append(line)
            if len(keys) >= limit:
                return keys
    return keys

def dominant_color_ratio(page: dict[str, Any], color: int) -> float:
    spans = page.get("spans")
    spans = spans if isinstance(spans, list) else []
    if not spans:
        return 0.0
    matches = sum(1 for span in spans if isinstance(span, dict) and int(span.get("color") or 0) == color)
    return matches / len(spans)

def nonblack_color_ratio(page: dict[str, Any]) -> float:
    spans = page.get("spans")
    spans = spans if isinstance(spans, list) else []
    if not spans:
        return 0.0
    matches = sum(1 for span in spans if isinstance(span, dict) and int(span.get("color") or 0) != 0)
    return matches / len(spans)

def bbox_overlap_ratio(box_a: list[float], box_b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax1, bx1)
    y1 = min(ay1, by1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = max((ax1 - ax0) * (ay1 - ay0), 1.0)
    area_b = max((bx1 - bx0) * (by1 - by0), 1.0)
    return inter / min(area_a, area_b)

def bbox_overlap_area(box_a: list[float], box_b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax1, bx1)
    y1 = min(ay1, by1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return round((x1 - x0) * (y1 - y0), 3)

def is_code_placeholder_span_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if stripped in {"...", "…"}:
        return True
    if VISIBLE_LATEX_COMMAND_RE.search(stripped):
        return True
    if re.fullmatch(r"\\[A-Za-z@]+\*?(?:\{[^{}]*\})?", stripped):
        return True
    return False

def should_ignore_overlap_pair(span_a: dict[str, Any], span_b: dict[str, Any]) -> bool:
    text_a = re.sub(r"\s+", " ", str(span_a.get("text") or "")).strip()
    text_b = re.sub(r"\s+", " ", str(span_b.get("text") or "")).strip()
    if is_code_placeholder_span_text(text_a) and is_code_placeholder_span_text(text_b):
        return True
    # Visual repair can repaint a short section heading over a stale text layer.
    # The text layer then contains overlapping identical heading spans, but the
    # visible page is not a paragraph collision.
    if text_a == text_b and len(text_a) <= 24 and HEADING_TEXT_RE.fullmatch(text_a):
        return True
    return False

def count_overlapping_spans(page: dict[str, Any], threshold: float = 0.55) -> int:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    count = 0
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) == 4 and bbox_overlap_ratio(box_a, box_b) >= threshold and not should_ignore_overlap_pair(span, other):
                count += 1
                break
    return count

def total_overlapping_area(page: dict[str, Any], threshold: float = 0.55) -> float:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    total = 0.0
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) == 4 and bbox_overlap_ratio(box_a, box_b) >= threshold and not should_ignore_overlap_pair(span, other):
                total += bbox_overlap_area(box_a, box_b)
    return round(total, 3)

def overlap_pair_samples(page: dict[str, Any], threshold: float = 0.55, limit: int = 12) -> list[dict[str, Any]]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    pairs: list[dict[str, Any]] = []
    for index, span in enumerate(spans):
        box_a = span["bbox"]
        if len(box_a) != 4:
            continue
        for other in spans[index + 1 :]:
            box_b = other["bbox"]
            if len(box_b) != 4:
                continue
            ratio = bbox_overlap_ratio(box_a, box_b)
            if ratio >= threshold and not should_ignore_overlap_pair(span, other):
                pairs.append(
                    {
                        "text_a": str(span.get("text") or "")[:80],
                        "text_b": str(other.get("text") or "")[:80],
                        "bbox_a": box_a,
                        "bbox_b": box_b,
                        "overlap_ratio": round(ratio, 3),
                        "overlap_area": bbox_overlap_area(box_a, box_b),
                    }
                )
                if len(pairs) >= limit:
                    return pairs
    return pairs

def infer_failure_stage(rule: str, category: str, message: str = "") -> str:
    value = " ".join([rule, category, message]).lower()
    if any(token in value for token in ["extract", "text_layer", "glyph", "tounicode", "ocr"]):
        return "parse"
    if any(token in value for token in ["reading_order", "toc", "role", "header", "footer", "caption", "section_heading"]):
        return "layout"
    if any(token in value for token in ["untranslated", "translated", "terminology", "example", "references_body"]):
        return "translate"
    if any(token in value for token in ["overlap", "bbox", "tiny_font", "page_count", "drift", "reflow"]):
        return "typeset"
    if any(token in value for token in ["color", "contrast", "font"]):
        return "paint"
    if any(token in value for token in ["dual", "left", "right", "composite"]):
        return "composite"
    return "unknown"

def infer_layout_role(rule: str, message: str = "") -> str:
    value = " ".join([rule, message]).lower()
    if "table" in value or "chart" in value:
        return "table_or_chart"
    if "formula" in value or "latex" in value:
        return "formula_or_tex"
    if "caption" in value:
        return "caption"
    if "foot" in value or "affiliation" in value or "email" in value:
        return "footnote_or_footer"
    if "header" in value:
        return "header"
    if "reference" in value:
        return "references"
    if "title" in value or "heading" in value:
        return "heading"
    if "example" in value or "st/" in value or "ht/" in value:
        return "example_or_parallel_text"
    return "main_text"

def infer_cause_category(rule: str, message: str = "", failure_stage: str = "") -> str:
    value = " ".join([rule, message, failure_stage]).lower()
    if any(
        token in value
        for token in [
            "person_name",
            "citation",
            "running_header",
            "signature",
            "references",
            "example",
            "st/",
            "ht/",
            "llm",
            "chart_title",
            "role",
        ]
    ):
        return "backend_role_classification"
    if any(token in value for token in ["tiny_font", "font_size", "overflow", "wrap", "line_break", "reflow", "bbox", "overlap"]):
        return "typeset_reflow"
    if any(
        token in value
        for token in [
            "image",
            "background",
            "portrait",
            "avatar",
            "rule_line",
            "underline",
            "link",
            "annotation",
            "color",
            "paint",
            "composite",
            "right_page",
            "dual",
        ]
    ):
        return "paint_composite"
    if any(token in value for token in ["artifact", "manifest", "report", "stale", "cached", "delivery_pdf", "source_of_truth"]):
        return "artifact_selection_report_drift"
    if failure_stage == "translate":
        return "backend_role_classification"
    if failure_stage == "typeset":
        return "typeset_reflow"
    if failure_stage in {"paint", "composite"}:
        return "paint_composite"
    return "needs_local_verification"

def infer_user_feedback_layout_role(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ["人名", "姓名", "citation", "引用", "作者"]):
        return "citation_or_person_names"
    if any(token in value for token in ["图表标题", "图题", "figure", "chart title"]):
        return "chart_title"
    if any(token in value for token in ["图像", "图片", "头像", "背景"]):
        return "background_or_image"
    if any(token in value for token in ["链接", "下划线", "uri", "url"]):
        return "link_or_annotation"
    if any(token in value for token in ["页眉", "header"]):
        return "running_header"
    if any(token in value for token in ["页脚", "脚注", "横线", "footer", "footnote"]):
        return "footnote_or_footer"
    if any(token in value for token in ["署名", "签名", "co-chair", "主席"]):
        return "signature"
    if any(token in value for token in ["目录", "contents", "toc"]):
        return "toc_or_chapter_index"
    if any(token in value for token in ["字体", "字号", "加粗", "颜色", "换行", "溢出"]):
        return "body_or_heading_text"
    return "main_text"

def normalize_user_visual_feedback(text: str, *, default_page: int | str = "global") -> dict[str, Any]:
    page_match = re.search(r"第\s*(\d+)\s*页|p(?:age)?\.?\s*(\d+)", text, flags=re.I)
    page: int | str = int(next(group for group in page_match.groups() if group)) if page_match else default_page
    layout_role = infer_user_feedback_layout_role(text)
    if layout_role in {"citation_or_person_names", "signature", "running_header", "chart_title"}:
        cause_category = "backend_role_classification"
    elif layout_role in {"background_or_image", "link_or_annotation", "footnote_or_footer"}:
        cause_category = "paint_composite"
    elif any(token in text for token in ["字号", "字体", "换行", "溢出", "加粗"]):
        cause_category = "typeset_reflow"
    elif any(token in text.lower() for token in ["manifest", "artifact", "报告", "旧候选", "最终交付"]):
        cause_category = "artifact_selection_report_drift"
    else:
        cause_category = "needs_local_verification"
    repair_target = {
        "backend_role_classification": "layout_role_policy / backend tracking / visible repair rule",
        "typeset_reflow": "BabelDOC typesetting / paragraph reflow / visible candidate bbox",
        "paint_composite": "PDF paint/composite / annotations / source region copy",
        "artifact_selection_report_drift": "artifact index / render manifest / report source-of-truth",
        "needs_local_verification": "screenshot + PyMuPDF local audit",
    }[cause_category]
    return {
        "version": 1,
        "page": page,
        "region": None,
        "layout_role": layout_role,
        "symptom": text,
        "expected": "与源 PDF 对应区域的结构、字体、颜色、图层和 protected text policy 保持一致。",
        "cause_category": cause_category,
        "repair_target": repair_target,
        "verification": ["source_vs_candidate_screenshot", "pymupdf_text_bbox_font_color", "manifest_rule_check"],
    }

def normalize_finding(finding: dict[str, Any] | str, default_page: int | str = "global") -> dict[str, Any]:
    if isinstance(finding, str):
        item: dict[str, Any] = {"rule": "visual_layout_note", "message": finding}
    else:
        item = dict(finding)
    rule = str(item.get("rule") or item.get("category") or "visual_layout_issue")
    severity = str(item.get("severity") or "")
    if severity in {"high", "critical"}:
        severity = "blocking"
    elif severity in {"medium", "low"}:
        severity = "warn" if severity == "medium" else "cosmetic"
    if not severity:
        severity = "blocking" if rule in {"text_overlap", "page_count_drift", "key_text_missing"} else "warn"
    item["severity"] = severity
    item["layer"] = item.get("layer") or "pdf_rendering"
    item["page"] = item.get("page") or default_page
    category = str(item.get("category") or "")
    message = str(item.get("message") or item.get("evidence") or "")
    item["failure_stage"] = item.get("failure_stage") or infer_failure_stage(rule, category, message)
    item["layout_role"] = item.get("layout_role") or infer_layout_role(rule, message)
    item["cause_category"] = item.get("cause_category") or infer_cause_category(rule, message, str(item["failure_stage"]))
    item["repair_target"] = item.get("repair_target") or {
        "parse": "PDF text extraction / OCR / ToUnicode layer",
        "layout": "LayoutParser / ParagraphFinder / role classification",
        "translate": "layout_role_policy / translator prompt / protected passthrough",
        "typeset": "BabelDOC Typesetting / paragraph split / bbox fit",
        "paint": "FontMapper / color / contrast",
        "composite": "bilingual composer / final PDF assembly",
        "unknown": "manual triage",
    }.get(str(item["failure_stage"]), "manual triage")
    item["evidence"] = item.get("evidence") or item.get("message") or json.dumps({k: v for k, v in item.items() if k not in {"evidence", "recommendation"}}, ensure_ascii=False)
    item["recommendation"] = item.get("recommendation") or {
        "key_text_missing": "对照源页截图确认标题或关键年份是否被遮挡；必要时重渲染该页。",
        "color_palette_shift_to_black": "检查中文字体和颜色映射；必要时切换字体或回退为可读版 PDF。",
        "text_overlap": "重渲染该页并降低字号或调整段落 bbox 拆分。",
        "toc_line_count_dropped": "重新检查目录块顺序和页码行，必要时局部重渲染目录页。",
        "toc_page_number_count_dropped": "重新检查目录页右侧页码列是否被合并或丢失，必要时局部重渲染目录页。",
        "toc_numeric_order_unstable": "重新检查目录页阅读顺序和页码对齐。",
        "toc_alignment_drift": "重新检查目录页章节标题和页码列的左右对齐关系，必要时局部重渲染目录页。",
        "font_size_regression": "禁止通过过度缩小字号把译文硬塞回原 bbox；需重排段落或降低文本密度。",
        "header_footer_fragmented": "页眉页脚、邮箱或机构脚注应保护或整体处理，避免碎片化翻译。",
        "page_count_drift": "确认源译 PDF 页数是否漂移；漂移时不应判定渲染通过。",
    }.get(rule, "复核该视觉 finding 对应页，并决定局部重渲染或可读降级交付。")
    return item

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
