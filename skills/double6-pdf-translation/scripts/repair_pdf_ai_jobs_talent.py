# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai jobs talent：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def apply_jobs_talent(context):
    """按源标题与区域执行talent类修复；参数由当前页上下文提供。"""
    from repair_pdf_drawing import sampled_background_color
    chart_title_source = context.chart_title_source
    fitz = context.fitz
    fixed_line = context.fixed_line
    fixed_textbox = context.fixed_textbox
    green_bg = context.green_bg
    has_line_in_region = context.has_line_in_region
    page = context.page
    page_number = context.page_number
    restore_chart_region = context.restore_chart_region
    source_page = context.source_page
    if has_line_in_region(source_page, "AI vs. overall hiring rate growth by geographic area", y0=488.0, y1=503.0):
                chart_title_source(
                    page,
                    page_number,
                    [42.0, 488.0, 290.0, 511.0],
                    "2025年各地区AI招聘增长相对整体招聘增长",
                    source="AI vs. overall hiring rate growth by geographic area, 2025",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.8,
                )
                for rect_values, point, source, target in [
                    ([56.0, 512.0, 86.0, 522.0], (58.0, 520.0), "Indonesia", "印度尼西亚"),
                    ([62.0, 525.0, 86.0, 536.0], (64.0, 533.5), "Croatia", "克罗地亚"),
                    ([60.0, 539.0, 86.0, 550.0], (62.0, 547.5), "Belgium", "比利时"),
                    ([52.0, 552.0, 86.0, 563.0], (54.0, 560.5), "Costa Rica", "哥斯达黎加"),
                    ([62.0, 566.0, 86.0, 577.0], (64.0, 574.5), "Cyprus", "塞浦路斯"),
                    ([38.0, 579.0, 86.0, 590.0], (40.0, 587.5), "Czech Republic", "捷克共和国"),
                    ([47.0, 593.0, 86.0, 604.0], (49.0, 601.5), "Luxembourg", "卢森堡"),
                    ([62.0, 606.0, 86.0, 617.0], (64.0, 615.0), "Greece", "希腊"),
                    ([44.0, 620.0, 86.0, 631.0], (46.0, 628.5), "New Zealand", "新西兰"),
                    ([64.0, 633.0, 86.0, 644.0], (66.0, 642.0), "Poland", "波兰"),
                    ([64.0, 647.0, 86.0, 658.0], (66.0, 655.5), "Turkey", "土耳其"),
                    ([48.0, 660.0, 86.0, 672.0], (50.0, 669.0), "Netherlands", "荷兰"),
                    ([63.0, 674.0, 86.0, 685.0], (65.0, 682.5), "Austria", "奥地利"),
                    ([61.0, 687.0, 86.0, 699.0], (63.0, 696.0), "Canada", "加拿大"),
                    ([58.0, 701.0, 86.0, 712.0], (60.0, 709.5), "Romania", "罗马尼亚"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.1, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [226.0, 722.0, 378.0, 733.0], (228.0, 730.2), "AI招聘增长相对整体招聘增长（%）", fontsize=4.8, source="Relative AI hiring rate year-over-year ratio", fill=(1, 1, 1))
                fixed_line(page, page_number, [516.0, 720.0, 578.0, 735.0], (518.0, 731.5), "图 4.4.15", fontsize=5.8, source="Figure 4.4.15", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "AI vs. overall hiring rate growth by geographic area, 2018", y0=70.0, y1=96.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 72.0, 318.0, 96.0],
                    "各地区AI招聘增长相对整体招聘增长，2018-2025",
                    source="AI vs. overall hiring rate growth by geographic area, 2018–25",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=5.0,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [32.0, 220.0, 48.0, 350.0],
                    "AI招聘增长相对整体招聘增长",
                    fontsize=4.8,
                    source="Relative AI hiring rate year-over-year ratio",
                    fill=(1, 1, 1),
                    rotate=90,
                    policy="translate_small_multiple_jobs_y_axis_preserve_country_panels_and_percent_ticks",
                )
                fixed_line(
                    page,
                    page_number,
                    [522.0, 740.0, 578.0, 755.0],
                    (524.0, 751.2),
                    "图 4.4.16",
                    fontsize=5.8,
                    source="Figure 4.4.16",
                    fill=sampled_background_color(page, fitz.Rect(522.0, 740.0, 578.0, 755.0)),
                    color=green_bg,
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "AI Talent Concentration", y0=116.0, y1=142.0):
                fixed_textbox(
                    page,
                    page_number,
                    [36.0, 114.0, 248.0, 144.0],
                    "AI人才集中度",
                    fontsize=12.0,
                    source="AI Talent Concentration",
                    fill=sampled_background_color(page, fitz.Rect(36.0, 114.0, 248.0, 144.0)),
                    color=(0.62, 0.88, 0.86),
                    policy="translate_jobs_ai_talent_concentration_subsection_heading",
                )

    if has_line_in_region(source_page, "AI talent concentration by geographic area", y0=266.0, y1=292.0):
                restore_chart_region(
                    source_page,
                    page,
                    page_number,
                    [36.0, 294.0, 296.0, 508.0],
                    source="AI talent concentration bar chart plot and country labels",
                    target="source chart plot restored; Chinese title/source/axis/figure label overlaid",
                )
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 266.0, 278.0, 292.0],
                    "2025年各地区AI人才集中度",
                    source="AI talent concentration by geographic area, 2025",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.8,
                )
                fixed_line(page, page_number, [151.0, 507.0, 230.0, 519.0], (153.0, 516.2), "AI人才集中度", fontsize=4.8, source="AI talent concentration", fill=(1, 1, 1))
                fixed_line(page, page_number, [236.0, 520.0, 286.0, 535.0], (238.0, 531.2), "图 4.4.21", fontsize=5.8, source="Figure 4.4.21", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Percentage change in AI talent concentration by", y0=266.0, y1=304.0):
                restore_chart_region(
                    source_page,
                    page,
                    page_number,
                    [314.0, 304.0, 576.0, 508.0],
                    source="AI talent concentration change bar chart plot and country labels",
                    target="source chart plot restored; Chinese title/source/axis/figure label overlaid",
                )
                chart_title_source(
                    page,
                    page_number,
                    [314.0, 266.0, 552.0, 304.0],
                    "各地区AI人才集中度变化百分比，2019 vs. 2025",
                    source="Percentage change in AI talent concentration by geographic area, 2019 vs. 2025",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.55,
                )
                fixed_line(page, page_number, [424.0, 507.0, 548.0, 519.0], (426.0, 516.2), "AI人才集中度变化百分比", fontsize=4.8, source="% change in AI talent concentration", fill=(1, 1, 1))
                fixed_line(page, page_number, [518.0, 520.0, 578.0, 535.0], (520.0, 531.2), "图 4.4.22", fontsize=5.8, source="Figure 4.4.22", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Net AI talent migration per 10,000 LinkedIn members by geographic area, 2025", y0=274.0, y1=300.0):
                restore_chart_region(
                    source_page,
                    page,
                    page_number,
                    [42.0, 302.0, 576.0, 545.0],
                    source="Net AI talent migration bar chart plot and country labels",
                    target="source chart plot restored; Chinese title/source/axis/figure label overlaid",
                )
                chart_title_source(
                    page,
                    page_number,
                    [43.0, 274.0, 430.0, 300.0],
                    "2025年各地区每万名LinkedIn会员的AI人才净迁移",
                    source="Net AI talent migration per 10,000 LinkedIn members by geographic area, 2025",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.85,
                )
                fixed_line(page, page_number, [251.0, 544.0, 438.0, 556.0], (253.0, 553.0), "每万名LinkedIn会员的AI人才净迁移", fontsize=4.8, source="Net AI talent migration (per 10,000 LinkedIn members)", fill=(1, 1, 1))
                fixed_line(page, page_number, [514.0, 579.0, 578.0, 594.0], (516.0, 590.4), "图 4.4.23", fontsize=5.8, source="Figure 4.4.23", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Net AI talent migration per 10,000 LinkedIn members by geographic area, 2021", y0=84.0, y1=110.0):
                chart_title_source(
                    page,
                    page_number,
                    [50.0, 84.0, 402.0, 110.0],
                    "各地区每万名LinkedIn会员的AI人才净迁移，2021-2025",
                    source="Net AI talent migration per 10,000 LinkedIn members by geographic area, 2021–25",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.85,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [49.0, 334.0, 61.0, 494.0],
                    "AI人才净迁移（每万名LinkedIn会员）",
                    fontsize=4.55,
                    source="Net AI talent migration (per 10,000 LinkedIn members)",
                    fill=(1, 1, 1),
                    rotate=90,
                    policy="translate_small_multiple_ai_talent_migration_y_axis_preserve_country_panels_and_numeric_ticks",
                )
                fixed_line(
                    page,
                    page_number,
                    [514.0, 721.0, 578.0, 736.0],
                    (516.0, 732.4),
                    "图 4.4.24",
                    fontsize=5.8,
                    source="Figure 4.4.24",
                    fill=sampled_background_color(page, fitz.Rect(514.0, 721.0, 578.0, 736.0)),
                    color=green_bg,
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "AI talent representation by gender and geographic area", y0=92.0, y1=118.0):
                restore_chart_region(
                    source_page,
                    page,
                    page_number,
                    [72.0, 118.0, 535.0, 724.0],
                    source="AI talent representation small-multiple chart panels",
                    target="source small-multiple chart restored; Chinese title/source/axis/legend/figure label overlaid",
                )
                chart_title_source(
                    page,
                    page_number,
                    [56.0, 94.0, 420.0, 120.0],
                    "按性别和地区划分的AI人才代表性，2016-2025",
                    source="AI talent representation by gender and geographic area, 2016–25",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.9,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [54.0, 354.0, 68.0, 496.0],
                    "AI人才代表性",
                    fontsize=4.8,
                    source="AI talent representation",
                    fill=(1, 1, 1),
                    rotate=90,
                    policy="translate_small_multiple_talent_representation_y_axis_preserve_country_panels_and_percent_ticks",
                )
                fixed_line(page, page_number, [464.0, 697.0, 492.0, 708.0], (466.0, 705.7), "男性", fontsize=4.8, source="Male", fill=(1, 1, 1))
                fixed_line(page, page_number, [464.0, 708.0, 496.0, 720.0], (466.0, 716.9), "女性", fontsize=4.8, source="Female", fill=(1, 1, 1))
                fixed_line(
                    page,
                    page_number,
                    [514.0, 724.0, 578.0, 739.0],
                    (516.0, 735.4),
                    "图 4.4.25",
                    fontsize=5.8,
                    source="Figure 4.4.25",
                    fill=sampled_background_color(page, fitz.Rect(514.0, 724.0, 578.0, 739.0)),
                    color=green_bg,
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "AI talent concentration by gender and geographic area", y0=92.0, y1=118.0):
                restore_chart_region(
                    source_page,
                    page,
                    page_number,
                    [72.0, 118.0, 535.0, 724.0],
                    source="AI talent concentration small-multiple chart panels by gender",
                    target="source small-multiple chart restored; Chinese title/source/axis/legend/figure label overlaid",
                )
                chart_title_source(
                    page,
                    page_number,
                    [56.0, 94.0, 430.0, 120.0],
                    "按性别和地区划分的AI人才集中度，2016-2025",
                    source="AI talent concentration by gender and geographic area, 2016–25",
                    source_line="来源：LinkedIn，2025 | 图表：2026年AI Index报告",
                    fontsize=4.9,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [54.0, 354.0, 68.0, 506.0],
                    "AI人才集中度",
                    fontsize=4.8,
                    source="AI talent concentration",
                    fill=(1, 1, 1),
                    rotate=90,
                    policy="translate_small_multiple_ai_talent_concentration_y_axis_preserve_country_panels_and_percent_ticks",
                )
                fixed_line(page, page_number, [464.0, 697.0, 492.0, 708.0], (466.0, 705.7), "男性", fontsize=4.8, source="Male", fill=(1, 1, 1))
                fixed_line(page, page_number, [464.0, 708.0, 496.0, 720.0], (466.0, 716.9), "女性", fontsize=4.8, source="Female", fill=(1, 1, 1))
                fixed_line(
                    page,
                    page_number,
                    [514.0, 724.0, 578.0, 739.0],
                    (516.0, 735.4),
                    "图 4.4.26",
                    fontsize=5.8,
                    source="Figure 4.4.26",
                    fill=sampled_background_color(page, fitz.Rect(514.0, 724.0, 578.0, 739.0)),
                    color=green_bg,
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
