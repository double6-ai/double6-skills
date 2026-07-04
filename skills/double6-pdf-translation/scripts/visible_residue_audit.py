#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py and tests to aggregate visible English residue diagnostics."

CRITICAL_PAGES = {1}
ORDINARY_BODY_ROLES = {"body_prose", "plain text", "text", "paragraph_hybrid", "unknown_visible_line", ""}


def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip().lower()


def normalize_match_text(value: str) -> str:
    value = re.sub(r"</?style\b[^>]*>", " ", str(value or ""), flags=re.I)
    value = re.sub(r"\{v\d+\}", " ", value)
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def has_long_ordinary_english(value: str) -> bool:
    text = str(value or "")
    if len(re.findall(r"[A-Za-z]", text)) < 18:
        return False
    if re.search(r"\b(?:the|this|that|these|those|we|our|agent|agents|method|methods|model|models|task|tasks|learn|learning|memory|performance|trajectory|trajectories)\b", text, re.I):
        return True
    return bool(re.search(r"[A-Za-z]{4,}(?:[\s,;:()\\/-]+[A-Za-z]{4,}){3,}", text))


def is_protected_visible_text(text: str, *, page: int | None = None) -> bool:
    stripped = re.sub(r"\s+", " ", str(text or "").strip())
    normalized = normalize_text(stripped)
    if not stripped:
        return True
    if re.fullmatch(r"https?://\S+|\S+@\S+", stripped, flags=re.I):
        return True
    if re.search(r"\barxiv\s*:\s*\d{4}\.\d{4,5}v?\d*\b", stripped, flags=re.I):
        return True
    if re.search(r"\b\d{4}\.\d{4,5}v\d+\s*\[[^\]]+\]\s*\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\b", stripped):
        return True
    if re.fullmatch(r"(?:[A-Z][A-Za-z'’.-]+|[A-Z]{2,})(?:\s+(?:and\s+)?(?:[A-Z][A-Za-z'’.-]+|[A-Z]{2,})){0,7}", stripped):
        return True
    if re.fullmatch(r"(?:UNC|UC|MIT|NEC|Labs?|University|College|Institute|America|Berkeley|Chicago|California|San Diego|Santa Barbara|Chapel Hill|Stanford)(?:[\s-]+[A-Za-z.]+){0,12}", stripped):
        return True
    if normalized in {"base", "model", "environment", "expert", "memory", "skill", "skills", "evolution"}:
        return True
    if re.fullmatch(r"(?:[A-Z][A-Za-z0-9-]*|LLM|RL|GRPO|SKILLRL|ALFWorld|WebShop)(?:[,;/\s]+(?:[A-Z][A-Za-z0-9-]*|LLM|RL|GRPO|SKILLRL|ALFWorld|WebShop))*", stripped):
        return True
    return False


def _first_int(*values: Any) -> int | None:
    for value in values:
        try:
            if value not in {None, ""}:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _repair_target_for_failure(failure_type: str, role: str) -> str:
    if failure_type == "translated_but_source_visible":
        if role.lower() in {"chart_label", "axis", "axis_label", "table_header", "table_caption"}:
            return "region_rerender_required"
        return "babeldoc_writeback_clear_source"
    if failure_type == "visible_text_not_tracked":
        return "paragraph_finder_required"
    if failure_type == "style_tag_leak":
        return "babeldoc_writeback_clear_source"
    if failure_type == "fallback_without_writeback":
        return "readable_fallback_required"
    return "readable_fallback_required"


def _ordinary_body_residue(item: dict[str, Any]) -> bool:
    role = str(item.get("layout_role") or "").lower()
    text = str(item.get("visible_text") or item.get("text") or "")
    if role not in ORDINARY_BODY_ROLES:
        return False
    return has_long_ordinary_english(text) and not is_protected_visible_text(text, page=_first_int(item.get("page")))


