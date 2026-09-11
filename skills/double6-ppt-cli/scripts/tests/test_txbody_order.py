import unittest
from pathlib import Path
import tempfile
import zipfile
from lxml import etree

from double6_ppt_cli.template_workflow import _normalize_txbody_paragraph_order, AML


class TxBodyOrderTest(unittest.TestCase):
    def test_reorders_end_para_rpr_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "deck.pptx"
            bad_slide = f'''<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="{AML}">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="TextBox"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:txBody>
        <a:bodyPr/>
        <a:p>
          <a:endParaRPr sz="1800"/>
          <a:r><a:rPr lang="zh-CN"/><a:t>hello</a:t></a:r>
        </a:p>
      </p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
</p:sld>'''
            with zipfile.ZipFile(pptx, "w") as z:
                z.writestr("[Content_Types].xml", "<Types/>")
                z.writestr("ppt/slides/slide1.xml", bad_slide)
            changed = _normalize_txbody_paragraph_order(pptx)
            self.assertGreaterEqual(changed, 1)
            with zipfile.ZipFile(pptx) as z:
                root = etree.fromstring(z.read("ppt/slides/slide1.xml"))
            tags = [etree.QName(c).localname for c in root.xpath(".//a:p", namespaces={"a": AML})[0]]
            self.assertEqual(tags, ["r", "endParaRPr"])


if __name__ == "__main__":
    unittest.main()
