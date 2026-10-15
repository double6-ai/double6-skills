import json
import tempfile
import unittest
from pathlib import Path

from double6_ppt_cli import design_presets
from double6_ppt_cli.runs import init_run

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "ppt-master-core" / "skills" / "ppt-master"



class DesignPresetTests(unittest.TestCase):
    def test_presets_map_to_vendored_styles(self):
        self.assertGreaterEqual(len(design_presets.PRESETS), 6)
        for name in design_presets.PRESETS:
            p = design_presets.resolve(name)
            self.assertTrue((VENDOR / "templates" / "styles" / p["style_id"] / "templates" / "design_spec.md").is_file(), name)
            self.assertTrue((VENDOR / "references" / "visual-styles" / f"{p['visual_style']}.md").is_file(), name)
            self.assertLessEqual(len(set(p["type"].values())), 7)
            self.assertGreaterEqual(p["type"]["body"], 20)
            self.assertGreaterEqual(p["type"]["title"], 40)
            self.assertNotIn("#4472C4", p["chart_series"])
        self.assertEqual(design_presets.resolve("business")["name"], "consulting")

    def test_init_writes_palette_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "s.md"; src.write_text("# x", encoding="utf-8")
            run = Path(tmp) / "run"
            init_run("generate", src, run, verify_tier="portable", design_profile="investor-pitch")
            lock = (run / "authoring" / "project" / "spec_lock.md").read_text(encoding="utf-8")
            self.assertIn("- primary: #2B1C8F", lock)
            self.assertIn("- chart_series: #FF5A3C", lock)
            self.assertIn("- library: tabler-outline", lock)
            self.assertNotIn("{{", lock)
            spec = (run / "authoring" / "project" / "design_spec.md").read_text(encoding="utf-8")
            self.assertIn("Composition", spec)
            self.assertNotIn("{{", spec)

    def test_design_subset_vendored(self):
        bom = json.loads((ROOT / "vendor" / "ppt-master-core" / "BOM.json").read_text(encoding="utf-8"))
        design = [e for e in bom["files"] if e["category"] == "design_subset"]
        self.assertTrue(any(e["path"].endswith("references/executor-base.md") for e in design))
        self.assertTrue((VENDOR / "templates" / "layouts" / "presentation_core").is_dir())
        self.assertTrue((VENDOR / "templates" / "layouts" / "report_core").is_dir())
        self.assertTrue((ROOT / "references" / "visual-design.md").is_file())


if __name__ == "__main__":
    unittest.main()
