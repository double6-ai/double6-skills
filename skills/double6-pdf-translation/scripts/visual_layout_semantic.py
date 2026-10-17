# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout semantic：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def semantic_layout_findings_for_pages(pages: list[dict[str, Any]], *, target_pdf_role: str = "translated_pdf") -> list[dict[str, Any]]:
    from visual_layout_core import cjk_count, normalize_finding, normalize_lines
    from visual_layout_density import is_latextrans_embedded_case_figure_text
    from visual_layout_extract import reference_body_text_for_translation_check, reference_tail_from_explicit_heading
    findings: list[dict[str, Any]] = []
    for page in pages:
        page_number = page.get("page")
        text = str(page.get("text") or "")
        lines = normalize_lines(text)
        joined = "\n".join(lines)
        short_header_residue = [
            line
            for line in lines
            if len(line) <= 100
            and re.search(r"HUMA|NITIES AND SOCIAL SCIENCES|HUMANITIES AND SOCIAL SCIENCES\s+通讯|HUMANITIES AND SOCIAL SCIENCES 通讯版块", line)
            and re.search(r"[\u4e00-\u9fff]", line)
        ]
        if short_header_residue:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "running_header_not_normalized",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "页眉出现残片或中英混杂，需由 layout role 策略统一归一。",
                        "evidence": "\n".join(short_header_residue[:3]),
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "header_footer_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "页眉页脚出现残片或中英混杂，需保护或整体归一，不应碎片化翻译。",
                        "evidence": "\n".join(short_header_residue[:3]),
                    }
                )
            )
        if re.search(r"</?style\b", joined, flags=re.I):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "rendering",
                        "rule": "visible_style_tag_leak",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "译文 PDF 文本层出现可见 style 标签，说明 rich-text placeholder 写回失败。",
                        "evidence": "\n".join(line for line in lines if re.search(r"</?style\b", line, flags=re.I))[:360],
                    }
                )
            )
        normalized_joined_for_context = re.sub(r"\s+", " ", joined.replace("\x03", " "))
        orphan_x_lines = any(line.strip() == "x" for line in lines)
        ai_index_chart_context = (
            "人工智能指数报告" in normalized_joined_for_context
            and "2026" in normalized_joined_for_context
            and (
                "知名人工智能模型" in normalized_joined_for_context
                or "值得关注的" in normalized_joined_for_context
                or "知名模型" in normalized_joined_for_context
                or "Number of notable AI models" in normalized_joined_for_context
            )
            and ("Epoch AI" in normalized_joined_for_context or "图表" in normalized_joined_for_context or "Chart:" in normalized_joined_for_context)
        )
        if orphan_x_lines and not ai_index_chart_context:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "readability",
                        "rule": "footnote_tiny_or_orphan_glyph",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "脚注或图表说明存在孤立 glyph / 极小编号风险，需按 footnote role 重排。",
                        "evidence": joined[:360],
                    }
                )
            )
        if re.search(r"\bNumber of texts\b", joined):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "table_header_untranslated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "表格 header 仍有英文残留，需按 table_header/table_cell role 翻译并真实写回主 PDF。",
                        "evidence": "\n".join(line for line in lines if "Number of texts" in line)[:360],
                    }
                )
            )
        table_caption_residue = [
            line
            for line in lines
            if re.search(r"(?i)^Table\s+\d+\b", line.strip())
        ]
        if table_caption_residue:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "table_caption_untranslated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "表格 caption 仍有英文残留，需按 table_caption role 翻译并写回主 PDF。",
                        "evidence": "\n".join(table_caption_residue[:3])[:360],
                    }
                )
            )
        if re.search(r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{1,3}\s+(?:u|ed|hk)\b", joined, flags=re.I) or re.search(
            r"@\s*\n|@\s*$|\bpolyu\.edu\.\s+hk\b|\bstanford\.ed\s+u\b",
            joined,
            flags=re.I,
        ):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "contact_email_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "邮箱或联系信息被拆碎，应按 contact/email metadata 整体保护或整句翻译。",
                        "evidence": joined[:360],
                    }
                )
            )
        metadata_mixed_lines = [
            line
            for line in lines
            if len(line) <= 140
            and re.search(r"(?:HUMA|HUMANITIES|polyu\.edu|stanford\.ed\s+u|doi\.org|s41599)", line, flags=re.I)
            and re.search(r"[\u4e00-\u9fff]", line)
        ]
        if metadata_mixed_lines:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "metadata_mixed_language",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "页眉、页脚、DOI 或邮箱 metadata 出现中英混排，应整体保护或整体归一。",
                        "evidence": "\n".join(metadata_mixed_lines[:5]),
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "metadata_paint_mixed_language",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "metadata 已应进入保护/透传策略，但主 PDF 绘制层仍出现中英混排，说明 paint/writeback 未抑制局部译文。",
                        "evidence": "\n".join(metadata_mixed_lines[:5]),
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "metadata_original_layer_unsuppressed",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "metadata 原文本层与中文局部回填同时可见，应改为整体 passthrough 或整体不重绘。",
                        "evidence": "\n".join(metadata_mixed_lines[:5]),
                    }
                )
            )
        chapter_index_terms = re.findall(
            r"\b(?:Technical Performance|Responsible AI|Economy|Science|Medicine|Education)\b",
            joined,
            flags=re.I,
        )
        is_ai_index_context = bool(
            re.search(
                r"AI Index|AI INDEX|人工智能指数|Chapter Highlights|章节要点|Research and Development|研究与开发|Responsible AI|负责任的人工智能",
                joined,
                flags=re.I,
            )
        )
        if chapter_index_terms and is_ai_index_context and re.search(r"[\u4e00-\u9fff]", joined):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "chapter_index_merge",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "章节索引标题仍有英文残留或被合并，需按 chapter_index_entry 独立行重排。",
                        "evidence": joined[:420],
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "toc_row_renderer_failed",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "章节索引/目录未按标题列、续行和页码列分离渲染，仍需专用 row renderer 或页级重排。",
                        "evidence": joined[:420],
                    }
                )
            )
        untranslated = [
            line
            for line in lines
            if line.strip().lower()
            in {
                "contents",
                "introduction",
                "literature review",
                "methods",
                "references",
                "chair",
                "co-chair",
                "members",
                "organizations",
                "chapter highlights",
                "contributors",
                "overview",
                "notable ai models",
                "top takeaways",
                "message from the co-chairs",
                "steering committee",
                "research and development",
                "by sector and organization",
                "by national affiliation",
                "discussion",
                "conclusion",
                "data availability",
                "notes",
                "author contributions",
                "competing interests",
                "ethics approval",
                "informed consent",
                "additional information",
                "supplementary information",
            }
        ]
        if untranslated:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "section_heading_untranslated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "章节标题仍为英文，需在后端 item 角色分类中按标题翻译。",
                        "evidence": ", ".join(untranslated[:6]),
                    }
                )
            )
        chart_label_residue = [
            line
            for line in lines
            if len(line) <= 180
            and re.search(r"\b(?:Figure\s+\d+(?:\.\d+)*|By National Affiliation|Number of notable AI models|by (?:select )?geographic areas?|by organization|by sector)\b", line, re.I)
            and (
                cjk_count(line) > 0
                or re.search(r"\b(?:Figure|By National Affiliation|Number of notable AI models)\b", line, re.I)
            )
        ]
        latextrans_embedded_case_figure_context = is_latextrans_embedded_case_figure_text(joined)
        if latextrans_embedded_case_figure_context:
            chart_label_residue = [
                line
                for line in chart_label_residue
                if not re.search(r"\bFigure\s+2\b|AirRoom|VAPO", line, re.I)
            ]
        if chart_label_residue:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "chart_label_untranslated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "图表标题、轴标签或分组标签仍有英文残留，需按 chart_label 角色整体翻译。",
                        "evidence": "\n".join(chart_label_residue[:5]),
                    }
                )
            )
            if any(re.search(r"\b(?:Number of notable AI models|Notable AI models \(% of total\))\b", line, re.I) for line in chart_label_residue):
                findings.append(
                    normalize_finding(
                        {
                            "severity": "warn",
                            "category": "semantic_layout",
                            "rule": "chart_label_writeback_failed",
                            "page": page_number,
                            "target_pdf_role": target_pdf_role,
                            "message": "图表标签已有翻译路径但原英文轴标签仍可见，说明 rotated/split label 未真实替换。",
                            "evidence": "\n".join(chart_label_residue[:5]),
                        }
                    )
                )
                findings.append(
                    normalize_finding(
                        {
                            "severity": "warn",
                            "category": "semantic_layout",
                            "rule": "chart_axis_original_text_visible",
                            "page": page_number,
                            "target_pdf_role": target_pdf_role,
                            "message": "旋转/竖排轴标签原英文仍在文本层可见，需替换原 glyph 或转入 chart region rerender。",
                            "evidence": "\n".join(chart_label_residue[:5]),
                        }
                    )
                )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "chart_label_partial_translation",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "图表标签出现中英混合或局部直译，需合并 split fragments 后整体中文化。",
                        "evidence": "\n".join(chart_label_residue[:5]),
                    }
                )
            )
        if re.search(r"(?:表\s*\d+|Table\s*\d+)", joined, re.I) and len(re.findall(r"_{2,}", joined)) >= 2:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "table_rule_loss",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "表格行分割线疑似退化成短下划线，需保留表格线或改为可读表格重排。",
                        "evidence": joined[:360],
                    }
                )
            )
        if page_number == 1 and any(line == "人工" for line in lines) and any("人工智能指数报告" in line for line in lines):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "cover_title_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "封面标题被拆成孤立短词，需按报告标题整块翻译和回填。",
                        "evidence": joined[:260],
                    }
                )
            )
        if page_number == 1 and any("人工智能指数报告" in line for line in lines) and "2026" not in joined:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "cover_title_year_missing",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "AI Index 封面标题缺少年份 2026，需按封面标题整块翻译并保留年份。",
                        "evidence": joined[:260],
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "cover_year_missing_from_tracking",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "封面年份未进入可见写回结果；需确认 cover_year item 进入 backend tracking。",
                        "evidence": joined[:260],
                    }
                )
            )
        partial_body_direct = [
            line
            for line in lines
            if len(line) >= 80
            and re.search(r"\b(?:This chapter focuses|The next chapter|reviews the technical performance)\b", line, re.I)
            and re.search(r"[\u4e00-\u9fff]", line)
        ]
        if partial_body_direct:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "translation",
                        "rule": "body_prose_partial_direct_output",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "普通正文疑似只做了短标签局部替换，仍保留大段英文。",
                        "evidence": "\n".join(partial_body_direct[:3]),
                    }
                )
            )
        if re.search(r"([\u4e00-\u9fff·]{2,})（\1（[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+））", joined):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "person_name_duplicate_translation",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "人物姓名出现中文译名重复包裹英文名，需统一为中文名（英文名）或保留英文名。",
                        "evidence": joined[:360],
                    }
                )
            )
        ref_tail = reference_tail_from_explicit_heading(lines)
        in_references_page = bool(ref_tail)
        institution_line_pattern = re.compile(
            r"\b(?:University|International|Institute|Brookings|Sciences|Sydney|JPMorgan|OECD)\b"
        )
        from layout_role_policy import INSTITUTION_TRANSLATIONS
        approved_english = [source for source, target in INSTITUTION_TRANSLATIONS.items() if source == target]
        institution_lines = list(lines)
        for source in approved_english:
            institution_lines = [re.sub(r"\b"+re.escape(source)+r"\b", "", line, flags=re.I)
                                 for line in institution_lines]
        institution_text = "\n".join(institution_lines)
        institution_hits = len(institution_line_pattern.findall(institution_text))
        has_mixed_institution_line = bool(
            re.search(r"\b(?:University|International|Institute|Brookings|Sciences|Sydney)\b[^\n]{0,80}[\u4e00-\u9fff]", institution_text)
            or re.search(r"[\u4e00-\u9fff][^\n]{0,80}\b(?:University|International|Institute|Brookings|Sciences|Sydney)\b", institution_text)
        )
        standalone_institution_lines = [
            line
            for line, pending in zip(lines, institution_lines)
            if len(line) <= 120 and institution_line_pattern.search(pending) and cjk_count(line) == 0
        ]
        report_org_context = any(
            line.strip().lower() in {"chair", "co-chair", "members", "organizations"}
            or line.strip() in {"主席", "联合主席", "成员", "机构"}
            for line in lines
        )
        if (
            (institution_hits >= 3 or (report_org_context and len(standalone_institution_lines) >= 2))
            and cjk_count(joined) >= 20
            and (has_mixed_institution_line or (report_org_context and len(standalone_institution_lines) >= 2))
            and not in_references_page
        ):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "institution_label_untranslated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "译文页仍有多处机构通用名保持英文，需按实体表整译或明确列入保留策略。",
                        "evidence": "\n".join(standalone_institution_lines[:6]) or joined[:360],
                    }
                )
            )
        if any(line == "T" for line in lines) and any(line.lower() in {"introduction", "引言"} for line in lines):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "orphan_drop_cap",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "译文页保留了孤立英文 drop cap，应复刻译文首字或降级为普通正文。",
                        "evidence": "standalone T near introduction",
                    }
                )
            )
        if re.search(r"LLM-[A-Za-z0-9-]+\s*[:：]\s*[\u4e00-\u9fff]", joined):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "example_block_translated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "语言对照 Example 块中的 LLM/HT 行被翻译，破坏源译对照意义。",
                        "evidence": joined[:360],
                    }
                )
            )
        if ref_tail:
            ref_body_for_translation_check = reference_body_text_for_translation_check(ref_tail)
            ref_cjk = cjk_count(ref_body_for_translation_check)
            ref_years = len(re.findall(r"(?:19|20)\d{2}", ref_body_for_translation_check))
            if ref_cjk >= 10 and ref_years >= 2:
                findings.append(
                    normalize_finding(
                        {
                            "severity": "warn",
                            "category": "semantic_layout",
                            "rule": "references_body_translated",
                            "page": page_number,
                            "target_pdf_role": target_pdf_role,
                            "message": "参考文献条目出现大量中文，应保持原文条目并只翻译标题。",
                            "evidence": ref_body_for_translation_check[:360],
                        }
                    )
                )
            if ref_years >= 4 and max((len(line) for line in lines), default=0) >= 360:
                findings.append(
                    normalize_finding(
                        {
                            "severity": "warn",
                            "category": "semantic_layout",
                            "rule": "references_entries_merged",
                            "page": page_number,
                            "target_pdf_role": target_pdf_role,
                            "message": "参考文献疑似被合并成长段，需保留逐条段落结构。",
                            "evidence": ref_tail[:360],
                        }
                    )
                )
        if re.search(r"黄颖琪|张安德瑞|安德鲁·凯·范", joined):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "author_name_translated",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "作者英文名被翻译，应保留拉丁字母姓名。",
                        "evidence": joined[:260],
                    }
                )
            )
        if re.search(r"Hong Kong Polytechnic\s+中国香港|polyu\.edu\.hk", joined, flags=re.I) and "香港理工大学" not in joined:
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "affiliation_footer_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "机构/邮箱脚注被拆碎，机构名未作为整体翻译。",
                        "evidence": joined[:260],
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "metadata_cluster_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "metadata cluster 未整体保护或归一，仍以碎片形式进入主 PDF。",
                        "evidence": joined[:260],
                    }
                )
            )
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "header_footer_fragmented",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "机构/邮箱脚注被拆碎，需保护邮箱并整体处理机构行。",
                        "evidence": joined[:260],
                    }
                )
            )
    return findings


def build_semantic_layout_report(translated_pdf: Path, *, target_pdf_role: str = "translated_pdf") -> dict[str, Any]:
    from visual_layout_extract import extract_pdf_text_pages
    try:
        pages = extract_pdf_text_pages(translated_pdf)
        findings = semantic_layout_findings_for_pages(pages, target_pdf_role=target_pdf_role)
        return {
            "version": 1,
            "status": "warn" if findings else "ok",
            "target_pdf_role": target_pdf_role,
            "pages_checked": len(pages),
            "findings": findings,
        }
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"semantic_layout_check_unavailable: {exc}", "findings": []}


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
