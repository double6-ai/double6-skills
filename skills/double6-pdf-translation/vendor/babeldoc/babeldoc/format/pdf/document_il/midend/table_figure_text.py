# Double6 Skills 维护版本（2026-10-18）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""表格与图内文字：节点内折行合并、紧凑标签的翻译范围、单行源基线。

三件事都只看源 PDF 的几何与文字本身，不按文档名或具体词表分支：

* ``merge_figure_node_lines``：同一填充节点（流程图/示意图方框）里同字体、同左缘、行距正常的
  连续单行，合成一个翻译单元。原先逐行成段，半数行被当作紧凑标签留英文。
* ``release_natural_compact_labels``：紧凑标签原本一律原样保留，用来保护图中的数据集名、方法名、
  型号。自然语言短语（含小写实词、功能词、冒号字段名、图表题注或多词标题式短语）改为正常翻译；
  单个首字母大写词只在与可翻译文字同栈/同行时随上下文翻译。含全大写缩写、数字、驼峰、URL
  或机构后缀而没有自然语言信号的标签继续原样保留。
* ``record_source_baselines``：给表格行一类单行段落记录原文基线（字形可见框下沿的中位数）。
  源字框下沿包含下伸部，按它回写会让整行下移约 0.3 em，压到下一行。
"""
from __future__ import annotations

import re
import statistics
import unicodedata

PASSTHROUGH_LABELS = {
    "compact_label", "code_label", "code_passthrough_label", "latex_structure_fragment",
    "cover_year", "year_label", "abandon",
}
ANCHOR_LABELS = {"fallback_line", "chart_label", "axis_label", "legend", "table_cell", "table_header"}
FUNCTION_WORDS = {
    "of", "and", "to", "by", "for", "the", "in", "on", "with", "that", "from", "per", "or", "but", "at", "as",
    "into", "over", "under", "between", "than", "via", "a", "an",
}
ORG_SUFFIX = re.compile(
    r"\b(?:Inc|Ltd|Corp|LLC|Labs?|University|Institute|College|Group|Company|GmbH|Univ)\b\.?")
# 小写点缩写（i.i.d.、non-i.i.d.、e.g.）是术语记号，译后常比格子宽得多，保持原样。
HARD_IDENTIFIER = re.compile(r"https?://|www\.|@|_|\\|[a-z][A-Z]|\(cid:\d+\)|(?<![A-Za-z])(?:[a-z]\.){2,}")
CAPTION = re.compile(r"^(?:fig(?:ure)?|table|tab|chart|exhibit)\.?\s*(?:[0-9]+|[IVXLC]+)\b", re.IGNORECASE)
TOKEN = re.compile(r"(?:[A-Za-z]\.){2,}|[A-Za-z]+(?:'[a-z]+)?|\d+")
DESCENDERS = set("gjpqyQJ")


def _text(finder, paragraph) -> str:
    # 按几何补空格的字符串（直接拼 char_unicode 会把「Fig. 2. Proposed Binary」拼成无空格串）。
    from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
    chars = list(_chars(finder, paragraph))
    text = get_char_unicode_string(chars) if chars else (paragraph.unicode or "")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _chars(finder, paragraph):
    for line in finder._paragraph_lines(paragraph):
        yield from line.pdf_character


def _dominant(finder, paragraph):
    sizes = {}
    for char in _chars(finder, paragraph):
        if not (char.char_unicode or "").strip() or char.pdf_style is None:
            continue
        key = (char.pdf_style.font_id, round(float(char.pdf_style.font_size or 0), 1))
        sizes[key] = sizes.get(key, 0) + 1
    if not sizes:
        return None, 0.0
    font_id, size = max(sizes, key=sizes.get)
    return font_id, size


def estimate_baseline(finder, paragraph):
    """单行段落的原文基线：主字号字母数字（不含下伸字母）可见框下沿的中位数。"""
    lines = finder._paragraph_lines(paragraph)
    if len(lines) != 1 or paragraph.box is None:
        return None
    _, size = _dominant(finder, paragraph)
    if not size:
        return None
    bottoms = []
    for char in lines[0].pdf_character:
        u = char.char_unicode or ""
        if len(u) != 1 or not u.isascii() or not u.isalnum() or u in DESCENDERS or char.visual_bbox is None:
            continue
        if abs(float(char.pdf_style.font_size or 0) - size) > 0.3:
            continue
        bottoms.append(char.visual_bbox.box.y)
    if len(bottoms) < 1:
        return None
    baseline = statistics.median(bottoms)
    if not paragraph.box.y - 0.01 <= baseline <= paragraph.box.y + 0.45 * size:
        return None
    return baseline


def record_source_baselines(finder, page, paragraphs) -> None:
    for paragraph in paragraphs:
        if (paragraph.layout_label or "") not in ANCHOR_LABELS or paragraph.vertical:
            continue
        baseline = estimate_baseline(finder, paragraph)
        if baseline is not None:
            paragraph.source_baseline = round(baseline, 3)


# ------------------------------------------------------------------ 图内节点

_RGB = re.compile(r"(?<![\d.])([\d.]+) ([\d.]+) ([\d.]+) (?:rg|scn|sc)\b")
_GRAY = re.compile(r"(?<![\d.])([\d.]+) g\b")
_CMYK = re.compile(r"(?<![\d.])([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) k\b")


def _is_coloured_fill(curve) -> bool:
    """有色（非白、非浅灰、非纯黑）填充：流程图节点。白色/浅灰底板（图表绘图区、图例框）不算。"""
    text = getattr(curve.graphic_state, "passthrough_per_char_instruction", "") or ""
    colours = [tuple(map(float, m)) for m in _RGB.findall(text)]
    colours += [(float(g),) * 3 for g in _GRAY.findall(text)]
    for c, m, y, k in (tuple(map(float, x)) for x in _CMYK.findall(text)):
        colours.append(((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)))
    return any(min(rgb) < 0.9 and max(rgb) > 0.05 for rgb in colours)


def figure_nodes(page):
    crop = page.cropbox.box if page.cropbox and page.cropbox.box else (page.mediabox.box if page.mediabox else None)
    if crop is None:
        return []
    page_area = max((crop.x2 - crop.x) * (crop.y2 - crop.y), 1.0)
    nodes = []
    for curve in page.pdf_curve or []:
        b = curve.box
        if not b or not curve.fill_background:
            continue
        w, h = b.x2 - b.x, b.y2 - b.y
        if w >= 40 and h >= 20 and w * h < 0.25 * page_area and _is_coloured_fill(curve):
            nodes.append(b)
    return nodes


def table_regions(page):
    return [l.box for l in page.page_layout or []
            if l.box is not None and (l.class_name or "").lower() in {"table", "table_body", "table_cell"}]


def _in_scope(finder, paragraph, nodes, tables) -> bool:
    """只在表格区域内、或填充节点内/紧贴节点上下的标签上放开翻译；图表绘图区与图例保持原行为。"""
    b = paragraph.box
    cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
    if any(t.x <= cx <= t.x2 and t.y <= cy <= t.y2 for t in tables):
        return True
    _, size = _dominant(finder, paragraph)
    pad = 0.8 * (size or 8.0)
    return any(n.x - 2 <= b.x and b.x2 <= n.x2 + 2 and max(n.y - b.y2, b.y - n.y2, 0.0) <= pad for n in nodes)

def _same_baseline_sibling(finder, paragraph, members, size):
    base = estimate_baseline(finder, paragraph)
    base = paragraph.box.y if base is None else base
    for other in members:
        if other is paragraph:
            continue
        other_base = estimate_baseline(finder, other)
        other_base = other.box.y if other_base is None else other_base
        if abs(other_base - base) < 0.3 * size and (other.box.x >= paragraph.box.x2 or other.box.x2 <= paragraph.box.x):
            return True
    return False


def merge_figure_node_lines(finder, page, paragraphs) -> list[str]:
    nodes = figure_nodes(page)
    merged_receipts = []
    used = set()
    for node in sorted(nodes, key=lambda b: (b.x2 - b.x) * (b.y2 - b.y)):
        members = [
            p for p in paragraphs
            if id(p) not in used and p.box is not None and not p.vertical
            and node.x - 2 <= p.box.x and p.box.x2 <= node.x2 + 2 and node.y - 2 <= p.box.y and p.box.y2 <= node.y2 + 2
            and len(finder._paragraph_lines(p)) == 1
        ]
        if len(members) < 2:
            continue
        for p in members:
            used.add(id(p))
        members.sort(key=lambda p: -p.box.y2)
        group = [members[0]]
        groups = []
        for current in members[1:]:
            last = group[-1]
            if _can_join(finder, last, current, members):
                group.append(current)
            else:
                groups.append(group)
                group = [current]
        groups.append(group)
        for group in groups:
            if len(group) < 2:
                continue
            head = group[0]
            for tail in group[1:]:
                head.pdf_paragraph_composition.extend(tail.pdf_paragraph_composition)
                tail.pdf_paragraph_composition = []
                paragraphs.remove(tail)
            boxes = [line.box for line in finder._paragraph_lines(head) if line.box is not None]
            head.box.x = min(b.x for b in boxes)
            head.box.y = min(b.y for b in boxes)
            head.box.x2 = max(b.x2 for b in boxes)
            head.box.y2 = max(b.y2 for b in boxes)
            finder.update_paragraph_data(head, update_unicode=True)
            merged_receipts.append(head.debug_id or "")
    return merged_receipts


def _can_join(finder, upper, lower, members) -> bool:
    font_a, size_a = _dominant(finder, upper)
    font_b, size_b = _dominant(finder, lower)
    if not size_a or font_a != font_b or abs(size_a - size_b) > 0.2:
        return False
    if (upper.layout_label or "") != (lower.layout_label or ""):
        return False
    if abs(upper.box.x - lower.box.x) > 1.5:
        return False
    upper_text = _text(finder, upper)
    if not upper_text or upper_text.endswith((":", ".", "：", "。")):
        return False
    base_a = estimate_baseline(finder, upper)
    base_b = estimate_baseline(finder, lower)
    base_a = upper.box.y if base_a is None else base_a
    base_b = lower.box.y if base_b is None else base_b
    pitch = base_a - base_b
    if not 0.9 * size_a <= pitch <= 1.45 * size_a:
        return False
    return not (_same_baseline_sibling(finder, upper, members, size_a) or _same_baseline_sibling(finder, lower, members, size_a))


# ------------------------------------------------------------------ 紧凑标签

def _tokens(text):
    return TOKEN.findall(text)


def is_natural_label(text: str) -> bool:
    text = text.strip()
    if not text or ORG_SUFFIX.search(text) or HARD_IDENTIFIER.search(text):
        return False
    if CAPTION.match(text):
        return True
    tokens = _tokens(text)
    words = [t for t in tokens if t[0].isalpha()]
    if not words:
        return False
    if any(w.islower() and len(w) >= 3 for w in words if "." not in w):
        return True
    if any(w.lower() in FUNCTION_WORDS for w in words if "." not in w):
        return True
    has_digit = any(t.isdigit() for t in tokens) or bool(re.search(r"\d", text))
    acronyms = [w for w in words if "." not in w and len(w) >= 2 and w.isupper()]
    if text.endswith(":") and not has_digit and any(len(w) >= 3 and not w.isupper() for w in words):
        return True
    if len(words) >= 2 and not has_digit and not acronyms and all(w[0].isupper() for w in words):
        return True
    return False


def is_context_promotable(text: str) -> bool:
    """单个（或含缩写的）首字母大写词：本身不足以判定，需看同栈/同行文字。"""
    text = text.strip()
    if not text or ORG_SUFFIX.search(text) or HARD_IDENTIFIER.search(text) or re.search(r"\d", text):
        return False
    words = [t for t in _tokens(text) if t[0].isalpha()]
    return any(len(w) >= 3 and not w.isupper() and "." not in w for w in words)


def _is_translatable(finder, paragraph) -> bool:
    from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_pure_numeric_paragraph
    if (paragraph.layout_label or "") in PASSTHROUGH_LABELS:
        return False
    text = _text(finder, paragraph)
    if not re.search(r"[A-Za-z]{3,}", text):
        return False
    return not is_pure_numeric_paragraph(paragraph)


def _neighbours(finder, a, b) -> bool:
    _, size_a = _dominant(finder, a)
    _, size_b = _dominant(finder, b)
    if not size_a or not size_b or not 0.75 <= size_a / size_b <= 1.34:
        return False
    fs = max(size_a, size_b)
    ba, bb = a.box, b.box
    vertical_gap = max(bb.y - ba.y2, ba.y - bb.y2, 0.0)
    left_close = abs(ba.x - bb.x) <= 2.5 * fs
    centre_close = abs((ba.x + ba.x2) / 2 - (bb.x + bb.x2) / 2) <= 2.5 * fs
    horizontal_overlap = min(ba.x2, bb.x2) - max(ba.x, bb.x) > -0.5
    if vertical_gap <= 0.8 * fs and (left_close or centre_close) and horizontal_overlap:
        return True
    centre_dy = abs((ba.y + ba.y2) / 2 - (bb.y + bb.y2) / 2)
    horizontal_gap = max(bb.x - ba.x2, ba.x - bb.x2, 0.0)
    return centre_dy <= 0.6 * fs and horizontal_gap <= 4 * fs


def release_natural_compact_labels(finder, page, paragraphs, prior_labels) -> list[str]:
    released = []
    pending = []
    nodes = figure_nodes(page)
    tables = table_regions(page)
    for paragraph in paragraphs:
        if paragraph.layout_label != "compact_label" or id(paragraph) not in prior_labels or paragraph.box is None:
            continue
        text = _text(finder, paragraph)
        if CAPTION.match(text) and is_natural_label(text):
            paragraph.layout_label = prior_labels[id(paragraph)] or "fallback_line"
            released.append(text)
            continue
        if not _in_scope(finder, paragraph, nodes, tables):
            continue
        if is_natural_label(text):
            paragraph.layout_label = prior_labels[id(paragraph)] or "fallback_line"
            released.append(text)
        elif is_context_promotable(text):
            pending.append(paragraph)
    anchors = [p for p in paragraphs if p.box is not None and _is_translatable(finder, p)]
    changed = True
    while changed and pending:
        changed = False
        for paragraph in list(pending):
            if paragraph.box is None:
                continue
            if any(_neighbours(finder, paragraph, other) for other in anchors if other is not paragraph):
                paragraph.layout_label = prior_labels[id(paragraph)] or "fallback_line"
                pending.remove(paragraph)
                anchors.append(paragraph)
                released.append(_text(finder, paragraph))
                changed = True
    return released
