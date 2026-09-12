from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .common import (
    D6PPTError,
    OFFICECLI_PIN_VERSION,
    RUNTIME_LOCK_SHA,
    SCHEMA_VERSION,
    skill_root,
    utc_now,
    write_json,
)


def bootstrap(runtime_dir: Path, *, confirmed: bool = False) -> dict:
    if not confirmed:
        raise D6PPTError("bootstrap requires explicit --yes installation authorization", "installation_confirmation_required")
    runtime_dir = runtime_dir.expanduser().resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    venv = runtime_dir / "python"
    node_dir = runtime_dir / "node"
    log = []
    venv_python = venv / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if not venv_python.is_file():
        proc = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True, timeout=180)
        log.append({"command": "python -m venv", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise D6PPTError("Could not create Python runtime", "bootstrap_failed", log)
    requirements = skill_root() / "requirements-core.lock"
    proc = subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], capture_output=True, text=True, timeout=900)
    log.append({"command": "pip install", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    if proc.returncode:
        raise D6PPTError("Pinned Python dependency installation failed", "bootstrap_failed", log)
    npm = shutil.which("npm")
    if not npm:
        raise D6PPTError("npm is required to install the pinned OfficeCLI dependency", "npm_missing")
    node_dir.mkdir(parents=True, exist_ok=True)
    # Always install the pin only; never follow latest.
    proc = subprocess.run(
        [npm, "install", "--ignore-scripts=false", "--save-exact", f"@officecli/officecli@{OFFICECLI_PIN_VERSION}"],
        cwd=node_dir,
        capture_output=True,
        text=True,
        timeout=900,
    )
    log.append({"command": f"npm install @officecli/officecli@{OFFICECLI_PIN_VERSION}", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    if proc.returncode:
        raise D6PPTError("Pinned OfficeCLI installation failed", "bootstrap_failed", log)
    receipt = {
        "schema_version": SCHEMA_VERSION, "status": "pass", "created_at": utc_now(),
        "runtime_dir": str(runtime_dir), "runtime_lock_sha": RUNTIME_LOCK_SHA,
        "officecli_version": OFFICECLI_PIN_VERSION,
        "install_policy": "exact_pin_only",
        "commands": log,
    }
    write_json(runtime_dir / "bootstrap_receipt.json", receipt)
    return receipt
