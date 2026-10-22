"""PR #20 review 1：真实 tesseract 的数学上下标 / 分式边界页（生成栅格页 → ocr_route.py，5 GiB / 120 s / 并发 1）。

- reviewer 页（superscript / ordinary / fraction / equation）与 reviewer 的 probe_ocr.py 逐字相同的排版与栅格化；
- 边界页：正文段落 + 一行手工排版的上标 / 下标 / 叠排分式（真实排版几何，不靠 Unicode 上下标字符）；
- 每个页面都由真实引擎跑完整 ocr_route.py（受 bounded_execution 管控），写出 <name>.result.json（与 probe 相同字段）。
被 tests/test_ocr_formula_preservation.py 与 tests/test_ocr_math_script_boundaries.py 复用；也可命令行运行生成证据：
    python tests/ocr_math_pages.py <out_dir> [case ...]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

TEXT = ('The experimental study compares the response of several samples under stable laboratory conditions. '
        'The measurements are repeated to verify the reliability of the observations. '
        'Each sample is stored in a separate container and carefully examined before testing. '
        'The final results provide a clear description of the observed behavior and the practical conclusions. ') * 3

PUNCT_TEXT = ('He said, "It\'s the samples\' state; don\'t retest them," and left. The team\'s notes (see p. 4) were brief: '
              'yes, no, maybe. Results were reported as "stable," "noisy," or "unclear"; the operator\'s log, however, '
              'listed each run separately. Wasn\'t that enough? It was -- mostly. The well-known "rule of thumb" '
              'applies here, as it does there; still, we\'d rather check twice, then once more. ') * 2

ZH_TEXT = ('本研究在稳定的实验室条件下比较了若干样品的响应。每个样品单独存放，并在测试前仔细检查。'
           '测量重复进行，以验证观察结果的可靠性。最终结果清楚地描述了所观察到的行为和实际结论。') * 4

# 行内片段：(文字, 字号比例, 抬高 em；正为上标、负为下标)
SUP, SUB = (0.62, 0.36), (0.62, -0.17)
LINES = {
    'sup_x2_typeset': [('The response is proportional to x', 1, 0), ('2', *SUP), (' for every sample.', 1, 0)],
    'sup_10e-3': [('The tolerance was set to 10', 1, 0), ('-3', *SUP), (' for each run.', 1, 0)],
    'footnote_marker': [('This effect was reported in earlier studies.', 1, 0), ('1', *SUP), (' It is small.', 1, 0)],
    'ordinal_superscript': [('The 1', 1, 0), ('st', *SUP), (' and 2', 1, 0), ('nd', *SUP), (' samples were stored.', 1, 0)],
    'sub_h2o': [('Each molecule of H', 1, 0), ('2', *SUB), ('O was counted twice.', 1, 0)],
    'sub_x_i': [('The sample value x', 1, 0), ('i', *SUB), (' was recorded twice.', 1, 0)],
    'frac_inline': [('The geometric ratio is a/b for every sample.', 1, 0)],
    'ordinal_inline': [('The 1st and 2nd samples were stored separately.', 1, 0)],
    # 中文页（china-s 字体，目标语言 en）
    'zh_plain': [('样品按顺序编号并记录。', 1, 0)],
    'zh_sup_m2': [('样品的面积为 5 m', 1, 0), ('2', *SUP), ('，按顺序记录。', 1, 0)],
    'zh_sub_h2o': [('每个 H', 1, 0), ('2', *SUB), ('O 分子都被计数。', 1, 0)],
}
REVIEWER = {
    'ordinary': 'The response is proportional to the total sample area.',
    'superscript': 'The response is proportional to x\u00b2 for every sample.',
    'fraction': 'The geometric ratio is M/N for every sample.',
    'equation': 'The equation is E = mc\u00b2 for every sample.',
}
CASES = list(REVIEWER) + [c for c in LINES if not c.startswith('zh_')] + ['frac_stacked', 'plain_paragraphs',
                                                                          'punctuation_heavy'] + [c for c in LINES if c.startswith('zh_')]
GEOM = 'image_geometry'   # blocked 且必须有 details.evidence == 'image_geometry' 的 ocr_formula_unsupported
EXPECTED = {  # 期望：blocked + 证据（GEOM = 图像几何；或文字门的错误码），或 ok（原样重建）
    'ordinary': ('ok', None), 'superscript': ('blocked', GEOM),
    'fraction': ('ok', None), 'equation': ('blocked', 'text'),
    'sup_x2_typeset': ('blocked', GEOM), 'sup_10e-3': ('blocked', GEOM),
    'footnote_marker': ('blocked', GEOM),
    'ordinal_superscript': ('blocked', GEOM),
    'sub_h2o': ('blocked', GEOM), 'sub_x_i': ('blocked', GEOM),
    'frac_inline': ('ok', None), 'ordinal_inline': ('ok', None),
    'frac_stacked': ('blocked', GEOM),
    'plain_paragraphs': ('ok', None), 'punctuation_heavy': ('ok', None),
    'zh_plain': ('ok', None), 'zh_sup_m2': ('blocked', GEOM),
    'zh_sub_h2o': ('blocked', GEOM),
}


def target_for(name: str) -> str:
    return 'en' if name.startswith('zh_') else 'zh'


def _rasterise(page, path: Path) -> Path:
    import fitz
    pix = page.get_pixmap(dpi=300)
    scan = fitz.open()
    p = scan.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=pix.tobytes('png'))
    scan.save(path)
    return path


def make_case(name: str, out_dir: Path) -> Path:
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    p = d.new_page(width=595, height=842)
    font = 'china-s' if name.startswith('zh_') else 'tiro'
    if font == 'china-s':
        p.insert_textbox((65, 70, 530, 650), ZH_TEXT, fontsize=12, fontname=font, lineheight=1.6)
    else:
        body = PUNCT_TEXT if name == 'punctuation_heavy' else TEXT
        p.insert_textbox((65, 70, 530, 650), body, fontsize=12, fontname=font, lineheight=1.4)
    size = 14
    if name in REVIEWER:
        p.insert_text((65, 700), REVIEWER[name], fontsize=size, fontname='tiro')
    elif name in LINES:
        x = 65.0
        for text, scale, rise in LINES[name]:
            fs = size * scale
            p.insert_text((x, 700 - rise * size), text, fontsize=fs, fontname=font)
            x += fitz.get_text_length(text, fontname=font, fontsize=fs)
    elif name == 'frac_stacked':
        x = 65.0
        lead = 'The geometric ratio is '
        p.insert_text((x, 700), lead, fontsize=size, fontname='tiro')
        x += fitz.get_text_length(lead, fontname='tiro', fontsize=size)
        fs = size * 0.7
        w = max(fitz.get_text_length(c, fontname='tiro', fontsize=fs) for c in 'ab') + 3
        axis = 700 - 0.25 * size
        p.draw_line((x, axis), (x + w, axis), width=0.6)
        for c, base in (('a', axis - 1.6), ('b', axis + 1.6 + 0.68 * fs)):
            cw = fitz.get_text_length(c, fontname='tiro', fontsize=fs)
            p.insert_text((x + (w - cw) / 2, base), c, fontsize=fs, fontname='tiro')
        x += w + 2
        p.insert_text((x, 700), ' for every sample.', fontsize=size, fontname='tiro')
    elif name != 'plain_paragraphs' and name != 'punctuation_heavy':
        raise KeyError(name)
    return _rasterise(p, out_dir / f'{name}.pdf')


def run_case(name: str, out_dir: Path, *, source: Path | None = None, target: str | None = None) -> dict:
    """与 reviewer probe_ocr.py 相同：bounded_execution 下真实运行 ocr_route.py，写 <name>.result.json。"""
    import fitz
    import psutil
    import bounded_execution as b
    source = source or make_case(name, out_dir)
    target = target or target_for(name)
    work = out_dir / name
    result = b.run_bounded([sys.executable, str(SKILL / 'scripts/ocr_route.py'), '--input', str(source), '--workdir', str(work),
                            '--target-language', target], cwd=SKILL / 'scripts', receipt_dir=out_dir / (name + '-receipts'),
                           operation='ocr-independent', timeout_seconds=120, interval_seconds=.1, rss_limit=5 * 1024 ** 3,
                           memory_metric='rss', max_total_fraction=.5, max_processes=8)
    manifest = work / 'OCR_MANIFEST.json'
    m = json.loads(manifest.read_text()) if manifest.exists() else {}
    row = {'job_status': result['status'], 'stop_reason': result.get('stop_reason'), 'peak': result.get('peak_task_memory_bytes'),
           'cleanup': result.get('cleanup'), 'seconds': result.get('elapsed_seconds'), 'ocr_status': m.get('status'),
           'error_code': m.get('error_code'), 'findings': m.get('findings'), 'text': [p.get('ocr_text') for p in m.get('pages', [])],
           'script_check': [p.get('script_check') for p in m.get('pages', [])]}
    if m.get('reconstructed_source'):
        d = fitz.open(m['reconstructed_source']['path'])
        row['reconstructed_text'] = '\n'.join(p.get_text() for p in d)
    row['actual_alive'] = []
    for ident in result.get('observed_owned_identities', []):
        try:
            q = psutil.Process(ident['pid'])
            if abs(q.create_time() - ident['created_at']) < .01 and q.status() != psutil.STATUS_ZOMBIE:
                row['actual_alive'].append(ident)
        except psutil.NoSuchProcess:
            pass
    (out_dir / (name + '.result.json')).write_text(json.dumps(row, ensure_ascii=False, indent=2))
    return row


if __name__ == '__main__':
    out = Path(sys.argv[1])
    for case in sys.argv[2:] or CASES:
        row = run_case(case, out)
        print(case, row['job_status'], row['ocr_status'], row['error_code'], EXPECTED.get(case), row['seconds'], flush=True)


_ROOT: Path | None = None


def reviewer_root() -> Path:
    """reviewer 测试的 R：生成（与 probe_ocr.py 同一排版、同一 300 dpi 栅格，嵌入图像逐字节相同）并真实运行 superscript 页，
    返回含 ocr-independent/superscript.result.json 的目录。tesseract 不在时整模块 skip（不 mock）。"""
    global _ROOT
    import atexit
    import shutil
    import tempfile
    import pytest
    import ocr_route
    if not (shutil.which('tesseract') and ocr_route.engine_info().get('available')):
        pytest.skip('tesseract + chi_sim/eng/osd not installed (OCR route optional)', allow_module_level=True)
    if _ROOT is None:
        root = Path(tempfile.mkdtemp(prefix='ocr-math-review1-'))
        atexit.register(shutil.rmtree, root, True)
        run_case('superscript', root / 'ocr-independent')
        _ROOT = root
    return _ROOT
