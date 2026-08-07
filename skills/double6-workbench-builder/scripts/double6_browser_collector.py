#!/usr/bin/env python3
"""内部浏览器事实收集器；不作最终通过判定。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

# 必须在关闭 bytecode 后再导入浏览器依赖。
from playwright.sync_api import sync_playwright  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visible(locator: Any) -> bool:
    return locator.count() > 0 and locator.first.is_visible()


def collect_smoke(run_dir: Path, chromium: Path, scenario: str) -> dict[str, Any]:
    """只验证每次发布必须保留的一个真实浏览器闭环。"""
    lock = read_json(run_dir / "candidate-lock.json")
    candidate = Path(lock["candidate_root"]) / lock["entrypoint"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(chromium))
        context = browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(candidate.as_uri(), wait_until="load")
        result: dict[str, Any] = {"scenario": scenario}
        if scenario == "child_learning":
            question = page.locator(".starter-question").first
            module_id = question.evaluate("el=>el.closest('[data-double6-module-id]').dataset.double6ModuleId")
            page.evaluate("id=>{location.hash='#module-'+id}", module_id)
            options = question.locator("[data-starter-option]")
            if options.count() < 2:
                result["question_present"] = False
            else:
                options.nth(1).click()
                question.locator("[data-starter-action='submit-question']").click()
                result["wrong_feedback_pass"] = "再想一想" in question.inner_text()
                options.nth(0).click()
                question.locator("[data-starter-action='submit-question']").click()
                result["correct_feedback_pass"] = "回答正确" in question.inner_text()
                result["question_present"] = True
                rewards_module = page.locator("[data-double6-module-id='education-rewards']")
                if rewards_module.count():
                    page.evaluate("location.hash='#module-education-rewards'")
                    page.wait_for_timeout(30)
                    balance_text = rewards_module.locator("[data-reward-balance]").inner_text()
                    result["stars_earned_pass"] = balance_text.strip().split(" ")[0].isdigit() and int(balance_text.strip().split(" ")[0]) >= 1
                    result["reward_shop_count"] = rewards_module.locator("[data-reward-redeem]").count()
                    result["reward_badge_count"] = rewards_module.locator("[data-reward-badge]").count()
                else:
                    result["stars_earned_pass"] = False
                    result["reward_shop_count"] = 0
                    result["reward_badge_count"] = 0
            reference_modules = {}
            speak_total = 0
            poem_total = 0
            for reference_module_id in ["education-language", "education-english", "education-reading", "education-math"]:
                page.evaluate("id=>{location.hash='#module-'+id}", reference_module_id)
                page.wait_for_timeout(30)
                reference_root = page.locator(f"[data-double6-module-id='{reference_module_id}']")
                reference_modules[reference_module_id] = reference_root.locator(".ref-card").count()
                speak_total += reference_root.locator("[data-ref-speak]").count()
                poem_total += reference_root.locator(".ref-poem").count()
            result["reference_module_cards"] = reference_modules
            result["reference_card_count"] = sum(reference_modules.values())
            result["ref_speak_count"] = speak_total
            result["ref_poem_count"] = poem_total
            page.evaluate(
                "()=>{window.__d6SpeakCalls=0;if('speechSynthesis' in window){window.speechSynthesis.speak=()=>{window.__d6SpeakCalls++}}}"
            )
            speak_chip = page.locator("[data-double6-module-id='education-math'] [data-ref-speak]").first
            if speak_chip.count():
                speak_chip.click()
                page.wait_for_timeout(20)
            result["ref_speak_pass"] = page.evaluate("()=>window.__d6SpeakCalls>0")
            result.update(page.evaluate("""() => {
  const link = document.querySelector('link[rel=manifest]');
  const apple = document.querySelector('link[rel=apple-touch-icon]');
  const base = {pwa_manifest_pass: false, pwa_icon_count: 0, pwa_apple_touch_pass: false, pwa_apple_meta_pass: false};
  if (apple && String(apple.getAttribute('href') || '').startsWith('data:image/png;base64,')) base.pwa_apple_touch_pass = true;
  const capable = document.querySelector('meta[name=apple-mobile-web-app-capable]');
  const titleMeta = document.querySelector('meta[name=apple-mobile-web-app-title]');
  if (capable && capable.getAttribute('content') === 'yes' && titleMeta && (titleMeta.getAttribute('content') || '').trim()) base.pwa_apple_meta_pass = true;
  if (!link) return base;
  const raw = link.getAttribute('href') || '';
  if (!raw.startsWith('data:application/manifest+json;base64,')) return base;
  try {
    const manifest = JSON.parse(atob(raw.split(',')[1]));
    const icons = Array.isArray(manifest.icons) ? manifest.icons : [];
    base.pwa_icon_count = icons.length;
    base.pwa_manifest_pass = Boolean(
      manifest.name && manifest.short_name && manifest.display === 'standalone'
      && manifest.start_url && manifest.theme_color && manifest.background_color
      && icons.length >= 3
      && icons.every(icon => String(icon.src).startsWith('data:image/png;base64,') && icon.sizes && icon.type === 'image/png')
      && icons.some(icon => icon.purpose === 'maskable')
    );
  } catch (error) {}
  return base;
}"""))
            module_ids = page.locator("[data-double6-module-id]").evaluate_all(
                "rows=>rows.map(el=>el.dataset.double6ModuleId)"
            )
            visible_copy = []
            for visible_module_id in module_ids:
                page.evaluate("id=>{location.hash='#module-'+id}", visible_module_id)
                page.wait_for_timeout(10)
                visible_copy.append(page.locator(f"[data-double6-module-id='{visible_module_id}']").inner_text())
            forbidden = [
                "starter", "action_checklist", "record_ledger", "stage_board",
                "metric_log", "review_journal", "reward_economy", "manual_handoff", "unsupported",
                "primary-transition", "baby-growth-explorer", "education-", "cap-0",
            ]
            combined_copy = "\n".join(visible_copy).lower()
            result["visible_internal_terms"] = [term for term in forbidden if term in combined_copy]
            result["navigation_item_count"] = page.locator("[data-double6-role='mobile-bottom-navigation'] .nav-item").count()
            result["navigation_labels_visible"] = page.locator(
                "[data-double6-role='mobile-bottom-navigation'] .nav-label"
            ).evaluate_all(
                "rows=>rows.length>0&&rows.every(el=>{const style=getComputedStyle(el),box=el.getBoundingClientRect();return style.display!=='none'&&style.visibility!=='hidden'&&box.width>0&&box.height>0&&el.textContent.trim()})"
            )
            result["module_count"] = len(module_ids)
            result["learning_feature_count"] = page.locator("[data-learning-feature]").count()
            result["user_weekly_item_count"] = page.locator("[data-starter-item-id^='user-']").count()
            result["weekly_reset_pass"] = True
            if result["user_weekly_item_count"]:
                weekly_card = page.locator("[data-starter-item-id^='user-']").first
                weekly_module_id = weekly_card.evaluate(
                    "el=>el.closest('[data-double6-module-id]').dataset.double6ModuleId"
                )
                weekly_item_id = weekly_card.get_attribute("data-starter-item-id")
                page.evaluate("id=>{location.hash='#module-'+id}", weekly_module_id)
                page.wait_for_timeout(10)
                weekly_card.locator("[data-starter-action='toggle']").click()
                weekly_cycle_key = page.evaluate(
                    "([moduleId,itemId])=>{const key=Object.keys(localStorage)[0],value=JSON.parse(localStorage.getItem(key));return value.modules[moduleId].starter.itemStates[itemId]?.cycleKey||''}",
                    [weekly_module_id, weekly_item_id],
                )
                page.evaluate(
                    "([moduleId,itemId])=>{const key=Object.keys(localStorage)[0],value=JSON.parse(localStorage.getItem(key));value.modules[moduleId].starter.itemStates[itemId].cycleKey='2000-01-03';localStorage.setItem(key,JSON.stringify(value))}",
                    [weekly_module_id, weekly_item_id],
                )
                page.reload(wait_until="load")
                page.evaluate("id=>{location.hash='#module-'+id}", weekly_module_id)
                page.wait_for_timeout(10)
                weekly_card = page.locator(f"[data-starter-item-id='{weekly_item_id}']")
                result["weekly_reset_pass"] = bool(
                    weekly_cycle_key
                    and weekly_card.locator("[data-starter-result]").count() == 0
                    and "完成这一项" in weekly_card.locator("[data-starter-action='toggle']").inner_text()
                )
        elif scenario == "finance":
            page.evaluate("location.hash='#data-tools'")
            page.wait_for_timeout(20)
            csv_ok = False
            if page.locator("[data-double6-hook='export-csv']").count() == 1:
                with page.expect_download() as csv_download:
                    page.locator("[data-double6-hook='export-csv']").click()
                csv_ok = Path(csv_download.value.suggested_filename).suffix == ".csv"
            with page.expect_download() as export_download:
                page.locator("[data-double6-hook='export']").click()
            export_path = run_dir / "smoke-import.json"
            export_download.value.save_as(str(export_path))
            page.locator("[data-double6-hook='import']").set_input_files(str(export_path))
            result["finance_csv_export_pass"] = csv_ok
            result["import_pass"] = page.locator("[data-double6-module-id]").count() > 0
            export_path.unlink(missing_ok=True)
        elif scenario == "personal_life_mobile":
            result.update(page.evaluate("""() => {const root=document.querySelector('[data-double6-build-id]');const style=getComputedStyle(root);const nav=document.querySelector('[data-double6-role=mobile-bottom-navigation]');const dashboard=document.querySelector('[data-dashboard-signature]');const navBox=nav&&nav.getBoundingClientRect();const dashboardBox=dashboard&&dashboard.getBoundingClientRect();const navItems=nav?nav.querySelectorAll('.nav-item').length:0;return {personal_life_nav_items:navItems,personal_life_mobile_unobscured:Boolean(navBox&&dashboardBox&&parseFloat(style.paddingLeft)>=64&&dashboardBox.left>=navBox.right+4&&navItems===9)}}"""))
        else:
            raise ValueError(f"未知 smoke 场景：{scenario}")
        context.close()
        browser.close()
    passed = (
        scenario == "child_learning"
        and all(result.get(key) is True for key in ["question_present", "wrong_feedback_pass", "correct_feedback_pass", "navigation_labels_visible", "stars_earned_pass"])
        and not result.get("visible_internal_terms")
        and result.get("navigation_item_count") == result.get("module_count", 0) + 2
        and result.get("learning_feature_count") == result.get("module_count")
        and result.get("weekly_reset_pass") is True
        and 10 <= result.get("reward_shop_count", 0) <= 40
        and result.get("reward_badge_count", 0) >= 15
        and result.get("reference_card_count", 0) >= 4
        and all(count >= 1 for count in result.get("reference_module_cards", {}).values())
        and len(result.get("reference_module_cards", {})) == 4
        and result.get("ref_speak_count", 0) >= 100
        and result.get("ref_poem_count", 0) >= 5
        and result.get("ref_speak_pass") is True
        and result.get("pwa_manifest_pass") is True
        and result.get("pwa_apple_touch_pass") is True
        and result.get("pwa_apple_meta_pass") is True
        or scenario == "finance" and all(result.get(key) is True for key in ["finance_csv_export_pass", "import_pass"])
        or scenario == "personal_life_mobile" and result.get("personal_life_mobile_unobscured") is True and result.get("personal_life_nav_items") == 9
    )
    return {"schema_version": 1, "status": "pass" if passed else "fail", **result}


def collect(run_dir: Path, output_dir: Path, chromium: Path) -> dict[str, Any]:
    product = read_json(run_dir / "product.json")
    lock = read_json(run_dir / "candidate-lock.json")
    candidate = Path(lock["candidate_root"]) / lock["entrypoint"]
    output_dir.mkdir(parents=True, exist_ok=True)
    entry_url = candidate.as_uri()
    console_errors: list[str] = []
    page_errors: list[str] = []
    requests: list[str] = []
    screenshots: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(chromium))
        context = browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        context.add_init_script("""
          window.__double6StorageKeys=[];
          for (const name of ['getItem','setItem','removeItem']) {
            const original=Storage.prototype[name];
            Storage.prototype[name]=function(key,...args){
              if(this===localStorage) window.__double6StorageKeys.push(String(key));
              return original.call(this,key,...args);
            };
          }
        """)
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url) if request.url != entry_url and not request.url.startswith(("data:", "blob:")) else None)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(entry_url, wait_until="load")
        build_id_matches = page.locator(f"[data-double6-build-id='{lock['build_id']}']").count() == 1
        primary_count = page.locator("[data-double6-primary-action='true']").count()
        today_present = page.locator("[data-today-workboard]").count() == 1
        quick_backup_controls = (
            page.locator("[data-double6-hook='quick-export']").count() == 1
            and page.locator("[data-double6-hook='quick-import']").count() == 1
        )
        root = page.locator("[data-double6-build-id]")
        root_experience = root.evaluate("el=>({scene_id:el.dataset.double6SceneId,experience_signature:el.dataset.double6ExperienceSignature,template_id:el.dataset.double6TemplateId,scene_template_id:el.dataset.double6SceneTemplateId,visual_kernel_id:el.dataset.double6VisualKernelId,renderer_id:el.dataset.double6RendererId,visual_contract_version:el.dataset.double6VisualContractVersion,reliability_contract_version:el.dataset.double6ReliabilityContractVersion})")
        representative_item_count = page.locator("[data-double6-representative-item]").count()
        dashboard_module_link_count = page.locator("[data-dashboard-module-link]").count()
        dashboard_module_link_ids = sorted(page.locator("[data-dashboard-module-link]").evaluate_all("rows=>[...new Set(rows.map(el=>el.dataset.dashboardModuleLink))]"))
        first_screen_slots = sorted(page.locator("[data-first-screen-slot]").evaluate_all("rows=>[...new Set(rows.map(el=>el.dataset.firstScreenSlot))]"))
        structure_signature = page.locator("[data-dashboard-signature]").get_attribute("data-dashboard-signature")
        semantic_emoji_marker_count = page.locator("[data-double6-emoji-role]").count()
        main_work_object_count = page.locator("[data-double6-work-object]").count()
        surface_contracts = page.locator("[data-double6-module-id]").evaluate_all(
            "rows=>rows.map(el=>({module_id:el.dataset.double6ModuleId,surface_type:el.dataset.double6SurfaceType,registry_version:el.dataset.double6SurfaceRegistryVersion}))"
        )
        starter_contract_version = root.get_attribute("data-double6-starter-contract-version")
        starter_surfaces = page.locator("[data-starter-root]")
        starter_surface_count = starter_surfaces.count()
        starter_item_counts = starter_surfaces.evaluate_all("rows=>rows.map(el=>Number(el.dataset.starterItemCount||0))")
        starter_all_nonempty = starter_surface_count == len(surface_contracts) and all(count > 0 for count in starter_item_counts)
        navigation_results: dict[str, bool] = {}
        for contract in surface_contracts:
            module_id = contract["module_id"]
            page.evaluate("id=>{location.hash='#module-'+id}", module_id)
            page.wait_for_timeout(20)
            navigation_results[module_id] = page.locator(f"[data-view-id='module-{module_id}']").is_visible()
        page.evaluate("location.hash='#dashboard'")
        page.wait_for_timeout(20)
        primary_box = page.locator("[data-double6-primary-action='true']").bounding_box()
        primary_action_in_first_viewport = bool(primary_box and primary_box["y"] < 844)
        first_capability = next(row for row in product["capabilities"] if row["mode"] == "in_page")
        test_value = str(first_capability["oracle"]["input_value"])

        def fill_surface(module_root: Any, value: str, *, date_value: str | None = None) -> None:
            module_form = module_root.locator("[data-module-form]")
            module_fields = module_form.locator("[data-double6-field]")
            wrote_primary_value = False
            for field_index in range(module_fields.count()):
                field = module_fields.nth(field_index)
                field_type = field.get_attribute("type") or field.evaluate("el=>el.tagName.toLowerCase()")
                if field_type == "number":
                    field.fill("1")
                elif field_type == "date":
                    field.fill(date_value or date.today().isoformat())
                elif field_type == "checkbox":
                    field.check()
                elif field_type == "select":
                    field.select_option(index=0)
                else:
                    field.fill(value if not wrote_primary_value else "验收备注")
                    wrote_primary_value = True

        page.locator("[data-double6-primary-action='true']").click()
        page.wait_for_timeout(50)
        first_module = page.locator("[data-double6-module-id]").first
        page.evaluate("id=>{location.hash='#module-'+id}", first_module.get_attribute("data-double6-module-id"))
        page.wait_for_timeout(30)
        question_capability = next((
            capability for capability in product["capabilities"] if capability.get("mode") == "in_page"
            and any(item.get("kind") == "question" for item in capability.get("starter", {}).get("starter_items", []))
        ), None)
        question_items = [item for item in (question_capability or first_capability)["starter"]["starter_items"] if item.get("kind") == "question"]
        question_present = bool(question_items)
        starter_wrong_feedback_pass = True
        starter_correct_feedback_pass = True
        starter_explanation_pass = True
        if question_present:
            starter_module = page.locator(f"[data-double6-module-id='{question_capability['recommendation_module_id']}']")
            page.evaluate("id=>{location.hash='#module-'+id}", question_capability["recommendation_module_id"])
            page.wait_for_timeout(30)
            question_item = question_items[0]
            question_card = starter_module.locator(".starter-question").first
            options = question_item.get("options") or []
            if options:
                wrong = next((str(option) for option in options if str(option).strip().lower() != str(question_item["answer"]).strip().lower()), None)
                if wrong is not None:
                    question_card.get_by_role("button", name=wrong, exact=True).click()
                    question_card.locator("[data-starter-action='submit-question']").click()
                    page.wait_for_timeout(30)
                    question_card = starter_module.locator(".starter-question").first
                    starter_wrong_feedback_pass = "再想一想" in question_card.inner_text() and "正确答案" in question_card.inner_text()
                question_card.get_by_role("button", name=str(question_item["answer"]), exact=True).click()
            else:
                def type_keypad(card: Any, value: str) -> None:
                    for char in value:
                        card.locator(f"[data-keypad-key='{char}']").click()

                if question_card.locator("[data-keypad-display]").count():
                    wrong_value = "0" if str(question_item["answer"]).strip() != "0" else "1"
                    type_keypad(question_card, wrong_value)
                    question_card.locator("[data-starter-action='submit-question']").click()
                    page.wait_for_timeout(30)
                    question_card = starter_module.locator(".starter-question").first
                    starter_wrong_feedback_pass = "再想一想" in question_card.inner_text() and "正确答案" in question_card.inner_text()
                    type_keypad(question_card, str(question_item["answer"]))
                else:
                    question_card.locator("[data-starter-answer-input]").fill("__验收错误答案__")
                    question_card.locator("[data-starter-action='submit-question']").click()
                    page.wait_for_timeout(30)
                    question_card = starter_module.locator(".starter-question").first
                    starter_wrong_feedback_pass = "再想一想" in question_card.inner_text() and "正确答案" in question_card.inner_text()
                    question_card.locator("[data-starter-answer-input]").fill(str(question_item["answer"]))
            question_card.locator("[data-starter-action='submit-question']").click()
            page.wait_for_timeout(30)
            question_card = starter_module.locator(".starter-question").first
            starter_correct_feedback_pass = "回答正确" in question_card.inner_text()
            starter_explanation_pass = str(question_item["explanation"]) in question_card.inner_text()
            starter_interaction_pass = starter_module.locator("[data-starter-result]").count() > 0
        else:
            starter_action = first_module.locator("[data-starter-action='toggle'],[data-starter-action='review'],[data-starter-action='calculate'],[data-starter-action='use-template']").first
            starter_action.click()
            page.wait_for_timeout(30)
            starter_interaction_pass = first_module.locator("[data-starter-result]").count() > 0
        page.reload(wait_until="load")
        page.wait_for_timeout(50)
        first_module = page.locator("[data-double6-module-id]").first
        starter_persistence_pass = page.locator("[data-starter-result]").count() > 0
        page.evaluate("id=>{location.hash='#module-'+id}", first_module.get_attribute("data-double6-module-id"))
        page.wait_for_timeout(20)
        fill_surface(first_module, test_value)
        page.locator("[data-double6-hook='save']").click()
        saved_visible = "已保存" in first_module.locator("[data-module-feedback]").inner_text()
        progress_feedback_pass = "自有记录 1 条" in page.locator("[data-double6-hook='progress-label']").first.inner_text()
        page.reload(wait_until="load")
        page.wait_for_timeout(50)
        first_module = page.locator("[data-double6-module-id]").first
        persistence_pass = first_module.locator("[data-module-record]").count() == 1 and test_value in first_module.locator("[data-module-record]").inner_text()

        module_action_pass = True
        module_nodes = page.locator("[data-double6-module-id]")
        for module_index in range(1, module_nodes.count()):
            module_root = module_nodes.nth(module_index)
            page.evaluate("id=>{location.hash='#module-'+id}", module_root.get_attribute("data-double6-module-id"))
            page.wait_for_timeout(30)
            fill_surface(module_root, f"模块验收-{module_index}")
            module_root.locator("[data-module-save]").click()
            module_action_pass = module_action_pass and module_root.locator("[data-module-record]").count() == 1

        surface_operation_results: dict[str, dict[str, bool]] = {}
        for contract in surface_contracts:
            surface_type = contract["surface_type"]
            if surface_type in surface_operation_results:
                continue
            module_root = page.locator(f"[data-double6-module-id='{contract['module_id']}']")
            page.evaluate("id=>{location.hash='#module-'+id}", contract["module_id"])
            page.wait_for_timeout(30)
            record = module_root.locator("[data-module-record]").first
            record.locator("[data-record-action='edit']").click()
            editable = module_root.locator("[data-module-form] textarea[data-double6-field]").first
            if editable.count() == 0:
                editable = module_root.locator("[data-module-form] input[data-double6-field]:not([type='date'])").first
            if editable.count() == 0:
                editable = module_root.locator("[data-module-form] select[data-double6-field]").first
            tag_name = editable.evaluate("node=>node.tagName.toLowerCase()")
            if tag_name == "select":
                options = editable.locator("option").all()
                choice = next((option.get_attribute("value") for option in options if option.get_attribute("value")), None)
                if choice is None:
                    raise RuntimeError(f"模块 {contract['module_id']} 缺少可选项")
                editable.select_option(choice)
                updated_value = editable.locator("option:checked").inner_text()
            elif (editable.get_attribute("type") or "") == "number":
                editable.fill("2")
                updated_value = "2"
            else:
                updated_value = f"更新-{surface_type}"
                editable.fill(updated_value)
            module_root.locator("[data-module-save]").click()
            update_pass = updated_value in module_root.locator("[data-module-record]").first.inner_text()
            status_pass = True
            if surface_type == "action_checklist":
                module_root.locator("[data-record-action='toggle-complete']").first.click()
                status_pass = "is-complete" in (module_root.locator("[data-module-record]").first.get_attribute("class") or "")
            elif surface_type == "stage_board":
                before = module_root.locator("[data-module-record]").first.inner_text()
                module_root.locator("[data-record-action='move']").first.click()
                status_pass = module_root.locator("[data-module-record]").first.inner_text() != before
            module_root.locator("[data-record-action='delete']").first.click()
            delete_pass = module_root.locator("[data-module-record]").count() == 0
            fill_surface(module_root, f"恢复-{surface_type}")
            module_root.locator("[data-module-save]").click()
            surface_operation_results[surface_type] = {"update": update_pass, "status_change": status_pass, "delete": delete_pass}

        today_rollover_pass: bool | None = None
        today_complete_pass: bool | None = None
        daily_contract = next((row for row in surface_contracts if row["surface_type"] == "action_checklist"), None)
        if daily_contract:
            daily_root = page.locator(f"[data-double6-module-id='{daily_contract['module_id']}']")
            page.evaluate("id=>{location.hash='#module-'+id}", daily_contract["module_id"])
            page.wait_for_timeout(30)
            fill_surface(daily_root, "昨天未完成的验收事项", date_value=(date.today() - timedelta(days=1)).isoformat())
            due = daily_root.locator("[data-field-id='due']")
            if due.count():
                daily_root.locator("[data-module-save]").click()
                page.evaluate("location.hash='#dashboard'")
                page.wait_for_timeout(50)
                today_board = page.locator("[data-today-workboard]")
                today_rollover_pass = "已顺延到今天" in today_board.inner_text() and today_board.locator("[data-today-complete]").count() >= 1
                today_action = today_board.locator("[data-today-complete]").first
                if today_rollover_pass:
                    today_action.click()
                    page.wait_for_timeout(30)
                    today_complete_pass = "昨天未完成的验收事项" not in today_board.inner_text()
                else:
                    today_complete_pass = False

        page.evaluate("location.hash='#data-tools'")
        page.wait_for_timeout(30)
        reliability_text = page.locator("[data-reliability-public-layer]").inner_text()
        reliability_public_layer_pass = page.locator("[data-reliability-public-layer]").count() == 1 and page.locator("[data-reliability-receipt]").count() == 1 and all(marker in reliability_text for marker in ["本地单文件", "当前设备、当前浏览器", "未接入云备份", "合成或自编"])
        export_path = output_dir / "candidate-export.json"
        finance_csv_export_pass: bool | None = None
        if page.locator("[data-double6-hook='export-csv']").count():
            csv_path = output_dir / "candidate-finance.csv"
            with page.expect_download() as csv_download:
                page.locator("[data-double6-hook='export-csv']").click()
            csv_download.value.save_as(str(csv_path))
            finance_csv_export_pass = csv_path.is_file() and csv_path.read_text(encoding="utf-8-sig").startswith("module,entry_type,amount")
        with page.expect_download() as download_info:
            page.locator("[data-double6-hook='export']").click()
        download_info.value.save_as(str(export_path))
        page.locator("[data-double6-hook='clear']").click()
        cleared = page.locator("[data-module-record]").count() == 0
        page.locator("[data-double6-hook='import']").set_input_files(str(export_path))
        page.wait_for_timeout(100)
        import_pass = page.locator("[data-double6-module-id]").first.locator("[data-module-record]").count() >= 1
        page.locator("[data-double6-hook='undo-import']").click()
        page.wait_for_timeout(50)
        import_undo_pass = page.locator("[data-module-record]").count() == 0
        page.locator("[data-double6-hook='import']").set_input_files(str(export_path))
        page.wait_for_timeout(100)

        unknown_v2_path = output_dir / "unknown-v2.json"
        unknown_v2 = read_json(export_path)
        unknown_v2["futureEnvelope"] = {"preserve": True}
        unknown_v2["modules"]["future-module"] = {"records": [], "future": True}
        first_module_id = product["recommendation_plan"]["selected_core_module_ids"][0]
        unknown_v2["modules"][first_module_id]["futureMeta"] = "保留"
        write_json(unknown_v2_path, unknown_v2)
        page.locator("[data-double6-hook='import']").set_input_files(str(unknown_v2_path))
        page.wait_for_timeout(100)
        unknown_v2_state = json.loads(page.evaluate("localStorage.getItem(Object.keys(localStorage)[0])"))
        unmapped_v2 = unknown_v2_state.get("legacyImport", {}).get("unmapped", {})
        v2_unknown_preserved = (
            unmapped_v2.get("envelope", {}).get("futureEnvelope", {}).get("preserve") is True
            and unmapped_v2.get("modules", {}).get("future-module", {}).get("future") is True
            and unmapped_v2.get("moduleExtras", {}).get(first_module_id, {}).get("futureMeta") == "保留"
        )

        malicious_path = output_dir / "malicious-v2.json"
        malicious = read_json(export_path)
        malicious_record = malicious["modules"][first_module_id]["records"][0]
        malicious_record["id"] = 'r-safe"><img data-double6-xss src=x onerror="window.__double6Xss=true">'
        malicious_record["values"][next(iter(malicious_record["values"]))] = '<img data-double6-xss src=x onerror="window.__double6Xss=true">'
        write_json(malicious_path, malicious)
        page.locator("[data-double6-hook='import']").set_input_files(str(malicious_path))
        page.wait_for_timeout(100)
        imported_record_id = page.locator(f"[data-double6-module-id='{first_module_id}'] [data-module-record]").first.get_attribute("data-record-id") or ""
        malicious_import_sanitized = (
            page.locator("img[data-double6-xss]").count() == 0
            and page.evaluate("Boolean(window.__double6Xss)") is False
            and imported_record_id.startswith("r-import-")
        )

        legacy_path = output_dir / "legacy-v1.json"
        write_json(legacy_path, {"value": "历史备注", "checked": ["old-item"], "unknown": {"preserve": True}})
        page.locator("[data-double6-hook='import']").set_input_files(str(legacy_path))
        page.wait_for_timeout(100)
        legacy_import_pass = visible(page.locator("[data-double6-hook='legacy-import']")) and "历史备注" in page.locator("[data-double6-hook='legacy-import']").inner_text()
        legacy_state = json.loads(page.evaluate("localStorage.getItem(Object.keys(localStorage)[0])"))
        legacy_unknown_preserved = legacy_state.get("legacyImport", {}).get("unmapped", {}).get("unknown", {}).get("preserve") is True

        page.evaluate("id=>{location.hash='#module-'+id}", first_module_id)
        page.wait_for_timeout(30)
        page.locator("[data-double6-field]").first.focus()
        page.locator("[data-double6-field]").first.press("Tab")
        focus_details = page.evaluate("""() => {const el=document.activeElement;if(!el)return {effective:false};const s=getComputedStyle(el);return {effective:el!==document.body&&el!==document.documentElement&&((s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>0)||s.boxShadow!=='none'),tag:el.tagName,hook:el.dataset.double6Hook||null,outline_style:s.outlineStyle,outline_width:s.outlineWidth,box_shadow:s.boxShadow}}""")
        focus_visible = bool(focus_details["effective"])
        interactive = page.locator("button,input,textarea,select,a[href]")
        touch = []
        for index in range(interactive.count()):
            item = interactive.nth(index)
            if not item.is_visible():
                continue
            box = item.bounding_box() or {"width": 0, "height": 0}
            name = item.evaluate("el=>(el.getAttribute('aria-label')||el.innerText||el.getAttribute('title')||(el.labels&&el.labels[0]&&el.labels[0].innerText)||el.value||'').trim()")
            touch.append({"width": box["width"], "height": box["height"], "accessible_name": name})

        viewports = [
            {"name": "mobile", "width": 390, "height": 844},
            {"name": "tablet", "width": 768, "height": 1024},
            {"name": "desktop", "width": 1280, "height": 900},
        ]
        responsive = []
        for viewport in viewports:
            page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
            page.evaluate("location.hash='#dashboard'")
            page.reload(wait_until="load")
            metrics = page.evaluate("""() => {const root=document.querySelector('[data-double6-build-id]');const style=getComputedStyle(root);const visible=el=>!!el&&getComputedStyle(el).display!=='none'&&el.getBoundingClientRect().width>0;const life=root.classList.contains('renderer-personal_life_dashboard');const nav=document.querySelector('[data-double6-role=mobile-bottom-navigation]');const dashboard=document.querySelector('[data-dashboard-signature]');const navBox=nav&&nav.getBoundingClientRect();const dashboardBox=dashboard&&dashboard.getBoundingClientRect();const lifeNavItems=life&&nav?nav.querySelectorAll('.nav-item').length:0;const lifeUnobscured=!life||Boolean(navBox&&dashboardBox&&parseFloat(style.paddingLeft)>=64&&dashboardBox.left>=navBox.right+4&&lifeNavItems===9);return {no_overflow:document.documentElement.scrollWidth<=document.documentElement.clientWidth,primary_action_count:document.querySelectorAll('[data-double6-primary-action=true]').length,root_display:style.display,grid_columns:style.gridTemplateColumns,identity_navigation_visible:visible(document.querySelector('[data-double6-role=identity-navigation]')),mobile_bottom_navigation_visible:visible(document.querySelector('[data-double6-role=mobile-bottom-navigation]')),personal_life_mobile_unobscured:lifeUnobscured,personal_life_nav_items:lifeNavItems}}""")
            path = output_dir / f"candidate-{lock['build_id']}-{viewport['name']}.png"
            page.screenshot(path=str(path), full_page=True)
            screenshots.append({"viewport": viewport["name"], "path": path.name, "sha256": sha(path)})
            responsive.append({**viewport, **metrics})
        runtime_storage_keys = sorted(set(page.evaluate("window.__double6StorageKeys||[]")))
        final_storage_keys = sorted(page.evaluate("Object.keys(localStorage)"))
        alternate_storage = {
            "session_storage_keys": sorted(page.evaluate("Object.keys(sessionStorage)")),
            "cookie_count": len(context.cookies()),
            "indexed_db_names": sorted(page.evaluate("indexedDB.databases?indexedDB.databases().then(rows=>rows.map(row=>row.name||'')):[]")),
        }
        context.close()

        failure_context = browser.new_context(viewport={"width": 390, "height": 844})
        failure_context.add_init_script("Storage.prototype.setItem=function(){throw new DOMException('denied','QuotaExceededError')}")
        failure_page = failure_context.new_page()
        failure_page.goto(entry_url, wait_until="load")
        failure_page.locator("[data-double6-primary-action='true']").click()
        failure_page.wait_for_timeout(30)
        failure_first_id = failure_page.locator("[data-double6-module-id]").first.get_attribute("data-double6-module-id")
        failure_page.evaluate("id=>{location.hash='#module-'+id}", failure_first_id)
        failure_page.wait_for_timeout(20)
        failure_root = failure_page.locator("[data-double6-module-id]").first
        fill_surface(failure_root, "失败时也要保留")
        failure_fields = failure_root.locator("[data-double6-field]")
        values_before = failure_fields.evaluate_all(
            "rows=>rows.map(el=>el.type==='checkbox'?el.checked:el.value)"
        )
        failure_root.locator("[data-module-save]").click()
        values_after = failure_fields.evaluate_all(
            "rows=>rows.map(el=>el.type==='checkbox'?el.checked:el.value)"
        )
        storage_failure_pass = (
            "保存失败" in failure_root.locator("[data-module-feedback]").inner_text()
            and values_before == values_after
        )
        failure_context.close()
        browser.close()
    return {
        "schema_version": 1,
        "status": "pass",
        "collector_session_id": f"collector-{uuid.uuid4().hex}",
        "build_id": lock["build_id"],
        "candidate_sha256": sha(candidate),
        "build_id_matches": build_id_matches,
        "primary_action_count": primary_count,
        "experience": {
            **root_experience,
            "representative_item_count": representative_item_count,
            "dashboard_module_link_count": dashboard_module_link_count,
            "dashboard_module_link_ids": dashboard_module_link_ids,
            "first_screen_slots": first_screen_slots,
            "structure_fingerprint": hashlib.sha256(str(structure_signature).encode("utf-8")).hexdigest(),
            "semantic_emoji_marker_count": semantic_emoji_marker_count,
            "progress_feedback_pass": progress_feedback_pass,
            "main_work_object_count": main_work_object_count,
            "primary_action_in_first_viewport": primary_action_in_first_viewport,
        },
        "core_flow": {"saved_visible": saved_visible, "persistence_pass": persistence_pass},
        "starter": {
            "contract_version": starter_contract_version,
            "surface_count": starter_surface_count,
            "item_counts": starter_item_counts,
            "all_nonempty": starter_all_nonempty,
            "question_present": question_present,
            "wrong_feedback_pass": starter_wrong_feedback_pass,
            "correct_feedback_pass": starter_correct_feedback_pass,
            "explanation_pass": starter_explanation_pass,
            "interaction_pass": starter_interaction_pass,
            "persistence_pass": starter_persistence_pass,
            "reliability_public_layer_pass": reliability_public_layer_pass,
        },
        "today": {
            "present": today_present,
            "quick_backup_controls": quick_backup_controls,
            "overdue_rollover_pass": today_rollover_pass,
            "complete_pass": today_complete_pass,
            "finance_csv_export_pass": finance_csv_export_pass,
        },
        "export_import": {
            "cleared": cleared, "import_pass": import_pass, "import_undo_pass": import_undo_pass,
            "malicious_import_sanitized": malicious_import_sanitized, "export_sha256": sha(export_path),
            "legacy_import_pass": legacy_import_pass, "legacy_unknown_preserved": legacy_unknown_preserved,
            "v2_unknown_preserved": v2_unknown_preserved,
        },
        "surfaces": {
            "module_count": len(surface_contracts), "contracts": surface_contracts,
            "types": sorted({row["surface_type"] for row in surface_contracts}),
            "module_action_pass": module_action_pass, "operation_results": surface_operation_results,
        },
        "navigation": navigation_results,
        "storage_failure_pass": storage_failure_pass,
        "accessibility": {"focus_visible": focus_visible, "focus_details": focus_details, "touch_targets": touch},
        "responsive": responsive,
        "runtime_storage_keys": runtime_storage_keys,
        "final_storage_keys": final_storage_keys,
        "alternate_storage": alternate_storage,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "unauthorized_requests": requests,
        "screenshots": screenshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chromium", type=Path, required=True)
    parser.add_argument("--smoke", choices=["child_learning", "finance", "personal_life_mobile"])
    args = parser.parse_args()
    try:
        result = collect_smoke(args.run.resolve(), args.chromium.resolve(), args.smoke) if args.smoke else collect(args.run.resolve(), args.output_dir.resolve(), args.chromium.resolve())
        write_json(args.output_dir / "browser-result.json", result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") == "pass" else 1
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        write_json(args.output_dir / "browser-result.json", {"schema_version": 1, "status": "blocked", "error": error})
        print(json.dumps({"status": "blocked", "error": error}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
