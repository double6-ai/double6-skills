#!/usr/bin/env python3
"""公式上/下标层级保真门（两个翻译方向通用；PR #25 公式结构项）。

源文每个“上/下标关系”（数学字体基字形 + 字号明显更小、基线明显抬高或降低的相邻字形）都须在成品里
找到同字符、同方向、同字体族、偏移量相近的关系（整份匹配，成品可重新分页；按源页报告）；找不到即判“层级被压平/丢失”，失败关闭（high，稳定规则码
``formula_script_structure_lost``）。只按字形几何核对，不依赖抽取顺序；成品段落可整体移动、缩放
（偏移以基字字号归一）。基字限于数学/斜体字体（或闭括号 + 数学字体角标），正文脚注角标不在本门范围。

同一函数也供可读版（final_readable）使用：可读版按页整页矢量复制的公式页，用其来源成品页的结论。
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RULE = 'formula_script_structure_lost'
# 与 pdf_input_preflight._MATH_FONT 相同的数学/斜体字体判据（基字形）；角标严格数学字体判据同 render_residue_check。
MATH_FONT = re.compile(r'italic|oblique|math|cmmi|cmsy|cmex|cmbsy|symbol|stix|cambria|mt-?extra|euclid|msam|msbm|rsfs|eufm|eusm',
                       re.IGNORECASE)
STRICT_MATH_FONT = re.compile(r'cmmi|cmsy|cmex|cmbsy|math|symbol|stix|euclid|mt-?extra|msam|msbm|rsfs|eufm|eusm', re.IGNORECASE)
CLOSING = frozenset(')]}|')
SCRIPT_SIZE_RATIO = 0.85     # 角标字号 < 基字字号 × 0.85
SCRIPT_MIN_OFFSET = 0.12     # 基线偏移 >= 0.12 个基字字号才算上/下标（同基线小字号偏移为 0）
MAX_GAP_EM = 0.6             # 角标左缘距基字右缘 <= 0.6 个基字字号（叠放上下标可为负）
MAX_VERTICAL_EM = 0.9        # 角标基线距基字基线 <= 0.9 个基字字号
MIN_VERTICAL_OVERLAP = 0.2  # 角标与基字的字形框须纵向重叠 >= 0.2 个角标字号
MATCH_TOLERANCE = (0.08, 0.25)  # 成品偏移与源偏移之差 <= max(0.08, 0.25×|源偏移|)
MAX_GLYPHS_PER_PAGE = 60000


def _glyphs(page) -> list[dict[str, Any]]:
    rows = []
    for block in page.get_text('rawdict').get('blocks', []):
        for line in block.get('lines', []):
            direction = line.get('dir') or (1, 0)
            if abs(direction[1]) > 1e-3:
                continue  # 竖排/旋转行不参与
            for span in line.get('spans', []):
                for char in span.get('chars', []):
                    c = char.get('c') or ''
                    if not c.strip() or unicodedata.category(c)[0] in 'ZC':
                        continue
                    rows.append({'c': c, 'x': char['origin'][0], 'y': char['origin'][1], 'bbox': tuple(char['bbox']),
                                 'size': float(span.get('size') or 0.0), 'font': span.get('font') or ''})
    return rows


def _base_ok(base: dict[str, Any], script: dict[str, Any]) -> bool:
    if MATH_FONT.search(base['font']):
        return True
    return base['c'] in CLOSING and bool(STRICT_MATH_FONT.search(script['font']))


def script_relations(page) -> list[dict[str, Any]]:
    """页面上所有上/下标关系：每个角标字形对应其左侧最近的、字号更大的基字形。"""
    glyphs = _glyphs(page)
    if len(glyphs) > MAX_GLYPHS_PER_PAGE:
        raise ValueError('formula_structure_glyph_count_limit')
    cells: dict[tuple[int, int], list[int]] = {}
    for index, g in enumerate(glyphs):
        cells.setdefault((int(g['x'] // 24), int(g['y'] // 24)), []).append(index)
    relations = []
    related: dict[int, dict[str, Any]] = {}
    for g in sorted(glyphs, key=lambda item: item['x']):
        if g['size'] <= 0:
            continue
        best = None
        cx, cy = int(g['x'] // 24), int(g['y'] // 24)
        for dx in (-2, -1, 0):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    b = glyphs[j]
                    if b is g or b['size'] <= 0 or g['size'] >= b['size'] * SCRIPT_SIZE_RATIO:
                        continue
                    if not b['x'] < g['x']:
                        continue
                    gap = g['bbox'][0] - b['bbox'][2]
                    if gap > MAX_GAP_EM * b['size'] or g['bbox'][0] - b['bbox'][0] < 0.1 * b['size']:
                        continue
                    if abs(b['y'] - g['y']) > MAX_VERTICAL_EM * b['size']:
                        continue
                    overlap = min(b['bbox'][3], g['bbox'][3]) - max(b['bbox'][1], g['bbox'][1])
                    if overlap < MIN_VERTICAL_OVERLAP * g['size']:
                        continue  # 上一行/下一行（或分式另一层）的字形不是基字
                    key = (b['x'], -abs(b['y'] - g['y']))
                    if best is None or key > best[0]:
                        best = (key, b)
        if best is None:
            # 角标串的后续字形（如 max 的 a、x）：紧邻左侧是同字号、同基线、已判为角标的字形时继承其基字。
            prev = _left_neighbour(g, glyphs, cells)
            if prev is None or id(prev) not in related:
                continue
            base = related[id(prev)]['_base']
        else:
            base = best[1]
        offset = (base['y'] - g['y']) / base['size']
        if abs(offset) < SCRIPT_MIN_OFFSET or not _base_ok(base, g):
            continue
        rel = {'base': base['c'], 'base_font': base['font'], 'script': g['c'], 'script_font': g['font'],
                          'kind': 'superscript' if offset > 0 else 'subscript', 'offset_em': round(offset, 4),
                          'size_ratio': round(g['size'] / base['size'], 4),
                          'base_origin': [round(base['x'], 3), round(base['y'], 3)],
                          'script_origin': [round(g['x'], 3), round(g['y'], 3)]}
        relations.append(rel)
        related[id(g)] = dict(rel, _base=base)
    return relations


def _left_neighbour(g: dict[str, Any], glyphs: list[dict[str, Any]], cells) -> dict[str, Any] | None:
    best = None
    cx, cy = int(g['x'] // 24), int(g['y'] // 24)
    for dx in (-1, 0):
        for dy in (-1, 0, 1):
            for j in cells.get((cx + dx, cy + dy), ()):
                h = glyphs[j]
                if h is g or not h['x'] < g['x'] or abs(h['size'] - g['size']) > 0.02 * g['size']:
                    continue
                if abs(h['y'] - g['y']) > 0.05 * g['size'] or g['bbox'][0] - h['bbox'][2] > 0.5 * g['size']:
                    continue
                if best is None or h['x'] > best['x']:
                    best = h
    return best


def _family(font: str) -> str:
    name = font.split('+', 1)[-1]
    return re.sub(r'[\d.]+$', '', name).lower()


def _key(rel: dict[str, Any]) -> tuple[str, str, str, str]:
    return rel['base'], rel['script'], rel['kind'], _family(rel['script_font'])


def match_relations(source: list[dict[str, Any]], target: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """源关系逐个匹配成品中同基字、同角标字符、同方向、同字体族且偏移相近的关系（每个成品关系只用一次）；
    返回未匹配（丢失）的源关系。"""
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for cand in target:
        buckets.setdefault(_key(cand), []).append(cand)
    used: set[int] = set()
    lost = []
    for rel in sorted(source, key=lambda r: abs(r['offset_em']), reverse=True):
        tol = max(MATCH_TOLERANCE[0], MATCH_TOLERANCE[1] * abs(rel['offset_em']))
        pick = None
        for cand in buckets.get(_key(rel), ()):
            if id(cand) in used:
                continue
            error = abs(cand['offset_em'] - rel['offset_em'])
            if error <= tol and (pick is None or error < pick[0]):
                pick = (error, cand)
        if pick is None:
            lost.append(rel)
        else:
            used.add(id(pick[1]))
    return lost


def page_script_structure(source_page, target_page) -> dict[str, Any]:
    source = script_relations(source_page)
    target = script_relations(target_page)
    lost = match_relations(source, target)
    return {'source_relations': len(source), 'target_relations': len(target), 'lost': len(lost),
            'samples': lost[:12], 'flagged': bool(lost)}


def check_formula_structure(source_pdf, target_pdf) -> dict[str, Any]:
    """整份核对上/下标关系（成品可能重新分页，如 LaTeX 直出，故按整份匹配、按源页报告）；
    检查本身出错时由调用方记 not_evaluated，不伪造通过。"""
    import fitz

    result: dict[str, Any] = {'schema_version': SCHEMA_VERSION, 'check': 'formula_script_structure', 'rule': RULE,
                              'source': str(source_pdf), 'target': str(target_pdf) if target_pdf else None,
                              'thresholds': {'script_size_ratio': SCRIPT_SIZE_RATIO, 'script_min_offset_em': SCRIPT_MIN_OFFSET,
                                             'max_gap_em': MAX_GAP_EM, 'max_vertical_em': MAX_VERTICAL_EM,
                                             'min_vertical_overlap': MIN_VERTICAL_OVERLAP,
                                             'match_tolerance_em': list(MATCH_TOLERANCE)},
                              'matching_scope': 'document', 'pages': []}
    if not target_pdf or not Path(target_pdf).is_file():
        result.update(status='not_evaluated', severity='ok', reason='target_pdf_missing', flagged_pages=[])
        return result
    with fitz.open(source_pdf) as source, fitz.open(target_pdf) as target:
        result['page_count_source'], result['page_count_target'] = len(source), len(target)
        source_rel = []
        for index in range(len(source)):
            for rel in script_relations(source[index]):
                source_rel.append(dict(rel, page=index + 1))
        target_rel = []
        target_counts = []
        for index in range(len(target)):
            rows = script_relations(target[index])
            target_counts.append(len(rows))
            target_rel.extend(dict(rel, page=index + 1) for rel in rows)
    lost = match_relations(source_rel, target_rel)
    for index in range(result['page_count_source']):
        page_lost = [r for r in lost if r['page'] == index + 1]
        result['pages'].append({'page': index + 1,
                                'source_relations': sum(1 for r in source_rel if r['page'] == index + 1),
                                'target_relations': target_counts[index] if index < len(target_counts) else 0,
                                'lost': len(page_lost), 'samples': page_lost[:12], 'flagged': bool(page_lost)})
    flagged = [p['page'] for p in result['pages'] if p['flagged']]
    result.update(status='evaluated', source_relations=len(source_rel), target_relations=len(target_rel), lost=len(lost),
                  flagged_pages=flagged, severity='high' if flagged else 'ok', quality_fail=bool(flagged))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    result = check_formula_structure(args.source, args.target)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 2 if result.get('quality_fail') else 0


if __name__ == '__main__':
    raise SystemExit(main())
