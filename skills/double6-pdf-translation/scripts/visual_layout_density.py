# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout density：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def text_density_stats(page: dict[str, Any]) -> dict[str, Any]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    page_area = float(page.get("width") or 0) * float(page.get("height") or 0)
    covered = 0.0
    for span in spans:
        box = span.get("bbox") or []
        if len(box) != 4:
            continue
        covered += max(float(box[2]) - float(box[0]), 0.0) * max(float(box[3]) - float(box[1]), 0.0)
    return {
        "span_count": len(spans),
        "text_area_ratio": round(covered / max(page_area, 1.0), 4),
    }

def is_allowed_compact_label(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "@" in stripped or "://" in stripped or stripped.lower().startswith(("doi", "http")):
        return True
    if re.fullmatch(r"[A-Za-z0-9_.%+-]+\.[A-Za-z]{2,}(?:\.[A-Za-z]{2,})?", stripped):
        return True
    if APPROVED_COMPACT_NAME_RE.fullmatch(stripped):
        return True
    if re.fullmatch(r"(?:OpenAI|GPT|ChatGPT)\s+o?\d+[A-Za-z]*", stripped):
        return True
    if AUTHOR_CITATION_LABEL_RE.fullmatch(stripped):
        return True
    if ALLOWED_COMPACT_LABEL_RE.match(stripped):
        return True
    if stripped in DIAGRAM_LABEL_ALLOWLIST:
        return True
    # 多词作者/机构名可保留；普通 Title Case 标题短语仍应进入 residual。
    words = stripped.split()
    if 2 <= len(words) <= 4 and all(word[:1].isupper() for word in words if word) and re.search(
        r"\b(?:University|Institute|Inc\.?|Ltd\.?|Corp\.?|International)\b", stripped
    ):
        return True
    return False

def is_neutral_compact_label(text: str) -> bool:
    stripped = text.strip()
    if not stripped or COMMON_UNTRANSLATED_HEADING_RE.match(stripped):
        return False
    if re.fullmatch(r"[A-Z][A-Za-z'’.-]{1,24}", stripped):
        return True
    if re.search(r"\bvs\.?\b", stripped, re.IGNORECASE) and re.search(
        r"\b(?:HT|MT|NMT|LLM|GPT|AI)\b",
        stripped,
        re.IGNORECASE,
    ):
        return True
    return False

def is_policy_passthrough_compact_label(text: str, page_text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    page_has_ai_acknowledgements = (
        "人工智能指数" in page_text
        and "表示感谢" in page_text
        and ("机构" in page_text or "ORGANIZATIONS" in page_text)
    )
    if page_has_ai_acknowledgements:
        if stripped in {"Policy and Governance", "Public Opinion"}:
            return False
        if stripped in {"Epoch AI", "McKinsey & Company", "GitHub", "Quid", "Lightcast", "Zeki", "LinkedIn"}:
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}", stripped):
            return True
    page_has_ai_roster = is_ai_roster_page_text(page_text)
    if page_has_ai_roster:
        if re.fullmatch(r"[A-Z][A-Z'’.-]+(?:\s+[A-Z][A-Z'’.-]+){1,3}", stripped):
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}", stripped):
            return True
        if stripped in {"Salesforce", "AI21 Labs", "UNSW Sydney", "Anthropic·OECD", "Anthropic-OECD", "Google Drive"}:
            return True
    page_has_ai_citation_frontmatter = (
        "如何引用本报告" in page_text
        and "公开数据与工具" in page_text
        and "Google Drive" in page_text
    )
    if page_has_ai_citation_frontmatter:
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}", stripped):
            return True
        if stripped in {"Google Drive", "AI Index", "AI", "bles"}:
            return True
    page_has_parallel_example = bool(
        re.search(r"\bExample\s+\d+:", page_text)
        and re.search(r"\bST:", page_text)
        and re.search(r"\b(?:NMT-GT|LLM-[A-Za-z0-9]+):", page_text)
    )
    if page_has_parallel_example:
        if re.match(r"^(?:Example\s+\d+:|ST:|HT:|NMT(?:-[A-Za-z0-9]+)?:|LLM-[A-Za-z0-9]+:)", stripped):
            return True
        # Example source/translation snippets are intentionally preserved in
        # Nature literary translation comparison blocks.
        if re.fullmatch(r"[A-Za-z][A-Za-z'’.,;:() -]{1,34}", stripped):
            return True

    page_has_references = bool(
        re.search(r"(?:参考文献|References)", page_text)
        or (
            re.search(r"\barXiv\b", page_text, re.I)
            and re.search(r"\b(?:preprint|doi|Proc|Translat|Linguist|Mach Transl|University Press)\b", page_text, re.I)
        )
    )
    if page_has_references:
        if not COMMON_UNTRANSLATED_HEADING_RE.match(stripped) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9'’.,;:()_ ./&:+\\-]{1,34}", stripped):
            return True
        if re.search(r"\b(?:arXiv|ACM|IEEE|Proc|Intell|Technol|Comput|Translat|Longman|Cambridge)\b", stripped):
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:,\s*[A-Z][A-Za-z'’.-]+)*", stripped):
            return True
        if re.fullmatch(r"[A-Za-z0-9_./-]{4,34}", stripped) and any(token in stripped for token in ["/", ".", "_"]):
            return True
        if re.fullmatch(r"[A-Za-z][A-Za-z'’.,;:() -]{1,34}", stripped) and re.search(
            r"\b(?:et al|preprint|survey|translation|translator|machine|models?|analysis|language|corpus|by)\b",
            stripped,
            re.I,
        ):
            return True

    return False

def is_ai_roster_page_text(page_text: str) -> bool:
    if "人工智能指数" in page_text and "贡献者" in page_text and re.search(r"\b(?:Yolanda Gil|Vanessa Parli|Ray(?:mond)? Perrault)\b", page_text):
        return True
    if "工作人员与研究人员" in page_text and re.search(r"\b(?:LEAD AND EDITOR-IN-CHIEF|Loredana Fattorini|Sha Sajadieh)\b", page_text):
        return True
    if re.search(r"\b(?:LEAD AND EDITOR-IN-CHIEF|RESEARCH MANAGER|AFFILIATED RESEARCHERS)\b", page_text) and re.search(r"\b(?:Raymond Perrault|Yolanda Gil|Loredana Fattorini|Sha Sajadieh)\b", page_text):
        return True
    roster_tokens = [
        "YOLANDA GIL",
        "RAYMOND PERRAULT",
        "RUSS ALTMAN",
        "CARLA BRODLEY",
        "ERIK BRYNJOLFSSON",
        "VIRGINIA DIGNUM",
        "VIPIN KUMAR",
        "JAMES LANDAY",
        "TERAH LYONS",
        "JAMES MANYIKA",
        "JUAN CARLOS",
    ]
    hit_count = sum(1 for token in roster_tokens if token in page_text)
    return hit_count >= 6 and ("指导委员会" in page_text or "Steering Committee" in page_text)

def is_ai_roster_page(page: dict[str, Any]) -> bool:
    return is_ai_roster_page_text(str(page.get("text") or ""))

def compact_text_for_context(text: str) -> str:
    return re.sub(r"\s+", "", text)

def is_latextrans_placeholder_diagram_text(page_text: str) -> bool:
    compact = compact_text_for_context(page_text)
    return (
        "LaTeXTrans" in page_text
        and bool(VISIBLE_LATEX_COMMAND_RE.search(page_text))
        and (
            "placeholder_ENV" in page_text
            or "placeholder_CAP" in page_text
            or "captions map" in page_text
            or "environments map" in page_text
            or "sections map" in page_text
            or "占位符" in page_text
        )
        and ("图2" in compact or "Figure2" in compact or "处理流程" in page_text)
    )

def is_latextrans_embedded_case_figure_text(page_text: str) -> bool:
    compact = compact_text_for_context(page_text)
    lower_compact = compact.lower()
    return (
        "LaTeXTrans" in page_text
        and ("图5" in compact or "Figure5" in compact)
        and ("案例1" in compact or "case1" in lower_compact)
        and ("案例2" in compact or "案例二" in compact or "case2" in lower_compact)
        and (
            "AirRoom" in page_text
            or "VAPO" in page_text
            or "英语至日语" in page_text
            or "AirRoom の" in page_text
        )
    )

def is_latextrans_visual_passthrough_page(page: dict[str, Any]) -> bool:
    page_text = str(page.get("text") or "")
    return is_latextrans_placeholder_diagram_text(page_text) or is_latextrans_embedded_case_figure_text(page_text)

def compact_label_stats(page: dict[str, Any]) -> dict[str, Any]:
    spans = [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]
    page_area = float(page.get("width") or 0) * float(page.get("height") or 0)
    page_text = str(page.get("text") or "")
    residual: list[str] = []
    allowed: list[str] = []
    neutral: list[str] = []
    for span in spans:
        text = str(span.get("text") or "").strip()
        box = span.get("bbox") or []
        if len(box) != 4 or not COMPACT_LABEL_RE.match(text):
            continue
        area = max(float(box[2]) - float(box[0]), 0.0) * max(float(box[3]) - float(box[1]), 0.0)
        size = float(span.get("size") or 0)
        if area / max(page_area, 1.0) <= 0.012 or (0 < size < 8):
            if is_allowed_compact_label(text) or is_policy_passthrough_compact_label(text, page_text):
                allowed.append(text)
            elif is_neutral_compact_label(text):
                neutral.append(text)
            else:
                residual.append(text)
    return {
        "compact_label_count": len(residual),
        "allowed_compact_label_count": len(allowed),
        "neutral_compact_label_count": len(neutral),
        "compact_label_samples": residual[:12],
        "allowed_compact_label_samples": allowed[:12],
        "neutral_compact_label_samples": neutral[:12],
    }

def is_dense_chart_or_index_page(page: dict[str, Any], small_fonts: dict[str, Any], compact_labels: dict[str, Any]) -> bool:
    text = str(page.get("text") or "")
    compact_text = re.sub(r"\s+", "", text)
    markers = 0
    for pattern in [
        r"\bContributors\b",
        r"\bChapter\s+\d+",
        r"\bResearch and Development\b",
        r"\bTechnical Performance\b",
        r"\bResponsible AI\b",
        r"\bOverview\b",
        r"\bPublications?\b",
        r"\bPatents?\b",
        r"\bAI\s+patents?\b",
        r"\bForward\s+Citations?\b",
        r"\bHugging\s+Face\b",
        r"\bConference\s+Attendance\b",
        r"\bTop\s+100\s+Publications\b",
        r"\bModel\s+and\s+Dataset\s+Ecosystem\b",
        r"\bMedicine\b",
        r"\bEducation\b",
        r"\bEconomy\b",
    ]:
        if re.search(pattern, text, re.I):
            markers += 1
    ai_index_chart_markers = (
        ("AI Index" in text or "人工智能指数报告" in text)
        and (re.search(r"图\d+\.\d+\.\d+", compact_text) or re.search(r"\bFigure\s+\d+\.\d+\.\d+", text, re.I))
        and (
            "知名人工智能模型" in text
            or "出版物" in text
            or "专利" in text
            or "前向引用" in text
            or "知识扩散" in text
            or re.search(
                r"\b(?:Notable AI models|AI publications|Publications|AI patents|Patents|Forward Citations|Knowledge Diffusion|Hugging\s+Face|Conference Attendance|Top 100 Publications|Model and Dataset Ecosystem)\b",
                text,
                re.I,
            )
        )
    )
    small_count = int(small_fonts.get("small_font_span_count") or 0)
    compact_count = int(compact_labels.get("compact_label_count") or 0)
    allowed_count = int(compact_labels.get("allowed_compact_label_count") or 0)
    neutral_count = int(compact_labels.get("neutral_compact_label_count") or 0)
    ai_index_patent_chart_markers = (
        ("AI Index" in text or "人工智能指数报告" in text)
        and (
            "授权AI专" in text
            or "AI patents" in text
            or "专利占全球总" in text
            or "专利占全球总" in text
            or "前向引用" in text
            or "Forward Citations" in text
        )
    )
    if (ai_index_chart_markers or ai_index_patent_chart_markers) and small_count >= 8:
        return True
    return markers >= 3 and small_count >= 12 and (compact_count + allowed_count + neutral_count) >= 4

def analyze_visual_pages(
    source_pages: list[dict[str, Any]],
    translated_pages: list[dict[str, Any]],
    *,
    key_texts: list[str] | None = None,
    full_translated_text: str | None = None,
) -> dict[str, Any]:
    from visual_layout_core import count_overlapping_spans, dominant_color_ratio, extract_key_texts, graphic_visibility_findings, nonblack_color_ratio, normalize_finding, overlap_pair_samples, total_overlapping_area
    from visual_layout_extract import block_role_profile, geometry_profile, page_text_layer_health, typography_profile
    from visual_layout_structure import directory_order_findings, small_font_stats, tiny_heading_spans
    from visual_layout_styles import abstract_typography_findings, chart_axis_label_malformed_findings, source_translated_chart_title_findings, source_translated_heading_style_findings, source_translated_protected_name_findings, source_translated_publisher_badge_findings, source_translated_table_caption_findings
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
        findings.extend(graphic_visibility_findings(source, translated, page_number))
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
                "graphic_paint": {"source": source.get("graphic_paint"), "candidate": translated.get("graphic_paint")},
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
        if heading_tiny_samples:
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


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
