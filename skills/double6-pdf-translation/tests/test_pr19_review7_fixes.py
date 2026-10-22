"""PR #19 第 7 轮修复的回归用例（无模型调用）：
P1(1) text_layer_math_loss 逐实例核对（英文单词里的字母不能顶替丢失的变量，有歧义即失败关闭）；
P1(2) 资源监控：非本任务进程的查询错误逐进程隔离、资源门照常生效；本任务进程监控失败结构化停止。"""
import json
import os
import sys
import time
from pathlib import Path

import fitz
import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'tests'), str(SKILL / 'vendor/babeldoc')]
import test_pr19_review_boundaries as b  # noqa: E402
from render_residue_check import check_render_residue, page_text_layer_math_loss  # noqa: E402

MIB = 1024 ** 2
GIB = 1024 ** 3
TAIL = ' This paper presents a mathematical framework for the far-field directivity of arrays and derives analytical expressions.' * 3


def _source(path, chars=('x',), *, font='tiit'):
    """与评审用例同构：中文正文行内插入斜体变量（可多个）。"""
    d = fitz.open()
    p = b._inline_page(d)
    x = 72 + 10.5 * len(b.ZH_LINE_A) + 4 + 2
    for i, ch in enumerate(chars):
        p.insert_text((x + 9 * i, 120), ch, fontname=font, fontsize=11)
    d.save(path)
    d.close()


def _target(path, pieces):
    """pieces: [(text, fontname)] 依次写在同一行（按实际字宽排版），再接英文填充段。"""
    d = fitz.open()
    p = d.new_page()
    x = 72
    for text, font in pieces:
        p.insert_text((x, 90), text, fontname=font, fontsize=10)
        x += fitz.get_text_length(text, fontname=font, fontsize=10)
    p.insert_textbox(fitz.Rect(72, 110, 520, 400), TAIL, fontname='helv', fontsize=10)
    d.save(path)
    d.close()


def _gate(tmp_path, chars, pieces, *, font='tiit'):
    src, tgt = tmp_path / 'source.pdf', tmp_path / 'target.pdf'
    _source(src, chars, font=font)
    _target(tgt, pieces)
    with fitz.open(src) as s, fitz.open(tgt) as t:
        loss = page_text_layer_math_loss(s, 0, t[0])
    qa = check_render_residue(src, tgt, target_language='en')
    return loss, qa


# ---- P1(1) 负例：英文单词内部或有歧义的字形不能算保留 ----

def test_x_inside_hyphenated_word_is_not_the_variable(tmp_path):
    loss, qa = _gate(tmp_path, ['x'], [('Consider an x-ray array of single-polarized antennas.', 'helv')])
    assert loss['lost'] == 1 and loss['samples'][0]['unresolved'] == 'only_inside_words', loss
    assert qa['quality_fail']


def test_two_variables_one_standalone_copy_loses_one(tmp_path):
    loss, qa = _gate(tmp_path, ['x', 'x'], [('Consider x single-polarized expressions.', 'helv')])
    assert (loss['located'], loss['lost']) == (2, 1), loss
    assert qa['quality_fail']


def test_article_a_cannot_stand_in_for_variable_a(tmp_path):
    loss, qa = _gate(tmp_path, ['a'], [('Consider a single-polarized array of antennas.', 'helv')])
    assert loss['lost'] == 1 and loss['samples'][0]['unresolved'] == 'ambiguous_english_word_letter', loss
    assert qa['quality_fail']


def test_abbreviation_letters_do_not_count(tmp_path):
    loss, qa = _gate(tmp_path, ['e'], [('Consider arrays, e.g. single-polarized antennas.', 'helv')])
    assert loss['lost'] == 1, loss
    assert qa['quality_fail']


# ---- P1(1) 正例：重排后的独立变量、带标点/运算符的变量、保留原字体的歧义字母 ----

@pytest.mark.parametrize('line', ['Consider an array of x, single-polarized antennas.',
                                  'Consider an array of (x) single-polarized antennas.',
                                  'Consider an array where x<0.5 for single-polarized antennas.'])
def test_reflowed_standalone_variable_is_kept(tmp_path, line):
    loss, qa = _gate(tmp_path, ['x'], [(line, 'helv')])
    assert loss['lost'] == 0, loss
    assert not qa['quality_fail'], qa


def test_variable_kept_in_math_italic_font_is_kept(tmp_path):
    loss, qa = _gate(tmp_path, ['x'], [('Consider an array of ', 'helv'), ('x', 'tiit'),
                                        (' single-polarized antennas.', 'helv')])
    assert loss['lost'] == 0, loss
    assert not qa['quality_fail'], qa


