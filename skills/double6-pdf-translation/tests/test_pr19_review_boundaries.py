"""PR #19 评审第 1 轮反例（移植自评审的 test_review_boundaries.py）与第 5 项补充用例。

固定模型响应，无网络或真实模型调用。前 6 个用例与评审原文断言一致，只把证据 JSON 写到 tmp_path、
并改为从本仓库 tests/ 导入；第 5 项（行内对象公式：Form XObject 行内变量、矢量路径公式字形）
用 PyMuPDF 按显式坐标生成带原生文字层的 PDF。
"""
import json
import re
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_zh2en_translation as zh  # noqa: E402
import test_table_figure_text as table  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402


def save(tmp_path, name, data):
    (tmp_path / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + '\n')


# ---------- 评审发现一：Qwen CLI 适配器的目标语言 ----------

def test_qwen_english_response_must_not_be_rewritten_to_chinese(monkeypatch, tmp_path):
    import qwen_pdf2zh_cli_translator as q
    from run_pdf_translation_context import DEFAULT_SYSTEM_PROMPT_EN
    from pdf_translation_paths import should_use_qwen_cli_adapter
    from pdf_translation_commands import build_pdf2zh_command
    args = zh._backend_args(tmp_path, '--target-language', 'en', '--model', 'qwen/qwen3.6-35b-a3b')
    args.base_url = 'http://127.0.0.1:9/v1'
    args.custom_system_prompt = DEFAULT_SYSTEM_PROMPT_EN
    assert should_use_qwen_cli_adapter(args)
    command = build_pdf2zh_command(args, tmp_path)
    adapter = q.build_parser().parse_args(shlex.split(command[command.index('--clitranslator-command') + 1])[2:])
    text = '我们与 Stanford University 合作开展研究。'
    english = 'We collaborate with Stanford University on this research.'
    monkeypatch.setattr(q, 'request_translation', lambda *a: english)
    actual = q.translate(text, adapter)
    save(tmp_path, 'QWEN_WRONG_LANGUAGE', {'source': text, 'fixed_model_response': english, 'actual_adapter_output': actual})
    assert actual == english, 'Correct English output is changed back into Chinese by the active adapter'


def test_qwen_retry_must_keep_english_target(monkeypatch, tmp_path):
    import qwen_pdf2zh_cli_translator as q
    from run_pdf_translation_context import DEFAULT_SYSTEM_PROMPT_EN
    args = q.build_parser().parse_args(['--base-url', 'http://127.0.0.1:9/v1', '--model', 'qwen', '--system-prompt', DEFAULT_SYSTEM_PROMPT_EN])
    calls = []

    def request(user, system, args):
        calls.append({'user': user, 'system': system})
        return 'See the source.' if len(calls) == 1 else 'See https://example.org/paper .'

    monkeypatch.setattr(q, 'request_translation', request)
    q.translate('参见 https://example.org/paper 。', args)
    save(tmp_path, 'QWEN_RETRY_PROMPT', {'calls': calls})
    assert len(calls) == 2
    assert 'into Simplified Chinese' not in calls[1]['user']


# ---------- 评审发现二：短中文正文原样输出 ----------

def short_source(tmp_path):
    text = '本文研究翻译系统在数学论文中的可靠性并分析实验结果。' * 2
    assert 40 <= len(re.findall(r'[\u4e00-\u9fff]', text)) < 100
    return text, zh.make_pdf(tmp_path / 'short.pdf', [(text, True)])


def test_unchanged_chinese_body_must_be_rejected(tmp_path):
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator, ParagraphTranslateTracker, classify_same_as_input_result
    text, pdf = short_source(tmp_path)
    style = il.PdfStyle(font_id='F1', font_size=10, graphic_state=il.GraphicState())
    para = il.PdfParagraph(unicode=text, layout_label='plain text', pdf_style=style, pdf_paragraph_composition=[])
    tracker = ParagraphTranslateTracker()
    tracker.new_llm_translate_tracker()
    translator = ILTranslator.__new__(ILTranslator)
    translator.translation_config = NS(lang_in='zh', lang_out='en')
    applied = translator.post_translate_paragraph(para, tracker, NS(unicode=text, placeholders=[], base_style=style), text)
    save(tmp_path, 'UNCHANGED_CHINESE_WRITEBACK', {'source': text, 'classification': classify_same_as_input_result(text),
                                                  'applied': applied, 'writeback_status': tracker.writeback_status})
    assert applied is False, 'Chinese ordinary prose is classified as protected passthrough and written unchanged'


