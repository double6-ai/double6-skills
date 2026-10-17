# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai misc：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_invalid_question_benchmark_chart(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import normalize_text
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    labels = [
        (333.0, "MMLU Math"),
        (360.0, "OpenBookQA"),
        (389.0, "MMLU CLG"),
        (417.0, "MMLU Med"),
        (446.0, "AIR-Bench"),
        (474.0, "MMLU Q&A"),
        (502.0, "Theorem"),
        (530.0, "MMLU SSb"),
        (558.0, "GSM8K"),
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if "九个基准测试中的无效问题检测" not in page_text:
            continue
        y_axis_rect = fitz.Rect(296.0, 546.0, 344.0, 609.0)
        _redact_with_fill(page, y_axis_rect, (1, 1, 1))
        page.insert_text((303.0, 604.0), "Precision@50", fontname="helv", fontsize=5.2, rotate=90, color=(0, 0, 0), overlay=True)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_invalid_question_benchmark_chart_axis_profile",
                "source": "Precision@50",
                "target": "Precision@50",
                "bbox": [round(v, 2) for v in [y_axis_rect.x0, y_axis_rect.y0, y_axis_rect.x1, y_axis_rect.y1]],
                "fontsize": 5.2,
                "fill_strategy": "white_chart_axis_background_latin_passthrough_redraw",
                "font_policy": "helvetica_latin_axis_label_passthrough",
                "text_policy": "preserve_benchmark_axis_label_untranslated",
            }
        )
        label_band = fitz.Rect(330.0, 648.0, 586.0, 720.0)
        _redact_with_fill(page, label_band, (1, 1, 1))
        for x, label in labels:
            page.insert_text((x, 713.0), label, fontname="helv", fontsize=5.0, rotate=90, color=(0, 0, 0), overlay=True)
        page.insert_text((432.0, 719.0), "Benchmark", fontname="helv", fontsize=5.2, color=(0, 0, 0), overlay=True)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_invalid_question_benchmark_chart_axis_profile",
                "source": "invalid_question_benchmark_x_axis_labels",
                "target": ", ".join(label for _, label in labels),
                "bbox": [round(v, 2) for v in [label_band.x0, label_band.y0, label_band.x1, label_band.y1]],
                "fontsize": 5.0,
                "fill_strategy": "white_chart_axis_background_latin_passthrough_redraw",
                "font_policy": "helvetica_latin_benchmark_names_passthrough",
                "text_policy": "preserve_benchmark_names_untranslated_and_redraw_as_compact_axis_labels",
            }
        )
    return repairs


def repair_ai_index_inference_paragraphs_from_text_layer(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import normalize_text, replace_rect_source_han
    repairs: list[dict[str, Any]] = []
    paragraphs = [
        {
            "needle": "Recent benchmarking by Jegham et al. (2025)",
            "target": (
                "Jegham 等人（2025）的最新基准测试估算了各模型在中等长度提示词下的推理能耗和碳排放"
                "（约 1,000 个输入词元和 1,000 个输出词元）。在 2025 年能耗最高的 15 个模型中，"
                "DeepSeek V3.2 Exp 和 DeepSeek V3.2 每次查询消耗最高（23 Wh），其次是 GPT-5 (high)，"
                "为 21.9 Wh（图1.4.5）。Claude 4 Opus 和 GPT-5 mini (medium) 等模型处于较低区间，约 5-6 Wh。"
                "按碳排放排序也呈现类似格局（图1.4.6）：DeepSeek V3.2 Exp 和 DeepSeek V3.2 的中等长度提示词排放最高，"
                "约为 14 克 CO2 当量；Claude 4 Opus 和 Mistral Medium 3 最低，分别为 1.6 克和 1.5 克。"
                "同一年发布的模型之间差异也很大，说明推理效率各不相同，能力更高并不必然意味着环境成本按比例上升。"
            ),
            "bbox": [34.0, 165.0, 580.0, 302.0],
            "fontsize": 7.2,
            "source": "Recent benchmarking by Jegham et al. (2025) ... environmental cost.",
        },
        {
            "needle": "At the level of a single query",
            "target": (
                "从单次查询看，数字较为温和。一次简短的 GPT-4o 查询约消耗 0.42 Wh，比一次 0.3 Wh 的 Google 搜索高约 40%"
                "（图1.4.7）。每天进行 8 次中等长度查询所用能量，大致相当于给两部智能手机充电（9.7 Wh）。"
                "但当每天查询达到数亿次时，总能耗会放大到更大的规模。\n"
                "同样的规模效应也适用于用水量（图1.4.8）。估算显示，GPT-4o 推理每年用水约为 130 万至 160 万千升；"
                "按高值计算，已超过 120 万人一年的饮用水需求。"
            ),
            "bbox": [332.0, 453.0, 579.0, 656.0],
            "fontsize": 7.0,
            "source": "At the level of a single query ... annual drinking water needs.",
        },
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        for item in paragraphs:
            if normalize_text(item["needle"]) not in page_text:
                continue
            rect = fitz.Rect(item["bbox"])
            meta = replace_rect_source_han(page, rect, item["target"], fontsize=float(item["fontsize"]), fill=(1, 1, 1))
            meta.update(
                {
                    "font_policy": "embed_source_han_sans_for_inference_body_paragraph_redraw",
                    "text_policy": "translate_ai_index_inference_body_prose_after_style_tag_same_as_input_failure",
                }
            )
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_inference_body_prose_text_layer_repair",
                    "source": item["source"],
                    "target": item["target"][:180],
                    **meta,
                }
            )
    return repairs


