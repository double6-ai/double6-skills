from __future__ import annotations

import hashlib
import importlib.util
import math
import posixpath
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from .common import (
    D6PPTError,
    SCHEMA_VERSION,
    load_run,
    read_json,
    resolve_run_path,
    save_run,
    set_status,
    sha256_file,
    skill_root,
    utc_now,
    write_json, rel_posix)
from .officecli import OfficeCLI
from .package_diff import compare_parts


PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
AML = "http://schemas.openxmlformats.org/drawingml/2006/main"
RML = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CTML = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"p": PML, "a": AML, "r": RML, "pr": PKG_REL}
SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
SLIDE_JUMP_ACTION = "ppaction://hlinksldjump"

# ECMA-376 CT_TextParagraph child order used to repair Fill Native output.
_PARAGRAPH_CHILD_ORDER = {
    f"{{{AML}}}pPr": 0,
    f"{{{AML}}}r": 10,
    f"{{{AML}}}br": 20,
    f"{{{AML}}}fld": 30,
    f"{{{AML}}}endParaRPr": 40,
}


def _normalize_txbody_paragraph_order(pptx: Path) -> int:
    """Fix a:p child order after vendor text fill (endParaRPr must follow runs)."""
    changed_parts = 0
    try:
        with zipfile.ZipFile(pptx, "r") as archive:
            entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    except zipfile.BadZipFile:
        return 0
    for name, data in list(entries.items()):
        if not (name.startswith("ppt/slides/") or name.startswith("ppt/slideLayouts/") or name.startswith("ppt/slideMasters/")):
            continue
        if not name.endswith(".xml"):
            continue
        try:
            root = etree.fromstring(data)
        except etree.XMLSyntaxError:
            continue
        dirty = False
        for paragraph in root.xpath(".//a:p", namespaces=NS):
            children = list(paragraph)
            keys = [
                (_PARAGRAPH_CHILD_ORDER.get(child.tag, 50), index, child)
                for index, child in enumerate(children)
            ]
            ordered = [child for _k, _i, child in sorted(keys, key=lambda item: (item[0], item[1]))]
            if ordered != children:
                for child in children:
                    paragraph.remove(child)
                for child in ordered:
                    paragraph.append(child)
                dirty = True
        if dirty:
            entries[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            changed_parts += 1
    if not changed_parts:
        return 0
    with tempfile.NamedTemporaryFile(prefix="d6-txbody-order-", suffix=".pptx", dir=pptx.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        temp_path.replace(pptx)
    finally:
        temp_path.unlink(missing_ok=True)
    return changed_parts


DISPOSITIONS = {
    "keep_design",
    "replace_content",
    "update_navigation",
    "remove_sample",
    "preserve_attribution",
    "manual_review",
}


def _image_kind(path: Path) -> tuple[str, str]:
    head = path.read_bytes()[:12]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    raise D6PPTError("Template replacement asset must be a PNG or JPEG image", "invalid_template_image_asset")


def import_template_asset(run: Path, asset: Path, name: str) -> dict[str, Any]:
    """Freeze one user-approved image inside a template-fill run."""
    run = run.resolve()
    manifest = load_run(run)
    if manifest.get("mode") != "template-fill":
        raise D6PPTError("Template assets are only valid for template-fill runs", "invalid_mode")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name or "") or "/" in name or "\\" in name:
        raise D6PPTError("Template asset name must be one safe file name", "invalid_template_asset_name")
    asset = asset.resolve()
    if not asset.is_file():
        raise D6PPTError(f"Template asset does not exist: {asset}", "template_asset_missing")
    extension, content_type = _image_kind(asset)
    requested_suffix = Path(name).suffix.lower().lstrip(".")
    if requested_suffix == "jpeg":
        requested_suffix = "jpg"
    if requested_suffix != extension:
        raise D6PPTError("Template asset name extension does not match its bytes", "template_asset_extension_mismatch")
    destination = run / "input" / "template_assets" / name
    digest = sha256_file(asset)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise D6PPTError("Template asset name already refers to different bytes", "template_asset_name_collision")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset, destination)
    record = {
        "name": name,
        "copied_path": rel_posix(destination, run),
        "sha256": digest,
        "extension": extension,
        "content_type": content_type,
    }
    assets = manifest.setdefault("template_assets", {})
    existing = assets.get(name)
    if existing and existing.get("sha256") != digest:
        raise D6PPTError("Template asset manifest collision", "template_asset_name_collision")
    assets[name] = record
    save_run(run, manifest)
    return {"schema_version": SCHEMA_VERSION, "status": "pass", **record}


