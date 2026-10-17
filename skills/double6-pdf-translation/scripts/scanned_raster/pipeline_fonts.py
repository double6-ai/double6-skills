# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline fonts：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def _embedded_cjk_font() -> tuple[str, bytes, dict[str, Any]]:
    """Return an embedded CJK font, preferring a local serif book face."""
    from scanned_raster.pipeline_resources import _sha256_bytes
    import fitz

    candidates = [
        Path(value)
        for value in (
            os.environ.get("PAPER_TRANSLATION_SCANNED_CJK_FONT"),
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
            "/usr/share/fonts/opentype/adobe-source-han-serif/SourceHanSerifSC-Regular.otf",
        )
        if value
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload, face_metadata = _load_preferred_serif_font(path)
            font = fitz.Font(fontbuffer=payload)
            if not font.has_glyph(ord("中")):
                continue
            alias = "PTEmbeddedCJK"
            return alias, payload, {
                "alias": alias,
                "base_font": str(font.name or face_metadata.get("family") or path.stem),
                "source": "local_serif_font",
                "source_path": str(path),
                "source_sha256": _sha256_bytes(payload),
                "source_bytes": len(payload),
                "style_class": "serif",
                **face_metadata,
            }
        except Exception:  # noqa: BLE001
            continue

    font = fitz.Font(fontname="china-s")
    buffer = bytes(font.buffer)
    if not buffer:
        raise RuntimeError("embedded_cjk_font_buffer_empty")
    alias = "PTEmbeddedCJK"
    return alias, buffer, {
        "alias": alias,
        "base_font": str(font.name or "Droid Sans Fallback Regular"),
        "source": "pymupdf_builtin_china_s_buffer",
        "source_sha256": _sha256_bytes(buffer),
        "source_bytes": len(buffer),
        "style_class": "sans_fallback",
    }


def _font_name_values(font: Any, name_ids: set[int]) -> set[str]:
    values: set[str] = set()
    for record in font["name"].names:
        if int(record.nameID) not in name_ids:
            continue
        try:
            values.add(record.toUnicode())
        except Exception:  # noqa: BLE001
            continue
    return values

def _load_preferred_serif_font(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.suffix.casefold() != ".ttc":
        payload = path.read_bytes()
        return payload, {"font_container": path.suffix.casefold().lstrip("."), "font_face_index": 0}

    from fontTools.ttLib import TTCollection

    collection = TTCollection(str(path))
    try:
        ranked: list[tuple[int, int, Any, set[str], set[str]]] = []
        for index, font in enumerate(collection.fonts):
            families = _font_name_values(font, {1, 16})
            subfamilies = _font_name_values(font, {2, 17})
            family_text = " ".join(families).casefold()
            subfamily_text = " ".join(subfamilies).casefold()
            score = 0
            if "songti sc" in family_text:
                score += 100
            elif "source han serif sc" in family_text:
                score += 90
            elif "noto serif cjk sc" in family_text:
                score += 80
            elif "stsong" in family_text:
                score += 70
            if "regular" in subfamily_text or "normal" in subfamily_text:
                score += 20
            ranked.append((score, index, font, families, subfamilies))
        score, index, font, families, subfamilies = max(ranked, key=lambda value: value[0])
        if score < 20:
            raise RuntimeError(f"no_regular_cjk_serif_face:{path}")
        output = BytesIO()
        font.save(output)
        payload = output.getvalue()
        return payload, {
            "font_container": "ttc_extracted_face",
            "font_face_index": index,
            "font_family": sorted(families)[0] if families else path.stem,
            "font_subfamily": sorted(subfamilies)[0] if subfamilies else "Regular",
        }
    finally:
        collection.close()

def _verify_embedded_font(output_pdf: Path, *, alias: str) -> dict[str, Any]:
    import fitz

    document = fitz.open(output_pdf)
    try:
        matches: list[dict[str, Any]] = []
        seen: set[int] = set()
        for page in document:
            for font in page.get_fonts(full=True):
                xref, extension, font_type, base_font, resource_name = font[:5]
                if str(resource_name) != alias or int(xref) in seen:
                    continue
                seen.add(int(xref))
                extracted = document.extract_font(int(xref))
                payload = extracted[3] if len(extracted) > 3 else b""
                matches.append(
                    {
                        "xref": int(xref),
                        "base_font": str(base_font),
                        "type": str(font_type),
                        "extension": str(extension),
                        "embedded_bytes": len(payload),
                    }
                )
        embedded = bool(matches) and all(item["embedded_bytes"] > 0 for item in matches)
        return {"embedded": embedded, "font_objects": matches}
    finally:
        document.close()

def _insert_fitted_textbox(
    page: Any,
    rect: Any,
    text: str,
    *,
    font_alias: str,
    initial_font_size: float,
    minimum_font_size: float = 5.5,
    fill_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    text_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    paint_background: bool = True,
    align: int = 0,
    lineheight: float = 1.32,
    font_metrics: Any = None,
    first_line_indent_pt: float = 0.0,
    first_line_indent_em: float = 0.0,
    baseline_step_pt: float | None = None,
) -> tuple[float, float]:
    """Commit a fitted text box after its size has passed layout."""
    if isinstance(first_line_indent_em, bool) or not isinstance(first_line_indent_em, (int, float)) or not math.isfinite(first_line_indent_em) or not 0 <= first_line_indent_em <= 4:
        raise ValueError("invalid_first_line_indent_em")
    if baseline_step_pt is not None and (font_metrics is None or isinstance(baseline_step_pt, bool) or not isinstance(baseline_step_pt, (int,float)) or not math.isfinite(baseline_step_pt) or baseline_step_pt <= 0):
        raise ValueError("invalid_baseline_step_pt")
    sizes: list[float] = []
    candidate = max(minimum_font_size, initial_font_size)
    while candidate > minimum_font_size:
        sizes.append(round(candidate, 2))
        candidate -= 0.5
    if not sizes or sizes[-1] != minimum_font_size:
        sizes.append(minimum_font_size)
    last_result = -1.0
    for font_size in sizes:
        effective_indent_pt = first_line_indent_pt + first_line_indent_em * font_size
        if font_metrics is not None and (baseline_step_pt is not None or (re.search(r"[\u3400-\u9fff]", text) and (align == 3 or effective_indent_pt))):
            import fitz
            import html
            archive = fitz.Archive()
            archive.add((bytes(font_metrics.buffer), 'cjk.ttf'))
            color = '#%02x%02x%02x' % tuple(round(max(0., min(1., c))*255) for c in text_color)
            alignment = {0:'left',1:'center',2:'right',3:'justify'}[align]
            css_lineheight = css_number(baseline_step_pt) + "pt" if baseline_step_pt is not None else str(lineheight)
            css = ("@font-face{font-family:PT;src:url(cjk.ttf)}"
                   f"body{{margin:0;padding:0;font-family:PT;font-size:{font_size}pt;color:{color}}}"
                   f"p{{margin:0;padding:0;line-height:{css_lineheight};text-align:{alignment};text-indent:{css_number(effective_indent_pt)}pt}}")
            css += '.latin{white-space:nowrap}'
            payload = ''.join('<p style="text-align:'+alignment+'">'+''.join(
                '<span class="latin">'+html.escape(t)+'</span>' if re.match(LATIN_ATOM,t) else html.escape(t)
                for t in TOKEN.findall(p))+'</p>' for p in text.split('\n'))
            # 组合上横线须复用现有完整数学字体，避免CJK字体缺字。
            if re.search(r"[A-Za-z]\u0304", text):
                archive.add((_overbar_math_font_buffer(), 'math.ttf'))
                css += '@font-face{font-family:PTMath;src:url(math.ttf)}.math{font-family:PTMath;white-space:nowrap}'
                payload = ''.join('<p style="text-align:'+alignment+'">'+''.join(
                    '<span class="math">'+html.escape(t)+'</span>' if re.match(r'[A-Za-z]',t) else html.escape(t)
                    for t in TOKEN.findall(p))+'</p>' for p in text.split('\n'))
            with fitz.open() as trial:
                trial_page = trial.new_page(width=rect.width, height=rect.height)
                spare, _, _ = insert_source_htmlbox(trial_page, trial_page.rect, payload, css=css, archive=archive,
                                                    default_alignment=alignment)
                last_result = spare
                if spare < 0:
                    continue
                if paint_background:
                    page.draw_rect(rect, color=None, fill=fill_color, overlay=True)
                page.show_pdf_page(rect, trial, 0)
            return font_size, last_result
        if re.search(r"[A-Za-z]\u0304", text) and font_metrics is not None:
            result = _insert_shaped_overbar_textbox(
                page, rect, text, font_metrics=font_metrics, font_size=font_size,
                align=align, lineheight=lineheight, text_color=text_color,
                paint_background=paint_background, fill_color=fill_color,
            )
            last_result = result
            if result >= 0:
                return font_size, result
            continue
        shape = page.new_shape()
        layout_text = (
            wrap_mixed_text(text, max(1.0, float(rect.width) - .5), lambda value: font_metrics.text_length(value, fontsize=font_size))
            if font_metrics is not None and re.search(r"[\u3400-\u9fff]", text)
            else text
        )
        if paint_background:
            shape.draw_rect(rect)
            shape.finish(color=None, fill=fill_color)
        result = shape.insert_textbox(
            rect,
            layout_text,
            fontname=font_alias,
            fontsize=font_size,
            color=text_color,
            align=align,
            lineheight=lineheight,
        )
        last_result = float(result)
        if result >= 0:
            shape.commit(overlay=True)
            return font_size, last_result
    return minimum_font_size, last_result

def _overbar_math_font_buffer() -> bytes:
    """从当前MuPDF内置字体中取得同时覆盖字母和组合上横线的同一字体。"""
    import fitz
    # 不依赖另一台机器上的系统Latin字体，也不读取外部字体目录。
    with fitz.open() as probe:
        page = probe.new_page(width=100, height=100)
        page.insert_htmlbox(page.rect, 'B̄', css='body{font-family:serif;font-size:16pt}', scale_low=1)
        for item in page.get_fonts():
            payload = probe.extract_font(item[0])[3]
            if not payload:
                continue
            font = fitz.Font(fontbuffer=payload)
            if (all(font.has_glyph(ord(c)) for c in 'ABab012̄')
                    and abs(font.text_length('̄', fontsize=12)) < .01):
                return payload
    raise RuntimeError('no_embedded_font_for_shaped_overbar')

def _insert_shaped_overbar_textbox(
    page: Any, rect: Any, text: str, *, font_metrics: Any, font_size: float,
    align: int, lineheight: float, text_color: tuple[float, float, float],
    paint_background: bool, fill_color: tuple[float, float, float],
) -> float:
    """在独立试排页整形带上横线变量；适配失败时不改动目标页。"""
    import html
    import fitz
    from .cjk_typography import TOKEN, LATIN_ATOM

    paragraphs = []
    for paragraph in text.split('\n'):
        parts = []
        for token in TOKEN.findall(paragraph):
            safe = html.escape(token)
            if re.match(LATIN_ATOM, token):
                safe = '<span class="math">' + safe + '</span>'
            parts.append(safe)
        paragraphs.append(''.join(parts))
    color = '#%02x%02x%02x' % tuple(round(max(0., min(1., c))*255) for c in text_color)
    alignment = {0: 'left', 1: 'center', 2: 'right', 3: 'justify'}.get(align, 'left')
    css = ("@font-face{font-family:PT;src:url(cjk.ttf)} "
           "@font-face{font-family:PTMath;src:url(math.ttf)} "
           f"body{{font-family:PT;font-size:{font_size}pt;line-height:{lineheight};"
           f"margin:0;padding:0;color:{color};text-align:{alignment};}} "
           ".math{font-family:PTMath;white-space:nowrap;}")
    archive = fitz.Archive()
    archive.add((bytes(font_metrics.buffer), 'cjk.ttf'))
    archive.add((_overbar_math_font_buffer(), 'math.ttf'))
    with fitz.open() as trial:
        trial_page = trial.new_page(width=rect.width, height=rect.height)
        spare, scale = trial_page.insert_htmlbox(
            trial_page.rect, '<br>'.join(paragraphs), css=css, archive=archive, scale_low=1,
        )
        if spare < 0 or scale != 1:
            return -1.
        # nowrap 的长变量不能越界；也不能用隐藏层或缺字补足覆盖。
        for span in trial_page.get_texttrace():
            if span.get('type') == 3 or span.get('opacity', 1) == 0:
                return -1.
            for code, _, _, bounds in span['chars']:
                if code == 0 or bounds[0] < -.05 or bounds[2] > rect.width + .05:
                    return -1.
        if paint_background:
            page.draw_rect(rect, color=None, fill=fill_color, overlay=True)
        page.show_pdf_page(rect, trial, 0, overlay=True)
        return float(spare)

def _insert_invisible_search_text(
    page: Any,
    rect: Any,
    text: str,
    *,
    font_alias: str,
) -> tuple[float, float]:
    """Insert extractable text without changing the protected source raster."""
    last_result = -1.0
    for font_size in (7.0, 6.0, 5.0, 4.0, 3.0, 2.0):
        shape = page.new_shape()
        result = shape.insert_textbox(
            rect,
            text,
            fontname=font_alias,
            fontsize=font_size,
            lineheight=1.0,
            render_mode=3,
        )
        last_result = float(result)
        if result >= 0:
            shape.commit(overlay=True)
            return font_size, last_result
    return 2.0, last_result

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
