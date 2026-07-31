#!/usr/bin/env python3
"""研究停止合同与独立复核验证。"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Shared validation helpers used by validate_research_bundle.py."

CANDIDATE_FILES = ("request_snapshot.md", "final_report.md", "research_record.json")
SOURCE_KINDS = {
    "official_document", "scholarly_research", "independent_evaluation",
    "industry_analysis", "user_or_adoption_evidence", "journalism", "other",
}
COVERAGE_CHECKS = {"freshness", "counterevidence", "omitted_objects", "omitted_dimensions"}
PREMATURE_STOP_KEYS = {
    "tool_result_limit_used", "preset_source_count_used", "time_limit_used", "fixed_round_count_used",
}
REVIEW_VERDICTS = {"pass", "fail"}
REVIEW_QUESTION_STATUSES = {"complete", "partial", "unanswered", "unsupported"}
REVIEW_CLAIM_STATUSES = {"verified", "failed", "uncertain"}
REVIEW_INDEPENDENCE_BASES = {"isolated_agent", "independent_human"}
REVIEW_DEPTH_ASSESSMENTS = {"adequate", "insufficient"}
FINDING_SEVERITIES = {"blocker", "major", "minor"}
ISO_DATE_OR_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))?$"
)

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
