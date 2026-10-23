# Double6 Skills 维护版本（2026-10-23）：新增模块，见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""同一物理行不被版面框切碎；表格行只在有可信列证据的列间空白处拆成单元格。

两件事都只看源 PDF 的字符几何与版面检测框，不按文档名或词表分支：

* ``unify_line_layouts``：版面模型给出的文字框常比实际行窄几个字（框在缩小的页面图上检测），
  行首/行尾越出框的字符只落在 ``fallback_line``（按字符几何聚出的物理行）里，于是同一行被拆成
  "The Arti" / 正文 / "t." 三段，两端碎片被当作紧凑标签原样保留。两个同级文字框重叠时，
  旧逻辑按 R-tree 返回顺序打破平局，同一行也会被拆到两个框里（表目录末行被切出去、缩成极小字号，
  其余三行因此凑不够目录行数而并成一段）。这里按物理行统一归属：
  只在整行字符都已归入正文类文字框或该行自身的 ``fallback_line`` 时处理；
  有正文框完整包住整行就归它，否则整行只碰到唯一一个正文框且该框在纵向上覆盖行高的大部分时归它。
  两种情况都要求同一行内不同归属的相邻字符之间是连续文字（间距小于 ``CONTINUOUS_GAP`` 个字号），
  且行碰到的正文框之间没有横向分离（分栏）；隔着栏间空白的字不合并。
  嵌套的同类正文框只有在"同一文字流的重复检测"证据齐全时才把内框字符归外框：内框横向覆盖外框大部分、
  外框里没有与内框并排的其他正文框（分栏）、且至少一条物理行连续地跨过内框左右边缘（内框把行截断）。
  外框只是把几栏一起框住时不合并，各栏保持各自的段落与阅读顺序。
  表格单元格、页眉页脚、图内文字、公式等其他角色一律不动。
* ``split_table_rows_at_column_gutters``：表格区域内，行聚类会把字距较小的表头整行聚成一个
  ``fallback_line``，译后整行左对齐，和下面各列错位。全表共有的空白本身不算列证据（单列单元格里的
  词间空白也会对齐）；只在该空白另有可信列结构时才拆：同表某一行在这里已经是两个独立段落、
  有竖直表格线穿过、有两个单元格框在这里分界，或同表某一数据行的两个相邻值记号（数字、布尔量等，
  ``VALUE_TOKEN``）在这里分开、且右侧的值与另一行的片段在同一列锚点上（左边、右边或中线相差 ≤2 pt）。
  版面检测的单元格框是可信结构：落在单元格框里的段落不拆，单元格框横跨的空白不是列边界。
