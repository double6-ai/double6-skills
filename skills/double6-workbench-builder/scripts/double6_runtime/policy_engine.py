"""Deterministic reward, constraint, consent, and external-confirmation policy engine.

The engine is intentionally renderer-neutral and side-effect free.  Every command
accepts an explicit timestamp and returns a new JSON-serialisable state plus a
machine receipt.  It never owns or mutates mastery, business truth, or completion
evidence; callers may pass those protected values only so the receipt can prove
their digest is unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any, Callable


ENGINE_VERSION = "double6_policy_engine_v1"
STATE_SCHEMA_VERSION = 1
DEFAULT_COMPLETION_STARS = 1
MAX_STARS_PER_EVENT = 100
ALLOWED_CONSTRAINT_TYPES = {"reminder", "quota", "cooldown", "adult_confirmation"}
ALLOWED_ADULT_ROLES = {"adult", "guardian", "owner"}
FORBIDDEN_EXTERNAL_TYPES = {
    "payment",
    "purchase",
    "merchant_checkout",
    "paid_redemption",
    "transferable_asset",
    "asset_transfer",
}
FORBIDDEN_FULFILLMENT_MODES = {
    "paid",
    "merchant",
    "merchant_checkout",
    "transferable",
    "external_auto",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _state_digest(state: dict[str, Any]) -> str:
    return _digest(state)


def _clean_text(value: Any, *, limit: int = 300) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("required_text_missing")
    return text[:limit]


def _stable_id(value: Any, field: str) -> str:
    identifier = str(value or "").strip()
    if not ID_PATTERN.fullmatch(identifier):
        raise ValueError(f"invalid_{field}")
    return identifier


def _iso_datetime(value: Any, field: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_timezone_required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_date(value: Any, field: str) -> str:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid_{field}") from exc


def _positive_int(value: Any, field: str, *, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid_{field}")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if isinstance(value, float) and (not math.isfinite(value) or value != number):
        raise ValueError(f"invalid_{field}")
    if number <= 0 or number > maximum:
        raise ValueError(f"invalid_{field}")
    return number


def initial_policy_state() -> dict[str, Any]:
    """Return a fresh empty state.  No wall clock is read."""

    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "reward": {
            "ledger_events": [],
            "goals": {},
            "redemption_requests": {},
            "celebrations": [],
        },
        "constraints": {"active": {}, "events": []},
        "authorizations": {
            "sensitive_data_consents": {},
            "external_operations": {},
        },
        "processed_commands": {},
        "audit_events": [],
    }


def validate_policy_state(state: dict[str, Any]) -> None:
    """Fail closed when a caller supplies an unknown or incomplete state."""

    if not isinstance(state, dict):
        raise ValueError("state_not_object")
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported_state_schema")
    if state.get("engine_version") != ENGINE_VERSION:
        raise ValueError("unsupported_engine_version")
    required = {
        "reward",
        "constraints",
        "authorizations",
        "processed_commands",
        "audit_events",
    }
    if not required <= set(state):
        raise ValueError("state_section_missing")
    reward = state["reward"]
    if not isinstance(reward, dict) or not {
        "ledger_events",
        "goals",
        "redemption_requests",
        "celebrations",
    } <= set(reward):
        raise ValueError("reward_state_invalid")


def validate_policy_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate the machine policy registry without mutating it."""

    if not isinstance(registry, dict):
        raise ValueError("policy_registry_not_object")
    if registry.get("schema_version") not in {1, 2}:
        raise ValueError("unsupported_policy_registry_schema")
    packs = registry.get("policy_packs")
    if not isinstance(packs, list) or not packs:
        raise ValueError("policy_pack_list_missing")
    required = {
        "policy_pack_id",
        "label",
        "maturity",
        "reward_rules",
        "constraint_rules",
        "privacy_rules",
        "real_data_rules",
        "external_operation_rules",
        "failure_recovery",
        "acceptance",
        "state_contract",
        "error_contract",
        "audit_contract",
    }
    identifiers: list[str] = []
    for pack in packs:
        if not isinstance(pack, dict) or not required <= set(pack):
            raise ValueError("policy_pack_required_field_missing")
        identifier = _stable_id(pack.get("policy_pack_id"), "policy_pack_id")
        if not identifier.startswith("policy."):
            raise ValueError("invalid_policy_pack_id")
        if pack.get("maturity") not in {
            "catalog_only",
            "contract_ready",
            "executable_ready",
            "release_ready",
        }:
            raise ValueError("invalid_policy_pack_maturity")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate_policy_pack_id")
    if registry.get("policy_pack_count") != len(packs):
        raise ValueError("policy_pack_count_mismatch")
    engine = registry.get("engine_contract")
    if not isinstance(engine, dict) or engine.get("engine_version") != ENGINE_VERSION:
        raise ValueError("policy_engine_contract_missing")
    vectors = registry.get("test_vectors")
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("policy_test_vectors_missing")
    vector_ids = [str(row.get("vector_id") or "") for row in vectors if isinstance(row, dict)]
    if len(vector_ids) != len(vectors) or any(not item for item in vector_ids):
        raise ValueError("policy_test_vector_id_missing")
    if len(vector_ids) != len(set(vector_ids)):
        raise ValueError("duplicate_policy_test_vector_id")
    return {
        "ok": True,
        "status": "valid",
        "engine_version": ENGINE_VERSION,
        "policy_pack_count": len(packs),
        "policy_pack_ids": identifiers,
        "test_vector_count": len(vectors),
        "registry_sha256": _digest(registry),
    }


