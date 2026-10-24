# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""有限 LaTeX/电子 PDF 的正式工作流；生成、审校与用户验收分别登记。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request

from bounded_execution import run_bounded, snapshot
import failure_root_cause
from cutover.scoped import check_scoped_preflight, sha
from pdf_input_preflight import DIGITAL_MAX_PAGES, PreflightError, blocked_result, finding, inspect_pdf
from resource_limits import (ResourceLimitError, backend_timeouts, limits_from_frozen_contract, recommended_contract,
                             resolve_limits, validate_resource_contract)

SCRIPT_DIR = Path(__file__).resolve().parent
from runtime_paths import workspace_root
ROOT = workspace_root()
PROJECT = ROOT / 'projects/paper-translation'
MODEL = None
ROUTES = {'digital_pdf': 'pdf_backend', 'latex_verified': 'latex_direct', 'scanned_ocr': 'ocr_reconstruct_pdf_backend'}
DIGITAL_ROUTING = {'selection':'explicit_pdf_backend_only','complete_native_pages_required':True,
                   'latex_discovery':'disabled','scan_or_mixed':'rejected'}
# 扫描/混合 PDF 的常规 OCR 路线（rc.8）：只接受受支持版式；OCR 重建源随后走同一电子 PDF 后端与全部质量门。
OCR_ROUTING = {'selection':'explicit_scanned_ocr','engine':'tesseract_cli','scan_or_mixed':'ocr_supported_pages_only',
               'unsupported_layouts':'rejected','latex_discovery':'disabled','backend':'pdf_backend_on_reconstructed_source'}
PDF_BACKEND_ROUTES = ('digital_pdf', 'scanned_ocr')
# 长文档分块（rc.9）：parent FREEZE 声明整份页数 + 冻结分块合同；每块派生自己的 FREEZE 走上面两条既有路线之一。
CHUNK_ROUTES = ('digital_pdf', 'scanned_ocr', 'per_chunk')
PER_CHUNK_ROUTING = {'selection':'per_chunk_explicit','native_text_pages':'digital_pdf','scanned_pages':'scanned_ocr',
                     'sparse_pages':'attach_to_neighbour_run','digital':DIGITAL_ROUTING,'scanned':OCR_ROUTING}


class BackendFailure(ValueError):
    """PDF 后端没有产出候选：携带本尝试结构化产物给出的根因（稳定原因码 + 细节）与根因回执引用。"""

    def __init__(self, root_cause, receipt_ref):
        super().__init__(root_cause.get('code') or failure_root_cause.UNAVAILABLE)
        self.root_cause, self.receipt_ref = root_cause, receipt_ref


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path)}


def bound_json(value):
    path = Path(value['path'])
    if not path.is_file() or sha(path) != value['sha256']:
        raise ValueError('frozen evidence changed')
    return read_json(path)


@contextmanager
def project_lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('project heavy task already running') from exc
        yield


