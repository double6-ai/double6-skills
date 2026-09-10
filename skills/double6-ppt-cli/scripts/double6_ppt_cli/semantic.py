from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from .common import D6PPTError, SCHEMA_VERSION, sha256_file, sha256_tree, utc_now, write_json
from .schemas import validate_semantic_manifest


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
EMU_PER_PT = 12700


def _norm(value: str) -> str:
    return "".join(value.split())


def _text(element: etree._Element) -> str:
    return _norm("".join(element.xpath(".//a:t/text()", namespaces=NS)))


def _cnvpr(element: etree._Element) -> etree._Element:
    nodes = element.xpath(
        "./p:nvSpPr/p:cNvPr | ./p:nvGrpSpPr/p:cNvPr | ./p:nvCxnSpPr/p:cNvPr | ./p:nvGraphicFramePr/p:cNvPr",
        namespaces=NS,
    )
    if not nodes:
        raise D6PPTError("DrawingML object lacks cNvPr", "invalid_pptx_structure")
    return nodes[0]


def _kind(element: etree._Element) -> str:
    local = etree.QName(element).localname
    if local == "sp":
        return "shape"
    if local == "grpSp":
        return "group"
    if local == "cxnSp":
        return "connector"
    if local == "graphicFrame":
        if element.xpath(".//a:tbl", namespaces=NS):
            return "table"
        if element.xpath(".//c:chart", namespaces=NS):
            return "chart"
        return "graphicFrame"
    return local


def _path(element: etree._Element, slide: int) -> tuple[str, int, str]:
    object_id = int(_cnvpr(element).get("id"))
    kind = _kind(element)
    parent = element.getparent()
    if parent is not None and etree.QName(parent).localname == "grpSp":
        parent_id = int(_cnvpr(parent).get("id"))
        return f"/slide[{slide}]/group[@id={parent_id}]/{kind}[@id={object_id}]", object_id, kind
    return f"/slide[{slide}]/{kind}[@id={object_id}]", object_id, kind


def _candidates(root: etree._Element) -> list[etree._Element]:
    return root.xpath(".//p:sp | .//p:grpSp | .//p:cxnSp | .//p:graphicFrame", namespaces=NS)


