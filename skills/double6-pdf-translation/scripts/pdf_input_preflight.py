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


# 中译英行内对象公式检测（结构规则，不用词表）：中文正文行内部只要定位到 1 个“行内结构对象”
# （Form XObject 绘制的非中文字形，或字形大小的填充矢量路径）即判定该页不受支持（失败关闭）。
# 这类对象不能随英文重排：留在原坐标会与译文压叠，或被排版引擎丢弃；单个变量（例如 M）也是公式信息。
INLINE_OBJECT_PAGE_MIN = 1


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


def _has_cjk_row(chars) -> bool:
    """字符多重集里是否有中文行：同一行（纵向中心相差不到半个字高）至少 2 个汉字。"""
    return any(len(line) >= 2 for line in _char_lines(chars))


def _char_lines(chars) -> list[list[tuple[int, int, int, int]]]:
    """把字符多重集里的汉字 bbox 按行聚类（纵向中心相差不到半个字高为同一行）。"""
    cjk = sorted((bbox for char, bbox in chars.elements() if _CJK.match(char)), key=lambda b: (b[1] + b[3]) / 2)
    lines: list[list[tuple[int, int, int, int]]] = []
    for bbox in cjk:
        last = lines[-1] if lines else None
        if last:
            ref = last[-1]
            if abs((ref[1] + ref[3]) - (bbox[1] + bbox[3])) / 2 <= 0.5 * max(ref[3] - ref[1], bbox[3] - bbox[1], 1):
                last.append(bbox)
                continue
        lines.append([bbox])
    return lines


def _inside_row(cx: float, cy: float, rows) -> tuple[float, float, float, float] | None:
    for row in rows:
        x0, y0, x1, y1 = row
        height = y1 - y0
        # 行首左侧（项目符号）不算行内；行内对象中心须落在该行文字范围内部。
        if x0 + 0.3 * height < cx < x1 and y0 <= cy <= y1:
            return row
    return None


def _is_vector_glyph(rect, row_height: float) -> bool:
    # 字形大小：不超过约两个字宽、不高于行高的 1.6 倍，且不是细线（下划线、分数线）。
    return (rect.width <= 2.0 * row_height and rect.height <= 1.6 * row_height
            and min(rect.width, rect.height) >= 0.12 * row_height and max(rect.width, rect.height) >= 0.25 * row_height)


def _form_tree(page) -> dict[int, int]:
    """页面引用的全部 Form XObject（含嵌套）：xref -> 调用者 xref（0 为页面内容流）。"""
    return {item[0]: item[2] for item in page.get_xobjects()}


# ---- 带中文的 Form：正文准入（默认不是正文） ----
# 字体名或斜体标志表明是数学/斜体字形（数学变量的常见排版）。
_MATH_FONT = re.compile(r'italic|oblique|math|cmmi|cmsy|cmex|cmbsy|symbol|stix|cambria|mt-?extra|euclid|msam|msbm|rsfs|eufm|eusm',
                        re.IGNORECASE)
PROSE_HOST_SIZE = 0.75     # 宿主正文行：汉字字号 >= 页面主体字号的 0.75 倍
PROSE_HOST_MIN_CJK = 4     # Form 自身的中文行要作为宿主（同一内容流里混排公式）时，至少 4 个汉字
IN_FLOW_ONE_SIDE = 3.0     # 只在一侧有宿主汉字时（行首/行尾公式），水平间隙 <= 3 个宿主字高
LATIN_SIZE_RATIO = (0.75, 1.33)  # 拉丁字母字号与 Form 自身汉字字号之比超出此范围（上下标、公式字号）即为数学证据


