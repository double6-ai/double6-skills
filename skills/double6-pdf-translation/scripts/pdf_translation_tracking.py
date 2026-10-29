# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-22：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation tracking：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def iter_tracking_paragraphs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_name in ["page", "cross_page", "cross_column"]:
        groups = payload.get(group_name)
        if not isinstance(groups, list):
            continue
        for page_index, group in enumerate(groups, start=1):
            paragraphs = group.get("paragraph") if isinstance(group, dict) else None
            if not isinstance(paragraphs, list):
                continue
            for paragraph in paragraphs:
                if not isinstance(paragraph, dict):
                    continue
                row = dict(paragraph)
                row.setdefault("tracking_group", group_name)
                if row.get("page") is None and group_name == "page":
                    row["page"] = page_index
                rows.append(row)
    return rows

def _tracking_text_blob(tracking_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for paragraph in iter_tracking_paragraphs(tracking_payload):
        for key in ("input", "output", "pdf_unicode"):
            value = str(paragraph.get(key) or "").strip()
            if value:
                chunks.append(value)
    return "\n".join(chunks)

def build_dropped_text_audit(
    translated_pages: list[dict[str, Any]],
    tracking_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare visible PDF text against tracked backend items.

    This is intentionally conservative: it only emits findings for round-known
    layout-sensitive labels whose absence from tracking means the writeback
    chain cannot possibly fix the visible residue.
    """
    tracking = tracking_payload if isinstance(tracking_payload, dict) else {}
    tracking_blob = _tracking_text_blob(tracking)
    findings: list[dict[str, Any]] = []
    table_headers = {
        "Sub-corpus": "子语料库",
        "Number of texts": "文本数量",
        "Tokens": "词元数",
        "Mean length": "平均长度",
    }
    table_captions = {
        "Table 1": "表 1",
        "Table 2": "表 2",
    }
    tracked_headers = {
        source: bool(re.search(rf"\b{re.escape(source)}\b|{re.escape(target)}", tracking_blob, re.I))
        for source, target in table_headers.items()
    }
    for page in translated_pages:
        page_number = page.get("page")
        text = str(page.get("text") or "")
        visible_headers = [source for source in table_headers if re.search(rf"\b{re.escape(source)}\b", text, re.I)]
        for source in visible_headers:
            tracked = tracked_headers[source]
            if tracked:
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "layout_mapping",
                    "rule": "table_header_missing_from_il",
                    "page": page_number,
                    "failure_stage": "paragraph_finder",
                    "layout_role": "table_header",
                    "repair_target": "BabelDOC table span extraction / synthetic table_header item",
                    "message": f"表头 {source} 在主 PDF 文本层可见，但未进入 backend_translate_tracking，无法通过翻译/写回链路修复。",
                    "evidence": source,
                }
            )
        for source in visible_headers:
            tracked = tracked_headers[source]
            if not tracked:
                continue
            if not re.search(rf"\b{re.escape(source)}\b", text, re.I):
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "pdf_rendering",
                    "rule": "table_header_writeback_failed",
                    "page": page_number,
                    "failure_stage": "paint",
                    "layout_role": "table_header",
                    "repair_target": "BabelDOC table_header writeback or table-region rerender",
                    "message": f"表头 {source} 已进入 tracking 或已有译文路径，但主 PDF 仍可见英文，说明写回/清除原文本失败。",
                    "evidence": source,
                }
            )
        visible_captions = [source for source in table_captions if re.search(rf"\b{re.escape(source)}\b", text, re.I)]
        for source in visible_captions:
            tracked = bool(re.search(rf"\b{re.escape(source)}\b|{re.escape(table_captions[source])}", tracking_blob, re.I))
            if not tracked:
                findings.append(
                    {
                        "severity": "blocking",
                        "category": "layout_mapping",
                        "rule": "table_caption_missing",
                        "page": page_number,
                        "failure_stage": "paragraph_finder",
                        "layout_role": "table_caption",
                        "repair_target": "BabelDOC table span extraction / synthetic table_caption item",
                        "message": f"{source} caption 在主 PDF 文本层可见，但未进入 backend_translate_tracking，无法通过翻译/写回链路修复。",
                        "evidence": source,
                    }
                )
                continue
            findings.append(
                {
                    "severity": "blocking",
                    "category": "pdf_rendering",
                    "rule": "table_caption_writeback_failed",
                    "page": page_number,
                    "failure_stage": "paint",
                    "layout_role": "table_caption",
                    "repair_target": "BabelDOC table_caption writeback or table-region rerender",
                    "message": f"{source} caption 已进入 tracking 或已有译文路径，但主 PDF 仍可见英文，说明写回/清除原文本失败。",
                    "evidence": source,
                }
            )
    payload = {
        "version": 1,
        "status": "warn" if findings else "ok",
        "finding_count": len(findings),
        "tracking_available": bool(tracking),
        "findings": findings,
    }
    return payload

def build_dropped_text_audit_from_files(
    translated_pdf: Path | None,
    tracking_path: Path | None,
) -> dict[str, Any]:
    if not translated_pdf or not translated_pdf.exists():
        return {"version": 1, "status": "unavailable", "reason": "missing_translated_pdf", "findings": []}
    try:
        pages = visual_layout.extract_pdf_text_pages(translated_pdf)
    except Exception as exc:  # noqa: BLE001
        return {"version": 1, "status": "unavailable", "reason": f"text_extract_failed: {exc}", "findings": []}
    tracking_payload: dict[str, Any] | None = None
    if tracking_path and tracking_path.exists():
        try:
            tracking_payload = json.loads(tracking_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            tracking_payload = None
    return build_dropped_text_audit(pages, tracking_payload)

def extract_tracking_failures(tracking_path: Path | None) -> list[dict[str, Any]]:
    from pdf_translation_backend_quality import cjk_count, classify_backend_fallback, classify_backend_passthrough, has_long_ordinary_english_run, looks_like_name_list_heavy, plain_text_without_style_tags
    if not tracking_path or not tracking_path.exists():
        return []
    try:
        payload = json.loads(tracking_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return [
            {
                "failure_type": "tracking_parse_error",
                "classification": "mapping_missing",
                "source_snippet": "",
                "output_snippet": "",
                "page": None,
                "paragraph_debug_id": None,
                "layout_label": None,
                "layout_role": None,
            }
        ]
    failures: list[dict[str, Any]] = []
    for paragraph in iter_tracking_paragraphs(payload):
        source = str(paragraph.get("input") or paragraph.get("pdf_unicode") or "")
        output = str(paragraph.get("output") or "")
        trackers = paragraph.get("llm_translate_trackers")
        trackers = trackers if isinstance(trackers, list) else []
        tracker_errors = [
            str(item.get("error_message") or "")
            for item in trackers
            if isinstance(item, dict) and (item.get("error_message") or item.get("fallback_to_translate"))
        ]
        fallback = any(isinstance(item, dict) and item.get("fallback_to_translate") for item in trackers)
        same_as_input = bool(source.strip() and output.strip() and source.strip() == output.strip())
        writeback_status = str(paragraph.get("writeback_status") or "")
        writeback_reason = str(paragraph.get("writeback_reason") or "")
        layout_role = paragraph.get("layout_role") or paragraph.get("layout_label")
        layout_role_text = str(layout_role or "").lower()
        if same_as_input and writeback_status == "preserved" and writeback_reason == "context_released_source_identity":
            # 仅凭上下文放行的单词标签，模型原样返回（专名）后按原文保留，不是未翻译。
            continue
        translated_not_written = (
            writeback_status in {"rejected", "needs_region_rerender", "chart_region_rerender_required"}
            and re.search(r"[\u4e00-\u9fff]", output)
            and re.search(r"[A-Za-z]{3,}", source)
        )
        output_words = re.findall(r"[A-Za-z]{3,}", output)
        partial_body_direct = (
            layout_role_text in {"body_prose", "plain text", "text", "paragraph_hybrid", ""}
            and len(source) >= 80
            and re.search(r"[\u4e00-\u9fff]", output)
            and len(output_words) >= 8
            and any(word.lower() in source.lower() for word in output_words[:12])
            and not looks_like_name_list_heavy(source)
            and has_long_ordinary_english_run(output)
        )
        if not fallback and not same_as_input and not tracker_errors and not translated_not_written and not partial_body_direct:
            continue
        error_text = " | ".join(error for error in tracker_errors if error)
        if partial_body_direct:
            failure_type = "body_prose_partial_direct_output"
            classification = classify_backend_passthrough(source)
            if classification in {"protected_or_passthrough", "already_translated_passthrough", "cover_split_fragment"}:
                pass
            elif classification != "layout_role_passthrough":
                classification = "ordinary_same_as_input"
        elif writeback_status == "needs_region_rerender":
            failure_type = "region_rerender_required"
            classification = "needs_backend_mapping"
        elif writeback_status == "chart_region_rerender_required":
            failure_type = "chart_region_rerender_required"
            classification = "needs_backend_mapping"
        elif translated_not_written:
            failure_type = "translated_but_not_written_back"
            classification = "ordinary_same_as_input"
        elif same_as_input:
            failure_type = "same_as_input_after_retry"
            classification = classify_backend_passthrough(source)
        elif fallback:
            failure_type = "fallback_to_simple_translation"
            classification = classify_backend_fallback(source, output)
            if (
                classification == "fallback_to_simple_translation"
                and layout_role_text in {"running_footer", "running_header", "affiliation_footer", "doi_line"}
                and cjk_count(output) >= 2
                and plain_text_without_style_tags(output).strip() != plain_text_without_style_tags(source).strip()
            ):
                classification = "fallback_but_translated_warn"
        elif "protected_or_passthrough" in error_text:
            failure_type = "protected_passthrough"
            classification = "protected_or_passthrough"
        else:
            failure_type = "structured_translation_failure"
            if str(paragraph.get("writeback_status") or "") == "applied" and output.strip() and not fallback:
                # 修订 135：解析失败只发生在历史重试（如纯翻译模型首次输出不带
                # 结构化包装，重试后成功），最终已写回且译文有效时不计 blocking。
                failure_type = "recovered_after_parse_retry"
                classification = "recovered_after_parse_retry"
            elif "same as input" in error_text.lower():
                classification = "ordinary_same_as_input"
            elif re.search(r"[\u4e00-\u9fff]", output) and re.search(r"[A-Za-z]{2,}", source):
                classification = "structured_translated_needs_mapping"
            else:
                classification = "needs_backend_mapping"
        failures.append(
            {
                "failure_type": failure_type,
                "source_snippet": source[:240],
                "output_snippet": output[:240],
                "paragraph_debug_id": paragraph.get("debug_id") or paragraph.get("paragraph_debug_id"),
                "page": paragraph.get("page"),
                "layout_label": layout_role,
                "layout_role": layout_role,
                "classification": classification,
                "blocking_reason": "ordinary prose untranslated or structured backend failure"
                if classification not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
                else None,
                "nonblocking_reason": classification if classification in NON_BLOCKING_BACKEND_FAILURE_CLASSES else None,
                "tracking_group": paragraph.get("tracking_group"),
                "error_message": error_text[:500],
                "writeback_status": writeback_status or None,
                "writeback_reason": writeback_reason or None,
            }
        )
    return failures


def dedupe_backend_retry_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    index: dict[tuple[Any, ...], int] = {}

    def key_for(item: dict[str, Any]) -> tuple[Any, ...]:
        debug_id = item.get("paragraph_debug_id")
        page = item.get("page")
        if debug_id:
            return ("paragraph", page, debug_id)
        return ("snippet", item.get("source_snippet"), item.get("output_snippet"))

    def is_blocking(item: dict[str, Any]) -> bool:
        return item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES

    for item in failures:
        key = key_for(item)
        if key not in index:
            index[key] = len(deduped)
            deduped.append(item)
            continue
        existing = deduped[index[key]]
        existing_types = set(existing.get("duplicate_failure_types") or [])
        if existing.get("failure_type"):
            existing_types.add(str(existing.get("failure_type")))
        if item.get("failure_type"):
            existing_types.add(str(item.get("failure_type")))
        existing["duplicate_failure_types"] = sorted(existing_types)
        if is_blocking(item) and not is_blocking(existing):
            item["duplicate_failure_types"] = sorted(existing_types)
            deduped[index[key]] = item
        elif is_blocking(item) == is_blocking(existing) and str(item.get("failure_type") or "") == "same_as_input_after_retry":
            item["duplicate_failure_types"] = sorted(existing_types)
            deduped[index[key]] = item
    return deduped

def write_backend_retry_failures(
    output_dir: Path,
    proxy_info: dict[str, Any],
    backend_quality: dict[str, Any],
    *,
    tracking_path: Path | None = None,
) -> Path:
    from pdf_translation_backend_quality import classify_backend_passthrough
    stats = proxy_info.get("stats") if isinstance(proxy_info, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    failures: list[dict[str, Any]] = []
    for sample in stats.get("json_batch_same_as_input_samples", []) if isinstance(stats.get("json_batch_same_as_input_samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        failures.append(
            {
                "failure_type": "same_as_input_after_retry",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": classify_backend_passthrough(source),
            }
        )
    for sample in stats.get("same_as_input_candidates", []) if isinstance(stats.get("same_as_input_candidates"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        if any(item.get("source_snippet") == source[:240] for item in failures):
            continue
        classification = classify_backend_passthrough(source)
        if classification == "ordinary_same_as_input":
            classification = "needs_backend_mapping"
        failures.append(
            {
                "failure_type": "same_as_input_retry_candidate",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": classification,
            }
        )
    for sample in stats.get("plain_layout_role_intercept_samples", []) if isinstance(stats.get("plain_layout_role_intercept_samples"), list) else []:
        if not isinstance(sample, dict):
            continue
        source = str(sample.get("source") or "")
        if any(item.get("source_snippet") == source[:240] for item in failures):
            continue
        failures.append(
            {
                "failure_type": "layout_role_passthrough",
                "source_snippet": source[:240],
                "output_snippet": str(sample.get("output") or "")[:240],
                "paragraph_debug_id": sample.get("paragraph_debug_id"),
                "page": sample.get("page"),
                "layout_label": sample.get("layout_label"),
                "layout_role": sample.get("layout_role") or sample.get("layout_label"),
                "classification": "layout_role_passthrough",
            }
        )
    seen = {(item.get("failure_type"), item.get("source_snippet"), item.get("output_snippet")) for item in failures}
    for item in extract_tracking_failures(tracking_path):
        key = (item.get("failure_type"), item.get("source_snippet"), item.get("output_snippet"))
        if key in seen:
            continue
        seen.add(key)
        failures.append(item)
    failures = dedupe_backend_retry_failures(failures)
    for item in failures:
        classification = item.get("classification")
        item.setdefault(
            "blocking_reason",
            "ordinary prose untranslated or structured backend failure"
            if classification not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
            else None,
        )
        item.setdefault("nonblocking_reason", classification if classification in NON_BLOCKING_BACKEND_FAILURE_CLASSES else None)
    blocking_count = sum(1 for item in failures if item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES)
    tracking_incomplete = [
        item
        for item in failures
        if item.get("classification") not in NON_BLOCKING_BACKEND_FAILURE_CLASSES
        and (item.get("page") is None or not item.get("paragraph_debug_id") or not (item.get("layout_role") or item.get("layout_label")))
    ]
    payload = {
        "version": 1,
        "status": "warn" if blocking_count or tracking_incomplete else "ok",
        "failure_count": len(failures),
        "blocking_failure_count": blocking_count,
        "backend_quality_same_as_input_origin": backend_quality.get("same_as_input_origin"),
        "tracking_source": str(tracking_path) if tracking_path else None,
        "tracking_mapping_status": "incomplete" if tracking_incomplete else ("ok" if tracking_path else "missing"),
        "tracking_incomplete_count": len(tracking_incomplete),
        "tracking_incomplete_samples": tracking_incomplete[:5],
        "failures": failures,
    }
    path = output_dir / "backend_retry_failures.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
