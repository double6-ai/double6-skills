#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


GLOSSARY_FIELDS = [
    "source_term",
    "translation",
    "action",
    "note",
    "confidence",
    "first_seen_block",
    "review_status",
    "term_type",
    "noise_reason",
    "notes",
]

KNOWN_TERMS: dict[str, dict[str, str]] = {
    "LLM": {
        "translation": "LLM（大型语言模型）",
        "action": "keep+explain",
        "note": "大模型语境下保留缩写并解释；优先统一为大型语言模型，不要译为法学硕士。",
        "confidence": "high",
        "term_type": "abbreviation",
    },
    "LLMs": {
        "translation": "LLMs（大型语言模型）",
        "action": "keep+explain",
        "note": "大模型语境下保留缩写并解释；优先统一为大型语言模型，不要译为法学硕士。",
        "confidence": "high",
        "term_type": "abbreviation",
    },
    "LitLLMs": {
        "translation": "LitLLMs",
        "action": "keep",
        "note": "论文自造名、系统名或数据集名默认保留原文；可在正文解释含义。",
        "confidence": "high",
        "term_type": "name",
    },
    "Literature Review": {
        "translation": "文献综述",
        "action": "translate",
        "note": "学术论文语境通常译为文献综述，不译为文学评论。",
        "confidence": "high",
        "term_type": "concept",
    },
    "Literature review": {
        "translation": "文献综述",
        "action": "translate",
        "note": "章节标题语境下译为文献综述。",
        "confidence": "high",
        "term_type": "section_heading",
    },
    "Introduction": {
        "translation": "引言",
        "action": "translate",
        "note": "章节标题语境下译为引言。",
        "confidence": "high",
        "term_type": "section_heading",
    },
    "Large Language Model": {
        "translation": "大型语言模型",
        "action": "translate",
        "note": "首次出现可写作“大型语言模型（LLM）”。",
        "confidence": "high",
        "term_type": "concept",
    },
    "Large Language Models": {
        "translation": "大型语言模型",
        "action": "translate",
        "note": "首次出现可写作“大型语言模型（LLMs）”。",
        "confidence": "high",
        "term_type": "concept",
    },
    "Human-Centered AI": {
        "translation": "以人为本人工智能",
        "action": "translate",
        "note": "AI Index / HAI 语境下避免直译为人类中心人工智能。",
        "confidence": "high",
        "term_type": "concept",
    },
    "AI sovereignty": {
        "translation": "人工智能主权",
        "action": "translate",
        "note": "政策语境中优先使用完整中文术语。",
        "confidence": "high",
        "term_type": "policy_term",
    },
    "Research and Development": {
        "translation": "研究与开发",
        "action": "contextual",
        "note": "目录或章节标题中避免过度压缩，正文中可按语境使用“研发”。",
        "confidence": "medium",
        "term_type": "section_title",
    },
    "Hong Kong Polytechnic University": {
        "translation": "香港理工大学",
        "action": "translate",
        "note": "机构专名，不要误译为香港大学。",
        "confidence": "high",
        "term_type": "organization",
    },
    "AI Index": {
        "translation": "人工智能指数（AI Index）",
        "action": "first_bilingual",
        "note": "报告名称首次出现使用双语形式；不要译为 AI指数。",
        "confidence": "high",
        "term_type": "publication",
    },
    "textbase": {
        "translation": "文本库",
        "action": "translate",
        "note": "文学翻译/语篇分析语境默认采用参考译文定译，不译为文本基础。",
        "confidence": "medium",
        "term_type": "discourse_term",
    },
    "Sub-corpus": {
        "translation": "子语料库",
        "action": "translate",
        "note": "表格表头术语，默认翻译。",
        "confidence": "medium",
        "term_type": "table_header",
    },
    "Number of texts": {
        "translation": "文本数量",
        "action": "translate",
        "note": "表格表头术语，默认翻译。",
        "confidence": "medium",
        "term_type": "table_header",
    },
    "Competing interests": {
        "translation": "竞争利益声明",
        "action": "translate",
        "note": "论文声明章节标题，默认翻译。",
        "confidence": "medium",
        "term_type": "section_title",
    },
    "Retrieval-Augmented Generation": {
        "translation": "检索增强生成",
        "action": "translate",
        "note": "可保留 RAG 缩写。",
        "confidence": "high",
        "term_type": "concept",
    },
    "RAG": {
        "translation": "RAG（检索增强生成）",
        "action": "keep+explain",
        "note": "缩写保留，首次出现时解释。",
        "confidence": "high",
        "term_type": "abbreviation",
    },
}

