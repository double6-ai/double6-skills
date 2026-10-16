"""进度投影：伙伴长大和花园只反映做过的事实，不等于掌握。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .incentive_library import load_incentive_library

GROWTH_STAGES = (
    {"id": "sprout", "min": 0, "label": "幼苗", "copy": "还很小，做过的事会让它长大一点"},
    {"id": "growing", "min": 3, "label": "在长大", "copy": "已经做过好几题了"},
    {"id": "familiar", "min": 10, "label": "很熟了", "copy": "经常见面"},
    {"id": "old-friend", "min": 20, "label": "老朋友", "copy": "陪你做过很多题了"},
)
ADULT_DEFAULT_LINES = (
    "今天先做最上面那一件就好。",
    "来了就算开始，不必一次做完。",
    "记下的都还在这台设备上。",
    "做完一件，再决定下一件。",
    "慢慢来，页面会等你。",
)


def _int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def project_growth(completed_count: Any) -> dict[str, Any]:
    done = _int(completed_count)
    current = GROWTH_STAGES[0]
    for row in GROWTH_STAGES:
        if done >= int(row["min"]):
            current = row
    return {
        "enabled": True,
        "stage_id": current["id"],
        "label": current["label"],
        "copy": current["copy"],
        "done": done,
        "affects_mastery": False,
    }


def project_garden(days: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    plots = []
    for row in list(days or [])[-7:]:
        if not isinstance(row, dict):
            continue
        full = bool(row.get("full"))
        has_any = bool(row.get("has_any"))
        plots.append(
            {
                "date": str(row.get("date") or "")[:10],
                "state": "bloom" if full else "sprout" if has_any else "empty",
            }
        )
    while len(plots) < 7:
        plots.insert(0, {"date": "", "state": "empty"})
    return {
        "enabled": True,
        "plots": plots[-7:],
        "caption": "只表示这几天来过，不是成绩",
        "affects_mastery": False,
    }


def project_visit_familiarity(days: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """近三日来过：投影在伙伴卡上，不是连续天数数字。"""
    plots: list[dict[str, Any]] = []
    for row in list(days or [])[-3:]:
        if not isinstance(row, dict):
            continue
        full = bool(row.get("full"))
        has_any = bool(row.get("has_any"))
        plots.append(
            {
                "date": str(row.get("date") or "")[:10],
                "state": "bloom" if full else "sprout" if has_any else "empty",
                "came": bool(has_any or full),
            }
        )
    while len(plots) < 3:
        plots.insert(0, {"date": "", "state": "empty", "came": False})
    plots = plots[-3:]
    consecutive = 0
    for item in reversed(plots):
        if item["came"]:
            consecutive += 1
        else:
            break
    copy = ""
    if consecutive >= 3:
        copy = "这几天都见到你了。"
    elif consecutive == 2:
        copy = "你昨天来过。"
    return {
        "enabled": True,
        "plots": plots,
        "consecutive": consecutive,
        "copy": copy,
        "affects_mastery": False,
    }


def last_seven_day_keys(today: date | None = None) -> list[str]:
    end = today or date.today()
    return [(end - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def project_fitness_daily_warmth(day_key: str) -> dict[str, Any]:
    library = load_incentive_library()
    row = next(
        (item for item in library["systems"] if item["system_id"] == "fitness-daily-warmth"),
        {},
    )
    raw_lines = ((row.get("skin") or {}).get("lines") or [])
    pool: list[dict[str, str]] = []
    for item in raw_lines:
        if isinstance(item, str) and item.strip():
            pool.append({"text": item.strip(), "cite": ""})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            pool.append({"text": str(item["text"]).strip(), "cite": str(item.get("cite") or "").strip()})
    if not pool:
        pool = [{"text": "来了就算开始，不必一次做完。", "cite": ""}]
    acc = sum(ord(char) for char in str(day_key or ""))
    pick = pool[acc % len(pool)]
    return {
        "enabled": True,
        "line": pick["text"],
        "cite": pick["cite"],
        "day_key": str(day_key or ""),
        "affects_mastery": False,
        "system_id": "fitness-daily-warmth",
    }


def project_adult_daily_warmth(day_key: str, *, lines: list[str] | None = None) -> dict[str, Any]:
    library = load_incentive_library()
    row = next(
        (item for item in library["systems"] if item["system_id"] == "adult-daily-warmth"),
        {},
    )
    skin = row.get("skin") or {}
    pool = [str(item).strip() for item in (lines or skin.get("lines") or ADULT_DEFAULT_LINES) if str(item).strip()]
    if not pool:
        pool = list(ADULT_DEFAULT_LINES)
    acc = sum(ord(char) for char in str(day_key or ""))
    return {
        "enabled": True,
        "line": pool[acc % len(pool)],
        "day_key": str(day_key or ""),
        "affects_mastery": False,
    }


def progress_runtime_contract() -> dict[str, Any]:
    load_incentive_library()
    return {
        "growth": {
            "system_id": "companion-growth-stage",
            "enabled": True,
            "stages": [dict(row) for row in GROWTH_STAGES],
        },
        "garden": {
            "system_id": "garden-progress",
            "enabled": True,
            "caption": "只表示这几天来过，不是成绩",
        },
        "visit": {
            "system_id": "garden-progress",
            "enabled": True,
            "window_days": 3,
            "open_counts_as_visit": True,
        },
        "adult_warmth": {
            "system_id": "adult-daily-warmth",
            "enabled": True,
            "lines": list(ADULT_DEFAULT_LINES),
        },
        "fitness_warmth": {
            "system_id": "fitness-daily-warmth",
            "enabled": True,
        },
    }
