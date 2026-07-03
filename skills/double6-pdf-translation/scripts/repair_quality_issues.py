#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import policy_utils

DEFAULT_RESIDUE_TRANSLATIONS = policy_utils.DEFAULT_RESIDUE_TRANSLATIONS
TERM_REPLACEMENT_HINTS = policy_utils.TERM_REPLACEMENT_HINTS


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_residue_translations(values: list[str]) -> dict[str, str]:
    translations = dict(DEFAULT_RESIDUE_TRANSLATIONS)
    for value in values:
        if "=" not in value:
            continue
        source, target = value.split("=", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            translations[source] = target
    return translations


def iter_issues(affected_blocks: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for block in affected_blocks.get("affected_blocks", []) if isinstance(affected_blocks.get("affected_blocks"), list) else []:
        if not isinstance(block, dict):
            continue
        for issue in block.get("issues", []) if isinstance(block.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            item = dict(issue)
            item.setdefault("block_id", block.get("block_id") or "document")
            item.setdefault("page", block.get("page") or "global")
            issues.append(item)
    return issues


def collect_missing_protected_values(issues: list[dict[str, Any]], translation: str) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for issue in issues:
        if str(issue.get("category") or "") != "protected_span":
            continue
        value = str(issue.get("source_evidence") or "").strip()
        if not value or value in translation or value in seen:
            continue
        seen.add(value)
        values.append(
            {
                "value": value,
                "block_id": str(issue.get("block_id") or "document"),
                "page": str(issue.get("page") or "global"),
                "title": str(issue.get("title") or "不可翻译元素缺失"),
            }
        )
    return values


def collect_residue_repairs(issues: list[dict[str, Any]], translation: str, residue_translations: dict[str, str]) -> list[dict[str, str]]:
    repairs: list[dict[str, str]] = []
    seen: set[str] = set()
    for issue in issues:
        title = str(issue.get("title") or "")
        if str(issue.get("category") or "") != "omission" or "must_translate" not in title:
            continue
        evidence = str(issue.get("translation_evidence") or "")
        evidence_parts = [part.strip() for part in re.split(r"[；;,]+", evidence) if part.strip()]
        tokens: list[str] = []
        for part in evidence_parts:
            if part in TERM_REPLACEMENT_HINTS or part in residue_translations:
                tokens.append(part)
            tokens.extend(piece.strip() for piece in re.split(r"\s+", part) if piece.strip())
        for token in tokens:
            target = residue_translations.get(token) or residue_translations.get(token.lower())
            if not target:
                for _key, replacements in TERM_REPLACEMENT_HINTS.items():
                    for old, new in replacements:
                        if token == old:
                            target = new
                            break
                    if target:
                        break
            if not target or token in seen or not re.search(rf"\b{re.escape(token)}\b", translation):
                continue
            seen.add(token)
            repairs.append(
                {
                    "source": token,
                    "target": target,
                    "block_id": str(issue.get("block_id") or "document"),
                    "page": str(issue.get("page") or "global"),
                }
            )
    return repairs


def apply_residue_repairs(translation: str, repairs: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    applied: list[dict[str, Any]] = []
    repaired = translation
    for repair in repairs:
        source = repair["source"]
        target = repair["target"]
        pattern = re.compile(rf"\b{re.escape(source)}\b")
        repaired, count = pattern.subn(target, repaired)
        if count:
            applied.append({**repair, "replacement_count": count})
    return repaired, applied


def collect_policy_repairs(issues: list[dict[str, Any]], translation: str) -> list[dict[str, str]]:
    repairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        category = str(issue.get("category") or "")
        if category not in {"entity_accuracy", "terminology"}:
            continue
        source = str(issue.get("source_evidence") or "")
        for key, replacements in TERM_REPLACEMENT_HINTS.items():
            if source != key and key not in source:
                continue
            for old, new in replacements:
                if old not in translation or (old, new) in seen:
                    continue
                seen.add((old, new))
                repairs.append(
                    {
                        "source": old,
                        "target": new,
                        "policy_source": key,
                        "block_id": str(issue.get("block_id") or "document"),
                        "page": str(issue.get("page") or "global"),
                    }
                )
    return repairs


def apply_literal_repairs(translation: str, repairs: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    applied: list[dict[str, Any]] = []
    repaired = translation
    for repair in repairs:
        source = repair["source"]
        target = repair["target"]
        count = repaired.count(source)
        if not count:
            continue
        repaired = repaired.replace(source, target)
        applied.append({**repair, "replacement_count": count})
    return repaired, applied


def normalize_metadata_entity_lines(translation: str) -> tuple[str, list[dict[str, Any]]]:
    repaired, count = re.subn(
        r"(polyu\.edu\.hk)[\x00-\x1f\s]*是香港理工大学（The[\x00-\x1f\s]*Hong[\x00-\x1f\s]*Kong[\x00-\x1f\s]*Polytechnic[\x00-\x1f\s]*University）的官方网站域名。",
        r"\1。",
        translation,
    )
    if not count:
        return translation, []
    return repaired, [
        {
            "repair_type": "metadata_entity_line_normalization",
            "auto_fixable": True,
            "requires_rerender": True,
            "source": "polyu.edu.hk + Hong Kong Polytechnic University metadata line",
            "target": "polyu.edu.hk。",
            "replacement_count": count,
            "block_id": "metadata",
            "page": "global",
        }
    ]


def append_protected_recovery_section(translation: str, values: list[dict[str, str]]) -> str:
    if not values:
        return translation
    lines = ["", "## 受保护元素恢复清单", ""]
    for item in values:
        location = f"block={item['block_id']}, page={item['page']}"
        lines.append(f"- `{item['value']}`（{location}）")
    return translation.rstrip() + "\n" + "\n".join(lines) + "\n"


def repair_translation(
    translation: str,
    affected_blocks: dict[str, Any],
    residue_translations: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    issues = iter_issues(affected_blocks)
    protected_values = collect_missing_protected_values(issues, translation)
    residue_repairs = collect_residue_repairs(issues, translation, residue_translations)
    repaired, applied_residue_repairs = apply_residue_repairs(translation, residue_repairs)
    policy_repairs = collect_policy_repairs(issues, repaired)
    repaired, applied_policy_repairs = apply_literal_repairs(repaired, policy_repairs)
    repaired, metadata_line_repairs = normalize_metadata_entity_lines(repaired)
    repaired = append_protected_recovery_section(repaired, protected_values)
    repairs: list[dict[str, Any]] = []
    repairs.extend(
        {
            "repair_type": "auto_text_residue_replacement",
            "auto_fixable": True,
            "requires_rerender": True,
            **item,
        }
        for item in applied_residue_repairs
    )
    repairs.extend(
        {
            "repair_type": "protected_span_readable_fallback_append",
            "auto_fixable": True,
            "requires_rerender": True,
            **item,
        }
        for item in protected_values
    )
    repairs.extend(
        {
            "repair_type": "policy_literal_replacement",
            "auto_fixable": True,
            "requires_rerender": True,
            **item,
        }
        for item in applied_policy_repairs
    )
    repairs.extend(metadata_line_repairs)
    plan = {
        "version": 1,
        "status": "repaired" if repairs else "ok",
        "repair_count": len(repairs),
        "residue_repair_count": len(applied_residue_repairs),
        "protected_span_recovery_count": len(protected_values),
        "policy_repair_count": len(applied_policy_repairs),
        "repairs": repairs,
        "notes": [
            "该脚本只生成可读降级译文修复，不原地修改 PDF。",
            "requires_rerender=true 表示若要让 PDF 同步修复，需要重新走渲染或局部重译流程。",
        ],
    }
    return repaired, plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair high-confidence QA issues into a readable fallback translation.")
    parser.add_argument("--translation", required=True, help="translation.md path.")
    parser.add_argument("--affected-blocks", required=True, help="affected_blocks.json path.")
    parser.add_argument("--output", help="Output repaired Markdown. Defaults to translation.qa_repaired.md.")
    parser.add_argument("--plan", help="Output repair plan JSON. Defaults to qa_repair_plan.json.")
    parser.add_argument("--residue-translation", action="append", default=[], help="Manual residue mapping, e.g. overwhelmingly=压倒性地.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    translation_path = Path(args.translation)
    affected_blocks_path = Path(args.affected_blocks)
    output_path = Path(args.output) if args.output else translation_path.with_name("translation.qa_repaired.md")
    plan_path = Path(args.plan) if args.plan else translation_path.with_name("qa_repair_plan.json")

    translation = translation_path.read_text(encoding="utf-8", errors="replace")
    affected_blocks = load_json(affected_blocks_path)
    residue_translations = load_residue_translations(args.residue_translation)
    repaired, plan = repair_translation(translation, affected_blocks, residue_translations)
    output_path.write_text(repaired, encoding="utf-8")
    plan.update(
        {
            "input_translation": str(translation_path),
            "affected_blocks": str(affected_blocks_path),
            "output_translation": str(output_path),
        }
    )
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "plan": str(plan_path), "status": plan["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
