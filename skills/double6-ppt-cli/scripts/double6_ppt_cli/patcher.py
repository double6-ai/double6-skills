from __future__ import annotations

import hashlib
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from .common import (
    D6PPTError, SCHEMA_VERSION, ensure_owner_writable, load_run, read_json, resolve_run_path, set_status,
    sha256_file, utc_now, write_json,
)
from .officecli import OfficeCLI
from .package_diff import compare_parts
from .schemas import validate_object_map, validate_patch_spec


PROPERTY_MAP = {"color": "color", "fill": "fill", "font": "font", "size": "size"}

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _logical_slide_parts(archive: zipfile.ZipFile) -> list[str]:
    presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
    relationships = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    rel_targets = {
        rel.get("Id"): posixpath.normpath(posixpath.join("ppt", rel.get("Target", "")))
        for rel in relationships
        if rel.get("Id") and rel.get("Target")
    }
    parts: list[str] = []
    for slide_id in presentation.xpath(
        "//p:sldIdLst/p:sldId",
        namespaces={"p": P_NS, "r": R_NS},
    ):
        rel_id = slide_id.get(f"{{{R_NS}}}id")
        target = rel_targets.get(rel_id)
        if target and target.startswith("ppt/slides/"):
            parts.append(target)
    if not parts:
        raise D6PPTError("PPTX has no logical slide order", "invalid_pptx")
    return parts


def _rewrite_xml_part(pptx: Path, part_name: str, payload: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{pptx.name}.", suffix=".pptx", dir=pptx.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with zipfile.ZipFile(pptx, "r") as source, zipfile.ZipFile(tmp, "w") as target:
            for info in source.infolist():
                target.writestr(info, payload if info.filename == part_name else source.read(info.filename))
        os.replace(tmp, pptx)
    finally:
        tmp.unlink(missing_ok=True)


def _shape_for_path(pptx: Path, officecli_path: str) -> tuple[str, etree._ElementTree, etree._Element]:
    match = re.fullmatch(
        r"/slide\[(\d+)\](?:/group\[@id=\d+\])*/(shape|textbox|equation)\[@id=(\d+)\]",
        officecli_path,
    )
    if not match:
        raise D6PPTError("Rich-text-safe patch requires a stable text leaf path", "unsafe_patch_target")
    logical_slide, drawingml_id = int(match.group(1)), match.group(3)
    with zipfile.ZipFile(pptx, "r") as archive:
        parts = _logical_slide_parts(archive)
        if logical_slide < 1 or logical_slide > len(parts):
            raise D6PPTError("Patch logical slide is out of range", "unsafe_patch_target")
        part_name = parts[logical_slide - 1]
        root = etree.fromstring(archive.read(part_name))
    identities = root.xpath(f".//p:cNvPr[@id='{drawingml_id}']", namespaces={"p": P_NS})
    if len(identities) != 1:
        raise D6PPTError("Patch DrawingML identity is missing or ambiguous", "ambiguous_patch_target")
    element = identities[0].getparent()
    while element is not None and etree.QName(element).localname not in {"sp", "cxnSp"}:
        element = element.getparent()
    if element is None or etree.QName(element).namespace != P_NS:
        raise D6PPTError("Patch target is not a text leaf shape", "unsafe_patch_target")
    return part_name, root.getroottree(), element


def _set_text_preserving_runs(
    pptx: Path,
    officecli_path: str,
    expected_text: str,
    value: str,
) -> dict[str, Any]:
    part_name, tree, shape = _shape_for_path(pptx, officecli_path)
    paragraphs = shape.xpath("./p:txBody/a:p", namespaces={"p": P_NS, "a": A_NS})
    observed_lines = ["".join(p.xpath(".//a:t/text()", namespaces={"a": A_NS})) for p in paragraphs]
    expected_lines = str(expected_text).split("\n")
    replacement_lines = str(value).split("\n")
    if observed_lines != expected_lines or len(replacement_lines) != len(paragraphs):
        raise D6PPTError(
            "Text replacement does not preserve the existing paragraph contract",
            "unsafe_rich_text_patch",
        )
    for paragraph, replacement in zip(paragraphs, replacement_lines):
        text_nodes = paragraph.xpath(".//a:t", namespaces={"a": A_NS})
        if len(text_nodes) != 1:
            raise D6PPTError(
                "Text paragraph has multiple runs; automatic replacement is ambiguous",
                "unsafe_rich_text_patch",
            )
        text_nodes[0].text = replacement
    _rewrite_xml_part(pptx, part_name, etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True))
    return {"status": "pass", "engine": "ooxml_preserve_runs", "updated": officecli_path, "property": "text"}


