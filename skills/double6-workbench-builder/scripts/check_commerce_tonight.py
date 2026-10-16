#!/usr/bin/env python3
"""拦电商首页：必须是处理今天这几单，不能是空经营台、实时库存或已发货。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_commerce_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "commerce-order-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "commerce-order-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    start = renderers.find("def _commerce_tonight")
    end = renderers.find("def _fitness(")
    tonight = renderers[start:end] if start >= 0 and end > start else ""
    if "def _commerce_tonight" not in renderers:
        errors.append("缺少电商今晚专用 renderer")
    for marker, label in (
        ("data-commerce-tonight-board", "电商今晚专用板"),
        ("data-commerce-order-form", "今晚这几单"),
        ("data-commerce-order-list", "订单列表"),
        ("data-commerce-stock-form", "库存快照"),
        ("data-commerce-service-list", "待在平台回"),
        ("data-commerce-warmth", "每日一句"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderCommerceTonight" not in helpers:
        errors.append("没有 renderCommerceTonight")
    if "data-commerce-order-form" not in listeners:
        errors.append("没有记下今晚这一单的监听")
    if "不是实时库存" not in helpers and "不是实时库存" not in tonight:
        errors.append("库存必须写明不是实时库存")
    if "不是已发货" not in listeners:
        errors.append("去平台处理不能假装已发货")
    if "没有发给任何人" not in listeners:
        errors.append("客服必须能记下待在平台回，且不能假装已发送")
    if "commerce-order-runtime-v1" not in packs:
        errors.append("pack 未绑定电商今晚 runtime")
    if "commerce_tonight_dashboard" not in packs:
        errors.append("pack 未使用电商今晚专用 dashboard")
    if "generic-priority-board-v1" in tonight:
        errors.append("电商今晚不得用通用空经营台签名")
    if "现在要做什么" in tonight:
        errors.append("电商今晚首页还在用模块卡片当主活动")
    denied = tonight.replace("不是已发货", "").replace("也不是已发货", "")
    if "已发货" in denied:
        errors.append("首页不得把本地勾选写成已发货")
    denied_shop = tonight.replace("也不连接店铺", "").replace("不连接店铺", "")
    if "自动退款" in tonight or "连接店铺" in denied_shop:
        errors.append("电商今晚不得声称自动退款或连接店铺")
    if "不连接店铺" not in tonight and "也不连接店铺" not in tonight:
        errors.append("首页必须写明不连接店铺")
    if "实时库存" in tonight.replace("不是实时库存", ""):
        errors.append("电商今晚不得声称实时库存")
    if "页面不会发货" not in tonight and "不发货" not in tonight:
        errors.append("首页必须写明不会发货")
    if "待在平台回" not in tonight:
        errors.append("客服必须保持待在平台回")
    if "insert_today_workboard=False" not in tonight:
        errors.append("电商今晚首页必须关掉通用今天待办板")
    if "commerce-order-warmth" not in library:
        errors.append("激励库缺少电商今晚暖话")
    if "打开就处理今天这几单" not in packs:
        errors.append("pack 主规则必须是今晚订单，不是空经营台")
    builder = (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    engine = (SKILL / "scripts" / "double6_runtime" / "atomic_engine.py").read_text(encoding="utf-8")
    if "data-ledger-csv-tool" not in builder or '"commerce-orders"' not in engine:
        errors.append("店铺订单 CSV 预览必须在成人设置里")
    if "data-ledger-csv" in tonight:
        errors.append("电商今晚首页不得放 CSV 导入")
    profile_slice = profiles[profiles.find("scene.ecommerce-operations.product-order-ops") :]
    if "executable_ready" not in profile_slice[:800]:
        errors.append("场景成熟度未升到 executable_ready")
    return errors


def check_all() -> dict:
    errors = check_commerce_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查电商今晚订单板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"电商今晚检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是今天这几单、库存快照、待在平台回。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