def test_untranslated_short_pdf_must_fail_residue_gate(tmp_path):
    from pdf_input_preflight import inspect_pdf
    from render_residue_check import check_render_residue
    text, pdf = short_source(tmp_path)
    pre = inspect_pdf(pdf, target_language='en', require_digital=True)
    assert pre['status'] != 'blocked' and pre['source_language']['language'] == 'zh'
    result = check_render_residue(pdf, pdf, target_language='en')
    save(tmp_path, 'UNCHANGED_SHORT_PDF', {'preflight': pre, 'residue': result})
    assert result['quality_fail'] and result['severity'] == 'high', 'Entire accepted source survives unchanged but residue gate is not_evaluated/ok'


# ---------- 评审发现三：英文扩框越过矢量表格线 ----------

def test_latin_expansion_must_respect_vector_cell_border(tmp_path):
    stage = table._typesetter()
    stage.is_cjk = False
    box = il.Box(x=50, y=100, x2=90, y2=112)
    para = il.PdfParagraph(box=box, layout_label='table_cell', first_line_indent=False)
    border = il.PdfCurve(box=il.Box(x=100, y=90, x2=100, y2=130))
    page = il.Page(page_number=1, cropbox=il.Cropbox(box=il.Box(x=0, y=0, x2=300, y2=300)), pdf_paragraph=[para],
                   pdf_character=[], pdf_figure=[], pdf_curve=[border], pdf_form=[])
    expanded = stage._latin_target_expanded_box(box, page, 0)
    assert expanded is not None
    scale, units = stage._find_optimal_scale_and_layout(para, page, table._units('Sample count', 10), apply_layout=True)
    fit = bool(units)
    crossing = [u.try_get_unicode() for u in units if u.box.x < 100 < u.box.x2]
    save(tmp_path, 'VECTOR_BORDER_EXPANSION', {'expanded_x2': expanded.x2, 'fit': fit, 'scale': scale, 'crossing_glyphs': crossing})
    assert not (fit and crossing), 'An accepted English layout crosses a source table border'


# ---------- 评审发现四：LaTeX 路线不支持英文目标 ----------

def test_latex_route_must_reject_unsupported_english_target(monkeypatch, tmp_path, capsys):
    import paper_translation_workflow as wf
    text, pdf = short_source(tmp_path)
    out = tmp_path / 'out'
    receipts = tmp_path / 'receipts'
    calls = []
    freeze = tmp_path / 'FREEZE.json'
    freeze.write_text(json.dumps({'resource_contract': {'task_rss_bytes': 3 * 1024 ** 3, 'per_job_seconds': 120, 'concurrency': 1},
                                  'latex_source': {'path': str(tmp_path / 'source.tex')}, 'model_fingerprint_ref': {'path': str(tmp_path / 'model.json')}}))
    monkeypatch.setattr(wf, 'validate_freeze', lambda *a, **k: [1])
    monkeypatch.setattr(wf, 'doctor', lambda *a, **k: {'blockers': [], 'latex_ready': True})

    def fake_job(args, command, operation):
        calls.append({'operation': operation, 'command': command})
        out.mkdir(exist_ok=True)
        if operation == 'prepare':
            (out / 'latex_plan.json').write_text(json.dumps({'units': [{'id': 'u1'}]}))
        if operation == 'compile':
            (out / 'latex_result.json').write_text(json.dumps({'status': 'candidate'}))
        return {'status': 'succeeded'}

    monkeypatch.setattr(wf, 'run_job', fake_job)
    code = wf.main(['candidate', '--input', str(pdf), '--output', str(out), '--receipts', str(receipts), '--freeze', str(freeze),
                    '--route', 'latex_verified', '--model', 'm', '--base-url', 'http://127.0.0.1:9/v1', '--target-language', 'en',
                    '--lock-path', str(tmp_path / 'lock')])
    value = json.loads(capsys.readouterr().out)
    save(tmp_path, 'LATEX_WRONG_DIRECTION', {'exit_code': code, 'result': value, 'stages': calls})
    assert code == 2 and calls == [], 'Unsupported route executes a hard-coded Simplified Chinese translator'
    assert value.get('error_code') == 'target_language_route_unsupported'


# ---------- 第 5 项：行内对象公式（Form XObject 行内变量、矢量路径字形）必须可靠阻断 ----------

ZH_LINE_A = '考虑一个由'
ZH_LINE_B = '个单极化全向天线组成的阵列，天线沿两个方向等间距排列。'
ZH_FILL = '本文给出了阵列远场指向性的数学框架，并推导了解析表达式，系统分析了各种因素对指向性的影响。' * 3


