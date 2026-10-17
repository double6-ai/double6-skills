# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai jobs workforce：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def apply_jobs_workforce(context):
    """按源标题与区域执行workforce类修复；参数由当前页上下文提供。"""
    from repair_pdf_drawing import fit_source_han_textbox, insert_source_han_sans, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    add_meta = context.add_meta
    chart_title_source = context.chart_title_source
    draw_labor_impact_table = context.draw_labor_impact_table
    draw_macro_productivity_table = context.draw_macro_productivity_table
    fitz = context.fitz
    fixed_line = context.fixed_line
    fixed_textbox = context.fixed_textbox
    green_bg = context.green_bg
    has_line_in_region = context.has_line_in_region
    jobs_chart_note = context.jobs_chart_note
    labor_impact_section_heading = context.labor_impact_section_heading
    page = context.page
    page_number = context.page_number
    source_page = context.source_page
    if has_line_in_region(source_page, "Productivity Trends", y0=252.0, y1=276.0):
                labor_impact_section_heading(page, page_number, [36.0, 252.0, 170.0, 274.0], "生产力趋势", source="Productivity Trends", fontsize=10.5)

    if has_line_in_region(source_page, "Micro-level Studies", y0=278.0, y1=300.0):
                labor_impact_section_heading(page, page_number, [36.0, 278.0, 170.0, 299.0], "微观层面研究", source="Micro-level Studies", fontsize=9.4)

    if has_line_in_region(source_page, "Change in", y0=100.0, y1=130.0) and has_line_in_region(source_page, "Reimers and Waldfogel", y0=140.0, y1=170.0):
                draw_labor_impact_table(page, page_number)

    if has_line_in_region(source_page, "Macro-level Studies", y0=470.0, y1=492.0):
                labor_impact_section_heading(page, page_number, [36.0, 470.0, 178.0, 493.0], "宏观层面研究", source="Macro-level Studies", fontsize=9.4)

    if has_line_in_region(source_page, "Productivity / employment", y0=104.0, y1=124.0) and has_line_in_region(source_page, "Aldasoro et al.", y0=145.0, y1=166.0):
                draw_macro_productivity_table(page, page_number)

    if has_line_in_region(source_page, "Workforce Impact", y0=514.0, y1=538.0):
                labor_impact_section_heading(page, page_number, [36.0, 516.0, 170.0, 538.0], "劳动力影响", source="Workforce Impact", fontsize=10.5)

    if has_line_in_region(source_page, "Normalized headcount trends by age group", y0=68.0, y1=88.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 68.0, 520.0, 92.0],
                    "2021年至2025年，各年龄段软件开发人员与客服人员人数变化趋势",
                    source="Normalized headcount trends by age group for software developers and customer service agents, 2021-25",
                    source_line="来源：Brynjolfsson等，2025 | 图表：2026年AI Index报告",
                    fontsize=4.55,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [70.0, 94.0, 432.0, 121.0],
                    "图例：初级(22-25)  早期(26-30)  发展中(31-34)\n中期(35-40)  中后期(41-49)  资深(50+)",
                    fontsize=4.25,
                    source="Early career / developing / mid-career / senior legend",
                    fill=(1, 1, 1),
                    policy="translate_jobs_age_group_legend_as_compact_two_line_legend",
                )
                for rect_values, point, source, target in [
                    ([107.0, 128.0, 174.0, 139.0], (109.0, 136.4), "Software developers", "软件开发人员"),
                    ([337.0, 128.0, 424.0, 139.0], (339.0, 136.4), "Customer support agents", "客服人员"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.1, source=source, fill=(1, 1, 1))
                fixed_textbox(page, page_number, [51.0, 162.0, 64.0, 245.0], "标准化人数", fontsize=4.3, source="Normalized headcount", fill=(1, 1, 1), rotate=90)
                fixed_textbox(page, page_number, [278.0, 162.0, 291.0, 245.0], "标准化人数", fontsize=4.3, source="Normalized headcount", fill=(1, 1, 1), rotate=90)
                fixed_line(page, page_number, [518.0, 276.0, 578.0, 292.0], (520.0, 288.2), "图 4.4.29", fontsize=5.8, source="Figure 4.4.29", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Headcount trends in high AI-exposure jobs", y0=418.0, y1=438.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 418.0, 438.0, 444.0],
                    "高AI暴露岗位中早期职业从业者人数趋势（22-25岁），2021-2025",
                    source="Headcount trends in high AI-exposure jobs (early career 22-25), 2021-25",
                    source_line="来源：Brynjolfsson等，2025 | 图表：2026年AIIndex报告",
                    fontsize=4.6,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [36.0, 470.0, 50.0, 640.0],
                    "人数差异估计（Q5 vs. Q1）",
                    fontsize=4.3,
                    source="Estimated % difference in headcount (Q5 vs. Q1)",
                    fill=(1, 1, 1),
                    rotate=90,
                )
                fixed_line(page, page_number, [514.0, 698.0, 580.0, 713.0], (516.0, 709.2), "图 4.4.30", fontsize=5.8, source="Figure 4.4.30", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Unemployment rate by AI exposure quintile", y0=200.0, y1=222.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 200.0, 300.0, 230.0],
                    "按AI暴露五分位划分的失业率",
                    source="Unemployment rate by AI exposure quintile",
                    source_line="来源：Eckhardt与Goldschlag，2025",
                    fontsize=5.0,
                )
                fixed_textbox(page, page_number, [38.0, 345.0, 52.0, 430.0], "失业率（%）", fontsize=4.8, source="unemployment (%)", fill=(1, 1, 1), rotate=90)
                fixed_textbox(
                    page,
                    page_number,
                    [180.0, 494.0, 530.0, 524.0],
                    "图例：AI暴露度  1  2  3  4  5  美国总体",
                    fontsize=4.45,
                    source="AI exposure 1 2 3 4 5 US total",
                    fill=(1, 1, 1),
                    policy="translate_jobs_ai_exposure_legend_as_compact_single_line",
                )
                jobs_chart_note(
                    page,
                    page_number,
                    [38.0, 532.0, 430.0, 552.0],
                    "注：AI暴露估计按Felten等（2021）能力权重交叉加权；失业数据来自CPS季度数据。",
                    source="Note: AI exposure estimate crosswalked using weighted abilities-based exposure ... Quarterly unemployment from CPS.",
                    fontsize=4.0,
                )
                fixed_line(page, page_number, [518.0, 545.0, 578.0, 561.0], (520.0, 556.6), "图 4.4.31", fontsize=5.8, source="Figure 4.4.31", fill=sampled_background_color(page, fitz.Rect(518.0, 545.0, 578.0, 561.0)), color=green_bg, rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Changes in the occupational mix from recent baselines", y0=104.0, y1=124.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 104.0, 332.0, 136.0],
                    "近期基准水平下职业结构的变化",
                    source="Changes in the occupational mix from recent baselines",
                    source_line="来源：Gimbel等，2025",
                    fontsize=5.0,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [40.0, 154.0, 212.0, 178.0],
                    "相异度指数（百分点）\n相对于基线后x个月",
                    fontsize=4.6,
                    source="Dissimilarity index (percentage points) / Months from baseline on x-axis",
                    fill=(1, 1, 1),
                )
                fixed_textbox(
                    page,
                    page_number,
                    [40.0, 184.0, 530.0, 200.0],
                    "基线：2022年11月（AI）    2021年1月    2022年1月    2022年7月",
                    fontsize=4.35,
                    source="Baseline Nov 2022 (AI) / Jan 2021 / Jan 2022 / Jul 2022",
                    fill=(1, 1, 1),
                    policy="translate_jobs_occupational_mix_legend_as_compact_single_line",
                )
                fixed_textbox(
                    page,
                    page_number,
                    [40.0, 418.0, 334.0, 440.0],
                    "相异度指数使用就业数据的12个月移动平均计算",
                    fontsize=4.1,
                    source="Dissimilarity index is calculated using a 12-month moving average of employment data",
                    fill=(1, 1, 1),
                )
                fixed_line(page, page_number, [518.0, 442.0, 578.0, 458.0], (520.0, 454.0), "图 4.4.32", fontsize=5.8, source="Figure 4.4.32", fill=sampled_background_color(page, fitz.Rect(518.0, 442.0, 578.0, 458.0)), color=green_bg, rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Expected change in workforce size as a result of AI in the next year", y0=86.0, y1=125.0):
                chart_title_source(
                    page,
                    page_number,
                    [54.0, 95.0, 395.0, 123.0],
                    "未来一年AI对员工规模预期变化的影响",
                    source="Expected change in workforce size as a result of AI in the next year",
                    source_line="来源：McKinsey公司调研，2025 | 图表：2026年AI Index报告",
                    fontsize=5.0,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [288.0, 124.0, 460.0, 144.0],
                    "图例：增加  减少  几乎无变化",
                    fontsize=4.2,
                    source="Increase / Decrease / Little or no change legend",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_label_repair",
                    policy="translate_workforce_change_legend_preserve_percent_bars",
                )
                fixed_line(page, page_number, [145.0, 160.0, 171.0, 170.0], (147.0, 168.0), "总体", fontsize=4.2, source="Overall", fill=(1, 1, 1))
                fixed_line(
                    page,
                    page_number,
                    [520.0, 300.0, 578.0, 316.0],
                    (522.0, 312.0),
                    "图 4.4.33",
                    fontsize=5.8,
                    source="Figure 4.4.33",
                    fill=green_bg,
                    color=(1, 1, 1),
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "Actual vs. expected change in workforce size as a result of AI by function", y0=346.0, y1=382.0):
                chart_title_source(
                    page,
                    page_number,
                    [50.0, 346.0, 418.0, 382.0],
                    "各职能领域中AI智能引发的实际与预期劳动力规模变化",
                    source="Actual vs. expected change in workforce size as a result of AI by function",
                    source_line="来源：McKinsey公司调研，2025 | 图表：2026年AI Index报告",
                    fontsize=4.7,
                )
                stale_credit_rect = fitz.Rect(36.0, 388.0, 92.0, 402.0)
                _redact_with_fill(page, stale_credit_rect, (1, 1, 1))
                fixed_textbox(
                    page,
                    page_number,
                    [274.0, 382.0, 454.0, 404.0],
                    "图例：实际减少 / 实际增加 / 预期减少 / 预期增加",
                    fontsize=3.8,
                    source="actual decrease / actual increase / expected decrease / expected increase legend",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_label_repair",
                    policy="translate_workforce_actual_expected_legend_preserve_bar_geometry",
                )
                function_labels = [
                    ([75.0, 401.0, 145.0, 411.0], (77.0, 408.6), "Human resources", "人力资源"),
                    ([75.0, 424.0, 145.0, 434.0], (77.0, 431.6), "Service operations", "服务运营"),
                    ([48.0, 446.0, 148.0, 456.0], (50.0, 453.6), "Supply chain/inventory management", "供应链/库存管理"),
                    ([75.0, 469.0, 146.0, 479.0], (77.0, 476.6), "Software engineering", "软件工程"),
                    ([122.0, 491.0, 145.0, 501.0], (124.0, 498.6), "IT", "IT"),
                    ([62.0, 514.0, 148.0, 524.0], (64.0, 521.6), "Product/service development", "产品/服务开发"),
                    ([120.0, 536.0, 145.0, 546.0], (122.0, 543.6), "Risk", "风险"),
                    ([73.0, 559.0, 147.0, 569.0], (75.0, 566.6), "Marketing and sales", "营销与销售"),
                    ([96.0, 581.0, 146.0, 591.0], (98.0, 588.6), "Manufacturing", "制造"),
                    ([66.0, 604.0, 147.0, 614.0], (68.0, 611.6), "Knowledge management", "知识管理"),
                    ([54.0, 626.0, 148.0, 636.0], (56.0, 633.6), "Strategy and corporate finance", "战略与企业财务"),
                ]
                for rect_values, point, source, target in function_labels:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=3.9, source=source, fill=(1, 1, 1), rule="ai_index_economy_jobs_chart_label_repair")
                label_band = fitz.Rect(58.0, 398.0, 180.0, 644.0)
                _redact_with_fill(page, label_band, (1, 1, 1))
                compact_function_labels = [
                    (411.0, "人力资源"),
                    (434.0, "服务运营"),
                    (456.0, "供应链/库存管理"),
                    (479.0, "软件工程"),
                    (501.0, "IT"),
                    (524.0, "产品/服务开发"),
                    (546.0, "风险"),
                    (569.0, "营销与销售"),
                    (591.0, "制造"),
                    (614.0, "知识管理"),
                    (637.0, "战略与企业财务"),
                ]
                for y, label in compact_function_labels:
                    insert_source_han_sans(page, (88.0, y), label, fontsize=3.9, color=(0, 0, 0))
                axis_label_rect = fitz.Rect(34.0, 500.0, 52.0, 588.0)
                _redact_with_fill(page, axis_label_rect, (1, 1, 1))
                fit_source_han_textbox(page, axis_label_rect, "职能", fontsize=4.4, rotate=90, color=(0, 0, 0))
                stale_function_rect = fitz.Rect(45.0, 438.0, 64.0, 505.0)
                _redact_with_fill(page, stale_function_rect, (1, 1, 1))
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_chart_label_repair",
                    "workforce actual-vs-expected function label band",
                    "Chinese function label band",
                    {"bbox": [58.0, 398.0, 180.0, 644.0], "fontsize": 3.9, "fill_strategy": "white_label_band_redraw"},
                    policy="redraw_workforce_function_labels_preserve_bar_geometry",
                )
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_chart_label_repair",
                    "Function / stale split function labels",
                    "职能",
                    {"bbox": [34.0, 438.0, 64.0, 588.0], "fontsize": 4.4, "fill_strategy": "white_axis_label_and_stale_fragment_redraw"},
                    policy="translate_workforce_function_axis_label_preserve_function_rows",
                )
                body_rect = fitz.Rect(36.0, 604.0, 574.0, 747.0)
                _redact_with_fill(page, body_rect, green_bg)
                body_text = (
                    "Shao 等（2026）的一项发现颇为意外：许多劳动者并不完全抗拒自动化（图 4.4.35）。"
                    "一项覆盖 844 项职业任务的调查显示，46.1% 的劳动者主动希望 AI 接手任务。"
                    "支持自动化的任务通常是可机械分解的流程，劳动者认为 AI 能够节省时间、承担高价值任务、减少重复性工作或提升输出质量。"
                    "不过，实际使用模式并不必然反映这些偏好。Shao 等提出的框架把任务按劳动者意愿和技术可行性分成四个区域。"
                    "从这个角度看，AI 对劳动力的影响更可能逐步体现为任务层面的重组，而不是职业层面的简单替代。"
                )
                fit_source_han_textbox(page, body_rect + (0, 4, 0, -3), body_text, fontsize=7.1, color=(1, 1, 1))
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_workforce_body_redraw",
                    "A surprising finding from Shao et al. (2026) shows that many workers are not wholly resistant to automation...",
                    "Chinese redraw of workforce impact body prose",
                    {"bbox": [36.0, 604.0, 574.0, 747.0], "fontsize": 7.1, "fill_strategy": "green_page_background_redraw"},
                    policy="redraw_workforce_impact_body_prose_as_readable_chinese_preserve_survey_numbers_and_figure_refs",
                )
                fixed_line(
                    page,
                    page_number,
                    [520.0, 580.0, 578.0, 596.0],
                    (522.0, 592.0),
                    "图 4.4.34",
                    fontsize=5.8,
                    source="Figure 4.4.34",
                    fill=green_bg,
                    color=(1, 1, 1),
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "Automation Desire Score Over 844 Tasks Across 104 Occupations", y0=78.0, y1=98.0):
                fixed_textbox(
                    page,
                    page_number,
                    [38.0, 77.0, 278.0, 100.0],
                    "104 个职业、844 项任务的自动化意愿得分",
                    fontsize=5.2,
                    source="Automation Desire Score Over 844 Tasks Across 104 Occupations",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_title_source_repair",
                    policy="translate_automation_desire_chart_title_preserve_source_image_geometry",
                )
                fixed_textbox(page, page_number, [33.0, 112.0, 48.0, 292.0], "自动化意愿", fontsize=4.5, source="Automation Desire", fill=(1, 1, 1), rotate=90)
                fixed_line(page, page_number, [186.0, 392.0, 238.0, 403.0], (188.0, 400.0), "任务排名", fontsize=4.2, source="Task Rank", fill=(1, 1, 1))
                for rect_values, point, source, target in [
                    ([300.0, 78.0, 388.0, 91.0], (302.0, 88.0), "Computer and Mathematical", "计算机与数学"),
                    ([434.0, 78.0, 508.0, 91.0], (436.0, 88.0), "Management", "管理"),
                    ([304.0, 284.0, 404.0, 297.0], (306.0, 294.0), "Business and Financial Operations", "商业与金融运营"),
                    ([438.0, 284.0, 522.0, 297.0], (440.0, 294.0), "Arts, Designs, and Media", "艺术、设计与媒体"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.1, source=source, fill=(1, 1, 1), rule="ai_index_economy_jobs_chart_label_repair")
                fixed_textbox(
                    page,
                    page_number,
                    [40.0, 393.0, 380.0, 421.0],
                    "选择自动化回答的原因（μ(A_i)；N=6,618）：节省时间、简单/常规、提升质量、复杂/困难",
                    fontsize=4.1,
                    source="Selected Reasons for Responses with Automation Desire",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_label_repair",
                    policy="translate_selected_reasons_caption_preserve_bar_chart_geometry",
                )
                fixed_textbox(
                    page,
                    page_number,
                    [415.0, 393.0, 534.0, 421.0],
                    "Claude.ai 使用占比\n2024年12月-2025年1月",
                    fontsize=4.1,
                    source="Percentage of Usage on Claude.ai",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_label_repair",
                )
                fixed_line(page, page_number, [522.0, 404.0, 578.0, 419.0], (524.0, 415.6), "图 4.4.35", fontsize=5.8, source="Figure 4.4.35", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
