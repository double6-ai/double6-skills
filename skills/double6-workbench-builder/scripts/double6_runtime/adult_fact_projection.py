"""成人工作台的确定性事实投影。

只处理用户目标、完成日期和本地流水；不推断掌握、健康、考试能力或业务结果。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping


def _day(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def deduped_completion_dates(values: Iterable[Any]) -> list[str]:
    """返回去重、升序的有效完成日期。"""
    return sorted({parsed.isoformat() for value in values if (parsed := _day(value))})


def completion_streak(values: Iterable[Any], *, as_of: str | date | None = None) -> int:
    """从 as_of 向前计算连续完成日；同一天多次完成只算一天。"""
    anchor = as_of if isinstance(as_of, date) else _day(as_of)
    anchor = anchor or date.today()
    completed = {date.fromisoformat(value) for value in deduped_completion_dates(values)}
    count = 0
    cursor = anchor
    while cursor in completed:
        count += 1
        cursor -= timedelta(days=1)
    return count


def project_goal(
    *,
    target: float | int | None,
    current: float | int | None,
    deadline: str | date | None,
    completion_dates: Iterable[Any] = (),
    reward: str = "",
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """投影进度、剩余量、目标等分和里程碑。

    `suggested_daily` 只是剩余量÷剩余天数的目标等分，不是专业建议。
    """
    anchor = as_of if isinstance(as_of, date) else _day(as_of)
    anchor = anchor or date.today()
    due = deadline if isinstance(deadline, date) else _day(deadline)
    safe_target = max(0.0, float(target or 0))
    safe_current = max(0.0, float(current or 0))
    remaining = max(0.0, safe_target - safe_current)
    progress = 0.0 if safe_target <= 0 else min(100.0, safe_current / safe_target * 100)
    remaining_days = max(0, (due - anchor).days + 1) if due else None
    suggested_daily = (
        remaining / remaining_days
        if remaining_days and remaining > 0
        else (0.0 if remaining <= 0 else None)
    )
    milestones = [25, 50, 75, 100]
    reached = max((value for value in milestones if progress >= value), default=0)
    return {
        "engine_id": "adult_fact_projection",
        "as_of": anchor.isoformat(),
        "target": safe_target,
        "current": safe_current,
        "remaining": remaining,
        "progress_percent": round(progress, 2),
        "remaining_days": remaining_days,
        "suggested_daily": None if suggested_daily is None else round(suggested_daily, 2),
        "suggested_daily_label": "目标等分（剩余量÷剩余天数），不是专业建议",
        "completion_dates": deduped_completion_dates(completion_dates),
        "completion_streak": completion_streak(completion_dates, as_of=anchor),
        "milestone_percent": reached,
        "celebrate_locally": bool(reached and reward.strip()),
        "reward": reward.strip(),
        "claims": {
            "changes_mastery": False,
            "health_conclusion": False,
            "exam_ability": False,
            "business_outcome": False,
            "external_redemption": False,
        },
    }


def project_ledger(
    rows: Iterable[Mapping[str, Any]],
    *,
    amount_field: str = "amount",
    positive_types: Iterable[str] = (),
    negative_types: Iterable[str] = (),
    type_field: str = "entry_type",
) -> float:
    """只按本地流水确定性加减，不连接账户或猜测缺失数据。"""
    positive, negative = set(positive_types), set(negative_types)
    total = 0.0
    for row in rows:
        kind = str(row.get(type_field) or "")
        try:
            amount = float(row.get(amount_field) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if kind in positive:
            total += amount
        elif kind in negative:
            total -= amount
    return round(total, 2)
