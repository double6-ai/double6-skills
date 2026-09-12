from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from .common import (
    D6PPTError,
    SCHEMA_VERSION,
    invalidate_pptx_derived_artifacts,
    load_run,
    resolve_run_path,
    set_status,
    sha256_file,
    utc_now,
    write_json, rel_posix)
from .package_diff import compare_parts


PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
RML = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CTML = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"p": PML, "r": RML, "pr": PKG_REL, "ct": CTML}
SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"


def _xml_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _relationship_owner(rel_part: str) -> str:
    if rel_part == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in rel_part or not rel_part.endswith(".rels"):
        raise D6PPTError(f"Invalid relationship part name: {rel_part}", "invalid_pptx_package")
    prefix, filename = rel_part.split(marker, 1)
    return posixpath.join(prefix, filename[:-5])


def _relationship_part(owner: str) -> str:
    return posixpath.join(posixpath.dirname(owner), "_rels", posixpath.basename(owner) + ".rels")


def _resolve_target(owner: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner), target))


def _referenced_relationship_ids(root: etree._Element) -> set[str]:
    values: set[str] = set()
    prefix = f"{{{RML}}}"
    for element in root.iter():
        for key, value in element.attrib.items():
            if key.startswith(prefix) and value:
                values.add(str(value))
    return values


def _protected_hashes(entries: dict[str, bytes]) -> dict[str, str]:
    return {
        name: hashlib.sha256(data).hexdigest()
        for name, data in entries.items()
        if name.startswith(("ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/", "ppt/notesSlides/"))
    }


def _logical_slide_parts(entries: dict[str, bytes]) -> tuple[list[str], etree._Element, etree._Element]:
    required = ("[Content_Types].xml", "ppt/presentation.xml", "ppt/_rels/presentation.xml.rels")
    missing = [name for name in required if name not in entries]
    if missing:
        raise D6PPTError("PPTX is missing required package parts", "invalid_pptx_package", {"missing": missing})
    presentation = etree.fromstring(entries["ppt/presentation.xml"])
    relationships = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])
    targets = {
        str(rel.get("Id")): _resolve_target("ppt/presentation.xml", str(rel.get("Target")))
        for rel in relationships.xpath("./pr:Relationship", namespaces=NS)
        if rel.get("Id") and rel.get("Target") and rel.get("TargetMode") != "External"
    }
    ordered_ids = presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)
    slide_parts = [targets.get(str(rel_id), "") for rel_id in ordered_ids]
    if not slide_parts or any(not part.startswith("ppt/slides/") or part not in entries for part in slide_parts):
        raise D6PPTError("Presentation slide list has a missing or invalid target", "invalid_pptx_package")
    if len(set(slide_parts)) != len(slide_parts):
        raise D6PPTError("Presentation slide list contains duplicate targets", "invalid_pptx_package")
    return slide_parts, presentation, relationships


