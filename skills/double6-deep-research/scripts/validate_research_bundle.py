#!/usr/bin/env python3
"""验证报告优先的 double6-deep-research 最小交付底线。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "request_snapshot.md",
    "final_report.md",
    "research_record.json",
)
PLACEHOLDER_PATTERN = re.compile(
    r"(?:\b(?:TODO|TBD|PLACEHOLDER)\b|待补(?:充|齐|写)?|占位)",
    re.IGNORECASE,
)
CITATION_PATTERN = re.compile(r"\[(S[A-Z0-9_-]+)\]")
URL_PATTERN = re.compile(r"https?://[^\s<>\])}\"']+")
AUTHORIAL_SNAPSHOT_PATTERN = re.compile(
    r"(?:this snapshot was captured for|the captured section describes|"
    r"the research process uses dated|以下内容由研究者(?:整理|概括|总结)|"
    r"本快照用于本次(?:研究|比较))",
    re.IGNORECASE,
)
REPORT_MIN_SUBSTANTIVE_CHARS = 100
KEY_CLAIM_SOURCE_STATUSES = {"full_text", "substantive_sections"}


def substantive_chars(text: str) -> int:
    text = URL_PATTERN.sub("", text)
    return len(re.sub(r"[\W_]+", "", text, flags=re.UNICODE))


def report_blocks(text: str) -> list[str]:
    return [
        block.strip()
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_json:{path.name}:{exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"json_root_not_object:{path.name}")
        return {}
    return value


def validate_source(
    bundle: Path,
    source: Any,
    source_ids: set[str],
    errors: list[str],
) -> None:
    if not isinstance(source, dict):
        errors.append("source_not_object")
        return
    source_id = str(source.get("source_id", "")).strip()
    if not source_id:
        errors.append("source_id_missing")
        return
    if source_id in source_ids:
        errors.append(f"duplicate_source_id:{source_id}")
    source_ids.add(source_id)
    for field in ("title", "url", "publisher", "accessed_at", "access_status"):
        if not str(source.get(field, "")).strip():
            errors.append(f"source_field_missing:{source_id}:{field}")
    if source.get("access_status") not in {
        "full_text",
        "substantive_sections",
        "metadata_only",
        "unavailable",
    }:
        errors.append(f"source_access_status_invalid:{source_id}")
    if source.get("content_origin") not in {
        "host_opened_page",
        "downloaded_document",
        "user_provided_material",
    }:
        errors.append(f"source_origin_invalid:{source_id}")
    if source.get("content_origin") == "researcher_summary":
        errors.append(f"researcher_summary_used_as_source:{source_id}")

    snapshot_value = source.get("snapshot_path")
    if snapshot_value is None:
        return
    snapshot = bundle / str(snapshot_value)
    if not snapshot.is_file():
        errors.append(f"source_snapshot_missing:{source_id}:{snapshot_value}")
        return
    declared_sha = str(source.get("snapshot_sha256", "")).strip()
    if not declared_sha or sha256_file(snapshot) != declared_sha:
        errors.append(f"source_snapshot_sha_mismatch:{source_id}")
    try:
        snapshot_text = snapshot.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        snapshot_text = ""
    if snapshot_text and AUTHORIAL_SNAPSHOT_PATTERN.search(snapshot_text):
        errors.append(f"researcher_authored_snapshot:{source_id}")


def validate_bundle(bundle: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for filename in REQUIRED_FILES:
        if not (bundle / filename).is_file():
            errors.append(f"missing_required_file:{filename}")
    if errors:
        return {
            "status": "error",
            "errors": errors,
            "warnings": warnings,
            "checks": {},
        }

    request = (bundle / "request_snapshot.md").read_text(encoding="utf-8")
    report = (bundle / "final_report.md").read_text(encoding="utf-8")
    record = read_json(bundle / "research_record.json", errors)

    if substantive_chars(request) < 10:
        errors.append("request_snapshot_too_short")
    if substantive_chars(report) < REPORT_MIN_SUBSTANTIVE_CHARS:
        errors.append("complete_report_too_short")
    if PLACEHOLDER_PATTERN.search(report):
        errors.append("complete_report_contains_placeholder")
    if not re.search(r"(?m)^#{1,3}\s+.+", report):
        errors.append("complete_report_has_no_sections")
    if not re.search(r"(?:局限|限制|不确定|limitations?|uncertaint)", report, re.I):
        errors.append("complete_report_missing_limitations")
    if not re.search(r"(?:来源|参考|sources?|references?)", report, re.I):
        errors.append("complete_report_missing_sources_section")

    if record.get("status") != "complete":
        errors.append("research_record_not_complete")

    questions = record.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("questions_missing")
        questions = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            errors.append(f"question_not_object:{index}")
            continue
        question_id = str(question.get("question_id", index))
        answer_section = str(question.get("answer_section", "")).strip()
        if question.get("status") != "answered":
            errors.append(f"question_not_answered:{question_id}")
        if not answer_section or answer_section not in report:
            errors.append(f"question_answer_section_missing:{question_id}")

    source_ids: set[str] = set()
    source_access_statuses: dict[str, str] = {}
    sources = record.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources_missing")
        sources = []
    for source in sources:
        validate_source(bundle, source, source_ids, errors)
        if isinstance(source, dict):
            source_id = str(source.get("source_id", "")).strip()
            if source_id:
                source_access_statuses[source_id] = str(
                    source.get("access_status", "")
                ).strip()

    cited_source_ids = set(CITATION_PATTERN.findall(report))
    unknown_citations = cited_source_ids - source_ids
    for source_id in sorted(unknown_citations):
        errors.append(f"unknown_report_citation:{source_id}")
    if not cited_source_ids:
        errors.append("report_has_no_source_citations")

    key_claims = record.get("key_claims")
    if not isinstance(key_claims, list) or not key_claims:
        errors.append("key_claims_missing")
        key_claims = []
    blocks = report_blocks(report)
    for index, claim in enumerate(key_claims):
        if not isinstance(claim, dict):
            errors.append(f"key_claim_not_object:{index}")
            continue
        claim_id = str(claim.get("claim_id", index))
        claim_text = str(claim.get("claim", "")).strip()
        claim_source_ids = claim.get("source_ids")
        matching_blocks = [
            block for block in blocks if claim_text and claim_text in block
        ]
        if not matching_blocks:
            errors.append(f"key_claim_not_in_report:{claim_id}")
        if not isinstance(claim_source_ids, list) or not claim_source_ids:
            errors.append(f"key_claim_sources_missing:{claim_id}")
            continue
        for source_id in claim_source_ids:
            if source_id not in source_ids:
                errors.append(f"key_claim_unknown_source:{claim_id}:{source_id}")
                continue
            if source_access_statuses.get(source_id) not in KEY_CLAIM_SOURCE_STATUSES:
                errors.append(
                    f"key_claim_source_not_substantive:{claim_id}:{source_id}"
                )
            if not any(f"[{source_id}]" in block for block in matching_blocks):
                errors.append(
                    f"key_claim_source_not_cited_with_claim:{claim_id}:{source_id}"
                )

    rounds = record.get("research_rounds")
    if not isinstance(rounds, list) or len(rounds) < 2:
        errors.append("research_rounds_insufficient")
        rounds = []
    if rounds and not any(
        isinstance(item, dict) and item.get("round_type") == "gap_check"
        for item in rounds
    ):
        errors.append("gap_check_round_missing")

    stop = record.get("stop_decision")
    if not isinstance(stop, dict):
        errors.append("stop_decision_missing")
        stop = {}
    if stop.get("status") != "complete":
        errors.append("stop_decision_not_complete")
    remaining = stop.get("remaining_high_priority_gaps")
    if not isinstance(remaining, list) or remaining:
        errors.append("high_priority_gaps_not_closed")
    if not str(stop.get("adequacy_rationale", "")).strip():
        errors.append("stop_adequacy_rationale_missing")
    if not str(stop.get("why_more_search_unlikely_to_change_conclusions", "")).strip():
        errors.append("stop_stability_reason_missing")

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "report_substantive_chars": substantive_chars(report),
            "question_count": len(questions),
            "source_count": len(source_ids),
            "cited_source_count": len(cited_source_ids),
            "key_claim_count": len(key_claims),
            "research_round_count": len(rounds),
        },
        "scope_note": (
            "本 validator 只检查来源记录一致性、关键引用完整性、完整报告存在性与"
            "明显提前停止；它不联网验证外部事实，报告质量由独立 reviewer 裁决。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()
    bundle_dir = args.bundle_dir.resolve()
    result = validate_bundle(bundle_dir)
    (bundle_dir / "validation_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
