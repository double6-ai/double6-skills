# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-22：2.0.0-rc.8 新增（扫描/混合 PDF 的常规 OCR 路线）；变更见Skill根目录MODIFICATIONS.md。
"""扫描/混合 PDF 的有界 OCR 重建（只在 ``candidate --route scanned_ocr`` 的有界任务内运行）。

流程（每页独立判定，任何一页不受支持即整份拒绝，fail-closed）：
1. 页分类沿用 ``pdf_input_preflight.classify_page``：原生文字页原样保留；扫描页走 OCR；
   文字转曲页、条带拼接扫描页、原生页内嵌大幅含字扫描图拒绝。
2. 扫描页按 300 dpi 渲染；源图有效分辨率、方向（Tesseract OSD）、倾斜、竖排、表格、公式、
   低置信度、文字压在图形/印章上等版式逐项检查，不支持的给稳定错误码。
3. 受支持的扫描页：把可信文字行的位置用周边背景色覆盖（图形、印章、非文字内容原样保留），
   再以可见文字层写回识别文本（原位置、按行宽拟合字号、保持墨色），得到“重建源 PDF”。
4. 对覆盖后的背景再跑一次 OCR（背景残留检查）：仍能识别出源语言文字即拒绝。
重建源 PDF 之后交给既有电子 PDF 路线（同一套预检、翻译、残留与综合质量门）处理。

OCR 引擎为本机 Tesseract CLI（Apache-2.0），每个 tesseract 进程都是本有界任务进程树的子进程，
受同一内存/时限计量与回收；逐进程记录 pid、create_time、退出码与 ru_maxrss。不调用任何网络服务。
OCR 文本未经人工核对：重建源与译文都不构成质量验收，综合质量最高为 unverified。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RENDER_DPI = 300
MIN_SOURCE_DPI = 200            # 源扫描图有效分辨率下限
DPI_TOLERANCE = 0.97            # 页面尺寸取整导致的 199.x dpi 视为 200
MIN_LINE_HEIGHT_PX = 18         # 可信文字行的中位行高下限（按源图像素计）
TEXT_CONF = {'eng': 70.0, 'chi_sim': 65.0}   # 可信文字行的平均词置信度下限
PAGE_MEAN_CONF = {'eng': 80.0, 'chi_sim': 75.0}
WORD_MIN_CONF = 50.0            # 行内任一可读词置信度低于此值 → 整行计为不确定行
JUNK_CONF = 40.0                # 低于此值且无可读字母/汉字的行视为非文字（图形、噪点），保留为图像
MAX_UNCERTAIN_LINES = 2         # 介于两者之间、含可读字母/汉字的“不确定文字行”最多允许的行数（超过即拒绝）
MAX_UNCERTAIN_CHAR_RATIO = 0.03
MAX_SKEW_DEGREES = 1.0
OSD_MIN_CONFIDENCE = 3.0
RESIDUE_CONF = 70.0
TESSERACT_TIMEOUT = 45
ENGINE_LANGS = {'en': 'chi_sim+eng', 'zh': 'eng'}   # 目标语言 -> OCR 语言（源语言）
SOURCE_LANG = {'en': 'zh', 'zh': 'en'}

CODES = {
    'ocr_engine_unavailable': '本机未找到 Tesseract 或所需语言数据（chi_sim/eng/osd）；OCR 路线不可用。电子 PDF 路线不受影响。',
    'ocr_route_no_scanned_pages': '文档没有扫描页；请使用 --route digital_pdf。',
    'ocr_outlined_vector_text_unsupported': '页面文字已转为矢量路径（无字体、无扫描图）；当前 OCR 路线不支持。',
    'ocr_tiled_scan_unsupported': '扫描页由多张条带/分块图像拼成；当前 OCR 路线只支持单张整页扫描图。',
    'ocr_mixed_within_page_unsupported': '同一页既有原生文字层又有含大量文字的扫描图；当前只支持“整页扫描”与“整页原生”按页混合。',
    'ocr_resolution_too_low': '扫描分辨率过低（源图有效分辨率或文字像素高度低于下限），识别结果不可靠。',
    'ocr_orientation_uncertain': '无法可靠判定扫描页方向。',
    'ocr_skew_unsupported': '扫描页倾斜超过 1°；当前不做纠偏，拒绝以免覆盖不准。',
    'ocr_vertical_text_unsupported': '检测到竖排文字；当前只支持横排。',
    'ocr_table_unsupported': '扫描页含表格（框线或多列对齐的表格行）；表格结构无法可靠重建，拒绝。',
    'ocr_formula_unsupported': '扫描页含公式或数学符号密集的行，或图像里有上标/下标/叠排分式（details.evidence=image_geometry）；OCR 无法保证公式完整，在覆盖原图之前拒绝，而不是删除或改写公式。',
    'ocr_low_confidence': '识别置信度不足（页均值过低或存在多行不确定文字）。',
    'ocr_text_over_graphics_unsupported': '文字压在图形、印章或非均匀底色上；无法干净覆盖原文，拒绝。',
    'ocr_no_reliable_text': '扫描页没有识别出可信文字。',
    'ocr_source_language_mismatch': '扫描页识别出的主要语言与翻译方向不符。',
    'ocr_background_text_residue': '覆盖原文后的背景中仍能识别出源语言文字；拒绝以免原文与译文叠加。',
    'ocr_engine_failed': 'Tesseract 进程失败或超时。',
}

_CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
_LATIN = re.compile(r'[A-Za-z]')
_LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
_MATH = re.compile(r'[=+<>±×÷∑∏∫√∞≈≠≤≥∂∇^_{}|~\u0391-\u03a9\u03b1-\u03c9]')
_EQ_NUMBER = re.compile(r'\(\s*\d{1,3}[a-z]?\s*\)\s*$')


def finding(code: str, **details: Any) -> dict[str, Any]:
    return {'code': code, 'severity': 'error', 'message': CODES[code], 'details': details}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- engine

def engine_info(tesseract: str | None = None) -> dict[str, Any]:
    """引擎与语言数据身份；缺失时返回 available=False（只对 OCR 路线构成阻断）。"""
    binary = tesseract or shutil.which('tesseract')
    info: dict[str, Any] = {'engine': 'tesseract', 'binary': binary, 'available': False}
    if not binary:
        info['missing'] = ['tesseract']
        return info
    try:
        version = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=20)
        langs = subprocess.run([binary, '--list-langs'], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        info['missing'] = [f'tesseract_unrunnable:{type(exc).__name__}']
        return info
    text = (version.stdout or '') + (version.stderr or '')
    match = re.search(r'tesseract\s+v?(\d+\.\d+[\w.\-]*)', text)
    info['version'] = match.group(1) if match else None
    info['version_banner'] = text.strip().splitlines()[:2]
    listing = (langs.stdout or '') + (langs.stderr or '')
    folder = re.search(r'"([^"]+)"', listing)
    available = [line.strip() for line in listing.splitlines()[1:] if line.strip()]
    info['tessdata_dir'] = folder.group(1) if folder else None
    info['languages'] = available
    missing = [lang for lang in ('chi_sim', 'eng', 'osd') if lang not in available]
    info['missing'] = missing
    data = {}
    if info['tessdata_dir']:
        for lang in ('chi_sim', 'eng', 'osd'):
            path = Path(info['tessdata_dir']) / f'{lang}.traineddata'
            if path.is_file():
                data[lang] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256_file(path)}
    info['traineddata'] = data
    info['available'] = bool(info['version']) and not missing and len(data) == 3
    return info


class EngineError(RuntimeError):
    pass


def run_tesseract(args: list[str], *, log: list[dict[str, Any]], purpose: str, timeout: float = TESSERACT_TIMEOUT,
                  stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    """以本有界任务子进程运行 tesseract；记录 pid、create_time、退出码、ru_maxrss。超时即终止并回收。"""
    import threading
    env = dict(os.environ, OMP_THREAD_LIMIT='1')
    started = time.time()
    proc = subprocess.Popen(args, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    created_at = None
    try:
        import psutil
        created_at = psutil.Process(proc.pid).create_time()
    except Exception:
        created_at = None
    row: dict[str, Any] = {'purpose': purpose, 'pid': proc.pid, 'created_at': created_at,
                           'argv': [Path(args[0]).name, *args[1:]]}
    log.append(row)
    buffers: dict[str, bytes] = {}

    def drain(name, stream):
        buffers[name] = stream.read()
    readers = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in (('out', proc.stdout), ('err', proc.stderr))]
    for reader in readers:
        reader.start()
    if stdin is not None:
        proc.stdin.write(stdin); proc.stdin.close()
    deadline = started + timeout
    status = usage = None
    timed_out = False
    peak_rss = 0
    try:
        import psutil
        watched = psutil.Process(proc.pid)
    except Exception:
        watched = None
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            break
        if watched is not None:
            try:
                peak_rss = max(peak_rss, watched.memory_info().rss)
            except Exception:
                pass
        if time.time() >= deadline:
            timed_out = True
            proc.kill()
            _, status, usage = os.wait4(proc.pid, 0)
            break
        time.sleep(0.02)
    proc.returncode = os.waitstatus_to_exitcode(status)
    for reader in readers:
        reader.join(5)
    out, err = buffers.get('out', b''), buffers.get('err', b'')
    # 逐进程峰值内存：20 ms 采样的 RSS 峰值（wait4 的 ru_maxrss 在 Linux 上含 fork 时继承的父进程高水位，不可用）
    row.update(returncode=proc.returncode, timed_out=timed_out, seconds=round(time.time() - started, 3),
               sampled_peak_rss_bytes=peak_rss or None, stderr_tail=err.decode('utf-8', 'replace')[-300:])
    if timed_out:
        raise EngineError(f'tesseract timed out after {timeout}s ({purpose})')
    return proc.returncode, out, err


def osd(binary: str, png: Path, log: list[dict[str, Any]]) -> dict[str, Any]:
    code, out, err = run_tesseract([binary, str(png), 'stdout', '--psm', '0', '-l', 'osd'], log=log, purpose='osd')
    text = out.decode('utf-8', 'replace') + err.decode('utf-8', 'replace')
    rotate = re.search(r'Rotate:\s*(\d+)', text)
    conf = re.search(r'Orientation confidence:\s*([\d.]+)', text)
    script = re.search(r'Script:\s*(\S+)', text)
    return {'returncode': code, 'rotate': int(rotate.group(1)) if rotate else None,
            'confidence': float(conf.group(1)) if conf else None, 'script': script.group(1) if script else None,
            'raw': text.strip()[-300:]}


def ocr_tsv(binary: str, png: Path, lang: str, log: list[dict[str, Any]], purpose: str) -> list[dict[str, Any]]:
    code, out, err = run_tesseract([binary, str(png), 'stdout', '-l', lang, '--psm', '3', '--dpi', str(RENDER_DPI),
                                    '-c', 'preserve_interword_spaces=1', 'tsv'], log=log, purpose=purpose)
    if code != 0:
        raise EngineError(f'tesseract exited {code} ({purpose}): {err.decode("utf-8", "replace")[-200:]}')
    rows = []
    lines = out.decode('utf-8', 'replace').splitlines()
    header = lines[0].split('\t') if lines else []
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) != len(header):
            continue
        row = dict(zip(header, parts))
        if row.get('level') != '5':
            continue
        text = row.get('text', '')
        if not text.strip():
            continue
        rows.append({'block': int(row['block_num']), 'par': int(row['par_num']), 'line': int(row['line_num']),
                     'left': int(row['left']), 'top': int(row['top']), 'width': int(row['width']),
                     'height': int(row['height']), 'conf': float(row['conf']), 'text': text})
    return rows


# ---------------------------------------------------------------- page analysis

def join_words(words: list[str]) -> str:
    out = ''
    for word in words:
        if not out:
            out = word
        elif _CJK.search(out[-1]) or _CJK.search(word[0]) or re.match(r'[，。、；：！？）》」』】,.;:!?)]', word[0]) \
                or re.search(r'[（《「『【(]$', out):
            out += word
        else:
            out += ' ' + word
    return out


def min_readable_conf(words: list[dict[str, Any]]) -> float | None:
    confs = [w['conf'] for w in words if w['conf'] >= 0 and (_CJK.search(w['text']) or _LATIN.search(w['text']))]
    return round(min(confs), 2) if confs else None


def group_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for word in words:
        lines.setdefault((word['block'], word['par'], word['line']), []).append(word)
    result = []
    for key, members in sorted(lines.items()):
        members.sort(key=lambda w: w['left'])
        x0 = min(w['left'] for w in members); y0 = min(w['top'] for w in members)
        x1 = max(w['left'] + w['width'] for w in members); y1 = max(w['top'] + w['height'] for w in members)
        text = join_words([w['text'] for w in members])
        confs = [w['conf'] for w in members if w['conf'] >= 0]
        gaps = [b['left'] - (a['left'] + a['width']) for a, b in zip(members, members[1:])]
        result.append({'key': list(key), 'bbox_px': [x0, y0, x1, y1], 'text': text,
                       'mean_conf': round(statistics.fmean(confs), 2) if confs else 0.0,
                       'words': len(members), 'gaps': gaps, 'min_readable_word_conf': min_readable_conf(members),
                       'readable_chars': len(_CJK.findall(text)) + len(_LATIN.findall(text)),
                       'word_boxes': [[w['left'], w['top'], w['left'] + w['width'], w['top'] + w['height']] for w in members],
                       'word_texts': [w['text'] for w in members]})
    return result


def _same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ay0, ay1 = a['bbox_px'][1], a['bbox_px'][3]
    by0, by1 = b['bbox_px'][1], b['bbox_px'][3]
    overlap = min(ay1, by1) - max(ay0, by0)
    height = max(ay1 - ay0, by1 - by0)
    gap = max(a['bbox_px'][0], b['bbox_px'][0]) - min(a['bbox_px'][2], b['bbox_px'][2])
    return overlap >= 0.5 * min(ay1 - ay0, by1 - by0) and gap <= 1.5 * height


def refine_fragmented_rows(lines: list[dict[str, Any]], image_path: Path, *, binary: str, lang: str, lang_key: str,
                           workdir: Path, page_no: int, log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一视觉行被引擎切成多段（常见于大号粗体标题）：把整行裁出来以单行模式（--psm 7）重新识别。
    重识别结果可信才替换原分段；否则保留原分段，由后续置信度门决定（不猜测、不删字）。"""
    from PIL import Image
    rows: list[list[dict[str, Any]]] = []
    for line in sorted(lines, key=lambda l: (l['bbox_px'][1], l['bbox_px'][0])):
        for row in rows:
            if any(_same_row(line, member) for member in row):
                row.append(line)
                break
        else:
            rows.append([line])
    image = None
    result: list[dict[str, Any]] = []
    for number, row in enumerate(rows):
        if len(row) == 1:
            result.extend(row)
            continue
        row.sort(key=lambda l: l['bbox_px'][0])
        x0 = min(l['bbox_px'][0] for l in row); y0 = min(l['bbox_px'][1] for l in row)
        x1 = max(l['bbox_px'][2] for l in row); y1 = max(l['bbox_px'][3] for l in row)
        if image is None:
            image = Image.open(image_path)
        pad = max(8, int(0.25 * (y1 - y0)))
        crop_box = (max(0, x0 - pad), max(0, y0 - pad), min(image.width, x1 + pad), min(image.height, y1 + pad))
        crop_path = workdir / f'page-{page_no:03d}.row-{number:03d}.png'
        image.crop(crop_box).save(crop_path)
        code, out, err = run_tesseract([binary, str(crop_path), 'stdout', '-l', lang, '--psm', '7', '--dpi', str(RENDER_DPI), 'tsv'],
                                       log=log, purpose='row_rerecognition')
        words = []
        for raw in out.decode('utf-8', 'replace').splitlines()[1:]:
            parts = raw.split('\t')
            if len(parts) == 12 and parts[0] == '5' and parts[11].strip():
                words.append({'left': int(parts[6]) + crop_box[0], 'top': int(parts[7]) + crop_box[1], 'width': int(parts[8]),
                              'height': int(parts[9]), 'conf': float(parts[10]), 'text': parts[11]})
        merged = None
        if code == 0 and words:
            text = join_words([w['text'] for w in words])
            confs = [w['conf'] for w in words if w['conf'] >= 0]
            mean = statistics.fmean(confs) if confs else 0.0
            if mean >= TEXT_CONF[lang_key] and (len(_CJK.findall(text)) + len(_LATIN_WORD.findall(text))) > 0:
                merged = {'key': row[0]['key'], 'bbox_px': [x0, y0, x1, y1], 'text': text, 'mean_conf': round(mean, 2),
                          'words': len(words), 'gaps': [b['left'] - (a['left'] + a['width']) for a, b in zip(words, words[1:])],
                          'min_readable_word_conf': min_readable_conf(words),
                          'readable_chars': len(_CJK.findall(text)) + len(_LATIN.findall(text)),
                          'word_boxes': [[w['left'], w['top'], w['left'] + w['width'], w['top'] + w['height']] for w in words],
                          'word_texts': [w['text'] for w in words],
                          'refined_from': [l['text'] for l in row]}
        log[-1]['accepted'] = merged is not None
        result.extend([merged] if merged else row)
    return sorted(result, key=lambda l: (l['key'], l['bbox_px'][1]))


