# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-24：新增（后端失败根因上浮、确定性失败不重试）；变更见Skill根目录MODIFICATIONS.md。
"""PDF 后端没有产出候选时的根因：只取本次尝试自己写出的结构化产物，核对身份后上浮。

子任务（``_execute-digital``）一侧 ``derive`` + ``write_receipt``：
  在本次尝试的 ``--output-dir`` 内读排版回执 ``_backend_working/<stem>/typesetting_writeback_report.json``
  与 ``render_manifest.json``，得到稳定原因码与结构化细节（页、计数、上限、阶段），连同本尝试身份
  （launch nonce、FREEZE 引用、输出目录、开始时间）与证据文件 sha 写入 ``BACKEND_FAILURE_ROOT_CAUSE.json``。
  不做日志关键字匹配；证据缺失、不可读、早于本尝试开始、不在本尝试输出目录内 → ``root_cause_unavailable``
  （明确写出查过什么），不猜。

父任务一侧 ``verify_for_result``：对一次有界子任务结果，按其 argv 的 ``--output-dir`` / ``--freeze`` 与
launch 回执的 nonce 逐项核对回执与证据 sha；任何一项不符 → ``root_cause_unavailable``（verified=False）。

重试类别（``retry``）：
* ``deterministic``：同一输入与配置必然重现（排版上限、可读下限溢出、子任务自身的合同/输入拒绝）→ 不重试，
  续跑也不重跑；
* ``resource``：后端内部超时 → 沿用既有二分；
* ``unknown``：拿不到可核实的根因 → 沿用既有“瞬时失败重试一次”（不把未知当确定）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

PROTOCOL = 'backend_failure_root_cause_v1'
RECEIPT_NAME = 'BACKEND_FAILURE_ROOT_CAUSE.json'
TYPESETTING_REPORT = 'typesetting_writeback_report.json'
DETERMINISTIC, RESOURCE, TRANSIENT, UNKNOWN = 'deterministic', 'resource', 'transient', 'unknown'
UNAVAILABLE = 'root_cause_unavailable'
# 稳定原因码 → 重试类别（只有这里列出的码会被当作确定性失败）。
CODES = {
    'typesetting_source_fallback_cap_exceeded': DETERMINISTIC,
    'typesetting_readable_floor_overflow': DETERMINISTIC,
    'typesetting_writeback_failed': DETERMINISTIC,
    'pdf_backend_timeout': RESOURCE,
    UNAVAILABLE: UNKNOWN,
}
MAX_ROWS = 20


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    """普通文件、本身不是符号链接，且解析后的实际路径位于 root 的实际路径内（经符号链接逃出即不算）。"""
    try:
        real, base = path.resolve(strict=True), root.resolve(strict=True)
    except OSError:
        return False
    return not path.is_symlink() and path.is_file() and real.is_relative_to(base)


def _ref(path: Path) -> dict[str, str]:
    return {'path': str(path.resolve()), 'sha256': _sha(path)}


def unavailable(problem: str, **details: Any) -> dict[str, Any]:
    return {'code': UNAVAILABLE, 'retry': UNKNOWN, 'stage': 'root_cause_lookup', 'problem': problem,
            'details': details}


# ------------------------------------------------------------------ 子任务一侧：从本尝试产物取根因
def _typesetting_cause(report: dict[str, Any], ref: dict[str, str]) -> dict[str, Any] | None:
    failures = [f for f in report.get('failures') or [] if isinstance(f, dict)]
    if report.get('stage') != 'post_typesetting' or report.get('status') != 'blocked' or not failures:
        return None
    pages = sorted({int(f['page_index']) + 1 for f in failures if isinstance(f.get('page_index'), int)})
    reasons: dict[str, int] = {}
    for row in failures:
        key = str(row.get('reason') or row.get('status') or 'unspecified')
        reasons[key] = reasons.get(key, 0) + 1
    details: dict[str, Any] = {'failure_count': len(failures), 'pages': pages, 'reasons': reasons,
                               'page_count': report.get('page_count')}
    cap = report.get('source_fallback_cap') if isinstance(report.get('source_fallback_cap'), dict) else {}
    if cap.get('status') == 'revoked_cap_exceeded':
        deferred = cap.get('deferred_violations') or []
        enforced = [v for v in cap.get('violations') or [] if isinstance(v, dict) and v not in deferred]
        details['violations'] = [{'scope': v.get('scope'), 'page_index': v.get('page_index'),
                                  'page': v['page_index'] + 1 if isinstance(v.get('page_index'), int) else None,
                                  'count': v.get('count'), 'cap': v.get('cap')} for v in enforced][:MAX_ROWS]
        details['document_cap'] = {'count': cap.get('count'), 'cap': cap.get('document_cap'),
                                   'scope': cap.get('document_cap_scope'),
                                   'deferred_violations': deferred[:MAX_ROWS]}
        code = 'typesetting_source_fallback_cap_exceeded'
    elif reasons.get('hard_readable_floor_overflow'):
        code = 'typesetting_readable_floor_overflow'
    else:
        code = 'typesetting_writeback_failed'
    details['examples'] = [{k: f.get(k) for k in ('page_index', 'paragraph_id', 'role', 'status', 'reason',
                                                    'source_fallback_rejected')} for f in failures[:5]]
    return {'code': code, 'retry': CODES[code], 'stage': 'post_typesetting', 'details': details, 'evidence': [ref]}


def derive(output_dir: Path | str, manifest: dict[str, Any] | None, *, expected_pages: int | None,
           started_at: float | None) -> dict[str, Any]:
    """本尝试输出目录内的结构化证据 → 根因。不读日志、不读其它尝试。"""
    out = Path(output_dir)
    checked: list[str] = []
    candidates = sorted(out.glob(f'_backend_working/*/{TYPESETTING_REPORT}'))
    checked.append(f'_backend_working/*/{TYPESETTING_REPORT}: {len(candidates)}')
    if len(candidates) > 1:
        return unavailable('ambiguous_typesetting_reports', checked=checked,
                           paths=[str(p) for p in candidates[:MAX_ROWS]])
    if candidates:
        path = candidates[0]
        if not _inside(path, out):
            return unavailable('typesetting_report_outside_attempt', checked=checked, path=str(path))
        if started_at is not None and path.stat().st_mtime < started_at:
            return unavailable('typesetting_report_older_than_attempt', checked=checked, path=str(path))
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            return unavailable('typesetting_report_unreadable', checked=checked, path=str(path),
                               error=f'{type(exc).__name__}: {exc}'[:200])
        if not isinstance(report, dict):
            return unavailable('typesetting_report_unreadable', checked=checked, path=str(path))
        if expected_pages is not None and report.get('page_count') != expected_pages:
            return unavailable('typesetting_report_page_count_mismatch', checked=checked, path=str(path),
                               report_pages=report.get('page_count'), expected_pages=expected_pages)
        cause = _typesetting_cause(report, _ref(path))
        if cause:
            return cause
        checked.append(f"typesetting report status={report.get('status')} failures={len(report.get('failures') or [])}")
    errors = [e for e in (manifest or {}).get('errors') or [] if isinstance(e, dict)]
    checked.append('render_manifest.errors: ' + ','.join(str(e.get('error_type')) for e in errors))
    if any(e.get('error_type') == 'timeout' for e in errors):
        manifest_path = out / 'render_manifest.json'
        evidence = [_ref(manifest_path)] if _inside(manifest_path, out) else []
        timeout = next(e for e in errors if e.get('error_type') == 'timeout')
        return {'code': 'pdf_backend_timeout', 'retry': RESOURCE, 'stage': 'pdf_backend',
                'details': {'timeout_seconds': timeout.get('timeout_seconds')}, 'evidence': evidence}
    return unavailable('no_structured_cause', checked=checked,
                       returncode=(manifest or {}).get('returncode'),
                       errors=[{k: e.get(k) for k in ('error_type', 'returncode')} for e in errors[:5]])


def owner_nonce() -> str | None:
    """本子任务的 launch nonce：有界执行在子进程环境里追加的最后一个 owner nonce。"""
    values = [v for v in os.environ.get('PAPER_TRANSLATION_BOUNDED_OWNERS', '').split(',') if v]
    return values[-1] if values else None


def write_receipt(output_dir: Path | str, cause: dict[str, Any], *, freeze_path: Path | str,
                  started_at: float | None) -> dict[str, str]:
    out = Path(output_dir)
    receipt = {'protocol': PROTOCOL, 'schema_version': 1,
               'attempt': {'output_dir': str(out.resolve()), 'freeze_ref': _ref(Path(freeze_path)),
                           'owner_nonce': owner_nonce(), 'started_at': started_at, 'pid': os.getpid()},
               'root_cause': cause}
    path = out / RECEIPT_NAME
    if path.exists():
        raise ValueError('backend failure root-cause receipt already exists in this attempt')
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return _ref(path)


def compact(cause: dict[str, Any]) -> dict[str, Any]:
    """stdout 结构化行用的精简根因（有界执行只保留 stdout 末尾 2 KiB）。"""
    details = cause.get('details') or {}
    keep = {k: details[k] for k in ('failure_count',) if k in details}
    if details.get('pages'):
        keep['pages'] = details['pages'][:MAX_ROWS]
    if details.get('violations'):
        keep['violations'] = details['violations'][:3]
    return {'code': cause.get('code'), 'retry': cause.get('retry'), 'stage': cause.get('stage'),
            'problem': cause.get('problem'), 'details': keep}


def message(cause: dict[str, Any]) -> str:
    details = cause.get('details') or {}
    code = cause.get('code')
    if code == 'typesetting_source_fallback_cap_exceeded':
        rows = '; '.join(f"{v.get('scope')} page {v.get('page')} count {v.get('count')} > cap {v.get('cap')}"
                         for v in details.get('violations') or [])
        return f'排版回执：原文保留降级超出冻结上限（{rows}）；整批撤销后 {details.get("failure_count")} 段写回失败，按设计拒绝。'
    if code == 'typesetting_readable_floor_overflow':
        return f'排版回执：{details.get("failure_count")} 段在可读字号下限仍放不下（页 {details.get("pages")}），按设计拒绝。'
    if code == 'typesetting_writeback_failed':
        return f'排版回执：{details.get("failure_count")} 段原生写回失败（页 {details.get("pages")}）。'
    if code == 'pdf_backend_timeout':
        return f'PDF 后端内部超时（{details.get("timeout_seconds")} s）。'
    return f'PDF 后端未产出候选，且本尝试没有可核实的结构化根因（{cause.get("problem")}）。'


# ------------------------------------------------------------------ 父任务一侧：核对本尝试回执
def _argv_value(argv: list[str], flag: str) -> str | None:
    for index, value in enumerate(argv[:-1]):
        if value == flag:
            return argv[index + 1]
    return None


def verify_for_result(result: dict[str, Any], claimed_ref: Any) -> dict[str, Any]:
    """有界子任务结果 + 子任务声称的回执引用 → 核实后的根因（失败即 root_cause_unavailable，verified=False）。"""
    command = result.get('command') or {}
    argv = [str(v) for v in command.get('argv') or []]
    output_dir, freeze = _argv_value(argv, '--output-dir'), _argv_value(argv, '--freeze')
    if not output_dir or not freeze:
        return dict(unavailable('attempt_identity_missing_from_argv'), verified=False)
    out = Path(output_dir)
    if not isinstance(claimed_ref, dict) or set(claimed_ref) != {'path', 'sha256'}:
        return dict(unavailable('root_cause_receipt_ref_invalid'), verified=False)
    path = Path(claimed_ref['path'])
    if path != (out / RECEIPT_NAME).resolve() and path != out / RECEIPT_NAME:
        return dict(unavailable('root_cause_receipt_not_in_attempt', path=str(path), output_dir=output_dir),
                    verified=False)
    if not _inside(path, out) or _sha(path) != claimed_ref['sha256']:
        return dict(unavailable('root_cause_receipt_missing_or_changed', path=str(path)), verified=False)
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return dict(unavailable('root_cause_receipt_unreadable', path=str(path)), verified=False)
    attempt = receipt.get('attempt') if isinstance(receipt, dict) else None
    cause = receipt.get('root_cause') if isinstance(receipt, dict) else None
    if receipt.get('protocol') != PROTOCOL or not isinstance(attempt, dict) or not isinstance(cause, dict):
        return dict(unavailable('root_cause_receipt_schema_invalid', path=str(path)), verified=False)
    launch_nonce = None
    launch = result.get('launch_receipt')
    try:
        launch_nonce = json.loads(Path(launch).read_text(encoding='utf-8')).get('nonce') if launch else None
    except (OSError, ValueError, AttributeError):
        launch_nonce = None
    problems = []
    if attempt.get('output_dir') != str(out.resolve()):
        problems.append('output_dir')
    try:
        if attempt.get('freeze_ref') != _ref(Path(freeze)):
            problems.append('freeze_ref')
    except OSError:
        problems.append('freeze_ref')
    if not launch_nonce or attempt.get('owner_nonce') != launch_nonce:
        problems.append('owner_nonce')
    code = cause.get('code')
    if code not in CODES or cause.get('retry') != CODES[code]:
        problems.append('code')
    for evidence in cause.get('evidence') or []:
        epath = Path(evidence.get('path', '')) if isinstance(evidence, dict) else Path('')
        if not isinstance(evidence, dict) or not _inside(epath, out) or _sha(epath) != evidence.get('sha256'):
            problems.append('evidence')
            break
    if CODES.get(code) in (DETERMINISTIC, RESOURCE) and not cause.get('evidence'):
        problems.append('evidence_missing')
    if problems:
        return dict(unavailable('root_cause_receipt_identity_mismatch', path=str(path), mismatched=problems,
                                claimed_code=code), verified=False)
    return dict(cause, verified=True, receipt_ref=dict(claimed_ref),
                attempt={k: attempt.get(k) for k in ('output_dir', 'owner_nonce', 'started_at')})
