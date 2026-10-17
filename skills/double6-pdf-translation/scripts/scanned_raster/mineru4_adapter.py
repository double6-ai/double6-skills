"""Lazy MinerU 4.0.4 adapter with a stable project-side region contract."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .constants import (
    MINERU_MIDDLE_SCHEMA,
    MINERU_MIDDLE_SCHEMA_VERSION,
    MINERU_VERSION,
    SCHEMA_VERSION,
    SKILL_VERSION,
)
from .mineru4_runtime import doctor, runtime_env


class MinerUUnavailableError(RuntimeError):
    """Raised when the pinned runtime or its explicitly prepared models are absent."""


class MinerUSchemaError(ValueError):
    """Raised when MinerU output cannot be consumed without guessing."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return re.sub(r"<[^>]+>", " ", value).strip()
    if isinstance(value, list):
        return " ".join(filter(None, (_text_from_content(item) for item in value))).strip()
    if isinstance(value, dict):
        direct = value.get("content")
        if direct is not None:
            return _text_from_content(direct)
        for key in ("text", "value", "latex"):
            if isinstance(value.get(key), str):
                return str(value[key]).strip()
    return ""


def _asset_refs(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "image_path" and isinstance(item, str) and item:
                found.append(item)
            else:
                found.extend(_asset_refs(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_asset_refs(item))
    return sorted(set(found))


def _page_dimensions(payload: dict[str, Any], input_pdf: Path) -> dict[int, tuple[float, float]]:
    dimensions: dict[int, tuple[float, float]] = {}
    layout = (payload.get("extensions") or {}).get("docvortex_layout") or {}
    for page in layout.get("pages") or []:
        if not isinstance(page, dict):
            continue
        index = page.get("page_idx")
        width = page.get("width_pt")
        height = page.get("height_pt")
        if isinstance(index, int) and isinstance(width, (int, float)) and isinstance(height, (int, float)):
            dimensions[index] = (float(width), float(height))
    try:
        import fitz

        document = fitz.open(input_pdf)
        try:
            for index, page in enumerate(document):
                dimensions.setdefault(index, (float(page.rect.width), float(page.rect.height)))
        finally:
            document.close()
    except Exception:
        pass
    return dimensions


def _absolute_bbox(raw: Any, dimensions: tuple[float, float] | None) -> list[float]:
    if not isinstance(raw, list) or len(raw) != 4 or not all(isinstance(v, (int, float)) for v in raw):
        raise MinerUSchemaError("MinerU block bbox is missing or invalid")
    bbox = [float(value) for value in raw]
    if dimensions and max(abs(value) for value in bbox) <= 1.5:
        width, height = dimensions
        bbox = [bbox[0] * width, bbox[1] * height, bbox[2] * width, bbox[3] * height]
    x0, y0, x1, y1 = bbox
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _polygon_from_bbox(bbox: list[float]) -> list[list[float]]:
    x0, y0, x1, y1 = bbox
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _confidence(block: dict[str, Any]) -> tuple[float | None, str]:
    for key in ("confidence", "score", "probability"):
        value = block.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value))), f"mineru_block.{key}"
    return None, "mineru_not_provided"


