"""产品边界 A：默认保留批注；明确勾选才按严格像素规则清批注。材料全部是虚构示例。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
import cli
import engine
import formats
import output_policy as policy
import pdf_preserve as pdf

KEEP = "整理活动反馈"
PHONE = "13800006661"
WORD = "DELETEME"
NOTE = "请再核对活动名称"
SKILL = Path(__file__).parents[2]
SCRIPTS = Path(__file__).parents[1]


def _pixel_box(rect):
    return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]


def _plan(box, clear=False, pages=None):
    plan = {
        "version": 1,
        "kind": "pdf",
        "reviewed": True,
        "reviewed_pages": [1] if pages is None else [row["page"] for row in pages],
        "keep": [KEEP],
        "pages": [{"page": 1, "rectangles": [box]}] if pages is None else pages,
    }
    if clear:
        plan["clear_annotations"] = True
    return plan


def _new_page():
    fitz = pdf.backend()
    doc = fitz.open()
    page = doc.new_page(width=420, height=320)
    page.insert_text((24, 48), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((24, 120), WORD, fontname="helv", fontsize=14)
    page.insert_text((24, 200), PHONE, fontname="helv", fontsize=14)
    return fitz, doc, page


def _pack(doc, page, text=WORD):
    found = page.search_for(text)[0]
    raw = doc.tobytes()
    doc.close()
    return raw, _pixel_box(found)


def _annot_blob(annot):
    info = annot.info or {}
    parts = [str(info.get(key) or "") for key in ("content", "title", "subject")]
    try:
        parts.append(annot.get_text("text") or "")
    except Exception:
        parts.append("")
    return "\n".join(parts)


def _word_leaked(data, word):
    """交付副本里还能读到补选词，才算漏。拒绝交付不算漏。"""
    with pdf.backend().open(stream=data, filetype="pdf") as doc:
        for page in doc:
            if word in page.get_text():
                return "正文"
            for annot in page.annots() or []:
                if word.casefold() in _annot_blob(annot).casefold():
                    return "批注"
    if word.encode("utf-8") in data or word.encode("utf-16-be") in data:
        return "文件字节"
    return ""


def _office_samples():
    """原先 12 份虚构办公批注的形状。框选的是 DELETEME，不勾清除批注。"""
    samples = []

    def add(name, draw):
        fitz, doc, page = _new_page()
        draw(fitz, page)
        raw, box = _pack(doc, page)
        samples.append((name, raw, box))

    def highlight(page, target):
        annot = page.add_highlight_annot(page.search_for(target)[0])
        annot.set_colors(stroke=(1, 1, 0))
        annot.update()

    add("黄色高亮在保留句", lambda _fitz, page: highlight(page, KEEP))
    add("黄色高亮压在号码上", lambda _fitz, page: highlight(page, PHONE))
    add("下划线", lambda _fitz, page: page.add_underline_annot(page.search_for(KEEP)[0]).update())
    add("删除线在被选词上", lambda _fitz, page: page.add_strikeout_annot(page.search_for(WORD)[0]).update())
    add("波浪线", lambda _fitz, page: page.add_squiggly_annot(page.search_for(KEEP)[0]).update())
    add("页边便签", lambda fitz, page: page.add_text_annot(fitz.Point(360, 48), NOTE).update())

    def blank_stamp(fitz, page):
        phone = page.search_for(PHONE)[0]
        page.add_stamp_annot(fitz.Rect(phone.x1 + 36, phone.y0 - 8, phone.x1 + 150, phone.y1 + 16)).update()

    def covering_stamp(fitz, page):
        phone = page.search_for(PHONE)[0]
        page.add_stamp_annot(fitz.Rect(phone.x0 - 4, phone.y0 - 6, phone.x1 + 8, phone.y1 + 8)).update()

    add("空白处审批图章", blank_stamp)
    add("图章压住号码", covering_stamp)
    add("页边手写签名", lambda _fitz, page: page.add_ink_annot([[(340, 70), (390, 110), (360, 140)]]).update())
    def red_circle(fitz, page):
        annot = page.add_circle_annot(fitz.Rect(300, 40, 400, 110))
        annot.set_colors(stroke=(1, 0, 0))
        annot.update()

    add("红圈圈注", red_circle)

    def black_box(fitz, page):
        phone = page.search_for(PHONE)[0]
        annot = page.add_rect_annot(fitz.Rect(phone.x0 - 2, phone.y0 - 2, phone.x1 + 2, phone.y1 + 2))
        annot.set_colors(stroke=(0, 0, 0), fill=(0.15, 0.15, 0.15))
        annot.set_opacity(1)
        annot.update()

    add("用户黑框盖住号码", black_box)

    def combined(_fitz, page):
        highlight(page, KEEP)
        page.add_underline_annot(page.search_for(PHONE)[0]).update()
        page.add_text_annot(pdf.backend().Point(360, 48), NOTE).update()

    add("高亮下划线和便签同时在", combined)
    return samples


def _square(page, rect, gray, border, opacity=1, fill=True):
    fitz = pdf.backend()
    annot = page.add_rect_annot(fitz.Rect(rect.x0 - 4, rect.y0 - 4, rect.x1 + 4, rect.y1 + 4))
    if fill:
        annot.set_colors(stroke=(1, 1, 1), fill=(gray, gray, gray))
    else:
        annot.set_colors(stroke=(gray, gray, gray))
    annot.set_border(width=border)
    annot.set_opacity(opacity)
    annot.update()
    return annot


class DefaultOfficeTests(unittest.TestCase):
    def test_ordinary_office_markup_delivers_without_clearing_annotations(self):
        delivered = []
        refused = []
        for name, raw, box in _office_samples():
            try:
                out, report, _ext = policy.export(raw, ".pdf", _plan(box))
            except engine.Rejected as exc:
                message = str(exc)
                self.assertNotIn(WORD, message, name)
                self.assertNotIn(PHONE, message, name)
                self.assertNotIn(NOTE, message, name)
                refused.append(name)
                continue
            leak = _word_leaked(out, WORD)
            self.assertFalse(leak, name + " 漏在" + leak)
            self.assertTrue(all(report["checks"].values()), name)
            self.assertIn("默认保留批注", report["scope"], name)
            with pdf.backend().open(stream=out, filetype="pdf") as doc:
                self.assertIsNotNone(doc[0].first_annot, name)
                self.assertIn(KEEP, doc[0].get_text(), name)
            delivered.append(name)
        self.assertEqual(refused, [], "默认路径应能交付这些虚构办公批注")
        self.assertEqual(len(delivered), 12, delivered)

    def test_margin_note_that_quotes_the_selection_is_removed(self):
        fitz, doc, page = _new_page()
        page.add_text_annot(fitz.Point(360, 48), "备用号码 " + PHONE).update()
        raw, box = _pack(doc, page, PHONE)
        out, report, _ext = policy.export(raw, ".pdf", _plan(box))
        self.assertIn("默认保留批注", report["scope"])
        self.assertFalse(_word_leaked(out, PHONE))
        with pdf.backend().open(stream=out, filetype="pdf") as opened:
            blobs = [_annot_blob(annot) for annot in opened[0].annots() or []]
            self.assertFalse(any(PHONE in blob for blob in blobs))
            self.assertIn(KEEP, opened[0].get_text())

    def test_dashed_number_in_a_margin_note_counts_as_a_hit(self):
        fitz, doc, page = _new_page()
        page.add_text_annot(fitz.Point(360, 48), "写成 138-0000-6661").update()
        raw, box = _pack(doc, page, PHONE)
        out, _report, _ext = policy.export(raw, ".pdf", _plan(box))
        self.assertFalse(_word_leaked(out, PHONE))
        self.assertNotIn("138-0000-6661".encode(), out)

    def test_hit_that_would_uncover_text_rejects_the_whole_file(self):
        fitz, doc, page = _new_page()
        keep = page.search_for(KEEP)[0]
        annot = page.add_rect_annot(fitz.Rect(keep.x0 - 2, keep.y0 - 2, keep.x1 + 2, keep.y1 + 2))
        annot.set_colors(stroke=(0.4, 0.4, 0.4), fill=(0.4, 0.4, 0.4))
        annot.set_opacity(1)
        annot.set_info(content=PHONE)
        annot.update()
        raw, box = _pack(doc, page, PHONE)
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", _plan(box))
        message = str(caught.exception)
        self.assertIn("第1页", message)
        self.assertIn("露出", message)
        self.assertNotIn(PHONE, message)
        self.assertNotIn(WORD, message)
        self.assertNotIn(KEEP, message)

    def test_note_on_another_page_still_counts(self):
        fitz = pdf.backend()
        doc = fitz.open()
        first = doc.new_page(width=420, height=320)
        first.insert_text((24, 48), KEEP, fontname="china-s", fontsize=14)
        first.insert_text((24, 120), WORD, fontname="helv", fontsize=14)
        found = first.search_for(WORD)[0]
        second = doc.new_page(width=420, height=320)
        second.insert_text((24, 48), KEEP, fontname="china-s", fontsize=14)
        second.add_text_annot(fitz.Point(300, 200), "另一页写了 " + WORD).update()
        raw = doc.tobytes()
        doc.close()
        pages = [{"page": 1, "rectangles": [_pixel_box(found)]}, {"page": 2, "rectangles": [[760, 560, 820, 620]]}]
        # 第二页的框在右下空白，不把便签或保留句当成补选词。跨页便签仍要按第一页的词来核对。
        out, _report, _ext = policy.export(raw, ".pdf", _plan(None, pages=pages))
        self.assertFalse(_word_leaked(out, WORD))
        with pdf.backend().open(stream=out, filetype="pdf") as opened:
            notes = [_annot_blob(annot) for page in opened for annot in page.annots() or []]
            self.assertFalse(any(WORD in note for note in notes))

    def _assert_quiet_refusal(self, raw, box, secret):
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", _plan(box))
        message = str(caught.exception)
        self.assertNotIn(secret, message)
        self.assertNotIn(WORD, message)
        self.assertNotIn(NOTE, message)
        return message

    def test_unreadable_annotations_are_refused_without_echoing(self):
        fitz, doc, page = _new_page()
        note = page.add_text_annot(fitz.Point(340, 40), PHONE)
        note.update()
        doc.xref_set_key(note.xref, "Subtype", "/Sound")
        raw, box = _pack(doc, page)
        message = self._assert_quiet_refusal(raw, box, PHONE)
        self.assertIn("没法确认", message)
        self.assertIn("第1页", message)

        fitz, doc, page = _new_page()
        page.add_file_annot(fitz.Point(340, 40), PHONE.encode(), "note.txt", desc="附件说明")
        raw, box = _pack(doc, page)
        self._assert_quiet_refusal(raw, box, PHONE)

        fitz, doc, page = _new_page()
        annot = page.add_text_annot(fitz.Point(340, 40), NOTE)
        annot.update()
        value = doc.xref_get_key(annot.xref, "AP")[1]
        tokens = value.replace("<", " ").replace(">", " ").split()
        form = int(tokens[tokens.index("/N") + 1])
        image = doc.get_new_xref()
        doc.update_object(image, "<</Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 12>>")
        doc.update_stream(image, b"\xff" * 12)
        doc.xref_set_key(form, "Resources", "<</XObject <</Im0 " + str(image) + " 0 R>>>>")
        doc.update_stream(form, (doc.xref_stream(form) or b"") + b"\n/Im0 Do\n")
        raw, box = _pack(doc, page)
        message = self._assert_quiet_refusal(raw, box, PHONE)
        self.assertTrue("没法确认" in message or "图片" in message, message)


class ClearPathTests(unittest.TestCase):
    def test_gray_and_thin_covers_do_not_leak_when_clearing_is_explicit(self):
        covers = (
            ("灰底白边", dict(gray=0.4, border=2, opacity=1, fill=True)),
            ("浅灰白边", dict(gray=0.7, border=6, opacity=1, fill=True)),
            ("半透明灰盖", dict(gray=0.45, border=3, opacity=0.45, fill=True)),
            ("细描边", dict(gray=0.25, border=2, opacity=1, fill=False)),
        )
        delivered = []
        for name, options in covers:
            _fitz, doc, page = _new_page()
            _square(page, page.search_for(PHONE)[0], **options)
            raw, box = _pack(doc, page)
            plan = _plan(box, clear=True)
            opened = pdf.export(raw, plan, _verify=False)
            with pdf.backend().open(stream=opened, filetype="pdf") as unchecked:
                self.assertIn(PHONE, unchecked[0].get_text(), name)
            try:
                policy.export(raw, ".pdf", plan)
            except engine.Rejected as exc:
                message = str(exc)
                self.assertIn("第1页", message, name)
                self.assertIn("去掉", message, name)
                self.assertTrue(any(part in message for part in ("画面变了", "盖住了", "不一样")), name + "\n" + message)
                self.assertNotIn(PHONE, message, name)
                self.assertNotIn(WORD, message, name)
                continue
            delivered.append(name)
        self.assertEqual(delivered, [])


class SurfaceTests(unittest.TestCase):
    def test_docs_cli_and_page_say_annotations_stay_unless_asked(self):
        formats_doc = (SKILL / "references" / "formats.md").read_text(encoding="utf-8")
        commands = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        page = (SCRIPTS / "web" / "index.html").read_text(encoding="utf-8")
        script = (SCRIPTS / "web" / "app.js").read_text(encoding="utf-8")
        for text in (formats_doc, commands, skill, page, formats.NOTICES["pdf"]):
            self.assertIn("一并清除批注", text)
        self.assertIn("默认只删除框选的正文", formats.NOTICES["pdf"])
        self.assertIn("默认不勾选", page)
        self.assertIn("clear_annotations:job.kind==='pdf'&&$('clear-annotations').checked", script)
        self.assertIn("默认保留批注", commands)
        self.assertIn("不会自动把批注烧进页面", formats_doc)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS)
        help_text = subprocess.run(
            [sys.executable, str(SCRIPTS / "cli.py"), "redact", "--help"],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
        self.assertEqual(help_text.returncode, 0, help_text.stderr)
        self.assertIn("--clear-annotations", help_text.stdout)
        self.assertIn("默认关闭", help_text.stdout)
        self.assertIn("一并清除批注", help_text.stdout)

    def test_plan_field_is_boolean_and_the_flag_is_pdf_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan_path = folder / "plan.json"
            body = {"version": 1, "kind": "pdf", "reviewed": True, "clear_annotations": True, "reviewed_pages": [1], "pages": [{"page": 1, "rectangles": [[0, 0, 10, 10]]}]}
            plan_path.write_text(json.dumps(body), encoding="utf-8")
            loaded = cli.load_plan(plan_path, "pdf")
            self.assertIs(loaded["clear_annotations"], True)
            body["clear_annotations"] = "yes"
            plan_path.write_text(json.dumps(body), encoding="utf-8")
            with self.assertRaises(cli.Failure) as caught:
                cli.load_plan(plan_path, "pdf")
            self.assertIn("一并清除批注", str(caught.exception))
            text_plan = {"version": 1, "kind": "text", "reviewed": True, "terms": ["示例"], "acknowledge_loss": True, "clear_annotations": True}
            plan_path.write_text(json.dumps(text_plan), encoding="utf-8")
            with self.assertRaises(cli.Failure):
                cli.load_plan(plan_path, "text")
            source = folder / "note.txt"
            source.write_text("示例 保留\n", encoding="utf-8")
            text_plan.pop("clear_annotations")
            plan_path.write_text(json.dumps(text_plan), encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SCRIPTS)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "cli.py"), "redact", "--input", str(source), "--plan", str(plan_path), "--output", str(folder / "out.txt"), "--clear-annotations"],
                capture_output=True, text=True, encoding="utf-8", env=env, check=False,
            )
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("只适用于 PDF", payload["error"])
            self.assertNotIn("示例", payload["error"])

    def test_rasterize_cannot_stand_in_for_clearing_annotations(self):
        raw = formats.make_pdf([Image.new("RGB", (80, 80), "white")])
        plan = {"reviewed_pages": [1], "pages": [{"page": 1, "rectangles": [[0, 0, 20, 20]]}], "acknowledge_loss": True, "pdf_mode": "rasterize", "clear_annotations": True, "keep": []}
        with self.assertRaises(engine.Rejected) as caught:
            formats.export(raw, "pdf", plan)
        self.assertIn("图像化", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
