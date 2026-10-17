# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai frontmatter：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def copy_source_region(source_page: Any, target_page: Any, rect: Any) -> dict[str, Any]:
    source_doc = getattr(source_page, "parent", None)
    page_number = getattr(source_page, "number", 0)
    if source_doc is None:
        raise RuntimeError("source_page has no parent document")
    target_page.show_pdf_page(rect, source_doc, page_number, clip=rect, overlay=True, keep_proportion=False)
    return {
        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
        "fill_strategy": "source_region_copy",
        "font_policy": "preserve_source_region_fonts_colors_and_geometry",
        "text_policy": "passthrough_original_visual_region",
    }

def repair_cover_year(fitz: Any, source_page: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import expanded_rect, normalize_text, page_lines
    if re.search(r"\b20\d{2}\b", target_page.get_text("text")):
        return []
    for row in page_lines(source_page):
        text = normalize_text(row["text"])
        collapsed = re.sub(r"\s+", "", text)
        if not re.fullmatch(r"20\d{2}|2\s*0\s*2\s*6", text) and collapsed != "2026":
            continue
        rect = expanded_rect(fitz, row.get("bbox"), target_page, pad=4, min_width=80)
        if not rect:
            continue
        rect.x1 = min(target_page.rect.width - 24, max(rect.x1, rect.x0 + 120))
        meta = copy_source_region(source_page, target_page, rect)
        return [{"page": 1, "rule": "cover_year_visible_repair", "source": row["text"], "target": "2026", **meta}]
    return []


def repair_ai_cover_title_wrap(fitz: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import cover_text_rect, normalize_text, page_lines, pdf_color_to_rgb, source_han_serif_fontname
    rows = page_lines(target_page)
    for index, row in enumerate(rows[:-1]):
        first_text = normalize_text(row["text"])
        second_text = normalize_text(rows[index + 1]["text"])
        if first_text != "人工智能指数报" or second_text != "告":
            continue
        first_bbox = row.get("bbox")
        second_bbox = rows[index + 1].get("bbox")
        if not first_bbox or not second_bbox:
            continue
        first_rect = fitz.Rect([float(value) for value in first_bbox[:4]])
        second_rect = fitz.Rect([float(value) for value in second_bbox[:4]])
        char_width = first_rect.width / max(1, len(first_text))
        cut_rect = fitz.Rect(first_rect.x1 - char_width - 1.0, first_rect.y0 - 1.0, first_rect.x1 + 2.0, first_rect.y1 + 1.0)
        cut_rect.x0 = max(0, cut_rect.x0)
        cut_rect.x1 = min(target_page.rect.width, cut_rect.x1)
        second_cover = fitz.Rect(second_rect.x0 - 1.0, second_rect.y0 - 1.0, second_rect.x0 + char_width + 3.0, second_rect.y1 + 1.0)
        second_cover.x0 = max(0, second_cover.x0)
        second_cover.x1 = min(target_page.rect.width, second_cover.x1)
        cover_text_rect(target_page, cut_rect)
        cover_text_rect(target_page, second_cover)
        span = row.get("spans", [{}])[0] if isinstance(row.get("spans"), list) and row.get("spans") else {}
        fontsize = float(row.get("size") or span.get("size") or 37.44)
        color = pdf_color_to_rgb(span.get("color"))
        second_origin_y = float(rows[index + 1].get("origin_y") or (second_rect.y1 - max(8.0, fontsize * 0.3)))
        target_page.insert_text(
            (second_rect.x0, second_origin_y),
            "报告",
            fontname=source_han_serif_fontname(target_page),
            fontsize=fontsize,
            color=color,
            overlay=True,
        )
        return [
            {
                "page": 1,
                "rule": "cover_title_word_wrap_repair",
                "source": "人工智能指数报\\n告",
                "target": "人工智能指数\\n报告",
                "bbox": [
                    round(first_rect.x0, 2),
                    round(first_rect.y0, 2),
                    round(max(first_rect.x1, second_cover.x1), 2),
                    round(second_rect.y1, 2),
                ],
                "fill_strategy": "minimal_adjacent_background_region_copy",
                "text_policy": "avoid_splitting_title_word",
                "font_policy": "redraw_second_line_with_source_han_serif_cn",
                "second_line_cover_width": round(second_cover.width, 2),
            }
        ]
    return []


def repair_ai_contents_page_labels(fitz: Any, target_page: Any) -> list[dict[str, Any]]:
    """Redraw the front contents labels to avoid CJK glyph clipping.

    The backend-generated labels on the first contents page can have correct text
    extraction but clipped right-side glyph strokes in the visible PDF. Redrawing
    only the text bands preserves the original divider lines while using one CJK
    font and slightly larger labels.
    """
    if target_page.number + 1 != 2:
        return []
    rows = [
        (197.4, 212.0, "引言", "2", "regular"),
        (197.4, 238.0, "核心要点", "9", "regular"),
        (197.4, 263.0, "1 研究与开发", "12", "section"),
        (197.4, 288.0, "2 技术性能", "68", "section"),
        (197.4, 313.0, "3 负责任人工智能", "126", "section"),
        (197.4, 338.0, "4 经济", "171", "section"),
        (197.4, 363.0, "5 科学", "231", "section"),
        (197.4, 388.0, "6 医学", "255", "section"),
        (197.4, 413.0, "7 教育", "288", "section"),
        (197.4, 438.0, "8 政策与治理", "323", "section"),
        (197.4, 463.0, "9 公众舆论", "360", "section"),
        (197.4, 488.0, "附录", "385", "regular"),
    ]
    repairs: list[dict[str, Any]] = []
    fill = AI_INDEX_FOOTER_BG
    for x, baseline, label, page_no, kind in rows:
        cover = fitz.Rect(x - 3.0, baseline - 12.0, 562.0, baseline + 4.0)
        target_page.draw_rect(cover, color=fill, fill=fill, overlay=True)
        fontsize = 8.8 if kind == "section" else 8.4
        target_page.insert_text((x, baseline), label, fontname="china-s", fontsize=fontsize, color=(1, 1, 1), overlay=True)
        number_size = 11.0
        try:
            number_width = fitz.get_text_length(page_no, fontname="helv", fontsize=number_size)
        except Exception:
            number_width = len(page_no) * number_size * 0.55
        target_page.insert_text((557.5 - number_width, baseline + 0.2), page_no, fontname="helv", fontsize=number_size, color=(1, 1, 1), overlay=True)
    repairs.append(
        {
            "page": 2,
            "rule": "toc_contents_page_uniform_redraw",
            "source": "front contents labels with clipped CJK glyphs",
            "target": "front contents labels redrawn with uniform CJK font and independent page numbers",
            "bbox": [194.4, 200.0, 562.0, 492.0],
            "fill_strategy": "solid_page_background_text_band_redraw",
            "text_policy": "keep_labels_and_page_numbers_as_independent_visual_fields",
            "font_policy": "single_cjk_font_with_larger_labels",
        }
    )
    return repairs

def repair_ai_contents_title(fitz: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_source_han_sans
    if target_page.number + 1 != 2:
        return []
    rect = fitz.Rect(126.0, 118.0, 260.0, 162.0)
    target_page.draw_rect(rect, color=AI_INDEX_FOOTER_BG, fill=AI_INDEX_FOOTER_BG, overlay=True)
    insert_source_han_sans(target_page, (136.0, 149.0), "目录", fontsize=23.5, color=(1, 1, 1))
    return [
        {
            "page": 2,
            "rule": "toc_contents_title_background_repair",
            "source": "Contents title white background artifact",
            "target": "目录",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fontsize": 23.5,
            "fill_strategy": "solid_page_background_redraw",
            "font_policy": "restore_contents_title_as_large_white_cjk_text_on_purple_background",
            "text_policy": "remove_white_title_patch_and_translate_contents_title",
        }
    ]


def insert_right_aligned_header_text(fitz: Any, page: Any, rect: Any, text: str, *, fontsize: float, color: tuple[float, float, float]) -> float:
    from repair_pdf_ai_links import draw_text_run, text_run_length
    size = fontsize
    while size >= 6.0:
        width = text_run_length(text, fontsize=size)
        if width <= rect.width - 2.0:
            draw_text_run(page, max(rect.x0, rect.x1 - width), 36.0, text, fontsize=size, color=color)
            return round(size, 2)
        size -= 0.3
    width = text_run_length(text, fontsize=6.0)
    draw_text_run(page, max(rect.x0, rect.x1 - width), 36.0, text, fontsize=6.0, color=color)
    return 6.0


def repair_ai_running_headers(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import first_line_color, sampled_background_color
    repairs: list[dict[str, Any]] = []
    for page_number, target in AI_HEADER_TRANSLATIONS.items():
        if page_number > doc.page_count:
            continue
        page = doc[page_number - 1]
        cover_rect = fitz.Rect(145, 20, 604, 45)
        header_rect = fitz.Rect(170, 22, 568, 43)
        fill = sampled_background_color(page, cover_rect)
        page.draw_rect(cover_rect, color=fill, fill=fill, overlay=True)
        color = first_line_color(page, fallback=(1, 1, 1) if page_number in {2, 3} else AI_INDEX_FOOTER_BG)
        if page_number in {14, 15}:
            color = AI_INDEX_HEADER_MUTED
        size = insert_right_aligned_header_text(fitz, page, header_rect, target, fontsize=8.0, color=color)
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_running_header_uniform_font_repair",
                "source": "mixed translated/untranslated running header",
                "target": target,
                "bbox": [round(v, 2) for v in [cover_rect.x0, cover_rect.y0, cover_rect.x1, cover_rect.y1]],
                "fontsize": size,
                "fill_strategy": "sampled_header_background_redraw",
                "font_policy": "match_source_running_header_size_unless_width_constrained_with_latin_ai_index_segment",
                "text_policy": "translate_ai_index_running_header_consistently",
            }
        )
    return repairs


def repair_ai_index_cropped_patents_running_headers(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_ai_links import draw_text_run, text_run_length
    from repair_pdf_drawing import normalize_text, sampled_background_color
    repairs: list[dict[str, Any]] = []
    header_targets = [
        (re.compile(r"\b1\.7\b.*\bPATENTS\b", re.I), "1.7 专利 | 研究与开发 | 人工智能指数报告 2026", "1.7 PATENTS running header"),
        (
            re.compile(r"\b1\.8\b.*\bAI\b.*\bAUTHORS\b.*\bINVENTORS\b", re.I),
            "1.8 AI作者与发明者 | 研究与开发 | 人工智能指数报告 2026",
            "1.8 AI AUTHORS AND INVENTORS running header",
        ),
    ]
    for page_index in range(doc.page_count):
        page = doc[page_index]
        header_probe = fitz.Rect(120, 18, 604, 48)
        header_text = normalize_text(page.get_text("text", clip=header_probe))
        matched_target: tuple[str, str] | None = None
        for pattern, target, source_label in header_targets:
            if pattern.search(header_text):
                matched_target = (target, source_label)
                break
        if not matched_target:
            continue
        target, source_label = matched_target
        cover_rect = fitz.Rect(145, 20, 604, 45)
        header_rect = fitz.Rect(170, 22, 568, 43)
        fill = sampled_background_color(page, cover_rect)
        try:
            page.add_redact_annot(cover_rect, fill=fill)
            page.apply_redactions()
        except Exception:
            page.draw_rect(cover_rect, color=fill, fill=fill, overlay=True)
        color = AI_INDEX_HEADER_MUTED
        size = 8.0
        while size >= 5.8 and text_run_length(target, fontsize=size) > header_rect.width - 2.0:
            size -= 0.2
        width = text_run_length(target, fontsize=size)
        draw_text_run(page, max(header_rect.x0, header_rect.x1 - width), 36.0, target, fontsize=size, color=color)
        repairs.append(
            {
                "page": page_index + 1,
                "rule": "ai_index_cropped_patents_running_header_repair",
                "source": source_label,
                "target": target,
                "bbox": [round(v, 2) for v in [cover_rect.x0, cover_rect.y0, cover_rect.x1, cover_rect.y1]],
                "fontsize": round(size, 2),
                "fill_strategy": "sampled_header_background_redraw",
                "font_policy": "match_ai_index_running_header_small_teal_text",
                "text_policy": "translate_cropped_batch_running_header_without_global_short_label_repair",
            }
        )
    return repairs


def repair_ai_page4_closing_and_signature(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_source_han_sans, insert_source_han_serif, pdf_color_to_rgb
    from repair_pdf_nature import _redact_with_fill
    if doc.page_count < 4:
        return []
    page = doc[3]
    repairs: list[dict[str, Any]] = []

    body_rect = fitz.Rect(34.0, 616.0, 550.0, 655.0)
    _redact_with_fill(page, body_rect, (1, 1, 1))
    body_lines = [
        "这些数据并未指向单一趋势。它们反映出这样一个现实：该领域的发展",
        "速度已远远超出周边系统的适应能力。我们鼓励您自行探索并作出判断。",
    ]
    body_color = pdf_color_to_rgb(-15593199, fallback=(0.07, 0.05, 0.07))
    y = 630.6
    for line in body_lines:
        insert_source_han_serif(page, (36.22, y), line, fontsize=10.4, color=body_color)
        y += 15.6
    repairs.append(
        {
            "page": 4,
            "rule": "ai_page4_footer_body_font_repair",
            "source": "The data does not point in a single direction...",
            "target": "\\n".join(body_lines),
            "bbox": [round(v, 2) for v in [body_rect.x0, body_rect.y0, body_rect.x1, body_rect.y1]],
            "fontsize": 10.4,
            "fill_strategy": "white_page_background_structured_redraw",
            "font_policy": "match_page_4_surrounding_body_size_source_han_serif_regular",
            "text_policy": "keep_closing_paragraph_as_body_text_not_microtext",
        }
    )

    signature_rect = fitz.Rect(34.0, 670.0, 360.0, 706.0)
    _redact_with_fill(page, signature_rect, (1, 1, 1))
    page.insert_text((36.0, 684.6), "Yolanda Gil and Raymond Perrault", fontname="helv", fontsize=11.0, color=(0, 0, 0), overlay=True)
    insert_source_han_sans(page, (36.0, 697.9), "《人工智能指数报告》联合主席", fontsize=10.6, color=(0.35, 0.35, 0.35))
    repairs.append(
        {
            "page": 4,
            "rule": "ai_page4_signature_structure_repair",
            "source": "Yolanda Gil and Raymond Perrault Co-chairs | 人工智能指数报告（AI Index Report）",
            "target": "Yolanda Gil and Raymond Perrault\\n《人工智能指数报告》联合主席",
            "bbox": [round(v, 2) for v in [signature_rect.x0, signature_rect.y0, signature_rect.x1, signature_rect.y1]],
            "fontsize": 11.0,
            "fill_strategy": "white_page_background_structured_redraw",
            "font_policy": "keep_names_in_latin_font_and_identity_in_cjk_font",
            "text_policy": "preserve_name_line_and_translate_role_line",
        }
    )
    return repairs


def repair_ai_page9_acknowledgement_width(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_ai_links import draw_text_run
    from repair_pdf_nature import _redact_with_fill
    if doc.page_count < 9:
        return []
    page = doc[8]
    organization_label_patch = fitz.Rect(82.0, 316.0, 174.0, 342.0)
    page.draw_rect(organization_label_patch, color=AI_CONTRIBUTOR_PINK_BG, fill=AI_CONTRIBUTOR_PINK_BG, overlay=True)
    rect = fitz.Rect(34.0, 632.0, 612.0, 724.0)
    _redact_with_fill(page, rect, (1, 1, 1))
    lines = [
        "人工智能指数还要感谢 Jeanina Matias、Nancy King、Carolyn Lehman、Shana Lynch、",
        "Jonathan Mindes 和 Johanna Friedman 在报告编写过程中的帮助；感谢 Christopher Ellis 和",
        "Madeleine Wright 对 AI Index 网站的维护；并感谢 Annie Benisch、Marc Gough、",
        "Caroline Meinhardt、Drew Spence、Casey Weston 和 Daniel Zhang 在本报告推广方面的工作。",
    ]
    baseline = 649.5
    for line in lines:
        draw_text_run(page, 36.2, baseline, line, fontsize=8.25, color=AI_INDEX_BODY_DARK)
        baseline += 15.6
    return [
        {
            "page": 9,
            "rule": "ai_page9_acknowledgement_width_repair",
            "source": "acknowledgement paragraph with spaced Latin names and right overflow",
            "target": "\\n".join(lines),
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fontsize": 8.25,
            "fill_strategy": "white_page_background_structured_redraw",
            "font_policy": "draw_latin_names_with_helvetica_and_cjk_text_with_existing_body_font",
            "text_policy": "remove_letter-spaced_latin_names_and_keep_acknowledgement_as_readable_paragraph",
            "backend_sink_down": "pending",
            "secondary_cleanup": {
                "rule": "ai_page9_organization_label_patch_cleanup",
                "bbox": [round(v, 2) for v in [organization_label_patch.x0, organization_label_patch.y0, organization_label_patch.x1, organization_label_patch.y1]],
                "fill_strategy": "match_contributor_panel_background",
            },
        }
    ]


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
