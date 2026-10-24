"""PR #25 第四项：文字 QA 按实际目标语言选择、双语产物名称/清单/标注与真实方向一致。

成对正负：中译英正确英文通过、带中文残留失败；英译中带英文残留失败、正确中文通过。
双语页序固定为“左源页、右译页”，只修名称与标注；方向未知时使用中性合同。
不依赖模型、网络或字体下载。
"""
import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

from check_translation_gates import check_render_manifest, collect_issues, resolve_qa_target_language  # noqa: E402
import build_bilingual_pdf  # noqa: E402
from pdf_translation_artifacts import build_standard_bilingual_output, mirror_latex_direct_bilingual_output  # noqa: E402

ZH = '本实验在多个数据集上评估模型性能并报告观察结果。我们进一步分析了不同设置下的误差来源。'
EN = ('The experiment evaluates model performance across multiple datasets and reports the observed results. '
      'We further analyse the sources of error under different settings.')
ZH_WITH_EN_RESIDUE = '本实验在多个数据集上评估模型性能。We further analyse the sources of error under different settings.'
EN_WITH_ZH_RESIDUE = 'The experiment evaluates model performance across multiple datasets. 我们进一步分析了不同设置下的误差来源。'


def titles(issues):
    return [i.title for i in issues]


def english_untranslated(issues):
    return [t for t in titles(issues) if '英文' in t and ('未翻译' in t or 'must_translate' in t)]


def chinese_untranslated(issues):
    return [t for t in titles(issues) if t == '疑似大段中文未翻译']


# ---------- 文字 QA：四个成对方向 ----------

def test_zh_to_en_correct_english_passes_residue_checks():
    issues = collect_issues(ZH, EN, [], manifest={'target_language': 'en', 'pages': []})
    assert not english_untranslated(issues) and not chinese_untranslated(issues), titles(issues)
    assert not [t for t in titles(issues) if '残留' in t], titles(issues)


def test_zh_to_en_chinese_residue_fails():
    issues = collect_issues(ZH, EN_WITH_ZH_RESIDUE, [], manifest={'target_language': 'en', 'pages': []})
    hit = [i for i in issues if i.title == '疑似大段中文未翻译']
    assert hit and hit[0].severity == 'medium' and hit[0].category == 'omission', titles(issues)
    assert '我们进一步分析了不同设置下的误差来源' in hit[0].detail
    assert not english_untranslated(issues)


def test_en_to_zh_english_residue_still_fails():
    for manifest in ({'target_language': 'zh', 'pages': []}, {'pages': []}):
        issues = collect_issues(EN, ZH_WITH_EN_RESIDUE, [], manifest=manifest)
        assert '疑似大段英文未翻译' in titles(issues), (manifest, titles(issues))
        assert not chinese_untranslated(issues)


def test_en_to_zh_correct_chinese_passes():
    issues = collect_issues(EN, ZH, [], manifest={'target_language': 'zh', 'pages': []})
    assert not english_untranslated(issues) and not chinese_untranslated(issues), titles(issues)


def test_target_from_render_manifest_or_argument():
    rm = {'target_language': 'en'}
    assert not english_untranslated(collect_issues(ZH, EN, [], manifest={'pages': []}, render_manifest=rm))
    assert not english_untranslated(collect_issues(ZH, EN, [], manifest={'pages': []}, target_language='en'))
    assert chinese_untranslated(collect_issues(ZH, EN_WITH_ZH_RESIDUE, [], manifest={'pages': []}, target_language='en'))


# ---------- 默认 / 未知 / 冲突方向合同 ----------

def test_unrecorded_direction_uses_documented_legacy_default():
    direction = resolve_qa_target_language(None, {}, {})
    assert direction == {'target_language': 'zh', 'basis': 'legacy_default_en_to_zh', 'conflict': [], 'unsupported': None}
    assert '疑似大段英文未翻译' in titles(collect_issues(EN, EN, [], manifest={'pages': []}))


