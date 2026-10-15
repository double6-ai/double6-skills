"""Normalize Double6 native chart/table markers for PPT Master v6.7.0.

Double6's authoring contract (unchanged since 0.2) treats the JSON metadata of a
``data-pptx-replace-with`` marker as the data authority and the SVG children as
an optional preview. PPT Master v6 makes that explicit: such markers must be
``data-pptx-native-authority="json"`` (JSON-first, bounds required in metadata),
otherwise they are SVG-first and need a synchronized fallback hash plus full
fallback/payload parity. Tables additionally moved to the
``ppt-master.semantic-table.v2`` schema whose unset colours mean ``noFill``.

This adapter runs only on the build copy. It never edits authoring sources.
"""
from __future__ import annotations

import json
import re
from typing import Any

from lxml import etree

from .common import D6PPTError

SVG_NS = "http://www.w3.org/2000/svg"
TABLE_SCHEMA_V2 = "ppt-master.semantic-table.v2"
# PPT Master v4.8.0 table defaults (scripts/svg_to_pptx/native_objects/table.py),
# applied so legacy payloads keep their look under v2 where unset means noFill.
V48_TABLE_STYLE_DEFAULTS = {
    "header_fill": "#1F4E79",
    "header_text": "#FFFFFF",
    "body_fill": "#FFFFFF",
    "body_text": "#1F2937",
    "band_fill": "#F3F6FA",
    "band_row": True,
    "font_size": 18,
}
AUTHORITY_ATTR = "data-pptx-native-authority"
BASELINE_ATTR = "data-pptx-fallback-sha256"


def _metadata_child(group: etree._Element) -> etree._Element | None:
    for child in group:
        if isinstance(child.tag, str) and etree.QName(child).localname == "metadata":
            return child
    return None


def _bounds(group: etree._Element) -> list[float] | None:
    raw = group.get("data-pptx-bounds")
    if raw:
        parts = re.split(r"[\s,]+", raw.strip())
        if len(parts) == 4:
            try:
                return [float(p) for p in parts]
            except ValueError:
                return None
    keys = ["data-pptx-x", "data-pptx-y", "data-pptx-width", "data-pptx-height"]
    if all(group.get(k) for k in keys):
        try:
            return [float(group.get(k)) for k in keys]
        except ValueError:
            return None
    return None


HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
OFFICE_DEFAULT_SERIES = ("#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47")


def parse_spec_lock_palette(text: str) -> dict[str, Any]:
    """Read ``## colors`` from spec_lock.md: ``- role: #RRGGBB`` and ``- chart_series: #.., #..``."""
    palette: dict[str, Any] = {}
    in_colors = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_colors = stripped[3:].strip().lower() == "colors"
            continue
        if not in_colors or not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        colors = [c.upper() for c in HEX.findall(value)]
        if not colors:
            continue
        palette[key.strip()] = colors if key.strip() == "chart_series" else colors[0]
    if "chart_series" not in palette:
        series = [palette[k] for k in ("accent", "primary") if k in palette]
        if series:
            palette["chart_series"] = series + [c for c in (palette.get("muted"), palette.get("line")) if c]
    return palette


def apply_chart_palette(payload: dict[str, Any], palette: dict[str, Any]) -> list[str]:
    """Give a chart the deck palette when the author left colours unset."""
    series_colors = palette.get("chart_series") or []
    if not series_colors:
        return []
    actions: list[str] = []
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    if not style.get("colors") and not payload.get("colors"):
        style["colors"] = list(series_colors)
        actions.append("deck_palette_series_colors")
    for key, role in (("text_color", "text"), ("axis_color", "line"), ("grid_color", "line")):
        if key not in style and palette.get(role):
            style[key] = palette[role]
            actions.append(f"deck_palette_{key}")
    payload["style"] = style
    return actions


