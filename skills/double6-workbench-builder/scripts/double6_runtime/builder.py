"""单候选构建器：公共壳层、精确场景 renderer、starter 与安全本地状态。"""

from __future__ import annotations

import base64
import html
import json
import uuid
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any

from .core import (
    ContractError, REFERENCES, canonical, commit, digest_bytes, load_run, now,
    product_content_sha256, read_json, require_state, schema, transition,
)
from .html_policy import CSP_POLICY
from .routing import style_hint
from .child_playground import (
    VISUAL_CONTRACT_VERSION as CHILD_PLAYGROUND_VISUAL_CONTRACT_VERSION,
    render_child_playground,
)
from .scene_renderers import (
    VISUAL_CONTRACT_VERSION,
    registered_renderer_ids,
    render_scene,
)
from .composition import module_contract, validate_compiled_composition
from .incentive_library import load_incentive_library
from .atomic_engine import LEDGER_CSV_SPECS
from .theme_system import select_design_theme, validate_theme_contract


TOKEN_IDS = {"general-focus", "professional-trust", "editorial-story", "playful-growth", "high-contrast-execution"}
TEMPLATE_IDS = {
    "coral_sprout", "cosmic_grape", "lesson_bloom", "sky_postcard", "studio_sunset", "ink_parchment",
    "ledger_jade", "home_sunrise", "energy_sprint",
}
SCENE_TEMPLATE_IDS = {
    "child_learning_quest", "teacher_lesson_studio", "freelance_delivery_studio",
    "travel_departure_atlas", "creator_production_room", "finance_month_close",
    "household_week_coordination", "fitness_week_sprint", "personal_life_dashboard",
    "research_reading_desk", "personal_week_command", "sales_followup_pipeline", "research_evidence_pipeline",
    "fitness_fat_loss_execute", "teaching_classroom_daily", "exam_civil_service_practice",
}

CJK_SANS_STACK = (
    "system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB',"
    "'Microsoft YaHei','Noto Sans CJK SC','Noto Sans SC','Source Han Sans SC',sans-serif"
)

POLISH_CSS = (
    "body{font-family:" + CJK_SANS_STACK + ";-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;letter-spacing:.005em}"
    "h1,h2,h3,h4{font-family:" + CJK_SANS_STACK + ";font-weight:800;letter-spacing:-.01em}"
    "small{color:color-mix(in srgb,var(--d6-ink) 62%,var(--d6-card))}"
    ".scene-hero{min-height:0;padding:clamp(20px,3.2vw,34px) clamp(20px,4vw,40px);border-radius:26px;"
    "box-shadow:0 18px 40px color-mix(in srgb,var(--d6-primary) 26%,transparent)}"
    ".scene-hero h1{font-size:clamp(1.45rem,2.6vw,2.05rem);max-width:26ch}"
    ".scene-hero p{max-width:52ch;opacity:.96}"
    ".hero-kicker{display:inline-flex;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.2);font-size:.8rem}"
    ".hero-motif{top:50%;transform:translateY(-50%);font-size:clamp(84px,12vw,150px);opacity:.22}"
    ".dashboard-view{gap:14px}"
    ".today-workboard{grid-template-columns:1fr;gap:10px;padding:16px 20px}"
    ".today-workboard h2{font-size:1.05rem}"
    ".today-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}"
    ".today-actions .text-link{margin-top:0;margin-right:auto}"
    "@media(min-width:900px){.today-workboard{grid-template-columns:minmax(0,1fr) auto;align-items:center}"
    ".today-workboard>.today-items{grid-column:1/-1}.today-workboard>.backup-reminder{grid-column:1/-1}}"
    ".panel-heading h2{font-size:clamp(1.15rem,2vw,1.45rem)}"
    ".eyebrow{letter-spacing:.04em}"
    ".module-heading h2{font-size:clamp(1.4rem,2.6vw,1.9rem)}"
    ".starter-card{box-shadow:0 4px 14px color-mix(in srgb,var(--d6-ink) 6%,transparent)}"
    ".starter-card p{color:color-mix(in srgb,var(--d6-ink) 82%,var(--d6-card))}"
    ".all-modules{display:grid;gap:10px}"
    ".all-modules-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}"
    ".module-tile{display:grid;grid-template-columns:44px 1fr;gap:10px;align-items:center;padding:12px 14px;border:1px solid var(--d6-line);"
    "border-radius:16px;background:var(--d6-card);transition:transform .15s ease,box-shadow .15s ease}"
    ".module-tile:hover{transform:translateY(-2px);box-shadow:0 10px 22px color-mix(in srgb,var(--d6-primary) 16%,transparent)}"
    ".module-tile>span{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;background:var(--d6-category-1);font-size:1.35rem}"
    ".module-tile:nth-child(4n+2)>span{background:var(--d6-category-2)}.module-tile:nth-child(4n+3)>span{background:var(--d6-category-3)}"
    ".module-tile:nth-child(4n+4)>span{background:var(--d6-category-4)}"
    ".module-tile strong{display:block;font-size:.98rem}.module-tile small{display:block;font-size:.8rem;line-height:1.35}"
    ".generic-work-card>span,.platform-chip>span{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;background:var(--d6-category-2);font-size:1.3rem}"
    ".generic-work-card:hover{border-color:var(--d6-primary)}"
    ".creator-grid,.research-grid{display:grid;gap:14px}"
    "@media(min-width:900px){.creator-grid,.research-grid{grid-template-columns:minmax(0,1.6fr) minmax(260px,.9fr)}}"
    ".pipeline-stage{display:grid;gap:4px;padding:14px;border-radius:16px;background:var(--d6-canvas);border:1px solid var(--d6-line)}"
    ".pipeline-stage>span{font-size:1.4rem}.pipeline-stage strong{font-size:1rem}"
    ".pipeline{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}"
    "@media(min-width:900px){.pipeline{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}.pipeline-stage{border-right:1px solid var(--d6-line);padding:14px}}"
    ".platform-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}"
    ".platform-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;background:var(--d6-category-1);font-weight:800;font-size:.86rem}"
    ".week-rhythm{display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:6px}"
    ".week-rhythm div{display:grid;gap:4px;justify-items:center;padding:10px 4px;border-radius:14px;background:var(--d6-canvas);border:1px solid var(--d6-line);font-size:.78rem;text-align:center}"
    ".week-rhythm div strong{font-size:.86rem}.week-rhythm div.is-today{background:var(--d6-primary);color:#fff;border-color:transparent}"
    ".week-rhythm div.is-today small{color:#fff}"
    ".reading-shelf{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}"
    ".shelf-stage{display:grid;gap:6px;padding:14px;border-radius:16px;background:var(--d6-canvas);border:1px solid var(--d6-line);border-top:5px solid var(--d6-primary)}"
    ".shelf-stage:nth-child(2){border-top-color:var(--d6-accent)}.shelf-stage:nth-child(3){border-top-color:#f2b84b}.shelf-stage:nth-child(4){border-top-color:#8a7cf0}"
    ".shelf-stage strong{font-size:1rem}.shelf-stage>span{font-size:1.5rem}"
    ".side-stack{display:grid;gap:14px;align-content:start}"
    ".side-card{padding:18px;border-radius:22px;background:var(--d6-sidebar);border:1px solid var(--d6-line)}"
    ".side-card ol,.side-card ul{margin:8px 0 0;padding-left:1.2em;display:grid;gap:6px}"
    ".side-card h3{margin:.2rem 0;font-size:1.05rem}"
    "@media(max-width:600px){.today-actions .text-link{flex-basis:100%}.hero-motif{font-size:84px;opacity:.14;top:auto;bottom:-6px;transform:none}"
    ".scene-hero h1{font-size:1.4rem}.scene-hero p{font-size:.95rem}.today-workboard{padding:14px 16px}}"
)

