"""场景能力 starter 合同加载、模块映射与内容硬门。"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .core import ContractError, REFERENCES, read_json


CAPABILITY_ID = re.compile(r"CAP-(?:0[0-9]|1[0-5])-[0-9]{2}")
ITEM_KINDS = {"action", "template", "question", "calculator", "reference", "prompt", "generator"}
GENERATOR_TYPES = {"mental_arithmetic"}
GENERATOR_STAGES = {
    "baby-growth-explorer", "primary-transition-1-to-2",
    "primary-transition-2-to-3", "primary-transition-3-to-4", "generic",
}
QUESTION_DOMAINS = {"education-learning", "exam-preparation"}
QUESTION_SEMANTIC_MARKERS = ("出题", "练习", "测验", "问答", "面试", "作答", "答题", "错题")
EDUCATION_PRACTICE_MODULES = {
    "education-language",
    "education-math",
    "education-english",
    "education-reading",
    "education-explore",
}
EDUCATION_REFERENCE_MODULES = {
    "education-language",
    "education-math",
    "education-english",
    "education-reading",
}
REFERENCE_STYLES = {"chips", "poems"}
# 参考内容包可见文本不得携带内部标识符；构建产物另有静态与浏览器双层扫描兜底。
_INTERNAL_ID_RE = re.compile(r"CAP-\d{2}-\d{2}|baby-growth-explorer|generic-primary-transition|primary-transition-\d+-to-\d+")


_QUEST_THEME = {
    "education-language": ("语言魔法任务", "收集一枚语言发现徽章"),
    "education-math": ("数学闯关任务", "点亮一格数字能量"),
    "education-english": ("英语游乐任务", "学会一句可以开口说的话"),
    "education-reading": ("故事剧场任务", "找到故事里最重要的一条线索"),
    "education-explore": ("科学实验室任务", "先猜一猜，再用证据选答案"),
    "education-errors": ("错题修理任务", "把原来的办法换成更好用的办法"),
}

# 孩子可见文案只允许出现友好学段名；内部 stage_id 永远不得进入用户可见文本。
_STAGE_VISIBLE_LABELS = {
    "baby-growth-explorer": "宝宝成长",
    "primary-transition-1-to-2": "一升二",
    "primary-transition-2-to-3": "二升三",
    "primary-transition-3-to-4": "三升四",
}


def _enrich_stage_question(stage_id: str, module_id: str, item: dict[str, Any], position: int) -> dict[str, Any]:
    """为所有学段题补足一致的任务叙事，旧题库也不再以题号裸露给孩子。"""
    enriched = dict(item)
    title, default_mission = _QUEST_THEME.get(module_id, ("今日小挑战", "完成这一张挑战卡"))
    stage_label = _STAGE_VISIBLE_LABELS.get(stage_id, "")
    prefix = f"这是{stage_label}的第 {position + 1} 张挑战卡" if stage_label else f"这是第 {position + 1} 张挑战卡"
    enriched.setdefault("activity_label", title)
    enriched.setdefault("mission", default_mission)
    enriched.setdefault("story", f"{prefix}，先自己想一想，再查看解析。")
    if module_id == "education-english":
        enriched.setdefault("audio_text", str(enriched.get("prompt") or ""))
    return enriched


@lru_cache(maxsize=1)
def education_stage_overrides() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """加载按已选学段替换的儿童练习题，避免把高年级题静默带入低年级场景。"""
    value = read_json(REFERENCES / "education-stage-starters.json")
    if value.get("schema_version") != 1 or value.get("contract_version") != "education_stage_override_v1":
        raise ContractError("education-stage-starters schema/contract 版本无效")
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for stage in value.get("stages", []):
        if not isinstance(stage, dict) or not str(stage.get("stage_id") or "").strip() or not isinstance(stage.get("modules"), dict):
            raise ContractError("学段题库缺少 stage_id 或 modules")
        stage_id = str(stage["stage_id"])
        if stage_id in result:
            raise ContractError(f"学段题库 stage_id 重复：{stage_id}")
        modules: dict[str, list[dict[str, Any]]] = {}
        for module_id, items in stage["modules"].items():
            if module_id not in EDUCATION_PRACTICE_MODULES | {"education-errors"} or not isinstance(items, list) or not items:
                raise ContractError(f"学段题库模块无效：{stage_id}/{module_id}")
            if any(not isinstance(item, dict) or item.get("kind") != "question" for item in items):
                raise ContractError(f"学段题库只能覆盖真实题目：{stage_id}/{module_id}")
            if module_id in EDUCATION_PRACTICE_MODULES:
                if len(items) != 8:
                    raise ContractError(f"学段练习题必须恰好为 8 道：{stage_id}/{module_id}")
                if len({str(item.get("knowledge_point") or "").strip() for item in items} - {""}) < 6:
                    raise ContractError(f"学段练习题必须覆盖至少 6 个知识点：{stage_id}/{module_id}")
            for item in items:
                required = ["item_id", "title", "prompt", "answer", "explanation", "knowledge_point", "difficulty", "source_label"]
                if any(not str(item.get(key) or "").strip() for key in required):
                    raise ContractError(f"学段题目字段不完整：{stage_id}/{module_id}")
                if not item.get("options") and item.get("input_type") not in {"text", "number"}:
                    raise ContractError(f"学段题目缺可作答控件：{stage_id}/{module_id}/{item.get('item_id')}")
                if "演示" in str(item.get("source_label") or ""):
                    raise ContractError(f"学段题目不得标为演示：{stage_id}/{module_id}/{item.get('item_id')}")
            modules[str(module_id)] = [
                _enrich_stage_question(stage_id, str(module_id), item, position)
                for position, item in enumerate(items)
            ]
        if not EDUCATION_PRACTICE_MODULES <= set(modules):
            raise ContractError(f"学段题库必须覆盖五类儿童练习：{stage_id}")
        result[stage_id] = modules
    return result


@lru_cache(maxsize=1)
def education_stage_references() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """加载按已选学段挂载的结构化参考内容包（拼音、写字表、词库、古诗、数表）。

    参考内容不是题目，不参与对错判定；它与学段题库一样来自源文件，不经过宿主提交。
    """
    value = read_json(REFERENCES / "education-stage-references.json")
    if value.get("schema_version") != 1 or value.get("contract_version") != "education_stage_reference_v1":
        raise ContractError("education-stage-references schema/contract 版本无效")
    expected_stages = set(education_stage_overrides())
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for stage in value.get("stages", []):
        if not isinstance(stage, dict) or not str(stage.get("stage_id") or "").strip() or not isinstance(stage.get("modules"), dict):
            raise ContractError("学段参考内容包缺少 stage_id 或 modules")
        stage_id = str(stage["stage_id"])
        if stage_id in result:
            raise ContractError(f"学段参考内容包 stage_id 重复：{stage_id}")
        modules: dict[str, list[dict[str, Any]]] = {}
        for module_id, items in stage["modules"].items():
            if module_id not in EDUCATION_REFERENCE_MODULES or not isinstance(items, list) or not items:
                raise ContractError(f"学段参考内容包模块无效：{stage_id}/{module_id}")
            for item in items:
                if not isinstance(item, dict) or item.get("kind") != "reference":
                    raise ContractError(f"学段参考内容包只能包含 reference 条目：{stage_id}/{module_id}")
                required = ["item_id", "title", "body", "result", "source_label"]
                if any(not str(item.get(key) or "").strip() for key in required):
                    raise ContractError(f"学段参考条目字段不完整：{stage_id}/{module_id}")
                if any(_INTERNAL_ID_RE.search(str(item.get(key) or "")) for key in required):
                    raise ContractError(f"学段参考条目可见文本携带内部标识符：{item.get('item_id')}")
                payload = item.get("reference")
                if not isinstance(payload, dict) or payload.get("style") not in REFERENCE_STYLES:
                    raise ContractError(f"学段参考条目缺少结构化载荷：{item.get('item_id')}")
                if payload["style"] == "chips":
                    groups = payload.get("groups")
                    if not isinstance(groups, list) or not groups:
                        raise ContractError(f"chips 参考条目必须有分组：{item.get('item_id')}")
                    for group in groups:
                        entries = group.get("entries") if isinstance(group, dict) else None
                        if not str(group.get("label") or "").strip() or not isinstance(entries, list) or not entries:
                            raise ContractError(f"chips 分组缺标签或条目：{item.get('item_id')}")
                        if any(not isinstance(entry, dict) or not str(entry.get("text") or "").strip() for entry in entries):
                            raise ContractError(f"chips 条目缺展示文本：{item.get('item_id')}")
                        if any(_INTERNAL_ID_RE.search(str(entry.get(key) or "")) for entry in entries for key in ("text", "note", "speak")):
                            raise ContractError(f"chips 条目携带内部标识符：{item.get('item_id')}")
                else:
                    poems = payload.get("poems")
                    if not isinstance(poems, list) or len(poems) < 5:
                        raise ContractError(f"古诗参考条目至少需要 5 首：{item.get('item_id')}")
                    for poem in poems:
                        lines = poem.get("lines") if isinstance(poem, dict) else None
                        if (
                            not str(poem.get("title") or "").strip()
                            or not str(poem.get("author") or "").strip()
                            or not isinstance(lines, list)
                            or not all(str(line).strip() for line in lines)
                            or not lines
                            or not str(poem.get("translation") or "").strip()
                        ):
                            raise ContractError(f"古诗条目必须有题名、作者、诗句与译文：{item.get('item_id')}")
                        visible = [poem.get("title"), poem.get("author"), poem.get("notes"), poem.get("translation"), *lines]
                        if any(_INTERNAL_ID_RE.search(str(row or "")) for row in visible):
                            raise ContractError(f"古诗条目携带内部标识符：{item.get('item_id')}")
            modules[str(module_id)] = [dict(item) for item in items]
        if not EDUCATION_REFERENCE_MODULES <= set(modules):
            raise ContractError(f"学段参考内容包必须覆盖语文、英语、阅读与数学：{stage_id}")
        result[stage_id] = modules
    if set(result) != expected_stages:
        raise ContractError(f"学段参考内容包必须覆盖学段题库全部学段：{sorted(expected_stages)}")
    return result


@lru_cache(maxsize=1)
def starter_catalog() -> dict[str, Any]:
    value = read_json(REFERENCES / "scene-capability-starters.json")
    if value.get("schema_version") != 1 or value.get("contract_version") != "mobile_scene_capability_v1":
        raise ContractError("scene-capability-starters schema/contract 版本无效")
    scenes = value.get("scenes", [])
    if not isinstance(scenes, list) or {row.get("scene_id") for row in scenes if isinstance(row, dict)} != {f"{index:02d}" for index in range(16)}:
        raise ContractError("scene-capability-starters 必须覆盖 Scene 00–15")
    capability_ids: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("capabilities"), list) or not scene["capabilities"]:
            raise ContractError(f"场景 starter 合同为空：{scene.get('scene_id') if isinstance(scene, dict) else scene}")
        for capability in scene["capabilities"]:
            capability_id = str(capability.get("capability_id") or "")
            if not CAPABILITY_ID.fullmatch(capability_id) or capability_id in capability_ids:
                raise ContractError(f"starter capability_id 无效或重复：{capability_id}")
            capability_ids.add(capability_id)
            if not all(str(capability.get(key) or "").strip() for key in ["title", "primary_action", "result_contract", "mobile_contract", "source_boundary"]):
                raise ContractError(f"starter capability 合同字段不完整：{capability_id}")
            items = capability.get("starter_items", [])
            if not isinstance(items, list):
                raise ContractError(f"starter_items 必须是列表：{capability_id}")
            if any(marker in str(capability.get("title") or "") for marker in QUESTION_SEMANTIC_MARKERS) and not any(
                isinstance(item, dict) and item.get("kind") == "question" for item in items
            ):
                raise ContractError(f"具备出题/问答语义的能力必须提供真实可作答题：{capability_id}")
            for item in items:
                if not isinstance(item, dict) or item.get("kind") not in ITEM_KINDS or not str(item.get("item_id") or "").strip() or not str(item.get("title") or "").strip():
                    raise ContractError(f"starter item 无效：{capability_id}")
                if item["kind"] == "question":
                    required = ["prompt", "answer", "explanation", "knowledge_point", "difficulty", "source_label"]
                    if any(not str(item.get(key) or "").strip() for key in required):
                        raise ContractError(f"题目缺答案、解析、知识点、难度或来源：{item.get('item_id')}")
                    if not item.get("options") and item.get("input_type") not in {"text", "number"}:
                        raise ContractError(f"题目缺可作答控件：{item.get('item_id')}")
                elif not str(item.get("result") or "").strip():
                    raise ContractError(f"非题目 starter 必须声明动作结果：{item.get('item_id')}")
                if item["kind"] == "generator":
                    spec = item.get("generator")
                    ranges = spec.get("stage_ranges", {}) if isinstance(spec, dict) else {}
                    if not isinstance(spec, dict) or spec.get("type") not in GENERATOR_TYPES or not isinstance(ranges, dict) or set(ranges) != GENERATOR_STAGES:
                        raise ContractError(f"生成器 starter 必须登记类型与全部学段参数：{item['item_id']}")
                    for stage_key, params in ranges.items():
                        if (
                            not isinstance(params, dict)
                            or not isinstance(params.get("add_max"), int) or params["add_max"] < 5
                            or not isinstance(params.get("sub_max"), int) or params["sub_max"] < 5
                            or not isinstance(params.get("mul_max"), int) or not 0 <= params["mul_max"] <= 19
                            or not isinstance(params.get("div"), bool)
                        ):
                            raise ContractError(f"生成器学段参数无效：{item['item_id']}/{stage_key}")
                if item["kind"] == "prompt" and (not isinstance(item.get("prompts"), list) or len(item["prompts"]) < 2):
                    raise ContractError(f"灵感 starter 必须至少提供两条可切换提示：{item.get('item_id')}")
    by_domain: dict[str, int] = {domain: 0 for domain in QUESTION_DOMAINS}
    for scene in scenes:
        domains = set(scene.get("domain_ids", []))
        count = sum(
            1 for capability in scene["capabilities"]
            for item in capability.get("starter_items", []) if item.get("kind") == "question"
        )
        for domain in domains & QUESTION_DOMAINS:
            by_domain[domain] += count
    if any(count < 12 for count in by_domain.values()):
        raise ContractError(f"教育与备考 starter 各自至少需要 12 道真实可作答题：{by_domain}")
    education_scene = next((scene for scene in scenes if scene.get("scene_id") == "02"), None)
    if not education_scene:
        raise ContractError("儿童学习 starter 缺少 Scene 02")
    question_items = [
        item
        for capability in education_scene["capabilities"]
        for item in capability.get("starter_items", [])
        if item.get("kind") == "question"
    ]
    for module_id in EDUCATION_PRACTICE_MODULES:
        module_questions = [item for item in question_items if module_id in item.get("module_ids", [])]
        if not 6 <= len(module_questions) <= 10:
            raise ContractError(f"儿童学习每个练习模块必须有 6–10 道可作答题：{module_id}={len(module_questions)}")
        knowledge_points = {str(item.get("knowledge_point") or "").strip() for item in module_questions}
        if len(knowledge_points - {""}) < 6:
            raise ContractError(f"儿童学习题库必须覆盖至少 6 个知识点：{module_id}")
        if any("演示" in str(item.get("source_label") or "") for item in module_questions):
            raise ContractError(f"儿童学习正式题库不得使用演示题来源标签：{module_id}")
    education_stage_overrides()
    education_stage_references()
    return value


def capability_index() -> dict[str, dict[str, Any]]:
    return {
        capability["capability_id"]: capability
        for scene in starter_catalog()["scenes"]
        for capability in scene["capabilities"]
    }


def _resolve_generator(item: dict[str, Any], learning_stage_id: str | None) -> dict[str, Any]:
    """构建期把生成器的学段参数表解析成当前学段的单一参数集，不把参数表原样发到页面。"""
    if item.get("kind") != "generator":
        return item
    spec = item.get("generator") or {}
    ranges = spec.get("stage_ranges") or {}
    params = ranges.get(str(learning_stage_id or "")) or ranges.get("generic")
    if not isinstance(params, dict):
        raise ContractError(f"生成器缺少可用学段参数：{item.get('item_id')} / {learning_stage_id}")
    resolved = dict(item)
    resolved["generator"] = {"type": spec.get("type"), "params": dict(params)}
    return resolved


def starter_for_module(module: dict[str, Any], *, learning_stage_id: str | None = None) -> dict[str, Any]:
    module_id = str(module.get("module_id") or "")
    refs = [str(ref) for ref in module.get("evidence_refs", [])]
    index = capability_index()
    contracts = []
    items = []
    seen_items: set[str] = set()
    for ref in refs:
        capability = index.get(ref)
        if not capability:
            continue
        selected_items = [
            dict(item) for item in capability.get("starter_items", [])
            if not item.get("module_ids") or module_id in item.get("module_ids", [])
        ]
        if not selected_items:
            continue
        contracts.append({
            "capability_id": ref,
            "title": capability["title"],
            "primary_action": capability["primary_action"],
            "states": list(capability.get("states", [])),
            "result_contract": capability["result_contract"],
            "mobile_contract": capability["mobile_contract"],
            "source_boundary": capability["source_boundary"],
        })
        for item in selected_items:
            if item["item_id"] not in seen_items:
                seen_items.add(item["item_id"])
                items.append(item)
    stage_items = education_stage_overrides().get(str(learning_stage_id), {}).get(module_id, []) if learning_stage_id else []
    if stage_items:
        items = [item for item in items if item.get("kind") != "question"]
        items.extend(dict(item) for item in stage_items)
    stage_references = education_stage_references().get(str(learning_stage_id), {}).get(module_id, []) if learning_stage_id else []
    if stage_references:
        seen_references = {item["item_id"] for item in items}
        items.extend(dict(item) for item in stage_references if item["item_id"] not in seen_references)
    items = [_resolve_generator(item, learning_stage_id) for item in items]
    if not contracts or not items:
        raise ContractError(f"模块没有可执行 starter 内容：{module_id} / {refs}")
    kinds = sorted({str(item["kind"]) for item in items})
    kind_labels = {
        "action": "小任务",
        "template": "可编辑模板",
        "question": "练习题",
        "calculator": "小工具",
        "reference": "参考内容",
        "prompt": "每日提示",
        "generator": "口算生成器",
    }
    if kinds == ["question"]:
        summary = f"这里有 {len(items)} 道练习题，答完马上能看结果和解析"
    elif "generator" in kinds and "reference" in kinds:
        summary = f"这里有 {len(items)} 项可以直接开始的内容（含不限题量的口算天天练与可点读的参考内容）"
    elif "generator" in kinds:
        summary = f"这里有 {len(items)} 项可以直接开始的内容（含不限题量的口算天天练）"
    elif "reference" in kinds:
        labels = "、".join(kind_labels[kind] for kind in kinds)
        summary = f"这里有 {len(items)} 项可以直接开始的内容（{labels}；参考内容点一点就能听）"
    else:
        summary = f"这里有 {len(items)} 项可以直接开始的内容（{'、'.join(kind_labels[kind] for kind in kinds)}）"
    return {
        "contract_version": "mobile_scene_capability_v1",
        "module_id": module_id,
        "capability_refs": [row["capability_id"] for row in contracts],
        "contracts": contracts,
        "item_kinds": kinds,
        "starter_items": items,
        "summary": summary,
    }
