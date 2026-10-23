# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-23：2.0.0-rc.9 新增（长文档分块翻译）；变更见Skill根目录MODIFICATIONS.md。
"""``paper_translation_workflow.py chunked-candidate`` 的编排：每块一个有界 candidate 任务，按页序合并。

* 整份文档：有界输入预检（最多 ``CHUNKING_CONTRACT['max_document_pages']`` 页）→ 冻结校验（parent FREEZE
  声明完整页数 + 冻结分块合同）→ doctor → 有界 ``chunk-plan`` 任务。
* 每块：派生块级 FREEZE（块 PDF 身份、页数 1..k、作用域证据指向 parent FREEZE 与计划、块路线及其
  既有路由合同、整份术语上下文绑定），以 ``candidate`` 动作原样执行——单份 candidate 的全部门
  （预检、路由、OCR 守门、质量门、拥有式计量与回收）逐块生效，单块单任务预算即 FREEZE 资源合同。
* 资源停止（超时/超内存）的块二分到单页；单页仍超限即失败关闭并记录实测。瞬时失败重试一次；
  预检拦截与质量 fail 不重试（结果确定）。
* 任何一块没有产物：整份 ``blocked``（``chunk_failed``，退出码 2），不合并、不交付部分结果。
  全部有产物：有界 ``chunk-merge`` 任务按页序合并并写合并综合质量（不好于最差的一块，fail 退出码 3）。
* 状态 ``CHUNKED_RUN_STATE.json`` 原子替换；每次尝试先登记 started 再执行。``--resume``：先回收上次
  遗留的本任务进程树（按 launch 回执的 PID + create_time + nonce），无法核实即失败关闭；已完成块的
  块 PDF、块 FREEZE、产物、综合质量与回执逐 sha 核对一致才复用，否则重跑。
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any

STATE_NAME = 'CHUNKED_RUN_STATE.json'
RECEIPT_NAME = 'WORKFLOW_CHUNKED_CANDIDATE.json'
# 回执里登记并在复用前逐 sha 核对的块产物（相对块尝试目录）。
OUTPUT_ROLES = ('translated_pdf', 'readable_repaired_pdf')


def save_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def run_lock(path: Path):
    """同一输出目录同时只允许一个编排进程（另一进程持锁即 RuntimeError → project_lock_busy 风格拦截）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'chunked run already active for {path.parent}') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


# ------------------------------------------------------------------ 遗留进程回收
def _live_owner_nonces() -> set[str]:
    import psutil
    found: set[str] = set()
    for pid in psutil.pids():
        try:
            value = psutil.Process(pid).environ().get('PAPER_TRANSLATION_BOUNDED_OWNERS', '')
        except (psutil.Error, OSError):
            continue
        found.update(filter(None, value.split(',')))
    return found


