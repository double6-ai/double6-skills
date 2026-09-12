from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .common import (
    D6PPTError, OFFICECLI_VERSION, PPT_MASTER_COMMIT, PPT_MASTER_VERSION,
    RUNTIME_LOCK_SHA, SCHEMA_VERSION, copy_input, ensure_owner_writable, sha256_tree, skill_root, utc_now, write_json, rel_posix)


RUN_DIRS = ("input", "authoring", "artifacts", "evidence", "logs", "review", "delivery", "patches", "plans")
VERIFY_TIERS = {"auto", "native", "portable"}
DESIGN_PROFILES = {
    "neutral": {
        "visual_style": "[fill]",
        "bg": "[fill]",
        "primary": "[fill]",
        "accent": "[fill]",
        "text": "[fill]",
        "font_family": "[fill after doctor confirms availability]",
        "title_size": "40",
        "body_size": "24",
        "footnote_size": "12",
        "page_mark_size": "12",
    },
    "academic": {
        "visual_style": "academic editorial",
        "bg": "#F7F8FA", "primary": "#173A5E", "accent": "#2F6B9A", "text": "#17212B",
        "font_family": "Arial", "title_size": "38", "body_size": "23", "footnote_size": "12", "page_mark_size": "12",
    },
    "business": {
        "visual_style": "business report",
        "bg": "#F8FAFC", "primary": "#16324F", "accent": "#0F766E", "text": "#17212B",
        "font_family": "Arial", "title_size": "40", "body_size": "24", "footnote_size": "12", "page_mark_size": "12",
    },
    "training": {
        "visual_style": "training workshop",
        "bg": "#FFFDF8", "primary": "#4A3428", "accent": "#D97706", "text": "#292524",
        "font_family": "Arial", "title_size": "40", "body_size": "25", "footnote_size": "12", "page_mark_size": "12",
    },
}


def _write_generate_scaffold(run: Path, profile_name: str) -> None:
    profile = DESIGN_PROFILES[profile_name]
    source_dir = skill_root() / "assets" / "scaffolds"
    project = run / "authoring" / "project"
    (project / "svg_output").mkdir(parents=True, exist_ok=True)
    replacements = {
        "{{VISUAL_STYLE}}": profile["visual_style"],
        "{{BG}}": profile["bg"],
        "{{PRIMARY}}": profile["primary"],
        "{{ACCENT}}": profile["accent"],
        "{{TEXT}}": profile["text"],
        "{{FONT_FAMILY}}": profile["font_family"],
        "{{TITLE_SIZE}}": profile["title_size"],
        "{{BODY_SIZE}}": profile["body_size"],
        "{{FOOTNOTE_SIZE}}": profile["footnote_size"],
        "{{PAGE_MARK_SIZE}}": profile["page_mark_size"],
    }
    for name in ("spec_lock.md", "design_spec.md"):
        target = project / name
        if target.exists():
            continue
        text = (source_dir / name).read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        target.write_text(text, encoding="utf-8")
    example = run / "authoring" / "semantic_manifest.example.json"
    if not example.exists():
        write_json(example, {
            "schema_version": SCHEMA_VERSION,
            "defaults": {"roundtrip_font_family": profile["font_family"]},
            "objects": [{
                "source_id": "slide-001-title",
                "slide": 1,
                "role": "title",
                "editable": True,
                "postflight_sensitive": True,
                "preferred_structure": "placeholder",
                "placeholder": "title",
                "source_selector": {"file": "svg_output/01.svg", "id": "title"},
                "match": {"drawingml_id": 1001},
            }],
            "authoring_note": "Set data-pptx-shape-id=1001 on the matching SVG element, then save this file as semantic_manifest.json.",
        })


def init_run(
    mode: str,
    source: Path,
    out: Path,
    template: Path | None = None,
    contract: Path | None = None,
    *,
    verify_tier: str = "auto",
    design_profile: str = "neutral",
) -> dict:
    if mode not in {"generate", "postflight", "template-fill"}:
        raise D6PPTError("mode must be generate, postflight, or template-fill", "invalid_mode")
    if verify_tier not in VERIFY_TIERS:
        raise D6PPTError("verify tier must be auto, native, or portable", "invalid_verify_tier")
    if design_profile not in DESIGN_PROFILES:
        raise D6PPTError("unknown design profile", "invalid_design_profile")
    source = source.resolve()
    out = out.resolve()
    if verify_tier != "portable" and sys.platform == "darwin" and (out == Path("/private/tmp") or Path("/private/tmp") in out.parents):
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
        source_copy = rel_posix(source_target, out)
        current_pptx = None
        if source.is_dir() and (source / "svg_output").is_dir():
            shutil.copytree(source, out / "authoring" / "project")
            for name in ("semantic_manifest.json",):
                if (source / name).is_file():
                    shutil.copy2(source / name, out / "authoring" / name)
            if mode == "generate":
                _write_generate_scaffold(out, design_profile)
        else:
            if mode == "generate":
                _write_generate_scaffold(out, design_profile)
            write_json(out / "authoring" / "authoring_request.json", {
                "schema_version": SCHEMA_VERSION,
                "source": source_copy,
                "source_sha256": source_sha,
                "instruction": (
                    "Create a confirmed native template fill plan before template-apply."
                    if mode == "template-fill" else
                    "Complete authoring/project/spec_lock.md and design_spec.md, create SVG pages in authoring/project/svg_output, then copy semantic_manifest.example.json to semantic_manifest.json and replace its example object list before compile."
                ),
            })
    template_record = None
    if template is not None:
        template_copy = out / "input" / "template.pptx"
        shutil.copy2(template, template_copy)
        template_record = {
            "original_path": str(template),
            "copied_path": rel_posix(template_copy, out),
            "sha256": sha256_tree(template),
        }
    contract_record = None
    if contract is not None:
        contract_copy = out / "input" / "content_contract.json"
        shutil.copy2(contract, contract_copy)
        contract_record = {
            "original_path": str(contract),
            "copied_path": rel_posix(contract_copy, out),
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
        "verification_preference": verify_tier,
        "target_application": "portable" if verify_tier == "portable" else "powerpoint_preferred",
        "design_profile": design_profile if mode == "generate" else None,
        "visual_policy": {
            "mode": "default_visual_review",
            "capability": "unknown",
            "decision": "pending",
        },
    }
    write_json(out / "run_manifest.json", manifest)
    return manifest
