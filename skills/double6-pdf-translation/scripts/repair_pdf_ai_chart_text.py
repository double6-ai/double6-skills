# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai chart text：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_chart_labels_from_text_layer(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import ai_index_chart_label_repair_skip_reason, cjk_text_width, expanded_rect, normalize_text, page_lines, replace_highlight_label, replace_rect_source_han
    repairs: list[dict[str, Any]] = []
    chart_label_map = {
        "API access": "API访问",
        "Hosted access (no API)": "托管访问（无API）",
        "Open weights (noncommercial)": "开放权重（非商业）",
        "Open weights (restricted use)": "开放权重（受限）",
        "Open weights (unrestricted)": "开放权重（无限制）",
        "Open (restricted use)": "开放（受限）",
        "Open (noncommercial)": "开放（非商业）",
        "Unreleased": "未发布",
        "Unknown": "未知",
        "Open source": "开源",
        "Closed source": "闭源",
        "Academia": "学术界",
        "Industry-academia collaboration": "产学合作",
        "Industry": "产业界",
        "Nonprofit": "非营利",
        "NonproǇt": "非营利",
        "Nonpro·t": "非营利",
        "United States": "美国",
        "China": "中国",
        "Number of notable AI models": "知名AI模型数",
        "Notable AI models (% of total)": "知名AI模型占比",
        "Publication date": "发布日期",
        "Training dataset size (tokens - log scale)": "训练数据集规模（词元，对数刻度）",
        "Training time (days - log scale)": "训练时间（天，对数刻度）",
        "Training compute (FLOP - log scale)": "训练算力（FLOP，对数刻度）",
        "Training compute (petaFLOP - log scale)": "训练算力（petaFLOP，对数刻度）",
        "Training compute (petaFLOP – log scale)": "训练算力（petaFLOP，对数刻度）",
        "Number of parameters (log scale)": "参数数量（对数刻度）",
        "Cumulative number of notable AI models": "值得关注AI模型累计数量",
        "Cumulative number of notable AI models trained by accelerator, 2017–25": "2017-25年按加速器训练的值得关注AI模型累计数量",
        "Cumulative compute capacity (H100e)": "累计计算能力（H100e）",
        "Cumulative power capacity (GW)": "累计电力容量（GW）",
        "Data Center Power Capacity": "数据中心电力容量",
        "Global AI data center power capacity, 2022–25": "2022-25年全球AI数据中心电力容量",
        "Other AI data center power": "其他AI数据中心电力",
        "data center power": "数据中心电力",
        "AI chip power (TDP)": "AI芯片功耗（TDP）",
        "Power infrastructure": "电力基础设施",
        "Inference": "推理",
        "Energy consumption (avg. - Wh)": "能耗（平均值，Wh）",
        "Carbon emissions (avg. - gCO₂e)": "碳排放（平均值，gCO₂e）",
        "Carbon emissions (avg. - gCO2e)": "碳排放（平均值，gCO2e）",
        "Energy consumption (Wh)": "能耗（Wh）",
        "Annual water consumption (kL)": "年度用水量（千升）",
        "Data Center Usage": "数据中心使用",
        "Cumulative": "累计",
        "Other AI systems": "其他AI系统",
        "Other AI accelerator modules": "其他AI加速器模块",
        "AI accelerator modules": "AI加速器模块",
        "All-in AI systems": "全栈AI系统",
        "The Netherlands": "荷兰",
        "Ireland": "爱尔兰",
        "Switzerland": "瑞士",
        "Austria": "奥地利",
        "Finland": "芬兰",
        "Bitcoin mining": "比特币挖矿",
        "Data centers": "数据中心",
        "(excl. crypto)": "（不含加密货币）",
        "Megawatts (MW)": "兆瓦（MW）",
        "Power demand (in thousands - megawatts)": "电力需求（千兆瓦）",
        "AI Development Activity Overview": "AI开发活动概览",
        "Projects": "项目",
        "GPU computation cost, 2006–24": "2006-24年GPU计算成本",
        "GPU cost index (2006=1)": "GPU成本指数（2006=1）",
        "Data center electricity consumption by region, 2020–30": "2020-30年按地区划分的数据中心用电量",
        "Electricity consumption (TWh)": "用电量（TWh）",
        "North America": "北美",
        "Europe": "欧洲",
        "Rest of the world": "世界其他地区",
        "Number of AI projects (in millions)": "AI项目数量（百万）",
        "Number of AI projects (in thousands)": "AI项目数量（千）",
        "AI projects (% of total)": "AI项目占比",
        "GitHub AI projects with at least 10 stars (% of total) by geographic area, 2011–25": "2011-25年各地区至少10个星标的GitHub AI项目占比",
        "GitHub AI projects with at least 10 stars": "至少10个星标的GitHub AI项目",
        "Number of GitHub stars (in millions)": "GitHub星标数（百万）",
        "Number of cumulative GitHub stars (in millions)": "GitHub累计星标数（百万）",
        "Number of models and datasets (in thousands)": "模型和数据集数量（千）",
        "Global distribution of downloads among top Hugging Face models, Q2 2020–Q3 2025": "2020年第二季度至2025年第三季度热门Hugging Face模型下载量的全球分布",
        "Download share by developer among top Hugging Face models, Q2 2020–Q3 2025": "2020年第二季度至2025年第三季度热门Hugging Face模型按开发者划分的下载份额",
        "Download share by modality among top Hugging Face models, Q3 2022–Q3 2025": "2022年第三季度至2025年第三季度热门Hugging Face模型按模态划分的下载份额",
        "Download share": "下载份额",
        "Unaffiliated user": "未关联用户",
        "Unaǅliated user": "未关联用户",
        "Una liated user": "未关联用户",
        "International/Online": "国际/在线",
        "Text generation": "文本生成",
        "Text embedding": "文本嵌入",
        "Text-to-image": "文生图",
        "Image-to-text": "图生文",
        "Multimodal generation": "多模态生成",
        "Multimodal embedding": "多模态嵌入",
        "Tabular models": "表格模型",
        "Computer vision": "计算机视觉",
        "Top 20 (inclusive)": "前20名（含）",
        "Top 20 (exclusive)": "前20名（不含）",
        "Total Number of AI Publications": "AI出版物总数",
        "AI publications in CS worldwide, 2013–24": "2013-24年全球计算机科学领域AI出版物",
        "Number of AI publications in CS (in thousands)": "CS领域AI出版物数量（千）",
        "Number of AI publications (in thousands)": "AI出版物数量（千）",
        "Number of AI publications by select top topics, 2013–24": "2013-24年按热门主题划分的AI出版物数量",
        "Number of AI publications by select top topics, 2013-24": "2013-24年按热门主题划分的AI出版物数量",
        "AI publications in CS (%)": "CS领域AI出版物占比",
        "AI publications in CS (% of total)": "CS领域AI出版物占比",
        "AI publications in CS (% of total) by sector, 2013–24": "2013-24年按部门划分的CS领域AI出版物占比",
        "AI publications in CS (% of total) by sector, 2013-24": "2013-24年按部门划分的CS领域AI出版物占比",
        "AI publications in CS (% of total) by sector and geographic area, 2024": "2024年按部门和地理区域划分的CS领域AI出版物占比",
        "By Sector": "按部门划分",
        "By Topic": "按主题划分",
        "By National Affiliation": "按国家/地区归属划分",
        "By Sector and Organization": "按部门与组织划分",
        "Top 100 Publications": "前100篇出版物",
        "Number of highly cited publications in top 100": "前100篇高被引出版物数量",
        "Number of highly cited publications in top 100 by select geographic areas, 2021–24": "2021-24年按选定地理区域划分的前100篇高被引出版物数量",
        "Number of highly cited publications in top 100 by select geographic areas, 2021-24": "2021-24年按选定地理区域划分的前100篇高被引出版物数量",
        "Patents": "专利",
        "PATENTS": "专利",
        "Global Trends": "全球趋势",
        "Speed of Knowledge Diffusion": "知识扩散速度",
        "Forward Citations Flow": "前向引用流向",
        "Citing country": "引用方国家/地区",
        "Cited country": "被引用方国家/地区",
        "Number of AI patents granted (in thousands)": "授权AI专利数量（千）",
        "Granted AI patents (% of world total)": "授权AI专利占全球总量比例",
        "Granted AI patents (% of world total) by select geographic areas, 2010–24": "2010-24年按选定地理区域划分的授权AI专利占全球总量比例",
        "Granted AI patents (% of world total) by select geographic areas, 2010-24": "2010-24年按选定地理区域划分的授权AI专利占全球总量比例",
        "Global distribution of forward citations to AI patents by geographic area, 2010–24": "2010-24年按地理区域划分的AI专利前向引用全球分布",
        "Global distribution of forward citations to AI patents by geographic area, 2010-24": "2010-24年按地理区域划分的AI专利前向引用全球分布",
        "Technological Proximity": "技术接近度",
        "Years since publication": "发表后年数",
        "Survival probability (no citation yet)": "生存概率（尚未被引用）",
        "Proximity to the United States": "与美国的技术接近度",
        "Proximity to China": "与中国的技术接近度",
        "AI patent portfolios’ technological proximity to the United States and China, 2010–24": "2010-24年AI专利组合与美国和中国的技术接近度",
        "AI patent portfolios' technological proximity to the United States and China, 2010-24": "2010-24年AI专利组合与美国和中国的技术接近度",
        "AI Patent Examples": "AI专利示例",
        "Top AI authors and inventors per 100,000 inhabitants by country, 2025": "2025年按国家划分的每10万人口顶级AI作者与发明者数量",
        "Top AI authors and inventors (per 100,000 inhabitants)": "每10万人口中的顶级AI作者与发明者数量",
        "Number of top AI authors and inventors (in thousands)": "顶级AI作者与发明者数量（千）",
        "By Education Level": "按教育水平划分",
        "By Gender": "按性别划分",
        "By Specialization": "按专业领域划分",
        "Mobility": "流动性",
        "Geographic Distribution": "地理分布",
        "% of AI authors and inventors by education level": "按教育水平划分的AI作者与发明者占比",
        "Percentage of top AI authors and inventors by education level and country, 2010–25": "2010-25年按教育水平和国家划分的顶级AI作者与发明者占比",
        "Percentage of top AI authors and inventors by education level and country, 2010-25": "2010-25年按教育水平和国家划分的顶级AI作者与发明者占比",
        "Top AI authors and inventors (% of total)": "顶级AI作者与发明者占比",
        "Top AI authors and inventors (% of total) by gender, 2010–25": "2010-25年按性别划分的顶级AI作者与发明者占比",
        "Top AI authors and inventors (% of total) by gender, 2010-25": "2010-25年按性别划分的顶级AI作者与发明者占比",
        "Within-country distribution of top AI authors and inventors across specialization areas": "各国顶级AI作者与发明者在专业领域中的分布",
        "Area of specialization": "专业领域",
        "Net ǈow top AI authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
        "Net flow top AI authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
        "Net ǈow of top AI authors and inventors by country, 2010–25": "2010-25年按国家划分的顶级AI作者与发明者净流动",
        "Net flow of top AI authors and inventors by country, 2010-25": "2010-25年按国家划分的顶级AI作者与发明者净流动",
        "Image classiǇcation (ImageNet Top-5)": "图像分类（ImageNet Top-5）",
        "Image classi·cation (ImageNet Top-5)": "图像分类（ImageNet Top-5）",
        "Image classification (ImageNet Top-5)": "图像分类（ImageNet Top-5）",
        "Visual reasoning (VQA)": "视觉推理（VQA）",
        "Multitask language understanding (MMLU)": "多任务语言理解（MMLU）",
        "Competition-level mathematics (MATH)": "竞赛级数学（MATH）",
        "Agent multimodal computer use (OSWorld)": "智能体多模态计算机使用（OSWorld）",
        "Mathematical reasoning (AIME)": "数学推理（AIME）",
        "Performance relative to the human baseline (%)": "相对人类基准的表现（%）",
        "Human baseline": "人类基准",
        "Arena score (Elo-like)": "Arena得分（类Elo）",
        "No available data": "无可用数据",
        "Number of data centers": "数据中心数量",
        "Number of data centers by geographic area, 2025": "2025年按地区划分的数据中心数量",
        "Source: Cloudscene, 2025 | Chart: 2026 AI Index report": "来源：Cloudscene，2025 | 图表：2026年AI指数报告",
        "Government": "政府",
        "Australia": "澳大利亚",
        "Netherlands": "荷兰",
        "Russia": "俄罗斯",
        "Taiwan": "中国台湾",
        "WIPO": "世界知识产权组织（WIPO）",
        "European Patent Office": "欧洲专利局",
        "European Patent Oǅce": "欧洲专利局",
        "Malaysia": "马来西亚",
        "Spain": "西班牙",
        "South Africa": "南非",
        "United Arab Emirates": "阿联酋",
        "Saudi Arabia": "沙特阿拉伯",
        "South Korea": "韩国",
        "Brazil": "巴西",
        "Mexico": "墨西哥",
        "Italy": "意大利",
        "India": "印度",
        "Poland": "波兰",
        "Switzerland": "瑞士",
        "Denmark": "丹麦",
        "Greece": "希腊",
        "Sweden": "瑞典",
        "Luxembourg": "卢森堡",
        "Leading hardware": "领先硬件",
        "Non-leading hardware": "非领先硬件",
        "Energy efficiency (FLOP/s per watt - log scale)": "能效（FLOP/s 每瓦，对数刻度）",
        "Energy eǅciency (FLOP/s per watt - log scale)": "能效（FLOP/s 每瓦，对数刻度）",
        "Total power draw required (watts - log scale)": "所需总功耗（瓦，对数刻度）",
        "Total power draw required to train frontier models, 2011–25": "2011-25年训练前沿模型所需总功耗",
        "Carbon emissions (tons of CO₂ equivalent)": "碳排放（吨二氧化碳当量）",
        "Carbon emissions (tons of CO2 equivalent)": "碳排放（吨二氧化碳当量）",
        "Carbon emissions (tons of CO₂ equivalent - log scale)": "碳排放（吨二氧化碳当量，对数刻度）",
        "Carbon emissions (tons of CO2 equivalent - log scale)": "碳排放（吨二氧化碳当量，对数刻度）",
        "Estimated carbon emissions from training select AI models and real-life activities, 2012–25": "2012-25年部分AI模型训练与现实活动的估算碳排放",
        "Estimated carbon emissions and number of parameters by select AI models": "部分AI模型的估算碳排放与参数数量",
        "Air travel (1 passenger, NY↔SF): 0.99": "航空旅行（NY-SF）：0.99",
        "Human life (avg., 1 year): 5.51": "人类生活（平均1年）：5.51",
        "American life (avg., 1 year): 18.08": "美国人生活（平均1年）：18.08",
        "Tokens": "词元",
        "HIGHLIGHT:": "要点",
        "Will Models Run Out of Data?": "模型会耗尽数据吗？",
        "Synthetic Data in Pre-training": "预训练中的合成数据",
        "Data-centric Methods": "以数据为中心的方法",
        "Synthetic Data in Post-training": "后训练中的合成数据",
        "Prevalence of Synthetic Content": "合成内容的普及",
        "Model performance on AIME 2025": "模型在 AIME 2025 上的表现",
        "AI-generated content vs. human content": "AI 生成内容与人类内容",
        "% AI-generated content": "AI 生成内容占比",
    }
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        narrow_vertical_axis_sources = {
            "Energy efficiency (FLOP/s per watt - log scale)",
            "Energy eǅciency (FLOP/s per watt - log scale)",
            "Total power draw required (watts - log scale)",
            "Carbon emissions (tons of CO₂ equivalent)",
            "Carbon emissions (tons of CO2 equivalent)",
            "Carbon emissions (tons of CO₂ equivalent - log scale)",
            "Carbon emissions (tons of CO2 equivalent - log scale)",
            "Survival probability (no citation yet)",
            "Proximity to the United States",
            "Proximity to China",
            "Number of parameters (log scale)",
            "Number of AI patents granted (in thousands)",
            "Granted AI patents (% of world total)",
            "Granted AI patents (% of world total) by select geographic areas, 2010–24",
            "Granted AI patents (% of world total) by select geographic areas, 2010-24",
            "Performance relative to the human baseline (%)",
            "Arena score (Elo-like)",
        }
        page_text_norm = normalize_text(page.get_text("text"))
        for source, target in sorted(chart_label_map.items(), key=lambda item: len(item[0]), reverse=True):
            if ai_index_chart_label_repair_skip_reason(source):
                continue
            if target in page_text_norm and source not in page_text_norm:
                continue
            raw_hits = list(page.search_for(source))
            if ai_index_chart_label_repair_skip_reason(source, hit_count=len(raw_hits)):
                continue
            hits = raw_hits[:10]
            if source == "Air travel (1 passenger, NY↔SF): 0.99" and hits:
                merged = hits[0]
                for hit in hits[1:]:
                    if abs(hit.y0 - merged.y0) < 3.0 and abs(hit.y1 - merged.y1) < 3.0:
                        merged |= hit
                hits = [merged]
            if not hits:
                for row in page_lines(page):
                    if source in str(row.get("normalized") or ""):
                        rect = expanded_rect(fitz, row.get("bbox"), page, pad=0.2, min_width=8)
                        if rect:
                            hits.append(rect)
            for hit in hits[:10]:
                rect = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], page, pad=1.8, min_width=24)
                if not rect:
                    continue
                rotate = 90 if rect.height > rect.width * 1.8 else 0
                if rotate and source in narrow_vertical_axis_sources:
                    rect = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], page, pad=0.35, min_width=8) or rect
                if source == "HIGHLIGHT:":
                    rect.x0 = max(0, rect.x0 - 2.0)
                    rect.y0 = max(0, rect.y0 - 4.0)
                    rect.x1 = min(page.rect.width, max(rect.x1 + 4.0, rect.x0 + 48.0))
                    rect.y1 = min(page.rect.height, max(rect.y1 + 4.0, rect.y0 + 15.0))
                    meta = replace_highlight_label(page, rect, target, fontsize=6.8)
                    meta.update(
                        {
                            "font_policy": "embed_source_han_sans_for_chart_label_redraw",
                            "text_policy": "translate_ai_index_chart_label_from_visible_text_layer_preserve_model_names_and_numeric_ticks",
                        }
                    )
                    repairs.append(
                        {
                            "page": page_number,
                            "rule": "ai_index_chart_label_text_layer_repair",
                            "source": source,
                            "target": target,
                            "rotate": rotate,
                            **meta,
                        }
                    )
                    continue
                elif rotate:
                    min_axis_width = 8.0 if source in narrow_vertical_axis_sources else 32.0
                    rect.x1 = min(page.rect.width, rect.x0 + max(rect.width, min_axis_width))
                    rect.y1 = min(page.rect.height, rect.y1 + 10.0)
                    repair_fill = (1, 1, 1)
                    repair_fontsize = 5.6
                else:
                    estimated_width = cjk_text_width(fitz, target, fontsize=6.0) + 6.0
                    rect.x1 = min(page.rect.width - 8.0, max(rect.x1, rect.x0 + min(estimated_width, page.rect.width - rect.x0 - 8.0)))
                    rect.y1 = min(page.rect.height, max(rect.y1, rect.y0 + 13.0))
                    repair_fill = None
                    if source not in {"Geographic Distribution", "By Education Level", "AI Patent Examples"}:
                        repair_fill = (1, 1, 1)
                    repair_fontsize = 6.0
                meta = replace_rect_source_han(page, rect, target, fontsize=repair_fontsize, rotate=rotate, fill=repair_fill)
                meta.update(
                    {
                        "font_policy": "embed_source_han_sans_for_chart_label_redraw",
                        "text_policy": "translate_ai_index_chart_label_from_visible_text_layer_preserve_model_names_and_numeric_ticks",
                    }
                )
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_chart_label_text_layer_repair",
                        "source": source,
                        "target": target,
                        "rotate": rotate,
                        **meta,
                    }
                )
            if hits:
                page_text_norm = normalize_text(page.get_text("text"))
        page_text_after = normalize_text(page.get_text("text"))
        if (
            page_number == 1
            and "训练算" in page_text_after
            and "petaFLOP" in page_text_after
            and "美国" not in page_text_after
            and "中国" not in page_text_after
        ):
            for source, target, bbox in [
                ("United States", "美国", [95.0, 436.2, 139.5, 449.5]),
                ("China", "中国", [158.5, 436.2, 181.5, 449.5]),
            ]:
                rect = fitz.Rect(bbox)
                meta = replace_rect_source_han(page, rect, target, fontsize=6.0, fill=(1, 1, 1))
                meta.update(
                    {
                        "font_policy": "embed_source_han_sans_for_missing_chart_legend_redraw",
                        "text_policy": "insert_missing_ai_index_chart_legend_label_preserve_series_color_marker",
                    }
                )
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_chart_label_text_layer_repair",
                        "source": source,
                        "target": target,
                        "rotate": 0,
                        **meta,
                    }
                )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
