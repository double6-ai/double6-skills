"""场景内容包、确定性子场景选择与通用交互表面合同。"""

from __future__ import annotations

from typing import Any

from .core import ContractError, REFERENCES, canonical, digest_bytes, read_json
from .starter_content import education_stage_overrides, starter_for_module


SURFACE_FIELDS: dict[str, list[dict[str, Any]]] = {
    "action_checklist": [
        {"field_id": "title", "label": "事项", "type": "text", "required": True},
        {"field_id": "due", "label": "日期", "type": "date", "required": False},
        {"field_id": "details", "label": "说明", "type": "textarea", "required": False},
    ],
    "record_ledger": [
        {"field_id": "title", "label": "记录", "type": "text", "required": True},
        {"field_id": "date", "label": "日期", "type": "date", "required": False},
        {"field_id": "notes", "label": "备注", "type": "textarea", "required": False},
    ],
    "stage_board": [
        {"field_id": "title", "label": "对象", "type": "text", "required": True},
        {"field_id": "stage", "label": "阶段", "type": "select", "required": True, "options": ["待处理", "进行中", "待确认", "已完成"]},
        {"field_id": "next_action", "label": "下一步", "type": "text", "required": False},
    ],
    "metric_log": [
        {"field_id": "metric", "label": "指标", "type": "text", "required": True},
        {"field_id": "value", "label": "数值", "type": "number", "required": True},
        {"field_id": "unit", "label": "单位", "type": "text", "required": False},
        {"field_id": "date", "label": "日期", "type": "date", "required": False},
        {"field_id": "notes", "label": "备注", "type": "textarea", "required": False},
    ],
    "review_journal": [
        {"field_id": "date", "label": "日期", "type": "date", "required": False},
        {"field_id": "conclusion", "label": "复盘结论", "type": "textarea", "required": True},
        {"field_id": "next_action", "label": "下一步", "type": "textarea", "required": False},
    ],
    "reward_economy": [
        {"field_id": "title", "label": "奖励名称", "type": "text", "required": True},
        {"field_id": "stars", "label": "所需星星", "type": "number", "required": True},
        {"field_id": "notes", "label": "约定说明", "type": "textarea", "required": False},
    ],
}
SURFACE_OPERATIONS = {
    "action_checklist": ["create", "update", "delete", "complete", "uncomplete", "archive", "unarchive"],
    "record_ledger": ["create", "update", "delete", "filter"],
    "stage_board": ["create", "update", "delete", "move", "archive", "unarchive"],
    "metric_log": ["create", "update", "delete", "filter"],
    "review_journal": ["create", "update", "delete", "filter"],
    "reward_economy": ["create", "update", "delete", "filter"],
}
ALLOWED_FIELD_TYPES = {"text", "textarea", "number", "date", "select", "boolean"}
BADGE_RULE_TYPES = {"stars_earned_total", "questions_correct_total", "generator_total", "streak_days", "redeems_total"}


def _surface(surface_type: str) -> dict[str, Any]:
    if surface_type not in SURFACE_FIELDS:
        raise ContractError(f"未知交互表面：{surface_type}")
    return {
        "registry_version": 1,
        "type": surface_type,
        "fields": [dict(row) for row in SURFACE_FIELDS[surface_type]],
        "operations": list(SURFACE_OPERATIONS[surface_type]),
    }


