# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation fidelity：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def check_faithfulness_markers(source: str, translation: str, *, block_id: str = "") -> list[Issue]:
    from check_translation_core import excerpt
    issues: list[Issue] = []
    # These are bounded review hints, not a cross-language claim aligner.
    # Do not apply absence-of-marker inference to a whole multi-page document.
    short_context = len(source) <= 500 and len(translation) <= 400
    modal_effect = re.search(
        r"\b(may|might|could|can)\s+"
        r"(?:(?:potentially|possibly|sometimes|also|only|even|slightly)\s+){0,2}"
        r"(?:improve|increase|reduce|decrease|enhance|lead|help|restrict|affect|impact|outperform|surpass|exceed)\b",
        source, re.I)
    retained_modal = re.search(
        r"可能|或许|也许|大概|可以|能够|有能力|有望|不排除|未必|不一定|似乎|或可|或能|或将|或会|有助于|假[说设]|推测|推断|猜测|估计"
        r"|具[有备][^。；;!?！？\n]{0,40}能力"
        r"|(?:(?<![性功技潜才本节效动热电智势储])能|可)(?:提高|改善|提升|增加|减少|降低|增强|导致|帮助|限制|影响|优于|超越|超过|胜过|达到|实现|使|让|将|把)"
        r"|\b(?:may|might|could|can)\b", translation, re.I)
    legacy_explicit_strengthening = bool(
        re.search(r"\b(may|might|could)\s+(improve|increase|reduce|decrease|enhance|lead|help)\b", source, re.I)
        and re.search(r"会提高|会改善|会增加|会减少|会降低|会增强|会导致|必然|一定", translation))
    if modal_effect and (short_context or legacy_explicit_strengthening) and translation.strip():
        if not retained_modal:
            issues.append(
                Issue(
                    "medium",
                    "保守措辞被强化",
                    "源文包含效果或能力限定，译文疑似未保留对应标记；短段缺失或既有显式强化词仅构成作用域审校线索。",
                    category="accuracy",
                    source_evidence=modal_effect.group(0),
                    translation_evidence=excerpt(translation),
                    suggestion="保留“可能、或许、提示、表明”等保守语气，不要强化成确定因果或确定收益。",
                    block_id=block_id,
                    rule="modality_drift",
                )
            )
    hypothesis = re.search(
        r"\b(?:(?:we|I|the\s+authors?)\s+hypothesi[sz](?:e|ed)|"
        r"it\s+(?:is|was)\s+hypothesi[sz]ed)\s+that\b", source, re.I)
    if hypothesis and short_context and translation.strip() and not re.search(
        r"假[说设]|推测|猜测|猜想|臆测|推断|估计|可能|或许|也许|似乎|\bhypothes\w*\b", translation, re.I
    ):
        issues.append(Issue(
            "medium", "假说限定可能缺失",
            "源文明确提出假说，短译段未见假设或推测标记；不能据此自动改写译文。",
            category="accuracy", source_evidence=hypothesis.group(0), translation_evidence=excerpt(translation),
            suggestion="核对主张力度及作用域；保留假说身份，允许等义改写，并记录人工裁决。",
            block_id=block_id, rule="evidence_strength_drift"))
    comparative = re.search(r"\b(?:better|higher|lower|improved)\b", source, re.I)
    added_degree = re.search(r"显著|大幅|极大", translation)
    explicit_degree = re.search(
        r"\b(?:significant\w*|substantial\w*|considerabl\w*|marked\w*|dramatic\w*|"
        r"extreme\w*|great\w*|large\w*|strong\w*|pronounced|much|far|clearly|notably|appreciabl\w*)\b",
        source, re.I)
    if short_context and comparative and added_degree and not explicit_degree:
        issues.append(Issue(
            "medium", "比较结果可能新增程度限定",
            "源文短片段包含比较表达，但未见支持译文显著/大幅/极大的程度词；此项不判断统计显著性。",
            category="accuracy", source_evidence=excerpt(source), translation_evidence=excerpt(translation),
            suggestion="对照完整主张及上下文，确认程度限定有来源；不自动删词或认定整句错误。",
            block_id=block_id, rule="evidence_strength_drift"))
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
    from check_translation_core import excerpt
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
    from check_translation_core import excerpt
    from check_translation_terms import extract_percentages
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
                rule="percentage_value_missing",
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
                rule="percentage_value_added",
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
                rule="percentage_value_split",
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
            + [Issue(**finding) for finding in invariant_findings(source, translation)]
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
        issues.extend(Issue(**finding, block_id=block_id) for finding in invariant_findings(block_source, block_translation))
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
    from check_translation_core import excerpt
    issues: list[Issue] = []
    spans = protected_spans.get("spans")
    if not isinstance(spans, list):
        return issues
    translation_by_block = {
        str(record.get("block_id") or ""): str(record.get("translation") or "")
        for record in (translation_blocks or [])
        if isinstance(record, dict)
    }
    strict_kinds = {"url", "doi", "citation", "inline_math", "display_math", "latex_command", "inline_code", "code_block"}
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
                    "high" if kind in {"doi", "url", "inline_math", "display_math", "latex_command"} else "medium",
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


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
