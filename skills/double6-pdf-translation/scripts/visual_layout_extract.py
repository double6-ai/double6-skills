# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout extract：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def _load_fitz():
    try:
        import fitz  # type: ignore

        return fitz
    except Exception:
        try:
            import pymupdf as fitz  # type: ignore

            return fitz
        except Exception as exc:  # noqa: BLE001 - 需要把可选依赖失败写进 manifest
            raise RuntimeError(f"PyMuPDF unavailable: {exc}") from exc

def pdf_page_count(path: Path) -> int | None:
    try:
        fitz = _load_fitz()
        with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
            return len(doc)
    except Exception:
        return None

def extract_pdf_full_text(path: Path, *, max_chars: int = 200000) -> str:
    try:
        fitz = _load_fitz()
        parts: list[str] = []
        with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
            for page in doc:
                parts.append(page.get_text("text"))
        text = "\n".join(parts)
        return text[:max_chars]
    except Exception:
        return ""

def infer_default_visual_check_pages(source_pdf: Path, *, max_pages: int = 3) -> list[int] | None:
    """为报告/论文类 PDF 扩展默认视觉抽检页，避免只看前三页漏掉章节页和图表页。"""
    text = extract_pdf_full_text(source_pdf, max_chars=12000).lower()
    page_count = pdf_page_count(source_pdf)
    if "ai index report" in text or "stanford institute for human-centered artificial intelligence" in text:
        candidate_pages = [1, 2, 3, 4, 7, 8, 13, 14, 15, 17, 19, 20]
    elif "literary autobiography translation" in text or "humanities and social sciences communications" in text:
        candidate_pages = [1, 2, 3, 5, 8, 12, 13]
    else:
        return None
    bounded = [page for page in candidate_pages if page > 0 and (page_count is None or page <= page_count)]
    if bounded:
        return bounded
    return list(range(1, max_pages + 1))

def text_layer_health(pages: list[dict[str, Any]]) -> dict[str, Any]:
    text = "\n".join(str(page.get("text") or "") for page in pages)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    replacement_count = text.count("\ufffd")
    suspicious_glyph_count = len(re.findall(r"[š�□]", text))
    status = "warn" if replacement_count or suspicious_glyph_count >= 3 else "ok"
    return {
        "status": status,
        "text_chars": len(text),
        "cjk_char_count": cjk_count,
        "replacement_char_count": replacement_count,
        "suspicious_glyph_count": suspicious_glyph_count,
    }

def page_text_layer_health(page: dict[str, Any]) -> dict[str, Any]:
    from visual_layout_core import ascii_word_count, cjk_count
    from visual_layout_density import is_latextrans_placeholder_diagram_text
    text = str(page.get("text") or "")
    command_samples = VISIBLE_LATEX_COMMAND_RE.findall(text)[:8]
    diagram_markers = len(
        re.findall(
            r"\b(?:Parsing|Filtering|Translator|Validator|section\d|caption\d|environment\d|Tex Source|Generate|Reconstruct)\b",
            text,
        )
    )
    command_context = (
        "diagram_or_flowchart"
        if command_samples and (diagram_markers >= 3 or is_latextrans_placeholder_diagram_text(text))
        else "unknown"
    )
    return {
        "text_chars": len(text),
        "cjk_char_count": cjk_count(text),
        "ascii_word_count": ascii_word_count(text),
        "visible_latex_command_count": len(VISIBLE_LATEX_COMMAND_RE.findall(text)),
        "visible_latex_command_samples": command_samples,
        "visible_latex_command_context": command_context,
        "diagram_marker_count": diagram_markers,
    }


def typography_profile(page: dict[str, Any], small_fonts: dict[str, Any]) -> dict[str, Any]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict)]
    sizes = [float(span.get("size") or 0) for span in spans if float(span.get("size") or 0) > 0]
    buckets = {
        "tiny_lt_6": sum(1 for size in sizes if size < 6),
        "small_6_8": sum(1 for size in sizes if 6 <= size < 8),
        "body_8_14": sum(1 for size in sizes if 8 <= size < 14),
        "large_gte_14": sum(1 for size in sizes if size >= 14),
    }
    return {
        "span_count": len(spans),
        "min_font_size": round(min(sizes), 2) if sizes else None,
        "max_font_size": round(max(sizes), 2) if sizes else None,
        "avg_font_size": round(sum(sizes) / len(sizes), 2) if sizes else None,
        "font_size_buckets": buckets,
        "main_prose_tiny_font_ratio": small_fonts.get("small_font_char_ratio", 0),
        "font_fallback_suspected": any(str(span.get("font") or "").lower() in {"helvetica", "helv"} for span in spans),
    }

