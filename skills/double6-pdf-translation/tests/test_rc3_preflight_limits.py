"""2.0.0-rc.3：结构化预检、可配置资源上限、真实错误收据、源语言与渲染残留检查。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

import resource_limits as rl  # noqa: E402
from pdf_input_preflight import PreflightError, detect_language, inspect_pdf  # noqa: E402
from render_residue_check import check_render_residue  # noqa: E402

GIB = 1024 ** 3
EN = ('Test-time training adapts model weights during inference so that the network can store '
      'long context in fast weights. We evaluate the approach on language modeling and view synthesis. ') * 6
ZH = '测试时训练在推理过程中更新模型权重，使网络能够把长上下文存入快速权重。我们在语言建模和新视角合成上评估该方法。' * 6


def make_pdf(path, pages=1, text=EN, cjk=False, **save):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        rect = fitz.Rect(50, 50, 545, 790)
        if cjk:
            page.insert_textbox(rect, text, fontname='china-s', fontsize=10)
        else:
            page.insert_textbox(rect, text, fontsize=10)
    doc.save(path, **save)
    doc.close()
    return path


def make_scan(path):
    src = fitz.open(); page = src.new_page(); page.insert_textbox(fitz.Rect(50, 50, 545, 790), EN, fontsize=10)
    pix = page.get_pixmap(dpi=60)
    doc = fitz.open(); out = doc.new_page(width=page.rect.width, height=page.rect.height)
    out.insert_image(out.rect, pixmap=pix)
    doc.save(path)
    return path


# ---------- resource limits ----------

def test_platform_defaults_and_precedence():
    big = 64 * GIB
    mac = rl.resolve_limits(platform='darwin', environ={}, total_memory=big)
    assert (mac['task_rss_bytes'], mac['per_job_seconds'], mac['memory_metric']) == (3 * GIB, 120, 'rss')
    lin = rl.resolve_limits(platform='linux', environ={}, total_memory=big)
    assert (lin['task_rss_bytes'], lin['per_job_seconds'], lin['memory_metric']) == (4 * GIB, 300, 'pss')
    env = {rl.ENV_MEMORY: '6144', rl.ENV_SECONDS: '600', rl.ENV_METRIC: 'rss'}
    from_env = rl.resolve_limits(platform='linux', environ=env, total_memory=big)
    assert (from_env['task_rss_bytes'], from_env['per_job_seconds'], from_env['memory_metric']) == (6 * GIB, 600, 'rss')
    assert from_env['source'] == {'task_rss_bytes': 'env', 'per_job_seconds': 'env', 'memory_metric': 'env'}
    cli = rl.resolve_limits(memory_mib=5120, timeout_seconds=200, memory_metric='pss', platform='linux', environ=env, total_memory=big)
    assert (cli['task_rss_bytes'], cli['per_job_seconds'], cli['memory_metric']) == (5 * GIB, 200, 'pss')
    assert cli['max_total_fraction'] == 0.5


def test_default_clamped_to_quarter_of_host_and_explicit_limit_checked():
    small = 12 * GIB
    lin = rl.resolve_limits(platform='linux', environ={}, total_memory=small)
    assert lin['task_rss_bytes'] == 3 * GIB and lin['clamped_to_host_fraction']
    assert rl.resolve_limits(memory_mib=6144, platform='linux', environ={}, total_memory=small)['task_rss_bytes'] == 6 * GIB
    with pytest.raises(rl.ResourceLimitError, match='exceeds_host_authorization'):
        rl.resolve_limits(memory_mib=7000, platform='linux', environ={}, total_memory=small)


@pytest.mark.parametrize('kwargs,match', [
    ({'memory_mib': 100}, 'out_of_bounds'), ({'timeout_seconds': 5}, 'out_of_bounds'),
    ({'memory_metric': 'vms'}, 'invalid_memory_metric'), ({'memory_mib': 'lots'}, 'invalid_memory_mib')])
def test_invalid_limits_are_rejected(kwargs, match):
    with pytest.raises(rl.ResourceLimitError, match=match):
        rl.resolve_limits(platform='linux', environ={}, total_memory=64 * GIB, **kwargs)


def test_resource_contract_validation_and_backend_timeouts():
    assert rl.validate_resource_contract(dict(rl.LEGACY_CONTRACT)) == rl.LEGACY_CONTRACT
    rl.validate_resource_contract({'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'concurrency': 1, 'memory_metric': 'pss'})
    for bad in ({'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'concurrency': 2}, None,
                {'task_rss_bytes': 4 * GIB, 'per_job_seconds': 300, 'concurrency': 1, 'extra': 1}):
        with pytest.raises(ValueError):
            rl.validate_resource_contract(bad)
    assert rl.backend_timeouts(120) == {'timeout': 110, 'openai_timeout': 90}
    assert rl.backend_timeouts(300) == {'timeout': 290, 'openai_timeout': 270}


# ---------- bounded execution receipts ----------

def test_bounded_failure_receipt_keeps_real_message(tmp_path):
    from bounded_execution import run_bounded
    outcome = run_bounded([sys.executable, '-c', 'pass', None], cwd=tmp_path, receipt_dir=tmp_path / 'r',
                          operation='none-arg', timeout_seconds=30, rss_limit=512 * 1024 ** 2)
    assert outcome['exception'] == 'TypeError'
    assert outcome['exception_message'] and 'NoneType' in outcome['exception_message']
    receipt = json.loads(Path(outcome['failure_receipt']).read_text())
    assert 'TypeError:' in json.dumps(receipt, ensure_ascii=False)


def test_pss_snapshot_not_larger_than_rss_sum():
    # 跨平台运行（原先在非 Linux 上 skip）：Linux 读真实 PSS；macOS/Windows 的 psutil 不提供 PSS，
    # 按设计逐进程回退为 RSS，因此任何平台上都应满足 0 < task_rss <= task_rss_sum。
    from bounded_execution import snapshot
    sample = snapshot([], metric='pss')
    assert sample['memory_metric'] == 'pss' and 0 < sample['task_rss'] <= sample['task_rss_sum']
    assert all(0 < row['pss'] <= row['rss'] for row in sample['processes'])
    if not sys.platform.startswith('linux'):
        assert sample['task_rss'] == sample['task_rss_sum']


# ---------- structured preflight ----------

def codes(result):
    return [f['code'] for f in result['findings']]


def test_clean_english_pdf_passes(tmp_path):
    result = inspect_pdf(make_pdf(tmp_path / 'en.pdf', pages=2), require_digital=True)
    assert result['status'] == 'ok' and result['error_code'] is None
    assert result['source_language']['language'] == 'en' and result['page_count'] == 2


def test_chinese_source_is_rejected_for_zh_target(tmp_path):
    result = inspect_pdf(make_pdf(tmp_path / 'zh.pdf', text=ZH, cjk=True), require_digital=True)
    assert result['error_code'] == 'source_language_matches_target'


def test_encrypted_permissions_truncated_and_not_pdf(tmp_path):
    user = make_pdf(tmp_path / 'user.pdf', encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='u', owner_pw='o', permissions=0)
    assert inspect_pdf(user)['error_code'] == 'encrypted_user_password_required'
    owner = make_pdf(tmp_path / 'owner.pdf', encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='o', permissions=0)
    restricted = inspect_pdf(owner)
    assert restricted['status'] == 'ok' and 'permissions_restricted' in restricted['warnings']
    truncated = tmp_path / 'truncated.pdf'
    truncated.write_bytes(make_pdf(tmp_path / 'full.pdf', pages=3).read_bytes()[:1500])
    assert inspect_pdf(truncated)['error_code'] == 'pdf_truncated_or_corrupt'
    (tmp_path / 'x.pdf').write_text('hello')
    assert inspect_pdf(tmp_path / 'x.pdf')['error_code'] == 'not_a_pdf'
    assert inspect_pdf(tmp_path / 'missing.pdf')['error_code'] == 'input_not_found'


def test_page_limit_and_non_digital_pages(tmp_path):
    long = inspect_pdf(make_pdf(tmp_path / 'long.pdf', pages=7))
    assert long['error_code'] == 'page_limit_exceeded'
    assert long['findings'][0]['details'] == {'page_count': 7, 'max_pages': 5}
    scan = make_scan(tmp_path / 'scan.pdf')
    assert inspect_pdf(scan, require_digital=True)['error_code'] == 'non_digital_pages'
    assert 'non_digital_pages' not in codes(inspect_pdf(scan, require_digital=False))


def test_detect_language():
    assert detect_language(EN)['language'] == 'en'
    assert detect_language(ZH)['language'] == 'zh'
    assert detect_language('x')['language'] == 'unknown'
    assert detect_language(ZH[:60] + EN[:400])['language'] == 'mixed'


# ---------- render residue ----------

def test_render_residue_flags_untranslated_output(tmp_path):
    source = make_pdf(tmp_path / 'src.pdf', pages=2)
    untranslated = check_render_residue(source, make_pdf(tmp_path / 'same.pdf', pages=2))
    assert untranslated['severity'] == 'high' and untranslated['quality_fail'] and untranslated['high_pages'] == [1, 2]
    translated = check_render_residue(source, make_pdf(tmp_path / 'zh.pdf', pages=2, text=ZH, cjk=True))
    assert translated['severity'] == 'ok' and not translated['quality_fail']


def test_qa_pipeline_residue_gate_writes_report(tmp_path):
    import qa_pipeline
    source = make_pdf(tmp_path / 'src.pdf')
    residue = qa_pipeline.render_residue_gate(source, make_pdf(tmp_path / 'same.pdf'), tmp_path)
    assert residue['severity'] == 'high' and (tmp_path / 'render_residue_check.json').is_file()
    assert '高风险' in qa_pipeline.render_residue_summary(residue)
    (tmp_path / 'missing').mkdir()
    missing = qa_pipeline.render_residue_gate(source, None, tmp_path / 'missing')
    assert missing['status'] == 'not_evaluated'


# ---------- workflow CLI (official entry point) ----------

def run_workflow(tmp_path, *argv):
    env = dict(os.environ, PAPER_TRANSLATION_WORKSPACE=str(tmp_path / 'ws'))
    proc = subprocess.run([sys.executable, str(SKILL / 'scripts/paper_translation_workflow.py'), *argv],
                          capture_output=True, text=True, env=env, timeout=180)
    return proc.returncode, json.loads(proc.stdout), proc.stderr


def test_inspect_input_without_catalog_url(tmp_path):
    pdf = make_pdf(tmp_path / 'en.pdf', pages=2)
    code, result, stderr = run_workflow(tmp_path, 'inspect-input', '--input', str(pdf),
                                        '--output', str(tmp_path / 'out/INPUT.json'), '--receipts', str(tmp_path / 'rc'))
    assert code == 0, stderr
    assert result['status'] == 'succeeded' and result['exception'] is None
    report = json.loads((tmp_path / 'out/INPUT.json').read_text())
    assert report['status'] == 'needs_source_review' and report['model_inventory']['status'] == 'not_configured'
    assert report['digital_route']['all_pages_native_text'] is True
    assert result['resource_limits']['memory_metric'] in ('rss', 'pss')


def test_inspect_input_reports_structured_error_codes(tmp_path):
    pdf = make_pdf(tmp_path / 'u.pdf', encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='u', owner_pw='o')
    code, result, _ = run_workflow(tmp_path, 'inspect-input', '--input', str(pdf),
                                   '--output', str(tmp_path / 'o1/INPUT.json'), '--receipts', str(tmp_path / 'r1'))
    assert code == 2 and result['status'] == 'blocked' and result['error_code'] == 'encrypted_user_password_required'
    pdf3 = make_pdf(tmp_path / 'three.pdf', pages=3)
    code, result, _ = run_workflow(tmp_path, 'inspect-input', '--input', str(pdf3),
                                   '--output', str(tmp_path / 'o2/INPUT.json'), '--receipts', str(tmp_path / 'r2'))
    assert code == 2 and result['error_code'] == 'page_limit_exceeded'
    assert 'digital_pdf' in result['findings'][0]['message']


@pytest.mark.parametrize('kind,expected', [('zh', 'source_language_matches_target'), ('long', 'page_limit_exceeded'),
                                           ('scan', 'non_digital_pages'), ('user', 'encrypted_user_password_required')])
def test_candidate_preflight_blocks_before_freeze_and_model(tmp_path, kind, expected):
    pdf = {'zh': lambda p: make_pdf(p, text=ZH, cjk=True), 'long': lambda p: make_pdf(p, pages=6), 'scan': make_scan,
           'user': lambda p: make_pdf(p, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='u', owner_pw='o')}[kind](tmp_path / 'in.pdf')
    (tmp_path / 'FREEZE.json').write_text('{}')
    code, result, stderr = run_workflow(tmp_path, 'candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'),
        '--receipts', str(tmp_path / 'rc'), '--freeze', str(tmp_path / 'FREEZE.json'), '--route', 'digital_pdf',
        '--model', 'm', '--base-url', 'http://127.0.0.1:9/v1')
    assert code == 2 and result['status'] == 'blocked' and result['error_code'] == expected, stderr
    assert 'Traceback' not in stderr
    assert json.loads((tmp_path / 'rc/WORKFLOW_INPUT_PREFLIGHT.json').read_text())['error_code'] == expected


def test_candidate_invalid_freeze_is_structured(tmp_path):
    pdf = make_pdf(tmp_path / 'en.pdf')
    (tmp_path / 'FREEZE.json').write_text('{}')
    code, result, stderr = run_workflow(tmp_path, 'candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'),
        '--receipts', str(tmp_path / 'rc'), '--freeze', str(tmp_path / 'FREEZE.json'), '--route', 'digital_pdf',
        '--model', 'm', '--base-url', 'http://127.0.0.1:9/v1')
    assert code == 2 and result['error_code'] == 'input_or_contract_invalid' and 'Traceback' not in stderr


def test_invalid_resource_flag_is_structured(tmp_path):
    pdf = make_pdf(tmp_path / 'en.pdf')
    code, result, _ = run_workflow(tmp_path, 'inspect-input', '--input', str(pdf), '--output', str(tmp_path / 'o.json'),
                                   '--receipts', str(tmp_path / 'rc'), '--task-memory-mib', '10')
    assert code == 2 and result['error_code'] == 'resource_limit_invalid'


def test_validate_freeze_page_scope_uses_error_code(tmp_path):
    import paper_translation_workflow as wf
    pdf = make_pdf(tmp_path / 'en.pdf')
    with pytest.raises(PreflightError) as info:
        wf.validate_freeze({'input': wf.ref(pdf), 'pages': list(range(1, 7))}, pdf, 'digital_pdf', 'm')
    assert info.value.code == 'page_limit_exceeded'


def test_versions_are_unified():
    skill = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
    version = skill.split('version: "', 1)[1].split('"', 1)[0]
    routes = json.loads((SKILL / 'configs/default-routes.json').read_text(encoding='utf-8'))
    from scanned_raster.constants import SKILL_VERSION
    changelog = (SKILL / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert routes['candidate_version'] == version == SKILL_VERSION
    assert changelog.split('\n## ', 1)[1].startswith(version)


# ---------- candidate exit codes: quality fail -> 3, pass/warn -> 0, preflight block -> 2 ----------

def _fake_backend(monkeypatch, wf, translated):
    """替换重任务子进程：照常写出译文与 QA 产物（残留检查用真实实现），其余入口逻辑保持真实。"""
    import qa_pipeline
    import bounded_execution

    def fake_run_bounded(command, **kwargs):
        if kwargs.get('operation') == 'input-preflight':  # 输入预检仍走真实有界子进程
            return bounded_execution.run_bounded(command, **kwargs)
        out = Path(command[command.index('--output') + 1])
        source = Path(command[command.index('--input') + 1])
        out.mkdir(parents=True)
        mono = out / 'in.no_watermark.zh.mono.pdf'
        with fitz.open(source) as src_doc:
            pages = src_doc.page_count
        make_pdf(mono, pages=pages, text=ZH, cjk=True) if translated else make_pdf(mono, pages=pages)
        residue = qa_pipeline.render_residue_gate(source, mono, out)
        issues = []
        if residue['severity'] == 'high':
            issues.append({'id': 'render_english_residue', 'rule': 'render_english_residue_high', 'severity': 'high',
                           'pages': residue['high_pages'], 'overall_residue_ratio': residue['overall_residue_ratio']})
        status = 'fail' if issues else 'warn'
        (out / 'comprehensive_quality.json').write_text(json.dumps({'status': status, 'issues': issues}))
        (out / 'render_manifest.json').write_text(json.dumps({
            'quality_status': status, 'outputs': {'translated_pdf': str(mono), 'mono_pdf': str(mono)},
            'render_residue': {k: residue.get(k) for k in ('severity', 'overall_residue_ratio', 'high_pages', 'medium_pages')}}))
        return {'status': 'succeeded', 'command': {'stdout_summary': {'excerpt': ''}}}

    monkeypatch.setattr(wf, 'run_bounded', fake_run_bounded)
    monkeypatch.setattr(wf, 'validate_freeze', lambda *a, **k: [1])
    monkeypatch.setattr(wf, 'doctor', lambda *a, **k: {'blockers': [], 'latex_ready': True})
    monkeypatch.setattr(wf, 'candidate_command', lambda args, freeze: [
        sys.executable, 'run_pdf_translation.py', '--input', str(args.input), '--output', str(args.output)])


def _candidate_main(tmp_path, wf, pdf, capsys):
    (tmp_path / 'FREEZE.json').write_text(json.dumps({'resource_contract': {
        'task_rss_bytes': 3 * GIB, 'per_job_seconds': 120, 'concurrency': 1}}))
    code = wf.main(['candidate', '--input', str(pdf), '--output', str(tmp_path / 'out'), '--receipts', str(tmp_path / 'rc'),
                    '--freeze', str(tmp_path / 'FREEZE.json'), '--route', 'digital_pdf', '--model', 'm',
                    '--base-url', 'http://127.0.0.1:9/v1', '--lock-path', str(tmp_path / 'wf.lock')])
    return code, json.loads(capsys.readouterr().out)


def test_candidate_quality_fail_exits_3_with_outputs_and_reasons(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    _fake_backend(monkeypatch, wf, translated=False)
    code, result = _candidate_main(tmp_path, wf, make_pdf(tmp_path / 'in.pdf', pages=2), capsys)
    assert code == wf.EXIT_QUALITY_FAIL == 3
    assert result['status'] == 'succeeded' and result['quality_status'] == 'fail' and result['exit_code'] == 3
    assert result['outputs_written'] is True and result['output_files'] == ['in.no_watermark.zh.mono.pdf']
    assert (tmp_path / 'out/in.no_watermark.zh.mono.pdf').is_file()
    reason = result['quality_fail_reasons'][0]
    assert reason['id'] == 'render_english_residue' and reason['severity'] == 'high' and reason['pages'] == [1, 2]
    assert [p['page'] for p in reason['page_levels']] == [1, 2] and all(p['severity'] == 'high' for p in reason['page_levels'])
    assert reason['thresholds']['page_high'] == 0.6
    assert 'render_english_residue(high) pages [1, 2]' in result['quality_fail_summary']
    receipt = json.loads((tmp_path / 'rc/WORKFLOW_CANDIDATE.json').read_text())
    assert receipt['quality_fail_reasons'] == result['quality_fail_reasons']


def test_candidate_quality_pass_or_warn_exits_0(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    _fake_backend(monkeypatch, wf, translated=True)
    code, result = _candidate_main(tmp_path, wf, make_pdf(tmp_path / 'in.pdf', pages=2), capsys)
    assert code == 0 and result['quality_status'] == 'warn' and result['render_residue']['severity'] == 'ok'
    assert 'quality_fail_reasons' not in result and 'exit_code' not in result


def test_candidate_preflight_block_still_exits_2(tmp_path, monkeypatch, capsys):
    import paper_translation_workflow as wf
    _fake_backend(monkeypatch, wf, translated=False)
    code, result = _candidate_main(tmp_path, wf, make_pdf(tmp_path / 'in.pdf', text=ZH, cjk=True), capsys)
    assert code == wf.EXIT_BLOCKED == 2 and result['error_code'] == 'source_language_matches_target'
    assert not (tmp_path / 'out').exists()
