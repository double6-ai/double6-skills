import json
import tempfile
import unittest
from pathlib import Path

from lxml import etree

from double6_ppt_cli import native_markers, source_adapter, template_workflow
from double6_ppt_cli.pm6_template import textfit

LOCK = """## colors
- bg: #FFFFFF
- surface: #F3F5F7
- primary: #1F3A5F
- accent: #3C7A78
- text: #1E2733
- line: #D9DDE2
- chart_series: #3C7A78, #1F3A5F, #8493A7

## typography
- body: 18
"""
SVG = "http://www.w3.org/2000/svg"


class PaletteTests(unittest.TestCase):
    def test_parse_palette(self):
        p = native_markers.parse_spec_lock_palette(LOCK)
        self.assertEqual(p["primary"], "#1F3A5F")
        self.assertEqual(p["chart_series"], ["#3C7A78", "#1F3A5F", "#8493A7"])

    def test_chart_and_table_get_deck_palette(self):
        p = native_markers.parse_spec_lock_palette(LOCK)
        root = etree.fromstring(
            f'<svg xmlns="{SVG}"><g id="c" data-pptx-bounds="0 0 100 100" data-pptx-replace-with="chart"><metadata>'
            '{"type":"column","categories":["a"],"series":[{"name":"s","values":[1]}]}</metadata></g>'
            '<g id="t" data-pptx-bounds="0 0 100 100" data-pptx-replace-with="table"><metadata>'
            '{"columns":["a"],"rows":[["1"]]}</metadata></g></svg>')
        native_markers.normalize_native_markers(root, palette=p)
        metas = [json.loads(m.text) for m in root.iter(f"{{{SVG}}}metadata")]
        self.assertEqual(metas[0]["style"]["colors"][0], "#3C7A78")
        for color in native_markers.OFFICE_DEFAULT_SERIES:
            self.assertNotIn(color, metas[0]["style"]["colors"])
        self.assertEqual(metas[1]["style"]["header_fill"], "#1F3A5F")

    def test_author_colors_win(self):
        p = native_markers.parse_spec_lock_palette(LOCK)
        payload = {"type": "line", "style": {"colors": ["#123456"]}}
        native_markers.apply_chart_palette(payload, p)
        self.assertEqual(payload["style"]["colors"], ["#123456"])


class AdapterTests(unittest.TestCase):
    def test_single_line_tspan_with_dy_zero_is_unwrapped(self):
        root = etree.fromstring(f'<svg xmlns="{SVG}"><text data-pptx-shape-id="5" x="1" y="2"><tspan x="1" dy="0">a</tspan></text></svg>')
        self.assertEqual(source_adapter._unwrap_single_line_tspans(root), ["5"])

    def test_icons_are_staged_from_vendored_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"; build = Path(tmp) / "build"
            (build / "svg_output").mkdir(parents=True); src.mkdir()
            (build / "svg_output" / "01.svg").write_text('<svg><use data-icon="tabler-outline/rocket" x="0" y="0" width="10" height="10"/></svg>', encoding="utf-8")
            self.assertEqual(source_adapter._stage_icons(src, build), ["tabler-outline/rocket"])
            self.assertTrue((build / "icons" / "tabler-outline" / "rocket.svg").is_file())
            (build / "svg_output" / "01.svg").write_text('<svg><use data-icon="tabler-outline/no-such-icon-x"/></svg>', encoding="utf-8")
            with self.assertRaises(Exception):
                source_adapter._stage_icons(src, build)


class TemplateTests(unittest.TestCase):
    def test_image_only_detection(self):
        full = {"x_emu": 0, "y_emu": 0, "width_emu": 12192000, "height_emu": 6858000}
        profile = {"canvas": {"width_emu": 12192000, "height_emu": 6858000}, "objects": [
            {"source_template_slide": 1, "object_type": "picture", "geometry": full, "normalized_text": ""},
            {"source_template_slide": 2, "object_type": "picture", "geometry": full, "normalized_text": ""},
            {"source_template_slide": 2, "object_type": "shape", "geometry": full, "normalized_text": "Title"},
        ]}
        r = template_workflow.detect_image_only_slides(profile)
        self.assertEqual(r["image_only_slides"], [1])
        self.assertFalse(r["all_image_only"])

    def test_letter_spacing_counts_in_width(self):
        props = {"sz": 12.0, "latin": "", "ea": "", "bold": False}
        plain = textfit.Metrics(props).width("ABCDEFGH")
        tracked = textfit.Metrics({**props, "spc": 2.25}).width("ABCDEFGH")
        self.assertAlmostEqual(tracked - plain, 18.0, places=3)


if __name__ == "__main__":
    unittest.main()
