#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import layout_role_policy
import policy_utils
import translation_compat_proxy
from pdf_translation_runtime import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_MODEL, resolve_api_key, resolve_base_url
from translation_compat_proxy import ProxyConfig


SCRIPT_INTERFACE = "diagnostic-cli"
SCRIPT_INTERFACE_REASON = "Run offline or live OpenAI-compatible translation probes without changing the delivery pipeline."

DEFAULT_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_TEMPERATURES = (0.1, 0.2, 0.3, 0.5)
DEFAULT_PROMPT_VARIANTS = ("current", "no_policy", "no_broad_protection", "force_chinese_retry", "paragraph")
DEFAULT_CALL_PATHS = ("direct", "proxy", "json-batch")
PROTECTED_TOKEN_RE = re.compile(
    r"(https?://[^\s)>\]]+|\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+|"
    r"[A-Za-z0-9_.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\{v\d+\}|\[[0-9,\-\s]{1,30}\]|"
    r"</?style\b[^>]*>|\\[A-Za-z]+(?:\{[^{}]*\})?)"
)


def visible_text(text: str) -> str:
    return translation_compat_proxy.visible_text_for_quality(text)


def cjk_count(text: str) -> int:
    return translation_compat_proxy.cjk_char_count(text)


def stable_case_id(prefix: str, source: str) -> str:
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()[:16]


def split_csv(value: str | None, defaults: tuple[Any, ...]) -> list[str]:
    if not value:
        return [str(item) for item in defaults]
    return [part.strip() for part in value.split(",") if part.strip()]


def split_float_csv(value: str | None, defaults: tuple[float, ...]) -> list[float]:
    if not value:
        return list(defaults)
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def expected_behavior_for_source(source: str, classification: str = "", role: str = "") -> str:
    if translation_compat_proxy.is_protected_or_passthrough_only(source):
        return "protect"
    if classification in {"layout_role_passthrough", "protected_passthrough", "reference_passthrough"}:
        return "protect"
    if role in {"reference_entry", "references_heading", "page_header_footer", "page_number"}:
        return "protect"
    return "translate"


