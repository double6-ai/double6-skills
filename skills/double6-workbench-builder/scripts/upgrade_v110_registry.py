#!/usr/bin/env python3
"""Idempotently compile the v1.1.0 registries from current project sources."""

from __future__ import annotations

import json
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
REFS = SKILL / "references"


def load(name: str):
    return json.loads((REFS / name).read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def module(module_id: str, object_type: str, job: str, title_field: str, label: str, disclosure: str = "summary"):
    return {
        "module_id": module_id,
        "object_type_id": object_type,
        "primary_job": job,
        "surface_template_id": "generic-module-surface-v1",
        "surface_signature": "generic-module-surface-v1",
        "default_disclosure": disclosure,
        "title_fields": [title_field],
        "link_label": label,
    }


def execution_projection(pack: dict) -> dict:
    regions = {row["region_id"]: row for row in pack["attention_model"]["regions"]}
    exact = pack["exact_module_ids"]
    return {
        "projection_version": "double6_execution_projection_v1",
        "today_module_ids": list(regions["now"]["source_module_ids"]),
        "lifecycle_module_ids": list(regions["flow"]["source_module_ids"]),
        "attention_module_ids": list(regions["attention"]["source_module_ids"]),
        "next_action_fields": ["next_action", "title"],
        "blocker_fields": ["blocker", "notes", "details"],
        "completion_events": ["record_completed", "starter_completed"],
        "home_projection": ["today", "lifecycle", "attention", "next_action"],
        "selected_scope_sha_input": exact,
    }


def life_pack() -> dict:
    modules = [
        module("personal-today", "today_action", "complete_today_top_one", "title", "今日 Top 1", "open"),
        module("personal-habits", "habit_checkin", "check_one_habit", "title", "习惯打卡", "open"),
        module("life-inspiration", "inspiration_note", "capture_inspiration", "title", "灵感书房"),
        module("life-mood", "mood_fact", "log_mood_fact", "mood", "安静角", "open"),
        module("life-finance", "finance_fact", "log_finance_fact", "category", "财务柜"),
        module("life-food", "food_fact", "log_food_fact", "food", "餐厨"),
        module("life-movement", "movement_fact", "complete_movement", "title", "运动角"),
        module("life-reading", "reading_item", "maintain_reading", "title", "阅读室"),
        module("life-vocabulary", "vocabulary_fact", "review_vocabulary", "word", "词汇复习"),
    ]
    pack = {
        "composition_id": "composition.personal.life-dashboard-v1",
        "scene_profile_id": "scene.personal-execution.personal-life-dashboard",
        "domain_id": "personal-execution",
        "maturity": "executable_ready",
        "scene_template_id": "personal_life_dashboard",
        "renderer_id": "personal_life_dashboard",
        "exact_module_ids": [row["module_id"] for row in modules],
        "attention_model": {
            "regions": [
                {"region_id": "now", "label": "今天先完成", "source_module_ids": ["personal-today", "life-mood", "personal-habits"], "max_visible_items": 3},
                {"region_id": "flow", "label": "目标与生活事实", "source_module_ids": ["personal-today", "personal-habits", "life-finance", "life-food", "life-movement", "life-reading", "life-vocabulary"], "max_visible_items": 9},
                {"region_id": "capture", "label": "留下一条灵感", "source_module_ids": ["life-inspiration"], "max_visible_items": 1},
                {"region_id": "attention", "label": "需要关注的未完成", "source_module_ids": ["personal-today", "personal-habits", "life-movement"], "max_visible_items": 4},
            ],
            "home_rule": "今日一页先完成 Top 1、心情记录和一个习惯；九个模块全部保留逐模块导航",
        },
        "object_graph": {
            "object_types": [row["object_type_id"] for row in modules],
            "relations": [
                {"from": "today_action", "relation": "records_with", "to": "mood_fact"},
                {"from": "habit_checkin", "relation": "contributes_fact", "to": "movement_fact"},
                {"from": "inspiration_note", "relation": "may_become", "to": "today_action"},
                {"from": "finance_fact", "relation": "summarizes_locally", "to": "today_action"},
                {"from": "food_fact", "relation": "summarizes_locally", "to": "today_action"},
                {"from": "reading_item", "relation": "feeds", "to": "vocabulary_fact"},
            ],
        },
        "runtime_binding": {"runtime_id": "personal-life-runtime-v1", "helper_slot": "personal_life_helpers", "render_slot": "personal_life_render", "listener_slot": "personal_life_listeners"},
        "modules": modules,
        "acceptance_tasks": ["reload_persistence", "import_preview_and_undo", "life_today_page_visible", "life_complete_top_one", "life_log_mood", "life_check_habit", "life_deduped_streak", "adult_fact_projection_visible", "theme_switch_isolated"],
        "adult_fact_projection": {"engine_id": "adult_fact_projection", "optional_goal_days": 21, "reward_mode": "user_authored_local_celebration_only"},
        "theme_family_id": "life_rooms",
    }
    pack["execution_projection"] = execution_projection(pack)
    return pack


def cet4_pack() -> dict:
    modules = [
        module("exam-goal", "exam_goal", "set_exam_date", "title", "考试目标", "open"),
        module("exam-today", "exam_today_action", "complete_today_plan", "title", "今日任务", "open"),
        module("exam-practice", "exam_answer_fact", "answer_original_practice", "title", "自编练习", "open"),
        module("exam-errors", "exam_error_fact", "revisit_mistake", "title", "错题回炉", "open"),
        module("exam-materials", "exam_manual_draft", "draft_and_manual_review", "title", "写作与翻译"),
        module("exam-mock", "exam_mock_fact", "log_section_results", "metric", "套卷记录"),
        module("exam-pomodoro", "focus_session", "run_resumable_timer", "title", "专注计时", "open"),
        module("exam-review", "exam_review", "record_next_round", "date", "阶段复盘"),
    ]
    pack = {
        "composition_id": "composition.exam.cet4-sprint-v1",
        "scene_profile_id": "scene.exam-preparation.certification-study-cycle",
        "domain_id": "exam-preparation",
        "maturity": "executable_ready",
        "scene_template_id": "exam_civil_service_practice",
        "renderer_id": "exam_practice_dashboard",
        "exact_module_ids": [row["module_id"] for row in modules],
        "attention_model": {
            "regions": [
                {"region_id": "now", "label": "今天先练", "source_module_ids": ["exam-today", "exam-practice", "exam-pomodoro"], "max_visible_items": 3},
                {"region_id": "flow", "label": "目标到复盘", "source_module_ids": [row["module_id"] for row in modules], "max_visible_items": 8},
                {"region_id": "capture", "label": "记录一轮结果", "source_module_ids": ["exam-mock"], "max_visible_items": 1},
                {"region_id": "attention", "label": "需要回炉或人工复核", "source_module_ids": ["exam-errors", "exam-materials", "exam-review"], "max_visible_items": 6},
            ],
            "home_rule": "考试日期由用户录入；先做一题或开始一段专注，再处理错题和人工复核",
        },
        "object_graph": {
            "object_types": [row["object_type_id"] for row in modules],
            "relations": [
                {"from": "exam_goal", "relation": "plans", "to": "exam_today_action"},
                {"from": "exam_today_action", "relation": "starts", "to": "focus_session"},
                {"from": "exam_answer_fact", "relation": "creates_when_incorrect", "to": "exam_error_fact"},
                {"from": "exam_error_fact", "relation": "retains_original_fact_after", "to": "exam_review"},
                {"from": "exam_manual_draft", "relation": "requires_manual_review_before", "to": "exam_review"},
                {"from": "exam_mock_fact", "relation": "informs", "to": "exam_review"},
            ],
        },
        "runtime_binding": {"runtime_id": "cet4-sprint-runtime-v1", "helper_slot": "cet4_sprint_helpers", "render_slot": "cet4_sprint_render", "listener_slot": "cet4_sprint_listeners"},
        "modules": modules,
        "acceptance_tasks": ["reload_persistence", "import_preview_and_undo", "exam_practice_board_visible", "cet4_original_items", "cet4_error_reflow", "cet4_manual_review", "cet4_timer_resume", "cet4_source_boundary", "adult_fact_projection_visible", "theme_switch_isolated"],
        "source_contract_id": "double6-cet4-original-content/v1",
        "adult_fact_projection": {"engine_id": "adult_fact_projection", "daily_equal_division_only": True},
        "theme_family_id": "study_companion",
    }
    pack["execution_projection"] = execution_projection(pack)
    return pack


def main() -> None:
    compositions = load("workbench-composition-packs.json")
    compositions["contract_version"] = "double6_declarative_composition_v2"
    compositions["kernel_version"] = "1.1.0"
    packs = [row for row in compositions["packs"] if row["scene_profile_id"] not in {"scene.personal-execution.personal-life-dashboard", "scene.exam-preparation.certification-study-cycle"}]
    for pack in packs:
        pack["execution_projection"] = execution_projection(pack)
    packs.extend([life_pack(), cet4_pack()])
    compositions["packs"] = packs
    save(REFS / "workbench-composition-packs.json", compositions)

    scenes = load("scene-profiles.json")
    by_id = {row["scene_profile_id"]: row for row in scenes["scene_profiles"]}
    life = by_id["scene.personal-execution.personal-life-dashboard"]
    life["maturity"] = "executable_ready"
    life["recommended_module_ids"] = life_pack()["exact_module_ids"]
    life["goal"] = "在今日一页完成 Top 1、心情和一个习惯，并保留九个生活模块的逐模块入口"
    life["machine_checkable_acceptance"] = ["exact_nine_module_composition", "today_page_three_real_actions", "deduped_completion_date_streak", "local_fact_only_aggregates", "theme_preference_isolated"]
    exam = by_id["scene.exam-preparation.certification-study-cycle"]
    exam["maturity"] = "executable_ready"
    exam["legacy_profile_ids"] = ["cet4-sprint"]
    exam["label"] = "四级冲刺工作台"
    exam["user"] = "准备大学英语四级、希望把日期、练习、错题、套卷与专注时段放在一个本地入口的学习者"
    exam["goal"] = "用自编练习、保留原错题事实的回炉队列和可恢复计时推进四级备考"
    exam["recommended_module_ids"] = cet4_pack()["exact_module_ids"]
    exam["boundaries"]["out_of_scope"] = ["复制或冒充真题", "自动评分写作与翻译", "保证通过", "自动报名或缴费"]
    exam["boundaries"]["data_rule"] = "官方考试结构记录来源与核验日期；全部练习自编，写作与翻译只保存人工复核状态"
    exam["machine_checkable_acceptance"] = ["exact_eight_module_composition", "eighteen_original_auto_graded_items", "six_manual_review_items", "mistake_fact_retained", "timestamp_timer_resume", "official_structure_sources_only", "no_pass_guarantee_claim"]
    counts = {key: 0 for key in ("catalog_only", "contract_ready", "executable_ready", "release_ready")}
    for row in scenes["scene_profiles"]:
        counts[row["maturity"]] += 1
    scenes["maturity_summary"] = counts
    save(REFS / "scene-profiles.json", scenes)

    graph = load("capability-graph.json")
    graph_paths = {row["scene_profile_id"]: row for row in graph["scene_paths"]}
    graph_paths["scene.personal-execution.personal-life-dashboard"]["recommended_module_ids"] = life_pack()["exact_module_ids"]
    graph_paths["scene.exam-preparation.certification-study-cycle"]["recommended_module_ids"] = cet4_pack()["exact_module_ids"]
    graph.setdefault("audit", {})["recommended_scene_module_path_count"] = sum(len(row["recommended_module_ids"]) for row in graph["scene_paths"])
    graph["audit"]["audited_at"] = "2026-08-31"
    save(REFS / "capability-graph.json", graph)

    domains = load("domain-content-packs.json")
    personal = next(row for row in domains["packs"] if row["pack_id"] == "personal-execution-base")
    personal_profile = next(row for row in personal["profiles"] if row["profile_id"] == "personal-life-dashboard")
    personal_profile["core_module_ids"] = life_pack()["exact_module_ids"]
    exam_domain = next(row for row in domains["packs"] if row["pack_id"] == "exam-preparation-base")
    exam_domain["profiles"] = [row for row in exam_domain["profiles"] if row["profile_id"] != "cet4-sprint"]
    exam_domain["profiles"].append({"profile_id": "cet4-sprint", "label": "四级冲刺工作台", "description": "面向大学英语四级的倒计时、自编练习、错题、人工复核和专注计时。", "triggers": ["四级", "CET4", "CET-4", "大学英语四级", "四级冲刺"], "core_module_ids": cet4_pack()["exact_module_ids"]})
    save(REFS / "domain-content-packs.json", domains)

    clarification = load("clarification-policies.json")
    exam_policy = next(row for row in clarification["domains"] if row["domain_id"] == "exam-preparation")
    exam_policy.setdefault("profile_overrides", {})["cet4-sprint"] = {"ask_goal_when": "outcome_ambiguous"}
    save(REFS / "clarification-policies.json", clarification)

    starter = load("scene-capability-starters.json")
    scene04 = next(row for row in starter["scenes"] if row["scene_id"] == "04")
    content = load("cet4-original-content.json")
    for item in content["auto_graded_items"]:
        item.setdefault("difficulty", "四级基础")
    for item in content["manual_review_items"]:
        item.setdefault("result", "保存草稿后由本人或老师人工复核；页面不自动评分")
    save(REFS / "cet4-original-content.json", content)
    for capability in scene04["capabilities"]:
        capability["starter_items"] = [row for row in capability.get("starter_items", []) if not str(row.get("item_id", "")).startswith("cet4-")]
    cap02 = next(row for row in scene04["capabilities"] if row["capability_id"] == "CAP-04-02")
    cap03 = next(row for row in scene04["capabilities"] if row["capability_id"] == "CAP-04-03")
    cap04 = next(row for row in scene04["capabilities"] if row["capability_id"] == "CAP-04-04")
    cap02["starter_items"].extend(content["auto_graded_items"])
    cap03["starter_items"].append({
        "item_id": "cet4-error-queue",
        "kind": "action",
        "module_ids": ["exam-errors"],
        "title": "从原错题事实开始回炉",
        "body": "答错后题目自动进入这里；重做正确也保留第一次答错的事实。",
        "result": "打开一条待回炉错题并保留原始作答记录",
    })
    cap04["starter_items"].extend(content["manual_review_items"])
    save(REFS / "scene-capability-starters.json", starter)

    incentives = load("incentive-library.json")
    incentives["engines"] = [row for row in incentives["engines"] if row["engine_id"] != "adult_fact_projection"]
    incentives["engines"].append({"engine_id": "adult_fact_projection", "label": "成人事实投影", "audience": ["adult"], "polarity": "neutral", "state": ["deduped_completion_dates", "goal", "local_ledger"], "inputs": ["completion_date", "user_goal", "local_ledger_record"], "forbidden": ["projection_equals_mastery", "health_conclusion", "exam_ability_claim", "business_outcome_claim", "automatic_reward_fulfillment"]})
    incentives["systems"] = [row for row in incentives["systems"] if row["system_id"] not in {"life-21-day-facts", "cet4-sprint-facts"}]
    incentives["systems"].extend([
        {"system_id": "life-21-day-facts", "engine_id": "adult_fact_projection", "label": "可选 21 天目标与本地里程碑", "status": "assembled", "audience": "adult", "default_on": False, "sources": ["01_research/2026-08-30_workbuddy-official-showcases/cross_case_synthesis.md"]},
        {"system_id": "cet4-sprint-facts", "engine_id": "adult_fact_projection", "label": "四级目标等分与练习事实", "status": "assembled", "audience": "adult", "default_on": True, "sources": ["references/cet4-original-content.json"]},
    ])
    save(REFS / "incentive-library.json", incentives)

    manifest_path = SKILL / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "1.1.0"
    manifest["status"] = "source_candidate"
    manifest["schemas"].update({"product": 9, "design": 7, "build": 8, "candidate_lock": 10})
    manifest["references"].update({"adult_theme_system": "references/adult-theme-system.json", "adult_fact_projection": "scripts/double6_runtime/adult_fact_projection.py", "cet4_original_content": "references/cet4-original-content.json"})
    manifest["release_validation"]["active_test"] = "workflows/double6-workbench-governance/tests/test_v110_execution_themes.py"
    manifest["release_validation"]["time_budget_seconds"] = 180
    save(manifest_path, manifest)

    for name, field in (("personal-platform-bridge.json", "version"), ("workbench-surface-templates.json", "kernel_version"), ("workbench-dashboard-templates.json", "kernel_version"), ("reliability-contracts.json", "skill_version")):
        value = load(name)
        value[field] = "1.1.0"
        save(REFS / name, value)


if __name__ == "__main__":
    main()
