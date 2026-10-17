# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai responsible tables：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def _draw_ai_index_responsible_ai_cell(
    page: Any,
    rect: Any,
    text: str,
    *,
    fontsize: float = 5.2,
    fill: tuple[float, float, float] = (0.90, 0.97, 0.99),
    color: tuple[float, float, float] = (0, 0, 0),
) -> float:
    from repair_pdf_drawing import fit_source_han_textbox
    from repair_pdf_nature import _redact_with_fill
    _redact_with_fill(page, rect, fill)
    return fit_source_han_textbox(page, rect, text, fontsize=fontsize, color=color)


def _redraw_ai_index_responsible_ai_headers(fitz: Any, page: Any, y0: float, y1: float) -> None:
    from repair_pdf_drawing import fit_source_han_textbox
    from repair_pdf_nature import _redact_with_fill
    header_fill = (0.02, 0.22, 0.40)
    for bbox, text in [
        ([55.0, y0, 122.0, y1], "维度"),
        ([133.0, y0, 284.0, y1], "定义"),
        ([291.0, y0, 446.0, y1], "示例"),
        ([454.0, y0, 565.0, y1], "参考文献"),
    ]:
        rect = fitz.Rect(bbox)
        _redact_with_fill(page, rect, header_fill)
        fit_source_han_textbox(page, rect + (0, 1.4, 0, 0), text, fontsize=6.1, color=(1, 1, 1))


