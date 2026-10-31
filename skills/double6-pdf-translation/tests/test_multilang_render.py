# SPDX-License-Identifier: AGPL-3.0-only
"""lane/d（T6 多语言第一阶段）：日译中的提示词分支、--lang-in 声明与假名残留门。

- resolve_system_prompt：目标 zh + 源 ja 换用日译中默认提示词；en 目标与自定义提示词不受影响。
- build_pdf2zh_command：源 ja 时显式 --lang-in ja；纯英译中命令行逐字不变。
- check_render_residue：source_language='ja' 走假名残留口径，整段未翻译判 high。
- resolve_input_source_language：环境变量声明优先，输入检测次之，失败回落 None。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S / 'scripts'))

import run_pdf_translation_context as ctx  # noqa: E402
from pdf_translation_commands import build_backend_system_prompt, build_pdf2zh_command  # noqa: E402
from pdf_translation_render import resolve_input_source_language  # noqa: E402
from render_residue_check import check_render_residue  # noqa: E402

JA = ('機械学習は、計算機上でデータからパターンを学習し、予測や判断を行う技術である。'
      '本研究では、新しいニューラルネットワークのアーキテクチャを提案し、既存手法と比較して'
      '精度が 12.5 パーセント向上することを示した。') * 4
ZH = '机器学习是一种让计算机从数据中学习模式并执行预测与判断的技术。本研究提出一种全新的神经网络架构，' \
     '与既有方法相比精度提高了 12.5 个百分点。' * 4


def test_resolve_system_prompt_ja_branch():
    assert ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'zh', 'ja') is ctx.DEFAULT_SYSTEM_PROMPT_JA2ZH
    assert ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'zh', None) is ctx.DEFAULT_SYSTEM_PROMPT
    assert ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'zh', 'en') is ctx.DEFAULT_SYSTEM_PROMPT
    assert ctx.resolve_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, 'en', 'ja') is ctx.DEFAULT_SYSTEM_PROMPT_EN
    assert ctx.resolve_system_prompt('自定义', 'zh', 'ja') == '自定义'


def test_backend_prompt_tail_source_aware(tmp_path):
    (tmp_path / 'term_policy.json').write_text(
        '{"terms": [{"source_term": "Transformer", "translation": "Transformer 架构", "active": true}]}',
        encoding='utf-8')
    zh_tail = build_backend_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, tmp_path, 'zh')
    ja_tail = build_backend_system_prompt(ctx.DEFAULT_SYSTEM_PROMPT, tmp_path, 'zh', source_language='ja')
    assert 'Translate ordinary English prose completely' in zh_tail
    assert 'do not copy Japanese Kanji words verbatim' in ja_tail


def _cmd_args(**overrides):
    base = dict(input_pdf='/tmp/x.pdf', output='/tmp/out', model='gpt', base_url='http://localhost:8000/v1',
                api_key=None, translator_mode='openai', pdf2zh_backend='vendored', pdf2zh_binary=None,
                target_language='zh', backend_debug_artifacts=False, ignore_translation_cache=False,
                source_cache_mode=None, openai_timeout=120, temperature=0.7,
                openai_send_reasoning_effort=False, openai_reasoning_effort='none',
                openai_json_mode=False, local_max_concurrency=None, custom_system_prompt='p',
                pdf_layout_profile='auto', dual=False, pages=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_pdf2zh_command_lang_in_ja(tmp_path):
    ja = build_pdf2zh_command(_cmd_args(input_pdf=str(tmp_path / 'x.pdf'), resolved_source_language='ja'),
                              tmp_path)
    assert ja[ja.index('--lang-in'):ja.index('--lang-in') + 4] == ['--lang-in', 'ja', '--lang-out', 'zh']
    # 纯英译中：不带 resolved_source_language 时保持既有命令行（无 --lang-in，pdf2zh 默认 en）
    en = build_pdf2zh_command(_cmd_args(input_pdf=str(tmp_path / 'x.pdf')), tmp_path)
    assert '--lang-in' not in en and '--lang-out' in en and en[en.index('--lang-out') + 1] == 'zh'
    # 中译英：显式 --lang-in zh（既有行为）
    zh2en = build_pdf2zh_command(_cmd_args(input_pdf=str(tmp_path / 'x.pdf'), target_language='en'), tmp_path)
    i = zh2en.index('--lang-in')
    assert zh2en[i:i + 4] == ['--lang-in', 'zh', '--lang-out', 'en']


def _make_pdf(path, text, fontname, pages=1):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontname=fontname, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_render_residue_japanese_gate(tmp_path):
    source = _make_pdf(tmp_path / 'ja.pdf', JA, 'japan')
    translated = _make_pdf(tmp_path / 'zh.pdf', ZH, 'china-s')
    untranslated = _make_pdf(tmp_path / 'ja_copy.pdf', JA, 'japan')
    ok = check_render_residue(source, translated, target_language='zh', source_language='ja')
    assert ok['check'] == 'render_japanese_residue'
    assert ok['severity'] == 'ok' and not ok['quality_fail']
    bad = check_render_residue(source, untranslated, target_language='zh', source_language='ja')
    assert bad['severity'] == 'high' and bad['quality_fail']
    # 缺省 source_language：沿用英文残留口径（行为不变）
    legacy = check_render_residue(source, translated, target_language='zh')
    assert legacy['check'] == 'render_english_residue'


def test_resolve_input_source_language(tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / 'ja.pdf', JA, 'japan')
    monkeypatch.delenv(ctx.SOURCE_LANGUAGE_ENV, raising=False)
    assert resolve_input_source_language(Path(pdf), 'zh') == 'ja'
    monkeypatch.setenv(ctx.SOURCE_LANGUAGE_ENV, 'en')  # 显式声明优先于检测
    assert resolve_input_source_language(Path(pdf), 'zh') == 'en'
    monkeypatch.setenv(ctx.SOURCE_LANGUAGE_ENV, 'ja')
    assert resolve_input_source_language(Path(pdf), 'en') is None  # en 目标不经此解析
    monkeypatch.delenv(ctx.SOURCE_LANGUAGE_ENV, raising=False)
    assert resolve_input_source_language(Path(tmp_path / 'missing.pdf'), 'zh') is None
