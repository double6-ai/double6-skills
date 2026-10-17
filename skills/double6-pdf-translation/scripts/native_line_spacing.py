"""按冻结的完整印刷行调整行距；保持原页、段首及逐字形身份。"""
from __future__ import annotations
from stable_page_raster import stable_get_pixmap

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import fitz
import numpy as np
from fontTools.ttLib import TTFont

from daily_skill_research.project_layout import validate_output_path

from owned_font_unicode import bind_owned_font_unicode
from raw_link_actions import (copy_page_with_raw_actions, rebind_expected_link_actions,
                              verify_saved_link_actions)

SCHEMA = "native-line-spacing@1"
MAX_PAGES, MAX_ROWS, MAX_GLYPHS = 5, 400, 10000


def reference(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest()}


def checked_ref(record, maximum_bytes):
    path = Path(record["path"])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError("input_missing_or_over_budget")
    if reference(path)["sha256"] != record["sha256"]:
        raise ValueError("input_sha_changed")
    return path


def glyphs(page):
    result = []
    for span in page.get_texttrace():
        for code, gid, origin, bbox in span["chars"]:
            result.append({"unicode": code, "gid": gid, "origin": list(origin),
                           "bbox": list(bbox), "font": span["font"], "size": span["size"],
                           "color": list(span["color"]), "type": span["type"],
                           "direction": list(span["dir"]), "opacity": span["opacity"]})
    return result


def identity(c):
    return (c["unicode"], c["gid"], c["font"], round(c["size"], 3),
            tuple(round(v, 3) for v in c["color"]),
            *(round(v, 3) for v in c["origin"]))


def compare_glyphs(actual, expected, tolerance=.001):
    def style(c):
        return (c["unicode"], c["gid"], c["font"], round(c["size"], 3),
                tuple(round(v, 6) for v in c["color"]), c["type"],
                tuple(c.get("direction", [1, 0])), c.get("opacity", 1))
    aa, ee = defaultdict(list), defaultdict(list)
    for c in actual:
        aa[style(c)].append(c["origin"])
    for c in expected:
        ee[style(c)].append(c["origin"])
    if set(aa) != set(ee) or any(len(aa[k]) != len(ee[k]) for k in aa):
        changes = [{"style": k, "actual": aa.get(k, []), "expected": ee.get(k, [])}
                   for k in set(aa) | set(ee) if len(aa.get(k, [])) != len(ee.get(k, []))]
        raise ValueError("glyph_text_style_or_count_changed:"+json.dumps(changes[:10], ensure_ascii=False))
    error = 0.
    for k in aa:
        for a, e in zip(sorted(aa[k], key=lambda p: (p[1], p[0])),
                        sorted(ee[k], key=lambda p: (p[1], p[0]))):
            error = max(error, *(abs(a[i] - e[i]) for i in (0, 1)))
    if error >= tolerance:
        raise ValueError(f"glyph_coordinate_changed:{error}")
    return error