def test_unsupported_target_is_reported_not_guessed():
    issues = collect_issues(ZH, EN, [], manifest={'target_language': 'fr', 'pages': []})
    assert 'QA 目标语言不受支持' in titles(issues)
    assert not english_untranslated(issues) and not chinese_untranslated(issues)
    assert [i for i in issues if i.title == 'QA 目标语言不受支持'][0].severity == 'high'


def test_conflicting_direction_records_are_reported():
    issues = collect_issues(ZH, EN, [], manifest={'target_language': 'zh', 'pages': []}, target_language='en')
    assert 'QA 目标语言记录不一致' in titles(issues)
    assert not english_untranslated(issues)  # 以本次任务参数为准


# ---------- 窄保护：参考文献 / 保护值；中文正文仍检出 ----------

def test_english_target_keeps_chinese_references_and_protected_values():
    translation = EN + '\n\n参考文献\n[1] 张三, 李四. 深度学习在医学图像中的应用[J]. 计算机学报, 2020, 43(2): 1-10.\n'
    issues = collect_issues(ZH, translation, [], manifest={'target_language': 'en', 'pages': []})
    assert not chinese_untranslated(issues), titles(issues)
    spans = {'spans': [{'value': '北京大学计算语言学研究所'}]}
    issues = collect_issues(ZH, EN + ' Affiliation: 北京大学计算语言学研究所.', [],
                            manifest={'target_language': 'en', 'pages': []}, protected_spans=spans)
    assert not chinese_untranslated(issues), titles(issues)
    # 参考文献标题之后的普通中文正文（无文献标记）仍检出
    issues = collect_issues(ZH, EN + '\n参考文献\n我们进一步分析了不同设置下的误差来源并讨论局限性', [],
                            manifest={'target_language': 'en', 'pages': []})
    assert chinese_untranslated(issues), titles(issues)


def test_render_manifest_cjk_requirement_follows_target():
    rm = {'status': 'ok', 'validation': {'has_translated_pdf': True, 'translated_text_chars': 500, 'cjk_char_count': 0}}
    assert '译文 PDF 缺少中文可复制文本' in titles(check_render_manifest(rm))
    assert '译文 PDF 缺少中文可复制文本' in titles(check_render_manifest(rm, target_language='zh'))
    assert '译文 PDF 缺少中文可复制文本' not in titles(check_render_manifest(rm, target_language='en'))


def test_terminology_policy_follows_target():
    source = '本文讨论 AI sovereignty 与香港理工大学（Hong Kong Polytechnic University）的合作。'
    translation = 'This paper discusses AI sovereignty and cooperation with the Hong Kong Polytechnic University.'
    zh = titles(collect_issues(source, translation, [], manifest={'target_language': 'zh', 'pages': []}))
    en = titles(collect_issues(source, translation, [], manifest={'target_language': 'en', 'pages': []}))
    assert any('AI sovereignty' in t for t in zh) and any('Hong Kong Polytechnic University' in t for t in zh), zh
    assert not any('AI sovereignty' in t or 'Hong Kong Polytechnic University' in t for t in en), en


# ---------- 双语产物：名称、清单、标注与页序 ----------

