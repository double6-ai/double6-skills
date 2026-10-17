# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai charts：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def toc_row_translation(text: str) -> str | None:
    from repair_pdf_drawing import normalize_text
    value = normalize_text(text)
    target = layout_role_policy.structured_row_direct_output("toc_entry", value)
    if target:
        return target
    target = layout_role_policy.structured_row_direct_output("chapter_index_entry", value)
    if target:
        return target
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
    }
    changed = value
    for source, replacement in replacements.items():
        changed = re.sub(re.escape(source), replacement, changed, flags=re.I)
    return changed if changed != value and re.search(r"[\u4e00-\u9fff]", changed) else None


def looks_like_toc_row(text: str) -> bool:
    from repair_pdf_drawing import normalize_text
    value = normalize_text(text)
    if not value:
        return False
    return bool(
        re.match(r"^(?:\d+(?:\.\d+)*|Chapter|Contents|Research and Development|Chapter Highlights)\b", value, re.I)
        or re.search(r"\.{2,}\s*\d{1,3}$", value)
        or re.search(r"\b(?:Notable AI models|Compute and Infrastructure|Open-Source AI Software|Publications)\b", value, re.I)
    )


def repair_toc_page(fitz: Any, source_page: Any, target_page: Any, page_number: int) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, page_lines, replace_rect
    repairs: list[dict[str, Any]] = []
    for row in page_lines(source_page):
        text = row["text"]
        if not looks_like_toc_row(text):
            continue
        target = toc_row_translation(text)
        if not target:
            continue
        rect = expanded_rect(fitz, row.get("bbox"), target_page, pad=1.2, min_width=80)
        if not rect:
            continue
        if rect.width < target_page.rect.width * 0.38:
            rect.x1 = min(target_page.rect.width - 24, rect.x0 + target_page.rect.width * 0.42)
        meta = replace_rect(target_page, rect, target, fontsize=min(float(row.get("size") or 8.5), 9.0))
        meta.update(
            {
                "font_policy": "match_source_toc_row_size_with_cjk_font",
                "text_policy": "translate_toc_row_preserve_numbering_and_page_reference",
            }
        )
        repairs.append({"page": page_number, "rule": "toc_row_visible_repair", "source": text[:180], "target": target[:180], **meta})
    return repairs


def draw_toc_text(page: Any, x: float, y: float, text: str, *, size: float, color: tuple[float, float, float], bold: bool = False) -> None:
    from repair_pdf_ai_links import draw_text_run
    draw_text_run(page, x, y, text, fontsize=size, color=color)