def _set_numeric_headline_size(
    pptx: Path,
    officecli_path: str,
    value: str,
    finding_id: str,
) -> dict[str, Any]:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)pt\s*", str(value))
    if not match or not str(finding_id).startswith("d6-numeric-display-capacity-"):
        raise D6PPTError("Mixed rich-text size patch is not a numeric capacity repair", "unsafe_rich_text_patch")
    part_name, tree, shape = _shape_for_path(pptx, officecli_path)
    paragraphs = [
        p for p in shape.xpath("./p:txBody/a:p", namespaces={"p": P_NS, "a": A_NS})
        if "".join(p.xpath(".//a:t/text()", namespaces={"a": A_NS})).strip()
    ]
    if not paragraphs:
        raise D6PPTError("Numeric size target has no text paragraph", "unsafe_rich_text_patch")
    target_paragraphs = paragraphs[:1] if len(paragraphs) > 1 else paragraphs
    run_properties = []
    for paragraph in target_paragraphs:
        run_properties.extend(paragraph.xpath(".//a:rPr", namespaces={"a": A_NS}))
    if not run_properties:
        raise D6PPTError("Numeric headline has no explicit run size", "unsafe_rich_text_patch")
    size = str(round(float(match.group(1)) * 100))
    for properties in run_properties:
        properties.set("sz", size)
    _rewrite_xml_part(pptx, part_name, etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True))
    return {
        "status": "pass",
        "engine": "ooxml_numeric_headline_only",
        "updated": officecli_path,
        "property": "size",
        "paragraphs_changed": len(target_paragraphs),
    }


def _package_invariants(path: Path) -> dict[str, Any]:
    def semantic_xml_sha(payload: bytes) -> str:
        root = etree.fromstring(payload)
        parts: list[str] = []
        for element in root.iter():
            parts.append(etree.QName(element).localname)
            for key, value in sorted(
                ((etree.QName(key).localname, value) for key, value in element.attrib.items()),
                key=lambda item: item[0],
            ):
                parts.extend((key, value))
            if element.text and element.text.strip():
                parts.append(element.text.strip())
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    slides: dict[int, str] = {}
    protected: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        slide_parts = _logical_slide_parts(archive)
        for logical_index, name in enumerate(slide_parts, start=1):
            payload = archive.read(name)
            texts = re.findall(rb"<a:t(?:\s[^>]*)?>(.*?)</a:t>", payload, flags=re.S)
            normalized = b"\n".join(texts)
            slides[logical_index] = hashlib.sha256(normalized).hexdigest()
        for name in archive.namelist():
            payload = archive.read(name)
            if name.startswith(("ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/", "ppt/notesSlides/")):
                protected[name] = semantic_xml_sha(payload) if name.endswith(".xml") else hashlib.sha256(payload).hexdigest()
    return {"slide_text_sha256": slides, "protected_part_sha256": protected}


def _single_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    if isinstance(data, dict) and isinstance(data.get("results"), list) and len(data["results"]) == 1:
        data = data["results"][0]
    return data if isinstance(data, dict) else {}


def _verify_fingerprint(path: str, before: dict[str, Any], fingerprint: dict[str, Any]) -> None:
    match = re.fullmatch(r"/slide\[\d+\](?:/group\[@id=\d+\])*/(shape|textbox|equation|connector|picture)\[@id=(\d+)\]", path)
    if not match:
        raise D6PPTError("Patch target is not a stable leaf path", "unsafe_patch_target")
    expected_type = fingerprint.get("object_type")
    aliases = {"shape": {"shape", "textbox", "equation"}, "textbox": {"shape", "textbox"}, "equation": {"shape", "equation"}}
    actual_type = match.group(1)
    if expected_type not in aliases.get(actual_type, {actual_type}) and actual_type not in aliases.get(str(expected_type), {str(expected_type)}):
        raise D6PPTError("Patch object type fingerprint does not match target", "stale_patch_fingerprint")
    if int(match.group(2)) != int(fingerprint.get("drawingml_id")):
        raise D6PPTError("Patch DrawingML id fingerprint does not match target", "stale_patch_fingerprint")
    data = _single_data(before)
    observed_text = str(data.get("text") or "")
    if fingerprint.get("text") is not None and observed_text.strip() != str(fingerprint["text"]).strip():
        raise D6PPTError("Patch text fingerprint is stale", "stale_patch_fingerprint")
    if fingerprint.get("text_sha256") is not None:
        observed_sha = hashlib.sha256(observed_text.strip().encode("utf-8")).hexdigest()
        if observed_sha != fingerprint["text_sha256"]:
            raise D6PPTError("Patch text hash fingerprint is stale", "stale_patch_fingerprint")


