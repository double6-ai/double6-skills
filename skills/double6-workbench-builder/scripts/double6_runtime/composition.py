"""声明式工作台组合内核：场景、对象、表面与运行时绑定的唯一入口。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .core import ContractError, REFERENCES, canonical, digest_bytes, read_json


COMPOSITION_FILE = "workbench-composition-packs.json"
SURFACE_TEMPLATE_FILE = "workbench-surface-templates.json"
DASHBOARD_TEMPLATE_FILE = "workbench-dashboard-templates.json"
PACK_DASHBOARD_RUNTIMES = {
    "personal-week-runtime-v1",
    "content-pipeline-runtime-v1",
    "sales-pipeline-runtime-v1",
}
CONTRACT_VERSION = "double6_declarative_composition_v2"
KERNEL_VERSION = "1.1.0"
EXPECTED_ATTENTION_REGIONS = {"now", "flow", "capture", "attention"}
ALLOWED_DISCLOSURE_MODES = {"open", "summary", "drawer"}
RUNTIME_IDS = {
    "personal-week-runtime-v1",
    "content-pipeline-runtime-v1",
    "sales-pipeline-runtime-v1",
    "object-pipeline-runtime-v1",
    "child-playground-runtime-v1",
    "fitness-daily-runtime-v1",
    "teacher-class-runtime-v1",
    "exam-practice-runtime-v1",
    "household-handoff-runtime-v1",
    "finance-bookkeeping-runtime-v1",
    "commerce-order-runtime-v1",
    "research-evidence-runtime-v1",
    "personal-life-runtime-v1",
    "cet4-sprint-runtime-v1",
}
OBJECT_PIPELINE_RUNTIME = "object-pipeline-runtime-v1"
CHILD_PLAYGROUND_RUNTIME = "child-playground-runtime-v1"
GENERIC_SURFACE_TEMPLATE = "generic-module-surface-v1"
SCENE_TEMPLATE_FILE = "vivid-social-template-system.json"
DOMAIN_CONTENT_FILE = "domain-content-packs.json"
SCENE_PROFILE_FILE = "scene-profiles.json"
ACCEPTANCE_PROGRAM_VERSION = "double6_acceptance_program_v1"
GENERIC_TASK_SPECS = {
    "reload_persistence": {
        "mode": "generic_executable",
        "existing_evaluate": "core_flow.persistence_pass",
        "required_markers": (
            ("data-double6-hook='save'", 'data-double6-hook="save"'),
            ("function persist(", "localStorage.setItem"),
        ),
    },
    "import_preview_and_undo": {
        "mode": "generic_executable",
        "existing_evaluate": "export_import.import_undo_pass",
        "required_markers": (
            ("data-double6-hook='undo-import'", 'data-double6-hook="undo-import"'),
            ("data-import-preview", "pendingImportState"),
        ),
    },
}
NAMED_HOP_TASKS = {
    "capture_to_week": (("inbox_item", "week_outcome"),),
    "week_or_project_to_today": (("week_outcome", "today_action"), ("project", "today_action")),
    "source_to_topic": (("source_item", "topic"),),
    "topic_to_brief": (("topic", "brief"),),
    "brief_to_production": (("brief", "production_item"),),
    "lead_to_client": (("lead", "client"),),
    "client_to_followup": (("client", "followup"),),
    "question_to_evidence": (("research_question", "evidence_item"),),
    "evidence_to_claim": (("evidence_item", "writing_claim"),),
}
CONTRACT_ONLY_TASK_SPECS = {
    "top_three_capacity": (("PERSONAL_TOP_PRIORITIES",), ("Top 1",), ("promote-top",)),
    "weekly_review_from_local_facts": (("function personalReviewFacts",), ("data-personal-review",)),
    "manual_publish_state_separation": (("[发布状态:${status}]",), ("待人工发布",), ("not_executed",)),
    "metric_to_next_topic": (("schedule-to-review",), ("人工录入 / 未核验",)),
    "overdue_visibility": (("sales-overdue",), ("逾期",)),
    "inquiry_quote_versioning": (("sales-quotes",), ("报价版本",)),
    "manual_send_confirmation": (("人工确认已发送", "人工确认已沟通"), ("not_executed",)),
    "weekly_pipeline_review": (("function salesReviewFacts",),),
    "claim_requires_source_or_gap": (("write_claim_only_with_evidence_or_gap",),),
    "coverage_review_from_local_facts": (("list_gaps_and_next_week_action",),),
    "derived_selected_scope": (("data-composition-surface-template=",),),
    "derived_object_chain": (('"relation"',),),
    "derived_attention_model": (('"region_id"',),),
    "derived_maturity_boundary": (("catalog_only", "contract_ready", "executable_ready"),),
    "first_completion_star": (("earn_and_redeem_stars_without_changing_mastery",),),
    "parent_confirm_redeem": (("education-rewards",), ("reward_ledger",)),
    "reward_truth_isolation": (("earn_and_redeem_stars_without_changing_mastery",),),
    "practice_to_error_repair": (("education-errors",), ("error_item",)),
    "parent_observe_only": (("education-parent",), ("parent_review",)),
    "no_adjacent_grade_fallback": (("exact_module_ids",), ("education-language",)),
    "no_textbook_alignment_claim": (("generic-module-surface-v1",), ("education-parent",)),
    "starter_empty_state_disclosed": (("capture",), ("education-language",)),
    "parent_beside_required": (("今天一起玩",), ("家长陪同",)),
    "no_unreviewed_game_content": (("不用未审游戏顶替",), ("exact_module_ids",)),
    "no_punishment_or_pet_hunger_mastery": (("惩罚不改掌握",), ("education-parent",)),
    "no_static_image_as_control": (("generic-module-surface-v1",), ("先用开箱内容",)),
    "reset_today_not_clear_all": (("重置今日不等于清空全部",), ("education-parent",)),
    "subject_learn_practice_library": (("学一学",), ("练一练",), ("题库",)),
    "fill_slots_original_order_current": (("按原文顺序填空",), ("高亮当前空",)),
    "family_tasks_opt_in_default_off": (("家庭任务默认关闭",), ("education-parent",)),
    "fact_calendar_not_mastery": (("本月打卡事实",), ("不是掌握",)),
    "incentive_loop_first_class": (("education-rewards",), ("earn_and_redeem_stars_without_changing_mastery",)),
    "combo_bonus_and_daily_three": (("combo_bonus",), ("daily_three_complete",)),
    "badge_wall_unlock": (("查看全部徽章",), ("checkBadges",)),
    "parent_star_adjust": (("家长调整星星",), ("parent_adjust",)),
    "combo_and_badge_wall": (("查看全部徽章",), ("combo_bonus",)),
    "companion_stake_visible": (("data-companion-card",), ("换房间",)),
    "room_theme_switchable": (("function applyRoom",), ("data-room",), ("换房间",)),
    "room_claim_visible": (("data-room-claim-label",), ("function roomClaimLabel",)),
    "warm_incorrect_visible": (("data-warm-incorrect",), ("答错也暖",)),
    "companion_growth_visible": (("data-companion-growth",), ("做过",)),
    "garden_progress_visible": (("data-garden-progress",), ("最近的花园",)),
    "adult_daily_warmth_visible": (("data-adult-warmth",), ("renderAdultWarmth",)),
    "fitness_daily_warmth_visible": (("data-fitness-warmth",), ("data-fitness-warmth-text",), ("renderFitnessWarmth",)),
    "tonight_set_visible": (("data-fitness-tonight-set",), ("data-fitness-move-list",), ("data-fitness-set",)),
    "fitness_daily_board_visible": (("data-fitness-daily-board",), ("data-fitness-weight-form",), ("data-fitness-meal-form",)),
    "log_today_weight": (("data-fitness-weight-form",), ("data-fitness-weight-input",)),
    "log_today_meal": (("data-fitness-meal-form",), ("data-fitness-meal-title",)),
    "checkin_today": (("data-fitness-checkin",), ("data-fitness-calendar",)),
    "teacher_class_board_visible": (("data-teacher-class-board",), ("data-teacher-duty-form",), ("data-teacher-attendance-list",)),
    "teacher_class_warmth_visible": (("data-teacher-warmth",), ("data-teacher-warmth-text",), ("renderTeacherWarmth",)),
    "tick_today_duty": (("data-teacher-duty-toggle",), ("data-teacher-duty-form",)),
    "mark_today_attendance": (("data-teacher-att-set",), ("data-teacher-att-status",)),
    "close_today_followup": (("data-teacher-follow-done",), ("data-teacher-follow-handoff",)),
    "exam_practice_board_visible": (("data-exam-practice-board",), ("data-exam-now",), ("data-exam-submit",)),
    "exam_practice_warmth_visible": (("data-exam-warmth",), ("data-exam-warmth-text",), ("renderExamWarmth",)),
    "content_tonight_board_visible": (("data-content-tonight-board",), ("data-content-opening-form",), ("data-content-opening",)),
    "content_tonight_warmth_visible": (("data-content-warmth",), ("data-content-warmth-text",), ("renderContentWarmth",)),
    "write_tonight_opening": (("data-content-opening-form",), ("data-content-opening",), ("留下这段开头",)),
    "content_week_written_visible": (("data-content-week",), ("data-content-week-count",), ("哪天写下过",)),
    "sales_tonight_board_visible": (("data-sales-tonight-board",), ("data-sales-today-act",), ("data-sales-today-alias",)),
    "sales_tonight_warmth_visible": (("data-sales-warmth",), ("data-sales-warmth-text",), ("renderSalesWarmth",)),
    "follow_tonight_account": (("data-sales-today-act",), ("今天跟这家",), ("改到明天",)),
    "answer_tonight_question": (("data-exam-submit",), ("data-exam-option",)),
    "review_exam_error": (("data-exam-retry",), ("data-exam-error-list",)),
    "household_tonight_board_visible": (("data-household-tonight-board",), ("data-household-chore-list",), ("data-household-tell-list",)),
    "household_tonight_warmth_visible": (("data-household-warmth",), ("data-household-warmth-text",), ("renderHouseholdWarmth",)),
    "tick_tonight_chore": (("data-household-chore-toggle",), ("data-household-chore-form",)),
    "mark_tell_in_person": (("data-household-tell-pending",), ("data-household-tell-done",), ("当面说",)),
    "finance_tonight_board_visible": (("data-finance-tonight-board",), ("data-finance-log-form",), ("data-finance-today-total",)),
    "finance_tonight_warmth_visible": (("data-finance-warmth",), ("data-finance-warmth-text",), ("renderFinanceWarmth",)),
    "log_tonight_amount": (("data-finance-log-form",), ("data-finance-log-amount",), ("记下这笔",)),
    "tick_tonight_voucher": (("data-finance-voucher-toggle",), ("data-finance-voucher-list",)),
    "keep_tax_unfiled": (("data-finance-tax-list",), ("待专业处理",), ("不是已申报",)),
    "commerce_tonight_board_visible": (("data-commerce-tonight-board",), ("data-commerce-order-form",), ("data-commerce-stock-form",)),
    "commerce_tonight_warmth_visible": (("data-commerce-warmth",), ("data-commerce-warmth-text",), ("renderCommerceWarmth",)),
    "handle_tonight_order": (("data-commerce-order-form",), ("data-commerce-order-handoff",), ("不是已发货",)),
    "log_stock_snapshot": (("data-commerce-stock-form",), ("data-commerce-stock-count",), ("不是实时库存",)),
    "keep_service_unsent": (("data-commerce-service-list",), ("待在平台回",), ("没有发给任何人",)),
    "research_tonight_board_visible": (("data-research-tonight-board",), ("data-research-claim-form",), ("data-research-evidence-form",)),
    "research_tonight_warmth_visible": (("data-research-warmth",), ("data-research-warmth-text",), ("renderResearchWarmth",)),
    "life_today_page_visible": (("data-life-today-page",), ("今日一页",)),
    "life_complete_top_one": (("data-life-top-one",), ("data-life-top-one-done",)),
    "life_log_mood": (("data-life-mood-quick",), ("data-life-mood-save",)),
    "life_check_habit": (("data-life-habit-quick",), ("data-life-habit-done",)),
    "life_deduped_streak": (("function lifeDedupedDates",), ("function lifeFactStreak",)),
    "adult_fact_projection_visible": (("data-adult-fact-projection",), ("目标等分",)),
    # 历史 task ID 保留以避免已确认 composition SHA 漂移；现在验证的是
    # 设计阶段锁定单主题，成品不启用运行时主题切换。
    "theme_switch_isolated": (
        ("data-double6-theme-selection-stage='design_time'",),
        ("data-double6-theme-runtime-switching='false'",),
        ("data-theme-id=",),
    ),
    "cet4_original_items": (("cet4-listen-01",), ("cet4-read-12",), ("非真题",)),
    "cet4_error_reflow": (("data-exam-retry",), ("retains-original-mistake-fact",)),
    "cet4_manual_review": (("data-cet4-manual-review",), ("需人工复核",)),
    "cet4_timer_resume": (("data-cet4-timer",), ("startedAt",), ("pausedRemainingMs",)),
    "cet4_source_boundary": (("教育部教育考试院",), ("CET4考核内容",), ("非真题",)),
    "write_tonight_claim": (("data-research-claim-form",), ("data-research-claim-title",), ("留下今晚这条",)),
    "keep_claim_sourced_or_gap": (("data-research-claim-source",), ("标缺口",), ("不能空着写成已证实",)),
    "check_one_set": (("data-fitness-set",), ("sets_done",)),
    "stop_one_set": (("data-fitness-stop",), ("stop_reason",)),
}
SPECIALIZED_HOP_MARKERS = {
    "capture_to_week": (("promote-week",), ("promoted_to_week",)),
    "week_or_project_to_today": (("plan-today",),),
    "source_to_topic": (("source-to-topic",),),
    "topic_to_brief": (("topic-to-brief",),),
    "brief_to_production": (("brief-to-production",),),
    "lead_to_client": (("lead-to-client",), ("qualified_to_client",)),
    "client_to_followup": (("client-to-followup",),),
}
POLICY_KINDS = {
    "capacity_slots",
    "manual_handoff_fsm",
    "promote_gate",
    "review_from_local_facts",
    "due_bucket",
}
TASK_POLICY_IDS = {
    "top_three_capacity": "top_three_capacity",
    "weekly_review_from_local_facts": "weekly_review_from_local_facts",
    "manual_publish_state_separation": "manual_publish_state_separation",
    "overdue_visibility": "overdue_visibility",
    "manual_send_confirmation": "manual_send_confirmation",
    "inquiry_quote_versioning": "quote_versioning",
    "weekly_pipeline_review": "weekly_pipeline_review",
}
REQUIRED_RUNTIME_POLICIES = {
    "personal-week-runtime-v1": ("top_three_capacity", "weekly_review_from_local_facts"),
    "content-pipeline-runtime-v1": ("manual_publish_state_separation",),
    "sales-pipeline-runtime-v1": (
        "lead_qualification",
        "overdue_visibility",
        "manual_send_confirmation",
        "quote_versioning",
        "weekly_pipeline_review",
    ),
}


def _unique_rows(rows: Any, field: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"{label} 必须是非空列表")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get(field) or "").strip():
            raise ContractError(f"{label} 含无效 {field}")
        row_id = str(row[field])
        if row_id in result:
            raise ContractError(f"{label} 含重复 {field}：{row_id}")
        result[row_id] = row
    return result


def _has_marker_group(corpus: str, group: Sequence[str]) -> bool:
    return any(marker in corpus for marker in group)


def _pack_policies(pack: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = pack.get("runtime_policies") or []
    if rows and not isinstance(rows, list):
        raise ContractError("runtime_policies 必须是列表")
    return _unique_rows(rows, "policy_id", "runtime_policies") if rows else {}


def _validate_runtime_policies(pack: Mapping[str, Any], scene_id: str) -> None:
    runtime_id = str(pack.get("runtime_binding", {}).get("runtime_id") or "")
    policies = _pack_policies(pack)
    required = REQUIRED_RUNTIME_POLICIES.get(runtime_id, ())
    missing = [policy_id for policy_id in required if policy_id not in policies]
    if missing:
        raise ContractError(f"composition runtime policy 缺失：{scene_id} {missing}")
    module_ids = set(pack.get("exact_module_ids", []))
    for policy_id, row in policies.items():
        if row.get("kind") not in POLICY_KINDS:
            raise ContractError(f"runtime policy kind 无效：{policy_id}")
        bound = str(row.get("module_id") or row.get("from_module_id") or "")
        if bound and bound not in module_ids:
            raise ContractError(f"runtime policy 引用未选模块：{policy_id}")
        if row["kind"] == "capacity_slots":
            values = row.get("committed_values")
            if not isinstance(values, list) or len(values) < 1 or int(row.get("max_committed") or 0) != len(values):
                raise ContractError(f"capacity_slots 合同不完整：{policy_id}")
        if row["kind"] == "manual_handoff_fsm":
            states = row.get("states")
            if not isinstance(states, list) or len(states) < 2 or row.get("confirmed_state") not in states:
                raise ContractError(f"manual_handoff_fsm 合同不完整：{policy_id}")
        if row["kind"] == "promote_gate":
            fields = row.get("required_fields")
            if not isinstance(fields, list) or not fields:
                raise ContractError(f"promote_gate 合同不完整：{policy_id}")


def object_pipeline_next_hop(pack: Mapping[str, Any], from_type: str) -> dict[str, Any] | None:
    """复现通用对象链运行时：每个 from 类型只取第一条 relation。"""
    relations = pack.get("object_graph", {}).get("relations", [])
    rel = next((row for row in relations if row.get("from") == from_type), None)
    if rel is None:
        return None
    target = next(
        (row for row in pack.get("modules", []) if row.get("object_type_id") == rel.get("to")),
        None,
    )
    if target is None:
        return None
    return {
        "from": rel["from"],
        "to": rel["to"],
        "relation": rel["relation"],
        "module_id": target["module_id"],
    }


def _named_task_row(
    task_id: str,
    pack: Mapping[str, Any],
    runtime_id: str,
) -> dict[str, Any]:
    if task_id in GENERIC_TASK_SPECS:
        spec = GENERIC_TASK_SPECS[task_id]
        return {
            "task_id": task_id,
            "kind": "generic",
            "mode": spec["mode"],
            "existing_evaluate": spec["existing_evaluate"],
            "required_markers": [list(group) for group in spec["required_markers"]],
        }
    policy_id = TASK_POLICY_IDS.get(task_id)
    policy = _pack_policies(pack).get(policy_id) if policy_id else None
    if policy:
        return {
            "task_id": task_id,
            "kind": "runtime_policy",
            "mode": "policy_executable",
            "policy_id": policy_id,
            "policy_kind": policy["kind"],
            "required_markers": [
                [f'"policy_id": "{policy_id}"', f'"policy_id":"{policy_id}"'],
                ["function policyById"],
            ],
        }
    hops = NAMED_HOP_TASKS.get(task_id)
    if hops:
        graph = {
            (str(row.get("from")), str(row.get("to")))
            for row in pack.get("object_graph", {}).get("relations", [])
        }
        missing = [list(pair) for pair in hops if pair not in graph]
        if missing:
            raise ContractError(f"acceptance task 缺少 object_graph 边：{task_id} {missing}")
        if runtime_id == OBJECT_PIPELINE_RUNTIME:
            executable = []
            contract_only = []
            for from_type, to_type in hops:
                hop = object_pipeline_next_hop(pack, from_type)
                if hop and hop["to"] == to_type:
                    executable.append(hop)
                else:
                    contract_only.append({"from": from_type, "to": to_type})
            if executable and not contract_only:
                return {
                    "task_id": task_id,
                    "kind": "object_graph_hop",
                    "mode": "object_pipeline_executable",
                    "hops": executable,
                    "required_markers": [
                        ["function pipelineNextHop"],
                        ["data-pipeline-promote"],
                        [f'"from":"{executable[0]["from"]}"', f'"from": "{executable[0]["from"]}"'],
                    ],
                }
        markers = SPECIALIZED_HOP_MARKERS.get(task_id)
        if not markers:
            raise ContractError(f"专用运行时缺少 hop 标记合同：{task_id}")
        return {
            "task_id": task_id,
            "kind": "object_graph_hop",
            "mode": "contract_only",
            "hops": [{"from": from_type, "to": to_type} for from_type, to_type in hops],
            "required_markers": [list(group) for group in markers],
        }
    spec = CONTRACT_ONLY_TASK_SPECS.get(task_id)
    if spec is None:
        raise ContractError(f"未登记的 composition acceptance task：{task_id}")
    return {
        "task_id": task_id,
        "kind": "scene_specific",
        "mode": "contract_only",
        "required_markers": [list(group) for group in spec],
    }


def compile_acceptance_program(pack: Mapping[str, Any]) -> dict[str, Any]:
    """把 pack.acceptance_tasks、对象图、注意力区和视口合同编成结构化验收程序。"""
    if not isinstance(pack, Mapping):
        raise ContractError("acceptance program 需要 composition pack")
    runtime_id = str(pack.get("runtime_binding", {}).get("runtime_id") or "")
    if runtime_id not in RUNTIME_IDS:
        raise ContractError(f"acceptance program runtime 无效：{runtime_id}")
    named_tasks = pack.get("acceptance_tasks", [])
    if not isinstance(named_tasks, list) or len(named_tasks) < 6 or len(named_tasks) != len(set(named_tasks)):
        raise ContractError("acceptance program 任务列表不完整")
    tasks = [_named_task_row(str(task_id), pack, runtime_id) for task_id in named_tasks]
    always_on = [
        {
            "task_id": "home_attention_four_regions",
            "kind": "always_on",
            "mode": "static_scan",
            "required_markers": [
                ['"region_id":"now"', '"region_id": "now"'],
                ['"region_id":"flow"', '"region_id": "flow"'],
                ['"region_id":"capture"', '"region_id": "capture"'],
                ['"region_id":"attention"', '"region_id": "attention"'],
            ],
        },
        {
            "task_id": "visibility_default_disclosure",
            "kind": "always_on",
            "mode": "static_scan",
            "required_markers": [
                ["data-composition-disclosure=", '"default_disclosure"'],
            ],
        },
        {
            "task_id": "three_viewport_contract",
            "kind": "always_on",
            "mode": "delegated_to_evaluate",
            "existing_evaluate": "responsive",
            "required_markers": [],
            "viewports": ["mobile", "tablet", "desktop"],
        },
    ]
    payload = {
        "schema_version": 1,
        "contract_version": ACCEPTANCE_PROGRAM_VERSION,
        "kernel_version": KERNEL_VERSION,
        "composition_id": pack.get("composition_id"),
        "scene_profile_id": pack.get("scene_profile_id"),
        "runtime_id": runtime_id,
        "named_task_ids": list(named_tasks),
        "tasks": tasks,
        "always_on": always_on,
    }
    payload["program_sha256"] = digest_bytes(canonical(payload))
    return payload


def scan_acceptance_program(program: Mapping[str, Any], corpus: str) -> dict[str, Any]:
    """对照候选 HTML 或 pack+runtime 语料检查验收程序标记，不启动浏览器。"""
    if not isinstance(program, Mapping) or program.get("contract_version") != ACCEPTANCE_PROGRAM_VERSION:
        raise ContractError("acceptance program 无效")
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    for row in list(program.get("tasks", [])) + list(program.get("always_on", [])):
        task_id = str(row.get("task_id") or "")
        mode = str(row.get("mode") or "")
        if mode == "delegated_to_evaluate":
            results.append({"task_id": task_id, "mode": mode, "status": "recorded"})
            continue
        missing = [
            list(group)
            for group in row.get("required_markers", [])
            if not _has_marker_group(corpus, group)
        ]
        status = "pass" if not missing else "fail"
        if missing:
            errors.append(f"acceptance task 缺少实现标记：{task_id} {missing}")
        results.append({"task_id": task_id, "mode": mode, "status": status, "missing_markers": missing})
    return {
        "status": "pass" if not errors else "fail",
        "program_sha256": program.get("program_sha256"),
        "composition_id": program.get("composition_id"),
        "results": results,
        "errors": errors,
    }


def execute_object_pipeline_program(pack: Mapping[str, Any], corpus: str) -> dict[str, Any]:
    """用 Python 复现通用对象链的第一跳，确认 pack 边能被运行时推进。"""
    runtime_id = str(pack.get("runtime_binding", {}).get("runtime_id") or "")
    if runtime_id != OBJECT_PIPELINE_RUNTIME:
        return {"status": "skipped", "reason": "not_object_pipeline", "hops": []}
    errors: list[str] = []
    if "function pipelineNextHop" not in corpus:
        errors.append("object pipeline 缺少 pipelineNextHop")
    if "data-pipeline-promote" not in corpus:
        errors.append("object pipeline 缺少 data-pipeline-promote")
    hops: list[dict[str, Any]] = []
    program = compile_acceptance_program(pack)
    for row in program["tasks"]:
        if row.get("mode") != "object_pipeline_executable":
            continue
        for expected in row.get("hops", []):
            actual = object_pipeline_next_hop(pack, expected["from"])
            ok = bool(actual and actual["to"] == expected["to"] and actual["module_id"])
            hops.append({"task_id": row["task_id"], "expected": expected, "actual": actual, "status": "pass" if ok else "fail"})
            if not ok:
                errors.append(f"object pipeline 无法执行第一跳：{row['task_id']}")
    return {"status": "pass" if not errors else "fail", "hops": hops, "errors": errors}


def composition_registry() -> dict[str, Any]:
    value = read_json(REFERENCES / COMPOSITION_FILE)
    if value.get("schema_version") != 1 or value.get("contract_version") != CONTRACT_VERSION:
        raise ContractError("composition registry schema/contract 版本无效")
    if value.get("kernel_version") != KERNEL_VERSION:
        raise ContractError("composition registry kernel 版本无效")
    if set(value.get("allowed_disclosure_modes", [])) != ALLOWED_DISCLOSURE_MODES:
        raise ContractError("composition registry disclosure 模式不完整")
    packs = _unique_rows(value.get("packs"), "scene_profile_id", "composition packs")
    if len(packs) < 3:
        raise ContractError("composition registry 至少登记三个成熟场景")
    template_registry = read_json(REFERENCES / SURFACE_TEMPLATE_FILE)
    templates = template_registry.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ContractError("surface template registry 为空")
    dashboard_registry = read_json(REFERENCES / DASHBOARD_TEMPLATE_FILE)
    dashboards = dashboard_registry.get("templates")
    if not isinstance(dashboards, dict) or not dashboards:
        raise ContractError("dashboard template registry 为空")
    composition_ids: set[str] = set()
    for scene_id, pack in packs.items():
        composition_id = str(pack.get("composition_id") or "")
        if not composition_id or composition_id in composition_ids:
            raise ContractError(f"composition_id 无效或重复：{scene_id}")
        composition_ids.add(composition_id)
        exact_modules = [str(value) for value in pack.get("exact_module_ids", [])]
        module_rows = _unique_rows(pack.get("modules"), "module_id", f"composition modules:{scene_id}")
        if not 4 <= len(exact_modules) <= 15 or len(exact_modules) != len(set(exact_modules)):
            raise ContractError(f"composition exact module 范围无效：{scene_id}")
        if exact_modules != list(module_rows):
            raise ContractError(f"composition module 顺序或范围漂移：{scene_id}")
        if pack.get("tonight_nav_module_ids"):
            raise ContractError(f"不得用 tonight_nav 收窄侧栏：{scene_id}。丰富度是每个已选房间有活，不是少开房间")
        for module_id, row in module_rows.items():
            title_fields = row.get("title_fields")
            if (
                row.get("default_disclosure") not in ALLOWED_DISCLOSURE_MODES
                or not str(row.get("object_type_id") or "").strip()
                or not str(row.get("primary_job") or "").strip()
                or not str(row.get("surface_template_id") or "").strip()
                or not str(row.get("surface_signature") or "").strip()
                or not str(row.get("link_label") or "").strip()
                or not isinstance(title_fields, list)
                or not title_fields
                or any(not str(field or "").strip() for field in title_fields)
            ):
                raise ContractError(f"composition module contract 不完整：{module_id}")
            if str(row["surface_template_id"]) not in templates:
                raise ContractError(f"composition surface template 未登记：{row['surface_template_id']}")
            stage_values = row.get("stage_values")
            gate_fields = row.get("gate_fields")
            if stage_values is not None:
                if (
                    not isinstance(stage_values, list)
                    or not stage_values
                    or any(not str(value or "").strip() for value in stage_values)
                    or not str(row.get("stage_field") or "").strip()
                ):
                    raise ContractError(f"composition module stage 合同不完整：{module_id}")
                default_stage = str(row.get("default_stage") or "")
                ready_stage = str(row.get("promote_ready_stage") or "")
                terminals = row.get("terminal_stages")
                if default_stage and default_stage not in stage_values:
                    raise ContractError(f"composition default_stage 不在阶段列表：{module_id}")
                if ready_stage and ready_stage not in stage_values:
                    raise ContractError(f"composition promote_ready_stage 不在阶段列表：{module_id}")
                if terminals is not None and (
                    not isinstance(terminals, list)
                    or any(str(value) not in stage_values for value in terminals)
                ):
                    raise ContractError(f"composition terminal_stages 无效：{module_id}")
            if gate_fields is not None and (
                not isinstance(gate_fields, list)
                or not gate_fields
                or any(not str(field or "").strip() for field in gate_fields)
            ):
                raise ContractError(f"composition module gate_fields 无效：{module_id}")
        attention = pack.get("attention_model", {})
        regions = _unique_rows(attention.get("regions"), "region_id", f"attention regions:{scene_id}")
        if set(regions) != EXPECTED_ATTENTION_REGIONS:
            raise ContractError(f"composition attention model 不完整：{scene_id}")
        for region in regions.values():
            if not set(region.get("source_module_ids", [])) <= set(exact_modules):
                raise ContractError(f"attention region 引用未选模块：{scene_id}")
        projection = pack.get("execution_projection")
        if not isinstance(projection, Mapping) or projection.get("projection_version") != "double6_execution_projection_v1":
            raise ContractError(f"composition execution_projection 缺失：{scene_id}")
        for key in ("today_module_ids", "lifecycle_module_ids", "attention_module_ids"):
            values = projection.get(key)
            if not isinstance(values, list) or not values or not set(values) <= set(exact_modules):
                raise ContractError(f"execution_projection.{key} 无效：{scene_id}")
        for key in ("next_action_fields", "blocker_fields", "completion_events"):
            values = projection.get(key)
            if not isinstance(values, list) or not values or any(not str(value or "").strip() for value in values):
                raise ContractError(f"execution_projection.{key} 无效：{scene_id}")
        object_graph = pack.get("object_graph", {})
        object_types = {str(value) for value in object_graph.get("object_types", [])}
        if not object_types or object_types != {str(row["object_type_id"]) for row in module_rows.values()}:
            raise ContractError(f"composition object graph 与模块对象不一致：{scene_id}")
        relations = object_graph.get("relations", [])
        if not isinstance(relations, list) or not relations or any(
            not isinstance(row, Mapping)
            or row.get("from") not in object_types
            or row.get("to") not in object_types
            or not str(row.get("relation") or "").strip()
            for row in relations
        ):
            raise ContractError(f"composition object relations 无效：{scene_id}")
        runtime = pack.get("runtime_binding", {})
        if runtime.get("runtime_id") not in RUNTIME_IDS or not all(
            str(runtime.get(key) or "").strip()
            for key in ("helper_slot", "render_slot", "listener_slot")
        ):
            raise ContractError(f"composition runtime binding 无效：{scene_id}")
        if runtime.get("runtime_id") in PACK_DASHBOARD_RUNTIMES:
            dashboard_id = str(pack.get("dashboard_template_id") or "").strip()
            dashboard = dashboards.get(dashboard_id)
            if not dashboard_id or not isinstance(dashboard, Mapping):
                raise ContractError(f"composition dashboard template 未登记：{scene_id}")
            if dashboard.get("renderer_id") != pack.get("renderer_id"):
                raise ContractError(f"composition dashboard template renderer 不匹配：{scene_id}")
        tasks = pack.get("acceptance_tasks", [])
        if not isinstance(tasks, list) or len(tasks) < 6 or len(tasks) != len(set(tasks)):
            raise ContractError(f"composition acceptance task 不完整：{scene_id}")
        _validate_runtime_policies(pack, scene_id)
        _validate_tonight_seeds(pack, exact_modules)
        compile_acceptance_program(pack)
    return value


def _validate_tonight_seeds(pack: Mapping[str, Any], exact_modules: Sequence[str]) -> None:
    seeds = pack.get("tonight_seeds") or []
    if not seeds:
        return
    if not isinstance(seeds, list):
        raise ContractError(f"tonight_seeds 必须是列表：{pack.get('composition_id')}")
    seen: set[str] = set()
    allowed = set(exact_modules)
    for seed in seeds:
        seed_id = str((seed or {}).get("id") or "").strip()
        module_id = str((seed or {}).get("module_id") or "").strip()
        values = (seed or {}).get("values")
        if not seed_id or seed_id in seen:
            raise ContractError(f"tonight_seed id 无效或重复：{pack.get('composition_id')}")
        if module_id not in allowed:
            raise ContractError(f"tonight_seed 引用未选模块：{module_id}")
        if not isinstance(values, dict) or not values:
            raise ContractError(f"tonight_seed 缺少 values：{seed_id}")
        seen.add(seed_id)


def _scene_profiles() -> dict[str, dict[str, Any]]:
    rows = read_json(REFERENCES / SCENE_PROFILE_FILE).get("scene_profiles", [])
    return _unique_rows(rows, "scene_profile_id", "scene profiles")


def _domain_modules() -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    for pack in read_json(REFERENCES / DOMAIN_CONTENT_FILE).get("packs", []):
        for row in pack.get("modules", []):
            if isinstance(row, Mapping) and row.get("module_id"):
                modules[str(row["module_id"])] = dict(row)
    return modules


def _match_scene_template(scene: Mapping[str, Any], selected_module_ids: Sequence[str]) -> dict[str, Any] | None:
    system = read_json(REFERENCES / SCENE_TEMPLATE_FILE)
    domain = str(scene.get("domain_id") or "")
    profile_ids = {str(scene.get("scene_profile_id") or "").rsplit(".", 1)[-1]}
    profile_ids.update(str(value) for value in scene.get("legacy_profile_ids") or [])
    selected = {str(value) for value in selected_module_ids}
    profile_hits: list[dict[str, Any]] = []
    module_hits: list[dict[str, Any]] = []
    for row in system.get("scene_templates", []):
        if not isinstance(row, Mapping):
            continue
        if domain not in {str(value) for value in row.get("domain_ids", [])}:
            continue
        rule = row.get("match") if isinstance(row.get("match"), Mapping) else {}
        allowed = {str(value) for value in rule.get("profile_ids", [])}
        required = {str(value) for value in rule.get("required_module_ids", [])}
        if allowed:
            if allowed & profile_ids and (not required or required <= selected):
                profile_hits.append(dict(row))
            continue
        if required and required <= selected:
            module_hits.append(dict(row))
    if profile_hits:
        return profile_hits[0]
    if module_hits:
        return module_hits[0]
    return None


def derive_composition_pack(
    scene_profile_id: str,
    selected_module_ids: Sequence[str],
) -> dict[str, Any]:
    """按场景合同和已选模块派生组合包。成熟度只约束声明，不另开架构。"""
    scenes = _scene_profiles()
    scene = scenes.get(str(scene_profile_id))
    if scene is None:
        raise ContractError(f"未知 scene_profile：{scene_profile_id}")
    selected = [str(value) for value in selected_module_ids]
    if not 4 <= len(selected) <= 15 or len(selected) != len(set(selected)):
        raise ContractError(f"派生组合包的模块范围无效：{scene_profile_id}")
    catalog = _domain_modules()
    unknown = [module_id for module_id in selected if module_id not in catalog]
    if unknown:
        raise ContractError(f"派生组合包引用未知模块：{unknown}")
    template = _match_scene_template(scene, selected)
    renderer_id = str((template or {}).get("renderer_id") or "composition_dashboard")
    runtime_id = CHILD_PLAYGROUND_RUNTIME if renderer_id == "child_playground_v2" else OBJECT_PIPELINE_RUNTIME
    modules = []
    object_types = []
    for module_id in selected:
        row = catalog[module_id]
        object_type = f"{module_id.replace('-', '_')}_object"
        object_types.append(object_type)
        modules.append(
            {
                "module_id": module_id,
                "object_type_id": object_type,
                "primary_job": f"maintain_{module_id.replace('-', '_')}",
                "surface_template_id": GENERIC_SURFACE_TEMPLATE,
                "surface_signature": GENERIC_SURFACE_TEMPLATE,
                "default_disclosure": "summary",
                "title_fields": ["title"],
                "link_label": str(row.get("name") or module_id),
            }
        )
    relations = [
        {
            "from": object_types[index],
            "relation": "next",
            "to": object_types[index + 1],
        }
        for index in range(len(object_types) - 1)
    ]
    first, last = selected[0], selected[-1]
    maturity = str(scene.get("maturity") or "catalog_only")
    slug = str(scene_profile_id).replace("scene.", "").replace(".", "-")
    pack = {
        "composition_id": f"composition.derived.{slug}-v1",
        "scene_profile_id": scene_profile_id,
        "domain_id": scene.get("domain_id"),
        "pack_origin": "derived",
        "maturity": maturity,
        "scene_template_id": (template or {}).get("scene_template_id"),
        "renderer_id": renderer_id,
        "exact_module_ids": selected,
        "attention_model": {
            "regions": [
                {"region_id": "now", "label": "现在先做", "source_module_ids": [first], "max_visible_items": 3},
                {"region_id": "flow", "label": "工作链", "source_module_ids": selected, "max_visible_items": 8},
                {"region_id": "capture", "label": "先记下", "source_module_ids": [first], "max_visible_items": 1},
                {"region_id": "attention", "label": "需要处理", "source_module_ids": [last], "max_visible_items": 4},
            ],
            "home_rule": "打开就做今晚这一件",
        },
        "object_graph": {
            "object_types": object_types,
            "relations": relations,
        },
        "runtime_binding": {
            "runtime_id": runtime_id,
            "helper_slot": "derived_helpers",
            "render_slot": "derived_render",
            "listener_slot": "derived_listeners",
        },
        "modules": modules,
        "acceptance_tasks": [
            "reload_persistence",
            "import_preview_and_undo",
            "derived_selected_scope",
            "derived_object_chain",
            "derived_attention_model",
            "derived_maturity_boundary",
        ],
    }
    pack["execution_projection"] = {
        "projection_version": "double6_execution_projection_v1",
        "today_module_ids": [first],
        "lifecycle_module_ids": selected,
        "attention_module_ids": [last],
        "next_action_fields": ["next_action", "title"],
        "blocker_fields": ["blocker", "notes", "details"],
        "completion_events": ["record_completed", "starter_completed"],
        "home_projection": ["today", "lifecycle", "attention", "next_action"],
        "selected_scope_sha_input": selected,
    }
    return pack


def compile_composition(
    scene_profile_id: str,
    selected_module_ids: Sequence[str],
) -> dict[str, Any]:
    """每个场景都编译组合合同。已登记 pack 保持精确范围；其余按已选模块派生。"""
    registry = composition_registry()
    pack = next(
        (row for row in registry["packs"] if row["scene_profile_id"] == scene_profile_id),
        None,
    )
    selected = [str(value) for value in selected_module_ids]
    if pack is not None:
        expected = list(pack["exact_module_ids"])
        if selected != expected:
            raise ContractError(
                f"声明式场景包要求精确 selected scope：{scene_profile_id}; "
                f"expected={expected}; selected={selected}"
            )
        compiled_pack = deepcopy(pack)
    else:
        compiled_pack = derive_composition_pack(scene_profile_id, selected)
    registry_sha256 = digest_bytes(canonical(registry))
    payload = {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "kernel_version": KERNEL_VERSION,
        "registry_sha256": registry_sha256,
        "activation_status": "compiled",
        "selected_scope_only": True,
        "pack": compiled_pack,
    }
    payload["composition_sha256"] = digest_bytes(canonical(payload))
    return payload


def validate_compiled_composition(value: Any) -> dict[str, Any] | None:
    """验证产品中冻结的组合合同与当前注册表一致，失败时阻断而非降级猜测。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContractError("composition contract 必须是对象")
    scene_id = str(value.get("pack", {}).get("scene_profile_id") or "")
    modules = value.get("pack", {}).get("exact_module_ids", [])
    expected = compile_composition(scene_id, modules)
    if expected != value:
        raise ContractError("composition contract 与当前声明式注册表不一致")
    return deepcopy(value)


def module_contract(value: dict[str, Any] | None, module_id: str) -> dict[str, Any] | None:
    if value is None:
        return None
    validated = validate_compiled_composition(value)
    return next(
        (deepcopy(row) for row in validated["pack"]["modules"] if row["module_id"] == module_id),
        None,
    )