def reward_projection(state: dict[str, Any], *, as_of_date: str) -> dict[str, int]:
    """Derive balance and streaks from the append-only ledger."""

    validate_policy_state(state)
    as_of = date.fromisoformat(_iso_date(as_of_date, "as_of_date"))
    ledger = state["reward"]["ledger_events"]
    balance = sum(int(row["points_delta"]) for row in ledger)
    earned = sum(max(0, int(row["points_delta"])) for row in ledger)
    spent = -sum(min(0, int(row["points_delta"])) for row in ledger)
    completion_days = sorted(
        {
            date.fromisoformat(row["completed_on"])
            for row in ledger
            if row.get("event_type") == "completion_award"
            and row.get("completed_on")
            and date.fromisoformat(row["completed_on"]) <= as_of
        }
    )
    current = 0
    cursor = as_of
    completed_set = set(completion_days)
    while cursor in completed_set:
        current += 1
        cursor -= timedelta(days=1)
    longest = 0
    running = 0
    previous: date | None = None
    for completed in completion_days:
        running = running + 1 if previous and completed - previous == timedelta(days=1) else 1
        longest = max(longest, running)
        previous = completed
    return {
        "earned_total": earned,
        "spent_total": spent,
        "balance": balance,
        "current_streak_days": current,
        "longest_streak_days": longest,
        "completion_day_count": len(completion_days),
    }


