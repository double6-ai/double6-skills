from __future__ import annotations

import re

import shutil
from pathlib import Path
from typing import Any

from lxml import etree

from .common import D6PPTError, SCHEMA_VERSION, read_json, sha256_tree, skill_root, utc_now, write_json
from .native_markers import normalize_native_markers, parse_spec_lock_palette
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


def _unwrap_single_line_tspans(root: etree._Element) -> list[str]:
    """Unwrap ``<text data-pptx-shape-id><tspan x=same>line</tspan></text>``.

    The vendored PPT Master v4.8.0 tspan lowering rebuilds a single positional
    tspan as a fresh ``<text>`` and drops ``data-pptx-shape-id`` on the way, so
    the stable DrawingML identity silently disappears (multi-line paragraphs
    keep it). Collapsing the redundant wrapper in the build copy is lossless
    and keeps the identity contract without patching vendor code.
    """
    unwrapped: list[str] = []
    for text in root.iter(f"{{{SVG_NS}}}text"):
        shape_id = text.get("data-pptx-shape-id")
        if shape_id is None or (text.text or "").strip():
            continue
        children = list(text)
        if len(children) != 1:
            continue
        tspan = children[0]
        if etree.QName(tspan).localname != "tspan" or len(tspan) or (tspan.tail or "").strip():
            continue
        extra = set(tspan.attrib) - {"x", "dy", "y"}
        if extra:
            continue
        if tspan.get("dy") not in (None, "0", "0px", "0em"):
            continue
        if tspan.get("y") is not None and tspan.get("y") != text.get("y"):
            continue
        if tspan.get("x") is not None and tspan.get("x") != text.get("x"):
            continue
        text.text = tspan.text or ""
        text.remove(tspan)
        unwrapped.append(shape_id)
    return unwrapped


ICON_REF = re.compile(r'data-icon="([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"')


def _stage_icons(source_project: Path, build_project: Path) -> list[str]:
    """Copy every referenced ``data-icon`` into ``build/icons/<lib>/`` so the vendored checker
    and converter embed them natively. Project-local icons win over the vendored library."""
    vendored = skill_root() / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "templates" / "icons"
    staged: list[str] = []
    missing: list[str] = []
    svg_dir = build_project / "svg_output"
    refs = set()
    for svg in sorted(svg_dir.glob("*.svg")) if svg_dir.is_dir() else []:
        refs |= set(ICON_REF.findall(svg.read_text(encoding="utf-8")))
    for lib, name in sorted(refs):
        target = build_project / "icons" / lib / f"{name}.svg"
        if target.is_file():
            continue
        for candidate in (source_project / "icons" / lib / f"{name}.svg", vendored / lib / f"{name}.svg"):
            if candidate.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, target)
                staged.append(f"{lib}/{name}")
                break
        else:
            missing.append(f"{lib}/{name}")
    if missing:
        raise D6PPTError(
            "Icons are not available in the vendored library or authoring/project/icons: " + ", ".join(missing),
            "icon_missing",
            {"missing": missing, "vendored_library": "vendor/ppt-master-core/skills/ppt-master/templates/icons/tabler-outline",
             "next_step": "Pick an existing name (see scripts/maintenance/design_icons_tabler_outline.txt) or add the SVG under authoring/project/icons/<lib>/."},
        )
    return staged


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
    authority_policy = str((semantic.get("defaults") or {}).get("native_marker_authority") or "json")
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
    staged_icons = _stage_icons(source_project, build_project)
    if staged_icons:
        changes.append({"action": "stage_icons", "icons": staged_icons})
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

    spec_lock = build_project / "spec_lock.md"
    palette = parse_spec_lock_palette(spec_lock.read_text(encoding="utf-8")) if spec_lock.is_file() else {}
    if (semantic.get("defaults") or {}).get("native_palette") is False:
        palette = {}
    svg_dir = build_project / "svg_output"
    for svg_file in sorted(svg_dir.glob("*.svg")) if svg_dir.is_dir() else []:
        relative = svg_file.relative_to(build_project).as_posix()
        if relative not in parsed:
            parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, no_network=True)
            parsed[relative] = (svg_file, etree.parse(str(svg_file), parser))
        unwrapped = _unwrap_single_line_tspans(parsed[relative][1].getroot())
        if unwrapped:
            changes.append({"file": relative, "action": "unwrap_single_line_tspan", "shape_ids": unwrapped})
        markers = normalize_native_markers(parsed[relative][1].getroot(), authority_policy=authority_policy, palette=palette)
        if markers:
            changes.append({"file": relative, "action": "normalize_native_markers", "markers": markers})

    for _, (target_file, tree) in parsed.items():
        tree.write(str(target_file), encoding="UTF-8", xml_declaration=False, pretty_print=False)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "adapter": "ppt-master-deep-adapter",
        "policy": "selective_safe_top_levelization",
        "native_marker_authority": authority_policy,
        "source_project_sha256": sha256_tree(source_project),
        "build_project_sha256": sha256_tree(build_project),
        "changes": changes,
    }
    write_json(receipt_path, receipt)
    return receipt
