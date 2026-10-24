"""复用冻结扫描区域，在新目录应用有依据的返修并重建单语/双语候选。"""
from __future__ import annotations

import argparse
import json
import statistics
import math
from pathlib import Path
from typing import Any

from assess_delivery import inspect_pdf, read_object, sha256
from build_bilingual_pdf import bilingual_direction, build_en_left_zh_right_pdf
from scanned_raster.pipeline import _render_translated_pdf, _normalize_inline_math_for_text_layer
from scanned_raster.quality_gate import evaluate_scan_quality_gate
from scanned_raster.scientific_integrity import scientific_integrity_findings
from scanned_raster.paragraph_recovery import coalesce_mineru_text_lines
from scanned_raster.name_columns import prepare_name_columns, preserve_source_region, vertical_margin_reason
from scanned_raster.frontmatter import prepare_centered_frontmatter


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_repairs(regions: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    # JSON deep copy 防止部分校验失败时污染调用者持有的原始区域。
    result = json.loads(json.dumps(regions))
    by_id = {r["region_id"]: r for r in result}
    if len(by_id) != len(result):
        raise ValueError("duplicate region identity")
    seen = set()
    for repair in manifest["repairs"]:
        rid = repair["region_id"]
        if rid in seen or rid not in by_id:
            raise ValueError("unknown or repeated repair region")
        seen.add(rid)
        evidence = repair["source_evidence"]
        if sha256(Path(evidence["path"])) != evidence["sha256"] or not repair.get("reason"):
            raise ValueError("missing or stale source review evidence")
        row = by_id[rid]
        updates = repair["updates"]
        if not updates or set(updates) - {"ocr_text", "normalized_text", "translation"} or set(updates) != set(repair["before"]):
            raise ValueError("repair fields must be explicit and limited to reviewed text")
        for key, value in repair["before"].items():
            if row.get(key) != value or not isinstance(updates[key], str):
                raise ValueError("repair does not match frozen region")
        row["reviewed_text_repair"] = repair
        row.update(updates)
        row["reviewed_translation_before_normalization"] = row.get("translation", "")
        row["translation"] = _normalize_inline_math_for_text_layer(row.get("translation", ""))
        if scientific_integrity_findings(row.get("normalized_text") or row.get("ocr_text", ""), row.get("translation", "")):
            raise ValueError("targeted repair still fails scientific symbol integrity")
        row.update(status="translated", skip_reason=None, in_destroke_mask=True)
    for preservation in manifest.get("preservations", []):
        rid = preservation["region_id"]
        if rid in seen or rid not in by_id or preservation.get("category") not in {"archival_annotation", "author_identity"}:
            raise ValueError("unknown, repeated or unsupported preservation")
        seen.add(rid)
        evidence = preservation["source_evidence"]
        if sha256(Path(evidence["path"])) != evidence["sha256"] or not preservation.get("reason"):
            raise ValueError("missing or stale preservation evidence")
        row = by_id[rid]
        before = preservation.get("before", {})
        if set(before) != {"ocr_text", "translation"} or any(row.get(k) != v for k,v in before.items()):
            raise ValueError("preservation does not match frozen source and translation")
        row["reviewed_source_preservation"] = preservation
        preserve_source_region(row, "reviewed_source_preservation:" + preservation["category"])
    return result


def merge_reviewed_bands(regions: list[dict[str, Any]], plans: list[dict]) -> list[dict[str, Any]]:
    """将审校后的同一 RapidOCR 段落移到末带排版，源行遮罩保持原位。"""
    import fitz
    if not isinstance(plans, list) or len(plans) > 20:
        raise ValueError("bounded reviewed paragraph merges required")
    result = json.loads(json.dumps(regions))
    for plan in plans:
        evidence = plan["source_evidence"]
        if not plan.get("reason") or sha256(Path(evidence["path"])) != evidence["sha256"]:
            raise ValueError("missing or stale paragraph review evidence")
        ids = plan["region_ids"]
        if not isinstance(ids, list) or not 2 <= len(ids) <= 8 or len(set(ids)) != len(ids):
            raise ValueError("explicit unique paragraph band identities required")
        positions = [i for i, r in enumerate(result) if r["region_id"] in ids]
        group = [result[i] for i in positions]
        if ([r["region_id"] for r in group] != ids or positions != list(range(positions[0], positions[0]+len(ids)))):
            raise ValueError("complete consecutive paragraph bands required")
        first = group[0]; n = len(group)
        identity = lambda r: (r.get("page"), r.get("source_pdf_sha256"), r.get("translation_group_id"))
        if (not first.get("translation_group_id") or not first.get("source_pdf_sha256")
                or any(identity(r) != identity(first) or r.get("engine") != "rapidocr"
                       or r.get("layout_role") != "text" or r.get("status") != "translated"
                       or not r.get("translation") or r.get("paragraph_band_count") != n
                       or r.get("paragraph_band_index") != i for i, r in enumerate(group))):
            raise ValueError("same verified RapidOCR paragraph required")
        # 末带原排版框是唯一可选落点，不接受任意扩大遮盖区域。
        layout = list(group[-1].get("original_layout_bbox") or group[-1]["bbox"])
        rect = fitz.Rect(layout)
        if rect.is_empty or not all(math.isfinite(x) for x in rect):
            raise ValueError("invalid final paragraph band")
        clips = []
        for row in result:
            if row["region_id"] in ids or row.get("page") != first.get("page"):
                continue
            peer = fitz.Rect(row.get("original_layout_bbox") or row["bbox"])
            if rect.intersects(peer):
                # OCR 相邻段底/顶边偶有不足 1pt 的量化重叠；仅收窄空白布局边，源去字行仍保留。
                if peer.y0 > rect.y0 and 0 < rect.y1 - peer.y0 <= 1:
                    clips.append({'peer_region_id':row['region_id'], 'original_bottom':rect.y1,
                                  'new_bottom':peer.y0-1, 'reason':'subpoint_adjacent_band_boundary'})
                    rect.y1 = peer.y0-1
                else:
                    raise ValueError(f"merged paragraph layout overlaps another region: {row['region_id']}")
        layout = list(rect)
        text = ''.join(r['translation'] for r in group)
        source = ' '.join(r.get('normalized_text') or r['ocr_text'] for r in group)
        lines = [line for r in group for line in (r.get('source_line_evidence') or r.get('source_regions') or [])]
        if not lines or len(lines) > 32 or max(len(text), len(source)) > 4000:
            raise ValueError("bounded source line evidence required")
        if scientific_integrity_findings(source, text):
            raise ValueError("merged paragraph fails scientific symbol integrity")
        source_box = [min(r['bbox'][0] for r in group), min(r['bbox'][1] for r in group),
                      max(r['bbox'][2] for r in group), max(r['bbox'][3] for r in group)]
        row = dict(first)
        for key in ['render_bbox', 'source_geometry_expansion', 'mask_geometry', 'destroke_boxes', 'translation_raw',
                    'font_size', 'writeback_status', 'overflow', 'occluded', 'overlap', 'reviewed_text_repair']:
            row.pop(key, None)
        rid = first['translation_group_id'] + '-reviewed-paragraph'
        row.update(region_id=rid, bbox=source_box, original_layout_bbox=layout, source_bbox=source_box,
                   ocr_text=' '.join(r['ocr_text'] for r in group), normalized_text=source,
                   translation=text, paragraph_source_text=source, paragraph_band_index=0, paragraph_band_count=1,
                   source_line_evidence=lines, source_regions=lines, source_line_count=len(lines),
                   source_line_height=statistics.median(line['bbox'][3]-line['bbox'][1] for line in lines),
                   source_region_ids=ids, source_bands=group, reviewed_paragraph_merge=plan,
                   grouping_policy='reviewed_rapidocr_complete_paragraph_last_band_v1', layout_boundary_clips=clips, in_destroke_mask=True)
        row['polygon'] = [[source_box[0],source_box[1]],[source_box[2],source_box[1]],
                          [source_box[2],source_box[3]],[source_box[0],source_box[3]]]
        result[positions[0]:positions[-1]+1] = [row]
    for order, row in enumerate(result):
        row['reading_order'] = order
    return result


def recover(source_run: Path, output: Path, repair_path: Path, *, max_pages: int = 5) -> dict[str, Any]:
    import fitz
    source_run, output = source_run.resolve(), output.resolve()
    if output.exists() or source_run in output.parents or not 1 <= max_pages <= 20:
        raise ValueError("fresh candidate outside source run and 1–20 page budget required")
    route = read_object(source_run / "route_manifest.json")
    source = Path(route["input_pdf"])
    info = inspect_pdf(source, max_pages)
    repair = read_object(repair_path)
    regions_path = source_run / "scan_regions.jsonl"
    if info["status"] != "ok" or route.get("document_route") != "scanned_raster" or route.get("dispatch_allowed") is not True:
        raise ValueError("verified bounded scanned route required")
    if repair["source_sha256"] != info["sha256"] or route["input_sha256"] != info["sha256"] or repair["regions_sha256"] != sha256(regions_path):
        raise ValueError("source or region SHA mismatch")
    frozen = {name: sha256(source_run / name) for name in ["route_manifest.json", "scan_regions.jsonl", "translated_scanned.pdf", "scan_quality_gate.json", "scan_parse_manifest.json"]}
    regions = [json.loads(line) for line in regions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(r.get("source_pdf_sha256") != info["sha256"] for r in regions):
        raise ValueError("region source identity mismatch")
    policies = repair.get("region_policy_passes", [])
    if (not isinstance(policies, list) or any(p not in {"scientific_name_columns", "vertical_marginalia", "centered_frontmatter"} for p in policies)
        or len(set(policies)) != len(policies)):
        raise ValueError("unsupported or repeated region policy")
    if "scientific_name_columns" in policies:
        regions = prepare_name_columns(regions)
    if "vertical_marginalia" in policies:
        for row in regions:
            reason = vertical_margin_reason(row)
            if reason:
                preserve_source_region(row, reason)
    if "centered_frontmatter" in policies:
        regions = prepare_centered_frontmatter(regions)
    grouping_pages = repair.get("coalesce_mineru_pages", [])
    if not isinstance(grouping_pages, list) or any(type(p) is not int or not 1 <= p <= info['page_count'] for p in grouping_pages) or len(set(grouping_pages)) != len(grouping_pages):
        raise ValueError("explicit unique bounded grouping pages required")
    if grouping_pages:
        regions = [row for page in range(1, info['page_count'] + 1) for row in (coalesce_mineru_text_lines([r for r in regions if r['page'] == page]) if page in grouping_pages else [r for r in regions if r['page'] == page])]
    repaired = apply_repairs(regions, repair)
    repaired = merge_reviewed_bands(repaired, repair.get("reviewed_paragraph_merges", []))
    if any(r.get('status') == 'pending' for r in repaired):
        raise ValueError("all regrouped paragraphs require reviewed translations")
    output.mkdir(parents=True)
    write(output / "route_manifest.json", route)
    receipt = {"status": "building", "source_run": str(source_run), "frozen_files": frozen,
               "repairs_sha256": sha256(repair_path), "repair_count": len(repair["repairs"]), "model_calls": 0,
               "reviewer_kind": "controller", "strict_promoted": False, "human_accepted": False}
    receipt['coalesce_mineru_pages'] = grouping_pages
    receipt['region_policy_passes'] = policies
    receipt['reviewed_paragraph_merges'] = repair.get('reviewed_paragraph_merges', [])
    receipt['preservation_count'] = len(repair.get('preservations', []))
    receipt['paragraph_groups'] = [{"region_id": r['region_id'], "source_region_ids": r['source_region_ids']} for r in repaired if r.get('grouping_policy')]
    write(output / "scan_recovery_receipt.json", receipt)
    primary = output / "translated_scanned.pdf"
    font = _render_translated_pdf(source, primary, repaired, dpi=144)
    (output / "scan_regions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in repaired), encoding="utf-8")
    with fitz.open(primary) as doc:
        gate = evaluate_scan_quality_gate(regions=repaired, extracted_text="\n".join(p.get_text() for p in doc), font_embedding=font, page_count=len(doc), source_page_count=info["page_count"])
    write(output / "scan_quality_gate.json", gate)
    parsed = read_object(source_run / "scan_parse_manifest.json")
    parsed.update(reviewed_region_repairs=str(output / "scan_recovery_receipt.json"), original_parse_manifest=str(source_run / "scan_parse_manifest.json"), render_font=font)
    write(output / "scan_parse_manifest.json", parsed)
    dual = output / "bilingual.review.pdf"
    write(output / "bilingual_pdf_manifest.json", build_en_left_zh_right_pdf(
        source, primary, dual, direction=bilingual_direction("en", "zh", basis="route_contract_scanned_raster_en_to_zh")))
    write(output / "render_manifest.json", {"status": "partial", "actual_render_source": "scanned_raster", "delivery_mode": "experimental_candidate_pending_review", "outputs": {"translated_pdf": str(primary), "standard_bilingual_pdf": str(dual)}})
    receipt.update(status="rendered_pending_review", gate_status=gate["status"], candidate_sha256=sha256(primary), original_unchanged=all(sha256(source_run / name) == value for name, value in frozen.items()))
    write(output / "scan_recovery_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repairs", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    result = recover(args.source_run, args.output, args.repairs, max_pages=args.max_pages)
    print(json.dumps({k: result[k] for k in ["status", "repair_count", "gate_status", "original_unchanged", "model_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