def content_catalog() -> dict[str, Any]:
    value = read_json(REFERENCES / "domain-content-packs.json")
    risk = read_json(REFERENCES / "risk-packs.json")
    risk_ids = {row.get("domain_id") for row in risk.get("packs", [])}
    packs = value.get("packs", [])
    pack_ids = [row.get("domain_id") for row in packs]
    policy = value.get("selection_policy", {})
    if value.get("schema_version") != 1 or value.get("surface_registry_version") != 1:
        raise ContractError("domain-content-packs schema 或 surface registry 版本无效")
    if len(packs) != 16 or set(pack_ids) != risk_ids or len(pack_ids) != len(set(pack_ids)):
        raise ContractError("domain-content-packs 必须与 16 个 risk pack 一一对应")
    for pack in packs:
        modules = pack.get("modules", [])
        by_id = {row.get("module_id"): row for row in modules}
        core = pack.get("core_module_ids", [])
        optional = pack.get("optional_module_ids", [])
        if not policy.get("core_min", 4) <= len(core) <= policy.get("core_max", 15):
            raise ContractError(f"核心模块数量无效：{pack.get('domain_id')}")
        if len(optional) < policy.get("optional_min", 2):
            raise ContractError(f"可选模块数量不足：{pack.get('domain_id')}")
        if len(by_id) != len(modules) or None in by_id or not set([*core, *optional]) <= set(by_id):
            raise ContractError(f"模块 ID 无效或重复：{pack.get('domain_id')}")
        for module in modules:
            if module.get("surface_type") not in SURFACE_FIELDS or not module.get("evidence_refs"):
                raise ContractError(f"模块缺表面或证据：{module.get('module_id')}")
            if module.get("surface_type") == "reward_economy":
                config = module.get("reward_economy")
                shop = config.get("shop", []) if isinstance(config, dict) else []
                badges = config.get("badges", []) if isinstance(config, dict) else []
                if not isinstance(config, dict) or not 10 <= len(shop) <= 20 or not 15 <= len(badges) <= 30:
                    raise ContractError(f"reward_economy 模块必须提供 10–20 项兑换奖励与 15–30 枚徽章：{module.get('module_id')}")
                if any(
                    not isinstance(item, dict)
                    or not str(item.get("item_id") or "").strip()
                    or not str(item.get("title") or "").strip()
                    or not str(item.get("icon") or "").strip()
                    or not isinstance(item.get("cost"), int) or not 1 <= item["cost"] <= 999
                    for item in shop
                ) or len({str(item.get("item_id")) for item in shop}) != len(shop):
                    raise ContractError(f"reward_economy 兑换奖励登记无效：{module.get('module_id')}")
                if any(
                    not isinstance(badge, dict)
                    or not str(badge.get("badge_id") or "").strip()
                    or not str(badge.get("title") or "").strip()
                    or not str(badge.get("icon") or "").strip()
                    or not str(badge.get("hint") or "").strip()
                    or not isinstance(badge.get("rule"), dict)
                    or badge["rule"].get("type") not in BADGE_RULE_TYPES
                    or not isinstance(badge["rule"].get("threshold"), int) or badge["rule"]["threshold"] < 1
                    for badge in badges
                ) or len({str(badge.get("badge_id")) for badge in badges}) != len(badges):
                    raise ContractError(f"reward_economy 徽章规则登记无效：{module.get('module_id')}")
            starter_for_module(module)
        for profile in pack.get("profiles", []):
            profile_core = profile.get("core_module_ids", [])
            if not profile.get("triggers") or not policy.get("core_min", 4) <= len(profile_core) <= policy.get("core_max", 15) or not set(profile_core) <= set(by_id):
                raise ContractError(f"子场景合同无效：{profile.get('profile_id')}")
        if pack.get("domain_id") == "education-learning":
            defaults = pack.get("learning_defaults")
            recommendations = pack.get("decision_recommendations")
            required_defaults = {"stage", "daily_session", "review_policy", "parent_rhythm", "device_and_data"}
            if not isinstance(defaults, dict) or not required_defaults <= set(defaults):
                raise ContractError("儿童学习内容包缺少可直接采用的学习默认值")
            if not isinstance(recommendations, dict) or not {"learning-priority", "learning-modules"} <= set(recommendations):
                raise ContractError("儿童学习内容包缺少关键问题的推荐值")
            recommended_modules = recommendations["learning-modules"].get("value", [])
            if not isinstance(recommended_modules, list) or not policy.get("core_min", 4) <= len(recommended_modules) <= policy.get("core_max", 15) or not set(recommended_modules) <= set(by_id):
                raise ContractError("儿童学习推荐模块范围无效")
            for module in modules:
                feature = module.get("learning_feature")
                required_feature = {"learning_goal", "content_map", "modes", "completion", "review_trigger", "guardrail"}
                if not isinstance(feature, dict) or not required_feature <= set(feature) or not isinstance(feature.get("modes"), list) or len(feature["modes"]) < 2:
                    raise ContractError(f"儿童学习模块缺少可执行的功能说明卡：{module.get('module_id')}")
            for profile in pack.get("profiles", []):
                stage = profile.get("learning_stage")
                if not isinstance(stage, dict) or not {"stage_id", "label", "dashboard_eyebrow", "content_variant"} <= set(stage):
                    raise ContractError(f"儿童学习子场景缺少学段合同：{profile.get('profile_id')}")
    return value


def _expanded(module: dict[str, Any], *, origin_domain: str, learning_stage_id: str | None = None) -> dict[str, Any]:
    surface = _surface(str(module["surface_type"]))
    if "surface_fields" in module:
        fields = module["surface_fields"]
        if not isinstance(fields, list) or not fields or any(
            not isinstance(field, dict)
            or not str(field.get("field_id") or "").strip()
            or not str(field.get("label") or "").strip()
            or field.get("type") not in ALLOWED_FIELD_TYPES
            for field in fields
        ):
            raise ContractError(f"模块自定义字段无效：{module.get('module_id')}")
        surface["fields"] = [dict(field) for field in fields]
    return {
        **module,
        "origin_domain": origin_domain,
        "surface": surface,
        "starter": starter_for_module(module, learning_stage_id=learning_stage_id),
    }


