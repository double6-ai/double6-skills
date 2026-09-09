from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import D6PPTError, SCHEMA_VERSION, load_run, resolve_run_path, save_run, sha256_file, utc_now, write_json


STATUSES = {"accepted", "accepted_with_warnings", "rejected"}


def record_visual_review(run: Path, status: str, reviewer: str, notes: str) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    if status not in STATUSES:
        raise D6PPTError("Invalid visual review status", "invalid_visual_review")
    if manifest.get("visual_policy", {}).get("capability") != "available":
        raise D6PPTError("Visual review requires declared visual capability", "visual_capability_missing")
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    contact_sheet = run / "review" / "contact_sheet.png"
    render_dir = run / "evidence" / "powerpoint_render"
    fact_source = "powerpoint"
    pages = sorted(render_dir.glob("slide-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
    pdf = render_dir / "powerpoint-render.pdf"
    if not pages:
        render_dir = run / "evidence" / "portable_render"
        fact_source = "libreoffice_portable"
        pages = sorted(render_dir.glob("slide-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
        pdf = next(render_dir.glob("*.pdf"), None)
    if not pages or not contact_sheet.is_file() or pdf is None or not Path(pdf).is_file():
        raise D6PPTError("Run PowerPoint or portable verification/render before recording visual review", "powerpoint_render_missing")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": status,
        "reviewer": reviewer,
        "visual_capability": "available",
        "fact_source": fact_source,
        "pptx_sha256": sha256_file(current),
        "render_pdf_sha256": sha256_file(Path(pdf)),
        "contact_sheet_sha256": sha256_file(contact_sheet),
        "page_count": len(pages),
        "pages": [{"page": index, "path": str(path.relative_to(run)), "sha256": sha256_file(path)} for index, path in enumerate(pages, 1)],
        "notes": notes,
    }
    output = run / "review" / "visual_review.json"
    write_json(output, payload)
    (run / "review" / "visual_review_waiver.json").unlink(missing_ok=True)
    manifest.setdefault("artifacts", {})["visual_review"] = "review/visual_review.json"
    manifest["artifacts"].pop("visual_review_waiver", None)
    save_run(run, manifest)
    return payload
