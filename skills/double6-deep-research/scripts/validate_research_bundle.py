#!/usr/bin/env python3
"""验证报告优先的 double6-deep-research 最小交付合同。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SKILL_VERSION = "2.3.0"
SCHEMA_VERSION = 2
REQUIRED_FILES = (
    "request_snapshot.md",
    "research_plan.md",
    "research_log.md",
    "final_report.md",
    "research_record.json",
)
CANDIDATE_FILES = REQUIRED_FILES
RESEARCH_STATUSES = {"complete", "partial", "blocked"}
QUESTION_STATUSES = {
    "answered",
    "partially_answered",
    "unanswered",
    "unsupported",
}
SOURCE_KINDS = {
    "official_document",
    "scholarly_research",
    "independent_evaluation",
    "industry_analysis",
    "user_or_adoption_evidence",
    "journalism",
    "other",
}
STAKEHOLDER_RELATIONS = {
    "first_party",
    "independent",
    "interested_third_party",
    "user_provided",
    "unknown",
}
SOURCE_ACCESS_STATUSES = {
    "full_text",
    "substantive_sections",
    "metadata_only",
    "unavailable",
}
SOURCE_ORIGINS = {
    "host_opened_page",
    "downloaded_document",
    "user_provided_material",
}
KEY_CLAIM_SOURCE_STATUSES = {"full_text", "substantive_sections"}
COVERAGE_CHECKS = {
    "freshness",
    "counterevidence",
    "omitted_objects",
    "omitted_dimensions",
}
CLAIM_TYPES = {
    "current_fact",
    "quantitative",
    "comparative",
    "recommendation",
    "risk",
    "adoption",
    "background",
}
INDEPENDENT_EVIDENCE_CLAIM_TYPES = {
    "comparative",
    "recommendation",
    "risk",
    "adoption",
}
RESEARCH_ROUND_TYPES = {
    "main_research",
    "coverage_gap_check",
    "adversarial_saturation_check",
}
RESEARCH_STRATEGY_TYPES = {
    "primary_sources",
    "independent_validation",
    "counterevidence",
    "freshness",
    "omission_scan",
    "user_material",
    "citation_snowball",
    "query_diversification",
}
CONCLUSION_IMPACTS = {"changed", "strengthened", "narrowed", "none"}
CLAIM_TYPE_ALIASES = {
    "fact": "current_fact",
    "calculation": "quantitative",
}
CONCLUSION_IMPACT_ALIASES = {
    "unchanged": "none",
    "no_change": "none",
}
SOURCE_KIND_ALIASES = {
    "official": "official_document",
    "news": "journalism",
}
STAKEHOLDER_ALIASES = {
    "first-party": "first_party",
    "third-party": "interested_third_party",
}
NON_CHECK_STRATEGIES = RESEARCH_STRATEGY_TYPES - COVERAGE_CHECKS
UNRESOLVED_ALIASES = (
    "还没查完",
    "未完成",
    "未闭合",
    "still open",
    "open questions",
    "what remains",
    "gaps",
)
CONTINUATION_ALIASES = (
    "本次只补这些缺口",
    "gaps to fill",
    "this pass only",
)
PLAN_HEADING_GROUPS = (
    ("questions", ("要回答的问题", "questions to answer", "research questions", "questions")),
    ("sources", ("准备查的来源", "sources to open", "sources to check", "sources")),
    ("unknowns", ("会标成未知的内容", "marked unknown", "will be unknown", "unknowns")),
)
DECISION_ALIASES = ("假设", "assumptions")
TASK_TYPES = {"open_landscape", "fixed_comparison", "bounded_decision"}
QUERY_FACETS = {
    "core_terms",
    "synonym_or_language",
    "source_type",
    "region_or_market",
    "time_window",
    "entity_specific",
    "adversarial",
    "citation_snowball",
}
# 开放全景的最低底线（不是充分性证明，只用来拦住明显过浅的 complete）。
LANDSCAPE_MIN_QUESTION_SOURCES = 2
LANDSCAPE_MIN_QUERY_FACETS = 4
LANDSCAPE_MIN_SATURATION_NEW_SOURCES = 2
LANDSCAPE_MIN_SATURATION_FACETS = 2
LANDSCAPE_CUES = (
    "全景",
    "格局",
    "综述",
    "进展",
    "版图",
    "图谱",
    "开放调研",
    "landscape",
    "state of",
    "overview",
    "survey of",
    "review of",
)
DECISION_CUES = (
    "预算",
    "该买",
    "选哪",
    "哪一款",
    "decide between",
    "which option",
    "should i buy",
)
EXACT_UNKNOWN_CELLS = {"无", "—", "-", "n/a", "na"}
UNKNOWN_MARKERS = (
    "未知",
    "未核到",
    "这次没核到",
    "未打开",
    "不适用",
    "unknown",
    "not available",
    "not opened",
)
ASSUMPTION_MARKERS = ("假设", "推算", "assumption", "estimated")
NEGATION_PATTERN = re.compile(
    r"没有|未写|没写|未载|没核|未核|找不到|未见|不是|"
    r"\bnot found\b|\bnot in\b|\bdoes not\b|\bdoesn't\b|\bno such\b|\babsent\b",
    re.IGNORECASE,
)
QUANTITATIVE_TOKEN_PATTERN = re.compile(
    r"(?:"
    r"\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{4}-\d{2}-\d{2}"
    r"|[$¥£€]\s?\d+(?:[.,]\d+)?(?:\s?(?:billion|million|thousand))?"
    r"|\d+(?:[.,]\d+)?\s*[%％]"
    r"|百分之(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万两]+)"
    r"|\d+(?:\.\d+)?\s?(?:万元|亿元|万亿元|万亿|美元|迪拉姆|元|万|亿)"
    r"|\d+(?:\.\d+)?\s?(?:yuan|dollars|usd)\b"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+\.\d+"
    r"|第(?:\d+|[零〇一二三四五六七八九十百千万两]+)名"
    r"|(?<!\d)(?!(?:19|20)\d{2}(?!\d))\d{3,6}(?!\d)"
    r")",
    re.IGNORECASE,
)
CN_SMALL_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
PREMATURE_STOP_KEYS = {
    "tool_result_limit_used",
    "preset_source_count_used",
    "time_limit_used",
    "fixed_round_count_used",
}
REVIEW_VERDICTS = {"pass", "fail"}
REVIEW_QUESTION_STATUSES = {
    "complete",
    "partial",
    "unanswered",
    "unsupported",
}
REVIEW_CLAIM_STATUSES = {"verified", "failed", "uncertain"}
REVIEW_INDEPENDENCE_BASES = {"isolated_agent", "independent_human"}
REVIEW_DEPTH_ASSESSMENTS = {"adequate", "insufficient"}
FINDING_SEVERITIES = {"blocker", "major", "minor"}
REQUIRED_REPORT_SECTIONS = {
    "executive_summary",
    "scope_and_method",
    "limitations",
    "sources",
}
EXPLICIT_PLACEHOLDER_PATTERN = re.compile(
    r"(?:\b(?:TODO|TBD|PLACEHOLDER)\b|"
    r"\{\{[^{}\n]+\}\}|"
    r"<\s*(?:todo|placeholder|fill(?:[_ -]?in)?)\b[^>]*>|"
    r"[【\[]\s*待填写\s*[】\]])",
    re.IGNORECASE,
)
SOURCE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]*$")
BRACKET_REFERENCE_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_-]*)\](?!\()")
URL_PATTERN = re.compile(r"https?://[^\s<>\])}\"']+")
ISO_DATE_OR_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))?$"
)
AUTHORIAL_SNAPSHOT_PATTERN = re.compile(
    r"(?:this snapshot was captured for|the captured section describes|"
    r"the research process uses dated|以下内容由研究者(?:整理|概括|总结)|"
    r"本快照用于本次(?:研究|比较))",
    re.IGNORECASE,
)
REPORT_MIN_SUBSTANTIVE_CHARS = 100
ANSWER_SECTION_MIN_SUBSTANTIVE_CHARS = 40


def join_allowed(allowed: set[str]) -> str:
    return "|".join(sorted(allowed))


def substantive_chars(text: str) -> int:
    text = URL_PATTERN.sub("", text)
    return len(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))


def evidence_units(text: str) -> list[str]:
    """把正文段落和 Markdown 表格行分别作为 claim-citation 绑定单元。"""
    units: list[str] = []
    prose: list[str] = []

    def flush_prose() -> None:
        if prose:
            units.append("\n".join(prose).strip())
            prose.clear()

    for line in text.splitlines():
        stripped = line.strip()
        is_table_row = (
            stripped.startswith("|")
            and stripped.endswith("|")
            and stripped.count("|") >= 3
        )
        if is_table_row:
            flush_prose()
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            units.append(stripped)
        elif not stripped:
            flush_prose()
        else:
            prose.append(line)
    flush_prose()
    return [unit for unit in units if unit]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"invalid_text:{path.name}:{exc}")
        return ""


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    text = read_text(path, errors)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid_json:{path.name}:{exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"json_root_not_object:{path.name}")
        return {}
    return value


def exact_heading_exists(report: str, heading: str) -> bool:
    heading = heading.strip()
    return bool(re.fullmatch(r"#{1,6}\s+.+", heading)) and any(
        line.strip() == heading for line in report.splitlines()
    )


def section_text(report: str, heading: str) -> str:
    lines = report.splitlines()
    target = heading.strip()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == target)
    except StopIteration:
        return ""
    level = len(target) - len(target.lstrip("#"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        match = re.match(r"^\s*(#{1,6})\s+", line)
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def valid_answer_section(
    report: str,
    heading: str,
    general_headings: set[str],
) -> bool:
    if not exact_heading_exists(report, heading):
        return False
    if heading in general_headings:
        return False
    body_headings = {
        line.strip()
        for line in section_text(report, heading).splitlines()
        if re.fullmatch(r"#{1,6}\s+.+", line.strip())
    }
    return not bool(body_headings & general_headings)


def valid_iso_date_or_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not ISO_DATE_OR_DATETIME_PATTERN.fullmatch(value):
        return False
    try:
        if "T" not in value:
            dt.date.fromisoformat(value)
            return True
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def validate_string_list(
    value: Any,
    *,
    error_key: str,
    errors: list[str],
    allowed: set[str] | None = None,
    require_nonempty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        errors.append(error_key)
        return []
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        errors.append(f"{error_key}_duplicate")
    if require_nonempty and not normalized:
        errors.append(f"{error_key}_empty")
    if allowed is not None:
        for item in normalized:
            if item not in allowed:
                errors.append(
                    f"{error_key}_invalid:{item}:allowed={join_allowed(allowed)}"
                )
    return normalized


def string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def canonical_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    try:
        host = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    default_port = (
        parsed.scheme == "http" and port == 80
    ) or (
        parsed.scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        )
    )
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def apply_alias(
    value: Any,
    aliases: dict[str, str],
    notes: list[str],
    path: str,
) -> Any:
    if isinstance(value, str) and value in aliases:
        notes.append(f"{path}:{value}->{aliases[value]}")
        return aliases[value]
    return value


def strip_non_checks(value: Any, notes: list[str], path: str) -> Any:
    if not isinstance(value, list):
        return value
    kept: list[Any] = []
    for item in value:
        if isinstance(item, str) and item in NON_CHECK_STRATEGIES:
            notes.append(f"{path}:removed_non_check:{item}")
            continue
        kept.append(item)
    return kept


def normalize_record(record: dict[str, Any]) -> list[str]:
    """接受常见同义词，并去掉误写入检查名单的策略名。不改写原文件。"""
    notes: list[str] = []
    claims = record.get("key_claims")
    if isinstance(claims, list):
        for index, claim in enumerate(claims):
            if isinstance(claim, dict):
                claim["claim_type"] = apply_alias(
                    claim.get("claim_type"),
                    CLAIM_TYPE_ALIASES,
                    notes,
                    f"key_claims[{index}].claim_type",
                )
    sources = record.get("sources")
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            source["source_kind"] = apply_alias(
                source.get("source_kind"),
                SOURCE_KIND_ALIASES,
                notes,
                f"sources[{index}].source_kind",
            )
            source["stakeholder_relation"] = apply_alias(
                source.get("stakeholder_relation"),
                STAKEHOLDER_ALIASES,
                notes,
                f"sources[{index}].stakeholder_relation",
            )
    questions = record.get("questions")
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                continue
            requirements = question.get("coverage_requirements")
            if not isinstance(requirements, dict):
                continue
            question_id = str(question.get("question_id", "")).strip() or "?"
            requirements["required_checks"] = strip_non_checks(
                requirements.get("required_checks"),
                notes,
                f"{question_id}.required_checks",
            )
    rounds = record.get("research_rounds")
    if isinstance(rounds, list):
        for research_round in rounds:
            if not isinstance(research_round, dict):
                continue
            round_id = str(research_round.get("round_id", "")).strip() or "?"
            impact = research_round.get("conclusion_impact")
            if isinstance(impact, dict):
                for key, value in list(impact.items()):
                    impact[key] = apply_alias(
                        value,
                        CONCLUSION_IMPACT_ALIASES,
                        notes,
                        f"{round_id}.conclusion_impact.{key}",
                    )
            checks = research_round.get("checks_completed")
            if isinstance(checks, dict):
                for key, value in list(checks.items()):
                    checks[key] = strip_non_checks(
                        value,
                        notes,
                        f"{round_id}.checks_completed.{key}",
                    )
    stop = record.get("stop_decision")
    if isinstance(stop, dict):
        unchecked = stop.get("unchecked_required_checks")
        if isinstance(unchecked, dict):
            for key, value in list(unchecked.items()):
                unchecked[key] = strip_non_checks(
                    value,
                    notes,
                    f"stop_decision.unchecked_required_checks.{key}",
                )
    return notes


def quantitative_tokens(text: str) -> list[str]:
    return QUANTITATIVE_TOKEN_PATTERN.findall(text)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def loose(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).casefold()


def loose_contains(haystack: str, needle: str) -> bool:
    folded = loose(needle)
    return bool(folded) and folded in loose(haystack)


def find_heading(text: str, aliases: tuple[str, ...]) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not re.fullmatch(r"#{1,6}\s+.+", stripped):
            continue
        title = re.sub(r"^#{1,6}\s+", "", stripped).casefold()
        if any(alias.casefold() in title for alias in aliases):
            return stripped
    return ""


def find_headings(text: str, aliases: tuple[str, ...]) -> list[str]:
    """Return every Markdown heading whose title contains one of the aliases."""
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not re.fullmatch(r"#{1,6}\s+.+", stripped):
            continue
        title = re.sub(r"^#{1,6}\s+", "", stripped).casefold()
        if any(alias.casefold() in title for alias in aliases):
            found.append(stripped)
    return found


def heading_title(heading: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", heading.strip()).strip()


def find_question_list_heading(
    plan: str,
    aliases: tuple[str, ...],
    questions: list[dict[str, Any]],
) -> str:
    """Pick the plan heading that really lists the recorded questions.

    Loose alias matching alone misfires on headings that merely mention the
    word (for example "Discovery (before freezing questions)").  Among all
    candidate headings, prefer the one whose section contains the most
    recorded question IDs/texts; break ties by an exact alias title, then by
    document order.  Falls back to the first candidate for old bundles.
    """
    candidates = find_headings(plan, aliases)
    if not candidates:
        return ""
    folded_aliases = {loose(alias) for alias in aliases}

    def score(heading: str) -> tuple[int, int]:
        body = section_text(plan, heading)
        hits = 0
        for question in questions:
            text = str(question.get("question", "")).strip()
            qid = str(question.get("question_id", "")).strip()
            if (text and loose_contains(body, text)) or (
                qid and re.search(rf"(?<![A-Za-z0-9]){re.escape(qid)}(?![0-9])", body)
            ):
                hits += 1
        exact = 1 if loose(heading_title(heading)) in folded_aliases else 0
        return hits, exact

    best = candidates[0]
    best_score = score(best)
    for heading in candidates[1:]:
        current = score(heading)
        if current > best_score:
            best, best_score = heading, current
    return best


def canonical_day(value: str) -> str | None:
    value = value.strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    chinese = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if chinese:
        return (
            f"{chinese.group(1)}-"
            f"{int(chinese.group(2)):02d}-"
            f"{int(chinese.group(3)):02d}"
        )
    return None


def recorded_calendar_days(record: dict[str, Any]) -> set[str]:
    days: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str):
            day = canonical_day(value)
            if day:
                days.add(day)

    add(record.get("research_as_of"))
    sources = record.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            add(source.get("accessed_at"))
            add(source.get("published_at"))
    return days


def claim_tokens(text: str, recorded_days: set[str]) -> list[str]:
    tokens: list[str] = []
    for token in quantitative_tokens(text):
        day = canonical_day(token)
        if day and day in recorded_days:
            continue
        tokens.append(token)
    return tokens


def parse_cn_small(text: str) -> int | None:
    if text == "十":
        return 10
    if text == "百":
        return 100
    if "十" in text:
        left, _, right = text.partition("十")
        if left == "":
            tens = 1
        elif left in CN_SMALL_DIGITS:
            tens = CN_SMALL_DIGITS[left]
        else:
            return None
        if right == "":
            ones = 0
        elif right in CN_SMALL_DIGITS:
            ones = CN_SMALL_DIGITS[right]
        else:
            return None
        return tens * 10 + ones
    if text in CN_SMALL_DIGITS:
        return CN_SMALL_DIGITS[text]
    return None


def percent_digits(token: str) -> str | None:
    match = re.fullmatch(r"百分之(.+)", token.strip())
    if not match:
        return None
    rest = match.group(1)
    if re.fullmatch(r"\d+(?:\.\d+)?", rest):
        return rest
    value = parse_cn_small(rest)
    if value is None:
        return None
    return str(value)


def number_core(token: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)*", token)
    if not match:
        return ""
    return match.group(0).replace(",", "")


def token_in_text(haystack: str, token: str) -> bool:
    folded = compact(haystack)
    if compact(token) in folded:
        return True
    day = canonical_day(token)
    if day:
        year, month, day_num = day.split("-")
        variants = (
            day,
            f"{year}年{int(month)}月{int(day_num)}日",
            f"{year}/{int(month)}/{int(day_num)}",
        )
        return any(compact(item) in folded for item in variants)
    percent = percent_digits(token)
    if percent is not None:
        return f"{percent}%" in folded or f"{percent}％" in folded
    if re.search(r"[%％]|百分之|第|名", token):
        return False
    core = number_core(token)
    return bool(core) and core in folded.replace(",", "")


def compact_contains(haystack: str, needle: str) -> bool:
    folded = compact(needle)
    return bool(folded) and folded in compact(haystack)


def has_marker(text: str, markers: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(marker.casefold() in folded for marker in markers)


def cell_is_unknown(cell: str) -> bool:
    if cell.strip().casefold() in EXACT_UNKNOWN_CELLS:
        return True
    return has_marker(cell, UNKNOWN_MARKERS)


def follow_up_present(section: str, question_text: str) -> bool:
    folded_question = loose(question_text)
    chunks = [chunk for chunk in re.split(r"\n+", section) if chunk.strip()]
    contexts = [
        chunk
        for chunk in chunks
        if folded_question and folded_question in loose(chunk)
    ] or [section]
    for chunk in contexts:
        remaining = loose(chunk).replace(folded_question, "", 1)
        if substantive_chars(remaining) >= 4:
            return True
    return False


def split_sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[。！？\n]", text)
        if part.strip()
    ]


def heading_sections(report: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    body: list[str] = []
    for line in report.splitlines():
        if re.fullmatch(r"#{1,6}\s+.+", line.strip()):
            if current_heading:
                sections.append((current_heading, "\n".join(body)))
            current_heading = line.strip()
            body = []
        else:
            body.append(line)
    if current_heading:
        sections.append((current_heading, "\n".join(body)))
    return sections


def markdown_table_rows(text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        is_row = (
            stripped.startswith("|")
            and stripped.endswith("|")
            and stripped.count("|") >= 2
        )
        if is_row:
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def validate_source(
    bundle: Path,
    source: Any,
    question_ids: set[str],
    source_ids: set[str],
    source_access_statuses: dict[str, str],
    snapshot_texts: dict[str, str],
    errors: list[str],
) -> None:
    if not isinstance(source, dict):
        errors.append("source_not_object")
        return
    source_id = str(source.get("source_id", "")).strip()
    if not source_id:
        errors.append("source_id_missing")
        return
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        errors.append(f"source_id_invalid:{source_id}")
    if source_id in source_ids:
        errors.append(f"duplicate_source_id:{source_id}")
    source_ids.add(source_id)
    for field in ("title", "url", "publisher", "accessed_at", "access_status"):
        if not str(source.get(field, "")).strip():
            errors.append(f"source_field_missing:{source_id}:{field}")
    if canonical_url(source.get("url")) is None:
        errors.append(f"source_url_invalid:{source_id}")
    if not valid_iso_date_or_datetime(source.get("accessed_at")):
        errors.append(f"source_accessed_at_invalid:{source_id}")
    published_at = source.get("published_at")
    if published_at is not None and not valid_iso_date_or_datetime(published_at):
        errors.append(f"source_published_at_invalid:{source_id}")
    if source.get("access_status") not in SOURCE_ACCESS_STATUSES:
        errors.append(
            f"source_access_status_invalid:{source_id}:"
            f"field=access_status:allowed={join_allowed(SOURCE_ACCESS_STATUSES)}"
        )
    if source.get("content_origin") not in SOURCE_ORIGINS:
        errors.append(
            f"source_origin_invalid:{source_id}:"
            f"field=content_origin:allowed={join_allowed(SOURCE_ORIGINS)}"
        )
    if source.get("source_kind") not in SOURCE_KINDS:
        errors.append(
            f"source_kind_invalid:{source_id}:"
            f"field=source_kind:allowed={join_allowed(SOURCE_KINDS)}"
        )
    if source.get("stakeholder_relation") not in STAKEHOLDER_RELATIONS:
        errors.append(
            f"source_stakeholder_relation_invalid:{source_id}:"
            f"field=stakeholder_relation:allowed={join_allowed(STAKEHOLDER_RELATIONS)}"
        )

    covered_questions = source.get("question_ids")
    if not isinstance(covered_questions, list) or not covered_questions:
        errors.append(f"source_question_ids_missing:{source_id}")
    else:
        for question_id in covered_questions:
            if not isinstance(question_id, str):
                errors.append(f"source_question_id_invalid:{source_id}")
            elif question_id not in question_ids:
                errors.append(
                    f"source_unknown_question:{source_id}:{question_id}"
                )

    source_access_statuses[source_id] = str(
        source.get("access_status", "")
    ).strip()
    snapshot_texts.setdefault(source_id, "")

    snapshot_value = source.get("snapshot_path")
    if snapshot_value is None:
        return
    snapshot_relative = Path(str(snapshot_value))
    if snapshot_relative.is_absolute() or ".." in snapshot_relative.parts:
        errors.append(f"source_snapshot_outside_bundle:{source_id}")
        return
    bundle_root = bundle.resolve()
    snapshot = (bundle_root / snapshot_relative).resolve()
    if not snapshot.is_relative_to(bundle_root):
        errors.append(f"source_snapshot_outside_bundle:{source_id}")
        return
    if not snapshot.is_file():
        errors.append(f"source_snapshot_missing:{source_id}:{snapshot_value}")
        return
    declared_sha = str(source.get("snapshot_sha256", "")).strip()
    if not declared_sha or sha256_file(snapshot) != declared_sha:
        errors.append(f"source_snapshot_sha_mismatch:{source_id}")
    snapshot_text = read_text(snapshot, errors)
    snapshot_texts[source_id] = snapshot_text
    if snapshot_text and AUTHORIAL_SNAPSHOT_PATTERN.search(snapshot_text):
        errors.append(f"researcher_authored_snapshot:{source_id}")


def validate_report_sections(
    report: str,
    record: dict[str, Any],
    errors: list[str],
) -> None:
    sections = record.get("report_sections")
    if not isinstance(sections, dict):
        errors.append(
            "report_sections_missing:expected_object_keys="
            + join_allowed(REQUIRED_REPORT_SECTIONS)
        )
        return
    for section_key in sorted(REQUIRED_REPORT_SECTIONS):
        heading = sections.get(section_key)
        if not isinstance(heading, str) or not exact_heading_exists(report, heading):
            errors.append(f"report_section_missing:{section_key}")
    declared_headings = [
        sections.get(section_key)
        for section_key in REQUIRED_REPORT_SECTIONS
        if isinstance(sections.get(section_key), str)
    ]
    if len(declared_headings) != len(set(declared_headings)):
        errors.append("report_sections_not_unique")


def validate_questions(
    report: str,
    record: dict[str, Any],
    research_status: str,
    errors: list[str],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    value = record.get("questions")
    if not isinstance(value, list) or not value:
        errors.append("questions_missing")
        return [], set()
    questions: list[dict[str, Any]] = []
    question_ids: set[str] = set()
    report_sections = record.get("report_sections")
    general_headings = (
        {
            heading.strip()
            for heading in report_sections.values()
            if isinstance(heading, str) and heading.strip()
        }
        if isinstance(report_sections, dict)
        else set()
    )
    used_answer_sections: dict[str, str] = {}
    for index, question in enumerate(value):
        if not isinstance(question, dict):
            errors.append(f"question_not_object:{index}")
            continue
        question_id = str(question.get("question_id", "")).strip()
        if not question_id:
            detail = "expected_field=question_id"
            if str(question.get("id", "")).strip():
                detail += ":found_field=id"
            errors.append(f"question_id_missing:{index}:{detail}")
            continue
        if question_id in question_ids:
            errors.append(f"duplicate_question_id:{question_id}")
        question_ids.add(question_id)
        questions.append(question)
        if not str(question.get("question", "")).strip():
            errors.append(f"question_text_missing:{question_id}")
        status = question.get("status")
        if status not in QUESTION_STATUSES:
            errors.append(
                f"question_status_invalid:{question_id}:"
                f"field=status:allowed={join_allowed(QUESTION_STATUSES)}"
            )
        if research_status == "complete" and status != "answered":
            errors.append(f"complete_question_not_answered:{question_id}")
        requirements = question.get("coverage_requirements")
        if not isinstance(requirements, dict):
            errors.append(
                f"question_coverage_requirements_missing:{question_id}:"
                "expected_field=coverage_requirements:"
                "expected_fields=required_source_kinds|"
                "independent_evidence_required|required_checks|"
                "required_objects|required_dimensions"
            )
        else:
            validate_string_list(
                requirements.get("required_source_kinds"),
                error_key=f"question_required_source_kinds:{question_id}",
                errors=errors,
                allowed=SOURCE_KINDS,
                require_nonempty=True,
            )
            if not isinstance(
                requirements.get("independent_evidence_required"),
                bool,
            ):
                errors.append(
                    f"question_independent_requirement_invalid:{question_id}"
                )
            validate_string_list(
                requirements.get("required_checks"),
                error_key=f"question_required_checks:{question_id}",
                errors=errors,
                allowed=COVERAGE_CHECKS,
                require_nonempty=True,
            )
            validate_string_list(
                requirements.get("required_objects"),
                error_key=f"question_required_objects:{question_id}",
                errors=errors,
            )
            validate_string_list(
                requirements.get("required_dimensions"),
                error_key=f"question_required_dimensions:{question_id}",
                errors=errors,
            )
        answer_section = str(question.get("answer_section", "")).strip()
        if status in {"answered", "partially_answered", "unsupported"}:
            if not exact_heading_exists(report, answer_section):
                errors.append(f"question_answer_section_missing:{question_id}")
            elif not valid_answer_section(
                report,
                answer_section,
                general_headings,
            ):
                errors.append(f"question_answer_section_invalid:{question_id}")
            elif (
                substantive_chars(section_text(report, answer_section))
                < ANSWER_SECTION_MIN_SUBSTANTIVE_CHARS
            ):
                errors.append(f"question_answer_section_too_short:{question_id}")
            previous_question_id = used_answer_sections.get(answer_section)
            if previous_question_id:
                errors.append(
                    f"question_answer_section_not_unique:"
                    f"{previous_question_id}:{question_id}"
                )
            elif answer_section:
                used_answer_sections[answer_section] = question_id
        elif answer_section and not exact_heading_exists(report, answer_section):
            errors.append(f"question_answer_section_missing:{question_id}")
        if research_status == "partial" and status != "answered":
            if not str(question.get("current_evidence", "")).strip():
                errors.append(
                    f"partial_question_current_evidence_missing:{question_id}:"
                    "expected_field=current_evidence"
                )
            if not str(question.get("next_step", "")).strip():
                errors.append(
                    f"partial_question_next_step_missing:{question_id}:"
                    "expected_field=next_step"
                )
    if research_status == "partial" and all(
        item.get("status") == "answered" for item in questions
    ):
        errors.append("partial_has_no_open_question")
    brief_threshold = max(300, 150 * len(questions))
    if substantive_chars(report) < brief_threshold:
        warnings.append(
            f"report_brief_for_question_count:{substantive_chars(report)}:{brief_threshold}"
        )
    return questions, question_ids


def validate_key_claims(
    report: str,
    record: dict[str, Any],
    research_status: str,
    questions: list[dict[str, Any]],
    question_ids: set[str],
    source_ids: set[str],
    source_access_statuses: dict[str, str],
    source_stakeholder_relations: dict[str, str],
    source_question_ids: dict[str, set[str]],
    errors: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    value = record.get("key_claims")
    if not isinstance(value, list):
        errors.append("key_claims_missing")
        return [], set()
    if research_status == "complete" and not value:
        errors.append("complete_key_claims_missing")
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    units = evidence_units(report)
    report_sections = record.get("report_sections")
    general_headings = (
        {
            heading.strip()
            for heading in report_sections.values()
            if isinstance(heading, str) and heading.strip()
        }
        if isinstance(report_sections, dict)
        else set()
    )
    question_answer_units = {
        str(question.get("question_id", "")).strip(): evidence_units(
            section_text(
                report,
                str(question.get("answer_section", "")).strip(),
            )
        )
        for question in questions
        if valid_answer_section(
            report,
            str(question.get("answer_section", "")).strip(),
            general_headings,
        )
    }
    for index, claim in enumerate(value):
        if not isinstance(claim, dict):
            errors.append(f"key_claim_not_object:{index}")
            continue
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id:
            errors.append(f"key_claim_id_missing:{index}")
            continue
        if claim_id in claim_ids:
            errors.append(f"duplicate_key_claim_id:{claim_id}")
        claim_ids.add(claim_id)
        claims.append(claim)
        claim_type = claim.get("claim_type")
        if claim_type not in CLAIM_TYPES:
            errors.append(
                f"key_claim_type_invalid:{claim_id}:"
                f"field=claim_type:allowed={join_allowed(CLAIM_TYPES)}"
            )
        claim_text = str(claim.get("claim", "")).strip()
        matching_units = [
            unit for unit in units if claim_text and claim_text in unit
        ]
        if not matching_units:
            errors.append(f"key_claim_not_in_report:{claim_id}")
        claim_question_ids = claim.get("question_ids")
        normalized_claim_question_ids: list[str] = []
        if not isinstance(claim_question_ids, list) or not claim_question_ids:
            errors.append(f"key_claim_question_ids_missing:{claim_id}")
        else:
            for question_id in claim_question_ids:
                if not isinstance(question_id, str):
                    errors.append(f"key_claim_question_id_invalid:{claim_id}")
                elif question_id not in question_ids:
                    errors.append(
                        f"key_claim_unknown_question:{claim_id}:{question_id}"
                    )
                else:
                    normalized_claim_question_ids.append(question_id)
        claim_source_ids = claim.get("source_ids")
        if not isinstance(claim_source_ids, list) or not claim_source_ids:
            errors.append(f"key_claim_sources_missing:{claim_id}")
            continue
        has_substantive_independent_source = False
        for source_id in claim_source_ids:
            if not isinstance(source_id, str):
                errors.append(f"key_claim_source_id_invalid:{claim_id}")
                continue
            if source_id not in source_ids:
                errors.append(f"key_claim_unknown_source:{claim_id}:{source_id}")
                continue
            for question_id in normalized_claim_question_ids:
                if question_id not in source_question_ids.get(source_id, set()):
                    errors.append(
                        f"key_claim_source_question_mismatch:"
                        f"{claim_id}:{source_id}:{question_id}"
                    )
            if source_access_statuses.get(source_id) not in KEY_CLAIM_SOURCE_STATUSES:
                errors.append(
                    f"key_claim_source_not_substantive:{claim_id}:{source_id}"
                )
            elif source_stakeholder_relations.get(source_id) == "independent":
                has_substantive_independent_source = True
            if not any(f"[{source_id}]" in unit for unit in matching_units):
                errors.append(
                    f"key_claim_source_not_cited_with_claim:{claim_id}:{source_id}"
                )
            for question_id in normalized_claim_question_ids:
                if not any(
                    claim_text in unit and f"[{source_id}]" in unit
                    for unit in question_answer_units.get(question_id, [])
                ):
                    errors.append(
                        f"key_claim_source_not_cited_in_answer:"
                        f"{claim_id}:{source_id}:{question_id}"
                    )
        if (
            research_status == "complete"
            and claim_type in INDEPENDENT_EVIDENCE_CLAIM_TYPES
            and not has_substantive_independent_source
        ):
            errors.append(f"key_claim_independent_evidence_missing:{claim_id}")
    return claims, claim_ids


def validate_round_item_map(
    value: Any,
    *,
    field: str,
    round_id: str,
    target_question_ids: set[str],
    question_ids: set[str],
    errors: list[str],
    allowed: set[str] | None = None,
    require_nonempty: bool = False,
    require_all_targets: bool = True,
) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        errors.append(f"research_round_{field}_invalid:{round_id}")
        return {}
    normalized: dict[str, list[str]] = {}
    for question_id, items in value.items():
        if question_id not in question_ids:
            errors.append(
                f"research_round_{field}_unknown_question:{round_id}:{question_id}"
            )
        if question_id not in target_question_ids:
            errors.append(
                f"research_round_{field}_untargeted_question:{round_id}:{question_id}"
            )
        normalized[question_id] = validate_string_list(
            items,
            error_key=f"research_round_{field}:{round_id}:{question_id}",
            errors=errors,
            allowed=allowed,
            require_nonempty=require_nonempty,
        )
    if require_all_targets:
        for question_id in sorted(target_question_ids - set(value)):
            errors.append(
                f"research_round_{field}_missing_question:"
                f"{round_id}:{question_id}"
            )
    return normalized


def validate_round_impact_map(
    value: Any,
    *,
    round_id: str,
    target_question_ids: set[str],
    question_ids: set[str],
    errors: list[str],
) -> dict[str, str]:
    if not isinstance(value, dict):
        errors.append(
            f"research_round_conclusion_impact_invalid:{round_id}:"
            f"field=conclusion_impact:allowed={join_allowed(CONCLUSION_IMPACTS)}"
        )
        return {}
    normalized: dict[str, str] = {}
    for question_id, impact in value.items():
        if question_id not in question_ids:
            errors.append(
                f"research_round_impact_unknown_question:"
                f"{round_id}:{question_id}"
            )
        if question_id not in target_question_ids:
            errors.append(
                f"research_round_impact_untargeted_question:"
                f"{round_id}:{question_id}"
            )
        if impact not in CONCLUSION_IMPACTS:
            errors.append(
                f"research_round_conclusion_impact_invalid:"
                f"{round_id}:{question_id}:"
                f"field=conclusion_impact:allowed={join_allowed(CONCLUSION_IMPACTS)}"
            )
        elif isinstance(question_id, str):
            normalized[question_id] = impact
    for question_id in sorted(target_question_ids - set(value)):
        errors.append(
            f"research_round_impact_missing_question:{round_id}:{question_id}"
        )
    return normalized


def validate_rounds(
    record: dict[str, Any],
    research_status: str,
    question_ids: set[str],
    errors: list[str],
) -> list[dict[str, Any]]:
    value = record.get("research_rounds")
    if not isinstance(value, list):
        errors.append("research_rounds_missing")
        return []
    rounds: list[dict[str, Any]] = []
    round_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"research_round_not_object:{index}")
            continue
        rounds.append(item)
        round_id = str(item.get("round_id", "")).strip()
        if not round_id:
            errors.append(f"research_round_id_missing:{index}")
            round_id = str(index)
        elif round_id in round_ids:
            errors.append(f"duplicate_research_round_id:{round_id}")
        round_ids.add(round_id)
        if item.get("round_type") not in RESEARCH_ROUND_TYPES:
            errors.append(
                f"research_round_type_invalid:{round_id}:"
                f"field=round_type:allowed={join_allowed(RESEARCH_ROUND_TYPES)}"
            )
        targets = validate_string_list(
            item.get("target_question_ids"),
            error_key=f"research_round_target_questions:{round_id}",
            errors=errors,
            require_nonempty=True,
        )
        target_set = set(targets)
        for question_id in targets:
            if question_id not in question_ids:
                errors.append(
                    f"research_round_unknown_question:{round_id}:{question_id}"
                )
        validate_round_item_map(
            item.get("strategy_types"),
            field="strategy_types",
            round_id=round_id,
            target_question_ids=target_set,
            question_ids=question_ids,
            errors=errors,
            allowed=RESEARCH_STRATEGY_TYPES,
            require_nonempty=True,
        )
        validate_round_item_map(
            item.get("checks_completed"),
            field="checks_completed",
            round_id=round_id,
            target_question_ids=target_set,
            question_ids=question_ids,
            errors=errors,
            allowed=COVERAGE_CHECKS,
        )
        validate_round_item_map(
            item.get("objects_checked"),
            field="objects_checked",
            round_id=round_id,
            target_question_ids=target_set,
            question_ids=question_ids,
            errors=errors,
        )
        validate_round_item_map(
            item.get("dimensions_checked"),
            field="dimensions_checked",
            round_id=round_id,
            target_question_ids=target_set,
            question_ids=question_ids,
            errors=errors,
        )
        validate_round_impact_map(
            item.get("conclusion_impact"),
            round_id=round_id,
            target_question_ids=target_set,
            question_ids=question_ids,
            errors=errors,
        )

    if research_status == "partial" and not any(
        item.get("round_type") == "main_research" for item in rounds
    ):
        errors.append("research_round_type_missing:main_research")
    if research_status == "complete":
        if not any(
            item.get("round_type") == "adversarial_saturation_check"
            for item in rounds
        ):
            errors.append(
                "research_round_type_missing:adversarial_saturation_check"
            )
        for question_id in sorted(question_ids):
            for required_type in RESEARCH_ROUND_TYPES:
                if not any(
                    item.get("round_type") == required_type
                    and question_id
                    in string_items(item.get("target_question_ids"))
                    for item in rounds
                ):
                    errors.append(
                        f"research_round_question_not_covered:"
                        f"{question_id}:{required_type}"
                    )
            main_indices = [
                index
                for index, item in enumerate(rounds)
                if item.get("round_type") == "main_research"
                and question_id in string_items(item.get("target_question_ids"))
            ]
            gap_indices = [
                index
                for index, item in enumerate(rounds)
                if item.get("round_type") == "coverage_gap_check"
                and question_id in string_items(item.get("target_question_ids"))
            ]
            saturation_indices = [
                index
                for index, item in enumerate(rounds)
                if item.get("round_type") == "adversarial_saturation_check"
                and question_id in string_items(item.get("target_question_ids"))
            ]
            if (
                main_indices
                and gap_indices
                and saturation_indices
                and not any(
                    main_index < gap_index < saturation_index
                    for main_index in main_indices
                    for gap_index in gap_indices
                    for saturation_index in saturation_indices
                )
            ):
                errors.append(
                    f"research_round_order_invalid:{question_id}"
                )
    return rounds


def build_coverage_diagnostics(
    report: str,
    record: dict[str, Any],
    questions: list[dict[str, Any]],
    sources: list[Any],
    rounds: list[dict[str, Any]],
    research_status: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    report_sections = record.get("report_sections")
    general_headings = (
        {
            heading.strip()
            for heading in report_sections.values()
            if isinstance(heading, str) and heading.strip()
        }
        if isinstance(report_sections, dict)
        else set()
    )
    for question in questions:
        question_id = str(question.get("question_id", "")).strip()
        requirements = question.get("coverage_requirements")
        if not isinstance(requirements, dict):
            requirements = {}
        required_source_kinds = set(
            string_items(requirements.get("required_source_kinds"))
        )
        required_checks = set(
            string_items(requirements.get("required_checks"))
        )
        required_objects = set(
            string_items(requirements.get("required_objects"))
        )
        required_dimensions = set(
            string_items(requirements.get("required_dimensions"))
        )
        covered_source_kinds: set[str] = set()
        independent_source_ids: set[str] = set()
        substantive_source_ids: set[str] = set()
        answer_section = str(question.get("answer_section", "")).strip()
        answer_source_ids = (
            set(
                BRACKET_REFERENCE_PATTERN.findall(
                    section_text(report, answer_section)
                )
            )
            if valid_answer_section(
                report,
                answer_section,
                general_headings,
            )
            else set()
        )
        for source in sources:
            if (
                not isinstance(source, dict)
                or question_id not in string_items(source.get("question_ids"))
                or source.get("access_status") not in KEY_CLAIM_SOURCE_STATUSES
                or str(source.get("source_id", "")).strip()
                not in answer_source_ids
            ):
                continue
            source_id = str(source.get("source_id", "")).strip()
            if source_id:
                substantive_source_ids.add(source_id)
            source_kind = source.get("source_kind")
            if source_kind in SOURCE_KINDS:
                covered_source_kinds.add(source_kind)
            if source.get("stakeholder_relation") == "independent" and source_id:
                independent_source_ids.add(source_id)

        checks_completed: set[str] = set()
        checked_objects: set[str] = set()
        checked_dimensions: set[str] = set()
        main_strategies: set[str] = set()
        last_saturation_strategies: set[str] = set()
        last_saturation_checks: set[str] = set()
        last_saturation_impact: str | None = None
        last_saturation_index: int | None = None
        for round_index, round_item in enumerate(rounds):
            if question_id not in string_items(
                round_item.get("target_question_ids")
            ):
                continue
            checks_map = round_item.get("checks_completed")
            round_checks = set(
                item
                for item in string_items(
                    checks_map.get(question_id)
                    if isinstance(checks_map, dict)
                    else None
                )
                if item in COVERAGE_CHECKS
            )
            checks_completed.update(round_checks)
            strategies_map = round_item.get("strategy_types")
            round_strategies = set(
                item
                for item in string_items(
                    strategies_map.get(question_id)
                    if isinstance(strategies_map, dict)
                    else None
                )
                if item in RESEARCH_STRATEGY_TYPES
            )
            if round_item.get("round_type") == "main_research":
                main_strategies.update(round_strategies)
            objects_map = round_item.get("objects_checked")
            if isinstance(objects_map, dict):
                checked_objects.update(
                    string_items(objects_map.get(question_id))
                )
            dimensions_map = round_item.get("dimensions_checked")
            if isinstance(dimensions_map, dict):
                checked_dimensions.update(
                    string_items(dimensions_map.get(question_id))
                )
            if (
                round_item.get("round_type")
                == "adversarial_saturation_check"
            ):
                impact = round_item.get("conclusion_impact")
                impact_value = (
                    impact.get(question_id)
                    if isinstance(impact, dict)
                    else None
                )
                if impact_value in CONCLUSION_IMPACTS:
                    last_saturation_impact = impact_value
                    last_saturation_index = round_index
                    last_saturation_strategies = round_strategies
                    last_saturation_checks = round_checks
        post_saturation_material_change = bool(
            last_saturation_index is not None
            and any(
                question_id
                in string_items(round_item.get("target_question_ids"))
                and (
                    round_item.get("conclusion_impact", {}).get(question_id)
                    if isinstance(
                        round_item.get("conclusion_impact"),
                        dict,
                    )
                    else None
                )
                != "none"
                for round_item in rounds[last_saturation_index + 1 :]
            )
        )

        missing_source_kinds = required_source_kinds - covered_source_kinds
        independent_evidence_missing = bool(
            requirements.get("independent_evidence_required") is True
            and not independent_source_ids
        )
        missing_checks = required_checks - last_saturation_checks
        missing_objects = required_objects - checked_objects
        missing_dimensions = required_dimensions - checked_dimensions
        diagnostic = {
            "question_id": question_id,
            "required_source_kinds": sorted(required_source_kinds),
            "covered_source_kinds": sorted(covered_source_kinds),
            "substantive_source_ids": sorted(substantive_source_ids),
            "independent_source_ids": sorted(independent_source_ids),
            "missing_source_kinds": sorted(missing_source_kinds),
            "independent_evidence_missing": independent_evidence_missing,
            "required_checks": sorted(required_checks),
            "checks_completed": sorted(checks_completed),
            "last_saturation_checks": sorted(last_saturation_checks),
            "missing_checks": sorted(missing_checks),
            "main_strategies": sorted(main_strategies),
            "last_saturation_strategies": sorted(last_saturation_strategies),
            "required_objects": sorted(required_objects),
            "checked_objects": sorted(checked_objects),
            "missing_objects": sorted(missing_objects),
            "required_dimensions": sorted(required_dimensions),
            "checked_dimensions": sorted(checked_dimensions),
            "missing_dimensions": sorted(missing_dimensions),
            "last_saturation_impact": last_saturation_impact,
            "post_saturation_material_change": post_saturation_material_change,
        }
        diagnostics.append(diagnostic)
        if research_status == "complete":
            if missing_source_kinds:
                errors.append(
                    f"question_source_kinds_not_covered:{question_id}:"
                    f"{','.join(sorted(missing_source_kinds))}"
                )
            if independent_evidence_missing:
                errors.append(
                    f"question_independent_evidence_missing:{question_id}"
                )
            if missing_checks:
                errors.append(
                    f"question_checks_not_completed:{question_id}:"
                    f"{','.join(sorted(missing_checks))}"
                )
            if missing_objects:
                errors.append(
                    f"question_objects_not_checked:{question_id}:"
                    f"{','.join(sorted(missing_objects))}"
                )
            if missing_dimensions:
                errors.append(
                    f"question_dimensions_not_checked:{question_id}:"
                    f"{','.join(sorted(missing_dimensions))}"
                )
            if last_saturation_impact != "none":
                errors.append(
                    f"question_not_saturated:{question_id}:"
                    f"{last_saturation_impact or 'missing'}"
                )
            if post_saturation_material_change:
                errors.append(
                    f"question_changed_after_saturation:{question_id}"
                )
            adversarial_strategies = {
                "independent_validation",
                "counterevidence",
                "freshness",
                "omission_scan",
            }
            if not (
                last_saturation_strategies & adversarial_strategies
            ):
                errors.append(
                    f"question_saturation_strategy_not_adversarial:{question_id}"
                )
            if (
                last_saturation_strategies
                and last_saturation_strategies == main_strategies
            ):
                errors.append(
                    f"question_saturation_strategy_not_distinct:{question_id}"
                )
    return diagnostics


def validate_gap(
    gap: Any,
    question_ids: set[str],
    prefix: str,
    errors: list[str],
) -> None:
    if not isinstance(gap, dict):
        errors.append(f"{prefix}_gap_not_object")
        return
    question_id = gap.get("question_id")
    if not isinstance(question_id, str) or question_id not in question_ids:
        errors.append(f"{prefix}_gap_unknown_question:{question_id}")
    for field in ("gap", "current_evidence", "next_step"):
        if not str(gap.get(field, "")).strip():
            errors.append(f"{prefix}_gap_field_missing:{question_id}:{field}")
    gap_type = gap.get("gap_type")
    if gap_type not in {
        "missing_source_kind",
        "missing_independent_evidence",
        "unchecked_required_check",
        "unchecked_object",
        "unchecked_dimension",
        "unresolved_conflict",
        "other",
    }:
        errors.append(f"{prefix}_gap_type_invalid:{question_id}")
    validate_string_list(
        gap.get("missing_items"),
        error_key=f"{prefix}_gap_missing_items:{question_id}",
        errors=errors,
        require_nonempty=True,
    )


def validate_stop_item_map(
    value: Any,
    *,
    field: str,
    question_ids: set[str],
    errors: list[str],
    allowed: set[str] | None = None,
) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        errors.append(f"stop_{field}_invalid")
        return {}
    normalized: dict[str, list[str]] = {}
    for question_id, items in value.items():
        if question_id not in question_ids:
            errors.append(f"stop_{field}_unknown_question:{question_id}")
        parsed = validate_string_list(
            items,
            error_key=f"stop_{field}:{question_id}",
            errors=errors,
            allowed=allowed,
            require_nonempty=True,
        )
        if parsed:
            normalized[question_id] = sorted(parsed)
    return normalized


def validate_stop_decision(
    record: dict[str, Any],
    research_status: str,
    question_ids: set[str],
    coverage_diagnostics: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if research_status == "partial":
        return
    stop = record.get("stop_decision")
    if not isinstance(stop, dict):
        errors.append("stop_decision_missing")
        return
    if stop.get("status") != research_status:
        errors.append("stop_decision_status_mismatch")
    expected_source_kinds = {
        item["question_id"]: item["missing_source_kinds"]
        for item in coverage_diagnostics
        if item["missing_source_kinds"]
    }
    expected_independent = sorted(
        item["question_id"]
        for item in coverage_diagnostics
        if item["independent_evidence_missing"]
    )
    expected_checks = {
        item["question_id"]: item["missing_checks"]
        for item in coverage_diagnostics
        if item["missing_checks"]
    }
    expected_objects = {
        item["question_id"]: item["missing_objects"]
        for item in coverage_diagnostics
        if item["missing_objects"]
    }
    expected_dimensions = {
        item["question_id"]: item["missing_dimensions"]
        for item in coverage_diagnostics
        if item["missing_dimensions"]
    }
    declared_source_kinds = validate_stop_item_map(
        stop.get("missing_required_source_kinds"),
        field="missing_required_source_kinds",
        question_ids=question_ids,
        errors=errors,
        allowed=SOURCE_KINDS,
    )
    declared_checks = validate_stop_item_map(
        stop.get("unchecked_required_checks"),
        field="unchecked_required_checks",
        question_ids=question_ids,
        errors=errors,
        allowed=COVERAGE_CHECKS,
    )
    declared_objects = validate_stop_item_map(
        stop.get("unchecked_objects"),
        field="unchecked_objects",
        question_ids=question_ids,
        errors=errors,
    )
    declared_dimensions = validate_stop_item_map(
        stop.get("unchecked_dimensions"),
        field="unchecked_dimensions",
        question_ids=question_ids,
        errors=errors,
    )
    declared_independent = validate_string_list(
        stop.get("missing_independent_evidence"),
        error_key="stop_missing_independent_evidence",
        errors=errors,
    )
    for question_id in declared_independent:
        if question_id not in question_ids:
            errors.append(
                f"stop_missing_independent_evidence_unknown_question:{question_id}"
            )
    if declared_source_kinds != expected_source_kinds:
        errors.append("stop_missing_source_kinds_mismatch")
    if sorted(declared_independent) != expected_independent:
        errors.append("stop_missing_independent_evidence_mismatch")
    if declared_checks != expected_checks:
        errors.append("stop_unchecked_required_checks_mismatch")
    if declared_objects != expected_objects:
        errors.append("stop_unchecked_objects_mismatch")
    if declared_dimensions != expected_dimensions:
        errors.append("stop_unchecked_dimensions_mismatch")

    conflicts = stop.get("unresolved_high_priority_conflicts")
    if not isinstance(conflicts, list):
        errors.append("stop_unresolved_conflicts_invalid")
        conflicts = []
    for index, conflict in enumerate(conflicts):
        if not isinstance(conflict, dict):
            errors.append(f"stop_conflict_not_object:{index}")
            continue
        question_id = conflict.get("question_id")
        if not isinstance(question_id, str) or question_id not in question_ids:
            errors.append(f"stop_conflict_unknown_question:{question_id}")
        for field in ("conflict", "current_evidence", "next_step"):
            if not str(conflict.get(field, "")).strip():
                errors.append(
                    f"stop_conflict_field_missing:{question_id}:{field}"
                )

    coverage_complete = not any(
        (
            expected_source_kinds,
            expected_independent,
            expected_checks,
            expected_objects,
            expected_dimensions,
            conflicts,
        )
    )
    if stop.get("coverage_complete") is not coverage_complete:
        errors.append("stop_coverage_complete_mismatch")

    premature_checks = stop.get("premature_stop_checks")
    if not isinstance(premature_checks, dict):
        errors.append("premature_stop_checks_invalid")
        premature_checks = {}
    if set(premature_checks) != PREMATURE_STOP_KEYS:
        errors.append("premature_stop_checks_keys_invalid")
    for key in PREMATURE_STOP_KEYS:
        if not isinstance(premature_checks.get(key), bool):
            errors.append(f"premature_stop_check_invalid:{key}")

    remaining = stop.get("remaining_high_priority_gaps")
    if not isinstance(remaining, list):
        errors.append("remaining_high_priority_gaps_invalid")
        remaining = []
    if research_status == "complete":
        if remaining:
            errors.append("complete_high_priority_gaps_not_closed")
        if not str(stop.get("adequacy_rationale", "")).strip():
            errors.append("stop_adequacy_rationale_missing")
        if not str(
            stop.get("why_more_search_unlikely_to_change_conclusions", "")
        ).strip():
            errors.append("stop_stability_reason_missing")
        if not coverage_complete:
            errors.append("complete_coverage_not_closed")
        for key in PREMATURE_STOP_KEYS:
            if premature_checks.get(key) is True:
                errors.append(f"complete_premature_stop:{key}")
    elif research_status == "blocked":
        if not str(stop.get("blocking_conditions", "")).strip():
            errors.append("blocked_conditions_missing")
        if not str(stop.get("unblock_requirements", "")).strip():
            errors.append("blocked_unblock_requirements_missing")
        for gap in remaining:
            validate_gap(gap, question_ids, "blocked", errors)


def candidate_hashes(bundle: Path, errors: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for filename in CANDIDATE_FILES:
        path = bundle / filename
        if path.is_file():
            try:
                hashes[filename] = sha256_file(path)
            except OSError as exc:
                errors.append(f"candidate_hash_failed:{filename}:{exc}")
    return hashes


def validate_independent_review(
    bundle: Path,
    question_ids: set[str],
    claim_ids: set[str],
    current_hashes: dict[str, str],
    errors: list[str],
) -> str:
    review_path = bundle / "independent_review.json"
    if not review_path.is_file():
        return "not_reviewed"
    review = read_json(review_path, errors)
    verdict = review.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        errors.append("review_verdict_invalid")
        return "invalid"
    if review.get("independence_basis") not in REVIEW_INDEPENDENCE_BASES:
        errors.append("review_independence_basis_invalid")
    if not valid_iso_date_or_datetime(review.get("reviewed_at")):
        errors.append("reviewed_at_invalid")
    if review.get("candidate_files_modified") is not False:
        errors.append("review_candidate_files_modified_not_false")

    declared_hashes = review.get("candidate_file_sha256")
    if not isinstance(declared_hashes, dict):
        errors.append("review_candidate_hashes_missing")
    else:
        for filename, actual_hash in current_hashes.items():
            if declared_hashes.get(filename) != actual_hash:
                errors.append(f"review_candidate_hash_mismatch:{filename}")

    counts = review.get("counts")
    valid_counts = isinstance(counts, dict)
    if not valid_counts:
        errors.append("review_counts_missing")
        counts = {}
    for severity in sorted(FINDING_SEVERITIES):
        value = counts.get(severity)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"review_count_invalid:{severity}")

    findings = review.get("findings")
    if not isinstance(findings, list):
        errors.append("review_findings_invalid")
        findings = []
    calculated_counts = {severity: 0 for severity in FINDING_SEVERITIES}
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"review_finding_not_object:{index}")
            continue
        severity = finding.get("severity")
        if severity not in FINDING_SEVERITIES:
            errors.append(f"review_finding_severity_invalid:{index}")
            continue
        calculated_counts[severity] += 1
        if not str(finding.get("description", "")).strip():
            errors.append(f"review_finding_description_missing:{index}")
    if valid_counts:
        for severity in FINDING_SEVERITIES:
            if counts.get(severity) != calculated_counts[severity]:
                errors.append(f"review_count_mismatch:{severity}")

    sampled_fact_checks = review.get("sampled_fact_checks")
    if not isinstance(sampled_fact_checks, list):
        errors.append("review_sampled_fact_checks_invalid")
        sampled_fact_checks = []
    elif not sampled_fact_checks and not str(
        review.get("no_sampleable_facts_reason", "")
    ).strip():
        errors.append("review_sampled_fact_checks_or_reason_missing")
    for index, fact_check in enumerate(sampled_fact_checks):
        if not isinstance(fact_check, dict):
            errors.append(f"review_fact_check_not_object:{index}")
            continue
        if not str(fact_check.get("fact", "")).strip():
            errors.append(f"review_fact_check_fact_missing:{index}")
        if fact_check.get("status") not in REVIEW_CLAIM_STATUSES:
            errors.append(f"review_fact_check_status_invalid:{index}")
        if not str(fact_check.get("notes", "")).strip():
            errors.append(f"review_fact_check_notes_missing:{index}")
    depth_assessment = review.get("depth_assessment")
    if depth_assessment not in REVIEW_DEPTH_ASSESSMENTS:
        errors.append("review_depth_assessment_invalid")
    if not isinstance(review.get("coverage_requirements_adequate"), bool):
        errors.append("review_coverage_requirements_adequate_invalid")
    if not isinstance(review.get("premature_stop"), bool):
        errors.append("review_premature_stop_invalid")
    if not isinstance(review.get("saturation_check_credible"), bool):
        errors.append("review_saturation_check_credible_invalid")
    missing_source_roles = validate_string_list(
        review.get("missing_source_roles"),
        error_key="review_missing_source_roles",
        errors=errors,
    )
    omitted_objects = validate_string_list(
        review.get("omitted_objects"),
        error_key="review_omitted_objects",
        errors=errors,
    )
    omitted_dimensions = validate_string_list(
        review.get("omitted_dimensions"),
        error_key="review_omitted_dimensions",
        errors=errors,
    )

    coverage = review.get("question_coverage")
    covered_questions: set[str] = set()
    if not isinstance(coverage, list):
        errors.append("review_question_coverage_missing")
        coverage = []
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            errors.append(f"review_question_coverage_not_object:{index}")
            continue
        question_id = item.get("question_id")
        if not isinstance(question_id, str) or question_id not in question_ids:
            errors.append(f"review_unknown_question:{question_id}")
        elif question_id in covered_questions:
            errors.append(f"review_duplicate_question:{question_id}")
        else:
            covered_questions.add(question_id)
        if item.get("status") not in REVIEW_QUESTION_STATUSES:
            errors.append(f"review_question_status_invalid:{question_id}")
        if not str(item.get("notes", "")).strip():
            errors.append(f"review_question_notes_missing:{question_id}")
    for question_id in sorted(question_ids - covered_questions):
        errors.append(f"review_question_not_covered:{question_id}")

    checks = review.get("critical_claim_checks")
    checked_claims: set[str] = set()
    if not isinstance(checks, list):
        errors.append("review_critical_claim_checks_missing")
        checks = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            errors.append(f"review_claim_check_not_object:{index}")
            continue
        claim_id = item.get("claim_id")
        if not isinstance(claim_id, str) or claim_id not in claim_ids:
            errors.append(f"review_unknown_claim:{claim_id}")
        elif claim_id in checked_claims:
            errors.append(f"review_duplicate_claim:{claim_id}")
        else:
            checked_claims.add(claim_id)
        if item.get("status") not in REVIEW_CLAIM_STATUSES:
            errors.append(f"review_claim_status_invalid:{claim_id}")
        if not str(item.get("notes", "")).strip():
            errors.append(f"review_claim_notes_missing:{claim_id}")
    for claim_id in sorted(claim_ids - checked_claims):
        errors.append(f"review_claim_not_checked:{claim_id}")

    blocker = counts.get("blocker")
    major = counts.get("major")
    should_pass = blocker == 0 and major == 0
    if verdict == "pass" and not should_pass:
        errors.append("review_pass_has_blocker_or_major")
    if verdict == "fail" and should_pass:
        errors.append("review_fail_without_blocker_or_major")
    if verdict == "pass":
        if any(
            not isinstance(item, dict)
            or item.get("status") != "complete"
            for item in coverage
        ):
            errors.append("review_pass_question_not_complete")
        if any(
            not isinstance(item, dict)
            or item.get("status") != "verified"
            for item in checks
        ):
            errors.append("review_pass_claim_not_verified")
        if any(
            not isinstance(item, dict)
            or item.get("status") != "verified"
            for item in sampled_fact_checks
        ):
            errors.append("review_pass_sampled_fact_not_verified")
        if depth_assessment != "adequate":
            errors.append("review_pass_depth_insufficient")
        if review.get("coverage_requirements_adequate") is not True:
            errors.append("review_pass_coverage_requirements_inadequate")
        if review.get("premature_stop") is not False:
            errors.append("review_pass_premature_stop")
        if review.get("saturation_check_credible") is not True:
            errors.append("review_pass_saturation_not_credible")
        if missing_source_roles:
            errors.append("review_pass_missing_source_roles")
        if omitted_objects:
            errors.append("review_pass_omitted_objects")
        if omitted_dimensions:
            errors.append("review_pass_omitted_dimensions")
    return verdict


def validate_quantitative_span(
    span: str,
    *,
    label: str,
    snapshot_texts: dict[str, str],
    source_access_statuses: dict[str, str],
    recorded_days: set[str],
    errors: list[str],
) -> None:
    tokens = claim_tokens(span, recorded_days)
    if not tokens:
        return
    if NEGATION_PATTERN.search(span):
        return
    if has_marker(span, UNKNOWN_MARKERS + ASSUMPTION_MARKERS):
        return
    cited = [
        source_id
        for source_id in BRACKET_REFERENCE_PATTERN.findall(span)
        if source_id in source_access_statuses
    ]
    if not cited:
        errors.append(f"quantitative_uncited:{label}:{tokens[0]}")
        return
    opened = [
        source_id
        for source_id in cited
        if source_access_statuses.get(source_id) in KEY_CLAIM_SOURCE_STATUSES
    ]
    if not opened:
        errors.append(f"quantitative_source_not_opened:{label}:{tokens[0]}")
        return
    for token in tokens:
        if any(
            token_in_text(snapshot_texts.get(source_id, ""), token)
            for source_id in opened
        ):
            continue
        errors.append(f"quantitative_not_in_opened_page:{label}:{token}")


def validate_quantitative_evidence(
    report: str,
    record: dict[str, Any],
    questions: list[dict[str, Any]],
    snapshot_texts: dict[str, str],
    source_access_statuses: dict[str, str],
    errors: list[str],
) -> None:
    recorded_days = recorded_calendar_days(record)
    sections = record.get("report_sections")
    sources_heading = ""
    question_labels: dict[str, str] = {}
    if isinstance(sections, dict):
        raw_sources = sections.get("sources")
        if isinstance(raw_sources, str):
            sources_heading = raw_sources.strip()
    for question in questions:
        heading = str(question.get("answer_section", "")).strip()
        question_id = str(question.get("question_id", "")).strip() or "?"
        if heading:
            question_labels[heading] = question_id
    for heading, body in heading_sections(report):
        if heading == sources_heading:
            continue
        label_prefix = question_labels.get(heading, heading)
        for index, sentence in enumerate(split_sentences(body)):
            validate_quantitative_span(
                sentence,
                label=f"{label_prefix}:{index}",
                snapshot_texts=snapshot_texts,
                source_access_statuses=source_access_statuses,
                recorded_days=recorded_days,
                errors=errors,
            )
    claims = record.get("key_claims")
    if not isinstance(claims, list):
        return
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id", "")).strip() or "?"
        claim_text = str(claim.get("claim", "")).strip()
        tokens = claim_tokens(claim_text, recorded_days)
        if claim.get("claim_type") != "quantitative" and not tokens:
            continue
        if NEGATION_PATTERN.search(claim_text) or has_marker(
            claim_text,
            UNKNOWN_MARKERS + ASSUMPTION_MARKERS,
        ):
            continue
        quote = str(claim.get("evidence_quote", "")).strip()
        if not quote:
            errors.append(f"quantitative_evidence_quote_missing:{claim_id}")
            continue
        source_ids = claim.get("source_ids")
        opened = [
            source_id
            for source_id in source_ids
            if isinstance(source_id, str)
            and source_access_statuses.get(source_id) in KEY_CLAIM_SOURCE_STATUSES
        ] if isinstance(source_ids, list) else []
        if not any(
            compact_contains(snapshot_texts.get(source_id, ""), quote)
            for source_id in opened
        ):
            errors.append(f"quantitative_evidence_quote_not_in_snapshot:{claim_id}")
        for token in tokens:
            if not token_in_text(quote, token):
                errors.append(f"quantitative_token_not_in_quote:{claim_id}:{token}")


def validate_comparison_tables(
    report: str,
    record: dict[str, Any],
    source_access_statuses: dict[str, str],
    snapshot_texts: dict[str, str],
    errors: list[str],
) -> None:
    recorded_days = recorded_calendar_days(record)
    for heading, body in heading_sections(report):
        for table_index, table in enumerate(markdown_table_rows(body)):
            for row_index, row in enumerate(table):
                for cell_index, cell in enumerate(row):
                    tokens = claim_tokens(cell, recorded_days)
                    if not tokens:
                        continue
                    label = f"{heading}:{table_index}:{row_index}:{cell_index}"
                    if cell_is_unknown(cell):
                        errors.append(f"comparison_unknown_cell_has_number:{label}")
                        continue
                    if has_marker(cell, ASSUMPTION_MARKERS):
                        continue
                    validate_quantitative_span(
                        cell,
                        label=label,
                        snapshot_texts=snapshot_texts,
                        source_access_statuses=source_access_statuses,
                        recorded_days=recorded_days,
                        errors=errors,
                    )


def unresolved_heading(report: str, record: dict[str, Any]) -> str:
    sections = record.get("report_sections")
    if isinstance(sections, dict):
        named = sections.get("unresolved")
        if isinstance(named, str) and exact_heading_exists(report, named.strip()):
            return named.strip()
    return find_heading(report, UNRESOLVED_ALIASES)


def validate_reader_gaps(
    report: str,
    record: dict[str, Any],
    questions: list[dict[str, Any]],
    research_status: str,
    errors: list[str],
) -> None:
    if research_status != "partial":
        return
    heading = unresolved_heading(report, record)
    if not heading:
        errors.append("unresolved_section_missing")
        return
    sections = record.get("report_sections")
    summary = (
        sections.get("executive_summary")
        if isinstance(sections, dict)
        else None
    )
    if isinstance(summary, str) and exact_heading_exists(report, summary):
        if report.find(heading) > report.find(summary):
            errors.append("unresolved_section_not_before_summary")
    section = section_text(report, heading)
    for question in questions:
        if question.get("status") == "answered":
            continue
        question_id = str(question.get("question_id", "")).strip() or "?"
        question_text = str(question.get("question", "")).strip()
        if question_text and not loose_contains(section, question_text):
            errors.append(f"unresolved_question_missing:{question_id}")
            continue
        if question_text and not follow_up_present(section, question_text):
            errors.append(f"unresolved_next_step_missing:{question_id}")


def validate_research_plan(
    plan: str,
    questions: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if substantive_chars(plan) < 20:
        errors.append("research_plan_too_short")
    found: dict[str, str] = {}
    for key, aliases in PLAN_HEADING_GROUPS:
        if key == "questions":
            heading = find_question_list_heading(plan, aliases, questions)
        else:
            heading = find_heading(plan, aliases)
        if not heading:
            errors.append(f"research_plan_section_missing:{key}")
            continue
        found[key] = heading
    question_section = section_text(plan, found.get("questions", ""))
    for question in questions:
        question_text = str(question.get("question", "")).strip()
        question_id = str(question.get("question_id", "")).strip() or "?"
        if question_text and not loose_contains(question_section, question_text):
            errors.append(f"research_plan_question_missing:{question_id}")


def validate_research_log(
    log: str,
    errors: list[str],
) -> None:
    if substantive_chars(log) < 8:
        errors.append("research_log_too_short")


def validate_continuation(
    report: str,
    record: dict[str, Any],
    questions: list[dict[str, Any]],
    errors: list[str],
) -> None:
    continuation = record.get("continuation")
    if continuation is None:
        return
    if not isinstance(continuation, dict):
        errors.append("continuation_not_object")
        return
    if continuation.get("mode") != "gap_fill":
        errors.append("continuation_mode_invalid:allowed=gap_fill")
        return
    heading = find_heading(report, CONTINUATION_ALIASES)
    if not heading:
        errors.append("continuation_section_missing")
        return
    question_by_id = {
        str(question.get("question_id", "")).strip(): question
        for question in questions
    }
    section = section_text(report, heading)
    frozen = continuation.get("frozen_question_ids")
    open_ids = continuation.get("open_question_ids")
    if not isinstance(frozen, list) or not isinstance(open_ids, list):
        errors.append("continuation_question_lists_missing")
        return
    if not open_ids:
        errors.append("continuation_open_questions_missing")
    for question_id in frozen:
        question = question_by_id.get(question_id)
        if question is None:
            errors.append(f"continuation_unknown_frozen_question:{question_id}")
        elif question.get("status") != "answered":
            errors.append(f"continuation_frozen_question_not_closed:{question_id}")
    for question_id in open_ids:
        question = question_by_id.get(question_id)
        if question is None:
            errors.append(f"continuation_unknown_open_question:{question_id}")
            continue
        if question.get("status") == "answered":
            errors.append(f"continuation_open_question_already_closed:{question_id}")
        question_text = str(question.get("question", "")).strip()
        if question_text and not loose_contains(section, question_text):
            errors.append(f"continuation_open_question_not_listed:{question_id}")


def validate_decision_assumptions(
    request: str,
    report: str,
    record: dict[str, Any],
    errors: list[str],
) -> None:
    if record.get("decision_task") is not True:
        return
    assumptions = record.get("decision_assumptions")
    if not isinstance(assumptions, list) or not assumptions:
        errors.append("decision_assumptions_missing")
        return
    if len(assumptions) > 3:
        errors.append("decision_assumptions_over_limit")
    if not find_heading(request, DECISION_ALIASES) and not find_heading(
        report, DECISION_ALIASES
    ):
        errors.append("decision_assumptions_section_missing")
    for index, item in enumerate(assumptions):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"decision_assumption_invalid:{index}")
            continue
        if not loose_contains(request, item) and not loose_contains(report, item):
            errors.append(f"decision_assumption_not_written:{index}")


def warn_unmarked_decision(
    request: str,
    record: dict[str, Any],
    warnings: list[str],
) -> None:
    if record.get("decision_task") is True:
        return
    folded = request.casefold()
    if any(cue.casefold() in folded for cue in DECISION_CUES):
        warnings.append("decision_assumptions_not_recorded")


def _round_queries(
    round_item: dict[str, Any],
    round_id: str,
    errors: list[str],
) -> list[tuple[str, str]]:
    raw = round_item.get("queries")
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"round_queries_invalid:{round_id}")
        return []
    result: list[tuple[str, str]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"round_query_not_object:{round_id}:{index}")
            continue
        query = str(entry.get("query", "")).strip()
        facet = str(entry.get("facet", "")).strip()
        if not query:
            errors.append(f"round_query_text_missing:{round_id}:{index}")
            continue
        if facet not in QUERY_FACETS:
            errors.append(
                f"round_query_facet_invalid:{round_id}:{index}:{facet or 'missing'}:"
                f"allowed={join_allowed(QUERY_FACETS)}"
            )
            continue
        result.append((query, facet))
    return result


def validate_depth_and_landscape(
    report: str,
    request: str,
    record: dict[str, Any],
    research_status: str,
    questions: list[dict[str, Any]],
    question_ids: set[str],
    sources: list[Any],
    rounds: list[dict[str, Any]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """检查开放全景的广度/深度底线、检索多样性、饱和新信息率与灌水迹象。"""
    task_type = record.get("task_type")
    if task_type is not None and task_type not in TASK_TYPES:
        errors.append(
            f"task_type_invalid:{task_type}:allowed={join_allowed(TASK_TYPES)}"
        )
        task_type = None
    if task_type is None:
        folded = request.casefold()
        if any(cue.casefold() in folded for cue in LANDSCAPE_CUES):
            warnings.append("task_type_not_recorded:looks_like_open_landscape")
    enforce = task_type == "open_landscape" and research_status == "complete"

    opened: dict[str, dict[str, Any]] = {}
    for source in sources:
        if (
            isinstance(source, dict)
            and source.get("access_status") in KEY_CLAIM_SOURCE_STATUSES
        ):
            source_id = str(source.get("source_id", "")).strip()
            if source_id:
                opened[source_id] = source
    all_source_ids = {
        str(source.get("source_id", "")).strip()
        for source in sources
        if isinstance(source, dict)
    } - {""}

    # 灌水检查：只在书目里出现、正文没有用到的来源不算深度。
    report_sections = record.get("report_sections")
    sources_heading = (
        str(report_sections.get("sources", "")).strip()
        if isinstance(report_sections, dict)
        else ""
    )
    body = report
    if sources_heading and exact_heading_exists(report, sources_heading):
        body = report.replace(section_text(report, sources_heading), "")
    body_cited = set(BRACKET_REFERENCE_PATTERN.findall(body)) & all_source_ids
    not_used = sorted(all_source_ids - body_cited)
    if not_used:
        warnings.append(
            "sources_not_used_in_report_body:" + ",".join(not_used)
        )
    publisher_counts: dict[str, int] = {}
    for source_id in body_cited:
        for source in sources:
            if (
                isinstance(source, dict)
                and str(source.get("source_id", "")).strip() == source_id
            ):
                publisher = str(source.get("publisher", "")).strip().casefold()
                if publisher:
                    publisher_counts[publisher] = (
                        publisher_counts.get(publisher, 0) + 1
                    )
    if body_cited and len(body_cited) >= 6:
        top_publisher, top_count = max(
            publisher_counts.items(), key=lambda item: item[1], default=("", 0)
        )
        if top_count * 10 > len(body_cited) * 4:
            warnings.append(f"source_publisher_concentration:{top_publisher}")

    # 每个问题实际在回答章节里使用的已打开来源。
    general_headings = (
        {
            heading.strip()
            for heading in report_sections.values()
            if isinstance(heading, str) and heading.strip()
        }
        if isinstance(report_sections, dict)
        else set()
    )
    per_question: dict[str, dict[str, Any]] = {}
    for question in questions:
        question_id = str(question.get("question_id", "")).strip()
        answer_section = str(question.get("answer_section", "")).strip()
        cited = (
            set(BRACKET_REFERENCE_PATTERN.findall(section_text(report, answer_section)))
            if valid_answer_section(report, answer_section, general_headings)
            else set()
        )
        used = sorted(
            source_id
            for source_id in cited
            if source_id in opened
            and question_id in string_items(opened[source_id].get("question_ids"))
        )
        non_first_party = sorted(
            source_id
            for source_id in used
            if opened[source_id].get("stakeholder_relation")
            in {"independent", "interested_third_party"}
        )
        per_question[question_id] = {
            "opened_sources_used": len(used),
            "non_first_party_sources_used": len(non_first_party),
        }
        if enforce and question.get("status") == "answered":
            if len(used) < LANDSCAPE_MIN_QUESTION_SOURCES or not non_first_party:
                errors.append(f"landscape_question_depth_floor:{question_id}")

    # 检索台账：每轮的查询和面向。
    facets_used: set[str] = set()
    query_total = 0
    novelty: list[dict[str, Any]] = []
    for index, round_item in enumerate(rounds):
        round_id = str(round_item.get("round_id", index))
        queries = _round_queries(round_item, round_id, errors)
        query_total += len(queries)
        facets_used.update(facet for _, facet in queries)
        new_ids = round_item.get("new_source_ids")
        new_count = round_item.get("new_material_findings_count")
        if new_ids is not None and not isinstance(new_ids, list):
            errors.append(f"round_new_source_ids_invalid:{round_id}")
            new_ids = []
        for source_id in new_ids or []:
            if source_id not in all_source_ids:
                errors.append(
                    f"round_new_source_unknown:{round_id}:{source_id}"
                )
        if new_count is not None and (
            not isinstance(new_count, int) or isinstance(new_count, bool)
            or new_count < 0
        ):
            errors.append(f"round_new_material_findings_count_invalid:{round_id}")
            new_count = None
        novelty.append(
            {
                "round_id": round_id,
                "round_type": round_item.get("round_type"),
                "queries": len(queries),
                "facets": sorted({facet for _, facet in queries}),
                "new_opened_sources": len(
                    [item for item in (new_ids or []) if item in opened]
                ),
                "new_material_findings_count": new_count,
            }
        )

    landscape_metrics: dict[str, Any] = {}
    if enforce:
        if query_total == 0:
            errors.append("landscape_query_ledger_missing")
        elif len(facets_used) < LANDSCAPE_MIN_QUERY_FACETS:
            errors.append(
                "landscape_query_facets_too_narrow:"
                + ",".join(sorted(facets_used))
            )
        if "citation_snowball" not in facets_used:
            errors.append("landscape_citation_snowball_missing")
        saturation = [
            item for item in novelty
            if item["round_type"] == "adversarial_saturation_check"
        ]
        if saturation:
            last = saturation[-1]
            if last["new_opened_sources"] < LANDSCAPE_MIN_SATURATION_NEW_SOURCES:
                errors.append("landscape_saturation_without_new_reading")
            if len(last["facets"]) < LANDSCAPE_MIN_SATURATION_FACETS:
                errors.append("landscape_saturation_queries_not_diversified")
            if last["new_material_findings_count"] is None:
                errors.append("landscape_saturation_novelty_missing")
            elif last["new_material_findings_count"] > 0:
                errors.append("landscape_saturation_found_new_material")

        landscape = record.get("landscape")
        if not isinstance(landscape, dict):
            errors.append("landscape_missing")
            landscape = {}
        segments_raw = landscape.get("segments")
        entities_raw = landscape.get("entities")
        segment_names: set[str] = set()
        if not isinstance(segments_raw, list) or not segments_raw:
            errors.append("landscape_segments_missing")
            segments_raw = []
        for index, segment in enumerate(segments_raw):
            if not isinstance(segment, dict) or not str(
                segment.get("segment", "")
            ).strip():
                errors.append(f"landscape_segment_invalid:{index}")
                continue
            name = str(segment["segment"]).strip()
            segment_names.add(name)
            mapped = string_items(segment.get("question_ids"))
            if not mapped or any(item not in question_ids for item in mapped):
                errors.append(f"landscape_segment_question_invalid:{name}")
        if not isinstance(entities_raw, list) or not entities_raw:
            errors.append("landscape_entities_missing")
            entities_raw = []
        segments_with_entities: set[str] = set()
        for index, entity in enumerate(entities_raw):
            if not isinstance(entity, dict) or not str(
                entity.get("name", "")
            ).strip():
                errors.append(f"landscape_entity_invalid:{index}")
                continue
            name = str(entity["name"]).strip()
            segment = str(entity.get("segment", "")).strip()
            if segment not in segment_names:
                errors.append(f"landscape_entity_segment_unknown:{name}")
            else:
                segments_with_entities.add(segment)
            if not any(
                item in opened for item in string_items(entity.get("source_ids"))
            ):
                errors.append(f"landscape_entity_unsourced:{name}")
            if not loose_contains(body, name):
                errors.append(f"landscape_entity_not_in_report:{name}")
        for name in sorted(segment_names - segments_with_entities):
            errors.append(f"landscape_segment_without_entities:{name}")
        table_heading = str(landscape.get("coverage_table_section", "")).strip()
        if not table_heading or not exact_heading_exists(report, table_heading):
            errors.append("landscape_coverage_table_missing")
        else:
            table_text = section_text(report, table_heading)
            if not markdown_table_rows(table_text):
                errors.append("landscape_coverage_table_missing")
            else:
                for name in sorted(segment_names):
                    if not loose_contains(table_text, name):
                        errors.append(
                            f"landscape_segment_not_in_coverage_table:{name}"
                        )
        landscape_metrics = {
            "segment_count": len(segment_names),
            "entity_count": len(
                [item for item in entities_raw if isinstance(item, dict)]
            ),
        }
    return {
        "task_type": task_type,
        "query_count": query_total,
        "query_facets": sorted(facets_used),
        "body_cited_source_count": len(body_cited),
        "sources_not_used_in_body": len(not_used),
        "per_question": per_question,
        "round_novelty": novelty,
        **landscape_metrics,
    }


def validate_bundle(bundle: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    if not bundle.is_dir():
        return {
            "status": "error",
            "research_status": "unknown",
            "review_status": "not_reviewed",
            "errors": ["bundle_directory_missing"],
            "warnings": [],
            "checks": {},
        }
    for filename in REQUIRED_FILES:
        if not (bundle / filename).is_file():
            errors.append(f"missing_required_file:{filename}")
    if errors:
        return {
            "status": "error",
            "research_status": "unknown",
            "review_status": "not_reviewed",
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
        }

    request = read_text(bundle / "request_snapshot.md", errors)
    plan = read_text(bundle / "research_plan.md", errors)
    log = read_text(bundle / "research_log.md", errors)
    report = read_text(bundle / "final_report.md", errors)
    record = read_json(bundle / "research_record.json", errors)
    normalizations = normalize_record(record)

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version_invalid:expected_{SCHEMA_VERSION}"
        )
    research_status = str(record.get("research_status", "")).strip()
    if research_status not in RESEARCH_STATUSES:
        errors.append("research_status_invalid")
        research_status = "unknown"
    if not valid_iso_date_or_datetime(record.get("research_as_of")):
        errors.append("research_as_of_invalid")

    if substantive_chars(request) < 10:
        errors.append("request_snapshot_too_short")
    if substantive_chars(report) < REPORT_MIN_SUBSTANTIVE_CHARS:
        errors.append("report_too_short")
    if EXPLICIT_PLACEHOLDER_PATTERN.search(report):
        errors.append("report_contains_explicit_placeholder")
    if not re.search(r"(?m)^#{1,6}\s+.+", report):
        errors.append("report_has_no_sections")
    validate_report_sections(report, record, errors)

    questions, question_ids = validate_questions(
        report,
        record,
        research_status,
        errors,
        warnings,
    )

    source_ids: set[str] = set()
    source_access_statuses: dict[str, str] = {}
    snapshot_texts: dict[str, str] = {}
    source_stakeholder_relations: dict[str, str] = {}
    source_question_ids: dict[str, set[str]] = {}
    sources_value = record.get("sources")
    if not isinstance(sources_value, list):
        errors.append("sources_missing")
        sources_value = []
    if research_status == "complete" and not sources_value:
        errors.append("complete_sources_missing")
    canonical_source_urls: dict[str, str] = {}
    for source in sources_value:
        validate_source(
            bundle,
            source,
            question_ids,
            source_ids,
            source_access_statuses,
            snapshot_texts,
            errors,
        )
        if isinstance(source, dict):
            source_id = str(source.get("source_id", "")).strip()
            if source_id:
                source_stakeholder_relations[source_id] = str(
                    source.get("stakeholder_relation", "")
                ).strip()
                raw_question_ids = source.get("question_ids")
                source_question_ids[source_id] = set(
                    item
                    for item in raw_question_ids
                    if isinstance(item, str)
                ) if isinstance(raw_question_ids, list) else set()
                normalized_url = canonical_url(source.get("url"))
                if normalized_url:
                    previous_source_id = canonical_source_urls.get(
                        normalized_url
                    )
                    if previous_source_id:
                        errors.append(
                            f"duplicate_source_url:"
                            f"{previous_source_id}:{source_id}"
                        )
                    else:
                        canonical_source_urls[normalized_url] = source_id

    bracket_references = set(BRACKET_REFERENCE_PATTERN.findall(report))
    known_non_source_ids = question_ids.copy()
    for claim in record.get("key_claims", []):
        if isinstance(claim, dict):
            known_non_source_ids.add(str(claim.get("claim_id", "")).strip())
    unknown_citations = bracket_references - source_ids - known_non_source_ids
    for source_id in sorted(unknown_citations):
        errors.append(f"unknown_report_citation:{source_id}")
    cited_source_ids = bracket_references & source_ids
    if research_status == "complete" and not cited_source_ids:
        errors.append("complete_report_has_no_source_citations")

    _, claim_ids = validate_key_claims(
        report,
        record,
        research_status,
        questions,
        question_ids,
        source_ids,
        source_access_statuses,
        source_stakeholder_relations,
        source_question_ids,
        errors,
    )
    if question_ids & source_ids:
        errors.append(
            "id_namespace_collision:question_source:"
            + ",".join(sorted(question_ids & source_ids))
        )
    if question_ids & claim_ids:
        errors.append(
            "id_namespace_collision:question_claim:"
            + ",".join(sorted(question_ids & claim_ids))
        )
    if source_ids & claim_ids:
        errors.append(
            "id_namespace_collision:source_claim:"
            + ",".join(sorted(source_ids & claim_ids))
        )
    rounds = validate_rounds(
        record,
        research_status,
        question_ids,
        errors,
    )
    coverage_diagnostics = build_coverage_diagnostics(
        report,
        record,
        questions,
        sources_value,
        rounds,
        research_status,
        errors,
    )
    validate_stop_decision(
        record,
        research_status,
        question_ids,
        coverage_diagnostics,
        errors,
    )
    validate_research_plan(plan, questions, errors)
    validate_research_log(log, errors)
    validate_reader_gaps(report, record, questions, research_status, errors)
    validate_quantitative_evidence(
        report,
        record,
        questions,
        snapshot_texts,
        source_access_statuses,
        errors,
    )
    validate_comparison_tables(
        report,
        record,
        source_access_statuses,
        snapshot_texts,
        errors,
    )
    validate_continuation(report, record, questions, errors)
    validate_decision_assumptions(request, report, record, errors)
    warn_unmarked_decision(request, record, warnings)
    depth_metrics = validate_depth_and_landscape(
        report,
        request,
        record,
        research_status,
        questions,
        question_ids,
        sources_value,
        rounds,
        errors,
        warnings,
    )

    hashes = candidate_hashes(bundle, errors)
    review_status = validate_independent_review(
        bundle,
        question_ids,
        claim_ids,
        hashes,
        errors,
    )
    if research_status != "complete" and review_status == "pass":
        errors.append("incomplete_research_cannot_review_pass")
    delivery_status = {
        ("complete", "not_reviewed"): "complete_draft",
        ("complete", "pass"): "reviewed_pass",
        ("complete", "fail"): "reviewed_fail",
        ("partial", "not_reviewed"): "partial",
        ("partial", "fail"): "partial",
        ("blocked", "not_reviewed"): "blocked",
        ("blocked", "fail"): "blocked",
    }.get((research_status, review_status), "invalid")
    if errors:
        delivery_status = "invalid"

    checks.update(
        {
            "skill_version": SKILL_VERSION,
            "schema_version": record.get("schema_version"),
            "report_substantive_chars": substantive_chars(report),
            "question_count": len(questions),
            "source_count": len(source_ids),
            "cited_source_count": len(cited_source_ids),
            "key_claim_count": len(claim_ids),
            "research_round_count": len(rounds),
            "question_coverage": coverage_diagnostics,
            "depth_metrics": depth_metrics,
            "normalizations": normalizations,
            "candidate_file_sha256": hashes,
        }
    )
    return {
        "status": "ok" if not errors else "error",
        "research_status": research_status,
        "review_status": review_status,
        "delivery_status": delivery_status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "scope_note": (
            "本 validator 检查结构化状态、逐问题来源与检查覆盖、饱和停止、关键引用、"
            "开放全景的广度/深度底线与饱和新信息率、"
            "表格里的数字、已保存页面中的数字、读者稿里的未完成项、候选文件完整性与"
            "独立审阅合同。它不联网重抓网页；页面里没有保存下来的数字仍算未核到。"
            "覆盖要求是否合理及报告质量仍由独立 reviewer 裁决。"
        ),
    }


def _ensure_utf8_stdio() -> None:
    """Emit UTF-8 regardless of the console/pipe code page (e.g. cp1252 on Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()
    bundle_dir = args.bundle_dir.resolve()
    result = validate_bundle(bundle_dir)
    if bundle_dir.is_dir():
        try:
            (bundle_dir / "validation_receipt.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            result["status"] = "error"
            result["errors"].append(f"validation_receipt_write_failed:{exc}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
