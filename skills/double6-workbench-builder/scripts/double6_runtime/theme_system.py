"""成人主题合同：设计阶段选择，成品只编译一个主题。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .core import ContractError, REFERENCES, canonical, digest_bytes, read_json


REGISTRY_FILE = "adult-theme-system.json"
CONTRACT_VERSION = "double6_adult_theme_contract_v2"
LEGACY_CONTRACT_VERSION = "double6_adult_theme_contract_v1"


def adult_theme_registry() -> dict[str, Any]:
    value = read_json(REFERENCES / REGISTRY_FILE)
    if value.get("schema_version") != "double6-adult-theme-system/v2":
        raise ContractError("成人主题 registry schema 无效")
    selection = value.get("selection_contract")
    if selection != {
        "selection_stage": "design_time",
        "themes_per_candidate": 1,
        "runtime_switching": False,
        "runtime_preference_storage": False,
        "invalid_selection_behavior": "build_fails_closed",
        "asset_failure_behavior": "build_fails_closed",
    }:
        raise ContractError("成人主题必须在设计阶段选择，并且每个成品只编译一个主题")
    families = value.get("families")
    if not isinstance(families, dict) or set(families) != {"life_rooms", "study_companion"}:
        raise ContractError("成人主题必须包含生活房间与学习伙伴两个家族")
    all_ids: set[str] = set()
    for family_id, family in families.items():
        themes = family.get("themes")
        if not isinstance(themes, list) or len(themes) != 3:
            raise ContractError(f"主题家族必须是经典回退加两套皮肤：{family_id}")
        ids = [str(row.get("theme_id") or "") for row in themes]
        if len(ids) != len(set(ids)) or not all(ids):
            raise ContractError(f"主题 ID 无效：{family_id}")
        all_ids.update(ids)
        if family.get("classic_fallback") not in ids or family.get("default_theme") not in ids:
            raise ContractError(f"主题默认值或经典回退未登记：{family_id}")
        for theme in themes:
            if theme.get("family_id") != family_id:
                raise ContractError(f"主题家族绑定错误：{theme.get('theme_id')}")
            for asset in theme.get("assets", []):
                path = REFERENCES / str(asset.get("path") or "")
                if not path.is_file():
                    raise ContractError(f"主题资产缺失：{path}")
                raw = path.read_bytes()
                if len(raw) > int(asset.get("max_bytes") or 0):
                    raise ContractError(f"主题资产超过体积上限：{path}")
                actual = digest_bytes(raw)
                if actual != asset.get("sha256"):
                    raise ContractError(f"主题资产 SHA 漂移：{path}")
    if len(all_ids) != 6:
        raise ContractError("成人主题 ID 必须全局唯一")
    return value


def compile_theme_contract(scene_profile_id: str) -> dict[str, Any] | None:
    registry = adult_theme_registry()
    family_id = registry.get("scene_family_map", {}).get(scene_profile_id)
    if not family_id:
        return None
    family = deepcopy(registry["families"][family_id])
    payload = {
        "schema_version": 2,
        "contract_version": CONTRACT_VERSION,
        "registry_sha256": digest_bytes(canonical(registry)),
        "activation_status": "design_options_compiled",
        "scene_profile_id": scene_profile_id,
        "family_id": family_id,
        "default_theme": family["default_theme"],
        "allowed_themes": [row["theme_id"] for row in family["themes"]],
        "classic_fallback": family["classic_fallback"],
        "semantic_state_mapping": family.get("semantic_state_mapping", {}),
        "room_groups": family.get("room_groups", []),
        "themes": family["themes"],
        "selection_contract": deepcopy(registry["selection_contract"]),
    }
    payload["theme_contract_sha256"] = digest_bytes(canonical(payload))
    return payload


def validate_theme_contract(value: Any, scene_profile_id: str) -> dict[str, Any] | None:
    expected = compile_theme_contract(scene_profile_id)
    if expected is None:
        if value is not None:
            raise ContractError("当前场景不应携带成人主题合同")
        return None
    if not isinstance(value, Mapping):
        raise ContractError("成人主题合同与当前 registry 不一致")
    supplied = dict(value)
    if supplied != expected:
        # 1.1.0 早期候选的产品确认已绑定 v1 合同。构建时只接受其完整
        # 主题 ID 集合并规范化为 v2；不回写已确认的产品合同。
        if not (
            supplied.get("contract_version") == LEGACY_CONTRACT_VERSION
            and supplied.get("scene_profile_id") == scene_profile_id
            and supplied.get("family_id") == expected["family_id"]
            and supplied.get("default_theme") == expected["default_theme"]
            and supplied.get("classic_fallback") == expected["classic_fallback"]
            and supplied.get("allowed_themes") == expected["allowed_themes"]
            and [row.get("theme_id") for row in supplied.get("themes", [])] == expected["allowed_themes"]
        ):
            raise ContractError("成人主题合同与当前 registry 不一致")
    return deepcopy(expected)


def select_design_theme(scene_profile_id: str, requested_theme_id: str | None = None) -> dict[str, Any] | None:
    """在构建前选择一个主题；非法 ID 或资产漂移都直接关闭构建。"""
    contract = compile_theme_contract(scene_profile_id)
    if contract is None:
        if requested_theme_id:
            raise ContractError("当前场景不支持成人主题")
        return None
    selected_id = str(requested_theme_id or contract["default_theme"])
    selected = next((row for row in contract["themes"] if row["theme_id"] == selected_id), None)
    if selected is None:
        raise ContractError(f"设计阶段选择了未知成人主题：{selected_id}")
    return deepcopy(selected)
