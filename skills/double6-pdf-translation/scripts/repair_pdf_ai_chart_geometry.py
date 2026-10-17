# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai chart geometry：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_chart_labels_from_source_bboxes(
    fitz: Any,
    source_doc: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    from repair_pdf_drawing import ai_index_chart_label_repair_skip_reason, cjk_text_width, expanded_rect, insert_source_han_sans, normalize_text, replace_rect_source_han
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    chart_label_map = {
        "By National Affiliation": "按国家/地区归属划分",
        "By Sector and Organization": "按部门与组织划分",
        "By Topic": "按主题划分",
        "Top 100 Publications": "前100篇出版物",
        "AI publications in CS (% of total) by sector and geographic area, 2024": "2024年按部门和地理区域划分的CS领域AI出版物占比",
        "AI publications in CS (% of total) by sector, 2013–24": "2013-24年按部门划分的CS领域AI出版物占比",
        "AI publications in CS (% of total) by sector, 2013-24": "2013-24年按部门划分的CS领域AI出版物占比",
        "Number of AI publications by select top topics, 2013–24": "2013-24年按热门主题划分的AI出版物数量",
        "Number of AI publications by select top topics, 2013-24": "2013-24年按热门主题划分的AI出版物数量",
        "Number of highly cited publications in top 100 by select geographic areas, 2021–24": "2021-24年按选定地理区域划分的前100篇高被引出版物数量",
        "Number of highly cited publications in top 100 by select geographic areas, 2021-24": "2021-24年按选定地理区域划分的前100篇高被引出版物数量",
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
        "Proximity to the United States": "与美国的技术接近度",
        "Proximity to China": "与中国的技术接近度",
        "Top AI authors and inventors (% of total)": "顶级AI作者与发明者占比",
        "Top AI authors and inventors (% of total) by gender, 2010–25": "2010-25年按性别划分的顶级AI作者与发明者占比",
        "Top AI authors and inventors (% of total) by gender, 2010-25": "2010-25年按性别划分的顶级AI作者与发明者占比",
        "By Education Level": "按教育水平划分",
        "By Gender": "按性别划分",
        "By Specialization": "按专业领域划分",
        "Mobility": "流动性",
        "% of AI authors and inventors by education level": "按教育水平划分的AI作者与发明者占比",
        "Percentage of top AI authors and inventors by education level and country, 2010–25": "2010-25年按教育水平和国家划分的顶级AI作者与发明者占比",
        "Percentage of top AI authors and inventors by education level and country, 2010-25": "2010-25年按教育水平和国家划分的顶级AI作者与发明者占比",
        "Within-country distribution of top AI authors and inventors across specialization areas": "各国顶级AI作者与发明者在专业领域中的分布",
        "Area of specialization": "专业领域",
        "Net ǈow top AI authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
        "Net flow top AI authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
        "Net ǈow of top AI authors and inventors by country, 2010–25": "2010-25年按国家划分的顶级AI作者与发明者净流动",
        "Net flow of top AI authors and inventors by country, 2010-25": "2010-25年按国家划分的顶级AI作者与发明者净流动",
        "Arena score (Elo-like)": "Arena得分（类Elo）",
        "Precision@50": "Precision@50",
        "Benchmark": "Benchmark",
        "MMLU Math": "MMLU Math",
        "OpenBookQA": "OpenBookQA",
        "MMLU CLG": "MMLU CLG",
        "MMLU Med": "MMLU Med",
        "AIR-Bench": "AIR-Bench",
        "MMLU Q&A": "MMLU Q&A",
        "Theorem": "Theorem",
        "MMLU SSb": "MMLU SSb",
        "GSM8K": "GSM8K",
        "European Patent Office": "欧洲专利局",
        "European Patent Oǅce": "欧洲专利局",
        "Rest of the world": "世界其他地区",
        "United Arab Emirates": "阿联酋",
        "United States": "美国",
        "United Kingdom": "英国",
        "Saudi Arabia": "沙特阿拉伯",
        "South Africa": "南非",
        "South Korea": "韩国",
        "Switzerland": "瑞士",
        "Netherlands": "荷兰",
        "India*": "印度*",
        "United States*": "美国*",
        "Australia": "澳大利亚",
        "Luxembourg": "卢森堡",
        "Malaysia": "马来西亚",
        "Austria": "奥地利",
        "Finland": "芬兰",
        "Denmark": "丹麦",
        "Singapore": "新加坡",
        "Germany": "德国",
        "Canada": "加拿大",
        "France": "法国",
        "Poland": "波兰",
        "Russia": "俄罗斯",
        "Greece": "希腊",
        "Israel": "以色列",
        "Japan": "日本",
        "Sweden": "瑞典",
        "Spain": "西班牙",
        "Taiwan": "中国台湾",
        "India": "印度",
        "Italy": "意大利",
        "Brazil": "巴西",
        "WIPO": "WIPO",
    }

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    contextual_short_sources = {
        "European Patent Office",
        "European Patent Oǅce",
        "Rest of the world",
        "United Arab Emirates",
        "United States",
        "United Kingdom",
        "Saudi Arabia",
        "South Africa",
        "South Korea",
        "Switzerland",
        "Netherlands",
        "Australia",
        "Luxembourg",
        "Malaysia",
        "Austria",
        "Finland",
        "Denmark",
        "Singapore",
        "Germany",
        "Canada",
        "France",
        "Poland",
        "Russia",
        "Greece",
        "Israel",
        "Japan",
        "Sweden",
        "Spain",
        "Taiwan",
        "India",
        "India*",
        "Italy",
        "Brazil",
        "United States*",
        "WIPO",
        "Arena score (Elo-like)",
        "Precision@50",
        "Benchmark",
        "MMLU Math",
        "OpenBookQA",
        "MMLU CLG",
        "MMLU Med",
        "AIR-Bench",
        "MMLU Q&A",
        "Theorem",
        "MMLU SSb",
        "GSM8K",
    }
    technical_arena_sources = {"Arena score (Elo-like)"}
    invalid_question_benchmark_sources = {
        "Precision@50",
        "Benchmark",
        "MMLU Math",
        "OpenBookQA",
        "MMLU CLG",
        "MMLU Med",
        "AIR-Bench",
        "MMLU Q&A",
        "Theorem",
        "MMLU SSb",
        "GSM8K",
    }
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        target_page = doc[page_index]
        source_context = normalize_text(source_page.get_text("text"))
        dense_time_axis_panel = source_context.count("2010") >= 5 and source_context.count("2025") >= 5
        ai_author_education_panel = bool(
            dense_time_axis_panel
            and
            re.search(r"% of AI authors and inventors by education level|by education level and country", source_context, re.I)
        )
        ai_author_gender_panel = bool(
            dense_time_axis_panel
            and
            re.search(r"By Gender|by gender, 2010", source_context, re.I)
            and re.search(r"Top AI authors and inventors \(% of total\)", source_context, re.I)
        )
        ai_author_mobility_panel = bool(
            dense_time_axis_panel
            and
            re.search(r"Net (?:ǈow|flow) (?:of )?top AI authors and inventors", source_context, re.I)
        )
        ai_author_geographic_panel = bool(
            re.search(r"\bGeographic Distribution\b", source_context, re.I)
            and re.search(
                r"Top AI authors and inventors per 100,000 inhabitants|Number of top AI authors and inventors",
                source_context,
                re.I,
            )
        )
        technical_arena_panel = bool(
            re.search(r"Arena score \(Elo-like\)|Arena Leaderboard|Performance of top models on the Arena", source_context, re.I)
        )
        invalid_question_benchmark_panel = bool(
            re.search(r"Invalid question detection across nine benchmarks|Precision@50|MMLU Math|OpenBookQA", source_context, re.I)
        )
        allow_contextual_short_sources = bool(
            re.search(
                r"Technological Proximity|AI Patent Examples",
                source_context,
                re.I,
            )
            or ai_author_education_panel
            or ai_author_gender_panel
            or ai_author_mobility_panel
            or ai_author_geographic_panel
        )
        target_text = normalize_text(target_page.get_text("text"))
        for source, target in sorted(chart_label_map.items(), key=lambda item: len(item[0]), reverse=True):
            source_is_special_technical_label = (
                (source in technical_arena_sources and technical_arena_panel)
                or (source in invalid_question_benchmark_sources and invalid_question_benchmark_panel)
            )
            if source in technical_arena_sources and source_is_special_technical_label and target in target_text:
                continue
            if source in contextual_short_sources and not (allow_contextual_short_sources or source_is_special_technical_label):
                continue
            if target in target_text and source not in contextual_short_sources:
                continue
            hits = list(source_page.search_for(source))
            if source in contextual_short_sources:
                if "AI Patent Examples" in source_context:
                    hits = [hit for hit in hits if 120 < hit.y0 < 275]
                elif ai_author_education_panel:
                    hits = [hit for hit in hits if hit.y0 > 105]
                elif ai_author_gender_panel:
                    hits = [hit for hit in hits if hit.y0 > 215]
                elif ai_author_mobility_panel:
                    hits = [hit for hit in hits if 90 < hit.y0 < 705]
                elif "By Education Level" in source_context:
                    hits = [hit for hit in hits if hit.y0 < 360]
                elif ai_author_geographic_panel:
                    hits = [hit for hit in hits if hit.y0 > 430]
                elif source in {"Arena score (Elo-like)"} and technical_arena_panel:
                    hits = [hit for hit in hits if 80 < hit.y0 < 660]
                elif source in {
                    "Precision@50",
                    "Benchmark",
                    "MMLU Math",
                    "OpenBookQA",
                    "MMLU CLG",
                    "MMLU Med",
                    "AIR-Bench",
                    "MMLU Q&A",
                    "Theorem",
                    "MMLU SSb",
                    "GSM8K",
                } and invalid_question_benchmark_panel:
                    hits = [hit for hit in hits if hit.x0 > 285 and hit.y0 > 500]
            if ai_index_chart_label_repair_skip_reason(source, hit_count=len(hits)):
                continue
            for hit in hits[:3]:
                rect = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], target_page, pad=1.8, min_width=26)
                if not rect:
                    continue
                rotate = 90 if rect.height > rect.width * 1.8 else 0
                if rotate:
                    rect.x1 = min(target_page.rect.width, rect.x0 + max(rect.width, 32.0))
                    rect.y1 = min(target_page.rect.height, rect.y1 + 10.0)
                    repair_fill = (1, 1, 1)
                    repair_fontsize = 5.6
                    if source in {
                        "Arena score (Elo-like)",
                        "Precision@50",
                        "MMLU Math",
                        "OpenBookQA",
                        "MMLU CLG",
                        "MMLU Med",
                        "AIR-Bench",
                        "MMLU Q&A",
                        "Theorem",
                        "MMLU SSb",
                        "GSM8K",
                    }:
                        rect.x1 = min(target_page.rect.width, rect.x1 + 8.0)
                        rect.y0 = max(0, rect.y0 - 4.0)
                        rect.y1 = min(target_page.rect.height, rect.y1 + 18.0)
                else:
                    estimated_width = cjk_text_width(fitz, target, fontsize=6.0) + 6.0
                    rect.x1 = min(
                        target_page.rect.width - 8.0,
                        max(rect.x1, rect.x0 + min(estimated_width, target_page.rect.width - rect.x0 - 8.0)),
                    )
                    rect.y1 = min(target_page.rect.height, max(rect.y1, rect.y0 + 13.0))
                    repair_fill = (1, 1, 1) if source in contextual_short_sources else None
                    repair_fontsize = 6.0
                if source in contextual_short_sources and not rotate:
                    _redact_with_fill(target_page, rect, repair_fill or (1, 1, 1))
                    insert_source_han_sans(target_page, (rect.x0 + 0.6, rect.y1 - 3.1), target, fontsize=5.5, color=(0, 0, 0))
                    meta = {
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 5.5,
                        "fill_strategy": "white_chart_panel_background_direct_short_label_redraw",
                    }
                elif source in {
                    "Arena score (Elo-like)",
                    "Precision@50",
                    "MMLU Math",
                    "OpenBookQA",
                    "MMLU CLG",
                    "MMLU Med",
                    "AIR-Bench",
                    "MMLU Q&A",
                    "Theorem",
                    "MMLU SSb",
                    "GSM8K",
                }:
                    if rotate and re.fullmatch(r"[A-Za-z0-9@& .+-]+", target):
                        _redact_with_fill(target_page, rect, (1, 1, 1))
                        # 旋转后的拉丁标签优先保证完整文本层；较长标签若沿用
                        # 统一字号，后续相邻 bbox 修复可能裁掉尾字符。
                        latin_fontsize = 4.6 if source == "OpenBookQA" else 5.2
                        target_page.insert_text(
                            (rect.x0 + 1.4, min(target_page.rect.height - 2.0, rect.y1 - 2.0)),
                            target,
                            fontname="helv",
                            fontsize=latin_fontsize,
                            rotate=90,
                            color=(0, 0, 0),
                            overlay=True,
                        )
                        meta = {
                            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                            "fontsize": latin_fontsize,
                            "fill_strategy": "white_chart_axis_background_complete_latin_fit_redraw",
                        }
                    else:
                        meta = replace_rect_source_han(target_page, rect, target, fontsize=5.2, rotate=rotate, fill=(1, 1, 1))
                        meta["fill_strategy"] = "white_chart_axis_background_passthrough_label_redraw"
                else:
                    meta = replace_rect_source_han(target_page, rect, target, fontsize=repair_fontsize, rotate=rotate, fill=repair_fill)
                meta.update(
                    {
                        "font_policy": "embed_source_han_sans_for_chart_label_redraw",
                        "text_policy": "translate_ai_index_chart_label_from_source_bbox_when_target_text_layer_missing",
                    }
                )
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_chart_label_source_bbox_repair",
                        "source": source,
                        "target": target,
                        "rotate": rotate,
                        **meta,
                    }
                )
                target_text = normalize_text(target_page.get_text("text"))
        # 所有 bbox 修复完成后再校验完整文本层。相邻 chart label 的后续
        # redaction 可能裁掉已写入的尾字符，因此只对不完整项做末次收口。
        if invalid_question_benchmark_panel:
            final_text = normalize_text(target_page.get_text("text"))
            for source in invalid_question_benchmark_sources:
                target = chart_label_map[source]
                if target in final_text:
                    continue
                hits = [hit for hit in source_page.search_for(source) if hit.x0 > 285 and hit.y0 > 500]
                if not hits:
                    continue
                hit = hits[0]
                rect = fitz.Rect(
                    max(0.0, hit.x0 - 2.0),
                    max(0.0, hit.y0 - 8.0),
                    min(target_page.rect.width, hit.x1 + 16.0),
                    min(target_page.rect.height, hit.y1 + 24.0),
                )
                _redact_with_fill(target_page, rect, (1, 1, 1))
                target_page.insert_text(
                    (rect.x0 + 1.2, rect.y1 - 2.0),
                    target,
                    fontname="helv",
                    fontsize=4.2,
                    rotate=90,
                    color=(0, 0, 0),
                    overlay=True,
                )
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_chart_label_complete_text_postvalidation_repair",
                        "source": source,
                        "target": target,
                        "rotate": 90,
                        "bbox": [round(value, 2) for value in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 4.2,
                        "fill_strategy": "white_chart_axis_background_postvalidated_complete_latin_redraw",
                        "text_policy": "validate_full_target_after_all_neighbor_bbox_repairs",
                    }
                )
                final_text = normalize_text(target_page.get_text("text"))
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
