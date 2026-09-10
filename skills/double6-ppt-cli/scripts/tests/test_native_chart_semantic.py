import unittest
from pathlib import Path
import tempfile
from lxml import etree

from double6_ppt_cli.semantic import _find
from double6_ppt_cli.common import D6PPTError

NSMAP = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}


def _sp_tree():
    return etree.fromstring('''<p:spTree xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
      xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
  <p:sp>
    <p:nvSpPr><p:cNvPr id="1001" name="TextBox 1001"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
    <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>图表测试</a:t></a:r></a:p></p:txBody>
  </p:sp>
  <p:graphicFrame>
    <p:nvGraphicFramePr>
      <p:cNvPr id="2" name="chart-g"/>
      <p:cNvGraphicFramePr/>
      <p:nvPr/>
    </p:nvGraphicFramePr>
    <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"/></a:graphic>
  </p:graphicFrame>
</p:spTree>''')


class NativeChartNameFallbackTest(unittest.TestCase):
    def test_falls_back_to_selector_id_when_drawingml_id_missing(self):
        root = _sp_tree()
        obj = {
            "source_id": "slide-001-chart",
            "preferred_structure": "native_chart",
            "source_selector": {"file": "svg_output/01.svg", "id": "chart-g"},
            "match": {"drawingml_id": 1002},
        }
        found = _find(root, obj)
        cnv = found.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr")
        self.assertEqual(cnv.get("name"), "chart-g")

    def test_missing_native_chart_still_raises(self):
        root = _sp_tree()
        obj = {
            "source_id": "slide-001-chart",
            "preferred_structure": "native_chart",
            "source_selector": {"file": "svg_output/01.svg", "id": "missing"},
            "match": {"drawingml_id": 9999},
        }
        with self.assertRaises(D6PPTError):
            _find(root, obj)


if __name__ == "__main__":
    unittest.main()
