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
    if key in STRICTER or oracle["d1"] == "reject" or oracle["cohort"] == "reveal":
        return "reject"
    return "deliver"


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
        self.assertEqual(office_deliver, 11, "正常办公 12 份里应有 11 份交付，用户黑框拒绝\n" + office_note)
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


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        Path(sys.argv[2]).write_text(json.dumps(collect_cases(), ensure_ascii=False), encoding="utf-8")
    else:
        unittest.main()
