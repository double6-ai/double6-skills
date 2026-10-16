#!/usr/bin/env python3
"""个人生活 1.1.0 专项门。"""

from __future__ import annotations

import json
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_all() -> dict:
    packs = json.loads((SKILL / "references/workbench-composition-packs.json").read_text(encoding="utf-8"))["packs"]
    pack = next(row for row in packs if row["scene_profile_id"] == "scene.personal-execution.personal-life-dashboard")
    builder = (SKILL / "scripts/double6_runtime/builder.py").read_text(encoding="utf-8")
    renderer = (SKILL / "scripts/double6_runtime/scene_renderers.py").read_text(encoding="utf-8")
    helpers = (SKILL / "references/runtimes/personal-life-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references/runtimes/personal-life-runtime-v1.listeners.js").read_text(encoding="utf-8")
    errors = []
    expected = ["personal-today", "personal-habits", "life-inspiration", "life-mood", "life-finance", "life-food", "life-movement", "life-reading", "life-vocabulary"]
    if pack["exact_module_ids"] != expected:
        errors.append("生活 pack 必须精确保留九个模块")
    for marker in ("data-life-today-page", "data-life-top-one-done", "data-life-mood-save", "data-life-habit-done"):
        if marker not in renderer and marker not in listeners:
            errors.append(f"今日一页缺少真实动作：{marker}")
    if "function lifeDedupedDates" not in helpers or "new Set" not in helpers or "function lifeFactStreak" not in helpers:
        errors.append("连续天数必须按去重完成日期确定性计算")
    if "剩余量÷剩余天数" not in renderer or "不会自动兑现" not in renderer:
        errors.append("目标等分与自定奖励边界未显式展示")
    if "data-double6-theme-selection-stage='design_time'" not in builder or "adult_theme_id" not in builder:
        errors.append("成人主题没有在设计阶段锁定")
    for forbidden in ["::ui:v1", "data-theme-switch", "D6_UI_STORAGE_KEY", "d6ApplyTheme"]:
        if forbidden in builder:
            errors.append(f"成品仍包含运行时主题切换：{forbidden}")
    return {"ok": not errors, "errors": errors, "module_count": len(pack["exact_module_ids"])}


if __name__ == "__main__":
    result = check_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
