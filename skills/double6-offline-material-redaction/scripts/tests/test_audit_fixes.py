"""回归：0.7.0 离线实测里确认过的脱敏问题。材料全部是虚构示例。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import engine
import formats
import output_policy as policy
import pdf_preserve as pdf


PHONE = "13800000000"
KEEP = "整理120条活动反馈"
NOTE = "PDF批注甲乙丙13700000016"


def _page():
    fitz = pdf.backend()
    doc = fitz.open()
    page = doc.new_page(width=400, height=280)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 140), PHONE, fontname="helv", fontsize=14)
    page.add_text_annot(fitz.Point(300, 200), NOTE)
    raw = doc.tobytes()
    found = page.search_for(PHONE)[0]
    doc.close()
    return raw, found


def _plan(box):
    return {
        "version": 1,
        "kind": "pdf",
        "reviewed": True,
        "reviewed_pages": [1],
        "keep": [KEEP],
        "pages": [{"page": 1, "rectangles": [box]}],
    }


def _pixel_box(rect):
    return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]


class PdfAnnotationTests(unittest.TestCase):
    def test_text_annotation_is_removed_and_text_layer_stays(self):
        raw, found = _page()
        out, report, ext = policy.export(raw, ".pdf", _plan(_pixel_box(found)))
        self.assertEqual(ext, ".pdf")
        self.assertTrue(report["checks"]["pdf_not_rasterized"])
        self.assertTrue(report["checks"]["outside_page_pixels_preserved"])
        self.assertTrue(report["checks"]["selected_text_removed"])
        self.assertTrue(report["checks"]["keep_phrases_preserved"])
        with pdf.backend().open(stream=out, filetype="pdf") as doc:
            text = doc[0].get_text()
            self.assertIn(KEEP, text)
            self.assertNotIn(PHONE, text)
            self.assertIsNone(doc[0].first_annot)
            self.assertNotIn(NOTE.encode(), out)
            self.assertGreater(len(text.strip()), 0)

    def test_annotation_does_not_excuse_a_cut_glyph(self):
        raw, found = _page()
        # 只盖住电话左半边。框外剩下的字形被删改时必须仍然失败。
        partial = [(found.x0 - 1) * 2, (found.y0 - 1) * 2, (found.x0 + found.width / 2) * 2, (found.y1 + 1) * 2]
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", _plan(partial))
        self.assertIn("框外", str(caught.exception))


class TableKeepTests(unittest.TestCase):
    def _plan(self, kind, terms, keep):
        return {"version": 1, "kind": kind, "reviewed": True, "terms": terms, "keep": keep, "acknowledge_loss": True}

    def test_plain_negative_stays_and_real_formulas_are_quoted(self):
        raw = "姓名,金额\n张三,-120\n公式,=1+1\n危险,-2+3\n命令,@SUM(A1)\n加号,+1+1\n".encode()
        for kind in ("csv", "tsv"):
            text = raw.decode().replace(",", "\t") if kind == "tsv" else raw.decode()
            out = formats.export(text.encode(), kind, self._plan(kind, ["张三"], ["-120"]))
            rows = formats.csv_rows(out, kind)
            self.assertEqual(rows[1][1], "-120")
            self.assertEqual(rows[2][1], "'=1+1")
            self.assertEqual(rows[3][1], "'-2+3")
            self.assertEqual(rows[4][1], "'@SUM(A1)")
            self.assertEqual(rows[5][1], "'+1+1")
            self.assertNotIn("张三", str(rows))

    def test_keep_sees_quoted_formula_as_changed(self):
        raw = "姓名,公式\n张三,=1+1\n".encode()
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(raw, "csv", self._plan("csv", ["张三"], ["=1+1"]))
        self.assertIn("完整单元格", str(caught.exception))
        self.assertIn("=1+1", str(caught.exception))


class WrappedTermTests(unittest.TestCase):
    TEXT = "1380000\n0000\n编号0000\n整理120条活动反馈\n"

    def test_split_short_terms_are_rejected(self):
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["1380000", "0000"], "keep": ["整理120条活动反馈"]}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(self.TEXT.encode(), "text", plan)
        self.assertIn("编号0000", str(caught.exception))
        self.assertIn("不要按换行拆开", str(caught.exception))

    def test_newline_inside_one_term_does_not_change_other_numbers(self):
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["1380000\n0000"], "keep": ["整理120条活动反馈", "编号0000"]}
        out = formats.export(self.TEXT.encode(), "text", plan).decode()
        self.assertIn("编号0000", out)
        self.assertIn("整理120条活动反馈", out)
        self.assertNotIn("1380000\n0000", out)

    def test_web_client_keeps_a_wrapped_selection_as_one_term(self):
        script = Path(__file__).parents[1].joinpath("web", "app.js").read_text(encoding="utf-8")
        self.assertIn("function decodeTerms", script)
        self.assertIn("terms:decodeTerms($('terms').value)", script)
        self.assertNotIn("terms:$('terms').value.split('\\n')", script)
        # 与网页 encode/decode 同一规则：跨行选区写成一行里的 \\n，读回仍是一项。
        shown = "1380000\\n0000\n整理120条活动反馈"
        items = []
        for line in shown.split("\n"):
            out = []
            chars = list(line)
            i = 0
            while i < len(chars):
                if chars[i] == "\\" and i + 1 < len(chars) and chars[i + 1] == "n":
                    out.append("\n")
                    i += 2
                elif chars[i] == "\\" and i + 1 < len(chars) and chars[i + 1] == "\\":
                    out.append("\\")
                    i += 2
                else:
                    out.append(chars[i])
                    i += 1
            text = "".join(out).strip()
            if text:
                items.append(text)
        self.assertEqual(items, ["1380000\n0000", "整理120条活动反馈"])


class MarkerCollisionTests(unittest.TestCase):
    def test_marker_word_uses_a_marker_that_does_not_contain_the_term(self):
        raw = "请已隐去此段 整理120条活动反馈\n".encode()
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["已隐去"], "keep": ["整理120条活动反馈"]}
        out = formats.export(raw, "text", plan).decode()
        self.assertNotIn("已隐去", out)
        self.assertIn("〔已处理A〕", out)
        self.assertIn("整理120条活动反馈", out)

    def test_both_markers_collide_explains_why(self):
        raw = "已隐去并且已处理\n".encode()
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["已隐去", "已处理"], "keep": []}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(raw, "text", plan)
        message = str(caught.exception)
        self.assertIn("替换标记", message)
        self.assertIn("已隐去", message)
        self.assertNotIn("导出复检失败", message)


if __name__ == "__main__":
    unittest.main()
