from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, resolve_run_path, save_run, sha256_file, utc_now, write_json, rel_posix
from .render_evidence import load_current_render_manifest


STATUSES = {"accepted", "accepted_with_warnings", "rejected"}


def _run_palette(run: Path) -> dict[str, Any]:
    from .native_markers import parse_spec_lock_palette

    for candidate in (run / "authoring" / "project" / "spec_lock.md", run / "build" / "project" / "spec_lock.md"):
        if candidate.is_file():
            return parse_spec_lock_palette(candidate.read_text(encoding="utf-8")) or {}
    return {}


def record_visual_review(run: Path, status: str, reviewer: str, notes: str, rubric: dict[str, Any] | None = None) -> dict[str, Any]:
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
    quality: dict[str, Any] | None = None
    if manifest.get("mode") == "generate" and status != "rejected":
        from .visual_quality import compute_visual_metrics, evaluate_rubric

        if rubric is None:
            raise D6PPTError(
                "Generate-mode visual acceptance requires an 8-dimension rubric (--rubric); see references/visual-quality.md",
                "visual_rubric_required",
            )
        rubric_result = evaluate_rubric(rubric)
        metrics = compute_visual_metrics(current, pages, palette=_run_palette(run))
        quality = {"rubric": rubric_result, "metrics": metrics}
        if not rubric_result["pass"] or metrics["status"] != "pass":
            write_json(run / "review" / "visual_quality.json", quality)
            raise D6PPTError(
                "Visual quality gate failed: fix the deck and re-render (rubric mean>=3.5, every dimension>=3, no metric errors)",
                "visual_quality_failed",
                {"rubric": rubric_result, "metric_errors": [f for f in metrics["findings"] if f["severity"] == "error"]},
            )
    elif rubric is not None:
        from .visual_quality import evaluate_rubric

        quality = {"rubric": evaluate_rubric(rubric)}
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
    if quality is not None:
        payload["visual_quality"] = quality
        write_json(run / "review" / "visual_quality.json", quality)
    output = run / "review" / "visual_review.json"
    write_json(output, payload)
    (run / "review" / "visual_review_waiver.json").unlink(missing_ok=True)
    manifest.setdefault("artifacts", {})["visual_review"] = "review/visual_review.json"
    manifest["artifacts"].pop("visual_review_waiver", None)
    save_run(run, manifest)
    return payload


def visual_metrics_for_run(run: Path) -> dict[str, Any]:
    """Compute the deterministic visual checks for the current render without recording a review."""
    from .visual_quality import compute_visual_metrics

    run = run.resolve()
    manifest = load_run(run)
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    render = load_current_render_manifest(run, sha256_file(current), expected_tier=manifest.get("artifacts", {}).get("verification_tier"))
    pages = [resolve_run_path(run, item["path"]) for item in render["pages"]]
    return compute_visual_metrics(current, pages, palette=_run_palette(run))