def geometry_profile(page: dict[str, Any], overlap_count: int, overlap_area: float) -> dict[str, Any]:
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    page_area = max(width * height, 1.0)
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    overflow_spans = []
    covered_area = 0.0
    for span in spans:
        box = span.get("bbox") or []
        if len(box) != 4:
            continue
        x0, y0, x1, y1 = [float(item) for item in box]
        covered_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
        if x0 < -1 or y0 < -1 or (width and x1 > width + 1) or (height and y1 > height + 1):
            overflow_spans.append({"text": str(span.get("text") or "")[:40], "bbox": box})
    return {
        "text_area_ratio": round(covered_area / page_area, 4),
        "overlap_count": overlap_count,
        "overlap_area": round(overlap_area, 2),
        "bbox_overflow_count": len(overflow_spans),
        "bbox_overflow_samples": overflow_spans[:8],
    }

def block_role_profile(page: dict[str, Any]) -> dict[str, Any]:
    counts = {"main_prose": 0, "caption": 0, "toc": 0, "footnote": 0, "table_or_chart": 0, "code_or_command": 0}
    spans = [span for span in page.get("spans", []) if isinstance(span, dict)]
    for span in spans:
        text = str(span.get("text") or "")
        size = float(span.get("size") or 0)
        lowered = text.lower()
        if VISIBLE_LATEX_COMMAND_RE.search(text) or "\\" in text:
            counts["code_or_command"] += 1
        elif re.search(r"\b(fig(?:ure)?|table)\s*\d+", lowered):
            counts["caption"] += 1
        elif size and size < 7:
            counts["footnote"] += 1
        elif re.fullmatch(r"\d+(?:\.\d+)*\s+.{2,80}", text.strip()):
            counts["toc"] += 1
        elif re.search(r"\b(chart|index|figure|table)\b", lowered):
            counts["table_or_chart"] += 1
        else:
            counts["main_prose"] += 1
    dominant = max(counts, key=counts.get) if spans else "unknown"
    return {"dominant_role": dominant, "role_counts": counts}

