from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .common import (
    D6PPTError, OFFICECLI_VERSION, PPT_MASTER_COMMIT, PPT_MASTER_VERSION,
    RUNTIME_LOCK_SHA, SCHEMA_VERSION, copy_input, ensure_owner_writable, sha256_tree, utc_now, write_json,
)


RUN_DIRS = ("input", "authoring", "artifacts", "evidence", "logs", "review", "delivery", "patches", "plans")


def init_run(
    mode: str,
    source: Path,
    out: Path,
    template: Path | None = None,
    contract: Path | None = None,
) -> dict:
    if mode not in {"generate", "postflight", "template-fill"}:
        raise D6PPTError("mode must be generate, postflight, or template-fill", "invalid_mode")
    source = source.resolve()
    out = out.resolve()
    if sys.platform == "darwin" and (out == Path("/private/tmp") or Path("/private/tmp") in out.parents):
        raise D6PPTError(
            "PowerPoint run directories cannot live under /private/tmp on macOS; choose a user-accessible project directory to avoid repeated file-access prompts",
            "powerpoint_inaccessible_workdir",
            {"run_directory": str(out)},
        )
    if not source.exists():
        raise D6PPTError(f"Source does not exist: {source}", "source_missing")
    template = template.resolve() if template else None
    contract = contract.resolve() if contract else None
    if mode == "template-fill" and template is None:
        raise D6PPTError("template-fill requires --template", "template_missing")
    if template is not None and (not template.is_file() or template.suffix.lower() != ".pptx"):
        raise D6PPTError("template must be one PPTX file", "invalid_template")
    if contract is not None and (not contract.is_file() or contract.suffix.lower() != ".json"):
        raise D6PPTError("content contract must be one JSON file", "invalid_content_contract")
    if out.exists():
        raise D6PPTError(f"Run directory already exists: {out}", "run_exists")
    out.mkdir(parents=True)
    for name in RUN_DIRS:
        (out / name).mkdir()
    source_sha = sha256_tree(source)
    if mode == "postflight":
        if source.suffix.lower() != ".pptx" or not source.is_file():
            raise D6PPTError("postflight source must be one PPTX file", "invalid_postflight_source")
        base = out / "artifacts" / "base.pptx"
        current = out / "artifacts" / "current.pptx"
        shutil.copy2(source, base)
        shutil.copy2(source, current)
        ensure_owner_writable(current)
        source_copy = "artifacts/base.pptx"
        current_pptx = "artifacts/current.pptx"
    else:
        source_target = out / "input" / ("source" if source.is_dir() else source.name)
        copy_input(source, source_target)
        source_copy = str(source_target.relative_to(out))
        current_pptx = None
        if source.is_dir() and (source / "svg_output").is_dir():
            shutil.copytree(source, out / "authoring" / "project")
            for name in ("semantic_manifest.json",):
                if (source / name).is_file():
                    shutil.copy2(source / name, out / "authoring" / name)
        else:
            write_json(out / "authoring" / "authoring_request.json", {
                "schema_version": SCHEMA_VERSION,
                "source": source_copy,
                "source_sha256": source_sha,
                "instruction": (
                    "Create a confirmed native template fill plan before template-apply."
                    if mode == "template-fill" else
                    "Author a PPT Master project in authoring/project and a semantic_manifest.json before compile."
                ),
            })
    template_record = None
    if template is not None:
        template_copy = out / "input" / "template.pptx"
        shutil.copy2(template, template_copy)
        template_record = {
            "original_path": str(template),
            "copied_path": str(template_copy.relative_to(out)),
            "sha256": sha256_tree(template),
        }
    contract_record = None
    if contract is not None:
        contract_copy = out / "input" / "content_contract.json"
        shutil.copy2(contract, contract_copy)
        contract_record = {
            "original_path": str(contract),
            "copied_path": str(contract_copy.relative_to(out)),
            "sha256": sha256_tree(contract),
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": out.name,
        "mode": mode,
        "status": "initialized",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "input": {"original_path": str(source), "copied_path": source_copy, "sha256": source_sha},
        "template": template_record,
        "content_contract": contract_record,
        "upstream": {
            "ppt_master": {"version": PPT_MASTER_VERSION, "commit": PPT_MASTER_COMMIT, "delivery": "vendored_lean_core"},
            "officecli": {"version": OFFICECLI_VERSION, "delivery": "external_pinned_dependency"},
            "runtime_lock_sha": RUNTIME_LOCK_SHA,
        },
        "artifacts": {"current_pptx": current_pptx},
        "stage_history": [{"at": utc_now(), "stage": "init", "status": "initialized"}],
        "unreplayed_patches": [],
        "powerpoint_status": "unverified",
        "target_application": "powerpoint",
        "visual_policy": {
            "mode": "default_visual_review",
            "capability": "unknown",
            "decision": "pending",
        },
    }
    write_json(out / "run_manifest.json", manifest)
    return manifest
