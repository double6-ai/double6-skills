# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation latex quality：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def build_latex_direct_quality_gate(
    *,
    source_segments: list[dict[str, Any]],
    latex_baseline_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from pdf_translation_latex_audit import latex_prose_for_line_estimate
    from pdf_translation_paths import latex_translation_after_writeback_repair
    issues: list[dict[str, Any]] = []
    command_inventory: list[dict[str, Any]] = []
    segment_completeness_rows: list[dict[str, Any]] = []
    paragraph_structure_rows: list[dict[str, Any]] = []
    auto_repairs: list[dict[str, Any]] = []

    def add(rule: str, severity: str, segment_id: str, evidence: str, repair_type: str) -> None:
        issues.append(
            {
                "rule": rule,
                "severity": severity,
                "segment_id": segment_id,
                "evidence": evidence[:500],
                "repair_type": repair_type,
            }
        )

    def latex_command_inventory(source: str, translation: str) -> dict[str, Any]:
        command_patterns = {
            "cite": r"\\cite\w*\*?(?:\[[^\]]*\])?\{[^{}]*\}",
            "ref": r"\\(?:ref|autoref|cref|Cref)\*?\{[^{}]*\}",
            "label": r"\\label\{[^{}]*\}",
            "url": r"\\url\{[^{}]*\}",
            "href": r"\\href\{[^{}]*\}\{[^{}]*\}",
            "caption": r"\\caption(?:\[[^\]]*\])?\{",
            "begin_env": r"\\begin\{[^{}]*\}",
            "end_env": r"\\end\{[^{}]*\}",
        }
        rows = []
        missing = []
        for command_type, pattern in command_patterns.items():
            source_items = re.findall(pattern, source)
            translation_items = re.findall(pattern, translation)
            source_norm = [re.sub(r"\s+", "", item) for item in source_items]
            translation_norm = [re.sub(r"\s+", "", item) for item in translation_items]
            for item in source_norm:
                if item not in translation_norm:
                    missing.append({"command_type": command_type, "command": item})
            rows.append(
                {
                    "command_type": command_type,
                    "source_count": len(source_items),
                    "translation_count": len(translation_items),
                    "missing_count": sum(1 for item in missing if item["command_type"] == command_type),
                }
            )
        return {
            "source_command_count": sum(item["source_count"] for item in rows),
            "translation_command_count": sum(item["translation_count"] for item in rows),
            "missing_command_count": len(missing),
            "by_type": rows,
            "missing_commands": missing,
        }

    def latex_residue_buckets(source: str, translation: str) -> dict[str, list[str]]:
        prose = latex_prose_for_line_estimate(translation)
        buckets = check_translation.classify_english_residue(prose)
        protected_source = " ".join(re.findall(r"\\(?:label|ref|cite|citep|citet|url|href)\*?(?:\[[^\]]*\])?\{[^{}]*\}", source))
        allowed = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", protected_source)}
        latex_allowed = {
            "paragraph",
            "placeholder",
            "footnote",
            "caption",
            "subcaption",
            "section",
            "subsection",
            "subsubsection",
            "textbackslash",
            "newcolumntype",
            "centering",
            "arraybackslash",
        }
        filtered = []
        for token in buckets.get("must_translate", []):
            lower = token.lower()
            if lower in latex_allowed or lower in allowed or "-" in lower or "_" in lower:
                continue
            filtered.append(token)
        buckets["must_translate"] = filtered
        return buckets

    def target_language_char_count(text: str) -> int:
        return sum(
            "\u4e00" <= ch <= "\u9fff"
            or "\u3040" <= ch <= "\u30ff"
            or "\uac00" <= ch <= "\ud7af"
            for ch in text
        )

    def source_sentences_left_untranslated(source: str, translation: str) -> list[str]:
        source_prose = latex_prose_for_line_estimate(source)
        translated_compact = re.sub(r"\s+", " ", translation).strip()
        findings: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", source_prose):
            sentence = sentence.strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", sentence)
            if len(sentence) < 70 or len(words) < 8:
                continue
            if sentence in translated_compact and sentence not in findings:
                findings.append(sentence)
            if len(findings) >= 5:
                break
        return findings

    def long_english_sections_in_translation(translation: str) -> list[str]:
        prose = latex_prose_for_line_estimate(translation)
        findings: list[str] = []
        for match in re.finditer(r"\b[A-Za-z][^。！？\u4e00-\u9fff]{80,}[.!?]", prose):
            candidate = re.sub(r"\s+", " ", match.group(0)).strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", candidate)
            if len(words) >= 12:
                findings.append(candidate)
            if len(findings) >= 5:
                return findings
        for sentence in re.split(r"(?<=[.!?])\s+", prose):
            sentence = sentence.strip()
            words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", sentence)
            if len(sentence) >= 90 and len(words) >= 12 and not re.search(r"[\u4e00-\u9fff]", sentence):
                findings.append(sentence)
            if len(findings) >= 5:
                break
        return findings

    def segment_completeness(source: str, translation: str) -> dict[str, Any]:
        source_prose = latex_prose_for_line_estimate(source)
        translated_prose = latex_prose_for_line_estimate(translation)
        source_words = len(re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", source_prose))
        source_letters = sum("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in source_prose)
        target_chars = target_language_char_count(translated_prose)
        untranslated_sentences = source_sentences_left_untranslated(source, translation)
        untranslated_residue_sections = long_english_sections_in_translation(translation)
        expected_min_target_chars = max(80, int(source_words * 0.22))
        partial = (
            source_letters >= 600
            and source_words >= 90
            and target_chars < expected_min_target_chars
            and len(translated_prose) < max(120, int(len(source_prose) * 0.22))
        )
        status = "blocking" if untranslated_sentences or untranslated_residue_sections or partial else "ok"
        return {
            "status": status,
            "source_chars": len(source_prose),
            "target_chars": len(translated_prose),
            "source_word_count": source_words,
            "target_language_chars": target_chars,
            "expected_min_target_language_chars": expected_min_target_chars if source_words >= 90 else None,
            "untranslated_sentences": untranslated_sentences,
            "untranslated_residue_sections": untranslated_residue_sections,
            "partial_segment_translation": partial,
        }

    def latex_paragraph_count(text: str) -> int:
        stripped = re.sub(r"(?m)^\s*%.*$", "", text).strip()
        if not stripped:
            return 0
        return len([part for part in re.split(r"\n\s*\n+", stripped) if part.strip()])

    def latex_environment_sequence(text: str) -> list[tuple[str, str]]:
        return [
            (kind, name)
            for kind, name in re.findall(r"\\(begin|end)\{([^{}]+)\}", text)
            if name.strip()
        ]

    def paragraph_sensitive_segment(segment_id: str, source: str) -> bool:
        lower_id = segment_id.lower()
        return bool(
            "abstract" in lower_id
            or re.search(r"\\begin\{abstract\}|\\caption(?:\[[^\]]*\])?\{|\\footnote\{|\\item\b", source)
        )

    def repair_paragraph_structure(source: str, translation: str) -> tuple[str, dict[str, Any]]:
        source_count = latex_paragraph_count(source)
        target_count = latex_paragraph_count(translation)
        env_source = latex_environment_sequence(source)
        env_target = latex_environment_sequence(translation)
        repaired = translation
        repair_applied = False
        if source_count <= 1 and target_count > 1:
            repaired = re.sub(r"\n\s*\n+", "\n", translation).strip()
            repair_applied = repaired != translation
        repaired_count = latex_paragraph_count(repaired)
        return repaired, {
            "source_paragraph_count": source_count,
            "translation_paragraph_count": target_count,
            "repaired_paragraph_count": repaired_count,
            "environment_sequence_match": env_source == env_target,
            "source_environment_sequence": env_source,
            "translation_environment_sequence": env_target,
            "repair_applied": repair_applied,
        }

    for segment in source_segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or segment.get("block_id") or "document")
        source = str(segment.get("source") or segment.get("text") or "")
        translation = str(segment.get("translation") or segment.get("target") or "")
        gate_translation = latex_translation_after_writeback_repair(source, translation)
        paragraph_repaired_translation, paragraph_structure = repair_paragraph_structure(source, gate_translation)
        paragraph_structure_rows.append({"segment_id": segment_id, "sensitive_segment": paragraph_sensitive_segment(segment_id, source), **paragraph_structure})
        if paragraph_structure["repair_applied"]:
            auto_repairs.append(
                {
                    "rule": "latex_paragraph_structure_drift",
                    "segment_id": segment_id,
                    "source_paragraph_count": paragraph_structure["source_paragraph_count"],
                    "translation_paragraph_count_before": paragraph_structure["translation_paragraph_count"],
                    "translation_paragraph_count_after": paragraph_structure["repaired_paragraph_count"],
                    "repair_type": "collapse_inserted_blank_lines",
                }
            )
        if paragraph_sensitive_segment(segment_id, source) and (
            paragraph_structure["source_paragraph_count"] != paragraph_structure["repaired_paragraph_count"]
            or not paragraph_structure["environment_sequence_match"]
        ):
            add(
                "latex_paragraph_structure_drift",
                "blocking",
                segment_id,
                json.dumps(paragraph_structure, ensure_ascii=False),
                "restore_latex_paragraph_boundaries",
            )
        gate_translation = paragraph_repaired_translation
        if translation.count(r"\footnote") > gate_translation.count(r"\footnote"):
            auto_repairs.append(
                {
                    "rule": "duplicate_footnote_payload",
                    "segment_id": segment_id,
                    "source_footnote_count": source.count(r"\footnote"),
                    "translation_footnote_count_before": translation.count(r"\footnote"),
                    "translation_footnote_count_after": gate_translation.count(r"\footnote"),
                    "repair_type": "deduplicate_repeated_footnote_payload",
                }
            )
        inventory = latex_command_inventory(source, gate_translation)
        if inventory["source_command_count"] or inventory["translation_command_count"]:
            command_inventory.append({"segment_id": segment_id, **inventory})
        for missing in inventory.get("missing_commands", []):
            command_type = str(missing.get("command_type") or "command")
            severity = "blocking" if command_type in {"cite", "ref", "label", "url", "href", "begin_env", "end_env"} else "warn"
            add(
                "missing_latex_command",
                severity,
                segment_id,
                json.dumps(missing, ensure_ascii=False),
                "restore_latex_command_inventory",
            )
        if segment.get("status") in {"empty", "fallback"} or not translation.strip():
            add("segment_empty_or_fallback", "blocking", segment_id, source[:200], "retry_segment_or_restore_source")
        completeness = segment_completeness(source, gate_translation)
        segment_completeness_rows.append({"segment_id": segment_id, **completeness})
        for sentence in completeness.get("untranslated_sentences", []) if isinstance(completeness.get("untranslated_sentences"), list) else []:
            add(
                "untranslated_english_section",
                "blocking",
                segment_id,
                sentence,
                "split_segment_and_retry_translation",
            )
        for sentence in completeness.get("untranslated_residue_sections", []) if isinstance(completeness.get("untranslated_residue_sections"), list) else []:
            add(
                "untranslated_english_section",
                "blocking",
                segment_id,
                sentence,
                "split_segment_and_retry_translation",
            )
        if completeness.get("partial_segment_translation"):
            add(
                "partial_segment_translation",
                "blocking",
                segment_id,
                json.dumps(
                    {
                        "source_chars": completeness.get("source_chars"),
                        "target_chars": completeness.get("target_chars"),
                        "source_word_count": completeness.get("source_word_count"),
                        "target_language_chars": completeness.get("target_language_chars"),
                        "expected_min_target_language_chars": completeness.get("expected_min_target_language_chars"),
                    },
                    ensure_ascii=False,
                ),
                "split_segment_and_retry_translation",
            )
        if re.search(r"\\(?:section|subsection|subsubsection|paragraph|caption)\s+[A-Za-z]", gate_translation):
            add("visible_structural_command_as_prose", "blocking", segment_id, gate_translation[:200], "restore_latex_command_argument")
        if gate_translation.count("{") != gate_translation.count("}"):
            add("brace_balance", "blocking", segment_id, gate_translation[:200], "restore_original_segment")
        for value in policy_utils.protected_values(source):
            if re.match(r"(?i)^https?://|^10\.", value) and not policy_utils.protected_value_present(value, gate_translation):
                add("missing_protected_url_or_doi", "blocking", segment_id, value, "restore_protected_span")
        buckets = latex_residue_buckets(source, gate_translation)
        if buckets.get("must_translate"):
            add(
                "ordinary_english_residue",
                "warn",
                segment_id,
                ", ".join(buckets["must_translate"][:12]),
                "retry_segment_with_term_policy",
            )

    baseline_audit = latex_baseline_audit if isinstance(latex_baseline_audit, dict) else {}
    baseline_pdf = baseline_audit.get("baseline_pdf") if isinstance(baseline_audit.get("baseline_pdf"), dict) else {}
    current_pdf = baseline_audit.get("current_pdf") if isinstance(baseline_audit.get("current_pdf"), dict) else {}
    accepted_delta = baseline_audit.get("accepted_delta") if isinstance(baseline_audit.get("accepted_delta"), dict) else {}
    if baseline_pdf.get("exists") and current_pdf.get("exists"):
        baseline_pages = baseline_pdf.get("page_count")
        current_pages = current_pdf.get("page_count")
        segment_coverage = baseline_audit.get("segment_window_coverage") if isinstance(baseline_audit.get("segment_window_coverage"), dict) else {}
        coverage_ok = segment_coverage.get("status") in {"ok", "warn"} and not segment_coverage.get("blocking_coverage_loss")
        delta_ok = accepted_delta.get("status") == "accepted" and not accepted_delta.get("content_loss_evidence") and coverage_ok
        if baseline_pages is not None and current_pages is not None and baseline_pages != current_pages and not delta_ok:
            line_estimate = baseline_audit.get("line_reflow_estimate") if isinstance(baseline_audit.get("line_reflow_estimate"), dict) else {}
            repair_type = (
                "latex_reflow_patch_plan"
                if line_estimate.get("required_line_coverage") is not None
                else "coverage_diff_review"
            )
            add(
                "latex_baseline_page_drift",
                "blocking",
                "document",
                json.dumps(
                    {
                        "baseline_page_count": baseline_pages,
                        "current_page_count": current_pages,
                        "line_reflow_estimate": line_estimate,
                    },
                    ensure_ascii=False,
                ),
                repair_type,
            )
    worst = "blocking" if any(item["severity"] == "blocking" for item in issues) else ("warn" if issues else "ok")
    inventory_summary = {
        "segment_count": len(command_inventory),
        "source_command_count": sum(int(item.get("source_command_count") or 0) for item in command_inventory),
        "translation_command_count": sum(int(item.get("translation_command_count") or 0) for item in command_inventory),
        "missing_command_count": sum(int(item.get("missing_command_count") or 0) for item in command_inventory),
        "segments": command_inventory[:200],
    }
    return {
        "version": 1,
        "status": worst,
        "issues": issues,
        "command_inventory": inventory_summary,
        "auto_repairs": {
            "count": len(auto_repairs),
            "items": auto_repairs[:200],
        },
        "segment_completeness": {
            "checked_count": len(segment_completeness_rows),
            "blocking_count": sum(1 for item in segment_completeness_rows if item.get("status") == "blocking"),
            "segments": segment_completeness_rows[:200],
        },
        "paragraph_structure": {
            "checked_count": len(paragraph_structure_rows),
            "drift_count": sum(
                1
                for item in paragraph_structure_rows
                if item.get("source_paragraph_count") != item.get("repaired_paragraph_count")
                or not item.get("environment_sequence_match", True)
            ),
            "auto_repair_count": sum(1 for item in paragraph_structure_rows if item.get("repair_applied")),
            "segments": paragraph_structure_rows[:200],
        },
        "segment_window_coverage": build_latex_segment_window_coverage(source_segments),
    }


def write_latex_segment_repair_plan(output_dir: Path, quality_gate: dict[str, Any], source_segments: list[dict[str, Any]]) -> dict[str, Any]:
    from pdf_translation_latex_audit import latex_prose_for_line_estimate
    segment_lookup = {
        str(item.get("id") or item.get("block_id") or ""): item
        for item in source_segments
        if isinstance(item, dict) and (item.get("id") or item.get("block_id"))
    }
    actionable_rules = {
        "partial_segment_translation",
        "untranslated_english_section",
        "segment_empty_or_fallback",
        "ordinary_english_residue",
        "missing_protected_url_or_doi",
        "brace_balance",
        "missing_latex_command",
        "latex_paragraph_structure_drift",
    }
    tasks: list[dict[str, Any]] = []
    for issue in quality_gate.get("issues", []) if isinstance(quality_gate.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        rule = str(issue.get("rule") or "")
        if rule not in actionable_rules:
            continue
        segment_id = str(issue.get("segment_id") or "")
        segment = segment_lookup.get(segment_id, {})
        source = str(segment.get("source") or segment.get("text") or "")
        translation = str(segment.get("translation") or segment.get("target") or "")
        tasks.append(
            {
                "task_id": f"latex-segment-repair-{len(tasks)+1:04d}",
                "segment_id": segment_id or "document",
                "rule": rule,
                "severity": issue.get("severity") or "warn",
                "repair_type": issue.get("repair_type") or "retry_segment",
                "source_excerpt": latex_prose_for_line_estimate(source)[:500],
                "target_excerpt": latex_prose_for_line_estimate(translation)[:500],
                "evidence": issue.get("evidence"),
                "recommended_action": (
                    "按句群或 LaTeX 安全边界拆分该 segment 后局部重译；重译后必须重新运行 "
                    "segment_completeness_check、protected span 和 command inventory gate。"
                    if rule in {"partial_segment_translation", "untranslated_english_section"}
                    else "局部修复该 segment 后重新运行 LaTeX direct quality gate。"
                ),
            }
        )
    payload = {
        "version": 1,
        "status": "blocking" if any(item.get("severity") == "blocking" for item in tasks) else ("warn" if tasks else "ok"),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    path = output_dir / "latex_segment_repair_plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(path)
    return payload


def write_latex_paragraph_structure_repair_manifest(output_dir: Path, quality_gate: dict[str, Any]) -> dict[str, Any]:
    paragraph_structure = quality_gate.get("paragraph_structure") if isinstance(quality_gate.get("paragraph_structure"), dict) else {}
    segments = paragraph_structure.get("segments") if isinstance(paragraph_structure.get("segments"), list) else []
    repairs = [
        item
        for item in segments
        if isinstance(item, dict)
        and (
            item.get("repair_applied")
            or item.get("source_paragraph_count") != item.get("repaired_paragraph_count")
            or not item.get("environment_sequence_match", True)
        )
    ]
    payload = {
        "version": 1,
        "status": "partial" if repairs else "ok",
        "repair_count": len(repairs),
        "repairs": repairs[:200],
        "policy": "abstract/caption/footnote/item 段落边界漂移必须在 LaTeX direct 写回前阻断或保守合并。",
    }
    path = output_dir / "latex_paragraph_structure_repair_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(path)
    return payload

def build_latex_segment_window_coverage(source_segments: list[dict[str, Any]], window_size: int = 20) -> dict[str, Any]:
    if not source_segments:
        return {
            "version": 1,
            "status": "unavailable",
            "reason": "missing_latex_segments",
            "segment_count": 0,
            "windows": [],
        }
    windows: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    fallback_ids: list[str] = []
    for offset in range(0, len(source_segments), window_size):
        window = source_segments[offset : offset + window_size]
        missing = []
        fallback = []
        ok = 0
        for segment in window:
            segment_id = str(segment.get("id") or segment.get("block_id") or f"segment-{offset}")
            translation = str(segment.get("translation") or segment.get("target") or "")
            status = str(segment.get("status") or "ok")
            if not translation.strip():
                missing.append(segment_id)
            elif status in {"empty", "fallback", "error"}:
                fallback.append(segment_id)
            else:
                ok += 1
        missing_ids.extend(missing)
        fallback_ids.extend(fallback)
        windows.append(
            {
                "window_id": f"segments-{offset + 1}-{offset + len(window)}",
                "start_index": offset + 1,
                "end_index": offset + len(window),
                "segment_count": len(window),
                "ok_count": ok,
                "missing_segment_ids": missing,
                "fallback_segment_ids": fallback,
                "coverage_ratio": round(ok / max(len(window), 1), 3),
                "status": "warn" if missing or fallback else "ok",
            }
        )
    blocking_loss = len(missing_ids) > max(2, int(len(source_segments) * 0.03))
    return {
        "version": 1,
        "status": "blocking" if blocking_loss else ("warn" if missing_ids or fallback_ids else "ok"),
        "segment_count": len(source_segments),
        "missing_segment_count": len(missing_ids),
        "fallback_segment_count": len(fallback_ids),
        "blocking_coverage_loss": blocking_loss,
        "windows": windows,
    }

def load_latex_direct_segments_for_gate(summary: dict[str, Any]) -> list[dict[str, Any]]:
    segments_path = Path(str(summary.get("segments_english") or ""))
    translations_path = Path(str(summary.get("reviewed_translations") or summary.get("translations") or ""))
    if not segments_path.is_file() or not translations_path.is_file():
        return []
    segments: dict[str, dict[str, Any]] = {}
    for line in segments_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        segment_id = str(row.get("id") or row.get("segment_id") or "")
        if not segment_id:
            continue
        segments[segment_id] = {
            "id": segment_id,
            "source": str(row.get("text") or row.get("source") or ""),
            "status": str(row.get("status") or "ok"),
        }
    for line in translations_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        segment_id = str(row.get("id") or row.get("segment_id") or "")
        if not segment_id or segment_id not in segments:
            continue
        segments[segment_id]["translation"] = str(row.get("translation") or row.get("target") or "")
        if row.get("status"):
            segments[segment_id]["status"] = str(row.get("status"))
    return list(segments.values())

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
