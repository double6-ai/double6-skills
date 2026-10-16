"""v0.53 可复用原子能力的确定性本地执行内核。

这里只处理选定范围内的本地事实与人工交接草稿。任何外部发布、发送或通知
都必须由独立运行时返回真实回执；本模块不会把本地确认冒充成外部成功。
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence


ENGINE_VERSION = "1.1.0"
MATURITIES = {"catalog_only", "contract_ready", "executable_ready", "release_ready"}
ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$")
FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_RECORDS_PER_MODULE = 2000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _failure(code: str, message: str, state: Any = None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "rejected",
        "state": deepcopy(state),
        "receipt": None,
        "error": {"code": code, "message": message},
    }


def _success(status: str, state: Any, receipt: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    result = {
        "ok": True,
        "status": status,
        "state": deepcopy(state),
        "receipt": dict(receipt),
        "error": None,
    }
    result.update(deepcopy(extra))
    return result


def validate_atomic_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    """校验 atom 注册表的稳定 ID、成熟度和可执行绑定。"""
    rows = registry.get("atomic_capabilities") if isinstance(registry, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return _failure("registry_rows_missing", "atomic_capabilities 必须是非空列表")
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return _failure("registry_row_invalid", "atom 条目必须是对象")
        atom_id = str(row.get("atomic_capability_id") or "")
        if not atom_id.startswith("atom."):
            return _failure("atom_id_invalid", f"无效 atom ID：{atom_id}")
        if row.get("maturity") not in MATURITIES:
            return _failure("maturity_invalid", f"{atom_id} 成熟度无效")
        for field in ("action", "inputs", "state_model", "outputs", "failure_modes", "recovery", "acceptance"):
            if not row.get(field):
                return _failure("contract_field_missing", f"{atom_id} 缺少 {field}")
        if row.get("maturity") == "executable_ready" and not row.get("runtime_binding"):
            return _failure("runtime_binding_missing", f"{atom_id} 已标可执行但没有运行时绑定")
        ids.append(atom_id)
    if len(ids) != len(set(ids)):
        return _failure("duplicate_atom_id", "atomic_capability_id 必须唯一")
    return _success(
        "valid",
        None,
        {
            "engine_version": ENGINE_VERSION,
            "atomic_capability_count": len(ids),
            "registry_sha256": _digest(registry),
        },
    )


def _safe_record(
    module_id: str,
    record: Any,
    index: int,
    allowed_fields: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(record, Mapping):
        return None, {"module_id": module_id, "record_index": index, "reason": "record_not_object"}
    raw_values = record.get("values")
    if not isinstance(raw_values, Mapping):
        return None, {"module_id": module_id, "record_index": index, "reason": "values_not_object"}
    values = {str(key): deepcopy(value) for key, value in raw_values.items() if str(key) in allowed_fields}
    unknown_fields = sorted(str(key) for key in raw_values if str(key) not in allowed_fields)
    raw_id = str(record.get("id") or "")
    record_id = raw_id if re.fullmatch(r"r-[A-Za-z0-9._-]{1,120}", raw_id) else (
        f"r-import-{index}-{_digest({'module_id': module_id, 'record': record})[:12]}"
    )
    safe = {
        "id": record_id,
        "values": values,
        "completed": bool(record.get("completed")),
        "archived": bool(record.get("archived")),
        "createdAt": str(record.get("createdAt") or ""),
        "updatedAt": str(record.get("updatedAt") or ""),
    }
    known_record_keys = {"id", "values", "completed", "archived", "createdAt", "updatedAt"}
    unknown_record_keys = sorted(str(key) for key in record if key not in known_record_keys)
    quarantine = None
    if unknown_fields or unknown_record_keys or record_id != raw_id:
        quarantine = {
            "module_id": module_id,
            "record_index": index,
            "reason": "unknown_or_repaired_fields",
            "unknown_field_ids": unknown_fields,
            "unknown_record_keys": unknown_record_keys,
            "record_id_repaired": record_id != raw_id,
        }
    return safe, quarantine


def preview_import(
    current_state: Mapping[str, Any],
    backup: Mapping[str, Any],
    selected_module_fields: Mapping[str, Iterable[str]],
    *,
    max_records_per_module: int = 2000,
) -> dict[str, Any]:
    """产生不修改当前状态的导入候选、差异与隔离摘要。"""
    original = deepcopy(current_state)
    if not isinstance(backup, Mapping):
        return _failure("backup_invalid", "备份必须是对象", original)
    if backup.get("productId") not in {None, current_state.get("productId")}:
        return _failure("product_mismatch", "备份不属于当前产品", original)
    modules = backup.get("modules")
    if not isinstance(modules, Mapping):
        return _failure("modules_missing", "备份缺少 modules 对象", original)
    selected = {str(key): {str(field) for field in fields} for key, fields in selected_module_fields.items()}
    candidate = deepcopy(original)
    candidate["modules"] = deepcopy(original.get("modules", {}))
    quarantined: list[dict[str, Any]] = []
    changed_modules: list[str] = []
    module_diffs: list[dict[str, Any]] = []
    for module_id in sorted(selected):
        source = modules.get(module_id, {})
        rows = source.get("records", []) if isinstance(source, Mapping) else []
        if not isinstance(rows, list):
            return _failure("records_invalid", f"{module_id} records 必须是列表", original)
        if len(rows) > max_records_per_module:
            return _failure("record_limit_exceeded", f"{module_id} 记录超过上限", original)
        safe_rows: list[dict[str, Any]] = []
        for index, record in enumerate(rows):
            safe, quarantine = _safe_record(module_id, record, index, selected[module_id])
            if safe is not None:
                safe_rows.append(safe)
            if quarantine is not None:
                quarantined.append(quarantine)
        current_module = candidate["modules"].get(module_id, {})
        current_count = len(current_module.get("records", [])) if isinstance(current_module, Mapping) else 0
        next_module = deepcopy(current_module) if isinstance(current_module, Mapping) else {}
        next_module["records"] = safe_rows
        candidate["modules"][module_id] = next_module
        if current_module.get("records", []) != safe_rows:
            changed_modules.append(module_id)
        module_diffs.append({"module_id": module_id, "before": current_count, "after": len(safe_rows)})
    for module_id in sorted(str(key) for key in modules if str(key) not in selected):
        quarantined.append({"module_id": module_id, "reason": "module_not_selected"})
    preview = {
        "changed_module_ids": changed_modules,
        "module_record_counts": module_diffs,
        "quarantine_count": len(quarantined),
        "quarantine": quarantined,
        "candidate_sha256": _digest(candidate),
        "current_state_sha256": _digest(original),
    }
    return _success(
        "preview_ready",
        original,
        {
            "engine_version": ENGINE_VERSION,
            "preview_sha256": _digest(preview),
            "mutation_applied": False,
        },
        preview=preview,
        candidate_state=candidate,
    )


def parse_backup_text(raw: str) -> dict[str, Any]:
    """只接受合法 JSON 对象。坏文件不得被收成历史备注。"""
    if not isinstance(raw, str) or not raw.strip():
        return _failure("backup_empty", "备份是空的，当前数据未改动")
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_IMPORT_BYTES:
        return _failure("backup_too_large", "备份超过 8 MB，当前数据未改动")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _failure("invalid_json", "备份不是合法 JSON，当前数据未改动")
    if not isinstance(payload, Mapping):
        return _failure("backup_invalid", "备份必须是对象，当前数据未改动")
    return _success(
        "parsed",
        payload,
        {"engine_version": ENGINE_VERSION, "byte_size": len(encoded), "mutation_applied": False},
    )


def write_with_rollback(previous_raw: str | None, new_raw: str, writer: Any) -> dict[str, Any]:
    """写入失败时把存储恢复成写入前的字节。"""
    previous = previous_raw
    try:
        writer(new_raw)
        return _success(
            "written",
            new_raw,
            {
                "engine_version": ENGINE_VERSION,
                "previous_sha256": sha256((previous or "").encode("utf-8")).hexdigest(),
                "written_sha256": sha256(new_raw.encode("utf-8")).hexdigest(),
                "rolled_back": False,
            },
        )
    except Exception as exc:
        try:
            writer(previous if previous is not None else "")
        except Exception:
            pass
        return _failure(
            "storage_write_failed",
            f"写入失败，已尝试恢复原数据：{exc}",
            previous,
        )


def confirm_import(current_state: Mapping[str, Any], preview: Mapping[str, Any], confirmed: bool) -> dict[str, Any]:
    """仅对同一 current-state 产生的预览执行原子替换。"""
    original = deepcopy(current_state)
    original_digest = _digest(original)
    if not confirmed:
        return _failure("confirmation_missing", "没有当前确认，不执行导入", original)
    detail = preview.get("preview") if isinstance(preview, Mapping) else None
    candidate = preview.get("candidate_state") if isinstance(preview, Mapping) else None
    if not isinstance(detail, Mapping) or not isinstance(candidate, Mapping):
        return _failure("preview_missing", "必须先产生有效预览", original)
    if detail.get("current_state_sha256") != original_digest:
        return _failure("preview_stale", "当前状态已变化，请重新预览", original)
    if detail.get("candidate_sha256") != _digest(candidate):
        return _failure("candidate_tampered", "导入候选与预览不一致", original)
    if _digest(original) != original_digest:
        return _failure("current_mutated", "确认过程中当前数据被改动，已拒绝导入", original)
    return _success(
        "imported",
        candidate,
        {
            "engine_version": ENGINE_VERSION,
            "preview_sha256": preview.get("receipt", {}).get("preview_sha256"),
            "previous_state_sha256": original_digest,
            "imported_state_sha256": _digest(candidate),
            "mutation_applied": True,
        },
    )


WORKSPACE_CONTRACT = "double6_workspace_v1"
WORKSPACE_SCHEMA_VERSION = 4
ACCEPTED_WORKSPACE_SCHEMAS = {2, 3, 4}
MAX_WORKSPACE_SNAPSHOTS = 5
SNAPSHOT_REASONS = {"before_import", "before_clear", "before_restore"}


def workspace_export_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    """导出可携带备份；恢复点和本机能力四态只留在当前设备。"""
    payload = deepcopy(state)
    payload.pop("snapshots", None)
    payload.pop("runtimeCapabilities", None)
    payload.pop("storageBackend", None)
    return payload


def _safe_snapshots(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for row in raw[:MAX_WORKSPACE_SNAPSHOTS]:
        if not isinstance(row, Mapping):
            continue
        snapshot_id = str(row.get("snapshotId") or "")
        workspace = row.get("workspace")
        if not snapshot_id.startswith("s-") or not isinstance(workspace, Mapping):
            continue
        items.append(
            {
                "snapshotId": snapshot_id[:80],
                "createdAt": str(row.get("createdAt") or ""),
                "reason": str(row.get("reason") or "before_import")[:40],
                "recordCount": int(row.get("recordCount") or 0),
                "packId": str(row.get("packId") or workspace.get("packId") or ""),
                "schemaVersion": int(row.get("schemaVersion") or workspace.get("schemaVersion") or WORKSPACE_SCHEMA_VERSION),
                "moduleIds": [
                    str(item)
                    for item in (row.get("moduleIds") or list((workspace.get("modules") or {}).keys()))
                ],
                "workspace": workspace_export_payload(workspace),
            }
        )
    return items[:MAX_WORKSPACE_SNAPSHOTS]


MAX_IMPORT_LOG = 10


def record_import_provenance(
    log: Any,
    *,
    source_name: str,
    source_pack_id: str,
    current_pack_id: str,
    changed_modules: Sequence[Mapping[str, Any]],
    quarantine_count: int,
    snapshot_id: str = "",
    imported_at: str = "",
) -> dict[str, Any]:
    """追加一条导入出处，最多保留 10 条。"""
    rows = [row for row in (log or []) if isinstance(row, Mapping)]
    pack = workspace_pack_compat(source_pack_id, current_pack_id, [], [])
    entry = {
        "importedAt": str(imported_at or ""),
        "sourceName": str(source_name or "未命名备份")[:200],
        "sourcePackId": str(source_pack_id or ""),
        "currentPackId": str(current_pack_id or ""),
        "changedModules": [
            {
                "module_id": str(row.get("module_id") or ""),
                "before": int(row.get("before") or 0),
                "after": int(row.get("after") or 0),
            }
            for row in changed_modules
            if isinstance(row, Mapping)
        ][:40],
        "quarantineCount": int(quarantine_count or 0),
        "snapshotId": str(snapshot_id or "")[:80],
        "packStatus": pack["status"],
        "packNote": pack["note"],
    }
    next_log = [entry, *rows][:MAX_IMPORT_LOG]
    return _success(
        "recorded",
        next_log,
        {
            "engine_version": ENGINE_VERSION,
            "entry_count": len(next_log),
            "pack_status": pack["status"],
        },
        entry=entry,
    )


def workspace_pack_compat(
    source_pack_id: str,
    target_pack_id: str,
    source_module_ids: Sequence[str] = (),
    target_module_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """判断一份备份或恢复点相对当前工作台能否迁上来。"""
    source_pack = str(source_pack_id or "")
    target_pack = str(target_pack_id or "")
    source_set = {str(item) for item in source_module_ids}
    target_set = {str(item) for item in target_module_ids}
    mapped = sorted(source_set & target_set) if source_set and target_set else []
    unmapped = sorted(source_set - target_set) if source_set and target_set else []
    if source_pack and target_pack and source_pack == target_pack:
        return {
            "status": "same",
            "migratable": True,
            "mapped_module_ids": mapped,
            "unmapped_module_ids": unmapped,
            "note": "同一套工作台，可直接恢复。",
        }
    if unmapped:
        return {
            "status": "migrated_with_unmapped",
            "migratable": True,
            "mapped_module_ids": mapped,
            "unmapped_module_ids": unmapped,
            "note": "工作台版本不同。对得上的模块会迁上来，其余进未映射区，不会悄悄丢掉。",
        }
    if source_pack and target_pack and source_pack != target_pack:
        return {
            "status": "migrated",
            "migratable": True,
            "mapped_module_ids": mapped,
            "unmapped_module_ids": unmapped,
            "note": "工作台版本不同，模块都能对上，可以迁上来。",
        }
    return {
        "status": "unknown",
        "migratable": True,
        "mapped_module_ids": mapped,
        "unmapped_module_ids": unmapped,
        "note": "没有版本标记，按字段尽量迁上来。",
    }


def product_revision_diff(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """比较两版产品合同：模块增减、组合包变化和字段变化。"""
    prev_plan = previous.get("recommendation_plan") if isinstance(previous.get("recommendation_plan"), Mapping) else {}
    curr_plan = current.get("recommendation_plan") if isinstance(current.get("recommendation_plan"), Mapping) else {}
    prev_mods = [str(item) for item in prev_plan.get("selected_core_module_ids") or []]
    curr_mods = [str(item) for item in curr_plan.get("selected_core_module_ids") or []]
    added = [item for item in curr_mods if item not in prev_mods]
    removed = [item for item in prev_mods if item not in curr_mods]
    prev_pack = str(prev_plan.get("pack_id") or "")
    curr_pack = str(curr_plan.get("pack_id") or "")
    prev_fields: dict[str, list[str]] = {}
    curr_fields: dict[str, list[str]] = {}
    for row in previous.get("capabilities") or []:
        if isinstance(row, Mapping) and row.get("recommendation_module_id"):
            surface = row.get("surface") if isinstance(row.get("surface"), Mapping) else {}
            prev_fields[str(row["recommendation_module_id"])] = [
                str(field.get("field_id") or "")
                for field in surface.get("fields") or []
                if isinstance(field, Mapping)
            ]
    for row in current.get("capabilities") or []:
        if isinstance(row, Mapping) and row.get("recommendation_module_id"):
            surface = row.get("surface") if isinstance(row.get("surface"), Mapping) else {}
            curr_fields[str(row["recommendation_module_id"])] = [
                str(field.get("field_id") or "")
                for field in surface.get("fields") or []
                if isinstance(field, Mapping)
            ]
    field_changes = []
    for module_id in sorted(set(prev_fields) & set(curr_fields)):
        lost = [item for item in prev_fields[module_id] if item and item not in curr_fields[module_id]]
        gained = [item for item in curr_fields[module_id] if item and item not in prev_fields[module_id]]
        if lost or gained:
            field_changes.append({"module_id": module_id, "lost_fields": lost, "gained_fields": gained})
    return {
        "contract_version": "double6_product_revision_diff_v1",
        "added_module_ids": added,
        "removed_module_ids": removed,
        "unchanged_module_ids": [item for item in curr_mods if item in prev_mods],
        "pack_changed": prev_pack != curr_pack,
        "previous_pack_id": prev_pack,
        "current_pack_id": curr_pack,
        "field_changes": field_changes,
        "has_changes": bool(added or removed or field_changes or prev_pack != curr_pack),
    }


def first_run_visible(state: Mapping[str, Any]) -> bool:
    """未见过且还没有自有记录时才显示第一次说明。"""
    if not isinstance(state, Mapping):
        return True
    if state.get("firstRunSeen"):
        return False
    return _record_count(state) == 0


def _record_count(state: Mapping[str, Any]) -> int:
    modules = state.get("modules")
    if not isinstance(modules, Mapping):
        return 0
    total = 0
    for row in modules.values():
        records = row.get("records") if isinstance(row, Mapping) else []
        if isinstance(records, list):
            total += len(records)
    return total


RUNTIME_CAPABILITY_CONTRACT = "double6_runtime_capabilities_v1"
RUNTIME_CAPABILITY_STATES = {"ready", "broken", "declined", "stale"}
RUNTIME_CAPABILITY_IDS = ("storage", "import_export", "clipboard", "reminder")
OPTIONAL_RUNTIME_CAPABILITIES = {"clipboard", "reminder"}
RUNTIME_CAPABILITY_EVENTS = {
    "persist_ok": ("storage", "ready", "", ""),
    "persist_quota": ("storage", "broken", "当前设备存储已满，没法再写入。", "先导出备份，再删掉不用的记录后重试。"),
    "persist_denied": ("storage", "broken", "浏览器拒绝写入本机存储。", "检查是否关闭了网站数据，或换一个浏览器再试。"),
    "import_ok": ("import_export", "ready", "", ""),
    "import_too_large": ("import_export", "stale", "备份超过 8 MB，没有改当前数据。", "拆成更小的备份，或先清掉不用的记录。"),
    "import_unavailable": ("import_export", "broken", "当前浏览器不能生成或读取备份文件。", "换一个现代浏览器，或请别人帮你导出。"),
    "clipboard_ok": ("clipboard", "ready", "", ""),
    "clipboard_missing": ("clipboard", "broken", "当前环境没有剪贴板接口。", "用导出备份代替复制，或换浏览器。"),
    "clipboard_denied": ("clipboard", "declined", "你没有允许使用剪贴板。", "可在浏览器权限里允许，或改用导出文件。"),
    "reminder_saved": ("reminder", "ready", "", ""),
    "reminder_notify_denied": ("reminder", "declined", "系统通知已被拒绝。本地提醒意图仍可记下。", "要弹通知需在浏览器设置里允许，或继续只用本机记录。"),
}


def empty_runtime_capabilities() -> dict[str, dict[str, str]]:
    return {
        capability_id: {"status": "ready", "reason": "", "repair": "", "updatedAt": ""}
        for capability_id in RUNTIME_CAPABILITY_IDS
    }


def _safe_runtime_capabilities(raw: Any) -> dict[str, dict[str, str]]:
    next_caps = empty_runtime_capabilities()
    if not isinstance(raw, Mapping):
        return next_caps
    for capability_id in RUNTIME_CAPABILITY_IDS:
        row = raw.get(capability_id)
        if not isinstance(row, Mapping) or row.get("status") not in RUNTIME_CAPABILITY_STATES:
            continue
        next_caps[capability_id] = {
            "status": str(row["status"]),
            "reason": str(row.get("reason") or "")[:200],
            "repair": str(row.get("repair") or "")[:200],
            "updatedAt": str(row.get("updatedAt") or ""),
        }
    return next_caps


def runtime_capability_summary(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    """列出降级项和仍可用项；declined 计入降级但不算失败。"""
    caps = _safe_runtime_capabilities(capabilities)
    degraded = [
        {"capability_id": capability_id, "status": row["status"], "reason": row["reason"], "repair": row["repair"]}
        for capability_id, row in caps.items()
        if row["status"] != "ready"
    ]
    return {
        "contract_version": RUNTIME_CAPABILITY_CONTRACT,
        "degraded": degraded,
        "ready_ids": [capability_id for capability_id, row in caps.items() if row["status"] == "ready"],
        "declined_ids": [row["capability_id"] for row in degraded if row["status"] == "declined"],
        "failure": any(row["status"] == "broken" for row in degraded),
    }


def apply_runtime_capability_event(
    capabilities: Mapping[str, Any],
    event: str,
    *,
    capability_id: str | None = None,
) -> dict[str, Any]:
    """按一次真实探测或用户选择更新四态。用户拒绝返回成功。"""
    original = _safe_runtime_capabilities(capabilities)
    if event == "user_decline":
        if capability_id not in OPTIONAL_RUNTIME_CAPABILITIES:
            return _failure("capability_not_optional", "只有可选能力能被用户关闭", original)
        next_caps = deepcopy(original)
        next_caps[capability_id] = {
            "status": "declined",
            "reason": "你已关闭这项可选能力。",
            "repair": "需要时再点重新启用。",
            "updatedAt": "",
        }
        summary = runtime_capability_summary(next_caps)
        return _success(
            "declined",
            next_caps,
            {
                "engine_version": ENGINE_VERSION,
                "capability_id": capability_id,
                "not_failure": True,
                "degraded": summary["degraded"],
            },
        )
    spec = RUNTIME_CAPABILITY_EVENTS.get(event)
    if spec is None:
        return _failure("capability_event_unknown", "未知的本机能力事件", original)
    target_id, status, reason, repair = spec
    next_caps = deepcopy(original)
    next_caps[target_id] = {"status": status, "reason": reason, "repair": repair, "updatedAt": ""}
    summary = runtime_capability_summary(next_caps)
    return _success(
        status,
        next_caps,
        {
            "engine_version": ENGINE_VERSION,
            "capability_id": target_id,
            "event": event,
            "not_failure": status == "declined",
            "degraded": summary["degraded"],
        },
    )


def probe_runtime_capabilities(
    environment: Mapping[str, Any] | None = None,
    declined_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """根据当前设备能力探测四态，不接云服务。"""
    env = environment or {}
    declined = {str(item) for item in declined_ids}
    caps = empty_runtime_capabilities()
    if env.get("local_storage", True) is False:
        caps = apply_runtime_capability_event(caps, "persist_denied")["state"]
    if env.get("file_reader", True) is False or env.get("blob", True) is False:
        caps = apply_runtime_capability_event(caps, "import_unavailable")["state"]
    if "clipboard" in declined or env.get("clipboard") == "denied":
        caps = apply_runtime_capability_event(caps, "clipboard_denied")["state"]
    elif env.get("clipboard") == "missing":
        caps = apply_runtime_capability_event(caps, "clipboard_missing")["state"]
    if "reminder" in declined or env.get("notification") == "denied":
        caps = apply_runtime_capability_event(caps, "reminder_notify_denied")["state"]
    summary = runtime_capability_summary(caps)
    return _success(
        "probed",
        caps,
        {
            "engine_version": ENGINE_VERSION,
            "contract_version": RUNTIME_CAPABILITY_CONTRACT,
            "degraded": summary["degraded"],
            "declined_is_not_failure": True,
            "failure": summary["failure"],
        },
    )


def migrate_workspace(
    value: Mapping[str, Any],
    *,
    product_id: str,
    pack_id: str,
    storage_key: str,
    keep_snapshots: bool = False,
) -> dict[str, Any]:
    """把 schemaVersion 2/3/4 收成当前 workspace 合同。"""
    if not isinstance(value, Mapping):
        return _failure("workspace_invalid", "工作区必须是对象")
    if value.get("productId") != product_id:
        return _failure("workspace_identity_mismatch", "工作区不属于当前产品")
    if value.get("schemaVersion") not in ACCEPTED_WORKSPACE_SCHEMAS:
        return _failure("workspace_schema_unsupported", "不支持的工作区版本")
    ownership = value.get("ownership") if isinstance(value.get("ownership"), Mapping) else {}
    source_modules = value.get("modules") if isinstance(value.get("modules"), Mapping) else {}
    pack_migration = (
        workspace_pack_compat(str(value.get("packId") or ""), pack_id, list(source_modules), [])
        if value.get("packId") and value.get("packId") != pack_id
        else None
    )
    next_state = {
        "schemaVersion": WORKSPACE_SCHEMA_VERSION,
        "contractVersion": WORKSPACE_CONTRACT,
        "productId": product_id,
        "packId": pack_id,
        "ownership": {
            "kind": "device_local",
            "namespace": storage_key,
            "sync": "not_connected",
        },
        "modules": deepcopy(source_modules),
        "rewards": deepcopy(value.get("rewards") or {}),
        "workflowIntents": deepcopy(value.get("workflowIntents") or {"reminders": {}, "handoffs": {}}),
        "legacyImport": deepcopy(value.get("legacyImport")),
        "snapshots": _safe_snapshots(value.get("snapshots")) if keep_snapshots else [],
        "runtimeCapabilities": (
            _safe_runtime_capabilities(value.get("runtimeCapabilities"))
            if keep_snapshots
            else empty_runtime_capabilities()
        ),
        "firstRunSeen": bool(value.get("firstRunSeen")),
        "importLog": [
            row for row in (value.get("importLog") or []) if isinstance(row, Mapping)
        ][:MAX_IMPORT_LOG],
        "packMigration": pack_migration,
        "updatedAt": str(value.get("updatedAt") or ""),
    }
    if ownership.get("kind") == "device_local" and ownership.get("namespace"):
        next_state["ownership"]["namespace"] = str(ownership.get("namespace"))
    return _success(
        "migrated",
        next_state,
        {
            "engine_version": ENGINE_VERSION,
            "from_schema": value.get("schemaVersion"),
            "to_schema": WORKSPACE_SCHEMA_VERSION,
            "contract_version": WORKSPACE_CONTRACT,
            "snapshots_kept": keep_snapshots,
        },
    )


def capture_workspace_snapshot(state: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """在破坏性写入前追加一条本机恢复点，最多保留 5 条。"""
    original = deepcopy(state)
    if reason not in SNAPSHOT_REASONS:
        return _failure("snapshot_reason_invalid", "恢复点原因必须是导入前、清空前或恢复前", original)
    item = {
        "snapshotId": f"s-{_digest({'reason': reason, 'state': workspace_export_payload(original)})[:16]}",
        "createdAt": str(original.get("updatedAt") or ""),
        "reason": reason,
        "recordCount": _record_count(original),
        "workspace": workspace_export_payload(original),
    }
    next_state = deepcopy(original)
    next_state["snapshots"] = [item, *_safe_snapshots(original.get("snapshots"))][:MAX_WORKSPACE_SNAPSHOTS]
    return _success(
        "snapshot_captured",
        next_state,
        {
            "engine_version": ENGINE_VERSION,
            "snapshot_id": item["snapshotId"],
            "snapshot_count": len(next_state["snapshots"]),
            "reason": reason,
        },
        snapshot=item,
    )


def restore_workspace_snapshot(state: Mapping[str, Any], snapshot_id: str) -> dict[str, Any]:
    """用本机恢复点替换当前工作区；恢复点列表本身保留。"""
    original = deepcopy(state)
    items = _safe_snapshots(original.get("snapshots"))
    item = next((row for row in items if row["snapshotId"] == snapshot_id), None)
    if item is None:
        return _failure("snapshot_missing", "找不到这个恢复点", original)
    restored = deepcopy(item["workspace"])
    restored["snapshots"] = items
    return _success(
        "restored",
        restored,
        {
            "engine_version": ENGINE_VERSION,
            "snapshot_id": snapshot_id,
            "record_count": item["recordCount"],
            "mutation_applied": True,
        },
    )


def record_metric(samples: Sequence[Mapping[str, Any]], event: Mapping[str, Any]) -> dict[str, Any]:
    original = deepcopy(list(samples))
    metric_id = str(event.get("metric_id") or "").strip()
    recorded_at = str(event.get("recorded_at") or "").strip()
    try:
        value = float(event.get("value"))
    except (TypeError, ValueError):
        return _failure("invalid_value", "指标值必须是有限数字", original)
    if not metric_id:
        return _failure("metric_missing", "必须声明 metric_id", original)
    if not math.isfinite(value):
        return _failure("invalid_value", "指标值必须是有限数字", original)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", recorded_at):
        return _failure("recorded_at_invalid", "必须提供有效记录时间", original)
    source_ref = str(event.get("source_ref") or "").strip()
    method = str(event.get("method") or "manual").strip()
    if method not in {"manual", "imported", "calculated"}:
        return _failure("unknown_method", "未知指标记录方法", original)
    sample = {
        "sample_id": f"metric-{_digest(event)[:16]}",
        "metric_id": metric_id,
        "value": value,
        "unit": str(event.get("unit") or "unitless").strip() or "unitless",
        "recorded_at": recorded_at,
        "source_ref": source_ref or None,
        "source_status": "verified" if source_ref else "unverified",
        "method": method,
        "correction_of": str(event.get("correction_of") or "") or None,
    }
    if sample["correction_of"] and sample["correction_of"] not in {
        str(row.get("sample_id")) for row in original
    }:
        return _failure("correction_target_missing", "更正目标不存在", original)
    next_samples = [*original, sample]
    return _success(
        "recorded",
        next_samples,
        {
            "engine_version": ENGINE_VERSION,
            "sample_id": sample["sample_id"],
            "source_status": sample["source_status"],
            "append_only": True,
        },
        metric_sample=sample,
    )


def summarize_metrics(
    samples: Sequence[Mapping[str, Any]],
    metric_id: str,
    aggregation_method: str,
) -> dict[str, Any]:
    selected = [deepcopy(row) for row in samples if row.get("metric_id") == metric_id]
    if not selected:
        return _success(
            "insufficient_data",
            list(samples),
            {"engine_version": ENGINE_VERSION, "method": aggregation_method, "source_sample_ids": []},
            summary=None,
            coverage_gap="no_matching_samples",
        )
    units = {str(row.get("unit") or "unitless") for row in selected}
    if len(units) != 1:
        return _failure("mixed_units", "不同单位必须分开汇总", list(samples))
    if aggregation_method not in {"sum", "average", "latest"}:
        return _failure("method_missing", "汇总方法必须是 sum、average 或 latest", list(samples))
    values = [float(row["value"]) for row in selected]
    if aggregation_method == "sum":
        value = sum(values)
    elif aggregation_method == "average":
        value = sum(values) / len(values)
    else:
        value = float(max(selected, key=lambda row: str(row.get("recorded_at") or ""))["value"])
    source_ids = [str(row["sample_id"]) for row in selected]
    summary = {
        "metric_id": metric_id,
        "value": value,
        "unit": next(iter(units)),
        "method": aggregation_method,
        "source_sample_ids": source_ids,
    }
    return _success(
        "summary_ready",
        list(samples),
        {"engine_version": ENGINE_VERSION, "method": aggregation_method, "source_sample_ids": source_ids},
        summary=summary,
        coverage_gap=None,
    )


def retrieve_library_items(
    query: str,
    items: Sequence[Mapping[str, Any]],
    selected_item_ids: Iterable[str],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    text = str(query).strip().casefold()
    if not text:
        return _success(
            "empty",
            None,
            {"engine_version": ENGINE_VERSION, "query": "", "result_count": 0},
            results=[],
            honest_empty_state="请输入关键词；空查询不会展开全部资料。",
        )
    if len(text) > 200:
        return _failure("query_too_long", "检索词不能超过 200 字符")
    selected = {str(value) for value in selected_item_ids}
    matches: list[dict[str, Any]] = []
    for row in items:
        item_id = str(row.get("item_id") or row.get("fact_id") or "")
        if item_id not in selected:
            continue
        haystack = " ".join(str(value) for value in row.values()).casefold()
        if text in haystack:
            matches.append({
                "item_id": item_id,
                "title": str(row.get("title") or row.get("text") or item_id),
                "source_status": str(row.get("source_status") or "unverified"),
                "source_ref": row.get("source_ref"),
            })
    matches.sort(key=lambda row: row["item_id"])
    results = matches[: max(1, min(int(limit), 100))]
    return _success(
        "results" if results else "empty",
        None,
        {"engine_version": ENGINE_VERSION, "query": text, "result_count": len(results)},
        results=results,
        honest_empty_state=None if results else "选定资料范围内没有匹配项。",
    )


def generate_review_draft(
    selected_fact_ids: Sequence[str],
    facts: Sequence[Mapping[str, Any]],
    draft_type: str,
) -> dict[str, Any]:
    by_id = {str(row.get("fact_id") or ""): deepcopy(row) for row in facts}
    if not selected_fact_ids:
        return _failure("fact_missing", "至少选择一条事实")
    if set(selected_fact_ids) - set(by_id):
        return _failure("fact_missing", "所选事实不在当前选定范围")
    selected = [by_id[str(fact_id)] for fact_id in selected_fact_ids]
    mapping: list[dict[str, Any]] = []
    lines = [f"草稿｜{str(draft_type).strip() or '待审核内容'}"]
    for index, fact in enumerate(selected, start=1):
        source_ref = str(fact.get("source_ref") or "").strip()
        source_status = str(fact.get("source_status") or ("verified" if source_ref else "gap"))
        marker = source_ref or "[来源缺口：发布前补充]"
        lines.append(f"{index}. {str(fact.get('text') or fact.get('title') or '').strip()}（{marker}）")
        mapping.append({
            "fact_id": str(fact.get("fact_id")),
            "source_status": source_status,
            "source_ref": source_ref or None,
        })
    lines.append("状态：仅为草稿，尚未发送或发布，必须人工审核。")
    draft = "\n".join(lines)
    gaps = [row["fact_id"] for row in mapping if not row["source_ref"]]
    return _success(
        "draft",
        None,
        {
            "engine_version": ENGINE_VERSION,
            "selected_fact_ids": list(selected_fact_ids),
            "source_gap_fact_ids": gaps,
            "external_status": "not_executed",
        },
        draft_text=draft,
        fact_and_source_map=mapping,
        review_status="human_review_required",
    )


def confirm_external_operation(
    operation_type: str,
    target: str,
    payload_preview: str,
    impact: str,
    user_confirmation: bool,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    draft = {
        "operation_type": str(operation_type).strip(),
        "target": str(target).strip(),
        "payload_preview": str(payload_preview).strip(),
        "impact": str(impact).strip(),
    }
    if not all(draft.values()):
        return _failure("operation_invalid", "操作、目标、载荷预览和影响都必须明确", draft)
    if not user_confirmation:
        return _success(
            "confirmation_pending",
            draft,
            {"engine_version": ENGINE_VERSION, "external_status": "not_executed", "side_effect": False},
        )
    receipt = {
        "engine_version": ENGINE_VERSION,
        "confirmation_id": f"handoff-{_digest({**draft, 'idempotency_key': idempotency_key})[:16]}",
        "idempotency_key": idempotency_key,
        "external_status": "not_executed",
        "side_effect": False,
        "next_step": "manual_handoff",
    }
    return _success("manual_handoff_ready", draft, receipt)


LEDGER_CSV_SPECS: dict[str, dict[str, Any]] = {
    "finance-transactions": {
        "label": "今晚流水",
        "headers": ["title", "entry_type", "amount", "category", "date", "notes"],
        "required": ["title", "entry_type", "amount"],
        "enums": {"entry_type": ["支出", "收入"]},
        "number_fields": ["amount"],
        "max_rows": 200,
    },
    "commerce-orders": {
        "label": "今晚订单",
        "headers": ["title", "stage", "next_action", "date"],
        "required": ["title"],
        "enums": {"stage": ["待发货", "记下已去平台处理"]},
        "number_fields": [],
        "max_rows": 200,
    },
    "teaching-attendance": {
        "label": "今日考勤",
        "headers": ["title", "status", "date"],
        "required": ["title", "status"],
        "enums": {"status": ["到", "假", "迟"]},
        "number_fields": [],
        "max_rows": 200,
    },
}


def _csv_safe(value: Any) -> str:
    text = str(value if value is not None else "")
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def export_selected_csv(
    selected_module_id: str,
    selected_field_ids: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    allowed_field_ids: Iterable[str],
) -> dict[str, Any]:
    fields = [str(value) for value in selected_field_ids]
    allowed = {str(value) for value in allowed_field_ids}
    if not fields:
        return _failure("no_selected_fields", "至少选择一个导出字段", list(records))
    if len(fields) != len(set(fields)) or set(fields) - allowed:
        return _failure("unknown_field", "导出字段不属于当前选定模块", list(records))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(fields)
    for record in records:
        values = record.get("values", {}) if isinstance(record, Mapping) else {}
        writer.writerow([_csv_safe(values.get(field_id)) for field_id in fields])
    csv_text = "\ufeff" + output.getvalue()
    return _success(
        "exported",
        list(records),
        {
            "engine_version": ENGINE_VERSION,
            "selected_module_id": str(selected_module_id),
            "selected_field_ids": fields,
            "record_count": len(records),
            "source_mutated": False,
            "csv_sha256": sha256(csv_text.encode()).hexdigest(),
        },
        csv_text=csv_text,
    )


def preview_ledger_csv(
    current_state: Mapping[str, Any],
    csv_text: str,
    module_id: str,
    *,
    mode: str = "append",
) -> dict[str, Any]:
    """记录型台账 CSV 预览。确认前不改当前数据。"""
    original = deepcopy(current_state)
    spec = LEDGER_CSV_SPECS.get(str(module_id))
    if spec is None:
        return _failure("ledger_not_allowed", "只有记账流水、店铺订单和考勤允许 CSV", original)
    if mode not in {"append", "replace"}:
        return _failure("mode_invalid", "CSV 只能追加或替换这一本台账", original)
    if not isinstance(csv_text, str) or not csv_text.strip():
        return _failure("csv_empty", "CSV 是空的，当前数据未改动", original)
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    except csv.Error:
        return _failure("csv_invalid", "CSV 解析失败，当前数据未改动", original)
    if not rows:
        return _failure("csv_empty", "CSV 没有数据行，当前数据未改动", original)
    if len(rows) > int(spec["max_rows"]):
        return _failure("csv_too_many", f"一次最多 {spec['max_rows']} 行，当前数据未改动", original)
    headers = [str(key) for key in (rows[0].keys() if rows else [])]
    missing = [name for name in spec["required"] if name not in headers]
    if missing:
        return _failure("csv_headers", f"缺少必要列：{'、'.join(missing)}", original)
    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        values: dict[str, Any] = {}
        for field in spec["headers"]:
            if field not in row:
                continue
            raw = str(row.get(field) or "").strip()
            if field in spec["number_fields"]:
                number = float(raw) if raw else 0
                if not math.isfinite(number) or number <= 0:
                    return _failure("csv_number", f"第 {index + 1} 行金额无效", original)
                values[field] = number
            else:
                values[field] = raw
        for field in spec["required"]:
            if values.get(field) in (None, ""):
                return _failure("csv_required", f"第 {index + 1} 行缺少 {field}", original)
        for field, allowed in spec["enums"].items():
            if field in values and values[field] not in allowed:
                return _failure("csv_enum", f"第 {index + 1} 行 {field} 只能是 {' / '.join(allowed)}", original)
        parsed.append(
            {
                "id": f"r-csv-{index}-{_digest({'module_id': module_id, 'row': values})[:12]}",
                "values": values,
                "completed": False,
                "archived": False,
                "createdAt": "",
                "updatedAt": "",
            }
        )
    modules = deepcopy(original.get("modules") or {})
    current_module = modules.get(module_id) if isinstance(modules.get(module_id), Mapping) else {}
    current_rows = list(current_module.get("records") or []) if isinstance(current_module, Mapping) else []
    next_rows = parsed if mode == "replace" else current_rows + parsed
    if len(next_rows) > MAX_RECORDS_PER_MODULE:
        return _failure("record_limit_exceeded", "导入后会超过每本台账 2000 条", original)
    preview = {
        "module_id": module_id,
        "mode": mode,
        "incoming": len(parsed),
        "before": len(current_rows),
        "after": len(next_rows),
        "sample": parsed[:4],
        "current_state_sha256": _digest(original),
        "candidate_records_sha256": _digest(next_rows),
    }
    return _success(
        "preview_ready",
        original,
        {
            "engine_version": ENGINE_VERSION,
            "mutation_applied": False,
            "preview_sha256": _digest(preview),
        },
        preview=preview,
        candidate_records=next_rows,
    )


def confirm_ledger_csv(
    current_state: Mapping[str, Any],
    preview: Mapping[str, Any],
    confirmed: bool,
) -> dict[str, Any]:
    original = deepcopy(current_state)
    if not confirmed:
        return _failure("confirmation_missing", "没有当前确认，不执行 CSV 导入", original)
    detail = preview.get("preview") if isinstance(preview, Mapping) else None
    records = preview.get("candidate_records") if isinstance(preview, Mapping) else None
    if not isinstance(detail, Mapping) or not isinstance(records, list):
        return _failure("preview_missing", "必须先产生有效 CSV 预览", original)
    if detail.get("current_state_sha256") != _digest(original):
        return _failure("preview_stale", "当前状态已变化，请重新预览", original)
    if detail.get("candidate_records_sha256") != _digest(records):
        return _failure("candidate_tampered", "CSV 候选与预览不一致", original)
    module_id = str(detail.get("module_id") or "")
    next_state = deepcopy(original)
    module = next_state.setdefault("modules", {}).setdefault(module_id, {"records": [], "starter": {}})
    module["records"] = deepcopy(records)
    return _success(
        "imported",
        next_state,
        {
            "engine_version": ENGINE_VERSION,
            "module_id": module_id,
            "mode": detail.get("mode"),
            "previous_state_sha256": detail.get("current_state_sha256"),
            "imported_state_sha256": _digest(next_state),
            "mutation_applied": True,
        },
    )


def schedule_local_reminder(
    target_record_id: str,
    remind_at: str,
    target_records: Sequence[Mapping[str, Any]],
    *,
    message_draft: str = "",
) -> dict[str, Any]:
    record_ids = {str(row.get("id") or "") for row in target_records}
    if str(target_record_id) not in record_ids:
        return _failure("target_missing", "提醒目标不存在", list(target_records))
    if not ISO_MINUTE.fullmatch(str(remind_at)):
        return _failure("invalid_time", "提醒时间必须是本地日期时间", list(target_records))
    intent = {
        "reminder_intent_id": f"reminder-{_digest({'target': target_record_id, 'at': remind_at})[:16]}",
        "target_record_id": str(target_record_id),
        "remind_at": str(remind_at),
        "message_draft": str(message_draft).strip(),
        "external_status": "not_executed",
    }
    return _success(
        "local_intent_saved",
        intent,
        {
            "engine_version": ENGINE_VERSION,
            "external_status": "not_executed",
            "notification_sent": False,
            "target_preserved": True,
        },
    )


REWARD_EVENT_TYPES = {"earn", "redeem", "reverse"}


def _reward_events(ledger: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in ledger if isinstance(row, Mapping)]


def reward_ledger_balance(ledger: Sequence[Mapping[str, Any]]) -> int:
    """奖励余额只从账本事件投影，不改掌握或完成证据。"""
    balance = 0
    for row in _reward_events(ledger):
        event_type = str(row.get("event_type") or "")
        points = int(row.get("points") or 0)
        if event_type == "earn":
            balance += points
        elif event_type == "redeem":
            balance -= points
        elif event_type == "reverse":
            balance += points
    return balance


def post_reward_ledger_event(
    ledger: Sequence[Mapping[str, Any]],
    *,
    completion_evidence_id: str,
    event_type: str,
    points: int,
    idempotency_key: str,
    reason: str = "",
) -> dict[str, Any]:
    """以完成证据和幂等键追加奖励事件；重复键复用，冲正只能新增。"""
    events = _reward_events(ledger)
    key = str(idempotency_key or "").strip()
    evidence = str(completion_evidence_id or "").strip()
    kind = str(event_type or "").strip()
    if kind not in REWARD_EVENT_TYPES:
        return _failure("invalid_event_type", "奖励事件只能是 earn、redeem 或 reverse", events)
    if not evidence:
        return _failure("evidence_missing", "奖励事件必须绑定完成证据", events)
    if not key:
        return _failure("idempotency_missing", "奖励事件必须有幂等键", events)
    if not isinstance(points, int) or points <= 0:
        return _failure("invalid_points", "奖励点数必须是正整数", events)
    existing = next((row for row in events if str(row.get("idempotency_key") or "") == key), None)
    if existing:
        return _success(
            "duplicate_reused",
            events,
            {
                "engine_version": ENGINE_VERSION,
                "duplicate_status": "reused",
                "reward_event_id": existing.get("event_id"),
                "balance_projection": reward_ledger_balance(events),
                "affects_mastery": False,
            },
            reward_event=existing,
        )
    event = {
        "event_id": f"reward-{_digest({'key': key, 'type': kind, 'evidence': evidence})[:16]}",
        "event_type": kind,
        "points": points,
        "completion_evidence_id": evidence,
        "idempotency_key": key,
        "reason": str(reason or "").strip(),
        "affects_mastery": False,
        "affects_completion_evidence": False,
    }
    next_events = [*events, event]
    return _success(
        "posted",
        next_events,
        {
            "engine_version": ENGINE_VERSION,
            "duplicate_status": "new",
            "reward_event_id": event["event_id"],
            "balance_projection": reward_ledger_balance(next_events),
            "affects_mastery": False,
        },
        reward_event=event,
    )


def request_reward_redemption(
    ledger: Sequence[Mapping[str, Any]],
    reward_item_id: str,
    cost: int,
    *,
    adult_confirmed: bool,
    note: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """余额足够才接受兑换请求；未家长确认不扣星，确认后只改奖励账本。"""
    events = _reward_events(ledger)
    item_id = str(reward_item_id or "").strip()
    if not item_id:
        return _failure("unknown_reward_item", "兑换目标不存在", events)
    if not isinstance(cost, int) or cost <= 0:
        return _failure("invalid_cost", "兑换成本必须是正整数", events)
    key = str(idempotency_key or f"redeem:{item_id}:{cost}").strip()
    existing = next((row for row in events if str(row.get("idempotency_key") or "") == key), None)
    if existing:
        return _success(
            "duplicate_reused",
            events,
            {
                "engine_version": ENGINE_VERSION,
                "approval_status": "already_posted",
                "duplicate_status": "reused",
                "balance_projection": reward_ledger_balance(events),
                "affects_mastery": False,
            },
            redemption_request=existing,
        )
    balance = reward_ledger_balance(events)
    request = {
        "reward_item_id": item_id,
        "cost": cost,
        "note": str(note or "").strip(),
        "idempotency_key": key,
        "pending_balance_projection": balance - cost,
        "affects_mastery": False,
    }
    if balance < cost:
        return _failure("insufficient_balance", "星星还不够，未扣减", events)
    if not adult_confirmed:
        return _success(
            "requested",
            events,
            {
                "engine_version": ENGINE_VERSION,
                "approval_status": "pending_adult",
                "balance_projection": balance,
                "affects_mastery": False,
                "side_effect": False,
            },
            redemption_request=request,
        )
    posted = post_reward_ledger_event(
        events,
        completion_evidence_id=f"redeem:{item_id}",
        event_type="redeem",
        points=cost,
        idempotency_key=key,
        reason=str(note or item_id),
    )
    if not posted["ok"]:
        return posted
    return _success(
        "ledger_posted",
        posted["state"],
        {
            "engine_version": ENGINE_VERSION,
            "approval_status": "approved",
            "reward_event_id": posted["receipt"]["reward_event_id"],
            "balance_projection": posted["receipt"]["balance_projection"],
            "affects_mastery": False,
            "external_status": "not_executed",
        },
        redemption_request=request,
        reward_event=posted.get("reward_event"),
    )
