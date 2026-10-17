# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""基于实际渲染成品的英文残留检查（最小版）。

逐页比较源 PDF 与译文 PDF 中可抽取的拉丁词数量：残留率 r = 译文拉丁词 / 源文拉丁词。
正常英译中保留人名、引用、公式变量等，实测 r≈0.05–0.15；整页未翻译时 r≈1。
本检查直接读最终 PDF，能发现从未进入翻译请求的文本（例如图表标签），
也能发现模型原样返回英文的情况；不依赖 translation blocks 的自报结果。

按 skill 规则本就不翻译的内容不计入残留率（源与译文两侧同样剔除，并逐页记录剔除词数）：
参考文献条目、等宽字体代码、URL/DOI/邮箱/arXiv 编号、方括号编号引用与作者-年份引用（含 et al.）。

参考文献的识别不依赖内容流顺序：先按文本行的坐标（纵向位置与分栏）计算阅读顺序，
再把行切成条目（编号、悬挂缩进或空行分隔），每个条目单独校验是否像文献条目
（编号、年份、作者/首字母、出版物/DOI/页码等特征，且虚词比例低）。
- 有 References/参考文献 等标题时，标题之后（阅读顺序）通过校验的条目被剔除，直到附录类标题
  （Appendix、附录、A/A.1/B 等字母编号标题）为止；标题之后的普通正文仍然计数。
- 没有标题时，只剔除连续 ≥3 条、按更严格阈值通过校验的条目。
- 译文侧的剔除量不得超过源文同页剔除量（×1.2 + 20 词），超出部分加回计数，防止译文用伪条目躲避检查。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
MIN_SOURCE_WORDS = 50
PAGE_HIGH = 0.60
PAGE_MEDIUM = 0.30
DOCUMENT_HIGH = 0.50


# 参考文献标题：整行只有标题（可带章节号）。
REFERENCE_HEADING = re.compile(
    r'^\s*(?:[0-9IVX]+(?:\.[0-9]+)*\.?\s+)?(?:references?|bibliography|works\s+cited|literature\s+cited|'
    r'reference\s+list|参考文献|参考资料|引用文献)\s*[:：]?\s*$', re.IGNORECASE)
# 结束参考文献区的附录类标题：命名附录，或字母编号标题（A、A.1、B …，后接大写词或中文）。
APPENDIX_HEADING = re.compile(
    r'^\s*(?:[A-Z](?:\.\d+)*\.?\s+)?(?:appendix(?:\s+[A-Z0-9]+)?|appendices|supplementary(?:\s+materials?)?|'
    r'附\s*录|补充材料)(?:\b|\s|$|[:：.])', re.IGNORECASE)