def _adult_confirmation(command: dict[str, Any]) -> dict[str, str]:
    confirmation = command.get("adult_confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("explicit") is not True:
        raise ValueError("adult_confirmation_missing")
    role = str(confirmation.get("actor_role") or "")
    if role not in ALLOWED_ADULT_ROLES:
        raise ValueError("adult_actor_not_authorized")
    return {
        "confirmation_id": _stable_id(confirmation.get("confirmation_id"), "confirmation_id"),
        "actor_role": role,
        "confirmed_at": _iso_datetime(confirmation.get("confirmed_at"), "confirmed_at"),
    }


def _balance(state: dict[str, Any]) -> int:
    return sum(int(row["points_delta"]) for row in state["reward"]["ledger_events"])


def _event_id(kind: str, idempotency_key: str) -> str:
    return f"{kind}.{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:20]}"


def _append_audit(
    state: dict[str, Any], command: dict[str, Any], command_type: str, effect: dict[str, Any]
) -> None:
    state["audit_events"].append(
        {
            "audit_event_id": _event_id("audit", command["idempotency_key"]),
            "command_type": command_type,
            "command_id": command["command_id"],
            "idempotency_key": command["idempotency_key"],
            "effective_at": command["effective_at"],
            "effect_type": effect["effect_type"],
            "affected_policy_ids": effect.get("affected_policy_ids", []),
        }
    )


def _completion_confirmed(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    if command.get("evidence_confirmed") is not True:
        raise ValueError("completion_evidence_not_confirmed")
    evidence_id = _stable_id(command.get("completion_evidence_id"), "completion_evidence_id")
    stars = _positive_int(
        command.get("stars", DEFAULT_COMPLETION_STARS),
        "stars",
        maximum=MAX_STARS_PER_EVENT,
    )
    completed_on = _iso_date(command.get("completed_on"), "completed_on")
    event_id = _event_id("reward", command["idempotency_key"])
    state["reward"]["ledger_events"].append(
        {
            "reward_event_id": event_id,
            "event_type": "completion_award",
            "completion_evidence_id": evidence_id,
            "points_delta": stars,
            "completed_on": completed_on,
            "recorded_at": command["effective_at"],
            "affects_mastery": False,
            "affects_business_truth": False,
            "affects_completion_evidence": False,
        }
    )
    return {
        "effect_type": "completion_reward_posted",
        "reward_event_id": event_id,
        "points_delta": stars,
        "affected_policy_ids": ["policy.reward-truth-isolation"],
    }


def _set_reward_goal(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    goal_id = _stable_id(command.get("goal_id"), "goal_id")
    cost = _positive_int(command.get("cost"), "cost")
    fulfillment_mode = str(command.get("fulfillment_mode") or "family_manual")
    if fulfillment_mode in FORBIDDEN_FULFILLMENT_MODES:
        raise ValueError("forbidden_reward_fulfillment")
    state["reward"]["goals"][goal_id] = {
        "goal_id": goal_id,
        "title": _clean_text(command.get("title"), limit=120),
        "cost": cost,
        "fulfillment_mode": fulfillment_mode,
        "status": "active",
        "set_at": command["effective_at"],
    }
    return {
        "effect_type": "reward_goal_set",
        "goal_id": goal_id,
        "affected_policy_ids": ["policy.reward-truth-isolation"],
    }


def _request_redemption(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    request_id = _stable_id(command.get("request_id"), "request_id")
    goal_id = _stable_id(command.get("goal_id"), "goal_id")
    goal = state["reward"]["goals"].get(goal_id)
    if not goal or goal.get("status") != "active":
        raise ValueError("reward_goal_unavailable")
    if goal["fulfillment_mode"] in FORBIDDEN_FULFILLMENT_MODES:
        raise ValueError("forbidden_reward_fulfillment")
    if request_id in state["reward"]["redemption_requests"]:
        raise ValueError("redemption_request_id_conflict")
    if _balance(state) < int(goal["cost"]):
        raise ValueError("insufficient_reward_balance")
    state["reward"]["redemption_requests"][request_id] = {
        "request_id": request_id,
        "goal_id": goal_id,
        "cost": int(goal["cost"]),
        "status": "adult_confirmation_pending",
        "requested_at": command["effective_at"],
        "fulfillment_status": "not_started",
    }
    return {
        "effect_type": "redemption_requested_without_deduction",
        "request_id": request_id,
        "points_delta": 0,
        "affected_policy_ids": [
            "policy.reward-truth-isolation",
            "policy.external-operation-confirmation",
        ],
    }


def _confirm_redemption(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    request_id = _stable_id(command.get("request_id"), "request_id")
    request = state["reward"]["redemption_requests"].get(request_id)
    if not request:
        raise ValueError("redemption_request_missing")
    if request["status"] != "adult_confirmation_pending":
        raise ValueError("redemption_request_not_pending")
    confirmation = _adult_confirmation(command)
    cost = int(request["cost"])
    if _balance(state) < cost:
        raise ValueError("insufficient_reward_balance")
    event_id = _event_id("redemption", command["idempotency_key"])
    state["reward"]["ledger_events"].append(
        {
            "reward_event_id": event_id,
            "event_type": "redemption_debit",
            "redemption_request_id": request_id,
            "points_delta": -cost,
            "recorded_at": command["effective_at"],
            "adult_confirmation_id": confirmation["confirmation_id"],
            "affects_mastery": False,
            "affects_business_truth": False,
            "affects_completion_evidence": False,
        }
    )
    request.update(
        {
            "status": "confirmed",
            "confirmed_at": confirmation["confirmed_at"],
            "adult_confirmation_id": confirmation["confirmation_id"],
            "fulfillment_status": "manual_pending",
        }
    )
    return {
        "effect_type": "redemption_confirmed_once",
        "request_id": request_id,
        "reward_event_id": event_id,
        "points_delta": -cost,
        "external_fulfillment": "manual_pending_not_executed",
        "affected_policy_ids": [
            "policy.reward-truth-isolation",
            "policy.external-operation-confirmation",
        ],
    }


def _record_stage_celebration(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    celebration_id = _stable_id(command.get("celebration_id"), "celebration_id")
    evidence_id = _stable_id(command.get("stage_evidence_id"), "stage_evidence_id")
    if command.get("stage_evidence_confirmed") is not True:
        raise ValueError("stage_evidence_not_confirmed")
    state["reward"]["celebrations"].append(
        {
            "celebration_id": celebration_id,
            "stage_evidence_id": evidence_id,
            "label": _clean_text(command.get("label"), limit=120),
            "recorded_at": command["effective_at"],
            "points_delta": 0,
            "display_only": True,
            "affects_mastery": False,
            "affects_business_truth": False,
            "affects_completion_evidence": False,
        }
    )
    return {
        "effect_type": "stage_celebration_recorded_without_reward",
        "celebration_id": celebration_id,
        "points_delta": 0,
        "affected_policy_ids": ["policy.reward-truth-isolation"],
    }


def _apply_constraint(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    constraint_id = _stable_id(command.get("constraint_id"), "constraint_id")
    constraint_type = str(command.get("constraint_type") or "")
    if constraint_type not in ALLOWED_CONSTRAINT_TYPES:
        raise ValueError("permanent_or_unknown_constraint_forbidden")
    if command.get("reversible") is not True:
        raise ValueError("constraint_must_be_reversible")
    if command.get("shaming") is True or command.get("permanent_loss") is True:
        raise ValueError("harmful_constraint_forbidden")
    if constraint_id in state["constraints"]["active"]:
        raise ValueError("constraint_id_conflict")
    row: dict[str, Any] = {
        "constraint_id": constraint_id,
        "constraint_type": constraint_type,
        "scope": _clean_text(command.get("scope"), limit=120),
        "reason_code": _stable_id(command.get("reason_code"), "reason_code"),
        "status": "active",
        "applied_at": command["effective_at"],
        "removal_path": "adult_or_owner_confirmation",
        "affects_mastery": False,
        "affects_business_truth": False,
        "affects_completion_evidence": False,
    }
    if constraint_type == "quota":
        row["quota"] = _positive_int(command.get("quota"), "quota")
    if constraint_type == "cooldown":
        cooldown_until = _iso_datetime(command.get("cooldown_until"), "cooldown_until")
        if datetime.fromisoformat(cooldown_until.replace("Z", "+00:00")) <= datetime.fromisoformat(
            command["effective_at"].replace("Z", "+00:00")
        ):
            raise ValueError("cooldown_must_end_after_start")
        row["cooldown_until"] = cooldown_until
    state["constraints"]["active"][constraint_id] = row
    state["constraints"]["events"].append(
        {
            "constraint_event_id": _event_id("constraint", command["idempotency_key"]),
            "constraint_id": constraint_id,
            "event_type": "applied",
            "recorded_at": command["effective_at"],
        }
    )
    return {
        "effect_type": "reversible_constraint_applied",
        "constraint_id": constraint_id,
        "removal_path": row["removal_path"],
        "affected_policy_ids": ["policy.reversible-constraint"],
    }


def _remove_constraint(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    constraint_id = _stable_id(command.get("constraint_id"), "constraint_id")
    row = state["constraints"]["active"].get(constraint_id)
    if not row:
        raise ValueError("active_constraint_missing")
    confirmation = _adult_confirmation(command)
    removed = state["constraints"]["active"].pop(constraint_id)
    state["constraints"]["events"].append(
        {
            "constraint_event_id": _event_id("constraint-remove", command["idempotency_key"]),
            "constraint_id": constraint_id,
            "event_type": "manually_removed",
            "reason_code": _stable_id(command.get("reason_code"), "reason_code"),
            "recorded_at": command["effective_at"],
            "adult_confirmation_id": confirmation["confirmation_id"],
        }
    )
    return {
        "effect_type": "constraint_removed",
        "constraint_id": constraint_id,
        "previous_constraint_type": removed["constraint_type"],
        "affected_policy_ids": ["policy.reversible-constraint"],
    }


def _expire_constraints(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    now = datetime.fromisoformat(command["effective_at"].replace("Z", "+00:00"))
    expired: list[str] = []
    for constraint_id, row in list(state["constraints"]["active"].items()):
        until = row.get("cooldown_until")
        if until and datetime.fromisoformat(until.replace("Z", "+00:00")) <= now:
            state["constraints"]["active"].pop(constraint_id)
            expired.append(constraint_id)
            state["constraints"]["events"].append(
                {
                    "constraint_event_id": f"constraint-expiry.{constraint_id}.{command['effective_at']}",
                    "constraint_id": constraint_id,
                    "event_type": "expired",
                    "recorded_at": command["effective_at"],
                }
            )
    return {
        "effect_type": "constraint_expiry_evaluated",
        "expired_constraint_ids": sorted(expired),
        "affected_policy_ids": ["policy.reversible-constraint"],
    }


def _grant_sensitive_data_consent(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    consent_id = _stable_id(command.get("consent_id"), "consent_id")
    if command.get("explicit") is not True or command.get("revocable") is not True:
        raise ValueError("explicit_revocable_consent_required")
    if command.get("storage") != "local_only":
        raise ValueError("sensitive_data_storage_must_be_local_only")
    if command.get("subject_or_controller_authorized") is not True:
        raise ValueError("data_controller_authority_missing")
    scope = command.get("field_scope")
    if not isinstance(scope, list) or not scope or not all(str(item).strip() for item in scope):
        raise ValueError("sensitive_data_scope_missing")
    state["authorizations"]["sensitive_data_consents"][consent_id] = {
        "consent_id": consent_id,
        "purpose": _clean_text(command.get("purpose"), limit=200),
        "field_scope": sorted({str(item).strip()[:100] for item in scope}),
        "storage": "local_only",
        "status": "active",
        "granted_at": command["effective_at"],
        "revocable": True,
        "raw_sensitive_data_stored": False,
    }
    return {
        "effect_type": "sensitive_data_consent_granted",
        "consent_id": consent_id,
        "affected_policy_ids": ["policy.local-sensitive-data-consent"],
    }


def _revoke_sensitive_data_consent(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    consent_id = _stable_id(command.get("consent_id"), "consent_id")
    consent = state["authorizations"]["sensitive_data_consents"].get(consent_id)
    if not consent or consent.get("status") != "active":
        raise ValueError("active_consent_missing")
    confirmation = _adult_confirmation(command)
    consent.update(
        {
            "status": "revoked",
            "revoked_at": command["effective_at"],
            "adult_confirmation_id": confirmation["confirmation_id"],
            "new_processing_allowed": False,
        }
    )
    return {
        "effect_type": "sensitive_data_consent_revoked",
        "consent_id": consent_id,
        "affected_policy_ids": ["policy.local-sensitive-data-consent"],
    }


def _request_external_operation(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    operation_id = _stable_id(command.get("operation_id"), "operation_id")
    operation_type = str(command.get("operation_type") or "")
    if operation_type in FORBIDDEN_EXTERNAL_TYPES:
        raise ValueError("paid_or_transferable_operation_forbidden")
    if not operation_type:
        raise ValueError("operation_type_missing")
    if operation_id in state["authorizations"]["external_operations"]:
        raise ValueError("external_operation_id_conflict")
    state["authorizations"]["external_operations"][operation_id] = {
        "operation_id": operation_id,
        "operation_type": operation_type,
        "target_summary": _clean_text(command.get("target_summary"), limit=200),
        "payload_sha256": _stable_id(command.get("payload_sha256"), "payload_sha256"),
        "status": "confirmation_pending",
        "requested_at": command["effective_at"],
        "execution_status": "not_executed",
    }
    return {
        "effect_type": "external_operation_preview_requested",
        "operation_id": operation_id,
        "external_side_effect": False,
        "affected_policy_ids": ["policy.external-operation-confirmation"],
    }


def _confirm_external_operation(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    operation_id = _stable_id(command.get("operation_id"), "operation_id")
    operation = state["authorizations"]["external_operations"].get(operation_id)
    if not operation or operation.get("status") != "confirmation_pending":
        raise ValueError("external_operation_not_pending")
    confirmation = _adult_confirmation(command)
    operation.update(
        {
            "status": "manual_handoff_authorized",
            "confirmed_at": confirmation["confirmed_at"],
            "adult_confirmation_id": confirmation["confirmation_id"],
            "execution_status": "not_executed",
        }
    )
    return {
        "effect_type": "external_manual_handoff_confirmed",
        "operation_id": operation_id,
        "external_side_effect": False,
        "execution_status": "not_executed",
        "affected_policy_ids": ["policy.external-operation-confirmation"],
    }


HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "completion_confirmed": _completion_confirmed,
    "set_reward_goal": _set_reward_goal,
    "request_redemption": _request_redemption,
    "confirm_redemption": _confirm_redemption,
    "record_stage_celebration": _record_stage_celebration,
    "apply_constraint": _apply_constraint,
    "remove_constraint": _remove_constraint,
    "expire_constraints": _expire_constraints,
    "grant_sensitive_data_consent": _grant_sensitive_data_consent,
    "revoke_sensitive_data_consent": _revoke_sensitive_data_consent,
    "request_external_operation": _request_external_operation,
    "confirm_external_operation": _confirm_external_operation,
}


ERROR_RECOVERY = {
    "completion_evidence_not_confirmed": "保留奖励账本不变，先核验完成证据再重试",
    "insufficient_reward_balance": "不扣减星星；保留请求前状态，余额满足后重新提交",
    "adult_confirmation_missing": "不执行兑换、撤销或外部授权；切换到成人设置重新确认",
    "adult_actor_not_authorized": "不执行命令；由成人、监护人或工作台所有者重新确认",
    "forbidden_reward_fulfillment": "移除付费、商户、交易资产或自动外部履约，改用本地虚拟或家庭人工约定",
    "paid_or_transferable_operation_forbidden": "停止该操作；本引擎不支持付费、购买或可交易资产",
    "permanent_or_unknown_constraint_forbidden": "改用提醒、可逆配额、冷却或人工确认",
    "constraint_must_be_reversible": "补充成人可见撤销路径后重新提交",
    "harmful_constraint_forbidden": "删除羞辱或永久损失设计，改用可逆约束",
    "sensitive_data_storage_must_be_local_only": "回退合成数据，或改为明确的当前设备本地保存",
    "explicit_revocable_consent_required": "回退合成数据，直到取得明确且可撤销的本地同意",
    "data_controller_authority_missing": "回退合成数据，直到数据主体或有权控制者确认",
    "idempotency_conflict": "使用新的幂等键表达新意图，或重放与原命令完全一致的载荷",
}


def _error_result(
    state: dict[str, Any],
    command: dict[str, Any],
    protected_truth_sha256: str,
    code: str,
) -> dict[str, Any]:
    state_sha = _state_digest(state)
    return {
        "ok": False,
        "status": "rejected",
        "state": deepcopy(state),
        "receipt": {
            "engine_version": ENGINE_VERSION,
            "command_type": str(command.get("command_type") or "unknown"),
            "command_id": str(command.get("command_id") or "unknown"),
            "state_sha256_before": state_sha,
            "state_sha256_after": state_sha,
            "protected_truth_sha256_before": protected_truth_sha256,
            "protected_truth_sha256_after": protected_truth_sha256,
            "invariant_checks": {
                "mastery_unchanged": True,
                "business_truth_unchanged": True,
                "completion_evidence_unchanged": True,
                "external_side_effect": False,
            },
        },
        "error": {
            "code": code,
            "message": code.replace("_", " "),
            "recovery": ERROR_RECOVERY.get(code, "修正命令合同后使用新的幂等键重试"),
            "state_mutated": False,
        },
    }


def apply_policy_command(
    state: dict[str, Any],
    command: dict[str, Any],
    *,
    protected_truth: Any = None,
) -> dict[str, Any]:
    """Apply one policy command without side effects or input mutation.

    ``protected_truth`` may include caller-owned mastery, business records, and
    completion evidence.  It is fingerprinted only and is never copied into policy
    state.  Replaying the exact command reuses its prior effect; reusing a key with
    a different payload is rejected.
    """

    original = deepcopy(state)
    protected_truth_sha = _digest(protected_truth)
    try:
        validate_policy_state(original)
        if not isinstance(command, dict):
            raise ValueError("command_not_object")
        normalized = deepcopy(command)
        command_type = str(normalized.get("command_type") or "")
        if command_type not in HANDLERS:
            raise ValueError("unsupported_command_type")
        normalized["command_id"] = _stable_id(normalized.get("command_id"), "command_id")
        normalized["idempotency_key"] = _stable_id(
            normalized.get("idempotency_key"), "idempotency_key"
        )
        normalized["effective_at"] = _iso_datetime(
            normalized.get("effective_at"), "effective_at"
        )
        command_sha = _digest(normalized)
        previous = original["processed_commands"].get(normalized["idempotency_key"])
        if previous:
            if previous["command_sha256"] != command_sha:
                raise ValueError("idempotency_conflict")
            current_sha = _state_digest(original)
            return {
                "ok": True,
                "status": "idempotent_replay",
                "state": original,
                "receipt": {
                    "engine_version": ENGINE_VERSION,
                    "command_type": command_type,
                    "command_id": normalized["command_id"],
                    "state_sha256_before": current_sha,
                    "state_sha256_after": current_sha,
                    "protected_truth_sha256_before": protected_truth_sha,
                    "protected_truth_sha256_after": protected_truth_sha,
                    "effect": deepcopy(previous["effect"]),
                    "invariant_checks": {
                        "mastery_unchanged": True,
                        "business_truth_unchanged": True,
                        "completion_evidence_unchanged": True,
                        "duplicate_effect_applied": False,
                        "external_side_effect": False,
                    },
                },
                "error": None,
            }
        next_state = deepcopy(original)
        effect = HANDLERS[command_type](next_state, normalized)
        next_state["processed_commands"][normalized["idempotency_key"]] = {
            "command_type": command_type,
            "command_id": normalized["command_id"],
            "command_sha256": command_sha,
            "effect": deepcopy(effect),
        }
        _append_audit(next_state, normalized, command_type, effect)
        before_sha = _state_digest(original)
        after_sha = _state_digest(next_state)
        return {
            "ok": True,
            "status": "applied",
            "state": next_state,
            "receipt": {
                "engine_version": ENGINE_VERSION,
                "command_type": command_type,
                "command_id": normalized["command_id"],
                "state_sha256_before": before_sha,
                "state_sha256_after": after_sha,
                "protected_truth_sha256_before": protected_truth_sha,
                "protected_truth_sha256_after": protected_truth_sha,
                "effect": effect,
                "invariant_checks": {
                    "mastery_unchanged": True,
                    "business_truth_unchanged": True,
                    "completion_evidence_unchanged": True,
                    "duplicate_effect_applied": False,
                    "external_side_effect": False,
                },
            },
            "error": None,
        }
    except (KeyError, TypeError, ValueError) as exc:
        code = str(exc).strip("'") or "invalid_command"
        return _error_result(original, command if isinstance(command, dict) else {}, protected_truth_sha, code)


def apply_policy_event(
    state: dict[str, Any], event: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Public event API used by governance and future renderer integrations."""

    context = context or {}
    protected_truth = (
        context["protected_truth"]
        if isinstance(context, dict) and "protected_truth" in context
        else context
    )
    return apply_policy_command(
        state,
        event,
        protected_truth=protected_truth,
    )


def _path_value(value: Any, path: str) -> Any:
    parts = path.split(".")

    def walk(current: Any, index: int) -> Any:
        if index == len(parts):
            return current
        if isinstance(current, dict):
            for end in range(len(parts), index, -1):
                key = ".".join(parts[index:end])
                if key in current:
                    return walk(current[key], end)
            return None
        if isinstance(current, list) and parts[index].isdigit():
            item_index = int(parts[index])
            return walk(current[item_index], index + 1) if item_index < len(current) else None
        return None

    return walk(value, 0)


def run_policy_test_vector(vector: dict[str, Any]) -> dict[str, Any]:
    """Execute one registry vector and return its assertion report."""

    initial = initial_policy_state()
    state = initial
    protected_truth = deepcopy(
        vector.get(
            "protected_truth",
            {
                "mastery": {"status": "caller_owned"},
                "business_truth": {"value": 17},
                "completion_evidence": {"status": "caller_owned"},
            },
        )
    )
    protected_before = deepcopy(protected_truth)
    setup_results: list[dict[str, Any]] = []
    for setup in vector.get("setup_events", []):
        result = apply_policy_event(state, setup, {"protected_truth": protected_truth})
        setup_results.append(result)
        if not result["ok"]:
            return {
                "vector_id": vector.get("vector_id"),
                "passed": False,
                "failures": [f"setup_failed:{result['error']['code']}"],
                "result": result,
            }
        state = result["state"]
    state_before_event = deepcopy(state)
    result = apply_policy_event(state, vector["event"], {"protected_truth": protected_truth})
    input_unchanged = state == state_before_event and protected_truth == protected_before
    if vector.get("repeat_event") and result["ok"]:
        replay_input = deepcopy(result["state"])
        replay = apply_policy_event(
            result["state"], vector["event"], {"protected_truth": protected_truth}
        )
        replay["input_unchanged"] = result["state"] == replay_input
        result = replay
    expected = vector.get("expected", {})
    failures: list[str] = []
    if "ok" in expected and result["ok"] is not expected["ok"]:
        failures.append(f"ok:{result['ok']}!={expected['ok']}")
    if "status" in expected and result["status"] != expected["status"]:
        failures.append(f"status:{result['status']}!={expected['status']}")
    actual_error = result["error"]["code"] if result.get("error") else None
    if "error_code" in expected and actual_error != expected["error_code"]:
        failures.append(f"error_code:{actual_error}!={expected['error_code']}")
    effect_type = _path_value(result, "receipt.effect.effect_type")
    if "effect_type" in expected and effect_type != expected["effect_type"]:
        failures.append(f"effect_type:{effect_type}!={expected['effect_type']}")
    if expected.get("input_unchanged") is True and not input_unchanged:
        failures.append("input_mutated")
    invariant_checks = result["receipt"]["invariant_checks"]
    if expected.get("protected_truth_unchanged") is True and not all(
        invariant_checks.get(key) is True
        for key in (
            "mastery_unchanged",
            "business_truth_unchanged",
            "completion_evidence_unchanged",
        )
    ):
        failures.append("protected_truth_invariant_failed")
    projection_date = expected.get("projection_as_of")
    projection = (
        reward_projection(result["state"], as_of_date=projection_date)
        if projection_date
        else None
    )
    for key in (
        "balance",
        "earned_total",
        "spent_total",
        "current_streak_days",
        "longest_streak_days",
    ):
        if key in expected and (projection or {}).get(key) != expected[key]:
            failures.append(f"{key}:{(projection or {}).get(key)}!={expected[key]}")
    derived = {
        "ledger_event_count": len(result["state"]["reward"]["ledger_events"]),
        "celebration_count": len(result["state"]["reward"]["celebrations"]),
        "active_constraint_count": len(result["state"]["constraints"]["active"]),
    }
    for key, actual in derived.items():
        if key in expected and actual != expected[key]:
            failures.append(f"{key}:{actual}!={expected[key]}")
    for path, wanted in expected.get("path_equals", {}).items():
        actual = _path_value(result, path)
        if actual != wanted:
            failures.append(f"path:{path}:{actual}!={wanted}")
    return {
        "vector_id": vector.get("vector_id"),
        "passed": not failures,
        "failures": failures,
        "result": result,
        "projection": projection,
        "setup_count": len(setup_results),
    }


def run_policy_test_vectors(registry: dict[str, Any]) -> dict[str, Any]:
    """Validate a registry and execute all of its declared vectors."""

    validation = validate_policy_registry(registry)
    reports = [run_policy_test_vector(vector) for vector in registry["test_vectors"]]
    passed = sum(report["passed"] for report in reports)
    return {
        "ok": passed == len(reports),
        "engine_version": ENGINE_VERSION,
        "registry_sha256": validation["registry_sha256"],
        "test_vector_count": len(reports),
        "passed": passed,
        "failed": len(reports) - passed,
        "failures": [
            {"vector_id": report["vector_id"], "failures": report["failures"]}
            for report in reports
            if not report["passed"]
        ],
    }


__all__ = [
    "ENGINE_VERSION",
    "STATE_SCHEMA_VERSION",
    "apply_policy_event",
    "apply_policy_command",
    "initial_policy_state",
    "reward_projection",
    "run_policy_test_vector",
    "run_policy_test_vectors",
    "validate_policy_registry",
    "validate_policy_state",
]
