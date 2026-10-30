"""PR #25 review-11：预检拒绝提示里的执行入口命令保留已请求的目标语言（中译英 en / 默认英译中 zh 成对）。

只给接受 ``--target-language`` 的入口（chunked-candidate、candidate --route scanned_ocr）带上该参数；
inspect-input、prepare-scan 不接受，不加。目标语言未知或与预检冲突时不给提示（不猜）。
按提示列出的参数真实调用入口（空 FREEZE、回环关闭端口 127.0.0.1:9），只到语言预检与 FREEZE 校验，不翻译、不调模型。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))

import paper_translation_workflow as wf  # noqa: E402

SCRIPT = SKILL / 'scripts/paper_translation_workflow.py'
ZH = '本研究分析长文本推理过程中的训练方法，比较不同网络参数和实验结果。模型通过输入数据更新内部状态，研究人员使用统一的评价标准进行测试。' * 10
EN = ('Test-time training adapts model weights during inference so that the network can store '
      'long context in fast weights. We evaluate the approach on language modeling and view synthesis. ') * 6
SOURCE_FOR = {'en': 'zh', 'zh': 'en'}


def text_pdf(path, source, pages=6):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if source == 'zh':
            page.insert_textbox(fitz.Rect(40, 40, 550, 800), ZH, fontname='china-s', fontsize=10)
        else:
            page.insert_textbox(fitz.Rect(50, 50, 545, 790), EN, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def scan_pdf(path):
    src = fitz.open()
    page = src.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 545, 790), EN, fontsize=10)
    pix = page.get_pixmap(dpi=60)
    doc = fitz.open()
    out = doc.new_page(width=page.rect.width, height=page.rect.height)
    out.insert_image(out.rect, pixmap=pix)
    doc.save(path)
    return path


def env_for(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ('LOCAL_TRANSLATION_API_KEY', 'OPENAI_API_KEY', 'PDF2ZH_OPENAI_API_KEY', 'PDF2ZH_DEBUG')}
    (tmp_path / 'ws').mkdir(exist_ok=True)
    env.update(PAPER_TRANSLATION_WORKSPACE=str(tmp_path / 'ws'), PYTHONDONTWRITEBYTECODE='1')
    return env


def run(tmp_path, argv):
    proc = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True,
                          env=env_for(tmp_path), timeout=60)
    assert 'Traceback' not in proc.stderr, proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def candidate(tmp_path, pdf, target=None, route='digital_pdf', name='cand'):
    (tmp_path / 'FREEZE.json').write_text('{}')
    d = tmp_path / name
    argv = ['candidate', '--input', str(pdf), '--freeze', str(tmp_path / 'FREEZE.json'), '--route', route,
            '--model', 'agent-self', '--base-url', 'http://127.0.0.1:9/v1', '--output', str(d / 'out'),
            '--receipts', str(d / 'rc'), '--lock-path', str(d / 'heavy.lock')]
    if target:
        argv += ['--target-language', target]
    code, result = run(tmp_path, argv)
    receipt = json.loads((d / 'rc/WORKFLOW_INPUT_PREFLIGHT.json').read_text())
    assert code == 2 and not (d / 'out').exists()
    assert result.get('guidance') == receipt.get('guidance') and ('guidance' in result) == ('guidance' in receipt)
    assert result['findings'] == receipt['findings'] and result['error_code'] == receipt['error_code']
    return result, receipt


def listed_argv(step, tmp_path, pdf, name):
    """把提示里列出的命令按原参数取出，占位符替换为本测试的新路径/空 FREEZE/关闭端口；不增删任何参数。"""
    body = step.split('paper_translation_workflow.py ', 1)[1]
    body = re.split('[；…。]', body, maxsplit=1)[0]
    tokens = re.findall(r'<[^>]*>|\S+', body)
    d = tmp_path / name
    dirs = iter([str(d / 'out'), str(d / 'rc')])
    mapping = {'<PDF>': str(pdf), '<新 FREEZE.json>': str(tmp_path / 'FREEZE.json'), '<model>': 'agent-self',
               '<endpoint>': 'http://127.0.0.1:9/v1', '<新报告.json>': str(d / 'out/INPUT_PREFLIGHT.json')}
    argv = [mapping[t] if t in mapping else next(dirs) if t == '<新目录>' else t for t in tokens]
    assert not any(a.startswith('<') for a in argv), argv
    return tokens, argv + ['--lock-path', str(d / 'heavy.lock')]


def help_text(tmp_path, action):
    proc = subprocess.run([sys.executable, str(SCRIPT), action, '--help'], capture_output=True, text=True,
                          env=env_for(tmp_path), timeout=60)
    assert proc.returncode == 0
    return proc.stdout


def test_entry_argparse_target_language_support(tmp_path):
    """提示只给 argparse 实际接受该参数的入口加 --target-language。"""
    assert '--target-language' in help_text(tmp_path, 'candidate')
    assert '--target-language' in help_text(tmp_path, 'chunked-candidate')


# ---------- 长文档：zh->en 与默认 en->zh 成对 ----------

@pytest.mark.parametrize('target', ['en', 'zh', None])
def test_long_document_listed_chunked_command_keeps_direction_and_passes_language_gate(tmp_path, target):
    requested = target or 'zh'  # argparse 默认 zh（未改）
    pdf = text_pdf(tmp_path / 'six.pdf', SOURCE_FOR[requested])
    result, receipt = candidate(tmp_path, pdf, target)
    assert result['error_code'] == 'page_limit_exceeded' and result['page_count'] == 6
    g = result['guidance']
    assert g['route_hint'] == 'chunked-candidate' and g['target_language'] == requested
    verify, _, chunked = g['next_steps']
    assert f'--route digital_pdf --target-language {requested} --model' in chunked
    assert 'inspect-input' not in verify and 'chunked-candidate（带' in verify
    # 按所列参数真实调用分块入口：语言预检通过（源语言与目标相反），再因空 FREEZE 拒绝。
    tokens, argv = listed_argv(chunked, tmp_path, pdf, 'chunked')
    assert tokens[0] == 'chunked-candidate' and tokens.count('--target-language') == 1
    code, out = run(tmp_path, argv)
    pre = json.loads((tmp_path / 'chunked/rc/invocation-1/WORKFLOW_INPUT_PREFLIGHT.json').read_text())
    assert pre['status'] == 'ok' and pre['target_language'] == requested
    assert pre['source_language']['language'] == SOURCE_FOR[requested]
    assert code == 2 and out['error_code'] == 'input_or_contract_invalid', out
    assert not list((tmp_path / 'chunked/out').rglob('*.pdf'))


def test_zh_to_en_listed_command_without_language_would_fall_back_and_be_refused(tmp_path):
    """对照：同一中文长文档若去掉所列的 --target-language en，真实分块入口按默认 zh 以 source_language_matches_target 拒绝。"""
    pdf = text_pdf(tmp_path / 'six.pdf', 'zh')
    result, _ = candidate(tmp_path, pdf, 'en')
    _, argv = listed_argv(result['guidance']['next_steps'][2], tmp_path, pdf, 'stripped')
    i = argv.index('--target-language')
    del argv[i:i + 2]
    code, out = run(tmp_path, argv)
    assert code == 2 and out['error_code'] == 'source_language_matches_target'


def test_explicit_zh_and_default_give_identical_guidance(tmp_path):
    pdf = text_pdf(tmp_path / 'six.pdf', 'en')
    default, _ = candidate(tmp_path, pdf, None, name='d')
    explicit, _ = candidate(tmp_path, pdf, 'zh', name='e')
    assert default['guidance'] == explicit['guidance']


# ---------- 扫描提示：en 与 zh ----------

@pytest.mark.parametrize('target', ['en', 'zh'])
def test_scan_pages_get_no_route_hint_in_public_build(tmp_path, target):
    pdf = scan_pdf(tmp_path / 'scan.pdf')
    result, receipt = candidate(tmp_path, pdf, target)
    assert result['error_code'] == 'non_digital_pages'
    g = result['guidance']
    assert g['route_hint'] is None and g['target_language'] == target
    assert g['eligibility'] == 'non_digital_pages_unsupported' and g['next_steps'] == []
    assert '仅支持原生电子 PDF' in g['message']


# ---------- 未知或冲突的目标语言：不猜 ----------

LONG = wf.finding('page_limit_exceeded', page_count=6, max_pages=5)
SCAN = wf.finding('non_digital_pages', pages=[{'page': 1, 'kind': 'scanned_image'}])


@pytest.mark.parametrize('finding_,count', [(LONG, 6), (SCAN, 1)])
@pytest.mark.parametrize('requested,reported', [(None, 'zh'), ('fr', 'fr'), ('', 'zh'), ('EN', 'en'),
                                                ('en', 'zh'), ('zh', 'en'), ('en', None)])
def test_unknown_or_conflicting_target_language_gets_no_guidance(finding_, count, requested, reported):
    report = wf.blocked_result([finding_], page_count=count, target_language=reported)
    assert wf.input_preflight_guidance(report, 'candidate', 'digital_pdf', requested) is None


@pytest.mark.parametrize('target', ['en', 'zh'])
def test_consistent_target_language_guidance_pair(target):
    report = wf.blocked_result([LONG], page_count=6, target_language=target)
    g = wf.input_preflight_guidance(report, 'candidate', 'digital_pdf', target)
    assert g['target_language'] == target and f'--target-language {target} ' in g['next_steps'][2]
    other = {'en': 'zh', 'zh': 'en'}[target]
    assert f'--target-language {other}' not in json.dumps(g, ensure_ascii=False)