def recommendation_snapshot(text: str, route: dict[str, Any]) -> dict[str, Any]:
    catalog = content_catalog()
    by_domain = {row["domain_id"]: row for row in catalog["packs"]}
    domain_id = route.get("primary_domain") if route.get("primary_domain") in by_domain else catalog["selection_policy"]["fallback_domain"]
    pack = by_domain[domain_id]
    modules = {row["module_id"]: row for row in pack["modules"]}
    profiles = {str(row.get("profile_id")): row for row in pack.get("profiles", [])}
    selected_profile_id = route.get("profile_id")
    if selected_profile_id:
        profile = profiles.get(str(selected_profile_id))
        if profile is None:
            raise ContractError("宿主选择的 profile 不属于当前内容包")
    elif route.get("selection_source") == "host_agent":
        profile = None
    else:
        profile = next(
            (row for row in pack.get("profiles", []) if any(str(trigger).lower() in text.lower() for trigger in row.get("triggers", []))),
            None,
        )
    learning_stage = None
    if domain_id == "education-learning":
        learning_stage = dict((profile or {}).get("learning_stage") or {
            "stage_id": "generic-primary-transition",
            "label": "通用小学衔接",
            "dashboard_eyebrow": "小学学习计划",
            "content_variant": None,
        })
    learning_stage_id = learning_stage.get("stage_id") if learning_stage else None
    if learning_stage_id and learning_stage_id != "generic-primary-transition" and learning_stage_id not in education_stage_overrides():
        raise ContractError(f"stage_content_missing：{learning_stage_id} 缺少专属五类练习题，不能回退到通用题库")
    default_core = list((profile or {}).get("core_module_ids") or pack["core_module_ids"])
    lowered_text = text.lower()
    explicit = [
        module_id for module_id in pack["optional_module_ids"]
        if (
            modules[module_id]["name"].lower() in lowered_text
            or (module_id == "education-errors" and "错题" in lowered_text)
        )
    ]
    ordered_core = [*explicit, *[module_id for module_id in default_core if module_id not in explicit]][: catalog["selection_policy"]["core_max"]]
    optional_ids = [
        module_id for module_id in [*default_core, *pack["optional_module_ids"]]
        if module_id not in ordered_core
    ]
    auxiliary_modules: list[dict[str, Any]] = []
    for auxiliary_domain in route.get("auxiliary_domains", []):
        auxiliary = by_domain.get(auxiliary_domain)
        if not auxiliary:
            continue
        for module_id in auxiliary.get("optional_module_ids", []):
            auxiliary_modules.append(_expanded(next(row for row in auxiliary["modules"] if row["module_id"] == module_id), origin_domain=auxiliary_domain))
            if len(auxiliary_modules) >= catalog["selection_policy"]["auxiliary_optional_max"]:
                break
        if len(auxiliary_modules) >= catalog["selection_policy"]["auxiliary_optional_max"]:
            break
    core_modules = [_expanded(modules[module_id], origin_domain=domain_id, learning_stage_id=learning_stage_id) for module_id in ordered_core]
    optional_modules = [_expanded(modules[module_id], origin_domain=domain_id, learning_stage_id=learning_stage_id) for module_id in optional_ids]
    optional_modules.extend(row for row in auxiliary_modules if row["module_id"] not in {item["module_id"] for item in optional_modules})
    payload = {
        "schema_version": 1,
        "catalog_id": catalog["catalog_id"],
        "catalog_schema_version": catalog["schema_version"],
        "surface_registry_version": catalog["surface_registry_version"],
        "starter_contract_version": "mobile_scene_capability_v1",
        "domain_id": domain_id,
        "pack_id": pack["pack_id"],
        "pack_label": pack["label"],
        "profile_id": profile.get("profile_id") if profile else None,
        "matched_profile_triggers": [trigger for trigger in (profile or {}).get("triggers", []) if str(trigger).lower() in text.lower()],
        "selection_reason": "用户明确模块优先，其次子场景与主领域默认包",
        "default_work_mode": pack["default_work_mode"],
        "core_modules": core_modules,
        "optional_modules": optional_modules,
        "manual_handoffs": list(pack.get("manual_handoffs", [])),
        "prohibited": list(pack.get("prohibited", [])),
        "source_rules": list(pack.get("source_rules", [])),
        "reliability_evidence_refs": list(catalog["reliability_evidence_refs"]),
    }
    if domain_id == "education-learning":
        payload["learning_stage"] = learning_stage
        payload["learning_defaults"] = dict(pack["learning_defaults"])
        payload["decision_recommendations"] = {
            key: dict(value) for key, value in pack["decision_recommendations"].items()
        }
    payload["recommendation_sha256"] = digest_bytes(canonical(payload))
    return payload


def validate_surface(value: Any, expected: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("registry_version") != 1 or value.get("type") != expected.get("type"):
        raise ContractError("台内能力必须绑定当前表面注册表")
    if value.get("fields") != expected.get("fields") or value.get("operations") != expected.get("operations"):
        raise ContractError("台内能力表面字段或操作与推荐包不一致")
    for field in value["fields"]:
        if field.get("type") not in ALLOWED_FIELD_TYPES:
            raise ContractError(f"不支持的字段类型：{field.get('type')}")
