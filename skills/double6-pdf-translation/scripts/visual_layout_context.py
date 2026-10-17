# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual_layout的共享依赖与固定规则；业务处理按职责模块加载。"""
from __future__ import annotations

from stable_page_raster import stable_get_pixmap

import json

import hashlib

import math

import re

from pathlib import Path

from typing import Any

HEADING_TEXT_RE = re.compile(
    r"^(?:摘要|引言|文献综述|方法|结果|讨论|结论|参考文献|目录|贡献者|概览|章节要点|"
    r"数据可用性|注释|致谢|作者贡献|利益冲突|伦理批准|知情同意|附加信息|"
    r"第一章|第二章|第三章|第四章|第五章|第六章|第七章|研究与开发|技术性能|负责任的人工智能|经济|科学|医学|教育|"
    r"Abstract|Introduction|Literature Review|Methods?|Results?|Discussion|Conclusions?|References|Contents|"
    r"Data availability|Notes|Acknowledgements|Author contributions|Competing interests|Ethics approval|Informed consent|Additional information|"
    r"Contributors|Overview|Chapter Highlights|Chapter\s+\d+|Research and Development|Technical Performance|Responsible AI|Economy|Science|Medicine|Education)$",
    re.I,
)

HEADING_TRANSLATION_PAIRS = {
    "abstract": "摘要",
    "introduction": "引言",
    "literature review": "文献综述",
    "methods": "方法",
    "method": "方法",
    "results": "结果",
    "result": "结果",
    "discussion": "讨论",
    "conclusion": "结论",
    "conclusions": "结论",
    "references": "参考文献",
    "chapter 1": "第一章",
    "chapter 2": "第二章",
    "chapter 3": "第三章",
    "chapter 4": "第四章",
    "chapter 5": "第五章",
    "chapter 6": "第六章",
    "chapter 7": "第七章",
    "research and development": "研究与开发",
    "technical performance": "技术性能",
    "responsible ai": "负责任的人工智能",
    "economy": "经济",
    "science": "科学",
    "medicine": "医学",
    "education": "教育",
}

LATIN_PERSON_NAME_RE = re.compile(r"^(?:[A-Z][A-Za-z'’.-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'’.-]+|[A-Z]\.)){1,4}$")

LATIN_NAME_EXCLUDE_WORDS = {
    "chapter",
    "research",
    "development",
    "introduction",
    "science",
    "medicine",
    "education",
    "economy",
    "responsible",
    "technical",
    "performance",
    "public",
    "opinion",
    "policy",
    "governance",
    "ai",
    "index",
    "report",
    "contributors",
    "the",
    "of",
    "and",
    "by",
    "national",
    "affiliation",
    "sector",
    "organization",
    "geographic",
    "distribution",
    "north",
    "south",
    "east",
    "west",
    "central",
    "latin",
    "america",
    "australia",
    "brazil",
    "canada",
    "denmark",
    "europe",
    "finland",
    "france",
    "germany",
    "india",
    "israel",
    "italy",
    "japan",
    "netherlands",
    "asia",
    "africa",
    "middle",
    "united",
    "states",
    "kingdom",
    "arab",
    "emirates",
    "saudi",
    "arabia",
    "singapore",
    "spain",
    "sweden",
    "switzerland",
    "korea",
    "zeki",
    "data",
    "using",
}

LATIN_PERSON_NAME_EXCLUDE_PHRASES = {
    "Geographic Distribution",
    "North America",
    "Latin America",
    "United States",
    "United Kingdom",
    "United Arab",
    "United Arab Emirates",
    "Arab Emirates",
    "Saudi Arabia",
    "South Korea",
    "Australia",
    "Brazil",
    "Canada",
    "Denmark",
    "Finland",
    "France",
    "Germany",
    "India",
    "Israel",
    "Italy",
    "Japan",
    "Netherlands",
    "Singapore",
    "Spain",
    "Sweden",
    "Switzerland",
    "Zeki Data",
    "Using Zeki",
}

