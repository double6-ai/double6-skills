#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
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

DEFAULT_BASE_URL = None
DEFAULT_MODEL = None
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


def resolve_target_language(args: argparse.Namespace) -> str:
    """显式 --target-language 优先；未传时，系统提示词以中译英默认提示词开头即判定为 en，否则保持 zh（英译中默认不变）。"""
    explicit = getattr(args, "target_language", None)
    if explicit:
        return policy_utils.normalize_target_language(explicit)
    prompt = str(getattr(args, "system_prompt", "") or "")
    return "en" if prompt.startswith(policy_utils.DEFAULT_SYSTEM_PROMPT_EN) else "zh"


def effective_system_prompt(args: argparse.Namespace) -> str:
    # 中译英但沿用了本适配器的英译中默认提示词时，换成中译英默认提示词。
    if resolve_target_language(args) == "en" and args.system_prompt == DEFAULT_SYSTEM_PROMPT:
        return policy_utils.DEFAULT_SYSTEM_PROMPT_EN
    return args.system_prompt


def load_context_prompt(path_value: str | None, target_language: str = "zh") -> str:
    prompt = policy_utils.build_policy_context_prompt(policy_utils.load_policy_context(path_value), target_language=target_language)
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


TARGET_LANGUAGE_NAMES = {"zh": "Simplified Chinese", "en": "English"}


def build_retry_user_input(text: str, missing_values: list[str], target_language: str = "zh") -> str:
    values = "\n".join(f"- {value}" for value in missing_values)
    target_name = TARGET_LANGUAGE_NAMES[policy_utils.normalize_target_language(target_language)]
    return (
        f"The previous translation omitted protected spans. Translate the source again into {target_name}, "
        "and preserve every protected span exactly as written.\n\n"
        f"Protected spans that must appear verbatim:\n{values}\n\n"
        f"Source:\n{text}"
    )


def apply_source_aware_replacements(source_text: str, translated_text: str, target_language: str = "zh") -> str:
    return policy_utils.apply_source_aware_replacements(source_text, translated_text, target_language)


def request_translation(user_text: str, system_prompt: str, args: argparse.Namespace) -> str:
    context_prompt = load_context_prompt(args.context_file, resolve_target_language(args))
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
    for name in ("top_p", "top_k", "repetition_penalty"):
        value = getattr(args, name, None)
        if value is not None:
            payload[name] = value
    if args.reasoning_effort and "qwen" in str(args.model).lower():
        payload["reasoning_effort"] = args.reasoning_effort
    request = urllib.request.Request(
        chat_completions_url(args.base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            **({"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}),
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
    target = resolve_target_language(args)
    system_prompt = effective_system_prompt(args)
    first = request_translation(text, system_prompt, args)
    if policy_utils.policy_note_leaks(text, first, policy_utils.load_policy_context(getattr(args, "context_file", None))):
        raise RuntimeError("policy_instruction_leak: model output copied document policy notes")
    first = apply_source_aware_replacements(text, first, target)
    missing = missing_protected_values(text, first)
    if not missing:
        return first
    retry_prompt = (
        system_prompt
        + "\nProtected span validation failed on the previous attempt. The retry must include every listed protected span verbatim."
    )
    second = request_translation(build_retry_user_input(text, missing, target), retry_prompt, args)
    if policy_utils.policy_note_leaks(text, second, policy_utils.load_policy_context(getattr(args, "context_file", None))):
        raise RuntimeError("policy_instruction_leak: model output copied document policy notes")
    second = apply_source_aware_replacements(text, second, target)
    still_missing = missing_protected_values(text, second)
    if still_missing:
        raise RuntimeError("Qwen CLI translator omitted protected spans after retry: " + "; ".join(still_missing[:8]))
    return second


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="stdin/stdout Qwen translator adapter for pdf2zh-next CLITranslator.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--target-language", choices=("zh", "en"), default=None,
                        help="翻译目标语言；未传时按系统提示词推断（中译英默认提示词 -> en，否则 zh）。")
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
