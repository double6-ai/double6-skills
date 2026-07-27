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


SKILL_VERSION = "2.0.0"
SCHEMA_VERSION = 2
REQUIRED_FILES = (
    "request_snapshot.md",
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
}
CONCLUSION_IMPACTS = {"changed", "strengthened", "narrowed", "none"}
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
                errors.append(f"{error_key}_invalid:{item}")
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


def validate_source(
    bundle: Path,
    source: Any,
    question_ids: set[str],
    source_ids: set[str],
    source_access_statuses: dict[str, str],
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
        errors.append(f"source_access_status_invalid:{source_id}")
    if source.get("content_origin") not in SOURCE_ORIGINS:
        errors.append(f"source_origin_invalid:{source_id}")
    if source.get("source_kind") not in SOURCE_KINDS:
        errors.append(f"source_kind_invalid:{source_id}")
    if source.get("stakeholder_relation") not in STAKEHOLDER_RELATIONS:
        errors.append(f"source_stakeholder_relation_invalid:{source_id}")

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
    if snapshot_text and AUTHORIAL_SNAPSHOT_PATTERN.search(snapshot_text):
        errors.append(f"researcher_authored_snapshot:{source_id}")


def validate_report_sections(
    report: str,
    record: dict[str, Any],
    errors: list[str],
) -> None:
    sections = record.get("report_sections")
    if not isinstance(sections, dict):
        errors.append("report_sections_missing")
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
            errors.append(f"question_id_missing:{index}")
            continue
        if question_id in question_ids:
            errors.append(f"duplicate_question_id:{question_id}")
        question_ids.add(question_id)
        questions.append(question)
        if not str(question.get("question", "")).strip():
            errors.append(f"question_text_missing:{question_id}")
        status = question.get("status")
        if status not in QUESTION_STATUSES:
            errors.append(f"question_status_invalid:{question_id}")
        if research_status == "complete" and status != "answered":
            errors.append(f"complete_question_not_answered:{question_id}")
        requirements = question.get("coverage_requirements")
        if not isinstance(requirements, dict):
            errors.append(f"question_coverage_requirements_missing:{question_id}")
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
                errors.append(f"partial_question_current_evidence_missing:{question_id}")
            if not str(question.get("next_step", "")).strip():
                errors.append(f"partial_question_next_step_missing:{question_id}")
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
            errors.append(f"key_claim_type_invalid:{claim_id}")
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
        errors.append(f"research_round_conclusion_impact_invalid:{round_id}")
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
                f"{round_id}:{question_id}"
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
            errors.append(f"research_round_type_invalid:{round_id}")
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
    open_question_ids: set[str],
    coverage_diagnostics: list[dict[str, Any]],
    errors: list[str],
) -> None:
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
    elif research_status == "partial":
        if not remaining:
            errors.append("partial_remaining_gaps_missing")
        for gap in remaining:
            validate_gap(gap, question_ids, "partial", errors)
        recorded_gap_question_ids = {
            str(gap.get("question_id", ""))
            for gap in remaining
            if isinstance(gap, dict)
        }
        for question_id in sorted(
            open_question_ids - recorded_gap_question_ids
        ):
            errors.append(
                f"partial_open_question_gap_missing:{question_id}"
            )
        recorded_gap_items: set[tuple[str, str, str]] = set()
        for gap in remaining:
            if not isinstance(gap, dict):
                continue
            question_id = str(gap.get("question_id", ""))
            gap_type = str(gap.get("gap_type", ""))
            for item in string_items(gap.get("missing_items")):
                recorded_gap_items.add((question_id, gap_type, item))
        expected_gap_items: set[tuple[str, str, str]] = set()
        for question_id, items in expected_source_kinds.items():
            expected_gap_items.update(
                (question_id, "missing_source_kind", item) for item in items
            )
        expected_gap_items.update(
            (question_id, "missing_independent_evidence", "independent")
            for question_id in expected_independent
        )
        for question_id, items in expected_checks.items():
            expected_gap_items.update(
                (question_id, "unchecked_required_check", item)
                for item in items
            )
        for question_id, items in expected_objects.items():
            expected_gap_items.update(
                (question_id, "unchecked_object", item) for item in items
            )
        for question_id, items in expected_dimensions.items():
            expected_gap_items.update(
                (question_id, "unchecked_dimension", item) for item in items
            )
        expected_gap_items.update(
            (
                str(conflict.get("question_id", "")),
                "unresolved_conflict",
                str(conflict.get("conflict", "")),
            )
            for conflict in conflicts
            if isinstance(conflict, dict)
        )
        for missing_gap in sorted(expected_gap_items - recorded_gap_items):
            errors.append(
                f"partial_coverage_gap_not_recorded:"
                f"{missing_gap[0]}:{missing_gap[1]}:{missing_gap[2]}"
            )
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
    report = read_text(bundle / "final_report.md", errors)
    record = read_json(bundle / "research_record.json", errors)

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
        {
            str(question.get("question_id", "")).strip()
            for question in questions
            if question.get("status") != "answered"
        },
        coverage_diagnostics,
        errors,
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
            "候选文件完整性与独立审阅合同；它不联网验证外部事实，覆盖要求是否合理及"
            "报告质量仍由独立 reviewer 裁决。"
        ),
    }


def main() -> int:
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
