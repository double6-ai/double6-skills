#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from model_client import extract_text, post_chat


DEFAULT_ENDPOINT = ""
DEFAULT_MODEL = ""
DEFAULT_REASONING_EFFORT = "none"
DEFAULT_HYMT2_TEMPERATURE = 0.7
DEFAULT_HYMT2_MAX_TOKENS = 4096


def read_optional(path: str | None) -> str:
    if not path:
        return ""
    value = Path(path)
    return value.read_text(encoding="utf-8", errors="replace") if value.exists() else ""


def read_json_optional(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    value = Path(path)
    if not value.exists():
        return {}
    try:
        data = json.loads(value.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def default_output_path(source: Path) -> Path:
    return source.with_name("translation.md")


def default_manifest_path(source: Path) -> Path:
    return source.with_name("source_manifest.json")


def default_protected_spans_path(source: Path) -> Path:
    return source.with_name("protected_spans.json")


def build_translation_system_prompt(target_language: str) -> str:
    return (
        "你是严谨的学术论文翻译执行器。"
        f"目标语言是{target_language}。"
        "翻译必须准确、学术、可读；保留公式、引用编号、图表编号、URL、代码和数据集名。"
        "对 LLM/LLMs 等缩写必须按大语言模型语境处理，不能译为法学硕士。"
        "只输出译文 Markdown，不输出解释性前言。"
    )


def build_translation_user_input(
    *,
    source_text: str,
    glossary_text: str,
    policy_text: str,
    extra_instruction: str,
    target_language: str,
    block_context: str = "",
    protected_context: str = "",
) -> str:
    return f"""请将下面论文源文翻译为{target_language}。

## 翻译规则

{policy_text.strip() or '遵循学术论文翻译规则：准确、保守、术语一致，保留引用和公式。'}

## 术语表

{glossary_text.strip() or '暂无术语表。请先从标题、摘要和正文中识别关键术语，并在译文中保持一致。'}

## 额外要求

{extra_instruction.strip() or '无。'}

## 当前分块上下文

{block_context.strip() or '整篇文档翻译。'}

## 不可翻译元素

{protected_context.strip() or '无。若源文出现公式、引用编号、URL、DOI、代码或变量名，请保留原样。'}

## 源文

{source_text}
"""


def spans_for_block(protected_spans: dict[str, Any], block_id: str) -> list[dict[str, Any]]:
    spans = protected_spans.get("spans")
    if not isinstance(spans, list):
        return []
    return [item for item in spans if isinstance(item, dict) and item.get("block_id") == block_id]


def format_protected_context(spans: list[dict[str, Any]]) -> str:
    if not spans:
        return ""
    lines = []
    for item in spans:
        lines.append(f"- {item.get('token')}: {item.get('kind')} = {item.get('value')}")
    return "\n".join(lines)


def translate_text(
    *,
    text: str,
    glossary_text: str,
    policy_text: str,
    extra_instruction: str,
    target_language: str,
    block_context: str,
    protected_context: str,
    args: argparse.Namespace,
) -> tuple[str, dict[str, Any]]:
    user_input = build_translation_user_input(
        source_text=text,
        glossary_text=glossary_text,
        policy_text=policy_text,
        extra_instruction=extra_instruction,
        target_language=target_language,
        block_context=block_context,
        protected_context=protected_context,
    )
    response = post_chat(
        endpoint=args.endpoint,
        model=args.model,
        system_prompt=build_translation_system_prompt(target_language),
        user_input=user_input,
        request_timeout_seconds=args.timeout,
        provider=args.provider,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        extra_body=(
            {"reasoning_effort": getattr(args, "reasoning_effort", DEFAULT_REASONING_EFFORT)}
            if getattr(args, "reasoning_effort", DEFAULT_REASONING_EFFORT)
            else None
        ),
    )
    return extract_text(response), response


def write_translation_blocks(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_model_response(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ["response_id", "id", "model", "model_instance_id"]:
        value = response.get(key)
        if isinstance(value, (str, int, float)):
            summary[key] = value
    stats = response.get("stats")
    if isinstance(stats, dict):
        summary["stats"] = {
            key: value
            for key, value in stats.items()
            if isinstance(value, (str, int, float, bool)) and key != "reasoning_content"
        }
    output = response.get("output")
    if isinstance(output, list):
        summary["output_types"] = [
            item.get("type")
            for item in output
            if isinstance(item, dict) and isinstance(item.get("type"), str)
        ]
    choices = response.get("choices")
    if isinstance(choices, list):
        summary["choice_count"] = len(choices)
    return summary


def write_run_manifest(
    *,
    path: Path,
    status: str,
    args: argparse.Namespace,
    source_path: Path,
    output_path: Path,
    source_manifest_path: Path,
    protected_spans_path: Path,
    translation_blocks_path: Path,
    block_records: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    started: float,
) -> dict[str, Any]:
    manifest = {
        "status": status,
        "executor_endpoint": args.endpoint,
        "executor_provider": args.provider or "local_hermes",
        "executor_model": args.model,
        "reasoning_effort": getattr(args, "reasoning_effort", DEFAULT_REASONING_EFFORT),
        "source": str(source_path),
        "source_manifest": str(source_manifest_path) if source_manifest_path.exists() else None,
        "protected_spans": str(protected_spans_path) if protected_spans_path.exists() else None,
        "glossary": args.glossary,
        "policy": args.policy,
        "output": str(output_path),
        "translation_blocks": str(translation_blocks_path) if block_records else None,
        "block_count": len(block_records),
        "error_count": len(errors),
        "errors": errors,
        "allow_partial": bool(getattr(args, "allow_partial", False)),
        "duration_seconds": round(time.monotonic() - started, 3),
        "responses": responses,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def translate(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    source_path = Path(args.source)
    output_path = Path(args.output) if args.output else default_output_path(source_path)
    manifest_path = Path(args.manifest) if args.manifest else output_path.with_name("translation_run_manifest.json")
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    glossary_text = read_optional(args.glossary)
    policy_text = read_optional(args.policy)
    source_manifest_path = Path(args.source_manifest) if args.source_manifest else default_manifest_path(source_path)
    protected_spans_path = Path(args.protected_spans) if args.protected_spans else default_protected_spans_path(source_path)
    source_manifest = read_json_optional(str(source_manifest_path))
    protected_spans = read_json_optional(str(protected_spans_path))
    blocks = source_manifest.get("blocks") if not args.whole_document else None
    translation_blocks_path = Path(args.translation_blocks) if args.translation_blocks else output_path.with_name("translation_blocks.jsonl")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    block_records: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if isinstance(blocks, list) and blocks:
        translated_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("block_id") or f"block-{len(block_records) + 1:04d}")
            block_text = str(block.get("text") or "")
            block_spans = spans_for_block(protected_spans, block_id)
            block_context = (
                f"block_id: {block_id}\n"
                f"section: {block.get('section') or ''}\n"
                f"page: {block.get('page') or ''}\n"
                f"element_type: {block.get('element_type') or 'paragraph'}\n"
                "请只翻译自然语言，保留不可翻译元素原文。"
            )
            try:
                translation, response = translate_text(
                    text=block_text,
                    glossary_text=glossary_text,
                    policy_text=policy_text,
                    extra_instruction=args.instruction or "",
                    target_language=args.target_language,
                    block_context=block_context,
                    protected_context=format_protected_context(block_spans),
                    args=args,
                )
            except Exception as exc:
                error = {"block_id": block_id, "error": str(exc), "error_type": type(exc).__name__}
                errors.append(error)
                record = {
                    "block_id": block_id,
                    "status": "error",
                    "source_text": block_text,
                    "translation": "",
                    "section": block.get("section"),
                    "page": block.get("page"),
                    "element_type": block.get("element_type"),
                    "protected_span_ids": [item.get("span_id") for item in block_spans],
                    "executor_provider": args.provider or "local_hermes",
                    "executor_model": args.model,
                    "error": error["error"],
                    "error_type": error["error_type"],
                }
                block_records.append(record)
                if not getattr(args, "allow_partial", False):
                    write_translation_blocks(translation_blocks_path, block_records)
                    output_path.write_text("\n\n".join(translated_parts).rstrip() + "\n", encoding="utf-8")
                    write_run_manifest(
                        path=manifest_path,
                        status="error",
                        args=args,
                        source_path=source_path,
                        output_path=output_path,
                        source_manifest_path=source_manifest_path,
                        protected_spans_path=protected_spans_path,
                        translation_blocks_path=translation_blocks_path,
                        block_records=block_records,
                        responses=responses,
                        errors=errors,
                        started=started,
                    )
                    raise
                translated_parts.append(f"<!-- block:{block_id} status:error -->\n\n<!-- 翻译失败：{error['error']} -->")
                continue
            record = {
                "block_id": block_id,
                "status": "ok",
                "source_text": block_text,
                "translation": translation,
                "section": block.get("section"),
                "page": block.get("page"),
                "element_type": block.get("element_type"),
                "protected_span_ids": [item.get("span_id") for item in block_spans],
                "executor_provider": args.provider or "local_hermes",
                "executor_model": args.model,
            }
            block_records.append(record)
            responses.append({"block_id": block_id, "response_summary": summarize_model_response(response)})
            translated_parts.append(f"<!-- block:{block_id} -->\n\n{translation.strip()}")
        translation = "\n\n".join(translated_parts).rstrip() + "\n"
        write_translation_blocks(translation_blocks_path, block_records)
    else:
        try:
            translation, response = translate_text(
                text=source_text,
                glossary_text=glossary_text,
                policy_text=policy_text,
                extra_instruction=args.instruction or "",
                target_language=args.target_language,
                block_context="整篇文档翻译；未使用 source_manifest blocks。",
                protected_context=format_protected_context(protected_spans.get("spans", []) if isinstance(protected_spans.get("spans"), list) else []),
                args=args,
            )
        except Exception as exc:
            errors.append({"block_id": None, "error": str(exc), "error_type": type(exc).__name__})
            output_path.write_text("", encoding="utf-8")
            write_run_manifest(
                path=manifest_path,
                status="error",
                args=args,
                source_path=source_path,
                output_path=output_path,
                source_manifest_path=source_manifest_path,
                protected_spans_path=protected_spans_path,
                translation_blocks_path=translation_blocks_path,
                block_records=block_records,
                responses=responses,
                errors=errors,
                started=started,
            )
            raise
        responses.append({"response_summary": summarize_model_response(response)})

    output_path.write_text(translation.rstrip() + "\n", encoding="utf-8")
    return write_run_manifest(
        path=manifest_path,
        status="partial" if errors else "ok",
        args=args,
        source_path=source_path,
        output_path=output_path,
        source_manifest_path=source_manifest_path,
        protected_spans_path=protected_spans_path,
        translation_blocks_path=translation_blocks_path,
        block_records=block_records,
        responses=responses,
        errors=errors,
        started=started,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate a prepared academic paper source with the local translation model.")
    parser.add_argument("--source", required=True, help="Prepared source.md path.")
    parser.add_argument("--glossary", help="Glossary TSV path.")
    parser.add_argument("--source-manifest", help="source_manifest.json path. Defaults to beside source.")
    parser.add_argument("--protected-spans", help="protected_spans.json path. Defaults to beside source.")
    parser.add_argument("--translation-blocks", help="translation_blocks.jsonl path. Defaults to beside output.")
    parser.add_argument(
        "--policy",
        default=str(Path(__file__).resolve().parents[1] / "references" / "academic-translation-policy.md"),
        help="Academic translation policy path.",
    )
    parser.add_argument("--output", help="Output translation.md path. Defaults to beside source.")
    parser.add_argument("--manifest", help="Run manifest path. Defaults to translation_run_manifest.json beside output.")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("LOCAL_TRANSLATION_ENDPOINT") or DEFAULT_ENDPOINT,
        help="Chat completions endpoint.",
    )
    parser.add_argument("--provider", default="openai_compatible", help="Chat provider shape.")
    parser.add_argument("--model", default=os.environ.get("LOCAL_TRANSLATION_MODEL") or DEFAULT_MODEL, help="Executor model.")
    parser.add_argument("--target-language", default="简体中文", help="Target language.")
    parser.add_argument("--instruction", help="Extra translation instruction.")
    parser.add_argument("--whole-document", action="store_true", help="Ignore manifest blocks and translate source.md as one document.")
    parser.add_argument("--allow-partial", action="store_true", help="Continue after block-level model errors and write partial artifacts.")
    parser.add_argument("--temperature", type=float, default=DEFAULT_HYMT2_TEMPERATURE)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_HYMT2_MAX_TOKENS)
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.endpoint.strip() or not args.model.strip():
        parser.error("--endpoint and --model are required.")
    manifest = translate(args)
    print(json.dumps({k: v for k, v in manifest.items() if k != "responses"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
