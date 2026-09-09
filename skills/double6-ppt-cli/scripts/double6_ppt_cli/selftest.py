from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import SCHEMA_VERSION, skill_root
from .doctor import doctor


def run_self_test(runtime_dir: Path | None = None, *, integration: bool = False) -> dict:
    tests = skill_root() / "scripts" / "tests"
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(tests), "-p", "test_*.py", "-v"],
        capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "PYTHONPATH": str(skill_root() / "scripts")},
    )
    result = {
        "schema_version": SCHEMA_VERSION, "status": "pass" if proc.returncode == 0 else "fail",
        "unit_tests": {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr},
        "doctor": doctor(runtime_dir), "integration_requested": integration,
    }
    if integration:
        result["integration"] = {
            "status": "not_run_by_self_test",
            "instruction": "Run the registered P0 and real-case receipts; self-test never invents source material or visual acceptance.",
        }
    return result
