from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance import APPROVAL_PHRASE, EXPECTED_CASES


APPLY_APPROVAL_PHRASE = "apply-user-feedback-strict-cutover"
OUTPUTS = Path("outputs")
DAILY_ROOT = Path(".")
DAILY_INDEX = Path("indexes/artifact_index.json")


def _blocker(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _read(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def acceptance_ok(acceptance: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    if acceptance.get("_missing") or not acceptance:
        blockers = [_blocker("acceptance_missing_or_invalid")]
        return False, blockers
    blockers: list[dict[str, Any]] = []
    if acceptance.get("status") != "accepted" or acceptance.get("human_review_status") != "accepted":
        blockers.append(_blocker("acceptance_not_accepted"))
    accepted = set(acceptance.get("accepted_cases") or [])
    missing = sorted(EXPECTED_CASES - accepted)
    if missing:
        blockers.append(_blocker("acceptance_missing_cases", cases=missing))
    if acceptance.get("rejected_cases"):
        blockers.append(_blocker("acceptance_contains_rejected_cases"))
    phrase = acceptance.get("approval_phrase")
    if phrase is not None and phrase != APPROVAL_PHRASE:
        blockers.append(_blocker("acceptance_approval_phrase_invalid"))
    return not blockers, blockers


def evidence_ok(
    full_sweep: dict[str, Any], targeted_audit: dict[str, Any], independent_spot_check: dict[str, Any]
) -> tuple[bool, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    summary = full_sweep.get("summary") or {}
    if full_sweep.get("status") != "ok" or summary.get("hard_failure_count", 0) or summary.get("warning_count", 0):
        blockers.append(_blocker("full_page_sweep_not_clean"))
    if targeted_audit.get("status") != "ok":
        blockers.append(_blocker("targeted_region_audit_not_ok"))
    if independent_spot_check.get("status") not in {"ok", "ok_for_targeted_scope_pending_human_acceptance"}:
        blockers.append(_blocker("independent_visual_spot_check_not_ok"))
    return not blockers, blockers


def verification_only_case_state(
    case_id: str, paths: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    render_manifest_path = Path(paths["render_manifest"])
    manifest = _read(render_manifest_path, {})
    state = {
        "case_id": case_id,
        "promotion_mode": paths.get("promotion_mode"),
        "render_manifest": str(render_manifest_path),
        "render_manifest_status": manifest.get("status"),
        "validation_gate_status": ((manifest.get("validation") or {}).get("gates") or {}).get("status"),
        "actual_render_source": manifest.get("actual_render_source"),
    }
    blockers: list[dict[str, Any]] = []
    checks = {
        "render_manifest_status": paths.get("expected_render_status"),
        "validation_gate_status": paths.get("expected_validation_gate_status"),
        "actual_render_source": paths.get("expected_actual_render_source"),
    }
    for field, expected in checks.items():
        if expected is not None and state[field] != expected:
            blockers.append(_blocker("verification_only_case_mismatch", case_id=case_id, field=field, expected=expected, actual=state[field]))
    for field in ("candidate_dual", "daily_dual"):
        path = Path(paths[field])
        if not path.is_file():
            blockers.append(_blocker("verification_only_artifact_missing", case_id=case_id, field=field, path=str(path)))
    return state, blockers


def inspect_case(case_id: str) -> dict[str, Any]:
    case_dir = OUTPUTS / case_id
    manifest_path = case_dir / "formal_targeted_candidate_manifest.json"
    review_path = case_dir / "human_visual_review.json"
    candidate = _read(manifest_path, {})
    review = _read(review_path, {})
    blockers: list[dict[str, Any]] = []
    if candidate.get("status") != "candidate_ready_needs_human_visual_review":
        blockers.append(_blocker("candidate_manifest_not_ready"))
    if review.get("status") != "accepted":
        blockers.append(_blocker("human_visual_review_pending"))
    if review.get("accepted_candidate_manifest") and Path(review["accepted_candidate_manifest"]).resolve() != manifest_path.resolve():
        blockers.append(_blocker("accepted_candidate_manifest_mismatch"))
    for field in ("mono_pdf", "dual_pdf", "visual_layout_report", "dual_visual_report", "bilingual_pdf_manifest", "repair_manifest"):
        if not Path(str(candidate.get(field) or "")).is_file():
            blockers.append(_blocker("candidate_artifact_missing", field=field, path=candidate.get(field)))
    return {
        "case_id": case_id,
        "status": "ready_to_promote" if not blockers else "blocked",
        "blockers": blockers,
        "candidate_manifest": str(manifest_path),
        "human_review": str(review_path),
    }


def _promoted_render_payload(case_id: str, promoted_at: str) -> tuple[Path, dict[str, Any]]:
    case_dir = OUTPUTS / case_id
    candidate = _read(case_dir / "formal_targeted_candidate_manifest.json", {})
    render_path = case_dir / "render_manifest.json"
    render = _read(render_path, {})
    render.update({"status": "ok", "actual_render_source": "formal_targeted_candidate", "promoted_at": promoted_at})
    outputs = render.setdefault("outputs", {})
    outputs["translated_pdf"] = candidate.get("mono_pdf")
    outputs["standard_bilingual_pdf"] = candidate.get("dual_pdf")
    gates = render.setdefault("validation", {}).setdefault("gates", {})
    gates.update({"status": "ok", "worst_gate": "ok", "blocking": []})
    render["formal_targeted_candidate_manifest"] = str(case_dir / "formal_targeted_candidate_manifest.json")
    return render_path, render


def promote_render_manifest(case_id: str, promoted_at: str) -> None:
    audit = inspect_case(case_id)
    if audit["status"] != "ready_to_promote":
        raise RuntimeError(f"candidate promotion blocked: {audit['blockers']}")
    path, payload = _promoted_render_payload(case_id, promoted_at)
    _atomic_json(path, payload)


def _updated_index(case_ids: list[str], promoted_at: str) -> dict[str, Any]:
    index = _read(DAILY_INDEX, {})
    for section in index.values():
        if not isinstance(section, dict) or not isinstance(section.get("cases"), dict):
            continue
        for case_id in case_ids:
            case = section["cases"].get(case_id)
            if not isinstance(case, dict):
                continue
            candidate = _read(OUTPUTS / case_id / "formal_targeted_candidate_manifest.json", {})
            case.update(
                {
                    "render_status": "ok",
                    "delivery_gate_status": "ok",
                    "actual_render_source": "formal_targeted_candidate",
                    "remaining_blockers": [],
                    "promoted_at": promoted_at,
                }
            )
            artifacts = case.setdefault("artifacts", {})
            artifacts.update({"translated_pdf": candidate.get("mono_pdf"), "standard_bilingual_pdf": candidate.get("dual_pdf")})
    return index


def update_daily_index(case_ids: list[str], promoted_at: str) -> None:
    for case_id in case_ids:
        audit = inspect_case(case_id)
        if audit["status"] != "ready_to_promote":
            raise RuntimeError(f"candidate promotion blocked: {audit['blockers']}")
    _atomic_json(DAILY_INDEX, _updated_index(case_ids, promoted_at))


def promote_transaction(case_ids: list[str], receipt_path: Path, promoted_at: str | None = None) -> dict[str, Any]:
    """先完成全部 preflight，再以可回滚方式同步 manifest 与 index。"""
    promoted_at = promoted_at or datetime.now(timezone.utc).isoformat()
    audits = [inspect_case(case_id) for case_id in case_ids]
    blockers = [blocker for audit in audits for blocker in audit["blockers"]]
    if blockers:
        return {"status": "blocked", "promoted_at": promoted_at, "cases": audits, "blockers": blockers}
    writes = [_promoted_render_payload(case_id, promoted_at) for case_id in case_ids]
    writes.append((DAILY_INDEX, _updated_index(case_ids, promoted_at)))
    originals = {path: path.read_bytes() if path.exists() else None for path, _ in writes}
    try:
        for path, payload in writes:
            _atomic_json(path, payload)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
    receipt = {"status": "promoted", "promoted_at": promoted_at, "cases": case_ids, "writes": [str(path) for path, _ in writes]}
    _atomic_json(receipt_path, receipt)
    return receipt


def preflight_decision(preflight: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    status = str(preflight.get("status") or "blocked")
    blockers = list(preflight.get("blockers") or [])
    if status == "awaiting_human_acceptance":
        blockers.extend(preflight.get("pending") or [])
    return status, blockers


def next_action_for(status: str) -> str:
    if status == "awaiting_human_acceptance":
        return "python -m cutover.cli accept --reviewer <name> --decision accepted"
    if status == "ready_for_cutover_apply":
        return f"python -m cutover.cli run --apply --approval-phrase {APPLY_APPROVAL_PHRASE}"
    if status == "blocked":
        return "Repair blockers and rerun: python -m cutover.cli audit"
    return "No action required."


def build_receipt(
    *, status: str, apply_requested: bool, apply_allowed: bool, blockers: list[dict[str, Any]], steps: list[Any], preflight: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "apply_requested": apply_requested,
        "apply_allowed": apply_allowed,
        "approval_phrase_required_for_apply": APPLY_APPROVAL_PHRASE,
        "blockers": blockers,
        "steps": steps,
        "preflight": preflight,
        "next_action": next_action_for(status),
    }
