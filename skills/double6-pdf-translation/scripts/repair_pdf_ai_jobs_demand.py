# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai jobs demand：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def apply_jobs_demand(context):
    """按源标题与区域执行demand类修复；参数由当前页上下文提供。"""
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
    if has_line_in_region(source_page, "AI job postings (% of all job postings)", y0=380.0, y1=400.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 232.0, 312.0, 258.0],
                    "各地区AI劳动力需求",
                    fontsize=12.0,
                    source="AI Labor Demand Across Geographies",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 232.0, 312.0, 258.0)),
                    color=green_bg,
                    policy="translate_jobs_subsection_heading",
                )
                chart_title_source(
                    page,
                    page_number,
                    [38.0, 382.0, 448.0, 407.5],
                    "各地区AI招聘岗位占比，2014-2025（第1部分）",
                    source="AI job postings (% of all job postings) by select geographic areas, 2014–25 (part 1)",
                )
                fixed_textbox(page, page_number, [33.0, 465.0, 50.0, 594.0], "AI招聘岗位占全部岗位比例", fontsize=5.0, source="AI job postings (% of all job postings)", fill=(1, 1, 1), rotate=90)
                labels = [
                    (426.6, "4.69%, 新加坡"),
                    (438.8, "3.48%, 香港"),
                    (451.2, "2.90%, 阿联酋"),
                    (463.5, "2.86%, 卢森堡"),
                    (475.8, "2.56%, 印度"),
                    (488.1, "2.39%, 奥地利"),
                    (500.4, "2.20%, 荷兰"),
                    (512.7, "2.15%, 瑞士"),
                    (525.0, "2.08%, 瑞典"),
                    (537.3, "1.97%, 美国"),
                    (549.6, "1.87%, 加拿大"),
                    (561.9, "1.82%, 澳大利亚"),
                    (574.2, "1.76%, 英国"),
                ]
                _redact_with_fill(page, fitz.Rect(472.0, 423.0, 574.0, 584.0), (1, 1, 1))
                for y, target in labels:
                    insert_source_han_sans(page, (474.0, y + 6.0), target, fontsize=3.7, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_endpoint_label_repair",
                    "right-side country endpoint labels",
                    "Chinese country endpoint labels with AI job posting percentages",
                    {"bbox": [472.0, 423.0, 574.0, 584.0], "fontsize": 3.7, "fill_strategy": "right_endpoint_label_strip_redraw"},
                    policy="translate_country_endpoint_labels_preserve_percent_values_and_line_chart_geometry",
                )
                fixed_line(
                    page,
                    page_number,
                    [526.0, 672.0, 578.0, 687.0],
                    (528.0, 683.4),
                    "图 4.4.1",
                    fontsize=5.8,
                    source="Figure 4.4.1",
                    fill=green_bg,
                    color=(1, 1, 1),
                    rule="ai_index_economy_jobs_figure_label_repair",
                    policy="translate_jobs_figure_label_preserve_footer_geometry",
                )

    if has_line_in_region(source_page, "AI job postings (% of all job postings) by select geographic areas", y0=96.0, y1=116.0):
                chart_title_source(
                    page,
                    page_number,
                    [34.0, 96.0, 448.0, 121.0],
                    "各地区AI招聘岗位占比，2014-2025（第2部分）",
                    source="AI job postings (% of all job postings) by select geographic areas, 2014–25 (part 2)",
                )
                fixed_textbox(page, page_number, [33.0, 183.0, 50.0, 309.0], "AI招聘岗位占全部岗位比例", fontsize=5.0, source="AI job postings (% of all job postings)", fill=(1, 1, 1), rotate=90)
                labels = [
                    (346.5, "0.38%, 克罗地亚"),
                    (326.1, "0.81%, 新西兰"),
                    (317.0, "0.84%, 奥地利"),
                    (307.9, "0.99%, 法国"),
                    (298.8, "1.04%, 荷兰"),
                    (289.7, "1.13%, 德国"),
                    (280.6, "1.33%, 意大利"),
                    (271.4, "1.36%, 比利时"),
                    (262.3, "1.38%, 墨西哥"),
                    (253.2, "1.59%, 瑞士"),
                    (244.1, "1.78%, 澳大利亚"),
                ]
                _redact_with_fill(page, fitz.Rect(502.0, 241.0, 574.0, 357.0), (1, 1, 1))
                for y, target in labels:
                    insert_source_han_sans(page, (504.0, y + 7.0), target, fontsize=3.6, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_endpoint_label_repair",
                    "right-side country endpoint labels",
                    "Chinese country endpoint labels with AI job posting percentages",
                    {"bbox": [502.0, 241.0, 574.0, 357.0], "fontsize": 3.6, "fill_strategy": "right_endpoint_label_strip_redraw"},
                    policy="translate_country_endpoint_labels_preserve_percent_values_and_line_chart_geometry",
                )
                fixed_line(page, page_number, [524.0, 402.0, 578.0, 417.0], (526.0, 413.0), "图 4.4.2", fontsize=5.8, source="Figure 4.4.2", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Skill Composition", y0=510.0, y1=535.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 510.0, 170.0, 536.0],
                    "技能构成",
                    fontsize=12.0,
                    source="Skill Composition",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 510.0, 170.0, 536.0)),
                    color=(0.62, 0.88, 0.86),
                    policy="translate_jobs_subsection_heading",
                )

    if has_line_in_region(source_page, "AI job postings (% of all job postings) in the United States by skill cluster", y0=88.0, y1=108.0):
                chart_title_source(
                    page,
                    page_number,
                    [51.0, 88.0, 440.0, 113.0],
                    "美国按技能类别划分的AI招聘岗位占比，2010-2025",
                    source="AI job postings (% of all job postings) in the United States by skill cluster, 2010–25",
                )
                fixed_textbox(page, page_number, [48.0, 169.0, 65.0, 287.0], "AI招聘岗位占全部岗位比例", fontsize=5.0, source="AI job postings (% of all job postings)", fill=(1, 1, 1), rotate=90)
                labels = [
                    (124.0, "0.05%, 人工智能伦理/治理/监管"),
                    (144.0, "0.08%, 机器人技术"),
                    (163.0, "0.09%, 视觉图像识别"),
                    (181.5, "0.14%, 自动驾驶"),
                    (201.0, "0.20%, 神经网络"),
                    (220.0, "0.22%, 自然语言处理"),
                    (239.0, "0.23%, AI智能体"),
                    (258.0, "0.41%, 生成式AI"),
                    (277.5, "0.99%, 机器学习"),
                    (297.0, "1.70%, 人工智能"),
                ]
                _redact_with_fill(page, fitz.Rect(502.0, 120.0, 612.0, 312.0), (1, 1, 1))
                for y, target in labels:
                    insert_source_han_sans(page, (504.0, y + 6.0), target, fontsize=3.25, color=(0, 0, 0))
                add_meta(
                    page_number,
                    "ai_index_economy_jobs_endpoint_label_repair",
                    "right-side skill-cluster endpoint labels",
                    "Chinese skill-cluster endpoint labels with AI job posting percentages",
                    {"bbox": [502.0, 120.0, 612.0, 312.0], "fontsize": 3.25, "fill_strategy": "right_endpoint_label_strip_redraw"},
                    policy="translate_skill_cluster_endpoint_labels_preserve_percent_values_and_line_chart_geometry",
                )
                fixed_line(page, page_number, [522.0, 376.0, 580.0, 392.0], (524.0, 388.5), "图 4.4.3", fontsize=5.8, source="Figure 4.4.3", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Top 10 specialized skills in 2025 AI job postings", y0=420.0, y1=438.0):
                chart_title_source(
                    page,
                    page_number,
                    [50.0, 420.0, 455.0, 445.0],
                    "2025年美国AI招聘岗位十大专业技能：2013-2015 vs. 2025",
                    source="Top 10 specialized skills in 2025 AI job postings in the United States, 2013–15 vs. 2025",
                    fontsize=5.2,
                )
                for rect_values, point, source, target in [
                    ([78.0, 653.0, 162.0, 664.0], (80.0, 661.5), "Amazon Web Services", "Amazon Web Services"),
                    ([92.0, 631.0, 162.0, 642.0], (94.0, 639.5), "Data science", "数据科学"),
                    ([70.0, 608.0, 162.0, 619.0], (72.0, 616.5), "Project management", "项目管理"),
                    ([54.0, 586.0, 162.0, 597.0], (56.0, 594.5), "SQL (programming language)", "SQL（编程语言）"),
                    ([90.0, 563.0, 162.0, 574.0], (92.0, 571.5), "Data analysis", "数据分析"),
                    ([70.0, 541.0, 162.0, 552.0], (72.0, 549.5), "Workflow management", "工作流管理"),
                    ([102.0, 518.0, 162.0, 529.0], (104.0, 526.5), "Automation", "自动化"),
                    ([100.0, 496.0, 162.0, 507.0], (102.0, 504.5), "Scalability", "可扩展性"),
                    ([78.0, 473.0, 162.0, 484.0], (80.0, 481.5), "Computer science", "计算机科学"),
                    ([54.0, 451.0, 162.0, 462.0], (56.0, 459.5), "Python (programming language)", "Python（编程语言）"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.4, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [314.0, 679.0, 404.0, 691.0], (316.0, 688.2), "AI招聘岗位数量", fontsize=5.2, source="Number of AI job postings", fill=(1, 1, 1))
                fixed_line(page, page_number, [524.0, 711.0, 578.0, 726.0], (526.0, 722.5), "图 4.4.4", fontsize=5.8, source="Figure 4.4.4", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Generative AI skills in AI job postings", y0=104.0, y1=124.0):
                chart_title_source(
                    page,
                    page_number,
                    [52.0, 104.0, 398.0, 129.0],
                    "美国AI招聘岗位中的生成式AI技能，2024 vs. 2025",
                    source="Generative AI skills in AI job postings in the United States, 2024 vs. 2025",
                )
                for rect_values, point, source, target in [
                    ([55.0, 135.0, 162.0, 146.0], (57.0, 143.5), "Generative artificial intelligence", "生成式人工智能"),
                    ([76.0, 158.0, 162.0, 169.0], (78.0, 166.5), "Large language modeling", "大型语言建模"),
                    ([94.0, 180.0, 162.0, 191.0], (96.0, 188.5), "Prompt engineering", "提示工程"),
                    ([55.0, 203.0, 162.0, 214.0], (57.0, 211.5), "Retrieval augmented generation", "检索增强生成"),
                    ([92.0, 225.0, 162.0, 236.0], (94.0, 233.5), "Text to speech (TTS)", "文本转语音（TTS）"),
                    ([55.0, 248.0, 162.0, 259.0], (57.0, 256.5), "Generative adversarial networks", "生成对抗网络"),
                    ([96.0, 270.0, 162.0, 281.0], (98.0, 278.5), "Multimodal models", "多模态模型"),
                    ([78.0, 292.0, 162.0, 304.0], (80.0, 301.0), "Variational autoencoders", "变分自编码器"),
                    ([106.0, 315.0, 162.0, 326.0], (108.0, 323.5), "Stable Diffusion", "Stable Diffusion"),
                    ([92.0, 337.0, 162.0, 349.0], (94.0, 346.0), "Context engineering", "上下文工程"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.35, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [314.0, 365.0, 404.0, 376.0], (316.0, 373.8), "AI招聘岗位数量", fontsize=5.2, source="Number of AI job postings", fill=(1, 1, 1))
                fixed_line(page, page_number, [524.0, 395.0, 578.0, 410.0], (526.0, 406.5), "图 4.4.5", fontsize=5.8, source="Figure 4.4.5", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Share of generative AI skills", y0=438.0, y1=456.0):
                chart_title_source(
                    page,
                    page_number,
                    [52.0, 438.0, 436.0, 463.0],
                    "美国AI招聘岗位中生成式AI技能占比，2024 vs. 2025",
                    source="Share of generative AI skills in AI job postings in the United States, 2024 vs. 2025",
                )
                for rect_values, point, source, target in [
                    ([55.0, 469.0, 162.0, 480.0], (57.0, 477.5), "Generative artificial intelligence", "生成式人工智能"),
                    ([76.0, 491.0, 162.0, 502.0], (78.0, 500.0), "Large language modeling", "大型语言建模"),
                    ([94.0, 514.0, 162.0, 525.0], (96.0, 522.5), "Prompt engineering", "提示工程"),
                    ([55.0, 536.0, 162.0, 547.0], (57.0, 545.0), "Retrieval augmented generation", "检索增强生成"),
                    ([92.0, 559.0, 162.0, 570.0], (94.0, 567.5), "Text to speech (TTS)", "文本转语音（TTS）"),
                    ([55.0, 581.0, 162.0, 592.0], (57.0, 589.5), "Generative adversarial networks", "生成对抗网络"),
                    ([96.0, 603.0, 162.0, 615.0], (98.0, 612.0), "Multimodal models", "多模态模型"),
                    ([78.0, 626.0, 162.0, 637.0], (80.0, 634.5), "Variational autoencoders", "变分自编码器"),
                    ([92.0, 648.0, 162.0, 660.0], (94.0, 657.0), "Context engineering", "上下文工程"),
                    ([106.0, 671.0, 162.0, 682.0], (108.0, 679.5), "Stable Diffusion", "Stable Diffusion"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.35, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [304.0, 697.0, 414.0, 708.0], (306.0, 705.8), "AI招聘岗位中的技能占比（%）", fontsize=5.0, source="Skill share in AI job postings (%)", fill=(1, 1, 1))
                fixed_line(page, page_number, [524.0, 728.0, 578.0, 743.0], (526.0, 739.5), "图 4.4.6", fontsize=5.8, source="Figure 4.4.6", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "AI agent skills in AI job postings in the United States, 2025", y0=96.0, y1=114.0):
                chart_title_source(
                    page,
                    page_number,
                    [53.0, 96.0, 332.0, 121.0],
                    "美国AI招聘岗位中的AI智能体技能，2025",
                    source="AI agent skills in AI job postings in the United States, 2025",
                )
                for rect_values, point, source, target in [
                    ([104.0, 127.0, 138.0, 139.0], (106.0, 136.0), "ChatGPT", "ChatGPT"),
                    ([92.0, 150.0, 138.0, 161.0], (94.0, 158.5), "Agentic AI", "智能体AI"),
                    ([102.0, 172.0, 138.0, 184.0], (104.0, 181.0), "AI agents", "AI智能体"),
                    ([76.0, 195.0, 138.0, 206.0], (78.0, 203.5), "Conversational AI", "对话式AI"),
                    ([76.0, 217.0, 138.0, 229.0], (78.0, 226.0), "Microsoft Copilot", "Microsoft Copilot"),
                    ([68.0, 240.0, 138.0, 251.0], (70.0, 248.5), "Multi-agent systems", "多智能体系统"),
                    ([107.0, 262.0, 138.0, 274.0], (109.0, 271.0), "Chatbot", "聊天机器人"),
                    ([98.0, 284.0, 138.0, 296.0], (100.0, 293.0), "LangGraph", "LangGraph"),
                    ([54.0, 307.0, 138.0, 318.0], (56.0, 315.5), "Microsoft Copilot Studio", "Microsoft Copilot Studio"),
                    ([81.0, 329.0, 138.0, 341.0], (83.0, 338.0), "Agentic systems", "智能体系统"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.25, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [302.0, 356.6, 392.0, 367.0], (304.0, 364.3), "AI招聘岗位数量", fontsize=5.2, source="Number of AI job postings", fill=(1, 1, 1))
                fixed_line(page, page_number, [520.0, 385.0, 578.0, 400.0], (522.0, 396.5), "图 4.4.7", fontsize=5.8, source="Figure 4.4.7", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Share of AI agent skills", y0=425.0, y1=443.0):
                chart_title_source(
                    page,
                    page_number,
                    [53.0, 425.0, 414.0, 450.0],
                    "美国AI招聘岗位中AI智能体技能占比，2024 vs. 2025",
                    source="Share of AI agent skills in AI job postings in the United States, 2024 vs. 2025",
                )
                for rect_values, point, source, target in [
                    ([92.0, 456.0, 138.0, 468.0], (94.0, 465.0), "Agentic AI", "智能体AI"),
                    ([102.0, 478.0, 138.0, 490.0], (104.0, 487.0), "AI agents", "AI智能体"),
                    ([104.0, 501.0, 138.0, 512.0], (106.0, 509.5), "ChatGPT", "ChatGPT"),
                    ([76.0, 523.0, 138.0, 535.0], (78.0, 532.0), "Conversational AI", "对话式AI"),
                    ([76.0, 546.0, 138.0, 557.0], (78.0, 554.5), "Microsoft Copilot", "Microsoft Copilot"),
                    ([68.0, 568.0, 138.0, 580.0], (70.0, 577.0), "Multi-agent systems", "多智能体系统"),
                    ([107.0, 590.0, 138.0, 602.0], (109.0, 599.5), "Chatbot", "聊天机器人"),
                    ([98.0, 613.0, 138.0, 625.0], (100.0, 622.0), "LangGraph", "LangGraph"),
                    ([54.0, 635.0, 138.0, 647.0], (56.0, 644.0), "Microsoft Copilot Studio", "Microsoft Copilot Studio"),
                    ([81.0, 658.0, 138.0, 670.0], (83.0, 667.0), "Agentic systems", "智能体系统"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.25, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [292.0, 684.0, 402.0, 696.0], (294.0, 693.3), "AI招聘岗位中的技能占比（%）", fontsize=5.0, source="Skill share in AI job postings (%)", fill=(1, 1, 1))
                fixed_line(page, page_number, [524.0, 710.0, 578.0, 725.0], (526.0, 721.5), "图 4.4.8", fontsize=5.8, source="Figure 4.4.8", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "AI job postings (% of all job postings) in the United States by sector", y0=316.0, y1=334.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 130.0, 126.0, 154.0],
                    "按部门划分",
                    fontsize=12.0,
                    source="By Sector",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 130.0, 126.0, 154.0)),
                    color=green_bg,
                    policy="translate_jobs_subsection_heading",
                )
                chart_title_source(
                    page,
                    page_number,
                    [36.0, 316.0, 448.0, 344.0],
                    "美国按部门划分的AI招聘岗位占比，2024 vs. 2025",
                    source="AI job postings (% of all job postings) in the United States by sector, 2024 vs. 2025",
                )
                for rect_values, point, source, target in [
                    ([190.0, 345.0, 232.0, 356.0], (192.0, 353.5), "Information", "信息业"),
                    ([74.0, 361.0, 232.0, 372.0], (76.0, 369.5), "Professional, scientific, and technical services", "专业/科学/技术服务"),
                    ([153.0, 377.0, 232.0, 389.0], (155.0, 386.0), "Finance and insurance", "金融与保险"),
                    ([178.0, 394.0, 232.0, 405.0], (180.0, 402.5), "Manufacturing", "制造业"),
                    ([82.0, 410.0, 232.0, 421.0], (84.0, 418.5), "Management of companies and enterprises", "公司和企业管理"),
                    ([203.0, 426.0, 232.0, 438.0], (205.0, 435.0), "Utilities", "公用事业"),
                    ([159.0, 442.0, 232.0, 454.0], (161.0, 451.0), "Educational services", "教育服务"),
                    ([115.0, 458.0, 232.0, 470.0], (117.0, 467.0), "Real estate and rental and leasing", "房地产/租赁"),
                    ([173.0, 475.0, 232.0, 486.0], (175.0, 484.0), "Wholesale trade", "批发贸易"),
                    ([78.0, 491.0, 232.0, 503.0], (80.0, 500.0), "Mining, quarrying, and oil and gas extraction", "采矿/采石/油气开采"),
                    ([157.0, 507.0, 232.0, 519.0], (159.0, 516.0), "Public administration", "公共行政"),
                    ([190.0, 523.0, 232.0, 535.0], (192.0, 532.0), "Retail trade", "零售贸易"),
                    ([92.0, 540.0, 232.0, 552.0], (94.0, 549.0), "Agriculture, forestry, fishing and hunting", "农林渔猎"),
                    ([119.0, 556.0, 232.0, 568.0], (121.0, 565.0), "Transportation and warehousing", "运输与仓储"),
                    ([40.0, 572.0, 232.0, 584.0], (42.0, 581.0), "Waste management and administrative support services", "废弃物管理与行政支持服务"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.2, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [336.0, 597.0, 466.0, 609.0], (338.0, 606.0), "AI招聘岗位占全部岗位比例", fontsize=5.0, source="AI job postings (% of all job postings)", fill=(1, 1, 1))
                fixed_line(page, page_number, [520.0, 622.0, 578.0, 637.0], (522.0, 633.5), "图 4.4.9", fontsize=5.8, source="Figure 4.4.9", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "By State", y0=76.0, y1=98.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 74.0, 118.0, 100.0],
                    "按州划分",
                    fontsize=12.0,
                    source="By State",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 74.0, 118.0, 100.0)),
                    color=green_bg,
                    policy="translate_jobs_subsection_heading",
                )

    if has_line_in_region(source_page, "Number of AI job postings in the United States by state", y0=286.0, y1=304.0):
                chart_title_source(
                    page,
                    page_number,
                    [124.0, 286.0, 384.0, 305.0],
                    "2025年美国各州AI招聘岗位数量",
                    source="Number of AI job postings in the United States by state, 2025",
                    fontsize=4.8,
                )
                fixed_line(page, page_number, [522.0, 496.0, 578.0, 511.0], (524.0, 507.5), "图 4.4.10", fontsize=5.8, source="Figure 4.4.10", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Percentage of US AI job postings by state", y0=532.0, y1=545.0):
                chart_title_source(
                    page,
                    page_number,
                    [124.0, 532.0, 326.0, 553.0],
                    "2025年美国各州AI招聘岗位占比",
                    source="Percentage of US AI job postings by state, 2025",
                    fontsize=4.8,
                )
                fixed_line(page, page_number, [522.0, 746.0, 578.0, 761.0], (524.0, 757.5), "图 4.4.11", fontsize=5.8, source="Figure 4.4.11", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Percentage of US AI job postings by select US state", y0=86.0, y1=103.0):
                chart_title_source(
                    page,
                    page_number,
                    [42.0, 86.0, 340.0, 112.0],
                    "美国部分州AI招聘岗位占比，2010-2025",
                    source="Percentage of US AI job postings by select US state, 2010–25",
                )
                fixed_textbox(page, page_number, [39.0, 151.0, 56.0, 303.0], "美国AI招聘岗位占比", fontsize=5.0, source="Percentage of United States AI job postings", fill=(1, 1, 1), rotate=90)
                for rect_values, point, source, target in [
                    ([493.0, 313.0, 560.0, 324.0], (495.0, 321.5), "3.93%, Washington", "3.93%, 华盛顿州"),
                    ([493.0, 290.0, 552.0, 301.0], (495.0, 298.5), "6.64%, New York", "6.64%, 纽约州"),
                    ([493.0, 277.0, 538.0, 289.0], (495.0, 286.5), "8.10%, Texas", "8.10%, 德克萨斯州"),
                    ([493.0, 198.0, 552.0, 211.0], (495.0, 208.0), "17.18%, California", "17.18%, 加利福尼亚州"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.1, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [522.0, 382.0, 578.0, 397.0], (524.0, 393.5), "图 4.4.12", fontsize=5.8, source="Figure 4.4.12", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Percentage of US states", y0=462.0, y1=475.0):
                chart_title_source(
                    page,
                    page_number,
                    [129.0, 462.0, 346.0, 483.0],
                    "2025年美国各州AI招聘岗位占比",
                    source="Percentage of US states' job postings in AI, 2025",
                    fontsize=4.8,
                )
                fixed_line(page, page_number, [522.0, 693.0, 578.0, 708.0], (524.0, 704.5), "图 4.4.13", fontsize=5.8, source="Figure 4.4.13", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "Percentage of US states’ job postings in AI by select US state", y0=85.0, y1=101.0):
                chart_title_source(
                    page,
                    page_number,
                    [42.0, 85.0, 340.0, 108.0],
                    "美国部分州AI招聘岗位占比，2010-2025",
                    source="Percentage of US states’ job postings in AI by select US state, 2010–25",
                )
                fixed_textbox(page, page_number, [39.0, 151.0, 56.0, 272.0], "美国AI招聘岗位占比", fontsize=5.0, source="Percentage of US states’ job postings in AI", fill=(1, 1, 1), rotate=90)
                for rect_values, point, source, target in [
                    ([439.0, 204.0, 479.0, 214.0], (441.0, 211.5), "2.38%, Texas", "2.38%, 德克萨斯州"),
                    ([439.0, 166.0, 489.0, 176.0], (441.0, 173.5), "3.21%, New York", "3.21%, 纽约州"),
                    ([439.0, 128.0, 498.0, 139.0], (441.0, 136.0), "4.03%, Washington", "4.03%, 华盛顿州"),
                    ([439.0, 117.0, 491.0, 129.0], (441.0, 126.0), "4.26%, California", "4.26%, 加利福尼亚州"),
                ]:
                    fixed_line(page, page_number, rect_values, point, target, fontsize=4.0, source=source, fill=(1, 1, 1))
                fixed_line(page, page_number, [522.0, 326.0, 578.0, 341.0], (524.0, 337.5), "图 4.4.14", fontsize=5.8, source="Figure 4.4.14", fill=green_bg, color=(1, 1, 1), rule="ai_index_economy_jobs_figure_label_repair", policy="translate_jobs_figure_label_preserve_footer_geometry")

    if has_line_in_region(source_page, "AI Hiring", y0=358.0, y1=382.0):
                fixed_textbox(
                    page,
                    page_number,
                    [34.0, 356.0, 126.0, 382.0],
                    "人工智能招聘",
                    fontsize=12.0,
                    source="AI Hiring",
                    fill=sampled_background_color(page, fitz.Rect(34.0, 356.0, 126.0, 382.0)),
                    color=green_bg,
                    policy="translate_jobs_subsection_heading",
                )


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
