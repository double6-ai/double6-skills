#!/usr/bin/env python3
from __future__ import annotations
from stable_page_raster import stable_get_pixmap

import argparse
import json
import math
import os
import re
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


# 标准双语页合同：左页恒为源文页、右页恒为译文页（页序不随语言变化）。
# 文件名与清单中的语言标注只取调用方已知的翻译方向；方向未知时不猜，使用中性名称。
SUPPORTED_DIRECTIONS = {("en", "zh"), ("zh", "en")}
LANGUAGE_LABELS = {"en": "英文", "zh": "中文"}
NEUTRAL_LAYOUT = "source_left_translation_right"
NEUTRAL_NAME_INFIX = "source-left.translation-right"


def _language(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return "en" if text.startswith("en") else "zh" if text.startswith("zh") else text


def bilingual_direction(source_language: str | None = None, target_language: str | None = None,
                        *, basis: str | None = None) -> dict[str, Any]:
    source, target = _language(source_language), _language(target_language)
    if (source, target) in SUPPORTED_DIRECTIONS:
        return {
            "layout": f"{source}_left_{target}_right",
            "name_infix": f"{source}-left.{target}-right",
            "left_role": "source", "right_role": "translation",
            "left_language": source, "right_language": target,
            "left_label": f"{LANGUAGE_LABELS[source]}原文", "right_label": f"{LANGUAGE_LABELS[target]}译文",
            "direction_basis": basis or "caller_declared",
        }
    return {
        "layout": NEUTRAL_LAYOUT,
        "name_infix": NEUTRAL_NAME_INFIX,
        "left_role": "source", "right_role": "translation",
        "left_language": "unknown", "right_language": "unknown",
        "left_label": "原文", "right_label": "译文",
        "direction_basis": "unknown",
        **({"declared_source_language": source, "declared_target_language": target} if (source or target) else {}),
    }


def name_infix_for(manifest: dict[str, Any] | None) -> str:
    """由清单已记录的左右语言重建文件名中缀；记录缺失或未知时为中性中缀。"""
    manifest = manifest or {}
    pair = (manifest.get("left_language"), manifest.get("right_language"))
    return f"{pair[0]}-left.{pair[1]}-right" if pair in SUPPORTED_DIRECTIONS else NEUTRAL_NAME_INFIX


def direction_fields(direction: dict[str, Any] | None) -> dict[str, Any]:
    direction = direction or bilingual_direction()
    return {key: value for key, value in direction.items() if key != "name_infix"}


def _show_pdf_page_vector(page: Any, rect: Any, source_doc: Any, page_index: int, fitz: Any) -> None:
    page.show_pdf_page(rect, source_doc, page_index)


def _show_pdf_page_raster(page: Any, rect: Any, source_page: Any, fitz: Any, raster_dpi: int) -> None:
    scale = max(float(raster_dpi), 72.0) / 72.0
    pix = stable_get_pixmap(source_page, matrix=fitz.Matrix(scale, scale), alpha=False)
    page.insert_image(rect, pixmap=pix, keep_proportion=False)


def build_en_left_zh_right_pdf_pypdf(source_pdf: Path, translated_pdf: Path, output_pdf: Path, *,
                                    direction: dict[str, Any] | None = None) -> dict[str, Any]:
    """历史函数名保留；左源页、右译页。语言标注见 direction（未知时为中性）。"""
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
        "status": "ok" if link_manifest["status"] == "ok" else "needs_review",
        **direction_fields(direction),
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
    """按各输入页面重建URI和内部跳转，避免merge产生孤立页对象与错误坐标。"""
    fitz = _load_fitz()
    source_doc = fitz.open(str(source_pdf))
    translated_doc = fitz.open(str(translated_pdf))
    out_doc = fitz.open(str(output_pdf))
    inserted = removed = source_inserted = internal_inserted = 0
    named_resolved = remote_inserted = 0
    unsupported = []
    tmp_output = None

    def right_shift(index: int) -> float:
        page = source_doc[index] if index < len(source_doc) else translated_doc[index]
        return float(page.mediabox.width)

    def transform(value, original_page, output_page, shift):
        # get_links采用PyMuPDF页面坐标；先回到原PDF坐标，再应用合页平移。
        value = value * ~original_page.transformation_matrix
        value = value * fitz.Matrix(1, 0, 0, 1, shift, 0)
        return value * output_page.transformation_matrix

    try:
        names_by_side={'source':source_doc.resolve_names(),'translated':translated_doc.resolve_names()}
        for index in range(out_doc.page_count):
            out_page = out_doc[index]
            for existing in list(out_page.get_links()):
                if (existing.get("kind") in (fitz.LINK_URI, fitz.LINK_GOTO, fitz.LINK_GOTOR)
                        or out_doc.xref_get_key(existing['xref'], 'A/S') == ('name', '/GoToR')
                        or existing.get('kind')==fitz.LINK_NAMED and existing.get('nameddest')):
                    out_page.delete_link(existing)
                    removed += 1
            for side, doc in (("source", source_doc), ("translated", translated_doc)):
                if index >= len(doc):
                    continue
                page = doc[index]
                named_destinations=names_by_side[side]
                for link in page.get_links():
                    kind = link.get("kind")
                    # MuPDF exposes a remote named destination as LINK_LAUNCH
                    # with a #nameddest suffix. The PDF action is authoritative.
                    if doc.xref_get_key(link['xref'], 'A/S') == ('name', '/GoToR'):
                        dtype, remote_name = doc.xref_get_key(link['xref'], 'A/D')
                        ftype, remote_file = doc.xref_get_key(link['xref'], 'A/F')
                        if dtype == 'string':
                            if ftype != 'string':
                                raise ValueError('remote_file_specification_unsupported')
                            link = {**link, 'kind': fitz.LINK_GOTOR, 'page': -1,
                                    'to': remote_name, 'file': remote_file}
                            kind = fitz.LINK_GOTOR
                    if kind==fitz.LINK_NAMED and link.get('nameddest'):
                        name=link['nameddest'];resolved=named_destinations.get(name,{})
                        destination=resolved.get('page',-1);point=resolved.get('to')
                        if (isinstance(destination,int) and 0<=destination<len(doc) and point is not None
                                and len(point)==2 and all(math.isfinite(v) for v in point)):
                            # resolve_names返回PDF坐标；现有GOTO分支接收PyMuPDF页面坐标。
                            link={**link,'kind':fitz.LINK_GOTO,'page':destination,
                                  'to':fitz.Point(point)*doc[destination].transformation_matrix,
                                  'zoom':resolved.get('zoom',0)}
                            kind=fitz.LINK_GOTO;named_resolved+=1
                        elif isinstance(destination,int) and 0<=destination<len(doc) and resolved.get('dest','').strip()=='/Fit':
                            link={**link,'kind':fitz.LINK_GOTO,'page':destination,'to':fitz.Point(0,0),
                                  'fit_original_page':True}
                            kind=fitz.LINK_GOTO;named_resolved+=1
                        else:
                            shift=right_shift(index) if side=='translated' else 0
                            out_page.insert_link({'kind':fitz.LINK_GOTO,'page':-1,'to':name,
                                'from':transform(fitz.Rect(link['from']),page,out_page,shift)})
                            unsupported.append({'page':index+1,'side':side,'kind':kind,'nameddest':name,
                                                'reason':'source_named_destination_unresolved' if destination<0 else 'named_destination_view_unsupported',
                                                'view':resolved.get('dest'),'annotation_preserved':True})
                            continue
                    if kind not in (fitz.LINK_URI, fitz.LINK_GOTO, fitz.LINK_GOTOR):
                        unsupported.append({"page": index + 1, "side": side, "kind": kind})
                        continue
                    shift = right_shift(index) if side == "translated" else 0
                    rebuilt = {"kind": kind, "from": transform(fitz.Rect(link["from"]), page, out_page, shift)}
                    if kind == fitz.LINK_URI:
                        rebuilt["uri"] = link["uri"]
                    elif kind == fitz.LINK_GOTOR:
                        # Remote destinations use the original PDF coordinates.
                        # Relative files must still resolve to the same document
                        # after the reader is written to another directory.
                        path=Path(link['file'])
                        input_path=source_pdf if side=='source'else translated_pdf
                        if not path.is_absolute():
                            path=Path(os.path.relpath((input_path.parent/path).resolve(),output_pdf.parent))
                        destination=link.get('page',-1)
                        point=link.get('to',(0,0))
                        if destination>=0:point=fitz.Point(point)
                        elif not isinstance(point,str):raise ValueError('remote_named_destination_missing')
                        rebuilt.update(file=str(path),page=destination,to=point,zoom=link.get('zoom',0))
                        dtype,remote_destination=doc.xref_get_key(link['xref'],'A/D')
                        # MuPDF get_links may expose (0,0) for a remote XYZ
                        # target without loading that file. Bind the actual
                        # annotation destination rather than those placeholders.
                        if dtype=='array':
                            if not re.fullmatch(r'\[\s*\d+\s*/(?:XYZ|Fit|FitH|FitV|FitR|FitB|FitBH|FitBV)(?:\s+(?:null|[-+]?(?:\d+\.?\d*|\.\d+)))*\s*\]',remote_destination):
                                raise ValueError('remote_destination_array_unsupported')
                        elif dtype=='string':remote_destination=fitz.get_pdf_str(remote_destination)
                        else:raise ValueError('remote_destination_kind_unsupported')
                        remote_inserted+=1
                    else:
                        destination = link.get("page", -1)
                        if not isinstance(destination, int) or not 0 <= destination < min(len(doc), len(out_doc)):
                            raise ValueError("bilingual internal link has no corresponding destination page")
                        dest_shift = right_shift(destination) if side == "translated" else 0
                        rebuilt.update(page=destination,
                            to=transform(fitz.Point(link.get("to", (0, 0))), doc[destination], out_doc[destination], dest_shift),
                            zoom=link.get("zoom", 0))
                        internal_inserted += 1
                    before_xrefs={a[0] for a in out_page.annot_xrefs()} if link.get('fit_original_page') or kind==fitz.LINK_GOTOR else set()
                    out_page.insert_link(rebuilt)
                    if kind==fitz.LINK_GOTOR:
                        added={a[0]for a in out_page.annot_xrefs()}-before_xrefs
                        if len(added)!=1:raise ValueError('cannot_bind_remote_annotation')
                        out_doc.xref_set_key(added.pop(),'A/D',remote_destination)
                    if link.get('fit_original_page'):
                        added={a[0] for a in out_page.annot_xrefs()}-before_xrefs
                        if len(added)!=1:raise ValueError('cannot bind bilingual fit-page annotation')
                        # 将原件整页适配转成合页中的对应半页FitR，保持阅读视图而非丢弃缩放含义。
                        fit_rect=transform(doc[destination].rect,doc[destination],out_doc[destination],dest_shift)
                        pdf_rect=fit_rect*~out_doc[destination].transformation_matrix
                        coordinates=' '.join(format(v,'.6f') for v in pdf_rect)
                        out_doc.xref_set_key(added.pop(),'A/D',f'[{out_doc.page_xref(destination)} 0 R /FitR {coordinates}]')
                    if side == "translated":
                        inserted += 1
                    else:
                        source_inserted += 1
        if inserted or source_inserted or removed:
            tmp_output = output_pdf.with_suffix(output_pdf.suffix + ".links.tmp")
            out_doc.save(str(tmp_output), garbage=4, deflate=True)
    finally:
        out_doc.close()
        translated_doc.close()
        source_doc.close()
    if tmp_output is not None:
        tmp_output.replace(output_pdf)
    return {
        "status": "needs_review" if unsupported else "ok",
        "translated_links_shifted": inserted,
        "source_links_restored": source_inserted,
        "internal_links_restored": internal_inserted,
        "named_destinations_resolved": named_resolved,
        "remote_links_restored": remote_inserted,
        "unshifted_translated_links_removed": removed,
        "unsupported_links": unsupported,
    }


def build_en_left_zh_right_pdf(
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    *,
    mode: str = "pypdf-vector",
    raster_dpi: int = 144,
    direction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode == "pypdf-vector":
        return build_en_left_zh_right_pdf_pypdf(source_pdf, translated_pdf, output_pdf, direction=direction)
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
        **direction_fields(direction),
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
    direction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return build_en_left_zh_right_pdf(source_pdf, translated_pdf, output_pdf, mode=mode, raster_dpi=raster_dpi, direction=direction)
    except Exception as exc:  # noqa: BLE001 - 双语后处理失败不能吞掉主 PDF
        return {
            "version": 1,
            "status": "error",
            **direction_fields(direction),
            "source_pdf": str(source_pdf),
            "translated_pdf": str(translated_pdf),
            "output_pdf": str(output_pdf),
            "render_mode": mode,
            "raster_dpi": raster_dpi if mode == "raster" else None,
            "error": str(exc),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a bilingual PDF with the source page on the left and the translated page on the right.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--mode", choices=["vector", "raster", "pypdf-vector"], default="pypdf-vector")
    parser.add_argument("--raster-dpi", type=int, default=144)
    parser.add_argument("--source-language", choices=["en", "zh"], default=None,
                        help="Language of the source (left) pages; omit when unknown (labels stay neutral).")
    parser.add_argument("--target-language", choices=["en", "zh"], default=None,
                        help="Language of the translated (right) pages; omit when unknown (labels stay neutral).")
    args = parser.parse_args(argv)
    manifest = build_manifest(
        Path(args.source_pdf),
        Path(args.translated_pdf),
        Path(args.output_pdf),
        mode=args.mode,
        raster_dpi=args.raster_dpi,
        direction=bilingual_direction(args.source_language, args.target_language, basis="cli_argument"),
    )
    manifest_path = Path(args.manifest) if args.manifest else Path(args.output_pdf).with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
