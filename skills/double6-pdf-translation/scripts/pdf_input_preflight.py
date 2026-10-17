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
    'source_language_matches_target': ('error', '源文主要语言已经是目标语言（中文）；当前版本只支持英译中，不会静默输出中文原文。'),
    'source_language_mixed': ('warning', '源文中英混合比例较高，语言判定不确定；请确认源文主体是英文。'),
    'source_language_unknown': ('info', '可抽取文字过少，无法判定源语言（常见于扫描件或文字转曲）。'),
    'page_load_failed': ('error', '部分页面无法解析。'),
}

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


def inspect_pdf(path, *, max_pages: int | None = DIGITAL_MAX_PAGES, target_language: str = 'zh',
                require_digital: bool = False, language_pages: int = 3) -> dict[str, Any]:
    """返回结构化预检结果；不抛异常，所有问题都进入 findings。"""
    import fitz

    path = Path(path)
    findings: list[dict[str, Any]] = []
    facts: dict[str, Any] = {'input': str(path), 'page_count': None, 'max_pages': max_pages,
                             'pages': [], 'source_language': None, 'encryption': None,
                             'target_language': target_language}
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
        if language['language'] == 'zh' and target_language == 'zh':
            findings.append(finding('source_language_matches_target', **language))
        elif language['language'] == 'mixed':
            findings.append(finding('source_language_mixed', **language))
        elif language['language'] == 'unknown':
            findings.append(finding('source_language_unknown', **language))
    return summarize(findings, **facts)


def raise_for_blocked(result: dict[str, Any]) -> None:
    if result['status'] == 'blocked':
        first = next(f for f in result['findings'] if f['severity'] == 'error')
        exc = PreflightError(first['code'], first['message'], **first['details'])
        exc.result = result
        raise exc
