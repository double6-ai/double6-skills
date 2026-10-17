# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""基于实际渲染成品的英文残留检查（最小版）。

逐页比较源 PDF 与译文 PDF 中可抽取的拉丁词数量：残留率 r = 译文拉丁词 / 源文拉丁词。
正常英译中保留人名、引用、公式变量等，实测 r≈0.05–0.15；整页未翻译时 r≈1。
本检查直接读最终 PDF，能发现从未进入翻译请求的文本（例如图表标签），
也能发现模型原样返回英文的情况；不依赖 translation blocks 的自报结果。
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
        for index in range(count):
            row = page_residue(source[index].get_text(), target[index].get_text())
            row['page'] = index + 1
            result['pages'].append(row)
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
