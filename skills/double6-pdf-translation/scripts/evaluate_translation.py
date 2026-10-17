#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from model_client import extract_json_object, extract_text, post_chat


DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"


def read_optional(path: str | None) -> str:
    if not path:
        return ""
    value = Path(path)
    return value.read_text(encoding="utf-8", errors="replace") if value.exists() else ""


def build_evaluation_system_prompt() -> str:
    return (
        "你是学术论文翻译质量评测员。"
        "你只评价给定源文和译文，不重新翻译整篇文章。"
        "必须返回严格 JSON，不要输出 Markdown。"
    )


def build_evaluation_user_input(
    *,
    source_text: str,
    translation_text: str,
    glossary_text: str,
    quality_report: str,
) -> str:
    return f"""请评测这份论文译文。重点关注：
1. 术语一致性，尤其 LLM/LLMs、Literature Review、自造词和模型名。
2. 标题、摘要、引用、公式、图表编号是否保真。
3. 是否有未翻译英文、误译、漏译、逻辑强化或削弱。
4. 中文是否学术但可读。

返回 JSON，schema:
{{
  "overall_score": 0-100,
  "terminology_score": 0-100,
  "faithfulness_score": 0-100,
  "readability_score": 0-100,
  "structure_score": 0-100,
  "critical_errors": ["..."],
  "warnings": ["..."],
  "strengths": ["..."],
  "revision_priorities": ["..."],
  "verdict": "pass|revise|fail"
}}

## 术语表

{glossary_text.strip() or '无'}

## 本地规则质检报告

{quality_report.strip() or '无'}

## 源文

{source_text}

## 译文

{translation_text}
"""


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    source_path = Path(args.source)
    translation_path = Path(args.translation)
    output_path = Path(args.output) if args.output else translation_path.with_name("deepseek_evaluation.json")
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    translation_text = translation_path.read_text(encoding="utf-8", errors="replace")
    user_input = build_evaluation_user_input(
        source_text=source_text,
        translation_text=translation_text,
        glossary_text=read_optional(args.glossary),
        quality_report=read_optional(args.quality_report),
    )
    response = post_chat(
        endpoint=args.endpoint,
        model=args.model,
        system_prompt=build_evaluation_system_prompt(),
        user_input=user_input,
        request_timeout_seconds=args.timeout,
        provider=args.provider,
        api_key_env=args.api_key_env,
        api_key_file=args.api_key_file,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        response_format={"type": "json_object"},
    )
    output_text = extract_text(response)
    parsed = extract_json_object(output_text)
    result: dict[str, Any] = {
        "status": "ok" if parsed is not None else "unparsed",
        "judge_endpoint": args.endpoint,
        "judge_provider": args.provider,
        "judge_model": args.model,
        "source": str(source_path),
        "translation": str(translation_path),
        "glossary": args.glossary,
        "quality_report": args.quality_report,
        "duration_seconds": round(time.monotonic() - started, 3),
        "evaluation": parsed,
        "raw_output": output_text,
        "response": response,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate an academic paper translation with DeepSeek.")
    parser.add_argument("--source", required=True, help="Source Markdown/text path.")
    parser.add_argument("--translation", required=True, help="Translation Markdown/text path.")
    parser.add_argument("--glossary", help="Glossary TSV path.")
    parser.add_argument("--quality-report", help="Local quality_report.md path.")
    parser.add_argument("--output", help="Output JSON path. Defaults to deepseek_evaluation.json beside translation.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--provider", default="openai_compatible")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--api-key-file")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate(args)
    print(json.dumps({k: v for k, v in result.items() if k != "response"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
