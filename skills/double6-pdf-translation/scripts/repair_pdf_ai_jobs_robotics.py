# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai jobs robotics：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def apply_jobs_robotics(context):
    """按源标题与区域执行robotics类修复；参数由当前页上下文提供。"""
    from repair_pdf_drawing import insert_source_han_sans, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    add_meta = context.add_meta
    chart_title_source = context.chart_title_source
    fitz = context.fitz
    fixed_line = context.fixed_line
    fixed_textbox = context.fixed_textbox
    green_bg = context.green_bg
    has_line_in_region = context.has_line_in_region
    page = context.page
    page_number = context.page_number
    source_page = context.source_page
    if has_line_in_region(source_page, "Automation Desire-Capability Landscape", y0=432.0, y1=456.0):
                fixed_textbox(
                    page,
                    page_number,
                    [38.0, 431.0, 260.0, 454.0],
                    "自动化意愿-能力图谱",
                    fontsize=5.4,
                    source="Automation Desire-Capability Landscape",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_jobs_chart_title_source_repair",
                    policy="translate_automation_desire_capability_landscape_title_preserve_scatter_geometry",
                )
                for rect_values, point, source, target in [
                    ([69.0, 464.0, 148.0, 477.0], (71.0, 474.0), "RAD Opportunity Zone", "机会区"),
                    ([300.0, 464.0, 392.0, 477.0], (302.0, 474.0), "Automation \"Green Light\" Zone", "自动化绿灯区"),
                    ([62.0, 646.0, 148.0, 660.0], (64.0, 657.0), "Low Priority Zone", "低优先级区"),
                    ([294.0, 646.0, 400.0, 660.0], (296.0, 657.0), "Automation \"Red Light\" Zone", "自动化红灯区"),
                    ([76.0, 662.0, 188.0, 674.0], (78.0, 671.0), "AI expected Automation Capability", "AI预期自动化能力"),
                    ([38.0, 520.0, 52.0, 636.0], (40.0, 632.0), "Worker-desired Automation Desire", "劳动者期望自动化意愿"),
                ]:
                    rotate = 90 if rect_values[2] - rect_values[0] < 20 else 0
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.0, source=source, fill=sampled_background_color(page, fitz.Rect(rect_values)), rule="ai_index_economy_jobs_chart_label_repair")
                for rect_values, target, source in [
                    ([40.0, 693.0, 182.0, 724.0], "a  每个能力区的任务数\n（2025年4月24日）", "a Average Number of Y Combinator Companies per Task by Desire-Capability Zone"),
                    ([318.0, 693.0, 456.0, 724.0], "c  每个能力区的智能体论文数\n（2025年4月24日）", "c Average Number of AI Agent Research Papers per Task by Desire-Capability Zone"),
                ]:
                    fixed_textbox(page, page_number, rect_values, target, fontsize=4.2, source=source, fill=(1, 1, 1), rule="ai_index_economy_jobs_chart_label_repair")
                fixed_line(page, page_number, [522.0, 724.0, 578.0, 740.0], (524.0, 736.0), "图 4.4.36", fontsize=5.8, source="Figure 4.4.36", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "4.5 ROBOT DEPLOYMENTS", y0=24.0, y1=42.0) or has_line_in_region(source_page, "4.5 Robot Deployments", y0=70.0, y1=96.0):
                fixed_textbox(
                    page,
                    page_number,
                    [246.0, 24.0, 510.0, 42.0],
                    "4.5 机器人部署 | 经济 | 人工智能指数报告 2026",
                    fontsize=3.9,
                    source="4.5 ROBOT DEPLOYMENTS | ECONOMY | AI INDEX REPORT 2026",
                    fill=(1, 1, 1),
                    color=green_bg,
                    rule="ai_index_economy_robot_deployments_running_header_repair",
                    policy="translate_robot_deployments_running_header_preserve_page_rule",
                )

    if has_line_in_region(source_page, "Geographic Patterns", y0=84.0, y1=112.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 84.0, 218.0, 112.0],
                    "地理分布格局",
                    fontsize=13.0,
                    source="Geographic Patterns",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 84.0, 218.0, 112.0)),
                    color=green_bg,
                    rule="ai_index_economy_robot_deployments_section_heading_repair",
                    policy="translate_robot_deployments_section_heading_preserve_body_flow",
                )

    if has_line_in_region(source_page, "Number of industrial robots installed by geographic area", y0=194.0, y1=222.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 198.0, 390.0, 226.0],
                    "2024年各地区安装的工业机器人数量",
                    source="Number of industrial robots installed by geographic area, 2024",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.75,
                )
                label_band = fitz.Rect(36.0, 228.0, 84.0, 438.0)
                _redact_with_fill(page, label_band, (1, 1, 1))
                for y, source, target in [
                    (240.0, "China", "中国"),
                    (261.5, "Japan", "日本"),
                    (283.0, "United States", "美国"),
                    (304.5, "South Korea", "韩国"),
                    (326.0, "Germany", "德国"),
                    (347.5, "India", "印度"),
                    (369.0, "Italy", "意大利"),
                    (390.5, "Taiwan", "中国台湾"),
                    (412.0, "Mexico", "墨西哥"),
                    (433.5, "Spain", "西班牙"),
                ]:
                    insert_source_han_sans(page, (54.0, y), target, fontsize=4.0, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_robot_deployments_chart_label_repair",
                    "geographic area country label band",
                    "Chinese country labels for Figure 4.5.4",
                    {"bbox": [36.0, 228.0, 84.0, 438.0], "fontsize": 4.0, "fill_strategy": "white_label_band_redraw"},
                    policy="translate_robot_geography_country_labels_preserve_bars_and_values",
                )
                fixed_line(
                    page,
                    page_number,
                    [520.0, 438.0, 578.0, 454.0],
                    (522.0, 450.0),
                    "图 4.5.4",
                    fontsize=5.8,
                    source="Figure 4.5.4",
                    fill=(1, 1, 1),
                    color=green_bg,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_figure_label_preserve_chart_geometry",
                )

    if has_line_in_region(source_page, "Number of new industrial robots installed in top 5 countries", y0=480.0, y1=512.0) or has_line_in_region(source_page, "Number of new industrial robots installed by the top five countries", y0=480.0, y1=512.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 500.0, 335.0, 526.0],
                    "2011年至2024年全球前五大国家新增工业机器人安装数量",
                    source="Number of new industrial robots installed by the top five countries, 2011–24",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.55,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [32.0, 532.0, 48.0, 700.0],
                    "已安装工业机器人数量（千台）",
                    fontsize=4.35,
                    source="Number of industrial robots installed (in thousands)",
                    fill=(1, 1, 1),
                    rotate=90,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_country_series_y_axis_preserve_line_geometry",
                )
                for y, source, target in [
                    (527.0, "295, China", "295，中国"),
                    (694.0, "45, Japan", "45，日本"),
                    (701.0, "34, United States", "34，美国"),
                    (709.0, "31, South Korea", "31，韩国"),
                    (716.0, "27, Germany", "27，德国"),
                ]:
                    fixed_line(
                        page,
                        page_number,
                        [450.0, y - 8.0, 512.0, y + 4.0],
                        (452.0, y),
                        target,
                        fontsize=4.0,
                        source=source,
                        fill=(1, 1, 1),
                        rule="ai_index_economy_robot_deployments_chart_label_repair",
                        policy="translate_robot_country_series_endpoint_labels_preserve_lines",
                    )
                fixed_line(
                    page,
                    page_number,
                    [520.0, 730.0, 578.0, 746.0],
                    (522.0, 742.0),
                    "图 4.5.5",
                    fontsize=5.8,
                    source="Figure 4.5.5",
                    fill=(1, 1, 1),
                    color=green_bg,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_figure_label_preserve_chart_geometry",
                )

    if has_line_in_region(source_page, "Annual growth rate of industrial robots installed by geographic area", y0=72.0, y1=98.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 73.0, 440.0, 101.0],
                    "2023年与2024年全球各地工业机器人安装量年度增长率",
                    source="Annual growth rate of industrial robots installed by geographic area, 2023 vs. 2024",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.55,
                )
                label_band = fitz.Rect(36.0, 98.0, 80.0, 310.0)
                _redact_with_fill(page, label_band, (1, 1, 1))
                for y, source, target in [
                    (111.0, "Taiwan", "中国台湾"),
                    (132.5, "India", "印度"),
                    (154.0, "China", "中国"),
                    (175.5, "Mexico", "墨西哥"),
                    (197.0, "Spain", "西班牙"),
                    (218.5, "South Korea", "韩国"),
                    (240.0, "Japan", "日本"),
                    (261.5, "Germany", "德国"),
                    (283.0, "United States", "美国"),
                    (304.5, "Italy", "意大利"),
                ]:
                    insert_source_han_sans(page, (42.0, y), target, fontsize=3.75, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_robot_deployments_chart_label_repair",
                    "annual growth rate country label band",
                    "Chinese country labels for Figure 4.5.6",
                    {"bbox": [36.0, 98.0, 80.0, 310.0], "fontsize": 3.75, "fill_strategy": "white_label_band_redraw"},
                    policy="translate_robot_growth_country_labels_preserve_signed_bars",
                )
                fixed_line(
                    page,
                    page_number,
                    [220.0, 319.0, 372.0, 333.0],
                    (224.0, 329.0),
                    "工业机器人安装量年增长率",
                    fontsize=4.3,
                    source="Annual growth rate of industrial robots installed",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_growth_axis_label_preserve_ticks",
                )
                fixed_line(page, page_number, [520.0, 332.0, 578.0, 348.0], (522.0, 344.0), "图 4.5.6", fontsize=5.8, source="Figure 4.5.6", fill=(1, 1, 1), color=green_bg, rule="ai_index_economy_robot_deployments_chart_label_repair", policy="translate_robot_figure_label_preserve_chart_geometry")

    if has_line_in_region(source_page, "Service Robotics", y0=360.0, y1=392.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 362.0, 156.0, 392.0],
                    "服务机器人",
                    fontsize=11.0,
                    source="Service Robotics",
                    fill=(1, 1, 1),
                    color=green_bg,
                    rule="ai_index_economy_robot_deployments_section_heading_repair",
                    policy="translate_service_robotics_section_heading_preserve_body_flow",
                )

    if has_line_in_region(source_page, "Number of service robots installed", y0=474.0, y1=506.0) and has_line_in_region(source_page, "application area", y0=474.0, y1=506.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 480.0, 420.0, 510.0],
                    "2021年至2024年全球各应用领域安装的服务型机器人数量",
                    source="Number of service robots installed by application area, 2021–24",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.35,
                )
                label_band = fitz.Rect(36.0, 518.0, 138.0, 704.0)
                _redact_with_fill(page, label_band, (1, 1, 1))
                for y, source, target in [
                    (530.0, "Agriculture", "农业"),
                    (573.0, "Hospitality", "酒店服务"),
                    (615.0, "Medical and healthcare", "医疗与健康"),
                    (657.0, "Professional cleaning", "专业清洁"),
                    (699.0, "Transportation and logistics", "运输与物流"),
                ]:
                    insert_source_han_sans(page, (70.0, y), target, fontsize=4.25, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_robot_deployments_chart_label_repair",
                    "service robotics application label band",
                    "Chinese application labels for Figure 4.5.7",
                    {"bbox": [36.0, 518.0, 138.0, 704.0], "fontsize": 4.25, "fill_strategy": "white_label_band_redraw"},
                    policy="translate_service_robotics_application_labels_preserve_grouped_bars",
                )
                fixed_line(page, page_number, [520.0, 724.0, 578.0, 740.0], (522.0, 736.0), "图 4.5.7", fontsize=5.8, source="Figure 4.5.7", fill=(1, 1, 1), color=green_bg, rule="ai_index_economy_robot_deployments_chart_label_repair", policy="translate_robot_figure_label_preserve_chart_geometry")

    if has_line_in_region(source_page, "Number of industrial robots installed in the world, 2012", y0=432.0, y1=462.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 438.0, 338.0, 468.0],
                    "2012年至2024年全球已安装的工业机器人数量",
                    source="Number of industrial robots installed in the world, 2012–24",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.75,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 510.0, 48.0, 648.0],
                    "已安装工业机器人数量（千台）",
                    fontsize=4.4,
                    source="Number of industrial robots installed (in thousands)",
                    fill=(1, 1, 1),
                    rotate=90,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_deployment_y_axis_preserve_year_ticks_and_bar_values",
                )
                fixed_line(page, page_number, [522.0, 690.0, 578.0, 706.0], (524.0, 702.0), "图 4.5.1", fontsize=5.8, source="Figure 4.5.1", fill=(1, 1, 1), color=green_bg, rule="ai_index_economy_robot_deployments_chart_label_repair", policy="translate_robot_figure_label_preserve_chart_geometry")

    if has_line_in_region(source_page, "Operational stock of industrial robots in the world, 2012", y0=88.0, y1=116.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 88.0, 350.0, 118.0],
                    "全球工业机器人的在役存量，2012年至2024年",
                    source="Operational stock of industrial robots in the world, 2012–24",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.75,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 164.0, 48.0, 312.0],
                    "工业机器人在役存量（千台）",
                    fontsize=4.4,
                    source="Number of industrial robots (in thousands)",
                    fill=(1, 1, 1),
                    rotate=90,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_stock_y_axis_preserve_year_ticks_and_bar_values",
                )
                fixed_line(page, page_number, [522.0, 348.0, 578.0, 364.0], (524.0, 360.0), "图 4.5.2", fontsize=5.8, source="Figure 4.5.2", fill=(1, 1, 1), color=green_bg, rule="ai_index_economy_robot_deployments_chart_label_repair", policy="translate_robot_figure_label_preserve_chart_geometry")

    if has_line_in_region(source_page, "Number of industrial robots installed in the world by type", y0=430.0, y1=462.0):
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 430.0, 376.0, 462.0],
                    "2017年至2024年全球按类型划分的工业机器人安装数量",
                    source="Number of industrial robots installed in the world by type, 2017–24",
                    source_line="来源：国际机器人联合会（IFR），2025 | 图表：2026年AI Index报告",
                    fontsize=4.6,
                )
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 520.0, 48.0, 686.0],
                    "已安装工业机器人数量（千台）",
                    fontsize=4.4,
                    source="Number of industrial robots installed (in thousands)",
                    fill=(1, 1, 1),
                    rotate=90,
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_by_type_y_axis_preserve_year_ticks_and_bar_values",
                )
                fixed_textbox(
                    page,
                    page_number,
                    [84.0, 462.0, 150.0, 493.0],
                    "传统型\n协作型",
                    fontsize=4.6,
                    source="Traditional / Collaborative legend",
                    fill=(1, 1, 1),
                    rule="ai_index_economy_robot_deployments_chart_label_repair",
                    policy="translate_robot_type_legend_preserve_stacked_bar_colors",
                )
                fixed_line(page, page_number, [536.0, 713.0, 578.0, 729.0], (538.0, 725.0), "图 4.5.3", fontsize=5.8, source="Figure 4.5.3", fill=(1, 1, 1), color=green_bg, rule="ai_index_economy_robot_deployments_chart_label_repair", policy="translate_robot_figure_label_preserve_chart_geometry_without_erasing_2024_tick")

    if has_line_in_region(source_page, "5 SCIENCE", y0=24.0, y1=44.0) and has_line_in_region(source_page, "Contents", y0=100.0, y1=128.0):
                science_toc_bg = (76 / 255, 32 / 255, 73 / 255)
                science_toc_items = [
                    ([66.0, 182.0, 232.0, 199.0], "Publications in AI for Science", "人工智能科学出版物", 6.0),
                    ([66.0, 228.0, 342.0, 245.0], "Physics, Astronomy, Chemistry, and Materials Science", "物理、天文学、化学与材料科学", 5.8),
                    ([66.0, 246.0, 150.0, 262.0], "Datasets", "数据集", 6.2),
                    ([66.0, 264.0, 160.0, 280.0], "Benchmarks", "基准测试", 6.2),
                    ([66.0, 282.0, 190.0, 298.0], "Foundation Models", "基础模型", 6.2),
                    ([66.0, 300.0, 150.0, 316.0], "AI Agents", "AI智能体", 6.2),
                    ([66.0, 318.0, 220.0, 335.0], "Biological and Life Sciences", "生物与生命科学", 5.9),
                    ([66.0, 336.0, 150.0, 352.0], "Datasets", "数据集", 6.2),
                    ([66.0, 354.0, 160.0, 370.0], "Benchmarks", "基准测试", 6.2),
                    ([66.0, 372.0, 190.0, 388.0], "Foundation Models", "基础模型", 6.2),
                    ([66.0, 390.0, 150.0, 406.0], "AI Agents", "AI智能体", 6.2),
                    ([66.0, 408.0, 150.0, 424.0], "Earth Science", "地球科学", 6.2),
                    ([66.0, 426.0, 150.0, 442.0], "Datasets", "数据集", 6.2),
                    ([66.0, 444.0, 160.0, 460.0], "Benchmarks", "基准测试", 6.2),
                    ([66.0, 462.0, 190.0, 478.0], "Foundation Models", "基础模型", 6.2),
                    ([66.0, 480.0, 150.0, 496.0], "AI Agents", "AI智能体", 6.2),
                    ([66.0, 498.0, 150.0, 514.0], "Mathematics", "数学", 6.2),
                    ([48.0, 523.0, 306.0, 541.0], "5.3 AI Agents and Tools for Science Workflows", "5.3 科学工作流中的AI智能体与工具", 5.4),
                    ([66.0, 578.0, 150.0, 596.0], "AI Agents", "AI智能体", 6.2),
                    ([66.0, 596.0, 190.0, 614.0], "AI as a Co-scientist", "作为共同科学家的AI", 5.8),
                ]
                for rect_values, source, target, fontsize in science_toc_items:
                    fixed_textbox(
                        page,
                        page_number,
                        rect_values,
                        target,
                        fontsize=fontsize,
                        source=source,
                        fill=science_toc_bg,
                        color=(1, 1, 1),
                        rule="ai_index_science_toc_entry_repair",
                        policy="translate_science_toc_entries_preserve_page_numbers_rules_and_benchmark_names",
                    )


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
