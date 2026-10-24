"""回归：0.7.0 离线实测里确认过的脱敏问题。材料全部是虚构示例。"""
import io
import sys
import unittest
from pathlib import Path

from docx import Document
from openpyxl import Workbook

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


def _pdf_plan(box):
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
        out, report, ext = policy.export(raw, ".pdf", _pdf_plan(_pixel_box(found)))
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
            policy.export(raw, ".pdf", _pdf_plan(partial))
        self.assertIn("框外", str(caught.exception))


class TableKeepTests(unittest.TestCase):
    def _office_plan(self, kind, terms, keep):
        return {"version": 1, "kind": kind, "reviewed": True, "terms": terms, "keep": keep, "acknowledge_loss": True}

    def test_plain_negative_stays_and_real_formulas_are_quoted(self):
        raw = "姓名,金额\n张三,-120\n公式,=1+1\n危险,-2+3\n命令,@SUM(A1)\n加号,+1+1\n".encode()
        for kind in ("csv", "tsv"):
            text = raw.decode().replace(",", "\t") if kind == "tsv" else raw.decode()
            out = formats.export(text.encode(), kind, self._office_plan(kind, ["张三"], ["-120"]))
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
            formats.export(raw, "csv", self._office_plan("csv", ["张三"], ["=1+1"]))
        self.assertIn("完整单元格", str(caught.exception))
        self.assertIn("=1+1", str(caught.exception))


class WrappedTermTests(unittest.TestCase):
    TEXT = "1380000\n0000\n编号0000\n整理120条活动反馈\n"

    def test_split_short_terms_are_rejected(self):
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["1380000", "0000"], "keep": ["整理120条活动反馈"]}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(self.TEXT.encode(), "text", plan)
        message = str(caught.exception)
        self.assertNotIn("编号0000", message)
        self.assertNotIn("13800000000", message)
        self.assertIn("完整", message)

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


class SuggestionAndRepeatTests(unittest.TestCase):
    SAMPLE = "\n".join([
        "联系人张三 Zhang San",
        "半角电话13800000000",
        "空格电话138 0000 0000",
        "连字符电话138-0000-0000",
        "全角电话１３８００００００００",
        "零宽电话138\u200b00000000",
        "邮箱zhangsan@example.com",
        "全角邮箱ｚｈａｎｇｓａｎ＠ｅｘａｍｐｌｅ．ｃｏｍ",
        "身份证110101199001010015",
        "银行卡6228480000000007",
        "订单号13600000000",
        "长订单136000000001234",
        "整理120条活动反馈",
    ]) + "\n"

    def test_suggestions_cover_variants_and_skip_order_numbers(self):
        found = engine.suggest_terms(self.SAMPLE)
        self.assertEqual(set(found), {
            "110101199001010015",
            "138 0000 0000",
            "138-0000-0000",
            "13800000000",
            "138\u200b00000000",
            "6228480000000007",
            "zhangsan@example.com",
            "ｚｈａｎｇｓａｎ＠ｅｘａｍｐｌｅ．ｃｏｍ",
            "１３８００００００００",
        })
        self.assertEqual(found, sorted(found))
        self.assertNotIn("13600000000", found)
        self.assertNotIn("136000000001234", found)
        self.assertNotIn("张三", found)

    def test_short_order_inside_a_longer_number_is_refused(self):
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["13600000000"], "keep": ["整理120条活动反馈"]}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(self.SAMPLE.encode(), "text", plan)
        message = str(caught.exception)
        self.assertNotIn("136000000001234", message)
        self.assertIn("更长", message)

    def test_repeat_on_redacted_text_is_refused(self):
        raw = "电话13800000000\n整理120条活动反馈\n".encode()
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["13800000000"], "keep": ["整理120条活动反馈"]}
        first, report, _ = policy.export(raw, ".txt", plan)
        self.assertNotIn("13800000000", first.decode())
        self.assertTrue(report["checks"]["selected_strings_absent"])
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(first, ".txt", plan)
        self.assertIn("未在预览", str(caught.exception))

    def test_missing_term_on_fresh_text_still_stops(self):
        plan = {"version": 1, "kind": "text", "reviewed": True, "acknowledge_loss": True, "terms": ["13800000000"], "keep": ["整理120条活动反馈"]}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export("整理120条活动反馈\n".encode(), "text", plan)
        self.assertIn("未在预览", str(caught.exception))


