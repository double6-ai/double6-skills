# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf nature：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_nature_header_footer(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, page_lines, replace_rect
    repairs: list[dict[str, Any]] = []
    clean_header = "人文与社会科学通讯 | https://doi.org/10.1057/s41599-026-06630-4"
    for page_number in {2, 4, 6, 8, 10, 12, 14}:
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        header_hits: list[Any] = []
        for row in page_lines(page):
            text = row["text"]
            bbox = row.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            y0 = float(bbox[1])
            is_mixed_footer = bool(
                re.search(
                    r"doi\.org|HUMANITIE|HUMANITIES AND SOCIAL SCIENCES COMMUNICATIONS|人文与社会科学通讯|社会科学与人文通讯",
                    text,
                    re.I,
                )
            )
            if not is_mixed_footer or y0 > 42:
                continue
            rect = expanded_rect(fitz, bbox, page, pad=1.5, min_width=80)
            if not rect:
                continue
            header_hits.append((text, rect))
        if not header_hits:
            continue
        union = header_hits[0][1]
        for _, rect in header_hits[1:]:
            union.include_rect(rect)
        union.x0 = min(union.x0, 180)
        union.x1 = min(page.rect.width - 35, max(union.x1, 545))
        union.y0 = max(12, union.y0 - 2)
        union.y1 = min(34, union.y1 + 2)
        meta = replace_rect(page, union, clean_header, fontsize=6.3)
        repairs.append(
            {
                "page": page_number,
                "rule": "nature_header_metadata_visible_repair",
                "source": " | ".join(text[:80] for text, _ in header_hits),
                "target": clean_header,
                **meta,
            }
        )
    return repairs


