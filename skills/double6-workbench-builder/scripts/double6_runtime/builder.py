"""单候选构建器：公共壳层、精确场景 renderer、starter 与安全本地状态。"""

from __future__ import annotations

import base64
import html
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import (
    ContractError, REFERENCES, canonical, commit, digest_bytes, load_run, now,
    product_content_sha256, read_json, require_state, schema, transition,
)
from .routing import style_hint
from .scene_renderers import (
    VISUAL_CONTRACT_VERSION,
    registered_renderer_ids,
    render_scene,
)


TOKEN_IDS = {"general-focus", "professional-trust", "editorial-story", "playful-growth", "high-contrast-execution"}
TEMPLATE_IDS = {
    "coral_sprout", "cosmic_grape", "lesson_bloom", "sky_postcard", "studio_sunset", "ink_parchment",
    "ledger_jade", "home_sunrise", "energy_sprint",
}
SCENE_TEMPLATE_IDS = {
    "child_learning_quest", "teacher_lesson_studio", "freelance_delivery_studio",
    "travel_departure_atlas", "creator_production_room", "finance_month_close",
    "household_week_coordination", "fitness_week_sprint", "personal_life_dashboard",
}
FIRST_SCREEN_SLOTS = {"hero", "primary_surface", "progress", "supporting_panel"}
EMOJI_RULES = [
    (("口算", "数学", "计算", "指标", "收支"), "🧮"),
    (("阅读", "读书", "资料", "文献", "素材"), "📚"),
    (("写", "记录", "日志", "复盘"), "✍️"),
    (("运动", "训练", "健身", "恢复"), "🏃"),
    (("日程", "计划", "排期", "预约"), "📅"),
    (("客户", "学生", "跟进", "管道"), "🤝"),
    (("分析", "数据", "成绩", "库存"), "📊"),
    (("内容", "选题", "发布"), "💡"),
]
EMOJI_FALLBACKS = ["🧩", "🎯", "🗂️", "📝", "⭐", "🔖", "🪄", "🌈"]


def _design_system() -> dict[str, Any]:
    value = read_json(REFERENCES / "design-system.json")
    if value.get("schema_version") != 3 or len(value.get("tokens", {})) != 5:
        raise ContractError("design-system 必须包含五组可执行视觉 token")
    return value


def _template_system() -> dict[str, Any]:
    value = read_json(REFERENCES / "vivid-social-template-system.json")
    ids = {row.get("template_id") for row in value.get("templates", [])}
    required_tokens = set(value.get("common_kernel", {}).get("color_contract", {}).get("required_tokens", []))
    if (
        value.get("schema_version") != 4
        or value.get("default_template_id") != "coral_sprout"
        or ids != TEMPLATE_IDS
        or len(required_tokens) != 14
        or {row.get("scene_template_id") for row in value.get("scene_templates", [])} != SCENE_TEMPLATE_IDS
    ):
        raise ContractError("鲜艳社媒模板系统必须包含九套去重模板、九个精确场景模板和十四个颜色 token")
    for row in value["templates"]:
        if set(row.get("palette", {})) != required_tokens:
            raise ContractError(f"模板颜色 token 不完整：{row.get('template_id')}")
    renderer_ids = registered_renderer_ids()
    for row in value["scene_templates"]:
        if (
            row.get("renderer_id") not in renderer_ids
            or row.get("visual_contract_version") != VISUAL_CONTRACT_VERSION
            or set(row.get("first_screen_slots", [])) != FIRST_SCREEN_SLOTS
            or row.get("detail_mode") != "single_active_view"
            or row.get("visual_status") not in {"candidate_needs_user_review", "user_accepted"}
            or "continuous_crud_forms_on_dashboard" not in row.get("forbidden_fallbacks", [])
        ):
            raise ContractError(f"场景 renderer 合同不完整：{row.get('scene_template_id')}")
    return value


BRAND_ICON_SET = "double6_brand"
ICON_SET_SPECS = {
    ("64x64", "favicon"), ("180x180", "apple-touch"),
    ("192x192", "any"), ("512x512", "any"), ("512x512", "maskable"),
}


def _icon_sets() -> dict[str, dict[str, str]]:
    """加载按模板离线渲染的 PNG 图标集。

    每套图标与首页标题旁品牌块一致（模板 motif emoji + 模板主色圆角块）；
    double6_brand 套保留 Double6 品牌图标，供用户明确要求时选用。
    """
    source = REFERENCES / "app-icons.json"
    if not source.is_file():
        raise ContractError("缺少应用图标集：references/app-icons.json")
    value = read_json(source)
    if value.get("schema_version") != 1 or value.get("contract_version") != "double6_template_icons_v1":
        raise ContractError("app-icons schema/contract 版本无效")
    raw_sets = value.get("sets", {})
    if set(raw_sets) != TEMPLATE_IDS | {BRAND_ICON_SET}:
        raise ContractError("app-icons 必须覆盖九套模板与 double6_brand 品牌套")
    templates = {row["template_id"]: row for row in _template_system()["templates"]}
    sets: dict[str, dict[str, str]] = {}
    for set_id, entry in raw_sets.items():
        template = templates.get(set_id)
        if template and (entry.get("motif") != template["motif"] or entry.get("background") != template["palette"]["primary"]):
            raise ContractError(f"app-icons 与首页品牌块不一致：{set_id}")
        icons: dict[str, str] = {}
        seen = set()
        for row in entry.get("icons", []):
            key = (str(row.get("sizes") or ""), str(row.get("purpose") or ""))
            if key not in ICON_SET_SPECS or key in seen or row.get("type") != "image/png":
                raise ContractError(f"app-icons 条目无效：{set_id} {key}")
            seen.add(key)
            raw = base64.b64decode(str(row.get("png_base64") or ""))
            width, height = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
            if not raw.startswith(b"\x89PNG") or f"{width}x{height}" != key[0]:
                raise ContractError(f"app-icons PNG 尺寸与声明不符：{set_id} {key}")
            icons[f"{key[0]}:{key[1]}"] = base64.b64encode(raw).decode("ascii")
        if seen != ICON_SET_SPECS:
            raise ContractError(f"app-icons 套不完整：{set_id} 缺 {sorted(ICON_SET_SPECS - seen)}")
        sets[set_id] = icons
    return sets


def _icon_set_for(product: dict[str, Any], template_id: str) -> dict[str, str]:
    """图标默认跟随当前视觉模板；用户明确要求时经 design_brief.icon_override 指定另一套模板或 double6_brand。"""
    override = product.get("design_brief", {}).get("icon_override")
    if override is None:
        set_id = template_id
    elif override in TEMPLATE_IDS or override == BRAND_ICON_SET:
        set_id = str(override)
    else:
        raise ContractError("design_brief.icon_override 必须是九套模板之一或 double6_brand")
    return _icon_sets()[set_id]


