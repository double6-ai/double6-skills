"""PR #19 评审第 2 轮反例（移植自评审的 test_sparse_math.py）：中文正文行内只有 1–2 个结构对象
（填充矢量公式字形、Form XObject 变量）时，必须被中译英预检拦下，或由成品门判 fail。

真实 PyMuPDF 原生文字层 PDF，直接调用 inspect_pdf 与 check_render_residue，无模型调用。
译文页优先使用 babeldoc 实际排版用的 NotoSans-Regular.ttf（本机缓存）；不存在时（例如 CI）退回内置 Helvetica。
"""
import json
import os
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review_boundaries as b  # noqa: E402

ENGLISH = 'Consider an array of antennas arranged along the axis.'


def noto_font() -> str | None:
    for base in (os.environ.get('HOME', ''), '/home/box'):
        path = Path(base) / '.cache/babeldoc/fonts/NotoSans-Regular.ttf'
        if path.is_file():
            return str(path)
    return None


def write_source(n, kind, path):
    d = fitz.open()
    p = b._inline_page(d)
    x = 72 + 10.5 * len(b.ZH_LINE_A) + 4
    y = 120
    if kind == 'vector':
        for k in range(n):
            xx = x + 2 + 7 * k
            p.draw_polyline([(xx, y), (xx + 3, y - 8), (xx + 6, y), (xx, y)], color=None, fill=(0, 0, 0))
    else:
        f = fitz.open()
        fp = f.new_page(width=40, height=16)
        fp.insert_text((2, 12), 'MN'[:n], fontname='tiro', fontsize=11)
        p.show_pdf_page(fitz.Rect(x, y - 12, x + 30, y + 3), f, 0)
    d.save(path)
    d.close()


def write_english(page, text=ENGLISH, point=(72, 100)):
    font = noto_font()
    if font:
        page.insert_text(point, text, fontname='Noto', fontfile=font, fontsize=11)
    else:
        page.insert_text(point, text, fontname='helv', fontsize=11)


@pytest.mark.parametrize('kind', ['vector', 'xobject'])
@pytest.mark.parametrize('n', [1, 2])
def test_sparse_inline_math_cannot_escape_both_gates(kind, n, tmp_path):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    src = tmp_path / f'{kind}{n}-source.pdf'
    tgt = tmp_path / f'{kind}{n}-target.pdf'
    write_source(n, kind, src)
    d = fitz.open()
    p = d.new_page()
    write_english(p)
    if kind == 'xobject':
        p.insert_text((72, 100), 'MN'[:n], fontname='tiro', fontsize=11)
    d.save(tgt)
    d.close()
    pre = inspect_pdf(src, target_language='en', require_digital=True)
    qa = check_render_residue(src, tgt, target_language='en')
    (tmp_path / f'SPARSE_{kind}{n}.json').write_text(json.dumps({'preflight': pre, 'quality': qa}, ensure_ascii=False, indent=2, default=str))
    assert pre['status'] == 'blocked' or qa['quality_fail'], 'Sparse unsupported inline math passes preflight and rendered residue/structural gate'