def _consensus_key(text: str) -> str:
    return re.sub(r'[\s\W_]+', '', text).casefold()


def _line_pass(binary: str, crop_path: Path, lang: str, log: list[dict[str, Any]], purpose: str, offset: tuple[int, int],
               scale: float = 1.0) -> dict[str, Any] | None:
    code, out, _err = run_tesseract([binary, str(crop_path), 'stdout', '-l', lang, '--psm', '7', '--dpi',
                                     str(int(RENDER_DPI * scale)), 'tsv'], log=log, purpose=purpose)
    words = []
    for raw in out.decode('utf-8', 'replace').splitlines()[1:]:
        parts = raw.split('\t')
        if len(parts) == 12 and parts[0] == '5' and parts[11].strip():
            words.append({'left': int(int(parts[6]) / scale) + offset[0], 'top': int(int(parts[7]) / scale) + offset[1],
                          'width': int(int(parts[8]) / scale), 'height': int(int(parts[9]) / scale),
                          'conf': float(parts[10]), 'text': parts[11]})
    if code != 0 or not words:
        return None
    confs = [w['conf'] for w in words if w['conf'] >= 0]
    return {'words': words, 'text': join_words([w['text'] for w in words]),
            'mean': statistics.fmean(confs) if confs else 0.0, 'weakest': min_readable_conf(words)}


