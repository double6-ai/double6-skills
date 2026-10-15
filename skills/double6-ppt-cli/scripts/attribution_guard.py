#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from double6_ppt_cli.common import content_sha_matches, sha256_file
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# ClawHub accepts <= 50 MB per version, but its multipart gateway historically rejected > 20 MB;
# keep the whole skill under 15 MB and the vendored design subset under 2 MB.
PACKAGE_BUDGET_BYTES = 15 * 1024 * 1024
DESIGN_SUBSET_BUDGET_BYTES = 2 * 1024 * 1024


def sha(path: Path) -> str:
    return sha256_file(path)


def main() -> int:
    required = [
        ROOT / "LICENSE", ROOT / "NOTICE", ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "UPSTREAM_LOCK.json", ROOT / "MODIFICATIONS.md",
        ROOT / "licenses" / "PPT_MASTER_LICENSE",
        ROOT / "licenses" / "OfficeCLI_LICENSE",
        ROOT / "licenses" / "OfficeCLI_NOTICE",
        ROOT / "licenses" / "TABLER_ICONS_LICENSE",
    ]
    errors = [f"missing:{path.relative_to(ROOT)}" for path in required if not path.is_file()]
    bom_path = ROOT / "vendor" / "ppt-master-core" / "BOM.json"
    if not bom_path.is_file():
        errors.append("missing:vendor/ppt-master-core/BOM.json")
    else:
        bom = json.loads(bom_path.read_text(encoding="utf-8"))
        for entry in bom.get("files", []):
            path = ROOT / "vendor" / "ppt-master-core" / entry["path"]
            if not path.is_file():
                errors.append(f"vendor_missing:{entry['path']}")
            elif not content_sha_matches(path, entry["sha256"]):
                errors.append(f"vendor_modified:{entry['path']}")
        design = [e for e in bom.get("files", []) if e.get("category") == "design_subset"]
        design_bytes = sum(int(e.get("bytes", 0)) for e in design)
        if design and design_bytes > DESIGN_SUBSET_BUDGET_BYTES:
            errors.append(f"design_subset_over_budget:{design_bytes}>{DESIGN_SUBSET_BUDGET_BYTES}")
        icons = [e for e in design if "/templates/icons/tabler-outline/" in e["path"]]
        if design and not (300 <= len(icons) <= 500):
            errors.append(f"design_icon_count_out_of_range:{len(icons)}")
        if design and not (ROOT / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "templates" / "icons" / "THIRD_PARTY_NOTICES.md").is_file():
            errors.append("missing:icons THIRD_PARTY_NOTICES.md")
    total = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts)
    if total > PACKAGE_BUDGET_BYTES:
        errors.append(f"package_over_budget:{total}>{PACKAGE_BUDGET_BYTES}")
    result = {"status": "pass" if not errors else "fail", "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
