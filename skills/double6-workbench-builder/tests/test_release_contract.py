from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "double6.py"


class ReleaseContractTests(unittest.TestCase):
    def test_cli_version_matches_manifest(self) -> None:
        manifest = json.loads((SKILL_ROOT / "manifest.json").read_text(encoding="utf-8"))
        result = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(manifest["version"]), result.stdout)

    def test_route_catalog_is_available_without_writing_a_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "start",
                    "--run",
                    str(run_dir),
                    "--request",
                    "做一个个人任务面板",
                ],
                cwd=SKILL_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "route_selection_required")
            self.assertEqual(len(payload["route_options"]), 16)
            self.assertFalse(run_dir.exists())


if __name__ == "__main__":
    unittest.main()
