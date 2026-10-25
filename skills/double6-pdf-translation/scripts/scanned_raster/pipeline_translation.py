# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline translation：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def _split_translation_for_regions(translation: str, regions: list[dict[str, Any]]) -> list[str]:
    if len(regions) <= 1:
        return [translation]
    weights = [max(1, len(re.sub(r"\s+", "", str(item.get("ocr_text") or "")))) for item in regions]
    total_weight = sum(weights)
    length = len(translation)
    parts: list[str] = []
    start = 0
    cumulative = 0
    for index, weight in enumerate(weights[:-1]):
        cumulative += weight
        target = max(start + 1, min(length, round(length * cumulative / total_weight)))
        if target < length:
            nearby = [
                pos
                for pos in range(max(start + 1, target - 5), min(length, target + 6))
                if translation[pos - 1] in "，。；！？、：,.;!? ”’"
            ]
            if nearby:
                target = min(nearby, key=lambda pos: abs(pos - target))
        parts.append(translation[start:target].strip())
        start = target
    parts.append(translation[start:].strip())
    return parts

def _selected_pages(route_manifest: dict[str, Any], pages_argument: str | None) -> list[int]:
    candidates = [int(value) for value in route_manifest.get("raster_candidate_pages") or []]
    if not pages_argument:
        return candidates
    selected: set[int] = set()
    for chunk in pages_argument.split(","):
        value = chunk.strip()
        if not value:
            continue
        if "-" in value:
            left, right = value.split("-", 1)
            selected.update(range(int(left), int(right) + 1))
        else:
            selected.add(int(value))
    return [page for page in candidates if page in selected]

def _default_translate(text: str, args: Any) -> str:
    import qwen_pdf2zh_cli_translator

    if not hasattr(args, "system_prompt"):
        args.system_prompt = getattr(args, "custom_system_prompt", "")
    if not hasattr(args, "max_tokens"):
        args.max_tokens = getattr(args, "cli_max_tokens", 4096)
    if not hasattr(args, "reasoning_effort"):
        args.reasoning_effort = getattr(args, "openai_reasoning_effort", "none")
    if not hasattr(args, "context_file"):
        args.context_file = None
    if "hy-mt" in str(getattr(args, "model", "")).lower():
        args.top_p = getattr(args, "top_p", 1.0)
        args.top_k = getattr(args, "top_k", -1)
        args.repetition_penalty = getattr(args, "repetition_penalty", 1.0)
    return qwen_pdf2zh_cli_translator.translate(text, args)

