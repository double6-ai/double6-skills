"""本地 OCR：macOS Vision 或已安装的 Tesseract；材料经管道传递，不下载模型。"""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

MAX_SIDE = 3200


class OcrUnavailable(Exception):
    pass


def _cache_binary():
    source = Path(__file__).with_name('ocr_vision.swift')
    key = hashlib.sha256(source.read_bytes() + platform.machine().encode()).hexdigest()[:20]
    cache = Path.home() / '.local/share/double6-redaction/ocr'
    return source, cache / ('vision-' + key)


def _tesseract():
    configured = os.environ.get('REDACTION_TESSERACT')
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_absolute() and path.is_file() else None
    return shutil.which('tesseract')


def status():
    if sys.platform == 'darwin':
        _, binary = _cache_binary()
        if binary.is_file() or shutil.which('swiftc'):
            return {'available': True, 'engine': 'macOS Vision', 'languages': ['zh-Hans', 'zh-Hant', 'en-US'], 'local_only': True}
    executable = _tesseract()
    if executable:
        try:
            result = subprocess.run([executable, '--list-langs'], capture_output=True, timeout=10, check=True)
            languages = [s for s in result.stdout.decode('utf-8', 'replace').splitlines() if s in ('chi_sim', 'chi_tra', 'eng')]
            if languages:
                return {'available': True, 'engine': 'Tesseract', 'languages': languages, 'local_only': True}
        except (OSError, subprocess.SubprocessError):
            pass
    return {'available': False, 'engine': None, 'languages': [], 'local_only': True,
            'message': '未找到本地 OCR。macOS 需可用的 Command Line Tools；Windows 请安装 Tesseract 及中文、英文语言包。文字层仍可检测，图片内容需补选。'}


def prepare_vision():
    source, binary = _cache_binary()
    if binary.is_file():
        return binary
    compiler = shutil.which('swiftc')
    if not compiler:
        raise OcrUnavailable('本机没有可用的 Vision 编译工具，请安装 macOS Command Line Tools。')
    binary.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # 临时目录只接收编译产物，不写入用户材料。
    with tempfile.TemporaryDirectory(prefix='build-', dir=binary.parent) as folder:
        target = Path(folder) / 'vision'
        try:
            subprocess.run([compiler, str(source), '-O', '-o', str(target)], capture_output=True, timeout=120, check=True)
            target.chmod(0o700)
            os.replace(target, binary)
        except (OSError, subprocess.SubprocessError) as exc:
            raise OcrUnavailable('本地 Vision 工具准备失败；请检查 Command Line Tools。') from exc
    return binary


def _valid_box(value, size):
    if not isinstance(value, (tuple, list)) or len(value) != 4 or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in value):
        raise OcrUnavailable('OCR 返回了无法定位的区域。')
    x0, y0, x1, y1 = value
    return [max(0, min(size[0], x0)), max(0, min(size[1], y0)), max(0, min(size[0], x1)), max(0, min(size[1], y1))]


def _vision(payload, size):
    binary = prepare_vision()
    try:
        result = subprocess.run([str(binary)], input=payload, capture_output=True, timeout=60, check=True)
        if len(result.stdout) > 16 * 1024 * 1024:
            raise OcrUnavailable('OCR 文字数量超出本次处理范围。')
        data = json.loads(result.stdout)
        lines = []
        for row in data['lines']:
            text = ''; boxes = []
            for char in row['chars']:
                value = char['text']; box = char['box']
                scaled = _valid_box([box[0]*size[0], box[1]*size[1], box[2]*size[0], box[3]*size[1]], size)
                text += value; boxes.extend([scaled] * len(value))
            lines.append({'text': text, 'boxes': boxes})
        return lines, data['languages']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise OcrUnavailable('本地 Vision 文字识别未完成，请检查图片或稍后重试。') from exc


def _tess(payload, size, rendered_size, info):
    args = [_tesseract(), 'stdin', 'stdout', '-l', '+'.join(info['languages']), '--psm', '3', 'tsv']
    try:
        result = subprocess.run(args, input=payload, capture_output=True, timeout=60, check=True)
        if len(result.stdout) > 16 * 1024 * 1024:
            raise OcrUnavailable('OCR 文字数量超出本次处理范围。')
        groups = {}
        for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t'):
            if row['level'] != '5' or not row['text'].strip():
                continue
            key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
            x, y, w, h = [int(row[k]) for k in ('left', 'top', 'width', 'height')]
            box = _valid_box([x*size[0]/rendered_size[0], y*size[1]/rendered_size[1], (x+w)*size[0]/rendered_size[0], (y+h)*size[1]/rendered_size[1]], size)
            groups.setdefault(key, []).append((row['text'], box))
        lines = []
        for words in groups.values():
            text = ''; boxes = []
            for word, box in words:
                # 汉字词之间不添空格；英文词保留词间距。定位始终覆盖完整识别词。
                if text and not ('\u3400' <= text[-1] <= '\u9fff' or '\u3400' <= word[0] <= '\u9fff'):
                    text += ' '; boxes.append(None)
                text += word; boxes.extend([box] * len(word))
            lines.append({'text': text, 'boxes': boxes})
        return lines, info['languages']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise OcrUnavailable('本地 Tesseract 文字识别未完成，请检查语言包或图片。') from exc


def recognize(image):
    size = image.size
    rendered = image.convert('RGB')
    rendered.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    encoded = io.BytesIO(); rendered.save(encoded, format='PNG')
    info = status()
    if not info['available']:
        raise OcrUnavailable(info['message'])
    if info['engine'] == 'macOS Vision':
        lines, languages = _vision(encoded.getvalue(), size)
    else:
        lines, languages = _tess(encoded.getvalue(), size, rendered.size, info)
    return {'lines': lines, 'engine': info['engine'], 'languages': languages}
