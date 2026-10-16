#!/usr/bin/env python3
"""拦自媒体首页：必须能当场写今晚这篇开头，不能先记一条观察。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_content_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "content-pipeline-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "content-pipeline-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    creator_fn = renderers[renderers.find("def _creator") : renderers.find("def _personal_week")]
    for marker, label in (
        ("data-content-tonight-board", "自媒体专用今日板"),
        ("data-content-opening-form", "当场写开头"),
        ("data-content-opening", "开头输入"),
        ("data-content-warmth", "每日一句"),
        ("data-content-piece-steps", "这篇走到哪"),
        ("data-content-week", "近七日写过"),
    ):
        if marker not in creator_fn and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderContentTonight" not in helpers:
        errors.append("没有 renderContentTonight")
    if "data-content-opening-form" not in listeners:
        errors.append("没有留下开头的监听")
    if "也不会替你发布" not in creator_fn:
        errors.append("首页必须写明不会替你发布")
    if "insert_today_workboard=False" not in creator_fn:
        errors.append("自媒体首页必须关掉通用今天待办板")
    if "刚发现什么" in creator_fn or "继续选题" in creator_fn:
        errors.append("首页还在用先记一条或继续选题当主活动")
    if "data-today-items" in creator_fn or "今天要处理" in creator_fn:
        errors.append("自媒体首页不得再插通用待办条")
    if "content-pipeline-runtime-v1" not in packs:
        errors.append("pack 未绑定内容 runtime")
    if "content_tonight_board_visible" not in packs:
        errors.append("pack 未声明今晚写稿验收")
    if "d6EarnStar" in helpers or "d6EarnStar" in listeners:
        errors.append("自媒体写稿不得给星星")
    if "content-tonight-warmth" not in library:
        errors.append("激励库缺少自媒体暖话")
    if "先写完这一段" not in library:
        errors.append("自媒体暖话必须有写稿鼓励句")
    if "草稿先留在这台设备上" in library or "记下的都还在这台设备上" in library.split("content-tonight-warmth", 1)[-1].split("garden-progress", 1)[0]:
        errors.append("自媒体暖话不得用存储提醒冒充激励")
    if "confirmed||queued" in helpers or "人工发布',confirmed||queued" in helpers:
        errors.append("记下已复制不得点亮人工发布")
    if "需要时再打开工作面" in creator_fn:
        errors.append("首页不得把管线计数当主视觉")
    if "data-fitness-weight" in creator_fn or "data-exam-now" in creator_fn or "data-teacher-duty" in creator_fn:
        errors.append("自媒体首页套了其它场景模版")
    if "renderContentWeek" not in helpers:
        errors.append("没有近七日写过")
    return errors


def check_all() -> dict:
    errors = check_content_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查自媒体今晚写稿板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"自媒体今晚写稿检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页能当场写今晚这篇开头，不是先记一条观察。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
