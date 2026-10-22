# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""基于实际渲染成品的源语言残留检查（最小版）：英译中查英文残留，中译英查中文残留。

中译英（target_language='en'）：逐页比较源/译文可抽取的 CJK 汉字数，残留率 r = 译文汉字 / 源文汉字。
英文译文里合理保留的汉字几乎为零（不像英译中要保留人名、公式变量），阈值因此更严：
页 r≥0.30 为 high、r≥0.10 为 medium，全文 r≥0.25 为 high；源页汉字少于 100 不评估。
另记录整句原样残留（≥12 个汉字的源文行原样出现在译文中）和全角中文标点数，供人工复核；
并检测源文保留字形（未翻译的公式碎片）与英文译文字形的压叠（≥10 个字符的页记为 medium，提示复核）。
以下为英译中检查说明。

逐页比较源 PDF 与译文 PDF 中可抽取的拉丁词数量：残留率 r = 译文拉丁词 / 源文拉丁词。
正常英译中保留人名、引用、公式变量等，实测 r≈0.05–0.15；整页未翻译时 r≈1。
本检查直接读最终 PDF，能发现从未进入翻译请求的文本（例如图表标签），
也能发现模型原样返回英文的情况；不依赖 translation blocks 的自报结果。

按 skill 规则本就不翻译的内容不计入残留率（源与译文两侧同样剔除，并逐页记录剔除词数）：
参考文献条目、等宽字体代码、URL/DOI/邮箱/arXiv 编号、方括号编号引用与作者-年份引用（含 et al.）。

参考文献的识别不依赖内容流顺序：先按文本行的坐标（纵向位置与分栏）计算阅读顺序，
再把行切成条目（编号、悬挂缩进或空行分隔），每个条目单独校验是否像文献条目
（编号、年份、作者/首字母、出版物/DOI/页码等特征，且虚词比例低）。
- 逐条分类为 strong（编号/作者开头 + 年份 + 出处信号）、weak（只缺其一、栏首残段或栏底被截断的编号条目头）、
  short、break。strong 剔除；weak 默认计数，只有正面证据才剔除：编号与紧邻条目连续（numbered_sequence），
  或是紧接已剔除且未结束条目的栏首/页首续接残段（continuation）；break 计数。无标题段与标题区域规则一致，
  每条决定写入审计记录。
- 有 References/参考文献 等标题时，规则作用于标题之后（阅读顺序）直到附录类标题
  （Appendix、附录、A/A.1/B 等字母编号标题）为止的区域。
- 句子式正文（指标枚举、多个小数/年份/叙述式引用、第一人称、谓语动词、句首连接词）一律否决。
- 没有标题时需要强结构证据（宁可误报不可漏判）：≥3 条编号/作者开头且含年份与出处的条目、左边距一致、
  位于文末或节末、全文剔除不超过源文英文词一半；译文侧只在源文已接受的页上剔除；候选段写入审计记录。
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
LEADING_MARKER = re.compile(r'^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,3}\.\s)')  # n. 最多三位，避免把 "2000. 标题" 当编号
# 年份：不把 arXiv 编号（2010.11929）的前四位算作年份。
YEAR = re.compile(r'(?<![\d.:/])(?:19|20)\d{2}[a-z]?(?!\d|\.\d)')
AUTHOR = re.compile(r"\b[A-Z]\.(?:\s?[A-Z]\.)*\s?[A-Z][a-zA-Z'\-]+|\b[A-Z][a-zA-Z'\-]+,\s(?:[A-Z]\.\s?)+|\bet\s+al\b|"
                    r"(?:\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)*\s+[A-Z][a-zA-Z'\-]+,\s+){2,}")
VENUE = re.compile(r'\b(?:proceedings|proc\.|conference|journal|transactions|symposium|workshop|arxiv|preprint|doi|'
                   r'vol\.|volume|pp\.|pages|press|neurips|nips|icml|iclr|cvpr|iccv|eccv|acl|naacl|emnlp|aaai|ieee|acm|'
                   r'springer|elsevier|pmlr|advances\s+in)\b|10\.\d{4,9}/|\d+\s*\(\d+\)\s*:\s*\d+', re.IGNORECASE)
VENUE_IN = re.compile(r'\.\s+In\s+(?:[A-Z]|\d{4})')  # "… title. In Proceedings / In ICLR / In 2021 …\"
STOPWORDS = frozenset(
    'the of and to in is that for we this with as on are be by it an which from at or can our not these their its '
    'was were has have had been than also such into more but when where while only both each other there they them '
    'how what why who will would should could may might must do does did so if then thus however because between '
    'over under about after before through during without within very most much many some any all no one two us '
    'you he she his her i me my your'.split())
