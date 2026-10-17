#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


DIMENSIONS: dict[str, dict[str, str]] = {
    "content_parsing": {
        "label": "PDF 内容解析",
        "description": "文本完整性、阅读顺序、乱码、断词、错序和抽取质量。",
    },
    "layout_mapping": {
        "label": "结构映射",
        "description": "标题、目录、章节、作者区、机构、脚注和跨页块结构。",
    },
    "protected_elements": {
        "label": "术语与保护元素",
        "description": "术语、缩写、公式、引用、URL、人名、机构名和专名保护。",
    },
    "translation_execution": {
        "label": "分块翻译",
        "description": "语义忠实、术语一致、上下文连续和中文可读性。",
    },
    "pdf_rendering": {
        "label": "PDF 渲染",
        "description": "中文字体、可复制文本、重叠、溢出和单语/双语 PDF 输出。",
    },
    "qa_traceability": {
        "label": "QA 与可回查",
        "description": "日志、manifest、中间产物、问题归因和复现证据。",
    },
}


KEYWORDS: dict[str, tuple[str, ...]] = {
    "content_parsing": (
        "乱码",
        "截断",
        "抽取",
        "解析",
        "错序",
        "断行",
        "fi/fl",
        "fi",
        "fl",
        "单字排列",
        "字符丢失",
        "文本提取",
        "顺序混乱",
    ),
    "layout_mapping": (
        "标题",
        "目录",
        "章节",
        "作者",
        "机构",
        "页眉",
        "页脚",
        "脚注",
        "列表",
        "层级",
        "排版",
        "结构",
    ),
    "protected_elements": (
        "术语",
        "缩写",
        "公式",
        "url",
        "URL",
        "引用",
        "专名",
        "Validator",
        "ambient AI scribes",
        "Schmidt Sciences",
        "LLM",
        "LLMs",
        "人名",
        "机构名",
    ),
    "pdf_rendering": (
        "字体",
        "黑框",
        "缺字",
        "重叠",
        "溢出",
        "可复制文本",
        "渲染",
        "中文字符",
        "glyph",
        "乱码",
    ),
}


DIMENSION_RECOMMENDATIONS = {
    "content_parsing": "先输出并审查 source_manifest/extraction_quality，把抽取问题和翻译问题分开处理。",
    "layout_mapping": "为标题、目录、作者区、机构名和跨页块增加结构校验，必要时生成 layout_map。",
    "protected_elements": "把 glossary、protected_spans 和术语修订传播放进默认 QA，不依赖外部工具隐式处理。",
    "translation_execution": "保留 translation_blocks、模型配置、术语表版本和失败状态，支持局部重译。",
    "pdf_rendering": "记录 render_manifest、字体 fallback、CJK 可复制字符数、重叠/溢出和视觉抽检图。",
    "qa_traceability": "把日志、候选文本、run_summary、layout/cache 和问题归因串成可回查证据链。",
}


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def average(*values: Any, default: float = 0.0) -> float:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return sum(numeric) / len(numeric) if numeric else default


def classify_issue_text(text: str) -> list[str]:
    """把裁判 finding/risk 归因到分层评测维度。"""
    matched: list[str] = []
    for dimension, keywords in KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            matched.append(dimension)
    if not matched:
        matched.append("translation_execution")
    return matched


def classify_issues(findings: list[str], risks: list[str]) -> dict[str, list[str]]:
    issues = {key: [] for key in DIMENSIONS}
    for text in findings + risks:
        for dimension in classify_issue_text(text):
            issues[dimension].append(text)
    return issues


def artifact_traceability_score(flags: dict[str, bool]) -> int:
    score = 40
    weights = {
        "has_run_summary": 10,
        "has_log": 10,
        "has_candidate_text": 10,
        "has_selected_output": 10,
        "has_judge": 10,
        "has_layout_or_cache": 10,
    }
    for key, value in weights.items():
        if flags.get(key):
            score += value
    if flags.get("has_font_fix_evidence"):
        score += 5
    return clamp_score(score)


def score_case_dimensions(
    case: dict[str, Any],
    artifact_flags: dict[str, bool] | None = None,
) -> dict[str, dict[str, Any]]:
    judge = case.get("judge") or {}
    scores = judge.get("scores") or {}
    findings = list(judge.get("key_findings") or [])
    risks = list(judge.get("major_risks") or [])
    issues = classify_issues(findings, risks)
    rule = case.get("rule_metrics") or {}
    flags = artifact_flags or {}

    bases = {
        "content_parsing": average(scores.get("coverage"), scores.get("structure")),
        "layout_mapping": average(scores.get("structure")),
        "protected_elements": average(scores.get("terminology")),
        "translation_execution": average(scores.get("semantic_fidelity"), scores.get("readability")),
        "pdf_rendering": average(scores.get("structure"), scores.get("readability")),
        "qa_traceability": artifact_traceability_score(flags),
    }
    deductions = {dimension: min(30, len(items) * 5) for dimension, items in issues.items()}

    if rule:
        if rule.get("chars", 0) < 80:
            deductions["content_parsing"] += 35
            deductions["qa_traceability"] += 10
        if rule.get("chinese_chars", 0) == 0 and flags.get("has_pdf_output"):
            deductions["pdf_rendering"] += 35
            deductions["translation_execution"] += 15
        if rule.get("contains_common_failure_marker"):
            deductions["qa_traceability"] += 5
        if rule.get("contains_urls"):
            bases["protected_elements"] += 2
        if rule.get("contains_formula_markers"):
            bases["protected_elements"] += 2

    result: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        score = clamp_score(bases[dimension] - deductions[dimension])
        evidence = []
        if dimension == "qa_traceability":
            evidence = [key for key, value in sorted(flags.items()) if value]
        elif rule:
            evidence = [
                f"chars={rule.get('chars', 0)}",
                f"chinese_chars={rule.get('chinese_chars', 0)}",
                f"ascii_words={rule.get('ascii_words', 0)}",
            ]
        result[dimension] = {
            "score": score,
            "issues": issues[dimension],
            "issue_count": len(issues[dimension]),
            "evidence": evidence,
            "recommendation": DIMENSION_RECOMMENDATIONS[dimension],
        }
    return result


def aggregate_dimension_scores(cases: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, list[int]] = {dimension: [] for dimension in DIMENSIONS}
    for case in cases:
        dimensions = case.get("dimensions") or {}
        for dimension in DIMENSIONS:
            value = dimensions.get(dimension, {}).get("score")
            if isinstance(value, int | float):
                totals[dimension].append(int(value))
    return {
        dimension: round(sum(values) / len(values), 1) if values else 0.0
        for dimension, values in totals.items()
    }
