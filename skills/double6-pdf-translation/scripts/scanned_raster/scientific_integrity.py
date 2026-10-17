"""扫描正文中可确定的下标、撇号和简单比较式保真检查。

只检查 OCR 所给出的符号身份，不裁决 OCR 是否忠实于原页，也不推断公式含义。
"""
from __future__ import annotations

import re
from typing import Any


LETTERS = r"A-Za-zα-ωΑ-Ω"
GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "lambda": "λ", "phi": "φ", "theta": "θ", "mu": "μ", "sigma": "σ", "omega": "ω"}
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def canonical_math(text: str) -> str:
    value = text.translate(SUBSCRIPTS).replace("″", "′′").replace("‴", "′′′")
    # 模型有时以右单引号书写变量的撇号；仅在独立数学变量位置
    # 归一化，不把英语所有格、姓名或引语词尾作为科学符号。
    value = re.sub(rf"(?<![{LETTERS}])([{LETTERS}]\d*)([’]+)(?=$|[^{LETTERS}’])",
                   lambda m: m[1] + "′" * len(m[2]), value)
    value = re.sub(r"\\(?:mathbf|mathit|mathrm|text)\s*\{\s*([A-Za-z0-9 ]+)\s*\}", r"\1", value)
    value = re.sub(r"\\(alpha|beta|gamma|delta|lambda|phi|theta|mu|sigma|omega)\b", lambda m: GREEK[m[1]], value)
    value = re.sub(r"\\(?:neq|ne)\b", "≠", value)
    value = re.sub(r"\\(?:leq|le)\b", "≤", value)
    value = re.sub(r"\\(?:geq|ge)\b", "≥", value)
    value = re.sub(r"\\pm\b", "±", value)
    value = value.replace(r"\prime", "′")
    value = re.sub(r"\^?\s*\{\s*(['′ ]+)\s*\}", lambda m: m[1].replace(" ", "").replace("'", "′"), value)
    value = re.sub(r"\s*_\s*\{\s*([0-9 ]+)\s*\}", lambda m: m[1].replace(" ", ""), value)
    value = re.sub(r"\s*_\s*([0-9]+)", r"\1", value)
    # 将变量与紧随其后的索引连起来，保留大小写和撇号个数。
    value = re.sub(rf"(?<![{LETTERS}])([{LETTERS}])(['′]+)\s*(\d+)", lambda m: m[1] + m[3] + m[2].replace("'", "′"), value)
    value = re.sub(rf"([{LETTERS}]\d*)['′]+", lambda m: m[0].replace("'", "′"), value)
    return value


def protected_atoms(text: str) -> set[str]:
    value = canonical_math(text)
    return {m[0] for m in re.finditer(rf"(?<![{LETTERS}])([{LETTERS}](?:\d+′*|′+))(?=$|[^{LETTERS}\d′]|[{LETTERS}]\d)", value)}


def relations(text: str) -> set[str]:
    value = canonical_math(text)
    operand = rf"(?:[{LETTERS}]\d*′*|[+-]?\d+(?:\.\d+)?)"
    pattern = rf"(?<![{LETTERS}\d])(?=({operand})\s*(=|≠|≤|≥|±|<|>)\s*({operand})(?![{LETTERS}\d_{{\\^]))"
    return {"".join(m.groups()) for m in re.finditer(pattern, value) if re.search(rf"[{LETTERS}]", m[1] + m[3])}


def scientific_integrity_findings(source: str, translation: str) -> list[dict[str, Any]]:
    expected, actual = protected_atoms(source), protected_atoms(translation)
    findings = []
    if re.search(r"_\s*\{[^{}]*_", source):
        findings.append({"rule": "scientific_ocr_notation_requires_review", "severity": "blocking",
                         "reason": "nested subscript cannot be safely flattened by the current plain-text renderer; verify original page"})
    missing = sorted(expected - actual)
    if missing:
        findings.append({"rule": "scientific_symbol_loss", "severity": "blocking", "missing": missing,
                         "source_atoms": sorted(expected), "translated_atoms": sorted(actual)})
    expected_relations, actual_relations = relations(source), relations(translation)
    lost_relations = sorted(expected_relations - actual_relations)
    if lost_relations:
        findings.append({"rule": "scientific_relation_changed", "severity": "blocking", "missing": lost_relations,
                         "source_relations": sorted(expected_relations), "translated_relations": sorted(actual_relations)})
    return findings