def test_ambiguous_letter_kept_in_source_italic_font_is_kept(tmp_path):
    loss, qa = _gate(tmp_path, ['a'], [('Consider an array of ', 'helv'), ('a', 'tiit'),
                                        (' single-polarized antennas.', 'helv')])
    assert loss['lost'] == 0, loss
    assert not qa['quality_fail'], qa


def test_rule_is_reported(tmp_path):
    loss, _ = _gate(tmp_path, ['x'], [('Consider x antennas.', 'helv')])
    assert loss['rule'] == 'per_instance_v1'


# ---- P1(1) 真实后端缺陷样例：Linux 回放（2386a99，无模型）得到的成品，按逐字符几何存为 JSON（仓库不提交 PDF） ----

REAL = json.loads((SKILL / 'tests' / 'fixtures' / 'pr19_review7' / 'italic_x_backend_mono_chars.json').read_text())


def _noto_serif():
    for base in (os.environ.get('HOME', ''), '/home/box'):
        path = Path(base) / '.cache/babeldoc/fonts/NotoSerif-Regular.ttf'
        if path.is_file():
            return str(path)
    return None


def _rebuild_real(tmp_path, *, drop_italic=False):
    """按 JSON 重建真实成品页：Times-Italic 字形用内置 Times-Italic，译文用 babeldoc 的 NotoSerif（本机缓存；
    CI 没有时退回 Helvetica，此时重叠门无法识别译文字体，相关断言跳过）。"""
    from test_pr19_review7_text_layer_counter import write_source
    src, tgt = tmp_path / 'source.pdf', tmp_path / 'target.pdf'
    write_source(src, False)
    noto = _noto_serif()
    d = fitz.open()
    page = d.new_page(width=REAL['page'][0], height=REAL['page'][1])
    for span in REAL['spans']:
        italic = 'Italic' in span['font']
        if italic and drop_italic:
            continue
        for c, origin, _ in span['chars']:
            if italic:
                page.insert_text(origin, c, fontname='tiit', fontsize=span['size'])
            elif noto:
                page.insert_text(origin, c, fontname='NotoSerif', fontfile=noto, fontsize=span['size'])
            else:
                page.insert_text(origin, c, fontname='helv', fontsize=span['size'])
    d.save(tgt)
    d.close()
    return src, tgt, noto


def test_real_backend_italic_x_output_is_rejected(tmp_path):
    """后端把斜体 x 留在原坐标（Times-Italic），与重排后的英文重叠：x 仍在（逐实例门不判丢失），
    成品由重叠门判失败——不是“丢了 x 却退出 0”。"""
    src, tgt, noto = _rebuild_real(tmp_path)
    with fitz.open(src) as s, fitz.open(tgt) as t:
        loss = page_text_layer_math_loss(s, 0, t[0])
    assert (loss['located'], loss['lost']) == (1, 0), loss
    if not noto:
        pytest.skip('NotoSerif not cached; overlap gate needs the translated font')
    qa = check_render_residue(src, tgt, target_language='en')
    assert qa['quality_fail'] and qa['retained_glyph_overlap_pages'] == [1], qa


def test_real_backend_output_with_variable_removed_is_lost(tmp_path):
    """同一真实成品去掉保留的斜体 x（英文里仍有 expressions 等带 x 的单词）：逐实例门必须判丢失。"""
    src, tgt, _ = _rebuild_real(tmp_path, drop_italic=True)
    with fitz.open(tgt) as t:
        assert 'x' in ''.join(c for sp in REAL['spans'] if 'Italic' not in sp['font'] for c, _, _ in sp['chars'])
    with fitz.open(src) as s, fitz.open(tgt) as t:
        loss = page_text_layer_math_loss(s, 0, t[0])
    assert (loss['located'], loss['lost']) == (1, 1), loss
    assert loss['samples'][0]['unresolved'] == 'only_inside_words'
    assert check_render_residue(src, tgt, target_language='en')['quality_fail']


# ---- P1(2) 资源监控 ----

class _FakeProc:
    def __init__(self, pid, name=None, exc=None, rss=10 * MIB):
        self.pid, self._name, self._exc, self._rss = pid, name, exc, rss

    def name(self):
        if self._exc:
            raise self._exc
        return self._name

    def memory_info(self):
        return type('M', (), {'rss': self._rss})()


