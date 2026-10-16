"""统一场景、能力、atom、surface 与 policy 供给合同。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .core import ContractError, REFERENCES, read_json


MATURITY_LEVELS = (
    "catalog_only",
    "contract_ready",
    "executable_ready",
    "release_ready",
)
REFERENCE_FILES = {
    "supply": "capability-supply-contract.json",
    "scenes": "scene-profiles.json",
    "atoms": "atomic-capabilities.json",
    "surfaces": "surface-primitives.json",
    "layout": "layout-system.json",
    "policies": "policy-packs.json",
}


def _registry(name: str) -> dict[str, Any]:
    return read_json(REFERENCES / REFERENCE_FILES[name])


def _unique(rows: list[dict[str, Any]], field: str, registry: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"{registry} 必须包含非空列表")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get(field) or "").strip():
            raise ContractError(f"{registry} 含无效 {field}")
        row_id = str(row[field])
        if row_id in result:
            raise ContractError(f"{registry} 含重复 {field}：{row_id}")
        result[row_id] = row
    return result


def _require_fields(row: dict[str, Any], fields: list[str], row_id: str) -> None:
    missing = [field for field in fields if field not in row or row[field] in (None, "", [])]
    if missing:
        raise ContractError(f"{row_id} 缺少合同字段：{', '.join(missing)}")


def _require_maturity(row: dict[str, Any], row_id: str) -> None:
    if row.get("maturity") not in MATURITY_LEVELS:
        raise ContractError(f"{row_id} maturity 无效")


def validate_capability_supply() -> dict[str, Any]:
    """跨注册表校验 v0.50+ 的共享供给合同，不把编目冒充可执行。"""
    supply = _registry("supply")
    scenes = _registry("scenes")
    atoms = _registry("atoms")
    surfaces = _registry("surfaces")
    layout = _registry("layout")
    policies = _registry("policies")
    content = read_json(REFERENCES / "domain-content-packs.json")
    starters = read_json(REFERENCES / "scene-capability-starters.json")

    if supply.get("contract_version") != "double6_capability_supply_v1":
        raise ContractError("capability supply 合同版本无效")
    if supply.get("maturity_contract", {}).get("ordered_levels") != list(MATURITY_LEVELS):
        raise ContractError("成熟度顺序漂移")
    if supply.get("scope", {}).get("catalog_is_not_execution") is not True:
        raise ContractError("必须明确 catalog 不能冒充 execution")

    packs = _unique(content.get("packs", []), "domain_id", "domain content packs")
    modules_by_domain = {
        domain_id: {str(module["module_id"]): module for module in pack.get("modules", [])}
        for domain_id, pack in packs.items()
    }
    capability_ids = {
        str(capability["capability_id"])
        for scene in starters.get("scenes", [])
        for capability in scene.get("capabilities", [])
    }

    scene_rows = scenes.get("scene_profiles", [])
    scene_by_id = _unique(scene_rows, "scene_profile_id", "scene profiles")
    scene_required = supply["contract_types"]["scene_profile"]["required"]
    scene_counts = {domain_id: 0 for domain_id in packs}
    for scene_id, row in scene_by_id.items():
        _require_fields(row, scene_required, scene_id)
        _require_maturity(row, scene_id)
        domain_id = str(row["domain_id"])
        if domain_id not in packs or not re.fullmatch(rf"scene\.{re.escape(domain_id)}\.[a-z0-9-]+", scene_id):
            raise ContractError(f"{scene_id} domain 或 ID 无效")
        scene_counts[domain_id] += 1
        if not set(row["recommended_module_ids"]) <= set(modules_by_domain[domain_id]):
            raise ContractError(f"{scene_id} 引用未知模块")
    if set(scene_counts.values()) - {2, 3, 4} or len(scene_by_id) != scenes.get("scene_profile_count"):
        raise ContractError("scene profile 必须覆盖 16 领域且每域 2–4 项")

    graph = scenes.get("capability_graph_seed", {})
    verticals = graph.get("verticals", []) if isinstance(graph, dict) else []
    if {row.get("vertical_id") for row in verticals} != {
        "vertical.personal-household", "vertical.content-research", "vertical.small-business",
    }:
        raise ContractError("v0.50 三条纵向样板不完整")
    graph_scene_ids: set[str] = set()
    graph_path_count = 0
    for vertical in verticals:
        for scene_path in vertical.get("scene_paths", []):
            scene_id = str(scene_path.get("scene_profile_id") or "")
            if scene_id not in scene_by_id:
                raise ContractError(f"capability graph 引用未知场景：{scene_id}")
            graph_scene_ids.add(scene_id)
            domain_id = scene_by_id[scene_id]["domain_id"]
            for module in scene_path.get("modules", []):
                graph_path_count += 1
                if module.get("module_id") not in modules_by_domain[domain_id]:
                    raise ContractError(f"{scene_id} 图路径引用未知模块")
                if not module.get("capability_ids") or not set(module["capability_ids"]) <= capability_ids:
                    raise ContractError(f"{scene_id} 图路径引用未知 CAP")

    surface_rows = surfaces.get("surface_primitives", [])
    surface_by_id = _unique(surface_rows, "surface_primitive_id", "surface primitives")
    surface_required = supply["contract_types"]["surface_primitive"]["required"]
    for surface_id, row in surface_by_id.items():
        _require_fields(row, surface_required, surface_id)
        _require_maturity(row, surface_id)
    expected_surfaces = {
        "surface.today-action", "surface.checklist", "surface.record-ledger", "surface.stage-board",
        "surface.metric", "surface.review", "surface.library", "surface.guided-practice",
        "surface.reward-exchange",
    }
    if set(surface_by_id) != expected_surfaces:
        raise ContractError("九类 surface primitive 未完整锁定")

    policy_rows = policies.get("policy_packs", [])
    policy_by_id = _unique(policy_rows, "policy_pack_id", "policy packs")
    policy_required = supply["contract_types"]["policy_pack"]["required"]
    for policy_id, row in policy_by_id.items():
        _require_fields(row, policy_required, policy_id)
        _require_maturity(row, policy_id)

    atom_rows = atoms.get("atomic_capabilities", [])
    atom_by_id = _unique(atom_rows, "atomic_capability_id", "atomic capabilities")
    atom_required = supply["contract_types"]["atomic_capability"]["required"]
    for atom_id, row in atom_by_id.items():
        _require_fields(row, atom_required, atom_id)
        _require_maturity(row, atom_id)
        if not set(row["supported_surface_primitive_ids"]) <= set(surface_by_id):
            raise ContractError(f"{atom_id} 引用未知 surface")
        if not set(row["policy_pack_ids"]) <= set(policy_by_id):
            raise ContractError(f"{atom_id} 引用未知 policy")

    layout_text = str(layout)
    if any(token not in layout_text for token in ("home", "module", "detail", "adult_settings", "390", "768", "1280")):
        raise ContractError("layout system 缺少四层或三视口合同")
    selected_scope = layout.get("selected_scope_visibility", {})
    if not selected_scope:
        raise ContractError("layout system 缺少 selected-scope 可见性合同")

    maturity = {
        level: sum(
            row.get("maturity") == level
            for rows in (scene_rows, atom_rows, surface_rows, policy_rows)
            for row in rows
        )
        for level in MATURITY_LEVELS
    }
    return {
        "schema_version": 1,
        "contract_version": supply["contract_version"],
        "status": "valid",
        "domain_count": len(packs),
        "scene_profile_count": len(scene_by_id),
        "vertical_count": len(verticals),
        "vertical_scene_count": len(graph_scene_ids),
        "graph_path_count": graph_path_count,
        "atomic_capability_count": len(atom_by_id),
        "surface_primitive_count": len(surface_by_id),
        "policy_pack_count": len(policy_by_id),
        "maturity": maturity,
    }


def scene_profile_catalog() -> dict[str, Any]:
    validate_capability_supply()
    return deepcopy(_registry("scenes"))


def _scene_from_route(domain_id: str, route: dict[str, Any]) -> dict[str, Any] | None:
    scenes = _registry("scenes")
    rows = scenes["scene_profiles"]
    by_id = {row["scene_profile_id"]: row for row in rows}
    requested = route.get("scene_profile_id")
    if requested:
        row = by_id.get(str(requested))
        if row is None or row["domain_id"] != domain_id:
            raise ContractError("宿主选择的 scene_profile 不属于当前领域")
        return row
    legacy = str(route.get("profile_id") or "")
    if legacy:
        mapping = {
            row["legacy_profile_id"]: row["scene_profile_id"]
            for row in scenes.get("audit", {}).get("existing_profile_migration", [])
        }
        scene_id = mapping.get(legacy)
        if scene_id:
            return by_id[scene_id]
    candidates = [row for row in rows if row["domain_id"] == domain_id and row["maturity"] != "catalog_only"]
    return candidates[0] if candidates else None


def vertical_supply_snapshot(domain_id: str, route: dict[str, Any]) -> dict[str, Any] | None:
    """返回 v0.50 三条纵向样板的选定路径；非样板领域诚实返回 None。"""
    validate_capability_supply()
    scene = _scene_from_route(domain_id, route)
    if scene is None:
        return None
    scenes = _registry("scenes")
    for vertical in scenes["capability_graph_seed"]["verticals"]:
        for path in vertical["scene_paths"]:
            if path["scene_profile_id"] == scene["scene_profile_id"]:
                return {
                    "schema_version": 1,
                    "contract_version": "double6_vertical_supply_v1",
                    "vertical_id": vertical["vertical_id"],
                    "scene_profile": deepcopy(scene),
                    "module_paths": deepcopy(path["modules"]),
                    "maturity": "contract_ready",
                    "selected_scope_only": True,
                    "deferred_bindings": ["atomic_capability", "surface_primitive", "policy_pack"],
                }
    return None
