"""rc.8 常规 OCR 路线（candidate --route scanned_ocr）。

- 纯函数门：不确定行、多遍一致性、框线证据（与方向无关）、正文字号上限、质量封顶、FREEZE 路由合同、引擎缺失只阻断 OCR 路线。
- 真实引擎（tesseract 不在时 skip，绝不用 mock 代替）：合成扫描页 → 受支持页重建；低分辨率 / 表格框线 / 公式 / 旋转。
- 真实进程计量与回收（tests/test_ocr_route_processes.py）。"""
import json
import shutil
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import ocr_route  # noqa: E402

HAS_ENGINE = bool(shutil.which('tesseract')) and ocr_route.engine_info().get('available')
needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason='tesseract + chi_sim/eng/osd not installed (OCR route optional)')

BODY = ('The floor of most of the bentonite beds is marked by a sharp contact with the subjacent shale, '
        'which is locally silicified just below the bentonite to form a thin hard cherty layer. In general '
        'the roof is less definite and the bentonite of the upper part of the bed grades through an indistinct '
        'zone of dark bentonitic shale into the overlying bedrock, which is most commonly dark gray shale. '
        'Ordinarily the bed itself is made up of a number of clay layers which differ from one another in color, '
        'texture or colloidal properties. Beds averaging less than three feet in thickness cannot be mined profitably.')


def scanned_pdf(path: Path, *, text=BODY, dpi=300, rotate=0, grid=False, extra_lines=()):
    """先排版一页电子文本，再按 dpi 栅格化成只含整页图像的“扫描”PDF。"""
    import pymupdf
    src = pymupdf.open()
    page = src.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(72, 90, 523, 600), text, fontsize=12, fontname='tiro', lineheight=1.4)
    y = 620
    for line in extra_lines:
        page.insert_text((72, y), line, fontsize=12, fontname='tiro')
        y += 20
    if grid:
        for k in range(6):
            page.draw_line((72, 640 + 30 * k), (523, 640 + 30 * k), width=1.2)
        for x in (72, 250, 400, 523):
            page.draw_line((x, 640), (x, 790), width=1.2)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    out = pymupdf.open()
    target = out.new_page(width=595, height=842)
    target.insert_image(target.rect, stream=pix.tobytes('png'))
    if rotate:
        target.set_rotation(rotate)
    out.save(path)
    return path


# ---------- 纯函数门 ----------

def _line(text, conf=95.0, weakest=None, **extra):
    row = {'text': text, 'mean_conf': conf, 'readable_chars': len(text), 'min_readable_word_conf': weakest}
    row.update(extra)
    return row


def test_weak_word_line_is_uncertain_unless_multi_pass_consensus():
    assert ocr_route.classify_line(_line('a thin hard cherty layer', 92, weakest=3.0), 'eng') == 'uncertain'
    assert ocr_route.classify_line(_line('a thin hard cherty layer', 92, weakest=3.0, weak_word_verification='consensus'), 'eng') == 'text'
    assert ocr_route.classify_line(_line('a thin hard cherty layer', 92, weakest=88.0), 'eng') == 'text'
    # 中文源中孤立的极短拉丁片段（“用”被识别成“Fil.”）
    assert ocr_route.classify_line(_line('Fil.', 90, weakest=90.0), 'chi_sim') == 'uncertain'
    assert ocr_route.classify_line(_line('42 .', 10), 'eng') == 'non_text'


def test_consensus_key_ignores_spacing_punctuation_and_case_only():
    k = ocr_route._consensus_key
    assert k('a thin, hard layer') == k('athin hard Layer')
    assert k('签订疯络接入合同') != k('签订网络接入合同')


def test_ruled_table_evidence_is_orientation_symmetric_and_needs_both_directions():
    assert ocr_route.ruled_table_evidence({'horizontal': 5, 'vertical': 3})
    assert ocr_route.ruled_table_evidence({'horizontal': 3, 'vertical': 5})      # 旋转 90° 的表格
    assert not ocr_route.ruled_table_evidence({'horizontal': 1, 'vertical': 3})  # 单条页眉线 + 竖线
    assert not ocr_route.ruled_table_evidence({'horizontal': 0, 'vertical': 2})