MAX_ENTRY_LINES = 10
# 无标题参考文献（第三轮收紧）：只有强结构证据才剔除，宁可误报不可漏判。
ENTRY_MARKER = re.compile(r'^\s*(?:\[\d{1,4}\]|\d{1,3}\.\s)')
AUTHOR_LEAD = re.compile(r"^\s*(?:[A-Z][\w'\u2019\-]+,\s+(?:[A-Z]\.\s?)+|(?:[A-Z]\.\s?){1,3}[A-Z][\w'\u2019\-]+)")
NAME_PARTICLES = frozenset('and et al al. & van von der den de da del di du la le dos das y'.split())


def _is_name_token(token: str) -> bool:
    """作者名中的词：首字母大写（含 Ł、É 等非 ASCII 大写）且只由字母、连字符、撇号、句点组成，或常见姓名小词。"""
    if token in NAME_PARTICLES:
        return True
    return token[:1].isupper() and all(ch.isalpha() or ch in ".-'\u2019" for ch in token)
# 正文否决：出现任一硬否决，或软信号合计 ≥2，该块就不是文献条目。
HARD_METRIC = re.compile(
    r'%|\u00b1|\+/-|\b(?:accuracy|acc|bleu|rouge(?:-\w+)?|f1|perplexity|ppl|psnr|ssim|mAP|auc|wer|cer|top-?[15]|error rate|'
    r'win rate|speedup|score)\b[^.;]{0,12}?\d|\d(?:\.\d+)?\s*(?:points?|bleu|f1|db)\b', re.IGNORECASE)
SHORT_DECIMAL = re.compile(r'(?<![\w:./-])\d{1,3}\.\d{1,2}(?![\w./-])')
NARRATIVE_CITE = re.compile(r'\b[A-Z][a-z]+(?:\s+et\s+al\.?|\s+and\s+[A-Z][a-z]+)?,?\s+\((?:19|20)\d{2}[a-z]?\)')
ET_AL = re.compile(r'\bet\s+al\b')
PRONOUN = re.compile(r'\b(?:we|our|ours|us)\b', re.IGNORECASE)
BE_HAVE = re.compile(r'\b(?:is|are|was|were|has|have|had|been|being)\b')
RESEARCH_VERB = re.compile(
    r'(?<![\w-])(?:propose[sd]?|introduce[sd]?|show(?:s|ed|n)?|demonstrate[sd]?|presented|found|find|trained|train|'
    r'evaluate[sd]?|used|use[s]?|achieve[sd]?|reported|report|obtain(?:s|ed)?|reached|studied|extended|applied|observed|'
    r'improved|improving|reduced|compared|outperform(?:s|ed)?|released|matched|fit|cast|follow(?:s|ed)?|adopt(?:s|ed)?)\b')
SENTENCE_START = re.compile(
    r'(?:^|[.;!?]\s+)(?:We|Our|This|These|Those|They|It|Its|Their|However|Moreover|Furthermore|Finally|Overall|Notably|'
    r'Specifically|Compared|Similarly|Additionally|Here|Thus|Hence|Following|In contrast)\b')
HEADINGLESS_ENTRY_STOPWORDS = 0.30
HEADINGLESS_MAX_ENTRY_WORDS = 90
HEADINGLESS_MAX_ENTRY_LINES = 8
HEADINGLESS_MARGIN_TOLERANCE = 3.0
HEADINGLESS_MAX_DOCUMENT_FRACTION = 0.5
SHORT_GROUP_WORDS = 6
# 虚词比例阈值：实测文献条目 0.10–0.29，英文正文 0.40–0.50（含夹带引用的正文）。
REGION_ENTRY_STOPWORDS = 0.33
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
                'author': bool(AUTHOR.search(text)), 'venue': bool(VENUE.search(text) or VENUE_IN.search(text)),
                'comma_dense': bool(words) and text.count(',') / len(words) >= 0.10}
    features['score'] = (2 * features['marker'] + features['year'] + features['author'] + features['venue']
                         + features['comma_dense'])
    return features


def prose_veto(text: str) -> list[str]:
    """句子式正文的否决理由（空表示不否决）：指标枚举、多个年份/叙述式引用、第一人称、谓语动词、句首连接词。"""
    reasons = []
    if HARD_METRIC.search(text):
        reasons.append('metric')
    if len(SHORT_DECIMAL.findall(text)) >= 2:
        reasons.append('decimals')
    if len(YEAR.findall(text)) >= 3:
        reasons.append('many_years')
    if len(NARRATIVE_CITE.findall(text)) >= 2 or len(ET_AL.findall(text)) >= 2:
        reasons.append('narrative_citations')
    soft = (min(len(PRONOUN.findall(text)), 2) + len(BE_HAVE.findall(text)) + len(RESEARCH_VERB.findall(text))
            + 2 * len(SENTENCE_START.findall(text)) + (1 if ';' in text else 0))
    if soft >= 2:
        reasons.append('sentence_like')
    return reasons


