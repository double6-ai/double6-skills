# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-31：写回墨迹覆盖率测量独立件（随 3.1.0 审计盲区自动化引入）；变更见 Skill 根目录 MODIFICATIONS.md。
"""墨迹覆盖率测量(独立模块,写回审计的基础件)。

来源:内部审计路线图 T8。实验中验证过的检测法——写回后逐行栅格化,零墨迹行切片
暗像素比例 0-0.5%,正常行 13-17%。本模块只做测量与分类,不做任何修改;
写回审计(audit_blindspots)与离线抽查复用这里的接口,因此保持无副作用、
可独立调用。

接口:
    render_page_grayscale(pdf_path, page_number, dpi) -> np.ndarray   # 0-255 灰度图
    dark_pixel_ratio(gray_img, threshold) -> float                     # 暗像素占比
    measure_region_ink(pdf_path, page_number, bbox_pt, dpi) -> float   # bbox(pt 坐标)内暗像素占比
    measure_line_inks(pdf_path, page_number, lines, dpi) -> list[dict] # 批量:[{index,bbox_pt,ratio,char_count,text}]
    classify_line_ink(ratio, page_median) -> 'normal'|'low-ink'|'zero-ink'

阈值为实验参考值而非硬门:正常带受字号/字重/行距影响,分类时以同页中位数
为相对基准,绝对零墨迹阈值才有裁决力。
"""
from pathlib import Path

import fitz
import numpy as np

# 实验验证的参考带(逐行切片实测)
ZERO_INK_MAX_RATIO = 0.005     # ratio <= 该值视为零墨迹(文字层在但渲染无墨)
REFERENCE_NORMAL_RANGE = (0.13, 0.17)  # 正常译文行的典型暗像素带,仅作参考记录
LOW_INK_FRACTION_OF_MEDIAN = 0.25      # 低于同页中位数 1/4 视为异常偏低
DEFAULT_DPI = 150
DEFAULT_DARK_THRESHOLD = 128  # 灰度 < 该值记为暗像素


def render_page_grayscale(pdf_path, page_number, dpi=DEFAULT_DPI):
    """整页渲染为 0-255 灰度 ndarray;page_number 从 1 计。"""
    path = Path(pdf_path)
    if not path.exists():
        raise ValueError('ink_metrics_pdf_missing')
    doc = fitz.open(path)
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError('ink_metrics_page_out_of_range')
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, annots=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    finally:
        doc.close()


def dark_pixel_ratio(gray_img, threshold=DEFAULT_DARK_THRESHOLD):
    """暗像素占比;空图返回 0.0 而不是除零。"""
    img = np.asarray(gray_img)
    if img.size == 0:
        return 0.0
    return float((img < threshold).sum()) / float(img.size)


def measure_region_ink(pdf_path, page_number, bbox_pt, dpi=DEFAULT_DPI,
                       threshold=DEFAULT_DARK_THRESHOLD):
    """bbox(pt 坐标 x0,y0,x1,y1)内暗像素占比。行 bbox 建议纵向各外扩 1-2pt,
    避免抗锯齿边缘把整行算空;纯背景区返回 0 是合法结果。"""
    if len(bbox_pt) != 4 or bbox_pt[0] >= bbox_pt[2] or bbox_pt[1] >= bbox_pt[3]:
        raise ValueError('ink_metrics_bbox_invalid')
    path = Path(pdf_path)
    doc = fitz.open(path)
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError('ink_metrics_page_out_of_range')
        page = doc[page_number - 1]
        page_rect = page.rect
        x0, y0, x1, y1 = bbox_pt
        x0, y0 = max(x0, page_rect.x0), max(y0, page_rect.y0)
        x1, y1 = min(x1, page_rect.x1), min(y1, page_rect.y1)
        if x0 >= x1 or y0 >= y1:
            return 0.0
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, annots=False,
                              clip=fitz.Rect(x0, y0, x1, y1))
        if pix.width == 0 or pix.height == 0:
            return 0.0
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        return dark_pixel_ratio(img, threshold)
    finally:
        doc.close()


def measure_line_inks(pdf_path, page_number, lines, dpi=DEFAULT_DPI,
                      threshold=DEFAULT_DARK_THRESHOLD, pad_pt=1.5):
    """批量行墨迹测量。

    lines: [{'bbox_pt': [x0,y0,x1,y1], 'text': str(可选), ...}, ...]
    返回逐行 dict,index 对应输入下标;bbox 做了 pad 外扩后的实测比例。
    """
    results = []
    for i, line in enumerate(lines):
        bbox = line['bbox_pt'] if isinstance(line, dict) else line
        padded = [bbox[0] - pad_pt, bbox[1] - pad_pt, bbox[2] + pad_pt, bbox[3] + pad_pt]
        ratio = measure_region_ink(pdf_path, page_number, padded, dpi, threshold)
        row = {'index': i, 'bbox_pt': list(bbox), 'ratio': round(ratio, 5)}
        if isinstance(line, dict) and 'text' in line:
            row['text'] = line['text']
        results.append(row)
    return results


def classify_line_ink(ratio, page_median=None):
    """行墨迹分类。

    normal   正常;
    zero-ink ratio <= ZERO_INK_MAX_RATIO(绝对判据,文字层在但渲染无墨);
    low-ink  有墨但显著低于同页中位数(相对判据,page_median 缺失时退化为
             低于参考带下限的四分之一)。
    """
    if ratio <= ZERO_INK_MAX_RATIO:
        return 'zero-ink'
    if page_median and page_median > ZERO_INK_MAX_RATIO:
        if ratio < LOW_INK_FRACTION_OF_MEDIAN * page_median:
            return 'low-ink'
    elif ratio < LOW_INK_FRACTION_OF_MEDIAN * REFERENCE_NORMAL_RANGE[0]:
        return 'low-ink'
    return 'normal'


def page_ink_summary(pdf_path, page_number, dpi=DEFAULT_DPI):
    """单页全部文字行的墨迹摘要,直接可用于写回审计与像素抽查。"""
    path = Path(pdf_path)
    doc = fitz.open(path)
    try:
        if not 1 <= page_number <= len(doc):
            raise ValueError('ink_metrics_page_out_of_range')
        page = doc[page_number - 1]
        lines = []
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            for line in block['lines']:
                text = ''.join(s['text'] for s in line['spans']).strip()
                if text:
                    lines.append({'bbox_pt': list(line['bbox']), 'text': text})
    finally:
        doc.close()
    measured = measure_line_inks(pdf_path, page_number, lines, dpi)
    ratios = [m['ratio'] for m in measured]
    median = float(np.median(ratios)) if ratios else None
    for m in measured:
        m['class'] = classify_line_ink(m['ratio'], median)
    return {'pdf': str(path), 'page': page_number, 'dpi': dpi,
            'line_count': len(measured),
            'median_ratio': round(median, 5) if median is not None else None,
            'reference_normal_range': list(REFERENCE_NORMAL_RANGE),
            'lines': measured}
