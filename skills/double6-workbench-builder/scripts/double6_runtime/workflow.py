"""精简工作流、内容摘要确认与可执行视觉反馈。"""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import (
    ContractError,
    REFERENCES,
    canonical,
    commit,
    digest_bytes,
    load_run,
    now,
    product_content_sha256,
    read_json,
    release_id,
    require_state,
    schema,
    transition,
)
from .routing import BOUNDARY_DECISION_IDS, critical_decisions, route_options, route_request, safe_defaults
from .recommendations import clarification_catalog, recommendation_snapshot, validate_surface
from .recommendation_compiler import compile_selection
from .policy_engine import run_policy_test_vectors, validate_policy_registry
from .child_playground import learning_content_selection
from .composition import compile_composition
from .theme_system import compile_theme_contract


EVENT_INTENTS = {
    "answer", "approve_product", "revise_product", "approve_visual", "reject_visual",
    "renderer_revised", "switch_scene",
}
RESPONSIVE_DEVICE_TARGET = "responsive_both"
RESPONSIVE_DEVICE_LABEL = "手机、平板与电脑自适应（含横竖屏）"
SENSITIVE_DATA_POLICIES = {"synthetic_or_redacted", "self_owned_local_only", "real_data_local_only_with_explicit_consent"}
CONTENT_SOURCE_MODES = {"generic_non_claimed", "user_provided_or_official_verified"}
QUESTION_LIMIT_PER_SCENE = 5


def _new_events(request: str) -> dict[str, Any]:
    """由 start 的原始请求创建首个本地事件，不依赖宿主回执。"""
    raw = request.strip()
    value = {
        "event_id": f"request-{digest_bytes(raw.encode('utf-8'))[:16]}",
        "turn_index": 0,
        "raw_text": raw,
        "raw_text_sha256": digest_bytes(raw.encode("utf-8")),
        "intent": "request",
        "recorded_at": now(),
    }
    return {"schema_version": schema("events"), "events": [value], "updated_at": now()}


