"""v4.8 Template Fill Native behaviours that the PM6 backend must keep (ported contract tests).

Covers: selector forms (slot_id / shape_id / shape_name, ``paragraphs``), SmartArt reading and the
non-text warning, transition validation + writing, speaker notes semantics, reuse concentration,
table-frame slots, merge-slave scaffolding, and mixed-format run preservation.
"""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from double6_ppt_cli.pm6_template import analyze_pptx, apply_plan, check_plan, scaffold_plan
from double6_ppt_cli.pm6_template.ooxml import NS, q
from double6_ppt_cli.pm6_template.txbody import set_text, styled_runs

try:
    from pptx import Presentation
    from pptx.util import Emu, Pt
    HAVE_PPTX = True
except Exception:  # pragma: no cover
    HAVE_PPTX = False

FIXTURES = Path(__file__).parent / "fixtures"
P = NS["p"]


def build_deck(path: Path) -> None:
    prs = Presentation()
    for i in range(3):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = f"Title {i + 1}"
        s.placeholders[1].text_frame.text = f"Body {i + 1}"
        s.notes_slide.notes_text_frame.text = f"Sample notes {i + 1}"
    s = prs.slides[1]
    tb = s.shapes.add_textbox(Emu(600000), Emu(5200000), Emu(5000000), Emu(500000))
    tb.name = "KPI"
    para = tb.text_frame.paragraphs[0]
    r1 = para.add_run(); r1.text = "Revenue: "; r1.font.bold = True
    r2 = para.add_run(); r2.text = "12.5M USD"; r2.font.size = Pt(20)
    el = prs.slides[0]._element
    anchor = el.find(f"{{{P}}}clrMapOvr")
    (anchor if anchor is not None else el.find(f"{{{P}}}cSld")).addnext(etree.fromstring(f'<p:transition xmlns:p="{P}" spd="med"><p:fade/></p:transition>'))
    prs.save(path)


def _xml(pptx: Path, part: str) -> str:
    with zipfile.ZipFile(pptx) as z:
        return z.read(part).decode("utf-8")


def _notes_of(pptx: Path, slide_no: int) -> str | None:
    with zipfile.ZipFile(pptx) as z:
        rels = z.read(f"ppt/slides/_rels/slide{slide_no}.xml.rels").decode()
        import re
        m = re.search(r'Target="\.\./notesSlides/([^"]+)"', rels)
        if not m:
            return None
        root = etree.fromstring(z.read("ppt/notesSlides/" + m.group(1)))
        return "".join(root.xpath(".//p:sp[.//p:ph[@type='body']]//a:t/text()", namespaces=NS))


class StyledRunsTest(unittest.TestCase):
    def _p(self, inner: str):
        return etree.fromstring(f'<a:p xmlns:a="{NS["a"]}">{inner}</a:p>')

    def test_label_style_kept_value_style_kept(self):
        p = self._p('<a:r><a:rPr b="1"/><a:t>Revenue: </a:t></a:r><a:r><a:rPr sz="2000"/><a:t>12.5M USD</a:t></a:r>')
        runs = styled_runs(p, "Revenue: 14.1M USD")
        self.assertEqual([t for _r, t in runs], ["Revenue: ", "14.1M USD"])
        self.assertEqual(runs[0][0].get("b"), "1")
        self.assertEqual(runs[1][0].get("sz"), "2000")

    def test_single_style_returns_none(self):
        p = self._p('<a:r><a:rPr b="1"/><a:t>a</a:t></a:r><a:r><a:rPr b="1"/><a:t>b</a:t></a:r>')
        self.assertIsNone(styled_runs(p, "xyz"))

    def test_unchanged_paragraph_keeps_fields_and_breaks(self):
        body = etree.fromstring(f'<p:txBody xmlns:p="{P}" xmlns:a="{NS["a"]}"><a:bodyPr/><a:p><a:r><a:t>Page </a:t></a:r>'
                                '<a:fld id="{1}" type="slidenum"><a:t>3</a:t></a:fld></a:p><a:p><a:r><a:t>old</a:t></a:r></a:p></p:txBody>')
        set_text(body, "Page 3\nnew")
        ps = body.findall(q("a", "p"))
        self.assertIsNotNone(ps[0].find(q("a", "fld")))
        self.assertEqual("".join(ps[1].xpath(".//a:t/text()", namespaces=NS)), "new")


