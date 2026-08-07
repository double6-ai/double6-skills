"""Double6 当前活动版本的共享原语、事务提交与运行状态。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REFERENCES = PACKAGE_ROOT / "references"
ALLOWED_STATES = {
    "intake",
    "clarifying",
    "awaiting_product_confirmation",
    "ready_to_build",
    "candidate_built",
    "evaluation_failed",
    "local_delivered",
}


class ContractError(ValueError):
    """输入或运行产物不满足活动合同时抛出。"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    if not path.is_file():
        raise ContractError(f"文件不存在：{path}")
    return digest_bytes(path.read_bytes())


def product_content_sha256(product: dict[str, Any]) -> str:
    """计算用户实际确认的产品内容摘要；确认回执自身不参与，避免循环依赖。"""
    value = deepcopy(product)
    value.pop("confirmation", None)
    return digest_bytes(canonical(value))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON 顶层必须是对象：{path}")
    return value


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp = Path(handle.name)
    os.replace(temp, path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def write_text(path: Path, value: str) -> None:
    _atomic_bytes(path, value.encode("utf-8"))


def manifest() -> dict[str, Any]:
    return read_json(PACKAGE_ROOT / "manifest.json")


def version() -> str:
    return str(manifest()["version"])


def release_id() -> str:
    return f"{manifest()['skill_id']}@{version()}"


def schema(name: str) -> int:
    try:
        return int(manifest()["schemas"][name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"manifest 缺少 schema：{name}") from exc


def safe_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ContractError("路径必须是非空相对路径")
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"路径越界：{relative}") from exc
    if not path.is_file():
        raise ContractError(f"文件不存在：{relative}")
    return path


def tree_rows(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise ContractError(f"目录不存在：{root}")
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": digest_file(path), "size": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts
    ]


def tree_digest(root: Path) -> dict[str, Any]:
    rows = tree_rows(root)
    return {"file_count": len(rows), "sha256": digest_bytes(canonical(rows)), "files": rows}


def _transaction_marker(run_dir: Path) -> Path:
    return run_dir / ".transaction.json"


def _remove_staging_if_possible(staging: Path) -> list[str]:
    """尽力清理 staging；受限宿主禁止删除时不能影响已提交数据。"""
    if not staging.exists():
        return []
    try:
        shutil.rmtree(staging)
    except OSError as exc:
        return [f"transaction_staging_retained:{staging.name}:{exc}"]
    return []


def recover_transaction(run_dir: Path) -> list[str]:
    """完成一次被中断的向前提交。

    ``.transaction.json`` 是可重入 journal，而不是必须删除的临时文件。某些
    Windows 宿主会拦截 ``Path.unlink``；此时只要所有目标已落盘，就把 journal
    原子标记为 committed，后续调用直接复用它，不会把成功提交误报为失败。
    """
    marker_path = _transaction_marker(run_dir)
    if not marker_path.is_file():
        return []
    marker = read_json(marker_path)
    staging = run_dir / str(marker.get("staging_dir", ""))
    if marker.get("phase") == "committed":
        # committed 之后的文件变化由各业务 gate（例如确认 SHA）处理；不能把
        # 用户或测试对已提交文件的改动误判为半截事务。
        return _remove_staging_if_possible(staging)
    for row in marker.get("writes", []):
        target = run_dir / str(row["target"])
        expected = str(row["sha256"])
        if target.is_file() and digest_file(target) == expected:
            continue
        staged = staging / str(row["target"])
        if not staged.is_file() or digest_file(staged) != expected:
            raise ContractError(f"事务无法恢复：{row['target']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)
    if marker.get("phase") != "committed":
        completed = dict(marker)
        completed["phase"] = "committed"
        completed["committed_at"] = now()
        # 使用 replace 写回同一路径，不依赖删除权限。
        write_json(marker_path, completed)
    return _remove_staging_if_possible(staging)


def cleanup_transaction(run_dir: Path) -> dict[str, Any]:
    """恢复可恢复的事务并报告受宿主策略保留的 staging。"""
    warnings = recover_transaction(run_dir)
    marker_path = _transaction_marker(run_dir)
    marker = read_json(marker_path) if marker_path.is_file() else None
    retained = sorted(
        path.name for path in run_dir.glob(".transaction-*") if path.exists()
    )
    return {
        "status": "pass",
        "journal": "committed" if marker and marker.get("phase") == "committed" else "absent",
        "retained_staging": retained,
        "warnings": warnings,
    }


def commit(run_dir: Path, writes: dict[str, dict[str, Any] | str]) -> None:
    """原子化提交一组快照；run.json 必须存在并最后落盘。"""
    if "run.json" not in writes:
        raise ContractError("事务必须包含 run.json")
    recover_transaction(run_dir)
    transaction_id = digest_bytes(os.urandom(24))[:16]
    staging_name = f".transaction-{transaction_id}"
    staging = run_dir / staging_name
    rows: list[dict[str, Any]] = []
    ordered = [key for key in writes if key != "run.json"] + ["run.json"]
    for relative in ordered:
        value = writes[relative]
        payload = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            if isinstance(value, dict)
            else str(value).encode("utf-8")
        )
        staged = staging / relative
        _atomic_bytes(staged, payload)
        rows.append({"target": relative, "sha256": digest_bytes(payload)})
    write_json(_transaction_marker(run_dir), {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "staging_dir": staging_name,
        "writes": rows,
        "created_at": now(),
        "phase": "prepared",
    })
    recover_transaction(run_dir)


def load_run(run_dir: Path) -> dict[str, Any]:
    recover_transaction(run_dir)
    run = read_json(run_dir / "run.json")
    if run.get("release") != release_id() or run.get("schema_version") != schema("run"):
        raise ContractError("活动运行时只读取当前版本；旧任务请保留为历史证据，不混入新运行")
    if run.get("state") not in ALLOWED_STATES:
        raise ContractError(f"未知运行状态：{run.get('state')}")
    return run


def require_state(run: dict[str, Any], *states: str) -> None:
    if run.get("state") not in states:
        raise ContractError(f"当前状态 {run.get('state')} 不允许此操作；需要 {', '.join(states)}")


def transition(
    run: dict[str, Any],
    state: str,
    status: str,
    event: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in ALLOWED_STATES:
        raise ContractError(f"非法目标状态：{state}")
    updated = dict(run)
    updated["state"] = state
    updated["status"] = status
    updated["updated_at"] = now()
    history = list(updated.get("history", []))
    history.append({"at": updated["updated_at"], "event": event, "detail": detail or {}})
    updated["history"] = history[-100:]
    return updated


def read_text_arg(path: str | None, value: str | None, name: str) -> str:
    text = Path(path).read_text(encoding="utf-8") if path else value or ""
    if not text.strip():
        raise ContractError(f"{name} 不能为空")
    return text.strip()