def _validated_event(
    event: dict[str, Any],
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = str(event.get("raw_text", "")).strip()
    event_id = str(event.get("event_id", "")).strip()
    if not raw:
        raise ContractError("事件必须保存未经改写的用户原文")
    if not event_id or any(row.get("event_id") == event_id for row in previous):
        raise ContractError("event_id 必须非空且唯一")
    if not isinstance(event.get("turn_index"), int):
        raise ContractError("事件必须记录整数 turn_index")
    if previous and event["turn_index"] <= max(int(row.get("turn_index", -1)) for row in previous):
        raise ContractError("用户事件 turn_index 必须递增")
    raw_sha256 = digest_bytes(raw.encode("utf-8"))
    return {
        "event_id": event_id,
        "turn_index": event["turn_index"],
        "raw_text": raw,
        "raw_text_sha256": raw_sha256,
        "intent": event.get("intent"),
        "normalized_value": event.get("normalized_value"),
        "decision_id": event.get("decision_id"),
        "resolution_status": event.get("resolution_status"),
        "presented_content_sha256": event.get("presented_content_sha256"),
        "presented_candidate_sha256": event.get("presented_candidate_sha256"),
        "recorded_at": now(),
    }


def _visual_preferences(raw: str, normalized: Any) -> dict[str, Any]:
    """只把当前运行时能真实执行的视觉意见转成自动重建参数。"""
    supplied = dict(normalized) if isinstance(normalized, dict) else {}
    dimensions = set(supplied.get("feedback_dimensions", []))
    preferences: dict[str, Any] = {"visual_requirements": raw}
    keyword_dimensions = {
        "composition": ["布局", "构图", "卡片墙", "首屏", "左右", "上下"],
        "density": ["太空", "空白", "紧凑", "太挤", "密度"],
        "tone": ["日记", "幼稚", "严肃", "专业", "温柔", "力量感"],
        "color": ["颜色", "配色", "粉色", "珊瑚", "绿色", "薄荷", "黄色", "紫色", "深蓝", "黑红", "杏桃", "太暗", "太亮", "高对比", "饱和"],
        "typography": ["字体", "字号", "字重", "标题"],
        "asset": ["图标", "插画", "图片", "素材", "角色"],
        "scene_specificity": ["不像", "健身感", "训练感", "场景", "模板"],
        "interaction": ["步骤", "主按钮", "动作", "反馈", "进度"],
    }
    for dimension, markers in keyword_dimensions.items():
        if any(marker in raw for marker in markers):
            dimensions.add(dimension)
    if any(marker in raw for marker in ["高对比", "训练感", "执行感", "力量感"]):
        preferences["token_id"] = "high-contrast-execution"
    elif any(marker in raw for marker in ["专业", "克制", "可靠", "台账"]):
        preferences["token_id"] = "professional-trust"
    elif any(marker in raw for marker in ["叙事", "杂志", "编辑感"]):
        preferences["token_id"] = "editorial-story"
    template_markers = [
        (["珊瑚", "浅粉", "小芽"], "coral_sprout"),
        (["薄荷", "果园", "苹果绿", "翡翠绿"], "ledger_jade"),
        (["阳光黄", "黄色", "暖阳"], "home_sunrise"),
        (["莓果", "丝带", "玫红"], "coral_sprout"),
        (["星河", "葡萄", "紫色"], "cosmic_grape"),
        (["暗夜", "黑红", "黑色"], "energy_sprint"),
        (["深蓝", "课堂蓝", "藏蓝"], "lesson_bloom"),
        (["杏桃", "暖杏", "桃色", "橘色"], "studio_sunset"),
    ]
    selected_template = next((template_id for markers, template_id in template_markers if any(marker in raw for marker in markers)), None)
    if selected_template:
        preferences["template_id"] = selected_template
        dimensions.add("color")
    adult_theme_markers = [
        (["暖阳生活小屋", "暖阳小屋"], "life_sunlit_cottage"),
        (["安静城市工作室", "城市工作室"], "life_quiet_studio"),
        (["生活经典版"], "life_classic"),
        (["涂鸦成长伙伴", "涂鸦伙伴"], "study_doodle_sprout"),
        (["纸片学习机器人", "纸片机器人"], "study_paper_robot"),
        (["学习经典版"], "study_classic"),
    ]
    selected_adult_theme = next(
        (theme_id for markers, theme_id in adult_theme_markers if any(marker in raw for marker in markers)),
        None,
    )
    if selected_adult_theme:
        preferences["adult_theme_id"] = selected_adult_theme
        dimensions.add("color")
    for key in ["token_id", "template_id", "adult_theme_id", "visual_requirements"]:
        if supplied.get(key) not in (None, ""):
            preferences[key] = supplied[key]
    supplied_dimensions = supplied.get("feedback_dimensions")
    if isinstance(supplied_dimensions, list):
        dimensions.update(str(row) for row in supplied_dimensions)
    preferences["feedback_dimensions"] = sorted(dimensions)
    preferences["automatic_rebuild_supported"] = dimensions == {"color"} and bool(
        preferences.get("template_id") or preferences.get("adult_theme_id")
    )
    return preferences


def _next(run: dict[str, Any], requirements: dict[str, Any] | None = None) -> str | None:
    state = run["state"]
    if state == "clarifying":
        missing = [row for row in (requirements or {}).get("critical_decisions", []) if row["status"] == "missing"]
        session = (requirements or {}).get("scene_session", requirements or {})
        if int(session.get("question_count", 0)) >= int(session.get("question_limit", QUESTION_LIMIT_PER_SCENE)):
            required = [row for row in missing if row["decision_id"] in BOUNDARY_DECISION_IDS]
            if required:
                return "\n".join(row["question"] for row in required)
            if missing:
                return "普通澄清已达上限；核对已展示且适用的低风险默认值，必要授权不得默认通过。"
        return missing[0]["question"] if missing else "propose"
    return {
        "intake": "propose",
        "awaiting_product_confirmation": "respond",
        "ready_to_build": "build",
        "candidate_built": (
            "evaluate" if run.get("status") == "visual_approved"
            else "respond" if run.get("status") == "renderer_revision_required"
            else "respond"
        ),
        "evaluation_failed": "evaluate" if run.get("status") == "evaluation_blocked" else "build",
        "local_delivered": None,
    }.get(state)


def _base_run(run_dir: Path, request: str, request_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": schema("run"),
        "release": release_id(),
        "run_id": f"run-{uuid.uuid4().hex}",
        "state": "intake",
        "status": "active",
        "original_request": request,
        "active_request": request,
        "request_binding": {
            "request_sha256": digest_bytes(request.encode("utf-8")),
            "request_event_id": request_event["event_id"],
        },
        "candidate_root": str((run_dir / "candidate").resolve()),
        "created_at": now(),
        "updated_at": now(),
        "history": [],
    }


def _scene_session(
    request: str,
    *,
    route_status: str,
    question_count: int = 0,
    session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id or f"scene-{uuid.uuid4().hex}",
        "request_text": request,
        "route_status": route_status,
        "question_count": question_count,
        "question_limit": QUESTION_LIMIT_PER_SCENE,
        "authorization_question_count": 0,
        "question_budget_policy": "preferences_only_v1",
    }


def _new_requirements(
    request: str,
    route: dict[str, Any],
    *,
    session_id: str | None = None,
    question_count: int = 0,
) -> dict[str, Any]:
    decisions = critical_decisions(request, route)
    decision_ids = {row["decision_id"] for row in decisions}
    return {
        "schema_version": schema("requirements"),
        "request_text": request,
        "request_sha256": digest_bytes(request.encode("utf-8")),
        "route": route,
        "recommendation_snapshot": recommendation_snapshot(request, route),
        "critical_decisions": decisions,
        "safe_defaults": [row for row in safe_defaults(request, route) if row["decision_id"] not in decision_ids],
        "scene_session": _scene_session(
            request,
            route_status="selected",
            question_count=question_count,
            session_id=session_id,
        ),
        "question_count": question_count,
        "question_limit": QUESTION_LIMIT_PER_SCENE,
        "updated_at": now(),
    }


def _discovery_requirements(request: str, *, session_id: str | None = None) -> dict[str, Any]:
    catalog = clarification_catalog()
    discovery = dict(catalog["scene_discovery"])
    discovery.update({
        "impact": "high",
        "status": "missing",
        "value": None,
        "risk_tags": ["scene-definition"],
        "evidence_refs": [],
        "recommended_value": None,
        "recommendation_reason": "先确认真实场景，再生成领域推荐；系统不会按关键词静默猜测。",
        "scene_scope": {"primary_domain": None, "profile_id": None},
    })
    return {
        "schema_version": schema("requirements"),
        "request_text": request,
        "request_sha256": digest_bytes(request.encode("utf-8")),
        "route": None,
        "recommendation_snapshot": None,
        "critical_decisions": [discovery],
        "safe_defaults": [],
        "scene_session": _scene_session(request, route_status="needs_discovery", session_id=session_id),
        "question_count": 0,
        "question_limit": QUESTION_LIMIT_PER_SCENE,
        "updated_at": now(),
    }


def _ensure_scene_session(requirements: dict[str, Any]) -> dict[str, Any]:
    """读取旧 run 时补兼容视图，不追溯改写旧问题或旧限制。"""
    if isinstance(requirements.get("scene_session"), dict):
        return requirements
    legacy_limit = int(requirements.get("question_limit", 3))
    requirements["scene_session"] = {
        "session_id": f"legacy-{requirements.get('request_sha256', 'unknown')[:16]}",
        "request_text": str(requirements.get("request_text") or ""),
        "route_status": "selected" if requirements.get("route") else "needs_discovery",
        "question_count": int(requirements.get("question_count", 0)),
        "question_limit": legacy_limit,
    }
    return requirements


def _validated_sources(value: dict[str, Any]) -> dict[str, Any]:
    rows = value.get("sources", [])
    if not isinstance(rows, list):
        raise ContractError("sources 必须是列表")
    ids = [row.get("source_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or None in ids or len(ids) != len(set(ids)):
        raise ContractError("source_id 必须非空且唯一")
    for row in rows:
        if row.get("time_sensitive") is True and not str(row.get("captured_at", "")).strip():
            raise ContractError(f"时效来源缺 captured_at：{row.get('source_id')}")
    return {"schema_version": schema("sources"), "sources": rows, "updated_at": now()}


def start_run(
    run_dir: Path,
    request: str,
    route_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ContractError("run 目录必须不存在或为空")
    run_dir.mkdir(parents=True, exist_ok=True)
    events = _new_events(request)
    run = _base_run(run_dir, request, events["events"][0])
    if route_assessment is None:
        route = None
        requirements = _discovery_requirements(request)
    else:
        route = route_request(request, route_assessment)
        requirements = _new_requirements(request, route)
    writes: dict[str, dict[str, Any] | str] = {"events.json": events, "requirements.json": requirements}
    state = "clarifying" if requirements["critical_decisions"] else "intake"
    status = "needs_answer" if state == "clarifying" else "ready_to_propose"
    run = transition(run, state, status, "run_started", {
        "primary_domain": route["primary_domain"] if route else None,
        "route_status": requirements["scene_session"]["route_status"],
        "scene_session_id": requirements["scene_session"]["session_id"],
    })
    writes["run.json"] = run
    commit(run_dir, writes)
    result = {
        "status": run["status"],
        "state": run["state"],
        "next": _next(run, requirements),
        "scene_session": requirements["scene_session"],
        "risk_pack_ids": route["risk_pack_ids"] if route else [],
    }
    if route is None:
        result.update({
            "route_options": route_options(),
            "selection_contract": {
                "required_after_discovery": ["primary_domain", "evidence_spans"],
                "optional": ["profile_id", "auxiliary_domains", "classifier"],
            },
        })
    return result


def clone_confirmed_run(source_dir: Path, run_dir: Path) -> dict[str, Any]:
    """从完全相同的已确认合同创建新 run，不复制候选、视觉或评估证据。"""
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ContractError("目标 run 目录必须不存在或为空")
    source_run = load_run(source_dir)
    if source_run.get("state") not in {"ready_to_build", "candidate_built", "evaluation_failed", "local_delivered"}:
        raise ContractError("只能克隆已完成产品确认的 run")
    product = read_json(source_dir / "product.json")
    confirmation = product.get("confirmation", {})
    if confirmation.get("status") != "confirmed" or confirmation.get("product_content_sha256") != product_content_sha256(product):
        raise ContractError("源 run 的产品确认不完整或产品内容已漂移")
    if product.get("data_policy", {}).get("sensitive_data") == "real_data_local_only_with_explicit_consent":
        raise ContractError("含真实数据授权的 run 不能静默克隆；请重新走确认流程")
    events = read_json(source_dir / "events.json")
    if confirmation.get("event_id") not in {row.get("event_id") for row in events.get("events", [])}:
        raise ContractError("源 run 缺少产品确认事件")
    requirements = read_json(source_dir / "requirements.json")
    run_dir.mkdir(parents=True, exist_ok=True)
    cloned = dict(source_run)
    cloned.update({
        "run_id": f"run-{uuid.uuid4().hex}",
        "candidate_root": str((run_dir / "candidate").resolve()),
        "created_at": now(),
        "updated_at": now(),
        "state": "ready_to_build",
        "status": "cloned_confirmed",
        "history": [{"at": now(), "event": "confirmed_run_cloned", "detail": {"source_run": str(source_dir.resolve()), "product_content_sha256": confirmation["product_content_sha256"]}}],
    })
    writes: dict[str, dict[str, Any] | str] = {
        "events.json": events,
        "requirements.json": requirements,
        "product.json": product,
        "clone.json": {
            "schema_version": 1,
            "source_run": str(source_dir.resolve()),
            "source_run_id": source_run.get("run_id"),
            "product_content_sha256": confirmation["product_content_sha256"],
            "cloned_at": now(),
            "boundary": "只复用完全相同的产品确认；候选、视觉确认和评估证据不会复制。",
        },
        "run.json": cloned,
    }
    if (source_dir / "sources.json").is_file():
        writes["sources.json"] = read_json(source_dir / "sources.json")
    commit(run_dir, writes)
    return {"status": cloned["status"], "state": cloned["state"], "next": "build", "source_run": str(source_dir)}


def _append_event(events: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    rows = list(events.get("events", []))
    value = _validated_event(event, rows)
    if value.get("intent") not in EVENT_INTENTS:
        raise ContractError(f"未知事件意图：{value.get('intent')}")
    rows.append(value)
    return {"schema_version": schema("events"), "events": rows, "updated_at": now()}


def _require_current_candidate_binding(run_dir: Path, recorded: dict[str, Any]) -> dict[str, Any]:
    """视觉意见只能指向当前 run 中已展示的候选，杜绝旧文件串到新会话。"""
    lock = read_json(run_dir / "candidate-lock.json")
    if str(recorded.get("presented_candidate_sha256") or "") != str(lock.get("candidate_sha256") or ""):
        raise ContractError("视觉确认或反馈必须绑定当前展示候选的 SHA：事件字段 presented_candidate_sha256 必须等于最近一次 build 返回的 candidate_sha256（也见 candidate-lock.json）")
    run = load_run(run_dir)
    binding = run.get("request_binding", {})
    for key in ["request_sha256", "request_event_id"]:
        if lock.get(key) != binding.get(key):
            raise ContractError("候选与当前请求绑定不一致")
    return lock


def _resolved_decision_value(decision: dict[str, Any], supplied: Any) -> Any:
    """允许宿主把“按推荐”标准化为推荐值，避免推荐只停留在提问文案。"""
    requested_recommendation = isinstance(supplied, str) and supplied in {"recommended", "use_recommendation", "按推荐"}
    if isinstance(supplied, dict):
        requested_recommendation = supplied.get("choice") in {"recommended", "use_recommendation"}
    if not requested_recommendation:
        return supplied
    if "recommended_value" not in decision:
        raise ContractError("当前问题没有可采用的推荐值")
    return deepcopy(decision["recommended_value"])


def _capabilities_for_modules(snapshot: dict[str, Any], module_ids: list[str]) -> list[str]:
    mapping = snapshot.get("capabilities_by_module", {})
    return sorted({
        capability_id
        for module_id in module_ids
        for capability_id in mapping.get(module_id, [])
    })


def _validate_capability_selection(snapshot: dict[str, Any], module_ids: list[str], supplied: Any) -> list[str]:
    if not isinstance(supplied, list) or not supplied or len(supplied) != len(set(supplied)):
        raise ContractError("能力项选择必须是非空且不重复的能力 ID 列表")
    allowed = set(_capabilities_for_modules(snapshot, module_ids))
    if not set(supplied) <= allowed:
        raise ContractError("能力项选择包含未选模块或当前场景之外的能力")
    mapping = snapshot.get("capabilities_by_module", {})
    uncovered = [module_id for module_id in module_ids if not set(mapping.get(module_id, [])) & set(supplied)]
    if uncovered:
        raise ContractError(f"每个已选模块至少保留一项能力：{','.join(uncovered)}")
    return list(supplied)


def _compiled_selected_supply(
    snapshot: dict[str, Any],
    selected_module_ids: list[str],
    selected_capability_ids: list[str],
) -> dict[str, Any]:
    """把产品选择重新编译为 selected-only 供给快照，不携带完整图谱。"""
    supply = snapshot.get("capability_supply")
    if not isinstance(supply, dict):
        raise ContractError("推荐快照缺少全领域 capability supply")
    scene = supply.get("scene_profile")
    if not isinstance(scene, dict) or not scene.get("scene_profile_id"):
        raise ContractError("capability supply 缺少 scene_profile")
    domain_id = str(snapshot.get("domain_id") or "")
    known_modules = {
        row["module_id"]: row
        for row in [*snapshot.get("core_modules", []), *snapshot.get("optional_modules", [])]
        if isinstance(row, dict) and row.get("module_id")
    }
    primary_modules = [
        module_id for module_id in selected_module_ids
        if known_modules.get(module_id, {}).get("origin_domain") == domain_id
    ]
    primary_capabilities = sorted({
        capability_id
        for module_id in primary_modules
        for capability_id in snapshot.get("capabilities_by_module", {}).get(module_id, [])
        if capability_id in selected_capability_ids
    })
    return compile_selection(
        domain_id,
        {"scene_profile_id": scene["scene_profile_id"]},
        primary_modules,
        primary_capabilities,
    )


def _policy_engine_binding(capability_supply: dict[str, Any]) -> dict[str, Any]:
    """验证策略注册表，并只绑定当前 selected-scope 实际引用的策略。"""
    registry = read_json(REFERENCES / "policy-packs.json")
    validation = validate_policy_registry(registry)
    vectors = run_policy_test_vectors(registry)
    if validation.get("ok") is not True or vectors.get("ok") is not True:
        raise ContractError("policy pack 注册表或可执行向量未通过")
    selected_policy_ids = sorted({
        str(policy_id)
        for module in capability_supply.get("module_paths", [])
        if isinstance(module, dict)
        for capability in module.get("capability_paths", [])
        if isinstance(capability, dict)
        for policy_id in capability.get("policy_pack_ids", [])
        if policy_id
    })
    known_policy_ids = set(validation.get("policy_pack_ids", []))
    if not set(selected_policy_ids) <= known_policy_ids:
        raise ContractError("selected-scope 引用了未登记 policy pack")
    return {
        "engine_version": validation["engine_version"],
        "registry_sha256": validation["registry_sha256"],
        "maturity": "executable_ready",
        "selected_scope_only": True,
        "selected_policy_ids": selected_policy_ids,
        "test_vector_count": vectors["test_vector_count"],
        "test_vectors_passed": vectors["passed"],
        "truth_isolation": "policy_state_never_overwrites_mastery_business_truth_or_completion_evidence",
        "external_operation_boundary": "manual_handoff_until_independent_host_receipt",
    }


def respond(run_dir: Path, event: dict[str, Any], supplied_sources: dict[str, Any] | None = None) -> dict[str, Any]:
    run = load_run(run_dir)
    events = read_json(run_dir / "events.json")
    intent = event.get("intent")
    previous_events = list(events.get("events", []))
    if not previous_events:
        raise ContractError("run 缺少原始请求事件")
    updated_events = _append_event(events, event)
    recorded = updated_events["events"][-1]
    writes: dict[str, dict[str, Any] | str] = {"events.json": updated_events}
    if supplied_sources is not None:
        writes["sources.json"] = _validated_sources(supplied_sources)

    requirements = _ensure_scene_session(read_json(run_dir / "requirements.json"))
    if intent == "answer":
        require_state(run, "clarifying")
        decision_id = recorded.get("decision_id")
        decisions = [dict(row) for row in requirements.get("critical_decisions", [])]
        decision = next((row for row in decisions if row["decision_id"] == decision_id and row["status"] == "missing"), None)
        if not decision:
            raise ContractError("回答必须绑定当前未解决的关键决策")
        if recorded.get("normalized_value") in (None, ""):
            raise ContractError("回答必须提供 normalized_value")
        resolution = recorded.get("resolution_status") or "confirmed"
        if resolution not in {"confirmed", "blocked"}:
            raise ContractError("resolution_status 只能是 confirmed/blocked")
        if decision_id == "scene-discovery":
            supplied_discovery = recorded.get("normalized_value")
            if not isinstance(supplied_discovery, dict) or not isinstance(supplied_discovery.get("route"), dict):
                raise ContractError("场景厘清回答必须由宿主提供 request 与语义 route")
            new_request = str(supplied_discovery.get("request") or recorded["raw_text"]).strip()
            route = route_request(new_request, supplied_discovery["route"])
            session = requirements["scene_session"]
            question_count = int(session.get("question_count", 0)) + 1
            if question_count > int(session.get("question_limit", QUESTION_LIMIT_PER_SCENE)):
                raise ContractError("每个场景的关键问题不得超过五轮")
            requirements = _new_requirements(
                new_request,
                route,
                session_id=str(session["session_id"]),
                question_count=question_count,
            )
            requirements["scene_discovery"] = {
                "status": "confirmed",
                "value": {"request": new_request, "route": route},
                "evidence_refs": [recorded["event_id"]],
            }
            run["active_request"] = new_request
            run["request_binding"] = {
                "request_sha256": digest_bytes(new_request.encode("utf-8")),
                "request_event_id": recorded["event_id"],
            }
            missing = [row for row in requirements["critical_decisions"] if row["status"] == "missing"]
            run = transition(
                run,
                "clarifying" if missing else "intake",
                "needs_answer" if missing else "ready_to_propose",
                "scene_discovered",
                {"primary_domain": route["primary_domain"], "scene_session_id": session["session_id"]},
            )
            writes["requirements.json"] = requirements
            writes["run.json"] = run
            commit(run_dir, writes)
            return {
                "status": run["status"],
                "state": run["state"],
                "next": _next(run, requirements),
                "scene_session": requirements["scene_session"],
            }
        decision_value = _resolved_decision_value(decision, recorded["normalized_value"])
        decision.update({"status": resolution, "value": decision_value, "evidence_refs": [recorded["event_id"]]})
        requirements["critical_decisions"] = decisions
        if decision_id == "learning-modules" and resolution == "confirmed":
            selected_module_ids = decision_value
            if not isinstance(selected_module_ids, list) or not 4 <= len(selected_module_ids) <= 15 or len(selected_module_ids) != len(set(selected_module_ids)):
                raise ContractError("学习内容选择必须标准化为 4–15 个不重复的模块 ID")
            snapshot = dict(requirements["recommendation_snapshot"])
            available = {
                row["module_id"]: row
                for row in [*snapshot.get("core_modules", []), *snapshot.get("optional_modules", [])]
                if isinstance(row, dict) and row.get("module_id")
            }
            if not set(selected_module_ids) <= set(available):
                raise ContractError("学习内容选择包含当前内容包外的模块")
            snapshot["core_modules"] = [available[module_id] for module_id in selected_module_ids]
            snapshot["optional_modules"] = [row for module_id, row in available.items() if module_id not in selected_module_ids]
            snapshot["selection_reason"] = "用户在澄清阶段确认的学习内容范围"
            snapshot["recommended_capability_ids"] = _capabilities_for_modules(snapshot, selected_module_ids)
            snapshot["capability_supply"] = _compiled_selected_supply(
                snapshot,
                selected_module_ids,
                list(snapshot["recommended_capability_ids"]),
            )
            capability_decision = next(
                (row for row in decisions if row.get("decision_id") == "learning-capabilities" and row.get("status") == "missing"),
                None,
            )
            if capability_decision:
                capability_decision["recommended_value"] = list(snapshot["recommended_capability_ids"])
            snapshot.pop("recommendation_sha256", None)
            snapshot["recommendation_sha256"] = digest_bytes(canonical(snapshot))
            requirements["recommendation_snapshot"] = snapshot
        if decision_id == "learning-capabilities" and resolution == "confirmed":
            snapshot = dict(requirements["recommendation_snapshot"])
            selected_module_ids = [row["module_id"] for row in snapshot.get("core_modules", [])]
            selected_capability_ids = _validate_capability_selection(snapshot, selected_module_ids, decision_value)
            snapshot["selected_capability_ids"] = selected_capability_ids
            snapshot["capability_supply"] = _compiled_selected_supply(
                snapshot,
                selected_module_ids,
                selected_capability_ids,
            )
            snapshot.pop("recommendation_sha256", None)
            snapshot["recommendation_sha256"] = digest_bytes(canonical(snapshot))
            requirements["recommendation_snapshot"] = snapshot
        session = requirements["scene_session"]
        # 分类来自运行时已知的边界 ID，不接受宿主自报类型绕过普通澄清上限。
        is_authorization = decision_id in BOUNDARY_DECISION_IDS
        counter = "authorization_question_count" if is_authorization else "question_count"
        session[counter] = int(session.get(counter, 0)) + 1
        requirements["question_count"] = session["question_count"]
        requirements["authorization_question_count"] = int(session.get("authorization_question_count", 0))
        requirements["updated_at"] = now()
        if not is_authorization and session["question_count"] > int(session.get("question_limit", requirements.get("question_limit", QUESTION_LIMIT_PER_SCENE))):
            raise ContractError("每个场景的普通需求和偏好澄清不得超过五轮")
        missing = [row for row in decisions if row["status"] == "missing"]
        run = transition(run, "clarifying" if missing else "intake", "needs_answer" if missing else "ready_to_propose", "decision_recorded", {
            "decision_id": decision_id,
            "scene_session_id": session["session_id"],
            "question_count": session["question_count"],
            "authorization_question_count": int(session.get("authorization_question_count", 0)),
        })
        writes["requirements.json"] = requirements
    elif intent == "approve_product":
        require_state(run, "awaiting_product_confirmation")
        product = read_json(run_dir / "product.json")
        presented_sha = str(recorded.get("presented_content_sha256") or "")
        if presented_sha != str(product.get("presentation", {}).get("content_sha256") or ""):
            raise ContractError("产品确认必须绑定当前最新理解稿：事件字段 presented_content_sha256 必须等于当前 run 的 product.json → presentation.content_sha256")
        confirmed_product_sha256 = product_content_sha256(product)
        product["confirmation"] = {
            "status": "confirmed", "event_id": recorded["event_id"], "confirmed_at": now(),
            "product_content_sha256": confirmed_product_sha256,
        }
        writes["product.json"] = product
        run = transition(run, "ready_to_build", "confirmed", "product_confirmed", {
            "event_id": recorded["event_id"], "product_content_sha256": confirmed_product_sha256,
        })
    elif intent == "approve_visual":
        require_state(run, "candidate_built")
        lock = _require_current_candidate_binding(run_dir, recorded)
        design = read_json(run_dir / "design.json")
        design["visual_review"] = {
            "status": "approved", "event_id": recorded["event_id"], "candidate_sha256": lock["candidate_sha256"], "approved_at": now(),
        }
        design["updated_at"] = now()
        writes["design.json"] = design
        run = transition(run, "candidate_built", "visual_approved", "candidate_visual_approved", {"event_id": recorded["event_id"], "build_id": lock["build_id"]})
    elif intent == "revise_product":
        require_state(
            run,
            "awaiting_product_confirmation",
            "ready_to_build",
            "candidate_built",
            "evaluation_failed",
            "local_delivered",
        )
        product = read_json(run_dir / "product.json")
        previous_candidate_sha256 = None
        if (run_dir / "candidate-lock.json").is_file():
            previous_candidate_sha256 = read_json(run_dir / "candidate-lock.json").get("candidate_sha256")
        product.setdefault("revisions", []).append({
            "event_id": recorded["event_id"],
            "raw_text": recorded["raw_text"],
            "recorded_at": now(),
            "previous_state": run["state"],
            "previous_candidate_sha256": previous_candidate_sha256,
        })
        product["confirmation"] = {"status": "revision_requested", "event_id": recorded["event_id"]}
        product["updated_at"] = now()
        writes["product.json"] = product
        if (run_dir / "delivery.json").is_file():
            delivery = read_json(run_dir / "delivery.json")
            delivery.setdefault("local", {})["state"] = "superseded_by_product_revision"
            delivery["local"]["superseded_candidate_sha256"] = previous_candidate_sha256
            delivery["local"]["updated_at"] = now()
            delivery["updated_at"] = now()
            writes["delivery.json"] = delivery
        if (run_dir / "evidence.json").is_file():
            evidence = read_json(run_dir / "evidence.json")
            evidence["status"] = "superseded_by_product_revision"
            evidence["updated_at"] = now()
            writes["evidence.json"] = evidence
        run = transition(run, "intake", "needs_reproposal", "product_revision_requested", {
            "event_id": recorded["event_id"],
            "previous_candidate_sha256": previous_candidate_sha256,
            "storage_continuity": "same_product_id_required",
        })
    elif intent == "reject_visual":
        _require_current_candidate_binding(run_dir, recorded)
        require_state(run, "candidate_built", "evaluation_failed", "local_delivered")
        design = read_json(run_dir / "design.json")
        preferences = _visual_preferences(recorded["raw_text"], recorded.get("normalized_value"))
        design.setdefault("feedback", []).append({
            "event_id": recorded["event_id"], "raw_text": recorded["raw_text"],
            "preferences": preferences, "recorded_at": now(),
        })
        merged = dict(design.get("visual_preferences", {}))
        merged.update({key: value for key, value in preferences.items() if value not in (None, "", [])})
        design["visual_preferences"] = merged
        design["status"] = "revision_requested" if preferences["automatic_rebuild_supported"] else "renderer_revision_required"
        design["updated_at"] = now()
        writes["design.json"] = design
        if (run_dir / "delivery.json").is_file():
            delivery = read_json(run_dir / "delivery.json")
            delivery.setdefault("local", {})["state"] = "superseded_by_visual_feedback"
            delivery["updated_at"] = now()
            writes["delivery.json"] = delivery
        if preferences["automatic_rebuild_supported"]:
            run = transition(
                run, "ready_to_build", "visual_revision_ready", "visual_rejected",
                {"feedback_dimensions": preferences["feedback_dimensions"]},
            )
        else:
            run = transition(
                run, "candidate_built", "renderer_revision_required", "visual_rejected_requires_source_update",
                {"feedback_dimensions": preferences["feedback_dimensions"]},
            )
    elif intent == "renderer_revised":
        require_state(run, "candidate_built")
        previous_status = run.get("status")
        if previous_status not in {"renderer_revision_required", "needs_visual_confirmation"}:
            raise ContractError("只有等待视觉确认或 renderer 修订的候选可以恢复构建")
        run = transition(run, "ready_to_build", "renderer_revision_ready", "renderer_revised", {
            "event_id": recorded["event_id"],
            "previous_status": previous_status,
            "visual_confirmation_required_for_new_candidate": True,
        })
    elif intent == "switch_scene":
        supplied_switch = recorded.get("normalized_value")
        if isinstance(supplied_switch, dict):
            new_request = str(supplied_switch.get("request") or recorded["raw_text"]).strip()
            supplied_route = supplied_switch.get("route")
        else:
            new_request = recorded["raw_text"]
            supplied_route = None
        if supplied_route is None:
            route = None
            requirements = _discovery_requirements(new_request)
        elif isinstance(supplied_route, dict):
            route = route_request(new_request, supplied_route)
            requirements = _new_requirements(new_request, route)
        else:
            raise ContractError("切换场景的 route 必须是对象或省略以进入场景厘清")
        run["active_request"] = new_request
        run["request_binding"] = {
            "request_sha256": digest_bytes(new_request.encode("utf-8")),
            "request_event_id": recorded["event_id"],
        }
        state = "clarifying" if requirements["critical_decisions"] else "intake"
        run = transition(run, state, "needs_answer" if state == "clarifying" else "ready_to_propose", "scene_switched", {
            "primary_domain": route["primary_domain"] if route else None,
            "route_status": requirements["scene_session"]["route_status"],
            "scene_session_id": requirements["scene_session"]["session_id"],
            "question_count": 0,
        })
        writes["requirements.json"] = requirements
        if (run_dir / "product.json").is_file():
            old_product = read_json(run_dir / "product.json")
            writes["product.json"] = {"schema_version": schema("product"), "status": "superseded", "previous_product_id": old_product.get("product_id"), "updated_at": now()}
    else:
        raise ContractError(f"状态 {run['state']} 不接受事件意图 {intent}")

    writes["run.json"] = run
    commit(run_dir, writes)
    return {
        "status": run["status"],
        "state": run["state"],
        "next": _next(run, requirements),
        "scene_session": requirements.get("scene_session"),
    }


def _validate_product(value: dict[str, Any], requirements: dict[str, Any], events: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    required = {"product_id", "title", "facts", "outcomes", "work_objects", "core_flow", "capabilities", "data_policy", "device_target", "design_brief", "boundaries"}
    if not required <= set(value):
        raise ContractError(f"product 缺字段：{sorted(required - set(value))}")
    product_id = str(value["product_id"])
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", product_id):
        raise ContractError("product_id 只能使用小写字母、数字和连字符")
    def required_rows(field: str, fields: set[str], *, nonempty: bool = True) -> list[dict[str, Any]]:
        rows = value.get(field)
        if not isinstance(rows, list) or (nonempty and not rows):
            raise ContractError(f"product.{field} 必须是{'非空' if nonempty else ''}列表")
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ContractError(f"product.{field}[{index}] 必须是对象")
            missing = sorted(key for key in fields if not str(row.get(key, "")).strip())
            if missing:
                raise ContractError(f"product.{field}[{index}] 缺少非空字段：{missing}")
            normalized.append(row)
        return normalized

    # 这些字段会在理解稿或 HTML 中直接读取，必须在任何派生逻辑之前校验。
    required_rows("facts", {"fact_id", "text", "evidence_refs"})
    required_rows("outcomes", {"outcome_id", "text"})
    required_rows("work_objects", {"work_object_id", "name"})
    required_rows("capabilities", {"capability_id", "name", "description", "mode", "work_object_ids"})
    required_rows("boundaries", {"boundary_id", "mode", "reason"}, nonempty=False)
    if not isinstance(value.get("core_flow"), list) or not value["core_flow"] or any(not isinstance(step, str) or not step.strip() for step in value["core_flow"]):
        raise ContractError("product.core_flow 必须是非空字符串列表")
    if not isinstance(value.get("data_policy"), dict):
        raise ContractError("product.data_policy 必须是对象")
    if not isinstance(value.get("design_brief"), dict):
        raise ContractError("product.design_brief 必须是对象")
    unresolved = [row for row in requirements.get("critical_decisions", []) if row["status"] == "missing"]
    if unresolved:
        raise ContractError("仍有未确认的高影响决策，不能提案")
    blocked = {row["decision_id"] for row in requirements.get("critical_decisions", []) if row["status"] == "blocked"}
    boundary_decisions = {row.get("decision_id") for row in value.get("boundaries", []) if row.get("mode") == "unsupported"}
    if not blocked <= boundary_decisions:
        raise ContractError("blocked 决策必须进入 unsupported 边界")
    object_ids = {row.get("work_object_id") for row in value["work_objects"] if isinstance(row, dict)}
    capability_ids = {row.get("capability_id") for row in value["capabilities"] if isinstance(row, dict)}
    if None in object_ids or len(object_ids) != len(value["work_objects"]):
        raise ContractError("work_object_id 必须非空且唯一")
    if None in capability_ids or len(capability_ids) != len(value["capabilities"]):
        raise ContractError("capability_id 必须非空且唯一")
    recommendation = requirements.get("recommendation_snapshot")
    if not isinstance(recommendation, dict) or not recommendation.get("recommendation_sha256"):
        raise ContractError("缺少合法且不可变的场景推荐快照")
    known_modules = {
        row["module_id"]: row
        for row in [*recommendation.get("core_modules", []), *recommendation.get("optional_modules", [])]
        if isinstance(row, dict) and row.get("module_id")
    }
    supplied_plan = value.get("recommendation_plan")
    if supplied_plan is None:
        supplied_plan = {
            "catalog_id": recommendation["catalog_id"],
            "pack_id": recommendation["pack_id"],
            "profile_id": recommendation.get("profile_id"),
            "recommendation_sha256": recommendation["recommendation_sha256"],
            "selected_core_module_ids": [row["module_id"] for row in recommendation["core_modules"]],
            "selected_capability_ids": list(
                recommendation.get("selected_capability_ids")
                or recommendation.get("recommended_capability_ids", [])
            ),
            "optional_module_ids": [row["module_id"] for row in recommendation["optional_modules"]],
            "user_changes": [],
        }
    if not isinstance(supplied_plan, dict):
        raise ContractError("recommendation_plan 必须是对象；可省略，省略时自动采用 requirements.json 中 recommendation_snapshot 的默认模块")
    for key in ["catalog_id", "pack_id", "recommendation_sha256"]:
        if supplied_plan.get(key) != recommendation.get(key):
            raise ContractError(f"recommendation_plan.{key} 与需求快照不一致")
    selected_module_ids = supplied_plan.get("selected_core_module_ids", [])
    if not isinstance(selected_module_ids, list) or not 4 <= len(selected_module_ids) <= 15 or len(selected_module_ids) != len(set(selected_module_ids)):
        raise ContractError("产品必须从内容包选择 4–15 个不重复的核心模块")
    if not set(selected_module_ids) <= set(known_modules):
        raise ContractError("产品选择了内容包之外的模块")
    supplied_capability_ids = supplied_plan.get("selected_capability_ids")
    if supplied_capability_ids is None:
        supplied_capability_ids = recommendation.get("selected_capability_ids") or _capabilities_for_modules(
            recommendation, selected_module_ids,
        )
    selected_capability_ids = _validate_capability_selection(
        recommendation,
        selected_module_ids,
        supplied_capability_ids,
    )
    optional_module_ids = supplied_plan.get("optional_module_ids", [])
    if not isinstance(optional_module_ids, list) or not set(optional_module_ids) <= set(known_modules) or set(optional_module_ids) & set(selected_module_ids):
        raise ContractError("可选模块库无效或与核心模块重复")
    in_page = []
    bound_module_ids: list[str] = []
    normalized_capabilities: list[dict[str, Any]] = []
    for raw_capability in value["capabilities"]:
        capability = dict(raw_capability)
        if capability.get("mode") not in {"in_page", "manual_handoff", "unsupported"}:
            raise ContractError("capability.mode 无效")
        if not set(capability.get("work_object_ids", [])) <= object_ids:
            raise ContractError(f"能力绑定未知工作对象：{capability.get('capability_id')}")
        if capability["mode"] == "in_page":
            in_page.append(capability)
            module_id = capability.get("recommendation_module_id")
            if module_id not in selected_module_ids or module_id in bound_module_ids:
                raise ContractError("每个台内能力必须唯一绑定一个已选内容包模块：in_page 能力需填写 recommendation_module_id，取值来自 recommendation_plan.selected_core_module_ids，且不能重复")
            bound_module_ids.append(module_id)
            if capability.get("surface") is None:
                capability["surface"] = known_modules[module_id]["surface"]
            validate_surface(capability.get("surface"), known_modules[module_id]["surface"])
            expected_starter = known_modules[module_id]["starter"]
            if capability.get("starter") is not None and capability.get("starter") != expected_starter:
                raise ContractError("台内能力 starter 内容与不可变推荐快照不一致")
            capability["starter"] = expected_starter
            expected_rewards = known_modules[module_id].get("reward_economy")
            if capability.get("reward_economy") is not None and capability.get("reward_economy") != expected_rewards:
                raise ContractError("台内能力奖励经济配置与不可变推荐快照不一致")
            capability["reward_economy"] = expected_rewards
            capability["recommendation_module_name"] = known_modules[module_id]["name"]
            if not str(capability.get("oracle", {}).get("input_value", "")).strip():
                raise ContractError(f"台内核心能力缺最小 oracle：{capability.get('capability_id')}；请填写 oracle.input_value（验收时写入的一条示例输入）")
        normalized_capabilities.append(capability)
    if set(bound_module_ids) != set(selected_module_ids):
        raise ContractError("所有已选核心模块都必须有真实台内交互表面")
    if value["device_target"] != RESPONSIVE_DEVICE_TARGET:
        raise ContractError("device_target 固定为 responsive_both；不再让用户选择手机或电脑")
    policy = value["data_policy"]
    if policy.get("storage") != "local_only" or policy.get("sensitive_data") not in SENSITIVE_DATA_POLICIES or policy.get("export_import") is not True:
        raise ContractError("当前版本要求 local_only、受支持的数据边界和导入导出")
    privacy_decision = next((row for row in requirements.get("critical_decisions", []) if row.get("decision_id") == "privacy-boundary"), None)
    privacy_default = next((row for row in requirements.get("safe_defaults", []) if row.get("decision_id") == "privacy-boundary"), None)
    if privacy_decision and privacy_decision.get("status") == "confirmed" and policy.get("sensitive_data") != privacy_decision.get("value"):
        raise ContractError("data_policy 必须与已确认的数据边界一致")
    if not privacy_decision and privacy_default and policy.get("sensitive_data") != privacy_default.get("value"):
        raise ContractError("未显式授权真实敏感数据时，data_policy 必须采用安全默认值（合成/脱敏，或本人自用健康记录的 self_owned_local_only）")
    if policy.get("sensitive_data") == "real_data_local_only_with_explicit_consent":
        required_consent = {
            "explicit_consent": True,
            "authorized_data_controller": "user_or_authorized_controller",
            "shared_device_warning_acknowledged": True,
            "retention": "until_user_clears_or_replaces_local_data",
        }
        if any(policy.get(key) != expected for key, expected in required_consent.items()):
            raise ContractError("真实数据必须明确授权、由有权主体提供、确认非共享设备风险，并允许用户清除")
    content_decision = next((row for row in requirements.get("critical_decisions", []) if row.get("decision_id") == "content-source-boundary"), None)
    content_default = next((row for row in requirements.get("safe_defaults", []) if row.get("decision_id") == "content-source-boundary"), None)
    content_policy = policy.get("content_source")
    if content_decision and content_decision.get("status") == "confirmed":
        if not isinstance(content_policy, dict) or content_policy.get("mode") not in CONTENT_SOURCE_MODES:
            raise ContractError("教育和备考任务必须记录学习内容的来源边界")
        if content_decision.get("value") in CONTENT_SOURCE_MODES and content_policy["mode"] != content_decision["value"]:
            raise ContractError("data_policy 必须与已确认的学习内容来源边界一致")
        if content_policy["mode"] == "user_provided_or_official_verified":
            required_source_fields = {"source_refs", "version_or_region", "scope", "copyright_boundary"}
            if not required_source_fields <= set(content_policy) or not isinstance(content_policy["source_refs"], list) or not content_policy["source_refs"]:
                raise ContractError("指定教材、真题或大纲必须记录来源、版本/地区、适用范围和版权边界")
            source_rows = sources.get("sources", [])
            source_by_id = {row.get("source_id"): row for row in source_rows if isinstance(row, dict)}
            referenced = [source_by_id.get(source_id) for source_id in content_policy["source_refs"]]
            if any(row is None for row in referenced):
                raise ContractError("指定教材、真题或大纲的 source_refs 必须指向已登记来源")
            for row in referenced:
                if not all(str(row.get(field, "")).strip() for field in ["title", "origin", "version_or_region", "scope", "copyright_boundary"]):
                    raise ContractError("已登记学习来源缺少标题、来源、版本/地区、适用范围或版权边界")
    elif content_default:
        if not isinstance(content_policy, dict) or content_policy.get("mode") != content_default.get("value"):
            raise ContractError("未指定教材、真题或考纲时必须使用自编通用内容并明确不声称版本对齐")
    brief = dict(value["design_brief"])
    if brief.get("primary_capability_id") not in capability_ids:
        raise ContractError("design_brief 必须绑定真实主能力：design_brief.primary_capability_id 必须是 capabilities 中的 capability_id")
    shortcuts = brief.get("shortcut_capability_ids", [])
    if not isinstance(shortcuts, list) or len(shortcuts) > 3 or not set(shortcuts) <= capability_ids or brief["primary_capability_id"] in shortcuts:
        raise ContractError("捷径最多三个且不能与主能力重复")
    if brief.get("work_mode") not in {"orient", "execute", "review", "manage"}:
        raise ContractError("design_brief.work_mode 无效：只能是 orient / execute / review / manage")
    primary = next(row for row in value["capabilities"] if row["capability_id"] == brief["primary_capability_id"])
    experience = dict(brief.get("experience") or {})
    supplied_items = experience.get("representative_items")
    if supplied_items is None:
        supplied_items = [
            {
                "item_id": module_id,
                "label": known_modules[module_id]["name"],
                "meta": known_modules[module_id]["reason"],
                "state": "ready",
            }
            for module_id in selected_module_ids
        ]
    if not isinstance(supplied_items, list) or not 4 <= len(supplied_items) <= 15:
        raise ContractError("experience.representative_items 必须包含 4–15 项")
    representative_items = []
    for index, row in enumerate(supplied_items, 1):
        if not isinstance(row, dict) or not str(row.get("label", "")).strip():
            raise ContractError("representative item 必须包含 label")
        representative_items.append({
            "item_id": str(row.get("item_id") or f"item-{index}"),
            "label": str(row["label"]),
            "meta": str(row.get("meta") or "示例内容"),
            "state": str(row.get("state") or "ready"),
        })
    experience.update({
        "scene_id": str(experience.get("scene_id") or requirements.get("route", {}).get("primary_domain") or "personal-execution"),
        "primary_action_label": str(experience.get("primary_action_label") or f"保存{primary['name']}"),
        "success_feedback": str(experience.get("success_feedback") or "已保存到当前设备，可以继续下一步。"),
        "representative_items": representative_items,
        "identity_motif": str(experience.get("identity_motif") or requirements.get("route", {}).get("primary_domain") or "personal-work"),
        "sample_policy": "explicit_first_use_example",
    })
    for deprecated in ["surface_archetype", "density"]:
        experience.pop(deprecated, None)
    brief["experience"] = experience
    event_ids = {row.get("event_id") for row in events.get("events", [])}
    for fact in value["facts"]:
        refs = fact.get("evidence_refs", []) if isinstance(fact, dict) else []
        if not refs or any(not (ref in event_ids or str(ref).startswith("legacy:")) for ref in refs):
            raise ContractError(f"事实缺有效证据：{fact.get('fact_id') if isinstance(fact, dict) else fact}")
    extensions: list[dict[str, Any]] = []
    extension_ids: set[str] = set()
    for raw_extension in value.get("module_extensions", []):
        if not isinstance(raw_extension, dict):
            raise ContractError("module_extensions 每项必须是对象")
        extension_id = str(raw_extension.get("extension_id") or "")
        module_id = str(raw_extension.get("module_id") or "")
        evidence_refs = raw_extension.get("evidence_refs", [])
        weekdays = raw_extension.get("weekdays", [])
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", extension_id) or extension_id in extension_ids:
            raise ContractError("module extension_id 必须是唯一的小写连字符 ID")
        if module_id not in selected_module_ids:
            raise ContractError("新增周期事项必须归入一个已确认模块")
        if not str(raw_extension.get("title") or "").strip() or not str(raw_extension.get("result") or "").strip():
            raise ContractError("新增周期事项必须包含 title 和 result")
        if not isinstance(weekdays, list) or not weekdays or any(day not in range(1, 8) for day in weekdays):
            raise ContractError("新增周期事项必须提供 1–7 的 weekdays")
        if not isinstance(evidence_refs, list) or not evidence_refs or any(ref not in event_ids for ref in evidence_refs):
            raise ContractError("新增周期事项必须绑定真实用户事件证据")
        extension_ids.add(extension_id)
        extensions.append({
            "extension_id": extension_id,
            "module_id": module_id,
            "title": str(raw_extension["title"]).strip(),
            "weekdays": sorted(set(weekdays)),
            "result": str(raw_extension["result"]).strip(),
            "evidence_refs": list(evidence_refs),
            "source_label": "用户明确提出并在产品理解稿中确认",
        })
    result = dict(value)
    result["capabilities"] = normalized_capabilities
    result["module_extensions"] = extensions
    result["design_brief"] = brief
    capability_supply_snapshot = _compiled_selected_supply(
        recommendation,
        list(selected_module_ids),
        selected_capability_ids,
    )
    compiled_scene = capability_supply_snapshot.get("scene_profile", {})
    composition_contract = compile_composition(
        str(compiled_scene.get("scene_profile_id") or ""),
        list(selected_module_ids),
    )
    theme_contract = compile_theme_contract(str(compiled_scene.get("scene_profile_id") or ""))
    result["recommendation_plan"] = {
        "catalog_id": supplied_plan["catalog_id"],
        "pack_id": supplied_plan["pack_id"],
        "profile_id": recommendation.get("profile_id"),
        "learning_stage": dict(recommendation.get("learning_stage") or {}),
        "recommendation_sha256": supplied_plan["recommendation_sha256"],
        "selected_core_module_ids": list(selected_module_ids),
        "selected_capability_ids": selected_capability_ids,
        "selected_capabilities_by_module": {
            module_id: [
                capability_id
                for capability_id in recommendation.get("capabilities_by_module", {}).get(module_id, [])
                if capability_id in selected_capability_ids
            ]
            for module_id in selected_module_ids
        },
        "optional_module_ids": list(optional_module_ids),
        "user_changes": list(supplied_plan.get("user_changes", [])),
        "surface_registry_version": recommendation["surface_registry_version"],
        "starter_contract_version": recommendation["starter_contract_version"],
        "capability_supply_snapshot": capability_supply_snapshot,
        "composition_contract": composition_contract,
        "theme_contract": theme_contract,
    }
    result["recommendation_plan"]["policy_engine_binding"] = _policy_engine_binding(
        result["recommendation_plan"]["capability_supply_snapshot"]
    )
    if recommendation.get("domain_id") == "education-learning":
        supplied_selection = supplied_plan.get("learning_content_selection")
        selected_atoms = supplied_selection.get("selected_atom_ids") if isinstance(supplied_selection, dict) else None
        result["recommendation_plan"]["learning_content_selection"] = learning_content_selection(selected_atoms)
    result["recommendation_options"] = [
        {
            "module_id": module_id,
            "name": known_modules[module_id]["name"],
            "description": known_modules[module_id]["description"],
            "reason": known_modules[module_id]["reason"],
            "surface_type": known_modules[module_id]["surface_type"],
            "starter_summary": known_modules[module_id]["starter"]["summary"],
            "implementation_status": "available_before_confirmation",
        }
        for module_id in optional_module_ids
    ]
    capability_by_id = {
        row["capability_id"]: row for row in recommendation.get("capability_options", [])
    }
    result["selected_capability_options"] = [
        capability_by_id[capability_id]
        for capability_id in selected_capability_ids
        if capability_id in capability_by_id
    ]
    if recommendation.get("domain_id") == "education-learning":
        priority = next(
            (row.get("value") for row in requirements.get("critical_decisions", []) if row.get("decision_id") == "learning-priority"),
            None,
        )
        result["learning_design"] = {
            "defaults": dict(recommendation.get("learning_defaults", {})),
            "confirmed_priority": priority,
            "feature_cards": [
                {
                    "module_id": module_id,
                    "name": known_modules[module_id]["name"],
                    **dict(known_modules[module_id]["learning_feature"]),
                }
                for module_id in selected_module_ids
            ],
        }
    result["recommendation_boundaries"] = {
        "manual_handoffs": list(recommendation.get("manual_handoffs", [])),
        "prohibited": list(recommendation.get("prohibited", [])),
        "source_rules": list(recommendation.get("source_rules", [])),
    }
    result.update({
        "schema_version": schema("product"),
        "requirements_sha256": digest_bytes(canonical(requirements)),
        "confirmation": {"status": "awaiting_user_confirmation", "event_id": None},
        "revisions": list(value.get("revisions", [])),
        "updated_at": now(),
    })
    return result


def _product_summary(product: dict[str, Any]) -> str:
    lines = [f"# {product['title']}", "", "## 要完成的结果"]
    lines.extend(f"- {row.get('text')}" for row in product["outcomes"])
    lines.extend(["", "## 工作对象"])
    lines.extend(f"- {row.get('name')}" for row in product["work_objects"])
    lines.extend(["", "## 核心流程"])
    lines.extend(f"{index}. {step}" for index, step in enumerate(product["core_flow"], 1))
    learning_design = product.get("learning_design")
    if learning_design:
        lines.extend(["", "## 学习安排（默认已采用）"])
        if learning_design.get("confirmed_priority"):
            lines.append(f"- 本次优先目标：{learning_design['confirmed_priority']}")
        lines.extend(f"- {label}：{value}" for label, value in learning_design.get("defaults", {}).items())
        lines.append("- 下列是本轮功能设计约束；候选只可展示已实际支持的练习方式，未支持项必须明确降级，不能写成已可用。")
        for feature in learning_design.get("feature_cards", []):
            lines.append(
                f"- **{feature['name']}**：{feature['learning_goal']} 内容按{feature['content_map']}；"
                f"练习方式为{'、'.join(feature['modes'])}；完成后{feature['completion']}；"
                f"{feature['review_trigger']} 边界：{feature['guardrail']}"
            )
        selection = product.get("recommendation_plan", {}).get("learning_content_selection", {})
        lines.append(
            f"- 正式内容：v{selection.get('source_product_version', '1.7.2')}；"
            f"已选择 {len(selection.get('selected_atom_ids', []))} 个学习 atom，"
            f"装配 {len(selection.get('eligible_item_ids', []))} 条正式内容。"
        )
    plan = product.get("recommendation_plan", {})
    selected_ids = set(plan.get("selected_core_module_ids", []))
    capability_by_module = {row.get("recommendation_module_id"): row for row in product["capabilities"]}
    lines.extend(["", "## 默认为你安排"])
    for module_id in plan.get("selected_core_module_ids", []):
        row = capability_by_module.get(module_id, {})
        starter = row.get("starter", {})
        lines.append(f"- **{row.get('recommendation_module_name') or row.get('name', module_id)}**（台内完成）：{row.get('description', '')}；{starter.get('summary', '开箱内容待核对')}")
        for extension in product.get("module_extensions", []):
            if extension.get("module_id") == module_id:
                weekday_labels = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
                schedule = "、".join(weekday_labels[day] for day in extension.get("weekdays", []))
                lines.append(f"  - 用户周期事项：{extension.get('title')}（每周 {schedule}）")
    selected_capabilities = product.get("selected_capability_options", [])
    if selected_capabilities:
        lines.extend(["", "## 已确定的能力项"])
        lines.extend(
            f"- **{row.get('title')}**：{row.get('primary_action')}；完成后{row.get('result_contract')}"
            for row in selected_capabilities
        )
    lines.extend(["", "## 还可以加入"])
    optional_rows = product.get("recommendation_options", [])
    if optional_rows:
        lines.extend(
            f"- **{row.get('name')}**：{row.get('description', '')}；{row.get('starter_summary', '')}"
            for row in optional_rows if row.get("module_id") not in selected_ids
        )
    else:
        lines.extend(f"- `{module_id}`（可在确认前加入）" for module_id in plan.get("optional_module_ids", []))
    handoffs = [row for row in product["capabilities"] if row.get("mode") == "manual_handoff"]
    if handoffs:
        lines.append("- 人工交接：" + "；".join(f"{row.get('name')}（{row.get('description', '')}）" for row in handoffs))
    elif product.get("recommendation_boundaries", {}).get("manual_handoffs"):
        lines.append("- 只能人工交接：" + "；".join(product["recommendation_boundaries"]["manual_handoffs"]))
    policy = product["data_policy"]
    data_line = "- 个人数据只保存在当前设备；支持导出、清空和导入恢复。"
    if policy.get("sensitive_data") == "real_data_local_only_with_explicit_consent":
        data_line = "- 你已明确授权录入真实数据：仅保存在当前设备；请勿在共享设备使用，可随时导出或清空。"
    lines.extend(["", "## 数据与交付边界", f"- 设备：{RESPONSIVE_DEVICE_LABEL}", data_line, "- 页面会标明本机保存、导入导出、剪贴板和本地提醒是否还能用；关掉某项可选能力不算失败。", "- 第一次打开会看到短说明：先做一件事、数据只在这台设备、换电脑前先导出；电脑 Chrome 可用应用窗口打开，但不表示已经安装或已经上线。"])
    source_policy = policy.get("content_source")
    if isinstance(source_policy, dict):
        if source_policy.get("mode") == "user_provided_or_official_verified":
            lines.append(f"- 学习内容：使用你提供或官方可核验的材料（{source_policy.get('version_or_region')}）；仅在 {source_policy.get('scope')} 内使用。")
        else:
            lines.append("- 学习内容：使用通用内容，不宣称与特定教材、真题或考试大纲对齐。")
    lines.extend(["- 联网、多人协作、账号操作、支付与自动发布不在当前本地版本内；如需发布，在本地交付后进入独立宿主发布流程，并以真实链接和内容校验回执为准。"])
    diff = product.get("revision_diff") if isinstance(product.get("revision_diff"), dict) else None
    if diff and diff.get("has_changes"):
        lines.extend(["", "## 相对上一版的变化"])
        if diff.get("pack_changed"):
            lines.append(f"- 组合包：{diff.get('previous_pack_id') or '无'} → {diff.get('current_pack_id') or '无'}")
        if diff.get("added_module_ids"):
            lines.append("- 新加入模块：" + "、".join(diff["added_module_ids"]))
        if diff.get("removed_module_ids"):
            lines.append("- 拿掉的模块：" + "、".join(diff["removed_module_ids"]) + "。这些模块里已有的本机记录会进未映射区，加回来时还能恢复。")
        for row in diff.get("field_changes") or []:
            lost = "、".join(row.get("lost_fields") or [])
            gained = "、".join(row.get("gained_fields") or [])
            bits = [part for part in (f"少了 {lost}" if lost else "", f"多了 {gained}" if gained else "") if part]
            if bits:
                lines.append(f"- {row.get('module_id')}：" + "；".join(bits))
    lines.extend(["", "你可以自然回复同意开始制作，或直接指出需要修改的内容。", ""])
    return "\n".join(lines)


def _slug_product_id(title: str, fallback: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ascii_slug or ""):
        return ascii_slug[:48]
    return fallback


def draft_product_from_snapshot(
    requirements: dict[str, Any],
    events: dict[str, Any],
    *,
    product_id: str | None = None,
    title: str | None = None,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按当前推荐快照生成可提案的产品合同，供宿主 Agent 不必手写全部字段。"""
    snapshot = requirements.get("recommendation_snapshot")
    if not isinstance(snapshot, dict) or not snapshot.get("recommendation_sha256"):
        raise ContractError("还没有推荐快照，不能按快照提案")
    selected = [row for row in snapshot.get("core_modules", []) if isinstance(row, dict) and row.get("module_id")]
    if not 4 <= len(selected) <= 15:
        raise ContractError("推荐快照的核心模块必须是 4–15 个")
    request_events = [row for row in events.get("events", []) if isinstance(row, dict) and row.get("event_id")]
    if not request_events:
        raise ContractError("run 缺少原始请求事件")
    request_event_id = str(request_events[0]["event_id"])
    request_text = str(requirements.get("request_text") or "").strip()
    scene = (snapshot.get("capability_supply") or {}).get("scene_profile") or {}
    scene_label = str(scene.get("label") or snapshot.get("pack_label") or "本地工作台")
    resolved_title = (title or scene_label).strip()
    if not resolved_title:
        raise ContractError("产品标题不能为空")
    fallback_id = f"wb-{digest_bytes(f'{request_event_id}:{resolved_title}'.encode('utf-8'))[:12]}"
    resolved_id = (product_id or "").strip() or _slug_product_id(resolved_title, fallback_id)
    work_objects = []
    capabilities = []
    for module in selected:
        module_id = str(module["module_id"])
        object_id = f"obj-{module_id}"
        work_objects.append({"work_object_id": object_id, "name": module.get("name") or module_id})
        capabilities.append({
            "capability_id": f"cap-{module_id}",
            "recommendation_module_id": module_id,
            "name": module.get("name") or module_id,
            "description": module.get("description") or module.get("name") or module_id,
            "mode": "in_page",
            "surface": module["surface"],
            "work_object_ids": [object_id],
            "oracle": {"input_value": f"{module.get('name') or module_id}：完成本模块一次真实操作并保存"},
        })
    privacy = next(
        (
            row for row in requirements.get("critical_decisions", [])
            if row.get("decision_id") == "privacy-boundary" and row.get("status") == "confirmed"
        ),
        None,
    )
    privacy_default = next(
        (row for row in requirements.get("safe_defaults", []) if row.get("decision_id") == "privacy-boundary"),
        None,
    )
    sensitive = (privacy or privacy_default or {}).get("value") or "synthetic_or_redacted"
    data_policy: dict[str, Any] = {
        "storage": "local_only",
        "sensitive_data": sensitive,
        "export_import": True,
    }
    if sensitive == "real_data_local_only_with_explicit_consent":
        data_policy.update({
            "explicit_consent": True,
            "authorized_data_controller": "user_or_authorized_controller",
            "shared_device_warning_acknowledged": True,
            "retention": "until_user_clears_or_replaces_local_data",
        })
    content = next(
        (
            row for row in requirements.get("critical_decisions", [])
            if row.get("decision_id") == "content-source-boundary" and row.get("status") == "confirmed"
        ),
        None,
    )
    content_default = next(
        (row for row in requirements.get("safe_defaults", []) if row.get("decision_id") == "content-source-boundary"),
        None,
    )
    if content or content_default:
        data_policy["content_source"] = {"mode": (content or content_default).get("value") or "generic_non_claimed"}
        if data_policy["content_source"]["mode"] == "user_provided_or_official_verified":
            source_rows = [row for row in (sources or {}).get("sources", []) if isinstance(row, dict) and row.get("source_id")]
            if not source_rows:
                raise ContractError("采用用户提供或官方来源时，快照提案需要已登记来源")
            data_policy["content_source"].update({
                "source_refs": [str(row["source_id"]) for row in source_rows],
                "version_or_region": "；".join(dict.fromkeys(str(row.get("version_or_region") or "") for row in source_rows)),
                "scope": "；".join(dict.fromkeys(str(row.get("scope") or "") for row in source_rows)),
                "copyright_boundary": "；".join(dict.fromkeys(str(row.get("copyright_boundary") or "") for row in source_rows)),
            })
    boundaries = [
        {
            "boundary_id": row["decision_id"],
            "mode": "unsupported",
            "reason": str(row.get("question") or "当前场景不支持该决策"),
        }
        for row in requirements.get("critical_decisions", [])
        if row.get("status") == "blocked" and row.get("decision_id")
    ]
    work_mode = snapshot.get("default_work_mode")
    if work_mode not in {"orient", "execute", "review", "manage"}:
        work_mode = "execute"
    return {
        "product_id": resolved_id,
        "title": resolved_title,
        "facts": [{
            "fact_id": "fact-request",
            "text": request_text or scene_label,
            "evidence_refs": [request_event_id],
        }],
        "outcomes": [{
            "outcome_id": "outcome-main",
            "text": scene_label if scene_label != resolved_title else f"用当前设备完成{resolved_title}并保存",
        }],
        "work_objects": work_objects,
        "core_flow": [f"打开{row.get('name') or row['module_id']}" for row in selected[:4]] + ["保存到当前设备"],
        "capabilities": capabilities,
        "data_policy": data_policy,
        "device_target": RESPONSIVE_DEVICE_TARGET,
        "design_brief": {
            "primary_capability_id": capabilities[0]["capability_id"],
            "shortcut_capability_ids": [row["capability_id"] for row in capabilities[1:4]],
            "first_use_state": "empty",
            "work_mode": work_mode,
        },
        "boundaries": boundaries,
    }


def propose_from_snapshot(
    run_dir: Path,
    *,
    product_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """宿主默认提案入口：按当前快照生成产品合同再走同一条 propose。"""
    requirements = _ensure_scene_session(read_json(run_dir / "requirements.json"))
    events = read_json(run_dir / "events.json")
    sources = read_json(run_dir / "sources.json") if (run_dir / "sources.json").is_file() else {"sources": []}
    return propose(
        run_dir,
        draft_product_from_snapshot(requirements, events, product_id=product_id, title=title, sources=sources),
    )


def propose(run_dir: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    run = load_run(run_dir)
    require_state(run, "intake")
    requirements = _ensure_scene_session(read_json(run_dir / "requirements.json"))
    events = read_json(run_dir / "events.json")
    sources = read_json(run_dir / "sources.json") if (run_dir / "sources.json").is_file() else {"sources": []}
    previous_revisions = []
    previous_product_id = None
    if (run_dir / "product.json").is_file():
        previous_product = read_json(run_dir / "product.json")
        previous_revisions = previous_product.get("revisions", [])
        if previous_product.get("confirmation", {}).get("status") == "revision_requested":
            previous_product_id = previous_product.get("product_id")
    value = dict(supplied)
    if previous_product_id and value.get("product_id") != previous_product_id:
        raise ContractError("同一工作台的 Vibe 调整必须保留 product_id，以延续本机数据；需要新产品时请新建或切换任务")
    value["revisions"] = previous_revisions
    product = _validate_product(value, requirements, events, sources)
    revision_diff = None
    writes: dict[str, Any] = {}
    if (run_dir / "product.json").is_file():
        from .atomic_engine import product_revision_diff

        previous_product = read_json(run_dir / "product.json")
        revision_diff = product_revision_diff(previous_product, product)
        product["revision_diff"] = revision_diff
        writes["revision_diff.json"] = {"schema_version": 1, **revision_diff, "updated_at": now()}
    product["presentation"] = {"conversation_text": _product_summary(product), "content_sha256": ""}
    product["presentation"]["content_sha256"] = digest_bytes(product["presentation"]["conversation_text"].encode("utf-8"))
    run = transition(run, "awaiting_product_confirmation", "needs_confirmation", "product_proposed", {"product_id": product["product_id"]})
    writes.update({"product.json": product, "run.json": run})
    commit(run_dir, writes)
    return {"status": run["status"], "state": run["state"], "conversation_text": product["presentation"]["conversation_text"], "next": "respond"}


def status(run_dir: Path, verbose: bool = False) -> dict[str, Any]:
    run = load_run(run_dir)
    requirements = _ensure_scene_session(read_json(run_dir / "requirements.json"))
    result: dict[str, Any] = {
        "status": "pass", "state": run["state"], "run_status": run["status"],
        "release": run["release"], "next": _next(run, requirements),
    }
    if verbose:
        result["run"] = run
        result["scene_session"] = requirements.get("scene_session")
        result["critical_decisions"] = requirements.get("critical_decisions", [])
        result["artifacts"] = sorted(path.name for path in run_dir.iterdir() if path.is_file() and not path.name.startswith("."))
        if (run_dir / "delivery.json").is_file():
            result["delivery"] = read_json(run_dir / "delivery.json")
    return result