def apply_table_palette(payload: dict[str, Any], palette: dict[str, Any]) -> list[str]:
    if not palette.get("primary"):
        return []
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    defaults = {
        "header_fill": palette.get("primary"), "header_text": "#FFFFFF",
        "body_text": palette.get("text"), "body_fill": palette.get("bg") or "#FFFFFF",
        "band_fill": palette.get("surface") or palette.get("tint"), "border_color": palette.get("line"),
    }
    added = []
    for key, value in defaults.items():
        if value and key not in style:
            style[key] = value
            added.append(key)
    payload["style"] = style
    return ["deck_palette_table:" + ",".join(added)] if added else []


def upgrade_table_payload(payload: dict[str, Any], palette: dict[str, Any] | None = None) -> list[str]:
    """Upgrade a legacy (v4.8, schema-less) table payload in place."""
    actions: list[str] = []
    if palette:
        actions += apply_table_palette(payload, palette)
    if "schema" in payload:
        return actions
    payload["schema"] = TABLE_SCHEMA_V2
    actions.append("table_schema_v2")
    style = payload.get("style")
    if not isinstance(style, dict):
        style = {}
    added = []
    for key, value in V48_TABLE_STYLE_DEFAULTS.items():
        if key == "header_fill" and not payload.get("columns") and not payload.get("header_rows"):
            continue
        if key not in style:
            style[key] = value
            added.append(key)
    if "header_font_size" not in style and "font_size" in style:
        style["header_font_size"] = style["font_size"]
        added.append("header_font_size")
    payload["style"] = style
    if added:
        actions.append("v48_style_defaults:" + ",".join(added))
    return actions


def normalize_native_markers(root: etree._Element, *, authority_policy: str = "json", palette: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return one record per marker changed. ``authority_policy``: ``json`` | ``author``."""
    if authority_policy not in {"json", "author"}:
        raise D6PPTError(f"Unknown native marker authority policy: {authority_policy}", "invalid_semantic_manifest")
    records: list[dict[str, Any]] = []
    for group in root.iter(f"{{{SVG_NS}}}g"):
        kind = group.get("data-pptx-replace-with")
        if kind not in {"chart", "table"}:
            continue
        label = group.get("id") or group.get("data-pptx-shape-id") or "?"
        meta_el = _metadata_child(group)
        raw = meta_el.text if meta_el is not None else group.get("data-pptx-json")
        if not raw or not raw.strip():
            raise D6PPTError(f"Native {kind} marker #{label} has no JSON metadata", "native_marker_invalid")
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise D6PPTError(f"Native {kind} marker #{label} metadata is not valid JSON: {exc}", "native_marker_invalid") from exc
        if not isinstance(payload, dict):
            raise D6PPTError(f"Native {kind} marker #{label} metadata must be a JSON object", "native_marker_invalid")
        actions: list[str] = []
        if kind == "table":
            actions += upgrade_table_payload(payload, palette)
        elif palette:
            actions += apply_chart_palette(payload, palette)
        if authority_policy == "json" and group.get(AUTHORITY_ATTR) is None and group.get(BASELINE_ATTR) is None:
            group.set(AUTHORITY_ATTR, "json")
            actions.append("json_first_authority")
        if group.get(AUTHORITY_ATTR) == "json":
            missing = [k for k in ("x", "y", "width", "height") if k not in payload]
            if missing:
                bounds = _bounds(group)
                if bounds is None:
                    raise D6PPTError(
                        f"Native {kind} marker #{label}: JSON-first markers need x/y/width/height in metadata or data-pptx-bounds",
                        "native_marker_invalid",
                    )
                for key, value in zip(("x", "y", "width", "height"), bounds):
                    payload.setdefault(key, value)
                actions.append("bounds_from_data_pptx_bounds")
        if not actions:
            continue
        text = json.dumps(payload, ensure_ascii=False)
        if meta_el is None:
            meta_el = etree.SubElement(group, f"{{{SVG_NS}}}metadata")
            group.remove(meta_el)
            group.insert(0, meta_el)
            meta_el.set("type", "application/json")
            if "data-pptx-json" in group.attrib:
                del group.attrib["data-pptx-json"]
                actions.append("metadata_attribute_to_child")
        meta_el.text = text
        records.append({"id": label, "kind": kind, "shape_id": group.get("data-pptx-shape-id"), "actions": actions})
    return records
