#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import build_babeldoc_il_layout_map


EVIDENCE_SOURCE = "poppler_pdftotext_bbox_layout"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip().lower()


def is_meaningful_visible_text(text: str) -> bool:
    if len(text) < 4:
        return False
    if re.fullmatch(r"[\d\s.,:;()%/\-]+", text):
        return False
    if re.fullmatch(r"https?://\S+|\S+@\S+", text, flags=re.I):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]{3,}", text))


def visible_line_role(text: str) -> str:
    normalized = normalize_text(text)
    if normalized in {"sub-corpus", "number of texts", "tokens", "mean length"}:
        return "table_header"
    if re.search(r"\b(?:number of notable ai models|notable ai models \(% of total\)|by national affiliation|by sector and organization)\b", normalized, re.I):
        return "chart_label"
    if re.search(r"\b(?:overview|contents|chapter highlights|research and development)\b", normalized, re.I):
        return "toc_or_heading"
    if re.search(r"\b(?:doi\.org|humanities and social sciences|email:|@)\b", normalized, re.I):
        return "metadata_or_footer"
    return "body_prose" if len(normalized) > 20 else "unknown_visible_line"


def is_ai_index_policy_passthrough_visible_line(text: str, page: int | None) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    normalized = normalize_text(stripped)
    if not stripped:
        return False
    page_number = int(page or 0)
    if page_number in {5, 6}:
        if re.search(r"\b(?:LEAD AND EDITOR-IN-CHIEF|RESEARCH MANAGER|AFFILIATED RESEARCHERS|UNDERGRADUATE|GRADUATE)\b", stripped):
            return True
        if re.search(r"\b(?:Stanford University|IMT School|Advanced Studies Lucca|Northeastern|Minnesota|Washington)\b", stripped):
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}", stripped):
            return True
    if page_number in {8, 9}:
        if stripped in {"McKinsey & Company", "Quid", "Lightcast", "Zeki", "LinkedIn", "Epoch AI", "GitHub"}:
            return True
        if re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5}(?:,\s*[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,4})*", stripped):
            return True
    if page_number in {11, 12, 18, 19, 20} and re.search(
        r"\b(?:TO P TA K E AWAY S|A I I N D E X R E P O R T|N OTA B L E A I M O D E L S|R E S E A R C H A N D D E V E LO P M E N T)\b",
        stripped,
    ):
        return True
    if page_number == 11 and re.fullmatch(r"\d{1,2}\s+estimated", normalized):
        return True
    if page_number in {17, 18, 19, 20}:
        if re.fullmatch(r"(?:Canada|France|Hong Kong|Singapore|United Kingdom)\s+\d+", stripped):
            return True
        if re.fullmatch(r"Figure\s+1\.1\.\d+\s*\d?", stripped):
            return True
        if re.search(r"\b(?:Epoch AI|AI Index 2026|DeepMind|OpenAI|Google|Alibaba|Anthropic|xAI|LG AI Research|Meta|Tsinghua University|ByteDance|Moonshot|Nvidia|University of Illinois|Z\.ai|Zhipu AI|MiniMax|Shanghai AI Lab|Allen Institute for AI|Ai2|Ant Group|Baidu|CUHK Shenzhen Research Institute)\b", stripped):
            return True
        if normalized in {"nonpro t", "nonprofit", "industry", "academia"}:
            return True
        if re.search(r"\b(?:notable ai models|models \(% of total\)|national affiliation|sector and organization)\b", normalized):
            return True
    return False


def is_ai_index_policy_passthrough_source_visible(text: str, page: int | None) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    page_number = int(page or 0)
    if page_number == 4 and re.fullmatch(r"[A-Z][A-Za-z'’.-]+(?:\s+(?:and\s+)?[A-Z][A-Za-z'’.-]+){2,5}", stripped):
        return True
    if page_number in {8, 9} and re.search(r"\b(?:Loredana Fattorini|Yolanda Gil|Vanessa Parli|Ray(?:mond)? Perrault|Sha Sajadieh)\b", stripped):
        return True
    return False


