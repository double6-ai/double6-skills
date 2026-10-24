#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from pathlib import Path
from collections import Counter

import layout_role_policy
import policy_utils
import upstream_identity


DEFAULT_MODEL = None
DEFAULT_UPSTREAM_BASE_URL = None
DEFAULT_API_KEY = None
HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS: dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 1.0,
    "top_k": -1,
    "repetition_penalty": 1.0,
    "max_tokens": 4096,
}


@dataclass
class ProxyConfig:
    model: str = DEFAULT_MODEL
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    api_key: str = DEFAULT_API_KEY
    host: str = "127.0.0.1"
    port: int = 18082
    policy_context_path: str | None = None
    transport: str = 'openai_compatible'
    trace_dir: str | None = None
    source_cache_context_ref: dict | None = None
    source_cache_mode: str | None = None
    source_cache_coverage_ref: dict | None = None
    source_cache_render_id: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    rejected_source_shas: set[str] = field(default_factory=set)

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


def normalize_hymt_payload_for_upstream(payload: dict[str, Any]) -> dict[str, Any]:
    """把上层 OpenAI-compatible 请求改写成本地 hy-mt2 接受的形态。"""
    normalized = dict(payload)
    normalized.pop("thinking", None)
    if should_apply_hymt2_official_generation_defaults(normalized):
        for key, value in HYMT2_30B_OFFICIAL_GENERATION_DEFAULTS.items():
            normalized.setdefault(key, value)
    response_format = normalized.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        normalized["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": {"type": "object"},
                "strict": False,
            },
        }
    return normalized


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
    # pdfmathtranslate-next's current OpenAITranslator wraps each complete
    # source string in this fixed single-message template. Accept only the
    # literal suffix after its explicit ``Input:`` boundary; arbitrary prompts
    # still fail closed below.
    current_template = re.fullmatch(
        r"You are a professional,authentic machine translation engine\.\n\n"
        r";; Treat next line as plain text input and translate it into ([A-Za-z0-9_-]+), output translation ONLY\. "
        r"If translation is unnecessary \(e\.g\. proper nouns, codes, \{\{1\}\}, etc\. \), return the original text\. "
        r"NO explanations\. NO notes\. Input:\n\n([\s\S]+)",
        prompt,
    )
    if current_template:
        source = current_template.group(2)
        return source if source.strip() else None
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
    return re.sub(r"^(译文|翻译|Translation|原文)\s*[:：]\s*", "", value.strip(), flags=re.I)


def _has_non_cjk_source_script(text: str) -> bool:
    """Recognize scripts that the Han-only heuristic otherwise mistakes for Chinese."""
    if re.search(r"[\u3040-\u30ff\uff65-\uff9f\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]", text):
        return True
    return any(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)