LETTERED_HEADING = re.compile(r'^\s*[A-Z](?:\.\d+)*\s+(?:[A-Z][A-Za-z\-]*|[\u4e00-\u9fff])')
INLINE_EXCLUSIONS = (
    ('url', re.compile(r'(?:https?://|www\.)\S+', re.IGNORECASE)),
    ('email', re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b')),
    ('doi', re.compile(r'\b(?:doi:\s*)?10\.\d{4,9}/\S+', re.IGNORECASE)),
    ('arxiv_id', re.compile(r'\barXiv:\s*\S+', re.IGNORECASE)),
    ('numeric_citation', re.compile(r'\[\s*\d+(?:\s*[,–\-]\s*\d+)*\s*\]')),
    ('author_year_citation', re.compile(r'\([^()]{0,160}?\b(?:19|20)\d{2}[a-z]?\)')),
    ('et_al', re.compile(r'\bet\s+al\.?', re.IGNORECASE)),
)
MONO_FONT = re.compile(r'mono|courier|consol|code|menlo|inconsolata|cour\b', re.IGNORECASE)

# 文献条目特征。
LEADING_MARKER = re.compile(r'^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,4}\.\s)')
YEAR = re.compile(r'(?<![\d.])(?:19|20)\d{2}[a-z]?(?![\d])')
AUTHOR = re.compile(r"\b[A-Z]\.(?:\s?[A-Z]\.)*\s?[A-Z][a-zA-Z'\-]+|\b[A-Z][a-zA-Z'\-]+,\s(?:[A-Z]\.\s?)+|\bet\s+al\b|"
                    r"(?:\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)*\s+[A-Z][a-zA-Z'\-]+,\s+){2,}")
VENUE = re.compile(r'\b(?:proceedings|proc\.|conference|journal|transactions|symposium|workshop|arxiv|preprint|doi|'
                   r'vol\.|volume|pp\.|pages|press|neurips|nips|icml|iclr|cvpr|iccv|eccv|acl|naacl|emnlp|aaai|ieee|acm|'
                   r'springer|elsevier|pmlr|advances\s+in)\b|10\.\d{4,9}/', re.IGNORECASE)
STOPWORDS = frozenset(
    'the of and to in is that for we this with as on are be by it an which from at or can our not these their its '
    'was were has have had been than also such into more but when where while only both each other there they them '
    'how what why who will would should could may might must do does did so if then thus however because between '
    'over under about after before through during without within very most much many some any all no one two us '
    'you he she his her i me my your'.split())
MAX_ENTRY_LINES = 10
# 虚词比例阈值：实测文献条目 0.10–0.29，英文正文 0.40–0.50（含夹带引用的正文）。
REGION_ENTRY_STOPWORDS = 0.33
STRICT_ENTRY_STOPWORDS = 0.32
HEADINGLESS_RUN_MEAN_STOPWORDS = 0.27
HEADINGLESS_MIN_RUN = 3
MAX_ENTRY_WORDS = 160
TARGET_EXCLUSION_SLACK = (1.2, 20)


def _is_code_span(span: dict[str, Any]) -> bool:
    return bool(int(span.get('flags', 0)) & 8) or bool(MONO_FONT.search(span.get('font', '') or ''))


def _visual_lines(page) -> list[dict[str, Any]]:
    """带坐标的视觉行（同一基线上相邻的片段合并）；等宽代码单独计数并从文本中剔除。"""
    rows = []
    for block in page.get_text('dict').get('blocks', []):
        for line in block.get('lines', []):
            kept, code, sizes, bold = [], 0, [], False
            for span in line.get('spans', []):
                text = span.get('text', '')
                if text.strip() and _is_code_span(span):
                    code += len(LATIN_WORD.findall(text))
                    continue
                kept.append(text)
                if text.strip():
                    sizes.append(float(span.get('size', 0)))
                    bold = bold or bool(int(span.get('flags', 0)) & 16) or 'bold' in (span.get('font', '') or '').lower()
            x0, y0, x1, y1 = line.get('bbox', (0, 0, 0, 0))
            rows.append({'text': ''.join(kept), 'code': code, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
                         'size': max(sizes) if sizes else 0.0, 'bold': bold})
    rows.sort(key=lambda r: (round(r['y0']), r['x0']))
    merged: list[dict[str, Any]] = []
    for row in rows:
        last = merged[-1] if merged else None
        if last and abs(row['y0'] - last['y0']) < 2 and 0 <= row['x0'] - last['x1'] < 12:
            last.update(text=last['text'] + ' ' + row['text'], code=last['code'] + row['code'], x1=row['x1'],
                        y1=max(last['y1'], row['y1']), size=max(last['size'], row['size']), bold=last['bold'] or row['bold'])
        else:
            merged.append(dict(row))
    return [r for r in merged if r['text'].strip() or r['code']]


def _reading_order(rows: list[dict[str, Any]], width: float) -> list[dict[str, Any]]:
    """按坐标计算阅读顺序：识别双栏；通栏行把页面切成带，每带内先左栏后右栏。"""
    mid, tol = width / 2, width * 0.04
    for row in rows:
        left, right = row['x1'] <= mid + tol, row['x0'] >= mid - tol
        row['col'] = 'F' if left == right else 'L' if left else 'R'
    wide = [r for r in rows if r['x1'] - r['x0'] >= 0.2 * width]
    if sum(r['col'] == 'L' for r in wide) < 3 or sum(r['col'] == 'R' for r in wide) < 3:
        for row in rows:
            row['col'] = 'F'
        return sorted(rows, key=lambda r: (r['y0'], r['x0']))
    ordered, band = [], []
    for row in sorted(rows, key=lambda r: (r['y0'], r['x0'])):
        if row['col'] == 'F':
            ordered += sorted([r for r in band if r['col'] == 'L'], key=lambda r: r['y0'])
            ordered += sorted([r for r in band if r['col'] == 'R'], key=lambda r: r['y0'])
            ordered.append(row)
            band = []
        else:
            band.append(row)
    ordered += sorted([r for r in band if r['col'] == 'L'], key=lambda r: r['y0'])
    ordered += sorted([r for r in band if r['col'] == 'R'], key=lambda r: r['y0'])
    return ordered


def _stopword_ratio(words: list[str]) -> float:
    return sum(w.lower() in STOPWORDS for w in words) / len(words) if words else 1.0


def citation_features(text: str) -> dict[str, Any]:
    words = LATIN_WORD.findall(text)
    features = {'words': len(words), 'stopword_ratio': round(_stopword_ratio(words), 3),
                'marker': bool(LEADING_MARKER.match(text)), 'year': bool(YEAR.search(text)),
                'author': bool(AUTHOR.search(text)), 'venue': bool(VENUE.search(text)),
                'comma_dense': bool(words) and text.count(',') / len(words) >= 0.10}
    features['score'] = (2 * features['marker'] + features['year'] + features['author'] + features['venue']
                         + features['comma_dense'])
    return features


def is_citation_entry(text: str, lines: int, *, strict: bool) -> bool:
    """单个条目是否像参考文献条目；普通正文（虚词比例高、无文献结构）一律不算。"""
    f = citation_features(text)
    if f['words'] < 4 or lines > MAX_ENTRY_LINES or f['words'] > MAX_ENTRY_WORDS:
        return False
    if strict:
        return f['year'] and f['score'] >= 4 and f['stopword_ratio'] <= STRICT_ENTRY_STOPWORDS
    return f['score'] >= 3 and f['stopword_ratio'] <= REGION_ENTRY_STOPWORDS


def _is_end_heading(row: dict[str, Any], body_size: float, gap_before: float) -> bool:
    text = row['text'].strip()
    if not text or len(text) > 80 or YEAR.search(text) or text.count(',') > 1:
        return False
    if APPENDIX_HEADING.match(text):
        return True
    if not LETTERED_HEADING.match(text) or text.endswith('.') or len(LATIN_WORD.findall(text)) > 12:
        return False
    height = max(row['y1'] - row['y0'], 1.0)
    return row['bold'] or row['size'] > body_size * 1.05 or gap_before > 0.5 * height


def _page_groups(page) -> list[dict[str, Any]]:
    """按阅读顺序把视觉行切成条目/段落；标题行单独成组。"""
    rows = _reading_order(_visual_lines(page), page.rect.width)
    sizes = sorted(r['size'] for r in rows if r['size'])
    body_size = sizes[len(sizes) // 2] if sizes else 0.0
    left_edge: dict[str, float] = {}
    for row in rows:
        left_edge[row['col']] = min(left_edge.get(row['col'], row['x0']), row['x0'])
    groups: list[dict[str, Any]] = []
    prev = None
    for row in rows:
        text = row['text'].strip()
        gap = (row['y0'] - prev['y1']) if prev and prev['col'] == row['col'] and row['y0'] >= prev['y0'] else 1e9
        kind = ('reference_heading' if REFERENCE_HEADING.match(text) else
                'end_heading' if _is_end_heading(row, body_size, gap) else None)
        height = max((prev or row)['y1'] - (prev or row)['y0'], 1.0)
        hanging = (prev is not None and prev['col'] == row['col'] and abs(row['x0'] - left_edge[row['col']]) <= 1.5
                   and prev['x0'] - left_edge[prev['col']] > 4)
        new = (not groups or kind or groups[-1]['kind'] or gap > 0.5 * height or hanging
               or bool(LEADING_MARKER.match(text)))
        if new:
            groups.append({'kind': kind, 'rows': [row]})
        else:
            groups[-1]['rows'].append(row)
        prev = row
    for group in groups:
        group['text'] = ' '.join(r['text'] for r in group['rows'])
        group['code'] = sum(r['code'] for r in group['rows'])
        group['page'] = page.number + 1
    return groups


def split_counted_text(document) -> tuple[list[str], list[dict[str, int]], list[int]]:
    """逐页返回计数文本与剔除统计；参考文献区按阅读顺序跨页延续，直到附录类标题。"""
    pages = [_page_groups(page) for page in document]
    in_region = False
    for groups in pages:
        for group in groups:
            group['exclude'] = None
            if group['kind'] == 'reference_heading':
                in_region, group['exclude'] = True, 'reference_section'
            elif group['kind'] == 'end_heading':
                in_region = False
            elif in_region and is_citation_entry(group['text'], len(group['rows']), strict=False):
                group['exclude'] = 'reference_section'
            group['in_region'] = in_region
    # 无标题的参考文献：连续 ≥3 条按严格阈值通过校验的条目（跳过页码等极短组）。
    run: list[dict[str, Any]] = []
    sequence = [g for groups in pages for g in groups] + [None]
    for group in sequence:
        if group is not None and len(LATIN_WORD.findall(group['text'])) < 4 and group['kind'] is None:
            continue
        candidate = (group is not None and group['exclude'] is None and not group['in_region']
                     and group['kind'] is None and is_citation_entry(group['text'], len(group['rows']), strict=True))
        if candidate:
            run.append(group)
            continue
        mean_stop = (sum(citation_features(g['text'])['stopword_ratio'] for g in run) / len(run)) if run else 1.0
        if len(run) >= HEADINGLESS_MIN_RUN and mean_stop <= HEADINGLESS_RUN_MEAN_STOPWORDS:
            for item in run:
                item['exclude'] = 'reference_entries_headingless'
        run = []
    counted_pages, excluded_pages, reference_pages = [], [], []
    for groups in pages:
        counted, stats = [], {'reference_section': 0, 'reference_entries_headingless': 0, 'code': 0}
        for group in groups:
            stats['code'] += group['code']
            if group['exclude']:
                stats[group['exclude']] += len(LATIN_WORD.findall(group['text']))
                if group['page'] not in reference_pages:
                    reference_pages.append(group['page'])
            else:
                counted.append(group['text'])
        page_text = '\n'.join(counted)
        for name, pattern in INLINE_EXCLUSIONS:
            removed = pattern.findall(page_text)
            stats[name] = sum(len(LATIN_WORD.findall(m if isinstance(m, str) else m[0])) for m in removed)
            page_text = pattern.sub(' ', page_text)
        counted_pages.append(page_text)
        excluded_pages.append(stats)
    return counted_pages, excluded_pages, reference_pages


def _norm_lines(text: str) -> list[str]:
    return [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]


def page_residue(source_text: str, target_text: str, target_extra_words: int = 0) -> dict[str, Any]:
    source_words = len(LATIN_WORD.findall(source_text))
    target_words = len(LATIN_WORD.findall(target_text)) + target_extra_words
    candidates = [l for l in _norm_lines(source_text) if len(l) >= 25 and len(LATIN_WORD.findall(l)) >= 4]
    joined = ' '.join(_norm_lines(target_text))
    verbatim = sum(1 for line in candidates if line in joined)
    ratio = target_words / source_words if source_words else 0.0
    evaluated = source_words >= MIN_SOURCE_WORDS
    severity = ('high' if ratio >= PAGE_HIGH else 'medium' if ratio >= PAGE_MEDIUM else 'ok') if evaluated else 'not_evaluated'
    return {'source_latin_words': source_words, 'target_latin_words': target_words,
            'target_cjk_chars': len(CJK.findall(target_text)), 'residue_ratio': round(ratio, 4),
            'verbatim_source_lines': verbatim, 'source_lines_checked': len(candidates),
            'evaluated': evaluated, 'severity': severity}


def check_render_residue(source_pdf, target_pdf, *, target_language: str = 'zh') -> dict[str, Any]:
    import fitz

    result: dict[str, Any] = {'schema_version': 1, 'check': 'render_english_residue', 'target_language': target_language,
                              'source': str(source_pdf), 'target': str(target_pdf) if target_pdf else None,
                              'thresholds': {'page_high': PAGE_HIGH, 'page_medium': PAGE_MEDIUM,
                                             'document_high': DOCUMENT_HIGH, 'min_source_words': MIN_SOURCE_WORDS},
                              'pages': []}
    if target_language != 'zh':
        result.update(status='not_applicable', severity='ok', reason='only_en_to_zh_supported')
        return result
    if not target_pdf or not Path(target_pdf).is_file():
        result.update(status='not_evaluated', severity='ok', reason='target_pdf_missing')
        return result
    with fitz.open(source_pdf) as source, fitz.open(target_pdf) as target:
        # mono 成品与源页一一对应；页数不一致时只比较共同页并记录。
        count = min(len(source), len(target))
        result['page_count_source'], result['page_count_target'] = len(source), len(target)
        source_text, source_excluded, source_refs = split_counted_text(source)
        target_text, target_excluded, target_refs = split_counted_text(target)
        for index in range(count):
            source_ex, target_ex = sum(source_excluded[index].values()), sum(target_excluded[index].values())
            allowed = int(source_ex * TARGET_EXCLUSION_SLACK[0]) + TARGET_EXCLUSION_SLACK[1]
            added_back = max(0, target_ex - allowed)  # 译文侧剔除超出源文同页剔除量的部分加回计数
            row = page_residue(source_text[index], target_text[index], added_back)
            row['page'] = index + 1
            row['excluded_source_words'] = source_ex
            row['excluded_target_words'] = target_ex - added_back
            row['target_exclusion_capped_words'] = added_back
            row['excluded_source_breakdown'] = {k: v for k, v in source_excluded[index].items() if v}
            result['pages'].append(row)
        result['excluded'] = {
            'rules': ['reference_section', 'reference_entries_headingless', 'code'] + [name for name, _ in INLINE_EXCLUSIONS],
            'target_exclusion_cap': {'factor': TARGET_EXCLUSION_SLACK[0], 'slack_words': TARGET_EXCLUSION_SLACK[1]},
            'reference_section_pages': {'source': source_refs, 'target': target_refs},
            'source_words': sum(sum(p.values()) for p in source_excluded[:count]),
            'target_words': sum(sum(p.values()) for p in target_excluded[:count]),
        }
    evaluated = [p for p in result['pages'] if p['evaluated']]
    total_source = sum(p['source_latin_words'] for p in evaluated)
    total_target = sum(p['target_latin_words'] for p in evaluated)
    overall = total_target / total_source if total_source else 0.0
    high_pages = [p['page'] for p in evaluated if p['severity'] == 'high']
    medium_pages = [p['page'] for p in evaluated if p['severity'] == 'medium']
    severity = 'high' if (evaluated and overall >= DOCUMENT_HIGH) or high_pages else 'medium' if medium_pages else 'ok'
    result.update(status='evaluated' if evaluated else 'not_evaluated', overall_residue_ratio=round(overall, 4),
                  high_pages=high_pages, medium_pages=medium_pages, severity=severity,
                  quality_fail=severity == 'high')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    result = check_render_residue(args.source, args.target)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 2 if result.get('quality_fail') else 0


if __name__ == '__main__':
    raise SystemExit(main())
