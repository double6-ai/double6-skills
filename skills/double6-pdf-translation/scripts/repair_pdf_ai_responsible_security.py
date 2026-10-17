# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai responsible security：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_responsible_ai_security_safety_visible_labels(
    fitz: Any,
    source_doc: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    """修复 3.9 Security and Safety 页的固定图表/表格层。

    模型名、机构名、URL、年份和数值刻度按 protected span 保留；中文化只覆盖
    小节标题、图题、source、图例、轴标题、表头和等级标签。
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
        font_policy: str = "source_han_sans_fixed_responsible_ai_security_safety",
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

    def copy_region(source_page: Any, page: Any, page_number: int, rect_values: list[float], rule: str, source: str, target: str) -> None:
        rect = fitz.Rect(rect_values)
        meta = copy_source_region(source_page, page, rect)
        add_meta(
            page_number,
            rule,
            source,
            target,
            meta,
            policy="copy_source_security_safety_visual_region_to_restore_protected_labels_before_chinese_overlay",
            font_policy="source_region_fonts_preserved_for_security_safety_protected_labels",
        )

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
        policy: str = "translate_security_safety_fixed_label_preserve_visual_geometry",
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
        policy: str = "translate_security_safety_fixed_label_preserve_visual_geometry",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    def fixed_vertical_axis(page: Any, page_number: int, rect_values: list[float], point: tuple[float, float], target: str, source: str) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        page.insert_text(point, target, fontname=source_han_sans_fontname(page), fontsize=5.4, rotate=90, color=(0, 0, 0), overlay=True)
        add_meta(
            page_number,
            "ai_index_responsible_ai_security_safety_axis_label_repair",
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": 5.4, "fill_strategy": "white_axis_band_then_rotated_source_han"},
            policy="translate_axis_title_preserve_numeric_ticks_and_protected_model_labels",
        )

    def grade_label_rows(
        page: Any,
        page_number: int,
        rows: list[tuple[float, str, str]],
        *,
        x0: float,
        x1: float,
        rule: str,
    ) -> None:
        for y, target, source in rows:
            fixed_line(
                page,
                page_number,
                [x0, y - 13.0, x1, y + 8.0],
                (x0 + 2.0, y + 1.0),
                target,
                rule,
                fontsize=6.2,
                source=source,
                fill=(1, 1, 1),
                policy="translate_ailuminate_grade_labels_preserve_model_names_and_colored_status_squares",
            )

    def fixed_39_header(page: Any, page_number: int) -> None:
        fixed_textbox(
            page,
            page_number,
            [247.0, 24.0, 578.0, 39.5],
            "3.9 安全性与安全保障 | 负责任人工智能 | 人工智能指数报告 2026",
            "ai_index_responsible_ai_security_safety_running_header_repair",
            fontsize=5.0,
            source="3.9 SECURITY AND SAFETY | RESPONSIBLE AI | AI INDEX REPORT 2026",
            fill=sampled_background_color(page, fitz.Rect(247.0, 24.0, 578.0, 39.5)),
            color=(0.09, 0.25, 0.43),
            policy="translate_security_safety_running_header_consistently",
        )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        if has_line_in_region(source_page, "3.9 SECURITY AND SAFETY", y0=24.0, y1=40.0):
            fixed_39_header(page, page_number)

        if has_line_in_region(source_page, "AI safety institutes and network membership", y0=450.0, y1=480.0):
            fixed_line(
                page,
                page_number,
                [34.0, 213.0, 230.0, 239.0],
                (36.0, 232.0),
                "全球AI安全研究所",
                "ai_index_responsible_ai_security_safety_section_heading_repair",
                fontsize=10.8,
                source="Global AI Safety Institutes",
                fill=sampled_background_color(page, fitz.Rect(34.0, 213.0, 230.0, 239.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_security_safety_section_heading_preserve_heading_style",
            )
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 453.0, 578.0, 724.0],
                "ai_index_responsible_ai_security_safety_institute_map_source_region_restore",
                "AI safety institutes and network membership map",
                "source map restored with protected country colors and URL geometry",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 459.0, 300.0, 481.0],
                "AI安全研究所及其网络成员情况\n来源：All Tech is Human，2025 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_security_safety_institute_map_title_source_repair",
                fontsize=5.2,
                source="AI safety institutes and network membership / Source",
            )
            legend_rows = [
                ([62.0, 651.0, 158.0, 660.5], (64.0, 658.5), "已宣布（建设中）", "Announced (in development)"),
                ([62.0, 661.0, 158.0, 670.5], (64.0, 668.8), "已成立（运行中）", "Established (operational)"),
                ([62.0, 671.0, 190.0, 681.5], (64.0, 679.2), "网络成员（无正式研究所）", "Network member (no formal institute)"),
            ]
            for rect_values, point, target, source in legend_rows:
                fixed_line(page, page_number, rect_values, point, target, "ai_index_responsible_ai_security_safety_map_legend_repair", fontsize=4.9, source=source)
            fixed_line(
                page,
                page_number,
                [520.0, 706.0, 578.0, 721.0],
                (522.0, 718.0),
                "图 3.9.1",
                "ai_index_responsible_ai_security_safety_figure_label_repair",
                fontsize=6.0,
                source="Figure 3.9.1",
                fill=sampled_background_color(page, fitz.Rect(520.0, 706.0, 578.0, 721.0)),
                color=(0.09, 0.25, 0.43),
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 746.0, 455.0, 760.0],
                "18 数据来源：https://alltechishuman.org/all-tech-is-human-blog/the-global-landscape-of-ai-safety-institutes。",
                "ai_index_responsible_ai_security_safety_map_footnote_repair",
                fontsize=4.7,
                source="18 Data source: https://alltechishuman.org/all-tech-is-human-blog/the-global-landscape-of-ai-safety-institutes.",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                policy="translate_data_source_label_preserve_url",
            )

        if has_line_in_region(source_page, "HELM Safety: mean score", y0=350.0, y1=390.0):
            fixed_line(
                page,
                page_number,
                [34.0, 92.0, 130.0, 118.0],
                (36.0, 111.0),
                "基准测试",
                "ai_index_responsible_ai_security_safety_section_heading_repair",
                fontsize=10.8,
                source="Benchmarks",
                fill=sampled_background_color(page, fitz.Rect(34.0, 92.0, 130.0, 118.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_security_safety_section_heading_preserve_heading_style",
            )
            copy_region(
                source_page,
                page,
                page_number,
                [36.0, 358.0, 578.0, 682.0],
                "ai_index_responsible_ai_helm_safety_chart_source_region_restore",
                "HELM Safety mean score chart",
                "source chart restored with protected model names and numeric bars",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 360.0, 220.0, 386.0],
                "HELM Safety：平均得分\n来源：HELM，2026 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_helm_safety_chart_title_source_repair",
                fontsize=5.2,
                source="HELM Safety: mean score / Source",
            )
            fixed_vertical_axis(page, page_number, [34.0, 416.0, 47.5, 462.0], (44.5, 459.0), "平均得分", "Mean score")
            fixed_line(
                page,
                page_number,
                [525.0, 663.0, 578.0, 681.0],
                (527.0, 676.5),
                "图 3.9.2",
                "ai_index_responsible_ai_security_safety_figure_label_repair",
                fontsize=6.0,
                source="Figure 3.9.2",
                fill=sampled_background_color(page, fitz.Rect(525.0, 663.0, 578.0, 681.0)),
                color=(0.09, 0.25, 0.43),
            )

        if has_line_in_region(source_page, "Source: MLCommons, 2025", y0=715.0, y1=740.0):
            fixed_line(
                page,
                page_number,
                [34.0, 224.0, 190.0, 246.0],
                (36.0, 240.0),
                "安全基准测试结果",
                "ai_index_responsible_ai_ailuminate_section_heading_repair",
                fontsize=9.0,
                source="Safety Benchmark Results",
                fill=sampled_background_color(page, fitz.Rect(34.0, 224.0, 190.0, 246.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_ailuminate_section_heading_preserve_benchmark_name",
            )
            header_blue = (0.0, 0.33, 0.64)
            fixed_line(page, page_number, [45.0, 368.0, 90.0, 381.5], (46.0, 378.5), "名称", "ai_index_responsible_ai_ailuminate_table_header_repair", fontsize=6.0, source="Name", fill=header_blue, color=(1, 1, 1), policy="translate_ailuminate_table_headers_preserve_blue_header")
            fixed_line(page, page_number, [350.0, 368.0, 395.0, 381.5], (352.0, 378.5), "等级", "ai_index_responsible_ai_ailuminate_table_header_repair", fontsize=6.0, source="Grade", fill=header_blue, color=(1, 1, 1), policy="translate_ailuminate_table_headers_preserve_blue_header")
            rows = [
                (402.5, "很好", "Very Good"),
                (435.0, "很好", "Very Good"),
                (467.5, "很好", "Very Good"),
                (500.0, "良好", "Good"),
                (532.5, "良好", "Good"),
                (565.0, "良好", "Good"),
                (597.5, "良好", "Good"),
                (630.0, "良好", "Good"),
                (662.5, "良好", "Good"),
                (695.0, "良好", "Good"),
            ]
            grade_label_rows(page, page_number, rows, x0=367.0, x1=442.0, rule="ai_index_responsible_ai_ailuminate_grade_label_repair")
            fixed_textbox(
                page,
                page_number,
                [438.0, 721.0, 578.0, 738.0],
                "来源：MLCommons，2025年",
                "ai_index_responsible_ai_ailuminate_source_repair",
                fontsize=5.0,
                source="Source: MLCommons, 2025",
                fill=sampled_background_color(page, fitz.Rect(438.0, 721.0, 578.0, 738.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_source_label_preserve_organization_name",
            )
            fixed_line(
                page,
                page_number,
                [526.0, 742.0, 578.0, 758.0],
                (527.0, 754.0),
                "图 3.9.3",
                "ai_index_responsible_ai_security_safety_figure_label_repair",
                fontsize=6.0,
                source="Figure 3.9.3",
                fill=sampled_background_color(page, fitz.Rect(526.0, 742.0, 578.0, 758.0)),
                color=(0.09, 0.25, 0.43),
            )

        if has_line_in_region(source_page, "Source: MLCommons, 2025", y0=685.0, y1=708.0):
            header_blue = (0.0, 0.33, 0.64)
            fixed_line(page, page_number, [45.0, 113.0, 90.0, 126.5], (46.0, 123.0), "名称", "ai_index_responsible_ai_ailuminate_table_header_repair", fontsize=6.0, source="Name", fill=header_blue, color=(1, 1, 1), policy="translate_ailuminate_table_headers_preserve_blue_header")
            fixed_line(page, page_number, [286.0, 113.0, 330.0, 126.5], (288.0, 123.0), "等级", "ai_index_responsible_ai_ailuminate_table_header_repair", fontsize=6.0, source="Grade", fill=header_blue, color=(1, 1, 1), policy="translate_ailuminate_table_headers_preserve_blue_header")
            rows = [
                (141.0, "很好", "Very Good"),
                (167.0, "很好", "Very Good"),
                (193.0, "很好", "Very Good"),
                (219.0, "良好", "Good"),
                (245.0, "良好", "Good"),
                (271.0, "良好", "Good"),
                (297.0, "良好", "Good"),
                (323.0, "良好", "Good"),
                (349.0, "良好", "Good"),
                (375.0, "良好", "Good"),
                (401.0, "良好", "Good"),
                (427.0, "良好", "Good"),
                (453.0, "良好", "Good"),
                (479.0, "良好", "Good"),
                (505.0, "良好", "Good"),
                (531.0, "一般", "Fair"),
                (557.0, "一般", "Fair"),
                (583.0, "一般", "Fair"),
                (609.0, "一般", "Fair"),
                (635.0, "一般", "Fair"),
                (661.0, "一般", "Fair"),
                (687.0, "较差", "Poor"),
            ]
            grade_label_rows(page, page_number, rows, x0=299.0, x1=374.0, rule="ai_index_responsible_ai_ailuminate_grade_label_repair")
            fixed_textbox(
                page,
                page_number,
                [437.0, 689.0, 577.0, 707.0],
                "来源：MLCommons，2025年",
                "ai_index_responsible_ai_ailuminate_source_repair",
                fontsize=5.0,
                source="Source: MLCommons, 2025",
                fill=sampled_background_color(page, fitz.Rect(437.0, 689.0, 577.0, 707.0)),
                color=(0.09, 0.25, 0.43),
                policy="translate_source_label_preserve_organization_name",
            )
            fixed_line(
                page,
                page_number,
                [526.0, 709.0, 577.0, 724.0],
                (527.0, 721.0),
                "图 3.9.4",
                "ai_index_responsible_ai_security_safety_figure_label_repair",
                fontsize=6.0,
                source="Figure 3.9.4",
                fill=sampled_background_color(page, fitz.Rect(526.0, 709.0, 577.0, 724.0)),
                color=(0.09, 0.25, 0.43),
            )

    return repairs


def repair_ai_index_responsible_ai_security_safety_jailbreak_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 3.9 Security and Safety 续页的 AILuminate jailbreak 图表标签。"""
    from repair_pdf_drawing import insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []

    def add_meta(page_number: int, rule: str, source: str, target: str, meta: dict[str, Any], *, policy: str) -> None:
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": "source_han_sans_fixed_responsible_ai_security_safety_jailbreak",
                "text_policy": policy,
            }
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
        fill: tuple[float, float, float],
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_jailbreak_chart_fixed_label_preserve_chart_marks",
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

    def fixed_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float],
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_jailbreak_chart_fixed_label_preserve_chart_marks",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        if has_line_in_region(source_page, "3.9 SECURITY AND SAFETY", y0=24.0, y1=40.0):
            fixed_textbox(
                page,
                page_number,
                [247.0, 24.0, 578.0, 39.5],
                "3.9 安全性与安全保障 | 负责任人工智能 | 人工智能指数报告 2026",
                "ai_index_responsible_ai_security_safety_running_header_repair",
                fontsize=5.0,
                source="3.9 SECURITY AND SAFETY | RESPONSIBLE AI | AI INDEX REPORT 2026",
                fill=sampled_background_color(page, fitz.Rect(247.0, 24.0, 578.0, 39.5)),
                color=(0.09, 0.25, 0.43),
                policy="translate_security_safety_running_header_consistently",
            )
        if not has_line_in_region(source_page, "Jailbreak T2T Benchmark v0.5 Results", y0=100.0, y1=130.0):
            continue
        fixed_textbox(
            page,
            page_number,
            [60.0, 291.0, 292.0, 322.0],
            "系统性能分析",
            "ai_index_responsible_ai_jailbreak_chart_title_repair",
            fontsize=9.0,
            source="System Performance Analysis",
            fill=(1, 1, 1),
            color=(0.09, 0.25, 0.43),
        )
        grade_rows = [
            ([50.0, 321.0, 120.0, 334.0], (81.0, 331.0), "极佳", "Excellent", (0.0, 0.39, 0.64)),
            ([50.0, 334.0, 120.0, 349.0], (80.0, 344.5), "很好", "Very Good", (0.0, 0.58, 0.35)),
            ([50.0, 352.0, 120.0, 375.0], (81.0, 366.0), "良好", "Good", (0.0, 0.66, 0.38)),
            ([50.0, 376.0, 120.0, 401.0], (82.0, 393.0), "一般", "Fair", (1.0, 0.67, 0.14)),
            ([50.0, 432.0, 120.0, 457.0], (82.0, 447.0), "较差", "Poor", (1.0, 0.34, 0.35)),
        ]
        for rect_values, point, target, source, fill in grade_rows:
            fixed_line(
                page,
                page_number,
                rect_values,
                point,
                target,
                "ai_index_responsible_ai_jailbreak_chart_grade_band_repair",
                fontsize=5.2,
                source=source,
                fill=fill,
                color=(1, 1, 1),
                policy="translate_jailbreak_grade_band_labels_preserve_colored_bands",
            )
        fixed_textbox(
            page,
            page_number,
            [297.0, 488.0, 430.0, 506.0],
            "去标识化 SUT 编号",
            "ai_index_responsible_ai_jailbreak_chart_axis_label_repair",
            fontsize=6.0,
            source="Deidentified SUT number",
            fill=(1, 1, 1),
        )
        fixed_textbox(
            page,
            page_number,
            [247.0, 510.0, 445.0, 528.0],
            "■ 安全得分   ● 越狱得分   — 结果范围",
            "ai_index_responsible_ai_jailbreak_chart_legend_repair",
            fontsize=5.2,
            source="Safety Score / Jailbreak Score / Range of Results",
            fill=(1, 1, 1),
        )
        fixed_line(
            page,
            page_number,
            [524.0, 536.0, 578.0, 553.0],
            (526.0, 548.5),
            "图 3.9.5",
            "ai_index_responsible_ai_jailbreak_figure_label_repair",
            fontsize=6.0,
            source="Figure 3.9.5",
            fill=sampled_background_color(page, fitz.Rect(524.0, 536.0, 578.0, 553.0)),
            color=(0.09, 0.25, 0.43),
        )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
