# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf ai economy overview：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def repair_ai_index_economy_contents_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 AI Index 第 4 章 Economy 目录页中未进入翻译链的固定目录项。"""
    from repair_pdf_drawing import normalize_text, page_lines, replace_rect_source_han, sampled_background_color

    repairs: list[dict[str, Any]] = []

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

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        if not (
            has_line_in_region(source_page, "Contents", y0=95.0, y1=130.0, x0=20.0, x1=120.0)
            and has_line_in_region(source_page, "4.1 Year in Review: 2025", y0=155.0, y1=185.0, x0=40.0, x1=220.0)
        ):
            continue
        rect = fitz.Rect(48.0, 160.0, 224.0, 183.0)
        meta = replace_rect_source_han(page, rect, "4.1 年度回顾：2025", fontsize=8.6, fill=sampled_background_color(page, rect), color=(1, 1, 1))
        repairs.append(
            {
                "page": page_number,
                "rule": "ai_index_economy_contents_year_review_label_repair",
                "source": "4.1 Year in Review: 2025",
                "target": "4.1 年度回顾：2025",
                **meta,
                "font_policy": "source_han_sans_fixed_economy_contents_label",
                "text_policy": "translate_fixed_toc_entry_preserve_page_number_and_row_geometry",
            }
        )
    return repairs


def repair_ai_index_economy_timeline_visible_labels(
    fitz: Any, source_doc: Any, doc: Any, *, pages: set[int] | None = None
) -> list[dict[str, Any]]:
    """修复 AI Index Economy 4.1 时间线页的固定标题、页眉和类别标签。"""
    from repair_pdf_drawing import insert_source_han_sans, normalize_text, page_lines
    from repair_pdf_nature import _redact_with_fill

    repairs: list[dict[str, Any]] = []

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

    def has_exact_line_in_region(page: Any, needle: str, *, y0: float, y1: float, x0: float = 0.0, x1: float = 612.0) -> bool:
        normalized_needle = normalize_text(needle)
        for row in page_lines(page):
            text = normalize_text(row.get("text") or "")
            bbox = row.get("bbox")
            if text != normalized_needle or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
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
                "font_policy": "source_han_sans_fixed_economy_timeline_label",
                "text_policy": policy,
            }
        )

    def fixed_line(
        page: Any,
        page_number: int,
        rect_values: list[float],
        point: tuple[float, float],
        target: str,
        rule: str,
        *,
        fontsize: float,
        source: str,
        fill: tuple[float, float, float],
        color: tuple[float, float, float],
        policy: str,
    ) -> None:
        rect = fitz.Rect(rect_values)
        _redact_with_fill(page, rect, fill)
        insert_source_han_sans(page, point, target, fontsize=fontsize, color=color)
        add_meta(
            page_number,
            rule,
            source,
            target,
            {"bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]], "fontsize": fontsize, "fill_strategy": "fixed_fill_then_source_han_line"},
            policy=policy,
        )

    timeline_bg = (12 / 255, 110 / 255, 108 / 255)
    label_colors = {
        "INVESTMENT": (0.44, 0.82, 0.9),
        "MILESTONE": (0.92, 0.54, 0.83),
        "ACQUISITION": (0.55, 0.78, 0.18),
        "FUNDING": (1.0, 0.86, 0.0),
        "DEAL": (1.0, 0.32, 0.08),
        "PARTNERSHIP": (0.44, 0.82, 0.9),
    }
    label_targets = {
        "INVESTMENT": "投资",
        "MILESTONE": "里程碑",
        "ACQUISITION": "收购",
        "FUNDING": "融资",
        "DEAL": "交易",
        "PARTNERSHIP": "合作",
    }

    page_limit = min(getattr(source_doc, "page_count", 0), getattr(doc, "page_count", 0))
    for page_index in range(page_limit):
        page_number = page_index + 1
        if pages and page_number not in pages:
            continue
        source_page = source_doc[page_index]
        page = doc[page_index]
        has_timeline_title = has_line_in_region(source_page, "4.1 Year in Review: 2025", y0=55.0, y1=115.0, x0=25.0, x1=410.0)
        has_timeline_header = has_line_in_region(source_page, "WHAT", y0=20.0, y1=45.0, x0=180.0, x1=590.0) and has_line_in_region(
            source_page, "TIMELINE", y0=20.0, y1=45.0, x0=180.0, x1=590.0
        )
        if not (has_timeline_title or has_timeline_header):
            continue
        if has_timeline_title:
            title_rect = fitz.Rect(34.0, 60.0, 398.0, 103.5)
            stray_year_rect = fitz.Rect(34.0, 98.0, 76.0, 138.0)
            _redact_with_fill(page, title_rect, timeline_bg)
            _redact_with_fill(page, stray_year_rect, timeline_bg)
            insert_source_han_sans(page, (36.0, 96.5), "4.1 年度回顾：2025", fontsize=25.0, color=(1, 1, 1))
            add_meta(
                page_number,
                "ai_index_economy_timeline_title_repair",
                "4.1 Year in Review: 2025",
                "4.1 年度回顾：2025",
                {"bbox": [34.0, 60.0, 398.0, 138.0], "fontsize": 25.0, "fill_strategy": "split_timeline_green_regions_then_source_han_line"},
                policy="translate_economy_timeline_title_as_single_readable_line",
            )
        if has_timeline_header:
            rect = fitz.Rect(216.0, 27.0, 578.0, 39.5)
            _redact_with_fill(page, rect, timeline_bg)
            insert_source_han_sans(page, (224.0, 36.8), "4.1 2025年时间线 | 经济 | 人工智能指数报告 2026", fontsize=4.9, color=(1, 1, 1))
            add_meta(
                page_number,
                "ai_index_economy_timeline_running_header_repair",
                "4.1 WHAT'S NEW IN 2025: A TIMELINE | ECONOMY | AI INDEX REPORT 2026",
                "4.1 2025年时间线 | 经济 | 人工智能指数报告 2026",
                {"bbox": [216.0, 27.0, 578.0, 39.5], "fontsize": 4.9, "fill_strategy": "fixed_timeline_green_region_then_source_han_line"},
                policy="translate_economy_timeline_running_header_consistently",
            )
        for row in page_lines(source_page):
            source = normalize_text(row.get("text") or "")
            if source not in label_targets:
                continue
            bbox = row.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
            except Exception:
                continue
            if x0 < 490.0 or not (90.0 <= y0 <= 720.0):
                continue
            target = label_targets[source]
            rect_values = [max(490.0, x0 - 3.0), y0 - 1.0, min(562.0, x1 + 4.0), y1 + 2.0]
            point = (rect_values[0] + 4.0, y1 - 1.0)
            fixed_line(
                page,
                page_number,
                rect_values,
                point,
                target,
                "ai_index_economy_timeline_category_label_repair",
                fontsize=6.2,
                source=source,
                fill=timeline_bg,
                color=label_colors[source],
                policy="translate_economy_timeline_category_label_preserve_color_and_row_geometry",
            )
    return repairs


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
