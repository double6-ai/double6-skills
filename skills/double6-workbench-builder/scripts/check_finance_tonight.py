#!/usr/bin/env python3
"""拦月度记账首页：必须是记今晚这笔，不能是空月结台、已申报或银行余额。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))


def check_finance_tonight_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "finance-bookkeeping-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "finance-bookkeeping-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    profiles = (SKILL / "references" / "scene-profiles.json").read_text(encoding="utf-8")
    library = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    errors: list[str] = []
    tonight = renderers[renderers.find("def _finance_tonight") : renderers.find("def _household_tonight")]
    if "def _finance_tonight" not in renderers:
        errors.append("缺少月度记账今晚专用 renderer")
        tonight = ""
    for marker, label in (
        ("data-finance-tonight-board", "记账今晚专用板"),
        ("data-finance-log-form", "记今晚这笔"),
        ("data-finance-today-total", "今日合计"),
        ("data-finance-voucher-list", "凭证勾选"),
        ("data-finance-tax-list", "税务材料"),
        ("data-finance-warmth", "每日一句"),
    ):
        if marker not in renderers and marker not in helpers:
            errors.append(f"缺少 {label}（{marker}）")
    if "renderFinanceTonight" not in helpers:
        errors.append("没有 renderFinanceTonight")
    if "data-finance-log-form" not in listeners:
        errors.append("没有记下今晚这笔的监听")
    if "不是银行余额" not in helpers and "不是银行余额" not in tonight:
        errors.append("今日合计必须写明不是银行余额")
    if "不是已申报" not in listeners:
        errors.append("税务交接不能假装已申报")
    if "finance-bookkeeping-runtime-v1" not in packs:
        errors.append("pack 未绑定记账今晚 runtime")
    if "finance_tonight_dashboard" not in packs:
        errors.append("pack 未使用记账今晚专用 dashboard")
    if "本月先核哪一笔" in tonight:
        errors.append("记账今晚首页还在用月结空台当主活动")
    if "finance-month-close-console-v1" in tonight:
        errors.append("记账今晚不得用旧月结签名")
    denied = tonight.replace("也不是已申报", "").replace("不是已申报", "")
    if "已申报" in denied:
        errors.append("首页不得把材料写成已申报")
    tax_at = tonight.find("data-finance-tax-card")
    tax_card = tonight[tax_at : tonight.find("</article>", tax_at) + 10] if tax_at != -1 else ""
    if "不是已申报" not in tax_card:
        errors.append("税务材料卡必须写明不是已申报")
    privacy_at = tonight.find("finance-privacy")
    privacy = tonight[privacy_at : tonight.find("</aside>", privacy_at) + 8] if privacy_at != -1 else ""
    if "不是银行余额" in privacy or "不是已申报" in privacy:
        errors.append("首页隐私条不能再当税/银行免责壁纸")
    if "自动报税" in tonight or "连接银行" in tonight or "永不丢失" in tonight:
        errors.append("记账今晚不得声称自动报税、银行连接或数据永不丢失")
    if "页面不会去银行" not in tonight and "不会去银行" not in tonight:
        errors.append("首页必须写明不会去银行取数")
    if "待专业处理" not in tonight:
        errors.append("税务必须保持待专业处理")
    if "placeholder='29.9'" in tonight:
        errors.append("金额框占位不得写成种子金额 29.9，以免像已经填过")
    if "今晚还没记下" not in helpers or "今天还没有流水" not in helpers:
        errors.append("记账首页空账必须能自己记第一笔，不能只在有种子时才像账本")
    pack_payload = json.loads((SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8"))
    finance_pack = next(
        (row for row in pack_payload.get("packs") or [] if row.get("composition_id") == "composition.finance.monthly-bookkeeping-v1"),
        {},
    )
    tx_seeds = [row for row in finance_pack.get("tonight_seeds") or [] if row.get("module_id") == "finance-transactions"]
    if tx_seeds:
        errors.append("记账开箱不得预填流水。首页应是空账，让人自己记第一笔。")
    if any("晚饭" in str(((row.get("values") or {}).get("title") or "")) for row in finance_pack.get("tonight_seeds") or []):
        errors.append("开箱种子不能写成晚饭账，那像别人已经记过")
    if "insert_today_workboard=False" not in tonight:
        errors.append("记账今晚首页必须关掉通用今天待办板")
    if "data-today-workboard" not in tonight:
        errors.append("记账今晚板必须自己带今天入口标记，不能缺 evaluate 骨架")
    if "data-double6-primary-action='true'" not in tonight:
        errors.append("记账首页必须有一个主动作")
    if "今天要处理" in tonight:
        errors.append("记账首页不能套通用今天待办板文案")
    if "_tonight_evaluate_shell" not in tonight:
        errors.append("记账首页必须列出全部房间入口")
    if "finance-bookkeeping-warmth" not in library:
        errors.append("激励库缺少记账今晚暖话")
    if "打开就记今晚这笔" not in packs:
        errors.append("pack 主规则必须是今晚记账，不是空月结")
    finance_nav = packs[packs.find('"composition_id": "composition.finance.monthly-bookkeeping-v1"') : packs.find('"composition_id": "composition.ecommerce.product-order-ops-v1"')]
    for module_id, label in (
        ("finance-transactions", "流水"),
        ("finance-vouchers", "凭证"),
        ("finance-tax", "税务"),
        ("finance-review", "复盘"),
        ("finance-audit", "审计"),
    ):
        if f'"{module_id}"' not in finance_nav:
            errors.append(f"记账必须保留{label}房间，不能靠收侧栏假装干净")
    if "tonight_nav_module_ids" in finance_nav:
        errors.append("记账不得用 tonight_nav 藏凭证/税/复盘/审计")
    if '"link_label": "待核验"' in finance_nav or '"link_label": "本机记下"' in finance_nav:
        errors.append("记账标题要说缺票和对账、重复票据，不能写待核验")
    if '"link_label": "重复票据"' not in finance_nav or '"link_label": "缺票和对账"' not in finance_nav:
        errors.append("复盘和审计标题必须是缺票和对账、重复票据")
    if "判断缺票" not in tonight or "判断重复票" not in tonight:
        errors.append("首页还要能跳进缺票和重复票，侧栏本身仍须保留这两个房间")
    if "数值 ${index+1}" in helpers or "数值 ${index+1}" in (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8"):
        errors.append("记账演算框不能叫数值 1 / 数值 2，必须写收入、支出")
    starters = (SKILL / "references" / "scene-capability-starters.json").read_text(encoding="utf-8")
    starter_payload = json.loads(starters)
    starter_items = [item for scene in starter_payload["scenes"] for capability in scene["capabilities"] for item in capability.get("starter_items", [])]
    cash_item = next((item for item in starter_items if item.get("item_id") == "fin-cash-1"), {})
    if cash_item.get("input_labels") != ["收入", "支出"]:
        errors.append("月度收支演示必须标明收入和支出，不能只给两个数字")
    if "fin-recon-1" not in starters or "12 元留着等票" not in starters:
        errors.append("对账复盘必须有可判断的开箱题，不能只剩空说明")
    if "fin-risk-1" not in starters or "同一张票出现两次" not in starters:
        errors.append("审计事项必须能判断重复票据，不能只写待人工复核")
    if not any(item.get("module_ids") == ["finance-vouchers"] and "勾掉今晚外卖小票" in str(item.get("title") or "") for item in starter_items):
        errors.append("凭证必须有自己的勾票活，不能拿收支演算充数")
    if "fin-recon-2" not in starters or "fin-risk-2" not in starters:
        errors.append("复盘和审计必须各有不同的第二题，不能同题")
    from double6_runtime.content_mines import check_finance_room_starters_are_bound

    errors.extend(check_finance_room_starters_are_bound())
    builder = (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    engine = (SKILL / "scripts" / "double6_runtime" / "atomic_engine.py").read_text(encoding="utf-8")
    if "data-ledger-csv-tool" not in builder or "data-ledger-csv-preview" not in builder:
        errors.append("记账台账 CSV 预览必须在成人设置里")
    if '"finance-transactions"' not in engine:
        errors.append("记账流水必须在 CSV 允许名单里")
    if "data-ledger-csv" in tonight:
        errors.append("记账今晚首页不得放 CSV 导入")
    profile_slice = profiles[profiles.find("scene.finance-tax-contract.monthly-bookkeeping") :]
    if "executable_ready" not in profile_slice[:800]:
        errors.append("场景成熟度未升到 executable_ready")
    return errors


def check_all() -> dict:
    errors = check_finance_tonight_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查月度记账今晚板")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"月度记账检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("首页是记今晚这笔、今日合计、凭证可勾、税待专业处理。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
