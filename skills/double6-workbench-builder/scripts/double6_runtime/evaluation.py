"""候选静态扫描、浏览器收集编排与独立结果判定。"""

from __future__ import annotations

import os
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .composition import (
    OBJECT_PIPELINE_RUNTIME,
    compile_acceptance_program,
    execute_object_pipeline_program,
    scan_acceptance_program,
)
from .core import (
    ContractError,
    PACKAGE_ROOT,
    commit,
    digest_file,
    load_run,
    now,
    read_json,
    require_state,
    schema,
    transition,
    tree_rows,
)
from .domain_remnants import audit_candidate_html


NETWORK_CODE = re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(|navigator\.serviceWorker|https?://", re.I)
STORAGE_KEY = re.compile(r"double6:[a-z0-9-]+:v3")
FAKE_HISTORY = re.compile(r"(?:\b[1-9][0-9]?%|连续\s*[1-9][0-9]*\s*天|累计\s*[1-9][0-9]*)")
INTERNAL_UI_TERMS = {
    "starter", "unsupported", "manual_handoff", "action_checklist", "record_ledger",
    "stage_board", "metric_log", "review_journal", "reward_economy", "能力与交接",
    # runtime-contract：使用者看得见的文案不能是「内置内容 / 自有记录」。
    "内置内容", "自有记录",
}
INTERNAL_ID_PATTERNS = [
    re.compile(r"\bCAP-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:baby-growth-explorer|generic-primary-transition|primary-transition-\d+-to-\d+)\b"),
]
# snake_case 机器标记（如 synthetic_demo、manual_handoff）不得出现在用户可见文案或页面渲染的内置内容里。
SNAKE_CASE_TOKEN = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")
STARTER_VISIBLE_KEYS = ("title", "body", "result", "prompt", "explanation", "answer", "hint", "story", "mission")
LIFE_SCENE_MARKERS = ("life-finance", "life-food", "life-movement", "life-reading", "data-life-", "calories")


def _starter_snake_tokens(product: dict[str, Any]) -> list[str]:
    """内置内容由页面脚本渲染，静态 HTML 解析看不到，因此直接扫描产品里的 starter 文案。"""
    hits: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            hits.extend(SNAKE_CASE_TOKEN.findall(value))
        elif isinstance(value, list):
            for row in value:
                walk(row)
        elif isinstance(value, dict):
            for key in STARTER_VISIBLE_KEYS:
                if key in value:
                    walk(value[key])
            for key in ("options", "lines", "items", "prompts", "groups", "poems"):
                if key in value:
                    walk(value[key])
            if isinstance(value.get("reference"), dict):
                walk(value["reference"])

    for capability in product.get("capabilities", []):
        starter = capability.get("starter") if isinstance(capability, dict) else None
        if isinstance(starter, dict):
            walk(starter.get("summary", ""))
            walk(starter.get("starter_items", []))
    return hits


class CandidateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []
        self.hooks: set[str] = set()
        self.build_ids: set[str] = set()
        self.token_ids: set[str] = set()
        self.template_ids: set[str] = set()
        self.scene_template_ids: set[str] = set()
        self.visual_kernel_ids: set[str] = set()
        self.renderer_ids: set[str] = set()
        self.visual_contract_versions: set[str] = set()
        self.dashboard_signatures: set[str] = set()
        self.first_screen_slots: set[str] = set()
        self.dashboard_module_links: set[str] = set()
        self.scene_ids: set[str] = set()
        self.experience_signatures: set[str] = set()
        self.pack_ids: set[str] = set()
        self.recommendation_hashes: set[str] = set()
        self.surface_registry_versions: set[str] = set()
        self.starter_contract_versions: set[str] = set()
        self.composition_contract_versions: set[str] = set()
        self.composition_ids: set[str] = set()
        self.composition_hashes: set[str] = set()
        self.composition_statuses: set[str] = set()
        self.reliability_contract_versions: set[str] = set()
        self.reliability_envelope_versions: set[str] = set()
        self.reliability_registry_hashes: set[str] = set()
        self.reliability_envelope_hashes: set[str] = set()
        self.reliability_envelope_statuses: set[str] = set()
        self.reliability_guard_counts: list[int] = []
        self.reliability_blocked_counts: list[int] = []
        self.reliability_public_layers = 0
        self.reliability_receipts = 0
        self.today_workboards = 0
        self.deployment_guides = 0
        self.starter_surface_versions: list[str] = []
        self.starter_item_counts: list[int] = []
        self.module_surfaces: dict[str, str] = {}
        self.composition_surfaces: dict[str, dict[str, str]] = {}
        self.module_forms = 0
        self.module_save_buttons = 0
        self.work_objects: set[str] = set()
        self.representative_items = 0
        self.primary_actions = 0
        self.semantic_emoji_markers = 0
        self.page_icon_rels: set[str] = set()
        self.theme_colors: set[str] = set()
        self.visible_text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            self._ignored_depth += 1
        values = {key: value or "" for key, value in attrs}
        if tag == "link":
            rel = values.get("rel", "")
            href = values.get("href", "")
            if rel in {"icon", "shortcut icon"} and href.startswith(("data:image/png;base64,", "data:image/svg+xml;base64,")):
                self.page_icon_rels.add(rel)
            if rel == "apple-touch-icon" and href.startswith("data:image/png;base64,"):
                self.page_icon_rels.add(rel)
            if rel == "manifest" and href.startswith("data:application/manifest+json;base64,"):
                self.page_icon_rels.add(rel)
        if tag == "meta" and values.get("name") == "theme-color" and values.get("content"):
            self.theme_colors.add(values["content"])
        for resource_tag, attribute in {"img": "src", "audio": "src", "video": "src", "source": "src", "iframe": "src", "script": "src", "link": "href"}.items():
            if tag == resource_tag and values.get(attribute) and not values[attribute].startswith(("data:", "#")):
                self.errors.append(f"禁止外部资源：{tag}[{attribute}]")
        if values.get("data-double6-hook"):
            self.hooks.add(values["data-double6-hook"])
        if values.get("data-double6-build-id"):
            self.build_ids.add(values["data-double6-build-id"])
            self.token_ids.add(values.get("data-double6-token-id", ""))
            self.template_ids.add(values.get("data-double6-template-id", ""))
            self.scene_template_ids.add(values.get("data-double6-scene-template-id", ""))
            self.visual_kernel_ids.add(values.get("data-double6-visual-kernel-id", ""))
            self.renderer_ids.add(values.get("data-double6-renderer-id", ""))
            self.visual_contract_versions.add(values.get("data-double6-visual-contract-version", ""))
            self.scene_ids.add(values.get("data-double6-scene-id", ""))
            self.experience_signatures.add(values.get("data-double6-experience-signature", ""))
            self.pack_ids.add(values.get("data-double6-pack-id", ""))
            self.recommendation_hashes.add(values.get("data-double6-recommendation-sha256", ""))
            self.surface_registry_versions.add(values.get("data-double6-surface-registry-version", ""))
            self.starter_contract_versions.add(values.get("data-double6-starter-contract-version", ""))
            self.composition_contract_versions.add(values.get("data-double6-composition-contract-version", ""))
            self.composition_ids.add(values.get("data-double6-composition-id", ""))
            self.composition_hashes.add(values.get("data-double6-composition-sha256", ""))
            self.composition_statuses.add(values.get("data-double6-composition-status", ""))
            self.reliability_contract_versions.add(values.get("data-double6-reliability-contract-version", ""))
            self.reliability_envelope_versions.add(values.get("data-double6-reliability-envelope-version", ""))
            self.reliability_registry_hashes.add(values.get("data-double6-reliability-registry-sha256", ""))
            self.reliability_envelope_hashes.add(values.get("data-double6-reliability-envelope-sha256", ""))
            self.reliability_envelope_statuses.add(values.get("data-double6-reliability-envelope-status", ""))
            try:
                self.reliability_guard_counts.append(int(values.get("data-double6-reliability-guard-count", "0")))
                self.reliability_blocked_counts.append(int(values.get("data-double6-reliability-blocked-count", "0")))
            except ValueError:
                self.reliability_guard_counts.append(0)
                self.reliability_blocked_counts.append(-1)
        if values.get("data-reliability-public-layer") is not None:
            self.reliability_public_layers += 1
        if values.get("data-reliability-receipt") is not None:
            self.reliability_receipts += 1
        if values.get("data-today-workboard") is not None:
            self.today_workboards += 1
        if values.get("data-deployment-guide") is not None:
            self.deployment_guides += 1
        if values.get("data-starter-root") is not None:
            self.starter_surface_versions.append(values.get("data-starter-contract-version", ""))
            try:
                self.starter_item_counts.append(int(values.get("data-starter-item-count", "0")))
            except ValueError:
                self.starter_item_counts.append(0)
        if values.get("data-double6-module-id"):
            module_id = values["data-double6-module-id"]
            self.module_surfaces[module_id] = values.get("data-double6-surface-type", "")
            if values.get("data-composition-surface-template"):
                self.composition_surfaces[module_id] = {
                    "surface_template_id": values.get("data-composition-surface-template", ""),
                    "surface_signature": values.get("data-composition-surface-signature", ""),
                    "object_type_id": values.get("data-composition-object-type", ""),
                    "default_disclosure": values.get("data-composition-disclosure", ""),
                }
        if values.get("data-module-form") is not None:
            self.module_forms += 1
        if values.get("data-module-save") is not None:
            self.module_save_buttons += 1
        if values.get("data-double6-work-object"):
            self.work_objects.add(values["data-double6-work-object"])
        if values.get("data-double6-representative-item"):
            self.representative_items += 1
        if values.get("data-dashboard-signature"):
            self.dashboard_signatures.add(values["data-dashboard-signature"])
        if values.get("data-first-screen-slot"):
            self.first_screen_slots.add(values["data-first-screen-slot"])
        if values.get("data-dashboard-module-link"):
            self.dashboard_module_links.add(values["data-dashboard-module-link"])
        if values.get("data-double6-primary-action") == "true":
            self.primary_actions += 1
        if values.get("data-double6-emoji-role"):
            self.semantic_emoji_markers += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.visible_text.append(data.strip())


def static_scan(run_dir: Path) -> dict[str, Any]:
    lock = read_json(run_dir / "candidate-lock.json")
    candidate = Path(lock["candidate_root"])
    rows = tree_rows(candidate)
    errors: list[str] = []
    if [row["path"] for row in rows] != ["index.html"]:
        errors.append("候选目录必须恰好只有 index.html")
        return {"status": "fail", "errors": errors}
    path = candidate / "index.html"
    text = path.read_text(encoding="utf-8")
    parser = CandidateParser()
    parser.feed(text)
    errors.extend(parser.errors)
    if NETWORK_CODE.search(text):
        errors.append("候选包含网络调用或远端地址")
    if re.search(r"\b(?:TODO|FIXME)\b|占位功能|demo\s*only", text, re.I):
        errors.append("候选包含未完成标记")
    if 'data-feedback-collection="none"' not in text:
        errors.append("候选未明确关闭首发反馈采集")
    if re.search(r"data-(?:external-)?feedback-entry|mailto:|https?://[^\"']*(?:feedback|issue)", text, re.I):
        errors.append("候选不应提供反馈问题提交入口")
    if lock.get("renderer_id") == "child_playground_v2":
        selection = lock.get("learning_content_selection", {})
        expected_ids = set(selection.get("eligible_item_ids", []))
        embedded_ids = set(re.findall(r'"item_id":"([^"]+)"', text))
        if parser.build_ids != {lock["build_id"]}:
            errors.append("儿童候选未继承当前 build")
        if parser.renderer_ids != {"child_playground_v2"} or parser.visual_contract_versions != {"child_playground_v2"}:
            errors.append("儿童候选 renderer 或视觉合同漂移")
        child_slots = {
            slot for slot, marker in {
                "hero": ".playground-hero",
                "primary_surface": ".today-board",
                "progress": ".home-stats",
                "supporting_panel": ".world-more",
            }.items()
            if marker in text
        }
        if child_slots != {"hero", "primary_surface", "progress", "supporting_panel"}:
            errors.append("儿童候选首屏槽位不完整")
        if len(parser.dashboard_signatures) != 1:
            errors.append("儿童候选缺少唯一首页结构签名")
        if not expected_ids or not expected_ids <= embedded_ids:
            errors.append("儿童候选未完整内嵌当前选择的已审内容")
        if f'data-double6-selection-sha256="{selection.get("selection_sha256", "")}"' not in text:
            errors.append("儿童候选内容选择摘要与候选锁漂移")
        if f'data-double6-formal-item-count="{len(expected_ids)}"' not in text or 'data-double6-learning-content-version="1.7.2"' not in text:
            errors.append("儿童候选未锁定 v1.7.2 与当前选择的内容数量")
        # 学段适配器会裁剪房间；核对选中模块对应的真实入口，不强制恢复已关闭的房间。
        selected_modules = set(lock.get("module_ids", []))
        required_views = {"home"}
        for module_id, view in {"education-language": "语文", "education-math": "数学", "education-english": "英语", "education-reading": "阅读", "education-parent": "parent", "education-movement": "movement", "education-rewards": "collect"}.items():
            if module_id in selected_modules:
                required_views.add(view)
        if "education-errors" in selected_modules:
            required_views.add("repair")
        actual_views = set(re.findall(r'<button[^>]*class="nav-btn"[^>]*data-view="([^"]+)"', text))
        if not required_views <= actual_views:
            errors.append(f"儿童候选主导航缺少选中房间：{sorted(required_views - actual_views)}")
        if "child_learning_starter" in text or "starter-education" in text:
            errors.append("旧 starter 内容误混入儿童正式候选")
        if digest_file(path) != lock["candidate_sha256"]:
            errors.append("候选 SHA 已漂移")
        return {
            "status": "pass" if not errors else "fail", "errors": errors,
            "candidate_sha256": digest_file(path), "hooks": sorted(parser.hooks),
            "renderer_id": next(iter(parser.renderer_ids), None),
            "visual_contract_version": next(iter(parser.visual_contract_versions), None),
            "first_screen_slots": sorted(child_slots),
            "structure_fingerprint": hashlib.sha256(next(iter(parser.dashboard_signatures), "").encode("utf-8")).hexdigest(),
            "formal_item_count": len(expected_ids), "embedded_formal_item_count": len(expected_ids & embedded_ids),
            "selection_sha256": selection.get("selection_sha256"),
            "page_icon_rels": sorted(parser.page_icon_rels), "theme_color": next(iter(parser.theme_colors), None),
        }
    keys = set(STORAGE_KEY.findall(text))
    if keys != {lock["storage_key"]}:
        errors.append(f"存储命名空间不唯一：{sorted(keys)}")
    required_hooks = {"save", "export", "quick-export", "quick-import", "clear", "import", "undo-import", "data-feedback", "claims", "progress-label", "legacy-import"}
    if not required_hooks <= parser.hooks:
        errors.append(f"缺少核心挂钩：{sorted(required_hooks - parser.hooks)}")
    if parser.build_ids != {lock["build_id"]} or parser.token_ids != {read_json(run_dir / "design.json")["current"]["token_id"]}:
        errors.append("候选未继承当前 build 或 token")
    design = read_json(run_dir / "design.json")
    if parser.template_ids != {design["current"]["template_id"]} or parser.visual_kernel_ids != {"vivid_social_workbench_templates_v4"}:
        errors.append("候选未继承当前鲜艳社媒模板或公共视觉内核")
    expected_scene_template = design["current"].get("scene_template_id") or "general_workbench"
    if parser.scene_template_ids != {expected_scene_template}:
        errors.append("候选未继承当前场景默认模板")
    if (
        parser.renderer_ids != {lock.get("renderer_id")}
        or parser.visual_contract_versions != {lock.get("visual_contract_version")}
        or parser.visual_contract_versions != {"scene_dashboard_v1"}
    ):
        errors.append("候选 renderer 或视觉合同与候选锁漂移")
    required_slots = {"hero", "primary_surface", "progress", "supporting_panel"}
    if parser.first_screen_slots != required_slots:
        errors.append(f"首屏槽位不完整：{sorted(required_slots - parser.first_screen_slots)}")
    if len(parser.dashboard_signatures) != 1:
        errors.append("候选缺少唯一 dashboard 结构签名")
    required_color_tokens = {
        "--d6-canvas", "--d6-sidebar", "--d6-card", "--d6-ink", "--d6-muted", "--d6-line",
        "--d6-primary", "--d6-primary-strong", "--d6-accent", "--d6-category-1",
        "--d6-category-2", "--d6-category-3", "--d6-category-4",
    }
    if not required_color_tokens <= {row.split(":", 1)[0] for row in re.findall(r"--d6-[a-z0-9-]+\s*:[^;}}]+", text)}:
        errors.append("候选缺少鲜艳社媒模板颜色 token")
    if parser.semantic_emoji_markers < 5:
        errors.append("候选缺少稳定的 emoji 导航或能力语义")
    if parser.page_icon_rels != {"icon", "shortcut icon", "apple-touch-icon", "manifest"} or len(parser.theme_colors) != 1:
        errors.append("候选缺少内嵌页面图标、主屏幕图标、PWA manifest 或主题色")
    if parser.scene_ids != {lock["scene_id"]} or parser.experience_signatures != {lock["experience_signature"]}:
        errors.append("候选未继承当前场景或体验签名")
    product = read_json(run_dir / "product.json")
    run = read_json(run_dir / "run.json")
    binding = run.get("request_binding", {})
    if any(lock.get(key) != binding.get(key) for key in ["request_sha256", "request_event_id"]):
        errors.append("候选与当前请求绑定不一致")
    plan = product["recommendation_plan"]
    expected_modules = {
        row["recommendation_module_id"]: row["surface"]["type"]
        for row in product["capabilities"] if row["mode"] == "in_page"
    }
    if parser.pack_ids != {plan["pack_id"]} or parser.recommendation_hashes != {plan["recommendation_sha256"]} or parser.surface_registry_versions != {str(plan["surface_registry_version"])}:
        errors.append("候选未绑定当前内容包、推荐摘要或表面注册表")
    if (
        parser.starter_contract_versions != {plan["starter_contract_version"]}
        or len(parser.starter_surface_versions) != len(expected_modules)
        or set(parser.starter_surface_versions) != {plan["starter_contract_version"]}
        or len(parser.starter_item_counts) != len(expected_modules)
        or any(count < 1 for count in parser.starter_item_counts)
        or sorted(parser.starter_item_counts) != sorted(lock.get("starter_item_counts", {}).values())
    ):
        errors.append("核心模块缺少非空 starter 内容或 starter 合同与候选锁漂移")
    if parser.reliability_contract_versions != {lock.get("reliability_contract_version")} or parser.reliability_public_layers != 1 or parser.reliability_receipts != 1:
        errors.append("候选缺少入口、数据位置、外部来源与恢复能力的诚实交付公共层")
    reliability_binding = lock.get("reliability_envelope_binding", {})
    if (
        not isinstance(reliability_binding, dict)
        or parser.reliability_envelope_versions != {reliability_binding.get("contract_version")}
        or parser.reliability_registry_hashes != {reliability_binding.get("registry_sha256")}
        or parser.reliability_envelope_hashes != {reliability_binding.get("envelope_sha256")}
        or parser.reliability_envelope_statuses != {reliability_binding.get("status")}
        or parser.reliability_guard_counts != [reliability_binding.get("guard_count")]
        or parser.reliability_blocked_counts != [0]
        or reliability_binding.get("status_counts", {}).get("blocked") != 0
    ):
        errors.append("候选未绑定当前 selected-scope 可靠性信封或仍含阻断项")
    composition_binding = lock.get("composition_binding", {})
    composition_contract = plan.get("composition_contract")
    acceptance_scan = None
    if composition_binding.get("activation_status") == "compiled":
        pack = (composition_contract or {}).get("pack", {})
        expected_composition_surfaces = {
            row["module_id"]: {
                "surface_template_id": row["surface_template_id"],
                "surface_signature": row["surface_signature"],
                "object_type_id": row["object_type_id"],
                "default_disclosure": row["default_disclosure"],
            }
            for row in pack.get("modules", [])
        }
        if (
            parser.composition_contract_versions != {composition_binding.get("contract_version")}
            or parser.composition_ids != {composition_binding.get("composition_id")}
            or parser.composition_hashes != {composition_binding.get("composition_sha256")}
            or parser.composition_statuses != {"compiled"}
            or parser.composition_surfaces != expected_composition_surfaces
        ):
            errors.append("候选未完整绑定当前声明式 composition contract")
        acceptance_program = compile_acceptance_program(pack)
        acceptance_scan = scan_acceptance_program(acceptance_program, text)
        if acceptance_scan["status"] != "pass":
            errors.extend(acceptance_scan["errors"])
        if pack.get("runtime_binding", {}).get("runtime_id") == OBJECT_PIPELINE_RUNTIME:
            hop_scan = execute_object_pipeline_program(pack, text)
            if hop_scan["status"] != "pass":
                errors.extend(hop_scan["errors"])
            acceptance_scan = {**acceptance_scan, "object_pipeline": hop_scan}
    elif (
        parser.composition_contract_versions != {"none"}
        or parser.composition_ids != {"none"}
        or parser.composition_hashes != {"none"}
        or parser.composition_statuses != {"not_registered"}
        or parser.composition_surfaces
    ):
        errors.append("未登记场景不应隐式激活 composition runtime")
    if parser.today_workboards != 1:
        errors.append("候选缺少唯一的今天要处理入口")
    if parser.deployment_guides != 1:
        errors.append("候选缺少受控部署与主屏幕使用指引")
    if parser.module_surfaces != expected_modules or parser.module_forms != len(expected_modules) or parser.module_save_buttons != len(expected_modules):
        errors.append("台内能力缺少一一对应的真实交互表面")
    if not 4 <= len(expected_modules) <= 15:
        errors.append("候选核心模块必须为 4–15 个")
    if not parser.work_objects:
        errors.append("候选未呈现能力绑定的真实工作对象")
    if set(expected_modules) - parser.dashboard_module_links:
        errors.append(f"dashboard 缺少核心模块入口：{sorted(set(expected_modules) - parser.dashboard_module_links)}")
    dashboard_prefix = text.split("data-double6-module-id=", 1)[0]
    if "data-module-form" in dashboard_prefix:
        errors.append("dashboard 禁止连续展示 CRUD 表单")
    if parser.primary_actions != 1:
        errors.append("候选必须且只能有一个主动作")
    if product["design_brief"].get("first_use_state") == "empty" and FAKE_HISTORY.search(" ".join(parser.visible_text)):
        errors.append("首次使用页面含虚构历史指标")
    visible_copy = " ".join(parser.visible_text).lower()
    if any(term.lower() in visible_copy for term in INTERNAL_UI_TERMS):
        errors.append("候选向用户泄漏内部合同术语")
    visible_copy_raw = " ".join(parser.visible_text)
    if any(pattern.search(visible_copy_raw) for pattern in INTERNAL_ID_PATTERNS):
        errors.append("候选可见文案泄漏学段或能力内部标识符")
    snake_hits = sorted(set(SNAKE_CASE_TOKEN.findall(visible_copy_raw)) | set(_starter_snake_tokens(product)))
    if snake_hits:
        errors.append(f"候选可见文案或内置内容泄漏机器标记：{snake_hits[:8]}")
    nav_labels = re.findall(r"<span class='nav-label'>(.*?)</span>", text)
    if nav_labels:
        counts = {label: nav_labels.count(label) for label in nav_labels}
        if len(set(counts.values())) > 1:
            errors.append(f"导航标签重名：{sorted(label for label, count in counts.items() if count > min(counts.values()))}")
    leaked_module_ids = sorted(module_id for module_id in expected_modules if module_id.lower() in visible_copy)
    if leaked_module_ids:
        errors.append(f"候选可见文案泄漏模块内部 ID：{leaked_module_ids}")
    errors.extend(audit_candidate_html(visible_copy_raw, str(lock.get("scene_id") or "")))
    if not any(module_id.startswith("life-") for module_id in expected_modules):
        allowed = {"calories"} if "fitness-food" in expected_modules else set()
        dead_markers = [marker for marker in LIFE_SCENE_MARKERS if marker not in allowed and marker in text]
        if dead_markers:
            errors.append(f"非个人生活场景候选携带跨场景死代码：{dead_markers}")
    if digest_file(path) != lock["candidate_sha256"]:
        errors.append("候选 SHA 已漂移")
    return {
        "status": "pass" if not errors else "fail", "errors": errors,
        "candidate_sha256": digest_file(path), "hooks": sorted(parser.hooks),
        "representative_item_count": parser.representative_items,
        "dashboard_module_link_count": len(parser.dashboard_module_links),
        "dashboard_module_link_ids": sorted(parser.dashboard_module_links),
        "composition_id": next(iter(parser.composition_ids), None),
        "composition_sha256": next(iter(parser.composition_hashes), None),
        "composition_status": next(iter(parser.composition_statuses), None),
        "composition_surface_count": len(parser.composition_surfaces),
        "acceptance_program": acceptance_scan,
        "renderer_id": next(iter(parser.renderer_ids), None),
        "visual_contract_version": next(iter(parser.visual_contract_versions), None),
        "first_screen_slots": sorted(parser.first_screen_slots),
        "structure_fingerprint": hashlib.sha256(next(iter(parser.dashboard_signatures), "").encode("utf-8")).hexdigest(),
        "template_id": next(iter(parser.template_ids), None),
        "scene_template_id": next(iter(parser.scene_template_ids), None),
        "visual_kernel_id": next(iter(parser.visual_kernel_ids), None),
        "page_icon_rels": sorted(parser.page_icon_rels),
        "theme_color": next(iter(parser.theme_colors), None),
        "semantic_emoji_markers": parser.semantic_emoji_markers,
        "module_surfaces": parser.module_surfaces,
        "surface_registry_version": next(iter(parser.surface_registry_versions), None),
        "starter_contract_version": next(iter(parser.starter_contract_versions), None),
        "starter_surface_count": len(parser.starter_surface_versions),
        "starter_item_counts": parser.starter_item_counts,
        "reliability_contract_version": next(iter(parser.reliability_contract_versions), None),
        "reliability_envelope_version": next(iter(parser.reliability_envelope_versions), None),
        "reliability_registry_sha256": next(iter(parser.reliability_registry_hashes), None),
        "reliability_envelope_sha256": next(iter(parser.reliability_envelope_hashes), None),
        "reliability_envelope_status": next(iter(parser.reliability_envelope_statuses), None),
        "reliability_guard_count": parser.reliability_guard_counts[0] if parser.reliability_guard_counts else 0,
        "reliability_blocked_count": parser.reliability_blocked_counts[0] if parser.reliability_blocked_counts else -1,
        "reliability_public_layer_count": parser.reliability_public_layers,
        "today_workboard_count": parser.today_workboards,
        "deployment_guide_count": parser.deployment_guides,
    }


def _playwright_python() -> Path | None:
    candidates: list[Path] = []
    if os.environ.get("DOUBLE6_BROWSER_PYTHON"):
        candidates.append(Path(os.environ["DOUBLE6_BROWSER_PYTHON"]))
    candidates.extend([
        Path(sys.executable),
        PACKAGE_ROOT.parents[2] / ".venv" / "bin" / "python",
        PACKAGE_ROOT.parents[2] / ".venv" / "Scripts" / "python.exe",
        PACKAGE_ROOT.parents[3] / ".venv" / "bin" / "python",
        PACKAGE_ROOT.parents[3] / ".venv" / "Scripts" / "python.exe",
    ])
    workbuddy = Path.home() / ".workbuddy" / "binaries" / "python" / "versions"
    if workbuddy.is_dir():
        candidates.extend(sorted(workbuddy.glob("*/bin/python*"), reverse=True))
        candidates.extend(sorted(workbuddy.glob("*/Scripts/python*.exe"), reverse=True))
    for name in ["python3", "python"]:
        path_python = shutil.which(name)
        if path_python:
            candidates.append(Path(path_python))
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        probe = subprocess.run([str(candidate), "-B", "-c", "import playwright"], capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            return candidate
    return None


PLAYWRIGHT_BROWSER_GLOBS = (
    # Linux：完整 Chromium（旧版 chrome-linux、Chrome for Testing 的 chrome-linux64）与 headless shell
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-linux64/chrome",
    "chromium_headless_shell-*/chrome-linux/headless_shell",
    "chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
    # macOS：Intel 与 Apple Silicon、旧版 Chromium.app 与新版 Chrome for Testing
    "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chromium_headless_shell-*/chrome-mac*/headless_shell",
    "chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell",
    # Windows：旧版 chrome-win 与新版 chrome-win64
    "chromium-*/chrome-win/chrome.exe",
    "chromium-*/chrome-win64/chrome.exe",
    "chromium_headless_shell-*/chrome-win*/headless_shell.exe",
    "chromium_headless_shell-*/chrome-headless-shell-win*/chrome-headless-shell.exe",
)


def _playwright_cache_roots() -> list[Path]:
    roots: list[Path] = []
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom and custom != "0":
        roots.append(Path(custom))
    home = Path.home()
    roots.extend([home / ".cache" / "ms-playwright", home / "Library" / "Caches" / "ms-playwright"])
    if os.environ.get("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    return roots


def _playwright_cache_browsers() -> list[Path]:
    """按 Playwright 官方缓存目录发现浏览器；完整 Chromium 优先于 headless shell，新版本优先。"""
    found: list[Path] = []
    for root in _playwright_cache_roots():
        if not root.is_dir():
            continue
        for pattern in PLAYWRIGHT_BROWSER_GLOBS:
            found.extend(sorted(root.glob(pattern), reverse=True))
    return found


def _chromium() -> Path | None:
    candidates = []
    if os.environ.get("DOUBLE6_CHROMIUM_EXECUTABLE"):
        candidates.append(Path(os.environ["DOUBLE6_CHROMIUM_EXECUTABLE"]))
    candidates.extend([
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ])
    for variable in ["LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"]:
        base = os.environ.get(variable)
        if not base:
            continue
        root = Path(base)
        candidates.extend([
            root / "Google" / "Chrome" / "Application" / "chrome.exe",
            root / "Chromium" / "Application" / "chrome.exe",
        ])
    candidates.extend(_playwright_cache_browsers())
    for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "chrome.exe"]:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def browser_environment() -> dict[str, Any]:
    """返回无副作用的浏览器验收环境预检及可执行的修复指引。"""
    browser_python = _playwright_python()
    chromium = _chromium()
    blockers = []
    if browser_python is None:
        blockers.append("playwright_python_missing")
    if chromium is None:
        blockers.append("chromium_missing")
    instructions = []
    if browser_python is None:
        instructions.append("在准备给 DOUBLE6_BROWSER_PYTHON 的 Python 环境执行：python -m pip install playwright")
    if chromium is None:
        instructions.append("安装 Google Chrome 或 Chromium，或设置 DOUBLE6_CHROMIUM_EXECUTABLE 为 chrome.exe 的绝对路径")
    return {
        "status": "ready" if not blockers else "blocked",
        "platform": sys.platform,
        "browser_python": str(browser_python) if browser_python else None,
        "chromium": str(chromium) if chromium else None,
        "blockers": blockers,
        "instructions": instructions,
        "environment_variables": ["DOUBLE6_BROWSER_PYTHON", "DOUBLE6_CHROMIUM_EXECUTABLE"],
    }


def _judge(browser: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if browser.get("visible_machine_markers"):
        failures.append("visible_internal_markers_failed")
    if browser.get("status") == "blocked":
        return [f"browser_blocked:{browser.get('error')}"]
    if lock.get("renderer_id") == "child_playground_v2":
        if (
            browser.get("build_id") != lock["build_id"]
            or browser.get("candidate_sha256") != lock["candidate_sha256"]
            or browser.get("build_id_matches") is not True
        ):
            failures.append("candidate_binding_failed")
        if browser.get("child_playground_v2_pass") is not True or browser.get("reward_selection_pass") is not True:
            failures.append("child_playground_flow_failed")
        if not all(browser.get("navigation", {}).get(module_id) is True for module_id in lock.get("module_ids", [])):
            failures.append("child_playground_navigation_failed")
        responsive = browser.get("responsive", [])
        if (
            {row.get("name") for row in responsive} != {"mobile", "tablet", "desktop"}
            or any(
                row.get("no_overflow") is not True
                or row.get("persistent_left_tabs_pass") is not True
                or row.get("navigation_labels_visible") is not True
                for row in responsive
            )
        ):
            failures.append("child_playground_responsive_failed")
        accessibility = browser.get("accessibility", {})
        if accessibility.get("focus_visible") is not True or any(
            row.get("width", 0) < 44
            or row.get("height", 0) < 44
            or not str(row.get("accessible_name", "")).strip()
            for row in accessibility.get("touch_targets", [])
        ):
            failures.append("accessibility_failed")
        if browser.get("console_errors") or browser.get("page_errors") or browser.get("unauthorized_requests"):
            failures.append("runtime_error_or_network_detected")
        if set(browser.get("runtime_storage_keys", [])) != {lock["storage_key"]} or set(browser.get("final_storage_keys", [])) != {lock["storage_key"]}:
            failures.append("storage_namespace_failed")
        alternate = browser.get("alternate_storage", {})
        extra_idb = [name for name in (alternate.get("indexed_db_names") or []) if name and name != "double6-workspace-v1"]
        if alternate.get("session_storage_keys") or alternate.get("cookie_count") or extra_idb:
            failures.append("alternate_storage_detected")
        return failures
    if browser.get("build_id") != lock["build_id"] or browser.get("candidate_sha256") != lock["candidate_sha256"] or browser.get("build_id_matches") is not True:
        failures.append("candidate_binding_failed")
    if browser.get("primary_action_count") != 1:
        failures.append("primary_action_failed")
    experience = browser.get("experience", {})
    reliability_binding = lock.get("reliability_envelope_binding", {})
    composition_binding = lock.get("composition_binding", {})
    if (
        experience.get("scene_id") != lock.get("scene_id")
        or experience.get("experience_signature") != lock.get("experience_signature")
        or experience.get("template_id") != lock.get("template_id")
        or experience.get("visual_kernel_id") != "vivid_social_workbench_templates_v4"
        or experience.get("scene_template_id") != (lock.get("scene_template_id") or "general_workbench")
        or experience.get("renderer_id") != lock.get("renderer_id")
        or experience.get("visual_contract_version") != lock.get("visual_contract_version")
        or experience.get("reliability_contract_version") != lock.get("reliability_contract_version")
        or experience.get("reliability_envelope_version") != reliability_binding.get("contract_version")
        or experience.get("reliability_registry_sha256") != reliability_binding.get("registry_sha256")
        or experience.get("reliability_envelope_sha256") != reliability_binding.get("envelope_sha256")
        or experience.get("reliability_envelope_status") != reliability_binding.get("status")
        or experience.get("reliability_guard_count") != reliability_binding.get("guard_count")
        or experience.get("reliability_blocked_count") != 0
        or experience.get("composition_status") != composition_binding.get("activation_status")
        or (
            composition_binding.get("activation_status") == "compiled"
            and (
                experience.get("composition_id") != composition_binding.get("composition_id")
                or experience.get("composition_sha256") != composition_binding.get("composition_sha256")
            )
        )
        or set(experience.get("dashboard_module_link_ids", [])) != set(lock.get("module_ids", []))
        or set(experience.get("first_screen_slots", [])) != {"hero", "primary_surface", "progress", "supporting_panel"}
        or experience.get("semantic_emoji_marker_count", 0) < 5
        or experience.get("progress_feedback_pass") is not True
        or experience.get("primary_action_in_first_viewport") is not True
        or experience.get("main_work_object_count", 0) < 1
    ):
        failures.append("experience_contract_failed")
    if not all(browser.get("core_flow", {}).get(key) is True for key in ["saved_visible", "persistence_pass"]):
        failures.append("core_flow_failed")
    starter = browser.get("starter", {})
    if (
        starter.get("contract_version") != lock.get("starter_contract_version")
        or starter.get("surface_count") != len(lock.get("module_ids", []))
        or starter.get("all_nonempty") is not True
        or starter.get("interaction_pass") is not True
        or starter.get("persistence_pass") is not True
        or starter.get("reliability_public_layer_pass") is not True
        or (starter.get("question_present") and not all(starter.get(key) is True for key in ["wrong_feedback_pass", "correct_feedback_pass", "explanation_pass"]))
    ):
        failures.append("starter_contract_failed")
    today = browser.get("today", {})
    if today.get("present") is not True or today.get("quick_backup_controls") is not True:
        failures.append("today_and_backup_contract_failed")
    if today.get("overdue_rollover_pass") is False or today.get("complete_pass") is False:
        failures.append("today_action_flow_failed")
    if not all(browser.get("export_import", {}).get(key) is True for key in ["cleared", "import_pass", "import_undo_pass", "legacy_import_pass", "legacy_unknown_preserved", "v2_unknown_preserved", "malicious_import_sanitized"]):
        failures.append("export_import_failed")
    surface_contracts = browser.get("surfaces", {}).get("contracts", [])
    if (
        browser.get("surfaces", {}).get("module_count") != len(lock.get("module_ids", []))
        or {row.get("module_id") for row in surface_contracts} != set(lock.get("module_ids", []))
        or any(row.get("registry_version") != str(lock.get("surface_registry_version")) for row in surface_contracts)
        or browser.get("surfaces", {}).get("module_action_pass") is not True
        or any(not all(result.values()) for result in browser.get("surfaces", {}).get("operation_results", {}).values())
    ):
        failures.append("surface_contract_failed")
    if browser.get("storage_failure_pass") is not True:
        failures.append("storage_failure_failed")
    if browser.get("console_errors") or browser.get("page_errors") or browser.get("unauthorized_requests"):
        failures.append("runtime_error_or_network_detected")
    if set(browser.get("runtime_storage_keys", [])) != {lock["storage_key"]} or set(browser.get("final_storage_keys", [])) != {lock["storage_key"]}:
        failures.append("storage_namespace_failed")
    alternate = browser.get("alternate_storage", {})
    extra_idb = [name for name in (alternate.get("indexed_db_names") or []) if name and name != "double6-workspace-v1"]
    if alternate.get("session_storage_keys") or alternate.get("cookie_count") or extra_idb:
        failures.append("alternate_storage_detected")
    responsive = browser.get("responsive", [])
    navigation_failed = any(
        (row.get("name") == "mobile" and (row.get("mobile_bottom_navigation_visible") is not True or row.get("identity_navigation_visible") is not False))
        or (row.get("name") == "desktop" and (row.get("identity_navigation_visible") is not True or row.get("mobile_bottom_navigation_visible") is not False))
        for row in responsive
    )
    navigation_reachability_failed = any(
        row.get("navigation_labels_visible") is not True
        or row.get("navigation_label_contrast_pass") is not True
        or row.get("navigation_within_viewport") is not True
        or row.get("navigation_scroll_reachable") is not True
        for row in responsive
    )
    if not responsive or navigation_failed or navigation_reachability_failed or any(row.get("no_overflow") is not True or row.get("primary_action_count") != 1 for row in responsive):
        failures.append("responsive_failed")
    if any(row.get("name") == "mobile" and row.get("personal_life_mobile_unobscured") is False for row in responsive):
        failures.append("personal_life_mobile_navigation_failed")
    accessibility = browser.get("accessibility", {})
    if accessibility.get("focus_visible") is not True or any(row.get("width", 0) < 44 or row.get("height", 0) < 44 or not str(row.get("accessible_name", "")).strip() for row in accessibility.get("touch_targets", [])):
        failures.append("accessibility_failed")
    return failures


def evaluate(run_dir: Path, *, preflight: bool = False, skip_browser: bool = False) -> dict[str, Any]:
    run = load_run(run_dir)
    if preflight:
        environment = browser_environment()
        return {"status": "environment_ready" if environment["status"] == "ready" else "evaluation_blocked", "state": run["state"], "environment": environment, "next": _next_for_preflight(run)}
    require_state(run, "candidate_built", "evaluation_failed")
    retrying_evaluation = run.get("state") == "evaluation_failed"
    if (not retrying_evaluation and run.get("status") != "visual_approved") or (
        retrying_evaluation and run.get("status") not in {"evaluation_blocked", "candidate_failed"}
    ):
        raise ContractError("候选必须经当前用户视觉确认后才能验收")
    lock = read_json(run_dir / "candidate-lock.json")
    design = read_json(run_dir / "design.json")
    review = design.get("visual_review", {})
    if review.get("status") != "approved" or review.get("candidate_sha256") != lock.get("candidate_sha256"):
        raise ContractError("候选必须由当前用户视觉确认后才能验收")
    scan = static_scan(run_dir)
    blockers: list[str] = []
    failures = list(scan["errors"])
    browser_result: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = []
    if not failures and skip_browser:
        return {"status": "static_precheck_passed", "state": run["state"], "failures": [], "next": "evaluate", "delivery": "not_delivered_browser_evaluation_required"}
    if not failures:
        environment = browser_environment()
        blockers.extend(environment["blockers"])
        browser_python = Path(environment["browser_python"]) if environment["browser_python"] else None
        chromium = Path(environment["chromium"]) if environment["chromium"] else None
        if not blockers:
            with tempfile.TemporaryDirectory() as temp:
                output_dir = Path(temp)
                collector = PACKAGE_ROOT / "scripts" / "double6_browser_collector.py"
                completed = subprocess.run([
                    str(browser_python), "-B", str(collector), "--run", str(run_dir),
                    "--output-dir", str(output_dir), "--chromium", str(chromium),
                ], capture_output=True, text=True, check=False)
                result_path = output_dir / "browser-result.json"
                if not result_path.is_file():
                    blockers.append("browser_collector_no_result")
                else:
                    browser_result = read_json(result_path)
                    collected = browser_result.get("build_id") == lock["build_id"] and browser_result.get("candidate_sha256") == lock["candidate_sha256"]
                    if completed.returncode and not collected:
                        blockers.append(f"browser_collector_failed:{browser_result.get('error', completed.stderr.strip())}")
                    else:
                        judged = _judge(browser_result, lock)
                        failures.extend(judged)
                        if browser_result.get("status") == "fail" and not judged:
                            failures.append("browser_collector_quality_failed")
                        evidence_dir = run_dir / "evidence"
                        evidence_dir.mkdir(parents=True, exist_ok=True)
                        for row in browser_result.get("screenshots", []):
                            source = output_dir / str(row["path"])
                            target = evidence_dir / str(row["path"])
                            shutil.copy2(source, target)
                            artifacts.append({"kind": "screenshot", "viewport": row["viewport"], "path": f"evidence/{target.name}", "sha256": digest_file(target)})
    status = "evaluation_blocked" if blockers else "candidate_failed" if failures else "pass"
    browser_surfaces = (browser_result or {}).get("surfaces", {})
    operation_by_type = browser_surfaces.get("operation_results", {})
    surface_checks = {}
    for contract in browser_surfaces.get("contracts", []):
        result = operation_by_type.get(contract.get("surface_type"), {})
        surface_checks[contract.get("module_id")] = {
            "surface_type": contract.get("surface_type"),
            "crud": "pass" if result.get("update") and result.get("delete") else "fail",
            "status_change": "pass" if result.get("status_change") else "fail",
            "persistence": "pass" if (browser_result or {}).get("core_flow", {}).get("persistence_pass") else "fail",
            "recovery": "pass" if (browser_result or {}).get("export_import", {}).get("import_pass") else "fail",
        }
    browser_starter = (browser_result or {}).get("starter", {})
    starter_checks = {
        module_id: {
            "content": "pass" if browser_starter.get("all_nonempty") else "fail",
            "interaction": "pass" if browser_starter.get("interaction_pass") else "fail",
            "persistence": "pass" if browser_starter.get("persistence_pass") else "fail",
        }
        for module_id in lock.get("module_ids", [])
    }
    evidence = {
        "schema_version": schema("evidence"), "status": status, "build_id": lock["build_id"],
        "surface_registry_version": lock.get("surface_registry_version"), "surface_checks": surface_checks,
        "starter_contract_version": lock.get("starter_contract_version"), "starter_checks": starter_checks,
        "reliability_envelope_binding": lock.get("reliability_envelope_binding"),
        "composition_binding": lock.get("composition_binding"),
        "renderer_id": lock.get("renderer_id"), "visual_contract_version": lock.get("visual_contract_version"),
        "first_screen_slots": {slot: "pass" if slot in set(scan.get("first_screen_slots", [])) else "fail" for slot in ["hero", "primary_surface", "progress", "supporting_panel"]},
        "structure_fingerprint": scan.get("structure_fingerprint"),
        "viewport_evidence": {name: "pass" if any(row.get("viewport") == name for row in artifacts) else "missing" for name in ["mobile", "tablet", "desktop"]},
        "function_entry_checks": {module_id: "pass" if (browser_result or {}).get("navigation", {}).get(module_id) else "fail" for module_id in lock.get("module_ids", [])},
        "candidate_lock_sha256": digest_file(run_dir / "candidate-lock.json"),
        "checks": {"static": scan, "browser": browser_result},
        "blockers": blockers, "failures": failures, "artifacts": artifacts, "updated_at": now(),
    }
    delivery = read_json(run_dir / "delivery.json")
    if status == "pass":
        delivery["local"] = {"state": "local_delivered", "build_id": lock["build_id"], "candidate_sha256": lock["candidate_sha256"], "delivered_at": now()}
        run = transition(run, "local_delivered", "delivered", "local_evaluation_passed", {"build_id": lock["build_id"]})
    else:
        delivery["local"] = {"state": status, "build_id": lock["build_id"], "updated_at": now()}
        run = transition(run, "evaluation_failed", status, "local_evaluation_failed", {"blockers": blockers, "failures": failures})
    delivery["updated_at"] = now()
    commit(run_dir, {"evidence.json": evidence, "delivery.json": delivery, "run.json": run})
    return {"status": status, "state": run["state"], "blockers": blockers, "failures": failures, "next": None if status == "pass" else "evaluate" if status == "evaluation_blocked" else "build"}


def _next_for_preflight(run: dict[str, Any]) -> str | None:
    if run.get("state") == "evaluation_failed" and run.get("status") == "evaluation_blocked":
        return "evaluate"
    return run.get("state")
