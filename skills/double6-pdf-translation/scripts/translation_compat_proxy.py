#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import layout_role_policy
import policy_utils


DEFAULT_MODEL = ""
DEFAULT_UPSTREAM_BASE_URL = ""
DEFAULT_API_KEY = ""
HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS: dict[str, Any] = {
    "temperature": 0.1,
    "top_p": 1.0,
    "top_k": -1,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}
TRANSIENT_UPSTREAM_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class ProxyConfig:
    model: str = DEFAULT_MODEL
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    api_key: str = DEFAULT_API_KEY
    host: str = "127.0.0.1"
    port: int = 18082
    policy_context_path: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


def strip_json_wrappers(text: str) -> str:
    value = text.strip()
    if value.startswith("<json>"):
        value = value[6:]
    if value.endswith("</json>"):
        value = value[:-7]
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def normalize_jsonish_content(content: str) -> str:
    cleaned = strip_json_wrappers(content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        values = []
        index = 0
        while index < len(cleaned):
            while index < len(cleaned) and cleaned[index].isspace():
                index += 1
            if index >= len(cleaned):
                break
            try:
                parsed_value, end = decoder.raw_decode(cleaned, index)
            except json.JSONDecodeError:
                return cleaned
            values.append(parsed_value)
            index = end
        return json.dumps(values, ensure_ascii=False) if values else cleaned
    if isinstance(parsed, dict) and ("id" in parsed or "output" in parsed):
        return json.dumps([parsed], ensure_ascii=False)
    return json.dumps(parsed, ensure_ascii=False)


def normalize_proxy_payload_for_upstream(payload: dict[str, Any]) -> dict[str, Any]:
    """把上层 OpenAI-compatible 请求改写成上游接口可接受的形态。"""
    normalized = dict(payload)
    if should_apply_hymt2_official_generation_defaults(normalized):
        for key, value in HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS.items():
            normalized.setdefault(key, value)
    return normalized


def is_deepseek_upstream(model: str = "", base_url: str = "") -> bool:
    value = f"{model} {base_url}".lower()
    return "deepseek" in value or "api.deepseek.com" in value


def apply_translation_request_defaults(payload: dict[str, Any], config: ProxyConfig) -> dict[str, Any]:
    normalized = normalize_proxy_payload_for_upstream(payload)
    probe_thinking = str(config.stats.get("_probe_thinking") or "").strip().lower()
    if probe_thinking in {"enabled", "disabled"}:
        normalized["thinking"] = {"type": probe_thinking}
    elif probe_thinking == "omit":
        normalized.pop("thinking", None)
    elif is_deepseek_upstream(config.model, config.upstream_base_url):
        normalized.setdefault("thinking", {"type": "disabled"})
    return normalized


def is_response_format_rejection(status: int, body: bytes) -> bool:
    if status != 400:
        return False
    text = body.decode("utf-8", errors="replace").lower()
    return "response_format" in text and (
        "unavailable" in text
        or "invalid_request_error" in text
        or "must be one of" in text
        or "unsupported" in text
    )


def upstream_retry_attempts(config: ProxyConfig) -> int:
    raw_value = config.stats.get("_probe_upstream_attempts") or os.environ.get("PAPER_TRANSLATION_UPSTREAM_RETRY_ATTEMPTS", "3")
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 3


def upstream_retry_delay(attempt: int) -> float:
    return min(4.0, 0.5 * (2 ** max(attempt - 1, 0)))


def upstream_error_body(error_type: str, message: str) -> bytes:
    return json.dumps(
        {"error": {"type": error_type, "message": message[:1000]}},
        ensure_ascii=False,
    ).encode("utf-8")


def should_apply_hymt2_official_generation_defaults(payload: dict[str, Any]) -> bool:
    value = os.environ.get("PAPER_TRANSLATION_HYMT2_OFFICIAL_PARAMS", "1")
    if value in {"0", "false", "False"}:
        return False
    model = str(payload.get("model") or "").lower()
    return "hy-mt2-30b-a3b" in model


def extract_babeldoc_json_items(prompt: str) -> list[dict[str, Any]] | None:
    marker = "## Here is the input:"
    if marker not in prompt:
        return None
    tail = prompt.split(marker, 1)[1]
    start = tail.find("[")
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(tail[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    items = [item for item in parsed if isinstance(item, dict) and "id" in item and "input" in item]
    return items if len(items) == len(parsed) else None


def extract_babeldoc_plain_fallback_text(prompt: str) -> str | None:
    marker = "Now translate the following text:"
    if marker not in prompt:
        return None
    value = prompt.rsplit(marker, 1)[1].strip()
    return value or None


def clean_plain_translation(text: str) -> str:
    value = strip_json_wrappers(text).strip()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, str):
            value = parsed
        elif isinstance(parsed, dict):
            value = str(parsed.get("output") or parsed.get("translation") or parsed.get("text") or value)
    except json.JSONDecodeError:
        pass
    value = layout_role_policy.strip_rich_text_tags(value)
    return re.sub(r"^(译文|翻译|Translation|原文)\s*[:：]\s*", "", value.strip(), flags=re.I)


def should_translate_to_chinese(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if is_protected_or_passthrough_only(stripped):
        return False
    alpha_chars = len(re.findall(r"[A-Za-z]", stripped))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    if re.fullmatch(r"(ST|TT)\s*[:：]\s*[\u4e00-\u9fff，。、“”‘’；：！？（）《》\s]+", stripped):
        return False
    return alpha_chars > 0 or cjk_chars == 0


def cjk_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


APPROVED_NAME_ONLY_RE = re.compile(
    r"^(?:AI|LLMs?|LLM(?:-[A-Za-z0-9]+)?|GPT(?:-?\d+(?:\.\d+)?[A-Za-z]*)?|"
    r"ChatGPT(?:-?\d+(?:\.\d+)?[A-Za-z]*)?|OpenAI(?:\s+o?\d+[A-Za-z]*)?|"
    r"Claude(?:\s+\d+(?:\.\d+)?)?|DeepSeek(?:-[A-Za-z0-9]+)?|LaTeX|TeX|PDF|API)$",
    re.I,
)


def is_approved_name_only(text: str) -> bool:
    return bool(APPROVED_NAME_ONLY_RE.fullmatch(text.strip()))


def _strip_protected_passthrough_tokens(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"</?style\b[^>]*>", " ", stripped, flags=re.I)
    stripped = re.sub(r"https?://\S+|www\.\S+", " ", stripped, flags=re.I)
    stripped = re.sub(r"\b\d{2}\.\d{4,9}/[-._;()/:A-Za-z0-9]+", " ", stripped)
    stripped = re.sub(r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", " ", stripped)
    stripped = re.sub(r"\{v\d+\}|\{[A-Za-z_][A-Za-z0-9_]*\}|%\d*\$?[sd]|%\w", " ", stripped)
    stripped = re.sub(r"\[[\d,\s;:-]+\]", " ", stripped)
    stripped = re.sub(r"`[^`]*`", " ", stripped)
    stripped = re.sub(
        r"\\(?:begin|end|section|subsection|subsubsection|caption|label|ref|cite|url|textbf|textit|left|right|[A-Za-z]+)"
        r"(?:\{[^{}]*\})?",
        " ",
        stripped,
    )
    stripped = re.sub(r"[\\{}()[\].,;:，。！？、…\s_\-=+*/|<>\"'“”‘’]+", "", stripped)
    return stripped


def is_protected_or_passthrough_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if is_approved_name_only(stripped):
        return True
    if re.fullmatch(r"(ST|TT)\s*[:：]\s*[\u4e00-\u9fff，。、“”‘’；：！？（）《》\s]+", stripped):
        return True
    residue = _strip_protected_passthrough_tokens(stripped)
    if not residue:
        return True
    # LaTeX/placeholder fragments may leave only CJK already translated inside a command.
    if not re.search(r"[A-Za-z]", residue):
        return True
    return False


def is_same_as_input_translation(source: str, translated: str) -> bool:
    source_norm = re.sub(r"\s+", " ", source).strip()
    translated_norm = re.sub(r"\s+", " ", translated).strip()
    if not source_norm or not translated_norm:
        return False
    if source_norm == translated_norm:
        return True
    if should_translate_to_chinese(source) and cjk_char_count(translated) == 0:
        return True
    return False


def looks_partially_untranslated(source: str, translated: str) -> bool:
    if not should_translate_to_chinese(source) or is_protected_or_passthrough_only(source):
        return False
    source_words = re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", visible_text_for_quality(source))
    if len(source_words) < 18:
        return False
    translated_visible = visible_text_for_quality(translated)
    translated_words = re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", translated_visible)
    cjk = cjk_char_count(translated_visible)
    if len(source_words) >= 80 and len(translated_words) >= int(len(source_words) * 0.55) and cjk < int(len(source_words) * 0.75):
        return True
    compact_translated = re.sub(r"\s+", " ", translated_visible)
    for sentence in re.split(r"(?<=[.!?])\s+", visible_text_for_quality(source)):
        words = re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", sentence)
        if len(sentence) >= 100 and len(words) >= 14 and sentence.strip() in compact_translated:
            return True
    return False


def looks_like_task_explanation(text: str) -> bool:
    stripped = visible_text_for_quality(text)
    return bool(
        re.search(
            r"\b(?:we\s+(?:need|are asked|required)|the\s+user\s+provides|given\s+the\s+text|"
            r"task\s+is\s+to\s+translate)\b|(?:我们(?:需要|被要求|要做的是|的任务是)|用户(?:提供|给出)|给定的文本)",
            stripped,
            flags=re.I,
        )
    )


def visible_text_for_quality(text: str) -> str:
    value = re.sub(r"</?style\b[^>]*>", " ", str(text or ""), flags=re.I)
    value = re.sub(r"\{v\d+\}", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _increment_stat(config: ProxyConfig, key: str) -> None:
    config.stats[key] = int(config.stats.get(key, 0)) + 1


def _append_stat_sample(config: ProxyConfig, key: str, sample: dict[str, Any], limit: int = 20) -> None:
    values = config.stats.setdefault(key, [])
    if isinstance(values, list) and len(values) < limit:
        values.append(sample)


def _record_layout_role(config: ProxyConfig, role: str, item: dict[str, Any]) -> None:
    counts = config.stats.setdefault("layout_role_counts", {})
    if isinstance(counts, dict):
        counts[role] = int(counts.get(role, 0)) + 1
    _append_stat_sample(
        config,
        "layout_role_samples",
        {
            "id": item.get("id"),
            "role": role,
            "layout_label": item.get("layout_label"),
            "page": item.get("page") or item.get("page_number"),
            "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
            "source": str(item.get("input") or "")[:180],
        },
        limit=40,
    )


def _record_layout_role_direct_output(config: ProxyConfig, role: str, item: dict[str, Any], output: str) -> None:
    _append_stat_sample(
        config,
        "layout_role_direct_output_samples",
        {
            "id": item.get("id"),
            "role": role,
            "layout_label": item.get("layout_label"),
            "page": item.get("page") or item.get("page_number"),
            "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
            "source": str(item.get("input") or "")[:180],
            "output": output[:180],
        },
        limit=40,
    )


def _item_sample_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "page": item.get("page") or item.get("page_number"),
        "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
        "layout_label": item.get("layout_label"),
    }


def _ledger_quality_status(source: str, output: str) -> str:
    if not output:
        return "empty_output"
    if is_protected_or_passthrough_only(source) and normalize_text_for_ledger(source) == normalize_text_for_ledger(output):
        return "protected_passthrough"
    if is_same_as_input_translation(source, output):
        return "same_as_input_or_non_chinese"
    if looks_partially_untranslated(source, output):
        return "partial_untranslated"
    if looks_like_task_explanation(output):
        return "task_explanation"
    if policy_utils.missing_protected_values(source, output):
        return "protected_value_missing"
    return "translated"


def normalize_text_for_ledger(value: str) -> str:
    return re.sub(r"\s+", " ", layout_role_policy.strip_rich_text_tags(str(value or ""))).strip().lower()


def _record_translation_ledger(
    config: ProxyConfig,
    *,
    source: str,
    output: str,
    role: str = "",
    item: dict[str, Any] | None = None,
    batch_id: int | str | None = None,
    path: str = "",
    status: str | None = None,
) -> None:
    values = config.stats.setdefault("_translation_ledger", [])
    if not isinstance(values, list):
        return
    item = item or {}
    values.append(
        {
            "entry_id": len(values) + 1,
            "batch_id": batch_id,
            "path": path or "unknown",
            "id": item.get("id"),
            "page": item.get("page") or item.get("page_number"),
            "paragraph_debug_id": item.get("paragraph_debug_id") or item.get("debug_id"),
            "layout_role": role or item.get("layout_role"),
            "layout_label": item.get("layout_label"),
            "source": str(source or "")[:5000],
            "output": str(output or "")[:5000],
            "quality_status": status or _ledger_quality_status(source, output),
            "source_norm": normalize_text_for_ledger(source)[:1000],
            "output_has_cjk": cjk_char_count(output) > 0,
        }
    )


def _request_plain_translation(text: str, config: ProxyConfig, policy_prompt: str, retry: bool = False, role: str = "") -> str:
    role_instruction = (
        "This item is ordinary body prose. Translate every human-readable English word or sentence into natural Simplified Chinese. "
        "Do not preserve bibliography-style English unless the input is explicitly a reference entry. "
        if role in {"body_prose", "plain text", "text", "paragraph_hybrid", ""}
        else ""
    )
    retry_instruction = (
        "The previous attempt returned unchanged or partially untranslated source text. Translate all ordinary English prose now. "
        "If the input contains <style id='...'> tags, placeholders, or LaTeX commands, keep those wrappers exactly "
        "and translate only the human-readable English between them. Do not copy the input unless it is only a URL, "
        "citation, placeholder, LaTeX command fragment, code label, or proper name.\n\n"
        if retry
        else ""
    )
    prompt = (
        "Translate the following academic PDF text into Simplified Chinese. "
        "Preserve placeholders such as {v1}, citations like [12], URLs, code, LaTeX commands, "
        "XML/HTML-style tags, model names, and file names exactly. Output only the translation.\n\n"
        "Preserve Latin personal names in the original alphabet. Keep numbered lists as separate items. "
        "Never explain the task, never mention these instructions, and never output analysis.\n\n"
        + role_instruction
        + retry_instruction
        + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
        + f"{text}"
    )
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": int(config.stats.get("_probe_max_tokens") or min(4096, max(256, len(text) * 3))),
    }
    payload = apply_translation_request_defaults(payload, config)
    request = urllib.request.Request(
        chat_completions_url(config.upstream_base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error: Exception | None = None
    attempts = upstream_retry_attempts(config)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=int(config.stats.get("_probe_timeout") or 7200)) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in TRANSIENT_UPSTREAM_STATUS and attempt < attempts:
                _increment_stat(config, "plain_upstream_http_retry")
                time.sleep(upstream_retry_delay(attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                _increment_stat(config, "plain_upstream_network_retry")
                time.sleep(upstream_retry_delay(attempt))
                continue
            raise
    else:
        raise RuntimeError(f"translation upstream request failed: {last_error}")
    message = data["choices"][0]["message"]
    return clean_plain_translation(message.get("content") or message.get("reasoning_content") or "")


def call_plain_translation(
    text: str,
    config: ProxyConfig | None = None,
    policy_prompt: str = "",
    *,
    record_ledger: bool = True,
    ledger_item: dict[str, Any] | None = None,
    ledger_batch_id: int | str | None = None,
    ledger_path: str = "plain",
) -> str:
    active = config or ProxyConfig(
        model=os.environ.get("LOCAL_TRANSLATION_MODEL", DEFAULT_MODEL),
        upstream_base_url=os.environ.get("LOCAL_TRANSLATION_BASE_URL", DEFAULT_UPSTREAM_BASE_URL).rstrip("/"),
        api_key=os.environ.get("LOCAL_TRANSLATION_API_KEY", DEFAULT_API_KEY),
    )
    role = layout_role_policy.classify_babeldoc_item({"id": "plain", "input": text})
    direct_output = layout_role_policy.direct_output_for_role(role, text)
    if direct_output is not None:
        _increment_stat(active, "plain_layout_role_direct_output")
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=direct_output,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="layout_role_direct_output",
            )
        return direct_output
    if is_protected_or_passthrough_only(text):
        _increment_stat(active, "protected_passthrough")
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=text,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="protected_passthrough",
            )
        return text
    if not should_translate_to_chinese(text):
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=text,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="no_translation_needed",
            )
        return text
    translated = _request_plain_translation(text, active, policy_prompt, role=role)
    if translated:
        text_quality_failure = (
            is_same_as_input_translation(text, translated)
            or looks_partially_untranslated(text, translated)
            or looks_like_task_explanation(translated)
        )
        protected_value_failure = bool(policy_utils.missing_protected_values(text, translated))
    else:
        text_quality_failure = False
        protected_value_failure = False
    if translated and (text_quality_failure or protected_value_failure):
        if text_quality_failure:
            _append_stat_sample(active, "same_as_input_candidates", {"source": text[:160], "output": translated[:160]})
            _increment_stat(active, "same_as_input_retry")
        if protected_value_failure:
            _append_stat_sample(active, "protected_value_candidates", {"source": text[:160], "output": translated[:160]})
            _increment_stat(active, "protected_value_retry")
        retry_translated = _request_plain_translation(text, active, policy_prompt, retry=True, role=role)
        retry_text_quality_failure = (
            retry_translated
            and (
                is_same_as_input_translation(text, retry_translated)
                or looks_partially_untranslated(text, retry_translated)
                or looks_like_task_explanation(retry_translated)
            )
        )
        retry_protected_value_failure = bool(
            retry_translated and policy_utils.missing_protected_values(text, retry_translated)
        )
        if retry_translated and not retry_text_quality_failure and not retry_protected_value_failure:
            if text_quality_failure:
                _increment_stat(active, "same_as_input_retry_success")
            if protected_value_failure:
                _increment_stat(active, "protected_value_retry_success")
            translated = retry_translated
        else:
            if text_quality_failure:
                _increment_stat(active, "same_as_input_retry_failed")
            if protected_value_failure:
                _increment_stat(active, "protected_value_retry_failed")
    if not translated:
        _increment_stat(active, "empty_translation_fallback")
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=text,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="empty_translation_fallback",
            )
        return text
    if should_translate_to_chinese(text) and cjk_char_count(translated) == 0 and re.search(r"[A-Za-z]{4,}", translated):
        _increment_stat(active, "non_chinese_translation_fallback")
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=text,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="non_chinese_translation_fallback",
            )
        return text
    literal_repairs = policy_utils.policy_literal_repairs(text, translated)
    if literal_repairs:
        for _repair in literal_repairs:
            _increment_stat(active, "policy_literal_repair")
    translated = policy_utils.apply_source_aware_replacements(text, translated)
    translated = policy_utils.restore_missing_protected_values(text, translated)
    try:
        final_output = policy_utils.enforce_protected_values(text, translated)
    except RuntimeError:
        _increment_stat(active, "protected_span_fallback")
        if record_ledger:
            _record_translation_ledger(
                active,
                source=text,
                output=text,
                role=role,
                item=ledger_item,
                batch_id=ledger_batch_id,
                path=ledger_path,
                status="protected_span_fallback",
            )
        return text
    if record_ledger:
        _record_translation_ledger(
            active,
            source=text,
            output=final_output,
            role=role,
            item=ledger_item,
            batch_id=ledger_batch_id,
            path=ledger_path,
        )
    return final_output


def synthesize_babeldoc_json_response(payload: dict[str, Any], items: list[dict[str, Any]], config: ProxyConfig | None = None) -> bytes:
    active = config or ProxyConfig()
    policy_context = policy_utils.load_policy_context(active.policy_context_path)
    _increment_stat(active, "json_batch_requests")
    batch_id = int(active.stats.get("json_batch_requests", 0))
    active.stats["json_batch_items"] = int(active.stats.get("json_batch_items", 0)) + len(items)
    translated = []
    references_mode = False
    for item in items:
        source = str(item.get("input", ""))
        role = layout_role_policy.classify_babeldoc_item(item, references_mode=references_mode)
        _record_layout_role(active, role, item)
        if role == "references_heading":
            references_mode = True
        elif references_mode and layout_role_policy.is_open_access_license(source):
            references_mode = False
        direct_output = layout_role_policy.direct_output_for_role(role, source)
        if direct_output is not None:
            direct_output = layout_role_policy.strip_rich_text_tags(direct_output)
            _increment_stat(active, "json_batch_layout_role_direct_output")
            _record_layout_role_direct_output(active, role, item, direct_output)
            _record_translation_ledger(
                active,
                source=source,
                output=direct_output,
                role=role,
                item=item,
                batch_id=batch_id,
                path="json_batch",
                status="layout_role_direct_output",
            )
            translated.append({"id": item["id"], "output": direct_output})
            continue
        if is_protected_or_passthrough_only(source):
            _increment_stat(active, "json_batch_protected_passthrough")
            _record_translation_ledger(
                active,
                source=source,
                output=source,
                role=role,
                item=item,
                batch_id=batch_id,
                path="json_batch",
                status="protected_passthrough",
            )
            translated.append({"id": item["id"], "output": source})
            continue
        policy_prompt = policy_utils.build_policy_context_prompt(policy_context, source_text=source)
        role_prompt = layout_role_policy.role_prompt(role)
        policy_prompt = "\n".join(part for part in [policy_prompt, role_prompt] if part.strip())
        output = call_plain_translation(source, active, policy_prompt=policy_prompt, record_ledger=False)
        output = layout_role_policy.postprocess_translation_for_role(role, source, output)
        output = layout_role_policy.strip_rich_text_tags(output)
        if should_translate_to_chinese(source) and (
            is_same_as_input_translation(source, output)
            or looks_partially_untranslated(source, output)
            or looks_like_task_explanation(output)
        ):
            _increment_stat(active, "json_batch_same_as_input_after_retry")
            _append_stat_sample(
                active,
                "json_batch_same_as_input_samples",
                {**_item_sample_metadata(item), "source": source[:160], "output": output[:160]},
            )
        _record_translation_ledger(
            active,
            source=source,
            output=output,
            role=role,
            item=item,
            batch_id=batch_id,
            path="json_batch",
        )
        translated.append({"id": item["id"], "output": output})
    response = {
        "id": "translation-json-compat-proxy",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", active.model),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(translated, ensure_ascii=False)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return json.dumps(response, ensure_ascii=False).encode("utf-8")


def synthesize_plain_role_response(payload: dict[str, Any], source: str, output: str, config: ProxyConfig) -> bytes:
    _increment_stat(config, "plain_layout_role_intercept")
    response = {
        "id": "translation-plain-layout-role-proxy",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", config.model),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    _append_stat_sample(config, "plain_layout_role_intercept_samples", {"source": source[:180], "output": output[:180]}, limit=40)
    return json.dumps(response, ensure_ascii=False).encode("utf-8")


class _TranslationCompatHandler(BaseHTTPRequestHandler):
    server_version = "TranslationCompatProxy/1.0"

    @property
    def config(self) -> ProxyConfig:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return
        user_content = "\n".join(
            str(message.get("content", ""))
            for message in payload.get("messages", [])
            if isinstance(message, dict)
        )
        items = extract_babeldoc_json_items(user_content)
        if items:
            try:
                self._send_json_bytes(synthesize_babeldoc_json_response(payload, items, self.config))
                return
            except Exception as exc:  # noqa: BLE001 - 代理必须把策略失败显式暴露给后端日志
                body = json.dumps(
                    {
                        "error": {
                            "type": "paper_translation_policy_validation_failed",
                            "message": str(exc)[:500],
                        }
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        plain_source = extract_babeldoc_plain_fallback_text(user_content)
        if plain_source:
            role = layout_role_policy.classify_babeldoc_item({"id": "plain_fallback", "input": plain_source})
            direct_output = layout_role_policy.direct_output_for_role(role, plain_source)
            if direct_output is not None:
                direct_output = layout_role_policy.strip_rich_text_tags(direct_output)
                plain_item = {"id": "plain_fallback", "input": plain_source, "layout_label": "plain_fallback"}
                _record_layout_role(self.config, role, plain_item)
                _record_translation_ledger(
                    self.config,
                    source=plain_source,
                    output=direct_output,
                    role=role,
                    item=plain_item,
                    path="plain_fallback",
                    status="layout_role_direct_output",
                )
                self._send_json_bytes(synthesize_plain_role_response(payload, plain_source, direct_output, self.config))
                return
        payload = apply_translation_request_defaults(payload, self.config)
        requested_json = bool(payload.get("response_format"))
        _increment_stat(self.config, "passthrough_requests")
        if requested_json:
            _increment_stat(self.config, "passthrough_json_requests")
        status, body = self._post_upstream_payload(payload)
        if is_response_format_rejection(status, body) and requested_json:
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            _increment_stat(self.config, "passthrough_json_text_fallback_requests")
            self.config.stats["last_response_format_error_body"] = body.decode("utf-8", errors="replace")[:1000]
            status, body = self._post_upstream_payload(retry_payload)
            self.config.stats[f"passthrough_json_text_fallback_status_{status}"] = (
                int(self.config.stats.get(f"passthrough_json_text_fallback_status_{status}", 0)) + 1
            )
        self.config.stats[f"passthrough_status_{status}"] = int(self.config.stats.get(f"passthrough_status_{status}", 0)) + 1
        if status >= 400:
            self.config.stats["last_upstream_error_status"] = status
            self.config.stats["last_upstream_error_body"] = body.decode("utf-8", errors="replace")[:1000]
        if status == 200:
            body = self._normalize_openai_response(body, requested_json)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json_bytes(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _post_upstream_payload(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        request = urllib.request.Request(
            chat_completions_url(self.config.upstream_base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": self.headers.get("Authorization", f"Bearer {self.config.api_key}"),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        attempts = upstream_retry_attempts(self.config)
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=7200) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                body = exc.read()
                if exc.code in TRANSIENT_UPSTREAM_STATUS and attempt < attempts:
                    _increment_stat(self.config, "passthrough_upstream_http_retry")
                    time.sleep(upstream_retry_delay(attempt))
                    continue
                return exc.code, body
            except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected, OSError) as exc:
                if attempt < attempts:
                    _increment_stat(self.config, "passthrough_upstream_network_retry")
                    time.sleep(upstream_retry_delay(attempt))
                    continue
                return 502, upstream_error_body("upstream_network_error", str(exc))
        return 502, upstream_error_body("upstream_network_error", "upstream request failed after retries")

    def _normalize_openai_response(self, body: bytes, requested_json: bool) -> bytes:
        try:
            data = json.loads(body.decode("utf-8"))
            usage = data.setdefault("usage", {})
            for key in ["prompt_tokens", "completion_tokens", "total_tokens"]:
                value = usage.get(key)
                usage[key] = value if isinstance(value, (int, float)) else 0
            if requested_json:
                message = data["choices"][0]["message"]
                content = message.get("content") or message.get("reasoning_content") or ""
                message["content"] = normalize_jsonish_content(content)
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception:
            return body


class TranslationCompatServer(ThreadingHTTPServer):
    config: ProxyConfig
    stats: dict[str, Any]


def start_translation_compat_proxy(config: ProxyConfig) -> TranslationCompatServer:
    if not config.model.strip() or not config.upstream_base_url.strip() or not config.api_key.strip():
        raise ValueError("translation compatibility proxy requires model, upstream_base_url, and api_key.")
    config.stats.clear()
    try:
        server = TranslationCompatServer((config.host, config.port), _TranslationCompatHandler)
    except OSError:
        if config.port == 0:
            raise
        config.stats["port_fallback_from"] = config.port
        server = TranslationCompatServer((config.host, 0), _TranslationCompatHandler)
        config.port = int(server.server_address[1])
        config.stats["port_fallback_to"] = config.port
    else:
        config.port = int(server.server_address[1])
    server.config = config
    server.stats = config.stats
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local translation compatibility proxy used by the PDF translation pipeline.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local host to bind.")
    parser.add_argument("--port", type=int, default=18082, help="Local port to bind; falls back to a free port if busy.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name passed through to the upstream endpoint.")
    parser.add_argument("--upstream-base-url", default=DEFAULT_UPSTREAM_BASE_URL, help="OpenAI-compatible upstream base URL.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key for upstream requests.")
    parser.add_argument("--policy-context-path", help="Optional policy context JSON path for layout-role counters.")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the proxy and block until interrupted. Without this flag the command prints help and exits.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.serve:
        parser.print_help()
        return 0
    if not args.model.strip() or not args.upstream_base_url.strip() or not args.api_key.strip():
        parser.error("--model, --upstream-base-url, and --api-key are required when --serve is used.")
    server = start_translation_compat_proxy(
        ProxyConfig(
            model=args.model,
            upstream_base_url=args.upstream_base_url,
            api_key=args.api_key,
            host=args.host,
            port=args.port,
            policy_context_path=args.policy_context_path,
        )
    )
    print(f"translation compatibility proxy listening at http://{server.config.host}:{server.config.port}/v1", flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    try:
        while not stop.is_set():
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    server.shutdown()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
