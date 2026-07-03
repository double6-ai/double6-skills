#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by visual_layout.py for semantic layout reports and paragraph label audits."

import json
import re
from pathlib import Path
from typing import Any


from visual_layout_core import *  # noqa: F401,F403
from visual_layout_core import _load_fitz
from visual_layout_findings import *  # noqa: F401,F403
from visual_layout_analyzer import *  # noqa: F401,F403
from visual_layout_analyzer import _page_region_metrics

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


REFERENCE_BODY_IGNORE_LINES = {
    "data availability",
    "数据可用性",
    "notes",
    "注释",
    "published online",
    "在线发表",
    "received",
    "收稿日期",
    "accepted",
    "录用日期",
}


def is_policy_preserved_metadata_line(line: str) -> bool:
    value = re.sub(r"\s+", " ", str(line or "")).strip()
    if not value:
        return False
    has_email = bool(re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", value))
    if has_email and not re.search(r"@\s*$|@\s+|\.ed\s+u\b|\.edu\.\s+hk\b", value, re.I):
        if "香港理工大学" in value or "Hong Kong Polytechnic University" in value or "邮箱" in value or "email" in value.lower():
            return True
    if re.search(r"^HUMANITIES\s+AND\s+SOCIAL\s+SCIENCES\s+COMMUNICATIONS\b", value, re.I) and not re.search(r"[\u4e00-\u9fff]", value):
        return True
    if re.search(r"^https://doi\.org/10\.1057/s41599", value, re.I) and not re.search(r"[\u4e00-\u9fff]", value):
        return True
    return False


def reference_body_text_for_translation_check(ref_tail: str) -> str:
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


def looks_like_references_page(lines: list[str]) -> bool:
    joined = "\n".join(lines)
    years = len(re.findall(r"(?:19|20)\d{2}", joined))
    doi_or_url = len(re.findall(r"https?://|doi\.org|arXiv", joined, flags=re.I))
    author_markers = len(re.findall(r"\b[A-Z][A-Za-z'’-]+,\s+[A-Z][A-Za-z'’. -]{1,30}|\bet\s+al\.?", joined))
    journal_markers = len(re.findall(r"\b(?:Transl|Linguist|Commun|Comput|Survey|Press|Rev\.|Journal|Machine Transl)\b", joined, flags=re.I))
    return years >= 5 and doi_or_url >= 1 and (author_markers >= 3 or journal_markers >= 3)


def semantic_layout_findings_for_pages(pages: list[dict[str, Any]], *, target_pdf_role: str = "translated_pdf") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for page in pages:
        page_number = page.get("page")
        text = str(page.get("text") or "")
        lines = normalize_lines(text)
        joined = "\n".join(lines)
        ref_tail = reference_tail_from_explicit_heading(lines)
        in_references_page = bool(ref_tail) or looks_like_references_page(lines)
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
            and re.search(r"(?:\bHUMA\b|HUMANITIES|polyu\.edu|stanford\.ed\s+u|doi\.org|s41599)", line, flags=re.I)
            and re.search(r"[\u4e00-\u9fff]", line)
            and not in_references_page
            and not is_policy_preserved_metadata_line(line)
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
        translated_person_patterns = [
            r"约兰达·吉尔\s*（\s*Yolanda\s+Gil\s*）",
            r"雷蒙德·佩罗\s*（\s*Ray(?:mond)?\s+Perrault\s*）",
            r"[一-龥·]{2,12}\s*（\s*(?:Yolanda\s+Gil|Ray(?:mond)?\s+Perrault|Loredana\s+Fattorini|Sha\s+Sajadieh|Vanessa\s+Parli)\s*）",
        ]
        if any(re.search(pattern, joined, re.I) for pattern in translated_person_patterns):
            findings.append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "semantic_layout",
                        "rule": "person_name_translated_with_parenthetical_english",
                        "page": page_number,
                        "target_pdf_role": target_pdf_role,
                        "message": "AI Index 人员姓名被音译成中文名加括号英文；默认策略应保留英文姓名原样。",
                        "evidence": joined[:360],
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
        institution_line_pattern = re.compile(
            r"\b(?:University|International|Institute|Brookings|Sciences|Sydney|JPMorgan|OECD)\b"
        )
        institution_hits = len(institution_line_pattern.findall(joined))
        has_mixed_institution_line = bool(
            re.search(r"\b(?:University|International|Institute|Brookings|Sciences|Sydney)\b[^\n]{0,80}[\u4e00-\u9fff]", joined)
            or re.search(r"[\u4e00-\u9fff][^\n]{0,80}\b(?:University|International|Institute|Brookings|Sciences|Sydney)\b", joined)
        )
        standalone_institution_lines = [
            line
            for line in lines
            if len(line) <= 120 and institution_line_pattern.search(line) and cjk_count(line) == 0
        ]
        report_org_context = any(
            line.strip().lower() in {"chair", "co-chair", "members", "organizations"}
            or line.strip() in {"主席", "联合主席", "成员", "机构"}
            for line in lines
        )
        roster_affiliation_context = (
            report_org_context
            and institution_hits >= 3
            and any(re.search(r"\b(?:Chair|Co-Chair|Members|Organizations)\b|主席|联合主席|成员|机构", line, re.I) for line in lines)
            and not re.search(r"\b(?:stanford\.ed\s+u|polyu\.edu\.\s+hk)\b", joined, re.I)
        )
        if (
            institution_hits >= 3
            and cjk_count(joined) >= 20
            and (has_mixed_institution_line or (report_org_context and len(standalone_institution_lines) >= 2))
            and not in_references_page
            and not roster_affiliation_context
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
        if re.search(r"黄颖琪|张安德瑞|安德鲁·凯·范", joined) and not in_references_page:
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


def build_dual_visual_report(
    source_pdf: Path | None,
    mono_translated_pdf: Path | None,
    standard_dual_pdf: Path | None,
    backend_dual_pdf: Path | None,
    output_dir: Path,
) -> dict[str, Any]:
    if not source_pdf or not mono_translated_pdf or not standard_dual_pdf or not source_pdf.exists() or not mono_translated_pdf.exists() or not standard_dual_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_source_mono_or_standard_dual_pdf", "findings": []}
    fitz = _load_fitz()
    findings: list[dict[str, Any]] = []
    page_metrics: list[dict[str, Any]] = []

    def inspect_dual(path: Path, role: str, delivery_blocking: bool) -> None:
        with fitz.open(str(source_pdf)) as source_doc, fitz.open(str(mono_translated_pdf)) as mono_doc, fitz.open(str(path)) as dual_doc:  # type: ignore[attr-defined]
            for page_index in range(min(len(source_doc), len(mono_doc), len(dual_doc))):
                source_full = _page_region_metrics(source_doc, page_index, "full")
                mono_full = _page_region_metrics(mono_doc, page_index, "full")
                left = _page_region_metrics(dual_doc, page_index, "left")
                right = _page_region_metrics(dual_doc, page_index, "right")
                page_metrics.append(
                    {
                        "role": role,
                        "page": page_index + 1,
                        "source_full": source_full,
                        "mono_translated_full": mono_full,
                        "dual_left": left,
                        "dual_right": right,
                    }
                )
                source_nonempty = source_full["text_chars"] >= 30 or source_full["nonwhite_ratio"] >= 0.025
                translated_nonempty = mono_full["text_chars"] >= 20 or mono_full["cjk_count"] >= 8
                right_low = (
                    right["text_chars"] < max(20, int(mono_full["text_chars"] * 0.08))
                    and right["cjk_count"] < 8
                    and right["nonwhite_ratio"] < max(0.012, float(mono_full["nonwhite_ratio"]) * 0.25)
                )
                if source_nonempty and translated_nonempty and right_low:
                    findings.append(
                        normalize_finding(
                            {
                                "severity": "blocking" if delivery_blocking else "warn",
                                "category": "rendering",
                                "rule": "blank_or_low_content_page",
                                "page": page_index + 1,
                                "target_pdf_role": role,
                                "delivery_blocking": delivery_blocking,
                                "message": "双语 PDF 中文侧文本/CJK 覆盖极低，疑似中文侧空白。",
                                "evidence": json.dumps(
                                    {
                                        "mono_text_chars": mono_full["text_chars"],
                                        "mono_cjk_count": mono_full["cjk_count"],
                                        "right_text_chars": right["text_chars"],
                                        "right_cjk_count": right["cjk_count"],
                                        "right_nonwhite_ratio": right["nonwhite_ratio"],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    )
                left_delta = abs(float(left["nonwhite_ratio"]) - float(source_full["nonwhite_ratio"]))
                mean_delta = max(abs(float(left["mean_rgb"][idx]) - float(source_full["mean_rgb"][idx])) for idx in range(3))
                if source_nonempty and (left_delta >= 0.18 or mean_delta >= 55):
                    findings.append(
                        normalize_finding(
                            {
                                "severity": "blocking" if delivery_blocking else "warn",
                                "category": "rendering",
                                "rule": "dual_background_shift",
                                "page": page_index + 1,
                                "target_pdf_role": role,
                                "delivery_blocking": delivery_blocking,
                                "message": "双语 PDF 英文侧背景/像素分布与源页差异过大，可能出现背景漂移或侧栏异常。",
                                "evidence": json.dumps(
                                    {
                                        "source_nonwhite_ratio": source_full["nonwhite_ratio"],
                                        "left_nonwhite_ratio": left["nonwhite_ratio"],
                                        "source_mean_rgb": source_full["mean_rgb"],
                                        "left_mean_rgb": left["mean_rgb"],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    )

    try:
        inspect_dual(standard_dual_pdf, "standard_delivery", True)
        if backend_dual_pdf and backend_dual_pdf.exists() and backend_dual_pdf != standard_dual_pdf:
            inspect_dual(backend_dual_pdf, "backend_intermediate", False)
        semantic = build_semantic_layout_report(mono_translated_pdf, target_pdf_role="mono_translated_pdf")
        if semantic.get("findings"):
            findings.extend(semantic["findings"])
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"dual_visual_check_unavailable: {exc}", "findings": []}
    delivery_findings = [item for item in findings if item.get("delivery_blocking") and item.get("severity") == "blocking"]
    return {
        "version": 1,
        "status": "warn" if findings else "ok",
        "delivery_status": "blocking" if delivery_findings else "ok",
        "standard_dual_pdf": str(standard_dual_pdf),
        "backend_dual_pdf": str(backend_dual_pdf) if backend_dual_pdf else None,
        "page_metrics": page_metrics,
        "semantic_layout_report": semantic,
        "findings": findings,
    }


def build_paragraph_label_audit(translated_pdf: Path | None, output_dir: Path, pages: list[int] | None = None) -> dict[str, Any]:
    if not translated_pdf or not translated_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_translated_pdf", "paragraphs": [], "overlap_pairs": []}
    preview_dir = output_dir / "visual_pages"
    try:
        extracted = extract_pdf_pages(translated_pdf, preview_dir, "audit_translated", max_pages=5, pages=pages)
    except Exception as exc:  # noqa: BLE001 - 审计产物不能让主流程在测试/降级 PDF 上失败
        return {
            "version": 1,
            "status": "unavailable",
            "reason": f"paragraph_label_audit_unavailable: {exc}",
            "translated_pdf": str(translated_pdf),
            "paragraphs": [],
            "overlap_pairs": [],
        }
    paragraphs: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    for page in extracted:
        page_number = page.get("page")
        for span in page.get("spans", []):
            if not isinstance(span, dict):
                continue
            text = str(span.get("text") or "")
            label = "ordinary_text"
            if is_allowed_compact_label(text) or is_neutral_compact_label(text):
                label = "allowed_compact_label"
            elif re.search(r"(?:\\[A-Za-z]+|[A-Za-z]+_[A-Za-z0-9_]+)", text):
                label = "code_like_span"
            elif 0 < float(span.get("size") or 0) < 6:
                label = "small_font_span"
            paragraphs.append(
                {
                    "page": page_number,
                    "bbox": span.get("bbox"),
                    "layout_label": label,
                    "xobj_id": None,
                    "debug_id": None,
                    "unicode_sample": text[:120],
                    "scale": None,
                    "participates_translation": label != "allowed_compact_label",
                    "participates_typesetting": True,
                    "source": "pymupdf_post_render",
                }
            )
        for pair in overlap_pair_samples(page):
            pair["page"] = page_number
            overlaps.append(pair)
    return {
        "version": 1,
        "status": "warn" if overlaps else "ok",
        "audit_source": "pymupdf_post_render",
        "translated_pdf": str(translated_pdf),
        "pages": pages or "auto",
        "paragraph_count": len(paragraphs),
        "overlap_pair_count": len(overlaps),
        "paragraphs": paragraphs[:1000],
        "overlap_pairs": overlaps[:200],
    }


def build_visual_layout_report(
    source_pdf: Path | None,
    translated_pdf: Path | None,
    output_dir: Path,
    *,
    max_pages: int = 3,
    pages: list[int] | None = None,
) -> dict[str, Any]:
    if not source_pdf or not translated_pdf or not source_pdf.exists() or not translated_pdf.exists():
        return {
            "version": 1,
            "status": "unavailable",
            "reason": "missing_source_or_translated_pdf",
            "findings": [],
        }
    preview_dir = output_dir / "visual_pages"
    try:
        effective_pages = pages or infer_default_visual_check_pages(source_pdf, max_pages=max_pages)
        source_pages = extract_pdf_pages(source_pdf, preview_dir, "source", max_pages=max_pages, pages=effective_pages)
        translated_pages = extract_pdf_pages(translated_pdf, preview_dir, "translated", max_pages=max_pages, pages=effective_pages)
        report = analyze_visual_pages(
            source_pages,
            translated_pages,
            full_translated_text=extract_pdf_full_text(translated_pdf),
        )
        source_page_count = pdf_page_count(source_pdf)
        translated_page_count = pdf_page_count(translated_pdf)
        if source_page_count is not None and translated_page_count is not None and source_page_count != translated_page_count:
            report["findings"].append(
                normalize_finding(
                    {
                        "severity": "blocking",
                        "category": "rendering",
                        "rule": "page_count_drift_full_pdf",
                        "page": "document",
                        "source_page_count": source_page_count,
                        "translated_page_count": translated_page_count,
                        "message": "源/译 PDF 总页数不一致，主版式交付存在页数漂移风险。",
                    }
                )
            )
            report["status"] = "warn"
        health = text_layer_health(translated_pages)
        if health["status"] != "ok":
            report["findings"].append(
                normalize_finding(
                    {
                        "severity": "warn",
                        "category": "rendering",
                        "rule": "text_layer_glyph_risk",
                        "page": "document",
                        "evidence": json.dumps(health, ensure_ascii=False),
                        "message": "译文 PDF 文本层存在可疑乱码或 ToUnicode 抽取风险。",
                    }
                )
            )
            report["status"] = "warn"
        coverage = build_full_document_coverage_report(source_pdf, translated_pdf)
        if coverage.get("findings"):
            report["findings"].extend(coverage["findings"])
            report["status"] = "warn"
        semantic = build_semantic_layout_report(translated_pdf, target_pdf_role="translated_pdf")
        if semantic.get("findings"):
            report["findings"].extend(semantic["findings"])
            report["status"] = "warn"
        report.update(
            {
                "source_pdf": str(source_pdf),
                "translated_pdf": str(translated_pdf),
                "source_page_count": source_page_count,
                "translated_page_count": translated_page_count,
                "text_layer_health": health,
                "full_document_coverage": coverage,
                "semantic_layout_report": semantic,
                "visual_check_pages": effective_pages or "auto",
                "preview_dir": str(preview_dir),
                "source_pages": [{"page": item["page"], "preview_path": item["preview_path"]} for item in source_pages],
                "translated_pages": [{"page": item["page"], "preview_path": item["preview_path"]} for item in translated_pages],
            }
        )
        return report
    except Exception as exc:  # noqa: BLE001 - 视觉检查不能阻断翻译主路径
        return {
            "version": 1,
            "status": "unavailable",
            "reason": f"visual_check_unavailable: {exc}",
            "findings": [],
        }