def test_ruling_lines_detects_slightly_skewed_grid_but_not_text_rows():
    from PIL import Image, ImageDraw
    img = Image.new('L', (2480, 3508), 255)
    d = ImageDraw.Draw(img)
    for k in range(5):  # 轻微倾斜的水平线（跨 1800 px 漂移 3 px）
        d.line([(300, 1500 + 120 * k), (2100, 1503 + 120 * k)], fill=0, width=3)
    for x in (300, 900, 2100):
        d.line([(x, 1500), (x, 1980)], fill=0, width=3)
    rules = ocr_route.ruling_lines(img)
    assert ocr_route.ruled_table_evidence(rules), rules
    text_like = Image.new('L', (2480, 3508), 255)
    d = ImageDraw.Draw(text_like)
    for row in range(30):
        for col in range(40):  # 字符块之间有空隙：不是长线
            d.rectangle([300 + col * 45, 300 + row * 90, 330 + col * 45, 340 + row * 90], fill=0)
    assert not ocr_route.ruled_table_evidence(ocr_route.ruling_lines(text_like))


def test_body_lines_are_not_drawn_larger_than_page_body_size():
    import pymupdf
    font = pymupdf.Font('tiro')
    lines = [{'bbox_px': [0, 100 * i, 1800, 100 * i + 50], 'text': 'x' * 90, 'paragraph': [1, i]} for i in range(10)]
    # OCR 漏字：同样宽度只识别出很少字符 → 宽度拟合字号虚高
    lines.append({'bbox_px': [0, 1200, 1800, 1250], 'text': 'L, USER R', 'paragraph': [1, 99]})
    ocr_route.fit_font_sizes(lines, font, 72 / 300)
    body = sorted(l['fontsize'] for l in lines[:-1])[5]
    assert lines[-1]['fontsize'] <= round(ocr_route.BODY_SIZE_CAP_RATIO * body, 2) + 0.01


def test_engine_missing_blocks_only_the_ocr_route(tmp_path):
    info = ocr_route.engine_info(str(tmp_path / 'no-such-tesseract'))
    assert info['available'] is False and info['missing']
    import paper_translation_workflow as wf
    health = wf.doctor('http://127.0.0.1:9/v1', 'm', provider_generation_required=False)
    assert 'ocr_engine' not in health                 # 默认 doctor（电子路线）不检查 OCR
    original = ocr_route.engine_info
    try:
        ocr_route.engine_info = lambda tesseract=None: {'engine': 'tesseract', 'available': False, 'missing': ['tesseract']}
        status = wf.ocr_engine_status()
    finally:
        ocr_route.engine_info = original
    assert status['blocks_routes'] == ['scanned_ocr'] and status['blocks_digital_route'] is False


def test_ocr_quality_is_capped_and_fail_stays_fail():
    import paper_translation_workflow as wf
    passing = {'status': 'succeeded', 'quality_status': 'pass'}
    wf.cap_ocr_quality(passing)
    assert passing['quality_status'] == 'unverified' and passing['quality_status_before_ocr_cap'] == 'pass'
    assert passing['ocr_text_layer_is_acceptance'] is False
    assert any(p['id'] == 'ocr_text_unverified' for p in passing['quality_pending'])
    failing = {'status': 'succeeded', 'quality_status': 'fail'}
    wf.cap_ocr_quality(failing)
    assert failing['quality_status'] == 'fail'
    blocked = {'status': 'blocked', 'error_code': 'ocr_table_unsupported'}
    wf.cap_ocr_quality(blocked)
    assert 'quality_status' not in blocked


def test_freeze_requires_exact_ocr_routing_contract(tmp_path):
    import paper_translation_workflow as wf
    pdf = scanned_pdf(tmp_path / 'scan.pdf', dpi=72)
    scope = tmp_path / 'scope.json'
    scope.write_text('{}')
    base = {'input': wf.ref(pdf), 'pages': [1], 'complete_semantic_scope': True, 'scope_evidence': wf.ref(scope),
            'route': 'scanned_ocr', 'model': 'm'}
    for contract in (dict(wf.DIGITAL_ROUTING), {**wf.OCR_ROUTING, 'unsupported_layouts': 'flagged'}, None):
        with pytest.raises(ValueError, match='scanned OCR routing contract'):
            wf.validate_freeze({**base, 'routing_contract': contract}, pdf, 'scanned_ocr', 'm')
    with pytest.raises(ValueError, match='scanned OCR routing contract'):
        wf.validate_freeze({**base, 'routing_contract': dict(wf.OCR_ROUTING), 'source_cache_contract': 'x'},
                           pdf, 'scanned_ocr', 'm')
    # 正确的路由合同越过这一检查（之后的模型指纹等检查照常进行，这里不伪造）
    with pytest.raises(Exception) as excinfo:
        wf.validate_freeze({**base, 'routing_contract': dict(wf.OCR_ROUTING)}, pdf, 'scanned_ocr', 'm')
    assert 'scanned OCR routing contract' not in str(excinfo.value)


