# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-25：智谱 coding plan 等模型档案；变更见 Skill 根目录 MODIFICATIONS.md。
"""按 configs/model-profiles.json 补齐未写明的模型、端点和凭据。显式参数优先。"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parents[1] / "configs" / "model-profiles.json"
GENERIC_TEMPERATURE = 0.7
GENERIC_REASONING_EFFORT = "none"


def request_concurrency_from_env(environ: dict | None = None) -> int | None:
    """环境变量写了同时请求数就用它；没写则返回 None，交给档案或各入口自己的默认。"""
    env = os.environ if environ is None else environ
    raw = env.get("LOCAL_MODEL_MAX_CONCURRENCY")
    if raw is None or not str(raw).strip():
        return None
    return int(str(raw).strip())


def _configured_concurrency(profile: dict | None) -> int | None:
    if not profile:
        return None
    value = profile.get("max_concurrency")
    if type(value) is not int or value < 1:
        return None
    return value


def _apply_request_concurrency(args, profile: dict | None) -> None:
    """没写路数、且档案写了同时请求数时，用档案里的数。已经写了数（含环境变量）则保持。"""
    configured = _configured_concurrency(profile)
    if configured is None or getattr(args, "local_max_concurrency", None) is not None:
        return
    args.local_max_concurrency = configured


def load_model_profiles(path: Path | None = None) -> dict:
    return json.loads((path or PROFILE_PATH).read_text(encoding="utf-8"))


def profile_for(data: dict, model: str | None) -> dict | None:
    profiles = data.get("profiles") or []
    if model:
        for profile in profiles:
            names = {profile.get("default_model"), *(profile.get("models") or [])}
            if model in names:
                return profile
        return None
    default_id = data.get("default_profile")
    for profile in profiles:
        if profile.get("id") == default_id:
            return profile
    return None


def thinking_floor(profile: dict, model: str | None) -> dict:
    """该模型思考强度的最低档。5.3 系列不能关闭，最低是 low。"""
    floors = profile.get("thinking_floors") or {}
    if model and model in floors and isinstance(floors[model], dict):
        return floors[model]
    default = profile.get("thinking_floor_default")
    return default if isinstance(default, dict) else {}


def _blank(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def apply_model_profile(args, environ: dict | None = None, profiles: dict | None = None) -> str | None:
    """补上档案里的模型、端点，以及没写明时的同时请求数。已写明的模型、端点、温度、reasoning、路数不改。

    命中档案且 LOCAL_TRANSLATION_API_KEY 为空时，把对应服务的 credential_fallback_env
    抄进进程环境的 LOCAL_TRANSLATION_API_KEY，供子进程继承。不写入命令行，也不把值放进返回值。
    """
    env = os.environ if environ is None else environ
    model = _blank(getattr(args, "model", None))
    base_url = _blank(getattr(args, "base_url", None))
    data = profiles if profiles is not None else load_model_profiles()
    profile = profile_for(data, model)
    _apply_request_concurrency(args, profile)
    if profile is None:
        return None
    if not model and hasattr(args, "model"):
        args.model = profile["default_model"]
    if not base_url and hasattr(args, "base_url"):
        args.base_url = profile["base_url"]
    if hasattr(args, "temperature") and args.temperature == GENERIC_TEMPERATURE and "temperature" in profile:
        args.temperature = float(profile["temperature"])
    if hasattr(args, "openai_json_mode") and profile.get("json_mode") is True and args.openai_json_mode is None:
        args.openai_json_mode = True
    # 调用方没改思考强度、也没要求留下模型默认档时，落到该模型的最低档。
    effort_left_default = (not hasattr(args, "openai_reasoning_effort")
                           or args.openai_reasoning_effort == GENERIC_REASONING_EFFORT)
    if effort_left_default and getattr(args, "openai_send_reasoning_effort", True):
        floor = thinking_floor(profile, model or profile.get("default_model"))
        if hasattr(args, "openai_reasoning_effort") and floor.get("reasoning_effort"):
            args.openai_reasoning_effort = floor["reasoning_effort"]
        if floor.get("thinking"):
            args.thinking = floor["thinking"]
    primary = profile.get("credential_env") or "LOCAL_TRANSLATION_API_KEY"
    fallback = profile.get("credential_fallback_env")
    if not env.get(primary) and fallback and env.get(fallback):
        env[primary] = env[fallback]
        if hasattr(args, "api_key") and not _blank(getattr(args, "api_key", None)):
            args.api_key = env[primary]
    if hasattr(args, "model_profile"):
        args.model_profile = profile.get("id")
    return profile.get("id")


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由翻译入口调用的模型档案模块，不提供独立命令。"