def validate_plan(plan):
    if plan.get("schema_version") != SCHEMA or plan.get("same_original_page_required") is not True:
        raise ValueError("invalid_spacing_schema_or_page_policy")
    ratio = plan.get("ratio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 1 <= ratio <= 1.2:
        raise ValueError("uniform_ratio_out_of_range")
    if not 0 < plan.get("maximum_baseline_drift_pt", 0) <= 60:
        raise ValueError("invalid_drift_limit")
    pages = plan.get("pages", [])
    if not 1 <= len(pages) <= MAX_PAGES or len({p["page"] for p in pages}) != len(pages):
        raise ValueError("page_budget_or_duplicate")
    if not 1 <= len(plan.get("fonts", {})) <= 8:
        raise ValueError("font_budget")
    for page in pages:
        rows = page["rows"]
        if not isinstance(page["page"], int) or page["page"] < 1 or not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError("row_or_page_budget")
        targets = [c for row in rows for c in row["characters"]]
        if not 1 <= len(targets) <= MAX_GLYPHS:
            raise ValueError("glyph_budget")
        if any(n != 1 and not chr(k[0]).isspace() for k, n in Counter(identity(c) for c in targets).items()):
            raise ValueError("duplicate_target_glyph")
        covered = []
        for fragment in page["paragraph_fragments"]:
            start, end = fragment["start_row"], fragment["end_row"]
            if not 0 <= start < end <= len(rows) or page["page"] not in fragment["source_page_set"]:
                raise ValueError("paragraph_origin_or_range")
            part = rows[start:end]
            if any(r["paragraph_id"] != fragment["id"] or r["line_index"] != i
                   for i, r in enumerate(part)):
                raise ValueError("paragraph_row_order")
            if not 0 < fragment["old_step_pt"] <= 100 or not math.isfinite(fragment["new_step_pt"]):
                raise ValueError("invalid_source_step")
            if abs(fragment["new_step_pt"] / fragment["old_step_pt"] - ratio) > .000001:
                raise ValueError("nonuniform_spacing")
            if abs(part[0]["delta_y"]) > .000001:
                raise ValueError("paragraph_start_moved")
            for i, row in enumerate(part):
                delta = i * fragment["old_step_pt"] * (ratio - 1)
                if (not math.isfinite(row["delta_y"]) or abs(delta - row["delta_y"]) > .002
                        or abs(row["delta_y"]) > plan["maximum_baseline_drift_pt"]):
                    raise ValueError("spacing_delta_or_drift")
                if abs(row["old_baseline"] - part[0]["old_baseline"] - i * fragment["old_step_pt"]) > .02:
                    raise ValueError("source_step_not_uniform")
            covered.extend(range(start, end))
        if sorted(covered) != list(range(len(rows))):
            raise ValueError("paragraph_coverage")
        for c in targets:
            if (c["font"] not in plan["fonts"] or c["type"] != 0 or c["unicode"] == 65533
                    or c.get("direction", [1, 0]) != [1, 0] or c.get("opacity", 1) != 1
                    or not 0 < c["size"] <= 72 or not 0 <= c["unicode"] <= 0x10ffff
                    or 0xd800 <= c["unicode"] <= 0xdfff or len(c["color"]) != 3):
                raise ValueError("unsupported_target_glyph")
            if not all(math.isfinite(v) for v in [*c["origin"], *c["bbox"], c["size"], *c["color"]]):
                raise ValueError("nonfinite_glyph_geometry")
        for row in rows:
            nonspace = [c for c in row["characters"] if not chr(c["unicode"]).isspace()]
            if not nonspace:
                raise ValueError("row_has_no_body_glyph")
            dominant_size = Counter(round(c["size"], 3) for c in nonspace).most_common(1)[0][0]
            body = [c for c in nonspace if round(c["size"], 3) == dominant_size]
            if any(abs(c["origin"][1]-row["old_baseline"]) > .002 for c in body):
                raise ValueError("row_body_baseline_mismatch")
            declared_scripts = row.get("verified_scripts", [])
            specs = {object_sha(identity(s["glyph"])): s for s in declared_scripts}
            if len(specs) != len(declared_scripts):
                raise ValueError("duplicate_script_evidence")
            used = set()
            for c in row["characters"]:
                offset = c["origin"][1]-row["old_baseline"]
                if abs(offset) <= .002:
                    continue
                key = object_sha(identity(c)); spec = specs.get(key)
                if (not spec or spec.get("host_baseline") != row["old_baseline"] or
                        abs(spec.get("relative_y", 100)-offset) > .001 or not spec.get("reason") or
                        abs(offset) > dominant_size or
                        (not chr(c["unicode"]).isspace() and not c["size"] < dominant_size)):
                    raise ValueError("script_host_evidence_required")
                checked_ref(spec["source_evidence"], 16 * 1024**2)
                used.add(key)
            if used != set(specs):
                raise ValueError("unused_or_duplicate_script_evidence")
            union = fitz.Rect(row["characters"][0]["bbox"])
            for c in row["characters"][1:]:
                union |= fitz.Rect(c["bbox"])
            if max(abs(union[i]-row["bbox"][i]) for i in range(4)) > .002:
                raise ValueError("row_bbox_not_actual_glyph_union")


def shifted_box(c, delta):
    return fitz.Rect(c["bbox"]) + (0, delta, 0, delta)


def geometry_guard(page, rows, protected):
    for i, row in enumerate(rows):
        moved = [shifted_box(c, row["delta_y"]) for c in row["characters"] if not chr(c["unicode"]).isspace()]
        if any(not page.rect.contains(b) for b in moved):
            raise ValueError("shifted_glyph_outside_page")
        obstacles = [fitz.Rect(c["bbox"]) for c in protected if not chr(c["unicode"]).isspace()]
        obstacles += [shifted_box(c, other["delta_y"]) for other in rows[i+1:]
                      for c in other["characters"] if not chr(c["unicode"]).isspace()]
        for b in moved:
            if any((b & o).width > .2 and (b & o).height > .2 for o in obstacles):
                raise ValueError("shifted_glyph_collision")
        for image in page.get_image_info():
            if any(b.intersects(fitz.Rect(image["bbox"])) for b in moved):
                raise ValueError("shifted_glyph_intersects_image")


def plain(value):
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, fitz.Point, fitz.Rect, fitz.Quad)):
        return [plain(v) for v in value]
    return value


