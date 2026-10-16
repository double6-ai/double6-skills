#!/usr/bin/env python3
"""拦家庭今晚首页：必须是谁做什么、能勾掉、待当面说，不能是周历空表或假装已发送。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_household_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "household-handoff-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "household-handoff-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    tonight = renderers[renderers.find("def _household_tonight") : renderers.find("def _household(")]
    for marker, label in (
        ("data-household-tonight-board", "家庭今晚专用板"),
        ("data-household-chore-form", "今晚家务"),
        ("data-household-shop-list", "今晚要买"),
        ("data-household-tell-list", "待当面说"),
        ("data-household-warmth", "每日一句"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderHouseholdTonight" not in helpers:
        errors.append("没有 renderHouseholdTonight")
    if "data-household-chore-toggle" not in listeners:
        errors.append("没有勾今晚家务的监听")
    if "待当面说" not in listeners or "没有发给任何人" not in listeners:
        errors.append("交接必须能记下待当面说，且不能假装已发送")
    if "household-handoff-runtime-v1" not in packs:
        errors.append("pack 未绑定家庭今晚 runtime")
    if "household_tonight_dashboard" not in packs:
        errors.append("pack 未使用家庭今晚专用 dashboard")
    if "把今天放回整周里看" in tonight:
        errors.append("家庭今晚首页还在用周历当主活动")
    if "household-week-calendar-v1" in tonight:
        errors.append("家庭今晚不得用旧周历签名")
    if "爱心币" in tonight or "在一起" in tonight:
        errors.append("家庭今晚不得搬情侣游戏")
    if "页面不会发消息" not in tonight:
        errors.append("首页必须写明不会发消息")
    if "insert_today_workboard=False" not in tonight:
        errors.append("家庭今晚首页必须关掉通用今天待办板")
    if "household-handoff-warmth" not in library:
        errors.append("激励库缺少家庭今晚暖话")
    if "打开就勾今晚这几件家务" not in packs:
        errors.append("pack 主规则必须是今晚家务，不是周交接空表")
    if "executable_ready" not in profiles[profiles.find("scene.household-collaboration.weekly-household-handoff") :]:
        errors.append("场景成熟度未升到 executable_ready")
    return errors


def check_all() -> dict:
    errors = check_household_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查家庭今晚家务板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"家庭今晚检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是今晚谁做什么、能勾掉、待当面说。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
