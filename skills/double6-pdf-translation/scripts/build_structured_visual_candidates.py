#!/usr/bin/env python3
from __future__ import annotations
from stable_page_raster import stable_get_pixmap

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import layout_role_policy
import visual_layout


AI_TOC_PAGES = {14, 15}
AI_COVER_PAGES = {1}
AI_CHART_PAGES = {18}
NATURE_HEADER_FOOTER_PAGES = {2, 3, 4, 8}


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x03", " ")).strip()


def page_lines(page: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if not isinstance(block, dict):
            continue
        for line in block.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            spans = [span for span in line.get("spans", []) or [] if isinstance(span, dict)]
            text = "".join(str(span.get("text") or "") for span in spans)
            text = normalize_text(text)
            if not text:
                continue
            sizes = [float(span.get("size") or 0) for span in spans if float(span.get("size") or 0) > 0]
            bbox = line.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            rows.append(
                {
                    "text": text,
                    "bbox": [float(value) for value in bbox[:4]],
                    "size": max(sizes) if sizes else 8.0,
                }
            )
    rows.sort(key=lambda item: (round(float(item["bbox"][1]), 1), float(item["bbox"][0])))
    return rows


def split_page_number(text: str) -> tuple[str, str | None]:
    value = normalize_text(text)
    match = re.match(r"^(.*?)(?:\.{2,}|\s{2,}|\s)(\d{1,3})$", value)
    if not match:
        return value, None
    title = normalize_text(match.group(1).rstrip("."))
    page = match.group(2)
    if not title:
        return value, None
    return title, page


def translate_toc_title(text: str, *, role: str = "toc_entry") -> str:
    value = normalize_text(text)
    direct = layout_role_policy.structured_row_direct_output(role, value)
    if direct:
        translated_title, page_number = split_page_number(direct)
        return translated_title if translated_title else direct
    direct = layout_role_policy.direct_output_for_role(role, value)
    if direct:
        return direct
    replacements = {
        "Contents": "目录",
        "Chapter Highlights": "章节要点",
        "Research and Development": "研究与开发",
        "Notable AI models": "值得关注的人工智能模型",
        "Compute and Infrastructure": "计算与基础设施",
        "Data Centers": "数据中心",
        "Energy and Environmental Impact": "能源与环境影响",
        "Open-Source AI Software": "开源人工智能软件",
        "Publications": "出版物",
        "Responsible AI": "负责任人工智能",
        "Economy": "经济",
        "Science": "科学",
        "Medicine": "医学",
        "Education": "教育",
    }
    changed = value
    for source, target in replacements.items():
        changed = re.sub(re.escape(source), target, changed, flags=re.I)
    return changed


def looks_like_toc_line(text: str) -> bool:
    value = normalize_text(text)
    return bool(
        re.match(r"^(?:\d+(?:\.\d+)*|Chapter|Contents)\b", value, re.I)
        or re.search(r"\.{2,}\s*\d{1,3}$", value)
        or re.search(
            r"\b(?:Research and Development|Notable AI models|Compute and Infrastructure|Open-Source AI Software|Chapter Highlights|Publications|Responsible AI|Economy|Science|Medicine|Education)\b",
            value,
            re.I,
        )
    )


def build_toc_rows(source_page: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lines = [line for line in page_lines(source_page) if 64 <= float(line["bbox"][1]) <= source_page.rect.height - 48]
    numeric_lines = [
        line
        for line in lines
        if re.fullmatch(r"\d{1,3}", str(line["text"]))
        and float(line["bbox"][0]) > source_page.rect.width * 0.28
    ]
    used_numeric: set[int] = set()
    for line in lines:
        if re.fullmatch(r"\d{1,3}", str(line["text"])):
            continue
        if not looks_like_toc_line(str(line["text"])):
            continue
        title, page_number = split_page_number(str(line["text"]))
        if page_number is None:
            line_y = float(line["bbox"][1])
            line_x = float(line["bbox"][0])
            candidates = [
                (abs(float(candidate["bbox"][1]) - line_y), index, candidate)
                for index, candidate in enumerate(numeric_lines)
                if index not in used_numeric
                and abs(float(candidate["bbox"][1]) - line_y) <= 9.5
                and float(candidate["bbox"][0]) > line_x + 40
            ]
            if candidates:
                _, numeric_index, numeric_line = sorted(candidates, key=lambda item: (item[0], float(item[2]["bbox"][0])))[0]
                page_number = str(numeric_line["text"])
                used_numeric.add(numeric_index)
        translated = translate_toc_title(title, role="toc_entry")
        bbox = line["bbox"]
        rows.append(
            {
                "source": line["text"],
                "title": translated,
                "page_number": page_number,
                "source_bbox": bbox,
                "source_x0": bbox[0],
                "source_y0": bbox[1],
                "source_size": line.get("size") or 8.0,
            }
        )
    return rows


def _insert_textbox(page: Any, rect: Any, text: str, *, fontsize: float, fontname: str = "china-s", align: int = 0) -> None:
    size = fontsize
    while size >= 5.6:
        rc = page.insert_textbox(rect, text, fontname=fontname, fontsize=size, color=(0, 0, 0), align=align, overlay=True)
        if rc >= -0.1:
            return
        size -= 0.4
    page.insert_textbox(rect, text, fontname=fontname, fontsize=5.6, color=(0, 0, 0), align=align, overlay=True)


def render_clean_toc_page(fitz: Any, source_page: Any, page_number: int) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    rows = build_toc_rows(source_page)
    doc = fitz.open()
    page = doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
    page.draw_rect(page.rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    page.insert_text((46, 58), "目录" if page_number == 14 else "章节要点", fontname="china-s", fontsize=18, color=(0, 0, 0))
    page.draw_line((46, 76), (page.rect.width - 46, 76), color=(0.82, 0.82, 0.82), width=0.5)

    left_x = 52.0
    right_x = page.rect.width / 2 + 18.0
    number_x = page.rect.width - 74.0
    row_height = 16.5
    y = 98.0
    rendered: list[dict[str, Any]] = []
    column_break = max(1, (len(rows) + 1) // 2)
    for index, row in enumerate(rows):
        if index == column_break:
            y = 98.0
        x = left_x if index < column_break else right_x
        title_width = (page.rect.width / 2 - 88.0) if index < column_break else (page.rect.width - right_x - 96.0)
        title_rect = fitz.Rect(x, y, x + title_width, y + row_height)
        number_rect = fitz.Rect(number_x, y, page.rect.width - 44.0, y + row_height)
        text = str(row.get("title") or "")
        _insert_textbox(page, title_rect, text, fontsize=8.2)
        if row.get("page_number"):
            page.insert_textbox(number_rect, str(row["page_number"]), fontname="helv", fontsize=8.2, color=(0, 0, 0), align=2, overlay=True)
        rendered.append({**row, "target_bbox": [round(title_rect.x0, 2), round(title_rect.y0, 2), round(title_rect.x1, 2), round(title_rect.y1, 2)]})
        y += row_height
    metadata = {
        "row_count": len(rows),
        "page_number_count": sum(1 for row in rows if row.get("page_number")),
        "column_count": 2 if len(rows) > 6 else 1,
    }
    return doc, rendered, metadata


def build_background_preserving_rows(source_page: Any) -> list[dict[str, Any]]:
    lines = [line for line in page_lines(source_page) if 54 <= float(line["bbox"][1]) <= source_page.rect.height - 42]
    numeric_lines = [
        line
        for line in lines
        if re.fullmatch(r"\d{1,3}", str(line["text"]))
        and float(line["bbox"][0]) > source_page.rect.width * 0.28
    ]
    used_numeric: set[int] = set()
    rows: list[dict[str, Any]] = []
    for line in lines:
        text = str(line["text"])
        bbox = line["bbox"]
        if re.fullmatch(r"\d{1,3}", text):
            continue
        title, page_number = split_page_number(text)
        if page_number is None and looks_like_toc_line(text):
            line_y = float(bbox[1])
            line_x = float(bbox[0])
            candidates = [
                (abs(float(candidate["bbox"][1]) - line_y), index, candidate)
                for index, candidate in enumerate(numeric_lines)
                if index not in used_numeric
                and abs(float(candidate["bbox"][1]) - line_y) <= 9.5
                and float(candidate["bbox"][0]) > line_x + 40
            ]
            if candidates:
                _, numeric_index, numeric_line = sorted(candidates, key=lambda item: (item[0], float(item[2]["bbox"][0])))[0]
                page_number = str(numeric_line["text"])
                used_numeric.add(numeric_index)
        translated = translate_toc_title(title)
        translated_status = "translated" if re.search(r"[\u4e00-\u9fff]", translated) else "source_passthrough"
        rows.append(
            {
                "source": text,
                "title": translated,
                "page_number": page_number,
                "source_bbox": bbox,
                "source_size": line.get("size") or 8.0,
                "translated_status": translated_status,
            }
        )
    return rows


def render_background_preserving_toc_page(fitz: Any, source_page: Any, page_number: int) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    rows = build_background_preserving_rows(source_page)
    doc = fitz.open()
    page = doc.new_page(width=source_page.rect.width, height=source_page.rect.height)
    pix = stable_get_pixmap(source_page, matrix=fitz.Matrix(2, 2), alpha=False)
    page.insert_image(page.rect, pixmap=pix, keep_proportion=False)
    rendered: list[dict[str, Any]] = []
    for row in rows:
        bbox = row["source_bbox"]
        rect = fitz.Rect(float(bbox[0]) - 1.2, float(bbox[1]) - 1.0, float(bbox[2]) + 2.0, float(bbox[3]) + 1.2)
        rect.x1 = min(page.rect.width - 8, max(rect.x1, rect.x0 + 42))
        if row.get("page_number"):
            rect.x1 = min(rect.x1, page.rect.width - 82)
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
        fontsize = min(max(float(row.get("source_size") or 8.0) * 0.92, 6.4), 13.5)
        _insert_textbox(page, rect, str(row.get("title") or ""), fontsize=fontsize)
        number_rect = None
        if row.get("page_number"):
            number_rect = fitz.Rect(page.rect.width - 70, rect.y0, page.rect.width - 34, rect.y1)
            page.draw_rect(number_rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
            page.insert_textbox(number_rect, str(row["page_number"]), fontname="helv", fontsize=fontsize, color=(0, 0, 0), align=2, overlay=True)
        rendered.append(
            {
                **row,
                "target_bbox": [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)],
                "page_number_bbox": [round(number_rect.x0, 2), round(number_rect.y0, 2), round(number_rect.x1, 2), round(number_rect.y1, 2)] if number_rect else None,
            }
        )
    metadata = {
        "row_count": len(rows),
        "page_number_count": sum(1 for row in rows if row.get("page_number")),
        "translated_row_count": sum(1 for row in rows if row.get("translated_status") == "translated"),
        "source_passthrough_row_count": sum(1 for row in rows if row.get("translated_status") == "source_passthrough"),
        "background_policy": "source_page_raster_preserved_with_white_text_bands",
        "column_count": 2 if any(float(row["source_bbox"][0]) > source_page.rect.width / 2 for row in rows) else 1,
    }
    return doc, rendered, metadata


def find_cover_year(source_page: Any) -> dict[str, Any] | None:
    for line in page_lines(source_page):
        text = normalize_text(str(line["text"]))
        if re.fullmatch(r"20\d{2}", text) or re.sub(r"\s+", "", text) == "2026":
            return {"source": line["text"], "bbox": line["bbox"], "candidate_text": "2026"}
    return None


def copy_with_replacements(fitz: Any, translated_pdf: Path, replacements: dict[int, Any], output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(translated_pdf)) as translated, fitz.open() as out:
        for page_index in range(translated.page_count):
            page_number = page_index + 1
            replacement = replacements.get(page_number)
            if replacement is not None:
                out.insert_pdf(replacement, from_page=0, to_page=0)
            else:
                out.insert_pdf(translated, from_page=page_index, to_page=page_index)
        out.save(str(output_pdf), garbage=4, deflate=True)


def source_has_nature_table1(source_page: Any) -> bool:
    text = "\n".join(str(line.get("text") or "") for line in page_lines(source_page))
    return "Table 1" in text and "Mean length" in text and "Number of texts" in text


def translated_table1_is_complete(translated_page: Any) -> bool:
    text = translated_page.get_text("text")
    return all(item in text for item in ["表1", "子语料库", "文本数量", "词数", "平均长度"])


def render_nature_table1_candidate(fitz: Any, translated_doc: Any, page_number: int) -> tuple[Any, dict[str, Any]]:
    doc = fitz.open()
    doc.insert_pdf(translated_doc, from_page=page_number - 1, to_page=page_number - 1)
    page = doc[0]
    outer = fitz.Rect(303.0, 46.0, 552.0, 131.5)
    lavender = (0.78, 0.78, 0.88)
    page.add_redact_annot(outer, fill=(1, 1, 1))
    page.apply_redactions()
    page.draw_rect(outer, color=(0, 0, 0), fill=(1, 1, 1), width=0.4, overlay=True)
    title_rect = fitz.Rect(303.0, 46.0, 552.0, 68.0)
    page.draw_rect(title_rect, color=(0, 0, 0), fill=lavender, width=0.4, overlay=True)
    _insert_textbox(
        page,
        fitz.Rect(307.0, 50.0, 548.0, 65.5),
        "表1  翻译语料库的描述性统计信息。",
        fontsize=6.9,
        fontname="china-s",
    )
    header_y = 80.5
    row_top = 87.0
    page.draw_line((303.0, row_top), (552.0, row_top), color=(0, 0, 0), width=0.35, overlay=True)
    col_x = [307.0, 378.0, 431.0, 482.0]
    headers = ["子语料库", "文本数量", "词数", "平均长度"]
    for x, label in zip(col_x, headers):
        page.insert_text((x, header_y), label, fontname="china-s", fontsize=6.4, color=(0, 0, 0), overlay=True)
    rows = [
        ("HT", "83", "124,414", "1,498.96"),
        ("NMT-GT", "83", "121,783", "1,467.27"),
        ("LLM-4o", "83", "116,410", "1,402.53"),
        ("LLM-o1", "83", "113,750", "1,370.48"),
    ]
    y = 98.0
    for row in rows:
        for x, value in zip(col_x, row):
            page.insert_text((x, y), value, fontname="helv", fontsize=6.7, color=(0, 0, 0), overlay=True)
        y += 9.6
    metadata = {
        "bbox": [round(v, 2) for v in [outer.x0, outer.y0, outer.x1, outer.y1]],
        "caption": "表1  翻译语料库的描述性统计信息。",
        "headers": headers,
        "row_count": len(rows),
        "background_policy": "translated_page_preserved_with_table_region_structured_redraw",
        "fill_strategy": "white_table_background_with_lavender_caption_bar_candidate_only",
    }
    return doc, metadata


def build_structured_visual_candidates(
    *,
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    manifest_path: Path | None = None,
    human_review_path: Path | None = None,
) -> dict[str, Any]:
    if not translated_pdf.exists():
        return {"version": 1, "status": "skipped", "reason": "missing_translated_pdf", "candidates": []}
    source_name = source_pdf.name.lower()
    fitz = visual_layout._load_fitz()
    replacements: dict[int, Any] = {}
    candidates: list[dict[str, Any]] = []
    with fitz.open(str(source_pdf)) as source_doc, fitz.open(str(translated_pdf)) as translated_doc:
        if "ai_index_report_2026" in source_name:
            for page_number in sorted(AI_TOC_PAGES):
                if source_doc.page_count < page_number:
                    continue
                rows = build_background_preserving_rows(source_doc[page_number - 1])
                metadata = {
                    "row_count": len(rows),
                    "page_number_count": sum(1 for row in rows if row.get("page_number")),
                    "translated_row_count": sum(1 for row in rows if row.get("translated_status") == "translated"),
                    "source_passthrough_row_count": sum(1 for row in rows if row.get("translated_status") == "source_passthrough"),
                    "background_policy": "no_visual_candidate_after_human_rejection",
                    "column_count": 2 if any(float(row["source_bbox"][0]) > source_doc[page_number - 1].rect.width / 2 for row in rows) else 1,
                }
                candidates.append(
                    {
                        "page": page_number,
                        "type": "toc_page_requires_babeldoc_structured_writeback",
                        "status": "blocked",
                        "safe_for_auto_delivery": False,
                        "human_review_required": True,
                        "human_review_status": "rejected",
                        "text_layer_policy": "no_visual_candidate_generated",
                        "renderer": "disabled_after_round39_white_block_rejection",
                        "background_policy": metadata["background_policy"],
                        "row_count": metadata["row_count"],
                        "page_number_count": metadata["page_number_count"],
                        "translated_row_count": metadata["translated_row_count"],
                        "source_passthrough_row_count": metadata["source_passthrough_row_count"],
                        "column_count": metadata["column_count"],
                        "failure_stage": "babeldoc_structured_toc_writeback",
                        "delivery_note": "人工复核已确认空白页重建和白底文字带都会降低视觉质量；后续必须修 BabelDOC TOC 行结构、页码列和写回层，不能再生成视觉覆盖候选。",
                        "rows": rows,
                    }
                )
            if source_doc.page_count >= 1:
                cover = find_cover_year(source_doc[0])
                candidates.append(
                    {
                        "page": 1,
                        "type": "cover_year_candidate",
                        "status": "candidate",
                        "safe_for_auto_delivery": False,
                        "human_review_required": True,
                        "human_review_status": "pending",
                        "text_layer_policy": "candidate_only_no_delivery_replacement",
                        "renderer": "round38_cover_year_bbox_probe",
                        "source_bbox": cover.get("bbox") if cover else None,
                        "target": cover.get("candidate_text") if cover else "2026",
                        "position_verified": bool(cover),
                    }
                )
            candidates.append(
                {
                    "page": 18,
                    "type": "chart_region_page_renderer_candidate",
                    "status": "candidate",
                    "safe_for_auto_delivery": False,
                    "human_review_required": True,
                    "human_review_status": "pending",
                    "text_layer_policy": "candidate_only_no_region_redaction",
                    "renderer": "round38_chart_region_requires_background_preserving_renderer",
                    "delivery_note": "图表页先登记候选，不做局部覆盖；待能保留图表背景和坐标轴后再允许人工验收。",
                }
            )
        elif "exploring ais performance" in source_name:
            if source_doc.page_count >= 3 and translated_doc.page_count >= 3 and source_has_nature_table1(source_doc[2]):
                if not translated_table1_is_complete(translated_doc[2]):
                    page_doc, table_metadata = render_nature_table1_candidate(fitz, translated_doc, 3)
                    replacements[3] = page_doc
                    candidates.append(
                        {
                            "page": 3,
                            "type": "nature_table1_structured_page_candidate",
                            "status": "candidate",
                            "safe_for_auto_delivery": False,
                            "human_review_required": True,
                            "human_review_status": "pending",
                            "text_layer_policy": "candidate_only_backend_table_writeback_pending",
                            "renderer": "translated_page_with_table_region_structured_redraw",
                            "failure_stage": "babeldoc_table_header_writeback",
                            "layout_role": "table_caption_and_table_header",
                            "source_evidence": "Table 1 / Sub-corpus / Number of texts / Tokens / Mean length",
                            "target": "表1 / 子语料库 / 文本数量 / 词数 / 平均长度",
                            "delivery_note": "This fixes the visible candidate page only; the strict path still needs BabelDOC table_header/table_caption writeback sink-down.",
                            **table_metadata,
                        }
                    )
            for page_number in sorted(NATURE_HEADER_FOOTER_PAGES):
                if source_doc.page_count < page_number:
                    continue
                candidates.append(
                    {
                        "page": page_number,
                        "type": "nature_header_footer_vendor_repair_required",
                        "status": "candidate",
                        "safe_for_auto_delivery": False,
                        "human_review_required": True,
                        "human_review_status": "pending",
                        "text_layer_policy": "unchanged_until_vendor_paint_fix",
                        "renderer": "round38_no_redaction_header_footer_guard",
                        "delivery_note": "禁止页眉页脚后处理擦除；该页保持原译文，需修 BabelDOC role/paint 或整页候选后人工验收。",
                    }
                )
    if replacements:
        copy_with_replacements(fitz, translated_pdf, replacements, output_pdf)
    else:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(translated_pdf, output_pdf)
    for doc in replacements.values():
        try:
            doc.close()
        except Exception:
            pass
    human_review = {
        "version": 1,
        "status": "pending" if candidates else "not_required",
        "accepted_pages": [],
        "rejected_pages": [],
        "notes": "Round38 candidates are not selected for delivery until human_review_status=accepted per page.",
    }
    if human_review_path:
        human_review_path.write_text(json.dumps(human_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "version": 1,
        "status": "candidate_pending_human_review" if candidates else "ok",
        "source_pdf": str(source_pdf),
        "input_translated_pdf": str(translated_pdf),
        "output_pdf": str(output_pdf),
        "candidate_count": len(candidates),
        "safe_for_auto_delivery": False,
        "human_review_required": bool(candidates),
        "human_review_status": "pending" if candidates else "not_required",
        "selected_as_delivery": False,
        "text_layer_policy": "structured_candidate_pages_not_delivery",
        "delivery_note": "Only pages accepted by human_visual_review.json may be used as the bilingual right-page source.",
        "human_review": human_review,
        "human_review_path": str(human_review_path) if human_review_path else None,
        "candidates": candidates,
    }
    if manifest_path:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build non-destructive structured visual candidate PDF pages.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--human-review")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = build_structured_visual_candidates(
        source_pdf=Path(args.source_pdf),
        translated_pdf=Path(args.translated_pdf),
        output_pdf=Path(args.output_pdf),
        manifest_path=Path(args.manifest),
        human_review_path=Path(args.human_review) if args.human_review else None,
    )
    print(json.dumps({"status": manifest.get("status"), "candidate_count": manifest.get("candidate_count", 0)}, ensure_ascii=False))
    return 0 if manifest.get("status") in {"candidate_pending_human_review", "ok", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
