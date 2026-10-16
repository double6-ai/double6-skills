#!/usr/bin/env python3
"""审查所有场景的题目低级错误，不限于儿童题。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from double6_runtime.content_mines import (  # noqa: E402
    audit_all_workbench_questions,
    check_auto_hero_follows_story,
    check_hero_source_skips_answer,
    check_next_is_one_button,
    check_option_letters_fit_card,
    check_practice_keeps_story,
    check_serve_path_shuffles,
    check_stage_copy_is_group_play,
    check_visible_copy_avoids_licensed_ultraman,
    check_calculator_input_labels,
    check_exam_questions_match_civil_service,
    check_exam_room_starters_are_bound,
    check_finance_room_starters_are_bound,
    check_module_work_not_buried,
    check_selected_nav_keeps_rooms,
    check_visible_copy_avoids_builder_speak,
    check_starter_actions_not_sticky,
    load_question_catalog,
)


def check_all() -> dict:
    starter_source = (SKILL / "scripts" / "double6_runtime" / "starter_content.py").read_text(encoding="utf-8")
    child_source = (SKILL / "scripts" / "double6_runtime" / "child_playground.py").read_text(encoding="utf-8")
    errors: list[str] = []
    errors.extend(check_serve_path_shuffles(starter_source))
    errors.extend(audit_all_workbench_questions())
    errors.extend(check_auto_hero_follows_story())
    errors.extend(check_next_is_one_button(child_source))
    errors.extend(check_practice_keeps_story(child_source))
    errors.extend(check_hero_source_skips_answer(child_source))
    errors.extend(check_option_letters_fit_card(child_source))
    errors.extend(check_stage_copy_is_group_play(child_source))
    library_text = (SKILL / "references" / "incentive-library.json").read_text(encoding="utf-8")
    theme_text = (SKILL / "references" / "child-visual-theme.json").read_text(encoding="utf-8")
    errors.extend(check_visible_copy_avoids_licensed_ultraman(library_text))
    errors.extend(check_visible_copy_avoids_licensed_ultraman(child_source))
    errors.extend(check_calculator_input_labels())
    errors.extend(check_exam_questions_match_civil_service())
    errors.extend(check_exam_room_starters_are_bound())
    errors.extend(check_finance_room_starters_are_bound())
    builder_source = (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    errors.extend(check_module_work_not_buried(builder_source))
    errors.extend(check_starter_actions_not_sticky(builder_source))
    errors.extend(check_selected_nav_keeps_rooms())
    errors.extend(check_visible_copy_avoids_builder_speak(builder_source))
    errors.extend(check_visible_copy_avoids_builder_speak(starter_source))
    from check_fitness_tonight import check_fitness_tonight_sources
    from check_teacher_class import check_teacher_class_sources
    from check_exam_practice import check_exam_practice_sources
    from check_content_tonight import check_content_tonight_sources
    from check_sales_tonight import check_sales_tonight_sources
    from check_household_tonight import check_household_tonight_sources
    from check_finance_tonight import check_finance_tonight_sources
    from check_commerce_tonight import check_commerce_tonight_sources
    from check_research_tonight import check_research_tonight_sources
    from check_domain_remnants import check_domain_remnant_sources

    errors.extend(check_fitness_tonight_sources())
    errors.extend(check_teacher_class_sources())
    errors.extend(check_exam_practice_sources())
    errors.extend(check_content_tonight_sources())
    errors.extend(check_sales_tonight_sources())
    errors.extend(check_household_tonight_sources())
    errors.extend(check_finance_tonight_sources())
    errors.extend(check_commerce_tonight_sources())
    errors.extend(check_research_tonight_sources())
    errors.extend(check_domain_remnant_sources())
    # 主题合同可以解释「不是授权奥特曼」，但不能当产品可见文案。
    if '"label":' in theme_text and "奥特曼" in theme_text.split('"notes"')[0]:
        errors.extend(check_visible_copy_avoids_licensed_ultraman(theme_text))
    catalog = load_question_catalog()
    scenes = sorted({str(row.get("_scene_id") or "") for row in catalog})
    return {
        "ok": not errors,
        "question_count": len(catalog),
        "scenes": scenes,
        "failed": len(errors),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审查所有场景题目里已经炸过的低级错误")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"已审查 {result['question_count']} 道题，覆盖 {len(result['scenes'])} 个场景，失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("各场景题目当前没有已登记类型的低级错误。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
