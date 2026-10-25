# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-23：2.0.0-rc.9 新增（长文档分块翻译）；变更见Skill根目录MODIFICATIONS.md。
"""``paper_translation_workflow.py chunked-candidate`` 的编排：每块一个有界 candidate 任务，按页序合并。

* 整份文档：有界输入预检（最多 ``CHUNKING_CONTRACT['max_document_pages']`` 页）→ 冻结校验（parent FREEZE
  声明完整页数 + 冻结分块合同）→ doctor → 有界 ``chunk-plan`` 任务。
* 每块：派生块级 FREEZE（块 PDF 身份、页数 1..k、作用域证据指向 parent FREEZE 与计划、块路线及其
  既有路由合同、整份术语上下文绑定），以 ``candidate`` 动作原样执行——单份 candidate 的全部门
  （预检、路由、OCR 守门、质量门、拥有式计量与回收）逐块生效，单块单任务预算即 FREEZE 资源合同。
  电子块的翻译后端整份共用一个已经加载版面模型的进程；某块碰到时间上限后该进程退出，下一块重新加载一次。
  纯扫描不启动这个进程。不超过 5 页的单份 ``candidate`` 仍是每份单独启动。
* 资源停止（超时/超内存）的块二分到单页；单页仍超限即失败关闭并记录实测。瞬时失败重试一次；
  预检拦截与质量 fail 不重试（结果确定）。PDF 后端未产出候选时，根因取本尝试自己写出、身份核对一致的
  结构化回执（``failure_root_cause``）：确定性根因（排版上限、可读下限溢出、子任务自身的合同/输入拒绝）
  不重试，``--resume`` 也不重跑（同一输入与配置）；拿不到可核实的根因记 ``root_cause_unavailable``，
  按既有瞬时失败处理（重试一次）。根因上浮到块结果、``CHUNKED_RUN_STATE`` 与整份回执。
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

from backend_session import open_document_backend
from translation_cost_ledger import sum_ledgers

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
GUARD_PROTOCOL = 'launch_receipt_recovery_scan_v2'


def owner_nonce_scan() -> dict[str, Any]:
    """全机一次：环境里带 ``PAPER_TRANSLATION_BOUNDED_OWNERS`` 的进程的 nonce 集合（只用于记录，不用于判定已清理）。
    读不到环境的同用户非僵尸进程计入 ``unreadable``；枚举本身失败即 ``complete=False``。"""
    import psutil
    from bounded_execution import PROCESS_QUERY_ERRORS, _enumerate_all_pids, _query_failure_counts
    report: dict[str, Any] = {'complete': False, 'nonces': set(), 'unreadable': 0, 'method': None}
    try:
        pids, report['method'], _ = _enumerate_all_pids()
    except Exception as exc:  # noqa: BLE001 - 枚举失败只说明本次扫描不完整
        report['error'] = f'{type(exc).__name__}: {exc}'[:200]
        return report
    for pid in pids:
        proc = None
        try:
            proc = psutil.Process(pid)
            value = proc.environ().get('PAPER_TRANSLATION_BOUNDED_OWNERS', '')
        except psutil.NoSuchProcess:
            continue
        except PROCESS_QUERY_ERRORS:
            if _query_failure_counts(proc):
                report['unreadable'] += 1
            continue
        report['nonces'].update(filter(None, value.split(',')))
    report['complete'] = True
    return report


def _reason_codes(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get('reason') or 'unverified') for row in rows})


def _detail_codes(rows: list[dict[str, Any]]) -> list[str]:
    """细分原因码（如 older_than_root_nonce_unreadable：按墙钟早于根进程、读不到 nonce、无单调证据可排除）。"""
    return sorted({str(row['code']) for row in rows if row.get('code')})


def _verify_receipt(identity: dict[str, Any]) -> dict[str, Any]:
    """一张 launch 回执的整树核实。先做一次只读预检（与回收同一套恢复扫描：nonce / 本次进程组 / 已核验父链，
    查询失败的同用户进程记为归属未知）；只有预检“完整、无所属存活、无归属未知、根已退出或号码已复用、
    原进程组已空”才记为 already_gone。否则交给 ``reclaim_owned_tree(discovery_failed=True)``：
    已知可信根/成员按 PID + create_time 回收（时钟跳变带有效 nonce 的按 nonce 刷新身份），归属未知的进程
    不发信号、记入 unverified（confirmed=False）。"""
    from bounded_execution import _group_empty, _identity_state, _recovery_scan, reclaim_owned_tree
    import psutil
    from launch_clock import start_evidence
    pid, born = int(identity['pid']), float(identity['created_at'])
    nonce = identity.get('nonce')
    state = _identity_state(pid, born)[0]
    recorded_ev = identity.get('start_evidence') if isinstance(identity.get('start_evidence'), dict) else None

    def clock_shifted_root() -> bool:
        # create_time 不符（看似 PID 复用），但同一次开机内的单调启动读数与回执一致：仍是原根进程，只是墙钟跳变
        # （PR #21 review-2）。不能按“号码已复用”把它当已退出，也不能据此跳过原进程组的探测。
        if not recorded_ev or _identity_state(pid, born)[0] != 'pid_reused' or start_evidence(pid) != recorded_ev:
            return False
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except Exception:  # noqa: BLE001 - 状态读不到：按仍存活处理（失败关闭）
            return True
    shifted = state == 'pid_reused' and clock_shifted_root()
    if shifted:
        state = 'alive_clock_shifted'
    pgid = identity.get('process_group')
    own_group = bool(pgid) and pgid == pid and os.name == 'posix'
    group_trusted = own_group and state in ('alive', 'zombie', 'dead', 'alive_clock_shifted')
    group_empty = _group_empty(pgid) if own_group and state != 'pid_reused' else True
    pre = _recovery_scan(identity, {pid: born}, nonce, group_trusted, 'guard_precheck')
    precheck = {'root_state': state, 'group_empty': group_empty, 'complete': pre['complete'],
                'owned_found': len(pre['owned_found']), 'ownership_unknown': len(pre['ownership_unknown'])}
    if (state in ('dead', 'pid_reused') and group_empty is True and pre['complete']
            and not pre['owned_found'] and not pre['ownership_unknown']):
        return {'already_gone': True, 'confirmed': True, 'precheck': precheck, 'unverified': []}
    outcome = reclaim_owned_tree(identity, {}, time.monotonic() + 15, discovery_failed=True, nonce=nonce)
    unverified = list(outcome.get('unverified') or [])
    if shifted and clock_shifted_root():
        # 无 nonce 刷新身份时回收端按“号码复用”不发信号；原根进程仍在 → 未核实（不发信号、停止后续调度）。
        unverified.append({'pid': pid, 'created_at': born, 'reason': 'root_identity_clock_shifted',
                           'detail': 'create_time moved with the wall clock; boot-relative start matches the receipt'})
    if pre['ownership_unknown'] and not unverified:
        # 预检发现的归属未知不能因回收端的再次扫描“恰好没看到”而消失（例如查询结果抖动）：保留为未核实。
        unverified += [dict(row, reason='ownership_unknown') for row in pre['ownership_unknown']
                       if row.get('created_at') is None
                       or _identity_state(int(row['pid']), float(row['created_at']))[0] in ('alive', 'unknown')]
    return {'already_gone': False, 'confirmed': bool(outcome.get('confirmed')) and not unverified, 'precheck': precheck,
            'status': outcome.get('status') if not unverified or outcome.get('status') != 'confirmed' else 'unconfirmed',
            'unverified': unverified, 'identity_refreshed': outcome.get('identity_refreshed', [])}


def reclaim_stale(roots: list[Path]) -> dict[str, Any]:
    """扫描运行目录下所有 launch 回执，逐张整树核实/回收（``_verify_receipt``）。回执读不了、核实抛错、
    或任何一张未核实 → confirmed=False，且 ``unverified`` 非空（带稳定原因码 ``reason_codes``）。
    不再以全机 nonce 扫描（读不到环境的进程会被漏掉）判定“已无残留”（PR #21 review-1）。"""
    report: dict[str, Any] = {'protocol': GUARD_PROTOCOL, 'confirmed': True, 'receipts_scanned': 0,
                              'reclaimed': [], 'already_gone': 0, 'unverified': []}
    for root in roots:
        if not root.exists():
            continue
        for receipt in sorted(root.rglob('*.launch.json')):
            report['receipts_scanned'] += 1
            try:
                identity = json.loads(receipt.read_text(encoding='utf-8'))
                verdict = _verify_receipt(identity)
            except Exception as exc:  # noqa: BLE001 - 核实不了即未核实（失败关闭），不当作已清理
                row = {'receipt': str(receipt), 'reason': 'receipt_verification_error',
                       'error': f'{type(exc).__name__}: {exc}'[:200]}
                report['confirmed'] = False
                report['unverified'].append(row)
                report['reclaimed'].append(dict(row, confirmed=False))
                continue
            if verdict['already_gone']:
                report['already_gone'] += 1
                continue
            report['reclaimed'].append({'receipt': str(receipt), 'pid': identity.get('pid'),
                                        'root_state': verdict['precheck']['root_state'],
                                        'group_busy': verdict['precheck']['group_empty'] is False,
                                        'precheck': verdict['precheck'],
                                        'confirmed': verdict['confirmed'], 'status': verdict.get('status'),
                                        'unverified': verdict['unverified'],
                                        'identity_refreshed': verdict.get('identity_refreshed', [])})
            if not verdict['confirmed']:
                report['confirmed'] = False
                report['unverified'] += [dict(row, receipt=str(receipt)) for row in verdict['unverified']] or [
                    {'receipt': str(receipt), 'reason': 'reclaim_unconfirmed'}]
    report['reason_codes'] = _reason_codes(report['unverified'])
    report['detail_codes'] = _detail_codes(report['unverified'])
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
    """尝试结束后：本尝试每张 launch 回执都做整树核实（``reclaim_stale([attempt])``）；存活的本任务进程
    回收后核实，归属无法判定、枚举不完整或回收未核实 → confirmed=False、unverified 非空（调用方失败关闭、
    停止调度后续块；重任务并发 1）。全机 nonce 扫描只作记录（``live_after_attempt``），不作“已清理”的依据。"""
    nonces = attempt_nonces(attempt)
    before = owner_nonce_scan()
    reclaim = reclaim_stale([attempt])
    after = owner_nonce_scan()
    still = nonces & after['nonces']
    report: dict[str, Any] = {'protocol': GUARD_PROTOCOL, 'nonces': len(nonces),
                              'live_after_attempt': sorted(nonces & before['nonces']),
                              'nonce_scan': {k: before[k] for k in ('complete', 'unreadable', 'method')},
                              'reclaim': reclaim, 'still_live': sorted(still)}
    unverified = list(reclaim.get('unverified') or [])
    if not reclaim.get('confirmed') and not unverified:
        unverified.append({'reason': 'reclaim_unconfirmed'})
    if still:
        unverified.append({'reason': 'owned_nonce_still_live', 'nonces': sorted(still)})
    report.update(unverified=unverified, reason_codes=_reason_codes(unverified), detail_codes=_detail_codes(unverified),
                  confirmed=bool(reclaim['confirmed']) and not unverified)
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
                            route=chunk['route'], model=args.model, base_url=args.base_url,
                            local_max_concurrency=getattr(args, 'local_max_concurrency', None), smoke=False,
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


