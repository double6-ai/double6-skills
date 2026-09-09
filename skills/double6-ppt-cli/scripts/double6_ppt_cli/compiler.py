from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .common import D6PPTError, invalidate_pptx_derived_artifacts, load_run, save_run, set_status, sha256_file, skill_root, utc_now, write_json
from .semantic import apply_semantic_contract
from .source_adapter import prepare_ppt_master_project


def _check_authoring_scaffold(project: Path, semantic: Path) -> None:
    missing = []
    if not project.is_dir():
        missing.append("authoring/project")
    if not semantic.is_file():
        missing.append("authoring/semantic_manifest.json")
    spec = project / "spec_lock.md"
    if project.is_dir() and not spec.is_file():
        missing.append("authoring/project/spec_lock.md")
    if missing:
        raise D6PPTError(
            "Generate authoring is incomplete: " + ", ".join(missing),
            "authoring_incomplete",
            {
                "next_steps": [
                    "Complete authoring/project/spec_lock.md and design_spec.md.",
                    "Create SVG pages under authoring/project/svg_output/.",
                    "Copy authoring/semantic_manifest.example.json to authoring/semantic_manifest.json and replace the example objects.",
                ]
            },
        )
    spec_text = spec.read_text(encoding="utf-8")
    if "[fill" in spec_text or "- status: draft" in spec_text:
        raise D6PPTError(
            "The generated spec_lock scaffold still contains draft fields",
            "authoring_scaffold_incomplete",
            {
                "path": str(spec),
                "next_step": "Fill every [fill] field and change '- status: draft' to '- status: confirmed'.",
            },
        )


def compile_run(run: Path, *, native_charts_and_tables: bool = True) -> dict:
    run = run.resolve()
    manifest = load_run(run)
    prior_pptx_sha = manifest.get("artifacts", {}).get("pptx_sha256")
    if manifest["mode"] != "generate":
        raise D6PPTError("compile is only available for generate runs", "invalid_command_for_mode")
    project = run / "authoring" / "project"
    semantic = run / "authoring" / "semantic_manifest.json"
    _check_authoring_scaffold(project, semantic)
    set_status(run, manifest, "authored", "authoring_contract_present")
    build_project = run / "build" / "ppt-master-project"
    prepare_ppt_master_project(
        project,
        semantic,
        build_project,
        run / "evidence" / "source_adapter_receipt.json",
    )
    converter = skill_root() / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"
    checker = skill_root() / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "scripts" / "svg_quality_checker.py"
    raw = run / "artifacts" / "compiler_raw.pptx"
    final = run / "artifacts" / "current.pptx"
    object_map = run / "artifacts" / "object_path_map.json"
    trace = run / "evidence" / "conversion_trace.json"
    quality_command = [sys.executable, str(checker), str(build_project), "--stage", "final", "--json"]
    quality = subprocess.run(quality_command, capture_output=True, text=True, timeout=300)
    write_json(run / "logs" / "svg_quality_checker.json", {
        "at": utc_now(), "command": quality_command, "returncode": quality.returncode,
        "stdout": quality.stdout, "stderr": quality.stderr,
    })
    if quality.returncode != 0:
        set_status(run, manifest, "blocked", "svg_quality_failed", quality.stdout[-4000:] + quality.stderr[-4000:])
        raise D6PPTError("PPT Master SVG quality gate failed", "svg_quality_failed")
    command = [sys.executable, str(converter), str(build_project), "-o", str(raw), "--conversion-trace", str(trace), "--pptx-structure", "flat"]
    if native_charts_and_tables:
        command.append("--native-charts-and-tables")
    proc = subprocess.run(command, capture_output=True, text=True, timeout=600)
    write_json(run / "logs" / "compiler.json", {
        "at": utc_now(), "command": command, "returncode": proc.returncode,
        "stdout": proc.stdout, "stderr": proc.stderr,
    })
    if proc.returncode != 0 or not raw.is_file():
        set_status(run, manifest, "blocked", "compile_failed", proc.stderr[-4000:])
        raise D6PPTError("PPT Master compiler failed", "compile_failed")
    try:
        mapping = apply_semantic_contract(raw, semantic, final, object_map, project)
    except Exception as exc:
        set_status(run, manifest, "blocked", "semantic_contract_failed", str(exc))
        raise
    raw.unlink(missing_ok=True)
    manifest["artifacts"].update({
        "current_pptx": "artifacts/current.pptx",
        "object_path_map": "artifacts/object_path_map.json",
        "semantic_manifest": "authoring/semantic_manifest.json",
        "pptx_sha256": sha256_file(final),
    })
    current_pptx_sha = manifest["artifacts"]["pptx_sha256"]
    if prior_pptx_sha and prior_pptx_sha != current_pptx_sha:
        stale = invalidate_pptx_derived_artifacts(manifest)
        manifest.setdefault("stale_artifacts", []).append({
            "at": utc_now(),
            "reason": "pptx_sha_changed_after_recompile",
            "prior_pptx_sha256": prior_pptx_sha,
            "current_pptx_sha256": current_pptx_sha,
            "artifacts": stale,
        })
    prior_ledger = run / "evidence" / "patch_ledger.json"
    if prior_ledger.is_file():
        from .common import read_json
        manifest["unreplayed_patches"] = [entry["patch_id"] for entry in read_json(prior_ledger).get("entries", [])]
    else:
        manifest["unreplayed_patches"] = []
    set_status(run, manifest, "compiled", "compile", {"objects": mapping["resolved_count"]})
    return manifest