def doctor(base_url, model=MODEL, provider_generation_required=True, include_ocr=False):
    """只检查首发必需项；扫描/OCR依赖不参与首发阻塞。"""
    dependencies = {name: importlib.util.find_spec(name) is not None
                    for name in ('fitz', 'psutil', 'PIL', 'requests', 'pdf2zh_next', 'babeldoc')}
    blockers = [f'missing_dependency:{name}' for name, present in dependencies.items() if not present]
    models = []
    from credential_env import CREDENTIAL_ENV, REMOTE_REQUIRES_KEY, credential_source, is_loopback_endpoint
    # 与运行入口同一来源：只读 LOCAL_TRANSLATION_API_KEY（不再静默采用 OPENAI_API_KEY）；只报告来源，不记录值。
    credential = credential_source(os.environ)
    api_key = os.environ.get(CREDENTIAL_ENV) or None
    if provider_generation_required and not api_key and not is_loopback_endpoint(base_url):
        blockers.append(REMOTE_REQUIRES_KEY)
    elif provider_generation_required:
        try:
            headers = {'Authorization': 'Bearer ' + api_key} if api_key else {}
            request = urllib.request.Request(base_url.rstrip('/') + '/models', headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.load(response)
            models = sorted(row['id'] for row in payload.get('data', []) if isinstance(row.get('id'), str))
            if model not in models:
                blockers.append('configured_model_not_available')
        except (OSError, ValueError, KeyError) as exc:
            blockers.append('model_endpoint_unavailable:' + type(exc).__name__)
    memory = snapshot([])
    if any(row['rss'] >= 20 * 1024**3 for row in memory['codex']):
        blockers.append('codex_memory_fuse')
    return {'schema_version': 1, 'status': 'ready' if not blockers else 'blocked',
            'blockers': blockers, 'dependencies': dependencies,
            'latex_compiler': shutil.which('xelatex'), 'latex_ready': bool(shutil.which('xelatex')),
            'model': model, 'available_model_ids': models,
            'model_identity': 'served model ID only; weight/provider fingerprint requires separate frozen evidence',
            'scan_dependencies_required': False, 'model_calls': 0,
            'provider_generation_required':provider_generation_required,
            'credential': credential,
            'resources': {key: memory[key] for key in ('total', 'available', 'swap_used', 'codex')},
            'supported_routes': list(ROUTES),
            'recommended_resource_contract': recommended_contract(),
            **({'ocr_engine': ocr_engine_status()} if include_ocr else {})}


def ocr_engine_status():
    """OCR 路线依赖（仅信息）：缺失只影响 --route scanned_ocr，不进入 doctor 阻断项。"""
    from ocr_route import engine_info
    info = engine_info()
    return {k: info.get(k) for k in ('engine', 'available', 'version', 'languages', 'missing', 'tessdata_dir', 'traineddata')} | {
        'blocks_routes': ['scanned_ocr'] if not info.get('available') else [], 'blocks_digital_route': False}


def validate_freeze(freeze, input_pdf, route, model, *, chunked=False):
    if route not in ROUTES and not (chunked and route == 'per_chunk'):
        raise ValueError('route outside limited first release')
    if chunked and route == 'latex_verified':
        raise ValueError('chunked translation supports digital_pdf, scanned_ocr and per_chunk only')
    if freeze.get('input') != ref(input_pdf):
        raise ValueError('input identity changed')
    pages = freeze.get('pages')
    if chunked:
        from chunked_translation import CHUNKING_CONTRACT
        if freeze.get('chunking_contract') != CHUNKING_CONTRACT:
            raise ValueError('frozen chunking contract missing or changed')
        limit = CHUNKING_CONTRACT['max_document_pages']
        if not isinstance(pages, list) or pages != list(range(1, len(pages) + 1)) or not 1 <= len(pages) <= limit:
            raise PreflightError('page_limit_exceeded', f'分块 FREEZE.pages 必须是从 1 开始的完整连续 1–{limit} 页。',
                                 declared_pages=len(pages) if isinstance(pages, list) else None, max_pages=limit)
        closure = {str(Path(e.get('path', '')).resolve()) for e in freeze.get('implementation_refs') or [] if isinstance(e, dict)}
        if str((SCRIPT_DIR / 'chunked_translation.py').resolve()) not in closure:
            raise ValueError('frozen implementation closure must include chunked_translation.py')
        if freeze.get('source_cache_contract'):
            raise ValueError('source cache contracts are not supported by chunked translation')
    elif not isinstance(pages, list) or pages != list(range(1, len(pages) + 1)) or not 1 <= len(pages) <= DIGITAL_MAX_PAGES:
        raise PreflightError('page_limit_exceeded', 'FREEZE.pages 必须是从 1 开始的完整连续 1–5 页。',
                             declared_pages=pages if isinstance(pages, list) and len(pages) <= 50 else None,
                             max_pages=DIGITAL_MAX_PAGES)
    if freeze.get('complete_semantic_scope') is not True or not freeze.get('scope_evidence'):
        raise ValueError('complete semantic scope evidence required')
    if freeze.get('route') != route or freeze.get('model') != model:
        raise ValueError('route or model differs from freeze')
    if route=='digital_pdf' and freeze.get('routing_contract')!=DIGITAL_ROUTING:
        raise ValueError('frozen explicit digital routing contract differs')
    if route=='scanned_ocr' and (freeze.get('routing_contract')!=OCR_ROUTING or freeze.get('source_cache_contract')):
        raise ValueError('frozen explicit scanned OCR routing contract differs')
    if route=='per_chunk' and freeze.get('routing_contract')!=PER_CHUNK_ROUTING:
        raise ValueError('frozen per-chunk routing contract differs')
    if route=='digital_pdf' and freeze.get('source_cache_contract'):
        from pdf_source_cache import CONTRACT, GROUP_CONTRACT, REVISION_CONTRACT, RENDER_INVOCATION_PROTOCOL
        declared=freeze['source_cache_contract']
        contracts={c['protocol']:c for c in (CONTRACT,GROUP_CONTRACT,REVISION_CONTRACT)}
        expected=contracts.get(declared.get('protocol'))
        if expected is None:raise ValueError('unknown source cache frozen protocol')
        if declared!=expected or bound_json(freeze['source_cache_policy_ref']).get('protocol')!=expected['protocol']:
            raise ValueError('source cache frozen contract changed')
        if expected in (GROUP_CONTRACT,REVISION_CONTRACT) and bound_json(freeze['render_invocation_policy_ref']).get('protocol')!=RENDER_INVOCATION_PROTOCOL:
            raise ValueError('actual group render invocation policy differs')
    if route in PDF_BACKEND_ROUTES or route == 'per_chunk':
        api_contract=bound_json(freeze['model_fingerprint_ref']).get('api_contract')
        if api_contract not in (None,'lmstudio_native_chat_v1'):raise ValueError('unknown frozen API contract')
        expected_proxy = 'source_bound_native' if api_contract else ('hymt_compat' if 'hy-mt' in model.lower() else 'none')
        if freeze.get('proxy_quality_contract') != {'adapter':expected_proxy,'required':expected_proxy!='none'}:
            raise ValueError('frozen proxy quality applicability missing or changed')
    # 资源合同只约束边界与并发 1；实际上限由 --task-memory-mib/--job-timeout-seconds、环境变量或平台默认值决定。
    validate_resource_contract(freeze.get('resource_contract'))
    fingerprint=bound_json(freeze['model_fingerprint_ref'])
    if fingerprint.get('model_id') != model:
        raise ValueError('model fingerprint identity changed')
    bound_json(freeze['scope_evidence'])
    environment = freeze.get('backend_environment', {})
    if set(environment) - {'BABELDOC_ONNX_PROVIDER', 'PAPER_TRANSLATION_ENGINE_HOME'} or environment.get('BABELDOC_ONNX_PROVIDER', 'cpu') != 'cpu':
        raise ValueError('unsupported frozen backend environment')
    if freeze.get('environment_assets_ref'):
        assets = bound_json(freeze['environment_assets_ref'])
        for evidence in assets.get('integrity_refs', []):
            if not Path(evidence['path']).is_file() or sha(evidence['path']) != evidence['sha256']:
                raise ValueError('frozen external runtime asset changed')
    for name in ('entrypoint','rules','standard'):
        evidence=freeze[name]
        if not Path(evidence['path']).is_file() or sha(evidence['path']) != evidence['sha256']:
            raise ValueError('frozen implementation or standard changed:' + name)
    implementations = freeze.get('implementation_refs')
    if not implementations:
        raise ValueError('frozen implementation closure required')
    for evidence in implementations:
        if not Path(evidence['path']).is_file() or sha(evidence['path']) != evidence['sha256']:
            raise ValueError('frozen implementation closure changed')
    if route == 'latex_verified':
        from independent_latex import TRANSPORT, PROTECTION_PROTOCOL
        if freeze.get('transport_contract') != TRANSPORT:
            raise ValueError('frozen LaTeX transport contract differs')
        if freeze.get('protection_protocol') != PROTECTION_PROTOCOL:
            raise ValueError('frozen LaTeX source atom protocol differs')
        policy=bound_json(freeze['protection_policy_ref'])
        if policy.get('protocol')!=PROTECTION_PROTOCOL:raise ValueError('source atom policy changed')
        if freeze.get('semantic_feedback_ref'):bound_json(freeze['semantic_feedback_ref'])
        source = freeze.get('latex_source')
        if not source or not Path(source['path']).is_file() or sha(source['path']) != source['sha256']:
            raise ValueError('trusted LaTeX source missing or changed')
    return pages


def job_limits(args):
    limits = getattr(args, 'resource_limits', None)
    return limits if limits else resolve_limits()


def candidate_command(args, freeze, input_pdf=None):
    timeouts = backend_timeouts(job_limits(args)['per_job_seconds'])
    command = [sys.executable, str(SCRIPT_DIR / 'run_pdf_translation.py'), str(Path(input_pdf or args.input).resolve()),
               '--output-dir', str(args.output.resolve()), '--model', args.model, '--base-url', args.base_url,
               '--local-max-concurrency', '1', '--timeout', str(timeouts['timeout']), '--openai-timeout', str(timeouts['openai_timeout']),
               '--latex-render-timeout', str(timeouts['timeout']), '--latex-translate-timeout', str(timeouts['openai_timeout']),
               '--latex-compile-timeout', '45', '--hymt-compat-proxy', 'auto', '--strict-delivery-gates']
    target_language = getattr(args, 'target_language', 'zh')
    if target_language != 'zh':
        # 只有非默认方向才追加参数，英译中命令行与既有回执保持逐字不变。
        command += ['--target-language', target_language]
    context = getattr(args, 'document_term_context', None)
    if context:
        # 分块翻译：整份文档术语上下文（每块 FREEZE 以 document_term_context_ref 绑定，_execute-digital 核对）。
        command += ['--document-term-context', str(Path(context).resolve()), '--document-term-context-sha256', sha(context)]
    if freeze.get('model_fingerprint_ref') and bound_json(freeze['model_fingerprint_ref']).get('api_contract')=='lmstudio_native_chat_v1':
        command+=['--translation-transport','lmstudio_native_chat_v1','--translator-mode','openai']
    if args.route == 'latex_verified':
        command += ['--source-override', freeze['latex_source']['path'], '--latex-render-mode', 'required',
                    '--skip-pdf-backend-when-latex-direct']
    elif args.route in PDF_BACKEND_ROUTES:command+=['--pdf-backend-only','--latex-render-mode','off']
    if args.smoke:
        if args.route == 'latex_verified':
            raise ValueError('LaTeX smoke requires a separately frozen complete source project')
        command += ['--pages', '1']
    return command


def run_job(args, command, operation, interval_seconds=2):
    limits = job_limits(args)
    with project_lock(args.lock_path):
        result = run_bounded(command, cwd=ROOT, receipt_dir=args.receipts / operation, operation=operation,
            timeout_seconds=limits['per_job_seconds'], interval_seconds=interval_seconds, rss_limit=limits['task_rss_bytes'], max_processes=8,
            deadline_monotonic=getattr(args,'task_deadline_monotonic',None),
            memory_metric=limits['memory_metric'], max_total_fraction=limits['max_total_fraction'],
            env={**os.environ, **getattr(args, 'frozen_environment', {}), 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
    result['resource_limits'] = limits
    if result.get('status') == 'cleanup_unconfirmed':
        # 停止后无法核实本任务进程树已全部退出：独立错误码，回执 cleanup.unverified 列出未核实对象。
        result.setdefault('error_code', 'owned_tree_cleanup_unconfirmed')
    elif result.get('status') == 'stopped' and result.get('stop_reason'):
        # 资源门/监控失败的结构化停止：稳定错误码即 stop_reason（如 owned_process_monitor_unavailable）。
        result.setdefault('error_code', result['stop_reason'])
    child = child_structured_result(result)
    if child:
        # 子任务以结构化 JSON 报告的预检/路由拒绝：上浮为 blocked，并保留错误码与发现。
        result.update(status='blocked', error_code=child.get('error_code'), findings=child.get('findings', []))
    else:
        attach_root_cause(result)
    return result


def attach_root_cause(result):
    """PDF 后端未产出候选（子任务结构化行带 root_cause_ref）：只采信本尝试输出目录内、身份（argv 的 --output-dir /
    --freeze、launch 回执 nonce）与 sha 逐项核对一致的根因回执；状态不变（仍是 failed），只补稳定原因码、
    结构化细节与回执引用。核对不了 → root_cause_unavailable（verified=False）。"""
    envelope = child_marker(result)
    if not envelope or 'root_cause_ref' not in envelope or result.get('status') != 'failed' or result.get('error_code'):
        return result
    cause = failure_root_cause.verify_for_result(result, envelope['root_cause_ref'])
    result.update(error_code=cause['code'], root_cause=cause,
                  findings=[finding(cause['code'], failure_root_cause.message(cause), stage=cause.get('stage'),
                                    retry=cause.get('retry'), verified=cause.get('verified'))])
    return result


def cap_ocr_quality(result):
    """OCR 文本未经人工核对：重建源的文字层不构成验收，综合质量最高为 unverified（fail 保持 fail）。"""
    if result.get('status') == 'blocked':
        return
    status = result.get('quality_status')
    result['ocr_text_layer_is_acceptance'] = False
    if status not in (None, 'fail', 'unverified'):
        result['quality_status_before_ocr_cap'] = status
        result['quality_status'] = 'unverified'
    result.setdefault('quality_pending', []).append({'id': 'ocr_text_unverified',
        'message': 'OCR 识别文本未经人工逐字核对；译文质量不因生成的文字层而被视为通过。'})


def run_scanned_ocr_candidate(args, freeze):
    """scanned_ocr：有界 OCR 重建（tesseract 子进程计入同一进程树计量与回收）→ 重建源电子预检 → 电子后端。
    OCR 与后端共享同一单任务时限（FREEZE 资源合同的 per_job_seconds）。任何不受支持的版式在模型调用前以退出码 2 拒绝。"""
    import ocr_route
    info = ocr_route.engine_info()
    engine = {k: info.get(k) for k in ('engine', 'version', 'available', 'missing', 'languages', 'traineddata', 'tessdata_dir')}
    if not info['available']:
        return dict(blocked_result([finding('ocr_engine_unavailable', ocr_route.CODES['ocr_engine_unavailable'],
                                            missing=info.get('missing'))]), ocr_stage='ocr_engine', ocr_engine=engine)
    limits = job_limits(args)
    if getattr(args, 'task_deadline_monotonic', None) is None:
        args.task_deadline_monotonic = time.monotonic() + limits['per_job_seconds']
    workdir = (args.receipts / 'ocr').resolve()
    target = getattr(args, 'target_language', 'zh')
    job = run_job(args, [sys.executable, str(SCRIPT_DIR / 'ocr_route.py'), '--input', str(args.input.resolve()),
                         '--workdir', str(workdir), '--target-language', target, '--tesseract', info['binary']],
                  'ocr-reconstruct', interval_seconds=0.5)
    manifest_path = workdir / 'OCR_MANIFEST.json'
    ocr = {'engine': engine, 'job': {k: job.get(k) for k in ('status', 'stop_reason', 'error_code', 'elapsed_seconds',
           'peak_task_memory_bytes', 'peak_task_rss_sum_bytes', 'rss_limit_bytes', 'memory_metric', 'resource_receipt',
           'observed_owned_identities', 'launch_identity')} | {'cleanup_status': (job.get('cleanup') or {}).get('status')},
           'manifest_ref': ref(manifest_path) if manifest_path.is_file() else None}
    if job.get('status') != 'succeeded':
        return dict(job, ocr_stage='ocr_reconstruct', ocr=ocr)
    if not manifest_path.is_file():
        raise ValueError('OCR reconstruction finished without its manifest')
    manifest = read_json(manifest_path)
    ocr['status'] = manifest['status']
    ocr['pages'] = [{k: row.get(k) for k in ('page', 'kind', 'source_image_dpi', 'mean_word_conf', 'lines', 'osd', 'skew_degrees',
                     'ruling_lines', 'tabular_lines', 'background_residue', 'reconstructed_page', 'text_line_count',
                     'low_confidence_lines_written', 'refined_rows')} for row in manifest.get('pages', [])]
    ocr['tesseract_processes'] = manifest.get('processes', [])
    if manifest['status'] != 'ok':
        return dict(blocked_result(manifest['findings']), ocr_stage='ocr_reconstruct', ocr=ocr)
    rebuilt = Path(manifest['reconstructed_source']['path'])
    ocr['reconstructed_source_ref'] = ref(rebuilt)
    report = bounded_input_preflight(rebuilt, args.receipts / 'reconstructed-input', require_digital=True, target_language=target)
    ocr['reconstructed_preflight'] = {k: report.get(k) for k in ('status', 'error_code', 'warnings', 'source_language', 'page_count')}
    if report['status'] == 'blocked':
        return dict(report, ocr_stage='ocr_reconstructed_preflight', ocr=ocr)
    command = candidate_command(args, freeze, input_pdf=rebuilt)
    result = run_job(args, [sys.executable, str(Path(__file__)), '_execute-digital', '--freeze', str(args.freeze.resolve()),
                            '--ocr-manifest', str(manifest_path), '--ocr-manifest-sha256', sha(manifest_path),
                            '--', *command[2:]], 'candidate')
    result['ocr'] = ocr
    result['ocr_stage'] = 'pdf_backend'
    return result


def run_chunked_candidate(args):
    """长文档分块（rc.9）：编排见 chunked_workflow.py；每块是一次普通 candidate。"""
    import chunked_workflow
    return chunked_workflow.run(args, sys.modules[__name__])


CHILD_RESULT_MARKER = 'PAPER_TRANSLATION_STRUCTURED_RESULT '
EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_QUALITY_FAIL = 0, 1, 2, 3
# FREEZE 绑定的动作：冻结的 resource_contract 是唯一权威预算（见 resource_limits.limits_from_frozen_contract）。
FREEZE_BOUND_ACTIONS = {'candidate', 'collect', 'resume-latex', 'chunked-candidate'}
# 输入预检子进程自身的有界预算：只读、最多解析 5 页，不需要作业级预算。
PREFLIGHT_RSS_BYTES = 1536 * 1024 ** 2
PREFLIGHT_SECONDS = 60


def frozen_limits(args, freeze):
    return limits_from_frozen_contract(freeze.get('resource_contract'), memory_mib=getattr(args, 'task_memory_mib', None),
        timeout_seconds=getattr(args, 'job_timeout_seconds', None), memory_metric=getattr(args, 'memory_metric', None))


def quality_verdict(output_dir, manifest=None):
    """综合质量结论（任何路线）：comprehensive_quality.json 为准，其次 render_manifest 的 quality_status。"""
    output_dir = Path(output_dir)
    if manifest is None:
        manifest_path = output_dir / 'render_manifest.json'
        manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    quality_path = output_dir / 'comprehensive_quality.json'
    quality = read_json(quality_path) if quality_path.is_file() else {}
    status = quality.get('status') or manifest.get('quality_status')
    if not status:
        return {}
    verdict = {'quality_status': status, 'quality_source': 'comprehensive_quality.json' if quality.get('status')
               else 'render_manifest.json'}
    if manifest.get('render_residue') is not None:
        verdict['render_residue'] = manifest['render_residue']
    # 原文保留降级（overflow_source_fallback）与参考文献剔除计数：单份取回执字段，分块取汇总。
    fallback_count = quality.get('overflow_source_fallback_count')
    if fallback_count is None:
        fallback_count = (quality.get('overflow_source_fallback_check') or {}).get('count')
    if fallback_count is None:
        fallback_count = manifest.get('overflow_source_fallback_count')
    if fallback_count is not None:
        verdict['overflow_source_fallback_count'] = fallback_count
    reference_exclusion = quality.get('reference_exclusion') or manifest.get('reference_exclusion')
    if reference_exclusion:
        verdict['reference_exclusion'] = reference_exclusion
    # 公式上/下标层级门与可读版数学保真结论（拒绝时带稳定 reason_code）。
    structure = quality.get('formula_structure_check')
    if isinstance(structure, dict) and structure.get('status'):
        verdict['formula_structure'] = {k: structure.get(k) for k in ('status', 'severity', 'lost', 'flagged_pages')}
    readable = quality.get('readable_output')
    if isinstance(readable, dict) and readable.get('status'):
        verdict['readable_output'] = {k: readable.get(k) for k in ('status', 'reason_code', 'vector_pages')}
    if status == 'fail':
        verdict.update(quality_gate_failure(output_dir, manifest))
    return verdict


def quality_output_dirs(args, result):
    dirs = []
    output = getattr(args, 'output', None)
    if output:
        dirs += [Path(output), Path(output) / 'render']
    candidate = (result.get('candidate_ref') or {}).get('path') if isinstance(result.get('candidate_ref'), dict) else None
    if candidate:
        dirs.append(Path(candidate).parent)
    return dirs


def quality_gate_failure(output_dir, manifest):
    """QA 判 fail 时的结构化原因：哪些检查、哪些页、残留等级；译文文件照常保留。"""
    output_dir = Path(output_dir)
    quality_path = output_dir / 'comprehensive_quality.json'
    quality = read_json(quality_path) if quality_path.is_file() else {}
    issues = [i for i in quality.get('issues', []) if isinstance(i, dict)]
    blocking = [i for i in issues if i.get('severity') in {'high', 'critical', 'blocker'}] or issues
    reasons = []
    for issue in blocking:
        reason = {k: issue[k] for k in ('id', 'rule', 'severity', 'pages', 'overall_residue_ratio', 'message') if k in issue}
        reason.setdefault('id', issue.get('rule') or 'quality_issue')
        reasons.append(reason)
    residue_path = output_dir / 'render_residue_check.json'
    residue_pages = []
    if residue_path.is_file():
        residue = read_json(residue_path)
        residue_pages = [{'page': page.get('page'), 'severity': page.get('severity'),
                          'residue_ratio': page.get('residue_ratio')}
                         for page in residue.get('pages', [])
                         if page.get('evaluated') and page.get('severity') in {'high', 'medium'}]
        for reason in reasons:
            if reason.get('id') == 'render_english_residue':
                reason['page_levels'] = residue_pages
                reason['thresholds'] = residue.get('thresholds')
    if not reasons:
        reasons.append({'id': 'quality_status_fail', 'severity': 'high',
                        'message': 'comprehensive quality status is fail without itemised issues'})
    outputs = manifest.get('outputs') if isinstance(manifest.get('outputs'), dict) else {}
    files = sorted({Path(v).name for k, v in outputs.items()
                    if isinstance(v, str) and v.endswith('.pdf') and (output_dir / Path(v).name).is_file()})
    summary = '; '.join(
        f"{r['id']}({r.get('severity')})" + (f" pages {r['pages']}" if r.get('pages') else '')
        + (f" residue {r['overall_residue_ratio']}" if r.get('overall_residue_ratio') is not None else '')
        for r in reasons)
    return {'quality_gate': 'fail', 'exit_code': EXIT_QUALITY_FAIL,
            'quality_fail_summary': f'quality_status=fail: {summary}',
            'quality_fail_reasons': reasons, 'render_residue_pages': residue_pages,
            'outputs_written': True, 'output_files': files}


def child_marker(result):
    """子任务 stdout 末尾的结构化结果行（有界执行只保留 stdout 末尾 2 KiB；读不出即 None）。"""
    command = result.get('command') or {}
    excerpt = ((command.get('stdout_summary') or {}).get('excerpt') or '')
    for line in reversed(excerpt.splitlines()):
        if line.startswith(CHILD_RESULT_MARKER):
            try:
                value = json.loads(line[len(CHILD_RESULT_MARKER):])
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


def child_structured_result(result):
    value = child_marker(result)
    return value if value and value.get('status') == 'blocked' else None


def input_inspection_job(args):
    command = [sys.executable, str(SCRIPT_DIR/'scan_input_preflight.py'), '--input', str(args.input.resolve()),
               '--output', str(args.output.resolve()), '--max-pages', str(args.max_pages)]
    if getattr(args, 'catalog_url', None):
        command += ['--catalog-url', str(args.catalog_url)]
    for name in ('source_review', 'reuse_contract', 'model'):
        value = getattr(args, name, None)
        if value is not None:
            command += ['--'+name.replace('_', '-'), str(value)]
    if getattr(args, 'fresh', False):
        command.append('--fresh')
    result = run_job(args, command, 'bounded-input-inspection')
    result.update(report_ref=ref(args.output) if args.output.is_file() else None,
                  input_modified=False, new_OCR_MT_calls=0)
    if args.output.is_file():
        try:
            report = read_json(args.output)
        except ValueError:
            report = {}
        result.update(preflight_status=report.get('status'), error_code=report.get('error_code'),
                      findings=report.get('findings', []), source_language=report.get('source_language'))
        if report.get('status') == 'blocked' and result['status'] == 'failed':
            result['status'] = 'blocked'
            result['error_code'] = report.get('error_code') or (report.get('blockers') or [None])[0]
    write_new(args.receipts/'WORKFLOW_INPUT_INSPECTION.json', result)
    return result


def prepare_scan_job(args):
    command=[sys.executable,str(SCRIPT_DIR/'scan_structure_proposal.py'),'--source',str(args.input.resolve()),'--prepare-directory',str(args.output.resolve()),'--max-pages',str(args.max_pages)]
    for name in ('ocr','reuse-preparation','source-plan','groups','roles','targets','font','semantic-review','ink-protection','raw-targets'):
        value=getattr(args,name.replace('-','_'))
        if value is not None:command+=['--'+name,str(value.resolve())]
    if args.draft_source_plan:command+=['--draft-source-plan']
    result=run_job(args,command,'reviewed-scan-preparation')
    prepared_inputs=args.output/'FROZEN_PREPARATION_INPUTS.json'
    raw_ocr_ref=read_json(prepared_inputs)['rawOCR'] if result['status']=='succeeded' and prepared_inputs.is_file() else (ref(args.ocr) if args.ocr else None)
    result.update(stage='scan_source_and_trial_preparation',input_ref=ref(args.input),raw_OCR_ref=raw_ocr_ref,new_model_calls=0,human_accepted=False,strict_delivery=False)
    write_new(args.receipts/'WORKFLOW_SCAN_PREPARATION.json',result)
    return result


def trial_render_job(args):
    contract = read_json(args.contract)
    if contract.get('source_pdf_ref') != ref(args.input):
        raise ValueError('trial source PDF identity mismatch')
    result = run_job(args, [sys.executable, str(SCRIPT_DIR/'source_anchored_trial.py'),
        '--contract', str(args.contract.resolve()), '--output', str(args.output.resolve())], 'finite-source-anchored-trial')
    result.update(contract_ref=ref(args.contract), input_ref=ref(args.input),
                  stage='finite_source_anchored_trial', new_model_calls=0, human_accepted=False, strict_delivery=False)
    write_new(args.receipts/'WORKFLOW_TRIAL_RENDER.json', result)
    return result


def run_reviewed_scan(args):
    from scan_input_preflight import load_run_config, ref as input_ref
    result = {'status': 'blocked', 'development_revision': '109-unpublished', 'stages': [],
              'new_OCR_MT_calls': 0, 'human_acceptance': False, 'strict_delivery': False}
    try:
        if args.output.exists():
            raise ValueError('reviewed_run_requires_new_output')
        config, source, cp = load_run_config(args.config)
        limits = job_limits(args)
        args.task_deadline_monotonic = time.monotonic()+limits['per_job_seconds']
        common = dict(lock_path=args.lock_path, task_deadline_monotonic=args.task_deadline_monotonic, resource_limits=limits)
        inspect = argparse.Namespace(input=source, output=args.output/'INPUT_PREFLIGHT.json',
            receipts=args.receipts/'inspection', max_pages=config.get('max_pages', 2),
            catalog_url=config.get('model_catalog_url'),
            model=config.get('model'), reuse_contract=cp, source_review=None, fresh=False, **common)
        outcome = input_inspection_job(inspect)
        result['stages'].append(outcome)
        if outcome['status'] != 'succeeded':
            raise ValueError('input_inspection_failed_before_render')
        if config['mode'] == 'reprepare':
            fields = {n: None for n in ('ocr', 'source_plan', 'groups', 'roles', 'targets', 'font', 'semantic_review', 'ink_protection', 'raw_targets')}
            prepare = argparse.Namespace(input=source, output=args.output/'prepared', receipts=args.receipts/'prepare',
                reuse_preparation=cp, max_pages=config.get('max_pages', 2), draft_source_plan=False, **fields, **common)
            outcome = prepare_scan_job(prepare)
            result['stages'].append(outcome)
            if outcome['status'] != 'succeeded':
                raise ValueError('preparation_failed_before_render')
            cp = prepare.output/'TRIAL_CONTRACT.json'
        render = argparse.Namespace(input=source, contract=cp, output=args.output/'render',
                                    receipts=args.receipts/'render', **common)
        outcome = trial_render_job(render)
        result['stages'].append(outcome)
        result.update(status=outcome['status'], mode=config['mode'], config_ref=ref(args.config), source_ref=ref(source),
            entry_code_ref=ref(__file__), inspection_code_ref=input_ref(SCRIPT_DIR/'scan_input_preflight.py'),
            contract_ref=ref(cp), candidate_PDFs={k: ref(render.output/('page.'+k+'.pdf')) for k in ('mono','dual')} if outcome['status']=='succeeded' else {})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result.update(status='blocked', reason=str(exc), failed_before_new_OCR_MT=True)
    write_new(args.receipts/'WORKFLOW_REVIEWED_SCAN.json', result)
    return result


def run_latex_candidate(args, freeze, *, resume=False):
    """每个完整语义单元单独取锁和监控；任何失败阻止后续编译。"""
    script = str(SCRIPT_DIR / 'independent_latex.py')
    stages = []
    if resume:
        from latex_resume import validate_resume
        validate_resume(args, freeze)
        stages.append({'status': 'succeeded', 'operation': 'validated_existing_preparation',
                       'new_model_calls': 0, 'previous_result_ref': ref(args.previous_result)})
    else:
        prepare_command=[sys.executable,script,'prepare','--tex',freeze['latex_source']['path'],'--output',str(args.output.resolve())]
        if freeze.get('semantic_feedback_ref'):prepare_command+=['--semantic-feedback',freeze['semantic_feedback_ref']['path']]
        prepared = run_job(args,prepare_command,'prepare')
        stages.append(prepared)
        if prepared['status'] != 'succeeded':
            return {'status': 'failed', 'stages': stages, 'failed_stage': 'prepare'}
    plan = read_json(args.output / 'latex_plan.json')
    identifiers = [unit['id'] for unit in plan['units']]
    if args.smoke:
        identifiers = identifiers[:1]
    for identifier in identifiers:
        if resume and (args.output/'units'/(identifier+'.raw.json')).exists() and not (args.output/'units'/(identifier+'.json')).exists():
            return {'status': 'failed', 'stages': stages, 'failed_stage': identifier,
                    'blocker': 'failed_raw_requires_reviewed_complete_unit_or_new_attempt',
                    'new_model_calls_for_failed_unit': 0}
        outcome = run_job(args, [sys.executable, script, 'translate', '--output', str(args.output.resolve()),
            '--unit', identifier, '--model', args.model, '--base-url', args.base_url,
            '--model-fingerprint', freeze['model_fingerprint_ref']['path']], identifier)
        stages.append(outcome)
        if outcome['status'] != 'succeeded':
            return {'status': 'failed', 'stages': stages, 'failed_stage': identifier}
    if args.smoke:
        return {'status': 'succeeded', 'stages': stages, 'smoke_scope': identifiers,
                'candidate_pdf_generated': False, 'full_semantic_translation': False}
    compiled = run_job(args, [sys.executable, script, 'compile', '--output', str(args.output.resolve()),
                            '--cjk-font', args.cjk_font, '--source-pdf', str(args.input.resolve())], 'compile')
    stages.append(compiled)
    result_path = args.output / 'latex_result.json'
    candidate = read_json(result_path) if result_path.exists() else {}
    succeeded = compiled['status'] == 'succeeded' and candidate.get('status') == 'candidate'
    return {'status': 'succeeded' if succeeded else 'failed', 'stages': stages,
            'candidate': candidate, 'fallback_used': False}


def validate_proxy_quality(stats, native=False):
    if not isinstance(stats, dict):
        raise ValueError('proxy quality statistics object required')
    keys=('policy_instruction_leak_rejected', 'format_placeholder_rejected', 'source_protocol_rejected')+ (('native_response_rejected',) if native else ())
    for key in keys:
        count = stats.get(key)
        if type(count) is not int or count < 0:
            raise ValueError('invalid or absent proxy quality count: '+key)
        if count:
            raise ValueError('source-bound proxy quality failure: ' + key)


def validate_proxy_evidence(path, required, adapter=None):
    if type(required) is not bool:
        raise ValueError('explicit proxy applicability required')
    if not required:
        return
    if not path.is_file():
        raise ValueError('required actual proxy quality evidence missing')
    evidence = read_json(path)
    if not isinstance(evidence, dict) or not isinstance(evidence.get('proxy'), dict) or evidence['proxy'].get('enabled') is not True:
        raise ValueError('required proxy not actually active')
    if adapter and evidence['proxy'].get('adapter')!=adapter:
        raise ValueError('actual source-bound adapter differs from freeze')
    validate_proxy_quality(evidence.get('stats'),native=adapter=='source_bound_native')


def execute_digital(freeze_path, command, ocr_manifest=None):
    """子任务内核对真实页数和扫描路线，扫描禁止进入首发模型调用。
    scanned_ocr 路线：输入必须是同一 FREEZE 输入经 OCR 清单绑定的重建源（逐 sha 核对），其余守门与电子路线相同。"""
    import fitz
    import run_pdf_translation
    from scanned_raster.route_pdf import route_pdf
    started_at = time.time()
    freeze = read_json(freeze_path)
    args = run_pdf_translation.build_parser().parse_args(command)
    args.attempt_started_at, args.attempt_freeze_path = started_at, freeze_path
    if ocr_manifest is None:
        if freeze.get('route')!='digital_pdf' or freeze.get('routing_contract')!=DIGITAL_ROUTING or not args.pdf_backend_only or args.latex_render_mode!='off':
            raise ValueError('explicit digital route identity missing or changed')
    else:
        manifest = bound_json(ocr_manifest)
        rebuilt = manifest.get('reconstructed_source') or {}
        if (freeze.get('route')!='scanned_ocr' or freeze.get('routing_contract')!=OCR_ROUTING or not args.pdf_backend_only
                or args.latex_render_mode!='off' or manifest.get('status')!='ok'
                or manifest.get('input',{}).get('sha256')!=freeze['input']['sha256']
                or ref(args.input_pdf)!={'path':rebuilt.get('path'),'sha256':rebuilt.get('sha256')}):
            raise ValueError('explicit scanned OCR route identity or reconstructed source binding missing or changed')
    with fitz.open(args.input_pdf) as document:
        if list(range(1, len(document)+1)) != freeze['pages']:
            raise ValueError('actual PDF page scope differs from freeze')
    given_context = ({'path': str(Path(args.document_term_context).resolve()), 'sha256': args.document_term_context_sha256}
                     if args.document_term_context else None)
    if freeze.get('document_term_context_ref') != given_context or (given_context and sha(given_context['path']) != given_context['sha256']):
        raise ValueError('document term context binding missing or changed')
    expected_transport=read_json(Path(freeze['model_fingerprint_ref']['path'])).get('api_contract') or 'openai_compatible'
    if args.translation_transport!=expected_transport or (expected_transport!='openai_compatible' and args.translator_mode!='openai'):
        raise ValueError('frozen explicit transport changed')
    route = route_pdf(Path(args.input_pdf), args=args)
    if route.get('document_route') != 'pdf_backend' or not route.get('dispatch_allowed'):
        review_pages = [{'page': p.get('page'), 'reasons': p.get('reasons')} for p in route.get('pages', [])
                        if p.get('decision') not in (None, 'native_digital', 'digital')][:20]
        raise PreflightError('non_digital_pages', '路由判定存在非原生电子页（扫描、图像文字或信号不足）；电子 PDF 路线要求全部页面为原生文字层。',
                             document_route=route.get('document_route'), review_reasons=route.get('review_reasons'),
                             pages=review_pages)
    if args.source_cache_mode:
        from pdf_source_cache import source_cache
        context=source_cache({'path':str(args.source_cache_context.resolve()),'sha256':args.source_cache_context_sha256},args.source_cache_mode).context
        if context['freeze_ref']!=ref(freeze_path) or context['input_ref']!=freeze['input'] or context['scope_ref']!=freeze['scope_evidence']:
            raise ValueError('source cache current freeze/input/scope mismatch')
    result = run_pdf_translation.run(args)
    if args.source_cache_mode=='collect':
        if result.get('status')!='source_only_collected':raise ValueError('source-only collection missing')
        return result
    return finish_digital_result(freeze, args, result, context if args.source_cache_mode else None)


def finish_digital_result(freeze, args, result, context):
    """正式生成与原render续验共同使用原完整尾部守门。"""
    manifest = read_json(Path(args.output_dir)/'render_manifest.json')
    proxy_stats_path = Path(args.output_dir)/'hymt_proxy_stats.json'
    validate_proxy_evidence(proxy_stats_path, freeze['proxy_quality_contract']['required'],freeze['proxy_quality_contract']['adapter'])
    if args.source_cache_mode=='read':
        evidence=read_json(proxy_stats_path)['stats']
        from pdf_source_cache import GROUP_PROTOCOLS
        if context['protocol'] in GROUP_PROTOCOLS:
            from pdf_source_cache import validate_group_render_evidence,bound_json
            invocation_ref=manifest.get('source_cache_render_invocation_ref')
            if not invocation_ref or invocation_ref!=result.get('source_cache_render_invocation_ref'):
                raise ValueError('actual current render invocation missing from manifests')
            invocation=bound_json(invocation_ref)
            if (invocation['requested_pages']!=args.pages or read_json(proxy_stats_path)['proxy'].get('source_cache_render_id')!=invocation['render_id']):
                raise ValueError('actual current render requested pages/proxy identity differs')
            if args.pages not in (None,'1'):raise ValueError('formal group render requires whole input or page1 smoke')
            pages=[1] if args.pages=='1' else freeze['pages']
            coverage=validate_group_render_evidence(context_ref={'path':str(args.source_cache_context.resolve()),'sha256':args.source_cache_context_sha256},
                invocation_ref=invocation_ref,pages=pages,proxy_trace_dir=Path(args.output_dir)/'native_transport')
            write_new(Path(args.output_dir)/'WORKFLOW_GROUP_RENDER_EVIDENCE.json',coverage)
        for key in ('source_cache_rejected','actual_provider_calls'):
            if type(evidence.get(key)) is not int or evidence[key]!=0:raise ValueError('cache-only render rejected or generated')
        if type(evidence.get('current_attempt_cache_hits')) is not int or evidence['current_attempt_cache_hits']<=0:
            raise ValueError('cache-only rendering lacked actual source boundary hits')
    target = manifest.get('outputs', {}).get('translated_pdf')
    attempt_freeze = getattr(args, 'attempt_freeze_path', None)
    if attempt_freeze and manifest.get('actual_render_source') == 'pdf_backend' and (not target or not Path(target).is_file()):
        # 本次 _execute-digital 的后端失败（未产出候选）：根因只取本尝试输出目录内的结构化产物
        # （排版回执、render_manifest），连同本尝试身份写根因回执；拿不到即 root_cause_unavailable，不猜。
        output_dir = Path(args.output_dir)
        started_at = getattr(args, 'attempt_started_at', None)
        cause = failure_root_cause.derive(output_dir, manifest, expected_pages=len(freeze['pages']), started_at=started_at)
        receipt_ref = failure_root_cause.write_receipt(output_dir, cause, freeze_path=attempt_freeze, started_at=started_at)
        raise BackendFailure(cause, receipt_ref)
    if manifest.get('actual_render_source') != 'pdf_backend' or not target or not Path(target).is_file():
        raise ValueError('PDF backend failed or changed route; no fallback delivery')
    write_new(Path(args.output_dir)/'WORKFLOW_RENDER_RESULT.json', result)
    return {'status':'candidate', 'candidate_ref':ref(target), 'quality_pass':False,
            'human_accepted':False, 'strict_delivery':False}


def continue_digital(contract_ref, receipt_path):
    """只续验已正常完成的原render；不创建UUID、HTTP请求或PDF。"""
    from pdf_source_cache import bound_json, source_cache
    from types import SimpleNamespace
    import run_pdf_translation
    contract = bound_json(contract_ref)
    required = {'protocol','render_id','producer_freeze_ref','context_ref','input_ref','pdf_ref',
        'manifest_ref','backend_manifest_ref','proxy_stats_ref','identity_ref','invocation_ref',
        'producer_entrypoint_snapshot_ref','continuation_entrypoint_ref','interrupted_result_ref'}
    if set(contract) != required or contract['protocol'] != 'completed_digital_render_continuation_v1':
        raise ValueError('exact completed render continuation contract required')
    for name in required - {'protocol','render_id'}:
        bound_json(contract[name]) if name not in {'input_ref','pdf_ref','producer_entrypoint_snapshot_ref','continuation_entrypoint_ref'} else checked_continuation_file(contract[name])
    if contract['continuation_entrypoint_ref'] != ref(Path(__file__)):
        raise ValueError('actual continuation implementation identity differs')
    freeze = bound_json(contract['producer_freeze_ref'])
    if contract['producer_entrypoint_snapshot_ref']['sha256'] != freeze['entrypoint']['sha256']:
        raise ValueError('actual original producer entrypoint snapshot differs')
    validate_freeze(freeze,Path(contract['input_ref']['path']),'digital_pdf',freeze['model'])
    context = source_cache(contract['context_ref'],'read').context
    manifest = bound_json(contract['manifest_ref']); backend = bound_json(contract['backend_manifest_ref'])
    identity = bound_json(contract['identity_ref']); invocation = bound_json(contract['invocation_ref'])
    stats = bound_json(contract['proxy_stats_ref'])
    output = Path(contract['manifest_ref']['path']).parent
    if (freeze['input'] != contract['input_ref'] or context['input_ref'] != contract['input_ref']
            or context['freeze_ref'] != contract['producer_freeze_ref']
            or context['scope_ref'] != freeze['scope_evidence']
            or invocation['context_ref'] != contract['context_ref'] or invocation['input_ref'] != contract['input_ref']
            or invocation['render_id'] != contract['render_id'] or identity['render_id'] != contract['render_id']
            or identity['context_ref'] != contract['context_ref'] or identity['final_pdf_ref'] != contract['pdf_ref']
            or manifest.get('returncode') != 0 or manifest.get('actual_render_source') != 'pdf_backend'
            or backend.get('actual_render_source') != 'pdf_backend'
            or manifest.get('outputs',{}).get('translated_pdf') != contract['pdf_ref']['path']
            or manifest.get('source_cache_render_invocation_ref') != contract['invocation_ref']
            or backend.get('source_cache_render_invocation_ref') != contract['invocation_ref']
            or stats.get('proxy',{}).get('source_cache_render_id') != contract['render_id']
            or ref(output/'hymt_proxy_stats.json') != contract['proxy_stats_ref']
            or ref(output/'FINAL_ARTIFACT_IDENTITY.json') != contract['identity_ref']
            or bound_json(contract['interrupted_result_ref']).get('status') != 'stopped'):
        raise ValueError('completed original backend/source/artifact/render/stat identity differs')
    if receipt_path.exists():raise ValueError('fresh continuation receipt required')
    args = SimpleNamespace(input_pdf=contract['input_ref']['path'],output_dir=str(output),
        source_cache_mode='read',source_cache_context=Path(contract['context_ref']['path']),
        source_cache_context_sha256=contract['context_ref']['sha256'],pages=invocation['requested_pages'])
    import fitz
    from scanned_raster.route_pdf import route_pdf
    with fitz.open(args.input_pdf) as source:
        if list(range(1,len(source)+1)) != freeze['pages']:
            raise ValueError('actual original source page scope changed')
    args.pdf_backend_only=True;args.latex_render_mode='off'
    route=route_pdf(Path(args.input_pdf),args=args)
    if route.get('document_route') != 'pdf_backend' or not route.get('dispatch_allowed'):
        raise ValueError('original source digital route changed')
    # 同一实际保存产物重跑既有字形/字体/ToUnicode绑定，不继承一个布尔成功。
    run_pdf_translation.bind_final_group_artifact(args,output,manifest,contract['invocation_ref'])
    if ref(output/'FINAL_ARTIFACT_IDENTITY.json') != contract['identity_ref']:
        raise ValueError('original saved artifact identity changed during continuation')
    result = finish_digital_result(freeze,args,manifest,context)
    result.update(stage='completed_original_digital_render_continuation',render_id=contract['render_id'],
        producer_controller_status='stopped',fresh_render=False,new_provider_calls=0,
        continuation_contract_ref=contract_ref,continuation_implementation_ref=ref(Path(__file__)))
    write_new(receipt_path,result)
    return result


def checked_continuation_file(evidence):
    from independent_latex import reject_symlink_ancestors
    reject_symlink_ancestors(evidence['path'])
    if set(evidence) != {'path','sha256'} or ref(Path(evidence['path'])) != evidence:
        raise ValueError('completed continuation physical input changed')
    return evidence


def preflight(packet_path, acceptance_path):
    packet = read_json(packet_path)
    acceptance = read_json(acceptance_path)
    result = check_scoped_preflight(packet, acceptance)
    blockers = result['blockers']
    try:
        quality = bound_json(packet['comprehensive_quality_ref'])
        if quality.get('status') != 'pass' or quality.get('quality_pass') is not True:
            blockers.append('comprehensive_quality_not_pass')
        if quality.get('issues') or quality.get('pending'):
            blockers.append('comprehensive_quality_unresolved')
        target = quality.get('target')
        if target not in [{'path': a['path'], 'sha256': a['sha256']} for a in packet['artifacts']]:
            blockers.append('quality_target_outside_accepted_artifacts')
    except (KeyError, ValueError, OSError):
        blockers.append('comprehensive_quality_missing_or_changed')
    result['status'] = 'ready_for_delivery' if not blockers else 'blocked'
    result['packet_ref'] = ref(packet_path)
    result['acceptance_ref'] = ref(acceptance_path)
    return result


def deliver(packet_path, acceptance_path, output):
    result = preflight(packet_path, acceptance_path)
    if result['blockers']:
        return result
    packet = read_json(packet_path)
    names = [Path(item['path']).name for item in packet['artifacts']]
    if len(set(names)) != len(names):
        raise ValueError('duplicate delivery filenames')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    copies = []
    for item in packet['artifacts']:
        # 复制前后再次核对，避免预检之后输入变化继承验收。
        if sha(item['path']) != item['sha256']:
            raise ValueError('accepted artifact changed during delivery')
        target = output / Path(item['path']).name
        shutil.copyfile(item['path'], target)
        if sha(target) != item['sha256']:
            raise ValueError('delivery copy identity mismatch')
        copies.append({'id': item['id'], **ref(target)})
    result.update(status='delivered', delivered_at=datetime.now(timezone.utc).isoformat(),
                  artifacts=copies, scope='only listed accepted PDF identities; no Skill publication')
    write_new(output / 'DELIVERY_RECEIPT.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    inspect = sub.add_parser('inspect-input', help='只读有界输入事实与库存；源图资格不自动判定')
    inspect.add_argument('--input', type=Path, required=True)
    inspect.add_argument('--output', type=Path, required=True)
    inspect.add_argument('--receipts', type=Path, required=True)
    inspect.add_argument('--max-pages', type=int, default=2)
    inspect.add_argument('--source-review', type=Path)
    inspect.add_argument('--reuse-contract', type=Path)
    inspect.add_argument('--model')
    inspect.add_argument('--catalog-url', default=None)
    inspect.add_argument('--fresh', action='store_true')
    inspect.add_argument('--lock-path', type=Path, default=PROJECT/'logs/paper_translation_workflow.lock')
    reviewed = sub.add_parser('run-reviewed-scan', help='单配置衔接既有输入预检、审后复用和有限渲染')
    reviewed.add_argument('--config', type=Path, required=True)
    reviewed.add_argument('--output', type=Path, required=True)
    reviewed.add_argument('--receipts', type=Path, required=True)
    reviewed.add_argument('--lock-path', type=Path, default=PROJECT/'logs/paper_translation_workflow.lock')
    d = sub.add_parser('doctor')
    d.add_argument('--base-url', required=True)
    d.add_argument('--model', required=True)
    d.add_argument('--output', type=Path)
    continuation = sub.add_parser('continue-digital', help='仅续验同一已完成backend的原render，不重新生成')
    continuation.add_argument('--contract', type=Path, required=True)
    continuation.add_argument('--contract-sha256', required=True)
    continuation.add_argument('--receipt', type=Path, required=True)
    continuation.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
    internal = sub.add_parser('_execute-digital', help=argparse.SUPPRESS)
    internal.add_argument('--freeze', type=Path, required=True)
    internal.add_argument('--ocr-manifest', type=Path)
    internal.add_argument('--ocr-manifest-sha256')
    internal.add_argument('command', nargs=argparse.REMAINDER)
    revision = sub.add_parser('revise-latex', help='审校通过的完整源单元修订，另生成候选')
    revision.add_argument('--input', type=Path, required=True)
    revision.add_argument('--contract', type=Path, required=True)
    revision.add_argument('--output', type=Path, required=True)
    revision.add_argument('--receipts', type=Path, required=True)
    revision.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
    revision.add_argument('--cjk-font', default='Songti SC')
    roles = sub.add_parser('preserve-roles', help='独立源角色字形与动作保护，另生成候选')
    roles.add_argument('--input', type=Path, required=True)
    roles.add_argument('--contract', type=Path, required=True)
    roles.add_argument('--output', type=Path, required=True)
    roles.add_argument('--receipts', type=Path, required=True)
    roles.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
    trial = sub.add_parser('trial-render', help='显式源角色/同类leading/源锚点的有限cache-only候选')
    trial.add_argument('--input', type=Path, required=True)
    trial.add_argument('--contract', type=Path, required=True)
    trial.add_argument('--output', type=Path, required=True)
    trial.add_argument('--receipts', type=Path, required=True)
    trial.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
    scan_prepare = sub.add_parser('prepare-scan', help='复用OCR和具名完整源组/角色输入，准备现有trial-render')
    scan_prepare.add_argument('--input',type=Path,required=True)
    scan_prepare.add_argument('--ocr',type=Path)
    scan_prepare.add_argument('--reuse-preparation',type=Path)
    scan_prepare.add_argument('--source-plan',type=Path)
    scan_prepare.add_argument('--draft-source-plan',action='store_true')
    scan_prepare.add_argument('--output',type=Path,required=True)
    scan_prepare.add_argument('--receipts',type=Path,required=True)
    scan_prepare.add_argument('--lock-path',type=Path,default=PROJECT/'logs/paper_translation_workflow.lock')
    scan_prepare.add_argument('--max-pages',type=int,default=5)
    for name in ('groups','roles','targets','font','semantic-review','ink-protection','raw-targets'):
        scan_prepare.add_argument('--'+name,type=Path)
    resumed = sub.add_parser('resume-latex', help='核原失败回执与完整单元后继续LaTeX候选；保留所有保护门')
    for name in ('input', 'freeze', 'output', 'receipts', 'previous-result'):
        resumed.add_argument('--'+name, type=Path, required=True)
    resumed.add_argument('--previous-result-sha256', required=True)
    resumed.add_argument('--model', required=True)
    resumed.add_argument('--base-url', required=True)
    resumed.add_argument('--cjk-font', default='Songti SC')
    resumed.add_argument('--lock-path', type=Path, default=PROJECT/'logs/paper_translation_workflow.lock')
    resumed.add_argument('--smoke', action='store_true', help=argparse.SUPPRESS)
    for action in ('candidate','collect','review'):
        p = sub.add_parser(action)
        p.add_argument('--input', type=Path, required=True)
        p.add_argument('--output', type=Path, required=True)
        p.add_argument('--receipts', type=Path, required=True)
        p.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
        if action in ('candidate','collect'):
            p.add_argument('--freeze', type=Path, required=True)
            p.add_argument('--route', choices=list(ROUTES), required=True)
            p.add_argument('--model', required=True)
            p.add_argument('--base-url', required=True)
            p.add_argument('--smoke', action='store_true')
            p.add_argument('--cjk-font', default='Songti SC')
            p.add_argument('--target-language', choices=('zh', 'en'), default='zh',
                           help='目标语言：zh=英译中（默认），en=中译英')
            p.add_argument('--source-cache-context',type=Path)
            p.add_argument('--source-cache-context-sha256')
        else:
            p.add_argument('--candidate', type=Path, required=True)
    chunked = sub.add_parser('chunked-candidate', help='长文档：按页范围分成有界块逐块走既有路线，按原页序合并；任何一块失败即整份失败关闭')
    chunked.add_argument('--input', type=Path, required=True)
    chunked.add_argument('--output', type=Path, required=True)
    chunked.add_argument('--receipts', type=Path, required=True)
    chunked.add_argument('--freeze', type=Path, required=True)
    chunked.add_argument('--route', choices=list(CHUNK_ROUTES), required=True,
                         help='digital_pdf / scanned_ocr：全部块同一路线；per_chunk：原生文字页走 digital_pdf，扫描页走 scanned_ocr')
    chunked.add_argument('--model', required=True)
    chunked.add_argument('--base-url', required=True)
    chunked.add_argument('--target-language', choices=('zh', 'en'), default='zh')
    chunked.add_argument('--cjk-font', default='Songti SC')
    chunked.add_argument('--resume', action='store_true', help='在同一 --output/--receipts 续跑：已完成块逐 sha 核对后复用，未完成块重跑')
    chunked.add_argument('--lock-path', type=Path, default=PROJECT / 'logs/paper_translation_workflow.lock')
    for action in ('preflight', 'deliver', 'preflight-finite', 'deliver-finite'):
        p = sub.add_parser(action)
        p.add_argument('--packet', type=Path, required=True)
        p.add_argument('--acceptance', type=Path, required=True)
        if action in {'deliver', 'deliver-finite'}:
            p.add_argument('--output', type=Path, required=True)
    for name, subparser in sub.choices.items():
        if name in {'doctor', '_execute-digital', 'preflight', 'deliver', 'preflight-finite', 'deliver-finite'}:
            continue
        group = subparser.add_argument_group('resource limits (CLI > env > platform default; candidate/collect/resume-latex: '
                                              'the frozen FREEZE resource_contract is authoritative, overrides must match it)')
        group.add_argument('--task-memory-mib', type=int, default=None,
                           help='进程树内存上限（MiB）；也可用环境变量 PAPER_TRANSLATION_TASK_MEMORY_MIB。默认 macOS 5120（RSS）、Linux 4096（PSS），且不超过物理内存 25%%')
        group.add_argument('--job-timeout-seconds', type=int, default=None,
                           help='单作业总时限（秒）；也可用 PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS。默认 macOS 120、Linux 300')
        group.add_argument('--memory-metric', choices=('rss', 'pss'), default=None,
                           help='内存计量口径；也可用 PAPER_TRANSLATION_MEMORY_METRIC。默认 macOS rss、Linux pss')
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except (PreflightError, ResourceLimitError, ValueError, OSError, RuntimeError) as exc:
        result = structured_failure(args, exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == '_execute-digital' and isinstance(exc, PreflightError):
            print(CHILD_RESULT_MARKER + json.dumps({k: result[k] for k in ('status', 'error_code', 'findings')}, ensure_ascii=False))
        elif args.action == '_execute-digital' and isinstance(exc, BackendFailure):
            # 精简结构化行（父任务据 root_cause_ref 读回执并逐项核对，不信任这一行本身的细节）。
            print(CHILD_RESULT_MARKER + json.dumps({'status': result['status'], 'error_code': result['error_code'],
                                                    'root_cause': failure_root_cause.compact(exc.root_cause),
                                                    'root_cause_ref': exc.receipt_ref}, ensure_ascii=False))
        return EXIT_BLOCKED
    except Exception as exc:
        # 未预期的内部错误：仍输出结构化 JSON 与回执（不再只剩 traceback），退出码 1；不吞掉错误。
        result = unexpected_failure(args, exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] == 'blocked':
        return EXIT_BLOCKED
    ok = result['status'] in {'ready', 'succeeded', 'ready_for_delivery', 'delivered', 'candidate', 'source_only_collected'}
    if ok and result.get('quality_status') == 'fail':
        # 任何生成候选的动作/路线：译文已照常写出，但综合质量判 fail，用独立退出码 3（预检拦截为 2）。
        result.setdefault('exit_code', EXIT_QUALITY_FAIL)
        return EXIT_QUALITY_FAIL
    return EXIT_OK if ok else EXIT_ERROR


def unexpected_failure(args, exc):
    import traceback
    result = {'status': 'failed', 'error_code': 'internal_error', 'action': args.action, 'schema_version': 1,
              'exception_type': type(exc).__name__, 'exception_message': str(exc)[:500],
              'traceback_tail': traceback.format_exc()[-2000:]}
    receipts = getattr(args, 'receipts', None)
    if receipts:
        try:
            Path(receipts).mkdir(parents=True, exist_ok=True)
            path = Path(receipts) / 'WORKFLOW_INTERNAL_ERROR.json'
            if not path.exists():
                write_new(path, result)
            result['receipt'] = str(path)
        except OSError as receipt_exc:
            result['receipt_error'] = f'{type(receipt_exc).__name__}: {receipt_exc}'[:300]
    print(result['traceback_tail'], file=sys.stderr)
    return result


def structured_failure(args, exc):
    """所有动作失败时统一输出结构化 JSON（不再打印原始 traceback）。"""
    if isinstance(exc, PreflightError):
        result = getattr(exc, 'result', None) or exc.to_dict()
        result = dict(result, status='blocked', error_code=exc.code)
    elif isinstance(exc, BackendFailure):
        cause = exc.root_cause
        result = blocked_result([finding(cause['code'], failure_root_cause.message(cause), stage=cause.get('stage'),
                                         retry=cause.get('retry'))])
        result.update(status='failed', root_cause=cause, root_cause_ref=exc.receipt_ref)
    else:
        code = (getattr(exc, 'code', 'resource_limit_invalid') if isinstance(exc, ResourceLimitError) else
                'project_lock_busy' if isinstance(exc, RuntimeError) else
                'input_or_contract_invalid' if isinstance(exc, ValueError) else 'io_error')
        result = blocked_result([finding(code, f'{type(exc).__name__}: {exc}'[:500])])
    result.update(action=args.action, schema_version=1)
    return result


def bounded_input_preflight(input_pdf, receipts, *, require_digital, target_language='zh', max_pages=DIGITAL_MAX_PAGES):
    """在有界子进程中解析 PDF（内存/时限受监控）；页数超限时子进程不再逐页解析。"""
    receipt_dir = Path(receipts) / 'input-preflight'
    report_path = receipt_dir / 'input_preflight_report.json'
    receipt_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(SCRIPT_DIR / 'pdf_input_preflight.py'), '--input', str(Path(input_pdf).resolve()),
               '--max-pages', str(max_pages), '--target-language', target_language, '--output', str(report_path)]
    if require_digital:
        command.append('--require-digital')
    outcome = run_bounded(command, cwd=SCRIPT_DIR, receipt_dir=receipt_dir, operation='input-preflight',
                          timeout_seconds=PREFLIGHT_SECONDS, interval_seconds=0.5, rss_limit=PREFLIGHT_RSS_BYTES,
                          max_processes=4, memory_metric='rss', max_total_fraction=0.5)
    guard = {key: outcome.get(key) for key in ('status', 'stop_reason', 'elapsed_seconds', 'rss_limit_bytes',
                                               'memory_metric', 'peak_task_memory_bytes')}
    guard['timeout_seconds'] = PREFLIGHT_SECONDS
    if outcome.get('status') != 'succeeded' or not report_path.is_file():
        report = blocked_result([finding('preflight_guard_stopped',
            f"输入预检子进程未在有界预算内完成：{outcome.get('stop_reason') or outcome.get('status')}",
            stop_reason=outcome.get('stop_reason'), exception=outcome.get('exception_message'),
            stderr=((outcome.get('command') or {}).get('stderr_summary') or {}).get('excerpt', '')[-300:])])
    else:
        report = read_json(report_path)
    report['preflight_guard'] = guard
    return report


def check_target_language_route(args):
    """中译英只支持 candidate --route digital_pdf：LaTeX 路线的译者与 collect 的源绑定原生传输都写死译成简体中文。
    在预检、FREEZE、doctor 与任何模型调用之前以退出码 2 拒绝，避免静默产出错误方向的译文。"""
    target = getattr(args, 'target_language', 'zh') or 'zh'
    if target == 'zh':
        return
    allowed = PDF_BACKEND_ROUTES + (('per_chunk',) if args.action == 'chunked-candidate' else ())
    if args.route not in allowed or args.action == 'collect':
        exc = PreflightError('target_language_route_unsupported',
                             f'--target-language {target} 只支持 candidate --route digital_pdf / scanned_ocr；'
                             f'当前 {args.action} --route {args.route} 的译者固定译成简体中文。',
                             target_language=target, route=args.route, action=args.action)
        exc.result = dict(blocked_result([finding('target_language_route_unsupported', target_language=target,
                                                  route=args.route, action=args.action)]),
                          stage='target_language_route')
        raise exc


def candidate_input_preflight(args):
    """candidate/collect 在验证 FREEZE 与启动重任务前先做轻量结构化输入预检。"""
    receipts = Path(args.receipts)
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / 'WORKFLOW_INPUT_PREFLIGHT.json'
    report = bounded_input_preflight(args.input, receipts, require_digital=args.route == 'digital_pdf',
                                     target_language=getattr(args, 'target_language', 'zh'))
    if not path.exists():
        write_new(path, report)
    if report['status'] == 'blocked':
        first = next(f for f in report['findings'] if f['severity'] == 'error')
        exc = PreflightError(first['code'], first['message'], **first['details'])
        exc.result = dict(report, stage='input_preflight', preflight_ref=ref(path))
        raise exc
    return report


def dispatch(args):
    if hasattr(args, 'task_memory_mib') and args.action not in FREEZE_BOUND_ACTIONS:
        args.resource_limits = resolve_limits(memory_mib=args.task_memory_mib,
            timeout_seconds=args.job_timeout_seconds, memory_metric=args.memory_metric)
    if args.action == 'inspect-input':
        result = input_inspection_job(args)
    elif args.action == 'run-reviewed-scan':
        result = run_reviewed_scan(args)
    elif args.action == 'continue-digital':
        with project_lock(args.lock_path):
            result = continue_digital({'path':str(args.contract.resolve()),'sha256':args.contract_sha256},args.receipt)
    elif args.action == '_execute-digital':
        manifest_ref = ({'path': str(args.ocr_manifest.resolve()), 'sha256': args.ocr_manifest_sha256}
                        if args.ocr_manifest else None)
        if args.ocr_manifest and not args.ocr_manifest_sha256:
            raise ValueError('OCR manifest exact SHA required')
        result = execute_digital(args.freeze, args.command[1:] if args.command[:1] == ['--'] else args.command, manifest_ref)
    elif args.action == 'doctor':
        result = doctor(args.base_url, args.model, include_ocr=True)
        if args.output:
            write_new(args.output, result)
    elif args.action == 'resume-latex':
        if args.receipts.exists():
            raise ValueError('resume_requires_fresh_receipt_directory')
        freeze = read_json(args.freeze)
        pages = validate_freeze(freeze, args.input, 'latex_verified', args.model)
        args.resource_limits = frozen_limits(args, freeze)
        args.frozen_environment = freeze.get('backend_environment', {})
        health = doctor(args.base_url, args.model)
        if health['blockers'] or not health['latex_ready']:
            raise ValueError('required environment not ready')
        result = run_latex_candidate(args, freeze, resume=True)
        result.update(freeze_ref=ref(args.freeze), input_ref=ref(args.input), route='latex_verified',
                      declared_pages=pages, stage='resumed_candidate', human_accepted=False,
                      strict_delivery=False, previous_result_ref=ref(args.previous_result),
                      resource_contract_frozen=freeze.get('resource_contract'))
        result.update(quality_verdict(args.output))
        write_new(args.receipts/'WORKFLOW_RESUMED_CANDIDATE.json', result)
    elif args.action in ('candidate','collect'):
        check_target_language_route(args)
        preflight_report = candidate_input_preflight(args)
        freeze = read_json(args.freeze)
        pages = validate_freeze(freeze, args.input, args.route, args.model)
        args.resource_limits = frozen_limits(args, freeze)
        args.frozen_environment = freeze.get('backend_environment', {})
        if args.output.exists():
            raise ValueError('candidate requires a new output directory')
        from pdf_source_cache import REVISION_CONTRACT, source_cache
        offline_revision=(args.action=='candidate' and args.route=='digital_pdf'
            and freeze.get('source_cache_contract')==REVISION_CONTRACT)
        if offline_revision:
            if not args.source_cache_context or not args.source_cache_context_sha256:
                raise ValueError('validated current revision context required before offline doctor')
            current=source_cache({'path':str(args.source_cache_context.resolve()),
                'sha256':args.source_cache_context_sha256},'read')
            if current.context['freeze_ref']!=ref(args.freeze):
                raise ValueError('offline doctor revision context is from another renderer freeze')
            del current
            from pdf_source_cache import release_source_parsing_cache
            release_source_parsing_cache()
        health = doctor(args.base_url, args.model,provider_generation_required=not offline_revision)
        if health['blockers'] or args.route == 'latex_verified' and not health['latex_ready']:
            raise ValueError('required environment not ready')
        if args.action=='collect':
            from pdf_source_cache import CONTRACT
            if freeze.get('source_cache_contract')!=CONTRACT:raise ValueError('collector contract not frozen')
            if args.route!='digital_pdf' or args.smoke:raise ValueError('collect requires complete digital PDF scope')
            from pdf_source_cache import PROTOCOL
            args.output.mkdir(parents=True)
            context={'protocol':PROTOCOL,'freeze_ref':ref(args.freeze),'input_ref':freeze['input'],
                'scope_ref':freeze['scope_evidence'],'model_fingerprint_ref':freeze['model_fingerprint_ref'],
                'implementation_refs':freeze['implementation_refs'],'policy_ref':freeze['source_cache_policy_ref'],
                'model':args.model,'endpoint':args.base_url,
                'parameters':bound_json(freeze['model_fingerprint_ref'])['generation_parameters'],
                'transport':'lmstudio_native_chat_v1','transport_contract':bound_json(freeze['model_fingerprint_ref'])['transport_contract'],'cache_directory':str(args.output.resolve()/'responses'),
                'collection_file':str(args.output.resolve()/'SOURCE_REQUESTS.jsonl'),
                'editorial_revisions':freeze.get('editorial_revisions',[])}
            context_path=args.output/'COLLECTION_CONTEXT.json';write_new(context_path,context)
            args.output=args.output/'collector_backend'
            command=candidate_command(args,freeze)+['--source-cache-mode','collect','--source-cache-context',str(context_path.resolve()),'--source-cache-context-sha256',sha(context_path)]
            result=run_job(args,[sys.executable,str(Path(__file__)),'_execute-digital','--freeze',str(args.freeze.resolve()),'--',*command[2:]],'source-collect')
        elif args.route == 'latex_verified':
            result = run_latex_candidate(args, freeze)
        elif args.route == 'scanned_ocr':
            result = run_scanned_ocr_candidate(args, freeze)
        else:
            command = candidate_command(args, freeze)
            if freeze.get('source_cache_contract') and not args.source_cache_context:
                raise ValueError('frozen cache-only candidate requires current attempt context')
            if args.source_cache_context:
                if not args.source_cache_context_sha256:raise ValueError('source cache exact context SHA required')
                command+=['--source-cache-mode','read','--source-cache-context',str(args.source_cache_context.resolve()),'--source-cache-context-sha256',args.source_cache_context_sha256]
            result = run_job(args, [sys.executable, str(Path(__file__)), '_execute-digital',
                '--freeze', str(args.freeze.resolve()), '--', *command[2:]], 'candidate')
        result.update(freeze_ref=ref(args.freeze), input_ref=ref(args.input), route=args.route,
                      declared_pages=pages, stage='smoke_candidate' if args.smoke else 'candidate',
                      human_accepted=False, strict_delivery=False, heavy_task_concurrency=1)
        result.update(input_preflight={k: preflight_report[k] for k in ('status', 'warnings', 'source_language', 'page_count')},
                      resource_contract_frozen=freeze.get('resource_contract'))
        if args.route=='digital_pdf':result['routing_contract']=DIGITAL_ROUTING
        if args.route=='scanned_ocr':result['routing_contract']=OCR_ROUTING
        if args.action=='collect':result.update(stage='source_only_collect',candidate_generated=False)
        else:
            # 任何路线（电子 PDF、LaTeX）都把综合质量结论上浮到回执；fail 时退出码 3。
            result.update(quality_verdict(args.output))
            if args.route=='scanned_ocr':cap_ocr_quality(result)
        write_new(args.receipts / ('WORKFLOW_COLLECTION.json' if args.action=='collect' else 'WORKFLOW_CANDIDATE.json'), result)
    elif args.action == 'chunked-candidate':
        result = run_chunked_candidate(args)
    elif args.action == 'revise-latex':
        contract = read_json(args.contract)
        if contract.get('source_pdf_ref') != ref(args.input):
            raise ValueError('editorial source PDF identity mismatch')
        result = run_job(args, [sys.executable, str(SCRIPT_DIR/'latex_editorial_revision.py'),
            '--contract', str(args.contract.resolve()), '--output', str(args.output.resolve()),
            '--cjk-font', args.cjk_font], 'complete-unit-editorial-revision')
        result.update(stage='complete_unit_editorial_revision', input_ref=ref(args.input),
                      contract_ref=ref(args.contract), new_model_calls=0,
                      human_accepted=False, strict_delivery=False)
        result.update(quality_verdict(args.output))
        write_new(args.receipts/'WORKFLOW_EDITORIAL_REVISION.json', result)
    elif args.action == 'prepare-scan':
        result = prepare_scan_job(args)
    elif args.action == 'trial-render':
        result = trial_render_job(args)
    elif args.action == 'preserve-roles':
        contract = read_json(args.contract)
        if contract.get('source_pdf_ref') != ref(args.input):
            raise ValueError('protected-role source PDF identity mismatch')
        result = run_job(args, [sys.executable, str(SCRIPT_DIR/'protected_pdf_roles.py'),
            '--contract', str(args.contract.resolve()), '--output', str(args.output.resolve())],
            'source-bound-protected-role')
        result.update(stage='source_bound_protected_role', input_ref=ref(args.input),
                      contract_ref=ref(args.contract), new_model_calls=0,
                      human_accepted=False, strict_delivery=False)
        result.update(quality_verdict(args.output))
        write_new(args.receipts/'WORKFLOW_PROTECTED_ROLE.json', result)
    elif args.action == 'review':
        command = [sys.executable, str(SCRIPT_DIR / 'build_delivery_review_packet.py'),
                   '--source', str(args.input.resolve()), '--candidate', str(args.candidate.resolve()),
                   '--output', str(args.output.resolve()), '--max-pages', '5']
        result = run_job(args, command, 'review')
        write_new(args.receipts / 'WORKFLOW_REVIEW.json', result)
    elif args.action == 'preflight':
        result = preflight(args.packet, args.acceptance)
    elif args.action == 'preflight-finite':
        from finite_delivery import preflight_finite
        result = preflight_finite(args.packet, args.acceptance)
    elif args.action == 'deliver-finite':
        from finite_delivery import deliver_finite
        result = deliver_finite(args.packet, args.acceptance, args.output)
    else:
        result = deliver(args.packet, args.acceptance, args.output)
    if args.action in {'trial-render', 'run-reviewed-scan', 'continue-digital'} and 'quality_status' not in result:
        # 这些动作的回执由各自流程写出；若产出了综合质量结论，另写一份结论回执并上浮。
        for directory in quality_output_dirs(args, result):
            verdict = quality_verdict(directory)
            if verdict:
                result.update(verdict, quality_output_dir=str(directory))
                receipts = getattr(args, 'receipts', None)
                if receipts and Path(receipts).is_dir() and not (Path(receipts) / 'WORKFLOW_QUALITY_VERDICT.json').exists():
                    write_new(Path(receipts) / 'WORKFLOW_QUALITY_VERDICT.json', verdict)
                break
    return result


if __name__ == '__main__':
    raise SystemExit(main())