def validate_middle_json(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != MINERU_MIDDLE_SCHEMA:
        errors.append(f"schema must be {MINERU_MIDDLE_SCHEMA}")
    if payload.get("schema_version") != MINERU_MIDDLE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {MINERU_MIDDLE_SCHEMA_VERSION}")
    metadata = payload.get("metadata")
    producer = metadata.get("producer") if isinstance(metadata, dict) else None
    if not isinstance(producer, dict) or producer.get("name") != "mineru":
        errors.append("metadata.producer.name must be mineru")
    if not isinstance(payload.get("pages"), list):
        errors.append("pages must be a list")
    if not isinstance(payload.get("is_full_document"), bool):
        errors.append("is_full_document must be boolean")
    return errors


def _load_saved_middle_json(raw_dir: Path) -> dict[str, Any]:
    """Load the canonical MiddleJSON produced by the writer.

    MinerU may add asset paths while ``result.save()`` writes images and JSON.
    Normalizing ``result.to_dict()`` directly can therefore lose those paths and
    make a complete image block look as if its required asset were missing.
    """
    direct = raw_dir / "middle_json.json"
    candidates = [direct] if direct.is_file() else sorted(raw_dir.rglob("middle_json.json"))
    if len(candidates) != 1:
        raise MinerUSchemaError(
            f"expected exactly one saved middle_json.json under {raw_dir}, found {len(candidates)}"
        )
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinerUSchemaError(f"cannot read saved MiddleJSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MinerUSchemaError("saved MiddleJSON root must be an object")
    return payload


def normalize_middle_json(
    payload: dict[str, Any],
    *,
    input_pdf: Path,
    tier: str,
    runtime: str,
    page_image_hashes: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors = validate_middle_json(payload)
    if errors:
        raise MinerUSchemaError("; ".join(errors))
    source_sha = sha256_file(input_pdf)
    dimensions = _page_dimensions(payload, input_pdf)
    config_sha = hashlib.sha256(
        json.dumps(
            {"engine": "mineru", "version": MINERU_VERSION, "tier": tier, "runtime": runtime, "ocr_mode": "ocr"},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    producer = payload["metadata"]["producer"]
    producer_version = str(producer.get("version") or "unknown")
    warnings: list[str] = []
    if producer_version != MINERU_VERSION:
        warnings.append(f"producer_version_mismatch:{producer_version}")
    extensions = payload.get("extensions") or {}
    mineru_extension = extensions.get("mineru") if isinstance(extensions, dict) else {}
    extension_tier = mineru_extension.get("tier") if isinstance(mineru_extension, dict) else None
    if extension_tier and extension_tier != tier:
        warnings.append(f"tier_mismatch:{extension_tier}")

    regions: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for page in payload["pages"]:
        if not isinstance(page, dict) or not isinstance(page.get("page_idx"), int):
            raise MinerUSchemaError("every MinerU page must have an integer page_idx")
        source_page_idx = int(page["page_idx"])
        if source_page_idx < 0 or source_page_idx in seen_pages:
            raise MinerUSchemaError("MinerU page_idx values must be unique non-negative integers")
        seen_pages.add(source_page_idx)
        page_number = source_page_idx + 1
        blocks = page.get("blocks") or []
        if not isinstance(blocks, list):
            raise MinerUSchemaError(f"page {source_page_idx} blocks must be a list")
        for order, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            text = _text_from_content(block.get("content"))
            role = str(block.get("type") or "unknown")
            if not text and role not in {"table", "formula", "image", "chart"}:
                continue
            bbox = _absolute_bbox(block.get("bbox"), dimensions.get(source_page_idx))
            page_width, page_height = dimensions.get(source_page_idx, (0.0, 0.0))
            confidence, confidence_source = _confidence(block)
            region_id = f"p{page_number:04d}-m{order:04d}"
            regions.append(
                {
                    "region_id": region_id,
                    "page": page_number,
                    "source_page_idx": source_page_idx,
                    "bbox": bbox,
                    "polygon": _polygon_from_bbox(bbox),
                    "layout_role": role,
                    "reading_order": int(block.get("index")) if isinstance(block.get("index"), int) else order,
                    "ocr_text": text,
                    "normalized_text": " ".join(text.split()),
                    "confidence": confidence,
                    "confidence_source": confidence_source,
                    "engine": "mineru",
                    "engine_version": MINERU_VERSION,
                    "model": str(producer.get("name") or "mineru"),
                    "tier": tier,
                    "runtime": runtime,
                    "source_pdf_sha256": source_sha,
                    "source_page_image_sha256": (page_image_hashes or {}).get(page_number, ""),
                    "config_sha256": config_sha,
                    "preprocess": {
                        "ocr_mode": "ocr",
                        "page_range": str(page_number),
                        "page_width": page_width,
                        "page_height": page_height,
                        "page_rotation": int(page.get("rotation") or 0),
                    },
                    "translation_group_id": f"p{page_number:04d}-g{order:04d}",
                    "status": "skipped_with_reason",
                    "translation": None,
                    "skip_reason": "translation_pending",
                    "in_destroke_mask": False,
                    "mask_geometry": {"type": "polygon", "points": _polygon_from_bbox(bbox)},
                    "mask_overlap_ratio": 0.0,
                    "asset_refs": _asset_refs(block),
                    "overflow": False,
                    "occluded": False,
                    "overlap": False,
                }
            )
    return sorted(regions, key=lambda item: (item["page"], item["reading_order"])), warnings


def _temporary_environment(values: dict[str, str]):
    class _Environment:
        def __enter__(self) -> None:
            self.before = {key: os.environ.get(key) for key in values}
            os.environ.update(values)

        def __exit__(self, *_args: object) -> None:
            for key, value in self.before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    return _Environment()


def _render_candidates(result: Any, output_dir: Path) -> list[str]:
    from mineru.render import PdfLayout, render_pdf

    experimental = output_dir / "experimental" / "mineru4"
    experimental.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for layout_name, filename in (
        ("ORIGINAL", "mineru_original_layout_candidate.pdf"),
        ("REFLOW", "mineru_reflow_candidate.pdf"),
    ):
        layout = getattr(PdfLayout, layout_name, None)
        if layout is None:
            continue
        target = experimental / filename
        target.write_bytes(render_pdf(result.middle_json, layout=layout))
        outputs.append(str(target))
    return outputs


def parse_with_mineru(
    input_pdf: Path,
    *,
    output_dir: Path,
    tier: str,
    runtime: str,
    page_range: str,
    allow_cloud_layout: bool,
    emit_render_candidates: bool = False,
    page_image_hashes: dict[int, str] | None = None,
) -> dict[str, Any]:
    if tier not in {"basic", "standard", "advanced"}:
        raise ValueError("MinerU tier must be basic, standard, or advanced")
    if runtime not in {"local", "remote"}:
        raise ValueError("MinerU runtime must be local or remote")
    if runtime == "remote" and not allow_cloud_layout:
        raise PermissionError("MinerU remote parsing requires --allow-cloud-layout")
    if runtime == "remote" and not os.environ.get("MINERU_API_KEY", "").strip():
        raise MinerUUnavailableError("mineru_remote_api_key_missing")

    readiness = doctor(tier=tier, verify_models=runtime == "local")
    if readiness.get("status") != "ok":
        raise MinerUUnavailableError(str(readiness.get("error") or readiness.get("status")))

    raw_dir = output_dir / "raw" / f"mineru-{tier}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with _temporary_environment(runtime_env()):
        if runtime == "local":
            from mineru.parser import parse

            result = parse(input_pdf, tier=tier, ocr_mode="ocr", page_range=page_range)
        else:
            from mineru.parser import MinerUApiParser

            api_key = os.environ.get("MINERU_API_KEY")
            parser = MinerUApiParser(
                api_url=os.environ.get("MINERU_API_URL"),
                api_key=api_key,
                tier=tier,
                ocr_mode="ocr",
                include_images=True,
            )
            result = parser.parse(input_pdf, page_range=page_range)

        from mineru.parser.writer import FileBasedDataWriter

        result.save(FileBasedDataWriter(str(raw_dir)))
        payload = _load_saved_middle_json(raw_dir)
        regions, warnings = normalize_middle_json(
            payload,
            input_pdf=input_pdf,
            tier=tier,
            runtime=runtime,
            page_image_hashes=page_image_hashes,
        )
        candidates = _render_candidates(result, output_dir) if emit_render_candidates else []

    raw_json_files = sorted(raw_dir.rglob("*.json"))
    raw_json_hashes = {str(path.relative_to(raw_dir)): sha256_file(path) for path in raw_json_files}
    config = {
        "tier": tier,
        "runtime": runtime,
        "page_range": page_range,
        "ocr_mode": "ocr",
        "include_images": True,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "needs_review" if warnings else "ok",
        "provider": "mineru",
        "upstream_version": MINERU_VERSION,
        "producer_version": payload.get("metadata", {}).get("producer", {}).get("version"),
        "middle_schema": payload.get("schema"),
        "middle_schema_version": payload.get("schema_version"),
        "tier": tier,
        "runtime": runtime,
        "model_backend": "local_sdk" if runtime == "local" else "official_remote_api",
        "page_range": page_range,
        "config_sha256": hashlib.sha256(
            json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "input_pdf": str(input_pdf),
        "input_sha256": sha256_file(input_pdf),
        "raw_output_dir": str(raw_dir),
        "raw_json_sha256": raw_json_hashes,
        "model_readiness": {
            "status": readiness.get("status"),
            "installed_version": readiness.get("installed_version"),
            "models_checked": readiness.get("models_checked"),
        },
        "regions": regions,
        "warnings": warnings,
        "render_candidates": candidates,
        "credentials_recorded": False,
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
