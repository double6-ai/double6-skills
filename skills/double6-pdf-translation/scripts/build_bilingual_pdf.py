#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def build_en_left_zh_right_pdf_pypdf(source_pdf: Path, translated_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    try:
        from pypdf import PageObject, PdfReader, PdfWriter, Transformation  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pypdf unavailable: {exc}") from exc
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    source_reader = PdfReader(str(source_pdf))
    translated_reader = PdfReader(str(translated_pdf))
    writer = PdfWriter()
    source_pages = len(source_reader.pages)
    translated_pages = len(translated_reader.pages)
    page_count = max(source_pages, translated_pages)
    for index in range(page_count):
        source_page = source_reader.pages[index] if index < source_pages else None
        translated_page = translated_reader.pages[index] if index < translated_pages else None
        source_width = float(source_page.mediabox.width if source_page is not None else translated_page.mediabox.width)
        source_height = float(source_page.mediabox.height if source_page is not None else translated_page.mediabox.height)
        translated_width = float(translated_page.mediabox.width if translated_page is not None else source_page.mediabox.width)
        translated_height = float(translated_page.mediabox.height if translated_page is not None else source_page.mediabox.height)
        page = PageObject.create_blank_page(width=source_width + translated_width, height=max(source_height, translated_height))
        if source_page is not None:
            page.merge_page(source_page)
        if translated_page is not None:
            page.merge_transformed_page(translated_page, Transformation().translate(tx=source_width, ty=0), expand=False)
        writer.add_page(page)
    with output_pdf.open("wb") as handle:
        writer.write(handle)
    link_manifest = repair_pypdf_link_annotations(source_pdf, translated_pdf, output_pdf)
    return {
        "version": 1,
        "status": "ok",
        "layout": "en_left_zh_right",
        "source_pdf": str(source_pdf),
        "translated_pdf": str(translated_pdf),
        "output_pdf": str(output_pdf),
        "render_mode": "pypdf-vector",
        "raster_dpi": None,
        "preview_compatibility": "candidate_direct_content_merge",
        "text_layer_policy": "preserve_merged_page_text_when_viewer_supports_content_stream_merge",
        "source_pages": source_pages,
        "translated_pages": translated_pages,
        "page_count": page_count,
        "link_annotation_repair": link_manifest,
    }


def rects_close(left: Any, right: Any, *, tolerance: float = 1.5) -> bool:
    return (
        abs(float(left.x0) - float(right.x0)) <= tolerance
        and abs(float(left.y0) - float(right.y0)) <= tolerance
        and abs(float(left.x1) - float(right.x1)) <= tolerance
        and abs(float(left.y1) - float(right.y1)) <= tolerance
    )


def repair_pypdf_link_annotations(source_pdf: Path, translated_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    fitz = _load_fitz()
    source_doc = fitz.open(str(source_pdf))
    translated_doc = fitz.open(str(translated_pdf))
    out_doc = fitz.open(str(output_pdf))
    inserted = 0
    removed = 0
    try:
        page_count = min(out_doc.page_count, translated_doc.page_count)
        for index in range(page_count):
            source_width = float(source_doc[index].rect.width) if index < source_doc.page_count else 0.0
            source_links = (
                [link for link in source_doc[index].get_links() if link.get("kind") == fitz.LINK_URI and link.get("uri")]
                if index < source_doc.page_count
                else []
            )
            translated_links = [link for link in translated_doc[index].get_links() if link.get("kind") == fitz.LINK_URI and link.get("uri")]
            if not source_links and not translated_links:
                continue
            out_page = out_doc[index]
            for existing in list(out_page.get_links()):
                if existing.get("kind") == fitz.LINK_URI:
                    out_page.delete_link(existing)
                    removed += 1
            for source_link in source_links:
                source_rect = source_link.get("from")
                source_uri = str(source_link.get("uri") or "")
                if source_rect is None or not source_uri:
                    continue
                out_page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(source_rect), "uri": source_uri})
            for target_link in translated_links:
                target_rect = target_link.get("from")
                target_uri = str(target_link.get("uri") or "")
                if target_rect is None:
                    continue
                shifted = fitz.Rect(target_rect)
                shifted.x0 += source_width
                shifted.x1 += source_width
                out_page.insert_link({"kind": fitz.LINK_URI, "from": shifted, "uri": target_uri})
                inserted += 1
        if inserted or removed:
            tmp_output = output_pdf.with_suffix(output_pdf.suffix + ".links.tmp")
            out_doc.save(str(tmp_output), garbage=4, deflate=True)
    finally:
        out_doc.close()
        translated_doc.close()
        source_doc.close()
    if (inserted or removed) and "tmp_output" in locals():
        tmp_output.replace(output_pdf)
    return {
        "status": "ok",
        "translated_links_shifted": inserted,
        "unshifted_translated_links_removed": removed,
    }