def _vendor_modules():
    scripts = skill_root() / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    package_dir = scripts / "template_fill_pptx"
    module_name = "double6_vendor_template_fill_pptx"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            module_name,
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise D6PPTError("Vendored PPT Master Fill Native package is unavailable", "vendor_template_fill_missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return module.analyze_pptx, module.apply_plan, module.check_plan, module.scaffold_plan


def _template_path(run: Path, manifest: dict[str, Any]) -> Path:
    record = manifest.get("template")
    if not isinstance(record, dict) or not record.get("copied_path"):
        raise D6PPTError("This run has no frozen template", "template_missing")
    template = resolve_run_path(run, record["copied_path"])
    if not template.is_file() or sha256_file(template) != record.get("sha256"):
        raise D6PPTError("Frozen template is missing or stale", "stale_template")
    return template


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _relationships(archive: zipfile.ZipFile, slide_part: str) -> dict[str, str]:
    rel_part = posixpath.join(posixpath.dirname(slide_part), "_rels", posixpath.basename(slide_part) + ".rels")
    if rel_part not in archive.namelist():
        return {}
    root = etree.fromstring(archive.read(rel_part))
    result: dict[str, str] = {}
    for rel in root.xpath("./pr:Relationship", namespaces=NS):
        target = rel.get("Target")
        if not target or rel.get("TargetMode") == "External":
            continue
        result[str(rel.get("Id"))] = posixpath.normpath(posixpath.join(posixpath.dirname(slide_part), target))
    return result


def _cnvpr(element: etree._Element) -> etree._Element | None:
    rows = element.xpath(
        "./p:nvSpPr/p:cNvPr | ./p:nvPicPr/p:cNvPr | ./p:nvGraphicFramePr/p:cNvPr | "
        "./p:nvGrpSpPr/p:cNvPr | ./p:nvCxnSpPr/p:cNvPr",
        namespaces=NS,
    )
    return rows[0] if rows else None


def _geometry(element: etree._Element) -> dict[str, int | None]:
    offsets = element.xpath("./p:spPr/a:xfrm/a:off | ./p:blipFill/../p:spPr/a:xfrm/a:off | ./p:xfrm/a:off | ./p:grpSpPr/a:xfrm/a:off", namespaces=NS)
    extents = element.xpath("./p:spPr/a:xfrm/a:ext | ./p:blipFill/../p:spPr/a:xfrm/a:ext | ./p:xfrm/a:ext | ./p:grpSpPr/a:xfrm/a:ext", namespaces=NS)
    off = offsets[0] if offsets else None
    ext = extents[0] if extents else None
    return {
        "x_emu": int(off.get("x")) if off is not None and off.get("x") else None,
        "y_emu": int(off.get("y")) if off is not None and off.get("y") else None,
        "width_emu": int(ext.get("cx")) if ext is not None and ext.get("cx") else None,
        "height_emu": int(ext.get("cy")) if ext is not None and ext.get("cy") else None,
    }


def _classify(text: str, object_type: str, placeholder: str | None) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if placeholder or (object_type in {"shape", "textbox"} and not compact):
        return "content_slot"
    if object_type in {"picture", "chart", "table", "equation", "ole"}:
        return "unknown"
    if not compact:
        return "design_system"
    return "unknown"


def build_pptx_profile(pptx: Path) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    media_sha: dict[str, str] = {}
    protected_parts: dict[str, str] = {}
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(pptx) as archive:
        names = set(archive.namelist())
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        size = presentation.xpath("./p:sldSz", namespaces=NS)
        canvas = {
            "width_emu": int(size[0].get("cx")) if size else None,
            "height_emu": int(size[0].get("cy")) if size else None,
        }
        presentation_rels = _relationships(archive, "ppt/presentation.xml")
        ordered_ids = presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)
        slide_parts = [
            presentation_rels[str(rel_id)] for rel_id in ordered_ids
            if presentation_rels.get(str(rel_id)) in names
        ]
        slide_number_by_part = {part: number for number, part in enumerate(slide_parts, 1)}
        for slide_number, slide_part in enumerate(slide_parts, 1):
            root = etree.fromstring(archive.read(slide_part))
            rels = _relationships(archive, slide_part)
            layout_part = next((target for target in rels.values() if target.startswith("ppt/slideLayouts/")), None)
            layout_rels = _relationships(archive, layout_part) if layout_part else {}
            master_part = next((target for target in layout_rels.values() if target.startswith("ppt/slideMasters/")), None)
            master_rels = _relationships(archive, master_part) if master_part else {}
            theme_part = next((target for target in master_rels.values() if target.startswith("ppt/theme/")), None)
            tree = root.xpath("./p:cSld/p:spTree", namespaces=NS)
            if not tree:
                continue

            def visit(container: etree._Element, path_prefix: str, identity_prefix: str) -> None:
                for zorder, element in enumerate(container, 1):
                    local = etree.QName(element).localname
                    if local in {"nvGrpSpPr", "grpSpPr"}:
                        continue
                    cnv = _cnvpr(element)
                    if cnv is None or not cnv.get("id"):
                        continue
                    shape_id = int(cnv.get("id"))
                    type_map = {
                        "sp": "shape", "pic": "picture", "graphicFrame": "graphic_frame",
                        "grpSp": "group", "cxnSp": "connector",
                    }
                    object_type = type_map.get(local, local)
                    if object_type == "graphic_frame":
                        if element.xpath(".//a:tbl", namespaces=NS):
                            object_type = "table"
                        elif element.xpath(".//*[local-name()='chart']"):
                            object_type = "chart"
                        elif element.xpath(".//*[local-name()='oleObj']"):
                            object_type = "ole"
                    if object_type == "shape" and element.xpath(".//*[local-name()='oMath']"):
                        object_type = "equation"
                    text = "" if object_type == "group" else "".join(element.xpath(".//a:t/text()", namespaces=NS)).strip()
                    ph = element.xpath("./p:nvSpPr/p:nvPr/p:ph", namespaces=NS)
                    placeholder = (ph[0].get("type") or "body") if ph else None
                    media_part = None
                    media_digest = None
                    embeds = element.xpath("./p:blipFill/a:blip/@r:embed", namespaces=NS)
                    if embeds:
                        media_part = rels.get(str(embeds[0]))
                        if media_part and media_part in names:
                            media_digest = hashlib.sha256(archive.read(media_part)).hexdigest()
                            media_sha[media_part] = media_digest
                    jump_ids = cnv.xpath(
                        "./a:hlinkClick[@action='ppaction://hlinksldjump']/@r:id",
                        namespaces=NS,
                    )
                    jump_parts = [rels.get(str(rel_id)) for rel_id in jump_ids if rels.get(str(rel_id))]
                    jump_source_slides = [
                        slide_number_by_part[part] for part in jump_parts if part in slide_number_by_part
                    ]
                    office_element = {
                        "shape": "shape", "picture": "picture", "group": "group",
                        "connector": "connector", "table": "table", "chart": "chart",
                        "ole": "ole", "equation": "equation",
                    }.get(object_type, "shape")
                    office_path = f"{path_prefix}/{office_element}[@id={shape_id}]"
                    object_id = f"{identity_prefix}:{object_type}:{shape_id}"
                    role = "navigation" if jump_source_slides else _classify(text, object_type, placeholder)
                    objects.append({
                        "source_object_id": object_id,
                        "source_template_slide": slide_number,
                        "slide_part": slide_part,
                        "layout_part": layout_part,
                        "master_part": master_part,
                        "theme_part": theme_part,
                        "drawingml_id": shape_id,
                        "drawingml_name": cnv.get("name"),
                        "object_type": object_type,
                        "officecli_element": office_element,
                        "officecli_path": office_path,
                        "zorder": zorder,
                        "geometry": _geometry(element),
                        "placeholder": placeholder,
                        "text": text,
                        "normalized_text": re.sub(r"\s+", " ", text).strip(),
                        "text_sha256": _sha_text(re.sub(r"\s+", " ", text).strip()),
                        "media_part": media_part,
                        "media_sha256": media_digest,
                        "slide_jump_source_slides": jump_source_slides,
                        "role": role,
                        "disposition": "unassigned",
                    })
                    counts[object_type] += 1
                    if object_type == "group":
                        visit(element, office_path, object_id)

            visit(tree[0], f"/slide[{slide_number}]", f"s{slide_number:02d}")
        counts["slides"] = len(slide_parts)
        counts["masters"] = len([n for n in names if re.fullmatch(r"ppt/slideMasters/slideMaster\d+\.xml", n)])
        counts["layouts"] = len([n for n in names if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)])
        counts["themes"] = len([n for n in names if re.fullmatch(r"ppt/theme/theme\d+\.xml", n)])
        counts["notes"] = len([n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)])
        for name in sorted(names):
            if name.startswith(("ppt/slideMasters/", "ppt/slideLayouts/", "ppt/theme/", "ppt/notesSlides/")):
                protected_parts[name] = hashlib.sha256(archive.read(name)).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "pptx": str(pptx),
        "pptx_sha256": sha256_file(pptx),
        "canvas": canvas,
        "counts": dict(counts),
        "media": [{"part": part, "sha256": digest} for part, digest in sorted(media_sha.items())],
        "protected_parts_sha256": protected_parts,
        "objects": objects,
    }


def _default_disposition(obj: dict[str, Any]) -> str:
    if obj["role"] == "design_system":
        return "keep_design"
    if obj["role"] == "content_slot":
        return "replace_content"
    if obj["role"] in {"sample_content", "sample_formula_media"}:
        return "remove_sample"
    if obj["role"] == "navigation":
        return "update_navigation"
    if obj["role"] == "attribution":
        return "manual_review"
    return "manual_review"


PROFILE_ROLES = {
    "attribution", "navigation", "sample_content", "sample_formula_media",
    "content_slot", "design_system", "unknown",
}


def _apply_template_profile_rules(profile: dict[str, Any], rules: list[dict[str, Any]]) -> None:
    """Apply project-specific template labels only when the content contract declares them."""
    for index, rule in enumerate(rules, 1):
        if not isinstance(rule, dict) or rule.get("role") not in PROFILE_ROLES:
            raise D6PPTError(f"Invalid template profile rule {index}", "invalid_content_contract")
        text_pattern = rule.get("text_pattern")
        name_pattern = rule.get("name_pattern")
        try:
            text_re = re.compile(str(text_pattern), re.I) if text_pattern else None
            name_re = re.compile(str(name_pattern), re.I) if name_pattern else None
        except re.error as exc:
            raise D6PPTError(f"Invalid template profile rule {index}: {exc}", "invalid_content_contract") from exc
        if text_re is None and name_re is None and not rule.get("object_type") and not rule.get("slides"):
            raise D6PPTError(f"Template profile rule {index} has no selector", "invalid_content_contract")
        selected_slides = {int(value) for value in rule.get("slides", [])}
        for obj in profile.get("objects", []):
            if selected_slides and int(obj.get("source_template_slide", 0)) not in selected_slides:
                continue
            if rule.get("object_type") and obj.get("object_type") != rule["object_type"]:
                continue
            if text_re and not text_re.search(str(obj.get("text") or "")):
                continue
            if name_re and not name_re.search(str(obj.get("drawingml_name") or "")):
                continue
            obj["role"] = rule["role"]
            obj["profile_rule_id"] = str(rule.get("rule_id") or f"rule-{index:03d}")


