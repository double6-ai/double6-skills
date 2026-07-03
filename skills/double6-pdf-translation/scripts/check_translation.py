#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import repair_quality_issues
from check_translation_memory import *  # noqa: F401,F403

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check an academic paper translation for terminology and structure risks.")
    parser.add_argument("--source", required=True, help="Source Markdown/text path.")
    parser.add_argument("--translation", required=True, help="Translation Markdown/text path.")
    parser.add_argument("--glossary", help="Glossary TSV path.")
    parser.add_argument("--source-manifest", help="source_manifest.json path. Defaults to beside source.")
    parser.add_argument("--protected-spans", help="protected_spans.json path. Defaults to beside source.")
    parser.add_argument("--translation-blocks", help="translation_blocks.jsonl path. Defaults to beside translation.")
    parser.add_argument("--render-manifest", help="render_manifest.json path. Defaults to beside translation.")
    parser.add_argument("--output", help="Quality report path. Defaults to quality_report.md beside the translation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_path = Path(args.source)
    translation_path = Path(args.translation)
    glossary_path = Path(args.glossary) if args.glossary else None
    manifest_path = Path(args.source_manifest) if args.source_manifest else source_path.with_name("source_manifest.json")
    protected_spans_path = Path(args.protected_spans) if args.protected_spans else source_path.with_name("protected_spans.json")
    translation_blocks_path = Path(args.translation_blocks) if args.translation_blocks else translation_path.with_name("translation_blocks.jsonl")
    render_manifest_path = Path(args.render_manifest) if args.render_manifest else translation_path.with_name("render_manifest.json")
    output_path = Path(args.output) if args.output else translation_path.with_name("quality_report.md")

    source = source_path.read_text(encoding="utf-8", errors="replace")
    translation = translation_path.read_text(encoding="utf-8", errors="replace")
    glossary = load_glossary(glossary_path)
    manifest = load_json(manifest_path)
    manifest["coverage_gate"] = manifest.get("coverage_gate") if isinstance(manifest.get("coverage_gate"), dict) else build_coverage_gate(manifest, translation)
    protected_spans = load_json(protected_spans_path)
    translation_blocks = load_translation_blocks(translation_blocks_path)
    render_manifest = load_json(render_manifest_path)
    term_policy = build_term_policy(glossary, manifest=manifest, source=source)
    entity_map = build_entity_map(manifest, glossary)
    issues = collect_issues(
        source,
        translation,
        glossary,
        manifest=manifest,
        protected_spans=protected_spans,
        translation_blocks=translation_blocks,
        render_manifest=render_manifest,
    )
    report = render_quality_report(issues)
    output_path.write_text(report, encoding="utf-8")
    output_path.with_name("alignment_report.json").write_text(
        json.dumps(build_alignment_report(manifest, translation_blocks), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("document_memory.json").write_text(
        json.dumps(
            build_document_memory(manifest, glossary, entity_map=entity_map, term_policy=term_policy),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    output_path.with_name("term_policy.json").write_text(
        json.dumps(term_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("entity_map.json").write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("qa_checks.json").write_text(
        json.dumps(build_qa_checks(issues), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    affected_blocks = build_affected_blocks(issues, manifest, translation_blocks)
    output_path.with_name("affected_blocks.json").write_text(
        json.dumps(affected_blocks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_path.with_name("confirmed_repair_plan.json").write_text(
        json.dumps(
            build_confirmed_repair_plan(
                load_json(output_path.with_name("manual_confirmations.json")),
                affected_blocks,
                manifest,
                translation_blocks,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    repaired_translation, qa_repair_plan = repair_quality_issues.repair_translation(
        translation,
        affected_blocks,
        repair_quality_issues.DEFAULT_RESIDUE_TRANSLATIONS,
    )
    repaired_path = output_path.with_name("translation.qa_repaired.md")
    qa_repair_plan_path = output_path.with_name("qa_repair_plan.json")
    repaired_path.write_text(repaired_translation, encoding="utf-8")
    qa_repair_plan.update(
        {
            "input_translation": str(translation_path),
            "affected_blocks": str(output_path.with_name("affected_blocks.json")),
            "output_translation": str(repaired_path),
        }
    )
    qa_repair_plan_path.write_text(json.dumps(qa_repair_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