def repair_ai_index_responsible_ai_dimension_tables(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import normalize_text
    repairs: list[dict[str, Any]] = []
    light_fill = (0.90, 0.97, 0.99)
    table_font = 4.95
    ref_font = 4.75
    label_font = 5.15
    cell_specs_by_page = {
        1: {
            "trigger": ["What AI systems should achieve", "Data stewardship"],
            "headers": [(474.0, 501.0)],
            "cells": [
                ([52.0, 515.0, 125.0, 543.0], "有效性与\n可靠性", label_font),
                ([132.0, 515.0, 284.0, 598.0], "针对特定范围和可接受的性能水平而设计，例如完成任务目标、符合专家知识，或达到有益于个人、组织或系统的准确率阈值，并按设计进行验证与确认。", table_font),
                ([289.0, 515.0, 449.0, 579.0], "团队在上线前设定目标准确率和失败阈值，按这些标准验证系统，并在生产环境中持续监测，确保仍满足设计预期。", table_font),
                ([452.0, 515.0, 565.0, 550.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则", ref_font),
                ([52.0, 604.0, 125.0, 625.0], "隐私", label_font),
                ([132.0, 604.0, 284.0, 660.0], "在AI生命周期（收集、训练、部署、再利用）中，保护个人机密性、匿名性、知情同意以及对个人数据的控制。", table_font),
                ([289.0, 604.0, 449.0, 650.0], "消息应用对会话进行端到端加密，并清楚告知用户能否选择将数据用于训练语言模型。", table_font),
                ([452.0, 604.0, 565.0, 671.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；UNESCO《人工智能伦理建议书》", ref_font),
                ([52.0, 678.0, 125.0, 705.0], "数据治理", label_font),
                ([132.0, 678.0, 284.0, 719.0], "确保数据的质量、来源、完整性以及合法使用和再利用，并配套清晰的访问控制与文档记录。", table_font),
                ([289.0, 678.0, 449.0, 744.0], "物流公司追踪训练路径规划模型所用数据集的血缘，实施基于角色的访问控制，并定期复核数据质量和漂移。", table_font),
                ([452.0, 678.0, 565.0, 724.0], "EU《可信AI伦理指南》；ISO/IEC 42001:2023；OECD AI原则", ref_font),
            ],
        },
        2: {
            "trigger": ["Fairness and bias", "Environmental sustainability", "Factuality and truthfulness"],
            "headers": [],
            "cells": [
                ([52.0, 101.0, 125.0, 123.0], "公平性与\n偏见", label_font),
                ([132.0, 101.0, 284.0, 166.0], "保护公民权利，防止在不同个人或群体之间出现无正当理由的歧视和系统性不利影响，并考虑受保护属性、文化背景和使用场景。", table_font),
                ([289.0, 101.0, 449.0, 174.0], "银行审计信贷评分模型在不同人群中的审批率和错误率差异，记录发现，并在部署前落实偏见缓解措施。", table_font),
                ([452.0, 101.0, 565.0, 166.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；UNESCO《人工智能伦理建议书》", ref_font),
                ([52.0, 183.0, 125.0, 210.0], "透明度与\n可审计性", label_font),
                ([132.0, 183.0, 284.0, 258.0], "向相关利益方清楚披露AI系统的使用、目的、范围和高层运行方式，并使授权方能够检查、重构和验证系统是否按预期开发、训练、配置和运行。", table_font),
                ([289.0, 183.0, 449.0, 258.0], "城市使用AI模型安排巡检优先级时，发布通俗说明，记录模型卡和数据来源，保留训练脚本与日志，并支持内部审计复现关键决策。", table_font),
                ([452.0, 183.0, 565.0, 258.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；UNESCO《人工智能伦理建议书》；ISO/IEC 42001:2023", 4.45),
                ([52.0, 265.0, 125.0, 284.0], "可解释性", label_font),
                ([132.0, 265.0, 284.0, 312.0], "能够为系统输出提供可理解、适合语境的理由，包括影响预测或决策的关键因素。", table_font),
                ([289.0, 265.0, 449.0, 339.0], "AI欺诈检测工具向调查人员显示主要贡献特征和简要理由，同时向商户解释交易被标记的原因及可采取的后续步骤。", table_font),
                ([452.0, 265.0, 565.0, 330.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；UNESCO《人工智能伦理建议书》", ref_font),
                ([52.0, 347.0, 125.0, 374.0], "自主性与\n人类能动性", label_font),
                ([132.0, 347.0, 284.0, 392.0], "保护人们作出知情选择和自由行动的能力，避免AI系统不当操纵、胁迫或替代人的决策。", table_font),
                ([289.0, 347.0, 449.0, 411.0], "健康聊天机器人明确说明自己不是人类，也不能替代专业护理；避免给出会改变人生的指令性建议，并在高风险情境中引导用户寻求专家帮助。", table_font),
                ([452.0, 347.0, 565.0, 403.0], "EU《可信AI伦理指南》；OECD AI原则；UNESCO《人工智能伦理建议书》", ref_font),
                ([52.0, 423.0, 125.0, 451.0], "环境\n可持续性", label_font),
                ([132.0, 423.0, 284.0, 508.0], "限制并管理AI系统全生命周期的环境影响，包括能源使用、碳排放和资源消耗；承诺计量、披露并持续降低影响，同时避免资源滥用。", table_font),
                ([289.0, 423.0, 449.0, 497.0], "公司测量大型训练运行的能源和用水量并对外报告，选择更高效的模型架构，并在电网碳强度较低时安排训练。", table_font),
                ([452.0, 423.0, 565.0, 479.0], "EU《可信AI伦理指南》；OECD AI原则；UNESCO；《欧盟AI法案》能效要求", ref_font),
                ([52.0, 516.0, 125.0, 543.0], "事实性与\n真实性", label_font),
                ([132.0, 516.0, 284.0, 582.0], "AI系统输出的准确性与可靠性，包括模型能否生成事实正确的信息、避免误导性陈述和捏造，并诚实表达不确定性。", table_font),
                ([289.0, 516.0, 449.0, 628.0], "公司系统性地用事实性评测（如SimpleQA）测试大语言模型，随模型发布披露幻觉率，采用检索增强生成将输出锚定在可信来源，并向用户提供置信指标和引用。", table_font),
                ([452.0, 516.0, 565.0, 536.0], "NIST AI RMF", ref_font),
            ],
        },
        3: {
            "trigger_any_groups": [
                ["System Integrity and Risk Controls", "Governance, Accountability, and Enforcement"],
                ["第二层", "第三层", "Security", "Accountability"],
            ],
            "headers": [(124.5, 151.0), (479.0, 505.0)],
            "cells": [
                ([52.0, 165.0, 125.0, 186.0], "安全防护", label_font),
                ([132.0, 165.0, 284.0, 191.0], "确保AI系统能够抵御网络威胁和滥用。", table_font),
                ([289.0, 165.0, 449.0, 220.0], "学校系统用AI提供个性化辅导，并将数据和模型托管在安全服务器中，同时对相关人员开展充分安全培训。", table_font),
                ([452.0, 165.0, 565.0, 211.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；ISO/IEC 42001:2023", ref_font),
                ([52.0, 234.0, 125.0, 255.0], "安全性", label_font),
                ([132.0, 234.0, 284.0, 338.0], "规定正常行为与受影响系统，分析越界条件以刻画风险因素（对人、环境、政治制度、人权等造成的身心或其他风险），并结合治理机制进行风险检测、管理、补救和安全监督。", 4.7),
                ([289.0, 234.0, 449.0, 309.0], "工业控制系统使用异常检测模型，并在模拟攻击和传感器故障下测试，实时监控；当异常超过阈值时，系统回退到人工控制。", table_font),
                ([452.0, 234.0, 565.0, 280.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；ISO/IEC 42001:2023", ref_font),
                ([52.0, 349.0, 125.0, 371.0], "稳健性", label_font),
                ([132.0, 349.0, 284.0, 397.0], "面对分布漂移、外部自然或对抗事件以及组件故障时仍保持稳健，并配套测试、监控和安全回退机制。", table_font),
                ([289.0, 349.0, 449.0, 405.0], "食品连锁企业用由多个模型组成的AI系统预测需求，这些模型会在恶劣天气、演唱会和体育赛事等情况下被触发。", table_font),
                ([452.0, 349.0, 565.0, 394.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；ISO/IEC 42001:2023", ref_font),
                ([52.0, 519.0, 125.0, 548.0], "问责与\n责任承担", label_font),
                ([132.0, 519.0, 284.0, 585.0], "明确AI系统结果的责任归属，包括法律责任、运营负责人、决策权限和升级路径，使损害和失败能够被调查、处理和补救。", table_font),
                ([289.0, 519.0, 449.0, 594.0], "平台为高风险推荐系统指定负责人，定义KPI和损害阈值，记录发布审批权限，并维护事件调查、用户通知和赔偿流程。", table_font),
                ([452.0, 519.0, 565.0, 565.0], "EU《可信AI伦理指南》；NIST AI RMF；OECD AI原则；ISO/IEC 42001:2023", ref_font),
                ([52.0, 613.0, 125.0, 641.0], "人类监督与\n可质疑性", label_font),
                ([132.0, 613.0, 284.0, 679.0], "确保在适当情况下有有意义的人类参与，包括挑战、申诉或推翻AI辅助决策的能力，以及获得有效救济的渠道。", table_font),
                ([289.0, 613.0, 449.0, 678.0], "雇主使用AI筛选工具时，必须由人工复核所有不利决定，向候选人披露AI使用情况，解释关键因素，并提供请求人工复议和纠错的清晰路径。", table_font),
                ([452.0, 613.0, 565.0, 690.0], "《欧盟AI法案》高风险AI人类监督义务；EU《可信AI伦理指南》；OECD AI原则；UNESCO《人工智能伦理建议书》", 4.45),
            ],
            "source_line": ([463.0, 717.0, 575.0, 749.0], "来源：AI Index，2026\n图 3.1.1", 5.2),
        },
    }
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        spec = next(
            (
                candidate
                for candidate in cell_specs_by_page.values()
                if ("trigger" in candidate and all(trigger in page_text for trigger in candidate["trigger"]))
                or any(all(trigger in page_text for trigger in group) for group in candidate.get("trigger_any_groups", []))
            ),
            None,
        )
        if not spec:
            continue
        page_repairs: list[dict[str, Any]] = []
        for header_y0, header_y1 in spec.get("headers", []):
            _redraw_ai_index_responsible_ai_headers(fitz, page, float(header_y0), float(header_y1))
        for bbox, text, fontsize in spec["cells"]:
            rect = fitz.Rect(bbox)
            used = _draw_ai_index_responsible_ai_cell(page, rect, text, fontsize=float(fontsize), fill=light_fill)
            page_repairs.append({"bbox": [round(v, 2) for v in bbox], "target": text[:80], "fontsize": used})
        if spec.get("source_line"):
            bbox, text, fontsize = spec["source_line"]
            rect = fitz.Rect(bbox)
            used = _draw_ai_index_responsible_ai_cell(page, rect, text, fontsize=float(fontsize), fill=(1, 1, 1))
            page_repairs.append({"bbox": [round(v, 2) for v in bbox], "target": text[:80], "fontsize": used})
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_responsible_ai_dimension_table_redraw",
                "source": " / ".join(spec.get("trigger") or spec.get("trigger_any_groups", [[]])[0]),
                "target": "Responsible AI dimension framework table translated as structured Chinese cells",
                "cell_count": len(page_repairs),
                "bbox": [35.0, 80.0 if page_number != 1 else 470.0, 578.0, 748.0],
                "fill_strategy": "cell_text_region_redraw_preserving_table_background_and_grid",
                "font_policy": "source_han_sans_compact_table_text_4_45_to_5_15pt",
                "text_policy": "translate_responsible_ai_dimension_definition_example_labels_preserve_framework_references",
                "backend_sink_down": "pending",
                "cells": page_repairs[:8],
            }
        )
    return repairs


def repair_ai_index_responsible_ai_benchmark_tables(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import fit_source_han_textbox, insert_source_han_sans, normalize_text
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    header_fill = (0.02, 0.44, 0.66)
    table_specs = [
        {
            "trigger": ["MMLU", "GPT-5.2", "AIME 2025"],
            "caption_bbox": [46.0, 78.0, 430.0, 94.0],
            "caption": "热门基础模型报告的通用能力基准\n来源：AI Index | 表：2026年AI Index报告",
            "headers": [
                ([47.0, 103.0, 113.0, 134.0], "能力\n基准", 5.7),
                ([113.0, 103.0, 178.0, 134.0], "GPT-5.2", 5.4),
                ([178.0, 103.0, 243.0, 134.0], "Gemini 3", 5.4),
                ([243.0, 103.0, 308.0, 134.0], "DeepSeek-V3.2", 4.9),
                ([308.0, 103.0, 373.0, 134.0], "Llama 4\nMaverick", 4.8),
                ([373.0, 103.0, 438.0, 134.0], "Grok 4.1", 5.4),
                ([438.0, 103.0, 503.0, 134.0], "Claude Opus\n4.5", 4.9),
                ([503.0, 103.0, 568.0, 134.0], "Mistral 3 Large", 3.8),
            ],
        },
        {
            "trigger": ["StrongREJECT", "WMDP benchmark"],
            "caption_bbox": [46.0, 371.0, 440.0, 389.0],
            "caption": "热门基础模型报告的安全与负责任AI基准\n来源：AI Index | 表：2026年AI Index报告",
            "headers": [
                ([47.0, 397.0, 139.0, 428.0], "RAI\n基准", 5.6),
                ([139.0, 397.0, 201.0, 428.0], "GPT-5.2", 5.4),
                ([201.0, 397.0, 263.0, 428.0], "Gemini 3", 5.4),
                ([263.0, 397.0, 325.0, 428.0], "DeepSeek-V3.2", 4.9),
                ([325.0, 397.0, 387.0, 428.0], "Llama 4\nMaverick", 4.8),
                ([387.0, 397.0, 449.0, 428.0], "Grok 4.1", 5.4),
                ([449.0, 397.0, 510.0, 428.0], "Claude Opus\n4.5", 4.9),
                ([510.0, 397.0, 568.0, 428.0], "Mistral 3 Large", 3.8),
            ],
        },
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        for spec in table_specs:
            if not all(trigger in page_text for trigger in spec["trigger"]):
                continue
            cap_rect = fitz.Rect(spec["caption_bbox"])
            _redact_with_fill(page, cap_rect, (1, 1, 1))
            fit_source_han_textbox(page, cap_rect, spec["caption"], fontsize=4.8, color=(0, 0, 0))
            for bbox, label, fontsize in spec["headers"]:
                rect = fitz.Rect(bbox)
                _redact_with_fill(page, rect, header_fill)
                if label == "Mistral 3 Large":
                    insert_source_han_sans(
                        page,
                        (rect.x0 + 3.0, rect.y0 + 18.0),
                        label,
                        fontsize=float(fontsize),
                        color=(1, 1, 1),
                    )
                else:
                    fit_source_han_textbox(page, rect + (1.0, 1.5, -1.0, -1.0), label, fontsize=float(fontsize), color=(1, 1, 1))
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_benchmark_table_header_redraw",
                    "source": " / ".join(spec["trigger"]),
                    "target": "Responsible AI benchmark table captions and model headers normalized",
                    "bbox": [46.0, spec["caption_bbox"][1], 568.0, spec["headers"][0][0][3]],
                    "fill_strategy": "caption_white_cover_and_blue_header_row_redraw",
                    "font_policy": "source_han_sans_compact_table_header_preserve_model_names",
                    "text_policy": "translate_table_caption_and_first_column_header_keep_model_and_benchmark_names_passthrough",
                }
            )
    return repairs


def repair_ai_index_responsible_ai_organization_view_chart_labels(
    fitz: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    label_map = {
        "Excellent": "优秀",
        "Good": "良好",
        "Satisfactory": "一般",
        "Needs improvement": "需要改进",
        "Insufficient": "不足",
        "Insuǅcient": "不足",
        "Insu·cient": "不足",
        "Unknown": "未知",
        "% of respondents": "受访者占比",
        "Considered relevant": "认为相关",
        "Actively mitigated": "主动缓解",
        "AI risks": "AI风险",
        "Inaccuracy": "不准确性",
        "Cybersecurity": "网络安全",
        "Regulatory compliance": "监管合规",
        "Personal/individual privacy": "个人隐私",
        "IP infringement": "知识产权侵权",
        "Autonomous/unintended": "自主/非预期",
        "system actions": "系统行动",
        "Organizational reputation": "组织声誉",
        "Explainability": "可解释性",
        "Equity and fairness": "公平与公正",
        "Resource misuse": "资源滥用",
        "Workforce labor": "劳动力",
        "displacement": "替代",
        "Environmental impact": "环境影响",
        "National security": "国家安全",
        "Physical safety": "人身安全",
        "Political stability": "政治稳定",
        "Information security": "信息安全",
        "(cyber/fraud/privacy)": "网络/欺诈/隐私",
        "Risk/compliance": "风险/合规",
        "AI-specific governance": "AI专项治理",
        "AI-speciǇc governance": "AI专项治理",
        "roles": "角色",
        "Data and analytics": "数据与分析",
        "Engineering": "工程",
        "Legal": "法务",
        "Internal audit/ethics": "内部审计/伦理",
        "No business function": "无业务职能",
        "primarily responsible": "主要负责",
        "Customer care": "客户服务",
        "Other": "其他",
        "Revenue in USD": "收入（美元）",
        "Improved business operations": "改善业务运营",
        "Increased customer trust": "提升客户信任",
        "Increased user adoption": "提高用户采用率",
        "Improved business outcomes": "改善业务成果",
        "Decrease in number of incidents": "减少事件数量",
        "Enhanced brand reputation": "提升品牌声誉",
        "Faster time-to-market": "缩短上市时间",
        "Slower time-to-market": "延长上市时间",
        "Have not implemented RAI policies": "尚未实施RAI政策",
        "Knowledge and training gaps": "知识与培训缺口",
        "Resource or budget constraints": "资源或预算限制",
        "Regulatory uncertainty": "监管不确定性",
        "Technical limitations": "技术限制",
        "Organizational resistance": "组织阻力",
        "Lack of executive support": "缺乏高管支持",
        "Security and risk concerns": "安全与风险担忧",
        "Gaps in RAI tooling and control": "RAI工具与控制缺口",
        "Unclear or insuǅcient": "商业价值",
        "Unclear or insufficient": "商业价值",
        "business value": "不明或不足",
        "Immature vendor or": "供应商或",
        "ecosystem landscape": "生态不成熟",
        "None": "无",
        "EU General Data Protection": "欧盟通用数据保护",
        "Regulation (GDPR)": "条例（GDPR）",
        "EU AI Act": "欧盟AI法案",
        "ISO/IEC 42001 (AI Management": "ISO/IEC 42001",
        "System Standard)": "AI管理体系标准",
        "NIST AI Risk Management": "NIST AI风险管理",
        "Framework (AI RMF)": "框架（AI RMF）",
        "US Presidential": "美国总统",
        "Executive Order on AI": "AI行政命令",
        "OECD AI Principles": "经合组织AI原则",
        "None of the these/no change": "均无/无变化",
    }
    trigger_needles = (
        "3.3 HOW ORGANIZATIONS AND BUSINESSES VIEW RAI",
        "Percentage of organizations that experienced AI incidents",
        "AI risks: considered relevant",
        "governance primarily responsible",
        "responsible AI policies",
        "Improved business outcomes",
        "Have not implemented RAI policies",
    )
    incident_response_labels = {"Excellent", "Good", "Satisfactory", "Needs improvement", "Insufficient", "Insuǅcient", "Insu·cient", "Unknown"}
    incident_response_short = {
        "Excellent": "优秀",
        "Good": "良好",
        "Satisfactory": "一般",
        "Needs improvement": "需改进",
        "Insufficient": "不足",
        "Insuǅcient": "不足",
        "Insu·cient": "不足",
        "Unknown": "未知",
    }
    incident_occurrence_legend_short = {"Yes": "是", "No": "否", "Unknown": "未知"}
    compact_left_axis_labels = {
        "Knowledge and training gaps",
        "Resource or budget constraints",
        "Regulatory uncertainty",
        "Technical limitations",
        "Organizational resistance",
        "Lack of executive support",
        "Security and risk concerns",
        "Gaps in RAI tooling and control",
        "Unclear or insuǅcient",
        "Unclear or insufficient",
        "business value",
        "Immature vendor or",
        "ecosystem landscape",
        "None",
        "EU General Data Protection",
        "Regulation (GDPR)",
        "EU AI Act",
        "ISO/IEC 42001 (AI Management",
        "System Standard)",
        "NIST AI Risk Management",
        "Framework (AI RMF)",
        "US Presidential",
        "Executive Order on AI",
        "OECD AI Principles",
        "None of the these/no change",
    }
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if not any(needle in page_text for needle in trigger_needles) and not any(label in page_text for label in label_map):
            continue
        for row in page_lines(page):
            source = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if not source or not bbox:
                continue
            target = label_map.get(source)
            rect = None
            if target is None and 515.0 <= bbox[1] <= 540.0 and ("OECD" in source or "经合组织" in source):
                target = "经合组织AI原则"
                source = "OECD AI Principles"
                rect = fitz.Rect(88.5, 520.3, 156.5, 537.5)
            if target is None and source in incident_occurrence_legend_short:
                probe_rect = expanded_rect(fitz, bbox, page, pad=0.35, min_width=16.0)
                if probe_rect and 80.0 <= probe_rect.x0 <= 180.0 and 340.0 <= probe_rect.y0 <= 360.0:
                    target = incident_occurrence_legend_short[source]
                    rect = probe_rect
            if target is None:
                continue
            if rect is None:
                rect = expanded_rect(fitz, bbox, page, pad=0.35, min_width=max(16.0, len(target) * 5.0))
            if not rect:
                continue
            if not (40.0 <= rect.y0 <= 700.0):
                continue
            if source in compact_left_axis_labels and rect.x1 <= 170.0 and 80.0 <= rect.y0 <= 690.0:
                slot_x0 = max(34.0, rect.x0 - 1.0)
                slot_x1 = min(154.0, max(rect.x1 + 3.0, rect.x0 + len(target) * 5.4 + 3.0))
                if slot_x1 <= slot_x0 + 12.0:
                    slot_x1 = min(154.0, slot_x0 + 18.0)
                slot = fitz.Rect(slot_x0, rect.y0 - 0.8, slot_x1, rect.y1 + 0.8)
                fill = (1.0, 1.0, 1.0)
                _redact_with_fill(page, slot, fill)
                baseline = row.get("origin_y")
                if not isinstance(baseline, (int, float)):
                    baseline = rect.y1 - 1.6
                insert_source_han_sans(page, (slot.x0 + 0.8, float(baseline)), target, fontsize=5.1, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_responsible_ai_compact_left_axis_label_baseline_repair",
                        "source": source,
                        "target": target,
                        "bbox": [round(v, 2) for v in [slot.x0, slot.y0, slot.x1, slot.y1]],
                        "fontsize": 5.1,
                        "fill_strategy": "white_chart_background_baseline_redraw_for_compact_left_axis_labels",
                        "font_policy": "source_han_sans_baseline_draw_for_dense_mckinsey_chart_categories",
                        "text_policy": "translate_responsible_ai_mckinsey_axis_categories_preserve_values_and_series",
                    }
                )
                continue
            if source in incident_occurrence_legend_short and 80.0 <= rect.x0 <= 180.0 and 340.0 <= rect.y0 <= 360.0:
                fill = sampled_background_color(page, rect)
                _redact_with_fill(page, rect, fill)
                baseline = row.get("origin_y")
                if not isinstance(baseline, (int, float)):
                    baseline = rect.y1 - 1.6
                insert_source_han_sans(page, (rect.x0 + 0.8, float(baseline)), target, fontsize=5.2, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_responsible_ai_incident_occurrence_legend_baseline_repair",
                        "source": source,
                        "target": target,
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 5.2,
                        "fill_strategy": "sampled_background_baseline_redraw_for_short_legend_labels",
                        "font_policy": "source_han_sans_baseline_draw_for_short_chart_legend",
                        "text_policy": "translate_yes_no_unknown_legend_only_in_incident_occurrence_chart_slot",
                    }
                )
                continue
            if source in incident_response_labels and rect.x0 >= 300.0 and 490.0 <= rect.y0 <= 660.0:
                slot = fitz.Rect(309.5, rect.y0 - 0.8, 382.5, rect.y1 + 0.8)
                fill = sampled_background_color(page, slot)
                _redact_with_fill(page, slot, fill)
                baseline = row.get("origin_y")
                if not isinstance(baseline, (int, float)):
                    baseline = rect.y1 - 1.6
                insert_source_han_sans(page, (slot.x0 + 1.2, float(baseline)), incident_response_short[source], fontsize=5.2, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_responsible_ai_incident_response_label_baseline_repair",
                        "source": source,
                        "target": incident_response_short[source],
                        "bbox": [round(v, 2) for v in [slot.x0, slot.y0, slot.x1, slot.y1]],
                        "fontsize": 5.2,
                        "fill_strategy": "sampled_background_baseline_redraw_for_tiny_horizontal_labels",
                        "font_policy": "source_han_sans_baseline_draw_for_sub_8pt_chart_labels",
                        "text_policy": "translate_mckinsey_incident_response_rating_labels_without_axis_overlap",
                    }
                )
                continue
            rect.x0 = max(24.0, rect.x0)
            rect.x1 = min(page.rect.width - 24.0, max(rect.x1, rect.x0 + len(target) * 5.3 + 3.0))
            meta = replace_rect_source_han(page, rect, target, fontsize=5.2)
            meta.update(
                {
                    "font_policy": "source_han_sans_compact_chart_category_labels",
                    "text_policy": "translate_mckinsey_responsible_ai_organization_view_chart_categories_preserve_values",
                }
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_responsible_ai_organization_view_chart_label_repair",
                    "source": source,
                    "target": target,
                    **meta,
                }
            )
    return repairs


def repair_ai_index_responsible_ai_academia_chart_labels(
    fitz: Any,
    doc: Any,
    *,
    pages: set[int] | None = None,
) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    label_map = {
        "Privacy and data governance": "隐私与数据治理",
        "Fairness and bias": "公平性与偏见",
        "Transparency and explainability": "透明度与可解释性",
        "Security and safety": "安全防护与安全性",
    }
    axis_map = {
        "Number of RAI papers": "RAI论文数量",
        "RAI papers (% of total)": "RAI论文占比（%）",
    }
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if not (
            "RAI in Academia" in page_text
            or "Publication Volume" in page_text
            or "Privacy and data governance" in page_text
            or "Number of RAI papers" in page_text
        ):
            continue
        for row in page_lines(page):
            source = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if not source or not bbox:
                continue
            if source in label_map:
                rect = expanded_rect(fitz, bbox, page, pad=0.35, min_width=48.0)
                if not rect:
                    continue
                fill = sampled_background_color(page, rect)
                _redact_with_fill(page, rect, fill)
                baseline = row.get("origin_y")
                if not isinstance(baseline, (int, float)):
                    baseline = rect.y1 - 1.6
                insert_source_han_sans(page, (rect.x0 + 0.8, float(baseline)), label_map[source], fontsize=4.9, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_responsible_ai_academia_legend_label_repair",
                        "source": source,
                        "target": label_map[source],
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 4.9,
                        "fill_strategy": "sampled_background_baseline_redraw_for_academia_legend_labels",
                        "font_policy": "source_han_sans_compact_legend_label",
                        "text_policy": "translate_responsible_ai_academia_subtopic_legend_preserve_series_colors",
                    }
                )
                continue
            if source in axis_map:
                rect = expanded_rect(fitz, bbox, page, pad=0.25, min_width=1.0)
                if not rect:
                    continue
                meta = replace_rect_source_han(page, rect, axis_map[source], fontsize=5.3, rotate=90, fill=(1, 1, 1))
                meta.update(
                    {
                        "font_policy": "source_han_sans_rotated_axis_label",
                        "text_policy": "translate_responsible_ai_academia_axis_labels_preserve_numeric_ticks",
                    }
                )
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_responsible_ai_academia_axis_label_repair",
                        "source": source,
                        "target": axis_map[source],
                        **meta,
                    }
                )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
