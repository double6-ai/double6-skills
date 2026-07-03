#!/usr/bin/env python3
from __future__ import annotations

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by check_translation.py for English residue, coverage, and protected span validation rules."

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_policies import *  # noqa: F401,F403

def is_allowed_technical_residue(translation: str, start: int, end: int) -> bool:
    """识别邮箱用户名、URL 路径和代码仓库 owner 这类应保留的英文片段。"""
    window = translation[max(0, start - 48) : min(len(translation), end + 48)].lower()
    before = translation[max(0, start - 16) : start]
    after = translation[end : min(len(translation), end + 32)]
    at_after = after.find("@")
    at_before = before.rfind("@")
    if at_after != -1 and not re.search(r"[\u4e00-\u9fff]", after[:at_after]):
        return True
    if at_before != -1 and not re.search(r"[\u4e00-\u9fff]", before[at_before + 1 :]):
        return True
    if re.search(r"https?://|www\.|github\.com|gitlab\.com|doi\.org", window):
        return True
    if re.search(r"\b[a-z0-9]+-[a-z0-9-]+\b", translation[start:end], re.I) and re.search(
        r"github\.com|gitlab\.com|bitbucket\.org",
        window,
    ):
        return True
    return False


def classify_english_residue(
    translation: str,
    *,
    protected_spans: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    allowed = {
        "abstract",
        "references",
        "doi",
        "url",
        "http",
        "https",
        "et",
        "al",
        "openai",
        "latextrans",
    }
    technical_policy_needed = {
        "caption",
        "captions",
        "environment",
        "environments",
        "eqnarray",
        "gpt-academic",
        "pdflatex",
        "pylatexenc",
        "subsection",
        "textbf",
    }
    protected = protected_values(protected_spans)
    term_terms = term_policy_terms(term_policy)
    entity_terms = entity_policy_terms(entity_map)
    must_translate_tokens = {
        "sub-corpus",
        "number",
        "texts",
        "tokens",
        "mean",
        "length",
        "translation",
        "profile",
        "dimensions",
        "continuing",
    }
    buckets: dict[str, list[str]] = {"must_translate": [], "allowed_keep": [], "needs_term_policy": []}
    for match in re.finditer(r"\b[A-Za-z][A-Za-z-]{2,}\b", translation):
        token = match.group(0)
        lower = token.lower()
        if lower in must_translate_tokens:
            bucket = "must_translate"
        elif token in protected or lower in allowed or is_allowed_technical_residue(translation, match.start(), match.end()):
            bucket = "allowed_keep"
        elif lower in technical_policy_needed:
            bucket = "needs_term_policy"
        elif lower in term_terms or lower in entity_terms or any(lower in term for term in term_terms | entity_terms):
            bucket = "needs_term_policy"
        elif token[:1].isupper() or token.isupper():
            bucket = "allowed_keep"
        elif len(token) >= 8:
            bucket = "must_translate"
        else:
            continue
        if token not in buckets[bucket]:
            buckets[bucket].append(token)
    return buckets


def is_likely_allowed_english_phrase(snippet: str) -> bool:
    """识别机构/委员名单等英文串，避免误判成普通 prose 漏译。"""
    words = re.findall(r"[A-Za-z][A-Za-z-]*", snippet)
    if len(words) < 4:
        return False
    role_markers = {
        "MEMBERS",
        "CO-CHAIR",
        "CHAIR",
        "LEAD",
        "EDITOR",
        "EDITOR-IN-CHIEF",
        "RESEARCH",
        "MANAGER",
        "UNDERGRADUATE",
        "GRADUATE",
        "AFFILIATED",
        "RESEARCHERS",
    }
    if any(marker in snippet for marker in role_markers):
        return True
    proper_like = sum(1 for word in words if word[:1].isupper() or word.isupper())
    lowercase_function_words = {
        word.lower()
        for word in words
        if word.islower() and word.lower() in {"of", "and", "for", "in", "on", "to", "the"}
    }
    content_lowercase = [word for word in words if word.islower() and word.lower() not in lowercase_function_words]
    return proper_like >= max(3, len(words) - 2) and len(content_lowercase) <= 1


def strip_role_passthrough_lines(text: str) -> str:
    """剔除按版式角色允许保留英文的 References 条目和 Example 对照行。"""
    kept: list[str] = []
    in_references = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower().strip(":：")
        if lowered in {"references", "参考文献"}:
            in_references = True
            kept.append(raw_line)
            continue
        if in_references and re.search(r"\(\d{4}\)|\bdoi\.org/|\b10\.\d{4,9}/|et al\.", line, re.I):
            continue
        if re.match(r"^(?:Example\s+\d+|ST|TT|HT|NMT-GT|LLM-[A-Za-z0-9-]+)\s*[:：]", line, re.I):
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def check_untranslated_english(
    translation: str,
    *,
    protected_spans: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    scan_text = strip_role_passthrough_lines(translation)
    candidates = []
    for match in re.finditer(r"\b[A-Za-z][A-Za-z-]+(?:\s+[A-Za-z][A-Za-z-]+){4,}\b", scan_text):
        snippet = " ".join(match.group(0).split())
        if (
            len(snippet) > 40
            and not re.search(r"https?://|doi\.org|et al|References", snippet, re.IGNORECASE)
            and not is_likely_allowed_english_phrase(snippet)
        ):
            candidates.append(snippet[:160])
    buckets = classify_english_residue(
        scan_text,
        protected_spans=protected_spans,
        entity_map=entity_map,
        term_policy=term_policy,
    )
    must_translate = buckets["must_translate"]
    needs_term_policy = buckets["needs_term_policy"]
    if candidates:
        issues.append(
            Issue(
                "medium",
                "疑似大段英文未翻译",
                "发现可能未翻译的英文片段：" + "；".join(candidates[:5]),
                category="omission",
                translation_evidence="；".join(candidates[:3]),
                suggestion="回看对应段落，确认是否为必须保留的原文；否则补译。",
            )
        )
    if must_translate:
        issues.append(
            Issue(
                "medium",
                "疑似英文单词残留（must_translate）",
                "译文中发现可能应翻译的英文单词：" + "；".join(must_translate[:8]),
                category="omission",
                translation_evidence="；".join(must_translate[:5]),
                suggestion="检查这些词是否为术语、代码或专名；若不是，应补译并重新抽取译文 PDF 文本。",
            )
        )
    if needs_term_policy:
        issues.append(
            Issue(
                "low",
                "英文残留待术语策略确认（needs_term_policy）",
                "这些英文片段命中术语/实体策略，需确认是保留英文还是补充中文定译：" + "；".join(needs_term_policy[:8]),
                category="terminology",
                translation_evidence="；".join(needs_term_policy[:5]),
                suggestion="补全 term_policy/entity_map 的保留、首次双语或中文化策略。",
            )
        )
    return issues


def check_sections(source: str, translation: str) -> list[Issue]:
    issues: list[Issue] = []
    source_headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", source)
    translation_headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", translation)
    if len(source_headings) >= 3 and len(translation_headings) < max(1, len(source_headings) // 2):
        issues.append(
            Issue(
                "medium",
                "章节结构可能缺失",
                f"源文有 {len(source_headings)} 个 Markdown 标题，译文只有 {len(translation_headings)} 个。",
                category="structure",
                source_evidence=", ".join(source_headings[:5]),
                translation_evidence=", ".join(translation_headings[:5]),
                suggestion="保留源文主要标题层级，或在译文中提供对应章节锚点。",
            )
        )
    if re.search(r"(?im)^#+\s*Abstract\b|^Abstract\b", source) and not re.search(r"摘要|Abstract", translation):
        issues.append(
            Issue(
                "low",
                "摘要标题缺失",
                "源文包含 Abstract，但译文中未找到“摘要”或 Abstract 标题。",
                category="structure",
                source_evidence="Abstract",
                suggestion="补充“摘要”标题或保留 Abstract 锚点。",
            )
        )
    return issues


def check_faithfulness_markers(source: str, translation: str, *, block_id: str = "") -> list[Issue]:
    issues: list[Issue] = []
    if re.search(r"\b(may|might|could)\s+(improve|increase|reduce|decrease|enhance|lead|help)\b", source, re.I):
        if re.search(r"会提高|会改善|会增加|会减少|会降低|会增强|会导致|必然|一定", translation):
            issues.append(
                Issue(
                    "medium",
                    "保守措辞被强化",
                    "源文包含 may/might/could + 效果动词的保守表达，但译文疑似改成确定结论。",
                    category="accuracy",
                    source_evidence="may / might / could + effect verb",
                    translation_evidence=excerpt(translation),
                    suggestion="保留“可能、或许、提示、表明”等保守语气，不要强化成确定因果或确定收益。",
                    block_id=block_id,
                    rule="modality_drift",
                )
            )
    if re.search(r"\b(suggests?|suggested|indicates?|indicated)\b", source, re.I):
        if re.search(r"证明|证实|确定|必然|一定|充分证明", translation):
            issues.append(
                Issue(
                    "medium",
                    "提示性表述被改成证明性结论",
                    "源文使用 suggest/indicate 等提示性表达，但译文疑似改成“证明/证实”等更强结论。",
                    category="accuracy",
                    source_evidence="suggest / indicate",
                    translation_evidence=excerpt(translation),
                    suggestion="保留“提示、表明、说明、可能意味着”等较弱表达，不要改成证明性结论。",
                    block_id=block_id,
                    rule="evidence_strength_drift",
                )
            )
    if re.search(r"\b(associated with|association with|correlated with|correlation between)\b", source, re.I):
        if re.search(r"导致|造成|引起|带来|使得", translation):
            issues.append(
                Issue(
                    "medium",
                    "相关关系被翻成因果关系",
                    "源文表达 association/correlation，但译文疑似改成导致、造成、引起等因果关系。",
                    category="accuracy",
                    source_evidence="associated with / correlated with",
                    translation_evidence=excerpt(translation),
                    suggestion="保留“相关、有关联、存在相关性”等表达，除非源文明示因果。",
                    block_id=block_id,
                    rule="causality_drift",
                )
            )
    if re.search(r"\b(cannot conclude|can not conclude|cannot be concluded|limited evidence|insufficient evidence|no evidence)\b", source, re.I):
        has_source_negation = re.search(r"\b(cannot|can not|no|insufficient|limited)\b", source, re.I)
        has_translation_negation = re.search(r"不能|无法|不足|有限|没有证据|证据不足|尚不能|不能得出", translation)
        if has_source_negation and not has_translation_negation:
            issues.append(
                Issue(
                    "high",
                    "证据限制或无法得出结论被弱化",
                    "源文包含 cannot conclude / limited evidence / insufficient evidence 等限制，但译文未保留限制。",
                    category="accuracy",
                    source_evidence="cannot conclude / limited evidence / insufficient evidence",
                    translation_evidence=excerpt(translation),
                    suggestion="明确保留“不能得出结论、证据有限、证据不足、没有证据”等限制。",
                    block_id=block_id,
                    rule="negation_drift",
                )
            )
    if re.search(r"\bdoes\s+not\s+guarantee\b|\bdo\s+not\s+guarantee\b|\bnot\s+guarantee\b", source, re.I):
        if "保证" in translation and not re.search(r"不保证|不能保证|并不保证|无法保证|未保证", translation):
            issues.append(
                Issue(
                    "high",
                    "否定保证关系被反转",
                    "源文明确写了 does not guarantee，但译文出现正向“保证”。",
                    category="accuracy",
                    source_evidence="does not guarantee",
                    translation_evidence=excerpt(translation),
                    suggestion="恢复否定范围，例如“并不保证……”或“不能保证……”。",
                    block_id=block_id,
                    rule="negation_drift",
                )
            )
    return issues


def has_reference_context(text: str) -> bool:
    return bool(
        re.search(r"\\(?:cite|citep|citet|ref|eqref)\{[^}]+\}", text)
        or re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
        or re.search(r"\barXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?", text, re.I)
        or re.search(r"\b[A-Z][A-Za-z-]+(?:\s+et\s+al\.)?\s*\(\d{4}\)", text)
        or re.search(r"\b(?:Figure|Fig\.|Table)\s+\d+[A-Za-z]?", text, re.I)
    )


def extract_protected_reference_values(text: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for pattern, kind in [
        (r"\\(?:cite|citep|citet|ref|eqref)\{[^}]+\}", "latex_reference"),
        (r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", "doi"),
        (r"\barXiv:\s*\d{4}\.\d{4,5}(?:v\d+)?", "arxiv"),
    ]:
        for match in re.finditer(pattern, text, re.I):
            values.append((kind, match.group(0).strip()))
    return values


def check_citation_claim_drift(source: str, translation: str, *, block_id: str = "") -> list[Issue]:
    issues: list[Issue] = []
    if not has_reference_context(source):
        return issues
    for kind, value in extract_protected_reference_values(source):
        if not protected_value_present(value, translation):
            issues.append(
                Issue(
                    "medium",
                    f"引用或标识符缺失: {kind}",
                    "源文 citation/ref/DOI/arXiv 等可回查标识在译文中未找到，可能破坏引用追踪。",
                    category="protected_span",
                    source_evidence=value,
                    translation_evidence=excerpt(translation),
                    suggestion="保留 citation/ref/DOI/arXiv 原文，或在译文中提供等价可回查标识。",
                    block_id=block_id,
                    rule="protected_citation_missing",
                )
            )
    if re.search(r"\b(suggests?|indicates?|may|might|could)\b", source, re.I) and re.search(
        r"证明|证实|确定|必然|一定|充分证明|会提高|会改善|会导致", translation
    ):
        issues.append(
            Issue(
                "medium",
                "引用上下文主张力度漂移",
                "源文在引用上下文中使用提示性或保守表达，但译文疑似改成证明性或确定性结论。",
                category="accuracy",
                source_evidence=excerpt(source),
                translation_evidence=excerpt(translation),
                suggestion="保留引用上下文中的主张力度，避免把引用支持关系从“提示/可能/相关”改成“证明/必然/因果”。",
                block_id=block_id,
                rule="citation_context_drift",
            )
        )
    if re.search(r"\b(?:Figure|Fig\.|Table)\s+\d+[A-Za-z]?", source, re.I) and re.search(
        r"证明|证实|因果|导致|造成|引起", translation
    ):
        issues.append(
            Issue(
                "medium",
                "图表引用主张漂移",
                "源文图表引用只应说明显示、比较或相关关系，译文疑似改成证明因果或结论。",
                category="accuracy",
                source_evidence=excerpt(source),
                translation_evidence=excerpt(translation),
                suggestion="图表引用应保留 show/indicate/association 的强度，除非源文明示 causal proof。",
                block_id=block_id,
                rule="figure_table_claim_drift",
            )
        )
    return issues


def check_quantitative_fidelity(source: str, translation: str, *, block_id: str = "") -> list[Issue]:
    issues: list[Issue] = []
    source_percentages = extract_percentages(source)
    translation_percentages = extract_percentages(translation)
    if not source_percentages and not translation_percentages:
        return issues
    source_set = set(source_percentages)
    translation_set = set(translation_percentages)
    missing = [value for value in source_percentages if value not in translation_set]
    additions = [value for value in translation_percentages if value not in source_set]
    if missing:
        issues.append(
            Issue(
                "high",
                "百分比数值漏译或改写",
                "源文包含百分比数值，但译文未保留对应数值。",
                category="accuracy",
                source_evidence=", ".join(missing),
                translation_evidence=excerpt(translation),
                suggestion="逐一核对百分比、范围和比较对象，避免改变实验结论。",
                block_id=block_id,
            )
        )
    if additions:
        issues.append(
            Issue(
                "high",
                "译文新增百分比数值",
                "译文出现源文中不存在的百分比，可能是数字事实幻觉或比较关系误译。",
                category="accuracy",
                source_evidence=", ".join(source_percentages) or "-",
                translation_evidence=", ".join(additions),
                suggestion="删除或改正源文中不存在的百分比，并复核“分别、翻倍、提高”等比较关系。",
                block_id=block_id,
            )
        )
    if len(source_percentages) == 1 and len(translation_percentages) > 1 and re.search(r"分别|respectively", translation, re.I):
        issues.append(
            Issue(
                "high",
                "单一百分比被拆成多个分别数值",
                "源文只有一个百分比，但译文使用“分别”等表达引入多个数值，可能改变实验结论。",
                category="accuracy",
                source_evidence=", ".join(source_percentages),
                translation_evidence=excerpt(translation),
                suggestion="按源文保留单一提升幅度，或明确说明该百分比适用的指标集合。",
                block_id=block_id,
            )
        )
    return issues


def check_block_faithfulness(
    source: str,
    translation: str,
    translation_blocks: list[dict[str, Any]],
) -> list[Issue]:
    if not translation_blocks:
        return (
            check_faithfulness_markers(source, translation)
            + check_quantitative_fidelity(source, translation)
            + check_citation_claim_drift(source, translation)
        )
    issues: list[Issue] = []
    for record in translation_blocks:
        if not isinstance(record, dict):
            continue
        block_id = str(record.get("block_id") or "")
        block_source = str(record.get("source_text") or "")
        block_translation = str(record.get("translation") or "")
        if not block_source or not block_translation:
            continue
        issues.extend(check_faithfulness_markers(block_source, block_translation, block_id=block_id))
        issues.extend(check_quantitative_fidelity(block_source, block_translation, block_id=block_id))
        issues.extend(check_citation_claim_drift(block_source, block_translation, block_id=block_id))
    return issues


def check_source_extraction_quality(manifest: dict[str, Any]) -> list[Issue]:
    quality = manifest.get("extraction_quality")
    if not isinstance(quality, dict) or quality.get("status") != "warn":
        return []
    examples = quality.get("suspicious_examples")
    evidence = ", ".join(str(item) for item in examples[:5]) if isinstance(examples, list) else ""
    return [
        Issue(
            "medium",
            "源文本抽取质量风险",
            "source_manifest 显示抽取文本疑似存在单词粘连、页眉页脚、元数据混排、异常 heading 或长 block，翻译质量需要和抽取质量分开判断。",
            category="source_quality",
            source_evidence=evidence,
            suggestion="先抽样核对 source.md；如确认粘连、双栏错序或元数据混排，应更换抽取器或重新 OCR/版面解析后再翻译。",
        )
    ]


def page_tail_map_from_manifest(manifest: dict[str, Any], limit: int = 80) -> dict[int, str]:
    page_text: dict[int, list[str]] = {}
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return {}
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("page"), int):
            continue
        page_text.setdefault(int(block["page"]), []).append(str(block.get("text") or ""))
    return {page: " ".join(parts).strip()[-limit:] for page, parts in page_text.items() if " ".join(parts).strip()}


def build_intra_page_continuity(manifest: dict[str, Any], translation: str = "") -> dict[str, Any]:
    tails = page_tail_map_from_manifest(manifest)
    if not tails or not translation.strip():
        return {"status": "not_checked", "checked_pages": [], "warnings": []}
    normalized_translation = re.sub(r"\s+", " ", translation)
    warnings = []
    for page, tail in sorted(tails.items()):
        anchors = re.findall(r"\b20\d{2}\b|\b[A-Za-z][A-Za-z-]{11,}\b", tail)
        anchors = anchors[-3:]
        if anchors and not any(anchor in normalized_translation for anchor in anchors):
            warnings.append(
                {
                    "page": page,
                    "source_tail": tail,
                    "missing_anchors": anchors,
                    "risk": "page_tail_not_found_in_translation_text",
                }
            )
    return {
        "status": "warn" if warnings else "ok",
        "checked_pages": sorted(tails),
        "warnings": warnings,
    }


def build_coverage_gate(manifest: dict[str, Any], translation: str = "") -> dict[str, Any]:
    blocks = manifest.get("blocks")
    blocks = blocks if isinstance(blocks, list) else []
    pages = sorted(
        {
            int(block.get("page"))
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("page"), int)
        }
    )
    page_count = int(manifest.get("page_count") or len(pages) or 0)
    missing_pages = [page for page in range(1, page_count + 1) if page not in pages] if page_count else []
    input_name = Path(str(manifest.get("input") or "")).name.lower()
    sample_match = re.search(r"(?:first|前)[_-]?(\d+)\s*p|first(\d+)p|_(\d+)p\b", input_name)
    requested_sample_pages = int(next(group for group in sample_match.groups() if group)) if sample_match else None
    boundary = "sample_boundary" if requested_sample_pages and page_count <= requested_sample_pages else "full_or_unknown"
    status = "ok"
    reasons: list[str] = []
    if missing_pages:
        status = "warn"
        reasons.append("missing_pages_in_source_blocks")
    if page_count and len(pages) < max(1, page_count // 2):
        status = "fail"
        reasons.append("low_page_block_coverage")
    if boundary == "sample_boundary":
        reasons.append("input_is_trimmed_sample")
    headings = [
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and str(block.get("element_type") or "") == "heading"
    ]
    intra_page = build_intra_page_continuity(manifest, translation)
    if intra_page.get("status") == "warn":
        status = "warn" if status == "ok" else status
        reasons.append("intra_page_tail_missing")
    return {
        "version": 1,
        "status": status,
        "boundary": boundary,
        "page_count": page_count,
        "covered_pages": pages,
        "missing_pages": missing_pages,
        "requested_sample_pages": requested_sample_pages,
        "source_block_count": len(blocks),
        "heading_count": len(headings),
        "intra_page_continuity": intra_page,
        "reasons": reasons,
    }


def check_source_coverage(manifest: dict[str, Any]) -> list[Issue]:
    gate = manifest.get("coverage_gate")
    gate = gate if isinstance(gate, dict) else build_coverage_gate(manifest)
    issues: list[Issue] = []
    if gate.get("boundary") == "sample_boundary":
        issues.append(
            Issue(
                "low",
                "评测样本页数边界",
                "输入文件名显示这是截取样本；后续页缺失应归因到评测边界，而不是翻译后端遗漏。",
                category="coverage",
                source_evidence=str(manifest.get("input") or ""),
                suggestion="报告覆盖度时明确 sample boundary；完整论文评测需换用完整 PDF。",
            )
        )
    intra_page = gate.get("intra_page_continuity")
    if isinstance(intra_page, dict) and intra_page.get("status") == "warn":
        warnings = intra_page.get("warnings")
        issues.append(
            Issue(
                "medium",
                "样本页内覆盖疑似截断",
                "输入可能是截取样本，但样本页内部的源文页尾锚点未在译文文本中找到。",
                category="coverage",
                source_evidence=json.dumps(warnings[:3], ensure_ascii=False) if isinstance(warnings, list) else "",
                suggestion="区分 sample boundary 与样本页内部漏译；复查对应页末尾是否被 PDF 渲染或抽取丢失。",
            )
        )
    missing_pages = gate.get("missing_pages")
    missing_pages = missing_pages if isinstance(missing_pages, list) else []
    if gate.get("status") == "warn" and missing_pages:
        issues.append(
            Issue(
                "medium",
                "源文页面覆盖存在缺口",
                "source_manifest 中部分页面没有可回查 block。",
                category="coverage",
                source_evidence=", ".join(str(item) for item in missing_pages[:10]),
                suggestion="核对 PDF 抽取和 layout_map；如为扫描页或复杂版面，考虑显式启用 OCR/layout。",
            )
        )
    if gate.get("status") == "fail":
        issues.append(
            Issue(
                "high",
                "源文页面覆盖不足",
                "source_manifest 的 block 页面覆盖明显不足，译文完整性无法可靠判断。",
                category="coverage",
                source_evidence=json.dumps(gate, ensure_ascii=False),
                suggestion="先修复源文抽取或 OCR，再执行翻译。",
            )
        )
    return issues


def check_protected_spans(
    translation: str,
    protected_spans: dict[str, Any],
    translation_blocks: list[dict[str, Any]] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    spans = protected_spans.get("spans")
    if not isinstance(spans, list):
        return issues
    translation_by_block = {
        str(record.get("block_id") or ""): str(record.get("translation") or "")
        for record in (translation_blocks or [])
        if isinstance(record, dict)
    }
    strict_kinds = {"url", "doi", "citation", "inline_math", "latex_command", "inline_code", "code_block"}
    for item in spans:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        value = str(item.get("value") or "")
        if not value or kind not in strict_kinds:
            continue
        block_id = str(item.get("block_id") or "")
        search_text = translation_by_block.get(block_id, translation)
        present_in_block = (
            protected_inline_code_present(value, search_text)
            if kind == "inline_code"
            else protected_value_present(value, search_text)
        )
        present_in_document = (
            protected_inline_code_present(value, translation)
            if kind == "inline_code"
            else protected_value_present(value, translation)
        )
        if not present_in_block and (search_text == translation or not present_in_document):
            issues.append(
                Issue(
                    "high" if kind in {"doi", "url", "inline_math", "latex_command"} else "medium",
                    f"不可翻译元素缺失: {kind}",
                    f"受保护元素 `{value}` 未在译文中原样出现。",
                    category="protected_span",
                    source_evidence=value,
                    translation_evidence=excerpt(search_text),
                    suggestion="恢复该元素原文，或在 manifest 中标注允许变更的理由。",
                    block_id=block_id,
                    page=str(item.get("page") or ""),
                )
            )
    return issues


def gate_status(render_manifest: dict[str, Any] | None, name: str) -> str:
    gates = ((render_manifest or {}).get("validation") or {}).get("gates")
    gate_items = gates.get("gates") if isinstance(gates, dict) else []
    for gate in gate_items if isinstance(gate_items, list) else []:
        if isinstance(gate, dict) and gate.get("name") == name:
            return str(gate.get("status") or "")
    return ""