def _inline_page(doc, *, vector=False, xobject=False, figure_xobject=False):
    """一行中文正文中间留出空隙，按需在空隙中放 Form XObject 文字或矢量字形；下方是普通中文正文。"""
    page = doc.new_page()
    y = 120
    page.insert_text((72, y), ZH_LINE_A, fontname='china-s', fontsize=10.5)
    gap_x = 72 + 10.5 * len(ZH_LINE_A) + 4
    page.insert_text((gap_x + 34, y), ZH_LINE_B, fontname='china-s', fontsize=10.5)
    page.insert_textbox(fitz.Rect(72, 140, 520, 400), ZH_FILL, fontname='china-s', fontsize=10.5)
    if xobject or figure_xobject:
        src = fitz.open()
        sp = src.new_page(width=40, height=16)
        sp.insert_text((2, 12), 'M×N' if xobject else 'f(x)', fontname='tiro', fontsize=11)
        rect = fitz.Rect(gap_x, y - 12, gap_x + 30, y + 3) if xobject else fitz.Rect(200, 600, 320, 650)
        page.show_pdf_page(rect, src, 0)
    if vector:
        for k in range(4):  # 4 个填充字形轮廓（MathJax/网页打印公式常见形态）
            x0 = gap_x + 2 + 7 * k
            page.draw_polyline([(x0, y), (x0 + 3, y - 8), (x0 + 6, y), (x0, y)], color=None, fill=(0, 0, 0))
    return page


def _pdf(tmp_path, name, **kw):
    doc = fitz.open()
    _inline_page(doc, **kw)
    path = tmp_path / name
    doc.save(path)
    return path


def _codes(report):
    return {f['code'] for f in report['findings']}


def test_preflight_blocks_inline_form_xobject_text_for_english_target(tmp_path):
    from pdf_input_preflight import inspect_pdf
    pdf = _pdf(tmp_path, 'xobj.pdf', xobject=True)
    report = inspect_pdf(pdf, target_language='en', require_digital=True)
    save(tmp_path, 'INLINE_XOBJECT', report)
    assert report['status'] == 'blocked' and 'zh2en_inline_object_math_unsupported' in _codes(report)
    finding = next(f for f in report['findings'] if f['code'] == 'zh2en_inline_object_math_unsupported')
    assert finding['details']['pages'][0]['page'] == 1 and finding['details']['pages'][0]['xobject_text_glyphs'] >= 3


def test_preflight_blocks_inline_vector_formula_glyphs_for_english_target(tmp_path):
    from pdf_input_preflight import inspect_pdf
    pdf = _pdf(tmp_path, 'vector.pdf', vector=True)
    report = inspect_pdf(pdf, target_language='en', require_digital=True)
    assert report['status'] == 'blocked' and 'zh2en_inline_object_math_unsupported' in _codes(report)
    finding = next(f for f in report['findings'] if f['code'] == 'zh2en_inline_object_math_unsupported')
    assert finding['details']['pages'][0]['vector_glyphs'] >= 3


def test_preflight_inline_object_rule_is_structural_and_direction_scoped(tmp_path):
    from pdf_input_preflight import inspect_pdf
    # 普通中文正文、位于正文行之外的图形 XObject：不阻断
    plain = inspect_pdf(_pdf(tmp_path, 'plain.pdf'), target_language='en', require_digital=True)
    figure = inspect_pdf(_pdf(tmp_path, 'figure.pdf', figure_xobject=True), target_language='en', require_digital=True)
    assert 'zh2en_inline_object_math_unsupported' not in _codes(plain) | _codes(figure)
    assert plain['status'] != 'blocked' and figure['status'] != 'blocked'
    # 只约束中译英：同一文件按英译中预检时照旧按“源文已是中文”处理，不出现新码
    en2zh = inspect_pdf(_pdf(tmp_path, 'xobj.pdf', xobject=True), target_language='zh', require_digital=True)
    assert 'zh2en_inline_object_math_unsupported' not in _codes(en2zh)


def test_workflow_blocks_inline_object_math_before_any_model_call(tmp_path, monkeypatch, capsys):
    pdf = _pdf(tmp_path, 'in.pdf', xobject=True)
    code, result, command = zh._workflow_candidate(tmp_path, monkeypatch, capsys, pdf, ['--target-language', 'en'])
    assert code == 2 and command is None
    assert result.get('error_code') == 'zh2en_inline_object_math_unsupported'


def test_retained_glyph_overlap_fails_closed(tmp_path):
    """输出侧兜底：源文保留字形与英文译文压叠达到阈值时判 high（退出码 3），不只记 medium。"""
    import render_residue_check as rrc
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), 'Consider a planar array of antennas along the axis', fontname='helv', fontsize=11)
    page.insert_text((72, 100), 'MNxzMNxzMNxzMN', fontname='tiro', fontsize=11)
    path = tmp_path / 'overlap.pdf'
    doc.save(path)
    source = zh.make_pdf(tmp_path / 's.pdf', [(zh.ZH * 2, True)])
    original = rrc.TRANSLATED_FONT_PATTERN
    try:
        rrc.TRANSLATED_FONT_PATTERN = re.compile('Helvetica')
        result = rrc.check_render_residue(source, path, target_language='en')
    finally:
        rrc.TRANSLATED_FONT_PATTERN = original
    assert result['retained_glyph_overlap_pages'] == [1]
    assert result['severity'] == 'high' and result['quality_fail']
