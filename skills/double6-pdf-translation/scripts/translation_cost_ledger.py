# SPDX-License-Identifier: AGPL-3.0-only
"""一次翻译任务的时间和模型账。

只记录已经测到的数。后端没有写出账本、或字数没有从服务商返回时，对应字段留空，不补 0。
"""
from __future__ import annotations

import json
from pathlib import Path

PROTOCOL = "translation_cost_ledger_v1"
BACKEND_FILENAME = "translation_cost_ledger.json"

# 一批大约一页正文。字数按送模型前的源文计，超过才另起一批；段落上限防止一页碎成很多短行时合成一条过大的请求。
PAGE_BATCH_TOKEN_LIMIT = 1000
PAGE_BATCH_PARAGRAPH_LIMIT = 24

_READ_PDF = ("Parse PDF and Create Intermediate Representation",)
_LAYOUT = ("Parse Page Layout",)
_PREPARE = ("Parse Paragraphs", "Parse Formulas and Styles", "Parse Table", "DetectScannedFile")
_TRANSLATE = ("Translate Paragraphs",)
_TYPESET = ("Typesetting", "Add Fonts", "Generate drawing instructions", "Subset font", "Save PDF")


def batch_is_full(token_count: int, paragraph_count: int) -> bool:
    """当前这批已经超过一页正文的额度。调用方是先放入本段再判断，所以超限的那段仍留在本批。"""
    return token_count > PAGE_BATCH_TOKEN_LIMIT or paragraph_count > PAGE_BATCH_PARAGRAPH_LIMIT


def _round_seconds(value: float) -> float:
    return round(float(value), 3)


def _sum_named(stage_seconds: dict, names: tuple[str, ...]) -> float:
    return _round_seconds(sum(float(stage_seconds.get(name) or 0) for name in names))


def backend_ledger(
    *,
    requests: int,
    local_cache_hits: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    provider_cache_hit_prompt_tokens: int | None,
    token_usage_reported: bool,
    single_paragraph_retries: int,
    batch_splits: int,
    stage_seconds: dict,
    model_wait_seconds: float,
) -> dict:
    """后端进程能直接测到的部分。质量检查在后端退出后才跑，这里先不含这一项。"""
    stages = stage_seconds if isinstance(stage_seconds, dict) else {}
    return {
        "protocol": PROTOCOL,
        "available": True,
        "scope": "task",
        "requests": int(requests),
        "local_cache_hits": int(local_cache_hits),
        "prompt_tokens": None if prompt_tokens is None or not token_usage_reported else int(prompt_tokens),
        "completion_tokens": None if completion_tokens is None or not token_usage_reported else int(completion_tokens),
        "provider_cache_hit_prompt_tokens": (
            None if provider_cache_hit_prompt_tokens is None or not token_usage_reported
            else int(provider_cache_hit_prompt_tokens)
        ),
        "token_usage_reported": bool(token_usage_reported),
        "single_paragraph_retries": int(single_paragraph_retries),
        "batch_splits": int(batch_splits),
        "batch_token_limit": PAGE_BATCH_TOKEN_LIMIT,
        "batch_paragraph_limit": PAGE_BATCH_PARAGRAPH_LIMIT,
        "seconds": {
            "read_pdf": _sum_named(stages, _READ_PDF),
            "layout": _sum_named(stages, _LAYOUT),
            "prepare": _sum_named(stages, _PREPARE),
            "translate_stage": _sum_named(stages, _TRANSLATE),
            "model_wait": _round_seconds(model_wait_seconds),
            "typeset": _sum_named(stages, _TYPESET),
        },
    }


def unavailable(reason: str) -> dict:
    return {"protocol": PROTOCOL, "available": False, "reason": reason, "scope": "task"}


def _atomic(value) -> int:
    if value is None:
        return 0
    raw = value.value if hasattr(value, "value") else value
    return int(raw)


def collect_from_babeldoc_config(config) -> dict:
    """从一次已经跑完的后端配置里取计数。缺哪项就按「没测到」处理。"""
    translator = getattr(config, "translator", None)
    requests = int(getattr(translator, "model_request_count", 0) or 0)
    reported = int(getattr(translator, "usage_reported_count", 0) or 0)
    token_usage_reported = reported > 0 or requests == 0
    prompt = completion = cache_hit = None
    if token_usage_reported and translator is not None and hasattr(translator, "prompt_token_count"):
        prompt = _atomic(getattr(translator, "prompt_token_count", None))
        completion = _atomic(getattr(translator, "completion_token_count", None))
        cache_hit = _atomic(getattr(translator, "cache_hit_prompt_token_count", None))
    else:
        token_usage_reported = False
    monitor = getattr(config, "progress_monitor", None)
    stage_seconds = dict(getattr(monitor, "stage_seconds", {}) or {})
    shared = getattr(config, "shared_context_cross_split_part", None)
    stats = getattr(shared, "double6_batch_stats", None)
    stats = stats if isinstance(stats, dict) else {}
    return backend_ledger(
        requests=requests,
        local_cache_hits=int(getattr(translator, "translate_cache_call_count", 0) or 0),
        prompt_tokens=prompt,
        completion_tokens=completion,
        provider_cache_hit_prompt_tokens=cache_hit,
        token_usage_reported=token_usage_reported and prompt is not None,
        single_paragraph_retries=int(stats.get("single_paragraph_retries") or 0),
        batch_splits=int(stats.get("batch_splits") or 0),
        stage_seconds=stage_seconds,
        model_wait_seconds=float(getattr(translator, "model_wait_seconds", 0) or 0),
    )


