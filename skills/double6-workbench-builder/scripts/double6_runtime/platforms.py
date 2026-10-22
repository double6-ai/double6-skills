"""内容运营：开箱平台跟随用户原话；用户没点名平台时才用默认组合。"""

from __future__ import annotations

from typing import Any

# (图标, 显示名, 别名, 主要形态)
PLATFORM_CATALOG: list[tuple[str, str, tuple[str, ...], str]] = [
    ("📕", "小红书", ("小红书", "红书", "xhs"), "图文"),
    ("📺", "B站", ("b站", "哔哩哔哩", "bilibili", "b 站"), "视频"),
    ("🟢", "公众号", ("公众号",), "长文"),
    ("🎬", "抖音", ("抖音", "douyin", "tiktok"), "短视频"),
    ("🎞️", "视频号", ("视频号",), "短视频"),
    ("🎵", "快手", ("快手",), "短视频"),
    ("🔥", "微博", ("微博",), "短帖"),
    ("❓", "知乎", ("知乎",), "长文"),
    ("📝", "即刻", ("即刻",), "短帖"),
    ("✖️", "X", ("推特", "twitter"), "短帖"),
    ("▶️", "YouTube", ("youtube", "油管"), "视频"),
]

DEFAULT_PLATFORMS = [("📕", "小红书"), ("🟢", "公众号"), ("🎬", "视频号 / 抖音"), ("✖️", "X / 即刻")]
DEFAULT_WEEK = [
    ("一", "长文", "公众号"), ("二", "短帖 ×2", "X / 即刻"), ("三", "图文", "小红书"), ("四", "短视频", "视频号 / 抖音"),
    ("五", "数字复盘", "全平台"), ("六", "回评论", "不新发"), ("日", "休息", "攒素材"),
]


def requested_platforms(text: str) -> list[tuple[str, str, str]]:
    """按原话中出现的先后返回 (图标, 平台, 形态)；没点名返回空列表。"""
    lowered = str(text or "").lower()
    hits: list[tuple[int, tuple[str, str, str]]] = []
    for icon, name, aliases, kind in PLATFORM_CATALOG:
        positions = [lowered.find(alias) for alias in aliases if alias in lowered]
        if positions:
            hits.append((min(positions), (icon, name, kind)))
    return [row for _, row in sorted(hits)]


def request_text(product: dict[str, Any]) -> str:
    return " ".join(str(row.get("text") or "") for row in product.get("facts", []) if isinstance(row, dict))


def creator_platforms(product: dict[str, Any]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]], bool]:
    """返回 (平台徽章, 一周节奏, 是否来自用户原话)。"""
    picked = requested_platforms(request_text(product))
    if not picked:
        return DEFAULT_PLATFORMS, DEFAULT_WEEK, False
    chips = [(icon, name) for icon, name, _ in picked]
    days = ["一", "二", "三", "四"]
    week = [(day, picked[index % len(picked)][2], picked[index % len(picked)][1]) for index, day in enumerate(days)]
    week += [("五", "数字复盘", "全部平台" if len(picked) > 1 else picked[0][1]), ("六", "回评论", "不新发"), ("日", "休息", "攒素材")]
    return chips, week, True


def personalize_content_starters(capabilities: list[dict[str, Any]], product: dict[str, Any]) -> None:
    """把素材卡与一鱼多吃里的平台换成用户点名的平台（只改本次构建的可见副本）。"""
    picked = requested_platforms(request_text(product))
    if not picked:
        return
    names = "/".join(name for _, name, _ in picked)
    split = " → ".join(f"{kind}版（{name}）" for _, name, kind in picked)
    for row in capabilities:
        for item in (row.get("starter") or {}).get("starter_items", []) or []:
            if item.get("item_id") == "content-input-1":
                item["body"] = f"来源（链接或出处）｜原话/数据｜我的观点｜发在哪（{names}）｜是否已核实"
            elif item.get("item_id") == "content-topic-2":
                item["title"] = f"一鱼多吃：一个选题拆{len(picked)}个平台" if len(picked) > 1 else "一个选题做成主版本和预告"
                item["body"] = split if len(picked) > 1 else f"{picked[0][2]}主版本（{picked[0][1]}）→ 30 秒预告或封面文案（{picked[0][1]}）"
