"""领域候选、语义路由与独立风险扫描。"""

from __future__ import annotations

from typing import Any

from .core import ContractError, REFERENCES, digest_bytes, now, read_json
from .recommendations import clarification_catalog, recommendation_snapshot


RISK_RULES = {
    "child-data": ["孩子", "儿童", "学生", "未成年", "幼小"],
    "multi-user": ["家里", "家庭", "共享", "共同", "夫妻", "成员", "多人"],
    "customer-data": ["客户", "会员", "病人", "患者"],
    "financial-data": ["财务", "账务", "报税", "发票", "收入", "支出"],
    "health-data": ["健康", "医疗", "疾病", "用药", "孕期", "症状", "健身"],
    "account-data": ["账号", "登录", "密码", "令牌", "API key"],
    "external-side-effect": ["发布", "发送", "下单", "支付", "预约", "退款", "通知", "自动同步"],
}
PRIMARY_ANCHORS = {
    "travel-planning": ["旅行", "旅游", "行程"],
    "exam-preparation": ["考公", "备考", "国考", "省考", "事业编"],
    "household-collaboration": ["家庭共享", "家里", "夫妻", "家务"],
    "health-pregnancy": ["医疗", "孕期", "用药", "症状"],
    "finance-tax-contract": ["财务", "报税", "税务", "账务"],
}
BOUNDARY_DECISION_IDS = frozenset({
    "privacy-boundary", "content-source-boundary", "participant-boundary", "external-action-boundary",
})
CONTENT_SOURCE_DOMAINS = {"education-learning", "teaching-classroom", "exam-preparation"}
SENSITIVE_RISKS = {"child-data", "customer-data", "financial-data", "health-data", "sensitive-data", "account-data"}
SELF_USE_HEALTH_DOMAINS = {"fitness-nutrition"}
# 出现这些词说明数据涉及他人，自用健康例外不适用，仍走原有授权与合成默认。
OTHER_PERSON_MARKERS = (
    "孩子", "儿童", "学生", "宝宝", "客户", "会员", "学员", "病人", "患者", "员工", "家人", "家里", "老婆", "老公",
    "妻子", "丈夫", "父母", "爸爸", "妈妈", "老人", "朋友", "同事", "别人", "他人", "全家", "我们",
)


def is_self_use_health(text: str, route: dict[str, Any]) -> bool:
    """自己记自己的减脂/训练：数据属于本人且只存本机，不需要另行授权，也不推荐合成数据。"""
    domains = {route.get("primary_domain"), *route.get("auxiliary_domains", [])}
    risks = set(route.get("risk_pack_ids", [])) & SENSITIVE_RISKS
    if route.get("primary_domain") not in SELF_USE_HEALTH_DOMAINS or not domains <= SELF_USE_HEALTH_DOMAINS:
        return False
    if not risks <= {"health-data"}:
        return False
    return not any(marker in str(text or "") for marker in OTHER_PERSON_MARKERS)
REAL_DATA_MARKERS = {
    "真实数据", "真实学生", "学生名单", "客户名单", "导入客户", "员工资料", "候选人简历",
    "我的账单", "银行流水", "发票数据", "工资数据", "薪酬数据", "产检报告", "检查报告",
    "病历", "健康记录", "真实流水", "真实账单", "真实饮食", "真实训练", "体重", "账号密码", "cookie", "token",
}
LIFE_DASHBOARD_TRIGGERS = ("个人生活工作台", "日常生活工作台", "生活驾驶舱", "我的生活工作台")
NAMED_CONTENT_MARKERS = {
    "人教版", "苏教版", "北师大版", "沪教版", "教材", "真题", "考纲", "考试大纲",
    "官方题库", "校本", "课程讲义", "指定版本",
}
AUTOMATIC_EXTERNAL_MARKERS = {
    "自动发布", "自动发送", "自动下单", "自动支付", "自动预约", "自动退款", "自动通知",
    "定时发布", "定时发送",
}
ROUTE_DESCRIPTIONS = {
    "personal-execution": "个人待办、日程、习惯、记录与复盘。",
    "education-learning": "儿童或学生的自主学习、练习、错题与家长轻回顾。",
    "teaching-classroom": "教师备课、班务、学情和课堂材料整理。",
    "exam-preparation": "备考计划、练习、错题和资料复盘。",
    "sales-trade": "销售线索、客户跟进、商机与交付记录。",
    "content-operations": "自媒体与多平台社媒：素材、选题、制作、排期、数据复盘与人工发布交接。",
    "ecommerce-operations": "商品、订单、库存、售后和运营记录。",
    "finance-tax-contract": "本地收支、凭证、预算、税务与合同台账。",
    "hr-employment": "招聘、员工事务、制度与人事流程记录。",
    "research-knowledge": "阅读清单、读书/论文笔记、研究问题、证据引用与研究复盘。",
    "fitness-nutrition": "训练、饮食、恢复与个人指标记录。",
    "health-pregnancy": "孕期健康事项、检查安排与问题记录，不作诊断。",
    "travel-planning": "旅行行程、材料、预算与出发前准备。",
    "household-collaboration": "家庭家务、采购、分工与人工交接。",
    "professional-services": "咨询、审计、法律等专业项目的交付管理。",
    "local-service-store": "本地门店排班、到店服务、会员与经营记录。",
}