MARKER = "【已隐去1】"
ALT = "〔已处理A〕"
WRONG = "13800000001"
LONG = "138000000001234"


def _office_plan(kind, terms, keep=None):
    return {
        "version": 1,
        "kind": kind,
        "reviewed": True,
        "acknowledge_loss": True,
        "terms": terms,
        "keep": [KEEP] if keep is None else keep,
    }


def _docx(text):
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _xlsx(rows):
    book = Workbook()
    sheet = book.active
    for index, row in enumerate(rows, start=1):
        for col, value in enumerate(row, start=1):
            sheet.cell(index, col, value)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


class ForgedMarkerTests(unittest.TestCase):
    def _assert_refused(self, export):
        with self.assertRaises(engine.Rejected) as caught:
            export()
        message = str(caught.exception)
        self.assertIn("未在预览", message)
        self.assertNotIn(PHONE, message)

    def test_wrong_phone_with_a_handwritten_marker_is_refused(self):
        body = MARKER + "\n电话" + PHONE + "\n" + KEEP + "\n"
        self._assert_refused(lambda: policy.export(body.encode(), ".txt", _office_plan("text", [WRONG])))
        self._assert_refused(lambda: policy.export(body.encode(), ".csv", _office_plan("csv", [WRONG], [])))
        self._assert_refused(lambda: policy.export(_docx(body), ".docx", _office_plan("word", [WRONG])))
        self._assert_refused(lambda: policy.export(_xlsx([[MARKER], [PHONE], [KEEP]]), ".xlsx", _office_plan("excel", [WRONG])))

    def test_missing_name_with_a_marker_is_refused(self):
        body = MARKER + "\n电话" + PHONE + "\n" + KEEP + "\n"
        self._assert_refused(lambda: policy.export(body.encode(), ".txt", _office_plan("text", ["张三"])))

    def test_zero_width_phone_with_a_marker_is_refused(self):
        body = MARKER + "\n138\u200b00000000\n" + KEEP + "\n"
        self._assert_refused(lambda: policy.export(body.encode(), ".txt", _office_plan("text", [PHONE])))


class LeftoverNumberTests(unittest.TestCase):
    def test_marker_does_not_excuse_a_number_inside_a_longer_one(self):
        body = MARKER + "\n" + LONG + "\n" + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(body.encode(), ".txt", _office_plan("text", [PHONE]))
        self.assertNotIn(LONG, str(caught.exception))
        self.assertTrue(engine.term_remains(body, PHONE))

    def test_standalone_and_prefix_of_a_longer_number_are_refused(self):
        body = "电话" + PHONE + "\n长编号" + LONG + "\n" + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(body.encode(), ".txt", _office_plan("text", [PHONE]))
        self.assertNotIn(LONG, str(caught.exception))

    def test_eight_digit_prefix_left_inside_a_longer_number_is_refused(self):
        short = "13800000"
        longer = "138000009999"
        body = short + "\n" + longer + "\n" + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(body.encode(), ".txt", _office_plan("text", [short]))
        message = str(caught.exception)
        self.assertNotIn(longer, message)
        self.assertNotIn(short, message)
        self.assertTrue(engine.term_remains("【已隐去1】" + longer, short))

    def test_zero_width_sibling_is_still_present(self):
        body = PHONE + "\n138\u200b00000000\n" + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(body.encode(), ".txt", _office_plan("text", [PHONE]))
        self.assertNotIn(PHONE, str(caught.exception))
        self.assertTrue(engine.term_remains("138\u200b00000000", PHONE))


