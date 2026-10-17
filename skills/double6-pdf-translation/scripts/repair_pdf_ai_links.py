# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai links：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def source_page_numbers(source_page: Any) -> dict[str, dict[str, Any]]:
    from repair_pdf_drawing import normalize_text, page_lines
    numbers: dict[str, dict[str, Any]] = {}
    for row in page_lines(source_page):
        text = normalize_text(row["text"])
        bbox = row.get("bbox")
        if not re.fullmatch(r"\d{1,3}", text) or not bbox:
            continue
        y0 = float(bbox[1])
        if not 190 <= y0 <= 500:
            continue
        numbers.setdefault(text, row)
    return numbers


def target_toc_number_rows(target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import normalize_text
    rows: list[dict[str, Any]] = []
    for block in target_page.get_text("dict").get("blocks", []):
        if not isinstance(block, dict):
            continue
        for line in block.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            spans = [span for span in line.get("spans", []) or [] if isinstance(span, dict)]
            text = "".join(str(span.get("text") or "") for span in spans)
            normalized = normalize_text(text)
            match = re.search(r"[\x03\s](\d{1,3})$", normalized)
            if not match:
                continue
            bbox = line.get("bbox")
            if not bbox or not (190 <= float(bbox[1]) <= 500):
                continue
            number = match.group(1)
            number_spans = [span for span in spans if re.search(rf"(?:\x03|\s)?{re.escape(number)}$", str(span.get("text") or ""))]
            if not number_spans:
                continue
            rows.append({"text": normalized, "number": number, "number_span": number_spans[-1], "line": line})
    return rows


def repair_ai_contents_page_numbers(fitz: Any, source_page: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import draw_solid_cover
    repairs: list[dict[str, Any]] = []
    source_numbers = source_page_numbers(source_page)
    for row in target_toc_number_rows(target_page):
        number = row["number"]
        source_row = source_numbers.get(number)
        if not source_row:
            continue
        source_bbox = source_row.get("bbox")
        number_span = row["number_span"]
        number_bbox = number_span.get("bbox")
        if not source_bbox or not number_bbox:
            continue
        old_rect = fitz.Rect([float(value) for value in number_bbox[:4]])
        old_rect.x0 = max(0, old_rect.x0 - 2.0)
        old_rect.y0 = max(0, old_rect.y0 - 1.0)
        old_rect.x1 = min(target_page.rect.width, old_rect.x1 + 2.0)
        old_rect.y1 = min(target_page.rect.height, old_rect.y1 + 1.0)
        draw_solid_cover(target_page, old_rect)
        source_rect = fitz.Rect([float(value) for value in source_bbox[:4]])
        fontsize = float(source_row.get("size") or 11.0)
        baseline = source_rect.y1 - max(2.0, fontsize * 0.23)
        target_page.insert_text((source_rect.x0, baseline), number, fontname="helv", fontsize=fontsize, color=(1, 1, 1), overlay=True)
        repairs.append(
            {
                "page": 2,
                "rule": "toc_page_number_passthrough_repair",
                "source": row["text"],
                "target": number,
                "bbox": [round(v, 2) for v in [source_rect.x0, source_rect.y0, source_rect.x1, source_rect.y1]],
                "old_bbox": [round(v, 2) for v in [old_rect.x0, old_rect.y0, old_rect.x1, old_rect.y1]],
                "target_bbox": [round(v, 2) for v in [source_rect.x0, source_rect.y0, source_rect.x1, source_rect.y1]],
                "text_policy": "page_number_passthrough_original_position",
                "font_policy": "preserve_source_toc_page_number_size_color",
                "fill_strategy": "solid_page_background_patch",
            }
        )
    return repairs


def mixed_font_runs(text: str) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    for part in re.findall(r"[A-Za-z0-9][A-Za-z0-9 .:/_-]*|[^A-Za-z0-9]+", text):
        if not part:
            continue
        font = "helv" if re.match(r"^[A-Za-z0-9]", part) else "china-s"
        runs.append((part, font))
    return runs

def draw_text_run(page: Any, x: float, baseline: float, text: str, *, fontsize: float, color: tuple[float, float, float]) -> float:
    fitz_mod = __import__("fitz")
    current_x = x
    for part, fontname in mixed_font_runs(text):
        page.insert_text((current_x, baseline), part, fontname=fontname, fontsize=fontsize, color=color, overlay=True)
        try:
            current_x += float(fitz_mod.get_text_length(part, fontname=fontname, fontsize=fontsize))
        except Exception:
            current_x += len(part) * fontsize
    return current_x

def text_run_length(text: str, *, fontsize: float) -> float:
    fitz_mod = __import__("fitz")
    total = 0.0
    for part, fontname in mixed_font_runs(text):
        try:
            total += float(fitz_mod.get_text_length(part, fontname=fontname, fontsize=fontsize))
        except Exception:
            total += len(part) * fontsize
    return total

def draw_linked_sentence(
    fitz: Any,
    page: Any,
    *,
    x: float,
    baseline: float,
    prefix: str,
    link_text: str,
    suffix: str,
    uri: str,
    fontsize: float = 8.0,
) -> dict[str, Any]:
    text_color = (1, 1, 1)
    link_start = draw_text_run(page, x, baseline, prefix, fontsize=fontsize, color=text_color)
    link_end = draw_text_run(page, link_start, baseline, link_text, fontsize=fontsize, color=LINK_BLUE)
    draw_text_run(page, link_end, baseline, suffix, fontsize=fontsize, color=text_color)
    underline_y = baseline + 1.0
    page.draw_line((link_start, underline_y), (link_end, underline_y), color=LINK_BLUE, width=0.5, overlay=True)
    link_rect = fitz.Rect(link_start, baseline - fontsize * 1.3, link_end, baseline + fontsize * 0.45)
    page.insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": uri})
    return {
        "uri": uri,
        "link_text": link_text,
        "link_bbox": [round(v, 2) for v in [link_rect.x0, link_rect.y0, link_rect.x1, link_rect.y1]],
    }

def repair_ai_footer_links(fitz: Any, source_page: Any, target_page: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import draw_solid_cover
    source_links = source_page.get_links()
    hai_uri = next((str(item.get("uri")) for item in source_links if "hai.stanford.edu" in str(item.get("uri") or "")), "http://hai.stanford.edu")
    ai100_uri = next((str(item.get("uri")) for item in source_links if "ai100.stanford.edu" in str(item.get("uri") or "")), "https://ai100.stanford.edu/")
    cover = fitz.Rect(190, 678, 566, 760)
    draw_solid_cover(target_page, cover)
    size = 9.0
    white = (1, 1, 1)
    draw_text_run(target_page, 198.0, 696.0, "人工智能指数（AI Index）是由斯坦福以人为本人工智能研究院（HAI）", fontsize=size, color=white)
    draw_text_run(target_page, 198.0, 708.0, "牵头开展的独立项目。", fontsize=size, color=white)
    link1_rect = fitz.Rect(360.0, 684.8, 548.0, 699.6)
    target_page.insert_link({"kind": fitz.LINK_URI, "from": link1_rect, "uri": hai_uri})
    draw_text_run(target_page, 198.0, 733.6, "人工智能指数（AI Index）这一概念最初是在“人工智能百年研究（AI100）”", fontsize=size, color=white)
    draw_text_run(target_page, 198.0, 745.6, "项目中被提出的。", fontsize=size, color=white)
    link2_rect = fitz.Rect(408.0, 722.4, 558.0, 737.2)
    target_page.insert_link({"kind": fitz.LINK_URI, "from": link2_rect, "uri": ai100_uri})
    return [
        {
            "page": 2,
            "rule": "footer_link_style_and_uri_repair",
            "source": "Stanford Institute for Human-Centered Artificial Intelligence (HAI)",
            "target": "斯坦福以人为本人工智能研究院（HAI）",
            "bbox": [192, 682, 560, 718],
            "fill_strategy": "solid_page_background_patch",
            "fontsize": size,
            "font_policy": "restore_source_footer_body_size_with_line_wrap",
            "text_policy": "restore_link_color_uri_and_source_like_body_size_without_long_underlines",
            "uri": hai_uri,
            "link_text": "斯坦福以人为本人工智能研究院（HAI）",
            "link_bbox": [round(v, 2) for v in [link1_rect.x0, link1_rect.y0, link1_rect.x1, link1_rect.y1]],
        },
        {
            "page": 2,
            "rule": "footer_link_style_and_uri_repair",
            "source": "One Hundred Year Study on Artificial Intelligence (AI100)",
            "target": "人工智能百年研究（AI100）",
            "bbox": [192, 724, 560, 758],
            "fill_strategy": "solid_page_background_patch",
            "fontsize": size,
            "font_policy": "restore_source_footer_body_size_with_line_wrap",
            "text_policy": "restore_link_color_uri_and_source_like_body_size_without_long_underlines",
            "uri": ai100_uri,
            "link_text": "人工智能百年研究（AI100）",
            "link_bbox": [round(v, 2) for v in [link2_rect.x0, link2_rect.y0, link2_rect.x1, link2_rect.y1]],
        },
    ]


def draw_ai_serif_segments(
    fitz: Any,
    page: Any,
    *,
    x: float,
    baseline: float,
    segments: list[tuple[str, tuple[float, float, float]]],
    fontsize: float,
) -> float:
    from repair_pdf_drawing import cjk_text_width, insert_source_han_serif
    cursor = x
    for text, color in segments:
        for part, fontname in mixed_font_runs(text):
            if fontname == "helv":
                page.insert_text((cursor, baseline), part, fontname="helv", fontsize=fontsize, color=color, overlay=True)
                try:
                    cursor += float(fitz.get_text_length(part, fontname="helv", fontsize=fontsize))
                except Exception:
                    cursor += len(part) * fontsize * 0.48
            else:
                insert_source_han_serif(page, (cursor, baseline), part, fontsize=fontsize, color=color)
                cursor += cjk_text_width(fitz, part, fontsize=fontsize)
    return cursor


def repair_ai_page6_citation_passthrough(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_nature import _redact_with_fill
    if source_doc.page_count < 6 or doc.page_count < 6:
        return []
    page = doc[5]
    rect = fitz.Rect(34.0, 468.0, 580.0, 541.5)
    _redact_with_fill(page, rect, AI_INDEX_FOOTER_BG)
    lines = [
        "Sha Sajadieh, Loredana Fattorini, Raymond Perrault, Yolanda Gil, Vanessa Parli, Lapo Santarlasci, Juan Pava,",
        "Nestor Maslej, Russ Altman, Erik Brynjolfsson, Carla Brodley, Jack Clark, Virginia Dignum, Vipin Kumar,",
        "James Landay, Terah Lyons, James Manyika, Juan Carlos Niebles, Yoav Shoham, Elham Tabassi, Russel",
        "Wald, Toby Walsh, Dan Weld. \"The AI Index 2026 Annual Report,\" AI Index Steering Committee, Institute for",
        "Human-Centered AI, Stanford University, Stanford, CA, April 2026.",
    ]
    baseline = 481.8
    for line in lines:
        page.insert_text((36.2, baseline), line, fontname="helv", fontsize=8.8, color=(1, 1, 1), overlay=True)
        baseline += 12.4
    return [
        {
            "page": 6,
            "rule": "ai_page6_citation_passthrough_repair",
            "source": "Sha Sajadieh ... The AI Index 2026 Annual Report citation block",
            "target": "source English citation block",
            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
            "fill_strategy": "solid_footer_background_structured_redraw",
            "text_policy": "preserve_person_names_and_english_citation_untranslated",
            "font_policy": "preserve_source_citation_font_size_and_color",
        }
    ]


def repair_ai_page6_link_lines(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_nature import _redact_with_fill
    if doc.page_count < 6:
        return []
    page = doc[5]
    repairs: list[dict[str, Any]] = []
    white = (1, 1, 1)

    license_rect = fitz.Rect(32.0, 546.0, 570.0, 580.0)
    _redact_with_fill(page, license_rect, AI_INDEX_FOOTER_BG)
    draw_ai_serif_segments(
        fitz,
        page,
        x=36.3,
        baseline=560.8,
        fontsize=8.4,
        segments=[("《2026年人工智能指数年度报告》由斯坦福大学发布，采用", white)],
    )
    draw_ai_serif_segments(
        fitz,
        page,
        x=36.3,
        baseline=573.0,
        fontsize=8.4,
        segments=[("Attribution-NoDerivatives 4.0 International", LINK_BLUE), (" 许可协议。", white)],
    )
    repairs.append(
        {
            "page": 6,
            "rule": "ai_page6_link_line_repair",
            "source": "license link with long underline/trailing blank visual line",
            "target": "license line redrawn without underline graphics",
            "bbox": [round(v, 2) for v in [license_rect.x0, license_rect.y0, license_rect.x1, license_rect.y1]],
            "fontsize": 8.4,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_footer_link_line_size_color",
            "text_policy": "preserve_blue_link_text_without_long_underlines",
        }
    )

    data_rect = fitz.Rect(50.0, 692.0, 566.0, 718.0)
    _redact_with_fill(page, data_rect, AI_INDEX_FOOTER_BG)
    draw_ai_serif_segments(
        fitz,
        page,
        x=54.5,
        baseline=711.0,
        fontsize=9.1,
        segments=[
            ("原始数据与图表：报告中所有公开数据及高分辨率图表均可从 ", white),
            ("Google Drive", LINK_BLUE),
            (" 获取。", white),
        ],
    )
    repairs.append(
        {
            "page": 6,
            "rule": "ai_page6_link_line_repair",
            "source": "Google Drive link with long underline/trailing blank visual line",
            "target": "Google Drive line redrawn without underline graphics",
            "bbox": [round(v, 2) for v in [data_rect.x0, data_rect.y0, data_rect.x1, data_rect.y1]],
            "fontsize": 9.1,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_footer_link_line_size_color",
            "text_policy": "preserve_blue_link_text_without_long_underlines",
        }
    )

    tool_rect = fitz.Rect(50.0, 724.0, 575.0, 755.0)
    _redact_with_fill(page, tool_rect, AI_INDEX_FOOTER_BG)
    draw_ai_serif_segments(
        fitz,
        page,
        x=54.5,
        baseline=740.0,
        fontsize=8.5,
        segments=[
            ("全球人工智能活力评估工具", LINK_BLUE),
            ("：该工具可用于对比36个国家的人工智能生态系统。该工具将于2026年底完成更新。", white),
        ],
    )
    repairs.append(
        {
            "page": 6,
            "rule": "ai_page6_link_line_repair",
            "source": "Global AI Vibrancy Tool link with long underline/trailing blank visual line",
            "target": "Global AI Vibrancy Tool line redrawn without underline graphics",
            "bbox": [round(v, 2) for v in [tool_rect.x0, tool_rect.y0, tool_rect.x1, tool_rect.y1]],
            "fontsize": 8.5,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_footer_link_line_size_color",
            "text_policy": "preserve_blue_link_text_without_long_underlines",
        }
    )
    return repairs


def repair_ai_page17_text_styles(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import cjk_text_width, insert_source_han_serif, insert_source_han_serif_fake_bold
    from repair_pdf_nature import _redact_with_fill
    if doc.page_count < 17:
        return []
    page = doc[16]
    repairs: list[dict[str, Any]] = []
    white = (1, 1, 1)

    intro_rect = fitz.Rect(34.0, 262.0, 570.0, 296.0)
    _redact_with_fill(page, intro_rect, white)
    intro_lines = [
        "本章主要探讨研究与开发流程及其相关输入要素。下一章将专门论述技术表现，",
        "详细分析各类模型的能力以及它们在各项基准测试中的表现。",
    ]
    for baseline, text in zip([280.6, 293.8], intro_lines, strict=True):
        insert_source_han_serif(page, (36.8, baseline), text, fontsize=11.0, color=AI_INDEX_BODY_DARK)
    repairs.append(
        {
            "page": 17,
            "rule": "ai_page17_intro_paragraph_font_repair",
            "source": "This chapter focuses on the research and development pipeline and its inputs.",
            "target": "本章主要探讨研究与开发流程及其相关输入要素。",
            "bbox": [round(v, 2) for v in [intro_rect.x0, intro_rect.y0, intro_rect.x1, intro_rect.y1]],
            "fontsize": 11.0,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_body_11pt_and_color",
            "text_policy": "translate_intro_paragraph_without_downscaling",
        }
    )

    heading_rect = fitz.Rect(32.0, 360.0, 230.0, 391.0)
    _redact_with_fill(page, heading_rect, white)
    heading = "按国家/地区归属划分"
    insert_source_han_serif_fake_bold(page, (36.9, 384.5), heading, fontsize=15.0, color=AI_INDEX_TEAL)
    superscript_x = 36.9 + cjk_text_width(fitz, heading, fontsize=15.0) + 1.2
    insert_source_han_serif(page, (superscript_x, 374.8), "2", fontsize=7.4, color=AI_INDEX_TEAL)
    repairs.append(
        {
            "page": 17,
            "rule": "ai_page17_national_affiliation_heading_repair",
            "source": "By National Affiliation2",
            "target": "按国家/地区归属划分²",
            "bbox": [round(v, 2) for v in [heading_rect.x0, heading_rect.y0, heading_rect.x1, heading_rect.y1]],
            "fontsize": 15.0,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_subheading_size_color_and_bold_weight",
            "text_policy": "translate_subheading_preserve_superscript_marker",
        }
    )

    footnote_rect = fitz.Rect(34.0, 681.0, 584.0, 760.5)
    _redact_with_fill(page, footnote_rect, white)
    page.draw_line((36.9, 681.7), (86.0, 681.7), color=AI_INDEX_BODY_DARK, width=0.8, overlay=True)
    size = 8.0
    x = 36.9
    line1_prefix = "1 各类新发布和历史模型会不断加入 "
    line1_link = "Epoch AI"
    line1_suffix = " 数据库，因此本年度《人工智能指数报告》中统计的模型年度数量"
    link_start = draw_ai_serif_segments(
        fitz,
        page,
        x=x,
        baseline=691.8,
        fontsize=size,
        segments=[(line1_prefix, AI_INDEX_BODY_DARK)],
    )
    link_end = draw_ai_serif_segments(
        fitz,
        page,
        x=link_start,
        baseline=691.8,
        fontsize=size,
        segments=[(line1_link, AI_INDEX_FOOTNOTE_LINK)],
    )
    draw_ai_serif_segments(
        fitz,
        page,
        x=link_end,
        baseline=691.8,
        fontsize=size,
        segments=[(line1_suffix, AI_INDEX_BODY_DARK)],
    )
    page.draw_line((link_start, 693.3), (link_end, 693.3), color=AI_INDEX_FOOTNOTE_LINK, width=0.35, overlay=True)
    footnote_lines = [
        (702.0, "可能与去年报告中的数值略有差异。本次数据基于 2026 年 4 月 22 日采集的快照。"),
        (718.4, "2 若某机器学习模型的论文作者中至少有一人隶属于某国机构，则该模型归入该国家；若作者来自多个国家，"),
        (728.6, "可能出现重复统计。"),
        (745.0, "3 该图表展示特定地理区域的模型发布情况；更全面的各国模型发布数据将出现在即将推出的"),
        (755.2, "人工智能指数全球活跃度工具中。"),
    ]
    for baseline, text in footnote_lines:
        insert_source_han_serif(page, (x, baseline), text, fontsize=size, color=AI_INDEX_BODY_DARK)
    repairs.append(
        {
            "page": 17,
            "rule": "ai_page17_footnote_style_repair",
            "source": "page 17 footnotes with first line undersized and misplaced underline",
            "target": "page 17 footnotes redrawn with uniform 8pt body and scoped Epoch AI underline",
            "bbox": [round(v, 2) for v in [footnote_rect.x0, footnote_rect.y0, footnote_rect.x1, footnote_rect.y1]],
            "fontsize": size,
            "fill_strategy": "solid_page_background_patch",
            "font_policy": "match_source_footnote_8pt_across_all_footnotes",
            "text_policy": "remove_errant_x_and_restrict_underline_to_epoch_ai_link_text",
        }
    )
    return repairs


def repair_ai_page19_sector_heading_and_orphan(fitz: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_drawing import insert_source_han_serif_fake_bold, sampled_background_color
    if doc.page_count < 19:
        return []
    page = doc[18]
    repairs: list[dict[str, Any]] = []

    heading_rect = fitz.Rect(34.0, 94.0, 240.0, 122.0)
    fill = sampled_background_color(page, heading_rect)
    page.draw_rect(heading_rect, color=fill, fill=fill, overlay=True)
    heading = "按部门与组织划分"
    insert_source_han_serif_fake_bold(page, (36.2, 116.5), heading, fontsize=15.0, color=AI_INDEX_TEAL)
    repairs.append(
        {
            "page": 19,
            "rule": "ai_page19_sector_heading_and_orphan_repair",
            "source": "By Sector and Organization",
            "target": heading,
            "bbox": [round(v, 2) for v in [heading_rect.x0, heading_rect.y0, heading_rect.x1, heading_rect.y1]],
            "fontsize": 15.0,
            "fill_strategy": "sampled_region_background",
            "font_policy": "restore_source_subheading_size_color_and_weight",
            "text_policy": "translate_missing_sector_organization_subheading",
        }
    )

    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