# 子任务把这些异常映射成的错误码是环境性质（锁被占、I/O），不是输入/配置的确定性质：不据此判确定性失败。
CHILD_ENVIRONMENT_CODES = ('project_lock_busy', 'io_error')


def child_envelope(result: dict[str, Any]) -> dict[str, Any] | None:
    """``_execute-digital`` 子任务自己以结构化 JSON 报告的拒绝（stdout 全文：未截断、sha 与摘录一致、退出码 2、
    动作与错误码自洽）。读不出、截断或不一致即 None——不从日志/摘录里找关键字。"""
    import hashlib
    command = result.get('command') or {}
    summary = command.get('stdout_summary') or {}
    excerpt = summary.get('excerpt')
    if (command.get('returncode') != 2 or summary.get('truncated') is not False or not isinstance(excerpt, str)
            or hashlib.sha256(excerpt.encode('utf-8')).hexdigest() != summary.get('sha256')):
        return None
    try:
        value = json.loads(excerpt)
    except ValueError:
        return None
    findings = value.get('findings') if isinstance(value, dict) else None
    if (not isinstance(value, dict) or value.get('action') != '_execute-digital' or value.get('status') != 'blocked'
            or not value.get('error_code') or not isinstance(findings, list) or not findings
            or not isinstance(findings[0], dict) or findings[0].get('code') != value['error_code']):
        return None
    return value