def _adopt(line: dict[str, Any], result: dict[str, Any]) -> None:
    words, text = result['words'], result['text']
    line.update({'text': text, 'mean_conf': round(result['mean'], 2), 'words': len(words),
                 'gaps': [b['left'] - (a['left'] + a['width']) for a, b in zip(words, words[1:])],
                 'readable_chars': len(_CJK.findall(text)) + len(_LATIN.findall(text)),
                 'word_boxes': [[w['left'], w['top'], w['left'] + w['width'], w['top'] + w['height']] for w in words],
                 'word_texts': [w['text'] for w in words],
                 'min_readable_word_conf': result['weakest']})


def verify_weak_lines(lines: list[dict[str, Any]], image_path: Path, *, binary: str, lang: str, lang_key: str,
                      workdir: Path, page_no: int, log: list[dict[str, Any]]) -> None:
    """含低置信度词（< WORD_MIN_CONF）的行做多遍独立识别并表决（常规 OCR 多遍校验，不猜字、不删字）：

    第 2 遍：裁行、--psm 7 单行模式；第 3 遍（仅当前两遍不一致时）：同一裁行 1.5× 放大、--psm 7。
    比较键 = 去空白/标点、忽略大小写的文字。
    - 任意两遍一致 → 采用该一致文字（consensus；若一致的是第 2、3 遍则替换第 1 遍），记为可信文字；
    - 三遍互不一致，但某一遍所有可读词 ≥ WORD_MIN_CONF 且均值 ≥ TEXT_CONF → 采用该遍（line_pass）；
    - 否则保持原状，由 classify_line 计为不确定行（受页面不确定行上限约束，超限整页拒绝）。
    注意：一致只说明多遍结果稳定，不等于正确；OCR 文本因此永不作为质量验收（见 OCR_MANIFEST.quality_claim）。"""
    from PIL import Image
    image = None
    for number, line in enumerate(lines):
        weakest = line.get('min_readable_word_conf')
        if weakest is None or weakest >= WORD_MIN_CONF:
            continue
        if image is None:
            image = Image.open(image_path)
        x0, y0, x1, y1 = line['bbox_px']
        pad = max(8, int(0.25 * (y1 - y0)))
        crop_box = (max(0, x0 - pad), max(0, y0 - pad), min(image.width, x1 + pad), min(image.height, y1 + pad))
        crop = image.crop(crop_box)
        crop_path = workdir / f'page-{page_no:03d}.verify-{number:03d}.png'
        crop.save(crop_path)
        first_key = _consensus_key(line['text'])
        second = _line_pass(binary, crop_path, lang, log, 'weak_line_verification', crop_box[:2])
        passes = {'first': line['text'], 'second': second['text'] if second else None}
        outcome = 'unverified'
        if second and first_key and _consensus_key(second['text']) == first_key:
            outcome = 'consensus'
        else:
            big_path = workdir / f'page-{page_no:03d}.verify-{number:03d}.x15.png'
            crop.resize((int(crop.width * 1.5), int(crop.height * 1.5)), Image.LANCZOS).save(big_path)
            third = _line_pass(binary, big_path, lang, log, 'weak_line_adjudication', crop_box[:2], scale=1.5)
            passes['third'] = third['text'] if third else None
            third_key = _consensus_key(third['text']) if third else ''
            if third_key and third_key == first_key:
                outcome = 'consensus'
            elif third_key and second and third_key == _consensus_key(second['text']):
                outcome = 'consensus'
                _adopt(line, second)
            else:
                for candidate in (second, third):
                    if candidate and candidate['weakest'] is not None and candidate['weakest'] >= WORD_MIN_CONF \
                            and candidate['mean'] >= TEXT_CONF[lang_key]:
                        outcome = 'line_pass'
                        _adopt(line, candidate)
                        break
        line['verification_passes'] = passes
        line['weak_word_verification'] = outcome


def classify_line(line: dict[str, Any], lang_key: str) -> str:
    text = line['text']
    readable = len(_CJK.findall(text)) + len(_LATIN_WORD.findall(text))
    if readable == 0:
        return 'non_text'      # 纯数字/符号/噪点：保留为图像（数字不需翻译）
    if line['mean_conf'] < JUNK_CONF and line['readable_chars'] <= 3:
        return 'non_text'
    if lang_key == 'chi_sim' and not _CJK.search(text) and len(_LATIN.findall(text)) <= 4 and not re.search(r'\d', text):
        return 'uncertain'     # 中文源中孤立的极短拉丁片段（如把“用”识别成“Fil.”）：计入不确定行
    weakest = line.get('min_readable_word_conf')
    if weakest is not None and weakest < WORD_MIN_CONF and line.get('weak_word_verification') != 'consensus':
        return 'uncertain'     # 行均值高但含个别极低置信度词（漏字/错字）：不当作可信文字
    if line['mean_conf'] >= TEXT_CONF[lang_key]:
        return 'text'
    return 'uncertain'


def is_math_line(text: str) -> bool:
    symbols = len(_MATH.findall(text))
    chars = max(1, len(re.sub(r'\s', '', text)))
    if symbols >= 2 and symbols / chars >= 0.06:
        return True
    if re.search(r'(?<![A-Za-z])[A-Za-z]\s*=\s*\S', text) and symbols >= 1:
        return True
    if _EQ_NUMBER.search(text) and chars <= 40 and (symbols >= 1 or len(_LATIN_WORD.findall(text)) <= 2):
        return True
    return False