def _bad_iter(include_codex=True, then_raise=True):
    def gen(*args, **kwargs):
        yield _FakeProc(999901, exc=SystemError('proc_cmdline returned a result with an exception set: KERN_PROCARGS2'))
        yield _FakeProc(999902, exc=psutil.AccessDenied(999902))
        yield _FakeProc(999903, exc=psutil.ZombieProcess(999903))
        yield _FakeProc(999904, exc=PermissionError('denied'))
        yield _FakeProc(999905, exc=psutil.NoSuchProcess(999905))
        if include_codex:
            yield _FakeProc(999906, name='Codex Helper', rss=123 * MIB)
        if then_raise:
            raise SystemError('iterator failure from psutil C extension')
    return gen


def test_unowned_per_process_errors_are_isolated(monkeypatch):
    import bounded_execution as be
    monkeypatch.setattr(be.psutil, 'process_iter', _bad_iter(then_raise=False))
    snap = be.snapshot([])
    assert snap['task_rss'] > 0 and snap['process_count'] >= 1
    assert [row['pid'] for row in snap['codex']] == [999906]
    assert snap['unowned_scan'] == {'complete': True, 'per_process_errors': 5, 'iterator_error': None}
    assert snap['owned_monitor_errors'] == []


def test_codex_fuse_still_enforced_with_unowned_errors(monkeypatch):
    import bounded_execution as be
    def gen(*a, **k):
        yield _FakeProc(999901, exc=SystemError('KERN_PROCARGS2'))
        yield _FakeProc(999906, name='codex', rss=21 * GIB)
    monkeypatch.setattr(be.psutil, 'process_iter', gen)
    snap = be.snapshot([])
    assert be.violation(snap, snap, rss_limit=8 * GIB, max_processes=8) == 'codex_memory_fuse'


def test_unowned_errors_run_continues_and_completes(monkeypatch, tmp_path):
    import bounded_execution as be
    monkeypatch.setattr(be.psutil, 'process_iter', _bad_iter())
    outcome = be.run_bounded([sys.executable, '-c', 'import time; time.sleep(0.5); print("done")'], cwd=tmp_path,
                             receipt_dir=tmp_path / 'r', operation='ok', timeout_seconds=30, interval_seconds=0.1,
                             rss_limit=2 * GIB, memory_metric='rss')
    assert outcome['status'] == 'succeeded', outcome
    assert outcome['stop_reason'] is None and outcome['peak_task_memory_bytes'] > 0
    samples = [json.loads(line) for line in Path(outcome['resource_receipt']).read_text().splitlines()]
    assert len(samples) >= 3 and all(s['unowned_scan']['complete'] is False for s in samples)


def test_unowned_errors_memory_limit_still_triggers(monkeypatch, tmp_path):
    import bounded_execution as be
    monkeypatch.setattr(be.psutil, 'process_iter', _bad_iter())
    code = 'import time; b = bytearray(400 * 1024 * 1024); time.sleep(20)'
    start = time.monotonic()
    outcome = be.run_bounded([sys.executable, '-c', code], cwd=tmp_path, receipt_dir=tmp_path / 'r', operation='mem',
                             timeout_seconds=60, interval_seconds=0.1, rss_limit=256 * MIB, memory_metric='rss')
    assert outcome['status'] == 'stopped' and outcome['stop_reason'] == 'task_memory_limit', outcome
    assert outcome['owned_tree_alive'] == [] and time.monotonic() - start < 15
    receipt = json.loads(Path(outcome['failure_receipt']).read_text())
    assert receipt['failure_code'] == 'task_memory_limit'


def test_owned_process_error_stops_structurally(monkeypatch, tmp_path):
    import bounded_execution as be
    real = be._process_memory
    me = os.getpid()

    def flaky(proc, metric):
        if proc.pid != me:
            raise SystemError('KERN_PROCARGS2 permission denied on owned child')
        return real(proc, metric)
    monkeypatch.setattr(be, '_process_memory', flaky)
    start = time.monotonic()
    outcome = be.run_bounded([sys.executable, '-c', 'import time; time.sleep(20)'], cwd=tmp_path,
                             receipt_dir=tmp_path / 'r', operation='owned', timeout_seconds=60, interval_seconds=0.1,
                             rss_limit=2 * GIB, memory_metric='rss')
    assert outcome['status'] == 'stopped' and outcome['stop_reason'] == 'owned_process_monitor_unavailable', outcome
    assert outcome['owned_tree_alive'] == [] and time.monotonic() - start < 15
    receipt = json.loads(Path(outcome['failure_receipt']).read_text())
    assert receipt['failure_code'] == 'owned_process_monitor_unavailable'
    samples = [json.loads(line) for line in Path(outcome['resource_receipt']).read_text().splitlines()]
    assert any(s.get('owned_monitor_errors') for s in samples)


