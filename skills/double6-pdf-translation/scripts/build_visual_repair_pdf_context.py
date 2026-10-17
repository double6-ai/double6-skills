# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""build_visual_repair_pdf的共享依赖与固定规则；业务处理按职责模块加载。"""
from __future__ import annotations

from stable_page_raster import stable_get_pixmap

import argparse

import json

import re

import shutil

from pathlib import Path

from typing import Any

import build_babeldoc_il_layout_map

import layout_role_policy

import visual_layout

CHART_LABEL_FALLBACKS = {
    "Number of notable AI models": "知名AI模型数",
    "Source: Epoch AI": "来源：Epoch AI",
    "Chart: 2026 AI Index report": "图表：2026 年人工智能指数报告",
    "Notable AI models (% of total)": "知名AI模型（占总数百分比）",
    "By National Affiliation": "按国家/地区归属划分",
    "By National Affiliation2": "按国家/地区归属划分",
    "By Sector and Organization": "按部门与组织划分",
    "Figure 1.1.1": "图 1.1.1",
    "Figure 1.1.13": "图 1.1.1",
    "Figure 1.1.2": "图 1.1.2",
    "Figure 1.1.3": "图 1.1.3",
    "Figure 1.1.4": "图 1.1.4",
    "Figure 1.1.5": "图 1.1.5",
    "Figure 1.1.6": "图 1.1.6",
    "Figure 1.1.7": "图 1.1.7",
}

AI_INSTITUTION_REPAIRS = {
    "Stanford University": "斯坦福大学",
    "SRI International": "SRI International",
    "University of Oxford": "牛津大学",
    "Information Sciences Institute": "信息科学研究所",
    "University of Southern California": "南加州大学",
    "Northeastern University": "东北大学",
    "University of Minnesota": "明尼苏达大学",
}

LINK_BLUE = (0.09, 0.882, 0.988)

AI_INDEX_FOOTER_BG = (0.29399558901786804, 0.13798733055591583, 0.2849927544593811)

REPO_ROOT = __import__("runtime_paths").workspace_root()

SOURCE_HAN_SERIF_CN_REGULAR = __import__("runtime_paths").engine_home() / ".cache/babeldoc/fonts/SourceHanSerifCN-Regular.ttf"

SOURCE_HAN_SANS_CN_REGULAR = __import__("runtime_paths").engine_home() / ".cache/babeldoc/fonts/SourceHanSansCN-Regular.ttf"

AI_INDEX_CHART_LABEL_MAX_HITS = 12

AI_INDEX_CHART_LABEL_BROAD_SOURCE_BLOCKLIST = {
    "Audio",
    "Classifiers",
    "Datasets",
    "Human",
    "Japan",
    "Models",
    "Other",
    "Others",
    "PATENTS",
    "Patents",
    "Stars",
}

RISKY_REPAIR_RULES = {
    "toc_row_visible_repair",
    "toc_contents_page_uniform_redraw",
    "toc_page_structured_redraw",
    "ai_page4_footer_body_font_repair",
    "ai_page4_signature_structure_repair",
    "ai_page9_acknowledgement_width_repair",
    "ai_page6_citation_passthrough_repair",
    "ai_page6_link_line_repair",
    "ai_contributor_list_body_font_repair",
    "ai_contributor_list_heading_font_repair",
    "ai_contributor_list_name_passthrough",
    "ai_contributor_roster_structure_redraw",
    "ai_contributor_roster_source_passthrough",
    "ai_page17_footnote_style_repair",
    "ai_page17_intro_paragraph_font_repair",
    "ai_page17_chart_axis_label_repair",
    "ai_page18_20_chart_axis_label_repair",
    "ai_index_chart_label_source_bbox_repair",
    "ai_index_chart_label_text_layer_repair",
    "ai_index_economy_corporate_ai_adoption_chart_label_repair",
    "ai_index_economy_corporate_ai_adoption_chart_title_source_repair",
    "ai_index_economy_corporate_ai_adoption_figure_label_repair",
    "ai_index_economy_jobs_chart_label_repair",
    "ai_index_economy_jobs_chart_title_source_repair",
    "ai_index_economy_jobs_figure_label_repair",
    "ai_index_economy_jobs_chart_source_region_restore",
    "ai_index_economy_jobs_labor_impact_section_heading_repair",
    "ai_index_economy_jobs_labor_impact_table_redraw",
    "ai_index_economy_jobs_macro_productivity_table_redraw",
    "ai_index_economy_jobs_workforce_body_redraw",
    "ai_index_economy_robot_deployments_chart_label_repair",
    "ai_index_economy_robot_deployments_chart_title_source_repair",
    "ai_index_economy_robot_deployments_running_header_repair",
    "ai_index_responsible_ai_dimension_table_redraw",
    "ai_page17_20_chart_title_translation_repair",
    "ai_page17_national_affiliation_heading_repair",
    "ai_page19_sector_heading_and_orphan_repair",
    "ai_running_header_uniform_font_repair",
    "chart_label_visible_repair",
    "chart_region_passthrough_repair",
    "chapter_highlights_first_item_repair",
    "chapter_highlights_title_visible_repair",
    "institution_label_visible_repair",
    "nature_footer_removed_from_header_band",
    "nature_header_footer_source_passthrough",
    "nature_inline_bold_label_repair",
    "nature_page2_numbered_question_list_repair",
    "nature_page1_doi_open_passthrough",
    "nature_page1_footer_rule_passthrough",
    "nature_page1_title_wrap_repair",
    "nature_page1_abstract_visible_repair",
    "nature_page1_stray_text_cover",
    "nature_publisher_badge_source_region_passthrough",
    "nature_publication_metadata_visible_repair",
    "nature_section_heading_style_repair",
    "nature_table1_structured_redraw",
    "nature_table2_structured_redraw",
    "nature_table_caption_visible_repair",
    "nature_table_header_visible_repair",
    "nature_visible_text_repair",
}

