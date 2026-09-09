from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2.0"
LEGACY_SCHEMA_VERSIONS = {"1.0"}
OFFICECLI_VERSION = "1.0.144"
PPT_MASTER_VERSION = "4.8.0"
PPT_MASTER_COMMIT = "53c9c2a5e9f1a49096324fba4f95833649c6a0f4"
RUNTIME_LOCK_INPUT = f"double6-ppt-cli:0.2.1|officecli:{OFFICECLI_VERSION}|ppt-master:{PPT_MASTER_COMMIT}"
RUNTIME_LOCK_SHA = hashlib.sha256(RUNTIME_LOCK_INPUT.encode()).hexdigest()[:16]
STATUSES = {
    "initialized", "authored", "compiled", "inspected", "repair_needed",
    "verified", "verified_with_warnings", "local_delivered", "delivered_with_warnings", "blocked",
}


class D6PPTError(RuntimeError):
    def __init__(self, message: str, code: str = "d6ppt_error", details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        if "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise D6PPTError(f"Cannot read JSON: {path}: {exc}", "invalid_json") from exc
    if not isinstance(value, dict):
        raise D6PPTError(f"Expected JSON object: {path}", "invalid_json")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def copy_input(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def ensure_owner_writable(path: Path) -> None:
    """Make an attempt-local working copy writable without changing its source."""
    path.chmod(path.stat().st_mode | 0o200)


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_runtime_dir() -> Path:
    return Path.home() / ".cache" / "double6-ppt-cli" / RUNTIME_LOCK_SHA


def run_manifest_path(run: Path) -> Path:
    return run.resolve() / "run_manifest.json"


def load_run(run: Path) -> dict[str, Any]:
    manifest = read_json(run_manifest_path(run))
    version = manifest.get("schema_version")
    if version not in {SCHEMA_VERSION, *LEGACY_SCHEMA_VERSIONS}:
        raise D6PPTError("Unsupported run manifest schema", "schema_version_mismatch")
    if version in LEGACY_SCHEMA_VERSIONS:
        manifest = dict(manifest)
        manifest["schema_version"] = SCHEMA_VERSION
        manifest["_legacy_source_schema_version"] = version
        manifest["_legacy_read_only"] = True
        manifest.setdefault("visual_policy", {
            "mode": "default_visual_review",
            "capability": "unknown",
            "decision": "pending",
        })
        manifest.setdefault("target_application", "powerpoint")
    return manifest


def save_run(run: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("_legacy_read_only"):
        raise D6PPTError(
            "Schema 1.0 runs are readable through an in-memory compatibility view but cannot be rewritten",
            "legacy_run_read_only",
        )
    manifest["updated_at"] = utc_now()
    write_json(run_manifest_path(run), manifest)


def set_status(run: Path, manifest: dict[str, Any], status: str, stage: str, details: Any = None) -> None:
    if status not in STATUSES:
        raise D6PPTError(f"Unknown status: {status}", "invalid_status")
    manifest["status"] = status
    manifest.setdefault("stage_history", []).append({
        "at": utc_now(), "stage": stage, "status": status, "details": details,
    })
    save_run(run, manifest)


def resolve_run_path(run: Path, relative: str) -> Path:
    root = run.resolve()
    result = (root / relative).resolve()
    if result != root and root not in result.parents:
        raise D6PPTError("Run path escapes run directory", "unsafe_path")
    return result