# ---------------------------------------------------------------- 上下标 / 叠排分式（图像几何证据，不依赖 OCR 文字）
# 复用思路：电子路线 pdf_input_preflight._math_like_glyphs 以“字号比超出 0.75–1.33 + 偏离同行基线”认定数学字形；
# 扫描页没有字体信息，改在渲染图上做连通域：同一列（横向重叠）的连通域合并为字形簇，按本行基线与 x 高度
# 量化每个簇的上下位置。上标簇底边明显高于基线、顶边高过 x 高度；下标簇顶边低于中线、底边低于基线。
# 只有当 OCR 在同一个词里确实读出了天然处于该位置的标点（引号/撇号/*/° 抬高，逗号/分号压低）时才算得到解释；
# 其它（读成 '?'、数字、被丢掉、落在词框之外）一律视为上下标证据并整页拒绝。
SCRIPT_RAISED_BOTTOM = 0.35       # 簇底边高于基线 ≥ 0.35 x 高
SCRIPT_RAISED_TOP = 1.15          # 且簇顶边高于基线 ≥ 1.15 x 高（越过 x 高线）
SCRIPT_LOWERED_TOP = 0.75         # 下标：簇顶边高于基线 ≤ 0.75 x 高（低于 x 高线）
SCRIPT_LOWERED_BOTTOM = -0.25     # 且簇底边低于基线 ≥ 0.25 x 高
SCRIPT_MIN_HEIGHT = 0.45          # 簇高 ≥ 0.45 x 高（排除 i 点之外的小噪点、句点）
SCRIPT_MIN_WIDTH_PX = 3           # 簇宽 ≥ 3 px 且 ≥ 0.15 x 高：排除扫描发丝线（300 dpi 下真实字形不止 2 px 宽）
SCRIPT_MIN_WIDTH = 0.15
# 含汉字的行：“x 高”取的是汉字高度，上下标字形相对汉字很小；按小字形处理（高度 0.2–0.6 汉字高），
# 汉字自身的分离部件（如上下结构的上半部）通常 > 0.6，不计入。
CJK_SCRIPT_RAISED_BOTTOM = 0.35
CJK_SCRIPT_LOWERED_TOP = 0.5
CJK_SCRIPT_LOWERED_BOTTOM = -0.15
CJK_SCRIPT_HEIGHT = (0.2, 0.6)
RAISED_MARKS = {"'": 1, '"': 2, '\u2018': 1, '\u2019': 1, '\u201c': 2, '\u201d': 2, '`': 1, '\u00b4': 1, '\u2032': 1,
                '\u2033': 2, '*': 1, '\u00b0': 1, '^': 1, '\u00ba': 1, '\u00aa': 1}
LOWERED_MARKS = {',': 1, ';': 1, '\uff0c': 1, '\uff1b': 1, '\u3001': 1}
# 标点能“解释”抬高/压低字形的形状上限（x 高为单位）：引号/撇号/星号是小而窄的记号；逗号/分号的顶端贴近基线。
# 被误读成 ' 或 ° 的上标数字（高 ≈ 0.85–0.95）、被误读成 , ; 的下标（顶端 ≈ 0.55–0.6）因此不会被解释掉。
MARK_MAX_HEIGHT = 0.72
MARK_MAX_WIDTH = 0.8               # 打字机字体的双引号两撇常连成一个簇
COMMA_MAX_TOP = 0.5
MARK_SEARCH = 2.0                 # 词框外 2 x 高内的记号归到最近的词（tesseract 词框常不含尾随引号）
FRACTION_BAR_MAX_THICK = 0.18     # 分数线：厚度 ≤ 0.18 x 高
FRACTION_BAR_MIN_LEN = 0.9        # 长度 ≥ 0.9 x 高、≤ 8 x 高（更长的是框线/下划线，另有门）
FRACTION_BAR_MAX_LEN = 8.0
FRACTION_GAP = 0.45               # 分数线与上下字形的竖向间隙 ≤ 0.45 x 高


def _ink_threshold(gray) -> int:
    import numpy as np
    return int(min(RULE_INK_THRESHOLD, int(np.percentile(gray, 90)) - 60))


def _components(ink, offset=(0, 0), min_area: int = 4) -> list[list[int]]:
    import cv2
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= min_area:
            out.append([x + offset[0], y + offset[1], x + w + offset[0], y + h + offset[1], area])
    return out


def _clusters(comps: list[list[int]]) -> list[dict[str, Any]]:
    """横向重叠（> 较窄者宽度 50%）的连通域合并成一个字形簇（i/j 的点、重音、汉字的分离笔画并入同一簇）。"""
    clusters: list[dict[str, Any]] = []
    for c in sorted(comps):
        for k in clusters:
            overlap = min(k['box'][2], c[2]) - max(k['box'][0], c[0])
            if overlap > 0.5 * min(k['box'][2] - k['box'][0], c[2] - c[0]):
                k['box'] = [min(k['box'][0], c[0]), min(k['box'][1], c[1]), max(k['box'][2], c[2]), max(k['box'][3], c[3])]
                k['parts'].append(c)
                break
        else:
            clusters.append({'box': c[:4], 'parts': [c]})
    return clusters


def _mark_count(text: str, marks: dict[str, int]) -> int:
    return sum(marks.get(ch, 0) for ch in text)


def _mark_zone(word: str, kind: str) -> str:
    """能解释压低字形的逗号/分号不能夹在两个字母数字之间（“H,O”“x,y” 中间的逗号不算，“1,”“word,(1947)” 算）；
    抬高记号（引号、撇号、*、°）整词都算（don't、’s）。"""
    if kind == 'raised':
        return word
    def alnum(i: int) -> bool:
        return 0 <= i < len(word) and word[i].isalnum()
    return ''.join(ch for i, ch in enumerate(word) if ch in LOWERED_MARKS and not (alnum(i - 1) and alnum(i + 1)))


def line_script_evidence(gray, line: dict[str, Any], threshold: int) -> dict[str, Any]:
    """一行的上下标几何证据。返回 {'baseline','x_height','suspects':[...]}；suspects 非空即该行含无法解释的上下标字形。"""
    import numpy as np
    x0, y0, x1, y1 = line['bbox_px']
    h = max(1, y1 - y0)
    margin = int(0.25 * h)
    H, W = gray.shape
    cx0, cy0, cx1, cy1 = max(0, x0 - margin), max(0, y0 - margin), min(W, x1 + margin), min(H, y1 + margin)
    ink = (gray[cy0:cy1, cx0:cx1] < threshold).astype(np.uint8)
    comps = [c for c in _components(ink, (cx0, cy0))
             if y0 - 0.05 * h <= (c[1] + c[3]) / 2 <= y1 + 0.05 * h]   # 中心在本行内：不吸收上下相邻行
    clusters = _clusters(comps)
    if len(clusters) < 3:
        return {'baseline': None, 'x_height': None, 'suspects': [], 'cjk_stroke_like_skipped': 0}
    baseline = statistics.median(k['box'][3] for k in clusters)
    near = [k['box'][3] - k['box'][1] for k in clusters if abs(k['box'][3] - baseline) <= 0.08 * h]
    xh = float(np.percentile(near, 30)) if near else 0.5 * h
    xh = max(xh, 1.0)
    boxes, texts = line.get('word_boxes') or [], line.get('word_texts') or []
    raised_by_word: dict[int, list[dict[str, Any]]] = {}
    lowered_by_word: dict[int, list[dict[str, Any]]] = {}
    suspects = []
    cjk = bool(_CJK.search(line.get('text', '')))
    skipped_cjk = 0
    for k in clusters:
        bx0, by0, bx1, by1 = k['box']
        if bx1 - bx0 < max(SCRIPT_MIN_WIDTH_PX, SCRIPT_MIN_WIDTH * xh):
            continue
        centre = (bx0 + bx1) / 2
        height = (by1 - by0) / xh
        near = sorted((max(b[0] - centre, centre - b[2], 0), i) for i, b in enumerate(boxes) if i < len(texts))
        near = [(d, i) for d, i in near if d <= (0.5 if cjk else MARK_SEARCH) * xh]
        local = baseline
        if cjk:
            if not CJK_SCRIPT_HEIGHT[0] <= height <= CJK_SCRIPT_HEIGHT[1]:
                continue
            if not near or _CJK.search(texts[near[0][1]]):
                # 汉字行：分离的笔画（省、学、心的上部点画）与小号上标在几何上无法区分，且汉字 OCR 词框常有偏移。
                # 只检查落在拉丁/数字词旁（0.5 字高内）的小字形；靠近汉字词或不在任何词旁的视为汉字笔画（已知局限，见 ocr-route.md）。
                skipped_cjk += 1
                continue
            # 汉字行里的拉丁/数字词：基线取该词自身其它字形的底边中位数（汉字字面常比拉丁基线更低）
            wb = boxes[near[0][1]]
            own = [o['box'][3] for o in clusters if o is not k and wb[0] - 0.1 * xh <= (o['box'][0] + o['box'][2]) / 2 <= wb[2] + 0.1 * xh]
            if own:
                local = statistics.median(own)
        bottom = (local - by1) / xh; top = (local - by0) / xh
        if cjk:
            raised = bottom >= CJK_SCRIPT_RAISED_BOTTOM
            lowered = top <= CJK_SCRIPT_LOWERED_TOP and bottom <= CJK_SCRIPT_LOWERED_BOTTOM
        else:
            raised = bottom >= SCRIPT_RAISED_BOTTOM and top >= SCRIPT_RAISED_TOP and height >= SCRIPT_MIN_HEIGHT
            lowered = top <= SCRIPT_LOWERED_TOP and bottom <= SCRIPT_LOWERED_BOTTOM and height >= SCRIPT_MIN_HEIGHT
        if not (raised or lowered):
            continue
        item = {'kind': 'raised' if raised else 'lowered', 'box_px': [bx0, by0, bx1, by1],
                'bottom_over_baseline_xh': round(bottom, 2), 'top_over_baseline_xh': round(top, 2), 'height_xh': round(height, 2)}
        kind = 'raised' if raised else 'lowered'
        marks = RAISED_MARKS if raised else LOWERED_MARKS
        if not near:
            item['reason'] = 'outside_any_ocr_word'
            suspects.append(item)
            continue
        with_marks = [i for d, i in near if _mark_count(_mark_zone(texts[i], kind), marks)]
        owner = with_marks[0] if with_marks else near[0][1]
        item['word'] = texts[owner]
        if raised:
            mark_shaped = height <= MARK_MAX_HEIGHT and (bx1 - bx0) / xh <= MARK_MAX_WIDTH
        else:
            mark_shaped = top <= COMMA_MAX_TOP and (bx1 - bx0) / xh <= MARK_MAX_WIDTH
        if not mark_shaped:
            item['reason'] = 'glyph_too_large_for_punctuation'
            suspects.append(item)
            continue
        (raised_by_word if raised else lowered_by_word).setdefault(owner, []).append(item)
    for table, marks, kind in ((raised_by_word, RAISED_MARKS, 'raised'), (lowered_by_word, LOWERED_MARKS, 'lowered')):
        for owner, items in table.items():
            word = texts[owner]
            available = _mark_count(_mark_zone(word, kind), marks)
            alnum = re.sub(r'[\W_]', '', word)
            if kind == 'raised' and available and alnum and len(alnum) <= 2 and not _CJK.search(word):
                # “x'” “2'” “1‘”：单个变量/数字旁的小号抬高记号可能是被误读的上标，不当作解释（宁可拒绝）。
                # 压低一侧不需要：逗号形状（顶端 ≤ COMMA_MAX_TOP）已与下标（顶端 ≈ 0.55–0.6）分开。
                for item in items:
                    item['reason'] = 'mark_after_short_token_ambiguous'
                suspects.extend(items)
                continue
            if len(items) > available:
                for item in items:
                    item['reason'] = 'not_explained_by_ocr_punctuation'
                suspects.extend(items)
    return {'baseline': round(baseline, 1), 'x_height': round(xh, 1), 'suspects': suspects, 'cjk_stroke_like_skipped': skipped_cjk}


