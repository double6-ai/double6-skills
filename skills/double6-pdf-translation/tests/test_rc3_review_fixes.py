"""2.0.0-rc.3 评审修复（PR #16）：每个问题先有复现用例，再修复。"""
import json
import sys
import time
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

GIB = 1024 ** 3
MIB = 1024 ** 2
EN = ('Test-time training adapts model weights during inference so that the network can store '
      'long context in fast weights. We evaluate the approach on language modeling and view synthesis. ') * 6
ZH = '测试时训练在推理过程中更新模型权重，使网络能够把长上下文存入快速权重。我们在语言建模和新视角合成上评估该方法。' * 6
REFS = [f'[{i}] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. N. Gomez. Attention is all you need. '
        f'In Advances in Neural Information Processing Systems, volume {i}, pages 5998-6008, 2017.' for i in range(1, 9)]
LEGACY = {'task_rss_bytes': 3 * GIB, 'per_job_seconds': 120, 'concurrency': 1}


def write_lines(page, lines, *, y=60, size=9, font='helv', width=480):
    """逐段写入并返回下一段起始 y；每段独立成行块，便于标题识别。"""
    for line in lines:
        rect = fitz.Rect(50, y, 50 + width, 820)
        rest = page.insert_textbox(rect, line, fontname=font, fontsize=size)
        used = (rect.height - rest) if rest >= 0 else rect.height
        y += used + size * 0.8
    return y


def make_doc(path, pages):
    """pages: [[(text, font), ...], ...]；font 'china-s' 表示中文。"""
    doc = fitz.open()
    for items in pages:
        page = doc.new_page()
        y = 60
        for text, font in items:
            y = write_lines(page, [text], y=y, font=font)
    doc.save(path)
    doc.close()
    return path


def make_pdf(path, pages=1, text=EN, cjk=False):
    return make_doc(path, [[(text, 'china-s' if cjk else 'helv')] for _ in range(pages)])


# ---------- Issue 1 [P1]: frozen resource contract is authoritative ----------

def _fake_backend(monkeypatch, wf, *, quality='warn', issues=(), route='digital_pdf', calls=None):
    calls = [] if calls is None else calls

    def fake_run_bounded(command, **kwargs):
        calls.append({'command': command, **{k: kwargs.get(k) for k in ('timeout_seconds', 'rss_limit', 'memory_metric', 'operation')}})
        if kwargs.get('operation') == 'input-preflight':
            return _real_run_bounded(command, **kwargs)
        out = Path(command[command.index('--output') + 1])
        out.mkdir(parents=True, exist_ok=True)
        verb = command[2] if len(command) > 2 else ''
        if route == 'latex_verified' and verb == 'prepare':
            (out / 'latex_plan.json').write_text(json.dumps({'units': []}))
        elif route == 'latex_verified' and verb == 'compile' or route != 'latex_verified':
            mono = out / 'candidate.zh.mono.pdf'
            make_pdf(mono, text=ZH, cjk=True)
            (out / 'comprehensive_quality.json').write_text(json.dumps({'status': quality, 'issues': list(issues)}))
            manifest = {'quality_status': quality, 'outputs': {'translated_pdf': str(mono)}}
            (out / 'render_manifest.json').write_text(json.dumps(manifest))
            if route == 'latex_verified':
                (out / 'latex_result.json').write_text(json.dumps({'status': 'candidate'}))
        return {'status': 'succeeded', 'command': {'stdout_summary': {'excerpt': ''}}}

    import bounded_execution
    _real_run_bounded = bounded_execution.run_bounded
    monkeypatch.setattr(wf, 'run_bounded', fake_run_bounded)
    monkeypatch.setattr(wf, 'validate_freeze', lambda *a, **k: [1])
    monkeypatch.setattr(wf, 'doctor', lambda *a, **k: {'blockers': [], 'latex_ready': True})
    monkeypatch.setattr(wf, 'candidate_command', lambda args, freeze: [
        sys.executable, 'run_pdf_translation.py', '--input', str(args.input), '--output', str(args.output)])
    return calls