class CoveredAnnotationTests(unittest.TestCase):
    def _pdf(self, draw):
        fitz = pdf.backend()
        doc = fitz.open()
        page = doc.new_page(width=400, height=280)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
        page.insert_text((20, 140), "13800008888", fontname="helv", fontsize=14)
        page.insert_text((20, 200), "DELETEME", fontname="helv", fontsize=14)
        draw(fitz, page)
        raw = doc.tobytes()
        target = page.search_for("DELETEME")[0]
        doc.close()
        return raw, target

    def _plan_for(self, target):
        box = [(target.x0 - 1) * 2, (target.y0 - 1) * 2, (target.x1 + 1) * 2, (target.y1 + 1) * 2]
        return _office_plan("pdf", []) | {
            "reviewed_pages": [1],
            "pages": [{"page": 1, "rectangles": [box]}],
            "terms": [],
        }

    def test_white_square_covering_text_is_refused(self):
        def draw(fitz, page):
            phone = page.search_for("13800008888")[0]
            annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
            annot.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
            annot.set_opacity(1)
            annot.update()

        raw, target = self._pdf(draw)
        plan = self._plan_for(target)
        leaked = pdf.export(raw, plan, _verify=False)
        with pdf.backend().open(stream=leaked, filetype="pdf") as doc:
            self.assertIn("13800008888", doc[0].get_text())
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", plan)
        message = str(caught.exception)
        self.assertIn("看不见", message)
        self.assertIn("框外", message)

    def test_link_and_hidden_note_are_still_removed(self):
        def draw(fitz, page):
            page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(20, 28, 160, 44), "uri": "https://example.com/note"})
            annot = page.add_text_annot(fitz.Point(300, 230), "隐藏便签甲乙丙")
            annot.set_flags(fitz.PDF_ANNOT_IS_HIDDEN | fitz.PDF_ANNOT_IS_NO_VIEW)
            annot.update()

        raw, target = self._pdf(draw)
        out, report, _ = policy.export(raw, ".pdf", self._plan_for(target))
        self.assertTrue(report["checks"]["covered_text_not_revealed"])
        self.assertTrue(report["checks"]["keep_phrases_preserved"])
        with pdf.backend().open(stream=out, filetype="pdf") as doc:
            self.assertIn(KEEP, doc[0].get_text())
            self.assertNotIn("DELETEME", doc[0].get_text())
            self.assertIsNone(doc[0].first_annot)
            self.assertFalse(doc[0].get_links())

    def test_freetext_and_stamp_are_still_refused(self):
        fitz = pdf.backend()

        def freetext(_fitz, page):
            page.add_freetext_annot(fitz.Rect(250, 210, 380, 250), "自由文本甲乙丙", fontsize=11, fontname="china-s", fill_color=(1, 1, 0.8), text_color=(0, 0, 0)).update()

        def stamp(_fitz, page):
            page.add_stamp_annot(fitz.Rect(250, 180, 370, 250)).update()

        for draw in (freetext, stamp):
            raw, target = self._pdf(draw)
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(raw, ".pdf", self._plan_for(target))
            self.assertIn("框外", str(caught.exception))


class SeparatorAndKeepTests(unittest.TestCase):
    def test_short_term_separated_from_a_label_is_refused(self):
        for sep in ("\n", "\u200b", "\u00a0", "\u3000"):
            body = "编号" + sep + "0000\n" + KEEP + "\n"
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(body.encode(), ".txt", _office_plan("text", ["0000"]))
            message = str(caught.exception)
            self.assertNotIn("编号0000", message)
            self.assertNotIn("0000", message)

    def test_formula_after_exotic_space_is_quoted_and_plain_negative_stays(self):
        for lead in ("\u00a0", "\u3000", "\u2028", "\f", "\v"):
            self.assertEqual(formats.safe_cell(lead + "=1+1"), "'" + lead + "=1+1")
        self.assertEqual(formats.safe_cell("-120"), "-120")
        self.assertEqual(formats.safe_cell(" -120"), " -120")
        raw = "姓名,公式\n张三,\u00a0=1+1\n李四,\u3000=1+1\n".encode()
        out = formats.export(raw, "csv", _office_plan("csv", ["张三", "李四"], []))
        rows = formats.csv_rows(out, "csv")
        self.assertEqual(rows[1][1], "'\u00a0=1+1")
        self.assertEqual(rows[2][1], "'\u3000=1+1")

    def test_keep_does_not_accept_a_quoted_formula_with_trailing_space(self):
        raw = "姓名,公式\n张三,=1+1 \n".encode()
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(raw, "csv", _office_plan("csv", ["张三"], ["=1+1"]))
        self.assertIn("空格", str(caught.exception))

    def test_keep_of_a_new_marker_is_refused(self):
        raw = "请已隐去此段 " + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw.encode(), ".txt", _office_plan("text", ["已隐去"], [ALT]))
        self.assertIn("复检", str(caught.exception))

    def test_existing_alternate_marker_collides(self):
        raw = "已有" + ALT + " 请已隐去此段 " + KEEP + "\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw.encode(), ".txt", _office_plan("text", ["已隐去"]))
        message = str(caught.exception)
        self.assertIn("替换标记", message)
        self.assertNotIn("请已隐去此段", message)

    def test_existing_default_marker_switches_style(self):
        raw = "备注" + MARKER + " 电话" + PHONE + "\n" + KEEP + "\n"
        out = policy.export(raw.encode(), ".txt", _office_plan("text", [PHONE]))[0].decode()
        self.assertIn(ALT, out)
        self.assertIn(MARKER, out)
        self.assertNotIn(PHONE, out)
        self.assertIn(KEEP, out)


