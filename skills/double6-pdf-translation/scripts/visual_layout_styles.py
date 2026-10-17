# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""visual layout styles：从原入口拆出的同一实现。"""
from __future__ import annotations
from visual_layout_context import *

def _visual_spans(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [span for span in page.get("spans", []) if isinstance(span, dict) and isinstance(span.get("bbox"), list)]

def _span_text(span: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(span.get("text") or "")).strip()

def _span_size(span: dict[str, Any]) -> float:
    return float(span.get("size") or 0)

def _bbox_center(span: dict[str, Any]) -> tuple[float, float] | None:
    bbox = span.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return ((float(bbox[0]) + float(bbox[2])) / 2.0, (float(bbox[1]) + float(bbox[3])) / 2.0)
    except (TypeError, ValueError):
        return None

def _select_spatially_matching_span(source_span: dict[str, Any], target_spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not target_spans:
        return None
    source_center = _bbox_center(source_span)
    if source_center is None:
        return target_spans[0]
    source_size = _span_size(source_span)

    def score(target_span: dict[str, Any]) -> float:
        target_center = _bbox_center(target_span)
        if target_center is None:
            return 1_000_000.0
        x_distance = abs(target_center[0] - source_center[0])
        y_distance = abs(target_center[1] - source_center[1])
        target_size = _span_size(target_span)
        size_gap = abs(target_size - source_size) if source_size > 0 and target_size > 0 else 0.0
        undersized_penalty = max(0.0, source_size * 0.86 - target_size) if source_size > 0 and target_size > 0 else 0.0
        # Heading false positives often come from running headers/footers that
        # reuse the same translated label. Vertical proximity is the strongest
        # signal that the target span is the corresponding body heading. When
        # visual repair paints a corrected heading over a stale tiny text layer,
        # both candidates are spatially close; in that case, prefer the span
        # whose size still preserves the source heading role.
        return y_distance * 4.0 + x_distance + size_gap * 2.0 + undersized_penalty * 8.0

    return min(target_spans, key=score)

def _is_regular_cjk_font(font: str) -> bool:
    lowered = font.lower()
    if "heiti" in lowered:
        return False
    return any(token in lowered for token in ["regular", "sourcehan", "song", "serifcn"]) and not any(
        token in lowered for token in ["bold", "heavy", "semibold", "medium"]
    )

def _is_cjk_body_font_for_mixed_latin(font: str) -> bool:
    lowered = font.lower()
    return "heiti" in lowered or _is_regular_cjk_font(font)

def _is_toc_like_page(page: dict[str, Any]) -> bool:
    text = str(page.get("text") or "").lower()
    return ("contents" in text or "目录" in text) and (
        len(re.findall(r"\bchapter\b|\bintroduction\b|\bappendix\b|\d{1,3}\b|第[一二三四五六七八九十]+章", text)) >= 3
    )

def _is_source_heading_weighted(span: dict[str, Any]) -> bool:
    lowered = str(span.get("font") or "").lower()
    try:
        flags = int(span.get("flags") or 0)
    except (TypeError, ValueError):
        flags = 0
    if lowered.startswith("advot") and flags & 4:
        return True
    return any(token in lowered for token in ["black", "bold", "heavy", "semibold", "medium"])

def _heading_size_regressed(source_size: float, target_size: float) -> bool:
    if source_size <= 0 or target_size <= 0:
        return False
    if source_size >= 24 and target_size >= 24 and target_size >= source_size * 0.75:
        return False
    return source_size >= 8.5 and target_size < source_size * 0.86

def source_translated_heading_style_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    source_spans = _visual_spans(source_page)
    translated_spans = _visual_spans(translated_page)
    skip_entry_style_checks = _is_toc_like_page(source_page) or _is_toc_like_page(translated_page)
    for source_span in source_spans:
        source_text = _span_text(source_span)
        target_text = HEADING_TRANSLATION_PAIRS.get(source_text.lower())
        if not target_text:
            continue
        if skip_entry_style_checks and source_text.lower() not in {"contents"}:
            continue
        target_candidates = [span for span in translated_spans if _span_text(span) == target_text]
        target_span = _select_spatially_matching_span(source_span, target_candidates)
        if not target_span:
            continue
        source_size = _span_size(source_span)
        target_size = _span_size(target_span)
        if _heading_size_regressed(source_size, target_size):
            evidence = {
                "source_text": source_text,
                "target_text": target_text,
                "source_size": round(source_size, 2),
                "target_size": round(target_size, 2),
                "source_font": source_span.get("font"),
                "target_font": target_span.get("font"),
                "source_bbox": source_span.get("bbox"),
                "target_bbox": target_span.get("bbox"),
            }
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "heading_font_size_regression",
                    "page": page_number,
                    "message": "译文章节标题字号相对源 PDF 明显变小，标题层级被弱化。",
                    "evidence": json.dumps(evidence, ensure_ascii=False),
                }
            )
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "font_size_regression",
                    "page": page_number,
                    "message": "译文字号相对源版式明显退化，不能仅因页面无重叠就判定视觉通过。",
                    "evidence": json.dumps(evidence, ensure_ascii=False),
                }
            )
        target_font = str(target_span.get("font") or "")
        if source_size >= 8.5 and _is_source_heading_weighted(source_span) and _is_regular_cjk_font(target_font):
            findings.append(
                {
                    "severity": "warn",
                    "category": "readability",
                    "rule": "heading_bold_style_drift",
                    "page": page_number,
                    "message": "源 PDF 标题为独立 heading 样式，译文使用普通 CJK 字体，疑似丢失加粗/标题层级。",
                    "evidence": json.dumps(
                        {
                            "source_text": source_text,
                            "target_text": target_text,
                            "source_size": round(source_size, 2),
                            "target_size": round(target_size, 2),
                            "source_font": source_span.get("font"),
                            "target_font": target_font,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
    return findings

def extract_latin_person_names(text: str) -> list[str]:
    names: list[str] = []
    excluded = {word.lower() for word in LATIN_NAME_EXCLUDE_WORDS}
    for part in re.split(r",|;|\band\b|\n", str(text or "")):
        normalized = re.sub(r"\s+", " ", part).strip().strip(".")
        if not normalized:
            continue
        words = normalized.split()
        for start in range(len(words)):
            for end in range(start + 2, min(len(words), start + 5) + 1):
                candidate = " ".join(words[start:end]).strip()
                if not LATIN_PERSON_NAME_RE.fullmatch(candidate):
                    continue
                if candidate in LATIN_PERSON_NAME_EXCLUDE_PHRASES:
                    continue
                candidate_words = [word.strip(".").lower() for word in candidate.split()]
                if any(word in excluded for word in candidate_words):
                    continue
                if candidate not in names:
                    names.append(candidate)
    return names

def source_translated_protected_name_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    from visual_layout_core import cjk_count
    from visual_layout_density import is_ai_roster_page_text
    source_text = str(source_page.get("text") or "")
    translated_text = str(translated_page.get("text") or "")
    roster_or_citation_context = (
        is_ai_roster_page_text(source_text)
        or is_ai_roster_page_text(translated_text)
        or re.search(r"\bContributors\b", source_text, re.I)
        or "贡献者" in translated_text
        or re.search(r"\bHow to cite\b", source_text, re.I)
        or "如何引用" in translated_text
    )
    if not roster_or_citation_context:
        return []
    source_names = extract_latin_person_names(source_text)
    if len(source_names) < 8:
        return []
    missing_names = [name for name in source_names if name not in translated_text]
    missing_ratio = len(missing_names) / max(len(source_names), 1)
    if missing_ratio < 0.24:
        return []
    evidence = {
        "source_name_count": len(source_names),
        "missing_name_count": len(missing_names),
        "missing_ratio": round(missing_ratio, 3),
        "source_name_samples": source_names[:16],
        "missing_name_samples": missing_names[:16],
        "translated_cjk_count": cjk_count(translated_text),
    }
    return [
        {
            "severity": "warn",
            "category": "semantic_layout",
            "rule": "protected_person_name_translation_drift",
            "page": page_number,
            "message": "源页含大量英文人名，但译文页缺失较多原文姓名，疑似人员名单被中文音译；AI Index roster/citation 人名应保留英文原样。",
            "evidence": json.dumps(evidence, ensure_ascii=False),
        },
        {
            "severity": "warn",
            "category": "semantic_layout",
            "rule": "person_name_passthrough_coverage_low",
            "page": page_number,
            "message": "人员名单英文姓名保留率不足，需按 protected span / roster role 检查翻译与写回。",
            "evidence": json.dumps(evidence, ensure_ascii=False),
        },
    ]


def source_translated_chart_title_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    source_text = str(source_page.get("text") or "")
    translated_text = str(translated_page.get("text") or "")
    findings: list[dict[str, Any]] = []
    for source_title, required_tokens in CHART_TITLE_TRANSLATION_REQUIREMENTS.items():
        if not re.search(re.escape(source_title), source_text, re.I):
            continue
        if all(token in translated_text for token in required_tokens):
            continue
        source_spans = [span for span in _visual_spans(source_page) if re.search(re.escape(source_title), _span_text(span), re.I)]
        title_y_values = [float((span.get("bbox") or [0, 0, 0, 0])[1]) for span in source_spans]
        nearby_target_spans = [
            span
            for span in _visual_spans(translated_page)
            if title_y_values and any(abs(float((span.get("bbox") or [0, 99999, 0, 0])[1]) - y) <= 48 for y in title_y_values)
        ]
        evidence = {
            "source_title": source_title,
            "required_tokens": required_tokens,
            "source_title_spans": [_span_text(span) for span in source_spans[:4]],
            "source_bbox_samples": [span.get("bbox") for span in source_spans[:4]],
            "nearby_target_samples": [_span_text(span)[:100] for span in nearby_target_spans[:8]],
            "translated_text_sample": translated_text[:360],
        }
        findings.append(
            {
                "severity": "warn",
                "category": "semantic_layout",
                "rule": "chart_title_missing",
                "page": page_number,
                "message": f"源页图表/小节标题 {source_title!r} 未在译文页对应为包含 {required_tokens} 的中文标题。",
                "evidence": json.dumps(evidence, ensure_ascii=False),
            }
        )
        findings.append(
            {
                "severity": "warn",
                "category": "semantic_layout",
                "rule": "chart_label_coverage_low",
                "page": page_number,
                "message": "图表标题或分组标题覆盖不足，不能只凭正文已翻译判定该页通过。",
                "evidence": json.dumps(evidence, ensure_ascii=False),
            }
        )
    return findings

def chart_axis_label_malformed_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    from visual_layout_core import normalize_lines
    source_text = str(source_page.get("text") or "")
    translated_text = str(translated_page.get("text") or "")
    source_chart_context = bool(
        re.search(r"\bFigure\s+1\.1\.\d+\b", source_text, re.I)
        or re.search(r"\bNumber of notable AI models\b", source_text, re.I)
    )
    translated_chart_context = bool(
        "图 1.1." in translated_text
        or "图1.1." in translated_text
        or "知名人工智能模型" in translated_text
        or "值得关注的人工智能模型" in translated_text
        or re.search(r"\bNumber of notable AI models\b", translated_text, re.I)
    )
    translated_explicit_figure_context = bool(re.search(r"图\s*1\.1\.\d+", translated_text))
    if not source_chart_context and not translated_explicit_figure_context:
        return []
    if not source_chart_context and not translated_chart_context:
        return []
    spans = _visual_spans(translated_page)
    digit_axis_lines = len(re.findall(r"(?m)^\s*\d{1,3}\s*$", translated_text))
    expected_axis_labels = {
        "美国",
        "中国",
        "韩国",
        "加拿大",
        "法国",
        "中国香港",
        "新加坡",
        "英国",
        "学术界",
        "产业界",
        "非营利",
        "其他",
        "产学合作",
    }
    orphan_axis_tokens = [
        _span_text(span)
        for span in spans
        if 0 < _span_size(span) < 6.5
        and re.fullmatch(r"[A-Za-z0-9%().-]{1,4}|[\u4e00-\u9fff]{1,2}", _span_text(span))
        and _span_text(span) not in expected_axis_labels
        and not re.fullmatch(r"\d{1,4}|(?:\d+(?:\.\d+)?)%", _span_text(span))
    ]
    axis_title_missing = (
        re.search(r"\bNumber of notable AI models\b", source_text, re.I)
        and not any(token in translated_text for token in ["知名人工智能模型数", "值得关注的人工智能模型数量", "知名人工智能模型数量"])
    )
    if digit_axis_lines < 8 and len(orphan_axis_tokens) < 8 and not axis_title_missing:
        return []
    evidence = {
        "digit_axis_line_count": digit_axis_lines,
        "orphan_axis_token_count": len(orphan_axis_tokens),
        "orphan_axis_token_samples": orphan_axis_tokens[:18],
        "axis_title_missing": axis_title_missing,
        "source_chart_samples": [line for line in normalize_lines(source_text) if re.search(r"Figure\s+1\.1\.|Number of notable AI models", line, re.I)][:8],
        "translated_chart_samples": [
            line
            for line in normalize_lines(translated_text)
            if re.search(r"图\s*1\.1\.|Number of notable AI models|知名人工智能模型|值得关注", line, re.I)
        ][:8],
    }
    return [
        {
            "severity": "warn",
            "category": "semantic_layout",
            "rule": "chart_axis_label_malformed",
            "page": page_number,
            "message": "图表坐标轴标签疑似碎片化、过小或未形成完整中文轴标题；需要进入 chart region 级视觉复核。",
            "evidence": json.dumps(evidence, ensure_ascii=False),
        }
    ]


def preview_region_pixel_stats(page: dict[str, Any], region: list[float]) -> dict[str, Any] | None:
    from visual_layout_extract import _load_fitz
    preview_path = page.get("preview_path")
    if not preview_path:
        return None
    path = Path(str(preview_path))
    if not path.exists():
        return None
    try:
        fitz = _load_fitz()
        pix = fitz.Pixmap(str(path))
    except Exception:
        return None
    page_width = float(page.get("width") or pix.width)
    page_height = float(page.get("height") or pix.height)
    x0 = max(0, min(pix.width, int(round(region[0] / max(page_width, 1.0) * pix.width))))
    y0 = max(0, min(pix.height, int(round(region[1] / max(page_height, 1.0) * pix.height))))
    x1 = max(0, min(pix.width, int(round(region[2] / max(page_width, 1.0) * pix.width))))
    y1 = max(0, min(pix.height, int(round(region[3] / max(page_height, 1.0) * pix.height))))
    if x1 <= x0 or y1 <= y0:
        return None
    nonwhite = 0
    colored = 0
    unique: set[tuple[int, int, int]] = set()
    total = (x1 - x0) * (y1 - y0)
    samples = pix.samples
    channels = pix.n
    stride = pix.width * channels
    for y in range(y0, y1):
        row = y * stride
        for x in range(x0, x1):
            offset = row + x * channels
            r = int(samples[offset])
            g = int(samples[offset + 1]) if channels > 1 else r
            b = int(samples[offset + 2]) if channels > 2 else r
            rgb = (r, g, b)
            unique.add(rgb)
            if min(rgb) < 245:
                nonwhite += 1
            if max(rgb) - min(rgb) >= 18 and min(rgb) < 245:
                colored += 1
    return {
        "region": [round(item, 2) for item in region],
        "preview_path": str(path),
        "pixel_count": total,
        "nonwhite_ratio": round(nonwhite / max(total, 1), 4),
        "colored_ratio": round(colored / max(total, 1), 4),
        "unique_color_count": len(unique),
        "image_size": [pix.width, pix.height],
    }


def source_translated_publisher_badge_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    if int(page_number) != 1:
        return []
    source_text = str(source_page.get("text") or "")
    if "humanities and social sciences communications" not in source_text.lower() and "doi.org/10.1057" not in source_text.lower():
        return []
    source_stats = preview_region_pixel_stats(source_page, NATURE_PUBLISHER_BADGE_REGION)
    translated_stats = preview_region_pixel_stats(translated_page, NATURE_PUBLISHER_BADGE_REGION)
    if not source_stats or not translated_stats:
        return []
    source_nonwhite = float(source_stats.get("nonwhite_ratio") or 0.0)
    translated_nonwhite = float(translated_stats.get("nonwhite_ratio") or 0.0)
    nonwhite_drop = source_nonwhite - translated_nonwhite
    if source_nonwhite < 0.08 or translated_nonwhite >= source_nonwhite * 0.55 or nonwhite_drop < 0.035:
        return []
    evidence = {
        "region_role": "nature_publisher_check_for_updates_badge",
        "expected_policy": "source_region_passthrough_or_gradient_preserving_redraw",
        "source": source_stats,
        "translated": translated_stats,
        "nonwhite_ratio_drop": round(nonwhite_drop, 4),
    }
    return [
        {
            "severity": "warn",
            "category": "rendering",
            "rule": "publisher_badge_background_drift",
            "page": page_number,
            "message": "Nature 首页右上角出版商 Check for updates badge 的渐变/图标背景在译文页明显变淡或变白，应按源区域保护或保留渐变重绘。",
            "evidence": json.dumps(evidence, ensure_ascii=False),
        },
        {
            "severity": "warn",
            "category": "rendering",
            "rule": "source_region_image_background_loss",
            "page": page_number,
            "message": "源 PDF 图像型控件区域的非白像素覆盖在译文页显著下降，疑似被白底覆盖或重新渲染。",
            "evidence": json.dumps(evidence, ensure_ascii=False),
        },
    ]

def source_translated_table_caption_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    source_text = str(source_page.get("text") or "")
    translated_text = str(translated_page.get("text") or "")
    # 正文中的 “as shown in Table 1” 不构成表题。兼容无冒号的独立表题，
    # 并排除以 Table N 起句的常见交叉引用。
    caption_pattern = r"(?im)^\s*Table\s+(\d+)(?!\d)\s*(?::|[.：]|\s+(?!(?:shows|lists|presents|reports|summarizes|illustrates|contains|compares|demonstrates)\b)[A-Z])"
    source_tables = sorted({int(match.group(1)) for match in re.finditer(caption_pattern, source_text)})
    findings: list[dict[str, Any]] = []
    for table_number in source_tables:
        source_caption_spans = [
            span
            for span in _visual_spans(source_page)
            if re.search(rf"\bTable\s+{table_number}\b", _span_text(span), re.I)
        ]
        target_caption_spans = [
            span
            for span in _visual_spans(translated_page)
            if re.search(rf"(?:表\s*{table_number}(?!\d)|Table\s+{table_number}(?!\d))", _span_text(span), re.I)
        ]
        # 从整页文本匹配身份，允许中文/数字被拆成字体 span 及合法重排。
        # 行首与标点约束避免正文 “如表1所示” 冒充实际表题。
        target_pattern = rf"(?im)^\s*(?:表\s*{table_number}|Table\s+{table_number})(?!\d)\s*(?::|[.：]|\s+(?!(?:所示|shows\b|lists\b|presents\b|reports\b|summarizes\b|illustrates\b|contains\b|compares\b|demonstrates\b))[^\W\d_])"
        caption_present = bool(re.search(target_pattern, translated_text))
        if not caption_present:
            findings.append(
                {
                    "severity": "warn",
                    "category": "semantic_layout",
                    "rule": "table_caption_missing",
                    "page": page_number,
                    "message": f"源页存在 Table {table_number} caption，但译文页未出现 表{table_number}/Table {table_number}。",
                    "evidence": json.dumps(
                        {
                            "table_number": table_number,
                            "source_caption_samples": [_span_text(span) for span in source_caption_spans[:3]],
                            "source_bbox_samples": [span.get("bbox") for span in source_caption_spans[:3]],
                            "target_caption_samples": [_span_text(span) for span in target_caption_spans[:3]],
                            "target_bbox_samples": [span.get("bbox") for span in target_caption_spans[:3]],
                            "translated_text_sample": translated_text[:260],
                        },
                        ensure_ascii=False,
                    ),
                }
            )
    return findings

def abstract_typography_findings(source_page: dict[str, Any], translated_page: dict[str, Any], page_number: int | str) -> list[dict[str, Any]]:
    from visual_layout_core import cjk_count
    if int(page_number) != 1:
        return []
    source_spans = [
        span
        for span in _visual_spans(source_page)
        if 280 <= float((span.get("bbox") or [0, 0, 0, 0])[1]) <= 380 and len(_span_text(span)) >= 24 and _span_size(span) >= 8
    ]
    translated_spans = [
        span
        for span in _visual_spans(translated_page)
        if 280 <= float((span.get("bbox") or [0, 0, 0, 0])[1]) <= 380 and cjk_count(_span_text(span)) >= 8
    ]
    if not source_spans or not translated_spans:
        return []
    source_avg = sum(_span_size(span) for span in source_spans) / len(source_spans)
    translated_avg = sum(_span_size(span) for span in translated_spans) / len(translated_spans)
    findings: list[dict[str, Any]] = []
    evidence = {
        "source_avg_size": round(source_avg, 2),
        "translated_avg_size": round(translated_avg, 2),
        "source_samples": [_span_text(span)[:80] for span in source_spans[:3]],
        "translated_samples": [_span_text(span)[:80] for span in translated_spans[:3]],
        "translated_fonts": sorted({str(span.get("font") or "") for span in translated_spans})[:6],
    }
    if translated_avg < source_avg * 0.78:
        findings.append(
            {
                "severity": "warn",
                "category": "readability",
                "rule": "abstract_font_size_regression",
                "page": page_number,
                "message": "摘要正文相对源 PDF 明显变小，肉眼阅读层级退化。",
                "evidence": json.dumps(evidence, ensure_ascii=False),
            }
        )
        findings.append(
            {
                "severity": "warn",
                "category": "readability",
                "rule": "font_size_regression",
                "page": page_number,
                "message": "摘要区域字号相对源版式明显退化，应进入视觉 gate。",
                "evidence": json.dumps(evidence, ensure_ascii=False),
            }
        )
    mixed_latin_cjk_spans = [
        span
        for span in translated_spans
        if re.search(r"[A-Za-z]{2,}", _span_text(span))
        and cjk_count(_span_text(span)) >= 8
        and _is_cjk_body_font_for_mixed_latin(str(span.get("font") or ""))
    ]
    if mixed_latin_cjk_spans:
        findings.append(
            {
                "severity": "warn",
                "category": "readability",
                "rule": "latin_font_fallback_in_cjk_body",
                "page": page_number,
                "message": "摘要正文中的英文 token 使用 CJK 正文字体混排，可能导致英文字母过宽或不协调。",
                "evidence": json.dumps(
                    {
                        **evidence,
                        "mixed_latin_cjk_samples": [_span_text(span)[:100] for span in mixed_latin_cjk_spans[:5]],
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return findings


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