def is_nature_policy_passthrough_source_visible(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    normalized = normalize_text(stripped)
    if re.search(r"\bhumanities and social sciences communications\b", normalized) and "doi.org/10.1057/s41599-026-06630-4" in normalized:
        return True
    return False


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _float_attr(node: ET.Element, name: str) -> float | None:
    value = node.attrib.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _bbox_from_node(node: ET.Element) -> list[float] | None:
    values = [_float_attr(node, key) for key in ["xMin", "yMin", "xMax", "yMax"]]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _page_number_by_identity(root: ET.Element) -> dict[int, tuple[int, float | None, float | None]]:
    pages: dict[int, tuple[int, float | None, float | None]] = {}
    page_index = 0
    for node in root.iter():
        if _local_name(node.tag) != "page":
            continue
        page_index += 1
        pages[id(node)] = (page_index, _float_attr(node, "width"), _float_attr(node, "height"))
    return pages


def _parent_map(root: ET.Element) -> dict[int, ET.Element]:
    return {id(child): parent for parent in root.iter() for child in parent}


def _page_info_for_line(line: ET.Element, parents: dict[int, ET.Element], pages: dict[int, tuple[int, float | None, float | None]]) -> tuple[int, float | None, float | None]:
    current: ET.Element | None = line
    while current is not None:
        page_info = pages.get(id(current))
        if page_info:
            return page_info
        current = parents.get(id(current))
    return (0, None, None)


def _parse_xml_lenient(content: str) -> ET.Element:
    def strip_invalid_xml_chars(value: str) -> str:
        return re.sub(
            r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]",
            "",
            value,
        )
    try:
        return ET.fromstring(strip_invalid_xml_chars(content))
    except ET.ParseError:
        # pdftotext normally emits XHTML. If a local build emits named HTML
        # entities not accepted by XML, unescape them and try one more time.
        return ET.fromstring(strip_invalid_xml_chars(html.unescape(content)))


def parse_bbox_layout(content: str) -> list[dict[str, Any]]:
    root = _parse_xml_lenient(content)
    parents = _parent_map(root)
    pages = _page_number_by_identity(root)
    lines: list[dict[str, Any]] = []
    line_index_by_page: dict[int, int] = {}
    for line in root.iter():
        if _local_name(line.tag) != "line":
            continue
        page, page_width, page_height = _page_info_for_line(line, parents, pages)
        line_index_by_page[page] = line_index_by_page.get(page, 0) + 1
        words: list[dict[str, Any]] = []
        for word in line:
            if _local_name(word.tag) != "word":
                continue
            text = "".join(word.itertext()).strip()
            if not text:
                continue
            words.append({"text": text, "bbox": _bbox_from_node(word)})
        if words:
            text = " ".join(word["text"] for word in words).strip()
        else:
            text = " ".join(part.strip() for part in line.itertext() if part.strip())
        if not text:
            continue
        lines.append(
            {
                "page": page,
                "line_index": line_index_by_page[page] - 1,
                "text": text,
                "normalized_text": normalize_text(text),
                "bbox": _bbox_from_node(line),
                "page_width": page_width,
                "page_height": page_height,
                "words": words,
                "word_count": len(words),
            }
        )
    return lines


def pdftotext_version(binary: str) -> str | None:
    result = subprocess.run([binary, "-v"], capture_output=True, text=True, timeout=10, check=False)
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    return output.splitlines()[0] if output else None


def extract_bbox_lines(pdf_path: Path, *, max_pages: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    binary = shutil.which("pdftotext")
    if not binary:
        raise FileNotFoundError("pdftotext_unavailable")
    if not pdf_path.exists():
        raise FileNotFoundError(str(pdf_path))
    with tempfile.TemporaryDirectory(prefix="paper_translation_poppler_") as tmp:
        out_path = Path(tmp) / "bbox.xhtml"
        cmd = [binary, "-bbox-layout"]
        if max_pages is not None:
            cmd.extend(["-f", "1", "-l", str(max_pages)])
        cmd.extend([str(pdf_path), str(out_path)])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "pdftotext_bbox_layout_failed")
        content = out_path.read_text(encoding="utf-8", errors="replace")
    metadata = {"binary": binary, "tool_version": pdftotext_version(binary)}
    return parse_bbox_layout(content), metadata


