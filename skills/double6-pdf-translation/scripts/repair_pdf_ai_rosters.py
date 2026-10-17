# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai rosters：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def cover_ai_roster_text(page: Any, x: float, y: float, w: float, h: float, fill: tuple[float, float, float]) -> None:
    page.draw_rect((x, y, x + w, y + h), color=fill, fill=fill, overlay=True)

def draw_ai_roster_label(
    page: Any,
    x: float,
    y: float,
    text: str,
    *,
    fill: tuple[float, float, float] = AI_CONTRIBUTOR_WHITE_BG,
    cover_top_pad: float = 16.0,
    cover_height: float = 42.0,
) -> None:
    from repair_pdf_drawing import insert_source_han_sans
    cover_ai_roster_text(page, x - 1.2, y - cover_top_pad, max(172.0, len(text) * 9.2), cover_height, fill)
    insert_source_han_sans(page, (x, y), text, fontsize=8.8, color=AI_CONTRIBUTOR_ROLE_COLOR)


def draw_ai_roster_card(
    fitz: Any,
    page: Any,
    x: float,
    y: float,
    name: str,
    affiliation_lines: list[str],
    *,
    fill: tuple[float, float, float] = AI_CONTRIBUTOR_WHITE_BG,
    cover_top_pad: float = 11.5,
) -> None:
    from repair_pdf_drawing import insert_source_han_sans
    cover_width = max(165.0, min(190.0, max([len(name) * 5.4 + 18.0, *(len(line) * 5.0 + 18.0 for line in affiliation_lines)])))
    cover_height = 47.0 + max(0, len(affiliation_lines) - 1) * 10.2
    cover_ai_roster_text(page, x - 1.0, y - cover_top_pad, cover_width, cover_height, fill)
    page.insert_text((x, y), name, fontname="helv", fontsize=9.0, color=AI_CONTRIBUTOR_NAME_COLOR, overlay=True)
    line_y = y + 13.6
    for line in affiliation_lines:
        if re.search(r"[\u4e00-\u9fff]", line):
            insert_source_han_sans(page, (x, line_y), line, fontsize=7.4, color=AI_CONTRIBUTOR_AFFILIATION_COLOR)
        else:
            page.insert_text((x, line_y), line, fontname="helv", fontsize=8.1, color=AI_CONTRIBUTOR_AFFILIATION_COLOR, overlay=True)
        line_y += 10.0


def draw_ai_roster_card_multiline_name(
    fitz: Any,
    page: Any,
    x: float,
    y: float,
    name_lines: list[str],
    affiliation_lines: list[str],
    *,
    fill: tuple[float, float, float] = AI_CONTRIBUTOR_WHITE_BG,
    cover_top_pad: float = 11.5,
) -> None:
    from repair_pdf_drawing import insert_source_han_sans
    cover_width = max(
        165.0,
        min(
            190.0,
            max(
                [
                    *(len(line) * 5.4 + 18.0 for line in name_lines),
                    *(len(line) * 5.0 + 18.0 for line in affiliation_lines),
                ]
            ),
        ),
    )
    cover_height = 47.0 + max(0, len(name_lines) - 1) * 12.0 + max(0, len(affiliation_lines) - 1) * 10.2
    cover_ai_roster_text(page, x - 1.0, y - cover_top_pad, cover_width, cover_height, fill)
    line_y = y
    for line in name_lines:
        page.insert_text((x, line_y), line, fontname="helv", fontsize=9.0, color=AI_CONTRIBUTOR_NAME_COLOR, overlay=True)
        line_y += 12.0
    line_y += 1.6
    for line in affiliation_lines:
        if re.search(r"[\u4e00-\u9fff]", line):
            insert_source_han_sans(page, (x, line_y), line, fontsize=7.4, color=AI_CONTRIBUTOR_AFFILIATION_COLOR)
        else:
            page.insert_text((x, line_y), line, fontname="helv", fontsize=8.1, color=AI_CONTRIBUTOR_AFFILIATION_COLOR, overlay=True)
        line_y += 10.0


