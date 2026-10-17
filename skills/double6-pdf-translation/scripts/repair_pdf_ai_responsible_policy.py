# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai responsible policy：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_responsible_ai_policy_making_visible_labels(
    fitz: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    from repair_pdf_drawing import cjk_text_width, fit_source_han_textbox, insert_source_han_sans, normalize_text, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []

    def redraw_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float = 5.0,
        fill: tuple[float, float, float] = (1, 1, 1),
        source: str | None = None,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        page.draw_rect(rect, color=fill, fill=fill, overlay=True)
        fit_source_han_textbox(page, rect, target, fontsize=fontsize, color=(0, 0, 0))
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source or target,
                "target": target,
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": fontsize,
                "fill_strategy": "fixed_white_region_then_source_han_textbox_redraw",
                "font_policy": "source_han_sans_fixed_responsible_ai_policy_making_chart_label",
                "text_policy": "translate_responsible_ai_policy_making_visible_chart_labels_preserve_values_and_map_geometry",
            }
        )

    def redraw_baseline_rows(
        page: Any,
        page_number: int,
        rect_values: list[float],
        rows: list[tuple[float, str]],
        rule: str,
        *,
        fontsize: float = 5.1,
        x: float | None = None,
        right_align_x: float | None = None,
        fontname: str = "source_han",
        source: str | None = None,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
        x0 = rect.x0 + 1.0 if x is None else x
        for baseline, text in rows:
            draw_x = x0
            if right_align_x is not None:
                draw_x = right_align_x - cjk_text_width(fitz, text, fontsize=fontsize)
            if fontname == "helv":
                page.insert_text((draw_x, baseline), text, fontname="helv", fontsize=fontsize, color=(0, 0, 0), overlay=True)
            elif fontname == "china-s":
                page.insert_text((draw_x, baseline), text, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)
            else:
                insert_source_han_sans(page, (draw_x, baseline), text, fontsize=fontsize, color=(0, 0, 0))
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source or "fixed policy-making chart labels",
                "target": " / ".join(text for _, text in rows),
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": fontsize,
                "fill_strategy": "fixed_white_region_then_source_han_baseline_rows",
                "font_policy": "source_han_sans_fixed_responsible_ai_policy_making_dense_labels",
                "text_policy": "translate_dense_country_or_legend_labels_preserve_chart_values",
            }
        )

    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        match_text = (
            page_text
            .replace("理", "理")
            .replace("利", "利")
            .replace("行", "行")
            .replace("年", "年")
            .replace("量", "量")
        )
        has_policy_geographic_context = (
            "responsible AI papers" in match_text
            or "RAI papers" in match_text
            or "负责任人工智能论文" in match_text
            or "RAI论文" in match_text
            or "被选定AI会议录用" in match_text
        )
        if (
            "Geographic Distribution" in match_text
            or "地理分布" in match_text
            or ("2025年各地区" in match_text and "负责任人工智能论文数量" in match_text)
        ) and has_policy_geographic_context:
            redraw_textbox(
                page,
                page_number,
                [35.0, 118.0, 210.0, 146.5],
                "地理分布",
                "ai_index_responsible_ai_policy_geographic_distribution_heading_repair",
                fontsize=8.0,
                fill=sampled_background_color(page, fitz.Rect(35.0, 118.0, 210.0, 146.5)),
                source="Geographic Distribution",
            )
            redraw_textbox(
                page,
                page_number,
                [316.0, 136.0, 576.0, 158.8],
                "2025年各地区被选定AI会议录用的\nRAI论文数量",
                "ai_index_responsible_ai_policy_geographic_bar_title_repair",
                fontsize=5.3,
                source="Number of responsible AI papers accepted at select AI conferences by geographic area, 2025",
            )
            redraw_textbox(
                page,
                page_number,
                [316.0, 158.5, 576.0, 178.5],
                "来源：AI Index，2026 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_policy_geographic_bar_source_repair",
                fontsize=4.7,
                source="Source: AI Index, 2026 | Chart: 2026 AI Index report",
            )
            redraw_baseline_rows(
                page,
                page_number,
                [315.0, 170.0, 374.5, 352.0],
                [
                    (184.0, "中国"),
                    (202.2, "美国"),
                    (220.3, "新加坡"),
                    (238.5, "英国"),
                    (256.7, "中国香港"),
                    (274.9, "澳大利亚"),
                    (293.0, "德国"),
                    (311.1, "韩国"),
                    (329.3, "加拿大"),
                    (347.4, "意大利"),
                ],
                "ai_index_responsible_ai_policy_geographic_country_label_repair",
                fontsize=5.3,
                x=330.0,
                fontname="china-s",
                source="China / United States / Singapore / United Kingdom / Hong Kong / Australia / Germany / South Korea / Canada / Italy",
            )
            redraw_baseline_rows(
                page,
                page_number,
                [57.0, 641.0, 133.0, 722.0],
                [
                    (659.5, "1-10"),
                    (670.8, "11-50"),
                    (682.1, "51-150"),
                    (693.4, "151-500"),
                    (704.7, "501-2,100"),
                    (716.0, "2,101-3,900"),
                ],
                "ai_index_responsible_ai_policy_geographic_map_legend_repair",
                fontsize=5.2,
                x=84.0,
                fontname="helv",
                source="RAI papers map legend ranges",
            )
        has_ram_context = (
            ("readiness assessment methodology" in page_text or "RAM" in page_text)
            and "UNESCO" in page_text
        )
        has_ram_legend_only_context = (
            "UNESCO" in page_text
            and "In preparation" in page_text
            and "In process" in page_text
            and "Completed" in page_text
        )
        if has_ram_context or has_ram_legend_only_context:
            redraw_textbox(
                page,
                page_number,
                [36.0, 394.0, 535.0, 424.5],
                "各成员国实施人工智能准备度评估方法（RAM）的情况\n来源：联合国教科文组织（UNESCO），2025 | 图表：2026年AI Index报告",
                "ai_index_responsible_ai_policy_ram_map_title_source_repair",
                fontsize=5.4,
                source="Readiness Assessment Methodology (RAM) implementation across member countries",
            )
            redraw_baseline_rows(
                page,
                page_number,
                [64.0, 602.0, 134.0, 640.0],
                [
                    (614.5, "筹备中"),
                    (625.7, "进行中"),
                    (636.9, "已完成"),
                ],
                "ai_index_responsible_ai_policy_ram_map_legend_repair",
                fontsize=5.1,
                x=73.0,
                fontname="china-s",
                source="In preparation / In process / Completed",
            )
        if "Global AI Governance Participation" in page_text:
            redraw_textbox(
                page,
                page_number,
                [35.0, 69.0, 258.0, 91.0],
                "全球AI治理参与",
                "ai_index_responsible_ai_policy_governance_participation_heading_repair",
                fontsize=8.2,
                source="Global AI Governance Participation",
            )
        if "3.5 RAI POLICYMAKING" in page_text or "3.5 RAI" in page_text:
            rect = fitz.Rect(118.0, 25.0, 580.0, 42.0)
            fill = sampled_background_color(page, rect)
            _redact_with_fill(page, rect, fill)
            fit_source_han_textbox(
                page,
                rect,
                "3.5 RAI政策制定 | 负责任人工智能 | 人工智能指数报告 2026",
                fontsize=5.0,
                color=(0, 0, 0),
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_policy_running_header_repair",
                    "source": "3.5 RAI POLICYMAKING",
                    "target": "3.5 RAI政策制定 | 负责任人工智能 | 人工智能指数报告 2026",
                    "bbox": [118.0, 25.0, 580.0, 42.0],
                    "fontsize": 5.0,
                    "fill_strategy": "sampled_header_background_then_source_han_textbox_redraw",
                    "font_policy": "source_han_sans_fixed_responsible_ai_running_header",
                    "text_policy": "translate_responsible_ai_policy_making_running_header_consistently",
                }
            )
        if "152" in page_text and ("3.5 RAI POLICYMAKING" in page_text or "3.5 RAI" in page_text):
            title_rect = fitz.Rect(36.0, 92.0, 575.0, 116.5)
            _redact_with_fill(page, title_rect, (1, 1, 1))
            fit_source_han_textbox(
                page,
                title_rect,
                "AI治理机制参与情况\n来源：联合国“为人类治理AI”，2025；AI行动峰会，2025 | 图表：2026年AI Index报告",
                fontsize=5.0,
                color=(0, 0, 0),
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_policy_governance_mechanisms_table_title_repair",
                    "source": "Participation in AI governance mechanisms",
                    "target": "AI治理机制参与情况",
                    "bbox": [36.0, 92.0, 575.0, 116.5],
                    "fontsize": 5.0,
                    "fill_strategy": "white_table_title_band_then_source_han_textbox_redraw",
                    "font_policy": "source_han_sans_fixed_responsible_ai_policy_table_title",
                    "text_policy": "translate_governance_mechanisms_table_title_and_source_preserve_chart_matrix",
                }
            )
            header_rect = fitz.Rect(169.0, 120.0, 579.0, 149.5)
            _redact_with_fill(page, header_rect, (1, 1, 1))
            header_boxes = [
                ([172.0, 122.0, 223.0, 149.0], "OECD AI\n原则\n(2019)"),
                ([224.0, 122.0, 275.0, 149.0], "G20 AI\n原则\n(2019)"),
                ([276.0, 122.0, 327.0, 149.0], "欧洲委员会\n起草方\n(2022)"),
                ([328.0, 122.0, 379.0, 149.0], "GPAI部长级\n宣言\n(2022)"),
                ([380.0, 122.0, 431.0, 149.0], "布莱切利\n宣言\n(2023)"),
                ([432.0, 122.0, 483.0, 149.0], "G7广岛AI\n进程\n(2023)"),
                ([484.0, 122.0, 535.0, 149.0], "首尔部长级\n声明\n(2024)"),
                ([536.0, 122.0, 579.0, 149.0], "AI行动峰会\n声明\n(2025)"),
            ]
            for box, label in header_boxes:
                fit_source_han_textbox(page, fitz.Rect(box), label, fontsize=4.25, color=(0, 0, 0))
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_policy_governance_mechanisms_table_header_repair",
                    "source": "OECD AI Principles / G20 AI Principles / CoE drafters / GPAI Ministerial Declaration / Bletchley Declaration / G7 Hiroshima AI Process / Seoul Ministerial Statement / AI Action Summit Statement",
                    "target": "OECD AI原则 / G20 AI原则 / 欧洲委员会起草方 / GPAI部长级宣言 / 布莱切利宣言 / G7广岛AI进程 / 首尔部长级声明 / AI行动峰会声明",
                    "bbox": [169.0, 120.0, 579.0, 149.5],
                    "fontsize": 4.25,
                    "fill_strategy": "white_table_header_band_then_source_han_textbox_redraw",
                    "font_policy": "source_han_sans_fixed_responsible_ai_policy_table_headers",
                    "text_policy": "translate_governance_mechanisms_table_column_headers_preserve_matrix_values",
                }
            )
            country_rect = fitz.Rect(37.0, 139.5, 169.0, 737.0)
            _redact_with_fill(page, country_rect, (1, 1, 1))
            country_labels = [
                "阿根廷", "亚美尼亚", "澳大利亚", "奥地利", "巴林", "比利时", "巴西", "加拿大",
                "智利", "中国", "哥伦比亚", "丹麦", "埃及", "爱沙尼亚", "欧盟", "芬兰",
                "法国", "德国", "希腊", "匈牙利", "冰岛", "印度", "印度尼西亚", "爱尔兰",
                "以色列", "意大利", "日本", "肯尼亚", "立陶宛", "卢森堡", "马来西亚", "马耳他",
                "墨西哥", "摩洛哥", "荷兰", "新西兰", "尼日利亚", "挪威", "巴基斯坦", "葡萄牙",
                "卡塔尔", "韩国", "俄罗斯联邦", "沙特阿拉伯", "新加坡", "斯洛伐克", "斯洛文尼亚",
                "南非", "西班牙", "斯里兰卡", "瑞典", "瑞士", "突尼斯", "土耳其", "阿联酋",
                "英国", "美国", "乌拉圭", "越南",
            ]
            y = 151.2
            for label in country_labels:
                draw_x = 164.0 - cjk_text_width(fitz, label, fontsize=4.15)
                insert_source_han_sans(page, (draw_x, y), label, fontsize=4.15, color=(0, 0, 0))
                y += 9.45
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_policy_governance_mechanisms_country_label_repair",
                    "source": "country and region labels in governance mechanisms table",
                    "target": "translated_country_region_labels",
                    "bbox": [37.0, 139.5, 169.0, 737.0],
                    "fontsize": 4.15,
                    "fill_strategy": "white_country_label_band_then_right_aligned_source_han_rows",
                    "font_policy": "source_han_sans_fixed_responsible_ai_policy_table_country_labels",
                    "text_policy": "translate_country_region_labels_preserve_table_matrix_geometry",
                }
            )
    return repairs


