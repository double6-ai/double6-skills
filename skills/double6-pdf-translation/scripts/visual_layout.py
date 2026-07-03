#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


from visual_layout_core import *  # noqa: F401,F403
from visual_layout_core import _load_fitz
from visual_layout_findings import *  # noqa: F401,F403
from visual_layout_analyzer import *  # noqa: F401,F403
from visual_layout_analyzer import _page_region_metrics
from visual_layout_semantic import *  # noqa: F401,F403

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build visual regression report for translated PDFs.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--pages", default="auto", help="Pages to inspect, e.g. 1,2,5,8-10. Default auto checks the first pages.")
    args = parser.parse_args()
    report = build_visual_layout_report(
        Path(args.source_pdf),
        Path(args.translated_pdf),
        Path(args.output_dir),
        max_pages=args.max_pages,
        pages=parse_page_selection(args.pages),
    )
    output_path = Path(args.output_dir) / "visual_layout_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