def copy_ai_roster_background(fitz: Any, source_doc: Any, target_page: Any, page_number: int, rect: Any, *, raster: bool=False) -> bool:
    from repair_pdf_nature import _redact_with_fill
    if page_number > source_doc.page_count:
        raise ValueError('source_roster_page_missing')
    # show_pdf_page 拒绝没有内容流的真实空白页；按同一源区域渲染其白底，
    # 不通过捕获任意异常掩盖损坏文件、错误页号或复制失败。
    if raster or not source_doc[page_number - 1].get_contents():
        pixmap = stable_get_pixmap(source_doc[page_number - 1], matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
        _redact_with_fill(target_page, rect, (1, 1, 1))
        target_page.insert_image(rect, pixmap=pixmap, overlay=True)
    else:
        _redact_with_fill(target_page, rect, (1, 1, 1))
        target_page.show_pdf_page(rect, source_doc, page_number - 1, clip=rect, overlay=True, keep_proportion=False)
    return True


def redraw_ai_page5_steering_roster_text(fitz: Any, page: Any) -> list[dict[str, Any]]:
    """Redraw the AI Index steering committee roster text over the copied source layout."""
    from repair_pdf_drawing import insert_source_han_sans_fake_bold

    repairs: list[dict[str, Any]] = []

    role_specs = [
        (fitz.Rect(34.5, 135.5, 72.0, 154.0), "主席", 35.6, 150.0),
        (fitz.Rect(266.4, 135.5, 326.0, 154.0), "联合主席", 267.2, 150.0),
        (fitz.Rect(35.0, 247.8, 92.0, 267.0), "成员", 36.0, 263.0),
    ]
    for rect, text, x, baseline in role_specs:
        cover_sampled_rect(page, rect)
        insert_source_han_sans_fake_bold(page, (x, baseline), text, fontsize=8.8, color=AI_CONTRIBUTOR_ROLE_COLOR)

    card_specs = [
        (108.5, 181.2, "YOLANDA GIL", ["南加州大学", "信息科学研究所"], AI_CONTRIBUTOR_PINK_BG, 14.0),
        (342.2, 181.2, "RAYMOND PERRAULT", ["SRI International"], AI_CONTRIBUTOR_PINK_BG, 14.0),
        (36.1, 362.0, "RUSS ALTMAN", ["斯坦福大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (152.9, 362.0, "CARLA BRODLEY", ["东北大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (269.3, 362.0, "ERIK BRYNJOLFSSON", ["斯坦福大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (386.1, 362.0, "JACK CLARK", ["Anthropic，OECD"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (502.0, 363.0, "VIRGINIA DIGNUM", ["于默奥大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (36.1, 488.2, "VIPIN KUMAR", ["明尼苏达大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (153.6, 488.2, "JAMES LANDAY", ["斯坦福大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (269.9, 488.2, "TERAH LYONS", ["摩根大通"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (386.6, 488.2, "JAMES MANYIKA", ["谷歌，牛津大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (36.4, 613.4, "VANESSA PARLI", ["斯坦福大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (152.9, 613.4, "YOAV SHOHAM", ["斯坦福大学", "AI21 Labs"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (269.3, 613.4, "ELHAM TABASSI", ["布鲁金斯学会"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (386.6, 613.4, "RUSSELL WALD", ["斯坦福大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (36.4, 738.7, "DAN WELD", ["华盛顿大学"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
        (153.0, 738.7, "TOBY WALSH", ["悉尼新南威尔士大学", "UNSW Sydney"], AI_CONTRIBUTOR_WHITE_BG, 11.5),
    ]
    for x, y, name, affiliation_lines, fill, cover_top_pad in card_specs:
        draw_ai_roster_card(
            fitz,
            page,
            x,
            y,
            name,
            affiliation_lines,
            fill=fill,
            cover_top_pad=cover_top_pad,
        )
    draw_ai_roster_card_multiline_name(
        fitz,
        page,
        502.2,
        488.2,
        ["JUAN CARLOS", "NIEBLES"],
        ["斯坦福大学", "Salesforce"],
        fill=AI_CONTRIBUTOR_WHITE_BG,
        cover_top_pad=11.5,
    )

    repairs.append(
        {
            "page": 5,
            "rule": "ai_contributor_roster_structure_redraw",
            "source": "steering committee roster source layout with malformed translated name/affiliation merges",
            "target": "source portraits and panel backgrounds preserved; role labels and institution lines redrawn with structured Chinese text",
            "bbox": [30.0, 132.0, 590.0, 767.0],
            "fill_strategy": "source_region_copy_then_text_region_structured_redraw",
            "font_policy": "preserve_latin_names_with_helvetica_and_draw_chinese_affiliations_with_source_han_sans",
            "text_policy": "preserve_person_names_in_english_translate_institutions_and_roles",
            "backend_sink_down": "pending",
        }
    )
    return repairs


def repair_ai_contributor_rosters(fitz: Any, source_doc: Any, doc: Any) -> list[dict[str, Any]]:
    from repair_pdf_nature import _redact_with_fill
    repairs: list[dict[str, Any]] = []
    if doc.page_count >= 5:
        page = doc[4]
        rect = fitz.Rect(30.0, 132.0, 590.0, 767.0)
        copied = copy_ai_roster_background(fitz, source_doc, page, 5, rect)
        if not copied:
            _redact_with_fill(page, rect, (1, 1, 1))
        repairs.extend(redraw_ai_page5_steering_roster_text(fitz, page))
    if doc.page_count >= 6:
        page = doc[5]
        rect = fitz.Rect(30.0, 132.0, 590.0, 400.0)
        copied = copy_ai_roster_background(fitz, source_doc, page, 6, rect)
        if not copied:
            _redact_with_fill(page, rect, (1, 1, 1))
        repairs.append(
            {
                "page": 6,
                "rule": "ai_contributor_roster_source_passthrough",
                "source": "staff and researcher roster with portraits, pink panels, and source typography",
                "target": "source roster visual region copied unchanged to avoid image occlusion and color drift",
                "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                "fill_strategy": "source_region_copy_then_targeted_text_redraw" if copied else "white_page_background_structured_redraw",
                "font_policy": "preserve_source_roster_typography_and_colors",
                "text_policy": "passthrough_image_heavy_roster_to_prevent_name_affiliation_merging_without_covering_portraits",
            }
        )
    return repairs


def cover_sampled_rect(page: Any, rect: Any) -> None:
    from repair_pdf_drawing import sampled_background_color
    fill = sampled_background_color(page, rect)
    page.draw_rect(rect, color=fill, fill=fill, overlay=True)


def redraw_ai_contributor_list_heading(
    page: Any,
    rect: Any,
    text: str,
    *,
    x: float,
    baseline: float,
    fontsize: float,
) -> dict[str, Any]:
    from repair_pdf_drawing import insert_source_han_sans
    cover_sampled_rect(page, rect)
    insert_source_han_sans(page, (x, baseline), text, fontsize=fontsize, color=AI_INDEX_DARK_PURPLE)
    return {
        "target": text,
        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
        "fontsize": fontsize,
        "fill_strategy": "sampled_panel_background_redraw",
        "font_policy": "restore_contributor_list_heading_source_like_size",
        "text_policy": "translate_contributor_list_chapter_heading",
    }


def copy_ai_contributor_name_region(fitz: Any, source_doc: Any, target_page: Any, page_number: int, rect: Any) -> dict[str, Any]:
    from repair_pdf_drawing import sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    fill = sampled_background_color(target_page, rect)
    _redact_with_fill(target_page, rect, fill)
    try:
        target_page.show_pdf_page(rect, source_doc, page_number - 1, clip=rect, overlay=True, keep_proportion=False)
        fill_strategy = "source_region_copy_after_clearing_translated_name_layer"
        error = None
    except Exception as exc:
        fill_strategy = "source_region_copy_unavailable_after_clearing_translated_name_layer"
        error = str(exc)
    return {
        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
        "fill_strategy": fill_strategy,
        "font_policy": "preserve_source_english_name_size",
        "text_policy": "preserve_person_names_in_english",
        **({"error": error} if error else {}),
    }


def redraw_ai_contributor_body_lines(
    page: Any,
    rect: Any,
    lines: list[str],
    *,
    x: float,
    first_baseline: float,
    fontsize: float,
    line_gap: float,
) -> dict[str, Any]:
    from repair_pdf_drawing import insert_source_han_serif, sampled_background_color
    from repair_pdf_nature import _redact_with_fill
    fill = sampled_background_color(page, rect)
    _redact_with_fill(page, rect, fill)
    baseline = first_baseline
    for line in lines:
        insert_source_han_serif(page, (x, baseline), line, fontsize=fontsize, color=AI_INDEX_BODY_DARK)
        baseline += line_gap
    return {
        "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
        "fontsize": fontsize,
        "line_gap": line_gap,
        "fill_strategy": "sampled_page_background_multiline_redraw",
        "font_policy": "restore_contributor_body_source_like_readability_size",
        "text_policy": "translate_contributor_acknowledgement_body_preserve_names",
    }


def repair_ai_contributor_list_pages(fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None) -> list[dict[str, Any]]:
    target_pages = pages or {9}
    repairs: list[dict[str, Any]] = []
    if 8 in target_pages and source_doc.page_count >= 8 and doc.page_count >= 8:
        page = doc[7]
        intro_rect = fitz.Rect(34.0, 121.5, 570.0, 155.0)
        intro_meta = redraw_ai_contributor_body_lines(
            page,
            intro_rect,
            [
                "人工智能指数项目谨向以下按章节列明的各位人士致谢，",
                "感谢他们为《2026年人工智能指数报告》提供了数据、分析资料、专业建议及权威评述：",
            ],
            x=36.2,
            first_baseline=136.0,
            fontsize=9.6,
            line_gap=13.2,
        )
        repairs.append({"page": 8, "rule": "ai_contributor_list_body_font_repair", "source": "tiny translated contributor acknowledgement intro", "target": "readable two-line Chinese acknowledgement intro", **intro_meta})
        name_regions = [
            ("Medicine name list", fitz.Rect(318.5, 486.0, 582.5, 637.5)),
            ("Responsible AI name list", fitz.Rect(32.8, 607.5, 282.5, 692.0)),
        ]
        for source, rect in name_regions:
            meta = copy_ai_contributor_name_region(fitz, source_doc, page, 8, rect)
            repairs.append({"page": 8, "rule": "ai_contributor_list_name_passthrough", "source": source, "target": "source English person-name list", **meta})
        heading_specs = [
            (fitz.Rect(34.0, 176.0, 116.0, 197.0), "引言", 35.9, 193.8, 11.0),
            (fitz.Rect(35.0, 252.0, 86.0, 268.0), "第一章", 36.0, 266.0, 9.0),
            (fitz.Rect(35.0, 267.0, 194.0, 288.0), "研究与开发", 36.0, 284.8, 11.0),
            (fitz.Rect(35.5, 441.0, 88.0, 457.0), "第二章", 36.7, 454.7, 9.0),
            (fitz.Rect(35.5, 455.0, 168.0, 477.0), "技术性能", 36.8, 473.9, 11.0),
            (fitz.Rect(35.5, 569.0, 88.0, 586.0), "第三章", 36.0, 583.0, 9.0),
            (fitz.Rect(35.2, 583.0, 174.0, 606.0), "负责任人工智能", 36.0, 602.0, 11.0),
            (fitz.Rect(320.5, 176.0, 374.0, 193.0), "第四章", 321.5, 191.0, 9.0),
            (fitz.Rect(320.8, 193.5, 382.0, 214.0), "经济", 321.7, 211.2, 11.0),
            (fitz.Rect(320.5, 340.5, 374.0, 358.0), "第五章", 321.5, 356.0, 9.0),
            (fitz.Rect(320.8, 358.0, 382.0, 378.0), "科学", 321.7, 375.8, 11.0),
            (fitz.Rect(320.5, 444.5, 374.0, 461.5), "第六章", 321.5, 459.0, 9.0),
            (fitz.Rect(320.8, 462.0, 382.0, 483.0), "医学", 321.7, 480.4, 11.0),
            (fitz.Rect(320.5, 649.0, 374.0, 666.0), "第七章", 321.5, 663.3, 9.0),
            (fitz.Rect(320.8, 666.5, 382.0, 686.5), "教育", 321.7, 684.0, 11.0),
        ]
        for rect, text, x, baseline, size in heading_specs:
            meta = redraw_ai_contributor_list_heading(page, rect, text, x=x, baseline=baseline, fontsize=size)
            repairs.append({"page": 8, "rule": "ai_contributor_list_heading_font_repair", "source": "small translated contributor heading", **meta})
    if 9 in target_pages and source_doc.page_count >= 9 and doc.page_count >= 9:
        page = doc[8]
        thanks_rect = fitz.Rect(34.0, 636.0, 586.0, 682.0)
        thanks_meta = redraw_ai_contributor_body_lines(
            page,
            fitz.Rect(34.0, 636.0, 586.0, 698.0),
            [
                "人工智能指数（AI Index）还要感谢 Jeanina Matias、Nancy King、Carolyn Lehman、Shana Lynch、Jonathan Mindes 和",
                "Johanna Friedman 在报告编写过程中的帮助；感谢 Christopher Ellis 与 Madeleine Wright 对人工智能指数网站的维护工作；",
                "同时感谢 Annie Benisch、Marc Gough、Caroline Meinhardt、Drew Spence、Casey Weston 以及 Daniel Zhang",
                "为宣传推广该报告所付出的努力。",
            ],
            x=36.0,
            first_baseline=651.0,
            fontsize=8.8,
            line_gap=12.4,
        )
        repairs.append({"page": 9, "rule": "ai_contributor_list_body_font_repair", "source": "small translated final acknowledgement paragraph", "target": "larger mixed Chinese-English acknowledgement paragraph", **thanks_meta})
        rect = fitz.Rect(322.0, 374.0, 555.0, 405.0)
        meta = copy_ai_contributor_name_region(fitz, source_doc, page, 9, rect)
        repairs.append({"page": 9, "rule": "ai_contributor_list_name_passthrough", "source": "McKinsey & Company person-name list", "target": "source English person-name list", **meta})
        heading_specs = [
            (fitz.Rect(35.0, 91.0, 88.0, 107.0), "第八章", 36.1, 105.2, 9.0),
            (fitz.Rect(35.0, 108.0, 190.0, 131.0), "政策与治理", 36.2, 127.0, 11.0),
            (fitz.Rect(325.0, 91.0, 380.0, 107.0), "第九章", 326.1, 105.2, 9.0),
            (fitz.Rect(325.0, 108.0, 440.0, 131.0), "公众观点", 326.1, 127.0, 11.0),
            (fitz.Rect(62.5, 322.0, 122.0, 342.0), "机构", 63.9, 339.2, 11.0),
        ]
        for rect, text, x, baseline, size in heading_specs:
            meta = redraw_ai_contributor_list_heading(page, rect, text, x=x, baseline=baseline, fontsize=size)
            repairs.append({"page": 9, "rule": "ai_contributor_list_heading_font_repair", "source": "small or untranslated contributor heading", **meta})
    return repairs

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