STOP_TERMS = {
    "Abstract",
    "Conclusion",
    "References",
    "Related Work",
    "The",
    "This",
    "These",
    "Figure",
    "Table",
}
SECTION_PREFIXES = ("Abstract ", "Introduction ", "Conclusion ", "References ", "Keywords ")
STOP_PHRASES = {
    "Proceedings of the",
    "In the",
    "GPT with",
    "LLMs and",
    "LLM and",
    "Sub-corpus Number",
    "Number of texts",
    "Competing interests",
    "The paper",
    "This paper",
    "In this paper",
}
LOW_VALUE_END_WORDS = {"and", "or", "with", "of", "the", "in", "for", "to"}
LOW_VALUE_START_WORDS = {"the", "this", "these", "in", "on", "for", "with", "using"}


def normalize_space(value: str) -> str:
    return " ".join(value.strip().split())


def is_low_value_term(term: str) -> bool:
    return low_value_reason(term) != ""


def low_value_reason(term: str) -> str:
    normalized = normalize_space(term).strip(" ,.;:()[]{}")
    if not normalized:
        return "empty"
    lowered = normalized.lower()
    if normalized in STOP_PHRASES or lowered in {item.lower() for item in STOP_PHRASES}:
        return "stop_phrase"
    words = lowered.split()
    if words and (words[0] in LOW_VALUE_START_WORDS or words[-1] in LOW_VALUE_END_WORDS):
        return "function_word_boundary"
    if len(words) <= 2 and any(word in LOW_VALUE_END_WORDS | LOW_VALUE_START_WORDS for word in words):
        return "short_function_phrase"
    if re.fullmatch(r"(?:[A-Z][a-z]+\s+){0,2}(?:Proceedings|Transactions|Journal|Conference|Workshop)\s+of\s+the", normalized):
        return "publication_fragment"
    return ""


def classify_term_type(term: str) -> str:
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,}s?", term):
        return "abbreviation"
    if re.fullmatch(r"[A-Z][A-Za-z]+[A-Z][A-Za-z0-9]*", term):
        return "name"
    lowered = term.lower()
    if any(marker in lowered for marker in ["journal", "proceedings", "conference", "workshop", "transactions"]):
        return "publication"
    if any(marker in lowered for marker in ["university", "institute", "laboratory", "department"]):
        return "organization"
    return "concept"


def add_candidate(candidates: dict[str, dict[str, str]], term: str, *, confidence: str = "medium") -> None:
    term = normalize_space(term).strip(" ,.;:()[]{}")
    if len(term) < 2 or term in STOP_TERMS:
        return
    noise_reason = "" if term in KNOWN_TERMS else low_value_reason(term)
    if noise_reason:
        return
    if term.startswith(SECTION_PREFIXES):
        return
    if term.lower() in {item.lower() for item in STOP_TERMS}:
        return
    if re.search(r"\b[A-Z]{2,}s?\s+for\s+", term):
        return
    if term in candidates:
        return
    known = KNOWN_TERMS.get(term)
    if known:
        candidates[term] = {
            "source_term": term,
            **known,
            "first_seen_block": "",
            "review_status": "needs_review",
            "term_type": known.get("term_type", classify_term_type(term)),
            "noise_reason": "",
            "notes": "",
        }
        return
    candidates[term] = {
        "source_term": term,
        "translation": "",
        "action": "decide",
        "note": "翻译前根据论文领域确认译法；不确定时保留英文并加简短解释。",
        "confidence": confidence,
        "first_seen_block": "",
        "review_status": "needs_review",
        "term_type": classify_term_type(term),
        "noise_reason": "",
        "notes": "",
    }