def fraction_bar_evidence(gray, lines: list[dict[str, Any]], x_height: float, threshold: int) -> list[dict[str, Any]]:
    """叠排分式：短横线（不是表格框线/下划线），正上方与正下方紧贴处都有字形。"""
    import numpy as np
    if not lines or x_height <= 0:
        return []
    x0 = max(0, min(l['bbox_px'][0] for l in lines) - int(2 * x_height)); x1 = max(l['bbox_px'][2] for l in lines) + int(2 * x_height)
    y0 = max(0, min(l['bbox_px'][1] for l in lines) - int(2 * x_height)); y1 = max(l['bbox_px'][3] for l in lines) + int(2 * x_height)
    ink = (gray[y0:y1, x0:x1] < threshold).astype(np.uint8)
    comps = _components(ink, (x0, y0))
    found = []
    for c in comps:
        w, h = c[2] - c[0], c[3] - c[1]
        if not (h <= max(2.0, FRACTION_BAR_MAX_THICK * x_height) and FRACTION_BAR_MIN_LEN * x_height <= w <= FRACTION_BAR_MAX_LEN * x_height):
            continue
        if c[4] < 0.6 * w * h:          # 实心细横线
            continue
        def glyphs(side):
            out = []
            for d in comps:
                if d is c or (d[3] - d[1]) < 0.4 * x_height:
                    continue
                if d[0] < c[0] - 0.2 * x_height or d[2] > c[2] + 0.2 * x_height:
                    continue
                gap = (c[1] - d[3]) if side == 'above' else (d[1] - c[3])
                if 0 <= gap <= FRACTION_GAP * x_height:
                    out.append(d[:4])
            return out
        above, below = glyphs('above'), glyphs('below')
        if above and below:
            found.append({'bar_px': c[:4], 'above_px': above[:3], 'below_px': below[:3]})
    return found


RULE_INK_THRESHOLD = 160         # 框线二值化阈值（灰度 < 160 视为墨）
RULE_ROW_TOLERANCE = 2           # 在 2× 缩小图上允许 ±2 行（≈±4 px@300dpi）的倾斜/断线容差


def _longest_runs(matrix) -> list[int]:
    import numpy as np
    n, w = matrix.shape
    pad = np.zeros((n, w + 2), dtype=np.int8)
    pad[:, 1:-1] = matrix
    d = np.diff(pad, axis=1)
    out = []
    for i in range(n):
        starts = np.flatnonzero(d[i] == 1)
        ends = np.flatnonzero(d[i] == -1)
        out.append(int((ends - starts).max()) if len(starts) else 0)
    return out


def _count_rules(matrix, minimum: int) -> int:
    import numpy as np
    acc = matrix.copy()
    for k in range(1, RULE_ROW_TOLERANCE + 1):
        acc[k:] |= matrix[:-k]
        acc[:-k] |= matrix[k:]
    hit = np.asarray(_longest_runs(acc)) >= minimum
    if not hit.size:
        return 0
    return int(np.count_nonzero(hit[1:] & ~hit[:-1]) + (1 if hit[0] else 0))


def ruling_lines(gray) -> dict[str, int]:
    """长水平/竖直墨线数量（表格框线 / 图表网格证据）。

    在 2× 缩小图上二值化，对相邻 ±RULE_ROW_TOLERANCE 行做或运算后找最长连续墨段：
    水平线须 ≥ 20% 页宽，竖直线须 ≥ 8% 页高。按"渲染方向"计数，判定时水平/竖直对称处理，
    因此在方向检测（OSD）之前即可运行。
    """
    import numpy as np
    arr = np.asarray(gray.reduce(2)) < RULE_INK_THRESHOLD
    h, w = arr.shape
    return {'horizontal': _count_rules(arr, int(0.2 * w)),
            'vertical': _count_rules(np.ascontiguousarray(arr.T), int(0.08 * h))}


def ruled_table_evidence(rules: dict[str, int]) -> bool:
    a, b = rules['horizontal'], rules['vertical']
    return (a >= 3 and b >= 2) or (b >= 3 and a >= 2)


def estimate_skew(lines: list[dict[str, Any]]) -> float | None:
    """由同一行内首末词框中心的高度差估计倾斜角（度），取中位数。"""
    import math
    angles = []
    for line in lines:
        boxes = line['word_boxes']
        if len(boxes) < 4:
            continue
        a, b = boxes[0], boxes[-1]
        dx = (b[0] + b[2]) / 2 - (a[0] + a[2]) / 2
        if dx < 300:
            continue
        dy = (b[3]) - (a[3])
        angles.append(math.degrees(math.atan2(dy, dx)))
    return round(statistics.median(angles), 3) if len(angles) >= 3 else None


def ring_stats(rgb, gray, box, mask_boxes, pad):
    import numpy as np
    h, w = gray.shape
    x0, y0, x1, y1 = box
    rx0, ry0, rx1, ry1 = max(0, x0 - pad - 4), max(0, y0 - pad - 4), min(w, x1 + pad + 4), min(h, y1 + pad + 4)
    region = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
    region[max(0, y0 - pad - ry0):max(0, y1 + pad - ry0), max(0, x0 - pad - rx0):max(0, x1 + pad - rx0)] = False
    for mx0, my0, mx1, my1 in mask_boxes:
        ix0, iy0, ix1, iy1 = max(rx0, mx0), max(ry0, my0), min(rx1, mx1), min(ry1, my1)
        if ix0 < ix1 and iy0 < iy1:
            region[iy0 - ry0:iy1 - ry0, ix0 - rx0:ix1 - rx0] = False
    lum = gray[ry0:ry1, rx0:rx1][region]
    col = rgb[ry0:ry1, rx0:rx1][region]
    if lum.size < 40:
        return None
    chroma = col.max(axis=1).astype(int) - col.min(axis=1).astype(int)
    return {'median_rgb': [int(v) for v in np.median(col, axis=0)], 'p10': float(np.percentile(lum, 10)),
            'p90': float(np.percentile(lum, 90)), 'chroma_fraction': float((chroma > 60).mean()),
            'dark_fraction': float((lum < 128).mean()), 'pixels': int(lum.size)}