def repair_ai_research_contents_page(fitz: Any, target_page: Any) -> list[dict[str, Any]]:
    """Redraw AI Index page-14 TOC as a structured two-column table.

    The generic string-level TOC repair is too local for this page: section numbers,
    row labels, and page-number columns are separate visual fields in the source,
    but the translated PDF has them merged into long text runs.
    """
    from repair_pdf_nature import _redact_with_fill
    body = fitz.Rect(24, 80, target_page.rect.width - 24, 690)
    _redact_with_fill(target_page, body, AI_TOC_TEAL)
    target_page.draw_line((292, 88), (292, 642), color=AI_TOC_LINE, width=0.6, overlay=True)
    target_page.draw_line((306, 88), (306, 642), color=AI_TOC_LINE, width=0.6, overlay=True)

    rows = [
        (34, 105, 270, "目录", "", "title", 0),
        (48, 142, 270, "章节要点", "14", "section", 0),
        (48, 174, 270, "1.1 值得关注的人工智能模型", "16", "section", 0),
        (66, 196, 270, "按国家/地区归属划分", "16", "item", 0),
        (66, 218, 270, "按部门与组织划分", "18", "item", 0),
        (66, 240, 270, "模型发布", "20", "item", 0),
        (66, 262, 270, "参数与计算趋势", "22", "item", 0),
        (66, 284, 270, "亮点：模型会耗尽数据吗？", "25", "highlight", 0),
        (48, 324, 270, "1.2 计算与基础设施", "28", "section", 0),
        (66, 346, 270, "性能与效率", "28", "item", 0),
        (66, 368, 270, "知名模型硬件", "29", "item", 0),
        (66, 390, 270, "全球计算能力", "29", "item", 0),
        (66, 412, 270, "数据中心供电能力", "30", "item", 0),
        (48, 452, 270, "1.3 数据中心", "31", "section", 0),
        (66, 474, 270, "GPU 之外的 AI 基础设施", "31", "item", 0),
        (66, 496, 270, "地理分布", "32", "item", 0),
        (48, 536, 270, "1.4 能源与环境影响", "33", "section", 0),
        (66, 558, 270, "训练", "33", "item", 0),
        (66, 580, 270, "推理", "36", "item", 0),
        (66, 602, 270, "数据中心使用", "39", "item", 0),
        (48, 642, 270, "1.5 开源 AI 软件", "41", "section", 0),
        (66, 664, 270, "AI 开发活动概览", "41", "item", 0),
        (324, 105, 550, "星级", "43", "item", 1),
        (324, 127, 550, "模型与数据集生态系统", "44", "item", 1),
        (324, 167, 550, "1.6 出版物", "47", "section", 1),
        (342, 189, 550, "AI 出版物总数", "47", "item", 1),
        (342, 211, 550, "按发表场所划分", "48", "item", 1),
        (342, 233, 550, "会议参与度", "48", "item", 1),
        (342, 255, 550, "按国家/地区归属划分", "50", "item", 1),
        (342, 277, 550, "按部门划分", "52", "item", 1),
        (342, 299, 550, "按主题划分", "53", "item", 1),
        (342, 339, 550, "前100篇出版物", "53", "item", 1),
        (360, 361, 550, "按国家/地区归属划分", "53", "item", 1),
        (360, 383, 550, "按部门与组织划分", "54", "item", 1),
        (324, 423, 550, "1.7 专利", "56", "section", 1),
        (342, 445, 550, "全球趋势", "56", "item", 1),
        (342, 467, 550, "前向引用流", "58", "item", 1),
        (342, 489, 550, "知识扩散速度", "59", "item", 1),
        (342, 511, 550, "技术邻近性", "60", "item", 1),
        (342, 533, 550, "亮点：AI 专利实例", "61", "highlight", 1),
        (324, 573, 550, "1.8 AI 作者与发明者", "62", "section", 1),
        (342, 595, 550, "地理分布", "62", "item", 1),
        (342, 617, 550, "按教育水平划分", "63", "item", 1),
        (342, 639, 550, "按性别划分", "65", "item", 1),
        (342, 661, 550, "按专业领域划分", "66", "item", 1),
        (342, 683, 550, "流动性", "66", "item", 1),
    ]
    for x, y, page_x, label, page_no, kind, _column in rows:
        if kind != "title":
            target_page.draw_line((x, y + 8), (page_x + 18, y + 8), color=AI_TOC_LINE, width=0.35, overlay=True)
        color = AI_TOC_HIGHLIGHT if kind == "highlight" else AI_TOC_WHITE
        size = 11.0 if kind == "title" else 9.2 if kind == "section" else 8.6
        draw_toc_text(target_page, x, y, label, size=size, color=color)
        if page_no:
            draw_toc_text(target_page, page_x, y, page_no, size=8.8, color=color if kind == "highlight" else AI_TOC_WHITE)
    return [
        {
            "page": 14,
            "rule": "toc_page_structured_redraw",
            "source": "Research and Development contents table",
            "target": "two-column Chinese contents table with independent right-aligned page numbers",
            "bbox": [round(v, 2) for v in [body.x0, body.y0, body.x1, body.y1]],
            "fill_strategy": "solid_page_background_redraw",
            "font_policy": "structured_two_column_toc_source_like_hierarchy",
            "text_policy": "keep_section_numbers_and_page_numbers_as_independent_visual_fields",
        }
    ]


