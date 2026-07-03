#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from typing import Any

import policy_utils

DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "qwen/qwen3.6-35b-a3b"
DEFAULT_API_KEY = "local-dummy"
DEFAULT_REASONING_EFFORT = "none"
DEFAULT_SYSTEM_PROMPT = (
    "/no_think You are a professional, authentic machine translation engine. "
    "Translate the input into fluent Simplified Chinese. Output translation only. "
    "Preserve formulas, citations, URLs, code, named entities, and placeholders exactly. "
    "Do not leave ordinary English prose words untranslated; translate residual words such as "
    "'overwhelmingly' into natural Chinese unless they are protected spans, code, URLs, emails, or approved names."
)


def compact_items(items: list[dict[str, Any]], *, key: str, limit: int = 12) -> list[str]:
    lines = []
    for item in items[:limit]:
        source = str(item.get("source_term") or "")
        translation = str(item.get("translation") or "")
        note = str(item.get("note") or "")
        if not source or not translation:
            continue
        line = f"- {source} => {translation}"
        forbidden = item.get("forbidden_translations")
        if isinstance(forbidden, list) and forbidden:
            line += "；禁用：" + "、".join(str(value) for value in forbidden if value)
        if note:
            line += f"；{note[:120]}"
        lines.append(line)
    return lines


def load_context_prompt(path_value: str | None) -> str:
    prompt = policy_utils.build_policy_context_prompt(policy_utils.load_policy_context(path_value))
    return ("\n" + prompt) if prompt else ""


def chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def extract_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                raise RuntimeError("Qwen returned reasoning_content but empty message.content; reasoning_effort=none was not honored.")
    raise RuntimeError("No translated content found in model response.")


def protected_values(text: str) -> list[str]:
    return policy_utils.protected_values(text)


def missing_protected_values(source_text: str, translated_text: str) -> list[str]:
    return policy_utils.missing_protected_values(source_text, translated_text)


def build_retry_user_input(text: str, missing_values: list[str]) -> str:
    values = "\n".join(f"- {value}" for value in missing_values)
    return (
        "The previous translation omitted protected spans. Translate the source again into Simplified Chinese, "
        "and preserve every protected span exactly as written.\n\n"
        f"Protected spans that must appear verbatim:\n{values}\n\n"
        f"Source:\n{text}"
    )


def apply_source_aware_replacements(source_text: str, translated_text: str) -> str:
    return policy_utils.apply_source_aware_replacements(source_text, translated_text)


def request_translation(user_text: str, system_prompt: str, args: argparse.Namespace) -> str:
    context_prompt = load_context_prompt(args.context_file)
    if context_prompt:
        system_prompt = f"{system_prompt}\n\n{context_prompt}"
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }
    if args.reasoning_effort:
        payload["reasoning_effort"] = args.reasoning_effort
    request = urllib.request.Request(
        chat_completions_url(args.base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen CLI translator HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Qwen CLI translator request failed: {exc}") from exc
    return extract_content(json.loads(raw))


def translate(text: str, args: argparse.Namespace) -> str:
    first = request_translation(text, args.system_prompt, args)
    first = apply_source_aware_replacements(text, first)
    missing = missing_protected_values(text, first)
    if not missing:
        return first
    retry_prompt = (
        args.system_prompt
        + "\nProtected span validation failed on the previous attempt. The retry must include every listed protected span verbatim."
    )
    second = request_translation(build_retry_user_input(text, missing), retry_prompt, args)
    second = apply_source_aware_replacements(text, second)
    still_missing = missing_protected_values(text, second)
    if still_missing:
        raise RuntimeError("Qwen CLI translator omitted protected spans after retry: " + "; ".join(still_missing[:8]))
    return second


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="stdin/stdout Qwen translator adapter for pdf2zh-next CLITranslator.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--context-file", help="Optional document_memory.json with global terminology/entity constraints.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = sys.stdin.read()
    if not source.strip():
        return 0
    try:
        print(translate(source, args))
    except Exception as exc:  # noqa: BLE001 - stderr 是 pdf2zh 失败归因入口
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