def make_pdf(path, text, font):
    doc = fitz.open()
    page = doc.new_page(width=500, height=220)
    page.insert_text((20, 80), text, fontname=font, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def side_texts(path):
    with fitz.open(path) as doc:
        page = doc[0]
        mid = page.rect.width / 2
        left = page.get_text(clip=fitz.Rect(0, 0, mid, page.rect.height))
        right = page.get_text(clip=fitz.Rect(mid, 0, page.rect.width, page.rect.height))
    return left, right


@pytest.mark.parametrize('source_lang,target_lang,src_text,src_font,dst_text,dst_font', [
    ('zh', 'en', '本实验评估模型性能', 'china-s', 'The experiment evaluates models', 'helv'),
    ('en', 'zh', 'The experiment evaluates models', 'helv', '本实验评估模型性能', 'china-s'),
])
def test_bilingual_name_manifest_and_page_order_match_direction(tmp_path, source_lang, target_lang, src_text, src_font, dst_text, dst_font):
    src = make_pdf(tmp_path / f'paper.{source_lang}.pdf', src_text, src_font)
    out = make_pdf(tmp_path / f'paper.{target_lang}.mono.pdf', dst_text, dst_font)
    selected = {'mono_pdf': str(out)}
    r = build_standard_bilingual_output(src, tmp_path, selected, enabled=True, source_language=source_lang,
                                        target_language=target_lang, direction_basis='declared_target_language')
    assert r['status'] == 'ok', r
    final = Path(selected['dual_pdf'])
    assert final.name == f'paper.{source_lang}.{source_lang}-left.{target_lang}-right.dual.pdf'
    assert selected['standard_bilingual_pdf'] == r['output_pdf'] == str(final)
    assert r['layout'] == f'{source_lang}_left_{target_lang}_right'
    assert (r['left_role'], r['right_role']) == ('source', 'translation')
    assert (r['left_language'], r['right_language']) == (source_lang, target_lang)
    assert r['direction_basis'] == 'declared_target_language'
    on_disk = json.loads(Path(r['manifest_path']).read_text(encoding='utf-8'))
    assert on_disk['output_pdf'] == str(final) and on_disk['layout'] == r['layout']
    left, right = side_texts(final)
    assert src_text.split()[0] in left and dst_text.split()[0] in right  # 页序未改：左源右译


def test_en_to_zh_default_name_unchanged(tmp_path):
    src = make_pdf(tmp_path / 'paper.pdf', 'The experiment', 'helv')
    out = make_pdf(tmp_path / 'paper.zh.mono.pdf', '本实验', 'china-s')
    selected = {'mono_pdf': str(out)}
    r = build_standard_bilingual_output(src, tmp_path, selected, enabled=True, source_language='en', target_language='zh')
    assert Path(r['output_pdf']).name == 'paper.en-left.zh-right.dual.pdf' and r['layout'] == 'en_left_zh_right'


def test_unknown_direction_uses_neutral_contract(tmp_path):
    src = make_pdf(tmp_path / 'paper.pdf', '本实验', 'china-s')
    out = make_pdf(tmp_path / 'paper.mono.pdf', 'The experiment', 'helv')
    for kwargs in ({}, {'source_language': 'zh'}, {'source_language': 'zh', 'target_language': 'zh'}):
        selected = {'mono_pdf': str(out)}
        r = build_standard_bilingual_output(src, tmp_path, selected, enabled=True, **kwargs)
        assert Path(r['output_pdf']).name == 'paper.source-left.translation-right.dual.pdf', kwargs
        assert r['layout'] == 'source_left_translation_right' and r['direction_basis'] == 'unknown'
        assert (r['left_language'], r['right_language']) == ('unknown', 'unknown')
        assert (r['left_label'], r['right_label']) == ('原文', '译文')
        assert 'en-left' not in r['output_pdf'] and 'zh-right' not in r['output_pdf']


def test_skipped_results_carry_direction(tmp_path):
    r = build_standard_bilingual_output(tmp_path / 'x.pdf', tmp_path, {}, enabled=True, source_language='zh', target_language='en')
    assert r['status'] == 'skipped' and r['layout'] == 'zh_left_en_right'
    r = build_standard_bilingual_output(tmp_path / 'x.pdf', tmp_path, {}, enabled=True)
    assert r['layout'] == 'source_left_translation_right'


def test_latex_mirror_follows_recorded_direction(tmp_path):
    dual = make_pdf(tmp_path / 'std.dual.pdf', 'x', 'helv')
    latex = make_pdf(tmp_path / 'main.zh.pdf', '中', 'china-s')
    for manifest, name in (({'left_language': 'en', 'right_language': 'zh'}, 'main.zh.en-left.zh-right.dual.pdf'),
                           ({'left_language': 'unknown', 'right_language': 'unknown'}, 'main.zh.source-left.translation-right.dual.pdf')):
        selected = {}
        out = mirror_latex_direct_bilingual_output({'status': 'ok', 'output_pdf': str(dual), **manifest},
                                                   {'translated_pdf': str(latex)}, selected)
        assert Path(out).name == name and selected['latex_direct_dual_pdf'] == out


def test_bilingual_cli_labels(tmp_path):
    src = make_pdf(tmp_path / 's.pdf', '本实验', 'china-s')
    out = make_pdf(tmp_path / 't.pdf', 'The experiment', 'helv')
    script = SKILL / 'scripts' / 'build_bilingual_pdf.py'
    for extra, layout in ((['--source-language', 'zh', '--target-language', 'en'], 'zh_left_en_right'), ([], 'source_left_translation_right')):
        proc = subprocess.run([sys.executable, str(script), '--source-pdf', str(src), '--translated-pdf', str(out),
                               '--output-pdf', str(tmp_path / 'o.pdf'), *extra], capture_output=True, text=True, cwd=SKILL / 'scripts')
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)['layout'] == layout