def route_options() -> list[dict[str, Any]]:
    """向宿主公开全部场景及其子场景，不自行替用户选择。"""
    packs = read_json(REFERENCES / "domain-content-packs.json").get("packs", [])
    options: list[dict[str, Any]] = []
    for pack in packs:
        domain_id = str(pack.get("domain_id") or "")
        if not domain_id:
            continue
        profiles = [
            {
                "profile_id": profile["profile_id"],
                "label": profile.get("label", profile["profile_id"]),
                "description": profile.get("description", "该领域下的细分工作台。"),
            }
            for profile in pack.get("profiles", [])
            if isinstance(profile, dict) and str(profile.get("profile_id") or "").strip()
        ]
        options.append({
            "domain_id": domain_id,
            "label": str(pack.get("label") or domain_id),
            "description": ROUTE_DESCRIPTIONS.get(domain_id, "在当前设备本地完成一类真实工作。"),
            "profiles": profiles,
        })
    return options


def registry() -> list[dict[str, Any]]:
    value = read_json(REFERENCES / "risk-packs.json")
    packs = value.get("packs")
    if value.get("schema_version") != 1 or not isinstance(packs, list) or len(packs) != 16:
        raise ContractError("risk-packs 必须包含 16 个领域包")
    return packs


def _keyword_candidates(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    rows = []
    for pack in registry():
        hits = [word for word in pack.get("keywords", []) if str(word).lower() in lowered]
        anchor_hits = [word for word in PRIMARY_ANCHORS.get(pack["domain_id"], []) if word in text]
        score = len(hits) * 2 + len(anchor_hits) * 8
        if score:
            rows.append({"domain_id": pack["domain_id"], "score": score, "hits": hits, "anchor_hits": anchor_hits})
    return sorted(rows, key=lambda row: (-row["score"], row["domain_id"]))


def _validate_semantic_route(text: str, supplied: dict[str, Any], domain_ids: set[str]) -> dict[str, Any]:
    primary = supplied.get("primary_domain")
    auxiliary = supplied.get("auxiliary_domains", [])
    spans = supplied.get("evidence_spans", [])
    if primary not in domain_ids:
        raise ContractError("semantic route 的 primary_domain 无效")
    if not isinstance(auxiliary, list) or len(auxiliary) > 2 or primary in auxiliary or not set(auxiliary) <= domain_ids:
        raise ContractError("semantic route 最多包含两个不重复的辅助领域")
    if not isinstance(spans, list) or not spans or any(not str(span).strip() or str(span) not in text for span in spans):
        raise ContractError("semantic route 必须引用用户原话中的证据片段")
    profile_id = supplied.get("profile_id")
    if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
        raise ContractError("profile_id 必须是非空字符串或省略")
    options = {row["domain_id"]: row for row in route_options()}
    allowed_profiles = {row["profile_id"] for row in options[primary].get("profiles", [])}
    if profile_id and profile_id not in allowed_profiles:
        raise ContractError("profile_id 不属于宿主选择的主场景")
    scene_profile_id = supplied.get("scene_profile_id")
    if scene_profile_id is not None and (not isinstance(scene_profile_id, str) or not scene_profile_id.strip()):
        raise ContractError("scene_profile_id 必须是非空字符串或省略")
    if scene_profile_id:
        scene_rows = read_json(REFERENCES / "scene-profiles.json").get("scene_profiles", [])
        scene = next(
            (row for row in scene_rows if row.get("scene_profile_id") == scene_profile_id),
            None,
        )
        if not isinstance(scene, dict) or scene.get("domain_id") != primary:
            raise ContractError("scene_profile_id 不属于宿主选择的主领域")
        migrations = read_json(REFERENCES / "scene-profiles.json").get("audit", {}).get("existing_profile_migration", [])
        mapped = [row["legacy_profile_id"] for row in migrations
                  if row.get("scene_profile_id") == scene_profile_id and row.get("legacy_profile_id") in allowed_profiles]
        if profile_id and mapped and profile_id not in mapped:
            raise ContractError("profile_id 与 scene_profile_id 指向不同子场景")
        if not profile_id and len(mapped) == 1:
            # 显式场景 ID 也必须带出学段和专用运行时使用的 profile；不按关键词推断。
            profile_id = mapped[0]
    return {
        "primary_domain": primary,
        "auxiliary_domains": auxiliary,
        "profile_id": profile_id,
        "scene_profile_id": scene_profile_id,
        "evidence_spans": spans,
        "classifier": supplied.get("classifier", "host_agent_selection"),
    }


def _risk_ids(text: str, selected_domains: list[str]) -> list[str]:
    risks = {risk for risk, words in RISK_RULES.items() if any(word.lower() in text.lower() for word in words)}
    by_id = {row["domain_id"]: row for row in registry()}
    for domain_id in selected_domains:
        risks.update(by_id[domain_id].get("risk_triggers", []))
    if any(trigger in text for trigger in LIFE_DASHBOARD_TRIGGERS) and any(marker.lower() in text.lower() for marker in REAL_DATA_MARKERS):
        risks.update({"financial-data", "health-data", "sensitive-data"})
    return sorted(risks)


def route_request(text: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    packs = registry()
    domain_ids = {row["domain_id"] for row in packs}
    candidates = _keyword_candidates(text)
    life_dashboard_requested = any(trigger in text for trigger in LIFE_DASHBOARD_TRIGGERS)
    if supplied:
        semantic = _validate_semantic_route(text, supplied, domain_ids)
        selection_source = "host_agent"
    else:
        # 仅保留给旧测试和只读诊断的兼容提示；start_run 不会用它创建生产任务。
        primary = "personal-execution" if life_dashboard_requested else candidates[0]["domain_id"] if candidates else "personal-execution"
        semantic = {
            "primary_domain": primary,
            "auxiliary_domains": [row["domain_id"] for row in candidates if row["domain_id"] != primary][:2],
            "profile_id": None,
            "scene_profile_id": None,
            "evidence_spans": [next(trigger for trigger in LIFE_DASHBOARD_TRIGGERS if trigger in text)] if life_dashboard_requested else candidates[0]["anchor_hits"][:1] or candidates[0]["hits"][:1] if candidates else [text],
            "classifier": "compatibility_hint_only",
        }
        selection_source = "compatibility_hint_only"
    selected = [semantic["primary_domain"], *semantic["auxiliary_domains"]]
    return {
        "schema_version": 1,
        "request_sha256": digest_bytes(text.encode("utf-8")),
        "primary_domain": semantic["primary_domain"],
        "auxiliary_domains": semantic["auxiliary_domains"],
        "profile_id": semantic.get("profile_id"),
        "scene_profile_id": semantic.get("scene_profile_id"),
        "selection_source": selection_source,
        "semantic_evidence_spans": semantic["evidence_spans"],
        "classifier": semantic["classifier"],
        "keyword_candidates": candidates,
        "risk_pack_ids": _risk_ids(text, selected),
        "routed_at": now(),
    }


def _decision(
    *,
    decision_id: str,
    question: str,
    reason: str,
    recommended_value: Any,
    recommendation_reason: str,
    route: dict[str, Any],
    risk_tags: list[str],
    allowed_adjustments: list[str],
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "question_kind": "authorization" if decision_id in BOUNDARY_DECISION_IDS else "preference",
        "question": question,
        "question_reason": reason,
        "allowed_adjustments": allowed_adjustments,
        "scene_scope": {
            "primary_domain": route.get("primary_domain"),
            "profile_id": route.get("profile_id"),
            "scene_profile_id": route.get("scene_profile_id"),
        },
        "impact": "high",
        "status": "missing",
        "value": None,
        "risk_tags": risk_tags,
        "evidence_refs": [],
        "recommended_value": recommended_value,
        "recommendation_reason": recommendation_reason,
    }


def critical_decisions(text: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    risks = set(route.get("risk_pack_ids", []))
    decisions: list[dict[str, Any]] = []
    snapshot = recommendation_snapshot(text, route)
    policy = snapshot.get("clarification_policy", {})
    learning_recommendations = snapshot.get("decision_recommendations", {})
    # “学习重点”只属于目标仍含糊且没有明确子场景的教育请求，不再是教育固定问法。
    if (
        route.get("primary_domain") == "education-learning"
        and policy.get("ask_learning_priority_when") == "goal_ambiguous_without_profile"
        and not snapshot.get("profile_id")
        and not any(marker in text for marker in ["重点", "薄弱", "最卡", "优先", "只要", "主要练"])
    ):
        recommended = learning_recommendations["learning-priority"]
        decisions.append(_decision(
            decision_id="learning-priority",
            question=f"这套学习台，最想先帮孩子解决哪件事？推荐先按“{recommended['value']}”安排，因为{recommended['reason']}。你可以直接回复“按推荐”，或告诉我最近最卡在哪里。",
            reason="当前只确定了教育场景，学习结果仍可能显著改变首页主任务和内容侧重。",
            recommended_value=recommended["value"],
            recommendation_reason=recommended["reason"],
            route=route,
            risk_tags=["learning-goal"],
            allowed_adjustments=["当前最卡的内容", "优先目标", "明确不需要的学习方向"],
        ))
    if (
        risks & SENSITIVE_RISKS
        and any(marker.lower() in text.lower() for marker in REAL_DATA_MARKERS)
        and not is_self_use_health(text, route)
    ):
        life_copy = any(trigger in text for trigger in LIFE_DASHBOARD_TRIGGERS)
        decisions.append(_decision(
            decision_id="privacy-boundary",
            question="这次会录入真实的个人、学生、客户、财务或健康数据吗？" + ("推荐先用合成示例；若要记录真实流水、饮食、体重或训练，请明确授权并确认仅在当前受控设备本地保存。" if life_copy else "推荐继续使用合成或脱敏数据；若要录入真实数据，请明确授权并确认仅在受控本机保存。"),
            reason="真实敏感数据会改变数据保护合同，不能由系统代替用户授权。",
            recommended_value="synthetic_or_redacted",
            recommendation_reason="默认不需要真实敏感数据即可完成当前任务。",
            route=route,
            risk_tags=sorted(risks & {"child-data", "customer-data", "financial-data", "health-data", "sensitive-data", "account-data"}),
            allowed_adjustments=["继续使用合成或脱敏数据", "明确授权真实数据仅在受控本机保存"],
        ))
    if (
        set([route.get("primary_domain"), *route.get("auxiliary_domains", [])]) & CONTENT_SOURCE_DOMAINS
        and any(marker.lower() in text.lower() for marker in NAMED_CONTENT_MARKERS)
    ):
        decisions.append(_decision(
            decision_id="content-source-boundary",
            question="学习内容使用什么来源？推荐先采用自编通用内容，不声称对齐教材；只有要按指定教材、真题或考纲生成时，才需要确认来源、版本、范围与版权边界。",
            reason="指定内容来源会改变题目真值依据与版权边界。",
            recommended_value="generic_non_claimed",
            recommendation_reason="没有可核验材料时，通用练习是唯一诚实且可立即执行的默认路径。",
            route=route,
            risk_tags=["content-source"],
            allowed_adjustments=["自编通用内容", "用户提供或官方可核验来源"],
        ))
    if "multi-user" in risks:
        decisions.append(_decision(
            decision_id="participant-boundary",
            question="哪些人会使用它？推荐每个人在各自设备本地使用，必要时用导出文件人工交接；当前单文件没有多人实时同步。",
            reason="参与者数量会改变同步、权限和数据交接边界。",
            recommended_value="separate_local_devices_manual_export",
            recommendation_reason="符合当前离线单文件的真实保存边界。",
            route=route,
            risk_tags=["multi-user"],
            allowed_adjustments=["单人本机使用", "多人各自本机并人工导出交接"],
        ))
    if "external-side-effect" in risks and any(marker.lower() in text.lower() for marker in AUTOMATIC_EXTERNAL_MARKERS):
        decisions.append(_decision(
            decision_id="external-action-boundary",
            question="发布、发送、下单、支付或预约是否都只做人工交接，不由工作台自动执行？推荐只做人工交接。",
            reason="外部副作用必须由用户明确授权，当前单文件运行时不能代替用户执行。",
            recommended_value="manual_handoff",
            recommendation_reason="当前产品不应自动产生外部副作用。",
            route=route,
            risk_tags=["external-side-effect"],
            allowed_adjustments=["仅人工交接", "标记为暂不支持"],
        ))
    # 教育内容范围在构建期确认；明确学段不再触发无关的“学习重点”问题。
    if route.get("primary_domain") == "education-learning" and policy.get("module_capability_selection") == "clarifying_adaptive":
        recommended = learning_recommendations["learning-modules"]
        recommended_names = {
            row["module_id"]: row["name"]
            for row in snapshot.get("core_modules", []) + snapshot.get("optional_modules", [])
        }
        labels = "、".join(recommended_names[module_id] for module_id in recommended["value"])
        decisions.append(_decision(
            decision_id="learning-modules",
            question=f"这次要保留哪些学习模块？推荐先用：{labels}。因为{recommended['reason']}。你可以直接回复“按推荐”，或删减、替换。",
            reason="模块范围决定最终工作台出现哪些学习世界。",
            recommended_value=list(recommended["value"]),
            recommendation_reason=recommended["reason"],
            route=route,
            risk_tags=["learning-scope"],
            allowed_adjustments=["采用全部推荐", "删除模块", "加入当前内容包中的可选模块"],
        ))
        capability_names = {row["capability_id"]: row["title"] for row in snapshot.get("capability_options", [])}
        recommended_capability_ids = list(snapshot.get("recommended_capability_ids", []))
        capability_labels = "、".join(capability_names[row] for row in recommended_capability_ids)
        decisions.append(_decision(
            decision_id="learning-capabilities",
            question=f"这些模块里建议启用的能力项是：{capability_labels}。可以回复“按推荐”，或告诉我要删掉哪项；每个保留模块至少需要一项能力。",
            reason="能力项决定模块内部真正支持哪些动作，不能只确认模块名称。",
            recommended_value=recommended_capability_ids,
            recommendation_reason="推荐能力项全部来自已选模块的现有能力合同，不新增能力。",
            route=route,
            risk_tags=["learning-capability-scope"],
            allowed_adjustments=["采用全部推荐", "删除能力项", "恢复当前模块已有能力项"],
        ))
    question_limit = int(clarification_catalog()["question_limit_per_scene"])
    return decisions[:question_limit]


def safe_defaults(text: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    """对未显式要求真实数据/指定教材的任务应用安全默认，不浪费澄清轮次。"""
    domains = set([route.get("primary_domain"), *route.get("auxiliary_domains", [])])
    risks = set(route.get("risk_pack_ids", []))
    defaults: list[dict[str, Any]] = []
    if is_self_use_health(text, route):
        defaults.append({
            "decision_id": "privacy-boundary", "value": "self_owned_local_only",
            "reason": "本人自用的健康记录：数据属于用户自己且只存当前设备，无需另行授权，也不改用合成数据",
        })
    elif risks & SENSITIVE_RISKS:
        defaults.append({
            "decision_id": "privacy-boundary", "value": "synthetic_or_redacted",
            "reason": "用户未明确要求录入真实敏感数据，默认使用合成或脱敏数据",
        })
    if domains & CONTENT_SOURCE_DOMAINS:
        defaults.append({
            "decision_id": "content-source-boundary", "value": "generic_non_claimed",
            "reason": "用户未指定教材、真题或考纲，默认提供自编通用内容且不声称版本对齐",
        })
    if "education-learning" in domains:
        stage = recommendation_snapshot(text, route).get("learning_stage", {})
        defaults.extend([
            {"decision_id": "learning-stage", "value": stage.get("stage_id", "generic-primary-transition"), "reason": f"宿主已选择{stage.get('label', '通用小学衔接')}；未指定教材时仍只使用自编通用内容，不声称版本对齐"},
            {"decision_id": "daily-session", "value": "about_20_minutes", "reason": "默认每天约 20 分钟，先做一项主练习再做巩固或运动"},
            {"decision_id": "review-policy", "value": "keep_feedback_and_continue_next_time", "reason": "默认保留正误、解析和未完成指针，下一次从可继续内容开始"},
            {"decision_id": "parent-rhythm", "value": "weekly_light_review", "reason": "默认家长每周轻量回顾一次，不打断孩子当次练习"},
        ])
    if "external-side-effect" in risks:
        defaults.append({
            "decision_id": "external-action-boundary", "value": "manual_handoff",
            "reason": "用户未明确要求自动执行外部动作，默认只在工作台记录并人工交接",
        })
    return defaults


def style_hint(route: dict[str, Any]) -> str:
    by_id = {row["domain_id"]: row for row in registry()}
    return str(by_id[route["primary_domain"]].get("style_token") or "general-focus")