def _find(root: etree._Element, obj: dict[str, Any]) -> etree._Element:
    items = _candidates(root)
    match = obj["match"]
    if match.get("drawingml_id") is not None:
        wanted_id = int(match["drawingml_id"])
        matches = [item for item in items if int(_cnvpr(item).get("id") or 0) == wanted_id]
        # Native chart/table markers often keep the SVG id as cNvPr name and
        # assign a new drawingml id; fall back to source_selector.id as name.
        if not matches and obj.get("preferred_structure") in {"native_chart", "native_table"}:
            selector_id = str((obj.get("source_selector") or {}).get("id") or "")
            if selector_id:
                matches = [
                    item for item in items
                    if _cnvpr(item).get("name") == selector_id
                    or (_cnvpr(item).get("name") or "").endswith(selector_id)
                ]
    elif match.get("drawingml_name") is not None:
        wanted = str(match["drawingml_name"])
        matches = [item for item in items if _cnvpr(item).get("name") == wanted]
    elif match.get("connector_ordinal") is not None:
        connectors = [item for item in items if _kind(item) == "connector"]
        if not connectors:
            connectors = [
                item for item in items
                if _kind(item) == "shape" and (
                    bool(item.xpath("./p:spPr/a:prstGeom[@prst='line']", namespaces=NS))
                    or "line" in (_cnvpr(item).get("name") or "").lower()
                    or "connector" in (_cnvpr(item).get("name") or "").lower()
                )
            ]
        ordinal = int(match["connector_ordinal"])
        matches = connectors[ordinal - 1:ordinal]
    elif match.get("group_contains") is not None:
        wanted = _norm(str(match["group_contains"]))
        matches = [item for item in items if _kind(item) == "group" and wanted in _text(item)]
    else:
        wanted = _norm(str(match["text"]))
        matches = [item for item in items if _text(item) == wanted]
        if match.get("kind"):
            matches = [item for item in matches if _kind(item) == match["kind"]]
        ordinal = match.get("ordinal")
        if ordinal is not None:
            ordinal = int(ordinal)
            matches = matches[ordinal - 1:ordinal]
    if len(matches) != 1:
        source_selector = obj.get("source_selector") or {}
        candidates = [
            {
                "drawingml_id": int(_cnvpr(item).get("id") or 0),
                "drawingml_name": _cnvpr(item).get("name"),
                "kind": _kind(item),
                "text": "".join(item.xpath(".//a:t/text()", namespaces=NS)).strip()[:160],
            }
            for item in items[:12]
        ]
        preferred = obj.get("preferred_structure")
        hint = ""
        if preferred in {"native_chart", "native_table"}:
            hint = (
                " Hint: native chart/table objects must be produced by a root-level "
                f"<g data-pptx-replace-with=\"{preferred.replace('native_', '')}\"> marker "
                "with data-pptx-shape-id and JSON metadata; a plain SVG diagram group is not a native object."
            )
        raise D6PPTError(
            (
                f"Semantic object must resolve uniquely: {obj['source_id']} candidates={len(matches)}; "
                f"source={source_selector.get('file') or '<unknown>'}{hint}"
            ),
            "ambiguous_object_mapping",
            {"source_selector": source_selector, "match": match, "slide_candidates": candidates},
        )
    target = matches[0]
    preferred = obj.get("preferred_structure")
    is_nested = target.getparent() is not None and etree.QName(target.getparent()).localname == "grpSp"
    if preferred in {"top_level", "placeholder", "native_chart", "native_table", "connector"} and is_nested:
        raise D6PPTError(f"{obj['source_id']} violates top-level authoring contract", "structure_contract_violation")
    if preferred == "group" and _kind(target) != "group":
        raise D6PPTError(f"{obj['source_id']} must remain a group", "structure_contract_violation")
    return target


def _add_placeholder(element: etree._Element, placeholder: str) -> None:
    if _kind(element) != "shape":
        raise D6PPTError("Placeholder target must be a shape", "placeholder_contract_violation")
    nv_pr = element.find(f"{{{NS['p']}}}nvSpPr/{{{NS['p']}}}nvPr")
    if nv_pr is None:
        raise D6PPTError("Placeholder target lacks nvPr", "placeholder_contract_violation")
    for old in nv_pr.findall(f"{{{NS['p']}}}ph"):
        nv_pr.remove(old)
    ph = etree.Element(f"{{{NS['p']}}}ph")
    ph.set("type", placeholder)
    nv_pr.insert(0, ph)


def _set_height(element: etree._Element, height_pt: float) -> None:
    if _kind(element) != "shape":
        raise D6PPTError("height_pt override requires a shape", "compiler_override_violation")
    xfrm = element.find(f"{{{NS['p']}}}spPr/{{{NS['a']}}}xfrm")
    ext = xfrm.find(f"{{{NS['a']}}}ext") if xfrm is not None else None
    if ext is None:
        raise D6PPTError("height_pt override target lacks geometry", "compiler_override_violation")
    ext.set("cy", str(round(height_pt * EMU_PER_PT)))
    body_pr = element.find(f"{{{NS['p']}}}txBody/{{{NS['a']}}}bodyPr")
    if body_pr is not None:
        for child in list(body_pr):
            if etree.QName(child).localname in {"spAutoFit", "normAutofit", "noAutofit"}:
                body_pr.remove(child)
        body_pr.append(etree.Element(f"{{{NS['a']}}}noAutofit"))


def _set_font_family(element: etree._Element, font_family: str) -> None:
    if _kind(element) != "shape":
        raise D6PPTError("font_family override requires a shape", "compiler_override_violation")
    runs = element.xpath(".//a:rPr | .//a:defRPr | .//a:endParaRPr", namespaces=NS)
    if not runs:
        raise D6PPTError("font_family override target lacks text runs", "compiler_override_violation")
    for run in runs:
        for tag in ("latin", "ea", "cs"):
            child = run.find(f"{{{NS['a']}}}{tag}")
            if child is None:
                child = etree.SubElement(run, f"{{{NS['a']}}}{tag}")
            child.set("typeface", font_family)


