from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, read_json, resolve_run_path, sha256_file, utc_now, write_json


LEAF_PATH = re.compile(
    r"/slide\[\d+\](?:/group\[@id=\d+\])*/(shape|textbox|equation|connector|picture)\[@id=(\d+)\]"
)


def build_patch_plan(run: Path, output: Path, confirmed_findings: list[str] | None = None) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    findings_payload = read_json(run / "evidence" / "findings.json")
    current_sha = sha256_file(current)
    if findings_payload.get("pptx_sha256") != current_sha:
        raise D6PPTError("Inspect the current PPTX before planning patches", "inspection_stale")
    confirmed = set(confirmed_findings or [])
    inspection_path = run / "artifacts" / "inspection_map.json"
    inspection = read_json(inspection_path) if inspection_path.is_file() else {"objects": []}
    rows = {str(item.get("officecli_path")): item for item in inspection.get("objects", [])}
    patches = []
    skipped = []
    planned_paths: set[str] = set()
    for finding in findings_payload.get("findings", []):
        finding_id = str(finding.get("finding_id") or "")
        path = str((finding.get("object") or {}).get("officecli_path") or "")
        match = LEAF_PATH.fullmatch(path)
        confirmed_picture = finding_id in confirmed and match and match.group(1) == "picture"
        automatic = finding.get("deterministic") is True and finding.get("suggested_route") == "bounded_patch"
        if not match or not (automatic or confirmed_picture):
            skipped.append({"finding_id": finding_id, "reason": "manual_or_non_leaf"})
            continue
        if path in planned_paths:
            skipped.append({"finding_id": finding_id, "reason": "duplicate_target_path"})
            continue
        row = rows.get(path, {})
        observed_text = str(row.get("text") or finding.get("evidence", {}).get("text") or "")
        operation = finding.get("suggested_operation") or "set_property"
        patch = {
            "source_id": row.get("inspection_id") or f"inspection:{path}",
            "officecli_path": path,
            "operation": operation,
            "finding_id": finding_id,
            "source_template_object_id": f"output:{path}",
            "reason": str(finding.get("message") or "deterministic inspection repair"),
            "expected_fingerprint": {
                "drawingml_id": int(match.group(2)),
                "object_type": match.group(1),
                "text": observed_text,
                "text_sha256": hashlib.sha256(observed_text.strip().encode("utf-8")).hexdigest(),
            },
        }
        if operation == "set_property":
            value = finding.get("suggested_value")
            if value is None:
                skipped.append({"finding_id": finding_id, "reason": "replacement_value_missing"})
                continue
            patch.update({"property": finding.get("suggested_property") or "text", "value": value})
        if confirmed_picture:
            patch["user_confirmed"] = True
        patches.append(patch)
        planned_paths.add(path)
    if not patches:
        raise D6PPTError("No deterministic or explicitly confirmed leaf repairs are available", "no_safe_patch")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "pptx_sha256": current_sha,
        "user_confirmed": bool(confirmed),
        "confirmation_source": "explicit --confirm-finding values" if confirmed else None,
        "patches": patches,
        "skipped_findings": skipped,
    }
    output = output.resolve()
    write_json(output, payload)
    return {"status": "pass", "patch_spec": str(output), "patch_count": len(patches), "skipped_count": len(skipped)}
