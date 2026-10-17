# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline resources：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

def _config_sha256(payload: dict[str, Any]) -> str:
    return _sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))

def _polygon_bbox(points: list[list[float]]) -> list[float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]

def _process_rss_gib() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024**3) if raw > 1024**2 else raw / (1024**2)

def _check_memory_limit() -> None:
    rss = _process_rss_gib()
    if rss > 20.0:
        raise MemoryError(f"paper-translation scanned pipeline exceeded 20 GiB RSS ({rss:.2f} GiB)")

def render_page_png(
    input_pdf: Path, page_number: int, *, dpi: int = DEFAULT_SCAN_DPI
) -> tuple[bytes, float, float, int]:
    import fitz

    document = fitz.open(input_pdf)
    try:
        page = document[page_number - 1]
        pixmap = stable_get_pixmap(page, matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        return pixmap.tobytes("png"), float(page.rect.width), float(page.rect.height), int(page.rotation)
    finally:
        document.close()

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
