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
from cutover.scoped import check_scoped_preflight, sha

SCRIPT_DIR = Path(__file__).resolve().parent
from runtime_paths import workspace_root
ROOT = workspace_root()
PROJECT = ROOT / 'projects/paper-translation'
MODEL = None
ROUTES = {'digital_pdf': 'pdf_backend', 'latex_verified': 'latex_direct'}
DIGITAL_ROUTING = {'selection':'explicit_pdf_backend_only','complete_native_pages_required':True,
                   'latex_discovery':'disabled','scan_or_mixed':'rejected'}


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


def doctor(base_url, model=MODEL, provider_generation_required=True):
    """只检查首发必需项；扫描/OCR依赖不参与首发阻塞。"""
    dependencies = {name: importlib.util.find_spec(name) is not None
                    for name in ('fitz', 'psutil', 'PIL', 'requests', 'pdf2zh_next', 'babeldoc')}
    blockers = [f'missing_dependency:{name}' for name, present in dependencies.items() if not present]
    models = []
    if provider_generation_required:
        try:
            api_key = os.environ.get('LOCAL_TRANSLATION_API_KEY') or os.environ.get('OPENAI_API_KEY')
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
            'resources': {key: memory[key] for key in ('total', 'available', 'swap_used', 'codex')},
            'supported_routes': list(ROUTES)}


def validate_freeze(freeze, input_pdf, route, model):
    if route not in ROUTES:
        raise ValueError('route outside limited first release')
    if freeze.get('input') != ref(input_pdf):
        raise ValueError('input identity changed')
    pages = freeze.get('pages')
    if not isinstance(pages, list) or pages != list(range(1, len(pages) + 1)) or not 1 <= len(pages) <= 5:
        raise ValueError('complete input must contain 1–5 consecutive pages')
    if freeze.get('complete_semantic_scope') is not True or not freeze.get('scope_evidence'):
        raise ValueError('complete semantic scope evidence required')
    if freeze.get('route') != route or freeze.get('model') != model:
        raise ValueError('route or model differs from freeze')
    if route=='digital_pdf' and freeze.get('routing_contract')!=DIGITAL_ROUTING:
        raise ValueError('frozen explicit digital routing contract differs')
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
    if route=='digital_pdf':
        api_contract=bound_json(freeze['model_fingerprint_ref']).get('api_contract')
        if api_contract not in (None,'lmstudio_native_chat_v1'):raise ValueError('unknown frozen API contract')
        expected_proxy = 'source_bound_native' if api_contract else ('hymt_compat' if 'hy-mt' in model.lower() else 'none')
        if freeze.get('proxy_quality_contract') != {'adapter':expected_proxy,'required':expected_proxy!='none'}:
            raise ValueError('frozen proxy quality applicability missing or changed')
    if freeze.get('resource_contract') != {'task_rss_bytes': 3 * 1024**3, 'per_job_seconds': 120, 'concurrency': 1}:
        raise ValueError('frozen resource contract differs from current workflow')
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


def candidate_command(args, freeze):
    command = [sys.executable, str(SCRIPT_DIR / 'run_pdf_translation.py'), str(args.input.resolve()),
               '--output-dir', str(args.output.resolve()), '--model', args.model, '--base-url', args.base_url,
               '--local-max-concurrency', '1', '--timeout', '110', '--openai-timeout', '90',
               '--latex-render-timeout', '110', '--latex-translate-timeout', '90',
               '--latex-compile-timeout', '45', '--hymt-compat-proxy', 'auto', '--strict-delivery-gates']
    if freeze.get('model_fingerprint_ref') and bound_json(freeze['model_fingerprint_ref']).get('api_contract')=='lmstudio_native_chat_v1':
        command+=['--translation-transport','lmstudio_native_chat_v1','--translator-mode','openai']
    if args.route == 'latex_verified':
        command += ['--source-override', freeze['latex_source']['path'], '--latex-render-mode', 'required',
                    '--skip-pdf-backend-when-latex-direct']
    elif args.route=='digital_pdf':command+=['--pdf-backend-only','--latex-render-mode','off']
    if args.smoke:
        if args.route == 'latex_verified':
            raise ValueError('LaTeX smoke requires a separately frozen complete source project')
        command += ['--pages', '1']
    return command


def run_job(args, command, operation):
    with project_lock(args.lock_path):
        return run_bounded(command, cwd=ROOT, receipt_dir=args.receipts / operation, operation=operation,
            timeout_seconds=120, interval_seconds=2, rss_limit=3 * 1024**3, max_processes=8,
            deadline_monotonic=getattr(args,'task_deadline_monotonic',None),
            env={**os.environ, **getattr(args, 'frozen_environment', {}), 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})


