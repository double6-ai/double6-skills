"""领域候选、语义路由与独立风险扫描。"""

from __future__ import annotations

from typing import Any

from .core import ContractError, REFERENCES, digest_bytes, now, read_json
from .recommendations import recommendation_snapshot


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
CONTENT_SOURCE_DOMAINS = {"education-learning", "teaching-classroom", "exam-preparation"}
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
    "content-operations": "选题、素材、制作、排期与人工发布交接。",
    "ecommerce-operations": "商品、订单、库存、售后和运营记录。",
    "finance-tax-contract": "本地收支、凭证、预算、税务与合同台账。",
    "hr-employment": "招聘、员工事务、制度与人事流程记录。",
    "research-knowledge": "研究问题、资料、证据、引用与研究复盘。",
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
    return {
        "primary_domain": primary,
        "auxiliary_domains": auxiliary,
        "profile_id": profile_id,
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
        "selection_source": selection_source,
        "semantic_evidence_spans": semantic["evidence_spans"],
        "classifier": semantic["classifier"],
        "keyword_candidates": candidates,
        "risk_pack_ids": _risk_ids(text, selected),
        "routed_at": now(),
    }


def critical_decisions(text: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    risks = set(route.get("risk_pack_ids", []))
    decisions: list[dict[str, Any]] = []
    learning_recommendations = {}
    learning_snapshot = {}
    if route.get("primary_domain") == "education-learning":
        learning_snapshot = recommendation_snapshot(text, route)
        learning_recommendations = learning_snapshot.get("decision_recommendations", {})
    # “做一个工作台”只说明了容器，没有说明最优先要解决的真实结果。
    # 对儿童学习这种多模块场景，先问一个能改变首页主动作和练习侧重的问题，
    # 不再把“没有指定教材”误当成“无需了解用户目标”。
    if route.get("primary_domain") == "education-learning":
        recommended = learning_recommendations["learning-priority"]
        decisions.append({
            "decision_id": "learning-priority",
            "question": f"这套学习台，最想先帮孩子解决哪件事？推荐先按“{recommended['value']}”安排，因为{recommended['reason']}。你可以直接回复“按推荐”，或告诉我她最近最卡在哪里。",
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": ["learning-goal"], "evidence_refs": [],
            "recommended_value": recommended["value"], "recommendation_reason": recommended["reason"],
        })
    if (
        risks & {"child-data", "customer-data", "financial-data", "health-data", "sensitive-data", "account-data"}
        and any(marker.lower() in text.lower() for marker in REAL_DATA_MARKERS)
    ):
        life_copy = any(trigger in text for trigger in LIFE_DASHBOARD_TRIGGERS)
        decisions.append({
            "decision_id": "privacy-boundary",
            "question": "这次会录入真实的个人、学生、客户、财务或健康数据吗？" + ("推荐先用合成示例；若要记录真实流水、饮食、体重或训练，请明确授权并确认仅在当前受控设备本地保存。" if life_copy else "推荐继续使用合成或脱敏数据：不需要孩子真实信息也能完成当前学习台，风险更低。若要录入真实数据，请明确授权并确认仅在受控本机保存。"),
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": sorted(risks & {"child-data", "customer-data", "financial-data", "health-data", "sensitive-data", "account-data"}),
            "evidence_refs": [], "recommended_value": "synthetic_or_redacted",
            "recommendation_reason": "默认不需要真实敏感数据即可完成当前任务。",
        })
    if (
        set([route.get("primary_domain"), *route.get("auxiliary_domains", [])]) & CONTENT_SOURCE_DOMAINS
        and any(marker.lower() in text.lower() for marker in NAMED_CONTENT_MARKERS)
    ):
        decisions.append({
            "decision_id": "content-source-boundary",
            "question": "学习内容使用什么来源？推荐先采用自编通用内容，不声称对齐教材；这样可以立即开始。只有要按人教版教材、真题或考纲生成时，才需要提供或确认来源、版本/年份或地区、范围与版权边界。",
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": ["content-source"], "evidence_refs": [], "recommended_value": "generic_non_claimed",
            "recommendation_reason": "没有可核验材料时，通用练习是唯一诚实且可立即执行的默认路径。",
        })
    if "multi-user" in risks:
        decisions.append({
            "decision_id": "participant-boundary",
            "question": "哪些人会使用它？推荐每个人在各自设备本地使用，必要时用导出文件人工交接；当前单文件没有多人实时同步。",
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": ["multi-user"], "evidence_refs": [], "recommended_value": "separate_local_devices_manual_export",
            "recommendation_reason": "符合当前离线单文件的真实保存边界。",
        })
    if "external-side-effect" in risks and any(marker.lower() in text.lower() for marker in AUTOMATIC_EXTERNAL_MARKERS):
        decisions.append({
            "decision_id": "external-action-boundary",
            "question": "发布、发送、下单、支付或预约是否都只做人工交接，不由工作台自动执行？推荐只做人工交接，避免工作台代替你执行外部动作。",
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": ["external-side-effect"], "evidence_refs": [], "recommended_value": "manual_handoff",
            "recommendation_reason": "当前产品不应自动产生外部副作用。",
        })
    # 如果用户已提出真实数据或指定教材，优先保留相应的安全/来源确认，
    # 不让模块选择挤掉这两类边界问题。
    if route.get("primary_domain") == "education-learning" and len(decisions) < 3:
        recommended = learning_recommendations["learning-modules"]
        recommended_names = {
            row["module_id"]: row["name"]
            for row in learning_snapshot.get("core_modules", []) + learning_snapshot.get("optional_modules", [])
        }
        labels = "、".join(recommended_names[module_id] for module_id in recommended["value"])
        decisions.append({
            "decision_id": "learning-modules",
            "question": f"这次要保留哪些学习内容？推荐先用：{labels}。因为{recommended['reason']}。你可以直接回复“按推荐”，或删减、替换其中的内容。",
            "impact": "high", "status": "missing", "value": None,
            "risk_tags": ["learning-scope"], "evidence_refs": [],
            "recommended_value": list(recommended["value"]), "recommendation_reason": recommended["reason"],
        })
    return decisions[:3]


def safe_defaults(text: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    """对未显式要求真实数据/指定教材的任务应用安全默认，不浪费澄清轮次。"""
    domains = set([route.get("primary_domain"), *route.get("auxiliary_domains", [])])
    risks = set(route.get("risk_pack_ids", []))
    defaults: list[dict[str, Any]] = []
    if risks & {"child-data", "customer-data", "financial-data", "health-data", "sensitive-data", "account-data"}:
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