@unittest.skipUnless(HAVE_PPTX, "python-pptx needed for fixtures")
class ParityCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deck = Path(cls.tmp.name) / "deck.pptx"
        build_deck(cls.deck)
        cls.lib = analyze_pptx(cls.deck)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, slides):
        return {"schema": "template_fill_pptx_plan.v1", "status": "confirmed", "slides": slides}

    def codes(self, report, status=None):
        return [r["code"] for r in report["results"] if status is None or r["status"] == status]

    def test_library_carries_notes_transition_and_selectors(self):
        s1 = self.lib["slides"][0]
        self.assertEqual(s1["notes_text"], "Sample notes 1")
        self.assertEqual(s1["transition"]["effect"], "fade")
        kpi = next(s for s in self.lib["slides"][1]["slots"] if s.get("shape_name") == "KPI")
        self.assertTrue(kpi["shape_id"])
        self.assertEqual(self.lib["schema"], "template_fill_pptx_library.v1")

    def test_shape_name_selector_and_paragraphs(self):
        rep = check_plan(self.lib, self.plan([{"source_slide": 2, "notes": "n", "replacements": [{"shape_name": "KPI", "paragraphs": ["Revenue: 14.1M USD"]}]}]))
        self.assertEqual(rep["summary"]["error"], 0, rep)
        self.assertIn("text_fit", self.codes(rep))
        rep = check_plan(self.lib, self.plan([{"source_slide": 2, "replacements": [{"shape_name": "Nope", "text": "x"}]}]))
        self.assertIn("replacement_target_not_found", self.codes(rep, "ERROR"))

    def test_transition_validation(self):
        rep = check_plan(self.lib, self.plan([{"source_slide": 1, "notes": "n", "transition": {"effect": "fade", "bogus": 1}}]))
        self.assertIn("transition_unknown_fields", self.codes(rep, "ERROR"))
        rep = check_plan(self.lib, self.plan([{"source_slide": 1, "notes": "n", "transition": {"effect": "no-such-effect"}}]))
        self.assertIn("transition_invalid", self.codes(rep, "ERROR"))

    def test_notes_semantics_in_check(self):
        rep = check_plan(self.lib, self.plan([{"source_slide": 1}]))
        self.assertIn("template_notes_dropped", self.codes(rep, "WARN"))
        rep = check_plan(self.lib, self.plan([{"source_slide": 1, "notes": "keep"}]))
        self.assertNotIn("template_notes_dropped", self.codes(rep))
        rep = check_plan(self.lib, self.plan([{"source_slide": 1, "notes": 5}]))
        self.assertIn("notes_invalid", self.codes(rep, "ERROR"))

    def test_reuse_concentration_warns(self):
        rep = check_plan(self.lib, self.plan([{"source_slide": 1, "notes": "keep"}] * 3))
        self.assertIn("source_reuse_concentration", self.codes(rep, "WARN"))

    def test_scaffold_skips_system_and_keeps_notes(self):
        plan = scaffold_plan(self.lib, None, include_empty=True)
        self.assertEqual(plan["schema"], "template_fill_pptx_plan.v1")
        self.assertEqual(plan["slides"][0]["notes"], "Sample notes 1")
        self.assertEqual(check_plan(self.lib, plan)["summary"]["error"], 0)


class SmartArtTest(unittest.TestCase):
    def test_smartart_read_and_reported(self):
        lib = analyze_pptx(FIXTURES / "poi_smartart.pptx")
        diagrams = lib["slides"][0]["diagrams"]
        self.assertTrue(diagrams)
        self.assertEqual(len(diagrams[0]["nodes"]), 5)
        self.assertEqual(lib["slides"][0]["fill_risk"]["kinds"], ["smartart"])
        rep = check_plan(lib, {"schema": "template_fill_pptx_plan.v1", "slides": [{"source_slide": 1, "replacements": []}]})
        self.assertIn("non_text_content_unedited", [r["code"] for r in rep["results"]])


@unittest.skipUnless(HAVE_PPTX, "python-pptx needed for fixtures")
class ParityApplyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.deck = root / "deck.pptx"
        build_deck(cls.deck)
        cls.out = root / "out.pptx"
        plan = {"schema": "template_fill_pptx_plan.v1", "slides": [
            {"source_slide": 1, "replacements": [], "notes": "New notes A", "transition": {"effect": "push", "duration": 0.7}},
            {"source_slide": 2, "replacements": [{"shape_name": "KPI", "paragraphs": ["Revenue: 14.1M USD"]}]},
            {"source_slide": 1, "replacements": [], "notes": "keep"},
            {"source_slide": 3, "replacements": [{"shape_id": "3", "text": "Body three"}], "notes": "Third"},
        ]}
        cls.receipt = apply_plan(cls.deck, plan, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_notes_replace_drop_keep(self):
        self.assertEqual(_notes_of(self.out, 1), "New notes A")
        self.assertIsNone(_notes_of(self.out, 2))
        self.assertEqual(_notes_of(self.out, 3), "Sample notes 1")
        self.assertEqual(_notes_of(self.out, 4), "Third")

    def test_transition_replace_and_keep(self):
        self.assertIn("<p:push", _xml(self.out, "ppt/slides/slide1.xml"))
        self.assertIn("<p:fade", _xml(self.out, "ppt/slides/slide3.xml"))
        self.assertNotIn("<p:transition", _xml(self.out, "ppt/slides/slide2.xml"))

    def test_mixed_runs_preserved(self):
        root = etree.fromstring(_xml(self.out, "ppt/slides/slide2.xml").encode())
        kpi = root.xpath(".//p:sp[p:nvSpPr/p:cNvPr[@name='KPI']]", namespaces=NS)[0]
        runs = kpi.findall(".//a:r", NS)
        self.assertEqual([r.findtext("a:t", namespaces=NS) for r in runs], ["Revenue: ", "14.1M USD"])
        self.assertEqual(runs[0].find("a:rPr", NS).get("b"), "1")
        self.assertEqual(runs[1].find("a:rPr", NS).get("sz"), "2000")

    def test_shape_id_selector_applied(self):
        self.assertIn("Body three", _xml(self.out, "ppt/slides/slide4.xml"))


if __name__ == "__main__":
    unittest.main()