def repair_nature_header_footer_passthrough(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    for page_number in range(2, min(source_doc.page_count, doc.page_count) + 1):
        source_page = source_doc[page_number - 1]
        target_page = doc[page_number - 1]
        header_rect = fitz.Rect(38.0, 12.0, 558.0, 40.0)
        footer_rect = fitz.Rect(38.0, 742.0, 558.0, 764.0)
        for role, rect in [("header", header_rect), ("footer", footer_rect)]:
            _redact_with_fill(target_page, rect, (1, 1, 1))
            copied = True
            try:
                target_page.show_pdf_page(rect, source_doc, page_number - 1, clip=rect, overlay=True, keep_proportion=False)
            except Exception:
                copied = False
            repairs.append(
                {
                    "page": page_number,
                    "rule": "nature_header_footer_source_passthrough",
                    "source": f"source_{role}_region",
                    "target": f"passthrough_original_{role}_region",
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fill_strategy": "source_region_copy" if copied else "white_page_background_source_region_empty",
                    "font_policy": "preserve_source_header_footer_region_fonts",
                    "text_policy": "passthrough_original_metadata_region",
                }
            )
    return repairs

def repair_nature_tables(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, normalize_text, page_lines, replace_rect
    repairs: list[dict[str, Any]] = []
    caption_policy = {
        "font_policy": "match_source_table_caption_compact_6_6pt",
        "text_policy": "translate_table_caption_without_reflowing_table_grid",
        "backend_sink_down": "pending",
    }
    header_policy = {
        "font_policy": "match_source_table_header_compact_7_4pt",
        "text_policy": "translate_table_headers_preserve_column_semantics",
        "backend_sink_down": "pending",
    }
    replacements = {
        3: {
            "表1": "表1 翻译语料库的描述性统计信息。",
            "子语料库": "子语料库",
            "文本数量": "文本数量",
            "词数": "词数",
            "平均长度": "平均长度",
        },
        5: {
            "表2": "表2 六个语言维度上具有统计学显著性的成对差异数量。",
        },
    }
    for page_number, mapping in replacements.items():
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        for row in page_lines(page):
            text = normalize_text(row["text"])
            bbox = row.get("bbox")
            if not bbox:
                continue
            y0 = float(bbox[1])
            if page_number == 3 and y0 > 140:
                continue
            if page_number == 5 and not (330 <= y0 <= 400):
                continue
            for needle, target in mapping.items():
                if needle not in text:
                    continue
                rect = expanded_rect(fitz, bbox, page, pad=1.2, min_width=max(44, len(target) * 4.6))
                if not rect:
                    continue
                if needle.startswith("表"):
                    rect.x1 = min(page.rect.width - 35, max(rect.x1, rect.x0 + len(target) * 5.0))
                    rule = "nature_table_caption_visible_repair"
                    fontsize = 6.6
                    policy = caption_policy
                else:
                    rect.x1 = min(page.rect.width - 35, max(rect.x1, rect.x0 + len(target) * 6.8))
                    rule = "nature_table_header_visible_repair"
                    fontsize = 7.4
                    policy = header_policy
                meta = replace_rect(page, rect, target, fontsize=fontsize)
                repairs.append({"page": page_number, "rule": rule, "source": text[:120], "target": target, **meta, **policy})
                break
    fixed_insertions = [
        (3, "nature_table_caption_visible_repair", [306.5, 49.6, 520.0, 62.0], "表1 翻译语料库的描述性统计信息。", 6.6),
        (3, "nature_table_header_visible_repair", [305.5, 75.4, 352.0, 88.6], "子语料库", 7.4),
        (3, "nature_table_header_visible_repair", [369.2, 75.4, 416.0, 88.6], "文本数量", 7.4),
        (3, "nature_table_header_visible_repair", [451.1, 75.4, 498.0, 88.6], "词数", 7.4),
        (3, "nature_table_header_visible_repair", [502.0, 75.4, 549.0, 88.6], "平均长度", 7.4),
        (5, "nature_table_caption_visible_repair", [46.5, 355.4, 290.0, 368.4], "表2 六个语言维度上具有统计学显著性的成对差异数量。", 6.6),
    ]
    repaired_targets = {(int(item.get("page") or 0), str(item.get("target") or "")) for item in repairs}
    for page_number, rule, bbox, target, fontsize in fixed_insertions:
        if page_number > doc.page_count or (page_number, target) in repaired_targets:
            continue
        page = doc[page_number - 1]
        rect = expanded_rect(fitz, bbox, page, pad=0.8, min_width=40)
        if not rect:
            continue
        meta = replace_rect(page, rect, target, fontsize=fontsize)
        policy = caption_policy if rule == "nature_table_caption_visible_repair" else header_policy
        repairs.append({"page": page_number, "rule": rule, "source": "fixed_table_region", "target": target, **meta, **policy})
    return repairs


def _redact_with_fill(page: Any, rect: Any, fill: tuple[float, float, float] = (1, 1, 1)) -> None:
    try:
        page.add_redact_annot(rect, fill=fill)
        page.apply_redactions()
    except Exception:
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)

def draw_fake_bold_text(page: Any, point: tuple[float, float], text: str, *, fontsize: float, fontname: str = "china-s") -> None:
    page.insert_text(point, text, fontname=fontname, fontsize=fontsize, color=(0, 0, 0), overlay=True)

def draw_fake_bold_run(fitz: Any, page: Any, x: float, y: float, text: str, *, fontsize: float) -> float:
    draw_fake_bold_text(page, (x, y), text, fontsize=fontsize)
    try:
        return x + float(fitz.get_text_length(text, fontname="china-s", fontsize=fontsize))
    except Exception:
        return x + len(text) * fontsize * 0.52

def cover_heading_pixels(page: Any, rect: Any, *, fill: tuple[float, float, float] = (1, 1, 1)) -> None:
    page.draw_rect(rect, color=fill, fill=fill, overlay=True)

def find_line_rect_by_text(fitz: Any, page: Any, needle: str, *, pad_x: float = 0.8, pad_y: float = 0.35) -> Any | None:
    from repair_pdf_drawing import expanded_rect, normalize_text, page_lines
    for row in page_lines(page):
        if needle not in normalize_text(row.get("text") or ""):
            continue
        rect = expanded_rect(fitz, row.get("bbox"), page, pad=0.0, min_width=1.0)
        if not rect:
            continue
        rect.x0 = max(0, rect.x0 - pad_x)
        rect.x1 = min(page.rect.width, rect.x1 + pad_x)
        rect.y0 = max(0, rect.y0 - pad_y)
        rect.y1 = min(page.rect.height, rect.y1 + pad_y)
        return rect
    return None


def draw_mixed_font_line(fitz: Any, page: Any, x: float, y: float, text: str, *, fontsize: float) -> None:
    pattern = re.compile(r"([A-Za-z0-9][A-Za-z0-9\-./:_%’']*(?: [A-Za-z0-9][A-Za-z0-9\-./:_%’']*)*)")
    cursor = x
    pos = 0
    for match in pattern.finditer(text):
        if match.start() > pos:
            chunk = text[pos : match.start()]
            page.insert_text((cursor, y), chunk, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)
            try:
                cursor += fitz.get_text_length(chunk, fontname="china-s", fontsize=fontsize)
            except Exception:
                cursor += len(chunk) * fontsize * 0.52
        chunk = match.group(0)
        page.insert_text((cursor, y), chunk, fontname="helv", fontsize=fontsize, color=(0, 0, 0), overlay=True)
        try:
            cursor += fitz.get_text_length(chunk, fontname="helv", fontsize=fontsize)
        except Exception:
            cursor += len(chunk) * fontsize * 0.5
        pos = match.end()
    if pos < len(text):
        chunk = text[pos:]
        page.insert_text((cursor, y), chunk, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)

def repair_nature_section_headings(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    headings = [
        (2, "Introduction", "引言", [43.0, 47.5, 88.0, 61.0], (44.0, 58.6)),
        (2, "Literature review", "文献综述", [302.8, 212.5, 365.0, 226.5], (303.8, 224.0)),
        (3, "Methods", "方法", [43.0, 366.4, 86.0, 380.5], (44.0, 378.2)),
        (4, "Results", "结果", [38.5, 287.8, 126.0, 311.0], (44.0, 305.2)),
        (8, "Discussion", "讨论", [303.0, 664.7, 346.0, 678.7], (304.0, 676.4)),
        (12, "Conclusion", "结论", [303.0, 487.2, 336.0, 496.0], (304.0, 496.2)),
        (13, "Data availability", "数据可用性", [42.5, 586.0, 170.0, 594.8], (43.6, 593.2)),
        (13, "Notes", "注释", [42.5, 695.7, 88.0, 706.8], (43.6, 704.8)),
        (13, "References", "参考文献", [303.0, 173.2, 363.0, 185.6], (304.2, 185.0)),
        (14, "Acknowledgements", "致谢", [302.5, 430.0, 386.0, 441.8], (303.6, 439.9)),
        (14, "Author contributions", "作者贡献", [302.5, 470.0, 394.0, 481.6], (303.6, 479.9)),
        (14, "Competing interests", "利益冲突", [302.5, 518.5, 394.0, 530.2], (303.6, 528.0)),
        (14, "Ethics approval", "伦理批准", [302.5, 549.7, 376.0, 561.3], (303.6, 559.2)),
        (14, "Informed consent", "知情同意", [302.5, 589.5, 386.0, 601.2], (303.6, 599.0)),
        (14, "Additional information", "附加信息", [302.5, 629.4, 406.0, 641.0], (303.6, 638.9)),
    ]
    for page_number, source, target, bbox, point in headings:
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        page_text = page.get_text("text")
        if target in page_text and source not in page_text:
            rect = find_line_rect_by_text(fitz, page, target) or fitz.Rect(bbox)
            cover_heading_pixels(page, rect)
            draw_point = (point[0], point[1] - 0.8)
            draw_fake_bold_text(page, draw_point, target, fontsize=9.5)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "nature_section_heading_style_repair",
                    "source": source,
                    "target": target,
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": 9.5,
                    "font_weight": "visual_bold",
                    "fill_strategy": "tight_pixel_cover_existing_chinese_heading",
                    "font_policy": "match_source_section_heading_9_5pt_visual_bold",
                    "text_policy": "restore_source_heading_weight_without_double_layer",
                }
            )
            continue
        if source == "Data availability":
            rect = fitz.Rect(42.5, 586.0, 286.0, 610.0)
            _redact_with_fill(page, rect)
            draw_fake_bold_text(page, (43.6, 594.8), target, fontsize=9.5)
            draw_mixed_font_line(fitz, page, 43.86, 607.9, "本研究过程中生成和/或分析所得的数据集，可应合理请求由通讯", fontsize=8.52)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "nature_section_heading_style_repair",
                    "source": source,
                    "target": target,
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": 9.5,
                    "font_weight": "visual_bold",
                    "fill_strategy": "tight_redaction_and_first_line_redraw",
                    "font_policy": "match_source_section_heading_9_5pt_visual_bold",
                    "text_policy": "remove_original_english_heading_layer_and_redraw_chinese_heading",
                }
            )
            continue
        if source == "Notes":
            rect = fitz.Rect(42.5, 695.7, 88.0, 708.6)
            _redact_with_fill(page, rect)
            draw_fake_bold_text(page, (43.6, 704.0), target, fontsize=9.5)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "nature_section_heading_style_repair",
                    "source": source,
                    "target": target,
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": 9.5,
                    "font_weight": "visual_bold",
                    "fill_strategy": "tight_redaction",
                    "font_policy": "match_source_section_heading_9_5pt_visual_bold",
                    "text_policy": "remove_original_english_heading_layer_and_redraw_chinese_heading",
                }
            )
            continue
        rect = fitz.Rect(bbox)
        cover_heading_pixels(page, rect)
        draw_fake_bold_text(page, (point[0], point[1] - 0.8), target, fontsize=9.5)
        repairs.append(
            {
                "page": page_number,
                "rule": "nature_section_heading_style_repair",
                "source": source,
                "target": target,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": 9.5,
                "font_weight": "visual_bold",
                "fill_strategy": "white_page_background",
                "font_policy": "match_source_section_heading_9_5pt_visual_bold",
                "text_policy": "restore_source_heading_weight_and_size",
            }
        )
    return repairs

