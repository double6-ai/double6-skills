"""儿童学习专属单文件装配：复用 v1.7.2 内容与引擎，替换产品壳层。"""

from __future__ import annotations

import base64
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import ContractError, PACKAGE_ROOT, canonical, digest_bytes
from .html_policy import protect_offline_html
from .companion_stake import companion_runtime_contract
from .encouragement import encouragement_runtime_contract
from .incentive_library import assembled_system_ids, companion_skins
from .content_mines import place_answer
from .progress_projection import progress_runtime_contract


VISUAL_CONTRACT_VERSION = "child_playground_v2"
FORMAL_PRODUCT_VERSION = "1.7.2"
FORMAL_ITEM_COUNT = 104
DEFAULT_ATOM_IDS = (
    "learn-hanzi-shape-sound-meaning-v1",
    "learn-sentence-who-where-do-v1",
    "learn-count-one-to-one-20-v1",
    "learn-add-make-ten-100-v1",
    "learn-subtract-bridge-ten-100-v1",
    "learn-english-word-meaning-v1",
    "learn-read-explicit-information-v1",
    "learn-read-aloud-phrase-retell-v1",
)
SCIENCE_ITEM_IDS = (
    "class-foundation-animal-outlier",
    "class-foundation-fruit-outlier",
    "class-guided-school-things",
    "class-guided-numbers",
    "sequence-transfer-apple-fish",
    "sequence-transfer-moon-star",
    "offscreen-foundation-read",
    "offscreen-foundation-describe-toy",
    "offscreen-guided-sort-books",
    "offscreen-guided-fruit-count",
    "offscreen-transfer-room-sounds",
    "offscreen-transfer-leaves",
)


def _formal_root() -> Path:
    """运行资源随技能分发；按原始 SHA 校验，禁止回退到作者机器上的项目目录。"""
    root = PACKAGE_ROOT / "references/child-learning-source"
    manifest = json.loads((root / "source-integrity.json").read_text(encoding="utf-8"))
    for name, row in manifest["files"].items():
        data = (root / name).read_bytes()
        if digest_bytes(data) != row["sha256"]:
            raise ContractError(f"儿童冻结内容资源 SHA 不匹配：{name}")
    return root


def _content_source(key: str) -> Path:
    root = _formal_root()
    manifest = json.loads((root / "source-integrity.json").read_text(encoding="utf-8"))
    return root / manifest["content_library_files"][key]


def _source_html() -> Path:
    return _formal_root() / "index.source.html"


