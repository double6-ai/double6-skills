#!/usr/bin/env python3
"""拦减脂日常首页：必须是今天的体重、三餐和打卡，不能套小学勾组当主活动。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_fitness_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "fitness-daily-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "fitness-daily-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    errors: list[str] = []
    for marker, label in (
        ("data-fitness-daily-board", "健身专用今日板"),
        ("data-fitness-weight-form", "今日体重"),
        ("data-fitness-meal-form", "今日三餐"),
        ("data-fitness-checkin", "今日运动打卡"),
        ("data-fitness-calendar", "近七日记录"),
        ("data-fitness-warmth", "每日一句鼓励或诗词"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderFitnessDaily" not in helpers:
        errors.append("没有 renderFitnessDaily")
    if "data-fitness-weight-form" not in listeners or "data-fitness-meal-form" not in listeners:
        errors.append("没有记下体重或加一餐的监听")
    if "fitness-daily-runtime-v1" not in packs:
        errors.append("pack 未绑定健身日常 runtime")
    if "fitness_sprint_dashboard" not in packs:
        errors.append("pack 未使用健身专用 dashboard")
    if "保证瘦下来" not in renderers and "不保证瘦下来" not in renderers:
        errors.append("首页必须写明不保证瘦下来")
    if "假装视频在播" not in renderers:
        errors.append("首页必须写明不会假装跟练在播")
    if "勾第 1 组" in renderers:
        errors.append("健身首页还在用小学勾组当主活动")
    fitness_fn = renderers[renderers.find("def _fitness") : renderers.find("def _life")]
    if "insert_today_workboard=False" not in fitness_fn:
        errors.append("健身首页必须关掉通用今天待办板，不能再插「先完成一件最重要的事」")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    if "打开就能勾今晚组次" in profiles:
        errors.append("场景合同还在把小学勾组写成减脂日常的主目标")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    if "fitness-daily-warmth" not in library:
        errors.append("激励库缺少减脂日常暖话")
    if "千里之行，始于足下" not in library or "来了就算开始" not in library:
        errors.append("减脂日常暖话必须同时有鼓励句和公版诗句")
    if "renderFitnessWarmth" not in helpers:
        errors.append("没有 renderFitnessWarmth")
    return errors


def check_all() -> dict:
    errors = check_fitness_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查减脂日常今日板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"减脂日常今日板检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是体重、三餐和打卡，不是小学勾组。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
