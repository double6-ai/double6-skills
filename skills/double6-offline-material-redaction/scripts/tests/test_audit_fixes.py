"""回归：0.7.0 离线实测里确认过的脱敏问题。材料全部是虚构示例。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import engine
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


if __name__ == "__main__":
    unittest.main()