def drawing_record(d):
    return plain({k: d.get(k) for k in ("type", "items", "rect", "color", "fill", "width", "lineCap",
                  "lineJoin", "dashes", "stroke_opacity", "fill_opacity", "closePath", "even_odd")})


def object_sha(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decorations(page, page_plan):
    rows = page_plan["rows"]
    lines, links = [], []
    specs = page_plan.get("underlines", [])
    declared = {s["source_drawing_sha256"]: s for s in specs}
    if len(declared) != len(specs):
        raise ValueError("duplicate_underline_declaration")
    seen = set()
    for drawing in page.get_drawings():
        if drawing["type"] == "f" and drawing.get("fill") == (1., 1., 1.):
            continue
        box = fitz.Rect(drawing["rect"]) + (-.6, -.6, .6, .6)
        hits = [r for r in rows if box.intersects(fitz.Rect(r["bbox"]))]
        if not hits:
            continue
        digest = object_sha(drawing_record(drawing))
        spec = declared.get(digest)
        if (not spec or spec.get("role") != "source_verified_underline" or not spec.get("reason")
                or not 0 <= spec.get("row_index", -1) < len(rows)):
            raise ValueError("drawing_requires_named_underline_evidence")
        checked_ref(spec["source_evidence"], 16 * 1024**2)
        if (len(hits) != 1 or drawing["type"] != "s" or drawing.get("fill") is not None
                or not drawing["items"] or any(item[0] != "l" or abs(item[1].y - item[2].y) > .001
                                                for item in drawing["items"]) or hits[0] is not rows[spec["row_index"]]):
            raise ValueError("unsupported_or_ambiguous_body_drawing")
        if digest in seen:
            raise ValueError("ambiguous_source_underline")
        seen.add(digest)
        lines.append({"drawing": drawing, "delta_y": hits[0]["delta_y"], "declaration": spec})
    if seen != set(declared):
        raise ValueError("declared_underline_not_found")
    specs = page_plan.get("uri_links", [])
    declared = {s["source_link_sha256"]: s for s in specs}
    if len(declared) != len(specs):
        raise ValueError("duplicate_link_declaration")
    seen = set()
    for link in page.get_links():
        hits = [r for r in rows if fitz.Rect(link["from"]).intersects(fitz.Rect(r["bbox"]))]
        if hits:
            digest = object_sha(link_identity(link))
            spec = declared.get(digest)
            if not spec or not spec.get("reason") or not 0 <= spec.get("row_index", -1) < len(rows):
                raise ValueError("link_requires_named_mapping")
            checked_ref(spec["source_evidence"], 16 * 1024**2)
            if not link.get("uri") or len(hits) != 1:
                raise ValueError("multirow_or_internal_link_requires_mapping")
            if hits[0] is not rows[spec["row_index"]] or digest in seen:
                raise ValueError("ambiguous_source_link")
            seen.add(digest)
            links.append({"link": link, "delta_y": hits[0]["delta_y"], "declaration": spec})
    if seen != set(declared):
        raise ValueError("declared_link_not_found")
    return lines, links


def link_identity(link):
    return (link["kind"], link.get("uri"), link.get("page"),
            tuple(round(v, 3) for v in link["from"]),
            tuple(link.get("to", ())), link.get("zoom"), link.get("nameddest"))


def compare_drawings(actual, expected):
    def close(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a-b) < .001
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
        return a == b
    remaining = list(actual)
    for record in expected:
        match = next((i for i, r in enumerate(remaining) if close(r, record)), None)
        if match is None:
            raise ValueError("drawing_identity_changed")
        remaining.pop(match)
    if remaining:
        raise ValueError("unexpected_drawing_added")


def verify_pixels(before, after, rows, lines):
    if (before.width, before.height, before.n) != (after.width, after.height, after.n):
        raise ValueError("page_raster_geometry_changed")
    aa = np.frombuffer(before.samples, dtype=np.uint8).reshape(before.height, before.width, before.n)
    bb = np.frombuffer(after.samples, dtype=np.uint8).reshape(after.height, after.width, after.n)
    allowed = np.zeros(aa.shape[:2], dtype=bool)
    boxes = [shifted_box(c, delta) for r in rows for c in r["characters"] for delta in (0, r["delta_y"])]
    boxes += [fitz.Rect(x["drawing"]["rect"]) + (0, delta, 0, delta)
              for x in lines for delta in (0, x["delta_y"])]
    for box in boxes:
        # 144dpi，字形抗锯齿及线宽仅扩大1pt。
        b = fitz.IRect((box + (-1, -1, 1, 1)) * fitz.Matrix(2, 2)) & fitz.IRect(0, 0, before.width, before.height)
        allowed[b.y0:b.y1, b.x0:b.x1] = True
    outside = np.any(aa != bb, axis=2) & ~allowed
    if outside.any():
        raise ValueError(f"protected_pixels_changed:{int(outside.sum())}")
    return {"dpi": 144, "outside_target_changed_pixels": 0,
            "target_mask_pixels": int(allowed.sum()), "page_pixels": before.width * before.height}


def render_page(plan_path, page_number, output_dir):
    plan_path = Path(plan_path).resolve()
    if plan_path.stat().st_size > 16 * 1024**2:
        raise ValueError("plan_over_budget")
    plan_ref = reference(plan_path)
    plan = json.loads(plan_path.read_text())
    validate_plan(plan)
    source_path = checked_ref(plan["baseline"], 128 * 1024**2)
    evidence = plan.get("source_scope_evidence")
    if not evidence:
        raise ValueError("source_scope_evidence_required")
    checked_ref(evidence, 16 * 1024**2)
    font_paths = {name: checked_ref(record, 64 * 1024**2) for name, record in plan["fonts"].items()}
    if sum(p.stat().st_size for p in font_paths.values()) > 128 * 1024**2:
        raise ValueError("aggregate_font_budget")
    matches = [p for p in plan["pages"] if p["page"] == page_number]
    if len(matches) != 1:
        raise ValueError("page_not_in_frozen_plan")
    row = matches[0]
    output_dir = validate_output_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    candidate = output_dir / "unverified-page.pdf"
    try:
        with fitz.open(source_path) as source, fitz.open() as out:
            if page_number > len(source) or source[page_number-1].rotation != 0:
                raise ValueError("source_page_or_rotation")
            source_links = source[page_number-1].get_links()
            if any(l["kind"] != fitz.LINK_URI for l in source_links):
                raise ValueError("subset_non_uri_links_requires_document_mapping")
            raw_link_records = copy_page_with_raw_actions(out, source, page_number-1)
            page = out[0]
            if Counter(link_identity(l) for l in page.get_links()) != Counter(link_identity(l) for l in source_links):
                raise ValueError("source_links_changed_by_page_copy")
            if list(source[page_number-1].annots() or []):
                raise ValueError("non_link_annotations_unsupported")
            before = glyphs(page)
            targets = [c for r in row["rows"] for c in r["characters"]]
            counts = Counter(identity(c) for c in targets)
            actual = Counter(identity(c) for c in before)
            if any(actual[k] != n for k, n in counts.items()):
                raise ValueError("target_glyph_not_in_source")
            # 字符逻辑框也必须来自冻结源，不能扩大遮罩和像素许可范围。
            by_id = {identity(c): c for c in before}
            for c in targets:
                native = by_id[identity(c)]
                if max(abs(c["bbox"][i]-native["bbox"][i]) for i in range(4)) >= .001:
                    raise ValueError("target_bbox_changed")
                if native["direction"] != [1, 0] or native["opacity"] != 1 or native["type"] != 0:
                    raise ValueError("unsupported_source_render_mode")
            protected = [c for c in before if identity(c) not in counts]
            sizes = [Counter(round(c["size"], 3) for c in r["characters"]
                             if not chr(c["unicode"]).isspace()).most_common(1)[0][0] for r in row["rows"]]
            small_hosts = {}
            for c in before:
                if chr(c["unicode"]).isspace() or c["type"] != 0:
                    continue
                possible = [(abs(c["origin"][1]-r["old_baseline"]), i) for i, r in enumerate(row["rows"])
                            if c["size"] <= sizes[i]*.9 and abs(c["origin"][1]-r["old_baseline"]) <= sizes[i]
                            and r["bbox"][0]-sizes[i] <= c["origin"][0] <= r["bbox"][2]+sizes[i]]
                possible.sort()
                if possible:
                    if len(possible)>1 and possible[1][0]-possible[0][0] < .5:
                        raise ValueError("ambiguous_inline_script_host")
                    small_hosts[identity(c)] = possible[0][1]
            # 当前入口限已审单栏完整行。正文空格也按主基线/实际字号归属，
            # 不能移出目标行再借原位保护白名单绕过完整行检查。
            for row_index, r in enumerate(row["rows"]):
                members = Counter(identity(c) for c in r["characters"])
                native_line = Counter(identity(c) for c in before
                    if c["type"] == 0 and c["opacity"] == 1
                    and abs(c["origin"][1]-r["old_baseline"]) <= .002
                    and (not chr(c["unicode"]).isspace() or abs(c["size"]-sizes[row_index]) <= .002))
                if native_line - members:
                    raise ValueError("incomplete_source_printed_line")
                # 单栏的邻近小号字形不能静默留在原位；源语义是否为脚注仍由具名证据裁定。
                nearby = [c for c in before if small_hosts.get(identity(c)) == row_index]
                if any(identity(c) not in members for c in nearby):
                    raise ValueError("unassigned_inline_script_or_ambiguous_small_text")
                if any(identity(c) in small_hosts and small_hosts[identity(c)] != row_index for c in r["characters"]):
                    raise ValueError("script_host_binding_mismatch")
            restorable = row.get("restorable_protected_spaces", [])
            allowed_restore = Counter(identity(c) for c in restorable)
            protected_counts = Counter(identity(c) for c in protected)
            if (len(restorable) > 1000 or any(not chr(c["unicode"]).isspace() or c["type"] != 0
                                             or c["font"] not in font_paths for c in restorable)
                    or any(n > protected_counts[k] for k, n in allowed_restore.items())):
                raise ValueError("invalid_protected_space_declaration")
            for c in restorable:
                native = by_id[identity(c)]
                if c.get("protection_role") != "verified_residual_source_space" or not c.get("protection_reason"):
                    raise ValueError("protected_residual_space_evidence_required")
                checked_ref(c["source_evidence"], 16 * 1024**2)
                if (c.get("direction") != native["direction"] or c.get("opacity") != native["opacity"]
                        or max(abs(c["bbox"][i]-native["bbox"][i]) for i in range(4)) >= .001):
                    raise ValueError("protected_space_style_or_bbox_changed")
            geometry_guard(page, row["rows"], protected)
            lines, links = decorations(page, row)
            original_drawings = [drawing_record(d) for d in page.get_drawings()]
            expected_drawings = list(original_drawings)
            for item in lines:
                original = drawing_record(item["drawing"])
                moved = drawing_record(item["drawing"])
                delta = item["delta_y"]
                moved["rect"] = list(fitz.Rect(moved["rect"]) + (0, delta, 0, delta))
                moved["items"] = [[tag, [a[0], a[1]+delta], [b[0], b[1]+delta]] for tag, a, b in moved["items"]]
                expected_drawings.remove(original)
                expected_drawings.append(moved)
            original_links = page.get_links()
            original_pixels = stable_get_pixmap(source[page_number-1], matrix=fitz.Matrix(2, 2), alpha=False)
            for item in lines:
                page.add_redact_annot(fitz.Rect(item["drawing"]["rect"]) + (-.6, -.6, .6, .6), fill=False)
            if lines:
                page.apply_redactions(images=0, graphics=1, text=1)
                page = out.reload_page(page)
            for c in targets:
                b = fitz.Rect(c["bbox"]); x, y = (b.x0+b.x1)/2, (b.y0+b.y1)/2
                page.add_redact_annot(fitz.Rect(x-.012, y-.012, x+.012, y+.012), fill=False)
            page.apply_redactions(images=0, graphics=0, text=0)
            page = out.reload_page(page)
            remaining = glyphs(page)
            missing = protected_counts - Counter(identity(c) for c in remaining)
            if any(n > allowed_restore[k] for k, n in missing.items()):
                compare_glyphs(remaining, protected)
            restore = []
            retained = []
            for c in protected:
                k = identity(c)
                if missing[k]:
                    restore.append(c); missing[k] -= 1
                else:
                    retained.append(c)
            compare_glyphs(remaining, retained)
            moved_links = []
            for item in links:
                link, delta = item["link"], item["delta_y"]
                for existing in page.get_links():
                    if existing["xref"] == link["xref"]:
                        page.delete_link(existing)
                box = fitz.Rect(link["from"]) + (0, delta, 0, delta)
                page.insert_link({"kind": fitz.LINK_URI, "from": box, "uri": link["uri"]})
                moved_links.append({"uri": link["uri"], "before": list(link["from"]), "after": list(box), "delta_y": delta})
            needed_fonts = {c["font"] for c in [*targets, *restore]}
            fonts = {name: fitz.Font(fontfile=str(path)) for name, path in font_paths.items() if name in needed_fonts}
            source_xrefs = {f[0] for f in source[page_number-1].get_fonts(full=True)}
            for name in needed_fonts:
                record = plan["fonts"][name]
                declared_xrefs = record.get("source_font_xrefs", [])
                if not declared_xrefs or not set(declared_xrefs) & source_xrefs:
                    raise ValueError("source_font_xref_evidence_required")
                if any(hashlib.sha256(source.extract_font(xref)[3]).hexdigest() != record["sha256"]
                       for xref in declared_xrefs):
                    raise ValueError("source_font_asset_bytes_changed")
                with TTFont(font_paths[name], lazy=True) as font:
                    ps_names = {n.toUnicode() for n in font['name'].names if n.nameID == 6}
                if name not in ps_names:
                    raise ValueError("source_font_postscript_identity_changed")
            resources = {}
            previous_fonts = {f[0] for f in page.get_fonts(full=True)}
            expected, used = list(protected), defaultdict(dict)
            for i, (name, path) in enumerate(font_paths.items()):
                if name not in needed_fonts:
                    continue
                resources[name] = f"NativeSpacing{i}"
                if any(f[4] == resources[name] for f in page.get_fonts(full=True)):
                    raise ValueError("font_resource_name_already_owned_by_source")
                page.insert_font(fontname=resources[name], fontfile=str(path))
            for r in row["rows"]:
                for c in sorted(r["characters"], key=lambda c: c["origin"][0]):
                    name, code, gid = c["font"], c["unicode"], c["gid"]
                    if fonts[name].has_glyph(code) != gid or gid == 0:
                        raise ValueError("font_glyph_identity_changed")
                    if gid in used[name] and used[name][gid] != chr(code):
                        raise ValueError("ambiguous_unicode_for_gid")
                    used[name][gid] = chr(code)
                    position = [c["origin"][0], c["origin"][1]+r["delta_y"]]
                    expected.append({**c, "origin": position})
                    page.insert_text(position, chr(code), fontname=resources[name], fontsize=c["size"], color=c["color"])
            for c in restore:
                name, code, gid = c["font"], c["unicode"], c["gid"]
                if fonts[name].has_glyph(code) != gid or gid == 0 or (gid in used[name] and used[name][gid] != chr(code)):
                    raise ValueError("protected_space_font_or_unicode_changed")
                used[name][gid] = chr(code)
                page.insert_text(c["origin"], chr(code), fontname=resources[name], fontsize=c["size"], color=c["color"])
            owned = {f[0] for f in page.get_fonts(full=True)} - previous_fonts
            cmaps = []
            for xref in sorted(owned):
                sha = hashlib.sha256(out.extract_font(xref)[3]).hexdigest()
                names = [name for name, record in plan["fonts"].items() if record["sha256"] == sha and name in used]
                if len(names) != 1:
                    raise ValueError("new_embedded_font_bytes_or_identity_changed")
                cmaps.append(bind_owned_font_unicode(out, xref, used[names[0]], owned_font_xrefs=owned))
            for item in lines:
                drawing, delta = item["drawing"], item["delta_y"]
                shape = page.new_shape()
                for _, a, b in drawing["items"]:
                    shape.draw_line(a+(0, delta), b+(0, delta))
                shape.finish(color=drawing["color"], width=drawing["width"], lineCap=drawing["lineCap"][0],
                             lineJoin=drawing["lineJoin"], dashes=drawing["dashes"], stroke_opacity=drawing["stroke_opacity"],
                             closePath=drawing["closePath"])
                shape.commit()
            # 去字可能删除注释，URI重建也可能改变顺序；按冻结动作和唯一预期矩形重绑。
            expected_raw_links = []
            for record in raw_link_records:
                expected_link = dict(record["fields"])
                for item in links:
                    if record["candidate_xref"] == item["link"]["xref"]:
                        expected_link["from"] = fitz.Rect(expected_link["from"]) + (0, item["delta_y"], 0, item["delta_y"])
                expected_raw_links.append(expected_link)
            page = out.reload_page(page)
            raw_link_records = rebind_expected_link_actions(out, 0, raw_link_records, expected_raw_links)
            out.save(candidate, garbage=4, deflate=True)
        with fitz.open(candidate) as final:
            final_glyphs = glyphs(final[0])
            final_drawings = [drawing_record(d) for d in final[0].get_drawings()]
            error = compare_glyphs(final_glyphs, expected)
            compare_drawings(final_drawings, expected_drawings)
            expected_links = [dict(link) for link in original_links]
            for link in expected_links:
                for item in links:
                    if link["xref"] == item["link"]["xref"]:
                        link["from"] = fitz.Rect(link["from"]) + (0, item["delta_y"], 0, item["delta_y"])
            raw_link_verification = verify_saved_link_actions(final, 0, raw_link_records)
            final_links = final[0].get_links()
            if Counter(link_identity(l) for l in final_links) != Counter(link_identity(l) for l in expected_links):
                raise ValueError("link_geometry_or_target_changed")
            pixels = verify_pixels(original_pixels, stable_get_pixmap(final[0], matrix=fitz.Matrix(2, 2), alpha=False), row["rows"], lines)
        checked_ref(plan["baseline"], 128 * 1024**2)
        checked_ref(evidence, 16 * 1024**2)
        for record in plan["fonts"].values():
            checked_ref(record, 64 * 1024**2)
        for item in [*lines, *links]:
            checked_ref(item["declaration"]["source_evidence"], 16 * 1024**2)
        for r in row["rows"]:
            for spec in r.get("verified_scripts", []):
                checked_ref(spec["source_evidence"], 16 * 1024**2)
        if reference(plan_path) != plan_ref:
            raise ValueError("plan_changed_during_execution")
        final_path = output_dir / "candidate-page.pdf"
        candidate.rename(final_path)
        elements_path = output_dir / "elements.json"
        elements_path.write_text(json.dumps({"before_glyphs": before, "expected_glyphs": expected,
            "after_glyphs": final_glyphs, "before_drawings": original_drawings,
            "expected_drawings": expected_drawings, "after_drawings": final_drawings,
            "before_links": plain(original_links), "expected_links": plain(expected_links),
            "after_links": plain(final_links)},
            ensure_ascii=False, indent=2)+"\n")
        receipt = {"schema_version": SCHEMA, "status": "mechanical_candidate_verified", "plan": plan_ref,
                   "baseline": plan["baseline"], "source_scope_evidence": evidence, "pdf": reference(final_path),
                   "source_page": page_number, "output_page": 1, "same_page_mapping": True,
                   "ratio": plan["ratio"], "paragraph_fragments": row["paragraph_fragments"],
                   "target_glyphs": len(targets), "protected_glyphs": len(protected), "all_glyphs": len(expected),
                   "maximum_coordinate_error_pt": error, "outside_target_pixels": pixels,
                   "owned_font_mappings": cmaps, "moved_links": moved_links, "moved_underlines": len(lines),
                   "restored_protected_spaces": restore,
                   "raw_link_actions": raw_link_verification,
                   "elements": reference(elements_path),
                   "quality_pass": False, "strict_delivery": False, "model_calls": 0}
        (output_dir / "verification.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n")
        return receipt
    except Exception as exc:
        (output_dir / "failure.json").write_text(json.dumps({"status": "failed", "error": str(exc),
            "plan": plan_ref, "quality_pass": False, "strict_delivery": False}, ensure_ascii=False, indent=2)+"\n")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = render_page(args.plan, args.page, args.output_dir)
    print(json.dumps({k: receipt[k] for k in ("status", "source_page", "target_glyphs", "protected_glyphs", "pdf")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
