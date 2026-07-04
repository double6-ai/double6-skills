#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import visible_residue_audit


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py to build and verify conservative visible-residue repair candidates."

CRITICAL_PAGES = {1}
ORDINARY_BODY_ROLES = {"body_prose", "plain text", "text", "paragraph_hybrid", "unknown_visible_line", ""}


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def first_int(value: Any) -> int | None:
    try:
        if value not in {None, ""}:
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def coerce_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def find_cjk_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for value in candidates:
        if Path(value).exists():
            return value
    return None


def protected_or_unsafe_item(item: dict[str, Any]) -> bool:
    text = str(item.get("visible_text") or "")
    if re.search(r"</?style\b", text, flags=re.I):
        return True
    if visible_residue_audit.is_protected_visible_text(text, page=first_int(item.get("page"))):
        return True
    role = str(item.get("layout_role") or "").lower()
    return role not in ORDINARY_BODY_ROLES


def repair_bbox_for_item(item: dict[str, Any]) -> list[float] | None:
    for key in ["source_bbox", "bbox"]:
        bbox = coerce_bbox(item.get(key))
        if bbox:
            return bbox
    return None


def candidate_items(audit: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in audit.get("findings", []) if isinstance(audit.get("findings"), list) else []:
        if not isinstance(item, dict):
            continue
        page = first_int(item.get("page"))
        reason = ""
        if page not in CRITICAL_PAGES:
            reason = "non_critical_page"
        elif item.get("failure_type") != "translated_but_source_visible":
            reason = "not_translated_but_source_visible"
        elif not item.get("ordinary_body_residue"):
            reason = "not_ordinary_body_residue"
        elif protected_or_unsafe_item(item):
            reason = "protected_or_unsafe_layout_role"
        elif not has_cjk(str(item.get("tracking_output") or "")):
            reason = "missing_chinese_tracking_output"
        elif repair_bbox_for_item(item) is None:
            reason = "missing_trusted_pdf_bbox"
        if reason:
            rejected.append({"item": item, "reason": reason})
        else:
            accepted.append(item)
    return accepted, rejected


def fit_bbox_to_page(page: Any, bbox: list[float]) -> Any | None:
    import fitz  # type: ignore

    rect = fitz.Rect(bbox)
    page_rect = page.rect
    if rect.x0 < -2 or rect.y0 < -2 or rect.x1 > page_rect.width + 2 or rect.y1 > page_rect.height + 2:
        return None
    rect = rect & page_rect
    if rect.width < 18 or rect.height < 6:
        return None
    return rect + (-1.5, -1.5, 1.5, 1.5)


def insert_cjk_textbox(page: Any, rect: Any, text: str, fontfile: str) -> int:
    fontsize = max(5.5, min(9.0, rect.height * 0.45))
    for _attempt in range(4):
        remaining = page.insert_textbox(
            rect,
            text,
            fontsize=fontsize,
            fontname="visible-residue-cjk",
            fontfile=fontfile,
            color=(0, 0, 0),
            align=0,
            overlay=True,
        )
        if remaining >= 0:
            return 0
        fontsize *= 0.88
    return -1


def render_candidate_page(output_pdf: Path, post_dir: Path, *, page_number: int = 1, dpi: int = 180) -> Path | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    visual_dir = post_dir / "visual_pages"
    visual_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(output_pdf) as doc:
        if page_number < 1 or page_number > doc.page_count:
            return None
        page = doc[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        path = visual_dir / f"translated_page_{page_number:03d}.png"
        pixmap.save(path)
        return path


def text_layer_has_style_tag(pdf_path: Path, *, page_number: int = 1) -> bool:
    try:
        import fitz  # type: ignore
    except Exception:
        return False
    try:
        with fitz.open(pdf_path) as doc:
            if page_number < 1 or page_number > doc.page_count:
                return False
            return bool(re.search(r"</?style\b", doc[page_number - 1].get_text("text"), flags=re.I))
    except Exception:
        return False


def apply_visible_residue_repair(
    *,
    audit: dict[str, Any],
    translated_pdf: Path | None,
    source_pdf: Path | None,
    output_dir: Path,
    mode: str = "auto",
    proxy_ledger: dict[str, Any] | None = None,
    poppler_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = output_dir / "visible_residue_repair_manifest.json"
    if mode == "off":
        manifest = {"version": 1, "status": "skipped", "reason": "visible_residue_repair_off", "selected_as_delivery": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    if not translated_pdf or not translated_pdf.is_file():
        manifest = {"version": 1, "status": "skipped", "reason": "missing_translated_pdf", "selected_as_delivery": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    if not audit.get("findings"):
        manifest = {"version": 1, "status": "skipped", "reason": "no_visible_residue_findings", "selected_as_delivery": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    try:
        import fitz  # type: ignore
    except Exception as exc:  # noqa: BLE001
        manifest = {"version": 1, "status": "unavailable", "reason": f"pymupdf_unavailable: {exc}", "selected_as_delivery": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    fontfile = find_cjk_font()
    if not fontfile:
        manifest = {"version": 1, "status": "rejected", "reason": "missing_cjk_font", "selected_as_delivery": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest

    repair_items, rejected_items = candidate_items(audit)
    output_pdf = output_dir / f"{translated_pdf.stem}.visible-residue-repaired.zh.pdf"
    actions: list[dict[str, Any]] = []
    if repair_items:
        shutil.copy2(translated_pdf, output_pdf)
        with fitz.open(output_pdf) as doc:
            for index, item in enumerate(repair_items, start=1):
                page_number = first_int(item.get("page")) or 1
                if page_number < 1 or page_number > doc.page_count:
                    rejected_items.append({"item": item, "reason": "page_out_of_range"})
                    continue
                page = doc[page_number - 1]
                bbox = repair_bbox_for_item(item)
                rect = fit_bbox_to_page(page, bbox or [])
                if rect is None:
                    rejected_items.append({"item": item, "reason": "bbox_outside_page"})
                    continue
                try:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions()
                    rc = insert_cjk_textbox(page, rect, str(item.get("tracking_output") or ""), fontfile)
                except Exception as exc:  # noqa: BLE001 - 候选修复不能让主翻译流程失败
                    rejected_items.append({"item": item, "reason": f"repair_exception: {exc}"})
                    continue
                if rc < 0:
                    rejected_items.append({"item": item, "reason": "textbox_overflow"})
                    continue
                actions.append(
                    {
                        "action_id": f"visible-residue-repair-{index:04d}",
                        "page": page_number,
                        "bbox": [round(rect.x0, 3), round(rect.y0, 3), round(rect.x1, 3), round(rect.y1, 3)],
                        "visible_text": item.get("visible_text"),
                        "tracking_output": item.get("tracking_output"),
                    }
                )
            if actions:
                doc.saveIncr()
    else:
        output_pdf = translated_pdf

    post_dir = output_dir / "visible_residue_post_repair"
    post_dir.mkdir(parents=True, exist_ok=True)
    post_audit: dict[str, Any] = {"version": 1, "status": "skipped", "reason": "no_candidate_actions"}
    if actions and output_pdf.exists():
        render_candidate_page(output_pdf, post_dir, page_number=1)
        post_audit = visible_residue_audit.build_visible_residue_audit(
            poppler_audit=poppler_audit or {},
            proxy_ledger=proxy_ledger or {},
            output_dir=post_dir,
        )
        if text_layer_has_style_tag(output_pdf, page_number=1):
            post_audit.setdefault("findings", []).append(
                {
                    "failure_type": "style_tag_leak",
                    "rule": "post_repair_style_tag_leak",
                    "page": 1,
                    "critical_page": True,
                    "delivery_blocking": True,
                    "ordinary_body_residue": False,
                    "visible_text": "<style>",
                }
            )
            post_audit["status"] = "partial"
            post_audit["blocking_count"] = int(post_audit.get("blocking_count") or 0) + 1
    selected = bool(
        mode == "auto"
        and actions
        and post_audit.get("status") == "ok"
        and int(post_audit.get("ordinary_body_critical_count") or 0) == 0
    )
    status = "applied" if selected else ("candidate_rejected" if actions else "rejected")
    manifest = {
        "version": 1,
        "status": status,
        "mode": mode,
        "input_pdf": str(translated_pdf),
        "source_pdf": str(source_pdf) if source_pdf else None,
        "output_pdf": str(output_pdf) if actions and output_pdf.exists() else None,
        "selected_as_delivery": selected,
        "repair_count": len(actions),
        "eligible_count": len(repair_items),
        "rejected_count": len(rejected_items),
        "actions": actions,
        "rejected_items": [
            {
                "reason": item.get("reason"),
                "page": (item.get("item") or {}).get("page") if isinstance(item.get("item"), dict) else None,
                "failure_type": (item.get("item") or {}).get("failure_type") if isinstance(item.get("item"), dict) else None,
                "visible_text": (item.get("item") or {}).get("visible_text") if isinstance(item.get("item"), dict) else None,
            }
            for item in rejected_items[:50]
        ],
        "post_repair_audit": post_audit,
        "post_repair_dir": str(post_dir),
        "delivery_note": "只有 post-repair OCR 与文本层 gate 全部通过时才允许替换主 PDF。",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a conservative visible English residue repair candidate.")
    parser.add_argument("--audit", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--source-pdf")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mode", choices=["auto", "candidate-only", "off"], default="auto")
    parser.add_argument("--proxy-ledger")
    parser.add_argument("--poppler-audit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = apply_visible_residue_repair(
        audit=load_json(Path(args.audit)),
        translated_pdf=Path(args.translated_pdf),
        source_pdf=Path(args.source_pdf) if args.source_pdf else None,
        output_dir=Path(args.output_dir),
        mode=args.mode,
        proxy_ledger=load_json(Path(args.proxy_ledger)) if args.proxy_ledger else {},
        poppler_audit=load_json(Path(args.poppler_audit)) if args.poppler_audit else {},
    )
    print(json.dumps({"status": manifest.get("status"), "repair_count": manifest.get("repair_count", 0)}, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") not in {"unavailable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
