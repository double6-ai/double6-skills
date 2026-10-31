# SPDX-License-Identifier: AGPL-3.0-only
"""终局双语件方向按实际源语言，ja/ko 源不再标"英文原文"。

- bilingual_direction 的方向对扩展（ja/ko→zh）与标签/文件名中缀。
- _resolved_document_source_language 的依据链：页级 render_manifest 多数
  > 声明环境变量 > 输入文字检测 > 旧默认（目标 zh 视源 en，既有 en/zh 流程不变）。
"""
import json
from pathlib import Path
import sys

import fitz

S = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(S / 'scripts')]
import build_bilingual_pdf  # noqa: E402
import translation_continuation as continuation  # noqa: E402


def test_bilingual_direction_supports_ja_ko_source_to_zh():
    ja = build_bilingual_pdf.bilingual_direction('ja', 'zh', basis='resolved_document_source_language')
    assert ja['layout'] == 'ja_left_zh_right' and ja['name_infix'] == 'ja-left.zh-right'
    assert ja['left_label'] == '日文原文' and ja['right_label'] == '中文译文'
    assert ja['left_language'] == 'ja' and ja['right_language'] == 'zh'
    ko = build_bilingual_pdf.bilingual_direction('ko', 'zh', basis='resolved_document_source_language')
    assert ko['name_infix'] == 'ko-left.zh-right' and ko['left_label'] == '韩文原文'
    # 既有方向与"未知方向走中性标注"行为不变
    assert build_bilingual_pdf.bilingual_direction('en', 'zh')['layout'] == 'en_left_zh_right'
    assert build_bilingual_pdf.bilingual_direction('zh', 'en')['name_infix'] == 'zh-left.en-right'
    unknown = build_bilingual_pdf.bilingual_direction('ja', 'en')
    assert unknown['name_infix'] == build_bilingual_pdf.NEUTRAL_NAME_INFIX


def test_name_infix_for_rebuilds_japanese_infix_from_manifest():
    manifest = {'left_language': 'ja', 'right_language': 'zh'}
    assert build_bilingual_pdf.name_infix_for(manifest) == 'ja-left.zh-right'
    assert build_bilingual_pdf.name_infix_for({'left_language': None, 'right_language': None}) \
        == build_bilingual_pdf.NEUTRAL_NAME_INFIX


def _document(tmp_path: Path, text: str):
    path = tmp_path / 'source.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=500)
        # china-s（Droid Sans Fallback）带假名字形；默认 helv 写假名只会得到空白页。
        page.insert_font(fontname='cjk', fontbuffer=bytes(fitz.Font('china-s').buffer))
        page.insert_textbox(fitz.Rect(30, 40, 370, 460), text, fontsize=12, fontname='cjk')
        doc.save(path)
    return fitz.open(path)


def _page_row(tmp_path: Path, name: str, source_language: str):
    """造一页 target 产物与其 render_manifest（source_language 为渲染层解析结果）。"""
    folder = tmp_path / name
    folder.mkdir()
    target = folder / 'page.zh.mono.pdf'
    with fitz.open() as doc:
        doc.new_page(width=100, height=100)
        doc.save(target)
    (folder / 'render_manifest.json').write_text(json.dumps({'source_language': source_language}),
                                                 encoding='utf-8')
    return {'target': continuation.reference(target)}


def test_document_source_language_prefers_page_manifests(tmp_path):
    rows = [_page_row(tmp_path, 'p1', 'ja')]
    with _document(tmp_path, 'This paragraph contains reliable source text for translation and ordinary reading. ' * 8) as document:
        language, basis, detail = continuation._resolved_document_source_language(document, rows, 'zh')
    assert (language, basis) == ('ja', 'page_manifests') and detail['votes'] == {'ja': 1}


def test_document_source_language_majority_over_minority(tmp_path):
    rows = [_page_row(tmp_path, name, language) for name, language in (('p1', 'ja'), ('p2', 'ja'), ('p3', 'en'))]
    with _document(tmp_path, 'plain english body text without manifests here for detection fallback') as document:
        language, basis, _ = continuation._resolved_document_source_language(document, rows, 'zh')
    assert (language, basis) == ('ja', 'page_manifests')


def test_document_source_language_render_manifest_then_env_then_default(tmp_path, monkeypatch):
    rows = [_page_row(tmp_path, 'render', 'ja')]
    monkeypatch.delenv('PAPER_TRANSLATION_SOURCE_LANGUAGE', raising=False)
    with _document(tmp_path, 'This paragraph contains reliable source text for translation and ordinary reading. ' * 8) as document:
        language, basis, _ = continuation._resolved_document_source_language(document, rows, 'zh')
    assert (language, basis) == ('ja', 'page_manifests')
        # 无任何清单 → 声明环境变量
    monkeypatch.setenv('PAPER_TRANSLATION_SOURCE_LANGUAGE', 'ko')
    with _document(tmp_path, 'This paragraph contains reliable source text for translation and ordinary reading. ' * 8) as document:
        language, basis, _ = continuation._resolved_document_source_language(document, rows[:0], 'zh')
    assert (language, basis) == ('ko', 'declared_env')
        # 无声明 → 输入检测（假名主体）
    monkeypatch.delenv('PAPER_TRANSLATION_SOURCE_LANGUAGE', raising=False)
    ja_text = ('本研究では、提案手法と既存のファインチューニングを比較した。' * 6)
    with _document(tmp_path, ja_text) as document:
        language, basis, _ = continuation._resolved_document_source_language(document, [], 'zh')
    assert (language, basis) == ('ja', 'input_detection')
        # 检测不出（无文字层空白页）→ 旧默认：目标 zh 视源 en
    blank = tmp_path / 'blank.pdf'
    with fitz.open() as doc:
        doc.new_page(width=400, height=500)
        doc.save(blank)
    with fitz.open(blank) as document:
        language, basis, _ = continuation._resolved_document_source_language(document, [], 'zh')
    assert (language, basis) == ('en', 'target_default')
