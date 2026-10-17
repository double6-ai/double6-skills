# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline的共享依赖与固定规则；业务处理按职责模块加载。"""

from __future__ import annotations

from stable_page_raster import stable_get_pixmap

import hashlib

import json

import math

import os

import re

import resource

import statistics

from datetime import datetime, timezone

from io import BytesIO

from pathlib import Path

from typing import Any, Callable

from .typography_contract import validate_uniform_typography

from .constants import (
    DEFAULT_SCAN_DPI,
    MINERU_VERSION,
    PROTECTED_LAYOUT_ROLES,
    SCHEMA_VERSION,
    SKILL_VERSION,
)

from .mineru4_adapter import MinerUUnavailableError, parse_with_mineru, sha256_file, write_jsonl

from .parser_policy import assess_mineru_result, assess_rapidocr_page

from .quality_gate import evaluate_scan_quality_gate, resolve_translation_alternatives

from .scientific_integrity import scientific_integrity_findings

from .name_columns import prepare_name_columns, vertical_margin_reason

from .frontmatter import prepare_centered_frontmatter

from .cjk_typography import LATIN_ATOM, TOKEN, wrap_mixed_text

from source_formatting import infer_paragraph_geometry

from cjk_justification import insert_source_htmlbox

from css_numbers import css_number

RapidOCRRunner = Callable[[Path, int, int], tuple[list[dict[str, Any]], dict[str, Any]]]

MinerURunner = Callable[..., dict[str, Any]]

Translator = Callable[[str, Any], str]

SEARCH_LAYER_PROTECTED_ROLES = {"table"}

COMPACT_CONNECTIVE_TRANSLATIONS = {
    "and": "和",
    "or": "或",
    "and obtain": "可得",
    "where": "其中",
    "that is to say,": "即",
    "that is to say": "即",
    "that is,": "即",
    "that is": "即",
    "i.e.,": "即",
    "i.e.": "即",
    "and hence": "因此",
    "hence": "因此",
    "therefore": "因此",
    "thus": "因此",
    "for": "用于",
    "then,": "则",
    "then": "则",
    "similarly,": "同样",
    "similarly": "同样",
}

SUBSCRIPT_DIGIT_TRANSLATION = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

SUPERSCRIPT_DIGITS = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")

INLINE_LATEX_SYMBOLS = {
    r"\varepsilon": "ε",
    r"\epsilon": "ε",
    r"\varphi": "φ",
    r"\lambda": "λ",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\theta": "θ",
    r"\kappa": "κ",
    r"\sigma": "σ",
    r"\omega": "ω",
    r"\cdot": "·",
    r"\ldots": "…",
    r"\cdots": "…",
    r"\times": "×",
    r"\infty": "∞",
    r"\approx": "≈",
    r"\neq": "≠",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\phi": "φ",
    r"\iota": "ι",
    r"\eta": "η",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\tau": "τ",
    r"\psi": "ψ",
    r"\chi": "χ",
    r"\nu": "ν",
    r"\mu": "μ",
    r"\rho": "ρ",
    r"\zeta": "ζ",
    r"\ell": "ℓ",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Phi": "Φ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Omega": "Ω",
    r"\bullet": "•",
}

LATEX_TEXT_WRAPPERS = (
    "mathbf",
    "mathrm",
    "mathit",
    "mathcal",
    "mathbb",
    "boldsymbol",
    "mathsf",
    "mathtt",
    "textrm",
    "textbf",
    "textit",
    "operatorname",
    "text",
    "mbox",
    "dot",
    "ddot",
    "hat",
    "tilde",
    "vec",
    "check",
    "breve",
)

LATEX_WRAPPER_RE = re.compile(
    r"\\(?:" + "|".join(LATEX_TEXT_WRAPPERS) + r")\s*\{\s*([^{}]*)\s*\}"
)

LATEX_FRAC_RE = re.compile(r"\\frac\s*\{\s*([^{}]+)\s*\}\s*\{\s*([^{}]+)\s*\}")

LATEX_SPACING_RE = re.compile(r"\\(?:quad|qquad|,|;|!|:| |hspace\s*\{[^{}]*\})")

LATEX_LEFTOVER_COMMAND_RE = re.compile(r"\\[A-Za-z]+\*?")

PRECOMPOSED_MACRONS = {
    "A": "Ā",
    "a": "ā",
    "E": "Ē",
    "e": "ē",
    "I": "Ī",
    "i": "ī",
    "O": "Ō",
    "o": "ō",
    "U": "Ū",
    "u": "ū",
}

__all__ = ['Any', 'BytesIO', 'COMPACT_CONNECTIVE_TRANSLATIONS', 'Callable', 'DEFAULT_SCAN_DPI', 'INLINE_LATEX_SYMBOLS', 'LATEX_FRAC_RE', 'LATEX_LEFTOVER_COMMAND_RE', 'LATEX_SPACING_RE', 'LATEX_TEXT_WRAPPERS', 'LATEX_WRAPPER_RE', 'LATIN_ATOM', 'MINERU_VERSION', 'MinerURunner', 'MinerUUnavailableError', 'PRECOMPOSED_MACRONS', 'PROTECTED_LAYOUT_ROLES', 'Path', 'RapidOCRRunner', 'SCHEMA_VERSION', 'SEARCH_LAYER_PROTECTED_ROLES', 'SKILL_VERSION', 'SUBSCRIPT_DIGIT_TRANSLATION', 'SUPERSCRIPT_DIGITS', 'TOKEN', 'Translator', 'annotations', 'assess_mineru_result', 'assess_rapidocr_page', 'css_number', 'datetime', 'evaluate_scan_quality_gate', 'hashlib', 'infer_paragraph_geometry', 'insert_source_htmlbox', 'json', 'math', 'os', 'parse_with_mineru', 'prepare_centered_frontmatter', 'prepare_name_columns', 're', 'resolve_translation_alternatives', 'resource', 'scientific_integrity_findings', 'sha256_file', 'stable_get_pixmap', 'statistics', 'timezone', 'validate_uniform_typography', 'vertical_margin_reason', 'wrap_mixed_text', 'write_jsonl']

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
