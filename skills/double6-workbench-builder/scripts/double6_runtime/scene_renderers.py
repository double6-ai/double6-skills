"""场景首页 renderer：首屏聚焦，全部核心模块保持可达。"""

from __future__ import annotations

import html
from collections.abc import Callable
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


def _module_rows(capabilities: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(row["recommendation_module_id"]),
            "name": str(row["name"]),
            "description": str(row.get("description", "")),
        }
        for row in capabilities
    ]


def _nav_icon_id(label: str) -> str:
    return next((icon_id for words, icon_id in NAV_ICON_RULES if any(word in label for word in words)), "list_alt")


NAV_LABEL_RULES = [
    (("首页",), "首页"),
    (("数据", "备份", "恢复"), "数据"),
    (("错题",), "错题"),
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
    (("执行", "计划", "待办", "日程"), "计划"),
    (("灵感",), "灵感"),
    (("心情",), "心情"),
    (("记账", "储蓄", "收支"), "记账"),
    (("饮食",), "饮食"),
]


def _compact_nav_label(label: str) -> str:
    """侧栏只放高辨识度短标签；完整模块名继续留在 aria-label 与页面正文。"""
    return next((short for words, short in NAV_LABEL_RULES if any(word in label for word in words)), label[:4])


def _nav_item(view_id: str, label: str, emoji: str) -> dict[str, str]:
    return {"view_id": view_id, "label": label, "nav_label": _compact_nav_label(label), "emoji": emoji}


def _link(row: dict[str, str], label: str | None = None, class_name: str = "text-link") -> str:
    return (
        f"<a class='{class_name}' href='#module-{_e(row['id'])}' "
        f"data-dashboard-module-link='{_e(row['id'])}'>{_e(label or row['name'])}</a>"
    )


def _hero(
    product: dict[str, Any],
    template: dict[str, Any],
    eyebrow: str,
    title: str,
    body: str,
    primary: dict[str, str],
    action_label: str,
) -> str:
    return (
        "<header class='scene-hero' data-first-screen-slot='hero'>"
        f"<div><span class='hero-kicker'>{_e(eyebrow)}</span><h1>{_e(title)}</h1><p>{_e(body)}</p>"
        f"<a class='primary-cta' href='#module-{_e(primary['id'])}' data-double6-primary-action='true' "
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
    dashboard_html = dashboard_html[:hero_end] + _today_workboard(primary) + dashboard_html[hero_end:]
    details = "".join(
        detail_renderer(row, index == 0, emoji)
        for index, (row, emoji) in enumerate(zip(capabilities, emojis, strict=True))
    )
    nav_items = [_nav_item("dashboard", "首页", "🏠")]
    nav_items.extend(
        _nav_item(f"module-{row['recommendation_module_id']}", str(row["name"]), emoji)
        for row, emoji in zip(capabilities, emojis, strict=True)
    )
    nav_items.append(_nav_item("data-tools", "数据", "💾"))
    return {
        "renderer_id": renderer_id,
        "dashboard_html": dashboard_html,
        "detail_views_html": details,
        "nav_items": nav_items,
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
        "<strong data-reward-balance>0 ⭐</strong><small>答对题目就能赚星星，去成长收集册兑换奖励、点亮徽章</small></section><section class='encouragement'><strong>想再做一点？</strong>"
        f"<div class='mini-action-grid'>{mini_links}</div></section>"
        "<section class='reward-box'><strong>成长收集册 · 从第一张完成卡开始</strong><p>先完成一项真实任务，再到成长收集册记录自己的小进步。</p></section></aside></div>"
        + "</div><section class='child-parent-review dashboard-panel child-view-parent' hidden><span class='eyebrow'>家长回顾</span><h2>先看完成情况，再决定是否减负或调整</h2>"
        "<p data-child-parent-summary>正在读取本机的练习与错题线索。</p><div class='child-parent-boundary'><strong>这是同一台设备上的查看方式，不是账号、密码或隐私权限。</strong>"
        "<p>不自动判断学习能力、健康或行为；需要调整时只基于当前已保存的事实。</p></div>"
        f"{parent_adjustment}</section>"
        + "</section>"
    )
    return _base_result("child_learning_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label", "completion", "progress-bar"])


