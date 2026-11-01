"""真实办公软件导出写法与默认批注路径的回归。全部信息均为虚构。"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).parents[1]))
import cli
import engine
import formats
import output_policy as policy
import pdf_preserve as pdf


SECRET = "张伟明"
KEEP = "保留这句业务内容"


def _office_plan(kind, terms, keep):
    return {"version": 1, "kind": kind, "reviewed": True, "terms": terms, "keep": keep, "acknowledge_loss": True}


def _xlsx(cells):
    book = Workbook()
    sheet = book.active
    for coordinate, (value, number_format) in cells.items():
        sheet[coordinate] = value
        sheet[coordinate].number_format = number_format
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class CurrencyFormatTests(unittest.TestCase):
    """LibreOffice 常把货币写成 \\¥#,##0.00，Excel 写 [$¥-804]#,##0.00。显示读法都是符号加数字。"""

    CASES = [
        ("\\¥#,##0.00", "¥123,456.78"),
        ("[$¥-804]#,##0.00", "¥123,456.78"),
        ("\\$#,##0.00", "$123,456.78"),
        ("[$US$-409]#,##0.00", "US$123,456.78"),
        ("[$€-407]#,##0.00", "€123,456.78"),
    ]

    def test_escaped_and_locale_currency_preserved(self):
        for number_format, shown in self.CASES:
            with self.subTest(fmt=number_format):
                raw = _xlsx({"A1": (SECRET, "General"), "B1": (123456.78, number_format), "C1": (KEEP, "General")})
                plan = _office_plan("excel", [SECRET], [KEEP, shown])
                out = formats.export(raw, "excel", plan)
                text = formats.inspect(out, "excel")["preview"]
                self.assertNotIn(SECRET, text)
                self.assertIn(shown, text)

    def test_display_matches_office_reading(self):
        self.assertEqual(formats.cell_display.display(123456.78, "\\¥#,##0.00"), "¥123,456.78")
        self.assertEqual(formats.cell_display.display(123456.78, "[$¥-804]#,##0.00"), "¥123,456.78")
        self.assertEqual(formats.cell_display.display(123456.78, "[$US$-409]#,##0.00"), "US$123,456.78")

    def test_unknown_sections_still_stop(self):
        for number_format in ["[$¥-804]#,##0.00;[$¥-804]-#,##0.00", "\\¥#,##0.00;;;", "0.00E+00", "[$¥-804]* #,##0.00"]:
            with self.subTest(fmt=number_format):
                with self.assertRaises(engine.Rejected):
                    formats.cell_display.validate_numeric_format(number_format)


class HighlightOverSelectionTests(unittest.TestCase):
    """高亮盖住要框选的词是常见办公场景：正文删除，高亮整体保留，不按部分矢量拒绝。"""

    def _pdf_with_highlight_on_secret(self):
        fitz = pdf.backend()
        doc = fitz.open()
        page = doc.new_page(width=300, height=200)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=12)
        page.insert_text((20, 100), SECRET, fontname="china-s", fontsize=12)
        page.add_highlight_annot(page.search_for(SECRET)[0]).update()
        found = page.search_for(SECRET)[0]
        raw = doc.tobytes()
        doc.close()
        return raw, found

    def test_highlight_over_selected_text_is_kept_and_text_removed(self):
        raw, found = self._pdf_with_highlight_on_secret()
        box = [(found.x0 - 1) * 2, (found.y0 - 1) * 2, (found.x1 + 1) * 2, (found.y1 + 1) * 2]
        plan = {"reviewed_pages": [1], "pages": [{"page": 1, "rectangles": [box]}], "keep": [KEEP]}
        out, report, ext = policy.export(raw, ".pdf", plan)
        self.assertTrue(all(report["checks"].values()))
        self.assertIn("默认保留批注", report["scope"])
        with pdf.backend().open(stream=out, filetype="pdf") as opened:
            self.assertNotIn(SECRET, opened[0].get_text())
            self.assertIn(KEEP, opened[0].get_text())
            self.assertTrue(any(a.type[1] == "Highlight" for a in (opened[0].annots() or [])))


class ImagePlanTests(unittest.TestCase):
    def test_image_plan_rejects_text_keep(self):
        image = Image.new("RGB", (40, 40), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        plan = {"version": 1, "kind": "image", "reviewed": True, "keep": [KEEP], "rectangles": [[0, 0, 10, 10]]}
        with tempfile.TemporaryDirectory(prefix="redaction-plan-") as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(cli.Failure) as caught:
                cli.load_plan(path, "image")
        self.assertIn("keep", str(caught.exception))


class TermScannerTests(unittest.TestCase):
    CASES = [
        "电话13800000000尾号",
        "张伟明 整理120条活动反馈",
        "１３８００００００００",
        "编号 10086 编号100861234",
        "138\u200b00000000",
        "138-0000-0000",
    ]

    def test_scanner_matches_single_query(self):
        terms = ["13800000000", "张伟明", "10086"]
        for text in self.CASES:
            scanner = engine.TermScanner(text)
            for term in terms:
                self.assertEqual(scanner.remains(term), engine.term_remains(text, term), (text, term))

    def test_alternate_matches_helper(self):
        for text in self.CASES:
            scanner = engine.TermScanner(text)
            self.assertEqual(
                scanner.alternate("13800000000"),
                engine.alternate_spelling_remains(text, "13800000000"),
            )


if __name__ == "__main__":
    unittest.main()
