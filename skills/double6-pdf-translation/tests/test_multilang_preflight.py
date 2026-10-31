# SPDX-License-Identifier: AGPL-3.0-only
"""lane/d（T6 多语言第一阶段）：源语言检测 ja/ko 扩展与 ja→zh 预检放行。

detect_language 在无假名/谚文时必须与旧版 zh/en/mixed/unknown 判定完全一致；
日文（假名占比）与韩文（谚文主体）按书写系统区块识别；日文横排 PDF 以目标 zh
预检时不得再被误判成中文而遭 source_language_matches_target 拒绝。
"""
import sys
from pathlib import Path

import fitz
import pytest

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S / 'scripts'))

from pdf_input_preflight import detect_language, inspect_pdf  # noqa: E402

EN = ('Test-time training adapts model weights during inference so that the network can store '
      'long context in fast weights. We evaluate the approach on language modeling and view synthesis. ') * 6
ZH = '测试时训练在推理过程中更新模型权重，使网络能够把长上下文存入快速权重。我们在语言建模和新视角合成上评估该方法。' * 6
# 日文横排：汉字+假名混排、少量数字与拉丁缩写，学术摘要风格
JA = ('機械学習は、計算機上でデータからパターンを学習し、予測や判断を行う技術である。'
      '本研究では、新しいニューラルネットワークのアーキテクチャを提案し、既存手法と比較して'
      '精度が 12.5 パーセント向上することを示した。実験では 3 つの公開データセットを用い、'
      'GPU クラスタ上で大規模な訓練を行った。') * 4
# 韩文：谚文主体（现代韩文极少汉字）
KO = ('머신러닝은 컴퓨터가 데이터에서 패턴을 학습하여 예측과 판단을 수행하는 기술이다. '
      '본 연구에서는 새로운 신경망 아키텍처를 제안하고 기존 방법과 비교하여 정확도가 '
      '12.5 퍼센트 향상됨을 보였다. 실험에서는 3 개의 공개 데이터셋을 사용하였다.') * 4


def test_detect_language_zh_en_unchanged():
    assert detect_language(EN)['language'] == 'en'
    assert detect_language(ZH)['language'] == 'zh'
    assert detect_language(ZH[:60] + EN[:400])['language'] == 'mixed'
    assert detect_language('x')['language'] == 'unknown'


def test_detect_language_japanese_by_kana():
    result = detect_language(JA)
    assert result['language'] == 'ja'
    assert result['kana_chars'] > 0 and result['cjk_chars'] > 0
    assert result['method'] == 'script_block_counts'


def test_detect_language_korean_by_hangul():
    result = detect_language(KO)
    assert result['language'] == 'ko'
    assert result['hangul_chars'] > 0


def test_detect_language_chinese_with_short_ja_quote_stays_zh():
    """中文正文里的少量日文引文（假名占比 <10%）不得翻转判定。"""
    assert detect_language(ZH + '「テスト駆動開発」の実装例')['language'] == 'zh'


def test_detect_language_counts_exposed():
    result = detect_language(JA[:0] + EN)
    assert result['latin_words'] > 0 and result['kana_chars'] == 0 and result['hangul_chars'] == 0


def _make_pdf(path, text, fontname):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontname=fontname, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_inspect_pdf_japanese_to_chinese_not_blocked(tmp_path):
    """日文横排 PDF、目标 zh：语言判 ja，不再误判中文触发 source_language_matches_target。"""
    pdf = _make_pdf(tmp_path / 'ja.pdf', JA, 'japan')
    report = inspect_pdf(pdf, target_language='zh', require_digital=True)
    assert report['status'] == 'ok', report['findings']
    assert report['source_language']['language'] == 'ja'


def test_inspect_pdf_japanese_full_page_extractable(tmp_path):
    """生成的测试件文字层真实可抽取（防字体名退化成不可见字形的假通过）。"""
    pdf = _make_pdf(tmp_path / 'ja2.pdf', JA, 'japan')
    with fitz.open(pdf) as doc:
        text = doc[0].get_text()
    result = detect_language(text)
    assert result['kana_chars'] >= 40, text[:80]


def test_inspect_pdf_korean_detected(tmp_path):
    pdf = _make_pdf(tmp_path / 'ko.pdf', KO, 'korea')
    report = inspect_pdf(pdf, target_language='zh', require_digital=True)
    assert report['source_language']['language'] == 'ko'
    assert report['status'] == 'ok', report['findings']


def test_inspect_pdf_chinese_target_zh_still_blocked(tmp_path):
    """回归：中文源 + 目标 zh 仍被拒绝（既有行为不变）。"""
    pdf = _make_pdf(tmp_path / 'zh.pdf', ZH, 'china-s')
    report = inspect_pdf(pdf, target_language='zh', require_digital=True)
    assert report['status'] == 'blocked'
    assert report['error_code'] == 'source_language_matches_target'