def _unwrap_latex_text_commands(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = LATEX_FRAC_RE.sub(r"\1/\2", current)
        current = LATEX_WRAPPER_RE.sub(r"\1", current)
    return current

def _normalize_inline_math_for_text_layer(text: str) -> str:
    """Keep prose variables readable in a PDF text layer without TeX rendering."""
    normalized = text.translate(SUBSCRIPT_DIGIT_TRANSLATION)
    # CJK 正文字体不保证覆盖 Unicode 字母下标（如 Lotka 的 Sₙ/Xₙ）。
    # 与数字下标及 TeX _{n} 同样展平，避免写入缺字而丢失变量身份。
    normalized = normalized.translate(str.maketrans("ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ", "aehijklmnoprstuvx"))
    # 当前纯文本字体的 Unicode 数字下标/撇号会被分离排版；统一为连续的
    # ASCII 科学变量串，保留撇号个数，避免 A₁″ 被拆成多个字体片段。
    normalized = normalized.replace("‴", "'''").replace("″", "''").replace("′", "'")
    normalized = normalized.replace("$", "")
    normalized = normalized.replace(r"\(", "").replace(r"\)", "")
    normalized = normalized.replace(r"\[", "").replace(r"\]", "")
    normalized = _unwrap_latex_text_commands(normalized)
    normalized = re.sub(
        r"\^\s*\{\s*([0-9+-]+)\s*\}",
        lambda match: match.group(1).translate(SUPERSCRIPT_DIGITS),
        normalized,
    )
    normalized = re.sub(
        r"\^\s*([0-9+-]+)",
        lambda match: match.group(1).translate(SUPERSCRIPT_DIGITS),
        normalized,
    )
    normalized = re.sub(r"_\s*\{\s*\\circ\s*\}", "°", normalized)
    normalized = re.sub(r"_\s*\{\s*\\bullet\s*\}", "•", normalized)
    def macron(match: re.Match[str]) -> str:
        letter = match.group(1)
        return PRECOMPOSED_MACRONS.get(letter, f"{letter}̄")

    normalized = re.sub(r"\\bar\s*\{\s*([A-Za-z])\s*\}", macron, normalized)
    normalized = re.sub(r"\\overline\s*\{+\s*([A-Za-z])\s*\}+", macron, normalized)
    normalized = re.sub(r"\^\s*\{\s*\\prime\s+\\prime\s*\}", "''", normalized)
    normalized = re.sub(r"\^\s*\{\s*\\prime\s*\}", "'", normalized)
    normalized = re.sub(r"_\s*\{\s*([0-9A-Za-z]+)\s*\}", r"\1", normalized)
    normalized = re.sub(r"_\s*([0-9]+)", r"\1", normalized)
    normalized = normalized.replace(r"\pm", "±")
    for latex, symbol in sorted(INLINE_LATEX_SYMBOLS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(latex, symbol)
    normalized = LATEX_SPACING_RE.sub(" ", normalized)
    normalized = _unwrap_latex_text_commands(normalized)
    normalized = LATEX_LEFTOVER_COMMAND_RE.sub("", normalized)
    normalized = normalized.replace(r"\_", "_")
    normalized = re.sub(r"\{\s*([^{}]{1,8})\s*\}", r"\1", normalized)
    return re.sub(r"[ \t]+", " ", normalized).strip()

def _fixed_structured_field_translation(source: str) -> str | None:
    """栏位和固定抬头能确定译法时直接给出；对不上返回 None，留给模型。"""
    normalized_source = " ".join(source.split())
    normalized_source = re.sub(r"^[\"'‘’“”|]+\s*", "", normalized_source)
    normalized_source = re.sub(r"^[iI]\s+(?=Examiner\s*:)", "", normalized_source)
    exact_headings = {
        "in the united states patent and trademark office": "美国专利商标局",
        "information disclosure statement": "信息披露声明",
    }
    fixed_heading = exact_headings.get(normalized_source.casefold())
    if fixed_heading:
        return fixed_heading
    patterns = (
        (r"(?i)^Applicant:\s*(.+)$", "申请人：{}"),
        (r"(?i)^Assignee:\s*(.+)$", "受让人：{}"),
        (r"(?i)^Examiner:\s*(?!.*Group Art Unit:)(.+)$", "审查员：{}"),
        (r"(?i)^Group Art Unit:\s*(.+)$", "技术组：{}"),
        (r"(?i)^Serial No\.:\s*(.+)$", "序列号：{}"),
        (r"(?i)^Attorney Docket No\.:\s*(.+)$", "律师案卷号：{}"),
    )
    for pattern, template in patterns:
        match = re.fullmatch(pattern, normalized_source)
        if match:
            value = match.group(1).strip()
            if value.casefold() == "unknown":
                value = "未知"
            return template.format(value)
    examiner = re.fullmatch(
        r"(?i)^Examiner:\s*(.*?)\s+Group Art Unit:\s*(.+)$",
        normalized_source,
    )
    if examiner:
        examiner_name = "未知" if examiner.group(1).casefold() == "unknown" else examiner.group(1)
        art_unit = "未知" if examiner.group(2).casefold() == "unknown" else examiner.group(2)
        return f"审查员：{examiner_name}　技术组：{art_unit}"
    if normalized_source.casefold() == "sir:":
        return "先生："
    return None


def _fixed_scan_translation(text: str) -> str | None:
    """整段就是固定短句或栏位时返回确定译文，否则返回 None。"""
    compact = COMPACT_CONNECTIVE_TRANSLATIONS.get(" ".join(text.split()).casefold())
    if compact:
        return compact
    return _fixed_structured_field_translation(text)


def _normalize_structured_field_translation(source: str, translation: str) -> str:
    """Keep identifiers and named parties intact in common formal-document fields."""
    return _fixed_structured_field_translation(source) or translation

def _clip_rect_against_protected(rect: Any, protected_rects: list[Any]) -> tuple[Any, list[list[float]]]:
    """Keep the largest axis-aligned part of a text region outside protected content."""
    import fitz

    safe = fitz.Rect(rect)
    clipped_by: list[list[float]] = []
    for protected in protected_rects:
        protected_rect = fitz.Rect(protected)
        intersection = safe & protected_rect
        if intersection.is_empty or intersection.get_area() <= 0:
            continue
        candidates = [
            fitz.Rect(safe.x0, safe.y0, safe.x1, intersection.y0),
            fitz.Rect(safe.x0, intersection.y1, safe.x1, safe.y1),
            fitz.Rect(safe.x0, safe.y0, intersection.x0, safe.y1),
            fitz.Rect(intersection.x1, safe.y0, safe.x1, safe.y1),
        ]
        viable = [candidate for candidate in candidates if candidate.width >= 2 and candidate.height >= 2]
        if not viable:
            return fitz.Rect(), clipped_by + [[*protected_rect]]
        safe = max(viable, key=lambda candidate: candidate.get_area())
        clipped_by.append([*protected_rect])
    return safe, clipped_by

def _translate_regions(regions: list[dict[str, Any]], args: Any, translator: Translator) -> list[str]:
    from scanned_raster.pipeline_ocr_groups import _join_ocr_group_text
    failures: list[str] = []
    pending_groups: dict[str, list[dict[str, Any]]] = {}
    for region in regions:
        if region.get("source_column_ambiguity"):
            region.update(status="failed", skip_reason="source_column_order_unresolved", in_destroke_mask=False)
            failures.append(str(region.get("region_id")))
            continue
        if region.get("name_column_ambiguity"):
            region.update(status="failed", skip_reason="unresolved_scientific_name_column", in_destroke_mask=False)
            failures.append(str(region.get("region_id")))
            continue
        text = str(region.get("ocr_text") or "").strip()
        role = str(region.get("layout_role") or "unknown")
        author_line = bool(re.fullmatch(r"BY\s+[A-Z][A-Z .,'’\-]+", text))
        vertical_reason = vertical_margin_reason(region)
        scientific_name = region.get("structured_name_column") == "scientific"
        if text and role in SEARCH_LAYER_PROTECTED_ROLES:
            region["search_layer_required"] = True
            fixed_search = _fixed_scan_translation(text)
            try:
                if fixed_search is not None:
                    search_translation = _normalize_inline_math_for_text_layer(fixed_search)
                    region["search_layer_source"] = "fixed_phrase"
                else:
                    search_translation = _normalize_inline_math_for_text_layer(
                        translator(text, args).strip()
                    )
            except Exception as exc:  # noqa: BLE001
                search_translation = ""
                region.update(search_layer_status="failed", search_layer_error=str(exc))
                failures.append(str(region.get("region_id")))
            if search_translation:
                region.update(
                    search_layer_translation=search_translation,
                    search_layer_status="translation_ready",
                )
            elif region.get("search_layer_status") != "failed":
                region.update(search_layer_status="failed", search_layer_error="translation_empty")
                failures.append(str(region.get("region_id")))
        if not text or role in PROTECTED_LAYOUT_ROLES or author_line or vertical_reason or scientific_name:
            protected_reason = f"protected_layout_role:{role}" if role in PROTECTED_LAYOUT_ROLES else "empty_text"
            if author_line:
                protected_reason = "protected_author_line"
            elif vertical_reason:
                protected_reason = vertical_reason
            elif scientific_name:
                protected_reason = "protected_scientific_name_column"
            region.update(
                status="protected",
                skip_reason=protected_reason,
                translation=None,
                in_destroke_mask=False,
            )
            continue
        candidate_group = str(region.get("translation_group_id") or "")
        group_id = (
            candidate_group
            if region.get("engine") == "rapidocr" and "-rg" in candidate_group
            else str(region.get("region_id"))
        )
        pending_groups.setdefault(group_id, []).append(region)

    for grouped_regions in pending_groups.values():
        text = _join_ocr_group_text(grouped_regions)
        fixed = _fixed_scan_translation(text)
        if fixed is not None:
            raw_translation = fixed
            translation = _normalize_inline_math_for_text_layer(fixed)
            for region in grouped_regions:
                region["translation_source"] = "fixed_phrase"
        else:
            try:
                translation = translator(text, args).strip()
            except Exception as exc:  # noqa: BLE001
                for region in grouped_regions:
                    region.update(status="failed", skip_reason=f"translation_failed:{exc}", in_destroke_mask=False)
                    failures.append(str(region.get("region_id")))
                continue
            if not translation:
                for region in grouped_regions:
                    region.update(status="failed", skip_reason="translation_empty", in_destroke_mask=False)
                    failures.append(str(region.get("region_id")))
                continue
            raw_translation = translation
            translation = _normalize_inline_math_for_text_layer(translation)
            translation = _normalize_structured_field_translation(text, translation)
            # Structured-field rewrites and future translator adapters must never
            # reintroduce TeX markup into the plain searchable PDF text layer.
            translation = _normalize_inline_math_for_text_layer(translation)
        translation = resolve_translation_alternatives(text, translation)
        integrity_findings = scientific_integrity_findings(text, translation)
        if integrity_findings:
            for region in grouped_regions:
                region.update(status="failed", skip_reason="scientific_integrity_failed", in_destroke_mask=False,
                              translation_raw=raw_translation, scientific_integrity_findings=integrity_findings)
                failures.append(str(region.get("region_id")))
            continue
        translations = _split_translation_for_regions(translation, grouped_regions)
        for region, part in zip(grouped_regions, translations, strict=True):
            if not part:
                region.update(status="protected", skip_reason="empty_group_split", in_destroke_mask=False)
                continue
            region.update(
                status="translated",
                translation=part,
                translation_raw=raw_translation,
                skip_reason=None,
                in_destroke_mask=True,
                mask_overlap_ratio=0.0,
            )
    return failures


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