def repair_ai_index_technological_proximity_body(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import fit_source_han_textbox, insert_source_han_sans_fake_bold, normalize_text, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    target_title = "技术接近度"
    target_body = (
        "技术接近度衡量各国是在相似类型的人工智能创新上趋同，还是走向不同路径。按照 Bar 等人（2012）"
        "提出的方法，本分析比较各国 AI 专利组合与两个最大参照点美国和中国的贴近程度（见图1.7.7）。"
        "重合度按 0（完全不相似）到 1（完全相同）计分。大多数国家聚集在右上方，说明其 AI 专利覆盖的技术领域"
        "与美国和中国相近，但也有一些国家更偏向美国专利组合。印度和澳大利亚的专利组合与两者都接近 80% 重合；"
        "丹麦与两个参照点的相似度最低，与中国约 45% 重合、与美国约 52% 重合。这是因为丹麦的 AI 专利更多集中在"
        "能源和风能相关技术类别（专利代码 Y02E、F03D、F05B），而不是美国和中国占主导的核心计算与数据处理类别"
        "（G06F、G06N、G06K）。虽然多数国家的 AI 创新组合结构相似，但各国工业优势往往会影响 AI 的应用方向。"
    )
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if "Technological proximity" not in page_text:
            continue
        title_rect = fitz.Rect(34.0, 432.0, 260.0, 459.0)
        body_rect = fitz.Rect(34.0, 461.0, 585.0, 647.0)
        fill = sampled_background_color(page, body_rect)
        _redact_with_fill(page, title_rect, fill)
        _redact_with_fill(page, body_rect, fill)
        insert_source_han_sans_fake_bold(page, (36.0, 452.5), target_title, fontsize=15.2, color=(0.62, 0.89, 0.88))
        meta = fit_source_han_textbox(page, body_rect, target_body, fontsize=10.2, color=(1, 1, 1))
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_technological_proximity_body_repair",
                "source": "Technological proximity paragraph",
                "target": target_body[:180],
                "bbox": [round(v, 2) for v in [title_rect.x0, title_rect.y0, body_rect.x1, body_rect.y1]],
                "fontsize": meta,
                "fill_strategy": "sampled_teal_background_redraw",
                "font_policy": "match_ai_index_teal_callout_with_source_han_sans_white_body",
                "text_policy": "translate_ai_index_body_prose_misclassified_as_chart_label",
            }
        )
    return repairs


def repair_ai_missing_fixed_chart_labels(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, normalize_text, replace_rect
    repairs: list[dict[str, Any]] = []
    fixed_insertions = [
        (17, [35.55, 366.14, 190.85, 387.47], "按国家/地区归属划分", "By National Affiliation"),
        (17, [528.23, 651.72, 574.34, 665.56], "图 1.1.1", "Figure 1.1.1"),
        (18, [342.82, 353.59, 390.99, 367.44], "图 1.1.2", "Figure 1.1.2"),
        (18, [529.08, 711.52, 577.3, 725.36], "图 1.1.3", "Figure 1.1.3"),
        (19, [528.49, 607.91, 576.85, 621.75], "图 1.1.4", "Figure 1.1.4"),
        (20, [528.59, 376.45, 576.85, 390.29], "图 1.1.5", "Figure 1.1.5"),
        (20, [525.83, 719.11, 574.17, 732.95], "图 1.1.6", "Figure 1.1.6"),
    ]
    for page_number, bbox, target, source in fixed_insertions:
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        if target in normalize_text(page.get_text("text")):
            continue
        rect = expanded_rect(fitz, bbox, page, pad=1.3, min_width=36)
        if not rect:
            continue
        rect.x1 = min(page.rect.width - 8, max(rect.x1, rect.x0 + min(max(len(target) * 7.0 * 0.8, 36), page.rect.width - rect.x0 - 8)))
        meta = replace_rect(page, rect, target, fontsize=7.0)
        meta.update(
            {
                "font_policy": "match_source_chart_label_or_figure_label_size_color",
                "text_policy": "translate_missing_fixed_chart_label_preserve_numbering",
            }
        )
        repairs.append({"page": page_number, "rule": "chart_label_visible_repair", "source": source, "target": target, **meta})
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
