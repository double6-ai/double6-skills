"""2.0.0-rc.3 评审修复第四轮：weak 条目默认计数，只有正面证据才剔除（PR #16 第四次复审）。

复审发现：3 条真实文献条目之后跟一段 57 词的英文实验叙述（无出处信息），被归为 weak 并随整段一起剔除，
结果 ok / 0.0，审计标为 accepted。修复方向：weak 默认计数；只有续接证据（跨页/跨栏续接相邻条目）
或编号连续证据才剔除；无标题段与 References 标题区域一致；审计逐条列出决定。
"""
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(SKILL / 'tests'))

from render_residue_check import check_render_residue  # noqa: E402
from test_rc3_review_round2 import EN_PARA, REFS, ZH_PARA, Page, flow, save  # noqa: E402

# 复审者用例：无出处信息的英文实验叙述，57 词，作者开头、含年份、虚词比例低、不含指标与常见谓语。
NARRATIVE = ('Lin, Y. (2024) ran sixty sequence lengths between four thousand and one million tokens on eight GPUs, '
             'sweeping chunk sizes, learning rates, Muon steps, window widths, hidden dimensions, optimizer momentum, '
             'weight decay, warmup lengths, gradient clipping thresholds, batch sizes and data mixtures, then logged '
             'validation loss, throughput, memory and latency curves for every configuration across three random seeds.')


def run(tmp_path, source_pages, target_pages):
    return check_render_residue(save(tmp_path / 's.pdf', source_pages), save(tmp_path / 't.pdf', target_pages))


def two_pages(tail, heading=False):
    """第 1 页：5 段正文（译文为中文）；第 2 页：参考文献条目与叙述段（译文原样保留英文）。"""
    def doc(body, font):
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 5)
        second = Page(); y = 50
        if heading:
            y = flow(second, 50, 545, y, [('References', 'hebo')])
        flow(second, 50, 545, y, [(t, 'helv') for t in tail])
        return [first, second]
    return doc(EN_PARA, 'helv'), doc(ZH_PARA, 'china-s')


def entry_decisions(result, side='source'):
    rows = []
    for run_ in result['excluded']['headingless_runs'][side]:
        rows += run_['entries_detail']
    rows += result['excluded']['reference_region_entries'][side]
    return rows


def narrative_rows(result):
    return [r for r in entry_decisions(result) if r['preview'].startswith('Lin, Y. (2024)')]


def assert_narrative_counted(result):
    page2 = result['pages'][1]
    assert page2['evaluated'] and page2['severity'] == 'high', page2
    assert result['quality_fail']
    rows = narrative_rows(result)
    assert rows and all(r['decision'] == 'counted' for r in rows), rows


# ---------- 复现：weak 叙述段不得随条目段剔除 ----------

def test_round4_reviewer_case_three_refs_then_narrative_is_counted(tmp_path):
    source, target = two_pages(REFS[:3] + [NARRATIVE])
    assert_narrative_counted(run(tmp_path, source, target))


def test_round4_narrative_in_middle_of_run_is_counted(tmp_path):
    source, target = two_pages(REFS[:2] + [NARRATIVE] + REFS[2:5])
    assert_narrative_counted(run(tmp_path, source, target))


def test_round4_narrative_at_end_of_long_run_is_counted(tmp_path):
    source, target = two_pages(REFS + [NARRATIVE])
    assert_narrative_counted(run(tmp_path, source, target))


def test_round4_narrative_in_references_heading_region_is_counted(tmp_path):
    source, target = two_pages(REFS[:3] + [NARRATIVE], heading=True)
    assert_narrative_counted(run(tmp_path, source, target))


# ---------- 正面证据：真正的续接残段与编号连续的短条目仍剔除 ----------

def test_round4_cross_page_continuation_fragment_is_excluded(tmp_path):
    head = ('[6] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning for image recognition. '
            'In IEEE Conference on Computer')
    tail = 'Vision and Pattern Recognition (CVPR), pages 770-778, 2016.'
    later = ['[7] ' + REFS[3][4:], '[8] ' + REFS[4][4:], '[9] ' + REFS[1][4:]]
    def doc(body, font):
        first = Page(); flow(first, 50, 545, 50, [(body, font)] * 6)
        second = Page(); flow(second, 50, 545, 50, [(r, 'helv') for r in REFS[:5]] + [(head, 'helv')])
        third = Page(); flow(third, 50, 545, 50, [(tail, 'helv')] + [(r, 'helv') for r in later])
        return [first, second, third]
    result = run(tmp_path, doc(EN_PARA, 'helv'), doc(ZH_PARA, 'china-s'))
    assert result['severity'] == 'ok', result['pages']
    rows = {r['preview'][:12]: r for r in entry_decisions(result)}
    assert rows['Vision and P']['decision'] == 'excluded' and rows['Vision and P']['reason'] == 'continuation', rows
    assert rows['[6] Kaiming ']['decision'] == 'excluded' and rows['[6] Kaiming ']['reason'] == 'numbered_sequence', rows


def test_round4_numbered_short_entry_without_venue_is_excluded(tmp_path):
    entries = REFS[:3] + ['[4] Noam Shazeer. Glu variants improve transformer, 2020.'] + ['[5]' + REFS[4][3:], '[6]' + REFS[5][3:]]
    source, target = two_pages(entries)
    result = run(tmp_path, source, target)
    assert result['severity'] == 'ok', result['pages']
    row = [r for r in entry_decisions(result) if r['preview'].startswith('[4] Noam')][0]
    assert row['class'] == 'weak' and row['decision'] == 'excluded' and row['reason'] == 'numbered_sequence', row


def test_round4_unnumbered_weak_entry_is_counted_by_default(tmp_path):
    entries = REFS[:3] + ['Shazeer, N. GLU variants improve the transformer model family, 2020.'] + REFS[3:]
    source, target = two_pages(entries)
    result = run(tmp_path, source, target)
    row = [r for r in entry_decisions(result) if r['preview'].startswith('Shazeer, N.')][0]
    assert row['class'] == 'weak' and row['decision'] == 'counted' and row['reason'] == 'weak_no_positive_evidence', row


def test_round4_audit_lists_every_entry_decision(tmp_path):
    source, target = two_pages(REFS + [NARRATIVE])
    result = run(tmp_path, source, target)
    rows = result['excluded']['headingless_runs']['source'][0]['entries_detail']
    assert len(rows) == 7
    for row in rows:
        assert set(row) >= {'page', 'class', 'decision', 'reason', 'words', 'preview'}
    assert [r['decision'] for r in rows[:6]] == ['excluded'] * 6 and rows[6]['decision'] == 'counted'
    region = result['excluded']['reference_region_entries']
    assert region == {'source': [], 'target': []}
