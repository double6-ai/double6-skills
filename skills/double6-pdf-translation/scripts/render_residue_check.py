# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""基于实际渲染成品的英文残留检查（最小版）。

逐页比较源 PDF 与译文 PDF 中可抽取的拉丁词数量：残留率 r = 译文拉丁词 / 源文拉丁词。
正常英译中保留人名、引用、公式变量等，实测 r≈0.05–0.15；整页未翻译时 r≈1。
本检查直接读最终 PDF，能发现从未进入翻译请求的文本（例如图表标签），
也能发现模型原样返回英文的情况；不依赖 translation blocks 的自报结果。

按 skill 规则本就不翻译的内容不计入残留率（源与译文两侧同样剔除，并逐页记录剔除词数）：
参考文献/Bibliography 段（直到附录标题）、等宽字体代码、URL/DOI/邮箱/arXiv 编号、
方括号编号引用与作者-年份引用（含 et al.）。
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


# 参考文献段起止：整行只有标题（可带章节号）。附录类标题恢复计数。
REFERENCE_HEADING = re.compile(
    r'^\s*(?:[0-9IVX]+(?:\.[0-9]+)*\.?\s+)?(?:references?|bibliography|works\s+cited|literature\s+cited|'
    r'reference\s+list|参考文献|参考资料|引用文献)\s*[:：]?\s*$', re.IGNORECASE)
RESUME_HEADING = re.compile(
    r'^\s*(?:[A-Z](?:\.[0-9]+)*\.?\s+)?(?:appendix|appendices|supplementary(?:\s+materials?)?|附录|补充材料)\b',
    re.IGNORECASE)
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


def _is_code_span(span: dict[str, Any]) -> bool:
    return bool(int(span.get('flags', 0)) & 8) or bool(MONO_FONT.search(span.get('font', '') or ''))


def _page_lines(page) -> list[tuple[str, int]]:
    """按内容流顺序返回 (行文本, 等宽代码拉丁词数)；等宽代码从行文本中剔除。"""
    lines = []
    for block in page.get_text('dict').get('blocks', []):
        for line in block.get('lines', []):
            kept, code_words = [], 0
            for span in line.get('spans', []):
                text = span.get('text', '')
                if _is_code_span(span):
                    code_words += len(LATIN_WORD.findall(text))
                else:
                    kept.append(text)
            lines.append((''.join(kept), code_words))
    return lines


def _block_heading_text(page) -> list[str]:
    return [' '.join(''.join(s.get('text', '') for s in l.get('spans', [])) for l in b.get('lines', [])).strip()
            for b in page.get_text('dict').get('blocks', []) if b.get('lines')]


def split_counted_text(document) -> tuple[list[str], list[dict[str, int]], list[int]]:
    """逐页返回计数文本与剔除统计；参考文献段跨页延续，直到附录标题。"""
    counted_pages, excluded_pages, reference_pages = [], [], []
    in_references = False
    for page in document:
        counted, stats = [], {'reference_section': 0, 'code': 0}
        headings = set(h for h in _block_heading_text(page) if len(h) <= 40)
        for text, code_words in _page_lines(page):
            stripped = text.strip()
            stats['code'] += code_words
            heading = stripped if stripped else ''
            if REFERENCE_HEADING.match(heading) or (heading and heading in headings and REFERENCE_HEADING.match(heading)):
                in_references = True
                if page.number + 1 not in reference_pages:
                    reference_pages.append(page.number + 1)
                stats['reference_section'] += len(LATIN_WORD.findall(stripped))
                continue
            if in_references and RESUME_HEADING.match(stripped):
                in_references = False
            if in_references:
                stats['reference_section'] += len(LATIN_WORD.findall(text))
                if page.number + 1 not in reference_pages:
                    reference_pages.append(page.number + 1)
                continue
            counted.append(text)
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


def page_residue(source_text: str, target_text: str) -> dict[str, Any]:
    source_words = len(LATIN_WORD.findall(source_text))
    target_words = len(LATIN_WORD.findall(target_text))
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
            row = page_residue(source_text[index], target_text[index])
            row['page'] = index + 1
            row['excluded_source_words'] = sum(source_excluded[index].values())
            row['excluded_target_words'] = sum(target_excluded[index].values())
            row['excluded_source_breakdown'] = {k: v for k, v in source_excluded[index].items() if v}
            result['pages'].append(row)
        result['excluded'] = {
            'rules': ['reference_section', 'code'] + [name for name, _ in INLINE_EXCLUSIONS],
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