def input_inspection_job(args):
    command = [sys.executable, str(SCRIPT_DIR/'scan_input_preflight.py'), '--input', str(args.input.resolve()),
               '--output', str(args.output.resolve()), '--max-pages', str(args.max_pages), '--catalog-url', args.catalog_url]
    for name in ('source_review', 'reuse_contract', 'model'):
        value = getattr(args, name, None)
        if value is not None:
            command += ['--'+name.replace('_', '-'), str(value)]
    if getattr(args, 'fresh', False):
        command.append('--fresh')
    result = run_job(args, command, 'bounded-input-inspection')
    result.update(report_ref=ref(args.output) if args.output.is_file() else None,
                  input_modified=False, new_OCR_MT_calls=0)
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
        args.task_deadline_monotonic = time.monotonic()+120
        common = dict(lock_path=args.lock_path, task_deadline_monotonic=args.task_deadline_monotonic)
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


def execute_digital(freeze_path, command):
    """子任务内核对真实页数和扫描路线，扫描禁止进入首发模型调用。"""
    import fitz
    import run_pdf_translation
    from scanned_raster.route_pdf import route_pdf
    freeze = read_json(freeze_path)
    args = run_pdf_translation.build_parser().parse_args(command)
    if freeze.get('route')!='digital_pdf' or freeze.get('routing_contract')!=DIGITAL_ROUTING or not args.pdf_backend_only or args.latex_render_mode!='off':
        raise ValueError('explicit digital route identity missing or changed')
    with fitz.open(args.input_pdf) as document:
        if list(range(1, len(document)+1)) != freeze['pages']:
            raise ValueError('actual PDF page scope differs from freeze')
    expected_transport=read_json(Path(freeze['model_fingerprint_ref']['path'])).get('api_contract') or 'openai_compatible'
    if args.translation_transport!=expected_transport or (expected_transport!='openai_compatible' and args.translator_mode!='openai'):
        raise ValueError('frozen explicit transport changed')
    route = route_pdf(Path(args.input_pdf), args=args)
    if route.get('document_route') != 'pdf_backend' or not route.get('dispatch_allowed'):
        raise ValueError('input is not a verified digital PDF route')
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
            p.add_argument('--source-cache-context',type=Path)
            p.add_argument('--source-cache-context-sha256')
        else:
            p.add_argument('--candidate', type=Path, required=True)
    for action in ('preflight', 'deliver', 'preflight-finite', 'deliver-finite'):
        p = sub.add_parser(action)
        p.add_argument('--packet', type=Path, required=True)
        p.add_argument('--acceptance', type=Path, required=True)
        if action in {'deliver', 'deliver-finite'}:
            p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'inspect-input':
        result = input_inspection_job(args)
    elif args.action == 'run-reviewed-scan':
        result = run_reviewed_scan(args)
    elif args.action == 'continue-digital':
        with project_lock(args.lock_path):
            result = continue_digital({'path':str(args.contract.resolve()),'sha256':args.contract_sha256},args.receipt)
    elif args.action == '_execute-digital':
        result = execute_digital(args.freeze, args.command[1:] if args.command[:1] == ['--'] else args.command)
    elif args.action == 'doctor':
        result = doctor(args.base_url, args.model)
        if args.output:
            write_new(args.output, result)
    elif args.action == 'resume-latex':
        if args.receipts.exists():
            raise ValueError('resume_requires_fresh_receipt_directory')
        freeze = read_json(args.freeze)
        pages = validate_freeze(freeze, args.input, 'latex_verified', args.model)
        args.frozen_environment = freeze.get('backend_environment', {})
        health = doctor(args.base_url, args.model)
        if health['blockers'] or not health['latex_ready']:
            raise ValueError('required environment not ready')
        result = run_latex_candidate(args, freeze, resume=True)
        result.update(freeze_ref=ref(args.freeze), input_ref=ref(args.input), route='latex_verified',
                      declared_pages=pages, stage='resumed_candidate', human_accepted=False,
                      strict_delivery=False, previous_result_ref=ref(args.previous_result))
        write_new(args.receipts/'WORKFLOW_RESUMED_CANDIDATE.json', result)
    elif args.action in ('candidate','collect'):
        freeze = read_json(args.freeze)
        pages = validate_freeze(freeze, args.input, args.route, args.model)
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
        if args.route=='digital_pdf':result['routing_contract']=DIGITAL_ROUTING
        if args.action=='collect':result.update(stage='source_only_collect',candidate_generated=False)
        write_new(args.receipts / ('WORKFLOW_COLLECTION.json' if args.action=='collect' else 'WORKFLOW_CANDIDATE.json'), result)
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'ready', 'succeeded', 'ready_for_delivery', 'delivered', 'candidate', 'source_only_collected'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
