#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by pdf_translation_artifacts_runtime.py to geometrically verify bilingual left/right orientation."

import re
from collections import Counter
from pathlib import Path
from typing import Any

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
EXPLICIT_LAYOUTS = {"zh-left-en-right", "en-left-zh-right"}


def _load_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception:
        try:
            import pymupdf as fitz  # type: ignore

            return fitz
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"PyMuPDF unavailable: {exc}") from exc


def normalize_layout_name(layout: str | None) -> str | None:
    if not layout or layout in {"off", "backend-default", "backend_default"}:
        return layout.replace("_", "-") if layout else None
    return str(layout).replace("_", "-")


def script_counts(text: str) -> tuple[int, int]:
    value = str(text or "")
    return len(CJK_RE.findall(value)), len(LATIN_RE.findall(value))


def classify_side_scripts(left_cjk: int, left_latin: int, right_cjk: int, right_latin: int) -> str:
    total_cjk = left_cjk + right_cjk
    total_latin = left_latin + right_latin
    if total_cjk < 4 or total_latin < 4:
        return "unknown"
    cjk_left_share = left_cjk / total_cjk
    latin_left_share = left_latin / total_latin
    if cjk_left_share >= 0.62 and latin_left_share <= 0.45:
        return "zh-left-en-right"
    if cjk_left_share <= 0.38 and latin_left_share >= 0.55:
        return "en-left-zh-right"
    return "unknown"


def verify_bilingual_pdf(path: Path, requested_layout: str | None = None) -> dict[str, Any]:
    requested = normalize_layout_name(requested_layout)
    result: dict[str, Any] = {
        "layout_verification": "geometry",
        "requested_layout": requested,
        "observed_layout": "unknown",
        "match": False,
        "pages_checked": 0,
        "classified_pages": 0,
        "page_observations": [],
        "status": "unavailable",
    }
    if not path or not Path(path).is_file():
        result["reason"] = "bilingual_pdf_missing"
        return result
    try:
        fitz = _load_fitz()
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"pymupdf_unavailable:{exc}"
        return result
    observations: list[str] = []
    try:
        with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
            for page_index, page in enumerate(doc):
                midpoint = page.rect.x0 + (page.rect.width / 2)
                left_text = page.get_text("text", clip=fitz.Rect(page.rect.x0, page.rect.y0, midpoint, page.rect.y1))
                right_text = page.get_text("text", clip=fitz.Rect(midpoint, page.rect.y0, page.rect.x1, page.rect.y1))
                left_cjk, left_latin = script_counts(left_text)
                right_cjk, right_latin = script_counts(right_text)
                observed = classify_side_scripts(left_cjk, left_latin, right_cjk, right_latin)
                observations.append(observed)
                result["page_observations"].append(
                    {
                        "page": page_index + 1,
                        "observed_layout": observed,
                        "left_cjk": left_cjk,
                        "left_latin": left_latin,
                        "right_cjk": right_cjk,
                        "right_latin": right_latin,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"geometry_read_failed:{exc}"
        return result
    result["pages_checked"] = len(observations)
    classified = [item for item in observations if item != "unknown"]
    result["classified_pages"] = len(classified)
    if classified:
        observed_layout, _count = Counter(classified).most_common(1)[0]
        result["observed_layout"] = observed_layout
    if requested in EXPLICIT_LAYOUTS:
        result["match"] = result["observed_layout"] == requested
        result["status"] = "ok" if result["match"] else "mismatch"
        if result["status"] == "mismatch":
            result["reason"] = "observed_layout_differs_from_requested"
    elif result["observed_layout"] != "unknown":
        result["match"] = True
        result["status"] = "ok"
    else:
        result["status"] = "unavailable"
        result["reason"] = result.get("reason") or "insufficient_side_script_signal"
    return result


def apply_geometry_verification(
    manifest: dict[str, Any],
    pdf_path: Path | None,
    requested_layout: str | None,
    *,
    require_match: bool,
) -> dict[str, Any]:
    geometry = verify_bilingual_pdf(Path(pdf_path) if pdf_path else Path(""), requested_layout)
    manifest["layout_verification"] = "geometry"
    manifest["observed_layout"] = geometry.get("observed_layout")
    manifest["geometry"] = {
        "status": geometry.get("status"),
        "match": geometry.get("match"),
        "pages_checked": geometry.get("pages_checked"),
        "classified_pages": geometry.get("classified_pages"),
        "page_observations": geometry.get("page_observations"),
        "reason": geometry.get("reason"),
    }
    if require_match and not geometry.get("match"):
        if manifest.get("status") == "ok":
            manifest["status"] = "error"
        manifest["reason"] = str(geometry.get("reason") or "bilingual_layout_geometry_mismatch")
    return manifest
