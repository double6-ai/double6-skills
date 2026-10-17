# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai adoption：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_economy_corporate_ai_adoption_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 Economy 4.3 企业 AI 采用页的固定图表标签。"""
    from repair_pdf_drawing import fit_source_han_textbox, insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
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

    def add_meta(page_number: int, rule: str, source: str, target: str, meta: dict[str, Any], *, policy: str) -> None:
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": "source_han_sans_fixed_economy_corporate_ai_adoption_chart_label",
                "text_policy": policy,
            }
        )

    def fixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float],
        color: tuple[float, float, float] = (0, 0, 0),
        rule: str = "ai_index_economy_corporate_ai_adoption_chart_label_repair",
        policy: str = "translate_corporate_ai_adoption_chart_label_preserve_ticks_values_and_series",
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
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float],
        color: tuple[float, float, float] = (0, 0, 0),
        rotate: int = 0,
        rule: str = "ai_index_economy_corporate_ai_adoption_chart_label_repair",
        policy: str = "translate_corporate_ai_adoption_chart_label_preserve_ticks_values_and_series",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color, rotate=rotate)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    def draw_science_table(
        page: Any,
        page_number: int,
        rect_values: list[float],
        rows: list[dict[str, Any]],
        *,
        header_color: tuple[float, float, float],
        include_header: bool = True,
        rule: str = "ai_index_science_table_region_repair",
    ) -> None:
        rect = fitz.Rect(rect_values)
        bg = (244 / 255, 239 / 255, 245 / 255)
        line = (0.66, 0.66, 0.66)
        blue = (0.02, 0.35, 0.65)
        sector_colors = {
            "学术界": (0.22, 0.64, 0.86),
            "非营利": (0.0, 0.58, 0.2),
            "产业界": (0.70, 0.36, 0.69),
            "政府": (0.50, 0.52, 0.52),
        }
        _redact_with_fill(page, rect, bg)
        page.draw_rect(rect, color=bg, fill=bg, overlay=True)
        rel_cols = [0.02, 0.19, 0.43, 0.60, 0.76]
        rel_widths = [0.15, 0.23, 0.14, 0.14, 0.22]
        xs = [rect.x0 + rect.width * value for value in rel_cols]
        widths = [rect.width * value for value in rel_widths]
        y = rect.y0 + (18.0 if include_header else 10.0)
        if include_header:
            for x, w, label in zip(xs, widths, ["名称", "机构", "领域", "部门", "摘要"]):
                header_rect = fitz.Rect(x, rect.y0 + 14.0, x + w, rect.y0 + 44.0)
                page.draw_rect(header_rect, color=header_color, fill=header_color, radius=0.12, overlay=True)
                fit_source_han_textbox(page, header_rect + (0, 7, 0, 0), label, fontsize=8.2, color=(1, 1, 1))
            y = rect.y0 + 58.0
        available = rect.y1 - y - 8.0
        row_h = max(34.0, available / max(len(rows), 1))
        for idx, row in enumerate(rows):
            top = y + idx * row_h
            bottom = top + row_h
            if idx > 0:
                page.draw_line((rect.x0 + 10.0, top), (rect.x1 - 10.0, top), color=line, width=0.35, overlay=True)
            name_rect = fitz.Rect(xs[0], top + 7.0, xs[0] + widths[0], bottom - 5.0)
            fit_source_han_textbox(page, name_rect, row["name"], fontsize=7.1, color=blue)
            try:
                page.draw_line((name_rect.x0 + 3.0, name_rect.y0 + 17.0), (min(name_rect.x1 - 4.0, name_rect.x0 + len(row["name"]) * 4.5), name_rect.y0 + 17.0), color=blue, width=0.35, overlay=True)
            except Exception:
                pass
            aff_rect = fitz.Rect(xs[1], top + 7.0, xs[1] + widths[1], bottom - 5.0)
            fit_source_han_textbox(page, aff_rect, row.get("affiliation", ""), fontsize=5.8, color=(0.12, 0.12, 0.12))
            domain_rect = fitz.Rect(xs[2], top + 8.0, xs[2] + widths[2], bottom - 5.0)
            fit_source_han_textbox(page, domain_rect, row.get("domain", ""), fontsize=7.0, color=(0.12, 0.12, 0.12))
            sector_y = top + 7.0
            for sector in row.get("sectors", []):
                badge = fitz.Rect(xs[3] + 4.0, sector_y, xs[3] + widths[3] - 4.0, sector_y + 14.0)
                color = sector_colors.get(sector, (0.5, 0.5, 0.5))
                page.draw_rect(badge, color=color, fill=color, radius=0.2, overlay=True)
                fit_source_han_textbox(page, badge + (0, 2.0, 0, 0), sector, fontsize=6.0, color=(1, 1, 1))
                sector_y += 16.0
            summary_rect = fitz.Rect(xs[4], top + 7.0, xs[4] + widths[4], bottom - 5.0)
            fit_source_han_textbox(page, summary_rect, row.get("summary", ""), fontsize=5.8, color=(0.12, 0.12, 0.12))
        add_meta(
            page_number,
            rule,
            "AI Index Science table region",
            "localized structured Science table",
            {
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "row_count": len(rows),
                "fill_strategy": "full_table_region_redaction_and_structured_chinese_redraw",
            },
            policy="preserve_benchmark_and_affiliation_names_translate_headers_domains_sectors_and_summary",
        )

    def chart_title_source(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        source_line: str = "来源：麦肯锡公司调查，2025 | 图表：2026年AI Index报告",
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        insert_source_han_sans(page, (rect.x0 + 1.5, rect.y0 + 10.0), target, fontsize=5.2, color=(0, 0, 0))
        insert_source_han_sans(page, (rect.x0 + 1.5, rect.y0 + 17.6), source_line, fontsize=4.6, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_economy_corporate_ai_adoption_chart_title_source_repair",
            source,
            f"{target} / {source_line}",
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": 5.2, "fill_strategy": "fixed_white_region_then_title_source_lines"},
            policy="redraw_corporate_ai_adoption_chart_title_source_as_compact_chinese_lines",
        )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    green_bg = (12 / 255, 110 / 255, 108 / 255)
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        if has_line_in_region(source_page, "Industry Usage", y0=238.0, y1=270.0):
            fixed_line(
                page,
                page_number,
                [34.0, 242.0, 180.0, 268.0],
                (36.0, 262.0),
                "行业使用情况",
                fontsize=10.0,
                source="Industry Usage",
                fill=sampled_background_color(page, fitz.Rect(34.0, 242.0, 180.0, 268.0)),
                color=green_bg,
                policy="translate_corporate_ai_adoption_section_heading",
            )
            fixed_line(
                page,
                page_number,
                [526.0, 696.0, 578.0, 711.5],
                (528.0, 707.8),
                "图 4.3.1",
                fontsize=5.8,
                source="Figure 4.3.1",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "AI use by organizations in the world", y0=64.0, y1=90.0):
            chart_title_source(
                page,
                page_number,
                [34.0, 68.0, 430.0, 100.0],
                "2023-2025年全球组织AI使用情况",
                source="AI use by organizations in the world, 2023–25",
            )
            for rect_values, point, source, target in [
                ([63.0, 102.5, 112.5, 115.5], (65.0, 111.9), "All geographies", "全部地区"),
                ([75.0, 138.0, 112.5, 150.8], (77.0, 147.4), "Asia-Pacific", "亚太"),
                ([88.0, 173.3, 112.5, 186.0], (90.0, 182.7), "Europe", "欧洲"),
                ([66.0, 208.8, 112.5, 221.5], (68.0, 218.2), "North America", "北美"),
                ([67.5, 235.8, 121.0, 248.5], (69.0, 245.2), "Greater China", "大中华区"),
                ([50.5, 267.0, 112.5, 279.7], (52.0, 276.4), "Developing markets", "发展中市场"),
                ([87.5, 292.5, 112.5, 305.2], (89.0, 301.9), "MENA)", "中东和北非）"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.8, source=source, fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [524.0, 316.0, 578.0, 331.5],
                (526.0, 327.8),
                "图 4.3.2",
                fontsize=5.8,
                source="Figure 4.3.2",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "By Industry and Function", y0=380.0, y1=406.0):
            fixed_textbox(
                page,
                page_number,
                [34.0, 381.0, 190.0, 406.0],
                "按行业和职能",
                fontsize=12.0,
                source="By Industry and Function",
                fill=sampled_background_color(page, fitz.Rect(34.0, 381.0, 190.0, 406.0)),
                color=green_bg,
                policy="translate_corporate_ai_adoption_by_industry_function_heading",
            )
        if has_line_in_region(source_page, "Cost decrease and revenue increase from analytical AI use by function", y0=88.0, y1=116.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 94.0, 455.0, 113.5],
                "分析型AI使用带来的成本下降和营收增长（按职能），2025",
                source="Cost decrease and revenue increase from analytical AI use by function, 2025",
            )
            for rect_values, point, source, target in [
                ([62.0, 123.5, 124.8, 136.5], (64.0, 133.4), "Decrease by <10%", "降低<10%"),
                ([146.5, 123.5, 224.0, 136.5], (148.0, 133.4), "Decrease by 10%–19%", "降低10%-19%"),
                ([245.0, 123.5, 310.0, 136.5], (247.0, 133.4), "Decrease by ≥20%", "降低≥20%"),
                ([331.0, 123.5, 391.0, 136.5], (333.0, 133.4), "Increase by >10%", "增长>10%"),
                ([412.0, 123.5, 484.0, 136.5], (414.0, 133.4), "Increase by 6%–10%", "增长6%-10%"),
                ([505.0, 123.5, 562.0, 136.5], (507.0, 133.4), "Increase by ≤5%", "增长≤5%"),
                ([120.0, 147.8, 190.5, 160.4], (122.0, 157.2), "Marketing and sales", "营销与销售"),
                ([129.0, 188.4, 190.5, 201.0], (131.0, 197.8), "Human resources", "人力资源"),
                ([65.0, 208.7, 190.5, 221.3], (67.0, 218.1), "Product and/or service development", "产品/服务开发"),
                ([98.0, 229.0, 190.5, 241.6], (100.0, 238.4), "Supply chain management", "供应链管理"),
                ([124.5, 249.3, 190.5, 261.9], (126.5, 258.7), "Service operations", "服务运营"),
                ([114.5, 289.8, 190.5, 302.4], (116.5, 299.2), "Software engineering", "软件工程"),
                ([138.0, 310.1, 190.5, 322.7], (140.0, 319.5), "Manufacturing", "制造"),
                ([83.0, 330.4, 190.5, 343.0], (85.0, 339.8), "Strategy and corporate finance", "战略与企业财务"),
                ([103.0, 350.6, 190.5, 363.2], (105.0, 360.0), "Knowledge management", "知识管理"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.9, source=source, fill=(1, 1, 1))
            for rect_values, point, source, target in [
                ([172.0, 168.0, 191.0, 181.0], (174.0, 177.7), "Risk", "风险"),
                ([179.5, 269.5, 191.0, 282.5], (181.0, 279.2), "IT", "IT"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=5.0, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [47.0, 239.0, 61.0, 273.0], "职能", fontsize=5.0, source="Function", fill=(1, 1, 1), rotate=90)
            fixed_textbox(page, page_number, [350.0, 368.5, 412.0, 382.0], "受访者占比", fontsize=5.0, source="% of respondents", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [524.0, 407.0, 578.0, 422.0],
                (526.0, 418.2),
                "图 4.3.4",
                fontsize=5.8,
                source="Figure 4.3.4",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "AI impact on organizational measures over the past year", y0=432.0, y1=458.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 437.0, 340.0, 456.5],
                "过去一年AI对组织指标的影响，2025",
                source="AI impact on organizational measures over the past year, 2025",
            )
            for rect_values, point, source, target in [
                ([167.0, 464.6, 200.0, 477.6], (169.0, 474.0), "Improved", "改善"),
                ([218.0, 464.6, 264.5, 477.6], (220.0, 474.0), "Had no effect", "无影响"),
                ([282.0, 464.6, 321.0, 477.6], (284.0, 474.0), "Don’t know", "不知道"),
                ([339.0, 464.6, 375.0, 477.6], (341.0, 474.0), "Worsened", "恶化"),
                ([113.5, 486.2, 149.0, 498.8], (115.0, 495.6), "Innovation", "创新"),
                ([132.0, 572.7, 149.0, 585.3], (133.5, 582.1), "Cost", "成本"),
                ([62.0, 551.1, 149.0, 563.7], (64.0, 560.5), "Competitive differentiation", "竞争差异化"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.8, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [33.5, 540.0, 47.0, 618.0], "组织指标", fontsize=5.0, source="Organizational measure", fill=(1, 1, 1), rotate=90)
            for rect_values, point, source, target in [
                ([78.5, 507.8, 149.0, 520.5], (80.0, 517.2), "Employee satisfaction", "员工满意度"),
                ([78.0, 529.4, 149.0, 542.1], (80.0, 538.8), "Customer satisfaction", "客户满意度"),
                ([71.0, 615.9, 149.0, 628.6], (73.0, 625.3), "Organic revenue growth", "有机营收增长"),
                ([44.0, 637.5, 149.0, 650.2], (46.0, 646.9), "Attraction and retention of talent", "人才吸引与留任"),
                ([72.5, 659.1, 149.0, 671.8], (74.0, 668.5), "Change in market share", "市场份额变化"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.8, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [310.0, 687.0, 367.0, 700.5], "受访者占比", fontsize=5.0, source="% of respondents", fill=(1, 1, 1))
        if has_line_in_region(source_page, "Deployment Stages", y0=95.0, y1=130.0):
            fixed_line(
                page,
                page_number,
                [34.0, 94.0, 180.0, 126.0],
                (36.0, 116.0),
                "部署阶段",
                fontsize=12.0,
                source="Deployment Stages",
                fill=green_bg,
                color=(198 / 255, 232 / 255, 88 / 255),
                policy="translate_corporate_ai_adoption_section_heading",
            )
            chart_title_source(
                page,
                page_number,
                [36.0, 209.0, 375.0, 228.0],
                "按组织营收划分的AI部署阶段，2025",
                source="Stage of AI deployment by organization revenue, 2025",
            )
            for rect_values, point, source, target in [
                ([114.0, 237.0, 148.0, 251.0], (116.0, 247.0), "Not using", "未使用"),
                ([168.0, 237.0, 218.0, 251.0], (170.0, 247.0), "Experimenting", "试验中"),
                ([238.0, 237.0, 266.0, 251.0], (240.0, 247.0), "Piloting", "试点中"),
                ([286.0, 237.0, 313.0, 251.0], (288.0, 247.0), "Scaling", "扩展中"),
                ([332.0, 237.0, 374.0, 251.0], (334.0, 247.0), "Fully scaled", "已全面扩展"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=5.1, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [34.0, 317.0, 50.0, 397.0], "营收（美元）", fontsize=5.2, source="Revenue in US dollars", fill=(1, 1, 1), rotate=90)
            fixed_textbox(page, page_number, [292.0, 468.0, 355.0, 483.0], "受访者占比", fontsize=5.2, source="% of respondents", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [522.0, 501.0, 580.0, 518.5],
                (524.0, 514.2),
                "图 4.3.6",
                fontsize=5.8,
                source="Figure 4.3.6",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "Figure 4.3.7", y0=378.0, y1=402.0) or "AI agents in scaled use" in normalize_text(page.get_text("text")):
            chart_title_source(
                page,
                page_number,
                [34.0, 86.0, 405.0, 111.0],
                "按行业和职能划分的AI智能体规模化使用情况，2025",
                source="AI agents in scaled use by industry and function, 2025",
            )
            _redact_with_fill(page, fitz.Rect(34.0, 114.0, 176.0, 382.0), (1, 1, 1))
            for _, point, source, target in [
                ([68.0, 116.0, 174.0, 128.0], (70.0, 125.0), "Advanced manufacturing", "先进制造"),
                ([54.0, 139.0, 174.0, 151.0], (56.0, 148.0), "Consumer goods and retail", "消费品与零售"),
                ([82.0, 162.0, 174.0, 174.0], (84.0, 171.0), "Energy and materials", "能源与材料"),
                ([52.0, 185.0, 174.0, 197.0], (54.0, 194.0), "Engineering and construction", "工程与建筑"),
                ([78.0, 208.0, 174.0, 220.0], (80.0, 217.0), "Financial institutions", "金融机构"),
                ([118.0, 231.0, 174.0, 243.0], (120.0, 240.0), "Healthcare", "医疗健康"),
                ([130.0, 253.0, 174.0, 265.0], (132.0, 262.0), "Insurance", "保险"),
                ([91.0, 276.0, 174.0, 288.0], (93.0, 285.0), "Media and telecom", "媒体与电信"),
                ([60.0, 299.0, 174.0, 311.0], (62.0, 308.0), "Pharma and medical products", "医药与医疗产品"),
                ([82.0, 322.0, 174.0, 334.0], (84.0, 331.0), "Professional services", "专业服务"),
                ([129.0, 345.0, 174.0, 357.0], (131.0, 354.0), "Technology", "科技"),
                ([83.0, 368.0, 174.0, 380.0], (85.0, 377.0), "Travel and logistics", "旅游与物流"),
            ]:
                insert_source_han_sans(page, point, target, fontsize=4.6, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_corporate_ai_adoption_chart_label_repair",
                    source,
                    target,
                    {"bbox": [34.0, round(point[1] - 8.0, 2), 176.0, round(point[1] + 2.0, 2)], "fontsize": 4.6, "fill_strategy": "left_heatmap_label_strip_redraw"},
                    policy="translate_corporate_ai_adoption_heatmap_row_label_preserve_matrix",
                )
            column_band = fitz.Rect(177.0, 292.0, 578.0, 383.0)
            _redact_with_fill(page, column_band, (1, 1, 1))
            insert_source_han_sans(page, (181.0, 312.0), "职能列：人力资源、IT、知识管理、制造、营销与销售、产品/服务开发", fontsize=4.4, color=(0, 0, 0))
            insert_source_han_sans(page, (181.0, 326.0), "风险/法务合规、服务运营、软件工程、战略/企业财务、供应链/库存管理", fontsize=4.4, color=(0, 0, 0))
            add_meta(
                page_number,
                "ai_index_economy_corporate_ai_adoption_heatmap_column_summary_repair",
                "heatmap function column labels",
                "职能列：人力资源、IT、知识管理、制造、营销与销售、产品/服务开发；风险/法务合规、服务运营、软件工程、战略/企业财务、供应链/库存管理",
                {"bbox": [177.0, 292.0, 578.0, 383.0], "fontsize": 4.4, "fill_strategy": "column_label_band_summary_redraw"},
                policy="summarize_dense_rotated_heatmap_column_labels_without_covering_matrix",
            )
            fixed_textbox(page, page_number, [52.0, 245.0, 66.0, 285.0], "行业", fontsize=5.0, source="Industry", fill=(1, 1, 1), rotate=90)
            fixed_textbox(page, page_number, [372.0, 350.0, 470.0, 364.0], "受访者占比（职能）", fontsize=5.0, source="% of respondents (function)", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [524.0, 365.0, 578.0, 380.0],
                (526.0, 376.5),
                "图 4.3.7",
                fontsize=5.8,
                source="Figure 4.3.7",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "Stage of AI agent use by business function", y0=405.0, y1=435.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 416.0, 384.0, 437.5],
                "按业务职能划分的AI智能体使用阶段，2025",
                source="Stage of AI agent use by business function, 2025",
            )
            for rect_values, point, source, target in [
                ([148.0, 443.0, 187.0, 457.0], (150.0, 453.0), "Don’t know", "不知道"),
                ([203.0, 443.0, 237.0, 457.0], (205.0, 453.0), "Not at all", "完全没有"),
                ([258.0, 443.0, 345.0, 457.0], (260.0, 453.0), "Planning to use within year", "计划一年内使用"),
                ([364.0, 443.0, 413.0, 457.0], (366.0, 453.0), "Experimenting", "试验中"),
                ([433.0, 443.0, 461.0, 457.0], (435.0, 453.0), "Piloting", "试点中"),
                ([480.0, 443.0, 507.0, 457.0], (482.0, 453.0), "Scaling", "扩展中"),
                ([526.0, 443.0, 568.0, 457.0], (528.0, 453.0), "Fully scaled", "已全面扩展"),
                ([118.0, 653.0, 170.0, 668.0], (120.0, 664.0), "Manufacturing", "制造"),
                ([44.0, 634.0, 171.0, 649.0], (46.0, 645.0), "Supply chain/inventory management", "供应链/库存管理"),
                ([63.0, 615.0, 171.0, 630.0], (65.0, 626.0), "Strategy and corporate finance", "战略与企业财务"),
                ([109.0, 596.0, 171.0, 611.0], (111.0, 607.0), "Human resources", "人力资源"),
                ([154.0, 577.0, 171.0, 592.0], (156.0, 588.0), "Risk", "风险"),
                ([96.0, 558.0, 171.0, 573.0], (98.0, 569.0), "Software engineering", "软件工程"),
                ([47.0, 539.0, 171.0, 554.0], (49.0, 550.0), "Product and/or service development", "产品/服务开发"),
                ([106.0, 520.0, 171.0, 535.0], (108.0, 531.0), "Service operations", "服务运营"),
                ([101.0, 501.0, 171.0, 516.0], (103.0, 512.0), "Marketing and sales", "营销与销售"),
                ([84.0, 482.0, 171.0, 497.0], (86.0, 493.0), "Knowledge management", "知识管理"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.8, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [34.0, 548.0, 49.0, 586.0], "职能", fontsize=5.0, source="Function", fill=(1, 1, 1), rotate=90)
            fixed_textbox(page, page_number, [336.0, 682.0, 401.0, 697.0], "受访者占比", fontsize=5.0, source="% of respondents", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [522.0, 721.0, 578.0, 736.0],
                (524.0, 732.2),
                "图 4.3.8",
                fontsize=5.8,
                source="Figure 4.3.8",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "Speed of AI adoption by technology", y0=348.0, y1=380.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 356.0, 372.0, 378.0],
                "各类技术的AI采用速度",
                source="Speed of AI adoption by technology",
            )
            fixed_textbox(page, page_number, [36.0, 469.0, 51.0, 524.0], "采用率", fontsize=5.2, source="Adoption rate", fill=(1, 1, 1), rotate=90)
            fixed_textbox(page, page_number, [163.0, 623.0, 367.0, 639.0], "首个大众市场产品推出后的年数", fontsize=5.2, source="Years since the introduction of the first mass-market product", fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [522.0, 654.0, 578.0, 670.5],
                (524.0, 666.2),
                "图 4.3.9",
                fontsize=5.8,
                source="Figure 4.3.9",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "No available data", y0=440.0, y1=464.0):
            legend_rect = fitz.Rect(76.0, 390.0, 138.0, 462.0)
            _redact_with_fill(page, legend_rect, (1, 1, 1))
            for y, source, target in [
                (399.0, "0%–10%", "0%-10%"),
                (408.7, "11%–20%", "11%-20%"),
                (418.4, "21%–30%", "21%-30%"),
                (428.1, "31%–40%", "31%-40%"),
                (437.8, "41%–50%", "41%-50%"),
                (447.4, "51%–65%", "51%-65%"),
                (457.1, "No available data", "无可用数据"),
            ]:
                insert_source_han_sans(page, (79.0, y), target, fontsize=4.8, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_corporate_ai_adoption_map_legend_repair",
                    source,
                    target,
                    {"bbox": [76.0, round(y - 8.0, 2), 138.0, round(y + 2.0, 2)], "fontsize": 4.8, "fill_strategy": "redraw_map_legend_text"},
                    policy="translate_corporate_ai_adoption_map_legend_preserve_bins",
                )
            for rect_values, point, source, target in [
                ([520.0, 470.0, 578.0, 485.5], (522.0, 481.2), "Figure 4.3.10", "图 4.3.10"),
            ]:
                fixed_line(
                    page,
                    page_number,
                    rect_values,
                    point,
                    target,
                    fontsize=5.8,
                    source=source,
                    fill=green_bg,
                    color=(1, 1, 1),
                    rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                    policy="translate_corporate_ai_adoption_map_label_preserve_geography",
                )
        if has_line_in_region(source_page, "GDP per capita (in US dollars)", y0=724.0, y1=742.0):
            chart_title_source(
                page,
                page_number,
                [50.0, 506.0, 430.0, 529.0],
                "按地区划分的每人均GDP对应的AI传播水平，2025",
                source="AI diffusion relative to GDP per capita by geographic area, 2025",
            )
            legend_rect = fitz.Rect(96.0, 532.0, 178.0, 594.0)
            _redact_with_fill(page, legend_rect, (1, 1, 1))
            for rect_values, point, source, target in [
                ([98.0, 533.0, 178.0, 541.0], (102.0, 539.5), "East Asia and Pacific", "东亚和太平洋"),
                ([98.0, 541.0, 178.0, 550.0], (102.0, 547.8), "Europe and Central Asia", "欧洲和中亚"),
                ([98.0, 549.0, 178.0, 558.0], (102.0, 556.0), "Latin America and Caribbean", "拉美和加勒比"),
                ([98.0, 557.0, 178.0, 567.0], (102.0, 564.3), "Middle East and North Africa", "中东和北非"),
                ([98.0, 566.0, 178.0, 575.0], (102.0, 572.6), "North America", "北美"),
                ([98.0, 574.0, 178.0, 584.0], (102.0, 580.9), "South Asia", "南亚"),
                ([98.0, 582.0, 178.0, 592.0], (102.0, 589.2), "Sub-Saharan Africa", "撒哈拉以南非洲"),
                ([236.0, 724.0, 330.0, 742.0], (240.0, 736.0), "GDP per capita (in US dollars)", "人均GDP（美元）"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.4, source=source, fill=(1, 1, 1))
            fixed_textbox(page, page_number, [48.0, 602.0, 63.0, 639.0], "AI传播", fontsize=4.8, source="AI diffusion", fill=(1, 1, 1), rotate=90)
            for rect_values, point, source, target in [
                ([74.0, 688.0, 92.0, 701.0], (76.0, 697.0), "India", "印度"),
                ([111.0, 652.0, 132.0, 665.0], (113.0, 661.0), "China", "中国"),
                ([140.0, 626.0, 166.0, 639.0], (142.0, 635.0), "Bulgaria", "保加利亚"),
                ([151.0, 664.0, 172.0, 677.0], (153.0, 673.0), "Oman", "阿曼"),
                ([157.0, 620.0, 185.0, 633.0], (159.0, 629.0), "Hungary", "匈牙利"),
                ([177.0, 668.0, 204.0, 681.0], (179.0, 677.0), "Portugal", "葡萄牙"),
                ([193.0, 628.0, 220.0, 641.0], (195.0, 637.0), "Slovenia", "斯洛文尼亚"),
                ([231.0, 656.0, 247.0, 668.0], (233.0, 665.0), "Italy", "意大利"),
                ([200.0, 592.0, 220.0, 604.0], (202.0, 601.0), "Spain", "西班牙"),
                ([254.0, 630.0, 279.0, 643.0], (256.0, 639.0), "Finland", "芬兰"),
                ([262.0, 657.0, 291.0, 671.0], (264.0, 666.0), "Germany", "德国"),
                ([271.0, 614.0, 295.0, 627.0], (273.0, 623.0), "Austria", "奥地利"),
                ([275.0, 646.0, 302.0, 659.0], (277.0, 655.0), "Sweden", "瑞典"),
                ([247.0, 598.0, 296.0, 611.0], (249.0, 607.0), "United Kingdom", "英国"),
                ([217.0, 612.0, 257.0, 625.0], (219.0, 621.0), "New Zealand", "新西兰"),
                ([232.0, 586.0, 256.0, 599.0], (234.0, 595.0), "France", "法国"),
                ([309.0, 657.0, 339.0, 671.0], (311.0, 666.0), "Denmark", "丹麦"),
                ([289.0, 603.0, 318.0, 616.0], (291.0, 612.0), "Australia", "澳大利亚"),
                ([293.0, 633.0, 332.0, 646.0], (295.0, 642.0), "Netherlands", "荷兰"),
                ([226.0, 538.0, 289.0, 551.0], (228.0, 547.0), "United Arab Emirates", "阿联酋"),
                ([347.0, 658.0, 388.0, 672.0], (349.0, 667.0), "United States", "美国"),
                ([332.0, 600.0, 352.0, 613.0], (334.0, 609.0), "Qatar", "卡塔尔"),
                ([361.0, 615.0, 387.0, 628.0], (363.0, 624.0), "Norway", "挪威"),
                ([388.0, 545.0, 421.0, 559.0], (390.0, 554.0), "Singapore", "新加坡"),
                ([411.0, 643.0, 448.0, 656.0], (413.0, 652.0), "Switzerland", "瑞士"),
                ([446.0, 584.0, 470.0, 598.0], (448.0, 593.0), "Ireland", "爱尔兰"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.0, source=source, fill=(1, 1, 1))
        if has_line_in_region(source_page, "top 30 geographic areas", y0=196.0, y1=216.0):
            chart_title_source(
                page,
                page_number,
                [40.0, 198.0, 370.0, 222.0],
                "全球前30个地区AI传播率对比，2025年上半年与下半年",
                source="AI diffusion by top 30 geographic areas, first vs. second half 2025",
                source_line="来源：Microsoft AI Economy Institute，2025 | 图表：2026年AI Index报告",
            )
            fixed_line(page, page_number, [166.0, 228.0, 217.0, 242.0], (168.0, 238.5), "2025上半年", fontsize=4.8, source="First half 2025", fill=(1, 1, 1))
            fixed_line(page, page_number, [292.0, 228.0, 352.0, 242.0], (294.0, 238.5), "2025下半年", fontsize=4.8, source="Second half 2025", fill=(1, 1, 1))
            left_labels = [
                (255.7, "阿联酋 59.40"), (271.0, "新加坡 58.60"), (286.2, "挪威 45.30"), (301.4, "爱尔兰 41.70"),
                (316.6, "法国 40.90"), (331.8, "西班牙 39.70"), (347.0, "新西兰 37.60"), (362.2, "英国 36.40"),
                (377.5, "荷兰 36.30"), (392.7, "卡塔尔 35.70"), (407.9, "澳大利亚 34.50"), (423.1, "以色列 33.90"),
                (438.3, "比利时 33.50"), (453.5, "加拿大 33.50"), (468.8, "瑞士 32.40"), (484.0, "瑞典 31.20"),
                (499.2, "奥地利 29.10"), (514.4, "匈牙利 27.90"), (529.6, "丹麦 26.60"), (544.8, "德国 26.50"),
                (560.0, "波兰 26.40"), (575.3, "台湾 26.40"), (590.5, "美国 26.30"), (605.7, "捷克 26.00"),
                (620.9, "韩国 25.90"), (636.1, "意大利 25.80"), (651.3, "芬兰 25.60"), (666.5, "保加利亚 25.40"),
                (681.8, "约旦 25.40"), (695.8, "哥斯达黎加 25.10"),
            ]
            right_labels = [
                (255.3, "阿联酋 64.00 (+4.60)"), (270.5, "新加坡 60.90 (+2.30)"), (285.7, "挪威 46.40 (+1.10)"),
                (300.9, "爱尔兰 44.60 (+2.90)"), (316.2, "法国 44.00 (+3.10)"), (331.4, "西班牙 41.80 (+2.10)"),
                (346.6, "新西兰 40.50 (+2.90)"), (361.8, "英国 38.90 (+2.50)"), (377.0, "荷兰 38.90 (+2.60)"),
                (392.2, "卡塔尔 38.30 (+2.60)"), (407.5, "澳大利亚 36.90 (+2.40)"), (422.7, "以色列 36.10 (+2.20)"),
                (437.9, "比利时 36.00 (+2.50)"), (453.1, "加拿大 35.00 (+1.50)"), (468.3, "瑞士 34.80 (+2.50)"),
                (483.5, "瑞典 33.30 (+2.20)"), (498.7, "奥地利 31.40 (+2.20)"), (514.0, "韩国 30.70 (+4.80)"),
                (529.2, "匈牙利 29.80 (+1.90)"), (544.4, "丹麦 28.70 (+2.10)"), (559.6, "德国 28.60 (+2.10)"),
                (574.8, "波兰 28.50 (+2.10)"), (590.0, "台湾 28.40 (+2.00)"), (605.3, "美国 28.30 (+2.10)"),
                (620.5, "捷克 27.80 (+1.80)"), (635.7, "意大利 27.80 (+2.00)"), (650.9, "保加利亚 27.30 (+1.90)"),
                (666.1, "芬兰 27.30 (+1.70)"), (681.3, "约旦 27.00 (+1.60)"), (695.4, "哥斯达黎加 26.50 (+1.40)"),
            ]
            _redact_with_fill(page, fitz.Rect(88.0, 249.0, 184.0, 704.0), (1, 1, 1))
            _redact_with_fill(page, fitz.Rect(326.0, 249.0, 454.0, 704.0), (1, 1, 1))
            for y, target in left_labels:
                insert_source_han_sans(page, (90.0, y + 6.0), target, fontsize=3.55, color=(0, 0, 0))
            for y, target in right_labels:
                insert_source_han_sans(page, (328.0, y + 6.0), target, fontsize=3.5, color=(0, 0, 0))
            add_meta(
                page_number,
                "ai_index_economy_corporate_ai_adoption_geography_lollipop_label_repair",
                "top 30 geographic areas labels and values",
                "Chinese geographic labels for first and second half 2025 with values and deltas",
                {"bbox": [88.0, 249.0, 454.0, 704.0], "fontsize": 3.55, "fill_strategy": "two_label_strips_redraw_preserve_lollipop_chart"},
                policy="translate_geographic_area_labels_preserve_values_deltas_and_lollipop_geometry",
            )
            fixed_line(
                page,
                page_number,
                [522.0, 722.0, 578.0, 738.0],
                (524.0, 734.0),
                "图 4.3.12",
                fontsize=5.8,
                source="Figure 4.3.12",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "Task usage share by occupation group", y0=274.0, y1=292.0):
            chart_title_source(
                page,
                page_number,
                [70.0, 276.0, 280.0, 299.0],
                "各职业群体任务使用占比，2025",
                source="Task usage share by occupation group, 2025",
                source_line="来源：Anthropic Economic Index，2026 | 图表：2026年AI Index报告",
            )
            residue_rect = fitz.Rect(70.0, 302.0, 258.0, 316.0)
            _redact_with_fill(page, residue_rect, (1, 1, 1))
            add_meta(
                page_number,
                "ai_index_economy_corporate_ai_adoption_chart_residue_cleanup",
                "residual Anthropic Economic Index / AI Index Report fragment",
                "",
                {"bbox": [70.0, 302.0, 258.0, 316.0], "fill_strategy": "white_chart_background_cleanup"},
                policy="remove_residual_source_fragment_overlapping_small_multiple_chart",
            )
            fixed_textbox(page, page_number, [68.0, 420.0, 84.0, 458.0], "使用指数", fontsize=4.8, source="Usage Index", fill=(1, 1, 1), rotate=90)
            for rect_values, point, source, target in [
                ([142.0, 305.0, 224.0, 318.0], (144.0, 314.5), "Computer and Mathematical", "计算机与数学"),
                ([322.0, 305.0, 450.0, 318.0], (324.0, 314.5), "Arts, Design, Entertainment, Sports, and Media", "艺术/设计/娱乐/体育/媒体"),
                ([134.0, 398.0, 230.0, 411.0], (136.0, 407.5), "Educational Instruction and Library", "教育教学与图书馆"),
                ([340.0, 398.0, 434.0, 411.0], (342.0, 407.5), "Office and Administrative Support", "办公与行政支持"),
                ([136.0, 491.0, 230.0, 504.0], (138.0, 500.5), "Life, Physical, and Social Sciences", "生命/物理/社会科学"),
                ([340.0, 491.0, 434.0, 504.0], (342.0, 500.5), "Business and Financial Operations", "商业与金融运营"),
                ([142.0, 584.0, 224.0, 598.0], (144.0, 594.0), "Architecture and Engineering", "建筑与工程"),
                ([366.0, 584.0, 406.0, 598.0], (368.0, 594.0), "Management", "管理"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.6, source=source, fill=(1, 1, 1))
            fixed_line(
                page,
                page_number,
                [520.0, 670.0, 578.0, 686.0],
                (522.0, 682.0),
                "图 4.3.13",
                fontsize=5.8,
                source="Figure 4.3.13",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
        if has_line_in_region(source_page, "Claude.ai collaboration mode share", y0=136.0, y1=158.0):
            chart_title_source(
                page,
                page_number,
                [34.0, 140.0, 255.0, 165.0],
                "Claude.ai协作模式占比，2025",
                source="Claude.ai collaboration mode share, 2025",
                source_line="来源：Anthropic Economic Index，2026 | 图表：2026年AI Index报告",
            )
            for rect_values, point, source, target in [
                ([88.0, 408.0, 124.0, 423.0], (90.0, 419.0), "Jan-2025", "2025年1月"),
                ([221.0, 408.0, 260.0, 423.0], (223.0, 419.0), "Mar-2025", "2025年3月"),
                ([356.0, 408.0, 394.0, 423.0], (358.0, 419.0), "Aug-2025", "2025年8月"),
                ([490.0, 408.0, 528.0, 423.0], (492.0, 419.0), "Nov-2025", "2025年11月"),
                ([497.0, 350.0, 544.0, 363.0], (499.0, 359.0), "Automation", "自动化"),
                ([497.0, 362.0, 550.0, 375.0], (499.0, 371.0), "Augmentation", "增强"),
            ]:
                fixed_line(page, page_number, rect_values, point, target, fontsize=4.8, source=source, fill=(1, 1, 1))
            for rect_values, point, source in [
                ([48.0, 167.0, 65.0, 181.0], (50.0, 177.0), "70%"),
                ([48.0, 201.0, 65.0, 215.0], (50.0, 211.0), "60%"),
                ([48.0, 234.0, 65.0, 248.0], (50.0, 244.0), "50%"),
                ([48.0, 268.0, 65.0, 282.0], (50.0, 278.0), "40%"),
                ([48.0, 301.0, 65.0, 315.0], (50.0, 311.0), "30%"),
                ([48.0, 335.0, 65.0, 349.0], (50.0, 345.0), "20%"),
                ([48.0, 368.0, 65.0, 382.0], (50.0, 378.0), "10%"),
                ([48.0, 401.0, 65.0, 416.0], (50.0, 412.0), "0%"),
            ]:
                fixed_line(
                    page,
                    page_number,
                    rect_values,
                    point,
                    source,
                    fontsize=6.0,
                    source=source,
                    fill=(1, 1, 1),
                    rule="ai_index_economy_corporate_ai_adoption_percent_tick_repair",
                    policy="redraw_collaboration_mode_y_axis_percent_ticks_preserve_scale",
                )
            fixed_textbox(page, page_number, [31.0, 240.0, 49.0, 333.0], "协作模式占比", fontsize=5.0, source="Collaboration mode share", fill=(1, 1, 1), rotate=90)
            fixed_line(
                page,
                page_number,
                [522.0, 451.0, 578.0, 467.0],
                (524.0, 463.0),
                "图 4.3.14",
                fontsize=5.8,
                source="Figure 4.3.14",
                fill=green_bg,
                color=(1, 1, 1),
                rule="ai_index_economy_corporate_ai_adoption_figure_label_repair",
                policy="translate_corporate_ai_adoption_figure_label_preserve_footer_geometry",
            )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