def _main(tmp_path, wf, capsys, *extra, contract=LEGACY, route='digital_pdf', pdf=None):
    pdf = pdf or make_pdf(tmp_path / 'in.pdf')
    freeze = {'resource_contract': contract} if contract is not None else {}
    if route == 'latex_verified':
        freeze.update(latex_source={'path': str(tmp_path / 'main.tex')}, model_fingerprint_ref={'path': str(tmp_path / 'fp.json')})
    (tmp_path / 'FREEZE.json').write_text(json.dumps(freeze))
    code = wf.main(['candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'),
                    '--freeze', str(tmp_path / 'FREEZE.json'), '--route', route, '--model', 'm',
                    '--base-url', 'http://127.0.0.1:9/v1', '--lock-path', str(tmp_path / 'wf.lock'), *extra])
    return code, json.loads(capsys.readouterr().out)


def _heavy(calls):
    return [c for c in calls if c['operation'] != 'input-preflight']


def test_issue1_frozen_contract_enforced_without_overrides(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    for name in ('PAPER_TRANSLATION_TASK_MEMORY_MIB', 'PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS', 'PAPER_TRANSLATION_MEMORY_METRIC'):
        monkeypatch.delenv(name, raising=False)
    calls = _fake_backend(monkeypatch, wf)
    code, result = _main(tmp_path, wf, capsys)
    assert code == 0, result
    job = _heavy(calls)[0]
    assert job['rss_limit'] == 3 * GIB and job['timeout_seconds'] == 120 and job['memory_metric'] == 'rss'
    enforced = result['resource_limits']
    assert enforced['task_rss_bytes'] == 3 * GIB and enforced['per_job_seconds'] == 120
    assert enforced['source'] == {'task_rss_bytes': 'freeze', 'per_job_seconds': 'freeze', 'memory_metric': 'freeze'}
    receipt = json.loads((tmp_path / 'rc/WORKFLOW_CANDIDATE.json').read_text())
    assert receipt['resource_limits']['task_rss_bytes'] == receipt['resource_contract_frozen']['task_rss_bytes']


@pytest.mark.parametrize('via', ['cli', 'env'])
def test_issue1_override_exceeding_frozen_contract_is_rejected(tmp_path, monkeypatch, capsys, via):
    import paper_translation_workflow as wf
    calls = _fake_backend(monkeypatch, wf)
    extra = ()
    if via == 'cli':
        extra = ('--task-memory-mib', '4096', '--job-timeout-seconds', '600')
    else:
        monkeypatch.setenv('PAPER_TRANSLATION_TASK_MEMORY_MIB', '4096')
        monkeypatch.setenv('PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS', '600')
    code, result = _main(tmp_path, wf, capsys, *extra)
    assert code == 2 and result['error_code'] == 'resource_override_conflicts_with_freeze', result
    assert 'task_rss_bytes' in result['findings'][0]['message'] and 'per_job_seconds' in result['findings'][0]['message']
    assert _heavy(calls) == [] and not (tmp_path / 'out').exists()


def test_issue1_override_equal_to_frozen_contract_is_accepted(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    calls = _fake_backend(monkeypatch, wf)
    code, result = _main(tmp_path, wf, capsys, '--task-memory-mib', '3072', '--job-timeout-seconds', '120', '--memory-metric', 'rss')
    assert code == 0 and _heavy(calls)[0]['rss_limit'] == 3 * GIB


def test_issue1_frozen_contract_metric_and_host_cap(tmp_path):
    import resource_limits as rl
    pss = rl.limits_from_frozen_contract({'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'concurrency': 1,
                                          'memory_metric': 'pss'}, environ={}, total_memory=16 * GIB)
    assert pss['memory_metric'] == 'pss' and pss['per_job_seconds'] == 300 and pss['max_total_fraction'] == 0.5
    assert rl.limits_from_frozen_contract(LEGACY, environ={}, total_memory=16 * GIB)['memory_metric'] == 'rss'
    with pytest.raises(rl.ResourceLimitError, match='task_memory_limit_exceeds_host_authorization'):
        rl.limits_from_frozen_contract({'task_rss_bytes': 12 * GIB, 'per_job_seconds': 300, 'concurrency': 1},
                                       environ={}, total_memory=16 * GIB)
    with pytest.raises(rl.ResourceLimitError, match='resource_override_conflicts_with_freeze'):
        rl.limits_from_frozen_contract(LEGACY, memory_metric='pss', environ={}, total_memory=16 * GIB)


# ---------- Issue 2 [P1]: references / URLs / citations / code excluded from residue ----------

def _body_and_refs(path, body_text, body_font, heading, refs, split_pages=True):
    body = [(body_text, body_font)]
    tail = [(heading, body_font if heading == '参考文献' else 'helv')] + [(r, 'helv') for r in refs]
    return make_doc(path, [body, tail] if split_pages else [body + tail])


@pytest.mark.parametrize('split_pages', [True, False])
@pytest.mark.parametrize('target_heading', ['参考文献', 'References'])
def test_issue2_english_references_do_not_fail_translated_body(tmp_path, split_pages, target_heading):
    from render_residue_check import check_render_residue
    source = _body_and_refs(tmp_path / 's.pdf', EN, 'helv', 'References', REFS, split_pages)
    target = _body_and_refs(tmp_path / 't.pdf', ZH, 'china-s', target_heading, REFS, split_pages)
    result = check_render_residue(source, target)
    assert result['severity'] == 'ok' and not result['quality_fail'], result
    assert result['excluded']['reference_section_pages']['source'] == ([2] if split_pages else [1])
    assert sum(p['excluded_source_words'] for p in result['pages']) > 100


def test_issue2_untranslated_body_with_references_still_fails(tmp_path):
    from render_residue_check import check_render_residue
    source = _body_and_refs(tmp_path / 's.pdf', EN, 'helv', 'References', REFS)
    result = check_render_residue(source, _body_and_refs(tmp_path / 't.pdf', EN, 'helv', 'References', REFS))
    assert result['severity'] == 'high' and result['high_pages'] == [1]


def test_issue2_urls_citations_and_code_are_excluded(tmp_path):
    from render_residue_check import check_render_residue
    urls = ' '.join(f'https://github.com/example/project-{i}/blob/main/README.md' for i in range(12))
    cites = ' '.join(f'[{i}] (Vaswani et al., 2017; Brown et al., 2020)' for i in range(10))
    code = 'def forward(self, input_tensor): return self.linear_layer(self.dropout(input_tensor)) + residual_value'
    source = make_doc(tmp_path / 's.pdf', [[(EN, 'helv'), (urls, 'helv'), (cites, 'helv'), (code, 'cour'), (code, 'cour')]])
    target = make_doc(tmp_path / 't.pdf', [[(ZH, 'china-s'), (urls, 'helv'), (cites, 'helv'), (code, 'cour'), (code, 'cour')]])
    result = check_render_residue(source, target)
    assert result['severity'] == 'ok', result['pages']
    assert result['pages'][0]['residue_ratio'] < 0.3


# ---------- Issue 3 [P2]: any combined QA fail -> exit 3, on every route ----------

LATEX_ISSUE = {'id': 'latex_unresolved_reference', 'rule': 'latex_compile_unresolved', 'severity': 'high', 'pages': [1]}


def test_issue3_latex_route_quality_fail_exits_3(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    _fake_backend(monkeypatch, wf, quality='fail', issues=[LATEX_ISSUE], route='latex_verified')
    code, result = _main(tmp_path, wf, capsys, route='latex_verified')
    assert code == 3, result
    assert result['quality_status'] == 'fail' and result['quality_fail_reasons'][0]['id'] == 'latex_unresolved_reference'
    assert json.loads((tmp_path / 'rc/WORKFLOW_CANDIDATE.json').read_text())['quality_gate'] == 'fail'


def test_issue3_digital_non_residue_quality_fail_exits_3(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    issue = {'id': 'technical_receipt_mismatch', 'rule': 'technical_check', 'severity': 'high'}
    _fake_backend(monkeypatch, wf, quality='fail', issues=[issue])
    code, result = _main(tmp_path, wf, capsys)
    assert code == 3 and result['quality_fail_reasons'][0]['id'] == 'technical_receipt_mismatch'


def test_issue3_revise_latex_quality_fail_exits_3(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    _fake_backend(monkeypatch, wf, quality='fail', issues=[LATEX_ISSUE])
    pdf = make_pdf(tmp_path / 'in.pdf')
    (tmp_path / 'contract.json').write_text(json.dumps({'source_pdf_ref': wf.ref(pdf)}))
    code = wf.main(['revise-latex', '--input', str(pdf), '--contract', str(tmp_path / 'contract.json'),
                    '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'), '--lock-path', str(tmp_path / 'l')])
    result = json.loads(capsys.readouterr().out)
    assert code == 3 and result['quality_status'] == 'fail', result


def test_issue3_comprehensive_quality_is_authoritative_over_manifest(tmp_path):
    import paper_translation_workflow as wf
    (tmp_path / 'comprehensive_quality.json').write_text(json.dumps({'status': 'fail', 'issues': [LATEX_ISSUE]}))
    (tmp_path / 'render_manifest.json').write_text(json.dumps({'quality_status': 'unverified'}))
    verdict = wf.quality_verdict(tmp_path)
    assert verdict['quality_status'] == 'fail' and verdict['quality_fail_reasons'][0]['id'] == 'latex_unresolved_reference'


# ---------- Issue 4 [P2]: page-limit short-circuit; parsing inside guards ----------

def test_issue4_page_limit_short_circuits_page_parsing(tmp_path, monkeypatch):
    import pdf_input_preflight as pre
    calls = []
    real = pre.classify_page
    monkeypatch.setattr(pre, 'classify_page', lambda page: calls.append(page.number) or real(page))
    result = pre.inspect_pdf(make_pdf(tmp_path / 'long.pdf', pages=12), max_pages=5)
    assert result['error_code'] == 'page_limit_exceeded' and result['page_count'] == 12
    assert calls == [], f'pages parsed after limit known: {calls}'


def test_issue4_candidate_preflight_runs_inside_bounded_child(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    calls = _fake_backend(monkeypatch, wf)
    code, result = _main(tmp_path, wf, capsys, pdf=make_pdf(tmp_path / 'long.pdf', pages=7))
    assert code == 2 and result['error_code'] == 'page_limit_exceeded'
    pre = [c for c in calls if c['operation'] == 'input-preflight']
    assert len(pre) == 1 and pre[0]['rss_limit'] and pre[0]['timeout_seconds']
    assert (tmp_path / 'rc/input-preflight/input-preflight.resource.jsonl').is_file()
    assert _heavy(calls) == []


# ---------- Issue 5 [P2]: baseline and final samples count toward the peak ----------

def test_issue5_fast_job_peak_includes_baseline_and_final(tmp_path):
    from bounded_execution import run_bounded
    samples = iter([700 * MIB] + [100 * MIB] * 50)

    def observer():
        value = next(samples, 100 * MIB)
        return {'total': 64 * GIB, 'available': 32 * GIB, 'swap_used': 0, 'codex': [], 'task_rss': value,
                'task_rss_sum': value, 'process_count': 1, 'processes': []}

    outcome = run_bounded([sys.executable, '-c', 'pass'], cwd=tmp_path, receipt_dir=tmp_path / 'r', operation='fast',
                          timeout_seconds=30, interval_seconds=5, rss_limit=2 * GIB, observer=observer)
    assert outcome['peak_task_memory_bytes'] >= 700 * MIB, outcome.get('peak_task_memory_bytes')


def test_issue5_real_fast_job_peak_is_not_zero(tmp_path):
    from bounded_execution import run_bounded
    code = 'import time; b = bytearray(64 * 1024 * 1024); time.sleep(0.4)'
    outcome = run_bounded([sys.executable, '-c', code], cwd=tmp_path, receipt_dir=tmp_path / 'r', operation='fast',
                          timeout_seconds=30, interval_seconds=5, rss_limit=2 * GIB)
    assert outcome['status'] == 'succeeded'
    assert outcome['peak_task_memory_bytes'] >= 32 * MIB, outcome.get('peak_task_memory_bytes')
    # 峰值必须覆盖收据中的每一个样本（含基线与收尾样本）。
    samples = [json.loads(line) for line in Path(outcome['resource_receipt']).read_text().splitlines()]
    assert len(samples) >= 3
    assert outcome['peak_task_memory_bytes'] == max(s['task_rss'] for s in samples)
    assert outcome['peak_task_rss_sum_bytes'] == max(s['task_rss_sum'] for s in samples)
