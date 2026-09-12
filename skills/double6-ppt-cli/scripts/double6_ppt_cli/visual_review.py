from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, resolve_run_path, save_run, sha256_file, utc_now, write_json, rel_posix
from .render_evidence import load_current_render_manifest


STATUSES = {"accepted", "accepted_with_warnings", "rejected"}


def record_visual_review(run: Path, status: str, reviewer: str, notes: str) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    if status not in STATUSES:
        raise D6PPTError("Invalid visual review status", "invalid_visual_review")
    if manifest.get("visual_policy", {}).get("capability") != "available":
        raise D6PPTError("Visual review requires declared visual capability", "visual_capability_missing")
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    current_sha = sha256_file(current)
    expected_tier = manifest.get("artifacts", {}).get("verification_tier")
    render = load_current_render_manifest(run, current_sha, expected_tier=expected_tier)
    contact_sheet = resolve_run_path(run, render["contact_sheet"]["path"])
    pdf = resolve_run_path(run, render["pdf"]["path"])
    pages = [resolve_run_path(run, item["path"]) for item in render["pages"]]
    render_manifest_path = run / "evidence" / "render_manifest.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": status,
        "reviewer": reviewer,
        "visual_capability": "available",
        "fact_source": render["fact_source"],
        "verification_tier": render["verification_tier"],
        "pptx_sha256": current_sha,
        "render_manifest_sha256": sha256_file(render_manifest_path),
        "render_pdf_sha256": sha256_file(Path(pdf)),
        "contact_sheet_sha256": sha256_file(contact_sheet),
        "page_count": len(pages),
        "pages": [{"page": index, "path": rel_posix(path, run), "sha256": sha256_file(path)} for index, path in enumerate(pages, 1)],
        "notes": notes,
    }
    output = run / "review" / "visual_review.json"
    write_json(output, payload)
    (run / "review" / "visual_review_waiver.json").unlink(missing_ok=True)
    manifest.setdefault("artifacts", {})["visual_review"] = "review/visual_review.json"
    manifest["artifacts"].pop("visual_review_waiver", None)
    save_run(run, manifest)
    return payload
