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

# PR #20 review 2：reviewer probe_math_geometry.py 的正文与两张汉字变量上下标页（逐字相同的生成方式）
REVIEW2_BODY = ('本研究对不同条件下的样本开展系统观察，并比较各项测量结果。为了确保记录可靠，每个样本都在相同环境下重复测试。'
                '研究人员根据测量记录分析数据，给出清晰的描述和结论。所有原始记录均按照统一标准保存，以便后续核对。') * 5
REVIEW2 = {'cjk-variable-sup': -7, 'cjk-variable-sub': 4}
ZH_PUNCT_TEXT = ('他说：“结果（见表1）稳定，‘样本’共12个；《报告》第3页、第5页均有记录。”然后，团队复核了A组、B组和C组的数据：'
                 '均值为3.5，方差为0.25；误差约2%。问题是：为什么？答案很简单：数据足够。'
                 '缩写PDF和OCR保持原样。半角标点也会出现,例如逗号;以及冒号:如此。') * 2
ZH_COMMON_TEXT = ('春天来了，小河边的柳树发出新芽，孩子们在草地上放风筝。学校图书馆新到了一批关于历史、地理、物理和化学的书籍，'
                  '老师鼓励同学们每周至少读完一本。城市交通日益便利，地铁线路通往主要街区，公共汽车更加准时。'
                  '医院改进了挂号流程，病人等候时间缩短；农民利用新技术种植水稻和小麦，产量稳步增长。'
                  '心理学家认为，良好的睡眠、适量运动与均衡饮食对健康至关重要。我们应当珍惜时间，努力学习，关心他人。') * 2
