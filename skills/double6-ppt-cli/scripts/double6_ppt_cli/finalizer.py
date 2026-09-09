from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, read_json, resolve_run_path, set_status, sha256_file, utc_now, write_json


def finalize_run(run: Path) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    verification_path = run / "evidence" / "verification_receipt.json"
    if not verification_path.is_file():
        raise D6PPTError("verify must run before finalize", "verification_missing")
    verification = read_json(verification_path)
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    current_sha = sha256_file(current)
    if verification.get("source_pptx_sha256") != current_sha:
        raise D6PPTError("Verification receipt is stale", "verification_stale")
    if verification.get("status") not in {"pass", "pass_with_warnings"}:
        raise D6PPTError("Verification did not pass", "verification_failed")
    failed = [name for name, value in verification.get("gates", {}).items() if value == "fail"]
    warnings = []
    if verification.get("powerpoint_status") != "verified":
        raise D6PPTError("Microsoft PowerPoint verification is required", "powerpoint_verification_missing")
    if verification.get("gates", {}).get("visual_review") == "skipped_with_user_ack":
        warnings.append("未进行模型视觉质量检查；当前 PPTX SHA 已记录用户豁免。")
    libreoffice = verification.get("libreoffice_compatibility")
    if isinstance(libreoffice, dict):
        diff = libreoffice.get("package_diff", {})
        if diff.get("changed") or diff.get("added") or diff.get("removed"):
            warnings.append("LibreOffice 附加兼容性 roundtrip 重写了 package parts；详见验证回执。")
    warning_gates = [name for name, value in verification.get("gates", {}).items() if value == "warn"]
    if warning_gates:
        warnings.append(f"Warning gates remain: {', '.join(sorted(warning_gates))}.")
    if failed:
        delivery_status = "blocked"
    elif warnings:
        delivery_status = "delivered_with_warnings"
    else:
        delivery_status = "local_delivered"
    delivery = {
        "schema_version": SCHEMA_VERSION, "created_at": utc_now(), "status": delivery_status,
        "run_id": manifest["run_id"], "mode": manifest["mode"],
        "artifact": str(current.relative_to(run)), "artifact_sha256": current_sha,
        "gates": verification.get("gates"), "warnings": warnings,
        "libreoffice_receipt": (
            "evidence/libreoffice_roundtrip/receipt.json" if isinstance(libreoffice, dict) else None
        ),
        "powerpoint_receipt": verification.get("powerpoint_receipt"),
        "powerpoint_status": "verified",
        "visual_review_status": verification.get("gates", {}).get("visual_review"),
        "visual_review_receipt": verification.get("visual_receipt"),
        "compatibility_statement": (
            "原始交付文件为原生可编辑 PPTX，已通过 OfficeCLI 校验与 Microsoft PowerPoint 原生另存、重开、"
            "改字、移动对象、再次保存和持久化验证；逐页渲染事实源来自 Microsoft PowerPoint。"
            + (" 未进行模型视觉质量检查。" if verification.get("gates", {}).get("visual_review") == "skipped_with_user_ack" else "")
            + (" LibreOffice 仅作为显式请求的附加兼容性检查。" if isinstance(libreoffice, dict) else "")
        ),
        "public_release_authorized": False,
    }
    write_json(run / "delivery" / "delivery_manifest.json", delivery)
    manifest["artifacts"]["delivery_manifest"] = "delivery/delivery_manifest.json"
    set_status(run, manifest, delivery_status, "finalize", {"failed_gates": failed, "warnings": warnings})
    return delivery