def tracking_text_blob(tracking_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for row in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        for key in ["input", "output", "pdf_unicode"]:
            value = normalize_text(str(row.get(key) or ""))
            if value:
                chunks.append(value)
    return "\n".join(chunks)


def visible_text_not_tracked(source_lines: list[dict[str, Any]], tracking_payload: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    blob = tracking_text_blob(tracking_payload)
    findings: list[dict[str, Any]] = []
    for row in source_lines:
        normalized = str(row.get("normalized_text") or "")
        if not is_meaningful_visible_text(normalized):
            continue
        if is_ai_index_policy_passthrough_visible_line(str(row.get("text") or ""), row.get("page")):
            continue
        if normalized in blob:
            continue
        if len(normalized) >= 20 and any(normalized[:20] in chunk or chunk[:20] in normalized for chunk in blob.splitlines()):
            continue
        findings.append(
            {
                "rule": "poppler_visible_text_not_tracked",
                "severity": "warn",
                "page": row.get("page"),
                "text": str(row.get("text") or "")[:240],
                "bbox": row.get("bbox"),
                "failure_stage": "paragraph_finder",
                "layout_role": visible_line_role(str(row.get("text") or "")),
                "evidence_source": EVIDENCE_SOURCE,
                "recommendation": "Poppler 可见文本未进入 BabelDOC tracking，需修 paragraph finder 或生成合成 tracking item。",
            }
        )
        if len(findings) >= limit:
            break
    return findings


def tracking_translated_but_source_visible(
    translated_lines: list[dict[str, Any]],
    tracking_payload: dict[str, Any],
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    visible_lines = [row for row in translated_lines if is_meaningful_visible_text(str(row.get("normalized_text") or ""))]
    findings: list[dict[str, Any]] = []
    for tracked in build_babeldoc_il_layout_map.iter_tracking_paragraphs(tracking_payload):
        source = str(tracked.get("input") or tracked.get("pdf_unicode") or "")
        output = str(tracked.get("output") or "")
        source_norm = normalize_text(source)
        tracked_page = tracked.get("page")
        engine_id = str(tracked.get("engine_block_id") or tracked.get("block_id") or "")
        if len(source_norm) < 20 or not re.search(r"[\u4e00-\u9fff]", output):
            continue
        if normalize_text(output) == source_norm:
            continue
        for line in visible_lines:
            if not pages_compatible_for_tracking(tracked_page, line.get("page"), engine_id):
                continue
            line_norm = str(line.get("normalized_text") or "")
            if len(line_norm) < 20:
                continue
            visible_text = str(line.get("text") or "")
            if is_ai_index_policy_passthrough_source_visible(visible_text, line.get("page")):
                continue
            if is_nature_policy_passthrough_source_visible(visible_text):
                continue
            source_anchor = source_norm[: min(60, len(source_norm))]
            line_anchor = line_norm[: min(60, len(line_norm))]
            token_overlap = len(set(line_norm.split()[:12]) & set(source_norm.split()[:18]))
            if line_norm in source_norm or source_norm.startswith(line_anchor[:40]) or source_anchor in line_norm or token_overlap >= 5:
                findings.append(
                    {
                        "rule": "poppler_tracking_translated_but_source_visible",
                        "severity": "blocking",
                        "page": line.get("page"),
                        "paragraph_debug_id": tracked.get("debug_id") or tracked.get("paragraph_debug_id"),
                        "text": str(line.get("text") or "")[:240],
                        "tracking_output": output[:240],
                        "bbox": line.get("bbox"),
                        "failure_stage": "paint",
                        "layout_role": tracked.get("layout_role") or tracked.get("layout_label") or visible_line_role(source),
                        "evidence_source": EVIDENCE_SOURCE,
                        "recommendation": "Poppler 仍能看到已翻译 tracking 对应的英文源文，需修 writeback/paint 或原文本清除。",
                    }
                )
                break
        if len(findings) >= limit:
            break
    return findings


def pages_compatible_for_tracking(tracked_page: Any, visible_page: Any, engine_id: str = "") -> bool:
    if tracked_page in (None, "") or visible_page in (None, ""):
        return True
    try:
        tracked = int(tracked_page)
        visible = int(visible_page)
    except (TypeError, ValueError):
        return str(tracked_page) == str(visible_page)
    if tracked == visible:
        return True
    return engine_id.startswith("cross_page:") and visible in {tracked - 1, tracked + 1}


def _line_center_y(row: dict[str, Any]) -> float | None:
    bbox = row.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        return (float(bbox[1]) + float(bbox[3])) / 2.0
    except (TypeError, ValueError):
        return None


def _has_translated_toc_title_for_number(number_row: dict[str, Any], translated_lines: list[dict[str, Any]]) -> bool:
    bbox = number_row.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    try:
        page = int(number_row.get("page") or 0)
        number_x0 = float(bbox[0])
        center_y = _line_center_y(number_row)
    except (TypeError, ValueError):
        return False
    if center_y is None:
        return False
    for row in translated_lines:
        if int(row.get("page") or 0) != page:
            continue
        row_bbox = row.get("bbox")
        if not isinstance(row_bbox, (list, tuple)) or len(row_bbox) < 4:
            continue
        row_y = _line_center_y(row)
        if row_y is None or abs(row_y - center_y) > 8.5:
            continue
        text = str(row.get("text") or "").strip()
        normalized = normalize_text(text)
        if not normalized or re.fullmatch(r"\d{1,3}", normalized):
            continue
        try:
            row_x0 = float(row_bbox[0])
            row_x1 = float(row_bbox[2])
        except (TypeError, ValueError):
            continue
        if row_x0 < number_x0 - 12 or row_x1 <= number_x0 + 24:
            if re.search(r"[\u4e00-\u9fffA-Za-z]", text):
                return True
    return False


def _has_toc_page_context(page: int, lines: list[dict[str, Any]]) -> bool:
    page_lines = [str(row.get("text") or "") for row in lines if int(row.get("page") or 0) == page]
    blob = normalize_text(" ".join(page_lines))
    if re.search(r"\bcontents\b|目录|章节要点|chapter highlights", blob, re.I):
        return True
    return False


def toc_page_number_unpaired(
    source_lines: list[dict[str, Any]],
    translated_lines: list[dict[str, Any]] | None = None,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidate_lines = translated_lines if translated_lines is not None else source_lines
    for row in candidate_lines:
        text = str(row.get("text") or "").strip()
        if not re.fullmatch(r"\d{1,3}", text):
            continue
        bbox = row.get("bbox")
        page_width = float(row.get("page_width") or 0)
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4 or page_width <= 0:
            continue
        try:
            x0 = float(bbox[0])
        except (TypeError, ValueError):
            continue
        if x0 < page_width * 0.55:
            continue
        context_lines = translated_lines if translated_lines is not None else source_lines
        if not _has_toc_page_context(int(row.get("page") or 0), context_lines):
            continue
        if translated_lines is not None and _has_translated_toc_title_for_number(row, translated_lines):
            continue
        findings.append(
            {
                "rule": "poppler_toc_page_number_unpaired",
                "severity": "warn",
                "page": row.get("page"),
                "text": text,
                "bbox": bbox,
                "failure_stage": "paragraph_finder",
                "layout_role": "toc_page_number",
                "evidence_source": EVIDENCE_SOURCE,
                "recommendation": "Poppler 检测到右侧独立页码列；需确认 BabelDOC 是否绑定到 TOC row。",
            }
        )
        if len(findings) >= limit:
            break
    return findings


def build_audit_from_lines(
    *,
    source_pdf: Path | None,
    translated_pdf: Path | None,
    source_lines: list[dict[str, Any]],
    translated_lines: list[dict[str, Any]],
    tracking_payload: dict[str, Any] | None = None,
    tool_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tracking = tracking_payload if isinstance(tracking_payload, dict) else {}
    findings: list[dict[str, Any]] = []
    if tracking:
        findings.extend(visible_text_not_tracked(source_lines, tracking))
        findings.extend(tracking_translated_but_source_visible(translated_lines, tracking))
    findings.extend(toc_page_number_unpaired(source_lines, translated_lines))
    has_blocking = any(item.get("severity") == "blocking" for item in findings)
    metadata = tool_metadata if isinstance(tool_metadata, dict) else {}
    return {
        "version": 1,
        "status": "partial" if has_blocking else "warn" if findings else "ok",
        "tool": "pdftotext",
        "tool_version": metadata.get("tool_version"),
        "source_pdf": str(source_pdf) if source_pdf else None,
        "translated_pdf": str(translated_pdf) if translated_pdf else None,
        "source_line_count": len(source_lines),
        "translated_line_count": len(translated_lines),
        "finding_count": len(findings),
        "blocking_finding_count": sum(1 for item in findings if item.get("severity") == "blocking"),
        "findings": findings,
        "source_lines": source_lines[:1000],
        "translated_lines": translated_lines[:1000],
    }


def build_poppler_text_bbox_audit(
    *,
    source_pdf: Path | None = None,
    translated_pdf: Path | None = None,
    tracking_payload: dict[str, Any] | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    binary = shutil.which("pdftotext")
    if not binary:
        return {"version": 1, "status": "skipped", "reason": "pdftotext_unavailable", "findings": []}
    try:
        source_lines, metadata = extract_bbox_lines(source_pdf, max_pages=max_pages) if source_pdf else ([], {"binary": binary, "tool_version": pdftotext_version(binary)})
        translated_lines, translated_metadata = extract_bbox_lines(translated_pdf, max_pages=max_pages) if translated_pdf else ([], metadata)
        metadata = {**metadata, **{key: value for key, value in translated_metadata.items() if value}}
    except Exception as exc:  # noqa: BLE001
        return {
            "version": 1,
            "status": "error",
            "reason": f"pdftotext_bbox_layout_failed: {exc}",
            "source_pdf": str(source_pdf) if source_pdf else None,
            "translated_pdf": str(translated_pdf) if translated_pdf else None,
            "findings": [],
        }
    return build_audit_from_lines(
        source_pdf=source_pdf,
        translated_pdf=translated_pdf,
        source_lines=source_lines,
        translated_lines=translated_lines,
        tracking_payload=tracking_payload,
        tool_metadata=metadata,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Poppler pdftotext -bbox-layout side-channel audit.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf")
    parser.add_argument("--tracking")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_poppler_text_bbox_audit(
        source_pdf=Path(args.source_pdf),
        translated_pdf=Path(args.translated_pdf) if args.translated_pdf else None,
        tracking_payload=build_babeldoc_il_layout_map.load_json(Path(args.tracking)) if args.tracking else {},
        max_pages=args.max_pages,
    )
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": payload.get("status")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
