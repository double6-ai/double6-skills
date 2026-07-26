#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


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


def _show_pdf_page_vector(page: Any, rect: Any, source_doc: Any, page_index: int, fitz: Any) -> None:
    page.show_pdf_page(rect, source_doc, page_index)


def _show_pdf_page_raster(page: Any, rect: Any, source_page: Any, fitz: Any, raster_dpi: int) -> None:
    scale = max(float(raster_dpi), 72.0) / 72.0
    pix = source_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    page.insert_image(rect, pixmap=pix, keep_proportion=False)


def _copy_uri_links(output_page: Any, source_page: Any, x_offset: float, fitz: Any) -> int:
    inserted = 0
    for link in source_page.get_links():
        if link.get("kind") != fitz.LINK_URI or not link.get("uri") or link.get("from") is None:
            continue
        rect = fitz.Rect(link["from"])
        rect.x0 += x_offset
        rect.x1 += x_offset
        output_page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": str(link["uri"])})
        inserted += 1
    return inserted


def build_bilingual_pdf(
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    *,
    layout: str = "zh-left-en-right",
    mode: str = "vector",
    raster_dpi: int = 144,
) -> dict[str, Any]:
    requested_mode = mode
    if mode == "pypdf-vector":
        mode = "vector"
    fitz = _load_fitz()
    if mode not in {"vector", "raster"}:
        raise ValueError(f"unsupported bilingual render mode: {mode}")
    if layout not in {"zh-left-en-right", "en-left-zh-right"}:
        raise ValueError(f"unsupported bilingual layout: {layout}")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    source_doc = fitz.open(str(source_pdf))
    translated_doc = fitz.open(str(translated_pdf))
    left_doc, right_doc = (
        (translated_doc, source_doc)
        if layout == "zh-left-en-right"
        else (source_doc, translated_doc)
    )
    out = fitz.open()
    inserted_links = 0
    try:
        source_pages = int(source_doc.page_count)
        translated_pages = int(translated_doc.page_count)
        page_count = max(source_pages, translated_pages)
        for index in range(page_count):
            left_page = left_doc[index] if index < left_doc.page_count else None
            right_page = right_doc[index] if index < right_doc.page_count else None
            left_rect = left_page.rect if left_page is not None else right_page.rect
            right_rect = right_page.rect if right_page is not None else left_page.rect
            width = float(left_rect.width + right_rect.width)
            height = float(max(left_rect.height, right_rect.height))
            page = out.new_page(width=width, height=height)
            if left_page is not None:
                target_left = fitz.Rect(0, 0, left_rect.width, left_rect.height)
                if mode == "raster":
                    _show_pdf_page_raster(page, target_left, left_page, fitz, raster_dpi)
                else:
                    _show_pdf_page_vector(page, target_left, left_doc, index, fitz)
                    inserted_links += _copy_uri_links(page, left_page, 0.0, fitz)
            if right_page is not None:
                target_right = fitz.Rect(left_rect.width, 0, left_rect.width + right_rect.width, right_rect.height)
                if mode == "raster":
                    _show_pdf_page_raster(page, target_right, right_page, fitz, raster_dpi)
                else:
                    _show_pdf_page_vector(page, target_right, right_doc, index, fitz)
                    inserted_links += _copy_uri_links(page, right_page, float(left_rect.width), fitz)
            page.draw_line((left_rect.width, 0), (left_rect.width, height), color=(0.82, 0.82, 0.82), width=0.4)
        out.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        out.close()
        source_doc.close()
        translated_doc.close()
    return {
        "version": 1,
        "status": "ok",
        "layout": layout.replace("-", "_"),
        "source": "pymupdf_rebuilt",
        "content_sync": "final_mono",
        "layout_verification": "constructed",
        "source_pdf": str(source_pdf),
        "translated_pdf": str(translated_pdf),
        "output_pdf": str(output_pdf),
        "render_mode": mode,
        "requested_render_mode": requested_mode,
        "deprecated_render_mode_alias": requested_mode == "pypdf-vector",
        "raster_dpi": raster_dpi if mode == "raster" else None,
        "preview_compatibility": "high" if mode == "raster" else "viewer_dependent",
        "text_layer_policy": "visual_raster_composite; use mono_pdf for searchable translated text" if mode == "raster" else "preserve_embedded_page_text_when_viewer_supports_form_xobject",
        "source_pages": source_pages,
        "translated_pages": translated_pages,
        "page_count": page_count,
        "uri_links_copied": inserted_links,
    }


def build_manifest(
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    *,
    layout: str = "zh-left-en-right",
    mode: str = "vector",
    raster_dpi: int = 144,
) -> dict[str, Any]:
    try:
        return build_bilingual_pdf(
            source_pdf,
            translated_pdf,
            output_pdf,
            layout=layout,
            mode=mode,
            raster_dpi=raster_dpi,
        )
    except Exception as exc:  # noqa: BLE001 - 双语后处理失败不能吞掉主 PDF
        return {
            "version": 1,
            "status": "error",
            "layout": layout.replace("-", "_"),
            "source": "pymupdf_rebuilt",
            "content_sync": "unknown",
            "layout_verification": "failed",
            "source_pdf": str(source_pdf),
            "translated_pdf": str(translated_pdf),
            "output_pdf": str(output_pdf),
            "render_mode": mode,
            "raster_dpi": raster_dpi if mode == "raster" else None,
            "error": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a bilingual PDF from the English source and Chinese translation.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--layout", choices=["zh-left-en-right", "en-left-zh-right"], default="zh-left-en-right")
    parser.add_argument("--mode", choices=["vector", "raster", "pypdf-vector"], default="vector")
    parser.add_argument("--raster-dpi", type=int, default=144)
    args = parser.parse_args(argv)
    if args.mode == "pypdf-vector":
        print(
            "DEPRECATION: --mode pypdf-vector now uses PyMuPDF vector mode; use --mode vector.",
            file=sys.stderr,
        )
    manifest = build_manifest(
        Path(args.source_pdf),
        Path(args.translated_pdf),
        Path(args.output_pdf),
        layout=args.layout,
        mode=args.mode,
        raster_dpi=args.raster_dpi,
    )
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output_pdf).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