def ink_color(rgb, gray, box, background_lum):
    import numpy as np
    x0, y0, x1, y1 = box
    lum = gray[y0:y1, x0:x1]
    col = rgb[y0:y1, x0:x1]
    mask = lum < background_lum - 60
    if mask.sum() < 10:
        return [0, 0, 0]
    return [int(v) for v in np.median(col[mask], axis=0)]


def source_image_dpi(page) -> float | None:
    best = None
    area = page.rect.get_area() or 1
    for info in page.get_image_info():
        x0, y0, x1, y1 = info['bbox']
        bw, bh = abs(x1 - x0), abs(y1 - y0)
        if bw * bh < 0.5 * area or not info.get('width') or not info.get('height'):
            continue
        iw, ih = info['width'], info['height']
        dpi = min(max(iw, ih) / max(bw, bh), min(iw, ih) / min(bw, bh)) * 72
        best = dpi if best is None else max(best, dpi)
    return best


def image_union_fraction(page) -> float:
    area = page.rect.get_area() or 1
    total = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info['bbox']
        total += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(1.0, total / area)


def analyse_scanned_page(page, index: int, *, binary: str, lang: str, lang_key: str, workdir: Path,
                         log: list[dict[str, Any]]) -> dict[str, Any]:
    """渲染、方向、OCR、版式门；受支持时返回覆盖后的背景与文字行。"""
    import numpy as np
    import pymupdf
    from PIL import Image
    record: dict[str, Any] = {'page': index + 1, 'kind': 'scanned', 'findings': []}
    dpi = source_image_dpi(page)
    record['source_image_dpi'] = round(dpi, 1) if dpi else None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_DPI / 72, RENDER_DPI / 72), alpha=False)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    render_path = workdir / f'page-{index + 1:03d}.render.png'
    image.save(render_path)
    record['render'] = {'path': render_path.name, 'sha256': sha256_file(render_path), 'size_px': list(image.size),
                        'dpi': RENDER_DPI}
    if dpi is not None and dpi < MIN_SOURCE_DPI * DPI_TOLERANCE:
        record['findings'].append(finding('ocr_resolution_too_low', page=index + 1, source_image_dpi=round(dpi, 1),
                                          minimum_dpi=MIN_SOURCE_DPI))
        return record
    # 表格/网格框线证据在 OSD 之前按渲染方向检测（对称判定，与旋转无关）
    rules = ruling_lines(image.convert('L'))
    record['ruling_lines'] = rules
    if ruled_table_evidence(rules):
        record['findings'].append(finding('ocr_table_unsupported', page=index + 1, ruling_lines=rules,
                                          evidence='ruled_lines_before_ocr'))
        return record
    orientation = osd(binary, render_path, log)
    record['osd'] = orientation
    rotate = orientation['rotate'] or 0
    if rotate:
        if (orientation['confidence'] or 0) < OSD_MIN_CONFIDENCE:
            record['findings'].append(finding('ocr_orientation_uncertain', page=index + 1, osd=orientation))
            return record
        image = image.rotate(-rotate, expand=True)
        upright = workdir / f'page-{index + 1:03d}.upright.png'
        image.save(upright)
        record['upright'] = {'path': upright.name, 'rotated_clockwise_degrees': rotate, 'sha256': sha256_file(upright)}
        ocr_input = upright
    else:
        ocr_input = render_path
    words = ocr_tsv(binary, ocr_input, lang, log, 'ocr')
    tsv_path = workdir / f'page-{index + 1:03d}.words.json'
    tsv_path.write_text(json.dumps(words, ensure_ascii=False) + '\n', encoding='utf-8')
    lines = refine_fragmented_rows(group_lines(words), ocr_input, binary=binary, lang=lang, lang_key=lang_key,
                                   workdir=workdir, page_no=index + 1, log=log)
    record['refined_rows'] = [{'text': l['text'], 'from': l['refined_from']} for l in lines if l.get('refined_from')]
    verify_weak_lines(lines, ocr_input, binary=binary, lang=lang, lang_key=lang_key, workdir=workdir,
                      page_no=index + 1, log=log)
    record['weak_line_verification'] = [{'text': l['text'], 'passes': l.get('verification_passes'),
                                         'outcome': l['weak_word_verification']} for l in lines if 'weak_word_verification' in l]
    for line in lines:
        line['class'] = classify_line(line, lang_key)
        line['math'] = line['class'] != 'non_text' and is_math_line(line['text'])
    text_lines = [l for l in lines if l['class'] == 'text']
    uncertain = [l for l in lines if l['class'] == 'uncertain']
    readable_total = sum(l['readable_chars'] for l in lines if l['class'] != 'non_text') or 1
    record['ocr_text'] = '\n'.join(l['text'] for l in lines if l['class'] != 'non_text')
    (workdir / f'page-{index + 1:03d}.ocr.txt').write_text(record['ocr_text'] + '\n', encoding='utf-8')
    record['lines'] = {'text': len(text_lines), 'uncertain': len(uncertain),
                       'non_text': sum(1 for l in lines if l['class'] == 'non_text'),
                       'math': sum(1 for l in lines if l['math'])}
    confs = [w['conf'] for w in words if w['conf'] >= 0 and (_CJK.search(w['text']) or _LATIN.search(w['text']))]
    record['mean_word_conf'] = round(statistics.fmean(confs), 2) if confs else 0.0
    heights = [l['bbox_px'][3] - l['bbox_px'][1] for l in text_lines]
    scale = (dpi / RENDER_DPI) if dpi else 1.0
    record['median_line_height_source_px'] = round(statistics.median(heights) * scale, 1) if heights else None
    page_no = index + 1
    f = record['findings']
    if not text_lines:
        f.append(finding('ocr_no_reliable_text', page=page_no, mean_word_conf=record['mean_word_conf']))
        return record
    if record['median_line_height_source_px'] is not None and record['median_line_height_source_px'] < MIN_LINE_HEIGHT_PX:
        f.append(finding('ocr_resolution_too_low', page=page_no,
                         median_line_height_source_px=record['median_line_height_source_px'], minimum_px=MIN_LINE_HEIGHT_PX))
    vertical = [l for l in text_lines + uncertain if (l['bbox_px'][3] - l['bbox_px'][1]) > 2 * (l['bbox_px'][2] - l['bbox_px'][0])
                and l['readable_chars'] >= 3]
    if len(vertical) >= 2:
        f.append(finding('ocr_vertical_text_unsupported', page=page_no, lines=len(vertical)))
    skew = estimate_skew(text_lines)
    record['skew_degrees'] = skew
    if skew is not None and abs(skew) > MAX_SKEW_DEGREES:
        f.append(finding('ocr_skew_unsupported', page=page_no, skew_degrees=skew, maximum=MAX_SKEW_DEGREES))
    gray_img = image.convert('L')
    median_h = statistics.median(heights)
    tabular = [l for l in text_lines + uncertain if sum(1 for g in l['gaps'] if g > 2.0 * median_h) >= 2]
    record['tabular_lines'] = len(tabular)
    if len(tabular) >= 3:
        f.append(finding('ocr_table_unsupported', page=page_no, evidence='column_gaps', tabular_lines=len(tabular),
                         samples=[l['text'][:60] for l in tabular[:3]]))
    math_lines = [l for l in lines if l['math']]
    if math_lines:
        f.append(finding('ocr_formula_unsupported', page=page_no, lines=len(math_lines),
                         samples=[l['text'][:60] for l in math_lines[:5]]))
    uncertain_chars = sum(l['readable_chars'] for l in uncertain)
    if (record['mean_word_conf'] < PAGE_MEAN_CONF[lang_key] or len(uncertain) > MAX_UNCERTAIN_LINES
            or uncertain_chars / readable_total > MAX_UNCERTAIN_CHAR_RATIO):
        f.append(finding('ocr_low_confidence', page=page_no, mean_word_conf=record['mean_word_conf'],
                         minimum_mean_conf=PAGE_MEAN_CONF[lang_key], uncertain_lines=len(uncertain),
                         uncertain_char_ratio=round(uncertain_chars / readable_total, 4),
                         samples=[l['text'][:60] for l in uncertain[:5]]))
    # 上下标 / 叠排分式：在覆盖原图之前按图像几何检查（OCR 把 x² 读成 x? 时文字里已没有数学证据）
    gray_np = np.asarray(gray_img)
    ink_threshold = _ink_threshold(gray_np)
    script_lines = []
    x_heights = []
    cjk_skipped = 0
    for l in text_lines + uncertain:
        ev = line_script_evidence(gray_np, l, ink_threshold)
        cjk_skipped += ev['cjk_stroke_like_skipped']
        if _CJK.search(l['text']):
            ev = dict(ev, x_height=None)        # 汉字行的“x 高”是字高，不参与分数线尺度
        if ev['x_height']:
            x_heights.append(ev['x_height'])
        if ev['suspects']:
            script_lines.append({'text': l['text'][:80], 'bbox_px': l['bbox_px'], 'baseline_px': ev['baseline'],
                                 'x_height_px': ev['x_height'], 'suspects': ev['suspects'][:5]})
    latin_lines = [l for l in text_lines + uncertain if not _CJK.search(l['text'])]
    bars = fraction_bar_evidence(gray_np, latin_lines, statistics.median(x_heights) if x_heights else 0.0, ink_threshold) \
        if latin_lines else []
    record['script_check'] = {'ink_threshold': ink_threshold, 'lines_checked': len(text_lines + uncertain),
                              'script_lines': len(script_lines), 'fraction_bars': len(bars),
                              'cjk_stroke_like_skipped': cjk_skipped}
    if script_lines or bars:
        # 复用公式拒绝码（错误码集合保持稳定）；details.evidence 区分图像几何证据与文字证据
        f.append(finding('ocr_formula_unsupported', page=page_no, evidence='image_geometry', kind='math_script_or_stacked_fraction',
                         script_lines=len(script_lines), fraction_bars=len(bars), samples=script_lines[:5],
                         fraction_samples=bars[:3]))
    if f:
        record['line_details'] = [{k: l[k] for k in ('key', 'bbox_px', 'text', 'mean_conf', 'class', 'math')} for l in lines]
        return record
    # 覆盖原文：可信文字行与不确定行（≤2 行，经上面的门）都覆盖；不确定行同样写回（低置信度在回执中标出）
    rgb = np.asarray(image).copy()
    gray = np.asarray(gray_img)
    covered = text_lines + uncertain
    pads = {}
    boxes = []
    for l in covered:
        x0, y0, x1, y1 = l['bbox_px']
        pad = max(3, int(0.12 * (y1 - y0)))
        pads[id(l)] = pad
        boxes.append([x0 - pad, y0 - pad, x1 + pad, y1 + pad])
    page_bg = int(np.percentile(gray, 90))
    over_graphics = []
    for l, box in zip(covered, boxes):
        x0, y0, x1, y1 = l['bbox_px']
        stats = ring_stats(rgb, gray, (x0, y0, x1, y1), [b for b in boxes if b is not box], pads[id(l)])
        if stats is None:
            fill = [page_bg] * 3; background_lum = page_bg
        else:
            if stats['p90'] - stats['p10'] > 60 or stats['chroma_fraction'] > 0.05 or stats['dark_fraction'] > 0.08:
                over_graphics.append({'text': l['text'][:40], 'bbox_px': l['bbox_px'], 'ring': stats})
                continue
            fill = stats['median_rgb']; background_lum = int(sum(fill) / 3)
        l['ink_rgb'] = ink_color(rgb, gray, (x0, y0, x1, y1), background_lum)
        l['fill_rgb'] = fill
    if over_graphics:
        f.append(finding('ocr_text_over_graphics_unsupported', page=page_no, lines=len(over_graphics),
                         samples=over_graphics[:3]))
        return record
    h, w = gray.shape
    for l, box in zip(covered, boxes):
        x0, y0, x1, y1 = [max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])]
        rgb[y0:y1, x0:x1] = l['fill_rgb']
    cleaned = Image.fromarray(rgb)
    chroma = (np.asarray(cleaned).max(axis=2).astype(int) - np.asarray(cleaned).min(axis=2).astype(int))
    colourful = float((chroma > 40).mean()) > 0.001
    cleaned_path = workdir / f'page-{index + 1:03d}.background.png'
    (cleaned if colourful else cleaned.convert('L')).save(cleaned_path, optimize=True)
    residue_words = ocr_tsv(binary, cleaned_path, lang, log, 'background_residue')
    residue = [w for w in residue_words if w['conf'] >= RESIDUE_CONF and
               (len(_CJK.findall(w['text'])) >= 1 or len(_LATIN_WORD.findall(w['text'])) >= 1)
               and (len(_CJK.findall(w['text'])) + len(_LATIN.findall(w['text']))) >= 2]
    record['background_residue'] = {'words_recognised': len(residue_words), 'source_words_conf_ge_70': len(residue),
                                    'samples': [w['text'] for w in residue[:10]]}
    if residue:
        f.append(finding('ocr_background_text_residue', page=page_no, words=len(residue),
                         samples=[w['text'] for w in residue[:10]]))
        return record
    record['background'] = {'path': cleaned_path.name, 'sha256': sha256_file(cleaned_path), 'colour': colourful,
                            'size_px': [w, h]}
    record['text_lines'] = [{'bbox_px': l['bbox_px'], 'text': l['text'], 'mean_conf': l['mean_conf'],
                             'class': l['class'], 'paragraph': l['key'][:2], 'ink_rgb': l['ink_rgb']} for l in covered]
    return record


