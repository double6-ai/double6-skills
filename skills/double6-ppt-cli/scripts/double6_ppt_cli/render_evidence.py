from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, read_json, resolve_run_path, sha256_file, write_json


RENDER_MANIFEST = Path("evidence/render_manifest.json")


def _inside_run(run: Path, path: Path) -> tuple[str, Path]:
    root = run.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise D6PPTError("Render evidence must stay inside the run", "render_path_outside_run") from exc
    return relative.as_posix(), resolved


def _artifact(run: Path, path: Path) -> dict[str, Any]:
    relative, resolved = _inside_run(run, path)
    if not resolved.is_file():
        raise D6PPTError(f"Render artifact is missing: {relative}", "render_bundle_incomplete")
    return {"path": relative, "sha256": sha256_file(resolved)}


def record_render_manifest(
    run: Path,
    pptx: Path,
    *,
    verification_tier: str,
    renderer: str,
    fact_source: str,
    pdf: Path,
    pages: list[Path],
    contact_sheet: Path,
) -> dict[str, Any]:
    run = run.resolve()
    if verification_tier not in {"native", "portable"}:
        raise D6PPTError("Render tier must be native or portable", "invalid_render_tier")
    if not pages:
        raise D6PPTError("Render bundle contains no pages", "render_bundle_incomplete")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "pptx_sha256": sha256_file(pptx),
        "verification_tier": verification_tier,
        "renderer": renderer,
        "fact_source": fact_source,
        "pdf": _artifact(run, pdf),
        "pages": [_artifact(run, path) for path in pages],
        "contact_sheet": _artifact(run, contact_sheet),
    }
    write_json(run / RENDER_MANIFEST, payload)
    return payload


def clear_render_manifest(run: Path) -> None:
    (run.resolve() / RENDER_MANIFEST).unlink(missing_ok=True)


def load_current_render_manifest(
    run: Path,
    pptx_sha256: str,
    *,
    expected_tier: str | None = None,
) -> dict[str, Any]:
    run = run.resolve()
    path = run / RENDER_MANIFEST
    if not path.is_file():
        raise D6PPTError("Current run has no complete render manifest", "render_manifest_missing")
    payload = read_json(path)
    if payload.get("pptx_sha256") != pptx_sha256:
        raise D6PPTError("Render manifest is stale for the current PPTX", "render_manifest_stale")
    if expected_tier and payload.get("verification_tier") != expected_tier:
        raise D6PPTError("Render manifest belongs to another verification tier", "render_tier_mismatch")
    artifacts = [payload.get("pdf"), payload.get("contact_sheet"), *payload.get("pages", [])]
    if len(payload.get("pages", [])) == 0:
        raise D6PPTError("Render manifest contains no pages", "render_bundle_incomplete")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not artifact.get("path") or not artifact.get("sha256"):
            raise D6PPTError("Render manifest contains an incomplete artifact", "render_bundle_incomplete")
        candidate = resolve_run_path(run, str(artifact["path"]))
        if not candidate.is_file() or sha256_file(candidate) != artifact["sha256"]:
            raise D6PPTError("Render artifact is missing or stale", "render_bundle_stale", {"path": artifact["path"]})
    return payload