COVERED = "13800006661"


def _digits(phone, base):
    return "".join(chr(base + int(ch)) for ch in phone)


def _superscript(phone):
    table = {"0": "\u2070", "1": "\u00b9", "2": "\u00b2", "3": "\u00b3", "4": "\u2074", "5": "\u2075", "6": "\u2076", "7": "\u2077", "8": "\u2078", "9": "\u2079"}
    return "".join(table[ch] for ch in phone)


class DarkCoverTests(unittest.TestCase):
    def _pdf(self, color, cover):
        fitz = pdf.backend()
        doc = fitz.open()
        page = doc.new_page(width=400, height=280)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
        page.insert_text((20, 130), COVERED, fontname="helv", fontsize=16, color=color)
        page.insert_text((20, 230), "OTHERTEXT", fontname="helv", fontsize=14)
        phone = page.search_for(COVERED)[0]
        other = page.search_for("OTHERTEXT")[0]
        cover(fitz, page, phone)
        raw = doc.tobytes()
        doc.close()
        return raw, other, phone

    def _plan(self, target):
        return _pdf_plan(_pixel_box(target))

    def _square(self, fill, opacity):
        def draw(fitz, page, phone):
            annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
            annot.set_colors(stroke=fill, fill=fill)
            annot.set_opacity(opacity)
            annot.update()

        return draw

    def test_dark_cover_over_lighter_or_darker_text_is_refused(self):
        colors = {
            "black": (0, 0, 0),
            "red": (0.8, 0.1, 0.1),
            "yellow": (0.85, 0.75, 0.1),
            "gray": (0.45, 0.45, 0.45),
            "light": (0.75, 0.75, 0.75),
            "near_white": (0.92, 0.92, 0.92),
        }
        covers = (
            self._square((0, 0, 0), 1),
            self._square((0, 0, 0), 0.98),
            self._square((0.25, 0.25, 0.25), 1),
        )

        def freetext(fitz, page, phone):
            page.add_freetext_annot(
                fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 4),
                "盖",
                fontsize=12,
                fontname="china-s",
                fill_color=(0, 0, 0),
                text_color=(0, 0, 0),
            ).update()

        covers = covers + (freetext,)
        for name, color in colors.items():
            for draw in covers:
                raw, other, _phone = self._pdf(color, draw)
                leaked = pdf.export(raw, self._plan(other), _verify=False)
                with pdf.backend().open(stream=leaked, filetype="pdf") as doc:
                    self.assertIn(COVERED, doc[0].get_text(), name)
                with self.assertRaises(engine.Rejected, msg=name) as caught:
                    policy.export(raw, ".pdf", self._plan(other))
                message = str(caught.exception)
                self.assertIn("看不见", message, name)
                self.assertNotIn(COVERED, message, name)

    def test_black_square_on_blank_space_still_delivers(self):
        def draw(fitz, page, _phone):
            annot = page.add_rect_annot(fitz.Rect(300, 30, 360, 80))
            annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
            annot.set_opacity(1)
            annot.update()

        raw, other, _phone = self._pdf((0, 0, 0), draw)
        out, report, _ext = policy.export(raw, ".pdf", self._plan(other))
        self.assertTrue(report["checks"]["covered_text_not_revealed"])
        self.assertTrue(report["checks"]["outside_page_pixels_preserved"])
        with pdf.backend().open(stream=out, filetype="pdf") as doc:
            text = doc[0].get_text()
            self.assertIn(KEEP, text)
            self.assertIn(COVERED, text)
            self.assertNotIn("OTHERTEXT", text)
            self.assertIsNone(doc[0].first_annot)

    def test_boxing_the_covered_number_still_removes_it(self):
        raw, _other, phone = self._pdf((0, 0, 0), self._square((0, 0, 0), 1))
        out, report, _ext = policy.export(raw, ".pdf", self._plan(phone))
        self.assertTrue(report["checks"]["covered_text_not_revealed"])
        self.assertTrue(report["checks"]["selected_text_removed"])
        with pdf.backend().open(stream=out, filetype="pdf") as doc:
            self.assertNotIn(COVERED, doc[0].get_text())
            self.assertIn(KEEP, doc[0].get_text())

    def test_highlight_over_visible_text_still_delivers(self):
        def draw(fitz, page, _phone):
            found = page.search_for(KEEP)[0]
            page.add_highlight_annot(found).update()

        raw, other, _phone = self._pdf((0, 0, 0), draw)
        out, report, _ext = policy.export(raw, ".pdf", self._plan(other))
        self.assertTrue(report["checks"]["covered_text_not_revealed"])
        self.assertTrue(report["checks"]["keep_phrases_preserved"])
        with pdf.backend().open(stream=out, filetype="pdf") as doc:
            self.assertIn(KEEP, doc[0].get_text())
            self.assertNotIn("OTHERTEXT", doc[0].get_text())
            self.assertIsNone(doc[0].first_annot)

    def test_line_and_polyline_over_text_are_refused(self):
        def line(fitz, page, phone):
            y = (phone.y0 + phone.y1) / 2
            annot = page.add_line_annot(fitz.Point(phone.x0 - 6, y), fitz.Point(phone.x1 + 18, y))
            annot.set_border(width=12)
            annot.set_colors(stroke=(0, 0, 0))
            annot.update()

        def polyline(fitz, page, phone):
            y = (phone.y0 + phone.y1) / 2
            points = [fitz.Point(phone.x0 - 4, y - 3), fitz.Point((phone.x0 + phone.x1) / 2, y + 4), fitz.Point(phone.x1 + 14, y - 2)]
            annot = page.add_polyline_annot(points)
            annot.set_border(width=10)
            annot.set_colors(stroke=(0, 0, 0))
            annot.update()

        for draw in (line, polyline):
            raw, other, _phone = self._pdf((0, 0, 0), draw)
            leaked = pdf.export(raw, self._plan(other), _verify=False)
            with pdf.backend().open(stream=leaked, filetype="pdf") as doc:
                self.assertIn(COVERED, doc[0].get_text())
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(raw, ".pdf", self._plan(other))
            message = str(caught.exception)
            self.assertIn("看不见", message)
            self.assertIn("去掉", message)
            self.assertNotIn(COVERED, message)

    def test_vector_strokes_under_a_black_square_are_refused(self):
        fitz = pdf.backend()
        doc = fitz.open()
        page = doc.new_page(width=400, height=280)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
        page.insert_text((20, 230), "OTHERTEXT", fontname="helv", fontsize=14)
        shape = page.new_shape()
        for dx in range(0, 120, 8):
            shape.draw_line(fitz.Point(30 + dx, 100), fitz.Point(32 + dx, 140))
        shape.finish(color=(0, 0, 0), width=1.5)
        shape.commit()
        annot = page.add_rect_annot(fitz.Rect(24, 92, 160, 148))
        annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        annot.set_opacity(1)
        annot.update()
        other = page.search_for("OTHERTEXT")[0]
        raw = doc.tobytes()
        doc.close()
        plan = self._plan(other)
        leaked = pdf.export(raw, plan, _verify=False)
        with pdf.backend().open(stream=leaked, filetype="pdf") as opened:
            self.assertNotIn(COVERED, opened[0].get_text())
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", plan)
        message = str(caught.exception)
        self.assertIn("看不见", message)
        self.assertIn("去掉", message)

    def test_faint_or_stroke_only_square_tells_user_to_remove_it(self):
        def stroke(fitz, page, phone):
            annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
            annot.set_colors(stroke=(0, 0, 0))
            annot.set_border(width=2)
            annot.update()

        for draw in (self._square((0, 0, 0), 0.08), stroke):
            raw, other, _phone = self._pdf((0, 0, 0), draw)
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(raw, ".pdf", self._plan(other))
            message = str(caught.exception)
            self.assertIn("去掉", message)
            self.assertNotIn(COVERED, message)