def _visual_theme() -> dict[str, Any]:
    path = PACKAGE_ROOT / "references/child-visual-theme.json"
    if not path.is_file():
        raise ContractError(f"缺少儿童视觉主题合同：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_data_uri(relative_path: str, mime: str) -> str:
    path = PACKAGE_ROOT / "references/assets/child-playground-v2" / relative_path
    if not path.is_file():
        raise ContractError(f"缺少儿童乐园资产：{path}")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _hero_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"


def _companion_mood_assets(theme: dict[str, Any]) -> dict[str, dict[str, str]]:
    moods = theme.get("companion_moods") if isinstance(theme.get("companion_moods"), dict) else {}
    skins = moods.get("skins") if isinstance(moods.get("skins"), dict) else {}
    loaded: dict[str, dict[str, str]] = {}
    for skin_id, poles in skins.items():
        key = str(skin_id or "").replace("companion-", "").strip()
        if not key or not isinstance(poles, dict):
            continue
        loaded[key] = {}
        for pole in ("waiting", "well"):
            row = poles.get(pole) if isinstance(poles.get(pole), dict) else {}
            file = str((row or {}).get("file") or "").strip()
            if not file:
                raise ContractError(f"伙伴心情图缺少文件：{skin_id}/{pole}")
            loaded[key][pole] = _asset_data_uri(file, "image/jpeg")
    if len(loaded) < 4:
        raise ContractError("四种伙伴皮都必须有 waiting / well 心情图")
    return loaded


def _child_assets() -> dict[str, Any]:
    theme = _visual_theme()
    object_names = ("apple", "fish", "flower", "ball", "leaf", "cat", "dog", "storybook")
    companion_names = ("puppy", "panda", "plants", "ultraman")
    rooms: dict[str, Any] = {}
    for room in theme.get("rooms") or []:
        room_id = str(room.get("room_id") or "").strip()
        hero = str(room.get("hero") or "").strip()
        if not room_id or not hero:
            raise ContractError("儿童房间主题缺少 room_id 或 hero")
        rooms[room_id] = {
            "room_id": room_id,
            "label": room.get("label") or room_id,
            "brand": room.get("brand") or room.get("label") or "小花园",
            "brand_sub": room.get("brand_sub") or "学习工作台",
            "emoji": room.get("emoji") or "🌱",
            "companion_skin": room.get("companion_skin") or "",
            "hero": _asset_data_uri(hero, _hero_mime(hero)),
            "decorations": list(room.get("decorations") or []),
            "palette": dict(room.get("palette") or {}),
        }
    claim = theme.get("room_claim") if isinstance(theme.get("room_claim"), dict) else {}
    if "garden" not in rooms:
        raise ContractError("儿童房间主题缺少默认小花园")
    return {
        "objects": {
            name: _asset_data_uri(f"learning-objects-openmoji/{name}.svg", "image/svg+xml")
            for name in object_names
        },
        "companions": {
            name: _asset_data_uri(f"companions/{name}.jpg", "image/jpeg")
            for name in companion_names
        },
        "companion_moods": _companion_mood_assets(theme),
        "rooms": rooms,
        "skin_to_room": dict(theme.get("skin_to_room") or {}),
        "default_room": str(theme.get("default_room") or "garden"),
        "theme_id": str(theme.get("current_theme_id") or "room-bound-companions-v1"),
        "room_claim": {
            "name_max": int((claim.get("name_max") or 6)),
        },
    }


def _pwa_metadata(product: dict[str, Any]) -> str:
    catalog = json.loads((PACKAGE_ROOT / "references/app-icons.json").read_text(encoding="utf-8"))
    icon_rows = catalog.get("sets", {}).get("double6_brand", {}).get("icons", [])
    icons = {
        f'{row.get("sizes")}:{row.get("purpose")}': row.get("png_base64")
        for row in icon_rows
    }
    required = {"64x64:favicon", "180x180:apple-touch", "192x192:any", "512x512:any", "512x512:maskable"}
    if not required <= set(icons):
        raise ContractError("儿童乐园缺少无 emoji 的 Double6 PWA 图标集")
    title = str(product["title"]).strip()
    short_name = title[:12]
    manifest = {
        "name": title,
        "short_name": short_name,
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "background_color": "#fffaf3",
        "theme_color": "#ff6f68",
        "icons": [
            {"src": f'data:image/png;base64,{icons["192x192:any"]}', "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": f'data:image/png;base64,{icons["512x512:any"]}', "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": f'data:image/png;base64,{icons["512x512:maskable"]}', "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    manifest_uri = "data:application/manifest+json;base64," + base64.b64encode(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    favicon = f'data:image/png;base64,{icons["64x64:favicon"]}'
    apple = f'data:image/png;base64,{icons["180x180:apple-touch"]}'
    return (
        '<meta name="theme-color" content="#ff6f68">\n  '
        '<meta name="mobile-web-app-capable" content="yes">\n  '
        '<meta name="apple-mobile-web-app-capable" content="yes">\n  '
        f'<meta name="apple-mobile-web-app-title" content="{short_name}">\n  '
        f'<link rel="icon" type="image/png" href="{favicon}">\n  '
        f'<link rel="shortcut icon" type="image/png" href="{favicon}">\n  '
        f'<link rel="apple-touch-icon" href="{apple}">\n  '
        f'<link rel="manifest" href="{manifest_uri}">'
    )


def _extract_assignment(source: str, name: str, next_name: str) -> tuple[int, int, dict[str, Any]]:
    start_token = f"window.{name}="
    end_token = f";window.{next_name}="
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < 0:
        raise ContractError(f"v1.7.2 候选缺少内嵌数据：{name}")
    payload_start = start + len(start_token)
    return payload_start, end, json.loads(source[payload_start:end])


def _replace_assignment(source: str, name: str, next_name: str, value: dict[str, Any]) -> str:
    start, end, _ = _extract_assignment(source, name, next_name)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return source[:start] + payload + source[end:]


def _extract_last_assignment(source: str, name: str) -> tuple[int, int, dict[str, Any]]:
    start_token = f"window.{name}="
    start = source.find(start_token)
    end = source.find(";</script>", start)
    if start < 0 or end < 0:
        raise ContractError(f"v1.7.2 候选缺少内嵌数据：{name}")
    payload_start = start + len(start_token)
    return payload_start, end, json.loads(source[payload_start:end])


def _replace_last_assignment(source: str, name: str, value: dict[str, Any]) -> str:
    start, end, _ = _extract_last_assignment(source, name)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return source[:start] + payload + source[end:]


def _replace_between(source: str, start_token: str, end_token: str, replacement: str) -> str:
    start = source.find(start_token)
    end = source.find(end_token, start)
    if start < 0 or end < 0:
        raise ContractError(f"儿童乐园壳层锚点缺失：{start_token} / {end_token}")
    return source[:start] + replacement + source[end:]


def learning_content_selection(selected_atom_ids: list[str] | None = None) -> dict[str, Any]:
    """返回构建期内容选择合同；当前参考候选默认选择全部八个 atom。"""
    selected = list(selected_atom_ids or DEFAULT_ATOM_IDS)
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(DEFAULT_ATOM_IDS):
        raise ContractError("learning_content_selection 必须选择 1–8 个已审 atom")
    source_product = json.loads((_formal_root() / "product.json").read_text(encoding="utf-8"))
    path = json.loads((_formal_root() / "learning-path-14-day.json").read_text(encoding="utf-8"))
    catalog = json.loads(
        (_formal_root() / "catalog.json").read_text(encoding="utf-8")
    )
    selected_set = set(selected)
    core_ids = [
        item["item_id"]
        for atom in catalog["atoms"]
        if atom["atom_id"] in selected_set
        for item in atom["practice"]["items"]
    ]
    base_path_ids = []
    for day in path["days"]:
        for slot in day.get("slots", []):
            targets = set(_path_item_atoms(slot["item_id"]))
            if targets & selected_set:
                base_path_ids.append(slot["item_id"])
    adaptive_ids = []
    for atom_id, roles in path["adaptive_follow_up"]["atom_role_items"].items():
        for role in path["adaptive_follow_up"]["role_order"]:
            for item_id in roles.get(role, []):
                targets = set(_path_item_atoms(item_id))
                if atom_id not in targets:
                    raise ContractError(f"自适应题目 {item_id} 错挂到能力 {atom_id}")
                if atom_id in selected_set:
                    adaptive_ids.append(item_id)
    eligible = list(dict.fromkeys([*core_ids, *base_path_ids, *adaptive_ids]))
    contract = {
        "contract_version": "child_learning_content_selection_v1",
        "source_product_version": FORMAL_PRODUCT_VERSION,
        "selection_mode": "recommended_default" if selected == list(DEFAULT_ATOM_IDS) else "parent_selected",
        "selected_atom_ids": selected,
        "eligible_item_ids": eligible,
        "core_item_ids": core_ids,
        "base_path_item_ids": list(dict.fromkeys(base_path_ids)),
        "adaptive_item_ids": list(dict.fromkeys(adaptive_ids)),
        "formal_truth_matrix_sha256": source_product["formal_content_truth"]["matrix_sha256"],
        "learning_path_id": (
            path["path_id"]
            if selected == list(DEFAULT_ATOM_IDS)
            else f'{path["path_id"]}-subset-{digest_bytes(canonical(selected))[:12]}'
        ),
        "learning_path_sha256": source_product["recommendation_plan"]["learning_path_14_day"]["manifest_sha256"],
        "adaptive_daily_item_limit": path["adaptive_follow_up"]["daily_item_limit"],
        "mastery_effect": "none_for_supplemental_movement_and_rewards",
    }
    contract["selection_sha256"] = digest_bytes(canonical(contract))
    return contract


_ITEM_ATOM_CACHE: dict[str, tuple[str, ...]] | None = None


def _path_item_atoms(item_id: str) -> tuple[str, ...]:
    global _ITEM_ATOM_CACHE
    if _ITEM_ATOM_CACHE is None:
        mapping: dict[str, tuple[str, ...]] = {}
        catalog = json.loads(
            (_formal_root() / "catalog.json").read_text(encoding="utf-8")
        )
        for atom in catalog["atoms"]:
            for item in atom["practice"]["items"]:
                mapping[item["item_id"]] = (atom["atom_id"],)
        for key in ("source_path", "adaptive_source_path", "replacement_source_path"):
            pack = json.loads((_content_source(key)).read_text(encoding="utf-8"))
            for item in pack["items"]:
                mapping[item["item_id"]] = tuple(item.get("target_atom_ids", []))
        _ITEM_ATOM_CACHE = mapping
    return _ITEM_ATOM_CACHE.get(item_id, ())


def _selection_from_product(product: dict[str, Any]) -> dict[str, Any]:
    supplied = product.get("recommendation_plan", {}).get("learning_content_selection")
    selected = supplied.get("selected_atom_ids") if isinstance(supplied, dict) else None
    return learning_content_selection(selected)


def _reward_economy(product: dict[str, Any]) -> dict[str, Any]:
    def focused_contract(reward: dict[str, Any]) -> dict[str, Any]:
        shop = reward.get("shop", [])
        badges = reward.get("badges", [])
        if not 10 <= len(shop) <= 20:
            raise ContractError("星星奖励必须保持 10–20 项家庭奖励")
        if len(badges) < 18:
            raise ContractError("儿童激励必须提供至少 18 枚可点亮徽章")
        return {
            "shop": deepcopy(shop),
            "badges": deepcopy(badges),
            "earn_rules": deepcopy(
                reward.get("earn_rules")
                or {
                    "first_formal_complete": 1,
                    "combo_at": [3, 5],
                    "combo_stars": [1, 1],
                    "daily_three_complete": 3,
                    "movement_stars": 0,
                    "family_task_stars": 0,
                }
            ),
            "library": {
                "assembled": assembled_system_ids(),
                "companion_skins": [row["system_id"] for row in companion_skins()],
            },
            "companion": companion_runtime_contract(
                default_skin=_stage_face(_learning_stage_id(product)).get("default_skin")
            ),
            "encouragement": encouragement_runtime_contract(),
            "progress": progress_runtime_contract(),
        }

    for capability in [*product.get("capabilities", []), *product.get("capability_index", [])]:
        reward = capability.get("reward_economy")
        if isinstance(reward, dict):
            return focused_contract(reward)
    catalog = json.loads((PACKAGE_ROOT / "references/domain-content-packs.json").read_text(encoding="utf-8"))
    for pack in catalog.get("packs", []):
        for module in pack.get("modules", []):
            reward = module.get("reward_economy")
            if module.get("module_id") == "education-rewards" and isinstance(reward, dict):
                return focused_contract(reward)
    raise ContractError("星星奖励标准合同缺失")


STAGE_PLAYABLE_OVERLAYS = {
    "baby-growth-explorer",
    "primary-transition-1-to-2",
    "primary-transition-2-to-3",
    "primary-transition-3-to-4",
}
_STAGE_DAY_COPY = {
    "baby-growth-explorer": "语言、数感、英语各玩一件小事。请家长读题、一起指。",
    "primary-transition-1-to-2": "语言、数学、英语各一组。一组做完先停。",
    "primary-transition-2-to-3": "词、算、词义各一组。每站先看懂再做。",
    "primary-transition-3-to-4": "词义、运算、用法各一组。每站先看清再辨。",
}
_STAGE_FACE = {
    "baby-growth-explorer": {
        "face_id": "picture-book",
        "default_skin": "companion-puppy",
        "default_room": "garden",
        "home_title": "今天来玩",
        "cta": "我们一起指",
        "hud": "soft",
        "chip": "请家长陪同",
    },
    "primary-transition-1-to-2": {
        "face_id": "garden-lesson",
        "default_skin": "companion-puppy",
        "default_room": "garden",
        "home_title": "今天的一升二",
        "cta": "去做这一站",
        "hud": "soft",
        "chip": "一组连做 · 学一学也可去",
    },
    "primary-transition-2-to-3": {
        "face_id": "bamboo-read",
        "default_skin": "companion-panda",
        "default_room": "bamboo",
        "home_title": "今天先看懂",
        "cta": "先看懂再做",
        "hud": "read",
        "chip": "先看懂这件事",
    },
    "primary-transition-3-to-4": {
        "face_id": "dusk-compare",
        "default_skin": "companion-ultraman",
        "default_room": "dusk",
        "home_title": "今天先看清",
        "cta": "先看清再辨",
        "hud": "compare",
        "chip": "先看清再判断",
    },
}
_STAGE_LESSON = {
    "baby-growth-explorer": {
        "home": "今天和家长一起玩三件小事。先看故事，再一起选。不是考试。",
        "board": "请家长读题、一起指。做完也不算测评。",
        "hero": "先听一句，再一起选。",
        "how": "听完故事，指一指，再选。",
        "cta": "我们一起指",
        "learn": "先听一句，再一起玩。",
        "together": "请家长陪在旁边。孩子指，大人读。",
    },
    "primary-transition-1-to-2": {
        "home": "今天三组，每组连做几题。做完一组先停。",
        "board": "每站先看一眼，再连做这一组。",
        "hero": "先看一眼怎么玩，再做。",
        "how": "看示范，再自己做。",
        "cta": "去做这一站",
        "learn": "学一学，再练一练。",
        "together": "",
    },
    "primary-transition-2-to-3": {
        "home": "今天先看懂再做：词、算、词义各一组。",
        "board": "每站先看这件事在问什么，再自己做。",
        "hero": "先看懂问什么。",
        "how": "把问题读完，再选。",
        "cta": "先看懂再做",
        "learn": "先看懂，再做。",
        "together": "",
    },
    "primary-transition-3-to-4": {
        "home": "今天先看清再辨：词义、运算、用法各一组。",
        "board": "每站先看差别在哪，再判断。",
        "hero": "先看清差在哪。",
        "how": "把选项看清楚，再辨。",
        "cta": "先看清再辨",
        "learn": "先看清，再辨。",
        "together": "",
    },
}


def _stage_face(stage_id: str) -> dict[str, str]:
    return dict(_STAGE_FACE.get(stage_id) or _STAGE_FACE["primary-transition-1-to-2"])
_STAGE_MODULE_ATOMS = {
    "education-language": ("learn-sentence-who-where-do-v1", "stage-lang", "语文练习", "语文"),
    "education-math": ("learn-add-make-ten-100-v1", "stage-math", "数学练习", "数学"),
    "education-english": ("learn-english-word-meaning-v1", "stage-en", "英语练习", "英语"),
    "education-reading": ("learn-read-explicit-information-v1", "stage-read", "阅读练习", "阅读"),
    "education-explore": ("learn-count-one-to-one-20-v1", "stage-explore", "观察练习", "观察"),
}


def _learning_stage_id(product: dict[str, Any]) -> str:
    stage = (product.get("recommendation_plan") or {}).get("learning_stage") or {}
    return str(stage.get("stage_id") or "")


# 题图和选项按词义选图，不按题型名。
_MEANING_ICONS: dict[str, str] = {
    "苹果": "🍎", "banana": "🍌", "香蕉": "🍌", "梨": "🍐", "橙子": "🍊", "葡萄": "🍇",
    "草莓": "🍓", "橘子": "🍊", "糖": "🍬", "贴纸": "🌟", "豆子": "🫘", "饼干": "🍪", "🍪": "🍪",
    "积木": "🧱", "玻璃珠": "🔵", "星星": "⭐", "糖果": "🍬",
    "鱼": "🐟", "小鱼": "🐟", "fish": "🐟", "花": "🌸", "小花": "🌸", "flower": "🌼",
    "球": "⚽", "皮球": "⚽", "ball": "🎾", "叶": "🍃", "树叶": "🍃", "leaf": "🍃",
    "长颈鹿": "🦒", "大象": "🐘", "小象": "🐘", "蚂蚁": "🐜", "小蚂蚁": "🐜", "猫": "🐱", "小猫": "🐱",
    "cat": "🐱", "狗": "🐶", "小狗": "🐶", "dog": "🐶", "兔": "🐰", "小兔": "🐰",
    "rabbit": "🐰", "鸟": "🐦", "小鸟": "🐦", "bird": "🐦", "蜜蜂": "🐝", "蝴蝶": "🦋",
    "龟": "🐢", "熊猫": "🐼", "panda": "🐼", "小熊": "🐻", "熊": "🐻", "bear": "🐻", "老虎": "🐯",
    "象": "🐘", "猴子": "🐵", "马": "🐴",
    "书": "📕", "book": "📕", "故事": "📕", "诗": "📜", "月亮": "🌙", "太阳": "☀️",
    "sun": "☀️", "雨": "☔", "伞": "☔", "雨伞": "☔", "火车": "🚂", "汽车": "🚗",
    "自行车": "🚲", "种子": "🌱", "影子": "🌑",
    "高兴": "😊", "开心": "😊", "快乐": "😊", "欣赏": "🖼️", "赞赏": "👏", "美丽": "🌸",
    "漂亮": "🌸", "迅速": "⚡", "快速": "⚡", "快捷": "⚡", "缓慢": "🐢", "立刻": "⏱️",
    "马上": "⏱️", "仔细": "🔍", "认真": "📝", "马虎": "🙃", "粗心": "🙃", "随便": "🤷",
    "勤奋": "💪", "努力": "💪", "懒惰": "😴", "勇敢": "🦸", "英勇": "🦸", "胆小": "🐣",
    "退缩": "🔙", "安静": "🤫", "宁静": "🤫", "热闹": "🎉", "喧哗": "📢", "嘈杂": "📢",
    "难过": "😢", "伤心": "😢", "害怕": "😨", "生气": "😠", "困惑": "🤔",
    "躲藏": "🙈", "忘记": "😶", "缩小": "🔽", "遥远": "🌄", "普通": "😐", "丑陋": "🤢",
    "狭窄": "🚪", "疲倦": "😫", "以后": "⏳", "从不": "🚫", "偶尔": "🎲",
    "寒冷": "❄️", "炎热": "🔥", "温暖": "☀️", "明亮": "💡", "昏暗": "🌑",
    "高": "🦒", "矮": "🐜", "快": "⚡", "慢": "🐢", "开始": "▶️", "结束": "⏹️",
    "铅笔": "✏️", "钢笔": "🖊️", "pen": "🖊️", "pencil": "✏️", "尺子": "📏",
    "ruler": "📏", "橡皮": "🧽", "eraser": "🧽", "包": "🎒", "bag": "🎒", "书包": "🎒",
    "桌子": "🪑", "desk": "🪑", "椅子": "🪑", "本": "📕", "枝": "✏️", "朵": "🌸",
    "匹": "🐴", "条": "🐟", "辆": "🚗", "封": "✉️",
    "学校": "🏫", "school": "🏫", "医院": "🏥", "hospital": "🏥", "公园": "🌳",
    "park": "🌳", "商店": "🛒", "shop": "🛒", "教室": "🏫", "classroom": "🏫",
    "车站": "🚉", "station": "🚉", "图书馆": "📚", "library": "📚", "厨房": "🍳",
    "卧室": "🛏️", "操场": "🏟️", "食堂": "🍱",
    "红色": "🔴", "red": "🔴", "蓝色": "🔵", "blue": "🔵", "绿色": "🟢", "green": "🟢",
    "黄色": "🟡", "yellow": "🟡", "紫色": "🟣", "黑色": "⚫", "白色": "⚪",
    "粉色": "🩷", "橙色": "🟠",
    "星期一": "1️⃣", "monday": "1️⃣", "星期二": "2️⃣", "tuesday": "2️⃣",
    "星期三": "3️⃣", "wednesday": "3️⃣", "星期四": "4️⃣", "thursday": "4️⃣",
    "星期五": "5️⃣", "friday": "5️⃣", "星期六": "6️⃣", "saturday": "6️⃣",
    "星期日": "7️⃣", "sunday": "7️⃣",
    "apple": "🍎", "water": "💧", "水": "💧", "hello": "👋", "goodbye": "👋",
    "thank": "🙏", "sorry": "🙇",
    "爸爸": "👨", "妈妈": "👩", "爷爷": "👴", "奶奶": "👵", "弟弟": "👦", "哥哥": "👦",
    "妹妹": "👧", "姐姐": "👧", "宝宝": "👶", "老师": "👩‍🏫", "乐乐": "🧒", "花花": "🌸",
    "包子": "🥟",
    "萝卜": "🥕", "大树": "🌳", "小草": "🌱", "蘑菇": "🍄", "房子": "🏠", "楼房": "🏢",
    "牛奶": "🥛", "杯子": "🥤", "西瓜": "🍉", "睡觉": "😴", "关灯": "💡", "收玩具": "🧸",
    "穿鞋": "👟", "洗澡": "🛁", "刷牙": "🪥", "打开书": "📖", "坐稳": "🪑", "去公园": "🌳",
    "放风筝": "🪁", "去跑步": "🏃", "吃午餐": "🍚",
    "圆形": "⭕", "三角形": "🔺", "正方形": "🟦", "长方形": "▬",
    "会跳舞": "💃", "会唱歌": "🎤", "会眨眼": "😉", "会用手": "👋", "会点头": "🙂",
    "会跑跳": "🏃", "会起床": "🌅", "会微笑": "😊", "小人": "🧑",
    "石头": "🪨", "算术": "➕", "雷": "⚡", "砖": "🧱", "尺": "📏", "作业": "📝",
    "铁": "⚙️", "门": "🚪", "窗": "🪟", "手表": "⌚", "粉笔": "✏️",
    "洗手": "🧼", "吃饭": "🍚", "踢球": "⚽", "浇花": "🪴", "上学": "🏫",
    "门口": "🚪", "运动会": "🏅",
    "假期": "🏖️", "银行": "🏦", "音乐": "🎵", "长大": "🌱", "重量": "⚖️", "好学": "📖",
    "米": "📏", "厘米": "📏", "小时": "⏰", "分钟": "⏱️", "钟": "⏰",
    "镜框": "🖼️", "方框": "🟦", "盒子": "📦", "盘子": "🍽️",
}
_MEANING_ICON_KEYS = tuple(sorted(_MEANING_ICONS, key=len, reverse=True))
_QUOTE_WORD = re.compile(r"[“「\"']([^”」\"']+)[”」\"']")
_ENGLISH_WORD = re.compile(r"\b([A-Za-z]{2,})\b")


def _meaning_icon(text: str, explicit: dict[str, Any] | None = None) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if explicit and raw in explicit:
        return str(explicit[raw] or "")
    folded = raw.lower()
    if folded in _MEANING_ICONS:
        return _MEANING_ICONS[folded]
    if raw in _MEANING_ICONS:
        return _MEANING_ICONS[raw]
    quoted = _QUOTE_WORD.findall(raw)
    for word in quoted:
        icon = _MEANING_ICONS.get(word) or _MEANING_ICONS.get(word.lower())
        if icon:
            return icon
    english = _ENGLISH_WORD.findall(raw)
    for word in english:
        icon = _MEANING_ICONS.get(word.lower())
        if icon:
            return icon
    for key in _MEANING_ICON_KEYS:
        if len(key) >= 2 and (key in raw or key.lower() in folded):
            return _MEANING_ICONS[key]
    return ""


def _option_icon(label: str, explicit: dict[str, Any] | None = None) -> str:
    return _meaning_icon(label, explicit)


_STAGE_VISUAL_FALLBACKS = (
    "🐻", "🦊", "🐰", "🐼", "🐸", "🐥", "🦉", "🐝", "🐢", "🦋",
    "🌙", "☀️", "🌈", "🎈", "🧩", "🎵", "🪄", "🧁", "🥕", "☂️",
    "🥁", "🚂", "🦒", "🐿️", "🖍️", "🧱", "🎯", "🍀", "🛎️", "🪁",
    "🧁", "🧸", "🪄", "🧿", "🧠", "📘", "📗", "📙", "🔮", "🪵",
)
# 故事里的角色/物件才能当题图。高/妈妈这类语言点不能抢图。
_STORY_ACTORS: dict[str, str] = {
    "长颈鹿": "🦒",
    "大象": "🐘",
    "小象": "🐘",
    "小蚂蚁": "🐜",
    "蚂蚁": "🐜",
    "小猫": "🐱",
    "小狗": "🐶",
    "小兔": "🐰",
    "小鸟": "🐦",
    "小鱼": "🐟",
    "小花": "🌸",
    "蜜蜂": "🐝",
    "蝴蝶": "🦋",
    "熊猫": "🐼",
    "小熊": "🐻",
    "小松鼠": "🐿️",
    "松鼠": "🐿️",
    "老虎": "🐯",
    "小猴": "🐵",
    "猴子": "🐵",
    "爸爸": "👨",
    "妈妈": "👩",
    "爷爷": "👴",
    "奶奶": "👵",
    "弟弟": "👦",
    "哥哥": "👦",
    "妹妹": "👧",
    "姐姐": "👧",
    "宝宝": "👶",
    "老师": "👩‍🏫",
    "乐乐": "🧒",
    "熊": "🐻",
    "象": "🐘",
    "猫": "🐱",
    "狗": "🐶",
    "兔": "🐰",
    "鸟": "🐦",
    "鱼": "🐟",
    "花": "🌸",
    "火车": "🚂",
    "汽车": "🚗",
    "书": "📕",
}
_STORY_ACTOR_KEYS = tuple(sorted(_STORY_ACTORS, key=len, reverse=True))


def _story_actor_icon(text: str) -> str:
    """从故事里取出最先出现的在场角色，不把「高」「妈妈」这种被提问的词当成题图。"""
    raw = str(text or "")
    best_icon = ""
    best_pos: int | None = None
    best_len = 0
    for key in _STORY_ACTOR_KEYS:
        pos = raw.find(key)
        if pos < 0:
            continue
        if best_pos is None or pos < best_pos or (pos == best_pos and len(key) > best_len):
            best_icon = _STORY_ACTORS[key]
            best_pos = pos
            best_len = len(key)
    return best_icon


def _place_answer(item_id: str, options: list[dict[str, Any]], answer: str) -> list[dict[str, Any]]:
    return place_answer(item_id, options, answer)


_COUNT_CONTAINERS = ("小盘子", "盘子", "碟子", "篮子", "盒子", "小盘", "碗", "盘", "篮")
_COUNT_CONTAINER_ICONS = {"🍽️", "🧺", "🥣", "📦"}


def _count_object_token(story: str, title: str) -> str:
    """点数图画被数的物件，不能画成盘子、篮子这类容器。"""
    stripped = story
    for word in sorted(_COUNT_CONTAINERS, key=len, reverse=True):
        stripped = stripped.replace(word, "")
    token = _meaning_icon(stripped) or _meaning_icon(title)
    if token in _COUNT_CONTAINER_ICONS:
        token = ""
    if token:
        return token
    hay = f"{story}{title}"
    if "积木" in hay:
        return "🧱"
    if "鸟" in hay or "只" in story:
        return "🐦"
    if "泡" in hay:
        return "🫧"
    if "苹果" in hay:
        return "🍎"
    if "草莓" in hay or "颗" in story:
        return "🍓"
    return "🍪"


def _count_scene(row: dict[str, Any]) -> tuple[list[int], str]:
    story = str(row.get("story") or "")
    title = str(row.get("title") or "")
    numbers = [int(match) for match in re.findall(r"(\d+)", story)]
    token = _count_object_token(story, title)
    two_group = ("又", "再", "放进", "来了", "飞来", "冒出", "左边", "右边", "一篮", "红堆", "蓝堆")
    if len(numbers) >= 2 and any(word in story for word in two_group):
        return numbers[:2], token
    if len(numbers) == 1 and "有" in story:
        return numbers[:1], token
    return [], token


def _stage_visible_title(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    if title and not re.search(
        r"(语文|数学|英语|阅读|观察|科学|近义|量词|加法|减法|乘法|除法).*\d+$",
        title,
    ):
        return title
    mission = str(row.get("mission") or "").strip()
    if mission:
        return mission[:16]
    prompt = str(row.get("prompt") or "").strip()
    return prompt[:16] or "今天一题"


def _stage_visual_hero(row: dict[str, Any], used: set[str]) -> str:
    answer_icon = _meaning_icon(str(row.get("answer") or ""))
    explicit = str(row.get("hero") or "").strip()
    _face_heroes = {"😢", "😠", "😨", "😄", "🤔", "😊", "😎", "😴", "😌", "😐", "😋"}
    if explicit and explicit != answer_icon and explicit not in _face_heroes:
        used.add(explicit)
        return explicit
    # 先看故事里的角色。引号里的「高」「妈妈」是题目，不是画面。
    story_icon = _story_actor_icon(row.get("story") or "")
    if story_icon and story_icon != answer_icon and story_icon not in _COUNT_CONTAINER_ICONS:
        used.add(story_icon)
        return story_icon
    title_icon = _story_actor_icon(row.get("title") or "")
    if title_icon and title_icon != answer_icon and title_icon not in _COUNT_CONTAINER_ICONS:
        used.add(title_icon)
        return title_icon
    counts, count_token = _count_scene(row)
    if counts and count_token and count_token != answer_icon and count_token not in _COUNT_CONTAINER_ICONS:
        used.add(count_token)
        return count_token
    point = str(row.get("knowledge_point") or "")
    by_point = {
        "近义词": "💬",
        "近义词辨析": "💬",
        "反义词": "↔️",
        "多音字": "🔊",
        "量词搭配": "✋",
        "标点符号": "❗️",
        "字母顺序": "🔠",
        "基础词汇": "🖼️",
        "场所词汇": "🗺️",
        "动物词汇": "🐾",
        "学习用品词汇": "✏️",
        "星期词汇": "📅",
    }
    if point in by_point and by_point[point] != answer_icon:
        used.add(by_point[point])
        return by_point[point]
    item_key = str(row.get("item_id") or "")
    start = sum(ord(char) for char in item_key) % len(_STAGE_VISUAL_FALLBACKS)
    for offset in range(len(_STAGE_VISUAL_FALLBACKS)):
        hero = _STAGE_VISUAL_FALLBACKS[(start + offset) % len(_STAGE_VISUAL_FALLBACKS)]
        if hero not in used:
            used.add(hero)
            return hero
    used.add("🌼")
    return "🌼"


def _stage_pack_items(stage_id: str) -> list[dict[str, Any]]:
    from .starter_content import education_stage_overrides

    overrides = education_stage_overrides().get(stage_id, {})
    items: list[dict[str, Any]] = []
    used_heroes: set[str] = set()
    for module_id, (atom_id, family_id, family_name, _subject) in _STAGE_MODULE_ATOMS.items():
        for row in overrides.get(module_id, []):
            if row.get("kind") != "question":
                continue
            number_mode = str(row.get("input_type") or "") == "number"
            options = []
            if not number_mode:
                icons = row.get("option_icons") if isinstance(row.get("option_icons"), dict) else {}
                raw_options = [str(option) for option in row.get("options") or []]
                inferred = []
                for label in raw_options:
                    if len(label) > 6 or "。" in label:
                        icon = str((icons or {}).get(label) or "")
                    else:
                        icon = _option_icon(label, icons)
                    inferred.append(icon)
                short_labels = all(0 < len(label) <= 4 and " " not in label for label in raw_options)
                if short_labels:
                    inferred = [""] * len(raw_options)
                elif any(inferred) and not all(inferred):
                    start = sum(ord(char) for char in str(row.get("item_id") or "")) % len(_STAGE_VISUAL_FALLBACKS)
                    for index, icon in enumerate(inferred):
                        if icon:
                            continue
                        inferred[index] = _STAGE_VISUAL_FALLBACKS[(start + index) % len(_STAGE_VISUAL_FALLBACKS)]
                elif not any(inferred) and raw_options:
                    start = sum(ord(char) for char in str(row.get("item_id") or "")) % len(_STAGE_VISUAL_FALLBACKS)
                    inferred = [
                        _STAGE_VISUAL_FALLBACKS[(start + index) % len(_STAGE_VISUAL_FALLBACKS)]
                        for index in range(len(raw_options))
                    ]
                for label, icon in zip(raw_options, inferred):
                    packed = {"value": label, "label": label, "semantic": label}
                    if icon:
                        packed["icon"] = icon
                    options.append(packed)
                options = _place_answer(str(row["item_id"]), options, str(row.get("answer") or ""))
            counts, count_token = _count_scene(row)
            hero = _stage_visual_hero(row, used_heroes)
            story = str(row.get("story") or "").strip()
            if story.startswith("这是"):
                story = ""
            mission = str(row.get("mission") or "").strip()
            if "徽章" in mission or mission.startswith("完成这一张"):
                mission = ""
            lesson = _STAGE_LESSON.get(stage_id, {})
            knowledge = str(row.get("knowledge_point") or "").strip()
            items.append(
                {
                    "item_id": str(row["item_id"]),
                    "family_id": family_id,
                    "family_name": "去玩",
                    "level": "foundation",
                    "level_label": "",
                    "mode": "assessment",
                    "kind": "question",
                    "title": _stage_visible_title(row),
                    "target_atom_ids": [atom_id],
                    "objective": mission or str(row.get("prompt") or ""),
                    "prompt": str(row.get("prompt") or ""),
                    "cues": ["选一个"],
                    "options": options,
                    "oracle": {
                        "answer": str(row.get("answer") or ""),
                        "explanation": str(row.get("explanation") or ""),
                    },
                    "response_mode": "number_input" if number_mode else "single_choice",
                    "presentation": {
                        "hero": hero,
                        "stimulus_lines": [line for line in (story,) if line],
                        "object_counts": counts,
                        "object_token": count_token if counts else "",
                    },
                    "teach": {
                        "story": story,
                        "mission": mission,
                        "how": str(lesson.get("how") or "先看懂这件事，再选。"),
                        "focus": family_id if stage_id == "primary-transition-1-to-2" else knowledge,
                        "together": str(lesson.get("together") or ""),
                        "cta": str(lesson.get("cta") or "看完了，开始这一站"),
                    },
                    "render_contract": {
                        "required_semantics": ["prompt", "choice"] if options else ["prompt"],
                    },
                    "source_boundary": {
                        "origin": "agent_authored_generic",
                        "claim": str(row.get("source_label") or "通用自编，未对齐指定教材"),
                    },
                    "stage_item": True,
                }
            )
    if len(items) < 12:
        raise ContractError(f"学段可练内容不足：{stage_id}")
    return items


def _stage_learning_days(items: list[dict[str, Any]], stage_id: str) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_family.setdefault(str(item["family_id"]), []).append(item)
    daily_families = ["stage-lang", "stage-math", "stage-en"]
    description = _STAGE_DAY_COPY.get(stage_id, "先做三题，攒星星。")
    days = []
    for day in range(1, 15):
        slots = []
        for family_id in daily_families:
            pool = by_family[family_id]
            item = pool[(day - 1) % len(pool)]
            slots.append(
                {
                    "item_id": item["item_id"],
                    "family_id": family_id,
                    "level": "foundation",
                    "arc_id": f"arc-{family_id}",
                }
            )
        days.append(
            {
                "day": day,
                "phase": "practice",
                "phase_label": "今天三站",
                "title": f"第 {day} 天三站",
                "description": description,
                "slots": slots,
            }
        )
    return days


def _apply_stage_playable_overlay(
    source: str,
    selection: dict[str, Any],
    items: list[dict[str, Any]],
    stage_id: str,
) -> tuple[str, dict[str, Any]]:
    overlay = deepcopy(selection)
    overlay["eligible_item_ids"] = [item["item_id"] for item in items]
    overlay["core_item_ids"] = list(overlay["eligible_item_ids"])
    overlay["base_path_item_ids"] = list(overlay["eligible_item_ids"])
    overlay["adaptive_item_ids"] = []
    overlay["selection_mode"] = "stage_playable_overlay"
    overlay["learning_path_id"] = f"{stage_id}-today-three-v1"
    overlay["source_product_version"] = FORMAL_PRODUCT_VERSION
    overlay.pop("selection_sha256", None)
    overlay["selection_sha256"] = digest_bytes(canonical(overlay))
    _, _, expansion = _extract_assignment(source, "CONTENT_EXPANSION", "LEARNING_PATH")
    expansion["items"] = deepcopy(items)
    expansion["families"] = [
        {"family_id": family_id, "label": next(item["family_name"] for item in items if item["family_id"] == family_id)}
        for family_id in dict.fromkeys(item["family_id"] for item in items)
    ]
    expansion["scope"] = {**dict(expansion.get("scope", {})), "effective_item_count": len(items)}
    source = _replace_assignment(source, "CONTENT_EXPANSION", "LEARNING_PATH", expansion)
    _, _, path = _extract_last_assignment(source, "LEARNING_PATH")
    path["path_id"] = overlay["learning_path_id"]
    path["title"] = "今天三站"
    path["daily_item_count"] = 3
    path["active_day_count"] = 14
    path["days"] = _stage_learning_days(items, stage_id)
    adaptive = path.get("adaptive_follow_up") or {}
    adaptive["atom_role_items"] = {}
    adaptive["role_items"] = {}
    path["adaptive_follow_up"] = adaptive
    source = _replace_last_assignment(source, "LEARNING_PATH", path)
    return source, overlay


def _compact_subset_days(path: dict[str, Any], item_ids: list[str]) -> int:
    """把子集路线压紧为 14 个稳定学习日，并保证每条已选基础内容至少自然出现一次。"""
    slot_by_id = {
        slot["item_id"]: deepcopy(slot)
        for day in path["days"]
        for slot in day.get("slots", [])
    }
    families = {slot_by_id[item_id]["family_id"] for item_id in item_ids}
    daily_count = min(3, len(item_ids), len(families))
    remaining = list(item_ids)
    rotation = list(item_ids)
    fill_cursor = 0
    for day in path["days"]:
        chosen: list[str] = []
        chosen_families: set[str] = set()
        scan = 0
        while remaining and len(chosen) < daily_count and scan < len(remaining):
            item_id = remaining[scan]
            family_id = slot_by_id[item_id]["family_id"]
            if family_id in chosen_families:
                scan += 1
                continue
            chosen.append(item_id)
            chosen_families.add(family_id)
            remaining.pop(scan)
            scan = 0
        while len(chosen) < daily_count:
            for _ in range(len(rotation)):
                item_id = rotation[fill_cursor % len(rotation)]
                fill_cursor += 1
                family_id = slot_by_id[item_id]["family_id"]
                if item_id not in chosen and family_id not in chosen_families:
                    chosen.append(item_id)
                    chosen_families.add(family_id)
                    break
            else:
                raise ContractError("子集路线无法保持同日题目与内容家族唯一")
        day["slots"] = [deepcopy(slot_by_id[item_id]) for item_id in chosen]
        day.pop("selection_rule", None)
    if remaining:
        raise ContractError(f"14 日子集路线仍有 {len(remaining)} 条基础内容不可达")
    return daily_count


def _filter_formal_sources(source: str, selection: dict[str, Any]) -> str:
    """按构建期 atom 选择裁剪内嵌目录、扩展包和路线；默认八 atom 保持原始 14 日路径。"""
    selected_atoms = set(selection["selected_atom_ids"])
    eligible = set(selection["eligible_item_ids"])
    _, _, catalog = _extract_assignment(source, "CONTENT_CATALOG", "CONTENT_EXPANSION")
    filtered_atoms = []
    for raw_atom in catalog["atoms"]:
        if raw_atom["atom_id"] not in selected_atoms:
            continue
        atom = deepcopy(raw_atom)
        atom["practice"]["items"] = [item for item in atom["practice"]["items"] if item["item_id"] in eligible]
        filtered_atoms.append(atom)
    catalog["atoms"] = filtered_atoms
    catalog["candidate_backlog"] = []
    source = _replace_assignment(source, "CONTENT_CATALOG", "CONTENT_EXPANSION", catalog)

    _, _, expansion = _extract_assignment(source, "CONTENT_EXPANSION", "LEARNING_PATH")
    expansion["items"] = [item for item in expansion["items"] if item["item_id"] in eligible]
    family_ids = {item["family_id"] for item in expansion["items"]}
    expansion["families"] = [
        row for row in expansion.get("families", [])
        if (row.get("family_id") if isinstance(row, dict) else row) in family_ids
    ]
    expansion["scope"] = {**dict(expansion.get("scope", {})), "effective_item_count": len(expansion["items"])}
    source = _replace_assignment(source, "CONTENT_EXPANSION", "LEARNING_PATH", expansion)

    _, _, path = _extract_last_assignment(source, "LEARNING_PATH")
    path["path_id"] = selection["learning_path_id"]
    for day in path["days"]:
        day["slots"] = [slot for slot in day.get("slots", []) if slot["item_id"] in eligible]
    if selected_atoms != set(DEFAULT_ATOM_IDS):
        pool = [item_id for item_id in selection["base_path_item_ids"] if item_id in eligible]
        if not pool:
            raise ContractError("选择后的学习路线没有可用正式内容")
        path["daily_item_count"] = _compact_subset_days(path, pool)
    adaptive = path["adaptive_follow_up"]
    adaptive["atom_role_items"] = {
        atom_id: {
            role: [item_id for item_id in ids if item_id in eligible]
            for role, ids in roles.items()
        }
        for atom_id, roles in adaptive["atom_role_items"].items()
        if atom_id in selected_atoms
    }
    adaptive["role_items"] = {
        role: [item_id for item_id in ids if item_id in eligible]
        for role, ids in adaptive["role_items"].items()
    }
    if selected_atoms == set(DEFAULT_ATOM_IDS):
        path["daily_item_count"] = 3
    return _replace_last_assignment(source, "LEARNING_PATH", path)


def _nav_html(
    selected_subjects: set[str],
    selected_module_ids: set[str],
    eligible_item_ids: set[str],
    overlay: bool = False,
) -> str:
    """保持左侧多 Tab 常驻，但把儿童、支持与成人入口分组。"""
    learn_group = "去玩" if overlay else "学习"
    rows: list[tuple[str, str, str, str, bool]] = [
        ("home", "今天", "🏡", "", True),
        ("数学", "数学", "🔢", learn_group, "数学" in selected_subjects),
        ("语文", "语言", "✏️", learn_group, "语文" in selected_subjects),
        ("英语", "英语", "🔤", learn_group, "英语" in selected_subjects),
        ("阅读", "阅读", "📖", learn_group, "阅读" in selected_subjects),
        ("repair", "换个办法", "🧩", "轻松探索", "education-errors" in selected_module_ids),
        (
            "science",
            "观察",
            "🔍",
            "轻松探索",
            "education-explore" in selected_module_ids
            and (
                bool(eligible_item_ids.intersection(SCIENCE_ITEM_IDS))
                or any("explore" in item_id for item_id in eligible_item_ids)
            ),
        ),
        ("movement", "动一动", "🤸", "轻松探索", "education-movement" in selected_module_ids),
        ("collect", "小卖部", "⭐", "轻松探索", "education-rewards" in selected_module_ids),
        ("parent", "家长区", "👨‍👩‍👧", "成人", "education-parent" in selected_module_ids),
    ]
    groups: list[str] = []
    current_group: str | None = None
    for view, label, emoji, group, enabled in rows:
        if not enabled:
            continue
        if group != current_group:
            if current_group is not None:
                groups.append("    </div>")
            group_class = " nav-group-adult" if group == "成人" else ""
            groups.append(f'    <div class="nav-group{group_class}">')
            if group:
                groups.append(f'      <span class="nav-group-label">{group}</span>')
            current_group = group
        adult_attr = ' data-adult-entry="true"' if view == "parent" else ""
        groups.append(
            f'      <button class="nav-btn" data-view="{view}"{adult_attr}>'
            f'<span class="nav-icon nav-emoji" data-nav-emoji="{emoji}" aria-hidden="true">{emoji}</span>'
            f'<span class="nav-label">{label}</span></button>'
        )
    if current_group is not None:
        groups.append("    </div>")
    buttons = "\n".join(groups)
    return (
        '<nav class="rail" aria-label="主要导航">\n'
        f'    <div class="brand" aria-label="小花园"><span class="brand-mark brand-emoji" aria-hidden="true">🌱</span><span><strong>小花园</strong><small>{"我的房间" if overlay else "学习工作台"}</small></span></div>\n'
        '    <button type="button" class="star-box" data-star-box data-view="collect" hidden>⭐ <b data-star-count>0</b></button>\n'
        f"{buttons}\n"
        "  </nav>"
    )


_CSS = r"""
<style data-child-playground-style>
:root{--ink:#382d43;--muted:#5f5667;--paper:#fffaf4;--panel:#fffefa;--green:#247b63;--green-2:#d9f3e8;--gold:#f4bb3c;--danger:#b94a43;--line:#eadfe7;--coral:#b52c51;--coral-2:#a7433d;--pink-rail:#ffe7ef;--blue-soft:#dff0ff;--mint-soft:#dcf6e9;--violet-soft:#ebe2ff;--yellow-soft:#fff0bb;--rail-line:#f3d7e1;--nav-active:#ffd0dc;--hero-sky:#bfe9ff;--brand-small:#8c4860;--shadow:0 16px 38px rgba(78,52,82,.12);--radius:22px}
.app[data-room="garden"]{--paper:#fffaf4;--panel:#fffefa;--pink-rail:#ffe7ef;--green:#247b63;--green-2:#d9f3e8;--line:#eadfe7;--coral:#b52c51;--rail-line:#f3d7e1;--nav-active:#ffd0dc;--hero-sky:#bfe9ff;--brand-small:#8c4860}
.app[data-room="bamboo"]{--paper:#f4f8ef;--panel:#fbfef6;--pink-rail:#e4f0d8;--green:#3d6b3a;--green-2:#e4f3d8;--line:#d5e4c8;--coral:#5a7a3a;--rail-line:#c9ddb4;--nav-active:#c8e0a8;--hero-sky:#cfe8c4;--brand-small:#4a6b38}
.app[data-room="greenhouse"]{--paper:#f6fbf4;--panel:#fbfff8;--pink-rail:#e8f6e4;--green:#2d7a4a;--green-2:#e0f4d8;--line:#d4e8c8;--coral:#c46a3d;--rail-line:#c5ddb8;--nav-active:#c8e8b8;--hero-sky:#d4edc8;--brand-small:#3d6b3a}
.app[data-room="dusk"]{--paper:#fff6ef;--panel:#fffaf4;--pink-rail:#ffe4d0;--green:#c45d4a;--green-2:#ffe8d6;--line:#f0d4c0;--coral:#c43d5a;--rail-line:#f3d0b8;--nav-active:#ffd0b0;--hero-sky:#ffc89a;--brand-small:#8c4860}
.app[data-room="bamboo"] .home-encourage,.app[data-room="bamboo"] .companion-card[data-companion-mood="waiting"]{background:#eef6e4}
.app[data-room="greenhouse"] .home-encourage,.app[data-room="greenhouse"] .companion-card[data-companion-mood="waiting"]{background:#eef8ea}
.app[data-room="dusk"] .home-encourage,.app[data-room="dusk"] .companion-card[data-companion-mood="waiting"]{background:#fff0e4}
.app[data-room="bamboo"] .world-heading{background:#e4f0d4}
.app[data-room="greenhouse"] .world-heading{background:#dcefd4}
.app[data-room="dusk"] .world-heading{background:#ffe4d4}
.stage-chip{display:inline-block;margin:8px 0 0;padding:4px 10px;border-radius:999px;background:#fff3c4;color:#6a5414;font-size:13px;font-weight:850}
.app[data-stage-face="picture-book"] .home-greeting h1{font-size:clamp(32px,4vw,46px)}
.app[data-stage-face="picture-book"] .today-stop h3{font-size:20px}
.app[data-stage-face="picture-book"] .today-stop p{font-size:15px}
.app[data-stage-face="bamboo-read"] .home-greeting h1{color:#3d6b3a}
.app[data-stage-face="dusk-compare"] .home-greeting h1{color:#c45d4a}
html,body{background:var(--paper)}
.app{display:grid;grid-template-columns:220px minmax(0,1fr);min-height:100dvh;background:var(--paper)}
.rail{position:sticky;top:0;height:100dvh;overflow-y:auto;display:flex;flex-direction:column;gap:4px;padding:18px 14px;background:var(--pink-rail);color:var(--ink);border-right:1px solid var(--rail-line);z-index:5}
.brand{display:grid;grid-template-columns:46px minmax(0,1fr);align-items:center;gap:10px;padding:4px 8px 10px}.brand-mark{width:42px;height:42px;display:grid;place-items:center;border-radius:14px;background:#fff;box-shadow:0 7px 18px rgba(78,52,82,.12)}.brand-emoji{font-size:27px}.brand strong,.brand small{display:block}.brand strong{font-size:19px}.brand small{margin-top:2px;color:var(--brand-small);font-size:12px;font-weight:850}.star-box{display:flex;align-items:center;justify-content:center;gap:4px;margin:0 8px 12px;padding:7px 12px;border:0;border-radius:16px;background:#fff;box-shadow:0 3px 10px rgba(100,60,120,.08);color:#e8a200;font-weight:900}.star-box[hidden]{display:none}.reward-hud{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.reward-hud .star-box{margin:0}.companion-chip{min-height:36px;padding:4px 10px;border:0;border-radius:999px;background:#fff7e4;font-size:18px}.companion-card{display:grid;grid-template-columns:132px minmax(0,1fr);gap:12px;align-items:center;margin:10px 0 0;padding:10px 14px;border-radius:18px;background:#fff;box-shadow:var(--shadow)}.companion-card[data-companion-mood="waiting"]{background:#fff6ea}.companion-card[data-companion-mood="well"]{background:#eef9f1}.companion-emoji{position:relative;width:132px;height:132px;display:grid;place-items:center;border-radius:20px;background:#fff3c4;font-size:28px;overflow:hidden;padding:0}.visit-plots{position:absolute;left:6px;right:6px;bottom:6px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;z-index:1}.visit-plot{height:22px;border-radius:8px;display:grid;place-items:center;background:rgba(255,255,255,.92);font-size:14px;line-height:1}.visit-plot[data-garden-state="empty"]{opacity:.4}.visit-copy{display:block;margin:2px 0 4px;color:#6a5414;font-size:12px;font-weight:850}.companion-portrait{width:100%;height:100%;object-fit:contain;background:#fff8ec;display:block}.companion-chip .companion-portrait{width:32px;height:32px;border-radius:50%}.companion-copy span{display:block;color:#8c4860;font-size:12px;font-weight:850}.companion-copy strong{display:block;margin:4px 0 6px;font-size:20px}.companion-copy p{margin:0 0 10px;color:var(--muted);font-size:13px}.companion-copy .primary{min-height:40px;padding:8px 14px}.companion-done{margin:0;font-weight:850;color:#317048}.stage-teach{margin:16px 0 0;padding:20px 22px;border-radius:24px;background:#fff;box-shadow:var(--shadow);display:grid;gap:12px}.stage-teach .teach-kicker{color:#8c4860;font-size:12px;font-weight:850}.stage-teach h2{margin:0;font-size:clamp(22px,3vw,32px)}.stage-teach .teach-story{margin:0;font-size:17px;font-weight:750;line-height:1.45}.stage-teach .teach-how{margin:0;padding:12px 14px;border-radius:16px;background:var(--yellow-soft)}.stage-teach .teach-together{margin:0;color:#8c4860;font-weight:850}.stage-teach .primary{justify-self:start;min-height:48px}.tonight-rail{margin-top:14px;padding:14px 16px;border-radius:18px;background:#fff;box-shadow:var(--shadow)}.tonight-rail p{margin:0 0 8px;color:#8c4860;font-size:12px;font-weight:850}.tonight-rail div{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.tonight-rail button{min-height:52px;padding:8px 10px;border:1px solid var(--line);border-radius:14px;background:#fff;text-align:left;display:flex;align-items:center;gap:8px;font-weight:850}.tonight-rail button.current{border-color:var(--green);background:var(--mint-soft)}.tonight-rail b{width:22px;height:22px;display:grid;place-items:center;border-radius:50%;background:var(--yellow-soft);font-size:12px}.home-boost{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:12px;margin-top:12px}.home-encourage,.home-achieve{padding:16px 18px;border-radius:20px;display:grid;gap:8px}.home-encourage{background:#fff6ea}.home-achieve{background:#fff;box-shadow:var(--shadow)}.home-encourage strong,.home-achieve .teach-kicker{display:block}.home-encourage p,.home-achieve p{margin:0;color:var(--muted)}.achieve-row{display:flex;flex-wrap:wrap;gap:8px}.achieve-chip{min-height:36px;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:#fff;font-weight:850}.achieve-goal{display:grid;gap:6px}.achieve-next{font-size:13px;font-weight:850}.achieve-recent{display:flex;gap:8px;font-size:26px}.companion-skin-list{display:grid;gap:8px;margin-top:12px}.companion-skin-list button{min-height:44px}.feedback.warm-incorrect{background:#fff6ea;border-color:#f0d2a8}.feedback.warm-incorrect p{margin:6px 0 0}.feedback.warm-incorrect .warm-next{font-weight:850;color:#6a5414}.companion-growth{display:inline-block;margin-top:4px;padding:2px 8px;border-radius:999px;background:#fff3c4;color:#6a5414;font-size:12px;font-weight:850}.garden-strip{margin:4px 0 0;padding:12px 16px;border-radius:18px;background:#f3faf4}.garden-strip p{margin:0 0 8px;color:#5b6b5e;font-size:12px;font-weight:850}.garden-plots{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px}.garden-plot{min-height:44px;border-radius:12px;display:grid;place-items:center;font-size:22px;background:#fff}.garden-plot[data-garden-state="empty"]{opacity:.45}.topline{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}
.nav-group{display:grid;gap:4px}.nav-group+.nav-group{margin-top:10px}.nav-group-adult{margin-top:auto;padding-top:10px;border-top:1px solid rgba(165,85,112,.18)}.nav-group-label{padding:0 10px 3px;color:#94556b;font-size:11px;font-weight:950;letter-spacing:.12em}
.nav-btn{width:100%;min-height:52px;padding:7px 10px;display:flex;align-items:center;gap:10px;border:0;border-radius:15px;color:#4f4057;background:transparent;font-size:15px;font-weight:900;text-align:left;white-space:nowrap}
.nav-icon{width:34px;height:34px;display:grid;place-items:center;flex:none;border-radius:11px;background:#fff;box-shadow:0 4px 10px rgba(78,52,82,.09);line-height:1}.nav-emoji{font-size:22px;line-height:1}.nav-btn:hover{background:rgba(255,255,255,.72)}.nav-btn.active{background:var(--nav-active);color:#382d43;box-shadow:inset 0 0 0 2px rgba(255,93,130,.24)}.nav-btn.active .nav-icon{box-shadow:none}.nav-label{overflow:hidden;text-overflow:ellipsis}
.main{min-width:0;padding:24px 28px 52px}.shell{max-width:1220px;margin:0 auto}.topline{margin-bottom:16px}
.playground-home{display:grid;gap:18px}.home-greeting{display:flex;align-items:center;justify-content:space-between;gap:16px}.home-greeting h1{margin:0;font-size:clamp(26px,3vw,38px)}.home-greeting p{margin:6px 0 0;color:var(--muted);font-weight:750}.home-stats{display:flex;gap:10px}.home-stat{min-width:108px;padding:12px 14px;border-radius:16px;background:#fff}.home-stat span,.home-stat strong{display:block}.home-stat span{color:#625968;font-size:12px}.home-stat strong{margin-top:3px;font-size:21px}
.playground-hero{position:relative;min-height:280px;padding:0;border-radius:28px;overflow:hidden;background:var(--hero-sky) var(--playground-hero) center 58%/cover no-repeat;box-shadow:var(--shadow)}.playground-hero.home-stage{min-height:92px;max-height:110px}.room-label{position:absolute;left:16px;top:14px;margin:0;padding:8px 14px;border-radius:999px;background:rgba(255,254,250,.94);color:var(--ink);font-size:16px;font-weight:900}.hero-copy{display:none}
.option.is-picture{display:grid;gap:6px;justify-items:center;align-content:center;min-height:188px;padding:14px 10px;overflow:hidden;container-type:inline-size}.option-picture{font-size:96px;line-height:1;max-width:100%}.option-letter{display:flex;align-items:center;justify-content:center;max-width:100%;overflow:hidden;font-size:clamp(56px,42cqi,136px);font-weight:900;letter-spacing:.02em;line-height:1.05;text-align:center;word-break:keep-all}.option-letter[data-letter-len="1"]{font-size:clamp(80px,68cqi,168px)}.option-letter[data-letter-len="2"]{font-size:clamp(44px,34cqi,96px)}.option-letter[data-letter-len="3"],.option-letter[data-letter-len="4"]{font-size:clamp(32px,24cqi,72px)}.option-label{font-size:24px;font-weight:850}.visual-option .visual-emoji,.option .visual-emoji{font-size:88px;line-height:1}.same-type-more{margin:0 0 8px;color:#8c4860;font-weight:850}.same-type-group{margin:16px 0 8px;padding:14px 16px;border-radius:18px;background:#fff;box-shadow:var(--shadow)}.same-type-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.same-type-entry{min-height:52px;padding:8px 10px;border:1px solid var(--line);border-radius:14px;background:#fff;text-align:left;display:flex;align-items:center;gap:8px;font-weight:850}.same-type-entry.current{border-color:var(--green);background:var(--mint-soft)}.same-type-entry b{width:22px;height:22px;flex:none;display:grid;place-items:center;border-radius:50%;background:var(--yellow-soft);font-size:12px}.same-type-entry span{min-width:0}.same-type-entry i{margin-left:auto;font-style:normal;font-size:12px;font-weight:850;color:var(--muted)}.same-type-group>.primary{margin-top:10px}.same-type-progress{margin:0 0 10px;color:#8c4860;font-size:15px;font-weight:900;letter-spacing:.04em}
.today-board{padding:22px;border-radius:24px;background:#fff;box-shadow:var(--shadow)}.today-board-head{display:flex;justify-content:space-between;align-items:end;gap:16px}.today-board-head h2{margin:0}.today-board-head p{margin:5px 0 0;color:var(--muted)}.today-route{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}.today-stop{position:relative;min-height:190px;padding:17px;border:1px solid var(--line);border-radius:19px;background:var(--panel);display:flex;flex-direction:column}.today-stop.done{background:var(--mint-soft)}.today-stop.now{box-shadow:0 0 0 2px rgba(36,123,99,.35)}.today-stop .stop-number{position:absolute;right:13px;top:13px;width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:var(--yellow-soft);font-weight:950}.task-visual{width:72px;height:72px;display:grid;place-items:center;border-radius:20px;background:#fff5cf;font-size:52px;line-height:1}.task-visual .learning-object{width:56px;height:56px}.task-visual .learning-object-emoji{font-size:52px;line-height:1}.today-stop h3{margin:12px 0 6px}.today-stop p{margin:0 0 14px;color:var(--muted);font-size:14px}.today-stop button{margin-top:auto;width:100%}
.world-heading{display:grid;grid-template-columns:minmax(0,1fr) 96px;align-items:center;gap:18px;padding:22px 24px;border-radius:24px;background:#ffe0e8}.world-heading.math{background:var(--violet-soft)}.world-heading.english{background:var(--blue-soft)}.world-heading.reading{background:var(--mint-soft)}.world-heading.science{background:#ccf0e4}.world-heading.movement{background:var(--yellow-soft)}.world-heading h1{margin:0;font-size:clamp(28px,3vw,40px)}.world-heading p{max-width:58ch;margin:7px 0 0;color:var(--muted);font-weight:720}.world-heading-art{width:86px;height:86px;display:grid;place-items:center;border-radius:24px;background:rgba(255,255,255,.72)}.world-heading-art .learning-object{width:68px;height:68px}
.world-mode-tabs{display:flex;gap:8px;margin:16px 0 0;padding:5px;border-radius:16px;background:#fff;box-shadow:var(--shadow)}.world-mode-tab{flex:1;min-height:44px;border:0;border-radius:12px;background:transparent;color:var(--muted);font-size:14px;font-weight:900}.world-mode-tab.active{background:var(--green);color:#fff}
.order-slots{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}.order-slot{min-width:52px;min-height:48px;padding:8px 12px;border:2px dashed #d7c6d4;border-radius:14px;background:#fff;font-weight:900;text-align:center}.order-slot.active{border-style:solid;border-color:var(--green);background:#e8f7f0;box-shadow:0 0 0 3px rgba(36,123,99,.16)}.order-slot.done{border-style:solid;border-color:#91bcae;background:#f4fbf7}.order-slot-sep{color:#c9b7c4;font-weight:900}.family-checkins{display:grid;gap:8px;margin-top:16px}.family-checkin{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:52px;padding:12px 14px;border-radius:14px;background:#fff}.family-checkin.done{background:#e4f5ec}
.fact-calendar{margin-top:18px;padding:18px;border-radius:22px;background:#fff;box-shadow:var(--shadow)}.cal-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.calendar{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}.cal-head{text-align:center;font-size:11px;color:var(--muted);font-weight:900;padding:4px 0}.cal-day{aspect-ratio:1;border-radius:10px;display:grid;place-items:center;font-size:13px;font-weight:850;background:#f6f1fb;color:#8b7ea0}.cal-day.empty{background:transparent}.cal-day.part{background:var(--yellow-soft);color:#6a5414}.cal-day.full{background:var(--green);color:#fff}.cal-day.today{box-shadow:0 0 0 2.5px var(--coral)}button.cal-day{border:0;padding:0;cursor:pointer;font:inherit}.cal-day.picked{outline:2px solid var(--ink)}.cal-legend{display:flex;gap:14px;justify-content:center;margin-top:10px;font-size:11px;color:var(--muted)}.cal-legend span:nth-child(1)::before{content:"";display:inline-block;width:9px;height:9px;margin-right:5px;border-radius:3px;background:var(--yellow-soft);vertical-align:middle}.cal-legend span:nth-child(2)::before{content:"";display:inline-block;width:9px;height:9px;margin-right:5px;border-radius:3px;background:var(--green);vertical-align:middle}.cal-legend span:nth-child(3)::before{content:"";display:inline-block;width:9px;height:9px;margin-right:5px;border-radius:3px;box-shadow:0 0 0 2px var(--coral);vertical-align:middle}.cal-summary{margin:8px 0 0;text-align:center;color:var(--muted);font-size:13px;font-weight:750}
.world-primary{margin-top:18px;padding:18px;border-radius:22px;background:#fff}.world-primary h2{margin:0 0 12px}.world-primary>.content-card,.world-primary>.card{min-height:190px}.world-more{margin-top:22px}.compact-head{display:flex;justify-content:space-between;align-items:end;gap:14px}.compact-head h2{margin:0}.compact-head p{margin:5px 0 0;color:var(--muted)}.world-more .content-grid,.content-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.more-content{margin-top:14px;padding:14px;border:1px solid var(--line);border-radius:18px;background:#fff}.more-content summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:950}.more-content .content-grid{margin-top:12px}
.repair-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}.repair-grid.count-1{grid-template-columns:minmax(0,650px)}.repair-grid .content-card{min-height:210px;padding:20px}.compact-empty{padding:28px;border-radius:20px;background:#fff;color:var(--muted);text-align:center}
.movement-player{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:18px;align-items:center;margin-top:18px;padding:22px;border-radius:24px;background:var(--yellow-soft)}.movement-player h2{margin:0}.movement-player p{color:#625968}.movement-clock{font-size:46px;font-weight:950}.movement-controls{display:flex;gap:10px;flex-wrap:wrap}.movement-figure{width:100%;aspect-ratio:1;display:grid;place-items:center;border-radius:22px;background:#fff}.movement-figure-emoji{font-size:78px}.support-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}.support-action{min-height:124px;padding:16px;border:1px solid var(--line);border-radius:18px;background:#fff;text-align:left;display:grid;grid-template-columns:52px minmax(0,1fr);gap:12px;align-items:center}.support-action.done{background:#e4f5ec}.support-action-emoji{font-size:34px;text-align:center}.support-action strong,.support-action span{display:block}.support-action strong{font-size:18px}.support-action span{margin-top:7px;color:var(--muted)}
.learning-object{width:46px;height:46px;object-fit:contain;vertical-align:middle}.learning-object-emoji{display:inline-grid;place-items:center;width:auto;height:auto;font-size:1em;line-height:1}.content-hero{display:flex;align-items:center;min-height:64px;margin:2px 0 10px;font-size:56px;line-height:1}.content-hero .learning-object{width:56px;height:56px}.content-hero.is-picture{justify-content:flex-start;min-height:132px;margin:6px 0 16px;font-size:108px}.content-hero.is-picture .learning-object,.content-hero.is-picture .learning-object-emoji{width:108px;height:108px;font-size:108px}.content-card{position:relative}.content-card-visual{float:right;width:58px;height:58px;margin:0 0 8px 12px;display:grid;place-items:center;border-radius:16px;background:#fff5cf;font-size:42px}.content-card-visual .learning-object{width:46px;height:46px}.content-card-visual .learning-object-emoji{font-size:42px}.content-object-row{display:flex!important;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;font-size:76px;line-height:1}.content-object-row .learning-object,.content-stimulus .learning-object{width:76px;height:76px}.content-object-row .learning-object-emoji,.content-stimulus .learning-object-emoji{font-size:76px;line-height:1}.visual-object{min-width:72px;min-height:72px;padding:4px;border:2px solid transparent;border-radius:14px;background:#fff;display:inline-grid;place-items:center;font-size:64px}.visual-object[aria-pressed="true"]{border-color:var(--green);background:var(--green-2);transform:translateY(-2px)}.count-progress{margin:10px 0 0;text-align:center;color:var(--green);font-weight:950}.kid-step-number{width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:var(--yellow-soft);font-weight:950}
.reward-balance{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:18px 0;padding:20px 22px;border-radius:22px;background:linear-gradient(135deg,#fff0b8,#ffe1a4);box-shadow:var(--shadow)}.reward-balance-copy span,.reward-balance-copy strong{display:block}.reward-balance-copy span{color:#67543b;font-weight:850}.reward-balance-copy strong{margin-top:4px;font-size:34px}.reward-balance-icon{font-size:56px;filter:drop-shadow(0 7px 8px rgba(134,88,20,.18))}.reward-goal{display:grid;grid-template-columns:92px minmax(0,1fr);gap:20px;align-items:center;margin-top:16px;padding:22px;border-radius:23px;background:#fff;box-shadow:var(--shadow)}.reward-goal-icon{width:86px;height:86px;display:grid;place-items:center;border-radius:24px;background:var(--violet-soft);font-size:48px}.reward-goal h2{margin:3px 0 7px}.reward-goal p{margin:0;color:var(--muted)}.reward-progress{height:13px;margin:14px 0 8px;overflow:hidden;border-radius:999px;background:#eee7f0}.reward-progress>span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--coral),var(--gold))}.reward-goal-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}.reward-shop-head{margin-top:26px}.reward-shop{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}.reward-item{position:relative;padding:16px;border:2px solid transparent;border-radius:18px;background:#fff;text-align:left}.reward-item.selected{border-color:var(--coral);background:#fff7fa}.reward-item-icon{width:54px;height:54px;display:grid;place-items:center;margin-bottom:10px;border-radius:17px;background:var(--yellow-soft);font-size:31px}.reward-item strong,.reward-item span{display:block}.reward-item span{margin-top:5px;color:var(--muted);font-size:14px;font-weight:850}.reward-item button{width:100%;margin-top:12px}.reward-more{margin-top:14px;padding:14px;border:1px solid var(--line);border-radius:18px;background:#fff}.reward-more summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:900}.reward-history{display:grid;gap:8px;margin-top:14px}.reward-history-row{display:flex;justify-content:space-between;gap:12px;padding:13px 15px;border-radius:14px;background:#fff}.reward-history-row span{color:var(--muted)}.reward-confirm-panel{position:fixed;inset:0;z-index:30;display:grid;place-items:center;padding:20px;background:rgba(56,45,67,.48);backdrop-filter:blur(5px)}.reward-confirm-card{width:min(470px,100%);padding:24px;border-radius:24px;background:#fff;box-shadow:0 24px 70px rgba(50,33,55,.28)}.reward-confirm-icon{font-size:54px}.reward-confirm-card h2{margin:10px 0 8px}.reward-confirm-card p{color:var(--muted)}.reward-confirm-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.collect-tabs{display:flex;gap:8px;margin:14px 0 4px;padding:5px;border-radius:16px;background:#fff;box-shadow:var(--shadow)}.collect-tab{flex:1;min-height:44px;border:0;border-radius:12px;background:transparent;color:var(--muted);font-weight:900}.collect-tab.active{background:var(--green);color:#fff}.chip-row{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}.chip{min-height:36px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:#fff;font-weight:850}.chip.active{background:var(--coral);border-color:var(--coral);color:#fff}.badge-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:10px;margin-top:14px}.badge-card{padding:14px 10px;border-radius:18px;background:#fff;text-align:center;box-shadow:var(--shadow);opacity:.55}.badge-card.unlocked{opacity:1;border:2px solid var(--gold)}.badge-emoji{font-size:34px}.badge-card strong,.badge-card span{display:block}.badge-card span{margin-top:4px;color:var(--muted);font-size:12px}.badge-progress{height:7px;margin:8px 0 4px;overflow:hidden;border-radius:999px;background:#eee7f0}.badge-progress>i{display:block;height:100%;background:var(--coral)}.badge-pct{font-size:11px;color:var(--muted);font-weight:850}.combo-pill{display:inline-block;margin-left:8px;padding:3px 10px;border-radius:999px;background:#fff0e0;color:#d97a2b;font-size:12px;font-weight:900}.star-burst{position:fixed;inset:0;z-index:40;pointer-events:none}.star-burst span{position:absolute;left:50%;top:42%;font-size:22px;animation:starFall .9s ease-out forwards}@keyframes starFall{to{transform:translate(var(--x),var(--y));opacity:0}}
.parent-sections{display:grid;gap:12px;margin-top:18px}.parent-sections>details{padding:14px 16px;border:1px solid var(--line);border-radius:18px;background:#fff}.parent-sections>details>summary{min-height:48px;display:flex;align-items:center;cursor:pointer;font-size:17px;font-weight:950}.parent-sections>details[open]>summary{margin-bottom:14px}.parent-detail-body{min-width:0}.parent-detail-body>.parent-path{margin:0}.parent-tool{padding:0}.parent-tool h3{margin-top:0}.parent-tool .data-actions{margin-top:12px}.custom-task-form{display:grid;gap:10px;margin-top:14px}.custom-task-form label{display:grid;gap:5px;color:var(--muted);font-size:13px;font-weight:850}.custom-task-form input,.custom-task-form textarea{width:100%;min-height:46px}.custom-task-list{display:grid;gap:7px;margin-top:12px}.custom-task-row{padding:10px 12px;border-radius:12px;background:#fff8eb;display:flex;align-items:center;justify-content:space-between;gap:10px}.custom-task-row small{display:block;margin-top:3px}.mini{min-height:38px;padding:7px 10px}.parent-reward-stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.parent-reward-stats span{padding:6px 10px;border-radius:999px;background:#fff8eb;font-size:13px;font-weight:850}.legacy-note{margin-top:12px;padding:12px;border-radius:14px;background:#f6f0ff;color:#645a78}
[data-double6-reward-module-enabled="false"] .reward-manager{display:none}.content-card,.card,.practice,.lesson-title,.parent-path,.review{border-color:var(--line);box-shadow:none}.content-card{border-radius:18px}.primary{background:var(--green)}.secondary{color:var(--green);border-color:#91bcae}.content-stimulus,.kid-demo{background:#fff8d8}.garden,.library-invite{display:none}
button{transition:transform .14s ease,box-shadow .14s ease,background-color .14s ease}button:active{transform:scale(.985)}button:focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible{outline:4px solid rgba(36,123,99,.28);outline-offset:3px}
@media(max-width:980px){.app{grid-template-columns:172px minmax(0,1fr)}.rail{padding:16px 10px}.brand{grid-template-columns:38px minmax(0,1fr);padding-inline:5px}.brand-mark{width:36px;height:36px}.nav-btn{padding-inline:7px}.main{padding:18px}.reward-shop{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:820px){.app{grid-template-columns:90px minmax(0,1fr)}.rail{position:sticky;inset:auto;width:auto;height:100dvh;padding:10px 7px;display:flex;overflow-y:auto;border:0;border-right:1px solid var(--rail-line);border-radius:0;background:var(--pink-rail)}.brand{display:grid;grid-template-columns:1fr;padding:0 0 10px;justify-items:center}.brand>span:last-child{display:none}.brand-mark{width:38px;height:38px}.nav-group-label{padding:0;text-align:center;font-size:10px;letter-spacing:.04em}.nav-btn{min-height:60px;padding:5px 3px;display:grid;grid-template-columns:1fr;justify-items:center;align-content:center;gap:3px;border-radius:13px;font-size:12px;line-height:1.1;text-align:center;white-space:normal}.nav-icon{width:30px;height:30px}.nav-emoji{font-size:20px}.nav-label{display:block;overflow:visible;text-overflow:clip}.main{padding:14px 12px 34px}.home-greeting{display:block}.home-stats{margin-top:12px}.playground-hero{min-height:168px;padding:0;border-radius:22px}.playground-hero.home-stage{min-height:72px;max-height:88px;padding:0;border-radius:22px}.room-label{left:12px;top:10px;padding:4px 10px;font-size:12px}.hero-copy{left:12px;top:12px;width:calc(100% - 24px);padding:15px}.hero-copy h2{font-size:25px}.hero-copy p{font-size:14px}.today-board{padding:15px}.today-board-head{display:block}.world-more .content-grid,.content-grid,.repair-grid,.repair-grid.count-1{grid-template-columns:1fr}.today-route{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.today-stop{min-height:0;padding:10px}.today-stop p{display:none}.today-stop button{min-height:36px;padding:6px;font-size:12px}.home-stats{display:flex;margin-top:8px}.home-stat{min-width:0;padding:8px 10px}.home-stat:not(:first-child){display:none}.tonight-rail div{grid-template-columns:1fr}.same-type-list{grid-template-columns:1fr}.option.is-picture{min-height:148px;padding:10px 8px}.option-letter{font-size:clamp(48px,40cqi,112px)}.option-letter[data-letter-len="1"]{font-size:clamp(64px,62cqi,132px)}.option-letter[data-letter-len="2"]{font-size:clamp(36px,30cqi,72px)}.option-letter[data-letter-len="3"],.option-letter[data-letter-len="4"]{font-size:clamp(28px,22cqi,56px)}.home-boost{grid-template-columns:1fr}.world-heading{grid-template-columns:minmax(0,1fr) 70px;padding:18px}.world-heading-art{width:66px;height:66px;border-radius:19px}.world-heading-art .learning-object{width:54px;height:54px}.content-hero.is-picture{min-height:108px;font-size:88px}.content-hero.is-picture .learning-object,.content-hero.is-picture .learning-object-emoji{width:88px;height:88px;font-size:88px}.content-object-row{font-size:64px}.content-object-row .learning-object,.content-stimulus .learning-object{width:64px;height:64px}.task-visual{width:64px;height:64px;font-size:46px}.compact-head{display:block}.movement-player{grid-template-columns:1fr}.movement-figure{display:none}.support-actions{grid-template-columns:1fr}.reward-shop{grid-template-columns:1fr 1fr}.reward-goal{grid-template-columns:70px minmax(0,1fr);padding:17px;gap:14px}.reward-goal-icon{width:66px;height:66px;font-size:38px}.topline{margin-bottom:12px}}
@media(min-width:760px) and (max-width:899px){.app{grid-template-columns:104px minmax(0,1fr)}.rail{padding-inline:7px}}
@media(max-width:430px){.app{grid-template-columns:82px minmax(0,1fr)}.rail{padding-inline:5px}.nav-btn{font-size:12px}.main{padding:10px 9px 28px}.home-stats{display:flex}.home-stat{min-width:0}.home-stat:not(:first-child){display:none}.reward-shop{grid-template-columns:1fr}.reward-balance{padding:17px}.reward-balance-icon{font-size:44px}.reward-goal{grid-template-columns:1fr}.reward-confirm-actions{grid-template-columns:1fr}.world-heading h1{font-size:25px}.lesson{max-width:100%}.practice{padding:16px 12px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
"""


_HELPERS = r'''
const SUBJECT_COPY={"语文":["语言魔法屋","认字、排句，也把想法说出来。","language"],"数学":["数学闯关岛","数一数、算一算，把方法真正用出来。","math"],"英语":["英语游乐场","把图、单词和生活场景连起来。","english"],"阅读":["故事与诗歌剧场","从故事里找线索，再试着读和说。","reading"]};
const ASSETS=window.CHILD_ASSETS;
const OBJECT_ASSET_BY_TOKEN={"🍎":"apple","🐟":"fish","🌼":"flower","🎾":"ball","🍃":"leaf","🐱":"cat","🐶":"dog","📕":"storybook",apple:"apple",fish:"fish",flower:"flower",ball:"ball",leaf:"leaf",cat:"cat",dog:"dog",book:"storybook",storybook:"storybook"};
const SUBJECT_OBJECT={"语文":"flower","数学":"apple","英语":"cat","阅读":"storybook"};
const FAMILY_OBJECT={count:"apple",add:"apple",subtract:"fish",sentence:"flower",hanzi:"leaf",english:"cat",read:"storybook",aloud:"storybook",class:"ball",sequence:"fish",offscreen:"leaf"};
const MOVEMENT_EMOJIS=["🌳","🐱","🚶","🔄","👀","🙌","🌬️","💧"];
const MOVEMENT_ACTIONS=[
  ["伸展成大树","双脚站稳，手臂慢慢举高，舒服就停。",20],["小猫伸懒腰","扶稳桌边，背部轻轻拱起再放松。",20],
  ["原地点点步","原地交替抬脚，不追求速度。",20],["肩膀画小圈","肩膀向后慢慢画小圈。",20],
  ["看远再看近","看窗外远处，再看手边物品。",20],["手腕转一转","双手自然放松，手腕慢慢转圈。",20],
  ["慢慢深呼吸","吸气、停一下、慢慢呼气。",30],["喝口水休息","坐稳后喝一小口水，准备好了再继续。",20]
];
const FORMAL_IDS=new Set(PRODUCT.recommendation_plan.learning_content_selection.eligible_item_ids);
const SCIENCE_ITEM_IDS=["class-foundation-animal-outlier","class-foundation-fruit-outlier","class-guided-school-things","class-guided-numbers","sequence-transfer-apple-fish","sequence-transfer-moon-star","offscreen-foundation-read","offscreen-foundation-describe-toy","offscreen-guided-sort-books","offscreen-guided-fruit-count","offscreen-transfer-room-sounds","offscreen-transfer-leaves"];
const REWARD_CONTRACT=PRODUCT.reward_economy;
const REWARD_ENABLED=Boolean(PRODUCT.facts.reward_module_enabled);
const STAGE_OVERLAY=Boolean(PRODUCT.facts.stage_playable_overlay);
const STAGE_LESSON=PRODUCT.facts.stage_lesson||{};
const STAGE_FACE=PRODUCT.facts.stage_face||{};
const STAGE_LABEL=(PRODUCT.recommendation_plan&&PRODUCT.recommendation_plan.learning_stage&&PRODUCT.recommendation_plan.learning_stage.label)||"";
const STAGE_HINT="三站就好，答对攒星星，做完可以去左边自由探索。";
function stageHomeTitle(){return STAGE_FACE.home_title||(STAGE_OVERLAY?"今天来玩":(STAGE_LABEL?`今天的${STAGE_LABEL}`:"今天的小花园"))}
function stageCta(done){if(done)return"再玩一次";return STAGE_FACE.cta||STAGE_LESSON.cta||(STAGE_OVERLAY?"去玩":"打开这一站")}
function defaultCompanionSkin(){return STAGE_FACE.default_skin||(REWARD_CONTRACT.companion&&REWARD_CONTRACT.companion.default_skin)||"companion-puppy"}
function companionPortraitPole(mood){return mood==="well"?"well":"waiting"}
function companionPortraitHtml(skinId,mood){const key=String(skinId||"").replace("companion-",""),pole=companionPortraitPole(mood),moods=ASSETS&&ASSETS.companion_moods&&ASSETS.companion_moods[key],src=(moods&&moods[pole])||(ASSETS&&ASSETS.companions&&ASSETS.companions[key]);return src?`<img class="companion-portrait" data-companion-portrait-pole="${pole}" src="${src}" alt="">`:""}
function rewardHud(){if(!REWARD_ENABLED)return"";const stats=rewardStats(),combo=ui.sessionCombo||0,badges=(state.rewards.badges||[]).length,companion=companionVisible()?companionProjection(todayRouteDone(),3):null,face=companion?(companionPortraitHtml(companion.skin_id,companion.mood)||esc(companion.emoji)):"";return `<div class="reward-hud" data-reward-hud><button type="button" class="star-box" data-view="collect">⭐ <b>${stats.balance}</b></button>${companion?`<span class="companion-chip" data-companion-chip aria-hidden="true">${face}</span>`:""}${combo>1?`<span class="combo-pill">🔥 ${combo} 连击</span>`:""}<button type="button" class="chip" data-collect-tab="badge">🏅 ${badges}</button></div>`}
function paintRewardChrome(){const box=document.querySelector("[data-star-box]"),count=document.querySelector("[data-star-count]");if(!box||!count)return;if(!REWARD_ENABLED){box.hidden=true;return}box.hidden=false;count.textContent=String(rewardStats().balance)}
function completedFormalIds(){const done=new Set();Object.values(state.atom_rounds||{}).forEach(round=>Object.entries(round.trials||{}).forEach(([itemId,trial])=>{if(trial.resolved&&FORMAL_IDS.has(itemId))done.add(itemId)}));Object.entries(state.content_items||{}).forEach(([itemId,row])=>{if((row.resolved||row.guardian_confirmed)&&FORMAL_IDS.has(itemId))done.add(itemId)});return done}
function rewardLedger(){return Array.isArray(state.rewards.ledger)?state.rewards.ledger:[]}
function rewardLedgerStars(){return rewardLedger().reduce((sum,row)=>sum+Number(row.stars||0),0)}
function rewardStats(){const first=completedFormalIds().size,extras=rewardLedgerStars(),spent=(state.rewards.redemptions||[]).reduce((sum,row)=>sum+Number(row.cost||0),0),earned=first+Math.max(0,extras);return{first,extras,earned,spent,balance:Math.max(0,first+extras-spent)}}
function postRewardLedger(kind,stars,key,note){if(!REWARD_ENABLED)return null;if(!stars&&kind!=="first_complete")return null;state.rewards.ledger=rewardLedger();if(key&&state.rewards.ledger.some(row=>row.key===key))return null;const row={event_id:`reward-${Date.now()}-${Math.random().toString(36).slice(2,7)}`,kind,stars,key:key||"",note:note||"",affects_mastery:false,at:new Date().toISOString()};state.rewards.ledger.push(row);if(stars){state.history.push({event:"reward_ledger",kind,stars,key:row.key,affects_mastery:false,at:row.at});state.history=state.history.slice(-500)}return row}
function perfectDayCount(){return Object.keys(state.learning_path?.day_by_date||{}).filter(date=>dayActivity(date).full).length}
function worldsPracticed(){return ["语文","数学","英语","阅读"].filter(subject=>formalItemsForSubject(subject).some(contentDone)).length}
function badgeValue(badge){const stats=rewardStats(),rule=badge.rule||{};switch(rule.type){case"stars_earned_total":return stats.earned;case"questions_correct_total":return completedFormalIds().size;case"generator_total":return Number(state.math_generator?.correct||0);case"streak_days":return learningStreak();case"redeems_total":return (state.rewards.redemptions||[]).length;case"perfect_days":return perfectDayCount();case"best_combo":return Number(state.rewards.best_combo||0);case"worlds_practiced":return worldsPracticed();default:return 0}}
function checkBadges(){if(!REWARD_ENABLED)return[];const catalog=REWARD_CONTRACT.badges||[];state.rewards.badges=Array.isArray(state.rewards.badges)?state.rewards.badges:[];const unlocked=[];catalog.forEach(badge=>{if(!state.rewards.badges.includes(badge.badge_id)&&badgeValue(badge)>=Number(badge.rule?.threshold||0)){state.rewards.badges.push(badge.badge_id);unlocked.push(badge)}});if(unlocked.length){state.history.push({event:"badge_unlocked",badge_ids:unlocked.map(row=>row.badge_id),affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500)}return unlocked}
function noteAnswer(correct,item){if(!REWARD_ENABLED)return null;if(!correct){ui.sessionCombo=0;ui.lastReward=null;return null}ui.sessionCombo=(ui.sessionCombo||0)+1;state.rewards.best_combo=Math.max(Number(state.rewards.best_combo||0),ui.sessionCombo);const rules=REWARD_CONTRACT.earn_rules||{},comboAt=rules.combo_at||[3,5],comboStars=rules.combo_stars||[1,1];let bonus=0,parts=["答对啦"];if(item&&FORMAL_IDS.has(item.item_id)&&postRewardLedger("first_complete",0,`first:${item.item_id}`,"首次完成"))parts.push("+1⭐");comboAt.forEach((need,index)=>{if(ui.sessionCombo===need){const got=postRewardLedger("combo_bonus",Number(comboStars[index]||1),`combo:${todayKey()}:${ui.sessionCombo}:${item?.item_id||"x"}`,`连击 ${need}`);if(got)bonus+=got.stars}});if(ui.sessionCombo>=3)parts.push(`🔥 ${ui.sessionCombo} 连击${bonus?` +${bonus}⭐`:""}`);const dailyNeed=Number(rules.daily_three_complete||3);if(dailyNeed&&dayActivity(todayKey()).full){const got=postRewardLedger("daily_three_complete",dailyNeed,`daily-three:${todayKey()}`,"今天三站");if(got)parts.push(`今天三站 +${got.stars}⭐`)}const unlocked=checkBadges();ui.lastReward={combo:ui.sessionCombo,bonus,unlocked,message:parts.join(" · ")};return ui.lastReward}
function completedLearningDates(){return Object.entries(state.learning_path?.day_by_date||{}).filter(([,day])=>Object.values(state.content_items||{}).some(row=>row.completed_ordinal===day.ordinal)).map(([date])=>date).sort()}
function learningStreak(){const dates=completedLearningDates();if(!dates.length)return 0;let streak=1;for(let i=dates.length-1;i>0;i-=1){const later=new Date(`${dates[i]}T00:00:00Z`),earlier=new Date(`${dates[i-1]}T00:00:00Z`);if((later-earlier)/86400000!==1)break;streak+=1}return streak}
function todayCollected(){const today=ENGINE.localDateKey(new Date());return new Set(state.history.filter(row=>row.correct&&FORMAL_IDS.has(row.item_id)&&historyDateKey(row.at)===today).map(row=>row.item_id)).size}
function todayMetric(count){return REWARD_ENABLED?`<div class="daily-metric"><span>今日收藏</span><strong>${count} 颗星</strong></div>`:`<div class="daily-metric"><span>今日完成</span><strong>${count} 项</strong></div>`}
function availableRewards(){return [...REWARD_CONTRACT.shop,...(state.rewards.custom_items||[]).filter(row=>!row.deleted)]}
function selectedReward(rewards){const selected=rewards.find(row=>row.item_id===state.rewards.selected_item_id),fallback=rewards.slice().sort((a,b)=>a.cost-b.cost)[0]||null;return selected||fallback}
function rewardIcon(row){return row?.icon||"🎁"}
function historyDateKey(value){return value?ENGINE.localDateKey(value):""}
function todayKey(){return ENGINE.localDateKey(new Date())}
function todayMovementCount(){const today=todayKey();return (state.history||[]).filter(row=>row.event==="movement_completed"&&historyDateKey(row.at)===today).length}
function resetTodaySession(){const today=todayKey(),cleared=todayMovementCount();state.history=(state.history||[]).filter(row=>!((row.event==="movement_completed"||row.event==="family_task_checked")&&historyDateKey(row.at)===today));state.today_session=state.today_session&&typeof state.today_session==="object"?state.today_session:{};state.today_session[today]={reset:true,cleared_movement:cleared,affects_mastery:false,at:new Date().toISOString()};state.history.push({event:"today_session_reset",date:today,cleared_movement:cleared,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);return {cleared_movement:cleared,affects_mastery:false}}
function familyTasksEnabled(){return state.family_tasks_enabled===true}
function familyTaskDone(id){const today=todayKey();return (state.history||[]).some(row=>row.event==="family_task_checked"&&row.task_id===id&&historyDateKey(row.at)===today)}
function fillCurrentOrderSlot(value,target){const next=ui.contentOrder.length;if(!Array.isArray(target)||next>=target.length)return false;if(String(value)!==String(target[next]))return false;ui.contentOrder.push(String(value));return true}
function fillCurrentAtomSlot(value,target){const next=ui.order.length;if(!Array.isArray(target)||next>=target.length)return false;if(String(value)!==String(target[next]))return false;ui.order.push(String(value));return true}
function orderSlotsHtml(target,filled,labelOf){const current=filled.length;return `<div class="order-slots" data-order-slots aria-label="按原文顺序填空，高亮当前空">${(target||[]).map((_,index)=>{const value=filled[index],done=value!==undefined&&value!=="";return `<span class="order-slot${done?" done":index===current?" active":""}" data-order-slot="${index}" aria-current="${index===current?"step":"false"}">${done?esc(labelOf?labelOf(value):value):"　"}</span>`;}).join('<span class="order-slot-sep" aria-hidden="true">—</span>')}</div>`}
function dayActivity(dateKey){const ignore=new Set(["today_session_reset","learning_path_activated","daily_content_pack_created","learning_path_day_created"]);const rows=(state.history||[]).filter(row=>historyDateKey(row.at||row.date)===dateKey&&!ignore.has(row.event));const movement=rows.filter(row=>row.event==="movement_completed").length;const family=rows.filter(row=>row.event==="family_task_checked").length;const attempts=rows.filter(row=>row.event==="practice_attempt"||row.event==="supplemental_content_attempt"||row.event==="supplemental_offscreen_confirmation").length;const visited=rows.filter(row=>row.event==="home_visited").length;const assignment=state.learning_path?.day_by_date?.[dateKey];const pack=state.daily_content_packs?.[dateKey]||[];const routeDone=assignment?pack.filter(id=>{const row=state.content_items?.[id];return row&&Number(row.completed_ordinal)===Number(assignment.ordinal);}).length:0;return{hasAny:movement>0||family>0||attempts>0||routeDone>0||visited>0,full:routeDone>=3,movement,family,attempts,routeDone,visited}}
function shiftFactCalendar(delta){const now=new Date();if(!ui.calYm)ui.calYm={y:now.getFullYear(),m:now.getMonth()};let y=ui.calYm.y,m=ui.calYm.m+Number(delta);if(m<0){m=11;y--}else if(m>11){m=0;y++}if(y>now.getFullYear()||(y===now.getFullYear()&&m>now.getMonth()))return;if(y<2024)return;ui.calYm={y,m}}
function dayFactCopy(dateKey){const fact=dayActivity(dateKey),parts=[];if(fact.routeDone)parts.push(`三站留下 ${fact.routeDone} 题`);if(fact.attempts)parts.push("做过练习");if(fact.movement)parts.push("身体充电");if(fact.family)parts.push("家庭小事");const title=dateKey.replace(/(\d+)-0?(\d+)-0?(\d+)/,"$1年$2月$3日");if(!fact.hasAny)return `${title}没有本机记录。缺席不会跳过学习日，也不算没学会。`;return `${title}${fact.full?"三站都留下痕迹":"有过记录"}。${parts.join("，")}。这是到场记录，不是掌握。`}
function factCalendarHtml(){const now=new Date();if(!ui.calYm)ui.calYm={y:now.getFullYear(),m:now.getMonth()};const y=ui.calYm.y,m=ui.calYm.m,first=new Date(y,m,1).getDay(),days=new Date(y,m+1,0).getDate(),isCurrent=y===now.getFullYear()&&m===now.getMonth(),today=isCurrent?now.getDate():0;let cells="",checked=0,full=0;for(let i=0;i<first;i+=1)cells+='<div class="cal-day empty"></div>';for(let day=1;day<=days;day+=1){const key=`${y}-${String(m+1).padStart(2,"0")}-${String(day).padStart(2,"0")}`,fact=dayActivity(key);let cls="cal-day";if(fact.full){cls+=" full";checked+=1;full+=1}else if(fact.hasAny){cls+=" part";checked+=1}if(day===today)cls+=" today";if(ui.calDay===key)cls+=" picked";cells+=`<button type="button" class="${cls}" data-cal-day="${key}" aria-label="${esc(dayFactCopy(key))}">${day}</button>`}const label=`${y}年${m+1}月`,selected=ui.calDay||(isCurrent?todayKey():"");return `<section class="fact-calendar" data-fact-calendar><div class="cal-toolbar"><button class="secondary mini" data-cal-shift="-1" ${y<=2024&&m<=0?"disabled":""} aria-label="上个月">‹</button><strong data-cal-label>${label}做过的日子</strong><button class="secondary mini" data-cal-shift="1" ${isCurrent?"disabled":""} aria-label="下个月">›</button></div><p class="writing-note">只表示这天有没有本机记录，不是掌握，也不推进学习日。</p><div class="calendar">${["日","一","二","三","四","五","六"].map(name=>`<div class="cal-head">${name}</div>`).join("")}${cells}</div><div class="cal-legend"><span>做过一件</span><span>三站都留下痕迹</span><span>今天</span></div><p class="cal-summary" data-cal-summary>${label}有记录 ${checked} 天，其中三站都留下痕迹 ${full} 天</p><p class="cal-day-copy" data-cal-day-copy>${esc(selected?dayFactCopy(selected):"点一天，看那天留下了什么。")}</p></section>`}
function movementDone(id){const today=todayKey();return state.history.some(row=>row.event==="movement_completed"&&row.action_id===id&&historyDateKey(row.at)===today)}
function startMovementTimer(){clearInterval(window.__movementTimer);window.__movementTimer=setInterval(()=>{if(ui.view!=="movement"||ui.movementAction===null||ui.movementAction===undefined){clearInterval(window.__movementTimer);return}ui.movementRemaining=Math.max(0,ui.movementRemaining-1);if(ui.movementRemaining===0){clearInterval(window.__movementTimer);render();return}const clock=document.querySelector(".movement-clock");if(clock)clock.textContent=`${ui.movementRemaining} 秒`},1000)}
function legacyRecord(){return state.legacy?.imports?.at(-1)||null}
function customTasks(){return (state.family_tasks||[]).slice(-20).reverse()}
function migrateLegacy(raw){const fresh=ENGINE.createState(),at=new Date().toISOString();fresh.legacy.imports.push({source_schema:raw.schemaVersion,payload:raw,at});fresh.history.push({event:"legacy_workbench_migrated",source_schema:raw.schemaVersion,affects_mastery:false,at});return fresh}
function subjectForItem(item){const targets=new Set(item.target_atom_ids||[]),atom=CATALOG.atoms.find(row=>targets.has(row.atom_id));return atom?.subject||"home"}
function objectImg(token,label=""){const key=OBJECT_ASSET_BY_TOKEN[token]||OBJECT_ASSET_BY_TOKEN[String(token).toLowerCase()],names={apple:"苹果",fish:"小鱼",flower:"花",ball:"球",leaf:"树叶",cat:"小猫",dog:"小狗",storybook:"故事书"},alt=esc(label||CONTENT_LABELS[token]||names[key]||token);return key?`<img class="learning-object" src="${ASSETS.objects[key]}" alt="${alt}">`:`<span class="learning-object learning-object-emoji" role="img" aria-label="${alt}">${esc(token)}</span>`}
function objectForItem(item){const p=item.presentation||{};if(p.hero)return p.hero;if(p.object_token)return p.object_token;const hay=`${item.family_id||""} ${item.item_id||""}`.toLowerCase(),key=Object.entries(FAMILY_OBJECT).find(([token])=>hay.includes(token))?.[1]||SUBJECT_OBJECT[subjectForItem(item)]||"flower";return key}
function kidTitle(text){return String(text||"").replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u,"").replace(/^\d+[\ufe0f\u20e3]?\s*/,"").trim()}
function friendlyReason(trigger){return {wrong_answer:"刚才这里有点绕，我们换个方法。",hint_used:"用过提示也没关系，这次自己试试。",delayed_transfer:"隔了一会儿，再看看你还记得吗。"}[trigger]||"换个办法，再试一次。"}
function worldHeader(view){const [title,copy,tone]=SUBJECT_COPY[view];return `<header class="world-heading ${tone}"><div><p class="eyeline">${STAGE_OVERLAY?"来玩这里":"我的学习世界"}</p><h1>${esc(title)}</h1><p>${esc(copy)}</p></div><div class="world-heading-art" aria-hidden="true">${objectImg(SUBJECT_OBJECT[view])}</div></header>`}
function worldModeTabs(){const mode=ui.worldMode||"practice";return `<div class="world-mode-tabs" data-world-mode-tabs role="tablist"><button type="button" role="tab" class="world-mode-tab${mode==="learn"?" active":""}" data-world-mode="learn" aria-selected="${mode==="learn"}">学一学</button><button type="button" role="tab" class="world-mode-tab${mode==="practice"?" active":""}" data-world-mode="practice" aria-selected="${mode==="practice"}">练一练</button><button type="button" role="tab" class="world-mode-tab${mode==="library"?" active":""}" data-world-mode="library" aria-selected="${mode==="library"}">题库</button></div>`}
function itemTeach(item){const raw=item&&item.teach||{},baby=PRODUCT.facts&&PRODUCT.facts.learning_stage_id==="baby-growth-explorer";return {title:kidTitle(item.title),story:raw.story||"",mission:raw.mission||item.objective||"",how:raw.how||STAGE_LESSON.how||"先看懂这件事，再选。",focus:raw.focus||"",together:raw.together||STAGE_LESSON.together||(baby?"请家长陪在旁边。孩子选，大人读。":""),cta:raw.cta||STAGE_LESSON.cta||"看完了，开始这一站"}}
function tonightItems(){const baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH);return pathDay.item_ids.map(id=>contentItems[id]).filter(Boolean).slice(0,3)}
function tonightRail(currentId){const daily=tonightItems();if(daily.length<2)return"";return `<nav class="tonight-rail" data-tonight-rest aria-label="今晚另外两件"><p>今晚这三件</p><div>${daily.map((item,index)=>`<button type="button" class="${item.item_id===currentId?"current":""}" data-open-content="${esc(item.item_id)}"><b>${index+1}</b><span>${esc(kidTitle(item.title))}</span></button>`).join("")}</div></nav>`}
function renderStageTeach(item){const teach=itemTeach(item),pool=sameTypePool(item),count=Math.max(pool.length,1),baby=PRODUCT.facts&&PRODUCT.facts.learning_stage_id==="baby-growth-explorer";document.body.dataset.contentItemId=item.item_id;document.getElementById("app-main").innerHTML=`<div class="lesson"><button class="back" data-close-content>← ${ui.contentOrigin==="home"?"返回今天":"返回"}</button><section class="stage-teach" data-stage-teach data-scene-confirm data-item-id="${esc(item.item_id)}"><p class="teach-kicker">${baby?"先问一声再开始":"先确认再开始"}</p><h2>${esc(teach.title)}</h2>${teach.story?`<p class="teach-story">${esc(teach.story)}</p>`:""}<p class="teach-how" data-scene-count>这一站有 ${count} 题。${baby?"我们一起做吗？":"现在开始吗？"}</p>${teach.together?`<p class="teach-together">${esc(teach.together)}</p>`:""}<div class="practice-actions"><button class="secondary" data-close-content>先回去</button><button class="primary" data-start-content-practice>${esc(teach.cta||"开始")}</button></div></section></div>`}
function formalItemsForSubject(subject){const atomIds=new Set(CATALOG.atoms.filter(row=>row.subject===subject).map(row=>row.atom_id));return PACK.items.filter(item=>!item.content_role&&(item.target_atom_ids||[]).some(id=>atomIds.has(id)))}
function renderWorld(subject){const atomList=CATALOG.atoms.filter(row=>row.subject===subject);const items=formalItemsForSubject(subject);if(STAGE_OVERLAY){if(!items.length){ui.view="home";return renderHome()}const next=items.find(item=>!contentDone(item))||items[0],mode=ui.worldMode||"practice";let body="";if(mode==="learn"){const focus=items.find(item=>!contentDone(item))||items[0],teach=itemTeach(focus);body=`<section class="world-primary" data-world-mode-panel="learn"><section class="stage-teach" data-stage-teach data-item-id="${esc(focus.item_id)}"><h2>${esc(teach.title)}</h2>${teach.story?`<p class="teach-story">${esc(teach.story)}</p>`:""}<button class="primary" data-open-content="${esc(focus.item_id)}" data-start-content-practice>${esc(teach.cta||"开始")}</button></section></section>`}else if(mode==="library"){const completed=items.filter(contentDone).length;body=`<section class="world-primary" data-world-mode-panel="library"><div class="compact-head"><div><p class="eyeline">本学科题库</p><h2>做过 ${completed}/${items.length}</h2><p>这里只表示做过，不改变家长核验或掌握。</p></div></div><div class="content-grid">${items.map(item=>contentCard(item)).join("")}</div></section>`}else{body=`<section class="world-primary" data-world-mode-panel="practice" data-world-practice-one><div class="compact-head"><div><p class="eyeline">现在开始</p><h2>${esc(kidTitle(next.title))}</h2><p>先做这一题。做完会出现下一题。</p></div></div>${contentCard(next)}</section>`}document.getElementById("app-main").innerHTML=worldHeader(subject)+worldModeTabs()+body;return}if(!atomList.length){ui.view="home";return renderHome()}const nextAtom=atomList.find(atom=>evidence(atom).scored_trials<atom.practice.items.length)||atomList[0],visible=items.slice(0,2),more=items.slice(2),mode=ui.worldMode||"practice";let body="";if(mode==="learn")body=`<section class="world-primary" data-world-mode-panel="learn"><div class="compact-head"><div><p class="eyeline">先看怎么玩</p><h2>学一学</h2><p>只看玩法和例子，不记掌握。看完再去练一练。</p></div></div><div class="content-grid">${atomList.map(atom=>card(atom)).join("")}</div></section>`;else if(mode==="library"){const completed=items.filter(contentDone).length;body=`<section class="world-primary" data-world-mode-panel="library"><div class="compact-head"><div><p class="eyeline">本学科题库</p><h2>做过 ${completed}/${items.length}</h2><p>这里只表示做过，不改变家长核验或掌握。</p></div></div><div class="content-grid">${items.map(item=>contentCard(item)).join("")}</div></section>`}else body=`<section class="world-primary" data-world-mode-panel="practice"><div class="compact-head"><div><p class="eyeline">现在开始</p><h2>${esc(kidTitle(guide(nextAtom).title))}</h2><p>先做这一个，完成后再决定要不要继续。</p></div></div>${card(nextAtom)}</section><section class="world-more"><div class="compact-head"><div><h2>还想玩</h2><p>两个同类挑战，其他内容先收起来。</p></div></div><div class="content-grid">${visible.map(item=>contentCard(item)).join("")}</div>${more.length?`<details class="more-content"><summary>看看其他挑战</summary><div class="content-grid">${more.map(item=>contentCard(item)).join("")}</div></details>`:""}</section>`;document.getElementById("app-main").innerHTML=worldHeader(subject)+worldModeTabs()+body}
function renderRepair(){if(STAGE_OVERLAY){const items=PACK.items.filter(item=>{const row=(state.content_items||{})[item.item_id];return row&&row.first_attempt_correct===false&&!row.resolved&&!row.guardian_confirmed});document.getElementById("app-main").innerHTML=`<header class="world-heading"><div><p class="eyeline">换个办法</p><h1>我们再试一次</h1><p>只重做本机答错且还没有完成的题，不改变掌握结论。</p></div></header>${items.length?`<div class="content-grid repair-grid">${items.map(item=>contentCard(item,"换个方法再试一次")).join("")}</div>`:`<div class="compact-empty">现在没有需要再试的挑战。</div>`}`;return}const baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH),follow=ENGINE.adaptiveFollowUpPack(state,PACK.items,LEARNING_PATH,pathDay.item_ids,CATALOG.atoms),items=follow.item_ids.map(id=>contentItems[id]).filter(Boolean);save();document.getElementById("app-main").innerHTML=`<header class="world-heading"><div><p class="eyeline">换个办法</p><h1>我们再试一次</h1><p>有点难很正常，这里会换一个提示帮你继续。</p></div><div class="world-heading-art" aria-hidden="true">${objectImg("fish")}</div></header>${items.length?`<div class="content-grid repair-grid count-${items.length}">${items.map(item=>contentCard(item,friendlyReason(follow.triggers[item.item_id]),follow.triggers[item.item_id])).join("")}</div>`:`<div class="compact-empty"><strong>现在没有需要再试的挑战。</strong><br>去左边挑一个喜欢的学习世界吧。</div>`}`}
function renderScience(){const items=STAGE_OVERLAY?PACK.items.filter(item=>String(item.family_id||"").includes("explore")):SCIENCE_ITEM_IDS.map(id=>contentItems[id]).filter(Boolean).filter(item=>!item.content_role),featured=items.find(item=>!contentDone(item))||items[0],more=items.filter(item=>item!==featured);document.getElementById("app-main").innerHTML=`<header class="world-heading science"><div><p class="eyeline">观察与发现</p><h1>观察实验室</h1><p>先看一看、猜一猜，再用手边的东西验证。</p></div><div class="world-heading-art" aria-hidden="true">${objectImg("leaf")}</div></header>${featured?`<section class="world-primary"><div class="compact-head"><div><p class="eyeline">今天观察</p><h2>${esc(kidTitle(featured.title))}</h2><p>${esc(featured.objective)}</p></div><button class="primary" data-open-content="${featured.item_id}">开始观察</button></div></section>`:""}${STAGE_OVERLAY?"":`<section class="world-more"><div class="compact-head"><div><h2>继续发现</h2><p>先看一看，再猜一猜。</p></div></div><div class="content-grid">${more.slice(0,3).map(item=>contentCard(item)).join("")}</div>${more.length>3?`<details class="more-content"><summary>更多观察挑战</summary><div class="content-grid">${more.slice(3).map(item=>contentCard(item)).join("")}</div></details>`:""}</section>`}`}
function movementPlayer(){if(ui.movementAction===null||ui.movementAction===undefined)return"";const row=MOVEMENT_ACTIONS[ui.movementAction],ready=ui.movementRemaining<=0;return `<section class="movement-player" data-movement-player><div><p class="eyeline">正在充电</p><h2>${esc(row[0])}</h2><p>${esc(row[1])}</p><div class="movement-clock" aria-live="polite">${ready?"完成啦":`${ui.movementRemaining} 秒`}</div><div class="movement-controls">${ready?`<button class="primary" data-movement-finish>完成充电</button>`:`<button class="secondary" data-movement-stop>随时停下</button>`}</div></div><div class="movement-figure movement-figure-emoji" aria-hidden="true">${MOVEMENT_EMOJIS[ui.movementAction]}</div></section>`}
function renderMovement(){const enabled=familyTasksEnabled(),tasks=enabled?customTasks():[];document.getElementById("app-main").innerHTML=`<header class="world-heading movement"><div><p class="eyeline">学习间歇</p><h1>身体充电站</h1><p>选一个舒服的动作，跟着倒计时来做，随时可以停。</p></div><div class="world-heading-art" aria-hidden="true">${objectImg("ball")}</div></header>${movementPlayer()}<div class="support-actions">${MOVEMENT_ACTIONS.map((row,index)=>`<button class="support-action ${movementDone(index)?"done":""}" data-movement-start="${index}"><span class="support-action-emoji" aria-hidden="true">${MOVEMENT_EMOJIS[index]}</span><span><strong>${movementDone(index)?"今天做过 · ":""}${esc(row[0])}</strong><span>${esc(row[1])}</span></span></button>`).join("")}</div>${enabled&&tasks.length?`<section class="family-checkins" data-family-task-checkins><h2>今天的家庭小事</h2><p>家长加的一次性安排，打勾不改掌握、不加星星。</p>${tasks.map(row=>`<div class="family-checkin${familyTaskDone(row.task_id)?" done":""}"><span><strong>${esc(row.title)}</strong><small>${esc(row.due||"今天可以做")}</small></span><button class="secondary" data-family-task-toggle="${esc(row.task_id)}">${familyTaskDone(row.task_id)?"今天做过":"记下做完"}</button></div>`).join("")}</section>`:""}`;if(ui.movementAction!==null&&ui.movementAction!==undefined&&ui.movementRemaining>0)startMovementTimer()}
function rewardCard(row,goal,stats){const selected=goal?.item_id===row.item_id,ok=stats.balance>=row.cost&&state.rewards.status==="active",shortfall=Math.max(0,row.cost-stats.balance);return `<article class="reward-item ${selected?"selected":""} ${ok?"":"locked"}"><div class="reward-item-icon" aria-hidden="true">${esc(rewardIcon(row))}</div><strong>${esc(row.title)}</strong><span>⭐ ${row.cost}${row.cat?` · ${esc(row.cat)}`:""}</span><button class="${selected?"secondary":"primary"}" data-select-reward="${esc(row.item_id)}" ${selected?"disabled":""}>${selected?"当前目标":"设为目标"}</button><button class="secondary" data-redeem="${esc(row.item_id)}" ${ok?"":"disabled"}>${ok?"请家长兑换":`还差 ${shortfall}`}</button></article>`}
function rewardConfirmPanel(rewards){const row=rewards.find(item=>item.item_id===ui.pendingRewardId);if(!row)return"";return `<section class="reward-confirm-panel" role="dialog" aria-modal="true" aria-labelledby="reward-confirm-title" data-reward-confirm-panel><div class="reward-confirm-card"><div class="reward-confirm-icon" aria-hidden="true">${esc(rewardIcon(row))}</div><h2 id="reward-confirm-title">请家长确认兑换</h2><p>用 <strong>${row.cost} 颗星</strong>兑换“${esc(row.title)}”。确认后会扣除星星并留下本机记录。</p><div class="reward-confirm-actions"><button class="secondary" data-cancel-redeem>先不兑换</button><button class="primary" data-confirm-redeem>家长确认兑换</button></div></div></section>`}
function badgeUnlockPanel(){const got=ui.pendingBadges||[];if(!got.length)return"";const first=got[0];return `<section class="reward-confirm-panel" role="dialog" aria-modal="true" aria-labelledby="badge-unlock-title" data-badge-unlock-panel><div class="reward-confirm-card"><div class="reward-confirm-icon" aria-hidden="true">${esc(first.icon||"🏅")}</div><h2 id="badge-unlock-title">解锁新徽章</h2><p><b>${esc(first.title)}</b><br>${esc(first.hint||"")}${got.length>1?`<br>同时点亮了另外 ${got.length-1} 枚`:""}</p><div class="reward-confirm-actions"><button class="secondary" data-dismiss-badge>知道啦</button><button class="primary" data-collect-tab="badge">查看徽章墙</button></div></div></section>`}
function renderBadgeWall(){const catalog=REWARD_CONTRACT.badges||[],owned=new Set(state.rewards.badges||[]);return `<div class="compact-head reward-shop-head"><div><h2>最近的徽章</h2><p>已点亮 ${owned.size} / ${catalog.length}。徽章只庆祝坚持，不表示学会了。</p></div></div><div class="badge-grid">${catalog.map(badge=>{const on=owned.has(badge.badge_id),value=Math.min(badgeValue(badge),Number(badge.rule?.threshold||1)),need=Number(badge.rule?.threshold||1),pct=Math.round(value/need*100);return `<article class="badge-card${on?" unlocked":""}" data-reward-badge="${esc(badge.badge_id)}"><div class="badge-emoji">${esc(badge.icon||"🏅")}</div><strong>${esc(badge.title)}</strong><span>${esc(badge.hint||"")}</span>${on?`<div class="badge-pct">已点亮 ✓</div>`:`<div class="badge-progress"><i style="width:${pct}%"></i></div><div class="badge-pct">${value}/${need}</div>`}</article>`}).join("")}</div>`}
function renderCollect(){if(!REWARD_ENABLED){ui.view="home";return renderHome()}const stats=rewardStats(),rewards=availableRewards(),goal=selectedReward(rewards),shortfall=goal?Math.max(0,goal.cost-stats.balance):0,progress=goal?Math.min(100,Math.round(stats.balance/goal.cost*100)):0,recent=(state.rewards.redemptions||[]).slice().reverse(),tab=ui.collectTab||"shop",cats=["全部",...[...new Set(rewards.map(row=>row.cat).filter(Boolean))]],shopCat=ui.shopCat||"全部",shown=rewards.filter(row=>shopCat==="全部"||row.cat===shopCat);if(goal&&state.rewards.selected_item_id!==goal.item_id){state.rewards.selected_item_id=goal.item_id;save()}document.getElementById("app-main").innerHTML=top("星星小卖部","答对就攒星，连击有加成，攒够请家长兑换")+`<section class="reward-balance"><div class="reward-balance-copy"><span>现在有</span><strong>${stats.balance} 颗星</strong></div><div class="reward-balance-icon" aria-hidden="true">⭐</div></section>${state.rewards.status!=="active"?`<div class="legacy-note">奖励约定已${state.rewards.status==="paused"?"暂停":"关闭"}，已有星星和兑换记录仍保留。</div>`:""}<div class="collect-tabs" role="tablist"><button type="button" class="collect-tab${tab==="shop"?" active":""}" data-collect-tab="shop">星星小卖部</button><button type="button" class="collect-tab${tab==="badge"?" active":""}" data-collect-tab="badge">查看全部徽章</button></div>${tab==="badge"?renderBadgeWall():`${goal?`<section class="reward-goal"><div class="reward-goal-icon" aria-hidden="true">${esc(rewardIcon(goal))}</div><div><p class="eyeline">我的目标奖励</p><h2>${esc(goal.title)}</h2><p>${goal.cost} 颗星可以兑换</p><div class="reward-progress" role="progressbar" aria-label="目标奖励进度" aria-valuemin="0" aria-valuemax="${goal.cost}" aria-valuenow="${Math.min(stats.balance,goal.cost)}"><span style="width:${progress}%"></span></div><p>${shortfall?`还差 ${shortfall} 颗星`:`星星够啦，请家长来确认`}</p><div class="reward-goal-actions">${state.rewards.status!=="active"?`<button class="secondary" disabled>奖励当前不可兑换</button>`:shortfall?`<button class="primary" data-view="home">去完成新挑战</button>`:`<button class="primary" data-redeem="${esc(goal.item_id)}">请家长兑换</button>`}</div></div></section>`:""}<div class="chip-row">${cats.map(cat=>`<button type="button" class="chip${shopCat===cat?" active":""}" data-shop-cat="${esc(cat)}">${esc(cat)}</button>`).join("")}</div><div class="compact-head reward-shop-head"><div><h2>可选奖励</h2><p>选一个想攒的目标，够了就请家长兑换。</p></div></div><div class="reward-shop">${shown.map(row=>rewardCard(row,goal,stats)).join("")}</div><div class="compact-head reward-shop-head"><div><h2>最近兑换</h2><p>只记录家长已经确认的兑换。</p></div></div>${recent.length?`<div class="reward-history">${recent.slice(0,20).map(row=>`<div class="reward-history-row"><strong>${esc(row.title)}</strong><span>-${row.cost} 颗星</span></div>`).join("")}</div>`:`<div class="compact-empty">还没有兑换记录。</div>`}`}${rewardConfirmPanel(rewards)}${badgeUnlockPanel()}`}
'''


_COMPANION_JS = r'''function companionVisible(){if(!REWARD_ENABLED||state.rewards.status!=="active"||!(REWARD_CONTRACT.companion&&REWARD_CONTRACT.companion.skins||[]).length)return false;return companionPrefs().enabled}
function companionPrefs(){const skins=(REWARD_CONTRACT.companion&&REWARD_CONTRACT.companion.skins)||[],raw=state.rewards.companion||{},ids=new Set(skins.map(row=>row.system_id)),fallback=defaultCompanionSkin();return {enabled:raw.enabled!==false,skin_id:ids.has(raw.skin_id)?raw.skin_id:fallback}}
function companionSkin(){const prefs=companionPrefs(),skins=(REWARD_CONTRACT.companion&&REWARD_CONTRACT.companion.skins)||[];return skins.find(row=>row.system_id===prefs.skin_id)||skins[0]||null}
function todayRouteDone(){const baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH);return pathDay.item_ids.map(id=>contentItems[id]).filter(Boolean).slice(0,3).filter(groupDone).length}
function companionProjection(done,need){const skin=companionSkin();if(!skin)return null;const want=Number(need)||3,clamped=Math.max(0,Math.min(Number(done)||0,want)),mood=clamped>=want?"well":clamped>=2?"almost":clamped>=1?"hopeful":"waiting";const baby=PRODUCT.facts&&PRODUCT.facts.learning_stage_id==="baby-growth-explorer";let copy=(skin.moods&&skin.moods[mood])||"";if(baby&&mood==="waiting"&&skin.baby_waiting)copy=skin.baby_waiting;return {enabled:true,skin_id:skin.system_id,mood,copy,emoji:skin.emoji||"🐾",label:skin.label||"",recover:skin.recover||"",celebration:skin.celebration||"",done:clamped,need:want,affects_mastery:false}}
function companionGrowthView(){const stages=((REWARD_CONTRACT.progress||{}).growth||{}).stages||[{id:"sprout",min:0,label:"幼苗",copy:"还很小，做过的事会让它长大一点"},{id:"growing",min:3,label:"在长大",copy:"已经做过好几题了"},{id:"familiar",min:10,label:"很熟了",copy:"经常见面"},{id:"old-friend",min:20,label:"老朋友",copy:"陪你做过很多题了"}];const done=completedFormalIds().size;let current=stages[0];stages.forEach(row=>{if(done>=Number(row.min||0))current=row});return {stage_id:current.id||"sprout",label:current.label||"幼苗",copy:current.copy||"",done,affects_mastery:false}}
function noteHomeVisit(){const key=todayKey();if((state.history||[]).some(row=>row.event==="home_visited"&&historyDateKey(row.at)===key))return;state.history=state.history||[];state.history.push({event:"home_visited",affects_mastery:false,at:new Date().toISOString()})}
function visitDayKeys(count){const keys=[];const today=new Date();for(let offset=count-1;offset>=0;offset-=1){const day=new Date(today.getFullYear(),today.getMonth(),today.getDate()-offset);keys.push(`${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,"0")}-${String(day.getDate()).padStart(2,"0")}`)}return keys}
function visitFamiliarityView(){const keys=visitDayKeys(3);const plots=keys.map(date=>{const act=dayActivity(date);const plot=act.full?"bloom":act.hasAny?"sprout":"empty";return {date,state:plot,came:Boolean(act.hasAny)}});let consecutive=0;for(let i=plots.length-1;i>=0;i-=1){if(plots[i].came)consecutive+=1;else break}const copy=consecutive>=3?"这几天都见到你了。":consecutive===2?"你昨天来过。":"";return {plots,consecutive,copy,affects_mastery:false}}
function visitPlotsHtml(visit){return `<div class="visit-plots" data-visit-familiarity="${visit.consecutive}" aria-label="最近来过">${visit.plots.map(plot=>`<span class="visit-plot" data-garden-state="${esc(plot.state)}" title="${esc(plot.date)}">${plot.state==="bloom"?"🌸":plot.state==="sprout"?"🌱":"🪴"}</span>`).join("")}</div>`}
function companionCardHtml(done,need,next){if(!companionVisible())return"";const view=companionProjection(done,need);if(!view)return"";maybeCelebrateCompanion(view);const growth=companionGrowthView();const visit=visitFamiliarityView();const face=companionPortraitHtml(view.skin_id,view.mood)||esc(view.emoji);const action=next?`<button class="primary" data-open-content="${esc(next.item_id)}">${esc(stageCta(false))}</button>`:`<p class="companion-done">${esc(view.celebration||"今天的三站做完啦")}</p>`;return `<section class="companion-card" data-companion-card data-companion-mood="${esc(view.mood)}" data-companion-skin="${esc(view.skin_id)}"><div class="companion-emoji">${face}${visitPlotsHtml(visit)}</div><div class="companion-copy"><span>${esc(view.label)}</span><strong>${esc(view.copy)}</strong>${visit.copy?`<span class="visit-copy" data-visit-copy>${esc(visit.copy)}</span>`:""}<span class="companion-growth" data-companion-growth="${esc(growth.stage_id)}">${esc(growth.label)} · 做过 ${growth.done} 题</span><p>今天 ${view.done}/${view.need} · ${esc(view.recover)}</p>${action}</div></section>`}
function gardenPrefs(){const raw=state.rewards.progress||{};return {enabled:raw.garden_enabled!==false}}
function gardenVisible(){if(!REWARD_ENABLED||!((REWARD_CONTRACT.progress||{}).garden||{}).enabled)return false;if(!gardenPrefs().enabled)return false;if(companionVisible()&&companionPrefs().skin_id==="companion-plants")return false;return true}
function gardenProgressHtml(){if(!gardenVisible())return"";const keys=[];const today=new Date();for(let offset=6;offset>=0;offset-=1){const day=new Date(today.getFullYear(),today.getMonth(),today.getDate()-offset);keys.push(`${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,"0")}-${String(day.getDate()).padStart(2,"0")}`)}const plots=keys.map(date=>{const act=dayActivity(date);const plot=act.full?"bloom":act.hasAny?"sprout":"empty";return `<div class="garden-plot" data-garden-state="${plot}" title="${date}">${plot==="bloom"?"🌸":plot==="sprout"?"🌱":"🪴"}</div>`});return `<section class="garden-strip" data-garden-progress><p>最近的花园 · 只表示这几天来过，不是成绩</p><div class="garden-plots">${plots.join("")}</div></section>`}
function maybeCelebrateCompanion(view){if(!view||view.mood!=="well")return;const key=todayKey();if(ui.companionCelebratedOn===key)return;ui.companionCelebratedOn=key;toast(view.celebration||"今天的三站做完啦")}
function currentRoom(){const rooms=(ASSETS&&ASSETS.rooms)||{},map=(ASSETS&&ASSETS.skin_to_room)||{},fallback=ASSETS.default_room||"garden",id=map[companionPrefs().skin_id]||fallback;return Object.assign({room_id:id,label:"小花园",brand:"小花园",brand_sub:"我的房间",emoji:"🌱"},rooms[id]||rooms[fallback]||{})}
function sanitizeRoomName(raw){const original=String(raw||""),text=original.replace(/\s+/g,""),max=((ASSETS&&ASSETS.room_claim)||{}).name_max||6;if(!text)return"";const lower=(original+" "+text).toLowerCase();if(lower.includes("hellokitty")||lower.includes("hello kitty")||/[\u5965][\u7279][\u66fc]/.test(original+text))return"";const clipped=text.slice(0,max);if(!/^[\u4e00-\u9fffA-Za-z0-9·]+$/.test(clipped))return"";return clipped}
function roomClaimPrefs(){const raw=state.room_claim||{};return {name:sanitizeRoomName(raw.name)}}
function roomClaimLabel(room){const name=roomClaimPrefs().name,label=(room||currentRoom()).label||"房间";return name?`${name}的${label}`:`我的${label}`}
function applyRoom(){const room=currentRoom(),app=document.querySelector(".app"),claim=roomClaimLabel(room);if(!app)return;app.dataset.room=room.room_id||"garden";if(room.hero)app.style.setProperty("--playground-hero",`url("${room.hero}")`);const brand=app.querySelector(".brand strong"),small=app.querySelector(".brand small"),mark=app.querySelector(".brand-mark"),stage=app.querySelector("[data-room-stage]"),label=app.querySelector("[data-room-stage] .room-label");if(brand)brand.textContent=room.brand||"小花园";if(small)small.textContent=claim;if(mark)mark.textContent=room.emoji||"🌱";if(stage)stage.setAttribute("aria-label",claim);if(label)label.textContent=claim}
function roomClaimParentPanel(){const prefs=roomClaimPrefs();return `<details data-room-claim-parent><summary>门牌 · ${esc(prefs.name||"还没写称呼")}</summary><div class="parent-detail-body"><p>写一个家里怎么叫小朋友的短称呼，会出现在房间门牌上，例如「乐乐的小花园」。只留在这台设备，不要写真实全名或学校。换电脑前先导出。</p><label>怎么称呼<input data-room-claim-name-input maxlength="6" value="${esc(prefs.name)}" placeholder="例如乐乐"></label><div class="data-actions"><button class="primary" data-room-claim-save>写到门牌上</button>${prefs.name?`<button class="secondary" data-room-claim-clear>拿掉称呼</button>`:""}</div></div></details>`}
function companionParentPanel(){if(!REWARD_ENABLED||!(REWARD_CONTRACT.companion&&REWARD_CONTRACT.companion.skins||[]).length)return"";const prefs=companionPrefs(),skins=REWARD_CONTRACT.companion.skins,room=currentRoom(),rooms=(ASSETS&&ASSETS.rooms)||{},map=(ASSETS&&ASSETS.skin_to_room)||{};return `<details data-companion-parent data-room-parent><summary>换房间 · ${esc(room.label||"小花园")} · ${prefs.enabled?"使用中":"已关闭"}</summary><div class="parent-detail-body"><p>选一间房间，颜色、房子、装饰和伙伴会一起换。关掉后儿童页不再出现伙伴，已有星星还在。不改掌握。</p><div class="data-actions">${prefs.enabled?`<button class="secondary" data-companion-enabled="false">关掉伙伴</button>`:`<button class="primary" data-companion-enabled="true">打开伙伴</button>`}</div><div class="companion-skin-list">${skins.map(row=>{const mapped=rooms[map[row.system_id]]||{};return `<button class="${prefs.skin_id===row.system_id?"primary":"secondary"}" data-companion-skin="${esc(row.system_id)}" data-room="${esc(mapped.room_id||"")}">${esc(row.emoji||"")} ${esc(mapped.label||row.label)}</button>`}).join("")}</div></div></details>`}
function warmIncorrectEnabled(){if(!REWARD_ENABLED||!(REWARD_CONTRACT.encouragement))return false;const prefs=state.rewards.encouragement||{};return prefs.enabled!==false&&REWARD_CONTRACT.encouragement.enabled!==false}
function warmIncorrectView(item){const pack=REWARD_CONTRACT.encouragement||{},lines=pack.lines||[],baby=PRODUCT.facts&&PRODUCT.facts.learning_stage_id==="baby-growth-explorer",id=String(item&&item.item_id||"");let acc=0;for(let i=0;i<id.length;i+=1)acc+=id.charCodeAt(i);const line=lines.length?lines[acc%lines.length]:{title:"没关系",copy:"这次没对，很正常。"};const next=String((item&&item.remediation_next_action)||pack.default_next||"再看一眼题目，换一个答案。");return {title:baby?(pack.baby_title||"我们一起再试一次"):(line.title||"没关系"),copy:baby?(pack.baby_copy||"做错了也没关系，我们再看一眼。"):(line.copy||"这次没对，很正常。"),next,affects_mastery:false}}
function contentFeedbackHtml(item){const fb=ui.contentFeedback;if(!fb)return"";if(!fb.correct&&warmIncorrectEnabled()){const warm=warmIncorrectView(item);return `<div class="feedback wrong warm-incorrect" data-warm-incorrect data-result="${esc(fb.result||"retry")}"><b>${esc(warm.title)}</b><p>${esc(warm.copy)}</p><p class="warm-next">下一步：${esc(warm.next)}</p></div>`}return `<div class="feedback ${fb.correct?"correct":"wrong"}" data-result="${esc(fb.result||"")}"><b>${fb.correct?"完成啦！":"再看一眼"}</b>${esc(fb.text)}</div>`}
function encouragementParentPanel(){if(!REWARD_ENABLED||!REWARD_CONTRACT.encouragement)return"";const on=warmIncorrectEnabled();return `<details data-warm-parent><summary>答错也暖 · ${on?"使用中":"已关闭"}</summary><div class="parent-detail-body"><p>答错只给一句暖和下一步，不扣星星、不改掌握。关掉后仍显示原来的对错说明。</p><div class="data-actions">${on?`<button class="secondary" data-warm-enabled="false">关掉答错也暖</button>`:`<button class="primary" data-warm-enabled="true">打开答错也暖</button>`}</div></div></details>`}
function gardenParentPanel(){if(!REWARD_ENABLED||!((REWARD_CONTRACT.progress||{}).garden||{}).enabled)return"";const on=gardenPrefs().enabled,plants=companionVisible()&&companionPrefs().skin_id==="companion-plants",label=plants?"植物皮时收起":on?"使用中":"已关闭";return `<details data-garden-parent><summary>近七日花园 · ${label}</summary><div class="parent-detail-body"><p>七格只表示这几天来过，不是成绩，也不改掌握。换成植物伙伴时会自动收起，避免两套植物抢首页。</p><div class="data-actions">${on?`<button class="secondary" data-garden-enabled="false">关掉花园条</button>`:`<button class="primary" data-garden-enabled="true">打开花园条</button>`}</div></div></details>`}
function homeEncourageCopy(dailyDone){const baby=PRODUCT.facts&&PRODUCT.facts.learning_stage_id==="baby-growth-explorer";if(dailyDone>=3)return baby?"今天三件小事都留下啦。可以去小卖部看看。":"今天三站做完啦。去小卖部看看能换什么。";if(dailyDone===2)return baby?"还差一件，我们一起做完。":"还差一站，今天三站奖励就快到了。";if(dailyDone===1)return baby?"已经一起做完一件，下一件还在等你们。":"已经留下一站了，下一站还在等你。";return baby?"来了就算开始。请家长读题，我们一起先看第一件。":"来了就算开始。先看懂，再做第一站。"}
function homeBoostHtml(dailyDone){const line=homeEncourageCopy(dailyDone);if(!REWARD_ENABLED)return `<section class="home-boost" data-home-boost><article class="home-encourage" data-home-encourage><p class="teach-kicker">今天的话</p><strong>${esc(line)}</strong></article></section>`;const stats=rewardStats(),combo=ui.sessionCombo||0,best=Number(state.rewards.best_combo||0),catalog=REWARD_CONTRACT.badges||[],owned=new Set(state.rewards.badges||[]),nextBadge=catalog.find(badge=>!owned.has(badge.badge_id))||null,need=nextBadge?Number(nextBadge.rule?.threshold||1):1,got=nextBadge?Math.min(badgeValue(nextBadge),need):0,rewards=availableRewards(),goal=selectedReward(rewards),shortfall=goal?Math.max(0,goal.cost-stats.balance):0,threeKey=`daily-three:${todayKey()}`,threeGot=rewardLedger().some(row=>row.key===threeKey),recent=(state.rewards.badges||[]).slice(-3).map(id=>catalog.find(badge=>badge.badge_id===id)).filter(Boolean);return `<section class="home-boost" data-home-boost><article class="home-encourage" data-home-encourage><p class="teach-kicker">今天的话</p><strong>${esc(line)}</strong><p>${threeGot?"今天三站奖励已经记下了。":dailyDone>=3?"三站都留下了，奖励会记在星星里。":"做完今天三站，会多记 3 颗星。"}</p></article><article class="home-achieve" data-home-achieve><p class="teach-kicker">成就还在这</p><div class="achieve-row"><button type="button" class="achieve-chip" data-view="collect">⭐ ${stats.balance} 颗星</button><button type="button" class="achieve-chip" data-collect-tab="badge">🏅 ${owned.size}/${catalog.length} 徽章</button>${combo>1?`<span class="achieve-chip">🔥 现在 ${combo} 连击</span>`:best?`<span class="achieve-chip">🔥 最高 ${best} 连击</span>`:`<span class="achieve-chip">🔥 还没有连击</span>`}<span class="achieve-chip">${threeGot?"今天三站 ✓":`今天三站 ${dailyDone}/3`}</span></div>${goal?`<div class="achieve-goal"><span>目标：${esc(goal.title)} · ${shortfall?`还差 ${shortfall} 颗`:"够了，请家长兑换"}</span><div class="reward-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${goal.cost}" aria-valuenow="${Math.min(stats.balance,goal.cost)}"><span style="width:${Math.min(100,Math.round(stats.balance/goal.cost*100))}%"></span></div></div>`:""}${nextBadge?`<p class="achieve-next">下一枚徽章「${esc(nextBadge.title)}」${got}/${need}</p>`:""}${recent.length?`<div class="achieve-recent">${recent.map(badge=>`<span title="${esc(badge.title)}">${esc(badge.icon||"🏅")}</span>`).join("")}</div>`:""}</article></section>`}
'''

_HOME = r'''function renderHome(){const stats=rewardStats(),done=completedFormalIds().size,streak=learningStreak(),baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH),daily=pathDay.item_ids.map(id=>contentItems[id]).filter(Boolean).slice(0,3),follow=STAGE_OVERLAY?{item_ids:[],triggers:{}}:ENGINE.adaptiveFollowUpPack(state,PACK.items,LEARNING_PATH,pathDay.item_ids,CATALOG.atoms),followItems=follow.item_ids.map(id=>contentItems[id]).filter(Boolean).slice(0,2),next=daily.find(item=>!groupDone(item))||null,dailyDone=daily.filter(groupDone).length,badgeCount=(state.rewards.badges||[]).length,room=currentRoom(),claim=roomClaimLabel(room),hud=STAGE_FACE.hud||"soft",chip=STAGE_FACE.chip||"";noteHomeVisit();save();document.getElementById("app-main").innerHTML=`<section class="playground-home" data-stage-face="${esc(STAGE_FACE.face_id||"garden-lesson")}"><header class="home-greeting"><div><h1 data-stage-home-title>${esc(stageHomeTitle())}</h1>${chip?`<p class="stage-chip" data-stage-chip>${esc(chip)}</p>`:""}<p>${esc(STAGE_HINT)}</p></div><div class="home-stats" data-stage-hud="${esc(hud)}">${hud==="full"?`<div class="home-stat"><span>今天路线</span><strong>${dailyDone}/3</strong></div><div class="home-stat"><span>连续有记录</span><strong>${streak} 天</strong></div>${REWARD_ENABLED?`<div class="home-stat"><span>可用星星</span><strong>${stats.balance} 颗</strong></div><div class="home-stat"><span>徽章</span><strong>${badgeCount}</strong></div>`:""}`:`<div class="home-stat"><span>今天</span><strong>${dailyDone}/3</strong></div>${REWARD_ENABLED&&hud!=="soft"?`<div class="home-stat"><span>星星</span><strong>${stats.balance}</strong></div>`:""}`}</div></header>${companionCardHtml(dailyDone,3,next)}<section class="today-board" data-daily-content-pack data-learning-path-day="${pathDay.day_in_cycle}"><div class="today-board-head"><div><h2>今天三站</h2><p>${esc(STAGE_LESSON.board||(pathDay.title+" · 完成后自动保留。"))}</p></div><strong>${dailyDone}/3</strong></div><div class="today-route">${daily.map((item,index)=>`<article class="today-stop ${item===next?"now":""} ${groupDone(item)?"done":""}" data-group-progress="${esc(groupProgress(item))}"><span class="stop-number">${index+1}</span><div class="task-visual" aria-hidden="true">${objectImg(objectForItem(item))}</div><h3>${esc(kidTitle(item.title))}</h3><p>${esc(groupProgress(item))} · ${esc(item.objective)}</p><button class="${!groupDone(item)&&item===next?"primary":"secondary"}" data-open-content="${(sameTypePool(item).find(row=>!contentDone(row))||item).item_id}">${esc(stageCta(groupDone(item)))}</button></article>`).join("")}</div></section><section class="playground-hero home-stage" data-room-stage data-room-claim data-room-claim-name="${esc(roomClaimPrefs().name)}" aria-label="${esc(claim)}"><p class="room-label" data-room-claim-label>${esc(claim)}</p></section>${homeBoostHtml(dailyDone)}${gardenProgressHtml()}${factCalendarHtml()}${followItems.length?`<section class="world-more" data-adaptive-follow-up><div class="compact-head"><div><h2>换个办法</h2><p>今天最多加两个，只在真正需要时出现。</p></div></div><div class="content-grid repair-grid count-${followItems.length}">${followItems.map(item=>contentCard(item,friendlyReason(follow.triggers[item.item_id]),follow.triggers[item.item_id])).join("")}</div></section>`:""}</section>`}'''


_PARENT = r'''function renderParent(){const pack=ENGINE.packForRound(PRODUCT,state.current_round).map(id=>atoms[id]).filter(Boolean),baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH),follow=ENGINE.adaptiveFollowUpPack(state,PACK.items,LEARNING_PATH,pathDay.item_ids,CATALOG.atoms),legacy=legacyRecord(),tasks=customTasks(),customRewards=(state.rewards.custom_items||[]).filter(row=>!row.deleted),statusText={active:"使用中",paused:"已暂停",closed:"已关闭"}[state.rewards.status];document.getElementById("app-main").innerHTML=top("家长区","成人查看的安排依据、家庭设置与本机数据")+`<div class="legacy-note" data-parent-mode>这里是成人区。儿童学习页不会出现备份、清空或奖励编辑工具。</div><div class="parent-sections"><details open><summary>今天的安排依据</summary><div class="parent-detail-body">${renderParentPath(pathDay,follow)}<div class="legacy-note">“观察实验室”只是跨学科观察活动，不会生成独立的科学掌握结论。</div></div></details><details><summary>本月打卡事实</summary><div class="parent-detail-body"><p>格子只回答这天有没有留下本机痕迹：做过题、身体充电或家庭小事。黄格是做过一件，绿格是当天三站都留下痕迹。它不是成绩单，也不能证明学会了；缺席不会跳过活跃学习日。</p>${factCalendarHtml()}</div></details><details><summary>本轮完成确认</summary><div class="parent-detail-body"><p>只核对当前练习记录，不做能力诊断。</p><div class="review-list">${pack.map(a=>{const e=evidence(a),v=verified(a.atom_id);return `<article class="review"><div><h3>${esc(kidTitle(guide(a).title))}</h3><div class="parent-checks"><span class="parent-check ${e.scored_trials===4?"ok":""}">4 题完成</span><span class="parent-check ${e.transfer_correct?"ok":""}">迁移完成</span><span class="parent-check ${e.hints===0&&e.scored_trials===4?"ok":""}">未用提示</span></div></div><button class="${v?"secondary":"primary"}" data-verify="${a.atom_id}" ${!e.pass||v?"disabled":""}>${v?"已确认":e.pass?"确认完成":"还没完成"}</button></article>`}).join("")}</div></div></details><details><summary>家庭任务 · ${familyTasksEnabled()?"使用中":"默认关闭"}</summary><div class="parent-detail-body"><p>家庭任务默认关闭，不进教材，也不改掌握或星星。打开后只加一次性家庭小事，孩子可在身体充电页打勾。</p><div class="data-actions">${familyTasksEnabled()?`<button class="secondary" data-family-tasks-enabled="false">关闭家庭任务</button>`:`<button class="primary" data-family-tasks-enabled="true">打开家庭任务</button>`}</div>${familyTasksEnabled()?`<form class="custom-task-form" data-custom-task-form><label>任务名称<input name="title" maxlength="80" required placeholder="例如：睡前整理书包"></label><label>计划日期（可选）<input name="due" type="date"></label><label>补充说明（可选）<textarea name="details" maxlength="300"></textarea></label><button class="primary" type="submit">加入家庭任务</button></form><div class="custom-task-list">${tasks.map(row=>`<div class="custom-task-row"><span><strong>${esc(row.title)}</strong><small>${esc(row.due||"未设日期")}</small></span><button class="danger-btn mini" data-delete-family-task="${esc(row.task_id)}">删除</button></div>`).join("")||"<p>还没有家庭任务。</p>"}</div>`:`<p>保持关闭时，儿童页不会出现家庭任务。</p>`}</div></details>${REWARD_ENABLED?`<details><summary>星星奖励 · ${statusText}</summary><div class="parent-detail-body"><p>奖励只用于家庭约定，不改变学习判断。兑换必须由家长在奖励页确认。家长可以手动加减星星，扣减可再加回去。</p><div class="parent-reward-stats"><span>可用 ${rewardStats().balance}</span><span>累计获得 ${rewardStats().earned}</span><span>徽章 ${(state.rewards.badges||[]).length}</span><span>兑换 ${(state.rewards.redemptions||[]).length}</span></div><div class="data-actions"><button class="secondary" data-view="collect">查看星星奖励</button>${state.rewards.status==="active"?`<button class="secondary" data-reward-status="paused">暂停奖励</button>`:`<button class="primary" data-reward-status="active">${state.rewards.status==="closed"?"重新启用":"恢复奖励"}</button>`}<button class="danger-btn" data-reward-status="closed" ${state.rewards.status==="closed"?"disabled":""}>关闭奖励</button></div><form class="custom-task-form" data-star-adjust-form><label>星星调整（正数奖励，负数扣减）<input name="stars" type="number" min="-50" max="50" required placeholder="例如 2 或 -1"></label><label>原因<input name="reason" maxlength="40" placeholder="例如：今天特别认真"></label><button class="primary" type="submit">家长调整星星</button></form><form class="custom-task-form" data-custom-reward-form><label>自定义奖励名称<input name="title" maxlength="60" required placeholder="例如：一起烤小饼干"></label><label>需要星星<input name="cost" type="number" min="1" max="200" required value="8"></label><button class="primary" type="submit">加入奖励</button></form><div class="custom-task-list">${customRewards.map(row=>`<div class="custom-task-row"><span><strong>${esc(row.title)}</strong><small>${row.cost} 颗星</small></span><span><button class="secondary mini" data-edit-reward="${esc(row.item_id)}">修改</button><button class="danger-btn mini" data-delete-reward="${esc(row.item_id)}">删除</button></span></div>`).join("")}</div></div></details>${companionParentPanel()}${encouragementParentPanel()}${gardenParentPanel()}`:""}${roomClaimParentPanel()}<details><summary>重置今日、备份与清空</summary><div class="parent-detail-body"><p>重置今日只撤销今天的身体充电打卡，不改题目记录、家长核验、星星和学习日。清空全部会删除本机所有记录，请先导出。</p><div class="data-actions"><button class="secondary" data-reset-today>重置今日</button><button class="primary" data-export>导出备份</button><button class="secondary" data-import>导入恢复</button>${undoImport?`<button class="secondary" data-undo-import>撤销本次导入</button>`:""}<button class="danger-btn" data-clear>清空全部记录</button></div>${legacy?`<div class="legacy-note">旧版工作台数据已放在 legacy 区，不会误算成当前学习内容的完成记录。</div>`:""}</div></details></div>`}'''


_RENDER = r'''function render(){applyRoom();nav();delete document.body.dataset.contentItemId;document.body.dataset.focusMode=Boolean(ui.contentId||ui.screen);if(ui.contentId)renderContent();else if(ui.screen){const atom=atoms[ui.screen.atomId];if(ui.screen.phase==="teach")renderTeach(atom);else if(ui.screen.phase==="practice")renderPractice(atom);else renderEvidence(atom)}else if(ui.view==="home")renderHome();else if(["语文","数学","英语","阅读"].includes(ui.view))renderWorld(ui.view);else if(ui.view==="repair")renderRepair();else if(ui.view==="collect")renderCollect();else if(ui.view==="science")renderScience();else if(ui.view==="movement")renderMovement();else if(ui.view==="parent"&&ui.adultMode)renderParent();else{ui.view="home";renderHome()}paintRewardChrome()}'''


_LIBRARY = r'''function renderLibrary(){const baseItems=PACK.items.filter(item=>!item.content_role),items=baseItems.filter(item=>ui.contentLevel==="all"||item.level===ui.contentLevel),families=[...new Map(items.map(item=>[item.family_id,item.family_name])).entries()],completed=baseItems.filter(contentDone).length;document.getElementById("app-main").innerHTML=top("路线练习",`${families.length} 类 ${baseItems.length} 个练习`)+`<p class="library-summary">已完成 ${completed}/${baseItems.length}。这里的记录只表示做过，不会改变花园过关或家长核验。</p><div class="level-tabs">${Object.entries(LEVEL_LABELS).filter(([key])=>!["repair","production","offscreen"].includes(key)).map(([key,label])=>`<button data-content-level="${key}" class="${ui.contentLevel===key?"active":""}">${label}</button>`).join("")}</div><div class="family-stack">${families.map(([familyId,familyName])=>`<section class="family-block"><h2>${esc(familyName)}</h2><div class="content-grid">${items.filter(item=>item.family_id===familyId).map(item=>contentCard(item)).join("")}</div></section>`).join("")}</div><div class="boundary"><strong>练习边界</strong><br>这里仅展示 ${baseItems.length} 条基础路线练习；纠错、迁移、主动表达和屏外应用只会在真实触发后进入“修理”或“今天”，不会在练习库直接出现。</div>`}'''


def _patch_reward_state_schema(source: str, default_skin: str = "companion-puppy") -> str:
    skin = default_skin if default_skin in {
        "companion-puppy",
        "companion-panda",
        "companion-plants",
        "companion-ultraman",
    } else "companion-puppy"
    create_anchor = '''      rewards: {
        status: "active",
        custom_items: [],
        redemptions: []
      },'''
    create_replacement = f'''      rewards: {{
        status: "active",
        selected_item_id: null,
        custom_items: [],
        redemptions: [],
        ledger: [],
        badges: [],
        best_combo: 0,
        companion: {{ enabled: true, skin_id: "{skin}" }},
        encouragement: {{ enabled: true }},
        progress: {{ garden_enabled: true }}
      }},'''
    normalize_anchor = '''      base.rewards = {
        status: ["active", "paused", "closed"].includes(value.rewards.status) ? value.rewards.status : "active",
        custom_items: Array.isArray(value.rewards.custom_items) ? clone(value.rewards.custom_items) : [],
        redemptions: Array.isArray(value.rewards.redemptions) ? clone(value.rewards.redemptions) : []
      };'''
    normalize_replacement = f'''      base.rewards = {{
        status: ["active", "paused", "closed"].includes(value.rewards.status) ? value.rewards.status : "active",
        selected_item_id: typeof value.rewards.selected_item_id === "string" ? value.rewards.selected_item_id.slice(0, 200) : null,
        custom_items: Array.isArray(value.rewards.custom_items) ? clone(value.rewards.custom_items) : [],
        redemptions: Array.isArray(value.rewards.redemptions) ? clone(value.rewards.redemptions) : [],
        ledger: Array.isArray(value.rewards.ledger) ? clone(value.rewards.ledger) : [],
        badges: Array.isArray(value.rewards.badges) ? clone(value.rewards.badges) : [],
        best_combo: Number.isInteger(value.rewards.best_combo) ? value.rewards.best_combo : 0,
        companion: {{
          enabled: !value.rewards.companion || value.rewards.companion.enabled !== false,
          skin_id: typeof value.rewards.companion?.skin_id === "string" ? value.rewards.companion.skin_id.slice(0, 80) : "{skin}"
        }},
        encouragement: {{
          enabled: !value.rewards.encouragement || value.rewards.encouragement.enabled !== false
        }},
        progress: {{
          garden_enabled: !value.rewards.progress || value.rewards.progress.garden_enabled !== false
        }}
      }};'''
    if source.count(create_anchor) != 1 or source.count(normalize_anchor) != 1:
        raise ContractError("星星奖励状态兼容锚点缺失")
    return source.replace(create_anchor, create_replacement, 1).replace(
        normalize_anchor, normalize_replacement, 1
    )


def _patch_family_task_schema(source: str) -> str:
    create_anchor = """      family_tasks: [],
      history: [],"""
    create_replacement = """      family_tasks: [],
      family_tasks_enabled: false,
      room_claim: { name: "", belonging_id: "", places: {} },
      history: [],"""
    normalize_anchor = """    base.family_tasks = Array.isArray(value.family_tasks) ? clone(value.family_tasks) : [];
    base.history = Array.isArray(value.history) ? value.history.slice(-500) : [];"""
    normalize_replacement = """    base.family_tasks = Array.isArray(value.family_tasks) ? clone(value.family_tasks) : [];
    base.family_tasks_enabled = value.family_tasks_enabled === true;
    base.room_claim = {
      name: typeof value.room_claim?.name === "string" ? value.room_claim.name.slice(0, 6) : "",
      belonging_id: typeof value.room_claim?.belonging_id === "string" ? value.room_claim.belonging_id.slice(0, 40) : "",
      places: value.room_claim && value.room_claim.places && typeof value.room_claim.places === "object" ? value.room_claim.places : {}
    };
    base.history = Array.isArray(value.history) ? value.history.slice(-500) : [];"""
    if source.count(create_anchor) != 1 or source.count(normalize_anchor) != 1:
        raise ContractError("家庭任务默认关闭状态锚点缺失")
    return source.replace(create_anchor, create_replacement, 1).replace(
        normalize_anchor, normalize_replacement, 1
    )


_CONTENT_CARD = r'''function contentCard(item,reason="",trigger="",skipTeach=false){return `<article class="content-card" data-content-card="${item.item_id}" data-family-id="${esc(item.family_id)}" data-content-level="${esc(item.level)}" data-content-role="${esc(item.content_role||"curated_base")}" ${trigger?`data-adaptive-trigger="${esc(trigger)}"`:""}><div class="content-card-visual" aria-hidden="true">${objectImg(objectForItem(item))}</div>${STAGE_OVERLAY?"":`<div class="content-meta"><span class="content-chip">${esc(item.family_name)}</span></div>`}<h3>${esc(kidTitle(item.title))}</h3><p>${esc(item.objective)}</p>${reason?`<p class="followup-reason">${esc(reason)}</p>`:""}<button class="primary" data-open-content="${item.item_id}"${skipTeach?" data-skip-teach":""}>${contentDone(item)?"再玩一次":"去玩"}</button></article>`}'''


_CONTENT_STIMULUS = r'''function contentStimulus(item){const p=item.presentation||{};if(item.kind==="arithmetic"){const token=item.render_contract.object_token||p.hero||"🍎";return (item.render_contract.object_counts||[]).map((n,i)=>`<div class="content-bridge-step"><div>${esc((p.snapshot_labels||p.stimulus_lines||[])[i]||"数一数")}</div><div class="content-object-row">${Array.from({length:n},()=>objectImg(token)).join("")}</div></div>`).join("")}if(item.kind==="classification")return `<div class="content-object-row" data-semantic-values="${esc(item.render_contract.rendered_values.join(","))}">${item.oracle.displayed_objects.map(x=>objectImg(x.value,p.semantic_labels[x.value]||CONTENT_LABELS[x.value]||x.value)).join("")}</div>`;if(item.kind==="sequence")return `<div class="content-object-row" data-semantic-values="${esc(item.render_contract.rendered_values.join(","))}">${item.oracle.pattern.map(x=>objectImg(x,p.semantic_labels[x]||CONTENT_LABELS[x]||x)).join("")}<strong>?</strong></div>`;if(item.kind==="reading_evidence")return `<div class="content-passage">${esc(item.oracle.passage)}</div>${p.hint?`<p>${esc(p.hint)}</p>`:""}`;if(item.kind==="poetry_mapping")return `<div class="content-passage"><strong>${esc(item.oracle.source_text.title)} · ${esc(item.oracle.source_text.author)}</strong><br>${item.oracle.source_text.lines.map(esc).join("<br>")}</div>`;if(item.kind==="offscreen_action")return `<div class="content-passage">${(p.action_lines||[]).map(x=>`<div>${esc(x)}</div>`).join("")}</div>`;const lines=(p.pre_action_lines||p.stimulus_lines||(item.story?[item.story]:[])).filter(Boolean);return lines.length?`<div class="content-passage">${lines.map(x=>`<div>${esc(x)}</div>`).join("")}</div>`:""}'''


_CONTENT_CONTROLS = r'''function optionIsShort(option){const label=String((option&&option.label)||(option&&option.value)||"").trim();return label.length>0&&label.length<=4&&!/\s/.test(label)}
function optionFace(option){const label=String((option&&option.label)||(option&&option.value)||"");if(optionIsShort(option))return `<span class="option-picture option-letter" data-letter-len="${[...label].length}" aria-hidden="true">${esc(label)}</span>`;if(option&&option.icon)return `<span class="option-picture" aria-hidden="true">${option.icon}</span><span class="option-label">${esc(label)}</span>`;return esc(label)}
function optionButton(option){const picture=Boolean((option&&option.icon)||optionIsShort(option));return `<button class="option${picture?" is-picture":""} ${ui.contentSelection===String(option.value)?"selected":""}" data-content-answer="${esc(option.value)}" aria-label="${esc(option.semantic||option.label||option.value)}">${optionFace(option)}</button>`}
function sameTypePool(item){if(!item||!item.stage_item)return[];const focus=(item.teach&&item.teach.focus)||"";if(focus){const same=PACK.items.filter(row=>row.stage_item&&(row.teach&&row.teach.focus)===focus);if(same.length)return same}const family=item.family_id||"";return family?PACK.items.filter(row=>row.stage_item&&row.family_id===family):[]}
function groupDone(item){const pool=sameTypePool(item);return pool.length?pool.every(contentDone):contentDone(item)}
function groupProgress(item){const pool=sameTypePool(item);return pool.length?`${pool.filter(contentDone).length}/${pool.length}`:(contentDone(item)?"1/1":"0/1")}
function nextSameTypeItem(item){const pool=sameTypePool(item);const undone=pool.filter(row=>row.item_id!==item.item_id&&!contentDone(row));if(!undone.length)return null;const index=pool.findIndex(row=>row.item_id===item.item_id);return undone.find(row=>pool.indexOf(row)>index)||undone[0]}
function nextGroupItem(item){if(!item||!item.stage_item)return null;const poolIds=new Set(sameTypePool(item).map(row=>row.item_id));return PACK.items.find(row=>row.stage_item&&row.family_id===item.family_id&&!poolIds.has(row.item_id)&&!contentDone(row))||null}
function sameTypeGroupHtml(item){const next=nextSameTypeItem(item);if(next)return `<button class="primary" data-open-content="${esc(next.item_id)}" data-skip-teach data-same-type-next>下一题</button>`;const more=nextGroupItem(item);if(!more)return `<button class="primary" data-close-content data-same-type-next>这组做完了，回去</button>`;return `<div class="same-type-more" data-group-done><p>这一组做完了。</p><button class="primary" data-close-content data-same-type-next>回去休息</button><button class="secondary" data-open-content="${esc(more.item_id)}" data-scene-more>还想再玩一组</button></div>`}
function nextSameTypeHtml(item){if(!item||!item.stage_item)return"";return sameTypeGroupHtml(item)}
function sameTypeProgressHtml(item){const pool=sameTypePool(item);if(pool.length<2)return"";const index=Math.max(1,pool.findIndex(row=>row.item_id===item.item_id)+1);return `<p class="same-type-progress" data-same-type-progress aria-label="这组第 ${index} 题，一共 ${pool.length} 题">${index}/${pool.length}</p>`}
function overlaySceneHtml(item){const story=(item.teach&&item.teach.story)||"",p=item.presentation||{},counts=p.object_counts||[],token=p.object_token||p.hero||"🍪";const visual=counts.length?`<div class="content-object-row" data-overlay-scene>${counts.map(n=>`<span class="scene-group">${Array.from({length:Math.min(Number(n)||0,8)},()=>objectImg(token)).join("")}</span>`).join('<span class="scene-plus" aria-hidden="true">+</span>')}</div>`:"";return `${story?`<p class="teach-story" data-item-story>${esc(story)}</p>`:""}${visual}`}
function renderStagePractice(item){const presentation=item.presentation||{},hero=presentation.hero||objectForItem(item)||"🌼",feedback=contentFeedbackHtml(item);document.body.dataset.contentItemId=item.item_id;document.body.dataset.responseMode=item.response_mode||"legacy";document.getElementById("app-main").innerHTML=`<div class="lesson"><button class="back" data-close-content>← ${ui.contentOrigin==="home"?"返回今天":"返回"}</button><section class="practice is-kid" data-stage-practice data-item-id="${esc(item.item_id)}">${sameTypeProgressHtml(item)}<div class="content-hero is-picture" aria-hidden="true">${objectImg(hero)}</div><h2>${esc(item.title)}</h2>${overlaySceneHtml(item)}<div class="prompt">${esc(item.prompt)}</div>${contentControls(item)}${feedback}${feedback?nextSameTypeHtml(item):""}</section></div>`;if(item.response_mode==="handwriting_canvas")bindContentCanvas()}
function contentControls(item){const mode=item.response_mode;if(!mode){const options=(item.options||[]).map(optionButton).join("");return item.mode==="offscreen_action"?`<div class="content-done"><button class="primary" data-content-child-done>我完成了</button></div>${ui.contentGuardianStarted?`<div class="guardian-confirm"><label><input type="checkbox" data-content-guardian-check> 家长已在现场查看</label><button class="primary" data-content-guardian-confirm disabled>家长确认完成</button></div>`:""}`:`<div class="options">${options}</div>`}const c=item.interaction_contract||{};if(mode==="single_choice")return `<div class="options">${item.options.map(optionButton).join("")}</div>`;if(mode==="number_input")return `<div class="content-controls"><div class="content-number" aria-label="当前数字答案">${esc(ui.contentNumber||"?")}</div><div class="keypad">${[1,2,3,4,5,6,7,8,9,"清空",0,"退格"].map(key=>`<button class="key" data-content-key="${key}">${key}</button>`).join("")}</div><button class="primary" data-content-submit>提交答案</button></div>`;if(mode==="ordered_tokens"){const display=c.display_order||c.tokens||[],target=(c.correct_order||item.oracle.answer||[]).map(String);return `<div class="content-controls">${orderSlotsHtml(target,ui.contentOrder)}<p class="writing-note">按原文顺序填空，高亮当前空。空位不显示答案。</p><div class="content-token-bank">${display.map(value=>`<button class="content-token" data-content-token="${esc(value)}" ${ui.contentOrder.includes(String(value))?"disabled":""}>${esc(value)}</button>`).join("")}</div><div class="content-action-row"><button class="secondary" data-content-reset>重新排</button><button class="primary" data-content-submit>提交顺序</button></div></div>`}if(mode==="letter_tiles"||mode==="phrase_blocks"){const rows=mode==="letter_tiles"?c.tiles:c.blocks,ids=(mode==="letter_tiles"?c.correct_tile_ids:c.correct_block_ids)||[],labelOf=id=>(rows.find(row=>String(row.id)===String(id))||{}).label||id;return `<div class="content-controls">${orderSlotsHtml(ids,ui.contentOrder,labelOf)}<p class="writing-note">按原文顺序填空，高亮当前空。空位不显示答案。</p><div class="content-token-bank">${rows.map(row=>`<button class="content-piece" data-content-piece="${esc(row.id)}" ${ui.contentOrder.includes(String(row.id))?"disabled":""}>${esc(row.label)}</button>`).join("")}</div><div class="content-action-row"><button class="secondary" data-content-reset>重新拼</button><button class="primary" data-content-submit>完成</button></div></div>`}if(mode==="handwriting_canvas")return `<div class="writing-wrap"><canvas class="writing-canvas" width="320" height="320" aria-label="田字格手写板"></canvas><div class="writing-note">只在本页练习，不录音、不上传，也不会自动判字。</div><div class="writing-target ${ui.contentFeedback?.draft?"open":""}">${esc(c.writing_target)}</div><div class="content-action-row"><button class="secondary" data-content-clear>清空重写</button><button class="primary" data-content-submit>写完了</button></div>${ui.contentFeedback?.draft?`<button class="primary" data-content-self-confirm>我对照好了</button>`:""}</div>`;if(mode==="guardian_observation"||mode==="guardian_oral_observation")return `<button class="primary" data-content-child-done>${mode==="guardian_oral_observation"?"我说完了":"孩子已完成"}</button><div class="writing-note">不录音、不上传；家长只按题内标准现场确认。</div><div class="content-guardian ${ui.contentGuardianStarted?"open":""}">${(c.observable_rubric||[]).map(row=>`<label><input type="checkbox" data-content-rubric="${esc(row.criterion_id)}" ${ui.contentGuardianChecks.includes(String(row.criterion_id))?"checked":""}> <span>${esc(row.label)}</span></label>`).join("")}<button class="primary" data-content-guardian-confirm ${(c.observable_rubric||[]).every(row=>ui.contentGuardianChecks.includes(String(row.criterion_id)))?"":"disabled"}>家长确认完成</button></div>`;return""}
'''


_COUNT_VISUAL = r'''function countVisual(item){const v=COUNT_VISUALS[item.item_id];if(!v)return"";let index=0;const one=()=>{const pressed=ui.countMarks.includes(index),current=index++;return `<button type="button" class="visual-object" data-count-mark="${current}" aria-pressed="${pressed}">${objectImg(v.symbol)}</button>`};let body="";if(v.rows)body=v.rows.map(n=>`<div class="visual-row">${Array.from({length:n},one).join("")}</div>`).join("");if(v.groups)body=`<div class="visual-groups">${v.groups.map(n=>`<div class="visual-group">${Array.from({length:n},one).join("")}</div>`).join("")}</div>`;if(v.scatter)body=`<div class="visual-scatter">${Array.from({length:v.scatter},one).join("")}</div>`;return `<div class="stimulus visual-count" data-count-visual="${item.item_id}">${body}<p class="count-progress" aria-live="polite">已点数 ${ui.countMarks.length} 个</p></div>`}'''


_CONTENT_RENDER = r'''function renderContent(){const item=contentItems[ui.contentId];if(!item){ui.contentId=null;return ui.contentOrigin==="home"?renderHome():renderLibrary()}if(STAGE_OVERLAY&&item.stage_item&&ui.contentPhase!=="practice")return renderStageTeach(item);if(STAGE_OVERLAY&&item.stage_item)return renderStagePractice(item);const presentation=item.presentation||{},contract=item.render_contract||{},hero=presentation.hero||objectForItem(item)||"🌼",required=(contract.required_semantics||[]).join(","),stim=contentStimulus(item),heroIsPicture=Boolean(item.stage_item)||!String(stim||"").includes("learning-object"),feedback=contentFeedbackHtml(item);const optionalHint=!item.content_role&&item.mode==="assessment"&&item.cues.length>1;const visibleCues=optionalHint&&!ui.contentHint?item.cues.slice(0,1):item.cues;document.body.dataset.contentItemId=item.item_id;document.body.dataset.responseMode=item.response_mode||"legacy";document.body.dataset.contentRole=item.content_role||"curated_base";document.getElementById("app-main").innerHTML=`<div class="lesson"><button class="back" data-close-content>← ${ui.contentOrigin==="home"?"返回今天":"返回练习库"}</button><section class="practice"><div class="practice-top"><div class="content-meta"><span class="content-chip">${esc(item.level_label)}</span><span class="content-chip ${item.content_role?"adaptive":item.mode==="guided_practice"?"guided":""}">${esc(contentMode(item))}</span></div><span class="state-text">${contentDone(item)?"已经做过":"还没做"}</span></div><div class="content-hero${heroIsPicture?" is-picture":""}" aria-hidden="true">${objectImg(hero)}</div><h2>${esc(item.title)}</h2><div class="kid-cues">${visibleCues.map((cue,index)=>`<div class="kid-cue"><b>${index?"2️⃣":"1️⃣"}</b><span>${esc(cue)}</span></div>`).join("")}</div>${optionalHint&&!ui.contentHint?`<button class="secondary" data-content-hint>需要时看第 2 个提示</button>`:optionalHint?`<div class="hint-box" data-content-hint-used>已打开第 2 个提示</div>`:""}${stim?`<section class="content-stimulus" data-required-semantics="${esc(required)}">${stim}</section>`:""}<div class="prompt">${esc(item.prompt)}</div>${contentControls(item)}${feedback}${nextSameTypeHtml(item)}<p class="content-boundary">完成记录只留在这台设备，不改变花园过关或正式掌握结果。</p></section></div>`;if(item.response_mode==="handwriting_canvas")bindContentCanvas()}'''


_TEACH = r'''function renderTeach(atom){ui.view=atom.subject;const g=guide(atom),demo=atom.atom_id.includes("count-one-to-one")?`<div class="content-object-row">${[0,1,2].map((_,i)=>`<span>${objectImg("🍎",`第 ${i+1} 个苹果`)}<b class="kid-step-number">${i+1}</b></span>`).join("")}</div>`:g.demo;document.getElementById("app-main").innerHTML=`<div class="lesson"><button class="back" data-close-atom>← 返回</button><section class="lesson-title"><p class="eyeline">看一眼就会玩</p><h2>${esc(kidTitle(g.title))}</h2></section><div class="kid-guide" data-kid-guide><div class="kid-demo">${demo}</div><div class="kid-cues">${g.cues.map((c,index)=>`<div class="kid-cue"><b class="kid-step-number">${index+1}</b><span>${esc(c[1])}</span></div>`).join("")}</div></div><div class="practice-actions"><button class="secondary" data-close-atom>先回去</button><button class="primary" data-start-practice>开始玩</button></div></div>`}'''


def _app_source_patch(source: str) -> str:
    source = source.replace(
        'function load(){try{return ENGINE.normalizeState(JSON.parse(localStorage.getItem(KEY)||"null"))}catch(_){return ENGINE.createState()}}',
        'function load(){try{const raw=JSON.parse(localStorage.getItem(KEY)||"null");if(raw&&[2,3].includes(raw.schemaVersion))return migrateLegacy(raw);return ENGINE.normalizeState(raw)}catch(_){return ENGINE.createState()}}',
    )
    source = source.replace(
        'function nav(){document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===ui.view&&!ui.screen&&!ui.contentId))}',
        'function nav(){const activeView=ui.contentId?(ui.contentOrigin||ui.view):ui.view;document.querySelectorAll(".rail [data-view]").forEach(b=>{const active=b.dataset.view===activeView;b.classList.toggle("active",active);if(active)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")})}',
    )
    source = _replace_between(source, "function renderHome()", "function renderSubject", _HELPERS + _COMPANION_JS + _HOME + "\n")
    source = _replace_between(source, "function contentCard", "function renderLibrary", _CONTENT_CARD + "\n")
    source = _replace_between(source, "function renderLibrary()", "function contentStimulus", _LIBRARY + "\n")
    source = _replace_between(source, "function contentStimulus", "function contentControls", _CONTENT_STIMULUS + "\n")
    source = _replace_between(source, "function contentControls", "function renderContent", _CONTENT_CONTROLS + "\n")
    source = _replace_between(source, "function renderContent", "function renderTeach", _CONTENT_RENDER + "\n")
    source = _replace_between(source, "function renderTeach", "function countVisual", _TEACH + "\n")
    source = _replace_between(source, "function countVisual", "function hanziVisual", _COUNT_VISUAL + "\n")
    source = _replace_between(source, "function renderParent()", "function renderData", _PARENT + "\n")
    source = _replace_between(source, "function render(){", "function clearAnswer", _RENDER + "\n")
    ui_anchor = 'let ui={view:state.last_view||"home",screen:null,selection:null,number:"",order:[],feedback:null,hint:false,observe:[],contentId:null,contentOrigin:"library",contentSelection:null,contentFeedback:null,contentGuardianStarted:false,contentGuardianChecks:[],contentOrder:[],contentNumber:"",contentHint:false,contentLevel:"all"}'
    ui_replacement = 'let ui={view:["parent","data"].includes(state.last_view)?"home":state.last_view||"home",screen:null,selection:null,number:"",order:[],feedback:null,hint:false,observe:[],countMarks:[],contentId:null,contentOrigin:"home",contentPhase:null,contentSelection:null,contentFeedback:null,contentGuardianStarted:false,contentGuardianChecks:[],contentOrder:[],contentNumber:"",contentHint:false,contentLevel:"all",adultMode:false,movementAction:null,movementRemaining:0,pendingRewardId:null,worldMode:"practice",calYm:null,calDay:null,collectTab:"shop",sessionCombo:0,lastReward:null,pendingBadges:null}'
    if ui_anchor not in source:
        raise ContractError("儿童乐园 UI 状态锚点缺失")
    source = source.replace(ui_anchor, ui_replacement, 1)
    source = source.replace(
        'function clearAnswer(){document.querySelectorAll(".leaf-burst").forEach(node=>node.remove());ui.selection=null;ui.number="";ui.order=[];ui.feedback=null;ui.hint=false;ui.observe=[]}',
        'function clearAnswer(){document.querySelectorAll(".leaf-burst").forEach(node=>node.remove());ui.selection=null;ui.number="";ui.order=[];ui.feedback=null;ui.hint=false;ui.observe=[];ui.countMarks=[]}',
        1,
    )
    click_anchor = 'if(t.dataset.view){ui.view=t.dataset.view;state.last_view=ui.view;ui.screen=null;ui.contentId=null;save();render();return goTop()}'
    click_extra = r'''if(t.dataset.view==="parent"){if(!confirm("这里有备份、清空和家庭设置。请由家长操作。"))return;ui.adultMode=true;ui.view="parent";state.last_view="home";ui.screen=null;ui.contentId=null;save();render();return goTop()}
if(t.dataset.world){ui.view=t.dataset.world;state.last_view=ui.view;ui.screen=null;ui.contentId=null;save();render();return goTop()}
if(t.dataset.countMark!==undefined&&!ui.feedback){const id=Number(t.dataset.countMark),pos=ui.countMarks.indexOf(id);if(pos>=0)ui.countMarks.splice(pos,1);else ui.countMarks.push(id);ui.number=String(ui.countMarks.length);render();return}
if(t.dataset.movementStart!==undefined){const id=Number(t.dataset.movementStart);ui.movementAction=id;ui.movementRemaining=MOVEMENT_ACTIONS[id][2];render();return}
if(t.dataset.movementStop!==undefined){clearInterval(window.__movementTimer);ui.movementAction=null;ui.movementRemaining=0;render();return}
if(t.dataset.movementFinish!==undefined){const id=ui.movementAction;if(id!==null&&!movementDone(id)){state.history.push({event:"movement_completed",action_id:id,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("身体充电完成")}ui.movementAction=null;ui.movementRemaining=0;render();return}
if(t.dataset.selectReward!==undefined){const row=availableRewards().find(item=>item.item_id===t.dataset.selectReward);if(!row)return;state.rewards.selected_item_id=row.item_id;save();toast("已设为目标奖励");render();return}
if(t.dataset.redeem!==undefined){const row=availableRewards().find(item=>item.item_id===t.dataset.redeem),stats=rewardStats();if(!row||state.rewards.status!=="active")return toast("奖励约定当前不可兑换");if(stats.balance<row.cost)return toast("星星还不够");ui.pendingRewardId=row.item_id;render();return goTop()}
if(t.dataset.cancelRedeem!==undefined){ui.pendingRewardId=null;render();return}
if(t.dataset.confirmRedeem!==undefined){const row=availableRewards().find(item=>item.item_id===ui.pendingRewardId),stats=rewardStats();if(!row||state.rewards.status!=="active"||stats.balance<row.cost){ui.pendingRewardId=null;render();return toast("奖励状态或星星数量已经变化，请重新确认")}const at=new Date().toISOString(),redemptionId=`reward-${Date.now()}`;state.rewards.redemptions.push({redemption_id:redemptionId,item_id:row.item_id,title:row.title,cost:row.cost,at});state.history.push({event:"reward_redeemed",redemption_id:redemptionId,item_id:row.item_id,title:row.title,cost:row.cost,affects_mastery:false,at});state.history=state.history.slice(-500);ui.pendingRewardId=null;ui.pendingBadges=checkBadges();save();toast("兑换已记录，请家长兑现约定");render();return}
if(t.dataset.collectTab){ui.collectTab=t.dataset.collectTab;ui.pendingBadges=null;if(ui.view!=="collect"){ui.view="collect";state.last_view="collect"}render();return goTop()}
if(t.dataset.shopCat){ui.shopCat=t.dataset.shopCat;render();return}
if(t.dataset.dismissBadge!==undefined){ui.pendingBadges=null;render();return}
if(t.dataset.rewardStatus){state.rewards.status=t.dataset.rewardStatus;state.history.push({event:"reward_status_changed",status:state.rewards.status,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast(state.rewards.status==="active"?"奖励已恢复":state.rewards.status==="paused"?"奖励已暂停":"奖励已关闭");render();return}
if(t.dataset.companionEnabled!==undefined){state.rewards.companion=companionPrefs();state.rewards.companion.enabled=t.dataset.companionEnabled==="true";state.history.push({event:"companion_enabled_changed",enabled:state.rewards.companion.enabled,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast(state.rewards.companion.enabled?"伙伴已打开":"伙伴已关掉，儿童页不再出现");render();return}
if(t.dataset.companionSkin){state.rewards.companion=companionPrefs();state.rewards.companion.skin_id=t.dataset.companionSkin;state.history.push({event:"companion_skin_changed",skin_id:t.dataset.companionSkin,room_id:(ASSETS.skin_to_room||{})[t.dataset.companionSkin]||"",affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("已换房间，颜色、房子和伙伴一起换了，进度和星星不变");render();return}
if(t.dataset.roomClaimSave!==undefined){const next=sanitizeRoomName((document.querySelector("[data-room-claim-name-input]")||{}).value);if(!next)return toast("换一个短称呼，不要写授权名字");state.room_claim=Object.assign(state.room_claim||{},roomClaimPrefs(),{name:next});state.history.push({event:"room_claim_name_changed",has_name:true,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("门牌写好了，只留在这台设备");render();return}
if(t.dataset.roomClaimClear!==undefined){state.room_claim=roomClaimPrefs();state.room_claim.name="";state.history.push({event:"room_claim_name_changed",has_name:false,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("门牌回到「我的房间」");render();return}
if(t.dataset.warmEnabled!==undefined){state.rewards.encouragement=state.rewards.encouragement||{enabled:true};state.rewards.encouragement.enabled=t.dataset.warmEnabled==="true";state.history.push({event:"warm_incorrect_changed",enabled:state.rewards.encouragement.enabled,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast(state.rewards.encouragement.enabled?"答错也暖已打开":"答错也暖已关掉");render();return}
if(t.dataset.gardenEnabled!==undefined){state.rewards.progress=state.rewards.progress||{garden_enabled:true};state.rewards.progress.garden_enabled=t.dataset.gardenEnabled==="true";state.history.push({event:"garden_progress_changed",enabled:state.rewards.progress.garden_enabled,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast(state.rewards.progress.garden_enabled?"花园条已打开":"花园条已关掉");render();return}
if(t.dataset.editReward){const row=state.rewards.custom_items.find(item=>item.item_id===t.dataset.editReward&&!item.deleted);if(!row)return;const title=prompt("修改奖励名称",row.title);if(title===null)return;const cost=Number(prompt("修改需要的星星数",String(row.cost)));if(!title.trim()||!Number.isInteger(cost)||cost<1||cost>200)return toast("请输入 1–200 的整数星星数");row.title=title.trim();row.cost=cost;row.updated_at=new Date().toISOString();save();toast("自定义奖励已修改");render();return}
if(t.dataset.deleteReward){const row=state.rewards.custom_items.find(item=>item.item_id===t.dataset.deleteReward&&!item.deleted);if(row&&confirm(`删除“${row.title}”吗？既有兑换记录仍会保留。`)){row.deleted=true;row.updated_at=new Date().toISOString();if(state.rewards.selected_item_id===row.item_id)state.rewards.selected_item_id=null;save();toast("自定义奖励已删除");render()}return}
if(t.dataset.worldMode){ui.worldMode=t.dataset.worldMode;render();return goTop()}
if(t.dataset.resetToday!==undefined){if(!confirm("只撤销今天的身体充电打卡。题目记录、家长核验、星星和历史学习日都不会改。继续吗？"))return;resetTodaySession();save();toast("今日打卡已重置");render();return goTop()}
if(t.dataset.familyTasksEnabled!==undefined){state.family_tasks_enabled=t.dataset.familyTasksEnabled==="true";state.history.push({event:"family_tasks_toggled",enabled:state.family_tasks_enabled,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast(state.family_tasks_enabled?"家庭任务已打开":"家庭任务已关闭");render();return}
if(t.dataset.deleteFamilyTask){const id=t.dataset.deleteFamilyTask;if(!confirm("删除这个家庭任务？不会改学习记录。"))return;state.family_tasks=(state.family_tasks||[]).filter(row=>row.task_id!==id);state.history.push({event:"family_task_deleted",task_id:id,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("家庭任务已删除");render();return}
if(t.dataset.familyTaskToggle){const id=t.dataset.familyTaskToggle;if(!familyTasksEnabled())return;if(familyTaskDone(id))return toast("今天已经记下了，重置今日可撤销");state.history.push({event:"family_task_checked",task_id:id,affects_mastery:false,at:new Date().toISOString()});state.history=state.history.slice(-500);save();toast("已记下，不加星星");render();return}
if(t.dataset.calShift!==undefined){shiftFactCalendar(t.dataset.calShift);render();return}
if(t.dataset.calDay){ui.calDay=t.dataset.calDay;render();return}
''' + click_anchor
    if click_anchor not in source:
        raise ContractError("儿童乐园点击事件锚点缺失")
    source = source.replace(click_anchor, click_extra, 1)
    old_open_content = 'if(t.dataset.openContent){ui.contentOrigin=ui.view==="home"?"home":"library";ui.contentId=t.dataset.openContent;resetContentAnswer();history.replaceState(null,"",`?content=${encodeURIComponent(ui.contentId)}`);render();return goTop()}'
    new_open_content = 'if(t.dataset.openContent){ui.contentOrigin=ui.view;ui.contentId=t.dataset.openContent;ui.contentPhase=STAGE_OVERLAY&&t.dataset.skipTeach===undefined?"teach":"practice";resetContentAnswer();history.replaceState(null,"",`?content=${encodeURIComponent(ui.contentId)}`);render();return goTop()}'
    old_close_content = 'if(t.dataset.closeContent!==undefined){ui.contentId=null;resetContentAnswer();ui.view=ui.contentOrigin==="home"?"home":"library";history.replaceState(null,"",location.pathname);render();return goTop()}'
    new_close_content = 'if(t.dataset.startContentPractice!==undefined&&!t.dataset.openContent){ui.contentPhase="practice";render();return goTop()}if(t.dataset.closeContent!==undefined){ui.contentId=null;ui.contentPhase=null;resetContentAnswer();ui.view=ui.contentOrigin||"home";history.replaceState(null,"",location.pathname);render();return goTop()}'
    if old_open_content not in source or old_close_content not in source:
        raise ContractError("儿童乐园内容来源返回锚点缺失")
    source = source.replace(old_open_content, new_open_content, 1).replace(old_close_content, new_close_content, 1)
    old_back_label = '${ui.contentOrigin==="home"?"返回今天":"返回练习库"}'
    new_back_label = '${({home:"返回首页",repair:"返回错题复习",science:"返回科学实验室","语文":"返回语言魔法屋","数学":"返回数学闯关岛","英语":"返回英语游乐场","阅读":"返回故事剧场"}[ui.contentOrigin]||"返回上一页")}'
    if old_back_label not in source:
        raise ContractError("儿童乐园内容返回文案锚点缺失")
    source = source.replace(old_back_label, new_back_label, 1)
    change_anchor = 'document.addEventListener("change",e=>{'
    submit_listener = r'''document.addEventListener("submit",e=>{const taskForm=e.target.closest("[data-custom-task-form]"),rewardForm=e.target.closest("[data-custom-reward-form]"),starForm=e.target.closest("[data-star-adjust-form]");if(!taskForm&&!rewardForm&&!starForm)return;e.preventDefault();if(starForm){if(!REWARD_ENABLED)return toast("当前没有启用奖励");const stars=Number(new FormData(starForm).get("stars")),reason=String(new FormData(starForm).get("reason")||"").trim();if(!Number.isInteger(stars)||stars===0||stars<-50||stars>50)return toast("请输入 -50 到 50 的非零整数");if(stars<0&&rewardStats().balance+stars<0)return toast("可用星星不够扣");if(!confirm(stars>0?`给孩子加 ${stars} 颗星？`:`扣掉 ${-stars} 颗星？扣减可再加回去。`))return;postRewardLedger("parent_adjust",stars,`parent:${Date.now()}`,reason||"家长调整");ui.pendingBadges=checkBadges();save();starForm.reset();toast(stars>0?`已奖励 ${stars} 颗星`:`已扣减 ${-stars} 颗星`);render();return}const form=taskForm||rewardForm,data=new FormData(form),title=String(data.get("title")||"").trim();if(!title)return;if(taskForm){if(!familyTasksEnabled())return toast("请先打开家庭任务");const at=new Date().toISOString();state.family_tasks.push({task_id:`family-${Date.now()}`,title,due:String(data.get("due")||""),details:String(data.get("details")||""),at});state.history.push({event:"family_custom_task_created",title,affects_mastery:false,at});state.history=state.history.slice(-500);save();form.reset();toast("家庭任务已加入");render();return}const cost=Number(data.get("cost"));if(!Number.isInteger(cost)||cost<1||cost>200)return toast("请输入 1–200 的整数星星数");state.rewards.custom_items.push({item_id:`custom-reward-${Date.now()}`,title,cost,created_at:new Date().toISOString()});save();form.reset();toast("自定义奖励已加入");render()});
'''
    if change_anchor not in source:
        raise ContractError("儿童乐园表单事件锚点缺失")
    source = source.replace(change_anchor, submit_listener + change_anchor, 1)
    old_import = 'if(data.schema_version!==1||data.format!=="small-garden-learning-backup"||!data.state)throw Error("invalid");if(!confirm("导入会替换当前本机进度。继续吗？"))return;undoImport=state;state=ENGINE.normalizeState(data.state);'
    new_import = 'let imported;if(data.schema_version===1&&data.format==="small-garden-learning-backup"&&data.state)imported=ENGINE.normalizeState(data.state);else if(data&&[2,3].includes(data.schemaVersion))imported=migrateLegacy(data);else throw Error("invalid");if(!confirm("导入会替换当前本机进度。继续吗？"))return;undoImport=state;state=imported;'
    if old_import not in source:
        raise ContractError("儿童乐园导入恢复锚点缺失")
    source = source.replace(old_import, new_import, 1)
    old_content_token = 'if(t.dataset.contentToken!==undefined){ui.contentOrder.push(String(t.dataset.contentToken));return render()}\nif(t.dataset.contentPiece!==undefined){ui.contentOrder.push(String(t.dataset.contentPiece));return render()}'
    new_content_token = 'if(t.dataset.contentToken!==undefined){const item=contentItems[ui.contentId],c=item.interaction_contract||{},target=(c.correct_order||item.oracle.answer||[]).map(String);if(!fillCurrentOrderSlot(String(t.dataset.contentToken),target))toast("先填高亮的空");return render()}\nif(t.dataset.contentPiece!==undefined){const item=contentItems[ui.contentId],c=item.interaction_contract||{},ids=item.response_mode==="letter_tiles"?c.correct_tile_ids:c.correct_block_ids;if(!fillCurrentOrderSlot(String(t.dataset.contentPiece),(ids||[]).map(String)))toast("先填高亮的空");return render()}'
    if old_content_token not in source:
        raise ContractError("儿童乐园填空点选锚点缺失")
    source = source.replace(old_content_token, new_content_token, 1)
    old_order_add = 'if(t.dataset.orderAdd!==undefined){ui.order.push(t.dataset.orderAdd);return render()}'
    new_order_add = 'if(t.dataset.orderAdd!==undefined){const atom=atoms[ui.screen.atomId],item=atom.practice.items[ENGINE.ensureAtomRound(state,atom.atom_id).item_index];if(!fillCurrentAtomSlot(t.dataset.orderAdd,item.correct_answer||[]))toast("先填高亮的空");return render()}'
    if old_order_add not in source:
        raise ContractError("儿童乐园过关排序锚点缺失")
    source = source.replace(old_order_add, new_order_add, 1)
    old_atom_order = 'if(item.response_mode==="ordered_tokens"){const source=item.stimulus.tokens.filter(t=>!ui.order.includes(t));return `<div class="order-answer">${ui.order.map(t=>`<button class="token" data-order-remove="${esc(t)}">${esc(t)}</button>`).join("")||"依次点下面的词块"}</div><div class="options">${source.map(t=>`<button class="token" data-order-add="${esc(t)}">${esc(t)}</button>`).join("")}</div>`}'
    new_atom_order = 'if(item.response_mode==="ordered_tokens"){const target=item.correct_answer||[],source=(item.stimulus.tokens||[]).filter(t=>!ui.order.includes(t));return `<div class="content-controls">${orderSlotsHtml(target,ui.order)}<p class="writing-note">按原文顺序填空，高亮当前空。空位不显示答案。</p><div class="options">${source.map(t=>`<button class="token" data-order-add="${esc(t)}">${esc(t)}</button>`).join("")}</div></div>`}'
    if old_atom_order not in source:
        raise ContractError("儿童乐园过关填空表面锚点缺失")
    source = source.replace(old_atom_order, new_atom_order, 1)
    old_direct_content = 'const directContent=new URLSearchParams(location.search).get("content");if(directContent&&contentItems[directContent]){ui.view="library";ui.contentOrigin="library";ui.contentId=directContent}'
    new_direct_content = 'const directContent=new URLSearchParams(location.search).get("content");if(directContent&&contentItems[directContent]){const directItem=contentItems[directContent],baseItems=PACK.items.filter(item=>!item.content_role),pathDay=ENGINE.dailyLearningPathPack(state,baseItems,LEARNING_PATH),follow=ENGINE.adaptiveFollowUpPack(state,PACK.items,LEARNING_PATH,pathDay.item_ids,CATALOG.atoms);if(!directItem.content_role||follow.item_ids.includes(directContent)){const origin=directItem.content_role?"repair":subjectForItem(directItem);ui.view=origin;ui.contentOrigin=origin;ui.contentId=directContent}}'
    if old_direct_content not in source:
        raise ContractError("儿童乐园内容直达锚点缺失")
    source = source.replace(old_direct_content, new_direct_content, 1)
    old_clear = 'if(t.dataset.clear!==undefined){if(confirm("清空这台设备上的全部学习记录吗？此操作无法自动恢复，请先导出备份。")){state=ENGINE.createState();localStorage.removeItem(KEY);ui.view="home";ui.screen=null;ui.contentId=null;toast("本机记录已清空");render();goTop()}return}});'
    new_clear = 'if(t.dataset.clear!==undefined){if(confirm("这会删除全部学习记录、星星、家长核验和历史打卡，不能自动恢复。如果只想撤销今天的身体充电，请用「重置今日」。确定清空全部？")){state=ENGINE.createState();localStorage.removeItem(KEY);ui.view="home";ui.screen=null;ui.contentId=null;toast("本机记录已清空");render();goTop()}return}});'
    if old_clear not in source:
        raise ContractError("儿童乐园清空全部锚点缺失")
    source = source.replace(old_clear, new_clear, 1)
    old_burst = 'function burst(){const xs=[-100,-60,-20,30,70,110],ys=[-120,-85,-140,-95,-130,-70];document.getElementById("toast-root").insertAdjacentHTML("beforeend",`<div class="leaf-burst">${xs.map((x,i)=>`<span class="leaf" style="--x:${x}px;--y:${ys[i]}px">🍃</span>`).join("")}</div>`);setTimeout(()=>document.querySelector(".leaf-burst")?.remove(),1000)}'
    old_top = 'function top(title,eyeline){return `<div class="topline"><div>${eyeline?`<p class="eyeline">${esc(eyeline)}</p>`:""}<h1>${esc(title)}</h1></div><p class="mode-note">进度留在这台设备</p></div>`}'
    new_top = 'function top(title,eyeline){return `<div class="topline"><div>${eyeline?`<p class="eyeline">${esc(eyeline)}</p>`:""}<h1>${esc(title)}</h1></div>${rewardHud()||`<p class="mode-note">进度留在这台设备</p>`}</div>`}'
    if old_top not in source:
        raise ContractError("儿童乐园顶部激励条锚点缺失")
    source = source.replace(old_top, new_top, 1)
    if old_burst not in source:
        raise ContractError("儿童乐园庆祝反馈锚点缺失")
    record_anchor = 'function recordContent(item,correct,extra={}){ENGINE.recordContentAttempt(state,item,{correct,hint_used:ui.contentHint,path_ordinal:ENGINE.currentLearningOrdinal(state),...extra});save()}'
    record_replacement = 'function recordContent(item,correct,extra={}){ENGINE.recordContentAttempt(state,item,{correct,hint_used:ui.contentHint,path_ordinal:ENGINE.currentLearningOrdinal(state),...extra});noteAnswer(correct,item);save()}'
    if record_anchor not in source:
        raise ContractError("儿童乐园作答记账锚点缺失")
    source = source.replace(record_anchor, record_replacement, 1)
    attempt_anchor = "ENGINE.recordAttempt(state,atom,item,{correct,hint_used:ui.hint});save();"
    attempt_replacement = "ENGINE.recordAttempt(state,atom,item,{correct,hint_used:ui.hint});noteAnswer(correct,item);save();"
    if attempt_anchor not in source:
        raise ContractError("儿童乐园过关作答锚点缺失")
    source = source.replace(attempt_anchor, attempt_replacement, 1)
    return source.replace(old_burst, 'function burst(){document.querySelectorAll(".leaf-burst,.star-burst").forEach(node=>node.remove());const award=ui.lastReward,msg=award&&award.message?award.message:"完成啦！";toast(msg);const n=award&&award.combo>=3?16:10,root=document.getElementById("toast-root");if(root){root.insertAdjacentHTML("beforeend",`<div class="star-burst">${Array.from({length:n},(_,i)=>`<span style="--x:${[-90,-50,-10,30,70,110,-70,20,80,-30][i%10]}px;--y:${[-120,-80,-140,-90,-130,-70,-100,-60,-150,-85][i%10]}px">⭐</span>`).join("")}</div>`);setTimeout(()=>document.querySelector(".star-burst")?.remove(),1000)}if(award&&award.unlocked&&award.unlocked.length){ui.pendingBadges=award.unlocked;if(ui.view==="collect")render()}}', 1)


def render_child_playground(
    product: dict[str, Any],
    design: dict[str, Any],
    build_id: str,
    storage_key: str,
) -> tuple[str, dict[str, Any]]:
    """生成严格单文件候选，并返回学习内容选择合同。"""
    source_path = _source_html()
    if not source_path.is_file():
        raise ContractError(f"缺少 v1.7.2 正式产品候选：{source_path}")
    source = source_path.read_text(encoding="utf-8")
    selection = _selection_from_product(product)
    stage_id = _learning_stage_id(product)
    stage_overlay = stage_id in STAGE_PLAYABLE_OVERLAYS
    stage_items = _stage_pack_items(stage_id) if stage_overlay else []
    selected_module_ids = set(product["recommendation_plan"].get("selected_core_module_ids") or [])
    reward_enabled = "education-rewards" in selected_module_ids
    reward_economy = _reward_economy(product) if reward_enabled else {"shop": [], "badges": []}
    if stage_overlay:
        selection = {
            **selection,
            "eligible_item_ids": [item["item_id"] for item in stage_items],
            "core_item_ids": [item["item_id"] for item in stage_items],
            "base_path_item_ids": [item["item_id"] for item in stage_items],
            "adaptive_item_ids": [],
            "selection_mode": "stage_playable_overlay",
            "learning_path_id": f"{stage_id}-today-three-v1",
        }
        selection.pop("selection_sha256", None)
        selection["selection_sha256"] = digest_bytes(canonical(selection))
    effective_item_count = len(selection["eligible_item_ids"])
    source = _filter_formal_sources(source, selection)
    if stage_overlay:
        source, selection = _apply_stage_playable_overlay(source, selection, stage_items, stage_id)
        effective_item_count = len(selection["eligible_item_ids"])
    source = _patch_reward_state_schema(source, _stage_face(stage_id).get("default_skin", "companion-puppy"))
    source = _patch_family_task_schema(source)
    _, _, filtered_catalog = _extract_assignment(source, "CONTENT_CATALOG", "CONTENT_EXPANSION")
    selected_subjects = {str(atom.get("subject")) for atom in filtered_catalog.get("atoms", [])}
    eligible_item_ids = set(selection["eligible_item_ids"])
    p_start, p_end, formal_product = _extract_assignment(source, "PRODUCT", "CONTENT_CATALOG")
    del p_start, p_end
    formal_product = deepcopy(formal_product)
    formal_product["product_id"] = product["product_id"]
    formal_product["title"] = product["title"]
    formal_product["recommendation_plan"]["learning_stage"] = dict(
        (product.get("recommendation_plan") or {}).get("learning_stage") or {}
    )
    formal_product["facts"].update({
        "integrated_content_item_count": effective_item_count,
        "full_catalog_item_count": FORMAL_ITEM_COUNT if not stage_overlay else effective_item_count,
        "reward_exchange_mechanism": "parent_selected_enabled_no_mastery_effect",
        "reward_module_enabled": reward_enabled,
        "builder_renderer": VISUAL_CONTRACT_VERSION,
        "stage_playable_overlay": stage_overlay,
        "learning_stage_id": stage_id,
        "stage_lesson": dict(_STAGE_LESSON.get(stage_id) or {}),
        "stage_face": _stage_face(stage_id),
    })
    formal_product["data_policy"]["storage_key"] = storage_key
    formal_product["recommendation_plan"]["learning_content_selection"] = selection
    formal_product["reward_economy"] = reward_economy
    formal_product["design_brief"].update({
        "direction": "bright_persistent_tab_workbench",
        "navigation": "persistent_left_module_tabs",
        "module_rhythm": "single_active_tab",
        "icon_override": "double6_brand",
    })
    source = _replace_assignment(source, "PRODUCT", "CONTENT_CATALOG", formal_product)
    child_assets = _child_assets()
    reliability_envelope = (
        product.get("recommendation_plan", {})
        .get("capability_supply_snapshot", {})
        .get("reliability_envelope", {})
    )
    composition = (product.get("recommendation_plan") or {}).get("composition_contract") or {}
    composition_pack = composition.get("pack") if isinstance(composition.get("pack"), dict) else {}
    face = _stage_face(stage_id)
    default_room = str(face.get("default_room") or "garden")
    room_hero = child_assets["rooms"].get(default_room, child_assets["rooms"]["garden"])["hero"]
    metadata = (
        f'<div class="app" data-room="{default_room}" data-stage-id="{stage_id}" '
        f'data-stage-face="{face.get("face_id") or "garden-lesson"}" '
        f'style="--playground-hero:url(\'{room_hero}\')" '
        f'data-double6-build-id="{build_id}" data-double6-product-id="{product["product_id"]}" '
        f'data-double6-pack-id="{product["recommendation_plan"]["pack_id"]}" data-double6-renderer-id="child_playground_v2" '
        f'data-double6-visual-contract-version="{VISUAL_CONTRACT_VERSION}" data-double6-learning-content-version="{FORMAL_PRODUCT_VERSION}" '
        f'data-double6-formal-item-count="{effective_item_count}" data-double6-full-catalog-item-count="{FORMAL_ITEM_COUNT}" '
        f'data-double6-reward-module-enabled="{str(reward_enabled).lower()}" '
        f'data-double6-selection-sha256="{selection["selection_sha256"]}" '
        f'data-double6-recommendation-sha256="{product["recommendation_plan"]["recommendation_sha256"]}" '
        f'data-double6-surface-registry-version="{product["recommendation_plan"]["surface_registry_version"]}" '
        f'data-double6-starter-contract-version="{product["recommendation_plan"]["starter_contract_version"]}" '
        f'data-double6-reliability-contract-version="local_delivery_reliability_v1" '
        f'data-double6-reliability-envelope-version="{reliability_envelope.get("contract_version", "")}" '
        f'data-double6-reliability-registry-sha256="{reliability_envelope.get("registry_sha256", "")}" '
        f'data-double6-reliability-envelope-sha256="{reliability_envelope.get("envelope_sha256", "")}" '
        f'data-double6-reliability-envelope-status="{reliability_envelope.get("status", "")}" '
        f'data-double6-reliability-guard-count="{len(reliability_envelope.get("guards", []))}" '
        f'data-double6-reliability-blocked-count="{int(reliability_envelope.get("status_counts", {}).get("blocked", 0))}" '
        f'data-double6-token-id="{design["current"]["token_id"]}" data-double6-template-id="{design["current"]["template_id"]}" '
        f'data-double6-scene-template-id="{design["current"].get("scene_template_id") or "child_learning_quest"}" '
        f'data-double6-composition-contract-version="{composition.get("contract_version") or "none"}" '
        f'data-double6-composition-id="{composition_pack.get("composition_id") or "none"}" '
        f'data-double6-composition-sha256="{composition.get("composition_sha256") or "none"}" '
        f'data-double6-composition-status="{composition.get("activation_status") or "not_registered"}" '
        f'data-double6-visual-kernel-id="vivid_social_workbench_templates_v4" data-double6-scene-id="{design["current"]["scene_id"]}" '
        f'data-double6-experience-signature="{design["current"]["experience_signature"]}" data-dashboard-signature="child-tab-workbench-v1" '
        'data-feedback-collection="none">'
    )
    source = source.replace('<div class="app">', metadata, 1)
    source, head_count = re.subn(
        r'<meta name="theme-color"[\s\S]*?(?=<title>)',
        _pwa_metadata(product) + "\n  ",
        source,
        count=1,
    )
    if head_count != 1:
        raise ContractError("儿童乐园 PWA 元数据锚点缺失")
    nav_html = _nav_html(selected_subjects, selected_module_ids, eligible_item_ids, overlay=stage_overlay)
    source = _replace_between(source, '<nav class="rail" aria-label="主要导航">', '  <main class="main">', nav_html + '\n  <main class="main">')
    source = source.replace(
        "<script>",
        '<script>window.CHILD_ASSETS=' + json.dumps(child_assets, ensure_ascii=False, separators=(",", ":")) + ";",
        1,
    )
    source = source.replace("</head>", _CSS + "</head>", 1)
    source = _app_source_patch(source)
    stage_label = str(((product.get("recommendation_plan") or {}).get("learning_stage") or {}).get("label") or "")
    lesson = _STAGE_LESSON.get(stage_id) or {}
    stage_hint = str(lesson.get("home") or face.get("chip") or "三站就好。伙伴还在等你。")
    source = source.replace(
        'const STAGE_LABEL=(PRODUCT.recommendation_plan&&PRODUCT.recommendation_plan.learning_stage&&PRODUCT.recommendation_plan.learning_stage.label)||"";',
        f"const STAGE_LABEL={json.dumps(stage_label, ensure_ascii=False)};",
        1,
    )
    source = source.replace(
        'const STAGE_HINT="三站就好，答对攒星星，做完可以去左边自由探索。";',
        f"const STAGE_HINT={json.dumps(stage_hint, ensure_ascii=False)};",
        1,
    )
    source = source.replace("<title>小花园学习屋</title>", f"<title>{product['title']}</title>", 1)
    source = source.replace('content="#317048"', 'content="#ff6f68"', 1)
    source = source.replace('</style>', '.app button{min-width:44px!important;min-height:44px!important}.fact-calendar{min-width:0;max-width:100%}.calendar{grid-template-columns:repeat(7,minmax(44px,1fr));overflow-x:auto;max-width:100%}</style>', 1)
    source = source.replace('</head>', '<style>@media(max-width:640px){.app .today-board .today-route{grid-template-columns:minmax(0,1fr);gap:8px}.app .today-board .today-stop{display:grid;grid-template-columns:40px minmax(0,1fr) 78px;gap:4px 8px;align-items:center;padding:10px;min-width:0}.app .today-board .today-stop .task-visual{grid-column:1;grid-row:1/3;width:40px;height:44px;font-size:32px}.app .today-board .today-stop h3{grid-column:2;margin:0;font-size:16px;line-height:1.35;min-width:0;overflow-wrap:break-word}.app .today-board .today-stop p{grid-column:2;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;overflow:hidden;margin:0;font-size:11px;min-width:0}.app .today-board .today-stop button{grid-column:3;grid-row:1/3;white-space:normal;line-height:1.3;padding:7px 6px;width:78px;max-width:100%;font-size:12px}.app .today-board .today-stop .stop-number{display:none}}</style></head>', 1)
    return protect_offline_html(source), selection
