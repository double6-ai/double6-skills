"""批注遮盖回归。样例在测试里生成，不提交 PDF。号码都是虚构的。

220 例与复审原型的方向 1 对齐：会露出内容的一律不交付；正常办公里只有用户自己画的黑框拒绝。
生成放在单独进程里，避免同一进程里先画过直线后再画折线时，MuPDF 写出不同的外观。
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

import engine
import formats
import output_policy as policy
import pdf_preserve as pdf
import pymupdf as fitz
from generators.review_cases import DILUTION_SPECS
from generators.review_cases import KEEP as REVIEW_KEEP
from generators.review_cases import NEIGHBOR
from generators.review_cases import OUTSIDE_SPECS
from generators.review_cases import SECRET as REVIEW_SECRET
from generators.review_cases import dilution
from generators.review_cases import plain_phone


SECRETS = ("13800006661", "13800007771", "13800001111", "FICTIONAL13800009991")
# 原型把这两例判成可交付，产品仍按原有隐藏文字和未涂黑标记拒绝。
STRICTER = {
    ("attack", "攻击-只有不可见文字层"),
    ("round7:kinds", "未应用涂黑标记"),
}
# 隐藏或不可见标志下的灰方块，pdfium 和 MuPDF 都没有画出来，字的边缘还在。
# 原型另按“隐藏标志 + 矩形里有号码”拒绝；那会把本来看得见的字也拒掉，这里不沿用。
VISIBLE_DESPITE_FLAG = {
    ("round7:flags", "标志Hidden-灰底白边"),
    ("round7:flags", "标志NoView-灰底白边"),
    ("round7:flags", "标志Hidden+Print-灰底白边"),
    ("round7:flags", "标志NoView+Print-灰底白边"),
    ("round7:flags", "标志NoView+ToggleNoView-灰底白边"),
}
# 整块矩形仍可读，但单个字形已经不达标。逐字形不能把它们平均掉。
# 图章压住两个数字，两边都看成没看清。透明度 0.25 的方块有一个数字，pdfium 看成没看清、MuPDF 看成还在。
PER_GLYPH_COVER = {
    ("attack", "正常-图章压住号码"),
    ("attack", "攻击-黑方块透明度0.25"),
}


class _ImageSize:
    def __init__(self, size):
        self.size = size
        self.width, self.height = size


def _pdf_plan(box, keep):
    return {
        "version": 1,
        "kind": "pdf",
        "reviewed": True,
        "reviewed_pages": [1],
        "keep": keep,
        "pages": [{"page": 1, "rectangles": [[float(value) for value in box]]}],
    }


def _text_plan(terms, keep):
    return {
        "version": 1,
        "kind": "text",
        "reviewed": True,
        "acknowledge_loss": True,
        "terms": terms,
        "keep": keep,
    }


def _echo(message):
    return [item for item in SECRETS if item in message]


def _text_of(data):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _source_hides_phone(raw):
    """号码区域被涂成一块近乎纯色，就当成画面上已经看不见这串数字。"""
    size = formats.pdf_info(raw)[0]
    boxes = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        page = doc[0]
        for secret in SECRETS:
            for hit in page.search_for(secret):
                box = pdf._to_pixel_box(hit, page, _ImageSize(size))
                if box:
                    boxes.append(box)
    if not boxes:
        return False
    image = formats.pdf_image(raw, 0).convert("L")
    for box in boxes:
        clamped = pdf._clamp_pixel_box(box, image)
        if clamped is None:
            continue
        crop = image.crop(clamped)
        low, high = crop.getextrema()
        raw_bytes = crop.tobytes()
        mean = sum(raw_bytes) / len(raw_bytes)
        if high - low <= 12 and mean < 240:
            return True
    return False


def collect_cases():
    from generators.author_cases import build_samples
    from generators.office_cases import office_samples
    from generators.round7_cases import KEEP as round_keep
    from generators.round7_cases import cases

    rows = []
    for sample in office_samples():
        rows.append({
            "group": sample["group"],
            "name": sample["name"],
            "pdf": base64.b64encode(sample["raw"]).decode("ascii"),
            "box": sample["box"],
            "keep": [sample["keep"]] if sample["keep"] else [],
            "kind": "pdf",
            "params": sample["params"],
        })
    for row in cases():
        if row["kind"] == "text":
            rows.append({
                "group": row["group"],
                "name": row["name"],
                "kind": "text",
                "body": row["body"],
                "terms": row["terms"],
                "keep": row["keep"],
                "params": row["params"],
            })
            continue
        rows.append({
            "group": "round7:" + row["group"],
            "name": row["name"],
            "pdf": row["pdf_hex"],
            "pdf_encoding": "hex",
            "box": row["box"],
            "keep": [round_keep] if row["keep"] else [],
            "kind": "pdf",
            "params": row["params"],
        })
    for sample in build_samples():
        rows.append({
            "group": "author",
            "name": sample["name"],
            "pdf": sample["pdf"],
            "box": sample["plan"]["pages"][0]["rectangles"][0],
            "keep": sample["plan"]["keep"],
            "kind": "pdf",
            "params": sample["params"],
        })
    return rows


def _raw_of(row):
    if row.get("pdf_encoding") == "hex":
        return bytes.fromhex(row["pdf"])
    return base64.b64decode(row["pdf"])


def _expected(key, oracle):
    if key in VISIBLE_DESPITE_FLAG:
        return "deliver"
    if key in PER_GLYPH_COVER or key in STRICTER or oracle["d1"] == "reject" or oracle["cohort"] == "reveal":
        return "reject"
    return "deliver"


class OutsideNoiseTests(unittest.TestCase):
    def test_sub_glyph_raster_speck_is_not_treated_as_a_cover(self):
        # Windows 上高亮旁路出来的毛边大约是 4×9。框外真把号码涂平的块长边是两百像素上下。
        self.assertTrue(pdf._outside_change_is_noise((69, 67, 73, 76)))
        self.assertFalse(pdf._outside_change_is_noise((20, 309, 232, 389)))
        self.assertFalse(pdf._outside_change_is_noise((30, 320, 40, 360)))


class OcclusionOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.mkdtemp(prefix="occlusion-cases-")
        path = Path(directory) / "cases.json"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.check_call([sys.executable, str(Path(__file__).resolve()), "--dump", str(path)], env=env)
        payload = json.loads(path.read_text(encoding="utf-8"))
        oracle_path = Path(__file__).parent / "generators" / "occlusion_oracle.json"
        oracle_rows = json.loads(oracle_path.read_text(encoding="utf-8"))
        queues = defaultdict(list)
        for item in oracle_rows:
            queues[(item["group"], item["name"])].append(item)
        paired = []
        text_rows = []
        unmatched = []
        for row in payload:
            if row["kind"] == "text":
                text_rows.append(row)
                continue
            key = (row["group"], row["name"])
            if not queues[key]:
                unmatched.append(key)
                continue
            paired.append((row, queues[key].pop(0)))
        leftover = [key for key, queue in queues.items() if queue]
        if unmatched or leftover or len(paired) != 220:
            raise AssertionError(f"样例和 220 例对不上：多{unmatched[:5]} 少{leftover[:5]} 配上{len(paired)}")
        cls.paired = paired
        cls.text_rows = text_rows

    def test_reveal_cases_do_not_deliver_and_office_files_follow_the_edge_rule(self):
        problems = []
        reveal = 0
        leaks = 0
        office_deliver = 0
        office_names = []
        for row, oracle in self.paired:
            key = (row["group"], row["name"])
            expected = _expected(key, oracle)
            message = ""
            still = []
            try:
                out, _report, _ext = policy.export( _raw_of(row), ".pdf", _pdf_plan(row["box"], row["keep"]))
                decision = "deliver"
                still = [item for item in SECRETS if item in _text_of(out)]
            except engine.Rejected as exc:
                decision = "reject"
                message = str(exc)
            except Exception as exc:
                decision = "error"
                message = f"{type(exc).__name__}: {exc}"
            echoed = _echo(message)
            if echoed:
                problems.append(f"{row['name']} 报错回显了号码：{message[:160]}")
            if oracle["cohort"] == "reveal":
                reveal += 1
                if decision == "deliver":
                    leaks += 1
                    problems.append(f"漏脱 {row['group']} {row['name']} 副本仍有 {still}")
            if decision != expected:
                problems.append(
                    f"{row['group']} {row['name']} 期望{expected} 实际{decision} {message[:160]}"
                )
            if row["name"] == "正常-用户黑框盖住号码":
                if "盖住了" not in message or "方形" not in message:
                    problems.append(f"用户黑框的说明不对：{message}")
            if row["name"] == "正常-图章压住号码":
                if "盖住了" not in message or "图章" not in message:
                    problems.append(f"压住号码的图章应说明字形被盖住：{message}")
            if row["name"] == "攻击-黑方块透明度0.25":
                if "看不一致" not in message:
                    problems.append(f"25% 黑方块应说明两种渲染看不一致：{message}")
            if row["name"] == "线宽0黑方块整块框住":
                if "盖住了" not in message or "画面变了" in message:
                    problems.append(f"线宽 0 的说明不对：{message}")
            if row["name"] == "UserUnit框住被盖号码":
                if "盖住了" not in message or "可能切到字形" in message or "没有这块批注" in message:
                    problems.append(f"UserUnit 黑框的说明不对：{message}")
            if row["name"] == "UserUnit2框住被盖号码-不计误拒":
                if decision != "deliver" or any(item in still for item in SECRETS):
                    problems.append(f"UserUnit=2 框住号码应交付且号码消失：{decision} {still} {message[:120]}")
                elif "整理活动反馈" not in _text_of(out):
                    problems.append("UserUnit=2 副本没有留下保留句")
            if decision == "deliver" and _source_hides_phone(_raw_of(row)):
                leaks += 1
                problems.append(f"交付时画面上已经看不见号码：{row['group']} {row['name']}")
            if row["name"].startswith("正常-"):
                office_names.append(row["name"])
                if decision == "deliver":
                    office_deliver += 1
        office_note = "\n".join(problems[:40]) or "没有记录到被拒的办公样例"
        self.assertEqual(reveal, 152, "会露出内容的样例应当是 152 份")
        self.assertEqual(leaks, 0, office_note)
        self.assertEqual(
            office_deliver,
            10,
            "正常办公 12 份里应有 10 份交付。用户黑框，以及压住两个数字的图章，都拒绝。\n" + office_note,
        )
        self.assertEqual(len(office_names), 12)
        self.assertFalse(problems, office_note)

    def test_round7_text_variants_do_not_leave_the_number(self):
        self.assertGreaterEqual(len(self.text_rows), 4)
        for row in self.text_rows:
            with self.subTest(name=row["name"]):
                forged = row["name"] == "伪造标记不能原样交付"
                try:
                    out, _report, _ext = policy.export(row["body"].encode(), ".txt", _text_plan(row["terms"], row["keep"]))
                except engine.Rejected as exc:
                    message = str(exc)
                    for secret in SECRETS:
                        self.assertNotIn(secret, message)
                    if forged:
                        self.fail("正文里已有【已隐去1】时，应改用〔已处理A〕，而不是整单拒绝")
                    continue
                if not forged:
                    self.fail("另一种写法或连着的编号仍应拒绝，不能交付")
                text = out.decode()
                self.assertIn("〔已处理A〕", text)
                self.assertNotIn("联系人甲", text)
                for secret in SECRETS:
                    self.assertNotIn(secret, text)


def _joined_digits(text):
    return "".join(char for char in text if char.isdigit())


def _page_text(data):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _region_visible(image, box):
    clamped = pdf._clamp_pixel_box(box, image)
    if clamped is None:
        return False
    crop = image.convert("L").crop(clamped)
    low, high = crop.getextrema()
    data = crop.tobytes()
    mean = sum(data) / len(data)
    span = int(high - low)
    black = sum(value < 40 for value in data) / len(data)
    if span >= 40 and black < 0.85:
        return True
    return span >= 20 and 30 <= mean <= 230


def _digit_boxes(raw):
    size = formats.pdf_info(raw)[0]
    boxes = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        page = doc[0]
        for span in page.get_texttrace():
            for char in span["chars"]:
                if not chr(char[0]).isdigit():
                    continue
                box = pdf._to_pixel_box(fitz.Rect(char[3]), page, _ImageSize(size))
                if box:
                    boxes.append(box)
    return boxes


class DilutionOcclusionTests(unittest.TestCase):
    def test_disconnected_tiles_inside_a_readable_rect_are_refused(self):
        for name, kwargs in DILUTION_SPECS:
            with self.subTest(name=name):
                raw, box = dilution(**kwargs)
                with self.assertRaises(engine.Rejected) as caught:
                    policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
                message = str(caught.exception)
                self.assertNotIn(REVIEW_SECRET, message)
                self.assertNotIn(REVIEW_SECRET, _joined_digits(message))
                self.assertTrue(
                    any(token in message for token in ("盖住了", "没法对齐", "看不一致", "看不到这些字的边缘")),
                    message,
                )
                if kwargs["size"] >= 3 and kwargs["mode"] != "tight":
                    self.assertIn("盖住了", message)
                    self.assertIn("方形", message)

    def test_whole_rect_still_looks_readable_when_one_digit_is_covered(self):
        """整块矩形的存活率会被旁边的正文拉高。拒绝必须来自被盖住的那一个字形。"""
        for name, kwargs in (
            ("六行", dict(size=4, lines=6, mode="wide")),
            ("只盖一位", dict(size=4, lines=6, mode="one")),
        ):
            with self.subTest(name=name):
                raw, box = dilution(**kwargs)
                baseline = pdf.without_annotation_appearance(raw)
                source = formats.pdf_image(raw, 0).convert("L")
                base = formats.pdf_image(baseline, 0).convert("L")
                with fitz.open(stream=raw, filetype="pdf") as doc, fitz.open(stream=baseline, filetype="pdf") as stripped:
                    page = doc[0]
                    baseline_page = stripped[0]
                    mupdf_covered = pdf._mupdf_gray(page, source.size)
                    mupdf_base = pdf._mupdf_gray(baseline_page, source.size)
                    area = pdf._areas_to_judge(page)[0][0]
                    whole = pdf._sample_box(area, page, source)
                    self.assertEqual(pdf._judge_crop(base, source, whole), "readable")
                    self.assertEqual(pdf._judge_crop(mupdf_base, mupdf_covered, whole), "readable")
                    reason, _glyph_box = pdf._glyph_cover_reason(
                        baseline_page, page, area, base, source, mupdf_base, mupdf_covered,
                    )
                self.assertEqual(reason, "opaque")
                with self.assertRaises(engine.Rejected) as caught:
                    policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
                self.assertIn("盖住了", str(caught.exception))

    def test_tiles_outside_the_annotation_box_are_not_an_independent_leak(self):
        """外观画在批注矩形外面时，本轮的 12 像素跳过没有单独把藏住的号码交出去。

        这些小黑块落在外观框外，画面上的数字并没有被涂没。选区没框住号码时，文字层里还可以留下这串数字。
        """
        for name, kwargs in OUTSIDE_SPECS:
            with self.subTest(name=name):
                raw, box = dilution(**kwargs)
                source = formats.pdf_image(raw, 0)
                hidden = any(
                    not _region_visible(source, digit_box)
                    and pdf._clamp_pixel_box(digit_box, source) is not None
                    for digit_box in _digit_boxes(raw)
                )
                try:
                    out, _report, _ext = policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
                except engine.Rejected as exc:
                    self.assertNotIn(REVIEW_SECRET, str(exc))
                    continue
                self.assertFalse(hidden, f"{name} 画面上已经看不见数字，却交付了")
                self.assertIn(REVIEW_KEEP, _page_text(out))


class FloatUserUnitTests(unittest.TestCase):
    def test_float_xref_above_one_is_stored_and_below_one_is_not(self):
        for unit, kept in ((1.25, True), (1.5, True), (2.5, True), (2, True), (0.5, False)):
            with self.subTest(unit=unit):
                doc = fitz.open()
                page = doc.new_page()
                doc.xref_set_key(page.xref, "UserUnit", str(unit))
                kind, _value = doc.xref_get_key(page.xref, "UserUnit")
                saved = pdf._stored_user_unit(page)
                doc.close()
                if unit != int(unit):
                    self.assertEqual(kind, "float")
                if kept:
                    self.assertIsNotNone(saved)
                    self.assertAlmostEqual(float(saved), unit)
                else:
                    self.assertIsNone(saved)

    def test_fractional_user_unit_redacts_the_number_and_keeps_the_neighbor(self):
        for unit in (1.25, 1.5, 2.5):
            with self.subTest(unit=unit):
                raw, box = plain_phone(userunit=unit, cover=False)
                out, report, _ext = policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP, NEIGHBOR]))
                self.assertTrue(report["checks"]["selected_text_removed"])
                self.assertTrue(report["checks"]["outside_page_pixels_preserved"])
                text = _page_text(out)
                self.assertNotIn(REVIEW_SECRET, text)
                self.assertNotIn(REVIEW_SECRET, _joined_digits(text))
                self.assertIn(REVIEW_KEEP, text)
                self.assertIn(NEIGHBOR, text)
                source_size = formats.pdf_info(raw)[0]
                with fitz.open(stream=raw, filetype="pdf") as source_doc:
                    phone = source_doc[0].search_for(REVIEW_SECRET)[0]
                    phone_box = pdf._to_pixel_box(phone, source_doc[0], _ImageSize(source_size))
                output_image = formats.pdf_image(out, 0)
                self.assertFalse(_region_visible(output_image, phone_box))
                with fitz.open(stream=out, filetype="pdf") as opened:
                    page = opened[0]
                    kind, value = opened.xref_get_key(page.xref, "UserUnit")
                    self.assertIn(kind, ("float", "real", "int"))
                    self.assertAlmostEqual(float(value), unit)
                    neighbor = page.search_for(NEIGHBOR)[0]
                    neighbor_box = pdf._to_pixel_box(neighbor, page, _ImageSize(output_image.size))
                self.assertTrue(_region_visible(output_image, neighbor_box))

    def test_user_unit_below_one_still_refuses(self):
        raw, box = plain_phone(userunit=0.5, cover=False)
        with self.assertRaises(engine.Rejected) as caught:
            policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP, NEIGHBOR]))
        message = str(caught.exception)
        self.assertNotIn(REVIEW_SECRET, message)
        self.assertNotIn("盖住了", message)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        Path(sys.argv[2]).write_text(json.dumps(collect_cases(), ensure_ascii=False), encoding="utf-8")
    else:
        unittest.main()
