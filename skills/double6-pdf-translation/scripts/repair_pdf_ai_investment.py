# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai investment：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_economy_investment_chart_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 Economy 4.2 投资与基础设施页的固定图表标签。"""
    from repair_pdf_ai_frontmatter import copy_source_region
    from repair_pdf_drawing import insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []

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
        normalized_needle = normalize_text(needle)
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if text != normalized_needle or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                rx0, ry0, rx1, ry1 = [float(v) for v in bbox[:4]]
            except Exception:
                continue
            if rx1 >= x0 and rx0 <= x1 and ry1 >= y0 and ry0 <= y1:
                return True
        return False

    def add_meta(page_number: int, rule: str, source: str, target: str, meta: dict[str, Any], *, policy: str) -> None:
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": "source_han_sans_fixed_economy_investment_chart_label",
                "text_policy": policy,
            }
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
        rotate: int = 0,
        policy: str = "translate_economy_investment_chart_fixed_label_preserve_bars_ticks_values",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color, rotate=rotate)
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
        fill: tuple[float, float, float],
        color: tuple[float, float, float] = (0, 0, 0),
        policy: str = "translate_economy_investment_chart_fixed_label_preserve_bars_ticks_values",
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

    def chart_title_source(
        page: Any,
        page_number: int,
        rect_values: list[float],
        title: str,
        source: str,
        figure: str,
        *,
        credit_label: str = "图表",
        source_line: str | None = None,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        insert_source_han_sans(page, (rect.x0 + 1.5, rect.y0 + 10.0), title, fontsize=5.2, color=(0, 0, 0))
        visible_source_line = source_line or f"来源：Quid，2025 | {credit_label}：2026年AI Index报告"
        insert_source_han_sans(page, (rect.x0 + 1.5, rect.y0 + 17.6), visible_source_line, fontsize=4.6, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_economy_investment_chart_title_source_repair",
            source,
            f"{title} / {visible_source_line}",
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": 5.2, "fill_strategy": "fixed_white_region_then_title_source_lines", "figure": figure},
            policy="redraw_economy_investment_chart_title_source_as_compact_chinese_lines",
        )

    def geographic_label_rows(
        page: Any,
        page_number: int,
        rows: list[tuple[float, str, str]],
        *,
        x0: float,
        x1: float,
        rule: str = "ai_index_economy_investment_geographic_label_repair",
    ) -> None:
        for y, source, target in rows:
            fixed_line(
                page,
                page_number,
                [x0, y - 1.1, x1, y + 8.9],
                (x1 - 3.0 - len(target) * 5.0, y + 6.7),
                target,
                rule,
                fontsize=5.0,
                source=source,
                fill=(1, 1, 1),
                policy="translate_geographic_chart_label_preserve_bars_ticks_values",
            )

    def table_label_rows(page: Any, page_number: int) -> None:
        rows = [
            (544.9, "Over 1 billion", "10亿以上"),
            (558.7, "500 million – 1 billion", "5亿-10亿"),
            (572.4, "100 million – 500 million", "1亿-5亿"),
            (586.2, "50 million – 100 million", "5000万-1亿"),
            (599.9, "Under 50 million", "5000万以下"),
            (613.7, "Undisclosed", "未披露"),
            (627.4, "Total", "总计"),
        ]
        fixed_line(
            page,
            page_number,
            [39.0, 526.0, 132.0, 539.2],
            (41.0, 535.8),
            "融资规模（美元）",
            "ai_index_economy_investment_table_header_repair",
            fontsize=5.0,
            source="Funding size (US dollars)",
            fill=(1, 1, 1),
            policy="translate_funding_size_table_header_preserve_years_and_values",
        )
        for y, source, target in rows:
            fixed_line(
                page,
                page_number,
                [39.0, y - 1.2, 130.0, y + 9.2],
                (41.0, y + 6.8),
                target,
                "ai_index_economy_investment_table_row_label_repair",
                fontsize=5.0,
                source=source,
                fill=(1, 1, 1),
                policy="translate_funding_size_table_row_label_preserve_numeric_columns",
            )

    def focus_area_label_box(
        page: Any,
        page_number: int,
        rect_values: list[float],
        source: str,
        target: str,
        *,
        fontsize: float = 4.8,
        rule: str = "ai_index_economy_investment_focus_area_label_repair",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=(1, 1, 1))
        add_meta(
            page_number,
            rule,
            source,
            target,
            meta,
            policy="translate_focus_area_chart_label_preserve_bars_ticks_and_numeric_values",
        )

    def state_map_legend_rows(page: Any, page_number: int) -> None:
        rows = [
            (452.2, "No data", "无数据"),
            (461.7, "<$100M", "<1亿美元"),
            (471.3, "$100M $500M", "1亿-5亿美元"),
            (480.8, "$500M $1B", "5亿-10亿美元"),
            (490.3, "$1B $5B", "10亿-50亿美元"),
            (499.8, "$5B $20B", "50亿-200亿美元"),
            (509.3, "$20B+", "200亿美元以上"),
        ]
        for y, source, target in rows:
            fixed_line(
                page,
                page_number,
                [430.0, y - 7.4, 506.0, y + 2.4],
                (431.5, y),
                target,
                "ai_index_economy_investment_state_map_legend_repair",
                fontsize=4.7,
                source=source,
                fill=(1, 1, 1),
                policy="translate_state_map_legend_preserve_color_squares_and_state_labels",
            )

    def legend_rows(page: Any, page_number: int) -> None:
        rect = fitz.Rect(92.0, 516.0, 158.0, 557.5)
        _redact_with_fill(page, rect, (1, 1, 1))
        for y, text in [(523.3, "并购"), (533.6, "少数股权"), (543.9, "私人投资"), (554.2, "公开募股")]:
            insert_source_han_sans(page, (101.5, y), text, fontsize=4.9, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_economy_investment_legend_label_repair",
            "Merger/acquisition / Minority stake / Private investment / Public offering",
            "并购 / 少数股权 / 私人投资 / 公开募股",
            {"bbox": [92.0, 516.0, 158.0, 557.5], "fontsize": 4.9, "fill_strategy": "fixed_white_region_preserve_legend_color_squares"},
            policy="translate_stacked_investment_legend_text_preserve_color_squares",
        )

    def cleanup_fragment(
        page: Any,
        page_number: int,
        rect_values: list[float],
        source: str,
        *,
        redraw_text: str | None = None,
        redraw_point: tuple[float, float] | None = None,
        fontsize: float = 5.4,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        if redraw_text and redraw_point:
            insert_source_han_sans(page, redraw_point, redraw_text, fontsize=fontsize, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_economy_investment_chart_fragment_cleanup",
            source,
            redraw_text or "",
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_white_cleanup_then_optional_tick_redraw"},
            policy="remove_fragmented_source_or_chart_label_residue_without_touching_bars",
        )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    green_bg = (12 / 255, 110 / 255, 108 / 255)
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        has_42_header = has_line_in_region(source_page, "INVESTMENT AND INFRASTRUCTURE", y0=20.0, y1=45.0)
        if has_42_header:
            fixed_line(
                page,
                page_number,
                [206.0, 27.0, 578.0, 40.0],
                (214.0, 36.8),
                "4.2 投资与基础设施 | 经济 | 人工智能指数报告 2026",
                "ai_index_economy_investment_running_header_repair",
                fontsize=4.9,
                source="4.2 INVESTMENT AND INFRASTRUCTURE | ECONOMY | AI INDEX REPORT 2026",
                fill=green_bg,
                color=(1, 1, 1),
                policy="translate_economy_investment_running_header_consistently",
            )
        if has_line_in_region(source_page, "Private Investment Activity", y0=65.0, y1=100.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 72.0, 210.0, 94.0],
                "私营投资活动",
                "ai_index_economy_private_investment_activity_heading_repair",
                fontsize=12.0,
                source="Private Investment Activity",
                fill=green_bg,
                color=(0.62, 0.88, 0.86),
                policy="translate_private_investment_subsection_heading_preserve_green_background",
            )
        if has_line_in_region(source_page, "Global corporate investment in AI by investment activity", y0=485.0, y1=510.0):
            chart_title_source(
                page,
                page_number,
                [38.0, 488.5, 350.0, 512.5],
                "2013-2025年全球企业AI投资（按投资类型）",
                "Global corporate investment in AI by investment activity, 2013–25 / Source: Quid, 2025",
                "Figure 4.2.1",
            )
            legend_rows(page, page_number)
            fixed_textbox(page, page_number, [34.0, 562.0, 47.0, 690.0], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [526.0, 749.0, 578.0, 764.0], (527.0, 760.8), "图 4.2.1", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.1", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in AI, 2013", y0=198.0, y1=225.0):
            chart_title_source(page, page_number, [50.0, 203.0, 276.0, 225.5], "2013-2025年全球AI私人投资", "Global private investment in AI, 2013–25 / Source: Quid, 2025", "Figure 4.2.2")
            cleanup_fragment(page, page_number, [50.0, 225.5, 76.0, 236.0], "residual wrapped chart source line overlapping top tick", redraw_text="350", redraw_point=(58.8, 235.1), fontsize=5.4)
            fixed_textbox(page, page_number, [47.0, 272.0, 59.5, 395.5], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [526.0, 464.0, 578.0, 478.0], (527.0, 475.0), "图 4.2.2", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.2", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in generative AI", y0=492.0, y1=520.0):
            chart_title_source(page, page_number, [50.0, 496.0, 300.0, 518.0], "2019-2025年全球生成式AI私人投资", "Global private investment in generative AI, 2019–25 / Source: Quid, 2025", "Figure 4.2.3")
            cleanup_fragment(page, page_number, [98.0, 518.0, 108.0, 535.5], "residual Chart/source label glyphs")
            fixed_textbox(page, page_number, [47.0, 563.0, 59.5, 684.5], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [526.0, 750.5, 578.0, 765.0], (527.0, 762.0), "图 4.2.3", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.3", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Number of newly funded AI companies in the world", y0=205.0, y1=235.0):
            chart_title_source(page, page_number, [43.0, 211.0, 330.0, 232.5], "2013-2025年全球新获融资AI公司数", "Number of newly funded AI companies in the world, 2013–25 / Source: Quid, 2025", "Figure 4.2.4")
            cleanup_fragment(page, page_number, [94.0, 233.0, 102.0, 250.5], "residual Chart/source label glyphs")
            fixed_textbox(page, page_number, [41.0, 308.0, 54.0, 377.0], "公司数量", "ai_index_economy_investment_company_axis_repair", fontsize=5.3, source="Number of companies", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [526.0, 475.5, 578.0, 490.0], (527.0, 486.8), "图 4.2.4", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.4", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Number of newly funded generative AI companies", y0=505.0, y1=532.0):
            chart_title_source(page, page_number, [62.0, 509.0, 382.0, 529.5], "2019-2025年全球新获融资生成式AI公司数", "Number of newly funded generative AI companies in the world, 2019–25 / Source: Quid, 2025", "Figure 4.2.5")
            cleanup_fragment(page, page_number, [96.0, 529.0, 115.5, 541.5], "residual wrapped chapter/source glyphs")
            fixed_textbox(page, page_number, [61.0, 598.0, 73.0, 663.0], "公司数量", "ai_index_economy_investment_company_axis_repair", fontsize=5.3, source="Number of companies", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [526.0, 751.5, 578.0, 765.5], (527.0, 762.8), "图 4.2.5", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.5", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Average size of global AI private investment events", y0=120.0, y1=150.0):
            chart_title_source(
                page,
                page_number,
                [37.0, 125.0, 358.0, 150.8],
                "2013-2025年全球AI私人投资事件平均规模",
                "Average size of global AI private investment events, 2013–25 / Source: Quid, 2025",
                "Figure 4.2.6",
            )
            fixed_textbox(
                page,
                page_number,
                [34.0, 196.0, 48.0, 348.0],
                "平均投资（百万美元）",
                "ai_index_economy_investment_average_axis_repair",
                fontsize=5.0,
                source="Average investment (in millions of US dollars)",
                fill=(1, 1, 1),
                rotate=90,
            )
            fixed_line(page, page_number, [525.0, 433.0, 578.0, 448.0], (527.0, 444.5), "图 4.2.6", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.6", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global AI private investment events by funding size", y0=482.0, y1=522.0):
            chart_title_source(
                page,
                page_number,
                [35.0, 486.0, 320.0, 522.0],
                "2024-2025年全球AI私人投资事件（按融资规模）",
                "Global AI private investment events by funding size, 2024 vs. 2025 / Source: Quid, 2025",
                "Figure 4.2.7",
                credit_label="表格",
            )
            table_label_rows(page, page_number)
            fixed_line(page, page_number, [288.0, 667.0, 340.0, 681.5], (290.0, 678.4), "图 4.2.7", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.7", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Geographic Distribution of Private Investment", y0=80.0, y1=105.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 82.0, 285.0, 103.0],
                "私人投资的地理分布",
                "ai_index_economy_private_investment_geographic_heading_repair",
                fontsize=12.0,
                source="Geographic Distribution of Private Investment",
                fill=(1, 1, 1),
                color=green_bg,
                policy="translate_private_investment_geographic_subsection_heading",
            )
        if has_line_in_region(source_page, "Global private investment in AI by geographic area, 2025", y0=255.0, y1=280.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 260.0, 300.0, 280.5],
                "2025年全球AI私人投资（按地理区域）",
                "Global private investment in AI by geographic area, 2025 / Source: Quid, 2025",
                "Figure 4.2.8",
            )
            geographic_label_rows(
                page,
                page_number,
                [
                    (468.1, "Sweden", "瑞典"),
                    (454.9, "Japan", "日本"),
                    (441.7, "Belgium", "比利时"),
                    (428.5, "South Korea", "韩国"),
                    (415.3, "Singapore", "新加坡"),
                    (402.1, "Saudi Arabia", "沙特阿拉伯"),
                    (388.9, "Australia", "澳大利亚"),
                    (375.7, "Israel", "以色列"),
                    (362.4, "Germany", "德国"),
                    (349.2, "India", "印度"),
                    (336.0, "Canada", "加拿大"),
                    (322.8, "France", "法国"),
                    (309.6, "United Kingdom", "英国"),
                    (296.4, "China", "中国"),
                    (283.2, "United States", "美国"),
                ],
                x0=38.0,
                x1=88.5,
            )
            fixed_line(page, page_number, [226.0, 487.5, 345.0, 498.0], (228.0, 495.0), "总投资（十亿美元）", "ai_index_economy_investment_x_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1))
            fixed_line(page, page_number, [526.0, 498.0, 578.0, 512.0], (528.0, 508.8), "图 4.2.8", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.8", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Number of newly funded AI companies by geographic area", y0=508.0, y1=535.0):
            chart_title_source(
                page,
                page_number,
                [37.0, 512.0, 330.0, 533.5],
                "2025年按地理区域划分的新获融资AI公司数",
                "Number of newly funded AI companies by geographic area, 2025 / Source: Quid, 2025",
                "Figure 4.2.9",
            )
            geographic_label_rows(
                page,
                page_number,
                [
                    (723.4, "Spain", "西班牙"),
                    (710.0, "Switzerland", "瑞士"),
                    (696.7, "Australia", "澳大利亚"),
                    (683.3, "Italy", "意大利"),
                    (669.9, "Singapore", "新加坡"),
                    (656.5, "Japan", "日本"),
                    (643.1, "South Korea", "韩国"),
                    (629.7, "Israel", "以色列"),
                    (616.4, "Canada", "加拿大"),
                    (603.0, "France", "法国"),
                    (589.6, "Germany", "德国"),
                    (576.2, "India", "印度"),
                    (562.8, "China", "中国"),
                    (549.5, "United Kingdom", "英国"),
                    (536.1, "United States", "美国"),
                ],
                x0=40.0,
                x1=90.0,
            )
            tick_rect = fitz.Rect(274.0, 735.0, 490.0, 745.8)
            _redact_with_fill(page, tick_rect, (1, 1, 1))
            try:
                meta = copy_source_region(source_page, page, tick_rect)
            except Exception:
                insert_source_han_sans(page, (276.0, 742.6), "1,000 1,100 1,200 1,300 1,400 1,500 1,600 1,700 1,800 1,900 2,000", fontsize=3.2, color=(0, 0, 0))
                meta = {"bbox": [274.0, 735.0, 490.0, 745.8], "fontsize": 3.2, "fill_strategy": "fallback_fixed_white_tail_tick_redraw"}
            add_meta(
                page_number,
                "ai_index_economy_investment_company_axis_tick_repair",
                "1,000 1,100 1,200 1,300 1,400 1,500 1,600 1,700 1,800 1,900 2,000",
                "1,000 1,100 1,200 1,300 1,400 1,500 1,600 1,700 1,800 1,900 2,000",
                meta,
                policy="restore_dense_company_axis_tail_ticks_from_source_numeric_region_without_touching_bars",
            )
            fixed_line(page, page_number, [256.0, 743.0, 322.0, 753.0], (258.0, 750.6), "公司数量", "ai_index_economy_investment_company_axis_repair", fontsize=5.2, source="Number of companies", fill=(1, 1, 1))
            fixed_line(page, page_number, [526.0, 747.0, 578.0, 761.0], (528.0, 758.0), "图 4.2.9", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.9", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in generative AI by geographic area", y0=80.0, y1=110.0):
            chart_title_source(
                page,
                page_number,
                [35.0, 84.5, 420.0, 109.0],
                "2019-2025年全球生成式AI私人投资（按地理区域）",
                "Global private investment in generative AI by geographic area, 2019–25 / Source: Quid, 2025",
                "Figure 4.2.10",
            )
            fixed_textbox(page, page_number, [34.0, 163.0, 48.0, 305.0], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [494.0, 117.8, 568.0, 128.8], (496.0, 126.0), "163.64，美国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="163.64, United States", fill=(1, 1, 1))
            fixed_line(page, page_number, [494.0, 328.4, 538.0, 337.7], (496.0, 336.4), "3.21，欧洲", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="3.21, Europe", fill=(1, 1, 1))
            fixed_line(page, page_number, [494.0, 337.9, 534.0, 348.5], (496.0, 345.8), "1.48，中国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="1.48, China", fill=(1, 1, 1))
            fixed_line(page, page_number, [522.0, 372.0, 578.0, 386.0], (524.0, 382.8), "图 4.2.10", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.10", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in AI by geographic area, 2013", y0=428.0, y1=456.0) and not has_line_in_region(source_page, "(sum)", y0=426.0, y1=456.0):
            chart_title_source(
                page,
                page_number,
                [35.0, 431.0, 360.0, 456.0],
                "2013-2025年全球AI私人投资（按地理区域）",
                "Global private investment in AI by geographic area, 2013–25 / Source: Quid, 2025",
                "Figure 4.2.11",
            )
            fixed_textbox(page, page_number, [35.0, 510.0, 49.0, 652.0], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [499.0, 464.8, 574.0, 476.0], (501.0, 473.1), "285.88，美国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="285.88, United States", fill=(1, 1, 1))
            fixed_line(page, page_number, [499.0, 668.0, 549.0, 677.6], (501.0, 676.2), "20.92，欧洲", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="20.92, Europe", fill=(1, 1, 1))
            fixed_line(page, page_number, [499.0, 677.8, 542.0, 688.0], (501.0, 685.4), "12.41，中国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="12.41, China", fill=(1, 1, 1))
            fixed_line(page, page_number, [524.0, 719.0, 578.0, 733.0], (526.0, 729.8), "图 4.2.11", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.11", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in AI by geographic area, 2013", y0=426.0, y1=456.0) and has_line_in_region(source_page, "(sum)", y0=426.0, y1=456.0):
            chart_title_source(
                page,
                page_number,
                [37.0, 429.5, 392.0, 454.5],
                "2013-2025年全球AI私人投资累计额（按地理区域）",
                "Global private investment in AI by geographic area, 2013–25 (sum) / Source: Quid, 2025",
                "Figure 4.2.12",
            )
            geographic_label_rows(
                page,
                page_number,
                [
                    (681.2, "United Arab Emirates", "阿拉伯联合酋长国"),
                    (665.3, "Switzerland", "瑞士"),
                    (649.3, "Australia", "澳大利亚"),
                    (633.4, "Japan", "日本"),
                    (617.5, "Sweden", "瑞典"),
                    (601.5, "Singapore", "新加坡"),
                    (585.6, "South Korea", "韩国"),
                    (569.7, "India", "印度"),
                    (553.7, "France", "法国"),
                    (537.8, "Germany", "德国"),
                    (521.9, "Israel", "以色列"),
                    (505.9, "Canada", "加拿大"),
                    (490.0, "United Kingdom", "英国"),
                    (474.1, "China", "中国"),
                    (458.1, "United States", "美国"),
                ],
                x0=40.0,
                x1=114.5,
            )
            fixed_line(page, page_number, [274.0, 705.0, 417.0, 716.0], (276.0, 713.2), "总投资（十亿美元）", "ai_index_economy_investment_x_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1))
            fixed_line(page, page_number, [523.0, 718.0, 578.0, 732.0], (525.0, 728.8), "图 4.2.12", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.12", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Number of newly funded AI companies by geographic area", y0=80.0, y1=104.0) and has_line_in_region(source_page, "(sum)", y0=80.0, y1=104.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 83.5, 410.0, 104.0],
                "2013-2025年新获融资AI公司数（按地理区域，累计）",
                "Number of newly funded AI companies by geographic area, 2013–25 (sum) / Source: Quid, 2025",
                "Figure 4.2.13",
            )
            geographic_label_rows(
                page,
                page_number,
                [
                    (332.3, "Netherlands", "荷兰"),
                    (316.3, "Spain", "西班牙"),
                    (300.4, "Switzerland", "瑞士"),
                    (284.4, "Australia", "澳大利亚"),
                    (268.5, "Singapore", "新加坡"),
                    (252.6, "South Korea", "韩国"),
                    (236.6, "Japan", "日本"),
                    (220.7, "Germany", "德国"),
                    (204.7, "India", "印度"),
                    (188.8, "France", "法国"),
                    (172.8, "Israel", "以色列"),
                    (156.9, "Canada", "加拿大"),
                    (141.0, "United Kingdom", "英国"),
                    (125.0, "China", "中国"),
                    (109.1, "United States", "美国"),
                ],
                x0=40.0,
                x1=99.0,
            )
            tick_rect = fitz.Rect(94.0, 346.8, 566.0, 357.5)
            _redact_with_fill(page, tick_rect, (1, 1, 1))
            try:
                meta = copy_source_region(source_page, page, tick_rect)
            except Exception:
                insert_source_han_sans(page, (96.0, 354.7), "0 500 1,000 1,500 2,000 2,500 3,000 3,500 4,000 4,500 5,000 5,500 6,000 6,500 7,000 7,500 8,000 8,500 9,000", fontsize=3.1, color=(0, 0, 0))
                meta = {"bbox": [94.0, 346.8, 566.0, 357.5], "fontsize": 3.1, "fill_strategy": "fallback_fixed_white_dense_tick_redraw"}
            add_meta(
                page_number,
                "ai_index_economy_investment_company_axis_tick_repair",
                "0 500 1,000 ... 9,000",
                "0 500 1,000 ... 9,000",
                meta,
                policy="restore_dense_company_axis_ticks_from_source_numeric_region_without_touching_bars",
            )
            fixed_line(page, page_number, [296.0, 356.0, 375.0, 367.0], (298.0, 364.4), "公司数量", "ai_index_economy_investment_company_axis_repair", fontsize=5.2, source="Number of companies", fill=(1, 1, 1))
            fixed_line(page, page_number, [522.0, 369.0, 578.0, 383.0], (524.0, 379.8), "图 4.2.13", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.13", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Number of newly funded AI companies by geographic area, 2013", y0=410.0, y1=442.0):
            chart_title_source(
                page,
                page_number,
                [35.0, 423.0, 380.0, 443.5],
                "2013-2025年新获融资AI公司数（按地理区域）",
                "Number of newly funded AI companies by geographic area, 2013–25 / Source: Quid, 2025",
                "Figure 4.2.14",
            )
            fixed_textbox(page, page_number, [34.0, 528.0, 48.0, 610.0], "公司数量", "ai_index_economy_investment_company_axis_repair", fontsize=5.2, source="Number of companies", fill=(1, 1, 1), rotate=90)
            fixed_line(page, page_number, [497.0, 452.5, 568.0, 463.8], (499.0, 461.0), "1,953，美国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="1,953, United States", fill=(1, 1, 1))
            fixed_line(page, page_number, [497.0, 603.4, 542.0, 614.2], (499.0, 611.7), "639，欧洲", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="639, Europe", fill=(1, 1, 1))
            fixed_line(page, page_number, [497.0, 658.2, 535.0, 669.0], (499.0, 666.4), "161，中国", "ai_index_economy_investment_line_annotation_repair", fontsize=5.1, source="161, China", fill=(1, 1, 1))
            fixed_line(page, page_number, [522.0, 716.5, 578.0, 731.0], (524.0, 727.6), "图 4.2.14", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.14", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "US state private investment in AI, 2025", y0=225.0, y1=250.0):
            chart_title_source(
                page,
                page_number,
                [144.0, 235.0, 340.0, 254.5],
                "2025年美国各州AI私人投资",
                "US state private investment in AI, 2025 / Source: Quid, 2025",
                "Figure 4.2.15",
            )
            state_map_legend_rows(page, page_number)
            fixed_line(page, page_number, [522.0, 535.0, 578.0, 549.0], (524.0, 545.8), "图 4.2.15", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.15", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Focus Areas of Private Investment", y0=100.0, y1=130.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 105.0, 300.0, 140.0],
                "私人投资的重点领域",
                "ai_index_economy_investment_focus_area_heading_repair",
                fontsize=12.0,
                source="Focus Areas of Private Investment",
                fill=(1, 1, 1),
                color=green_bg,
                policy="translate_private_investment_focus_area_heading",
            )
        if has_line_in_region(source_page, "Global private investment in AI by focus area", y0=340.0, y1=365.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 352.0, 305.0, 370.5],
                "2024-2025年全球AI私人投资（按重点领域）",
                "Global private investment in AI by focus area, 2024 vs. 2025 / Source: Quid, 2025",
                "Figure 4.2.16",
            )
            focus_rows = [
                ([36.0, 375.2, 178.0, 386.4], "AI infrastructure/models/research/governance", "AI基础设施/模型/研究/治理"),
                ([84.0, 386.8, 178.0, 398.0], "Data management, processing", "数据管理与处理"),
                ([123.0, 398.2, 178.0, 409.4], "Internet of things", "物联网"),
                ([104.0, 409.6, 178.0, 420.8], "Medical and healthcare", "医疗与健康"),
                ([128.0, 421.0, 178.0, 432.2], "Pharmaceutical", "制药"),
                ([122.0, 432.5, 178.0, 443.7], "Cloud computing", "云计算"),
                ([84.0, 443.9, 178.0, 455.1], "Cybersecurity, data protection", "网络安全与数据保护"),
                ([146.0, 455.3, 178.0, 466.5], "AI agents", "AI智能体"),
                ([111.0, 466.8, 178.0, 478.0], "Autonomous vehicles", "自动驾驶汽车"),
                ([148.0, 478.2, 178.0, 489.4], "Robotics", "机器人"),
                ([152.0, 489.7, 178.0, 500.9], "Fintech", "金融科技"),
                ([150.0, 501.1, 178.0, 512.3], "Defense", "国防"),
                ([152.0, 512.6, 178.0, 523.8], "Biotech", "生物技术"),
                ([113.0, 524.0, 178.0, 535.2], "Energy management", "能源管理"),
                ([126.0, 535.5, 178.0, 546.7], "Semiconductors", "半导体"),
                ([84.0, 546.9, 178.0, 558.1], "Creative, music, video content", "创意/音乐/视频内容"),
                ([157.0, 558.4, 178.0, 569.6], "Retail", "零售"),
                ([143.0, 569.8, 178.0, 581.0], "Legal tech", "法律科技"),
                ([132.0, 581.3, 178.0, 592.5], "Entertainment", "娱乐"),
                ([112.0, 592.7, 178.0, 603.9], "Quantum computing", "量子计算"),
                ([115.0, 604.2, 178.0, 615.4], "Accounting/finance", "会计/金融"),
                ([110.0, 615.6, 178.0, 626.8], "Marketing, digital ads", "营销/数字广告"),
                ([150.0, 627.1, 178.0, 638.3], "HR tech", "HR科技"),
                ([151.0, 638.5, 178.0, 649.7], "Ed tech", "教育科技"),
                ([153.0, 650.0, 178.0, 661.2], "Drones", "无人机"),
            ]
            for rect_values, source, target in focus_rows:
                focus_area_label_box(page, page_number, rect_values, source, target)
            cleanup_fragment(
                page,
                page_number,
                [178.0, 476.0, 228.0, 498.0],
                "oversized residual translated focus-area label fragment 人技术",
            )
            fixed_line(page, page_number, [280.0, 671.0, 405.0, 681.5], (282.0, 678.8), "总投资（十亿美元）", "ai_index_economy_investment_x_axis_repair", fontsize=5.2, source="Total investment (in billions of US dollars)", fill=(1, 1, 1))
            fixed_line(page, page_number, [522.0, 704.0, 578.0, 718.0], (524.0, 714.8), "图 4.2.16", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.16", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "Global private investment in AI by focus area, 2018", y0=80.0, y1=105.0):
            chart_title_source(
                page,
                page_number,
                [51.0, 86.0, 300.0, 105.0],
                "2018-2025年全球AI私人投资（按重点领域）",
                "Global private investment in AI by focus area, 2018–25 / Source: Quid, 2025",
                "Figure 4.2.17",
            )
            fixed_textbox(page, page_number, [50.0, 346.0, 62.5, 474.0], "总投资（十亿美元）", "ai_index_economy_investment_y_axis_repair", fontsize=5.0, source="Total investment (in billions of US dollars)", fill=(1, 1, 1), rotate=90)
            small_labels = [
                ([104.0, 108.0, 136.0, 119.0], "AI agents", "AI智能体"),
                ([167.0, 108.0, 313.0, 119.0], "AI infrastructure/models/research/governance*", "AI基础设施/模型/研究/治理*"),
                ([354.0, 108.0, 366.0, 119.0], "AV", "自动驾驶"),
                ([449.0, 108.0, 513.0, 119.0], "Accounting/finance", "会计/金融"),
                ([107.0, 195.0, 133.0, 207.0], "Biotech", "生物技术"),
                ([212.0, 195.0, 268.0, 207.0], "Cloud computing", "云计算"),
                ([312.0, 195.0, 408.0, 207.0], "Creative, music, video content", "创意/音乐/视频"),
                ([432.0, 195.0, 528.0, 207.0], "Cybersecurity, data protection", "网络安全/数据保护"),
                ([72.0, 282.0, 168.0, 294.0], "Data management, processing", "数据管理与处理"),
                ([226.0, 282.0, 255.0, 294.0], "Defense", "国防"),
                ([348.0, 282.0, 373.0, 294.0], "Drones", "无人机"),
                ([468.0, 282.0, 494.0, 294.0], "Ed tech", "教育科技"),
                ([87.0, 369.5, 153.0, 381.5], "Energy management", "能源管理"),
                ([217.0, 369.5, 264.0, 381.5], "Entertainment", "娱乐"),
                ([347.0, 369.5, 373.0, 381.5], "Fintech", "金融科技"),
                ([466.0, 369.5, 494.0, 381.5], "HR tech", "HR科技"),
                ([114.0, 456.5, 127.0, 468.5], "IoT", "物联网"),
                ([223.0, 456.5, 258.0, 468.5], "Legal tech", "法律科技"),
                ([326.0, 456.5, 395.0, 468.5], "Marketing, digital ads", "营销/数字广告"),
                ([443.0, 456.5, 518.0, 468.5], "Medical and healthcare", "医疗与健康"),
                ([95.0, 543.5, 145.0, 555.5], "Pharmaceutical", "制药"),
                ([207.0, 543.5, 273.0, 555.5], "Quantum computing", "量子计算"),
                ([350.0, 543.5, 371.0, 555.5], "Retail", "零售"),
                ([466.0, 543.5, 496.0, 555.5], "Robotics", "机器人"),
                ([94.0, 630.5, 147.0, 642.5], "Semiconductors", "半导体"),
            ]
            for rect_values, source, target in small_labels:
                focus_area_label_box(
                    page,
                    page_number,
                    rect_values,
                    source,
                    target,
                    fontsize=4.6,
                    rule="ai_index_economy_investment_focus_area_small_multiple_label_repair",
                )
            cleanup_fragment(
                page,
                page_number,
                [495.0, 542.0, 545.0, 564.0],
                "oversized residual translated small-multiple label fragment 人技术",
            )
            fixed_line(page, page_number, [522.0, 722.0, 578.0, 736.5], (524.0, 733.2), "图 4.2.17", "ai_index_economy_investment_figure_label_repair", fontsize=5.8, source="Figure 4.2.17", fill=green_bg, color=(1, 1, 1))
        if has_line_in_region(source_page, "AI Company Economics", y0=90.0, y1=125.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 95.0, 215.0, 121.0],
                "AI公司经济学",
                "ai_index_economy_ai_company_economics_heading_repair",
                fontsize=12.0,
                source="AI Company Economics",
                fill=(1, 1, 1),
                color=green_bg,
                policy="translate_ai_company_economics_subsection_heading",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 216.0, 96.0, 239.0],
                "营收",
                "ai_index_economy_ai_company_revenue_heading_repair",
                fontsize=11.5,
                source="Revenue",
                fill=(1, 1, 1),
                color=green_bg,
                policy="translate_ai_company_revenue_subheading",
            )
        if has_line_in_region(source_page, "AI company annualized revenue", y0=465.0, y1=492.0):
            chart_title_source(
                page,
                page_number,
                [37.0, 471.0, 274.0, 493.5],
                "AI公司的年化营收",
                "AI company annualized revenue / Source: Epoch AI, 2026",
                "Figure 4.2.18",
                source_line="来源：Epoch AI，2026 | 图表：2026年AI Index报告",
            )
            fixed_textbox(
                page,
                page_number,
                [36.0, 532.0, 48.0, 675.0],
                "年化营收（美元，对数刻度）",
                "ai_index_economy_ai_company_revenue_axis_repair",
                fontsize=5.0,
                source="Annualized revenue (in US dollars - log scale)",
                fill=(1, 1, 1),
                rotate=90,
                policy="translate_ai_company_revenue_axis_preserve_log_ticks_and_company_labels",
            )
            fixed_line(
                page,
                page_number,
                [522.0, 741.0, 578.0, 756.0],
                (524.0, 752.3),
                "图 4.2.18",
                "ai_index_economy_investment_figure_label_repair",
                fontsize=5.8,
                source="Figure 4.2.18",
                fill=(1, 1, 1),
                color=green_bg,
            )
        if has_line_in_region(source_page, "Annual Compute Spend", y0=185.0, y1=210.0):
            fixed_textbox(
                page,
                page_number,
                [295.0, 185.0, 450.0, 210.5],
                "年度计算支出",
                "ai_index_economy_annual_compute_spend_heading_repair",
                fontsize=12.0,
                source="Annual Compute Spend",
                fill=green_bg,
                color=(0.62, 0.88, 0.86),
                policy="translate_annual_compute_spend_subsection_heading_preserve_green_background",
            )
        if has_line_in_region(source_page, "Annual compute spend of select frontier AI companies", y0=438.0, y1=466.0):
            chart_title_source(
                page,
                page_number,
                [54.0, 443.0, 324.0, 464.5],
                "部分前沿AI公司的年度计算支出",
                "Annual compute spend of select frontier AI companies / Source: Epoch AI, 2026",
                "Figure 4.2.20",
                source_line="来源：Epoch AI，2026 | 图表：2026年AI Index报告",
            )
            fixed_textbox(
                page,
                page_number,
                [54.0, 480.0, 66.0, 633.0],
                "年度计算支出（十亿美元）",
                "ai_index_economy_annual_compute_spend_axis_repair",
                fontsize=5.0,
                source="Annual compute spend (in billions of US dollars)",
                fill=(1, 1, 1),
                rotate=90,
                policy="translate_compute_spend_axis_preserve_bars_values_and_company_labels",
            )
            fixed_line(page, page_number, [508.0, 466.0, 560.0, 479.0], (510.0, 476.5), "未归因", "ai_index_economy_compute_spend_legend_repair", fontsize=5.0, source="Unattributed", fill=(1, 1, 1))
            fixed_line(page, page_number, [508.0, 480.0, 540.0, 490.4], (510.0, 487.2), "研发", "ai_index_economy_compute_spend_legend_repair", fontsize=5.0, source="R&D", fill=(1, 1, 1))
            fixed_line(page, page_number, [508.0, 491.0, 550.0, 502.0], (510.0, 497.8), "推理", "ai_index_economy_compute_spend_legend_repair", fontsize=5.0, source="Inference", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [520.0, 729.0, 578.0, 744.0],
                (522.0, 740.6),
                "图 4.2.20",
                "ai_index_economy_investment_figure_label_repair",
                fontsize=5.8,
                source="Figure 4.2.20",
                fill=green_bg,
                color=(1, 1, 1),
            )
        if has_exact_line_in_region(source_page, "Figure 4.2.19", y0=370.0, y1=394.0):
            fixed_line(
                page,
                page_number,
                [35.0, 376.0, 92.0, 391.0],
                (37.0, 387.5),
                "图 4.2.19",
                "ai_index_economy_investment_figure_label_repair",
                fontsize=5.8,
                source="Figure 4.2.19",
                fill=green_bg,
                color=(1, 1, 1),
            )
        if has_line_in_region(source_page, "Capital Expenditures", y0=100.0, y1=130.0):
            fixed_textbox(
                page,
                page_number,
                [37.0, 104.0, 180.0, 127.0],
                "资本支出",
                "ai_index_economy_capital_expenditures_heading_repair",
                fontsize=12.0,
                source="Capital Expenditures",
                fill=(1, 1, 1),
                color=green_bg,
                policy="translate_capital_expenditures_subsection_heading",
            )
        if has_line_in_region(source_page, "Hyperscaler", y0=305.0, y1=330.0):
            fixed_textbox(
                page,
                page_number,
                [45.0, 309.0, 456.0, 329.5],
                "自ChatGPT发布以来，超大规模云厂商年资本支出已翻倍以上",
                "ai_index_economy_hyperscaler_capex_chart_title_repair",
                fontsize=6.0,
                source="Hyperscaler’s annual capex has more than doubled since ChatGPT’s release",
                fill=(1, 1, 1),
                policy="translate_hyperscaler_capex_chart_title_preserve_bars_and_legend",
            )
            fixed_textbox(
                page,
                page_number,
                [45.0, 323.0, 385.0, 342.0],
                "超大规模云厂商年度资本支出（2025和2026为估计值）",
                "ai_index_economy_hyperscaler_capex_inner_title_repair",
                fontsize=5.7,
                source="Hyperscaler annual capex (2025 and 2026 reflect estimates)",
                fill=(1, 1, 1),
                policy="translate_hyperscaler_capex_inner_chart_title_without_touching_legend_or_bars",
            )
            fixed_textbox(
                page,
                page_number,
                [45.0, 420.0, 60.5, 532.0],
                "资本支出（十亿美元）",
                "ai_index_economy_capex_axis_repair",
                fontsize=5.0,
                source="Capex (Billions USD)",
                fill=(1, 1, 1),
                rotate=90,
                policy="translate_capex_axis_preserve_numeric_ticks",
            )
            fixed_line(page, page_number, [306.0, 581.0, 332.0, 595.0], (308.0, 591.5), "年份", "ai_index_economy_capex_year_axis_repair", fontsize=5.2, source="Year", fill=(1, 1, 1))
            fixed_line(page, page_number, [87.0, 592.0, 226.0, 606.0], (89.0, 602.0), "指数视图。来源：Citi Research", "ai_index_economy_capex_source_repair", fontsize=5.0, source="Exponential view. Source: Citi Research", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [522.0, 622.0, 578.0, 637.0],
                (524.0, 633.7),
                "图 4.2.21",
                "ai_index_economy_investment_figure_label_repair",
                fontsize=5.8,
                source="Figure 4.2.21",
                fill=(1, 1, 1),
                color=green_bg,
            )
        if has_line_in_region(source_page, "What Is Generative AI Worth?", y0=68.0, y1=96.0):
            fixed_line(
                page,
                page_number,
                [35.0, 46.5, 103.0, 62.5],
                (37.0, 58.7),
                "亮点：",
                "ai_index_economy_generai_highlight_label_repair",
                fontsize=7.2,
                source="HIGHLIGHT:",
                fill=(0.82, 0.9, 0.38),
                color=(0, 0, 0),
                policy="translate_highlight_tab_label_without_touching_body_text",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 70.0, 270.0, 95.0],
                "生成式AI的价值究竟有多大？",
                "ai_index_economy_generai_value_heading_repair",
                fontsize=11.5,
                source="What Is Generative AI Worth?",
                fill=sampled_background_color(page, fitz.Rect(35.0, 70.0, 270.0, 95.0)),
                color=green_bg,
                policy="translate_generative_ai_value_heading",
            )
        if has_line_in_region(source_page, "Generative AI consumer surplus in the United States", y0=448.0, y1=480.0):
            chart_title_source(
                page,
                page_number,
                [46.0, 453.0, 380.0, 477.8],
                "2025与2026年美国生成式AI消费者剩余",
                "Generative AI consumer surplus in the United States, 2025 vs. 2026 / Source: Brynjolfsson et al., 2026",
                "Figure 4.2.22",
                source_line="来源：Brynjolfsson等，2026 | 图表：2026年AI Index报告",
            )
            fixed_line(page, page_number, [143.0, 482.0, 224.0, 494.5], (145.0, 491.2), "消费者剩余总额", "ai_index_economy_consumer_surplus_small_chart_title_repair", fontsize=4.8, source="Total consumer surplus", fill=(1, 1, 1))
            fixed_line(page, page_number, [394.0, 482.0, 506.0, 494.5], (396.0, 491.2), "使用生成式AI的美国成年人", "ai_index_economy_consumer_surplus_small_chart_title_repair", fontsize=4.8, source="U.S. adults using Generative AI", fill=(1, 1, 1))
            fixed_line(page, page_number, [124.0, 606.0, 242.0, 619.2], (126.0, 615.4), "每用户消费者剩余中位数", "ai_index_economy_consumer_surplus_small_chart_title_repair", fontsize=4.8, source="Median consumer surplus per user", fill=(1, 1, 1))
            fixed_line(page, page_number, [387.0, 606.0, 508.0, 619.2], (389.0, 615.4), "每用户消费者剩余平均值", "ai_index_economy_consumer_surplus_small_chart_title_repair", fontsize=4.8, source="Average consumer surplus per user", fill=(1, 1, 1))
            fixed_line(page, page_number, [53.0, 529.0, 66.0, 550.0], (55.0, 545.5), "价值", "ai_index_economy_consumer_surplus_axis_label_repair", fontsize=4.8, source="Value", fill=(1, 1, 1))
            fixed_line(page, page_number, [318.0, 529.0, 331.0, 550.0], (320.0, 545.5), "用户", "ai_index_economy_consumer_surplus_axis_label_repair", fontsize=4.8, source="Users", fill=(1, 1, 1))
            fixed_line(page, page_number, [54.0, 653.0, 67.0, 674.0], (56.0, 669.5), "价值", "ai_index_economy_consumer_surplus_axis_label_repair", fontsize=4.8, source="Value", fill=(1, 1, 1))
            fixed_line(page, page_number, [321.0, 653.0, 334.0, 674.0], (323.0, 669.5), "价值", "ai_index_economy_consumer_surplus_axis_label_repair", fontsize=4.8, source="Value", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [520.0, 743.0, 578.0, 758.0],
                (522.0, 754.5),
                "图 4.2.22",
                "ai_index_economy_investment_figure_label_repair",
                fontsize=5.8,
                source="Figure 4.2.22",
                fill=sampled_background_color(page, fitz.Rect(520.0, 743.0, 578.0, 758.0)),
                color=green_bg,
            )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