"""
from __future__ import annotations

import copy
import re

BODY_LABELS = frozenset({
    "plain text", "text", "title", "paragraph_title", "abstract", "content", "doc_title",
    "figure_caption", "table_caption", "figure_title", "table_title", "chart_title", "paragraph",
    "caption", "list_item", "footnote", "table_footnote", "tiny text", "paragraph_hybrid",
    "caption_hybrid", "title_hybrid", "list_item_hybrid", "footnote_hybrid",
})
TABLE_LAYOUTS = frozenset({"table", "table_body"})
CELL_LABELS = frozenset({"table_cell", "wired_table_cell", "wireless_table_cell", "table_cell_hybrid"})
TABLE_ROW_LABELS = frozenset({"fallback_line", "plain text", "text", "table_text"}) | CELL_LABELS
# 行的纵向覆盖率：框只在横向上截短时，它在纵向上覆盖整行。
MIN_VERTICAL_COVER = 0.6
CONTAIN_TOLERANCE = 1.5
# 同一行里归属不同的相邻字符，间距小于这么多个字号才算同一段连续文字（栏间空白远大于它）。
CONTINUOUS_GAP = 1.5
# 数据单元格里的“值”记号：数字（含正负号、小数、千分位、百分号、科学计数、括号、显著性星号）、布尔字面量与常见占位符号。
# 两个相邻的值记号之间的空白是值与值的分界，不是词间空白；“New York”这类词与词的空白不算。
VALUE_TOKEN = re.compile(
    r"[(\[]?[+\-\u2212\u2013\u00b1]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?:[eE][+\-\u2212]?\d+)?%?[)\]]?\**"
    r"|(?i:true|false)|[\u2014\u2013\-\u2713\u2717\u00d7]|(?i:n/?a|nan)")
# 列锚点对齐：值记号与另一行的片段左边、右边或中线相差不超过这么多 pt。
ANCHOR_TOLERANCE = 2.0
# 嵌套同类框被当作重复检测时，内框至少覆盖外框宽度的这个比例。
MIN_DUPLICATE_WIDTH = 0.6


def _box_of(chars):
    boxes = [c.visual_bbox.box for c in chars]
    return (min(b.x for b in boxes), min(b.y for b in boxes), max(b.x2 for b in boxes), max(b.y2 for b in boxes))


def _vertical_cover(line, box) -> float:
    height = line[3] - line[1]
    if height <= 0:
        return 0.0
    return max(0.0, min(line[3], box.y2) - max(line[1], box.y)) / height


def _contains(box, line) -> bool:
    t = CONTAIN_TOLERANCE
    return box.x - t <= line[0] and line[2] <= box.x2 + t and box.y - t <= line[1] and line[3] <= box.y2 + t


def _line_of(char, layout_index, layout_map):
    """字符所在的物理行（``fallback_line``）：取包住字符中心的最小那一条。"""
    b = char.visual_bbox.box
    cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
    best = None
    for i in layout_index.intersection((cx, cy, cx, cy)):
        layout = layout_map[i]
        if layout.class_name != "fallback_line" or layout.box is None:
            continue
        lb = layout.box
        if not (lb.x <= cx <= lb.x2 and lb.y <= cy <= lb.y2):
            continue
        area = (lb.x2 - lb.x) * (lb.y2 - lb.y)
        if best is None or area < best[0]:
            best = (area, layout)
    return best[1] if best else None


def _line_groups(chars, layout_index, layout_map):
    groups: dict[int, list[int]] = {}
    for index, char in enumerate(chars):
        if char.visual_bbox is None or char.visual_bbox.box is None:
            continue
        line = _line_of(char, layout_index, layout_map)
        if line is not None:
            groups.setdefault(line.id, []).append(index)
    return groups


def _center(char):
    b = char.visual_bbox.box
    return (b.x + b.x2) / 2, (b.y + b.y2) / 2


def _inside(box, point) -> bool:
    return box.x <= point[0] <= box.x2 and box.y <= point[1] <= box.y2


def _h_disjoint(a, b) -> bool:
    return a.x2 <= b.x or b.x2 <= a.x


def _continuous(member_chars, keys, is_space) -> bool:
    """同一行按 x 排序后，归属（``keys``）不同的相邻实字之间都必须是连续文字间距。"""
    pairs = sorted(((c, k) for c, k in zip(member_chars, keys) if not is_space(c)), key=lambda p: p[0].visual_bbox.box.x)
    size = _font_size([c for c, _ in pairs])
    if size <= 0:
        return False
    for (a, ka), (b, kb) in zip(pairs, pairs[1:]):
        if ka != kb and b.visual_bbox.box.x - a.visual_bbox.box.x2 >= CONTINUOUS_GAP * size:
            return False
    return True


def unify_line_layouts(chars, char_layouts, layout_index, layout_map, layout_type, is_space) -> int:
    """就地改写 ``char_layouts``，返回被改归属的字符数。``layout_type`` 为 layout_helper.Layout。"""
    by_id = {layout.id: layout for layout in layout_map.values()}
    groups = _line_groups(chars, layout_index, layout_map)
    changed = _prefer_outer_duplicates(chars, char_layouts, by_id, layout_type, groups, is_space)
    for line_id, members in groups.items():
        if len(members) < 2:
            continue
        member_chars = [chars[i] for i in members]
        if len({c.xobj_id for c in member_chars}) != 1 or any(c.vertical for c in member_chars):
            continue
        layouts = [char_layouts[i] for i in members]
        if any(layout is None for layout in layouts):
            continue
        if any(layout.name != "fallback_line" and layout.name not in BODY_LABELS for layout in layouts):
            continue
        if any(layout.name == "fallback_line" and layout.id != line_id for layout in layouts):
            continue
        if len({layout.id for layout in layouts}) < 2:
            continue
        line_box = _box_of([c for c in member_chars if not is_space(c)] or member_chars)
        body = {layout.id for layout in layouts if layout.name in BODY_LABELS}
        candidates = [by_id[i] for i in body if i in by_id and by_id[i].box is not None]
        # 行碰到两个横向分离的正文框：那是两栏，不是同一个框被截短。
        if any(_h_disjoint(a.box, b.box) for a in candidates for b in candidates if a.id < b.id):
            continue
        # 不同归属之间隔着栏间空白（不是连续文字），不合并。
        if not _continuous(member_chars, [layout.id for layout in layouts], is_space):
            continue
        containing = [l for l in candidates if _contains(l.box, line_box)]
        target = None
        if containing:
            counts = {l.id: sum(1 for x in layouts if x.id == l.id) for l in containing}
            target = max(containing, key=lambda l: (counts[l.id], -((l.box.x2 - l.box.x) * (l.box.y2 - l.box.y))))
        elif len(candidates) == 1 and _vertical_cover(line_box, candidates[0].box) >= MIN_VERTICAL_COVER:
            target = candidates[0]
        if target is None:
            continue
        for i in members:
            if char_layouts[i].id != target.id:
                char_layouts[i] = layout_type(target.id, target.class_name)
                changed += 1
    return changed


def _area(box) -> float:
    return (box.x2 - box.x) * (box.y2 - box.y)


def _is_duplicate_of(inner, outer, body, chars, groups, is_space) -> bool:
    """内框是否是外框同一文字流的重复（截短）检测，而不是外框里的一栏。"""
    ib, ob = inner.box, outer.box
    if ob.x2 - ob.x <= 0 or (ib.x2 - ib.x) < MIN_DUPLICATE_WIDTH * (ob.x2 - ob.x):
        return False
    # 外框里还有与内框并排（横向分离、纵向重叠）的正文框：外框框住的是几栏。
    for other in body:
        if other.id in (inner.id, outer.id):
            continue
        sb = other.box
        if not _contains(ob, (sb.x, sb.y, sb.x2, sb.y2)):
            continue
        if _h_disjoint(ib, sb) and min(ib.y2, sb.y2) - max(ib.y, sb.y) > 0:
            return False
    # 至少一条物理行连续地跨过内框左右边缘：内框把同一行截断了。
    for members in groups.values():
        line_chars = [chars[i] for i in members if not is_space(chars[i])]
        if len(line_chars) < 2 or any(not _inside(ob, _center(c)) for c in line_chars):
            continue
        keys = [_inside(ib, _center(c)) for c in line_chars]
        if all(keys) or not any(keys):
            continue
        if _continuous(line_chars, keys, is_space):
            return True
    return False


def _prefer_outer_duplicates(chars, char_layouts, by_id, layout_type, groups, is_space) -> int:
    """同类正文框嵌套且确属同一文字流的重复检测时，被两者都包住的字符统一归外框。

    两个框同类、字符都在框内时优先级和 IoU 都相同，旧逻辑按 R-tree 返回顺序取一个，
    同一段的末行或页码会被分到内框，成为单独的小段。外框只是把并排几栏一起框住时不动。"""
    body = [l for l in by_id.values() if l.box is not None and l.class_name in BODY_LABELS]
    outer_of = {}
    for inner in body:
        outers = [o for o in body if o.id != inner.id and o.class_name == inner.class_name
                  and _contains(o.box, (inner.box.x, inner.box.y, inner.box.x2, inner.box.y2))
                  and _area(o.box) > _area(inner.box)]
        outers = [o for o in outers if _is_duplicate_of(inner, o, body, chars, groups, is_space)]
        if outers:
            outer_of[inner.id] = max(outers, key=lambda o: _area(o.box))
    changed = 0
    for index, layout in enumerate(char_layouts):
        if layout is None or layout.id not in outer_of:
            continue
        outer = outer_of[layout.id]
        b = chars[index].visual_bbox.box if chars[index].visual_bbox else None
        if b is None or not _contains(outer.box, (b.x, b.y, b.x2, b.y2)):
            continue
        char_layouts[index] = layout_type(outer.id, outer.class_name)
        changed += 1
    return changed


# ------------------------------------------------------------------ 表格列间空白

def _segments(chars, size):
    """一行里按字距切出的连续字块（空格不算字），返回 [(x, x2, [chars])]。"""
    solid = sorted((c for c in chars if (c.char_unicode or "").strip()), key=lambda c: c.visual_bbox.box.x)
    segments = []
    for char in solid:
        b = char.visual_bbox.box
        if segments and b.x - segments[-1][1] < 0.8 * size:
            x, x2, members = segments[-1]
            segments[-1] = (x, max(x2, b.x2), members + [char])
        else:
            segments.append((b.x, b.x2, [char]))
    return segments


def _font_size(chars):
    sizes = sorted(float(c.pdf_style.font_size) for c in chars
                   if c.pdf_style is not None and c.pdf_style.font_size and (c.char_unicode or "").strip())
    return sizes[len(sizes) // 2] if sizes else 0.0


def _segment_text(segment) -> str:
    return "".join((c.char_unicode or "") for c in segment[2]).strip()


def _stacks(segment, others) -> bool:
    """片段在另一行有左边、右边或中线对齐的片段（同一数据列的锚点）。"""
    t = ANCHOR_TOLERANCE
    x, x2 = segment[0], segment[1]
    return any(abs(o[0] - x) <= t or abs(o[1] - x2) <= t or abs((o[0] + o[1]) - (x + x2)) <= 2 * t for o in others)


def _column_evidence(gutter, rows, cells, rules) -> bool:
    """列间空白是否有空白之外的可信列证据。"""
    g0, g1 = gutter
    # 同表某一行在这里已经是两个独立段落（字符聚类本身就在这里断开）。
    for row in rows:
        boxes = sorted((item[0].box for item in row), key=lambda b: b.x)
        for a, b in zip(boxes, boxes[1:]):
            if min(b.x, g1) - max(a.x2, g0) > 0:
                return True
    # 竖直表格线穿过这条空白。
    if any(g0 <= (r.x + r.x2) / 2 <= g1 for r in rules):
        return True
    # 两个单元格框在这里分界（左格右边、右格左边都落在空白里）。
    t = CONTAIN_TOLERANCE
    ends = [c.x2 for c in cells if g0 - t <= c.x2 <= g1 + t]
    starts = [c.x for c in cells if g0 - t <= c.x <= g1 + t]
    if ends and starts:
        return True
    # 数据行里两个相邻的值记号（数字、布尔量等）在这里分开，且右侧的值与另一行的片段在同一列锚点上：
    # 这是数据列本身的位置，不只是对齐的词间空白。
    segs_by_row = [[s for _, chars, size, _ in row for s in _segments(chars, size)] for row in rows]
    for r, segs in enumerate(segs_by_row):
        segs = sorted(segs, key=lambda s: s[0])
        others = [s for k, row_segs in enumerate(segs_by_row) if k != r for s in row_segs]
        for a, b in zip(segs, segs[1:]):
            if min(b[0], g1) - max(a[1], g0) <= 0:
                continue
            if VALUE_TOKEN.fullmatch(_segment_text(a)) and VALUE_TOKEN.fullmatch(_segment_text(b)) and _stacks(b, others):
                return True
    return False


def split_table_rows_at_column_gutters(finder, page, paragraphs, new_id) -> int:
    """就地拆分 ``paragraphs`` 中跨越有列证据的列间空白的单行表格段落，返回新增段落数。"""
    from babeldoc.format.pdf.document_il import PdfLine, PdfParagraphComposition

    layouts = [l for l in page.page_layout or [] if l.box is not None]
    tables = [l.box for l in layouts if (l.class_name or "").lower() in TABLE_LAYOUTS]
    added = 0
    for table in tables:
        def in_table(b):
            cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
            return table.x <= cx <= table.x2 and table.y <= cy <= table.y2
        cells = [l.box for l in layouts if (l.class_name or "").lower() in CELL_LABELS and in_table(l.box)]
        rules = [c.box for c in page.pdf_curve or [] if c.box is not None and c.box.x2 - c.box.x <= 2.0
                 and c.box.y2 - c.box.y > 0 and in_table(c.box)]
        rows_src = []
        for paragraph in paragraphs:
            b = paragraph.box
            if b is None or paragraph.vertical or (paragraph.layout_label or "") not in TABLE_ROW_LABELS:
                continue
            if not in_table(b):
                continue
            lines = finder._paragraph_lines(paragraph)
            if len(lines) != 1 or len(paragraph.pdf_paragraph_composition) != 1:
                continue
            chars = list(lines[0].pdf_character)
            if not chars or any(getattr(c, "formula_layout_id", None) for c in chars):
                continue
            size = _font_size(chars)
            if size <= 0:
                continue
            # 落在版面检测单元格框里的段落是可信单元格：参与列证据，自身不拆。
            trusted = any(_contains(cell, (b.x, b.y, b.x2, b.y2)) for cell in cells)
            rows_src.append((paragraph, chars, size, trusted))
        if len(rows_src) < 2:
            continue
        # 按纵向重叠把段落归到表格行。
        rows: list[list] = []
        for item in sorted(rows_src, key=lambda r: -(r[0].box.y + r[0].box.y2)):
            b = item[0].box
            for row in rows:
                rb = row[0][0].box
                overlap = min(b.y2, rb.y2) - max(b.y, rb.y)
                if overlap > 0.5 * min(b.y2 - b.y, rb.y2 - rb.y):
                    row.append(item)
                    break
            else:
                rows.append([item])
        if len(rows) < 2:
            continue
        occupied = []
        for paragraph, chars, size, _ in rows_src:
            occupied.extend((x, x2) for x, x2, _ in _segments(chars, size))
        occupied.sort()
        merged = []
        for x, x2 in occupied:
            if merged and x <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], x2)
            else:
                merged.append([x, x2])
        gutters = [(a[1], b[0]) for a, b in zip(merged, merged[1:])]
        # 单元格框横跨的空白在单元格内部，不是列边界。
        t = CONTAIN_TOLERANCE
        gutters = [g for g in gutters if not any(c.x + t < g[0] and g[1] < c.x2 - t for c in cells)]
        gutters = [g for g in gutters if _column_evidence(g, rows, cells, rules)]
        if not gutters:
            continue
        # 每一行都要有字跨在至少一条列间空白的两侧（证明行都按同一组列排），否则不认为是列。
        def spans(row):
            xs = [x for _, chars, size, _ in row for x, _, _ in _segments(chars, size)]
            return [g for g in gutters if min(xs) < g[0] and max(xs) > g[1]]
        if sum(1 for row in rows if spans(row)) < 2:
            continue
        result_ids = {}
        for paragraph, chars, size, trusted in rows_src:
            if trusted:
                continue
            segs = _segments(chars, size)
            if len(segs) < 2:
                continue
            cuts = [g for g in gutters if segs[0][0] < g[0] and g[1] < segs[-1][1]]
            if not cuts:
                continue
            pieces, current = [], []
            for seg in segs:
                if current and any(current[-1][1] <= g[0] and g[1] <= seg[0] for g in cuts):
                    pieces.append(current)
                    current = []
                current.append(seg)
            pieces.append(current)
            if len(pieces) < 2:
                continue
            children = []
            for piece in pieces:
                lo, hi = piece[0][0], piece[-1][1]
                members = [c for c in chars if lo - 0.01 <= (c.visual_bbox.box.x + c.visual_bbox.box.x2) / 2 <= hi + 0.01
                           and (c.char_unicode or "").strip()]
                inner = [c for c in chars if not (c.char_unicode or "").strip()
                         and lo < (c.visual_bbox.box.x + c.visual_bbox.box.x2) / 2 < hi]
                members = sorted(members + inner, key=lambda c: c.visual_bbox.box.x)
                if not members:
                    break
                child = copy.copy(paragraph)
                line = PdfLine(pdf_character=members)
                finder.update_line_data(line)
                child.pdf_paragraph_composition = [PdfParagraphComposition(pdf_line=line)]
                child.debug_id = new_id()
                finder.update_paragraph_data(child, update_unicode=True)
                children.append(child)
            else:
                result_ids[id(paragraph)] = children
        if result_ids:
            out = []
            for paragraph in paragraphs:
                replacement = result_ids.get(id(paragraph))
                if replacement:
                    out.extend(replacement)
                    added += len(replacement) - 1
                else:
                    out.append(paragraph)
            paragraphs[:] = out
    return added