def repair_nature_page2_numbered_question_list(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 2:
        return []
    page = doc[1]
    rect = fitz.Rect(301.5, 58.0, 563.0, 181.0)
    _redact_with_fill(page, rect, (1, 1, 1))
    lines = [
        "1. 人类翻译、NMT（Google Translate）与",
        "   LLM（ChatGPT-4o、OpenAI-o1）译文在哪些",
        "   语言维度上存在差异？",
        "2. LLM 的文学自传翻译表现是否比 NMT 更接近",
        "   人类译者？如果是，具体体现在哪些方面？",
        "3. 不同 LLM（ChatGPT-4o、OpenAI-o1）之间",
        "   的翻译表现是否存在显著差异？",
        "4. 相比人类翻译、NMT 以及彼此，不同 LLM",
        "   在文学自传翻译中的优势与局限是什么？",
    ]
    baseline = 68.4
    for line in lines:
        draw_mixed_font_line(fitz, page, 303.0, baseline, line, fontsize=6.45)
        baseline += 11.1 if line.startswith(("1.", "2.", "3.", "4.")) else 8.6
    return [
        {
            "page": 2,
            "rule": "nature_page2_numbered_question_list_repair",
            "source": "four numbered research questions merged into one Chinese paragraph",
            "target": "\\n".join(lines),
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fontsize": 6.45,
            "fill_strategy": "white_page_background_structured_redraw",
            "font_policy": "compact_source_like_question_list_body_size",
            "text_policy": "restore_four_independent_numbered_question_paragraphs",
            "backend_sink_down": "pending",
        }
    ]

def repair_nature_page13_publication_metadata(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 13:
        return []
    page = doc[12]
    rect = fitz.Rect(42.5, 655.2, 214.0, 669.8)
    _redact_with_fill(page, rect)
    draw_mixed_font_line(fitz, page, 43.6, 666.2, "在线发表：2026年3月7日", fontsize=8.6)
    return [
        {
            "page": 13,
            "rule": "nature_publication_metadata_visible_repair",
            "source": "Published online: 07 March 2026",
            "target": "在线发表：2026年3月7日",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fontsize": 8.6,
            "layout_role": "publication_metadata",
            "failure_stage": "paint",
            "fill_strategy": "tight_redaction",
            "font_policy": "match_source_metadata_approx_8_6pt_with_chinese_date",
            "text_policy": "translate_visible_publication_date_label_preserve_date_fact",
            "backend_sink_down": "pending",
        }
    ]

def repair_nature_page13_backmatter_headings(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 13:
        return []
    page = doc[12]
    repairs: list[dict[str, Any]] = []
    targets = [
        ("Data availability", "数据可用性", fitz.Rect(42.5, 586.0, 286.0, 610.0), (43.6, 594.8)),
        ("Notes", "注释", fitz.Rect(42.5, 695.7, 88.0, 708.6), (43.6, 704.0)),
    ]
    for source, target, rect, point in targets:
        page_text = page.get_text("text")
        if source not in page_text:
            continue
        _redact_with_fill(page, rect)
        draw_fake_bold_text(page, point, target, fontsize=9.5)
        repairs.append(
            {
                "page": 13,
                "rule": "nature_page13_backmatter_heading_repair",
                "source": source,
                "target": target,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": 9.5,
                "font_weight": "visual_bold",
                "layout_role": "section_heading",
                "failure_stage": "paint",
                "fill_strategy": "tight_redaction",
                "font_policy": "match_source_section_heading_9_5pt_visual_bold",
                "text_policy": "translate_backmatter_section_heading_preserve_body_and_reference_links",
                "backend_sink_down": "pending",
            }
        )
    return repairs

def repair_nature_page14_backmatter(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 14:
        return []
    page = doc[13]
    blocks = [
        (
            "nature_page14_backmatter_text_repair",
            "Acknowledgements",
            "致谢",
            ["本研究得到香港理工大学语言科学与技术系支持（资助编号：P0050978）。"],
            fitz.Rect(301.8, 429.5, 561.0, 461.8),
            303.6,
            439.5,
            (303.6, 453.0),
            6.8,
        ),
        (
            "nature_page14_backmatter_text_repair",
            "Author contributions",
            "作者贡献",
            [
                "Yingqi Huang：概念化、数据整理、形式分析、调查、方法论、",
                "撰写--初稿；Andrew K.F. Cheung：概念化、监督、",
                "撰写--审阅与编辑、经费获取。",
            ],
            fitz.Rect(301.8, 469.5, 561.0, 514.5),
            303.6,
            479.5,
            (303.6, 493.2),
            6.4,
        ),
        (
            "nature_page14_backmatter_text_repair",
            "Competing interests",
            "利益冲突",
            ["作者声明不存在利益冲突。"],
            fitz.Rect(301.8, 518.0, 561.0, 542.5),
            303.6,
            528.0,
            (303.6, 539.1),
            6.4,
        ),
        (
            "nature_page14_backmatter_text_repair",
            "Ethics approval",
            "伦理批准",
            ["本研究未涉及人类参与者实验，因此无需伦理审批。"],
            fitz.Rect(301.8, 549.0, 561.0, 581.0),
            303.6,
            559.0,
            (303.6, 570.4),
            6.8,
        ),
        (
            "nature_page14_backmatter_text_repair",
            "Informed consent",
            "知情同意",
            ["本研究未涉及人类参与者，因此无需取得知情同意。"],
            fitz.Rect(301.8, 589.0, 561.0, 621.5),
            303.6,
            599.0,
            (303.6, 610.4),
            6.8,
        ),
        (
            "nature_page14_backmatter_text_repair",
            "Additional information",
            "附加信息",
            [
                "补充信息：在线版本包含补充材料，见",
                "https://doi.org/10.1057/s41599-026-06630-4。",
                "通讯及材料请求请联系 Andrew Kay Fan Cheung。",
                "转载与授权相关信息可于下述网址获取：",
                "http://www.nature.com/reprints",
            ],
            fitz.Rect(301.8, 629.0, 561.0, 706.0),
            303.6,
            638.7,
            (303.6, 651.6),
            6.8,
        ),
    ]
    repairs: list[dict[str, Any]] = []
    for rule, source, target, body_lines, rect, heading_x, heading_y, body_origin, fontsize in blocks:
        _redact_with_fill(page, rect)
        draw_fake_bold_text(page, (heading_x, heading_y), target, fontsize=9.5)
        for line_index, line in enumerate(body_lines):
            draw_mixed_font_line(
                fitz,
                page,
                body_origin[0],
                body_origin[1] + line_index * (fontsize + 2.0),
                line,
                fontsize=fontsize,
            )
        repairs.append(
            {
                "page": 14,
                "rule": rule,
                "source": source,
                "target": target,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "body_origin": [round(v, 2) for v in body_origin],
                "body_lines": len(body_lines),
                "fontsize": fontsize,
                "heading_fontsize": 9.5,
                "layout_role": "backmatter_section",
                "failure_stage": "paint",
                "fill_strategy": "tight_redaction_and_section_redraw",
                "font_policy": "match_source_backmatter_heading_9_5pt_and_mixed_latin_cjk_body_text",
                "text_policy": "translate_backmatter_section_body_preserve_names_urls_and_grant_numbers",
                "backend_sink_down": "pending",
            }
        )
    return repairs

def draw_nature_inline_label_line(
    fitz: Any,
    page: Any,
    *,
    rect: Any,
    point: tuple[float, float],
    label: str,
    rest: str,
    fontsize: float,
) -> None:
    cover_heading_pixels(page, rect)
    cursor = draw_fake_bold_run(fitz, page, point[0], point[1], label, fontsize=fontsize)
    draw_mixed_font_line(fitz, page, cursor, point[1], rest, fontsize=fontsize)

def repair_nature_inline_bold_labels(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    repairs: list[dict[str, Any]] = []
    labels = [
        (
            3,
            "Corpus",
            "语料库",
            "。我们对比了由 LLM（大型语言模型）所生成的 ChatGPT-4o 与",
            [43.0, 579.0, 292.0, 592.2],
            (43.8, 589.2),
            7.57,
        ),
        (
            3,
            "Instruments, measures, and data analysis",
            "工具、度量方式及数据分析",
            "。语言特征涵盖了多个测量层级。本研究",
            [303.0, 422.0, 552.0, 435.8],
            (303.8, 432.5),
            8.04,
        ),
        (
            4,
            "Lexicon dimension",
            "词汇维度",
            "。这些 HT 指标与 NMT 相比，在多个词汇指标上呈现显著差异。",
            [43.0, 370.2, 292.0, 383.0],
            (43.8, 379.5),
            7.2,
        ),
        (
            5,
            "The syntactic dimension",
            "句法维度",
            "。在多个句法指标方面，HT、NMT 和各类 LLM 呈现出显著差异。",
            [43.0, 547.3, 292.0, 560.5],
            (43.8, 557.0),
            7.0,
        ),
        (
            6,
            "The textbase dimension",
            "文本库维度",
            "。在文本库层面，我们观察到各模型之间的显著差异。",
            [43.0, 662.5, 292.0, 676.0],
            (43.7, 672.4),
            7.4,
        ),
        (
            7,
            "The situation model dimension",
            "情境模型维度",
            "。情境模型能够体现超出文本字面意义的理解。",
            [43.0, 693.8, 292.0, 708.0],
            (43.8, 704.5),
            7.6,
        ),
        (
            8,
            "The descriptive dimension",
            "描述性维度",
            "。八个描述性统计指标凸显了不同样本间的显著差异。",
            [43.0, 462.2, 292.0, 476.0],
            (43.7, 472.8),
            7.5,
        ),
        (
            8,
            "The text readability and easability dimension",
            "文本可读性与易读性维度",
            "：在文本可读性和易读性方面，HT 与模型译文差异明显。",
            [43.0, 672.8, 292.0, 686.8],
            (43.7, 683.5),
            7.2,
        ),
    ]
    for page_number, source, label, rest, bbox, point, fontsize in labels:
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        rect = fitz.Rect(bbox)
        draw_nature_inline_label_line(fitz, page, rect=rect, point=point, label=label, rest=rest, fontsize=fontsize)
        repairs.append(
            {
                "page": page_number,
                "rule": "nature_inline_bold_label_repair",
                "source": source,
                "target": label,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": fontsize,
                "font_weight": "visual_bold_label",
                "fill_strategy": "pixel_cover_single_line_redraw",
                "font_policy": "restore_source_inline_bold_label_weight_with_existing_body_size",
                "text_policy": "restore_inline_bold_label_weight",
            }
        )
    return repairs

def repair_nature_page1_abstract(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 1:
        return []
    page = doc[0]
    text = page.get_text("text")
    if "AI-based" not in text and "ChatGPT-4o 与人类译文最为接近" in text:
        return []
    repairs: list[dict[str, Any]] = []
    stray_rect = fitz.Rect(0.0, 294.0, 18.0, 338.0)
    _redact_with_fill(page, stray_rect, (1, 1, 1))
    repairs.append(
        {
            "page": 1,
            "rule": "nature_page1_stray_text_cover",
            "source": "234567890() ;",
            "target": "",
            "bbox": [round(v, 2) for v in [stray_rect.x0, stray_rect.y0, stray_rect.x1, stray_rect.y1]],
            "fill_strategy": "white_page_background",
            "font_policy": "not_applicable_background_cleanup_only",
            "text_policy": "remove_stray_glyph_noise_without_touching_body_text",
        }
    )
    abstract_rect = fitz.Rect(42.0, 304.5, 570.0, 512.0)
    _redact_with_fill(page, abstract_rect, (1, 1, 1))
    abstract_lines = [
        "基于人工智能的模型正在改变翻译行业，Google Translate的",
        "神经机器翻译以及大型语言模型正在推动这一进程。然而，将",
        "这些模型用于文学翻译，尤其是经验丰富的人类译者仍感困难",
        "的领域，会引出一个关键问题：AI能在多大程度上复现人类",
        "翻译的深度与细腻度？哪类模型更接近人类译作？本研究基于",
        "语料库，比较NMT-GT、ChatGPT-4o、OpenAI-o1与人类译文。",
        "分析覆盖词汇与句法多样性、文本基础与情境模型、可读性等",
        "多个语言维度。结果显示，在这一文学自传案例中，ChatGPT-4o",
        "与人类译文最为接近，其次是NMT-GT，OpenAI-o1的相似度最低。",
        "这表明NMT系统并不一定逊于LLM；推理型OpenAI-o1也未比",
        "通用模型生成更接近人类的译文，而ChatGPT-4o最有效地弥合了",
        "人类译作与AI生成译文之间的差距。",
    ]
    y = 316.5
    for line in abstract_lines:
        draw_mixed_font_line(fitz, page, 43.0, y, line, fontsize=9.0)
        y += 14.4
    repairs.append(
        {
            "page": 1,
            "rule": "nature_page1_abstract_visible_repair",
            "source": "page_1_abstract_same_as_input_or_mixed_english",
            "target": " ".join(abstract_lines)[:180],
            "bbox": [round(v, 2) for v in [abstract_rect.x0, abstract_rect.y0, abstract_rect.x1, abstract_rect.y1]],
            "fontsize": 9.0,
            "line_gap": 14.4,
            "fill_strategy": "white_page_background",
            "font_policy": "source_body_prose_like_9pt_with_14_4pt_line_gap",
            "text_policy": "manual_visible_abstract_translation_without_deepseek_mixed_font_latin_terms",
        }
    )

    return repairs

def repair_nature_page1_title_wrap(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import normalize_text
    if doc.page_count < 1:
        return []
    page = doc[0]
    text = normalize_text(page.get_text("text"))
    if "各类人 工智能" not in text and "各类人工智能模型" in text:
        return []
    title_rect = fitz.Rect(43.0, 165.0, 570.0, 244.0)
    _redact_with_fill(page, title_rect, (1, 1, 1))
    lines = [
        "探讨人工智能在文学自传翻译中的表现：各类",
        "人工智能模型所产出的译文与人类译作的相似程度",
        "究竟如何？",
    ]
    y = 183.0
    for line in lines:
        page.insert_text((44.0, y), line, fontname="china-s", fontsize=15.4, color=(0, 0, 0), overlay=True)
        y += 25.0
    return [
        {
            "page": 1,
            "rule": "nature_page1_title_wrap_repair",
            "source": "title_wrap_split_artificial_intelligence",
            "target": "\\n".join(lines),
            "bbox": [round(v, 2) for v in [title_rect.x0, title_rect.y0, title_rect.x1, title_rect.y1]],
            "fill_strategy": "white_page_background",
            "font_policy": "match_source_title_scale_with_manual_three_line_wrap",
            "text_policy": "translate_title_without_splitting_artificial_intelligence",
        }
    ]


def repair_nature_page1_doi_open_passthrough(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    if source_doc.page_count < 1 or doc.page_count < 1:
        return []
    target_page = doc[0]
    rect = fitz.Rect(42.0, 145.0, 390.0, 164.0)
    _redact_with_fill(target_page, rect, (1, 1, 1))
    try:
        target_page.show_pdf_page(rect, source_doc, 0, clip=rect, overlay=True, keep_proportion=False)
    except Exception:
        return []
    return [
        {
            "page": 1,
            "rule": "nature_page1_doi_open_passthrough",
            "source": "source_doi_open_region",
            "target": "passthrough_original_doi_open_region",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "source_region_copy",
            "font_policy": "preserve_source_doi_open_metadata_fonts",
            "text_policy": "passthrough_original_metadata_region",
        }
    ]

def repair_nature_page1_publisher_badge_passthrough(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    if source_doc.page_count < 1 or doc.page_count < 1:
        return []
    target_page = doc[0]
    rect = fitz.Rect(465.0, 112.0, 575.0, 165.0)
    _redact_with_fill(target_page, rect, (1, 1, 1))
    try:
        target_page.show_pdf_page(rect, source_doc, 0, clip=rect, overlay=True, keep_proportion=False)
    except Exception:
        return []
    return [
        {
            "page": 1,
            "rule": "nature_publisher_badge_source_region_passthrough",
            "source": "source_check_for_updates_badge_region",
            "target": "passthrough_original_publisher_badge_region",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "source_region_copy_after_clearing_translated_layer",
            "font_policy": "preserve_source_badge_icon_gradient_button_and_label",
            "text_policy": "passthrough_original_publisher_badge_visual_region",
            "backend_sink_down": "pending",
        }
    ]

def repair_nature_page1_footer_rule_passthrough(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    if source_doc.page_count < 1 or doc.page_count < 1:
        return []
    target_page = doc[0]
    rect = fitz.Rect(40.0, 724.0, 555.0, 728.5)
    try:
        target_page.show_pdf_page(rect, source_doc, 0, clip=rect, overlay=True, keep_proportion=False)
    except Exception:
        target_page.draw_rect(fitz.Rect(43.4, 726.0, 551.9, 726.5), color=(0.649, 0.659, 0.832), fill=(0.649, 0.659, 0.832), overlay=True)
    return [
        {
            "page": 1,
            "rule": "nature_page1_footer_rule_passthrough",
            "source": "source_footer_separator_line",
            "target": "passthrough_original_footer_separator_line",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "source_region_copy",
            "font_policy": "not_applicable_source_footer_rule_copy",
            "text_policy": "passthrough_original_metadata_region",
        }
    ]

def repair_nature_table1_structured(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 3:
        return []
    page = doc[2]
    text = page.get_text("text")
    if "表1 翻译语料库的描述性统计信息" not in text and "Table 1" not in text:
        return []
    outer = fitz.Rect(303.0, 46.0, 552.0, 131.5)
    lavender = (0.78, 0.78, 0.88)
    _redact_with_fill(page, outer, (1, 1, 1))
    page.draw_rect(outer, color=(0, 0, 0), fill=(1, 1, 1), width=0.4, overlay=True)
    title_rect = fitz.Rect(303.0, 46.0, 552.0, 68.0)
    page.draw_rect(title_rect, color=(0, 0, 0), fill=lavender, width=0.4, overlay=True)
    page.insert_textbox(
        fitz.Rect(307.0, 50.0, 548.0, 65.5),
        "表1  翻译语料库的描述性统计信息。",
        fontname="china-s",
        fontsize=6.9,
        color=(0, 0, 0),
        overlay=True,
    )
    header_y0 = 72.0
    row_top = 87.0
    page.draw_line((303.0, row_top), (552.0, row_top), color=(0, 0, 0), width=0.35, overlay=True)
    col_x = [307.0, 378.0, 431.0, 482.0]
    headers = ["子语料库", "文本数量", "词数", "平均长度"]
    for x, label in zip(col_x, headers):
        page.insert_text((x, header_y0 + 8.5), label, fontname="china-s", fontsize=6.4, color=(0, 0, 0), overlay=True)
    rows = [
        ("HT", "83", "124,414", "1,498.96"),
        ("NMT-GT", "83", "121,783", "1,467.27"),
        ("LLM-4o", "83", "116,410", "1,402.53"),
        ("LLM-o1", "83", "113,750", "1,370.48"),
    ]
    y = 98.0
    for row in rows:
        for x, value in zip(col_x, row):
            font = "china-s" if re.search(r"[\u4e00-\u9fff]", value) else "helv"
            page.insert_text((x, y), value, fontname=font, fontsize=6.7, color=(0, 0, 0), overlay=True)
        y += 9.6
    return [
        {
            "page": 3,
            "rule": "nature_table1_structured_redraw",
            "source": "fragmented_table1_caption_and_headers",
            "target": "structured_table1_redraw_preserving_numeric_values",
            "bbox": [round(v, 2) for v in [outer.x0, outer.y0, outer.x1, outer.y1]],
            "fill_strategy": "white_table_background_with_lavender_caption_bar",
            "font_policy": "source_table_like_compact_6_4_to_6_9pt_with_numeric_values_preserved",
            "text_policy": "structured_table_redraw_translate_caption_and_headers_preserve_corpus_labels_and_numbers",
            "backend_sink_down": "pending",
        }
    ]

def repair_nature_table2_structured(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    if doc.page_count < 5:
        return []
    page = doc[4]
    text = page.get_text("text")
    if "表2" not in text and "Table 2" not in text:
        return []
    outer = fitz.Rect(45.0, 353.0, 552.0, 489.0)
    lavender = (0.78, 0.78, 0.88)
    _redact_with_fill(page, outer, (1, 1, 1))
    page.draw_rect(outer, color=(0, 0, 0), fill=(1, 1, 1), width=0.4, overlay=True)
    title_rect = fitz.Rect(45.0, 353.0, 552.0, 376.0)
    page.draw_rect(title_rect, color=(0, 0, 0), fill=lavender, width=0.4, overlay=True)
    page.insert_textbox(
        fitz.Rect(49.0, 357.5, 548.0, 372.0),
        "表2  六个语言维度上具有统计学显著性的成对差异数量。",
        fontname="china-s",
        fontsize=6.4,
        color=(0, 0, 0),
        overlay=True,
    )
    col_x = [49.0, 143.0, 214.0, 283.0, 354.0, 429.0, 503.0]
    headers = ["维度", "HT vs. NMT-GT", "HT vs. LLM-4o", "HT vs. LLM-o1", "NMT-GT vs. LLM-4o", "NMT-GT vs. LLM-o1", "LLM-4o vs. LLM-o1"]
    header_y = 393.0
    page.draw_line((45.0, 401.0), (552.0, 401.0), color=(0, 0, 0), width=0.35, overlay=True)
    for x, label in zip(col_x, headers):
        font = "china-s" if label == "维度" else "helv"
        size = 5.1 if label != "维度" else 6.0
        page.insert_text((x, header_y), label, fontname=font, fontsize=size, color=(0, 0, 0), overlay=True)
    rows = [
        ("词汇", "5", "7", "8", "8", "9", "1"),
        ("句法", "6", "8", "10", "9", "6", "3"),
        ("文本基础", "13", "6", "15", "16", "10", "3"),
        ("情境模型", "8", "6", "5", "3", "2", "2"),
        ("描述性", "4", "6", "6", "8", "6", "0"),
        ("可读性与易处理性", "12", "9", "11", "15", "9", "5"),
        ("各维度合计", "48", "42", "55", "59", "42", "14"),
    ]
    y = 413.0
    for row in rows:
        for x, value in zip(col_x, row):
            font = "china-s" if re.search(r"[\u4e00-\u9fff]", value) else "helv"
            size = 5.7 if font == "china-s" else 6.0
            page.insert_text((x, y), value, fontname=font, fontsize=size, color=(0, 0, 0), overlay=True)
        y += 10.4
    return [
        {
            "page": 5,
            "rule": "nature_table2_structured_redraw",
            "source": "mixed_language_table2_caption_only_repair",
            "target": "structured_table2_redraw_preserving_numeric_values",
            "bbox": [round(v, 2) for v in [outer.x0, outer.y0, outer.x1, outer.y1]],
            "fill_strategy": "white_table_background_with_lavender_caption_bar",
            "font_policy": "source_table_like_compact_5_1_to_6_4pt_with_numeric_values_preserved",
            "text_policy": "structured_table_redraw_translate_caption_and_dimension_labels_preserve_pairwise_model_headers_and_numbers",
            "backend_sink_down": "pending",
        }
    ]

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
