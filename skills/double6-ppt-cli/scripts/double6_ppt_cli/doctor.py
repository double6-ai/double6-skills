from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import (
    D6PPTError, OFFICECLI_VERSION, PPT_MASTER_COMMIT, RUNTIME_LOCK_SHA, default_runtime_dir,
    classify_officecli_version, content_sha_matches, sha256_file, skill_root,
)
from .powerpoint import find_powerpoint


def _bin_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("officecli.cmd", "officecli.exe", "officecli.js", "officecli")
    return ("officecli", "officecli.js")


def officecli_argv(binary: Path | None) -> list[str]:
    """Build a portable OfficeCLI command; .js entries need node on Windows/POSIX."""
    if not binary:
        return []
    if binary.suffix.lower() == ".js":
        node = shutil.which("node")
        if not node:
            raise D6PPTError(
                "OfficeCLI JavaScript entry requires node on PATH; install Node.js or bootstrap the runtime",
                "officecli_node_missing",
            )
        return [node, str(binary)]
    return [str(binary)]


def _officecli_candidates(runtime_dir: Path | None = None) -> list[Path]:
    values: list[Path] = []
    if os.environ.get("D6PPT_OFFICECLI"):
        values.append(Path(os.environ["D6PPT_OFFICECLI"]))
    runtime = runtime_dir or default_runtime_dir()
    for name in _bin_names():
        values.append(runtime / "node" / "node_modules" / ".bin" / name)
    values.extend([
        runtime / "node" / "node_modules" / "@officecli" / "officecli" / "officecli.js",
        runtime / "node" / "node_modules" / "@officecli" / "officecli" / "vendor" / "officecli",
    ])
    # Fallback: previous skill-version lock dirs under the cache root.
    cache_root = Path.home() / ".cache" / "double6-ppt-cli"
    if cache_root.is_dir():
        for child in sorted(cache_root.iterdir(), reverse=True):
            for name in _bin_names():
                values.append(child / "node" / "node_modules" / ".bin" / name)
            values.append(child / "node" / "node_modules" / "@officecli" / "officecli" / "officecli.js")
    if shutil.which("officecli"):
        values.append(Path(shutil.which("officecli") or ""))
    # de-dupe while preserving order
    seen = set()
    unique = []
    for item in values:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def find_officecli(runtime_dir: Path | None = None) -> Path | None:
    for candidate in _officecli_candidates(runtime_dir):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def find_soffice() -> Path | None:
    candidates = []
    if os.environ.get("D6PPT_SOFFICE"):
        candidates.append(Path(os.environ["D6PPT_SOFFICE"]))
    if shutil.which("soffice"):
        candidates.append(Path(shutil.which("soffice") or ""))
    candidates.extend([
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("/usr/bin/soffice"), Path("/usr/local/bin/soffice"),
    ])
    return next((p.resolve() for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def _version(binary: Path | None) -> str | None:
    if not binary:
        return None
    try:
        proc = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=15)
        return (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


CLAW_HUB_OMITTED_VENDOR_FILES = {
    "skills/ppt-master/scripts/pptx_animation_presets.json",
    "skills/ppt-master/scripts/pptx_shapes/data/presetShapeDefinitions.xml",
}


def _vendor_integrity(root: Path) -> dict[str, Any]:
    vendor_root = root / "vendor" / "ppt-master-core"
    bom_path = vendor_root / "BOM.json"
    if not bom_path.is_file():
        return {
            "status": "fail", "complete": False, "bom": str(bom_path),
            "reason": "Vendored PPT Master BOM is missing.",
        }
    try:
        bom = json.loads(bom_path.read_text(encoding="utf-8"))
        entries = bom.get("files", [])
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        return {
            "status": "fail", "complete": False, "bom": str(bom_path),
            "reason": f"Vendored PPT Master BOM is invalid: {exc}",
        }
    if not isinstance(entries, list) or not entries:
        return {
            "status": "fail", "complete": False, "bom": str(bom_path),
            "reason": "Vendored PPT Master BOM has no file entries.",
        }
    missing: list[str] = []
    mismatched: list[str] = []
    invalid_entries: list[int] = []
    seen_paths: set[str] = set()
    duplicates: list[str] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            invalid_entries.append(index)
            continue
        relative = str(entry.get("path") or "")
        expected = str(entry.get("sha256") or "")
        if not relative or not expected:
            invalid_entries.append(index)
            continue
        if relative in seen_paths:
            duplicates.append(relative)
            continue
        seen_paths.add(relative)
        candidate = (vendor_root / relative).resolve()
        try:
            candidate.relative_to(vendor_root.resolve())
        except ValueError:
            invalid_entries.append(index)
            continue
        if not relative or not candidate.is_file():
            missing.append(relative)
        elif expected and not content_sha_matches(candidate, expected):
            mismatched.append(relative)
    expected_omissions = sorted(set(missing) & CLAW_HUB_OMITTED_VENDOR_FILES)
    unexpected_missing = sorted(set(missing) - CLAW_HUB_OMITTED_VENDOR_FILES)
    declared_count_ok = bom.get("file_count") == len(entries)
    if mismatched or unexpected_missing or invalid_entries or duplicates or not declared_count_ok:
        status = "fail"
    elif expected_omissions:
        status = "partial"
    else:
        status = "pass"
    return {
        "status": status,
        "complete": status == "pass",
        "bom": str(bom_path),
        "bom_sha256": sha256_file(bom_path),
        "ppt_master_commit": PPT_MASTER_COMMIT,
        "checked_file_count": len(entries),
        "missing": sorted(missing),
        "expected_clawhub_omissions": expected_omissions,
        "unexpected_missing": unexpected_missing,
        "sha256_mismatches": sorted(mismatched),
        "invalid_entries": invalid_entries,
        "duplicate_paths": sorted(set(duplicates)),
        "declared_file_count": bom.get("file_count"),
        "declared_file_count_matches": declared_count_ok,
        "capabilities": {
            "postflight": status != "fail",
            "full_generate": status == "pass",
            "template_fill": status == "pass",
        },
        "repair": "Install the complete skill from GitHub or skills.sh when full generate/template-fill capability is required.",
    }


def _officecli_runtime_probe(binary: Path | None) -> dict[str, Any]:
    if not binary:
        return {"ok": False, "reason": "missing_binary"}
    try:
        command = officecli_argv(binary)
    except D6PPTError as exc:
        return {"ok": False, "reason": exc.code, "message": str(exc)}
    try:
        proc = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": "launch_failed", "command": command, "message": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "command": command,
        "returncode": proc.returncode,
        "version_line": (proc.stdout or proc.stderr).strip().splitlines()[:1],
    }


def doctor(
    runtime_dir: Path | None = None,
    *,
    verify_tier: str = "auto",
    mode: str | None = None,
) -> dict[str, Any]:
    if verify_tier not in {"auto", "native", "portable"}:
        raise D6PPTError("verify tier must be auto, native, or portable", "invalid_verify_tier")
    if mode not in {None, "generate", "postflight", "template-fill"}:
        raise D6PPTError("doctor mode must be generate, postflight, or template-fill", "invalid_mode")
    root = skill_root()
    officecli = find_officecli(runtime_dir)
    officecli_version = _version(officecli)
    officecli_policy = classify_officecli_version(officecli_version)
    soffice = find_soffice()
    pdftoppm = shutil.which("pdftoppm")
    vendor = _vendor_integrity(root)
    python_modules = {}
    for module in ("lxml", "PIL", "pptx", "xlsxwriter"):
        try:
            __import__(module)
            python_modules[module] = "available"
        except ImportError:
            python_modules[module] = "missing"
    fonts = []
    for directory in (
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("/usr/share/fonts"),
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Fonts",
    ):
        if directory.exists():
            fonts.append(str(directory))
    powerpoint = find_powerpoint()
    osascript = shutil.which("osascript")
    checks = {
        "python": {"status": "pass", "version": platform.python_version()},
        "python_modules": {"status": "pass" if all(v == "available" for v in python_modules.values()) else "fail", "modules": python_modules},
        "officecli": {
            "status": officecli_policy["status"],
            "path": str(officecli) if officecli else None,
            "expected_version": OFFICECLI_VERSION,
            "actual_version": officecli_version,
            "policy": officecli_policy,
            "risk": officecli_policy.get("risk"),
            "message": officecli_policy.get("message"),
            "repair": f"python scripts/d6ppt.py bootstrap --runtime-dir {runtime_dir or default_runtime_dir()} --yes",
            "auto_adapt": officecli_policy["status"] == "warn",
            "runtime_probe": _officecli_runtime_probe(officecli),
        },
        "libreoffice": {
            "status": "available" if soffice else "unavailable", "path": str(soffice) if soffice else None,
            "required": False,
            "required_for": "portable visual rendering",
            "reason": "Optional portable renderer and optional native-tier compatibility target.",
        },
        "pdf_renderer": {
            "status": "available" if pdftoppm else "unavailable", "path": pdftoppm,
            "required_for": "native or portable page rendering",
            "reason": "Rasterizes renderer PDF exports for page review; a user-approved visual waiver can omit rendering in portable tier.",
        },
        "fonts": {"status": "pass" if fonts else "warn", "directories": fonts},
        "vendor": vendor,
        "powerpoint": {
            "status": "available" if powerpoint else "unavailable",
            "path": str(powerpoint) if powerpoint else None,
            "required_for": "native tier (macOS + Microsoft PowerPoint)",
            "repair": "Install Microsoft PowerPoint on macOS, or use --verify-tier portable on any OS.",
        },
        "powerpoint_automation": {
            "status": "available" if osascript else "unavailable", "path": osascript,
            "required_for": "native tier (macOS only)",
            "repair": "On macOS, allow terminal automation for native verification; otherwise use --verify-tier portable (no macOS/PowerPoint required).",
        },
    }
    base_ready = (
        checks["python_modules"]["status"] == "pass"
        and checks["officecli"]["status"] in {"pass", "warn"}
    )
    vendor_required = mode in {"generate", "template-fill"}
    vendor_ready = vendor["status"] == "pass" if vendor_required else vendor["status"] != "fail"
    portable_ready = base_ready and vendor_ready
    portable_render_ready = portable_ready and bool(soffice) and bool(pdftoppm)
    native_ready = portable_ready and bool(powerpoint) and bool(osascript) and bool(pdftoppm)
    if verify_tier == "native":
        status = "pass" if native_ready else "fail"
        selected_tier = "native"
    elif verify_tier == "portable":
        status = "fail" if not portable_ready else ("pass" if portable_render_ready else "pass_with_warnings")
        selected_tier = "portable"
    elif native_ready:
        status = "pass"
        selected_tier = "native"
    elif portable_ready:
        status = "pass_with_warnings"
        selected_tier = "portable"
    else:
        status = "fail"
        selected_tier = None
    return {
        "schema_version": "2.0", "status": status,
        "requested_verify_tier": verify_tier, "selected_verify_tier": selected_tier, "mode": mode,
        "capabilities": {
            "native_ready": native_ready,
            "portable_ready": portable_ready,
            "portable_render_ready": portable_render_ready,
            "visual_waiver_required_for_portable": portable_ready and not portable_render_ready,
        },
        "runtime_lock_sha": RUNTIME_LOCK_SHA, "runtime_dir": str(runtime_dir or default_runtime_dir()), "checks": checks,
    }