def repair_ai_chapter_highlights_title(fitz: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_mixed_source_han_sans, insert_mixed_source_han_sans_fake_bold, insert_source_han_serif, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    if target_page.number + 1 != 15:
        return []
    cover = fitz.Rect(22, 58, 320, 124)
    target_page.draw_rect(cover, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    target_page.insert_text((36, 105), "章节要点", fontname="china-s", fontsize=28, color=(0.047, 0.471, 0.435), overlay=True)
    body_rect = fitz.Rect(73, 137, 574, 203)
    body_fill = sampled_background_color(target_page, body_rect)
    _redact_with_fill(target_page, body_rect, body_fill)
    first_color = (0.047, 0.431, 0.427)
    body_color = (0.086, 0.286, 0.31)
    insert_mixed_source_han_sans_fake_bold(
        fitz,
        target_page,
        (77.8, 154.8),
        [("2025", "latin"), ("年，产业界产出了超过", "cjk"), ("90%", "latin"), ("的知名人工智能模型，但最强模型的透明度反而最低。", "cjk")],
        fontsize=9.35,
        color=first_color,
    )
    insert_mixed_source_han_sans(
        fitz,
        target_page,
        (77.8, 171.2),
        [("包括 ", "cjk"), ("OpenAI", "latin"), ("、", "cjk"), ("Anthropic", "latin"), (" 以及 ", "cjk"), ("Google", "latin"), (" 的多个资源密集型系统在内，", "cjk")],
        fontsize=9.35,
        color=body_color,
    )
    insert_source_han_serif(
        target_page,
        (77.8, 187.6),
        "训练代码、参数数量、数据集规模和训练时长等信息已不再披露。",
        fontsize=9.35,
        color=body_color,
    )
    return [
        {
            "page": 15,
            "rule": "chapter_highlights_title_visible_repair",
            "source": "Chapter Highlights / stray Contents translation",
            "target": "章节要点",
            "bbox": [22, 58, 320, 124],
            "fill_strategy": "white_title_area_redraw",
            "font_policy": "match_source_large_chapter_highlights_title_size_color",
            "text_policy": "large_title_redraw_without_stray_toc_character",
        },
        {
            "page": 15,
            "rule": "chapter_highlights_first_item_repair",
            "source": "first highlight paragraph rendered with black heading and incomplete translation",
            "target": "first highlight paragraph redrawn with source-like teal emphasis and corrected translation",
            "bbox": [round(v, 2) for v in [body_rect.x0, body_rect.y0, body_rect.x1, body_rect.y1]],
            "fontsize": 9.35,
            "fill_strategy": "sampled_highlight_panel_background_redraw",
            "font_policy": "match_source_highlight_paragraph_size_and_teal_emphasis",
            "text_policy": "single_paragraph_with_bold_first_sentence_and_restored_meaning",
        },
    ]


def copy_ai_chart_regions(
    fitz: Any,
    source_doc: Any,
    target_doc: Any,
    *,
    pages: set[int] | None = None,
    redact_existing_text: bool = False,
) -> list[dict[str, Any]]:
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    regions = {
        17: [(294, 366, 585, 670)],
        18: [(28, 104, 395, 372), (28, 408, 585, 744)],
        19: [(28, 270, 585, 626)],
        20: [(28, 86, 585, 386), (28, 402, 585, 734)],
    }
    for page_number, boxes in regions.items():
        if pages and page_number not in pages:
            continue
        if page_number > source_doc.page_count or page_number > target_doc.page_count:
            continue
        source_page = source_doc[page_number - 1]
        target_page = target_doc[page_number - 1]
        for box in boxes:
            rect = fitz.Rect(box)
            if redact_existing_text:
                _redact_with_fill(target_page, rect, (1, 1, 1))
            pix = stable_get_pixmap(source_page, clip=rect, matrix=fitz.Matrix(2, 2), alpha=False)
            target_page.insert_image(rect, pixmap=pix, keep_proportion=False, overlay=True)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "chart_region_passthrough_repair",
                    "source": "original chart visual region",
                    "target": "chart copied from source PDF",
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fill_strategy": "source_region_raster_with_text_layer_redaction" if redact_existing_text else "source_region_copy",
                    "font_policy": "preserve_chart_visual_fonts_axes_colors_and_geometry",
                    "text_policy": "chart_visual_object_passthrough_without_source_text_layer" if redact_existing_text else "chart_visual_object_passthrough",
                }
            )
    return repairs


