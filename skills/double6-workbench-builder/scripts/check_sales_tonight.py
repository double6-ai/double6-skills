#!/usr/bin/env python3
"""拦销售首页：必须能当场跟今天这一家，不能先记一条线索。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_sales_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "sales-pipeline-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "sales-pipeline-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    sales_fn = renderers[renderers.find("def _sales_followup") : renderers.find("def _teacher_class")]
    for marker, label in (
        ("data-sales-tonight-board", "销售专用今日板"),
        ("data-sales-today-act", "当场跟或改期"),
        ("data-sales-today-alias", "今天这一家"),
        ("data-sales-warmth", "每日一句鼓励"),
    ):
        if marker not in sales_fn and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderSalesTonight" not in helpers:
        errors.append("没有 renderSalesTonight")
    if "data-sales-today-act" not in listeners:
        errors.append("没有今天跟这家的监听")
    if "不会发消息" not in sales_fn:
        errors.append("首页必须写明不会发消息")
    if "不会预测成交" not in sales_fn:
        errors.append("首页必须写明不会预测成交")
    if "insert_today_workboard=False" not in sales_fn:
        errors.append("销售首页必须关掉通用今天待办板")
    if "开始准备" in sales_fn or "新增线索" in sales_fn:
        errors.append("首页还在用开始准备或新增线索当主活动")
    if "data-today-items" in sales_fn or "今天要处理" in sales_fn:
        errors.append("销售首页不得再插通用待办条")
    if "sales-pipeline-runtime-v1" not in packs:
        errors.append("pack 未绑定销售 runtime")
    if "sales_tonight_board_visible" not in packs:
        errors.append("pack 未声明今晚跟进验收")
    if "d6EarnStar" in helpers or "d6EarnStar" in listeners:
        errors.append("销售跟进不得给星星")
    if "sales-followup-warmth" not in library:
        errors.append("激励库缺少销售鼓励")
    if "先跟今天这一家就好" not in library:
        errors.append("销售激励必须是鼓励的话")
    sales_skin = library.split("sales-followup-warmth", 1)[-1].split("garden-progress", 1)[0]
    if "cite" in sales_skin and any(name in sales_skin for name in ("陆游", "杜甫", "苏轼", "《")):
        errors.append("销售激励只要鼓励的话，不要诗句")
    if "这台设备" in sales_skin:
        errors.append("销售鼓励不得用存储提醒冒充激励")
    if "data-fitness-weight" in sales_fn or "data-content-opening" in sales_fn or "data-exam-now" in sales_fn:
        errors.append("销售首页套了其它场景模版")
    return errors


def check_all() -> dict:
    errors = check_sales_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查销售今晚跟进板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"销售今晚跟进检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页能当场跟今天这一家，不是先记一条线索。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
