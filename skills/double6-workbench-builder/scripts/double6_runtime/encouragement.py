"""答错也暖：短句加下一步，不扣分、不改掌握。"""

from __future__ import annotations

from typing import Any

from .incentive_library import load_incentive_library

FORBIDDEN = ("偷懒", "-25", "扣分", "掉血", "笨", "差生", "惩罚", "清零")
DEFAULT_NEXT = "再看一眼题目，换一个答案。"
DEFAULT_LINES = (
    {"title": "没关系", "copy": "这次没对，很正常。"},
    {"title": "我们再试一次", "copy": "慢慢来，看清楚再选。"},
    {"title": "还没对，没事", "copy": "换个角度想想就好。"},
)


def _pick_line(item_id: str, lines: list[dict[str, str]]) -> dict[str, str]:
    pool = lines or list(DEFAULT_LINES)
    acc = sum(ord(char) for char in str(item_id or ""))
    return pool[acc % len(pool)]


def _clean_next(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or any(token in text for token in FORBIDDEN):
        return fallback
    return text[:80]


def project_incorrect_warmth(
    item_id: str = "",
    *,
    next_action: Any = None,
    baby: bool = False,
    enabled: bool = True,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = contract if isinstance(contract, dict) else encouragement_runtime_contract()
    if not enabled or pack.get("enabled") is False:
        return {
            "enabled": False,
            "title": "",
            "copy": "",
            "next": "",
            "affects_mastery": False,
        }
    line = _pick_line(item_id, list(pack.get("lines") or []))
    if baby:
        title = str(pack.get("baby_title") or "我们一起再试一次")
        copy = str(pack.get("baby_copy") or "做错了也没关系，我们再看一眼。")
    else:
        title = str(line.get("title") or "没关系")
        copy = str(line.get("copy") or "这次没对，很正常。")
    next_step = _clean_next(next_action, str(pack.get("default_next") or DEFAULT_NEXT))
    blob = f"{title}{copy}{next_step}"
    if any(token in blob for token in FORBIDDEN):
        title, copy, next_step = "没关系", "这次没对，很正常。", DEFAULT_NEXT
    return {
        "enabled": True,
        "title": title,
        "copy": copy,
        "next": next_step,
        "affects_mastery": False,
    }


def encouragement_runtime_contract() -> dict[str, Any]:
    library = load_incentive_library()
    row = next(
        (item for item in library["systems"] if item["system_id"] == "warm-incorrect"),
        {},
    )
    skin = row.get("skin") or {}
    return {
        "system_id": "warm-incorrect",
        "enabled": row.get("status") == "assembled" and row.get("default_on", True),
        "lines": list(skin.get("lines") or DEFAULT_LINES),
        "default_next": skin.get("default_next") or DEFAULT_NEXT,
        "baby_title": skin.get("baby_title") or "我们一起再试一次",
        "baby_copy": skin.get("baby_copy") or "做错了也没关系，我们再看一眼。",
    }
