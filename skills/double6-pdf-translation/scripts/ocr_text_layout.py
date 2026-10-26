# SPDX-License-Identifier: AGPL-3.0-only
"""将已通过扫描准入的 OCR 行绑定到后端字符，保留段落和阅读顺序。

只由 scanned_ocr 工作流传入逐 SHA 核实的清单；原生页不使用此规则。
扫描准入仍先拒绝公式、表格和不可靠识别。这里修复版面模型对普通 OCR 正文的误分，
不对未经准入的图片推断结构，也不恢复被拒绝的页面。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from pathlib import Path

ENV = "PAPER_TRANSLATION_OCR_LAYOUT_REF"


def join_wrapped_ocr_groups(lines):
    """只接回同栏、连续行距、无新缩进且上一行显然未结束的 OCR 段落碎片。"""
    grouped = {}
    for line in lines:
        grouped.setdefault(tuple(line['paragraph']), []).append(line)
    result = []
    previous = []
    owner = None
    for key, members in grouped.items():
        join = False
        if previous:
            a, b = previous[-1], members[0]
            ax0, ay0, ax1, ay1 = a['bbox_px']
            bx0, by0, bx1, by1 = b['bbox_px']
            h = statistics.median(l['bbox_px'][3] - l['bbox_px'][1] for l in previous)
            left = statistics.median(l['bbox_px'][0] for l in previous)
            right = max(l['bbox_px'][2] for l in previous)
            letters = ''.join(c for l in previous for c in l['text'] if c.isalpha())
            next_letters = ''.join(c for l in members for c in l['text'] if c.isalpha())
            join = (h > 0 and letters and not letters.isupper() and next_letters and not next_letters.isupper()
                    and not re.search(r'[.!?。！？:：][\"\u2019\u201d)]*$', a['text'].rstrip())
                    and -.3 * h <= by0 - ay1 <= 1.2 * h
                    and .7 * h <= by1 - by0 <= 1.3 * h
                    and abs(bx0 - left) <= (h if b['text'].lstrip().startswith(('‘', '“', "'", '"')) else .65 * h)
                    and ax1 - ax0 >= .75 * (right - left)
                    and min(ax1, bx1) - max(ax0, bx0) >= .6 * min(ax1 - ax0, bx1 - bx0))
        if not join:
            owner, previous = key, []
        previous.extend(members)
        result.extend({**line, 'paragraph': owner} for line in members)
    return result


def bind_ocr_layout(page, characters, layout_type):
    reference = os.environ.get(ENV)
    if not reference:
        return None
    reference = json.loads(reference)
    path = Path(reference["path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("ocr_layout_manifest_changed")
    manifest = json.loads(raw)
    if manifest.get("status") != "ok" or not manifest.get("reconstructed_source"):
        raise ValueError("ocr_layout_manifest_not_admitted")
    record = next((r for r in manifest["pages"] if r["page"] == page.page_number + 1), None)
    if record is None:
        raise ValueError("ocr_layout_page_missing")
    if record["kind"] != "scanned":
        return None
    lines = record.get("text_lines", [])
    if record.get("text_lines_ref"):
        line_ref = record["text_lines_ref"]
        line_bytes = Path(line_ref["path"]).read_bytes()
        if hashlib.sha256(line_bytes).hexdigest() != line_ref["sha256"]:
            raise ValueError("ocr_layout_lines_changed")
        lines = json.loads(line_bytes)
    if not lines:
        raise ValueError("ocr_layout_lines_missing")
    # 兼容旧识别明细中“高置信行在前、准入的低置信行在后”的存储顺序。
    lines = sorted(lines, key=lambda line: (tuple(line['paragraph']), line['bbox_px'][1], line['bbox_px'][0]))
    lines = join_wrapped_ocr_groups(lines)
    scale = 72 / manifest["render_dpi"]
    width, height = [v * scale for v in record["background"]["size_px"]]
    box = page.cropbox.box if page.cropbox else page.mediabox.box
    if abs(box.x2 - box.x - width) > .5 or abs(box.y2 - box.y - height) > .5:
        raise ValueError("ocr_layout_page_geometry_changed")
    groups = {}
    geometry = []
    for index, line in enumerate(lines):
        key = tuple(line["paragraph"])
        groups.setdefault(key, []).append(line["text"])
        x0, y0, x1, y1 = [v * scale for v in line["bbox_px"]]
        geometry.append((key, index, x0, y0, x1, y1))
    layouts = {}
    for n, (key, texts) in enumerate(groups.items()):
        text = " ".join(texts)
        letters = "".join(c for c in text if c.isalpha())
        heading = bool(letters) and letters.isupper() and len(text) <= 180
        layout = layout_type(1_000_000 + n, "title" if heading else "plain text")
        layout.ocr_bound = True
        layouts[key] = layout
    assigned = []
    for char in characters:
        b = char.visual_bbox.box
        cx, cy = (b.x + b.x2) / 2, height - (b.y + b.y2) / 2
        candidates = []
        for key, index, x0, y0, x1, y1 in geometry:
            h = max(y1 - y0, 1)
            if x0 - h <= cx <= x1 + h and y0 - .65 * h <= cy <= y1 + .65 * h:
                score = abs(cy - (y0 + y1) / 2) / h + max(x0 - cx, cx - x1, 0) / h
                candidates.append((score, index, key))
        if not candidates:
            raise ValueError("ocr_layout_character_unbound")
        _, index, key = min(candidates)
        assigned.append((index, b.x, char, layouts[key]))
    # 以已核实 OCR 行的次序为准；模型框不能把同一行的末尾移到页尾。
    assigned.sort(key=lambda item: (item[0], item[1]))
    characters[:] = [item[2] for item in assigned]
    # 准入已经拒绝真实公式；避免模型的假公式框把正文中的几个词抽离。
    for layout in page.page_layout:
        if layout.class_name in {"formula", "isolate_formula"}:
            layout.class_name = "plain text"
    return [item[3] for item in assigned]


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由已绑定扫描清单的段落解析器调用。"
