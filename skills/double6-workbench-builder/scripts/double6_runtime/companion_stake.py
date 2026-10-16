"""伙伴风险：只投影今天三站，不另开货币，不改掌握。"""

from __future__ import annotations

from typing import Any

from .incentive_library import companion_skins, load_incentive_library

MOODS = ("waiting", "hopeful", "almost", "well")
PORTRAIT_POLES = ("waiting", "well")
MOOD_TO_PORTRAIT_POLE = {
    "waiting": "waiting",
    "hopeful": "waiting",
    "almost": "waiting",
    "well": "well",
}
DEFAULT_SKIN_ID = "companion-puppy"
DEFAULT_NEED = 3


def portrait_pole_for_mood(mood: str | None) -> str:
    """hopeful / almost 复用 waiting 图，只在 well 换成好了图。"""
    return MOOD_TO_PORTRAIT_POLE.get(str(mood or ""), "waiting")


def _clamp_done(today_done: Any, today_need: int) -> int:
    try:
        done = int(today_done)
    except (TypeError, ValueError):
        done = 0
    return max(0, min(done, today_need))


def mood_for_progress(today_done: Any, today_need: int = DEFAULT_NEED) -> str:
    need = today_need if isinstance(today_need, int) and today_need > 0 else DEFAULT_NEED
    done = _clamp_done(today_done, need)
    if done >= need:
        return "well"
    if done >= 2:
        return "almost"
    if done >= 1:
        return "hopeful"
    return "waiting"


def normalize_companion_prefs(raw: Any, *, reward_enabled: bool = True) -> dict[str, Any]:
    skins = {row["system_id"] for row in companion_skins()}
    payload = raw if isinstance(raw, dict) else {}
    skin_id = str(payload.get("skin_id") or DEFAULT_SKIN_ID)
    if skin_id not in skins:
        skin_id = DEFAULT_SKIN_ID
    enabled = bool(reward_enabled) and payload.get("enabled") is not False
    return {"enabled": enabled, "skin_id": skin_id}


def resolve_skin(skin_id: str | None) -> dict[str, Any]:
    skins = {row["system_id"]: row for row in companion_skins()}
    return skins.get(str(skin_id or ""), skins[DEFAULT_SKIN_ID])


def project_companion(
    today_done: Any,
    today_need: int = DEFAULT_NEED,
    *,
    skin_id: str | None = None,
    baby: bool = False,
    reward_enabled: bool = True,
    prefs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从今天完成数派生心情。结果不含 mastery，也不写饥饿分。"""
    normalized = normalize_companion_prefs(prefs, reward_enabled=reward_enabled)
    if skin_id:
        normalized["skin_id"] = normalize_companion_prefs(
            {"enabled": normalized["enabled"], "skin_id": skin_id},
            reward_enabled=reward_enabled,
        )["skin_id"]
    need = today_need if isinstance(today_need, int) and today_need > 0 else DEFAULT_NEED
    done = _clamp_done(today_done, need)
    if not normalized["enabled"]:
        return {
            "enabled": False,
            "skin_id": normalized["skin_id"],
            "mood": None,
            "copy": "",
            "emoji": "",
            "label": "",
            "recover": "",
            "celebration": "",
            "done": done,
            "need": need,
            "affects_mastery": False,
        }
    skin = resolve_skin(normalized["skin_id"])
    body = skin.get("skin") or {}
    moods = body.get("moods") or {}
    mood = mood_for_progress(done, need)
    copy = str(moods.get(mood) or "")
    if baby and mood == "waiting" and body.get("baby_waiting"):
        copy = str(body["baby_waiting"])
    return {
        "enabled": True,
        "skin_id": skin["system_id"],
        "mood": mood,
        "copy": copy,
        "emoji": str(body.get("emoji") or "🐾"),
        "label": str(skin.get("label") or ""),
        "recover": str(body.get("recover") or ""),
        "celebration": str(body.get("celebration") or ""),
        "done": done,
        "need": need,
        "affects_mastery": False,
    }


def companion_runtime_contract(default_skin: str | None = None) -> dict[str, Any]:
    load_incentive_library()
    skins = []
    valid = set()
    for row in companion_skins():
        body = row.get("skin") or {}
        skins.append(
            {
                "system_id": row["system_id"],
                "label": row["label"],
                "emoji": body.get("emoji") or "🐾",
                "moods": dict(body.get("moods") or {}),
                "recover": body.get("recover") or "",
                "celebration": body.get("celebration") or "",
                "baby_waiting": body.get("baby_waiting") or "",
            }
        )
        valid.add(row["system_id"])
    skin_id = default_skin if default_skin in valid else DEFAULT_SKIN_ID
    return {
        "default_enabled": True,
        "default_skin": skin_id,
        "skins": skins,
    }
