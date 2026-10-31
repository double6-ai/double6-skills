# SPDX-License-Identifier: AGPL-3.0-only
"""T8 审计盲区检查器:行尾截断守恒检查与写回墨迹覆盖率抽查的离线单测。

覆盖:两个已知真实缺陷形态(段尾悬空截断、白底块盖住的零墨迹行)的最小复现,
以及图题/条款收尾等已知误报形态的抑制。
"""
import json
import sys
from pathlib import Path

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S / 'scripts'))

import fitz

import audit_blindspots
import ink_metrics


def _make_pdf(path, paragraphs, invisible_paragraph=None):
    """paragraphs: [(text, color)];每段写成一个 block(两行起)。
    insert_textbox 空间不足会整段拒写(返回负值),高度不足时逐次加高重写。"""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    for text, color in paragraphs:
        height = 20 * len(text.split('\n')) + 12
        while True:
            box = fitz.Rect(72, y, 540, y + height)
            rc = page.insert_textbox(box, text, fontsize=11, color=color, align=0)
            if rc >= 0:
                break
            height += 20
            assert height < 400, 'textbox never fits'
        y = box.y1 + 10
    if invisible_paragraph:
        height = 60
        while True:
            box = fitz.Rect(72, y, 540, y + height)
            rc = page.insert_textbox(box, invisible_paragraph, fontsize=11, color=(1, 1, 1), align=0)
            if rc >= 0:
                break
            height += 20
            assert height < 400, 'invisible textbox never fits'
    doc.save(str(path))
    doc.close()


def test_ink_metrics_zero_vs_normal(tmp_path):
    """白字行(文字层在、渲染无墨)测出 0 墨,正常行落在正常带附近。"""
    pdf = tmp_path / 'ink.pdf'
    _make_pdf(pdf, [('Line one with enough text to measure.\nLine two with enough text.', (0, 0, 0))],
              invisible_paragraph='Invisible line rendered white on white.')
    summary = ink_metrics.page_ink_summary(str(pdf), 1)
    classes = {l['text'][:20]: l['class'] for l in summary['lines']}
    normal = [l for l in summary['lines'] if not l['text'].startswith('Invisible')]
    invisible = [l for l in summary['lines'] if l['text'].startswith('Invisible')]
    assert all(l['class'] == 'zero-ink' for l in invisible)
    assert all(l['class'] == 'normal' for l in normal)
    assert all(l['ratio'] > ink_metrics.ZERO_INK_MAX_RATIO for l in normal)


def test_writeback_ink_reports_zero_ink_line(tmp_path):
    pdf = tmp_path / 'zero.pdf'
    _make_pdf(pdf, [('Normal paragraph line one.\nNormal paragraph line two.', (0, 0, 0))],
              invisible_paragraph='This whole line is covered by a white block.')
    issues, summary = audit_blindspots.audit_writeback_ink(str(pdf), 1)
    codes = [i['code'] for i in issues]
    assert codes == ['writeback_zero_ink_line']
    assert issues[0]['text'].startswith('This whole line')


def test_truncation_alarm_on_dangling_tail_with_source_evidence(tmp_path):
    """已知缺陷形态:段尾悬空介词 + 源段同样无终结 + 数字消失。
    截断文本自身是段落的最后一行(自动换行成多行 block)。"""
    pdf = tmp_path / 'trunc.pdf'
    para = ('Beijing West Railway Station: take a taxi for about 2 hours to the hotel; or take '
            'Metro Line 9 to National Library, transfer to Line 4, then Line 13 to Qinghe, take '
            'the suburban railway S5523 to Huairou North, ride 1.2 km to the hotel (about 3 hours in')
    _make_pdf(pdf, [(para, (0, 0, 0))])
    src = ('北京西站:乘出租车约2小时至酒店;或乘坐地铁9号线至国家图书馆,换乘4号线,'
           '换乘13号线,市郊铁路怀密线S5523路至怀柔北站,骑行1.2公里左右至酒店(fA 3小')
    issues = audit_blindspots.audit_trailing_truncation(str(pdf), 1, [src])
    assert [i['code'] for i in issues] == ['trailing_truncation_suspect']
    issue = issues[0]
    # 悬空介词 + 源段同样无终结是本缺陷形态的核心双确认;真实缺陷样本还叠加
    # digits-missing:5523(源 S5523 被截丢),此处合成样本数字齐全
    assert 'dangling-tail-word' in issue['signals']
    assert 'source-paragraph-also-unterminated' in issue['signals']
    assert issue['paragraph_tail'].endswith('hours in')


def test_truncation_silent_on_complete_and_list_paragraphs(tmp_path):
    """句号/分号收尾的完整段与条款段不报。"""
    pdf = tmp_path / 'ok.pdf'
    _make_pdf(pdf, [
        ('This paragraph is complete and ends with a period.\nIt has two lines of body text.', (0, 0, 0)),
        ('Registration is free for enrolled students;\nmeals are provided during the workshop.', (0, 0, 0)),
    ])
    assert audit_blindspots.audit_trailing_truncation(str(pdf), 1, ['完整源段,结尾有句号。']) == []


def test_truncation_needs_higher_bar_without_source_evidence(tmp_path):
    """无源段证据时,图题类"专有名词收尾"段落不报警(Yanda Station 形态)。"""
    pdf = tmp_path / 'caption.pdf'
    _make_pdf(pdf, [('Figure 4.3-1\nSchematic diagram of monitoring points at Yanda Station', (0, 0, 0))])
    assert audit_blindspots.audit_trailing_truncation(str(pdf), 1, None) == []


def test_source_paragraphs_grouping_from_manifest(tmp_path):
    """original_ocr_lines 按纵向相邻聚段;间距大的行不合并。"""
    manifest = {'pages': [{'original_ocr_lines': [
        {'text': '第一段第一行', 'bbox_px': [100, 100, 500, 120]},
        {'text': '第一段第二行', 'bbox_px': [100, 122, 500, 142]},
        {'text': '第二段单独一行', 'bbox_px': [100, 300, 500, 320]},
    ]}]}
    path = tmp_path / 'source_manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False))
    paras = audit_blindspots.source_paragraphs_from_manifest(path)
    assert paras == ['第一段第一行第一段第二行', '第二段单独一行']


def test_page_blindspots_codes_aggregate(tmp_path):
    pdf = tmp_path / 'mix.pdf'
    _make_pdf(pdf, [('A complete line.\nAnother complete line.', (0, 0, 0))],
              invisible_paragraph='Covered by a white background block entirely.')
    result = audit_blindspots.audit_page_blindspots(str(pdf), 1)
    assert result['codes'] == ['writeback_zero_ink_line']
    assert result['ink_summary']['median_ratio'] > 0


def test_isolated_symbol_line_not_low_ink(tmp_path):
    """图例里的孤立符号行(如遥感图例的负号)bbox 天然近全空白,不做 low-ink
    相对判定(原文保留稿真实误报形态)。"""
    pdf = tmp_path / 'symbol.pdf'
    _make_pdf(pdf, [('Legend with several words on this line.\nAnother legend row of normal ink.', (0, 0, 0))])
    # 单独插入一个浅灰孤立符号行:有墨但比例远低于正文行中位数
    doc = fitz.open(str(pdf))
    doc[0].insert_text(fitz.Point(72, 200), '\u2212', fontsize=8, color=(0.8, 0.8, 0.8))
    doc.saveIncr()
    doc.close()
    issues, _summary = audit_blindspots.audit_writeback_ink(str(pdf), 1)
    assert all(i['code'] != 'writeback_low_ink_line' for i in issues)
