# Double6 Skills 维护版本（2026-10-23）：新增模块，见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""硬可读字号下限溢出时的“保留原文”降级（overflow_source_fallback）。

背景：排版先在可读字号下限以内缩字、在原框内折行、再按既有规则借用空白；全部试过仍放不下时，
旧行为把整段记为 ``hard_readable_floor_overflow`` 并让整份文档失败。对表头单元格、目录项/页码标签、
图内短标签这类“短、结构已确认”的片段，长度合理的译文也常因格子太窄放不下，整份文档因此失败。

本模块只做两件事，都是纯函数，方便单测：

* ``admission``：判定某个溢出段落能否保留原文（原字形、原位置，不缩字、不裁切、不重叠）。
  只接受明确的结构角色和短文本；正文、标题、图注、脚注等其它角色以及含公式/多句的片段一律拒绝，
  维持原来的失败。
* ``cap_violations``：按页、按文档两级上限检查降级数量，超限时整批撤销降级，照旧失败，
  防止“大部分没翻译”的文档靠降级通过。

降级不是通过：每条降级都写进 ``typesetting_writeback_report.json`` 的 ``source_fallbacks``，
稳定代码 ``overflow_source_fallback``；上层综合质量把它记为 pending（unverified），永不给 pass。
"""
from __future__ import annotations

import math
import re

CODE = "overflow_source_fallback"
CAP_CODE = "overflow_source_fallback_cap_exceeded"

TOC_ROLES = frozenset({"toc_entry", "chapter_index_entry"})
TABLE_ROLES = frozenset({"table_header", "table_cell"})
FIGURE_ROLES = frozenset({"chart_label", "axis", "axis_label", "legend", "diagram_node"})
# 只在几何上被既有版面分析确认位于表格区域/图内填充节点时才接受的通用短行角色。
GEOMETRY_CONFIRMED_ROLES = frozenset({"fallback_line"})

# 长度上限：源文（保留下来的就是它）必须是短标签。
MAX_SOURCE_CHARS = 40
MAX_SOURCE_LATIN_WORDS = 6
MAX_SOURCE_CJK_CHARS = 16
MAX_TRANSLATED_CHARS = 80
# 单行：段落框高度不超过最大字号的 2.2 倍。
MAX_LINE_HEIGHT_RATIO = 2.2

# 上限：每页 max(3, 20% 段落)，每份文档 max(4, 10% 段落)。
PAGE_CAP_MIN, PAGE_CAP_FRACTION = 3, 0.20
DOC_CAP_MIN, DOC_CAP_FRACTION = 4, 0.10

LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
PLACEHOLDER = re.compile(r"\{v\d+\}|<style\b", re.IGNORECASE)
# 句内终止符（行末的句号允许，例如 "Fig."）：出现即视为多句/正文。
INNER_SENTENCE_END = re.compile(r"[。！？；]|[.!?;]\s+\S")


def _center_inside(box, regions) -> bool:
    if box is None:
        return False
    cx, cy = (box.x + box.x2) / 2, (box.y + box.y2) / 2
    return any(r is not None and r.x <= cx <= r.x2 and r.y <= cy <= r.y2 for r in regions)


def structure_category(paragraph, page) -> str | None:
    """既有分类给出的结构类别：toc_entry / table_cell / figure_label；不是这三类返回 None。"""
    label = (getattr(paragraph, "layout_label", None) or "").lower()
    if label in TOC_ROLES:
        return "toc_entry"
    if label in TABLE_ROLES:
        return "table_cell"
    if label in FIGURE_ROLES:
        return "figure_label"
    if label in GEOMETRY_CONFIRMED_ROLES and page is not None:
        from babeldoc.format.pdf.document_il.midend.table_figure_text import figure_nodes, table_regions
        box = getattr(paragraph, "box", None)
        if _center_inside(box, table_regions(page)):
            return "table_cell"
        if _center_inside(box, figure_nodes(page)):
            return "figure_label"
    return None


def _backup_text_and_size(backup) -> tuple[str, float, bool]:
    """备份的源组合：(文本, 最大字号, 是否只含普通字符)。含公式/其它对象时第三项为 False。"""
    parts, sizes, plain = [], [], True
    for comp in backup or []:
        if getattr(comp, "pdf_formula", None) is not None:
            plain = False
        char = getattr(comp, "pdf_character", None)
        line = getattr(comp, "pdf_line", None)
        same = getattr(comp, "pdf_same_style_characters", None)
        uni = getattr(comp, "pdf_same_style_unicode_characters", None)
        chars = ([char] if char is not None else list(getattr(line, "pdf_character", None) or [])
                 if line is not None else list(getattr(same, "pdf_character", None) or []))
        for c in chars:
            parts.append(c.char_unicode or "")
            style = getattr(c, "pdf_style", None)
            if style is not None and style.font_size:
                sizes.append(float(style.font_size))
        if uni is not None:
            parts.append(uni.unicode or "")
            style = getattr(uni, "pdf_style", None)
            if style is not None and style.font_size:
                sizes.append(float(style.font_size))
        if char is None and line is None and same is None and uni is None:
            plain = False
    return "".join(parts), (max(sizes) if sizes else 0.0), plain


def backup_text(backup) -> str:
    return _backup_text_and_size(backup)[0]


def admission(paragraph, page, source_text: str | None, translated_text: str | None, backup) -> tuple[bool, str]:
    """返回 (是否接受, 类别或拒绝理由)。只有全部条件满足才接受。"""
    category = structure_category(paragraph, page)
    if category is None:
        return False, "role_not_admitted"
    if not backup:
        return False, "source_backup_missing"
    backup_text, size, plain = _backup_text_and_size(backup)
    if not plain:
        return False, "source_not_plain_text"
    source = re.sub(r"\s+", " ", (source_text or backup_text or "")).strip()
    if not source:
        return False, "source_empty"
    if PLACEHOLDER.search(source_text or ""):
        return False, "source_has_placeholder"
    if (len(source) > MAX_SOURCE_CHARS or len(LATIN_WORD.findall(source)) > MAX_SOURCE_LATIN_WORDS
            or len(CJK.findall(source)) > MAX_SOURCE_CJK_CHARS):
        return False, "source_too_long"
    if INNER_SENTENCE_END.search(source.rstrip(" .。")):
        return False, "source_multi_sentence"
    translated = (translated_text or "").strip()
    if not translated or len(translated) > MAX_TRANSLATED_CHARS:
        return False, "translation_length_out_of_range"
    box = getattr(paragraph, "box", None)
    if box is None or size <= 0 or (box.y2 - box.y) > MAX_LINE_HEIGHT_RATIO * size:
        return False, "source_not_single_line"
    return True, category


def page_cap(paragraph_count: int) -> int:
    return max(PAGE_CAP_MIN, math.ceil(PAGE_CAP_FRACTION * max(paragraph_count, 0)))


def doc_cap(paragraph_count: int) -> int:
    return max(DOC_CAP_MIN, math.ceil(DOC_CAP_FRACTION * max(paragraph_count, 0)))


def cap_violations(fallback_pages: list[int], paragraphs_per_page: dict[int, int]) -> dict:
    """fallback_pages：每条降级所在页；paragraphs_per_page：每页段落数。返回上限与违例（空 violations 表示未超限）。"""
    total = sum(paragraphs_per_page.values())
    counts: dict[int, int] = {}
    for p in fallback_pages:
        counts[p] = counts.get(p, 0) + 1
    violations = []
    for p, n in sorted(counts.items()):
        cap = page_cap(paragraphs_per_page.get(p, 0))
        if n > cap:
            violations.append({"scope": "page", "page_index": p, "count": n, "cap": cap})
    cap = doc_cap(total)
    if len(fallback_pages) > cap:
        violations.append({"scope": "document", "count": len(fallback_pages), "cap": cap})
    return {"document_cap": cap, "page_caps": {str(p): page_cap(paragraphs_per_page.get(p, 0)) for p in counts},
            "count": len(fallback_pages), "violations": violations}
