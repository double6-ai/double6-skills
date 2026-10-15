"""The one-click PowerPoint verification script must keep working on every OS (PowerPoint stage mocked)."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "verify"

try:
    import pptx  # noqa: F401
    HAVE_PPTX = True
except Exception:  # pragma: no cover
    HAVE_PPTX = False


def _load():
    spec = importlib.util.spec_from_file_location("d6_verify", HERE / "verify_template_fill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_PPTX, "python-pptx needed")
class VerifyScriptTest(unittest.TestCase):
    def test_cases_apply_and_report_joins_powerpoint_measurements(self):
        mod = _load()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report"
            rows = mod.run_cases(out)
            self.assertEqual([r["status"] for r in rows], ["applied", "applied"], rows)
            first = rows[0]["text"][0]
            fake = {"status": "measured", "shapes": [{"deck": rows[0]["case"], "slide": first["plan_slide"], "id": first["drawingml_id"],
                                                      "overflow_pt": 5.0, "font_size_after": 18}]}
            cmp_ = mod.compare(out, rows, fake)
            self.assertEqual(cmp_["slots_measured"], 1)
            self.assertEqual(cmp_["slots_overflowing_in_powerpoint"], 1)
            report = {"created_at": "t", "host": {"platform": "x", "python": "3"}, "cases": rows, "powerpoint": fake, "comparison": cmp_}
            mod.write_markdown(out, report)
            self.assertIn("PowerPoint", (out / "REPORT.md").read_text(encoding="utf-8"))
            json.dumps(rows, ensure_ascii=False)

    def test_launchers_present(self):
        for name in ("verify_template_fill_windows.cmd", "verify_template_fill_macos.command", "powerpoint_measure.ps1", "powerpoint_measure.applescript"):
            self.assertTrue((HERE / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