def entry_lead(text: str) -> str | None:
    """条目开头的结构证据：[n] / n. 编号，或作者开头（Surname, X. / X. Surname / 作者列表后紧跟年份）。"""
    if ENTRY_MARKER.match(text):
        return 'marker'
    if AUTHOR_LEAD.match(text):
        return 'author'
    text = re.sub(r'(\w)-\s+([a-z])', r'\1\2', text)  # 行尾连字符断词（Pap- pas → Pappas）
    match = YEAR.search(text)
    if match and match.start() <= 400:
        prefix = text[:match.start()].strip().rstrip('(').strip()
        tokens = [t.strip(',;:') for t in prefix.split()]
        tokens = [t for t in tokens if t]
        acl_year = bool(re.match(r'\s*\(?(?:19|20)\d{2}[a-z]?\)?\.', text[match.start() - (1 if text[match.start() - 1:match.start()] == '(' else 0):]))
        if (len(tokens) >= 2 and prefix[-1:] in '.,'
                and (',' in prefix or ' and ' in prefix or '&' in prefix or (acl_year and prefix.endswith('.')))
                and all(_is_name_token(t) for t in tokens)):
            return 'author_list'
    return None


def headingless_entry_class(group: dict[str, Any], *, region: bool = False) -> str:
    """逐块分类：strong（编号/作者开头 + 年份 + 出处信号）、weak（只缺年份或出处之一，或栏/页首的残段）、
    short（页码等极短组）、break（其它，包括被否决的正文）。weak 默认计数，见 _decide_entries。
    region=True 时用于 References 标题之后的区域（条目长度与虚词比例上限略宽）。"""
    text = group['text']
    f = citation_features(text)
    if f['words'] < SHORT_GROUP_WORDS and not prose_veto(text):
        return 'short'
    max_words, max_lines, max_stop = ((MAX_ENTRY_WORDS, MAX_ENTRY_LINES, REGION_ENTRY_STOPWORDS) if region else
                                      (HEADINGLESS_MAX_ENTRY_WORDS, HEADINGLESS_MAX_ENTRY_LINES, HEADINGLESS_ENTRY_STOPWORDS))
    if (f['words'] > max_words or len(group['rows']) > max_lines or f['stopword_ratio'] > max_stop
            or prose_veto(text)):
        return 'break'
    lead = entry_lead(text)
    if lead and f['year'] and f['venue']:
        return 'strong'
    if (lead or group.get('column_start')) and (f['year'] or f['venue']):
        return 'weak'
    if lead == 'marker' and group.get('column_end') and not text.rstrip().endswith('.'):
        return 'weak'  # 栏底/页底被截断的编号条目头（下一栏/页续接）
    return 'break'


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
    seen_columns: set[str] = set()
    last_in_column = {g['rows'][0]['col']: id(g) for g in groups
                      if len(LATIN_WORD.findall(' '.join(r['text'] for r in g['rows']))) >= 2}  # 忽略页码
    for group in groups:
        group['column_end'] = last_in_column.get(group['rows'][0]['col']) == id(group)
        group['text'] = ' '.join(r['text'] for r in group['rows'])
        group['code'] = sum(r['code'] for r in group['rows'])
        group['page'] = page.number + 1
        column = group['rows'][0]['col']
        group['column_start'] = column not in seen_columns
        group['x0'] = group['rows'][0]['x0']
        seen_columns.add(column)
    return groups


