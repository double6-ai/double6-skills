from __future__ import annotations

from pathlib import Path
from typing import Any

import re

from .common import D6PPTError, LEGACY_SCHEMA_VERSIONS, SCHEMA_VERSION, sha256_file


ROLES = {
    "title", "subtitle", "body", "caption", "label", "data", "chart",
    "table", "connector", "group_motif", "decorative", "notes", "footnote", "page_mark",
}
PREFERRED_STRUCTURES = {"top_level", "group", "connector", "placeholder", "native_chart", "native_table"}
PATCH_PROPERTIES = {"text", "color", "fill", "font", "size", "x", "y", "width", "height"}
PATCH_OPERATIONS = {"set_property", "remove_leaf"}
LEAF_OBJECT_TYPES = {"shape", "textbox", "equation", "connector", "picture"}


def require_schema(data: dict[str, Any], name: str) -> None:
    if data.get("schema_version") not in {SCHEMA_VERSION, *LEGACY_SCHEMA_VERSIONS}:
        raise D6PPTError(
            f"{name}.schema_version must be {SCHEMA_VERSION} or a supported legacy version",
            "schema_version_mismatch",
        )


def validate_semantic_manifest(data: dict[str, Any], source_root: Path | None = None) -> None:
    require_schema(data, "semantic_manifest")
    objects = data.get("objects")
    if not isinstance(objects, list) or not objects:
        raise D6PPTError("semantic_manifest.objects must be a non-empty list", "invalid_semantic_manifest")
    seen: set[str] = set()
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise D6PPTError(f"objects[{index}] must be an object", "invalid_semantic_manifest")
        source_id = obj.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip() or source_id in seen:
            raise D6PPTError(f"objects[{index}].source_id is missing or duplicated", "invalid_semantic_manifest")
        seen.add(source_id)
        if not isinstance(obj.get("slide"), int) or obj["slide"] < 1:
            raise D6PPTError(f"{source_id}: slide must be a positive integer", "invalid_semantic_manifest")
        if obj.get("role") not in ROLES:
            raise D6PPTError(f"{source_id}: unsupported role", "invalid_semantic_manifest")
        if not isinstance(obj.get("editable"), bool) or not isinstance(obj.get("postflight_sensitive"), bool):
            raise D6PPTError(f"{source_id}: editable and postflight_sensitive must be booleans", "invalid_semantic_manifest")
        if obj.get("preferred_structure") not in PREFERRED_STRUCTURES:
            raise D6PPTError(f"{source_id}: unsupported preferred_structure", "invalid_semantic_manifest")
        selector = obj.get("source_selector")
        if not isinstance(selector, dict) or not selector:
            raise D6PPTError(f"{source_id}: source_selector is required", "invalid_semantic_manifest")
        match = obj.get("match")
        if not isinstance(match, dict):
            raise D6PPTError(f"{source_id}: match is required", "invalid_semantic_manifest")
        methods = [k for k in ("drawingml_id", "drawingml_name", "text", "connector_ordinal", "group_contains") if match.get(k) is not None]
        if len(methods) != 1:
            raise D6PPTError(f"{source_id}: match must select exactly one primary method", "invalid_semantic_manifest")
        if methods[0] == "drawingml_id" and (
            not isinstance(match.get("drawingml_id"), int) or not 2 <= match["drawingml_id"] <= 4294967295
        ):
            raise D6PPTError(
                f"{source_id}: drawingml_id must be an integer from 2 to 4294967295",
                "invalid_semantic_manifest",
            )
        if methods[0] == "text" and match.get("ordinal") is None and match.get("source_selector") is None:
            raise D6PPTError(
                f"{source_id}: text cannot be the sole identity; add ordinal or match.source_selector",
                "ambiguous_text_identity",
            )
    if source_root is not None:
        for entry in data.get("source_files", []):
            path = source_root / entry["path"]
            if not path.is_file() or sha256_file(path) != entry.get("sha256"):
                raise D6PPTError(f"Source file is missing or stale: {entry.get('path')}", "stale_source")


def validate_object_map(data: dict[str, Any], pptx: Path, semantic_manifest: Path | None = None) -> None:
    require_schema(data, "object_path_map")
    if data.get("pptx_sha256") != sha256_file(pptx):
        raise D6PPTError("Object map is stale for current PPTX", "stale_object_map")
    if semantic_manifest is not None and data.get("semantic_manifest_sha256") != sha256_file(semantic_manifest):
        raise D6PPTError("Object map is stale for semantic manifest", "stale_object_map")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for obj in data.get("objects", []):
        source_id = obj.get("source_id")
        address = obj.get("officecli_path")
        if not source_id or source_id in seen_ids or not address or address in seen_paths:
            raise D6PPTError("Object map contains a missing or non-unique identity", "ambiguous_object_map")
        seen_ids.add(source_id)
        seen_paths.add(address)


def validate_patch_spec(data: dict[str, Any]) -> None:
    require_schema(data, "patch_spec")
    patches = data.get("patches")
    if not isinstance(patches, list) or not patches:
        raise D6PPTError("patches must be a non-empty list", "invalid_patch_spec")
    legacy = data.get("schema_version") in LEGACY_SCHEMA_VERSIONS
    for patch in patches:
        operation = patch.get("operation", "set_property")
        if operation not in PATCH_OPERATIONS:
            raise D6PPTError(f"Patch operation not allowed: {operation}", "patch_operation_forbidden")
        if not patch.get("source_id") and not patch.get("officecli_path"):
            raise D6PPTError("Patch requires source_id or officecli_path", "invalid_patch_spec")
        if operation == "set_property":
            if patch.get("property") not in PATCH_PROPERTIES:
                raise D6PPTError(f"Patch property not allowed: {patch.get('property')}", "patch_property_forbidden")
            if "value" not in patch:
                raise D6PPTError("Patch value is required", "invalid_patch_spec")
        if legacy:
            continue
        if not patch.get("finding_id"):
            raise D6PPTError("Schema 2.0 patches require finding_id", "patch_finding_required")
        if not patch.get("source_template_object_id"):
            raise D6PPTError("Schema 2.0 patches require source_template_object_id", "patch_source_identity_required")
        if not isinstance(patch.get("reason"), str) or not patch["reason"].strip():
            raise D6PPTError("Schema 2.0 patches require a repair reason", "patch_reason_required")
        fingerprint = patch.get("expected_fingerprint")
        if not isinstance(fingerprint, dict):
            raise D6PPTError("Schema 2.0 patches require expected_fingerprint", "patch_fingerprint_required")
        if not isinstance(fingerprint.get("drawingml_id"), int) or fingerprint.get("object_type") not in LEAF_OBJECT_TYPES:
            raise D6PPTError("Patch fingerprint requires a leaf object type and DrawingML id", "invalid_patch_fingerprint")
        path = str(patch.get("officecli_path") or "")
        leaf_path = r"/slide\[\d+\](?:/group\[@id=\d+\])*/(?:shape|textbox|equation|connector|picture)\[@id=\d+\]"
        if path and not re.fullmatch(leaf_path, path):
            raise D6PPTError("Schema 2.0 patches require a stable leaf OfficeCLI path", "unsafe_patch_target")
        if operation == "remove_leaf" and fingerprint.get("object_type") == "picture" and not (
            data.get("user_confirmed") is True or patch.get("user_confirmed") is True
        ):
            raise D6PPTError("Semantic picture removal requires user confirmation", "semantic_picture_confirmation_required")
