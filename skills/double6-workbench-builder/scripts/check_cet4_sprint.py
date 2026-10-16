#!/usr/bin/env python3
"""四级冲刺 1.1.0 专项门。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]


def check_all() -> dict:
    content = json.loads((SKILL / "references/cet4-original-content.json").read_text(encoding="utf-8"))
    packs = json.loads((SKILL / "references/workbench-composition-packs.json").read_text(encoding="utf-8"))["packs"]
    pack = next(row for row in packs if row["scene_profile_id"] == "scene.exam-preparation.certification-study-cycle")
    helpers = (SKILL / "references/runtimes/cet4-sprint-runtime-v1.helpers.js").read_text(encoding="utf-8")
    listeners = (SKILL / "references/runtimes/cet4-sprint-runtime-v1.listeners.js").read_text(encoding="utf-8")
    renderer = (SKILL / "scripts/double6_runtime/scene_renderers.py").read_text(encoding="utf-8")
    items = content["auto_graded_items"]
    manual = content["manual_review_items"]
    errors = []
    if len(items) != 18 or Counter(row["topic"] for row in items) != Counter({"听辨": 6, "阅读": 6, "词汇": 6}):
        errors.append("自编可判分题必须是 18 道：听辨 6、阅读 6、词汇 6")
    if len(manual) != 6 or Counter(row["topic"] for row in manual) != Counter({"写作": 3, "翻译": 3}):
        errors.append("人工复核题必须是 6 道：写作 3、翻译 3")
    prompts = [str(row["prompt"]).strip().casefold() for row in items]
    if len(prompts) != len(set(prompts)):
        errors.append("四级题目存在重复 prompt")
    for row in items:
        if str(row["answer"]).casefold() in str(row["title"]).casefold():
            errors.append(f"标题泄题：{row['item_id']}")
    option_positions = []
    for row in items:
        if row.get("options"):
            option_positions.append(row["options"].index(row["answer"]))
    if len(set(option_positions)) < 4:
        errors.append("答案位置没有覆盖四个选项位")
    base_helpers = (SKILL / "references/runtimes/exam-practice-runtime-v1.helpers.js").read_text(encoding="utf-8")
    if "retains-original-mistake-fact" not in listeners or "data-exam-retry" not in base_helpers:
        errors.append("错题回炉必须保留原错误事实")
    for marker in ("startedAt", "pausedRemainingMs", "data-cet4-timer"):
        if marker not in helpers + listeners + renderer:
            errors.append(f"计时恢复合同缺少 {marker}")
    if "需人工复核" not in renderer or "data-cet4-manual-review" not in renderer:
        errors.append("写作翻译必须显式人工复核")
    sources = content["source_contract"]["sources"]
    if {row["publisher"] for row in sources} != {"教育部教育考试院"} or len(sources) != 2:
        errors.append("来源合同只能采用两条教育部教育考试院来源")
    if "非真题" not in renderer or "非通过保证" not in renderer:
        errors.append("必须展示非真题、非通过保证")
    return {"ok": not errors, "errors": errors, "auto_graded": len(items), "manual_review": len(manual), "module_count": len(pack["exact_module_ids"])}


if __name__ == "__main__":
    result = check_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
