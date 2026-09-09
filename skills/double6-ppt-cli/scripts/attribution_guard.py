#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    required = [
        ROOT / "LICENSE", ROOT / "NOTICE", ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "UPSTREAM_LOCK.json", ROOT / "MODIFICATIONS.md",
        ROOT / "licenses" / "PPT_MASTER_LICENSE",
        ROOT / "licenses" / "OfficeCLI_LICENSE",
        ROOT / "licenses" / "OfficeCLI_NOTICE",
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
            elif sha(path) != entry["sha256"]:
                errors.append(f"vendor_modified:{entry['path']}")
    result = {"status": "pass" if not errors else "fail", "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
