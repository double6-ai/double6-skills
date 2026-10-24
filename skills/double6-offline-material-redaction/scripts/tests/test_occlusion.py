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
from PIL import Image
import output_policy as policy
import pdf_preserve as pdf
import pymupdf as fitz
from generators.glyph_attacks import attack_cases
from generators.glyph_attacks import contrast_page
from generators.glyph_attacks import strikeout_cut_through_glyph
from generators.glyph_attacks import strikeout_extends_outside
from generators.glyph_attacks import strikeout_on_selected_word
from generators.glyph_attacks import strikeout_rewrites_outside_digit
from generators.review_cases import DILUTION_SPECS
from generators.review_cases import KEEP as REVIEW_KEEP
from generators.review_cases import NEIGHBOR
from generators.review_cases import OUTSIDE_SPECS
from generators.review_cases import SECRET as REVIEW_SECRET
from generators.review_cases import dilution
from generators.office_cases import office_samples
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
# 选区外的字前景被改掉就拒绝。画在被选词上、整框落在选区里的删除线会随涂黑去掉。
# 下划线和波浪线的笔画落在保留句的字形框里，并且跨过这个字的局部中点，同样拒绝。
ADDED_INK_STROKE = {
    ("office", "正常-红圈圈注"),
    ("office", "正常-下划线"),
    ("office", "正常-波浪线"),
    ("round7:expect-reject-visible", "普通删除线"),
    ("round7:expect-reject-visible", "普通下划线"),
    ("round7:expect-reject-visible", "普通波浪线"),
    ("author", "普通删除线"),
    ("author", "普通下划线"),
    ("author", "普通波浪线"),
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
    if key in ADDED_INK_STROKE or key in PER_GLYPH_COVER or key in STRICTER or oracle["d1"] == "reject" or oracle["cohort"] == "reveal":
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
                if "图章" not in message or ("盖住了" not in message and "接近字迹的深色" not in message):
                    problems.append(f"压住号码的图章应说明字被盖住或被改掉：{message}")
            if row["name"] == "正常-红圈圈注":
                if "接近字迹的深色" not in message:
                    problems.append(f"{row['name']} 应说明空白被涂成接近字迹：{message}")
            if row["name"] == "正常-删除线在被选词上":
                if decision != "deliver":
                    problems.append(f"画在被选词上的删除线应随涂黑去掉：{message}")
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
            7,
            "正常办公 12 份里应有 7 份交付。用户黑框、压住数字的图章、压到选区外字上的红圈、下划线和波浪线都拒绝。高亮和画在被选词上的删除线可以去掉。\n" + office_note,
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


def _source_digits_visible(raw):
    image = formats.pdf_image(raw, 0)
    return any(_region_visible(image, box) for box in _digit_boxes(raw))


class ExitCleanupTests(unittest.TestCase):
    def test_sys_exit_runs_earlier_hooks_and_flushes_small_files(self):
        directory = tempfile.mkdtemp(prefix="redaction-exit-")
        early = os.path.join(directory, "early.txt")
        pending = os.path.join(directory, "pending.bin")
        script = (
            "import atexit, sys\n"
            "def early():\n"
            "    open(%r, 'w', encoding='utf-8').write('early')\n"
            "atexit.register(early)\n"
            "import pdf_preserve\n"
            "pdf_preserve.backend()\n"
            "handle = open(%r, 'wb')\n"
            "handle.write(b'HELLO-NOT-FLUSHED')\n"
            "sys.exit(7)\n"
        ) % (early, pending)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual(proc.returncode, 7, proc.stderr.decode("utf-8", "replace")[-400:])
        self.assertEqual(Path(early).read_text(encoding="utf-8"), "early")
        self.assertEqual(Path(pending).read_bytes(), b"HELLO-NOT-FLUSHED")

    def test_uncaught_error_is_not_reported_as_success(self):
        script = "import pdf_preserve\npdf_preserve.backend()\nraise RuntimeError('boom')\n"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"RuntimeError", proc.stderr)

    def test_sys_exit_text_is_written_before_the_hard_exit(self):
        script = "import pdf_preserve\npdf_preserve.backend()\nimport sys\nsys.exit('boom')\n"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"boom", proc.stderr)