def title_and_abstract(text: str) -> str:
    lines = [line.strip("# ").strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    abstract_match = re.search(
        r"(?is)(?:^|\n)\s*(?:#+\s*)?abstract\s*\n(?P<body>.*?)(?:\n\s*(?:#+\s*)?(?:introduction|1\.|keywords?)\b|\Z)",
        text,
    )
    abstract = abstract_match.group("body") if abstract_match else ""
    keywords_match = re.search(r"(?im)^Keywords?\s*[:：]\s*(.+)$", text)
    keywords = keywords_match.group(1) if keywords_match else ""
    return "\n".join([title, abstract, keywords, text[:6000]])


def load_blocks(manifest_path: Path | None) -> list[dict[str, Any]]:
    if not manifest_path or not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    blocks = data.get("blocks")
    return blocks if isinstance(blocks, list) else []


def first_seen_block(term: str, blocks: list[dict[str, Any]]) -> str:
    if not term or not blocks:
        return ""
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])") if re.fullmatch(r"[A-Za-z0-9+-]+", term) else None
    for block in blocks:
        text = str(block.get("text") or "")
        found = bool(pattern.search(text)) if pattern else term in text
        if found:
            return str(block.get("block_id") or "")
    return ""


def attach_block_metadata(rows: list[dict[str, str]], blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    for row in rows:
        row.setdefault("review_status", "needs_review")
        row.setdefault("term_type", classify_term_type(row.get("source_term", "")))
        row.setdefault("noise_reason", "")
        row.setdefault("notes", "")
        row["first_seen_block"] = row.get("first_seen_block") or first_seen_block(row.get("source_term", ""), blocks)
    return rows


def extract_candidate_terms(text: str, max_terms: int = 80, blocks: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    scope = title_and_abstract(text)
    candidates: dict[str, dict[str, str]] = {}

    for term in KNOWN_TERMS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", scope):
            add_candidate(candidates, term, confidence="high")

    acronym_counts = Counter(re.findall(r"\b[A-Z][A-Z0-9]{1,}s?\b", scope))
    camel_counts = Counter(re.findall(r"\b[A-Z][A-Za-z]+[A-Z][A-Za-z0-9]*\b", scope))
    phrase_pattern = re.compile(
        r"\b(?:[A-Z][a-z]+|[A-Z]{2,}s?)(?:[ \t]+(?:of|for|and|in|to|the|with|[A-Z][a-z]+|[A-Z]{2,}s?)){1,5}\b"
    )
    phrase_counts = Counter(match.group(0) for match in phrase_pattern.finditer(scope))

    for term, _count in acronym_counts.most_common(40):
        add_candidate(candidates, term, confidence="high" if term in KNOWN_TERMS else "medium")
    for term, _count in camel_counts.most_common(30):
        add_candidate(candidates, term, confidence="medium")
    for term, _count in phrase_counts.most_common(60):
        if len(term.split()) <= 6:
            add_candidate(candidates, term, confidence="medium")

    rows = []
    known_present = [term for term in KNOWN_TERMS if term in candidates]
    for row in candidates.values():
        term = row["source_term"]
        if term not in KNOWN_TERMS and any(term in known and term != known for known in known_present):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (0 if row["source_term"] in KNOWN_TERMS else 1, row["source_term"].lower()))
    return attach_block_metadata(rows[:max_terms], blocks or [])


def write_glossary(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GLOSSARY_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in GLOSSARY_FIELDS})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract a draft glossary from an academic paper source.")
    parser.add_argument("source", help="source.md or another text file.")
    parser.add_argument("--output", help="Output TSV path. Defaults to glossary.tsv beside the source.")
    parser.add_argument("--manifest", help="source_manifest.json path. Defaults to beside the source if present.")
    parser.add_argument("--max-terms", type=int, default=80, help="Maximum terms to keep.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_path = Path(args.source)
    text = source_path.read_text(encoding="utf-8", errors="replace")
    output_path = Path(args.output) if args.output else source_path.with_name("glossary.tsv")
    manifest_path = Path(args.manifest) if args.manifest else source_path.with_name("source_manifest.json")
    rows = extract_candidate_terms(text, max_terms=args.max_terms, blocks=load_blocks(manifest_path))
    write_glossary(rows, output_path)
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
