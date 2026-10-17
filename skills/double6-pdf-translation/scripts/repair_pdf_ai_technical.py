# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai technical：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_author_panel_caption_fragments(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, normalize_text, sampled_background_color
    repairs: list[dict[str, Any]] = []
    residue_fragments = [
        "域作者与发",
        "比情况数据来源",
        "2026年人工智能指",
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if "按性别划分的顶级AI作者与发明者占比" not in page_text:
            continue
        for fragment in residue_fragments:
            for hit in page.search_for(fragment)[:3]:
                if not (200 < hit.y0 < 250):
                    continue
                rect = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], page, pad=0.35, min_width=8)
                if not rect:
                    continue
                fill = sampled_background_color(page, rect)
                try:
                    page.add_redact_annot(rect, fill=fill)
                    page.apply_redactions()
                except Exception:
                    page.draw_rect(rect, color=fill, fill=fill, overlay=True)
                repairs.append(
                    {
                        "page": page_number,
                        "rule": "ai_index_author_panel_caption_fragment_cleanup",
                        "source": fragment,
                        "target": "",
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fill_strategy": "sampled_panel_background_fragment_cleanup",
                        "font_policy": "no_new_text_preserve_nearby_country_labels",
                        "text_policy": "remove_backend_fragmented_caption_residue_after_clean_chart_title_inserted",
                    }
                )
    return repairs


def repair_ai_index_mobility_panel_title_band(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_ai_links import draw_text_run
    from repair_pdf_drawing import normalize_text, sampled_background_color
    repairs: list[dict[str, Any]] = []
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if not ("2010" in page_text and "2025" in page_text and "分布情况" in page_text):
            continue
        if "净流动（12个月滚动平均）" not in page_text:
            continue
        cover_rect = fitz.Rect(35.0, 64.0, 292.0, 94.5)
        fill = sampled_background_color(page, cover_rect)
        try:
            page.add_redact_annot(cover_rect, fill=fill)
            page.apply_redactions()
        except Exception:
            page.draw_rect(cover_rect, color=fill, fill=fill, overlay=True)
        title = "图表：2010-25年各国顶级AI作者与发明者净流动"
        draw_text_run(page, 36.0, 76.2, title, fontsize=7.4, color=(0, 0, 0))
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_mobility_panel_title_band_redraw",
                "source": "fragmented mobility multipanel title/source band",
                "target": title,
                "bbox": [round(v, 2) for v in [cover_rect.x0, cover_rect.y0, cover_rect.x1, cover_rect.y1]],
                "fill_strategy": "sampled_panel_background_title_band_redraw_without_source_line",
                "font_policy": "mixed_latin_cjk_source_like_compact_title",
                "text_policy": "translate_mobility_chart_title_preserve_nearby_country_labels_and_chart_lines",
            }
        )
    return repairs


def repair_ai_index_technical_performance_highlight_residue(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, insert_source_han_sans_fake_bold, normalize_text, sampled_background_color
    repairs: list[dict[str, Any]] = []
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        probe_text = re.sub(r"[\x00-\x1f]+", " ", page_text)
        if not re.search(r"surpassing\s+human-level\s+perfor|surpassing\s+human-level\s+performance", probe_text, re.I):
            continue
        surpassing_hits = list(page.search_for("surpassing"))
        perfor_hits = list(page.search_for("perfor"))
        tail_hits = list(page.search_for("mance"))
        if not surpassing_hits:
            continue
        first_hit = surpassing_hits[0]
        same_line_perfor = next(
            (
                hit
                for hit in perfor_hits
                if abs(hit.y0 - first_hit.y0) < 3.0 and hit.x0 > first_hit.x0
            ),
            None,
        )
        first_bbox = [first_hit.x0, first_hit.y0, (same_line_perfor.x1 if same_line_perfor else first_hit.x1), first_hit.y1]
        first = expanded_rect(fitz, first_bbox, page, pad=0.4, min_width=20)
        if not first:
            continue
        repair_rects = [first]
        for hit in tail_hits[:3]:
            if first.y0 < hit.y0 < first.y1 + 25 and hit.x0 < 120:
                tail = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], page, pad=0.3, min_width=8)
                if tail:
                    repair_rects.append(tail)
                break
        for rect in repair_rects:
            fill = sampled_background_color(page, rect)
            try:
                page.add_redact_annot(rect, fill=fill)
                page.apply_redactions()
            except Exception:
                page.draw_rect(rect, color=fill, fill=fill, overlay=True)
        target = "超过人类水平表现"
        insert_source_han_sans_fake_bold(page, (first.x0 + 0.2, first.y1 - 3.1), target, fontsize=8.0, color=(0.43, 0.13, 0.48))
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_technical_performance_highlight_residue_repair",
                "source": "surpassing human-level performance",
                "target": target,
                "bbox": [round(v, 2) for v in [first.x0, first.y0, first.x1, first.y1]],
                "fill_strategy": "sampled_highlight_panel_background_fragment_cleanup",
                "font_policy": "source_han_sans_fake_bold_match_highlight_title_color",
                "text_policy": "translate_chapter_highlight_prose_residue_without_reflowing_entire_paragraph",
            }
        )
    return repairs


