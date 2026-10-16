#!/usr/bin/env python3
"""审查用户已经提出过的儿童乐园问题，防止同一类低级错误再漏。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
REFERENCES = SKILL / "references"
SOURCE = SKILL / "scripts" / "double6_runtime" / "child_playground.py"
STARTERS = REFERENCES / "education-stage-starters.json"
CATALOG = REFERENCES / "review-invariants.json"
OVERLAY_STAGES = (
    "baby-growth-explorer",
    "primary-transition-2-to-3",
    "primary-transition-3-to-4",
)
PRACTICE_MODULES = (
    "education-language",
    "education-math",
    "education-english",
    "education-reading",
    "education-explore",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def _js_function(source: str, name: str) -> str:
    needle = f"function {name}("
    start = source.find(needle)
    if start < 0:
        return ""
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    return source[start:]


def _stage_items(starters: dict[str, Any], stage_id: str) -> list[dict[str, Any]]:
    for stage in starters.get("stages", []):
        if stage.get("stage_id") == stage_id:
            items: list[dict[str, Any]] = []
            for module_id in PRACTICE_MODULES:
                rows = stage.get("modules", {}).get(module_id) or []
                items.extend(row for row in rows if isinstance(row, dict) and row.get("kind") == "question")
            return items
    return []


def check_promised_remaining_has_entry(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    from double6_runtime.content_mines import check_next_is_one_button, check_practice_keeps_story

    errors: list[str] = []
    errors.extend(check_next_is_one_button(source))
    errors.extend(check_practice_keeps_story(source))
    practice = _js_function(source, "renderStagePractice")
    if "nextSameTypeHtml(item)" not in practice and "下一题" not in practice:
        errors.append("作答页答完后必须有下一题")
    if "overlaySceneHtml(item)" not in practice:
        errors.append("作答页必须带上故事，不能把故事留在上一页")
    return errors


def check_content_mines(source: str, starters: dict[str, Any]) -> list[str]:
    from double6_runtime.child_playground import _stage_pack_items
    from double6_runtime.content_mines import (
        audit_all_workbench_questions,
        audit_items,
        check_hero_source_skips_answer,
        check_next_is_one_button,
        check_option_letters_fit_card,
        check_practice_keeps_story,
        check_serve_path_shuffles,
        check_stage_copy_is_group_play,
        check_visible_copy_avoids_licensed_ultraman,
    )

    del starters
    errors: list[str] = []
    errors.extend(check_next_is_one_button(source))
    errors.extend(check_practice_keeps_story(source))
    errors.extend(check_hero_source_skips_answer(source))
    errors.extend(check_option_letters_fit_card(source))
    errors.extend(check_stage_copy_is_group_play(source))
    errors.extend(check_visible_copy_avoids_licensed_ultraman(source))
    errors.extend(
        check_visible_copy_avoids_licensed_ultraman(
            (REFERENCES / "incentive-library.json").read_text(encoding="utf-8")
        )
    )
    errors.extend(check_serve_path_shuffles((SKILL / "scripts" / "double6_runtime" / "starter_content.py").read_text(encoding="utf-8")))
    from double6_runtime.content_mines import check_auto_hero_follows_story

    errors.extend(audit_all_workbench_questions())
    errors.extend(check_auto_hero_follows_story())
    for stage_id in OVERLAY_STAGES:
        try:
            packed = _stage_pack_items(stage_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{stage_id} 组包失败，无法排雷：{exc}")
            continue
        errors.extend(audit_items(packed))
    return errors


def check_type_bank_6_to_10(source: str, starters: dict[str, Any]) -> list[str]:
    del source
    errors: list[str] = []
    for stage_id in OVERLAY_STAGES:
        items = _stage_items(starters, stage_id)
        if not items:
            errors.append(f"{stage_id} 没有可审查题库")
            continue
        counts: dict[str, int] = {}
        for item in items:
            point = str(item.get("knowledge_point") or "").strip()
            if point:
                counts[point] = counts.get(point, 0) + 1
        if len(counts) < 6:
            errors.append(f"{stage_id} 知识点不足 6 个：{len(counts)}")
        for point, count in counts.items():
            if not 6 <= count <= 10:
                errors.append(f"{stage_id}/{point} 需要 6–10 题，当前 {count}")
    return errors


def check_giraffe_not_own_friend(source: str, starters: dict[str, Any]) -> list[str]:
    del source
    items = _stage_items(starters, "baby-growth-explorer")
    row = next((item for item in items if item.get("item_id") == "baby-math-02"), None)
    if not row:
        return ["找不到 baby-math-02"]
    errors: list[str] = []
    options = [str(option) for option in row.get("options") or []]
    if row.get("answer") == "长颈鹿":
        errors.append("高矮小队答案不能是长颈鹿自己")
    if "长颈鹿" in options:
        errors.append("高矮小队选项里不能再放长颈鹿")
    return errors


def check_hero_and_picture_options(source: str, starters: dict[str, Any]) -> list[str]:
    items = _stage_items(starters, "baby-growth-explorer")
    row = next((item for item in items if item.get("item_id") == "baby-math-02"), None)
    if not row:
        return ["找不到 baby-math-02"]
    errors: list[str] = []
    if row.get("hero") != "🦒":
        errors.append("高矮小队题图必须是长颈鹿，不能再用猫或从选项里抽")
    icons = row.get("option_icons") if isinstance(row.get("option_icons"), dict) else {}
    options = [str(option) for option in row.get("options") or []]
    missing = [option for option in options if not icons.get(option)]
    if missing:
        errors.append(f"高矮小队选项缺少图片/emoji：{missing}")
    start = source.find("def _stage_visual_hero")
    hay = source[start : start + 800] if start >= 0 else ""
    if 'row.get("options")' in hay:
        errors.append("题图不得从选项里抽，否则长颈鹿题会变成猫")
    return errors


def check_room_not_covered_by_today_board(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    if "data-room-stage" not in source:
        errors.append("首页必须有独立房间舞台 data-room-stage")
    if 'playground-hero home-stage"><section class="today-board"' in source:
        errors.append("今天三站不得再叠在房间图上")
    home = _js_function(source, "renderHome")
    if "data-room-stage" in home and "today-board" in home:
        room_at = home.find("data-room-stage")
        board_at = home.find("today-board")
        if room_at < board_at:
            errors.append("今天三站必须在房间图前面，不能被大图挤出首屏")
    return errors


def check_tonight_board_before_room(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    home = _js_function(source, "renderHome")
    if "today-board" not in home:
        errors.append("首页必须有今天三站")
    if "data-room-stage" in home and "today-board" in home:
        if home.find("data-room-stage") < home.find("today-board"):
            errors.append("今晚那一件是今天三站，房间门牌只能跟在后面")
    if "data-companion-card" in home and "today-board" in home:
        companion_at = home.find("companionCardHtml")
        board_at = home.find("today-board")
        if companion_at >= 0 and board_at >= 0 and board_at < companion_at:
            errors.append("伙伴卡仍应在今天三站前面")
    if re.search(r"home-stage\{[^}]*min-height:(1[3-9]\d|[2-9]\d{2})px", source):
        errors.append("首页房间只做门牌条，不得再做成杂志大图")
    return errors


def check_phone_home_only_today_count(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    face = re.search(
        r'"primary-transition-1-to-2":\s*\{[^{}]*"hud":\s*"([^"]+)"',
        source,
        re.S,
    )
    if not face or face.group(1) == "full":
        errors.append("一升二首页不得再用四格统计 HUD")
    if re.search(r'"hud":\s*"full"', source):
        errors.append("儿童学段不得登记 hud=full，手机首屏会被统计格挤掉今天三站")
    if ".home-stat:not(:first-child){display:none}" not in source.replace(" ", ""):
        errors.append("窄屏必须藏起今天 n/3 以外的首页统计格")
    home = _js_function(source, "renderHome")
    if "今天" not in home or "dailyDone}/3" not in home:
        errors.append("首页必须能显示今天 n/3")
    return errors


def check_visit_familiarity_on_companion(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    if "function noteHomeVisit" not in source:
        errors.append("打开首页必须记下 home_visited")
    if "home_visited" not in source or "visited>0" not in source.replace(" ", ""):
        errors.append("打开首页必须算今天来过")
    if "data-visit-familiarity" not in source:
        errors.append("伙伴卡必须投影近三日来过")
    if "这几天都见到你了" not in source:
        errors.append("连续来过三天必须能感到变化")
    if "连续有记录" in _js_function(source, "companionCardHtml"):
        errors.append("伙伴卡不得写连续天数数字")
    home = _js_function(source, "renderHome")
    if "noteHomeVisit()" not in home:
        errors.append("renderHome 必须先记下今天来过")
    return errors


def check_overlay_practice_must_have_hero(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    render = _js_function(source, "renderContent")
    if "item.presentation.hero" in render and "presentation.hero||objectForItem" not in render and "presentation||{}" not in render:
        errors.append("作答页不得直接读 item.presentation.hero，缺图会整页崩溃")
    if "const presentation=item.presentation||{}" not in render:
        errors.append("作答页必须给 presentation 兜底")
    if "heroIsPicture" not in render:
        errors.append("作答页必须能渲染题图，不能只在说明页或卡片封面放图")
    return errors


def check_kid_voice_not_exam_paper(source: str, starters: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    worksheet = re.compile(
        r"(语文|数学|英语|阅读|观察|科学|近义|量词|加法|减法|乘法|除法).*\d+$"
    )
    banned_title = ("近义词辨析", "三位数加法", "场所词汇", "语文字词")
    for stage_id in ("primary-transition-2-to-3", "primary-transition-3-to-4"):
        for item in _stage_items(starters, stage_id):
            title = str(item.get("title") or "")
            if worksheet.search(title) or title in banned_title:
                errors.append(f"{item.get('item_id')} 标题仍是试卷腔：{title}")
            prompt = str(item.get("prompt") or "")
            if "近义词是" in prompt or "主要使用了什么写法" in prompt:
                errors.append(f"{item.get('item_id')} 问句仍是试卷腔")
    teach = _js_function(source, "renderStageTeach")
    if "今天练的是" in teach:
        errors.append("说明页不得写出知识点名称")
    if "不记掌握" in teach:
        errors.append("说明页不得出现掌握、测评一类成人词")
    practice = _js_function(source, "renderStagePractice")
    if not practice:
        errors.append("孩子作答页必须单独渲染，不能和成人标签堆在一起")
    elif "基础练习" in practice or "点选答案" in practice or "还没做" in practice:
        errors.append("孩子作答页不得出现基础练习、点选答案、还没做")
    if "今天来玩" not in source:
        errors.append("宝宝首页标题应仍是今天来玩")
    if "我的房间" not in source:
        errors.append("侧栏应写我的房间，不是学习工作台")
    if re.search(r'\(\("近义".{0,40}🔤', source):
        errors.append("近义题不得再把题图落成字母块")
    if "_meaning_icon" not in source:
        errors.append("题图和选项必须按词义选图")
    return errors


def check_scene_confirm_before_new_group(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    next_fn = _js_function(source, "nextSameTypeItem")
    if "family_id" in next_fn:
        errors.append("下一题不得在一组做完后自动跳进同科下一组")
    if "return null" not in next_fn:
        errors.append("一组做完后下一题必须停住")
    if "data-scene-confirm" not in source:
        errors.append("新场景开始前必须先确认")
    if "data-scene-count" not in source:
        errors.append("确认页必须写出这一站有几题")
    if "data-scene-more" not in source:
        errors.append("还想再玩一组必须另点确认，不能直接出新题")
    if 'STAGE_OVERLAY&&t.dataset.skipTeach===undefined?"teach"' not in source:
        errors.append("从首页或学科页进新站必须先出确认，不能直接作答")
    teach = _js_function(source, "renderStageTeach")
    if "先回去" not in teach:
        errors.append("确认页必须能先回去")
    return errors


def check_four_stages_not_same_face(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    faces = re.findall(r'"face_id": "([^"]+)"', source)
    if len(set(faces)) < 4:
        errors.append("四档必须各有一张不同的脸，不能共用同一套壳")
    for title in ("今天来玩", "今天的一升二", "今天先看懂", "今天先看清"):
        if title not in source:
            errors.append(f"缺少学段首页标题：{title}")
    for cta in ("我们一起指", "去做这一站", "先看懂再做", "先看清再辨"):
        if cta not in source:
            errors.append(f"缺少学段主按钮：{cta}")
    if '"default_skin": "companion-panda"' not in source:
        errors.append("二升三默认应进竹林小屋，不能再默认小狗花园")
    if '"default_skin": "companion-ultraman"' not in source:
        errors.append("三升四默认应进暮光小屋，不能再默认小狗花园")
    if "data-stage-face" not in source:
        errors.append("页面必须标出学段脸，审查才能核对四档不同")
    if "data-stage-home-title" not in source:
        errors.append("首页标题必须可按学段核验")
    if "data-stage-chip" not in source:
        errors.append("首页必须有学段口吻标签")
    theme = _load_json(REFERENCES / "child-visual-theme.json")
    rooms = [room for room in theme.get("rooms") or [] if isinstance(room, dict)]
    heroes = [str(room.get("hero") or "") for room in rooms]
    if len([name for name in heroes if name]) < 4 or len(set(heroes)) < 4:
        errors.append("四档房间主图必须是不同文件，不能共用同一张构图")
    asset_dir = REFERENCES / "assets" / "child-playground-v2"
    hashes: list[str] = []
    composition_ids: list[str] = []
    buildings: list[str] = []
    cameras: list[str] = []
    settings: list[str] = []
    for room in rooms:
        room_id = str(room.get("room_id") or "")
        hero = str(room.get("hero") or "")
        path = asset_dir / hero
        if not path.is_file():
            errors.append(f"{room_id} 缺少主图文件 {hero}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.append(digest)
        expected = str(room.get("hero_sha256") or "")
        if expected and expected != digest:
            errors.append(f"{room_id} 主图哈希与合同不符，可能被换成同一张构图")
        composition = room.get("composition") if isinstance(room.get("composition"), dict) else {}
        if not composition.get("id") or not composition.get("building") or not composition.get("camera"):
            errors.append(f"{room_id} 必须写明 composition.id / camera / building，不能只换文件名")
        composition_ids.append(str(composition.get("id") or ""))
        buildings.append(str(composition.get("building") or ""))
        cameras.append(str(composition.get("camera") or ""))
        settings.append(str(composition.get("setting") or ""))
    if len(set(hashes)) < 4:
        errors.append("四档房间主图文件内容不能相同")
    if len(set(composition_ids)) < 4:
        errors.append("四档 composition.id 必须不同，不能共用同一张构图合同")
    if len(set(buildings)) < 4:
        errors.append("四档房子形状必须不同，不能都是同一座小屋")
    if len(set(cameras)) < 4:
        errors.append("四档机位必须不同")
    if len(set(settings)) < 4:
        errors.append("四档场景必须不同")
    return errors


def check_companion_mood_portraits(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    compact = source.replace(" ", "")
    if "function companionPortraitPole" not in source:
        errors.append("运行时必须按心情选 waiting / well 图，不能只贴一张笑脸")
    if "companionPortraitHtml(skinId,mood)" not in compact:
        errors.append("companionPortraitHtml 必须接收心情，不能只按皮取一张图")
    if "ASSETS.companion_moods" not in source and "ASSETS&&ASSETS.companion_moods" not in source:
        errors.append("运行时必须读取 ASSETS.companion_moods")
    if "companionPortraitHtml(companion.skin_id,companion.mood)" not in compact:
        errors.append("顶栏伙伴头像必须按当前心情换图")
    if "companionPortraitHtml(view.skin_id,view.mood)" not in compact:
        errors.append("伙伴卡必须按当前心情换图")
    theme = _load_json(REFERENCES / "child-visual-theme.json")
    moods = theme.get("companion_moods") if isinstance(theme.get("companion_moods"), dict) else {}
    skins = moods.get("skins") if isinstance(moods.get("skins"), dict) else {}
    reuse = moods.get("reuse") if isinstance(moods.get("reuse"), dict) else {}
    if reuse.get("hopeful") != "waiting" or reuse.get("almost") != "waiting":
        errors.append("hopeful / almost 必须复用 waiting 图，不得另出中间态")
    required = ("companion-puppy", "companion-panda", "companion-plants", "companion-ultraman")
    asset_dir = REFERENCES / "assets" / "child-playground-v2"
    hashes: list[str] = []
    for skin_id in required:
        poles = skins.get(skin_id) if isinstance(skins.get(skin_id), dict) else {}
        pole_hashes: dict[str, str] = {}
        for pole in ("waiting", "well"):
            row = poles.get(pole) if isinstance(poles.get(pole), dict) else {}
            file = str((row or {}).get("file") or "").strip()
            if not file:
                errors.append(f"{skin_id} 缺少 {pole} 心情图合同")
                continue
            path = asset_dir / file
            if not path.is_file():
                errors.append(f"{skin_id} 缺少心情图文件 {file}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = str((row or {}).get("sha256") or "")
            if expected and expected != digest:
                errors.append(f"{skin_id} {pole} 心情图哈希与合同不符")
            pole_hashes[pole] = digest
            hashes.append(digest)
        if len(pole_hashes) == 2 and pole_hashes["waiting"] == pole_hashes["well"]:
            errors.append(f"{skin_id} 的在等图和好了图不能是同一张")
    if len(set(hashes)) < 8:
        errors.append("四种皮的在等/好了图必须是八张不同文件")
    return errors


def check_warrior_waiting_shows_beast(source: str, starters: dict[str, Any]) -> list[str]:
    del source, starters
    theme = _load_json(REFERENCES / "child-visual-theme.json")
    moods = theme.get("companion_moods") if isinstance(theme.get("companion_moods"), dict) else {}
    skins = moods.get("skins") if isinstance(moods.get("skins"), dict) else {}
    warrior = skins.get("companion-ultraman") if isinstance(skins.get("companion-ultraman"), dict) else {}
    waiting = warrior.get("waiting") if isinstance(warrior.get("waiting"), dict) else {}
    composition = waiting.get("composition") if isinstance(waiting.get("composition"), dict) else {}
    errors: list[str] = []
    cast = [str(item) for item in (composition.get("visible_cast") or [])]
    if "ridge-beast" not in cast:
        errors.append("光之勇士在等图必须画出可见的小兽，不能只是勇士特写")
    if composition.get("camera") == "close-up-face":
        errors.append("光之勇士在等图不能再用脸部特写，卡片上看不见怪兽")
    if composition.get("id") != "ridge-two-figure":
        errors.append("光之勇士在等图必须是悬崖双人中景")
    asset = REFERENCES / "assets" / "child-playground-v2" / "companions" / "beast.jpg"
    if not asset.is_file():
        errors.append("缺少原创粘土小兽身份图 companions/beast.jpg")
    return errors


def check_option_letters_on_source(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    from double6_runtime.content_mines import check_option_letters_fit_card

    return check_option_letters_fit_card(source)


def check_stage_copy_on_source(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    from double6_runtime.content_mines import check_stage_copy_is_group_play

    return check_stage_copy_is_group_play(source)


def check_room_claim_visible(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    errors: list[str] = []
    if "function roomClaimLabel" not in source:
        errors.append("运行时必须能把门牌写成「我的房间」或「乐乐的房间」")
    if "function sanitizeRoomName" not in source:
        errors.append("称呼必须先清洗，不能原样写入门牌")
    if "data-room-claim-label" not in source:
        errors.append("房子图上必须有门牌")
    if "data-room-claim-save" not in source.replace(" ", ""):
        errors.append("家长区必须能写称呼到门牌")
    if "只留在这台设备" not in source:
        errors.append("写称呼时必须说明只留本机")
    if "function bindRoomPropDrag" in source or "function roomPropHtml" in source:
        errors.append("儿童首页不得再把摆放小物件当成主活动")
    if "room-belonging-picks" in source or "按住拖到你喜欢的地方" in source:
        errors.append("儿童首页不得再出现摆件选择条")
    from double6_runtime.room_claim import room_claim_label, sanitize_room_name

    if sanitize_room_name("奥特曼") or sanitize_room_name("Hello Kitty"):
        errors.append("称呼不得接受授权 IP 名")
    if room_claim_label("小花园", "") != "我的小花园":
        errors.append("没写名字时门牌必须是「我的小花园」")
    if room_claim_label("小花园", "乐乐") != "乐乐的小花园":
        errors.append("写了名字后门牌必须是「乐乐的小花园」")
    return errors


def check_ultraman_copy(source: str, starters: dict[str, Any]) -> list[str]:
    del starters
    from double6_runtime.content_mines import check_visible_copy_avoids_licensed_ultraman

    errors = check_visible_copy_avoids_licensed_ultraman(source)
    errors.extend(
        check_visible_copy_avoids_licensed_ultraman(
            (REFERENCES / "incentive-library.json").read_text(encoding="utf-8")
        )
    )
    return errors


CHECKERS: dict[str, Callable[[str, dict[str, Any]], list[str]]] = {
    "promised_remaining_has_entry": check_promised_remaining_has_entry,
    "four_stages_not_same_face": check_four_stages_not_same_face,
    "scene_confirm_before_new_group": check_scene_confirm_before_new_group,
    "type_bank_6_to_10": check_type_bank_6_to_10,
    "giraffe_not_own_friend": check_giraffe_not_own_friend,
    "hero_and_picture_options": check_hero_and_picture_options,
    "room_not_covered_by_today_board": check_room_not_covered_by_today_board,
    "tonight_board_before_room": check_tonight_board_before_room,
    "phone_home_only_today_count": check_phone_home_only_today_count,
    "visit_familiarity_on_companion": check_visit_familiarity_on_companion,
    "overlay_practice_must_have_hero": check_overlay_practice_must_have_hero,
    "kid_voice_not_exam_paper": check_kid_voice_not_exam_paper,
    "content_mines": check_content_mines,
    "option_letters_fit_card": check_option_letters_on_source,
    "stage_copy_is_group_play": check_stage_copy_on_source,
    "visible_copy_avoids_licensed_ultraman": check_ultraman_copy,
    "companion_mood_portraits": check_companion_mood_portraits,
    "room_claim_visible": check_room_claim_visible,
    "warrior_waiting_shows_beast": check_warrior_waiting_shows_beast,
}


def load_catalog() -> dict[str, Any]:
    catalog = _load_json(CATALOG)
    if catalog.get("contract_version") != "child_review_invariants_v1":
        raise ValueError("review-invariants contract_version 无效")
    rows = catalog.get("invariants")
    if not isinstance(rows, list) or not rows:
        raise ValueError("review-invariants 必须登记至少一条用户问题")
    return catalog


def check_all() -> dict[str, Any]:
    catalog = load_catalog()
    source = _read(SOURCE)
    starters = _load_json(STARTERS)
    findings: list[dict[str, Any]] = []
    for row in catalog["invariants"]:
        checker_id = str(row.get("checker") or "")
        checker = CHECKERS.get(checker_id)
        if checker is None:
            findings.append(
                {
                    "id": row.get("id"),
                    "severity": row.get("severity") or "blocking",
                    "user_finding": row.get("user_finding"),
                    "errors": [f"未实现检查器：{checker_id}"],
                }
            )
            continue
        errors = checker(source, starters)
        if errors:
            findings.append(
                {
                    "id": row.get("id"),
                    "severity": row.get("severity") or "blocking",
                    "user_finding": row.get("user_finding"),
                    "errors": errors,
                }
            )
    return {
        "ok": not findings,
        "checked": len(catalog["invariants"]),
        "failed": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审查已提过的儿童乐园问题")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"已审查 {result['checked']} 条用户问题，失败 {result['failed']} 条")
        for finding in result["findings"]:
            print(f"- [{finding['severity']}] {finding['id']}: {finding['user_finding']}")
            for error in finding["errors"]:
                print(f"  · {error}")
        if result["ok"]:
            print("全部已提问题当前仍成立。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
