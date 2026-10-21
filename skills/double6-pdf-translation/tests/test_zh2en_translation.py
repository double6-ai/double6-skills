"""PR #4：中译英（--target-language en，基线问题 F4）回归测试。

夹具来自许可明确的真实中文论文（arXiv:2512.18979 CC BY 4.0、arXiv:2601.14329 CC0 1.0，
见 tests/fixtures/zh2en/README.md）：逐字符几何与正文原文。测试直接调用真实的预检、
工作流、后端命令构造、提示词、渲染残留检查与 babeldoc 函数，不依赖模型、网络或字体下载。
英译中（默认 zh）路径的命令行与行为必须逐字不变。
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'vendor/babeldoc'))
FIXTURES = SKILL / 'tests/fixtures/zh2en'
SAMPLE = json.loads((FIXTURES / 'zh_text_samples.json').read_text(encoding='utf-8'))
CHARS = json.loads((FIXTURES / 'arxiv2512.18979_p5_chars.json').read_text(encoding='utf-8'))
JUSTIFIED = json.loads((FIXTURES / 'arxiv2510.26803_p3_chars.json').read_text(encoding='utf-8'))['justified_lines']
ZH, EN = SAMPLE['zh'], SAMPLE['en']

from pdf_input_preflight import inspect_pdf  # noqa: E402
from render_residue_check import check_render_residue  # noqa: E402
from babeldoc.format.pdf.document_il import il_version_1 as il  # noqa: E402


def make_pdf(path, pages):
    """pages: [(text, cjk)]；用真实中文正文生成带文字层的 PDF。"""
    doc = fitz.open()
    for text, cjk in pages:
        page = doc.new_page()
        rect = fitz.Rect(50, 50, 545, 790)
        if cjk:
            page.insert_textbox(rect, text, fontname='china-s', fontsize=10)
        else:
            page.insert_textbox(rect, text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def codes(report):
    return {f['code'] for f in report['findings']}


# ---------- 输入预检：按目标语言判断方向 ----------

def test_preflight_allows_chinese_source_for_english_target(tmp_path):
    pdf = make_pdf(tmp_path / 'zh.pdf', [(ZH * 2, True)] * 2)
    report = inspect_pdf(pdf, target_language='en')
    assert report['source_language']['language'] == 'zh'
    assert 'source_language_matches_target' not in codes(report)
    assert report['status'] != 'blocked'


def test_preflight_still_blocks_same_language_in_both_directions(tmp_path):
    zh_pdf = make_pdf(tmp_path / 'zh.pdf', [(ZH * 2, True)])
    en_pdf = make_pdf(tmp_path / 'en.pdf', [(EN * 2, False)])
    zh_to_zh = inspect_pdf(zh_pdf, target_language='zh')
    en_to_en = inspect_pdf(en_pdf, target_language='en')
    assert zh_to_zh['status'] == en_to_en['status'] == 'blocked'
    assert 'source_language_matches_target' in codes(zh_to_zh) and 'source_language_matches_target' in codes(en_to_en)
    message = next(f['message'] for f in en_to_en['findings'] if f['code'] == 'source_language_matches_target')
    assert '英文' in message and '只支持英译中' not in message
    assert inspect_pdf(en_pdf, target_language='zh')['status'] != 'blocked'


def test_preflight_rejects_unsupported_target_language(tmp_path):
    report = inspect_pdf(make_pdf(tmp_path / 'zh.pdf', [(ZH, True)]), target_language='fr')
    assert report['status'] == 'blocked' and 'target_language_unsupported' in codes(report)


# ---------- 工作流入口：--target-language 透传，英译中命令行不变 ----------

def _workflow_candidate(tmp_path, monkeypatch, capsys, pdf, extra):
    import paper_translation_workflow as wf
    import bounded_execution
    seen = {}

    def fake_run_bounded(command, **kwargs):
        if kwargs.get('operation') == 'input-preflight':  # 预检走真实有界子进程
            return bounded_execution.run_bounded(command, **kwargs)
        seen['command'] = command
        out = Path(command[command.index('--output-dir') + 1])
        out.mkdir(parents=True)
        mono = out / 'in.no_watermark.en.mono.pdf'
        make_pdf(mono, [(EN, False)])
        (out / 'comprehensive_quality.json').write_text(json.dumps({'status': 'warn', 'issues': []}))
        (out / 'render_manifest.json').write_text(json.dumps({
            'quality_status': 'warn', 'outputs': {'translated_pdf': str(mono), 'mono_pdf': str(mono)}}))
        return {'status': 'succeeded', 'command': {'stdout_summary': {'excerpt': ''}}}

    monkeypatch.setattr(wf, 'run_bounded', fake_run_bounded)
    monkeypatch.setattr(wf, 'validate_freeze', lambda *a, **k: [1])
    monkeypatch.setattr(wf, 'doctor', lambda *a, **k: {'blockers': [], 'latex_ready': True})
    (tmp_path / 'FREEZE.json').write_text(json.dumps({'resource_contract': {
        'task_rss_bytes': 3 * 1024 ** 3, 'per_job_seconds': 120, 'concurrency': 1}}))
    code = wf.main(['candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'),
                    '--freeze', str(tmp_path / 'FREEZE.json'), '--route', 'digital_pdf', '--model', 'm',
                    '--base-url', 'http://127.0.0.1:9/v1', '--lock-path', str(tmp_path / 'wf.lock'), *extra])
    return code, json.loads(capsys.readouterr().out), seen.get('command')


def test_workflow_candidate_zh_to_en_passes_preflight_and_forwards_target(tmp_path, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / 'in.pdf', [(ZH * 2, True)])
    code, result, command = _workflow_candidate(tmp_path, monkeypatch, capsys, pdf, ['--target-language', 'en'])
    assert code == 0, result
    assert command is not None and command[command.index('--target-language') + 1] == 'en'
    receipt = json.loads((tmp_path / 'rc/input-preflight/input_preflight_report.json').read_text())
    assert receipt['target_language'] == 'en' and receipt['status'] != 'blocked'


def test_workflow_candidate_default_command_unchanged(tmp_path, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / 'in.pdf', [(EN * 2, False)])
    code, result, command = _workflow_candidate(tmp_path, monkeypatch, capsys, pdf, [])
    assert code == 0, result
    assert '--target-language' not in command and '--lang-in' not in command


def test_workflow_candidate_zh_source_default_target_still_exits_2(tmp_path, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / 'in.pdf', [(ZH * 2, True)])
    code, result, command = _workflow_candidate(tmp_path, monkeypatch, capsys, pdf, [])
    assert code == 2 and command is None


# ---------- 后端命令与提示词 ----------

def _backend_args(tmp_path, *argv):
    from pdf_translation_cli import build_parser
    return build_parser().parse_args([str(tmp_path / 'in.pdf'), '--output-dir', str(tmp_path / 'out'), '--model', 'm',
                                '--base-url', 'http://127.0.0.1:9/v1', *argv])


def test_pdf2zh_command_language_flags(tmp_path):
    from pdf_translation_commands import build_pdf2zh_command
    default = build_pdf2zh_command(_backend_args(tmp_path), tmp_path / 'out')
    zh2en = build_pdf2zh_command(_backend_args(tmp_path, '--target-language', 'en'), tmp_path / 'out')
    assert default[default.index('--lang-out') + 1] == 'zh' and '--lang-in' not in default
    assert zh2en[zh2en.index('--lang-in') + 1] == 'zh' and zh2en[zh2en.index('--lang-out') + 1] == 'en'
    rest = lambda cmd: [x for x in cmd if x not in {'--lang-in', '--lang-out', 'zh', 'en'}]  # noqa: E731
    assert rest(default) == rest(zh2en)
    with pytest.raises(SystemExit):
        _backend_args(tmp_path, '--target-language', 'fr')


def test_system_prompt_follows_target_and_keeps_custom_prompt():
    import run_pdf_translation_context as ctx
    assert ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'zh') == ctx.DEFAULT_SYSTEM_PROMPT
    en_prompt = ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'en')
    assert 'Chinese' in en_prompt and 'into fluent, natural academic English' in en_prompt
    assert ctx.resolve_system_prompt('custom prompt', 'en') == 'custom prompt'


def test_backend_prompt_drops_en_to_zh_glossary_for_english_target(tmp_path):
    from pdf_translation_commands import build_backend_system_prompt
    (tmp_path / 'term_policy.json').write_text(json.dumps({'terms': [
        {'source': 'AI Index', 'translation': '人工智能指数', 'status': 'active'},
        {'source': '玻色子', 'translation': 'boson', 'status': 'active'}]}, ensure_ascii=False), encoding='utf-8')
    zh = build_backend_system_prompt('BASE', tmp_path)
    en = build_backend_system_prompt('BASE', tmp_path, target_language='en')
    assert '人工智能指数' in zh and 'Translate ordinary English prose completely' in zh
    assert '人工智能指数' not in en and 'boson' in en
    assert 'Translate all Chinese prose completely into English' in en


# ---------- 渲染残留检查：中译英查中文残留 ----------

def test_chinese_residue_flags_untranslated_and_partial_pages(tmp_path):
    source = make_pdf(tmp_path / 's.pdf', [(ZH * 2, True), (ZH * 2, True)])
    same = check_render_residue(source, source, target_language='en')
    assert same['check'] == 'render_chinese_residue' and same['severity'] == 'high' and same['high_pages'] == [1, 2]
    assert all(p['verbatim_source_lines'] > 0 for p in same['pages'])
    partial = check_render_residue(source, make_pdf(tmp_path / 'p.pdf', [(EN * 2, False), (ZH * 2, True)]),
                                   target_language='en')
    assert partial['severity'] == 'high' and partial['high_pages'] == [2]
    done = check_render_residue(source, make_pdf(tmp_path / 't.pdf', [(EN * 2, False)] * 2), target_language='en')
    assert done['severity'] == 'ok' and done['overall_residue_ratio'] == 0 and not done['quality_fail']


def test_render_residue_gate_uses_target_language(tmp_path):
    import qa_pipeline
    source = make_pdf(tmp_path / 's.pdf', [(ZH * 2, True)])
    (tmp_path / 'out').mkdir()
    residue = qa_pipeline.render_residue_gate(source, source, tmp_path / 'out', target_language='en')
    assert residue['check'] == 'render_chinese_residue' and residue['severity'] == 'high'
    assert '中文残留' in qa_pipeline.render_residue_summary(residue)
    saved = json.loads((tmp_path / 'out/render_residue_check.json').read_text())
    assert saved['check'] == 'render_chinese_residue'


# ---------- babeldoc：中文源文抽取不在汉字间补空格 ----------

def _chars(rows):
    out = []
    for serial, (u, x, y, x2, y2) in enumerate(rows):
        out.append(il.PdfCharacter(
            pdf_style=il.PdfStyle(font_id='F1', font_size=10.5, graphic_state=il.GraphicState()),
            box=il.Box(x=x, y=y, x2=x2, y2=y2), visual_bbox=il.VisualBbox(box=il.Box(x=x, y=y, x2=x2, y2=y2)),
            vertical=False, scale=1.0, pdf_character_id=serial, char_unicode=u))
    return out


def test_justified_chinese_prose_extracts_without_inter_character_spaces():
    from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
    rows = CHARS['prose_lines'][0] + CHARS['prose_lines'][1]  # 两行两端对齐正文（含 p<0.001、Tukey HSD）
    text = get_char_unicode_string(_chars(rows))
    assert '显示不同研究领域论文的新颖性存在显著的统计学差异' in text
    assert '为进一步分析各组间差异,采用 Tukey' in text  # 抽取串经 NFKC 规范化，中英交界保留空格
    assert 'Tukey HSD' in text  # 拉丁词之间的真实空格保留


@pytest.mark.parametrize('index,expected', [(0, '所示。忽略耦合的指向性参考值为'), (1, '中URA 所在的平面）的')])
def test_letter_spaced_chinese_lines_get_no_dummy_spaces(index, expected):
    # 真实两端对齐/字距调整行：原规则按间距中位数补空格，会得到“所 示 。忽 略 耦 合的”，
    # 中译英请求与缓存键都被污染。
    import unicodedata
    from babeldoc.format.pdf.document_il.utils.layout_helper import _add_space_dummy_chars_to_list, get_char_unicode_string
    chars = _chars(JUSTIFIED[index])
    _add_space_dummy_chars_to_list(chars)
    assert ''.join(c.char_unicode for c in chars) == expected
    assert get_char_unicode_string(_chars(JUSTIFIED[index])) == unicodedata.normalize('NFKC', expected)


def test_table_cells_keep_their_separating_spaces():
    from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
    header = [c for cell in CHARS['table_rows'][:7] for c in cell]
    row = [c for cell in CHARS['table_rows'][7:16] for c in cell]
    # 单元格内不拆字；单元格间按 babeldoc 原有间距规则补空格（窄间隔是否补空格沿用原规则，不在此改变）。
    assert get_char_unicode_string(_chars(header)).startswith('研究领域 样本量 均值 标准差')
    assert get_char_unicode_string(_chars(row)).startswith('物理科学 8509 ')


# ---------- babeldoc：中文短词照常翻译，非中文段落保留原字形 ----------

def test_short_chinese_labels_bypass_min_text_length_only_for_zh_to_en():
    from babeldoc.format.pdf.document_il.midend.il_translator import passes_min_text_length
    paragraph = NS(layout_label='compact_label', unicode='样本量')
    zh2en = NS(lang_in='zh', lang_out='en', min_text_length=5)
    en2zh = NS(lang_in='en', lang_out='zh', min_text_length=5)
    assert passes_min_text_length(paragraph, '样本量', zh2en)
    assert not passes_min_text_length(paragraph, '样本量', en2zh)
    assert not passes_min_text_length(NS(layout_label=None, unicode='(1)'), '(1)', zh2en)
    assert passes_min_text_length(NS(layout_label=None, unicode='x'), 'long enough text', en2zh)


def test_chinese_compact_labels_are_released_for_english_target():
    from babeldoc.format.pdf.document_il.midend.table_figure_text import release_natural_compact_labels
    header = CHARS['table_rows'][:2]  # 研究领域、样本量
    paragraphs = []
    for cell in header:
        chars = _chars(cell)
        box = il.Box(x=min(c.box.x for c in chars), y=min(c.box.y for c in chars),
                     x2=max(c.box.x2 for c in chars), y2=max(c.box.y2 for c in chars))
        paragraphs.append(il.PdfParagraph(box=box, layout_label='compact_label', unicode=''.join(c.char_unicode for c in chars),
                                          pdf_paragraph_composition=[il.PdfParagraphComposition(pdf_line=il.PdfLine(pdf_character=chars))]))
    page = il.Page(page_number=0, cropbox=il.Cropbox(box=il.Box(x=0, y=0, x2=595, y2=842)))

    def finder(lang_in, lang_out):
        return NS(translation_config=NS(lang_in=lang_in, lang_out=lang_out),
                  _paragraph_lines=lambda p: [c.pdf_line for c in p.pdf_paragraph_composition if c.pdf_line])

    for p in paragraphs:
        p.layout_label = 'compact_label'
    prior = {id(p): 'plain text' for p in paragraphs}
    assert release_natural_compact_labels(finder('en', 'zh'), page, paragraphs, prior) == []
    assert all(p.layout_label == 'compact_label' for p in paragraphs)
    released = release_natural_compact_labels(finder('zh', 'en'), page, paragraphs, prior)
    assert released == ['研究领域', '样本量'] and all(p.layout_label == 'plain text' for p in paragraphs)


# ---------- babeldoc 排版：拉丁目标语言按整词宽度断行 ----------

def test_english_word_break_extent_counts_word_once_for_latin_target():
    from babeldoc.format.pdf.document_il.midend.typesetting import english_word_break_extent
    # 'context' 剩余宽度 30（已含首字母 c=5）：行内剩 32 时整词放得下，不应断成 c|ontext。
    assert english_word_break_extent(False, 5.0, 30.0) == 30.0
    # CJK 目标语言（英译中）保持原式，逐像素不变。
    assert english_word_break_extent(True, 5.0, 30.0) == 35.0
    assert english_word_break_extent(False, 5.0, 0.0) == 5.0
