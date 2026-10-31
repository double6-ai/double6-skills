# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""run_pdf_translation的共享依赖与固定规则；业务处理按职责模块加载。"""
from __future__ import annotations

import argparse

import json

import math

import os

import re

import shlex

import shutil

import subprocess

import sys

import time

from pathlib import Path

from types import SimpleNamespace

from typing import Any

import build_block_bridge

import build_babeldoc_il_layout_map

import build_bilingual_pdf

import build_layout_structure_gate

import build_pdf_rerender_plan

import build_poppler_text_bbox_audit

import build_pymupdf_layout_audit

import build_structured_writeback_manifest

import build_structured_visual_candidates

import build_visual_repair_pdf

import check_translation

import extract_terms

import prepare_paper_source

import render_readable_pdf

import repair_quality_issues

import layout_role_policy

import policy_utils

import visual_layout

from hymt_compat_proxy import ProxyConfig, start_hymt_compat_proxy

DEFAULT_MODEL = None

DEFAULT_BASE_URL = None

DEFAULT_API_KEY = None

DEFAULT_REASONING_EFFORT = "none"

DEFAULT_TRANSLATOR_MODE = "auto"

DEFAULT_CLI_MAX_TOKENS = 4096

DEFAULT_LOCAL_MAX_CONCURRENCY = 3


def effective_local_max_concurrency(value) -> int:
    """直接翻译入口没写路数时的同时请求数。编排入口没写时仍是 1，不调用这里。"""
    if value is None:
        return DEFAULT_LOCAL_MAX_CONCURRENCY
    return int(value)

DEFAULT_HYMT_COMPAT_PROXY_PORT = 18082

DEFAULT_PDF2ZH_BACKEND = "vendored"

DEFAULT_LATEX_RENDER_MODE = "auto"

DEFAULT_LATEX_PROJECT_MODE = "in-place"

DEFAULT_LATEX_DOCKER_IMAGE = "paper-translation-tex:2026-05-21"

DEFAULT_HYMT2_TEMPERATURE = 0.7

LATEX_SOURCE_HINT_ENV = "PAPER_TRANSLATION_LATEX_SOURCE_HINT"

LATEX_SOURCE_ROOTS_ENV = "PAPER_TRANSLATION_LATEX_SOURCE_ROOTS"

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional, authentic machine translation engine. "
    "Translate academic PDFs into fluent Simplified Chinese while preserving "
    "formulas, citations, URLs, named entities, terminology, and layout-sensitive placeholders. "
    "Only output the translated result without additional explanation. "
    "Do not leave ordinary English words untranslated; translate residual prose words such as "
    "'overwhelmingly' into natural Chinese unless they are protected spans, code, URLs, emails, or approved names."
)

# 中译英（--target-language en）默认提示词；定义在 policy_utils，供 Qwen CLI 适配器子进程识别目标语言。
DEFAULT_SYSTEM_PROMPT_EN = policy_utils.DEFAULT_SYSTEM_PROMPT_EN

# 日译中（源=日文横排，目标=zh）默认提示词（lane/d，T6 多语言第一阶段）。
# 要点：日文汉字词不可照搬到中文（同形异义是日译中的主要质量风险），假名正文全部译出；
# 拉丁字母技术词、代码、URL、邮箱与核定专名保持原样；译文保持简洁以适配原版面空间。
DEFAULT_SYSTEM_PROMPT_JA2ZH = (
    "You are a professional, authentic machine translation engine. "
    "Translate Japanese academic PDFs (horizontal text) into fluent Simplified Chinese while preserving "
    "formulas, citations, URLs, named entities, terminology, and layout-sensitive placeholders. "
    "Only output the translated result without additional explanation. "
    "Do not copy Japanese Kanji words verbatim: rewrite them as their natural Simplified Chinese equivalents "
    "(for example 仕組み→机制, 勉強→学习, 論文→论文, 情報→信息), and translate all kana prose, headings, "
    "captions and table text into Chinese. Keep Latin-script technical terms, code, URLs, emails, and approved "
    "names as they are unless a conventional Chinese translation exists. "
    "Keep the Chinese concise, because it must fit the space of the original Japanese layout."
)

SUPPORTED_TARGET_LANGUAGES = ("zh", "en")
# 目标语言 -> 默认源语言（pdf2zh --lang-in / --lang-out）。zh 目标的非 en 源（lane/d 起支持
# ja/ko 横排）由渲染层按输入检测结果或 PAPER_TRANSLATION_SOURCE_LANGUAGE 显式声明覆盖。
TARGET_SOURCE_LANGUAGE = {"zh": "en", "en": "zh"}
# 源语言显式声明（ja/ko/en）：预检/渲染层的检测结果之上的用户级覆盖。
SOURCE_LANGUAGE_ENV = "PAPER_TRANSLATION_SOURCE_LANGUAGE"


