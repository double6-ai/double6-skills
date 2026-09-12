from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, read_json, resolve_run_path, set_status, sha256_file, utc_now, write_json, rel_posix


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
    powerpoint_status = verification.get("powerpoint_status")
    verification_tier = verification.get("verification_tier", "native")
    if powerpoint_status not in {"verified", "skipped_portable_tier"}:
        raise D6PPTError("Microsoft PowerPoint verification is required", "powerpoint_verification_missing")
    if verification_tier == "portable" or powerpoint_status == "skipped_portable_tier":
        warnings.append(
            "未在本机 Microsoft PowerPoint 完成原生 roundtrip；当前交付为 portable 档（OfficeCLI 持久化/改字探针）。"
        )
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
    if verification_tier == "portable":
        probe_status = (verification.get("officecli_edit_probe") or {}).get("status")
        render_status = (verification.get("portable_render") or {}).get("status")
        probe_text = (
            "OfficeCLI 改字与移动持久化探针通过"
            if probe_status == "pass" else
            "因缺少可信对象映射，OfficeCLI 改字探针未自动执行"
            if probe_status == "not_automated" else
            "OfficeCLI 改字探针未通过"
        )
        render_text = "LibreOffice 逐页渲染已完成" if render_status == "pass" else "portable 逐页渲染不可用"
        compatibility_statement = (
            f"原始交付文件已通过 OOXML 完整性与 OfficeCLI 校验；{probe_text}；{render_text}；"
            "本机未执行 Microsoft PowerPoint 原生另存、重开和移动对象门禁。"
        )
    else:
        compatibility_statement = (
            "原始交付文件为原生可编辑 PPTX，已通过 OfficeCLI 校验与 Microsoft PowerPoint 原生另存、重开、"
            "改字、移动对象、再次保存和持久化验证；逐页渲染事实源来自 Microsoft PowerPoint。"
        )
    if verification.get("gates", {}).get("visual_review") == "skipped_with_user_ack":
        compatibility_statement += " 未进行模型视觉质量检查。"
    if isinstance(libreoffice, dict):
        compatibility_statement += " LibreOffice 仅作为显式请求的附加兼容性检查。"
    delivery = {
        "schema_version": SCHEMA_VERSION, "created_at": utc_now(), "status": delivery_status,
        "run_id": manifest["run_id"], "mode": manifest["mode"],
        "artifact": rel_posix(current, run), "artifact_sha256": current_sha,
        "gates": verification.get("gates"), "warnings": warnings,
        "verification_tier": verification_tier,
        "libreoffice_receipt": (
            "evidence/libreoffice_roundtrip/receipt.json" if isinstance(libreoffice, dict) else None
        ),
        "powerpoint_receipt": verification.get("powerpoint_receipt"),
        "powerpoint_status": powerpoint_status,
        "visual_review_status": verification.get("gates", {}).get("visual_review"),
        "visual_review_receipt": verification.get("visual_receipt"),
        "compatibility_statement": compatibility_statement,
        "tier_result": verification.get("tier_result"),
        "public_release_authorized": False,
    }
    write_json(run / "delivery" / "delivery_manifest.json", delivery)
    manifest["artifacts"]["delivery_manifest"] = "delivery/delivery_manifest.json"
    set_status(run, manifest, delivery_status, "finalize", {"failed_gates": failed, "warnings": warnings})
    return delivery
