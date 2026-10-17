# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai medicine：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_medicine_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 AI Index Medicine 章节的固定可见标签。"""
    from repair_pdf_drawing import insert_ai_figure_label, insert_source_han_sans, insert_source_han_sans_fake_bold, normalize_text, page_lines, replace_rect_source_han
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []
    blue_bg = (4 / 255, 91 / 255, 158 / 255)
    white = (1, 1, 1)
    yellow = (214 / 255, 232 / 255, 0 / 255)

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

    def add_meta(
        page_number: int,
        rule: str,
        source: str,
        target: str,
        rect: Any,
        *,
        color: tuple[float, float, float],
        draw_meta: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "page": page_number,
            "rule": rule,
            "source": source,
            "target": target,
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "fixed_medicine_toc_blue_slot_redraw",
            "font_policy": "source_han_sans_fixed_ai_index_medicine_toc_label",
            "text_policy": "translate_medicine_toc_entries_preserve_page_numbers_rules_and_protected_model_benchmark_names",
            "color": "yellow" if color == yellow else "white",
        }
        if isinstance(draw_meta, dict):
            payload.update({k: v for k, v in draw_meta.items() if k != "bbox"})
        repairs.append(payload)

    def fixed_toc_label(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float = 8.1,
        color: tuple[float, float, float] = white,
        rule: str = "ai_index_medicine_toc_entry_repair",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=blue_bg, color=color)
        add_meta(page_number, rule, source, target, rect, color=color, draw_meta=meta)

    def add_profile_meta(
        page_number: int,
        rule: str,
        source: str,
        target: str,
        rect: Any,
        draw_meta: dict[str, Any] | None = None,
        *,
        policy: str,
        color_name: str = "black",
    ) -> None:
        payload = {
            "page": page_number,
            "rule": rule,
            "source": source,
            "target": target,
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "fixed_medicine_6_1_slot_redraw",
            "font_policy": "source_han_sans_fixed_ai_index_medicine_6_1_label",
            "text_policy": policy,
            "color": color_name,
        }
        if isinstance(draw_meta, dict):
            payload.update({k: v for k, v in draw_meta.items() if k != "bbox"})
        repairs.append(payload)

    def fixed_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float,
        fill: tuple[float, float, float] = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        rotate: int = 0,
        rule: str = "ai_index_medicine_6_1_visible_label_repair",
        policy: str = "translate_medicine_6_1_stable_visible_label_preserve_chart_geometry",
        color_name: str = "black",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, rotate=rotate, fill=fill, color=color)
        add_profile_meta(page_number, rule, source, target, rect, meta, policy=policy, color_name=color_name)

    def fixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        *,
        source: str,
        fontsize: float,
        fill: tuple[float, float, float] = (1, 1, 1),
        color: tuple[float, float, float] = (0, 0, 0),
        rule: str = "ai_index_medicine_6_1_visible_label_repair",
        policy: str = "translate_medicine_6_1_stable_visible_label_preserve_chart_geometry",
        color_name: str = "black",
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_source_han_sans(page, point, target, fontsize=fontsize, color=color)
        add_profile_meta(
            page_number,
            rule,
            source,
            target,
            rect,
            {"fontsize": fontsize, "fill_strategy": "fixed_region_redraw"},
            policy=policy,
            color_name=color_name,
        )

    def fixed_figure_label(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        *,
        source: str,
        fontsize: float = 5.8,
        fill: tuple[float, float, float] = (1, 1, 1),
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_ai_figure_label(fitz, page, point, target, fontsize=fontsize, color=blue_bg)
        add_profile_meta(
            page_number,
            "ai_index_medicine_6_1_figure_label_repair",
            source,
            target,
            rect,
            {"fontsize": fontsize, "fill_strategy": "fixed_figure_label_redraw"},
            policy="translate_medicine_6_1_figure_label_preserve_footer_geometry",
            color_name="medicine_blue",
        )

    def fixed_chart_title_source(
        page: Any,
        page_number: int,
        title_rect: list[float],
        title: str,
        *,
        source_title: str,
        source_line: str,
        source_rect: list[float] | None = None,
        fontsize: float = 6.2,
    ) -> None:
        fixed_textbox(
            page,
            page_number,
            title_rect,
            title,
            source=source_title,
            fontsize=fontsize,
            rule="ai_index_medicine_6_1_chart_title_source_repair",
            policy="translate_medicine_chart_title_and_credit_as_separate_compact_lines",
        )
        if source_rect:
            fixed_textbox(
                page,
                page_number,
                source_rect,
                source_line,
                source="Source: RAISE Health, 2026 | Chart: 2026 AI Index report",
                fontsize=4.5,
                rule="ai_index_medicine_6_1_chart_title_source_repair",
                policy="translate_medicine_chart_title_and_credit_as_separate_compact_lines",
            )

    def restore_source_label_band(
        source_page: Any,
        page: Any,
        page_number: int,
        rect_values: list[float],
        *,
        source: str,
        rule: str = "ai_index_medicine_6_1_source_label_band_restore",
        policy: str = "restore_protected_model_dataset_axis_labels_from_source_then_overlay_translated_stable_slots",
    ) -> None:
        rect = fitz.Rect(rect_values)
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
        try:
            page.show_pdf_page(rect, source_doc, page_number - 1, clip=rect, overlay=True, keep_proportion=False)
            fill_strategy = "source_region_passthrough"
        except Exception:
            fill_strategy = "source_region_passthrough_failed_white_cover_only"
        add_profile_meta(
            page_number,
            rule,
            source,
            "source protected label band",
            rect,
            {"fontsize": None, "fill_strategy": fill_strategy},
            policy=policy,
            color_name="source_passthrough",
        )

    def fixed_table_header(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float,
        fill: tuple[float, float, float],
    ) -> None:
        fixed_textbox(
            page,
            page_number,
            rect_values,
            target,
            source=source,
            fontsize=fontsize,
            fill=fill,
            color=(1, 1, 1),
            rule="ai_index_medicine_6_1_cofolding_table_header_repair",
            policy="translate_cofolding_table_header_pills_preserve_model_names_checks_and_grid",
            color_name="white",
        )

    def fixed_table_header_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        *,
        source: str,
        fontsize: float,
        fill: tuple[float, float, float],
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_source_han_sans_fake_bold(page, point, target, fontsize=fontsize, color=(1, 1, 1))
        add_profile_meta(
            page_number,
            "ai_index_medicine_6_1_cofolding_table_header_repair",
            source,
            target,
            rect,
            {"fontsize": fontsize, "fill_strategy": "fixed_table_header_full_slot_redraw"},
            policy="cover_full_header_slot_before_translating_to_avoid_source_target_overlap",
            color_name="white",
        )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]

        if has_line_in_region(source_page, "6.1 THE CENTRAL DOGMA", y0=20.0, y1=42.0):
            fixed_textbox(
                page,
                page_number,
                [260.0, 24.0, 576.0, 40.0],
                "6.1 中心法则 | 医学 | 人工智能指数报告 2026",
                source="6.1 THE CENTRAL DOGMA | MEDICINE | AI INDEX REPORT 2026",
                fontsize=5.0,
                color=blue_bg,
                rule="ai_index_medicine_6_1_running_header_repair",
                policy="translate_medicine_running_header_preserve_right_header_band",
                color_name="medicine_blue",
            )

        if has_line_in_region(source_page, "Research Volume", y0=245.0, y1=285.0):
            fixed_textbox(
                page,
                page_number,
                [34.0, 254.0, 170.0, 281.0],
                "研究规模",
                source="Research Volume",
                fontsize=13.0,
                color=blue_bg,
                rule="ai_index_medicine_6_1_section_heading_repair",
                policy="translate_medicine_section_heading_preserve_blue_style",
                color_name="medicine_blue",
            )
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 450.0, 410.0, 466.8],
                "2024年至2025年AI驱动蛋白质研究论文数量对比",
                source_title="Number of AI-driven protein research publications, 2024 vs. 2025",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 466.0, 322.0, 480.0],
                fontsize=5.2,
            )
            fixed_textbox(
                page,
                page_number,
                [34.0, 545.0, 48.0, 625.0],
                "论文数量",
                fontsize=4.9,
                source="Number of publications",
                fill=(1, 1, 1),
                rotate=90,
            )
            category_specs = [
                ([96.0, 696.0, 174.0, 719.0], "功能预测", "Function prediction", (104.0, 708.0)),
                ([224.0, 696.0, 290.0, 719.0], "蛋白质结构\n预测", "Protein structure prediction", None),
                ([352.0, 696.0, 404.0, 719.0], "蛋白质-药物\n相互作用", "Protein-drug interactions", None),
                ([468.0, 696.0, 532.0, 719.0], "合成蛋白质\n设计", "Synthetic protein design", None),
            ]
            for rect_values, target, source, point in category_specs:
                if point:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.9, source=source)
                else:
                    fixed_textbox(page, page_number, rect_values, target, fontsize=4.7, source=source)
            fixed_line(page, page_number, [288.0, 720.0, 348.0, 733.0], (299.0, 729.4), "研究领域", fontsize=4.8, source="Reseach domain")
            fixed_figure_label(page, page_number, [526.0, 744.0, 578.0, 758.0], (528.0, 755.0), "图 6.1.1", source="Figure 6.1.1")

        if has_line_in_region(source_page, "Number of publications on AI for drug discovery", y0=70.0, y1=106.0):
            fixed_chart_title_source(
                page,
                page_number,
                [38.0, 78.0, 344.0, 95.0],
                "2018年至2025年AI药物发现相关出版物数量",
                source_title="Number of publications on AI for drug discovery, 2018–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[38.0, 94.5, 238.0, 106.0],
                fontsize=5.2,
            )
            fixed_textbox(page, page_number, [34.0, 186.0, 48.0, 269.0], "论文数量", fontsize=4.9, source="Number of publications", rotate=90)
            fixed_figure_label(page, page_number, [526.0, 372.0, 578.0, 387.0], (528.0, 383.3), "图 6.1.2", source="Figure 6.1.2")
            fixed_textbox(
                page,
                page_number,
                [34.0, 403.0, 156.0, 431.0],
                "公开数据集",
                source="Public Datasets",
                fontsize=13.0,
                color=blue_bg,
                rule="ai_index_medicine_6_1_section_heading_repair",
                policy="translate_medicine_section_heading_preserve_blue_style",
                color_name="medicine_blue",
            )

        if has_line_in_region(source_page, "Size of public datasets for molecular and cellular biology", y0=66.0, y1=96.0):
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 70.0, 330.0, 87.0],
                "分子与细胞生物学公开数据集规模",
                source_title="Size of public datasets for molecular and cellular biology",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 86.0, 238.0, 98.0],
                fontsize=5.5,
            )
            legend_specs = [
                ([90.0, 103.0, 126.0, 115.0], "结构", "Structural", (94.0, 112.0)),
                ([144.0, 103.0, 208.0, 115.0], "序列/功能", "Sequence/function", (148.0, 112.0)),
                ([226.0, 103.0, 291.0, 115.0], "结合/活性", "Binding/bioactivity", (230.0, 112.0)),
                ([309.0, 103.0, 378.0, 115.0], "预测/模拟", "Predicted/simulated", (313.0, 112.0)),
                ([395.0, 103.0, 434.0, 115.0], "单细胞", "Single-cell", (399.0, 112.0)),
                ([451.0, 103.0, 500.0, 115.0], "宏基因组", "Metagenomic", (455.0, 112.0)),
            ]
            for rect_values, target, source, point in legend_specs:
                fixed_line(
                    page,
                    page_number,
                    rect_values,
                    point,
                    target,
                    fontsize=4.6,
                    source=source,
                    rule="ai_index_medicine_6_1_chart_legend_repair",
                    policy="translate_medicine_dataset_legend_labels_preserve_color_swatches",
                )
            fixed_textbox(page, page_number, [34.0, 154.0, 48.0, 260.0], "条目数（对数）", fontsize=4.4, source="Number of entries (log scale)", rotate=90)
            fixed_textbox(page, page_number, [250.0, 337.0, 365.0, 351.0], "数据集（发布年份）", fontsize=4.8, source="Dataset (release year)")
            fixed_figure_label(page, page_number, [525.0, 330.0, 578.0, 346.0], (527.0, 342.0), "图 6.1.3", source="Figure 6.1.3")
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 491.0, 320.0, 507.0],
                "2020年至2025年部分生物医学数据集发布规模",
                source_title="Size of select biomedical datasets at release, 2020–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 506.0, 286.0, 528.0],
                fontsize=5.0,
            )
            fixed_textbox(page, page_number, [34.0, 584.0, 48.0, 657.0], "出版物数量", fontsize=4.7, source="Number of publications", rotate=90)
            fixed_figure_label(page, page_number, [526.0, 744.0, 578.0, 758.0], (528.0, 755.4), "图 6.1.4", source="Figure 6.1.4")

        if has_line_in_region(source_page, "Sequence-Based Models: Protein Language Models", y0=82.0, y1=112.0):
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 464.0, 292.0, 479.0],
                "2020年至2025年蛋白质序列模型规模",
                source_title="Size of protein sequencing models, 2020–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 478.0, 274.0, 489.0],
                fontsize=5.2,
            )
            fixed_textbox(page, page_number, [34.0, 505.0, 48.0, 618.0], "参数数量（十亿）", fontsize=4.3, source="Number of parameters (in billions)", rotate=90)
            restore_source_label_band(source_page, page, page_number, [66.0, 636.0, 542.0, 738.0], source="protein sequencing model x-axis label band")
            fixed_figure_label(page, page_number, [526.0, 741.0, 578.0, 756.0], (528.0, 752.8), "图 6.1.5", source="Figure 6.1.5")

        if has_line_in_region(source_page, "Performance of protein language models on ProteinGym", y0=82.0, y1=106.0):
            fixed_chart_title_source(
                page,
                page_number,
                [35.0, 86.0, 368.0, 101.5],
                "2021年至2025年ProteinGym上蛋白质语言模型表现",
                source_title="Performance of protein language models on ProteinGym, 2021–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[35.0, 101.0, 274.0, 112.0],
                fontsize=5.0,
            )
            fixed_textbox(page, page_number, [34.0, 120.0, 48.0, 214.0], "平均相关性（Spearman）", fontsize=4.1, source="Avg. correlation (Spearman)", rotate=90)
            restore_source_label_band(source_page, page, page_number, [70.0, 224.0, 542.0, 351.0], source="ProteinGym model x-axis label band")
            fixed_textbox(page, page_number, [268.0, 350.0, 346.0, 362.0], "模型（参数）", fontsize=4.8, source="Model (parameters)")
            fixed_figure_label(page, page_number, [526.0, 363.0, 578.0, 378.0], (528.0, 374.5), "图 6.1.6", source="Figure 6.1.6")
            fixed_textbox(
                page,
                page_number,
                [34.0, 499.0, 360.0, 525.0],
                "结构预测与共折叠模型",
                source="Structure Prediction and Cofolding Models",
                fontsize=13.0,
                color=blue_bg,
                rule="ai_index_medicine_6_1_section_heading_repair",
                policy="translate_medicine_section_heading_preserve_blue_style",
                color_name="medicine_blue",
            )

        if has_line_in_region(source_page, "Training data sources for cofolding models", y0=110.0, y1=140.0):
            fixed_chart_title_source(
                page,
                page_number,
                [35.0, 116.0, 316.0, 134.0],
                "用于共折叠模型训练的数据源，2025年",
                source_title="Training data sources for cofolding models, 2025",
                source_line="",
                source_rect=None,
                fontsize=7.0,
            )
            table_blue_dark = (27 / 255, 71 / 255, 116 / 255)
            table_blue = blue_bg
            fixed_table_header_line(page, page_number, [46.0, 154.0, 145.0, 186.0], (80.0, 174.8), "模型", source="Model", fontsize=8.2, fill=table_blue_dark)
            fixed_table_header(page, page_number, [154.0, 156.0, 232.0, 183.0], "结构数据\n（实验）", source="Structural data (experimental)", fontsize=5.8, fill=table_blue)
            fixed_table_header(page, page_number, [238.0, 156.0, 316.0, 183.0], "结构数据\n（蒸馏）", source="Structural data (distilled)", fontsize=5.8, fill=table_blue)
            fixed_table_header(page, page_number, [330.0, 156.0, 386.0, 184.0], "分子\n动力学", source="Molecular dynamics", fontsize=5.8, fill=table_blue)
            fixed_table_header(page, page_number, [404.0, 158.0, 480.0, 181.0], "结合亲和力", source="Binding affinity", fontsize=6.0, fill=table_blue)
            fixed_table_header(page, page_number, [492.0, 158.0, 562.0, 181.0], "RNA结构", source="RNA structure", fontsize=6.0, fill=table_blue)
            fixed_figure_label(page, page_number, [524.0, 376.0, 580.0, 392.0], (526.0, 388.0), "图 6.1.6¹", source="Figure 6.1.6¹")

        if has_line_in_region(source_page, "Size of protein structure prediction models", y0=76.0, y1=104.0):
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 80.0, 330.0, 98.0],
                "2021年至2025年蛋白质结构预测模型规模",
                source_title="Size of protein structure prediction models, 2021–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 96.0, 274.0, 108.0],
                fontsize=5.2,
            )
            fixed_textbox(page, page_number, [34.0, 124.0, 48.0, 250.0], "模型参数数量（对数）", fontsize=4.1, source="Number of model parameters (log scale)", rotate=90)
            restore_source_label_band(source_page, page, page_number, [75.0, 254.0, 578.0, 376.0], source="protein structure model x-axis label band")
            fixed_figure_label(page, page_number, [526.0, 372.0, 578.0, 388.0], (528.0, 383.8), "图 6.1.8", source="Figure 6.1.8")
            fixed_chart_title_source(
                page,
                page_number,
                [36.0, 442.0, 330.0, 460.0],
                "FoldBench：2024年至2025年蛋白质共折叠表现",
                source_title="FoldBench: protein cofolding performance, 2024–25",
                source_line="来源：RAISE Health，2026 | 图表：2026年AI Index报告",
                source_rect=[36.0, 458.0, 274.0, 470.0],
                fontsize=5.1,
            )
            fixed_textbox(page, page_number, [34.0, 508.0, 48.0, 604.0], "准确率", fontsize=4.8, source="Accuracy", rotate=90)
            restore_source_label_band(source_page, page, page_number, [75.0, 632.0, 578.0, 730.0], source="FoldBench model x-axis label band")
            fixed_textbox(page, page_number, [282.0, 718.0, 360.0, 731.0], "模型（参数）", fontsize=4.8, source="Model (parameters)")
            fixed_figure_label(page, page_number, [526.0, 734.0, 578.0, 750.0], (528.0, 746.2), "图 6.1.9", source="Figure 6.1.9")

        is_medicine_toc = (
            has_line_in_region(source_page, "Contents", y0=100.0, y1=130.0, x0=20.0, x1=120.0)
            and has_line_in_region(source_page, "6.1 The Central Dogma", y0=160.0, y1=184.0)
            and has_line_in_region(source_page, "6.2 Clinical Applications", y0=488.0, y1=510.0)
        )
        if not is_medicine_toc:
            continue

        toc_items = [
            ([36.0, 165.0, 185.0, 183.0], "6.1 中心法则", "6.1 The Central Dogma", 7.0, white),
            ([64.0, 186.0, 190.0, 205.0], "研究规模", "Research Volume", 8.5, white),
            ([64.0, 214.0, 190.0, 233.0], "公开数据集", "Public Datasets", 8.5, white),
            ([82.0, 236.0, 235.0, 256.0], "分子与细胞生物学", "Molecular and Cellular Biology", 8.0, white),
            ([64.0, 279.0, 250.0, 312.0], "基于序列的模型：\n蛋白质语言模型", "Sequence-Based Models: Protein Language Models", 7.2, white),
            ([64.0, 318.0, 250.0, 342.0], "结构预测与共折叠模型", "Structure Prediction and Cofolding Models", 7.2, white),
            ([64.0, 382.0, 254.0, 410.0], "虚拟细胞模型与基因组基础模型", "Virtual Cell Models and Genomic Foundation Models", 7.0, white),
            ([64.0, 452.0, 238.0, 480.0], "亮点：自动化与智能体式生物医学发现", "Highlight: Automated and Agentic Biomedical Discovery", 7.2, yellow),
            ([36.0, 493.0, 190.0, 511.0], "6.2 临床应用", "6.2 Clinical Applications", 7.0, white),
            ([68.0, 512.0, 156.0, 533.0], "影像", "Imaging", 8.5, white),
            ([82.0, 532.0, 235.0, 550.0], "数据规模与可用性", "Data Scale and Availability", 7.8, white),
            ([82.0, 552.0, 225.0, 570.0], "建模方法", "Modeling Approaches", 7.8, white),
            ([82.0, 570.0, 245.0, 589.0], "前瞻性临床试验", "Prospective Clinical Trials", 7.8, white),
            ([68.0, 589.0, 250.0, 624.0], "亮点：LLM临床推理表现", "Highlight: LLM Clinical Reasoning Performance", 7.4, yellow),
            ([68.0, 624.0, 246.0, 660.0], "亮点：临床医学中的AI智能体", "Highlight: AI Agents in Clinical Medicine", 7.4, yellow),
            ([64.0, 688.0, 250.0, 724.0], "FDA授权的AI/ML医疗设备", "FDA-Authorized AI/ML-Enabled Devices", 7.4, white),
            ([395.0, 140.0, 510.0, 170.0], "按临床专科划分的设备", "Devices by Clinical Specialty", 8.1, white),
            ([395.0, 174.0, 520.0, 190.0], "行业格局", "Industry Landscape", 8.1, white),
            ([377.0, 193.0, 542.0, 224.0], "2025年的企业级部署", "Enterprise-Scale Deployments in 2025", 8.0, white),
            ([395.0, 229.0, 545.0, 253.0], "环境式AI文档记录", "Ambient AI Documentation", 8.0, white),
            ([395.0, 263.0, 548.0, 298.0], "AI驱动的脓毒症预测", "AI-Powered Sepsis Prediction", 8.0, white),
            ([395.0, 282.0, 552.0, 315.0], "临床工作流中的生成式AI", "Generative AI in Clinical Workflows", 8.0, white),
            ([346.0, 335.0, 538.0, 366.0], "亮点：医学中的数字孪生技术", "Highlight: Digital Twins in Medicine", 7.6, yellow),
            ([328.0, 363.0, 555.0, 398.0], "6.3 患者参与度与健康相关AI综述", "6.3 Patient Engagement and Health AI Reviews", 8.0, white),
            ([328.0, 458.0, 555.0, 493.0], "6.4 伦理考量：规模、全球健康与关注重点", "6.4 Ethical Considerations: Scale, Global Health, and Priorities", 8.0, white),
        ]
        for rect_values, target, source, fontsize, color in toc_items:
            fixed_toc_label(page, page_number, rect_values, target, source=source, fontsize=fontsize, color=color)
        line_color = (67 / 255, 160 / 255, 210 / 255)
        for x0, x1, y in [
            (49.0, 296.0, 155.0),
            (49.0, 296.0, 181.0),
            (49.0, 296.0, 220.0),
            (49.0, 296.0, 241.0),
            (49.0, 296.0, 275.0),
            (49.0, 296.0, 310.0),
            (49.0, 296.0, 344.0),
            (49.0, 296.0, 379.0),
            (49.0, 296.0, 414.0),
            (49.0, 296.0, 447.0),
            (49.0, 296.0, 482.0),
            (49.0, 296.0, 511.0),
            (49.0, 296.0, 531.0),
            (49.0, 296.0, 550.0),
            (49.0, 296.0, 569.0),
            (49.0, 296.0, 588.0),
            (49.0, 296.0, 623.0),
            (49.0, 296.0, 657.0),
            (49.0, 296.0, 687.0),
            (49.0, 296.0, 723.0),
            (328.0, 576.0, 170.0),
            (328.0, 576.0, 189.0),
            (328.0, 576.0, 222.0),
            (328.0, 576.0, 253.0),
            (328.0, 576.0, 276.0),
            (328.0, 576.0, 315.0),
            (328.0, 576.0, 349.0),
            (328.0, 576.0, 397.0),
            (328.0, 576.0, 493.0),
            (328.0, 576.0, 527.0),
        ]:
            page.draw_line((x0, y), (x1, y), color=line_color, width=0.35, overlay=True)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_medicine_toc_separator_line_restore",
                "source": "Medicine TOC separator rules",
                "target": "restored separator rules after localized label redraw",
                "line_count": 30,
                "stroke_color": [67, 160, 210],
                "text_policy": "restore_toc_rule_lines_after_fixed_blue_slot_redraw",
            }
        )

    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
