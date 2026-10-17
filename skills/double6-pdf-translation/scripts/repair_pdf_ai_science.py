# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai science：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_science_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 AI Index Science 章节的固定图表标签、页眉和小节标题。"""
    from repair_pdf_drawing import fit_source_han_textbox, insert_source_han_sans, normalize_text, page_lines, replace_rect_source_han, sampled_background_color
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []
    purple = (77 / 255, 32 / 255, 73 / 255)

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
            fit_source_han_textbox(page, fitz.Rect(xs[0], top + 7.0, xs[0] + widths[0], bottom - 5.0), row["name"], fontsize=7.1, color=blue)
            fit_source_han_textbox(page, fitz.Rect(xs[1], top + 7.0, xs[1] + widths[1], bottom - 5.0), row.get("affiliation", ""), fontsize=5.8, color=(0.12, 0.12, 0.12))
            fit_source_han_textbox(page, fitz.Rect(xs[2], top + 8.0, xs[2] + widths[2], bottom - 5.0), row.get("domain", ""), fontsize=7.0, color=(0.12, 0.12, 0.12))
            sector_y = top + 7.0
            for sector in row.get("sectors", []):
                badge = fitz.Rect(xs[3] + 4.0, sector_y, xs[3] + widths[3] - 4.0, sector_y + 14.0)
                color = sector_colors.get(sector, (0.5, 0.5, 0.5))
                page.draw_rect(badge, color=color, fill=color, radius=0.2, overlay=True)
                fit_source_han_textbox(page, badge + (0, 2.0, 0, 0), sector, fontsize=6.0, color=(1, 1, 1))
                sector_y += 16.0
            fit_source_han_textbox(page, fitz.Rect(xs[4], top + 7.0, xs[4] + widths[4], bottom - 5.0), row.get("summary", ""), fontsize=5.8, color=(0.12, 0.12, 0.12))
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
                "font_policy": "source_han_sans_fixed_ai_index_science_label",
                "text_policy": policy,
            }
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
        rule: str = "ai_index_science_chart_label_repair",
        policy: str = "translate_science_chart_label_preserve_chart_geometry",
    ) -> None:
        rect = fitz.Rect(rect_values)
        meta = replace_rect_source_han(page, rect, target, fontsize=fontsize, fill=fill, color=color, rotate=rotate)
        add_meta(page_number, rule, source, target, meta, policy=policy)

    def chart_title_source(
        page: Any,
        page_number: int,
        rect_values: list[float],
        target: str,
        *,
        source: str,
        fontsize: float = 4.8,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, (1, 1, 1))
        insert_source_han_sans(page, (rect.x0 + 2.0, rect.y0 + 10.0), target, fontsize=fontsize, color=(0, 0, 0))
        insert_source_han_sans(page, (rect.x0 + 2.0, rect.y0 + 18.0), "来源：AI Index，2026 | 图表：2026年AI Index报告", fontsize=4.0, color=(0, 0, 0))
        add_meta(
            page_number,
            "ai_index_science_chart_title_source_repair",
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_white_region_then_science_title_source_lines"},
            policy="redraw_science_chart_title_source_as_compact_chinese_lines",
        )

    def cleanup_hidden_residue(page: Any, page_number: int, needle: str, *, policy: str) -> None:
        """清理已被视觉层覆盖、但仍留在 PDF 文本层里的英文残片。"""

        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = normalize_text(span.get("text") or "")
                    if needle not in text:
                        continue
                    bbox = span.get("bbox")
                    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                        continue
                    rect = fitz.Rect(bbox).irect + (-1, -1, 1, 1)
                    fill = sampled_background_color(page, rect)
                    _redact_with_fill(page, rect, fill)
                    add_meta(
                        page_number,
                        "ai_index_science_highlights_hidden_text_layer_cleanup",
                        text,
                        "",
                        {
                            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                            "fill_strategy": "sampled_highlight_panel_background_text_layer_redaction",
                        },
                        policy=policy,
                    )

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]

        if has_line_in_region(source_page, "Chapter Highlights", y0=100.0, y1=135.0):
            cleanup_hidden_residue(
                page,
                page_number,
                "a model with 40 billion parameters",
                policy="remove_hidden_english_text_layer_residue_after_science_highlights_visual_translation",
            )

        if has_line_in_region(source_page, "5.2 AI ACROSS SCIENTIFIC DOMAINS", y0=24.0, y1=42.0):
            fixed_textbox(
                page,
                page_number,
                [232.0, 23.5, 512.0, 42.5],
                "5.2 人工智能跨科学领域 | 科学 | 人工智能指数报告 2026",
                fontsize=3.8,
                source="5.2 AI ACROSS SCIENTIFIC DOMAINS | SCIENCE | AI INDEX REPORT 2026",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_running_header_repair",
                policy="translate_science_5_2_running_header_preserve_page_rule_and_remove_leftover_ai_acr_residue",
            )

        if has_line_in_region(source_page, "5.1 AI FOR SCIENCE IN 2025", y0=24.0, y1=42.0):
            fixed_textbox(
                page,
                page_number,
                [278.0, 24.0, 510.0, 42.0],
                "5.1 2025年的AI科学 | 科学 | 人工智能指数报告 2026",
                fontsize=3.8,
                source="5.1 AI FOR SCIENCE IN 2025 | SCIENCE | AI INDEX REPORT 2026",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_running_header_repair",
                policy="translate_science_running_header_preserve_page_rule",
            )

        if has_line_in_region(source_page, "Number of AI-related publications in natural sciences, 2010", y0=74.0, y1=94.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 78.0, 360.0, 101.0],
                "2010年至2025年自然科学领域AI相关出版物数量",
                source="Number of AI-related publications in natural sciences, 2010–25",
                fontsize=4.8,
            )
            fixed_textbox(
                page,
                page_number,
                [34.0, 125.0, 52.0, 326.0],
                "AI相关自然科学出版物数量（千篇）",
                fontsize=4.25,
                source="Number of AI publications in natural sciences (in thousands)",
                fill=(1, 1, 1),
                rotate=90,
                rule="ai_index_science_chart_label_repair",
                policy="translate_science_publications_y_axis_preserve_line_chart_ticks",
            )
            fixed_textbox(
                page,
                page_number,
                [526.0, 368.0, 578.0, 384.0],
                "图 5.1.1",
                fontsize=5.8,
                source="Figure 5.1.1",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_chart_geometry",
            )

        if has_line_in_region(source_page, "AI-related publications in natural sciences (% of total)", y0=405.0, y1=426.0):
            chart_title_source(
                page,
                page_number,
                [36.0, 410.0, 368.0, 433.0],
                "2010年至2025年自然科学领域AI相关出版物占比",
                source="AI-related publications in natural sciences (% of total), 2010–25",
                fontsize=4.8,
            )
            fixed_textbox(
                page,
                page_number,
                [33.0, 482.0, 52.0, 635.0],
                "AI相关自然科学出版物占比（%）",
                fontsize=4.25,
                source="AI publications in natural sciences (% of total)",
                fill=(1, 1, 1),
                rotate=90,
                rule="ai_index_science_chart_label_repair",
                policy="translate_science_publications_share_y_axis_preserve_line_chart_ticks",
            )
            fixed_textbox(
                page,
                page_number,
                [526.0, 700.0, 578.0, 716.0],
                "图 5.1.2",
                fontsize=5.8,
                source="Figure 5.1.2",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_chart_geometry",
            )
            stale_credit_rect = fitz.Rect(34.0, 432.0, 108.0, 443.0)
            _redact_with_fill(page, stale_credit_rect, (1, 1, 1))
            add_meta(
                page_number,
                "ai_index_science_chart_credit_residue_cleanup",
                "2026 AI Index report",
                "",
                {
                    "bbox": [round(v, 2) for v in [stale_credit_rect.x0, stale_credit_rect.y0, stale_credit_rect.x1, stale_credit_rect.y1]],
                    "fill_strategy": "fixed_white_cleanup_for_wrapped_chart_credit_residue",
                },
                policy="remove_wrapped_chart_credit_residue_without_touching_axis_ticks_or_chart_lines",
            )

        if has_line_in_region(source_page, "In chemistry and materials", y0=500.0, y1=522.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 501.0, 172.0, 522.0],
                "化学与材料领域",
                fontsize=7.0,
                source="In chemistry and materials",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_inline_section_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Datasets", y0=572.0, y1=598.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 572.0, 104.0, 598.0],
                "数据集",
                fontsize=9.0,
                source="Datasets",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_section_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "AI Agents", y0=88.0, y1=116.0, x0=30.0, x1=150.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 90.0, 230.0, 116.0],
                "AI智能体",
                fontsize=11.0,
                source="AI Agents",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_ai_agents_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Biological and Life Sciences", y0=76.0, y1=104.0, x0=30.0, x1=260.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 78.0, 300.0, 104.0],
                "生物与生命科学",
                fontsize=11.0,
                source="Biological and Life Sciences",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_biological_life_sciences_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Datasets", y0=630.0, y1=660.0, x0=30.0, x1=130.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 633.0, 125.0, 660.0],
                "数据集",
                fontsize=15.0,
                source="Datasets",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_datasets_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Benchmarks", y0=525.0, y1=570.0, x0=30.0, x1=190.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 532.0, 172.0, 566.0],
                "基准测试",
                fontsize=15.0,
                source="Benchmarks",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_benchmarks_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Benchmarks", y0=452.0, y1=486.0, x0=30.0, x1=170.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 454.0, 170.0, 486.0],
                "基准测试",
                fontsize=15.0,
                source="Benchmarks",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_benchmarks_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Foundation Models", y0=525.0, y1=558.0, x0=30.0, x1=220.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 527.0, 220.0, 560.0],
                "基础模型",
                fontsize=15.0,
                source="Foundation Models",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_foundation_models_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Selected datasets in physics, astronomy, chemistry, and materials science", y0=80.0, y1=130.0):
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 464.0],
                [
                    {"name": "ChemPile", "affiliation": "Helmholtz Institute for Polymers (HIPOLE) Jena; Friedrich Schiller University Jena; Hacettepe University; University of Toronto", "domain": "化学", "sectors": ["学术界", "非营利"], "summary": "750亿+经整理的化学数据 token，涵盖 SMILES、InChI、文本、代码和教学材料。"},
                    {"name": "Multimodal Universe", "affiliation": "Polymathic AI; Instituto de Astrofisica de Canarias; Universidad de La Laguna; Massachusetts Institute of Technology", "domain": "天文学", "sectors": ["学术界", "非营利"], "summary": "100TB 天文数据集，包含来自数亿次观测的多通道图像、光谱和时间序列。"},
                    {"name": "OMol25", "affiliation": "FAIR at Meta; Los Alamos National Laboratory; University College Dublin", "domain": "化学、材料、化学物理", "sectors": ["产业界", "政府", "学术界"], "summary": "1亿+ DFT 计算，覆盖83种元素、多样化学相互作用，以及最多350个原子的结构。"},
                    {"name": "OC25", "affiliation": "FAIR at Meta; Texas Tech University; Nanyang Technological University", "domain": "化学、材料", "sectors": ["产业界", "政府", "学术界"], "summary": "780万次计算，覆盖150万种溶剂环境和88种元素，用于固液界面催化研究。"},
                ],
                header_color=(78 / 255, 32 / 255, 74 / 255),
            )

        if has_line_in_region(source_page, "Selected AI agents in physics, astronomy, chemistry, and materials science", y0=248.0, y1=286.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 255.0, 470.0, 280.0],
                "物理学、天文学、化学及材料科学领域的精选AI智能体（2025年）",
                fontsize=8.0,
                source="Selected AI agents in physics, astronomy, chemistry, and materials science (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 286.0, 576.0, 724.0],
                [
                    {"name": "ChatGPTMaterial Explorer", "affiliation": "Johns Hopkins University", "domain": "材料科学", "sectors": ["学术界"], "summary": "材料科学助手，将 LLM 与图神经网络结合，用于性质预测。"},
                    {"name": "ChemAgents", "affiliation": "University of Science and Technology of China; University of Birmingham; Henan Academy of Sciences", "domain": "化学", "sectors": ["学术界", "政府"], "summary": "机器人 AI 化学家（Llama-3.1-70B）；自主合成、优化和光催化。"},
                    {"name": "ChemToolAgent", "affiliation": "Shanghai Artificial Intelligence Laboratory; Soochow University; Zhejiang University", "domain": "化学、材料科学", "sectors": ["学术界", "政府"], "summary": "整合137个外部化学工具；HE-MCTS 框架在化学问答上超过 GPT-4o。"},
                    {"name": "Crystalyse", "affiliation": "Imperial College London", "domain": "材料科学、化学", "sectors": ["学术界"], "summary": "面向材料设计的多工具 AI 智能体，通过 LLM 推理框架协调多个计算工具。"},
                    {"name": "Physics Supernova", "affiliation": "Princeton University; Tsinghua University; Shanghai Jiao Tong University", "domain": "物理", "sectors": ["学术界"], "summary": "2025年 IPhO 得分23.5/30，在406名参赛者中排第14；达到金牌水平。"},
                    {"name": "StarWhisper Telescope", "affiliation": "University of Chinese Academy of Sciences; National Astronomical Observatories (CAS); Simon Fraser University", "domain": "天文学", "sectors": ["学术界", "政府", "产业界"], "summary": "自动规划10台望远镜的天文观测；由 LLM 驱动观测计划。"},
                ],
                header_color=(78 / 255, 32 / 255, 74 / 255),
            )

        if has_line_in_region(source_page, "Selected datasets in biological and life sciences", y0=72.0, y1=104.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 78.0, 350.0, 102.0],
                "生物与生命科学领域的精选数据集（2025年）",
                fontsize=8.4,
                source="Selected datasets in biological and life sciences (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 382.0],
                [
                    {"name": "OpenGenome2", "affiliation": "Arc Institute; Stanford University; Nvidia", "domain": "生物学、基因组学", "sectors": ["学术界", "非营利", "产业界"], "summary": "来自各生命域的9.3万亿个经整理 DNA 碱基对；Evo 2 的训练语料。"},
                    {"name": "ProteinTalks-DB", "affiliation": "Westlake University", "domain": "蛋白质组学、系统生物学", "sectors": ["学术界"], "summary": "来自药物处理乳腺癌细胞的3800万+蛋白质组测量，用于蛋白动力学和药物反应预测。"},
                    {"name": "Spacetop", "affiliation": "Dartmouth College; Johns Hopkins University; Emory University", "domain": "神经科学", "sectors": ["学术界"], "summary": "101名参与者、600多个成像小时；覆盖认知、情感、社会和内感受领域。"},
                ],
                header_color=(78 / 255, 32 / 255, 74 / 255),
            )

        if has_line_in_region(source_page, "Selected benchmarks in biological and life sciences", y0=72.0, y1=104.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 78.0, 365.0, 102.0],
                "生物与生命科学领域的精选基准测试（2025年）",
                fontsize=8.4,
                source="Selected benchmarks in biological and life sciences (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 492.0],
                [
                    {"name": "BaisBench", "affiliation": "Tsinghua University", "domain": "生物学", "sectors": ["学术界"], "summary": "通过细胞注释和数据驱动问题，评估 AI 的生物发现能力。"},
                    {"name": "BioML-bench", "affiliation": "Shift Bioscience; University of Cambridge; ScienceMachine", "domain": "生物学", "sectors": ["产业界", "学术界"], "summary": "首个端到端生物医学机器学习评测；AI 智能体平均低于人类基线。"},
                    {"name": "BixBench", "affiliation": "FutureHouse; ScienceMachine", "domain": "计算生物学", "sectors": ["产业界"], "summary": "50多个生物信息学场景；GPT-4o 与 Claude 3.5 Sonnet 准确率约17%。"},
                    {"name": "CGBench", "affiliation": "Stanford University", "domain": "生物学（遗传学）", "sectors": ["学术界"], "summary": "临床遗传学解释；推理模型在细粒度任务上表现突出，但仍有明显幻觉缺口。"},
                    {"name": "Mouse vs. AI: Robust Foraging Competition", "affiliation": "UC Santa Barbara", "domain": "神经科学", "sectors": ["学术界"], "summary": "仿生基准，将强化学习智能体置于与小鼠共享的觅食任务中，以神经科学为基础。"},
                ],
                header_color=(20 / 255, 80 / 255, 84 / 255),
            )

        if has_line_in_region(source_page, "Selected foundation models in biological and life sciences", y0=72.0, y1=104.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 78.0, 395.0, 102.0],
                "生物与生命科学领域的主要基础模型（2025年）",
                fontsize=8.4,
                source="Selected foundation models in biological and life sciences (2025)",
                fill=(1, 1, 1),
                color=(27 / 255, 71 / 255, 116 / 255),
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 644.0],
                [
                    {"name": "AlphaGenome", "affiliation": "Google DeepMind", "domain": "生物学、基因组学", "sectors": ["产业界"], "summary": "基因组基础模型，可在单碱基分辨率上预测数千种功能测量。"},
                    {"name": "ANN Model", "affiliation": "Baylor College of Medicine; Stanford University; University of Göttingen", "domain": "神经科学", "sectors": ["学术界"], "summary": "神经活动基础模型；可预测不同刺激类型和小鼠下的神经元反应。"},
                    {"name": "BioCLIP 2", "affiliation": "The Ohio State University; Smithsonian Institution; UNC-Chapel Hill", "domain": "生物学", "sectors": ["学术界", "非营利"], "summary": "用于生物分类的视觉基础模型；通过层级对比学习微调生命之树。"},
                    {"name": "BioLab", "affiliation": "Princeton University; BioMap Research; Zhejiang University", "domain": "生物学", "sectors": ["学术界", "产业界"], "summary": "面向自动化生物研究的多智能体系统；实验验证了新的抗体设计。"},
                    {"name": "CellFM", "affiliation": "Sun Yat-sen University; Chongqing University; Jinfeng Laboratory", "domain": "生物学", "sectors": ["学术界", "政府", "产业界"], "summary": "8亿参数、1亿个人体细胞；单细胞分析、扰动预测和基因关系。"},
                    {"name": "Evo 2", "affiliation": "Arc Institute; Nvidia; Stanford University; UC Berkeley", "domain": "生物学、基因组学", "sectors": ["学术界", "产业界"], "summary": "400亿参数、100万 token 上下文；9.3万亿碱基对，基因组级生成，完全开源。"},
                    {"name": "ProteinTalks", "affiliation": "Westlake University; DP Technology Co.; Westlake Omics Co.", "domain": "蛋白质组学、系统生物学", "sectors": ["学术界", "产业界"], "summary": "用于蛋白网络动态的基础模型；基于扰动蛋白组数据预测药物疗效与协同作用。"},
                ],
                header_color=(27 / 255, 71 / 255, 116 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 652.0, 576.0, 668.0],
                "图 5.2.7",
                fontsize=5.8,
                source="Figure 5.2.7",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "Selected AI agents in biological and life sciences", y0=214.0, y1=246.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 112.0, 576.0, 140.0],
                "生命科学领域的智能体系统正逐步用于实现各类复杂研究流程的自动化处理，包括文献综述整合与生物信息学分析等。",
                fontsize=9.0,
                source="Agent systems in the life sciences are beginning to operationalize complex research workflows, including literature synthesis and bioinformatics execution.",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 146.0, 576.0, 206.0],
                "BCI-Agent能够在无需针对特定任务进行训练的情况下，依据电生理记录数据自动完成神经元细胞类型的分类工作。Biomni是一款适用于25个生物医学子领域的通用型智能代理。第6章将更为详细地阐述其架构与功能特性（参见图5.2.8）。",
                fontsize=8.4,
                source="BCI-Agent performs autonomous neuronal cell-type classification ... Biomni is a general-purpose biomedical agent...",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 218.0, 380.0, 242.0],
                "生物与生命科学领域精选的人工智能智能体（2025年）",
                fontsize=8.0,
                source="Selected AI agents in biological and life sciences (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 250.0, 576.0, 514.0],
                [
                    {"name": "BCI-Agent", "affiliation": "Harvard University; Massachusetts Institute of Technology (MIT); Broad Institute of MIT and Harvard", "domain": "神经科学", "sectors": ["学术界"], "summary": "无需特定任务训练，即可依据电生理数据自主完成神经细胞类型分类。"},
                    {"name": "BioAgents", "affiliation": "UC Berkeley; Microsoft Research; UC San Francisco", "domain": "生物学", "sectors": ["学术界", "产业界"], "summary": "面向小语言模型的多智能体系统；在概念基因组学任务上达到专家水平。"},
                    {"name": "Biomni", "affiliation": "Stanford University; Genentech; Arc Institute", "domain": "生物学", "sectors": ["学术界", "产业界", "非营利"], "summary": "通用型生物医学智能体，覆盖25个领域；第6章有详细介绍。"},
                ],
                header_color=(128 / 255, 45 / 255, 131 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 522.0, 576.0, 538.0],
                "图 5.2.8",
                fontsize=5.8,
                source="Figure 5.2.8",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "Earth Science", y0=548.0, y1=586.0, x0=30.0, x1=210.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 552.0, 210.0, 586.0],
                "地球科学",
                fontsize=15.0,
                source="Earth Science",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_earth_science_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Datasets", y0=138.0, y1=170.0, x0=30.0, x1=140.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 142.0, 145.0, 172.0],
                "数据集",
                fontsize=15.0,
                source="Datasets",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_datasets_heading_preserve_body_flow",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 174.0, 576.0, 252.0],
                "地球科学领域的研究在很大程度上依赖于各类大型政府及机构观测系统，而非专门为人工智能训练而构建的语料库。在碳通量研究方面，全球范围内的通量观测塔网络提供了至关重要的基础观测数据。FLUXNET2015便汇集了来自世界各地观测站的涡度协方差测量数据；此外，各区域性网络如覆盖北美洲的AmeriFlux、覆盖欧洲的ICOS以及覆盖日本及东亚地区的JapanFlux也提供了补充数据。这些数据集为训练与评估相关模型创造了条件，使得人们能够将局部的碳通量测量结果推广至区域乃至全球尺度上的估算（见图5.2.9）。",
                fontsize=8.0,
                source="Earth science relies heavily on large governmental and institutional observation systems rather than purpose-built AI training corpora.",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )

        if has_line_in_region(source_page, "Selected datasets in Earth science", y0=270.0, y1=304.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 276.0, 300.0, 300.0],
                "地球科学领域的精选数据集（2025年）",
                fontsize=8.0,
                source="Selected datasets in Earth science (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 306.0, 576.0, 722.0],
                [
                    {"name": "AmeriFlux", "affiliation": "Indiana University; USDA Agricultural Research Service; University of Wisconsin-Madison", "domain": "生态学", "sectors": ["学术界", "政府"], "summary": "北美260多个通量塔站网络，测量生态系统碳、水和能量交换；50多个站点有10年以上连续数据。"},
                    {"name": "CAMELS", "affiliation": "NSF National Center for Atmospheric Research; U.S. Geological Survey; U.S. Department of the Interior", "domain": "水文学", "sectors": ["政府"], "summary": "671个美国河流流域的地形、气候、土壤和径流标准化数据，是 AI 水文基准的基础。"},
                    {"name": "FLUXNET2015", "affiliation": "Lawrence Berkeley National Laboratory; University of Tuscia; ETH Zurich", "domain": "生态学", "sectors": ["学术界", "政府"], "summary": "全球 CO2、水和能量交换测量；来自212个全球站点，覆盖1990至2014年。"},
                    {"name": "ICOS", "affiliation": "ICOS ERIC; University of Helsinki; Thünen Institute of Climate-Smart Agriculture; ETH Zurich", "domain": "生态学", "sectors": ["学术界", "政府"], "summary": "欧洲140多个站点观测网络，覆盖12个国家，测量温室气体浓度以及生态系统和海洋交换。"},
                    {"name": "JapanFlux", "affiliation": "Osaka Metropolitan University; Chiba University; National Institute of Polar Research (NIPR)", "domain": "生态学", "sectors": ["学术界", "政府"], "summary": "日本及东亚站点的陆地-大气通量测量；跟踪亚洲生态系统的能量、水和 CO2 交换。"},
                ],
                header_color=(77 / 255, 32 / 255, 73 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 728.0, 576.0, 744.0],
                "图 5.2.9",
                fontsize=5.8,
                source="Figure 5.2.9",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "Benchmarks", y0=86.0, y1=122.0, x0=30.0, x1=170.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 90.0, 170.0, 122.0],
                "基准测试",
                fontsize=15.0,
                source="Benchmarks",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_benchmarks_heading_preserve_body_flow",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 118.0, 576.0, 164.0],
                "2025年，地球科学领域的基准测试进一步延伸至对极端事件预测可靠性的评估；在这一领域中，人工智能气象模型面临着最为严峻的挑战。然而，常规的平均性能指标却难以准确反映这些模型的真实表现（见图5.2.10）。",
                fontsize=8.7,
                source="In 2025, benchmarks in Earth science expanded into reliability of extreme event coverage...",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )

        if has_line_in_region(source_page, "Selected benchmarks in Earth science", y0=180.0, y1=212.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 168.0, 330.0, 192.0],
                "地球科学领域的典型基准数据集（2025年）",
                fontsize=8.0,
                source="Selected benchmarks in Earth science (2025)",
                fill=(1, 1, 1),
                color=(20 / 255, 80 / 255, 84 / 255),
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 196.0, 576.0, 452.0],
                [
                    {"name": "EarthSE", "affiliation": "Shanghai Jiao Tong University; Shanghai Artificial Intelligence Laboratory; Hong Kong Polytechnic University", "domain": "地球科学", "sectors": ["学术界", "产业界"], "summary": "100篇论文、114个学科、11个 LLM；测试地球科学探索中的显著差距。"},
                    {"name": "ExEBench", "affiliation": "Technical University of Munich (TUM); Munich Center for Machine Learning (MCML)", "domain": "大气科学", "sectors": ["学术界"], "summary": "7类极端事件；全球覆盖。测试检测、监测和预报能力。"},
                    {"name": "UnivEARTH", "affiliation": "Cornell University; Columbia University", "domain": "地球科学", "sectors": ["学术界"], "summary": "140道地球观测问题；LLM 智能体准确率33%，代码错误占58%。"},
                ],
                header_color=(20 / 255, 80 / 255, 84 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 462.0, 576.0, 478.0],
                "图 5.2.10",
                fontsize=5.8,
                source="Figure 5.2.10",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "Foundation Models", y0=520.0, y1=560.0, x0=30.0, x1=220.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 526.0, 220.0, 560.0],
                "基础模型",
                fontsize=15.0,
                source="Foundation Models",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_foundation_models_heading_preserve_body_flow",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 562.0, 576.0, 650.0],
                "2025年发布的各类地球科学基础模型被广泛应用于天气预报、气候模拟以及地理空间信息表示。在天气预报领域，有多款系统均是以《2025年人工智能指数报告（AI Index Report）》中所重点介绍的模型为基础构建而成的。FourCastNet 3能够在单个GPU上仅用不到4分钟的时间便生成分辨率为0.25度的全球60天天气预报数据，其运算速度比传统方法快了8至60倍。而在地球观测领域，TerraMind则是首个可处理9种不同地理空间数据模态的“任意输入至任意输出”式生成型多模态模型（见图5.2.11）。",
                fontsize=8.0,
                source="Earth science foundation models released in 2025 covered weather forecasting...",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )

        if has_line_in_region(source_page, "Selected foundation models in Earth science", y0=72.0, y1=104.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 78.0, 365.0, 102.0],
                "地球科学领域的主要基础模型（2025年）",
                fontsize=8.2,
                source="Selected foundation models in Earth science (2025)",
                fill=(1, 1, 1),
                color=(27 / 255, 71 / 255, 116 / 255),
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 644.0],
                [
                    {"name": "AlphaEarth", "affiliation": "Google DeepMind", "domain": "地球观测", "sectors": ["产业界"], "summary": "面向通用地理空间表征的嵌入场模型，性能超过以往的特征化方法。"},
                    {"name": "cBottle (Climate in a Bottle)", "affiliation": "Nvidia", "domain": "气候科学", "sectors": ["产业界"], "summary": "基于扩散的气候模拟器；全球5公里、1250万像素分辨率，覆盖昼夜到季节变化。"},
                    {"name": "FourCastNet 3", "affiliation": "Nvidia; Lawrence Berkeley National Laboratory; UC Berkeley", "domain": "天气预报", "sectors": ["产业界", "政府", "学术界"], "summary": "单GPU不到4分钟生成60天预报，速度快8至60倍；延续 Aurora 与 NeuralGCM 的进展。"},
                    {"name": "GAIA", "affiliation": "USRA/RIACS; BCG X AI Science Institute", "domain": "大气科学", "sectors": ["产业界"], "summary": "基于15年卫星影像训练的大气基础模型；大气河流F1为0.58，气旋检测召回率81%。"},
                    {"name": "OlmoEarth", "affiliation": "Allen Institute for AI; University of Washington; Arizona State University", "domain": "地球观测", "sectors": ["学术界", "非营利"], "summary": "多模态时空地球观测基础模型，为非政府组织和非营利机构提供平台。"},
                    {"name": "TerraMind", "affiliation": "IBM Research; ETH Zurich; Forschungszentrum Julich", "domain": "地球观测", "sectors": ["产业界", "学术界", "政府"], "summary": "首个任意输入到任意输出的生成式多模态地球观测基础模型，覆盖9种地理空间模态。"},
                    {"name": "WeatherNext 2", "affiliation": "Google DeepMind", "domain": "天气预报", "sectors": ["产业界"], "summary": "不到1分钟/TPU即可输出数百种天气结果；较前代提升99.9%，并建立在 GenCast 基础上。"},
                ],
                header_color=(27 / 255, 71 / 255, 116 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 652.0, 576.0, 668.0],
                "图 5.2.11",
                fontsize=5.8,
                source="Figure 5.2.11",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "Selected AI agents in Earth science", y0=176.0, y1=206.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 90.0, 165.0, 116.0],
                "AI智能体",
                fontsize=11.0,
                source="AI Agents",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_ai_agents_heading_preserve_body_flow",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 118.0, 576.0, 168.0],
                "在地球科学领域，各类人工智能体正逐步摆脱单纯的数据检索功能，转而承担完整的研究工作流程——包括自动化的观测数据处理、基于文献资料的分析工作以及各类气候相关任务的执行。实践表明，ClimateAgent成功完成了85项气候相关任务，完成率达100%，其质量评分也达到了8.32；相比之下，微软Copilot的得分仅为6.27，GPT-5则仅有3.26（见图5.2.12）。",
                fontsize=8.4,
                source="In Earth science, AI agents are moving beyond data retrieval toward executing full research workflows...",
                fill=(1, 1, 1),
                color=(0, 0, 0),
                rule="ai_index_science_body_paragraph_repair",
                policy="translate_science_body_paragraph_after_partial_left_side_writeback_loss",
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 186.0, 330.0, 202.0],
                "地球科学领域中值得关注的AI智能体（2025年）",
                fontsize=8.0,
                source="Selected AI agents in Earth science (2025)",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_table_caption_repair",
                policy="translate_science_table_caption_preserve_table_geometry",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 216.0, 576.0, 456.0],
                [
                    {"name": "ClimateAgent", "affiliation": "The Hong Kong University of Science and Technology", "domain": "气候科学", "sectors": ["学术界"], "summary": "85项气候任务完成率100%，质量评分8.32；高于 Copilot 6.27 和 GPT-5 3.26。"},
                    {"name": "EarthLink", "affiliation": "Shanghai Artificial Intelligence Laboratory; Fudan University; University of Sydney", "domain": "气候科学", "sectors": ["产业界", "学术界"], "summary": "面向地球科学家的首个AI copilot，可通过动态反馈循环实现自动化研究流程。"},
                    {"name": "PANGAEA GPT", "affiliation": "Alfred Wegener Institute for Polar and Marine Research", "domain": "地球科学", "sectors": ["政府"], "summary": "面向 PANGAEA 地球科学数据库的多智能体系统，支持智能数据处理和自然语言界面。"},
                ],
                header_color=(128 / 255, 45 / 255, 131 / 255),
            )
            fixed_textbox(
                page,
                page_number,
                [518.0, 462.0, 576.0, 478.0],
                "图 5.2.12",
                fontsize=5.8,
                source="Figure 5.2.12",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_science_figure_label_preserve_table_geometry",
            )

        if has_line_in_region(source_page, "5.3 AI Agents and", y0=62.0, y1=112.0):
            fixed_textbox(
                page,
                page_number,
                [35.0, 66.0, 350.0, 122.0],
                "5.3 科学工作流中的\nAI智能体与工具",
                fontsize=15.0,
                source="5.3 AI Agents and Tools for Science Workflows",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_5_3_title_repair",
                policy="translate_science_5_3_chapter_title_preserve_large_heading",
            )

        if has_line_in_region(source_page, "AstaBench: average score", y0=392.0, y1=414.0):
            chart_title_source(
                page,
                page_number,
                [34.0, 394.0, 268.0, 424.0],
                "AstaBench：平均得分",
                source="AstaBench: average score",
                fontsize=5.0,
            )
            fixed_textbox(
                page,
                page_number,
                [32.0, 500.0, 52.0, 572.0],
                "平均得分",
                fontsize=4.6,
                source="Average score",
                fill=(1, 1, 1),
                rotate=90,
                rule="ai_index_science_chart_label_repair",
                policy="translate_astabench_y_axis_preserve_scatter_plot_geometry",
            )
            fixed_textbox(
                page,
                page_number,
                [246.0, 648.0, 398.0, 666.0],
                "每题平均成本（美元）",
                fontsize=4.8,
                source="Average cost per problem (in US dollars)",
                fill=(1, 1, 1),
                rule="ai_index_science_chart_label_repair",
                policy="translate_astabench_x_axis_preserve_tick_labels",
            )
            fixed_textbox(
                page,
                page_number,
                [524.0, 676.0, 578.0, 692.0],
                "图 5.3.1",
                fontsize=5.8,
                source="Figure 5.3.1",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_astabench_figure_label_preserve_chart_geometry",
            )

        if has_line_in_region(source_page, "5.3 AI AGENTS AND TOOLS FOR SCIENCE WORKFLOWS", y0=24.0, y1=42.0):
            fixed_textbox(
                page,
                page_number,
                [152.0, 24.0, 512.0, 42.5],
                "5.3 科学工作流中的AI智能体与工具 | 科学 | 人工智能指数报告 2026",
                fontsize=3.8,
                source="5.3 AI AGENTS AND TOOLS FOR SCIENCE WORKFLOWS | SCIENCE | AI INDEX REPORT 2026",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_running_header_repair",
                policy="translate_science_5_3_running_header_preserve_page_rule",
            )

        if has_line_in_region(source_page, "PaperArena: single vs. multiagent performance", y0=236.0, y1=260.0):
            chart_title_source(
                page,
                page_number,
                [34.0, 240.0, 285.0, 270.0],
                "PaperArena：单智能体与多智能体表现",
                source="PaperArena: single vs. multiagent performance",
                fontsize=5.0,
            )
            fixed_textbox(
                page,
                page_number,
                [84.0, 272.0, 212.0, 290.0],
                "单智能体     多智能体",
                fontsize=5.4,
                source="Single agent / Multiagent",
                fill=(1, 1, 1),
                rule="ai_index_science_chart_legend_repair",
                policy="translate_paperarena_legend_preserve_color_swatch_positions",
            )
            fixed_textbox(
                page,
                page_number,
                [32.0, 346.0, 52.0, 404.0],
                "平均得分",
                fontsize=4.6,
                source="Average score",
                fill=(1, 1, 1),
                rotate=90,
                rule="ai_index_science_chart_label_repair",
                policy="translate_paperarena_y_axis_preserve_bar_chart_geometry",
            )
            fixed_textbox(
                page,
                page_number,
                [304.0, 516.0, 342.0, 532.0],
                "模型",
                fontsize=5.0,
                source="Model",
                fill=(1, 1, 1),
                rule="ai_index_science_chart_label_repair",
                policy="translate_paperarena_x_axis_preserve_model_names",
            )
            fixed_textbox(
                page,
                page_number,
                [524.0, 522.0, 578.0, 538.0],
                "图 5.3.2",
                fontsize=5.8,
                source="Figure 5.3.2",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_paperarena_figure_label_preserve_chart_geometry",
            )

        if has_line_in_region(source_page, "AI as a Co-scientist", y0=614.0, y1=642.0):
            if has_line_in_region(source_page, "AI Agents", y0=574.0, y1=606.0, x0=30.0, x1=130.0):
                fixed_textbox(
                    page,
                    page_number,
                    [35.0, 582.0, 145.0, 606.0],
                    "AI智能体",
                    fontsize=11.0,
                    source="AI Agents",
                    fill=(1, 1, 1),
                    color=purple,
                    rule="ai_index_science_section_heading_repair",
                    policy="translate_science_ai_agents_heading_preserve_body_flow",
                )
            fixed_textbox(
                page,
                page_number,
                [35.0, 620.0, 220.0, 642.0],
                "作为共同科学家的AI",
                fontsize=11.0,
                source="AI as a Co-scientist",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_ai_as_co_scientist_heading_preserve_body_flow",
            )

        if has_line_in_region(source_page, "Source: Gottweis et al., 2025", y0=400.0, y1=424.0):
            fixed_textbox(
                page,
                page_number,
                [108.0, 218.0, 410.0, 244.0],
                "AI共同科学家表现与GPQA钻石集问题Elo评分的一致性",
                fontsize=5.3,
                source="Concordance of the Elo rating with AI co-scientist performance on GPQA diamond set questions",
                fill=(1, 1, 1),
                rule="ai_index_science_chart_label_repair",
                policy="translate_ai_coscientist_chart_title_preserve_line_plot_geometry",
            )
            fixed_textbox(
                page,
                page_number,
                [76.0, 246.0, 134.0, 266.0],
                "AI共同科学家\nGemini 2.0",
                fontsize=4.1,
                source="AI co-scientist / Gemini 2.0",
                fill=(1, 1, 1),
                rule="ai_index_science_chart_legend_repair",
                policy="translate_ai_coscientist_legend_preserve_series_colors",
            )
            fixed_textbox(
                page,
                page_number,
                [422.0, 404.0, 576.0, 444.0],
                "来源：Gottweis等人，2025年\n图 5.3.2",
                fontsize=5.5,
                source="Source: Gottweis et al., 2025 / Figure 5.3.2",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_ai_coscientist_source_and_figure_label_preserve_chart_geometry",
            )

        if has_line_in_region(source_page, "Source: Ding et al., 2025", y0=410.0, y1=440.0) and has_line_in_region(source_page, "Figure 5.3.2", y0=430.0, y1=458.0):
            fixed_textbox(
                page,
                page_number,
                [454.0, 418.0, 578.0, 456.0],
                "来源：Ding等人，2025年\n图 5.3.2",
                fontsize=5.4,
                source="Source: Ding et al., 2025 / Figure 5.3.2",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_figure_label_repair",
                policy="translate_scitoolagent_source_and_figure_label_preserve_dense_image_chart_geometry_do_not_overlay_internal_metric_labels_without_precise_bboxes",
            )

        if has_line_in_region(source_page, "Selected benchmarks in physics, astronomy, chemistry, and materials science", y0=80.0, y1=130.0):
            draw_science_table(
                page,
                page_number,
                [36.0, 112.0, 576.0, 724.0],
                [
                    {"name": "AstroVisBench", "affiliation": "University of Texas at Austin; NSF National Optical-Infrared Astronomy Research Laboratory; University of Virginia", "domain": "天文学", "sectors": ["学术界", "政府"], "summary": "首个面向 LLM 天文学科学计算与可视化能力的基准。"},
                    {"name": "Chembench", "affiliation": "Friedrich Schiller University Jena; Helmholtz Institute for Polymers (HIPOLE) Jena; Spanish National Research Council (CSIC)", "domain": "化学", "sectors": ["学术界", "政府", "产业界"], "summary": "2700+ 组问答。最佳模型平均优于人类化学家，但在基础任务上仍会吃力。"},
                    {"name": "ChemX", "affiliation": "ITMO University; D ONE", "domain": "化学、材料科学", "sectors": ["学术界"], "summary": "10个精选数据集，用于从纳米材料和小分子中自动抽取化学信息。"},
                    {"name": "GravityBench", "affiliation": "University of Toronto; NYU Abu Dhabi", "domain": "物理、天体物理", "sectors": ["学术界"], "summary": "测试 AI 从引力模拟中发现物理定律的能力，包含非真实世界物理。"},
                    {"name": "LLM-SRBench", "affiliation": "Virginia Tech; VinUniversity; Carnegie Mellon University", "domain": "物理、科学方程发现", "sectors": ["学术界", "产业界"], "summary": "239道题，区分真正的方程发现与记忆；最佳系统得分31.5%。"},
                    {"name": "Matbench Discovery", "affiliation": "University of Cambridge; Lawrence Berkeley National Laboratory; Federal Institute for Materials Research and Testing (BAM)", "domain": "材料、化学", "sectors": ["学术界", "政府"], "summary": "用于机器学习能量模型的评估框架，预筛稳定无机晶体。"},
                    {"name": "MatSciBench", "affiliation": "UCLA; Princeton; Virginia Tech", "domain": "材料科学", "sectors": ["学术界", "产业界"], "summary": "1340道大学水平问题，覆盖6个领域和31个子领域；顶尖模型低于80%。"},
                    {"name": "PHYBench", "affiliation": "Peking University; CSRC", "domain": "物理", "sectors": ["学术界", "产业界"], "summary": "500道原创物理题；Gemini 2.5 Pro 为36.9%，人类专家为61.9%。"},
                ],
                header_color=(20 / 255, 80 / 255, 84 / 255),
            )

        if has_line_in_region(source_page, "PhysGym", y0=80.0, y1=150.0) and has_line_in_region(source_page, "Foundation Models", y0=340.0, y1=390.0):
            draw_science_table(
                page,
                page_number,
                [36.0, 80.0, 576.0, 322.0],
                [
                    {"name": "PhysGym", "affiliation": "KAUST Center of Excellence for Generative AI; The Swiss AI Lab", "domain": "物理", "sectors": ["学术界", "产业界"], "summary": "交互式物理环境，用于在不同先验知识下测试 LLM 科学推理。"},
                    {"name": "ReplicationBench", "affiliation": "Stanford University; University of Toronto", "domain": "天体物理 / 研究复现", "sectors": ["学术界"], "summary": "测试 AI 复现完整天体物理论文的能力；前沿模型得分低于20%。"},
                    {"name": "TPBench", "affiliation": "University of Wisconsin-Madison; Indiana University; NSF-Simons AI Institute for the Sky (SkAI)", "domain": "理论物理", "sectors": ["学术界"], "summary": "57道新颖理论物理题，涵盖高能理论与宇宙学；研究级问题大多仍未解决。"},
                ],
                header_color=(20 / 255, 80 / 255, 84 / 255),
                include_header=False,
            )
            fixed_textbox(
                page,
                page_number,
                [35.0, 360.0, 210.0, 390.0],
                "基础模型",
                fontsize=15.0,
                source="Foundation Models",
                fill=(1, 1, 1),
                color=purple,
                rule="ai_index_science_section_heading_repair",
                policy="translate_science_foundation_models_heading_preserve_body_flow",
            )
            draw_science_table(
                page,
                page_number,
                [36.0, 512.0, 576.0, 724.0],
                [
                    {"name": "AION-1", "affiliation": "UC Berkeley; Flatiron Institute; New York University", "domain": "天文学", "sectors": ["学术界", "非营利", "政府"], "summary": "天文学基础模型：3亿至31亿参数，覆盖5项大型巡天的2亿+天体；开放发布。"},
                    {"name": "ChemDFM", "affiliation": "Shanghai Jiao Tong University; Suzhou Laboratory; AI Speech Co.", "domain": "化学", "sectors": ["学术界", "政府", "产业界"], "summary": "化学 LLM：340亿 token、270万条指令；通用化学 AI。"},
                ],
                header_color=(27 / 255, 71 / 255, 116 / 255),
            )

        if has_line_in_region(source_page, "GPhyT: General", y0=80.0, y1=150.0):
            draw_science_table(
                page,
                page_number,
                [36.0, 80.0, 576.0, 708.0],
                [
                    {"name": "GPhyT", "affiliation": "RWTH Aachen University; University of Virginia", "domain": "物理", "sectors": ["学术界"], "summary": "基于1.8TB模拟数据训练；性能最高比专用模型好29倍；具备零样本泛化。"},
                    {"name": "MACE-MP-0", "affiliation": "University of Cambridge; Federal Institute for Materials Research and Testing (BAM); UC Berkeley", "domain": "化学物理", "sectors": ["学术界", "政府", "产业界"], "summary": "通用力场模型，用于预测几乎所有材料中的原子相互作用。"},
                    {"name": "MatterGen", "affiliation": "Microsoft Research AI for Science; Shenzhen Institute of Advanced Technology (Chinese Academy of Sciences)", "domain": "材料科学", "sectors": ["产业界", "政府"], "summary": "基于扩散的生成模型；新颖性与稳定性比既有方法高2倍以上。"},
                    {"name": "PDE-Transformer", "affiliation": "Technical University of Munich", "domain": "物理模拟", "sectors": ["学术界"], "summary": "用于网格上物理偏微分方程的 Transformer；在16类物理模拟中优于最先进视觉架构。"},
                    {"name": "PhysiX", "affiliation": "UCLA", "domain": "物理模拟", "sectors": ["学术界"], "summary": "45亿参数，首个大规模物理模拟基础模型；可从自然视频迁移到模拟任务。"},
                    {"name": "SMI-TED", "affiliation": "IBM Research", "domain": "化学", "sectors": ["产业界"], "summary": "在分子序列上训练的化学基础模型。"},
                    {"name": "Surya", "affiliation": "University of Alabama in Huntsville; NASA Marshall Space Flight Center; IBM Research", "domain": "日球物理", "sectors": ["学术界", "政府", "产业界"], "summary": "3.66亿参数，首个日球物理基础模型；无需任务特定训练即可预测空间天气。"},
                    {"name": "Walrus", "affiliation": "Flatiron Institute; New York University; University of Cambridge", "domain": "流体力学、连续介质力学等", "sectors": ["学术界", "非营利", "产业界"], "summary": "流体力学基础模型，覆盖天体物理、地球科学、等离子体物理、声学等19个场景；开放权重。"},
                ],
                header_color=(27 / 255, 71 / 255, 116 / 255),
                include_header=False,
            )

    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
