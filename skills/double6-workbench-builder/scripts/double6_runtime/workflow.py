"""精简工作流、内容摘要确认与可执行视觉反馈。"""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import (
    ContractError,
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
from .routing import critical_decisions, route_options, route_request, safe_defaults
from .recommendations import recommendation_snapshot, validate_surface


EVENT_INTENTS = {
    "answer", "approve_product", "revise_product", "approve_visual", "reject_visual",
    "renderer_revised", "switch_scene",
}
RESPONSIVE_DEVICE_TARGET = "responsive_both"
RESPONSIVE_DEVICE_LABEL = "手机、平板与电脑自适应（含横竖屏）"
SENSITIVE_DATA_POLICIES = {"synthetic_or_redacted", "real_data_local_only_with_explicit_consent"}
CONTENT_SOURCE_MODES = {"generic_non_claimed", "user_provided_or_official_verified"}


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
    for key in ["token_id", "template_id", "visual_requirements"]:
        if supplied.get(key) not in (None, ""):
            preferences[key] = supplied[key]
    supplied_dimensions = supplied.get("feedback_dimensions")
    if isinstance(supplied_dimensions, list):
        dimensions.update(str(row) for row in supplied_dimensions)
    preferences["feedback_dimensions"] = sorted(dimensions)
    preferences["automatic_rebuild_supported"] = dimensions == {"color"} and bool(preferences.get("template_id"))
    return preferences


def _next(run: dict[str, Any], requirements: dict[str, Any] | None = None) -> str | None:
    state = run["state"]
    if state == "clarifying":
        missing = [row for row in (requirements or {}).get("critical_decisions", []) if row["status"] == "missing"]
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


def _new_requirements(request: str, route: dict[str, Any]) -> dict[str, Any]:
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
        "question_count": 0,
        "question_limit": 3,
        "updated_at": now(),
    }


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
    if route_assessment is None:
        return {
            "status": "route_selection_required",
            "message": "请由宿主 Agent 从 route_options 中选择主场景、可选子场景，并提供用户原话证据后重新调用 start。",
            "route_options": route_options(),
            "selection_contract": {
                "required": ["primary_domain", "evidence_spans"],
                "optional": ["profile_id", "auxiliary_domains", "classifier"],
            },
        }
    run_dir.mkdir(parents=True, exist_ok=True)
    events = _new_events(request)
    run = _base_run(run_dir, request, events["events"][0])
    route = route_request(request, route_assessment)
    requirements = _new_requirements(request, route)
    writes: dict[str, dict[str, Any] | str] = {"events.json": events, "requirements.json": requirements}
    state = "clarifying" if requirements["critical_decisions"] else "intake"
    status = "needs_answer" if state == "clarifying" else "ready_to_propose"
    run = transition(run, state, status, "run_started", {"primary_domain": route["primary_domain"]})
    writes["run.json"] = run
    commit(run_dir, writes)
    return {"status": run["status"], "state": run["state"], "next": _next(run, requirements), "risk_pack_ids": route["risk_pack_ids"]}


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
        raise ContractError("视觉确认或反馈必须绑定当前展示候选的 SHA")
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

    requirements = read_json(run_dir / "requirements.json")
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
            snapshot.pop("recommendation_sha256", None)
            snapshot["recommendation_sha256"] = digest_bytes(canonical(snapshot))
            requirements["recommendation_snapshot"] = snapshot
        requirements["question_count"] = int(requirements.get("question_count", 0)) + 1
        requirements["updated_at"] = now()
        if requirements["question_count"] > requirements["question_limit"]:
            raise ContractError("关键问题不得超过三轮")
        missing = [row for row in decisions if row["status"] == "missing"]
        run = transition(run, "clarifying" if missing else "intake", "needs_answer" if missing else "ready_to_propose", "decision_recorded", {"decision_id": decision_id})
        writes["requirements.json"] = requirements
    elif intent == "approve_product":
        require_state(run, "awaiting_product_confirmation")
        product = read_json(run_dir / "product.json")
        presented_sha = str(recorded.get("presented_content_sha256") or "")
        if presented_sha != str(product.get("presentation", {}).get("content_sha256") or ""):
            raise ContractError("产品确认必须绑定当前最新理解稿")
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
        require_state(run, "awaiting_product_confirmation")
        product = read_json(run_dir / "product.json")
        product.setdefault("revisions", []).append({"event_id": recorded["event_id"], "raw_text": recorded["raw_text"], "recorded_at": now()})
        product["confirmation"] = {"status": "revision_requested", "event_id": recorded["event_id"]}
        product["updated_at"] = now()
        writes["product.json"] = product
        run = transition(run, "intake", "needs_reproposal", "product_revision_requested", {"event_id": recorded["event_id"]})
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
        if run.get("status") != "renderer_revision_required":
            raise ContractError("只有等待 renderer 修订的候选可以恢复构建")
        run = transition(run, "ready_to_build", "renderer_revision_ready", "renderer_revised", {"event_id": recorded["event_id"]})
    elif intent == "switch_scene":
        supplied_switch = recorded.get("normalized_value")
        if isinstance(supplied_switch, dict):
            new_request = str(supplied_switch.get("request") or recorded["raw_text"]).strip()
            route = route_request(new_request, supplied_switch.get("route"))
        else:
            raise ContractError("切换场景必须由宿主 Agent 提供新的 route 选择，不能按关键词猜测")
        requirements = _new_requirements(new_request, route)
        run["active_request"] = new_request
        run["request_binding"] = {
            "request_sha256": digest_bytes(new_request.encode("utf-8")),
            "request_event_id": recorded["event_id"],
        }
        state = "clarifying" if requirements["critical_decisions"] else "intake"
        run = transition(run, state, "needs_answer" if state == "clarifying" else "ready_to_propose", "scene_switched", {"primary_domain": route["primary_domain"]})
        writes["requirements.json"] = requirements
        if (run_dir / "product.json").is_file():
            old_product = read_json(run_dir / "product.json")
            writes["product.json"] = {"schema_version": schema("product"), "status": "superseded", "previous_product_id": old_product.get("product_id"), "updated_at": now()}
    else:
        raise ContractError(f"状态 {run['state']} 不接受事件意图 {intent}")

    writes["run.json"] = run
    commit(run_dir, writes)
    return {"status": run["status"], "state": run["state"], "next": _next(run, requirements)}


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
            "optional_module_ids": [row["module_id"] for row in recommendation["optional_modules"]],
            "user_changes": [],
        }
    if not isinstance(supplied_plan, dict):
        raise ContractError("recommendation_plan 必须是对象")
    for key in ["catalog_id", "pack_id", "recommendation_sha256"]:
        if supplied_plan.get(key) != recommendation.get(key):
            raise ContractError(f"recommendation_plan.{key} 与需求快照不一致")
    selected_module_ids = supplied_plan.get("selected_core_module_ids", [])
    if not isinstance(selected_module_ids, list) or not 4 <= len(selected_module_ids) <= 15 or len(selected_module_ids) != len(set(selected_module_ids)):
        raise ContractError("产品必须从内容包选择 4–15 个不重复的核心模块")
    if not set(selected_module_ids) <= set(known_modules):
        raise ContractError("产品选择了内容包之外的模块")
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
                raise ContractError("每个台内能力必须唯一绑定一个已选内容包模块")
            bound_module_ids.append(module_id)
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
                raise ContractError(f"台内核心能力缺最小 oracle：{capability.get('capability_id')}")
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
        raise ContractError("未显式授权真实敏感数据时，data_policy 必须采用合成或脱敏默认值")
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
        raise ContractError("design_brief 必须绑定真实主能力")
    shortcuts = brief.get("shortcut_capability_ids", [])
    if not isinstance(shortcuts, list) or len(shortcuts) > 3 or not set(shortcuts) <= capability_ids or brief["primary_capability_id"] in shortcuts:
        raise ContractError("捷径最多三个且不能与主能力重复")
    if brief.get("work_mode") not in {"orient", "execute", "review", "manage"}:
        raise ContractError("design_brief.work_mode 无效")
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
    result["recommendation_plan"] = {
        "catalog_id": supplied_plan["catalog_id"],
        "pack_id": supplied_plan["pack_id"],
        "profile_id": recommendation.get("profile_id"),
        "learning_stage": dict(recommendation.get("learning_stage") or {}),
        "recommendation_sha256": supplied_plan["recommendation_sha256"],
        "selected_core_module_ids": list(selected_module_ids),
        "optional_module_ids": list(optional_module_ids),
        "user_changes": list(supplied_plan.get("user_changes", [])),
        "surface_registry_version": recommendation["surface_registry_version"],
        "starter_contract_version": recommendation["starter_contract_version"],
    }
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
    lines.extend(["", "## 数据与交付边界", f"- 设备：{RESPONSIVE_DEVICE_LABEL}", data_line])
    source_policy = policy.get("content_source")
    if isinstance(source_policy, dict):
        if source_policy.get("mode") == "user_provided_or_official_verified":
            lines.append(f"- 学习内容：使用你提供或官方可核验的材料（{source_policy.get('version_or_region')}）；仅在 {source_policy.get('scope')} 内使用。")
        else:
            lines.append("- 学习内容：使用通用内容，不宣称与特定教材、真题或考试大纲对齐。")
    lines.extend(["- 联网、多人协作、账号操作、支付与自动发布不在当前本地版本内；如需发布，在本地交付后进入独立宿主发布流程，并以真实链接和内容校验回执为准。", "", "你可以自然回复同意开始制作，或直接指出需要修改的内容。", ""])
    return "\n".join(lines)


