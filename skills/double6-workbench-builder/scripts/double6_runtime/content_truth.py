"""用户可见内容的真值合同与确定性审稿门。"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any


CONTRACT_VERSION = "double6_content_truth_v3"
SUPPORTED_CONTRACT_VERSIONS = {
    "double6_content_truth_v1",
    "double6_content_truth_v2",
    CONTRACT_VERSION,
}
ALLOWED_MODES = {"assessment", "guided_practice", "offscreen_action"}
ALLOWED_KINDS = {
    "arithmetic", "meaning_mapping", "classification", "sequence",
    "reading_evidence", "poetry_mapping", "offscreen_action", "counting",
    "ordered_tokens", "short_response", "handwriting_practice",
    "letter_tiles", "phrase_blocks", "oral_response",
}
ALLOWED_RESPONSE_MODES = {
    "single_choice", "number_input", "ordered_tokens", "short_text",
    "guardian_observation", "handwriting_canvas", "letter_tiles",
    "phrase_blocks", "guardian_oral_observation",
}
ALLOWED_CONTENT_ROLES = {
    "misconception_repair", "additional_transfer", "constructed_response",
    "structured_offscreen_expression",
}
ALLOWED_TRUTH_PREFIXES = {
    "deterministic_arithmetic", "deterministic_step_chain", "deterministic_sequence",
    "common_modern_chinese_meaning", "common_english_word_meaning", "common_category_membership",
    "self_contained_sentence_semantics", "self_contained_reading_passage",
    "public_domain_poem", "direct_text_semantics", "observable_completion_contract",
    "conservative_child_offscreen_safety_policy", "dictionary_meaning",
}
ALLOWED_SAFETY_POLICIES = {
    "indoor_guardian_observed_no_media",
    "outdoor_guardian_line_of_sight_observe_only_no_touch",
}


def _finding(item_id: str, code: str, message: str, severity: str = "blocking") -> dict[str, str]:
    return {"item_id": item_id, "code": code, "severity": severity, "message": message}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _option_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = item.get("options", [])
    return rows if isinstance(rows, list) else []


def _audit_common(item: dict[str, Any], item_id: str, bundle_author: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    mode = item.get("mode")
    kind = item.get("kind")
    if mode not in ALLOWED_MODES:
        findings.append(_finding(item_id, "mode_invalid", "mode 必须是 assessment、guided_practice 或 offscreen_action。"))
    if kind not in ALLOWED_KINDS:
        findings.append(_finding(item_id, "kind_invalid", "kind 未登记在内容真值合同中。"))
    for field in ("family_id", "objective", "prompt"):
        if not _text(item.get(field)):
            findings.append(_finding(item_id, f"{field}_missing", f"缺少 {field}。"))

    provenance = item.get("provenance", {})
    truth_basis = provenance.get("truth_basis", []) if isinstance(provenance, dict) else []
    if not isinstance(truth_basis, list) or not truth_basis:
        findings.append(_finding(item_id, "truth_basis_missing", "必须登记答案/事实的 truth_basis，不能只登记社媒呈现来源。"))
    elif any(_text(row).split(":", 1)[0] not in ALLOWED_TRUTH_PREFIXES for row in truth_basis):
        findings.append(_finding(item_id, "truth_basis_role_invalid", "truth_basis 含未允许的证据角色；社媒作者宣称、热度或模型自述不能作为真值依据。"))
    if not isinstance(provenance, dict) or not provenance.get("presentation_donors"):
        findings.append(_finding(item_id, "presentation_donor_missing", "必须登记呈现机制的社媒或既有设计来源。", "major"))

    review = item.get("review", {})
    if not isinstance(review, dict) or review.get("status") != "pass":
        findings.append(_finding(item_id, "independent_review_not_passed", "独立内容审稿状态必须为 pass。"))
    if isinstance(review, dict) and review.get("unresolved_findings"):
        findings.append(_finding(item_id, "unresolved_review_findings", "仍有未关闭的人工审稿 finding。"))
    if not isinstance(review, dict) or not all(_text(review.get(field)) for field in ("reviewer_id", "review_method", "review_receipt_sha256")):
        findings.append(_finding(item_id, "review_provenance_missing", "审稿必须登记 reviewer_id、review_method 与 review_receipt_sha256。"))
    elif review.get("independent_from_author") is not True or _text(review.get("reviewer_id")) == bundle_author or not re.fullmatch(r"[0-9a-f]{64}", _text(review.get("review_receipt_sha256"))) or _text(review.get("review_receipt_sha256")) == "0" * 64 or not _text(review.get("review_receipt_path")):
        findings.append(_finding(item_id, "independent_review_invalid", "审稿人必须与作者不同，明确 independent_from_author=true，并绑定 64 位小写 SHA256 回执。"))

    render = item.get("render_contract")
    if not isinstance(render, dict):
        findings.append(_finding(item_id, "render_contract_missing", "每项内容必须有 render_contract，禁止因缺合同而跳过渲染核对。"))
    else:
        if not render.get("required_pre_action_tokens"):
            findings.append(_finding(item_id, "required_render_tokens_missing", "render_contract 必须登记可在页面核对的 required_pre_action_tokens。"))
        if mode != "offscreen_action" and not render.get("expected_success_tokens"):
            findings.append(_finding(item_id, "expected_success_tokens_missing", "可判定内容必须登记答对解释的 expected_success_tokens。"))

    response_mode = item.get("response_mode", "single_choice" if mode != "offscreen_action" else "guardian_observation")
    if response_mode not in ALLOWED_RESPONSE_MODES:
        findings.append(_finding(item_id, "response_mode_invalid", "response_mode 未登记在内容真值合同中。"))
    if mode == "offscreen_action" and response_mode != "guardian_observation":
        findings.append(_finding(item_id, "offscreen_response_mode_invalid", "屏外行动必须使用 guardian_observation。"))
    if mode != "offscreen_action" and response_mode == "guardian_observation":
        findings.append(_finding(item_id, "scored_response_mode_invalid", "可判定内容不得使用 guardian_observation。"))

    if mode != "offscreen_action":
        options = _option_rows(item)
        answer = _text(item.get("oracle", {}).get("answer")) if isinstance(item.get("oracle"), dict) else ""
        values = [_text(row.get("value")) for row in options if isinstance(row, dict)]
        completion_only = response_mode in {"handwriting_canvas", "guardian_oral_observation"}
        if not answer and not completion_only:
            findings.append(_finding(item_id, "answer_missing", "可判定内容必须登记 oracle.answer。"))
        if response_mode == "single_choice":
            if not options:
                findings.append(_finding(item_id, "options_missing", "单选内容必须登记选项。"))
            if len(values) != len(set(values)):
                findings.append(_finding(item_id, "duplicate_option_values", "选项值必须唯一。"))
            if answer and values.count(answer) != 1:
                findings.append(_finding(item_id, "answer_not_unique_option", "正确答案必须且只能对应一个选项。"))
        elif options:
            findings.append(_finding(item_id, "options_for_non_choice", "非单选内容不得保留会误导运行时的 options。"))

        if mode == "assessment" and isinstance(render, dict) and render.get("pre_action_answer_exposed") is True:
            findings.append(_finding(item_id, "answer_exposed_before_action", "测验型内容不得在作答前通过图、标题、标记或解释泄露答案。"))
    return findings


def _audit_v2_contract(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    """第二版强制逐题错因、变式与真实交互合同。"""
    findings: list[dict[str, str]] = []
    role = item.get("content_role")
    response_mode = item.get("response_mode")
    interaction = item.get("interaction_contract", {})
    variation = item.get("variation_values")
    if role not in ALLOWED_CONTENT_ROLES:
        findings.append(_finding(item_id, "content_role_invalid", "v2 内容必须登记四类定向补充角色之一。"))
    if not isinstance(variation, dict) or not variation or any(not _text(key) or not _text(value) for key, value in variation.items()):
        findings.append(_finding(item_id, "variation_values_missing", "v2 内容必须把本题实际变式逐项绑定为非空 variation_values。"))
    if not isinstance(interaction, dict):
        findings.append(_finding(item_id, "interaction_contract_missing", "v2 内容必须登记 interaction_contract。"))
        interaction = {}

    misconception_refs = item.get("misconception_refs", [])
    if role == "misconception_repair":
        if not isinstance(misconception_refs, list) or len(misconception_refs) != 1 or not _text(misconception_refs[0]):
            findings.append(_finding(item_id, "misconception_ref_invalid", "逐错因纠正题必须且只能绑定一个 misconception_ref。"))
        error_mapping = item.get("error_mapping", {})
        if not isinstance(error_mapping, dict) or not error_mapping or set(error_mapping.values()) != set(misconception_refs):
            findings.append(_finding(item_id, "error_misconception_binding_invalid", "错误探针必须全部映射到本题唯一错因。"))
        if not _text(item.get("remediation_next_action")):
            findings.append(_finding(item_id, "remediation_next_action_missing", "纠正题必须给出具体、短小的下一步动作。"))
    elif misconception_refs:
        findings.append(_finding(item_id, "misconception_ref_on_wrong_role", "非逐错因纠正内容不得占用 misconception_refs。"))

    if role == "additional_transfer":
        axis = item.get("transfer_axis")
        if not isinstance(axis, dict) or not axis or not all(_text(value) for value in axis.values()):
            findings.append(_finding(item_id, "transfer_axis_missing", "新增迁移题必须说明改变了什么对象、措辞或生活情境。"))

    if response_mode == "single_choice":
        if interaction.get("type") != "single_choice":
            findings.append(_finding(item_id, "single_choice_interaction_invalid", "单选题 interaction_contract.type 必须为 single_choice。"))
    elif response_mode == "number_input":
        if interaction.get("type") != "number_input" or interaction.get("custom_keypad_required") is not True or not _text(interaction.get("wrong_answer_probe")):
            findings.append(_finding(item_id, "number_input_contract_invalid", "数字题必须使用页内数字键盘并登记错误探针。"))
    elif response_mode == "short_text":
        accepted = interaction.get("accepted_answers", [])
        probe = _text(interaction.get("wrong_answer_probe"))
        answer = _text(item.get("oracle", {}).get("answer"))
        if interaction.get("type") != "short_text" or not isinstance(accepted, list) or answer not in [_text(value) for value in accepted] or not probe or probe in [_text(value) for value in accepted]:
            findings.append(_finding(item_id, "short_text_contract_invalid", "短答必须绑定答案集合和不在答案集合内的错误探针。"))
    elif response_mode == "ordered_tokens":
        tokens = interaction.get("tokens", [])
        correct = interaction.get("correct_order", [])
        wrong = interaction.get("wrong_order_probe", [])
        answer = item.get("oracle", {}).get("answer")
        if interaction.get("type") != "ordered_tokens" or not isinstance(tokens, list) or len(tokens) < 2 or len(tokens) != len(set(tokens)) or correct != answer or sorted(correct) != sorted(tokens) or sorted(wrong) != sorted(tokens) or wrong == correct:
            findings.append(_finding(item_id, "ordered_tokens_contract_invalid", "排序题必须登记唯一词块、正确顺序和包含相同词块的错误顺序探针。"))
    elif response_mode == "guardian_observation":
        rubric = interaction.get("observable_rubric", [])
        if interaction.get("type") != "guardian_observation" or not isinstance(rubric, list) or not 2 <= len(rubric) <= 3 or any(not _text(row.get("criterion_id")) or not _text(row.get("label")) for row in rubric if isinstance(row, dict)) or any(not isinstance(row, dict) for row in rubric):
            findings.append(_finding(item_id, "observable_rubric_invalid", "屏外观察必须登记 2–3 个具名、可观察且不采集媒体的标准。"))
    elif response_mode == "handwriting_canvas":
        oracle = item.get("oracle", {})
        methods = interaction.get("input_methods", [])
        if (
            interaction.get("type") != "handwriting_canvas"
            or interaction.get("grid_style") != "tianzige"
            or not {"touch", "pointer"}.issubset(set(methods if isinstance(methods, list) else []))
            or interaction.get("blank_submission_probe") is not True
            or interaction.get("no_ocr_or_auto_correct_claim") is not True
            or interaction.get("completion_mode") != "self_compare"
            or _text(interaction.get("writing_target")) != _text(oracle.get("target"))
            or not _text(oracle.get("target"))
            or not _text(oracle.get("completion_evidence"))
            or oracle.get("mastery_claim") is not False
        ):
            findings.append(_finding(item_id, "handwriting_canvas_contract_invalid", "手写练习必须使用田字格触控画布、空白提交探针和自我对照完成；不得声称 OCR 判对或证明书写掌握。"))
    elif response_mode in {"letter_tiles", "phrase_blocks"}:
        rows_key = "tiles" if response_mode == "letter_tiles" else "blocks"
        correct_key = "correct_tile_ids" if response_mode == "letter_tiles" else "correct_block_ids"
        wrong_key = "wrong_tile_ids" if response_mode == "letter_tiles" else "wrong_block_ids"
        rows = interaction.get(rows_key, [])
        correct_ids = interaction.get(correct_key, [])
        wrong_ids = interaction.get(wrong_key, [])
        row_ids = [_text(row.get("id")) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        labels = {_text(row.get("id")): _text(row.get("label")) for row in rows if isinstance(row, dict)} if isinstance(rows, list) else {}
        assembled = "".join(labels.get(_text(value), "") for value in correct_ids)
        answer = _text(item.get("oracle", {}).get("answer"))
        valid_wrong = bool(wrong_ids) and wrong_ids != correct_ids and all(_text(value) in labels for value in wrong_ids)
        if (
            interaction.get("type") != response_mode
            or len(row_ids) < 2
            or len(row_ids) != len(set(row_ids))
            or any(not value for value in row_ids)
            or any(not value for value in labels.values())
            or not correct_ids
            or any(_text(value) not in labels for value in correct_ids)
            or not valid_wrong
            or assembled != answer
            or _text(interaction.get("assembled_answer")) != answer
        ):
            findings.append(_finding(item_id, f"{response_mode}_contract_invalid", "字母卡/词块必须使用唯一内部 ID，绑定正确组合、明确错误探针和可独立重算的组装答案。"))
    elif response_mode == "guardian_oral_observation":
        rubric = interaction.get("observable_rubric", [])
        if (
            interaction.get("type") != "guardian_oral_observation"
            or not isinstance(rubric, list)
            or not 2 <= len(rubric) <= 3
            or any(not isinstance(row, dict) or not _text(row.get("criterion_id")) or not _text(row.get("label")) for row in rubric)
            or interaction.get("no_audio_collection") is not True
            or interaction.get("guardian_required") is not True
            or interaction.get("answer_key_visible_to_guardian_only") is not True
            or not _text(item.get("oracle", {}).get("completion_evidence"))
            or item.get("oracle", {}).get("automated_correctness_claim") is not False
        ):
            findings.append(_finding(item_id, "guardian_oral_observation_contract_invalid", "口头作答必须由家长按 2–3 个可观察标准确认，不录音、不上传，也不得声称自动判对。"))
    return findings


def _audit_v3_contract(item: dict[str, Any], item_id: str, stage_id: str) -> list[dict[str, str]]:
    """第三版禁止低龄学习者被默认要求使用键盘作答。"""
    findings: list[dict[str, str]] = []
    if stage_id == "primary-transition-1-to-2" and item.get("response_mode") == "short_text":
        interaction = item.get("interaction_contract", {})
        if interaction.get("learner_keyboard_capability_confirmed") is not True:
            findings.append(_finding(item_id, "young_learner_keyboard_input_forbidden", "一升二内容不得默认要求键盘短答；必须改用手写板、卡片、词块或家长口头观察。"))
    if item.get("response_mode") == "handwriting_canvas" and item.get("mode") != "guided_practice":
        findings.append(_finding(item_id, "handwriting_assessment_unsupported", "未接入人工或可信识别前，手写画布只能作为引导练习，不能自动判定掌握。"))
    if item.get("response_mode") == "ordered_tokens":
        interaction = item.get("interaction_contract", {})
        tokens = interaction.get("tokens", [])
        display = interaction.get("display_order", [])
        correct = interaction.get("correct_order", [])
        if not isinstance(display, list) or sorted(display) != sorted(tokens) or display == correct:
            findings.append(_finding(item_id, "ordered_tokens_display_order_invalid", "排序题必须登记与正确答案不同的初始卡片顺序；重置后仍恢复该顺序，不能直接展示答案。"))
    return findings


def _audit_arithmetic(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    oracle = item.get("oracle", {})
    operation = oracle.get("operation", "subtract")
    if operation == "add_missing":
        try:
            initial = int(oracle["initial_count"])
            added = int(oracle["added_count"])
            target = int(oracle["target_count"])
            answer = int(oracle["answer"])
        except (KeyError, TypeError, ValueError):
            return [_finding(item_id, "arithmetic_oracle_invalid", "补数题必须登记可解析的初始量、补充量、目标量和答案。")]
        if initial + added != target or answer != added:
            findings.append(_finding(item_id, "arithmetic_conservation_failed", "初始量、补充量、目标量与答案不守恒。"))
        if _integer(oracle.get("explanation_result")) != added:
            findings.append(_finding(item_id, "explanation_oracle_mismatch", "补数解释的结构化结果必须与答案一致。"))
        snapshots = item.get("render_contract", {}).get("object_counts", [])
        if snapshots != [initial]:
            findings.append(_finding(item_id, "rendered_object_counts_mismatch", f"作答前具象对象计数应为 {[initial]}，实际登记为 {snapshots}。"))
        return findings
    if operation == "add":
        try:
            left = int(oracle["left"])
            right = int(oracle["right"])
            result = int(oracle["result"])
            answer = int(oracle["answer"])
        except (KeyError, TypeError, ValueError):
            return [_finding(item_id, "arithmetic_oracle_invalid", "加法题必须登记 left、right、result 和答案。")]
        if left + right != result or answer != result or _integer(oracle.get("explanation_result")) != result:
            findings.append(_finding(item_id, "arithmetic_conservation_failed", "加法题的两个加数、结果、答案和解释不守恒。"))
        return findings
    if operation == "split_addend":
        try:
            whole = int(oracle["whole"])
            parts = [int(value) for value in oracle["parts"]]
            answer = [int(value) for value in oracle["answer"]]
        except (KeyError, TypeError, ValueError):
            return [_finding(item_id, "arithmetic_oracle_invalid", "拆数题必须登记 whole、parts 与答案。")]
        if len(parts) != 2 or sum(parts) != whole or answer != parts:
            findings.append(_finding(item_id, "arithmetic_conservation_failed", "拆出的两部分必须与原加数守恒并按合同顺序作答。"))
        return findings
    if operation != "subtract":
        return [_finding(item_id, "arithmetic_operation_invalid", "当前算术合同只支持 add、subtract、add_missing 或 split_addend。")]
    try:
        initial = int(oracle["initial_count"])
        removed = int(oracle["removed_count"])
        remaining = int(oracle["remaining_count"])
        answer = int(oracle["answer"])
    except (KeyError, TypeError, ValueError):
        return [_finding(item_id, "arithmetic_oracle_invalid", "算术题必须登记可解析的初始量、变化量、结果量和答案。")]
    if initial - removed != remaining or answer != remaining:
        findings.append(_finding(item_id, "arithmetic_conservation_failed", "初始量、移除量、结果量与答案不守恒。"))
    if _integer(oracle.get("explanation_result")) != remaining:
        findings.append(_finding(item_id, "explanation_oracle_mismatch", "减法解释的结构化结果必须与答案一致。"))
    steps = oracle.get("steps", [])
    if not isinstance(steps, list) or not steps:
        findings.append(_finding(item_id, "arithmetic_steps_missing", "分步题必须登记每一步 before/remove/after。"))
    else:
        expected_before = initial
        total_removed = 0
        for index, step in enumerate(steps, 1):
            try:
                before = int(step["before"])
                change = int(step["remove"])
                after = int(step["after"])
            except (KeyError, TypeError, ValueError):
                findings.append(_finding(item_id, "arithmetic_step_invalid", f"第 {index} 步字段不可解析。"))
                continue
            if before != expected_before or before - change != after:
                findings.append(_finding(item_id, "arithmetic_step_chain_failed", f"第 {index} 步与前一步或减法结果不一致。"))
            expected_before = after
            total_removed += change
        if expected_before != remaining or total_removed != removed:
            findings.append(_finding(item_id, "arithmetic_step_total_failed", "分步链的总变化量或最终量与题目不一致。"))
    snapshots = item.get("render_contract", {}).get("object_counts", [])
    expected = [initial] + [int(step.get("after", -1)) for step in steps if isinstance(step, dict)]
    if snapshots != expected:
        findings.append(_finding(item_id, "rendered_object_counts_mismatch", f"视觉对象计数应为 {expected}，实际登记为 {snapshots}。"))
    return findings


def _audit_mapping(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    answer = _text(oracle.get("answer"))
    target = _text(oracle.get("target_semantic"))
    matching = [row for row in _option_rows(item) if _text(row.get("value")) == answer]
    if not target or len(matching) != 1 or _text(matching[0].get("semantic")) != target:
        return [_finding(item_id, "mapping_oracle_mismatch", "正确选项的 semantic 必须与目标语义完全一致。")]
    if _text(oracle.get("explanation_semantic")) != target:
        return [_finding(item_id, "explanation_oracle_mismatch", "映射题 explanation_semantic 必须与目标语义一致。")]
    return []


def _audit_counting(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    expected = _integer(oracle.get("expected_count"))
    answer = _integer(oracle.get("answer"))
    rendered = item.get("render_contract", {}).get("object_counts", [])
    if expected is None or answer != expected:
        return [_finding(item_id, "counting_oracle_invalid", "数数题答案必须等于独立登记的 expected_count。")]
    if rendered != [expected]:
        return [_finding(item_id, "rendered_object_counts_mismatch", f"数数画面必须实际呈现 {expected} 个对象。")]
    return []


def _audit_ordered_tokens(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    answer = oracle.get("answer")
    expected = oracle.get("expected_order")
    if not isinstance(answer, list) or answer != expected or len(answer) < 2 or len(answer) != len(set(answer)):
        return [_finding(item_id, "ordered_tokens_oracle_invalid", "排序答案必须是至少两个唯一词块，并与 expected_order 一致。")]
    source_text = _text(oracle.get("source_text"))
    evidence = _text(oracle.get("evidence_span"))
    if (source_text or evidence) and (not source_text or not evidence or evidence not in source_text):
        return [_finding(item_id, "ordered_tokens_evidence_invalid", "带文本证据的排序题必须把 evidence_span 逐字绑定到 source_text。")]
    return []


def _audit_short_response(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    answer = _text(oracle.get("answer"))
    accepted = [_text(value) for value in oracle.get("accepted_answers", [])]
    if not answer or answer not in accepted:
        return [_finding(item_id, "short_response_oracle_invalid", "短答答案必须出现在独立登记的 accepted_answers 中。")]
    source_text = _text(oracle.get("source_text"))
    evidence = _text(oracle.get("evidence_span"))
    if (source_text or evidence) and (not source_text or not evidence or evidence not in source_text or answer not in evidence):
        return [_finding(item_id, "short_response_evidence_invalid", "带文本证据的短答必须把答案与逐字 evidence_span 绑定。")]
    return []


def _audit_classification(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    rows = oracle.get("displayed_objects", [])
    expected_category = _text(oracle.get("expected_category"))
    outliers = [row for row in rows if isinstance(row, dict) and _text(row.get("category")) != expected_category]
    if not expected_category or len(outliers) != 1 or _text(outliers[0].get("value")) != _text(oracle.get("answer")):
        return [_finding(item_id, "classification_not_unique", "分类题必须存在且只存在一个基于已声明类别的异类。")]
    if _text(oracle.get("explanation_outlier")) != _text(oracle.get("answer")):
        return [_finding(item_id, "explanation_oracle_mismatch", "分类解释中的异类必须与答案一致。")]
    return []


def _audit_sequence(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    pattern = oracle.get("pattern", [])
    answer = _text(oracle.get("answer"))
    if len(pattern) < 4 or len(set(pattern[:2])) != 2 or any(value != pattern[index % 2] for index, value in enumerate(pattern)):
        return [_finding(item_id, "sequence_rule_ambiguous", "当前序列合同只接受至少两轮清楚交替的 AB 规律。")]
    if answer != _text(pattern[len(pattern) % 2]):
        return [_finding(item_id, "sequence_answer_mismatch", "下一项答案与已声明 AB 规律不一致。")]
    if _text(oracle.get("explanation_next")) != answer:
        return [_finding(item_id, "explanation_oracle_mismatch", "规律解释中的下一项必须与答案一致。")]
    return []


def _audit_reading(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    oracle = item.get("oracle", {})
    passage = _text(oracle.get("passage"))
    evidence = _text(oracle.get("evidence_span"))
    if not passage or not evidence or evidence not in passage:
        return [_finding(item_id, "reading_evidence_missing", "阅读题答案证据必须逐字存在于题内文本。")]
    answer = _text(oracle.get("answer"))
    answer_text = _text(oracle.get("answer_text"))
    if not answer_text or answer_text not in evidence:
        return [_finding(item_id, "reading_answer_evidence_mismatch", "阅读题 answer_text 与 evidence_span 必须指向同一答案。")]
    if item.get("response_mode", "single_choice") == "single_choice":
        matching = [row for row in _option_rows(item) if _text(row.get("value")) == answer]
        if len(matching) != 1 or _text(matching[0].get("semantic")) != answer_text:
            return [_finding(item_id, "reading_answer_evidence_mismatch", "阅读题正确选项语义、answer_text 与 evidence_span 必须指向同一答案。")]
    if _text(oracle.get("explanation_answer_text")) != answer_text:
        return [_finding(item_id, "explanation_oracle_mismatch", "阅读解释中的答案实体必须与证据答案一致。")]
    return []


def _audit_poetry(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    findings = _audit_mapping(item, item_id)
    oracle = item.get("oracle", {})
    poem = oracle.get("source_text", {})
    lines = poem.get("lines", []) if isinstance(poem, dict) else []
    evidence = _text(oracle.get("evidence_span"))
    if not poem.get("title") or not poem.get("author") or evidence not in lines:
        findings.append(_finding(item_id, "poetry_source_incomplete", "古诗题必须登记题名、作者、完整采用诗句和逐字证据。"))
    if item.get("provenance", {}).get("copyright_status") != "public_domain":
        findings.append(_finding(item_id, "poetry_rights_unresolved", "采用古诗必须明确公共领域或获得授权。"))
    public_ref = item.get("provenance", {}).get("public_domain_reference", {})
    if not isinstance(public_ref, dict) or _text(public_ref.get("title")) != _text(poem.get("title")) or _text(public_ref.get("author")) != _text(poem.get("author")) or not _text(public_ref.get("source_locator")):
        findings.append(_finding(item_id, "poetry_source_reference_missing", "公共领域诗文必须用题名、作者和 source_locator 绑定独立来源记录。"))
    return findings


def _audit_offscreen(item: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    safety = item.get("safety", {})
    findings: list[dict[str, str]] = []
    required_true = ("guardian_required", "no_media_collection")
    for field in required_true:
        if safety.get(field) is not True:
            findings.append(_finding(item_id, f"{field}_required", f"屏外儿童行动必须明确 {field}=true。"))
    if not _text(safety.get("allowed_place")) or not _text(safety.get("stop_condition")):
        findings.append(_finding(item_id, "offscreen_safety_incomplete", "必须写明允许地点与停止条件。"))
    if safety.get("policy_id") not in ALLOWED_SAFETY_POLICIES:
        findings.append(_finding(item_id, "offscreen_safety_policy_invalid", "屏外行动必须绑定已审的保守 safety policy，不能用任意非空字符串代替。"))
    if not isinstance(safety.get("hazards"), list) or not safety.get("hazards"):
        findings.append(_finding(item_id, "offscreen_hazards_missing", "屏外行动必须列出与场景匹配的 hazards。"))
    if not _text(item.get("oracle", {}).get("completion_evidence")):
        findings.append(_finding(item_id, "completion_evidence_missing", "屏外行动必须声明可观察的完成证据。"))
    rubric = item.get("interaction_contract", {}).get("observable_rubric", [])
    if item.get("content_role") == "structured_offscreen_expression" and not 2 <= len(rubric) <= 3:
        findings.append(_finding(item_id, "observable_rubric_invalid", "结构化屏外表达必须登记 2–3 个观察标准。"))
    return findings


AUDITORS = {
    "arithmetic": _audit_arithmetic,
    "meaning_mapping": _audit_mapping,
    "classification": _audit_classification,
    "sequence": _audit_sequence,
    "reading_evidence": _audit_reading,
    "poetry_mapping": _audit_poetry,
    "offscreen_action": _audit_offscreen,
    "counting": _audit_counting,
    "ordered_tokens": _audit_ordered_tokens,
    "short_response": _audit_short_response,
}


def audit_content_truth_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """审计一组内容真值合同；只返回确定性结果，不修改输入。"""
    findings: list[dict[str, str]] = []
    contract_version = bundle.get("contract_version")
    if contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        findings.append(_finding("$bundle", "contract_version_invalid", f"contract_version 必须为 {sorted(SUPPORTED_CONTRACT_VERSIONS)} 之一。"))
    items = bundle.get("items", [])
    if not isinstance(items, list) or not items:
        findings.append(_finding("$bundle", "items_missing", "内容真值包至少包含一项内容。"))
        items = []
    if not _text(bundle.get("authored_by")):
        findings.append(_finding("$bundle", "author_missing", "真值包必须登记 authored_by。"))
    item_ids = [_text(item.get("item_id")) for item in items if isinstance(item, dict)]
    for item_id, count in Counter(item_ids).items():
        if not item_id:
            findings.append(_finding("$bundle", "item_id_missing", "每项内容必须有非空 item_id。"))
        elif count > 1:
            findings.append(_finding(item_id, "item_id_duplicate", "item_id 必须唯一。"))
    for item in items:
        if not isinstance(item, dict):
            findings.append(_finding("$bundle", "item_invalid", "items 中每项必须是对象。"))
            continue
        item_id = _text(item.get("item_id")) or "$unknown"
        findings.extend(_audit_common(item, item_id, _text(bundle.get("authored_by"))))
        if contract_version in {"double6_content_truth_v2", CONTRACT_VERSION}:
            findings.extend(_audit_v2_contract(item, item_id))
        if contract_version == CONTRACT_VERSION:
            findings.extend(_audit_v3_contract(item, item_id, _text(bundle.get("stage_id"))))
        auditor = AUDITORS.get(item.get("kind"))
        if auditor:
            findings.extend(auditor(item, item_id))
    blocking = [row for row in findings if row["severity"] == "blocking"]
    major = [row for row in findings if row["severity"] == "major"]
    return {
        "contract_version": contract_version,
        "status": "pass" if not blocking and not major else "fail",
        "item_count": len(items),
        "finding_count": len(findings),
        "blocking_count": len(blocking),
        "major_count": len(major),
        "findings": findings,
    }


def assert_content_truth_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """通过时返回回执；失败时抛出 ValueError，供发布门 fail closed。"""
    receipt = audit_content_truth_bundle(bundle)
    if receipt["status"] != "pass":
        summary = "; ".join(f"{row['item_id']}:{row['code']}" for row in receipt["findings"][:8])
        raise ValueError(f"内容真值审计失败：{summary}")
    return receipt