def _creator(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    stages = "".join(
        f"<a class='pipeline-stage' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'><span>0{index + 1}</span>"
        f"<strong>{_e(label)}</strong><small data-dashboard-module-status='{_e(row['id'])}'>还没有项目</small></a>"
        for index, (row, label) in enumerate(zip(rows[1:4], ["选题", "制作", "排期"], strict=False))
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view creator-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='creator-production-pipeline-v1'>"
        + _hero(product, template, "内容制作 · 把灵感推进到可发布", "今天推进哪一个作品？", "从素材入口开始，经过制作与排期；发布仍由你人工确认。", rows[0], "收下一条素材")
        + "<section class='production-board' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>制作管道</span>"
        "<h2>选题 → 制作 → 排期</h2></div><strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<div class='pipeline'>{stages}</div></section>"
        "<div class='creator-lower'><section class='asset-inbox' data-first-screen-slot='supporting_panel'><span class='eyebrow'>素材入口</span>"
        "<h2>先收集，再判断</h2><p>来源、观点和可用素材统一落到信息输入，避免灵感散在聊天与收藏里。</p>"
        f"{_link(rows[0], '打开素材收件箱', 'text-link')}</section>"
        "<section class='publish-reminder'><span>人工发布提醒</span><strong>没有自动发布</strong><p>页面只记录计划与结果，不会替你连接平台。</p></section></div>"
        + "</section>"
    )
    return _base_result("creator_production_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])


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
    return _base_result("teacher_lesson_dashboard", dashboard, capabilities, detail_renderer, emojis, ["completion", "records"])


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
    return _base_result("freelance_delivery_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label", "active", "latest"])


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
    return _base_result("travel_departure_dashboard", dashboard, capabilities, detail_renderer, emojis, ["countdown", "records", "active", "completion"])


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
    return _base_result("finance_month_close_dashboard", dashboard, capabilities, detail_renderer, emojis, ["records", "active", "completion"])


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
    return _base_result("household_week_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])


def _fitness(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view fitness-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='fitness-sprint-circuit-v1'>"
        + _hero(product, template, "今日训练 · 按步骤完成", "准备好开始第一组了吗？", "训练、饮水与恢复只记录你输入的事实，不提供医疗诊断。", rows[0], "开始今日训练")
        + "<div class='fitness-layout'><section class='circuit-card dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'>"
        "<div><span class='eyebrow'>今日步骤</span><h2>热身 → 主训练 → 放松</h2></div><strong data-dashboard-metric='completion'>0%</strong></div>"
        "<ol class='circuit'><li><span>01</span><div><strong>热身</strong><small>等待你添加动作</small></div></li>"
        "<li><span>02</span><div><strong>主训练</strong><small data-dashboard-metric='records'>0 组已录</small></div></li>"
        "<li><span>03</span><div><strong>放松</strong><small>按身体感受调整</small></div></li></ol></section>"
        "<aside class='recovery-panel' data-first-screen-slot='supporting_panel'><span class='eyebrow'>恢复提示</span><strong>先看自己的记录</strong>"
        "<p>若出现不适请停止训练并寻求专业意见。</p><div class='week-bars'><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>"
        "<small>本周安排从空白开始</small></aside></div>"
        + "</section>"
    )
    return _base_result("fitness_sprint_dashboard", dashboard, capabilities, detail_renderer, emojis, ["completion", "records"])


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
        + "<section class='life-metrics' data-first-screen-slot='progress'><div class='metric-card'><span>今日支出</span><strong data-life-metric='spending'>¥0</strong></div>"
        "<div class='metric-card'><span>储蓄余额</span><strong data-life-metric='savings'>¥0</strong><small data-life-goal-progress>尚未设置目标</small></div>"
        "<div class='metric-card'><span>今日饮食</span><strong data-life-metric='calories'>0 kcal</strong><small data-life-food-reference>未设置参考值</small></div>"
        "<div class='metric-card'><span>连续运动</span><strong data-life-metric='streak'>0 天</strong></div></section>"
        + f"<section class='life-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><div><span class='eyebrow'>今天可直接完成</span><h2>选一个入口，就从这里开始</h2></div><strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div><div class='life-card-grid'>{cards}</div></section>"
        "<aside class='life-support' data-first-screen-slot='supporting_panel'><span class='eyebrow'>本月运动日历</span><div class='life-calendar' data-life-calendar></div><p>只有完成训练才会点亮日期；停止或未完成不会计入连续天数。</p><label class='surface-field'>储蓄目标（元）<input data-life-savings-goal type='number' min='1' inputmode='decimal' placeholder='例如 3000'></label><button type='button' class='secondary' data-life-save-goal>保存储蓄目标</button><small>目标仅用于本地展示，进度只按“存入/取出储蓄”流水计算。</small><label class='surface-field'>饮食参考值（kcal）<input data-life-food-goal type='number' min='1' inputmode='decimal' placeholder='仅展示，不做建议'></label><button type='button' class='secondary' data-life-save-food-goal>保存饮食参考值</button><small>参考值只用于展示，不生成减脂处方、营养诊断或推荐摄入量。</small></aside>"
        + "</section>"
    )
    result = _base_result("personal_life_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])
    result["nav_items"] = [_nav_item("dashboard", "首页", "🏠")]
    result["nav_items"].extend(
        _nav_item(f"module-{row['id']}", row["name"], emoji)
        for row, emoji in zip(rows, emojis, strict=True)
    )
    result["nav_items"].append(_nav_item("data-tools", "数据", "💾"))
    return result


def _generic(product: dict[str, Any], template: dict[str, Any], capabilities: list[dict[str, Any]], detail_renderer: Callable[[dict[str, Any], bool, str], str], emojis: list[str]) -> dict[str, Any]:
    rows = _module_rows(capabilities)
    cards = "".join(
        f"<a class='generic-work-card' href='#module-{_e(row['id'])}' data-dashboard-module-link='{_e(row['id'])}'><span>{emojis[index]}</span>"
        f"<div><strong>{_e(row['name'])}</strong><small>{_e(row['description'])}</small></div></a>"
        for index, row in enumerate(rows)
    )
    dashboard = (
        "<section id='dashboard' class='app-view dashboard-view generic-dashboard is-active' data-view-id='dashboard' "
        "data-dashboard-signature='generic-priority-board-v1'>"
        + _hero(product, template, "个人工作台", product["title"], "先进入最重要的工作面，其他记录按需打开。", rows[0], f"开始{rows[0]['name']}")
        + f"<section class='generic-board dashboard-panel' data-first-screen-slot='primary_surface'><div class='panel-heading'><h2>现在要做什么</h2>"
        "<strong data-double6-hook='progress-label'>已保存 0 条记录</strong></div>"
        f"<div class='generic-card-grid'>{cards}</div></section>"
        + "<aside class='generic-support' data-first-screen-slot='supporting_panel'><p>所有进度都从本机记录开始计算。</p></aside></section>"
    )
    return _base_result("generic_dashboard", dashboard, capabilities, detail_renderer, emojis, ["progress-label"])


RENDERERS = {
    "child_learning_dashboard": _child,
    "creator_production_dashboard": _creator,
    "teacher_lesson_dashboard": _teacher,
    "freelance_delivery_dashboard": _freelance,
    "travel_departure_dashboard": _travel,
    "finance_month_close_dashboard": _finance,
    "household_week_dashboard": _household,
    "fitness_sprint_dashboard": _fitness,
    "personal_life_dashboard": _life,
    "generic_dashboard": _generic,
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
