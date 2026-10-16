#!/usr/bin/env python3
"""拦考公台：首页是行测/申论/面试三扇门，不是今晚一组通用题。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def check_exam_practice_sources() -> list[str]:
    helpers = (SKILL / "references" / "runtimes" / "exam-practice-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references" / "runtimes" / "exam-practice-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderers = (SKILL / "scripts" / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    packs = (SKILL / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    builder = (SKILL / "scripts" / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    starters = (SKILL / "references" / "scene-capability-starters.json").read_text(encoding="utf-8")
    exam_fn = renderers[renderers.find("def _exam_practice") : renderers.find("RENDERERS =")]
    start = starters.find('"scene_id": "04"')
    end = starters.find('"scene_id": "05"')
    exam_slice = starters[start:end] if start != -1 else ""
    errors: list[str] = []

    if "data-exam-practice-board" not in exam_fn:
        errors.append("缺少考公专用今日板（data-exam-practice-board）")
    if "data-exam-desk" not in exam_fn:
        errors.append("考公首页必须是三科台（data-exam-desk），不能再是今晚一组题")
    if "data-exam-door-xingce" not in exam_fn or "data-exam-door-shenlun" not in exam_fn or "data-exam-door-interview" not in exam_fn:
        errors.append("首页必须有行测、申论、面试三扇门")
    if "不是真题" not in exam_fn or "不保证上岸" not in exam_fn:
        errors.append("首页必须写明不是真题、不保证上岸")
    overlay_path = SKILL / "references" / "gongkao-civil-overlay.json"
    overlay = overlay_path.read_text(encoding="utf-8") if overlay_path.is_file() else ""
    if overlay_path.is_file():
        if overlay.count('"kind": "question"') < 80:
            errors.append("考公行测开箱层题量不够，连做会立刻见底")
        if overlay.count('"kind": "draft"') < 6:
            errors.append("考公申论开箱层必须有完整资料题")
        if overlay.count('"kind": "speak"') < 8:
            errors.append("考公面试开箱层必须够连抽")
        if "_apply_gongkao_civil_overlay" not in builder:
            errors.append("构建时必须把考公题库接到三科房间")
        if "examOpenRetry" not in helpers:
            errors.append("错题再做一次必须打开行测原题")
        if "关键词核对" not in helpers or "用词核对" not in helpers:
            errors.append("申论面试打判必须标明是关键词/用词核对，不能写成立意或采点过关")
        if "examPersistDraft" not in helpers:
            errors.append("申论面试必须按题保存草稿")
        if "examSourceLabel" not in helpers:
            errors.append("行测题卡必须显示来源题签")
        if "verdict.status==='invalid_answer'" not in listeners.replace(" ", ""):
            errors.append("空白打判不得写成已打判")
        if "data-exam-shenlun-now" not in builder or "data-exam-interview-now" not in builder:
            errors.append("申论和面试必须分开作答，不能堆在同一长页")
        if "不是官方分" not in exam_fn:
            errors.append("接上打判后必须写明不是官方分")
    elif "打判还没接上" not in exam_fn:
        errors.append("框架台必须写明打判还没接上")
    if "insert_today_workboard=False" not in exam_fn:
        errors.append("考公首页必须关掉通用今天待办板")
    if "data-today-workboard" not in exam_fn:
        errors.append("考公今晚板必须自己带今天入口标记")
    if "data-double6-primary-action='true'" not in exam_fn:
        errors.append("考公首页必须有一个主动作")
    if "去做行测" not in exam_fn:
        errors.append("首页主动作必须是去做行测，不能再是提交这一组题")
    if "data-exam-desk" in exam_fn and "行测、申论、面试" not in exam_fn:
        errors.append("三科台首页必须写出行测、申论、面试")
    if "exam-civil-desk" not in exam_fn or "exam-desk-sheet" not in exam_fn:
        errors.append("考公首页必须是纸面三科台，不能再是三颗同色按钮")
    if "exam-desk-xingce" not in exam_fn or "exam-desk-shenlun" not in exam_fn or "exam-desk-interview" not in exam_fn:
        errors.append("三扇门必须一眼分得出行测卷、申论稿纸、面试计时")
    if "考公工作台" not in exam_fn:
        errors.append("考公成品门牌必须是考公工作台")
    if "background:var(--d6-primary);color:#fff;font-weight:750" in builder:
        errors.append("考公门不能再编译成同色主按钮")
    if "grid-template-columns:1fr" not in builder or "minmax(190px,1fr)" not in builder:
        errors.append("考公三扇门窄屏必须竖排，不能挤成一排切掉面试")
    helpers_text = helpers
    if "打开就选一科" not in helpers_text:
        errors.append("三科台暖句不能再覆盖成先做完这一题")
    if 'CIVIL_NAV_ORDER = ["exam-practice", "exam-materials", "exam-today"' not in renderers:
        errors.append("考公侧栏必须按行测、申论、面试排列，错题不能插在三科中间")
    if "最接近下面哪个词" in exam_slice or "词义辨析" in exam_slice:
        errors.append("考公题不能是小学生近义词")
    starter_py = (SKILL / "scripts" / "double6_runtime" / "starter_content.py").read_text(encoding="utf-8")
    if 'starter_profile_id == "civil-service-exam"' not in starter_py:
        errors.append("考公题库必须滤掉四级题，不能把听力和阅读塞进行测")
    if exam_slice.count('"item_id": "exam-q0') > 6:
        errors.append("框架台默认行测题必须少，不能再堆一组无差别刷题")
    if '"kind": "speak"' not in exam_slice or "exam-interview-1" not in exam_slice:
        errors.append("必须有一道结构化面试开口练习")
    if '"speak"' not in starter_py or "ITEM_KINDS" not in starter_py:
        errors.append("开口练习 kind=speak 必须登记进 starter 合同")
    if '"kind": "draft"' not in exam_slice or '"key": "problem"' not in exam_slice:
        errors.append("申论必须能当场写问题、原因、对策")
    if "speakCard" not in builder or "kind==='speak'" not in builder.replace(" ", ""):
        errors.append("面试开口卡必须能渲染思考/作答计时和转写框")
    if "data-exam-import" not in exam_fn and "data-exam-import" not in helpers:
        errors.append("框架台必须留导入自己的题的入口")
    if "rights" not in listeners.lower() and "有权使用" not in listeners and "有权使用" not in exam_fn:
        errors.append("导入必须先声明有权使用")
    exam_nav = packs[packs.find('"composition_id": "composition.exam.civil-service-v1"') : packs.find('"composition_id": "composition.household.weekly-handoff-v1"')]
    for module_id, label in (
        ("exam-goal", "计划"),
        ("exam-today", "面试"),
        ("exam-practice", "行测"),
        ("exam-errors", "错题"),
        ("exam-materials", "申论"),
    ):
        if f'"{module_id}"' not in exam_nav:
            errors.append(f"考公必须保留{label}房间")
    if "打开就选行测" not in exam_nav and "行测、申论、面试" not in exam_nav:
        errors.append("pack 首页规则必须是打开就选行测、申论或面试")
    if '"link_label": "今晚的题"' in exam_nav:
        errors.append("行测房间标题不要再写成今晚的题")
    if "d6EarnStar" in helpers or "d6EarnStar" in listeners:
        errors.append("考公作答不得给星星")
    if "renderExamPractice" not in helpers:
        errors.append("没有 renderExamPractice")
    if "data-exam-submit" not in listeners:
        errors.append("行测房间仍要能提交选项")
    if "_tonight_evaluate_shell" not in exam_fn:
        errors.append("考公首页必须列出全部房间入口")
    if "走查工作台" in exam_fn or "声明式工作台" in exam_fn:
        errors.append("考公成品门牌不能写成走查或声明式工作台")
    return errors


def check_all() -> dict:
    errors = check_exam_practice_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查考公三科台")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print("check_exam_practice: ok")
        else:
            print(f"check_exam_practice: {result['failed']} failed")
            for error in result["errors"]:
                print(f"- {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
