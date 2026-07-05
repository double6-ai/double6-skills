from __future__ import annotations

import json
import argparse
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import translation_api_probe  # noqa: E402
import translation_compat_proxy  # noqa: E402
import layout_role_policy  # noqa: E402
import policy_utils  # noqa: E402
import latex_direct_runtime  # noqa: E402
import visible_residue_audit  # noqa: E402
import visible_residue_repair  # noqa: E402
import delivery_gate_runtime  # noqa: E402
import metadata_label_repair_runtime  # noqa: E402
import pdf_translation_artifacts_runtime  # noqa: E402
import pdf_translation_runtime  # noqa: E402
import preflight_runtime  # noqa: E402
from translation_compat_proxy import ProxyConfig  # noqa: E402


class _FakeHTTPResponse:
    def __init__(self, content: str, status: int = 200):
        self.content = content
        self.status = status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": self.content,
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")


class TranslationApiProbeTests(unittest.TestCase):
    def _require_fitz(self):
        try:
            import fitz  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"PyMuPDF unavailable: {exc}")
        return fitz

    def _write_text_pdf(self, path: Path, lines: list[tuple[float, float, str]]) -> None:
        fitz = self._require_fitz()
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        for x, y, text in lines:
            page.insert_text((x, y), text, fontsize=10)
        doc.save(path)
        doc.close()

    def test_ordinary_echo_is_classified_as_translation_failure(self) -> None:
        case = translation_api_probe.make_case(
            "Large language models can solve complex tasks by composing skills.",
            expected_behavior="translate",
        )

        metrics = translation_api_probe.classify_probe_result(case, case["source"])

        self.assertTrue(metrics["same_as_input"])
        self.assertTrue(metrics["non_chinese"])
        self.assertTrue(metrics["ordinary_failure"])

    def test_protected_only_echo_is_not_ordinary_failure(self) -> None:
        case = translation_api_probe.make_case(
            "https://arxiv.org/abs/2602.08234",
            expected_behavior="protect",
        )

        metrics = translation_api_probe.classify_probe_result(case, case["source"])

        self.assertFalse(metrics["same_as_input"])
        self.assertFalse(metrics["ordinary_failure"])
        self.assertFalse(metrics["protected_mistranslation"])

    def test_placeholder_and_style_tag_breaks_are_detected(self) -> None:
        case = translation_api_probe.make_case(
            "<style id='1'>The agent stores {v1} in memory.</style>",
            expected_behavior="translate",
        )

        metrics = translation_api_probe.classify_probe_result(case, "该智能体把技能库存入记忆。")

        self.assertTrue(metrics["placeholder_break"])
        self.assertTrue(metrics["style_tag_break"])
        self.assertTrue(metrics["protected_span_break"])

    def test_task_explanation_is_detected(self) -> None:
        case = translation_api_probe.make_case(
            "The method improves sample efficiency.",
            expected_behavior="translate",
        )

        metrics = translation_api_probe.classify_probe_result(
            case,
            "We need to translate the given text into Chinese.",
        )

        self.assertTrue(metrics["task_explanation"])
        self.assertTrue(metrics["ordinary_failure"])

    def test_provider_alias_infers_base_url_and_api_key(self) -> None:
        with mock.patch.dict("os.environ", {"DASHSCOPE_API_KEY": "dashscope-key"}, clear=True):
            base_url = pdf_translation_runtime.resolve_base_url("qwen", "")
            api_key = pdf_translation_runtime.resolve_api_key("qwen", "")
            inference = pdf_translation_runtime.resolve_base_url_inference("qwen", "")

        self.assertEqual("https://dashscope.aliyuncs.com/compatible-mode/v1", base_url)
        self.assertEqual("dashscope-key", api_key)
        self.assertEqual("provider", inference["source"])

    def test_generic_api_key_does_not_infer_base_url_without_provider(self) -> None:
        with mock.patch.dict("os.environ", {"LOCAL_TRANSLATION_API_KEY": "generic-key"}, clear=True):
            base_url = pdf_translation_runtime.resolve_base_url("", "")
            api_key = pdf_translation_runtime.resolve_api_key("", "")
            inference = pdf_translation_runtime.resolve_base_url_inference("", "")

        self.assertEqual("", base_url)
        self.assertEqual("generic-key", api_key)
        self.assertIsNone(inference)

    def test_multiple_provider_keys_do_not_infer_base_url_without_provider(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "deepseek-key", "OPENAI_API_KEY": "openai-key"},
            clear=True,
        ):
            base_url = pdf_translation_runtime.resolve_base_url("", "")
            inference = pdf_translation_runtime.resolve_base_url_inference("", "")

        self.assertEqual("", base_url)
        self.assertIsNone(inference)

    def test_preflight_models_404_falls_back_to_chat_probe(self) -> None:
        args = argparse.Namespace(
            base_url="https://provider.example/v1",
            model="model-name",
            api_key="test-key",
            endpoint_timeout=5,
        )
        models_error = urllib.error.HTTPError(
            "https://provider.example/v1/models",
            404,
            "not found",
            hdrs=None,
            fp=None,
        )

        with mock.patch(
            "preflight_runtime.urlopen",
            side_effect=[models_error, _FakeHTTPResponse("OK")],
        ) as urlopen_mock:
            result = preflight_runtime.check_endpoint(args)

        self.assertEqual("pass", result["status"])
        self.assertEqual(
            "https://provider.example/v1/chat/completions",
            urlopen_mock.call_args_list[1].args[0].full_url,
        )
        self.assertEqual(404, result["details"]["fallback_from"]["status"])

    def test_json_object_response_format_is_not_rewritten(self) -> None:
        payload = {
            "model": "deepseek-v4-flash",
            "messages": [],
            "response_format": {"type": "json_object"},
        }

        normalized = translation_compat_proxy.normalize_proxy_payload_for_upstream(payload)

        self.assertEqual({"type": "json_object"}, normalized["response_format"])
        self.assertNotEqual("json_schema", normalized["response_format"]["type"])

    def test_thinking_field_is_preserved_by_payload_normalization(self) -> None:
        payload = {
            "model": "deepseek-v4-flash",
            "messages": [],
            "thinking": {"type": "disabled"},
        }

        normalized = translation_compat_proxy.normalize_proxy_payload_for_upstream(payload)

        self.assertEqual({"type": "disabled"}, normalized["thinking"])

    def test_deepseek_translation_defaults_disable_thinking(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        payload = {"model": config.model, "messages": []}

        normalized = translation_compat_proxy.apply_translation_request_defaults(payload, config)

        self.assertEqual({"type": "disabled"}, normalized["thinking"])

    def test_probe_can_omit_thinking_for_ab_comparison(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        config.stats["_probe_thinking"] = "omit"
        payload = {"model": config.model, "messages": [], "thinking": {"type": "enabled"}}

        normalized = translation_compat_proxy.apply_translation_request_defaults(payload, config)

        self.assertNotIn("thinking", normalized)

    def test_babeldoc_placeholders_are_protected_values(self) -> None:
        source = "We use {v1} for the skill library and {v2} for the policy."

        missing = policy_utils.missing_protected_values(source, "我们使用技能库和策略。")
        repaired = policy_utils.restore_missing_protected_values(source, "我们使用技能库和策略。")

        self.assertEqual(["{v1}", "{v2}"], missing)
        self.assertIn("{v1}", repaired)
        self.assertIn("{v2}", repaired)

    def test_strip_rich_text_tags_preserves_placeholders(self) -> None:
        value = translation_compat_proxy.layout_role_policy.strip_rich_text_tags(
            "<style id='1'>The policy uses {v1}.</style>"
        )

        self.assertEqual("The policy uses {v1}.", value)

    def test_probe_task_matrix_respects_max_results(self) -> None:
        cases = [
            translation_api_probe.make_case("The first fragment needs translation.", case_id="c1"),
            translation_api_probe.make_case("The second fragment needs translation.", case_id="c2"),
        ]

        tasks = translation_api_probe.build_probe_tasks(
            cases,
            call_paths=["direct", "proxy"],
            prompt_variants=["current", "force_chinese_retry"],
            temperatures=[0.1, 0.3],
            max_results=5,
        )

        self.assertEqual(5, len(tasks))
        self.assertEqual("direct", tasks[0]["call_path"])
        self.assertEqual("current", tasks[0]["prompt_variant"])

    def test_mock_direct_api_echo_response_is_classified(self) -> None:
        case = translation_api_probe.make_case(
            "The agent learns reusable skills from sparse rewards.",
            expected_behavior="translate",
        )
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")

        with mock.patch("translation_api_probe.urllib.request.urlopen", return_value=_FakeHTTPResponse(case["source"])):
            output, extra = translation_api_probe.call_direct(case, "current", 0.1, config, 5)

        metrics = translation_api_probe.classify_probe_result(case, output)

        self.assertTrue(extra["temperature_applied"])
        self.assertEqual(case["source"], output)
        self.assertTrue(metrics["same_as_input"])
        self.assertTrue(metrics["ordinary_failure"])

    def test_plain_translation_retries_transient_network_error(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")

        with mock.patch(
            "translation_compat_proxy.urllib.request.urlopen",
            side_effect=[urllib.error.URLError("temporary eof"), _FakeHTTPResponse("智能体学习可复用技能。")],
        ):
            output = translation_compat_proxy._request_plain_translation(
                "The agent learns reusable skills.",
                config,
                policy_prompt="",
            )

        self.assertEqual("智能体学习可复用技能。", output)
        self.assertEqual(1, config.stats["plain_upstream_network_retry"])

    def test_missing_protected_value_does_not_count_as_same_input_retry(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        source = "Code is available at https://github.com/aiming-lab/SkillRL."

        with mock.patch(
            "translation_compat_proxy._request_plain_translation",
            side_effect=["代码可在此处获取。", "代码可在此处获取。"],
        ):
            output = translation_compat_proxy.call_plain_translation(source, config)

        self.assertIn("https://github.com/aiming-lab/SkillRL", output)
        self.assertNotIn("same_as_input_retry", config.stats)
        self.assertEqual(1, config.stats["protected_value_retry"])
        self.assertEqual(1, config.stats["protected_value_retry_failed"])

    def test_quality_retry_uses_reflection_context(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        config.stats["_quality_retry_attempts"] = 2
        source = "Usually, regulation targets the control of various emissions before implementing controls."
        calls: list[dict[str, object]] = []

        def fake_request(*args, **kwargs):
            calls.append(dict(kwargs))
            return source if len(calls) == 1 else "通常，监管目标是在实施控制前控制各种排放。"

        with mock.patch("translation_compat_proxy._request_plain_translation", side_effect=fake_request):
            output = translation_compat_proxy.call_plain_translation(source, config)

        self.assertEqual("通常，监管目标是在实施控制前控制各种排放。", output)
        self.assertEqual(2, len(calls))
        self.assertEqual(1, calls[1]["retry_round"])
        self.assertIn("same_as_input_or_non_chinese", calls[1]["failure_reasons"])
        self.assertEqual(source, calls[1]["previous_output"])
        self.assertEqual(1, config.stats["quality_retry_attempt"])
        self.assertEqual(1, config.stats["same_as_input_retry_success"])

    def test_quality_retry_has_max_attempts(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        config.stats["_quality_retry_attempts"] = 1
        source = "The method stores raw trajectories in memory for future tasks."

        with mock.patch("translation_compat_proxy._request_plain_translation", side_effect=[source, source, "该输出不应被调用。"]) as mocked:
            output = translation_compat_proxy.call_plain_translation(source, config)

        self.assertEqual(source, output)
        self.assertEqual(2, mocked.call_count)
        self.assertEqual(1, config.stats["quality_retry_attempt"])
        self.assertEqual(1, config.stats["same_as_input_retry_failed"])

    def test_prompt_leak_is_discarded_after_retry_exhaustion(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        config.stats["_quality_retry_attempts"] = 1
        source = "The aerosol burden changes after emissions are reduced."
        leaked = "以下是根据您的要求翻译的学术PDF文本。不要输出解释。"

        with mock.patch("translation_compat_proxy._request_plain_translation", side_effect=[leaked, leaked]):
            output = translation_compat_proxy.call_plain_translation(source, config)

        self.assertEqual(source, output)
        self.assertEqual(1, config.stats["prompt_leak_discarded"])
        self.assertEqual(1, config.stats["same_as_input_retry_failed"])

    def test_backend_retry_failures_loader(self) -> None:
        payload = {
            "failures": [
                {
                    "failure_type": "same_as_input_after_retry",
                    "source_snippet": "The abstract remains untranslated.",
                    "output_snippet": "The abstract remains untranslated.",
                    "classification": "ordinary_same_as_input",
                    "layout_role": "body_prose",
                    "paragraph_debug_id": "p1",
                }
            ]
        }
        path = Path("backend_retry_failures.json")

        cases = translation_api_probe.load_backend_retry_failure_cases(path, payload)

        self.assertEqual(1, len(cases))
        self.assertEqual("translate", cases[0]["expected_behavior"])
        self.assertEqual("body_prose", cases[0]["role"])

    def test_failure_dir_loader_collects_common_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend_retry_failures.json").write_text(
                json.dumps(
                    {
                        "failures": [
                            {
                                "source_snippet": "The abstract remains untranslated.",
                                "output_snippet": "The abstract remains untranslated.",
                                "classification": "ordinary_same_as_input",
                                "layout_role": "body_prose",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "visible_residue_audit.json").write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "failure_type": "translated_but_source_visible",
                                "visible_text": "Usually, regulation targets the control of emissions.",
                                "layout_role": "body_prose",
                                "page": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            cases = translation_api_probe.load_failure_dir_cases(root)

        self.assertEqual(2, len(cases))
        self.assertTrue(all(case["expected_behavior"] == "translate" for case in cases))

    def test_strict_reflection_prompt_includes_previous_bad_output(self) -> None:
        case = translation_api_probe.make_case(
            "The aerosol burden changes after emissions are reduced.",
            source_output="以下是根据您的要求翻译的学术PDF文本。不要输出解释。",
            metadata={"failure_type": "task_explanation"},
            expected_behavior="translate",
        )

        prompt = translation_api_probe.build_prompt(case["source"], case, "strict_reflection")

        self.assertIn("Previous bad output excerpt", prompt)
        self.assertIn("task_explanation", prompt)
        self.assertIn("Do not repeat the previous bad output", prompt)

    def test_references_mode_keeps_body_prose_fragments_translatable(self) -> None:
        role = layout_role_policy.classify_babeldoc_item(
            {
                "id": 1,
                "input": (
                    "burden. Usually, regulation targets the control of various kinds of emissions such as SOA "
                    "precursors before implementing emission controls."
                ),
            },
            references_mode=True,
        )

        self.assertEqual("body_prose", role)

    def test_references_mode_keeps_real_reference_entries(self) -> None:
        role = layout_role_policy.classify_babeldoc_item(
            {
                "id": 1,
                "input": (
                    "Adams, P. J., Seinfeld, J. H., Koch, D., Mickley, L., and Jacob, D.: "
                    "General circulation model assessment, J. Geophys. Res.-Atmos., 106, 1097-1111, 2001."
                ),
            },
            references_mode=True,
        )

        self.assertEqual("references_entry", role)

    def test_inline_citation_body_sentence_is_not_reference_entry(self) -> None:
        role = layout_role_policy.classify_babeldoc_item(
            {
                "id": 1,
                "input": (
                    "In another study Weber et al. (2007) used measurements of WSOC as an estimate of SOA mass. "
                    "They found high correlations between WSOC and anthropogenic emissions."
                ),
            },
            references_mode=True,
        )

        self.assertEqual("body_prose", role)

    def test_latex_direct_dependency_failure_is_classified(self) -> None:
        stage = latex_direct_runtime.infer_latex_direct_failure_stage(
            "ModuleNotFoundError: No module named 'pdf2zh_skill'",
            {"status": "error", "returncode": 1},
        )

        self.assertEqual("dependency", stage["failure_stage"])
        self.assertEqual("not_started", stage["api_stage_status"])
        self.assertEqual("not_started", stage["compile_stage_status"])

    def test_latex_direct_skips_when_external_skill_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "main.tex"
            source.write_text("\\section{Intro}\n", encoding="utf-8")
            args = argparse.Namespace(
                latex_render_mode="auto",
                latex_project_mode="in-place",
                translation_compat_proxy="off",
                base_url="https://api.deepseek.com",
                api_key="test-key",
                model="deepseek-v4-flash",
            )

            with mock.patch.dict("os.environ", {"PAPER_TRANSLATION_PDF2ZH_SKILL_PATH": str(root / "missing")}, clear=False):
                manifest = latex_direct_runtime.run_latex_direct_render(
                    args,
                    root / "paper.pdf",
                    root / "out",
                    source,
                    {},
                )

        self.assertEqual("skipped", manifest["status"])
        self.assertEqual("missing_external_pdf2zh_skill", manifest["reason"])
        self.assertEqual("dependency", manifest["failure_stage"])
        self.assertEqual("not_started", manifest["api_stage_status"])

    def test_metadata_references_word_in_body_does_not_clone_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = Path(tmpdir) / "paper.pdf"
            self._write_text_pdf(
                pdf,
                [
                    (50, 80, "1. Introduction"),
                    (50, 120, "The method stores raw trajectories during sampling to serve as references"),
                    (50, 136, "for similar future tasks without treating this phrase as a bibliography heading."),
                ],
            )

            plan = metadata_label_repair_runtime.build_repair_plan(pdf)

        reference_clones = [
            action
            for action in plan.get("actions", [])
            if action.get("kind") == "source_region_clone" and action.get("role") == "references_region"
        ]
        self.assertEqual([], reference_clones)

    def test_metadata_standalone_references_heading_clones_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf = Path(tmpdir) / "paper.pdf"
            self._write_text_pdf(
                pdf,
                [
                    (50, 80, "References"),
                    (50, 120, "Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K., and Yao, S. Reflexion. 2023."),
                    (50, 136, "Zhao, A., Huang, D., Xu, Q., Lin, M., Liu, Y.-J., and Huang, G. Expel. 2024."),
                ],
            )

            plan = metadata_label_repair_runtime.build_repair_plan(pdf)

        reference_clones = [
            action
            for action in plan.get("actions", [])
            if action.get("kind") == "source_region_clone" and action.get("role") == "references_region"
        ]
        self.assertEqual(1, len(reference_clones))
        self.assertEqual(1, reference_clones[0]["page"])

    def test_metadata_unsafe_clone_is_not_selected_for_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_pdf = root / "source.pdf"
            translated_pdf = root / "translated.pdf"
            lines = [
                (50, 80, "1. Introduction"),
                (50, 120, "Large language model agents operate in isolation and fail to learn from past experiences."),
                (50, 136, "These methods store trajectories as references for similar future tasks."),
            ]
            self._write_text_pdf(source_pdf, lines)
            self._write_text_pdf(translated_pdf, lines)
            plan = {
                "version": 1,
                "status": "ok",
                "actions": [
                    {
                        "kind": "source_region_clone",
                        "role": "references_region",
                        "page": 1,
                        "source_bbox": [30.0, 70.0, 582.0, 744.0],
                        "target_bbox": [30.0, 70.0, 582.0, 744.0],
                        "redact_before_clone": True,
                    }
                ],
                "action_count": 1,
            }

            with mock.patch("metadata_label_repair_runtime.build_repair_plan", return_value=plan):
                manifest = metadata_label_repair_runtime.apply_metadata_label_repair(
                    source_pdf=source_pdf,
                    translated_pdf=translated_pdf,
                    output_dir=root,
                    mode="auto",
                )

        self.assertEqual("unsafe_clone_skipped", manifest["reason"])
        self.assertEqual(1, manifest["unsafe_clone_skipped_count"])
        self.assertFalse(manifest["selected_as_delivery"])
        self.assertEqual("not_selected_for_delivery", manifest["delivery_status"])

    def test_rejected_visible_residue_candidate_pdf_is_cleaned_from_delivery_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_pdf = root / "paper.pdf"
            mono_pdf = root / "candidate.mono.pdf"
            bilingual_pdf = root / "candidate.bilingual.pdf"
            rejected_pdf = root / "paper.metadata-label-repaired.zh.mono.visible-residue-repaired.zh.pdf"
            self._write_text_pdf(input_pdf, [(50, 80, "source")])
            self._write_text_pdf(mono_pdf, [(50, 80, "译文")])
            self._write_text_pdf(bilingual_pdf, [(50, 80, "source | 译文")])
            self._write_text_pdf(rejected_pdf, [(50, 80, "failed candidate")])

            delivery = pdf_translation_artifacts_runtime.finalize_delivery_pdf_outputs(
                input_pdf,
                root,
                {"mono_pdf": str(mono_pdf), "standard_bilingual_pdf": str(bilingual_pdf)},
                candidate_pdfs=[str(rejected_pdf)],
            )

            self.assertFalse(rejected_pdf.exists())
            self.assertIn(str(rejected_pdf), delivery["removed_pdfs"])
            self.assertTrue((root / "paper.zh.pdf").exists())
            self.assertTrue((root / "paper.bilingual.pdf").exists())

    def test_visible_residue_detects_translated_but_source_visible(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            pymupdf_audit={
                "tracking_translated_but_source_visible": [
                    {
                        "rule": "tracking_translated_but_source_visible",
                        "page": 1,
                        "visible_text": "We argue that these approaches miss a crucial insight.",
                        "tracking_source": "We argue that these approaches miss a crucial insight.",
                        "tracking_output": "我们认为这些方法忽略了一个关键洞见。",
                        "layout_role": "body_prose",
                        "bbox": [100, 200, 300, 220],
                    }
                ]
            }
        )

        self.assertEqual("partial", audit["status"])
        self.assertEqual(1, audit["ordinary_body_critical_count"])
        self.assertEqual("translated_but_source_visible", audit["findings"][0]["failure_type"])
        self.assertTrue(audit["findings"][0]["delivery_blocking"])

    def test_visible_residue_detects_visible_text_not_tracked(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            poppler_audit={
                "visible_text_not_tracked": [
                    {
                        "rule": "visible_text_not_tracked",
                        "severity": "warn",
                        "page": 2,
                        "text": "The method stores raw trajectories in memory.",
                        "layout_role": "body_prose",
                    }
                ]
            }
        )

        self.assertEqual("warn", audit["status"])
        self.assertEqual("visible_text_not_tracked", audit["findings"][0]["failure_type"])
        self.assertEqual("paragraph_finder_required", audit["findings"][0]["repair_target"])

    def test_text_layer_residue_blocks_non_critical_body_page(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            poppler_audit={
                "translated_lines": [
                    {"page": 2, "text": "2 人为活动影响BSOA的机制", "bbox": [300, 80, 520, 90]},
                    {"page": 2, "text": "在大气中，生物源挥发性有机化合物分子发生反应并形成气溶胶。", "bbox": [300, 100, 520, 112]},
                    {"page": 2, "text": "Usually, regulation targets the control of various emissions", "bbox": [40, 100, 250, 112]},
                    {"page": 2, "text": "Before implementing emission controls, chemistry models are used", "bbox": [40, 114, 250, 126]},
                    {"page": 2, "text": "to assess the effect of changes in emissions on the burden", "bbox": [40, 128, 250, 140]},
                    {"page": 2, "text": "volatile compounds which oxidise and partition to the phase", "bbox": [40, 142, 250, 154]},
                    {"page": 2, "text": "organic aerosol has commonly been classified in different groups", "bbox": [40, 156, 250, 168]},
                    {"page": 2, "text": "these definitions depend on the measurement techniques applied", "bbox": [40, 170, 250, 182]},
                ]
            }
        )

        gates = delivery_gate_runtime.build_delivery_gates(
            visual_report={"status": "ok", "findings": []},
            backend_quality={"status": "ok"},
            rerender_candidates={"status": "ok", "candidates": []},
            translated_text="正文",
            strict=False,
            pipeline_status="ok",
            has_translated_pdf=True,
            visible_residue_audit=audit,
        )
        gate_by_name = {item["name"]: item for item in gates["gates"]}

        self.assertEqual("partial", audit["status"])
        self.assertEqual("translated_but_source_visible", audit["findings"][0]["failure_type"])
        self.assertTrue(audit["findings"][0]["delivery_blocking"])
        self.assertEqual("blocking", gate_by_name["critical_page_visible_residue"]["status"])

    def test_text_layer_prompt_leak_blocks_delivery(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            poppler_audit={
                "translated_lines": [
                    {"page": 16, "text": "以下是根据您的要求翻译的学术PDF文本。已保留占位符。", "bbox": [40, 100, 300, 112]},
                ]
            }
        )

        self.assertEqual("partial", audit["status"])
        self.assertEqual("prompt_leak", audit["findings"][0]["failure_type"])
        self.assertEqual("translation_output_filter_required", audit["findings"][0]["repair_target"])
        self.assertTrue(audit["findings"][0]["delivery_blocking"])

    def test_visible_residue_protected_visible_text_is_ignored(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            pymupdf_audit={
                "visible_text_not_tracked": [
                    {"rule": "visible_text_not_tracked", "page": 1, "text": "https://github.com/aiming-lab/SkillRL"},
                    {"rule": "visible_text_not_tracked", "page": 1, "text": "arXiv:2602.08234v1 [cs.LG] 9 Feb 2026"},
                    {"rule": "visible_text_not_tracked", "page": 1, "text": "UNC-Chapel Hill University of Chicago"},
                ]
            }
        )

        self.assertEqual("ok", audit["status"])
        self.assertEqual([], audit["findings"])

    def test_visible_residue_style_tag_blocks_critical_page_gate(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            visual_report={
                "findings": [
                    {
                        "rule": "visible_style_tag_leak",
                        "severity": "warn",
                        "page": 1,
                        "evidence": "ps://github.com/aiming-lab/SkillRL</style",
                        "layout_role": "main_text",
                    }
                ]
            }
        )

        gates = delivery_gate_runtime.build_delivery_gates(
            visual_report={"status": "ok", "findings": []},
            backend_quality={"status": "ok"},
            rerender_candidates={"status": "ok", "candidates": []},
            translated_text="摘要",
            strict=True,
            pipeline_status="ok",
            has_translated_pdf=True,
            visible_residue_audit=audit,
        )
        gate_by_name = {item["name"]: item for item in gates["gates"]}

        self.assertEqual("style_tag_leak", audit["findings"][0]["failure_type"])
        self.assertEqual("blocking", gate_by_name["critical_page_visible_residue"]["status"])

    def test_visible_residue_repair_plan_and_fallback_markdown(self) -> None:
        audit = visible_residue_audit.build_visible_residue_audit(
            pymupdf_audit={
                "tracking_translated_but_source_visible": [
                    {
                        "rule": "tracking_translated_but_source_visible",
                        "page": 1,
                        "visible_text": "Current LLM agents operate in isolation.",
                        "tracking_output": "当前 LLM 智能体孤立运行。",
                        "layout_role": "body_prose",
                    }
                ]
            }
        )

        plan = visible_residue_audit.build_pdf_backend_repair_plan(audit)
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback = visible_residue_audit.write_readable_fallback_markdown(audit, Path(tmpdir))
            markdown = Path(fallback["markdown"]).read_text(encoding="utf-8")

        self.assertEqual("review_required", plan["status"])
        self.assertEqual("babeldoc_writeback_clear_source", plan["tasks"][0]["repair_target"])
        self.assertIn("当前 LLM 智能体孤立运行。", markdown)

    def test_translation_proxy_ledger_records_json_batch_items(self) -> None:
        config = ProxyConfig(model="deepseek-v4-flash", upstream_base_url="https://api.deepseek.com", api_key="test-key")
        payload = {"model": config.model}
        items = [{"id": 1, "input": "1. Introduction", "layout_label": "title"}]

        translation_compat_proxy.synthesize_babeldoc_json_response(payload, items, config)

        ledger = config.stats["_translation_ledger"]
        self.assertEqual(1, len(ledger))
        self.assertEqual("1. Introduction", ledger[0]["source"])
        self.assertEqual("1 引言", ledger[0]["output"])
        self.assertEqual("json_batch", ledger[0]["path"])
        self.assertNotIn("api_key", ledger[0])

    def test_ocr_residue_matches_proxy_ledger_and_poppler_bbox(self) -> None:
        findings = [
            {
                "failure_type": "translated_but_source_visible",
                "rule": "ocr_critical_page_english_residue",
                "page": 1,
                "bbox": [50, 100, 260, 118],
                "visible_text": "Current LLM agents operate in isolation.",
                "layout_role": "body_prose",
                "critical_page": True,
                "ordinary_body_residue": True,
                "delivery_blocking": True,
                "evidence_source": "critical_page_ocr",
            }
        ]
        ledger = {
            "entries": [
                {
                    "source": "Current LLM agents operate in isolation, failing to learn from past experiences.",
                    "output": "当前 LLM 智能体孤立运行，无法从过往经验中学习。",
                    "layout_role": "body_prose",
                    "layout_label": "plain text",
                }
            ]
        }
        poppler = {
            "source_lines": [
                {
                    "page": 1,
                    "text": "Current LLM agents operate in isolation.",
                    "bbox": [52.0, 99.0, 280.0, 116.0],
                }
            ]
        }

        enriched = visible_residue_audit.enrich_visible_residue_findings(
            findings,
            proxy_ledger=ledger,
            poppler_audit=poppler,
        )

        self.assertEqual("translated_but_source_visible", enriched[0]["failure_type"])
        self.assertIn("当前 LLM 智能体", enriched[0]["tracking_output"])
        self.assertEqual([52.0, 99.0, 280.0, 116.0], enriched[0]["source_bbox"])
        self.assertGreaterEqual(enriched[0]["match_confidence"], 0.52)

    def test_unmatched_ocr_residue_requires_paragraph_finder_not_auto_repair(self) -> None:
        findings = [
            {
                "failure_type": "translated_but_source_visible",
                "rule": "ocr_critical_page_english_residue",
                "page": 1,
                "bbox": [50, 100, 260, 118],
                "visible_text": "This visible line was never tracked by the translation backend.",
                "layout_role": "body_prose",
                "critical_page": True,
                "ordinary_body_residue": True,
                "delivery_blocking": True,
                "evidence_source": "critical_page_ocr",
            }
        ]

        enriched = visible_residue_audit.enrich_visible_residue_findings(findings, proxy_ledger={"entries": []})
        repair_items, rejected = visible_residue_repair.candidate_items({"findings": enriched})

        self.assertEqual("visible_text_not_tracked", enriched[0]["failure_type"])
        self.assertEqual("paragraph_finder_required", enriched[0]["repair_target"])
        self.assertEqual([], repair_items)
        self.assertEqual("not_translated_but_source_visible", rejected[0]["reason"])

    def test_visible_residue_repair_rejects_style_tag_and_missing_output(self) -> None:
        audit = {
            "findings": [
                {
                    "failure_type": "style_tag_leak",
                    "page": 1,
                    "visible_text": "ps://github.com/aiming-lab/SkillRL</style",
                    "layout_role": "main_text",
                    "critical_page": True,
                    "ordinary_body_residue": False,
                },
                {
                    "failure_type": "translated_but_source_visible",
                    "page": 1,
                    "visible_text": "Current LLM agents operate in isolation.",
                    "layout_role": "body_prose",
                    "critical_page": True,
                    "ordinary_body_residue": True,
                    "bbox": [50, 100, 260, 118],
                    "tracking_output": "",
                },
            ]
        }

        repair_items, rejected = visible_residue_repair.candidate_items(audit)

        self.assertEqual([], repair_items)
        self.assertEqual(["not_translated_but_source_visible", "missing_chinese_tracking_output"], [item["reason"] for item in rejected])

    def test_repair_candidate_rejected_does_not_select_delivery_pdf(self) -> None:
        try:
            import fitz  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"PyMuPDF unavailable: {exc}")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf = root / "input.pdf"
            doc = fitz.open()
            page = doc.new_page(width=300, height=200)
            page.insert_text((50, 100), "Current LLM agents operate in isolation.")
            doc.save(pdf)
            doc.close()
            audit = {
                "findings": [
                    {
                        "failure_type": "translated_but_source_visible",
                        "page": 1,
                        "visible_text": "Current LLM agents operate in isolation.",
                        "layout_role": "body_prose",
                        "critical_page": True,
                        "ordinary_body_residue": True,
                        "bbox": [50, 90, 260, 112],
                        "tracking_output": "",
                    }
                ]
            }

            manifest = visible_residue_repair.apply_visible_residue_repair(
                audit=audit,
                translated_pdf=pdf,
                source_pdf=pdf,
                output_dir=root,
                mode="auto",
            )

        self.assertEqual("rejected", manifest["status"])
        self.assertFalse(manifest["selected_as_delivery"])


if __name__ == "__main__":
    unittest.main()