def reclaim_stale(roots: list[Path]) -> dict[str, Any]:
    """扫描本次运行目录下所有 launch 回执；仍有存活成员（根进程、原进程组或继承 nonce 的进程）的
    逐个以 ``reclaim_owned_tree(discovery_failed=True)`` 回收并核实。任何一个未核实即 confirmed=False。"""
    from bounded_execution import _group_empty, _identity_state, reclaim_owned_tree
    nonces = _live_owner_nonces()
    report: dict[str, Any] = {'confirmed': True, 'receipts_scanned': 0, 'reclaimed': [], 'already_gone': 0}
    for root in roots:
        if not root.exists():
            continue
        for receipt in sorted(root.rglob('*.launch.json')):
            report['receipts_scanned'] += 1
            try:
                identity = json.loads(receipt.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                report['confirmed'] = False
                report['reclaimed'].append({'receipt': str(receipt), 'error': f'{type(exc).__name__}: {exc}'[:200]})
                continue
            state = _identity_state(int(identity['pid']), float(identity['created_at']))[0]
            pgid = identity.get('process_group')
            group_busy = bool(pgid) and pgid == identity.get('pid') and state != 'pid_reused' and _group_empty(pgid) is False
            if state not in ('alive', 'zombie', 'unknown') and not group_busy and identity.get('nonce') not in nonces:
                report['already_gone'] += 1
                continue
            outcome = reclaim_owned_tree(identity, {}, time.monotonic() + 15, discovery_failed=True,
                                         nonce=identity.get('nonce'))
            report['reclaimed'].append({'receipt': str(receipt), 'pid': identity.get('pid'),
                                        'root_state': state, 'group_busy': group_busy,
                                        'confirmed': outcome.get('confirmed'), 'status': outcome.get('status'),
                                        'unverified': outcome.get('unverified')})
            if not outcome.get('confirmed'):
                report['confirmed'] = False
    return report


def attempt_nonces(attempt: Path) -> set[str]:
    nonces = set()
    for receipt in attempt.rglob('*.launch.json'):
        try:
            value = json.loads(receipt.read_text(encoding='utf-8')).get('nonce')
        except (OSError, json.JSONDecodeError, AttributeError):
            value = None
        if value:
            nonces.add(value)
    return nonces


def post_attempt_guard(attempt: Path) -> dict[str, Any]:
    """尝试结束后：本尝试任何启动 nonce 仍挂在存活进程上（环境变量核验，不依赖墙钟 create_time）
    即回收（reclaim_stale）并复查；复查仍存活或回收未核实 → confirmed=False（调用方失败关闭、停止调度）。"""
    nonces = attempt_nonces(attempt)
    live = nonces & _live_owner_nonces()
    report: dict[str, Any] = {'protocol': 'launch_nonce_scan_v1', 'nonces': len(nonces), 'live_after_attempt': sorted(live),
                              'confirmed': True}
    if live:
        reclaim = reclaim_stale([attempt])
        still = nonces & _live_owner_nonces()
        report.update(reclaim=reclaim, still_live=sorted(still), confirmed=bool(reclaim['confirmed']) and not still)
    return report


# ------------------------------------------------------------------ 块执行
def chunk_context(wf, context_path: Path, context_ref: dict[str, str], chunk: dict[str, Any], directory: Path) -> Path:
    """块级术语上下文：整份文档术语上下文原样 + 本块页范围 + 参考文献区带入状态（来自计划，
    整份源文上计算）。块 FREEZE 以 document_term_context_ref 绑定此文件，_execute-digital 与渲染逐 sha 核对。"""
    context = wf.read_json(context_path)
    context.update(document_context_ref=context_ref,
                   chunk={k: chunk[k] for k in ('id', 'start', 'end')},
                   reference_region_open_at_start=chunk.get('reference_region_open_at_start') is True)
    path = directory / 'CHUNK_TERM_CONTEXT.json'
    wf.write_new(path, context)
    return path


def chunk_freeze(wf, parent: dict[str, Any], parent_ref: dict[str, str], plan_ref: dict[str, str],
                 chunk: dict[str, Any], context_ref: dict[str, str], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    scope = directory / 'SCOPE_EVIDENCE.json'
    wf.write_new(scope, {'kind': 'chunk_of_frozen_document', 'parent_freeze_ref': parent_ref,
                         'parent_scope_evidence': parent.get('scope_evidence'), 'plan_ref': plan_ref,
                         'chunk': {k: chunk[k] for k in ('id', 'start', 'end', 'pages', 'route')},
                         'note': 'complete page range of the parent document; the parent scope evidence covers the whole document'})
    freeze = {k: v for k, v in parent.items() if k != 'chunking_contract'}
    freeze.update(input=chunk['source_ref'], pages=list(range(1, chunk['pages'] + 1)), complete_semantic_scope=True,
                  scope_evidence=wf.ref(scope), route=chunk['route'],
                  routing_contract=wf.DIGITAL_ROUTING if chunk['route'] == 'digital_pdf' else wf.OCR_ROUTING,
                  document_term_context_ref=context_ref,
                  chunk_of={'parent_freeze_ref': parent_ref, 'plan_ref': plan_ref, 'chunk_id': chunk['id'],
                            'source_pages': [chunk['start'], chunk['end']]})
    path = directory / 'FREEZE.json'
    wf.write_new(path, freeze)
    return path


def run_chunk_candidate(wf, args: argparse.Namespace, freeze_path: Path, chunk: dict[str, Any],
                        attempt: Path, context_path: Path) -> dict[str, Any]:
    """块 = 一次普通 candidate（同一进程内调用 dispatch；其重任务仍是独立的有界子进程树）。"""
    ns = argparse.Namespace(action='candidate', input=Path(chunk['source_ref']['path']), output=attempt / 'out',
                            receipts=attempt / 'receipts', lock_path=args.lock_path, freeze=freeze_path,
                            route=chunk['route'], model=args.model, base_url=args.base_url, smoke=False,
                            cjk_font=args.cjk_font, target_language=args.target_language,
                            source_cache_context=None, source_cache_context_sha256=None,
                            task_memory_mib=args.task_memory_mib, job_timeout_seconds=args.job_timeout_seconds,
                            memory_metric=args.memory_metric, document_term_context=context_path)
    try:
        return wf.dispatch(ns)
    except (wf.PreflightError, wf.ResourceLimitError, ValueError, OSError, RuntimeError) as exc:
        return wf.structured_failure(ns, exc)
    except Exception as exc:  # noqa: BLE001 — 结构化记录，块失败关闭
        return wf.unexpected_failure(ns, exc)


# 测试可替换（真实进程的负例测试用它注入一块失败）。
CHUNK_RUNNER = run_chunk_candidate


def _stop_reason(result: dict[str, Any]) -> str | None:
    for source in (result, (result.get('ocr') or {}).get('job') or {}):
        for key in ('stop_reason', 'error_code'):
            if source.get(key):
                return source[key]
    return None


def backend_timed_out(attempt: Path | None) -> bool:
    """后端在本任务内的内部超时：块输出 render_manifest.json 的 errors 含 error_type=timeout。"""
    if attempt is None:
        return False
    path = attempt / 'out' / 'render_manifest.json'
    try:
        errors = json.loads(path.read_text(encoding='utf-8')).get('errors') or []
    except (OSError, json.JSONDecodeError, AttributeError):
        return False
    return any(isinstance(e, dict) and e.get('error_type') == 'timeout' for e in errors)


def effective_stop_reason(result: dict[str, Any], attempt: Path | None = None) -> str | None:
    reason = _stop_reason(result)
    if result.get('status') not in ('succeeded', 'candidate') and backend_timed_out(attempt):
        return 'backend_timeout'
    return reason


# 既有有界执行的启动身份核验（墙钟 create_time）在墙钟跳变时抛出的错误：环境原因，不是输入的确定性质。
# 尝试后核查确认进程已回收后按瞬时失败重试一次（仍受 retry_transient_failures 限制）；其它 blocked 不变。
LAUNCH_IDENTITY_RACE = ('ValueError: bounded launch PID was reused', 'ValueError: bounded launch identity mismatch')


def launch_identity_race(result: dict[str, Any]) -> bool:
    findings = result.get('findings') or []
    return (result.get('error_code') == 'input_or_contract_invalid' and len(findings) == 1
            and isinstance(findings[0], dict) and findings[0].get('message') in LAUNCH_IDENTITY_RACE)


def classify(result: dict[str, Any], contract: dict[str, Any], attempt: Path | None = None) -> str:
    if result.get('status') in ('succeeded', 'candidate'):
        return 'completed'   # candidate 的有界任务成功（综合质量另计，fail 也是确定结果，照常合并后整份 fail）
    if result.get('status') == 'cleanup_unconfirmed' or result.get('error_code') == 'owned_tree_cleanup_unconfirmed':
        return 'cleanup_unconfirmed'   # 进程树无法核实已回收：不重试、不二分，失败关闭
    reason = _stop_reason(result)
    if reason in contract['split_on_resource_stop']:
        return 'resource_stop'
    if 'backend_timeout' in contract['split_on_resource_stop'] and backend_timed_out(attempt):
        return 'resource_stop'
    if result.get('status') == 'blocked' and launch_identity_race(result):
        return 'transient'
    if result.get('status') == 'blocked':
        return 'blocked'
    return 'transient'


def chunk_outputs(wf, attempt: Path) -> dict[str, Any] | None:
    out = attempt / 'out'
    manifest_path = out / 'render_manifest.json'
    quality_path = out / 'comprehensive_quality.json'
    receipt = attempt / 'receipts' / 'WORKFLOW_CANDIDATE.json'
    if not (manifest_path.is_file() and quality_path.is_file() and receipt.is_file()):
        return None
    outputs = (wf.read_json(manifest_path).get('outputs') or {})
    refs = {}
    for role in OUTPUT_ROLES:
        value = outputs.get(role)
        if value and Path(value).is_file():
            refs[role] = wf.ref(value)
    if 'translated_pdf' not in refs:
        return None
    result = wf.read_json(receipt)
    ocr = result.get('ocr') or {}
    backend_input = ocr.get('reconstructed_source_ref')
    return {'outputs': refs, 'quality_ref': wf.ref(quality_path), 'render_manifest_ref': wf.ref(manifest_path),
            'receipt_ref': wf.ref(receipt), 'backend_input': backend_input,
            'quality_status': result.get('quality_status')}


def prune_temporaries(wf, attempt: Path, patterns: list[str]) -> dict[str, Any]:
    out = attempt / 'out'
    removed = []
    for pattern in patterns:
        for path in sorted(out.glob(pattern)):
            if path.is_file() and not path.is_symlink():
                removed.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': wf.sha(path)})
                path.unlink()
    record = {'patterns': patterns, 'removed': removed, 'bytes': sum(r['bytes'] for r in removed)}
    wf.write_new(attempt / 'CHUNK_PRUNED.json', record)
    return record


def verify_completed(entry: dict[str, Any]) -> list[str]:
    from chunked_translation import sha256_file
    problems = []
    record = entry.get('completed') or {}
    refs = [('chunk_pdf', entry['source_ref']), ('freeze', record.get('freeze_ref')), ('quality', record.get('quality_ref')),
            ('render_manifest', record.get('render_manifest_ref')), ('receipt', record.get('receipt_ref'))]
    refs += [(role, value) for role, value in (record.get('outputs') or {}).items()]
    if record.get('backend_input'):
        refs.append(('backend_input', record['backend_input']))
    if 'context_ref' in record:
        refs.append(('chunk_context', record['context_ref']))
    for role, value in refs:
        if not value or not Path(value['path']).is_file() or sha256_file(value['path']) != value['sha256']:
            problems.append(role)
    return problems


def _measure(result: dict[str, Any]) -> dict[str, Any]:
    ocr_job = (result.get('ocr') or {}).get('job') or {}
    keys = ('status', 'stop_reason', 'error_code', 'elapsed_seconds', 'peak_task_memory_bytes', 'rss_limit_bytes',
            'memory_metric', 'quality_status')
    row = {k: result.get(k) for k in keys}
    row['cleanup_status'] = (result.get('cleanup') or {}).get('status')
    if ocr_job:
        row['ocr_job'] = {k: ocr_job.get(k) for k in ('status', 'stop_reason', 'elapsed_seconds', 'peak_task_memory_bytes',
                                                      'cleanup_status')}
    return row


# ------------------------------------------------------------------ 编排
def run(args: argparse.Namespace, wf) -> dict[str, Any]:
    from chunked_translation import CHUNKING_CONTRACT, split_range
    wf.check_target_language_route(args)
    output, receipts = args.output, args.receipts
    state_path = receipts / STATE_NAME
    if args.resume:
        if not state_path.is_file():
            raise ValueError('resume requires an existing chunked run state in --receipts')
    elif output.exists() or receipts.exists():
        raise ValueError('chunked-candidate requires new --output and --receipts directories (or --resume)')
    receipts.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(receipts / 'CHUNKED_RUN.lock'):
        state = wf.read_json(state_path) if args.resume else {'schema_version': 1, 'invocations': []}
        invocation = len(state['invocations']) + 1
        inv_dir = receipts / f'invocation-{invocation}'
        inv_dir.mkdir()
        inv: dict[str, Any] = {'number': invocation, 'started_at': wf.datetime.now(wf.timezone.utc).isoformat(),
                               'resume': bool(args.resume)}
        state['invocations'].append(inv)
        if args.resume:
            stale = reclaim_stale([receipts, output])
            wf.write_new(inv_dir / 'STALE_RECLAIM.json', stale)
            inv['stale_reclaim'] = {k: stale[k] for k in ('confirmed', 'receipts_scanned', 'already_gone')} | {
                'reclaimed': len(stale['reclaimed'])}
            if not stale['confirmed']:
                save_state(state_path, state)
                return dict(wf.blocked_result([wf.finding('owned_tree_cleanup_unconfirmed',
                            '上次运行遗留的本任务进程树无法核实已回收；不续跑。', receipt=str(inv_dir / 'STALE_RECLAIM.json'))]),
                            stage='chunked_resume_reclaim')
            for entry in state.get('chunk_table', {}).values():
                for attempt in entry.get('attempts', []):
                    if attempt.get('status') == 'started':
                        attempt.update(status='abandoned', abandoned_by_invocation=invocation)
        report = wf.bounded_input_preflight(args.input, inv_dir, require_digital=args.route == 'digital_pdf',
                                            target_language=args.target_language,
                                            max_pages=CHUNKING_CONTRACT['max_document_pages'])
        wf.write_new(inv_dir / 'WORKFLOW_INPUT_PREFLIGHT.json', report)
        if report['status'] == 'blocked':
            first = next(f for f in report['findings'] if f['severity'] == 'error')
            exc = wf.PreflightError(first['code'], first['message'], **first['details'])
            exc.result = dict(report, stage='input_preflight', preflight_ref=wf.ref(inv_dir / 'WORKFLOW_INPUT_PREFLIGHT.json'))
            save_state(state_path, state)
            raise exc
        freeze = wf.read_json(args.freeze)
        pages = wf.validate_freeze(freeze, args.input, args.route, args.model, chunked=True)
        if report.get('page_count') != len(freeze['pages']):
            raise ValueError('actual PDF page count differs from the frozen chunked scope')
        args.resource_limits = wf.frozen_limits(args, freeze)
        args.frozen_environment = freeze.get('backend_environment', {})
        health = wf.doctor(args.base_url, args.model, include_ocr=args.route != 'digital_pdf')
        if health['blockers']:
            raise ValueError('required environment not ready')
        # 有界任务（chunk-plan / 块 / chunk-merge）以运行目录为 cwd：首次使用的新工作区（如 CI 的
        # PAPER_TRANSLATION_WORKSPACE）此时可能尚不存在，先建好；路径被普通文件占用则照常报错失败关闭。
        wf.ROOT.mkdir(parents=True, exist_ok=True)
        identity = {'freeze_ref': wf.ref(args.freeze), 'input_ref': wf.ref(args.input), 'route': args.route,
                    'target_language': args.target_language, 'model': args.model, 'base_url': args.base_url,
                    'contract': CHUNKING_CONTRACT}
        if args.resume and state.get('identity') != identity:
            raise ValueError('resume identity differs (freeze, input, route, language, model, endpoint or contract changed)')
        state['identity'] = identity
        job_args = copy.copy(args)
        job_args.receipts = inv_dir
        # ---- 计划
        if state.get('plan_ref'):
            from chunked_translation import sha256_file
            plan_ref = state['plan_ref']
            if sha256_file(plan_ref['path']) != plan_ref['sha256']:
                raise ValueError('chunk plan changed after it was recorded')
            plan = wf.read_json(plan_ref['path'])
        else:
            plan_dir = output / 'plan'
            if plan_dir.exists():
                # 上次在计划阶段中断：旧计划未登记，保留原样作证据，换新目录。
                plan_dir = output / f'plan-{invocation}'
            job = wf.run_job(job_args, [wf.sys.executable, str(wf.SCRIPT_DIR / 'chunked_translation.py'), 'plan',
                                        '--input', str(args.input.resolve()), '--preflight',
                                        str((inv_dir / 'input-preflight' / 'input_preflight_report.json').resolve()),
                                        '--route', args.route, '--output', str(plan_dir.resolve())], 'chunk-plan')
            inv['plan_job'] = _measure(job)
            if job.get('status') != 'succeeded' or not (plan_dir / 'CHUNK_PLAN.json').is_file():
                save_state(state_path, state)
                return dict(job, stage='chunk_plan', status='blocked' if job.get('status') == 'blocked' else job.get('status', 'failed'))
            plan_ref = wf.ref(plan_dir / 'CHUNK_PLAN.json')
            plan = wf.read_json(plan_dir / 'CHUNK_PLAN.json')
            if plan['input_ref'] != freeze['input'] or plan['contract'] != CHUNKING_CONTRACT or plan['page_count'] != len(pages):
                raise ValueError('chunk plan does not match the frozen input and contract')
            state.update(plan_ref=plan_ref, order=[c['id'] for c in plan['chunks']],
                         chunk_table={c['id']: dict(c, status='pending', attempts=[]) for c in plan['chunks']})
            save_state(state_path, state)
        context_ref = plan['document_term_context_ref']
        context_path = Path(context_ref['path'])
        if wf.sha(context_path) != context_ref['sha256']:
            raise ValueError('document term context changed after planning')
        parent_ref = wf.ref(args.freeze)
        table, order = state['chunk_table'], state['order']
        reused, executed = [], []
        index = 0
        while index < len(order):
            cid = order[index]
            entry = table[cid]
            if wf.sha(entry['source_ref']['path']) != entry['source_ref']['sha256']:
                raise ValueError(f'chunk source {cid} changed after planning')
            if entry['status'] == 'completed':
                problems = verify_completed(entry)
                if not problems:
                    if entry['completed']['invocation'] != invocation:
                        reused.append(cid)
                    index += 1
                    continue
                entry.update(status='invalidated', invalidated={'invocation': invocation, 'changed': problems})
            elif entry['status'] in ('failed', 'blocked') and entry.get('final_invocation') == invocation:
                index += 1
                continue
            transient_retries = sum(1 for a in entry['attempts'] if a.get('classification') == 'transient'
                                    and a.get('invocation') == invocation)
            number = len(entry['attempts']) + 1
            attempt_dir = output / 'chunks' / cid / f'attempt-{number}'
            (attempt_dir / 'freeze').mkdir(parents=True, exist_ok=False)
            entry_context = chunk_context(wf, context_path, context_ref, entry, attempt_dir / 'freeze')
            freeze_path = chunk_freeze(wf, freeze, parent_ref, plan_ref, entry, wf.ref(entry_context), attempt_dir / 'freeze')
            record = {'number': number, 'invocation': invocation, 'status': 'started', 'dir': str(attempt_dir),
                      'freeze_ref': wf.ref(freeze_path), 'started_at': wf.datetime.now(wf.timezone.utc).isoformat()}
            entry['attempts'].append(record)
            entry['status'] = 'running'
            save_state(state_path, state)
            started = time.monotonic()
            result = CHUNK_RUNNER(wf, args, freeze_path, entry, attempt_dir, entry_context)
            kind = classify(result, CHUNKING_CONTRACT, attempt_dir)
            record.update(status='finished', classification=kind, wall_seconds=round(time.monotonic() - started, 3),
                          measurements=_measure(result), error_code=result.get('error_code'))
            if effective_stop_reason(result, attempt_dir) == 'backend_timeout':
                record['stop_reason'] = 'backend_timeout'
            wf.write_new(attempt_dir / 'CHUNK_RESULT.json', result)
            guard = post_attempt_guard(attempt_dir)
            record['post_attempt_guard'] = {k: guard[k] for k in ('live_after_attempt', 'confirmed')}
            if guard['live_after_attempt']:
                wf.write_new(attempt_dir / 'POST_ATTEMPT_GUARD.json', guard)
            if not guard['confirmed']:
                kind = record['classification'] = 'cleanup_unconfirmed'
            record['pruned_bytes'] = prune_temporaries(wf, attempt_dir, CHUNKING_CONTRACT['prune_backend_temporaries'])['bytes']
            executed.append(cid)
            if kind == 'completed':
                produced = chunk_outputs(wf, attempt_dir)
                if produced is None:
                    kind = record['classification'] = 'missing_outputs'
                else:
                    entry.update(status='completed', completed=dict(produced, freeze_ref=record['freeze_ref'],
                                                                    context_ref=wf.ref(entry_context),
                                                                    attempt=number, invocation=invocation))
                    save_state(state_path, state)
                    index += 1
                    continue
            if kind == 'resource_stop':
                if entry['pages'] > 1:
                    children = split_range(entry)
                    entry['status'] = 'split'
                    entry['split_into'] = [c['id'] for c in children]
                    from chunked_translation import write_chunk_pdf
                    import fitz
                    with fitz.open(args.input) as source:
                        for child in children:
                            child['source_ref'] = write_chunk_pdf(source, child,
                                                                  output / 'chunks' / f"{child['id']}.pdf")
                            child['page_kinds'] = entry['page_kinds'][child['start'] - entry['start']:
                                                                      child['end'] - entry['start'] + 1]
                            opened = plan.get('reference_region_open_at_page_start') or []
                            child['reference_region_open_at_start'] = (opened[child['start'] - 1]
                                                                       if len(opened) >= child['start'] else False)
                            table[child['id']] = dict(child, status='pending', attempts=[], split_from=cid)
                    order[index:index + 1] = [c['id'] for c in children]
                    save_state(state_path, state)
                    continue
                entry.update(status='failed', final_invocation=invocation, failure={
                    'error_code': 'chunk_page_exceeds_task_budget', 'stop_reason': effective_stop_reason(result, attempt_dir),
                    'measurements': record['measurements'],
                    'message': '单页仍超出冻结的单任务资源预算；不放宽限制，整份失败关闭。'})
            elif kind == 'transient' and transient_retries < CHUNKING_CONTRACT['retry_transient_failures']:
                save_state(state_path, state)
                continue
            else:
                entry.update(status='blocked' if kind == 'blocked' else 'failed', final_invocation=invocation,
                             failure={'error_code': ('chunk_cleanup_unconfirmed' if kind == 'cleanup_unconfirmed'
                                                     else result.get('error_code') or kind),
                                      'classification': kind, 'findings': result.get('findings', [])[:5]})
                if kind == 'cleanup_unconfirmed':
                    # 本块进程树无法核实已回收：不再启动任何块（重任务并发 1），整份失败关闭。
                    save_state(state_path, state)
                    break
            save_state(state_path, state)
            index += 1
        chunks = [table[cid] for cid in order]
        summary = [{'id': c['id'], 'pages': [c['start'], c['end']], 'route': c['route'], 'status': c['status'],
                    'attempts': len(c['attempts']),
                    'last_attempt': ({k: c['attempts'][-1].get(k) for k in ('number', 'invocation', 'classification',
                                                                            'wall_seconds', 'measurements')}
                                     if c['attempts'] else None),
                    'quality_status': (c.get('completed') or {}).get('quality_status')} for c in chunks]
        base = {'action': 'chunked-candidate', 'freeze_ref': parent_ref, 'input_ref': wf.ref(args.input),
                'route': args.route, 'declared_pages': pages, 'plan_ref': plan_ref, 'chunk_count': len(chunks),
                'chunks': summary, 'reused_chunks': reused, 'executed_chunks': executed, 'invocation': invocation,
                'human_accepted': False, 'strict_delivery': False, 'heavy_task_concurrency': 1,
                'resource_contract_frozen': freeze.get('resource_contract'), 'chunking_contract': CHUNKING_CONTRACT,
                'input_preflight': {k: report.get(k) for k in ('status', 'warnings', 'source_language', 'page_count')},
                'stage': 'chunked_candidate', 'schema_version': 1}
        failed = [c for c in chunks if c['status'] != 'completed']
        if failed:
            result = dict(wf.blocked_result([wf.finding('chunk_failed',
                          f"{len(failed)} 块未产出可合并的结果；整份失败关闭，不合并、不交付部分结果。",
                          chunks=[{'id': c['id'], 'pages': [c['start'], c['end']], 'status': c['status'],
                                   **(c.get('failure') or {})} for c in failed])]), **base)
            result.update(error_code='chunk_failed', merged=False)
        else:
            rows = [{'chunk': {k: c[k] for k in ('id', 'start', 'end', 'pages', 'route', 'source_ref')},
                     'outputs': c['completed']['outputs'], 'quality_ref': c['completed']['quality_ref'],
                     'quality_status': c['completed']['quality_status'],
                     'backend_input': c['completed'].get('backend_input')} for c in chunks]
            results_path = inv_dir / 'MERGE_INPUT.json'
            wf.write_new(results_path, rows)
            merged_dir = output / f'merged-{invocation}'
            job = wf.run_job(job_args, [wf.sys.executable, str(wf.SCRIPT_DIR / 'chunked_translation.py'), 'merge',
                                        '--plan', plan_ref['path'], '--plan-sha256', plan_ref['sha256'],
                                        '--results', str(results_path.resolve()), '--results-sha256', wf.sha(results_path),
                                        '--input', str(args.input.resolve()), '--target-language', args.target_language,
                                        '--output', str(merged_dir.resolve())], 'chunk-merge')
            inv['merge_job'] = _measure(job)
            manifest_path = merged_dir / 'MERGE_MANIFEST.json'
            if job.get('status') != 'succeeded' or not manifest_path.is_file():
                result = dict(wf.blocked_result([wf.finding('chunk_merge_failed', '有界合并任务未完成；不交付。',
                              stop_reason=job.get('stop_reason'), status=job.get('status'))]), **base)
                result.update(error_code='chunk_merge_failed', merged=False, merge_job=_measure(job))
            else:
                manifest = wf.read_json(manifest_path)
                result = dict(base, status='candidate', merged=True, merge_job=_measure(job),
                              merged_output_dir=str(merged_dir), merge_manifest_ref=wf.ref(manifest_path),
                              outputs=manifest['outputs'], merge_issues=manifest['issues'], links=manifest['links'],
                              toc_entries=manifest['toc_entries'], page_labels=manifest['page_labels'])
                result.update(wf.quality_verdict(merged_dir))
                worst = max((c['completed']['quality_status'] or 'fail' for c in chunks),
                            key=lambda s: {'pass': 0, 'unverified': 1}.get(s, 2))
                order_rank = {'pass': 0, 'unverified': 1, 'fail': 2}
                if order_rank.get(result.get('quality_status'), 2) < order_rank.get(worst, 2):
                    raise AssertionError('merged quality better than the worst chunk')
        inv['finished_at'] = wf.datetime.now(wf.timezone.utc).isoformat()
        inv['status'] = result.get('status')
        save_state(state_path, state)
        receipt = receipts / (RECEIPT_NAME if invocation == 1 else f'WORKFLOW_CHUNKED_CANDIDATE.invocation-{invocation}.json')
        result['state_ref'] = wf.ref(state_path)
        wf.write_new(receipt, result)
        result['receipt'] = str(receipt)
        return result