FIRST_SCREEN_SLOTS = {"hero", "primary_surface", "progress", "supporting_panel"}
SURFACE_PRIMITIVE_IDS = {
    "action_checklist": "surface.checklist",
    "record_ledger": "surface.record-ledger",
    "stage_board": "surface.stage-board",
    "metric_log": "surface.metric",
    "review_journal": "surface.review",
    "reward_economy": "surface.reward-exchange",
}
EMOJI_RULES = [
    # 语义优先：具体词在前，确保同一工作台里每个入口的 emoji 与含义一致且不重复。
    (("阅读清单", "书单", "在读"), "📖"),
    (("研究问题",), "🔍"),
    (("文献", "证据", "引用"), "📚"),
    (("信息输入", "素材", "收集"), "📥"),
    (("选题",), "💡"),
    (("制作", "脚本"), "🛠️"),
    (("发布", "排期"), "📅"),
    (("数据复盘", "指标", "分析"), "📊"),
    (("写作", "交付", "报告"), "✍️"),
    (("周复盘", "复盘"), "🔁"),
    (("文献", "证据", "引用"), "🔖"),
    (("账号",), "👥"),
    (("口算", "数学", "计算", "指标", "收支"), "🧮"),
    (("阅读", "读书", "资料", "文献", "素材"), "📚"),
    (("写", "记录", "日志", "复盘"), "✍️"),
    (("运动", "训练", "健身", "恢复"), "🏃"),
    (("日程", "计划", "排期", "预约"), "📅"),
    (("内容", "选题", "发布"), "💡"),
    (("客户", "学生", "跟进", "管道"), "🤝"),
    (("分析", "数据", "成绩", "库存"), "📊"),
]
LEARNING_MODULE_PREFIXES = ("education-", "exam-")
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
        raise ContractError("鲜艳社媒模板系统必须包含九套去重模板、十六个精确场景模板和十四个颜色 token")
    for row in value["templates"]:
        if set(row.get("palette", {})) != required_tokens:
            raise ContractError(f"模板颜色 token 不完整：{row.get('template_id')}")
    renderer_ids = registered_renderer_ids()
    for row in value["scene_templates"]:
        expected_visual_contract = (
            CHILD_PLAYGROUND_VISUAL_CONTRACT_VERSION
            if row.get("renderer_id") == "child_playground_v2"
            else VISUAL_CONTRACT_VERSION
        )
        if (
            row.get("renderer_id") not in renderer_ids
            or row.get("visual_contract_version") != expected_visual_contract
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
    composition = validate_compiled_composition(
        product.get("recommendation_plan", {}).get("composition_contract")
    )
    pack = (composition or {}).get("pack") or {}
    scene = _scene_template(template_system, requirements, product)
    if pack.get("scene_template_id"):
        packed = next(
            (row for row in template_system["scene_templates"] if row.get("scene_template_id") == pack["scene_template_id"]),
            None,
        )
        if packed is None:
            raise ContractError(f"composition pack 引用未知 scene_template：{pack['scene_template_id']}")
        scene = packed
    elif pack:
        scene = None
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
    renderer_id = pack.get("renderer_id") or (scene["renderer_id"] if scene else "generic_dashboard")
    scene_template_id = pack.get("scene_template_id") if pack else (scene["scene_template_id"] if scene else None)
    scene_profile_id = str(pack.get("scene_profile_id") or "")
    requested_adult_theme = (
        preferences.get("adult_theme_id")
        or product.get("design_brief", {}).get("adult_theme_id")
    )
    if not requested_adult_theme and scene_profile_id.endswith("civil-service-exam"):
        requested_adult_theme = "study_paper_robot"
    selected_adult_theme = select_design_theme(scene_profile_id, requested_adult_theme)
    adult_theme_id = selected_adult_theme["theme_id"] if selected_adult_theme else None
    visual_contract = (
        CHILD_PLAYGROUND_VISUAL_CONTRACT_VERSION
        if renderer_id == "child_playground_v2"
        else (scene["visual_contract_version"] if scene else VISUAL_CONTRACT_VERSION)
    )
    attempt = {
        "attempt_id": f"attempt-{len(previous.get('visual_attempts', [])) + 1}",
        "token_id": token_id, "template_id": template_id, "scene_template_id": scene_template_id,
        "renderer_id": renderer_id,
        "adult_theme_id": adult_theme_id,
        "theme_selection_stage": "design_time" if adult_theme_id else None,
        "visual_contract_version": visual_contract,
        "experience_signature": signature,
        "feedback_dimensions": sorted(dimensions), "attempted_at": now(),
    }
    design = {
        "schema_version": schema("design"), "status": "selected",
        "current": {
            "token_id": token_id, "template_id": template_id,
            "template_system_id": template_system["system_id"], "scene_template_id": scene_template_id,
            "renderer_id": renderer_id,
            "adult_theme_id": adult_theme_id,
            "theme_selection_stage": "design_time" if adult_theme_id else None,
            "visual_contract_version": visual_contract,
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


def _contrast_ink(background_value: str, fallback_ink: str) -> str:
    """为背景选择达到 WCAG AA 的白色或当前模板正文色。"""
    def luminance(value: str) -> float:
        raw = value.lstrip("#")
        channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    background = luminance(background_value)
    white_contrast = (1.0 + 0.05) / (background + 0.05)
    fallback = luminance(fallback_ink)
    fallback_contrast = (max(background, fallback) + 0.05) / (min(background, fallback) + 0.05)
    if white_contrast >= 4.5:
        return "#ffffff"
    return fallback_ink if fallback_contrast >= 4.5 else "#000000"


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


def _theme_bundle(product: dict[str, Any], design: dict[str, Any]) -> dict[str, Any] | None:
    plan = product.get("recommendation_plan", {})
    composition = validate_compiled_composition(plan.get("composition_contract"))
    scene_id = str((composition or {}).get("pack", {}).get("scene_profile_id") or "")
    contract = validate_theme_contract(plan.get("theme_contract"), scene_id)
    if contract is None:
        return None
    selected_id = str(design.get("current", {}).get("adult_theme_id") or "")
    selected = next((row for row in contract["themes"] if row["theme_id"] == selected_id), None)
    if selected is None:
        raise ContractError("设计稿未锁定有效的成人主题")
    theme = deepcopy(selected)
    embedded_assets = {}
    for asset in theme.get("assets", []):
        path = REFERENCES / asset["path"]
        raw = path.read_bytes()
        if digest_bytes(raw) != asset["sha256"]:
            raise ContractError(f"主题资产 SHA 漂移：{path}")
        mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/jpeg"
        embedded_assets[asset["role"]] = {
            "data_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
            "alt": asset.get("alt", ""),
            "sha256": asset["sha256"],
        }
    theme["embedded_assets"] = embedded_assets
    return {
        "schema_version": 2,
        "contract_version": contract["contract_version"],
        "registry_sha256": contract["registry_sha256"],
        "family_id": contract["family_id"],
        "selection_stage": "design_time",
        "runtime_switching": False,
        "selected_theme": theme,
    }


def _theme_root_attributes(bundle: dict[str, Any] | None) -> str:
    if not bundle:
        return " data-double6-theme-selection-stage='none' data-double6-theme-runtime-switching='false'"
    theme = bundle["selected_theme"]
    tokens = theme["tokens"]
    hero = theme.get("embedded_assets", {}).get("hero", {}).get("data_url", "")
    quiet_studio = theme["theme_id"] == "life_quiet_studio"
    style_tokens = {
        "--d6-canvas": tokens["canvas"], "--d6-card": tokens["card"],
        "--d6-ink": tokens["ink"], "--d6-muted": tokens["muted"],
        "--d6-primary": tokens["primary"], "--d6-accent": tokens["accent"],
        "--d6-sidebar": tokens["sidebar"], "--d6-line": tokens["line"],
        "--d6-sidebar-ink": _contrast_ink(tokens["sidebar"], tokens["ink"]),
        "--d6-primary-ink": _contrast_ink(tokens["primary"], tokens["ink"]),
        "--d6-theme-hero": f'url("{hero}")' if hero else "none",
        "--d6-hero-ink": "#ffffff" if quiet_studio else tokens["ink"],
        "--d6-hero-overlay-start": "rgba(21,29,45,.98)" if quiet_studio else "color-mix(in srgb,var(--d6-card) 96%,transparent)",
        "--d6-hero-overlay-mid": "rgba(21,29,45,.82)" if quiet_studio else "color-mix(in srgb,var(--d6-card) 80%,transparent)",
        "--d6-hero-overlay-end": "rgba(21,29,45,.12)" if quiet_studio else "transparent",
    }
    style = ";".join(f"{key}:{value}" for key, value in style_tokens.items())
    asset_shas = ",".join(asset["sha256"] for asset in theme.get("assets", [])) or "none"
    return (
        f" data-theme-id='{_e(theme['theme_id'])}'"
        " data-double6-theme-selection-stage='design_time'"
        " data-double6-theme-runtime-switching='false'"
        f" data-double6-theme-asset-shas='{_e(asset_shas)}' style='{_e(style)}'"
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


def _own_record_heading(module_id: str) -> str:
    """自有记录区按模块说话：成人台不套儿童作业口吻。"""
    family = str(module_id).split("-", 1)[0]
    if family == "education":
        detail = "只有要保存老师布置的内容、自己的错题或安排时，才需要填写下面这部分。"
        voice = "education"
    elif family == "exam":
        detail = "只有要保存自己的题目、错题或复习安排时，才需要填写下面这部分。"
        voice = "exam"
    elif family == "teaching":
        detail = "只有要保存教案、作业或课堂安排时，才需要填写下面这部分。"
        voice = "teaching"
    else:
        detail = "只有要把自己的记录、安排或结果保存下来时，才需要填写下面这部分。"
        voice = "adult"
    return (
        f"<div class='own-record-heading' data-own-record-voice='{voice}'>"
        "<span class='eyebrow'>自己要留的记录</span>"
        f"<p>{detail}</p></div>"
    )


def _surface_label(surface_type: str, module_id: str = "") -> str:
    """房间眉题说今晚的活，不说存储合同。"""
    job = {
        "exam-goal": "今晚备考",
        "exam-today": "今晚备考",
        "exam-practice": "今晚备考",
        "exam-errors": "今晚备考",
        "exam-materials": "今晚备考",
        "finance-transactions": "今晚记账",
        "finance-vouchers": "今晚记账",
        "finance-tax": "今晚记账",
        "finance-review": "今晚记账",
        "finance-audit": "今晚记账",
        "household-chores": "今晚谁做",
        "household-shopping": "今晚要买",
        "household-handoff": "待当面说",
        "commerce-orders": "今天这几单",
        "commerce-inventory": "库存快照",
        "commerce-service": "待在平台回",
        "research-writing": "今晚这条结论",
        "research-questions": "今晚这个问题",
        "research-evidence": "挂上的出处",
        "fitness-today": "今天练不练",
        "fitness-food": "今日三餐",
        "fitness-log": "今日体重",
        "teaching-daily": "今日班务",
        "teaching-attendance": "今日考勤",
        "teaching-students": "待跟进",
    }.get(str(module_id))
    if job:
        return job
    family = str(module_id).split("-", 1)[0]
    if family in {"exam", "finance", "household", "commerce", "research", "fitness", "teaching"}:
        return {
            "action_checklist": "今晚要勾的",
            "record_ledger": "今晚记下的",
            "stage_board": "进行到哪",
            "metric_log": "今晚做过的",
            "review_journal": "今晚判断",
        }.get(surface_type, "今晚这件事")
    return {
        "action_checklist": "现在要做的",
        "record_ledger": "我的记录",
        "stage_board": "进行到哪",
        "metric_log": "记下的数字",
        "review_journal": "复盘",
        "reward_economy": "星星与奖励",
    }.get(surface_type, "我的内容")


def _atomic_tools_html(capability: dict[str, Any]) -> str:
    """只渲染当前已选模块编译出的 executable atom 控件。"""
    atom_ids = {str(value) for value in capability.get("atomic_capability_ids", [])}
    tools: list[str] = []
    if "atom.shared.retrieve-library-item" in atom_ids:
        tools.append(
            "<section class='atomic-tool' data-atomic-tool='atom.shared.retrieve-library-item'>"
            "<span class='eyebrow'>当前模块资料检索</span><h3>只查已选资料</h3>"
            "<label><span>关键词</span><input data-library-query maxlength='200' placeholder='输入来源、主题或标题'></label>"
            "<button type='button' class='secondary' data-library-search>检索</button>"
            "<div class='atomic-output' data-library-results aria-live='polite'>空查询不会展开全部资料。</div></section>"
        )
    if "atom.shared.generate-review-draft" in atom_ids:
        tools.append(
            "<section class='atomic-tool' data-atomic-tool='atom.shared.generate-review-draft'>"
            "<span class='eyebrow'>可审核草稿</span><h3>从明确选中的事实起草</h3>"
            "<div class='atomic-fact-list' data-draft-facts></div>"
            "<button type='button' class='secondary' data-generate-draft>生成草稿</button>"
            "<pre class='atomic-output' data-draft-output aria-live='polite'>先选择至少一条事实。</pre></section>"
        )
    if "atom.shared.summarize-metrics" in atom_ids:
        tools.append(
            "<section class='atomic-tool' data-atomic-tool='atom.shared.summarize-metrics'>"
            "<span class='eyebrow'>事实指标汇总</span><h3>按同指标、同单位重算</h3>"
            "<label><span>方法</span><select data-metric-method><option value='sum'>合计</option>"
            "<option value='average'>平均</option><option value='latest'>最新</option></select></label>"
            "<button type='button' class='secondary' data-metric-summary>重新汇总</button>"
            "<div class='atomic-output' data-metric-output aria-live='polite'>没有样本时会显示“数据不足”，不会写成 0。</div></section>"
        )
    if "atom.shared.confirm-external-operation" in atom_ids:
        tools.append(
            "<section class='atomic-tool' data-atomic-tool='atom.shared.confirm-external-operation'>"
            "<span class='eyebrow'>外部操作人工交接</span><h3>先看目标、载荷与影响</h3>"
            "<label><span>外部目标</span><input data-handoff-target placeholder='例如：待人工打开的平台或联系人代号'></label>"
            "<label><span>载荷预览</span><textarea data-handoff-payload placeholder='只写准备交接的内容，不填账号密钥'></textarea></label>"
            "<label><span>影响</span><input data-handoff-impact placeholder='例如：可能对外可见'></label>"
            "<div class='form-actions'><button type='button' class='secondary' data-handoff-preview>生成交接预览</button>"
            "<button type='button' data-handoff-confirm hidden>确认仅保存人工交接</button></div>"
            "<div class='atomic-output' data-handoff-output aria-live='polite'>当前未执行任何发送或发布。</div></section>"
        )
    return "".join(tools)


def _personal_platform_cards(module_id: str) -> str:
    """把锁定的个人执行模板放回它们真正服务的模块，而不是堆在首页。"""
    source = read_json(REFERENCES / "personal-platform-bridge.json")
    rows = source.get("items", []) if source.get("schema_version") == "double6.personal-platform-bridge/v1" else []
    selected = [row for row in rows if row.get("target_module_id") == module_id]
    if not selected:
        return ""
    cards = "".join(
        "<article class='personal-tool-card' "
        f"data-personal-platform-item='{_e(row['item_id'])}' data-platform-source-sha='{_e(row['source_sha256'])}'>"
        f"<div><strong>{_e(row['title'])}</strong><p>{_e(row['body'])}</p><small>{_e(row['result'])}</small></div>"
        f"<button type='button' class='tiny' data-personal-platform-action='{_e(row['action'])}' "
        f"data-personal-platform-item-id='{_e(row['item_id'])}'>{_e(row['action_label'])}</button></article>"
        for row in selected
    )
    return f"<aside class='personal-module-templates'><span class='eyebrow'>可直接采用</span><div class='personal-tool-grid'>{cards}</div></aside>"


SURFACE_TEMPLATE_FILE = "workbench-surface-templates.json"


def _surface_templates() -> dict[str, Any]:
    value = read_json(REFERENCES / SURFACE_TEMPLATE_FILE)
    templates = value.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ContractError("surface template registry 为空")
    return templates


def _composition_special_surface(contract: dict[str, Any] | None) -> str:
    """只按已编译的 surface_template_id 查找声明式模板，不再按场景函数分发。"""
    if contract is None:
        return ""
    surface_template_id = str(contract["surface_template_id"])
    row = _surface_templates().get(surface_template_id)
    if not isinstance(row, dict) or not row.get("html"):
        raise ContractError(f"composition surface renderer 未登记：{surface_template_id}")
    markup = str(row["html"])
    if "{platform_cards}" in markup:
        markup = markup.replace("{platform_cards}", _personal_platform_cards(str(row.get("platform_cards_module") or "")))
    return markup


def _apply_pack_visible_copy(capabilities: list[dict[str, Any]], pack: dict[str, Any]) -> None:
    """健身页用 pack 模块名，避免夹具把考公文案写成「错题复盘」。"""
    scene = str(pack.get("scene_profile_id") or "")
    if "fitness" not in scene and pack.get("domain_id") not in {
        "fitness-nutrition",
        "teaching-classroom",
        "exam-preparation",
        "content-operations",
        "sales-trade",
        "finance-tax-contract",
    }:
        return
    catalog = {
        str(row.get("module_id")): row
        for pack_row in read_json(REFERENCES / "domain-content-packs.json").get("packs", [])
        for row in pack_row.get("modules", [])
        if isinstance(row, dict) and row.get("module_id")
    }
    by_id = {str(row["module_id"]): row for row in pack.get("modules", [])}
    for row in capabilities:
        module_id = str(row.get("recommendation_module_id") or "")
        pack_mod = by_id.get(module_id) or {}
        domain_mod = catalog.get(module_id) or {}
        if pack_mod.get("link_label"):
            row["name"] = pack_mod["link_label"]
        desc = str(domain_mod.get("description") or "").strip()
        if desc:
            row["description"] = desc
        elif "错题" in str(row.get("description") or ""):
            row["description"] = "打开就记下今天的体重、三餐和有没有练。"


def _apply_gongkao_civil_overlay(capabilities: list[dict[str, Any]], pack: dict[str, Any]) -> None:
    """考公第二步：把本站题库和打判接进三科房间，不改已确认的模块名单。"""
    if pack.get("scene_profile_id") != "scene.exam-preparation.civil-service-exam":
        return
    overlay = read_json(REFERENCES / "gongkao-civil-overlay.json")
    names = overlay.get("names") or {}
    summaries = overlay.get("summaries") or {}
    for row in capabilities:
        module_id = str(row.get("recommendation_module_id") or "")
        if module_id in names:
            row["name"] = names[module_id]
        items = overlay.get(module_id)
        if isinstance(items, list) and items:
            row.setdefault("starter", {})["starter_items"] = deepcopy(items)
            row["starter"]["item_kinds"] = sorted({str(item.get("kind") or "") for item in items})
            row["starter"]["summary"] = summaries.get(module_id) or row["starter"].get("summary")
        if module_id == "exam-practice":
            row["description"] = "按模块连做，当场看对错和本题说明。打判不是官方分。"
        elif module_id == "exam-materials":
            row["description"] = "对着资料写，打立意、结构和采点。不是阅卷分数。"
        elif module_id == "exam-today":
            row["description"] = "抽题计时，贴转写打内容。不是过线，也不是心理测评。"
        elif module_id == "exam-errors":
            row["description"] = "只回炉行测里错过的原题。"


def _surface_section(
    capability: dict[str, Any],
    primary: bool,
    emoji: str,
    *,
    composition_contract: dict[str, Any] | None = None,
) -> str:
    module_id, surface = str(capability["recommendation_module_id"]), capability["surface"]
    starter = capability["starter"]
    surface_primitive_id = SURFACE_PRIMITIVE_IDS[str(surface["type"])]
    starter_kinds = {str(row.get("kind") or "") for row in starter["starter_items"]}
    starter_bindings = ""
    if "reference" in starter_kinds:
        starter_bindings += " data-surface-library data-surface-primitive-library='surface.library'"
    if starter_kinds & {"question", "generator", "calculator", "prompt", "template", "action"}:
        starter_bindings += " data-guided-practice data-surface-primitive-guided='surface.guided-practice'"
    atom_ids = {str(value) for value in capability.get("atomic_capability_ids", [])}
    field_rows = []
    for source_field in surface["fields"]:
        field = deepcopy(source_field)
        if "atom.shared.record-metric" in atom_ids and field.get("field_id") == "date":
            field.update(required=True, label="记录日期")
        field_rows.append(field)
    fields = "".join(_field_html(module_id, row) for row in field_rows)
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
            "<section class='reward-economy' data-reward-root data-surface-primitive-id='surface.reward-exchange'>"
            "<div class='reward-balance-card'><span class='eyebrow'>我的星星</span><strong data-reward-balance>0 ⭐</strong>"
            "<small data-reward-summary>完成练习就能赚星星</small></div>"
            "<div class='reward-section'><span class='eyebrow'>星星小卖部</span><div class='reward-shop-grid' data-reward-shop></div></div>"
            "<div hidden data-reward-badges></div>"
            "<div class='reward-section'><span class='eyebrow'>练习日历</span><div class='life-calendar reward-calendar-grid' data-reward-calendar></div>"
            "<small data-reward-streak></small></div>"
            "<div class='reward-section'><span class='eyebrow'>兑换记录</span><div class='reward-history' data-reward-history></div></div>"
            "</section>"
        )
    atomic_tools = _atomic_tools_html(capability)
    composition_module = module_contract(composition_contract, module_id)
    domain_special = _composition_special_surface(composition_module)
    disclosure = str((composition_module or {}).get("default_disclosure") or "summary")
    family = str(module_id).split("-", 1)[0]
    if starter_kinds <= {"question"}:
        starter_note = "答完马上能看对错"
    elif family == "finance":
        starter_note = "记下、勾掉或判断这一笔"
    elif family == "exam":
        starter_note = "今晚就能动手"
    elif family == "education":
        starter_note = "今晚就能练"
    else:
        starter_note = "只留在这台设备"
    residual_compose = family in {
        "exam",
        "finance",
        "household",
        "commerce",
        "research",
        "fitness",
        "teaching",
    }
    compose_open = " open data-compose-default='open'" if disclosure == "open" and not residual_compose else ""
    compose_eyebrow = "自己要留的记录"
    compose_hint = "默认可收起" if compose_open else "按需展开"
    composition_attributes = (
        f" data-composition-surface-template='{_e(composition_module['surface_template_id'])}'"
        f" data-composition-surface-signature='{_e(composition_module['surface_signature'])}'"
        f" data-composition-object-type='{_e(composition_module['object_type_id'])}'"
        f" data-composition-disclosure='{_e(disclosure)}'"
        if composition_module else ""
    )
    generic_open = (
        f"<details class='personal-module-compose personal-collapsible'{compose_open}><summary><span><span class='eyebrow'>{compose_eyebrow}</span>"
        f"<strong>做完今晚这件事，需要留下的再写</strong></span><span>{compose_hint}</span></summary><div class='personal-generic-stack'>"
        if domain_special else ""
    )
    generic_close = "</div></details>" if domain_special else ""
    if module_id == "exam-practice":
        starter_html = (
            f"<section class='starter-surface exam-module-paper' data-starter-root{starter_bindings} "
            f"data-starter-contract-version='{_e(starter['contract_version'])}' "
            f"data-starter-item-count='{len(starter['starter_items'])}'>"
            "<div class='exam-topic-strip' data-exam-topics></div>"
            "<div data-exam-now></div>"
            "<p class='exam-disclaimer'>自编通用题，不是真题，也不保证上岸。</p>"
            "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        )
    elif module_id == "exam-today":
        is_civil = (composition_contract or {}).get("pack", {}).get("scene_profile_id") == "scene.exam-preparation.civil-service-exam"
        if is_civil:
            starter_html = (
                f"<section class='starter-surface exam-module-paper exam-interview-paper' data-starter-root{starter_bindings} "
                f"data-starter-contract-version='{_e(starter['contract_version'])}' "
                f"data-starter-item-count='{len(starter['starter_items'])}'>"
                "<div class='starter-heading'><div><span class='eyebrow'>面试</span>"
                "<h3>抽题、计时、贴转写，再看内容打判</h3></div></div>"
                "<div data-exam-interview-now></div>"
                "<p class='exam-disclaimer'>打判不是过线结论，也不是心理测评。本页可不录音。</p>"
                "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
            )
        else:
            starter_html = (
                f"<section class='starter-surface exam-topic-room' data-starter-root{starter_bindings} "
                f"data-starter-contract-version='{_e(starter['contract_version'])}' "
                f"data-starter-item-count='{len(starter['starter_items'])}'>"
                "<div class='starter-heading'><div><span class='eyebrow'>三科入口</span>"
                "<h3>行测、申论、面试，点进去就开始</h3></div></div>"
                "<div class='starter-content' data-starter-content></div>"
                "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
            )
    elif module_id == "exam-errors":
        starter_html = (
            f"<section class='starter-surface exam-module-paper exam-error-paper' data-starter-root{starter_bindings} "
            f"data-starter-contract-version='{_e(starter['contract_version'])}' "
            f"data-starter-item-count='{len(starter['starter_items'])}'>"
            "<div class='exam-topic-strip' data-exam-error-strip></div>"
            "<div data-exam-error-now></div>"
            "<p class='exam-disclaimer'>回炉只表示错过，不是掌握，更不是排名。</p>"
            "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        )
    elif module_id == "exam-goal":
        starter_html = (
            f"<section class='starter-surface exam-plan-room' data-starter-root{starter_bindings} "
            f"data-starter-contract-version='{_e(starter['contract_version'])}' "
            f"data-starter-item-count='{len(starter['starter_items'])}'>"
            "<div class='starter-heading'><div><span class='eyebrow'>今晚怎么排</span>"
            "<h3>今晚 60 分钟就这三块</h3></div></div>"
            "<div class='starter-content' data-starter-content></div>"
            "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        )
    elif module_id == "exam-materials":
        is_civil = (composition_contract or {}).get("pack", {}).get("scene_profile_id") == "scene.exam-preparation.civil-service-exam"
        if is_civil:
            starter_html = (
                f"<section class='starter-surface exam-write-room exam-shenlun-paper' data-starter-root{starter_bindings} "
                f"data-starter-contract-version='{_e(starter['contract_version'])}' "
                f"data-starter-item-count='{len(starter['starter_items'])}'>"
                "<div class='starter-heading'><div><span class='eyebrow'>申论</span>"
                "<h3>读材料、作答、打判、再改一版</h3></div></div>"
                "<div data-exam-shenlun-now></div>"
                "<p class='exam-disclaimer'>打判看立意、结构和采点，不是阅卷分数，也不保证上岸。</p>"
                "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
            )
        else:
            starter_html = (
                f"<section class='starter-surface exam-write-room' data-starter-root{starter_bindings} "
                f"data-starter-contract-version='{_e(starter['contract_version'])}' "
                f"data-starter-item-count='{len(starter['starter_items'])}'>"
                "<div class='starter-heading'><div><span class='eyebrow'>申论和面试</span>"
                "<h3>先写申论，再开口试。打判还没接上</h3></div></div>"
            "<div class='starter-content' data-starter-content></div>"
            "<p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        )
    else:
        starter_html = (
            f"<section class='starter-surface' data-starter-root{starter_bindings} data-starter-contract-version='{_e(starter['contract_version'])}' "
            f"data-starter-item-count='{len(starter['starter_items'])}'><div class='starter-heading'><div><span class='eyebrow'>打开就能做</span>"
            f"<h3>{_e(starter['summary'])}</h3></div><small>{_e(starter_note)}</small></div>"
            "<div class='starter-content' data-starter-content></div><p class='feedback' data-starter-feedback aria-live='polite'></p></section>"
        )
    return (
        f"<section id='module-{_e(module_id)}' class='app-view workspace module-surface' data-view-id='module-{_e(module_id)}' data-layout-level='module' hidden "
        f"data-double6-module-id='{_e(module_id)}' data-double6-work-object='{_e(capability['work_object_ids'][0])}' "
        f"data-double6-spec-id='{_e(capability['capability_id'])}' data-double6-surface-type='{_e(surface['type'])}' "
        f"data-surface-primitive-id='{_e(surface_primitive_id)}' data-double6-surface-registry-version='{surface['registry_version']}'{composition_attributes}>"
        "<a class='back-dashboard' href='#dashboard'>← 返回首页</a>"
        f"<div class='module-heading'><span class='capability-emoji' data-double6-emoji-role='capability' aria-hidden='true'>{emoji}</span><div><span class='eyebrow'>{_e(_surface_label(str(surface['type']), module_id))}</span>"
        f"<h2>{_e(capability['name'])}</h2><p>{_e(capability.get('description', ''))}</p></div></div>"
        f"{domain_special}{feature_html}"
        f"{starter_html}"
        f"{generic_open}"
        f"{reward_html}"
        f"{atomic_tools}"
        f"{_own_record_heading(module_id)}"
        f"<form data-module-form{work_input_hook}><div class='surface-fields'>{fields}</div><div class='form-actions'>"
        f"<button type='submit' data-module-save{save_hook}>保存记录</button><button type='button' class='secondary' data-module-cancel hidden>取消编辑</button></div></form>"
        f"{filter_box}<p class='feedback' data-module-feedback data-double6-hook='save-success' aria-live='polite'></p><span class='hidden' data-double6-hook='save-error'></span>"
        f"<div class='record-list' data-module-records><p class='empty-record'>先做上面今晚这件事。自己要留的流水，做完再补。</p></div>{generic_close}</section>"
    )


RUNTIME_FRAGMENT_DIR = REFERENCES / "runtimes"
RUNTIME_RENDER_CALLS = {
    "personal-week-runtime-v1": "renderPersonalWeek();document.querySelector('[data-personal-now-content] .primary-cta')?.classList.replace('primary-cta','now-cta');",
    "content-pipeline-runtime-v1": "renderContentPipeline();",
    "sales-pipeline-runtime-v1": "renderSalesPipeline();",
    "object-pipeline-runtime-v1": "renderObjectPipeline();",
    "fitness-daily-runtime-v1": "renderFitnessDaily();",
    "teacher-class-runtime-v1": "renderTeacherClass();",
    "exam-practice-runtime-v1": "renderExamPractice();renderExamErrors();",
    "household-handoff-runtime-v1": "renderHouseholdTonight();",
    "finance-bookkeeping-runtime-v1": "renderFinanceTonight();",
    "commerce-order-runtime-v1": "renderCommerceTonight();",
    "research-evidence-runtime-v1": "renderResearchTonight();",
    "personal-life-runtime-v1": "renderLifeTodayPage();",
    "cet4-sprint-runtime-v1": "renderExamPractice();renderExamErrors();renderCet4Sprint();",
}


def _scene_warmth_js(runtime_id: str) -> str:
    system_id = {
        "fitness-daily-runtime-v1": "fitness-daily-warmth",
        "teacher-class-runtime-v1": "teacher-class-warmth",
        "exam-practice-runtime-v1": "exam-practice-warmth",
        "content-pipeline-runtime-v1": "content-tonight-warmth",
        "sales-pipeline-runtime-v1": "sales-followup-warmth",
        "household-handoff-runtime-v1": "household-handoff-warmth",
        "finance-bookkeeping-runtime-v1": "finance-bookkeeping-warmth",
        "commerce-order-runtime-v1": "commerce-order-warmth",
        "research-evidence-runtime-v1": "research-evidence-warmth",
        "cet4-sprint-runtime-v1": "exam-practice-warmth",
    }.get(runtime_id)
    if not system_id:
        return ""
    library = load_incentive_library()
    row = next((item for item in library["systems"] if item["system_id"] == system_id), {})
    lines = (row.get("skin") or {}).get("lines") or []
    if not isinstance(lines, list) or not lines:
        raise ContractError(f"{system_id} 暖话库为空")
    const_name = {
        "fitness-daily-runtime-v1": "FITNESS_WARMTH_LINES",
        "teacher-class-runtime-v1": "TEACHER_WARMTH_LINES",
        "exam-practice-runtime-v1": "EXAM_WARMTH_LINES",
        "content-pipeline-runtime-v1": "CONTENT_WARMTH_LINES",
        "sales-pipeline-runtime-v1": "SALES_WARMTH_LINES",
        "household-handoff-runtime-v1": "HOUSEHOLD_WARMTH_LINES",
        "finance-bookkeeping-runtime-v1": "FINANCE_WARMTH_LINES",
        "commerce-order-runtime-v1": "COMMERCE_WARMTH_LINES",
        "research-evidence-runtime-v1": "RESEARCH_WARMTH_LINES",
        "cet4-sprint-runtime-v1": "EXAM_WARMTH_LINES",
    }[runtime_id]
    return f"const {const_name}={json.dumps(lines, ensure_ascii=False)};\n"


def _runtime_fragment(runtime_id: str, kind: str) -> str:
    if not runtime_id:
        return ""
    path = RUNTIME_FRAGMENT_DIR / f"{runtime_id}.{kind}.js"
    if not path.is_file():
        raise ContractError(f"runtime 片段缺失：{runtime_id}.{kind}")
    text = path.read_text(encoding="utf-8")
    if runtime_id == "cet4-sprint-runtime-v1":
        base_path = RUNTIME_FRAGMENT_DIR / f"exam-practice-runtime-v1.{kind}.js"
        if not base_path.is_file():
            raise ContractError(f"CET4 基础练习 runtime 缺失：{kind}")
        text = base_path.read_text(encoding="utf-8") + "\n" + text
    if kind != "helpers":
        return text
    shared = RUNTIME_FRAGMENT_DIR / "runtime-policies-v1.helpers.js"
    if not shared.is_file():
        raise ContractError("runtime 策略片段缺失：runtime-policies-v1.helpers")
    prefix = _scene_warmth_js(runtime_id)
    return shared.read_text(encoding="utf-8") + "\n" + prefix + text


_LIFE_HELPERS = r"""
function lifeNumber(value){const number=Number(value);return Number.isFinite(number)?number:0}
function lifeDate(){return localDate()}
function lifeStreak(days){let count=0,cursor=new Date();for(;;){const date=dateKey(cursor);if(!days.has(date))break;count+=1;cursor.setDate(cursor.getDate()-1)}return count}
function renderLifeDashboard(){if(!document.querySelector('.life-dashboard'))return;const finance=appState.modules['life-finance']?.records||[],food=appState.modules['life-food']?.records||[],movement=appState.modules['life-movement']?.records||[],goal=lifeNumber(appState.modules['life-finance']?.starter?.itemStates?.['life-finance-1']?.result),today=lifeDate(),spending=finance.filter(row=>row.values.entry_type==='支出'&&String(row.values.date||today)===today).reduce((sum,row)=>sum+lifeNumber(row.values.amount),0),savings=finance.reduce((sum,row)=>sum+(row.values.entry_type==='存入储蓄'?lifeNumber(row.values.amount):row.values.entry_type==='取出储蓄'?-lifeNumber(row.values.amount):0),0),calories=food.filter(row=>String(row.values.date||today)===today).reduce((sum,row)=>sum+lifeNumber(row.values.calories),0),days=new Set(movement.filter(row=>row.completed).map(row=>localDayOf(row.values.due||row.updatedAt||'')).filter(Boolean)),streak=lifeStreak(days);document.querySelectorAll('[data-life-metric="spending"]').forEach(node=>node.textContent=`¥${spending.toFixed(2)}`);document.querySelectorAll('[data-life-metric="savings"]').forEach(node=>node.textContent=goal?`¥${savings.toFixed(2)} / ¥${goal.toFixed(2)}`:`¥${savings.toFixed(2)}`);document.querySelectorAll('[data-life-goal-progress]').forEach(node=>node.textContent=goal?`目标进度 ${Math.max(0,Math.min(100,savings/goal*100)).toFixed(0)}%`:'尚未设置目标');document.querySelectorAll('[data-life-savings-goal]').forEach(node=>node.value=goal||'');document.querySelectorAll('[data-life-metric="calories"]').forEach(node=>node.textContent=`${Math.round(calories)} kcal`);document.querySelectorAll('[data-life-metric="streak"]').forEach(node=>node.textContent=`${streak} 天`);document.querySelectorAll('[data-life-calendar]').forEach(root=>{const now=new Date(),year=now.getFullYear(),month=now.getMonth(),count=new Date(year,month+1,0).getDate();root.innerHTML=Array.from({length:count},(_,index)=>{const date=`${year}-${String(month+1).padStart(2,'0')}-${String(index+1).padStart(2,'0')}`,done=days.has(date),isToday=date===today;return `<span class="${done?'done ':''}${isToday?'today':''}" title="${date}">${index+1}</span>`}).join('')})}
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


_ATOMIC_LISTENERS = r"""
function factSourceLabel(value){const labels={synthetic_demo:'自编示例，待核实',verified:'已核验',user_local:'本机记录',unverified:'待核实',inferred:'推测，待核实'};return labels[value]||(/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(String(value))?'待核实':String(value||'待核实'))}
function selectedFacts(module){const starter=module.starter.starter_items.map(item=>({factId:item.item_id,text:[item.title,item.body,item.result].filter(Boolean).join(' · '),sourceStatus:item.source_label||'synthetic_demo',sourceRef:item.source_label||null})),records=(appState.modules[module.id]?.records||[]).map(record=>({factId:record.id,text:recordText(record)||'未命名记录',sourceStatus:record.values.source_ref?'verified':'user_local',sourceRef:record.values.source_ref||null}));return [...starter,...records]}
function renderAtomicTools(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"]`);if(!root)return;const factRoot=root.querySelector('[data-draft-facts]');if(factRoot){const facts=selectedFacts(module);factRoot.innerHTML=facts.length?facts.map(fact=>`<label class="atomic-fact"><input type="checkbox" data-draft-fact-id="${attrSafe(fact.factId)}"><span>${escapeHtml(fact.text)}<small>来源状态：${escapeHtml(factSourceLabel(fact.sourceStatus))}</small></span></label>`).join(''):'<p>当前选定模块还没有可用事实。</p>'}}
document.addEventListener('click',event=>{const button=event.target.closest('[data-library-search]');if(!button)return;const root=button.closest('[data-double6-module-id]'),module=moduleById[root.dataset.double6ModuleId],query=(root.querySelector('[data-library-query]').value||'').trim().toLowerCase(),output=root.querySelector('[data-library-results]');if(!query){output.textContent='请输入关键词；空查询不会展开全部资料。';return}const results=selectedFacts(module).filter(fact=>fact.text.toLowerCase().includes(query)).slice(0,20);output.innerHTML=results.length?results.map(fact=>`<article><strong>${escapeHtml(fact.text)}</strong><small>来源状态：${escapeHtml(factSourceLabel(fact.sourceStatus))}</small></article>`).join(''):'选定资料范围内没有匹配项。'});
document.addEventListener('click',event=>{const button=event.target.closest('[data-generate-draft]');if(!button)return;const root=button.closest('[data-double6-module-id]'),module=moduleById[root.dataset.double6ModuleId],selected=[...root.querySelectorAll('[data-draft-fact-id]:checked')].map(node=>node.dataset.draftFactId),facts=selectedFacts(module),chosen=facts.filter(fact=>selected.includes(fact.factId)),output=root.querySelector('[data-draft-output]');if(!chosen.length){output.textContent='先选择至少一条当前模块事实。';return}output.textContent=['草稿｜待人工审核',...chosen.map((fact,index)=>`${index+1}. ${fact.text}（${fact.sourceRef||'[来源缺口：发布前补充]'}）`),'状态：尚未发送或发布，必须人工审核。'].join('\n')});
document.addEventListener('click',event=>{const button=event.target.closest('[data-metric-summary]');if(!button)return;const root=button.closest('[data-double6-module-id]'),id=root.dataset.double6ModuleId,method=root.querySelector('[data-metric-method]').value,rows=(appState.modules[id]?.records||[]).filter(record=>Number.isFinite(Number(record.values.value))),output=root.querySelector('[data-metric-output]');if(!rows.length){output.textContent='数据不足：没有可汇总的事实样本。';return}const first=rows[0],metric=String(first.values.metric||''),unit=String(first.values.unit||'unitless'),selected=rows.filter(record=>String(record.values.metric||'')===metric&&String(record.values.unit||'unitless')===unit);if(selected.length!==rows.length){output.textContent='口径不一致：请按指标和单位分开汇总。';return}const values=selected.map(record=>Number(record.values.value)),value=method==='sum'?values.reduce((sum,row)=>sum+row,0):method==='average'?values.reduce((sum,row)=>sum+row,0)/values.length:Number([...selected].sort((a,b)=>String(b.values.date||'').localeCompare(String(a.values.date||'')))[0].values.value),sources=selected.map(record=>record.id);output.textContent=`${metric}：${value} ${unit}；方法 ${method}；来源状态：人工录入/未核验；来源样本 ${sources.join('、')}`});
document.addEventListener('click',event=>{const button=event.target.closest('[data-handoff-preview]');if(!button)return;const root=button.closest('[data-double6-module-id]'),target=root.querySelector('[data-handoff-target]').value.trim(),payload=root.querySelector('[data-handoff-payload]').value.trim(),impact=root.querySelector('[data-handoff-impact]').value.trim(),output=root.querySelector('[data-handoff-output]'),confirmButton=root.querySelector('[data-handoff-confirm]');if(!target||!payload||!impact){output.textContent='目标、载荷预览和影响都必须明确；当前未执行。';confirmButton.hidden=true;return}root.__double6Handoff={target,payload,impact};output.textContent=`交接预览｜目标：${target}｜影响：${impact}｜状态：未执行`;confirmButton.hidden=false});
document.addEventListener('click',event=>{const button=event.target.closest('[data-handoff-confirm]');if(!button)return;const root=button.closest('[data-double6-module-id]'),draft=root.__double6Handoff;if(!draft){button.hidden=true;return}const id=root.dataset.double6ModuleId,next=clone(appState),intentId=`handoff-${Date.now()}`;next.workflowIntents.handoffs[intentId]={...draft,moduleId:id,externalStatus:'not_executed',confirmedAt:new Date().toISOString()};try{persist(next);appState=next;root.querySelector('[data-handoff-output]').textContent='已保存人工交接；外部状态：未执行。请在外部渠道另行操作并保留真实回执。';button.hidden=true}catch(error){root.querySelector('[data-handoff-output]').textContent='交接保存失败；当前未执行任何外部操作。'}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-record-action="local-reminder"]');if(!button)return;const id=button.dataset.reminderModuleId,recordId=button.dataset.reminderRecordId,record=appState.modules[id]?.records?.find(row=>row.id===recordId),due=String(record?.values?.due||'');if(!record||!/^\d{4}-\d{2}-\d{2}$/.test(due)){feedback(id,'先给这条记录填写有效日期；没有登记提醒。',true);return}const next=clone(appState);next.workflowIntents.reminders[recordId]={targetRecordId:recordId,remindAt:`${due}T09:00`,messageDraft:recordText(record),externalStatus:'not_executed',savedAt:new Date().toISOString()};try{persist(next);appState=next;if(typeof Notification!=='undefined'&&Notification.permission==='denied'){markCapability('reminder','declined','系统通知已被拒绝。本地提醒意图仍可记下。','要弹通知需在浏览器设置里允许，或继续只用本机记录。');feedback(id,'已登记本地提醒意图；系统通知已关闭，没有发出通知。')}else{markCapability('reminder','ready','','');feedback(id,'已登记本地提醒意图；没有发送通知，目标记录保持不变。')}}catch(error){feedback(id,'提醒意图保存失败；目标记录未改动。',true)}});
function renderSelectedCsvFields(){const select=document.querySelector('[data-csv-module]'),root=document.querySelector('[data-csv-fields]');if(!select||!root)return;const module=moduleById[select.value];root.innerHTML=module.fields.map(field=>`<label class="atomic-fact"><input type="checkbox" data-csv-field-id="${attrSafe(field.field_id)}"><span>${escapeHtml(field.label)}</span></label>`).join('')}
document.querySelector('[data-csv-module]')?.addEventListener('change',renderSelectedCsvFields);
document.querySelector('[data-double6-hook="export-selected-csv"]')?.addEventListener('click',()=>{const select=document.querySelector('[data-csv-module]'),output=document.querySelector('[data-selected-csv-output]'),module=select&&moduleById[select.value],fields=[...document.querySelectorAll('[data-csv-field-id]:checked')].map(node=>node.dataset.csvFieldId);if(!module||!fields.length){output.textContent='至少明确选择一个当前模块字段；没有生成文件。';return}const quote=value=>{let text=String(value??'');if(/^[=+\-@]/.test(text))text=`'${text}`;return `"${text.replaceAll('"','""')}"`},rows=appState.modules[module.id].records,csv=['\ufeff'+fields.map(quote).join(','),...rows.map(record=>fields.map(field=>quote(record.values[field])).join(','))].join('\n'),blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${PRODUCT_ID}-${module.id}-selected.csv`;link.click();URL.revokeObjectURL(link.href);output.textContent=`已导出 ${module.name} 的 ${fields.length} 个选定字段、${rows.length} 条记录。`});
document.addEventListener('submit',event=>{if(event.target.matches('[data-module-form]'))setTimeout(()=>MODULES.forEach(row=>renderAtomicTools(row.id)),0)});
document.addEventListener('click',event=>{if(event.target.closest('[data-record-action]'))setTimeout(()=>MODULES.forEach(row=>renderAtomicTools(row.id)),0)});
renderSelectedCsvFields();
"""


def _script(product: dict[str, Any], capabilities: list[dict[str, Any]], storage_key: str) -> str:
    modules = [{
        "id": row["recommendation_module_id"], "name": row["name"], "type": row["surface"]["type"],
        "fields": row["surface"]["fields"], "operations": row["surface"]["operations"],
        "starter": row["starter"], "rewards": row.get("reward_economy"),
        "atoms": list(row.get("atomic_capability_ids", [])),
    } for row in capabilities]
    finance_module_ids = [
        row["recommendation_module_id"]
        for row in capabilities
        if {"entry_type", "amount"} <= {field["field_id"] for field in row["surface"]["fields"]}
    ]
    source = r"""
const STORAGE_KEY=__STORAGE_KEY__,PRODUCT_ID=__PRODUCT_ID__,PACK_ID=__PACK_ID__,COMPOSITION_ID=__COMPOSITION_ID__,MODULES=__MODULES__,FINANCE_MODULE_IDS=__FINANCE_MODULE_IDS__,LEDGER_CSV_SPECS=__LEDGER_CSV_SPECS__;
const MAX_IMPORT_BYTES=8*1024*1024,MAX_RECORDS_PER_MODULE=2000,WORKSPACE_CONTRACT='double6_workspace_v1',MAX_WORKSPACE_SNAPSHOTS=5,MAX_IMPORT_LOG=10;
const moduleById=Object.fromEntries(MODULES.map(row=>[row.id,row]));
const emptyStarterState=()=>({itemStates:{},questionIndex:0,promptIndex:null,answers:{},mistakes:[],lastResult:null});
const emptyRewards=()=>({stars:0,earnedTotal:0,generatorCorrect:0,awardedItems:[],days:{},redeemed:[],badges:[],dailyGenerator:{date:'',count:0}});
const emptyOwnership=()=>({kind:'device_local',namespace:STORAGE_KEY,sync:'not_connected'});
const emptyCapabilities=()=>({storage:{status:'ready',reason:'',repair:'',updatedAt:''},import_export:{status:'ready',reason:'',repair:'',updatedAt:''},clipboard:{status:'ready',reason:'',repair:'',updatedAt:''},reminder:{status:'ready',reason:'',repair:'',updatedAt:''}});
const emptyState=()=>({schemaVersion:4,contractVersion:WORKSPACE_CONTRACT,productId:PRODUCT_ID,packId:PACK_ID,compositionId:COMPOSITION_ID,ownership:emptyOwnership(),modules:Object.fromEntries(MODULES.map(row=>[row.id,{records:[],starter:emptyStarterState()}])),rewards:emptyRewards(),workflowIntents:{reminders:{},handoffs:{}},legacyImport:null,snapshots:[],runtimeCapabilities:emptyCapabilities(),firstRunSeen:false,importLog:[],storageBackend:'localStorage',updatedAt:new Date().toISOString()});
const clone=value=>JSON.parse(JSON.stringify(value));let appState=emptyState(),lastImportBackup=null,pendingImportState=null,pendingImportMeta=null;
const workspacePayload=state=>{const copy=clone(state);delete copy.snapshots;delete copy.runtimeCapabilities;delete copy.storageBackend;return copy};
const recordCount=state=>MODULES.reduce((total,module)=>total+(state.modules[module.id]?.records||[]).length,0);
function packCompat(sourcePack,sourceModules){const sourceSet=new Set(sourceModules||[]),unmapped=[...sourceSet].filter(id=>!moduleById[id]);if(sourcePack&&sourcePack===PACK_ID)return {status:'same',note:'同一套工作台，可直接恢复。'};if(unmapped.length)return {status:'migrated_with_unmapped',note:'工作台版本不同。对得上的模块会迁上来，其余进未映射区，不会悄悄丢掉。'};if(sourcePack&&sourcePack!==PACK_ID)return {status:'migrated',note:'工作台版本不同，模块都能对上，可以迁上来。'};return {status:'unknown',note:'没有版本标记，按字段尽量迁上来。'}}
function captureSnapshot(reason){const item={snapshotId:`s-${Date.now()}-${Math.random().toString(16).slice(2)}`,createdAt:new Date().toISOString(),reason:String(reason||'before_import').slice(0,40),recordCount:recordCount(appState),packId:appState.packId||PACK_ID,schemaVersion:appState.schemaVersion||4,moduleIds:MODULES.map(row=>row.id),workspace:workspacePayload(appState)};return [item,...(Array.isArray(appState.snapshots)?appState.snapshots:[])].slice(0,MAX_WORKSPACE_SNAPSHOTS)}
function snapshotReasonLabel(reason){return ({before_import:'导入前',before_clear:'清空前',before_restore:'恢复前'})[reason]||'恢复点'}
function renderSnapshots(){const root=document.querySelector('[data-snapshot-list]');if(!root)return;const items=Array.isArray(appState.snapshots)?appState.snapshots:[];if(!items.length){root.innerHTML='<p class="empty-record">还没有恢复点。确认导入或清空前会自动留下一条。</p>';return}root.innerHTML=items.map(item=>{const compat=packCompat(item.packId||item.workspace?.packId||'',item.moduleIds||Object.keys(item.workspace?.modules||{}));return `<article class="record" data-snapshot-id="${attrSafe(item.snapshotId)}" data-pack-status="${compat.status}"><div><strong>${escapeHtml(snapshotReasonLabel(item.reason))}</strong><small>${escapeHtml(item.createdAt)} · ${item.recordCount} 条记录 · 合同 v${escapeHtml(item.schemaVersion||4)}</small><small>${escapeHtml(item.packId||PACK_ID)} · ${escapeHtml(compat.note)}</small></div><div class="record-actions"><button type="button" class="tiny" data-restore-snapshot="${attrSafe(item.snapshotId)}">恢复到这时</button></div></article>`}).join('')}
function renderImportLog(){const root=document.querySelector('[data-import-log-list]');if(!root)return;const items=Array.isArray(appState.importLog)?appState.importLog:[];if(!items.length){root.innerHTML='<p class="empty-record">还没有导入记录。确认导入后会留下来源、时间和改了哪些模块。</p>';return}root.innerHTML=items.map(item=>{const changed=(item.changedModules||[]).map(row=>`${row.module_id||row.name||''} ${row.before}→${row.after}`).filter(Boolean).join('；');return `<article class="record" data-import-log-at="${attrSafe(item.importedAt||'')}"><div><strong>${escapeHtml(item.sourceName||'未命名备份')}</strong><small>${escapeHtml(item.importedAt||'')} · 隔离 ${item.quarantineCount||0} 项</small><small>${escapeHtml(changed||'记录数无变化')}</small><small>${escapeHtml(item.packNote||'')}</small></div></article>`}).join('')}
function capabilityLabel(status){return ({ready:'可用',broken:'不可用',declined:'已关闭',stale:'待复查'})[status]||'待复查'}
function markCapability(id,status,reason,repair){const caps=appState.runtimeCapabilities||emptyCapabilities();caps[id]={status,reason:String(reason||'').slice(0,200),repair:String(repair||'').slice(0,200),updatedAt:new Date().toISOString()};appState.runtimeCapabilities=caps;renderCapabilityDoctor();return caps}
function renderFirstRun(){const root=document.querySelector('[data-first-run]');if(!root)return;if(document.querySelector('[data-exam-practice-board]')){root.hidden=true;return}const seen=Boolean(appState.firstRunSeen),empty=!recordCount(appState),hash=location.hash||'#dashboard',onHome=hash==='#'||hash==='#dashboard';root.hidden=seen||!empty||!onHome}
const ADULT_WARMTH_LINES=['今天先做最上面那一件就好。','来了就算开始，不必一次做完。','记下的都还在这台设备上。','做完一件，再决定下一件。','慢慢来，页面会等你。'];
function renderAdultWarmth(){const root=document.querySelector('[data-adult-warmth]');if(!root)return;if(document.querySelector('.child-dashboard,.child-layout,[data-fitness-daily-board],[data-teacher-class-board],[data-exam-practice-board],[data-content-tonight-board],[data-sales-tonight-board],[data-household-tonight-board],[data-finance-tonight-board],[data-commerce-tonight-board],[data-research-tonight-board]')){root.hidden=true;return}const now=new Date(),key=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;let acc=0;for(const ch of key)acc+=ch.charCodeAt(0);root.hidden=false;root.textContent=ADULT_WARMTH_LINES[acc%ADULT_WARMTH_LINES.length]}
function renderCapabilityDoctor(){const root=document.querySelector('[data-capability-doctor]');if(!root)return;const caps=appState.runtimeCapabilities||emptyCapabilities(),catalog=[{id:'storage',title:'本机保存',required:true},{id:'import_export',title:'导入导出',required:true},{id:'clipboard',title:'复制到剪贴板',required:false},{id:'reminder',title:'本地提醒',required:false}];root.innerHTML=catalog.map(row=>{const cap=caps[row.id]||{status:'ready',reason:'',repair:''},optional=row.required?'':`<button type="button" class="tiny" data-decline-capability="${row.id}">${cap.status==='declined'?'重新启用':'先不用'}</button>`;return `<article class="record" data-capability-id="${row.id}" data-capability-status="${cap.status}"><div><strong>${escapeHtml(row.title)} · ${capabilityLabel(cap.status)}</strong><small>${escapeHtml(cap.reason||(cap.status==='ready'?'当前可用。':''))}</small>${cap.repair?`<small>${escapeHtml(cap.repair)}</small>`:''}</div><div class="record-actions">${optional}</div></article>`}).join('');const degraded=catalog.filter(row=>caps[row.id]&&caps[row.id].status!=='ready'),summary=document.querySelector('[data-capability-degraded]');if(summary){summary.hidden=!degraded.length;if(degraded.length)summary.textContent=`当前降级：${degraded.map(row=>`${row.title}（${capabilityLabel(caps[row.id].status)}）`).join('；')}。记录和本机工作仍可继续，只是这些能力按上面的说明处理。`}}
function probeCapabilities(){const caps=appState.runtimeCapabilities||emptyCapabilities();appState.runtimeCapabilities=caps;if(!(window.FileReader&&window.Blob&&window.URL&&typeof URL.createObjectURL==='function')){if(caps.import_export.status!=='declined')markCapability('import_export','broken','当前浏览器不能生成或读取备份文件。','换一个现代浏览器，或请别人帮你导出。')}if(!(navigator.clipboard&&typeof navigator.clipboard.writeText==='function')){if(caps.clipboard.status!=='declined')markCapability('clipboard','broken','当前环境没有剪贴板接口。','用导出备份代替复制，或换浏览器。')}if(typeof Notification!=='undefined'&&Notification.permission==='denied'&&caps.reminder.status!=='declined')markCapability('reminder','declined','系统通知已被拒绝。本地提醒意图仍可记下。','要弹通知需在浏览器设置里允许，或继续只用本机记录。')}
const feedback=(id,message,error=false)=>{const node=document.querySelector(`[data-double6-module-id="${id}"] [data-module-feedback]`);if(node){node.textContent=message;node.className=`feedback ${error?'error':'success'}`}};
const dataFeedback=(message,error=false)=>{const node=document.querySelector('[data-double6-hook="data-feedback"]');if(node){node.textContent=message;node.className=`feedback ${error?'error':'success'}`}};
function safeRecord(module,record,index,quarantine){if(!record||typeof record!=='object'){quarantine.push(record);return null}const fields=new Map(module.fields.map(row=>[row.field_id,row])),values={};for(const [key,raw] of Object.entries(record.values||{})){const field=fields.get(key);if(!field)continue;if(field.type==='boolean')values[key]=Boolean(raw);else if(field.type==='number'){const number=Number(raw);values[key]=Number.isFinite(number)?number:''}else values[key]=String(raw??'').slice(0,10000)}const rawId=String(record.id||''),id=/^r-[a-zA-Z0-9._-]{1,120}$/.test(rawId)?rawId:`r-import-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`,links=(Array.isArray(record.links)?record.links:[]).filter(link=>link&&moduleById[String(link.sourceModuleId)]&&/^r-[a-zA-Z0-9._-]{1,120}$/.test(String(link.sourceRecordId||''))).slice(0,20).map(link=>({sourceModuleId:String(link.sourceModuleId),sourceRecordId:String(link.sourceRecordId),relation:String(link.relation||'related').slice(0,80)}));if(id!==rawId||Object.keys(record).some(key=>!['id','values','links','completed','archived','createdAt','updatedAt'].includes(key)))quarantine.push(clone(record));return {id,values,links,completed:Boolean(record.completed),archived:Boolean(record.archived),createdAt:String(record.createdAt||''),updatedAt:String(record.updatedAt||'')}}
function safeStarter(module,raw){
  const next=emptyStarterState(),known=new Set(module.starter.starter_items.map(item=>item.item_id));
  if(!raw||typeof raw!=='object')return next;
  for(const [itemId,itemState] of Object.entries(raw.itemStates||{})){
    if(known.has(itemId)&&itemState&&typeof itemState==='object'){
      const kept={status:String(itemState.status||'').slice(0,30),result:String(itemState.result||'').slice(0,1000),updatedAt:String(itemState.updatedAt||''),cycleKey:String(itemState.cycleKey||'').slice(0,30)};
      if(itemState.drafts&&typeof itemState.drafts==='object'){const drafts={};Object.entries(itemState.drafts).slice(0,8).forEach(([key,value])=>{drafts[String(key).slice(0,40)]=String(value??'').slice(0,2000)});kept.drafts=drafts}
      if(typeof itemState.draft==='string')kept.draft=itemState.draft.slice(0,12000);
      if(Object.prototype.hasOwnProperty.call(itemState,'reviewed'))kept.reviewed=Boolean(itemState.reviewed);
      next.itemStates[itemId]=kept
    }
  }
  for(const [itemId,answer] of Object.entries(raw.answers||{})){if(known.has(itemId)&&answer&&typeof answer==='object')next.answers[itemId]={value:String(answer.value??'').slice(0,1000),correct:Boolean(answer.correct),updatedAt:String(answer.updatedAt||'')}}
  next.mistakes=Array.isArray(raw.mistakes)?[...new Set(raw.mistakes.map(String).filter(id=>known.has(id)))]:[];
  next.questionIndex=Math.max(0,Math.min(Number(raw.questionIndex)||0,module.starter.starter_items.length-1));
  next.promptIndex=Number.isInteger(raw.promptIndex)&&raw.promptIndex>=0?raw.promptIndex:null;
  if(raw.lastResult&&typeof raw.lastResult==='object')next.lastResult={itemId:known.has(String(raw.lastResult.itemId))?String(raw.lastResult.itemId):'',message:String(raw.lastResult.message||'').slice(0,1000),updatedAt:String(raw.lastResult.updatedAt||'')};
  if(/^\d{4}-\d{2}-\d{2}$/.test(String(raw.examDate||'')))next.examDate=String(raw.examDate);
  if(raw.factGoal&&typeof raw.factGoal==='object')next.factGoal={target:Math.max(0,Number(raw.factGoal.target)||0),current:Math.max(0,Number(raw.factGoal.current)||0),deadline:/^\d{4}-\d{2}-\d{2}$/.test(String(raw.factGoal.deadline||''))?String(raw.factGoal.deadline):'',reward:String(raw.factGoal.reward||'').slice(0,160),updatedAt:String(raw.factGoal.updatedAt||'')};
  if(raw.timer&&typeof raw.timer==='object'&&['idle','running','paused','completed'].includes(String(raw.timer.status||'')))next.timer={status:String(raw.timer.status),durationMs:Math.max(1000,Math.min(Number(raw.timer.durationMs)||1500000,86400000)),pausedRemainingMs:Math.max(0,Math.min(Number(raw.timer.pausedRemainingMs)||0,86400000)),startedAt:raw.timer.startedAt?String(raw.timer.startedAt).slice(0,40):null};
  return next
}
function safeRewards(raw){const next=emptyRewards();if(!raw||typeof raw!=='object')return next;const clampInt=value=>{const number=Math.floor(Number(value));return Number.isFinite(number)?Math.max(0,Math.min(number,1000000)):0};next.stars=clampInt(raw.stars);next.earnedTotal=clampInt(raw.earnedTotal);next.generatorCorrect=clampInt(raw.generatorCorrect);next.awardedItems=Array.isArray(raw.awardedItems)?[...new Set(raw.awardedItems.map(value=>String(value).slice(0,200)))].slice(0,2000):[];if(raw.days&&typeof raw.days==='object'){for(const key of Object.keys(raw.days).slice(0,400)){if(/^\d{4}-\d{2}-\d{2}$/.test(key)&&raw.days[key])next.days[key]=true}}next.redeemed=(Array.isArray(raw.redeemed)?raw.redeemed:[]).slice(0,500).filter(entry=>entry&&typeof entry==='object').map(entry=>({title:String(entry.title||'').slice(0,200),cost:clampInt(entry.cost),date:String(entry.date||'').slice(0,10),at:String(entry.at||'').slice(0,40)}));next.badges=Array.isArray(raw.badges)?[...new Set(raw.badges.map(value=>String(value).slice(0,100)))].slice(0,200):[];const daily=raw.dailyGenerator;if(daily&&typeof daily==='object')next.dailyGenerator={date:String(daily.date||'').slice(0,10),count:clampInt(daily.count)};return next}
function normalize(value,options){const next=emptyState(),keepSnapshots=Boolean(options&&options.keepSnapshots);if(value&&[2,3,4].includes(value.schemaVersion)&&value.productId===PRODUCT_ID&&value.modules&&typeof value.modules==='object'){const knownModuleIds=new Set(MODULES.map(row=>row.id)),retainedModules=value.legacyImport?.unmapped?.modules&&typeof value.legacyImport.unmapped.modules==='object'?value.legacyImport.unmapped.modules:{},unknownModules={...Object.fromEntries(Object.entries(retainedModules).filter(([id])=>!knownModuleIds.has(id))),...Object.fromEntries(Object.entries(value.modules).filter(([id])=>!knownModuleIds.has(id)))},moduleExtras={},quarantinedRecords={};MODULES.forEach(module=>{const source=value.modules[module.id]||retainedModules[module.id],rows=Array.isArray(source?.records)?source.records:[];if(rows.length>MAX_RECORDS_PER_MODULE)throw new Error(`模块 ${module.name} 的记录超过 ${MAX_RECORDS_PER_MODULE} 条`);const quarantine=[];next.modules[module.id]={records:rows.map((record,index)=>safeRecord(module,record,index,quarantine)).filter(Boolean),starter:safeStarter(module,source?.starter)};if(quarantine.length)quarantinedRecords[module.id]=quarantine;if(source&&typeof source==='object'){const extra=Object.fromEntries(Object.entries(source).filter(([key])=>!['records','starter'].includes(key)));if(Object.keys(extra).length)moduleExtras[module.id]=extra}});const known=new Set(['schemaVersion','productId','packId','compositionId','modules','rewards','workflowIntents','legacyImport','updatedAt','contractVersion','ownership','snapshots','runtimeCapabilities','firstRunSeen','importLog','storageBackend','packMigration']),unknown=Object.fromEntries(Object.entries(value).filter(([key])=>!known.has(key)));next.rewards=safeRewards(value.rewards);next.contractVersion=WORKSPACE_CONTRACT;next.ownership=emptyOwnership();next.firstRunSeen=Boolean(value.firstRunSeen);next.importLog=Array.isArray(value.importLog)?value.importLog.filter(item=>item&&typeof item==='object').slice(0,MAX_IMPORT_LOG):[];next.packMigration=value.packId&&value.packId!==PACK_ID?packCompat(value.packId,Object.keys(value.modules||{})):null;if(value.ownership&&value.ownership.kind==='device_local'&&value.ownership.namespace)next.ownership.namespace=String(value.ownership.namespace);if(keepSnapshots){next.snapshots=(Array.isArray(value.snapshots)?value.snapshots:[]).filter(item=>item&&typeof item==='object'&&String(item.snapshotId||'').startsWith('s-')&&item.workspace&&typeof item.workspace==='object').slice(0,MAX_WORKSPACE_SNAPSHOTS).map(item=>({snapshotId:String(item.snapshotId).slice(0,80),createdAt:String(item.createdAt||''),reason:String(item.reason||'before_import').slice(0,40),recordCount:Number(item.recordCount)||0,packId:String(item.packId||item.workspace?.packId||PACK_ID),schemaVersion:Number(item.schemaVersion)||4,moduleIds:Array.isArray(item.moduleIds)?item.moduleIds.map(String):Object.keys(item.workspace?.modules||{}),workspace:workspacePayload(item.workspace)}));if(value.runtimeCapabilities&&typeof value.runtimeCapabilities==='object'){const kept=emptyCapabilities();['storage','import_export','clipboard','reminder'].forEach(id=>{const row=value.runtimeCapabilities[id];if(row&&['ready','broken','declined','stale'].includes(row.status))kept[id]={status:row.status,reason:String(row.reason||'').slice(0,200),repair:String(row.repair||'').slice(0,200),updatedAt:String(row.updatedAt||'')}});next.runtimeCapabilities=kept}}if(value.workflowIntents&&typeof value.workflowIntents==='object'){const reminders=value.workflowIntents.reminders,handoffs=value.workflowIntents.handoffs;next.workflowIntents.reminders=reminders&&typeof reminders==='object'?clone(reminders):{};next.workflowIntents.handoffs=handoffs&&typeof handoffs==='object'?clone(handoffs):{}}next.legacyImport=value.legacyImport||null;if(next.legacyImport?.unmapped?.modules)next.legacyImport.unmapped.modules=unknownModules;if(Object.keys(unknown).length||Object.keys(unknownModules).length||Object.keys(moduleExtras).length||Object.keys(quarantinedRecords).length)next.legacyImport={...(next.legacyImport||{}),unmapped:{...(next.legacyImport?.unmapped||{}),envelope:unknown,modules:unknownModules,moduleExtras,quarantinedRecords}}}else if(value&&typeof value==='object'){next.legacyImport={notes:typeof value.value==='string'?value.value.slice(0,10000):'',completedItemIds:Array.isArray(value.checked)?value.checked.map(String).slice(0,500):[],unmapped:clone(value),importedAt:new Date().toISOString()}}else throw new Error('备份格式无效');next.updatedAt=new Date().toISOString();return applyTonightSeeds(next)}
function openWorkspaceDB(){return new Promise((resolve,reject)=>{const req=indexedDB.open('double6-workspace-v1',1);req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains('kv'))req.result.createObjectStore('kv')};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error)})}
function indexedDBExists(){if(!window.indexedDB||typeof indexedDB.databases!=='function')return Promise.resolve(false);return indexedDB.databases().then(rows=>(rows||[]).some(row=>row&&row.name==='double6-workspace-v1')).catch(()=>false)}
function writeIndexedDB(text){return openWorkspaceDB().then(db=>new Promise((resolve,reject)=>{const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(text,STORAGE_KEY);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)}))}
function readIndexedDB(){return openWorkspaceDB().then(db=>new Promise((resolve,reject)=>{const tx=db.transaction('kv','readonly');const req=tx.objectStore('kv').get(STORAGE_KEY);req.onsuccess=()=>resolve(req.result||null);req.onerror=()=>reject(req.error)}))}
function persist(next){next.updatedAt=new Date().toISOString();next.runtimeCapabilities=appState.runtimeCapabilities||emptyCapabilities();next.importLog=Array.isArray(next.importLog)?next.importLog:appState.importLog||[];const text=JSON.stringify(next);try{localStorage.setItem(STORAGE_KEY,text);next.storageBackend='localStorage';if(next.runtimeCapabilities.storage.status!=='ready'&&next.runtimeCapabilities.storage.reason.indexOf('大容量')<0){next.runtimeCapabilities={...next.runtimeCapabilities,storage:{status:'ready',reason:'',repair:'',updatedAt:new Date().toISOString()}};appState.runtimeCapabilities=next.runtimeCapabilities;localStorage.setItem(STORAGE_KEY,JSON.stringify(next));renderCapabilityDoctor()}}catch(error){const quota=error&&(error.name==='QuotaExceededError'||/quota/i.test(String(error.message||error)));if(quota&&window.indexedDB){next.storageBackend='indexeddb';writeIndexedDB(text).then(()=>markCapability('storage','ready','本机空间不够，已改用大容量存储。','')).catch(()=>markCapability('storage','broken','大容量存储也写不进去。','先导出备份，再删掉不用的记录。'));markCapability('storage','ready','本机空间不够，已改用大容量存储。','');return}markCapability('storage','broken',quota?'当前设备存储已满，没法再写入。':'浏览器拒绝写入本机存储。',quota?'先导出备份，再删掉不用的记录后重试。':'检查是否关闭了网站数据，或换一个浏览器再试。');throw error}}
function persistOrRestore(next){const previous=localStorage.getItem(STORAGE_KEY);try{persist(next)}catch(error){try{if(previous==null)localStorage.removeItem(STORAGE_KEY);else localStorage.setItem(STORAGE_KEY,previous)}catch(ignored){}throw error}}
function recordText(record){return Object.values(record.values||{}).filter(value=>value!==false&&value!=null).join(' · ')}
function escapeHtml(value){const node=document.createElement('span');node.textContent=String(value);return node.innerHTML}
function attrSafe(value){return escapeHtml(value).replace(/"/g,'')}
function d6SpeakLang(text){const han=/[\u4e00-\u9fff]/.test(text),latin=/[A-Za-z]/.test(text);if(latin&&!han)return'en-US';if(han&&!latin)return'zh-CN';return han?'zh-CN':'en-US'}
function d6VoiceScore(voice,lang){const low=String(voice.name||'').toLowerCase(),vlang=String(voice.lang||'').toLowerCase().replace('_','-'),want=String(lang||'').toLowerCase(),pref=want.slice(0,2),zh=want.startsWith('zh');if(/compact|novelty|bad news|good news|bells|boing|cellos|zarvox|whisper|albert|trinoids|organ|princess|superstar|jester|junior|kathy|fred|pipe organ/.test(low))return-80;let score=0;if(vlang===want)score+=10;else if(vlang.startsWith(pref))score+=6;else score-=24;if(/google/.test(low)&&(zh?/普通话|中国|chinese/.test(low+vlang):/us english|uk english|english|en-/.test(low+vlang)))score+=24;if(/online|natural|neural|enhanced|premium|siri/.test(low))score+=12;if(voice.localService===false)score+=4;if(zh){if(/xiaoxiao|xiaoyi|yunxi|yunyang|yunjian|huihui|yaoyao|kangkang/.test(low))score+=18;if(/meijia/.test(low))score+=8;if(/ting-ting|tingting/.test(low)&&!/enhanced|premium/.test(low))score+=1;if(/microsoft/.test(low))score+=3}else{if(/samantha|aria|jenny|guy|emma|andrew|michelle|sonia|libby/.test(low))score+=18;if(/microsoft/.test(low))score+=4;if(/^alex$|alex \(/.test(low))score+=2}return score}
function d6PickVoice(lang){const voices=window.speechSynthesis.getVoices()||[];if(!voices.length)return null;let best=null,bestScore=-1;voices.forEach(voice=>{const score=d6VoiceScore(voice,lang);if(score>bestScore){best=voice;bestScore=score}});return bestScore>=0?best:null}
function d6Speak(text,lang){text=String(text||'').trim();if(!text)return false;if(!('speechSynthesis' in window))return false;const synth=window.speechSynthesis;synth.cancel();lang=String(lang||'').trim()||d6SpeakLang(text);const speak=()=>{const utterance=new SpeechSynthesisUtterance(text);utterance.lang=lang;utterance.rate=lang.startsWith('en')?(text.length<=4?.86:.92):(lang.startsWith('zh')?.92:.95);utterance.pitch=1;const voice=d6PickVoice(lang);if(voice){utterance.voice=voice;utterance.lang=voice.lang||lang}synth.speak(utterance)};if((synth.getVoices()||[]).length){speak();return true}const once=()=>{synth.removeEventListener('voiceschanged',once);speak()};synth.addEventListener('voiceschanged',once);setTimeout(()=>{synth.removeEventListener('voiceschanged',once);if(!synth.speaking)speak()},700);return true}
function actionButtons(module,record){let extra='';if(module.operations.includes('complete'))extra+=`<button type="button" class="tiny" data-record-action="toggle-complete">${record.completed?'撤销完成':'完成'}</button>`;if(module.operations.includes('archive'))extra+=`<button type="button" class="tiny" data-record-action="toggle-archive">${record.archived?'恢复':'停用/归档'}</button>`;if(module.operations.includes('move'))extra+='<button type="button" class="tiny" data-record-action="move">推进阶段</button>';if(module.id==='personal-inbox'&&!record.archived)extra+=`<button type="button" class="tiny" data-personal-action="promote-week" data-personal-record-id="${attrSafe(record.id)}">排进本周</button>`;if(module.id==='personal-week-plan'&&!record.archived&&!record.completed)extra+=`<button type="button" class="tiny" data-personal-action="plan-today" data-personal-record-id="${attrSafe(record.id)}">安排到今天</button>`;if(module.id==='personal-projects'&&!record.archived&&!record.completed)extra+=`<button type="button" class="tiny" data-personal-action="project-today" data-personal-record-id="${attrSafe(record.id)}">下一步放到今天</button>`;if(module.id==='personal-today'&&!record.archived&&!record.completed)extra+=`<button type="button" class="tiny" data-personal-action="tomorrow" data-personal-record-id="${attrSafe(record.id)}">顺延一天</button>`;if(module.atoms.includes('atom.shared.schedule-reminder'))extra+=`<button type="button" class="tiny" data-record-action="local-reminder" data-reminder-module-id="${attrSafe(module.id)}" data-reminder-record-id="${attrSafe(record.id)}">登记本地提醒</button>`;return `${extra}<button type="button" class="tiny" data-record-action="edit">编辑</button><button type="button" class="tiny danger" data-record-action="delete">删除</button>`}
function currentWeekKey(){const today=localDate(),date=new Date(`${today}T00:00:00`),offset=(date.getDay()+6)%7;date.setDate(date.getDate()-offset);return dateKey(date)}
function effectiveStarterState(item,state){const row=state.itemStates[item.item_id];return item.recurrence==='weekly'&&row?.cycleKey!==currentWeekKey()?null:row}
function activeStarterStates(module){const state=appState.modules[module.id].starter;return module.starter.starter_items.map(item=>effectiveStarterState(item,state)).filter(Boolean)}
function dashboardFacts(){const records=MODULES.flatMap(row=>appState.modules[row.id].records),starterStates=MODULES.flatMap(activeStarterStates),starterCompleted=starterStates.filter(row=>['completed','correct','reviewed','prepared','calculated'].includes(row.status)).length,completed=records.filter(row=>row.completed).length+starterCompleted,active=records.filter(row=>!row.completed&&!row.archived).length,total=records.length+MODULES.reduce((count,row)=>count+row.starter.starter_items.length,0),percentage=total?Math.round(completed/total*100):0;return {records,completed,active,percentage,starterCompleted}}
function renderProgress(){const facts=dashboardFacts();document.querySelectorAll('[data-double6-hook="progress-label"]').forEach(node=>{if(node.hasAttribute('data-finance-today-total')||node.closest('[data-exam-practice-board]')||node.closest('[data-household-tonight-board]')||node.closest('[data-commerce-tonight-board]')||node.closest('[data-research-tonight-board]'))return;node.textContent=facts.records.length?`本机已记下 ${facts.records.length} 笔`:'打开就能开始'});document.querySelectorAll('[data-dashboard-metric]').forEach(node=>{const kind=node.dataset.dashboardMetric;if(kind==='records')node.textContent=`${facts.records.length}${node.textContent.includes('组')?' 组':node.textContent.includes('段')?' 段':node.textContent.includes('项')?' 项':node.textContent.includes('笔')?' 笔':''}`;else if(kind==='active')node.textContent=`${facts.active}${node.textContent.includes('条')?' 条已录':' 项'}`;else if(kind==='completion')node.textContent=`${facts.percentage}%`;else if(kind==='countdown'){const dates=facts.records.flatMap(record=>Object.values(record.values||{})).filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(String(value))).sort();if(!dates.length){node.textContent='未设置'}else{const days=Math.ceil((new Date(`${dates[0]}T00:00:00`)-new Date())/86400000);node.textContent=days>=0?`${days} 天`:'日期已过'}}});document.querySelectorAll('[data-dashboard-progress-bar]').forEach(node=>node.style.width=`${facts.percentage}%`);MODULES.forEach(module=>{const records=appState.modules[module.id].records,starterDone=activeStarterStates(module).filter(row=>['completed','correct','reviewed','prepared','calculated'].includes(row.status)).length,label=records.length?`已记下 ${records.length}`:starterDone?`今晚已做 ${starterDone}`:'打开就能做';document.querySelectorAll(`[data-dashboard-module-status="${module.id}"]`).forEach(node=>node.textContent=label)});const latest=facts.records.sort((a,b)=>String(b.updatedAt||'').localeCompare(String(a.updatedAt||'')))[0];document.querySelectorAll('[data-dashboard-latest]').forEach(node=>node.textContent=latest?recordText(latest):facts.starterCompleted?'今晚已经做过':'还没有交付记录')}
function dateKey(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`}
function localDate(offset=0){const date=new Date();date.setDate(date.getDate()+offset);return dateKey(date)}
function applyTonightSeeds(state){const seeds=Array.isArray(COMPOSITION_PACK&&COMPOSITION_PACK.tonight_seeds)?COMPOSITION_PACK.tonight_seeds:[];if(!seeds.length||!state||!state.modules)return state;const today=localDate(),stamp=new Date().toISOString();seeds.forEach(seed=>{const moduleId=String(seed.module_id||''),seedId=String(seed.id||''),bucket=state.modules[moduleId];if(!bucket||!seedId)return;if(bucket.records.some(row=>row.id===seedId||row.values&&row.values.seed_id===seedId))return;if(bucket.records.some(row=>!String(row.id||'').startsWith('r-seed-')))return;const values={};Object.entries(seed.values||{}).forEach(([key,value])=>{values[key]=value==='{{today}}'?today:value});values.seed_id=seedId;values.synthetic='合成开箱，可改可删';bucket.records.push({id:seedId,values,links:Array.isArray(seed.links)?seed.links:[],completed:false,archived:false,createdAt:stamp,updatedAt:stamp})});return state}
function renderTodayBoard(){const board=document.querySelector('[data-today-workboard]');if(!board)return;const summary=board.querySelector('[data-today-summary]'),root=board.querySelector('[data-today-items]');if(!summary||!root)return;const today=localDate(),items=MODULES.flatMap(module=>(appState.modules[module.id].records||[]).filter(record=>!record.completed&&!record.archived&&/^\d{4}-\d{2}-\d{2}$/.test(String(record.values?.due||''))&&String(record.values.due)<=today).map(record=>({module,record}))).sort((left,right)=>String(left.record.values.due).localeCompare(String(right.record.values.due)));if(!items.length){summary.textContent='今天还没有排定待办；先从一个当前模块开始。';root.textContent='';return}const overdue=items.filter(item=>String(item.record.values.due)<today).length;summary.textContent=overdue?`有 ${overdue} 项逾期任务已顺延到今天，先处理最早的一项。`:`今天有 ${items.length} 项待办，完成后会留在当前设备。`;root.innerHTML=items.map(({module,record})=>{const past=String(record.values.due)<today;return `<article class="today-item ${past?'is-overdue':''}"><div><strong>${escapeHtml(recordText(record)||module.name)}</strong><small>${past?`原定 ${escapeHtml(record.values.due)} · 已顺延到今天`:'今天到期'} · ${escapeHtml(module.name)}</small></div><button type="button" class="tiny" data-today-complete data-today-module-id="${escapeHtml(module.id)}" data-today-record-id="${escapeHtml(record.id)}">完成</button></article>`}).join('')}
function renderBackupReminder(){const reminder=document.querySelector('[data-double6-hook="backup-reminder"]');if(!reminder)return;const count=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).length,0);reminder.hidden=count<30;reminder.textContent=count>=30?`已保存 ${count} 条记录，建议现在导出一份本地备份。`:''}
function renderChildParentSummary(){const summary=document.querySelector('[data-child-parent-summary]');if(!summary)return;const completed=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).filter(record=>record.completed).length,0),mistakes=MODULES.reduce((total,module)=>total+(appState.modules[module.id].starter.mistakes||[]).length,0),pending=MODULES.reduce((total,module)=>total+(appState.modules[module.id].records||[]).filter(record=>!record.completed&&!record.archived).length,0);summary.textContent=`本机已完成 ${completed} 项；有 ${mistakes} 道待回看错题、${pending} 条未完成记录。先从一件事做小调整。`}
function normalizeAnswer(value){return String(value??'').trim().replace(/\s+/g,' ').toLowerCase()}
function d6Celebrate(root){if(!root)return;const layer=document.createElement('div');layer.className='d6-star-layer';layer.setAttribute('aria-hidden','true');for(let index=0;index<8;index+=1){const star=document.createElement('span');star.textContent='⭐';star.style.left=`${6+Math.random()*88}%`;star.style.animationDelay=`${(Math.random()*.4).toFixed(2)}s`;layer.appendChild(star)}root.appendChild(layer);setTimeout(()=>layer.remove(),1700)}
function d6Shake(root){const node=root?.querySelector('[data-starter-result]');if(node)node.classList.add('d6-shake')}
function d6Streak(days){let count=0,offset=0;for(;;){const key=localDate(-offset);if(!days[key])break;count+=1;offset+=1}return count}
function d6BadgeMet(rule,rewards){if(rule.type==='stars_earned_total')return rewards.earnedTotal>=rule.threshold;if(rule.type==='questions_correct_total')return rewards.awardedItems.length>=rule.threshold;if(rule.type==='generator_total')return rewards.generatorCorrect>=rule.threshold;if(rule.type==='streak_days')return d6Streak(rewards.days)>=rule.threshold;if(rule.type==='redeems_total')return rewards.redeemed.length>=rule.threshold;return false}
function d6EvalBadges(next){const earned=[];MODULES.forEach(module=>((module.rewards&&module.rewards.badges)||[]).forEach(badge=>{if(!next.rewards.badges.includes(badge.badge_id)&&d6BadgeMet(badge.rule,next.rewards)){next.rewards.badges.push(badge.badge_id);earned.push(badge.title)}}));return earned}
function d6EarnStar(next,itemId,kind){const rewards=next.rewards,today=localDate();let awarded=false;if(kind==='generator'){if(rewards.dailyGenerator.date!==today)rewards.dailyGenerator={date:today,count:0};rewards.generatorCorrect+=1;if(rewards.dailyGenerator.count<20){rewards.dailyGenerator.count+=1;awarded=true}}else if(!rewards.awardedItems.includes(itemId)){rewards.awardedItems.push(itemId);awarded=true}if(awarded){rewards.stars+=1;rewards.earnedTotal+=1}rewards.days[today]=true;return {awarded,newBadges:[]}}
function d6StarMessage(earned){if(!earned)return'';const parts=[];if(earned.awarded)parts.push('获得 1 颗星星');if(earned.newBadges.length)parts.push(`解锁徽章：${earned.newBadges.join('、')}`);return parts.length?`，${parts.join('，')}`:''}
function renderStarBalance(){document.querySelectorAll('[data-reward-balance]').forEach(node=>node.textContent=`${appState.rewards?.stars??0} ⭐`)}
function renderRewards(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"] [data-reward-root]`);if(!root||!module.rewards)return;const rewards=appState.rewards,custom=(appState.modules[id].records||[]).filter(record=>!record.archived).map(record=>({item_id:record.id,title:String(record.values.title||'自定义奖励'),icon:'🎁',cost:Math.max(1,Math.floor(Number(record.values.stars))||1),custom:true})),shop=[...(module.rewards.shop||[]).map(item=>({...item,custom:false})),...custom];root.querySelector('[data-reward-shop]').innerHTML=shop.map(item=>`<article class="reward-shop-item"><span class="reward-icon" aria-hidden="true">${escapeHtml(item.icon||'🎁')}</span><strong>${escapeHtml(item.title)}</strong><small>${item.custom?'家庭自定义':'内置奖励'}</small><button type="button" class="tiny" data-reward-redeem="${escapeHtml(item.item_id)}" data-reward-cost="${item.cost}" data-reward-title="${escapeHtml(item.title)}" ${rewards.stars<item.cost?'disabled':''}>${item.cost} ⭐ 兑换</button></article>`).join('');root.querySelector('[data-reward-badges]').innerHTML=(module.rewards.badges||[]).map(badge=>{const earned=rewards.badges.includes(badge.badge_id);return `<article class="reward-badge ${earned?'is-earned':''}" data-reward-badge="${escapeHtml(badge.badge_id)}"><span aria-hidden="true">${escapeHtml(badge.icon)}</span><strong>${escapeHtml(badge.title)}</strong><small>${earned?'已点亮':escapeHtml(badge.hint)}</small></article>`}).join('');const now=new Date(),year=now.getFullYear(),month=now.getMonth(),count=new Date(year,month+1,0).getDate(),today=localDate();root.querySelector('[data-reward-calendar]').innerHTML=Array.from({length:count},(_,index)=>{const date=`${year}-${String(month+1).padStart(2,'0')}-${String(index+1).padStart(2,'0')}`;return `<span class="${rewards.days[date]?'done ':''}${date===today?'today':''}" title="${date}">${index+1}</span>`}).join('');const streak=d6Streak(rewards.days);root.querySelector('[data-reward-summary]').textContent=`累计获得 ${rewards.earnedTotal} 颗 · 连续练习 ${streak} 天`;root.querySelector('[data-reward-streak]').textContent=streak?`已连续练习 ${streak} 天，明天再来一天就更棒`:'今天完成一次练习就开始计天数';root.querySelector('[data-reward-history]').innerHTML=rewards.redeemed.length?rewards.redeemed.slice(0,5).map(entry=>`<p class="reward-history-row"><strong>${escapeHtml(entry.title)}</strong><small>${entry.cost} ⭐ · ${escapeHtml(entry.date)}</small></p>`).join(''):'<p class="reward-history-row">还没有兑换记录；星星够了就可以换。</p>'}
document.addEventListener('click',event=>{const button=event.target.closest('[data-reward-redeem]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]');if(!moduleRoot)return;const id=moduleRoot.dataset.double6ModuleId,cost=Math.floor(Number(button.dataset.rewardCost))||0,title=button.dataset.rewardTitle||'奖励';if(!(cost>0))return;if((appState.rewards?.stars??0)<cost){feedback(id,'星星还不够，再完成一些练习吧。',true);return}if(!confirm(`用 ${cost} 颗星星兑换「${title}」吗？兑换后记得和家长兑现。`))return;const next=clone(appState);next.rewards.stars-=cost;next.rewards.redeemed.unshift({title,cost,date:localDate(),at:new Date().toISOString()});try{persist(next);appState=next;renderModule(id);renderStarBalance();feedback(id,`已兑换「${title}」，记得和家长兑现哦。`);d6Celebrate(moduleRoot)}catch(error){feedback(id,'兑换保存失败，星星未被扣减。',true)}});
function starterResult(state,item){const answer=state.answers[item.item_id];if(item.kind==='question'&&answer)return `<div class="starter-result ${answer.correct?'success':'error'}" data-starter-result><strong>${answer.correct?'回答正确':'再想一想'}</strong><p>你的答案：${escapeHtml(answer.value)}</p><p>正确答案：${escapeHtml(item.answer)}</p><p>${escapeHtml(item.explanation)}</p><small>${escapeHtml(item.knowledge_point)} · ${escapeHtml(item.difficulty)} · ${escapeHtml(item.source_label)}</small></div>`;const itemState=effectiveStarterState(item,state);return itemState?.result?`<div class="starter-result success" data-starter-result><strong>结果已留在本机</strong><p>${escapeHtml(itemState.result)}</p></div>`:''}
function keypadHtml(){return `<div class="starter-keypad-answer"><output data-keypad-display aria-live="polite" aria-label="已输入的答案"></output><div class="starter-keypad">${['1','2','3','4','5','6','7','8','9','⌫','0','清'].map(key=>`<button type="button" class="keypad-key" data-keypad-key="${key}" aria-label="${key==='⌫'?'删除一位':key==='清'?'清空输入':`数字 ${key}`}">${key}</button>`).join('')}</div></div>`}
function detailButton(item){return ''}
function questionCard(item,state,index,total,moduleId){const answer=state.answers[item.item_id],exam=String(moduleId||'').startsWith('exam-'),options=Array.isArray(item.options)?`<div class="starter-options">${item.options.map(option=>`<button type="button" class="starter-option" data-starter-option="${escapeHtml(option)}" aria-pressed="false">${escapeHtml(option)}</button>`).join('')}</div>`:(item.input_type==='number'?keypadHtml():`<label class="starter-answer"><span>输入答案</span><input data-starter-answer-input type="text" inputmode="text" autocomplete="off"></label>`),mission=item.mission?`<div class="quest-mission"><span>${escapeHtml(item.activity_label||'今日小挑战')}</span><strong>${escapeHtml(item.mission)}</strong></div>`:'',story=item.story?`<p class="quest-story">${escapeHtml(item.story)}</p>`:'',hint=item.hint?`<details class="quest-hint"><summary>要一点提示</summary><p>${escapeHtml(item.hint)}</p></details>`:'',read=item.audio_text?`<button type="button" class="secondary" data-starter-action="read-aloud">听一听</button>`:'';return `<article class="starter-card starter-question${exam?' exam-question-card':''}" data-starter-item-id="${escapeHtml(item.item_id)}"><div class="starter-card-meta"><span>第 ${index+1} / ${total} 题</span><span>${escapeHtml(item.difficulty)} · ${escapeHtml(item.knowledge_point)}</span></div>${mission}${story}<h4>${escapeHtml(item.prompt)}</h4>${hint}${options}<div class="starter-actions">${read}<button type="button" data-starter-action="submit-question">${exam?(answer?'再做一次':'提交这题'):(answer?'重新作答':'提交答案')}</button><button type="button" class="secondary" data-starter-action="next-question">下一题</button>${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function d6GenQuestion(params){const ops=['add','sub'];if(params.mul_max>1)ops.push('mul');if(params.div)ops.push('div');const op=ops[Math.floor(Math.random()*ops.length)],rand=max=>1+Math.floor(Math.random()*max);let a,b,answer,text;if(op==='add'){a=rand(params.add_max);b=rand(params.add_max);answer=a+b;text=`${a} + ${b} = ?`}else if(op==='sub'){a=rand(params.sub_max);b=rand(a);answer=a-b;text=`${a} − ${b} = ?`}else if(op==='mul'){a=2+Math.floor(Math.random()*(params.mul_max-1));b=2+Math.floor(Math.random()*(params.mul_max-1));answer=a*b;text=`${a} × ${b} = ?`}else{b=2+Math.floor(Math.random()*(params.mul_max-1));answer=2+Math.floor(Math.random()*(params.mul_max-1));a=b*answer;text=`${a} ÷ ${b} = ?`}return{text,answer:String(answer)}}
function d6GenNext(card){const moduleRoot=card.closest('[data-double6-module-id]'),module=moduleRoot?moduleById[moduleRoot.dataset.double6ModuleId]:null,item=module?.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId),params=item?.generator?.params||{};const q=d6GenQuestion(params);card.dataset.currentAnswer=q.answer;const node=card.querySelector('[data-generator-question]');if(node)node.textContent=q.text;const display=card.querySelector('[data-keypad-display]');if(display)display.textContent='';const submit=card.querySelector('[data-starter-action="generator-submit"]');if(submit)submit.disabled=false;const nextButton=card.querySelector('[data-starter-action="generator-next"]');if(nextButton)nextButton.textContent='换一题'}
function generatorCard(item,state){const itemState=effectiveStarterState(item,state);return `<article class="starter-card starter-generator" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">口算天天练 · 不限题量</span><h4>${escapeHtml(item.title)}</h4><p class="generator-question" data-generator-question>点「开始出题」，答完一题马上出下一题。</p>${keypadHtml()}<div class="starter-actions"><button type="button" data-starter-action="generator-next">开始出题</button><button type="button" data-starter-action="generator-submit" disabled>提交答案</button>${detailButton(item)}</div><p class="generator-streak" data-generator-streak aria-live="polite"></p>${itemState?.result?`<div class="starter-result success" data-starter-result><strong>练习记录</strong><p>${escapeHtml(itemState.result)}</p></div>`:''}</article>`}
function calculatorCard(item,state){const labels=Array.isArray(item.input_labels)?item.input_labels:[];const inputs=(item.inputs||[]).map((value,index)=>{const label=String(labels[index]||'').trim();return `<label><span>${escapeHtml(label||'缺少字段名')}</span><input type="number" inputmode="decimal" step="any" data-starter-calc-input value="${escapeHtml(value)}"></label>`}).join('');return `<article class="starter-card starter-calculator" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">可现场修改的演算</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p><div class="starter-calculator-inputs">${inputs}</div><div class="starter-actions"><button type="button" data-starter-action="calculate">计算并保存结果</button>${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function promptCard(item,state){const prompts=Array.isArray(item.prompts)?item.prompts:[],fallback=new Date().getDate()%Math.max(prompts.length,1),index=Number.isInteger(state.promptIndex)?state.promptIndex%Math.max(prompts.length,1):fallback,prompt=prompts[index]||item.title;return `<article class="starter-card life-prompt" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">今日灵感</span><h4>${escapeHtml(prompt)}</h4><p>这是 Double6 自编提示，不引用第三方文案。写下感想后，它会和你的随手记一起保存在当前设备。</p><div class="starter-actions"><button type="button" data-starter-action="rotate-prompt">换一条灵感</button>${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function draftCard(item,state){const itemState=effectiveStarterState(item,state),drafts=itemState&&itemState.drafts&&typeof itemState.drafts==='object'?itemState.drafts:{},sections=Array.isArray(item.sections)?item.sections:[{key:'body',label:'今晚这段',placeholder:'用自己的话写。'}],fields=sections.map(section=>{const value=String(drafts[section.key]||'');return `<label class="starter-draft-field"><span>${escapeHtml(section.label||'今晚这段')}</span><textarea data-draft-field="${escapeHtml(section.key)}" maxlength="2000" rows="3" placeholder="${escapeHtml(section.placeholder||'用自己的话写。')}">${escapeHtml(value)}</textarea></label>`}).join(''),filled=sections.filter(section=>String(drafts[section.key]||'').trim()).length,material=String(item.prompt||item.body||''),hint=String(item.body&&item.prompt?item.body:'写完记下，只留在这台设备。不是已评分。');return `<article class="starter-card starter-draft" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">今晚写这一段</span><h4>${escapeHtml(item.title)}</h4><p class="starter-draft-material">${escapeHtml(material)}</p>${fields}<p class="starter-draft-count" data-draft-count>${filled?`已写下 ${filled} / ${sections.length} 段。练习草稿，不是已评分。`:escapeHtml(hint)}</p><div class="starter-actions">${material?`<button type="button" class="secondary" data-draft-listen>听材料</button>`:''}<button type="button" data-starter-action="save-draft">记下今晚这段</button>${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function examPlanMinutes(item){const match=String(item.title||'').match(/(\d+)\s*分钟/);return match?Number(match[1]):0}
function examPlanBlock(item,state,index,start){const itemState=effectiveStarterState(item,state),done=itemState?.status==='completed',openView=String(item.open_view||'').trim(),openItem=String(item.open_item_id||'').trim(),minutes=examPlanMinutes(item),end=start+minutes;return `<article class="exam-plan-block ${done?'is-done':''}" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="exam-plan-seq">${index+1}</span><span class="exam-plan-time">${start}'–${end}'</span><div class="exam-plan-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.body||'')}</small></div><div class="exam-plan-actions">${openView?`<a class="starter-open-view" href="#${escapeHtml(openView)}" data-open-view="${escapeHtml(openView)}"${openItem?` data-open-item="${escapeHtml(openItem)}"`:''}>去做</a>`:''}<button type="button" data-starter-action="toggle">${done?'还没做':'勾掉'}</button></div></article>`}
function regularStarterCard(item,state){const itemState=effectiveStarterState(item,state),verb=item.kind==='template'?'按这个改':item.kind==='reference'?(itemState?.status==='reviewed'?'再看一遍':'看过了'):itemState?.status==='completed'?'还没做':'勾掉',kind=item.kind==='template'?'可改的提纲':item.kind==='reference'?'打开就能看':'',kindHtml=kind?`<span class="starter-kind">${escapeHtml(kind)}</span>`:'',openView=String(item.open_view||'').trim(),openItem=String(item.open_item_id||'').trim(),todayJump=openView&&Array.isArray(item.module_ids)&&item.module_ids.includes('exam-today'),openHtml=openView?`<a class="starter-open-view" href="#${escapeHtml(openView)}" data-open-view="${escapeHtml(openView)}"${openItem?` data-open-item="${escapeHtml(openItem)}"`:''}>${todayJump?'去做这一科':'去做'}</a>`:'',extra=todayJump?'':`<button type="button" data-starter-action="${item.kind==='template'?'use-template':item.kind==='reference'?'review':'toggle'}">${verb}</button>`;return `<article class="starter-card" data-starter-item-id="${escapeHtml(item.item_id)}">${kindHtml}<h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p><div class="starter-actions">${openHtml}${extra}${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function referenceCard(item,state){const ref=item.reference;if(!ref||typeof ref!=='object')return regularStarterCard(item,state);const speakLang=String(ref.lang||(ref.style==='poems'?'zh-CN':'')).trim(),langAttr=speakLang?` data-speak-lang="${escapeHtml(speakLang)}"`:'';let content='';if(ref.style==='poems'&&Array.isArray(ref.poems)){content=`<div class="ref-poems">${ref.poems.map((poem,index)=>{const spoken=[poem.title,...poem.lines].join('，');return `<details class="ref-poem"${index===0?' open':''}><summary><strong>${escapeHtml(poem.title)}</strong><span>${escapeHtml(poem.author||'')}</span></summary><p class="ref-poem-lines">${(poem.lines||[]).map(line=>escapeHtml(line)).join('<br>')}</p>${poem.notes?`<p class="ref-poem-note"><b>注释</b>：${escapeHtml(poem.notes)}</p>`:''}${poem.translation?`<p class="ref-poem-note"><b>译文</b>：${escapeHtml(poem.translation)}</p>`:''}<div class="starter-actions"><button type="button" class="secondary" data-ref-speak="${attrSafe(spoken)}"${langAttr}>读一读</button></div></details>`}).join('')}</div>`}else if(Array.isArray(ref.groups)){content=ref.groups.map(group=>`<section class="ref-group"><h5>${escapeHtml(group.label||'')}</h5><div class="ref-chips">${(group.entries||[]).map(entry=>`<button type="button" class="ref-chip" data-ref-speak="${attrSafe(entry.speak||entry.text)}"${langAttr}><strong>${escapeHtml(entry.text)}</strong>${entry.note?`<small>${escapeHtml(entry.note)}</small>`:''}</button>`).join('')}</div></section>`).join('')}const itemState=effectiveStarterState(item,state);return `<article class="starter-card ref-card" data-starter-item-id="${escapeHtml(item.item_id)}"><span class="starter-kind">打开就能看</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body||'')}</p>${content}<div class="starter-actions"><button type="button" data-starter-action="review">${itemState?.status==='reviewed'?'再看一遍':'看过了'}</button>${detailButton(item)}</div>${starterResult(state,item)}</article>`}
function starterItemsFor(module){return (module.starter.starter_items||[]).filter(item=>!Array.isArray(item.module_ids)||item.module_ids.includes(module.id))}
function speakCard(item,state){const itemState=effectiveStarterState(item,state),drafts=itemState&&itemState.drafts&&typeof itemState.drafts==='object'?itemState.drafts:{},transcript=String(drafts.transcript||''),think=Number(item.think_seconds||60),speak=Number(item.speak_seconds||180);return `<article class="starter-card starter-speak" data-starter-item-id="${escapeHtml(item.item_id)}" data-exam-speak><span class="starter-kind">开口练习 · 打判还没接上</span><h4>${escapeHtml(item.title||'结构化面试')}</h4><p class="starter-draft-material">${escapeHtml(item.prompt||item.body||'')}</p><div class="exam-timer-row"><button type="button" data-exam-think="${think}">开始思考 ${think}s</button><button type="button" data-exam-speak-start="${speak}">开始作答 ${speak}s</button><strong data-exam-speak-clock>未开始</strong></div><label class="starter-draft-field"><span>转写</span><textarea data-draft-field="transcript" maxlength="4000" rows="6" placeholder="把转写贴在这里。本页还不录音。">${escapeHtml(transcript)}</textarea></label><p>内容打判还没接上，先把转写留下。不是过线结论，也不是心理测评。</p><div class="starter-actions"><button type="button" data-starter-action="save-draft">记下这段转写</button></div></article>`}
function starterCardFor(id,item,state){return item.kind==='calculator'?calculatorCard(item,state):item.kind==='prompt'?promptCard(item,state):item.kind==='generator'?generatorCard(item,state):item.kind==='reference'?referenceCard(item,state):item.kind==='draft'?draftCard(item,state):item.kind==='speak'?speakCard(item,state):regularStarterCard(item,state)}
function renderStarter(id){if(id==='exam-practice'||id==='exam-errors')return;if(document.querySelector('[data-exam-desk]')&&(id==='exam-materials'||id==='exam-today'))return;const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-content]`);if(!root)return;const state=appState.modules[id].starter,items=starterItemsFor(module),questions=items.filter(item=>item.kind==='question'),others=items.filter(item=>item.kind!=='question');const cards=[],paintQuestion=()=>{if(!questions.length)return;const mistake=state.mistakes.find(itemId=>questions.some(item=>item.item_id===itemId)),index=mistake?questions.findIndex(item=>item.item_id===mistake):state.questionIndex%questions.length;cards.push(questionCard(questions[index],state,index,questions.length,module.id))},paintOthers=()=>{if(id==='exam-goal'){const actions=others.filter(item=>item.kind==='action'),note=others.find(item=>item.item_id==='exam-plan-2'||item.kind==='reference');let start=0;const rows=actions.map((item,index)=>{const html=examPlanBlock(item,state,index,start);start+=examPlanMinutes(item);return html}).join('');cards.push(`<div class="exam-plan-table" data-exam-plan-table><header>今晚 ${start||60} 分钟</header>${rows}${note&&note.body?`<p class="exam-plan-foot">${escapeHtml(note.body)}</p>`:''}</div>`);return}cards.push(...others.map(item=>starterCardFor(id,item,state)))};if(id==='exam-goal')paintOthers();else{paintQuestion();paintOthers()}root.innerHTML=cards.join('')}
function renderModule(id){const module=moduleById[id],root=document.querySelector(`[data-double6-module-id="${id}"]`),list=root.querySelector('[data-module-records]'),query=(root.querySelector('[data-module-filter]')?.value||'').toLowerCase(),records=appState.modules[id].records.filter(record=>!query||recordText(record).toLowerCase().includes(query));renderStarter(id);list.innerHTML=records.length?records.map(record=>{const relation=typeof personalLinkLabel==='function'?personalLinkLabel(record):typeof contentLinkLabel==='function'?contentLinkLabel(record):typeof salesLinkLabel==='function'?salesLinkLabel(record):'';return `<article class="record ${record.completed?'is-complete':''} ${record.archived?'is-archived':''}" data-module-record data-record-id="${escapeHtml(record.id)}"><div><strong>${escapeHtml(recordText(record)||'未命名记录')}</strong><small>${record.completed?'已完成 · ':''}${record.archived?'已归档 · ':''}${relation?`${escapeHtml(relation)} · `:''}${escapeHtml(record.updatedAt||'')}</small></div><div class="record-actions">${actionButtons(module,record)}</div></article>`}).join(''):'<p class="empty-record">先做上面今晚这件事。自己要留的流水，做完再补。</p>';MODULES.forEach(row=>renderRewards(row.id));renderStarBalance();renderProgress();renderTodayBoard();renderBackupReminder();renderChildParentSummary()}
function renderLegacy(){const root=document.querySelector('[data-double6-hook="legacy-import"]');if(!appState.legacyImport){root.hidden=true;root.textContent='';return}root.hidden=false;root.textContent=`历史导入区：${appState.legacyImport.notes||'无备注'}；已完成项 ${appState.legacyImport.completedItemIds?.length||0} 个。未映射原始字段已原样保留在导出文件中。`}
const COMPOSITION_PACK=__COMPOSITION_PACK__;
__SCENE_RUNTIME_HELPERS__
__LIFE_HELPERS__
function render(){MODULES.forEach(row=>renderModule(row.id));MODULES.forEach(row=>renderAtomicTools(row.id));renderLegacy();renderProgress();renderTodayBoard();renderBackupReminder();renderChildParentSummary();renderStarBalance();renderSnapshots();renderImportLog();renderCapabilityDoctor();renderFirstRun();renderAdultWarmth();__SCENE_RUNTIME_RENDER____LIFE_RENDER__}
__LIFE_LISTENERS__
__SCENE_RUNTIME_LISTENERS__
function resetForm(root){const form=root.querySelector('[data-module-form]');form.reset();delete form.dataset.editing;delete form.dataset.sourceModuleId;delete form.dataset.sourceRecordId;delete form.dataset.sourceRelation;root.querySelector('[data-module-cancel]').hidden=true}
document.addEventListener('click',event=>{const button=event.target.closest('[data-open-detail]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]'),module=moduleById[moduleRoot?.dataset.double6ModuleId],item=module?.starter?.starter_items?.find(row=>row.item_id===button.dataset.openDetail),view=document.querySelector('[data-detail-view]');if(!moduleRoot||!module||!item||!view)return;view.dataset.detailObjectId=String(item.item_id);view.querySelector('[data-detail-title]').textContent=String(item.title||item.prompt||'当前详情');view.querySelector('[data-detail-body]').textContent=String(item.body||item.mission||item.result||'返回所属模块继续完成。');const status=appState.modules[module.id]?.starter?.itemStates?.[item.item_id]?.status;view.querySelector('[data-detail-status]').textContent=status?`当前状态：${status}`:'当前状态：尚未开始';view.querySelectorAll('[data-detail-back]').forEach((back,index)=>{back.href=`#module-${module.id}`;back.textContent=index?`返回${module.name}继续`:`← 返回${module.name}`});location.hash='#detail-view'});
function activateView(hash,{replace=false}={}){const requested=(hash||location.hash||'#dashboard').slice(1),target=document.querySelector(`[data-view-id="${CSS.escape(requested)}"]`),view=target||document.querySelector('[data-view-id="dashboard"]'),viewId=view.dataset.viewId;document.querySelectorAll('[data-view-id]').forEach(node=>{const active=node===view;node.hidden=!active;node.classList.toggle('is-active',active)});document.querySelectorAll('[data-nav-view]').forEach(node=>{const active=node.dataset.navView===viewId;node.classList.toggle('active',active);if(active)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current')});if(!target&&replace)history.replaceState(null,'','#dashboard');window.scrollTo({top:0,behavior:'instant'})}
function jumpStarterToItem(viewId,itemId){const moduleId=String(viewId||'').replace(/^module-/,'');if(!itemId||!moduleById[moduleId]||!appState.modules[moduleId]?.starter)return false;const items=moduleById[moduleId].starter.starter_items||[],questions=items.filter(item=>item.kind==='question'),index=questions.findIndex(row=>row.item_id===itemId);if(index>=0){const next=clone(appState);next.modules[moduleId].starter.questionIndex=index;persist(next);appState=next;render()}requestAnimationFrame(()=>{const node=document.querySelector(`[data-starter-item-id="${CSS.escape(itemId)}"]`);if(node)node.scrollIntoView({block:'start'})});return index>=0||Boolean(items.find(row=>row.item_id===itemId))}
document.addEventListener('click',event=>{const link=event.target.closest('[data-open-view]');if(!link)return;const itemId=link.getAttribute('data-open-item');if(itemId)try{jumpStarterToItem(link.getAttribute('data-open-view'),itemId)}catch(error){}});
window.addEventListener('hashchange',()=>{activateView(location.hash);renderFirstRun()});
document.querySelectorAll('[data-double6-module-id]').forEach(root=>{const id=root.dataset.double6ModuleId,module=moduleById[id],form=root.querySelector('[data-module-form]');form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const values={};module.fields.forEach(field=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);values[field.field_id]=field.type==='boolean'?input.checked:input.value});const next=clone(appState),stamp=new Date().toISOString(),editing=form.dataset.editing,sourceLink=form.dataset.sourceModuleId&&form.dataset.sourceRecordId?[{sourceModuleId:form.dataset.sourceModuleId,sourceRecordId:form.dataset.sourceRecordId,relation:form.dataset.sourceRelation||'derived_record'}]:[];let record;if(editing){record=next.modules[id].records.find(row=>row.id===editing);record.values=values;record.updatedAt=stamp}else{record={id:`r-${Date.now()}-${Math.random().toString(16).slice(2)}`,values,links:sourceLink,completed:false,archived:false,createdAt:stamp,updatedAt:stamp};next.modules[id].records.unshift(record)}try{persist(next);appState=next;resetForm(root);render();feedback(id,'已保存到当前设备。')}catch(error){feedback(id,'保存失败，输入仍保留，请重试或先导出。',true)}});root.querySelector('[data-module-cancel]').addEventListener('click',()=>resetForm(root));root.querySelector('[data-module-filter]')?.addEventListener('input',()=>renderModule(id));root.querySelector('[data-module-records]').addEventListener('click',event=>{const button=event.target.closest('[data-record-action]');if(!button)return;const article=button.closest('[data-module-record]'),next=clone(appState),records=next.modules[id].records,index=records.findIndex(row=>row.id===article.dataset.recordId),record=records[index];if(!record)return;const action=button.dataset.recordAction;if(action==='delete'){if(!confirm('确定删除这条记录吗？此操作不能自动撤销。'))return;records.splice(index,1)}else if(action==='toggle-complete'){record.completed=!record.completed;record.updatedAt=new Date().toISOString()}else if(action==='toggle-archive'){record.archived=!record.archived;record.updatedAt=new Date().toISOString()}else if(action==='move'){const stageField=module.fields.find(row=>['stage','status'].includes(row.field_id)&&Array.isArray(row.options)&&row.options.length),options=stageField?.options||[];if(options.length){const key=stageField.field_id;record.values[key]=options[(options.indexOf(record.values[key])+1)%options.length];if(record.values[key]==='已完成')record.completed=true;record.updatedAt=new Date().toISOString()}}else if(action==='edit'){module.fields.forEach(field=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);if(field.type==='boolean')input.checked=Boolean(record.values[field.field_id]);else input.value=record.values[field.field_id]??''});form.dataset.editing=record.id;root.querySelector('[data-module-cancel]').hidden=false;form.scrollIntoView({behavior:'smooth'});return}try{persist(next);appState=next;render();feedback(id,'修改已保存。')}catch(error){feedback(id,'修改失败，原记录仍保留。',true)}})});
document.addEventListener('click',event=>{const button=event.target.closest('[data-today-complete]');if(!button)return;const id=button.dataset.todayModuleId,recordId=button.dataset.todayRecordId,record=appState.modules[id]?.records?.find(row=>row.id===recordId);if(!record)return;const next=clone(appState),target=next.modules[id].records.find(row=>row.id===recordId);target.completed=true;target.updatedAt=new Date().toISOString();try{persist(next);appState=next;render();feedback(id,'已完成；今天的列表已更新。')}catch(error){dataFeedback('完成状态保存失败，原记录未被替换。',true)}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-child-mode]');if(!button)return;const parent=button.dataset.childMode==='parent';document.querySelectorAll('.child-view-child').forEach(node=>node.hidden=parent);document.querySelectorAll('.child-view-parent').forEach(node=>node.hidden=!parent);document.querySelectorAll('[data-child-mode]').forEach(node=>node.classList.toggle('active',node===button));renderChildParentSummary()});
function calculatedResult(operation,values){if(!values.length||values.some(value=>!Number.isFinite(value)))throw new Error('请填写有效数字');const first=values[0],second=values[1]||0,round=value=>Math.round(value*100)/100;if(operation==='sum')return `合计 ${round(values.reduce((sum,value)=>sum+value,0))}`;if(operation==='difference')return `结果 ${round(first-second)}`;if(operation==='percent')return second===0?'分母不能为 0':`比例 ${round(first/second*100)}%`;if(operation==='markup')return `建议值 ${round(first*1.3)}`;if(operation==='profit_margin'){const profit=round(first-second),rate=first===0?0:round(profit/first*100);return `毛利 ${profit}，毛利率 ${rate}%`}if(operation==='tax_add'){const tax=round(first*second/100);return `税额 ${tax}，含税 ${round(first+tax)}`}if(operation==='time_cost')return `时间成本 ${round(first/60*second)}`;throw new Error('此演算类型未登记')}
function saveStarter(id,next,message,error=false){try{persist(next);appState=next;renderModule(id);const node=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-feedback]`);node.textContent=message;node.className=`feedback ${error?'error':'success'}`}catch(saveError){const node=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-feedback]`);node.textContent='结果保存失败，请先导出备份后重试。';node.className='feedback error'}}
document.addEventListener('click',event=>{const keypadKey=event.target.closest('[data-keypad-key]');if(keypadKey){const wrap=keypadKey.closest('.starter-keypad-answer'),display=wrap?.querySelector('[data-keypad-display]');if(!display)return;const key=keypadKey.dataset.keypadKey;if(key==='清')display.textContent='';else if(key==='⌫')display.textContent=display.textContent.slice(0,-1);else if(display.textContent.length<9)display.textContent+=key;return}const draftListen=event.target.closest('[data-draft-listen]');if(draftListen){const moduleRoot=draftListen.closest('[data-double6-module-id]'),card=draftListen.closest('[data-starter-item-id]'),module=moduleById[moduleRoot?.dataset.double6ModuleId],item=module?.starter?.starter_items?.find(row=>row.item_id===card?.dataset.starterItemId),node=moduleRoot?.querySelector('[data-starter-feedback]');if(!d6Speak(item?.prompt||item?.body||'')){if(node){node.textContent='当前浏览器不支持朗读。';node.className='feedback error'}}return}const speakChip=event.target.closest('[data-ref-speak]');if(speakChip){if(!d6Speak(speakChip.getAttribute('data-ref-speak')||speakChip.querySelector('strong')?.textContent||'',speakChip.getAttribute('data-speak-lang'))){const speakRoot=speakChip.closest('[data-double6-module-id]'),speakNode=speakRoot?.querySelector('[data-starter-feedback]');if(speakNode){speakNode.textContent='当前浏览器不支持朗读；可以请家长一起读一读。';speakNode.className='feedback error'}}return}const option=event.target.closest('[data-starter-option]');if(option){const card=option.closest('[data-starter-item-id]');card.querySelectorAll('[data-starter-option]').forEach(node=>{const selected=node===option;node.classList.toggle('is-selected',selected);node.setAttribute('aria-pressed',String(selected))});return}const button=event.target.closest('[data-starter-action]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]'),card=button.closest('[data-starter-item-id]');if(!moduleRoot||!card)return;const id=moduleRoot.dataset.double6ModuleId,module=moduleById[id],item=module.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId);if(!item)return;const action=button.dataset.starterAction;if(action==='read-aloud'){const text=String(item.audio_text||item.prompt||''),lang=item.speak_lang||item.audio_lang||(id==='education-english'&&d6SpeakLang(text)==='en-US'?'en-US':''),node=moduleRoot.querySelector('[data-starter-feedback]');if(!d6Speak(text,lang)){if(node){node.textContent='当前浏览器不支持朗读；可以请家长一起读一读。';node.className='feedback error'}return}if(node){node.textContent=String(lang||d6SpeakLang(text)).startsWith('en')?'正在用英文声读。Windows 和 Mac 的音色不一样。':'正在朗读。这台电脑会选比较清楚的中文声，Windows 和 Mac 的音色不一样。';node.className='feedback success'}return}const next=clone(appState),state=next.modules[id].starter,stamp=new Date().toISOString();if(action==='submit-question'){const selected=card.querySelector('[data-starter-option][aria-pressed="true"]'),display=card.querySelector('[data-keypad-display]'),input=card.querySelector('[data-starter-answer-input]'),value=selected?.dataset.starterOption??(display?display.textContent:input?.value)??'';if(!String(value).trim()){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent='先选择或输入一个答案。';node.className='feedback error';return}const correct=normalizeAnswer(value)===normalizeAnswer(item.answer);state.answers[item.item_id]={value:String(value),correct,updatedAt:stamp};state.itemStates[item.item_id]={status:correct?'correct':'incorrect',result:correct?'回答正确，解析已展开。':'已加入错题回看，解析已展开。',updatedAt:stamp};state.mistakes=correct?state.mistakes.filter(row=>row!==item.item_id):[...new Set([...state.mistakes,item.item_id])];state.lastResult={itemId:item.item_id,message:correct?'回答正确':'回答错误',updatedAt:stamp};const earned=correct?d6EarnStar(next,item.item_id,'question'):null;saveStarter(id,next,(correct?'太棒了，答案、解析和这次完成记录都已保存在当前设备。':'先看解析；这道题已进入错题回看，下一次可以换个办法再战。')+d6StarMessage(earned),!correct);const freshRoot=document.querySelector(`[data-double6-module-id="${id}"]`);if(correct)d6Celebrate(freshRoot);else d6Shake(freshRoot);return}if(action==='next-question'){const questions=module.starter.starter_items.filter(row=>row.kind==='question');state.questionIndex=questions.length?(state.questionIndex+1)%questions.length:0;saveStarter(id,next,'已切到下一张挑战卡，可刷新后继续。');return}if(action==='generator-next'){d6GenNext(card);return}if(action==='generator-submit'){const display=card.querySelector('[data-keypad-display]'),value=(display?.textContent||'').trim(),node=moduleRoot.querySelector('[data-starter-feedback]');if(!card.dataset.currentAnswer){node.textContent='先点「开始出题」。';node.className='feedback error';return}if(!value){node.textContent='先用小键盘输入答案。';node.className='feedback error';return}const correct=normalizeAnswer(value)===normalizeAnswer(card.dataset.currentAnswer),streak=correct?Number(card.dataset.streak||'0')+1:0;card.dataset.streak=String(streak);const streakEl=card.querySelector('[data-generator-streak]');if(streakEl)streakEl.textContent=correct?`本次连对 ${streak} 题`:'';if(correct){const prev=state.itemStates[item.item_id]?.result||'',match=prev.match(/累计完成 (\d+) 题 · 最佳连对 (\d+)/),total=(match?Number(match[1]):0)+1,best=Math.max(match?Number(match[2]):0,streak);state.itemStates[item.item_id]={status:'practiced',result:`累计完成 ${total} 题 · 最佳连对 ${best}`,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:'口算答对',updatedAt:stamp};const earned=d6EarnStar(next,item.item_id,'generator');saveStarter(id,next,`答对了！本次连对 ${streak} 题${d6StarMessage(earned)}。`);const freshRoot=document.querySelector(`[data-double6-module-id="${id}"]`);d6Celebrate(freshRoot);const freshCard=freshRoot?.querySelector(`[data-starter-item-id="${item.item_id}"]`);if(freshCard)freshCard.dataset.streak=String(streak);setTimeout(()=>{const current=document.querySelector(`[data-double6-module-id="${id}"] [data-starter-item-id="${item.item_id}"]`);if(current)d6GenNext(current)},600);return}node.textContent=`再想一想，正确答案是 ${card.dataset.currentAnswer}；已帮你换下一题。`;node.className='feedback error';card.classList.add('d6-shake');setTimeout(()=>card.classList.remove('d6-shake'),500);setTimeout(()=>d6GenNext(card),900);return}if(action==='calculate'){try{const values=[...card.querySelectorAll('[data-starter-calc-input]')].map(node=>Number(node.value)),result=calculatedResult(item.calculation,values);state.itemStates[item.item_id]={status:'calculated',result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:result,updatedAt:stamp};saveStarter(id,next,`${result}；仅为本地演算，请按页面边界人工复核。`)}catch(error){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent=error.message;node.className='feedback error'}return}if(action==='save-draft'){const drafts={};card.querySelectorAll('[data-draft-field]').forEach(node=>{drafts[node.getAttribute('data-draft-field')]=String(node.value||'').slice(0,2000)});if(!Object.values(drafts).some(value=>String(value).trim())){const node=moduleRoot.querySelector('[data-starter-feedback]');node.textContent='先写下今晚这段，再记下。';node.className='feedback error';return}state.itemStates[item.item_id]={status:'drafted',result:item.result,drafts,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:item.result,updatedAt:stamp};saveStarter(id,next,'已记下今晚这段。练习草稿，不是已评分，也不保证上岸。');return}if(action==='use-template'){const form=moduleRoot.querySelector('[data-module-form]'),editable=module.fields.filter(field=>['text','textarea'].includes(field.type)),titleField=editable.find(field=>field.type==='text'),bodyField=editable.find(field=>field.type==='textarea')||editable.find(field=>field.field_id!==titleField?.field_id)||titleField;editable.forEach(field=>{const input=form.querySelector(`[data-field-id="${field.field_id}"]`);if(!input)return;const value=field.field_id===bodyField?.field_id?(item.body||item.result||item.title||''):field.field_id===titleField?.field_id?(item.title||''):'';if(value)input.value=value});state.itemStates[item.item_id]={status:'prepared',result:item.result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:item.result,updatedAt:stamp};saveStarter(id,next,'已填进下面要留的记录，检查后再保存。');moduleRoot.querySelector('[data-module-form]').scrollIntoView({behavior:'smooth',block:'center'});return}if(action==='review'){state.itemStates[item.item_id]={status:'reviewed',result:item.result,updatedAt:stamp};state.lastResult={itemId:item.item_id,message:item.result,updatedAt:stamp};saveStarter(id,next,'看过了，结果留在这台设备。');return}if(action==='toggle'){const completed=effectiveStarterState(item,state)?.status==='completed';state.itemStates[item.item_id]={status:completed?'ready':'completed',result:completed?'已取消勾掉':item.result,updatedAt:stamp,...(item.recurrence==='weekly'?{cycleKey:currentWeekKey()}:{})};state.lastResult={itemId:item.item_id,message:completed?'已取消勾掉':item.result,updatedAt:stamp};const earned=completed?null:d6EarnStar(next,item.item_id,'action');saveStarter(id,next,(completed?'已撤销，可再次完成。':'已完成，结果保存在当前设备。')+d6StarMessage(earned))}});
document.addEventListener('click',event=>{const button=event.target.closest('[data-starter-action="rotate-prompt"]');if(!button)return;const moduleRoot=button.closest('[data-double6-module-id]'),card=button.closest('[data-starter-item-id]');if(!moduleRoot||!card)return;const id=moduleRoot.dataset.double6ModuleId,module=moduleById[id],item=module.starter.starter_items.find(row=>row.item_id===card.dataset.starterItemId),prompts=Array.isArray(item?.prompts)?item.prompts:[];if(!prompts.length)return;const next=clone(appState),state=next.modules[id].starter,stamp=new Date().toISOString();state.promptIndex=((Number.isInteger(state.promptIndex)?state.promptIndex:new Date().getDate()%prompts.length)+1)%prompts.length;state.itemStates[item.item_id]={status:'rotated',result:'已保存今天选择的灵感。',updatedAt:stamp};saveStarter(id,next,'已换一条；写下感想后保存到下方随手记。')});
__LIFE_MOVEMENT__
__ATOMIC_LISTENERS__
function downloadState(){const blob=new Blob([JSON.stringify(workspacePayload(appState),null,2)],{type:'application/json'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${PRODUCT_ID}-backup-v4.json`;link.click();URL.revokeObjectURL(link.href)}
function downloadFinanceCsv(){const rows=FINANCE_MODULE_IDS.flatMap(id=>(appState.modules[id]?.records||[]).map(record=>({module:moduleById[id].name,...record.values,completed:record.completed?'是':'否',updated_at:record.updatedAt||''})));const headers=['module','entry_type','amount','category','date','notes','completed','updated_at'],quote=value=>`"${String(value??'').replaceAll('"','""')}"`,csv=['\ufeff'+headers.join(','),...rows.map(row=>headers.map(key=>quote(row[key])).join(','))].join('\n'),blob=new Blob([csv],{type:'text/csv;charset=utf-8'}),link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${PRODUCT_ID}-finance.csv`;link.click();URL.revokeObjectURL(link.href)}
let pendingLedgerCsv=null;
function parseCsvRows(text){const raw=String(text||'').replace(/^\ufeff/,'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');if(!raw.trim())return [];const rows=[];let row=[],cell='',inQuotes=false;for(let i=0;i<raw.length;i+=1){const ch=raw[i],next=raw[i+1];if(ch==='"'&&inQuotes&&next==='"'){cell+='"';i+=1;continue}if(ch==='"'){inQuotes=!inQuotes;continue}if(ch===','&&!inQuotes){row.push(cell);cell='';continue}if(ch==='\n'&&!inQuotes){row.push(cell);rows.push(row);row=[];cell='';continue}cell+=ch}row.push(cell);if(row.some(value=>String(value).trim()!==''))rows.push(row);return rows}
function previewLedgerCsv(event){const file=event.target.files&&event.target.files[0],host=document.querySelector('[data-ledger-csv-preview]'),summary=host&&host.querySelector('[data-ledger-csv-summary]');if(!file||!host||!summary)return;const moduleId=document.querySelector('[data-ledger-csv-module]')?.value,mode=document.querySelector('[data-ledger-csv-mode]')?.value||'append',spec=LEDGER_CSV_SPECS[moduleId];if(!spec||!moduleById[moduleId]){dataFeedback('只有记账流水、店铺订单或考勤能导入 CSV。',true);event.target.value='';return}const reader=new FileReader();reader.onload=()=>{try{const table=parseCsvRows(String(reader.result||''));if(table.length<2)throw new Error('CSV 没有数据行');const headers=table[0].map(value=>String(value||'').trim()),missing=(spec.required||[]).filter(name=>!headers.includes(name));if(missing.length)throw new Error('缺少必要列：'+missing.join('、'));const body=table.slice(1);if(body.length>Number(spec.max_rows||200))throw new Error('一次最多 '+(spec.max_rows||200)+' 行');const parsed=[];body.forEach((line,index)=>{const values={};headers.forEach((name,col)=>{if((spec.headers||[]).includes(name))values[name]=String(line[col]??'').trim()});(spec.required||[]).forEach(name=>{if(!values[name])throw new Error('第 '+(index+1)+' 行缺少 '+name)});Object.entries(spec.enums||{}).forEach(([name,allowed])=>{if(values[name]&&!allowed.includes(values[name]))throw new Error('第 '+(index+1)+' 行 '+name+' 只能是 '+allowed.join(' / '))});(spec.number_fields||[]).forEach(name=>{if(!(Number(values[name])>0))throw new Error('第 '+(index+1)+' 行金额无效');values[name]=Number(values[name])});parsed.push({id:'r-csv-'+Date.now()+'-'+index,values,links:[],completed:false,archived:false,createdAt:'',updatedAt:''})});const current=appState.modules[moduleId]?.records||[],nextRecords=mode==='replace'?parsed:current.concat(parsed);if(nextRecords.length>MAX_RECORDS_PER_MODULE)throw new Error('导入后会超过每本台账 2000 条');pendingLedgerCsv={moduleId,mode,records:nextRecords,incoming:parsed.length,before:current.length,after:nextRecords.length,sample:parsed.slice(0,4)};host.hidden=false;summary.textContent=`${moduleById[moduleId].name}：${mode==='replace'?'替换':'追加'} ${parsed.length} 行，导入后 ${nextRecords.length} 条。确认前当前数据未改动。样例：`+parsed.slice(0,4).map(row=>Object.values(row.values).join(' / ')).join('；');dataFeedback('CSV 预览已就绪。这不在首页，确认前不会改今晚那一本台账。')}catch(error){pendingLedgerCsv=null;host.hidden=true;dataFeedback(`CSV 导入失败，现有数据未改动：${error.message||'格式无效'}`,true)}finally{event.target.value=''}};reader.onerror=()=>dataFeedback('CSV 读不出来，当前数据未改动。',true);reader.readAsText(file)}
document.querySelector('[data-ledger-csv-confirm]')?.addEventListener('click',()=>{if(!pendingLedgerCsv){dataFeedback('没有可确认的 CSV 预览。',true);return}const next=clone(appState);next.modules[pendingLedgerCsv.moduleId].records=pendingLedgerCsv.records;try{const snaps=captureSnapshot('before_import');next.snapshots=snaps;persistOrRestore(next);appState=next;pendingLedgerCsv=null;document.querySelector('[data-ledger-csv-preview]').hidden=true;render();dataFeedback('台账 CSV 已写入这一本记录。首页主活动没有改。')}catch(error){dataFeedback('CSV 写入失败，现有数据未改动。',true)}});
document.querySelector('[data-ledger-csv-cancel]')?.addEventListener('click',()=>{pendingLedgerCsv=null;const host=document.querySelector('[data-ledger-csv-preview]');if(host)host.hidden=true;dataFeedback('已取消 CSV 导入；当前数据未改动。')});
document.querySelector('[data-ledger-csv-file]')?.addEventListener('change',previewLedgerCsv);
document.querySelector('[data-double6-hook="clear"]').addEventListener('click',()=>{if(!confirm('确定清空当前工作台的全部本地数据吗？建议先导出备份。'))return;try{const snaps=captureSnapshot('before_clear'),next=applyTonightSeeds(emptyState());next.snapshots=snaps;next.firstRunSeen=Boolean(appState.firstRunSeen);persist(next);appState=next;lastImportBackup=null;document.querySelector('[data-double6-hook="undo-import"]').hidden=true;document.querySelectorAll('[data-module-form]').forEach(form=>form.reset());render();dataFeedback('本地数据已清空；刚才的内容还在本机恢复点里。')}catch(error){dataFeedback('清空失败，本地数据未改动。',true)}});
document.querySelectorAll('[data-double6-hook="export"],[data-double6-hook="quick-export"]').forEach(button=>button.addEventListener('click',()=>{try{downloadState();markCapability('import_export','ready','','');dataFeedback('备份文件已生成。')}catch(error){markCapability('import_export','broken','没法在当前浏览器生成备份文件。','换一个浏览器，或把页面另存后再试。');dataFeedback('导出失败，当前数据未改动。',true)}}));
document.querySelector('[data-double6-hook="export-csv"]')?.addEventListener('click',()=>{downloadFinanceCsv();dataFeedback('财务 CSV 已生成；只包含当前设备里已保存的流水。')});
document.querySelector('[data-double6-hook="undo-import"]').addEventListener('click',event=>{if(!lastImportBackup)return;try{persist(lastImportBackup);appState=lastImportBackup;lastImportBackup=null;event.currentTarget.hidden=true;render();dataFeedback('已撤销最近一次导入。')}catch(error){dataFeedback('撤销导入失败，当前数据未改动。',true)}});
function importBackup(event){const file=event.target.files[0];if(!file)return;if(file.size>MAX_IMPORT_BYTES){markCapability('import_export','stale','备份超过 8 MB，没有改当前数据。','拆成更小的备份，或先清掉不用的记录。');dataFeedback('导入失败：备份文件不能超过 8 MB。',true);event.target.value='';return}const reader=new FileReader();reader.onload=()=>{try{let parsed;try{parsed=JSON.parse(String(reader.result||''))}catch(error){throw new Error('备份不是合法 JSON')}if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))throw new Error('备份必须是对象');const next=normalize(parsed),before=Object.fromEntries(MODULES.map(module=>[module.id,appState.modules[module.id].records.length])),after=Object.fromEntries(MODULES.map(module=>[module.id,next.modules[module.id].records.length])),changed=MODULES.filter(module=>before[module.id]!==after[module.id]).map(module=>`${module.name} ${before[module.id]}→${after[module.id]}`),unmapped=next.legacyImport?.unmapped||{},quarantine=Object.values(unmapped.quarantinedRecords||{}).reduce((sum,rows)=>sum+(Array.isArray(rows)?rows.length:0),0)+Object.keys(unmapped.modules||{}).length;pendingImportState=next;pendingImportMeta={sourceName:file.name||'未命名备份',sourcePackId:parsed&&parsed.packId||'',changedModules:MODULES.filter(module=>before[module.id]!==after[module.id]).map(module=>({module_id:module.id,before:before[module.id],after:after[module.id]})),quarantineCount:quarantine};const preview=document.querySelector('[data-import-preview]');preview.hidden=false;const compat=packCompat(pendingImportMeta.sourcePackId,Object.keys((parsed&&parsed.modules)||{}));preview.querySelector('[data-import-preview-summary]').textContent=`来源：${pendingImportMeta.sourceName}。变更模块：${changed.length?changed.join('；'):'记录数无变化'}。隔离项：${quarantine}。${compat.note}确认前当前数据未改动。`;dataFeedback('导入预览已就绪；请检查后再确认，当前数据未改动。')}catch(error){pendingImportState=null;pendingImportMeta=null;document.querySelector('[data-import-preview]').hidden=true;dataFeedback(`导入失败，现有数据未改动：${error.message||'格式无效'}`,true)}finally{event.target.value=''}};reader.onerror=()=>dataFeedback('导入失败：无法读取文件。',true);reader.readAsText(file)}
document.querySelector('[data-import-confirm]').addEventListener('click',()=>{if(!pendingImportState){dataFeedback('没有可确认的导入预览。',true);return}const next=pendingImportState,meta=pendingImportMeta||{};try{const snaps=captureSnapshot('before_import');lastImportBackup=clone(appState);next.snapshots=snaps;next.importLog=[{importedAt:new Date().toISOString(),sourceName:meta.sourceName||'未命名备份',sourcePackId:meta.sourcePackId||'',currentPackId:PACK_ID,changedModules:meta.changedModules||[],quarantineCount:meta.quarantineCount||0,snapshotId:snaps[0]&&snaps[0].snapshotId||'',packNote:packCompat(meta.sourcePackId||'',(meta.changedModules||[]).map(row=>row.module_id)).note},...(Array.isArray(appState.importLog)?appState.importLog:[])].slice(0,MAX_IMPORT_LOG);persistOrRestore(next);appState=next;markCapability('import_export','ready','','');pendingImportState=null;pendingImportMeta=null;render();document.querySelector('[data-import-preview]').hidden=true;document.querySelector('[data-double6-hook="undo-import"]').hidden=false;dataFeedback('导入完成；出处已记下，可立即撤销，也可在本机恢复点里找回导入前的数据。')}catch(error){dataFeedback('导入失败，现有数据未改动。',true)}});
document.querySelector('[data-import-cancel]').addEventListener('click',()=>{pendingImportState=null;pendingImportMeta=null;document.querySelector('[data-import-preview]').hidden=true;dataFeedback('已取消导入；当前数据未改动。')});
document.querySelectorAll('[data-double6-hook="import"],[data-double6-hook="quick-import"]').forEach(input=>input.addEventListener('change',importBackup));
document.querySelector('[data-snapshot-list]')?.addEventListener('click',event=>{const button=event.target.closest('[data-restore-snapshot]');if(!button)return;const snapshotId=button.dataset.restoreSnapshot,item=(appState.snapshots||[]).find(row=>row.snapshotId===snapshotId);if(!item){dataFeedback('找不到这个恢复点。',true);return}const compat=packCompat(item.packId||item.workspace?.packId||'',item.moduleIds||Object.keys(item.workspace?.modules||{}));if(!confirm(compat.status==='same'?'恢复会替换当前本机数据。当前内容会先留下一个恢复点。继续吗？':`${compat.note} 恢复会替换当前本机数据。继续吗？`))return;try{const snaps=recordCount(appState)?captureSnapshot('before_restore'):(appState.snapshots||[]),next=normalize(item.workspace);next.snapshots=snaps;persist(next);appState=next;lastImportBackup=null;document.querySelector('[data-double6-hook="undo-import"]').hidden=true;render();dataFeedback('已恢复到选定的本机恢复点。')}catch(error){dataFeedback('恢复失败，当前数据未改动。',true)}});
document.querySelector('[data-double6-hook="copy-backup"]')?.addEventListener('click',async()=>{const text=JSON.stringify(workspacePayload(appState),null,2);if(!(navigator.clipboard&&typeof navigator.clipboard.writeText==='function')){markCapability('clipboard','broken','当前环境没有剪贴板接口。','用导出备份代替复制，或换浏览器。');dataFeedback('当前环境不能复制，请改用导出备份。',true);return}try{await navigator.clipboard.writeText(text);markCapability('clipboard','ready','','');dataFeedback('备份已复制到剪贴板。')}catch(error){const denied=/denied|NotAllowed|permission/i.test(String(error&&error.name||'')+String(error&&error.message||''));markCapability('clipboard',denied?'declined':'broken',denied?'你没有允许使用剪贴板。':'复制失败。',denied?'可在浏览器权限里允许，或改用导出文件。':'请改用导出备份。');dataFeedback('没有复制成功；当前数据未改动。可改用导出备份。',true)}});
document.querySelector('[data-capability-doctor]')?.addEventListener('click',event=>{const button=event.target.closest('[data-decline-capability]');if(!button)return;const id=button.dataset.declineCapability,cap=(appState.runtimeCapabilities||emptyCapabilities())[id];if(cap&&cap.status==='declined'){markCapability(id,'ready','','');probeCapabilities()}else markCapability(id,'declined','你已关闭这项可选能力。','需要时再点重新启用。');try{persist(appState)}catch(error){}});
document.querySelector('[data-first-run-dismiss]')?.addEventListener('click',()=>{appState.firstRunSeen=true;try{persist(appState)}catch(error){}renderFirstRun()});
document.querySelector('[data-first-run-more]')?.addEventListener('click',()=>{const details=document.querySelector('[data-first-run-details]'),button=document.querySelector('[data-first-run-more]');if(!details)return;details.hidden=!details.hidden;if(button)button.textContent=details.hidden?'怎么打开、怎么备份':'收起说明'});
document.querySelector('[data-first-run-again]')?.addEventListener('click',()=>{const details=document.querySelector('[data-first-run-settings-details]');if(details)details.hidden=false;dataFeedback('第一次说明在上方，可随时再看。')});
function bootFromLocalStorage(){try{const raw=localStorage.getItem(STORAGE_KEY);if(raw){const parsed=JSON.parse(raw);appState=normalize(parsed,{keepSnapshots:true});if(parsed.schemaVersion!==4||parsed.contractVersion!==WORKSPACE_CONTRACT)persist(appState)}else{appState=applyTonightSeeds(emptyState());if(recordCount(appState))persist(appState)}}catch(error){try{feedback(MODULES[0].id,'恢复失败，可以导入备份重试。',true)}catch(ignored){}}probeCapabilities();render();activateView(location.hash,{replace:true})}
bootFromLocalStorage();
document.querySelectorAll('[data-weekday]').forEach(node=>node.classList.toggle('is-today',Number(node.dataset.weekday)===(new Date().getDay()+6)%7));
(async function recoverFromIndexedDB(){if(localStorage.getItem(STORAGE_KEY)||!window.indexedDB)return;if(!(await indexedDBExists()))return;try{const raw=await readIndexedDB();if(!raw)return;const parsed=typeof raw==='string'?JSON.parse(raw):raw;appState=normalize(parsed,{keepSnapshots:true});appState.storageBackend='indexeddb';probeCapabilities();render()}catch(error){}})();
"""
    has_life_modules = any(str(row["id"]).startswith("life-") for row in modules)
    composition = validate_compiled_composition(
        product.get("recommendation_plan", {}).get("composition_contract")
    )
    pack = (composition or {}).get("pack") or {}
    runtime_id = str(pack.get("runtime_binding", {}).get("runtime_id") or "")
    return (source.replace("__STORAGE_KEY__", _safe_script_json(storage_key))
            .replace("__PRODUCT_ID__", _safe_script_json(product["product_id"]))
            .replace("__PACK_ID__", _safe_script_json(product["recommendation_plan"]["pack_id"]))
            .replace("__COMPOSITION_ID__", _safe_script_json(str(pack.get("composition_id") or product["recommendation_plan"]["pack_id"])))
            .replace("__MODULES__", _safe_script_json(modules))
            .replace("__FINANCE_MODULE_IDS__", _safe_script_json(finance_module_ids))
            .replace("__LEDGER_CSV_SPECS__", _safe_script_json(LEDGER_CSV_SPECS))
            .replace("__COMPOSITION_PACK__", _safe_script_json(pack or None))
            .replace("__SCENE_RUNTIME_HELPERS__", _runtime_fragment(runtime_id, "helpers"))
            .replace("__SCENE_RUNTIME_RENDER__", RUNTIME_RENDER_CALLS.get(runtime_id, ""))
            .replace("__SCENE_RUNTIME_LISTENERS__", _runtime_fragment(runtime_id, "listeners"))
            .replace("__LIFE_HELPERS__", _LIFE_HELPERS if has_life_modules else "")
            .replace("__LIFE_RENDER__", "renderLifeDashboard();renderLifeGoals()" if has_life_modules else "")
            .replace("__LIFE_LISTENERS__", _LIFE_LISTENERS if has_life_modules else "")
            .replace("__LIFE_MOVEMENT__", _LIFE_MOVEMENT if has_life_modules else "")
            .replace("__ATOMIC_LISTENERS__", _ATOMIC_LISTENERS))


def _html(product: dict[str, Any], design: dict[str, Any], token: dict[str, Any], template: dict[str, Any], build_id: str, storage_key: str) -> str:
    primary_id = product["design_brief"]["primary_capability_id"]
    composition_contract = validate_compiled_composition(
        product.get("recommendation_plan", {}).get("composition_contract")
    )
    composition_pack = (composition_contract or {}).get("pack", {})
    if composition_contract:
        selected_module_ids = list(product["recommendation_plan"].get("selected_core_module_ids", []))
        if selected_module_ids != composition_pack.get("exact_module_ids"):
            raise ContractError("product selected scope 与 composition contract 不一致")
        if design["current"].get("renderer_id") != composition_pack.get("renderer_id"):
            raise ContractError("design renderer 与 composition contract 不一致")
        if design["current"].get("scene_template_id") != composition_pack.get("scene_template_id"):
            raise ContractError("design scene template 与 composition contract 不一致")
    capability_supply = product.get("recommendation_plan", {}).get("capability_supply_snapshot", {})
    compiled_paths = capability_supply.get("module_paths", [])
    reliability_envelope = capability_supply.get("reliability_envelope", {})
    atomic_ids_by_module = {
        str(path["module_id"]): sorted({
            str(atom_id)
            for capability_path in path.get("capability_paths", [])
            for atom_id in capability_path.get("atomic_capability_ids", [])
        })
        for path in compiled_paths
        if isinstance(path, dict) and path.get("module_id")
    }
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
        row["atomic_capability_ids"] = atomic_ids_by_module.get(module_id, [])
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
    _apply_pack_visible_copy(capabilities, composition_pack)
    _apply_gongkao_civil_overlay(capabilities, composition_pack)
    experience, palette = design["experience"], template["palette"]
    sidebar_ink = _contrast_ink(str(palette["sidebar"]), str(palette["ink"]))
    primary_ink = _contrast_ink(str(palette["primary"]), str(palette["ink"]))
    scene_template_id = design["current"].get("scene_template_id") or "general_workbench"
    emojis = _emojis([str(row["name"]) for row in capabilities], {template["motif"]})
    rendered = render_scene(
        product, design, capabilities, template,
        {
            "detail_renderer": partial(
                _surface_section,
                composition_contract=composition_contract,
            ),
            "emojis": emojis,
        },
    )
    if rendered["renderer_id"] != design["current"]["renderer_id"]:
        raise ContractError("renderer 输出与 design 锁不一致")
    dashboard_html = rendered["dashboard_html"].replace(
        "data-view-id='dashboard'", "data-view-id='dashboard' data-layout-level='home'", 1
    )
    opening = dashboard_html.find(">")
    if opening < 0:
        raise ContractError("dashboard 缺少开口标签")
    first_run = (
        "<aside class='first-run' data-first-run hidden>"
        "<div><span class='eyebrow'>第一次打开</span>"
        "<p>先做首页标出的那一件。记录只在这台设备；换电脑前先导出备份。</p></div>"
        "<div class='form-actions'>"
        "<button type='button' class='tiny' data-first-run-more>怎么打开、怎么备份</button>"
        "<button type='button' class='tiny' data-first-run-dismiss>知道了，开始</button>"
        "</div>"
        "<div data-first-run-details hidden><ol>"
        "<li>今天先看首页最上面的一件事，点进去做完。</li>"
        "<li>你写下的内容只留在这台设备的这个浏览器里，没有云同步。</li>"
        "<li>换电脑或重装浏览器前，到本地数据里导出备份。</li>"
        "<li>电脑上的 Chrome 可以把这个页面用应用窗口打开：菜单 → 更多工具 → 创建快捷方式 → 勾选「作为窗口打开」。这不是已经上架或已经安装的应用，也不需要联网字体。</li>"
        "</ol></div></aside>"
    )
    dashboard_html = (
        dashboard_html[: opening + 1]
        + first_run
        + "<p class='adult-warmth' data-adult-warmth hidden></p>"
        + dashboard_html[opening + 1 :]
    )
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
    theme_bundle = _theme_bundle(product, design)
    theme_root_attributes = _theme_root_attributes(theme_bundle)
    script = _script(product, capabilities, storage_key)
    has_finance_csv = any(
        {"entry_type", "amount"} <= {field["field_id"] for field in row["surface"]["fields"]}
        for row in capabilities
    )
    finance_csv_control = "<button class='secondary' data-double6-hook='export-csv'>导出财务 CSV</button>" if has_finance_csv else ""
    ledger_csv_modules = [
        row for row in capabilities
        if row.get("recommendation_module_id") in LEDGER_CSV_SPECS
    ]
    ledger_csv_control = ""
    if ledger_csv_modules:
        options = "".join(
            f"<option value='{_e(row['recommendation_module_id'])}'>{_e(str(LEDGER_CSV_SPECS[row['recommendation_module_id']].get('label') or row['name']))}</option>"
            for row in ledger_csv_modules
        )
        ledger_csv_control = (
            "<section class='atomic-tool ledger-csv-tool' data-atomic-tool='atom.shared.import-ledger-csv' data-ledger-csv-tool>"
            "<span class='eyebrow'>台账 CSV</span><h3>给这一本记录表追加或替换</h3>"
            "<p>只出现在成人设置，不占首页。确认前当前数据未改动。不是已发货、已申报或已发送。</p>"
            f"<label><span>台账</span><select data-ledger-csv-module>{options}</select></label>"
            "<label><span>方式</span><select data-ledger-csv-mode><option value='append'>追加</option><option value='replace'>只替换这一本</option></select></label>"
            "<label class='today-import'><span>选择 CSV</span><input data-ledger-csv-file type='file' accept='text/csv,.csv'></label>"
            "<section class='atomic-tool import-preview' data-ledger-csv-preview hidden><span class='eyebrow'>CSV 预览</span><div class='atomic-output' data-ledger-csv-summary></div>"
            "<div class='form-actions'><button type='button' data-ledger-csv-confirm>确认导入这本台账</button><button type='button' class='secondary' data-ledger-csv-cancel>取消</button></div></section></section>"
        )
    selected_csv_modules = [
        row for row in capabilities
        if "atom.shared.export-selected-csv" in row.get("atomic_capability_ids", [])
    ]
    selected_csv_control = ""
    if selected_csv_modules:
        options = "".join(
            f"<option value='{_e(row['recommendation_module_id'])}'>{_e(row['name'])}</option>"
            for row in selected_csv_modules
        )
        selected_csv_control = (
            "<section class='atomic-tool selected-csv-tool' data-atomic-tool='atom.shared.export-selected-csv'>"
            "<span class='eyebrow'>选定字段 CSV</span><h3>只导出一个已选模块</h3>"
            f"<label><span>模块</span><select data-csv-module>{options}</select></label>"
            "<div class='atomic-fact-list' data-csv-fields></div>"
            "<button type='button' class='secondary' data-double6-hook='export-selected-csv'>导出选定字段</button>"
            "<p class='atomic-output' data-selected-csv-output aria-live='polite'>先明确选择字段；公式前缀会被转义。</p></section>"
        )
    policy_binding = product["recommendation_plan"].get("policy_engine_binding", {})
    if policy_binding.get("maturity") != "executable_ready":
        raise ContractError("最终工作台缺少 executable_ready policy engine binding")
    icons = _icon_set_for(product, template["template_id"])
    page_icon = f"data:image/png;base64,{icons['64x64:favicon']}"
    pwa_head = _pwa_head(product, palette, icons)
    capability_depth_css = """
.personal-week-dashboard,.sales-followup-dashboard,.personal-week-dashboard>*{min-width:0;max-width:100%}
.week-command-metrics,.sales-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}
.week-command-metrics .metric-card,.sales-metrics .metric-card{border:1px solid var(--d6-line);background:var(--d6-card)}
.personal-quick-capture{display:grid;gap:10px;align-items:end;border:2px solid var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 7%,var(--d6-card))}
.personal-quick-capture label{display:grid;gap:7px;font-weight:900}.personal-quick-capture input{width:100%;min-height:48px;padding:11px 13px;border:1px solid var(--d6-line);border-radius:13px;background:var(--d6-card);color:var(--d6-ink)}
.personal-quick-capture p{grid-column:1/-1;color:var(--d6-ink)}
.week-outcome-board{border-top:6px solid var(--d6-primary)}
.week-outcome-lanes{display:grid;gap:9px;margin-bottom:16px}.week-outcome-composer{display:grid;gap:8px}.week-outcome-composer label{display:grid;gap:4px;font-size:.78rem;font-weight:900}.week-outcome-composer button{justify-self:start}.personal-outcome[draggable=true]{cursor:grab}
.personal-outcome-lane{display:grid;align-content:start;gap:8px;padding:13px;border-radius:15px;background:var(--d6-canvas)}
.personal-outcome{display:grid;gap:5px;padding:12px;border:1px solid var(--d6-line);border-radius:13px;background:var(--d6-card)}
.personal-outcome p{font-size:.86rem}.personal-outcome em,.personal-today-card em{font-size:.75rem;font-style:normal;color:var(--d6-primary-strong)}
.personal-outcome.is-complete,.personal-today-card.is-complete{opacity:.62;text-decoration:line-through}
.week-outcome-lanes span,.sales-stage-grid span{font-size:.76rem;font-weight:900;color:var(--d6-primary-strong)}
.week-flow-grid{display:grid;gap:10px}
.week-flow-card{display:grid;grid-template-columns:46px 1fr;gap:11px;padding:15px;border:1px solid var(--d6-line);border-radius:17px;background:var(--d6-card)}
.week-flow-card>span{width:40px;height:40px;display:grid;place-items:center;border-radius:13px;background:var(--d6-primary-strong);color:#fff;font-weight:950}
.week-flow-card small{display:block;margin-top:3px;color:var(--d6-ink)}
.personal-week-lower,.sales-work-grid{display:grid;gap:12px}
.blocker-board,.rhythm-board,.sales-object-chain,.manual-handoff-card{display:grid;align-content:start;gap:7px;padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-radius:24px;background:var(--d6-card);box-shadow:0 10px 28px color-mix(in srgb,var(--d6-ink) 8%,transparent)}
.blocker-board{border-left:6px solid var(--d6-accent)}
.rhythm-board,.manual-handoff-card{background:var(--d6-category-2)}
.rhythm-board .eyebrow,.rhythm-board .text-link,.manual-handoff-card .eyebrow,.manual-handoff-card .text-link{color:var(--d6-ink)}
.personal-today-focus>div:last-child,.personal-review-studio{display:grid;gap:10px}
.personal-today-card{display:grid;gap:10px;padding:12px;border:1px solid var(--d6-line);border-radius:14px;background:var(--d6-card);color:var(--d6-ink)}
.personal-today-card>div:first-child{display:grid;gap:3px}.personal-today-card .record-actions{display:flex;flex-wrap:wrap;gap:6px}
.personal-date-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;align-items:end}.personal-date-move label{display:grid;gap:4px;font-size:.76rem;font-weight:850}.personal-date-move select{min-height:44px}
.personal-top-list,.personal-candidate-list{display:grid;gap:9px}.personal-candidate-list{margin-top:12px;padding-top:12px;border-top:1px dashed var(--d6-line)}.personal-focus-heading{display:flex;justify-content:space-between;gap:10px;align-items:center}.personal-focus-heading small{font-size:.78rem}
.day-cell .personal-today-card{min-width:142px}.day-cell.today .personal-today-card{background:#fff;color:var(--d6-ink)}
.personal-empty-action,.personal-blocker-item{padding:13px;border:1px dashed var(--d6-line);border-radius:14px;background:var(--d6-canvas)}
.personal-collapsible>summary{display:flex;justify-content:space-between;align-items:center;gap:12px;cursor:pointer;list-style:none}.personal-collapsible>summary::-webkit-details-marker{display:none}.personal-collapsible>summary>span{display:grid;gap:3px}.personal-collapsible>summary>span:last-child{font-size:.8rem;font-weight:850;color:var(--d6-primary-strong)}.personal-collapsible[open]>summary{margin-bottom:16px}.personal-collapsible>summary:after{content:'展开';padding:6px 9px;border:1px solid var(--d6-line);border-radius:999px;font-size:.76rem;font-weight:900}.personal-collapsible[open]>summary:after{content:'收起'}
.personal-platform-tools{border-left:6px solid var(--d6-primary)}.personal-tool-grid{display:grid;gap:9px}.personal-tool-card{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}.personal-tool-card div{display:grid;gap:4px}.personal-tool-card p{font-size:.86rem}.personal-tool-card small{font-size:.76rem}.personal-tool-card button{min-height:44px}
.personal-review-studio{border-top:6px solid var(--d6-accent)}.review-actions{display:flex;flex-wrap:wrap;gap:9px}.personal-review-studio pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:16px;border-radius:16px;background:var(--d6-canvas);font:inherit}
.personal-week-dashboard .scene-hero{min-height:190px}.personal-now-panel{display:grid;gap:9px;border:0;background:var(--d6-primary-strong);color:#fff}.personal-now-panel .eyebrow{color:#fff}.personal-now-panel h2{font-size:clamp(1.55rem,4vw,2.35rem)}.personal-now-panel p{max-width:42rem}.personal-matter-board{display:grid;gap:10px;margin-top:10px}.personal-matter{display:grid;gap:4px;padding:14px;border-radius:16px;background:rgba(255,255,255,.16);color:#fff}.personal-matter span,.personal-matter small{font-size:.78rem;opacity:.88}.personal-matter p{margin:0}.personal-matter .tiny{justify-self:start;margin-top:6px;background:#fff;color:var(--d6-primary-strong);border:0;min-height:44px}.personal-now-panel .now-cta{display:inline-flex;align-items:center;justify-self:start;min-height:44px;margin-top:8px;padding:12px 18px;border-radius:14px;background:#fff;color:var(--d6-primary-strong);font-weight:900}.personal-attention-panel{border-left:6px solid var(--d6-accent)}.personal-attention-panel>[data-personal-attention]{display:grid;gap:8px}.personal-attention-panel>[data-personal-attention]>a{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:12px 14px;border-radius:14px;background:var(--d6-canvas)}.personal-attention-panel>[data-personal-attention]>a:after{content:'→';font-weight:950}.personal-attention-panel>[data-personal-attention] span{font-size:.78rem}.personal-workspace-switcher{margin-top:12px}.personal-workspace-switcher summary{display:flex;align-items:center;min-height:44px;cursor:pointer;font-weight:850}.personal-data-safety{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:15px;padding-top:13px;border-top:1px dashed var(--d6-line);font-size:.78rem}.personal-data-safety .today-actions{margin:0}.personal-data-safety button,.personal-data-safety .today-import{min-height:44px;padding:8px 10px;font-size:.78rem}
.personal-special-surface{display:grid;gap:16px;padding:clamp(18px,3vw,28px);border-radius:24px;background:var(--d6-canvas);border:1px solid var(--d6-line)}.personal-special-heading{display:flex;justify-content:space-between;align-items:start;gap:16px}.personal-special-heading h3{margin:.2rem 0;font-size:clamp(1.25rem,2.5vw,1.7rem)}.personal-special-heading>strong{padding:7px 10px;border-radius:999px;background:var(--d6-card);font-size:.78rem;white-space:nowrap}.personal-special-detail{justify-self:start}.personal-module-compose{padding:16px;border:1px dashed var(--d6-line);border-radius:18px;background:var(--d6-card)}.personal-generic-stack{display:grid;gap:16px}.personal-module-templates{display:grid;gap:9px;padding-top:12px;border-top:1px dashed var(--d6-line)}
.inbox-triage{border-top:7px solid var(--d6-category-3)}.personal-queue{display:grid;gap:10px}.inbox-triage-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center;padding:15px;border-radius:17px;background:var(--d6-card);border:1px solid var(--d6-line)}.inbox-triage-card>div:first-child{display:grid;gap:4px}.inbox-triage-card .record-actions{justify-content:flex-end;margin:0}
.week-capacity-board{border-top:7px solid var(--d6-primary)}.week-capacity-board .week-grid{padding:4px}.today-focus-room{border-top:7px solid var(--d6-accent)}.project-cockpit{border-top:7px solid var(--d6-category-4)}.personal-project-board{display:grid;gap:11px}.personal-project-card{display:grid;gap:12px;padding:16px;border-radius:18px;background:var(--d6-card);border:1px solid var(--d6-line)}.personal-project-card header{display:flex;gap:10px;align-items:center}.personal-project-card header span{padding:5px 8px;border-radius:999px;background:var(--d6-category-4);font-size:.74rem;font-weight:900}.personal-project-card dl{display:grid;gap:7px;margin:0}.personal-project-card dl div{display:grid;grid-template-columns:110px 1fr;gap:10px;padding-top:7px;border-top:1px dashed var(--d6-line)}.personal-project-card dt{font-size:.75rem;font-weight:900}.personal-project-card dd{margin:0}.personal-project-card button{justify-self:start}
.habit-week-grid{border-top:7px solid var(--d6-success)}.habit-week-grid>[data-personal-habit-grid]{display:grid;gap:11px}.habit-row{display:grid;gap:11px;padding:15px;border-radius:18px;background:var(--d6-card);border:1px solid var(--d6-line)}.habit-row>div:first-child{display:grid;gap:3px}.habit-days{display:grid;grid-template-columns:repeat(7,minmax(48px,1fr));gap:7px;overflow:auto}.habit-day{display:grid;place-items:center;gap:2px;min-height:62px;padding:6px;border:1px solid var(--d6-line);background:transparent;color:var(--d6-ink)}.habit-day span{font-size:.7rem}.habit-day strong{font-size:1.25rem}.habit-day.is-done{background:var(--d6-success);color:#fff;border-color:var(--d6-success)}
.life-timeline{border-top:7px solid var(--d6-category-2)}.life-timeline>[data-personal-life-timeline]{display:grid;gap:0}.life-fact-row{display:grid;grid-template-columns:92px minmax(0,1fr) auto;gap:13px;padding:15px 0;border-bottom:1px solid var(--d6-line)}.life-fact-row time{font-weight:900}.life-fact-row>div{display:grid;gap:3px}.life-fact-row>div>span{font-size:.72rem;color:var(--d6-primary-strong);font-weight:900}.review-workbench{border-top:7px solid var(--d6-accent)}.review-stepper{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:0;padding:0;list-style:none;counter-reset:review-step}.review-stepper li{display:grid;gap:4px;padding:11px;border-radius:14px;background:var(--d6-card);font-size:.78rem;font-weight:850}.review-stepper li:before{counter-increment:review-step;content:counter(review-step);width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:var(--d6-primary);color:#fff}.review-workbench .personal-review-studio{display:grid;gap:12px;padding-top:12px}.review-workbench .personal-review-studio summary{cursor:pointer;font-weight:900}
.sales-pipeline{border-top:6px solid var(--d6-primary)}
.sales-stage-grid{display:grid;gap:8px}
.sales-stage-grid>a{display:grid;gap:5px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}
.sales-stage-grid strong{font-size:1rem}
.content-now-panel{border:0;background:var(--d6-primary-strong);color:#fff}.content-now-panel .eyebrow{color:#fff}.content-now-panel h2{font-size:clamp(1.55rem,4vw,2.35rem)}.content-now-panel .now-cta{display:inline-flex;margin-top:8px;padding:12px 18px;border-radius:14px;background:#fff;color:var(--d6-primary-strong);font-weight:900}.content-due-strip{display:grid;gap:8px;margin-top:14px;padding-top:13px;border-top:1px solid rgba(255,255,255,.28)}.content-due-strip .today-item{background:#fff;color:var(--d6-ink)}.content-flow-panel{border-top:6px solid var(--d6-primary)}.content-home-flow{display:grid;gap:8px}.content-home-flow>a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}.content-home-flow>a strong{grid-row:1/3;grid-column:2;font-size:1.75rem}.content-home-flow small{font-size:.75rem}.content-home-capture{display:grid;gap:10px;align-items:end;border:2px solid var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 7%,var(--d6-card))}.content-home-capture label,.content-quick-form{display:grid;gap:6px;font-weight:850}.content-home-capture p{grid-column:1/-1}.content-attention-panel{border-left:6px solid var(--d6-accent)}.content-attention-panel>[data-content-attention]{display:grid;gap:8px}.content-attention-panel>[data-content-attention]>a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:12px;border-radius:14px;background:var(--d6-canvas)}.content-attention-panel>[data-content-attention]>a:after{content:'→';font-weight:950}.content-special-surface{display:grid;gap:15px;padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-top:7px solid var(--d6-primary);border-radius:24px;background:var(--d6-canvas)}.content-special-heading{display:flex;justify-content:space-between;align-items:start;gap:14px}.content-special-heading h3{margin:.2rem 0;font-size:clamp(1.25rem,2.5vw,1.7rem)}.content-special-heading>strong{padding:7px 10px;border-radius:999px;background:var(--d6-card);font-size:.78rem;white-space:nowrap}.content-quick-form{grid-template-columns:minmax(0,1fr);padding:13px;border:1px dashed var(--d6-line);border-radius:16px;background:var(--d6-card)}.content-card-list,.content-production-grid{display:grid;gap:10px}.content-work-card{display:grid;gap:10px;padding:15px;border:1px solid var(--d6-line);border-radius:17px;background:var(--d6-card)}.content-work-card>div:first-child{display:grid;gap:4px}.content-work-card>div:first-child>span{font-size:.72rem;font-weight:900;color:var(--d6-primary-strong)}.content-work-card.is-complete{border-color:var(--d6-success)}.content-work-card dl{display:grid;gap:5px;margin:7px 0}.content-work-card dl div{display:grid;grid-template-columns:90px 1fr;gap:8px;padding-top:5px;border-top:1px dashed var(--d6-line)}.content-work-card dt{font-size:.72rem;font-weight:900}.content-work-card dd{margin:0}.content-work-card em{font-size:.76rem;font-style:normal;font-weight:850;color:var(--d6-primary-strong)}.content-empty{padding:15px;border:1px dashed var(--d6-line);border-radius:15px;background:var(--d6-card)}.content-stage-board{display:grid;gap:9px;overflow:auto}.content-stage-board>section{display:grid;align-content:start;gap:8px;min-width:210px;padding:13px;border-radius:16px;background:var(--d6-card)}.content-stage-board>section>span{font-size:.78rem;font-weight:900;color:var(--d6-primary-strong)}.content-review-summary{display:grid;gap:8px}.content-review-summary article{display:grid;gap:3px;padding:12px;border-radius:14px;background:var(--d6-card)}.content-review-summary article strong{font-size:1.5rem}.content-source-inbox{border-top-color:var(--d6-category-3)}.content-topic-board{border-top-color:var(--d6-primary)}.content-brief-canvas{border-top-color:var(--d6-category-4)}.content-production-room{border-top-color:var(--d6-accent)}.content-publish-queue{border-top-color:var(--d6-category-2)}.content-review-lab{border-top-color:var(--d6-success)}
.sales-now-panel{border:0;background:var(--d6-primary-strong);color:#fff}.sales-now-panel .eyebrow{color:#fff}.sales-now-panel h2{font-size:clamp(1.55rem,4vw,2.35rem)}.sales-now-panel .now-cta{display:inline-flex;margin-top:8px;padding:12px 18px;border-radius:14px;background:#fff;color:var(--d6-primary-strong);font-weight:900}.sales-due-strip{display:grid;gap:8px;margin-top:14px;padding-top:13px;border-top:1px solid rgba(255,255,255,.28)}.sales-due-strip .today-item{background:#fff;color:var(--d6-ink)}.sales-flow-panel{border-top:6px solid var(--d6-primary)}.sales-home-flow{display:grid;gap:8px}.sales-home-flow>a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}.sales-home-flow>a strong{grid-row:1/3;grid-column:2;font-size:1.75rem}.sales-home-flow small{font-size:.75rem}.sales-home-capture{display:grid;gap:10px;align-items:end;border:2px solid var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 7%,var(--d6-card))}.sales-home-capture label{display:grid;gap:6px;font-weight:850}.sales-home-capture p{grid-column:1/-1}.sales-attention-panel{border-left:6px solid var(--d6-accent)}.sales-attention-panel>[data-sales-attention]{display:grid;gap:8px}.sales-attention-panel>[data-sales-attention]>a{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:12px;border-radius:14px;background:var(--d6-canvas)}.sales-attention-panel>[data-sales-attention]>a:after{content:'→';font-weight:950}.sales-special-surface{display:grid;gap:15px;padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-top:7px solid var(--d6-primary);border-radius:24px;background:var(--d6-canvas)}.sales-special-heading{display:flex;justify-content:space-between;align-items:start;gap:14px}.sales-special-heading h3{margin:.2rem 0;font-size:clamp(1.25rem,2.5vw,1.7rem)}.sales-special-heading>strong{padding:7px 10px;border-radius:999px;background:var(--d6-card);font-size:.78rem;white-space:nowrap}.sales-card-list{display:grid;gap:10px}.sales-work-card{display:grid;gap:10px;padding:15px;border:1px solid var(--d6-line);border-radius:17px;background:var(--d6-card)}.sales-work-card>div:first-child{display:grid;gap:5px}.sales-work-card>div:first-child>span{font-size:.72rem;font-weight:900;color:var(--d6-primary-strong)}.sales-work-card.is-complete{border-color:var(--d6-success)}.sales-work-card dl{display:grid;gap:5px;margin:7px 0}.sales-work-card dl div{display:grid;grid-template-columns:88px 1fr;gap:8px;padding-top:5px;border-top:1px dashed var(--d6-line)}.sales-work-card dt{font-size:.72rem;font-weight:900}.sales-work-card dd{margin:0}.sales-stage-board{display:grid;gap:9px;overflow:auto}.sales-stage-board>section{display:grid;align-content:start;gap:8px;min-width:220px;padding:13px;border-radius:16px;background:var(--d6-card)}.sales-stage-board>section>span{font-size:.78rem;font-weight:900;color:var(--d6-primary-strong)}.sales-status{justify-self:start;padding:5px 9px;border-radius:99px;background:var(--d6-category-2);font-size:.75rem;font-weight:900}.sales-overdue{color:var(--d6-error);font-weight:900}.sales-empty{padding:15px;border:1px dashed var(--d6-line);border-radius:15px;background:var(--d6-card)}.sales-review-room pre{white-space:pre-wrap;padding:14px;border-radius:15px;background:var(--d6-card);font:inherit}.sales-lead-qualification{border-top-color:var(--d6-category-3)}.sales-client-pipeline{border-top-color:var(--d6-primary)}.sales-followup-queue{border-top-color:var(--d6-error)}.sales-object-chain{border-top-color:var(--d6-category-4)}.sales-quote-workspace{border-top-color:var(--d6-accent)}.sales-review-room{border-top-color:var(--d6-success)}
.fitness-special-surface{display:grid;gap:15px;padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-top:7px solid var(--d6-primary);border-radius:24px;background:var(--d6-canvas)}.fitness-special-heading{display:flex;justify-content:space-between;align-items:start;gap:14px}.fitness-special-heading h3{margin:.2rem 0;font-size:clamp(1.25rem,2.5vw,1.7rem)}.fitness-special-heading>strong{padding:7px 10px;border-radius:999px;background:var(--d6-card);font-size:.78rem;white-space:nowrap}.fitness-dashboard .scene-hero,.fitness-hero{min-height:132px;align-items:center;padding:18px 20px}.fitness-dashboard .adult-warmth{display:none!important}.fitness-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.fitness-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45;opacity:.96}.fitness-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.fitness-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.fitness-daily-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.fitness-daily-grid{display:grid;gap:12px}@media(min-width:860px){.fitness-daily-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.fitness-daily-card{display:grid;gap:8px;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.fitness-daily-card strong{font-size:1.2rem}.fitness-inline-form{display:grid;gap:8px}.fitness-inline-form label{display:grid;gap:4px;font-size:.82rem;font-weight:700}.fitness-inline-form input{min-height:44px;padding:8px 10px;border-radius:12px;border:1px solid var(--d6-line)}.fitness-checkin-row{display:flex;flex-wrap:wrap;gap:8px}.fitness-week-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px}.fitness-day{display:grid;gap:2px;width:auto;min-width:0;min-height:64px;padding:6px 2px;border-radius:12px;border:1px solid var(--d6-line);background:var(--d6-card);text-align:center}.fitness-day span,.fitness-day small{font-size:.62rem;line-height:1.2}.fitness-day strong{font-size:.78rem}.fitness-day.is-today{border-color:var(--d6-primary);box-shadow:inset 0 0 0 1px var(--d6-primary)}.fitness-day.is-marked{background:var(--d6-primary);color:#fff;border-color:var(--d6-primary)}.fitness-day.is-marked small{color:#fff}.fitness-checkin-row button.is-selected{background:var(--d6-primary-strong);color:#fff;border-color:var(--d6-primary-strong)}.teacher-class-dashboard .scene-hero,.teacher-hero{min-height:132px;align-items:center;padding:18px 20px}.teacher-class-dashboard .adult-warmth{display:none!important}.teacher-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.teacher-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.teacher-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.teacher-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.teacher-class-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.teacher-class-grid{display:grid;gap:12px}@media(min-width:860px){.teacher-class-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.teacher-class-card{display:grid;gap:8px;align-content:start;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.teacher-duty-line{display:flex;justify-content:flex-start;align-items:flex-start;gap:8px;min-height:44px}.teacher-duty-line input{width:auto;flex:none;margin-top:4px}.teacher-duty-line span{flex:1;text-align:left}.teacher-duty-line.is-done span{text-decoration:line-through;opacity:.7}.teacher-att-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:6px 0;border-bottom:1px dashed var(--d6-line)}.teacher-att-actions,.teacher-follow-actions{display:flex;flex-wrap:wrap;gap:6px}.teacher-att-actions button.is-selected{background:var(--d6-primary-strong);color:#fff;border-color:var(--d6-primary-strong)}.teacher-follow-line{display:grid;gap:6px;padding:10px 0;border-bottom:1px dashed var(--d6-line)}.teacher-follow-line>div{display:grid;gap:3px}.teacher-follow-line small{display:block}.teacher-inline-form{display:grid;gap:8px}.teacher-inline-form input{min-height:44px}.teacher-empty{margin:0;font-size:.9rem}.teacher-privacy{margin:0;padding:10px 14px;border-radius:14px;background:var(--d6-category-2);font-weight:800}.research-tonight-dashboard .scene-hero,.research-hero{min-height:132px;align-items:center;padding:18px 20px}.research-tonight-dashboard .adult-warmth{display:none!important}.research-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.research-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.research-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.research-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.research-tonight-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.research-tonight-grid{display:grid;gap:12px}@media(min-width:860px){.research-tonight-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.research-tonight-card{display:grid;gap:8px;align-content:start;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.research-inline-form{display:grid;gap:8px}.research-inline-form input,.research-inline-form select,.research-inline-form textarea{min-height:44px}.research-inline-form textarea{min-height:88px}.research-claim-line,.research-evidence-line,.research-question-line{display:grid;gap:3px;padding:8px 0;border-bottom:1px dashed var(--d6-line)}.research-empty{margin:0;font-size:.9rem}.research-privacy{margin:0;padding:10px 14px;border-radius:14px;background:var(--d6-category-2);font-weight:800}.commerce-tonight-dashboard .scene-hero,.commerce-hero{min-height:132px;align-items:center;padding:18px 20px}.commerce-tonight-dashboard .adult-warmth{display:none!important}.commerce-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.commerce-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.commerce-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.commerce-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.commerce-tonight-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.commerce-tonight-grid{display:grid;gap:12px}@media(min-width:860px){.commerce-tonight-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.commerce-tonight-card{display:grid;gap:8px;align-content:start;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.commerce-inline-form{display:grid;gap:8px}.commerce-inline-form input,.commerce-inline-form select{min-height:44px}.commerce-order-line,.commerce-stock-line{display:grid;gap:6px;padding:10px 0;border-bottom:1px dashed var(--d6-line)}.commerce-order-line>div,.commerce-stock-line{display:grid;gap:3px}.commerce-order-line small,.commerce-stock-line small{display:block;font-weight:800}.commerce-order-actions{display:flex;flex-wrap:wrap;gap:6px}.commerce-service-line{display:flex;justify-content:flex-start;align-items:flex-start;gap:8px;min-height:44px}.commerce-service-line input{width:auto;flex:none;margin-top:4px}.commerce-service-line span{flex:1;text-align:left;display:grid;gap:2px}.commerce-service-line.is-done span{text-decoration:line-through;opacity:.7}.commerce-empty{margin:0;font-size:.9rem}.commerce-privacy{margin:0;padding:10px 14px;border-radius:14px;background:var(--d6-category-2);font-weight:800}.finance-tonight-dashboard .scene-hero,.finance-hero{min-height:132px;align-items:center;padding:18px 20px}.finance-tonight-dashboard .adult-warmth{display:none!important}.finance-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.finance-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.finance-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.finance-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.finance-tonight-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.finance-tonight-grid{display:grid;gap:12px}.finance-side-jobs{margin:4px 2px 0;font-weight:750}.finance-side-jobs a{font-weight:900;color:var(--d6-primary-strong);text-decoration:underline}@media(min-width:860px){.finance-tonight-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.finance-tonight-card{display:grid;gap:8px;align-content:start;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.finance-inline-form{display:grid;gap:8px}.finance-inline-form input,.finance-inline-form select{min-height:44px}.finance-tx-line{display:grid;gap:2px;padding:8px 0;border-bottom:1px dashed var(--d6-line)}.finance-tx-line strong{font-size:1.05rem}.finance-voucher-line{display:flex;justify-content:flex-start;align-items:flex-start;gap:8px;min-height:44px}.finance-voucher-line input{width:auto;flex:none;margin-top:4px}.finance-voucher-line.is-done span{text-decoration:line-through;opacity:.7}.finance-tax-line{display:grid;gap:6px;padding:10px 0;border-bottom:1px dashed var(--d6-line)}.finance-tax-line>div{display:grid;gap:3px}.finance-tax-line small{display:block;font-weight:800}.finance-empty{margin:0;font-size:.9rem}.finance-privacy{margin:0;padding:10px 14px;border-radius:14px;background:var(--d6-category-2);font-weight:800}.household-tonight-dashboard .scene-hero,.household-hero{min-height:132px;align-items:center;padding:18px 20px}.household-tonight-dashboard .adult-warmth{display:none!important}.household-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.household-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.household-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.household-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.household-tonight-now{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.household-tonight-grid{display:grid;gap:12px}@media(min-width:860px){.household-tonight-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}.household-tonight-card{display:grid;gap:8px;align-content:start;padding:16px;border-radius:20px;background:var(--d6-card);border:1px solid var(--d6-line)}.household-chore-line{display:flex;justify-content:flex-start;align-items:flex-start;gap:8px;min-height:44px}.household-chore-line input{width:auto;flex:none;margin-top:4px}.household-chore-line span{flex:1;text-align:left;display:grid;gap:2px}.household-chore-line small{display:block;font-weight:700}.household-chore-line.is-done span{text-decoration:line-through;opacity:.7}.household-tell-line{display:grid;gap:6px;padding:10px 0;border-bottom:1px dashed var(--d6-line)}.household-tell-line>div{display:grid;gap:3px}.household-tell-line small{display:block}.household-tell-actions{display:flex;flex-wrap:wrap;gap:6px}.household-inline-form{display:grid;gap:8px}.household-inline-form input,.household-inline-form select{min-height:44px}.household-empty{margin:0;font-size:.9rem}.household-privacy{margin:0;padding:10px 14px;border-radius:14px;background:var(--d6-category-2);font-weight:800}.exam-practice-dashboard{display:grid}@media(min-width:860px){.exam-practice-dashboard{grid-template-columns:minmax(0,1.4fr) minmax(260px,.85fr)}.exam-practice-dashboard>.scene-hero,.exam-practice-dashboard>.first-run,.exam-practice-dashboard>.adult-warmth{grid-column:1/-1}}.exam-practice-dashboard .scene-hero,.exam-hero{min-height:auto;align-items:center;padding:10px 16px}.exam-hero h1{display:none}.exam-practice-dashboard .hero-motif{display:none}.exam-practice-dashboard .adult-warmth{display:none!important}.exam-warmth{margin:6px 0 0;padding:0;border:0;max-width:38rem}.exam-warmth p{margin:0;font-size:1rem;font-weight:650}.exam-warmth cite{display:block;margin-top:4px;font-size:.75rem;opacity:.78}.exam-today-facts{margin:6px 0 0;font-size:.88rem;font-weight:850}.exam-now,.exam-module-paper{padding:clamp(16px,3vw,26px);border-top:6px solid var(--d6-primary)}.exam-module-paper{display:grid;gap:14px}.exam-practice-dashboard,.exam-practice-dashboard>*,.exam-now,.exam-module-paper{min-width:0;max-width:100%}.exam-topic-strip{display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;max-width:100%;min-width:0;-webkit-overflow-scrolling:touch;scrollbar-width:thin}.exam-topic{flex:none;min-height:44px;padding:8px 14px;border-radius:999px;border:2px solid var(--d6-line);background:var(--d6-card);color:var(--d6-ink);font-weight:850}.exam-topic.is-on{background:var(--d6-primary);color:var(--d6-primary-ink);border-color:var(--d6-primary)}.exam-question-card{display:grid;gap:12px}.exam-question-card h2{font-size:clamp(1.15rem,2.4vw,1.5rem);max-width:40ch}.exam-listen{width:auto;min-height:44px;justify-self:start;padding:8px 12px;background:transparent;color:var(--d6-ink);border:1px solid var(--d6-line)}.exam-options{display:grid;gap:8px}.exam-option{text-align:left;background:var(--d6-card);color:var(--d6-ink);border:2px solid var(--d6-line)}.exam-option.is-selected{border-color:var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 12%,var(--d6-card))}.exam-option.is-key{border-color:var(--d6-success);background:color-mix(in srgb,var(--d6-success) 14%,var(--d6-card))}.exam-option.is-bad{border-color:var(--d6-error);background:color-mix(in srgb,var(--d6-error) 12%,var(--d6-card))}.exam-result{padding:14px;border-radius:14px;background:var(--d6-canvas)}.exam-result strong{display:block;font-size:1.45rem;margin-bottom:6px}.exam-result.is-ok{border-left:6px solid var(--d6-success)}.exam-result.is-bad{border-left:6px solid var(--d6-error)}.exam-disclaimer{margin:12px 0 0;font-size:.86rem}.exam-topic-room .starter-open-view{flex:1;min-height:48px}.exam-plan-table{display:grid;gap:0;border:1px solid var(--d6-line);border-radius:18px;overflow:hidden;background:var(--d6-card)}.exam-plan-table>header{padding:10px 14px;background:var(--d6-primary);color:var(--d6-primary-ink);font-weight:850}.exam-plan-block{display:grid;grid-template-columns:28px 4.8rem minmax(0,1fr) auto;gap:10px;align-items:center;padding:12px 14px;border:0;border-bottom:1px solid var(--d6-line);border-radius:0;background:transparent}.exam-plan-block:last-child{border-bottom:0}.exam-plan-seq{width:26px;height:26px;border-radius:999px;background:var(--d6-primary);color:var(--d6-primary-ink);display:grid;place-items:center;font-weight:800;font-size:.82rem}.exam-plan-time{font-variant-numeric:tabular-nums;font-weight:850;font-size:.82rem;white-space:nowrap}.exam-plan-copy{display:grid;gap:3px}.exam-plan-block small{font-size:.82rem}.exam-plan-block.is-done{opacity:.7}.exam-plan-block.is-done strong{text-decoration:line-through}.exam-plan-actions{display:flex;gap:8px;flex-wrap:wrap}.exam-plan-actions .starter-open-view,.exam-plan-actions button{min-height:44px}.exam-plan-foot{margin:0;padding:10px 14px;font-size:.82rem;background:var(--d6-canvas);border-top:1px solid var(--d6-line);max-width:none}@media(max-width:520px){.exam-plan-block{grid-template-columns:28px auto minmax(0,1fr)}.exam-plan-actions{grid-column:1/-1}}[data-exam-home-submit]{width:100%;margin-top:12px}.exam-errors-panel [data-exam-error-list]{display:grid;gap:8px}.exam-error-line{text-align:left;background:var(--d6-canvas);color:var(--d6-ink);border:1px solid var(--d6-line)}.exam-empty{margin:0}.content-tonight-dashboard{display:grid}.content-tonight-dashboard .adult-warmth{display:none!important}.content-hero{min-height:132px;align-items:center;padding:18px 20px}.content-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.content-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.content-warmth cite{display:block;margin-top:4px;font-size:.75rem;font-style:normal;opacity:.78}.content-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.content-tonight-dashboard .content-now-panel{padding:clamp(16px,3vw,26px)}.content-piece-card{display:grid;gap:10px;padding:16px;border-radius:20px;background:#fff;color:var(--d6-ink)}.content-piece-card h2{margin:0;font-size:clamp(1.2rem,3vw,1.7rem);color:var(--d6-ink)}.content-opening-form{display:grid;gap:8px}.content-opening-form textarea{min-height:160px;font-size:1.05rem;line-height:1.5}.content-opening-meta{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.content-opening-meta button{width:auto}.content-piece-steps{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 12px}.content-step{padding:6px 10px;border-radius:999px;border:1px solid var(--d6-line);background:var(--d6-card);font-size:.82rem;font-weight:800}.content-step.is-on{background:var(--d6-primary);color:#fff;border-color:var(--d6-primary)}.content-publish-row{display:flex;flex-wrap:wrap;gap:8px}.content-publish-row>button{width:auto}.content-tonight-capture{margin-top:12px;padding:10px 12px;border-radius:16px;background:var(--d6-canvas)}.content-tonight-capture summary{cursor:pointer;font-weight:800}.content-tonight-capture .content-home-capture{margin-top:10px;border:1px dashed var(--d6-line);background:var(--d6-card)}.content-tonight-side{padding:clamp(16px,3vw,24px)}.content-tonight-dashboard .hero-progress,.content-tonight-dashboard .content-hero-progress{display:none!important}.content-week-panel{margin:12px 0;padding:0}.content-week-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px}.content-day{display:grid;gap:2px;min-width:0;min-height:56px;padding:6px 2px;border-radius:12px;border:1px solid var(--d6-line);background:var(--d6-card);text-align:center}.content-day span{font-size:.62rem}.content-day strong{font-size:.78rem}.content-day.is-today{border-color:var(--d6-primary)}.content-day.is-marked{background:var(--d6-primary);color:#fff;border-color:var(--d6-primary)}.content-tonight-flow{margin-top:12px}.content-tonight-flow summary{cursor:pointer;font-weight:800}.sales-tonight-dashboard{display:grid}.sales-tonight-dashboard .adult-warmth{display:none!important}.sales-tonight-dashboard .hero-progress,.sales-tonight-dashboard .sales-hero-progress{display:none!important}.sales-hero{min-height:132px;align-items:center;padding:18px 20px}.sales-warmth{margin:8px 0 0;padding:0;border:0;max-width:38rem}.sales-warmth p{margin:0;font-size:1.08rem;font-weight:650;line-height:1.45}.sales-today-facts{margin:8px 0 0;font-size:.88rem;font-weight:850}.sales-tonight-dashboard .sales-now-panel{padding:clamp(16px,3vw,26px)}.sales-today-card{display:grid;gap:10px;padding:16px;border-radius:20px;background:#fff;color:var(--d6-ink)}.sales-today-card h2{margin:0;font-size:clamp(1.2rem,3vw,1.7rem);color:var(--d6-ink)}.sales-today-actions{display:flex;flex-wrap:wrap;gap:8px}.sales-today-actions>button{width:auto}.sales-tonight-side{padding:clamp(16px,3vw,24px)}.sales-other-line{margin:0 0 8px;font-size:.9rem}.sales-tonight-flow,.sales-tonight-capture{margin-top:12px}.sales-tonight-flow summary,.sales-tonight-capture summary{cursor:pointer;font-weight:800}.sales-tonight-capture .sales-home-capture{margin-top:10px;border:1px dashed var(--d6-line);background:var(--d6-card)}@media(min-width:860px){.sales-tonight-dashboard{grid-template-columns:minmax(0,1.3fr) minmax(280px,.9fr)}.sales-tonight-dashboard>.scene-hero,.sales-tonight-dashboard>.first-run,.sales-tonight-dashboard>.adult-warmth{grid-column:1/-1}}@media(min-width:860px){.content-tonight-dashboard{grid-template-columns:minmax(0,1.3fr) minmax(280px,.9fr)}.content-tonight-dashboard>.scene-hero,.content-tonight-dashboard>.first-run,.content-tonight-dashboard>.adult-warmth{grid-column:1/-1}}.fitness-meal-line{margin:0;font-size:.9rem}.fitness-move-list,.fitness-now-moves{display:grid;gap:10px}.fitness-move-card{display:grid;gap:8px;padding:12px 13px;border:1px solid var(--d6-line);border-radius:17px;background:var(--d6-card);color:var(--d6-ink)}.fitness-move-card.is-compact{padding:10px 12px;gap:6px}.fitness-move-card>div{display:grid;gap:2px}.fitness-move-card>div>span{font-size:.72rem;font-weight:900;color:var(--d6-primary-strong)}.fitness-move-card.is-complete{border-color:var(--d6-success)}.fitness-move-card.is-stopped{border-color:var(--d6-accent)}.content-now-panel .fitness-move-card{background:#fff}.content-now-panel[data-fitness-now-panel] h2{font-size:clamp(1.2rem,3.4vw,1.7rem)}.fitness-set-row{display:flex;flex-direction:row;flex-wrap:wrap;gap:8px;align-items:center}.fitness-set-row>button{width:auto!important;flex:0 0 auto!important;min-width:4.5rem;max-width:none;display:inline-flex;justify-content:center}.content-now-panel[data-fitness-now-panel] p{margin:.2rem 0}.fitness-set-btn.is-done{background:var(--d6-success);color:#fff;border-color:var(--d6-success)}.composition-dashboard[data-fitness-home] .scene-hero{min-height:148px}
@media(max-width:520px){.fitness-dashboard .scene-hero,.fitness-hero,.composition-dashboard[data-fitness-home] .scene-hero{min-height:112px;align-items:center;padding:16px 14px}.fitness-warmth p{font-size:.98rem}.fitness-special-heading{display:grid}.content-now-panel[data-fitness-now-panel] p{display:none}.content-now-panel[data-fitness-now-panel] h2{font-size:1.15rem}}
@media(min-width:760px){.personal-quick-capture{grid-template-columns:minmax(0,1fr) auto}.week-outcome-lanes{grid-template-columns:repeat(3,minmax(0,1fr))}.week-flow-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.personal-tool-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.personal-week-lower{grid-template-columns:repeat(2,minmax(0,1fr))}.personal-project-board{grid-template-columns:repeat(2,minmax(0,1fr))}.sales-stage-grid{grid-template-columns:repeat(5,minmax(0,1fr))}.sales-work-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.content-home-flow,.sales-home-flow{grid-template-columns:repeat(3,minmax(0,1fr))}.content-home-capture{grid-template-columns:repeat(2,minmax(0,1fr)) auto}.sales-home-capture{grid-template-columns:repeat(3,minmax(0,1fr)) auto}.content-quick-form{grid-template-columns:minmax(0,1fr) minmax(0,1.2fr) auto}.content-stage-board{grid-template-columns:repeat(4,minmax(210px,1fr))}.sales-stage-board{grid-auto-flow:column;grid-auto-columns:minmax(220px,1fr)}.content-production-grid,.content-brief-list{grid-template-columns:repeat(2,minmax(0,1fr))}.content-review-summary{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:520px){.personal-tool-card,.inbox-triage-card,.life-fact-row{grid-template-columns:1fr}.personal-tool-card button{justify-self:start}.personal-collapsible>summary{align-items:start}.personal-collapsible>summary>span:last-child{display:none}.personal-special-heading,.content-special-heading,.sales-special-heading,.personal-data-safety{display:grid}.personal-data-safety .today-actions{display:grid;grid-template-columns:1fr 1fr}.review-stepper{grid-template-columns:repeat(2,minmax(0,1fr))}.personal-project-card dl div,.content-work-card dl div,.sales-work-card dl div{grid-template-columns:1fr}.habit-days{grid-template-columns:repeat(7,52px)}}
@media(min-width:900px){.creator-dashboard .pipeline{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:520px){.week-command-metrics,.sales-metrics{grid-template-columns:1fr}.week-outcome-board .week-grid{grid-template-columns:repeat(7,56px)}}
"""
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content="{CSP_POLICY}"><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='theme-color' content='{_e(palette['primary'])}'><link rel='icon' type='image/png' href='{page_icon}'><link rel='shortcut icon' type='image/png' href='{page_icon}'>{pwa_head}<title>{_e(product['title'])}</title><style>
:root{{--d6-sidebar-ink:{_contrast_ink(palette['sidebar'], palette['ink'])};--d6-primary-ink:{_contrast_ink(palette['primary'], palette['ink'])};--d6-accent-ink:{_contrast_ink(palette['accent'], palette['ink'])};--d6-canvas:{palette['canvas']};--d6-sidebar:{palette['sidebar']};--d6-sidebar-ink:{sidebar_ink};--d6-card:{palette['card']};--d6-ink:{palette['ink']};--d6-muted:{palette['muted']};--d6-line:{palette['line']};--d6-primary:{palette['primary']};--d6-primary-ink:{primary_ink};--d6-primary-strong:{palette['primary_strong']};--d6-accent:{palette['accent']};--d6-category-1:{palette['category_1']};--d6-category-2:{palette['category_2']};--d6-category-3:{palette['category_3']};--d6-category-4:{palette['category_4']};--d6-success:{token['success']};--d6-error:{token['error']}}}
	*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--d6-canvas);color:var(--d6-ink);font:16px/1.5 {token['font']},sans-serif}}button,input,textarea,select{{font:inherit}}input,textarea,select{{font-size:16px}}button,input[type=file],a{{min-height:44px}}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,a:focus-visible{{outline:3px solid var(--d6-accent);outline-offset:2px}}a{{color:inherit;text-decoration:none}}button{{border:0;border-radius:14px;padding:11px 16px;background:var(--d6-primary-strong);color:#fff;font-weight:850;cursor:pointer}}button.secondary,button.tiny,.today-import{{background:transparent;color:var(--d6-ink);border:1px solid var(--d6-line);box-shadow:none}}button.tiny{{min-height:44px;padding:8px 10px;font-size:.82rem}}input[type=checkbox],input[type=radio]{{width:22px;height:22px;min-height:22px;min-width:22px}}label:has(>input[type=checkbox]),label:has(>input[type=radio]){{min-height:44px;display:flex;align-items:center;gap:8px}}button.danger{{color:var(--d6-error)}}h1{{font-size:clamp(1.375rem,2vw,1.5625rem);line-height:1.2;margin:.3em 0;max-width:22ch;letter-spacing:-.02em}}h2{{font-size:clamp(1.35rem,3vw,1.9rem);margin:0}}p{{margin:.35rem 0;max-width:66ch}}small{{color:var(--d6-ink)}}
	.app{{max-width:1460px;margin:auto;padding:12px 12px 12px 96px;display:grid;gap:16px}}.mobile-brand,.brand{{display:flex;gap:10px;align-items:center;font-weight:900}}.mobile-brand{{font-size:.875rem}}.brand-mark{{width:42px;height:42px;display:grid;place-items:center;border-radius:14px;background:var(--d6-primary);font-size:24px}}.identity-nav{{display:none}}.app-view{{grid-column:1/-1}}.app-view[hidden]{{display:none!important}}.dashboard-view{{display:grid;gap:16px}}.adult-warmth{{margin:0;padding:10px 14px;border-radius:14px;background:color-mix(in srgb,var(--d6-accent) 22%,#fff);font-weight:850}}.scene-hero{{position:relative;overflow:hidden;min-height:240px;display:flex;align-items:center;padding:clamp(26px,5vw,54px);border-radius:30px;background:linear-gradient(120deg,{palette['hero_gradient'][0]},{palette['hero_gradient'][1]});color:#fff}}.scene-hero>div{{position:relative;z-index:1;display:grid;justify-items:start;gap:8px}}.hero-kicker{{font-weight:900}}.scene-hero p{{font-size:1.02rem}}.hero-motif{{position:absolute;right:5%;top:4%;font-size:clamp(92px,17vw,180px);opacity:.2}}.primary-cta{{display:inline-flex;align-items:center;margin-top:8px;padding:12px 18px;border-radius:14px;background:#fff;color:var(--d6-primary-strong);font-weight:900}}.hero-progress{{font-size:.84rem;opacity:.95}}.eyebrow{{font-size:.8rem;font-weight:900;color:var(--d6-primary-strong)}}.dashboard-panel,.workspace,.data-tools,.child-support>section,.creator-lower>section,.lesson-side>section,.delivery-grid>section,.booking-strip,.reconcile-note,.household-columns>section,.recovery-panel,.generic-support{{padding:clamp(18px,3vw,28px);border:1px solid var(--d6-line);border-radius:24px;background:var(--d6-card);box-shadow:0 10px 28px color-mix(in srgb,var(--d6-ink) 8%,transparent)}}.panel-heading{{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:16px}}.text-link{{display:inline-flex;align-items:center;margin-top:12px;font-weight:900;color:var(--d6-primary-strong)}}.tonight-room-strip{{display:flex;flex-wrap:wrap;gap:8px 14px;margin:10px 0}}.tonight-room-strip a{{margin-top:0;text-decoration:underline}}.today-workboard{{display:grid;gap:12px;border-top:6px solid var(--d6-accent)}}.today-workboard h2{{font-size:1.2rem}}.today-items{{display:grid;gap:8px}}.today-item{{display:grid;grid-template-columns:1fr auto;align-items:center;gap:10px;padding:12px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}}.today-item.is-overdue{{border-color:var(--d6-error);background:color-mix(in srgb,var(--d6-error) 8%,var(--d6-card))}}.today-item small{{display:block}}.today-actions{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}.today-import{{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:11px 16px;border-radius:14px;font-weight:850;cursor:pointer}}.backup-reminder{{padding:9px 12px;border-radius:12px;background:var(--d6-category-2);font-weight:800}}
	.child-layout,.creator-lower,.lesson-grid,.close-grid,.fitness-layout{{display:grid;gap:16px}}.child-greeting{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:4px 4px}}.child-greeting h2{{font-size:clamp(1.25rem,2vw,1.5rem)}}.child-mode-switch{{display:flex;gap:7px;flex-wrap:wrap}}.child-mode-switch button.active{{background:var(--d6-primary);color:#fff;border-color:var(--d6-primary)}}.child-parent-review{{display:grid;gap:12px}}.child-parent-boundary{{padding:12px;border-radius:14px;background:var(--d6-category-2)}}.child-dashboard .scene-hero{{min-height:176px}}.child-dashboard .scene-hero h1{{max-width:22ch}}.learning-task-grid{{display:grid;gap:10px}}.learning-task{{display:grid;grid-template-columns:34px 46px 1fr;align-items:center;gap:10px;min-height:82px;padding:12px;border-radius:19px;background:var(--d6-category-1)}}.learning-task:nth-child(2){{background:var(--d6-category-2)}}.learning-task:nth-child(3){{background:var(--d6-category-3)}}.learning-task:nth-child(4){{background:var(--d6-category-4)}}.learning-task small{{grid-column:3}}.task-number{{font-weight:950;opacity:.55}}.task-icon,.capability-emoji{{width:46px;height:46px;display:grid;place-items:center;border-radius:14px;background:#fff;font-size:24px}}.child-support,.lesson-side{{display:grid;gap:12px}}.reward-card strong,.metric-card strong,.countdown-card strong{{display:block;font-size:2rem}}.progress-track{{height:10px;margin:12px 0;border-radius:99px;background:var(--d6-line);overflow:hidden}}.progress-track i{{display:block;width:0;height:100%;background:var(--d6-accent)}}.mini-action-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px}}.mini-action-grid span,.mini-action-grid .mini-action{{display:grid;place-items:center;min-height:58px;padding:8px;border-radius:14px;background:var(--d6-category-2);font-size:.82rem;font-weight:850;text-align:center}}.mini-action-grid span:nth-child(2),.mini-action-grid .mini-action:nth-child(2){{background:var(--d6-category-3)}}.mini-action-grid span:nth-child(3),.mini-action-grid .mini-action:nth-child(3){{background:var(--d6-category-1)}}.mini-action-grid span:nth-child(4),.mini-action-grid .mini-action:nth-child(4){{background:var(--d6-category-4)}}.reward-box{{background:var(--d6-primary)!important;color:#fff}}.reward-box p{{font-size:.82rem}}
.production-board{{border-top:6px solid var(--d6-primary)}}.pipeline{{display:grid;gap:12px}}.pipeline-stage{{display:grid;grid-template-columns:44px 1fr;align-items:center;gap:8px;padding:16px;border-bottom:1px solid var(--d6-line)}}.pipeline-stage>span{{grid-row:1/3;width:40px;height:40px;display:grid;place-items:center;border-radius:50%;background:var(--d6-primary);color:#fff;font-weight:900}}.pipeline-stage small{{grid-column:2}}.publish-reminder{{background:var(--d6-sidebar)!important}}.publish-reminder strong{{display:block;font-size:1.35rem}}.lesson-timeline ol,.circuit,.route-line{{list-style:none;padding:0;margin:0;display:grid;gap:9px}}.lesson-timeline li,.circuit li,.route-line li{{display:grid;grid-template-columns:54px 1fr;gap:12px;padding:13px;border-radius:15px;background:var(--d6-canvas)}}.lesson-timeline li>span,.circuit li>span,.route-line li>span{{font-weight:950;color:var(--d6-primary)}}.milestone-rail{{background:var(--d6-sidebar)}}.rail{{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}}.rail span{{padding:11px 4px;text-align:center;border-top:4px solid var(--d6-line);font-weight:850}}.rail .done{{border-color:var(--d6-primary)}}.delivery-grid,.booking-strip,.household-columns{{display:grid;gap:12px}}.delivery-grid strong,.booking-strip strong,.household-columns strong{{display:block;font-size:1.18rem}}
.travel-overview{{display:grid;gap:16px}}.countdown-card{{padding:24px;border-radius:24px;background:var(--d6-primary-strong);color:#fff}}.countdown-card small{{color:#fff;opacity:.85}}.booking-strip>div{{padding:10px;border-bottom:1px solid var(--d6-line)}}.finance-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.metric-card{{padding:16px;border-radius:18px;background:var(--d6-sidebar)}}.ledger-lines{{display:grid;gap:8px}}.ledger-lines>div{{display:flex;justify-content:space-between;gap:12px;padding:12px;border-bottom:1px solid var(--d6-line)}}.status-pill{{padding:5px 9px;border-radius:99px;background:var(--d6-category-4);font-size:.78rem;font-weight:900}}.week-grid{{display:grid;grid-template-columns:repeat(7,minmax(64px,1fr));gap:7px;overflow:auto;padding-bottom:4px;max-width:100%;min-width:0}}.day-cell{{display:grid;gap:12px;min-height:92px;padding:10px;border:1px solid var(--d6-line);border-radius:14px}}.day-cell.today{{background:var(--d6-primary-strong);color:#fff}}.week-bars{{display:flex;align-items:end;gap:7px;height:72px;margin:16px 0}}.week-bars i{{flex:1;height:16%;border-radius:8px 8px 2px 2px;background:var(--d6-primary)}}.week-bars i:nth-child(2),.week-bars i:nth-child(5){{height:55%}}.week-bars i:nth-child(4){{height:85%}}.generic-card-grid{{display:grid;gap:10px}}.generic-work-card{{display:grid;grid-template-columns:46px 1fr;gap:10px;padding:14px;border:1px solid var(--d6-line);border-radius:16px}}
.life-metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}.life-card-grid{{display:grid;gap:10px}}.life-today-card{{display:grid;grid-template-columns:42px 1fr;gap:10px;padding:14px;border:1px solid var(--d6-line);border-left:6px solid var(--d6-category-1);border-radius:17px;background:var(--d6-card)}}.life-today-card:nth-child(2n){{border-left-color:var(--d6-category-3)}}.life-today-card>span{{font-size:1.65rem}}.life-today-card small{{display:block;margin-top:3px}}.life-support{{padding:20px;border-radius:24px;background:var(--d6-sidebar)}}.life-calendar{{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin:13px 0}}.life-calendar span{{display:grid;place-items:center;min-height:34px;border-radius:10px;background:var(--d6-card);font-size:.8rem;font-weight:800}}.life-calendar span.done{{background:var(--d6-primary);color:#fff}}.life-calendar span.today{{outline:2px solid var(--d6-accent);outline-offset:1px}}
	.learning-feature{{display:grid;gap:9px;padding:18px;border-radius:20px;background:var(--d6-category-2)}}.learning-feature h3{{margin:0;font-size:1.1rem}}.learning-feature ul{{display:flex;flex-wrap:wrap;gap:7px;margin:0;padding:0;list-style:none}}.learning-feature li{{padding:6px 10px;border-radius:999px;background:var(--d6-card);font-size:.82rem;font-weight:850}}.starter-surface{{display:grid;gap:14px;padding:clamp(16px,3vw,24px);border:2px solid color-mix(in srgb,var(--d6-primary) 35%,var(--d6-line));border-radius:22px;background:var(--d6-card)}}.starter-heading{{display:flex;justify-content:space-between;align-items:start;gap:12px}}.starter-heading h3{{margin:.25rem 0;font-size:1.15rem}}.starter-content{{display:grid;gap:12px}}.starter-card{{display:grid;gap:11px;padding:16px;border:1px solid var(--d6-line);border-radius:18px;background:var(--d6-card)}}.starter-card h4{{margin:0;font-size:1.12rem}}.starter-kind,.starter-card-meta{{font-size:.78rem;font-weight:900;color:var(--d6-primary-strong)}}.starter-card-meta{{display:flex;justify-content:space-between;gap:10px}}.quest-mission{{display:grid;gap:3px;padding:11px 13px;border-radius:14px;background:var(--d6-category-1);border:1px dashed color-mix(in srgb,var(--d6-primary) 50%,var(--d6-line))}}.quest-mission span{{font-size:.74rem;font-weight:900;color:var(--d6-primary-strong)}}.quest-mission strong{{font-size:.95rem}}.quest-story{{padding-left:12px;border-left:3px solid var(--d6-accent);color:var(--d6-muted);font-size:.92rem}}.quest-hint{{padding:9px 11px;border-radius:12px;background:var(--d6-category-2)}}.quest-hint summary{{cursor:pointer;font-weight:850}}.quest-hint p{{margin-top:7px}}.starter-options{{display:grid;gap:9px}}.starter-option{{width:100%;min-height:48px;text-align:left;background:var(--d6-canvas);color:var(--d6-ink);border:2px solid var(--d6-line)}}.starter-option.is-selected{{border-color:var(--d6-primary);background:color-mix(in srgb,var(--d6-primary) 12%,var(--d6-card))}}.starter-answer,.starter-calculator-inputs{{display:grid;gap:8px}}.starter-calculator-inputs label{{display:grid;gap:5px;font-weight:800}}.starter-actions{{display:flex;gap:9px;flex-wrap:wrap;position:static}}.starter-actions button,.starter-open-view{{min-height:48px}}.starter-open-view{{display:inline-flex;align-items:center;justify-content:center;padding:11px 16px;border-radius:14px;background:var(--d6-primary-strong);color:#fff;font-weight:850}}.starter-result{{padding:13px;border-left:5px solid currentColor;border-radius:12px;background:var(--d6-canvas)}}.starter-result p{{max-width:none}}.starter-draft-material{{padding:12px 14px;border-radius:14px;background:var(--d6-canvas);line-height:1.55}}.starter-draft-field{{display:grid;gap:6px}}.starter-draft-field span{{font-size:.8rem;font-weight:850}}.starter-draft-field textarea{{width:100%;min-height:108px;padding:12px;border:1px solid var(--d6-line);border-radius:14px;font:inherit;line-height:1.5;resize:vertical}}.starter-draft-count{{margin:0;font-size:.78rem}}.starter-keypad-answer{{display:grid;gap:9px}}[data-keypad-display]{{display:block;min-height:52px;padding:10px 14px;border:2px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);font-size:1.5rem;font-weight:900;text-align:center;letter-spacing:.08em}}.starter-keypad{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:340px}}.keypad-key{{min-height:52px;border-radius:14px;border:2px solid var(--d6-line);background:var(--d6-card);font-size:1.25rem;font-weight:900;color:var(--d6-ink)}}.keypad-key:active{{background:color-mix(in srgb,var(--d6-primary) 18%,var(--d6-card));transform:scale(.96)}}.generator-question{{margin:0;padding:12px;border-radius:14px;background:var(--d6-canvas);font-size:1.35rem;font-weight:900;text-align:center}}.generator-streak{{margin:0;font-weight:850;color:var(--d6-primary-strong);text-align:center}}.reward-economy{{display:grid;gap:16px;padding:clamp(16px,3vw,24px);border:2px solid color-mix(in srgb,var(--d6-accent) 45%,var(--d6-line));border-radius:22px;background:color-mix(in srgb,var(--d6-card) 80%,var(--d6-category-3))}}.reward-balance-card{{display:grid;gap:4px;padding:16px;border-radius:18px;background:var(--d6-card);text-align:center}}.reward-balance-card strong{{font-size:2.1rem;font-weight:950}}.reward-balance-card small{{color:var(--d6-muted);font-weight:750}}.reward-section{{display:grid;gap:10px}}.reward-shop-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}}.reward-shop-item{{display:grid;gap:5px;justify-items:center;padding:13px 10px;border:1px solid var(--d6-line);border-radius:16px;background:var(--d6-card);text-align:center}}.reward-shop-item .reward-icon{{font-size:1.7rem}}.reward-shop-item strong{{font-size:.92rem}}.reward-shop-item small{{color:var(--d6-muted);font-size:.72rem}}.reward-shop-item button[disabled]{{opacity:.45}}.reward-badge-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:9px}}.reward-badge{{display:grid;gap:4px;justify-items:center;padding:11px 8px;border:1px dashed var(--d6-line);border-radius:14px;background:var(--d6-canvas);text-align:center;filter:grayscale(1);opacity:.62}}.reward-badge.is-earned{{filter:none;opacity:1;border-style:solid;border-color:var(--d6-accent);background:var(--d6-card)}}.reward-badge span{{font-size:1.5rem}}.reward-badge strong{{font-size:.8rem}}.reward-badge small{{color:var(--d6-muted);font-size:.68rem}}.reward-calendar-grid{{margin:4px 0}}.reward-history{{display:grid;gap:7px}}.reward-history-row{{margin:0;display:flex;justify-content:space-between;gap:10px;padding:9px 12px;border-radius:12px;background:var(--d6-card);font-size:.86rem}}.reward-history-row small{{color:var(--d6-muted)}}.d6-star-layer{{position:fixed;inset:0;pointer-events:none;z-index:60;overflow:hidden}}.d6-star-layer span{{position:absolute;bottom:-40px;font-size:1.8rem;animation:d6-star-float 1.5s ease-in forwards}}@keyframes d6-star-float{{0%{{transform:translateY(0) scale(.6);opacity:0}}15%{{opacity:1}}100%{{transform:translateY(-105vh) scale(1.15) rotate(24deg);opacity:0}}}}.d6-shake{{animation:d6-shake .45s ease}}@keyframes d6-shake{{0%,100%{{transform:translateX(0)}}20%{{transform:translateX(-7px)}}40%{{transform:translateX(6px)}}60%{{transform:translateX(-4px)}}80%{{transform:translateX(3px)}}}}.ref-card{{gap:14px}}.ref-group{{display:grid;gap:8px}}.ref-group h5{{margin:0;font-size:.86rem;font-weight:900;color:var(--d6-primary-strong)}}.ref-chips{{display:flex;flex-wrap:wrap;gap:7px}}.ref-chip{{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-width:46px;min-height:48px;padding:6px 8px;border:2px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);color:var(--d6-ink);cursor:pointer}}.ref-chip strong{{font-size:.98rem;font-weight:900}}.ref-chip small{{font-size:.64rem;color:var(--d6-muted);font-weight:750}}.ref-chip:active{{background:color-mix(in srgb,var(--d6-primary) 16%,var(--d6-card));transform:scale(.96)}}.ref-poems{{display:grid;gap:10px}}.ref-poem{{border:1px solid var(--d6-line);border-radius:14px;background:var(--d6-canvas);padding:9px 10px}}.ref-poem summary{{display:grid;gap:2px;cursor:pointer;font-size:1rem}}.ref-poem summary strong{{font-weight:900}}.ref-poem summary span{{font-size:.78rem;color:var(--d6-muted);font-weight:800}}.ref-poem-lines{{margin:8px 0 0;font-size:.95rem;line-height:1.8;font-weight:800}}.ref-poem-note{{margin:8px 0 0;font-size:.86rem;color:var(--d6-muted)}}.ref-poem .starter-actions{{margin-top:10px}}.own-record-heading{{padding-top:8px;border-top:1px dashed var(--d6-line)}}.reliability-grid{{display:grid;gap:10px}}.reliability-grid article{{padding:14px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-card)}}
.workspace{{display:grid;gap:17px}}.detail-view{{display:grid;gap:14px;align-content:start}}.detail-card{{display:grid;gap:10px;padding:clamp(18px,4vw,32px);border:1px solid var(--d6-line);border-radius:22px;background:var(--d6-card)}}.detail-card [data-detail-status]{{font-weight:850;color:var(--d6-primary-strong)}}.back-dashboard{{justify-self:start;font-weight:900;color:var(--d6-primary-strong)}}.module-heading{{display:grid;grid-template-columns:50px 1fr;gap:13px}}.surface-fields{{display:grid;gap:12px}}.surface-field,.surface-filter{{display:grid;gap:6px;font-weight:800}}input,textarea,select{{width:100%;padding:11px 13px;border:1px solid var(--d6-line);border-radius:13px;background:color-mix(in srgb,var(--d6-card) 90%,var(--d6-canvas));color:var(--d6-ink)}}textarea{{min-height:90px;resize:vertical}}.form-actions,.tool-actions,.record-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}.feedback{{min-height:1.5em;font-weight:800}}.success{{color:var(--d6-success)}}.error{{color:var(--d6-error)}}.record-list{{display:grid;gap:9px}}.record{{display:grid;gap:9px;padding:13px;border:1px solid var(--d6-line);border-radius:15px;background:var(--d6-canvas)}}.record.is-complete strong{{text-decoration:line-through}}.record.is-archived{{opacity:.62}}.data-tools{{display:grid;gap:12px;background:var(--d6-card)}}.atomic-tool{{display:grid;gap:10px;padding:16px;border:1px solid var(--d6-line);border-radius:18px;background:var(--d6-card)}}.atomic-tool h3{{margin:0}}.atomic-tool label{{display:grid;gap:6px;font-weight:800}}.atomic-output{{padding:11px;border-radius:12px;background:var(--d6-canvas);white-space:pre-wrap;overflow-wrap:anywhere}}.atomic-output article{{display:grid;gap:3px;padding:8px 0;border-bottom:1px solid var(--d6-line)}}.atomic-output article:last-child{{border-bottom:0}}.atomic-output small,.atomic-fact small{{display:block;color:var(--d6-muted)}}.atomic-fact-list{{display:grid;gap:8px}}.atomic-fact{{display:grid!important;grid-template-columns:auto minmax(0,1fr);align-items:start;gap:9px!important;padding:9px;border:1px solid var(--d6-line);border-radius:12px;background:var(--d6-canvas)}}.atomic-fact input{{width:44px;height:44px;margin:0}}.legacy-import{{padding:12px;border-radius:12px;background:var(--d6-category-2)}}.first-run{{display:grid;gap:10px;align-content:start;padding:14px 16px;border:1px solid var(--d6-line);border-left:6px solid var(--d6-primary);border-radius:20px;background:var(--d6-card)}}.first-run .form-actions button{{flex:none;min-height:40px;width:auto}}.first-run[hidden]{{display:none!important}}.first-run p{{margin:4px 0 0}}.first-run ol{{margin:0;padding-left:1.2em;display:grid;gap:6px}}.first-run-settings ol{{margin:8px 0 12px;padding-left:1.2em;display:grid;gap:6px}}.nav-list{{display:grid;gap:6px}}.nav-item{{display:flex;align-items:center;gap:8px;padding:6px;border-radius:13px;font-weight:800}}.nav-item:nth-child(1){{--nav-icon-bg:#fff0b8;--nav-icon-ink:#de6a00}}.nav-item:nth-child(2){{--nav-icon-bg:#ffe1ec;--nav-icon-ink:#dc3d68}}.nav-item:nth-child(3){{--nav-icon-bg:#dff1ff;--nav-icon-ink:#2677d4}}.nav-item:nth-child(4){{--nav-icon-bg:#ebe3ff;--nav-icon-ink:#6a50ce}}.nav-item:nth-child(5){{--nav-icon-bg:#dcf5e6;--nav-icon-ink:#13805b}}.nav-icon{{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:var(--nav-icon-bg);box-shadow:0 4px 10px color-mix(in srgb,var(--nav-icon-ink) 18%,transparent);font-family:'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif;font-size:1.2rem;line-height:1}}.nav-item.active{{background:var(--d6-primary);color:var(--d6-primary-ink)}}.nav-item.active .nav-icon{{background:#fff;box-shadow:0 5px 13px rgba(45,32,48,.16)}}.bottom-nav{{position:fixed;z-index:10;left:6px;right:auto;top:60px;bottom:8px;width:84px;display:grid;grid-template-columns:1fr;grid-auto-rows:minmax(56px,auto);align-content:start;overflow-y:auto;padding:6px;border:1px solid var(--d6-line);border-radius:20px;background:color-mix(in srgb,var(--d6-card) 95%,transparent);backdrop-filter:blur(14px)}}.bottom-nav .nav-item{{display:grid;grid-template-columns:1fr;justify-items:center;align-content:center;gap:3px;width:70px;min-height:56px;padding:6px 4px;font-size:.68rem;line-height:1.15;text-align:center}}.bottom-nav .nav-label{{display:block;overflow-wrap:anywhere}}.bottom-nav .nav-icon{{width:32px;height:32px;font-size:1.1rem}}@media(max-width:430px){{.app{{padding-left:90px}}.bottom-nav{{width:78px}}.bottom-nav .nav-item{{width:64px;font-size:.62rem;gap:2px;min-height:54px}}.bottom-nav .nav-icon{{width:28px;height:28px;font-size:1rem}}}}.hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}}
.atomic-tool[hidden]{{display:none}}.data-tools summary{{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:850}}
@media(max-width:520px){{.child-greeting{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start}}.child-greeting>strong{{grid-column:2;grid-row:1}}.child-mode-switch{{grid-column:1/-1;grid-row:2;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}}.child-mode-switch button{{width:100%;min-width:0;padding:10px 6px;white-space:nowrap}}}}
@media(min-width:760px){{.learning-task-grid,.pipeline,.delivery-grid,.booking-strip,.household-columns,.generic-card-grid,.reliability-grid,.life-card-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.creator-lower,.lesson-grid,.close-grid,.fitness-layout,.travel-overview{{grid-template-columns:minmax(0,1.7fr) minmax(260px,.8fr)}}.life-dashboard .life-board{{grid-column:1/-1}}.lesson-side{{grid-template-rows:1fr 1fr}}.surface-fields{{grid-template-columns:repeat(2,minmax(0,1fr))}}.record{{grid-template-columns:1fr auto;align-items:center}}}}
@media(min-width:760px) and (max-width:899px){{.app{{padding-left:120px}}.bottom-nav{{width:104px}}.bottom-nav .nav-item{{width:90px;font-size:.72rem}}}}
@media(min-width:900px){{.app{{padding:24px;grid-template-columns:232px minmax(0,1fr)}}.mobile-brand,.bottom-nav{{display:none}}.identity-nav{{display:flex;position:sticky;top:24px;align-self:start;min-height:calc(100vh - 48px);padding:16px;border-radius:24px;background:var(--d6-sidebar);flex-direction:column;gap:18px}}.app-view{{grid-column:2}}.identity-nav{{grid-column:1;grid-row:1}}.child-layout{{grid-template-columns:minmax(0,1.7fr) minmax(260px,.7fr)}}.learning-task-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.pipeline{{grid-template-columns:repeat(3,minmax(0,1fr))}}.pipeline-stage{{display:grid;grid-template-columns:1fr;padding:20px;border-bottom:0;border-right:1px solid var(--d6-line)}}.pipeline-stage>span{{grid-row:auto}}.pipeline-stage small{{grid-column:auto}}.delivery-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.booking-strip{{grid-template-columns:repeat(3,1fr)}}.household-columns{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:520px){{.scene-hero{{min-height:270px;align-items:end}}.exam-practice-dashboard .scene-hero,.exam-hero{{display:none}}.exam-civil-desk .scene-hero,.exam-civil-desk .exam-hero{{display:flex!important;min-height:148px;align-items:end;padding:18px 16px}}.exam-now{{padding:14px 12px}}.exam-desk-doors{{grid-template-columns:1fr}}.exam-topic-strip{{flex-wrap:nowrap;overflow-x:auto}}.exam-topic{{min-height:40px;padding:6px 10px;flex:none}}.exam-question-card h2{{font-size:1.05rem}}.exam-option{{padding:8px 10px}}.exam-plan-block{{grid-template-columns:28px auto minmax(0,1fr);gap:8px}}.exam-plan-actions{{grid-column:1/-1}}.fitness-dashboard .scene-hero,.fitness-hero,.composition-dashboard[data-fitness-home] .scene-hero{{min-height:112px;align-items:center;padding:16px 14px}}.hero-motif{{right:-3%;font-size:100px}}.finance-metrics{{grid-template-columns:1fr}}.panel-heading,.starter-heading,.starter-card-meta{{display:grid}}.rail{{font-size:.78rem}}.starter-actions{{position:static}}.starter-actions a,.starter-actions button{{flex:1}}.starter-draft-material{{padding:8px 10px;font-size:.92rem;line-height:1.4}}.starter-draft-field textarea{{min-height:72px}}}}
.scene-template-freelance_delivery_studio .identity-nav{{color:#fff}}.scene-template-freelance_delivery_studio .identity-nav .nav-item.active{{background:var(--d6-accent);color:#102f29}}.scene-template-freelance_delivery_studio .identity-nav .brand-mark{{background:var(--d6-accent)}}.scene-template-freelance_delivery_studio .milestone-rail{{color:#fff}}.scene-template-freelance_delivery_studio .milestone-rail .eyebrow,.scene-template-freelance_delivery_studio .milestone-rail small{{color:#c9ddd6}}.scene-template-freelance_delivery_studio .milestone-rail .rail span{{border-color:#dce9e3}}
.child-greeting>strong{{white-space:nowrap}}
{POLISH_CSS}
{capability_depth_css}
.app-view{{min-width:0}}
.personal-module-compose>summary{{cursor:pointer;min-height:44px}}
.personal-module-compose[open]>summary{{margin-bottom:16px;padding-bottom:12px;border-bottom:1px dashed var(--d6-line)}}
.scene-hero{{color:var(--d6-hero-ink,var(--d6-ink));background-image:linear-gradient(90deg,var(--d6-hero-overlay-start,color-mix(in srgb,var(--d6-card) 96%,transparent)) 0%,var(--d6-hero-overlay-mid,color-mix(in srgb,var(--d6-card) 80%,transparent)) 43%,var(--d6-hero-overlay-end,transparent) 72%),var(--d6-theme-hero,none);background-size:cover;background-position:center}}
.scene-hero .eyebrow{{color:inherit}}.scene-hero .primary-cta{{background:var(--d6-card);color:var(--d6-ink);border:1px solid var(--d6-line)}}
.life-today-page{{grid-column:1/-1;display:grid;gap:14px;border-top:6px solid var(--d6-primary)}}.life-quick-grid,.life-goal-grid,.cet4-manual-grid{{display:grid;gap:10px}}.life-quick-grid article,.cet4-manual-card,.cet4-timer{{display:grid;gap:8px;padding:14px;border:1px solid var(--d6-line);border-radius:16px;background:var(--d6-card)}}.life-goal-card{{padding:13px;border-radius:15px;background:var(--d6-canvas)}}.life-goal-card summary{{cursor:pointer;font-weight:900}}.life-goal-grid{{margin:12px 0}}.life-goal-grid label,.cet4-goal-row label{{display:grid;gap:4px;font-weight:800}}.life-goal-track{{height:10px;overflow:hidden;border-radius:99px;background:var(--d6-line)}}.life-goal-track i{{display:block;width:0;height:100%;background:var(--d6-accent)}}.life-fact-note{{margin:0;padding:10px 12px;border-radius:13px;background:var(--d6-canvas)}}
.cet4-support{{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;min-width:0;max-width:100%;container-type:inline-size}}.cet4-support .panel-heading{{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;align-items:start}}.cet4-support .panel-heading>*{{min-width:0}}.cet4-support [data-study-state]{{justify-self:start;max-width:100%;overflow-wrap:anywhere}}.cet4-goal-row{{display:grid;grid-template-columns:minmax(0,1fr);gap:9px;align-items:end}}.cet4-goal-row>*{{min-width:0}}.cet4-goal-row input{{width:100%;max-width:100%}}.cet4-goal-row button{{justify-self:start;white-space:nowrap}}.cet4-goal-row [data-cet4-countdown]{{overflow-wrap:anywhere}}.cet4-timer>strong{{font-size:2.1rem;font-variant-numeric:tabular-nums}}.cet4-manual-grid{{grid-template-columns:minmax(0,1fr)}}.cet4-manual-card textarea{{min-height:130px}}.cet4-source-contract{{padding:13px;border-left:5px solid var(--d6-accent);border-radius:13px;background:var(--d6-canvas)}}
.exam-practice-dashboard{{grid-template-columns:minmax(0,1fr)!important;container-type:inline-size}}.exam-home-main{{display:grid;gap:16px;min-width:0;max-width:100%}}.exam-civil-desk .exam-hero{{min-height:0;align-items:end;padding:10px 16px 8px;background-image:none}}.exam-civil-desk .exam-hero h1{{display:block;margin:.15em 0 .2em;font-size:clamp(1.7rem,3.4vw,2.35rem);max-width:8ch;letter-spacing:-.03em}}.exam-desk-now{{background:linear-gradient(180deg,color-mix(in srgb,var(--d6-card) 88%,#f4e6c4),var(--d6-card));border-top:8px solid var(--d6-primary);box-shadow:0 18px 40px color-mix(in srgb,var(--d6-ink) 12%,transparent)}}.exam-desk-lead{{margin:0 0 16px;line-height:1.55;max-width:46ch}}.exam-desk-doors{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;min-width:0;align-items:stretch}}.exam-desk-door{{display:grid;gap:6px;align-content:start;justify-items:start;min-height:0;padding:12px 14px 12px;border-radius:6px 6px 20px 20px;background:var(--d6-card);color:var(--d6-ink);border:1px solid var(--d6-line);text-decoration:none;box-shadow:5px 9px 0 color-mix(in srgb,var(--d6-ink) 9%,transparent);transform:rotate(-.35deg)}}.exam-desk-xingce{{transform:rotate(-1.15deg);background:#fffaf1}}.exam-desk-shenlun{{transform:rotate(.7deg);background:#f6f1e4}}.exam-desk-interview{{transform:rotate(-.25deg);background:#eef3f8}}.exam-desk-door:hover,.exam-desk-door:focus-visible{{transform:rotate(0) translateY(-3px);box-shadow:0 16px 28px color-mix(in srgb,var(--d6-ink) 16%,transparent)}}.exam-desk-kicker{{font-size:.72rem;font-weight:900;letter-spacing:.12em;color:var(--d6-primary-strong)}}.exam-desk-door strong{{font-size:1.55rem;line-height:1.15}}.exam-desk-door small{{color:var(--d6-muted);line-height:1.4}}.exam-desk-door em{{margin-top:auto;padding-top:8px;font-style:normal;font-weight:850;color:var(--d6-primary-strong)}}.exam-desk-sheet{{display:grid;gap:6px;width:100%;min-height:40px;margin-bottom:4px;padding:6px;border-radius:6px;background:#fff;border:1px dashed color-mix(in srgb,var(--d6-ink) 18%,transparent)}}.exam-desk-sheet i{{display:block;height:6px;border-radius:99px;background:color-mix(in srgb,var(--d6-ink) 14%,transparent)}}.exam-desk-xingce .exam-desk-sheet{{grid-template-columns:repeat(4,1fr);align-items:end}}.exam-desk-xingce .exam-desk-sheet i{{grid-column:1/-1}}.exam-desk-xingce .exam-desk-sheet b{{display:grid;place-items:center;height:28px;border:1px solid var(--d6-line);border-radius:6px;font-size:.72rem;font-weight:850}}.exam-desk-lines i:nth-child(2){{width:86%}}.exam-desk-lines i:nth-child(3){{width:94%}}.exam-desk-lines i:nth-child(4){{width:62%}}.exam-desk-timer{{place-items:center;background:radial-gradient(circle at 50% 50%,#fff 0 38%,color-mix(in srgb,var(--d6-accent) 35%,#fff) 39% 46%,#fff 47%)}}.exam-desk-timer b{{font-size:1.15rem;font-variant-numeric:tabular-nums;letter-spacing:.04em}}.exam-options label.exam-option{{display:flex;gap:10px;align-items:flex-start;min-height:44px;padding:8px 10px;cursor:pointer}}.exam-options label.exam-option input{{width:18px;height:18px;min-width:18px;min-height:18px;margin-top:3px}}.exam-listen{{background:transparent;color:var(--d6-ink);border:1px solid var(--d6-line);font-weight:650}}.exam-import{{margin-top:16px}}.exam-timer-row{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}}.exam-home-main>*{{min-width:0;max-width:100%}}.exam-errors-panel{{align-self:start}}.cet4-support{{grid-column:1/-1}}.cet4-control-grid{{display:grid;grid-template-columns:minmax(0,1fr);gap:14px;min-width:0}}.cet4-control-grid>*{{min-width:0}}
@media(max-width:640px){{.exam-desk-doors{{grid-template-columns:1fr;gap:8px}}.exam-desk-sheet{{display:none}}.exam-desk-door{{min-height:0;padding:10px 12px;box-shadow:none;transform:none}}.exam-civil-desk .exam-hero{{padding:8px 12px}}.exam-desk-now{{padding:12px}}.exam-desk-lead{{margin:0 0 8px}}.exam-civil-desk .exam-errors-panel{{display:none}}.exam-save-hint{{font-size:.82rem;color:var(--d6-muted)}}}}.exam-save-hint{{margin:6px 0 0;font-size:.84rem;color:var(--d6-muted)}}
@media(max-width:899px){{.scene-template-exam_civil_service_practice .app{{padding-left:12px;padding-bottom:92px}}.scene-template-exam_civil_service_practice .bottom-nav{{left:8px;right:8px;top:auto;bottom:8px;width:auto;height:72px;grid-template-columns:repeat(7,minmax(56px,1fr));grid-auto-rows:56px;overflow-x:auto;overflow-y:hidden}}.scene-template-exam_civil_service_practice .bottom-nav .nav-item{{width:auto;min-width:0;font-size:.62rem}}}}@container(min-width:720px){{.cet4-control-grid{{grid-template-columns:minmax(260px,1fr) minmax(280px,1fr);align-items:start}}}}@container(min-width:920px){{.exam-home-main{{grid-template-columns:minmax(0,1.4fr) minmax(280px,.85fr)}}}}
@media(min-width:760px){{.life-quick-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.life-goal-grid{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}
@container(min-width:460px){{.cet4-goal-row{{grid-template-columns:minmax(180px,1fr) auto}}.cet4-goal-row [data-cet4-countdown]{{grid-column:1/-1}}}}@container(min-width:540px){{.cet4-manual-grid{{grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}}}}@container(min-width:620px){{.cet4-support .panel-heading{{grid-template-columns:minmax(0,1fr) auto}}.cet4-support [data-study-state]{{justify-self:end}}}}
@media(prefers-reduced-motion:reduce){{*,*::before,*::after{{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}}}
@media(min-width:900px){{
  .identity-nav{{height:calc(100dvh - 48px);max-height:calc(100dvh - 48px);min-height:0;min-width:0;overflow:hidden;gap:14px;color:var(--d6-sidebar-ink)}}
  .identity-nav>.brand{{flex:none;min-width:0;align-items:center}}
  .identity-nav .brand-title{{min-width:0;font-size:.88rem;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .identity-nav>.nav-list{{min-height:0;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:4px}}
  .identity-nav .nav-item{{min-height:46px;flex:none}}
  .identity-nav .nav-label{{display:block;min-width:0;overflow-wrap:anywhere}}
}}
.identity-nav,.identity-nav .nav-item{{color:var(--d6-sidebar-ink)}}.identity-nav .nav-item.active{{background:var(--d6-primary);color:var(--d6-primary-ink)}}.scene-template-freelance_delivery_studio .identity-nav .nav-item.active{{background:var(--d6-accent);color:var(--d6-accent-ink)}}
</style></head><body><main class="app scene-template-{_e(scene_template_id)} renderer-{_e(rendered['renderer_id'])}" data-double6-build-id="{_e(build_id)}" data-double6-product-id="{_e(product['product_id'])}" data-double6-pack-id="{_e(product['recommendation_plan']['pack_id'])}" data-double6-recommendation-sha256="{_e(product['recommendation_plan']['recommendation_sha256'])}" data-double6-surface-registry-version="{product['recommendation_plan']['surface_registry_version']}" data-double6-starter-contract-version="{_e(product['recommendation_plan']['starter_contract_version'])}" data-double6-policy-engine-version="{_e(policy_binding['engine_version'])}" data-double6-policy-registry-sha256="{_e(policy_binding['registry_sha256'])}" data-double6-selected-policy-count="{len(policy_binding['selected_policy_ids'])}" data-double6-composition-contract-version="{_e((composition_contract or {}).get('contract_version', 'none'))}" data-double6-composition-id="{_e(composition_pack.get('composition_id', 'none'))}" data-double6-composition-sha256="{_e((composition_contract or {}).get('composition_sha256', 'none'))}" data-double6-composition-status="{_e((composition_contract or {}).get('activation_status', 'not_registered'))}" data-double6-theme-contract-version="{_e((theme_bundle or {}).get('contract_version','none'))}" data-double6-theme-registry-sha256="{_e((theme_bundle or {}).get('registry_sha256','none'))}" data-double6-reliability-contract-version="local_delivery_reliability_v1" data-double6-reliability-envelope-version="{_e(reliability_envelope.get('contract_version'))}" data-double6-reliability-registry-sha256="{_e(reliability_envelope.get('registry_sha256'))}" data-double6-reliability-envelope-sha256="{_e(reliability_envelope.get('envelope_sha256'))}" data-double6-reliability-envelope-status="{_e(reliability_envelope.get('status'))}" data-double6-reliability-guard-count="{len(reliability_envelope.get('guards', []))}" data-double6-reliability-blocked-count="{int(reliability_envelope.get('status_counts', {}).get('blocked', 0))}" data-feedback-collection="none" data-double6-token-id="{_e(design['current']['token_id'])}" data-double6-template-id="{_e(design['current']['template_id'])}" data-double6-scene-template-id="{_e(scene_template_id)}" data-double6-renderer-id="{_e(rendered['renderer_id'])}" data-double6-visual-contract-version="{VISUAL_CONTRACT_VERSION}" data-double6-visual-kernel-id="vivid_social_workbench_templates_v4" data-double6-scene-id="{_e(experience['scene_id'])}" data-double6-experience-signature="{_e(design['current']['experience_signature'])}"{theme_root_attributes}>
<div class='mobile-brand'><span class='brand-mark' data-double6-emoji-role='brand'>{_e(template['motif'])}</span><span class='brand-title'>{_e(product['title'])}</span></div><aside class='identity-nav' data-double6-role='identity-navigation'><div class='brand'><span class='brand-mark' data-double6-emoji-role='brand'>{_e(template['motif'])}</span><span class='brand-title'>{_e(product['title'])}</span></div><nav class='nav-list'>{nav_html}</nav></aside>
{dashboard_html}{rendered['detail_views_html']}
	<section id='detail-view' class='app-view detail-view' data-view-id='detail-view' data-layout-level='detail' data-detail-view hidden><a class='back-dashboard' data-detail-back href='#dashboard'>← 返回所属模块</a><article class='detail-card'><span class='eyebrow'>当前对象详情</span><h2 data-detail-title>选择一个已选模块中的条目</h2><p data-detail-body>从所属模块打开详情后，这里只显示当前对象和下一步。</p><p data-detail-status>当前状态：尚未开始</p><a class='primary-cta' data-detail-back href='#dashboard'>返回并继续</a></article></section>
	<section id='data-tools' class='app-view data-tools' data-view-id='data-tools' data-layout-level='adult_settings' data-adult-settings hidden>
	<a class='back-dashboard' href='#dashboard'>← 返回首页</a><span class='eyebrow'>成人设置 · 本地保存与恢复</span>
	<div class='reliability-grid' data-reliability-public-layer><article><strong>入口</strong><p>本地单文件；当前候选不是永久链接或原生 App。</p></article><article><strong>数据位置</strong><p>当前设备、当前浏览器；未接入云备份或跨设备同步。</p></article><article><strong>外部数据</strong><p>内置内容为合成或自编；天气、价格、余量、账号和支付均未接入。</p></article><article data-reliability-receipt><strong>本地恢复能力</strong><p>保存、刷新恢复、导出、导入预览、撤销导入、清空和本机恢复点均进入验收。</p></article></div>
	<div class='tool-actions'><button class='secondary' data-double6-hook='export'>导出备份</button><button type='button' class='secondary' data-double6-hook='copy-backup'>复制备份到剪贴板</button>{finance_csv_control}<label><span class='hidden'>导入备份</span><input data-double6-hook='import' type='file' accept='application/json,text/plain,.json,.txt'></label><button class='secondary' data-double6-hook='undo-import' hidden>撤销最近导入</button><button class='secondary' data-double6-hook='clear'>清空本地数据</button></div>
	<p class='feedback' data-double6-hook='data-feedback' aria-live='polite'></p>
	<section class='atomic-tool import-preview' data-atomic-tool='atom.shared.import-backup-preview' data-import-preview hidden><span class='eyebrow'>导入预览</span><h3>还没有改动当前数据</h3><div class='atomic-output' data-import-preview-summary></div><div class='form-actions'><button type='button' data-import-confirm>确认导入</button><button type='button' class='secondary' data-import-cancel>取消</button></div></section>
	<section class='atomic-tool workspace-snapshots' data-workspace-snapshots><span class='eyebrow'>本机恢复点</span><h3>导入或清空前会自动留下恢复点</h3><p>恢复点只存在这台设备，不会写入导出文件。每条会标明当时的工作台版本，以及能不能迁到当前这一版。</p><div data-snapshot-list></div></section>
	<section class='atomic-tool import-log' data-import-log><span class='eyebrow'>导入出处</span><h3>最近带进来的备份</h3><p>记下文件名、时间、改了哪些模块、有没有进隔离区。最多 10 条。</p><div data-import-log-list></div></section>
	<section class='atomic-tool runtime-capabilities' data-runtime-capabilities><span class='eyebrow'>本机能力</span><h3>当前还能做什么</h3><p>保存、导入导出、复制和本地提醒会标明可用、不可用、已关闭或待复查。关掉可选能力不算失败。</p><div data-capability-doctor></div><p class='legacy-import' data-capability-degraded hidden></p></section>
	{selected_csv_control}{ledger_csv_control}<p class='legacy-import' data-double6-hook='legacy-import' hidden></p>
	<section class='atomic-tool first-run-settings' data-first-run-settings><span class='eyebrow'>第一次打开</span><h3>先做一件事，再谈备份</h3><div data-first-run-settings-details><ol><li>今天先看首页最上面的一件事，点进去做完。</li><li>你写下的内容只留在这台设备的这个浏览器里，没有云同步。浏览器存储不是加密保险箱，也不是账号。</li><li>换电脑或重装浏览器前，先导出备份。</li><li>电脑 Chrome：菜单 → 更多工具 → 创建快捷方式 → 勾选「作为窗口打开」。这不是已经上架或已经安装的应用，也不需要联网字体。</li></ol></div><button type='button' class='secondary' data-first-run-again>再看一次</button></section>
	<details data-deployment-guide><summary>想在手机上长期使用或分享给别人？</summary><p>先导出备份，并确认页面不含真实隐私数据；然后在取得明确授权后，交由独立宿主发布流程生成真实链接和内容回执。拿到链接后，可在手机浏览器中使用“添加到主屏幕”。电脑上的 Chrome 也可以把当前文件用应用窗口打开，那不是已经安装或已经上线。当前页面不会自动上线、发送或公开数据，也不注册后台服务。</p></details><div data-double6-hook='claims'>个人数据只保存在当前设备；页面只展示你录入的事实，不生成医学、财务、经营、天气或预订判断。导入最多 8 MB、每个模块最多 2000 条记录。本机空间不够时会改用大容量存储。<details><summary>使用边界</summary><ul>{boundaries}</ul></details></div></section>
<nav class='bottom-nav' data-double6-role="mobile-bottom-navigation">{nav_html}</nav></main><script>{script}</script></body></html>"""


def _reliability_binding(capability_supply: dict[str, Any]) -> dict[str, Any]:
    """Freeze the selected-scope reliability envelope into candidate identity."""
    envelope = capability_supply.get("reliability_envelope")
    if not isinstance(envelope, dict):
        raise ContractError("构建前缺少 selected-scope 可靠性信封")
    counts = envelope.get("status_counts")
    guards = envelope.get("guards")
    if (
        envelope.get("status") != "compiled"
        or not isinstance(counts, dict)
        or int(counts.get("blocked", 0)) != 0
        or not isinstance(guards, list)
        or not guards
    ):
        raise ContractError("selected-scope 可靠性信封未通过编译")
    return {
        "contract_version": envelope.get("contract_version"),
        "registry_sha256": envelope.get("registry_sha256"),
        "envelope_sha256": envelope.get("envelope_sha256"),
        "status": envelope.get("status"),
        "status_counts": {
            key: int(counts.get(key, 0))
            for key in ("satisfied", "contract_only", "not_applicable", "blocked")
        },
        "guard_count": len(guards),
        "guard_ids_by_status": {
            status: sorted(
                str(row["guard_id"])
                for row in guards
                if isinstance(row, dict) and row.get("status") == status and row.get("guard_id")
            )
            for status in ("satisfied", "contract_only", "not_applicable", "blocked")
        },
        "honest_boundary": envelope.get("honest_boundary"),
    }


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
    learning_selection = None
    if design["current"]["renderer_id"] == "child_playground_v2":
        candidate_html, learning_selection = render_child_playground(product, design, build_id, storage_key)
    else:
        candidate_html = _html(product, design, token, template, build_id, storage_key)
    candidate_sha = digest_bytes(candidate_html.encode("utf-8"))
    previous = read_json(run_dir / "build.json") if (run_dir / "build.json").is_file() else {"builds": []}
    builds = list(previous.get("builds", []))
    if previous.get("current"):
        builds.append(previous["current"])
    plan = product["recommendation_plan"]
    capability_supply = plan.get("capability_supply_snapshot", {})
    composition_contract = validate_compiled_composition(plan.get("composition_contract"))
    locked_capabilities = deepcopy(product["capabilities"])
    _apply_gongkao_civil_overlay(
        locked_capabilities,
        (composition_contract or {}).get("pack", {}),
    )
    policy_binding = plan.get("policy_engine_binding", {})
    reliability_binding = _reliability_binding(capability_supply)
    current = {
        "build_id": build_id, "product_sha256": digest_bytes(canonical(product)), "design_sha256": digest_bytes(canonical(design)),
        "token_id": design["current"]["token_id"], "template_id": design["current"]["template_id"],
        "adult_theme_id": design["current"].get("adult_theme_id"),
        "theme_selection_stage": design["current"].get("theme_selection_stage"),
        "template_system_id": design["current"]["template_system_id"], "storage_key": storage_key, "candidate_sha256": candidate_sha,
        "scene_template_id": design["current"].get("scene_template_id"), "renderer_id": design["current"]["renderer_id"],
        "visual_contract_version": design["current"]["visual_contract_version"],
        "scene_id": design["current"]["scene_id"],
        "experience_signature": design["current"]["experience_signature"], "content_pack_id": plan["pack_id"],
        "recommendation_sha256": plan["recommendation_sha256"], "surface_registry_version": plan["surface_registry_version"],
        "starter_contract_version": plan["starter_contract_version"],
        "capability_supply_selection_sha256": capability_supply.get("selection_sha256"),
        "capability_supply_selection_status": capability_supply.get("selection_status"),
        "composition_binding": {
            "contract_version": (composition_contract or {}).get("contract_version"),
            "kernel_version": (composition_contract or {}).get("kernel_version"),
            "registry_sha256": (composition_contract or {}).get("registry_sha256"),
            "composition_sha256": (composition_contract or {}).get("composition_sha256"),
            "composition_id": (composition_contract or {}).get("pack", {}).get("composition_id"),
            "activation_status": (composition_contract or {}).get("activation_status", "not_registered"),
        },
        "policy_engine_version": policy_binding.get("engine_version"),
        "policy_registry_sha256": policy_binding.get("registry_sha256"),
        "selected_policy_ids": list(policy_binding.get("selected_policy_ids", [])),
        "policy_test_vectors_passed": policy_binding.get("test_vectors_passed"),
        "reliability_contract_version": "local_delivery_reliability_v1",
        "reliability_envelope_binding": reliability_binding,
        "starter_item_counts": {
            row["recommendation_module_id"]: len(row["starter"]["starter_items"]) + sum(
                extension.get("module_id") == row["recommendation_module_id"]
                for extension in product.get("module_extensions", [])
            )
            for row in locked_capabilities if row["mode"] == "in_page"
        },
        "module_ids": list(plan["selected_core_module_ids"]), "built_at": now(),
    }
    if learning_selection:
        current["learning_content_selection"] = learning_selection
        current["formal_learning_item_count"] = len(learning_selection["eligible_item_ids"])
    build_value = {"schema_version": schema("build"), "current": current, "builds": builds, "updated_at": now()}
    design["build_history"] = [{
        "build_id": row.get("build_id"), "template_id": row.get("template_id"),
        "adult_theme_id": row.get("adult_theme_id"),
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
        "capability_supply_selection_sha256": capability_supply.get("selection_sha256"),
        "reliability_envelope_binding": reliability_binding,
        "policy_engine_binding": {
            "engine_version": policy_binding.get("engine_version"),
            "registry_sha256": policy_binding.get("registry_sha256"),
            "maturity": policy_binding.get("maturity"),
            "selected_policy_ids": list(policy_binding.get("selected_policy_ids", [])),
            "test_vectors_passed": policy_binding.get("test_vectors_passed"),
            "truth_isolation": policy_binding.get("truth_isolation"),
            "external_operation_boundary": policy_binding.get("external_operation_boundary"),
        },
        "starter_checks": {module_id: {"content": "pending", "interaction": "pending", "persistence": "pending"} for module_id in plan["selected_core_module_ids"]},
        "renderer_id": current["renderer_id"], "visual_contract_version": current["visual_contract_version"],
        "first_screen_slots": {slot: "pending" for slot in sorted(FIRST_SCREEN_SLOTS)},
        "structure_fingerprint": "pending", "viewport_evidence": {"mobile": "pending", "tablet": "pending", "desktop": "pending"},
        "function_entry_checks": {module_id: "pending" for module_id in plan["selected_core_module_ids"]},
        "surface_checks": {module_id: {"crud": "pending", "persistence": "pending", "recovery": "pending"} for module_id in plan["selected_core_module_ids"]},
        "checks": {}, "artifacts": [], "updated_at": now(),
    }
    if learning_selection:
        evidence["learning_content_selection"] = learning_selection
        evidence["formal_content_checks"] = {
            "selection": "pending", "reachability": "pending", "adaptive": "pending",
            "persistence": "pending", "parent_explanation": "pending",
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
        "adult_theme_id": design["current"].get("adult_theme_id"),
        "renderer_id": design["current"]["renderer_id"], "visual_contract_version": design["current"]["visual_contract_version"],
        "candidate_sha256": candidate_sha,
        "conversation_text": "候选已生成。请先打开并实际查看这个页面；满意时再明确确认当前候选，或直接描述构图、密度、颜色、字体、场景感或交互需要怎样改。未收到你的视觉确认前，不会进入验收或标记交付。",
        "next": "respond",
    }
