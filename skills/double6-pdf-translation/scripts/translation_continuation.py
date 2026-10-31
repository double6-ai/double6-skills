"""默认按页续译；局部保留原文并单列报告，只有全局故障才停止调度。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

POLICY = 'local_preserve_v1'

# B6（编排优化，2026-10-31）：高置信电子页分层跳过——仅对"多信号合取高置信 +
# 页型历史全通过"的原生电子页跳过盲区审计与 usable_candidate 重核。
LIGHT_REVIEW_MIN_HISTORY = 3


def _light_review_history_path():
    from runtime_paths import workspace_root
    return workspace_root() / 'projects/paper-translation/light-review-history.jsonl'


def _light_review_history(profile):
    """页型历史（真实审计记录，跳过页不计入）：次数与盲区命中数。文件缺失/损坏视为无历史。"""
    path = _light_review_history_path()
    count = blindspot_hits = 0
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if tuple(row.get('profile') or ()) == tuple(profile):
                count += 1
                if row.get('blindspot_codes'):
                    blindspot_hits += 1
    except (OSError, ValueError, TypeError):
        return {'count': 0, 'blindspot_hits': 0}
    return {'count': count, 'blindspot_hits': blindspot_hits}


def _record_light_review(profile, blindspot_codes):
    """追加一条真实审计历史（append-only；单任务串行写，无并发争用）。"""
    path = _light_review_history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'profile': list(profile),
                                     'blindspot_codes': list(blindspot_codes),
                                     'at': datetime.now().isoformat(timespec='seconds')},
                                    ensure_ascii=False) + '\n')
    except OSError:
        pass  # 历史记录失败只影响后续跳过资格，不影响本次审计行为


def _light_review_decision(output_dir, args):
    """高置信门（保守多信号合取）。返回跳过依据；None 表示照常全量审计。

    显式标注（不可静默）：跳过信息写入页 row 的 light_review_skipped 字段与审校记录。"""
    if os.environ.get('PAPER_TRANSLATION_DISABLE_LIGHT_REVIEW') == '1':
        return None
    facts = getattr(args, 'page_preflight_facts', None)
    if not facts or facts.get('kind') != 'native_text':
        return None
    try:
        quality = read(Path(output_dir) / 'comprehensive_quality.json')
    except (OSError, ValueError):
        return None
    tech = quality.get('technical_check') or {}
    residue = quality.get('render_residue_check') or {}
    hot_residue = [p for p in residue.get('pages', [])
                   if p.get('evaluated') and p.get('severity') in ('high', 'medium')]
    fallback_count = (quality.get('overflow_source_fallback_check') or {}).get('count')
    if (quality.get('issues') or []) or (tech.get('issues') or []) or (tech.get('pending') or []) or hot_residue:
        return None
    if (quality.get('formula_structure_check') or {}).get('severity') != 'ok':
        return None
    if (quality.get('readable_output') or {}).get('status') != 'ok':
        return None
    if fallback_count:
        return None
    profile = ('digital_pdf', 'native_text', (facts.get('source_language') or {}).get('language'))
    history = _light_review_history(profile)
    if history['count'] < LIGHT_REVIEW_MIN_HISTORY or history['blindspot_hits']:
        return None
    return {'profile': list(profile), 'history_pass': history['count'],
            'gate': 'b6_high_confidence_v1', 'skipped': ['usable_candidate_recheck', 'audit_blindspots']}


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


# 终局双语件方向不得按目标语言反推源语言。依据优先级：① 各页 render_manifest 的
# source_language（取多数）→ ② 显式声明环境变量 → ③ 输入文字脚本检测 →
# ④ 都没有时沿用旧默认（目标 zh 视源 en），保证既有 en/zh 流程逐字不变。
def _resolved_document_source_language(document, rows, target_language):
    votes: dict[str, int] = {}
    for row in rows:
        language = None
        if row.get('target'):
            render = Path(row['target']['path']).parent / 'render_manifest.json'
            if render.is_file():
                try:
                    language = read(render).get('source_language')
                except (OSError, ValueError, TypeError):
                    language = None
        if language in {'ja', 'ko', 'en', 'zh'}:
            votes[language] = votes.get(language, 0) + 1
    if votes:
        best = max(sorted(votes), key=lambda key: votes[key])
        return best, 'page_manifests', {'votes': votes}
    declared = os.environ.get('PAPER_TRANSLATION_SOURCE_LANGUAGE', '').strip().lower()
    if declared in {'ja', 'ko', 'en', 'zh'}:
        return declared, 'declared_env', None
    try:
        from pdf_input_preflight import detect_language
        text = '\n'.join(document[index].get_text() for index in range(min(3, len(document))))
        language = detect_language(text).get('language')
    except Exception:
        language = None
    if language in {'ja', 'ko', 'en', 'zh'}:
        return language, 'input_detection', None
    return ('en' if target_language == 'zh' else 'zh'), 'target_default', None


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
    if re.search(r'configured_model_identity_mismatch|\bmodel_not_found\b|\bunknown model\b|\binvalid model\b|model[^\n]{0,40}does not exist', text, re.I):
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
    return target, None


def run_page(page_pdf, directory, args, closure):
    import paper_translation_workflow as workflow
    from bounded_execution import run_bounded
    from pdf_input_preflight import classify_page
    import fitz
    page_started=time.monotonic()
    directory.mkdir(parents=True)
    route = 'digital_pdf'
    limits = args.resource_limits
    scope = directory / 'scope.json'
    write(scope, {'pages': [1], 'complete_semantic_scope': True,
                  'document_page': args.document_page, 'source_ref': reference(page_pdf),
                  'scope': '本页全部可见内容；跨页句子可保持未完成，不补入说明。'})
    # B5（编排优化，2026-10-31）：translate 主进程拆页时的 classify_page/detect_language
    # 结论写入页级预检事实文件并冻结引用——candidate 侧据此跳过对同一页 PDF 的预检
    # 子进程重跑（页任务首页仍真跑子进程预检作抽样复核，见 candidate_input_preflight
    # 的复用门）。拒绝语义不变：密码件/页数超限/数字页在首次进入（主进程与首页子进程）
    # 拦截，逐字同码。
    preflight_facts = getattr(args, 'page_preflight_facts', None)
    facts_path = directory / 'input-preflight-facts.json'
    if preflight_facts is not None:
        write(facts_path, {'input': reference(page_pdf), 'page_count': 1,
                           'document_page': args.document_page,
                           'target_language': args.target_language, **preflight_facts})
    fingerprint = directory / 'model.json'
    write(fingerprint, {'model_id': args.model, 'endpoint': args.base_url})
    frozen = {'input': reference(page_pdf), 'pages': [1], 'complete_semantic_scope': True,
              'scope_evidence': reference(scope), 'route': route, 'model': args.model,
              'target_language': args.target_language,
              **({'preflight_facts_ref': reference(facts_path)} if preflight_facts is not None else {}),
              'hymt_proxy_mode': str(getattr(args, 'hymt_compat_proxy', 'auto') or 'auto'),
              'routing_contract': workflow.DIGITAL_ROUTING,
              'model_fingerprint_ref': reference(fingerprint),
              # 修订 135：hy-mt 代理仅在译中且未显式关闭时必需（en 目标 auto 跳过代理，
              # 见 pdf_translation_render.py；与 paper_translation_workflow 的合同校验同构推导）
              'proxy_quality_contract': {'adapter': 'hymt_compat' if ('hy-mt' in args.model.lower()
                                          and args.target_language == 'zh'
                                          and str(getattr(args, 'hymt_compat_proxy', 'auto') or 'auto') != 'off') else 'none',
                                         'required': 'hy-mt' in args.model.lower()
                                                     and args.target_language == 'zh'
                                                     and str(getattr(args, 'hymt_compat_proxy', 'auto') or 'auto') != 'off'},
              'resource_contract': {k: limits[k] for k in ('task_rss_bytes', 'per_job_seconds', 'memory_metric')} | {'concurrency': 1},
              'entrypoint': reference(workflow.__file__), 'rules': reference(Path(workflow.SCRIPT_DIR).parent / 'references/academic-translation-policy.md'),
              'standard': reference(Path(workflow.SCRIPT_DIR).parent / 'references/quality-and-delivery-contract.md'),
              'implementation_refs': closure, 'continuation_policy': POLICY,
              'backend_environment': {'BABELDOC_ONNX_PROVIDER': 'cpu'}}
    if os.environ.get('PAPER_TRANSLATION_ENGINE_HOME'):
        frozen['backend_environment']['PAPER_TRANSLATION_ENGINE_HOME'] = os.environ['PAPER_TRANSLATION_ENGINE_HOME']
    freeze = directory / 'FREEZE.json'; write(freeze, frozen)
    arguments = ['candidate', '--input', str(page_pdf), '--freeze', str(freeze), '--route', route,
        '--model', args.model, '--base-url', args.base_url, '--target-language', args.target_language,
        '--local-max-concurrency', str(args.local_max_concurrency or 1), '--output', str(directory/'output'),
        '--receipts', str(directory/'receipts')]
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
    if fatal:
        return {'fatal': fatal, 'status': 'original_preserved', 'issues': [fatal]}
    if job.get('status') == 'stopped' or result.get('status') not in {'succeeded', 'candidate', 'ready'}:
        target, error = None, result.get('error_code') or job.get('stop_reason') or 'page_translation_unavailable'
    else:
        # B6：高置信电子页（多信号合取 + 页型历史全通过）跳过 usable_candidate 重核，
        # 只保留候选存在性与身份一致性（reference 可算即文件未被改动）。
        light = _light_review_decision(directory/'output', args)
        if light is not None:
            candidates = sorted(Path(directory/'output').glob('*.no_watermark.*.mono.pdf'))
            if not candidates:
                target, error = None, 'page_translation_unavailable'
            else:
                target, error = candidates[0], None
                reference(target)  # 存在性与 sha256 一致性锚点（读取失败即抛，等同原文保留路径）
                result['light_review_skipped'] = light
        else:
            target, error = usable_candidate(directory/'output', None)
    issues = []
    if error:
        issues.append(result.get('error_code') or error)
    if result.get('quality_status') == 'fail':
        issues.append('quality_review_required')
    # 审计盲区检查（2026-10-31）：行尾截断守恒 + 写回墨迹覆盖率抽查。
    # 只上浮 issue code 进审校记录与详表回执,不改路由/重试/交付判定。
    # B6：高置信页跳过盲区审计（light_review_skipped 显式标注，历史只记真实审计）。
    if target and not result.get('light_review_skipped'):
        try:
            from audit_blindspots import audit_page_blindspots
            blindspot = audit_page_blindspots(str(target), 1)
            if getattr(args, 'page_preflight_facts', None) \
                    and args.page_preflight_facts.get('kind') == 'native_text':
                profile = ('digital_pdf', 'native_text',
                           (args.page_preflight_facts.get('source_language') or {}).get('language'))
                _record_light_review(profile, blindspot['codes'])
            if blindspot['codes']:
                issues += blindspot['codes']
                write(directory / 'receipts/audit/BLINDSPOT_AUDIT.json', blindspot)
        except Exception:
            # 审计器自身故障不拦交付,但显式留痕,防静默失效
            issues.append('blindspot_audit_unavailable')
    return {'status': 'translated' if target else 'original_preserved',
            'target': reference(target) if target else None, 'issues': list(dict.fromkeys(issues)),
            # B6：高置信跳过标注随页返回（审校记录与页 row 双留痕，不可静默）
            **({'light_review_skipped': result['light_review_skipped']} if result.get('light_review_skipped') else {})}


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
            # 只沿用本运行已经完成的前页真实术语，未完成/未来页不参与。
            terms={}
            for n,row in sorted(completed.items()):
                if n<=index and row.get('target'):
                    for term in row.get('document_glossary',[]):terms.setdefault(term['source'],term)
            args.document_glossary=list(terms.values())
            if reference(source) != identity['input']:
                return {'status': 'blocked', 'error_code': 'source_changed_during_translation', 'state': str(state_path)}
            previous = completed.get(index+1)
            if previous and previous['status'] in {'translated', 'already_target_language', 'blank_preserved'} and previous.get('target'):
                p = Path(previous['target']['path'])
                if p.is_file() and reference(p) == previous['target']:
                    continue
            page = document[index]
            facts = classify_page(page)
            # B5：主进程拆页事实（页分类 + 源语言判定）随页传递，供 candidate 侧预检复用
            # （首页 first_page=True 仍真跑子进程预检，非首页跳过重跑；拒绝语义见 run_page）。
            args.page_preflight_facts = {'kind': facts['kind'],
                                         'source_language': detect_language(page.get_text()),
                                         'first_page': index == 0}
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
        # 基线页结果保持不可变，跨页排版只用于本次拼版视图；恢复不会重复搬移标题。
        rows=state['pages']
        completed={r['page']:r for r in rows}
        translated = sum(r['status'] in {'translated','partially_translated'} for r in rows)
        formal = output/('译文.pdf' if translated else '原文保留稿.pdf')
        bilingual_page_map = []
        with fitz.open() as merged:
            for i in range(len(document)):
                row = completed[i+1]
                if row.get('target'):
                    with fitz.open(row['target']['path']) as part:
                        bilingual_page_map.extend([i] * len(part))
                        merged.insert_pdf(part)
                else:
                    bilingual_page_map.append(i)
                    merged.insert_pdf(document, from_page=i, to_page=i)
            temp = output/'译文.tmp.pdf';merged.save(temp,garbage=4,deflate=True);temp.replace(formal)
        from build_bilingual_pdf import build_en_left_zh_right_pdf, bilingual_direction
        dual = output/'原文左-译文右.pdf'
        bilingual_options = {'source_page_map': bilingual_page_map} if len(bilingual_page_map) != len(document) else {}
        # B1（编排优化，2026-10-31）：单页任务直接提升页级 dual 为任务级双语件。
        # 页任务 backend 已产出 source.*.dual.pdf；任务级 build_en_left_zh_right_pdf 用
        # 译文.pdf+原文重建一遍，实测两者同源配对。复用条件（保守）：单页、无页映射
        # 重排、目标 zh、render_manifest 登记的 translated_pdf 与本页 target 为同一文件
        # （dual 与 mono 同源配对，防 QA 重渲染错配）。不满足或核对失败一律回退原构建
        # 路径；PAPER_TRANSLATION_DISABLE_DUAL_REUSE=1 可关。
        dual_reuse = None
        if (len(document) == 1 and not bilingual_options and rows
                and args.target_language == 'zh'
                and os.environ.get('PAPER_TRANSLATION_DISABLE_DUAL_REUSE') != '1'):
            target_ref = rows[0].get('target')
            if target_ref:
                try:
                    outputs = (read(Path(target_ref['path']).parent / 'render_manifest.json').get('outputs') or {})
                    backend_dual = outputs.get('dual_pdf')
                    if (backend_dual and outputs.get('translated_pdf')
                            and Path(outputs['translated_pdf']).resolve() == Path(target_ref['path']).resolve()
                            and Path(backend_dual).is_file()):
                        dual_reuse = Path(backend_dual)
                except (OSError, ValueError, KeyError, TypeError):
                    dual_reuse = None
        # 终局双语件方向按实际源语言取（页 render_manifest 多数 > 声明环境变量 > 输入
        # 检测 > 旧默认），ja/ko 源不再被错标"英文原文"；页序合同（左源右译）不变。
        # 证据随终局回执留痕。
        doc_source_language, source_basis, source_votes = _resolved_document_source_language(document, rows, args.target_language)
        bilingual_direction_evidence = {'source_language': doc_source_language, 'basis': source_basis,
                                        'detail': source_votes}
        if dual_reuse is not None:
            import shutil
            shutil.copyfile(dual_reuse, dual)
            rows[0]['bilingual_reuse'] = {'source_ref': reference(dual_reuse),
                                          'basis': 'single_page_backend_dual_identity'}
        else:
            build_en_left_zh_right_pdf(source, formal, dual, mode='vector',
                                     direction=bilingual_direction(doc_source_language, args.target_language,
                                                                   basis='resolved_document_source_language'),
                                     **bilingual_options)
        retained = sum(r['status']=='original_preserved' for r in rows)
        partial = sum(r['status']=='partially_translated' for r in rows)
        warnings = retained or partial or any(r['issues'] for r in rows)
        status = ('completed_with_warnings' if warnings else 'completed') if translated else (
            'already_target_language' if not retained else 'blocked')
        result = {'status': status, 'translated_pages': translated, 'original_preserved_pages': retained,
                  'partially_translated_pages': partial, 'page_count': len(rows), 'pages': rows,
                  'output_pdf': reference(formal), 'translated_pdf': reference(formal) if translated else None,
                  'preserved_pdf': reference(formal) if not translated else None, 'bilingual_pdf': reference(dual),
                  'bilingual_direction_source': bilingual_direction_evidence,
                  'source_scope_complete': True, 'translation_complete': retained==partial==0,
                  'quality_status': 'unverified', 'human_acceptance': False, 'strict_delivery': False,
                  'output': str(output), 'resume_supported': True}
        if status == 'blocked':
            result['error_code'] = 'no_pages_translated'
        write(output/'翻译报告.json', result)
        lines = ['# 翻译审校记录', '', f'共{len(rows)}页，翻译{translated}页，局部保留原文{partial}页，整页保留原文{retained}页。',
                 '这些记录不插入正式译文。', '']
        lines += [f'- 第{r["page"]}页：{r["status"]}；'+'、'.join(r['issues']) for r in rows if r['issues']]
        # B6：高置信跳过页显式披露（不进 issues，避免把高置信页误标 completed_with_warnings；
        # 审校记录与页 row 的 light_review_skipped 字段双留痕，供人工抽查，不可静默）。
        lines += [f'- 第{r["page"]}页：高置信跳过盲区审计与候选重核（light_review_skipped；'
                  f'页型 {"/".join(str(x) for x in r["light_review_skipped"]["profile"])}，'
                  f'历史真实审计通过 {r["light_review_skipped"]["history_pass"]} 次）'
                  for r in rows if r.get('light_review_skipped')]
        (output/'翻译审校记录.md').write_text('\n'.join(lines)+'\n')
        return result


SCRIPT_INTERFACE = 'internal-module'
SCRIPT_INTERFACE_REASON = '由主入口 translate 调用；页级执行仍走原有资源与进程回收。'
