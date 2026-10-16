"""激励库：引擎与皮肤的只读合同，不代替星星账本。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .core import ContractError

LIBRARY_PATH = (
    Path(__file__).resolve().parents[2] / "references" / "incentive-library.json"
)
ASSEMBLED = "assembled"
CATALOG_READY = "catalog_ready"
ALLOWED_STATUS = {ASSEMBLED, CATALOG_READY}
ALLOWED_POLARITY = {
    "positive",
    "negative_cute",
    "warmth",
    "neutral",
    "adult_control",
}


@lru_cache(maxsize=1)
def load_incentive_library() -> dict[str, Any]:
    payload = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    validate_incentive_library(payload)
    return payload


def validate_incentive_library(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "double6-incentive-library/v1":
        raise ContractError("激励库 schema 不匹配")
    engines = {row["engine_id"]: row for row in payload.get("engines") or [] if row.get("engine_id")}
    if not engines:
        raise ContractError("激励库缺少引擎")
    seen: set[str] = set()
    for row in payload.get("systems") or []:
        system_id = str(row.get("system_id") or "")
        engine_id = str(row.get("engine_id") or "")
        status = str(row.get("status") or "")
        if not system_id or system_id in seen:
            raise ContractError(f"激励系统 id 无效或重复：{system_id}")
        if engine_id not in engines:
            raise ContractError(f"激励系统 {system_id} 引用了未知引擎 {engine_id}")
        if status not in ALLOWED_STATUS:
            raise ContractError(f"激励系统 {system_id} 状态不合法")
        polarity = str(engines[engine_id].get("polarity") or "")
        if polarity not in ALLOWED_POLARITY:
            raise ContractError(f"引擎 {engine_id} 极性不合法")
        visible = [
            str(row.get("label") or ""),
            str((row.get("skin") or {}).get("character") or ""),
        ]
        skin = row.get("skin") if isinstance(row.get("skin"), dict) else {}
        visible.extend(str(value) for value in (skin.get("moods") or {}).values())
        for key in ("recover", "celebration", "baby_waiting"):
            visible.append(str(skin.get(key) or ""))
        if any("奥特曼" in part for part in visible):
            raise ContractError(f"{system_id} 可见文案不得使用授权 IP 名")
        seen.add(system_id)
    if "stars-shop" not in seen:
        raise ContractError("激励库必须包含已装配的星星攒兑")


def assembled_system_ids() -> list[str]:
    library = load_incentive_library()
    return [row["system_id"] for row in library["systems"] if row["status"] == ASSEMBLED]


def catalog_system_ids(*, engine_id: str | None = None) -> list[str]:
    library = load_incentive_library()
    rows = library["systems"]
    if engine_id:
        rows = [row for row in rows if row["engine_id"] == engine_id]
    return [row["system_id"] for row in rows]


def companion_skins() -> list[dict[str, Any]]:
    library = load_incentive_library()
    return [row for row in library["systems"] if row["engine_id"] == "companion_stake"]