def build_en_left_zh_right_pdf(
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    *,
    mode: str = "pypdf-vector",
    raster_dpi: int = 144,
) -> dict[str, Any]:
    if mode == "pypdf-vector":
        return build_en_left_zh_right_pdf_pypdf(source_pdf, translated_pdf, output_pdf)
    fitz = _load_fitz()
    if mode not in {"vector", "raster", "pypdf-vector"}:
        raise ValueError(f"unsupported bilingual render mode: {mode}")
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    source_doc = fitz.open(str(source_pdf))
    translated_doc = fitz.open(str(translated_pdf))
    out = fitz.open()
    try:
        source_pages = int(source_doc.page_count)
        translated_pages = int(translated_doc.page_count)
        page_count = max(source_pages, translated_pages)
        for index in range(page_count):
            source_page = source_doc[index] if index < source_doc.page_count else None
            translated_page = translated_doc[index] if index < translated_doc.page_count else None
            source_rect = source_page.rect if source_page is not None else translated_page.rect
            translated_rect = translated_page.rect if translated_page is not None else source_page.rect
            width = float(source_rect.width + translated_rect.width)
            height = float(max(source_rect.height, translated_rect.height))
            page = out.new_page(width=width, height=height)
            if source_page is not None:
                left_rect = fitz.Rect(0, 0, source_rect.width, source_rect.height)
                if mode == "raster":
                    _show_pdf_page_raster(page, left_rect, source_page, fitz, raster_dpi)
                else:
                    _show_pdf_page_vector(page, left_rect, source_doc, index, fitz)
            if translated_page is not None:
                right_rect = fitz.Rect(source_rect.width, 0, source_rect.width + translated_rect.width, translated_rect.height)
                if mode == "raster":
                    _show_pdf_page_raster(page, right_rect, translated_page, fitz, raster_dpi)
                else:
                    _show_pdf_page_vector(page, right_rect, translated_doc, index, fitz)
            page.draw_line((source_rect.width, 0), (source_rect.width, height), color=(0.82, 0.82, 0.82), width=0.4)
        out.save(str(output_pdf), garbage=4, deflate=True)
    finally:
        out.close()
        source_doc.close()
        translated_doc.close()
    return {
        "version": 1,
        "status": "ok",
        "layout": "en_left_zh_right",
        "source_pdf": str(source_pdf),
        "translated_pdf": str(translated_pdf),
        "output_pdf": str(output_pdf),
        "render_mode": mode,
        "raster_dpi": raster_dpi if mode == "raster" else None,
        "preview_compatibility": "high" if mode == "raster" else "viewer_dependent",
        "text_layer_policy": "visual_raster_composite; use mono_pdf for searchable translated text" if mode == "raster" else "preserve_embedded_page_text_when_viewer_supports_form_xobject",
        "source_pages": source_pages,
        "translated_pages": translated_pages,
        "page_count": page_count,
    }


def build_manifest(
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    *,
    mode: str = "pypdf-vector",
    raster_dpi: int = 144,
) -> dict[str, Any]:
    try:
        return build_en_left_zh_right_pdf(source_pdf, translated_pdf, output_pdf, mode=mode, raster_dpi=raster_dpi)
    except Exception as exc:  # noqa: BLE001 - 双语后处理失败不能吞掉主 PDF
        return {
            "version": 1,
            "status": "error",
            "layout": "en_left_zh_right",
            "source_pdf": str(source_pdf),
            "translated_pdf": str(translated_pdf),
            "output_pdf": str(output_pdf),
            "render_mode": mode,
            "raster_dpi": raster_dpi if mode == "raster" else None,
            "error": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a bilingual PDF with original English on the left and Chinese translation on the right.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--mode", choices=["vector", "raster", "pypdf-vector"], default="pypdf-vector")
    parser.add_argument("--raster-dpi", type=int, default=144)
    args = parser.parse_args(argv)
    manifest = build_manifest(
        Path(args.source_pdf),
        Path(args.translated_pdf),
        Path(args.output_pdf),
        mode=args.mode,
        raster_dpi=args.raster_dpi,
    )
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output_pdf).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
