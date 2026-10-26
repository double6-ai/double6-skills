"""扫描重译回归：真实 CLI 到 HTTP 请求、待审标题候选、已准入 OCR 的行与段落身份。"""
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'vendor/babeldoc'), str(SKILL / 'vendor/pdfmathtranslate_next')]

from ocr_text_layout import ENV, bind_ocr_layout, join_wrapped_ocr_groups
from pdf_translation_commands import _compact_policy_items


def test_optional_boolean_cli_reaches_real_http_payload(tmp_path, monkeypatch):
    import pdf2zh_next.config.main as config_main
    from pdf2zh_next.config.main import ConfigManager
    from pdf2zh_next.translator.utils import get_translator
    calls = []
    monkeypatch.setattr(config_main, 'DEFAULT_CONFIG_DIR', tmp_path)
    monkeypatch.setattr(config_main, 'VERSION_DEFAULT_CONFIG_FILE', tmp_path/'version.toml')
    monkeypatch.setattr(ConfigManager, '_default_config_file_path', tmp_path/'default.toml')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            payload = json.dumps({'id': 'unit-test', 'model': 'glm-5.3-flash', 'choices': [
                {'index': 0, 'message': {'role': 'assistant', 'content': '测试'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('PDF2ZH_OPENAI_API_KEY', 'SYNTHETIC-UNIT-TEST')
    monkeypatch.setenv('PDF_TRANSLATION_THINKING', 'enabled')
    monkeypatch.setattr(sys, 'argv', ['pdf2zh', '--openai', '--openai-model', 'glm-5.3-flash',
        '--openai-base-url', f'http://127.0.0.1:{server.server_address[1]}/v1',
        '--openai-temperature', '0.7', '--openai-send-temprature',
        '--openai-reasoning-effort', 'low', '--openai-send-reasoning-effort',
        '--openai-enable-json-mode', '--ignore-cache'])
    try:
        settings = ConfigManager().initialize_config()
        translator = get_translator(settings)
        translator.do_llm_translate('Return a JSON object.', {'request_json_mode': True})
        assert calls
        assert all(c['reasoning_effort'] == 'low' and c['temperature'] == .7 for c in calls)
        assert calls[-1]['response_format'] == {'type': 'json_object'}
        assert calls[-1]['thinking'] == {'type': 'enabled'}
    finally:
        server.shutdown()
        server.server_close()


def test_unreviewed_heading_candidate_does_not_become_keep_instruction():
    rows = [{'source_term': 'COLLOIDAL PROPERTIES', 'action': 'decide', 'translation': ''},
            {'source_term': 'NASA', 'action': 'keep', 'translation': ''},
            {'source_term': 'Artificial intelligence', 'action': 'translate', 'translation': '人工智能'}]
    result = _compact_policy_items(rows, limit=2)
    assert result == ['- NASA', '- Artificial intelligence => 人工智能']


def _page():
    return NS(page_number=0, cropbox=NS(box=NS(x=0, y=0, x2=240, y2=240)),
              page_layout=[NS(class_name='formula')])


class Layout:
    def __init__(self, layout_id, name):
        self.id, self.name = layout_id, name


def _character(text, x, top):
    return NS(char_unicode=text, visual_bbox=NS(box=NS(x=x, x2=x+4, y=240-top-5, y2=240-top)))


def test_ocr_line_fragment_keeps_its_source_paragraph_and_order(tmp_path, monkeypatch):
    # 同一左栏段落中的中间一行即使被模型标为公式，也必须留在段内，不能排到全页尾。
    lines = [
        {'text': 'first line', 'paragraph': [1, 1], 'bbox_px': [10, 20, 100, 30]},
        {'text': 'last line', 'paragraph': [1, 1], 'bbox_px': [10, 50, 100, 60]},
        {'text': 'RIGHT HEADING', 'paragraph': [2, 1], 'bbox_px': [130, 20, 230, 30]},
        {'text': 'calcareous member', 'paragraph': [1, 1], 'bbox_px': [10, 35, 100, 45]},
    ]
    manifest = {'status': 'ok', 'reconstructed_source': {'sha256': 'bound-by-workflow'}, 'render_dpi': 72,
                'pages': [{'page': 1, 'kind': 'scanned', 'background': {'size_px': [240, 240]}, 'text_lines': lines}]}
    path = tmp_path/'ocr.json'
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv(ENV, json.dumps({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
    chars = [_character('R', 140, 22), _character('a', 15, 22),
             _character('c', 15, 37), _character('z', 15, 52)]
    page = _page()
    layouts = bind_ocr_layout(page, chars, Layout)
    assert [c.char_unicode for c in chars] == ['a', 'c', 'z', 'R']
    assert len({x.id for x in layouts[:3]}) == 1
    assert layouts[-1].name == 'title' and layouts[-1].id != layouts[0].id
    assert page.page_layout[0].class_name == 'plain text'
    path.write_text('{}')
    with pytest.raises(ValueError, match='ocr_layout_manifest_changed'):
        bind_ocr_layout(page, chars, Layout)


def test_native_page_without_bound_manifest_is_unchanged(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    page = _page()
    assert bind_ocr_layout(page, [], Layout) is None
    assert page.page_layout[0].class_name == 'formula'


def test_mixed_native_page_does_not_override_formula_layout(tmp_path, monkeypatch):
    path = tmp_path/'mixed.json'
    path.write_text(json.dumps({'status': 'ok', 'reconstructed_source': {'sha256': 'bound'},
                               'pages': [{'page': 1, 'kind': 'native'}]}))
    monkeypatch.setenv(ENV, json.dumps({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
    page = _page()
    assert bind_ocr_layout(page, [], Layout) is None
    assert page.page_layout[0].class_name == 'formula'


def test_wrapped_quote_fragment_joins_only_with_same_column_continuation():
    rows = [
        {'text': 'the ground is commonly littered with', 'paragraph': [1, 1], 'bbox_px': [10, 20, 100, 30]},
        {'text': '‘residual fragments of minerals', 'paragraph': [2, 1], 'bbox_px': [10, 35, 100, 45]},
        {'text': 'and other deposits.', 'paragraph': [3, 1], 'bbox_px': [10, 50, 100, 60]},
        {'text': 'new right column', 'paragraph': [4, 1], 'bbox_px': [130, 20, 230, 30]},
    ]
    actual = join_wrapped_ocr_groups(rows)
    assert [x['paragraph'] for x in actual] == [(1, 1), (1, 1), (1, 1), (4, 1)]
    assert rows[1]['paragraph'] == [2, 1]  # 原始 OCR 证据保持原样。
    rows[1]['bbox_px'] = [30, 35, 100, 45]  # 真正的新段缩进不能接回。
    assert join_wrapped_ocr_groups(rows)[1]['paragraph'] == (2, 1)