class ShortNumberSideTests(unittest.TestCase):
    def test_right_side_and_hyphen_are_refused(self):
        samples = ("0000合同", "0000 合同", "0000\n合同", "ID-0000", "ID\u20140000", "0000-ID")
        for sample in samples:
            body = sample + "\n" + KEEP + "\n"
            with self.assertRaises(engine.Rejected, msg=sample) as caught:
                policy.export(body.encode(), ".txt", _office_plan("text", ["0000"]))
            message = str(caught.exception)
            self.assertNotIn("0000", message, sample)
            self.assertNotIn("合同", message, sample)
            self.assertNotIn("ID", message, sample)

    def test_standalone_short_number_still_delivers(self):
        body = KEEP + "。\n0000\n120\n"
        out, report, _ext = policy.export(body.encode(), ".txt", _office_plan("text", ["0000"], [KEEP]))
        text = out.decode()
        self.assertNotIn("0000", text)
        self.assertIn("【已隐去1】", text)
        self.assertIn(KEEP, text)
        self.assertTrue(report["checks"]["selected_strings_absent"])

    def test_underscore_slash_and_hyphenated_digits_are_refused(self):
        samples = ("ID_0000", "0000_合同", "ID/0000", "0000/合同", "ID／0000", "0000-1234", "1234-0000")
        for sample in samples:
            body = sample + "\n" + KEEP + "\n"
            with self.assertRaises(engine.Rejected, msg=sample) as caught:
                policy.export(body.encode(), ".txt", _office_plan("text", ["0000"]))
            message = str(caught.exception)
            self.assertIn("整段", message, sample)
            self.assertNotIn("0000", message, sample)
            self.assertNotIn("1234", message, sample)
            self.assertNotIn("合同", message, sample)
            self.assertNotIn("ID", message, sample)

    def test_short_number_beside_words_tells_user_to_select_the_span(self):
        body = "价格 12 元\n活动反馈说明\n"
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(body.encode(), ".txt", _office_plan("text", ["12"], ["活动反馈说明"]))
        message = str(caught.exception)
        self.assertIn("整段", message)
        self.assertIn("一起选上", message)
        self.assertNotIn("12", message)
        self.assertNotIn("价格", message)
        self.assertNotIn("元", message)