def repair_ai_index_responsible_ai_privacy_fairness_visible_labels(
    fitz: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []

    def fixed_textbox(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        fill: tuple[float, float, float] | None = None,
        color: tuple[float, float, float] = (0, 0, 0),
        source: str,
        policy: str,
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color)
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": target,
                **meta,
                "font_policy": "source_han_sans_fixed_responsible_ai_privacy_fairness_label",
                "text_policy": policy,
            }
        )

    def fixed_baseline_rows(
        page: Any,
        page_number: int,
        rect_values: list[float],
        rows: list[tuple[float, str]],
        rule: str,
        *,
        fontsize: float,
        x: float,
        source: str,
        policy: str,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
        for baseline, text in rows:
            insert_source_han_sans(page, (x, baseline), text, fontsize=fontsize, color=(0, 0, 0))
        repairs.append(
            {
                "page": page_number,
                "rule": rule,
                "source": source,
                "target": " / ".join(text for _, text in rows),
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fontsize": fontsize,
                "fill_strategy": "fixed_white_region_then_source_han_baseline_rows",
                "font_policy": "source_han_sans_fixed_responsible_ai_privacy_fairness_legend",
                "text_policy": policy,
            }
        )

    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        match_text = (
            page_text.replace("理", "理")
            .replace("利", "利")
            .replace("行", "行")
            .replace("年", "年")
            .replace("量", "量")
        )
        rows = page_lines(page)
        has_gender_heading_line = any(
            (
                normalize_text(row.get("text") or "") in {"Gender Equality", "性别平等"}
                and isinstance(row.get("bbox"), (list, tuple))
                and len(row.get("bbox") or []) >= 4
                and float(row["bbox"][0]) < 180.0
                and float(row["bbox"][1]) < 130.0
            )
            for row in rows
        )
        no_data_legend_ys = [
            float(row["bbox"][1])
            for row in rows
            if normalize_text(row.get("text") or "") in {"No data", "无数据"}
            and isinstance(row.get("bbox"), (list, tuple))
            and len(row.get("bbox") or []) >= 4
        ]
        has_top_map_no_data = any(340.0 <= y <= 365.0 for y in no_data_legend_ys)
        has_middle_map_no_data = any(455.0 <= y <= 480.0 for y in no_data_legend_ys)
        has_bottom_map_no_data = any(645.0 <= y <= 670.0 for y in no_data_legend_ys)
        has_36_context = (
            "Governance for Privacy" in match_text
            or "DATA GOVERNANCE FOR PRIVACY" in match_text
            or "Data Protection and Privacy" in match_text
            or "data protection and privacy legislation" in match_text
            or "数据保护与隐私" in match_text
            or "隐私数据治理" in match_text
        )
        has_37_context = (
            "FAIRNESS AND BIAS" in match_text
            or "Fairness and Bias" in match_text
            or "Bias and Unfair Discrimination" in match_text
            or has_gender_heading_line
            or "Cultural and Linguistic Diversity" in match_text
            or "公平性" in match_text
        )
        if has_36_context:
            if "Governance for Privacy" in match_text or "隐私数据治理" in match_text:
                fixed_textbox(
                    page,
                    page_number,
                    [35.0, 66.0, 370.0, 104.5],
                    "3.6 隐私数据治理",
                    "ai_index_responsible_ai_privacy_data_governance_heading_repair",
                    fontsize=12.6,
                    fill=sampled_background_color(page, fitz.Rect(35.0, 66.0, 370.0, 104.5)),
                    color=(0.13, 0.27, 0.48),
                    source="3.6 Data Governance for Privacy",
                    policy="translate_responsible_ai_privacy_section_heading_without_touching_body",
                )
            if "DATA GOVERNANCE FOR PRIVACY" in match_text:
                fixed_textbox(
                    page,
                    page_number,
                    [196.0, 24.0, 512.0, 39.0],
                    "3.6 隐私数据治理 | 负责任人工智能 | 人工智能指数报告 2026",
                    "ai_index_responsible_ai_privacy_running_header_repair",
                    fontsize=5.0,
                    fill=sampled_background_color(page, fitz.Rect(196.0, 24.0, 512.0, 39.0)),
                    source="3.6 DATA GOVERNANCE FOR PRIVACY",
                    policy="translate_responsible_ai_privacy_running_header_consistently",
                )
            if "Global Index on" in match_text or "全球负责任人工智能指数" in match_text:
                fixed_textbox(
                    page,
                    page_number,
                    [36.0, 91.0, 300.0, 113.8],
                    "全球负责任AI评估得分\n来源：全球负责任AI指数，2024 | 图表：2026年AI Index报告",
                    "ai_index_responsible_ai_privacy_girai_map_title_source_repair",
                    fontsize=5.2,
                    fill=(1, 1, 1),
                    source="Global Index on Responsible AI map title/source",
                    policy="redraw_fragmented_privacy_map_title_source_as_compact_chinese_lines",
                )
            if "Legislation" in match_text or "Draft legislation" in match_text or "No data" in match_text:
                fixed_baseline_rows(
                    page,
                    page_number,
                    [62.0, 618.0, 122.0, 667.0],
                    [
                        (628.5, "已有立法"),
                        (639.8, "立法草案"),
                        (651.1, "无立法"),
                        (662.4, "无数据"),
                    ],
                    "ai_index_responsible_ai_privacy_legislation_legend_repair",
                    fontsize=5.1,
                    x=64.0,
                    source="Legislation / Draft legislation / No legislation / No data",
                    policy="translate_data_protection_map_legends_preserve_map_geometry",
                )
            if has_top_map_no_data:
                fixed_baseline_rows(
                    page,
                    page_number,
                    [67.0, 345.0, 100.0, 360.2],
                    [(356.0, "无数据")],
                    "ai_index_responsible_ai_privacy_girai_no_data_legend_repair",
                    fontsize=5.1,
                    x=70.0,
                    source="No data",
                    policy="translate_small_map_no_data_legend_only",
                )
        if has_37_context:
            if "FAIRNESS AND BIAS" in match_text:
                fixed_textbox(
                    page,
                    page_number,
                    [262.0, 24.0, 512.0, 39.0],
                    "3.7 公平性与偏见 | 负责任人工智能 | 人工智能指数报告 2026",
                    "ai_index_responsible_ai_fairness_running_header_repair",
                    fontsize=5.0,
                    fill=sampled_background_color(page, fitz.Rect(262.0, 24.0, 512.0, 39.0)),
                    source="3.7 FAIRNESS AND BIAS",
                    policy="translate_responsible_ai_fairness_running_header_consistently",
                )
            if "3.7" in match_text and ("Fairness" in match_text or "Bias" in match_text):
                fixed_textbox(
                    page,
                    page_number,
                    [35.0, 60.0, 324.0, 122.0],
                    "3.7 公平性与偏见",
                    "ai_index_responsible_ai_fairness_section_heading_repair",
                    fontsize=12.4,
                    fill=sampled_background_color(page, fitz.Rect(35.0, 60.0, 324.0, 122.0)),
                    color=(0.13, 0.27, 0.48),
                    source="3.7 Fairness and Bias",
                    policy="translate_responsible_ai_fairness_section_heading_without_parenthetical_leftovers",
                )
            if has_gender_heading_line:
                fixed_textbox(
                    page,
                    page_number,
                    [35.0, 80.0, 158.0, 106.0],
                    "性别平等",
                    "ai_index_responsible_ai_gender_equality_heading_repair",
                    fontsize=12.0,
                    fill=sampled_background_color(page, fitz.Rect(35.0, 80.0, 158.0, 106.0)),
                    color=(0.13, 0.27, 0.48),
                    source="Gender Equality",
                    policy="translate_gender_equality_subsection_heading_without_touching_body",
                )
            if has_middle_map_no_data:
                fixed_baseline_rows(
                    page,
                    page_number,
                    [68.0, 460.0, 104.0, 475.8],
                    [(471.0, "无数据")],
                    "ai_index_responsible_ai_fairness_map_no_data_legend_repair",
                    fontsize=5.1,
                    x=71.0,
                    source="No data",
                    policy="translate_small_fairness_map_no_data_legend_only",
                )
            if has_bottom_map_no_data:
                fixed_baseline_rows(
                    page,
                    page_number,
                    [67.0, 648.0, 102.0, 663.8],
                    [(658.6, "无数据")],
                    "ai_index_responsible_ai_bias_map_no_data_legend_repair",
                    fontsize=5.1,
                    x=70.0,
                    source="No data",
                    policy="translate_small_bias_map_no_data_legend_only",
                )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
