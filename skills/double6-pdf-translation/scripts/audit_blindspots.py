# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-31：审计盲区自动检查器（随 3.1.0 审计盲区自动化引入）；变更见 Skill 根目录 MODIFICATIONS.md。
"""审计盲区自动检查器:行尾截断守恒检查 + 写回墨迹覆盖率抽查。

背景:两类缺陷文字层/常规审计看不见——
  1. 行尾截断:文字层截断但渲染正常(源段行尾即截断,译文随丢,审计不报警);
  2. 零墨迹行:文字层完整但渲染无墨(如行底白块后画盖住译文整行的历史缺陷)。

本模块只产 issues 与测量回执,不当场改译文;issues 以 code 形式上浮到
翻译审校记录(挂接点在 translation_continuation.py 每页结果组装处,
不改动路由分发与工作流结构)。墨迹测量委托独立模块 ink_metrics.py。

CLI(对既有产物做离线审计,历史缺陷样本复现用):
  python3 audit_blindspots.py --target 译文.pdf [--manifest 源段清单.json] \
      [--page N] [--out report.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import fitz

import ink_metrics

# ---- 行尾截断检查参数 -------------------------------------------------------
# 终结标点(中西文)。分号/冒号收尾的条款/列表段是合法收笔,不算截断;
# 右括号/引号单独不算完整,需其前还有终结标点,由正则一并处理。
_TERMINAL_RE = re.compile(r'[.?!。!?…;:]["\')》〉」』”’；：]?$')
# 悬空尾词:段落在这些词后中断,几乎必然是截断(而非译者收笔)。只收介词/
# 连词/冠词/系动词与"数字+未完单位"这类强功能词;地名/编号等弱收尾(如
# Station、no.)不收,否则图题、地址段会被误报。
_DANGLING_TAIL_EN = re.compile(
    r'(?:\b(?:in|of|at|on|for|and|or|to|by|with|the|a|an|about|per|from|into|'
    r'toward|within|between|after|before|during|under|over|than|that|which|is|are|was|were)'
    r'\W*|[0-9]+(?:\.[0-9]+)?\s*(?:h|hr|hours?|km|m|cm|yuan|元|'
    r'\u5c0f|\u65f6|\u5206|\u79d2|\u3005)?)$', re.IGNORECASE)
_DANGLING_TAIL_ZH = re.compile(r'[0-9]+\u5c0f?$|[\u7ea6\u7b2c\u5171\u81f3\u4ece\u7531\u4e8e]$')
# 报警分数线:有源段守恒证据(源段对齐成功)时 3 分即报;拿不到源段
# 证据(无 manifest/匹配失败)时悬空词信号单薄,提到 4 分防图题类误报。
TRUNCATION_ALARM_SCORE = 3
TRUNCATION_ALARM_SCORE_NO_EVIDENCE = 4
# 参与段落级检查的最小规模(行数/字符数),压标题、单元格等短行误报
_MIN_PARA_LINES = 2
_MIN_PARA_CHARS = 24
# 源段匹配门槛:数字交集达到该值才认定"找到了对应源段"
_SOURCE_MATCH_MIN_DIGIT_HITS = 2


def _para_tail(text):
    return text.rstrip()[-12:] if text and text.rstrip() else ''


def _digits_multiset(text):
    # 数字守恒用:抽取所有数字串(含小数),多重集比较
    return sorted(re.findall(r'\d+(?:\.\d+)?', text))


def _extract_paragraphs(pdf_path, page_number):
    """以 PDF block 为段落骨架,行文本与行 bbox 一起返回。"""
    doc = fitz.open(pdf_path)
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError('audit_page_out_of_range')
        page = doc[page_number - 1]
        paras = []
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            lines = []
            for line in block['lines']:
                text = ''.join(s['text'] for s in line['spans'])
                if text.strip():
                    lines.append({'text': text, 'bbox_pt': list(line['bbox'])})
            if lines:
                paras.append({'lines': lines, 'text': ''.join(l['text'] for l in lines),
                              'bbox_pt': list(block['bbox'])})
        return paras
    finally:
        doc.close()


def source_paragraphs_from_manifest(manifest_path):
    """从源段清单取源段(用于源侧段尾确认与数字守恒)。

    original_ocr_lines 逐行带 bbox_px[y0,y1];纵向相邻(间距 < 1.2 倍行高)
    的行聚为一段——行级直接对齐译文段不可靠,段级才可比。缺 bbox 时退回
    ocr_text 按空行/单行为段。
    """
    try:
        manifest = json.loads(Path(manifest_path).read_text())
    except (OSError, ValueError):
        return []
    paragraphs = []
    for p in manifest.get('pages', []):
        rows = [r for r in (p.get('original_ocr_lines') or [])
                if isinstance(r, dict) and isinstance(r.get('text'), str) and r['text'].strip()]
        if not rows:
            ocr_text = p.get('ocr_text')
            if isinstance(ocr_text, str):
                paragraphs += [l.strip() for l in ocr_text.splitlines() if l.strip()]
            continue
        paragraph, prev_bottom, prev_height = [], None, None
        for r in rows:
            bbox = r.get('bbox_px')
            gap_ok = True
            if prev_bottom is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                height = max(bbox[3] - bbox[1], 1)
                gap_ok = (bbox[1] - prev_bottom) < 1.2 * max(prev_height or height, height)
                prev_height = height
                prev_bottom = bbox[3]
            elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                prev_bottom, prev_height = bbox[3], max(bbox[3] - bbox[1], 1)
            if paragraph and not gap_ok:
                paragraphs.append(''.join(paragraph))
                paragraph = []
            paragraph.append(r['text'].strip())
        if paragraph:
            paragraphs.append(''.join(paragraph))
    return paragraphs


def _match_source_paragraph(para_digits, source_paragraphs):
    """按数字多重集交集找译文段对应的源段;命中不足返回 None(宁缺毋滥,
    匹配不上的段落不做源侧守恒,防错配误报)。"""
    if not source_paragraphs or not para_digits:
        return None
    best, best_hits = None, 0
    for src in source_paragraphs:
        src_digits = _digits_multiset(src)
        if not src_digits:
            continue
        pool = list(src_digits)
        hits = 0
        for d in para_digits:
            if d in pool:
                pool.remove(d)
                hits += 1
        if hits > best_hits:
            best, best_hits = src, hits
    return best if best_hits >= _SOURCE_MATCH_MIN_DIGIT_HITS else None


def _match_source_for_paragraph(para_text, source_lines):
    """给译文段落找数字证据最接近的源行组(守恒检查用,对不齐就返回 None)。"""
    if not source_lines:
        return None
    want = _digits_multiset(para_text)
    if not want:
        return None
    best, best_hits = None, -1
    for src in source_lines:
        got = _digits_multiset(src)
        if not got:
            continue
        hits = sum(1 for d in want if d in got)
        if hits > best_hits:
            best, best_hits = src, hits
    return best


def audit_trailing_truncation(pdf_path, page_number, source_paragraphs=None):
    """行尾/段尾截断守恒检查。

    每段落打嫌疑分(只有段尾无终结标点才进入源侧核对,防完整段被噪声源行误配):
      +1 段尾无终结标点;
      +2 段尾悬空功能词/裸数字+未完单位(强信号);
      +1 对应源段尾同样无终结标点(源段行即截断,非译者收笔);
      +2 对应源段的数字在译文中消失(字符守恒失败)。
    分数 >= TRUNCATION_ALARM_SCORE 报 trailing_truncation_suspect。
    """
    issues = []
    paras = _extract_paragraphs(pdf_path, page_number)
    for para in paras:
        text = para['text'].strip()
        if len(para['lines']) < _MIN_PARA_LINES or len(text) < _MIN_PARA_CHARS:
            continue
        tail = _para_tail(text)
        score, signals = 0, []
        if not _TERMINAL_RE.search(text[-2:] if text else ''):
            score += 1
            signals.append('no-terminal-punct')
        else:
            continue  # 完整收笔的段落不做源侧核对
        if _DANGLING_TAIL_EN.search(tail) or _DANGLING_TAIL_ZH.search(tail):
            score += 2
            signals.append('dangling-tail-word')
        para_digits = _digits_multiset(text)
        src = _match_source_paragraph(para_digits, source_paragraphs) if source_paragraphs else None
        if src is not None:
            if not re.search(r'[.!?\u3002\uff01\uff1f\u2026\uff1b\uff1a]', src.rstrip()[-6:]):
                score += 1
                signals.append('source-paragraph-also-unterminated')
            pool = list(_digits_multiset(text))
            missing = []
            for d in _digits_multiset(src):
                if d in pool:
                    pool.remove(d)
                else:
                    missing.append(d)
            if missing:
                score += 2
                signals.append(f'digits-missing:{",".join(missing[:6])}')
        alarm_line = TRUNCATION_ALARM_SCORE if src is not None else TRUNCATION_ALARM_SCORE_NO_EVIDENCE
        if score >= alarm_line:
            issues.append({
                'code': 'trailing_truncation_suspect', 'page': page_number,
                'score': score, 'signals': signals,
                'paragraph_tail': tail, 'paragraph_lines': len(para['lines']),
                'bbox_pt': para['bbox_pt'],
                'source_paragraph_tail': src.rstrip()[-16:] if src else None})
    return issues


def audit_writeback_ink(pdf_path, page_number, dpi=ink_metrics.DEFAULT_DPI):
    """写回后墨迹覆盖率抽查:文字层行存在但渲染无墨/墨异常偏低即报警。

    孤立符号行(<=2 个非空白字符,如图例里的负号/连接号)bbox 内天然几乎
    全空白,不参与 low-ink 相对判定,防误报;zero-ink 仍报(完全无墨意味着
    字符根本没画出来,与行长无关)。
    """
    summary = ink_metrics.page_ink_summary(pdf_path, page_number, dpi)
    issues = []
    for line in summary['lines']:
        text = (line.get('text') or '').strip()
        short_line = len(text) <= 2
        if line['class'] == 'zero-ink':
            issues.append({
                'code': 'writeback_zero_ink_line', 'page': page_number,
                'ratio': line['ratio'], 'bbox_pt': line['bbox_pt'],
                'text': (line.get('text') or '')[:40],
                'note': '文字层存在但切片暗像素<=0.5%,疑似被遮挡或漏渲染'})
        elif line['class'] == 'low-ink' and not short_line:
            issues.append({
                'code': 'writeback_low_ink_line', 'page': page_number,
                'ratio': line['ratio'], 'page_median': summary['median_ratio'],
                'bbox_pt': line['bbox_pt'],
                'text': (line.get('text') or '')[:40],
                'note': '暗像素显著低于同页中位数,建议人工抽查'})
    return issues, summary


def audit_page_blindspots(pdf_path, page_number, source_paragraphs=None,
                          dpi=ink_metrics.DEFAULT_DPI, max_lines_per_page=400):
    """单页两案合并审计。返回 {'codes': [...], 'issues': [...], 'ink_summary': {...}}。

    codes 是去重后的 issue code 列表,供 translation_continuation 上浮进审校
    记录;行数超限(超大页)时跳过墨迹抽查并记 skip 原因,防止审计拖垮管线。
    """
    issues = audit_trailing_truncation(pdf_path, page_number, source_paragraphs)
    ink_summary = None
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        text_line_count = sum(
            1 for b in page.get_text('dict')['blocks'] if b.get('type') == 0
            for _ in b['lines'])
    finally:
        doc.close()
    if text_line_count <= max_lines_per_page:
        ink_issues, ink_summary = audit_writeback_ink(pdf_path, page_number, dpi)
        issues += ink_issues
    else:
        ink_summary = {'skipped': 'line_count_over_limit', 'line_count': text_line_count}
    codes = list(dict.fromkeys(i['code'] for i in issues))
    return {'codes': codes, 'issues': issues, 'ink_summary': ink_summary}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--target', required=True, help='译文 PDF 路径')
    ap.add_argument('--manifest', help='源段清单 JSON(可选,提供后启用源段守恒证据)')
    ap.add_argument('--page', type=int, help='只审计指定页(默认全部)')
    ap.add_argument('--out', help='结果写入该 JSON 文件(默认 stdout)')
    args = ap.parse_args()

    doc = fitz.open(args.target)
    total = len(doc)
    doc.close()
    shared_source = source_paragraphs_from_manifest(args.manifest) if args.manifest else None
    pages = [args.page] if args.page else range(1, total + 1)

    result = {'target': str(Path(args.target).resolve()), 'pages': {}}
    all_codes = []
    for pno in pages:
        page_result = audit_page_blindspots(args.target, pno, shared_source)
        result['pages'][pno] = page_result
        all_codes += page_result['codes']
    result['codes'] = list(dict.fromkeys(all_codes))
    payload = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(payload + '\n')
        print(f'codes={result["codes"] or ["(clean)"]} -> {args.out}')
    else:
        print(payload)
    # 有报警时退出码 1,便于脚本链判断
    return 1 if result['codes'] else 0


if __name__ == '__main__':
    sys.exit(main())
