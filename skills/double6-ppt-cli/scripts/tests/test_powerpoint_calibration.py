"""Text-fit engine vs real PowerPoint 16 (Win11) measurements (fixtures/powerpoint_win11)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from double6_ppt_cli.pm6_template import textfit  # noqa: E402
from double6_ppt_cli.pm6_template.ooxml import NS, Package, q  # noqa: E402
from double6_ppt_cli.pm6_template.style import fit_context  # noqa: E402
from double6_ppt_cli.pm6_template.txbody import apply_fit  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "powerpoint_win11"


def _shape(pkg, slide, sid):
    part = f"ppt/slides/slide{slide}.xml"
    el = next(e for e in pkg.xml(part).iter(q("p", "sp")) if e.find(".//p:cNvPr", NS).get("id") == str(sid))
    return part, el


def _paragraphs(el):
    out = []
    for p in el.findall(".//a:p", NS):
        ppr = p.find(q("a", "pPr"))
        lvl = int(ppr.get("lvl", 0)) if ppr is not None and ppr.get("lvl") else 0
        out.append((lvl, "".join(t.text or "" for t in p.iter(q("a", "t")))))
    return out


class PowerPointCalibrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meas = json.loads((FIX / "measurements.json").read_text(encoding="utf-8"))["shapes"]
        cls.pkgs = {d: Package.open(FIX / f"{d}.filled.pptx") for d in ("en_qbr", "zh_factory")}

    def _rows(self):
        for m in self.meas:
            if not m.get("recomputed"):
                continue
            pkg = self.pkgs[m["deck"]]
            part, el = _shape(pkg, m["slide"], m["id"])
            ctx = fit_context(pkg, part, el)
            yield m, ctx, _paragraphs(el)

    def test_line_height_is_powerpoint_single_spacing(self):
        # one-line 44pt titles: PowerPoint bound 52.8pt regardless of script
        for m, ctx, paras in self._rows():
            if m["name"].startswith("Title") and m["bound_height_after"] == 52.8:
                raw = textfit.layout(ctx, paras, safety=False)
                self.assertAlmostEqual(raw["need_h_pt"] - 7.2, 52.8, delta=0.5, msg=m)

    def test_raw_estimate_tracks_powerpoint_and_safe_estimate_is_conservative(self):
        for m, ctx, paras in self._rows():
            raw = textfit.layout(ctx, paras, safety=False)
            safe = textfit.layout(ctx, paras)
            ppt = m["bound_height_after"] + m["margin_top"] + m["margin_bottom"]
            if raw["engine"] in ("heuristic", "partial"):
                continue  # widths need real fonts; line heights are covered above
            # body text: within -1%..+20% of PowerPoint (exp.2 predicted 340pt where PowerPoint needed 552pt)
            self.assertGreaterEqual(raw["need_h_pt"], ppt * 0.99, msg=(m["deck"], m["name"], raw["need_h_pt"], ppt))
            self.assertLessEqual(raw["need_h_pt"], ppt * 1.2 + 10, msg=(m["deck"], m["name"], raw["need_h_pt"], ppt))
            self.assertGreaterEqual(safe["need_h_pt"], ppt, msg=(m["deck"], m["name"], safe["need_h_pt"], ppt))

    def test_every_slot_powerpoint_overflowed_is_not_fits(self):
        for m, ctx, paras in self._rows():
            if m["overflow_pt"] > 2:
                text = "\n".join("\t" * lvl + t for lvl, t in paras)
                report = textfit.fit(ctx, text, levels=[lvl for lvl, _t in paras])
                self.assertIn(report["status"], {"shrunk", "overflow"}, msg=(m, report["status"]))

    def test_seven_bullet_body_is_a_rewrite_not_a_shrink(self):
        pkg = self.pkgs["en_qbr"]
        part, el = _shape(pkg, 2, 3)
        paras = _paragraphs(el)
        ctx = fit_context(pkg, part, el)
        report = textfit.fit(ctx, "\n".join(t for _l, t in paras), levels=[lvl for lvl, _t in paras])
        if report["engine"] not in ("heuristic", "partial"):
            self.assertEqual(report["status"], "overflow")

    def test_shrink_is_baked_not_fontscale(self):
        pkg = self.pkgs["zh_factory"]
        part, el = _shape(pkg, 2, 2)
        apply_fit(el, {"status": "shrunk", "font_scale": 0.725, "autofit_mode": "norm"})
        norm = el.find("./p:txBody/a:bodyPr/a:normAutofit", NS)
        self.assertIsNotNone(norm)
        self.assertIsNone(norm.get("fontScale"))
        self.assertIsNone(norm.get("lnSpcReduction"))

    def test_title_floor(self):
        pkg = self.pkgs["zh_factory"]
        part, el = _shape(pkg, 2, 2)
        ctx = fit_context(pkg, part, el)
        self.assertTrue(ctx["is_title"])
        report = textfit.fit(ctx, "很长的标题" * 30)
        self.assertEqual(report["status"], "overflow")
        self.assertGreaterEqual(report["font_scale"] * 44, textfit.MIN_PT["title"] - 0.01)


if __name__ == "__main__":
    unittest.main()
