#!/usr/bin/env python3
"""Re-vendor the PPT Master v6.7.0 visual-design subset into vendor/ppt-master-core.

Usage: python scripts/maintenance/vendor_design_subset.py <unzipped ppt-master-skill-v6.7.0.zip root>

Copies files byte-for-byte from the SHA-verified official release asset and appends them to
BOM.json with category ``design_subset``. Never patches upstream files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKILL = HERE.parents[2]
VENDOR = SKILL / "vendor" / "ppt-master-core"
PREFIX = "skills/ppt-master/"

REFERENCES = [
    "executor-base.md", "shared-standards-core.md", "svg-effects.md", "native-shape-authoring.md",
    "preset-shape-vocabulary.md", "image-layout-patterns.md", "image-layout-spec.md", "executor-chart.md",
    "executor-table.md", "executor-visualization.md", "visual-review.md", "native-data-interface.md",
    "semantic-svg.md", "topology-assembly.md", "executor-structure.md", "canvas-formats.md",
    "executor-image.md", "svg-image-embedding.md",
]
TREES = [
    "references/visual-styles", "references/modes", "templates/styles",
    "templates/layouts/presentation_core", "templates/layouts/report_core",
    "templates/layouts/editorial_bleed",
    "templates/charts", "templates/tables",
]
SINGLE = [
    "templates/README.md", "templates/layouts/README.md", "templates/layouts/layouts_index.json",
    "templates/design_spec_reference.md", "templates/spec_lock_reference.md",
    "templates/icons/README.md", "templates/icons/THIRD_PARTY_NOTICES.md",
    "scripts/preset_shape_svg.py", "scripts/shape_boolean_svg.py", "scripts/icon_sync.py",
    "scripts/svg_position_calculator.py",
]
WHY = {
    "references/": "Upstream visual-design guidance (page expression, styles, effects, charts) that the Double6 SKILL.md visual section routes to.",
    "templates/styles/": "Upstream style presets (communication method + visual defaults).",
    "templates/layouts/": "Upstream layout library used as composition references for generate.",
    "templates/charts/": "Upstream chart composition templates.",
    "templates/tables/": "Upstream table composition templates.",
    "templates/icons/": "Curated tabler-outline line icons (MIT) embedded at compile time.",
    "templates/": "Upstream template catalog documentation.",
    "scripts/": "Upstream authoring helper (preset shapes, boolean shapes, icon sync, position calculator).",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(src_root: str) -> int:
    root = Path(src_root)
    up = root / "ppt-master" / PREFIX if (root / "ppt-master").is_dir() else root / PREFIX
    rels: list[str] = [f"references/{r}" for r in REFERENCES] + SINGLE
    for t in TREES:
        rels += sorted(str(p.relative_to(up)).replace("\\", "/") for p in (up / t).rglob("*") if p.is_file())
    icons = (HERE.parent / "design_icons_tabler_outline.txt").read_text(encoding="utf-8").split()
    rels += [f"templates/icons/tabler-outline/{n}.svg" for n in icons]
    bom_path = VENDOR / "BOM.json"
    bom = json.loads(bom_path.read_text(encoding="utf-8"))
    known = {f["path"] for f in bom["files"]}
    added = 0
    for rel in rels:
        s = up / rel
        if not s.is_file():
            print("missing upstream", rel, file=sys.stderr)
            return 2
        path = PREFIX + rel
        dst = VENDOR / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, dst)
        if path in known:
            continue
        why = next(v for k, v in WHY.items() if rel.startswith(k))
        bom["files"].append({
            "path": path, "bytes": s.stat().st_size, "sha256": sha(s), "origin_path": path,
            "license": "MIT", "category": "design_subset", "why_needed": why,
        })
        added += 1
    bom["files"].sort(key=lambda f: f["path"])
    bom["file_count"] = len(bom["files"])
    bom["total_bytes"] = sum(f["bytes"] for f in bom["files"])
    bom["status"] = "vendored_for_double6_ppt_cli_0.5.0_generate_template_fill_and_design_subset"
    bom["design_subset"] = {
        "added_in": "double6-ppt-cli 0.5.0",
        "selection": "visual-design references, 15 styles, visual-styles/modes, presentation_core + report_core + editorial_bleed layouts, chart/table templates, curated tabler-outline icons (scripts/maintenance/design_icons_tabler_outline.txt), shape/icon authoring scripts",
        "not_included": "image generation/search, brands, decks, sounds, other icon libraries, workflows/",
    }
    bom_path.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"added": added, "file_count": bom["file_count"], "total_bytes": bom["total_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