def with_document_pages(cause: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """根因细节里的页号是块内页号（1 起）；另记整份文档页号（块起始页 + 块内页 − 1）。"""
    details = cause.get('details')
    if not isinstance(details, dict):
        return cause
    offset = int(entry['start']) - 1
    details = dict(details)
    if isinstance(details.get('pages'), list) and all(isinstance(p, int) for p in details['pages']):
        details['document_pages'] = [p + offset for p in details['pages']]
    if isinstance(details.get('violations'), list):
        details['violations'] = [dict(v, document_page=v['page'] + offset) if isinstance(v, dict) and isinstance(v.get('page'), int)
                                 else v for v in details['violations']]
    return dict(cause, details=details, chunk_page_offset=offset)


def failure_root_cause(result: dict[str, Any], attempt: Path | None = None) -> dict[str, Any] | None:
    """本次尝试失败的根因（只用本尝试的结构化回执）。``retry``：deterministic / resource / unknown。"""
    from failure_root_cause import UNKNOWN, unavailable
    if result.get('status') in ('succeeded', 'candidate'):
        return None
    cause = result.get('root_cause')
    if isinstance(cause, dict) and cause.get('code'):
        return cause   # run_job 已按本尝试 argv / launch nonce / FREEZE / sha 核对过（verified 字段）
    command = result.get('command') or {}
    if result.get('status') == 'blocked' and command and result.get('error_code'):
        # 子任务结构化拒绝行（预检/路由守门，PreflightError）已由 run_job 上浮为 blocked。
        return {'code': result['error_code'], 'retry': 'deterministic', 'stage': 'child_preflight_refusal',
                'verified': True, 'source': 'child_structured_result_marker',
                'details': {'findings': [{k: f.get(k) for k in ('code', 'message')} for f in result.get('findings') or []
                                         if isinstance(f, dict)][:3]}}
    envelope = child_envelope(result) if command else None
    if envelope:
        code, message = envelope['error_code'], str(envelope['findings'][0].get('message') or '')
        retry = UNKNOWN if code in CHILD_ENVIRONMENT_CODES else 'deterministic'
        cause = {'code': code, 'retry': retry, 'stage': 'child_contract_refusal', 'verified': True,
                 'source': 'child_structured_stdout', 'details': {'message': message[:300]}}
        if message.startswith('ValueError: PDF backend failed or changed route'):
            # 旧版子任务的笼统拒绝：本结果里没有本尝试的结构化根因回执，明确记为不可得，不猜具体原因。
            cause['backend_root_cause'] = unavailable('legacy_child_refusal_without_root_cause_receipt')
        return cause
    return None


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
    cause = failure_root_cause(result, attempt)
    if cause and cause.get('verified') is True:
        if cause.get('retry') == 'resource' and 'backend_timeout' in contract['split_on_resource_stop']:
            return 'resource_stop'
        if cause.get('retry') == 'deterministic':
            return 'blocked'   # 同一输入与配置必然重现：不重试（续跑也不重跑，见 run）
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
    completed = {'outputs': refs, 'quality_ref': wf.ref(quality_path), 'render_manifest_ref': wf.ref(manifest_path),
            'receipt_ref': wf.ref(receipt), 'backend_input': backend_input,
            'quality_status': result.get('quality_status'), 'quality_reasons': quality_reasons(result)}
    if isinstance(result.get('cost_ledger'), dict):
        completed['cost_ledger'] = result['cost_ledger']
    return completed


def quality_reasons(result: dict[str, Any]) -> dict[str, Any]:
    """块回执里质量门/可读版的稳定原因码（fail 原因 id、公式上下标层级门、可读版拒绝码），上浮到整份回执。"""
    reasons: dict[str, Any] = {'fail_reason_codes': sorted({str(r.get('id')) for r in result.get('quality_fail_reasons') or []
                                                            if isinstance(r, dict) and r.get('id')})}
    structure = result.get('formula_structure')
    if isinstance(structure, dict) and structure.get('status'):
        reasons['formula_structure'] = {k: structure.get(k) for k in ('status', 'lost', 'flagged_pages')}
    readable = result.get('readable_output')
    if isinstance(readable, dict) and readable.get('status'):
        reasons['readable_output'] = {k: readable.get(k) for k in ('status', 'reason_code')}
    return reasons


# 决定排版上限/可读下限结果的实现文件：任何一个变了，登记的确定性失败不再沿用（续跑照常重跑）。
DETERMINISM_IMPLEMENTATION = ('scripts/chunked_workflow.py', 'scripts/failure_root_cause.py',
                              'scripts/paper_translation_workflow.py', 'scripts/run_pdf_translation.py',
                              'vendor/babeldoc/babeldoc/format/pdf/document_il/midend/typesetting.py',
                              'vendor/babeldoc/babeldoc/format/pdf/document_il/midend/overflow_source_fallback.py')


def failure_identity(wf, entry: dict[str, Any], state: dict[str, Any], attempt_freeze_ref: dict[str, str]) -> dict[str, Any]:
    """确定性失败登记时的输入与配置身份：块 PDF、页范围、路线、整份运行身份（parent FREEZE / 输入 / 路线 / 语言 /
    模型 / 端点 / 分块合同）、计划、该尝试的块 FREEZE、实现文件 sha。续跑时逐项一致才沿用登记的失败（不重跑）。"""
    skill = Path(__file__).resolve().parent.parent
    implementation = {}
    for name in DETERMINISM_IMPLEMENTATION:
        path = skill / name
        implementation[name] = wf.sha(path) if path.is_file() else None
    freeze_now = (wf.ref(attempt_freeze_ref['path']) if Path(attempt_freeze_ref['path']).is_file() else None)
    return {'chunk_source_ref': entry['source_ref'], 'pages': [entry['start'], entry['end']], 'route': entry['route'],
            'run_identity': state.get('identity'), 'plan_ref': state.get('plan_ref'),
            'attempt_freeze_ref': freeze_now, 'implementation': implementation}


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
            inv['stale_reclaim'] = {k: stale[k] for k in ('confirmed', 'receipts_scanned', 'already_gone', 'reason_codes')} | {
                'reclaimed': len(stale['reclaimed']), 'unverified': len(stale['unverified'])}
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
        reused, executed, not_reexecuted = [], [], []
        index = 0
        session = open_document_backend(inv_dir, args.route)
        try:
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
                elif entry['status'] == 'blocked' and (entry.get('failure') or {}).get('deterministic') is True:
                    recorded = entry['failure'].get('identity')
                    current = failure_identity(wf, entry, state, entry['attempts'][-1]['freeze_ref']) if entry['attempts'] else None
                    if recorded and current == recorded:
                        # 同一输入与配置下登记过的确定性失败：不重跑，保留首个根因与全部尝试记录。
                        entry.setdefault('not_reexecuted_by_invocations', []).append(invocation)
                        not_reexecuted.append(cid)
                        index += 1
                        continue
                    entry['failure']['identity_changed_at_invocation'] = invocation
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
                if session is not None and entry.get('route') != 'scanned_ocr':
                    session.ensure()
                result = CHUNK_RUNNER(wf, args, freeze_path, entry, attempt_dir, entry_context)
                kind = classify(result, CHUNKING_CONTRACT, attempt_dir)
                cause = failure_root_cause(result, attempt_dir) if kind != 'completed' else None
                record.update(status='finished', classification=kind, wall_seconds=round(time.monotonic() - started, 3),
                              measurements=_measure(result), error_code=result.get('error_code'))
                if kind != 'completed':
                    from failure_root_cause import unavailable
                    record['root_cause'] = with_document_pages(cause, entry) if cause else unavailable(
                        'no_structured_cause_in_result', status=result.get('status'), error_code=result.get('error_code'),
                        failure_code=(result.get('command') or {}).get('failure_code'))
                if effective_stop_reason(result, attempt_dir) == 'backend_timeout':
                    record['stop_reason'] = 'backend_timeout'
                wf.write_new(attempt_dir / 'CHUNK_RESULT.json', result)
                guard = post_attempt_guard(attempt_dir)
                record['post_attempt_guard'] = {k: guard[k] for k in ('live_after_attempt', 'confirmed', 'reason_codes')}
                if guard['live_after_attempt'] or guard['reclaim'].get('reclaimed') or not guard['confirmed']:
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
                    stop = effective_stop_reason(result, attempt_dir)
                    entry.update(status='failed', final_invocation=invocation, failure={
                        'error_code': 'chunk_page_exceeds_task_budget', 'stop_reason': stop,
                        'measurements': record['measurements'],
                        'message': '单页仍超出冻结的单任务资源预算；不放宽限制，整份失败关闭。',
                        'root_cause': {'code': 'chunk_page_exceeds_task_budget', 'retry': 'resource', 'stage': 'bounded_task',
                                       'verified': True, 'details': {'stop_reason': stop, 'pages': [entry['start'], entry['end']]}},
                        'attempt': number, 'invocation': invocation})
                elif kind == 'transient' and transient_retries < CHUNKING_CONTRACT['retry_transient_failures']:
                    save_state(state_path, state)
                    continue
                else:
                    root = record.get('root_cause') or {}
                    first = next((a['root_cause'] for a in entry['attempts'] if a.get('root_cause')), root)
                    deterministic = kind == 'blocked' and root.get('retry') == 'deterministic' and root.get('verified') is True
                    if kind == 'cleanup_unconfirmed':
                        code = 'chunk_cleanup_unconfirmed'
                    elif root.get('code') and root['code'] != 'root_cause_unavailable':
                        code = root['code']
                    else:
                        code = result.get('error_code') or root.get('code') or kind
                    failure = {'error_code': code,
                               'classification': kind, 'findings': result.get('findings', [])[:5],
                               'root_cause': root, 'first_root_cause': first, 'attempt': number, 'invocation': invocation,
                               'deterministic': deterministic}
                    if deterministic:
                        failure['identity'] = failure_identity(wf, entry, state, record['freeze_ref'])
                    entry.update(status='blocked' if kind == 'blocked' else 'failed', final_invocation=invocation, failure=failure)
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
                                                                                'wall_seconds', 'measurements', 'error_code',
                                                                                'root_cause')}
                                         if c['attempts'] else None),
                        'quality_status': (c.get('completed') or {}).get('quality_status'),
                        **({'quality_reasons': c['completed']['quality_reasons']}
                           if (c.get('completed') or {}).get('quality_reasons') else {}),
                        **({'cost_ledger': c['completed']['cost_ledger']}
                           if isinstance((c.get('completed') or {}).get('cost_ledger'), dict) else {}),
                        **({'error_code': c['failure'].get('error_code'), 'root_cause': c['failure'].get('root_cause')}
                           if c['status'] != 'completed' and c.get('failure') else {})} for c in chunks]
            base = {'action': 'chunked-candidate', 'freeze_ref': parent_ref, 'input_ref': wf.ref(args.input),
                    'route': args.route, 'declared_pages': pages, 'plan_ref': plan_ref, 'chunk_count': len(chunks),
                    'chunks': summary, 'reused_chunks': reused, 'executed_chunks': executed, 'invocation': invocation,
                    'deterministic_failures_not_reexecuted': not_reexecuted,
                    'human_accepted': False, 'strict_delivery': False, 'heavy_task_concurrency': 1,
                    'backend_process': 'shared' if session is not None else 'per_chunk',
                    'resource_contract_frozen': freeze.get('resource_contract'), 'chunking_contract': CHUNKING_CONTRACT,
                    'input_preflight': {k: report.get(k) for k in ('status', 'warnings', 'source_language', 'page_count')},
                    'stage': 'chunked_candidate', 'schema_version': 1}
            failed = [c for c in chunks if c['status'] != 'completed']
            if failed:
                result = dict(wf.blocked_result([wf.finding('chunk_failed',
                              f"{len(failed)} 块未产出可合并的结果；整份失败关闭，不合并、不交付部分结果。",
                              chunks=[{'id': c['id'], 'pages': [c['start'], c['end']], 'status': c['status'],
                                       **(c.get('failure') or {})} for c in failed])]), **base)
                # 整份回执：保留稳定的 chunk_failed，另上浮按页序第一块的根因与全部失败块的根因（含块、页、尝试）。
                from failure_root_cause import unavailable
                causes = [dict((c.get('failure') or {}).get('root_cause') or unavailable('chunk_not_executed', status=c['status']),
                               chunk=c['id'], chunk_pages=[c['start'], c['end']],
                               attempt=(c.get('failure') or {}).get('attempt'), invocation=(c.get('failure') or {}).get('invocation'))
                          for c in failed]
                result.update(error_code='chunk_failed', merged=False, root_cause=causes[0], root_causes=causes)
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
                    merged_quality_path = merged_dir / 'comprehensive_quality.json'
                    merged_quality = wf.read_json(merged_quality_path) if merged_quality_path.is_file() else {}
                    blocking = [i for i in merged_quality.get('issues', []) if isinstance(i, dict) and i.get('id') in
                                ('overflow_source_fallback_cap_exceeded', 'overflow_source_fallback_receipt_incomplete')]
                    if blocking:
                        code = blocking[0]['id']
                        result = dict(wf.blocked_result([wf.finding(code, '原文保留降级的整份文档上限未满足或无法核对；整份失败关闭，不交付合并结果。',
                                      document_cap=merged_quality.get('overflow_source_fallback_document_cap'))]), **base)
                        result.update(error_code=code, merged=False, merge_job=_measure(job), quality_status='fail',
                                      merge_manifest_ref=wf.ref(manifest_path),
                                      overflow_source_fallback_document_cap=merged_quality.get('overflow_source_fallback_document_cap'))
                    else:
                        result = dict(base, status='candidate', merged=True, merge_job=_measure(job),
                                      merged_output_dir=str(merged_dir), merge_manifest_ref=wf.ref(manifest_path),
                                      outputs=manifest['outputs'], merge_issues=manifest['issues'], links=manifest['links'],
                                      toc_entries=manifest['toc_entries'], page_labels=manifest['page_labels'])
                        result.update(wf.quality_verdict(merged_dir))
                        result['cost_ledger'] = sum_ledgers([(c.get('completed') or {}).get('cost_ledger') for c in chunks])
                        result['overflow_source_fallback_document_cap'] = merged_quality.get('overflow_source_fallback_document_cap')
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
        finally:
            if session is not None:
                session.close()