def normalize_finding(raw: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    rule = str(raw.get("rule") or "")
    sample = raw
    if "samples" in raw and isinstance(raw.get("samples"), list):
        return None
    text = str(raw.get("visible_text") or raw.get("text") or raw.get("evidence") or "")
    tracking_output = str(raw.get("tracking_output") or raw.get("output") or "")
    tracking_source = str(raw.get("tracking_source") or raw.get("source") or raw.get("source_text") or "")
    role = str(raw.get("layout_role") or raw.get("layout_label") or "")
    page = _first_int(raw.get("page"))
    failure_type = ""
    if "style_tag" in rule or re.search(r"</?style\b", text, re.I):
        failure_type = "style_tag_leak"
    elif "visible_text_not_tracked" in rule:
        failure_type = "visible_text_not_tracked"
    elif "translated_but_source_visible" in rule or "tracking_translated_but_source_visible" in rule:
        failure_type = "translated_but_source_visible"
    elif "ocr_critical_page_english_residue" in rule:
        failure_type = "translated_but_source_visible"
    elif raw.get("fallback_to_translate") or "fallback" in rule:
        failure_type = "fallback_without_writeback"
    else:
        return None
    if failure_type != "style_tag_leak" and text and is_protected_visible_text(text, page=page):
        return None
    severity = str(raw.get("severity") or ("blocking" if failure_type in {"translated_but_source_visible", "style_tag_leak"} else "warn"))
    item = {
        "failure_type": failure_type,
        "rule": rule or failure_type,
        "severity": severity,
        "page": page,
        "bbox": raw.get("bbox"),
        "visible_text": text[:500],
        "tracking_source": tracking_source[:500],
        "tracking_output": tracking_output[:500],
        "layout_role": role or "unknown_visible_line",
        "paragraph_debug_id": raw.get("paragraph_debug_id") or raw.get("debug_id"),
        "failure_stage": raw.get("failure_stage") or ("paint" if failure_type != "visible_text_not_tracked" else "paragraph_finder"),
        "evidence_source": source,
        "repair_target": _repair_target_for_failure(failure_type, role),
    }
    item["critical_page"] = page in CRITICAL_PAGES
    item["ordinary_body_residue"] = _ordinary_body_residue(item)
    item["delivery_blocking"] = bool(
        item["critical_page"]
        and (item["ordinary_body_residue"] or failure_type in {"style_tag_leak", "translated_but_source_visible"})
    )
    return item


def iter_audit_findings(payload: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for key in ["visible_text_not_tracked", "tracking_translated_but_source_visible", "findings"]:
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for raw in values:
            if not isinstance(raw, dict):
                continue
            if key == "findings" and isinstance(raw.get("samples"), list):
                for sample in raw.get("samples") or []:
                    if isinstance(sample, dict):
                        merged = {**sample, "rule": sample.get("rule") or raw.get("rule"), "severity": sample.get("severity") or raw.get("severity")}
                        item = normalize_finding(merged, source=source)
                        if item:
                            findings.append(item)
                continue
            item = normalize_finding(raw, source=source)
            if item:
                findings.append(item)
    return findings


def tracking_fallback_findings(tracking_payload: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    try:
        import build_babeldoc_il_layout_map
    except Exception:
        return []
    findings: list[dict[str, Any]] = []
    for row in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        if not isinstance(row, dict):
            continue
        trackers = row.get("llm_translate_trackers")
        trackers = trackers if isinstance(trackers, list) else []
        fallback = any(isinstance(item, dict) and item.get("fallback_to_translate") for item in trackers)
        source = str(row.get("input") or row.get("pdf_unicode") or "")
        output = str(row.get("output") or "")
        if not fallback or not source or not has_cjk(output):
            continue
        item = normalize_finding(
            {
                "rule": "fallback_without_writeback",
                "severity": "warn",
                "page": row.get("page"),
                "visible_text": source,
                "tracking_source": source,
                "tracking_output": output,
                "layout_role": row.get("layout_role") or row.get("layout_label"),
                "paragraph_debug_id": row.get("debug_id") or row.get("paragraph_debug_id"),
                "failure_stage": "writeback",
                "fallback_to_translate": True,
            },
            source="backend_translate_tracking",
        )
        if item:
            findings.append(item)
        if len(findings) >= limit:
            break
    return findings


def ledger_entries(proxy_ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    entries = proxy_ledger.get("entries") if isinstance(proxy_ledger, dict) else []
    return [item for item in entries if isinstance(item, dict)]


def match_score(needle: str, haystack: str) -> float:
    needle_norm = normalize_match_text(needle)
    haystack_norm = normalize_match_text(haystack)
    if not needle_norm or not haystack_norm:
        return 0.0
    if needle_norm in haystack_norm:
        return min(1.0, max(0.75, len(needle_norm) / max(len(haystack_norm), 1)))
    needle_words = set(needle_norm.split())
    haystack_words = set(haystack_norm.split())
    token_score = len(needle_words & haystack_words) / max(len(needle_words), 1)
    sequence_score = difflib.SequenceMatcher(None, needle_norm, haystack_norm).ratio()
    return max(token_score, sequence_score)


def best_ledger_match(text: str, proxy_ledger: dict[str, Any] | None) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for entry in ledger_entries(proxy_ledger):
        source = str(entry.get("source") or "")
        output = str(entry.get("output") or "")
        if not source or not has_cjk(output):
            continue
        score = match_score(text, source)
        if score > best_score:
            best = entry
            best_score = score
    return best, round(best_score, 4)


def best_poppler_line_match(text: str, poppler_audit: dict[str, Any] | None, *, page: int | None, key: str) -> tuple[dict[str, Any] | None, float]:
    lines = poppler_audit.get(key) if isinstance(poppler_audit, dict) else []
    if not isinstance(lines, list):
        return None, 0.0
    best: dict[str, Any] | None = None
    best_score = 0.0
    for line in lines:
        if not isinstance(line, dict):
            continue
        if page is not None and _first_int(line.get("page")) != page:
            continue
        score = match_score(text, str(line.get("text") or ""))
        if score > best_score:
            best = line
            best_score = score
    return best, round(best_score, 4)


def enrich_visible_residue_findings(
    findings: list[dict[str, Any]],
    *,
    proxy_ledger: dict[str, Any] | None = None,
    poppler_audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in findings:
        updated = dict(item)
        text = str(updated.get("visible_text") or "")
        page = _first_int(updated.get("page"))
        if updated.get("bbox") is not None and updated.get("visible_bbox") is None:
            updated["visible_bbox"] = updated.get("bbox")
        if updated.get("evidence_source") == "critical_page_ocr" and text:
            ledger_match, ledger_score = best_ledger_match(text, proxy_ledger)
            source_line, source_score = best_poppler_line_match(text, poppler_audit, page=page, key="source_lines")
            if source_line and source_line.get("bbox"):
                updated["source_bbox"] = source_line.get("bbox")
                updated["source_line_match_confidence"] = source_score
            if ledger_match and ledger_score >= 0.52:
                updated["failure_type"] = "translated_but_source_visible"
                updated["tracking_source"] = str(ledger_match.get("source") or "")[:500]
                updated["tracking_output"] = str(ledger_match.get("output") or "")[:500]
                updated["layout_role"] = str(ledger_match.get("layout_role") or updated.get("layout_role") or "body_prose")
                updated["layout_label"] = ledger_match.get("layout_label")
                updated["paragraph_debug_id"] = ledger_match.get("paragraph_debug_id")
                updated["match_confidence"] = ledger_score
                updated["repair_target"] = _repair_target_for_failure("translated_but_source_visible", str(updated.get("layout_role") or ""))
            else:
                updated["failure_type"] = "visible_text_not_tracked"
                updated["failure_stage"] = "paragraph_finder"
                updated["match_confidence"] = ledger_score
                updated["repair_target"] = "paragraph_finder_required"
                updated["tracking_source"] = ""
                updated["tracking_output"] = ""
            updated["ordinary_body_residue"] = _ordinary_body_residue(updated)
            updated["delivery_blocking"] = bool(updated.get("critical_page") and updated.get("ordinary_body_residue"))
        enriched.append(updated)
    return enriched


def ocr_critical_page_findings(output_dir: Path | None, *, limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if output_dir is None:
        return [], {"status": "skipped", "reason": "output_dir_missing"}
    binary = shutil.which("tesseract")
    if not binary:
        return rapidocr_critical_page_findings(output_dir, limit=limit)
    findings: list[dict[str, Any]] = []
    pages_checked: list[int] = []
    for page in sorted(CRITICAL_PAGES):
        image = output_dir / "visual_pages" / f"translated_page_{page:03d}.png"
        if not image.exists():
            continue
        pages_checked.append(page)
        with tempfile.TemporaryDirectory(prefix="visible_residue_ocr_") as tmpdir:
            out_base = Path(tmpdir) / "ocr"
            result = subprocess.run(
                [binary, str(image), str(out_base), "-l", "eng", "--psm", "6", "tsv"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                continue
            tsv_path = out_base.with_suffix(".tsv")
            if not tsv_path.exists():
                continue
            line_words: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for raw_line in tsv_path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                parts = raw_line.split("\t")
                if len(parts) < 12:
                    continue
                text = parts[11].strip()
                if not text:
                    continue
                key = (parts[2], parts[3], parts[4])
                try:
                    left, top, width, height = (float(parts[6]), float(parts[7]), float(parts[8]), float(parts[9]))
                except (TypeError, ValueError):
                    continue
                line_words.setdefault(key, []).append({"text": text, "bbox": [left, top, left + width, top + height]})
            for words in line_words.values():
                text = " ".join(str(word["text"]) for word in words)
                if not has_long_ordinary_english(text) or is_protected_visible_text(text, page=page):
                    continue
                x0 = min(float(word["bbox"][0]) for word in words)
                y0 = min(float(word["bbox"][1]) for word in words)
                x1 = max(float(word["bbox"][2]) for word in words)
                y1 = max(float(word["bbox"][3]) for word in words)
                item = normalize_finding(
                    {
                        "rule": "ocr_critical_page_english_residue",
                        "severity": "blocking",
                        "page": page,
                        "visible_text": text,
                        "bbox": [x0, y0, x1, y1],
                        "layout_role": "body_prose",
                        "failure_stage": "paint",
                    },
                    source="critical_page_ocr",
                )
                if item:
                    item["failure_type"] = "translated_but_source_visible"
                    item["repair_target"] = "readable_fallback_required"
                    item["ordinary_body_residue"] = True
                    item["delivery_blocking"] = True
                    findings.append(item)
                if len(findings) >= limit:
                    break
    status = "ok" if pages_checked else "skipped"
    return findings, {"status": status, "engine": "tesseract", "pages_checked": pages_checked, "finding_count": len(findings)}


def rapidocr_critical_page_findings(output_dir: Path, *, limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return [], {"status": "unavailable", "reason": f"ocr_unavailable: {exc}"}
    findings: list[dict[str, Any]] = []
    pages_checked: list[int] = []
    try:
        engine = RapidOCR()
    except Exception as exc:  # noqa: BLE001
        return [], {"status": "unavailable", "engine": "rapidocr_onnxruntime", "reason": f"rapidocr_init_failed: {exc}"}
    for page in sorted(CRITICAL_PAGES):
        image = output_dir / "visual_pages" / f"translated_page_{page:03d}.png"
        if not image.exists():
            continue
        pages_checked.append(page)
        try:
            result, _elapsed = engine(str(image))
        except Exception as exc:  # noqa: BLE001
            return findings, {"status": "warn", "engine": "rapidocr_onnxruntime", "pages_checked": pages_checked, "reason": f"rapidocr_failed: {exc}", "finding_count": len(findings)}
        for raw in result or []:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            points = raw[0]
            text = str(raw[1] or "")
            score = float(raw[2]) if len(raw) > 2 else None
            if score is not None and score < 0.72:
                continue
            if not has_long_ordinary_english(text) or is_protected_visible_text(text, page=page):
                continue
            try:
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            except Exception:
                bbox = None
            item = normalize_finding(
                {
                    "rule": "ocr_critical_page_english_residue",
                    "severity": "blocking",
                    "page": page,
                    "visible_text": text,
                    "bbox": bbox,
                    "layout_role": "body_prose",
                    "failure_stage": "paint",
                },
                source="critical_page_ocr",
            )
            if item:
                item["ocr_engine"] = "rapidocr_onnxruntime"
                item["ocr_score"] = score
                item["repair_target"] = "readable_fallback_required"
                item["ordinary_body_residue"] = True
                item["delivery_blocking"] = True
                findings.append(item)
            if len(findings) >= limit:
                break
    status = "ok" if pages_checked else "skipped"
    return findings, {"status": status, "engine": "rapidocr_onnxruntime", "pages_checked": pages_checked, "finding_count": len(findings)}


def dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, Any, str, str]] = set()
    for item in findings:
        key = (
            str(item.get("failure_type") or ""),
            item.get("page"),
            normalize_text(str(item.get("visible_text") or ""))[:120],
            str(item.get("paragraph_debug_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_visible_residue_audit(
    *,
    pymupdf_audit: dict[str, Any] | None = None,
    poppler_audit: dict[str, Any] | None = None,
    visual_report: dict[str, Any] | None = None,
    tracking_payload: dict[str, Any] | None = None,
    proxy_ledger: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    findings = []
    findings.extend(iter_audit_findings(pymupdf_audit or {}, source="pymupdf_layout_audit"))
    findings.extend(iter_audit_findings(poppler_audit or {}, source="poppler_text_bbox_audit"))
    findings.extend(iter_audit_findings(visual_report or {}, source="visual_layout_report"))
    findings.extend(tracking_fallback_findings(tracking_payload or {}))
    ocr_findings, ocr_status = ocr_critical_page_findings(output_dir)
    findings.extend(ocr_findings)
    findings = enrich_visible_residue_findings(findings, proxy_ledger=proxy_ledger, poppler_audit=poppler_audit)
    findings = dedupe_findings(findings)
    blocking = [item for item in findings if item.get("delivery_blocking") or item.get("severity") == "blocking"]
    critical = [item for item in findings if item.get("critical_page")]
    by_type: dict[str, int] = {}
    for item in findings:
        key = str(item.get("failure_type") or "unknown")
        by_type[key] = by_type.get(key, 0) + 1
    return {
        "version": 1,
        "status": "partial" if blocking else ("warn" if findings else "ok"),
        "critical_pages": sorted(CRITICAL_PAGES),
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "critical_page_finding_count": len(critical),
        "ordinary_body_critical_count": sum(1 for item in findings if item.get("critical_page") and item.get("ordinary_body_residue")),
        "counts_by_failure_type": by_type,
        "ocr": ocr_status,
        "findings": findings,
    }


def build_pdf_backend_repair_plan(audit: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for item in audit.get("findings", []) if isinstance(audit.get("findings"), list) else []:
        if not isinstance(item, dict):
            continue
        tasks.append(
            {
                "task_id": f"pdf-backend-repair-{len(tasks) + 1:04d}",
                "status": "planned",
                "page": item.get("page"),
                "bbox": item.get("bbox"),
                "failure_type": item.get("failure_type"),
                "failure_stage": item.get("failure_stage"),
                "layout_role": item.get("layout_role"),
                "paragraph_debug_id": item.get("paragraph_debug_id"),
                "repair_target": item.get("repair_target") or _repair_target_for_failure(str(item.get("failure_type") or ""), str(item.get("layout_role") or "")),
                "visible_text": item.get("visible_text"),
                "tracking_output": item.get("tracking_output"),
                "requires_primary_pdf_rerender": item.get("repair_target") in {"babeldoc_writeback_clear_source", "region_rerender_required", "paragraph_finder_required"},
                "readable_fallback_required": True,
            }
        )
    return {
        "version": 1,
        "status": "review_required" if tasks else "ok",
        "task_count": len(tasks),
        "tasks": tasks,
        "notes": [
            "本计划只生成诊断与降级交付任务；默认不对白底覆盖或直接修改主 PDF。",
            "主 PDF 中存在 critical page 可见英文残留时，strict delivery 必须保持 partial。",
        ],
    }


def write_readable_fallback_markdown(audit: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    raw_findings = audit.get("findings") if isinstance(audit.get("findings"), list) else []
    findings = [
        item
        for item in raw_findings
        if isinstance(item, dict) and (item.get("critical_page") or item.get("delivery_blocking"))
    ]
    path = output_dir / "visible_residue_readable_fallback.md"
    if not findings:
        return {"version": 1, "status": "skipped", "reason": "no_visible_residue_findings", "markdown": str(path)}
    lines = ["# 可见英文残留可读降级说明", ""]
    lines.append("以下内容来自 PDF backend 可见残留审计。原版式 PDF 未被自动覆盖；这些条目用于人工复核或 readable fallback。")
    for item in sorted(findings, key=lambda x: (_first_int(x.get("page")) or 999999, str(x.get("paragraph_debug_id") or ""))):
        lines.extend(
            [
                "",
                f"## Page {item.get('page') or 'unknown'} - {item.get('failure_type')}",
                "",
                f"- 修复目标：{item.get('repair_target')}",
                f"- 版面角色：{item.get('layout_role')}",
                f"- 可见英文：{item.get('visible_text') or ''}",
                f"- 已有中文译文：{item.get('tracking_output') or '（未能关联到 tracking 输出）'}",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"version": 1, "status": "ok", "markdown": str(path), "item_count": len(findings)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build visible English residue audit and PDF backend repair plan.")
    parser.add_argument("--pymupdf-audit")
    parser.add_argument("--poppler-audit")
    parser.add_argument("--visual-report")
    parser.add_argument("--tracking")
    parser.add_argument("--proxy-ledger")
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = build_visible_residue_audit(
        pymupdf_audit=load_json(Path(args.pymupdf_audit)) if args.pymupdf_audit else {},
        poppler_audit=load_json(Path(args.poppler_audit)) if args.poppler_audit else {},
        visual_report=load_json(Path(args.visual_report)) if args.visual_report else {},
        tracking_payload=load_json(Path(args.tracking)) if args.tracking else {},
        proxy_ledger=load_json(Path(args.proxy_ledger)) if args.proxy_ledger else {},
        output_dir=output_dir,
    )
    repair_plan = build_pdf_backend_repair_plan(audit)
    fallback = write_readable_fallback_markdown(audit, output_dir)
    (output_dir / "visible_residue_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "pdf_backend_repair_plan.json").write_text(json.dumps(repair_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "visible_residue_readable_fallback_manifest.json").write_text(json.dumps(fallback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit.get("status"), "finding_count": audit.get("finding_count")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