def analyze_template(run: Path) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    template = _template_path(run, manifest)
    analyze_pptx, _apply_plan, _check_plan, scaffold_plan = _vendor_modules()
    library = analyze_pptx(template)
    library_path = run / "artifacts" / "template.slide_library.json"
    write_json(library_path, library)
    profile = build_pptx_profile(template)
    contract_record = manifest.get("content_contract")
    if isinstance(contract_record, dict) and contract_record.get("copied_path"):
        contract_path = resolve_run_path(run, contract_record["copied_path"])
        if sha256_file(contract_path) != contract_record.get("sha256"):
            raise D6PPTError("Content contract is stale", "stale_content_contract")
        contract = read_json(contract_path)
        _apply_template_profile_rules(profile, contract.get("template_profile_rules", []))
    profile["content_sha256"] = manifest["input"]["sha256"]
    profile_path = run / "artifacts" / "template_profile.json"
    write_json(profile_path, profile)
    scaffold = scaffold_plan(library, None, include_empty=True)
    scaffold["schema_version"] = SCHEMA_VERSION
    scaffold["status"] = "draft"
    scaffold["template_sha256"] = profile["pptx_sha256"]
    scaffold["content_sha256"] = manifest["input"]["sha256"]
    dispositions = []
    by_slide: dict[int, list[dict[str, Any]]] = {}
    for obj in profile["objects"]:
        by_slide.setdefault(int(obj["source_template_slide"]), []).append(obj)
    for plan_slide, slide in enumerate(scaffold.get("slides", []), 1):
        source_slide = int(slide["source_slide"])
        for obj in by_slide.get(source_slide, []):
            dispositions.append({
                "plan_slide": plan_slide,
                "source_slide": source_slide,
                "source_object_id": obj["source_object_id"],
                "disposition": _default_disposition(obj),
                "user_confirmed": False,
                "expected_fingerprint": {
                    "drawingml_id": obj["drawingml_id"],
                    "object_type": obj["object_type"],
                    "text_sha256": obj["text_sha256"],
                    "media_sha256": obj["media_sha256"],
                },
            })
    scaffold["object_dispositions"] = dispositions
    scaffold["numeric_claims"] = []
    scaffold_path = run / "plans" / "template_plan_scaffold.json"
    write_json(scaffold_path, scaffold)
    manifest["artifacts"].update({
        "template_library": rel_posix(library_path, run),
        "template_profile": rel_posix(profile_path, run),
        "template_plan_scaffold": rel_posix(scaffold_path, run),
    })
    set_status(run, manifest, "authored", "template_analyze", {"object_count": len(profile["objects"])})
    return {
        "status": "pass",
        "template_profile": str(profile_path),
        "template_library": str(library_path),
        "plan_scaffold": str(scaffold_path),
        "object_count": len(profile["objects"]),
    }


def _plan_text(plan: dict[str, Any]) -> str:
    values: list[str] = []
    for slide in plan.get("slides", []):
        values.append(str(slide.get("notes") or ""))
        for replacement in slide.get("replacements", []):
            values.append(str(replacement.get("text") or ""))
    return "\n".join(values)


def _check_numeric_claims(plan: dict[str, Any]) -> list[dict[str, Any]]:
    def number(value: Any) -> float:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if not match:
            raise ValueError(f"No numeric value in {value!r}")
        return float(match.group())

    results = []
    haystack = _plan_text(plan)
    for index, claim in enumerate(plan.get("numeric_claims", []), 1):
        claim_id = claim.get("claim_id") or f"numeric-{index:03d}"
        relation = claim.get("relation")
        operands = claim.get("operands")
        expected = str(claim.get("expected_display") or claim.get("expected") or "")
        forbidden_value = claim.get("forbidden_displays", claim.get("forbidden", []))
        forbidden = [str(value) for value in forbidden_value]
        status = "OK"
        message = "numeric claim is consistent"
        if relation == "percentage_point_difference":
            if not isinstance(operands, list) or len(operands) != 2:
                status, message = "ERROR", "percentage point difference requires exactly two operands"
            else:
                computed = abs(number(operands[0]) - number(operands[1]))
                declared = claim.get("result")
                if declared is None:
                    declared = expected
                try:
                    declared_number = number(declared)
                except ValueError:
                    declared_number = float("nan")
                if not math.isfinite(declared_number) or abs(declared_number - computed) > 1e-9:
                    status, message = "ERROR", f"declared result does not equal {computed:g} percentage points"
        elif relation not in {"difference", "ratio"}:
            status, message = "ERROR", f"unsupported numeric relation: {relation}"
        if status == "OK" and expected and expected not in haystack:
            status, message = "ERROR", f"expected display is missing: {expected}"
        present_forbidden = [value for value in forbidden if value and value in haystack]
        if present_forbidden:
            status, message = "ERROR", f"forbidden display remains: {', '.join(present_forbidden)}"
        results.append({"status": status, "code": "numeric_claim", "claim_id": claim_id, "message": message})
    return results


def _slot_normalize(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum() or character == "%")