def _char_records(page) -> list[dict[str, Any]]:
    # seq：字符在提取结果里的先后（未排序的 rawdict 保持内容流的绘制顺序），用于判断是否与中文同属一个视觉顺序的文本流。
    records = []
    for block in page.get_text('rawdict').get('blocks', []):
        for line in block.get('lines', []):
            for span in line['spans']:
                for char in span['chars']:
                    if char['c'].strip():
                        records.append({'key': (char['c'], tuple(round(v) for v in char['bbox'])), 'c': char['c'],
                                        'bbox': tuple(char['bbox']), 'font': span.get('font', ''),
                                        'size': span.get('size', 0.0), 'flags': span.get('flags', 0),
                                        'seq': len(records)})
    return records


def _same_line(r: dict[str, Any], pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    y0, y1 = r['bbox'][1], r['bbox'][3]
    h = max(y1 - y0, 1.0)
    return [o for o in pool if abs((o['bbox'][1] + o['bbox'][3]) - (y0 + y1)) / 2 <= 0.5 * h]


def _in_chinese_text_run(r: dict[str, Any], own: list[dict[str, Any]], *, word: bool) -> bool:
    """拉丁字形是否与同一 Form 里的中文同属一个按视觉顺序绘制的文本流（PR #19 第 6 轮，后端往返证据）：
    该行（同一 Form 自身、同一视觉行的字符）按 x 排序后绘制顺序严格递增（字形画在它左右邻字之间，
    后端按内容流顺序抽取时它留在原位；乱序后画的字母会被后端挪到行尾或丢失）；
    同行最近的汉字与它字号相同；孤立单字母还须与该汉字同一字体（同一文本流），
    斜体/数学字体的字形只有作为多字母单词（word=True，如斜体物种名、书名）时才可准入。"""
    line = sorted(_same_line(r, own), key=lambda o: (o['bbox'][0] + o['bbox'][2]) / 2)
    if any(a['seq'] >= b['seq'] for a, b in zip(line, line[1:])):
        return False
    cx = (r['bbox'][0] + r['bbox'][2]) / 2
    cjk = [o for o in line if _CJK.match(o['c'])]
    if not cjk:
        return False
    near = min(cjk, key=lambda o: abs((o['bbox'][0] + o['bbox'][2]) / 2 - cx))
    if abs(near['size'] - r['size']) > 0.05 * max(near['size'], 1.0):
        return False
    return word or near['font'] == r['font']


def _drawing_keys(page) -> list[tuple[str, tuple[int, int, int, int]]]:
    keys = []
    for drawing in page.get_drawings():
        r = drawing['rect']
        keys.append((drawing.get('type', ''), (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))))
    return keys


def _is_math_char(c: str) -> bool:
    import unicodedata
    code = ord(c)
    return (unicodedata.category(c) == 'Sm' or 0x0370 <= code <= 0x03FF or 0x1D400 <= code <= 0x1D7FF
            or 0x2100 <= code <= 0x214F or 0x2200 <= code <= 0x22FF)


