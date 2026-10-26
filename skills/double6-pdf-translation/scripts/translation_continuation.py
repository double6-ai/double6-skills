"""默认按页续译；局部保留原文并单列报告，只有全局故障才停止调度。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

POLICY = 'local_preserve_v1'


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def read(path):
    return json.loads(Path(path).read_text())


def fatal_reason(result, job):
    if job.get('cleanup', {}).get('confirmed') is False or job.get('status') == 'cleanup_unconfirmed':
        return 'owned_tree_cleanup_unconfirmed'
    stop = job.get('stop_reason')
    if stop in {'system_memory_pressure', 'codex_memory_fuse', 'owned_process_monitor_unavailable'}:
        return stop
    text = ' '.join(str(result.get(k, '')) for k in ('error_code', 'exception_message', 'message', 'root_cause', 'findings'))
    text += ' ' + str(job.get('command', {}).get('stderr_summary', ''))
    if re.search(r'(?:HTTP\S*|status(?:_code)?|Error(?: code)?|Unauthorized)\s*[:=]?\s*(?:401|403)\b', text, re.I):
        return 'provider_authentication_failed'
    if re.search(r'remote_backend_requires_explicit_api_key|invalid_api_key|authentication_error|permission_denied', text, re.I):
        return 'provider_authentication_failed'
    if re.search(r'insufficient_quota|credit_balance|payment_required', text, re.I):
        return 'provider_quota_unavailable'
    if re.search(r'\bmodel_not_found\b|\bunknown model\b|\binvalid model\b|model[^\n]{0,40}does not exist', text, re.I):
        return 'configured_model_unavailable'
    return None


def usable_candidate(directory, manifest):
    """坏页原样保留。可定位原图区域不能被新译文字覆盖，避免半成品叠字。"""
    import fitz
    candidates = sorted(Path(directory).glob('*.no_watermark.*.mono.pdf'))
    if not candidates:
        return None, 'page_translation_unavailable'
    target = candidates[0]
    quality_path = Path(directory) / 'comprehensive_quality.json'
    quality = read(quality_path) if quality_path.exists() else {}
    codes = str(quality.get('issues', []))
    if quality.get('status') == 'fail' and re.search(r'overlap|collision|script_structure_lost|glyph_loss|codepoint_loss|placeholder', codes, re.I):
        return None, 'page_content_integrity_risk'
    with fitz.open(target) as doc:
        if len(doc) != 1:
            return None, 'page_mapping_changed'
        text = doc[0].get_text()
        if not text.strip() or any(ord(c) < 32 and c not in '\n\r\t' for c in text) or '\ufffd' in text:
            return None, 'page_text_unreadable'
        regions = []
        for p in (manifest or {}).get('pages', []):
            for item in p.get('preserved_regions', []):
                regions.append(fitz.Rect([v * 72 / manifest['render_dpi'] for v in item['bbox_px']]))
        for block in doc[0].get_text('dict')['blocks']:
            for line in block.get('lines', []):
                for span in line['spans']:
                    box = fitz.Rect(span['bbox'])
                    if any((box & region).get_area() > .1 for region in regions):
                        return None, 'translated_text_over_preserved_source'
        if regions:
            # 字框不相交仍可能被后端白底擦掉；实际核对保留区，严重改变才退回原页。
            import numpy as np
            source_ref = manifest.get('reconstructed_source', {})
            source = Path(source_ref.get('path', ''))
            if not source.is_file() or reference(source)['sha256'] != source_ref.get('sha256'):
                return None, 'preserved_source_unverifiable'
            # 提取图文dict后同一MuPDF对象可能残留图像颜色/缓存状态；像素核对重新打开磁盘PDF。
            with fitz.open(source) as original, fitz.open(target) as rendered:
                for region in regions:
                    a = original[0].get_pixmap(matrix=fitz.Matrix(2,2), clip=region, colorspace=fitz.csGRAY)
                    b = rendered[0].get_pixmap(matrix=fitz.Matrix(2,2), clip=region, colorspace=fitz.csGRAY)
                    if (a.width,a.height)!=(b.width,b.height):
                        return None, 'preserved_source_geometry_changed'
                    before = np.frombuffer(a.samples, np.uint8).astype(float)
                    after = np.frombuffer(b.samples, np.uint8).astype(float)
                    ink = before < 160
                    ink_loss = float((after[ink] >= 160).mean()) if ink.any() else 0
                    if float(np.abs(before-after).mean()) > 2 or ink_loss > .1:
                        return None, 'preserved_source_damaged'
    return target, None


def run_page(page_pdf, directory, args, closure):
    import paper_translation_workflow as workflow
    from bounded_execution import run_bounded
    from pdf_input_preflight import classify_page
    import fitz
    directory.mkdir(parents=True)
    with fitz.open(page_pdf) as doc:
        kind = classify_page(doc[0])['kind']
    route = 'digital_pdf' if kind == 'native_text' else 'scanned_ocr'
    limits = args.resource_limits
    scope = directory / 'scope.json'
    write(scope, {'pages': [1], 'complete_semantic_scope': True,
                  'document_page': args.document_page, 'source_ref': reference(page_pdf),
                  'scope': '本页全部可见内容；跨页句子可保持未完成，不补入说明。'})
    fingerprint = directory / 'model.json'
    write(fingerprint, {'model_id': args.model, 'endpoint': args.base_url})
    frozen = {'input': reference(page_pdf), 'pages': [1], 'complete_semantic_scope': True,
              'scope_evidence': reference(scope), 'route': route, 'model': args.model,
              'routing_contract': workflow.DIGITAL_ROUTING if route == 'digital_pdf' else workflow.OCR_ROUTING,
              'model_fingerprint_ref': reference(fingerprint),
              'proxy_quality_contract': {'adapter': 'hymt_compat' if 'hy-mt' in args.model.lower() else 'none',
                                         'required': 'hy-mt' in args.model.lower()},
              'resource_contract': {k: limits[k] for k in ('task_rss_bytes', 'per_job_seconds', 'memory_metric')} | {'concurrency': 1},
              'entrypoint': reference(workflow.__file__), 'rules': reference(Path(workflow.SCRIPT_DIR).parent / 'references/academic-translation-policy.md'),
              'standard': reference(Path(workflow.SCRIPT_DIR).parent / 'references/quality-and-delivery-contract.md'),
              'implementation_refs': closure, 'continuation_policy': POLICY,
              'backend_environment': {'BABELDOC_ONNX_PROVIDER': 'cpu'}}
    if os.environ.get('PAPER_TRANSLATION_ENGINE_HOME'):
        frozen['backend_environment']['PAPER_TRANSLATION_ENGINE_HOME'] = os.environ['PAPER_TRANSLATION_ENGINE_HOME']
    if route == 'scanned_ocr':
        frozen['ocr_failure_policy'] = 'preserve_regions'
    freeze = directory / 'FREEZE.json'; write(freeze, frozen)
    arguments = ['candidate', '--input', str(page_pdf), '--freeze', str(freeze), '--route', route,
        '--model', args.model, '--base-url', args.base_url, '--target-language', args.target_language,
        '--local-max-concurrency', str(args.local_max_concurrency or 1), '--output', str(directory/'output'),
        '--receipts', str(directory/'receipts')]
    if route == 'scanned_ocr':
        arguments.append('--ocr-preserve-local')
    result_path = directory / 'candidate-result.json'
    config = directory / 'job.json'; write(config, {'arguments': arguments, 'result': str(result_path)})
    job = run_bounded([sys.executable, str(Path(__file__).with_name('continuation_page_job.py')), str(config)],
        cwd=directory, receipt_dir=directory/'outer-process', operation='translate-page',
        timeout_seconds=limits['per_job_seconds'], interval_seconds=.5, rss_limit=limits['task_rss_bytes'],
        max_processes=16, memory_metric=limits['memory_metric'], max_total_fraction=limits['max_total_fraction'], env=dict(os.environ))
    write(directory/'bounded-result.json', job)
    try:
        result = read(result_path)
    except (OSError, ValueError):
        result = {'error_code': job.get('stop_reason') or 'page_worker_failed'}
    fatal = fatal_reason(result, job)
    manifest_path = directory/'receipts/ocr/OCR_MANIFEST.json'
    manifest = read(manifest_path) if manifest_path.exists() else None
    if fatal:
        return {'fatal': fatal, 'status': 'original_preserved', 'issues': [fatal]}
    if job.get('status') == 'stopped' or result.get('status') not in {'succeeded', 'candidate', 'ready'}:
        target, error = None, result.get('error_code') or job.get('stop_reason') or 'page_translation_unavailable'
    else:
        target, error = usable_candidate(directory/'output', manifest)
    issues = []
    if error:
        issues.append(result.get('error_code') or error)
    if manifest:
        issues.append('ocr_text_unverified')
        for p in manifest['pages']:
            issues += [f['code'] for f in p.get('warnings', [])]
            if p.get('preserved_regions'):
                issues.append('local_source_regions_preserved')
    if result.get('quality_status') == 'fail':
        issues.append('quality_review_required')
    local_preserved = bool(manifest and any(p.get('preserved_regions') for p in manifest['pages']))
    return {'status': ('partially_translated' if local_preserved else 'translated') if target else 'original_preserved',
            'target': reference(target) if target else None, 'issues': list(dict.fromkeys(issues)),
            'ocr_manifest_ref': reference(manifest_path) if manifest else None}


def run(args, page_runner=None):
    import fitz
    import paper_translation_workflow as workflow
    from chunked_workflow import run_lock, reclaim_stale
    from pdf_input_preflight import classify_page, detect_language
    source = Path(args.input).resolve()
    try:
        document = fitz.open(source)
        if document.needs_pass or not len(document):
            document.close()
            return {'status': 'blocked', 'error_code': 'password_required_or_empty_pdf'}
    except Exception:
        return {'status': 'blocked', 'error_code': 'pdf_unreadable'}
    output = Path(args.output).resolve()
    if output.exists() and not args.resume:
        output = output / ('run-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=True)
    state_path = output/'TRANSLATION_STATE.json'
    skill = Path(__file__).resolve().parents[1]
    closure = [reference(p) for p in sorted(skill.rglob('*.py')) if 'tests' not in p.parts and '__pycache__' not in p.parts]
    identity = {'input': reference(source), 'model': args.model, 'base_url': args.base_url,
                'target_language': args.target_language, 'policy': POLICY,
                'runtime_sha256': hashlib.sha256(json.dumps(closure, sort_keys=True).encode()).hexdigest(),
                'configuration_refs': [reference(skill / name) for name in ('configs/model-profiles.json',
                    'configs/default-routes.json', 'references/academic-translation-policy.md',
                    'references/quality-and-delivery-contract.md')],
                'generation': {k: os.environ.get(k) for k in ('PDF_TRANSLATION_TEMPERATURE','PDF_TRANSLATION_OPENAI_REASONING_EFFORT',
                                                              'PDF_TRANSLATION_SYSTEM_PROMPT','PAPER_TRANSLATION_IGNORE_CACHE')},
                'request_concurrency': args.local_max_concurrency, 'resource_limits': args.resource_limits}
    state = {'identity': identity, 'pages': []}
    pages_root = Path(args.receipts).resolve()/'pages' if getattr(args, 'receipts', None) else output/'pages'
    if args.resume and state_path.exists():
        previous = read(state_path)
        if previous['identity'] != identity:
            document.close()
            args.output = output / ('changed-input-or-settings-' + datetime.now().strftime('%H%M%S-%f'))
            args.resume = False
            return run(args, page_runner=page_runner)
        pages_root = Path(previous.get('receipts_pages', str(pages_root)))
        recovery = reclaim_stale([pages_root])
        if not recovery['confirmed']:
            document.close()
            return {'status': 'blocked', 'error_code': 'owned_tree_cleanup_unconfirmed', 'recovery': recovery}
        state = previous
    state['receipts_pages'] = str(pages_root)
    page_runner = page_runner or run_page
    with document, run_lock(output/'continuation.lock'):
        model_checked = False
        completed = {r['page']: r for r in state['pages']}
        for index in range(len(document)):
            if reference(source) != identity['input']:
                return {'status': 'blocked', 'error_code': 'source_changed_during_translation', 'state': str(state_path)}
            previous = completed.get(index+1)
            if previous and previous['status'] in {'translated', 'already_target_language', 'blank_preserved'} and previous.get('target'):
                p = Path(previous['target']['path'])
                if p.is_file() and reference(p) == previous['target']:
                    continue
            page = document[index]
            facts = classify_page(page)
            blank = not page.get_text().strip() and not page.get_images() and not page.get_drawings()
            if blank or (facts['kind'] == 'native_text' and detect_language(page.get_text())['language'] == args.target_language):
                result = {'status': 'blank_preserved' if blank else 'already_target_language', 'issues': []}
                page_dir = pages_root/f'{index+1:05d}'/('unchanged-'+datetime.now().strftime('%H%M%S-%f'));page_dir.mkdir(parents=True)
                piece = page_dir/'source.pdf'
                with fitz.open() as part:
                    part.insert_pdf(document, from_page=index, to_page=index);part.save(piece)
                result['target'] = reference(piece)
            else:
                page_dir = pages_root/f'{index+1:05d}'/('attempt-'+datetime.now().strftime('%H%M%S-%f'))
                page_dir.mkdir(parents=True)
                piece = page_dir/'source.pdf'
                with fitz.open() as part:
                    part.insert_pdf(document, from_page=index, to_page=index);part.save(piece)
                args.document_page = index+1
                # 全部完成页的恢复和本来就在目标语言的页，不依赖模型在线或翻译引擎库存。
                if page_runner is run_page and not model_checked:
                    health = workflow.doctor(args.base_url, args.model, permissive_inventory=True)
                    write(output/'environment.json', health)
                    if health['blockers']:
                        return {'status': 'blocked', 'error_code': 'translation_environment_unavailable', 'blockers': health['blockers']}
                    model_checked = True
                result = page_runner(piece, page_dir/'task', args, closure)
            result['page'] = index+1
            completed[index+1] = result
            state['pages'] = [completed[n] for n in sorted(completed)]
            write(state_path, state)
            if result.get('fatal'):
                return {'status': 'blocked', 'error_code': result['fatal'], 'state': str(state_path),
                        'completed_pages': len(completed)-1, 'resume_supported': True}
        translated = sum(r['status'] in {'translated','partially_translated'} for r in state['pages'])
        formal = output/('译文.pdf' if translated else '原文保留稿.pdf')
        with fitz.open() as merged:
            for i in range(len(document)):
                row = completed[i+1]
                if row.get('target'):
                    with fitz.open(row['target']['path']) as part:
                        merged.insert_pdf(part)
                else:
                    merged.insert_pdf(document, from_page=i, to_page=i)
            temp = output/'译文.tmp.pdf';merged.save(temp,garbage=4,deflate=True);temp.replace(formal)
        from build_bilingual_pdf import build_en_left_zh_right_pdf, bilingual_direction
        dual = output/'原文左-译文右.pdf'
        build_en_left_zh_right_pdf(source, formal, dual, mode='vector',
                                 direction=bilingual_direction('en' if args.target_language=='zh' else 'zh', args.target_language))
        rows = state['pages']
        retained = sum(r['status']=='original_preserved' for r in rows)
        partial = sum(r['status']=='partially_translated' for r in rows)
        warnings = retained or partial or any(r['issues'] for r in rows)
        status = ('completed_with_warnings' if warnings else 'completed') if translated else (
            'already_target_language' if not retained else 'blocked')
        result = {'status': status, 'translated_pages': translated, 'original_preserved_pages': retained,
                  'partially_translated_pages': partial, 'page_count': len(rows), 'pages': rows,
                  'output_pdf': reference(formal), 'translated_pdf': reference(formal) if translated else None,
                  'preserved_pdf': reference(formal) if not translated else None, 'bilingual_pdf': reference(dual),
                  'source_scope_complete': True, 'translation_complete': retained==partial==0,
                  'quality_status': 'unverified', 'human_acceptance': False, 'strict_delivery': False,
                  'output': str(output), 'resume_supported': True}
        if status == 'blocked':
            result['error_code'] = 'no_pages_translated'
        write(output/'翻译报告.json', result)
        lines = ['# 翻译审校记录', '', f'共{len(rows)}页，翻译{translated}页，局部保留原文{partial}页，整页保留原文{retained}页。',
                 '这些记录不插入正式译文。', '']
        lines += [f'- 第{r["page"]}页：{r["status"]}；'+'、'.join(r['issues']) for r in rows if r['issues']]
        (output/'翻译审校记录.md').write_text('\n'.join(lines)+'\n')
        return result


SCRIPT_INTERFACE = 'internal-module'
SCRIPT_INTERFACE_REASON = '由主入口 translate 调用；页级执行仍走原有资源与进程回收。'