def _circled(phone):
    return "".join("\u24ea" if ch == "0" else chr(0x245F + int(ch)) for ch in phone)


class AlternateSpellingTests(unittest.TestCase):
    def _variants(self):
        return [
            "138 0000 0000",
            "138-0000-0000",
            "138\u00a00000\u00a00000",
            "138\u30000000\u30000000",
            "138.0000.0000",
            "138\u00b70000\u00b70000",
            _digits(PHONE, 0x0660),
            _digits(PHONE, 0x06F0),
            _digits(PHONE, 0x1D7CE),
            _superscript(PHONE),
            _circled(PHONE),
            "138\u20090000\u20090000",
            "138\u20070000\u20070000",
            "138\u202f0000\u202f0000",
            "138,0000,0000",
            "138/0000/0000",
            "138_0000_0000",
            "138 \u200b0000 \u200b0000",
        ]

    def test_other_spelling_of_the_same_number_is_refused(self):
        for variant in self._variants():
            body = "电话" + PHONE + "\n另一种" + variant + "\n" + KEEP + "\n"
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(body.encode(), ".txt", _office_plan("text", [PHONE]))
            message = str(caught.exception)
            self.assertIn("另一种写法", message)
            self.assertNotIn(PHONE, message)
            self.assertNotIn(variant, message)

    def test_a_different_number_can_remain_and_is_not_called_absent(self):
        other = "139 0000 0000"
        body = "电话" + PHONE + "\n其它" + other + "\n" + KEEP + "\n"
        out, report, _ext = policy.export(body.encode(), ".txt", _office_plan("text", [PHONE]))
        text = out.decode()
        self.assertNotIn(PHONE, text)
        self.assertIn(other, text)
        self.assertTrue(report["checks"]["selected_strings_absent"])
        self.assertIn(KEEP, text)

    def test_selecting_only_the_other_spelling_still_refuses(self):
        for variant in self._variants():
            body = "电话" + PHONE + "\n另一种" + variant + "\n" + KEEP + "\n"
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(body.encode(), ".txt", _office_plan("text", [variant]))
            message = str(caught.exception)
            self.assertIn("另一种写法", message)
            self.assertNotIn(PHONE, message)
            self.assertNotIn(variant, message)


class PdfKeepMessageTests(unittest.TestCase):
    def test_missing_keep_names_the_keep_item(self):
        raw, found = _page()
        plan = _pdf_plan(_pixel_box(found))
        plan["keep"] = ["原文里没有的保留句"]
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", plan)
        message = str(caught.exception)
        self.assertIn("保留项", message)
        self.assertIn("没有对上", message)
        self.assertNotIn("框外", message)
        self.assertNotIn("原文里没有的保留句", message)


if __name__ == "__main__":
    unittest.main()