def test_owned_discovery_error_stops_structurally(monkeypatch, tmp_path):
    import bounded_execution as be
    def broken():
        raise SystemError('pid list unavailable')
    monkeypatch.setattr(be.psutil, 'pids', broken)
    outcome = be.run_bounded([sys.executable, '-c', 'import time; time.sleep(20)'], cwd=tmp_path,
                             receipt_dir=tmp_path / 'r', operation='disc', timeout_seconds=60, interval_seconds=0.1,
                             rss_limit=2 * GIB, memory_metric='rss')
    assert outcome['stop_reason'] == 'owned_process_monitor_unavailable', outcome
    assert outcome['owned_tree_alive'] == [] and outcome['monitor_error']
    assert json.loads(Path(outcome['failure_receipt']).read_text())['failure_code'] == 'owned_process_monitor_unavailable'


def test_monitor_exception_mid_run_stops_structurally(monkeypatch, tmp_path):
    import bounded_execution as be
    real = be.psutil.virtual_memory
    calls = {'n': 0}

    def vm():
        calls['n'] += 1
        if calls['n'] > 2:
            raise SystemError('host memory query failed')
        return real()
    monkeypatch.setattr(be.psutil, 'virtual_memory', vm)
    outcome = be.run_bounded([sys.executable, '-c', 'import time; time.sleep(20)'], cwd=tmp_path,
                             receipt_dir=tmp_path / 'r', operation='vm', timeout_seconds=60, interval_seconds=0.1,
                             rss_limit=2 * GIB, memory_metric='rss')
    assert outcome['stop_reason'] == 'resource_monitor_unavailable', outcome
    assert outcome['owned_tree_alive'] == []
    assert json.loads(Path(outcome['failure_receipt']).read_text())['failure_code'] == 'resource_monitor_unavailable'


def test_baseline_monitor_failure_does_not_launch(monkeypatch, tmp_path):
    import bounded_execution as be
    def vm():
        raise SystemError('host memory query failed')
    monkeypatch.setattr(be.psutil, 'virtual_memory', vm)
    marker = tmp_path / 'launched'
    outcome = be.run_bounded([sys.executable, '-c', f'open({str(marker)!r}, "w").close()'], cwd=tmp_path,
                             receipt_dir=tmp_path / 'r', operation='base', timeout_seconds=30, interval_seconds=0.1,
                             rss_limit=2 * GIB, memory_metric='rss')
    assert outcome['status'] == 'stopped' and outcome['stop_reason'] == 'resource_monitor_unavailable'
    assert not marker.exists() and Path(outcome['failure_receipt']).is_file()


def test_workflow_unexpected_error_still_writes_stdout_and_receipt(monkeypatch, tmp_path, capsys):
    import paper_translation_workflow as wf
    def boom(args):
        raise SystemError('unexpected failure inside dispatch')
    monkeypatch.setattr(wf, 'dispatch', boom)
    receipts = tmp_path / 'receipts'
    src = tmp_path / 'in.pdf'
    d = fitz.open(); d.new_page(); d.save(src); d.close()
    code = wf.main(['candidate', '--input', str(src), '--freeze', str(tmp_path / 'F.json'), '--route', 'digital_pdf',
                    '--model', 'm', '--base-url', 'http://127.0.0.1:9/v1', '--output', str(tmp_path / 'out'),
                    '--receipts', str(receipts)])
    out = json.loads(capsys.readouterr().out)
    assert code == wf.EXIT_ERROR and out['error_code'] == 'internal_error' and out['exception_type'] == 'SystemError'
    assert json.loads((receipts / 'WORKFLOW_INTERNAL_ERROR.json').read_text())['error_code'] == 'internal_error'


def test_workflow_stopped_job_has_stable_error_code(monkeypatch, tmp_path):
    import paper_translation_workflow as wf
    monkeypatch.setattr(wf, 'run_bounded', lambda *a, **k: {'status': 'stopped', 'stop_reason': 'owned_process_monitor_unavailable',
                                                           'command': None})
    monkeypatch.setattr(wf, 'job_limits', lambda args: {'per_job_seconds': 60, 'task_rss_bytes': GIB,
                                                        'memory_metric': 'rss', 'max_total_fraction': .25})
    args = type('A', (), {'lock_path': tmp_path / 'lock', 'receipts': tmp_path / 'r'})()
    result = wf.run_job(args, ['true'], 'candidate')
    assert result['error_code'] == 'owned_process_monitor_unavailable'
