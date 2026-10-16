#!/usr/bin/env python3
"""把本站考公题库编译成考公工作台开箱层。只给 civil-service 构建用。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SITE: Path | None = None
OUT = SKILL / "references" / "gongkao-civil-overlay.json"

TOPIC = {
    "political-theory": "常识",
    "general-knowledge": "常识",
    "verbal": "言语",
    "quantitative": "数量",
    "logic": "判断",
    "data-analysis": "资料",
}

KIND_LABEL = {
    "official_outline_example": "官方例题，不是原卷",
    "synthetic_gap": "非原卷",
    "user_import": "你导入的题",
}


def offline_text(value: object) -> str:
    """移除离线单文件不能携带的远端 Markdown 图片引用。"""
    if isinstance(value, dict):
        value = value.get("text") or value.get("content") or ""
    text = str(value or "")
    return re.sub(r"!\[[^\]]*\]\(https?://[^)]+\)", "[资料图未随离线包提供]", text)


def load(name: str) -> dict:
    return json.loads((SITE / name).read_text(encoding="utf-8"))


def xingce_items() -> list[dict]:
    rows = []
    for item in load("gongkaoXingceWebBank.json")["items"]:
        options = item.get("options") or {}
        option_list = [f"{letter}. {text}" for letter, text in options.items()]
        key = str(item.get("answer_key") or "").strip().upper()
        answer = next((row for row in option_list if row.startswith(f"{key}. ")), key)
        topic = TOPIC.get(str(item.get("module") or ""), "行测")
        passage = offline_text(item.get("passage")).strip()
        stem = offline_text(item.get("stem"))
        prompt = f"{passage}\n\n{stem}".strip() if passage else stem
        rows.append(
            {
                "kind": "question",
                "item_id": item["item_id"],
                "module_ids": ["exam-practice"],
                "title": topic,
                "prompt": prompt,
                "options": option_list,
                "answer": answer,
                "answer_key": key,
                "explanation": offline_text(item.get("official_rationale")),
                "knowledge_point": topic,
                "topic": topic,
                "difficulty": "练习",
                "source_label": KIND_LABEL.get(str(item.get("kind") or ""), "非原卷"),
                "item_type": item.get("item_type") or "single_choice",
                "judgeable": item.get("judgeable") or "mechanical_choice",
            }
        )
    return rows


def shenlun_items() -> list[dict]:
    rows = []
    for item in load("gongkaoShenlunWebBank.json")["items"]:
        rows.append(
            {
                "kind": "draft",
                "item_id": item["item_id"],
                "module_ids": ["exam-materials"],
                "title": item.get("paper_title") or "申论",
                "prompt": offline_text(item.get("prompt")),
                "body": "写完打立意、结构和采点。不是阅卷分数。",
                "result": "留下今晚这段申论",
                "materials": [offline_text(value) for value in item.get("materials") or []],
                "word_min": item.get("word_min"),
                "word_max": item.get("word_max"),
                "item_type": item.get("item_type") or "essay",
                "intended_theme": item.get("intended_theme") or [],
                "points": item.get("points") or [],
                "judgeable": item.get("judgeable") or "rubric",
                "source_label": KIND_LABEL.get(str(item.get("kind") or ""), "非原卷"),
                "sections": [{"key": "answer", "label": "作答", "placeholder": "对着资料写。打判不是官方分。"}],
            }
        )
    return rows


def interview_items() -> list[dict]:
    rows = []
    for item in load("gongkaoInterviewWebBank.json")["items"]:
        rows.append(
            {
                "kind": "speak",
                "item_id": item["item_id"],
                "module_ids": ["exam-today"],
                "title": "结构化面试",
                "prompt": offline_text(item.get("prompt")),
                "body": "先思考，再开口，把转写贴进来打内容。不是过线，也不是心理测评。",
                "result": "留下今晚这段开口转写",
                "think_seconds": int(item.get("think_seconds") or 60),
                "speak_seconds": int(item.get("speak_seconds") or 180),
                "intended_theme": item.get("intended_theme") or [],
                "points": item.get("points") or [],
                "judgeable": item.get("judgeable") or "rubric",
                "competency": item.get("competency") or "",
                "source_label": KIND_LABEL.get(str(item.get("kind") or ""), "非原卷"),
            }
        )
    return rows


def main() -> int:
    global SITE, OUT
    parser = argparse.ArgumentParser(description="把用户有权使用的本地考公数据编译成离线开箱内容")
    parser.add_argument('--site-data', type=Path, required=True, help='包含三份 gongkao*WebBank.json 的本地数据目录')
    parser.add_argument('--output', type=Path, default=OUT, help='输出 overlay JSON；默认覆盖本技能的题库文件')
    args = parser.parse_args()
    SITE, OUT = args.site_data, args.output
    overlay = {
        "schema": "gongkao-civil-overlay@1",
        "exam-practice": xingce_items(),
        "exam-materials": shenlun_items(),
        "exam-today": interview_items(),
        "summaries": {
            "exam-practice": f"行测 {len(xingce_items())} 道，当场看对错",
            "exam-materials": f"申论 {len(shenlun_items())} 道，写完打立意结构和采点",
            "exam-today": f"面试 {len(interview_items())} 道，计时后贴转写打内容",
        },
        "names": {
            "exam-practice": "行测",
            "exam-materials": "申论",
            "exam-today": "面试",
            "exam-errors": "错题",
            "exam-goal": "计划",
        },
    }
    OUT.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.name}: 行测 {len(overlay['exam-practice'])} 申论 {len(overlay['exam-materials'])} 面试 {len(overlay['exam-today'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