def native_page_check(page, index: int, *, binary: str, lang: str, lang_key: str, workdir: Path,
                      log: list[dict[str, Any]]) -> dict[str, Any]:
    """原生文字页若同时含页主导大图：对该图区域 OCR，含大量文字即拒绝（页内混合不支持）。"""
    import pymupdf
    record: dict[str, Any] = {'page': index + 1, 'kind': 'native', 'findings': []}
    area = page.rect.get_area() or 1
    big = [i for i in page.get_image_info() if abs((i['bbox'][2] - i['bbox'][0]) * (i['bbox'][3] - i['bbox'][1])) >= .5 * area]
    if not big:
        return record
    clip = pymupdf.Rect(big[0]['bbox']) & page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_DPI / 72, RENDER_DPI / 72), clip=clip, alpha=False)
    path = workdir / f'page-{index + 1:03d}.native-image.png'
    pix.save(path)
    words = ocr_tsv(binary, path, lang, log, 'native_image_probe')
    reliable = [w for w in words if w['conf'] >= TEXT_CONF[lang_key] and (_CJK.search(w['text']) or _LATIN_WORD.search(w['text']))]
    record['image_probe'] = {'reliable_words': len(reliable), 'bbox': list(clip)}
    if len(reliable) >= 20:
        record['findings'].append(finding('ocr_mixed_within_page_unsupported', page=index + 1, reliable_words=len(reliable)))
    return record


# ---------------------------------------------------------------- reconstruction

BODY_LINE_HEIGHT_RATIO = 1.15   # 行高 ≤ 1.15× 页面中位行高视为正文行
BODY_SIZE_CAP_RATIO = 1.03      # 正文行字号上限 = 1.03× 页面中位拟合字号


def fit_font_sizes(lines: list[dict[str, Any]], font, scale: float) -> None:
    by_par: dict[tuple, list[dict[str, Any]]] = {}
    for line in lines:
        width_pt = (line['bbox_px'][2] - line['bbox_px'][0]) * scale
        length = font.text_length(line['text'], 1) or 1
        height_pt = (line['bbox_px'][3] - line['bbox_px'][1]) * scale
        line['fit'] = min(width_pt / length, height_pt * 1.25)
        by_par.setdefault(tuple(line['paragraph']), []).append(line)
    # 正文行（行高不明显大于页面中位行高）字号不超过页面正文中位字号的 1.03 倍：
    # OCR 漏字/并字会使宽度拟合字号虚高，把正文行画成标题样式，误导后端版面识别。
    heights = [(l['bbox_px'][3] - l['bbox_px'][1]) * scale for l in lines]
    page_height = statistics.median(heights) if heights else 0
    page_fit = statistics.median(l['fit'] for l in lines) if lines else 0
    for line, height_pt in zip(lines, heights):
        if height_pt <= BODY_LINE_HEIGHT_RATIO * page_height:
            line['fit'] = min(line['fit'], BODY_SIZE_CAP_RATIO * page_fit)
    for members in by_par.values():
        common = statistics.median(l['fit'] for l in members)
        for line in members:
            width_pt = (line['bbox_px'][2] - line['bbox_px'][0]) * scale
            length = font.text_length(line['text'], 1) or 1
            line['fontsize'] = round(max(4.0, min(common, width_pt * 1.02 / length)), 2)


