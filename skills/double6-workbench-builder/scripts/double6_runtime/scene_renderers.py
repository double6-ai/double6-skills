"""场景首页 renderer：首屏聚焦，已选模块全部进侧栏。丰富度靠每个房间有活，不靠少开房间。"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


VISUAL_CONTRACT_VERSION = "scene_dashboard_v1"

NAV_ICON_RULES = [
    (("灵感",), "lightbulb"),
    (("心情", "树洞"), "edit_note"),
    (("储蓄",), "wallet"),
    (("语文", "文章", "文案", "脚本", "阅读", "读书"), "article"),
    (("数学", "口算", "计算"), "calculate"),
    (("英语", "翻译", "外语"), "translate"),
    (("信息输入", "录入", "填写"), "edit_note"),
    (("选题", "灵感", "创意"), "lightbulb"),
    (("制作", "生产"), "checklist"),
    (("备课", "教学", "课堂", "课程"), "school"),
    (("班务", "作业"), "assignment"),
    (("学情", "成绩", "分析"), "analytics"),
    (("客户", "项目"), "work"),
    (("交付", "推进"), "task_alt"),
    (("报价", "合同", "协议"), "description"),
    (("条件", "决策", "偏好"), "checklist"),
    (("行程", "路线", "逐日"), "route"),
    (("预订", "酒店", "住宿"), "hotel"),
    (("收支", "财务", "预算", "账"), "wallet"),
    (("发票", "税务"), "payments"),
    (("凭证", "票据"), "receipt"),
    (("家务", "清洁"), "cleaning"),
    (("采购", "购物"), "shopping_cart"),
    (("家庭", "家人"), "family"),
    (("饮水", "喝水"), "water_drop"),
    (("饮食", "餐", "食物"), "restaurant"),
    (("训练日志", "运动日志"), "article"),
    (("训练", "健身", "运动"), "fitness"),
    (("日程", "日期", "排期", "预约"), "calendar"),
    (("发布",), "publish"),
    (("资料", "素材", "文件"), "folder"),
    (("复盘", "日志", "记录"), "article"),
    (("清单", "事项", "任务"), "list_alt"),
]


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


CIVIL_NAV_ORDER = ["exam-practice", "exam-materials", "exam-today", "exam-goal", "exam-errors"]


def _module_rows(capabilities: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(row["recommendation_module_id"]),
            "name": str(row["name"]),
            "description": str(row.get("description", "")),
        }
        for row in capabilities
    ]


def _civil_nav_rank(module_id: str) -> int:
    try:
        return CIVIL_NAV_ORDER.index(module_id)
    except ValueError:
        return len(CIVIL_NAV_ORDER)


def _nav_icon_id(label: str) -> str:
    return next((icon_id for words, icon_id in NAV_ICON_RULES if any(word in label for word in words)), "list_alt")


NAV_LABEL_RULES = [
    (("工作日志", "实验"), "日志"),
    (("写作",), "写作"),
    (("首页",), "首页"),
    (("复盘",), "复盘"),
    (("收件",), "收件"),
    (("线索",), "线索"),
    (("客户",), "客户"),
    (("跟进",), "跟进"),
    (("订单与售后",), "订单"),
    (("库存",), "库存"),
    (("商品",), "商品"),
    (("客服",), "客服"),
    (("研究问题",), "问题"),
    (("文献",), "出处"),
    (("写作",), "结论"),
    (("询盘", "订单"), "询盘"),
    (("询盘",), "询盘"),
    (("报价",), "报价"),
    (("数据", "备份", "恢复"), "数据"),
    (("错过的再做",), "错题"),
    (("错题",), "错题"),
    (("申论和面试",), "申论面试"),
    (("面试",), "面试"),
    (("申论",), "申论"),
    (("今晚的题",), "做题"),
    (("公式和申论",), "素材"),
    (("今晚科目",), "科目"),
    (("今晚计划",), "计划"),
    (("今晚这笔",), "记账"),
    (("今晚的票",), "凭证"),
    (("待专业处理",), "税务"),
    (("缺票和对账",), "复盘"),
    (("重复票据",), "审计"),
    (("积分", "宠物", "奖励"), "奖励"),
    (("语文",), "语文"),
    (("数学", "口算"), "数学"),
    (("英语",), "英语"),
    (("阅读",), "阅读"),
    (("传统文化",), "文化"),
    (("科学",), "科学"),
    (("逻辑",), "逻辑"),
    (("运动",), "运动"),
    (("训练", "健身"), "训练"),
    (("来源",), "来源"),
    (("选题",), "选题"),
    (("任务书",), "任务书"),
    (("制作",), "制作"),
    (("排期", "发布"), "排期"),
    (("执行", "计划", "待办", "日程"), "计划"),
    (("灵感",), "灵感"),
    (("心情",), "心情"),
    (("记账", "储蓄", "收支"), "记账"),
    (("饮食",), "饮食"),
]


def _compact_nav_label(label: str) -> str:
    """侧栏只放高辨识度短标签；完整模块名继续留在 aria-label 与页面正文。"""
    if len(label) <= 4:
        return label
    return next((short for words, short in NAV_LABEL_RULES if any(word in label for word in words)), label)


def _dedupe_nav(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """短标签撞名时回退为完整名称；导航文字允许换行，但不截断、不重名。"""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["nav_label"]] = counts.get(item["nav_label"], 0) + 1
    result = []
    for item in items:
        if counts[item["nav_label"]] > 1 and item["view_id"] != "data-tools":
            item = {**item, "nav_label": item["label"]}
        result.append(item)
    labels = [item["nav_label"] for item in result]
    if len(labels) != len(set(labels)):
        raise ValueError(f"导航标签重名：{labels}")
    return result


def _module_tiles(rows: list[dict[str, str]], emoji_by_id: dict[str, str]) -> str:
    return "".join(
        f"<a class='module-tile' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'>"
        f"<span aria-hidden='true'>{_e(emoji_by_id.get(row['id'], '🧩'))}</span><div><strong>{_e(row['name'])}</strong>"
        f"<small data-dashboard-module-status='{_e(row['id'])}'>{_e(row['description'])}</small></div></a>"
        for row in rows
    )


def _ensure_all_modules_reachable(dashboard_html: str, capabilities: list[dict[str, Any]], emojis: list[str]) -> str:
    """任何 renderer 只要首页漏掉已确认模块，就在首页末尾补一组“其他工作面”入口，保证全部可达。"""
    rows = _module_rows(capabilities)
    missing = [row for row in rows if f"data-dashboard-module-link='{row['id']}'" not in dashboard_html]
    if not missing:
        return dashboard_html
    emoji_by_id = {row["id"]: emoji for row, emoji in zip(rows, emojis, strict=False)}
    block = (
        "<section class='all-modules dashboard-panel' data-dashboard-all-modules><div class='panel-heading'>"
        "<div><span class='eyebrow'>其他工作面</span><h2>已确认的其余模块</h2></div></div>"
        f"<div class='all-modules-grid'>{_module_tiles(missing, emoji_by_id)}</div></section>"
    )
    closing = dashboard_html.rfind("</section>")
    return dashboard_html[:closing] + block + dashboard_html[closing:]


def _nav_item(view_id: str, label: str, emoji: str) -> dict[str, str]:
    return {"view_id": view_id, "label": label, "nav_label": _compact_nav_label(label), "emoji": emoji}


def _peer_nav_items(
    capabilities: list[dict[str, Any]],
    emojis: list[str],
    pack: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """已选模块全部进侧栏。不得靠收目录假装干净；pack 只用于核对范围，不删房间。"""
    selected = [str(value) for value in (pack or {}).get("exact_module_ids") or []]
    cap_ids = [str(row["recommendation_module_id"]) for row in capabilities]
    if selected and set(selected) != set(cap_ids):
        raise ValueError(f"侧栏范围与已选模块不一致：pack={selected} compiled={cap_ids}")
    module_items = [
        _nav_item(f"module-{row['recommendation_module_id']}", str(row["name"]), emoji)
        for row, emoji in zip(capabilities, emojis, strict=True)
    ]
    if (pack or {}).get("scene_profile_id") == "scene.exam-preparation.civil-service-exam":
        module_items.sort(key=lambda item: _civil_nav_rank(item["view_id"].replace("module-", "", 1)))
    nav_items = [_nav_item("dashboard", "首页", "🏠")]
    nav_items.extend(module_items)
    nav_items.append(_nav_item("data-tools", "数据", "💾"))
    return nav_items


def _link(row: dict[str, str], label: str | None = None, class_name: str = "text-link") -> str:
    return (
        f"<a class='{class_name}' href='#module-{_e(row['id'])}' "
        f"data-dashboard-module-link='{_e(row['id'])}'>{_e(label or row['name'])}</a>"
    )


def _composition_pack(product: dict[str, Any]) -> dict[str, Any]:
    return ((product.get("recommendation_plan") or {}).get("composition_contract") or {}).get("pack") or {}


def _attention_regions(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["region_id"]): row for row in pack.get("attention_model", {}).get("regions", []) if row.get("region_id")}


def _region_label(regions: dict[str, dict[str, Any]], region_id: str, fallback: str) -> str:
    return str((regions.get(region_id) or {}).get("label") or fallback)


def _visible_home_kicker(pack: dict[str, Any], product: dict[str, Any]) -> str:
    rule = str((pack.get("attention_model") or {}).get("home_rule") or "").strip()
    if rule and "_" not in rule and "orients" not in rule:
        return rule
    return str(product.get("title") or "今晚这一件")


def _is_fitness_tonight(pack: dict[str, Any]) -> bool:
    if "fat-loss-routine" in str(pack.get("scene_profile_id") or ""):
        return True
    now = next(
        (row for row in pack.get("attention_model", {}).get("regions", []) if row.get("region_id") == "now"),
        {},
    )
    now_ids = set(now.get("source_module_ids") or [])
    now_mod = next((row for row in pack.get("modules") or [] if row.get("module_id") in now_ids), None)
    return str((now_mod or {}).get("primary_job") or "") == "do_tonight_set"


def _region_module(regions: dict[str, dict[str, Any]], region_id: str, by_id: dict[str, dict[str, str]], fallback: dict[str, str]) -> dict[str, str]:
    module_ids = list((regions.get(region_id) or {}).get("source_module_ids") or [])
    return next((by_id[module_id] for module_id in module_ids if module_id in by_id), fallback)


def _tonight_evaluate_shell(rows: list[dict[str, str]]) -> str:
    """专用今晚板自己带验收骨架：房间入口、备份，不插入通用「今天要处理」板。"""
    links = "".join(
        f"<a class='text-link' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'>{_e(row['name'])}</a>"
        for row in rows
    )
    return (
        f"<nav class='tonight-room-strip' aria-label='今晚的房间'>{links}</nav>"
        "<div class='today-actions'>"
        "<button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span>"
        "<input class='hidden' data-double6-hook='quick-import' type='file' accept='application/json,text/plain,.json,.txt'>"
        "</label></div>"
    )


def _workspace_links(by_id: dict[str, dict[str, str]], module_ids: list[str]) -> str:
    return "".join(
        _link(by_id[module_id], by_id[module_id]["name"], "mini-action")
        for module_id in module_ids
        if module_id in by_id
    )


def _flow_title(pack: dict[str, Any], by_id: dict[str, dict[str, str]], fallback: str) -> str:
    declared = str(pack.get("attention_model", {}).get("flow_title") or "").strip()
    if declared:
        return declared
    names = [by_id[module_id]["name"] for module_id in pack.get("exact_module_ids", []) if module_id in by_id]
    return " → ".join(names) or fallback


DASHBOARD_TEMPLATE_FILE = "workbench-dashboard-templates.json"


def _dashboard_templates() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "references" / DASHBOARD_TEMPLATE_FILE
    value = json.loads(path.read_text(encoding="utf-8"))
    templates = value.get("templates")
    if value.get("schema_version") != 1 or not isinstance(templates, dict) or not templates:
        raise ValueError("dashboard template registry 无效")
    return templates


def _fill_dashboard(html: str, mapping: dict[str, str]) -> str:
    filled = html
    for key, value in mapping.items():
        filled = filled.replace("{" + key + "}", value)
    leftover = [part for part in filled.split("{")[1:] if "}" in part]
    if leftover:
        raise ValueError(f"dashboard 模板仍有未替换占位符：{leftover[0].split('}', 1)[0]}")
    return filled


def _pack_home(
    product: dict[str, Any],
    template: dict[str, Any],
    capabilities: list[dict[str, Any]],
    detail_renderer: Callable[[dict[str, Any], bool, str], str],
    emojis: list[str],
    renderer_id: str,
) -> dict[str, Any]:
    """按 pack.dashboard_template_id 装配成熟场景首页，不再在函数里写死三套 HTML。"""
    rows = _module_rows(capabilities)
    by_id = {row["id"]: row for row in rows}
    pack = _composition_pack(product)
    spec_id = str(pack.get("dashboard_template_id") or "").strip()
    spec = _dashboard_templates().get(spec_id)
    if not spec or spec.get("renderer_id") != renderer_id:
        raise ValueError(f"composition dashboard template 未登记或 renderer 不匹配：{spec_id or renderer_id}")
    regions = _attention_regions(pack)
    fallback_now = by_id.get(str(spec.get("now_fallback_module_id") or ""), rows[0])
    fallback_capture = by_id.get(str(spec.get("capture_fallback_module_id") or ""), rows[0])
    now = _region_module(regions, "now", by_id, fallback_now)
    capture = _region_module(regions, "capture", by_id, fallback_capture)
    attention_module_id = str(spec.get("attention_link_module_id") or now["id"])
    attention_target = by_id.get(attention_module_id, now)
    attention_label_text = str(spec.get("attention_link_label") or f"打开{attention_target['name']}")
    dashboard = _fill_dashboard(
        str(spec["html"]),
        {
            "hero": _hero(
                product,
                template,
                str(spec.get("hero_eyebrow") or ""),
                str(spec.get("hero_title") or product.get("title") or ""),
                str(spec.get("hero_body") or ""),
                now,
                f"打开{now['name']}",
            ),
            "flow_eyebrow": _e(_region_label(regions, "flow", str(spec.get("flow_eyebrow_fallback") or "对象链"))),
            "flow_title": _e(_flow_title(pack, by_id, str(spec.get("flow_title_fallback") or "模块工作链"))),
            "capture_label": _e(_region_label(regions, "capture", str(spec.get("capture_label_fallback") or "先记下什么？"))),
            "capture_name": _e(capture["name"]),
            "now_link": _link(now, f"打开{now['name']}", "text-link"),
            "attention_link": _link(attention_target, attention_label_text, "text-link"),
            "attention_label": _e(_region_label(regions, "attention", str(spec.get("attention_label_fallback") or "只显示会阻塞推进的缺口"))),
            "workspace_links": _workspace_links(by_id, list(pack.get("exact_module_ids") or by_id)),
        },
    )
    return _base_result(
        renderer_id,
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        list(spec.get("required_hooks") or []),
        insert_today_workboard=False,
        product=product,
    )


def _hero(
    product: dict[str, Any],
    template: dict[str, Any],
    eyebrow: str,
    title: str,
    body: str,
    primary: dict[str, str],
    action_label: str,
    action_href: str | None = None,
) -> str:
    href = action_href or f"#module-{_e(primary['id'])}"
    return (
        "<header class='scene-hero' data-first-screen-slot='hero'>"
        f"<div><span class='hero-kicker'>{_e(eyebrow)}</span><h1>{_e(title)}</h1><p>{_e(body)}</p>"
        f"<a class='primary-cta' href='{_e(href)}' data-double6-primary-action='true' "
        f"data-dashboard-module-link='{_e(primary['id'])}'>{_e(action_label)}</a>"
        "<strong class='hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
    )


def _metric(label: str, hook: str, suffix: str = "") -> str:
    return (
        "<div class='metric-card'>"
        f"<span>{_e(label)}</span><strong data-dashboard-metric='{_e(hook)}'>0{_e(suffix)}</strong>"
        "</div>"
    )


def _personal_platform_tools() -> list[dict[str, str]]:
    """读取已锁定的个人执行能力桥；候选只携带经过选择的可移植快照。"""
    bridge_path = Path(__file__).resolve().parents[2] / "references" / "personal-platform-bridge.json"
    bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    if bridge.get("schema_version") != "double6.personal-platform-bridge/v1":
        raise ValueError("个人执行能力桥 schema 不受支持")
    rows = bridge.get("items")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError("个人执行能力桥必须精确选择 5 个核心工具")
    required = {
        "item_id", "title", "body", "result", "action", "action_label",
        "target_module_id", "source_path", "source_sha256",
    }
    for row in rows:
        if not isinstance(row, dict) or required - row.keys():
            raise ValueError("个人执行能力桥条目不完整")
    return rows


def _today_workboard(primary: dict[str, str]) -> str:
    """所有场景共用的当日入口；实际待办由浏览器中的本地记录计算。"""
    return (
        "<section class='today-workboard dashboard-panel' data-today-workboard aria-label='今天要处理'>"
        "<div><span class='eyebrow'>今天要处理</span><h2>先完成一件最重要的事</h2>"
        "<p data-today-summary>正在读取当前设备上的待办。</p></div>"
        "<div class='today-items' data-today-items></div>"
        "<div class='today-actions'><a class='text-link' href='#module-"
        f"{_e(primary['id'])}' data-dashboard-module-link='{_e(primary['id'])}'>"
        f"从{_e(primary['name'])}开始</a>"
        "<button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span><input class='hidden' data-double6-hook='quick-import' "
        "type='file' accept='application/json,text/plain,.json,.txt'></label></div>"
        "<p class='backup-reminder' data-double6-hook='backup-reminder' hidden></p></section>"
    )


def _base_result(
    renderer_id: str,
    dashboard_html: str,
    capabilities: list[dict[str, Any]],
    detail_renderer: Callable[[dict[str, Any], bool, str], str],
    emojis: list[str],
    required_hooks: list[str],
    *,
    insert_today_workboard: bool = True,
    product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    primary_id = str(capabilities[0]["recommendation_module_id"])
    primary = {
        "id": primary_id,
        "name": str(capabilities[0]["name"]),
    }
    if "<header" not in dashboard_html:
        raise ValueError("场景首页缺少可插入的顶层 header")
    # 首个主动作必须在手机首屏。儿童 renderer 的欢迎语也使用 header，
    # 因此要精确定位含 hero 槽位的 header 后再插入待办板，不能插到欢迎语后。
    hero_start = dashboard_html.find("data-first-screen-slot='hero'")
    hero_end = dashboard_html.find("</header>", hero_start)
    if hero_start < 0 or hero_end < 0:
        raise ValueError("场景首页缺少可定位的 hero 结束标签")
    hero_end += len("</header>")
    if insert_today_workboard:
        dashboard_html = dashboard_html[:hero_end] + _today_workboard(primary) + dashboard_html[hero_end:]
    if "data-double6-hook='quick-export'" not in dashboard_html:
        backup = ("<div class='personal-data-safety'><span>本机保存与恢复</span><div class='today-actions'>"
                  "<button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
                  "<label class='secondary today-import'>导入恢复<input class='hidden' data-double6-hook='quick-import' type='file' accept='.json,.txt'></label></div></div>")
        closing = dashboard_html.rfind('</section>')
        dashboard_html = dashboard_html[:closing] + backup + dashboard_html[closing:]
    dashboard_html = _ensure_all_modules_reachable(dashboard_html, capabilities, emojis)
    details = "".join(
        detail_renderer(row, index == 0, emoji)
        for index, (row, emoji) in enumerate(zip(capabilities, emojis, strict=True))
    )
    return {
        "renderer_id": renderer_id,
        "dashboard_html": dashboard_html,
        "detail_views_html": details,
        "nav_items": _dedupe_nav(_peer_nav_items(capabilities, emojis, _composition_pack(product or {}))),
        "required_hooks": required_hooks,
        "primary_module_id": primary_id,
    }


def _child(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    learning_stage = product.get("recommendation_plan", {}).get("learning_stage", {})
    stage_eyebrow = str(learning_stage.get("dashboard_eyebrow") or "小学学习计划")
    reward = next((row for row in rows if row["id"] == "education-rewards"), None)
    parent_adjustment = (
        _link(reward, "调整奖励规则", "text-link")
        if reward
        else "<p>当前已确认模块没有独立奖励调整；如需加入，先回到产品确认，不在页面里悄悄增加能力。</p>"
    )
    tasks = "".join(
        f"<a class='learning-task task-{index + 1}' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}' "
        f"data-representative-card='{_e(row['id'])}'><span class='task-number'>0{index + 1}</span><span class='task-icon' "
        f"data-double6-emoji-role='work-item'>{emojis[index]}</span><strong>{_e(row['name'])}</strong>"
        f"<small data-dashboard-module-status='{_e(row['id'])}'>从第一条记录开始</small></a>"
        for index, row in enumerate(rows)
    )
    mini_links = "".join(
        _link(row, label, "mini-action")
        for row, label in zip(
            rows[:4],
            ["抽一张挑战卡", "闯一关数学岛", "听一句英语", "进故事剧场"],
            strict=False,
        )
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view child-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='child-task-quest-v1'>"
        "<header class='child-greeting'><div><h2>嗨，今天选一张挑战卡吧！</h2><p>不用把所有内容做完：选一项脑力挑战，再选一项故事、探索或身体活动就很好。</p></div>"
        "<div class='child-mode-switch' role='group' aria-label='查看方式'><button type='button' class='secondary active' data-child-mode='child'>孩子练习</button>"
        "<button type='button' class='secondary' data-child-mode='parent'>家长回顾</button></div><strong data-dashboard-metric='active'>0 项待完成</strong></header>"
        + "<div class='child-view child-view-child'>"
        + _hero(product, template, stage_eyebrow, "今天先打开一张想玩的挑战卡", "每张卡都有任务、故事、提示和讲解；完成记录只保存在当前设备。", rows[0], "抽第一张挑战卡")
        + "<div class='child-layout'><section class='dashboard-panel task-quest' data-first-screen-slot='primary_surface'>"
        "<div class='panel-heading'><div><span class='eyebrow'>今天想做什么？</span><h2>选一项开始就好</h2></div>"
        "<strong class='progress-copy' data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<div class='learning-task-grid'>{tasks}</div></section>"
        "<aside class='child-support' data-first-screen-slot='supporting_panel'><section class='reward-card'><span>今日能量</span>"
        "<strong data-dashboard-metric='completion'>0%</strong><div class='progress-track'><i data-dashboard-progress-bar></i></div>"
        "<small>完成状态只来自你勾选的记录</small></section><section class='reward-card star-balance-card'><span>我的星星</span>"
        "<strong data-reward-balance>0 ⭐</strong><small>完成新的学习挑战就能赚星星，攒够后请家长确认兑换奖励</small></section><section class='encouragement'><strong>想再做一点？</strong>"
        f"<div class='mini-action-grid'>{mini_links}</div></section>"
        "<section class='reward-box'><strong>成长收集册 · 从第一张完成卡开始</strong><p>先完成一项真实任务，再到成长收集册记录自己的小进步。</p></section></aside></div>"
        + "</div><section class='child-parent-review dashboard-panel child-view-parent' hidden><span class='eyebrow'>家长回顾</span><h2>先看完成情况，再决定是否减负或调整</h2>"
        "<p data-child-parent-summary>正在读取本机的练习与错题线索。</p><div class='child-parent-boundary'><strong>这是同一台设备上的查看方式，不是账号、密码或隐私权限。</strong>"
        "<p>不自动判断学习能力、健康或行为；需要调整时只基于当前已保存的事实。</p></div>"
        f"{parent_adjustment}</section>"
        + "</section>"
    )
    return _base_result("child_learning_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label", "completion", "progress-bar"], product=product)


# Historical compatibility markers scanned by inherited v0.55–v0.58 source gates:
# personal-week-execution-v3
# personal-week-execution-v4
# creator-production-pipeline-v1
# creator-production-pipeline-v2
# sales-followup-pipeline-v2
# sales-followup-pipeline-v3
# data-personal-now-content
# data-personal-today-focus
# data-personal-quick-capture
# data-personal-attention
CREATOR_WEEK = [
    ("一", "长文", "公众号"), ("二", "短帖 ×2", "X / 即刻"), ("三", "图文", "小红书"), ("四", "短视频", "视频号 / 抖音"),
    ("五", "数字复盘", "全平台"), ("六", "回评论", "不新发"), ("日", "休息", "攒素材"),
]

CREATOR_PLATFORMS = [("📕", "小红书"), ("🟢", "公众号"), ("🎬", "视频号 / 抖音"), ("✖️", "X / 即刻")]

READING_SHELF = [("📥", "想读", "先收进来，不急着读"), ("📖", "在读", "一次只读 1–2 本"), ("✅", "读完", "当天写一张读书卡"), ("🗂️", "已做笔记", "证据卡能被引用")]

def _research(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    emoji_by_id = {row["id"]: emoji for row, emoji in zip(rows, emojis, strict=False)}
    reading = rows[0]
    shelf = "".join(
        f"<a class='shelf-stage' href='#module-{_e(reading['id'])}' data-dashboard-module-link='{_e(reading['id'])}'>"
        f"<span aria-hidden='true'>{icon}</span><strong>{_e(name)}</strong><small>{_e(hint)}</small></a>"
        for icon, name, hint in READING_SHELF
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view research-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='research-reading-desk-v1'>"
        + _hero(product, template, "研究与阅读 · 每个结论都有出处", "今天读什么、想清楚什么？", "阅读清单、证据卡和研究问题连成一条线；摘录带页码，写作时直接引用。", rows[0], f"打开{rows[0]['name']}")
        + "<div class='research-grid'><section class='reading-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>阅读书架</span>"
        f"<h2>从想读到能引用</h2></div><small data-dashboard-module-status='{_e(reading['id'])}'>从第一本开始</small></div>"
        f"<div class='reading-shelf'>{shelf}</div>"
        "<div class='panel-heading' style='margin-top:18px'><div><span class='eyebrow'>研究工作流</span><h2>问题 · 证据 · 写作 · 复盘</h2></div></div>"
        f"<div class='all-modules-grid'>{_module_tiles(rows[1:], emoji_by_id)}</div></section>"
        "<aside class='side-stack' data-first-screen-slot='supporting_panel'><section class='side-card'><span class='eyebrow'>三遍阅读法</span>"
        "<h3>一篇论文不用一次读懂</h3><ol><li>10 分钟：标题、摘要、图表、结论</li><li>抓主要论证，标出疑问</li><li>复现关键推理，写下可借鉴之处</li></ol></section>"
        "<section class='side-card'><span class='eyebrow'>引用不丢</span><h3>摘录时就记页码</h3><p>证据卡 = 出处 + 原文 + 页码 + 我的理解。数据只存在这台设备，记得定期导出备份。</p></section></aside></div>"
        + "</section>"
    )
    return _base_result("research_reading_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])

def _creator(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    by_id = {row["id"]: row for row in rows}
    pack = _composition_pack(product)
    workspace_links = _workspace_links(by_id, list(pack.get("exact_module_ids") or by_id))
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view creator-dashboard content-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='content-tonight-board-v1' data-content-tonight-board>"
        "<header class='scene-hero content-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今晚这一篇</span>"
        "<h1>先把开头写出来</h1>"
        "<blockquote class='content-warmth' data-content-warmth>"
        "<p data-content-warmth-text>先写完这一段，再决定发不发。</p>"
        "<cite hidden data-content-warmth-cite></cite></blockquote>"
        "<p class='content-today-facts' data-content-today-facts>正在读取今晚这一篇。</p>"
        "<strong class='hero-progress content-hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label' hidden>已保存 0 条记录</strong>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='content-tonight-now' class='content-now-panel dashboard-panel' data-first-screen-slot='primary_surface' data-content-now-panel data-composition-region='now' data-today-workboard>"
        "<article class='content-piece-card'><span class='eyebrow'>今晚在写</span>"
        "<h2 data-content-piece-title>今晚这一篇</h2>"
        "<form class='content-opening-form' data-content-opening-form>"
        "<label>开头<textarea required minlength='8' maxlength='800' rows='7' data-content-opening "
        "placeholder='先写大约 80 字开头。写完再决定要不要进人工发布。'></textarea></label>"
        "<div class='content-opening-meta'><small data-content-opening-count>0 字</small>"
        "<button type='submit' data-double6-primary-action='true'>留下这段开头</button></div></form>"
        "<p>页面不会登录平台，也不会替你发布。</p></article></section>"
        "<aside class='content-tonight-side dashboard-panel' data-first-screen-slot='supporting_panel'>"
        "<div class='panel-heading'><div><span class='eyebrow'>这篇走到哪</span><h2>选题 · 任务书 · 开头 · 人工发布</h2></div></div>"
        "<div class='content-piece-steps' data-content-piece-steps></div>"
        "<div data-content-publish-now hidden><p>开头已留下 · <b data-content-publish-status></b></p>"
        "<div class='content-publish-row'>"
        "<button type='button' class='tiny' data-content-home-publish='copied'>记下已复制</button>"
        "<button type='button' class='tiny' data-content-home-publish='opened'>记下已打开平台</button>"
        "<button type='button' class='tiny' data-content-home-publish='confirmed'>人工确认已发布</button>"
        "</div><small>这三步只记你在站外做的事。只有人工确认才算这一步完成。</small></div>"
        "<section class='content-week-panel'><div class='panel-heading'><div><span class='eyebrow'>近七日</span><h2>哪天写下过</h2></div>"
        "<strong data-content-week-count>0 天写过</strong></div>"
        "<div class='content-week-grid' data-content-week></div>"
        "<p>点亮只表示这天本机留下过开头，或你人工确认过已发布。不是阅读量。</p></section>"
        "<details class='content-tonight-flow' data-composition-region='flow'><summary>其它工作面</summary>"
        "<section class='content-flow-panel'><div class='panel-heading'><div>"
        "<span class='eyebrow'>工作面</span><h2>来源到复盘</h2></div>"
        "<strong hidden data-content-flow-summary>0 条对象</strong></div>"
        "<div class='content-home-flow' data-content-home-flow></div></section></details>"
        "<details class='content-tonight-capture' data-composition-region='capture'><summary>来源箱，需要时再打开</summary>"
        "<form class='content-home-capture' data-content-home-capture>"
        "<label><span>一条观察或出处</span><input maxlength='160' data-content-home-title placeholder='不是今晚主活动'></label>"
        "<label><span>出处与待核问题</span><input maxlength='240' data-content-home-note placeholder='URL / 路径 / 日期'></label>"
        "<button type='submit'>收进来源箱</button>"
        "<p data-content-home-feedback aria-live='polite'>只保存在当前设备；没有来源的外部事实不会自动进入成稿。</p>"
        "</form></details>"
        "<section data-composition-region='attention'><div data-content-attention></div>"
        "<p>表现数据要你自己从平台抄回来，这里不会编阅读量。</p></section>"
        f"<details class='personal-workspace-switcher'><summary>打开完整生产工作区</summary><div class='mini-action-grid'>{workspace_links}</div></details>"
        "<div class='personal-data-safety'><span>本地记录 · 外部发布未执行</span><div class='today-actions'>"
        "<button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span><input class='hidden' data-double6-hook='quick-import' type='file' accept='application/json,text/plain,.json,.txt'></label>"
        "</div></div>"
        "</aside></section>"
    )
    pipeline = _module_tiles(rows, {row['id']: emoji for row, emoji in zip(rows, emojis)})
    week = ''.join(f"<div data-weekday='{index}'><small>周{day}</small><strong>{_e(kind)}</strong><small>{_e(where)}</small></div>" for index, (day, kind, where) in enumerate(CREATOR_WEEK))
    platforms = ''.join(f"<span class='platform-chip'><i aria-hidden='true'>{icon}</i>{_e(name)}</span>" for icon, name in CREATOR_PLATFORMS)
    resources = ("<section class='creator-resources dashboard-panel'><h2>内容流水线</h2>"
                 f"<div class='all-modules-grid'>{pipeline}</div><h3>建议的一周发布节奏</h3><div class='week-rhythm'>{week}</div>"
                 f"<h3>常用平台</h3><div class='platform-row'>{platforms}</div><p>排期只保存在本机，到点后在平台上人工发布。</p></section>")
    end = dashboard.rfind('</section>')
    dashboard = dashboard[:end] + resources + dashboard[end:]
    return _base_result(
        "creator_production_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _personal_week(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    return _pack_home(product, template, capabilities, detail_renderer, emojis, "personal_week_dashboard")


def _sales_followup(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    by_id = {row["id"]: row for row in rows}
    pack = _composition_pack(product)
    workspace_links = _workspace_links(by_id, list(pack.get("exact_module_ids") or by_id))
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view sales-followup-dashboard sales-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='sales-tonight-board-v1' data-sales-tonight-board>"
        "<header class='scene-hero sales-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今天这一家</span>"
        "<h1>先判断跟不跟，跟了记下结果</h1>"
        "<blockquote class='sales-warmth' data-sales-warmth>"
        "<p data-sales-warmth-text>先跟今天这一家就好。</p>"
        "<cite hidden data-sales-warmth-cite></cite></blockquote>"
        "<p class='sales-today-facts' data-sales-today-facts>正在读取今天这一家。</p>"
        "<strong class='hero-progress sales-hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label' hidden>已保存 0 条记录</strong>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='sales-tonight-now' class='sales-now-panel dashboard-panel' data-first-screen-slot='primary_surface' data-sales-now-panel data-composition-region='now' data-today-workboard>"
        "<article class='sales-today-card'><span class='eyebrow'>今天跟这一家</span>"
        "<h2 data-sales-today-alias>今天这一家</h2>"
        "<p data-sales-today-action>正在读取跟进动作。</p>"
        "<p data-sales-today-meta></p>"
        "<div class='sales-today-actions'>"
        "<button type='button' data-double6-primary-action='true' data-sales-today-act='follow'>今天跟这家</button>"
        "<button type='button' class='tiny' data-sales-today-act='defer'>改到明天</button>"
        "<button type='button' class='tiny' hidden data-sales-today-act='opened'>记下已打开渠道</button>"
        "<button type='button' class='tiny' hidden data-sales-today-act='confirmed'>人工确认已沟通</button>"
        "</div>"
        "<p>只用脱敏代号。页面不会发消息，也不会预测成交。</p></article></section>"
        "<aside class='sales-tonight-side dashboard-panel' data-first-screen-slot='supporting_panel'>"
        "<div class='panel-heading'><div><span class='eyebrow'>其它待跟</span><h2>今天以外的跟进</h2></div></div>"
        "<div data-sales-other-list></div>"
        "<details class='sales-tonight-flow' data-composition-region='flow'><summary>其它工作面</summary>"
        "<section class='sales-flow-panel'><div class='panel-heading'><div>"
        "<span class='eyebrow'>工作面</span><h2>线索到复盘</h2></div>"
        "<strong hidden data-sales-flow-summary>0 条对象</strong></div>"
        "<div class='sales-home-flow' data-sales-home-flow></div></section></details>"
        "<details class='sales-tonight-capture' data-composition-region='capture'><summary>新线索，需要时再打开</summary>"
        "<form class='sales-home-capture' data-sales-home-capture>"
        "<label><span>线索代号</span><input maxlength='80' data-sales-home-alias placeholder='例如：华东-A17（不要填真实姓名）'></label>"
        "<label><span>来源</span><input maxlength='160' data-sales-home-source placeholder='展会名 / 公开入口 / 转介绍代号'></label>"
        "<label><span>唯一下一步</span><input maxlength='160' data-sales-home-action placeholder='例如：确认采购周期'></label>"
        "<button type='submit'>收进线索箱</button>"
        "<p data-sales-home-feedback aria-live='polite'>只保存脱敏代号；页面不会联系客户。</p>"
        "</form></details>"
        "<section data-composition-region='attention'><div data-sales-attention></div>"
        "<p>消息和报价都要你自己发。这里不会登录平台。</p></section>"
        f"<details class='personal-workspace-switcher'><summary>打开完整销售工作区</summary><div class='mini-action-grid'>{workspace_links}</div></details>"
        "<div class='personal-data-safety'><span>脱敏本地数据 · 消息/报价未自动发送</span><div class='today-actions'>"
        "<button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span><input class='hidden' data-double6-hook='quick-import' type='file' accept='application/json,text/plain,.json,.txt'></label>"
        "</div></div>"
        "</aside></section>"
    )
    return _base_result(
        "sales_followup_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _teacher_class(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view teacher-class-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='teacher-class-board-v1' data-teacher-class-board>"
        "<header class='scene-hero teacher-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今天的班务日常</span>"
        "<h1>班务、考勤和待跟进都留在这一屏</h1>"
        "<blockquote class='teacher-warmth' data-teacher-warmth>"
        "<p data-teacher-warmth-text>一件一件来，班里的事不必一次做完。</p>"
        "<cite hidden data-teacher-warmth-cite></cite></blockquote>"
        "<p class='teacher-today-facts' data-teacher-today-facts>正在读取今天的班务。</p>"
        "<strong class='hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label'>已保存 0 条记录</strong>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='teacher-class-now' class='teacher-class-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='teacher-class-grid'>"
        "<article class='teacher-class-card' data-teacher-duty-card><span class='eyebrow'>今日班务</span>"
        "<div data-teacher-duty-list></div>"
        "<form class='teacher-inline-form' data-teacher-duty-form><label>再加一件<input required maxlength='80' data-teacher-duty-title placeholder='例如 检查值日'></label>"
        "<button type='submit' data-double6-primary-action='true'>加上这件</button></form>"
        "<small>勾掉只表示这件做完了，不是学生评语。</small></article>"
        "<article class='teacher-class-card' data-teacher-attendance-card><span class='eyebrow'>今日考勤</span>"
        "<div data-teacher-attendance-list></div>"
        "<small>只用合成代号。到 / 假 / 迟是本机事实，不是处分。</small></article>"
        "<article class='teacher-class-card' data-teacher-follow-card><span class='eyebrow'>待跟进</span>"
        "<div data-teacher-follow-list></div>"
        "<small>家校消息仍要你自己发。页面不会发送。</small></article>"
        "</div></section>"
        "<aside class='teacher-privacy' data-first-screen-slot='supporting_panel'>默认合成或脱敏。不要填真实姓名、成绩或电话。家校消息仍要你自己发。</aside>"
        "</section>"
    )
    return _base_result(
        "teacher_class_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


READING_SHELF = [("📥", "想读", "先收进来，不急着读"), ("📖", "在读", "一次只读 1–2 本"), ("✅", "读完", "当天写一张读书卡"), ("🗂️", "已做笔记", "证据卡能被引用")]


def _research(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    emoji_by_id = {row["id"]: emoji for row, emoji in zip(rows, emojis, strict=False)}
    reading = rows[0]
    shelf = "".join(
        f"<a class='shelf-stage' href='#module-{_e(reading['id'])}' data-dashboard-module-link='{_e(reading['id'])}'>"
        f"<span aria-hidden='true'>{icon}</span><strong>{_e(name)}</strong><small>{_e(hint)}</small></a>"
        for icon, name, hint in READING_SHELF
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view research-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='research-reading-desk-v1'>"
        + _hero(product, template, "研究与阅读 · 每个结论都有出处", "今天读什么、想清楚什么？", "阅读清单、证据卡和研究问题连成一条线；摘录带页码，写作时直接引用。", rows[0], f"打开{rows[0]['name']}")
        + "<div class='research-grid'><section class='reading-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>阅读书架</span>"
        f"<h2>从想读到能引用</h2></div><small data-dashboard-module-status='{_e(reading['id'])}'>从第一本开始</small></div>"
        f"<div class='reading-shelf'>{shelf}</div>"
        "<div class='panel-heading' style='margin-top:18px'><div><span class='eyebrow'>研究工作流</span><h2>问题 · 证据 · 写作 · 复盘</h2></div></div>"
        f"<div class='all-modules-grid'>{_module_tiles(rows[1:], emoji_by_id)}</div></section>"
        "<aside class='side-stack' data-first-screen-slot='supporting_panel'><section class='side-card'><span class='eyebrow'>三遍阅读法</span>"
        "<h3>一篇论文不用一次读懂</h3><ol><li>10 分钟：标题、摘要、图表、结论</li><li>抓主要论证，标出疑问</li><li>复现关键推理，写下可借鉴之处</li></ol></section>"
        "<section class='side-card'><span class='eyebrow'>引用不丢</span><h3>摘录时就记页码</h3><p>证据卡 = 出处 + 原文 + 页码 + 我的理解。数据只存在这台设备，记得定期导出备份。</p></section></aside></div>"
        + "</section>"
    )
    return _base_result("research_reading_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])


def _teacher(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    timeline = "".join(
        f"<li><span>{minute}</span><div><strong>{label}</strong><small>从备课记录补充内容</small></div></li>"
        for minute, label in [("05'", "导入与目标"), ("15'", "讲解与示范"), ("15'", "练习与观察"), ("05'", "总结与作业")]
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view teacher-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='teacher-lesson-timeline-v1'>"
        + _hero(product, template, "单节课工作面", "把这一节课备清楚", "目标、课堂节奏、材料与作业在同一张课前视图里。", rows[1] if len(rows) > 1 else rows[0], "继续备课")
        + "<div class='lesson-grid'><section class='lesson-timeline dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'>"
        "<div><span class='eyebrow'>40 分钟课堂流程</span><h2>从目标走到作业</h2></div><strong data-dashboard-metric='completion'>0%</strong></div>"
        f"<ol>{timeline}</ol></section><aside class='lesson-side' data-first-screen-slot='supporting_panel'><section><span>待准备材料</span>"
        "<strong data-dashboard-metric='records'>0 项</strong><small>从本机记录统计</small></section><section><span>作业提醒</span><strong>待人工填写</strong>"
        "<small>不生成未确认的教学内容</small></section></aside></div>"
        + "</section>"
    )
    return _base_result("teacher_lesson_dashboard", dashboard, capabilities, detail_renderer, emojis, ["completion", "records"], product=product)


def _freelance(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view freelance-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='freelance-milestone-ledger-v1'>"
        + _hero(product, template, "独立交付 · 先推进最近里程碑", "下一份交付物是什么？", "把项目阶段、待确认事项与时间成本留在可复核的事实记录里。", rows[0], "推进当前项目")
        + "<section class='milestone-rail dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div>"
        "<span class='eyebrow'>项目阶段</span><h2>从需求到复核</h2></div><strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        "<div class='rail'><span class='done'>需求</span><span>方案</span><span>交付</span><span>确认</span></div></section>"
        "<div class='delivery-grid' data-first-screen-slot='supporting_panel'><section><span class='eyebrow'>最近交付物</span><h2 data-dashboard-latest='records'>还没有交付记录</h2>"
        f"{_link(rows[1] if len(rows) > 1 else rows[0], '打开交付清单', 'text-link')}</section><section><span class='eyebrow'>客户待确认</span>"
        "<strong data-dashboard-metric='active'>0 项</strong><p>只显示你录入的待确认事实。</p></section><section><span class='eyebrow'>下一里程碑</span>"
        "<strong>待人工设定</strong><p>页面不代替合同或客户确认。</p></section></div>"
        + "</section>"
    )
    return _base_result("freelance_delivery_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label", "active", "latest"], product=product)


def _travel(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view travel-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='travel-departure-itinerary-v1'>"
        + _hero(product, template, "出发准备 · 所有状态都要有来源", "离出发还有多久？", "倒计时来自你填写的日期；天气与预订状态都需要人工确认。", rows[0], "填写出发条件")
        + "<div class='travel-overview'><section class='countdown-card' data-first-screen-slot='progress'><span>距离出发</span>"
        "<strong data-dashboard-metric='countdown'>未设置</strong><small>在“条件与决策”填写日期后计算</small></section>"
        "<section class='route-card dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>逐日路线</span>"
        "<h2>先把移动与落脚排顺</h2></div><strong data-dashboard-metric='records'>0 段</strong></div>"
        "<ol class='route-line'><li><span>D1</span><strong>从第一段行程开始</strong></li><li><span>D2</span><strong>等待你添加</strong></li>"
        "<li><span>备</span><strong>保留天气备选</strong></li></ol></section></div>"
        "<div class='booking-strip' data-first-screen-slot='supporting_panel'><div><span>预订状态</span><strong data-dashboard-metric='active'>0 条已录</strong></div>"
        "<div><span>天气备选</span><strong>非实时 · 人工确认</strong></div><div><span>出发清单</span><strong data-dashboard-metric='completion'>0%</strong></div></div>"
        + "</section>"
    )
    return _base_result("travel_departure_dashboard", dashboard, capabilities, detail_renderer, emojis, ["countdown", "records", "active", "completion"], product=product)


def _finance(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view finance-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='finance-month-close-console-v1'>"
        + _hero(product, template, "月结工作面 · 只汇总本地事实", "本月先核哪一笔？", "收支、凭证、预算和对账都来自你录入的数据，不生成经营或投资判断。", rows[0], "记录一笔收支")
        + "<section class='finance-metrics' data-first-screen-slot='progress'>"
        + _metric("本月记录", "records", " 笔") + _metric("待核事项", "active", " 项") + _metric("已完成", "completion", "%")
        + "</section><div class='close-grid'><section class='ledger-snapshot dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'>"
        "<div><span class='eyebrow'>月结队列</span><h2>凭证 → 预算 → 对账</h2></div><span class='status-pill'>本机数据</span></div>"
        "<div class='ledger-lines'><div><span>收支台账</span><strong data-dashboard-module-status='finance-transactions'>从 0 笔开始</strong></div>"
        "<div><span>凭证核验</span><strong data-dashboard-module-status='finance-vouchers'>从 0 项开始</strong></div>"
        "<div><span>月结复盘</span><strong data-dashboard-module-status='finance-review'>等待记录</strong></div></div></section>"
        "<aside class='reconcile-note' data-first-screen-slot='supporting_panel'><span>边界提醒</span><strong>所有金额只做事实汇总</strong>"
        "<p>税率、法规与投资建议不在本页自动生成。</p></aside></div>"
        + "</section>"
    )
    return _base_result("finance_month_close_dashboard", dashboard, capabilities, detail_renderer, emojis, ["records", "active", "completion"], product=product)


def _finance_tonight(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    shell = _tonight_evaluate_shell(rows)
    ledger = next((row for row in rows if row["id"] == "finance-transactions"), rows[0])
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view finance-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='finance-tonight-log-v1' data-finance-tonight-board>"
        "<header class='scene-hero finance-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今晚记账</span>"
        "<h1>打开就记今晚这笔</h1>"
        "<blockquote class='finance-warmth' data-finance-warmth>"
        "<p data-finance-warmth-text>先把今晚这笔写下。合计只加你填的数字。</p>"
        "<cite hidden data-finance-warmth-cite></cite></blockquote>"
        "<p class='finance-today-facts' data-finance-today-facts>正在读取今晚流水。</p>"
        "<strong class='hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label' data-finance-today-total>今日支出 0.00 元。这是你填的数字相加，不是银行余额。</strong>"
        f"<a class='primary-cta' href='#module-{_e(ledger['id'])}' data-double6-primary-action='true' "
        f"data-dashboard-module-link='{_e(ledger['id'])}'>记今晚这笔</a>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='finance-tonight-now' class='finance-tonight-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='finance-tonight-grid'>"
        "<article class='finance-tonight-card' data-finance-log-card><span class='eyebrow'>记今晚这笔</span>"
        "<form class='finance-inline-form' data-finance-log-form>"
        "<label>这笔是什么<input required maxlength='80' data-finance-log-title placeholder='例如 晚饭'></label>"
        "<label>金额<input required type='number' min='0.01' step='0.01' data-finance-log-amount placeholder='例如 12.5'></label>"
        "<label>类型<select data-finance-log-type><option value='支出' selected>支出</option><option value='收入'>收入</option></select></label>"
        "<label>分类<select data-finance-log-category><option value='餐饮'>餐饮</option><option value='交通'>交通</option><option value='日用'>日用</option><option value='其他'>其他</option></select></label>"
        "<button type='submit'>记下这笔</button></form>"
        "<div data-finance-tx-list></div>"
        "<small>页面不会去银行取数，也不连接支付。</small></article>"
        "<article class='finance-tonight-card' data-finance-voucher-card><span class='eyebrow'>今晚凭证</span>"
        "<div data-finance-voucher-list></div>"
        "<small>勾掉只表示这台设备记下找到了。不是发票查验。</small></article>"
        "<article class='finance-tonight-card' data-finance-tax-card><span class='eyebrow'>税务材料</span>"
        "<div data-finance-tax-list></div>"
        "<small>状态保持待专业处理。不是已申报。本页不申报、不付款。</small></article>"
        "</div>"
        "<p class='finance-side-jobs'>账记完，缺票去<a href='#module-finance-review' data-dashboard-module-link='finance-review'>判断缺票</a>，同一张票出现两次去<a href='#module-finance-audit' data-dashboard-module-link='finance-audit'>判断重复票</a>。</p>"
        "</section>"
        "<aside class='finance-privacy' data-first-screen-slot='supporting_panel'>数据只在这台设备。清缓存会没。不要写账号、税号或银行卡。"
        f"{shell}</aside>"
        "</section>"
    )
    return _base_result(
        "finance_tonight_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _household_tonight(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view household-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='household-tonight-board-v1' data-household-tonight-board>"
        "<header class='scene-hero household-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今晚家里这几件</span>"
        "<h1>谁做饭、谁洗碗，打开就能勾</h1>"
        "<blockquote class='household-warmth' data-household-warmth>"
        "<p data-household-warmth-text>勾掉今晚这几件就好。当面说一声，页面发不出去。</p>"
        "<cite hidden data-household-warmth-cite></cite></blockquote>"
        "<p class='household-today-facts' data-household-today-facts>正在读取今晚家务。</p>"
        "<strong class='hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label'>已保存 0 条记录</strong>"
        "<a class='primary-cta' href='#module-household-chores' data-double6-primary-action='true' data-dashboard-module-link='household-chores'>处理今晚家务</a>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='household-tonight-now' class='household-tonight-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='household-tonight-grid'>"
        "<article class='household-tonight-card' data-household-chore-card><span class='eyebrow'>今晚家务</span>"
        "<div data-household-chore-list></div>"
        "<form class='household-inline-form' data-household-chore-form>"
        "<label>再加一件<input required maxlength='80' data-household-chore-title placeholder='例如 晾衣服'></label>"
        "<label>谁做<select data-household-chore-who><option value='我'>我</option><option value='对方'>对方</option></select></label>"
        "<button type='submit' >加上今晚这件</button></form>"
        "<small>勾掉只表示这台设备记下做完了。对方看不见，除非你当面说。</small></article>"
        "<article class='household-tonight-card' data-household-shop-card><span class='eyebrow'>今晚要买</span>"
        "<div data-household-shop-list></div>"
        "<small>买过就勾。不是共同账本，也不接支付。</small></article>"
        "<article class='household-tonight-card' data-household-tell-card><span class='eyebrow'>待当面说</span>"
        "<div data-household-tell-list></div>"
        "<small>页面不会发消息、不会同步到另一部手机。</small></article>"
        "</div></section>"
        "<aside class='household-privacy' data-first-screen-slot='supporting_panel'>只用我 / 对方这种称呼。真实姓名、住址和钱不要写进来。数据只在这台设备。</aside>"
        "</section>"
    )
    return _base_result(
        "household_tonight_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _household(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    days = "".join(f"<div class='day-cell{' today' if index == 0 else ''}'><span>{day}</span><strong>{'今天' if index == 0 else '—'}</strong></div>" for index, day in enumerate("一二三四五六日"))
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view household-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='household-week-calendar-v1'>"
        + _hero(product, template, "家庭一周 · 单设备人工交接", "今天家里先做什么？", "家务、采购与交接集中在这台设备；没有实时多人同步。", rows[0], "添加今日家务")
        + "<section class='week-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>这一周</span>"
        "<h2>把今天放回整周里看</h2></div><strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<div class='week-grid'>{days}</div></section><div class='household-columns' data-first-screen-slot='supporting_panel'>"
        "<section><span class='eyebrow'>今日家务</span><strong data-dashboard-module-status='household-chores'>从 0 项开始</strong><p>完成状态来自勾选记录。</p></section>"
        "<section><span class='eyebrow'>采购清单</span><strong data-dashboard-module-status='household-shopping'>从 0 项开始</strong><p>出门前集中查看。</p></section>"
        "<section><span class='eyebrow'>人工交接</span><strong data-dashboard-module-status='household-handoff'>等待记录</strong><p>需要主动告诉其他成员。</p></section></div>"
        + "</section>"
    )
    return _base_result("household_week_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"], product=product)


def _commerce_tonight(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view commerce-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='commerce-tonight-orders-v1' data-commerce-tonight-board>"
        "<header class='scene-hero commerce-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今晚店铺这几单</span>"
        "<h1>打开就处理今天这几单</h1>"
        "<blockquote class='commerce-warmth' data-commerce-warmth>"
        "<p data-commerce-warmth-text>先处理今天这几单。库存只是你记下的快照。</p>"
        "<cite hidden data-commerce-warmth-cite></cite></blockquote>"
        "<strong class='hero-progress commerce-today-facts' data-first-screen-slot='progress' data-double6-hook='progress-label' data-commerce-today-facts>正在读取今晚订单。</strong>"
        "<a class='primary-cta' href='#module-commerce-orders' data-double6-primary-action='true' data-dashboard-module-link='commerce-orders'>处理今晚这几单</a>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='commerce-tonight-now' class='commerce-tonight-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='commerce-tonight-grid'>"
        "<article class='commerce-tonight-card' data-commerce-order-card><span class='eyebrow'>今晚这几单</span>"
        "<div data-commerce-order-list></div>"
        "<form class='commerce-inline-form' data-commerce-order-form>"
        "<label>这一单<input required maxlength='80' data-commerce-order-title placeholder='例如 米色卫衣'></label>"
        "<label>类型<select data-commerce-order-stage><option value='待发货' selected>待发货</option><option value='待售后'>待售后</option></select></label>"
        "<button type='submit' >加上今晚这单</button></form>"
        "<small>页面不会发货、不会退款，也不连接店铺。</small></article>"
        "<article class='commerce-tonight-card' data-commerce-stock-card><span class='eyebrow'>库存快照</span>"
        "<div data-commerce-stock-list></div>"
        "<form class='commerce-inline-form' data-commerce-stock-form>"
        "<label>哪件商品<input required maxlength='80' data-commerce-stock-title placeholder='例如 米色卫衣'></label>"
        "<label>件数<input required type='number' min='0' step='1' data-commerce-stock-count placeholder='例如 3'></label>"
        "<button type='submit'>记下快照</button></form>"
        "<small>数字是你填的手工快照，不是实时库存。</small></article>"
        "<article class='commerce-tonight-card' data-commerce-service-card><span class='eyebrow'>待在平台回</span>"
        "<div data-commerce-service-list></div>"
        "<small>勾掉只表示这台设备记下回过了。页面不会发消息。</small></article>"
        "</div></section>"
        "<aside class='commerce-privacy' data-first-screen-slot='supporting_panel'>数据只在这台设备。不要写买家真名、手机或店铺账号。本地勾选不是已发货，也不是平台已读。</aside>"
        "</section>"
    )
    return _base_result(
        "commerce_tonight_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _fitness(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view fitness-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='fitness-daily-board-v1' data-fitness-daily-board>"
        "<header class='scene-hero fitness-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今天的减脂日常</span>"
        "<h1>记下体重、三餐和有没有练</h1>"
        "<blockquote class='fitness-warmth' data-fitness-warmth>"
        "<p data-fitness-warmth-text>来了就算开始，不必一次做完。</p>"
        "<cite hidden data-fitness-warmth-cite></cite></blockquote>"
        "<p class='fitness-today-facts' data-fitness-today-facts>今天还没记下。</p>"
        "<strong class='hero-progress' data-first-screen-slot='progress' data-double6-hook='progress-label'>已保存 0 条记录</strong>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        + "<section id='fitness-daily-now' class='fitness-daily-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='fitness-daily-grid'>"
        "<article class='fitness-daily-card' data-fitness-weight-card><span class='eyebrow'>今日体重</span>"
        "<strong data-fitness-weight-readout>还没记</strong>"
        "<form class='fitness-inline-form' data-fitness-weight-form><label>公斤<input type='number' min='20' max='300' step='0.1' inputmode='decimal' required data-fitness-weight-input placeholder='例如 62.5'></label>"
        "<button type='submit' data-double6-primary-action='true'>记下体重</button></form>"
        "<small>只保存在这台设备。不会据此告诉你该减多少。</small></article>"
        "<article class='fitness-daily-card' data-fitness-meal-card><span class='eyebrow'>今日三餐</span>"
        "<strong data-fitness-kcal-readout>自己记的估计 0 kcal</strong>"
        "<div data-fitness-meal-list></div>"
        "<form class='fitness-inline-form' data-fitness-meal-form><label>吃了什么<input required maxlength='80' data-fitness-meal-title placeholder='例如 燕麦牛奶'></label>"
        "<label>估计热量<input type='number' min='0' max='5000' step='1' inputmode='numeric' data-fitness-meal-kcal placeholder='可不填'></label>"
        "<button type='submit'>加上这一餐</button></form>"
        "<small>合计是你填的数字相加，不是营养分析结果。</small></article>"
        "<article class='fitness-daily-card' data-fitness-checkin-card><span class='eyebrow'>今日运动</span>"
        "<strong data-fitness-checkin-readout>还没打卡</strong>"
        "<div class='fitness-checkin-row'>"
        "<button type='button' class='tiny' data-fitness-checkin='今天练了'>今天练了</button>"
        "<button type='button' class='tiny' data-fitness-checkin='今天休息'>今天休息</button>"
        "<button type='button' class='tiny secondary' data-fitness-checkin='不适停止'>不适停止</button>"
        "</div>"
        "<p data-fitness-follow-note>没有跟练链接时不会假装视频在播。数字不是营养师，也不保证瘦下来。</p></article>"
        "</div></section>"
        "<section class='fitness-calendar-panel dashboard-panel' data-first-screen-slot='supporting_panel'>"
        "<div class='panel-heading'><div><span class='eyebrow'>近七日</span><h2>哪天来过</h2></div>"
        "<strong data-fitness-week-count>0 天来过</strong></div>"
        "<div class='fitness-week-grid' data-fitness-calendar></div>"
        "<p>点亮只表示这天本机有体重、三餐或运动打卡，不是减重成功。</p></section>"
        + "</section>"
    )
    return _base_result(
        "fitness_sprint_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _life(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    cards = "".join(
        f"<a class='life-today-card life-card-{index + 1}' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'>"
        f"<span>{emojis[index]}</span><div><strong>{_e(row['name'])}</strong><small>{_e(row['description'])}</small></div></a>"
        for index, row in enumerate(rows)
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view life-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='personal-life-cockpit-v1'>"
        + _hero(product, template, "我的生活驾驶舱 · 数据只在当前设备", "今天，先照顾好哪一件小事？", "灵感、记录、行动和阅读都从本机事实开始；没有实时资讯、云同步或自动建议。", rows[0], "打开今天的灵感")
        + "<section class='life-today-page dashboard-panel' data-life-today-page data-adult-fact-projection><div class='panel-heading'><div><span class='eyebrow'>今日一页</span><h2>Top 1、心情和一个习惯</h2></div><strong>一次完成今天的三个事实</strong></div>"
        "<div class='life-quick-grid'><article><strong>1 · 今日 Top 1</strong><p data-life-top-one-status>还没有 Top 1</p><input data-life-top-one maxlength='100' placeholder='今天最重要的一件事'><button type='button' data-life-top-one-done>完成 Top 1</button></article>"
        "<article><strong>2 · 心情事实</strong><p data-life-mood-status>今天还没记录心情</p><select data-life-mood-quick><option>开心</option><option>平静</option><option>低落</option><option>烦躁</option><option>疲惫</option></select><input data-life-mood-note maxlength='160' placeholder='发生了什么，不做心理判断'><button type='button' data-life-mood-save>保存心情</button></article>"
        "<article><strong>3 · 一个习惯</strong><p data-life-habit-status>今天还没打卡</p><input data-life-habit-quick maxlength='80' placeholder='例如 阅读 10 分钟'><button type='button' data-life-habit-done>完成习惯</button></article></div>"
        "<details class='life-goal-card'><summary>可选：21 天目标与自定奖励</summary><div class='life-goal-grid'><label>目标总量<input type='number' min='1' data-life-goal-target></label><label>当前量<input type='number' min='0' value='0' data-life-goal-current></label><label>目标日期<input type='date' data-life-goal-deadline></label><label>自己填写的奖励<input maxlength='80' data-life-goal-reward placeholder='只在本地庆祝'></label></div><button type='button' data-life-goal-save>保存目标</button><p data-life-goal-facts>可选：设置一个 21 天目标</p><div class='life-goal-track'><i data-life-goal-progress-bar></i></div><p data-life-equal-division>尚无可计算的目标等分</p><p data-life-milestone>里程碑只在本机庆祝，不会自动兑现</p></details>"
        "<p class='life-fact-note'>连续记录 <strong data-life-fact-streak>0 天</strong>；只按去重后的完成日期计算。收支、饮食、运动和心情只汇总你录入的事实。</p></section>"
        + "<section class='life-metrics' data-first-screen-slot='progress'><div class='metric-card'><span>今日支出</span><strong data-life-metric='spending'>¥0</strong></div>"
        "<div class='metric-card'><span>储蓄余额</span><strong data-life-metric='savings'>¥0</strong><small data-life-goal-progress>尚未设置目标</small></div>"
        "<div class='metric-card'><span>今日饮食</span><strong data-life-metric='calories'>0 kcal</strong><small data-life-food-reference>未设置参考值</small></div>"
        "<div class='metric-card'><span>连续运动</span><strong data-life-metric='streak'>0 天</strong></div></section>"
        + f"<section class='life-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>今天可直接完成</span><h2>选一个入口，就从这里开始</h2></div><strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div><div class='life-card-grid'>{cards}</div></section>"
        "<aside class='life-support' data-first-screen-slot='supporting_panel'><span class='eyebrow'>本月运动日历</span><div class='life-calendar' data-life-calendar></div><p>只有完成训练才会点亮日期；停止或未完成不会计入连续天数。</p><label class='surface-field'>储蓄目标（元）<input data-life-savings-goal type='number' min='1' inputmode='decimal' placeholder='例如 3000'></label><button type='button' class='secondary' data-life-save-goal>保存储蓄目标</button><small>目标仅用于本地展示，进度只按“存入/取出储蓄”流水计算。</small><label class='surface-field'>饮食参考值（kcal）<input data-life-food-goal type='number' min='1' inputmode='decimal' placeholder='仅展示，不做建议'></label><button type='button' class='secondary' data-life-save-food-goal>保存饮食参考值</button><small>参考值只用于展示，不生成减脂处方、营养诊断或推荐摄入量。</small></aside>"
        + "</section>"
    )
    result = _base_result("personal_life_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"], product=product)
    result["nav_items"] = [_nav_item("dashboard", "首页", "🏠")]
    result["nav_items"].extend(
        _nav_item(f"module-{row['id']}", row["name"], emoji)
        for row, emoji in zip(rows, emojis, strict=True)
    )
    result["nav_items"].append(_nav_item("data-tools", "数据", "💾"))
    result["nav_items"] = _dedupe_nav(result["nav_items"])
    return result


def _composition_pipeline(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    """由 composition pack 的注意力模型装配四区首页，不再为新场景写死模块 ID。"""
    rows = _module_rows(capabilities)
    by_id = {row["id"]: row for row in rows}
    pack = _composition_pack(product)
    regions = _attention_regions(pack)
    capture = _region_module(regions, "capture", by_id, rows[0])
    now = _region_module(regions, "now", by_id, rows[0])
    workspace_links = _workspace_links(by_id, list(pack.get("exact_module_ids") or by_id))
    flow_label = _flow_title(pack, by_id, "模块工作链")
    attention_link = _link(now, "打开" + now["name"], "text-link")
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view composition-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='composition-object-pipeline-v1' data-composition-dashboard>"
        + _hero(product, template, _visible_home_kicker(pack, product), _region_label(regions, "now", "今晚这一件"), "打开就做今晚这一件，不要先填一张空表。", now, f"去做{_region_label(regions, 'now', '今晚这一件')}")
        + "<section class='content-now-panel dashboard-panel' data-first-screen-slot='primary_surface' data-composition-now-panel data-composition-region='now' data-today-workboard><div data-composition-now-content></div><div class='content-due-strip'><p data-today-summary>正在读取当前设备上的待办。</p><div class='today-items' data-today-items></div></div></section>"
        + f"<section class='content-flow-panel dashboard-panel' data-first-screen-slot='progress' data-composition-region='flow'><div class='panel-heading'><div><span class='eyebrow'>{_e(_region_label(regions, 'flow', '对象链'))}</span><h2>{_e(flow_label)}</h2></div><strong data-composition-flow-summary>0 条对象</strong></div><div class='content-home-flow' data-composition-home-flow></div></section>"
        + f"<form class='content-home-capture dashboard-panel' data-composition-home-capture data-composition-region='capture'><label><span>{_e(_region_label(regions, 'capture', '先记下什么？'))}</span><input required maxlength='160' data-composition-capture-title placeholder='一条问题、来源或观察'></label><button type='submit'>收进{_e(capture['name'])}</button><p data-composition-home-feedback aria-live='polite'>只保存在当前设备；不自动生成无来源结论。</p></form>"
        + f"<section class='content-attention-panel dashboard-panel' data-first-screen-slot='supporting_panel' data-composition-region='attention'><div class='panel-heading'><div><span class='eyebrow'>需要关注</span><h2>{_e(_region_label(regions, 'attention', '只显示会阻塞推进的缺口'))}</h2></div>"
        f"{attention_link}</div><div data-composition-attention></div>"
        f"<details class='personal-workspace-switcher'><summary>打开完整工作区</summary><div class='mini-action-grid'>{workspace_links}</div></details>"
        "<div class='personal-data-safety'><span>本地记录 · 外部动作未执行</span><div class='today-actions'><button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span><input class='hidden' data-double6-hook='quick-import' type='file' accept='application/json,text/plain,.json,.txt'></label></div></div></section>"
        + "</section>"
    )
    return _base_result("composition_dashboard", dashboard, capabilities, detail_renderer, emojis, [], insert_today_workboard=False, product=product)


def _generic(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    scene_label = str(
        product.get("recommendation_plan", {})
        .get("capability_supply_snapshot", {})
        .get("scene_profile", {})
        .get("label")
        or "场景工作台"
    )
    cards = "".join(
        f"<a class='generic-work-card' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'><span>{emojis[index]}</span>"
        f"<div><strong>{_e(row['name'])}</strong><small>{_e(row['description'])}</small></div></a>"
        for index, row in enumerate(rows)
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view generic-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='generic-priority-board-v1'>"
        + _hero(product, template, scene_label, product["title"], "先进入最重要的工作面，其他记录按需打开。", rows[0], f"开始{rows[0]['name']}")
        + f"<section class='generic-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><h2>现在要做什么</h2>"
        "<strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<div class='generic-card-grid'>{cards}</div></section>"
        + "<aside class='generic-support' data-first-screen-slot='supporting_panel'><p>所有进度都从本机记录开始计算。</p></aside></section>"
    )
    return _base_result("generic_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"], product=product)


def _exam_practice(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    is_cet4 = _composition_pack(product).get("scene_profile_id") == "scene.exam-preparation.certification-study-cycle"
    if not is_cet4:
        rows = sorted(rows, key=lambda row: _civil_nav_rank(row["id"]))
    shell = _tonight_evaluate_shell(rows)
    practice = next((row for row in rows if row["id"] == "exam-practice"), rows[0])
    cet4_support = (
        "<section class='cet4-support dashboard-panel' data-adult-fact-projection><div class='panel-heading'><div><span class='eyebrow'>四级冲刺 · 目标等分只按剩余量÷剩余天数</span><h2>日期、专注与人工复核</h2></div><strong data-study-state data-study-state-value='idle'>伙伴在等你开始</strong></div>"
        "<div class='cet4-control-grid'>"
        "<div class='cet4-goal-row'><label>考试日期<input type='date' data-cet4-date></label><button type='button' data-cet4-save-date>保存日期</button><strong data-cet4-countdown>先录入考试日期</strong></div>"
        "<article class='cet4-timer' data-cet4-timer><span class='eyebrow'>专注计时 · 刷新按时间戳恢复</span><strong data-cet4-timer-readout>25:00</strong><div class='form-actions'><button type='button' data-cet4-timer-action='start'>开始</button><button type='button' class='secondary' data-cet4-timer-action='pause'>暂停</button><button type='button' class='secondary' data-cet4-timer-action='resume'>恢复</button><button type='button' class='secondary' data-cet4-timer-action='finish'>完成</button></div></article>"
        "</div>"
        "<section class='cet4-manual-grid' data-cet4-manual-review></section>"
        "<aside class='cet4-source-contract'><strong>来源与版权边界</strong><p>考试结构仅参考教育部教育考试院《全国大学英语四、六级考试大纲》与《CET4考核内容》，核验于 2026-08-31。18 道判分练习与 6 道写作/翻译练习全部自编，非真题、非通过保证；写作与翻译需人工复核。</p></aside></section>"
        if is_cet4 else ""
    )
    civil_desk = (
        "<section id='dashboard' class='app-view dashboard-view exam-practice-dashboard exam-civil-desk is-active' data-view-id='dashboard' "
        "data-dashboard-signature='exam-desk-v1' data-exam-practice-board data-exam-desk>"
        "<header class='scene-hero exam-hero exam-civil-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>行测、申论、面试</span>"
        "<h1>考公工作台</h1>"
        "<blockquote class='exam-warmth' data-exam-warmth>"
        "<p data-exam-warmth-text>打开就选一科。打判不是官方分，也不说明能不能进面。</p>"
        "<cite hidden data-exam-warmth-cite></cite></blockquote>"
        "<p class='exam-today-facts' data-first-screen-slot='progress' data-exam-today-facts>打开就选一科练。</p>"
        "<strong class='hero-progress' hidden data-double6-hook='progress-label'>打开就能开始</strong>"
        "</div></header>"
        "<div class='exam-home-main'>"
        "<section class='exam-now exam-desk-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<p class='exam-desk-lead'>打开就选行测、申论或面试。题和打判已经接上。不是真题，打判不是官方分，也不保证上岸。</p>"
        "<div class='exam-desk-doors'>"
        f"<a class='exam-desk-door exam-desk-xingce' href='#module-exam-practice' data-exam-door-xingce data-dashboard-module-link='exam-practice' data-open-view='module-exam-practice' data-double6-primary-action='true'>"
        "<span class='exam-desk-sheet' aria-hidden='true'><i></i><i></i><i></i><b>A</b><b>B</b><b>C</b><b>D</b></span>"
        "<span class='exam-desk-kicker'>选择题</span><strong>行测</strong>"
        "<small>按模块连做，当场看对错</small><em>去做行测</em></a>"
        "<a class='exam-desk-door exam-desk-shenlun' href='#module-exam-materials' data-exam-door-shenlun data-dashboard-module-link='exam-materials' data-open-view='module-exam-materials'>"
        "<span class='exam-desk-sheet exam-desk-lines' aria-hidden='true'><i></i><i></i><i></i><i></i><i></i></span>"
        "<span class='exam-desk-kicker'>写作</span><strong>申论</strong>"
        "<small>读材料再写，关键词提示自查</small><em>去写申论</em></a>"
        "<a class='exam-desk-door exam-desk-interview' href='#module-exam-today' data-exam-door-interview data-dashboard-module-link='exam-today' data-open-view='module-exam-today'>"
        "<span class='exam-desk-sheet exam-desk-timer' aria-hidden='true'><b>15:00</b></span>"
        "<span class='exam-desk-kicker'>开口</span><strong>面试</strong>"
        "<small>抽题计时，贴转写做用词核对</small><em>去开口试</em></a>"
        "</div>"
        "<p class='exam-disclaimer'>不是真题，也不保证上岸。打判不是官方分，不能当过线依据。</p>"
        "<details class='exam-import' data-exam-import><summary>导入你有权使用的题</summary>"
        "<p>导入只留在这台设备。粉笔、华图、中公题库不要往这里搬。</p>"
        "<label><input type='checkbox' data-exam-rights> 我声明有权使用这些题目</label>"
        "<input class='hidden' type='file' accept='application/json,.json,.txt' data-exam-import-file>"
        "<button type='button' data-exam-import-pick>选择文件</button>"
        "<p class='feedback' data-exam-import-feedback></p></details>"
        "</section>"
        "<aside class='exam-errors-panel dashboard-panel' data-first-screen-slot='supporting_panel'>"
        "<div class='panel-heading'><div><span class='eyebrow'>错题回炉</span><h2>错过的再做</h2></div></div>"
        "<div data-exam-error-list></div>"
        "<p>回炉只表示错过，不是掌握，更不是排名。</p>"
        f"{shell}"
        "</aside></div></section>"
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view exam-practice-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='exam-practice-board-v1' data-exam-practice-board>"
        "<header class='scene-hero exam-hero' data-first-screen-slot='hero'><div>"
        f"<span class='hero-kicker'>{'四级冲刺 · 今天这一组' if is_cet4 else '今晚这一组'}</span>"
        "<blockquote class='exam-warmth' data-exam-warmth>"
        "<p data-exam-warmth-text>先做完这一题，再想下一题。</p>"
        "<cite hidden data-exam-warmth-cite></cite></blockquote>"
        "<p class='exam-today-facts' data-first-screen-slot='progress' data-exam-today-facts>正在读取今晚的题。</p>"
        "<strong class='hero-progress' hidden data-double6-hook='progress-label'>打开就能开始</strong>"
        "</div></header>"
        "<div class='exam-home-main'>"
        "<section id='exam-now' class='exam-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='exam-topic-strip' data-exam-topics></div>"
        "<div data-exam-now></div>"
        "<button type='button' data-double6-primary-action='true' data-exam-submit data-exam-home-submit "
        f"data-dashboard-module-link='{_e(practice['id'])}'>提交这题</button>"
        f"<p class='exam-disclaimer'>{'项目自编练习，非真题、非通过保证。没有合适英文语音时会显示“朗读不可用”。' if is_cet4 else '自编通用题，不是真题，也不保证上岸。'}</p>"
        "</section>"
        "<aside class='exam-errors-panel dashboard-panel' data-first-screen-slot='supporting_panel'>"
        "<div class='panel-heading'><div><span class='eyebrow'>错题回炉</span><h2>错过的再做</h2></div></div>"
        "<div data-exam-error-list></div>"
        "<p>回炉只表示错过，不是掌握，更不是排名。</p>"
        f"{shell}"
        "</aside>"
        "</div>"
        f"{cet4_support}"
        "</section>"
    )
    if not is_cet4:
        dashboard = civil_desk
    return _base_result(
        "exam_practice_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


def _research_tonight(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    module_links = "".join(
        f"<a class='text-link' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'>{_e(row['name'])}</a>"
        for row in rows
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view research-tonight-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='research-tonight-claim-v1' data-research-tonight-board>"
        "<header class='scene-hero research-hero' data-first-screen-slot='hero'><div>"
        "<span class='hero-kicker'>今晚这条结论</span>"
        "<h1>打开就写下今晚这条带出处的结论</h1>"
        "<blockquote class='research-warmth' data-research-warmth>"
        "<p data-research-warmth-text>没有出处，就先标缺口。不要写成已经证实。</p>"
        "<cite hidden data-research-warmth-cite></cite></blockquote>"
        "<strong class='hero-progress research-today-facts' data-first-screen-slot='progress' data-double6-hook='progress-label' data-research-today-facts>正在读取今晚结论。</strong>"
        "</div>"
        f"<span class='hero-motif' data-double6-emoji-role='brand' aria-hidden='true'>{_e(template['motif'])}</span>"
        "</header>"
        "<section id='research-tonight-now' class='research-tonight-now dashboard-panel' data-first-screen-slot='primary_surface' data-today-workboard>"
        "<div class='research-tonight-grid'>"
        "<article class='research-tonight-card' data-research-claim-card><span class='eyebrow'>今晚这条结论</span>"
        "<div data-research-claim-list></div>"
        "<form class='research-inline-form' data-research-claim-form>"
        "<label>结论<textarea required maxlength='240' data-research-claim-title placeholder='例如 没有出处就不能写成已证实'></textarea></label>"
        "<label>出处或缺口<select required data-research-claim-source><option value=''>先选一条出处，或标缺口</option><option value='gap'>标缺口：尚未核验来源</option></select></label>"
        "<button type='submit' data-double6-primary-action='true'>留下今晚这条</button></form>"
        "<small>没有出处就标缺口。本页不发表，也不生成无来源结论。</small></article>"
        "<article class='research-tonight-card' data-research-evidence-card><span class='eyebrow'>挂上的出处</span>"
        "<div data-research-evidence-list></div>"
        "<form class='research-inline-form' data-research-evidence-form>"
        "<label>来源<input required maxlength='80' data-research-evidence-title placeholder='例如 一篇公开摘录'></label>"
        "<label>记下了什么<input maxlength='160' data-research-evidence-notes placeholder='一句摘录，可空'></label>"
        "<button type='submit'>记下这条出处</button></form>"
        "<small>未核验摘录只能当出处，不能当成已经证实。</small></article>"
        "<article class='research-tonight-card' data-research-question-card><span class='eyebrow'>今晚这个问题</span>"
        "<div data-research-question-list></div>"
        "<form class='research-inline-form' data-research-question-form>"
        "<label>问题<input required maxlength='120' data-research-question-title placeholder='例如 今晚先回答哪一件'></label>"
        "<button type='submit'>钉住今晚这问</button></form>"
        "<small>一个问题就够。课堂材料和论文不要混在这一页。</small></article>"
        "</div></section>"
        "<aside class='research-privacy' data-first-screen-slot='supporting_panel'>数据只在这台设备。不要把未核验摘录写成事实，也不要写已发表。"
        f"<div class='research-module-links'>{module_links}</div>"
        "<div class='today-actions'><button type='button' class='secondary' data-double6-hook='quick-export'>导出备份</button>"
        "<label class='secondary today-import'><span>导入恢复</span><input class='hidden' data-double6-hook='quick-import' type='file' accept='application/json,text/plain,.json,.txt'></label></div></aside>"
        "</section>"
    )
    return _base_result(
        "research_tonight_dashboard",
        dashboard,
        capabilities,
        detail_renderer,
        emojis,
        ["progress-label"],
        insert_today_workboard=False,
        product=product,
    )


RENDERERS = {
    "child_playground_v2": _child,
    "creator_production_dashboard": _creator,
    "personal_week_dashboard": _personal_week,
    "sales_followup_dashboard": _sales_followup,
    "teacher_lesson_dashboard": _teacher,
    "teacher_class_dashboard": _teacher_class,
    "exam_practice_dashboard": _exam_practice,
    "freelance_delivery_dashboard": _freelance,
    "travel_departure_dashboard": _travel,
    "finance_month_close_dashboard": _finance,
    "finance_tonight_dashboard": _finance_tonight,
    "household_week_dashboard": _household,
    "household_tonight_dashboard": _household_tonight,
    "commerce_tonight_dashboard": _commerce_tonight,
    "fitness_sprint_dashboard": _fitness,
    "personal_life_dashboard": _life,
    "composition_dashboard": _composition_pipeline,
    "generic_dashboard": _generic,
    "research_tonight_dashboard": _research_tonight,
    "research_reading_dashboard": _research,
}


def registered_renderer_ids() -> set[str]:
    return set(RENDERERS)


def render_scene(
    product: dict[str, Any],
    design: dict[str, Any],
    capabilities: list[dict[str, Any]],
    template: dict[str, Any],
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    """按固定接口编译场景首页；已登记 renderer 缺失时由调用方提前阻断。"""
    renderer_id = str(design["current"].get("renderer_id") or "generic_dashboard")
    renderer = RENDERERS.get(renderer_id)
    if renderer is None:
        raise ValueError(f"未知 renderer：{renderer_id}")
    return renderer(
        product,
        template,
        capabilities,
        runtime_context["detail_renderer"],
        runtime_context["emojis"],
    )
