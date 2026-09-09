from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    D6PPTError,
    SCHEMA_VERSION,
    load_run,
    resolve_run_path,
    save_run,
    sha256_file,
    utc_now,
    write_json,
)


CAPABILITIES = {"available", "unavailable", "unknown"}
DECISIONS = {"perform", "waive"}
WAIVER_REASONS = {"user_declined_switch", "no_visual_model", "user_requested_skip"}


def set_visual_policy(
    run: Path,
    capability: str,
    decision: str,
    reason: str | None = None,
    user_ack: bool = False,
) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    if capability not in CAPABILITIES or decision not in DECISIONS:
        raise D6PPTError("Invalid visual policy", "invalid_visual_policy")
    if decision == "perform" and capability != "available":
        raise D6PPTError(
            "A model without declared vision capability cannot perform visual review",
            "visual_model_switch_required",
            {"suggested_prompt": "当前模型没有可确认的视觉能力，是否切换到视觉模型进行逐页检查？"},
        )
    current_rel = manifest.get("artifacts", {}).get("current_pptx")
    current = resolve_run_path(run, current_rel) if current_rel else None
    current_sha = sha256_file(current) if current and current.is_file() else None
    record = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "capability": capability,
        "decision": decision,
        "pptx_sha256": current_sha,
    }
    if decision == "waive":
        if reason not in WAIVER_REASONS or user_ack is not True:
            raise D6PPTError(
                "Visual waiver requires an allowed reason and --user-ack",
                "visual_waiver_confirmation_required",
            )
        record.update({
            "status": "skipped_with_user_ack",
            "reason": reason,
            "user_ack": True,
            "claim_boundary": "Visual quality was not assessed by a vision-capable model.",
        })
        write_json(run / "review" / "visual_review_waiver.json", record)
        (run / "review" / "visual_review.json").unlink(missing_ok=True)
        manifest.setdefault("artifacts", {})["visual_review_waiver"] = "review/visual_review_waiver.json"
        manifest["artifacts"].pop("visual_review", None)
    else:
        record["status"] = "visual_review_required"
        (run / "review" / "visual_review_waiver.json").unlink(missing_ok=True)
        manifest.setdefault("artifacts", {}).pop("visual_review_waiver", None)
    manifest["visual_policy"] = {
        "mode": "default_visual_review",
        "capability": capability,
        "decision": decision,
        "reason": reason,
        "recorded_at": record["created_at"],
        "pptx_sha256": current_sha,
    }
    save_run(run, manifest)
    return record


def resolve_visual_gate(run: Path, pptx_sha256: str) -> tuple[str, dict[str, Any]]:
    visual_path = run / "review" / "visual_review.json"
    if visual_path.is_file():
        from .common import read_json

        visual = read_json(visual_path)
        valid = (
            visual.get("status") in {"accepted", "accepted_with_warnings"}
            and visual.get("pptx_sha256") == pptx_sha256
        )
        if valid:
            return "pass", visual
    waiver_path = run / "review" / "visual_review_waiver.json"
    if waiver_path.is_file():
        from .common import read_json

        waiver = read_json(waiver_path)
        valid = (
            waiver.get("status") == "skipped_with_user_ack"
            and waiver.get("user_ack") is True
            and waiver.get("reason") in WAIVER_REASONS
            and waiver.get("pptx_sha256") == pptx_sha256
        )
        if valid:
            return "skipped_with_user_ack", waiver
    raise D6PPTError(
        "Visual review is pending. Use a vision-capable model, or record a per-run user waiver.",
        "visual_review_decision_required",
        {
            "suggested_prompt": "当前模型无法确认具备视觉检查能力。是否切换到视觉模型逐页检查？如果不切换，可以明确选择跳过；跳过不会阻断交付，但会标记视觉未验证。",
            "commands": {
                "perform": "d6ppt visual-policy --capability available --decision perform",
                "waive": "d6ppt visual-policy --capability unavailable --decision waive --reason <reason> --user-ack",
            },
        },
    )