def repair_ai_index_technical_performance_toc_headings(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, insert_source_han_sans, normalize_text, page_lines, sampled_background_color
    repairs: list[dict[str, Any]] = []
    replacements = {
        "Benchmarks vs. Human": ("基准测试与人类表现对比", 10.0, "white"),
        "Model Performance Converges at": ("前沿模型性能趋同", 10.0, "white"),
        "Frontier": ("前沿", 6.8, "white"),
        "Highlight: The Gap Between": ("亮点：长上下文窗口与", 9.0, "yellow"),
        "Long Context Windows and": ("AI深度理解之间的差距", 9.0, "yellow"),
        "Highlight: Progress in Video": ("亮点：视频生成", 9.0, "yellow"),
        "Generation": ("进展", 9.0, "yellow"),
        "Highlight: Time Understanding": ("亮点：MLLMs 的时间", 9.0, "yellow"),
        "in MLLMs": ("理解能力", 9.0, "yellow"),
        "Highlight: Theorem Proving": ("亮点：定理证明", 9.0, "yellow"),
        "Planning": ("规划", 10.0, "white"),
        "Software": ("软件", 10.0, "white"),
        "Mathematics": ("数学", 10.0, "white"),
        "Finance": ("金融", 10.0, "white"),
        "Law": ("法律", 10.0, "white"),
    }
    exact_line_needles = {
        "Frontier",
        "Generation",
        "Planning",
        "Software",
        "Mathematics",
        "Finance",
        "Law",
    }
    white = (1, 1, 1)
    yellow = (0.78, 0.93, 0.12)
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        page_text = normalize_text(page.get_text("text"))
        if "Video-Bench" not in page_text or "CaseLaw" not in page_text:
            continue
        repaired_generation_highlight = False
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if not text or not bbox:
                continue
            if "Highlight: Progress in Video" in text:
                repaired_generation_highlight = True
            if text == "Generation" and not repaired_generation_highlight:
                continue
            if text == "Generation" and float(bbox[1]) < 200:
                replacement = replacements.get("Generation")
            else:
                replacement = None
                for needle, (target, size, tone) in replacements.items():
                    if needle == "Generation":
                        continue
                    if needle in exact_line_needles:
                        if not (text == needle or re.fullmatch(rf"{re.escape(needle)}\s+\d{{1,3}}", text)):
                            continue
                    elif needle not in text:
                        continue
                    replacement = (target, size, tone)
                    break
            if not replacement:
                continue
            target, fontsize, tone = replacement
            page_number_match = re.search(r"\s(\d{2,3})$", text)
            if page_number_match and not re.search(r"\d{2,3}$", target):
                target = f"{target} {page_number_match.group(1)}"
            rect = expanded_rect(fitz, bbox, page, pad=0.65, min_width=max(24, len(target) * fontsize * 0.62))
            if not rect:
                continue
            rect.x1 = min(page.rect.width - 25, max(rect.x1, rect.x0 + len(target) * fontsize * 0.72))
            fill = sampled_background_color(page, rect)
            try:
                page.add_redact_annot(rect, fill=fill)
                page.apply_redactions()
            except Exception:
                page.draw_rect(rect, color=fill, fill=fill, overlay=True)
            color = yellow if tone == "yellow" else white
            baseline = rect.y1 - 3.1
            insert_source_han_sans(page, (rect.x0 + 0.8, baseline), target, fontsize=fontsize, color=color)
            repairs.append(
                {
                    "page": page_number,
                    "rule": "ai_index_technical_performance_toc_explanatory_heading_repair",
                    "source": text[:120],
                    "target": target,
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "fontsize": fontsize,
                    "fill_strategy": "sampled_purple_toc_background_exact_line_repair",
                    "font_policy": "source_han_sans_single_layer_match_toc_white_or_highlight_yellow",
                    "text_policy": "translate_explanatory_toc_headings_preserve_benchmark_names",
                }
            )
    return repairs


def repair_ai_index_technical_performance_section_headings(fitz: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    from repair_pdf_ai_links import draw_text_run
    from repair_pdf_drawing import cjk_text_width, expanded_rect, normalize_text, page_lines, sampled_background_color
    repairs: list[dict[str, Any]] = []
    replacements = [
        {
            "needle": "Tech技术性能基准与人类表现（Human Performance）",
            "target": "技术性能基准与人类表现",
            "fontsize": 12.4,
            "color": (0.43, 0.13, 0.48),
            "pad": 1.2,
            "min_width": 170.0,
            "rule": "ai_index_technical_performance_section_heading_repair",
        },
        {
            "needle": "Benchmarking AI",
            "target": "人工智能基准测试",
            "fontsize": 16.2,
            "color": (0.43, 0.13, 0.48),
            "pad": 1.4,
            "min_width": 135.0,
            "rule": "ai_index_technical_performance_section_heading_repair",
        },
        {
            "needle": "2.1 OVERALL PERFORMANCE TRENDS | 技术性能 | 人工智能指数报告 2026",
            "target": "2.1 人工智能整体性能发展趋势 | 技术性能 | 人工智能指数报告 2026",
            "fontsize": 5.2,
            "color": (0.43, 0.13, 0.48),
            "pad": 0.7,
            "min_width": 180.0,
            "rule": "ai_index_technical_performance_running_header_repair",
        },
    ]
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        page = doc[page_index]
        for spec in replacements:
            needle = spec["needle"]
            target = spec["target"]
            hit_rects = list(page.search_for(needle))[:3]
            if not hit_rects:
                for row in page_lines(page):
                    if needle in normalize_text(row.get("text") or ""):
                        rect_from_row = expanded_rect(fitz, row.get("bbox"), page, pad=0.0, min_width=1.0)
                        if rect_from_row:
                            hit_rects.append(rect_from_row)
                        break
            for hit in hit_rects:
                rect = expanded_rect(fitz, [hit.x0, hit.y0, hit.x1, hit.y1], page, pad=float(spec["pad"]), min_width=float(spec["min_width"]))
                if not rect:
                    continue
                if spec["rule"] == "ai_index_technical_performance_section_heading_repair":
                    rect.x1 = min(page.rect.width - 28, max(rect.x1, rect.x0 + cjk_text_width(fitz, target, fontsize=float(spec["fontsize"])) + 8))
                    rect.y1 = max(rect.y1, rect.y0 + 18.0)
                fill = sampled_background_color(page, rect)
                try:
                    page.add_redact_annot(rect, fill=fill)
                    page.apply_redactions()
                except Exception:
                    page.draw_rect(rect, color=fill, fill=fill, overlay=True)
                is_section_heading = spec["rule"] == "ai_index_technical_performance_section_heading_repair"
                baseline = rect.y1 - (4.6 if is_section_heading else 2.3)
                x_offset = 2.4 if is_section_heading else 0.8
                visible_target = f" {target}" if is_section_heading else target
                draw_text_run(page, rect.x0 + x_offset, baseline, visible_target, fontsize=float(spec["fontsize"]), color=spec["color"])
                repairs.append(
                    {
                        "page": page_number,
                        "rule": spec["rule"],
                        "source": needle,
                        "target": target,
                        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                        "fontsize": spec["fontsize"],
                        "fill_strategy": "sampled_page_background_exact_line_repair",
                        "font_policy": "source_han_sans_single_layer_preserve_text_layer_cleanliness",
                        "text_policy": "translate_technical_performance_heading_without_rewriting_body_or_proper_names",
                    }
                )
                break
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
