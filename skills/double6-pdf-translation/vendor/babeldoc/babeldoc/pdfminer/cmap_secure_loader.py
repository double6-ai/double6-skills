# Double6 Skills 维护版本（2026-10-17）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
"""Integrity-locked CMap loader backported from BabelDOC 0.6.4.

Upstream GHSA-m8gf-v64p-gfmg fix. The import and bundled directory below
target the 0.5.24 package layout; the 148 asset identities match upstream.
External CMAP_PATH and PDF-controlled filesystem paths are not searched.
"""
from __future__ import annotations

import gzip
import hashlib
import pickle
from pathlib import Path
from typing import Any

from ._cmap_manifest_data import CMAP_MANIFEST

BUNDLED_CMAP_DIR = (Path(__file__).resolve().parent / "cmap").resolve()


class CMapIntegrityError(Exception):
    """Requested CMap does not match a verified bundled file."""


def load_verified_cmap_data(name: str) -> Any:
    clean = name.replace("\0", "")
    filename = f"{clean}.pickle.gz"
    pinned = CMAP_MANIFEST.get(filename)
    if pinned is None:
        raise CMapIntegrityError(f"unknown cmap: {clean!r}")
    expected_sha, expected_size = pinned
    path = (BUNDLED_CMAP_DIR / filename).resolve()
    if path.parent != BUNDLED_CMAP_DIR:
        raise CMapIntegrityError(f"path escapes bundled dir: {clean!r}")
    if not path.is_file():
        raise CMapIntegrityError(f"missing bundled cmap: {clean!r}")
    if path.stat().st_size != expected_size:
        raise CMapIntegrityError(f"size mismatch: {clean!r}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise CMapIntegrityError(f"sha256 mismatch: {clean!r}")
    return pickle.loads(gzip.decompress(raw))  # verified published bytes only