def test_error_codes_are_stable_and_documented():
    expected = {'ocr_engine_unavailable', 'ocr_route_no_scanned_pages', 'ocr_outlined_vector_text_unsupported',
                'ocr_tiled_scan_unsupported', 'ocr_mixed_within_page_unsupported', 'ocr_resolution_too_low',
                'ocr_orientation_uncertain', 'ocr_skew_unsupported', 'ocr_vertical_text_unsupported',
                'ocr_table_unsupported', 'ocr_formula_unsupported', 'ocr_low_confidence',
                'ocr_text_over_graphics_unsupported', 'ocr_no_reliable_text', 'ocr_source_language_mismatch',
                'ocr_background_text_residue', 'ocr_engine_failed'}
    assert set(ocr_route.CODES) == expected
    doc = (SKILL / 'references' / 'ocr-route.md').read_text(encoding='utf-8')
    for code in expected:
        assert code in doc, code


# ---------- 真实引擎 ----------

@needs_engine
def test_real_engine_reconstructs_supported_scan(tmp_path):
    pdf = scanned_pdf(tmp_path / 'scan.pdf')
    manifest = ocr_route.run(pdf, tmp_path / 'w', 'zh')
    assert manifest['status'] == 'ok', manifest['findings']
    rebuilt = Path(manifest['reconstructed_source']['path'])
    assert ocr_route.sha256_file(rebuilt) == manifest['reconstructed_source']['sha256']
    import pymupdf
    text = pymupdf.open(rebuilt)[0].get_text()
    assert 'bentonite' in text and 'cherty' in text
    assert manifest['quality_claim'].startswith('none')
    assert all(p['returncode'] == 0 and p['pid'] and p['created_at'] for p in manifest['processes'])
    page = manifest['pages'][0]
    for name in ('render', 'background'):
        assert (tmp_path / 'w' / page[name]['path']).is_file()


@needs_engine
def test_real_engine_rejects_low_resolution(tmp_path):
    manifest = ocr_route.run(scanned_pdf(tmp_path / 'low.pdf', dpi=100), tmp_path / 'w', 'zh')
    assert manifest['status'] == 'blocked' and manifest['error_code'] == 'ocr_resolution_too_low'
    assert 'reconstructed_source' not in manifest or not manifest.get('reconstructed_source')


@needs_engine
def test_real_engine_rejects_ruled_table(tmp_path):
    manifest = ocr_route.run(scanned_pdf(tmp_path / 'table.pdf', grid=True), tmp_path / 'w', 'zh')
    assert manifest['status'] == 'blocked' and manifest['error_code'] == 'ocr_table_unsupported'


@needs_engine
def test_real_engine_rejects_formula_lines(tmp_path):
    manifest = ocr_route.run(scanned_pdf(tmp_path / 'f.pdf', text=BODY[:400],
                                         extra_lines=('M = (y - 1) x + 6 / (k + 1)        (105)',
                                                      'T = a + b * c - d / e = 2 x y      (106)')), tmp_path / 'w', 'zh')
    assert manifest['status'] == 'blocked'
    assert 'ocr_formula_unsupported' in {f['code'] for f in manifest['findings']}


@needs_engine
def test_real_engine_uprights_rotated_page_via_osd(tmp_path):
    manifest = ocr_route.run(scanned_pdf(tmp_path / 'rot.pdf', rotate=90), tmp_path / 'w', 'zh')
    assert manifest['status'] == 'ok', manifest['findings']
    page = manifest['pages'][0]
    assert page['osd']['rotate'] in (90, 270) and page['upright']['rotated_clockwise_degrees'] == page['osd']['rotate']


@needs_engine
def test_real_engine_rejects_source_language_mismatch(tmp_path):
    # 英文扫描页却声明 zh→en（源应为中文）：OCR 文本语言与声明不符 → 拒绝
    manifest = ocr_route.run(scanned_pdf(tmp_path / 'en.pdf'), tmp_path / 'w', 'en')
    assert manifest['status'] == 'blocked'
    assert manifest['error_code'] in ('ocr_source_language_mismatch', 'ocr_low_confidence')


def test_native_only_pdf_is_not_an_ocr_input(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 500, 700), BODY, fontsize=11)
    path = tmp_path / 'digital.pdf'
    doc.save(path)
    manifest = ocr_route.run(path, tmp_path / 'w', 'zh', tesseract=shutil.which('tesseract') or '/nonexistent/tesseract')
    assert manifest['status'] == 'blocked'
    assert manifest['error_code'] in ('ocr_route_no_scanned_pages', 'ocr_engine_unavailable')
    if HAS_ENGINE:
        assert manifest['error_code'] == 'ocr_route_no_scanned_pages'
