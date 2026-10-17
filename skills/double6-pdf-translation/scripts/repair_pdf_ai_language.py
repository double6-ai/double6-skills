# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai language：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_language_section_visible_residue(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_ai_links import draw_text_run
    from repair_pdf_drawing import cjk_text_width, expanded_rect, fit_source_han_textbox, fit_textbox, insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    heading_specs = {
        "Understanding": ("理解能力", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "Generation": ("生成能力", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "General Reasoning": ("通用推理", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "Arena Leaderboard": ("Arena 排行榜", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "MMLU-Pro: overall accuracy": ("MMLU-Pro：总体准确率", 8.8, (0, 0, 0), "chart_title"),
        "Text Arena: Elo rating": ("Text Arena：Elo评分", 8.4, (0, 0, 0), "chart_title"),
        "MTEB (English v2): average score": ("MTEB（英语 v2）：平均得分", 8.0, (0, 0, 0), "chart_title"),
        "Average task score": ("平均任务得分", 6.2, (0, 0, 0), "axis_label"),
        "HIGHLIGHT:": ("亮点：", 7.2, (0, 0, 0), "chart_title"),
        "The Gap Between Long Context Windows and Deep Understanding": ("长上下文窗口与深度理解之间的差距", 9.4, (0.43, 0.13, 0.48), "section_heading"),
        "SWE-bench: percent solved": ("SWE-bench：解题百分比", 8.0, (0, 0, 0), "chart_title"),
        "Percent solved": ("解题百分比", 6.2, (0, 0, 0), "axis_label"),
        "Terminal-Bench 2.0: accuracy": ("Terminal-Bench 2.0：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Source: Terminal-Bench 2.0 Leaderboard": ("来源：Terminal-Bench 2.0排行榜，2026", 5.0, (0, 0, 0), "chart_title"),
        "| Chart: 2026 AI Index report": ("图表：2026年人工智能指数报告", 5.0, (0, 0, 0), "chart_title"),
        "Vibe Code Bench v1.1: accuracy": ("Vibe Code Bench v1.1：准确率", 8.0, (0, 0, 0), "chart_title"),
        "FrontierMath Tier 4: pass@1 accuracy": ("T4", 6.6, (0, 0, 0), "chart_title"),
        "Pass@1 accuracy": ("Pass@1准确率", 6.2, (0, 0, 0), "axis_label"),
        "Source: Epoch AI, 2026 | Chart: 2026 AI Index report": ("来源：Epoch AI，2026 | 图表：2026年人工智能指数报告", 5.0, (0, 0, 0), "chart_title"),
        "MathArena: accuracy": ("MathArena：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Source: MathArena Leaderboard, 2026 | Chart: 2026 AI Index report": ("来源：MathArena Leaderboard，2026 | 图表：2026年人工智能指数报告", 5.0, (0, 0, 0), "chart_title"),
        "Mathematics": ("数学", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "Theorem Proving": ("定理证明", 13.0, (0.43, 0.13, 0.48), "section_heading"),
        "Finance": ("金融", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "TaxEval v2: accuracy": ("TaxEval v2：准确率", 8.0, (0, 0, 0), "chart_title"),
        "MortgageTax: accuracy": ("MortgageTax：准确率", 8.0, (0, 0, 0), "chart_title"),
        "CorpFin v2: accuracy": ("CorpFin v2：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Finance Agent v1.1: accuracy": ("Finance Agent v1.1：准确率", 8.0, (0, 0, 0), "chart_title"),
        "LegalBench: accuracy": ("LegalBench：准确率", 8.0, (0, 0, 0), "chart_title"),
        "GAIA: accuracy": ("GAIA：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Law": ("法律", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "OSWorld: accuracy": ("OSWorld：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Success rate": ("成功率", 6.2, (0, 0, 0), "axis_label"),
        "Robotics": ("机器人技术", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "Humanoid Robotics": ("人形机器人", 12.5, (0.43, 0.13, 0.48), "section_heading"),
        "Self-Driving Cars": ("自动驾驶汽车", 15.0, (0.43, 0.13, 0.48), "section_heading"),
        "Deployment": ("部署", 13.0, (0.43, 0.13, 0.48), "section_heading"),
        "Technical Innovations and New Benchmarks": ("技术创新与新基准", 12.0, (0.43, 0.13, 0.48), "section_heading"),
        "Safety": ("安全性", 13.0, (0.43, 0.13, 0.48), "section_heading"),
        "Number of weekly paid trips (in thousands)": ("每周付费行程数（千次）", 5.8, (0, 0, 0), "axis_label"),
        "Number of trips": ("行程数", 6.0, (0, 0, 0), "axis_label"),
        "Release year": ("发布年份", 6.2, (0, 0, 0), "axis_label"),
        "Amount of driving data in hours": ("驾驶数据时长（小时）", 5.6, (0, 0, 0), "axis_label"),
        "Number of ADS incidents": ("ADS事故数量", 5.8, (0, 0, 0), "axis_label"),
        "| Chart: 2026 AI Index report": ("图表：2026年人工智能指数报告", 5.0, (0, 0, 0), "chart_title"),
        "AI Incidents": ("AI 事件", 8.4, (1, 1, 1), "toc_label"),
        "Number of AI incidents": ("AI事件数量", 5.8, (0, 0, 0), "axis_label"),
        "Number of reported AI incidents, 2012–25": ("2012-2025年报告的AI事件数量", 6.2, (0, 0, 0), "chart_title"),
        "Examples": ("示例", 8.4, (1, 1, 1), "toc_label"),
        "RAI Benchmarks": ("RAI 基准", 8.4, (1, 1, 1), "toc_label"),
        "Factuality and Truthfulness": ("事实性与真实性", 8.4, (1, 1, 1), "toc_label"),
        "Hughes Hallucination": ("Hughes 幻觉", 8.4, (1, 1, 1), "toc_label"),
        "Evaluation Model (HHEM)": ("评估模型（HHEM）", 8.4, (1, 1, 1), "toc_label"),
        "Leaderboard": ("排行榜", 8.4, (1, 1, 1), "toc_label"),
        "AI Companions": ("AI 伴侣", 8.4, (1, 1, 1), "toc_label"),
        "Businesses View RAI": ("企业如何看待 RAI", 8.4, (1, 1, 1), "toc_label"),
        "Responsible AI Maturity": ("负责任AI成熟度", 8.4, (1, 1, 1), "toc_label"),
        "Efforts": ("投入举措", 8.4, (1, 1, 1), "toc_label"),
        "AI Governance and Investment": ("AI治理与投资", 8.4, (1, 1, 1), "toc_label"),
        "Benefits": ("收益", 8.4, (1, 1, 1), "toc_label"),
        "Regulatory Influence": ("监管影响", 8.4, (1, 1, 1), "toc_label"),
        "3.6 数据 Governance for Privacy 数据": ("3.6 隐私数据治理", 8.4, (1, 1, 1), "toc_label"),
        "Protection and Privacy": ("数据保护与隐私", 8.4, (1, 1, 1), "toc_label"),
        "Bias and Unfair Discrimination": ("偏见与不公平歧视", 8.4, (1, 1, 1), "toc_label"),
        "Gender Equality": ("性别平等", 8.4, (1, 1, 1), "toc_label"),
        "Cultural and Linguistic Diversity": ("文化与语言多样性", 8.4, (1, 1, 1), "toc_label"),
        "Foundation Model": ("基础模型", 8.4, (1, 1, 1), "toc_label"),
        "Transparency Index": ("透明度指数", 8.4, (1, 1, 1), "toc_label"),
        "Company": ("公司", 6.2, (1, 1, 1), "table_header"),
        "Country": ("国家", 6.2, (1, 1, 1), "table_header"),
        "Platform": ("平台", 6.2, (1, 1, 1), "table_header"),
        "Focus": ("重点", 6.2, (1, 1, 1), "table_header"),
        "Notable detail": ("重要细节", 6.2, (1, 1, 1), "table_header"),
        "Q score": ("Q得分", 6.2, (0, 0, 0), "chart_label"),
        "Full task success rate": ("任务完全成功率", 6.2, (0, 0, 0), "chart_label"),
        "Commercial pilots": ("商业试点", 5.8, (0, 0, 0), "table_cell"),
        "advanced perception": ("高级感知", 5.8, (0, 0, 0), "table_cell"),
        "Industrial": ("工业", 5.8, (0, 0, 0), "table_cell"),
        "industrial": ("工业", 5.8, (0, 0, 0), "table_cell"),
        "swapping": ("换电", 5.8, (0, 0, 0), "table_cell"),
        "Medical, service,": ("医疗、服务、", 5.5, (0, 0, 0), "table_cell"),
        "Camera-only vision and LLM interaction": ("纯视觉与LLM交互", 5.2, (0, 0, 0), "table_cell"),
        "Humanoid platforms": ("人形机器人平台", 5.5, (0, 0, 0), "table_cell"),
        "form factors": ("形态设计", 5.8, (0, 0, 0), "table_cell"),
        "human collaboration": ("人机协作", 5.8, (0, 0, 0), "table_cell"),
        "In development": ("开发中", 5.8, (0, 0, 0), "table_cell"),
        "Manipulation": ("操控", 5.8, (0, 0, 0), "table_cell"),
        "Expanding from mobile robotics toward": ("从移动机器人扩展到", 5.2, (0, 0, 0), "table_cell"),
        "humanoid manipulation": ("人形操控", 5.2, (0, 0, 0), "table_cell"),
        "Warehouse": ("仓储", 5.8, (0, 0, 0), "table_cell"),
        "commands": ("指令控制", 5.8, (0, 0, 0), "table_cell"),
        "Teleoperated systems": ("遥操作系统", 5.5, (0, 0, 0), "table_cell"),
        "Focus on teleoperated manipulation": ("聚焦遥操作操控", 5.2, (0, 0, 0), "table_cell"),
        "Robotics platforms": ("机器人平台", 5.5, (0, 0, 0), "table_cell"),
        "General purpose": ("通用", 5.8, (0, 0, 0), "table_cell"),
        "Continuing humanoid and manipulation": ("持续开展人形与操控", 5.2, (0, 0, 0), "table_cell"),
        "research": ("研究", 5.8, (0, 0, 0), "table_cell"),
        "Teleoperated manipulation systems": ("遥操作操控系统", 5.2, (0, 0, 0), "table_cell"),
        "Teleoperated manipulation for retail": ("面向零售的遥操作操控", 5.2, (0, 0, 0), "table_cell"),
        "environments": ("环境", 5.8, (0, 0, 0), "table_cell"),
        "Norway": ("挪威", 5.8, (0, 0, 0), "table_cell"),
        "Home": ("家庭", 5.8, (0, 0, 0), "table_cell"),
        "Workplace": ("工作场所", 5.8, (0, 0, 0), "table_cell"),
        "Industrial cobot (collaborative robot)": ("工业协作机器人组件", 5.0, (0, 0, 0), "table_cell"),
        "components adapted for humanoid": ("适配人形应用", 5.0, (0, 0, 0), "table_cell"),
        "applications": ("应用", 5.8, (0, 0, 0), "table_cell"),
        "Various": ("多种", 5.8, (0, 0, 0), "table_cell"),
        "Leveraging cobot components for": ("借助协作机器人组件", 5.0, (0, 0, 0), "table_cell"),
        "humanoidlike applications": ("实现类人应用", 5.0, (0, 0, 0), "table_cell"),
        "UAE": ("阿联酋", 5.8, (0, 0, 0), "table_cell"),
        "Testbed": ("测试平台", 5.8, (0, 0, 0), "table_cell"),
        "Embodied AI research": ("具身AI研究", 5.5, (0, 0, 0), "table_cell"),
        "models": ("模型", 5.8, (0, 0, 0), "table_cell"),
        "Social interaction,": ("社交互动、", 5.5, (0, 0, 0), "table_cell"),
        "Lifelike facial expressions for customer": ("面向客户互动的仿真表情", 5.0, (0, 0, 0), "table_cell"),
        "engagement": ("互动", 5.8, (0, 0, 0), "table_cell"),
        "underway": ("进行中", 5.8, (0, 0, 0), "table_cell"),
        "30,000+ vehicles": ("30000+辆车", 5.8, (0, 0, 0), "table_cell"),
        "Internal logistics": ("内部物流", 5.5, (0, 0, 0), "table_cell"),
        "Research": ("研究", 5.8, (0, 0, 0), "table_cell"),
        "Testbed for advanced locomotion and": ("高级运动与操控测试平台", 5.0, (0, 0, 0), "table_cell"),
        "manipulation": ("操控", 5.8, (0, 0, 0), "table_cell"),
        "Safety-rated operation around people": ("面向人员环境的安全运行", 5.0, (0, 0, 0), "table_cell"),
        "Foundation model": ("基础模型", 5.5, (0, 0, 0), "table_cell"),
        "stack": ("栈", 5.8, (0, 0, 0), "table_cell"),
        "Multi-embodiment": ("多具身形态", 5.5, (0, 0, 0), "table_cell"),
        "across multiple robot bodies": ("跨多种机器人本体", 5.2, (0, 0, 0), "table_cell"),
        "Source: Vals.": ("来源：Vals.ai，2026", 5.0, (0, 0, 0), "chart_title"),
        "Source: Vals.ai, 2026 | Chart: 2026 AI Index report": ("来源：Vals.ai，2026 | 图表：2026年人工智能指数报告", 5.0, (0, 0, 0), "chart_title"),
        "MVBench: average accuracy": ("MVBench：平均准确率", 8.0, (0, 0, 0), "chart_title"),
        "Average accuracy": ("平均准确率", 6.2, (0, 0, 0), "axis_label"),
        "Source: MVBench Lea er oar": ("来源：MVBench Leaderboard，2026 | 图表：2026年人工智能指数报告", 5.6, (0, 0, 0), "chart_title"),
        "Video-MMMU: overall accuracy": ("Video-MMMU：总体准确率", 8.0, (0, 0, 0), "chart_title"),
        "Vision Arena: Elo rating": ("Vision Arena：Elo评分", 8.0, (0, 0, 0), "chart_title"),
        "Video-Bench video quality": ("Video-Bench 视频质量", 8.0, (0, 0, 0), "chart_title"),
        "Imaging quality": ("成像质量", 5.6, (0, 0, 0), "chart_label"),
        "Aesthetic quality": ("审美质量", 5.6, (0, 0, 0), "chart_label"),
        "Temporal consistency": ("时间一致性", 5.6, (0, 0, 0), "chart_label"),
        "Motion effects": ("运动效果", 5.6, (0, 0, 0), "chart_label"),
        "Motion eǄects": ("运动效果", 5.6, (0, 0, 0), "chart_label"),
        "Motion e·ects": ("运动效果", 5.6, (0, 0, 0), "chart_label"),
        "Score↑": ("得分↑", 6.0, (0, 0, 0), "axis_label"),
        "Score·": ("得分↑", 6.0, (0, 0, 0), "axis_label"),
        "Score": ("得分", 6.0, (0, 0, 0), "axis_label"),
        "VBench-2.0: total score": ("VBench-2.0：总分", 8.0, (0, 0, 0), "chart_title"),
        "Total score": ("总分", 6.2, (0, 0, 0), "axis_label"),
        "Progress in Video Generation": ("视频生成的进展", 9.0, (0.43, 0.13, 0.48), "section_heading"),
        "Accuracy": ("准确率", 6.2, (0, 0, 0), "axis_label"),
        "Accuracy ↑": ("准确率↑", 6.2, (0, 0, 0), "axis_label"),
        "Accuracy ·": ("准确率↑", 6.2, (0, 0, 0), "axis_label"),
        "Mean accuracy": ("平均准确率", 6.2, (0, 0, 0), "axis_label"),
        "ClockQA: exact match": ("ClockQA：精确匹配", 8.0, (0, 0, 0), "chart_title"),
        "CalendarQA: accuracy": ("CalendarQA：准确率", 8.0, (0, 0, 0), "chart_title"),
        "ClockBench: accuracy": ("ClockBench：准确率", 8.0, (0, 0, 0), "chart_title"),
        "Source: ClockBench Leaderboard": ("来源：ClockBench Leaderboard", 5.0, (0, 0, 0), "chart_title"),
        "18 Data source: https://clockbench.ai.": ("18 数据来源：https://clockbench.ai.", 5.0, (0, 0, 0), "chart_title"),
        "17 Data source: https://lastexam.ai.": ("17 数据来源：https://lastexam.ai.", 5.0, (0, 0, 0), "chart_title"),
        "Overall accuracy": ("总体准确率", 6.2, (0, 0, 0), "axis_label"),
        "Elo rating": ("Elo评分", 6.2, (0, 0, 0), "axis_label"),
        "Hallucination rate ↓": ("幻觉率↓", 6.0, (0, 0, 0), "axis_label"),
        "Hallucination rate ·": ("幻觉率↓", 6.0, (0, 0, 0), "axis_label"),
        "Model": ("模型", 6.2, (0, 0, 0), "axis_label"),
    }
    body_specs = [
        {
            "needle": "As of early 2026, top model performance on MMLU-Pro",
            "bbox": [34.0, 643.0, 578.0, 730.0],
            "fontsize": 7.15,
            "target": (
                "截至2026年初，MMLU-Pro 上头部模型表现高度集中，排名前15的模型得分均超过87%（图2.2.1）。"
                "Google 的 Gemini-3.1-Pro 以91.2%领先，其次是 Gemini-3-Pro (Thinking) 的90.1% 和 GPT-o1 的89.3%。"
                "采用思维策略的模型通常排名更靠前，表现优于分布在87%-88%区间的标准版本。第一名与第15名之间的差距略高于"
                "4个百分点，说明前沿模型在广泛知识任务上的竞争已非常接近；这种紧密聚集也与第2.1节描述的趋同模式一致。"
            ),
        },
        {
            "needle": "The user-centered approach does have limitations",
            "bbox": [34.0, 628.0, 578.0, 732.0],
            "fontsize": 7.15,
            "target": (
                "这种以用户为中心的方法也存在局限：偏好并不一定等同于正确性，也未必能充分代表模型的实际使用场景或上下文。"
                "Singh 等人（2025）指出，排序偏差、长度偏差或风格偏好等因素可能影响结果，但它们并不一定与输出准确性相关。"
                "因此，如前所述，Arena 这类评测更适合作为补充视角，而不是模型质量的绝对分数。\n"
                "截至2026年初，Text Arena 上各模型评分仍高度集中，排名前15的模型之间差距很小。"
            ),
        },
        {
            "needle": "FrontierMath是由 Epoch AI 推出",
            "bbox": [34.0, 202.0, 326.0, 286.0],
            "fontsize": 6.85,
            "target": (
                "FrontierMath 是 Epoch AI 推出的高难数学基准。"
                "\n它包含数百道原创难题，考察真实数学推理而非模式识别。"
            ),
        },
        {
            "needle": "Physical Intelligence团队在π年发表",
            "bbox": [34.0, 331.0, 578.0, 380.0],
            "fontsize": 7.0,
            "target": (
                "Physical Intelligence 的 π0（2024）和 π0.6（2025）展示了这种路径：无需针对具体任务重新训练，"
                "机器人也能在不同平台上完成叠衣服等任务。\n"
                "英伟达的 GR00T 模型和 Gemini Robotics 也采取类似方向，训练单一模型来控制不同机器人、完成不同任务。"
            ),
        },
    ]
    fixed_region_specs = [
        {
            "needles": ["17 Data source: https://lastexam.ai.", "ARC-AGI-2"],
            "bbox": [366.0, 508.0, 540.0, 525.5],
            "target": "来源：Center for AI Safety，2026 | 图表：2026年人工智能指数报告",
            "fontsize": 4.2,
            "rule": "ai_index_reasoning_hle_chart_source_line_repair",
        },
        {
            "needles": ["TaxEval v2: accuracy", "Source: Vals.人工智"],
            "bbox": [36.0, 404.8, 260.0, 423.8],
            "target": "来源：Vals.ai，2026 | 图表：2026年人工智能指数报告",
            "fontsize": 4.4,
            "rule": "ai_index_finance_taxeval_fragmented_source_line_repair",
        },
        {
            "needles": ["CaseLaw v2：准确性来源：Vals.ai"],
            "bbox": [36.0, 406.0, 244.0, 432.0],
            "target": "CaseLaw v2：准确率\n来源：Vals.ai，2026 | 图表：2026年人工智能指数报告",
            "fontsize": 5.0,
            "rule": "ai_index_law_caselaw_title_source_line_repair",
        },
        {
            "needles": ["WebArena：成功率来源：WebArena排行榜"],
            "bbox": [44.0, 88.0, 270.0, 123.0],
            "target": "WebArena：成功率\n来源: WebArena排行榜, 2026",
            "fontsize": 5.0,
            "rule": "ai_index_agents_webarena_title_source_line_repair",
        },
        {
            "needles": ["MLE-bench：成功率来源：MLE-bench排行榜"],
            "bbox": [303.0, 416.0, 530.0, 446.0],
            "target": "MLE-bench：成功率\n来源: MLE-bench排行榜, 2026",
            "fontsize": 5.0,
            "rule": "ai_index_agents_mlebench_title_source_line_repair",
        },
        {
            "needles": ["docs.谷歌.com", "source: https://github.com/openai/mle-bench."],
            "bbox": [34.0, 728.0, 580.0, 756.0],
            "target": (
                "35 数据来源: https://docs.google.com/spreadsheets/d/1M801lEpBbKSNwP-vDBkC_pF7LdyGU1f_ufZb_NWNBZQ/edit?gid=0#gid=0.\n"
                "36 数据来源: https://github.com/openai/mle-bench."
            ),
            "fontsize": 4.4,
            "rule": "ai_index_agents_mlebench_footnote_url_protected_repair",
        },
        {
            "needles": ["Cybench：无引导条件下的问题解决率%来"],
            "bbox": [300.0, 95.0, 515.0, 135.0],
            "target": "Cybench：无引导解题率\n来源: Cybench排行榜, 2026",
            "fontsize": 5.0,
            "rule": "ai_index_agents_cybench_title_source_line_repair",
        },
        {
            "needles": ["τ基准测试：pass", "来源：τ-基准测试排行榜"],
            "bbox": [303.0, 422.0, 500.0, 450.0],
            "target": "τ-bench：pass@1\n来源: τ-bench排行榜, 2026",
            "fontsize": 5.0,
            "rule": "ai_index_agents_taubench_title_source_line_repair",
        },
        {
            "needles": ["RLBench：成功率（涵盖18项任务", "| Chart: 2026 AI Index report"],
            "bbox": [38.0, 396.0, 300.0, 424.0],
            "target": "RLBench：成功率（18项任务，每项100个示范）\n图表: 2026 AI Index报告",
            "fontsize": 5.0,
            "rule": "ai_index_robotics_rlbench_title_source_line_repair",
        },
        {
            "needles": ["2023年至2025年间,Waymo自动驾驶车辆", "| Chart: 2026 AI Index report"],
            "bbox": [35.0, 397.0, 292.0, 421.0],
            "target": "2023-2025年 Waymo 加州自动驾驶付费行程\n来源: CPUC, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 4.8,
            "rule": "ai_index_autonomous_waymo_trips_title_source_repair",
        },
        {
            "needles": ["2022年至2025年间 Apollo Go自动驾驶", "车辆的运营情况来源:百度"],
            "bbox": [44.0, 422.0, 238.0, 464.0],
            "target": "2022-2025年 Apollo Go 自动驾驶车辆运营情况\n来源: 百度, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 4.9,
            "rule": "ai_index_autonomous_apollo_title_source_repair",
        },
        {
            "needles": ["2022年至2025年间每月报告的自动驾驶系", "统事故情况数据来源:NHTSA"],
            "bbox": [36.0, 176.0, 244.0, 219.0],
            "target": "2022-2025年每月报告的自动驾驶系统事故\n来源: NHTSA, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 4.8,
            "rule": "ai_index_autonomous_monthly_ads_incidents_title_source_repair",
        },
        {
            "needles": ["2022至2025年间部分公司每月报告的自动驾驶车辆事故情", "况数据来源:NHTSA"],
            "bbox": [37.0, 476.0, 306.0, 508.0],
            "target": "2022-2025年部分公司每月报告的自动驾驶车辆事故\n来源: NHTSA, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 4.8,
            "rule": "ai_index_autonomous_company_ads_incidents_title_source_repair",
        },
        {
            "needles": ["按类型分类的各类伤亡事故统计", "ource: W"],
            "bbox": [38.0, 99.0, 342.0, 124.0],
            "target": "按类型分类的伤亡报告事件：Waymo 与同里程/区域基准对比\n来源: Waymo, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 5.1,
            "rule": "ai_index_waymo_injury_chart_title_source_repair",
        },
        {
            "needles": ["All others", "Cyclist", "V2V lateral", "Number of incidents"],
            "bbox": [54.0, 133.0, 115.5, 346.5],
            "target": "waymo_top_category_labels",
            "fontsize": 4.8,
            "rule": "ai_index_waymo_injury_category_labels_repair",
        },
        {
            "needles": ["All others", "Cyclist", "V2V lateral", "Number of incidents"],
            "bbox": [428.0, 314.0, 535.0, 337.0],
            "target": "仅 Waymo 乘客\n人类驾驶基准均值",
            "fontsize": 4.8,
            "rule": "ai_index_waymo_injury_legend_repair",
        },
        {
            "needles": ["All others", "Cyclist", "V2V lateral", "Number of incidents"],
            "bbox": [288.0, 362.5, 360.0, 373.0],
            "target": "事故数量",
            "fontsize": 5.0,
            "rule": "ai_index_waymo_injury_x_axis_repair",
        },
        {
            "needles": ["All others", "Cyclist", "V2V lateral", "Incident type"],
            "bbox": [39.0, 217.0, 50.0, 264.0],
            "target": "事故类型",
            "fontsize": 5.0,
            "rule": "ai_index_waymo_injury_y_axis_repair",
        },
        {
            "needles": ["按类型分类的安全气囊触发事件统计", "Incident type"],
            "bbox": [38.0, 420.0, 280.0, 455.0],
            "target": "按类型分类的安全气囊触发报告事件\n来源: Waymo, 2025 | 图表: 2026 AI Index报告",
            "fontsize": 5.1,
            "rule": "ai_index_waymo_airbag_chart_title_source_repair",
        },
        {
            "needles": ["按类型分类的安全气囊触发事件统计", "All others", "V2V lateral", "Incident type"],
            "bbox": [54.0, 464.0, 115.5, 659.5],
            "target": "waymo_bottom_category_labels",
            "fontsize": 4.8,
            "rule": "ai_index_waymo_airbag_category_labels_repair",
        },
        {
            "needles": ["按类型分类的安全气囊触发事件统计", "Waymo rider only", "Avg. human-driven benchmark"],
            "bbox": [428.0, 636.0, 535.0, 659.0],
            "target": "仅 Waymo 乘客\n人类驾驶基准均值",
            "fontsize": 4.8,
            "rule": "ai_index_waymo_airbag_legend_repair",
        },
        {
            "needles": ["按类型分类的安全气囊触发事件统计", "Number of incidents"],
            "bbox": [288.0, 683.5, 360.0, 694.5],
            "target": "事故数量",
            "fontsize": 5.0,
            "rule": "ai_index_waymo_airbag_x_axis_repair",
        },
        {
            "needles": ["按类型分类的安全气囊触发事件统计", "Incident type"],
            "bbox": [39.0, 538.0, 50.0, 586.0],
            "target": "事故类型",
            "fontsize": 5.0,
            "rule": "ai_index_waymo_airbag_y_axis_repair",
        },
        {
            "needles": ["3.1 SCOPE AND DIMENSIONS OF RESPONSIBLE AI"],
            "bbox": [118.0, 25.0, 580.0, 42.0],
            "target": "3.1 负责任AI的范围与维度 | 负责任人工智能 | 人工智能指数报告 2026",
            "fontsize": 5.0,
            "rule": "ai_index_responsible_ai_running_header_repair",
        },
        {
            "needles": ["3.2 ASSESSING RESPONSIBLE AI"],
            "bbox": [118.0, 25.0, 580.0, 42.0],
            "target": "3.2 评估负责任AI | 负责任人工智能 | 人工智能指数报告 2026",
            "fontsize": 5.0,
            "rule": "ai_index_responsible_ai_running_header_repair",
        },
        {
            "needles": ["3.3 HOW ORGANIZATIONS AND BUSINESSES VIEW RAI"],
            "bbox": [118.0, 25.0, 580.0, 42.0],
            "target": "3.3 各类组织与企业如何看待 RAI | 负责任人工智能 | 人工智能指数报告 2026",
            "fontsize": 5.0,
            "rule": "ai_index_responsible_ai_running_header_repair",
        },
        {
            "needles": ["3.4 RAI"],
            "bbox": [118.0, 25.0, 580.0, 42.0],
            "target": "3.4 学术界中的 RAI | 负责任人工智能 | 人工智能指数报告 2026",
            "fontsize": 5.0,
            "rule": "ai_index_responsible_ai_running_header_repair",
        },
        {
            "needles": ["Monthly AI incidents reported from news sources", "OECD"],
            "bbox": [36.0, 78.0, 330.0, 97.0],
            "target": "新闻来源报告的月度AI事件数（2020-2026）\n来源：OECD AIM，2026 | 图表：2026年AI Index报告",
            "fontsize": 4.9,
            "rule": "ai_index_responsible_ai_incidents_title_source_repair",
        },
        {
            "needles": ["Examples", "Grok"],
            "bbox": [35.0, 402.0, 112.0, 424.0],
            "target": "示例",
            "fontsize": 8.4,
            "color": (0.02, 0.23, 0.39),
            "rule": "ai_index_responsible_ai_section_heading_repair",
        },
        {
            "needles": ["After", "Joann", "Fabrics"],
            "bbox": [36.0, 100.0, 576.0, 166.0],
            "target": (
                "2025年1月，Joann Fabrics 第二次申请破产后，诈骗分子迅速发起伪造网站攻势，模仿该零售商的品牌标识、设计风格和产品目录。\n"
                "这些网站以极低折扣为诱饵，诱导消费者输入支付信息和个人资料；然而顾客最终并未收到商品，不少人还发现信用卡信息被盗用。\n"
                "这些假冒网站逼真度极高，甚至让原本谨慎的用户也上当，尤其在移动端浏览时更难识别网址真伪，受害风险更高。"
            ),
            "fontsize": 7.0,
            "rule": "ai_index_responsible_ai_joann_fabrics_body_repair",
        },
        {
            "needles": ["Public model evaluators and", "Artificial Analysis"],
            "bbox": [35.0, 627.0, 230.0, 646.0],
            "target": "公共模型评测者与基准平台",
            "fontsize": 8.0,
            "color": (0, 0, 0),
            "rule": "ai_index_responsible_ai_public_evaluators_heading_repair",
        },
        {
            "needles": ["Reported", "general", "capability", "foundation", "模型", "Table: 2026 AI Index report"],
            "bbox": [46.0, 78.0, 430.0, 94.0],
            "target": "热门基础模型报告的通用能力基准\n来源：AI Index | 表：2026年AI Index报告",
            "fontsize": 4.8,
            "rule": "ai_index_responsible_ai_benchmark_caption_repair",
        },
        {
            "needles": ["Reported", "safety", "responsible", "foundation", "模型", "Table: 2026 AI Index report"],
            "bbox": [46.0, 371.0, 440.0, 389.0],
            "target": "热门基础模型报告的安全与负责任AI基准\n来源：AI Index | 表：2026年AI Index报告",
            "fontsize": 4.8,
            "rule": "ai_index_responsible_ai_benchmark_caption_repair",
        },
        {
            "needles": ["H休斯幻觉评估模型", "HHEM"],
            "bbox": [35.0, 68.0, 250.0, 94.0],
            "target": "Hughes 幻觉评估模型（HHEM）排行榜",
            "fontsize": 12.8,
            "color": (0.02, 0.23, 0.39),
            "rule": "ai_index_responsible_ai_hhem_heading_repair",
        },
        {
            "needles": ["HHEM-2.3", "幻觉率来源", "HHEM排行榜"],
            "bbox": [35.0, 188.0, 250.0, 216.0],
            "target": "HHEM-2.3：幻觉率\n来源：HHEM排行榜，2026 | 图表：2026年AI Index报告",
            "fontsize": 5.2,
            "rule": "ai_index_responsible_ai_hhem_chart_title_source_repair",
        },
        {
            "needles": ["AA-Omniscience", "hallucination rate"],
            "bbox": [36.0, 78.0, 320.0, 101.0],
            "target": "AA-Omniscience：幻觉率\n来源：Artificial Analysis，2026 | 图表：2026年AI Index报告",
            "fontsize": 5.2,
            "rule": "ai_index_responsible_ai_aa_omniscience_hallucination_title_source_repair",
        },
        {
            "needles": ["AA-Omniscience: hallucination rate"],
            "bbox": [28.0, 424.0, 570.0, 459.0],
            "target": "AA-Omniscience 指数：跨领域表现（归一化）\nAA-Omniscience得分按同一领域所有模型归一化，绿色表示最高分，红色表示最低分。",
            "fontsize": 4.8,
            "rule": "ai_index_responsible_ai_aa_omniscience_heatmap_title_source_repair",
        },
        {
            "needles": ["AA-Omniscience: hallucination rate"],
            "bbox": [230.0, 454.0, 254.0, 466.0],
            "target": "最低",
            "fontsize": 4.4,
            "rule": "ai_index_responsible_ai_aa_omniscience_heatmap_legend_low_repair",
        },
        {
            "needles": ["AA-Omniscience: hallucination rate"],
            "bbox": [404.0, 454.0, 430.0, 466.0],
            "target": "最高",
            "fontsize": 4.4,
            "rule": "ai_index_responsible_ai_aa_omniscience_heatmap_legend_high_repair",
        },
        {
            "needles": ["AI Companions", "INTIMA"],
            "bbox": [35.0, 66.0, 170.0, 93.0],
            "target": "AI 伴侣",
            "fontsize": 12.6,
            "color": (0.02, 0.23, 0.39),
            "rule": "ai_index_responsible_ai_companions_heading_repair",
        },
        {
            "needles": ["Responsible AI Maturity", "McKinsey"],
            "bbox": [35.0, 280.0, 235.0, 307.0],
            "target": "负责任AI成熟度",
            "fontsize": 12.6,
            "color": (0.02, 0.23, 0.39),
            "rule": "ai_index_responsible_ai_maturity_heading_repair",
        },
        {
            "needles": ["Responsible AI maturity by region", "McKinsey"],
            "bbox": [35.0, 531.0, 300.0, 556.0],
            "target": "2024年与2025年各地区负责任AI成熟度\n来源：麦肯锡公司调查，2025 | 图表：2026年AI Index报告",
            "fontsize": 4.9,
            "rule": "ai_index_responsible_ai_maturity_chart_title_source_repair",
        },
        {
            "needles": ["Regulatory Influence", "General Data Protection"],
            "bbox": [35.0, 108.0, 220.0, 136.0],
            "target": "监管影响",
            "fontsize": 12.4,
            "color": (0.02, 0.23, 0.39),
            "rule": "ai_index_responsible_ai_regulatory_influence_heading_repair",
        },
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if (
            "FAIRNESS AND BIAS" in page_text
            and (
                "Global AI cultural and linguistic diversity assessment" in page_text
                or "Inclusiveness and the Global Language Gap" in page_text
                or "HELM Arabic" in page_text
                or "Indic LLM Arena" in page_text
                or "Slobench" in page_text
            )
        ):
            continue
        if not (
            "MMLU-Pro" in page_text
            or "Arena Leaderboard" in page_text
            or "Text Arena" in page_text
            or "Berkeley Function Calling" in page_text
            or "MTEB" in page_text
            or "Long Context Windows" in page_text
            or "MVBench" in page_text
            or "Video-MMMU" in page_text
            or "Vision Arena" in page_text
            or "Video-Bench" in page_text
            or "VBench-2.0" in page_text
            or "Progress in Video Generation" in page_text
            or "Midjourney" in page_text
            or "General Reasoning" in page_text
            or "ARC-AGI-2" in page_text
            or "ClockQA" in page_text
            or "GPQA" in page_text
            or "SWE-bench" in page_text
            or "Terminal-Bench" in page_text
            or "Vibe Code Bench" in page_text
            or "FrontierMath" in page_text
            or "MathArena" in page_text
            or "Theorem Proving" in page_text
            or "IMO-ProofBench" in page_text
            or "TaxEval" in page_text
            or "MortgageTax" in page_text
            or "CorpFin" in page_text
            or "Finance" in page_text
            or "Finance Agent" in page_text
            or "CaseLaw" in page_text
            or "LegalBench" in page_text
            or "GAIA" in page_text
            or "Law" in page_text
            or "OSWorld" in page_text
            or "WebArena" in page_text
            or "MLE-bench" in page_text
            or "Cybench" in page_text
            or "τ-bench" in page_text
            or "τ基准测试" in page_text
            or "RLBench" in page_text
            or "BEHAVIOR-1K" in page_text
            or "Robotics" in page_text
            or "Humanoid Robotics" in page_text
            or "ResponsibleRobotBench" in page_text
            or "Physical Intelligence" in page_text
            or "GR00T" in page_text
            or "Self-Driving Cars" in page_text
            or "Technical Innovations and New Benchmarks" in page_text
            or "Apollo Go" in page_text
            or "ADS incidents" in page_text
            or "Number of ADS incidents" in page_text
            or "Autonomous" in page_text
            or "Waymo" in page_text
            or "Incident type" in page_text
            or "AI Incidents" in page_text
            or "Number of AI incidents" in page_text
            or "Monthly AI incidents" in page_text
            or "Responsible AI" in page_text
            or "RESPONSIBLE AI" in page_text
            or "HOW ORGANIZATIONS" in page_text
            or "BUSINESSES VIEW RAI" in page_text
            or "SCOPE AND DIMENSIONS" in page_text
            or "ASSESSING RESPONSIBLE AI" in page_text
            or "HHEM" in page_text
            or "Hughes Hallucination" in page_text
            or "Hallucination rate" in page_text
            or "AA-Omniscience" in page_text
            or "AI Companions" in page_text
            or "Responsible AI Maturity" in page_text
            or "Responsible AI maturity by region" in page_text
            or "3.4 RAI" in page_text
            or "RAI IN ACADEMIA" in page_text
            or "RAI in Academia" in page_text
            or "Regulatory Influence" in page_text
            or "RAI Benchmarks" in page_text
            or "Joann Fabrics" in page_text
            or "Artificial Analysis" in page_text
            or "Reported general capability benchmarks" in page_text
            or "reported general capability benchmarks" in page_text
            or "Reported safety and responsible AI benchmarks" in page_text
            or "reported safety and responsible AI benchmarks" in page_text
            or "Safety" in page_text
            or "Release year" in page_text
            or "Amount of driving data" in page_text
        ):
            continue
        for spec in body_specs:
            if spec["needle"] not in page_text:
                continue
            rect = fitz.Rect(spec["bbox"])
            meta = replace_rect_source_han(page, rect, spec["target"], fontsize=float(spec["fontsize"]))
            meta.update(
                {
                    "font_policy": "embed_source_han_sans_for_language_body_redraw",
                    "text_policy": "translate_language_body_prose_misclassified_as_chart_label_or_passthrough",
                }
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_language_body_prose_text_layer_repair",
                    "source": spec["needle"],
                    "target": spec["target"][:180],
                    **meta,
                }
            )
        for spec in fixed_region_specs:
            if not all(needle in page_text for needle in spec["needles"]):
                continue
            rect = fitz.Rect(spec["bbox"])
            if spec["rule"] == "ai_index_finance_taxeval_fragmented_source_line_repair":
                _redact_with_fill(page, rect, (1, 1, 1))
                insert_source_han_sans(
                    page,
                    (rect.x0 + 1.0, rect.y1 - 2.0),
                    spec["target"],
                    fontsize=float(spec["fontsize"]),
                    color=(0, 0, 0),
                )
                meta = {
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": float(spec["fontsize"]),
                    "fill_strategy": "white_narrow_cover_then_single_line_source_han_redraw",
                }
            elif spec["rule"] == "ai_index_law_caselaw_title_source_line_repair":
                _redact_with_fill(page, rect, (1, 1, 1))
                insert_source_han_sans(
                    page,
                    (rect.x0 + 1.0, rect.y0 + 8.6),
                    "CaseLaw v2：准确率",
                    fontsize=6.0,
                    color=(0, 0, 0),
                )
                insert_source_han_sans(
                    page,
                    (rect.x0 + 1.0, rect.y0 + 17.8),
                    "来源：Vals.ai，2026 | 图表：2026年人工智能指数报告",
                    fontsize=float(spec["fontsize"]),
                    color=(0, 0, 0),
                )
                meta = {
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": float(spec["fontsize"]),
                    "fill_strategy": "white_narrow_cover_then_two_line_source_han_redraw",
                }
            elif (
                spec["rule"].startswith("ai_index_agents_")
                or spec["rule"].startswith("ai_index_robotics_")
                or spec["rule"].startswith("ai_index_autonomous_")
                or spec["rule"].startswith("ai_index_responsible_ai_")
            ):
                cover_fill = sampled_background_color(page, rect) if "running_header" in spec["rule"] else (1, 1, 1)
                _redact_with_fill(page, rect, cover_fill)
                title, _, source = spec["target"].partition("\n")
                if "footnote_url" in spec["rule"]:
                    insert_source_han_sans(
                        page,
                        (rect.x0 + 1.0, rect.y0 + 8.0),
                        title,
                        fontsize=float(spec["fontsize"]),
                        color=(0, 0, 0),
                    )
                    if source:
                        insert_source_han_sans(
                            page,
                            (rect.x0 + 1.0, rect.y0 + 18.0),
                            source,
                            fontsize=float(spec["fontsize"]),
                            color=(0, 0, 0),
                        )
                    meta = {
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": float(spec["fontsize"]),
                        "fill_strategy": "white_narrow_cover_then_two_line_source_han_redraw",
                    }
                    meta.update(
                        {
                            "font_policy": "embed_source_han_sans_for_url_footnote_repair",
                            "text_policy": "restore_protected_url_and_translate_data_source_label",
                        }
                    )
                    repairs.append(
                        {
                            "page": page_number,
                            "rule": spec["rule"],
                            "source": " / ".join(spec["needles"]),
                            "target": spec["target"],
                            **meta,
                        }
                    )
                    continue
                fit_source_han_textbox(
                    page,
                    rect,
                    spec["target"],
                    fontsize=float(spec["fontsize"]),
                    color=spec.get("color", (0, 0, 0)),
                )
                meta = {
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": float(spec["fontsize"]),
                    "fill_strategy": (
                        "sampled_header_background_then_source_han_textbox_redraw"
                        if "running_header" in spec["rule"]
                        else "white_narrow_cover_then_multiline_source_han_textbox_redraw"
                    ),
                }
            elif spec["rule"].startswith("ai_index_waymo_"):
                _redact_with_fill(page, rect, (1, 1, 1))
                fontsize = float(spec["fontsize"])
                if spec["target"] == "waymo_top_category_labels":
                    labels = [
                        ("其他", 344.5),
                        ("骑行者", 324.3),
                        ("摩托车", 304.1),
                        ("行人", 284.0),
                        ("二次碰撞", 263.8),
                        ("单车事故", 243.7),
                        ("V2V倒车", 223.5),
                        ("V2V前后碰", 203.4),
                        ("V2V迎面", 183.2),
                        ("V2V路口", 163.1),
                        ("V2V侧向", 143.0),
                    ]
                    for label, baseline in labels:
                        draw_text_run(page, rect.x0 + 1.0, baseline, label, fontsize=fontsize, color=(0, 0, 0))
                elif spec["target"] == "waymo_bottom_category_labels":
                    labels = [
                        ("其他", 657.0),
                        ("二次碰撞", 620.0),
                        ("V2V前后碰", 583.2),
                        ("V2V迎面", 546.3),
                        ("V2V路口", 509.3),
                        ("V2V侧向", 472.4),
                    ]
                    for label, baseline in labels:
                        draw_text_run(page, rect.x0 + 1.0, baseline, label, fontsize=fontsize, color=(0, 0, 0))
                elif spec["rule"].endswith("_y_axis_repair"):
                    fit_source_han_textbox(page, rect, spec["target"], fontsize=fontsize, rotate=90, color=(0, 0, 0))
                elif spec["rule"].endswith("_x_axis_repair"):
                    insert_source_han_sans(page, (rect.x0 + 1.0, rect.y1 - 2.0), spec["target"], fontsize=fontsize, color=(0, 0, 0))
                else:
                    title, _, source = spec["target"].partition("\n")
                    insert_source_han_sans(page, (rect.x0 + 1.0, rect.y0 + 8.5), title, fontsize=fontsize, color=(0, 0, 0))
                    if source:
                        insert_source_han_sans(page, (rect.x0 + 1.0, rect.y0 + 17.0), source, fontsize=max(4.5, fontsize - 0.2), color=(0, 0, 0))
                meta = {
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": fontsize,
                    "fill_strategy": "white_narrow_cover_then_waymo_chart_label_redraw",
                }
            else:
                meta = replace_rect_source_han(page, rect, spec["target"], fontsize=float(spec["fontsize"]))
            meta.update(
                {
                    "font_policy": "embed_source_han_sans_for_reasoning_small_chart_source",
                    "text_policy": "redraw_fragmented_reasoning_chart_source_line_as_single_chinese_line",
                }
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": spec["rule"],
                    "source": " / ".join(spec["needles"]),
                    "target": spec["target"],
                    **meta,
                }
            )
        # 幻觉率纵轴在部分字体中会把下降箭头抽取为中点；用限定 source
        # 前缀做完整标签修复，避免通用短词规则误伤其它图表。
        if "Hallucination rate" in page_text:
            for hit in page.search_for("Hallucination rate"):
                rect = fitz.Rect(max(0.0, hit.x0 - 2.0), max(0.0, hit.y0 - 5.0), hit.x1 + 8.0, min(page.rect.height, hit.y1 + 16.0))
                _redact_with_fill(page, rect, (1, 1, 1))
                fit_source_han_textbox(page, rect, "幻觉率↓", fontsize=6.0, rotate=90, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_language_heading_or_axis_label_repair",
                        "source": "Hallucination rate ↓",
                        "target": "幻觉率↓",
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 6.0,
                        "fill_strategy": "white_hallucination_axis_complete_text_fit_redraw",
                        "font_policy": "source_han_sans_vertical_axis_profile",
                        "text_policy": "restore_hallucination_rate_axis_with_direction_arrow",
                    }
                )
        # Video-Bench 的纵轴箭头在部分字体中会被抽取为中点，且通用逐行
        # 识别可能在邻近图表覆盖后丢失。这里用限定上下文和 bbox profile
        # 做三层一致的定点修复，不扩大到其它短词 “Score”。
        if "Video-Bench video quality" in page_text and "VBench-2.0: total score" in page_text:
            score_hits = [hit for hit in page.search_for("Score") if 490.0 <= hit.y0 <= 550.0]
            if score_hits:
                hit = score_hits[0]
                rect = fitz.Rect(max(0.0, hit.x0 - 2.0), max(0.0, hit.y0 - 5.0), hit.x1 + 8.0, min(page.rect.height, hit.y1 + 14.0))
                _redact_with_fill(page, rect, (1, 1, 1))
                fit_source_han_textbox(page, rect, "得分↑", fontsize=6.0, rotate=90, color=(0, 0, 0))
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_language_heading_or_axis_label_repair",
                        "source": "Score↑",
                        "target": "得分↑",
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": 6.0,
                        "fill_strategy": "white_video_bench_axis_complete_text_fit_redraw",
                        "font_policy": "source_han_sans_vertical_axis_profile",
                        "text_policy": "restore_video_bench_score_axis_with_arrow_from_contextual_bbox",
                    }
                )
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if not text or not bbox:
                continue
            matched_text = text
            if matched_text not in heading_specs:
                for long_axis_label in [
                    "Number of weekly paid trips (in thousands)",
                    "Amount of driving data in hours",
                    "Number of ADS incidents",
                ]:
                    if (
                        (len(text) >= 10 and long_axis_label.startswith(text))
                        or long_axis_label in text
                        or text.startswith(long_axis_label[:18])
                    ):
                        matched_text = long_axis_label
                        break
            if matched_text not in heading_specs and "3.6" in text and "Governance for Privacy" in text:
                matched_text = "3.6 数据 Governance for Privacy 数据"
            if matched_text not in heading_specs and "Number of reported AI incidents" in text:
                matched_text = "Number of reported AI incidents, 2012–25"
            if matched_text not in heading_specs and text.startswith("Hallucination rate"):
                matched_text = "Hallucination rate ↓"
            if matched_text not in heading_specs:
                continue
            target, fontsize, color, role = heading_specs[matched_text]
            if matched_text == "AI Incidents" and float(bbox[1]) > 540:
                target, fontsize, color, role = ("AI事件", 7.2, (0, 0, 0), "chart_title")
            if matched_text == "Generation" and float(bbox[1]) > 500:
                continue
            if matched_text == "Model" and float(bbox[1]) < 280:
                continue
            is_vertical_axis = role == "axis_label" and float(bbox[3]) > float(bbox[2] - bbox[0]) * 1.8
            if is_vertical_axis:
                rect = expanded_rect(fitz, bbox, page, pad=0.35, min_width=8.0)
            else:
                rect = expanded_rect(fitz, bbox, page, pad=1.0, min_width=max(28.0, cjk_text_width(fitz, target, fontsize=fontsize) + 6.0))
            if not rect:
                continue
            if text == "FrontierMath Tier 4: pass@1 accuracy":
                rect.x0 = max(20.0, rect.x0 - 120.0)
                rect.x1 = min(page.rect.width - 20.0, max(rect.x1, rect.x0 + 170.0))
                rect.y0 = max(0.0, rect.y0 - 2.0)
                rect.y1 = min(page.rect.height, rect.y1 + 6.0)
                meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=(1, 1, 1), color=color)
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_language_heading_or_axis_label_repair",
                        "source": matched_text,
                        "target": target,
                        **meta,
                        "font_policy": "source_han_sans_textbox_for_narrow_specific_domain_chart_title",
                        "text_policy": "translate_specific_domain_chart_title_with_bbox_left_expansion",
                    }
                )
                continue
            if matched_text in {"TaxEval v2: accuracy", "MortgageTax: accuracy", "CorpFin v2: accuracy", "Finance Agent v1.1: accuracy", "LegalBench: accuracy", "GAIA: accuracy"}:
                rect.x0 = max(20.0, rect.x0 - 1.0)
                rect.x1 = min(page.rect.width - 20.0, max(rect.x1 + 58.0, rect.x0 + 154.0))
                rect.y0 = max(0.0, rect.y0 - 2.0)
                rect.y1 = min(page.rect.height, rect.y1 + 7.0)
                meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=(1, 1, 1), color=color)
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_language_heading_or_axis_label_repair",
                        "source": matched_text,
                        "target": target,
                        **meta,
                        "font_policy": "source_han_sans_textbox_for_narrow_finance_chart_title",
                        "text_policy": "translate_specific_domain_finance_chart_title_with_bbox_expansion",
                    }
                )
                continue
            if role == "section_heading":
                rect.x1 = min(page.rect.width - 30, max(rect.x1, rect.x0 + cjk_text_width(fitz, target, fontsize=fontsize) + 12.0))
                rect.y1 = max(rect.y1, rect.y0 + 18.0)
            fill = (1, 1, 1) if role in {"axis_label", "chart_label"} else sampled_background_color(page, rect)
            _redact_with_fill(page, rect, fill)
            baseline = rect.y1 - (4.0 if role == "section_heading" else 2.0)
            if role == "axis_label" and rect.height >= rect.width:
                if re.search(r"[A-Za-z]", target):
                    fit_textbox(page, rect, target, fontsize=fontsize, rotate=90, color=color)
                else:
                    fit_source_han_textbox(page, rect, target, fontsize=fontsize, rotate=90, color=color)
            elif role == "section_heading":
                draw_text_run(page, rect.x0 + 1.0, baseline, target.strip(), fontsize=fontsize, color=color)
            else:
                insert_source_han_sans(page, (rect.x0 + 1.0, baseline), target, fontsize=fontsize, color=color)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_language_heading_or_axis_label_repair",
                    "source": matched_text,
                    "target": target,
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": fontsize,
                    "fill_strategy": "sampled_background_exact_line_repair",
                    "font_policy": "source_han_sans_single_layer_for_chart_axis_or_language_heading",
                    "text_policy": "translate_language_section_visible_labels_without_global_short_word_repair",
                }
            )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