def repair_ai_chart_titles_after_passthrough(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_ai_figure_label, insert_mixed_source_han_sans, insert_source_han_sans, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    black = (0, 0, 0)
    white = (1, 1, 1)
    title_specs = [
        {
            "page": 17,
            "rect": (296.0, 373.0, 566.0, 411.0),
            "title": [("二〇二五年按选定地理区域划分的知名人工智能模型数量", 11.2, 389.2)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.7, 408.6),
        },
        {
            "page": 18,
            "rect": (48.0, 97.0, 314.0, 134.0),
            "title": [("二〇〇三至二〇二五年按选定地理区域划分的知名人工智能模型数量", 10.8, 113.2)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.5, 132.0),
        },
        {
            "page": 18,
            "rect": (34.0, 416.5, 368.0, 445.5),
            "title": [("二〇〇三至二〇二五年按地理区域划分的知名人工智能模型数量（总数）", 10.7, 432.8)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.4, 441.0),
        },
        {
            "page": 19,
            "rect": (35.0, 299.0, 286.0, 326.5),
            "title": [("二〇〇三至二〇二五年按部门划分的知名人工智能模型数量", 10.7, 315.0)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.4, 322.8),
        },
        {
            "page": 20,
            "rect": (35.0, 84.5, 292.0, 111.5),
            "title": [("二〇〇三至二〇二五年按部门划分的知名人工智能模型占比", 10.3, 100.3)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.2, 107.8),
        },
        {
            "page": 20,
            "rect": (38.0, 420.5, 294.0, 447.0),
            "title": [("二〇二五年按组织划分的知名人工智能模型数量", 10.3, 436.4)],
            "source": ("来源：Epoch AI，2026 | 图表：2026 年人工智能指数报告", 6.2, 443.9),
        },
    ]
    for spec in title_specs:
        page_number = int(spec["page"])
        if pages and page_number not in pages:
            continue
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        rect = fitz.Rect(spec["rect"])
        _redact_with_fill(page, rect, white)
        for text, fontsize, baseline in spec["title"]:
            insert_source_han_sans(page, (rect.x0 + 2.0, baseline), text, fontsize=fontsize, color=black)
        source_text, source_size, source_baseline = spec["source"]
        if "Epoch AI" in source_text:
            insert_mixed_source_han_sans(
                fitz,
                page,
                (rect.x0 + 2.0, source_baseline),
                [
                    ("来源：", "cjk"),
                    ("Epoch AI", "latin"),
                    ("，", "cjk"),
                    ("2026", "latin"),
                    (" | ", "latin"),
                    ("图表：", "cjk"),
                    ("    ", "latin"),
                    ("AI Index ", "latin"),
                    ("2026", "latin"),
                ],
                fontsize=source_size,
                color=black,
            )
        else:
            insert_source_han_sans(page, (rect.x0 + 2.0, source_baseline), source_text, fontsize=source_size, color=black)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_page17_20_chart_title_translation_repair",
                "source": "chart title/source line copied from source PDF after chart passthrough",
                "target": "Chinese chart title and source line redrawn with source-like font size and color",
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fill_strategy": "solid_chart_background_patch",
                "font_policy": "match_source_chart_title_and_source_line_size_color",
                "text_policy": "translate_chart_title_without_spaced_latin_abbreviations_and_draw_epoch_ai_as_latin_segment",
            }
        )

    figure_specs = [
        (17, (526.0, 650.0, 578.0, 666.0), "图 1.1.1", 9.0, 662.8, "3", 5.2, 657.0),
        (18, (341.0, 352.0, 392.0, 368.0), "图 1.1.2", 9.0, 364.8, "", 5.2, 0.0),
        (18, (527.0, 710.0, 578.0, 726.0), "图 1.1.3", 9.0, 722.8, "", 5.2, 0.0),
        (19, (527.0, 606.0, 578.0, 622.0), "图 1.1.4", 9.0, 618.8, "", 5.2, 0.0),
        (20, (527.0, 375.0, 578.0, 391.0), "图 1.1.5", 9.0, 387.6, "", 5.2, 0.0),
        (20, (520.0, 715.5, 596.0, 736.0), "图 1.1.6", 9.0, 730.3, "4", 5.2, 724.5),
    ]
    for page_number, box, label, fontsize, baseline, superscript, sup_size, sup_baseline in figure_specs:
        if pages and page_number not in pages:
            continue
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        rect = fitz.Rect(box)
        fill = sampled_background_color(page, rect)
        _redact_with_fill(page, rect, fill)
        label_end_x = insert_ai_figure_label(fitz, page, (rect.x0 + 1.5, baseline), label, fontsize=fontsize, color=AI_INDEX_TEAL)
        if superscript:
            sup_x = label_end_x + 0.8
            insert_source_han_sans(page, (sup_x, sup_baseline), superscript, fontsize=sup_size, color=AI_INDEX_TEAL)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_page17_20_chart_title_translation_repair",
                "source": "Figure label copied from source PDF after chart passthrough",
                "target": label + (superscript or ""),
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fill_strategy": "sampled_region_background",
                "font_policy": "match_source_figure_label_size_color",
                "text_policy": "translate_figure_label_after_chart_passthrough_preserve_superscript",
            }
        )
    return repairs


