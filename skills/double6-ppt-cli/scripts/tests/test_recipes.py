"""Layout recipes: `d6ppt recipe list|show|apply|deck` turn small JSON payloads into finished pages."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from double6_ppt_cli import recipes
from double6_ppt_cli.common import D6PPTError


def _run(tmp: Path, design: str = "investor-pitch") -> Path:
    from double6_ppt_cli.images import add_image
    from double6_ppt_cli.runs import init_run
    src = tmp / "b.md"
    src.write_text("# Deck\n", encoding="utf-8")
    run = tmp / "run"
    init_run("generate", src, run, design_profile=design, verify_tier="portable")
    for name in ("hero", "side", "close"):
        add_image(run, name, placeholder="gradient", colours=["#2B1C8F", "#FF5A3C"], size="640x360", treatments="cover=640x360")
    lock = run / "authoring" / "project" / "spec_lock.md"
    text = lock.read_text(encoding="utf-8").replace("[fill after doctor confirms availability]", "Noto Sans CJK SC")
    lock.write_text(text, encoding="utf-8")
    return run


PLAN = {
    "footer": "Lumen", "audience": "Series A investors", "lang": "en",
    "pages": [
        {"recipe": "cover_split", "image": "hero", "title": "Lumen", "subtitle": "Vision AI that catches defects before they ship"},
        {"recipe": "split_photo", "image": "side", "title": "Manual inspection misses 1 in 5 defects",
         "items": ["$63B annual cost of poor quality", "Inspectors fatigue after 20 minutes"], "stat": {"value": "1 in 5", "label": "defects slip"}},
        {"recipe": "big_number", "title": "Traction", "value": "$4.2M", "label": "ARR after 18 months",
         "supporting": [{"value": "38", "label": "customers"}, {"value": "142%", "label": "net retention"}]},
        {"recipe": "chart_annotated", "title": "ARR growth since launch", "annotation": "$4.2M", "callout": "7x",
         "chart": {"kind": "line", "categories": ["Q1", "Q2", "Q3"], "series": [{"name": "ARR", "values": [1, 2, 4]}]}},
        {"recipe": "timeline", "title": "Roadmap", "steps": ["Q1 Pilot", "Q2 Scale", "Q3 Expand"]},
        {"recipe": "quote", "quote": "Review the code, support the author.", "attribution": "Key takeaway"},
        {"recipe": "closing_photo", "image": "close", "title": "Raising $12M to reach 150 lines by 2028"},
    ],
}


class RecipeCatalogTests(unittest.TestCase):
    def test_catalog_covers_card_free_compositions(self):
        names = {r["name"] for r in recipes.list_recipes()}
        for n in ("cover_photo", "cover_split", "statement_photo", "quote", "big_number", "timeline", "split_photo",
                  "features", "kpi_photo", "chart_annotated", "table_highlight", "team", "closing_photo"):
            self.assertIn(n, names)
        card_free = [r for r in recipes.list_recipes() if not r["uses_cards"]]
        self.assertGreaterEqual(len(card_free), 12)
        layout_doc = (Path(__file__).resolve().parents[2] / "references" / "layout-recipes.md").read_text(encoding="utf-8")
        for n in names:
            self.assertIn(f"`{n}`", layout_doc, f"{n} undocumented in layout-recipes.md")

    def test_wrap_never_leaves_short_tail(self):
        for s in ("分散布局的小斑块总降温效果高于集中大斑块23%", "Inspectors fatigue after twenty minutes of work ok"):
            for width in range(200, 700, 37):
                lines = recipes.wrap(s, 28, width, True)
                if len(lines) > 1:
                    self.assertFalse(len(lines[-1]) <= 2, (s, width, lines))

    def test_type_ladder_is_large_enough(self):
        p = recipes.load_palette(None, "consulting")
        self.assertGreaterEqual(p["type"]["body"], 20)
        self.assertGreaterEqual(p["type"]["title"], 40)
        self.assertLessEqual(len(set(p["type"].values())), 7)


class RecipeApplyTests(unittest.TestCase):
    def test_deck_writes_pages_manifest_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp))
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(PLAN), encoding="utf-8")
            out = recipes.apply_deck(run, plan)
            svgs = sorted((run / "authoring" / "project" / "svg_output").glob("*.svg"))
            self.assertEqual(len(svgs), len(PLAN["pages"]))
            first = svgs[0].read_text(encoding="utf-8")
            self.assertIn('<image href="../images/hero.jpg"', first)
            self.assertIn("#2B1C8F", first)  # spec_lock palette, not a hard-coded colour
            man = json.loads((run / "authoring" / "semantic_manifest.json").read_text(encoding="utf-8"))
            ids = {(o["slide"], o["source_selector"]["id"]) for o in man["objects"]}
            for n, svg in enumerate(svgs, 1):
                for m in re.finditer(r'<(?:text|g) id="([^"]+)" data-pptx-shape-id="(\d+)"', svg.read_text(encoding="utf-8")):
                    self.assertIn((n, m.group(1)), ids)
            chart = [o for o in man["objects"] if o["role"] == "chart"]
            self.assertEqual(chart[0]["preferred_structure"], "native_chart")
            lock = (run / "authoring" / "project" / "spec_lock.md").read_text(encoding="utf-8")
            self.assertNotIn("[fill: names used", lock)
            self.assertIn("- P01: anchor", lock)
            self.assertIn("- P06: breathing", lock)
            self.assertEqual(out["warnings"], [])

    def test_single_page_apply_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp), "academic")
            res = recipes.apply(run, [{"recipe": "big_number", "value": "23%", "label": "更高的降温效果"}], [2], {"lang": "zh"})
            self.assertEqual(res["pages"][2]["rhythm"], "breathing")
            self.assertTrue((run / "authoring" / "project" / "svg_output" / "02.svg").exists())
            with self.assertRaises(D6PPTError) as cm:
                recipes.apply(run, [{"recipe": "nope"}], [1])
            self.assertEqual(cm.exception.code, "recipe_unknown")
            with self.assertRaises(D6PPTError) as cm:
                recipes.apply(run, [{"recipe": "cover_photo", "title": "x"}], [1])
            self.assertEqual(cm.exception.code, "recipe_field_missing")
            with self.assertRaises(D6PPTError) as cm:
                recipes.apply(run, [{"recipe": "cover_photo", "title": "x", "image": "missing"}], [1])
            self.assertEqual(cm.exception.code, "recipe_image_missing")

    def test_card_heavy_and_repeat_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp))
            data = {"title": "KPIs", "data": {"A": "1", "B": "2", "C": "3"}}
            res = recipes.apply(run, [dict(data, recipe="kpi_row"), dict(data, recipe="kpi_row")], [2, 3])
            self.assertTrue(any("consecutive" in w for w in res["warnings"]))
            self.assertTrue(any("card-based" in w for w in res["warnings"]))

    def test_compiled_deck_passes_deterministic_checks(self):
        from double6_ppt_cli.compiler import compile_run
        from double6_ppt_cli.native_markers import parse_spec_lock_palette
        from double6_ppt_cli.visual_quality import compute_visual_metrics
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(Path(tmp))
            lock = run / "authoring" / "project" / "spec_lock.md"
            text = lock.read_text(encoding="utf-8").replace("- status: draft", "- status: confirmed")
            for k, v in (("primary_language", "en"), ("audience", "investors"), ("objective", "raise"), ("core_message", "raise")):
                text = text.replace(f"- {k}: [fill]", f"- {k}: {v}")
            lock.write_text(text, encoding="utf-8")
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps(PLAN), encoding="utf-8")
            recipes.apply_deck(run, plan)
            ds = run / "authoring" / "project" / "design_spec.md"
            body = ds.read_text(encoding="utf-8").split("## IX. Content Outline")[0]
            body = body.replace("[fill after doctor confirms availability]", "Noto Sans CJK SC")
            body += "## IX. Content Outline\n\n" + "".join(
                f"### Slide {i:02d}\n- Audience move: page {i}\n- Relationships: none\n- Composition: recipe {p['recipe']}\n\n"
                for i, p in enumerate(PLAN["pages"], 1))
            ds.write_text(body, encoding="utf-8")
            try:
                result = compile_run(run)
            except D6PPTError as exc:  # pragma: no cover - surfaces authoring regressions with context
                self.fail(f"compile failed: {exc.code} {exc} {exc.details}")
            pptx = run / result["artifacts"]["current_pptx"] if "artifacts" in result else next(run.rglob("*.pptx"))
            metrics = compute_visual_metrics(pptx, [], palette=parse_spec_lock_palette(lock.read_text(encoding="utf-8")))
            codes = {f["code"] for f in metrics["findings"]}
            self.assertFalse(codes & {"too_many_font_sizes", "small_body_text", "cjk_latin_space", "office_default_chart_colors", "no_non_text_element"}, metrics["findings"])


if __name__ == "__main__":
    unittest.main()