def reconstruct(source, records: list[dict[str, Any]], workdir: Path, output: Path, source_lang: str) -> dict[str, Any]:
    import pymupdf
    out = pymupdf.open()
    font_name = 'ocrcjk' if source_lang == 'zh' else 'tiro'
    font = pymupdf.Font('china-s') if source_lang == 'zh' else pymupdf.Font('tiro')
    for record in records:
        index = record['page'] - 1
        if record['kind'] != 'scanned':
            out.insert_pdf(source, from_page=index, to_page=index)
            continue
        w_px, h_px = record['background']['size_px']
        scale = 72 / RENDER_DPI
        page = out.new_page(width=w_px * scale, height=h_px * scale)
        page.insert_image(page.rect, filename=str(workdir / record['background']['path']))
        if source_lang == 'zh':
            page.insert_font(fontname=font_name, fontbuffer=font.buffer)
        fit_font_sizes(record['text_lines'], font, scale)
        for line in record['text_lines']:
            x0, y0, x1, y1 = [v * scale for v in line['bbox_px']]
            size = line['fontsize']
            descent = 0.12 if source_lang == 'zh' else (0.22 if re.search(r'[gjpqy,;]', line['text']) else 0.05)
            colour = tuple(v / 255 for v in line['ink_rgb'])
            page.insert_text((x0, y1 - descent * size), line['text'], fontsize=size, fontname=font_name, color=colour)
        record['reconstructed_page'] = out.page_count
    out.subset_fonts()
    out.save(output, garbage=3, deflate=True)
    out.close()
    return {'path': str(output), 'sha256': sha256_file(output), 'bytes': output.stat().st_size,
            'font': 'Droid Sans Fallback (PyMuPDF built-in china-s, Apache-2.0)' if source_lang == 'zh' else 'Times-Roman (PDF base-14)'}


# ---------------------------------------------------------------- driver

def run(input_pdf: Path, workdir: Path, target_language: str, tesseract: str | None = None) -> dict[str, Any]:
    import pymupdf
    from pdf_input_preflight import classify_page, detect_language
    workdir.mkdir(parents=True, exist_ok=False)
    started = time.time()
    lang = ENGINE_LANGS[target_language]
    lang_key = 'chi_sim' if target_language == 'en' else 'eng'
    source_lang = SOURCE_LANG[target_language]
    manifest: dict[str, Any] = {'schema_version': SCHEMA_VERSION, 'input': {'path': str(input_pdf), 'sha256': sha256_file(input_pdf)},
                                'target_language': target_language, 'source_language': source_lang, 'ocr_languages': lang,
                                'render_dpi': RENDER_DPI, 'thresholds': {
                                    'min_source_dpi': MIN_SOURCE_DPI, 'min_line_height_px': MIN_LINE_HEIGHT_PX,
                                    'text_conf': TEXT_CONF[lang_key], 'page_mean_conf': PAGE_MEAN_CONF[lang_key],
                                    'max_uncertain_lines': MAX_UNCERTAIN_LINES, 'max_skew_degrees': MAX_SKEW_DEGREES,
                                    'osd_min_confidence': OSD_MIN_CONFIDENCE, 'residue_conf': RESIDUE_CONF,
                                    'word_min_conf': WORD_MIN_CONF, 'junk_conf': JUNK_CONF,
                                    'max_uncertain_char_ratio': MAX_UNCERTAIN_CHAR_RATIO, 'dpi_tolerance': DPI_TOLERANCE,
                                    'rule_ink_threshold': RULE_INK_THRESHOLD, 'rule_row_tolerance': RULE_ROW_TOLERANCE,
                                    'body_line_height_ratio': BODY_LINE_HEIGHT_RATIO, 'body_size_cap_ratio': BODY_SIZE_CAP_RATIO},
                                'quality_claim': 'none: OCR text is machine output, not human-verified; never quality acceptance',
                                'processes': [], 'pages': []}
    info = engine_info(tesseract)
    manifest['engine'] = info
    findings: list[dict[str, Any]] = []
    if not info['available']:
        findings.append(finding('ocr_engine_unavailable', missing=info.get('missing')))
        return finish(manifest, findings, workdir, started)
    binary = info['binary']
    source = pymupdf.open(input_pdf)
    log = manifest['processes']
    try:
        records = []
        for index in range(source.page_count):
            page = source[index]
            facts = classify_page(page)
            if facts['kind'] == 'scanned_image':
                record = analyse_scanned_page(page, index, binary=binary, lang=lang, lang_key=lang_key, workdir=workdir, log=log)
            elif facts['kind'] == 'no_text_layer':
                record = {'page': index + 1, 'kind': 'outlined', 'findings': [finding('ocr_outlined_vector_text_unsupported', page=index + 1)]}
            elif facts['kind'] == 'sparse_text' and image_union_fraction(page) >= .5:
                record = {'page': index + 1, 'kind': 'tiled', 'findings': [finding('ocr_tiled_scan_unsupported', page=index + 1,
                                                                                    image_union_fraction=round(image_union_fraction(page), 3))]}
            elif facts['kind'] == 'native_text':
                record = native_page_check(page, index, binary=binary, lang=lang, lang_key=lang_key, workdir=workdir, log=log)
            else:
                record = {'page': index + 1, 'kind': 'sparse', 'findings': []}
            record['classification'] = facts
            records.append(record)
            findings.extend(record['findings'])
            manifest['pages'].append({k: v for k, v in record.items() if k not in ('text_lines', 'line_details')})
        scanned = [r for r in records if r['kind'] == 'scanned']
        if not any(r['kind'] in ('scanned', 'outlined', 'tiled') for r in records):
            findings.append(finding('ocr_route_no_scanned_pages', pages=source.page_count))
        if findings:
            # 被拒页的逐行明细写入独立文件，便于人工复核拒绝原因
            for r in records:
                if r.get('line_details'):
                    (workdir / f'page-{r["page"]:03d}.lines.json').write_text(json.dumps(r['line_details'], ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
            return finish(manifest, findings, workdir, started)
        language = detect_language('\n'.join(r.get('ocr_text', '') for r in scanned))
        manifest['ocr_source_language'] = language
        if language['language'] != source_lang:
            findings.append(finding('ocr_source_language_mismatch', expected=source_lang, **language))
            return finish(manifest, findings, workdir, started)
        for r in scanned:
            (workdir / f'page-{r["page"]:03d}.lines.json').write_text(json.dumps(r['text_lines'], ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        output = workdir / input_pdf.name
        manifest['reconstructed_source'] = reconstruct(source, records, workdir, output, source_lang)
        for page_row, r in zip(manifest['pages'], records):
            page_row['reconstructed_page'] = r.get('reconstructed_page')
            if r['kind'] == 'scanned':
                page_row['text_line_count'] = len(r['text_lines'])
                page_row['low_confidence_lines_written'] = [l['text'] for l in r['text_lines'] if l['class'] == 'uncertain']
    except EngineError as exc:
        findings.append(finding('ocr_engine_failed', detail=str(exc)[:300]))
    finally:
        source.close()
    return finish(manifest, findings, workdir, started)


def finish(manifest: dict[str, Any], findings: list[dict[str, Any]], workdir: Path, started: float) -> dict[str, Any]:
    manifest['findings'] = findings
    manifest['status'] = 'blocked' if findings else 'ok'
    manifest['error_code'] = findings[0]['code'] if findings else None
    manifest['seconds'] = round(time.time() - started, 3)
    (workdir / 'OCR_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='bounded OCR reconstruction for scanned/mixed PDFs (scanned_ocr route)')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--target-language', choices=sorted(ENGINE_LANGS), default='zh')
    parser.add_argument('--tesseract', default=None)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    manifest = run(args.input.resolve(), args.workdir.resolve(), args.target_language, args.tesseract)
    print(json.dumps({k: manifest.get(k) for k in ('status', 'error_code', 'seconds')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