def _pwa_head(product: dict[str, Any], palette: dict[str, Any], icons: dict[str, str]) -> str:
    """生成单文件 PWA 就绪元数据：内嵌 manifest 与 Apple 主屏标签。

    只声明元数据，不注册 service worker，也不承诺可安装；真正的安装提示依赖独立发布流程提供 https 入口。
    """
    title = str(product["title"]).strip()
    short_name = title[:12] if len(title) > 12 else title
    manifest = {
        "name": title,
        "short_name": short_name,
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "background_color": str(palette["canvas"]),
        "theme_color": str(palette["primary"]),
        "icons": [
            {"src": f"data:image/png;base64,{icons['192x192:any']}", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": f"data:image/png;base64,{icons['512x512:any']}", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": f"data:image/png;base64,{icons['512x512:maskable']}", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    manifest_uri = "data:application/manifest+json;base64," + base64.b64encode(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    apple_icon = f"data:image/png;base64,{icons['180x180:apple-touch']}"
    return (
        f"<meta name='mobile-web-app-capable' content='yes'>"
        f"<meta name='apple-mobile-web-app-capable' content='yes'>"
        f"<meta name='apple-mobile-web-app-status-bar-style' content='default'>"
        f"<meta name='apple-mobile-web-app-title' content='{_e(short_name)}'>"
        f"<link rel='apple-touch-icon' href='{apple_icon}'>"
        f"<link rel='manifest' href='{manifest_uri}'>"
    )


def _scene_template(system: dict[str, Any], requirements: dict[str, Any], product: dict[str, Any]) -> dict[str, Any] | None:
    primary_domain = requirements["route"].get("primary_domain")
    profile_id = product.get("recommendation_plan", {}).get("profile_id")
    selected_modules = set(product.get("recommendation_plan", {}).get("selected_core_module_ids", []))
    request_text = str(requirements.get("request_text", ""))

    def matches(row: dict[str, Any]) -> bool:
        if primary_domain not in set(row.get("domain_ids", [])):
            return False
        rule = row.get("match", {})
        profiles = set(rule.get("profile_ids", []))
        if profiles and profile_id not in profiles:
            return False
        required_modules = set(rule.get("required_module_ids", []))
        if required_modules and not required_modules <= selected_modules:
            return False
        request_any = [str(marker) for marker in rule.get("request_any", [])]
        if request_any and not any(marker in request_text for marker in request_any):
            return False
        request_none = [str(marker) for marker in rule.get("request_none", [])]
        return not any(marker in request_text for marker in request_none)

    requested = product.get("design_brief", {}).get("scene_template_id")
    if requested in SCENE_TEMPLATE_IDS:
        selected = next(row for row in system["scene_templates"] if row["scene_template_id"] == requested)
        if not matches(selected):
            raise ContractError("scene_template_id 与当前主场景、子场景或核心模块不匹配")
        return selected
    return next((row for row in system["scene_templates"] if matches(row)), None)


def _select_design(run_dir: Path, product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    system, template_system = _design_system(), _template_system()
    previous = read_json(run_dir / "design.json") if (run_dir / "design.json").is_file() else {
        "schema_version": schema("design"), "status": "new", "visual_attempts": [], "build_history": [],
        "feedback": [], "visual_preferences": {}, "revision_cycle": 0,
    }
    requirements = read_json(run_dir / "requirements.json")
    scene = _scene_template(template_system, requirements, product)
    preferences = dict(previous.get("visual_preferences", {}))
    current = previous.get("current", {})
    dimensions = set(preferences.get("feedback_dimensions", []))
    requested_token = preferences.get("token_id") or product.get("design_brief", {}).get("style_token")
    token_id = requested_token if requested_token in TOKEN_IDS else (scene["token_id"] if scene else style_hint(requirements["route"]))
    token = system["tokens"][token_id]
    requested_template = preferences.get("template_id") or product.get("design_brief", {}).get("template_id")
    if requested_template in TEMPLATE_IDS:
        template_id = requested_template
    elif scene:
        template_id = scene["template_id"]
    elif previous.get("status") == "revision_requested" and current.get("template_id") in TEMPLATE_IDS and "color" not in dimensions:
        template_id = current["template_id"]
    else:
        template_id = template_system["default_template_id"]
    template = next(row for row in template_system["templates"] if row["template_id"] == template_id)
    experience = dict(product["design_brief"]["experience"])
    signature = digest_bytes(canonical(experience))
    attempt = {
        "attempt_id": f"attempt-{len(previous.get('visual_attempts', [])) + 1}",
        "token_id": token_id, "template_id": template_id, "scene_template_id": scene["scene_template_id"] if scene else None,
        "renderer_id": scene["renderer_id"] if scene else "generic_dashboard",
        "visual_contract_version": scene["visual_contract_version"] if scene else VISUAL_CONTRACT_VERSION,
        "experience_signature": signature,
        "feedback_dimensions": sorted(dimensions), "attempted_at": now(),
    }
    design = {
        "schema_version": schema("design"), "status": "selected",
        "current": {
            "token_id": token_id, "template_id": template_id,
            "template_system_id": template_system["system_id"], "scene_template_id": scene["scene_template_id"] if scene else None,
            "renderer_id": scene["renderer_id"] if scene else "generic_dashboard",
            "visual_contract_version": scene["visual_contract_version"] if scene else VISUAL_CONTRACT_VERSION,
            "palette_status": template["palette_status"], "scene_id": experience["scene_id"],
            "experience_signature": signature, "content_pack_id": product["recommendation_plan"]["pack_id"],
            "recommendation_sha256": product["recommendation_plan"]["recommendation_sha256"],
            "surface_registry_version": product["recommendation_plan"]["surface_registry_version"],
        },
        "experience": experience, "visual_attempts": [*previous.get("visual_attempts", []), attempt],
        "build_history": list(previous.get("build_history", [])), "feedback": list(previous.get("feedback", [])),
        "visual_preferences": preferences, "revision_cycle": int(previous.get("revision_cycle", 0)), "updated_at": now(),
    }
    return design, token, template


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _emojis(labels: list[str], reserved: set[str]) -> list[str]:
    used, result = set(reserved), []
    for label in labels:
        emoji = next((mark for words, mark in EMOJI_RULES if mark not in used and any(word in label for word in words)), None)
        emoji = emoji or next((mark for mark in EMOJI_FALLBACKS if mark not in used), "✨")
        used.add(emoji)
        result.append(emoji)
    return result


def _navigation_emoji(item: dict[str, Any]) -> str:
    """导航和首页卡片共用同一枚系统彩色 emoji，避免窄屏退化成单色字形。"""
    emoji = str(item.get("emoji") or "🧩")
    return f"<span class='nav-icon' data-double6-emoji-role='navigation' aria-hidden='true'>{_e(emoji)}</span>"


def _safe_script_json(value: Any) -> str:
    """把 JSON 安全嵌入 script，阻断 </script> 与 HTML 实体逃逸。"""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _field_html(module_id: str, field: dict[str, Any]) -> str:
    field_id, field_type = str(field["field_id"]), str(field["type"])
    required = " required" if field.get("required") else ""
    attrs = f"data-double6-field data-field-id='{_e(field_id)}' id='{_e(module_id)}-{_e(field_id)}'{required}"
    if field_type == "textarea":
        control = f"<textarea {attrs}></textarea>"
    elif field_type == "select":
        options = "".join(f"<option value='{_e(option)}'>{_e(option)}</option>" for option in field.get("options", []))
        control = f"<select {attrs}>{options}</select>"
    elif field_type == "boolean":
        control = f"<input type='checkbox' {attrs}>"
    else:
        inputmode = " inputmode='decimal'" if field_type == "number" else ""
        control = f"<input type='{_e(field_type)}'{inputmode} {attrs}>"
    return f"<label class='surface-field' for='{_e(module_id)}-{_e(field_id)}'><span>{_e(field['label'])}</span>{control}</label>"


def _surface_label(surface_type: str) -> str:
    """把存储合同名称留在代码中，页面只说用户能理解的事。"""
    return {
        "action_checklist": "待完成的小事",
        "record_ledger": "我的记录",
        "stage_board": "进度安排",
        "metric_log": "数据记录",
        "review_journal": "复盘笔记",
        "reward_economy": "星星与奖励",
    }.get(surface_type, "我的内容")


def _surface_section(capability: dict[str, Any], primary: bool, emoji: str) -> str:
    module_id, surface = str(capability["recommendation_module_id"]), capability["surface"]
    starter = capability["starter"]
    fields = "".join(_field_html(module_id, row) for row in surface["fields"])
    filter_box = "<label class='surface-filter'><span>筛选记录</span><input type='text' data-module-filter placeholder='输入关键词'></label>" if "filter" in surface["operations"] else ""
    save_hook = " data-double6-hook='save'" if primary else ""
    work_input_hook = " data-double6-hook='work-input'" if primary else ""
    feature = capability.get("learning_feature")
    feature_html = ""
    if isinstance(feature, dict):
        modes = "".join(f"<li>{_e(mode)}</li>" for mode in feature.get("modes", []))
        feature_html = (
            "<section class='learning-feature' data-learning-feature>"
            "<span class='eyebrow'>这个模块会怎么学</span>"
            f"<h3>{_e(feature.get('learning_goal', ''))}</h3>"
            f"<p><strong>内容轮换：</strong>{_e(feature.get('content_map', ''))}</p>"
            f"<ul>{modes}</ul><p><strong>完成后：</strong>{_e(feature.get('completion', ''))}</p>"
            f"<p><strong>下次继续：</strong>{_e(feature.get('review_trigger', ''))}</p>"
            f"<small>{_e(feature.get('guardrail', ''))}</small></section>"
        )
    reward_html = ""
    if surface["type"] == "reward_economy":
        reward_html = (
            "<section class='reward-economy' data-reward-root>"
            "<div class='reward-balance-card'><span class='eyebrow'>我的星星</span><strong data-reward-balance>0 ⭐</strong>"
            "<small data-reward-summary>完成练习就能赚星星</small></div>"
            "<div class='reward-section'><span class='eyebrow'>星星小卖部</span><div class='reward-shop-grid' data-reward-shop></div></div>"
            "<div class='reward-section'><span class='eyebrow'>徽章墙</span><div class='reward-badge-grid' data-reward-badges></div></div>"
            "<div class='reward-section'><span class='eyebrow'>练习日历</span><div class='life-calendar reward-calendar-grid' data-reward-calendar></div>"
            "<small data-reward-streak></small></div>"
            "<div class='reward-section'><span class='eyebrow'>兑换记录</span><div class='reward-history' data-reward-history></div></div>"
            "</section>"
        )
    return (
        f"<section id='module-{_e(module_id)}' class='app-view workspace module-surface' data-view-id='module-{_e(module_id)}' hidden "
        f"data-double6-module-id='{_e(module_id)}' data-double6-work-object='{_e(capability['work_object_ids'][0])}' "
        f"data-double6-spec-id='{_e(capability['capability_id'])}' data-double6-surface-type='{_e(surface['type'])}' "
        f"data-double6-surface-registry-version='{surface['registry_version']}'>"
        "<a class='back-dashboard' href='#dashboard'>← 返回首页</a>"
        f"<div class='module-heading'><span class='capability-emoji' data-double6-emoji-role='capability' aria-hidden='true'>{emoji}</span><div><span class='eyebrow'>{_e(_surface_label(str(surface['type'])))}</span>"
        f"<h2>{_e(capability['name'])}</h2><p>{_e(capability.get('description', ''))}</p></div></div>"
        f"{feature_html}"
        f"<section class='starter-surface' data-starter-root data-starter-contract-version='{_e(starter['contract_version'])}' "
        f"data-starter-item-count='{len(starter['starter_items'])}'><div class='starter-heading'><div><span class='eyebrow'>先从这里开始</span>"
        f"<h3>{_e(starter['summary'])}</h3></div><small>可反复练习，进度只保存在这台设备上</small></div>"
        "<div class='starter-content' data-starter-content></div><p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        f"{reward_html}"
        "<div class='own-record-heading'><span class='eyebrow'>有自己的内容再填这里</span><p>上面的内容已经可以直接使用。只有要保存老师布置的内容、自己的错题或安排时，才需要填写下面这部分。</p></div>"
        f"<form data-module-form{work_input_hook}><div class='surface-fields'>{fields}</div><div class='form-actions'>"
        f"<button type='submit' data-module-save{save_hook}>保存记录</button><button type='button' class='secondary' data-module-cancel hidden>取消编辑</button></div></form>"
        f"{filter_box}<p class='feedback' data-module-feedback data-double6-hook='save-success' aria-live='polite'></p><span class='hidden' data-double6-hook='save-error'></span>"
        "<div class='record-list' data-module-records><p class='empty-record'>还没有自己的记录；上方内置内容仍可直接使用。</p></div></section>"
    )


_LIFE_HELPERS = r"""
function lifeNumber(value){const number=Number(value);return Number.isFinite(number)?number:0}
function lifeDate(){return new Date().toISOString().slice(0,10)}
function lifeStreak(days){let count=0,cursor=new Date();for(;;){const date=cursor.toISOString().slice(0,10);if(!days.has(date))break;count+=1;cursor.setDate(cursor.getDate()-1)}return count}
function renderLifeDashboard(){if(!document.querySelector('.life-dashboard'))return;const finance=appState.modules['life-finance']?.records||[],food=appState.modules['life-food']?.records||[],movement=appState.modules['life-movement']?.records||[],goal=lifeNumber(appState.modules['life-finance']?.starter?.itemStates?.['life-finance-1']?.result),today=lifeDate(),spending=finance.filter(row=>row.values.entry_type==='支出'&&String(row.values.date||today)===today).reduce((sum,row)=>sum+lifeNumber(row.values.amount),0),savings=finance.reduce((sum,row)=>sum+(row.values.entry_type==='存入储蓄'?lifeNumber(row.values.amount):row.values.entry_type==='取出储蓄'?-lifeNumber(row.values.amount):0),0),calories=food.filter(row=>String(row.values.date||today)===today).reduce((sum,row)=>sum+lifeNumber(row.values.calories),0),days=new Set(movement.filter(row=>row.completed).map(row=>String(row.values.due||row.updatedAt||'').slice(0,10)).filter(Boolean)),streak=lifeStreak(days);document.querySelectorAll('[data-life-metric="spending"]').forEach(node=>node.textContent=`¥${spending.toFixed(2)}`);document.querySelectorAll('[data-life-metric="savings"]').forEach(node=>node.textContent=goal?`¥${savings.toFixed(2)} / ¥${goal.toFixed(2)}`:`¥${savings.toFixed(2)}`);document.querySelectorAll('[data-life-goal-progress]').forEach(node=>node.textContent=goal?`目标进度 ${Math.max(0,Math.min(100,savings/goal*100)).toFixed(0)}%`:'尚未设置目标');document.querySelectorAll('[data-life-savings-goal]').forEach(node=>node.value=goal||'');document.querySelectorAll('[data-life-metric="calories"]').forEach(node=>node.textContent=`${Math.round(calories)} kcal`);document.querySelectorAll('[data-life-metric="streak"]').forEach(node=>node.textContent=`${streak} 天`);document.querySelectorAll('[data-life-calendar]').forEach(root=>{const now=new Date(),year=now.getFullYear(),month=now.getMonth(),count=new Date(year,month+1,0).getDate();root.innerHTML=Array.from({length:count},(_,index)=>{const date=`${year}-${String(month+1).padStart(2,'0')}-${String(index+1).padStart(2,'0')}`,done=days.has(date),isToday=date===today;return `<span class="${done?'done ':''}${isToday?'today':''}" title="${date}">${index+1}</span>`}).join('')})}
function lifeTaggedNumber(value,prefix){const text=String(value||'');return text.startsWith(prefix)?lifeNumber(text.slice(prefix.length)):0}
function renderLifeGoals(){if(!document.querySelector('.life-dashboard'))return;const foodGoal=lifeTaggedNumber(appState.modules['life-food']?.starter?.itemStates?.['life-food-1']?.result,'food-reference:'),food=appState.modules['life-food']?.records||[],today=lifeDate(),calories=food.filter(row=>String(row.values.date||today)===today).reduce((sum,row)=>sum+lifeNumber(row.values.calories),0);document.querySelectorAll('[data-life-food-goal]').forEach(node=>node.value=foodGoal||'');document.querySelectorAll('[data-life-food-reference]').forEach(node=>node.textContent=foodGoal?`个人参考值 ${Math.round(foodGoal)} kcal（仅展示）`:'未设置参考值');if(foodGoal)document.querySelectorAll('[data-life-metric="calories"]').forEach(node=>node.textContent=`${Math.round(calories)} / ${Math.round(foodGoal)} kcal`)}
"""

_LIFE_LISTENERS = r"""
document.addEventListener('submit',()=>setTimeout(renderLifeDashboard,0));
document.addEventListener('click',()=>setTimeout(renderLifeDashboard,0));
document.addEventListener('click',event=>{const button=event.target.closest('[data-life-save-goal]');if(!button)return;const input=document.querySelector('[data-life-savings-goal]'),goal=lifeNumber(input?.value);if(!(goal>0)){dataFeedback('储蓄目标必须是大于 0 的数字。',true);return}const next=clone(appState);next.modules['life-finance'].starter.itemStates['life-finance-1']={status:'savings-goal',result:String(goal),updatedAt:new Date().toISOString()};try{persist(next);appState=next;renderLifeDashboard();dataFeedback('储蓄目标已保存在当前设备。')}catch(error){dataFeedback('储蓄目标保存失败，原值未被替换。',true)}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-life-save-food-goal]');if(!button)return;const input=document.querySelector('[data-life-food-goal]'),goal=lifeNumber(input?.value);if(!(goal>0)){dataFeedback('饮食参考值必须是大于 0 的数字。',true);return}const next=clone(appState);next.modules['life-food'].starter.itemStates['life-food-1']={status:'food-reference',result:`food-reference:${goal}`,updatedAt:new Date().toISOString()};try{persist(next);appState=next;renderLifeGoals();dataFeedback('饮食参考值已保存在当前设备。')}catch(error){dataFeedback('饮食参考值保存失败，原值未被替换。',true)}});
document.addEventListener('submit',event=>{const form=event.target;if(!(form instanceof HTMLFormElement)||!form.matches('[data-module-form]'))return;const root=form.closest('[data-double6-module-id]'),id=root?.dataset.double6ModuleId,value=name=>form.querySelector(`[data-field-id="${name}"]`)?.value;if(id==='life-finance'&&!(Number(value('amount'))>0)){event.preventDefault();feedback(id,'金额必须是大于 0 的数字。',true)}if(id==='life-food'&&!(Number(value('calories'))>0)){event.preventDefault();feedback(id,'热量必须是大于 0 的数字。',true)}if(id==='life-reading'){const current=value('current_page'),total=value('total_pages');if((current!==''&&Number(current)<0)||(total!==''&&Number(total)<0)||(current!==''&&total!==''&&Number(current)>Number(total))){event.preventDefault();feedback(id,'页码不能为负，当前页不能超过总页数。',true)}}},true);
"""

_LIFE_MOVEMENT = r"""
document.addEventListener('click',event=>{const button=event.target.closest('[data-starter-action="toggle"]'),moduleRoot=button?.closest('[data-double6-module-id]'),card=button?.closest('[data-starter-item-id]');if(!button||moduleRoot?.dataset.double6ModuleId!=='life-movement'||!card)return;const id='life-movement',itemId=card.dataset.starterItemId;setTimeout(()=>{const module=moduleById[id],item=module.starter.starter_items.find(row=>row.item_id===itemId),next=clone(appState),state=next.modules[id].starter,completed=state.itemStates[itemId]?.status==='completed',today=lifeDate(),rows=next.modules[id].records,existing=rows.findIndex(row=>row.values.details===`starter:${itemId}`&&row.values.due===today);if(completed&&existing<0)rows.unshift({id:`r-${Date.now()}-${Math.random().toString(16).slice(2)}`,values:{title:item.title,due:today,details:`starter:${itemId}`},completed:true,archived:false,createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()});if(!completed&&existing>=0)rows.splice(existing,1);try{persist(next);appState=next;renderModule(id);renderLifeDashboard()}catch(error){feedback(id,'运动记录保存失败，原状态未被替换。',true)}},0)});
"""


def _script(product: dict[str, Any], capabilities: list[dict[str, Any]], storage_key: str) -> str:
    modules = [{
        "id": row["recommendation_module_id"], "name": row["name"], "type": row["surface"]["type"],
        "fields": row["surface"]["fields"], "operations": row["surface"]["operations"],
        "starter": row["starter"], "rewards": row.get("reward_economy"),
    } for row in capabilities]
    finance_module_ids = [
        row["recommendation_module_id"]
        for row in capabilities
        if {"entry_type", "amount"} <= {field["field_id"] for field in row["surface"]["fields"]}
    ]
    source = r"""
const STORAGE_KEY=__STORAGE_KEY__,PRODUCT_ID=__PRODUCT_ID__,PACK_ID=__PACK_ID__,MODULES=__MODULES__,FINANCE_MODULE_IDS=__FINANCE_MODULE_IDS__;
const MAX_IMPORT_BYTES=2*1024*1024,MAX_RECORDS_PER_MODULE=500;
const moduleById=Object.fromEntries(MODULES.map(row=>[row.id,row]));
const emptyStarterState=()=>({itemStates:{},questionIndex:0,promptIndex:null,answers:{},mistakes:[],lastResult:null});
const emptyRewards=()=>({stars:0,earnedTotal:0,generatorCorrect:0,awardedItems:[],days:{},redeemed:[],badges:[],dailyGenerator:{date:'',count:0}});
const emptyState=()=>({schemaVersion:3,productId:PRODUCT_ID,packId:PACK_ID,modules:Object.fromEntries(MODULES.map(row=>[row.id,{records:[],starter:emptyStarterState()}])),rewards:emptyRewards(),legacyImport:null,updatedAt:new Date().toISOString()});
const clone=value=>JSON.parse(JSON.stringify(value));let appState=emptyState(),lastImportBackup=null;
const feedback=(id,message,error=false)=>{const node=document.querySelector(`[data-double6-module-id="${id}"] [data-module-feedback]`);if(node){node.textContent=message;node.className=`feedback ${error?'error':'success'}`}};
const dataFeedback=(message,error=false)=>{const node=document.querySelector('[data-double6-hook="data-feedback"]');if(node){node.textContent=message;node.className=`feedback ${error?'error':'success'}`}};
function safeRecord(module,record,index,quarantine){if(!record||typeof record!=='object'){quarantine.push(record);return null}const fields=new Map(module.fields.map(row=>[row.field_id,row])),values={};for(const [key,raw] of Object.entries(record.values||{})){const field=fields.get(key);if(!field)continue;if(field.type==='boolean')values[key]=Boolean(raw);else if(field.type==='number'){const number=Number(raw);values[key]=Number.isFinite(number)?number:''}else values[key]=String(raw??'').slice(0,10000)}const rawId=String(record.id||''),id=/^r-[a-zA-Z0-9._-]{1,120}$/.test(rawId)?rawId:`r-import-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`;if(id!==rawId||Object.keys(record).some(key=>!['id','values','completed','archived','createdAt','updatedAt'].includes(key)))quarantine.push(clone(record));return {id,values,completed:Boolean(record.completed),archived:Boolean(record.archived),createdAt:String(record.createdAt||''),updatedAt:String(record.updatedAt||'')}}
function safeStarter(module,raw){const next=emptyStarterState(),known=new Set(module.starter.starter_items.map(item=>item.item_id));if(!raw||typeof raw!=='object')return next;for(const [itemId,itemState] of Object.entries(raw.itemStates||{})){if(known.has(itemId)&&itemState&&typeof itemState==='object')next.itemStates[itemId]={status:String(itemState.status||'').slice(0,30),result:String(itemState.result||'').slice(0,1000),updatedAt:String(itemState.updatedAt||''),cycleKey:String(itemState.cycleKey||'').slice(0,30)}}for(const [itemId,answer] of Object.entries(raw.answers||{})){if(known.has(itemId)&&answer&&typeof answer==='object')next.answers[itemId]={value:String(answer.value??'').slice(0,1000),correct:Boolean(answer.correct),updatedAt:String(answer.updatedAt||'')}}next.mistakes=Array.isArray(raw.mistakes)?[...new Set(raw.mistakes.map(String).filter(id=>known.has(id)))]:[];next.questionIndex=Math.max(0,Math.min(Number(raw.questionIndex)||0,module.starter.starter_items.length-1));next.promptIndex=Number.isInteger(raw.promptIndex)&&raw.promptIndex>=0?raw.promptIndex:null;if(raw.lastResult&&typeof raw.lastResult==='object')next.lastResult={itemId:known.has(String(raw.lastResult.itemId))?String(raw.lastResult.itemId):'',message:String(raw.lastResult.message||'').slice(0,1000),updatedAt:String(raw.lastResult.updatedAt||'')};return next}
function safeRewards(raw){const next=emptyRewards();if(!raw||typeof raw!=='object')return next;const clampInt=value=>{const number=Math.floor(Number(value));return Number.isFinite(number)?Math.max(0,Math.min(number,1000000)):0};next.stars=clampInt(raw.stars);next.earnedTotal=clampInt(raw.earnedTotal);next.generatorCorrect=clampInt(raw.generatorCorrect);next.awardedItems=Array.isArray(raw.awardedItems)?[...new Set(raw.awardedItems.map(value=>String(value).slice(0,200)))].slice(0,2000):[];if(raw.days&&typeof raw.days==='object'){for(const key of Object.keys(raw.days).slice(0,400)){if(/^\d{4}-\d{2}-\d{2}$/.test(key)&&raw.days[key])next.days[key]=true}}next.redeemed=(Array.isArray(raw.redeemed)?raw.redeemed:[]).slice(0,500).filter(entry=>entry&&typeof entry==='object').map(entry=>({title:String(entry.title||'').slice(0,200),cost:clampInt(entry.cost),date:String(entry.date||'').slice(0,10),at:String(entry.at||'').slice(0,40)}));next.badges=Array.isArray(raw.badges)?[...new Set(raw.badges.map(value=>String(value).slice(0,100)))].slice(0,200):[];const daily=raw.dailyGenerator;if(daily&&typeof daily==='object')next.dailyGenerator={date:String(daily.date||'').slice(0,10),count:clampInt(daily.count)};return next}
function normalize(value){const next=emptyState();if(value&&[2,3].includes(value.schemaVersion)&&value.productId===PRODUCT_ID&&value.packId===PACK_ID&&value.modules&&typeof value.modules==='object'){const knownModuleIds=new Set(MODULES.map(row=>row.id)),unknownModules=Object.fromEntries(Object.entries(value.modules).filter(([id])=>!knownModuleIds.has(id))),moduleExtras={},quarantinedRecords={};MODULES.forEach(module=>{const source=value.modules[module.id],rows=Array.isArray(source?.records)?source.records:[];if(rows.length>MAX_RECORDS_PER_MODULE)throw new Error(`模块 ${module.name} 的记录超过 ${MAX_RECORDS_PER_MODULE} 条`);const quarantine=[];next.modules[module.id]={records:rows.map((record,index)=>safeRecord(module,record,index,quarantine)).filter(Boolean),starter:safeStarter(module,source?.starter)};if(quarantine.length)quarantinedRecords[module.id]=quarantine;if(source&&typeof source==='object'){const extra=Object.fromEntries(Object.entries(source).filter(([key])=>!['records','starter'].includes(key)));if(Object.keys(extra).length)moduleExtras[module.id]=extra}});const known=new Set(['schemaVersion','productId','packId','modules','rewards','legacyImport','updatedAt']),unknown=Object.fromEntries(Object.entries(value).filter(([key])=>!known.has(key)));next.rewards=safeRewards(value.rewards);next.legacyImport=value.legacyImport||null;if(Object.keys(unknown).length||Object.keys(unknownModules).length||Object.keys(moduleExtras).length||Object.keys(quarantinedRecords).length)next.legacyImport={...(next.legacyImport||{}),unmapped:{...(next.legacyImport?.unmapped||{}),envelope:unknown,modules:unknownModules,moduleExtras,quarantinedRecords}}}else if(value&&typeof value==='object'){next.legacyImport={notes:typeof value.value==='string'?value.value.slice(0,10000):'',completedItemIds:Array.isArray(value.checked)?value.checked.map(String).slice(0,500):[],unmapped:clone(value),importedAt:new Date().toISOString()}}else throw new Error('备份格式无效');next.updatedAt=new Date().toISOString();return next}
function persist(next){next.updatedAt=new Date().toISOString();localStorage.setItem(STORAGE_KEY,JSON.stringify(next))}
function recordText(record){return Object.values(record.values||{}).filter(value=>value!==false&&value!=null).join(' · ')}
function escapeHtml(value){const node=document.createElement('span');node.textContent=String(value);return node.innerHTML}
function attrSafe(value){return escapeHtml(value).replace(/"/g,'')}
function d6Speak(text){text=String(text||'').trim();if(!text)return false;if(!('speechSynthesis' in window))return false;window.speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.lang=/[A-Za-z]/.test(text)&&!/[一-鿿]/.test(text)?'en-US':'zh-CN';utterance.rate=.85;window.speechSynthesis.speak(utterance);return true}
function actionButtons(module,record){let extra='';if(module.operations.includes('complete'))extra+=`<button type="button" class="tiny" data-record-action="toggle-complete">${record.completed?'撤销完成':'完成'}</button>`;if(module.operations.includes('archive'))extra+=`<button type="button" class="tiny" data-record-action="toggle-archive">${record.archived?'恢复':'停用/归档'}</button>`;if(module.operations.includes('move'))extra+='<button type="button" class="tiny" data-record-action="move">推进阶段</button>';return `${extra}<button type="button" class="tiny" data-record-action="edit">编辑</button><button type="button" class="tiny danger" data-record-action="delete">删除</button>`}
function currentWeekKey(){const today=localDate(),date=new Date(`${today}T00:00:00`),offset=(date.getDay()+6)%7;date.setDate(date.getDate()-offset);return date.toISOString().slice(0,10)}
function effectiveStarterState(item,state){const row=state.itemStates[item.item_id];return item.recurrence==='weekly'&&row?.cycleKey!==currentWeekKey()?null:row}
function activeStarterStates(module){const state=appState.modules[module.id].starter;return module.starter.starter_items.map(item=>effectiveStarterState(item,state)).filter(Boolean)}
function dashboardFacts(){const records=MODULES.flatMap(row=>appState.modules[row.id].records),starterStates=MODULES.flatMap(activeStarterStates),starterCompleted=starterStates.filter(row=>['completed','correct','reviewed','prepared','calculated'].includes(row.status)).length,completed=records.filter(row=>row.completed).length+starterCompleted,active=records.filter(row=>!row.completed&&!row.archived).length,total=records.length+MODULES.reduce((count,row)=>count+row.starter.starter_items.length,0),percentage=total?Math.round(completed/total*100):0;return {records,completed,active,percentage,starterCompleted}}
function renderProgress(){const facts=dashboardFacts();document.querySelectorAll('[data-double6-hook="progress-label"]').forEach(node=>node.textContent=`内置内容已完成 ${facts.starterCompleted} 项 · 自有记录 ${facts.records.length} 条`);document.querySelectorAll('[data-dashboard-metric]').forEach(node=>{const kind=node.dataset.dashboardMetric;if(kind==='records')node.textContent=`${facts.records.length}${node.textContent.includes('组')?' 组':node.textContent.includes('段')?' 段':node.textContent.includes('项')?' 项':node.textContent.includes('笔')?' 笔':''}`;else if(kind==='active')node.textContent=`${facts.active}${node.textContent.includes('条')?' 条已录':' 项'}`;else if(kind==='completion')node.textContent=`${facts.percentage}%`;else if(kind==='countdown'){const dates=facts.records.flatMap(record=>Object.values(record.values||{})).filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(String(value))).sort();if(!dates.length){node.textContent='未设置'}else{const days=Math.ceil((new Date(`${dates[0]}T00:00:00`)-new Date())/86400000);node.textContent=days>=0?`${days} 天`:'日期已过'}}});document.querySelectorAll('[data-dashboard-progress-bar]').forEach(node=>node.style.width=`${facts.percentage}%`);MODULES.forEach(module=>{const records=appState.modules[module.id].records,starterDone=activeStarterStates(module).filter(row=>['completed','correct','reviewed','prepared','calculated'].includes(row.status)).length,label=starterDone||records.length?`内置内容 ${starterDone}/${module.starter.starter_items.length}${records.length?` · 自有记录 ${records.length}`:''}`:'可直接开始练习';document.querySelectorAll(`[data-dashboard-module-status="${module.id}"]`).forEach(node=>node.textContent=label)});const latest=facts.records.sort((a,b)=>String(b.updatedAt||'').localeCompare(String(a.updatedAt||'')))[0];document.querySelectorAll('[data-dashboard-latest]').forEach(node=>node.textContent=latest?recordText(latest):facts.starterCompleted?`内置内容已完成 ${facts.starterCompleted} 项`:'还没有交付记录')}
function localDate(offset=0){const date=new Date();date.setMinutes(date.getMinutes()-date.getTimezoneOffset());date.setDate(date.getDate()+offset);return date.toISOString().slice(0,10)}
function renderTodayBoard(){const board=document.querySelector('[data-today-workboard]');if(!board)return;const today=localDate(),items=MODULES.flatMap(module=>(appState.modules[module.id].records||[]).filter(record=>!record.completed&&!record.archived&&/^\d{4}-\d{2}-\d{2}$/.test(String(record.values?.due||''))&&String(record.values.due)<=today).map(record=>({module,record}))).sort((left,right)=>String(left.record.values.due).localeCompare(String(right.record.values.due)));const summary=board.querySelector('[data-today-summary]'),root=board.querySelector('[data-today-items]');if(!items.length){summary.textContent='今天还没有排定待办；先从一个当前模块开始。';root.textContent='';return}const overdue=items.filter(item=>String(item.record.values.due)<today).length;summary.textContent=overdue?`有 ${overdue} 项逾期任务已顺延到今天，先处理最早的一项。`:`今天有 ${items.length} 项待办，完成后会留在当前设备。`;root.innerHTML=items.map(({module,record})=>{const past=String(record.values.due)<today;return `<article class="today-item ${past?'is-overdue':''}"><div><strong>${escapeHtml(recordText(record)||module.name)}</strong><small>${past?`原定 ${escapeHtml(record.values.due)} · 已顺延到今天`:'今天到期'} · ${escapeHtml(module.name)}</small></div><button type="button" class="tiny" data-today-complete data-today-module-id="${escapeHtml(module.id)}" data-today-record-id="${escapeHtml(record.id)}">完成</button></article>`}).join('')}
function renderBackupReminder(){const reminder=document.querySelector('[data-double6-hook="backup-reminder"]');if(!reminder)return;const count=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).length,0);reminder.hidden=count<30;reminder.textContent=count>=30?`已保存 ${count} 条记录，建议现在导出一份本地备份。`:''}
function renderChildParentSummary(){const summary=document.querySelector('[data-child-parent-summary]');if(!summary)return;const completed=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).filter(record=>record.completed).length,0),mistakes=MODULES.reduce((total,module)=>total+(appState.modules[module.id].starter.mistakes||[]).length,0),pending=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).filter(record=>!record.completed&&!record.archived).length,0);summary.textContent=`本机已完成 ${completed} 项；有 ${mistakes} 道待回看错题、${pending} 条未完成记录。先从一件事做小调整。`}
function normalizeAnswer(value){return String(value??'').trim().replace(/\s+/g,' ').toLowerCase()}
function d6Celebrate(root){if(!root)return;const layer=document.createElement('div');layer.className='d6-star-layer';layer.setAttribute('aria-hidden','true');for(let index=0;index<8;index+=1){const star=document.createElement('span');star.textContent='⭐';star.style.left=`${6+Math.random()*88}%`;star.style.animationDelay=`${(Math.random()*.4).toFixed(2)}s`;layer.appendChild(star)}root.appendChild(layer);setTimeout(()=>layer.remove(),1700)}
function d6Shake(root){const node=root?.querySelector('[data-starter-result]');if(node)node.classList.add('d6-shake')}
function d6Streak(days){let count=0,offset=0;for(;;){const key=localDate(-offset);if(!days[key])break;count+=1;offset+=1}return count}
function d6BadgeMet(rule,rewards){if(rule.type==='stars_earned_total')return rewards.earnedTotal>=rule.threshold;if(rule.type==='questions_correct_total')return rewards.awardedItems.length>=rule.threshold;if(rule.type==='generator_total')return rewards.generatorCorrect>=rule.threshold;if(rule.type==='streak_days')return d6Streak(rewards.days)>=rule.threshold;if(rule.type==='redeems_total')return rewards.redeemed.length>=rule.threshold;return false}
function d6EvalBadges(next){const earned=[];MODULES.forEach(module=>((module.rewards&&module.rewards.badges)||[]).forEach(badge=>{if(!next.rewards.badges.includes(badge.badge_id)&&d6BadgeMet(badge.rule,next.rewards)){next.rewards.badges.push(badge.badge_id);earned.push(badge.title)}}));return earned}
function d6EarnStar(next,itemId,kind){const rewards=next.rewards,today=localDate();let awarded=false;if(kind==='generator'){if(rewards.dailyGenerator.date!==today)rewards.dailyGenerator={date:today,count:0};rewards.generatorCorrect+=1;if(rewards.dailyGenerator.count<20){rewards.dailyGenerator.count+=1;awarded=true}}else if(!rewards.awardedItems.includes(itemId)){rewards.awardedItems.push(itemId);awarded=true}if(awarded){rewards.stars+=1;rewards.earnedTotal+=1}rewards.days[today]=true;return {awarded,newBadges:d6EvalBadges(next)}}
function d6StarMessage(earned){if(!earned)return'';const parts=[];if(earned.awarded)parts.push('获得 1 颗星星');if(earned.newBadges.length)parts.push(`解锁徽章：${earned.newBadges.join('、')}`);return parts.length?`，${parts.join('，')}`:''}
function renderStarBalance(){document.querySelectorAll('[data-reward-balance]').forEach(node=>node.textContent=`${appState.rewards?.stars??0} ⭐`)}
function renderRewards(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"] [data-reward-root]`);if(!root||!module.rewards)return;const rewards=appState.rewards,custom=(appState.modules[id].records||[]).filter(record=>!record.archived).map(record=>({item_id:record.id,title:String(record.values.title||'自定义奖励'),icon:'🎁',cost:Math.max(1,Math.floor(Number(record.values.stars))||1),custom:true})),shop=[...(module.rewards.shop||[]).map(item=>({...item,custom:false})),...custom];root.querySelector('[data-reward-shop]').innerHTML=shop.map(item=>`<article class="reward-shop-item"><span class="reward-icon" aria-hidden="true">${escapeHtml(item.icon||'🎁')}</span><strong>${escapeHtml(item.title)}</strong><small>${item.custom?'家庭自定义':'内置奖励'}</small><button type="button" class="tiny" data-reward-redeem="${escapeHtml(item.item_id)}" data-reward-cost="${item.cost}" data-reward-title="${escapeHtml(item.title)}" ${rewards.stars<item.cost?'disabled':''}>${item.cost} ⭐ 兑换</button></article>`).join('');root.querySelector('[data-reward-badges]').innerHTML=(module.rewards.badges||[]).map(badge=>{const earned=rewards.badges.includes(badge.badge_id);return `<article class="reward-badge ${earned?'is-earned':''}" data-reward-badge="${escapeHtml(badge.badge_id)}"><span aria-hidden="true">${escapeHtml(badge.icon)}</span><strong>${escapeHtml(badge.title)}</strong><small>${earned?'已点亮':escapeHtml(badge.hint)}</small></article>`}).join('');const now=new Date(),year=now.getFullYear(),month=now.getMonth(),count=new Date(year,month+1,0).getDate(),today=localDate();root.querySelector('[data-reward-calendar]').innerHTML=Array.from({length:count},(_,index)=>{const date=`${year}-${String(month+1).padStart(2,'0')}-${String(index+1).padStart(2,'0')}`;return `<span class="${rewards.days[date]?'done ':''}${date===today?'today':''}" title="${date}">${index+1}</span>`}).join('');const streak=d6Streak(rewards.days);root.querySelector('[data-reward-summary]').textContent=`累计获得 ${rewards.earnedTotal} 颗 · 连续练习 ${streak} 天`;root.querySelector('[data-reward-streak]').textContent=streak?`已连续练习 ${streak} 天，明天再来一天就更棒`:'今天完成一次练习就开始计天数';root.querySelector('[data-reward-history]').innerHTML=rewards.redeemed.length?rewards.redeemed.slice(0,5).map(entry=>`<p class="reward-history-row"><strong>${escapeHtml(entry.title)}</strong><small>${entry.cost} ⭐ · ${escapeHtml(entry.date)}</small></p>`).join(''):'<p class="reward-history-row">还没有兑换记录；星星够了就可以换。</p>'}
document.addEventListener('click',event=>{const button=event.target.closest('[data-reward-redeem]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]');if(!moduleRoot)return;const id=moduleRoot.dataset.double6ModuleId,cost=Math.floor(Number(button.dataset.rewardCost))||0,title=button.dataset.rewardTitle||'奖励';if(!(cost>0))return;if((appState.rewards?.stars??0)<cost){feedback(id,'星星还不够，再完成一些练习吧。',true);return}if(!confirm(`用 ${cost} 颗星星兑换「${title}」吗？兑换后记得和家长兑现。`))return;const next=clone(appState);next.rewards.stars-=cost;next.rewards.redeemed.unshift({title,cost,date:localDate(),at:new Date().toISOString()});const newBadges=d6EvalBadges(next);try{persist(next);appState=next;renderModule(id);renderStarBalance();feedback(id,`已兑换「${title}」，记得和家长兑现哦${newBadges.length?`；解锁徽章：${newBadges.join('、')}`:''}。`);d6Celebrate(moduleRoot)}catch(error){feedback(id,'兑换保存失败，星星未被扣减。',true)}});
function starterResult(state,item){const answer=state.answers[item.item_id];if(item.kind==='question'&&answer)return `<div class="starter-result ${answer.correct?'success':'error'}" data-starter-result><strong>${answer.correct?'回答正确':'再想一想'}</strong><p>你的答案：${escapeHtml(answer.value)}</p><p>正确答案：${escapeHtml(item.answer)}</p><p>${escapeHtml(item.explanation)}</p><small>${escapeHtml(item.knowledge_point)} · ${escapeHtml(item.difficulty)} · ${escapeHtml(item.source_label)}</small></div>`;const itemState=effectiveStarterState(item,state);return itemState?.result?`<div class="starter-result success" data-starter-result><strong>结果已留在本机</strong><p>${escapeHtml(itemState.result)}</p></div>`:''}
function keypadHtml(){return `<div class="starter-keypad-answer"><output data-keypad-display aria-live="polite" aria-label="已输入的答案"></output><div class="starter-keypad">${['1','2','3','4','5','6','7','8','9','⌫','0','清'].map(key=>`<button type="button" class="keypad-key" data-keypad-key="${key}" aria-label="${key==='⌫'?'删除一位':key==='清'?'清空输入':`数字 ${key}`}">${key}</button>`).join('')}</div></div>`}
function questionCard(item,state,index,total){const answer=state.answers[item.item_id],options=Array.isArray(item.options)?`<div class="starter-options">${item.options.map(option=>`<button type="button" class="starter-option" data-starter-option="${escapeHtml(option)}" aria-pressed="false">${escapeHtml(option)}</button>`).join('')}</div>`:(item.input_type==='number'?keypadHtml():`<label class="starter-answer"><span>输入答案</span><input data-starter-answer-input type="text" inputmode="text" autocomplete="off"></label>`),mission=item.mission?`<div class="quest-mission"><span>${escapeHtml(item.activity_label||'今日小挑战')}</span><strong>${escapeHtml(item.mission)}</strong></div>`:'',story=item.story?`<p class="quest-story">${escapeHtml(item.story)}</p>`:'',hint=item.hint?`<details class="quest-hint"><summary>要一点提示</summary><p>${escapeHtml(item.hint)}</p></details>`:'',read=item.audio_text?`<button type="button" class="secondary" data-starter-action="read-aloud">听一听</button>`:'';return `<article class="starter-card starter-question" data-starter-item-id="${escapeHtml(item.item_id)}"><div class="starter-card-meta"><span>第 ${index+1} / ${total} 题</span><span>${escapeHtml(item.difficulty)} · ${escapeHtml(item.knowledge_point)}</span></div>${mission}${story}<h4>${escapeHtml(item.prompt)}</h4>${hint}${options}<div class="starter-actions">${read}<button type="button" data-starter-action="submit-question">${answer?'重新作答':'提交答案'}</button><button type="button" class="secondary" data-starter-action="next-question">下一题</button></div>${starterResult(state,item)}</article>`}
function d6GenQuestion(params){const ops=['add','sub'];if(params.mul_max>1)ops.push('mul');if(params.div)ops.push('div');const op=ops[Math.floor(Math.random()*ops.length)],rand=max=>1+Math.floor(Math.random()*max);let a,b,answer,text;if(op==='add'){a=rand(params.add_max);b=rand(params.add_max);answer=a+b;text=`${a} + ${b} = ?`}else if(op==='sub'){a=rand(params.sub_max);b=rand(a);answer=a-b;text=`${a} − ${b} = ?`}else if(op==='mul'){a=2+Math.floor(Math.random()*(params.mul_max-1));b=2+Math.floor(Math.random()*(params.mul_max-1));answer=a*b;text=`${a} × ${b} = ?`}else{b=2+Math.floor(Math.random()*(params.mul_max-1));answer=2+Math.floor(Math.random()*(params.mul_max-1));a=b*answer;text=`${a} ÷ ${b} = ?`}return{text,answer:String(answer)}}
function d6GenNext(card){const moduleRoot=card.closest('[data-double6-module-id]'),module=moduleRoot?moduleById[moduleRoot.dataset.double6ModuleId]:null,item=module?.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId),params=item?.generator?.params||{};const q=d6GenQuestion(params);card.dataset.currentAnswer=q.answer;const node=card.querySelector('[data-generator-question]');if(node)node.textContent=q.text;const display=card.querySelector('[data-keypad-display]');if(display)display.textContent='';const submit=card.querySelector('[data-starter-action="generator-submit"]');if(submit)submit.disabled=false;const nextButton=card.querySelector('[data-starter-action="generator-next"]');if(nextButton)nextButton.textContent='换一题'}
function generatorCard(item,state){const itemState=effectiveStarterState(item,state);return `<article class="starter-card starter-generator" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">口算天天练 · 不限题量</span><h4>${escapeHtml(item.title)}</h4><p class="generator-question" data-generator-question>点「开始出题」，答完一题马上出下一题。</p>${keypadHtml()}<div class="starter-actions"><button type="button" data-starter-action="generator-next">开始出题</button><button type="button" data-starter-action="generator-submit" disabled>提交答案</button></div><p class="generator-streak" data-generator-streak aria-live="polite"></p>${itemState?.result?`<div class="starter-result success" data-starter-result><strong>练习记录</strong><p>${escapeHtml(itemState.result)}</p></div>`:''}</article>`}
function calculatorCard(item,state){const inputs=(item.inputs||[]).map((value,index)=>`<label><span>数值 ${index+1}</span><input type="number" inputmode="decimal" step="any" data-starter-calc-input value="${escapeHtml(value)}"></label>`).join('');return `<article class="starter-card starter-calculator" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">可现场修改的演算</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p><div class="starter-calculator-inputs">${inputs}</div><div class="starter-actions"><button type="button" data-starter-action="calculate">计算并保存结果</button></div>${starterResult(state,item)}</article>`}
function promptCard(item,state){const prompts=Array.isArray(item.prompts)?item.prompts:[],fallback=new Date().getDate()%Math.max(prompts.length,1),index=Number.isInteger(state.promptIndex)?state.promptIndex%Math.max(prompts.length,1):fallback,prompt=prompts[index]||item.title;return `<article class="starter-card life-prompt" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">今日灵感</span><h4>${escapeHtml(prompt)}</h4><p>这是 Double6 自编提示，不引用第三方文案。写下感想后，它会和你的随手记一起保存在当前设备。</p><div class="starter-actions"><button type="button" data-starter-action="rotate-prompt">换一条灵感</button></div>${starterResult(state,item)}</article>`}
function regularStarterCard(item,state){const itemState=effectiveStarterState(item,state),verb=item.kind==='template'?'使用这个模板':item.kind==='reference'?'标记已查看':itemState?.status==='completed'?'撤销完成':'完成这一项';return `<article class="starter-card" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">${escapeHtml(item.kind==='template'?'可编辑模板':item.kind==='reference'?'参考内容':'小任务')}</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p><div class="starter-actions"><button type="button" data-starter-action="${item.kind==='template'?'use-template':item.kind==='reference'?'review':'toggle'}">${verb}</button></div>${starterResult(state,item)}</article>`}
function referenceCard(item,state){const ref=item.reference;if(!ref||typeof ref!=='object')return regularStarterCard(item,state);let content='';if(ref.style==='poems'&&Array.isArray(ref.poems)){content=`<div class="ref-poems">${ref.poems.map((poem,index)=>{const spoken=[poem.title,...poem.lines].join('，');return `<details class="ref-poem"${index===0?' open':''}><summary><strong>${escapeHtml(poem.title)}</strong><span>${escapeHtml(poem.author||'')}</span></summary><p class="ref-poem-lines">${(poem.lines||[]).map(line=>escapeHtml(line)).join('<br>')}</p>${poem.notes?`<p class="ref-poem-note"><b>注释</b>：${escapeHtml(poem.notes)}</p>`:''}${poem.translation?`<p class="ref-poem-note"><b>译文</b>：${escapeHtml(poem.translation)}</p>`:''}<div class="starter-actions"><button type="button" class="secondary" data-ref-speak="${attrSafe(spoken)}">读一读</button></div></details>`}).join('')}</div>`}else if(Array.isArray(ref.groups)){content=ref.groups.map(group=>`<section class="ref-group"><h5>${escapeHtml(group.label||'')}</h5><div class="ref-chips">${(group.entries||[]).map(entry=>`<button type="button" class="ref-chip" data-ref-speak="${attrSafe(entry.speak||entry.text)}"><strong>${escapeHtml(entry.text)}</strong>${entry.note?`<small>${escapeHtml(entry.note)}</small>`:''}</button>`).join('')}</div></section>`).join('')}const itemState=effectiveStarterState(item,state);return `<article class="starter-card ref-card" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">参考内容 · 点一点可以听</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p>${content}<div class="starter-actions"><button type="button" data-starter-action="review">${itemState?.status==='reviewed'?'再看一遍':'标记已查看'}</button></div>${starterResult(state,item)}</article>`}
function renderStarter(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-content]`),state=appState.modules[id].starter,questions=module.starter.starter_items.filter(item=>item.kind==='question'),others=module.starter.starter_items.filter(item=>item.kind!=='question');const cards=[];if(questions.length){const mistake=state.mistakes.find(itemId=>questions.some(item=>item.item_id===itemId)),index=mistake?questions.findIndex(item=>item.item_id===mistake):state.questionIndex%questions.length;cards.push(questionCard(questions[index],state,index,questions.length))}cards.push(...others.map(item=>item.kind==='calculator'?calculatorCard(item,state):item.kind==='prompt'?promptCard(item,state):item.kind==='generator'?generatorCard(item,state):item.kind==='reference'?referenceCard(item,state):regularStarterCard(item,state)));root.innerHTML=cards.join('')}
function renderModule(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"]`),list=root.querySelector('[data-module-records]'),query=(root.querySelector('[data-module-filter]')?.value||'').toLowerCase(),records=appState.modules[id].records.filter(record=>!query||recordText(record).toLowerCase().includes(query));renderStarter(id);list.innerHTML=records.length?records.map(record=>`<article class="record ${record.completed?'is-complete':''} ${record.archived?'is-archived':''}" data-module-record data-record-id="${escapeHtml(record.id)}"><div><strong>${escapeHtml(recordText(record)||'未命名记录')}</strong><small>${record.completed?'已完成 · ':''}${record.archived?'已归档 · ':''}${escapeHtml(record.updatedAt||'')}</small></div><div class="record-actions">${actionButtons(module,record)}</div></article>`).join(''):'<p class="empty-record">还没有自己的记录；上方内置内容仍可直接使用。</p>';MODULES.forEach(row=>renderRewards(row.id));renderStarBalance();renderProgress();renderTodayBoard();renderBackupReminder();renderChildParentSummary()}
function renderLegacy(){const root=document.querySelector('[data-double6-hook="legacy-import"]');if(!appState.legacyImport){root.hidden=true;root.textContent='';return}root.hidden=false;root.textContent=`历史导入区：${appState.legacyImport.notes||'无备注'}；已完成项 ${appState.legacyImport.completedItemIds?.length||0} 个。未映射原始字段已原样保留在导出文件中。`}
__LIFE_HELPERS__
function render(){MODULES.forEach(row=>renderModule(row.id));renderLegacy();renderProgress();renderTodayBoard();renderBackupReminder();renderChildParentSummary();renderStarBalance();__LIFE_RENDER__}
__LIFE_LISTENERS__
function resetForm(root){const form=root.querySelector('[data-module-form]');form.reset();delete form.dataset.editing;root.querySelector('[data-module-cancel]').hidden=true}
function activateView(hash,{replace=false}={}){const requested=(hash||location.hash||'#dashboard').slice(1),target=document.querySelector(`[data-view-id="${CSS.escape(requested)}"]`),view=target||document.querySelector('[data-view-id="dashboard"]'),viewId=view.dataset.viewId;document.querySelectorAll('[data-view-id]').forEach(node=>{const active=node===view;node.hidden=!active;node.classList.toggle('is-active',active)});document.querySelectorAll('[data-nav-view]').forEach(node=>{const active=node.dataset.navView===viewId;node.classList.toggle('active',active);if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current')});if(!target&&replace)history.replaceState(null,'','#dashboard');window.scrollTo({top:0,behavior:'instant'})}
window.addEventListener('hashchange',()=>activateView(location.hash));
document.querySelectorAll('[data-double6-module-id]').forEach(root=>{const id=root.dataset.double6ModuleId,module=moduleById[id],form=root.querySelector('[data-module-form]');form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const values={};module.fields.forEach(field=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);values[field.field_id]=field.type==='boolean'?input.checked:input.value});const next=clone(appState),stamp=new Date().toISOString(),editing=form.dataset.editing;let record;if(editing){record=next.modules[id].records.find(row=>row.id===editing);record.values=values;record.updatedAt=stamp}else{record={id:`r-${Date.now()}-${Math.random().toString(16).slice(2)}`,values,completed:false,archived:false,createdAt:stamp,updatedAt:stamp};next.modules[id].records.unshift(record)}try{persist(next);appState=next;resetForm(root);renderModule(id);feedback(id,'已保存到当前设备。')}catch(error){feedback(id,'保存失败，输入仍保留，请重试或先导出。',true)}});root.querySelector('[data-module-cancel]').addEventListener('click',()=>resetForm(root));root.querySelector('[data-module-filter]')?.addEventListener('input',()=>renderModule(id));root.querySelector('[data-module-records]').addEventListener('click',event=>{const button=event.target.closest('[data-record-action]');if(!button)return;const article=button.closest('[data-module-record]'),next=clone(appState),records=next.modules[id].records,index=records.findIndex(row=>row.id===article.dataset.recordId),record=records[index];if(!record)return;const action=button.dataset.recordAction;if(action==='delete'){if(!confirm('确定删除这条记录吗？此操作不能自动撤销。'))return;records.splice(index,1)}else if(action==='toggle-complete'){record.completed=!record.completed;record.updatedAt=new Date().toISOString()}else if(action==='toggle-archive'){record.archived=!record.archived;record.updatedAt=new Date().toISOString()}else if(action==='move'){const options=module.fields.find(row=>row.field_id==='stage')?.options||[];record.values.stage=options[(options.indexOf(record.values.stage)+1)%options.length];record.updatedAt=new Date().toISOString()}else if(action==='edit'){module.fields.forEach(field=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);if(field.type==='boolean')input.checked=Boolean(record.values[field.field_id]);else input.value=record.values[field.field_id]??''});form.dataset.editing=record.id;root.querySelector('[data-module-cancel]').hidden=false;form.scrollIntoView({behavior:'smooth'});return}try{persist(next);appState=next;renderModule(id);feedback(id,'修改已保存。')}catch(error){feedback(id,'修改失败，原记录仍保留。',true)}})});
document.addEventListener('click',event=>{const button=event.target.closest('[data-today-complete]');if(!button)return;const id=button.dataset.todayModuleId,recordId=button.dataset.todayRecordId,record=appState.modules[id]?.records?.find(row=>row.id===recordId);if(!record)return;const next=clone(appState),target=next.modules[id].records.find(row=>row.id===recordId);target.completed=true;target.updatedAt=new Date().toISOString();try{persist(next);appState=next;render();feedback(id,'已完成；今天的列表已更新。')}catch(error){dataFeedback('完成状态保存失败，原记录未被替换。',true)}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-child-mode]');if(!button)return;const parent=button.dataset.childMode==='parent';document.querySelectorAll('.child-view-child').forEach(node=>node.hidden=parent);document.querySelectorAll('.child-view-parent').forEach(node=>node.hidden=!parent);document.querySelectorAll('[data-child-mode]').forEach(node=>node.classList.toggle('active',node===button));renderChildParentSummary()});
function calculatedResult(operation,values){if(!values.length||values.some(value=>!Number.isFinite(value)))throw new Error('请填写有效数字');const first=values[0],second=values[1]||0,round=value=>Math.round(value*100)/100;if(operation==='sum')return `合计 ${round(values.reduce((sum,value)=>sum+value,0))}`;if(operation==='difference')return `结果 ${round(first-second)}`;if(operation==='percent')return second===0?'分母不能为 0':`比例 ${round(first/second*100)}%`;if(operation==='markup')return `建议值 ${round(first*1.3)}`;if(operation==='profit_margin'){const profit=round(first-second),rate=first===0?0:round(profit/first*100);return `毛利 ${profit}，毛利率 ${rate}%`}if(operation==='tax_add'){const tax=round(first*second/100);return `税额 ${tax}，含税 ${round(first+tax)}`}if(operation==='time_cost')return `时间成本 ${round(first/60*second)}`;throw new Error('此演算类型未登记')}
function saveStarter(id,next,message,error=false){try{persist(next);appState=next;renderModule(id);const node=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-feedback]`);node.textContent=message;node.className=`feedback ${error?'error':'success'}`}catch(saveError){const node=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-feedback]`);node.textContent='结果保存失败，请先导出备份后重试。';node.className='feedback error'}}
document.addEventListener('click',event=>{const keypadKey=event.target.closest('[data-keypad-key]');if(keypadKey){const wrap=keypadKey.closest('.starter-keypad-answer'),display=wrap?.querySelector('[data-keypad-display]');if(!display)return;const key=keypadKey.dataset.keypadKey;if(key==='清')display.textContent='';else if(key==='⌫')display.textContent=display.textContent.slice(0,-1);else if(display.textContent.length<9)display.textContent+=key;return}const speakChip=event.target.closest('[data-ref-speak]');if(speakChip){if(!d6Speak(speakChip.getAttribute('data-ref-speak')||speakChip.textContent)){const speakRoot=speakChip.closest('[data-double6-module-id]'),speakNode=speakRoot?.querySelector('[data-starter-feedback]');if(speakNode){speakNode.textContent='当前浏览器不支持朗读；可以请家长一起读一读。';speakNode.className='feedback error'}}return}const option=event.target.closest('[data-starter-option]');if(option){const card=option.closest('[data-starter-item-id]');card.querySelectorAll('[data-starter-option]').forEach(node=>{const selected=node===option;node.classList.toggle('is-selected',selected);node.setAttribute('aria-pressed',String(selected))});return}const button=event.target.closest('[data-starter-action]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]'),card=button.closest('[data-starter-item-id]');if(!moduleRoot||!card)return;const id=moduleRoot.dataset.double6ModuleId,module=moduleById[id],item=module.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId);if(!item)return;const action=button.dataset.starterAction;if(action==='read-aloud'){const text=String(item.audio_text||item.prompt||'');if(!text||!('speechSynthesis' in window)){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent='当前浏览器不支持朗读；可以请家长一起读一读。';node.className='feedback error';return}window.speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.lang=/[A-Za-z]/.test(text)&&!/[\u4e00-\u9fff]/.test(text)?'en-US':'zh-CN';utterance.rate=.85;window.speechSynthesis.speak(utterance);const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent='正在朗读；不同设备的声音会略有差异。';node.className='feedback success';return}const next=clone(appState),state=next.modules[id].starter,stamp=new Date().toISOString();if(action==='submit-question'){const selected=card.querySelector('[data-starter-option][aria-pressed="true"]'),display=card.querySelector('[data-keypad-display]'),input=card.querySelector('[data-starter-answer-input]'),value=selected?.dataset.starterOption??(display?display.textContent:input?.value)??'';if(!String(value).trim()){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent='先选择或输入一个答案。';node.className='feedback error';return}const correct=normalizeAnswer(value)===normalizeAnswer(item.answer);state.answers[item.item_id]={value:String(value),correct,updatedAt:stamp};state.itemStates[item.item_id]={status:correct?'correct':'incorrect',result:correct?'回答正确，解析已展开。':'已加入错题回看，解析已展开。',updatedAt:stamp};state.mistakes=correct?state.mistakes.filter(row=>row!==item.item_id):[...new Set([...state.mistakes,item.item_id])];state.lastResult={itemId:item.item_id,message:correct?'回答正确':'回答错误',updatedAt:stamp};const earned=correct?d6EarnStar(next,item.item_id,'question'):null;saveStarter(id,next,(correct?'太棒了，答案、解析和这次完成记录都已保存在当前设备。':'先看解析；这道题已进入错题回看，下一次可以换个办法再战。')+d6StarMessage(earned),!correct);const freshRoot=document.querySelector(`[data-double6-module-id="${id}"]`);if(correct)d6Celebrate(freshRoot);else d6Shake(freshRoot);return}if(action==='next-question'){const questions=module.starter.starter_items.filter(row=>row.kind==='question');state.questionIndex=questions.length?(state.questionIndex+1)%questions.length:0;saveStarter(id,next,'已切到下一张挑战卡，可刷新后继续。');return}if(action==='generator-next'){d6GenNext(card);return}if(action==='generator-submit'){const display=card.querySelector('[data-keypad-display]'),value=(display?.textContent||'').trim(),node=moduleRoot.querySelector('[data-starter-feedback]');if(!card.dataset.currentAnswer){node.textContent='先点「开始出题」。';node.className='feedback error';return}if(!value){node.textContent='先用小键盘输入答案。';node.className='feedback error';return}const correct=normalizeAnswer(value)===normalizeAnswer(card.dataset.currentAnswer),streak=correct?Number(card.dataset.streak||'0')+1:0;card.dataset.streak=String(streak);const streakEl=card.querySelector('[data-generator-streak]');if(streakEl)streakEl.textContent=correct?`本次连对 ${streak} 题`:'';if(correct){const prev=state.itemStates[item.item_id]?.result||'',match=prev.match(/累计完成 (\d+) 题 · 最佳连对 (\d+)/),total=(match?Number(match[1]):0)+1,best=Math.max(match?Number(match[2]):0,streak);state.itemStates[item.item_id]={status:'practiced',result:`累计完成 ${total} 题 · 最佳连对 ${best}`,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:'口算答对',updatedAt:stamp};const earned=d6EarnStar(next,item.item_id,'generator');saveStarter(id,next,`答对了！本次连对 ${streak} 题${d6StarMessage(earned)}。`);const freshRoot=document.querySelector(`[data-double6-module-id="${id}"]`);d6Celebrate(freshRoot);const freshCard=freshRoot?.querySelector(`[data-starter-item-id="${item.item_id}"]`);if(freshCard)freshCard.dataset.streak=String(streak);setTimeout(()=>{const current=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-item-id="${item.item_id}"]`);if(current)d6GenNext(current)},600);return}node.textContent=`再想一想，正确答案是 ${card.dataset.currentAnswer}；已帮你换下一题。`;node.className='feedback error';card.classList.add('d6-shake');setTimeout(()=>card.classList.remove('d6-shake'),500);setTimeout(()=>d6GenNext(card),900);return}if(action==='calculate'){try{const values=[...card.querySelectorAll('[data-starter-calc-input]')].map(node=>Number(node.value)),result=calculatedResult(item.calculation,values);state.itemStates[item.item_id]={status:'calculated',result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:result,updatedAt:stamp};saveStarter(id,next,`${result}；仅为本地演算，请按页面边界人工复核。`)}catch(error){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent=error.message;node.className='feedback error'}return}if(action==='use-template'){const form=moduleRoot.querySelector('[data-module-form]'),editable=module.fields.filter(field=>field.type!=='boolean');editable.forEach((field,index)=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);if(!input)return;const value=index===0?item.title:index===1?(item.body||item.result||''):'';if(value)input.value=value});state.itemStates[item.item_id]={status:'prepared',result:item.result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:item.result,updatedAt:stamp};saveStarter(id,next,'模板已填入下方表单；检查并点击“保存记录”即可。');moduleRoot.querySelector('[data-module-form]').scrollIntoView({behavior:'smooth',block:'center'});return}if(action==='review'){state.itemStates[item.item_id]={status:'reviewed',result:item.result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:item.result,updatedAt:stamp};saveStarter(id,next,'已标记查看，结果保存在当前设备。');return}if(action==='toggle'){const completed=effectiveStarterState(item,state)?.status==='completed';state.itemStates[item.item_id]={status:completed?'ready':'completed',result:completed?'已撤销完成':item.result,updatedAt:stamp,...(item.recurrence==='weekly'?{cycleKey:currentWeekKey()}:{})};state.lastResult={itemId:item.item_id,message:completed?'已撤销完成':item.result,updatedAt:stamp};const earned=completed?null:d6EarnStar(next,item.item_id,'action');saveStarter(id,next,(completed?'已撤销，可再次完成。':'已完成，结果保存在当前设备。')+d6StarMessage(earned))}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-starter-action="rotate-prompt"]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]'),card=button.closest('[data-starter-item-id]');if(!moduleRoot||!card)return;const id=moduleRoot.dataset.double6ModuleId,module=moduleById[id],item=module.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId),prompts=Array.isArray(item?.prompts)?item.prompts:[];if(!prompts.length)return;const next=clone(appState),state=next.modules[id].starter,stamp=new Date().toISOString();state.promptIndex=((Number.isInteger(state.promptIndex)?state.promptIndex:new Date().getDate()%prompts.length)+1)%prompts.length;state.itemStates[item.item_id]={status:'rotated',result:'已保存今天选择的灵感。',updatedAt:stamp};saveStarter(id,next,'已换一条；写下感想后保存到下方随手记。')});
__LIFE_MOVEMENT__
function downloadState(){const blob=new Blob([JSON.stringify(appState,null,2)],{type:'application/json'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${PRODUCT_ID}-backup-v3.json`;link.click();URL.revokeObjectURL(link.href)}
function downloadFinanceCsv(){const rows=FINANCE_MODULE_IDS.flatMap(id=>(appState.modules[id]?.records||[]).map(record=>({module:moduleById[id].name,...record.values,completed:record.completed?'是':'否',updated_at:record.updatedAt||''})));const headers=['module','entry_type','amount','category','date','notes','completed','updated_at'],quote=value=>`"${String(value??'').replaceAll('"','""')}"`,csv=['\ufeff'+headers.join(','),...rows.map(row=>headers.map(key=>quote(row[key])).join(','))].join('\n'),blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${PRODUCT_ID}-finance.csv`;link.click();URL.revokeObjectURL(link.href)}
document.querySelector('[data-double6-hook="clear"]').addEventListener('click',()=>{if(!confirm('确定清空当前工作台的全部本地数据吗？建议先导出备份。'))return;const next=emptyState();try{localStorage.removeItem(STORAGE_KEY);appState=next;lastImportBackup=null;document.querySelector('[data-double6-hook="undo-import"]').hidden=true;document.querySelectorAll('[data-module-form]').forEach(form=>form.reset());render();dataFeedback('本地数据已清空。')}catch(error){dataFeedback('清空失败，本地数据未改动。',true)}});
document.querySelectorAll('[data-double6-hook="export"],[data-double6-hook="quick-export"]').forEach(button=>button.addEventListener('click',()=>{downloadState();dataFeedback('备份文件已生成。')}));
document.querySelector('[data-double6-hook="export-csv"]')?.addEventListener('click',()=>{downloadFinanceCsv();dataFeedback('财务 CSV 已生成；只包含当前设备里已保存的流水。')});
document.querySelector('[data-double6-hook="undo-import"]').addEventListener('click',event=>{if(!lastImportBackup)return;try{persist(lastImportBackup);appState=lastImportBackup;lastImportBackup=null;event.currentTarget.hidden=true;render();dataFeedback('已撤销最近一次导入。')}catch(error){dataFeedback('撤销导入失败，当前数据未改动。',true)}});
function importBackup(event){const file=event.target.files[0];if(!file)return;if(file.size>MAX_IMPORT_BYTES){dataFeedback('导入失败：备份文件不能超过 2 MB。',true);event.target.value='';return}const reader=new FileReader();reader.onload=()=>{try{let parsed;try{parsed=JSON.parse(String(reader.result||''))}catch(error){parsed={value:String(reader.result||''),checked:[]}}const next=normalize(parsed);if(!confirm('导入会覆盖当前工作台数据，是否继续？')){dataFeedback('已取消导入，当前数据未改动。');event.target.value='';return}lastImportBackup=clone(appState);persist(next);appState=next;render();document.querySelector('[data-double6-hook="undo-import"]').hidden=false;dataFeedback('导入完成；可立即撤销，未映射字段会保留在导出文件中。')}catch(error){dataFeedback(`导入失败，现有数据未改动：${error.message||'格式无效'}`,true)}finally{event.target.value=''}};reader.onerror=()=>dataFeedback('导入失败：无法读取文件。',true);reader.readAsText(file)}
document.querySelectorAll('[data-double6-hook="import"],[data-double6-hook="quick-import"]').forEach(input=>input.addEventListener('change',importBackup));
try{const raw=localStorage.getItem(STORAGE_KEY);if(raw)appState=normalize(JSON.parse(raw));render()}catch(error){render();feedback(MODULES[0].id,'恢复失败，可以导入备份重试。',true)}activateView(location.hash,{replace:true});
"""
    has_life_modules = any(str(row["id"]).startswith("life-") for row in modules)
    return (source.replace("__STORAGE_KEY__", _safe_script_json(storage_key))
            .replace("__PRODUCT_ID__", _safe_script_json(product["product_id"]))
            .replace("__PACK_ID__", _safe_script_json(product["recommendation_plan"]["pack_id"]))
            .replace("__MODULES__", _safe_script_json(modules))
            .replace("__FINANCE_MODULE_IDS__", _safe_script_json(finance_module_ids))
            .replace("__LIFE_HELPERS__", _LIFE_HELPERS if has_life_modules else "")
            .replace("__LIFE_RENDER__", "renderLifeDashboard();renderLifeGoals()" if has_life_modules else "")
            .replace("__LIFE_LISTENERS__", _LIFE_LISTENERS if has_life_modules else "")
            .replace("__LIFE_MOVEMENT__", _LIFE_MOVEMENT if has_life_modules else ""))


def _html(product: dict[str, Any], design: dict[str, Any], token: dict[str, Any], template: dict[str, Any], build_id: str, storage_key: str) -> str:
    primary_id = product["design_brief"]["primary_capability_id"]
    feature_by_module = {
        row["module_id"]: row
        for row in product.get("learning_design", {}).get("feature_cards", [])
        if isinstance(row, dict) and row.get("module_id")
    }
    extensions_by_module: dict[str, list[dict[str, Any]]] = {}
    weekday_labels = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
    for extension in product.get("module_extensions", []):
        extensions_by_module.setdefault(str(extension["module_id"]), []).append(extension)
    in_page = []
    for source in product["capabilities"]:
        if source["mode"] != "in_page":
            continue
        row = deepcopy(source)
        module_id = str(row["recommendation_module_id"])
        if module_id in feature_by_module:
            row["learning_feature"] = deepcopy(feature_by_module[module_id])
        for extension in extensions_by_module.get(module_id, []):
            days = "、".join(weekday_labels[day] for day in extension["weekdays"])
            row["starter"]["starter_items"].append({
                "kind": "action", "item_id": f"user-{extension['extension_id']}",
                "title": extension["title"], "body": f"每周 {days}；由用户在产品确认前提出。",
                "result": extension["result"], "source_label": extension["source_label"],
                "recurrence": "weekly", "weekdays": extension["weekdays"],
            })
        in_page.append(row)
    capabilities = sorted(in_page, key=lambda row: row["capability_id"] != primary_id)
    experience, palette = design["experience"], template["palette"]
    scene_template_id = design["current"].get("scene_template_id") or "general_workbench"
    emojis = _emojis([str(row["name"]) for row in capabilities], {template["motif"]})
    rendered = render_scene(
        product, design, capabilities, template,
        {"detail_renderer": _surface_section, "emojis": emojis},
    )
    if rendered["renderer_id"] != design["current"]["renderer_id"]:
        raise ContractError("renderer 输出与 design 锁不一致")
    dashboard_slots = set()
    for slot in FIRST_SCREEN_SLOTS:
        if f"data-first-screen-slot='{slot}'" in rendered["dashboard_html"]:
            dashboard_slots.add(slot)
    if dashboard_slots != FIRST_SCREEN_SLOTS:
        raise ContractError(f"renderer 首屏槽位不完整：{sorted(FIRST_SCREEN_SLOTS - dashboard_slots)}")
    nav_html = "".join(
        f"<a class='nav-item{' active' if index == 0 else ''}' href='#{_e(item['view_id'])}' data-nav-view='{_e(item['view_id'])}' aria-label='{_e(item['label'])}'>"
        f"{_navigation_emoji(item)}<span class='nav-label'>{_e(item.get('nav_label', item['label']))}</span></a>"
        for index, item in enumerate(rendered["nav_items"])
    )
    boundaries = "".join(f"<li>{_e(row['reason'])}</li>" for row in product["boundaries"])
    script = _script(product, capabilities, storage_key)
    has_finance_csv = any(
        {"entry_type", "amount"} <= {field["field_id"] for field in row["surface"]["fields"]}
        for row in capabilities
    )
    finance_csv_control = "<button class='secondary' data-double6-hook='export-csv'>导出财务 CSV</button>" if has_finance_csv else ""
    icons = _icon_set_for(product, template["template_id"])
    page_icon = f"data:image/png;base64,{icons['64x64:favicon']}"
    pwa_head = _pwa_head(product, palette, icons)
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='{_e(palette['primary'])}'><link rel='icon' type='image/png' href='{page_icon}'><link rel='shortcut icon' type='image/png' href='{page_icon}'>{pwa_head}<title>{_e(product['title'])}</title><style>
:root{{--d6-canvas:{palette['canvas']};--d6-sidebar:{palette['sidebar']};--d6-card:{palette['card']};--d6-ink:{palette['ink']};--d6-muted:{palette['muted']};--d6-line:{palette['line']};--d6-primary:{palette['primary']};--d6-primary-strong:{palette['primary_strong']};--d6-accent:{palette['accent']};--d6-category-1:{palette['category_1']};--d6-category-2:{palette['category_2']};--d6-category-3:{palette['category_3']};--d6-category-4:{palette['category_4']};--d6-success:{token['success']};--d6-error:{token['error']}}}
	*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--d6-canvas);color:var(--d6-ink);font:16px/1.5 {token['font']},sans-serif}}button,input,textarea,select{{font:inherit}}input,textarea,select{{font-size:16px}}button,input[type=file],a{{min-height:44px}}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,a:focus-visible{{outline:3px solid var(--d6-accent);outline-offset:2px}}a{{color:inherit;text-decoration:none}}button{{border:0;border-radius:14px;padding:11px 16px;background:var(--d6-primary);color:#fff;font-weight:850;cursor:pointer}}button.secondary,button.tiny,.today-import{{background:transparent;color:var(--d6-ink);border:1px solid var(--d6-line);box-shadow:none}}button.tiny{{min-height:36px;padding:6px 9px;font-size:.82rem}}button.danger{{color:var(--d6-error)}}h1{{font-size:clamp(1.375rem,2vw,1.5625rem);line-height:1.2;margin:.3em 0;max-width:22ch;letter-spacing:-.02em}}h2{{font-size:clamp(1.35rem,3vw,1.9rem);margin:0}}p{{margin:.35rem 0;max-width:66ch}}small{{color:var(--d6-muted)}}
	.app{{max-width:1460px;margin:auto;padding:12px 12px 12px 96px;display:grid;gap:16px}}.mobile-brand,.brand{{display:flex;gap:10px;align-items:center;font-weight:900}}.mobile-brand{{font-size:.875rem}}.brand-mark{{width:42px;height:42px;display:grid;place-items:center;border-radius:14px;background:var(--d6-primary);font-size:24px}}.identity-nav{{display:none}}.app-view{{grid-column:1/-1}}.app-view[hidden]{{display:none!important}}.dashboard-view{{display:grid;gap:16px}}.scene-hero{{position:relative;overflow:hidden;min-height:240px;display:flex;align-items:center;padding:clamp(26px,5vw,54px);border-radius:30px;background:linear-gradient(120deg,{palette['hero_gradient'][0]},{palette['hero_gradient'][1]});color:#fff}}.scene-hero>div{{position:relative;z-index:1;display:grid;justify-items:start;gap:8px}}.hero-kicker{{font-weight:900}}.scene-hero p{{font-size:1.02rem}}.hero-motif{{position:absolute;right:5%;top:4%;font-size:clamp(92px,17vw,180px);opacity:.2}}.primary-cta{{display:inline-flex;align-items:center;margin-top:8px;padding:12px 18px;border-radius:14px;background:#fff;color:var(--d6-primary-strong);font-weight:900}}.hero-progress{{font-size:.84rem;opacity:.95}}.eyebrow{{font-size:.8rem;font-weight:900;color:var(--d6-primary-strong)}}.dashboard-panel,.workspace,.data-tools,.child-support>section,.creator-lower>section,.lesson-side>section,.delivery-grid>section,.booking-strip,.reconcile-note,.household-columns>section,.recovery-panel,.generic-support{{padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-radius:24px;background:var(--d6-card);box-shadow:0 10px 28px color-mix(in srgb,var(--d6-ink) 8%,transparent)}}.panel-heading{{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:16px}}.text-link{{display:inline-flex;align-items:center;margin-top:12px;font-weight:900;color:var(--d6-primary-strong)}}.today-workboard{{display:grid;gap:12px;border-top:6px solid var(--d6-accent)}}.today-workboard h2{{font-size:1.2rem}}.today-items{{display:grid;gap:8px}}.today-item{{display:grid;grid-template-columns:1fr auto;align-items:center;gap:10px;padding:12px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}}.today-item.is-overdue{{border-color:var(--d6-error);background:color-mix(in srgb,var(--d6-error) 8%,var(--d6-card))}}.today-item small{{display:block}}.today-actions{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}.today-import{{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:11px 16px;border-radius:14px;font-weight:850;cursor:pointer}}.backup-reminder{{padding:9px 12px;border-radius:12px;background:var(--d6-category-2);font-weight:800}}
	.child-layout,.creator-lower,.lesson-grid,.close-grid,.fitness-layout{{display:grid;gap:16px}}.child-greeting{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:4px 4px}}.child-greeting h2{{font-size:clamp(1.25rem,2vw,1.5rem)}}.child-mode-switch{{display:flex;gap:7px;flex-wrap:wrap}}.child-mode-switch button.active{{background:var(--d6-primary);color:#fff;border-color:var(--d6-primary)}}.child-parent-review{{display:grid;gap:12px}}.child-parent-boundary{{padding:12px;border-radius:14px;background:var(--d6-category-2)}}.child-dashboard .scene-hero{{min-height:176px}}.child-dashboard .scene-hero h1{{max-width:22ch}}.learning-task-grid{{display:grid;gap:10px}}.learning-task{{display:grid;grid-template-columns:34px 46px 1fr;align-items:center;gap:10px;min-height:82px;padding:12px;border-radius:19px;background:var(--d6-category-1)}}.learning-task:nth-child(2){{background:var(--d6-category-2)}}.learning-task:nth-child(3){{background:var(--d6-category-3)}}.learning-task:nth-child(4){{background:var(--d6-category-4)}}.learning-task small{{grid-column:3}}.task-number{{font-weight:950;opacity:.55}}.task-icon,.capability-emoji{{width:46px;height:46px;display:grid;place-items:center;border-radius:14px;background:#fff;font-size:24px}}.child-support,.lesson-side{{display:grid;gap:12px}}.reward-card strong,.metric-card strong,.countdown-card strong{{display:block;font-size:2rem}}.progress-track{{height:10px;margin:12px 0;border-radius:99px;background:var(--d6-line);overflow:hidden}}.progress-track i{{display:block;width:0;height:100%;background:var(--d6-accent)}}.mini-action-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px}}.mini-action-grid span,.mini-action-grid .mini-action{{display:grid;place-items:center;min-height:58px;padding:8px;border-radius:14px;background:var(--d6-category-2);font-size:.82rem;font-weight:850;text-align:center}}.mini-action-grid span:nth-child(2),.mini-action-grid .mini-action:nth-child(2){{background:var(--d6-category-3)}}.mini-action-grid span:nth-child(3),.mini-action-grid .mini-action:nth-child(3){{background:var(--d6-category-1)}}.mini-action-grid span:nth-child(4),.mini-action-grid .mini-action:nth-child(4){{background:var(--d6-category-4)}}.reward-box{{background:var(--d6-primary)!important;color:#fff}}.reward-box p{{font-size:.82rem}}
.production-board{{border-top:6px solid var(--d6-primary)}}.pipeline{{display:grid;gap:12px}}.pipeline-stage{{display:grid;grid-template-columns:44px 1fr;align-items:center;gap:8px;padding:16px;border-bottom:1px solid var(--d6-line)}}.pipeline-stage>span{{grid-row:1/3;width:40px;height:40px;display:grid;place-items:center;border-radius:50%;background:var(--d6-primary);color:#fff;font-weight:900}}.pipeline-stage small{{grid-column:2}}.publish-reminder{{background:var(--d6-sidebar)!important}}.publish-reminder strong{{display:block;font-size:1.35rem}}.lesson-timeline ol,.circuit,.route-line{{list-style:none;padding:0;margin:0;display:grid;gap:9px}}.lesson-timeline li,.circuit li,.route-line li{{display:grid;grid-template-columns:54px 1fr;gap:12px;padding:13px;border-radius:15px;background:var(--d6-canvas)}}.lesson-timeline li>span,.circuit li>span,.route-line li>span{{font-weight:950;color:var(--d6-primary)}}.milestone-rail{{background:var(--d6-sidebar)}}.rail{{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}}.rail span{{padding:11px 4px;text-align:center;border-top:4px solid var(--d6-line);font-weight:850}}.rail .done{{border-color:var(--d6-primary)}}.delivery-grid,.booking-strip,.household-columns{{display:grid;gap:12px}}.delivery-grid strong,.booking-strip strong,.household-columns strong{{display:block;font-size:1.18rem}}
.travel-overview{{display:grid;gap:16px}}.countdown-card{{padding:24px;border-radius:24px;background:var(--d6-primary);color:#fff}}.countdown-card small{{color:#fff;opacity:.85}}.booking-strip>div{{padding:10px;border-bottom:1px solid var(--d6-line)}}.finance-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.metric-card{{padding:16px;border-radius:18px;background:var(--d6-sidebar)}}.ledger-lines{{display:grid;gap:8px}}.ledger-lines>div{{display:flex;justify-content:space-between;gap:12px;padding:12px;border-bottom:1px solid var(--d6-line)}}.status-pill{{padding:5px 9px;border-radius:99px;background:var(--d6-category-4);font-size:.78rem;font-weight:900}}.week-grid{{display:grid;grid-template-columns:repeat(7,minmax(64px,1fr));gap:7px;overflow:auto;padding-bottom:4px}}.day-cell{{display:grid;gap:12px;min-height:92px;padding:10px;border:1px solid var(--d6-line);border-radius:14px}}.day-cell.today{{background:var(--d6-primary);color:#fff}}.week-bars{{display:flex;align-items:end;gap:7px;height:72px;margin:16px 0}}.week-bars i{{flex:1;height:16%;border-radius:8px 8px 2px 2px;background:var(--d6-primary)}}.week-bars i:nth-child(2),.week-bars i:nth-child(5){{height:55%}}.week-bars i:nth-child(4){{height:85%}}.generic-card-grid{{display:grid;gap:10px}}.generic-work-card{{display:grid;grid-template-columns:46px 1fr;gap:10px;padding:14px;border:1px solid var(--d6-line);border-radius:16px}}
.life-metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}.life-card-grid{{display:grid;gap:10px}}.life-today-card{{display:grid;grid-template-columns:42px 1fr;gap:10px;padding:14px;border:1px solid var(--d6-line);border-left:6px solid var(--d6-category-1);border-radius:17px;background:var(--d6-card)}}.life-today-card:nth-child(2n){{border-left-color:var(--d6-category-3)}}.life-today-card>span{{font-size:1.65rem}}.life-today-card small{{display:block;margin-top:3px}}.life-support{{padding:20px;border-radius:24px;background:var(--d6-sidebar)}}.life-calendar{{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin:13px 0}}.life-calendar span{{display:grid;place-items:center;min-height:34px;border-radius:10px;background:var(--d6-card);font-size:.8rem;font-weight:800}}.life-calendar span.done{{background:var(--d6-primary);color:#fff}}.life-calendar span.today{{outline:2px solid var(--d6-accent);outline-offset:1px}}
	.learning-feature{{display:grid;gap:9px;padding:18px;border-radius:20px;background:var(--d6-category-2)}}.learning-feature h3{{margin:0;font-size:1.1rem}}.learning-feature ul{{display:flex;flex-wrap:wrap;gap:7px;margin:0;padding:0;list-style:none}}.learning-feature li{{padding:6px 10px;border-radius:999px;background:var(--d6-card);font-size:.82rem;font-weight:850}}.starter-surface{{display:grid;gap:14px;padding:clamp(16px,3vw,24px);border:2px solid color-mix(in srgb,var(--d6-primary) 35%,var(--d6-line));border-radius:22px;background:color-mix(in srgb,var(--d6-sidebar) 72%,var(--d6-card))}}.starter-heading{{display:flex;justify-content:space-between;align-items:start;gap:12px}}.starter-heading h3{{margin:.25rem 0;font-size:1.15rem}}.starter-content{{display:grid;gap:12px}}.starter-card{{display:grid;gap:11px;padding:16px;border:1px solid var(--d6-line);border-radius:18px;background:var(--d6-card)}}.starter-card h4{{margin:0;font-size:1.12rem}}.starter-kind,.starter-card-meta{{font-size:.78rem;font-weight:900;color:var(--d6-primary-strong)}}.starter-card-meta{{display:flex;justify-content:space-between;gap:10px}}.quest-mission{{display:grid;gap:3px;padding:11px 13px;border-radius:14px;background:var(--d6-category-1);border:1px dashed color-mix(in srgb,var(--d6-primary) 50%,var(--d6-line))}}.quest-mission span{{font-size:.74rem;font-weight:900;color:var(--d6-primary-strong)}}.quest-mission strong{{font-size:.95rem}}.quest-story{{padding-left:12px;border-left:3px solid var(--d6-accent);color:var(--d6-muted);font-size:.92rem}}.quest-hint{{padding:9px 11px;border-radius:12px;background:var(--d6-category-2)}}.quest-hint summary{{cursor:pointer;font-weight:850}}.quest-hint p{{margin-top:7px}}.starter-options{{display:grid;gap:9px}}.starter-option{{width:100%;min-height:48px;text-align:left;background:var(--d6-canvas);color:var(--d6-ink);border:2px solid var(--d6-line)}}.starter-option.is-selected{{border-color:var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 12%,var(--d6-card))}}.starter-answer,.starter-calculator-inputs{{display:grid;gap:8px}}.starter-calculator-inputs label{{display:grid;gap:5px;font-weight:800}}.starter-actions{{display:flex;gap:9px;flex-wrap:wrap}}.starter-actions button{{min-height:48px}}.starter-result{{padding:13px;border-left:5px solid currentColor;border-radius:12px;background:var(--d6-canvas)}}.starter-result p{{max-width:none}}.starter-keypad-answer{{display:grid;gap:9px}}[data-keypad-display]{{display:block;min-height:52px;padding:10px 14px;border:2px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);font-size:1.5rem;font-weight:900;text-align:center;letter-spacing:.08em}}.starter-keypad{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:340px}}.keypad-key{{min-height:52px;border-radius:14px;border:2px solid var(--d6-line);background:var(--d6-card);font-size:1.25rem;font-weight:900;color:var(--d6-ink)}}.keypad-key:active{{background:color-mix(in srgb,var(--d6-primary) 18%,var(--d6-card));transform:scale(.96)}}.generator-question{{margin:0;padding:12px;border-radius:14px;background:var(--d6-canvas);font-size:1.35rem;font-weight:900;text-align:center}}.generator-streak{{margin:0;font-weight:850;color:var(--d6-primary-strong);text-align:center}}.reward-economy{{display:grid;gap:16px;padding:clamp(16px,3vw,24px);border:2px solid color-mix(in srgb,var(--d6-accent) 45%,var(--d6-line));border-radius:22px;background:color-mix(in srgb,var(--d6-card) 80%,var(--d6-category-3))}}.reward-balance-card{{display:grid;gap:4px;padding:16px;border-radius:18px;background:var(--d6-card);text-align:center}}.reward-balance-card strong{{font-size:2.1rem;font-weight:950}}.reward-balance-card small{{color:var(--d6-muted);font-weight:750}}.reward-section{{display:grid;gap:10px}}.reward-shop-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}}.reward-shop-item{{display:grid;gap:5px;justify-items:center;padding:13px 10px;border:1px solid var(--d6-line);border-radius:16px;background:var(--d6-card);text-align:center}}.reward-shop-item .reward-icon{{font-size:1.7rem}}.reward-shop-item strong{{font-size:.92rem}}.reward-shop-item small{{color:var(--d6-muted);font-size:.72rem}}.reward-shop-item button[disabled]{{opacity:.45}}.reward-badge-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:9px}}.reward-badge{{display:grid;gap:4px;justify-items:center;padding:11px 8px;border:1px dashed var(--d6-line);border-radius:14px;background:var(--d6-canvas);text-align:center;filter:grayscale(1);opacity:.62}}.reward-badge.is-earned{{filter:none;opacity:1;border-style:solid;border-color:var(--d6-accent);background:var(--d6-card)}}.reward-badge span{{font-size:1.5rem}}.reward-badge strong{{font-size:.8rem}}.reward-badge small{{color:var(--d6-muted);font-size:.68rem}}.reward-calendar-grid{{margin:4px 0}}.reward-history{{display:grid;gap:7px}}.reward-history-row{{margin:0;display:flex;justify-content:space-between;gap:10px;padding:9px 12px;border-radius:12px;background:var(--d6-card);font-size:.86rem}}.reward-history-row small{{color:var(--d6-muted)}}.d6-star-layer{{position:fixed;inset:0;pointer-events:none;z-index:60;overflow:hidden}}.d6-star-layer span{{position:absolute;bottom:-40px;font-size:1.8rem;animation:d6-star-float 1.5s ease-in forwards}}@keyframes d6-star-float{{0%{{transform:translateY(0) scale(.6);opacity:0}}15%{{opacity:1}}100%{{transform:translateY(-105vh) scale(1.15) rotate(24deg);opacity:0}}}}.d6-shake{{animation:d6-shake .45s ease}}@keyframes d6-shake{{0%,100%{{transform:translateX(0)}}20%{{transform:translateX(-7px)}}40%{{transform:translateX(6px)}}60%{{transform:translateX(-4px)}}80%{{transform:translateX(3px)}}}}.ref-card{{gap:14px}}.ref-group{{display:grid;gap:8px}}.ref-group h5{{margin:0;font-size:.86rem;font-weight:900;color:var(--d6-primary-strong)}}.ref-chips{{display:flex;flex-wrap:wrap;gap:7px}}.ref-chip{{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-width:46px;min-height:48px;padding:6px 8px;border:2px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);color:var(--d6-ink);cursor:pointer}}.ref-chip strong{{font-size:.98rem;font-weight:900}}.ref-chip small{{font-size:.64rem;color:var(--d6-muted);font-weight:750}}.ref-chip:active{{background:color-mix(in srgb,var(--d6-primary) 16%,var(--d6-card));transform:scale(.96)}}.ref-poems{{display:grid;gap:10px}}.ref-poem{{border:1px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);padding:9px 10px}}.ref-poem summary{{display:grid;gap:2px;cursor:pointer;font-size:1rem}}.ref-poem summary strong{{font-weight:900}}.ref-poem summary span{{font-size:.78rem;color:var(--d6-muted);font-weight:800}}.ref-poem-lines{{margin:8px 0 0;font-size:.95rem;line-height:1.8;font-weight:800}}.ref-poem-note{{margin:8px 0 0;font-size:.86rem;color:var(--d6-muted)}}.ref-poem .starter-actions{{margin-top:10px}}.own-record-heading{{padding-top:8px;border-top:1px dashed var(--d6-line)}}.reliability-grid{{display:grid;gap:10px}}.reliability-grid article{{padding:14px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-card)}}
.workspace{{display:grid;gap:17px}}.back-dashboard{{justify-self:start;font-weight:900;color:var(--d6-primary-strong)}}.module-heading{{display:grid;grid-template-columns:50px 1fr;gap:13px}}.surface-fields{{display:grid;gap:12px}}.surface-field,.surface-filter{{display:grid;gap:6px;font-weight:800}}input,textarea,select{{width:100%;padding:11px 13px;border:1px solid var(--d6-line);border-radius:13px;background:color-mix(in srgb,var(--d6-card) 90%,var(--d6-canvas));color:var(--d6-ink)}}textarea{{min-height:90px;resize:vertical}}.form-actions,.tool-actions,.record-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.feedback{{min-height:1.5em;font-weight:800}}.success{{color:var(--d6-success)}}.error{{color:var(--d6-error)}}.record-list{{display:grid;gap:9px}}.record{{display:grid;gap:9px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}}.record.is-complete strong{{text-decoration:line-through}}.record.is-archived{{opacity:.62}}.data-tools{{display:grid;gap:12px;background:var(--d6-sidebar)}}.legacy-import{{padding:12px;border-radius:12px;background:var(--d6-category-2)}}.nav-list{{display:grid;gap:6px}}.nav-item{{display:flex;align-items:center;gap:8px;padding:6px;border-radius:13px;font-weight:800}}.nav-item:nth-child(1){{--nav-icon-bg:#fff0b8;--nav-icon-ink:#de6a00}}.nav-item:nth-child(2){{--nav-icon-bg:#ffe1ec;--nav-icon-ink:#dc3d68}}.nav-item:nth-child(3){{--nav-icon-bg:#dff1ff;--nav-icon-ink:#2677d4}}.nav-item:nth-child(4){{--nav-icon-bg:#ebe3ff;--nav-icon-ink:#6a50ce}}.nav-item:nth-child(5){{--nav-icon-bg:#dcf5e6;--nav-icon-ink:#13805b}}.nav-icon{{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:var(--nav-icon-bg);box-shadow:0 4px 10px color-mix(in srgb,var(--nav-icon-ink) 18%,transparent);font-family:'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif;font-size:1.2rem;line-height:1}}.nav-item.active{{background:var(--d6-primary);color:#fff}}.nav-item.active .nav-icon{{background:#fff;box-shadow:0 5px 13px rgba(45,32,48,.16)}}.bottom-nav{{position:fixed;z-index:10;left:6px;right:auto;top:60px;bottom:8px;width:84px;display:grid;grid-template-columns:1fr;grid-auto-rows:minmax(56px,auto);align-content:start;overflow-y:auto;padding:6px;border:1px solid var(--d6-line);border-radius:20px;background:color-mix(in srgb,var(--d6-card) 95%,transparent);backdrop-filter:blur(14px)}}.bottom-nav .nav-item{{display:grid;grid-template-columns:1fr;justify-items:center;align-content:center;gap:3px;width:70px;min-height:56px;padding:6px 4px;font-size:.68rem;line-height:1.15;text-align:center}}.bottom-nav .nav-label{{display:block;overflow-wrap:anywhere}}.bottom-nav .nav-icon{{width:32px;height:32px;font-size:1.1rem}}@media(max-width:430px){{.app{{padding-left:90px}}.bottom-nav{{width:78px}}.bottom-nav .nav-item{{width:64px;font-size:.62rem;gap:2px;min-height:54px}}.bottom-nav .nav-icon{{width:28px;height:28px;font-size:1rem}}}}.hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}}
@media(min-width:760px){{.learning-task-grid,.pipeline,.delivery-grid,.booking-strip,.household-columns,.generic-card-grid,.reliability-grid,.life-card-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.creator-lower,.lesson-grid,.close-grid,.fitness-layout,.travel-overview{{grid-template-columns:minmax(0,1.7fr) minmax(260px,.8fr)}}.life-dashboard .life-board{{grid-column:1/-1}}.lesson-side{{grid-template-rows:1fr 1fr}}.surface-fields{{grid-template-columns:repeat(2,minmax(0,1fr))}}.record{{grid-template-columns:1fr auto;align-items:center}}}}
@media(min-width:900px){{.app{{padding:24px;grid-template-columns:210px minmax(0,1fr)}}.mobile-brand,.bottom-nav{{display:none}}.identity-nav{{display:flex;position:sticky;top:24px;align-self:start;min-height:calc(100vh - 48px);padding:16px;border-radius:24px;background:var(--d6-sidebar);flex-direction:column;gap:18px}}.app-view{{grid-column:2}}.identity-nav{{grid-column:1;grid-row:1}}.child-layout{{grid-template-columns:minmax(0,1.7fr) minmax(260px,.7fr)}}.learning-task-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.pipeline{{grid-template-columns:repeat(3,minmax(0,1fr))}}.pipeline-stage{{display:grid;grid-template-columns:1fr;padding:20px;border-bottom:0;border-right:1px solid var(--d6-line)}}.pipeline-stage>span{{grid-row:auto}}.pipeline-stage small{{grid-column:auto}}.delivery-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.booking-strip{{grid-template-columns:repeat(3,1fr)}}.household-columns{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:520px){{.scene-hero{{min-height:270px;align-items:end}}.hero-motif{{right:-3%;font-size:100px}}.finance-metrics{{grid-template-columns:1fr}}.panel-heading,.starter-heading,.starter-card-meta{{display:grid}}.rail{{font-size:.78rem}}.starter-actions{{position:sticky;bottom:76px;z-index:2;padding:8px;border-radius:16px;background:color-mix(in srgb,var(--d6-card) 94%,transparent);backdrop-filter:blur(10px)}}.starter-actions button{{flex:1}}}}
.scene-template-freelance_delivery_studio .identity-nav{{color:#fff}}.scene-template-freelance_delivery_studio .identity-nav .nav-item.active{{background:var(--d6-accent);color:#102f29}}.scene-template-freelance_delivery_studio .identity-nav .brand-mark{{background:var(--d6-accent)}}.scene-template-freelance_delivery_studio .milestone-rail{{color:#fff}}.scene-template-freelance_delivery_studio .milestone-rail .eyebrow,.scene-template-freelance_delivery_studio .milestone-rail small{{color:#c9ddd6}}.scene-template-freelance_delivery_studio .milestone-rail .rail span{{border-color:#dce9e3}}
.child-greeting>strong{{white-space:nowrap}}
</style></head><body><main class="app scene-template-{_e(scene_template_id)} renderer-{_e(rendered['renderer_id'])}" data-double6-build-id="{_e(build_id)}" data-double6-product-id="{_e(product['product_id'])}" data-double6-pack-id="{_e(product['recommendation_plan']['pack_id'])}" data-double6-recommendation-sha256="{_e(product['recommendation_plan']['recommendation_sha256'])}" data-double6-surface-registry-version="{product['recommendation_plan']['surface_registry_version']}" data-double6-starter-contract-version="{_e(product['recommendation_plan']['starter_contract_version'])}" data-double6-reliability-contract-version="local_delivery_reliability_v1" data-double6-token-id="{_e(design['current']['token_id'])}" data-double6-template-id="{_e(design['current']['template_id'])}" data-double6-scene-template-id="{_e(scene_template_id)}" data-double6-renderer-id="{_e(rendered['renderer_id'])}" data-double6-visual-contract-version="{VISUAL_CONTRACT_VERSION}" data-double6-visual-kernel-id="vivid_social_workbench_templates_v4" data-double6-scene-id="{_e(experience['scene_id'])}" data-double6-experience-signature="{_e(design['current']['experience_signature'])}">
<div class='mobile-brand'><span class='brand-mark' data-double6-emoji-role='brand'>{_e(template['motif'])}</span><span>{_e(product['title'])}</span></div><aside class='identity-nav' data-double6-role='identity-navigation'><div class='brand'><span class='brand-mark' data-double6-emoji-role='brand'>{_e(template['motif'])}</span><span>{_e(product['title'])}</span></div><nav class='nav-list'>{nav_html}</nav></aside>
{rendered['dashboard_html']}{rendered['detail_views_html']}
	<section id='data-tools' class='app-view data-tools' data-view-id='data-tools' hidden><a class='back-dashboard' href='#dashboard'>← 返回首页</a><span class='eyebrow'>本地保存与恢复</span><div class='reliability-grid' data-reliability-public-layer><article><strong>入口</strong><p>本地单文件；当前候选不是永久链接或原生 App。</p></article><article><strong>数据位置</strong><p>当前设备、当前浏览器；未接入云备份或跨设备同步。</p></article><article><strong>外部数据</strong><p>内置内容为合成或自编；天气、价格、余量、账号和支付均未接入。</p></article><article data-reliability-receipt><strong>本地恢复能力</strong><p>保存、刷新恢复、导出、导入预览、撤销导入和清空均进入验收。</p></article></div><div class='tool-actions'><button class='secondary' data-double6-hook='export'>导出备份</button>{finance_csv_control}<label><span class='hidden'>导入备份</span><input data-double6-hook='import' type='file' accept='application/json,text/plain,.json,.txt'></label><button class='secondary' data-double6-hook='undo-import' hidden>撤销最近导入</button><button class='secondary' data-double6-hook='clear'>清空本地数据</button></div><p class='feedback' data-double6-hook='data-feedback' aria-live='polite'></p><p class='legacy-import' data-double6-hook='legacy-import' hidden></p><details data-deployment-guide><summary>想在手机上长期使用或分享给别人？</summary><p>先导出备份，并确认页面不含真实隐私数据；然后在取得明确授权后，交由独立宿主发布流程生成真实链接和内容回执。拿到链接后，可在手机浏览器中使用“添加到主屏幕”。当前页面不会自动上线、发送或公开数据。</p></details><div data-double6-hook='claims'>个人数据只保存在当前设备；页面只展示你录入的事实，不生成医学、财务、经营、天气或预订判断。导入最多 2 MB、每个模块最多 500 条记录。<details><summary>使用边界</summary><ul>{boundaries}</ul></details></div></section>
<nav class='bottom-nav' data-double6-role="mobile-bottom-navigation">{nav_html}</nav></main><script>{script}</script></body></html>"""


def build(run_dir: Path) -> dict[str, Any]:
    run = load_run(run_dir)
    require_state(run, "ready_to_build", "evaluation_failed")
    product = read_json(run_dir / "product.json")
    if product.get("confirmation", {}).get("status") != "confirmed":
        raise ContractError("构建前必须由当前用户事件确认产品")
    confirmed_sha256 = str(product.get("confirmation", {}).get("product_content_sha256") or "")
    if not confirmed_sha256 or confirmed_sha256 != product_content_sha256(product):
        raise ContractError("产品内容在确认后发生变化；必须重新生成理解稿并由用户确认")
    design, token, template = _select_design(run_dir, product)
    build_id = f"build-{uuid.uuid4().hex}"
    storage_key = f"double6:{product['product_id']}:v3"
    candidate_html = _html(product, design, token, template, build_id, storage_key)
    candidate_sha = digest_bytes(candidate_html.encode("utf-8"))
    previous = read_json(run_dir / "build.json") if (run_dir / "build.json").is_file() else {"builds": []}
    builds = list(previous.get("builds", []))
    if previous.get("current"):
        builds.append(previous["current"])
    plan = product["recommendation_plan"]
    current = {
        "build_id": build_id, "product_sha256": digest_bytes(canonical(product)), "design_sha256": digest_bytes(canonical(design)),
        "token_id": design["current"]["token_id"], "template_id": design["current"]["template_id"],
        "template_system_id": design["current"]["template_system_id"], "storage_key": storage_key, "candidate_sha256": candidate_sha,
        "scene_template_id": design["current"].get("scene_template_id"), "renderer_id": design["current"]["renderer_id"],
        "visual_contract_version": design["current"]["visual_contract_version"],
        "scene_id": design["current"]["scene_id"],
        "experience_signature": design["current"]["experience_signature"], "content_pack_id": plan["pack_id"],
        "recommendation_sha256": plan["recommendation_sha256"], "surface_registry_version": plan["surface_registry_version"],
        "starter_contract_version": plan["starter_contract_version"],
        "reliability_contract_version": "local_delivery_reliability_v1",
        "starter_item_counts": {
            row["recommendation_module_id"]: len(row["starter"]["starter_items"]) + sum(
                extension.get("module_id") == row["recommendation_module_id"]
                for extension in product.get("module_extensions", [])
            )
            for row in product["capabilities"] if row["mode"] == "in_page"
        },
        "module_ids": list(plan["selected_core_module_ids"]), "built_at": now(),
    }
    build_value = {"schema_version": schema("build"), "current": current, "builds": builds, "updated_at": now()}
    design["build_history"] = [{
        "build_id": row.get("build_id"), "template_id": row.get("template_id"),
        "candidate_sha256": row.get("candidate_sha256"),
    } for row in [*builds, current]]
    lock = {
        "schema_version": schema("candidate_lock"), "candidate_root": str((run_dir / "candidate").resolve()),
        "entrypoint": "index.html", **current, **run["request_binding"], "locked_at": now(),
    }
    evidence = {
        "schema_version": schema("evidence"), "status": "pending", "build_id": build_id,
        "surface_registry_version": plan["surface_registry_version"],
        "starter_contract_version": plan["starter_contract_version"],
        "starter_checks": {module_id: {"content": "pending", "interaction": "pending", "persistence": "pending"} for module_id in plan["selected_core_module_ids"]},
        "renderer_id": current["renderer_id"], "visual_contract_version": current["visual_contract_version"],
        "first_screen_slots": {slot: "pending" for slot in sorted(FIRST_SCREEN_SLOTS)},
        "structure_fingerprint": "pending", "viewport_evidence": {"mobile": "pending", "tablet": "pending", "desktop": "pending"},
        "function_entry_checks": {module_id: "pending" for module_id in plan["selected_core_module_ids"]},
        "surface_checks": {module_id: {"crud": "pending", "persistence": "pending", "recovery": "pending"} for module_id in plan["selected_core_module_ids"]},
        "checks": {}, "artifacts": [], "updated_at": now(),
    }
    delivery = read_json(run_dir / "delivery.json") if (run_dir / "delivery.json").is_file() else {"schema_version": schema("delivery")}
    delivery["local"] = {"state": "candidate_built", "build_id": build_id, "candidate_sha256": candidate_sha, "updated_at": now()}
    delivery["updated_at"] = now()
    run = transition(run, "candidate_built", "needs_visual_confirmation", "candidate_built", {"build_id": build_id, "template_id": design["current"]["template_id"], "renderer_id": current["renderer_id"]})
    commit(run_dir, {
        "candidate/index.html": candidate_html, "design.json": design, "build.json": build_value,
        "candidate-lock.json": lock, "evidence.json": evidence, "delivery.json": delivery, "run.json": run,
    })
    return {
        "status": run["status"], "state": run["state"], "build_id": build_id,
        "candidate": str((run_dir / "candidate" / "index.html").resolve()),
        "token_id": design["current"]["token_id"], "template_id": design["current"]["template_id"],
        "renderer_id": design["current"]["renderer_id"], "visual_contract_version": design["current"]["visual_contract_version"],
        "candidate_sha256": candidate_sha,
        "conversation_text": "候选已生成。请先打开并实际查看这个页面；满意时再明确确认当前候选，或直接描述构图、密度、颜色、字体、场景感或交互需要怎样改。未收到你的视觉确认前，不会进入验收或标记交付。",
        "next": "respond",
    }