CHART_TITLE_TRANSLATION_REQUIREMENTS = {
    "by sector and organization": ["部门", "组织"],
    "by national affiliation": ["国家", "地区"],
}

NATURE_PUBLISHER_BADGE_REGION = [465.0, 112.0, 575.0, 165.0]

COMPACT_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ ./&:+\\-]{1,34}$")

ALLOWED_COMPACT_LABEL_RE = re.compile(
    r"^(?:[A-Z]{2,}(?:-[A-Za-z0-9]+)?|"
    r"ChatGPT-?\d*(?:\.\d+)?[A-Za-z]*|OpenAI-?o?\d+|GPT-?\d+(?:\.\d+)?[A-Za-z]*|o\d+|"
    r"LLMs?|LLM(?:-[A-Za-z0-9]+)?|NMT(?:-[A-Za-z0-9]+)?|AI|MT|HT|DOI|URL|"
    r"LaTeX|TeX|PDF|API|OpenAI|ChatGPT)$"
)

COMMON_UNTRANSLATED_HEADING_RE = re.compile(
    r"^(?:Abstract|Introduction|Methods?|Results?|Discussion|Conclusion|"
    r"References?|Appendix|Contents|Acknowledgements?|Data availability|Notes|"
    r"Author contributions|Competing interests|Ethics approval|Informed consent|"
    r"Additional information|Supplementary information)$"
)

APPROVED_COMPACT_NAME_RE = re.compile(
    r"^(?:AI|LLMs?|LLM(?:-[A-Za-z0-9]+)?|GPT(?:-?\d+(?:\.\d+)?[A-Za-z]*)?|"
    r"ChatGPT(?:-?\d+(?:\.\d+)?[A-Za-z]*)?|OpenAI(?:\s+o?\d+[A-Za-z]*)?|"
    r"LaTeX|TeX|PDF|API|arXiv|DOI|URL)$",
    re.I,
)

AUTHOR_CITATION_LABEL_RE = re.compile(r"^[A-Z][A-Za-z'’.-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z'’.-]+)?\s+et\s+al\.?$")

DIAGRAM_LABEL_ALLOWLIST = {
    "Input",
    "Output",
    "Summary",
    "Document Structure",
    "Translator",
    "Validator",
    "Reconstruct",
    "Compile",
    "Translated Tex",
    "Parsing",
    "Filtering",
    "Term Dict",
    "Term_dict",
    "Pre Summary",
    "Pre_summary",
    "Pre Term Dict",
    "Pre_term_dict",
    "Next Section",
    "Next_section",
    "Source",
    "Target",
    "Result",
    "Reference",
    "Prompt",
    "Context",
}

VISIBLE_LATEX_COMMAND_RE = re.compile(r"\\(?:section|subsection|subsubsection|begin|end|cite|ref|url|texttt|emph|caption)\b")

REFERENCE_BODY_IGNORE_LINES = {
    "data availability",
    "数据可用性",
    "notes",
    "注释",
    "published online",
    "在线发表",
    "received",
    "收稿日期",
    "accepted",
    "录用日期",
}

__all__ = ['ALLOWED_COMPACT_LABEL_RE', 'APPROVED_COMPACT_NAME_RE', 'AUTHOR_CITATION_LABEL_RE', 'Any', 'CHART_TITLE_TRANSLATION_REQUIREMENTS', 'COMMON_UNTRANSLATED_HEADING_RE', 'COMPACT_LABEL_RE', 'DIAGRAM_LABEL_ALLOWLIST', 'HEADING_TEXT_RE', 'HEADING_TRANSLATION_PAIRS', 'LATIN_NAME_EXCLUDE_WORDS', 'LATIN_PERSON_NAME_EXCLUDE_PHRASES', 'LATIN_PERSON_NAME_RE', 'NATURE_PUBLISHER_BADGE_REGION', 'Path', 'REFERENCE_BODY_IGNORE_LINES', 'VISIBLE_LATEX_COMMAND_RE', 'annotations', 'hashlib', 'json', 'math', 're', 'stable_get_pixmap']

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