def propose(run_dir: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    run = load_run(run_dir)
    require_state(run, "intake")
    requirements = read_json(run_dir / "requirements.json")
    events = read_json(run_dir / "events.json")
    sources = read_json(run_dir / "sources.json") if (run_dir / "sources.json").is_file() else {"sources": []}
    previous_revisions = []
    if (run_dir / "product.json").is_file():
        previous_revisions = read_json(run_dir / "product.json").get("revisions", [])
    value = dict(supplied)
    value["revisions"] = previous_revisions
    product = _validate_product(value, requirements, events, sources)
    product["presentation"] = {"conversation_text": _product_summary(product), "content_sha256": ""}
    product["presentation"]["content_sha256"] = digest_bytes(product["presentation"]["conversation_text"].encode("utf-8"))
    run = transition(run, "awaiting_product_confirmation", "needs_confirmation", "product_proposed", {"product_id": product["product_id"]})
    commit(run_dir, {"product.json": product, "run.json": run})
    return {"status": run["status"], "state": run["state"], "conversation_text": product["presentation"]["conversation_text"], "next": "respond"}


def status(run_dir: Path, verbose: bool = False) -> dict[str, Any]:
    run = load_run(run_dir)
    requirements = read_json(run_dir / "requirements.json")
    result: dict[str, Any] = {
        "status": "pass", "state": run["state"], "run_status": run["status"],
        "release": run["release"], "next": _next(run, requirements),
    }
    if verbose:
        result["run"] = run
        result["critical_decisions"] = requirements.get("critical_decisions", [])
        result["artifacts"] = sorted(path.name for path in run_dir.iterdir() if path.is_file() and not path.name.startswith("."))
        if (run_dir / "delivery.json").is_file():
            result["delivery"] = read_json(run_dir / "delivery.json")
    return result
