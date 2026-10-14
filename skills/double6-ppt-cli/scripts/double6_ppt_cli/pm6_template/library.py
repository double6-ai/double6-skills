"""analyze / scaffold / check for the PM6 template-fill backend (replaces v4.8 template_fill_pptx).

Signatures intentionally mirror the removed upstream package so ``template_workflow`` can swap
backends: ``analyze_pptx(path)``, ``scaffold_plan(library, content, include_empty=...)``,
``check_plan(library, plan)``.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .ooxml import EMU_PER_PT, NS, Package, cnvpr, iter_shapes, placeholder, q, txbody_text
from .style import fit_context
from .textfit import fit, levels_are_implicit

LIBRARY_SCHEMA = "double6_pm6_slide_library.v1"
PLAN_SCHEMAS = {"template_fill_pptx_plan.v1", "double6_pm6_template_plan.v1"}
SLOT_RE = re.compile(r"s(\d+)_sh(\d+)")
TABLE_RE = re.compile(r"s(\d+)_tbl(\d+)")
CHART_RE = re.compile(r"s(\d+)_ch(\d+)")
SYSTEM_PH = {"dt", "ftr", "sldNum", "hdr"}
TOC_RE = re.compile(r"(目录|议程|agenda|contents|outline)", re.I)


def _px(emu: float, canvas_w_emu: int) -> int:
    return int(round(emu / canvas_w_emu * 1280))


def _chart_data(pkg: Package, slide_part: str, frame) -> dict[str, Any] | None:
    chart = frame.xpath(".//c:chart/@r:id", namespaces=NS)
    if not chart:
        return None
    rels = pkg.rels(slide_part)
    part = rels.get(chart[0], (None, None, None))[1]
    if not part or part not in pkg.entries:
        return None
    root = pkg.xml(part)
    series = []
    categories: list[str] = []
    kinds = sorted({etree_local(n) for n in root.xpath(".//c:plotArea/*[substring(local-name(), string-length(local-name()) - 4) = 'Chart']", namespaces=NS)})
    for ser in root.xpath(".//c:plotArea/*/c:ser", namespaces=NS):
        name = "".join(ser.xpath("./c:tx//c:v/text()", namespaces=NS))
        if not categories:
            categories = [str(v) for v in ser.xpath("./c:cat//c:pt/c:v/text()", namespaces=NS)]
        values = [v for v in ser.xpath("./c:val//c:pt/c:v/text()", namespaces=NS)]
        series.append({"name": name, "values": [float(v) for v in values]})
    return {"part": part, "chart_types": kinds, "categories": categories, "series": series}


def etree_local(node) -> str:
    return node.tag.split("}", 1)[-1]


def analyze_pptx(pptx: Path | str) -> dict[str, Any]:
    pptx = Path(pptx)
    pkg = Package.open(pptx)
    cw, ch = pkg.slide_size()
    slides = []
    for index, part in enumerate(pkg.slide_parts(), 1):
        root = pkg.xml(part)
        slots, tables, charts, pictures, links = [], [], [], [], []
        texts = []
        for element in iter_shapes(root.find("./p:cSld/p:spTree", NS)):
            c = cnvpr(element)
            if c is None:
                continue
            sid = int(c.get("id"))
            tag = etree_local(element)
            if c.find(q("a", "hlinkClick")) is not None:
                links.append({"drawingml_id": sid, "action": c.find(q("a", "hlinkClick")).get("action")})
            if tag == "sp" and element.find(q("p", "txBody")) is not None:
                ph = placeholder(element)
                text = txbody_text(element)
                ctx = fit_context(pkg, part, element)
                paragraphs = element.findall("./p:txBody/a:p", NS)
                role = "system" if ph and ph[0] in SYSTEM_PH else (
                    "title_candidate" if ph and ph[0] in ("title", "ctrTitle") else
                    "body_candidate" if ph else "label_candidate")
                geom = ctx["box"] if ctx else None
                slots.append({
                    "slot_id": f"s{index:02d}_sh{sid}", "drawingml_id": sid, "name": c.get("name", ""),
                    "role": role, "placeholder": list(ph) if ph else None, "text": text,
                    "paragraph_count": len([p for p in paragraphs if "".join(p.xpath('.//a:t/text()', namespaces=NS)).strip()]),
                    "geometry": {k: _px(geom[k2] * EMU_PER_PT, cw) for k, k2 in (("x", "x_pt"), ("y", "y_pt"), ("width", "w_pt"), ("height", "h_pt"))} if geom else None,
                    "text_metrics": {"font_size_px": round(ctx["levels"]["0"]["sz"] * 4 / 3, 2) if ctx else None,
                                     "paragraph_count": len(paragraphs)},
                    "fit_context": ctx,
                })
                if text.strip():
                    texts.append(text)
            elif tag == "graphicFrame" and element.find(".//a:tbl", NS) is not None:
                rows = element.findall(".//a:tbl/a:tr", NS)
                cells, slaves = [], []
                for r_i, tr in enumerate(rows):
                    row = []
                    for c_i, tc in enumerate(tr.findall(q("a", "tc"))):
                        row.append("\n".join("".join(p.xpath(".//a:t/text()", namespaces=NS)) for p in tc.findall("./a:txBody/a:p", NS)))
                        if tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true"):
                            slaves.append([r_i, c_i])
                    cells.append(row)
                tables.append({"table_id": f"s{index:02d}_tbl{sid}", "drawingml_id": sid, "name": c.get("name", ""),
                               "rows": len(cells), "cols": max((len(r) for r in cells), default=0), "cells": cells, "merge_slaves": slaves})
            elif tag == "graphicFrame":
                data = _chart_data(pkg, part, element)
                if data:
                    charts.append({"chart_id": f"s{index:02d}_ch{sid}", "drawingml_id": sid, "name": c.get("name", ""), **data})
            elif tag == "pic":
                pictures.append({"drawingml_id": sid, "name": c.get("name", "")})
        summary = "\n".join(texts)
        n = len(pkg.slide_parts())
        if index == 1:
            page_type = "cover_candidate"
        elif TOC_RE.search(summary[:80]):
            page_type = "toc_candidate"
        elif tables or charts:
            page_type = "data_candidate"
        elif index == n:
            page_type = "closing_candidate"
        elif len([s for s in slots if s["text"].strip()]) <= 2:
            page_type = "section_candidate"
        else:
            page_type = "content_candidate"
        slides.append({"slide_index": index, "slide_part": part, "page_type": page_type, "text_summary": summary,
                       "slots": slots, "tables": tables, "charts": charts, "pictures": pictures, "links": links})
    return {
        "schema": LIBRARY_SCHEMA, "source_pptx": str(pptx), "slide_count": len(slides),
        "canvas_px": {"width": 1280, "height": int(round(ch / cw * 1280))},
        "slides": slides,
        "plan_contract": {"schema": "template_fill_pptx_plan.v1", "slides": [{
            "source_slide": 1, "purpose": "cover / section / content / closing",
            "replacements": [{"slot_id": "s01_sh2", "text": "new text (\\n = new paragraph, leading \\t = list level)"}],
            "table_edits": [{"table_id": "s01_tbl3", "cells": [{"row": 0, "col": 0, "text": "cell"}]}],
            "chart_edits": [{"chart_id": "s01_ch4", "categories": ["A", "B"], "series": [{"name": "S1", "values": [1, 2]}]}]}]},
    }


def scaffold_plan(library: dict[str, Any], content: Any = None, include_empty: bool = True) -> dict[str, Any]:
    slides = []
    for slide in library["slides"]:
        reps = [{"slot_id": s["slot_id"], "old_text": s["text"], "text": s["text"]}
                for s in slide["slots"] if s["role"] != "system" and (include_empty or s["text"].strip())]
        slides.append({"source_slide": slide["slide_index"], "purpose": slide["page_type"],
                       "layout_rationale": {"layout_pattern": slide["page_type"], "why_fit": "", "risk": "unknown"},
                       "replacements": reps, "table_edits": [], "chart_edits": []})
    return {"schema": "template_fill_pptx_plan.v1", "status": "draft", "source_pptx": library.get("source_pptx"),
            "accepted_warnings": [], "slides": slides}


def _norm(text: str) -> str:
    """Whitespace-insensitive fingerprint (profiles may join paragraphs without separators)."""
    return re.sub(r"\s+", "", str(text or ""))


def check_plan(library: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    add = results.append
    if plan.get("schema") not in PLAN_SCHEMAS:
        add({"status": "ERROR", "code": "plan_schema_unsupported", "schema": plan.get("schema")})
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        add({"status": "ERROR", "code": "plan_has_no_slides"})
        slides = []
    by_index = {s["slide_index"]: s for s in library["slides"]}
    for plan_slide, item in enumerate(slides, 1):
        try:
            source_slide = int(item.get("source_slide", 0))
        except (TypeError, ValueError):
            source_slide = 0
        lib = by_index.get(source_slide)
        if lib is None:
            add({"status": "ERROR", "code": "source_slide_out_of_range", "plan_slide": plan_slide, "source_slide": source_slide})
            continue
        slots = {s["slot_id"]: s for s in lib["slots"]}
        seen = Counter()
        for rep in item.get("replacements", []) or []:
            slot_id = str(rep.get("slot_id") or "")
            seen[slot_id] += 1
            m = SLOT_RE.fullmatch(slot_id)
            base = {"plan_slide": plan_slide, "source_slide": source_slide, "slot_id": slot_id}
            if not m:
                add({"status": "ERROR", "code": "slot_id_invalid", **base})
                continue
            if int(m.group(1)) != source_slide:
                add({"status": "ERROR", "code": "cross_slide_slot", **base,
                     "message": "slot belongs to another template slide; provenance must stay on the same slide"})
                continue
            slot = slots.get(slot_id)
            if slot is None:
                if not rep.get("optional"):
                    add({"status": "ERROR", "code": "slot_not_found", **base})
                continue
            if seen[slot_id] > 1:
                add({"status": "ERROR", "code": "duplicate_slot_replacement", **base})
                continue
            if slot["role"] == "system":
                add({"status": "WARN", "code": "system_placeholder_replaced", **base})
            if "old_text" in rep and _norm(rep.get("old_text")) != _norm(slot["text"]):
                add({"status": "ERROR", "code": "stale_old_text", **base, "expected": slot["text"], "got": rep.get("old_text")})
                continue
            text = str(rep.get("text") if rep.get("text") is not None else "")
            if not text.strip() or text == slot["text"]:
                add({"status": "OK", "code": "text_fit", **base, "fit": "unchanged" if text == slot["text"] else "cleared"})
                continue
            ctx = slot.get("fit_context")
            if not ctx:
                add({"status": "WARN", "code": "text_fit_unknown", **base})
                continue
            levels = rep.get("levels")
            if levels is not None and (not isinstance(levels, list) or len(levels) != len(text.split("\n"))):
                add({"status": "ERROR", "code": "levels_length_mismatch", **base})
                continue
            if levels_are_implicit(ctx, text, levels):
                add({"status": "WARN", "code": "implicit_list_levels", **base,
                     "template_levels": ctx.get("template_paragraph_levels"),
                     "message": "template slot mixes list levels; new lines inherit them by position. Use leading tabs or a levels list"})
            report = fit(ctx, text, levels=levels)
            status = {"fits": "OK", "grow": "OK", "autofit": "WARN", "shrunk": "WARN", "overflow": "ERROR"}[report["status"]]
            if status == "ERROR" and slot["text"].strip():
                # Same rule as the upstream roundtrip checker: never worse than the template's own sample.
                baseline = fit(ctx, slot["text"], policy="never-shrink")
                if baseline["status"] == "overflow" and report.get("ratio", 99) <= baseline.get("ratio", 0) + 1e-6:
                    status = "WARN"
                    report["status"] = "overflow_like_template"
            add({"status": status, "code": "text_fit", **base, "role": slot["role"], "fit": report["status"],
                 "font_scale": report["font_scale"], "ratio": report.get("ratio"), "need_h_pt": report["need_h_pt"],
                 "avail_h_pt": report["avail_h_pt"], "line_count": report["line_count"], "engine": report["engine"],
                 "old_text": slot["text"], "new_text": text,
                 "message": {"fits": "fits the native frame", "grow": "frame grows (spAutoFit) within slide",
                             "autofit": "fits with native normAutofit shrink", "shrunk": "fits only with explicit size reduction",
                             "overflow": "does not fit even at minimum scale: shorten, split, or pick a larger layout",
                             "overflow_like_template": "overflows, but no more than the template's own sample text"}[report["status"]]})
        tables = {t["table_id"]: t for t in lib["tables"]}
        for edit in item.get("table_edits", []) or []:
            tid = str(edit.get("table_id") or "")
            m = TABLE_RE.fullmatch(tid)
            base = {"plan_slide": plan_slide, "source_slide": source_slide, "table_id": tid}
            if not m or int(m.group(1)) != source_slide or tid not in tables:
                add({"status": "ERROR", "code": "table_not_found_on_slide", **base})
                continue
            t = tables[tid]
            for cell in edit.get("cells", []) or []:
                r, c = int(cell.get("row", -1)), int(cell.get("col", -1))
                if not (0 <= r < t["rows"] and 0 <= c < len(t["cells"][r])):
                    add({"status": "ERROR", "code": "table_cell_out_of_range", **base, "row": r, "col": c})
                elif [r, c] in t["merge_slaves"]:
                    add({"status": "ERROR", "code": "table_cell_is_merge_slave", **base, "row": r, "col": c})
            add({"status": "OK", "code": "table_edit", **base, "cells": len(edit.get("cells", []) or [])})
        charts = {c["chart_id"]: c for c in lib["charts"]}
        for edit in item.get("chart_edits", []) or []:
            cid = str(edit.get("chart_id") or "")
            m = CHART_RE.fullmatch(cid)
            base = {"plan_slide": plan_slide, "source_slide": source_slide, "chart_id": cid}
            if not m or int(m.group(1)) != source_slide or cid not in charts:
                add({"status": "ERROR", "code": "chart_not_found_on_slide", **base})
                continue
            cats = edit.get("categories") or []
            bad = [s.get("name") for s in edit.get("series", []) or [] if len(s.get("values") or []) != len(cats)
                   or not all(isinstance(v, (int, float)) for v in s.get("values") or [])]
            add({"status": "ERROR" if bad or not cats else "OK", "code": "chart_edit", **base, "bad_series": bad})
    summary = Counter(r["status"] for r in results)
    return {"schema": "double6_pm6_check_report.v1", "results": results,
            "summary": {"ok": summary.get("OK", 0), "warn": summary.get("WARN", 0), "error": summary.get("ERROR", 0)}}