def repair_ai_page17_chart_axis_labels_after_passthrough(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import cjk_text_width, fit_textbox, insert_mixed_source_han_sans, insert_source_han_sans, mixed_source_han_sans_width, split_numeric_prefix_label
    if doc.page_count < 17:
        return []
    repairs: list[dict[str, Any]] = []
    label_specs = [
        (17, [301.0, 419.0, 360.5, 431.8], "美国", 5.8, 429.3, "United States", "right"),
        (17, [337.0, 444.5, 360.5, 457.2], "中国", 5.8, 454.8, "China", "right"),
        (17, [315.0, 470.0, 360.5, 482.6], "韩国", 5.8, 480.3, "South Korea", "right"),
        (17, [331.0, 495.4, 360.5, 508.0], "加拿大", 5.6, 505.8, "Canada", "right"),
        (17, [334.0, 520.8, 360.5, 533.4], "法国", 5.8, 531.0, "France", "right"),
        (17, [318.0, 546.3, 360.5, 558.8], "中国香港", 5.4, 556.6, "Hong Kong", "right"),
        (17, [322.0, 571.7, 360.5, 584.3], "新加坡", 5.6, 582.0, "Singapore", "right"),
        (17, [301.0, 597.2, 360.5, 609.7], "英国", 5.8, 607.4, "United Kingdom", "right"),
        (17, [414.0, 628.0, 522.0, 642.0], "知名人工智能模型数", 5.8, 638.6, "Number of notable AI models", "center"),
        (18, [47.0, 180.0, 61.0, 283.5], "知名人工智能模型数", 5.6, 278.0, "Number of notable AI models", "vertical"),
        (18, [256.0, 309.0, 294.0, 321.5], "2，欧洲", 5.7, 318.8, "2, Europe", "left"),
        (18, [256.0, 242.5, 294.0, 255.2], "35，中国", 5.7, 252.6, "35, China", "left"),
        (18, [256.0, 195.0, 319.0, 207.8], "59，美国", 5.7, 205.2, "59, United States", "left"),
        (19, [35.0, 393.0, 48.5, 496.5], "知名人工智能模型数", 5.6, 491.0, "Number of notable AI models", "vertical"),
        (19, [448.0, 539.0, 495.0, 552.2], "2，学术界", 5.7, 549.0, "2, Academia", "left"),
        (19, [448.0, 531.0, 482.0, 544.0], "2，其他", 5.7, 541.0, "2, Other", "left"),
        (19, [448.0, 523.0, 570.0, 536.0], "5，产学合作", 5.7, 533.0, "5, Industry-academia collaboration", "left"),
        (19, [448.0, 332.0, 494.0, 345.0], "93，产业界", 5.7, 342.0, "93, Industry", "left"),
        (20, [34.5, 173.0, 47.5, 274.5], "知名人工智能模型占比", 5.4, 268.5, "Notable AI models (% of total)", "vertical"),
        (20, [421.0, 313.5, 482.0, 326.5], "1.96%，学术界", 5.4, 323.7, "1.96%, Academia", "left"),
        (20, [421.0, 305.5, 469.0, 319.0], "1.96%，其他", 5.4, 316.0, "1.96%, Other", "left"),
        (20, [421.0, 297.5, 556.0, 311.0], "4.90%，产学合作", 5.4, 308.2, "4.90%, Industry-academia collaboration", "left"),
        (20, [421.0, 133.5, 478.5, 147.5], "91.18%，产业界", 5.4, 144.0, "91.18%, Industry", "left"),
        (20, [306.0, 685.0, 410.0, 699.5], "知名人工智能模型数", 5.4, 695.0, "Number of notable AI models", "center"),
        (20, [516.0, 625.0, 553.5, 638.5], "学术界", 5.4, 635.4, "Academia", "left"),
        (20, [516.0, 636.0, 548.0, 649.5], "产业界", 5.4, 646.4, "Industry", "left"),
        (20, [516.0, 647.0, 553.5, 660.5], "非营利", 5.4, 657.3, "Nonprofit", "left"),
    ]
    for page_number, bbox, target, fontsize, baseline, source, align in label_specs:
        if pages and page_number not in pages:
            continue
        if doc.page_count < page_number:
            continue
        page = doc[page_number - 1]
        rect = fitz.Rect(bbox)
        fill = (1, 1, 1)
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
        if align == "vertical":
            fit_textbox(page, rect, target, fontsize=fontsize, rotate=90, color=(0, 0, 0))
        elif align == "right":
            segments = split_numeric_prefix_label(target)
            width = mixed_source_han_sans_width(fitz, segments, fontsize=fontsize) if segments else cjk_text_width(fitz, target, fontsize=fontsize)
            x = rect.x1 - width - 1.0
            if segments:
                insert_mixed_source_han_sans(fitz, page, (max(rect.x0 + 1.0, x), baseline), segments, fontsize=fontsize, color=(0, 0, 0))
            else:
                insert_source_han_sans(page, (max(rect.x0 + 1.0, x), baseline), target, fontsize=fontsize, color=(0, 0, 0))
        elif align == "center":
            segments = split_numeric_prefix_label(target)
            width = mixed_source_han_sans_width(fitz, segments, fontsize=fontsize) if segments else cjk_text_width(fitz, target, fontsize=fontsize)
            x = rect.x0 + max(1.0, (rect.width - width) / 2.0)
            if segments:
                insert_mixed_source_han_sans(fitz, page, (max(rect.x0 + 1.0, x), baseline), segments, fontsize=fontsize, color=(0, 0, 0))
            else:
                insert_source_han_sans(page, (max(rect.x0 + 1.0, x), baseline), target, fontsize=fontsize, color=(0, 0, 0))
        else:
            x = rect.x0 + 1.0
            segments = split_numeric_prefix_label(target)
            if segments:
                insert_mixed_source_han_sans(fitz, page, (max(rect.x0 + 1.0, x), baseline), segments, fontsize=fontsize, color=(0, 0, 0))
            else:
                insert_source_han_sans(page, (max(rect.x0 + 1.0, x), baseline), target, fontsize=fontsize, color=(0, 0, 0))
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_page17_chart_axis_label_repair" if page_number == 17 else "ai_page18_20_chart_axis_label_repair",
                "source": source,
                "target": target,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": fontsize,
                "fill_strategy": "white_chart_label_background_patch",
                "font_policy": "match_source_chart_axis_label_size_color_and_rotation",
                "text_policy": "translate_chart_axis_series_and_legend_labels_after_chart_passthrough_preserve_organization_names",
            }
        )
    return repairs