def _math_like_glyphs(own: list[dict[str, Any]], page_records: list[dict[str, Any]], *,
                      admit_text_runs: bool = False) -> list[dict[str, Any]]:
    """Form 自身绘制的非中文字形里，像数学变量/符号的那些（结构与字体证据，不用词表）：
    数学符号或希腊字母；数学/斜体字体；孤立的单个拉丁字母（前后紧邻处没有其它字母数字）；
    字号与 Form 自身汉字字号明显不同的拉丁字母（上下标、公式字号）。普通英文单词与数字不算。"""
    import unicodedata
    cjk_sizes = sorted(r['size'] for r in own if _CJK.match(r['c']))
    cjk_size = cjk_sizes[len(cjk_sizes) // 2] if cjk_sizes else 0.0
    result = []
    for r in own:
        c = r['c']
        if _CJK.match(c) or unicodedata.category(c)[0] in 'PZC':
            continue
        if _is_math_char(c):
            result.append(r)  # 数学符号、希腊字母：始终是数学证据
            continue
        x0, y0, x1, y1 = r['bbox']
        # 紧邻的前后字符（同一行、间隙 <= 0.3 个字号的任何字符）；只要有一侧是拉丁字母或数字，就是单词的一部分。
        same_line = [o for o in _same_line(r, page_records) if o is not r]
        left = max((o for o in same_line if o['bbox'][2] <= x0 + 0.5), key=lambda o: o['bbox'][2], default=None)
        right = min((o for o in same_line if o['bbox'][0] >= x1 - 0.5), key=lambda o: o['bbox'][0], default=None)
        neighbours = [o for o in (left, right) if o is not None and
                      (x0 - o['bbox'][2] if o is left else o['bbox'][0] - x1) <= 0.3 * r['size']]
        in_word = any(o['c'].isalnum() and not _CJK.match(o['c']) for o in neighbours)
        if _MATH_FONT.search(r['font'] or '') or (r['flags'] & 2):
            if not (admit_text_runs and c.isalpha() and in_word and _in_chinese_text_run(r, own, word=True)):
                result.append(r)
            continue
        if not c.isalpha():
            continue  # 数字不单独作为数学证据（正文年份、编号、引用上标）
        if not in_word:
            if not (admit_text_runs and _in_chinese_text_run(r, own, word=False)):
                result.append(r)  # 孤立单字母（两侧紧邻处没有拉丁字母或数字）
            continue
        if cjk_size and not (LATIN_SIZE_RATIO[0] <= r['size'] / cjk_size <= LATIN_SIZE_RATIO[1]):
            result.append(r)
    return result


def _fraction_rules(own_paths, own: list[dict[str, Any]]):
    """Form 自身的细横线，且其正上方与正下方紧邻处都有 Form 自身的字形：分数线。"""
    rules = []
    for _, (x0, y0, x1, y1) in own_paths:
        if y1 - y0 > 1.5 or x1 - x0 < 3:
            continue
        overlap = [r for r in own if min(r['bbox'][2], x1) - max(r['bbox'][0], x0) > 0]
        above = any(0 <= y0 - r['bbox'][3] + 1 <= (r['bbox'][3] - r['bbox'][1]) + 1 for r in overlap)
        below = any(0 <= r['bbox'][1] - y1 + 1 <= (r['bbox'][3] - r['bbox'][1]) + 1 for r in overlap)
        if above and below:
            rules.append((x0, y0, x1, y1))
    return rules


def _host_lines(records: list[dict[str, Any]], body_size: float, min_cjk: int):
    """正文字号的中文行（宿主行）：(y0, y1, h, [x 区间])。"""
    from collections import Counter
    keyed = Counter(r['key'] for r in records if _CJK.match(r['c']) and r['size'] >= PROSE_HOST_SIZE * body_size)
    lines = []
    for line in _char_lines(keyed):
        if len(line) >= min_cjk:
            lines.append((min(b[1] for b in line), max(b[3] for b in line), max(max(b[3] - b[1] for b in line), 1),
                          [(b[0], b[2]) for b in line]))
    return lines


def _in_flow(bbox, lines) -> bool:
    """bbox 是否落在某条宿主中文行里：与行的纵向带相交，且两侧都有该行汉字，或一侧汉字的水平间隙 <= 3 个字高。"""
    x0, y0, x1, y1 = bbox
    for ly0, ly1, h, spans in lines:
        if min(y1, ly1) - max(y0, ly0) <= 0:
            continue
        left = [a1 for a0, a1 in spans if a1 <= x0 + 1]
        right = [a0 for a0, a1 in spans if a0 >= x1 - 1]
        if left and right:
            return True
        gaps = [x0 - a for a in left] + [a - x1 for a in right]
        if gaps and min(gaps) <= IN_FLOW_ONE_SIDE * h:
            return True
    return False


def inline_object_math(doc, page_index: int, *, with_objects: bool = False) -> dict[str, Any]:
    """定位一页中文正文行内的结构对象（结构证据，只读，不改源文件）。

    每个 Form XObject（含嵌套）按**自身**内容（扣除内层 Form 的内容）分类：
    - container：自身不画任何文字或路径（整页外壳等），只递归看内层；
    - object：自身不画汉字（Word/WPS 公式变量等）。在临时副本里清空后，其字形中心落在中文行内即为行内对象；
    - body：自身画汉字，且没有任何数学证据（数学符号/希腊字母、数学或斜体字体、孤立单字母、
      与自身汉字字号明显不同的拉丁字母、分数线）。只有正面确认为正文的 Form 才算正文；
    - mixed：自身画汉字且有数学证据。若数学证据落在宿主中文行里（Form 之外的正文行，或 Form 自身
      >= 4 个汉字的正文行），判 needs_review：整页拒绝，其数学字形与分数线逐个计入 ``objects``，
      供成品门核对；不在任何正文行里的（图内标签等）记为 standalone，不计入。
    尺寸（高、宽、间隙）不是忽略已定位证据的理由。
    """
    import fitz
    from collections import Counter

    page = doc[page_index]
    records = _char_records(page)
    original = Counter(r['key'] for r in records)
    by_key: dict[tuple, list[dict[str, Any]]] = {}
    for r in records:
        by_key.setdefault(r['key'], []).append(r)
    original_paths = Counter(_drawing_keys(page))
    cjk_sizes = Counter(round(r['size'], 1) for r in records if _CJK.match(r['c']))
    body_size = cjk_sizes.most_common(1)[0][0] if cjk_sizes else 0.0
    scratch = fitz.open()
    classes: dict[int, str] = {}
    objects: list[dict[str, Any]] = []
    try:
        scratch.insert_pdf(doc, from_page=page_index, to_page=page_index)
        tree = _form_tree(scratch[0])
        drawn: dict[int, Counter] = {}
        drawn_paths: dict[int, Counter] = {}
        owned: dict[int, Counter] = {}
        for xref in tree:
            saved = scratch.xref_stream(xref)
            scratch.update_stream(xref, b'')
            drawn[xref] = original - Counter(_char_keys(scratch[0]))
            drawn_paths[xref] = original_paths - Counter(_drawing_keys(scratch[0]))
            scratch.update_stream(xref, saved)
        for xref in tree:
            own_chars, own_paths = Counter(drawn[xref]), Counter(drawn_paths[xref])
            for child, parent in tree.items():
                if parent == xref and child != xref:
                    own_chars -= drawn[child]
                    own_paths -= drawn_paths[child]
            if not own_chars and not own_paths:
                classes[xref] = 'container'
                continue
            if drawn[xref] == original and drawn_paths[xref] == original_paths:
                # 页面等价 Form：它（连同内层）画出了整页的全部文字与路径，页面内容流与外壳自身什么都不画
                # （整页外壳 show_pdf_page / 打印驱动整页 Form）。后端对它自身内容的处理与页面级内容相同
                # （同一请求、逐像素相同的成品，见 PR #19 第 6 轮证据），因此按页面级内容对待：
                # 包装不改变判定。内层 Form 仍逐个分类。
                classes[xref] = 'page_equivalent'
                owned[xref] = Counter()
                continue
            owned[xref] = own_chars
            own = [rec for key in own_chars.elements() for rec in by_key.get(key, [])[:1]]
            if not any(_CJK.match(rec['c']) for rec in own):
                classes[xref] = 'object'
                continue
            math = _math_like_glyphs(own, records, admit_text_runs=True)
            rules = _fraction_rules(list(own_paths.elements()), own)
            if not math and not rules:
                classes[xref] = 'body'
                continue
            outside = [rec for key in (original - drawn[xref]).elements() for rec in by_key.get(key, [])[:1]]
            lines = _host_lines(outside, body_size, 2) + _host_lines(own, body_size, PROSE_HOST_MIN_CJK)
            if any(_in_flow(rec['bbox'], lines) for rec in math) or any(_in_flow(rule, lines) for rule in rules):
                classes[xref] = 'needs_review'
                for rec in math:
                    objects.append({'kind': 'xobject_text', 'char': rec['c'], 'bbox': [round(v) for v in rec['bbox']],
                                    'source': 'mixed_form_needs_review'})
                for rule in rules:
                    objects.append({'kind': 'form_rule', 'bbox': [round(v, 2) for v in rule], 'source': 'mixed_form_needs_review'})
            else:
                classes[xref] = 'standalone_mixed'
        for xref, kind in classes.items():
            if kind == 'object':
                # 只改内存中的临时副本：清空不画汉字的 Form，正文/混排/外壳 Form 保留。
                scratch.update_stream(xref, b'')
        # 文字层（页面级、或页面等价 Form 自身）中文正文行里的数学字形：预检不拦（后端按页面文字处理，
        # 与包装无关），但逐个记入 text_layer_math，由成品门核对它们在译文页里仍然存在（丢失即失败关闭）。
        form_owned = Counter()
        for xref, kind in classes.items():
            if kind not in ('container', 'page_equivalent'):
                form_owned += owned.get(xref, Counter())
        layer = [rec for key in (original - form_owned).elements() for rec in by_key.get(key, [])[:1]]
        layer_lines = _host_lines(layer, body_size, 2)
        text_layer_math = [{'kind': 'text_layer_glyph', 'char': rec['c'], 'bbox': [round(v, 1) for v in rec['bbox']]}
                           for rec in _math_like_glyphs(layer, records) if _in_flow(rec['bbox'], layer_lines)]
        bare = scratch[0]
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
    count = Counter(classes.values())
    for char, (x0, y0, x1, y1) in xobject_chars:
        if not _CJK.match(char) and _inside_row((x0 + x1) / 2, (y0 + y1) / 2, rows):
            objects.append({'kind': 'xobject_text', 'char': char, 'bbox': [x0, y0, x1, y1]})
    for drawing in page.get_drawings():
        if drawing.get('fill') is None:
            continue
        rect = drawing['rect']
        row = _inside_row((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2, rows)
        if row and _is_vector_glyph(rect, row[3] - row[1]):
            objects.append({'kind': 'vector_glyph', 'bbox': [round(v, 2) for v in (rect.x0, rect.y0, rect.x1, rect.y1)]})
    xobject_inline = sum(1 for o in objects if o['kind'] == 'xobject_text')
    vector_inline = sum(1 for o in objects if o['kind'] == 'vector_glyph')
    rule_inline = sum(1 for o in objects if o['kind'] == 'form_rule')
    reasons = sorted({'mixed_form_needs_review' if o.get('source') else 'inline_object' for o in objects})
    result = {'page': page_index + 1, 'cjk_rows': len(rows), 'form_xobjects': len(classes),
              'page_in_form': bool(count['body'] or count['needs_review'] or count['standalone_mixed'] or count['page_equivalent']),
              'container_forms': count['container'], 'page_equivalent_forms': count['page_equivalent'],
              # 页面等价 Form 承载的就是整页正文，计入 body_forms（另单列 page_equivalent_forms）。
              'body_forms': count['body'] + count['page_equivalent'], 'inline_forms': count['object'],
              'needs_review_forms': count['needs_review'], 'standalone_mixed_forms': count['standalone_mixed'],
              'xobject_text_glyphs': xobject_inline, 'vector_glyphs': vector_inline, 'form_rules': rule_inline,
              'reasons': reasons, 'samples': objects[:5],
              'text_layer_math_glyphs': len(text_layer_math),
              'flagged': xobject_inline + vector_inline + rule_inline >= INLINE_OBJECT_PAGE_MIN}
    if with_objects:
        result['objects'] = objects
        result['text_layer_math'] = text_layer_math
    return result


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
