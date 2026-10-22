# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：2.0.0-rc.3 新增；变更见Skill根目录MODIFICATIONS.md。
"""PDF 输入的结构化预检：细分错误码、权限警告、页数范围、非电子页与源语言。

所有动作共用同一结构化结果：``findings`` 中每项含 ``code``、``severity``
（error/warning/info）、``message`` 和 ``details``；存在 error 级发现时
``status`` 为 ``blocked``，并给出首个 ``error_code``。本模块只读输入，不改写源文件。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DIGITAL_MAX_PAGES = 5
MAX_INPUT_BYTES = 100 * 1024 * 1024

# code -> (severity, 中文说明)
CODES: dict[str, tuple[str, str]] = {
    'input_not_found': ('error', '输入文件不存在。'),
    'input_too_large': ('error', '输入文件超过 100 MiB 有界范围。'),
    'not_a_pdf': ('error', '文件头不是 %PDF，不是 PDF 文件。'),
    'pdf_truncated_or_corrupt': ('error', 'PDF 已损坏或被截断（无法打开、缺少文件尾或 0 页）。'),
    'pdf_repaired_on_open': ('info', 'PDF 结构在打开时由解析器自动修复；内容完整性已另行检查。'),
    'encrypted_user_password_required': ('error', 'PDF 需要打开密码（用户密码）；本 skill 不破解或猜测密码，请提供未加密副本。'),
    'permissions_restricted': ('warning', 'PDF 设有所有者权限限制（禁止修改/复制等）；继续处理前请确认你有权翻译和再分发该文档。'),
    'page_limit_exceeded': ('error', '页数超出当前路线允许的范围。'),
    'empty_document': ('error', 'PDF 没有任何页面。'),
    'non_digital_pages': ('error', '存在非原生电子页（扫描图像页或无文字层页）；电子 PDF 路线要求全部页面为原生文字层。'),
    'source_language_matches_target': ('error', '源文主要语言已经是目标语言；当前版本支持英译中（en→zh）与中译英（zh→en），不会静默输出原文。'),
    'target_language_unsupported': ('error', '目标语言不受支持；当前版本只支持 zh（英译中）与 en（中译英）。'),
    'zh2en_inline_object_math_unsupported': ('error', '中译英：中文正文行内的变量或公式由 Form XObject 文字或矢量路径字形绘制（例如 MathJax/网页打印公式、嵌入式行内变量）；'
                                             '排版引擎无法让这些对象随英文译文重排，会与译文压叠或丢失，因此在翻译前拒绝。请提供公式为普通文字层的 PDF 或 LaTeX 源。'),
    'target_language_route_unsupported': ('error', '中译英（--target-language en）只支持 candidate --route digital_pdf；LaTeX 路线与 collect 的译者固定译成简体中文。'),
    'source_language_mixed': ('warning', '源文中英混合比例较高，语言判定不确定；请确认源文主体语言与所选翻译方向一致。'),
    'source_language_unknown': ('info', '可抽取文字过少，无法判定源语言（常见于扫描件或文字转曲）。'),
    'page_load_failed': ('error', '部分页面无法解析。'),
    'preflight_guard_stopped': ('error', '输入预检子进程超出内存或时限预算被停止。'),
}

# 支持的目标语言及其对应源语言：zh 目标 = 英译中，en 目标 = 中译英。
SUPPORTED_TARGETS = {'zh': 'en', 'en': 'zh'}
LANGUAGE_NAMES = {'zh': '中文', 'en': '英文'}
_CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
_LATIN_WORD = re.compile(r'[A-Za-z]{2,}')


class PreflightError(ValueError):
    """携带结构化错误码的输入错误；``str(exc)`` 保持为错误码以兼容旧调用方。"""

    def __init__(self, code: str, message: str | None = None, **details: Any):
        super().__init__(code)
        self.code = code
        self.finding = finding(code, message, **details)

    def to_dict(self) -> dict[str, Any]:
        return blocked_result([self.finding])


def finding(code: str, message: str | None = None, **details: Any) -> dict[str, Any]:
    severity, default = CODES.get(code, ('error', code))
    return {'code': code, 'severity': severity, 'message': message or default, 'details': details}


def summarize(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    errors = [f for f in findings if f['severity'] == 'error']
    return {'schema_version': SCHEMA_VERSION, 'status': 'blocked' if errors else 'ok',
            'error_code': errors[0]['code'] if errors else None,
            'warnings': [f['code'] for f in findings if f['severity'] == 'warning'],
            'findings': findings, **extra}


def blocked_result(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    result = summarize(findings, **extra)
    result['status'] = 'blocked'
    if not result['error_code'] and findings:
        result['error_code'] = findings[0]['code']
    return result


def detect_language(text: str) -> dict[str, Any]:
    """按 CJK 字符与拉丁词数量粗判源语言；只区分 zh/en/mixed/unknown。"""
    cjk = len(_CJK.findall(text))
    words = len(_LATIN_WORD.findall(text))
    if cjk + words < 40:
        language = 'unknown'
    elif cjk >= 1.5 * words:
        language = 'zh'
    elif cjk <= 0.2 * words:
        language = 'en'
    else:
        language = 'mixed'
    return {'language': language, 'cjk_chars': cjk, 'latin_words': words,
            'method': 'cjk_char_vs_latin_word_count'}


def classify_page(page) -> dict[str, Any]:
    visible = 0
    for span in page.get_texttrace():
        if span.get('type') == 3 or span.get('opacity', 1) == 0:
            continue
        visible += len(span['chars'])
    area = page.rect.get_area() or 1
    images = page.get_image_info()
    largest = max([abs(_rect_area(x['bbox'])) / area for x in images] + [0])
    drawings = None
    if visible >= 30:
        kind = 'native_text'
    elif largest >= .5:
        kind = 'scanned_image'
    else:
        try:
            drawings = sum(len(item.get('items', ())) for item in page.get_cdrawings())
        except Exception:
            drawings = None
        # 大量矢量路径而几乎无文字：常见于"文字转曲"的 PDF；否则只是稀疏页（空白页、整页图示等）。
        kind = 'no_text_layer' if drawings is not None and drawings >= 5000 else 'sparse_text'
    return {'page': page.number + 1, 'kind': kind, 'visible_glyphs': visible,
            'largest_image_coverage': round(largest, 4), 'vector_path_items': drawings}


def _rect_area(bbox) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _has_pdf_trailer(path: Path) -> bool:
    size = path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(max(0, size - 4096))
        tail = stream.read()
    return b'%%EOF' in tail or b'startxref' in tail


# 中译英行内对象公式检测（结构规则，不用词表）：一行中文正文内部出现 >= INLINE_OBJECT_PAGE_MIN 个
# “行内对象”（Form XObject 绘制的非中文字形，或字形大小的填充矢量路径）即判定该页不受支持。
INLINE_OBJECT_PAGE_MIN = 3


def _cjk_rows(page) -> list[tuple[float, float, float, float]]:
    """页面级（不含 Form XObject）中文正文行：同一文本块内按纵向重叠合并的行，返回 (x0, y0, x1, y1)。"""
    rows = []
    for block in page.get_text('rawdict').get('blocks', []):
        lines = []
        for line in block.get('lines', []):
            chars = [c for span in line['spans'] for c in span['chars'] if c['c'].strip()]
            if sum(1 for c in chars if _CJK.match(c['c'])) >= 2:
                lines.append([min(c['bbox'][0] for c in chars), min(c['bbox'][1] for c in chars),
                              max(c['bbox'][2] for c in chars), max(c['bbox'][3] for c in chars)])
        lines.sort(key=lambda b: (b[1], b[0]))
        merged: list[list[float]] = []
        for box in lines:
            last = merged[-1] if merged else None
            if last and min(last[3], box[3]) - max(last[1], box[1]) > 0.5 * min(last[3] - last[1], box[3] - box[1]):
                last[:] = [min(last[0], box[0]), min(last[1], box[1]), max(last[2], box[2]), max(last[3], box[3])]
            else:
                merged.append(list(box))
        rows.extend(tuple(box) for box in merged)
    return rows


def _char_keys(page) -> list[tuple[str, tuple[int, int, int, int]]]:
    keys = []
    for block in page.get_text('rawdict').get('blocks', []):
        for line in block.get('lines', []):
            for span in line['spans']:
                for char in span['chars']:
                    if char['c'].strip():
                        keys.append((char['c'], tuple(round(v) for v in char['bbox'])))
    return keys


def _inside_row(cx: float, cy: float, rows) -> tuple[float, float, float, float] | None:
    for row in rows:
        x0, y0, x1, y1 = row
        height = y1 - y0
        # 行首左侧（项目符号）不算行内；行内对象中心须落在该行文字范围内部。
        if x0 + 0.3 * height < cx < x1 and y0 <= cy <= y1:
            return row
    return None


def inline_object_math(doc, page_index: int) -> dict[str, Any]:
    """统计一页中文正文行内的 Form XObject 字形与矢量路径字形（结构证据，只读，不改源文件）。"""
    import fitz
    from collections import Counter

    page = doc[page_index]
    scratch = fitz.open()
    try:
        scratch.insert_pdf(doc, from_page=page_index, to_page=page_index)
        bare = scratch[0]
        forms = {item[0] for item in bare.get_xobjects()}
        for xref in forms:
            # 只改内存中的临时副本：清空 Form XObject 内容流，差集即为 Form 绘制的文字。
            scratch.update_stream(xref, b'')
        rows = _cjk_rows(bare)
        remaining = Counter(_char_keys(bare))
        xobject_chars = []
        for key in _char_keys(page):
            if remaining[key] > 0:
                remaining[key] -= 1
            else:
                xobject_chars.append(key)
    finally:
        scratch.close()
    xobject_inline = 0
    for char, (x0, y0, x1, y1) in xobject_chars:
        if not _CJK.match(char) and _inside_row((x0 + x1) / 2, (y0 + y1) / 2, rows):
            xobject_inline += 1
    vector_inline = 0
    for drawing in page.get_drawings():
        if drawing.get('fill') is None:
            continue
        rect = drawing['rect']
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        row = _inside_row(cx, cy, rows)
        if not row:
            continue
        height = row[3] - row[1]
        # 字形大小：不超过约两个字宽、不高于行高的 1.6 倍，且不是细线（下划线/分数线另由文字判断）。
        if rect.width <= 2.0 * height and rect.height <= 1.6 * height and min(rect.width, rect.height) >= 0.12 * height \
                and max(rect.width, rect.height) >= 0.25 * height:
            vector_inline += 1
    return {'page': page_index + 1, 'cjk_rows': len(rows), 'form_xobjects': len(forms),
            'xobject_text_glyphs': xobject_inline, 'vector_glyphs': vector_inline,
            'flagged': xobject_inline >= INLINE_OBJECT_PAGE_MIN or vector_inline >= INLINE_OBJECT_PAGE_MIN}


def inspect_pdf(path, *, max_pages: int | None = DIGITAL_MAX_PAGES, target_language: str = 'zh',
                require_digital: bool = False, language_pages: int = 3) -> dict[str, Any]:
    """返回结构化预检结果；不抛异常，所有问题都进入 findings。"""
    import fitz

    path = Path(path)
    findings: list[dict[str, Any]] = []
    facts: dict[str, Any] = {'input': str(path), 'page_count': None, 'max_pages': max_pages,
                             'pages': [], 'source_language': None, 'encryption': None,
                             'target_language': target_language}
    if target_language not in SUPPORTED_TARGETS:
        return summarize([finding('target_language_unsupported', target_language=target_language)], **facts)
    if not path.is_file():
        return summarize([finding('input_not_found', path=str(path))], **facts)
    if path.stat().st_size > MAX_INPUT_BYTES:
        return summarize([finding('input_too_large', bytes=path.stat().st_size)], **facts)
    with path.open('rb') as stream:
        head = stream.read(1024)
    if b'%PDF-' not in head:
        return summarize([finding('not_a_pdf')], **facts)
    trailer = _has_pdf_trailer(path)
    try:
        doc = fitz.open(path)
    except Exception as exc:  # 解析器对损坏文件抛出多种异常类型
        return summarize([finding('pdf_truncated_or_corrupt', reason=f'{type(exc).__name__}: {exc}'[:300])], **facts)
    with doc:
        facts['encryption'] = (doc.metadata or {}).get('encryption')
        if doc.needs_pass:
            return summarize([finding('encrypted_user_password_required', encryption=facts['encryption'])], **facts)
        count = len(doc)
        facts['page_count'] = count
        if not trailer or count == 0:
            findings.append(finding('pdf_truncated_or_corrupt', trailer_found=trailer, page_count=count,
                                    repaired=bool(getattr(doc, 'is_repaired', False))))
            return summarize(findings, **facts)
        if getattr(doc, 'is_repaired', False):
            findings.append(finding('pdf_repaired_on_open'))
        permissions = doc.permissions
        if facts['encryption']:
            denied = [name for name, bit in (('print', fitz.PDF_PERM_PRINT), ('modify', fitz.PDF_PERM_MODIFY),
                                             ('copy', fitz.PDF_PERM_COPY), ('annotate', fitz.PDF_PERM_ANNOTATE))
                      if not permissions & bit]
            if denied:
                findings.append(finding('permissions_restricted', denied=denied, encryption=facts['encryption']))
        if max_pages is not None and count > max_pages:
            findings.append(finding('page_limit_exceeded',
                                    f'PDF 共 {count} 页，超过当前路线上限 {max_pages} 页；电子 PDF 主入口只接受完整 1–{DIGITAL_MAX_PAGES} 页，'
                                    '长文档请先按完整语义单元拆分。',
                                    page_count=count, max_pages=max_pages))
            # 页数一旦确定超限即短路：不再逐页解析（版面分类与语言抽样都只在范围内执行）。
            return summarize(findings, **facts)
        texts, failed = [], []
        for index in range(count):
            try:
                page = doc[index]
                facts['pages'].append(classify_page(page))
                if index < language_pages:
                    texts.append(page.get_text())
            except Exception as exc:
                failed.append({'page': index + 1, 'reason': type(exc).__name__})
            if index >= 199:  # 有界：超长文档只抽样前 200 页
                break
        if failed:
            findings.append(finding('page_load_failed', pages=failed))
        non_digital = [p for p in facts['pages'] if p['kind'] in ('scanned_image', 'no_text_layer')]
        if non_digital and require_digital:
            findings.append(finding('non_digital_pages', pages=[{'page': p['page'], 'kind': p['kind']} for p in non_digital]))
        language = detect_language('\n'.join(texts))
        facts['source_language'] = language
        if language['language'] == target_language:
            name = LANGUAGE_NAMES[target_language]
            findings.append(finding('source_language_matches_target',
                                    f'源文主要语言已经是目标语言（{name}）；当前版本支持英译中（en→zh）与中译英（zh→en），'
                                    f'不会静默输出{name}原文。', target_language=target_language, **language))
        elif language['language'] == 'mixed':
            findings.append(finding('source_language_mixed', **language))
        elif language['language'] == 'unknown':
            findings.append(finding('source_language_unknown', **language))
        if target_language == 'en' and language['language'] == 'zh' and not failed:
            inline = [inline_object_math(doc, index) for index in range(min(count, 200))]
            facts['inline_object_math'] = inline
            flagged = [row for row in inline if row['flagged']]
            if flagged:
                findings.append(finding('zh2en_inline_object_math_unsupported', pages=flagged,
                                        page_min=INLINE_OBJECT_PAGE_MIN))
    return summarize(findings, **facts)


def main(argv=None) -> int:
    """有界子进程入口：只写结构化报告；阻断与否由调用方读取报告决定。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description='structured PDF input preflight (read-only)')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=DIGITAL_MAX_PAGES)
    parser.add_argument('--target-language', default='zh', choices=sorted(SUPPORTED_TARGETS))
    parser.add_argument('--require-digital', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = inspect_pdf(args.input, max_pages=args.max_pages, target_language=args.target_language,
                         require_digital=args.require_digital)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 0


def raise_for_blocked(result: dict[str, Any]) -> None:
    if result['status'] == 'blocked':
        first = next(f for f in result['findings'] if f['severity'] == 'error')
        exc = PreflightError(first['code'], first['message'], **first['details'])
        exc.result = result
        raise exc


if __name__ == '__main__':
    raise SystemExit(main())