class AddedInkAttackTests(unittest.TestCase):
    def test_only_a_glyph_fully_inside_one_selection_skips_added_ink(self):
        self.assertTrue(pdf._glyph_inside_selection((10, 20, 30, 40), [(10, 20, 30, 40)]))
        self.assertTrue(pdf._glyph_inside_selection((12, 22, 28, 38), [(0, 0, 40, 50), (100, 100, 120, 130)]))
        self.assertFalse(pdf._glyph_inside_selection((8, 22, 28, 38), [(10, 20, 30, 40)]))
        self.assertFalse(pdf._glyph_inside_selection((10, 20, 36, 40), [(10, 20, 30, 40)]))
        # 两个选区拼起来能罩住，但没有一个单独罩住。
        self.assertFalse(pdf._glyph_inside_selection((0, 0, 40, 10), [(0, 0, 20, 10), (20, 0, 40, 10)]))
        self.assertFalse(pdf._glyph_inside_selection(None, [(0, 0, 10, 10)]))
        self.assertFalse(pdf._glyph_inside_selection((0, 0, 4, 4), []))
        self.assertFalse(pdf._pixel_box_inside((0, 0, 4, 4), None))

    def test_strikeout_inside_the_selection_can_be_removed_and_outside_glyphs_cannot(self):
        raw, box = strikeout_on_selected_word()
        out, _report, _ext = policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
        text = _page_text(out)
        self.assertIn(REVIEW_KEEP, text)
        self.assertNotIn("DELETEME", text)
        self.assertIn(REVIEW_SECRET, text)
        for builder in (strikeout_extends_outside, strikeout_rewrites_outside_digit, strikeout_cut_through_glyph):
            with self.subTest(builder=builder.__name__):
                raw, box = builder()
                with self.assertRaises(engine.Rejected) as caught:
                    policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
                message = str(caught.exception)
                self.assertNotIn(REVIEW_SECRET, message)
                self.assertNotIn(REVIEW_SECRET, _joined_digits(message))
                self.assertTrue(
                    "接近字迹的深色" in message or "盖住了" in message or "没法对齐" in message,
                    message,
                )
                if builder is strikeout_rewrites_outside_digit:
                    self.assertIn("接近字迹的深色", message)
                    self.assertIn("删除线", message)

    def test_added_ink_thresholds_stay_written_down(self):
        # 中点由每个字自己的底色和字迹色决定，不再用 176/96 这种固定亮度。
        self.assertEqual(pdf._CONTRAST_BG_PERCENT, 75)
        self.assertEqual(pdf._CONTRAST_INK_PERCENT, 10)
        self.assertEqual(pdf._CONTRAST_MIN, 40)
        self.assertEqual(pdf._CONTRAST_MOVE_NUM, 1)
        self.assertEqual(pdf._CONTRAST_MOVE_DEN, 5)
        self.assertEqual(pdf._MASK_DIFF_MIN, 6)
        self.assertEqual(pdf._GLYPH_INK_MARGIN, 2)
        self.assertEqual(pdf._MASK_SHIFT_RADIUS, 2)
        self.assertEqual(pdf._DARKEN_NUM, 1)
        self.assertEqual(pdf._DARKEN_DEN, 5)
        self.assertFalse(hasattr(pdf, "_ADDED_INK_BRIGHT"))

    def _paper_darken_count(self, drop, ink):
        """细笔画：8 个黑像素，10 分位仍是浅色。纸面变暗 drop，看贴边忽略之后还剩多少。"""
        side = 20
        base = Image.new("L", (side, side), 255)
        covered = Image.new("L", (side, side), 255 - drop)
        for index in range(8):
            base.putpixel((0, index), 0)
            covered.putpixel((0, index), 0)
        return pdf._background_darken_count(base, covered, (0, 0, side, side), 255, ink)

    def _darken_on(self, raw, glyph=None):
        """带上 2 像素贴边忽略之后，每个字形的变暗计数和掩码计数。"""
        baseline_raw = pdf.without_annotation_appearance(raw)
        source = formats.pdf_image(raw, 0).convert("L")
        base = formats.pdf_image(baseline_raw, 0).convert("L")
        rows = []
        with fitz.open(stream=raw, filetype="pdf") as doc, fitz.open(stream=baseline_raw, filetype="pdf") as stripped:
            page = doc[0]
            baseline_page = stripped[0]
            mupdf_covered = pdf._mupdf_gray(page, source.size)
            mupdf_base = pdf._mupdf_gray(baseline_page, source.size)
            area = pdf._areas_to_judge(page)[0][0]
            for text, rect in pdf._each_glyph(baseline_page, area):
                if glyph is not None and text != glyph:
                    continue
                box = pdf._to_pixel_box(rect, page, source)
                grown = pdf._grow_pixel_box(box, source, pdf._GLYPH_INK_MARGIN)
                left_level = pdf._local_threshold(base, box)
                right_level = pdf._local_threshold(mupdf_base, box)
                self.assertIsNotNone(left_level, text)
                self.assertIsNotNone(right_level, text)
                rows.append((
                    text,
                    pdf._background_darken_count(base, source, grown, left_level[0], left_level[1]),
                    pdf._background_darken_count(mupdf_base, mupdf_covered, grown, right_level[0], right_level[1]),
                    pdf._mask_change_count(base, source, grown, left_level[0], left_level[1]),
                    pdf._mask_change_count(mupdf_base, mupdf_covered, grown, right_level[0], right_level[1]),
                ))
        return rows

    def test_translucent_seal_cannot_hide_inside_the_two_pixel_halo(self):
        """0.35 和 0.45 的开口封条停在中点以上。贴边 2 像素忽略之后，变暗计数仍要达到 6。"""
        for opacity in (0.35, 0.45):
            raw, box = contrast_page(gray=0, opacity=opacity, blend=True)
            counted = [row for row in self._darken_on(raw, glyph="3")]
            self.assertTrue(counted, opacity)
            for text, left, right, left_mask, right_mask in counted:
                self.assertGreaterEqual(
                    left,
                    6,
                    (opacity, text, left, right, left_mask, right_mask),
                )
                self.assertGreaterEqual(
                    right,
                    6,
                    (opacity, text, left, right, left_mask, right_mask),
                )
            with self.assertRaises(engine.Rejected) as caught:
                policy.export(raw, ".pdf", _pdf_plan(box, [REVIEW_KEEP]))
            message = str(caught.exception)
            self.assertIn("接近字迹的深色", message)
            self.assertNotIn(REVIEW_SECRET, message)

    def test_office_highlight_darkening_stays_under_the_fraction(self):
        samples = {item["name"]: item for item in office_samples()}
        for name in ("正常-黄色高亮在保留句", "正常-黄色高亮压在号码上"):
            sample = samples[name]
            for text, left, right, left_mask, right_mask in self._darken_on(sample["raw"]):
                self.assertLess(left, 6, (name, text, left, right, left_mask, right_mask))
                self.assertLess(right, 6, (name, text, left, right, left_mask, right_mask))
            out, _report, _ext = policy.export(sample["raw"], ".pdf", _pdf_plan(sample["box"], [sample["keep"]]))
            self.assertIn(sample["keep"], _page_text(out))
        self.assertEqual(self._paper_darken_count(drop=29, ink=120), 0)
        self.assertGreaterEqual(self._paper_darken_count(drop=63, ink=120), 6)
        strike_raw, strike_box = strikeout_on_selected_word()
        out, _report, _ext = policy.export(strike_raw, ".pdf", _pdf_plan(strike_box, [REVIEW_KEEP]))
        text = _page_text(out)
        self.assertIn(REVIEW_KEEP, text)
        self.assertNotIn("DELETEME", text)

    def test_review_stroke_samples_and_the_hairline_are_refused(self):
        rows = attack_cases()
        names = [row["name"] for row in rows]
        self.assertEqual(len(names), len(set(names)))
        for required in (
            "改字-3左侧封口",
            "改字-1加顶横",
            "改字-填孔",
            "改字-封口加顶横再填孔",
            "只涂内部留边缘",
            "改字-细线封口",
            "只涂字形中心",
            "字间黑块",
            "框外-4pt黑块",
            "框外-整字黑块",
            "旧-浅色字-0.985",
            "真半透明0.25",
            "真半透明0.35",
            "真半透明0.45",
            "真半透明0.50",
            "真半透明0.55",
            "半透明灰竖条",
            "半透明红竖条",
            "整页灰底半透明黑竖条",
            "整页灰底半透明黑竖条0.25",
        ):
            self.assertIn(required, names)
        self.assertGreaterEqual(len(rows), 89)
        for row in rows:
            with self.subTest(name=row["name"]):
                self._check(row)

    def _check(self, row):
        try:
            out, _report, _ext = policy.export(row["raw"], ".pdf", _pdf_plan(row["box"], row["keep"]))
        except engine.Rejected as exc:
            message = str(exc)
            self.assertNotIn(REVIEW_SECRET, message)
            self.assertNotIn(REVIEW_SECRET, _joined_digits(message))
            expect = row["expect"]
            if expect == "tamper":
                self.assertIn("接近字迹的深色", message)
            elif expect == "cover":
                self.assertIn("盖住了", message)
            elif expect == "later-fill":
                # 画在字后面的整页铺色，要么在打开时就因后绘制挡住文字而停止，要么在批注复检里算线条或图片。
                self.assertTrue("线条或图片" in message or "后绘制" in message, message)
            elif expect == "refuse":
                # 只要拒绝。Windows 上错位黑块会说两种渲染看不一致，仍然不算放行。
                self.assertTrue(
                    any(
                        part in message
                        for part in ("盖住了", "接近字迹的深色", "看不一致", "没法对齐", "线条或图片")
                    ),
                    message,
                )
            elif expect == "invalid":
                self.assertIn("没法对齐", message)
            elif expect == "crop-rotation":
                self.assertIn("裁剪框和旋转", message)
            elif expect == "userunit-low":
                self.assertIn("可能切到字形", message)
                self.assertNotIn("盖住了", message)
            elif expect == "invisible":
                self.assertIn("不可见", message)
            else:
                self.fail(f"应交付，实际拒绝：{message[:180]}")
            return
        text = _page_text(out)
        self.assertIn(REVIEW_KEEP, text)
        expect = row["expect"]
        if expect == "redact":
            self.assertNotIn(REVIEW_SECRET, text)
            self.assertNotIn(REVIEW_SECRET, _joined_digits(text))
            self.assertIn(NEIGHBOR, text)
            source_size = formats.pdf_info(row["raw"])[0]
            with fitz.open(stream=row["raw"], filetype="pdf") as source_doc:
                phone = source_doc[0].search_for(REVIEW_SECRET)[0]
                phone_box = pdf._to_pixel_box(phone, source_doc[0], _ImageSize(source_size))
            self.assertFalse(_region_visible(formats.pdf_image(out, 0), phone_box))
        elif expect == "visible":
            self.assertTrue(_source_digits_visible(row["raw"]))
        elif expect == "aside":
            self.assertIn(REVIEW_KEEP, text)
        elif expect == "light":
            self.assertIn(REVIEW_SECRET, text)
        else:
            self.fail("应拒绝，实际交付了")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        Path(sys.argv[2]).write_text(json.dumps(collect_cases(), ensure_ascii=False), encoding="utf-8")
    else:
        unittest.main()
