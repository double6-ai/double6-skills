"""v0.54 的确定性 selected-scope 推荐与可靠性信封编译器。

本模块只编译上游已经确认的场景和选择，不新增澄清问题。图谱注册表可以
暴露全部供给用于治理；``compile_selection`` 的返回值则只包含最终选中路径。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence

from .core import ContractError, REFERENCES, canonical, digest_bytes, read_json
from .reliability import compile_reliability_envelope


GRAPH_FILE = "capability-graph.json"
LEGACY_SURFACE_TO_PRIMITIVE = {
    "action_checklist": "surface.checklist",
    "record_ledger": "surface.record-ledger",
    "stage_board": "surface.stage-board",
    "metric_log": "surface.metric",
    "review_journal": "surface.review",
    "reward_economy": "surface.reward-exchange",
}
MATURITY_ORDER = {
    "catalog_only": 0,
    "contract_ready": 1,
    "executable_ready": 2,
    "release_ready": 3,
}
MAX_QUESTIONS_PER_SCENE = 5
MIN_SELECTED_MODULES = 4
MAX_SELECTED_MODULES = 15

# 这些 atom 的当前实现本来就是所列 legacy surface 的通用运行时操作。
# capability_ids 仍用于记录更强的 direct_capability 证据；本表只允许以
# surface_runtime_generic 明示的方式复用，不把它冒充领域语义 atom。
GENERIC_RUNTIME_ATOMS_BY_SURFACE = {
    "surface.checklist": (
        "atom.shared.create-record",
        "atom.shared.edit-record",
        "atom.shared.delete-record",
        "atom.shared.complete-item",
        "atom.shared.create-checklist-item",
    ),
    "surface.record-ledger": (
        "atom.shared.create-record",
        "atom.shared.edit-record",
        "atom.shared.delete-record",
        "atom.shared.archive-record",
        "atom.shared.filter-records",
    ),
    "surface.stage-board": (
        "atom.shared.create-record",
        "atom.shared.edit-record",
        "atom.shared.delete-record",
        "atom.shared.archive-record",
        "atom.shared.move-stage",
        "atom.shared.filter-records",
    ),
    "surface.metric": (
        "atom.shared.create-record",
        "atom.shared.edit-record",
        "atom.shared.delete-record",
    ),
    "surface.review": (
        "atom.shared.create-record",
        "atom.shared.edit-record",
        "atom.shared.delete-record",
        "atom.shared.filter-records",
        "atom.shared.write-review",
    ),
    "surface.reward-exchange": (
        "atom.shared.request-reward-redemption",
        "atom.shared.post-reward-ledger-event",
    ),
}
GLOBAL_RUNTIME_ATOMS = ("atom.shared.import-backup-preview",)


def _rows_by_id(rows: Any, field: str, source: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"{source} 必须包含非空列表")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get(field) or "").strip():
            raise ContractError(f"{source} 含无效 {field}")
        row_id = str(row[field])
        if row_id in result:
            raise ContractError(f"{source} 含重复 {field}：{row_id}")
        result[row_id] = row
    return result


def _load_registries() -> dict[str, Any]:
    graph = read_json(REFERENCES / GRAPH_FILE)
    scenes = read_json(REFERENCES / "scene-profiles.json")
    content = read_json(REFERENCES / "domain-content-packs.json")
    capabilities = read_json(REFERENCES / "scene-capability-starters.json")
    atoms = read_json(REFERENCES / "atomic-capabilities.json")
    surfaces = read_json(REFERENCES / "surface-primitives.json")
    policies = read_json(REFERENCES / "policy-packs.json")

    scene_by_id = _rows_by_id(scenes.get("scene_profiles"), "scene_profile_id", "scene-profiles")
    pack_by_domain = _rows_by_id(content.get("packs"), "domain_id", "domain-content-packs")
    capability_by_id = _rows_by_id(
        [cap for scene in capabilities.get("scenes", []) for cap in scene.get("capabilities", [])],
        "capability_id",
        "scene-capability-starters",
    )
    atom_by_id = _rows_by_id(atoms.get("atomic_capabilities"), "atomic_capability_id", "atomic-capabilities")
    surface_by_id = _rows_by_id(surfaces.get("surface_primitives"), "surface_primitive_id", "surface-primitives")
    policy_by_id = _rows_by_id(policies.get("policy_packs"), "policy_pack_id", "policy-packs")
    graph_scene_by_id = _rows_by_id(graph.get("scene_paths"), "scene_profile_id", "capability-graph")
    modules_by_domain: dict[str, dict[str, dict[str, Any]]] = {}
    module_order_by_domain: dict[str, list[str]] = {}
    for domain_id, pack in pack_by_domain.items():
        modules_by_domain[domain_id] = _rows_by_id(pack.get("modules"), "module_id", f"modules:{domain_id}")
        module_order_by_domain[domain_id] = [str(row["module_id"]) for row in pack["modules"]]

    return {
        "graph": graph,
        "scenes": scenes,
        "scene_by_id": scene_by_id,
        "graph_scene_by_id": graph_scene_by_id,
        "pack_by_domain": pack_by_domain,
        "modules_by_domain": modules_by_domain,
        "module_order_by_domain": module_order_by_domain,
        "capability_by_id": capability_by_id,
        "atom_by_id": atom_by_id,
        "surface_by_id": surface_by_id,
        "policy_by_id": policy_by_id,
    }


def _domain_permitted(atom: Mapping[str, Any], domain_id: str) -> bool:
    domains = atom.get("reusability_domains", [])
    return isinstance(domains, list) and ("all_16_domains" in domains or domain_id in domains)


def _surface_id(module: Mapping[str, Any]) -> str:
    try:
        return LEGACY_SURFACE_TO_PRIMITIVE[str(module["surface_type"])]
    except KeyError as exc:
        raise ContractError(f"模块表面没有稳定 primitive 映射：{module.get('module_id')}") from exc


def _ordered_unique(values: Iterable[str], order: Sequence[str]) -> list[str]:
    requested = {str(value) for value in values}
    result: list[str] = []
    seen: set[str] = set()
    for value in order:
        if value in requested and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _resolve_scene(reg: Mapping[str, Any], domain_id: str, route: Mapping[str, Any]) -> dict[str, Any]:
    if domain_id not in reg["pack_by_domain"]:
        raise ContractError(f"未知领域：{domain_id}")
    scene_by_id = reg["scene_by_id"]
    requested = str(route.get("scene_profile_id") or "")
    if requested:
        scene = scene_by_id.get(requested)
        if scene is None or scene.get("domain_id") != domain_id:
            raise ContractError("宿主选择的 scene_profile 不属于当前领域")
        return scene

    legacy = str(route.get("profile_id") or "")
    if legacy:
        mapping = {
            str(row["legacy_profile_id"]): str(row["scene_profile_id"])
            for row in reg["scenes"].get("audit", {}).get("existing_profile_migration", [])
        }
        scene_id = mapping.get(legacy)
        if scene_id:
            scene = scene_by_id[scene_id]
            if scene.get("domain_id") != domain_id:
                raise ContractError("legacy profile 与当前领域不一致")
            return scene

    candidates = sorted(
        (row for row in scene_by_id.values() if row.get("domain_id") == domain_id),
        key=lambda row: str(row["scene_profile_id"]),
    )
    if not candidates:
        raise ContractError(f"领域没有 scene_profile：{domain_id}")
    return candidates[0]


def _atom_binding(
    atom: Mapping[str, Any],
    *,
    capability_id: str,
    surface_id: str,
) -> dict[str, Any] | None:
    atom_id = str(atom["atomic_capability_id"])
    supported = {str(value) for value in atom.get("supported_surface_primitive_ids", [])}
    if surface_id not in supported:
        return None
    direct = capability_id in {str(value) for value in atom.get("capability_ids", [])}
    generic = atom_id in GENERIC_RUNTIME_ATOMS_BY_SURFACE.get(surface_id, ())
    if not direct and not generic:
        return None
    return {
        "atomic_capability_id": atom_id,
        "label": str(atom["label"]),
        "binding_basis": "direct_capability" if direct else "surface_runtime_generic",
        "maturity": str(atom["maturity"]),
        "policy_pack_ids": sorted({str(value) for value in atom.get("policy_pack_ids", [])}),
    }


def _legacy_child_binding(scene: Mapping[str, Any], module: Mapping[str, Any]) -> dict[str, Any] | None:
    if (
        scene.get("domain_id") == "education-learning"
        and module.get("module_id") == "education-rewards"
        and module.get("surface_type") == "reward_economy"
    ):
        return {
            "binding_type": "legacy_child_runtime_binding",
            "status": "existing_runtime_preserved_not_generic_atom_promotion",
            "surface_primitive_id": "surface.reward-exchange",
            "implementation": "recommendations.py reward_economy + builder.py existing reward ledger",
            "invariants": [
                "preserve_existing_child_learning_runtime",
                "no_new_child_learning_atom",
                "reward_does_not_change_mastery_or_completion_truth",
            ],
        }
    return None


def _compile_module(
    reg: Mapping[str, Any],
    scene: Mapping[str, Any],
    module: Mapping[str, Any],
    capability_ids: Sequence[str],
) -> dict[str, Any]:
    domain_id = str(scene["domain_id"])
    module_id = str(module["module_id"])
    surface_id = _surface_id(module)
    surface = reg["surface_by_id"][surface_id]
    if MATURITY_ORDER.get(str(surface.get("maturity")), -1) < MATURITY_ORDER["executable_ready"]:
        raise ContractError(f"选定模块表面尚不可执行：{module_id} -> {surface_id}")

    selected_policy_ids: set[str] = {str(value) for value in surface.get("policy_pack_ids", [])}
    excluded: list[dict[str, str]] = []
    capability_paths: list[dict[str, Any]] = []
    module_atom_ids: set[str] = set()
    for capability_id in capability_ids:
        capability = reg["capability_by_id"][capability_id]
        bindings: list[dict[str, Any]] = []
        for atom_id in sorted(reg["atom_by_id"]):
            atom = reg["atom_by_id"][atom_id]
            if not _domain_permitted(atom, domain_id):
                continue
            candidate = _atom_binding(atom, capability_id=capability_id, surface_id=surface_id)
            if candidate is None:
                continue
            if atom.get("maturity") != "executable_ready":
                excluded.append({
                    "atomic_capability_id": atom_id,
                    "capability_id": capability_id,
                    "reason": "atom_not_executable_ready",
                })
                continue
            bindings.append(candidate)
            module_atom_ids.add(atom_id)
            selected_policy_ids.update(candidate["policy_pack_ids"])

        # 直接语义相关但尚未可执行的 atom 仍明确列出，不静默忽略。
        bound_ids = {row["atomic_capability_id"] for row in bindings}
        for atom_id, atom in sorted(reg["atom_by_id"].items()):
            if (
                capability_id in atom.get("capability_ids", [])
                and atom_id not in bound_ids
                and atom.get("maturity") != "executable_ready"
            ):
                excluded.append({
                    "atomic_capability_id": atom_id,
                    "capability_id": capability_id,
                    "reason": "direct_binding_contract_only",
                })

        capability_paths.append({
            "capability_id": capability_id,
            "label": str(capability["title"]),
            "primary_action": str(capability["primary_action"]),
            "result_contract": str(capability["result_contract"]),
            "executable_atom_bindings": sorted(
                bindings,
                key=lambda row: (row["atomic_capability_id"], row["binding_basis"]),
            ),
            "atomic_capability_ids": sorted({
                row["atomic_capability_id"] for row in bindings
            }),
            "surface_primitive_ids": [surface_id],
            "policy_pack_ids": sorted({
                *[str(value) for value in surface.get("policy_pack_ids", [])],
                *[
                    str(policy_id)
                    for row in bindings
                    for policy_id in row["policy_pack_ids"]
                ],
            }),
        })

    legacy = _legacy_child_binding(scene, module)
    if not module_atom_ids and legacy is None:
        raise ContractError(f"选定模块没有 executable atom，编译已阻断：{module_id}")
    if legacy:
        selected_policy_ids.update({
            "policy.reward-truth-isolation",
            "policy.reversible-constraint",
            "policy.external-operation-confirmation",
        })
    unknown_policies = selected_policy_ids - set(reg["policy_by_id"])
    if unknown_policies:
        raise ContractError(f"模块引用未知 policy：{module_id}: {sorted(unknown_policies)}")

    module_path: dict[str, Any] = {
        "module_id": module_id,
        "label": str(module["name"]),
        "surface": {
            "surface_primitive_id": surface_id,
            "maturity": str(surface["maturity"]),
        },
        "capability_paths": capability_paths,
        "policy_requirements": [
            {
                "policy_pack_id": policy_id,
                "maturity": str(reg["policy_by_id"][policy_id]["maturity"]),
                "runtime_claim": "requirement_only_until_independent_policy_runtime_promotion",
            }
            for policy_id in sorted(selected_policy_ids)
        ],
        "excluded_non_executable_bindings": sorted(
            {(
                row["atomic_capability_id"], row["capability_id"], row["reason"]
            ) for row in excluded}
        ),
        "runtime_binding_status": (
            "legacy_child_runtime_bound" if legacy and not module_atom_ids else "executable_atom_bound"
        ),
    }
    module_path["excluded_non_executable_bindings"] = [
        {"atomic_capability_id": atom_id, "capability_id": cap_id, "reason": reason}
        for atom_id, cap_id, reason in module_path["excluded_non_executable_bindings"]
    ]
    if legacy:
        module_path["legacy_runtime_binding"] = legacy
    return module_path


def _normalize_capability_overrides(
    value: Mapping[str, Sequence[str]] | None,
) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractError("capability_overrides 必须是 module_id 到 capability_id 列表的映射")
    result: dict[str, list[str]] = {}
    for module_id, capability_ids in value.items():
        if isinstance(capability_ids, (str, bytes)) or not isinstance(capability_ids, Sequence):
            raise ContractError(f"capability override 必须是列表：{module_id}")
        result[str(module_id)] = sorted({str(value) for value in capability_ids})
    return result


def compile_selection(
    domain_id: str,
    route: Mapping[str, Any],
    selected_module_ids: Sequence[str] | None = None,
    selected_capability_ids: Sequence[str] | None = None,
    *,
    add_module_ids: Sequence[str] | None = None,
    remove_module_ids: Sequence[str] | None = None,
    capability_overrides: Mapping[str, Sequence[str]] | None = None,
    clarification_question_count: int | None = None,
) -> dict[str, Any]:
    """编译一个选定场景的确定性 selected-only snapshot。

    ``route`` 接受 ``scene_profile_id`` 或兼容的 ``profile_id``。模块可整体采用、
    以显式列表替换，或通过 ``add_module_ids`` / ``remove_module_ids`` 调整。
    ``selected_capability_ids`` 是全局已选 CAP 集合；更精细的逐模块调整使用
    ``capability_overrides``。编译器不产生澄清问题，只验证可选的上游普通澄清计数；授权和边界确认另计，不传入该字段。
    """
    if not isinstance(route, Mapping):
        raise ContractError("route 必须是对象")
    if clarification_question_count is None:
        raw_count = route.get("clarification_question_count", route.get("question_count", 0))
        clarification_question_count = int(raw_count or 0)
    if not 0 <= clarification_question_count <= MAX_QUESTIONS_PER_SCENE:
        raise ContractError("同一 scene_session 的普通需求和偏好澄清不得超过 5 个")

    reg = _load_registries()
    scene = _resolve_scene(reg, str(domain_id), route)
    scene_id = str(scene["scene_profile_id"])
    graph_scene = reg["graph_scene_by_id"].get(scene_id)
    if graph_scene is None:
        raise ContractError(f"capability graph 缺场景：{scene_id}")
    modules_by_id = reg["modules_by_domain"][domain_id]
    domain_order = reg["module_order_by_domain"][domain_id]
    recommended = [str(value) for value in graph_scene["recommended_module_ids"]]

    if selected_module_ids is None:
        working = set(recommended)
        base_mode = "adopt_recommended"
    else:
        if isinstance(selected_module_ids, (str, bytes)):
            raise ContractError("selected_module_ids 必须是列表")
        working = {str(value) for value in selected_module_ids}
        base_mode = "explicit_module_selection"
    additions = {str(value) for value in (add_module_ids or [])}
    removals = {str(value) for value in (remove_module_ids or [])}
    if additions & removals:
        raise ContractError("同一模块不能同时加入和移除")
    unknown_adjustments = (additions | removals) - set(modules_by_id)
    if unknown_adjustments:
        raise ContractError(f"模块调整不属于当前领域：{sorted(unknown_adjustments)}")
    base_modules = set(working)
    working.update(additions)
    working.difference_update(removals)
    unknown_modules = working - set(modules_by_id)
    if unknown_modules:
        raise ContractError(f"选定模块不属于当前领域：{sorted(unknown_modules)}")
    if not MIN_SELECTED_MODULES <= len(working) <= MAX_SELECTED_MODULES:
        raise ContractError("最终选定模块数量必须为 4–15")
    # 默认采用必须保持 scene profile 的用户可见顺序；新增模块再按领域目录的
    # 稳定顺序附加，避免 set 或调用方输入顺序造成不确定输出。
    ordered_modules = _ordered_unique(working, [*recommended, *domain_order])

    global_capabilities: set[str] | None = None
    if selected_capability_ids is not None:
        if isinstance(selected_capability_ids, (str, bytes)):
            raise ContractError("selected_capability_ids 必须是列表")
        global_capabilities = {str(value) for value in selected_capability_ids}
    overrides = _normalize_capability_overrides(capability_overrides)
    if set(overrides) - set(ordered_modules):
        raise ContractError("capability_overrides 只能引用最终选定模块")

    reachable_selected_capabilities: set[str] = set()
    selected_by_module: dict[str, list[str]] = {}
    for module_id in ordered_modules:
        module_capabilities = [
            str(value) for value in modules_by_id[module_id].get("evidence_refs", [])
            if str(value).startswith("CAP-")
        ]
        if not module_capabilities:
            raise ContractError(f"模块没有 capability evidence_refs：{module_id}")
        if module_id in overrides:
            chosen = overrides[module_id]
        elif global_capabilities is not None:
            chosen = [value for value in module_capabilities if value in global_capabilities]
        else:
            chosen = module_capabilities
        if not chosen:
            raise ContractError(f"每个选定模块必须至少保留一项能力：{module_id}")
        if not set(chosen) <= set(module_capabilities):
            raise ContractError(f"能力跨模块泄漏：{module_id}")
        unknown_caps = set(chosen) - set(reg["capability_by_id"])
        if unknown_caps:
            raise ContractError(f"引用未知能力：{module_id}: {sorted(unknown_caps)}")
        selected_by_module[module_id] = [value for value in module_capabilities if value in set(chosen)]
        reachable_selected_capabilities.update(selected_by_module[module_id])
    if global_capabilities is not None and global_capabilities - reachable_selected_capabilities:
        raise ContractError("selected_capability_ids 含无法从选定模块到达的能力")

    module_paths = [
        _compile_module(reg, scene, modules_by_id[module_id], selected_by_module[module_id])
        for module_id in ordered_modules
    ]
    global_runtime_bindings: list[dict[str, Any]] = []
    for atom_id in GLOBAL_RUNTIME_ATOMS:
        atom = reg["atom_by_id"].get(atom_id)
        if atom is None or atom.get("maturity") != "executable_ready" or not atom.get("runtime_binding"):
            raise ContractError(f"全局可靠性 atom 尚不可执行：{atom_id}")
        global_runtime_bindings.append({
            "atomic_capability_id": atom_id,
            "label": str(atom["label"]),
            "maturity": str(atom["maturity"]),
            "binding_basis": "selected_workbench_global_reliability",
            "policy_pack_ids": sorted(str(value) for value in atom.get("policy_pack_ids", [])),
        })
    source_maturity = str(scene["maturity"])
    if source_maturity == "catalog_only":
        selection_status = "catalog_compiled"
    elif source_maturity == "contract_ready":
        selection_status = "contract_compiled"
    else:
        selection_status = "executable_selection_compiled"
    executable_atom_ids = sorted(
        {row["atomic_capability_id"] for row in global_runtime_bindings}
        | {
            binding["atomic_capability_id"]
            for module_path in module_paths
            for capability_path in module_path["capability_paths"]
            for binding in capability_path["executable_atom_bindings"]
        }
    )
    executable_binding_count = len(global_runtime_bindings) + sum(
        len(capability_path["executable_atom_bindings"])
        for module_path in module_paths
        for capability_path in module_path["capability_paths"]
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "contract_version": "double6_selected_capability_snapshot_v1",
        "compiler_version": "1.1.0",
        "scene_profile": {
            "scene_profile_id": scene_id,
            "domain_id": str(scene["domain_id"]),
            "label": str(scene["label"]),
            "maturity": source_maturity,
            "source_maturity": source_maturity,
        },
        "selection_maturity": source_maturity,
        "selection_status": selection_status,
        "usable": selection_status == "executable_selection_compiled",
        "usable_as_generic_supply": selection_status == "executable_selection_compiled",
        "executable_binding_evidence": {
            "executable_binding_count": executable_binding_count,
            "selected_executable_atom_ids": executable_atom_ids,
            "claim_boundary": "bindings are executable components; scene usability remains capped by selection_maturity",
        },
        "selected_scope_only": True,
        "question_policy": {
            "question_count": clarification_question_count,
            "question_limit_per_scene": MAX_QUESTIONS_PER_SCENE,
            "compiler_generated_question": False,
            "scene_session_count_observed": clarification_question_count,
            "maximum_questions_per_scene": MAX_QUESTIONS_PER_SCENE,
            "compiler_added_questions": 0,
            "scene_switch_counter_reset_owned_by_upstream": True,
        },
        "global_runtime_bindings": global_runtime_bindings,
        "module_paths": module_paths,
        "selection_receipt": {
            "base_mode": base_mode,
            "selected_module_count": len(module_paths),
            "selected_capability_count": len(reachable_selected_capabilities),
            "added_module_count": len(working - base_modules),
            "removed_module_count": len(base_modules - working),
            "capability_override_module_count": len(overrides),
            "selection_maturity": source_maturity,
            "executable_binding_count": executable_binding_count,
            "selected_executable_atom_ids": executable_atom_ids,
            "cascade_applied": [
                "module_to_capability",
                "capability_to_atomic_capability",
                "atomic_capability_to_surface_and_policy",
            ],
        },
        "honest_boundaries": [
            "catalog_only and contract_ready scene profiles are deterministic contract snapshots, not generic executable supply claims",
            "only executable_ready atoms are serialized as executable_atom_bindings",
            "policy packs remain requirements until independent runtime promotion",
            "legacy child runtime compatibility does not promote a generic child learning atom",
            "snapshot contains no unselected module inventory or full graph",
        ],
    }
    selected_policy_ids = sorted({
        policy_id
        for row in global_runtime_bindings
        for policy_id in row["policy_pack_ids"]
    } | {
        str(row["policy_pack_id"])
        for module_path in module_paths
        for row in module_path["policy_requirements"]
    })
    payload["reliability_envelope"] = compile_reliability_envelope(
        domain_id=str(scene["domain_id"]),
        scene_profile_id=scene_id,
        selected_atom_ids=executable_atom_ids,
        selected_policy_ids=selected_policy_ids,
        compiler_invariants={"selected_scope_only": payload["selected_scope_only"]},
    )
    if payload["reliability_envelope"]["status"] == "blocked":
        blocked = [
            row["guard_id"] for row in payload["reliability_envelope"]["guards"]
            if row["status"] == "blocked"
        ]
        raise ContractError(f"可靠性信封阻断编译：{blocked}")
    payload["selection_sha256"] = digest_bytes(canonical(payload))
    return payload


def compile_selected_scope(
    scene_profile_id: str,
    *,
    selected_module_ids: Sequence[str] | None = None,
    selected_capability_ids: Sequence[str] | None = None,
    add_module_ids: Sequence[str] | None = None,
    remove_module_ids: Sequence[str] | None = None,
    capability_overrides: Mapping[str, Sequence[str]] | None = None,
    clarification_question_count: int = 0,
) -> dict[str, Any]:
    """按 scene_profile_id 调用 ``compile_selection`` 的方便入口。"""
    reg = _load_registries()
    scene = reg["scene_by_id"].get(str(scene_profile_id))
    if scene is None:
        raise ContractError(f"未知 scene_profile：{scene_profile_id}")
    return compile_selection(
        str(scene["domain_id"]),
        {"scene_profile_id": str(scene_profile_id)},
        selected_module_ids,
        selected_capability_ids,
        add_module_ids=add_module_ids,
        remove_module_ids=remove_module_ids,
        capability_overrides=capability_overrides,
        clarification_question_count=clarification_question_count,
    )


def validate_capability_graph() -> dict[str, Any]:
    """完整重算 16 领域 / 34 profile 图并验证默认选择可确定编译。"""
    reg = _load_registries()
    graph = reg["graph"]
    if graph.get("contract_version") != "double6_capability_graph_v1":
        raise ContractError("capability graph 合同版本无效")
    if set(reg["graph_scene_by_id"]) != set(reg["scene_by_id"]):
        raise ContractError("capability graph 必须覆盖全部 34 个 scene_profile")
    if set(reg["pack_by_domain"]) != {str(row["domain_id"]) for row in reg["scene_by_id"].values()}:
        raise ContractError("capability graph 必须覆盖全部 16 个领域")

    path_count = 0
    maturity_counts = {level: 0 for level in MATURITY_ORDER}
    compiled_sha256: list[str] = []
    legacy_child_runtime_bindings = 0
    for scene_id in sorted(reg["scene_by_id"]):
        scene = reg["scene_by_id"][scene_id]
        graph_scene = reg["graph_scene_by_id"][scene_id]
        if graph_scene.get("domain_id") != scene.get("domain_id"):
            raise ContractError(f"图场景 domain 漂移：{scene_id}")
        if graph_scene.get("recommended_module_ids") != scene.get("recommended_module_ids"):
            raise ContractError(f"图场景模块与 scene profile 漂移：{scene_id}")
        path_count += len(graph_scene["recommended_module_ids"])
        snapshot = compile_selected_scope(scene_id)
        compiled_sha256.append(str(snapshot["selection_sha256"]))
        maturity_counts[str(scene["maturity"])] += 1
        for module_path in snapshot["module_paths"]:
            if module_path["runtime_binding_status"] == "legacy_child_runtime_bound":
                legacy_child_runtime_bindings += 1
            elif not any(
                capability["executable_atom_bindings"]
                for capability in module_path["capability_paths"]
            ):
                raise ContractError(f"模块缺少 executable atom：{scene_id}/{module_path['module_id']}")
    expected_path_count = int(graph.get("audit", {}).get("recommended_scene_module_path_count", -1))
    if path_count != expected_path_count:
        raise ContractError("capability graph path_count 漂移")

    return {
        "schema_version": 1,
        "contract_version": str(graph["contract_version"]),
        "status": "valid",
        "domain_count": len(reg["pack_by_domain"]),
        "scene_profile_count": len(reg["scene_by_id"]),
        "recommended_scene_module_path_count": path_count,
        "scene_maturity_counts": maturity_counts,
        "compiled_snapshot_count": len(compiled_sha256),
        "compiled_snapshot_set_sha256": digest_bytes(canonical(compiled_sha256)),
        "legacy_child_runtime_binding_count": legacy_child_runtime_bindings,
        "compiler_adds_questions": False,
        "maximum_questions_per_scene": MAX_QUESTIONS_PER_SCENE,
        "selected_scope_only": True,
    }


def capability_graph_catalog() -> dict[str, Any]:
    """返回完整治理图；产品编译不得调用此返回值作为最终 snapshot。"""
    validate_capability_graph()
    return deepcopy(_load_registries()["graph"])
