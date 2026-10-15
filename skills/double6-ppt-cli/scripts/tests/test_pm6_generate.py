"""Regression tests for the PPT Master v6.7.0 generate-path adaptation (0.4.0-exp)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lxml import etree

from double6_ppt_cli import compiler, schemas, semantic
from double6_ppt_cli import template_workflow as tw
from double6_ppt_cli.common import D6PPTError
from double6_ppt_cli.native_markers import (
    TABLE_SCHEMA_V2,
    V48_TABLE_STYLE_DEFAULTS,
    normalize_native_markers,
    upgrade_table_payload,
)

SVG = "http://www.w3.org/2000/svg"


def _svg(inner: str) -> etree._Element:
    return etree.fromstring(f'<svg xmlns="{SVG}" viewBox="0 0 1280 720">{inner}</svg>'.encode())


def _payload(group: etree._Element) -> dict:
    meta = [c for c in group if etree.QName(c).localname == "metadata"]
    return json.loads(meta[0].text)


class TableUpgradeTest(unittest.TestCase):
    def test_legacy_table_gets_v2_schema_and_v48_defaults(self):
        payload = {"columns": ["A", "B"], "rows": [["1", "2"]]}
        actions = upgrade_table_payload(payload)
        self.assertEqual(payload["schema"], TABLE_SCHEMA_V2)
        for key, value in V48_TABLE_STYLE_DEFAULTS.items():
            self.assertEqual(payload["style"][key], value)
        self.assertEqual(payload["style"]["header_font_size"], 18)
        self.assertIn("table_schema_v2", actions)

    def test_author_style_wins_and_v2_payload_untouched(self):
        payload = {"columns": ["A"], "rows": [["1"]], "style": {"header_fill": "#000000"}}
        upgrade_table_payload(payload)
        self.assertEqual(payload["style"]["header_fill"], "#000000")
        v2 = {"schema": TABLE_SCHEMA_V2, "rows": [["1"]]}
        self.assertEqual(upgrade_table_payload(v2), [])
        self.assertNotIn("style", v2)

    def test_headerless_table_gets_no_header_fill(self):
        payload = {"rows": [["1", "2"]]}
        upgrade_table_payload(payload)
        self.assertNotIn("header_fill", payload["style"])


class NativeMarkerTest(unittest.TestCase):
    def test_json_first_with_bounds_injected(self):
        root = _svg('<g id="c" data-pptx-replace-with="chart" data-pptx-bounds="10 20 300 200">'
                    '<metadata>{"type":"bar","categories":["a"],"series":[{"name":"s","values":[1]}]}</metadata></g>')
        records = normalize_native_markers(root)
        group = root[0]
        self.assertEqual(group.get("data-pptx-native-authority"), "json")
        p = _payload(group)
        self.assertEqual([p["x"], p["y"], p["width"], p["height"]], [10, 20, 300, 200])
        self.assertEqual(records[0]["kind"], "chart")

    def test_json_first_without_bounds_fails_clearly(self):
        root = _svg('<g id="c" data-pptx-replace-with="chart"><metadata>{"type":"bar"}</metadata></g>')
        with self.assertRaises(D6PPTError) as ctx:
            normalize_native_markers(root)
        self.assertEqual(ctx.exception.code, "native_marker_invalid")

    def test_author_policy_and_existing_baseline_are_respected(self):
        root = _svg('<g id="c" data-pptx-replace-with="chart"><metadata>{"type":"bar"}</metadata></g>'
                    '<g id="d" data-pptx-replace-with="chart" data-pptx-fallback-sha256="ab">'
                    '<metadata>{"type":"bar"}</metadata></g>')
        self.assertEqual(normalize_native_markers(root, authority_policy="author"), [])
        self.assertEqual(normalize_native_markers(_svg(etree.tostring(root[1]).decode())), [])
        with self.assertRaises(D6PPTError):
            normalize_native_markers(root, authority_policy="bogus")

    def test_invalid_json_and_attribute_metadata(self):
        with self.assertRaises(D6PPTError):
            normalize_native_markers(_svg('<g data-pptx-replace-with="table"><metadata>{bad</metadata></g>'))
        root = _svg('<g id="t" data-pptx-replace-with="table" data-pptx-bounds="0 0 100 50" '
                    'data-pptx-json=\'{"rows":[["x"]]}\'/>')
        records = normalize_native_markers(root)
        group = root[0]
        self.assertNotIn("data-pptx-json", group.attrib)
        self.assertEqual(_payload(group)["schema"], TABLE_SCHEMA_V2)
        self.assertIn("metadata_attribute_to_child", records[0]["actions"])


class SemanticPictureTest(unittest.TestCase):
    def test_pic_is_candidate_and_resolvable(self):
        xml = ('<p:spTree xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
               'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
               '<p:pic><p:nvPicPr><p:cNvPr id="7" name="img"/></p:nvPicPr></p:pic></p:spTree>')
        root = etree.fromstring(xml.encode())
        cands = semantic._candidates(root)
        self.assertEqual(len(cands), 1)
        self.assertEqual(semantic._kind(cands[0]), "picture")
        self.assertEqual(semantic._path(cands[0], 2), ("/slide[2]/picture[@id=7]", 7, "picture"))
        self.assertIn("image", schemas.ROLES)


class CompilerDiagnosticsTest(unittest.TestCase):
    def test_quality_report_errors_flattened(self):
        report = {
            "project_issues": {"design_spec": [{"severity": "error", "message": "missing Relationships"},
                                               {"severity": "warning", "message": "w"}]},
            "files": [{"file": "06.svg", "errors": ["chart value is not numeric"]}],
        }
        self.assertEqual(compiler._quality_report_errors(report),
                         ["[design_spec] missing Relationships", "06.svg: chart value is not numeric"])

    def test_design_spec_placeholders_block_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "spec_lock.md").write_text("- status: confirmed\n", encoding="utf-8")
            (project / "design_spec.md").write_text("### Slide 01\n- Relationships: [本页内容单元之间的关系]\n", encoding="utf-8")
            sem = Path(tmp) / "semantic_manifest.json"
            sem.write_text("{}", encoding="utf-8")
            with self.assertRaises(D6PPTError) as ctx:
                compiler._check_authoring_scaffold(project, sem)
            self.assertEqual(ctx.exception.code, "authoring_scaffold_incomplete")
            self.assertIn("Relationships", ctx.exception.details["remaining_fields"][0])


class TemplateFillGateTest(unittest.TestCase):
    def test_template_fill_reports_not_migrated(self):
        # template-fill now runs on the PM6 roundtrip backend; only the legacy v4.8 backend is refused.
        with mock.patch.dict("os.environ", {"D6PPT_TEMPLATE_BACKEND": "v48"}):
            with self.assertRaises(D6PPTError) as ctx:
                tw._vendor_modules()
        self.assertEqual(ctx.exception.code, "template_fill_not_migrated")
        self.assertEqual(ctx.exception.details["ppt_master_version"], "6.7.0")


if __name__ == "__main__":
    unittest.main()
