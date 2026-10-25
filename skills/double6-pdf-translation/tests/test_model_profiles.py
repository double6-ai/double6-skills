"""智谱 coding plan 档案：补默认模型，不覆盖已经写明的模型。"""
from __future__ import annotations

import os
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from model_profiles import apply_model_profile, load_model_profiles, request_concurrency_from_env
import chunked_workflow as chunked
import paper_translation_workflow as workflow
import pdf_translation_cli as cli
import pdf_translation_commands as commands


CODING_URL = "https://open.bigmodel.cn/api/coding/paas/v4"


def test_default_profile_is_glm_5_3_flash_on_the_coding_surface():
    data = load_model_profiles()
    args = Namespace(model=None, base_url=None, api_key=None, temperature=0.7, openai_reasoning_effort="none")
    env = {}
    assert apply_model_profile(args, env, data) == "glm-coding"
    assert args.model == "glm-5.3-flash"
    assert args.base_url == CODING_URL
    assert args.thinking == "enabled"
    assert args.openai_reasoning_effort == "low"
    assert args.local_max_concurrency == 8
    assert "/api/paas/v4" not in args.base_url
    assert env == {}


def test_explicit_model_and_endpoint_stay():
    args = Namespace(model="hy-mt2-1.8b", base_url="http://127.0.0.1:1234/v1", api_key=None,
                     temperature=0.2, openai_reasoning_effort="high")
    env = {"GLM_API_KEY": "should-not-copy", "LOCAL_TRANSLATION_API_KEY": ""}
    assert apply_model_profile(args, env) is None
    assert args.model == "hy-mt2-1.8b"
    assert args.base_url == "http://127.0.0.1:1234/v1"
    assert args.temperature == 0.2
    assert args.openai_reasoning_effort == "high"
    assert not hasattr(args, "local_max_concurrency")
    assert "LOCAL_TRANSLATION_API_KEY" not in env or env["LOCAL_TRANSLATION_API_KEY"] == ""


def test_keeping_reasoning_does_not_disable_thinking():
    args = Namespace(model="glm-5.3-flash", base_url=CODING_URL, api_key="k", temperature=0.7,
                     openai_reasoning_effort="none", openai_send_reasoning_effort=False)
    apply_model_profile(args, {})
    assert not hasattr(args, "thinking")


def test_each_glm_uses_its_own_lowest_thinking_level():
    flash = Namespace(model="glm-5.3-flashx", base_url=CODING_URL, api_key="k", temperature=0.7,
                      openai_reasoning_effort="none", openai_send_reasoning_effort=True)
    apply_model_profile(flash, {"LOCAL_TRANSLATION_API_KEY": "k"})
    assert flash.thinking == "enabled" and flash.openai_reasoning_effort == "low"
    older = Namespace(model="glm-5.2", base_url=CODING_URL, api_key="k", temperature=0.7,
                      openai_reasoning_effort="none", openai_send_reasoning_effort=True)
    apply_model_profile(older, {"LOCAL_TRANSLATION_API_KEY": "k"})
    assert older.thinking == "enabled" and older.openai_reasoning_effort == "minimal"
    classic = Namespace(model="glm-4.5", base_url=CODING_URL, api_key="k", temperature=0.7,
                        openai_reasoning_effort="none", openai_send_reasoning_effort=True)
    apply_model_profile(classic, {"LOCAL_TRANSLATION_API_KEY": "k"})
    assert classic.thinking == "disabled" and classic.openai_reasoning_effort == "none"


def test_named_glm_model_gets_the_coding_endpoint_and_existing_key():
    args = Namespace(model="glm-5.3", base_url=None, api_key=None, temperature=0.7, openai_reasoning_effort="none")
    env = {"GLM_API_KEY": "glm-key"}
    apply_model_profile(args, env)
    assert args.model == "glm-5.3"
    assert args.thinking == "enabled"
    assert args.openai_reasoning_effort == "low"
    assert args.base_url == CODING_URL
    assert env["LOCAL_TRANSLATION_API_KEY"] == "glm-key"
    assert args.api_key == "glm-key"


def test_existing_translation_key_is_not_replaced():
    args = Namespace(model=None, base_url=None, api_key="already", temperature=0.7, openai_reasoning_effort="none")
    env = {"LOCAL_TRANSLATION_API_KEY": "local-key", "GLM_API_KEY": "glm-key"}
    apply_model_profile(args, env)
    assert env["LOCAL_TRANSLATION_API_KEY"] == "local-key"
    assert args.api_key == "already"


