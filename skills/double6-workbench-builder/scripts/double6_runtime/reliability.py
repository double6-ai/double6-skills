"""v0.55 selected-scope 可靠性信封编译器。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractError, REFERENCES, canonical, digest_bytes, read_json


REGISTRY_FILE = "reliability-contracts.json"
MATURITIES = {"contract_ready", "executable_ready"}


def _ids(rows: Any, field: str, source: str) -> set[str]:
    if not isinstance(rows, list):
        raise ContractError(f"{source} 必须是列表")
    result = {str(row.get(field) or "") for row in rows if isinstance(row, dict)}
    if "" in result or len(result) != len(rows):
        raise ContractError(f"{source} 含空或重复 ID")
    return result


def validate_reliability_registry(
    registry: Mapping[str, Any] | None = None,
    *,
    policy_registry: Mapping[str, Any] | None = None,
    atom_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = dict(registry or read_json(REFERENCES / REGISTRY_FILE))
    policies = dict(policy_registry or read_json(REFERENCES / "policy-packs.json"))
    atoms = dict(atom_registry or read_json(REFERENCES / "atomic-capabilities.json"))
    guards = value.get("guards")
    guard_ids = _ids(guards, "guard_id", "reliability guards")
    policy_ids = _ids(policies.get("policy_packs"), "policy_pack_id", "policy packs")
    atom_ids = _ids(atoms.get("atomic_capabilities"), "atomic_capability_id", "atomic capabilities")
    if value.get("contract_version") != "double6_reliability_envelope_v1":
        raise ContractError("可靠性合同版本无效")
    if value.get("skill_version") != "1.1.0":
        raise ContractError("可靠性合同必须绑定 1.0.0")
    if value.get("guard_count") != len(guards) or len(guards) != 13:
        raise ContractError("可靠性 guard_count 漂移")
    for row in guards:
        if row.get("maturity") not in MATURITIES:
            raise ContractError(f"可靠性成熟度无效：{row.get('guard_id')}")
        activation = row.get("activation")
        if not isinstance(activation, dict) or activation.get("type") not in {
            "always", "when_any_atom_selected", "when_any_policy_selected", "domain_in"
        }:
            raise ContractError(f"可靠性 activation 无效：{row.get('guard_id')}")
        unknown_policies = set(map(str, row.get("required_policy_pack_ids", []))) - policy_ids
        unknown_atoms = set(map(str, row.get("required_atomic_capability_ids", []))) - atom_ids
        activation_ids = set(map(str, activation.get("ids", [])))
        if activation.get("type") == "when_any_atom_selected":
            unknown_atoms |= activation_ids - atom_ids
        if activation.get("type") == "when_any_policy_selected":
            unknown_policies |= activation_ids - policy_ids
        if unknown_policies or unknown_atoms:
            raise ContractError(
                f"可靠性 guard 引用未知注册项：{row['guard_id']}: "
                f"policy={sorted(unknown_policies)} atom={sorted(unknown_atoms)}"
            )
    return {
        "status": "valid",
        "contract_version": value["contract_version"],
        "guard_count": len(guard_ids),
        "registry_sha256": digest_bytes(canonical(value)),
    }


def _active(activation: Mapping[str, Any], domain_id: str, atoms: set[str], policies: set[str]) -> bool:
    kind = activation["type"]
    ids = set(map(str, activation.get("ids", [])))
    if kind == "always":
        return True
    if kind == "when_any_atom_selected":
        return bool(ids & atoms)
    if kind == "when_any_policy_selected":
        return bool(ids & policies)
    if kind == "domain_in":
        return domain_id in ids
    raise ContractError(f"未知可靠性 activation：{kind}")


def compile_reliability_envelope(
    *,
    domain_id: str,
    scene_profile_id: str,
    selected_atom_ids: Sequence[str],
    selected_policy_ids: Sequence[str],
    compiler_invariants: Mapping[str, bool],
) -> dict[str, Any]:
    registry = read_json(REFERENCES / REGISTRY_FILE)
    validation = validate_reliability_registry(registry)
    atoms = set(map(str, selected_atom_ids))
    policies = set(map(str, selected_policy_ids))
    results: list[dict[str, Any]] = []
    for guard in registry["guards"]:
        active = _active(guard["activation"], domain_id, atoms, policies)
        required_atoms = set(map(str, guard.get("required_atomic_capability_ids", [])))
        required_policies = set(map(str, guard.get("required_policy_pack_ids", [])))
        missing_atoms = sorted(required_atoms - atoms)
        missing_policies = sorted(required_policies - policies)
        invariant = str(guard.get("compiler_invariant") or "")
        invariant_ok = not invariant or bool(compiler_invariants.get(invariant))
        if not active:
            status = "not_applicable"
        elif guard["maturity"] == "contract_ready":
            status = "contract_only"
        elif missing_atoms or missing_policies or not invariant_ok:
            status = "blocked"
        else:
            status = "satisfied"
        results.append({
            "guard_id": guard["guard_id"],
            "label": guard["label"],
            "maturity": guard["maturity"],
            "active": active,
            "status": status,
            "missing_atomic_capability_ids": missing_atoms,
            "missing_policy_pack_ids": missing_policies,
            "compiler_invariant": invariant or None,
            "failure_state": guard["failure_state"],
            "claim_boundary": guard["claim_boundary"],
        })
    status_counts = {
        state: sum(row["status"] == state for row in results)
        for state in ("satisfied", "contract_only", "not_applicable", "blocked")
    }
    envelope = {
        "schema_version": 1,
        "contract_version": registry["contract_version"],
        "registry_sha256": validation["registry_sha256"],
        "scene_profile_id": scene_profile_id,
        "domain_id": domain_id,
        "status": "blocked" if status_counts["blocked"] else "compiled",
        "status_counts": status_counts,
        "guards": results,
        "honest_boundary": "contract_only guards are delivery requirements, not runtime success claims",
    }
    envelope["envelope_sha256"] = digest_bytes(canonical(envelope))
    return envelope


__all__ = ["compile_reliability_envelope", "validate_reliability_registry"]
