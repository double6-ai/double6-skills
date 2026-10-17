# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai responsible culture：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_responsible_ai_cultural_language_gap_visible_labels(
    fitz: Any,
    source_doc: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    """修复 3.7 文化/语言公平性页的固定图表层。

    这一组图里的模型名、benchmark 名和 URL 应按 protected span 保留；中文化只覆盖
    图题、来源、页眉、图例、轴标题、区域名和表头/说明单元格。
    """
    from repair_pdf_ai_frontmatter import copy_source_region
    from repair_pdf_drawing import insert_source_han_sans, insert_source_han_sans_fake_bold, normalize_text, page_lines, replace_rect_source_han, sampled_background_color, source_han_sans_fontname
    from repair_pdf_nature import _redact_with_fill, draw_mixed_font_line

    repairs: list[dict[str, Any]] = []

    def add_meta(
        page_number: int,
        rule: str,
        source: str,
        target: str,
        meta: dict[str, Any],
        *,
        policy: str,
        font_policy: str = "source_han_sans_fixed_responsible_ai_cultural_language_gap",
    ) -> None:
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": font_policy,
                "text_policy": policy,
            }
        )

    def copy_region(source_page: Any, page: Any, page_number: int, rect_values: list[float], rule: str, source: str, target: str) -> None:
        rect = fitz.Rect(rect_values)
        meta = copy_source_region(source_page, page, rect)
        add_meta(
            page_number,
            rule,
            source,
            target,
            meta,
            policy="copy_source_chart_region_to_restore_protected_model_labels_before_targeted_chinese_overlay",
            font_policy="source_region_fonts_preserved_for_protected_chart_labels",
        )

    def fixed_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] | None = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_fixed_chart_label_preserve_chart_geometry",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    def fixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_fixed_chart_label_preserve_chart_geometry",
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_source_han_sans(page, point, target, fontsize=fontsize, color=color)
        add_meta(
            page_number,
            rule,
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_fill_then_source_han_line"},
            policy=policy,
        )

    def fixed_mixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] = (1, 1, 1),
        policy: str = "translate_fixed_chart_label_preserve_protected_latin_terms",
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        draw_mixed_font_line(fitz, page, point[0], point[1], target, fontsize=fontsize)
        add_meta(
            page_number,
            rule,
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_fill_then_mixed_font_line"},
            policy=policy,
        )

    def fixed_highlight(page: Any, page_number: int) -> None:
        rect = fitz.Rect(35.0, 47.0, 102.0, 61.5)
        _redact_with_fill(page, rect, (0.82, 0.9, 0.38))
        insert_source_han_sans_fake_bold(page, (36.0, 59.5), "亮点：", fontsize=7.2, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_responsible_ai_language_gap_highlight_label_repair",
            "HIGHLIGHT:",
            "亮点：",
            {"bbox": [35.0, 47.0, 102.0, 61.5], "fontsize": 7.2, "fill_strategy": "highlight_label_green_fill_then_source_han_fake_bold"},
            policy="translate_highlight_tab_label_without_touching_body_text",
        )

    def fixed_header(page: Any, page_number: int) -> None:
        fixed_textbox(
            page,
            page_number,
            [262.0, 24.0, 576.0, 39.0],
            "3.7 公平性与偏见 | 负责任人工智能 | 人工智能指数报告 2026",
            "ai_index_responsible_ai_fairness_running_header_repair",
            fontsize=5.0,
            fill=sampled_background_color(page, fitz.Rect(262.0, 24.0, 576.0, 39.0)),
            source="3.7 FAIRNESS AND BIAS | RESPONSIBLE AI | AI INDEX REPORT 2026",
            policy="translate_responsible_ai_fairness_running_header_consistently",
        )

    def fixed_vertical_axis(page: Any, page_number: int, rect_values: list[float], point: tuple[float, float], target: str, source: str) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        page.insert_text(point, target, fontname=source_han_sans_fontname(page), fontsize=5.4, rotate=90, color=(0, 0, 0), overlay=True)
        add_meta(
            page_number,
            "ai_index_responsible_ai_language_gap_chart_axis_repair",
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": 5.4, "fill_strategy": "white_axis_band_then_rotated_source_han"},
            policy="translate_axis_title_preserve_numeric_ticks_and_protected_model_labels",
        )

    def body_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] = (0.90, 0.96, 0.99),
    ) -> None:
        fixed_textbox(
            page,
            page_number,
            rect_values,
            target,
            rule,
            fontsize=fontsize,
            source=source,
            fill=fill,
            policy="translate_table_body_cell_preserve_benchmark_names_and_grid",
        )

    def has_line_in_region(page: Any, needle: str, *, y0: float, y1: float, x0: float = 0.0, x1: float = 612.0) -> bool:
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if needle not in text or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                rx0, ry0, rx1, ry1 = [float(v) for v in bbox[:4]]
            except Exception:
                continue
            if rx1 >= x0 and rx0 <= x1 and ry1 >= y0 and ry0 <= y1:
                return True
        return False

    def has_exact_line_in_region(page: Any, needle: str, *, y0: float, y1: float, x0: float = 0.0, x1: float = 612.0) -> bool:
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if text != needle or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                rx0, ry0, rx1, ry1 = [float(v) for v in bbox[:4]]
            except Exception:
                continue
            if rx1 >= x0 and rx0 <= x1 and ry1 >= y0 and ry0 <= y1:
                return True
        return False

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        combined_text = normalize_text(source_page.get_text("text") + "\n" + page.get_text("text"))
        if has_line_in_region(source_page, "Global AI cultural and linguistic diversity assessment", y0=70.0, y1=105.0):
            fixed_header(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 78.0, 576.0, 379.5],
                "ai_index_responsible_ai_cultural_diversity_map_source_region_restore",
                "Global AI cultural and linguistic diversity assessment map",
                "source map restored with protected numeric legend",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 79.0, 320.0, 103.5],
                "全球AI文化与语言多样性评估\n来源：全球负责任AI指数，2024 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_cultural_diversity_map_title_source_repair",
                fontsize=5.4,
                source="Global AI cultural and linguistic diversity assessment / Source",
            )
            fixed_line(page, page_number, [68.0, 347.0, 99.0, 359.5], (70.0, 356.5), "无数据", "ai_index_responsible_ai_cultural_diversity_no_data_legend_repair", fontsize=5.1, source="No data")
            fixed_line(page, page_number, [528.0, 366.0, 577.5, 379.5], (529.0, 377.2), "图 3.7.3", "ai_index_responsible_ai_cultural_diversity_figure_label_repair", fontsize=6.0, source="Figure 3.7.3")
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 424.0, 576.5, 723.0],
                "ai_index_responsible_ai_cultural_diversity_bar_chart_source_region_restore",
                "Share of countries with evidence chart",
                "source chart restored with protected numeric data labels",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 419.5, 576.0, 442.5],
                "按地区和类别划分，有AI文化与语言多样性证据的国家占比\n来源：全球负责任AI指数，2024 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_cultural_diversity_bar_chart_title_source_repair",
                fontsize=4.9,
                source="Share of countries with evidence on cultural and linguistic diversity in AI by region and category / Source",
            )
            fixed_line(page, page_number, [89.0, 448.0, 174.0, 459.5], (91.0, 457.3), "政府框架", "ai_index_responsible_ai_cultural_diversity_bar_legend_repair", fontsize=5.0, source="Government frameworks")
            fixed_line(page, page_number, [196.0, 448.0, 267.0, 459.5], (198.0, 457.3), "政府行动", "ai_index_responsible_ai_cultural_diversity_bar_legend_repair", fontsize=5.0, source="Government actions")
            fixed_line(page, page_number, [288.0, 448.0, 346.0, 459.5], (290.0, 457.3), "非国家行为体", "ai_index_responsible_ai_cultural_diversity_bar_legend_repair", fontsize=4.8, source="Nonstate actors")
            fixed_vertical_axis(page, page_number, [35.0, 539.0, 47.0, 603.0], (44.2, 602.0), "国家占比", "Share of countries")
            region_labels = [
                ([93.0, 677.0, 116.0, 688.5], (94.0, 686.3), "非洲", "Africa"),
                ([146.0, 677.0, 207.0, 688.5], (147.0, 686.3), "亚洲和大洋洲", "Asia and Oceania"),
                ([229.5, 677.0, 267.0, 688.5], (231.0, 686.3), "加勒比", "Caribbean"),
                ([306.5, 677.0, 333.0, 688.5], (308.0, 686.3), "欧洲", "Europe"),
                ([370.5, 677.0, 413.0, 688.5], (372.0, 686.3), "中东", "Middle East"),
                ([437.0, 677.0, 489.0, 688.5], (439.0, 686.3), "北美", "North America"),
                ([505.0, 676.5, 564.0, 698.0], (508.0, 685.8), "南美和\n中美", "South and Central America"),
            ]
            for rect_values, point, target, source in region_labels:
                fixed_line(page, page_number, rect_values, point, target, "ai_index_responsible_ai_cultural_diversity_region_label_repair", fontsize=4.8, source=source)
            fixed_line(page, page_number, [528.0, 710.0, 577.5, 723.5], (529.0, 721.2), "图 3.7.4", "ai_index_responsible_ai_cultural_diversity_figure_label_repair", fontsize=6.0, source="Figure 3.7.4")
        if has_line_in_region(source_page, "HELM Arabic: mean score", y0=375.0, y1=410.0):
            fixed_header(page, page_number)
            fixed_highlight(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 374.0, 576.0, 684.0],
                "ai_index_responsible_ai_helm_arabic_chart_source_region_restore",
                "HELM Arabic chart region",
                "source chart restored with protected model labels",
            )
            fixed_textbox(page, page_number, [50.0, 384.0, 210.0, 407.0], "HELM Arabic：平均得分\n来源：HELM，2026 | 图表：2026年AI Index报告", "ai_index_responsible_ai_helm_arabic_chart_title_source_repair", fontsize=5.2, source="HELM Arabic: mean score / Source")
            fixed_vertical_axis(page, page_number, [50.0, 449.0, 61.0, 489.0], (58.0, 487.5), "平均得分", "Mean score")
            fixed_line(page, page_number, [523.0, 670.0, 577.5, 683.0], (524.0, 681.2), "图 3.7.5", "ai_index_responsible_ai_helm_arabic_figure_label_repair", fontsize=6.0, source="Figure 3.7.5")
        if has_line_in_region(source_page, "Indic LLM Arena", y0=165.0, y1=190.0):
            fixed_header(page, page_number)
            fixed_highlight(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 157.0, 576.0, 464.0],
                "ai_index_responsible_ai_indic_llm_arena_chart_source_region_restore",
                "Indic LLM Arena chart region",
                "source chart restored with protected model labels",
            )
            fixed_textbox(page, page_number, [53.0, 169.0, 260.0, 190.0], "Indic LLM Arena\n来源：Indic LLM Arena排行榜，2026 | 图表：2026年AI Index报告", "ai_index_responsible_ai_indic_llm_arena_chart_title_source_repair", fontsize=5.2, source="Indic LLM Arena / Source")
            fixed_vertical_axis(page, page_number, [51.0, 240.0, 61.5, 260.5], (59.0, 259.2), "得分", "Score")
            fixed_line(page, page_number, [303.0, 427.0, 326.0, 438.0], (304.5, 436.4), "模型", "ai_index_responsible_ai_indic_llm_arena_model_axis_repair", fontsize=5.2, source="Model")
            fixed_line(page, page_number, [522.0, 450.0, 577.0, 464.0], (523.0, 462.0), "图 3.7.6", "ai_index_responsible_ai_indic_llm_arena_figure_label_repair", fontsize=6.0, source="Figure 3.7.6")
        if has_line_in_region(source_page, "Slobench: accuracy", y0=84.0, y1=108.0):
            fixed_header(page, page_number)
            fixed_highlight(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 82.0, 578.0, 389.0],
                "ai_index_responsible_ai_slobench_chart_source_region_restore",
                "Slobench chart region",
                "source chart restored with protected model labels",
            )
            fixed_textbox(page, page_number, [48.0, 89.0, 145.0, 104.0], "Slobench：准确率", "ai_index_responsible_ai_slobench_chart_title_repair", fontsize=6.6, source="Slobench: accuracy")
            fixed_textbox(page, page_number, [48.0, 102.0, 315.0, 112.5], "来源：斯洛文尼亚方言-COPA基准排行榜，2026 | 图表：2026年AI Index报告", "ai_index_responsible_ai_slobench_chart_source_repair", fontsize=4.9, source="Source: Slovene DIALECT-COPA benchmark leaderboard, 2026 | Chart: 2026 AI Index report")
            fixed_line(page, page_number, [98.0, 119.0, 164.0, 130.5], (99.0, 128.8), "标准斯洛文尼亚语", "ai_index_responsible_ai_slobench_legend_repair", fontsize=4.8, source="Standard Slovenian")
            fixed_mixed_line(page, page_number, [183.0, 119.0, 234.0, 130.5], (184.0, 128.8), "Cerkno 方言", "ai_index_responsible_ai_slobench_legend_repair", fontsize=4.8, source="Cerkno dialect")
            fixed_vertical_axis(page, page_number, [46.0, 188.0, 56.5, 233.0], (54.5, 232.0), "准确率（%）", "Accuracy (%)")
            fixed_line(page, page_number, [289.0, 349.0, 313.0, 360.5], (290.5, 358.8), "模型", "ai_index_responsible_ai_slobench_model_axis_repair", fontsize=5.2, source="Model")
            fixed_line(page, page_number, [524.0, 375.0, 579.0, 389.0], (525.0, 387.0), "图 3.7.7", "ai_index_responsible_ai_slobench_figure_label_repair", fontsize=6.0, source="Figure 3.7.7")
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 541.0, 578.0, 724.0],
                "ai_index_responsible_ai_africa_table_source_region_restore",
                "Africa benchmark table",
                "source table restored before Chinese cell overlays",
            )
            fixed_line(page, page_number, [62.0, 576.0, 115.0, 590.0], (64.0, 587.5), "基准", "ai_index_responsible_ai_africa_table_header_repair", fontsize=6.4, source="Benchmark", fill=(0.09, 0.25, 0.43), color=(1, 1, 1))
            fixed_line(page, page_number, [194.0, 576.0, 282.0, 590.0], (196.0, 587.5), "覆盖语言", "ai_index_responsible_ai_africa_table_header_repair", fontsize=6.4, source="Languages covered", fill=(0.09, 0.25, 0.43), color=(1, 1, 1))
            fixed_line(page, page_number, [441.0, 576.0, 470.0, 590.0], (442.0, 587.5), "重点", "ai_index_responsible_ai_africa_table_header_repair", fontsize=6.4, source="Focus", fill=(0.09, 0.25, 0.43), color=(1, 1, 1))
            body_textbox(page, page_number, [196.0, 612.0, 292.0, 626.5], "64种非洲语言", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.7, source="64 African languages")
            body_textbox(page, page_number, [362.0, 610.0, 552.0, 635.0], "跨NLU、生成、问答/知识与数学的多任务LLM评测（15项任务；22个数据集）", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.2, source="Multi-task LLM evaluation across NLU, generation, QA/knowledge, and math (15 tasks; 22 datasets)")
            body_textbox(page, page_number, [147.0, 646.0, 322.0, 672.0], "覆盖西非、东非、南部非洲和中非的17种低资源非洲语言", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.2, source="17 low-resource African languages across West/East/Southern/Central Africa")
            body_textbox(page, page_number, [358.0, 646.0, 554.0, 681.5], "人工翻译套件，覆盖NLI（AfriXNLI）、数学推理（AfriMGSM）和多选知识问答（AfriMMLU）", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.2, source="Human-translated suite covering NLI (AfriXNLI), math reasoning (AfriMGSM), and multi-choice knowledge QA (AfriMMLU)")
            body_textbox(page, page_number, [168.0, 690.0, 305.0, 706.5], "Darija（阿拉伯文字 + 拉丁“Arabizi”）", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.2, source="Darija (Arabic script + Latin “Arabizi”)")
            body_textbox(page, page_number, [362.0, 688.0, 551.0, 721.5], "英语↔Darija机器翻译基准，强调文化语境和区域差异（850个条目）", "ai_index_responsible_ai_africa_table_cell_repair", fontsize=5.2, source="English↔Darija machine translation benchmark emphasizing cultural context and regional variation (850 entries)")
        if has_line_in_region(source_page, "ASIA, MENA (ARABIC), CENTRAL ASIA", y0=145.0, y1=170.0):
            fixed_header(page, page_number)
            fixed_highlight(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 78.0, 578.0, 746.0],
                "ai_index_responsible_ai_language_benchmark_directory_source_region_restore",
                "Language benchmark directory table: Asia, MENA (Arabic), Central Asia",
                "source table restored before Chinese directory overlays",
            )
            body_textbox(page, page_number, [176.0, 86.0, 330.0, 105.5], "豪萨语（+ 与英语代码转换）", "ai_index_responsible_ai_language_benchmark_directory_cell_repair", fontsize=5.3, source="Hausa (+ code-switched English)")
            body_textbox(page, page_number, [360.0, 86.0, 558.0, 124.0], "情感/评论类基准，来自5,000条豪萨语YouTube评论，反映常见代码转换", "ai_index_responsible_ai_language_benchmark_directory_cell_repair", fontsize=5.1, source="Sentiment/review-style benchmark from 5,000 Hausa YouTube comments reflecting common code-switching")
            fixed_line(page, page_number, [46.0, 148.0, 332.0, 170.0], (49.0, 165.2), "亚洲、MENA（阿拉伯语）、中亚", "ai_index_responsible_ai_language_benchmark_directory_region_heading_repair", fontsize=8.2, source="ASIA, MENA (ARABIC), CENTRAL ASIA", fill=(0.90, 0.96, 0.99), color=(0.09, 0.25, 0.43), policy="translate_language_benchmark_directory_region_heading_preserve_table_geometry")
            fixed_line(page, page_number, [62.0, 181.0, 122.0, 197.0], (64.0, 194.3), "基准", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Benchmark", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            fixed_line(page, page_number, [192.0, 181.0, 282.0, 197.0], (194.0, 194.3), "覆盖语言", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Languages covered", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            fixed_line(page, page_number, [441.0, 181.0, 474.0, 197.0], (443.0, 194.3), "重点", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Focus", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            directory_cells = [
                ([151.0, 218.0, 340.0, 237.5], "多种印度语言 + 英语克里奥尔语", "Many Indian languages + English-creoles"),
                ([360.0, 216.0, 558.0, 252.0], "众包、人在环路排行榜，评估印度语境中的语言、文化与安全（AI4Bharat；由 Google Cloud 支持）", "Crowd-sourced, human-in-the-loop leaderboard evaluating language, culture, and safety in Indian contexts"),
                ([151.0, 264.0, 340.0, 283.5], "菲律宾语、印度尼西亚语、泰米尔语、泰语、越南语", "Filipino, Indonesian, Tamil, Thai, Vietnamese"),
                ([360.0, 263.0, 558.0, 291.0], "东南亚整体评测，覆盖多任务中的语言与文化能力", "Southeast Asian holistic evaluation of linguistic and cultural competence across multiple tasks"),
                ([151.0, 308.0, 340.0, 326.5], "他加禄语、Taglish", "Tagalog, Taglish"),
                ([360.0, 306.0, 558.0, 337.5], "整体菲律宾语基准，覆盖理解、推理和生成；明确包含代码转换", "Holistic Filipino benchmark spanning understanding, reasoning, and generation; explicitly covers code-switching"),
                ([151.0, 354.0, 340.0, 373.0], "阿拉伯语", "Arabic"),
                ([360.0, 350.0, 558.0, 385.0], "透明、可复现的阿拉伯LLM评测排行榜，建立在成熟阿拉伯基准上（与 Arabic.ai 合作）", "Transparent, reproducible Arabic LLM evaluation leaderboard built on established Arabic benchmarks"),
                ([151.0, 400.0, 340.0, 419.0], "阿拉伯语", "Arabic"),
                ([360.0, 397.0, 558.0, 433.0], "社区驱动的阿拉伯基准和平台，采用盲评；78项任务覆盖14个类别（52K个样例）", "Community-driven Arabic benchmark and platform with blind evaluation; 78 tasks across 14 categories"),
                ([151.0, 446.0, 340.0, 464.5], "土耳其语", "Turkish"),
                ([360.0, 443.0, 558.0, 477.0], "统一土耳其语LLM基准，基于22个数据集，覆盖7项任务，并提供并排排行榜", "Unified Turkish LLM benchmark built from 22 datasets covering 7 tasks, with a side-by-side leaderboard"),
                ([151.0, 489.0, 340.0, 516.0], "阿塞拜疆语、克里米亚鞑靼语、卡拉卡尔帕克语、哈萨克语、吉尔吉斯语、鞑靼语、土耳其语、维吾尔语、乌兹别克语", "Azerbaijani, Crimean Tatar, Karakalpak, Kazakh, Kyrgyz, Tatar, Turkish, Uyghur, Uzbek"),
                ([360.0, 490.0, 558.0, 526.0], "面向突厥语族的原生多语种语言理解基准，使用11个学科的初高中问题", "Natively developed multilingual language-understanding benchmark for Turkic languages using middle-/high-school questions across 11 subjects"),
                ([151.0, 537.0, 340.0, 556.0], "吉尔吉斯语", "Kyrgyz"),
                ([360.0, 534.0, 558.0, 570.0], "吉尔吉斯语深度理解与推理套件，结合原生基准和翻译/后编辑的国际任务", "Suite for deep understanding and reasoning in Kyrgyz, combining native benchmarks with translated/post-edited international tasks"),
                ([151.0, 583.0, 340.0, 601.5], "亚美尼亚语", "Armenian"),
                ([360.0, 580.0, 558.0, 616.5], "亚美尼亚语LLM基准，结合大学入学考试与 MMLU-Pro-Hy（1,000题翻译样本）", "Armenian LLM benchmark combining university entrance exams with MMLU-Pro-Hy"),
                ([151.0, 629.0, 340.0, 647.5], "格鲁吉亚语", "Georgian"),
                ([360.0, 627.0, 558.0, 660.0], "人工整理的100题逻辑与推理基准，并由母语者验证", "Manually curated 100-question benchmark for logical and inferential reasoning, validated by native speakers"),
                ([151.0, 676.0, 340.0, 694.5], "粤语", "Cantonese"),
                ([360.0, 673.0, 558.0, 706.0], "七任务粤语NLU基准（句法/语义、NLI、情感、标注、解析）", "Seven-task Cantonese NLU benchmark"),
                ([150.0, 711.0, 344.0, 743.5], "藏语", "Tibetan"),
                ([356.0, 710.0, 560.0, 747.0], "衡量LLM藏语理解能力的大规模基准", "Large-scale benchmark measuring LLM proficiency in Tibetan language understanding"),
            ]
            for rect_values, target, source in directory_cells:
                body_textbox(page, page_number, rect_values, target, "ai_index_responsible_ai_language_benchmark_directory_cell_repair", fontsize=4.9, source=source)
        if has_line_in_region(source_page, "EUROPE", y0=91.0, y1=112.0) and has_line_in_region(source_page, "BenCzechMark", y0=160.0, y1=180.0):
            fixed_header(page, page_number)
            fixed_highlight(page, page_number)
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 93.0, 578.0, 620.0],
                "ai_index_responsible_ai_language_benchmark_directory_source_region_restore",
                "Language benchmark directory table: Europe",
                "source table restored before Chinese directory overlays",
            )
            fixed_line(page, page_number, [46.0, 91.0, 140.0, 113.0], (49.0, 108.2), "欧洲", "ai_index_responsible_ai_language_benchmark_directory_region_heading_repair", fontsize=8.4, source="EUROPE", fill=(0.90, 0.96, 0.99), color=(0.09, 0.25, 0.43), policy="translate_language_benchmark_directory_region_heading_preserve_table_geometry")
            fixed_line(page, page_number, [62.0, 124.0, 122.0, 140.0], (64.0, 137.3), "基准", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Benchmark", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            fixed_line(page, page_number, [192.0, 124.0, 282.0, 140.0], (194.0, 137.3), "覆盖语言", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Languages covered", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            fixed_line(page, page_number, [441.0, 124.0, 474.0, 140.0], (443.0, 137.3), "重点", "ai_index_responsible_ai_language_benchmark_directory_header_repair", fontsize=6.4, source="Focus", fill=(0.09, 0.25, 0.43), color=(1, 1, 1), policy="translate_language_benchmark_directory_headers_preserve_links")
            europe_cells = [
                ([151.0, 163.0, 340.0, 181.5], "捷克语", "Czech"),
                ([360.0, 160.0, 558.0, 196.0], "以捷克语为中心的综合基准，包含50项任务、多种格式/指标，并支持显著性感知聚合", "Comprehensive Czech-centric benchmark with 50 tasks, multiple formats/metrics, and significance-aware aggregation"),
                ([151.0, 211.0, 340.0, 229.5], "捷克语、斯洛伐克语、乌克兰语", "Czech, Slovak, Ukrainian"),
                ([360.0, 208.0, 558.0, 243.5], "开放式区域问答基准，含文本和视觉 grounding，由母语者整理并配有英文翻译", "Open-ended regional QA benchmark with text and visual grounding, curated by native speakers with English translations"),
                ([151.0, 256.0, 340.0, 274.5], "法语", "French"),
                ([360.0, 253.0, 558.0, 288.5], "23任务法语自然语言理解（NLU）基准，强调法语相关语言现象（用于评测94个LLM）", "23-task French natural language understanding benchmark emphasizing French-relevant linguistic phenomena"),
                ([151.0, 301.0, 340.0, 319.5], "爱沙尼亚语", "Estonian"),
                ([360.0, 298.0, 558.0, 333.0], "由7个数据集构建，覆盖知识、语法/词汇、摘要和语境理解", "Benchmark built from seven datasets covering knowledge, grammar/vocabulary, summarization, and contextual comprehension"),
                ([151.0, 347.0, 340.0, 374.0], "巴斯克语、加泰罗尼亚语、加利西亚语、西班牙语、葡萄牙语、英语", "Basque, Catalan, Galician, Spanish, Portuguese, English"),
                ([360.0, 345.0, 558.0, 381.0], "大型可扩展基准，整合101个数据集，覆盖22类任务（如毒性、摘要），并由社区驱动更新", "Large, extensible benchmark integrating 101 datasets across 22 task categories"),
                ([151.0, 394.0, 340.0, 420.0], "巴斯克语、加泰罗尼亚语、加利西亚语、欧洲西班牙语、欧洲葡萄牙语", "Basque, Catalan, Galician, European Spanish, European Portuguese"),
                ([360.0, 393.0, 558.0, 421.0], "基于LM Evaluation Harness框架构建的多任务基准（62项任务；179个子任务）", "Multi-task benchmark built on the LM Evaluation Harness framework"),
                ([151.0, 441.0, 340.0, 459.5], "波兰语", "Polish"),
                ([360.0, 438.0, 558.0, 474.0], "600道人工编写问题，评估波兰历史、地理、文化/传统、艺术、语法和词汇", "600 manually crafted questions evaluating Polish history, geography, culture/tradition, arts, grammar, and vocabulary"),
                ([151.0, 487.0, 340.0, 505.5], "波兰语", "Polish"),
                ([360.0, 484.0, 558.0, 520.0], "基于波兰全国考试的基准（约19K道封闭式问题，覆盖154个领域）", "Exam-based benchmark drawn from Polish national exams"),
                ([151.0, 533.0, 340.0, 551.5], "意大利语", "Italian"),
                ([360.0, 530.0, 558.0, 565.5], "具备文化感知的意大利语NLU基准，含10,000道多选题，覆盖12个领域", "Culture-aware Italian NLU benchmark with 10,000 multiple-choice questions spanning 12 domains"),
                ([151.0, 579.0, 340.0, 597.5], "斯洛文尼亚语", "Slovenian"),
                ([360.0, 576.0, 558.0, 612.0], "包含多个排行榜的评测平台，包括 DIALECT-COPA（标准语 vs. 方言）和斯洛文尼亚语音识别", "Evaluation platform with multiple leaderboards, including DIALECT-COPA and Slovene speech recognition"),
            ]
            for rect_values, target, source in europe_cells:
                body_textbox(page, page_number, rect_values, target, "ai_index_responsible_ai_language_benchmark_directory_cell_repair", fontsize=4.9, source=source)
            fixed_line(page, page_number, [524.0, 665.0, 578.0, 682.0], (525.0, 678.0), "图 3.7.8", "ai_index_responsible_ai_language_benchmark_directory_figure_label_repair", fontsize=6.0, source="Figure 3.7.8", fill=sampled_background_color(page, fitz.Rect(524.0, 665.0, 578.0, 682.0)), color=(0.09, 0.25, 0.43), policy="translate_language_benchmark_directory_figure_label")
    return repairs


def repair_ai_index_responsible_ai_transparency_visible_labels(
    fitz: Any,
    source_doc: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    """修复 3.8 透明度页的固定图表层。

    Openness/FMTI 图表中的模型名、公司 logo、百分比和热力图单元格是高密度
    protected visual object；翻译只覆盖标题、来源、图例、轴和维度名。
    """
    from repair_pdf_ai_frontmatter import copy_source_region
    from repair_pdf_drawing import insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color, source_han_sans_fontname
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []

    def add_meta(
        page_number: int,
        rule: str,
        source: str,
        target: str,
        meta: dict[str, Any],
        *,
        policy: str,
        font_policy: str = "source_han_sans_fixed_responsible_ai_transparency",
    ) -> None:
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": font_policy,
                "text_policy": policy,
            }
        )

    def copy_region(source_page: Any, page: Any, page_number: int, rect_values: list[float], rule: str, source: str, target: str) -> None:
        rect = fitz.Rect(rect_values)
        meta = copy_source_region(source_page, page, rect)
        add_meta(
            page_number,
            rule,
            source,
            target,
            meta,
            policy="copy_source_transparency_chart_region_to_restore_protected_model_names_logos_and_dense_labels",
            font_policy="source_region_fonts_preserved_for_transparency_chart_protected_labels",
        )

    def fixed_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] | None = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_transparency_chart_label_preserve_dense_visual_object",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    def fixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float] = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_transparency_chart_label_preserve_dense_visual_object",
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_source_han_sans(page, point, target, fontsize=fontsize, color=color)
        add_meta(
            page_number,
            rule,
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_fill_then_source_han_line"},
            policy=policy,
        )

    def fixed_vertical_axis(page: Any, page_number: int, rect_values: list[float], point: tuple[float, float], target: str, source: str) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        page.insert_text(point, target, fontname=source_han_sans_fontname(page), fontsize=5.4, rotate=90, color=(0, 0, 0), overlay=True)
        add_meta(
            page_number,
            "ai_index_responsible_ai_transparency_axis_label_repair",
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": 5.4, "fill_strategy": "white_axis_band_then_rotated_source_han"},
            policy="translate_transparency_axis_title_preserve_numeric_ticks_and_protected_model_labels",
        )

    def has_line_in_region(page: Any, needle: str, *, y0: float, y1: float, x0: float = 0.0, x1: float = 612.0) -> bool:
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if needle not in text or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                rx0, ry0, rx1, ry1 = [float(v) for v in bbox[:4]]
            except Exception:
                continue
            if rx1 >= x0 and rx0 <= x1 and ry1 >= y0 and ry0 <= y1:
                return True
        return False

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        if has_line_in_region(source_page, "Openness index by components", y0=350.0, y1=385.0):
            fixed_line(
                page,
                page_number,
                [36.0, 198.0, 270.0, 220.0],
                (36.0, 215.0),
                "开放性指数",
                "ai_index_responsible_ai_transparency_section_heading_repair",
                fontsize=10.5,
                source="The Openness Index",
                fill=sampled_background_color(page, fitz.Rect(36.0, 198.0, 270.0, 220.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_transparency_section_heading_preserve_heading_style",
            )
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 356.0, 576.0, 668.0],
                "ai_index_responsible_ai_openness_index_chart_source_region_restore",
                "Openness index by components chart",
                "source chart restored with protected model names and numeric labels",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 360.0, 258.0, 383.0],
                "开放性指数按组件分解\n来源：Artificial Analysis，2026 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_openness_index_chart_title_source_repair",
                fontsize=5.2,
                source="Openness index by components / Source",
            )
            legend_rows = [
                ([94.0, 391.0, 238.0, 403.5], (96.0, 401.0), "模型可用性", "Model availability"),
                ([94.0, 407.0, 276.0, 419.5], (96.0, 417.0), "透明度：方法", "Transparency methodology"),
                ([94.0, 422.5, 306.0, 435.0], (96.0, 432.5), "透明度：训练后数据", "Transparency: post-training data"),
                ([94.0, 438.0, 306.0, 450.5], (96.0, 448.0), "透明度：预训练数据", "Transparency: pre-training data"),
            ]
            for rect_values, point, target, source in legend_rows:
                fixed_line(page, page_number, rect_values, point, target, "ai_index_responsible_ai_openness_index_legend_repair", fontsize=5.0, source=source)
            fixed_vertical_axis(page, page_number, [36.0, 448.0, 48.0, 488.0], (45.0, 486.5), "得分", "Score")
            fixed_line(page, page_number, [523.0, 649.0, 578.0, 667.0], (525.0, 663.5), "图 3.8.1", "ai_index_responsible_ai_openness_index_figure_label_repair", fontsize=6.0, source="Figure 3.8.1", fill=sampled_background_color(page, fitz.Rect(523.0, 649.0, 578.0, 667.0)), color=(0.09, 0.25, 0.43))
            fixed_line(
                page,
                page_number,
                [36.0, 681.0, 330.0, 704.0],
                (36.0, 698.0),
                "基础模型透明度指数",
                "ai_index_responsible_ai_transparency_section_heading_repair",
                fontsize=10.5,
                source="Foundation Model Transparency Index",
                fill=sampled_background_color(page, fitz.Rect(36.0, 681.0, 330.0, 704.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_transparency_section_heading_preserve_heading_style",
            )
        if has_line_in_region(source_page, "Foundation Model Transparency Index Scores by Domain, 2025", y0=190.0, y1=220.0):
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 193.0, 578.0, 451.0],
                "ai_index_responsible_ai_fmti_domain_chart_source_region_restore",
                "Foundation Model Transparency Index scores by domain chart",
                "source chart restored with protected model names, logos and numeric bars",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 194.0, 330.0, 217.0],
                "2025年按领域划分的基础模型透明度指数得分\n来源：2025年基础模型透明度指数",
                "ai_index_responsible_ai_fmti_domain_chart_title_source_repair",
                fontsize=5.2,
                source="Foundation Model Transparency Index Scores by Domain, 2025 / Source",
            )
            fixed_line(page, page_number, [525.0, 408.0, 578.0, 426.0], (527.0, 422.8), "图 3.8.2", "ai_index_responsible_ai_fmti_domain_figure_label_repair", fontsize=6.0, source="Figure 3.8.2", fill=sampled_background_color(page, fitz.Rect(525.0, 408.0, 578.0, 426.0)), color=(0.09, 0.25, 0.43))
            fixed_line(page, page_number, [292.0, 420.0, 314.0, 435.0], (294.0, 432.5), "得分", "ai_index_responsible_ai_fmti_domain_axis_label_repair", fontsize=5.0, source="Score", fill=(1, 1, 1))
            legend_rows = [
                ([428.0, 366.0, 472.0, 380.0], (430.0, 377.5), "上游", "Upstream"),
                ([428.0, 377.0, 472.0, 391.0], (430.0, 388.5), "模型", "Model"),
                ([428.0, 388.0, 478.0, 402.0], (430.0, 399.5), "下游", "Downstream"),
            ]
            for rect_values, point, target, source in legend_rows:
                fixed_line(page, page_number, rect_values, point, target, "ai_index_responsible_ai_fmti_domain_legend_repair", fontsize=5.2, source=source)
            fixed_textbox(
                page,
                page_number,
                [428.0, 365.0, 474.0, 402.0],
                "上游\n模型\n下游",
                "ai_index_responsible_ai_fmti_domain_legend_block_repair",
                fontsize=5.2,
                source="Upstream / Model / Downstream",
                fill=None,
                policy="redraw_three_line_transparency_domain_legend_after_coordinate_calibration",
            )
        if has_line_in_region(source_page, "Foundation Model Transparency Index Scores by Major Dimensions of Transparency, 2025", y0=470.0, y1=500.0):
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 465.0, 578.0, 733.0],
                "ai_index_responsible_ai_fmti_dimension_heatmap_source_region_restore",
                "Foundation Model Transparency Index major dimensions heatmap",
                "source heatmap restored with protected model names, logos and numeric cells",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 469.0, 360.0, 492.0],
                "2025年各主要透明度维度下的基础模型透明度指数得分\n来源：2025年基础模型透明度指数",
                "ai_index_responsible_ai_fmti_dimension_heatmap_title_source_repair",
                fontsize=5.0,
                source="Foundation Model Transparency Index Scores by Major Dimensions of Transparency, 2025 / Source",
            )
            fixed_vertical_axis(page, page_number, [34.0, 550.0, 49.0, 665.0], (45.0, 664.0), "透明度主要维度", "Major Dimensions of Transparency")
            row_labels = [
                ([68.0, 515.0, 145.0, 525.0], (70.0, 523.2), "数据获取", "Data Acquisition"),
                ([68.0, 528.0, 145.0, 538.0], (70.0, 536.2), "数据属性", "Data Properties"),
                ([68.0, 541.0, 145.0, 551.0], (70.0, 549.2), "计算", "Compute"),
                ([68.0, 554.0, 145.0, 564.0], (70.0, 562.2), "模型信息", "Model Information"),
                ([68.0, 567.0, 145.0, 577.0], (70.0, 575.2), "模型访问", "Model Access"),
                ([68.0, 580.0, 145.0, 590.0], (70.0, 588.2), "能力", "Capabilities"),
                ([68.0, 593.0, 145.0, 603.0], (70.0, 601.2), "风险", "Risks"),
                ([68.0, 606.0, 145.0, 616.0], (70.0, 614.2), "模型缓解", "Model Mitigations"),
                ([68.0, 619.0, 145.0, 629.0], (70.0, 627.2), "发布", "Release"),
                ([68.0, 632.0, 145.0, 642.0], (70.0, 640.2), "使用数据", "Usage Data"),
                ([68.0, 645.0, 145.0, 655.0], (70.0, 653.2), "影响", "Impact"),
                ([42.0, 647.5, 146.0, 660.0], (44.0, 657.0), "部署后监测", "Post-deployment Monitoring"),
                ([54.0, 660.0, 118.0, 670.0], (56.0, 668.0), "模型行为政策", "Model Behavior Policy"),
                ([58.0, 671.0, 118.0, 681.0], (60.0, 679.0), "可接受使用政策", "Acceptable Use Policy"),
                ([52.0, 682.0, 118.0, 693.0], (54.0, 691.0), "下游缓解", "Downstream Mitigations"),
                ([125.0, 716.0, 170.0, 727.0], (127.0, 725.0), "平均", "Average"),
            ]
            for rect_values, point, target, source in row_labels:
                fixed_line(page, page_number, rect_values, point, target, "ai_index_responsible_ai_fmti_dimension_row_label_repair", fontsize=4.4, source=source)
            fixed_line(page, page_number, [520.0, 710.0, 578.0, 729.0], (522.0, 725.0), "图 3.8.3", "ai_index_responsible_ai_fmti_dimension_figure_label_repair", fontsize=6.0, source="Figure 3.8.3", fill=sampled_background_color(page, fitz.Rect(520.0, 710.0, 578.0, 729.0)), color=(0.09, 0.25, 0.43))
            fixed_textbox(
                page,
                page_number,
                [36.0, 733.0, 578.0, 760.0],
                "17 数据、劳动力、算力和方法属于上游指标；模型基础信息、访问、能力、风险与缓解属于模型层指标；分发、使用政策、反馈和影响属于下游指标。",
                "ai_index_responsible_ai_fmti_dimension_footnote_repair",
                fontsize=4.9,
                source="Data, labor, compute, and methods were upstream indicators...",
                fill=sampled_background_color(page, fitz.Rect(36.0, 733.0, 578.0, 760.0)),
                policy="translate_transparency_footnote_preserve_number_and_meaning",
            )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
