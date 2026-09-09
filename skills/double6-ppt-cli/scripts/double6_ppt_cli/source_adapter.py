from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from lxml import etree

from .common import D6PPTError, SCHEMA_VERSION, read_json, sha256_tree, utc_now, write_json
from .schemas import validate_semantic_manifest


SVG_NS = "http://www.w3.org/2000/svg"
STRUCTURES_REQUIRING_TOP_LEVEL = {"top_level", "placeholder"}
SAFE_GROUP_ATTRIBUTES = {"id", "data-pptx-bounds"}


def _select_by_id(root: etree._Element, source_id: str) -> list[etree._Element]:
    return root.xpath("//*[@id=$source_id]", source_id=source_id)


def _flatten_safe_group(group: etree._Element, *, label: str) -> int:
    if etree.QName(group).localname != "g":
        return 0
    unsafe = sorted(set(group.attrib) - SAFE_GROUP_ATTRIBUTES)
    if unsafe:
        raise D6PPTError(
            f"{label}: refusing to flatten group with unsafe attributes: {', '.join(unsafe)}",
            "unsafe_source_flatten",
        )
    parent = group.getparent()
    if parent is None or etree.QName(parent).localname != "svg":
        raise D6PPTError(f"{label}: only direct SVG groups may be flattened", "unsafe_source_flatten")
    children = list(group)
    if not children:
        raise D6PPTError(f"{label}: empty group cannot be flattened", "unsafe_source_flatten")
    index = parent.index(group)
    for offset, child in enumerate(children):
        group.remove(child)
        parent.insert(index + offset, child)
    parent.remove(group)
    return len(children)


def prepare_ppt_master_project(
    source_project: Path,
    semantic_manifest_path: Path,
    build_project: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Create a deterministic compiler workspace and selectively flatten safe groups.

    The authoring source remains immutable. Only semantic objects whose preferred
    structure requires a top-level DrawingML object participate in this adapter.
    Multiple objects may point at one source group; that group is flattened once.
    """
    semantic = read_json(semantic_manifest_path)
    validate_semantic_manifest(semantic, source_project)
    if build_project.exists():
        shutil.rmtree(build_project)
    build_project.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_project, build_project)

    selectors: dict[tuple[str, str], list[str]] = {}
    for obj in semantic["objects"]:
        if obj.get("preferred_structure") not in STRUCTURES_REQUIRING_TOP_LEVEL:
            continue
        selector = obj["source_selector"]
        relative = selector.get("file")
        selected_id = selector.get("id")
        if not relative or not selected_id:
            raise D6PPTError(
                f"{obj['source_id']}: top-level adaptation requires source_selector.file and id",
                "invalid_source_selector",
            )
        selectors.setdefault((str(relative), str(selected_id)), []).append(obj["source_id"])

    changes: list[dict[str, Any]] = []
    parsed: dict[str, tuple[Path, etree._ElementTree]] = {}
    for (relative, selected_id), source_ids in sorted(selectors.items()):
        target_file = (build_project / relative).resolve()
        try:
            target_file.relative_to(build_project.resolve())
        except ValueError as exc:
            raise D6PPTError(f"Source selector escapes project: {relative}", "invalid_source_selector") from exc
        if not target_file.is_file():
            raise D6PPTError(f"Source selector file is missing: {relative}", "invalid_source_selector")
        if relative not in parsed:
            parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, no_network=True)
            parsed[relative] = (target_file, etree.parse(str(target_file), parser))
        _, tree = parsed[relative]
        matches = _select_by_id(tree.getroot(), selected_id)
        if len(matches) != 1:
            raise D6PPTError(
                f"Source selector must resolve uniquely: {relative}#{selected_id} candidates={len(matches)}",
                "ambiguous_source_selector",
            )
        target = matches[0]
        flattened_children = _flatten_safe_group(target, label=f"{relative}#{selected_id}")
        changes.append({
            "file": relative,
            "id": selected_id,
            "source_ids": sorted(source_ids),
            "action": "flatten_group" if flattened_children else "already_top_level",
            "flattened_children": flattened_children,
        })

    for _, (target_file, tree) in parsed.items():
        tree.write(str(target_file), encoding="UTF-8", xml_declaration=False, pretty_print=False)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "adapter": "ppt-master-deep-adapter",
        "policy": "selective_safe_top_levelization",
        "source_project_sha256": sha256_tree(source_project),
        "build_project_sha256": sha256_tree(build_project),
        "changes": changes,
    }
    write_json(receipt_path, receipt)
    return receipt
