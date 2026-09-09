from __future__ import annotations

from typing import Any


SOURCE_REPAIR_CATEGORIES = {"content", "layout", "placeholder", "structure", "data", "chart", "table", "notes"}
BOUNDED_PATCH_PROPERTIES = {"text", "color", "fill", "font", "size", "x", "y", "width", "height"}


def route_finding(finding: dict[str, Any], *, mode: str, has_source_map: bool) -> dict[str, Any]:
    category = str(finding.get("category", "visual"))
    suggested = finding.get("suggested_property")
    unique = bool(finding.get("object", {}).get("officecli_path"))
    if mode == "generate" and category in SOURCE_REPAIR_CATEGORIES:
        route = "source_repair"
        reason = "生成型 deck 的内容、结构、数据或布局问题必须回源，确保重建后不丢失。"
    elif finding.get("suggested_operation") == "remove_leaf" and unique and finding.get("deterministic") is True:
        if finding.get("object", {}).get("object_type") == "picture" and finding.get("user_confirmed") is not True:
            route = "manual_review"
            reason = "语义图片即使可精确定位也必须由用户确认后删除或替换。"
        else:
            route = "bounded_patch"
            reason = "模板样例叶子对象有稳定地址和指纹，可在副本中执行确定性删除。"
    elif suggested in BOUNDED_PATCH_PROPERTIES and unique and (has_source_map or finding.get("deterministic") is True or finding.get("user_confirmed") is True):
        route = "bounded_patch"
        reason = "目标唯一且属性属于受限白名单；补丁仍必须作用于副本。"
    elif mode == "postflight" and not has_source_map:
        route = "manual_review"
        reason = "已有 PPTX 没有可信 source map，默认只诊断；自动补丁需唯一地址和用户确认。"
    elif category in SOURCE_REPAIR_CATEGORIES and has_source_map:
        route = "source_repair"
        reason = "问题与可追踪源对象相关，回源修复更稳定。"
    else:
        route = "manual_review"
        reason = "证据不足或不属于受限补丁合同。"
    return {"finding_id": finding.get("finding_id"), "route": route, "reason": reason}
