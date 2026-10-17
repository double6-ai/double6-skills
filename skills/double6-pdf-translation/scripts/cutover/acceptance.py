from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_CASES = {"latextrans", "nature_literary_autobiography", "ai_index"}
APPROVAL_PHRASE = "approve-user-feedback-candidate-cutover"


def _blocker(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def validate_packet(packet: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    cases = {str(item.get("case_id")): item for item in packet.get("cases") or []}
    missing = sorted(EXPECTED_CASES - set(cases))
    if missing:
        blockers.append(_blocker("candidate_packet_missing_cases", cases=missing))
    for case_id, item in cases.items():
        dual = item.get("dual_pdf") or {}
        if not dual.get("exists"):
            blockers.append(_blocker("candidate_dual_pdf_missing", case_id=case_id, path=dual.get("path")))
        dirty_checks = [check for check in item.get("checks") or [] if check.get("status") != "ok"]
        if dirty_checks:
            blockers.append(_blocker("candidate_checks_not_ok", case_id=case_id, checks=dirty_checks))
        if case_id == "latextrans":
            strict = item.get("strict_evidence") or {}
            if strict.get("status") != "ok" or strict.get("validation_gate_status") != "ok":
                blockers.append(_blocker("latextrans_strict_evidence_not_ok", case_id=case_id))
    return blockers


def build_acceptance(
    packet: dict[str, Any], reviewer: str, decision: str, reviewed_at: str | None = None
) -> dict[str, Any]:
    blockers = validate_packet(packet)
    if blockers:
        raise ValueError(f"candidate packet is not acceptable: {blockers}")
    if decision != "accepted":
        raise ValueError("only an explicit accepted decision can create an acceptance record")
    return {
        "schema_version": 1,
        "status": "accepted",
        "human_review_status": "accepted",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).isoformat(),
        "accepted_cases": sorted(EXPECTED_CASES),
        "rejected_cases": [],
        "approval_phrase": APPROVAL_PHRASE,
        "candidate_dir": packet.get("candidate_dir"),
    }


def latextrans_cutover_fields(preflight: dict[str, Any]) -> dict[str, Any]:
    state = (preflight.get("verification_only_cases") or {}).get("latextrans") or {}
    return {
        "cutover_mode": "verified_no_op_existing_strict_delivery",
        "strict_evidence": {
            "status": state.get("render_manifest_status"),
            "validation_gate_status": state.get("validation_gate_status"),
            "actual_render_source": state.get("actual_render_source"),
            "render_manifest": state.get("render_manifest"),
        },
    }


def acceptance_template(packet_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "accepted",
        "human_review_status": "accepted",
        "packet": str(packet_path),
        "accepted_cases": sorted(EXPECTED_CASES),
        "rejected_cases": [],
        "approval_phrase": APPROVAL_PHRASE,
        "evidence": {
            "verification": "pending",
            "full_page_sweep": "pending",
            "targeted_region_audit": "pending",
            "independent_visual_spot_check": "pending",
        },
        "next_guarded_cutover_command": "python -m cutover.cli run --apply",
        "notes": "Complete an independent visual spot check before guarded cutover.",
    }


def validate_evidence(
    verification: dict[str, Any],
    full_sweep: dict[str, Any],
    targeted_audit: dict[str, Any],
    independent_spot_check: dict[str, Any],
    preflight: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if verification.get("status") != "ok":
        blockers.append(_blocker("verification_not_ok"))
    summary = full_sweep.get("summary") or {}
    if full_sweep.get("status") not in {"ok", "ok_with_warnings"} or summary.get("hard_failure_count", 0):
        blockers.append(_blocker("full_sweep_not_ok"))
    if full_sweep.get("status") == "ok_with_warnings" or summary.get("warning_count", 0):
        blockers.append(_blocker("full_sweep_warnings_not_fully_reviewed"))
    if targeted_audit.get("status") != "ok":
        blockers.append(_blocker("targeted_region_audit_not_ok"))
    if independent_spot_check.get("status") not in {"ok", "ok_for_targeted_scope_pending_human_acceptance"}:
        blockers.append(_blocker("independent_visual_spot_check_not_ok"))
    if preflight.get("status") == "blocked" or preflight.get("blockers"):
        blockers.append(_blocker("cutover_preflight_blocked"))
    return blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建 strict cutover 人工验收记录")
    parser.add_argument("packet", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", choices=["accepted"], required=True)
    args = parser.parse_args(argv)
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    result = build_acceptance(packet, args.reviewer, args.decision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