def _flatten_content_strings(value: Any, pointer: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(value, str) and value.strip():
        rows.append({"source_ref": f"source:{pointer or '/'}", "text": value})
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_flatten_content_strings(item, f"{pointer}/{index}"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"index", "role"}:
                continue
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            rows.extend(_flatten_content_strings(item, f"{pointer}/{escaped}"))
    return rows


def _structured_slide_rows(source: Any, plan_slide: int) -> list[dict[str, str]]:
    if not isinstance(source, dict) or not isinstance(source.get("slides"), list):
        return []
    selected = next(
        (
            slide for index, slide in enumerate(source["slides"], 1)
            if isinstance(slide, dict) and int(slide.get("index", index)) == plan_slide
        ),
        None,
    )
    if selected is None:
        return []
    source_index = source["slides"].index(selected)
    return _flatten_content_strings(selected, f"/slides/{source_index}")


def _json_pointer(root: Any, pointer: str) -> Any:
    if pointer == "":
        return root
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    current = root
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _source_ref_rows(
    refs: Any,
    source: Any,
    contract: dict[str, Any],
    plan_slide: int,
) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    units = {
        str(item.get("content_unit_id")): item
        for item in contract.get("content_units", [])
        if isinstance(item, dict) and item.get("content_unit_id")
    }
    if not isinstance(refs, list) or not refs:
        return [], ["source_refs must be a non-empty list"]
    for raw_ref in refs:
        ref = str(raw_ref or "")
        try:
            if ref.startswith("source:"):
                pointer = ref[len("source:"):]
                value = _json_pointer(source, pointer)
                if pointer.startswith("/slides/"):
                    parts = pointer.split("/")
                    source_slide = int(parts[2]) + 1
                    if source_slide != plan_slide:
                        errors.append(f"cross-slide source ref is not allowed: {ref}")
                        continue
                rows.extend(_flatten_content_strings(value, pointer))
            elif ref.startswith("contract:"):
                unit_id = ref[len("contract:"):]
                unit = units[unit_id]
                unit_slide = unit.get("plan_slide")
                if unit_slide is not None and int(unit_slide) != plan_slide:
                    errors.append(f"cross-slide contract unit is not allowed: {ref}")
                    continue
                text = str(unit.get("text") or "")
                if not text.strip():
                    raise KeyError(ref)
                rows.append({"source_ref": ref, "text": text})
            else:
                errors.append(f"unsupported source ref: {ref}")
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append(f"invalid source ref: {ref}")
    return rows, errors


def _unsupported_slot_segments(output: str, source_rows: list[dict[str, str]]) -> list[str]:
    candidates = [_slot_normalize(row.get("text")) for row in source_rows]
    candidates = [value for value in candidates if value]
    if not output.strip():
        return []

    def supported(piece: str) -> bool:
        compact = _slot_normalize(piece)
        return not compact or any(compact in candidate for candidate in candidates)

    unsupported: list[str] = []
    lines = [piece.strip(" \t-–—•●▪◦") for piece in re.split(r"[\r\n•●▪◦;；。!?！？()（）]+", output)]
    for line in (piece for piece in lines if piece):
        if supported(line):
            continue
        clauses = [piece.strip() for piece in re.split(r"[,，:：、·]+", line) if piece.strip()]
        failed = [piece for piece in clauses if not supported(piece)]
        unsupported.extend(failed or [line])
    return unsupported


def _check_content_slot_bindings(
    plan: dict[str, Any],
    source: Any,
    contract: dict[str, Any],
    keyed_dispositions: dict[tuple[int, str], dict[str, Any]],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    policy = contract.get("template_slot_policy") if isinstance(contract, dict) else None
    policy = policy if isinstance(policy, dict) else {}
    has_structured_slides = isinstance(source, dict) and isinstance(source.get("slides"), list)
    enforcement = str(policy.get("enforcement") or ("strict" if has_structured_slides else "warn"))
    if enforcement not in {"strict", "warn", "off"}:
        return [{"status": "ERROR", "code": "invalid_template_slot_policy", "enforcement": enforcement}]
    if enforcement == "off":
        return []
    failure_status = "ERROR" if enforcement == "strict" else "WARN"
    by_source_and_shape = {
        (int(obj.get("source_template_slide", 0)), int(obj.get("drawingml_id", 0))): obj
        for obj in objects
    }
    results: list[dict[str, Any]] = []
    for plan_slide, slide in enumerate(plan.get("slides", []), 1):
        source_slide = int(slide.get("source_slide", 0))
        default_rows = _structured_slide_rows(source, plan_slide)
        if not default_rows and isinstance(source, str) and source.strip():
            default_rows = [{"source_ref": "source:/", "text": source}]
        for replacement in slide.get("replacements", []):
            slot_id = str(replacement.get("slot_id") or "")
            match = re.fullmatch(r"s(\d+)_sh(\d+)", slot_id)
            if not match:
                continue
            obj = by_source_and_shape.get((source_slide, int(match.group(2))))
            if obj is None:
                continue
            disposition = keyed_dispositions.get((plan_slide, str(obj.get("source_object_id") or "")), {})
            if disposition.get("disposition") != "replace_content" or obj.get("object_type") not in {"shape", "equation"}:
                continue
            old_text = str(replacement.get("old_text") or obj.get("text") or "").strip()
            output = str(replacement.get("text") or "")
            if re.fullmatch(r"\d+\s*/\s*\d+", old_text) and re.fullmatch(r"\d+\s*/\s*\d+", output.strip()):
                expected = f"{plan_slide}/{len(plan.get('slides', []))}"
                status = "OK" if re.sub(r"\s+", "", output) == expected else failure_status
                results.append({
                    "status": status,
                    "code": "slot_system_page_number" if status == "OK" else "slot_system_page_number_mismatch",
                    "plan_slide": plan_slide,
                    "slot_id": slot_id,
                    "expected": expected,
                })
                continue
            if not output.strip():
                results.append({"status": "OK", "code": "slot_cleared", "plan_slide": plan_slide, "slot_id": slot_id})
                continue
            binding = replacement.get("content_binding")
            if isinstance(binding, dict):
                mode = str(binding.get("mode") or "")
                rows, ref_errors = _source_ref_rows(binding.get("source_refs"), source, contract, plan_slide)
                if ref_errors:
                    results.append({
                        "status": failure_status, "code": "slot_source_ref_invalid",
                        "plan_slide": plan_slide, "slot_id": slot_id, "details": ref_errors,
                    })
                    continue
                if mode == "user_confirmed_paraphrase":
                    if binding.get("user_confirmed") is True:
                        results.append({
                            "status": "WARN", "code": "slot_user_confirmed_paraphrase",
                            "plan_slide": plan_slide, "slot_id": slot_id,
                            "source_refs": [row["source_ref"] for row in rows],
                        })
                    else:
                        results.append({
                            "status": failure_status, "code": "slot_paraphrase_confirmation_required",
                            "plan_slide": plan_slide, "slot_id": slot_id,
                        })
                    continue
                if mode not in {"exact", "extractive"}:
                    results.append({
                        "status": failure_status, "code": "slot_binding_mode_invalid",
                        "plan_slide": plan_slide, "slot_id": slot_id, "mode": mode,
                    })
                    continue
                unsupported = _unsupported_slot_segments(output, rows)
                if mode == "exact" and len(rows) == 1 and _slot_normalize(output) != _slot_normalize(rows[0]["text"]):
                    unsupported = [output]
            else:
                rows = default_rows
                unsupported = _unsupported_slot_segments(output, rows)
            if not rows:
                results.append({
                    "status": failure_status, "code": "slot_source_context_missing",
                    "plan_slide": plan_slide, "slot_id": slot_id,
                })
            elif unsupported:
                results.append({
                    "status": failure_status, "code": "slot_copy_not_supported_by_source",
                    "plan_slide": plan_slide, "slot_id": slot_id,
                    "unsupported_segments": unsupported,
                    "suggested_route": "bind_source_or_request_user_confirmed_paraphrase",
                })
            else:
                results.append({
                    "status": "OK", "code": "slot_source_supported",
                    "plan_slide": plan_slide, "slot_id": slot_id,
                    "source_refs": [row["source_ref"] for row in rows],
                    "binding": "explicit" if isinstance(binding, dict) else "inferred_same_slide_extractive",
                })
    return results


def check_template_plan(run: Path, plan_path: Path) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    _template_path(run, manifest)
    profile_path = resolve_run_path(run, manifest["artifacts"].get("template_profile", "artifacts/template_profile.json"))
    library_path = resolve_run_path(run, manifest["artifacts"].get("template_library", "artifacts/template.slide_library.json"))
    if not profile_path.is_file() or not library_path.is_file():
        raise D6PPTError("Run template-analyze before template-check-plan", "template_profile_missing")
    profile = read_json(profile_path)
    library = read_json(library_path)
    plan = read_json(plan_path.resolve())
    source_path = resolve_run_path(run, str(manifest["input"]["copied_path"]))
    source_value: Any = ""
    if source_path.is_file():
        if source_path.suffix.lower() == ".json":
            source_value = read_json(source_path)
        else:
            source_value = source_path.read_text(encoding="utf-8", errors="replace")
    contract: dict[str, Any] = {}
    contract_record = manifest.get("content_contract")
    if isinstance(contract_record, dict) and contract_record.get("copied_path"):
        contract_path = resolve_run_path(run, str(contract_record["copied_path"]))
        if not contract_path.is_file() or sha256_file(contract_path) != contract_record.get("sha256"):
            raise D6PPTError("Content contract is stale", "stale_content_contract")
        contract = read_json(contract_path)
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise D6PPTError("Template plan must use schema_version 2.0", "schema_version_mismatch")
    if plan.get("template_sha256") != profile["pptx_sha256"] or plan.get("content_sha256") != manifest["input"]["sha256"]:
        raise D6PPTError("Template plan preconditions are stale", "stale_template_plan")
    _analyze, _apply, vendor_check_plan, _scaffold = _vendor_modules()
    vendor_report = vendor_check_plan(library, plan)
    results = list(vendor_report.get("results", []))
    object_by_id = {obj["source_object_id"]: obj for obj in profile["objects"]}
    dispositions = plan.get("object_dispositions")
    if not isinstance(dispositions, list):
        dispositions = []
    keyed: dict[tuple[int, str], dict[str, Any]] = {}
    for item in dispositions:
        key = (int(item.get("plan_slide", 0)), str(item.get("source_object_id") or ""))
        if key in keyed:
            results.append({"status": "ERROR", "code": "duplicate_disposition", "plan_slide": key[0], "source_object_id": key[1]})
        keyed[key] = item
        if item.get("disposition") not in DISPOSITIONS:
            results.append({"status": "ERROR", "code": "invalid_disposition", "plan_slide": key[0], "source_object_id": key[1]})
    for plan_slide, slide in enumerate(plan.get("slides", []), 1):
        source_slide = int(slide.get("source_slide", 0))
        replacements = {str(item.get("slot_id")): item for item in slide.get("replacements", [])}
        for obj in profile["objects"]:
            if obj["source_template_slide"] != source_slide:
                continue
            item = keyed.get((plan_slide, obj["source_object_id"]))
            if item is None:
                results.append({"status": "ERROR", "code": "object_disposition_missing", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"]})
                continue
            if item.get("disposition") == "manual_review":
                results.append({"status": "ERROR", "code": "manual_review_unresolved", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"]})
            disposition = item.get("disposition")
            slot_id = f"s{source_slide:02d}_sh{obj['drawingml_id']}"
            replacement = replacements.get(slot_id)
            if disposition in {"replace_content", "update_navigation"} and obj["object_type"] in {"shape", "equation"}:
                if replacement is None:
                    results.append({"status": "ERROR", "code": "disposition_action_missing", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"], "expected_slot_id": slot_id})
                elif disposition == "update_navigation" and str(replacement.get("text") or "").strip() == str(obj.get("text") or "").strip():
                    results.append({"status": "ERROR", "code": "navigation_not_updated", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"]})
            if disposition == "keep_design" and obj.get("role") in {"sample_content", "sample_formula_media"}:
                results.append({"status": "ERROR", "code": "sample_content_kept", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"]})
            if item.get("disposition") == "remove_sample" and obj["object_type"] == "picture" and item.get("user_confirmed") is not True:
                results.append({"status": "ERROR", "code": "semantic_picture_confirmation_required", "plan_slide": plan_slide, "source_object_id": obj["source_object_id"]})
    image_edits = plan.get("image_edits", [])
    validated_image_edits: list[dict[str, Any]] = []
    image_edit_keys: set[tuple[int, str]] = set()
    if not isinstance(image_edits, list):
        results.append({"status": "ERROR", "code": "invalid_image_edits"})
        image_edits = []
    frozen_assets = manifest.get("template_assets", {})
    if not isinstance(frozen_assets, dict):
        frozen_assets = {}
    for edit in image_edits:
        try:
            plan_slide = int(edit.get("plan_slide", 0))
        except (TypeError, ValueError):
            plan_slide = 0
        source_object_id = str(edit.get("source_object_id") or "")
        key = (plan_slide, source_object_id)
        if key in image_edit_keys:
            results.append({"status": "ERROR", "code": "duplicate_image_edit", "plan_slide": plan_slide, "source_object_id": source_object_id})
            continue
        image_edit_keys.add(key)
        obj = object_by_id.get(source_object_id)
        disposition = keyed.get(key)
        if plan_slide < 1 or plan_slide > len(plan.get("slides", [])) or obj is None:
            results.append({"status": "ERROR", "code": "image_edit_target_missing", "plan_slide": plan_slide, "source_object_id": source_object_id})
            continue
        selected_source_slide = int(plan["slides"][plan_slide - 1].get("source_slide", 0))
        if int(obj.get("source_template_slide", 0)) != selected_source_slide:
            results.append({"status": "ERROR", "code": "image_edit_source_slide_mismatch", "plan_slide": plan_slide, "source_object_id": source_object_id})
        if obj.get("object_type") != "picture":
            results.append({"status": "ERROR", "code": "image_edit_target_not_picture", "plan_slide": plan_slide, "source_object_id": source_object_id})
        if not disposition or disposition.get("disposition") != "replace_content":
            results.append({"status": "ERROR", "code": "image_edit_disposition_mismatch", "plan_slide": plan_slide, "source_object_id": source_object_id})
        if edit.get("user_confirmed") is not True:
            results.append({"status": "ERROR", "code": "semantic_picture_confirmation_required", "plan_slide": plan_slide, "source_object_id": source_object_id})
        try:
            _verify_disposition_fingerprint(obj, edit)
        except D6PPTError:
            results.append({"status": "ERROR", "code": "stale_template_disposition", "plan_slide": plan_slide, "source_object_id": source_object_id})
        asset_name = str(edit.get("asset_name") or "")
        asset_record = frozen_assets.get(asset_name)
        if not isinstance(asset_record, dict):
            results.append({"status": "ERROR", "code": "template_asset_not_imported", "plan_slide": plan_slide, "asset_name": asset_name})
            continue
        try:
            asset_path = resolve_run_path(run, str(asset_record.get("copied_path") or ""))
        except D6PPTError:
            results.append({"status": "ERROR", "code": "unsafe_template_asset_path", "plan_slide": plan_slide, "asset_name": asset_name})
            continue
        actual_asset_sha = sha256_file(asset_path) if asset_path.is_file() else None
        expected_asset_sha = str(edit.get("asset_sha256") or "")
        if actual_asset_sha is None or actual_asset_sha != asset_record.get("sha256") or actual_asset_sha != expected_asset_sha:
            results.append({"status": "ERROR", "code": "stale_template_asset", "plan_slide": plan_slide, "asset_name": asset_name})
            continue
        validated_image_edits.append({
            "plan_slide": plan_slide,
            "source_object_id": source_object_id,
            "asset_name": asset_name,
            "asset_path": rel_posix(asset_path, run),
            "asset_sha256": actual_asset_sha,
            "extension": asset_record.get("extension"),
            "content_type": asset_record.get("content_type"),
        })
    for key, disposition in keyed.items():
        obj = object_by_id.get(key[1])
        if obj and obj.get("object_type") == "picture" and disposition.get("disposition") == "replace_content" and key not in image_edit_keys:
            results.append({"status": "ERROR", "code": "image_edit_missing", "plan_slide": key[0], "source_object_id": key[1]})
    raw_navigation_targets = plan.get("navigation_targets", [])
    navigation_targets: dict[str, int] = {}
    if not isinstance(raw_navigation_targets, list):
        results.append({"status": "ERROR", "code": "invalid_navigation_targets"})
        raw_navigation_targets = []
    for target in raw_navigation_targets:
        label = str(target.get("label") or "").strip()
        try:
            target_plan_slide = int(target.get("target_plan_slide", 0))
        except (TypeError, ValueError):
            target_plan_slide = 0
        if not label or label in navigation_targets:
            results.append({"status": "ERROR", "code": "duplicate_or_empty_navigation_target", "label": label})
            continue
        if target_plan_slide < 1 or target_plan_slide > len(plan.get("slides", [])):
            results.append({"status": "ERROR", "code": "navigation_target_out_of_range", "label": label, "target_plan_slide": target_plan_slide})
            continue
        navigation_targets[label] = target_plan_slide
    raw_source_targets = plan.get("navigation_source_targets", [])
    navigation_source_targets: dict[int, int] = {}
    if not isinstance(raw_source_targets, list):
        results.append({"status": "ERROR", "code": "invalid_navigation_source_targets"})
        raw_source_targets = []
    for target in raw_source_targets:
        try:
            source_template_slide = int(target.get("source_template_slide", 0))
            target_plan_slide = int(target.get("target_plan_slide", 0))
        except (TypeError, ValueError):
            source_template_slide = target_plan_slide = 0
        if source_template_slide < 1 or source_template_slide in navigation_source_targets:
            results.append({"status": "ERROR", "code": "duplicate_or_invalid_navigation_source_target", "source_template_slide": source_template_slide})
            continue
        if target_plan_slide < 1 or target_plan_slide > len(plan.get("slides", [])):
            results.append({"status": "ERROR", "code": "navigation_target_out_of_range", "source_template_slide": source_template_slide, "target_plan_slide": target_plan_slide})
            continue
        navigation_source_targets[source_template_slide] = target_plan_slide
    validated_navigation_links: list[dict[str, Any]] = []
    for key, disposition in keyed.items():
        obj = object_by_id.get(key[1])
        if not obj:
            continue
        plan_slide = key[0]
        old_jump_targets = sorted(set(int(value) for value in (obj.get("slide_jump_source_slides") or [])))
        if not old_jump_targets:
            continue
        if len(old_jump_targets) != 1:
            results.append({
                "status": "ERROR", "code": "ambiguous_navigation_source_target",
                "plan_slide": plan_slide, "source_object_id": obj["source_object_id"],
                "old_source_targets": old_jump_targets,
            })
            continue
        old_source_target = old_jump_targets[0]
        target_plan_slide = navigation_source_targets.get(old_source_target)
        label = ""
        selected = plan.get("slides", [])[plan_slide - 1] if 1 <= plan_slide <= len(plan.get("slides", [])) else {}
        if disposition.get("disposition") == "update_navigation":
            slot_id = f"s{int(obj.get('source_template_slide', 0)):02d}_sh{obj.get('drawingml_id')}"
            replacement = next((item for item in selected.get("replacements", []) if str(item.get("slot_id")) == slot_id), None)
            label = str((replacement or {}).get("text") or "").strip()
            label_target = navigation_targets.get(label)
            if label_target is None:
                results.append({
                    "status": "ERROR", "code": "navigation_label_target_missing",
                    "plan_slide": plan_slide, "source_object_id": obj["source_object_id"], "label": label,
                })
                continue
            if target_plan_slide is not None and target_plan_slide != label_target:
                results.append({
                    "status": "ERROR", "code": "navigation_target_mapping_conflict",
                    "plan_slide": plan_slide, "source_object_id": obj["source_object_id"], "label": label,
                    "source_mapping": target_plan_slide, "label_mapping": label_target,
                })
                continue
            target_plan_slide = label_target
        if target_plan_slide is None:
            results.append({
                "status": "ERROR", "code": "navigation_link_target_missing",
                "plan_slide": plan_slide, "source_object_id": obj["source_object_id"],
                "old_source_target": old_source_target,
            })
            continue
        validated_navigation_links.append({
            "plan_slide": plan_slide,
            "source_object_id": obj["source_object_id"],
            "drawingml_id": obj["drawingml_id"],
            "label": label or f"source-slide-{old_source_target}",
            "old_source_targets": old_jump_targets,
            "target_plan_slide": target_plan_slide,
        })
    section_starts = sorted(set(navigation_targets.values()))
    for link in validated_navigation_links:
        plan_slide = int(link["plan_slide"])
        target_plan_slide = int(link["target_plan_slide"])
        active_candidates = [value for value in section_starts if value <= plan_slide]
        if target_plan_slide in section_starts and active_candidates:
            link["selection_state"] = "selected" if target_plan_slide == active_candidates[-1] else "unselected"
            link["active_target_plan_slide"] = active_candidates[-1]
    counts = Counter(int(slide.get("source_slide", 0)) for slide in plan.get("slides", []))
    for source_slide, count in sorted(counts.items()):
        if count > 2:
            results.append({"status": "WARN", "code": "template_slide_overuse", "source_slide": source_slide, "reuse_count": count})
    results.extend(_check_content_slot_bindings(plan, source_value, contract, keyed, profile["objects"]))
    results.extend(_check_numeric_claims(plan))
    summary = {
        "ok": sum(str(row.get("status")).upper() == "OK" for row in results),
        "warn": sum(str(row.get("status")).upper() == "WARN" for row in results),
        "error": sum(str(row.get("status")).upper() == "ERROR" for row in results),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "pass" if summary["error"] == 0 else "fail",
        "template_sha256": profile["pptx_sha256"],
        "content_sha256": manifest["input"]["sha256"],
        "plan_sha256": sha256_file(plan_path.resolve()),
        "summary": summary,
        "results": results,
        "validated_image_edits": validated_image_edits,
        "validated_navigation_links": validated_navigation_links,
        "vendor_summary": vendor_report.get("summary"),
    }
    report_path = run / "evidence" / "template_check_report.json"
    write_json(report_path, report)
    manifest["artifacts"].update({
        "template_plan": str(plan_path.resolve()),
        "template_check_report": rel_posix(report_path, run),
    })
    if summary["error"]:
        set_status(run, manifest, "repair_needed", "template_check_plan", summary)
    else:
        set_status(run, manifest, "authored", "template_check_plan", summary)
    return report


def _verify_disposition_fingerprint(obj: dict[str, Any], item: dict[str, Any]) -> None:
    expected = item.get("expected_fingerprint") or {}
    if expected.get("drawingml_id") != obj.get("drawingml_id") or expected.get("object_type") != obj.get("object_type"):
        raise D6PPTError("Template disposition fingerprint is stale", "stale_template_disposition")
    for key in ("text_sha256", "media_sha256"):
        if expected.get(key) != obj.get(key):
            raise D6PPTError("Template disposition fingerprint is stale", "stale_template_disposition")


def _xml_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _write_package(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(path, "r") as archive:
        corrupt = archive.testzip()
    if corrupt:
        raise D6PPTError(f"Package rewrite produced a corrupt PPTX part: {corrupt}", "invalid_pptx_package")


def _strip_confirmed_navigation_links(
    template: Path,
    destination: Path,
    profile: dict[str, Any],
    validated_links: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove only confirmed navigation jump actions from a disposable vendor input."""
    if not validated_links:
        shutil.copy2(template, destination)
        return [], {"added": [], "removed": [], "changed": []}
    objects = {obj["source_object_id"]: obj for obj in profile["objects"]}
    with zipfile.ZipFile(template, "r") as archive:
        entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
    receipts: list[dict[str, Any]] = []
    handled: set[str] = set()
    for link in validated_links:
        source_object_id = str(link["source_object_id"])
        if source_object_id in handled:
            continue
        handled.add(source_object_id)
        obj = objects.get(source_object_id)
        if not obj:
            raise D6PPTError("Confirmed navigation object disappeared", "stale_template_disposition")
        slide_part = str(obj["slide_part"])
        root = etree.fromstring(entries[slide_part])
        matches = []
        for element in root.xpath(".//p:sp | .//p:pic | .//p:graphicFrame | .//p:grpSp | .//p:cxnSp", namespaces=NS):
            cnv = _cnvpr(element)
            if cnv is not None and int(cnv.get("id") or 0) == int(obj["drawingml_id"]):
                matches.append(cnv)
        if len(matches) != 1:
            raise D6PPTError("Confirmed navigation address is not unique", "ambiguous_template_navigation_target")
        removed_ids: list[str] = []
        for click in list(matches[0].xpath("./a:hlinkClick[@action='ppaction://hlinksldjump']", namespaces=NS)):
            removed_ids.append(str(click.get(f"{{{RML}}}id") or ""))
            matches[0].remove(click)
        if not removed_ids:
            raise D6PPTError("Confirmed navigation jump disappeared before apply", "stale_template_disposition")
        entries[slide_part] = _xml_bytes(root)
        receipts.append({
            "source_object_id": source_object_id,
            "source_slide": obj["source_template_slide"],
            "drawingml_id": obj["drawingml_id"],
            "removed_relationship_ids": removed_ids,
        })
    _write_package(destination, entries)
    return receipts, compare_parts(template, destination)


def _inject_confirmed_navigation_links(
    output: Path,
    validated_links: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bind confirmed navigation labels to logical output section-start slides."""
    if not validated_links:
        return [], {"added": [], "removed": [], "changed": []}
    with tempfile.TemporaryDirectory(prefix="d6-navigation-links-", dir=output.parent) as temp_dir:
        before = Path(temp_dir) / "before.pptx"
        candidate = Path(temp_dir) / "candidate.pptx"
        shutil.copy2(output, before)
        with zipfile.ZipFile(output, "r") as archive:
            entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
        presentation = etree.fromstring(entries["ppt/presentation.xml"])
        presentation_rels = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])
        rel_targets = {
            str(rel.get("Id")): str(rel.get("Target"))
            for rel in presentation_rels.xpath("./pr:Relationship", namespaces=NS)
            if rel.get("Target") and rel.get("TargetMode") != "External"
        }
        ordered_ids = presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)
        slide_parts = [posixpath.normpath(posixpath.join("ppt", rel_targets[str(rel_id)])) for rel_id in ordered_ids]
        receipts: list[dict[str, Any]] = []
        for link in validated_links:
            plan_slide = int(link["plan_slide"])
            target_plan_slide = int(link["target_plan_slide"])
            if not (1 <= plan_slide <= len(slide_parts) and 1 <= target_plan_slide <= len(slide_parts)):
                raise D6PPTError("Confirmed navigation target is out of range", "stale_template_plan")
            slide_part = slide_parts[plan_slide - 1]
            target_part = slide_parts[target_plan_slide - 1]
            root = etree.fromstring(entries[slide_part])
            matches = []
            for element in root.xpath(".//p:sp | .//p:pic | .//p:graphicFrame | .//p:grpSp | .//p:cxnSp", namespaces=NS):
                cnv = _cnvpr(element)
                if cnv is not None and int(cnv.get("id") or 0) == int(link["drawingml_id"]):
                    matches.append(cnv)
            if len(matches) != 1:
                raise D6PPTError("Output navigation address is not unique", "ambiguous_template_navigation_target")
            for old_click in list(matches[0].xpath("./a:hlinkClick[@action='ppaction://hlinksldjump']", namespaces=NS)):
                matches[0].remove(old_click)
            rel_part = posixpath.join(posixpath.dirname(slide_part), "_rels", posixpath.basename(slide_part) + ".rels")
            rel_root = etree.fromstring(entries[rel_part])
            used = {
                str(rel.get("Id")) for rel in rel_root.xpath("./pr:Relationship", namespaces=NS)
                if rel.get("Id")
            }
            index = 1
            while f"rIdD6Nav{index}" in used:
                index += 1
            rel_id = f"rIdD6Nav{index}"
            etree.SubElement(rel_root, f"{{{PKG_REL}}}Relationship", {
                "Id": rel_id,
                "Type": SLIDE_REL_TYPE,
                "Target": posixpath.relpath(target_part, posixpath.dirname(slide_part)),
            })
            etree.SubElement(matches[0], f"{{{AML}}}hlinkClick", {
                f"{{{RML}}}id": rel_id,
                "action": SLIDE_JUMP_ACTION,
            })
            entries[slide_part] = _xml_bytes(root)
            entries[rel_part] = _xml_bytes(rel_root)
            receipts.append({
                "plan_slide": plan_slide,
                "source_object_id": link["source_object_id"],
                "drawingml_id": link["drawingml_id"],
                "label": link["label"],
                "target_plan_slide": target_plan_slide,
                "relationship_id": rel_id,
            })
        _write_package(candidate, entries)
        candidate.replace(output)
        package_diff = compare_parts(before, output)
    return receipts, package_diff


_FILL_TAGS = {
    f"{{{AML}}}noFill",
    f"{{{AML}}}solidFill",
    f"{{{AML}}}gradFill",
    f"{{{AML}}}blipFill",
    f"{{{AML}}}pattFill",
    f"{{{AML}}}grpFill",
}


def _first_navigation_fill(element: etree._Element, *, text_role: bool) -> etree._Element:
    if text_role:
        candidates = element.xpath(
            ".//p:txBody/a:p/a:r/a:rPr/*[self::a:noFill or self::a:solidFill or self::a:gradFill or self::a:pattFill]",
            namespaces=NS,
        )
    else:
        candidates = element.xpath(
            "./p:spPr/*[self::a:noFill or self::a:solidFill or self::a:gradFill or self::a:blipFill or self::a:pattFill or self::a:grpFill]",
            namespaces=NS,
        )
    if not candidates:
        raise D6PPTError("Navigation style has no explicit fill", "navigation_style_ambiguous")
    return candidates[0]


def _replace_navigation_fill(element: etree._Element, fill: etree._Element, *, text_role: bool) -> None:
    if text_role:
        owners = element.xpath(".//p:txBody/a:p/a:r/a:rPr | .//p:txBody/a:p/a:endParaRPr", namespaces=NS)
    else:
        owners = element.xpath("./p:spPr", namespaces=NS)
    if not owners:
        raise D6PPTError("Navigation style target has no fill owner", "navigation_style_ambiguous")
    for owner in owners:
        existing = [child for child in owner if child.tag in _FILL_TAGS]
        if not existing:
            raise D6PPTError("Navigation style target has no explicit fill", "navigation_style_ambiguous")
        position = owner.index(existing[0])
        for child in existing:
            owner.remove(child)
        owner.insert(position, deepcopy(fill))


def _apply_confirmed_navigation_states(
    output: Path,
    validated_links: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Move the template's unique selected style to the confirmed logical section."""
    styled_links = [link for link in validated_links if link.get("selection_state") in {"selected", "unselected"}]
    if not styled_links:
        return [], {"added": [], "removed": [], "changed": []}
    with tempfile.TemporaryDirectory(prefix="d6-navigation-state-", dir=output.parent) as temp_dir:
        before = Path(temp_dir) / "before.pptx"
        candidate = Path(temp_dir) / "candidate.pptx"
        shutil.copy2(output, before)
        with zipfile.ZipFile(output, "r") as archive:
            entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
        presentation = etree.fromstring(entries["ppt/presentation.xml"])
        presentation_rels = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])
        rel_targets = {
            str(rel.get("Id")): str(rel.get("Target"))
            for rel in presentation_rels.xpath("./pr:Relationship", namespaces=NS)
            if rel.get("Target") and rel.get("TargetMode") != "External"
        }
        ordered_ids = presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)
        slide_parts = [posixpath.normpath(posixpath.join("ppt", rel_targets[str(rel_id)])) for rel_id in ordered_ids]
        receipts: list[dict[str, Any]] = []
        by_slide: dict[int, list[dict[str, Any]]] = {}
        for link in styled_links:
            by_slide.setdefault(int(link["plan_slide"]), []).append(link)
        for plan_slide, links in sorted(by_slide.items()):
            slide_part = slide_parts[plan_slide - 1]
            root = etree.fromstring(entries[slide_part])
            role_rows: dict[str, list[tuple[dict[str, Any], etree._Element, etree._Element, bytes]]] = {"text": [], "shape": []}
            for link in links:
                matches = []
                for element in root.xpath(".//p:sp | .//p:pic | .//p:graphicFrame | .//p:grpSp | .//p:cxnSp", namespaces=NS):
                    cnv = _cnvpr(element)
                    if cnv is not None and int(cnv.get("id") or 0) == int(link["drawingml_id"]):
                        matches.append(element)
                if len(matches) != 1:
                    raise D6PPTError("Output navigation state address is not unique", "ambiguous_template_navigation_target")
                element = matches[0]
                text_role = bool(element.xpath(".//p:txBody//a:t[normalize-space(.)]", namespaces=NS))
                fill = _first_navigation_fill(element, text_role=text_role)
                role_rows["text" if text_role else "shape"].append((link, element, fill, etree.tostring(fill)))
            for role, rows in role_rows.items():
                if not rows:
                    continue
                counts = Counter(signature for _link, _element, _fill, signature in rows)
                selected_signatures = [signature for signature, count in counts.items() if count == 1]
                unselected_signatures = [signature for signature, count in counts.items() if count == max(counts.values())]
                if len(selected_signatures) != 1 or len(unselected_signatures) != 1 or selected_signatures[0] == unselected_signatures[0]:
                    raise D6PPTError(
                        f"Navigation {role} styles do not prove one selected and one repeated unselected state",
                        "navigation_style_ambiguous",
                    )
                selected_fill = next(fill for _link, _element, fill, signature in rows if signature == selected_signatures[0])
                unselected_fill = next(fill for _link, _element, fill, signature in rows if signature == unselected_signatures[0])
                for link, element, _fill, old_signature in rows:
                    wanted = selected_fill if link["selection_state"] == "selected" else unselected_fill
                    _replace_navigation_fill(element, wanted, text_role=(role == "text"))
                    receipts.append({
                        "plan_slide": plan_slide,
                        "drawingml_id": int(link["drawingml_id"]),
                        "source_object_id": link["source_object_id"],
                        "role": role,
                        "selection_state": link["selection_state"],
                        "active_target_plan_slide": int(link["active_target_plan_slide"]),
                        "target_plan_slide": int(link["target_plan_slide"]),
                        "style_changed": old_signature != etree.tostring(wanted),
                    })
            entries[slide_part] = _xml_bytes(root)
        _write_package(candidate, entries)
        candidate.replace(output)
        package_diff = compare_parts(before, output)
    return receipts, package_diff


def _replace_confirmed_images(
    output: Path,
    run: Path,
    profile: dict[str, Any],
    validated_edits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace only SHA-locked picture relationships in cloned output slides."""
    if not validated_edits:
        return [], {"added": [], "removed": [], "changed": []}
    objects = {obj["source_object_id"]: obj for obj in profile["objects"]}
    with tempfile.TemporaryDirectory(prefix="d6-image-replace-", dir=output.parent) as temp_dir:
        before = Path(temp_dir) / "before.pptx"
        candidate = Path(temp_dir) / "candidate.pptx"
        shutil.copy2(output, before)
        with zipfile.ZipFile(output, "r") as archive:
            entries = {info.filename: archive.read(info.filename) for info in archive.infolist() if not info.is_dir()}
            presentation = etree.fromstring(entries["ppt/presentation.xml"])
            presentation_rels = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])
            rel_targets = {
                str(rel.get("Id")): str(rel.get("Target"))
                for rel in presentation_rels.xpath("./pr:Relationship", namespaces=NS)
                if rel.get("Target") and rel.get("TargetMode") != "External"
            }
            ordered_ids = presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)
            slide_parts = [
                posixpath.normpath(posixpath.join("ppt", rel_targets[str(rel_id)]))
                for rel_id in ordered_ids
            ]
        receipts: list[dict[str, Any]] = []
        content_types = etree.fromstring(entries["[Content_Types].xml"])
        for edit in validated_edits:
            plan_slide = int(edit["plan_slide"])
            if plan_slide < 1 or plan_slide > len(slide_parts):
                raise D6PPTError("Confirmed image target slide disappeared", "stale_template_disposition")
            obj = objects.get(edit["source_object_id"])
            if not obj or obj.get("object_type") != "picture":
                raise D6PPTError("Confirmed image target disappeared", "stale_template_disposition")
            slide_part = slide_parts[plan_slide - 1]
            slide_root = etree.fromstring(entries[slide_part])
            pictures = []
            for picture in slide_root.xpath(".//p:pic", namespaces=NS):
                cnv = _cnvpr(picture)
                if cnv is not None and int(cnv.get("id") or 0) == int(obj["drawingml_id"]):
                    pictures.append(picture)
            if len(pictures) != 1:
                raise D6PPTError("Confirmed picture address is not unique", "ambiguous_template_picture_target")
            embeds = pictures[0].xpath("./p:blipFill/a:blip/@r:embed", namespaces=NS)
            if len(embeds) != 1:
                raise D6PPTError("Confirmed picture has no unique media relationship", "ambiguous_template_picture_target")
            rel_id = str(embeds[0])
            rel_part = posixpath.join(posixpath.dirname(slide_part), "_rels", posixpath.basename(slide_part) + ".rels")
            rel_root = etree.fromstring(entries[rel_part])
            relationships = rel_root.xpath(f"./pr:Relationship[@Id='{rel_id}']", namespaces=NS)
            if len(relationships) != 1 or not str(relationships[0].get("Type") or "").endswith("/image"):
                raise D6PPTError("Confirmed picture relationship is not a unique image", "ambiguous_template_picture_target")
            old_target = str(relationships[0].get("Target") or "")
            old_part = posixpath.normpath(posixpath.join(posixpath.dirname(slide_part), old_target))
            if old_part not in entries or hashlib.sha256(entries[old_part]).hexdigest() != obj.get("media_sha256"):
                raise D6PPTError("Confirmed picture media changed before replacement", "stale_template_disposition")
            asset_path = resolve_run_path(run, edit["asset_path"])
            asset_bytes = asset_path.read_bytes()
            if hashlib.sha256(asset_bytes).hexdigest() != edit["asset_sha256"]:
                raise D6PPTError("Confirmed replacement image changed before apply", "stale_template_asset")
            extension = str(edit["extension"])
            new_part = f"ppt/media/d6_template_slide_{plan_slide:02d}_{edit['asset_sha256'][:16]}.{extension}"
            if new_part in entries and entries[new_part] != asset_bytes:
                raise D6PPTError("Replacement image package part collision", "template_asset_part_collision")
            entries[new_part] = asset_bytes
            relationships[0].set("Target", posixpath.relpath(new_part, posixpath.dirname(slide_part)))
            entries[rel_part] = _xml_bytes(rel_root)
            default_rows = content_types.xpath(
                f"./ct:Default[translate(@Extension, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='{extension}']",
                namespaces={"ct": CTML},
            )
            if not default_rows:
                etree.SubElement(content_types, f"{{{CTML}}}Default", Extension=extension, ContentType=str(edit["content_type"]))
            receipts.append({
                "plan_slide": plan_slide,
                "source_object_id": obj["source_object_id"],
                "drawingml_id": obj["drawingml_id"],
                "slide_part": slide_part,
                "relationship_id": rel_id,
                "old_media_part": old_part,
                "old_media_sha256": obj.get("media_sha256"),
                "new_media_part": new_part,
                "new_media_sha256": edit["asset_sha256"],
            })
        entries["[Content_Types].xml"] = _xml_bytes(content_types)
        _write_package(candidate, entries)
        candidate.replace(output)
        package_diff = compare_parts(before, output)
    return receipts, package_diff


def apply_template_plan(run: Path, plan_path: Path, runtime_dir: Path | None = None) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    template = _template_path(run, manifest)
    plan = read_json(plan_path.resolve())
    if plan.get("status") != "confirmed":
        raise D6PPTError("Template plan requires explicit status=confirmed", "template_plan_confirmation_required")
    report = check_template_plan(run, plan_path)
    if report["summary"]["error"]:
        raise D6PPTError("Template plan has unresolved errors", "template_plan_invalid", report["summary"])
    profile = read_json(run / "artifacts" / "template_profile.json")
    object_by_id = {obj["source_object_id"]: obj for obj in profile["objects"]}
    _analyze, vendor_apply_plan, _check, _scaffold = _vendor_modules()
    output = run / "artifacts" / "template-filled.pptx"
    if output.exists():
        raise D6PPTError("Template output already exists; create a new run", "artifact_exists")
    with tempfile.TemporaryDirectory(prefix="d6-vendor-template-", dir=run / "artifacts") as temp_dir:
        vendor_template = Path(temp_dir) / "template-with-confirmed-navigation-unlinked.pptx"
        stripped_navigation, navigation_input_diff = _strip_confirmed_navigation_links(
            template,
            vendor_template,
            profile,
            report.get("validated_navigation_links", []),
        )
        vendor_apply_plan(vendor_template, plan, output, transition="keep", transition_duration=0.5)
    # Vendor text fill can append a:r after an existing endParaRPr; normalize schema order.
    _normalize_txbody_paragraph_order(output)
    try:
        navigation_links, navigation_output_diff = _inject_confirmed_navigation_links(
            output,
            report.get("validated_navigation_links", []),
        )
        navigation_states, navigation_state_diff = _apply_confirmed_navigation_states(
            output,
            report.get("validated_navigation_links", []),
        )
        image_replacements, image_package_diff = _replace_confirmed_images(
            output,
            run,
            profile,
            report.get("validated_image_edits", []),
        )
    except Exception:
        # Incomplete vendor output must not block a clean retry in this run.
        output.unlink(missing_ok=True)
        raise
    client = OfficeCLI(runtime_dir, run / "logs")
    removals = []
    for item in plan.get("object_dispositions", []):
        if item.get("disposition") != "remove_sample":
            continue
        obj = object_by_id.get(item.get("source_object_id"))
        if obj is None:
            raise D6PPTError("Template object disappeared from profile", "stale_template_disposition")
        _verify_disposition_fingerprint(obj, item)
        if obj["object_type"] == "picture" and item.get("user_confirmed") is not True:
            raise D6PPTError("Semantic picture removal requires user confirmation", "semantic_picture_confirmation_required")
        path = f"/slide[{int(item['plan_slide'])}]/{obj['officecli_element']}[@id={obj['drawingml_id']}]"
        before = client.run(["get", str(output), path])
        if obj["text"]:
            data = before.get("data", {})
            if isinstance(data, dict) and isinstance(data.get("results"), list) and len(data["results"]) == 1:
                data = data["results"][0]
            observed = str((data or {}).get("text") or "") if isinstance(data, dict) else ""
            if observed.strip() != obj["text"].strip():
                raise D6PPTError("Sample object text changed before removal", "stale_template_disposition")
        result = client.remove(output, path)
        removals.append({"source_object_id": obj["source_object_id"], "output_path": path, "officecli_result": result.get("data")})
    client.save(output)
    client.close(output)
    validation = client.validate(output)
    output_sha = sha256_file(output)
    output_profile = build_pptx_profile(output)
    source_objects = {
        (int(obj["source_template_slide"]), int(obj["drawingml_id"])): obj["source_object_id"]
        for obj in profile["objects"]
    }
    source_slides = {
        index: int(slide["source_slide"]) for index, slide in enumerate(plan.get("slides", []), 1)
    }
    for obj in output_profile["objects"]:
        source_slide = source_slides.get(int(obj["source_template_slide"]))
        obj["origin_source_object_id"] = source_objects.get((source_slide, int(obj["drawingml_id"]))) if source_slide else None
    output_profile.update({
        "template_sha256": sha256_file(template),
        "content_sha256": manifest["input"]["sha256"],
        "output_pptx_sha256": output_sha,
    })
    output_profile_path = run / "artifacts" / "output_profile.json"
    write_json(output_profile_path, output_profile)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "pass",
        "template_sha256": sha256_file(template),
        "content_sha256": manifest["input"]["sha256"],
        "plan_sha256": sha256_file(plan_path.resolve()),
        "output": rel_posix(output, run),
        "output_sha256": output_sha,
        "removed_sample_objects": removals,
        "stripped_source_navigation_objects": stripped_navigation,
        "navigation_vendor_input_package_diff": navigation_input_diff,
        "updated_navigation_links": navigation_links,
        "navigation_output_package_diff": navigation_output_diff,
        "updated_navigation_states": navigation_states,
        "navigation_state_package_diff": navigation_state_diff,
        "replaced_picture_objects": image_replacements,
        "image_replacement_package_diff": image_package_diff,
        "officecli_validate": {key: value for key, value in validation.items() if key != "_receipt"},
    }
    receipt_path = run / "evidence" / "template_apply_receipt.json"
    write_json(receipt_path, receipt)
    manifest["artifacts"].update({
        "current_pptx": rel_posix(output, run),
        "pptx_sha256": output_sha,
        "template_plan": str(plan_path.resolve()),
        "template_apply_receipt": rel_posix(receipt_path, run),
        "output_profile": rel_posix(output_profile_path, run),
    })
    manifest["unreplayed_patches"] = []
    for stale in (run / "review" / "visual_review.json", run / "review" / "visual_review_waiver.json"):
        stale.unlink(missing_ok=True)
    set_status(run, manifest, "compiled", "template_apply", {
        "removed_sample_count": len(removals),
        "replaced_picture_count": len(image_replacements),
    })
    return receipt