def apply_semantic_contract(
    input_pptx: Path,
    semantic_manifest_path: Path,
    output_pptx: Path,
    object_map_path: Path,
    source_root: Path,
) -> dict[str, Any]:
    from .common import read_json

    semantic = read_json(semantic_manifest_path)
    validate_semantic_manifest(semantic, source_root)
    by_slide: dict[int, list[dict[str, Any]]] = {}
    for obj in semantic["objects"]:
        by_slide.setdefault(int(obj["slide"]), []).append(obj)
    roundtrip_font = (semantic.get("defaults") or {}).get("roundtrip_font_family")
    resolved: list[dict[str, Any]] = []
    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_pptx, "r") as source, zipfile.ZipFile(output_pptx, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith("ppt/slides/slide") and info.filename.endswith(".xml"):
                slide_number = int(posixpath.basename(info.filename)[5:-4])
                if slide_number in by_slide or roundtrip_font:
                    root = etree.fromstring(data)
                    if roundtrip_font:
                        for text_shape in root.xpath(".//p:sp[.//a:t]", namespaces=NS):
                            _set_font_family(text_shape, str(roundtrip_font))
                    for obj in by_slide.get(slide_number, []):
                        shape = _find(root, obj)
                        c_nv_pr = _cnvpr(shape)
                        c_nv_pr.set("name", f"d6:{obj['source_id']}")
                        c_nv_pr.set("descr", f"source_id={obj['source_id']};role={obj['role']}")
                        if obj.get("placeholder"):
                            _add_placeholder(shape, obj["placeholder"])
                        height_pt = (obj.get("compiler_overrides") or {}).get("height_pt")
                        if height_pt is not None:
                            _set_height(shape, float(height_pt))
                        font_family = (obj.get("compiler_overrides") or {}).get("font_family")
                        if font_family is None and obj.get("placeholder"):
                            font_family = (semantic.get("defaults") or {}).get("placeholder_font_family")
                        if font_family:
                            _set_font_family(shape, str(font_family))
                        office_path, drawingml_id, drawingml_type = _path(shape, slide_number)
                        resolved.append({
                            "source_id": obj["source_id"],
                            "slide": slide_number,
                            "role": obj["role"],
                            "editable": obj["editable"],
                            "postflight_sensitive": obj["postflight_sensitive"],
                            "drawingml_id": drawingml_id,
                            "drawingml_type": drawingml_type,
                            "drawingml_part": info.filename,
                            "drawingml_name": f"d6:{obj['source_id']}",
                            "officecli_path": office_path,
                            "source_selector": obj["source_selector"],
                            "placeholder": obj.get("placeholder"),
                            "compiler_overrides": obj.get("compiler_overrides") or {},
                            "identity_strategy": (
                                {"type": "slide_placeholder", "slide": slide_number, "placeholder": obj["placeholder"]}
                                if obj.get("placeholder") else
                                {"type": "drawingml_name", "value": f"d6:{obj['source_id']}"}
                            ),
                        })
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            target.writestr(info, data)
    if len(resolved) != len(semantic["objects"]):
        output_pptx.unlink(missing_ok=True)
        raise D6PPTError("Not all semantic objects were mapped", "incomplete_object_mapping")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "created_at": utc_now(),
        "source_root_sha256": sha256_tree(source_root),
        "semantic_manifest_sha256": sha256_file(semantic_manifest_path),
        "compiler_output_sha256": sha256_file(input_pptx),
        "pptx_sha256": sha256_file(output_pptx),
        "resolved_count": len(resolved),
        "expected_count": len(semantic["objects"]),
        "objects": sorted(resolved, key=lambda item: (item["slide"], item["source_id"])),
    }
    write_json(object_map_path, payload)
    return payload
