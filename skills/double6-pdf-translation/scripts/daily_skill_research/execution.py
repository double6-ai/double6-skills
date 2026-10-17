# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""Shared subprocess execution and failure-receipt boundaries."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import write_json


SCHEMA_VERSION = 1
SUMMARY_LIMIT = 2048
_SECRET_PATTERN = re.compile(
    r"(?i)(?P<key>api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|password|secret)"
    r"(?P<separator>\s*[:=]\s*)(?P<value>[^\s,;]+)"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_operation(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.")
    return normalized[:80] or "command"


def _redact_text(value: str) -> str:
    return _SECRET_PATTERN.sub(lambda match: f"{match.group('key')}{match.group('separator')}<redacted>", value)


def _output_summary(value: str, *, limit: int = SUMMARY_LIMIT) -> dict[str, Any]:
    redacted = _redact_text(value)
    encoded = value.encode("utf-8", errors="replace")
    truncated = len(redacted) > limit
    excerpt = redacted[-limit:] if truncated else redacted
    return {
        "char_count": len(value),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "excerpt": excerpt,
        "truncated": truncated,
    }


def _redacted_argv(argv: Sequence[str], indices: frozenset[int]) -> list[str]:
    return ["<redacted>" if index in indices else _redact_text(value) for index, value in enumerate(argv)]


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(item) for item in value]
    return value


@dataclass(frozen=True)
class CommandResult:
    operation: str
    argv: tuple[str, ...]
    redacted_argv: tuple[str, ...]
    cwd: str | None
    started_at: str
    finished_at: str
    duration_ms: int
    timeout_seconds: float | None
    returncode: int | None
    signal: int | None
    timed_out: bool
    stdout: str
    stderr: str
    failure_code: str | None
    retryable: bool
    exception_type: str | None
    failure_receipt_path: str | None

    @property
    def success(self) -> bool:
        return self.failure_code is None and self.returncode == 0

    @property
    def status(self) -> str:
        return "succeeded" if self.success else "failed"

    def as_dict(self, *, include_output: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "success": self.success,
            "operation": self.operation,
            "argv": list(self.redacted_argv),
            "cwd": self.cwd,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "returncode": self.returncode,
            "signal": self.signal,
            "timed_out": self.timed_out,
            "stdout_summary": _output_summary(self.stdout),
            "stderr_summary": _output_summary(self.stderr),
            "failure_code": self.failure_code,
            "retryable": self.retryable,
            "exception_type": self.exception_type,
            "failure_receipt_path": self.failure_receipt_path,
        }
        if include_output:
            payload.update({"stdout": self.stdout, "stderr": self.stderr})
        return payload


def write_failure_receipt(
    *,
    receipt_dir: Path,
    operation: str,
    domain: str,
    failure_code: str,
    retryable: bool,
    detail: str | None = None,
    command_result: CommandResult | None = None,
    exception: BaseException | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Atomically persist a sanitized failure receipt and return its path."""

    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_id = f"{_safe_operation(operation)}-{uuid.uuid4().hex[:12]}"
    receipt_path = receipt_dir / f"{receipt_id}.json"
    command = command_result.as_dict() if command_result is not None else None
    raw_detail = detail if detail is not None else (str(exception) if exception is not None else "")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": "execution_failure",
        "receipt_id": receipt_id,
        "occurred_at": _now_iso(),
        "operation": operation,
        "domain": domain,
        "status": "failed",
        "failure_code": failure_code,
        "retryable": retryable,
        "detail": _redact_text(raw_detail),
        "exception_type": type(exception).__name__ if exception is not None else None,
        "command": command,
        "metadata": _sanitize_metadata(dict(metadata or {})),
        "failure_receipt_path": str(receipt_path),
    }
    write_json(receipt_path, payload)
    return str(receipt_path)


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _completed_failure(returncode: int, stderr: str) -> tuple[str | None, bool, int | None]:
    if returncode == 0:
        return None, False, None
    if returncode < 0:
        return "terminated_by_signal", False, abs(returncode)
    lowered = stderr.lower()
    if returncode == 126 or "permission denied" in lowered or "operation not permitted" in lowered:
        return "permission_denied", False, None
    return "nonzero_exit", False, None


def run_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    operation: str,
    cwd: Path | str | None = None,
    timeout_seconds: float | None = None,
    env: Mapping[str, str] | None = None,
    receipt_dir: Path | None = None,
    redact_arg_indices: Sequence[int] = (),
) -> CommandResult:
    """Run one command without retries and write a receipt only on failure."""

    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("argv must be a non-empty sequence of command arguments")
    rendered = tuple(os.fspath(part) for part in argv)
    redacted = tuple(_redacted_argv(rendered, frozenset(redact_arg_indices)))
    rendered_cwd = str(Path(cwd).expanduser().resolve(strict=False)) if cwd is not None else None
    started_at = _now_iso()
    start = time.monotonic()
    returncode: int | None = None
    signal: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    failure_code: str | None = None
    retryable = False
    exception_type: str | None = None
    caught_exception: BaseException | None = None
    try:
        completed = subprocess.run(
            rendered,
            cwd=rendered_cwd,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=dict(env) if env is not None else None,
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        failure_code, retryable, signal = _completed_failure(returncode, stderr)
    except FileNotFoundError as exc:
        failure_code = "executable_not_found"
        exception_type = type(exc).__name__
        stderr = str(exc)
        caught_exception = exc
    except PermissionError as exc:
        failure_code = "permission_denied"
        exception_type = type(exc).__name__
        stderr = str(exc)
        caught_exception = exc
    except subprocess.TimeoutExpired as exc:
        failure_code = "timeout"
        retryable = True
        timed_out = True
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr) or f"timeout after {exc.timeout}s"
        exception_type = type(exc).__name__
        caught_exception = exc
    except OSError as exc:
        failure_code = "spawn_os_error"
        exception_type = type(exc).__name__
        stderr = str(exc)
        caught_exception = exc
    finished_at = _now_iso()
    duration_ms = max(0, round((time.monotonic() - start) * 1000))
    result = CommandResult(
        operation=operation,
        argv=rendered,
        redacted_argv=redacted,
        cwd=rendered_cwd,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        timeout_seconds=timeout_seconds,
        returncode=returncode,
        signal=signal,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        failure_code=failure_code,
        retryable=retryable,
        exception_type=exception_type,
        failure_receipt_path=None,
    )
    if failure_code is None or receipt_dir is None:
        return result
    receipt_path = write_failure_receipt(
        receipt_dir=receipt_dir,
        operation=operation,
        domain="command",
        failure_code=failure_code,
        retryable=retryable,
        detail=stderr,
        command_result=result,
        exception=caught_exception,
    )
    return replace(result, failure_receipt_path=receipt_path)