def tracking_chart_repairs(tracking_payload: dict[str, Any]) -> dict[str, str]:
    from repair_pdf_drawing import normalize_text
    repairs: dict[str, str] = dict(CHART_LABEL_FALLBACKS)
    for row in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        role = str(row.get("layout_role") or row.get("layout_label") or "").lower()
        source = normalize_text(str(row.get("input") or row.get("pdf_unicode") or ""))
        output = normalize_text(str(row.get("output") or ""))
        if role not in {"chart_label", "axis", "axis_label", "fallback_line", "table_header"}:
            continue
        if len(source) < 4 or not re.search(r"[\u4e00-\u9fff]", output):
            continue
        repairs[source] = output
    return repairs


def repair_visible_strings(fitz: Any, doc: Any, mapping: dict[str, str], *, pages: set[int] | None = None, rule: str, fontsize: float = 7.2) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, replace_rect
    repairs: list[dict[str, Any]] = []
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        for source, target in mapping.items():
            if not source or not target or source == target:
                continue
            hits = page.search_for(source)[:8]
            if not hits and "\x03" in source:
                hits = page.search_for(source.replace("\x03", " "))[:8]
            for rect in hits:
                rect = expanded_rect(fitz, [rect.x0, rect.y0, rect.x1, rect.y1], page, pad=1.3, min_width=36)
                if not rect:
                    continue
                rotate = 90 if rect.height > rect.width * 1.8 else 0
                if rotate:
                    rect.x1 = min(page.rect.width, rect.x0 + max(rect.width, 32))
                else:
                    rect.x1 = min(page.rect.width - 8, max(rect.x1, rect.x0 + min(max(len(target) * fontsize * 0.8, 36), page.rect.width - rect.x0 - 8)))
                meta = replace_rect(page, rect, target, fontsize=fontsize, rotate=rotate)
                meta.update(
                    {
                        "font_policy": "match_source_chart_or_institution_label_size_color_and_rotation",
                        "text_policy": "translate_visible_chart_or_institution_label_preserve_numbers",
                    }
                )
                repairs.append({"page": page_number, "rule": rule, "source": source[:180], "target": target[:180], "rotate": rotate, **meta})
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