def apply_patch(run: Path, spec_path: Path, runtime_dir: Path | None = None) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    spec = read_json(spec_path.resolve())
    validate_patch_spec(spec)
    current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    current_sha = sha256_file(current)
    if spec.get("pptx_sha256") != current_sha:
        raise D6PPTError("Patch PPTX precondition is stale", "stale_patch_precondition")
    if current.resolve() == Path(manifest["input"]["original_path"]).resolve():
        raise D6PPTError("Refusing to patch original source", "source_overwrite_forbidden")
    map_rel = manifest["artifacts"].get("object_path_map")
    object_map = None
    if map_rel:
        map_path = resolve_run_path(run, map_rel)
        object_map = read_json(map_path)
        semantic_rel = manifest["artifacts"].get("semantic_manifest")
        semantic_path = resolve_run_path(run, semantic_rel) if semantic_rel else None
        validate_object_map(object_map, current, semantic_path)
        if spec.get("object_map_sha256") != sha256_file(map_path):
            raise D6PPTError("Patch object-map precondition is stale", "stale_patch_precondition")
    schema_v2 = spec.get("schema_version") == SCHEMA_VERSION
    findings_by_id: dict[str, dict[str, Any]] = {}
    if schema_v2:
        findings_path = run / "evidence" / "findings.json"
        if not findings_path.is_file():
            raise D6PPTError("Schema 2.0 patches require current findings", "inspection_stale")
        findings_payload = read_json(findings_path)
        if findings_payload.get("pptx_sha256") != current_sha:
            raise D6PPTError("Schema 2.0 patch findings are stale", "inspection_stale")
        findings_by_id = {str(item.get("finding_id")): item for item in findings_payload.get("findings", [])}
    elif manifest["mode"] == "postflight" and spec.get("user_confirmed") is not True:
        raise D6PPTError("Legacy postflight patch without source map requires user_confirmed=true", "patch_confirmation_required")

    patch_root = run / "patches"
    index = len(list(patch_root.glob("patch-*.pptx"))) + 1
    patch_id = f"patch-{index:03d}"
    output = patch_root / f"{patch_id}.pptx"
    shutil.copy2(current, output)
    ensure_owner_writable(output)
    invariants_before = _package_invariants(current)
    client = OfficeCLI(runtime_dir, run / "logs")
    entries = []
    map_objects = {item["source_id"]: item for item in (object_map or {}).get("objects", [])}
    for patch in spec["patches"]:
        mapped = map_objects.get(patch.get("source_id")) if patch.get("source_id") else None
        path = patch.get("officecli_path") or (mapped or {}).get("officecli_path")
        if not path:
            output.unlink(missing_ok=True)
            raise D6PPTError("Patch target did not resolve uniquely", "ambiguous_patch_target")
        if mapped and patch.get("officecli_path") and patch["officecli_path"] != mapped["officecli_path"]:
            raise D6PPTError("source_id and officecli_path disagree", "patch_target_mismatch")
        if schema_v2:
            finding = findings_by_id.get(str(patch.get("finding_id")))
            if finding is None:
                raise D6PPTError("Patch finding is not present in the current inspection", "patch_finding_missing")
            finding_path = (finding.get("object") or {}).get("officecli_path")
            if finding_path != path:
                raise D6PPTError("Patch target does not match its finding", "patch_target_mismatch")
        before = client.run(["get", str(output), path])
        if schema_v2:
            _verify_fingerprint(path, before, patch["expected_fingerprint"])
        operation = patch.get("operation", "set_property")
        if operation == "remove_leaf":
            result = client.remove(output, path)
            prop = None
            new_value = None
        else:
            prop = PROPERTY_MAP.get(patch["property"], patch["property"])
            if prop == "text":
                client.close(output)
                result = _set_text_preserving_runs(
                    output,
                    path,
                    str(patch["expected_fingerprint"].get("text", "")),
                    str(patch["value"]),
                )
            elif prop == "size":
                client.close(output)
                result = _set_numeric_headline_size(
                    output,
                    path,
                    str(patch["value"]),
                    str(patch.get("finding_id", "")),
                )
            else:
                result = client.set_property(output, path, prop, patch["value"])
            new_value = patch["value"]
        entries.append({
            "target": {"source_id": patch.get("source_id"), "officecli_path": path},
            "finding_id": patch.get("finding_id"), "operation": operation,
            "source_template_object_id": patch.get("source_template_object_id"),
            "reason": patch.get("reason"),
            "expected_fingerprint": patch.get("expected_fingerprint"),
            "property": patch.get("property"), "old_value": before.get("data"),
            "new_value": new_value, "officecli_result": result.get("data"),
        })
    client.save(output)
    client.close(output)
    validation = client.validate(output)
    diff = compare_parts(current, output)
    invariants_after = _package_invariants(output)
    target_slide_parts = {
        int(match.group(1)) for entry in entries
        if (match := re.match(r"/slide\[(\d+)\]", entry["target"]["officecli_path"]))
    }
    all_slide_parts = set(invariants_before["slide_text_sha256"]) | set(invariants_after["slide_text_sha256"])
    untouched = sorted(all_slide_parts - target_slide_parts)
    unchanged_untargeted = all(
        invariants_before["slide_text_sha256"].get(slide) == invariants_after["slide_text_sha256"].get(slide)
        for slide in untouched
    )
    protected_parts_unchanged = invariants_before["protected_part_sha256"] == invariants_after["protected_part_sha256"]
    if not unchanged_untargeted or not protected_parts_unchanged:
        raise D6PPTError(
            "Bounded patch changed untargeted slide text or protected master/layout/theme/notes parts",
            "patch_scope_violation",
            {"untargeted_slides_unchanged": unchanged_untargeted, "protected_parts_unchanged": protected_parts_unchanged},
        )
    after_sha = sha256_file(output)
    ledger_path = run / "evidence" / "patch_ledger.json"
    ledger = read_json(ledger_path) if ledger_path.is_file() else {"schema_version": SCHEMA_VERSION, "entries": []}
    record = {
        "patch_id": patch_id, "created_at": utc_now(), "before_pptx": str(current.relative_to(run)),
        "before_sha256": current_sha, "after_pptx": str(output.relative_to(run)), "after_sha256": after_sha,
        "spec_sha256": sha256_file(spec_path), "operations": entries, "affected_package_parts": diff,
        "validate": {k: v for k, v in validation.items() if k != "_receipt"},
        "scope_invariants": {
            "target_slide_parts": sorted(target_slide_parts),
            "untargeted_slide_parts": untouched,
            "untargeted_slides_unchanged": unchanged_untargeted,
            "master_layout_theme_notes_unchanged": protected_parts_unchanged,
            "before": invariants_before,
            "after": invariants_after,
        },
        "warning": "OfficeCLI may rewrite unrelated package parts; inspect affected_package_parts.",
    }
    ledger["entries"].append(record)
    write_json(ledger_path, ledger)
    if object_map:
        next_map = dict(object_map)
        removed_source_ids = {
            operation["target"].get("source_id") for operation in entries
            if operation.get("operation") == "remove_leaf" and operation["target"].get("source_id")
        }
        removed_paths = {
            operation["target"]["officecli_path"] for operation in entries
            if operation.get("operation") == "remove_leaf"
        }
        next_map["objects"] = [
            item for item in object_map.get("objects", [])
            if item.get("source_id") not in removed_source_ids and item.get("officecli_path") not in removed_paths
        ]
        next_map["pptx_sha256"] = after_sha
        next_map["derived_from_object_map_sha256"] = spec["object_map_sha256"]
        next_map_path = run / "artifacts" / f"object_path_map_{patch_id}.json"
        write_json(next_map_path, next_map)
        manifest["artifacts"]["object_path_map"] = str(next_map_path.relative_to(run))
    manifest["artifacts"].update({
        "current_pptx": str(output.relative_to(run)), "pptx_sha256": after_sha,
        "patch_ledger": "evidence/patch_ledger.json",
    })
    manifest["unreplayed_patches"] = []
    set_status(run, manifest, "repair_needed", "bounded_patch", {"patch_id": patch_id, "requires_reinspection": True})
    return record
