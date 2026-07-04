from __future__ import annotations

import json
import os
import time
import http.client
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by translation CLI scripts for OpenAI-compatible local model calls and API key handling."

HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS: dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 1.0,
    "top_k": -1,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}


def should_apply_hymt2_official_generation_defaults(model: str) -> bool:
    value = os.environ.get("PAPER_TRANSLATION_HYMT2_OFFICIAL_PARAMS", "1")
    if value in {"0", "false", "False"}:
        return False
    return "hy-mt2-30b-a3b" in model.lower()


def is_deepseek_chat_target(endpoint: str, model: str, provider: str | None = None) -> bool:
    value = f"{provider or ''} {endpoint} {model}".lower()
    return "deepseek" in value or "api.deepseek.com" in value


def infer_chat_provider(endpoint: str, provider: str | None = None) -> str:
    if provider:
        return provider
    endpoint_lower = endpoint.lower()
    if "api.deepseek.com" in endpoint_lower or endpoint_lower.endswith("/chat/completions"):
        return "openai_compatible"
    return "local_hermes"


def parse_api_key_text(text: str, env_name: str | None = None) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            if env_name and isinstance(data.get(env_name), str):
                return data[env_name].strip()
            for key in ["api_key", "key"]:
                if isinstance(data.get(key), str):
                    return data[key].strip()
    except json.JSONDecodeError:
        pass
    if env_name:
        for line in stripped.splitlines():
            if line.strip().startswith(f"{env_name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    if "=" in stripped and "\n" not in stripped:
        return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return stripped


def resolve_api_key(api_key_env: str | None = None, api_key_file: str | None = None) -> str | None:
    if api_key_env:
        env_value = os.environ.get(api_key_env)
        if env_value:
            return env_value
    if api_key_file:
        path = Path(api_key_file).expanduser()
        if path.exists():
            value = parse_api_key_text(path.read_text(encoding="utf-8"), api_key_env)
            if value:
                return value
    return None


def post_chat(
    *,
    endpoint: str,
    model: str,
    system_prompt: str,
    user_input: str,
    request_timeout_seconds: int = 600,
    provider: str | None = None,
    api_key_env: str | None = None,
    api_key_file: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    extra_body: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_name = infer_chat_provider(endpoint, provider)
    headers = {"Content-Type": "application/json"}
    if provider_name in {"openai", "openai_compatible", "deepseek"}:
        api_key = resolve_api_key(api_key_env, api_key_file)
        if not api_key:
            key_hint = api_key_env or api_key_file or "API key"
            raise RuntimeError(f"Missing API key for {provider_name}: {key_hint}")
        headers["Authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "max_tokens": int(max_tokens or 4096),
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)
        if is_deepseek_chat_target(endpoint, model, provider):
            payload.setdefault("thinking", {"type": "disabled"})
        if should_apply_hymt2_official_generation_defaults(model):
            for key, value in HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS.items():
                payload.setdefault(key, value)
    else:
        payload = {
            "model": model,
            "system_prompt": system_prompt,
            "input": user_input,
        }
        if extra_body:
            payload.update(extra_body)

    last_error: Exception | None = None
    for attempt in range(1, 4):
        body = ""
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f"Request failed: {exc}")
        except http.client.IncompleteRead as exc:
            partial = exc.partial or b""
            last_error = RuntimeError(f"Incomplete response read: {len(partial)} bytes")
        except TimeoutError as exc:
            last_error = RuntimeError(f"Request timed out: {exc}")
        except json.JSONDecodeError:
            last_error = RuntimeError(f"Response is not valid JSON: {body[:500]}")
        if attempt < 3:
            time.sleep(attempt * 2)
    assert last_error is not None
    raise last_error


def extract_text(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    parts.append(content.strip())
        if parts:
            return "\n\n".join(parts)

    for key in ["output", "response", "text"]:
        item = payload.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            text = block.get("text") or block.get("content")
                            if isinstance(text, str) and text.strip():
                                parts.append(text.strip())
                    if parts:
                        return "\n\n".join(parts)
            text = choice.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                reasoning = message.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning.strip():
                    stripped_reasoning = reasoning.strip()
                    return stripped_reasoning
    raise RuntimeError("Unable to extract text content from model response.")


def extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[start : index + 1])
                        except json.JSONDecodeError:
                            break
                        return data if isinstance(data, dict) else None
        start = text.find("{", start + 1)
    return None