def _preview(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= 100 else text[:97] + '...'


def _mark_headingless_runs(pages: list[list[dict[str, Any]]], allowed_pages: set[int] | None) -> list[dict[str, Any]]:
    """无标题参考文献：只剔除同时满足以下全部条件的连续条目段，否则照常计数（宁可误报）。

    - 段内每块逐一分类（headingless_entry_class），被否决的正文或其它非条目块立即打断连续段；
    - 至少 3 条 strong，且 strong 占条目的 2/3 以上，strong 条目的虚词比例均值 ≤ 0.27；
    - strong 条目首行左边距一致（同栏内相差 ≤ 3pt）；
    - 位于文档末尾或节末：段后直到文档结束或下一个附录类标题之间只有极短组；
    - 源文侧：全文剔除量不超过源文英文词总数的一半；译文侧：只在源文已接受的页上接受。
    """
    sequence = [g for groups in pages for g in groups]
    total_words = sum(len(LATIN_WORD.findall(g['text'])) for g in sequence)
    runs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    segment: list[dict[str, Any]] = []

    def close(index: int) -> None:
        members, seg = list(current), list(segment)
        current.clear(); segment.clear()
        strong = [g for g in members if g['_class'] == 'strong']
        if not strong:
            return
        after = next((g for g in sequence[index:] if not (g['_class'] == 'short' and g['kind'] is None)), None)
        margins: dict[str, list[float]] = {}
        for g in strong:
            margins.setdefault(g['rows'][0]['col'], []).append(g['x0'])
        pages_ = sorted({g['page'] for g in members})
        mean_stop = sum(citation_features(g['text'])['stopword_ratio'] for g in strong) / len(strong)
        if len(strong) < HEADINGLESS_MIN_RUN:
            reason = 'too_few_strong_entries'
        elif len(strong) * 3 < len(members) * 2:
            reason = 'weak_entries_dominate'
        elif mean_stop > HEADINGLESS_RUN_MEAN_STOPWORDS:
            reason = 'high_stopword_ratio'
        elif any(max(xs) - min(xs) > HEADINGLESS_MARGIN_TOLERANCE for xs in margins.values()):
            reason = 'inconsistent_margin'
        elif after is not None and after['kind'] != 'end_heading':
            reason = 'not_at_document_or_section_end'
        elif allowed_pages is not None and not set(pages_) <= allowed_pages:
            reason = 'no_matching_source_run'
        else:
            reason = 'accepted'
        runs.append({'pages': pages_, 'entries': len(members), 'strong_entries': len(strong),
                     'weak_entries': len(members) - len(strong), 'reason': reason,
                     'first_entry': _preview(members[0]['text']), 'last_entry': _preview(members[-1]['text']),
                     '_members': members, '_segment': seg})

    for index, group in enumerate(sequence):
        free = group['exclude'] is None and not group['in_region'] and group['kind'] is None
        group['_class'] = headingless_entry_class(group) if free else 'break'
        if group['_class'] in ('strong', 'weak'):
            current.append(group); segment.append(group)
        elif group['_class'] == 'short' and current:
            segment.append(group)
        elif current:
            close(index)
    if current:
        close(len(sequence))
    label = 'reference_entries_headingless'
    for record in runs:
        if record['reason'] == 'accepted':
            record['entries_detail'] = _decide_entries(record['_segment'], label)
    if allowed_pages is None:
        excluded = sum(r['words'] for rec in runs if rec['reason'] == 'accepted'
                       for r in rec['entries_detail'] if r['decision'] == 'excluded')
        if excluded > HEADINGLESS_MAX_DOCUMENT_FRACTION * total_words:
            for record in runs:
                if record['reason'] == 'accepted':
                    record['reason'] = 'exceeds_document_fraction'
                    for g in record['_segment']:
                        if g.get('exclude') == label:
                            g['exclude'] = None
    for record in runs:
        record['accepted'] = record['reason'] == 'accepted'
        if not record['accepted']:
            record['entries_detail'] = [_entry_row(g, 'counted', 'run_rejected:' + record['reason'])
                                        for g in record['_members']]
        record['excluded_words'] = sum(r['words'] for r in record['entries_detail'] if r['decision'] == 'excluded')
        del record['_members'], record['_segment']
    return runs


def _marker_number(text: str) -> int | None:
    match = re.match(r'^\s*\[?(\d{1,4})[\].]', text)
    return int(match.group(1)) if match and ENTRY_MARKER.match(text) else None


def _entry_row(group: dict[str, Any], decision: str, reason: str) -> dict[str, Any]:
    return {'page': group['page'], 'class': group['_class'], 'decision': decision, 'reason': reason,
            'words': len(LATIN_WORD.findall(group['text'])), 'preview': _preview(group['text'])}


def _decide_entries(seq: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    """对一段按阅读顺序排列的块（已分类）逐条决定剔除或计数，并返回逐条审计记录。

    strong 剔除；weak 默认计数，只有正面证据才剔除：
    - numbered_sequence：带 [n]/n. 编号、≤40 词（栏底被截断、虚词比例 ≤0.15 的条目头不限词数），紧邻的带编号条目与之连续（n-1 或 n+1），且不存在不连续的紧邻编号；
    - continuation：栏首/页首、无编号也无作者开头，紧接在一个已剔除且未以句号结束的条目之后，
      左边距不在该栏 strong 条目边距之外（悬挂缩进一致）。
    break 与 short 计数（short 不进审计）。"""
    rows: list[dict[str, Any]] = []
    margins: dict[str, float] = {}
    for g in seq:
        if g['_class'] == 'strong':
            col = g['rows'][0]['col']
            margins[col] = min(margins.get(col, g['x0']), g['x0'])
    solid = [g for g in seq if g['_class'] != 'short']
    for index, g in enumerate(solid):
        cls = g['_class']
        if cls == 'break':
            rows.append(_entry_row(g, 'counted', 'not_an_entry'))
            continue
        if cls == 'strong':
            g['exclude'] = label
            rows.append(_entry_row(g, 'excluded', 'strong_entry'))
            continue
        prev = solid[index - 1] if index > 0 else None
        nxt = solid[index + 1] if index + 1 < len(solid) else None
        reason = 'weak_no_positive_evidence'
        number = _marker_number(g['text'])
        cut_head = (g.get('column_end') and not g['text'].rstrip().endswith('.')
                    and citation_features(g['text'])['stopword_ratio'] <= 0.15)
        if number is not None and (len(LATIN_WORD.findall(g['text'])) <= 40 or cut_head):
            neighbours = [(n, _marker_number(n['text'])) for n in (prev, nxt) if n is not None and n['_class'] in ('strong', 'weak')]
            numbered = [(n, k) for n, k in neighbours if k is not None]
            expected = {id(prev): number - 1, id(nxt): number + 1}
            if numbered and all(k == expected[id(n)] for n, k in numbered):
                reason = 'numbered_sequence'
        elif (entry_lead(g['text']) is None and g.get('column_start') and prev is not None and prev.get('exclude')
              and not prev['text'].rstrip().endswith('.')
              and g['x0'] >= margins.get(g['rows'][0]['col'], g['x0']) - HEADINGLESS_MARGIN_TOLERANCE):
            reason = 'continuation'
        if reason == 'weak_no_positive_evidence':
            rows.append(_entry_row(g, 'counted', reason))
        else:
            g['exclude'] = label
            rows.append(_entry_row(g, 'excluded', reason))
    return rows


def split_counted_text(document, allowed_pages: set[int] | None = None):
    """逐页返回计数文本、剔除统计、参考文献所在页与无标题参考文献审计记录。

    参考文献区按阅读顺序跨页延续，直到附录类标题；allowed_pages 不为 None 时（译文侧），
    无标题参考文献只在这些页上接受。"""
    pages = [_page_groups(page) for page in document]
    in_region = False
    for groups in pages:
        for group in groups:
            group['exclude'] = None
            if group['kind'] == 'reference_heading':
                in_region, group['exclude'] = True, 'reference_section'
            elif group['kind'] == 'end_heading':
                in_region = False
            group['in_region'] = in_region and group['kind'] is None
    # References 标题之后：与无标题段同一套逐条规则（strong 剔除，weak 需正面证据，其余计数）。
    region_seq = [g for groups in pages for g in groups if g['in_region']]
    for g in region_seq:
        g['_class'] = headingless_entry_class(g, region=True)
    region_rows = _decide_entries(region_seq, 'reference_section')
    audit = _mark_headingless_runs(pages, allowed_pages)
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
    return counted_pages, excluded_pages, reference_pages, {'headingless_runs': audit, 'region_entries': region_rows}


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


ZH_MIN_SOURCE_CHARS = 100
ZH_PAGE_HIGH = 0.30
ZH_PAGE_MEDIUM = 0.10
ZH_DOCUMENT_HIGH = 0.25
ZH_VERBATIM_MIN_CHARS = 12
# 所有页都短于 ZH_MIN_SOURCE_CHARS 时，按整份文件合计评估的最低中文字符数。
ZH_DOCUMENT_MIN_SOURCE_CHARS = 24
# 中文残留计数含康熙部首/部首补充与兼容汉字：部分中文 PDF 字体把常用字映射到这些码位。
CJK_WIDE = re.compile(r'[\u2e80-\u2fdf\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
CJK_PUNCT = re.compile(r'[\u3000-\u303f\uff01\uff08\uff09\uff0c\uff1a\uff1b\uff1f]')


def page_chinese_residue(source_text: str, target_text: str) -> dict[str, Any]:
    source_chars = len(CJK_WIDE.findall(source_text))
    target_chars = len(CJK_WIDE.findall(target_text))
    candidates = [re.sub(r'\s+', '', line) for line in source_text.splitlines()]
    candidates = [line for line in candidates if len(CJK_WIDE.findall(line)) >= ZH_VERBATIM_MIN_CHARS]
    joined = re.sub(r'\s+', '', target_text)
    verbatim = sum(1 for line in candidates if line in joined)
    ratio = target_chars / source_chars if source_chars else 0.0
    evaluated = source_chars >= ZH_MIN_SOURCE_CHARS
    severity = (('high' if ratio >= ZH_PAGE_HIGH else 'medium' if ratio >= ZH_PAGE_MEDIUM else 'ok')
                if evaluated else 'not_evaluated')
    # 短页（源文中文不足 ZH_MIN_SOURCE_CHARS）不按比例评估，但整行中文源句（>= ZH_VERBATIM_MIN_CHARS 个汉字）
    # 逐字出现在译文里是直接的未翻译证据，判 high。
    short_page_verbatim = not evaluated and verbatim > 0
    if short_page_verbatim:
        severity = 'high'
    return {'source_cjk_chars': source_chars, 'target_cjk_chars': target_chars,
            'target_cjk_punctuation': len(CJK_PUNCT.findall(target_text)),
            'target_latin_words': len(LATIN_WORD.findall(target_text)), 'residue_ratio': round(ratio, 4),
            'verbatim_source_lines': verbatim, 'source_lines_checked': len(candidates),
            'evaluated': evaluated, 'short_page_verbatim': short_page_verbatim, 'severity': severity}


# 中译英时英文译文用 babeldoc 自带的 Noto 字体排版；源文保留字形（未翻译的公式碎片、变量）仍是原字体。
TRANSLATED_FONT_PATTERN = re.compile(r'Noto', re.IGNORECASE)
OVERLAP_MIN_FRACTION = 0.5
# 任何一个源文保留字形与译文字形压叠都判 high（评审第 2 轮：不按整页净计数放行）。
OVERLAP_PAGE_MIN_CHARS = 1


def _glyph_boxes(page):
    import fitz

    boxes = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for char in span['chars']:
                    if char['c'].isalnum():
                        boxes.append((span['font'], char['c'], fitz.Rect(char['bbox'])))
    return boxes


def page_retained_glyph_overlap(page, translated_font_pattern=None) -> dict[str, Any]:
    """源文保留字形与英文译文字形相互压叠的字符数；达到 OVERLAP_PAGE_MIN_CHARS 时该页判 high（失败关闭）。"""
    translated_font_pattern = translated_font_pattern or TRANSLATED_FONT_PATTERN
    boxes = _glyph_boxes(page)
    translated = [b for b in boxes if translated_font_pattern.search(b[0])]
    retained = [b for b in boxes if not translated_font_pattern.search(b[0])]
    samples, count = [], 0
    for font, char, rect in retained:
        area = rect.get_area()
        if area <= 0:
            continue
        for _, other_char, other in translated:
            inter = rect & other
            if not inter.is_empty and inter.get_area() > OVERLAP_MIN_FRACTION * min(area, other.get_area()):
                count += 1
                if len(samples) < 5:
                    samples.append({'retained': char, 'font': font, 'translated': other_char,
                                    'bbox': [round(v, 1) for v in rect]})
                break
    return {'retained_glyphs': len(retained), 'overlapping_glyphs': count, 'samples': samples,
            'flagged': count >= OVERLAP_PAGE_MIN_CHARS}


# 字形大小的填充矢量路径（MathJax/网页打印公式把数学字形画成路径）。排版引擎会丢弃译文段落内的这类路径，
# 成品比源页少 >= VECTOR_GLYPH_LOSS_MIN 个且 >= VECTOR_GLYPH_LOSS_FRACTION 时判 high（失败关闭）。
VECTOR_GLYPH_MAX_SIDE = 24.0
VECTOR_GLYPH_LOSS_MIN = 3
VECTOR_GLYPH_LOSS_FRACTION = 0.25


def _vector_glyph_count(page) -> int:
    count = 0
    for drawing in page.get_drawings():
        if drawing.get('fill') is None:
            continue
        rect = drawing['rect']
        if (rect.width <= VECTOR_GLYPH_MAX_SIDE and rect.height <= VECTOR_GLYPH_MAX_SIDE
                and max(rect.width, rect.height) >= 2 and min(rect.width, rect.height) >= 0.8):
            count += 1
    return count


def page_vector_glyph_loss(source_page, target_page) -> dict[str, Any]:
    source, target = _vector_glyph_count(source_page), _vector_glyph_count(target_page)
    lost = max(0, source - target)
    return {'source_vector_glyphs': source, 'target_vector_glyphs': target, 'lost': lost,
            'flagged': lost >= VECTOR_GLYPH_LOSS_MIN and lost >= VECTOR_GLYPH_LOSS_FRACTION * source}


# 源文中文正文行内已定位的结构对象（矢量公式字形、Form XObject 变量）在成品中的核对容差（pt）。
INLINE_OBJECT_MATCH_TOLERANCE = 1.5
INLINE_OBJECT_COLLISION_FRACTION = 0.3


def _target_text_boxes(page):
    import fitz

    boxes = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for char in span['chars']:
                    if char['c'].strip():
                        boxes.append((char['c'], fitz.Rect(char['bbox'])))
    return boxes


def _collides(rect, others, fraction=INLINE_OBJECT_COLLISION_FRACTION) -> str | None:
    area = rect.get_area()
    for char, other in others:
        inter = rect & other
        if area > 0 and not inter.is_empty and inter.get_area() > fraction * min(area, other.get_area() or area):
            return char
    return None


def page_inline_object_damage(source_doc, page_index: int, target_page) -> dict[str, Any]:
    """逐个核对源页中文正文行内已定位的结构对象：成品中缺失（丢失）或与译文字形压叠，任何一个都判 high。"""
    import fitz
    from pdf_input_preflight import inline_object_math

    located = inline_object_math(source_doc, page_index, with_objects=True)['objects']
    tol = INLINE_OBJECT_MATCH_TOLERANCE
    text = _target_text_boxes(target_page)
    paths = [d['rect'] for d in target_page.get_drawings() if d.get('fill') is not None] if located else []
    used: set[int] = set()
    lost, collided = [], []
    for obj in located:
        rect = fitz.Rect(obj['bbox'])
        if obj['kind'] == 'vector_glyph':
            match = next((r for r in paths if abs(r.x0 - rect.x0) <= tol and abs(r.y0 - rect.y0) <= tol
                          and abs(r.x1 - rect.x1) <= tol and abs(r.y1 - rect.y1) <= tol), None)
            if match is None:
                lost.append(obj)
            elif (hit := _collides(match, text)):
                collided.append(dict(obj, with_text=hit))
        else:
            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
            index = next((i for i, (char, box) in enumerate(text) if i not in used and char == obj['char']
                          and abs((box.x0 + box.x1) / 2 - cx) <= tol + 1 and abs((box.y0 + box.y1) / 2 - cy) <= tol + 1), None)
            if index is None:
                lost.append(obj)
                continue
            used.add(index)
            box = text[index][1]
            others = [item for i, item in enumerate(text) if i != index]
            if (hit := _collides(box, others, OVERLAP_MIN_FRACTION)):
                collided.append(dict(obj, with_text=hit))
    return {'located': len(located), 'lost': len(lost), 'collided': len(collided),
            'samples': (lost + collided)[:5], 'flagged': bool(lost or collided)}


def check_chinese_residue(source_pdf, target_pdf) -> dict[str, Any]:
    """中译英：基于最终 PDF 的中文残留检查（不依赖 translation blocks 自报）。"""
    import fitz

    result: dict[str, Any] = {'schema_version': 1, 'check': 'render_chinese_residue', 'target_language': 'en',
                              'source': str(source_pdf), 'target': str(target_pdf) if target_pdf else None,
                              'thresholds': {'page_high': ZH_PAGE_HIGH, 'page_medium': ZH_PAGE_MEDIUM,
                                             'document_high': ZH_DOCUMENT_HIGH, 'min_source_chars': ZH_MIN_SOURCE_CHARS,
                                             'verbatim_min_chars': ZH_VERBATIM_MIN_CHARS,
                                             'document_min_source_chars': ZH_DOCUMENT_MIN_SOURCE_CHARS},
                              'pages': []}
    if not target_pdf or not Path(target_pdf).is_file():
        result.update(status='not_evaluated', severity='ok', reason='target_pdf_missing')
        return result
    with fitz.open(source_pdf) as source, fitz.open(target_pdf) as target:
        count = min(len(source), len(target))
        result['page_count_source'], result['page_count_target'] = len(source), len(target)
        for index in range(count):
            row = page_chinese_residue(source[index].get_text(), target[index].get_text())
            row['page'] = index + 1
            row['retained_glyph_overlap'] = page_retained_glyph_overlap(target[index])
            row['vector_glyph_loss'] = page_vector_glyph_loss(source[index], target[index])
            row['inline_object_damage'] = page_inline_object_damage(source, index, target[index])
            result['pages'].append(row)
    evaluated = [p for p in result['pages'] if p['evaluated']]
    scope = 'pages'
    if not evaluated:
        # 每页都太短时改按整份文件合计评估，避免短文件整份原样返回也被判为 not_evaluated/ok。
        whole = [p for p in result['pages'] if p['source_cjk_chars']]
        if sum(p['source_cjk_chars'] for p in whole) >= ZH_DOCUMENT_MIN_SOURCE_CHARS:
            evaluated, scope = whole, 'document'
    total_source = sum(p['source_cjk_chars'] for p in evaluated)
    total_target = sum(p['target_cjk_chars'] for p in evaluated)
    overall = total_target / total_source if total_source else 0.0
    high_pages = [p['page'] for p in result['pages'] if p['severity'] == 'high']
    medium_pages = [p['page'] for p in result['pages'] if p['severity'] == 'medium']
    short_verbatim_pages = [p['page'] for p in result['pages'] if p.get('short_page_verbatim')]
    overlap_pages = [p['page'] for p in result['pages'] if p['retained_glyph_overlap']['flagged']]
    vector_loss_pages = [p['page'] for p in result['pages'] if p['vector_glyph_loss']['flagged']]
    inline_damage_pages = [p['page'] for p in result['pages'] if p['inline_object_damage']['flagged']]
    # 源文保留字形（行内变量、公式碎片）与英文译文压叠时读者无法辨认，按失败关闭处理（high，退出码 3）。
    # 矢量路径公式字形在成品中丢失同样失败关闭。
    # 中文正文行内已定位的结构对象：任何一个丢失或与译文压叠都失败关闭。
    severity = ('high' if (evaluated and overall >= ZH_DOCUMENT_HIGH) or high_pages or overlap_pages or vector_loss_pages
                or inline_damage_pages
                else 'medium' if medium_pages else 'ok')
    result['thresholds'].update(overlap_min_fraction=OVERLAP_MIN_FRACTION, overlap_page_min_chars=OVERLAP_PAGE_MIN_CHARS,
                                vector_glyph_loss_min=VECTOR_GLYPH_LOSS_MIN,
                                vector_glyph_loss_fraction=VECTOR_GLYPH_LOSS_FRACTION,
                                inline_object_match_tolerance=INLINE_OBJECT_MATCH_TOLERANCE,
                                inline_object_damage_min=1)
    result.update(status='evaluated' if evaluated else 'not_evaluated', evaluation_scope=scope,
                  overall_residue_ratio=round(overall, 4), high_pages=high_pages, medium_pages=medium_pages,
                  short_page_verbatim_pages=short_verbatim_pages, retained_glyph_overlap_pages=overlap_pages,
                  vector_glyph_loss_pages=vector_loss_pages, inline_object_damage_pages=inline_damage_pages,
                  severity=severity, quality_fail=severity == 'high')
    return result


def check_render_residue(source_pdf, target_pdf, *, target_language: str = 'zh') -> dict[str, Any]:
    import fitz

    if target_language == 'en':
        return check_chinese_residue(source_pdf, target_pdf)

    result: dict[str, Any] = {'schema_version': 1, 'check': 'render_english_residue', 'target_language': target_language,
                              'source': str(source_pdf), 'target': str(target_pdf) if target_pdf else None,
                              'thresholds': {'page_high': PAGE_HIGH, 'page_medium': PAGE_MEDIUM,
                                             'document_high': DOCUMENT_HIGH, 'min_source_words': MIN_SOURCE_WORDS},
                              'pages': []}
    if target_language != 'zh':
        result.update(status='not_applicable', severity='ok', reason='unsupported_target_language')
        return result
    if not target_pdf or not Path(target_pdf).is_file():
        result.update(status='not_evaluated', severity='ok', reason='target_pdf_missing')
        return result
    with fitz.open(source_pdf) as source, fitz.open(target_pdf) as target:
        # mono 成品与源页一一对应；页数不一致时只比较共同页并记录。
        count = min(len(source), len(target))
        result['page_count_source'], result['page_count_target'] = len(source), len(target)
        source_text, source_excluded, source_refs, source_audit = split_counted_text(source)
        source_runs = source_audit['headingless_runs']
        accepted_pages = {page for run in source_runs if run['accepted'] for page in run['pages']}
        target_text, target_excluded, target_refs, target_audit = split_counted_text(target, accepted_pages)
        target_runs = target_audit['headingless_runs']
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
            'headingless_runs': {'source': source_runs, 'target': target_runs},
            'reference_region_entries': {'source': source_audit['region_entries'], 'target': target_audit['region_entries']},
            'headingless_rules': {'max_document_fraction': HEADINGLESS_MAX_DOCUMENT_FRACTION,
                                  'min_strong_entries': HEADINGLESS_MIN_RUN,
                                  'max_entry_stopword_ratio': HEADINGLESS_ENTRY_STOPWORDS,
                                  'max_run_mean_stopword_ratio': HEADINGLESS_RUN_MEAN_STOPWORDS,
                                  'margin_tolerance_pt': HEADINGLESS_MARGIN_TOLERANCE},
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
    parser.add_argument('--target-language', choices=('zh', 'en'), default='zh')
    args = parser.parse_args(argv)
    result = check_render_residue(args.source, args.target, target_language=args.target_language)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 2 if result.get('quality_fail') else 0


if __name__ == '__main__':
    raise SystemExit(main())