def resolve_system_prompt(prompt: str, target_language: str = "zh", source_language: str | None = None) -> str:
    """只在调用方未自定义提示词时按翻译方向替换默认值。

    方向优先级：目标 en（中译英）> 目标 zh 且源 ja（日译中，lane/d）> 既有默认（英译中）。
    """
    if prompt != DEFAULT_SYSTEM_PROMPT:
        return prompt
    if target_language == "en":
        return DEFAULT_SYSTEM_PROMPT_EN
    if source_language == "ja":
        return DEFAULT_SYSTEM_PROMPT_JA2ZH
    return prompt


PROTECTED_CHECK_VALUES = [
    "LLMs",
    "AI sovereignty",
    "Human-Centered AI",
    "Stanford Institute for Human-Centered AI",
    "Hong Kong Polytechnic University",
]

PROTECTED_CHECK_TRANSLATIONS = {
    "LLMs": ["大型语言模型", "LLMs"],
    "AI sovereignty": ["人工智能主权"],
    "Human-Centered AI": ["以人为本人工智能"],
    "Stanford Institute for Human-Centered AI": ["斯坦福以人为本人工智能研究院", "斯坦福大学以人为本人工智能研究院"],
    "Hong Kong Polytechnic University": ["香港理工大学"],
}

LATEX_MAIN_NAME_HINTS = {"main", "paper", "acl_latex", "ms", "article"}

LATEX_BAD_NAME_HINTS = {"merge_中文", "merge_english", "output", "template", "test"}

LATEX_REFLOW_LINE_WIDTH_CJK = 38.0

LATEX_REFLOW_LINES_PER_PAGE = 84

NON_BLOCKING_BACKEND_FAILURE_CLASSES = {
    "protected_or_passthrough",
    "already_translated_passthrough",
    "layout_role_passthrough",
    "cover_split_fragment",
    "fallback_but_translated_warn",
    "structured_translated_needs_mapping",
    "pdf_direct_repaired",
    "recovered_after_parse_retry",
}

PDF_DIRECT_REPAIR_RESOLUTIONS = {
    "AI-based models abstract": "nature_page1_abstract_pdf_direct_text_repair",
    "This research was supported by The Hong Kong Polytechnic University": "nature_page14_acknowledgements_pdf_direct_text_repair",
    "This research was supported by TheHong Kong Polytechnic University": "nature_page14_acknowledgements_pdf_direct_text_repair",
    "Supplementary information": "nature_page14_supplementary_information_pdf_direct_text_repair",
    "Correspondence and requests for materials should be addressed to Andrew Kay Fan Cheung.": "nature_page14_correspondence_pdf_direct_text_repair",
}

__all__ = ['Any', 'DEFAULT_API_KEY', 'DEFAULT_BASE_URL', 'DEFAULT_CLI_MAX_TOKENS', 'DEFAULT_HYMT2_TEMPERATURE', 'DEFAULT_HYMT_COMPAT_PROXY_PORT', 'DEFAULT_LATEX_DOCKER_IMAGE', 'DEFAULT_LATEX_PROJECT_MODE', 'DEFAULT_LATEX_RENDER_MODE', 'DEFAULT_LOCAL_MAX_CONCURRENCY', 'effective_local_max_concurrency', 'DEFAULT_MODEL', 'DEFAULT_PDF2ZH_BACKEND', 'DEFAULT_REASONING_EFFORT', 'DEFAULT_SYSTEM_PROMPT', 'DEFAULT_SYSTEM_PROMPT_EN', 'DEFAULT_SYSTEM_PROMPT_JA2ZH', 'SUPPORTED_TARGET_LANGUAGES', 'TARGET_SOURCE_LANGUAGE', 'SOURCE_LANGUAGE_ENV', 'resolve_system_prompt', 'DEFAULT_TRANSLATOR_MODE', 'LATEX_BAD_NAME_HINTS', 'LATEX_MAIN_NAME_HINTS', 'LATEX_REFLOW_LINES_PER_PAGE', 'LATEX_REFLOW_LINE_WIDTH_CJK', 'LATEX_SOURCE_HINT_ENV', 'LATEX_SOURCE_ROOTS_ENV', 'NON_BLOCKING_BACKEND_FAILURE_CLASSES', 'PDF_DIRECT_REPAIR_RESOLUTIONS', 'PROTECTED_CHECK_TRANSLATIONS', 'PROTECTED_CHECK_VALUES', 'Path', 'ProxyConfig', 'SimpleNamespace', 'annotations', 'argparse', 'build_babeldoc_il_layout_map', 'build_bilingual_pdf', 'build_block_bridge', 'build_layout_structure_gate', 'build_pdf_rerender_plan', 'build_poppler_text_bbox_audit', 'build_pymupdf_layout_audit', 'build_structured_visual_candidates', 'build_structured_writeback_manifest', 'build_visual_repair_pdf', 'check_translation', 'extract_terms', 'json', 'layout_role_policy', 'math', 'os', 'policy_utils', 'prepare_paper_source', 're', 'render_readable_pdf', 'repair_quality_issues', 'shlex', 'shutil', 'start_hymt_compat_proxy', 'subprocess', 'sys', 'time', 'visual_layout']

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