def _relationship_edges(entries: dict[str, bytes]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for rel_part, data in entries.items():
        if not (rel_part == "_rels/.rels" or rel_part.endswith(".rels")):
            continue
        owner = _relationship_owner(rel_part)
        root = etree.fromstring(data)
        for rel in root.xpath("./pr:Relationship", namespaces=NS):
            if rel.get("TargetMode") == "External" or not rel.get("Target"):
                continue
            edges.append({
                "owner": owner,
                "rel_part": rel_part,
                "relationship_id": str(rel.get("Id") or ""),
                "type": str(rel.get("Type") or ""),
                "target": _resolve_target(owner, str(rel.get("Target"))),
            })
    return edges


def _validate_relationship_closure(entries: dict[str, bytes]) -> list[dict[str, str]]:
    missing = [edge for edge in _relationship_edges(entries) if edge["target"] not in entries]
    if missing:
        raise D6PPTError("Package cleanup would leave broken internal relationships", "package_relationship_closure_failed", missing)
    return missing


def clean_orphan_slides(run: Path) -> dict[str, Any]:
    """Remove only provably unused slide parts and unused slide-jump relationships."""
    run = run.resolve()
    manifest = load_run(run)
    current_ref = manifest.get("artifacts", {}).get("current_pptx")
    if not current_ref:
        raise D6PPTError("No current PPTX is available for package cleanup", "pptx_missing")
    current = resolve_run_path(run, str(current_ref))
    if not current.is_file():
        raise D6PPTError("Current PPTX is missing", "pptx_missing")
    before_sha = sha256_file(current)
    with zipfile.ZipFile(current, "r") as archive:
        if archive.testzip():
            raise D6PPTError("Current PPTX ZIP is corrupt", "invalid_pptx_package")
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    logical_slides, presentation, presentation_rels = _logical_slide_parts(entries)
    logical_set = set(logical_slides)
    live_slide_hashes = {name: hashlib.sha256(entries[name]).hexdigest() for name in logical_slides}
    protected_before = _protected_hashes(entries)
    presentation_refs = _referenced_relationship_ids(presentation)
    removed_relationships: list[dict[str, Any]] = []

    for rel in list(presentation_rels.xpath("./pr:Relationship", namespaces=NS)):
        if rel.get("Type") != SLIDE_REL_TYPE or str(rel.get("Id") or "") in presentation_refs:
            continue
        target = _resolve_target("ppt/presentation.xml", str(rel.get("Target") or ""))
        removed_relationships.append({
            "owner": "ppt/presentation.xml",
            "relationship_id": str(rel.get("Id") or ""),
            "target": target,
            "reason": "slide_relationship_not_referenced_by_presentation_xml",
        })
        presentation_rels.remove(rel)
    entries["ppt/_rels/presentation.xml.rels"] = _xml_bytes(presentation_rels)

    for slide_part in logical_slides:
        rel_part = _relationship_part(slide_part)
        if rel_part not in entries:
            continue
        slide_root = etree.fromstring(entries[slide_part])
        slide_refs = _referenced_relationship_ids(slide_root)
        rel_root = etree.fromstring(entries[rel_part])
        changed = False
        for rel in list(rel_root.xpath("./pr:Relationship", namespaces=NS)):
            if rel.get("Type") != SLIDE_REL_TYPE or str(rel.get("Id") or "") in slide_refs:
                continue
            removed_relationships.append({
                "owner": slide_part,
                "relationship_id": str(rel.get("Id") or ""),
                "target": _resolve_target(slide_part, str(rel.get("Target") or "")),
                "reason": "slide_jump_relationship_not_referenced_by_live_slide_xml",
            })
            rel_root.remove(rel)
            changed = True
        if changed:
            entries[rel_part] = _xml_bytes(rel_root)

    all_slide_parts = {
        name for name in entries
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
    }
    orphan_candidates = sorted(all_slide_parts - logical_set)
    incoming = {name: [] for name in orphan_candidates}
    edges = _relationship_edges(entries)
    for edge in edges:
        if edge["target"] in incoming:
            incoming[edge["target"]].append(edge)
    orphan_set = set(orphan_candidates)
    retained_set = {
        name for name in orphan_candidates
        if any(edge["owner"] not in orphan_set for edge in incoming[name])
    }
    changed_retained = True
    while changed_retained:
        changed_retained = False
        for edge in edges:
            if edge["owner"] in retained_set and edge["target"] in orphan_set and edge["target"] not in retained_set:
                retained_set.add(edge["target"])
                changed_retained = True
    removable = sorted(orphan_set - retained_set)
    retained = [
        {"slide_part": name, "incoming_relationships": incoming[name]}
        for name in orphan_candidates if name in retained_set
    ]
    for slide_part in removable:
        entries.pop(slide_part, None)
        entries.pop(_relationship_part(slide_part), None)

    content_types = etree.fromstring(entries["[Content_Types].xml"])
    removed_overrides: list[str] = []
    removed_part_names = {f"/{name}" for name in removable}
    for override in list(content_types.xpath("./ct:Override", namespaces=NS)):
        part_name = str(override.get("PartName") or "")
        if part_name in removed_part_names:
            content_types.remove(override)
            removed_overrides.append(part_name)
    entries["[Content_Types].xml"] = _xml_bytes(content_types)

    _validate_relationship_closure(entries)
    after_logical, _presentation_after, _rels_after = _logical_slide_parts(entries)
    if after_logical != logical_slides:
        raise D6PPTError("Package cleanup changed logical slide order", "package_cleanup_scope_violation")
    after_live_hashes = {name: hashlib.sha256(entries[name]).hexdigest() for name in logical_slides}
    if after_live_hashes != live_slide_hashes or _protected_hashes(entries) != protected_before:
        raise D6PPTError("Package cleanup changed live slides or protected parts", "package_cleanup_scope_violation")

    changed = bool(removed_relationships or removable or removed_overrides)
    receipt_path = run / "evidence" / "package_cleanup_receipt.json"
    if not changed:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "status": "pass",
            "result": "no_change",
            "source_pptx": rel_posix(current, run),
            "source_pptx_sha256": before_sha,
            "logical_slide_count": len(logical_slides),
            "retained_nonlogical_slides": retained,
        }
        write_json(receipt_path, receipt)
        manifest["artifacts"]["package_cleanup_receipt"] = rel_posix(receipt_path, run)
        from .common import save_run
        save_run(run, manifest)
        return receipt

    output = run / "artifacts" / "package-cleaned.pptx"
    if output.exists():
        raise D6PPTError("Package-cleaned output already exists; create a new run", "artifact_exists")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(output, "r") as archive:
        corrupt = archive.testzip()
    if corrupt:
        output.unlink(missing_ok=True)
        raise D6PPTError(f"Package cleanup produced a corrupt part: {corrupt}", "invalid_pptx_package")
    after_sha = sha256_file(output)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "pass",
        "result": "cleaned",
        "source_pptx": rel_posix(current, run),
        "source_pptx_sha256": before_sha,
        "output_pptx": rel_posix(output, run),
        "output_pptx_sha256": after_sha,
        "logical_slide_count": len(logical_slides),
        "removed_relationships": removed_relationships,
        "removed_orphan_slide_parts": removable,
        "removed_content_type_overrides": removed_overrides,
        "retained_nonlogical_slides": retained,
        "scope_invariants": {
            "logical_slide_order_unchanged": True,
            "live_slide_xml_unchanged": True,
            "masters_layouts_themes_notes_unchanged": True,
            "internal_relationship_closure": "pass",
        },
        "package_diff": compare_parts(current, output),
    }
    write_json(receipt_path, receipt)
    stale = invalidate_pptx_derived_artifacts(manifest)
    if stale:
        manifest.setdefault("stale_artifacts", []).append({
            "at": utc_now(), "reason": "pptx_sha_changed_after_package_clean", "artifacts": stale,
        })
    manifest["artifacts"].update({
        "current_pptx": rel_posix(output, run),
        "pptx_sha256": after_sha,
        "package_cleanup_receipt": rel_posix(receipt_path, run),
    })
    manifest["unreplayed_patches"] = []
    set_status(run, manifest, "compiled", "package_clean", {
        "removed_relationship_count": len(removed_relationships),
        "removed_orphan_slide_count": len(removable),
    })
    return receipt