def backend_ledger_path(working_dir: Path, stem: str) -> Path:
    return Path(working_dir) / stem / BACKEND_FILENAME


def write_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_ledger(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return unavailable("backend_ledger_missing")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return unavailable("backend_ledger_unreadable")
    if not isinstance(data, dict) or data.get("protocol") != PROTOCOL:
        return unavailable("backend_ledger_unreadable")
    ledger = dict(data)
    ledger["available"] = True
    return ledger


def load_backend_for_output(output_dir: Path, input_pdf: Path) -> dict:
    path = backend_ledger_path(Path(output_dir) / "_backend_working", Path(input_pdf).stem)
    return read_ledger(path)


def add_quality_seconds(ledger: dict, seconds: float) -> dict:
    updated = dict(ledger)
    timing = dict(updated.get("seconds") or {})
    timing["quality_check"] = _round_seconds(float(timing.get("quality_check") or 0) + float(seconds))
    updated["seconds"] = timing
    return updated


def fold_quality_check(output_dir: Path, *, extra_seconds: float, input_pdf: Path | None = None) -> dict:
    """把质量检查耗时加进渲染清单。清单里已有后端账本时在其上累加，没有则只标明后端账缺失。"""
    output_dir = Path(output_dir)
    manifest_path = output_dir / "render_manifest.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except (OSError, json.JSONDecodeError):
            manifest = {}
    ledger = manifest.get("cost_ledger")
    if not isinstance(ledger, dict) or ledger.get("protocol") != PROTOCOL:
        ledger = load_backend_for_output(output_dir, input_pdf) if input_pdf is not None else unavailable("backend_ledger_missing")
    ledger = add_quality_seconds(ledger, extra_seconds)
    if manifest_path.is_file() and manifest:
        manifest["cost_ledger"] = ledger
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_ledger(output_dir / BACKEND_FILENAME, ledger)
    backend_manifest = output_dir / "backend_run_manifest.json"
    if backend_manifest.is_file():
        try:
            value = json.loads(backend_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            value["cost_ledger"] = ledger
            backend_manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ledger


def _number(ledger: dict, key: str) -> int | None:
    value = ledger.get(key)
    if value is None:
        return None
    return int(value)


def sum_ledgers(ledgers: list) -> dict:
    """整份文档的账 = 各块的账相加。任一块没有可用账本时不补 0，整份标为不完整。"""
    usable: list[dict] = []
    for item in ledgers:
        if isinstance(item, dict) and item.get("available") is True and item.get("protocol") == PROTOCOL:
            usable.append(item)
            continue
        return {
            "protocol": PROTOCOL,
            "available": False,
            "reason": "chunk_ledger_incomplete",
            "scope": "document",
            "chunks": len(ledgers),
            "usable": len(usable),
        }
    def total(key: str) -> int | None:
        values = [_number(item, key) for item in usable]
        if any(value is None for value in values):
            return None
        return sum(values)
    token_reported = all(item.get("token_usage_reported") is True for item in usable)
    second_keys: set[str] = set()
    for item in usable:
        second_keys.update((item.get("seconds") or {}).keys())
    seconds = {
        key: _round_seconds(sum(float((item.get("seconds") or {}).get(key) or 0) for item in usable))
        for key in sorted(second_keys)
    }
    return {
        "protocol": PROTOCOL,
        "available": True,
        "scope": "document",
        "chunks": len(usable),
        "requests": total("requests"),
        "local_cache_hits": total("local_cache_hits"),
        "prompt_tokens": total("prompt_tokens") if token_reported else None,
        "completion_tokens": total("completion_tokens") if token_reported else None,
        "provider_cache_hit_prompt_tokens": total("provider_cache_hit_prompt_tokens") if token_reported else None,
        "token_usage_reported": token_reported,
        "single_paragraph_retries": total("single_paragraph_retries"),
        "batch_splits": total("batch_splits"),
        "batch_token_limit": PAGE_BATCH_TOKEN_LIMIT,
        "batch_paragraph_limit": PAGE_BATCH_PARAGRAPH_LIMIT,
        "seconds": seconds,
    }