def make_case(
    source: str,
    *,
    case_id: str | None = None,
    origin: str = "manual",
    source_output: str = "",
    classification: str = "",
    role: str = "",
    expected_behavior: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(source or "").strip()
    role_value = role or layout_role_policy.classify_babeldoc_item({"id": case_id or "probe", "input": text})
    behavior = expected_behavior or expected_behavior_for_source(text, classification=classification, role=role_value)
    return {
        "id": case_id or stable_case_id(origin, text),
        "origin": origin,
        "source": text,
        "source_output": str(source_output or ""),
        "classification": classification,
        "role": role_value,
        "expected_behavior": behavior,
        "metadata": metadata or {},
    }


def dedupe_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for case in cases:
        source = str(case.get("source") or "").strip()
        if not source or source in seen:
            continue
        seen.add(source)
        deduped.append(case)
    return deduped


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            continue
        source = str(payload.get("source") or payload.get("input") or payload.get("source_snippet") or "")
        if not source.strip():
            continue
        cases.append(
            make_case(
                source,
                case_id=str(payload.get("id") or f"{path.stem}-{line_number}"),
                origin=f"jsonl:{path.name}",
                source_output=str(payload.get("output") or payload.get("output_snippet") or ""),
                classification=str(payload.get("classification") or ""),
                role=str(payload.get("role") or payload.get("layout_role") or ""),
                expected_behavior=payload.get("expected_behavior"),
                metadata={key: value for key, value in payload.items() if key not in {"source", "input", "source_snippet"}},
            )
        )
    return cases


def load_backend_retry_failure_cases(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    failures = payload.get("failures") if isinstance(payload, dict) else None
    for index, item in enumerate(failures if isinstance(failures, list) else []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_snippet") or "")
        if not source.strip():
            continue
        cases.append(
            make_case(
                source,
                case_id=str(item.get("paragraph_debug_id") or f"{path.stem}-failure-{index + 1}"),
                origin=f"backend_retry_failures:{path.name}",
                source_output=str(item.get("output_snippet") or ""),
                classification=str(item.get("classification") or ""),
                role=str(item.get("layout_role") or item.get("layout_label") or ""),
                metadata={
                    "failure_type": item.get("failure_type"),
                    "page": item.get("page"),
                    "blocking_reason": item.get("blocking_reason"),
                },
            )
        )
    return cases


def iter_proxy_stat_samples(stats: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sample_keys = [
        "json_batch_same_as_input_samples",
        "same_as_input_candidates",
        "protected_value_candidates",
        "non_chinese_translation_samples",
        "partial_untranslated_samples",
        "plain_layout_role_intercept_samples",
    ]
    samples: list[tuple[str, dict[str, Any]]] = []
    for key in sample_keys:
        values = stats.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                samples.append((key, item))
    return samples


def load_translation_proxy_stats_cases(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else payload
    if not isinstance(stats, dict):
        return []
    cases: list[dict[str, Any]] = []
    for index, (key, item) in enumerate(iter_proxy_stat_samples(stats), start=1):
        source = str(item.get("source") or item.get("source_snippet") or "")
        if not source.strip():
            continue
        cases.append(
            make_case(
                source,
                case_id=str(item.get("paragraph_debug_id") or item.get("id") or f"{path.stem}-{key}-{index}"),
                origin=f"translation_proxy_stats:{path.name}:{key}",
                source_output=str(item.get("output") or item.get("output_snippet") or ""),
                role=str(item.get("layout_role") or item.get("role") or item.get("layout_label") or ""),
                classification="layout_role_passthrough" if key == "plain_layout_role_intercept_samples" else "",
                metadata={"sample_key": key, "page": item.get("page"), "layout_label": item.get("layout_label")},
            )
        )
    return cases


def load_cases_from_path(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return load_jsonl_cases(path)
    payload = load_json(path)
    if isinstance(payload, dict) and "failures" in payload:
        return load_backend_retry_failure_cases(path, payload)
    if isinstance(payload, dict) and ("stats" in payload or "json_batch_items" in payload):
        return load_translation_proxy_stats_cases(path, payload)
    if isinstance(payload, list):
        cases: list[dict[str, Any]] = []
        for index, item in enumerate(payload, start=1):
            if isinstance(item, dict):
                source = str(item.get("source") or item.get("input") or item.get("source_snippet") or "")
                if source.strip():
                    cases.append(make_case(source, case_id=str(item.get("id") or f"{path.stem}-{index}"), origin=f"json:{path.name}"))
        return cases
    return []


def synthetic_cases() -> list[dict[str, Any]]:
    translate_sources = [
        "Large language models can solve complex tasks by recursively composing skills.",
        "The agent learns reusable skills from sparse rewards and transfers them to new environments.",
        "Our experiments show consistent improvements over strong reinforcement learning baselines.",
        "The framework reduces exploration cost while preserving the ability to discover novel strategies.",
        "Recursive skill augmentation enables agents to reuse prior behaviors without explicit demonstrations.",
        "This paper introduces a benchmark for evaluating long-horizon planning in language agents.",
        "The results suggest that structured memory improves robustness across diverse tasks.",
        "We observe that smaller models benefit more from explicit decomposition than larger models.",
        "The proposed method outperforms prior work on success rate and sample efficiency.",
        "Ablation studies confirm that both skill retrieval and policy refinement are necessary.",
        "<style id='1'>The model is trained with a curriculum of increasingly difficult tasks.</style>",
        "<style id='2'>Large Language Model agents often fail when rewards are delayed.</style>",
        "Figure 2: Success rate across recursive skill learning iterations.",
        "Table 1: Comparison with baseline reinforcement learning methods.",
        "Abstract",
        "Introduction",
        "Limitations and Future Work",
        "The environment provides observations, actions, and sparse terminal rewards.",
        "We use {v1} to denote the learned skill library and {v2} for the policy.",
        "The method is evaluated on planning, tool use, and interactive reasoning tasks.",
    ]
    protected_sources = [
        "https://arxiv.org/abs/2602.08234",
        "10.48550/arXiv.2602.08234",
        "contact@example.edu",
        "[12]",
        "[3, 7, 19]",
        "{v1}",
        "{v2} {v3}",
        "\\begin{equation}",
        "\\alpha + \\beta = \\gamma",
        "`python train.py --config skillrl.yaml`",
        "GPT-4o",
        "DeepSeek-V3",
        "OpenAI o1",
        "LaTeX",
        "PDF",
        "API",
        "<style id='7'></style>",
        "https://github.com/example/repo",
        "doi:10.1145/1234567.8901234",
        "\\cite{smith2024skill}",
    ]
    cases = [
        make_case(source, case_id=f"synthetic-translate-{index + 1:02d}", origin="synthetic", expected_behavior="translate")
        for index, source in enumerate(translate_sources)
    ]
    cases.extend(
        make_case(source, case_id=f"synthetic-protect-{index + 1:02d}", origin="synthetic", expected_behavior="protect")
        for index, source in enumerate(protected_sources)
    )
    return cases


def build_policy_prompt(case: dict[str, Any], variant: str) -> str:
    role_prompt = layout_role_policy.role_prompt(str(case.get("role") or ""))
    glossary = (
        "Terminology policy:\n"
        "- Large Language Model => 大型语言模型\n"
        "- reinforcement learning => 强化学习\n"
        "- recursive skill => 递归技能\n"
    )
    if variant == "no_policy":
        return ""
    if variant == "no_broad_protection":
        return role_prompt
    if variant == "paragraph":
        return "\n".join(part for part in [glossary, role_prompt, "Treat the input as a paragraph fragment; translate natural-language prose fully."] if part.strip())
    return "\n".join(part for part in [glossary, role_prompt] if part.strip())


def build_prompt(source: str, case: dict[str, Any], variant: str) -> str:
    policy_prompt = build_policy_prompt(case, variant)
    if variant == "no_broad_protection":
        return (
            "Translate the following academic PDF text into Simplified Chinese. Preserve only URLs, DOIs, citations, "
            "LaTeX commands, placeholders like {v1}, and XML/HTML-style tags exactly. Translate all other English prose, "
            "including terminology and model descriptions. Output only the translation.\n\n"
            + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
            + source
        )
    if variant == "force_chinese_retry":
        return (
            "The previous attempt copied English text. Translate every ordinary English word or sentence below into natural "
            "Simplified Chinese now. Do not echo the input unless it is only a URL, DOI, citation, placeholder, code, "
            "LaTeX command, or proper model/name token. Preserve wrappers exactly. Output only Chinese translation text.\n\n"
            + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
            + source
        )
    if variant == "paragraph":
        return (
            "Translate this academic paragraph fragment into Simplified Chinese. The text may be a PDF extraction fragment, "
            "but it is ordinary prose unless it is clearly a reference, URL, formula, or code. Preserve placeholders and tags. "
            "Output only the translated fragment.\n\n"
            + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
            + source
        )
    return (
        "Translate the following academic PDF text into Simplified Chinese. "
        "Preserve placeholders such as {v1}, citations like [12], URLs, code, LaTeX commands, "
        "XML/HTML-style tags, model names, and file names exactly. Output only the translation.\n\n"
        "Preserve Latin personal names in the original alphabet. Keep numbered lists as separate items. "
        "Never explain the task, never mention these instructions, and never output analysis.\n\n"
        + (policy_prompt.strip() + "\n\n" if policy_prompt.strip() else "")
        + source
    )


def extract_content(data: dict[str, Any]) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(message.get("content") or message.get("reasoning_content") or "")


def post_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    timeout: int,
    max_tokens: int,
    thinking: str = "disabled",
    response_format: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if thinking in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking}
    if response_format:
        payload["response_format"] = response_format
    request = urllib.request.Request(
        translation_compat_proxy.chat_completions_url(base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return extract_content(json.loads(response.read().decode("utf-8")))


def call_direct(case: dict[str, Any], variant: str, temperature: float, config: ProxyConfig, timeout: int) -> tuple[str, dict[str, Any]]:
    prompt = build_prompt(str(case["source"]), case, variant)
    max_tokens = int(config.stats.get("_probe_max_tokens") or 512)
    output = post_chat_completion(
        base_url=config.upstream_base_url,
        api_key=config.api_key,
        model=config.model,
        prompt=prompt,
        temperature=temperature,
        timeout=timeout,
        max_tokens=max_tokens,
        thinking=str(config.stats.get("_probe_thinking") or "disabled"),
    )
    return output, {
        "prompt_hash": prompt_hash(prompt),
        "temperature_applied": True,
        "max_tokens": max_tokens,
        "thinking": str(config.stats.get("_probe_thinking") or "disabled"),
    }


def call_proxy(case: dict[str, Any], _variant: str, _temperature: float, config: ProxyConfig, _timeout: int) -> tuple[str, dict[str, Any]]:
    output = translation_compat_proxy.call_plain_translation(str(case["source"]), config, policy_prompt=build_policy_prompt(case, "current"))
    return output, {"prompt_hash": None, "temperature_applied": False, "thinking": str(config.stats.get("_probe_thinking") or "disabled")}


def call_json_batch(case: dict[str, Any], _variant: str, _temperature: float, config: ProxyConfig, _timeout: int) -> tuple[str, dict[str, Any]]:
    item = {"id": str(case["id"]), "input": str(case["source"]), "layout_label": case.get("role")}
    body = translation_compat_proxy.synthesize_babeldoc_json_response({"model": config.model}, [item], config)
    content = extract_content(json.loads(body.decode("utf-8")))
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content, {"prompt_hash": None, "temperature_applied": False}
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        return str(parsed[0].get("output") or ""), {
            "prompt_hash": None,
            "temperature_applied": False,
            "thinking": str(config.stats.get("_probe_thinking") or "disabled"),
        }
    return content, {"prompt_hash": None, "temperature_applied": False, "thinking": str(config.stats.get("_probe_thinking") or "disabled")}


CALL_PATHS = {
    "direct": call_direct,
    "proxy": call_proxy,
    "json-batch": call_json_batch,
}


def probe_call_config(config: ProxyConfig) -> ProxyConfig:
    cloned = ProxyConfig(model=config.model, upstream_base_url=config.upstream_base_url, api_key=config.api_key)
    for key in ["_probe_max_tokens", "_probe_timeout", "_probe_thinking"]:
        if key in config.stats:
            cloned.stats[key] = config.stats[key]
    return cloned


def build_probe_tasks(
    cases: list[dict[str, Any]],
    call_paths: list[str],
    prompt_variants: list[str],
    temperatures: list[float],
    max_results: int = 0,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for call_path in call_paths:
        if call_path not in CALL_PATHS:
            raise ValueError(f"Unsupported call path: {call_path}")
        variants = prompt_variants if call_path == "direct" else ["current"]
        temps = temperatures if call_path == "direct" else [temperatures[0]]
        for variant in variants:
            for temperature in temps:
                for case in cases:
                    tasks.append(
                        {
                            "case": case,
                            "call_path": call_path,
                            "prompt_variant": variant,
                            "temperature": temperature,
                        }
                    )
                    if max_results > 0 and len(tasks) >= max_results:
                        return tasks
    return tasks


def execute_probe_task(
    task: dict[str, Any],
    *,
    config: ProxyConfig,
    timeout: int,
    model: str,
    base_url: str,
    thinking: str,
) -> dict[str, Any]:
    case = task["case"]
    call_path = str(task["call_path"])
    variant = str(task["prompt_variant"])
    temperature = float(task["temperature"])
    started = time.time()
    try:
        call_config = probe_call_config(config)
        output, extra = CALL_PATHS[call_path](case, variant, temperature, call_config, timeout)
        error = None
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, ValueError) as exc:
        output = ""
        extra = {}
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
    metrics = classify_probe_result(case, output)
    return {
        "case_id": case["id"],
        "origin": case["origin"],
        "role": case["role"],
        "expected_behavior": case["expected_behavior"],
        "call_path": call_path,
        "prompt_variant": variant,
        "temperature": temperature,
        "model": model,
        "base_url_host": re.sub(r"^https?://", "", base_url).split("/", 1)[0],
        "prompt_hash": extra.get("prompt_hash"),
        "temperature_applied": extra.get("temperature_applied"),
        "thinking": extra.get("thinking") or thinking,
        "source": case["source"],
        "output": output,
        "metrics": metrics,
        "error": error,
        "latency_seconds": round(time.time() - started, 3),
    }


def protected_tokens(source: str) -> list[str]:
    tokens = [match.group(0) for match in PROTECTED_TOKEN_RE.finditer(source)]
    return list(dict.fromkeys(tokens))


def missing_protected_tokens(source: str, output: str) -> list[str]:
    missing = []
    for token in protected_tokens(source):
        if not policy_utils.protected_value_present(token, output):
            missing.append(token)
    return missing


def classify_probe_result(case: dict[str, Any], output: str) -> dict[str, Any]:
    source = str(case.get("source") or "")
    expected = str(case.get("expected_behavior") or expected_behavior_for_source(source))
    same = translation_compat_proxy.is_same_as_input_translation(source, output)
    partial = translation_compat_proxy.looks_partially_untranslated(source, output)
    task_explanation = translation_compat_proxy.looks_like_task_explanation(output)
    non_chinese = (
        expected == "translate"
        and translation_compat_proxy.should_translate_to_chinese(source)
        and cjk_count(output) == 0
        and bool(re.search(r"[A-Za-z]{4,}", visible_text(output)))
    )
    missing_tokens = missing_protected_tokens(source, output)
    placeholder_break = any(re.fullmatch(r"\{v\d+\}", token) for token in missing_tokens)
    style_tag_break = any(token.lower().startswith("<style") or token.lower() == "</style>" for token in missing_tokens)
    protected_break = bool(missing_tokens)
    protected_mistranslation = expected == "protect" and not same and visible_text(source) != visible_text(output)
    ordinary_failure = expected == "translate" and (same or non_chinese or partial or task_explanation)
    return {
        "expected_behavior": expected,
        "same_as_input": bool(same and expected == "translate"),
        "non_chinese": bool(non_chinese),
        "partial_untranslated": bool(partial and expected == "translate"),
        "placeholder_break": bool(placeholder_break),
        "style_tag_break": bool(style_tag_break),
        "protected_span_break": bool(protected_break),
        "task_explanation": bool(task_explanation),
        "protected_mistranslation": bool(protected_mistranslation),
        "ordinary_failure": bool(ordinary_failure),
        "missing_protected_tokens": missing_tokens[:10],
        "cjk_chars": cjk_count(output),
        "source_alpha_words": len(re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", visible_text(source))),
        "output_alpha_words": len(re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", visible_text(output))),
    }


def select_cases(cases: list[dict[str, Any]], max_per_kind: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        key = str(case.get("expected_behavior") or "translate")
        if "backend_retry_failures" in str(case.get("origin")) or "translation_proxy_stats" in str(case.get("origin")):
            key = f"real_{key}"
        buckets.setdefault(key, []).append(case)
    selected: list[dict[str, Any]] = []
    for values in buckets.values():
        selected.extend(values[:max_per_kind])
    return dedupe_cases(selected)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for result in results:
        key = "|".join(
            [
                str(result.get("call_path")),
                str(result.get("prompt_variant")),
                str(result.get("temperature")),
                str(result.get("role")),
            ]
        )
        group = groups.setdefault(
            key,
            {
                "call_path": result.get("call_path"),
                "prompt_variant": result.get("prompt_variant"),
                "temperature": result.get("temperature"),
                "role": result.get("role"),
                "total": 0,
                "translate_total": 0,
                "protect_total": 0,
                "same_as_input": 0,
                "non_chinese": 0,
                "partial_untranslated": 0,
                "placeholder_break": 0,
                "style_tag_break": 0,
                "protected_span_break": 0,
                "task_explanation": 0,
                "protected_mistranslation": 0,
                "ordinary_failure": 0,
            },
        )
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        group["total"] += 1
        if metrics.get("expected_behavior") == "translate":
            group["translate_total"] += 1
        else:
            group["protect_total"] += 1
        for field in [
            "same_as_input",
            "non_chinese",
            "partial_untranslated",
            "placeholder_break",
            "style_tag_break",
            "protected_span_break",
            "task_explanation",
            "protected_mistranslation",
            "ordinary_failure",
        ]:
            if metrics.get(field):
                group[field] += 1
    summaries = []
    for group in groups.values():
        translate_total = max(int(group["translate_total"]), 1)
        protect_total = max(int(group["protect_total"]), 1)
        group["same_as_input_rate"] = round(group["same_as_input"] / translate_total, 4)
        group["non_chinese_rate"] = round(group["non_chinese"] / translate_total, 4)
        group["partial_untranslated_rate"] = round(group["partial_untranslated"] / translate_total, 4)
        group["placeholder_break_rate"] = round(group["placeholder_break"] / max(int(group["total"]), 1), 4)
        group["style_tag_break_rate"] = round(group["style_tag_break"] / max(int(group["total"]), 1), 4)
        group["protected_span_break_rate"] = round(group["protected_span_break"] / max(int(group["total"]), 1), 4)
        group["task_explanation_rate"] = round(group["task_explanation"] / max(int(group["total"]), 1), 4)
        group["protected_mistranslation_rate"] = round(group["protected_mistranslation"] / protect_total, 4)
        group["meets_candidate_thresholds"] = (
            group["same_as_input_rate"] <= 0.02
            and group["non_chinese_rate"] <= 0.02
            and group["placeholder_break_rate"] <= 0.01
            and group["protected_mistranslation_rate"] == 0
        )
        summaries.append(group)
    summaries.sort(key=lambda item: (str(item["call_path"]), str(item["prompt_variant"]), float(item["temperature"] or 0), str(item["role"])))
    return {"groups": summaries}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def render_summary_markdown(summary: dict[str, Any], *, cases_count: int, dry_run: bool) -> str:
    lines = [
        "# Translation API Probe Summary",
        "",
        f"- dry_run: `{str(dry_run).lower()}`",
        f"- cases: `{cases_count}`",
        "",
        "| call_path | prompt_variant | temperature | role | total | same_as_input_rate | non_chinese_rate | partial_untranslated_rate | placeholder_break_rate | style_tag_break_rate | protected_span_break_rate | task_explanation_rate | candidate |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for group in summary.get("groups", []):
        lines.append(
            "| {call_path} | {prompt_variant} | {temperature} | {role} | {total} | {same_as_input_rate:.4f} | "
            "{non_chinese_rate:.4f} | {partial_untranslated_rate:.4f} | {placeholder_break_rate:.4f} | "
            "{style_tag_break_rate:.4f} | {protected_span_break_rate:.4f} | {task_explanation_rate:.4f} | {candidate} |".format(
                **group,
                candidate="yes" if group.get("meets_candidate_thresholds") else "no",
            )
        )
    lines.append("")
    lines.append("Candidate thresholds: same-as-input <= 2%, non-Chinese <= 2%, placeholder break <= 1%, protected-only mistranslation = 0%.")
    return "\n".join(lines) + "\n"


def write_probe_outputs(
    output_dir: Path,
    payload: dict[str, Any],
    *,
    cases_count: int,
    dry_run: bool,
) -> None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {"groups": []}
    (output_dir / "probe_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "probe_summary.md").write_text(render_summary_markdown(summary, cases_count=cases_count, dry_run=dry_run), encoding="utf-8")


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    input_cases: list[dict[str, Any]] = []
    for input_path in args.input or []:
        input_cases.extend(load_cases_from_path(Path(input_path).expanduser()))
    if args.include_synthetic:
        input_cases.extend(synthetic_cases())
    cases = select_cases(dedupe_cases(input_cases), args.max_cases_per_kind)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    temperatures = split_float_csv(args.temperatures, DEFAULT_TEMPERATURES)
    prompt_variants = split_csv(args.prompt_variants, DEFAULT_PROMPT_VARIANTS)
    call_paths = split_csv(args.call_paths, DEFAULT_CALL_PATHS)
    model = args.model or os.environ.get("LOCAL_TRANSLATION_MODEL") or DEFAULT_MODEL or DEFAULT_MODEL_NAME
    base_url = resolve_base_url(args.provider, args.base_url or DEFAULT_BASE_URL).rstrip("/")
    api_key = resolve_api_key(args.provider, args.api_key or DEFAULT_API_KEY) or ""
    config = ProxyConfig(model=model, upstream_base_url=base_url, api_key=api_key)
    config.stats["_probe_max_tokens"] = int(args.max_tokens)
    config.stats["_probe_timeout"] = int(args.timeout)
    config.stats["_probe_thinking"] = str(args.thinking)
    case_rows = [
        {
            "id": case["id"],
            "origin": case["origin"],
            "role": case["role"],
            "expected_behavior": case["expected_behavior"],
            "classification": case.get("classification"),
            "source": case["source"],
        }
        for case in cases
    ]
    write_jsonl(output_dir / "probe_cases.jsonl", case_rows)
    if args.dry_run:
        results: list[dict[str, Any]] = []
    else:
        if not api_key:
            raise RuntimeError("Missing API key. Set provider-specific env vars such as DEEPSEEK_API_KEY, or pass --api-key.")
        results = []
        tasks = build_probe_tasks(cases, call_paths, prompt_variants, temperatures, max_results=int(args.max_results))
        planned_total = len(tasks)
        progress_every = max(int(args.progress_every), 0)
        save_every = max(int(args.save_every), 1)
        concurrency = max(int(args.concurrency), 1)

        def record_result(result: dict[str, Any]) -> None:
            results.append(result)
            if progress_every and len(results) % progress_every == 0:
                print(
                    json.dumps(
                        {
                            "progress": len(results),
                            "planned": planned_total,
                            "call_path": result.get("call_path"),
                            "prompt_variant": result.get("prompt_variant"),
                            "temperature": result.get("temperature"),
                            "concurrency": concurrency,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if len(results) % save_every == 0:
                partial_payload = build_payload(
                    args=args,
                    model=model,
                    base_url=base_url,
                    cases=cases,
                    temperatures=temperatures,
                    prompt_variants=prompt_variants,
                    call_paths=call_paths,
                    results=results,
                    partial=True,
                )
                write_probe_outputs(output_dir, partial_payload, cases_count=len(cases), dry_run=False)

        if concurrency == 1:
            for task in tasks:
                record_result(
                    execute_probe_task(
                        task,
                        config=config,
                        timeout=args.timeout,
                        model=model,
                        base_url=base_url,
                        thinking=args.thinking,
                    )
                )
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [
                    executor.submit(
                        execute_probe_task,
                        task,
                        config=config,
                        timeout=args.timeout,
                        model=model,
                        base_url=base_url,
                        thinking=args.thinking,
                    )
                    for task in tasks
                ]
                for future in concurrent.futures.as_completed(futures):
                    record_result(future.result())
    payload = build_payload(
        args=args,
        model=model,
        base_url=base_url,
        cases=cases,
        temperatures=temperatures,
        prompt_variants=prompt_variants,
        call_paths=call_paths,
        results=results,
        partial=False,
    )
    write_probe_outputs(output_dir, payload, cases_count=len(cases), dry_run=args.dry_run)
    return payload


def build_payload(
    *,
    args: argparse.Namespace,
    model: str,
    base_url: str,
    cases: list[dict[str, Any]],
    temperatures: list[float],
    prompt_variants: list[str],
    call_paths: list[str],
    results: list[dict[str, Any]],
    partial: bool,
) -> dict[str, Any]:
    summary = summarize_results(results)
    return {
        "version": 1,
        "model": model,
        "provider": args.provider,
        "base_url_host": re.sub(r"^https?://", "", base_url).split("/", 1)[0],
        "dry_run": bool(args.dry_run),
        "partial": bool(partial),
        "case_count": len(cases),
        "temperatures": temperatures,
        "prompt_variants": prompt_variants,
        "call_paths": call_paths,
        "thinking": args.thinking,
        "concurrency": int(args.concurrency),
        "summary": summary,
        "results": results,
        "warnings": build_warnings(cases),
    }


def build_warnings(cases: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for case in cases:
        key = str(case.get("expected_behavior") or "translate")
        if "backend_retry_failures" in str(case.get("origin")) or "translation_proxy_stats" in str(case.get("origin")):
            key = f"real_{key}"
        counts[key] = counts.get(key, 0) + 1
    warnings = []
    for key in ["real_translate", "translate", "protect"]:
        if counts.get(key, 0) < 20:
            warnings.append(f"{key} has {counts.get(key, 0)} cases; target is at least 20 for a small probe.")
    return warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe OpenAI-compatible translation behavior on PDF backend fragments.")
    parser.add_argument("--input", action="append", help="Input backend_retry_failures.json, translation_proxy_stats.json, JSON list, or JSONL fixture. Repeatable.")
    parser.add_argument("--output-dir", default=".cache/translation-api-probe", help="Directory for probe_results.json, probe_summary.md, and probe_cases.jsonl.")
    parser.add_argument("--provider", default=os.environ.get("LOCAL_TRANSLATION_PROVIDER", "deepseek"))
    parser.add_argument("--base-url", default=os.environ.get("LOCAL_TRANSLATION_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("LOCAL_TRANSLATION_MODEL") or DEFAULT_MODEL_NAME)
    parser.add_argument("--api-key", default=os.environ.get("LOCAL_TRANSLATION_API_KEY") or DEFAULT_API_KEY)
    parser.add_argument("--temperatures", default=",".join(str(value) for value in DEFAULT_TEMPERATURES))
    parser.add_argument("--prompt-variants", default=",".join(DEFAULT_PROMPT_VARIANTS))
    parser.add_argument("--call-paths", default=",".join(DEFAULT_CALL_PATHS))
    parser.add_argument("--max-cases-per-kind", type=int, default=20)
    parser.add_argument("--max-results", type=int, default=0, help="Stop after this many API results; 0 means no limit.")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of concurrent live API probe requests.")
    parser.add_argument("--save-every", type=int, default=20, help="Incrementally rewrite probe result files every N API results.")
    parser.add_argument("--progress-every", type=int, default=25, help="Print JSON progress every N API results; 0 disables progress logs.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=512, help="Maximum completion tokens for direct API probe calls.")
    parser.add_argument(
        "--thinking",
        choices=["disabled", "enabled", "omit"],
        default="disabled",
        help="DeepSeek thinking mode for live probes. Use omit to send no thinking field.",
    )
    parser.add_argument("--no-synthetic", dest="include_synthetic", action="store_false", help="Do not add built-in synthetic control/protected cases.")
    parser.add_argument("--dry-run", action="store_true", help="Only collect cases and write empty result summaries; do not call the API.")
    parser.set_defaults(include_synthetic=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_probe(args)
    print(
        json.dumps(
            {
                "output_dir": str(Path(args.output_dir).expanduser()),
                "case_count": payload["case_count"],
                "dry_run": payload["dry_run"],
                "warnings": payload["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