# 汉字行手工排版片段：(文字, 字体, 字号 pt, 抬高 pt（负为压低）, 之后前进 pt（None=按字宽）, 起笔前横移 pt)
HAN = 'china-s'
ZH_LINES = {
    'zh_han_sup_digit': [('估计量乙', HAN, 14, 0), ('3', 'tiro', 9, 7, 7), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_han_sub_digit': [('估计量乙', HAN, 14, 0), ('1', 'tiro', 9, -4, 7), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_han_sup_letter': [('估计量甲', HAN, 14, 0), ('n', 'tiro', 9, 7, 7), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_han_sub_letter': [('估计量甲', HAN, 14, 0), ('i', 'tiro', 9, -4, 6), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_han_sup_touching': [('估计量甲', HAN, 14, 0), ('2', 'tiro', 9, 7, 4.5, -3.0), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_han_sub_touching': [('估计量甲', HAN, 14, 0), ('2', 'tiro', 9, -4, 4.5, -3.0), ('的数值用于比较所有样本。', HAN, 14, 0)],
    'zh_footnote_sup': [('这一结论见于早期文献', HAN, 14, 0), ('1', 'tiro', 9, 7, 7), ('，此处不再展开。', HAN, 14, 0)],
    'zh_footnote_circled': [('这一结论见于早期文献①，此处不再展开。', HAN, 14, 0)],
    'zh_footnote_bracket': [('这一结论见于早期文献［1］，此处不再展开。', HAN, 14, 0)],
    'zh_punct_mix': [('他说：“结果（见表1）稳定，‘样本’共12个。”', HAN, 14, 0)],
    'zh_common_chars': [('心理学家认为，良好的睡眠与均衡饮食对健康至关重要。', HAN, 14, 0)],
    'touch_sup_latin': [('The tolerance was set to 10', 'tiro', 14, 0), ('3', 'tiro', 8.7, 5.0, 3.6), ('for each run.', 'tiro', 14, 0, None, -0.9)],
    'touch_sub_latin': [('Each molecule of H', 'tiro', 14, 0), ('2', 'tiro', 8.7, -2.4, 3.6), ('O was counted twice.', 'tiro', 14, 0, None, -0.9)],
}
ZH_BODIES = {'zh_punct_mix': ZH_PUNCT_TEXT, 'zh_common_chars': ZH_COMMON_TEXT}

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
CASES_REVIEW2 = list(REVIEW2) + list(ZH_LINES)
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
# PR #20 review 2：汉字旁的上下标（分离/粘连）、带圈序号必须在覆盖前拒绝；中文标点/常用字/［1］式序号原样通过
EXPECTED_REVIEW2 = {
    'cjk-variable-sup': ('blocked', GEOM), 'cjk-variable-sub': ('blocked', GEOM),
    'zh_han_sup_digit': ('blocked', GEOM), 'zh_han_sub_digit': ('blocked', GEOM),
    'zh_han_sup_letter': ('blocked', GEOM), 'zh_han_sub_letter': ('blocked', GEOM),
    'zh_han_sup_touching': ('blocked', GEOM), 'zh_han_sub_touching': ('blocked', GEOM),
    'zh_footnote_sup': ('blocked', GEOM), 'zh_footnote_circled': ('blocked', GEOM),
    'zh_footnote_bracket': ('ok', None), 'zh_punct_mix': ('ok', None), 'zh_common_chars': ('ok', None),
    'touch_sup_latin': ('blocked', GEOM), 'touch_sub_latin': ('blocked', GEOM),
}
EXPECTED.update(EXPECTED_REVIEW2)


def target_for(name: str) -> str:
    return 'en' if name.startswith(('zh_', 'cjk-')) else 'zh'


def _rasterise(page, path: Path) -> Path:
    import fitz
    pix = page.get_pixmap(dpi=300)
    scan = fitz.open()
    p = scan.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=pix.tobytes('png'))
    scan.save(path)
    return path


def make_review2_case(name: str, out_dir: Path) -> Path:
    """与 reviewer probe_math_geometry.py 逐字相同的排版（china-s 正文 12 pt；末行“估计量甲”14 pt，tiro 9 pt 的 2 抬高 7 pt / 压低 4 pt）。"""
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    shift = REVIEW2[name]
    doc = fitz.open(); p = doc.new_page(width=595, height=842); font = fitz.Font('china-s')
    p.insert_font(fontname='cjk', fontbuffer=font.buffer)
    p.insert_textbox((65, 60, 530, 630), REVIEW2_BODY, fontname='cjk', fontsize=12, lineheight=1.4)
    prefix = '估计量甲'; suffix = '的结果用于分析所有样本的变化。'
    p.insert_text((65, 700), prefix, fontname='cjk', fontsize=14); x = 65 + font.text_length(prefix, 14)
    p.insert_text((x, 700 + shift), '2', fontname='tiro', fontsize=9); p.insert_text((x + 7, 700), suffix, fontname='cjk', fontsize=14)
    return _rasterise(p, out_dir / f'{name}.pdf')


def make_case(name: str, out_dir: Path) -> Path:
    import fitz
    if name in REVIEW2:
        return make_review2_case(name, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    p = d.new_page(width=595, height=842)
    if name in ZH_LINES:
        # 与 reviewer probe 相同：china-s 字形以嵌入字体（insert_font）写入，标点按真实字形落位
        han = fitz.Font(HAN)
        p.insert_font(fontname='cjk', fontbuffer=han.buffer)
        if name.startswith('touch_'):
            p.insert_textbox((65, 70, 530, 650), TEXT, fontsize=12, fontname='tiro', lineheight=1.4)
        else:
            p.insert_textbox((65, 70, 530, 650), ZH_BODIES.get(name, ZH_TEXT), fontsize=12, fontname='cjk', lineheight=1.6)
        x = 65.0
        for seg in ZH_LINES[name]:
            text, fnt, fs, rise = seg[:4]
            advance = seg[4] if len(seg) > 4 else None
            x += seg[5] if len(seg) > 5 else 0
            p.insert_text((x, 700 - rise), text, fontsize=fs, fontname='cjk' if fnt == HAN else fnt)
            if advance is None:
                advance = han.text_length(text, fs) if fnt == HAN else fitz.get_text_length(text, fontname=fnt, fontsize=fs)
            x += advance
        return _rasterise(p, out_dir / f'{name}.pdf')
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
    for case in sys.argv[2:] or CASES + CASES_REVIEW2:
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


_ROOT2: Path | None = None


def reviewer2_root() -> Path:
    """PR #20 review 2 reviewer 测试的 R：按 reviewer probe_math_geometry.py 的同一排版真实生成并运行
    cjk-variable-sup / cjk-variable-sub，返回含 geometry-independent/<case>.result.json 的目录。tesseract 不在时 skip（不 mock）。"""
    global _ROOT2
    import atexit
    import shutil
    import tempfile
    import pytest
    import ocr_route
    if not (shutil.which('tesseract') and ocr_route.engine_info().get('available')):
        pytest.skip('tesseract + chi_sim/eng/osd not installed (OCR route optional)', allow_module_level=True)
    if _ROOT2 is None:
        root = Path(tempfile.mkdtemp(prefix='ocr-math-review2-'))
        atexit.register(shutil.rmtree, root, True)
        for case in REVIEW2:
            run_case(case, root / 'geometry-independent')
        _ROOT2 = root
    return _ROOT2