def test_route_contract_callers_declare_en_to_zh():
    # scanned_raster 路线只接受英译中：其双语清单明确声明 en→zh，而不是靠默认值。
    for rel in ('scripts/scanned_raster/pipeline_runtime.py', 'scripts/scanned_raster/mixed_cover.py', 'scripts/recover_scanned_delivery.py'):
        text = (SKILL / rel).read_text(encoding='utf-8')
        assert "route_contract_scanned_raster_en_to_zh" in text, rel
    assert build_bilingual_pdf.bilingual_direction('en', 'zh', basis='route_contract_scanned_raster_en_to_zh')['layout'] == 'en_left_zh_right'


# ---------- 质量报告标注与独立 QA 入口 ----------

def test_quality_report_labels_follow_target():
    from check_translation_reports import build_quality_report, render_quality_report
    zh_report = build_quality_report(EN, ZH, [], manifest={'target_language': 'zh', 'pages': []})
    en_report = build_quality_report(ZH, EN_WITH_ZH_RESIDUE, [], manifest={'target_language': 'en', 'pages': []})
    assert '- 疑似大段英文未翻译\n' in zh_report and '文字 QA 目标语言：`zh`' in zh_report
    assert '疑似大段英文未翻译' not in en_report and '- 疑似大段中文未翻译（英文译文中的中文残留）' in en_report
    assert '`chinese_residue_count`：1' in en_report and '文字 QA 目标语言：`en`' in en_report
    legacy = render_quality_report([])
    assert '- 疑似大段英文未翻译\n' in legacy and '文字 QA 目标语言' not in legacy and 'chinese_residue_count' not in legacy


def test_check_translation_cli_selects_target(tmp_path):
    (tmp_path / 'source.md').write_text(ZH, encoding='utf-8')
    (tmp_path / 'translation.md').write_text(EN, encoding='utf-8')
    (tmp_path / 'source_manifest.json').write_text(json.dumps({'pages': []}), encoding='utf-8')
    proc = subprocess.run([sys.executable, str(SKILL / 'scripts' / 'check_translation.py'), '--source', str(tmp_path / 'source.md'),
                           '--translation', str(tmp_path / 'translation.md'), '--target-language', 'en'],
                          capture_output=True, text=True, cwd=SKILL)
    report = (tmp_path / 'quality_report.md').read_text(encoding='utf-8')
    assert '文字 QA 目标语言：`en`' in report and '疑似大段英文未翻译' not in report, (proc.stderr[-2000:], report)
    qa = json.loads((tmp_path / 'qa_checks.json').read_text(encoding='utf-8'))
    assert not [c for c in qa.get('checks', []) if '英文' in json.dumps(c, ensure_ascii=False) and '未翻译' in json.dumps(c, ensure_ascii=False)]
    policy = json.loads((tmp_path / 'term_policy.json').read_text(encoding='utf-8'))
    assert policy.get('target_language') == 'en'