def extract_pdf_pages(
    path: Path,
    preview_dir: Path,
    prefix: str,
    max_pages: int = 3,
    pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    from visual_layout_core import graphic_paint_profile
    fitz = _load_fitz()
    extracted: list[dict[str, Any]] = []
    preview_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
        if pages is None:
            page_indexes = list(range(min(max_pages, len(doc))))
        else:
            page_indexes = [page - 1 for page in pages if 1 <= page <= len(doc)]
        for page_index in page_indexes:
            page = doc[page_index]
            pix = stable_get_pixmap(page, matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            preview_path = preview_dir / f"{prefix}_page_{page_index + 1:03d}.png"
            pix.save(str(preview_path))
            spans: list[dict[str, Any]] = []
            try:
                page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
                for block in page_dict.get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = str(span.get("text") or "").strip()
                            if text:
                                spans.append(
                                    {
                                        "text": text,
                                        "bbox": [float(item) for item in span.get("bbox", [])],
                                        "color": int(span.get("color") or 0),
                                        "size": float(span.get("size") or 0),
                                        "font": str(span.get("font") or ""),
                                        "flags": int(span.get("flags") or 0),
                                    }
                                )
            except Exception:
                spans = []
            extracted.append(
                {
                    "page": page_index + 1,
                    "text": page.get_text("text"),
                    "spans": spans,
                    "width": float(page.rect.width),
                    "height": float(page.rect.height),
                    "graphic_paint": graphic_paint_profile(page),
                    "preview_path": str(preview_path),
                }
            )
    return extracted


def _clip_page_text_stats(page: Any, rect: Any | None = None) -> dict[str, Any]:
    from visual_layout_core import ascii_word_count, cjk_count, normalize_lines
    kwargs = {"clip": rect} if rect is not None else {}
    text = page.get_text("text", **kwargs)
    spans: list[dict[str, Any]] = []
    try:
        page_dict = page.get_text("dict", **kwargs)
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = str(span.get("text") or "").strip()
                    if value:
                        spans.append(
                            {
                                "text": value,
                                "bbox": [float(item) for item in span.get("bbox", [])],
                                "size": float(span.get("size") or 0),
                            }
                        )
    except Exception:
        spans = []
    return {
        "text_chars": len(text.strip()),
        "cjk_count": cjk_count(text),
        "ascii_word_count": ascii_word_count(text),
        "span_count": len(spans),
        "small_font_span_count": sum(1 for span in spans if 0 < float(span.get("size") or 0) < 6),
        "text_sample": normalize_lines(text)[:6],
    }


def _clip_pixel_stats(page: Any, rect: Any | None = None) -> dict[str, Any]:
    fitz = _load_fitz()
    pix = stable_get_pixmap(page, matrix=fitz.Matrix(0.5, 0.5), alpha=False, clip=rect)
    samples = pix.samples
    pixels = max(pix.width * pix.height, 1)
    nonwhite = 0
    red = green = blue = 0
    for offset in range(0, len(samples), pix.n):
        r = samples[offset]
        g = samples[offset + 1] if pix.n > 1 else r
        b = samples[offset + 2] if pix.n > 2 else r
        red += r
        green += g
        blue += b
        if min(r, g, b) < 245:
            nonwhite += 1
    return {
        "nonwhite_ratio": round(nonwhite / pixels, 4),
        "mean_rgb": [round(red / pixels, 1), round(green / pixels, 1), round(blue / pixels, 1)],
    }

def _page_region_metrics(doc: Any, page_index: int, region: str) -> dict[str, Any]:
    page = doc[page_index]
    rect = page.rect
    if region == "left":
        clip = rect.__class__(rect.x0, rect.y0, rect.x0 + rect.width / 2, rect.y1)
    elif region == "right":
        clip = rect.__class__(rect.x0 + rect.width / 2, rect.y0, rect.x1, rect.y1)
    else:
        clip = None
    metrics = {
        "region": region,
        "page": page_index + 1,
        "width": float(rect.width if clip is None else clip.width),
        "height": float(rect.height if clip is None else clip.height),
    }
    metrics.update(_clip_page_text_stats(page, clip))
    metrics.update(_clip_pixel_stats(page, clip))
    return metrics

def build_full_document_coverage_report(source_pdf: Path, translated_pdf: Path) -> dict[str, Any]:
    from visual_layout_core import normalize_finding
    fitz = _load_fitz()
    page_metrics: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    with fitz.open(str(source_pdf)) as source_doc, fitz.open(str(translated_pdf)) as translated_doc:  # type: ignore[attr-defined]
        for page_index in range(min(len(source_doc), len(translated_doc))):
            source_stats = _page_region_metrics(source_doc, page_index, "full")
            translated_stats = _page_region_metrics(translated_doc, page_index, "full")
            item = {
                "page": page_index + 1,
                "source_text_chars": source_stats["text_chars"],
                "source_nonwhite_ratio": source_stats["nonwhite_ratio"],
                "translated_text_chars": translated_stats["text_chars"],
                "translated_cjk_count": translated_stats["cjk_count"],
                "translated_nonwhite_ratio": translated_stats["nonwhite_ratio"],
            }
            page_metrics.append(item)
            source_nonempty = source_stats["text_chars"] >= 30 or source_stats["nonwhite_ratio"] >= 0.025
            translated_low = (
                translated_stats["text_chars"] < max(20, int(source_stats["text_chars"] * 0.08))
                and translated_stats["cjk_count"] < 8
                and translated_stats["nonwhite_ratio"] < max(0.012, source_stats["nonwhite_ratio"] * 0.25)
            )
            if source_nonempty and translated_low:
                findings.append(
                    normalize_finding(
                        {
                            "severity": "blocking",
                            "category": "rendering",
                            "rule": "blank_or_low_content_page",
                            "page": page_index + 1,
                            "message": "源页非空，但译文页文本/中文/可见像素覆盖都过低，疑似空白页或内容丢失。",
                            "evidence": json.dumps(item, ensure_ascii=False),
                        }
                    )
                )
    return {
        "status": "warn" if findings else "ok",
        "pages_checked": len(page_metrics),
        "page_metrics": page_metrics,
        "findings": findings,
    }


def extract_pdf_text_pages(path: Path) -> list[dict[str, Any]]:
    fitz = _load_fitz()
    pages: list[dict[str, Any]] = []
    with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
        for page_index, page in enumerate(doc):
            pages.append({"page": page_index + 1, "text": page.get_text("text")})
    return pages

def reference_tail_from_explicit_heading(lines: list[str]) -> str:
    """只从独立 References/参考文献标题之后截取，避免把正文中的词触发成参考文献误报。"""
    for index, line in enumerate(lines):
        normalized = line.strip().strip(":：").lower()
        if normalized in {"references", "参考文献"}:
            return "\n".join(lines[index + 1 :])
    return ""

def reference_body_text_for_translation_check(ref_tail: str) -> str:
    from visual_layout_core import normalize_lines
    body_lines: list[str] = []
    for line in normalize_lines(ref_tail):
        stripped = line.strip().strip(":：")
        lowered = stripped.lower()
        if lowered in REFERENCE_BODY_IGNORE_LINES or stripped in REFERENCE_BODY_IGNORE_LINES:
            continue
        if any(lowered.startswith(prefix) for prefix in ["published online", "received", "accepted"]):
            continue
        if stripped.startswith(("在线发表", "收稿日期", "录用日期")):
            continue
        body_lines.append(line)
    return "\n".join(body_lines)


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