AI_HEADER_TRANSLATIONS = {
    2: "人工智能指数报告 2026",
    3: "人工智能指数报告 2026",
    4: "引言 | 人工智能指数报告 2026",
    5: "引言 | 人工智能指数报告 2026",
    6: "引言 | 人工智能指数报告 2026",
    7: "引言 | 人工智能指数报告 2026",
    8: "引言 | 人工智能指数报告 2026",
    9: "引言 | 人工智能指数报告 2026",
    10: "人工智能指数报告 2026",
    11: "核心要点 | 人工智能指数报告 2026",
    12: "核心要点 | 人工智能指数报告 2026",
    13: "人工智能指数报告 2026",
    14: "研究与开发 | AI Index 2026",
    15: "章节要点 | 研究与开发 | AI Index 2026",
    16: "章节要点 | 研究与开发 | AI Index 2026",
    17: "研究与开发 | AI Index 2026",
    18: "值得关注的 AI 模型 | AI Index 2026",
    19: "值得关注的 AI 模型 | AI Index 2026",
    20: "值得关注的 AI 模型 | AI Index 2026",
}

AI_CONTRIBUTOR_ROLE_COLOR = (0.09, 0.43, 0.39)

AI_CONTRIBUTOR_NAME_COLOR = (0, 0, 0)

AI_CONTRIBUTOR_AFFILIATION_COLOR = (0.35, 0.35, 0.35)

AI_CONTRIBUTOR_PINK_BG = (0.94, 0.92, 0.945)

AI_CONTRIBUTOR_WHITE_BG = (1, 1, 1)

AI_INDEX_DARK_PURPLE = (0.292, 0.139, 0.286)

AI_INDEX_BODY_DARK = (0.071, 0.067, 0.067)

AI_INDEX_HEADER_MUTED = (0.541, 0.643, 0.655)

AI_INDEX_TEAL = (0.047, 0.431, 0.427)

AI_INDEX_FOOTNOTE_LINK = (0.129, 0.369, 0.62)

AI_TOC_TEAL = (0.047, 0.471, 0.435)

AI_TOC_LINE = (0.62, 0.86, 0.82)

AI_TOC_WHITE = (1, 1, 1)

AI_TOC_HIGHLIGHT = (0.9, 0.93, 0.18)

__all__ = ['AI_CONTRIBUTOR_AFFILIATION_COLOR', 'AI_CONTRIBUTOR_NAME_COLOR', 'AI_CONTRIBUTOR_PINK_BG', 'AI_CONTRIBUTOR_ROLE_COLOR', 'AI_CONTRIBUTOR_WHITE_BG', 'AI_HEADER_TRANSLATIONS', 'AI_INDEX_BODY_DARK', 'AI_INDEX_CHART_LABEL_BROAD_SOURCE_BLOCKLIST', 'AI_INDEX_CHART_LABEL_MAX_HITS', 'AI_INDEX_DARK_PURPLE', 'AI_INDEX_FOOTER_BG', 'AI_INDEX_FOOTNOTE_LINK', 'AI_INDEX_HEADER_MUTED', 'AI_INDEX_TEAL', 'AI_INSTITUTION_REPAIRS', 'AI_TOC_HIGHLIGHT', 'AI_TOC_LINE', 'AI_TOC_TEAL', 'AI_TOC_WHITE', 'Any', 'CHART_LABEL_FALLBACKS', 'LINK_BLUE', 'Path', 'REPO_ROOT', 'RISKY_REPAIR_RULES', 'SOURCE_HAN_SANS_CN_REGULAR', 'SOURCE_HAN_SERIF_CN_REGULAR', 'annotations', 'argparse', 'build_babeldoc_il_layout_map', 'json', 'layout_role_policy', 're', 'shutil', 'stable_get_pixmap', 'visual_layout']

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
