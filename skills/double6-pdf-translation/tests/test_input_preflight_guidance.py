"""PR #25 review-10 P2-2：candidate 输入预检拒绝后的只读下一步提示。

只依据稳定错误码与预检已核实的页数/页型给出中文提示；拒绝码、退出码 2、页数与页型字段不变，
不自动切换路线、不分块、不执行任何入口。成对边界：分块整份上限内/外、整页扫描图像/无文字层矢量页/未知页型、
损坏/加密/其它错误无路线、正常页无提示、stdout 与持久化回执一致。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

import paper_translation_workflow as wf  # noqa: E402
from chunked_translation import CHUNKING_CONTRACT  # noqa: E402

LIMIT = CHUNKING_CONTRACT['max_document_pages']
EN = ('Test-time training adapts model weights during inference so that the network can store '
      'long context in fast weights. We evaluate the approach on language modeling and view synthesis. ') * 6
ROUTE_WORDS = ('chunked-candidate', 'scanned_ocr', 'prepare-scan', 'inspect-input')


def native_pdf(path, pages=1, text=EN):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def blank_pdf(path, pages):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=100, height=100)
    doc.save(path)
    doc.close()
    return path


def scan_pdf(path):
    src = fitz.open()
    page = src.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 545, 790), EN, fontsize=10)
    pix = page.get_pixmap(dpi=60)
    doc = fitz.open()
    out = doc.new_page(width=page.rect.width, height=page.rect.height)
    out.insert_image(out.rect, pixmap=pix)
    doc.save(path)
    return path


def vector_pdf(path):
    """无文字层、≥5000 个矢量路径项（预检判 no_text_layer，常见于文字转曲）。"""
    doc = fitz.open()
    page = doc.new_page()
    shape = page.new_shape()
    for i in range(5200):
        x, y = 40 + (i % 100) * 5, 60 + (i // 100) * 13
        shape.draw_line((x, y), (x + 3, y + 4))
    shape.finish(color=(0, 0, 0), width=0.6)
    shape.commit()
    doc.save(path)
    return path


def run_candidate(tmp_path, pdf, route='digital_pdf'):
    (tmp_path / 'FREEZE.json').write_text('{}')
    env = {k: v for k, v in os.environ.items()
           if k not in ('LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY', 'PDF2ZH_OPENAI_API_KEY', 'PDF2ZH_DEBUG')}
    env.update(PAPER_TRANSLATION_WORKSPACE=str(tmp_path / 'ws'), PYTHONDONTWRITEBYTECODE='1')
    proc = subprocess.run([sys.executable, str(SKILL / 'scripts/paper_translation_workflow.py'), 'candidate',
                           '--input', str(pdf), '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'),
                           '--freeze', str(tmp_path / 'FREEZE.json'), '--route', route, '--model', 'agent-self',
                           '--base-url', 'http://127.0.0.1:9/v1', '--lock-path', str(tmp_path / 'heavy.lock')],
                          capture_output=True, text=True, env=env, timeout=60)
    result = json.loads(proc.stdout)
    receipt = json.loads((tmp_path / 'rc/WORKFLOW_INPUT_PREFLIGHT.json').read_text())
    assert proc.returncode == 2 and result['status'] == 'blocked', proc.stderr
    assert not (tmp_path / 'out').exists() and 'Traceback' not in proc.stderr
    return result, receipt


def assert_stdout_matches_receipt(result, receipt):
    for key in ('error_code', 'findings', 'page_count', 'pages', 'max_pages', 'status'):
        assert result.get(key) == receipt.get(key), key
    assert result.get('guidance') == receipt.get('guidance')
    assert ('guidance' in result) == ('guidance' in receipt)
    assert result['preflight_ref']['sha256'] == wf.sha(Path(result['preflight_ref']['path']))


def text_of(result):
    return json.dumps({'findings': result.get('findings'), 'next_actions': result.get('next_actions'),
                       'guidance': result.get('guidance')}, ensure_ascii=False)


# ---------- 长文档：分块整份上限内 / 外 ----------

@pytest.mark.parametrize('pages', [6, 20, 21, LIMIT])
def test_within_chunked_limit_points_to_inspection_then_chunked_candidate(tmp_path, pages):
    result, receipt = run_candidate(tmp_path, blank_pdf(tmp_path / 'in.pdf', pages))
    assert result['error_code'] == 'page_limit_exceeded' and result['page_count'] == pages
    finding = result['findings'][0]
    assert finding['details'] == {'page_count': pages, 'max_pages': 5}
    assert finding['message'].startswith(f'PDF 共 {pages} 页，超过当前路线上限 5 页')  # 原拒绝文字不变
    g = result['guidance']
    assert g['route_hint'] == 'chunked-candidate' and g['eligibility'] == 'within_chunked_document_limit'
    assert (g['auto_switch'], g['executed'], g['page_kinds_verified']) == (False, False, False)
    assert (g['page_count'], g['max_pages'], g['chunked_document_max_pages']) == (pages, 5, LIMIT)
    inspect, freeze, run = g['next_steps']
    assert 'inspect-input' in inspect
    if pages <= 20:
        assert f'--max-pages {pages}' in inspect and '先只读核对输入事实' in inspect
    else:
        assert '最多 --max-pages 20' in inspect and '尚未核实' in inspect
    assert f'pages=1..{pages}' in freeze and 'CHUNKING_CONTRACT' in freeze and '不能沿用当前 FREEZE' in freeze
    assert 'chunked-candidate --input <PDF> --freeze <新 FREEZE.json> --route digital_pdf' in run
    assert '冻结完成后才可显式运行' in run
    assert '不自动分块' in g['message'] and '不提高页数上限' in g['message']
    assert_stdout_matches_receipt(result, receipt)


def test_over_chunked_limit_promises_no_route(tmp_path):
    result, receipt = run_candidate(tmp_path, blank_pdf(tmp_path / 'in.pdf', LIMIT + 1))
    assert result['error_code'] == 'page_limit_exceeded' and result['page_count'] == LIMIT + 1
    g = result['guidance']
    assert g['route_hint'] is None and g['next_steps'] == [] and g['eligibility'] == 'over_chunked_document_limit'
    assert not any(word in text_of(result) for word in ROUTE_WORDS)
    assert f'{LIMIT} 页' in g['message'] and '不推荐换路线' in g['message']
    assert_stdout_matches_receipt(result, receipt)


def test_scanned_ocr_route_long_document_points_to_same_route_chunked(tmp_path):
    result, receipt = run_candidate(tmp_path, blank_pdf(tmp_path / 'in.pdf', 7), route='scanned_ocr')
    assert result['error_code'] == 'page_limit_exceeded'
    assert '--route scanned_ocr' in result['guidance']['next_steps'][2]
    assert_stdout_matches_receipt(result, receipt)


def test_latex_route_long_document_gets_no_chunked_hint(tmp_path):
    result, receipt = run_candidate(tmp_path, blank_pdf(tmp_path / 'in.pdf', 7), route='latex_verified')
    assert result['error_code'] == 'page_limit_exceeded' and 'guidance' not in result
    assert 'chunked-candidate' not in text_of(result)
    assert_stdout_matches_receipt(result, receipt)


# ---------- 非原生页：整页扫描图像 / 无文字层矢量页 / 未知页型 ----------

def test_scanned_image_page_points_to_explicit_scanned_route_with_requirements(tmp_path):
    result, receipt = run_candidate(tmp_path, scan_pdf(tmp_path / 'in.pdf'))
    assert result['error_code'] == 'non_digital_pages'
    assert result['findings'][0]['details'] == {'pages': [{'page': 1, 'kind': 'scanned_image'}]}
    g = result['guidance']
    assert g['route_hint'] == 'scanned_ocr' and g['eligibility'] == 'scanned_image_pages_only'
    assert g['page_kinds'] == [{'page': 1, 'kind': 'scanned_image'}] and g['auto_switch'] is False
    inspect, ocr, prepare = g['next_steps']
    assert 'inspect-input --input <PDF>' in inspect and '--source-review' in inspect and '须人工审阅源图' in inspect
    assert 'candidate --route scanned_ocr' in ocr and 'OCR_ROUTING' in ocr and '1–5 页' in ocr
    assert 'Tesseract' in ocr and 'ocr_formula_unsupported' in ocr and '须人工复核' in ocr
    assert 'prepare-scan' in prepare and '--groups' in prepare and '--roles' in prepare
    assert '不自动切换路线' in g['message']
    assert_stdout_matches_receipt(result, receipt)


def test_vector_page_without_text_layer_is_not_scan_eligible(tmp_path):
    result, receipt = run_candidate(tmp_path, vector_pdf(tmp_path / 'in.pdf'))
    assert result['error_code'] == 'non_digital_pages'
    assert result['findings'][0]['details'] == {'pages': [{'page': 1, 'kind': 'no_text_layer'}]}
    g = result['guidance']
    assert g['route_hint'] is None and g['next_steps'] == [] and g['eligibility'] == 'not_scan_eligible'
    assert not any(word in text_of(result) for word in ROUTE_WORDS)
    assert_stdout_matches_receipt(result, receipt)


def blocked(findings, **extra):
    return wf.blocked_result(findings, **extra)


@pytest.mark.parametrize('kinds', [['sparse_text'], ['mystery'], [None], ['scanned_image', 'no_text_layer']])
def test_unknown_or_mixed_page_kinds_are_not_scan_eligible(kinds):
    pages = [{'page': i + 1, 'kind': k} for i, k in enumerate(kinds)]
    g = wf.input_preflight_guidance(blocked([wf.finding('non_digital_pages', pages=pages)], page_count=len(pages)),
                                    'candidate', 'digital_pdf')
    assert g['route_hint'] is None and g['eligibility'] == 'not_scan_eligible'
    assert 'scanned_ocr' not in json.dumps(g, ensure_ascii=False)


def test_scan_hint_requires_verified_pages():
    for details in ({}, {'pages': []}, {'pages': [{'kind': 'scanned_image'}]}, {'pages': 'x'}):
        report = blocked([wf.finding('non_digital_pages', **details)], page_count=1)
        assert wf.input_preflight_guidance(report, 'candidate', 'digital_pdf') is None
    report = blocked([wf.finding('non_digital_pages', pages=[{'page': 1, 'kind': 'scanned_image'}])], page_count=None)
    assert wf.input_preflight_guidance(report, 'candidate', 'digital_pdf') is None


# ---------- 损坏 / 加密 / 其它错误：不推荐任何路线 ----------

def test_corrupt_pdf_gets_no_route(tmp_path):
    bad = tmp_path / 'in.pdf'
    bad.write_bytes(b'%PDF-1.7\nbroken\n')
    result, receipt = run_candidate(tmp_path, bad)
    assert result['error_code'] == 'pdf_truncated_or_corrupt' and 'guidance' not in result
    assert not any(word in text_of(result) for word in ROUTE_WORDS)
    assert_stdout_matches_receipt(result, receipt)


def test_user_password_pdf_gets_no_route(tmp_path):
    pdf = tmp_path / 'in.pdf'
    doc = fitz.open()
    doc.new_page().insert_textbox(fitz.Rect(50, 50, 545, 790), EN, fontsize=10)
    doc.save(pdf, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='u', owner_pw='o')
    doc.close()
    result, receipt = run_candidate(tmp_path, pdf)
    assert result['error_code'] == 'encrypted_user_password_required' and 'guidance' not in result
    assert not any(word in text_of(result) for word in ROUTE_WORDS)
    assert_stdout_matches_receipt(result, receipt)


@pytest.mark.parametrize('code', ['preflight_guard_stopped', 'page_load_failed', 'not_a_pdf', 'input_not_found',
                                  'source_language_matches_target', 'some_future_code'])
def test_other_or_unknown_errors_get_no_route(code):
    report = blocked([wf.finding(code)], page_count=3)
    assert wf.input_preflight_guidance(report, 'candidate', 'digital_pdf') is None


def test_second_error_or_other_action_or_unverified_count_gets_no_route():
    scan = wf.finding('non_digital_pages', pages=[{'page': 1, 'kind': 'scanned_image'}])
    long = wf.finding('page_limit_exceeded', page_count=48, max_pages=5)
    assert wf.input_preflight_guidance(blocked([scan, wf.finding('page_load_failed', pages=[])], page_count=1),
                                       'candidate', 'digital_pdf') is None
    assert wf.input_preflight_guidance(blocked([scan], page_count=1), 'collect', 'digital_pdf') is None
    assert wf.input_preflight_guidance(blocked([scan], page_count=1), 'candidate', 'scanned_ocr') is None
    assert wf.input_preflight_guidance(blocked([long], page_count=48), 'collect', 'digital_pdf') is None
    for details in ({'max_pages': 5}, {'page_count': '48', 'max_pages': 5}, {'page_count': True, 'max_pages': 5},
                    {'page_count': 48}, {'page_count': 4, 'max_pages': 5}):
        report = blocked([wf.finding('page_limit_exceeded', **details)])
        assert wf.input_preflight_guidance(report, 'candidate', 'digital_pdf') is None
    # FREEZE 页门（声明页数，不是预检核实的页数）不是本提示的依据。
    freeze_gate = blocked([wf.finding('page_limit_exceeded', declared_pages=[1, 2], max_pages=5)])
    assert wf.input_preflight_guidance(freeze_gate, 'candidate', 'digital_pdf') is None


# ---------- 正常原生页：无换路线提示 ----------

def test_normal_native_page_gets_no_hint_and_unchanged_receipt(tmp_path):
    result, receipt = run_candidate(tmp_path, native_pdf(tmp_path / 'in.pdf'))
    assert result['error_code'] == 'input_or_contract_invalid'  # 预检通过，按空 FREEZE 拒绝
    assert receipt['status'] == 'ok' and 'guidance' not in receipt and 'guidance' not in result
    assert not any(word in text_of(result) for word in ROUTE_WORDS)
    assert [p['kind'] for p in receipt['pages']] == ['native_text']
