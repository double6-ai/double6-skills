#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by visual_layout.py for PDF extraction, text-layer health, and visual page analysis."

import json
import re
from pathlib import Path
from typing import Any


from visual_layout_core import *  # noqa: F401,F403
from visual_layout_findings import *  # noqa: F401,F403

def analyze_visual_pages(
    source_pages: list[dict[str, Any]],
    translated_pages: list[dict[str, Any]],
    *,
    key_texts: list[str] | None = None,
    full_translated_text: str | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    keys = key_texts or extract_key_texts(source_pages)
    translated_all_text = "\n".join(str(page.get("text") or "") for page in translated_pages)
    full_text = full_translated_text if full_translated_text is not None else translated_all_text
    for key in keys:
        if re.fullmatch(r"20\d{2}", key) and key not in full_text:
            findings.append(
                {
                    "severity": "warn",
                    "category": "rendering",
                    "rule": "key_text_missing",
                    "key_text": key,
                    "scope": "checked_pages_only" if full_translated_text is None else "full_pdf_text_layer",
                    "message": (
                        f"关键文字 {key} 未在已检查页的译文 PDF 文本层中出现，可能是抽样页未覆盖。"
                        if full_translated_text is None
                        else f"关键文字 {key} 未在全文译文 PDF 可抽取文本中出现，可能被遮挡或丢失。"
                    ),
                }
            )
    page_metrics: list[dict[str, Any]] = []
    for index, translated in enumerate(translated_pages):
        source = source_pages[index] if index < len(source_pages) else {}
        page_number = translated.get("page") or source.get("page") or index + 1
        source_nonblack = nonblack_color_ratio(source)
        translated_black = dominant_color_ratio(translated, 0)
        if index < 3 and source_nonblack >= 0.25 and translated_black >= 0.8:
            findings.append(
                {
                    "severity": "warn",
                    "category": "rendering",
                    "rule": "color_palette_shift_to_black",
                    "page": page_number,
                    "message": "源页存在较多非黑色文字，而译文页文字几乎全部变黑，存在低对比或主题色丢失风险。",
                }
            )
        overlaps = count_overlapping_spans(translated)
        overlap_area = total_overlapping_area(translated)
        ai_roster_context = is_ai_roster_page(translated)
        latextrans_visual_passthrough_context = is_latextrans_visual_passthrough_page(translated)
        if overlaps >= 3 and not ai_roster_context and not latextrans_visual_passthrough_context:
            findings.append(
                {
                    "severity": "blocking" if overlaps >= 8 else "warn",
                    "category": "structure",
                    "rule": "text_overlap",
                    "page": page_number,
                    "overlap_count": overlaps,
                    "overlap_area": overlap_area,
                    "overlap_pairs": overlap_pair_samples(translated),
                    "message": "译文页存在多个文本 bbox 重叠，可能出现遮挡或目录结构错乱。",
                }
            )
            if min((float(span.get("size") or 0) for span in translated.get("spans", []) if isinstance(span, dict) and span.get("size")), default=0) >= 5.8:
                findings.append(
                    {
                        "severity": "blocking" if overlaps >= 8 else "warn",
                        "category": "structure",
                        "rule": "role_font_floor_caused_overlap",
                        "page": page_number,
                        "overlap_count": overlaps,
                        "overlap_area": overlap_area,
                        "overlap_pairs": overlap_pair_samples(translated),
                        "message": "角色级字号下限放大后仍产生 bbox 重叠，应转入页级/图表重渲染而不是写入重叠文本。",
                    }
                )
        small_fonts = small_font_stats(translated)
        density = text_density_stats(translated)
        compact_labels = compact_label_stats(translated)
        typography = typography_profile(translated, small_fonts)
        geometry = geometry_profile(translated, overlaps, overlap_area)
        block_role = block_role_profile(translated)
        page_health = page_text_layer_health(translated)
        heading_tiny_samples = tiny_heading_spans(translated)
        page_metrics.append(
            {
                "page": page_number,
                "small_fonts": small_fonts,
                "text_density": density,
                "compact_labels": compact_labels,
                "typography": typography,
                "geometry": geometry,
                "block_role": block_role,
                "text_layer_health": page_health,
                "heading_tiny_font_samples": heading_tiny_samples,
            }
        )
        findings.extend(source_translated_heading_style_findings(source, translated, page_number))
        findings.extend(source_translated_protected_name_findings(source, translated, page_number))
        findings.extend(source_translated_chart_title_findings(source, translated, page_number))
        findings.extend(chart_axis_label_malformed_findings(source, translated, page_number))
        findings.extend(source_translated_publisher_badge_findings(source, translated, page_number))
        findings.extend(source_translated_table_caption_findings(source, translated, page_number))
        findings.extend(abstract_typography_findings(source, translated, page_number))
        latextrans_diagram_context = is_latextrans_visual_passthrough_page(translated)
        if heading_tiny_samples and latextrans_diagram_context:
            findings.append(
                {
                    "severity": "info",
                    "category": "readability",
                    "rule": "diagram_small_font_residual",
                    "page": page_number,
                    "message": "图示/流程图内部存在小字号 heading-like token；按图内诊断记录，不作为正文标题重排 blocker。",
                    "evidence": json.dumps({"samples": heading_tiny_samples[:8], "classification": "latextrans_diagram"}, ensure_ascii=False),
                }
            )
        elif heading_tiny_samples:
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "heading_tiny_font",
                    "page": page_number,
                    "message": "章节标题被压缩为极小字号，需按 heading role 重排而不是硬塞原 bbox。",
                    "evidence": json.dumps({"samples": heading_tiny_samples[:8]}, ensure_ascii=False),
                }
            )
        if page_health["visible_latex_command_count"]:
            is_diagram_context = page_health.get("visible_latex_command_context") == "diagram_or_flowchart"
            findings.append(
                {
                    "severity": "info" if is_diagram_context else "warn",
                    "category": "rendering",
                    "rule": "visible_latex_command",
                    "page": page_number,
                    "message": (
                        "译文 PDF 文本层出现 LaTeX 命令，但上下文像论文图示/流程图，先按诊断信息记录。"
                        if is_diagram_context
                        else "译文 PDF 文本层出现可见 LaTeX 命令，可能是结构命令被当作正文渲染。"
                    ),
                    "evidence": json.dumps(page_health, ensure_ascii=False),
                }
            )
        if geometry["bbox_overflow_count"]:
            findings.append(
                {
                    "severity": "warn",
                    "category": "structure",
                    "rule": "bbox_overflow",
                    "page": page_number,
                    "message": "译文页存在文本 bbox 越界，可能出现裁切或不可见文本。",
                    "evidence": json.dumps(geometry, ensure_ascii=False),
                }
            )
        is_diagram_context = page_health.get("visible_latex_command_context") == "diagram_or_flowchart"
        is_latextrans_embedded_case_context = is_latextrans_embedded_case_figure_text(str(translated.get("text") or ""))
        if (
            typography["main_prose_tiny_font_ratio"] >= 0.18
            and block_role["dominant_role"] == "main_prose"
            and not is_diagram_context
            and not is_latextrans_embedded_case_context
            and not is_dense_chart_or_index_page(translated, small_fonts, compact_labels)
        ):
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "main_prose_tiny_font",
                    "page": page_number,
                    "message": "主文疑似通过极小字号塞回原 bbox，影响可读性。",
                    "evidence": json.dumps(typography, ensure_ascii=False),
                }
            )
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "font_size_regression",
                    "page": page_number,
                    "message": "主文或标题字号相对原版式明显退化，疑似通过缩小字号硬塞回原 bbox。",
                    "evidence": json.dumps(typography, ensure_ascii=False),
                }
            )
        if small_fonts["small_font_span_count"] >= 12 and small_fonts["small_font_char_ratio"] >= 0.18:
            if is_diagram_context or is_latextrans_embedded_case_context:
                findings.append(
                    {
                        "severity": "info",
                        "category": "readability",
                        "rule": "diagram_small_font_residual" if is_diagram_context else "embedded_case_figure_small_font_residual",
                        "page": page_number,
                        "small_font_span_count": small_fonts["small_font_span_count"],
                        "small_font_char_ratio": small_fonts["small_font_char_ratio"],
                        "message": (
                            "流程图/图示上下文中存在小字号诊断 token；按图内残留记录，不作为主文 reflow blocker。"
                            if is_diagram_context
                            else "嵌入案例截图中存在小字号源文档内容；按图内证据记录，不作为主文 reflow blocker。"
                        ),
                        "evidence": json.dumps(
                            {
                                "small_fonts": small_fonts,
                                "compact_labels": compact_labels,
                                "classification": "diagram_or_flowchart" if is_diagram_context else "latextrans_embedded_case_figure",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            elif is_dense_chart_or_index_page(translated, small_fonts, compact_labels):
                findings.append(
                    {
                        "severity": "cosmetic",
                        "category": "readability",
                        "rule": "dense_chart_small_font_residual",
                        "page": page_number,
                        "small_font_span_count": small_fonts["small_font_span_count"],
                        "small_font_char_ratio": small_fonts["small_font_char_ratio"],
                        "message": "图表/索引密集页存在小字号残留；已按 dense chart residual 记录，不作为主文不可读 blocker。",
                        "evidence": json.dumps(
                            {
                                "small_fonts": small_fonts,
                                "compact_labels": compact_labels,
                                "classification": "chart_dense_page",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            else:
                findings.append(
                    {
                        "severity": "warn",
                        "category": "readability",
                        "rule": "small_font_overuse",
                        "page": page_number,
                        "small_font_span_count": small_fonts["small_font_span_count"],
                        "small_font_char_ratio": small_fonts["small_font_char_ratio"],
                        "message": "译文页小字号文本比例偏高，可能是通过过度缩放硬塞入原 bbox。",
                        "evidence": json.dumps(small_fonts, ensure_ascii=False),
                    }
                )
                findings.append(
                    {
                        "severity": "warn",
                        "category": "readability",
                        "rule": "font_size_regression",
                        "page": page_number,
                        "small_font_span_count": small_fonts["small_font_span_count"],
                        "small_font_char_ratio": small_fonts["small_font_char_ratio"],
                        "message": "译文页字号退化，疑似通过过度缩放硬塞入原 bbox。",
                        "evidence": json.dumps(small_fonts, ensure_ascii=False),
                    }
                )
        if compact_labels["compact_label_count"] >= 8:
            if is_diagram_context or is_latextrans_embedded_case_context:
                findings.append(
                    {
                        "severity": "info",
                        "category": "readability",
                        "rule": "diagram_compact_label_residual" if is_diagram_context else "embedded_case_figure_compact_label_residual",
                        "page": page_number,
                        "compact_label_count": compact_labels["compact_label_count"],
                        "compact_label_samples": compact_labels["compact_label_samples"],
                        "message": (
                            "流程图/图示上下文中存在紧凑英文标签；按图内标签保留记录，不作为主文漏译 blocker。"
                            if is_diagram_context
                            else "嵌入案例截图中存在紧凑英文/日文标签；按图内证据保留，不作为主文漏译 blocker。"
                        ),
                        "evidence": json.dumps(
                            {
                                "compact_labels": compact_labels,
                                "classification": "diagram_or_flowchart" if is_diagram_context else "latextrans_embedded_case_figure",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            elif ai_roster_context:
                findings.append(
                    {
                        "severity": "info",
                        "category": "readability",
                        "rule": "ai_roster_compact_name_passthrough",
                        "page": page_number,
                        "compact_label_count": compact_labels["compact_label_count"],
                        "compact_label_samples": compact_labels["compact_label_samples"],
                        "message": "AI Index 人员名单页保留英文姓名和少量机构英文名；按 roster 策略记录，不作为正文漏译或图内标签 blocker。",
                        "evidence": json.dumps(
                            {
                                "compact_labels": compact_labels,
                                "classification": "ai_roster_names_passthrough",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
            else:
                findings.append(
                    {
                        "severity": "warn",
                        "category": "readability",
                        "rule": "compact_label_residual",
                        "page": page_number,
                        "compact_label_count": compact_labels["compact_label_count"],
                        "compact_label_samples": compact_labels["compact_label_samples"],
                        "message": "译文页存在较多紧凑英文标签，需确认是保留策略还是图内文字漏处理。",
                        "evidence": json.dumps(compact_labels, ensure_ascii=False),
                    }
                )
        for warning in directory_order_findings(source, translated):
            findings.append(
                {
                    "severity": "warn",
                    "category": "structure",
                    "rule": warning["rule"],
                    "page": page_number,
                    "source_numeric_line_count": warning["source_numeric_line_count"],
                    "translated_numeric_line_count": warning["translated_numeric_line_count"],
                    "toc_line_preservation_ratio": warning["toc_line_preservation_ratio"],
                    "source_numeric_line_samples": warning["source_numeric_line_samples"],
                    "translated_numeric_line_samples": warning["translated_numeric_line_samples"],
                    "message": "目录行数量或顺序与源页不一致。",
                    "evidence": json.dumps(warning, ensure_ascii=False),
                }
            )
    if len(source_pages) != len(translated_pages):
        findings.append(
            {
                "severity": "blocking",
                "category": "rendering",
                "rule": "page_count_drift",
                "page": "document",
                "source_page_count": len(source_pages),
                "translated_page_count": len(translated_pages),
                "message": "源/译 PDF 可检查页数不一致，存在页数漂移或译文页缺失风险。",
            }
        )
    findings = [normalize_finding(item) for item in findings]
    report_status = "warn" if any(item.get("severity") in {"warn", "blocking"} for item in findings) else "ok"
    return {
        "version": 1,
        "status": report_status,
        "page_count_checked": min(len(source_pages), len(translated_pages)),
        "key_texts": keys,
        "page_metrics": page_metrics,
        "findings": findings,
    }


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


VISIBLE_LATEX_COMMAND_RE = re.compile(r"\\(?:section|subsection|subsubsection|begin|end|cite|ref|url|texttt|emph|caption)\b")


def page_text_layer_health(page: dict[str, Any]) -> dict[str, Any]:
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
            pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            preview_path = preview_dir / f"{prefix}_page_{page_index + 1:03d}.png"
            pix.save(str(preview_path))
            spans: list[dict[str, Any]] = []
            try:
                page_dict = page.get_text("dict")
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
                    "preview_path": str(preview_path),
                }
            )
    return extracted


def _clip_page_text_stats(page: Any, rect: Any | None = None) -> dict[str, Any]:
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
    pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False, clip=rect)
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
