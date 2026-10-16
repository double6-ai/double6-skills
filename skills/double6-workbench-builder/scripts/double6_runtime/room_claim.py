"""房间认领：称呼和一件自己的东西。只留本机，不改掌握。"""

from __future__ import annotations

import re
from typing import Any

NAME_MAX = 6
BANNED_NAME_FRAGMENTS = ("奥特曼", "hello kitty", "hellokitty")
NAME_OK = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·]+$")


def sanitize_room_name(raw: Any) -> str:
    original = str(raw or "")
    compact = re.sub(r"\s+", "", original)
    if not compact:
        return ""
    haystacks = (original, compact, original.casefold(), compact.casefold())
    if any(part in hay for hay in haystacks for part in BANNED_NAME_FRAGMENTS):
        return ""
    text = compact[:NAME_MAX]
    if not NAME_OK.fullmatch(text):
        return ""
    return text


def belonging_for_room(catalog: list[dict[str, Any]], room_id: str, belonging_id: str | None) -> dict[str, Any] | None:
    room = str(room_id or "")
    rows = [row for row in catalog if isinstance(row, dict) and row.get("id")]
    chosen = next((row for row in rows if str(row.get("id")) == str(belonging_id or "")), None)
    if chosen and _fits_room(chosen, room):
        return chosen
    return next((row for row in rows if _fits_room(row, room)), None)


def belongings_for_room(catalog: list[dict[str, Any]], room_id: str) -> list[dict[str, Any]]:
    room = str(room_id or "")
    return [row for row in catalog if isinstance(row, dict) and row.get("id") and _fits_room(row, room)]


def room_claim_label(room_label: str, name: str | None) -> str:
    room = str(room_label or "房间").strip() or "房间"
    cleaned = sanitize_room_name(name)
    if cleaned:
        return f"{cleaned}的{room}"
    return f"我的{room}"


def hero_slot_for_room(slots: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    row = slots.get(str(room_id or "")) if isinstance(slots, dict) else None
    if not isinstance(row, dict):
        return None
    try:
        x, y, w = float(row["x"]), float(row["y"]), float(row["w"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < w <= 40 and 0 <= x <= 100 and 0 <= y <= 100):
        return None
    return {"id": str(row.get("id") or room_id), "x": x, "y": y, "w": w}


def _fits_room(row: dict[str, Any], room_id: str) -> bool:
    rooms = row.get("rooms") or []
    if not isinstance(rooms, list):
        return False
    tokens = {str(item) for item in rooms}
    return "*" in tokens or room_id in tokens
