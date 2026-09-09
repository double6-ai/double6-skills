from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .common import (
    OFFICECLI_VERSION, PPT_MASTER_COMMIT, RUNTIME_LOCK_SHA, default_runtime_dir,
    sha256_file, skill_root,
)
from .powerpoint import find_powerpoint


def _officecli_candidates(runtime_dir: Path | None = None) -> list[Path]:
    values: list[Path] = []
    if os.environ.get("D6PPT_OFFICECLI"):
        values.append(Path(os.environ["D6PPT_OFFICECLI"]))
    runtime = runtime_dir or default_runtime_dir()
    values.extend([
        runtime / "node" / "node_modules" / ".bin" / "officecli",
        runtime / "node" / "node_modules" / "@officecli" / "officecli" / "vendor" / "officecli",
    ])
    if shutil.which("officecli"):
        values.append(Path(shutil.which("officecli") or ""))
    return values


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


def doctor(runtime_dir: Path | None = None) -> dict[str, Any]:
    root = skill_root()
    officecli = find_officecli(runtime_dir)
    officecli_version = _version(officecli)
    soffice = find_soffice()
    pdftoppm = shutil.which("pdftoppm")
    bom_path = root / "vendor" / "ppt-master-core" / "BOM.json"
    python_modules = {}
    for module in ("lxml", "PIL", "pptx", "xlsxwriter"):
        try:
            __import__(module)
            python_modules[module] = "available"
        except ImportError:
            python_modules[module] = "missing"
    fonts = []
    for directory in (Path.home() / "Library/Fonts", Path("/Library/Fonts"), Path("/usr/share/fonts")):
        if directory.exists():
            fonts.append(str(directory))
    powerpoint = find_powerpoint()
    osascript = shutil.which("osascript")
    checks = {
        "python": {"status": "pass", "version": platform.python_version()},
        "python_modules": {"status": "pass" if all(v == "available" for v in python_modules.values()) else "fail", "modules": python_modules},
        "officecli": {
            "status": "pass" if officecli_version == OFFICECLI_VERSION else "fail",
            "path": str(officecli) if officecli else None,
            "expected_version": OFFICECLI_VERSION,
            "actual_version": officecli_version,
            "repair": f"python scripts/d6ppt.py bootstrap --runtime-dir {runtime_dir or default_runtime_dir()} --yes",
        },
        "libreoffice": {"status": "available" if soffice else "unavailable", "path": str(soffice) if soffice else None, "required": False, "reason": "Optional explicit compatibility target; never substitutes for PowerPoint."},
        "pdf_renderer": {"status": "pass" if pdftoppm else "fail", "path": pdftoppm, "required": True, "reason": "Rasterizes PowerPoint PDF exports for page review."},
        "fonts": {"status": "pass" if fonts else "warn", "directories": fonts},
        "vendor": {
            "status": "pass" if bom_path.is_file() else "fail",
            "bom": str(bom_path), "bom_sha256": sha256_file(bom_path) if bom_path.is_file() else None,
            "ppt_master_commit": PPT_MASTER_COMMIT,
        },
        "powerpoint": {
            "status": "pass" if powerpoint else "fail",
            "path": str(powerpoint) if powerpoint else None,
            "required": True,
        },
        "powerpoint_automation": {"status": "pass" if osascript else "fail", "path": osascript, "required": True},
    }
    required = [checks["python_modules"], checks["officecli"], checks["pdf_renderer"], checks["vendor"], checks["powerpoint"], checks["powerpoint_automation"]]
    return {
        "schema_version": "2.0", "status": "pass" if all(c["status"] == "pass" for c in required) else "fail",
        "runtime_lock_sha": RUNTIME_LOCK_SHA, "runtime_dir": str(runtime_dir or default_runtime_dir()), "checks": checks,
    }