def should_translate_to_chinese(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    has_non_cjk_source_script = _has_non_cjk_source_script(stripped)
    if is_protected_or_passthrough_only(stripped) and not has_non_cjk_source_script:
        return False
    alpha_chars = len(re.findall(r"[A-Za-z]", stripped))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    if re.fullmatch(r"(ST|TT)\s*[:：]\s*[\u4e00-\u9fff，。、“”‘’；：！？（）《》\s]+", stripped):
        return False
    return has_non_cjk_source_script or alpha_chars > 0 or cjk_chars == 0


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
    # Kana, Hangul, and RTL letters identify source scripts that the residue
    # check below would otherwise treat as already-translated CJK/protected text.
    if _has_non_cjk_source_script(stripped):
        return False
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


def _request_plain_translation(text: str, config: ProxyConfig, policy_prompt: str, retry: bool = False) -> str:
    if not config.model or not config.upstream_base_url:
        raise ValueError("translation_requires_explicit_model_and_base_url")
    retry_instruction = (
        "The previous attempt returned unchanged or partially untranslated source text. Translate all ordinary English prose now. "
        "If the input contains <style id='...'> tags, placeholders, or LaTeX commands, keep those wrappers exactly "
        "and translate only the human-readable English between them. Do not copy the input unless it is only a URL, "
        "citation, placeholder, LaTeX command fragment, code label, or proper name.\n\n"
        if retry
        else ""
    )
    control = (
        "Translate the following academic PDF text into Simplified Chinese. "
        "Preserve placeholders such as {v1}, citations like [12], URLs, code, LaTeX commands, "
        "XML/HTML-style tags, model names, and file names exactly. Output only the translation.\n\n"
        "Preserve Latin personal names in the original alphabet. Keep bibliography entries and "
        "language-comparison examples unchanged unless the caller provides a role-specific mapping. "
        "Keep numbered lists as separate items.\n\n"
        + retry_instruction
        + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
    )
    payload = {
        "model": config.model,
        # Installed Hy template encodes system and user with distinct role tokens.
        # User content contains the complete literal source and no control prose.
        "messages": [{"role": "system", "content": control}, {"role": "user", "content": text}],
        "stream": False,
        "max_tokens": min(4096, max(256, len(text) * 3)),
    }
    cache=None;cache_request=None;editorial=None;transport_ref=None;cache_read_refs=None
    if config.source_cache_mode:
        from pdf_source_cache import source_cache
        try:
            cache=source_cache(config.source_cache_context_ref,config.source_cache_mode)
            if cache.context['model']!=config.model or cache.context['endpoint']!=config.upstream_base_url:
                raise ValueError('source cache actual model/endpoint changed')
            cache_request=cache.request(text,control,policy_prompt,retry)
            if config.source_cache_mode=='write':cache.verify_coverage(config.source_cache_coverage_ref,cache_request)
            if config.source_cache_mode=='collect':
                cache.collect(cache_request);_increment_stat(config,'source_only_collection_requests')
                # Source echo is diagnostic only; caller must stop before typesetting and disable backend cache.
                return text
        except Exception:
            _increment_stat(config,'source_cache_rejected');raise
    if cache and cache.protocol == 'pdf_whole_group_parent_cache_v1':
        from pdf_source_cache import GROUP_RENDER_CONTROL,render_invocation_id
        if config.source_cache_mode != 'read':
            raise ValueError('whole groups warm through explicit group stage only')
        try:
            if not isinstance(config.source_cache_render_id,str):
                raise ValueError('actual proxy render invocation ID required')
            render_id=render_invocation_id(config.source_cache_render_id)
            output, provenance = cache.render_literal(text, GROUP_RENDER_CONTROL, retry)
            validate_source_output(config, text, output)
        except Exception:
            _increment_stat(config, 'source_cache_rejected'); raise
        _increment_stat(config, 'current_attempt_cache_hits')
        _increment_stat(config, 'whole_group_projection_hits')
        directory = Path(config.trace_dir or os.environ['PAPER_TRANSLATION_PROXY_TRACE_DIR'])
        directory.mkdir(parents=True, exist_ok=True)
        with (directory/'requests.jsonl').open('a') as file:
            file.write(json.dumps({'render_id':render_id,'source_literal':text, 'source_sha256':source_identity(text),
                'render_control':GROUP_RENDER_CONTROL, 'effective_output':output,
                'effective_output_origin':provenance['origin'], 'provenance':provenance,
                'new_provider_calls':0, 'parent_response_is_not_child_response':True},ensure_ascii=False)+'\n')
        return output
    trace_dir = config.trace_dir or os.environ.get("PAPER_TRANSLATION_PROXY_TRACE_DIR")
    if config.transport == 'lmstudio_native_chat_v1':
        from lmstudio_native import native_payload,post_native
        payload=native_payload(config.model,control,text)
        transport_events=[];response_bodies=[]
        def event(row):
            transport_events.append(row)
            if trace_dir:
                directory=Path(trace_dir);directory.mkdir(parents=True,exist_ok=True)
                with (directory/'transport.jsonl').open('a',encoding='utf-8') as file:
                    file.write(json.dumps({'source_sha256':source_identity(text),**row})+'\n')
        try:
            if cache and config.source_cache_mode=='read':
                data,editorial=cache.read(cache_request);_increment_stat(config,'current_attempt_cache_hits')
                cache_read_refs=cache.last_read_refs
            else:
                if cache and config.source_cache_mode=='write' and not trace_dir:
                    raise ValueError('actual native RAW trace directory required for warming')
                _increment_stat(config,'actual_provider_calls')
                data=post_native(base_url=config.upstream_base_url,model=config.model,system=control,source=text,
                                 attempt_callback=event,response_callback=response_bodies.append)
                if cache and config.source_cache_mode=='write':
                    from pdf_source_cache import write_new,file_ref
                    from uuid import uuid4
                    directory=Path(trace_dir);directory.mkdir(parents=True,exist_ok=True)
                    raw_path=directory/('RAW_NATIVE_CALL_'+uuid4().hex+'.json')
                    if len(response_bodies)!=1:raise ValueError('one actual native HTTP response body required')
                    write_new(raw_path,{'context_ref':cache.context_ref,'request':cache_request,'payload':payload,
                        'endpoint':config.upstream_base_url.rstrip('/').removesuffix('/v1')+'/api/v1/chat',
                        'response':data,'response_body':response_bodies[0],'events':transport_events})
                    transport_ref=file_ref(raw_path)
        except Exception:
            _increment_stat(config,'source_cache_rejected' if cache and config.source_cache_mode=='read' else 'native_response_rejected');raise
    elif config.transport == 'openai_compatible':
        payload = normalize_hymt_payload_for_upstream(payload)
        request = urllib.request.Request(
        chat_completions_url(config.upstream_base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **({"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}),
            "Content-Type": "application/json",
        },
        method="POST",
    )
        with urllib.request.urlopen(request, timeout=110) as response:
            data = json.loads(response.read().decode("utf-8"))
    else:raise ValueError('unsupported explicit translation transport')
    if trace_dir:
        directory = Path(trace_dir)
        directory.mkdir(parents=True, exist_ok=True)
        record = {"source_sha256": source_identity(text), "source_literal": text,
                  "roles": {"system": "translation controls and source-bound policy", "user": "literal source"},
                  "request": payload, "response": data, "retry": retry,
                  "effective_output_origin":"coordinator_full_paragraph_editorial" if editorial else ("current_attempt_cache_native" if cache and config.source_cache_mode=="read" else "native_provider"),
                  "editorial":editorial,"transport_raw_ref":transport_ref,"cache_read_refs":cache_read_refs}
        with (directory / "requests.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    if config.transport=='lmstudio_native_chat_v1':
        from lmstudio_native import native_text
        try:output=native_text(data,config.model)
        except ValueError:
            _increment_stat(config,'native_response_rejected');raise
        stats=data['stats'];usage={'prompt_tokens':stats['input_tokens'],'completion_tokens':stats['total_output_tokens'],'total_tokens':stats['input_tokens']+stats['total_output_tokens'],'reasoning_output_tokens':stats['reasoning_output_tokens']}
    else:
        usage=data.get('usage',{})
        message = data["choices"][0]["message"]
        output = clean_plain_translation(message.get("content") or message.get("reasoning_content") or "")
    if editorial:
        output=editorial['output'];_increment_stat(config,'current_attempt_editorial_revision_hits')
    if cache and config.source_cache_mode=='read':usage={}
    for key, value in usage.items():
        if isinstance(value, (int, float)):
            config.stats["actual_upstream_" + key] = config.stats.get("actual_upstream_" + key, 0) + value
    # Exact control copies absent from the literal source are protocol leakage.
    if any(len(line.strip()) >= 40 and line.strip() in output and line.strip() not in text
           for line in control.splitlines()):
        reject_source(config, text, "instruction_leak: output contains source-absent control message")
    if cache and config.source_cache_mode=='write':
        validate_source_output(config,text,output)
        try:cache.store(cache_request,data,config.source_cache_coverage_ref,transport_ref)
        except Exception:
            _increment_stat(config,'source_cache_rejected');raise
    return output


def source_identity(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gate_identity(text: str) -> str:
    # Fallback formatting wrappers/line breaks must not erase a prior rejection.
    return source_identity(re.sub(r"\s+", " ", visible_text_for_quality(text)).strip())


def reject_source(config: ProxyConfig, text: str, reason: str) -> None:
    config.rejected_source_shas.add(source_identity(text))
    config.rejected_source_shas.add(gate_identity(text))
    _increment_stat(config, "policy_instruction_leak_rejected")
    raise RuntimeError(reason)


def validate_source_output(config: ProxyConfig, source: str, output: str | None) -> None:
    if {source_identity(source), gate_identity(source)} & config.rejected_source_shas:
        raise RuntimeError("instruction_leak: this source was already rejected in this attempt")
    if output is None:
        return
    if policy_utils.policy_note_leaks(source, output, policy_utils.load_policy_context(config.policy_context_path)):
        reject_source(config, source, "policy_instruction_leak: model output copied document policy notes")
    expected = Counter(re.findall(r"\{v\d+\}", source))
    actual = Counter(re.findall(r"\{v\d+\}", output))
    if actual != expected:
        _increment_stat(config, "format_placeholder_rejected")
        raise RuntimeError("format_placeholder_mismatch: " + json.dumps(
            {"expected": expected, "actual": actual}, ensure_ascii=False))


def is_group_projection(config):
    if not config.source_cache_mode: return False
    from pdf_source_cache import bound_json, GROUP_PROTOCOLS
    return bound_json(config.source_cache_context_ref).get('protocol') in GROUP_PROTOCOLS


def call_hymt_plain_translation(text: str, config: ProxyConfig | None = None, policy_prompt: str = "") -> str:
    active = config or ProxyConfig(
        model=os.environ.get("LOCAL_TRANSLATION_MODEL", DEFAULT_MODEL),
        upstream_base_url=(os.environ.get("LOCAL_TRANSLATION_BASE_URL", DEFAULT_UPSTREAM_BASE_URL) or "").rstrip("/"),
        api_key=os.environ.get("LOCAL_TRANSLATION_API_KEY", DEFAULT_API_KEY),
    )
    validate_source_output(active, text, None)
    if is_group_projection(active):
        return _request_plain_translation(text, active, "")
    role = layout_role_policy.classify_babeldoc_item({"id": "plain", "input": text})
    direct_output = layout_role_policy.direct_output_for_role(role, text)
    if direct_output is not None:
        _increment_stat(active, "plain_layout_role_direct_output")
        return direct_output
    if is_protected_or_passthrough_only(text):
        _increment_stat(active, "protected_passthrough")
        return text
    if not should_translate_to_chinese(text):
        return text
    translated = _request_plain_translation(text, active, policy_prompt)
    validate_source_output(active, text, translated)
    if translated and (is_same_as_input_translation(text, translated) or looks_partially_untranslated(text, translated)):
        _append_stat_sample(active, "same_as_input_candidates", {"source": text[:160], "output": translated[:160]})
        _increment_stat(active, "same_as_input_retry")
        retry_translated = _request_plain_translation(text, active, policy_prompt, retry=True)
        validate_source_output(active, text, retry_translated)
        if retry_translated and not is_same_as_input_translation(text, retry_translated) and not looks_partially_untranslated(text, retry_translated):
            _increment_stat(active, "same_as_input_retry_success")
            translated = retry_translated
        else:
            _increment_stat(active, "same_as_input_retry_failed")
    if not translated:
        _increment_stat(active, "empty_translation_fallback")
        return text
    if should_translate_to_chinese(text) and cjk_char_count(translated) == 0 and re.search(r"[A-Za-z]{4,}", translated):
        _increment_stat(active, "non_chinese_translation_fallback")
        return text
    literal_repairs = policy_utils.policy_literal_repairs(text, translated)
    if literal_repairs:
        for _repair in literal_repairs:
            _increment_stat(active, "policy_literal_repair")
    translated = policy_utils.apply_source_aware_replacements(text, translated)
    try:
        return policy_utils.enforce_protected_values(text, translated)
    except RuntimeError:
        _increment_stat(active, "protected_span_fallback")
        return text


def synthesize_babeldoc_json_response(payload: dict[str, Any], items: list[dict[str, Any]], config: ProxyConfig | None = None) -> bytes:
    active = config or ProxyConfig()
    before = dict(active.stats)
    policy_context = policy_utils.load_policy_context(active.policy_context_path)
    _increment_stat(active, "json_batch_requests")
    active.stats["json_batch_items"] = int(active.stats.get("json_batch_items", 0)) + len(items)
    translated = []
    references_mode = False
    for item in items:
        source = str(item.get("input", ""))
        validate_source_output(active, source, None)
        if is_group_projection(active):
            translated.append({"id":item["id"],"output":_request_plain_translation(source,active,"")})
            continue
        role = layout_role_policy.classify_babeldoc_item(item, references_mode=references_mode)
        _record_layout_role(active, role, item)
        if role == "references_heading":
            references_mode = True
        elif references_mode and layout_role_policy.is_open_access_license(source):
            references_mode = False
        direct_output = layout_role_policy.direct_output_for_role(role, source)
        if direct_output is not None:
            _increment_stat(active, "json_batch_layout_role_direct_output")
            _record_layout_role_direct_output(active, role, item, direct_output)
            translated.append({"id": item["id"], "output": direct_output})
            continue
        if is_protected_or_passthrough_only(source):
            _increment_stat(active, "json_batch_protected_passthrough")
            translated.append({"id": item["id"], "output": source})
            continue
        policy_prompt = policy_utils.build_policy_context_prompt(policy_context, source_text=source)
        role_prompt = layout_role_policy.role_prompt(role)
        policy_prompt = "\n".join(part for part in [policy_prompt, role_prompt] if part.strip())
        output = call_hymt_plain_translation(source, active, policy_prompt=policy_prompt)
        output = layout_role_policy.postprocess_translation_for_role(role, source, output)
        validate_source_output(active, source, output)
        if should_translate_to_chinese(source) and (is_same_as_input_translation(source, output) or looks_partially_untranslated(source, output)):
            _increment_stat(active, "json_batch_same_as_input_after_retry")
            _append_stat_sample(
                active,
                "json_batch_same_as_input_samples",
                {**_item_sample_metadata(item), "source": source[:160], "output": output[:160]},
            )
        translated.append({"id": item["id"], "output": output})
    response = {
        "id": "hymt-json-compat-proxy",
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
        "usage": upstream_usage_since(active,before),
    }
    return json.dumps(response, ensure_ascii=False).encode("utf-8")


def upstream_usage_since(config, before):
    # Native protocol provides strict numeric actual usage; direct role output has no call.
    return {key:config.stats.get('actual_upstream_'+key,0)-before.get('actual_upstream_'+key,0)
            for key in ('prompt_tokens','completion_tokens','total_tokens')}


def synthesize_plain_role_response(payload: dict[str, Any], source: str, output: str, config: ProxyConfig, usage=None) -> bytes:
    _increment_stat(config, "plain_layout_role_intercept")
    response = {
        "id": "hymt-plain-layout-role-proxy",
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
        "usage": usage if usage is not None else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    _append_stat_sample(config, "plain_layout_role_intercept_samples", {"source": source[:180], "output": output[:180]}, limit=40)
    return json.dumps(response, ensure_ascii=False).encode("utf-8")


class _HyMTJsonCompatHandler(BaseHTTPRequestHandler):
    server_version = "HyMTJsonCompatProxy/1.0"

    @property
    def config(self) -> ProxyConfig:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def upstream_identity(self) -> dict:
        """本代理实际转发到的真实上游身份（规范化地址、上游模型、传输方式；不含凭据）。"""
        return upstream_identity.build_identity(self.config.upstream_base_url, self.config.model, self.config.transport)

    def end_headers(self) -> None:
        # Double6 Skills，2026-10-24：每个响应（含 send_error）都声明真实上游身份，后端据此绑定/核对翻译缓存身份。
        self.send_header(upstream_identity.IDENTITY_HEADER, upstream_identity.encode_identity(self.upstream_identity()))
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/").endswith(upstream_identity.IDENTITY_PATH):
            body = upstream_identity.encode_identity(self.upstream_identity()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

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
        if is_group_projection(self.config):
            # The explicit reviewed-group route accepts only the actual sole-user
            # llm_translate packet, never legacy prompt extraction or fallbacks.
            try:
                messages=payload.get('messages')
                if not isinstance(messages,list) or len(messages)!=1 or not isinstance(messages[0],dict) or messages[0].get('role')!='user' or not isinstance(messages[0].get('content'),str):
                    raise ValueError('one literal source packet user message required')
                packet=json.loads(messages[0]['content'])
                from pdf_source_cache import validate_group_backend_packet
                cache=validate_group_backend_packet(packet,self.config.source_cache_context_ref,self.config.source_cache_render_id)
                if self.config.source_cache_mode!='read' or cache.context['model']!=self.config.model or cache.context['endpoint']!=self.config.upstream_base_url:
                    raise ValueError('current group read model/endpoint required')
                output,provenance=cache.render_literal(packet['source_literal'],packet['render_control'],source_paragraph_sha256=packet['source_paragraph_sha256'])
                validate_source_output(self.config,packet['source_literal'],output)
                _increment_stat(self.config,'current_attempt_cache_hits')
                _increment_stat(self.config,'whole_group_projection_hits')
                status=200
                body=synthesize_plain_role_response(payload,packet['source_literal'],output,self.config,{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0})
                event={'packet':packet,'provenance':provenance,'effective_output':output,'effective_output_origin':provenance['origin'],'new_provider_calls':0,'parent_response_is_not_child_response':True}
            except Exception as exc:
                _increment_stat(self.config,'source_protocol_rejected')
                _increment_stat(self.config,'source_cache_rejected')
                status=400
                body=json.dumps({'error':{'type':'whole_group_source_packet_rejected','message':str(exc)[:500]}}).encode()
                event={'error':str(exc),'new_provider_calls':0}
            directory=Path(self.config.trace_dir or os.environ['PAPER_TRANSLATION_PROXY_TRACE_DIR'])
            directory.mkdir(parents=True,exist_ok=True)
            event.update({'render_id':self.config.source_cache_render_id,'status':status,'request_body':raw_body.decode('utf-8'),'request_sha256':hashlib.sha256(raw_body).hexdigest(),'response_body':body.decode('utf-8'),'response_sha256':hashlib.sha256(body).hexdigest(),'context_ref':self.config.source_cache_context_ref})
            with (directory/'group_http_dispatch.jsonl').open('a') as file:
                file.write(json.dumps(event,ensure_ascii=False)+'\n')
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            try:
                before = dict(self.config.stats)
                policy = policy_utils.build_policy_context_prompt(
                    policy_utils.load_policy_context(self.config.policy_context_path), source_text=plain_source)
                output = call_hymt_plain_translation(plain_source, self.config, policy_prompt=policy)
                validate_source_output(self.config, plain_source, output)
                self._send_json_bytes(synthesize_plain_role_response(payload, plain_source, output, self.config,upstream_usage_since(self.config,before)))
                return
            except Exception as exc:
                self.send_error(502, str(exc)[:300])
                return
        # Unidentified caller prompts cannot establish a literal source boundary.
        # They must not bypass the same source-bound translation/quality protocol.
        _increment_stat(self.config, 'source_protocol_rejected')
        self.send_error(400, "unsupported_source_protocol: literal source boundary required")
        return
    def _send_json_bytes(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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


class HyMTCompatServer(ThreadingHTTPServer):
    config: ProxyConfig
    stats: dict[str, Any]


def start_hymt_compat_proxy(config: ProxyConfig) -> HyMTCompatServer:
    config.stats.clear()
    config.stats.update({key:0 for key in ('policy_instruction_leak_rejected', 'format_placeholder_rejected', 'source_protocol_rejected','native_response_rejected','source_cache_rejected','current_attempt_cache_hits','actual_provider_calls','source_only_collection_requests')})
    try:
        server = HyMTCompatServer((config.host, config.port), _HyMTJsonCompatHandler)
    except OSError:
        if config.port == 0:
            raise
        config.stats["port_fallback_from"] = config.port
        server = HyMTCompatServer((config.host, 0), _HyMTJsonCompatHandler)
        config.port = int(server.server_address[1])
        config.stats["port_fallback_to"] = config.port
    else:
        config.port = int(server.server_address[1])
    server.config = config
    server.stats = config.stats
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
