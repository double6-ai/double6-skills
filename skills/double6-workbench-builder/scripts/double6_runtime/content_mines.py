"""工作台题目排雷：儿童和其它场景共用同一套低级错误检查。

用户指出的不是零散笔误，而是几类会反复出现的内容雷。以后改任何场景的题库或作答页，
先跑这些检查，不要再让人一题一题排。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ONSETS = {
    "妈妈": "m",
    "蜜蜂": "m",
    "太阳": "t",
    "爸爸": "b",
    "萝卜": "l",
    "包子": "b",
    "宝宝": "b",
    "椅子": "y",
    "月亮": "y",
    "蝴蝶": "h",
    "火车": "h",
    "花花": "h",
    "苹果": "p",
    "大象": "d",
    "弟弟": "d",
    "豆子": "d",
    "小猫": "x",
    "雨伞": "y",
    "奶奶": "n",
    "牛奶": "n",
    "桌子": "z",
    "乐乐": "l",
    "西瓜": "x",
    "杯子": "b",
    "星星": "x",
    "积木": "j",
}
QUOTE = re.compile(r"[“「\"']([^”」\"']+)[”」\"']")
PAIR_TITLE = re.compile(r"^(.{1,6})和(.{1,6})$")
INCREMENT_MARKERS = ("又", "再", "放进", "来了", "飞来", "冒出", "左边", "右边", "一篮", "红堆", "蓝堆")
DIGIT = re.compile(r"\d+")
REFERENCES = Path(__file__).resolve().parents[2] / "references"


def place_answer(item_id: str, options: list[Any], answer: str) -> list[Any]:
    """把正确答案放到由题目 id 决定的位置，避免整组都是第一项。"""
    if len(options) < 2:
        return list(options)
    values = [
        str(option.get("value") or "") if isinstance(option, dict) else str(option)
        for option in options
    ]
    if answer not in values:
        return list(options)
    order = list(options)
    target = sum(ord(char) for char in item_id) % len(order)
    current = values.index(answer)
    order[current], order[target] = order[target], order[current]
    return order


def serve_question(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    options = item.get("options")
    if item.get("kind") == "question" and isinstance(options, list) and options:
        item["options"] = place_answer(str(item.get("item_id") or ""), list(options), str(item.get("answer") or ""))
    return item


def load_question_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scene_path = REFERENCES / "scene-capability-starters.json"
    if scene_path.is_file():
        catalog = json.loads(scene_path.read_text(encoding="utf-8"))
        for scene in catalog.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            for capability in scene.get("capabilities") or []:
                if not isinstance(capability, dict):
                    continue
                for item in capability.get("starter_items") or []:
                    if isinstance(item, dict) and item.get("kind") == "question":
                        row = dict(item)
                        row["_source"] = "scene-capability-starters"
                        row["_scene_id"] = scene.get("scene_id")
                        rows.append(row)
    stage_path = REFERENCES / "education-stage-starters.json"
    if stage_path.is_file():
        stages = json.loads(stage_path.read_text(encoding="utf-8"))
        for stage in stages.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            for module_id, items in (stage.get("modules") or {}).items():
                for item in items or []:
                    if isinstance(item, dict) and item.get("kind") == "question":
                        row = dict(item)
                        row["_source"] = "education-stage-starters"
                        row["_scene_id"] = stage.get("stage_id")
                        row["_module_id"] = module_id
                        rows.append(row)
    return rows


def audit_all_workbench_questions() -> list[str]:
    return audit_items([serve_question(row) for row in load_question_catalog()])


def check_serve_path_shuffles(starter_source: str) -> list[str]:
    if "serve_question(" not in starter_source:
        return ["所有场景的题目交给页面前必须打散选项，不能整组都是第一项"]
    return []


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    options = row.get("options") or []
    if options and isinstance(options[0], dict):
        options = [str(option.get("value") or "") for option in options]
    else:
        options = [str(option) for option in options]
    oracle = row.get("oracle") if isinstance(row.get("oracle"), dict) else {}
    teach = row.get("teach") if isinstance(row.get("teach"), dict) else {}
    presentation = row.get("presentation") if isinstance(row.get("presentation"), dict) else {}
    return {
        "item_id": str(row.get("item_id") or ""),
        "title": str(row.get("title") or ""),
        "prompt": str(row.get("prompt") or ""),
        "story": str(row.get("story") or teach.get("story") or ""),
        "answer": str(row.get("answer") or oracle.get("answer") or ""),
        "options": options,
        "knowledge_point": str(row.get("knowledge_point") or teach.get("focus") or ""),
        "object_counts": list(presentation.get("object_counts") or []),
        "stimulus_lines": [str(line) for line in presentation.get("stimulus_lines") or [] if line],
        "hero": str(presentation.get("hero") or row.get("hero") or ""),
    }


def _probe_word(row: dict[str, Any]) -> str:
    quoted = QUOTE.findall(row.get("prompt") or "")
    return quoted[-1] if quoted else ""


def _is_increment_story(story: str) -> bool:
    if not story or not DIGIT.search(story):
        return False
    return any(marker in story for marker in INCREMENT_MARKERS)


def check_answer_not_always_first(items: list[dict[str, Any]]) -> list[str]:
    groups: dict[str, list[int]] = defaultdict(list)
    for raw in items:
        row = _normalize(raw)
        options, answer = row["options"], row["answer"]
        if len(options) < 2 or answer not in options:
            continue
        scene = str(raw.get("_scene_id") or "")
        point = row["knowledge_point"] or row["item_id"]
        key = f"{scene}/{point}" if scene else point
        groups[key].append(options.index(answer))
    errors: list[str] = []
    for key, places in groups.items():
        if len(places) >= 4 and all(place == 0 for place in places):
            errors.append(f"{key} 有 {len(places)} 题，正确答案全在第一项")
    return errors


def check_title_does_not_leak_answer(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        title, answer, knowledge = row["title"], row["answer"], row["knowledge_point"]
        pair = PAIR_TITLE.match(title)
        if answer and not answer.isdigit() and answer in title:
            errors.append(f"{row['item_id']} 标题「{title}」里写着答案「{answer}」")
            continue
        if knowledge == "声母感知" and pair:
            errors.append(
                f"{row['item_id']} 标题「{title}」是「A和B」。声母题这样写要么泄题，要么和答案对不上"
            )
            continue
        if not pair or not answer:
            continue
        for part in pair.groups():
            if part == answer or (len(part) >= 2 and (part in answer or answer in part)):
                errors.append(f"{row['item_id']} 标题「{title}」已经点出答案「{answer}」")
                break
    return errors


def check_onset_friends(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        if row["knowledge_point"] != "声母感知":
            continue
        probe, answer, options = _probe_word(row), row["answer"], row["options"]
        if answer and options and answer not in options:
            errors.append(f"{row['item_id']} 答案「{answer}」不在选项里")
        if not probe or not answer:
            continue
        left, right = ONSETS.get(probe), ONSETS.get(answer)
        if left and right and left != right:
            errors.append(
                f"{row['item_id']} 「{probe}」和「{answer}」开头不一样（{left} vs {right}）"
            )
        if probe and PAIR_TITLE.match(row["title"]):
            pair = PAIR_TITLE.match(row["title"])
            promised = {pair.group(1), pair.group(2)}
            if answer not in promised:
                errors.append(
                    f"{row['item_id']} 标题「{row['title']}」答应的是 {promised}，答案却是「{answer}」"
                )
    return errors


def check_answer_in_options(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        if len(row["options"]) < 2:
            continue
        if row["answer"] and row["answer"] not in row["options"]:
            errors.append(f"{row['item_id']} 答案「{row['answer']}」不在选项里")
    return errors


def check_increment_story_stays_with_question(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        if not _is_increment_story(row["story"]):
            continue
        if not isinstance(raw.get("presentation"), dict):
            continue
        if not row["object_counts"]:
            errors.append(f"{row['item_id']} 故事里有数量变化，作答页却没画出对应物件")
        if row["story"] and row["story"] not in row["stimulus_lines"]:
            errors.append(f"{row['item_id']} 加减故事没有和问题放在同一页")
    return errors


def check_practice_keeps_story(source: str) -> list[str]:
    errors: list[str] = []
    if "function overlaySceneHtml" not in source:
        errors.append("作答页必须能画出题目故事，不能只剩问句")
    if "data-item-story" not in source:
        errors.append("故事和问句必须在同一页")
    if "data-overlay-scene" not in source:
        errors.append("有数量的故事要在作答页画出对应物件")
    return errors


def check_next_is_one_button(source: str) -> list[str]:
    errors: list[str] = []
    if "下一题" not in source:
        errors.append("答完后要有下一题按钮")
    if "function sameTypeGroupHtml" in source:
        start = source.find("function sameTypeGroupHtml")
        chunk = source[start : start + 800]
        if "data-same-type-entry" in chunk or "这组还有" in chunk:
            errors.append("答完后只能出下一题，不能再铺一组会泄题的标题")
    if "data-same-type-world" in source:
        errors.append("学科练一练不得在开做前列出同组题名")
    if "other.slice(0,4).map(item=>contentCard" in source:
        errors.append("学科练一练开做前不得再铺一组会泄题的题卡")
    if "data-world-practice-one" not in source:
        errors.append("overlay 练一练必须只留当前一题")
    if "data-same-type-progress" not in source or "sameTypeProgressHtml" not in source:
        errors.append("作答页要让家长看见这组第几题，例如 2/6")
    if "function nextSameTypeItem" in source:
        start = source.find("function nextSameTypeItem")
        depth = 0
        end = start
        for index in range(start, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        chunk = source[start:end]
        if "||pool.find(row=>row.item_id!==item.item_id)||null" in chunk:
            errors.append("一组题做完后不得再绕回已做过的题")
        if "!contentDone(row)" not in chunk:
            errors.append("下一题只能找还没做过的题")
        if "family_id" in chunk:
            errors.append("一组做完后不得自动跳进同科下一组，要先回去或先确认")
    return errors


def check_hero_does_not_leak_answer(items: list[dict[str, Any]]) -> list[str]:
    try:
        from double6_runtime.child_playground import _meaning_icon
    except ImportError:
        from .child_playground import _meaning_icon

    errors: list[str] = []
    for raw in items:
        presentation = raw.get("presentation") if isinstance(raw.get("presentation"), dict) else {}
        hero = str(presentation.get("hero") or "")
        if not hero:
            continue
        row = _normalize(raw)
        if row["answer"].isdigit():
            continue
        answer_icon = _meaning_icon(row["answer"])
        if answer_icon and hero == answer_icon:
            errors.append(f"{row['item_id']} 上方题图是答案「{row['answer']}」的图，已经泄题")
    return errors


def check_option_icons_do_not_mark_answer(items: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for raw in items:
        options = raw.get("options") or []
        if not options or not isinstance(options[0], dict):
            continue
        row = _normalize(raw)
        if row["answer"].isdigit() or row["answer"] not in row["options"]:
            continue
        with_icon = [str(option.get("value") or "") for option in options if option.get("icon")]
        without = [str(option.get("value") or "") for option in options if not option.get("icon")]
        if with_icon and without and with_icon == [row["answer"]]:
            errors.append(f"{row['item_id']} 只有正确答案带了图，等于把答案圈出来")
    return errors


def check_count_token_is_counted_object(items: list[dict[str, Any]]) -> list[str]:
    container_icons = {"🍽️", "🧺", "🥣", "📦"}
    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        if not _is_increment_story(row["story"]):
            continue
        presentation = raw.get("presentation") if isinstance(raw.get("presentation"), dict) else {}
        token = str(presentation.get("object_token") or "")
        if token in container_icons:
            errors.append(f"{row['item_id']} 数量图画的是盘子/篮子，不是故事里被数的物件")
    return errors


def check_hero_source_skips_answer(source: str) -> list[str]:
    start = source.find("def _stage_visual_hero")
    if start < 0:
        return []
    chunk = source[start : start + 1400]
    errors: list[str] = []
    if 'for field in ("title", "prompt", "story", "answer")' in chunk:
        errors.append("题图不得从答案里选，会泄题")
    if "_story_actor_icon" not in chunk:
        errors.append("题图必须先取故事里的角色，不能先吃引号里的「高」「妈妈」")
    story_pos = chunk.find("_story_actor_icon")
    quote_pos = chunk.find("_QUOTE_WORD")
    if quote_pos >= 0 and (story_pos < 0 or quote_pos < story_pos):
        errors.append("引号里的语言点不能排在故事角色前面当题图")
    return errors


def check_hero_matches_story_actor(items: list[dict[str, Any]]) -> list[str]:
    try:
        from double6_runtime.child_playground import _story_actor_icon
    except ImportError:
        from .child_playground import _story_actor_icon

    errors: list[str] = []
    for raw in items:
        row = _normalize(raw)
        actor = _story_actor_icon(row["story"])
        hero = row["hero"]
        if not actor or not hero:
            continue
        if hero != actor:
            errors.append(
                f"{row['item_id']} 故事里是在场角色，题图却是 {hero}，对不上故事"
            )
    return errors


def check_option_letters_fit_card(source: str) -> list[str]:
    compact = source.replace(" ", "")
    errors: list[str] = []
    if ".option-letter" not in compact:
        return errors
    if "container-type:inline-size" not in compact:
        errors.append("短选项大字必须按卡片宽度缩放，不能只写死字号")
    if ".option-letter{font-size:136px" in compact or ".option-letter[data-letter-len=\"1\"]{font-size:168px" in compact:
        errors.append("短选项不能只写死 136/168px，手机上会被卡片裁切")
    if "cqi" not in compact and "clamp(" not in compact:
        errors.append("短选项字号必须用 clamp 或容器单位适配卡片")
    return errors


def check_stage_copy_is_group_play(source: str) -> list[str]:
    if "各一题" in source:
        return ["学段首页不能再写「各一题」，现在一组连做"]
    return []


def check_visible_copy_avoids_licensed_ultraman(text: str) -> list[str]:
    if "奥特曼" in text:
        return ["可见文案不得写授权 IP「奥特曼」，暮光小屋用光之勇士"]
    return []


def check_calculator_input_labels() -> list[str]:
    """演算框必须用场景里的词，不能写数值 1、数值 2。"""
    payload = json.loads((Path(__file__).resolve().parents[2] / "references" / "scene-capability-starters.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    def walk(node: Any, scene: str = "") -> None:
        if isinstance(node, dict):
            current = str(node.get("scene_profile_id") or node.get("domain_id") or scene)
            if node.get("kind") == "calculator":
                inputs = node.get("inputs")
                labels = node.get("input_labels")
                item_id = str(node.get("item_id") or node.get("title") or "calculator")
                if not isinstance(inputs, list) or not inputs:
                    errors.append(f"{item_id} 演算缺少 inputs")
                    return
                if not isinstance(labels, list) or len(labels) != len(inputs):
                    errors.append(f"{item_id} 演算字段必须用 input_labels，且与 inputs 等长")
                    return
                for index, label in enumerate(labels):
                    text = str(label or "").strip()
                    if not text or re.fullmatch(r"数值\s*\d+", text):
                        errors.append(f"{item_id} 第 {index + 1} 个演算框不能叫「数值」，要写收入、支出这类场景用词")
            for value in node.values():
                walk(value, current)
        elif isinstance(node, list):
            for row in node:
                walk(row, scene)
    walk(payload)
    builder = (Path(__file__).resolve().parents[1] / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    if "数值 ${index+1}" in builder or "数值 ${index + 1}" in builder:
        errors.append("calculatorCard 不得把字段名写成「数值 N」")
    return errors


def check_exam_room_starters_are_bound() -> list[str]:
    """考公每个已选房间要有自己的开箱活，计划和今天科目不能抢同一张卡。"""
    payload = json.loads((Path(__file__).resolve().parents[2] / "references" / "scene-capability-starters.json").read_text(encoding="utf-8"))
    packs = json.loads((Path(__file__).resolve().parents[2] / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8"))
    domain = json.loads((Path(__file__).resolve().parents[2] / "references" / "domain-content-packs.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    scene = next((row for row in payload.get("scenes") or [] if row.get("scene_id") == "04"), None)
    if not scene:
        return ["找不到考公题库场景 04"]
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for capability in scene.get("capabilities") or []:
        for item in capability.get("starter_items") or []:
            module_ids = [str(value) for value in item.get("module_ids") or []]
            if not module_ids:
                errors.append(f"{item.get('item_id')} 必须写死 module_ids，不能让几个房间抢")
                continue
            if len(module_ids) != 1:
                errors.append(f"{item.get('item_id')} 不能同时进多个房间")
            by_module[module_ids[0]].append(item)
    required = {
        "exam-goal": ("计划", 2),
        "exam-today": ("今天科目", 3),
        "exam-practice": ("做题", 12),
        "exam-errors": ("错题", 3),
        "exam-materials": ("素材", 2),
    }
    for module_id, (label, minimum) in required.items():
        rows = by_module.get(module_id) or []
        if len(rows) < minimum:
            errors.append(f"考公{label}开箱活不够：{len(rows)} < {minimum}")
    overlay_path = Path(__file__).resolve().parents[2] / "references" / "gongkao-civil-overlay.json"
    if overlay_path.is_file():
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
        practice_topics = {
            str(row.get("topic") or "")
            for row in overlay.get("exam-practice") or []
            if row.get("kind") == "question"
        }
        if not {"言语", "判断", "数量"} <= practice_topics:
            errors.append("行测题库必须分别覆盖言语、判断、数量，不能只给一类题")
        if not any(row.get("kind") == "speak" for row in overlay.get("exam-today") or []):
            errors.append("面试房间必须有可开口的结构化面试题")
        if not any(row.get("kind") == "draft" for row in overlay.get("exam-materials") or []):
            errors.append("申论房间必须有可作答的资料题")
    else:
        today_titles = " ".join(str(row.get("title") or "") for row in by_module.get("exam-today") or [])
        if not all(token in today_titles for token in ("言语", "判断", "数量")):
            errors.append("今天科目必须分别有言语、判断、数量入口，不能和计划共用一张卡")
    if any(row.get("item_id") == "exam-plan-1" for row in by_module.get("exam-today") or []):
        errors.append("今晚这三块只能留在计划，不能出现在今天科目")
    error_points = {str(row.get("knowledge_point") or "") for row in by_module.get("exam-errors") or [] if row.get("kind") == "question"}
    if len(error_points) < 3:
        errors.append("错题回炉必须覆盖三个不同考点，不能三道同一题")
    practice_ids = {str(row.get("item_id") or "") for row in by_module.get("exam-practice") or []}
    leaked = practice_ids & {str(row.get("item_id") or "") for row in by_module.get("exam-errors") or []}
    if leaked:
        errors.append(f"错题串进了做题：{sorted(leaked)}")
    materials = " ".join(str(row.get("title") or "") + str(row.get("body") or "") for row in by_module.get("exam-materials") or [])
    if "申论" not in materials:
        errors.append("素材不能只剩公式卡，必须有申论提纲或草稿")
    drafts = [row for row in by_module.get("exam-materials") or [] if row.get("kind") == "draft"]
    if not drafts:
        errors.append("申论必须能当场写，不能只看提纲")
    if any(row.get("kind") == "template" and "申论" in f"{row.get('title') or ''}{row.get('body') or ''}" for row in by_module.get("exam-materials") or []):
        errors.append("申论不能只靠按这个改填进记录表")
    if not any(len(row.get("sections") or []) >= 3 for row in drafts):
        errors.append("申论写作面至少要能写问题、原因、对策三段")
    first_draft = next((row for row in drafts if row.get("item_id") == "exam-essay-1"), drafts[0] if drafts else {})
    if len(str(first_draft.get("prompt") or "")) > 90:
        errors.append("申论材料太长，手机第一屏看不见写作框")
    exam_pack = next(
        (row for row in packs.get("packs") or [] if row.get("composition_id") == "composition.exam.civil-service-v1"),
        {},
    )
    if "CAP-04-03" in str(
        next(
            (
                module
                for pack in domain.get("packs") or []
                for module in pack.get("modules") or []
                if module.get("module_id") == "exam-practice"
            ),
            {},
        ).get("evidence_refs")
    ):
        errors.append("做题房间不得再挂错题能力，否则回炉题会串进去")
    if "exam-today" not in str(exam_pack.get("exact_module_ids")):
        errors.append("考公 pack 必须保留今天科目")
    builder = (Path(__file__).resolve().parents[1] / "double6_runtime" / "builder.py").read_text(encoding="utf-8")
    if drafts and ("function draftCard" not in builder or "data-draft-field" not in builder or "save-draft" not in builder):
        errors.append("申论写作面必须渲染可写段落，不能只显示提纲")
    promised = [row for row in by_module.get("exam-today") or [] if "做题" in str(row.get("body") or "")]
    if promised and any(row.get("open_view") != "module-exam-practice" for row in promised):
        errors.append("科目写了去做题，必须带打开做题房的 open_view")
    if promised and ("data-open-view" not in builder or "item.open_view" not in builder):
        errors.append("科目去做题必须渲染打开 #module-exam-practice 的控件")
    practice_rows = [row for row in by_module.get("exam-practice") or [] if row.get("kind") == "question"]
    topics = {str(row.get("topic") or "") for row in practice_rows}
    if not {"言语", "判断", "数量"} <= topics:
        errors.append("做题必须能分出言语、判断、数量，不能是一组无差别练习卡")
    if any(not str(row.get("topic") or "") for row in practice_rows):
        errors.append("做题每道必须写题型")
    practice = {str(row.get("item_id") or ""): row for row in by_module.get("exam-practice") or []}
    for row in promised:
        target_id = str(row.get("open_item_id") or "")
        haystack = f"{row.get('title') or ''} {row.get('body') or ''}"
        if not target_id:
            errors.append(f"科目 {row.get('item_id')} 写了去做题，必须落到对应题，不能只打开做题房")
            continue
        target = practice.get(target_id)
        if not target:
            errors.append(f"科目 {row.get('item_id')} 指向的题不在做题房：{target_id}")
            continue
        point = str(target.get("knowledge_point") or "")
        if point and point not in haystack and not any(token in haystack for token in point.replace("问题", "").split()):
            errors.append(f"科目 {row.get('item_id')} 写的是「{haystack.strip()}」，却落到「{point}」")
    if promised and ("data-open-item" not in builder or "open_item_id" not in builder or "jumpStarterToItem" not in builder):
        errors.append("科目去做题必须按 open_item_id 落到对应题")
    return errors


def check_starter_actions_not_sticky(builder_source: str) -> list[str]:
    """手机开箱动作条必须跟在卡片里，不能吸底挡住选项和下一张卡。"""
    errors: list[str] = []
    compact = builder_source.replace(" ", "")
    if ".starter-actions{position:sticky" in compact or ".starter-actions{{position:sticky" in compact:
        errors.append("手机开箱动作条不能吸底挡住选项和下一张卡")
    return errors


def check_finance_room_starters_are_bound() -> list[str]:
    """记账每个已选房间要有自己的开箱活，凭证不能冒出收支演算，复盘和审计不能同题。"""
    payload = json.loads((Path(__file__).resolve().parents[2] / "references" / "scene-capability-starters.json").read_text(encoding="utf-8"))
    domain = json.loads((Path(__file__).resolve().parents[2] / "references" / "domain-content-packs.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    scene = next((row for row in payload.get("scenes") or [] if row.get("scene_id") == "07"), None)
    if not scene:
        return ["找不到记账题库场景 07"]
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected = {
        "finance-transactions",
        "finance-vouchers",
        "finance-tax",
        "finance-review",
        "finance-audit",
    }
    for capability in scene.get("capabilities") or []:
        for item in capability.get("starter_items") or []:
            module_ids = [str(value) for value in item.get("module_ids") or []]
            if not module_ids:
                errors.append(f"{item.get('item_id')} 必须写死 module_ids，不能让几个房间抢")
                continue
            if len(module_ids) != 1:
                errors.append(f"{item.get('item_id')} 不能同时进多个房间")
            by_module[module_ids[0]].append(item)
    required = {
        "finance-transactions": ("记账", 2),
        "finance-vouchers": ("凭证", 3),
        "finance-tax": ("税务", 2),
        "finance-review": ("复盘", 2),
        "finance-audit": ("审计", 2),
    }
    for module_id, (label, minimum) in required.items():
        rows = by_module.get(module_id) or []
        if len(rows) < minimum:
            errors.append(f"记账{label}开箱活不够：{len(rows)} < {minimum}")
    voucher_text = " ".join(str(row.get("title") or "") + str(row.get("body") or "") for row in by_module.get("finance-vouchers") or [])
    if "收入" in voucher_text and "支出" in voucher_text and "小票" not in voucher_text:
        errors.append("凭证房间不能拿收支演算充数")
    if any(row.get("item_id") == "fin-cash-1" for row in by_module.get("finance-vouchers") or []):
        errors.append("月度收支演算只能留在记账房间，不能出现在凭证")
    if "勾" not in voucher_text and "小票" not in voucher_text:
        errors.append("凭证必须能勾票、留缺票，不能只剩导入模板")
    review_ids = {str(row.get("item_id") or "") for row in by_module.get("finance-review") or []}
    audit_ids = {str(row.get("item_id") or "") for row in by_module.get("finance-audit") or []}
    if review_ids & audit_ids:
        errors.append(f"复盘和审计串题：{sorted(review_ids & audit_ids)}")
    review_points = {str(row.get("knowledge_point") or "") for row in by_module.get("finance-review") or [] if row.get("kind") == "question"}
    audit_points = {str(row.get("knowledge_point") or "") for row in by_module.get("finance-audit") or [] if row.get("kind") == "question"}
    if review_points & audit_points:
        errors.append("复盘和审计不能用同一个考点")
    if not any("缺票" in str(row.get("prompt") or "") or "没有票" in str(row.get("prompt") or "") for row in by_module.get("finance-review") or []):
        errors.append("复盘必须能判断缺票")
    if not any("8821" in str(row.get("prompt") or "") or "重复" in str(row.get("title") or "") for row in by_module.get("finance-audit") or []):
        errors.append("审计必须能判断重复票据")
    voucher_refs = next(
        (
            module.get("evidence_refs")
            for pack in domain.get("packs") or []
            for module in pack.get("modules") or []
            if module.get("module_id") == "finance-vouchers"
        ),
        [],
    )
    if "CAP-07-04" in [str(value) for value in voucher_refs or []]:
        errors.append("凭证房间不得再挂导入模板能力，否则会冒出流水预览")
    if selected - set(by_module):
        errors.append(f"记账已选房间缺开箱活：{sorted(selected - set(by_module))}")
    return errors


def check_exam_questions_match_civil_service() -> list[str]:
    """考公第一题必须像行测/申论练习，不能是小学生近义词。"""
    payload = json.loads((Path(__file__).resolve().parents[2] / "references" / "scene-capability-starters.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    questions: list[dict[str, Any]] = []

    def walk(node: Any, in_exam: bool = False) -> None:
        if isinstance(node, dict):
            domains = node.get("domain_ids") if isinstance(node.get("domain_ids"), list) else []
            current = in_exam or "civil-service" in str(node.get("scene_profile_id") or "") or node.get("domain_id") == "exam-preparation" or "exam-preparation" in domains or str(node.get("scene_id") or "") == "04"
            if current and node.get("kind") == "question":
                questions.append(node)
            for value in node.values():
                walk(value, current)
        elif isinstance(node, list):
            for row in node:
                walk(row, in_exam)

    walk(payload)
    if not questions:
        return ["考公题库缺少可作答题目"]
    first = questions[0]
    prompt = str(first.get("prompt") or "")
    knowledge = str(first.get("knowledge_point") or "")
    banned = ("最接近下面哪个词", "近义词", "反义词", "词义辨析")
    if any(token in prompt or token == knowledge for token in banned):
        errors.append("考公第一题不能是小学生近义词，要像行测言语、数量、判断或常识")
    if len(prompt) < 28:
        errors.append("考公第一题题干过短，不像一套能练的题")
    childlike = [
        row
        for row in questions
        if any(
            token in str(row.get("prompt") or "") or token == str(row.get("knowledge_point") or "")
            for token in banned + ("少百分之多少", "打八折", "可再生能源")
        )
    ]
    if childlike:
        errors.append("考公题库仍有词义辨析、八折或少百分之多少一类小学题")
    return errors


def check_visible_copy_avoids_builder_speak(builder_source: str) -> list[str]:
    """使用者看见的文案不能是制作器内部词。"""
    errors: list[str] = []
    if "内置内容已完成" in builder_source or "自有记录 ${" in builder_source or "自有记录 1" in builder_source:
        errors.append("首页进度不能写「内置内容 / 自有记录」，那是制作器的话")
    if "上方内置内容仍可直接使用" in builder_source:
        errors.append("空记录提示不能把制作器内部结构说给使用者听")
    if "完整操作区" in builder_source or "查看模板与全部原始记录" in builder_source:
        errors.append("记录表单不能写成「完整操作区」或「查看模板」，那是制作器的话")
    if "添加新内容、查看模板" in builder_source:
        errors.append("记录表单标题不能是添加新内容和查看模板")
    if "查看详情" in builder_source:
        errors.append("开箱卡不能再放「查看详情」，卡上就是今晚的活")
    if "待完成的小事" in builder_source or '"数据记录"' in builder_source:
        errors.append("房间眉题不能写「待完成的小事」或「数据记录」，要说今晚的活")
    if "先从这里开始" in builder_source:
        errors.append("开箱卡顶不能写「先从这里开始」，要说打开就能做")
    if "可反复练习" in builder_source:
        errors.append("开箱卡顶不能写「可反复练习」，那是后台引导")
    if "可以直接开始的内容" in builder_source:
        errors.append("开箱摘要不能写「可以直接开始的内容」，要说今晚就能做")
    if "打开就能做" not in builder_source and "今晚就能" not in builder_source:
        errors.append("开箱卡顶或摘要要说打开就能做、今晚就能做")
    if "完成这一项" in builder_source:
        errors.append("开箱卡不能写「完成这一项」，动作是勾掉")
    if "可编辑模板" in builder_source or "使用这个模板" in builder_source:
        errors.append("开箱卡不能写「可编辑模板」，动作是按这个改")
    if "标记已查看" in builder_source or "参考内容 · 点一点可以听" in builder_source:
        errors.append("开箱卡不能写「标记已查看」，看过了就是动作")
    if "'小任务'" in builder_source or '"小任务"' in builder_source or ":'小任务'" in builder_source:
        errors.append("开箱卡不能写「小任务」，那是制作器分类")
    return errors


def check_selected_nav_keeps_rooms() -> list[str]:
    """已选房间必须留在侧栏。不得靠收目录假装干净；丰富度是每个房间有活。"""
    errors: list[str] = []
    packs_text = (Path(__file__).resolve().parents[2] / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8")
    packs = json.loads(packs_text)
    renderers = (Path(__file__).resolve().parents[1] / "double6_runtime" / "scene_renderers.py").read_text(encoding="utf-8")
    if "tonight_nav_module_ids" in packs_text:
        errors.append("pack 不得用 tonight_nav 藏房间。丰富度是每个已选房间有活，不是少开侧栏")
    if "不得靠收目录假装干净" not in renderers:
        errors.append("侧栏必须列出已选模块，不能靠收目录优化")
    required = {
        "composition.exam.civil-service-v1": [
            "exam-goal",
            "exam-today",
            "exam-practice",
            "exam-errors",
            "exam-materials",
        ],
        "composition.finance.monthly-bookkeeping-v1": [
            "finance-transactions",
            "finance-vouchers",
            "finance-tax",
            "finance-review",
            "finance-audit",
        ],
    }
    by_id = {str(row.get("composition_id") or ""): row for row in packs.get("packs") or []}
    for composition_id, rooms in required.items():
        pack = by_id.get(composition_id) or {}
        exact = [str(value) for value in pack.get("exact_module_ids") or []]
        missing = [module_id for module_id in rooms if module_id not in exact]
        if missing:
            errors.append(f"{composition_id} 少了房间 {missing}，不能靠删模块提高「干净度」")
    return errors


def check_module_work_not_buried(builder_source: str) -> list[str]:
    """侧栏模块必须先看见可做的内容，不能只剩查看内置示例详情。"""
    errors: list[str] = []
    if "查看内置示例详情" in builder_source:
        errors.append("模块页不能把开箱工作收成「查看内置示例详情」")
    starter_at = builder_source.find("starter-surface")
    compose_at = builder_source.find("{generic_open}")
    if starter_at == -1 or compose_at == -1 or starter_at > compose_at:
        errors.append("模块页的开箱活必须在自己要留的记录折叠区外面")
    return errors


def audit_items(items: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    findings.extend(check_answer_not_always_first(items))
    findings.extend(check_title_does_not_leak_answer(items))
    findings.extend(check_onset_friends(items))
    findings.extend(check_answer_in_options(items))
    findings.extend(check_increment_story_stays_with_question(items))
    findings.extend(check_hero_does_not_leak_answer(items))
    findings.extend(check_count_token_is_counted_object(items))
    findings.extend(check_option_icons_do_not_mark_answer(items))
    return findings


def check_auto_hero_follows_story() -> list[str]:
    """自动选的题图必须跟故事角色走。作者写了 hero 的题不套这条。"""
    try:
        from double6_runtime.child_playground import _meaning_icon, _stage_pack_items, _story_actor_icon
        from double6_runtime.starter_content import education_stage_overrides
    except ImportError:
        from .child_playground import _meaning_icon, _stage_pack_items, _story_actor_icon
        from .starter_content import education_stage_overrides

    errors: list[str] = []
    overrides = education_stage_overrides()
    for stage_id, modules in overrides.items():
        try:
            packed = {item["item_id"]: item for item in _stage_pack_items(stage_id)}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{stage_id} 组包失败，无法核对题图：{exc}")
            continue
        for rows in modules.values():
            for row in rows or []:
                if not isinstance(row, dict) or row.get("kind") != "question":
                    continue
                if str(row.get("hero") or "").strip():
                    continue
                actor = _story_actor_icon(row.get("story") or "")
                if not actor:
                    continue
                if actor == _meaning_icon(str(row.get("answer") or "")):
                    continue
                hero = str(((packed.get(row.get("item_id")) or {}).get("presentation") or {}).get("hero") or "")
                if hero and hero != actor:
                    errors.append(
                        f"{row.get('item_id')} 故事里是在场角色，自动题图却是 {hero}，对不上故事"
                    )
    return errors
