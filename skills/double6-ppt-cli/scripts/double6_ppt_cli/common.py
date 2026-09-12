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
SKILL_VERSION = "0.2.12"
# Bootstrap always installs this exact OfficeCLI version.
OFFICECLI_PIN_VERSION = "1.0.144"
# Runtime accepts the pin and later 1.x builds (upstream ships quickly).
OFFICECLI_MIN_VERSION = OFFICECLI_PIN_VERSION
OFFICECLI_VERSION = OFFICECLI_PIN_VERSION
PPT_MASTER_VERSION = "4.8.0"
PPT_MASTER_COMMIT = "53c9c2a5e9f1a49096324fba4f95833649c6a0f4"
RUNTIME_LOCK_INPUT = f"officecli:{OFFICECLI_PIN_VERSION}|ppt-master:{PPT_MASTER_COMMIT}"
RUNTIME_LOCK_SHA = hashlib.sha256(RUNTIME_LOCK_INPUT.encode()).hexdigest()[:16]
STATUSES = {
    "initialized", "authored", "compiled", "inspected", "repair_needed",
    "verified", "verified_with_warnings", "local_delivered", "delivered_with_warnings", "blocked",
}
PPTX_DERIVED_ARTIFACT_KEYS = {
    "findings", "inspected_pptx_sha256", "verification_receipt", "verification_tier",
    "render_manifest", "powerpoint_receipt", "powerpoint_render", "portable_render",
    "portable_editability_receipt", "delivery_manifest", "visual_review", "visual_review_waiver",
    "contact_sheet", "libreoffice_roundtrip", "current_pptx_profile", "inspection_map",
}


def parse_version(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    parts: list[int] = []
    for token in str(value).strip().split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else None


def classify_officecli_version(actual: str | None, *, pin: str = OFFICECLI_PIN_VERSION, minimum: str = OFFICECLI_MIN_VERSION) -> dict[str, Any]:
    """Classify an installed OfficeCLI version against the pin/compat policy."""
    pin_v = parse_version(pin)
    min_v = parse_version(minimum) or pin_v
    actual_v = parse_version(actual)
    if actual_v is None:
        return {
            "status": "fail",
            "reason": "missing",
            "message": f"OfficeCLI is not installed; bootstrap installs pinned {pin}.",
            "risk": None,
            "action": "bootstrap",
        }
    if pin_v is None or min_v is None:
        return {"status": "fail", "reason": "invalid_policy", "message": "Invalid OfficeCLI version policy", "risk": None, "action": "bootstrap"}
    if actual_v[0] != pin_v[0]:
        return {
            "status": "fail",
            "reason": "major_mismatch",
            "message": f"OfficeCLI {actual} major version differs from pin {pin}; runtime contract is 1.x only.",
            "risk": "high",
            "action": "bootstrap",
        }
    if actual_v < min_v:
        return {
            "status": "fail",
            "reason": "too_old",
            "message": f"OfficeCLI {actual} is older than minimum compatible {minimum}.",
            "risk": "high",
            "action": "bootstrap",
        }
    if actual_v == pin_v:
        return {"status": "pass", "reason": "pinned", "message": f"OfficeCLI {actual} matches pin {pin}.", "risk": None, "action": "none"}
    # newer 1.x: usable with risk warning
    direction = "newer" if actual_v > pin_v else "older_but_compatible"
    return {
        "status": "warn",
        "reason": "not_pinned",
        "message": (
            f"OfficeCLI {actual} is {direction} than pin {pin}. Continuing with compatibility risk; "
            f"run bootstrap to re-pin if behavior looks wrong."
        ),
        "risk": "medium" if actual_v > pin_v else "low",
        "action": "bootstrap_optional",
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


def sha256_file_normalized(path: Path) -> str:
    """SHA-256 after normalizing CRLF/CR to LF (Git autocrlf-safe)."""
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def content_sha_matches(path: Path, expected: str) -> bool:
    return sha256_file(path) == expected or sha256_file_normalized(path) == expected


def rel_posix(path: Path, root: Path) -> str:
    """Run-relative path always using forward slashes for cross-platform artifacts."""
    return path.resolve().relative_to(root.resolve()).as_posix()


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


def invalidate_pptx_derived_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = manifest.setdefault("artifacts", {})
    stale = []
    for key in sorted(PPTX_DERIVED_ARTIFACT_KEYS):
        if key in artifacts:
            stale.append({"key": key, "value": artifacts.pop(key)})
    manifest["powerpoint_status"] = "unverified"
    return stale


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
