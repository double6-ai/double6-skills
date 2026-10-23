# Double6 Skills 维护版本（2026-10-23）：新增模块，见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""同一物理行不被版面框切碎；表格行按全表共有的列间空白拆成单元格。

两件事都只看源 PDF 的字符几何与版面检测框，不按文档名或词表分支：

* ``unify_line_layouts``：版面模型给出的文字框常比实际行窄几个字（框在缩小的页面图上检测），
  行首/行尾越出框的字符只落在 ``fallback_line``（按字符几何聚出的物理行）里，于是同一行被拆成
  "The Arti" / 正文 / "t." 三段，两端碎片被当作紧凑标签原样保留。两个同级文字框重叠时，
  旧逻辑按 R-tree 返回顺序打破平局，同一行也会被拆到两个框里（表目录末行被切出去、缩成极小字号，
  其余三行因此凑不够目录行数而并成一段）。这里按物理行统一归属：
  只在整行字符都已归入正文类文字框或该行自身的 ``fallback_line`` 时处理；
  有正文框完整包住整行就归它，否则整行只碰到唯一一个正文框且该框在纵向上覆盖行高的大部分时归它。
  表格单元格、页眉页脚、图内文字、公式等其他角色一律不动。
* ``split_table_rows_at_column_gutters``：表格区域内，行聚类会把字距较小的表头整行聚成一个
  ``fallback_line``，译后整行左对齐，和下面各列错位。只在同一表格区域有至少两行、且某个横向位置在
  **每一行**都是空白（全表共有的列间空白）时，才在该位置把单行段落拆开；任何一行在该位置有字，就不拆。
"""
from __future__ import annotations

import copy

BODY_LABELS = frozenset({
    "plain text", "text", "title", "paragraph_title", "abstract", "content", "doc_title",
    "figure_caption", "table_caption", "figure_title", "table_title", "chart_title", "paragraph",
    "caption", "list_item", "footnote", "table_footnote", "tiny text", "paragraph_hybrid",
    "caption_hybrid", "title_hybrid", "list_item_hybrid", "footnote_hybrid",
})
TABLE_LAYOUTS = frozenset({"table", "table_body"})
TABLE_ROW_LABELS = frozenset({"fallback_line", "plain text", "text", "table_text", "table_cell",
                              "wired_table_cell", "wireless_table_cell", "table_cell_hybrid"})
# 行的纵向覆盖率：框只在横向上截短时，它在纵向上覆盖整行。
MIN_VERTICAL_COVER = 0.6
CONTAIN_TOLERANCE = 1.5


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


def unify_line_layouts(chars, char_layouts, layout_index, layout_map, layout_type, is_space) -> int:
    """就地改写 ``char_layouts``，返回被改归属的字符数。``layout_type`` 为 layout_helper.Layout。"""
    by_id = {layout.id: layout for layout in layout_map.values()}
    changed = _prefer_outer_duplicates(chars, char_layouts, by_id, layout_type)
    groups: dict[int, list[int]] = {}
    for index, char in enumerate(chars):
        if char.visual_bbox is None or char.visual_bbox.box is None:
            continue
        line = _line_of(char, layout_index, layout_map)
        if line is not None:
            groups.setdefault(line.id, []).append(index)
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


def _prefer_outer_duplicates(chars, char_layouts, by_id, layout_type) -> int:
    """同类正文框嵌套（模型对同一区域的重复检测）时，被两者都包住的字符统一归外框。

    两个框同类、字符都在框内时优先级和 IoU 都相同，旧逻辑按 R-tree 返回顺序取一个，
    同一段的末行或页码会被分到内框，成为单独的小段。"""
    body = [l for l in by_id.values() if l.box is not None and l.class_name in BODY_LABELS]
    outer_of = {}
    for inner in body:
        outers = [o for o in body if o.id != inner.id and o.class_name == inner.class_name
                  and _contains(o.box, (inner.box.x, inner.box.y, inner.box.x2, inner.box.y2))
                  and (o.box.x2 - o.box.x) * (o.box.y2 - o.box.y) > (inner.box.x2 - inner.box.x) * (inner.box.y2 - inner.box.y)]
        if outers:
            outer_of[inner.id] = max(outers, key=lambda o: (o.box.x2 - o.box.x) * (o.box.y2 - o.box.y))
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


def split_table_rows_at_column_gutters(finder, page, paragraphs, new_id) -> int:
    """就地拆分 ``paragraphs`` 中跨越全表共有列间空白的单行表格段落，返回新增段落数。"""
    from babeldoc.format.pdf.document_il import PdfLine, PdfParagraphComposition

    tables = [l.box for l in page.page_layout or [] if l.box is not None and (l.class_name or "").lower() in TABLE_LAYOUTS]
    added = 0
    for table in tables:
        rows_src = []
        for paragraph in paragraphs:
            b = paragraph.box
            if b is None or paragraph.vertical or (paragraph.layout_label or "") not in TABLE_ROW_LABELS:
                continue
            cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
            if not (table.x <= cx <= table.x2 and table.y <= cy <= table.y2):
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
            rows_src.append((paragraph, chars, size))
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
        for paragraph, chars, size in rows_src:
            occupied.extend((x, x2) for x, x2, _ in _segments(chars, size))
        occupied.sort()
        merged = []
        for x, x2 in occupied:
            if merged and x <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], x2)
            else:
                merged.append([x, x2])
        gutters = [(a[1], b[0]) for a, b in zip(merged, merged[1:])]
        if not gutters:
            continue
        # 每一行都要有字跨在至少一条列间空白的两侧（证明行都按同一组列排），否则不认为是列。
        def spans(row):
            xs = [x for _, chars, size in row for x, _, _ in _segments(chars, size)]
            return [g for g in gutters if min(xs) < g[0] and max(xs) > g[1]]
        if sum(1 for row in rows if spans(row)) < 2:
            continue
        result_ids = {}
        for paragraph, chars, size in rows_src:
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
