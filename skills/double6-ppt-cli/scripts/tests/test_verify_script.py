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
            self.assertTrue(all(r["as_expected"] for r in rows), [(r["case"], r["status"]) for r in rows])
            self.assertEqual({r["case"]: r["status"] for r in rows},
                             {"en_qbr": "blocked_by_check", "en_qbr_shrink": "applied", "zh_factory": "blocked_by_check", "zh_factory_shrink": "applied",
                              "en_overfull": "blocked_by_check"})
            zh = next(r for r in rows if r["case"] == "zh_factory_shrink")
            body = next(t for t in zh["text"] if t["drawingml_id"] == 3)
            # spilled body (PowerPoint geometry) runs into a card; PowerPoint wanted a smaller size on recompute
            fake = {"status": "measured", "shapes": [
                {"deck": "zh_factory_shrink", "slide": 2, "id": 3, "name": "Content Placeholder 2", "left": 36, "top": 126, "width": 648, "height": 356.4,
                 "margin_top": 3.6, "margin_bottom": 3.6, "bound_height_open": 432, "bound_height_after": 432, "bound_left_open": 63, "bound_width_open": 600,
                 "font_size_first_run": 28, "font_size_after": 25, "overflow_open_pt": 82.8, "overflow_pt": 82.8}],
                "frames": [{"deck": "zh_factory_shrink", "slide": 2, "id": 4, "name": "卡片1", "left": 55, "top": 393.7, "width": 259.8, "height": 70.9}]}
            cmp_ = mod.compare(out, rows, fake)
            row = next(r for r in cmp_["slots"] if r["case"] == "zh_factory_shrink" and r["drawingml_id"] == body["drawingml_id"])
            self.assertEqual(row["verdict"], "FAIL")
            self.assertEqual(set(row["failures"]), {"overflow", "powerpoint_recompute_changed_size", "overlap"})
            self.assertEqual(row["overlaps"], ["卡片1"])
            self.assertEqual(cmp_["status"], "failed")
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
