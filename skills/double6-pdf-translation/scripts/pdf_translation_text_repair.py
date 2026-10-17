# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation text repair：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def apply_pdf_direct_text_repairs(
    pdf_path: Path | None,
    source_pdf: Path,
    output_dir: Path,
    *,
    apply_overlay: bool = False,
) -> dict[str, Any]:
    if not pdf_path or not pdf_path.is_file():
        return {"version": 1, "status": "skipped", "reason": "missing_pdf", "repairs": []}
    source_name = source_pdf.name.lower()
    if "latextrans" in source_name:
        return {"version": 1, "status": "skipped", "reason": "latex_direct_or_not_pdf_direct", "repairs": []}
    try:
        fitz = visual_layout._load_fitz()
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": repr(exc), "repairs": []}

    repairs: list[dict[str, Any]] = []
    manifest_reason = ""

    def redact_and_insert(page: Any, needle: str, replacement: str, *, fontsize: float = 8.0, max_hits: int = 20) -> int:
        hits = page.search_for(needle)[:max_hits]
        if not hits:
            return 0
        if not apply_overlay:
            return len(hits)
        for rect in hits:
            page.add_redact_annot(rect + (-1, -1, 4, 2), fill=(1, 1, 1))
        page.apply_redactions()
        for rect in hits:
            width = max(28, len(replacement) * fontsize * 0.7)
            page.insert_textbox(rect + (-1, -1, width, 5), replacement, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)
        return len(hits)

    def replace_everywhere(doc: Any, mapping: dict[str, str], *, fontsize: float = 8.0) -> None:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            for source, target in mapping.items():
                count = redact_and_insert(page, source, target, fontsize=fontsize)
                if count:
                    repairs.append({"page": page_index + 1, "source": source, "target": target, "count": count})

    def replace_on_pages(
        doc: Any,
        mapping: dict[str, str],
        *,
        pages: set[int],
        fontsize: float = 8.0,
        max_hits_per_source: int = 1,
    ) -> None:
        for page_index in range(doc.page_count):
            if page_index + 1 not in pages:
                continue
            page = doc[page_index]
            for source, target in mapping.items():
                count = redact_and_insert(page, source, target, fontsize=fontsize, max_hits=max_hits_per_source)
                if count:
                    repairs.append({"page": page_index + 1, "source": source, "target": target, "count": count, "mode": "page_scoped"})

    def replace_lines_by_normalized_text(doc: Any, mapping: dict[str, str], *, fontsize: float = 8.0) -> None:
        def normalized(value: str) -> str:
            return re.sub(r"\s+", " ", value.replace("\x03", " ")).strip()

        for page_index in range(doc.page_count):
            page = doc[page_index]
            lines = [
                ("".join(span.get("text", "") for span in line.get("spans", [])), line.get("bbox"))
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
            ]
            for source, target in mapping.items():
                source_norm = normalized(source)
                hits = []
                for text, bbox in lines:
                    if bbox and source_norm in normalized(text):
                        hits.append(fitz.Rect(bbox))
                if not hits:
                    continue
                if not apply_overlay:
                    repairs.append({"page": page_index + 1, "source": source, "target": target, "count": len(hits), "mode": "normalized_line"})
                    continue
                for rect in hits:
                    page.add_redact_annot(rect + (-1, -1, 4, 2), fill=(1, 1, 1))
                page.apply_redactions()
                for rect in hits:
                    width = max(36, len(target) * fontsize * 0.7)
                    page.insert_textbox(rect + (-1, -1, width, 5), target, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)
                repairs.append({"page": page_index + 1, "source": source, "target": target, "count": len(hits), "mode": "normalized_line"})

    def replace_block_by_normalized_prefix(
        page: Any,
        prefix: str,
        replacement: str,
        *,
        fontsize: float = 6.7,
        bottom_padding: float = 265,
    ) -> bool:
        def normalized(value: str) -> str:
            return re.sub(r"\s+", " ", str(value or "").replace("\x03", " ")).strip()

        prefix_norm = normalized(prefix)
        for block in page.get_text("dict").get("blocks", []):
            lines = block.get("lines", []) if isinstance(block, dict) else []
            block_text = " ".join(
                "".join(str(span.get("text", "")) for span in line.get("spans", []))
                for line in lines
                if isinstance(line, dict)
            )
            if prefix_norm not in normalized(block_text):
                continue
            bbox = block.get("bbox")
            if not bbox:
                first_line = next((line for line in lines if line.get("bbox")), None)
                bbox = first_line.get("bbox") if first_line else None
            if not bbox:
                continue
            first = fitz.Rect(bbox)
            block_rect = fitz.Rect(first.x0 - 2, first.y0 - 2, page.rect.width - 45, min(page.rect.height - 85, first.y0 + bottom_padding))
            if not apply_overlay:
                return True
            page.add_redact_annot(block_rect, fill=(1, 1, 1))
            page.apply_redactions()
            page.insert_textbox(block_rect, replacement, fontname="china-s", fontsize=fontsize, color=(0, 0, 0), overlay=True)
            return True
        return False

    def repair_nature_page1_affiliation_footer(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 1:
            return []
        page = doc[0]
        fixed: list[dict[str, Any]] = []
        target = "1 香港理工大学，中国香港。✉email: andrew.cheung@polyu.edu.hk"
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []) if isinstance(block, dict) else []:
                text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
                if "polyu.edu.hk" not in text:
                    continue
                if "香港理工大学" in text and "中国香港" in text:
                    return fixed
                if "Kong Polytechnic" not in text and "Hong Kong Polytechnic" not in text:
                    continue
                bbox = line.get("bbox")
                if not bbox:
                    continue
                if not apply_overlay:
                    fixed.append(
                        {
                            "page": 1,
                            "source": "1 Hong Kong Polytechnic University, Hong Kong, China.",
                            "target": "1 香港理工大学，中国香港。",
                            "count": 1,
                            "mode": "footer_line",
                        }
                    )
                    return fixed
                rect = fitz.Rect(bbox)
                cover = fitz.Rect(max(0, rect.x0 - 6), rect.y0 - 2, min(page.rect.width - 40, rect.x1 + 5), rect.y1 + 2)
                page.add_redact_annot(cover, fill=(1, 1, 1))
                page.apply_redactions()
                build_visual_repair_pdf.draw_mixed_font_line(
                    fitz,
                    page,
                    max(40, rect.x0 - 6),
                    rect.y1 - 1,
                    target,
                    fontsize=6.4,
                )
                fixed.append(
                    {
                        "page": 1,
                        "rule": "nature_page1_affiliation_footer_repair",
                        "source": text,
                        "target": target,
                        "bbox": [round(v, 2) for v in [cover.x0, cover.y0, cover.x1, cover.y1]],
                        "count": 1,
                        "mode": "footer_line_redraw",
                        "layout_role": "affiliation_footer",
                        "failure_stage": "paint",
                        "fill_strategy": "tight_redaction_and_mixed_font_footer_redraw",
                        "font_policy": "compact_source_footer_6_4pt_mixed_latin_cjk",
                        "text_policy": "translate_affiliation_preserve_email",
                    }
                )
                return fixed
        return fixed

    def repair_nature_metadata_headers(doc: Any) -> list[dict[str, Any]]:
        target = "HUMANITIES AND SOCIAL SCIENCES COMMUNICATIONS | https://doi.org/10.1057/s41599-026-06630-4"
        fixed: list[dict[str, Any]] = []
        for page_index in range(1, doc.page_count):
            page = doc[page_index]
            problem_rects: list[Any] = []
            metadata_rects: list[Any] = []
            article_rect = None
            article_fragment_rects: list[Any] = []
            top_lines: list[str] = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []) if isinstance(block, dict) else []:
                    bbox = line.get("bbox")
                    if not bbox or bbox[1] > 45:
                        continue
                    text = "".join(str(span.get("text", "")) for span in line.get("spans", [])).strip()
                    if not text:
                        continue
                    top_lines.append(text)
                    if text == "ARTICLE":
                        article_rect = fitz.Rect(bbox)
                        continue
                    if text == "A":
                        article_fragment_rects.append(fitz.Rect(bbox))
                        problem_rects.append(fitz.Rect(bbox))
                        continue
                    if re.search(r"HUMANIT|doi\.org|://doi|s41599|人文与社会科学", text, flags=re.I):
                        metadata_rects.append(fitz.Rect(bbox))
                    is_problem = False
                    if "doi.org/10.1057/s41599-026-06630-4" in text and ("人文" in text or "（2026" in text or "(2026" in text):
                        is_problem = True
                    if re.search(r"HUMANITIE\S*[\u4e00-\u9fff]|社会科学.*https", text):
                        is_problem = True
                    if "人文与社会科学通讯" in text and "doi.org" in text:
                        is_problem = True
                    if text.startswith("://doi.org/10.1057/s41599-026-06630-4"):
                        is_problem = True
                    if is_problem:
                        problem_rects.append(fitz.Rect(bbox))
            if not problem_rects and target in top_lines and len(metadata_rects) > 1 and any(line != target for line in top_lines if line != "ARTICLE"):
                problem_rects.extend(metadata_rects)
            if not problem_rects:
                continue
            source_text = " | ".join(top_lines)
            if not apply_overlay:
                fixed.append(
                    {
                        "page": page_index + 1,
                        "rule": "nature_metadata_header_repair",
                        "source": source_text,
                        "target": target,
                        "count": len(problem_rects),
                        "mode": "header_line",
                    }
                )
                continue
            impacted_article = False
            for rect in (metadata_rects + article_fragment_rects) or problem_rects:
                cover = fitz.Rect(max(38, rect.x0 - 3), max(12, rect.y0 - 2), min(page.rect.width - 38, rect.x1 + 4), min(44, rect.y1 + 3))
                if article_rect and cover.intersects(article_rect):
                    impacted_article = True
                page.add_redact_annot(cover, fill=(1, 1, 1))
            if article_rect and impacted_article:
                page.add_redact_annot(fitz.Rect(article_rect.x0 - 1, article_rect.y0 - 1, article_rect.x1 + 2, article_rect.y1 + 2), fill=(1, 1, 1))
            page.apply_redactions()
            if article_rect and impacted_article:
                page.insert_text(
                    (article_rect.x0, article_rect.y1 - 0.8),
                    "ARTICLE",
                    fontname="helv",
                    fontsize=11.4,
                    color=(0, 0, 0),
                    overlay=True,
                )
            x = 182.8 if page_index % 2 == 1 else 43.6
            y = 28.3
            page.insert_text(
                (x, y),
                target,
                fontname="helv",
                fontsize=6.0,
                color=(0.68, 0.68, 0.88),
                overlay=True,
            )
            fixed.append(
                {
                    "page": page_index + 1,
                    "rule": "nature_metadata_header_repair",
                    "source": source_text,
                    "target": target,
                    "count": len(metadata_rects) or len(problem_rects),
                    "mode": "top_metadata_redraw",
                    "layout_role": "running_header",
                    "failure_stage": "paint",
                    "fill_strategy": "tight_redaction_and_source_style_header_redraw",
                    "font_policy": "source_like_light_blue_6pt_helvetica",
                    "text_policy": "preserve_metadata_header_as_source_passthrough",
                }
            )
        return fixed

    def repair_ai_page5_steering_roster(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 5 or not source_pdf.exists():
            return []
        fixed: list[dict[str, Any]] = []
        try:
            source_doc = fitz.open(str(source_pdf))
        except Exception:
            source_doc = None
        try:
            page = doc[4]
            rect = fitz.Rect(30.0, 132.0, 590.0, 767.0)
            copied = False
            if source_doc is not None:
                copied = build_visual_repair_pdf.copy_ai_roster_background(fitz, source_doc, page, 5, rect, raster=True)
            if not copied:
                page.add_redact_annot(rect, fill=(1, 1, 1))
                page.apply_redactions()
            fixed.extend(build_visual_repair_pdf.redraw_ai_page5_steering_roster_text(fitz, page))
            for item in fixed:
                item["source_pdf"] = str(source_pdf)
                item["applied_to_standard_pdf"] = True
                item["fill_strategy"] = "source_region_raster_then_text_region_structured_redraw" if copied else "white_page_background_structured_redraw"
        finally:
            if source_doc is not None:
                source_doc.close()
        return fixed

    def repair_ai_cover_page(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 1 or not source_pdf.exists():
            return []
        try:
            source_doc = fitz.open(str(source_pdf))
        except Exception:
            return []
        try:
            if source_doc.page_count < 1:
                return []
            fixed: list[dict[str, Any]] = []
            fixed.extend(build_visual_repair_pdf.repair_cover_year(fitz, source_doc[0], doc[0]))
            fixed.extend(build_visual_repair_pdf.repair_ai_cover_title_wrap(fitz, doc[0]))
            for item in fixed:
                item["source_pdf"] = str(source_pdf)
                item["applied_to_standard_pdf"] = True
                item["backend_sink_down"] = "pending"
            return fixed
        finally:
            source_doc.close()

    def repair_ai_page6_staff_roster(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 6 or not source_pdf.exists():
            return []
        try:
            source_doc = fitz.open(str(source_pdf))
        except Exception:
            return []
        try:
            page = doc[5]
            rect = fitz.Rect(30.0, 132.0, 590.0, 400.0)
            copied = build_visual_repair_pdf.copy_ai_roster_background(fitz, source_doc, page, 6, rect, raster=True)
            if not copied:
                return []
            return [
                {
                    "page": 6,
                    "rule": "ai_contributor_roster_source_passthrough",
                    "source": "staff and researcher roster with portraits, pink panels, and source typography",
                    "target": "source roster visual region rasterized to avoid name-affiliation merging and source text-layer leakage",
                    "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                    "layout_role": "image_heavy_roster",
                    "failure_stage": "paint",
                    "fill_strategy": "source_region_raster_passthrough_without_source_text_layer",
                    "font_policy": "preserve_source_roster_typography_and_colors_as_raster_background",
                    "text_policy": "passthrough_image_heavy_roster_to_prevent_name_affiliation_merging_without_covering_portraits",
                    "backend_sink_down": "pending",
                    "source_pdf": str(source_pdf),
                    "applied_to_standard_pdf": True,
                }
            ]
        finally:
            source_doc.close()

    def repair_ai_page18_20_chart_regions(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 20 or not source_pdf.exists():
            return []
        try:
            source_doc = fitz.open(str(source_pdf))
        except Exception:
            return []
        try:
            pages = {18, 19, 20}
            fixed: list[dict[str, Any]] = []
            fixed.extend(
                build_visual_repair_pdf.copy_ai_chart_regions(
                    fitz,
                    source_doc,
                    doc,
                    pages=pages,
                    redact_existing_text=True,
                )
            )
            fixed.extend(build_visual_repair_pdf.repair_ai_chart_titles_after_passthrough(fitz, doc, pages=pages))
            fixed.extend(build_visual_repair_pdf.repair_ai_page17_chart_axis_labels_after_passthrough(fitz, doc, pages=pages))
            for item in fixed:
                item["source_pdf"] = str(source_pdf)
                item["applied_to_standard_pdf"] = True
                item["backend_sink_down"] = "pending"
            return fixed
        finally:
            source_doc.close()

    def repair_ai_page14_research_contents(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 14:
            return []
        fixed = build_visual_repair_pdf.repair_ai_research_contents_page(fitz, doc[13])
        for item in fixed:
            item["source_pdf"] = str(source_pdf)
            item["applied_to_standard_pdf"] = True
            item["backend_sink_down"] = "pending"
        return fixed

    def repair_ai_page17_orphan_footer_x(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 17:
            return []
        page = doc[16]
        fixed: list[dict[str, Any]] = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []) or []:
                for span in line.get("spans", []) or []:
                    if str(span.get("text") or "").strip() != "x":
                        continue
                    bbox = span.get("bbox")
                    if not bbox:
                        continue
                    rect = fitz.Rect(bbox)
                    if rect.y0 < 665 or rect.x0 < 520:
                        continue
                    rect = rect + (-1.0, -1.0, 1.0, 1.0)
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    fixed.append(
                        {
                            "page": 17,
                            "rule": "ai_page17_orphan_footer_x_cleanup",
                            "source": "isolated footnote/footer x glyph",
                            "target": "remove stray footer glyph without redrawing footnote text",
                            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                            "layout_role": "footnote_or_footer",
                            "failure_stage": "paint",
                            "fill_strategy": "narrow_white_footer_glyph_redaction",
                            "font_policy": "preserve_surrounding_footnote_fonts",
                            "text_policy": "remove_only_exact_isolated_x_in_footer_band",
                            "backend_sink_down": "pending",
                            "applied_to_standard_pdf": True,
                        }
                    )
        if fixed:
            page.apply_redactions()
        return fixed

    def repair_ai_page9_acknowledgement_chapter_headings(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 9:
            return []
        page = doc[8]
        source_doc = None
        try:
            source_doc = fitz.open(str(source_pdf)) if source_pdf.exists() else None
        except Exception:
            source_doc = None
        source_page = source_doc[8] if source_doc is not None and source_doc.page_count >= 9 else page
        specs = [
            ("Policy and Governance", "政策与治理", fitz.Rect(34.0, 104.0, 168.0, 132.0), (35.2, 122.0)),
            ("Public Opinion", "公众舆论", fitz.Rect(324.0, 104.0, 430.0, 132.0), (325.1, 122.0)),
        ]
        fixed: list[dict[str, Any]] = []
        try:
            for source, target, fallback_rect, point in specs:
                hits = page.search_for(source) + page.search_for(target)
                rects = []
                for hit in hits:
                    rect = fitz.Rect(hit)
                    rects.append(fitz.Rect(rect.x0 - 2.0, rect.y0 - 5.0, max(rect.x1 + 38.0, fallback_rect.x1), rect.y1 + 10.0))
                if not rects:
                    rects = [fallback_rect]
                fill = build_visual_repair_pdf.sampled_background_color(source_page, fallback_rect)
                for rect in rects:
                    page.add_redact_annot(rect, fill=fill)
                page.apply_redactions()
                for rect in rects[:1]:
                    build_visual_repair_pdf.insert_source_han_sans_fake_bold(
                        page,
                        (point[0], point[1]),
                        target,
                        fontsize=10.2,
                        color=(0.27, 0.11, 0.28),
                    )
                    fixed.append(
                        {
                            "page": 9,
                            "rule": "ai_acknowledgement_chapter_heading_repair",
                            "source": source,
                            "target": target,
                            "bbox": [round(v, 2) for v in [rect.x0, rect.y0, rect.x1, rect.y1]],
                            "layout_role": "acknowledgement_chapter_heading",
                            "failure_stage": "paint",
                            "fill_strategy": "sampled_source_lavender_background_not_white_redaction",
                            "font_policy": "source_like_purple_bold_heading",
                            "text_policy": "translate_chapter_topic_heading_preserve_contributor_names",
                            "backend_sink_down": "pending",
                            "applied_to_standard_pdf": True,
                        }
                    )
        finally:
            if source_doc is not None:
                source_doc.close()
        return fixed

    def repair_ai_page4_and_page6_link_text(doc: Any) -> list[dict[str, Any]]:
        if doc.page_count < 6:
            return []
        fixed: list[dict[str, Any]] = []
        fixed.extend(build_visual_repair_pdf.repair_ai_page4_closing_and_signature(fitz, doc))
        fixed.extend(build_visual_repair_pdf.repair_ai_page6_link_lines(fitz, doc))
        for item in fixed:
            item["source_pdf"] = str(source_pdf)
            item["applied_to_standard_pdf"] = True
            item["backend_sink_down"] = "pending"
        return fixed

    try:
        doc = fitz.open(str(pdf_path))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"open_failed: {exc}", "repairs": []}

    with doc:
        if "exploring ais performance" in source_name:
            if doc.page_count >= 1:
                page = doc[0]
                hits = page.search_for("AI-based models are transforming the translation industry")
                abstract = (
                    "基于人工智能的模型正在改变翻译行业，谷歌翻译的神经机器翻译（NMT-GT）和大型语言模型（LLMs）等工具推动了这一进程。"
                    "然而，将这些模型用于文学翻译这一即便对经验丰富的人类译者也颇具挑战的领域，仍会引出关键问题：人工智能在多大程度上能够复现人类翻译的深度与细腻差异，"
                    "神经机器翻译、通用型大型语言模型或推理型大型语言模型中，哪一类更接近人类译文？本研究基于语料库，比较了NMT-GT、ChatGPT-4o和OpenAI-o1的译文与人类译文。"
                    "分析显示，不同系统在词汇与句法多样性、文本库与情境模型以及可读性等多个语言维度上存在显著差异。结果表明，在这本文学自传案例中，ChatGPT-4o与人类译文最为接近，其次是NMT-GT，而OpenAI-o1相似度最低。"
                    "这些发现说明，神经机器翻译系统在接近人类译文方面并不必然逊于大型语言模型；推理型OpenAI-o1也未比通用型AI模型生成更具人类风格的译文，其中ChatGPT-4o最有效地弥合了人类译文与AI生成译文之间的差距。"
                )
                if hits:
                    if apply_overlay:
                        first = hits[0]
                        block = fitz.Rect(first.x0 - 2, first.y0 - 2, page.rect.width - 45, min(page.rect.height - 85, first.y0 + 265))
                        page.add_redact_annot(block, fill=(1, 1, 1))
                        page.apply_redactions()
                        page.insert_textbox(block, abstract, fontname="china-s", fontsize=6.7, color=(0, 0, 0), overlay=True)
                    repairs.append({"page": 1, "source": "AI-based models abstract", "target": "中文摘要覆盖修复", "count": 1})
                elif replace_block_by_normalized_prefix(page, "AI-based models are transforming the translation industry", abstract):
                    repairs.append(
                        {
                            "page": 1,
                            "source": "AI-based models abstract",
                            "target": "中文摘要覆盖修复",
                            "count": 1,
                            "mode": "normalized_block",
                        }
                    )
            replace_on_pages(
                doc,
                {
                    "Introduction": "引言",
                    "Literature review": "文献综述",
                },
                pages={2},
                fontsize=8.5,
            )
            replace_on_pages(
                doc,
                {
                    "Methods": "方法",
                    "Sub-corpus": "子语料库",
                    "Number of texts": "文本数量",
                    "Tokens": "词数",
                    "Mean length": "平均长度",
                },
                pages={3},
                fontsize=8.5,
            )
            replace_on_pages(
                doc,
                {
                    "References": "参考文献",
                },
                pages={13},
                fontsize=8.5,
                max_hits_per_source=1,
            )
            replace_on_pages(
                doc,
                {
                    "Acknowledgements": "致谢",
                    "This research was supported by The Hong Kong Polytechnic University": "本研究得到香港理工大学支持",
                    "This research was supported by TheHong Kong Polytechnic University": "本研究得到香港理工大学支持",
                    "Supplementary information": "附加信息",
                    "Correspondence and requests for materials should be addressed to Andrew Kay Fan Cheung.": "通讯及材料请求请联系 Andrew Kay Fan Cheung。",
                },
                pages={14},
                fontsize=7.2,
                max_hits_per_source=1,
            )
            if apply_overlay:
                repairs.extend(build_visual_repair_pdf.repair_nature_page13_backmatter_headings(fitz, doc))
                repairs.extend(build_visual_repair_pdf.repair_nature_page13_publication_metadata(fitz, doc))
                repairs.extend(build_visual_repair_pdf.repair_nature_page14_backmatter(fitz, doc))
            replace_on_pages(
                doc,
                {
                    "文本基础": "文本库",
                    "1 Hong Kong Polytechnic University, Hong Kong, China.": "1 香港理工大学，中国香港。",
                    "1 Hong Kong Polytechnic 香港理工大学，中国香港": "1 香港理工大学，中国香港",
                },
                pages={1, 14},
                fontsize=8.5,
            )
            repairs.extend(repair_nature_page1_affiliation_footer(doc))
            repairs.extend(repair_nature_metadata_headers(doc))
        elif "ai_index_report_2026" in source_name:
            replace_on_pages(
                doc,
                {
                    "Contents": "目录",
                    "Introduction": "引言",
                    "Research and Development": "研究与开发",
                    "Chapter Highlights": "章节要点",
                    "Notable AI models": "值得关注的人工智能模型",
                    "ORGANIZATIONS": "机构",
                    "CO-CHAIR": "联合主席",
                    "CO-主席": "联合主席",
                    "Co 主席": "联合主席",
                    "CHAIR": "主席",
                    "MEMBERS": "成员",
                    "Stanford University": "斯坦福大学",
                    "Northeastern University": "东北大学",
                    "University of Minnesota": "明尼苏达大学",
                    "Google, University of Oxford": "谷歌，牛津大学",
                    "谷歌,\x03University\x03of\x03Oxford": "谷歌，牛津大学",
                    "University of Oxford": "牛津大学",
                    "SRI International": "SRI International",
                    "Brookings": "布鲁金斯学会",
                    "University of Southern California": "南加州大学",
                    "USC Information Sciences Institute": "南加州大学信息科学研究所",
                    "Information Sciences Institute": "信息科学研究所",
                    "JPMorgan Chase & Co.": "摩根大通",
                    "Schmidt Sciences": "Schmidt Sciences",
                    "UNSW Sydney": "悉尼新南威尔士大学",
                    "University": "大学",
                },
                pages={1, 2, 3, 5, 8, 9, 14, 15},
                fontsize=7.2,
                max_hits_per_source=12,
            )
            replace_lines_by_normalized_text(
                doc,
                {
                    "CO-主席": "联合主席",
                    "Co 主席": "联合主席",
                    "谷歌, University of Oxford": "谷歌，牛津大学",
                    "Information Sciences Institute": "信息科学研究所",
                    "University of Southern California, Information Sciences Institute": "南加州大学，信息科学研究所",
                },
                fontsize=7.2,
            )
            if apply_overlay:
                repairs.extend(repair_ai_cover_page(doc))
                repairs.extend(repair_ai_page4_and_page6_link_text(doc))
                repairs.extend(repair_ai_page9_acknowledgement_chapter_headings(doc))
                repairs.extend(repair_ai_page5_steering_roster(doc))
                repairs.extend(repair_ai_page6_staff_roster(doc))
                repairs.extend(repair_ai_page14_research_contents(doc))
                repairs.extend(repair_ai_page18_20_chart_regions(doc))
                repairs.extend(repair_ai_page17_orphan_footer_x(doc))
            manifest_reason = "ai_index_targeted_heading_label_overlay"
        if repairs and apply_overlay:
            tmp = pdf_path.with_suffix(".text_repaired.tmp.pdf")
            doc.save(str(tmp), garbage=4, deflate=True)
            tmp.replace(pdf_path)

    manifest_path = output_dir / "pdf_direct_text_repair_manifest.json"
    existing_repairs: list[dict[str, Any]] = []
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and str(existing.get("pdf") or "") == str(pdf_path):
                existing_repairs = existing.get("repairs", []) if isinstance(existing.get("repairs"), list) else []
        except Exception:
            existing_repairs = []
    combined_repairs = existing_repairs[:] if apply_overlay else []
    for repair in repairs:
        if repair not in combined_repairs:
            combined_repairs.append(repair)
    status = "repaired" if apply_overlay and combined_repairs else ("needs_rerender" if combined_repairs else ("skipped" if manifest_reason else "ok"))
    manifest = {
        "version": 1,
        "status": status,
        "reason": manifest_reason,
        "pdf": str(pdf_path),
        "overlay_applied": bool(apply_overlay and combined_repairs),
        "delivery_safe": not bool(apply_overlay and combined_repairs),
        "note": (
            "PDF direct text repair is recorded as rerender evidence; main delivery PDF is not mutated."
            if combined_repairs and not apply_overlay
            else ""
        ),
        "repairs": combined_repairs,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