def test_translation_command_sends_reasoning_none_unless_turned_off():
    parser = cli.build_parser()
    default = parser.parse_args(["/tmp/in.pdf", "--model", "glm-5.3-flash", "--base-url", "http://127.0.0.1:9/v1"])
    command = commands.build_pdf2zh_command(default, Path("/tmp/out"))
    assert command[command.index("--openai-reasoning-effort") + 1] == "none"
    applied = Namespace(**vars(default))
    apply_model_profile(applied, {"LOCAL_TRANSLATION_API_KEY": "k"})
    lowered = commands.build_pdf2zh_command(applied, Path("/tmp/out"))
    assert lowered[lowered.index("--openai-reasoning-effort") + 1] == "low"
    assert "--openai-send-reasoning-effort" in command
    thinking = parser.parse_args([
        "/tmp/in.pdf", "--model", "glm-5.3-flash", "--base-url", "http://127.0.0.1:9/v1",
        "--no-openai-send-reasoning-effort",
    ])
    bare = commands.build_pdf2zh_command(thinking, Path("/tmp/out"))
    assert "--openai-send-reasoning-effort" not in bare
    assert "--openai-model" in bare and bare[bare.index("--openai-model") + 1] == "glm-5.3-flash"


def test_glm_sends_eight_requests_at_once_unless_a_number_was_given():
    saved = os.environ.pop("LOCAL_MODEL_MAX_CONCURRENCY", None)
    try:
        parser = cli.build_parser()
        default = parser.parse_args(["/tmp/in.pdf", "--model", "glm-5.3-flash", "--base-url", "http://127.0.0.1:9/v1"])
        assert default.local_max_concurrency is None
        before = commands.build_pdf2zh_command(default, Path("/tmp/out"))
        assert before[before.index("--qps") + 1] == "3"
        assert before[before.index("--pool-max-workers") + 1] == "3"
        applied = Namespace(**vars(default))
        apply_model_profile(applied, {"LOCAL_TRANSLATION_API_KEY": "k"})
        assert applied.local_max_concurrency == 8
        after = commands.build_pdf2zh_command(applied, Path("/tmp/out"))
        assert after[after.index("--qps") + 1] == "8"
        assert after[after.index("--pool-max-workers") + 1] == "8"
        explicit = parser.parse_args([
            "/tmp/in.pdf", "--model", "glm-5.3-flash", "--base-url", "http://127.0.0.1:9/v1",
            "--local-max-concurrency", "3",
        ])
        apply_model_profile(explicit, {"LOCAL_TRANSLATION_API_KEY": "k"})
        assert explicit.local_max_concurrency == 3
        local = parser.parse_args(["/tmp/in.pdf", "--model", "hy-mt2-1.8b", "--base-url", "http://127.0.0.1:9/v1"])
        apply_model_profile(local, {})
        assert local.local_max_concurrency is None
        local_command = commands.build_pdf2zh_command(local, Path("/tmp/out"))
        assert local_command[local_command.index("--qps") + 1] == "3"
        assert request_concurrency_from_env({}) is None
        assert request_concurrency_from_env({"LOCAL_MODEL_MAX_CONCURRENCY": "4"}) == 4
    finally:
        if saved is not None:
            os.environ["LOCAL_MODEL_MAX_CONCURRENCY"] = saved


def test_workflow_keeps_one_request_for_a_local_model():
    limits = {"per_job_seconds": 120}
    glm = Namespace(
        input=Path("/tmp/in.pdf"), output=Path("/tmp/out"), model=None, base_url=None,
        route="digital_pdf", smoke=False, target_language="zh", temperature=0.7,
        openai_reasoning_effort="none", resource_limits=limits,
    )
    apply_model_profile(glm, {})
    command = workflow.candidate_command(glm, {})
    assert command[command.index("--local-max-concurrency") + 1] == "8"
    local = Namespace(
        input=Path("/tmp/in.pdf"), output=Path("/tmp/out"), model="hy-mt2-1.8b",
        base_url="http://127.0.0.1:9/v1", route="digital_pdf", smoke=False, target_language="zh",
        temperature=0.2, openai_reasoning_effort="high", resource_limits=limits,
    )
    apply_model_profile(local, {})
    local_command = workflow.candidate_command(local, {})
    assert local_command[local_command.index("--local-max-concurrency") + 1] == "1"


def test_long_document_chunks_keep_the_profile_concurrency():
    captured = {}

    class FakeWorkflow:
        def dispatch(self, ns):
            captured["value"] = ns.local_max_concurrency
            return {"status": "candidate"}

        PreflightError = ValueError
        ResourceLimitError = ValueError

        def structured_failure(self, ns, exc):
            return {"status": "failed"}

        def unexpected_failure(self, ns, exc):
            return {"status": "failed"}

    parent = Namespace(
        model="glm-5.3-flash", base_url=CODING_URL, local_max_concurrency=8,
        lock_path=Path("/tmp/lock"), cjk_font="Songti SC", target_language="zh",
        task_memory_mib=None, job_timeout_seconds=None, memory_metric=None,
    )
    chunk = {"route": "digital_pdf", "source_ref": {"path": "/tmp/in.pdf"}}
    chunked.run_chunk_candidate(FakeWorkflow(), parent, Path("/tmp/freeze"), chunk, Path("/tmp/attempt"), Path("/tmp/context"))
    assert captured["value"] == 8
