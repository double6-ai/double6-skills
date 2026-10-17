# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai jobs：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_economy_jobs_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 AI Index Economy 4.4/4.5 与相邻章节目录的固定图表标签。"""
    from repair_pdf_ai_frontmatter import copy_source_region
    from repair_pdf_ai_jobs_demand import apply_jobs_demand
    from repair_pdf_ai_jobs_robotics import apply_jobs_robotics
    from repair_pdf_ai_jobs_talent import apply_jobs_talent
    from repair_pdf_ai_jobs_workforce import apply_jobs_workforce
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
                "font_policy": "source_han_sans_fixed_economy_jobs_chart_label",
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
        rule: str = "ai_index_economy_jobs_chart_label_repair",
        policy: str = "translate_jobs_chart_label_preserve_ticks_values_and_series",
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
        rule: str = "ai_index_economy_jobs_chart_label_repair",
        policy: str = "translate_jobs_chart_label_preserve_ticks_values_and_series",
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
        source_line: str = "来源：Lightcast，2025 | 图表：2026年AI Index报告",
        fontsize: float = 5.4,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        insert_source_han_sans(page, (rect.x0 + 2.0, rect.y0 + 10.0), target, fontsize=fontsize, color=(0, 0, 0))
        insert_source_han_sans(page, (rect.x0 + 2.0, rect.y0 + 18.0), source_line, fontsize=4.5, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_economy_jobs_chart_title_source_repair",
            source,
            f"{target} / {source_line}",
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_white_region_then_title_source_lines"},
            policy="redraw_jobs_chart_title_source_as_compact_chinese_lines",
        )

    def restore_chart_region(
        source_page: Any,
        page: Any,
        page_number: int,
        rect_values: list[float],
        *,
        source: str,
        target: str,
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = copy_source_region(source_page, page, rect)
        add_meta(
            page_number,
            "ai_index_economy_jobs_chart_source_region_restore",
            source,
            target,
            meta,
            policy="copy_source_jobs_chart_region_to_restore_dense_labels_before_targeted_chinese_overlay",
        )

    def labor_impact_section_heading(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float = 10.5,
    ) -> None:
        fixed_textbox(
            page,
            page_number,
            rect_values,
            target,
            fontsize=fontsize,
            source=source,
            fill=sampled_background_color(page, fitz.Rect(rect_values)),
            color=green_bg,
            rule="ai_index_economy_jobs_labor_impact_section_heading_repair",
            policy="translate_labor_impact_section_heading_preserve_body_flow",
        )

    def draw_labor_impact_table(page: Any, page_number: int) -> None:
        table_rect = fitz.Rect(36.0, 92.0, 554.0, 408.0)
        pale_bg = (236 / 255, 247 / 255, 244 / 255)
        line_color = (182 / 255, 211 / 255, 205 / 255)
        _redact_with_fill(page, table_rect, pale_bg)
        page.draw_rect(table_rect, color=pale_bg, fill=pale_bg, overlay=True)

        cols = [36.0, 154.0, 226.0, 306.0, 404.0, 554.0]
        headers = ["研究", "职业", "AI应用", "生产力变化", "受益最多者"]
        header_y0, header_y1 = 108.0, 136.0
        for index, header in enumerate(headers):
            rect = fitz.Rect(cols[index] + 2.0, header_y0, cols[index + 1] - 4.0, header_y1)
            page.draw_rect(rect, color=green_bg, fill=green_bg, radius=0.2, overlay=True)
            fit_source_han_textbox(page, rect + (0, 4, 0, -2), header, fontsize=5.2, color=(1, 1, 1))

        rows = [
            ["Reimers 与 Waldfogel\n(2026)", "作者", "用于内容创作的\nLLMs", "+200%\n（产出量；发布量增至三倍）", "新进入者提升数量；\nAI前作者保持质量"],
            ["Shen 与 Tamkin\n(2025)", "软件工程师", "学习新库", "0%\n（速度变化统计不显著）", "高分者（65%+）将AI用于概念查询，\n避免“学习惩罚”"],
            ["Becker 等\n(2025)", "开发者", "开源工具", "-19%\n（使用AI后速度变慢）", "无；感知帮助与实际表现\n存在显著差距"],
            ["Brynjolfsson 等\n(2025)", "客服人员", "对话式助手", "+14%-15%\n（每小时解决问题数）", "经验/技能较少的客服\n提升30%-35%"],
            ["Cui 等\n(2025)", "软件开发者", "GitHub Copilot", "+26%\n（完成的pull request）", "初级和经验较少员工"],
            ["Ju 与 Aral\n(2025)", "营销团队", "多模态广告创作", "+50%\n（每名员工产出）", "人机团队；从社会协调\n转向任务执行"],
            ["Choi 与 Xie\n(2025)", "会计", "AI会计支持", "+55%\n（每周客户支持吞吐量）", "资深会计；用信心分数\n指导复核"],
        ]
        y0 = 144.0
        row_h = 34.5
        for row_index, row in enumerate(rows):
            top = y0 + row_index * row_h
            bottom = top + row_h - 3.0
            page.draw_line((cols[0], bottom), (cols[-1], bottom), color=line_color, width=0.55, overlay=True)
            for col_index, text in enumerate(row):
                rect = fitz.Rect(cols[col_index] + 4.0, top + 2.0, cols[col_index + 1] - 5.0, bottom - 2.0)
                fontsize = 4.1 if col_index in {0, 3, 4} else 4.3
                fit_source_han_textbox(page, rect, text, fontsize=fontsize, color=(0, 0, 0))

        add_meta(
            page_number,
            "ai_index_economy_jobs_labor_impact_table_redraw",
            "Figure 4.4.27 productivity studies table",
            "Chinese structured redraw of Figure 4.4.27",
            {"bbox": [36.0, 92.0, 554.0, 408.0], "row_count": len(rows), "fill_strategy": "structured_table_redraw_on_pale_background"},
            policy="redraw_labor_impact_table_as_readable_chinese_summary_preserve_study_names_and_metrics",
        )

    def draw_macro_productivity_table(page: Any, page_number: int) -> None:
        table_rect = fitz.Rect(36.0, 87.0, 554.0, 482.0)
        pale_bg = (236 / 255, 247 / 255, 244 / 255)
        line_color = (182 / 255, 211 / 255, 205 / 255)
        _redact_with_fill(page, table_rect, pale_bg)
        page.draw_rect(table_rect, color=pale_bg, fill=pale_bg, overlay=True)

        cols = [36.0, 154.0, 230.0, 402.0, 554.0]
        headers = ["研究", "范围", "主要发现", "生产率/就业影响"]
        header_y0, header_y1 = 103.0, 134.0
        for index, header in enumerate(headers):
            rect = fitz.Rect(cols[index] + 2.0, header_y0, cols[index + 1] - 4.0, header_y1)
            page.draw_rect(rect, color=green_bg, fill=green_bg, radius=0.2, overlay=True)
            fit_source_han_textbox(page, rect + (0, 4, 0, -2), header, fontsize=5.5, color=(1, 1, 1))

        rows = [
            ["Aldasoro 等\n(2026)", "欧洲企业\n12,000家", "AI提升效率；\n未削弱短期就业。", "劳动生产率+4%；\n员工产出+5.9个百分点。"],
            ["Yotzov 等\n(2026)", "4国高管\n6,000人", "采用率高；\n实际生产率影响有限。", "预计生产率+1.4%；\n就业-0.7%（10年）。"],
            ["Brynjolfsson\n(2026)", "美国经济", "J曲线：早期收益\n可能暂不显现。", "2035年生产率+2.7%，\n约为前十年均值两倍。"],
            ["Filippucci 等\n(OECD, 2025)", "G7经济体\n（10年）", "ICT/高科技制造占比高\n则收益更大。", "美国/英国+0.4至+1.3个百分点；\n意/日+0.2至+0.8。"],
            ["Frank 等\n(2026)", "LinkedIn档案+\n美国失业记录", "ChatGPT后劳动力市场\n状态恶化风险上升。", "AI暴露岗位\n新进入率为负。"],
            ["Brynjolfsson 等\n(2025)", "美国ADP薪资\n至2025年", "早期职业群体\n最先承压。", "早期职业就业\n约下降15%-16%。"],
            ["Hosseini Maasoum\n与 Lichtinger (2025)", "6,200万劳动者；\n28.5万家企业", "偏资深技术变化：\n初级降，高级稳。", "初级就业明显下降，\n主要由招聘放缓驱动。"],
            ["St. Louis Fed\n(2025)", "美国整体\n劳动力市场", "按自报节省时间\n粗略推算。", "劳动生产率\n约+1.1%至+1.3%。"],
            ["Penn Wharton\nBudget Model (2025)", "美国经济", "估算AI当前对\nTFP的贡献。", "TFP贡献约+0.01个百分点，\n几乎可忽略。"],
        ]
        y0 = 144.0
        row_h = 34.6
        for row_index, row in enumerate(rows):
            top = y0 + row_index * row_h
            bottom = top + row_h - 3.0
            page.draw_line((cols[0], bottom), (cols[-1], bottom), color=line_color, width=0.55, overlay=True)
            for col_index, text in enumerate(row):
                rect = fitz.Rect(cols[col_index] + 4.0, top + 1.8, cols[col_index + 1] - 5.0, bottom - 1.8)
                fontsize = 4.95 if col_index in {0, 2, 3} else 5.05
                fit_source_han_textbox(page, rect, text, fontsize=fontsize, color=(0, 0, 0))

        fixed_line(
            page,
            page_number,
            [512.0, 484.0, 578.0, 500.0],
            (516.0, 496.0),
            "图 4.4.28",
            fontsize=5.8,
            source="Figure 4.4.28",
            fill=sampled_background_color(page, fitz.Rect(512.0, 484.0, 578.0, 500.0)),
            color=green_bg,
            rule="ai_index_economy_jobs_figure_label_repair",
            policy="translate_jobs_figure_label_preserve_footer_geometry",
        )
        add_meta(
            page_number,
            "ai_index_economy_jobs_macro_productivity_table_redraw",
            "Figure 4.4.28 macro productivity and employment impact table",
            "Chinese structured redraw of Figure 4.4.28",
            {"bbox": [36.0, 87.0, 554.0, 482.0], "row_count": len(rows), "fill_strategy": "structured_table_redraw_on_pale_background"},
            policy="redraw_macro_productivity_table_as_readable_chinese_summary_preserve_study_names_and_metrics",
        )

    def jobs_chart_note(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float = 4.2,
    ) -> None:
        fixed_textbox(
            page,
            page_number,
            rect_values,
            target,
            fontsize=fontsize,
            source=source,
            fill=(1, 1, 1),
            rule="ai_index_economy_jobs_chart_label_repair",
            policy="translate_jobs_chart_note_source_preserve_chart_geometry",
        )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    green_bg = (12 / 255, 110 / 255, 108 / 255)
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]

        from types import SimpleNamespace
        page_context = SimpleNamespace(
            add_meta=add_meta,
            chart_title_source=chart_title_source,
            draw_labor_impact_table=draw_labor_impact_table,
            draw_macro_productivity_table=draw_macro_productivity_table,
            fitz=fitz,
            fixed_line=fixed_line,
            fixed_textbox=fixed_textbox,
            green_bg=green_bg,
            has_line_in_region=has_line_in_region,
            jobs_chart_note=jobs_chart_note,
            labor_impact_section_heading=labor_impact_section_heading,
            page=page,
            page_number=page_number,
            restore_chart_region=restore_chart_region,
            source_page=source_page,
        )
        apply_jobs_demand(page_context)
        apply_jobs_talent(page_context)
        apply_jobs_workforce(page_context)
        apply_jobs_robotics(page_context)
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
