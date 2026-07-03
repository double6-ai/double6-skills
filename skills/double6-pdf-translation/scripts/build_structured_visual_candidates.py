#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def build_structured_visual_candidates(
    *,
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    manifest_path: Path | None = None,
    human_review_path: Path | None = None,
) -> dict[str, Any]:
    if not translated_pdf.exists():
        manifest = {"version": 1, "status": "skipped", "reason": "missing_translated_pdf", "candidates": []}
    else:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(translated_pdf, output_pdf)
        manifest = {
            "version": 1,
            "status": "candidate_pending_human_review",
            "reason": "generic_structured_visual_candidate",
            "source_pdf": str(source_pdf),
            "translated_pdf": str(translated_pdf),
            "output_pdf": str(output_pdf),
            "candidate_count": 0,
            "safe_for_auto_delivery": False,
            "human_review_required": True,
            "human_review_status": "pending",
            "human_visual_review": str(human_review_path) if human_review_path else None,
            "candidates": [],
        }
    if manifest_path:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a generic structured visual candidate manifest.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--human-review")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    build_structured_visual_candidates(
        source_pdf=Path(args.source_pdf),
        translated_pdf=Path(args.translated_pdf),
        output_pdf=Path(args.output_pdf),
        manifest_path=Path(args.manifest),
        human_review_path=Path(args.human_review) if args.human_review else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
