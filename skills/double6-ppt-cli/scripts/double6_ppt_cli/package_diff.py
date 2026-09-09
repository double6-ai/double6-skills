from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def _parts(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}


def compare_parts(before: Path, after: Path) -> dict:
    left = _parts(before)
    right = _parts(after)
    return {
        "added": sorted(set(right) - set(left)),
        "removed": sorted(set(left) - set(right)),
        "changed": sorted(name for name in set(left) & set(right) if left[name] != right[name]),
    }
