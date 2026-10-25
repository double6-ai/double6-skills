# SPDX-License-Identifier: AGPL-3.0-only
"""翻译账本，以及「大约一页一批、整批失败对半再试」。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / "scripts"), str(SKILL / "vendor" / "babeldoc"), str(SKILL / "vendor" / "pdfmathtranslate_next")]

from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (  # noqa: E402
    ILTranslatorLLMOnly,
    length_ratio_needs_retry,
    sliced_batch,
)
from babeldoc.progress_monitor import ProgressMonitor  # noqa: E402
from paper_translation_workflow import quality_verdict  # noqa: E402
from translation_cost_ledger import (  # noqa: E402
    PAGE_BATCH_PARAGRAPH_LIMIT,
    PAGE_BATCH_TOKEN_LIMIT,
    add_quality_seconds,
    backend_ledger,
    batch_is_full,
    collect_from_babeldoc_config,
    fold_quality_check,
    sum_ledgers,
)


class _Atomic:
    def __init__(self, value: int) -> None:
        self.value = value


def test_short_lines_keep_the_batch_translation():
    # 一个词译成三个词，旧规则因为刚好不小于 3 倍而再请求一次。
    assert length_ratio_needs_retry(1, 3) is False
    assert length_ratio_needs_retry(10, 30) is False
    assert length_ratio_needs_retry(5, 2) is False
    # 短句译文是空的，或长过 30 个 token，仍再译。
    assert length_ratio_needs_retry(5, 0) is True
    assert length_ratio_needs_retry(1, 31) is True
    assert length_ratio_needs_retry(0, 3) is True
    # 更长的段落仍用原来的 0.3 到 3 倍。
    assert length_ratio_needs_retry(11, 33) is True
    assert length_ratio_needs_retry(11, 32) is False
    assert length_ratio_needs_retry(100, 20) is True
    assert length_ratio_needs_retry(100, 50) is False


def test_page_batch_is_larger_than_the_old_five_paragraph_cap():
    assert PAGE_BATCH_TOKEN_LIMIT == 1000
    assert PAGE_BATCH_PARAGRAPH_LIMIT == 24
    # 旧额度是 200 词或 5 段。6 段短文、两段一共 250 词现在仍算一批。
    assert batch_is_full(60, 6) is False
    assert batch_is_full(250, 2) is False
    assert batch_is_full(1000, 24) is False
    assert batch_is_full(1001, 1) is True
    assert batch_is_full(10, 25) is True


def test_failed_batch_splits_in_half_before_any_single_paragraph_call():
    engine = ILTranslatorLLMOnly.__new__(ILTranslatorLLMOnly)
    engine.batch_split_count = 0
    engine.fallback_count = 0
    engine.total_count = 0
    engine.calc_token_count = lambda text: 1
    engine.il_translator = SimpleNamespace(translate_paragraph=lambda *args, **kwargs: None)
    sizes: list[int] = []
    jobs: list[object] = []

    def translate_paragraph(batch, *args, **kwargs):
        sizes.append(len(batch.paragraphs))
        if len(batch.paragraphs) > 1:
            engine._retry_failed_batch(batch, list(range(len(batch.paragraphs))), *args, **kwargs)

    engine.translate_paragraph = translate_paragraph
    paragraphs = [SimpleNamespace(debug_id=str(index), unicode="word") for index in range(4)]
    batch = SimpleNamespace(paragraphs=paragraphs, pages=[None] * 4, trackers=[SimpleNamespace() for _ in paragraphs])
    engine._retry_failed_batch(batch, [0, 1, 2, 3], None, {}, {}, None, None, SimpleNamespace(submit=jobs.append))
    assert sizes == [2, 1, 1, 2, 1, 1]
    assert engine.batch_split_count == 3
    assert engine.fallback_count == 0
    assert jobs == []


def test_single_remaining_paragraph_is_retried_alone():
    engine = ILTranslatorLLMOnly.__new__(ILTranslatorLLMOnly)
    engine.batch_split_count = 0
    engine.fallback_count = 0
    engine.total_count = 0
    engine.calc_token_count = lambda text: 3
    engine.il_translator = SimpleNamespace(translate_paragraph=lambda *args, **kwargs: None)
    jobs: list[tuple] = []

    def submit(*args, **kwargs):
        jobs.append(args)

    paragraph = SimpleNamespace(debug_id="only", unicode="sentence")
    batch = sliced_batch(
        SimpleNamespace(paragraphs=[paragraph], pages=["page"], trackers=[SimpleNamespace()]),
        [0],
    )
    engine._retry_failed_batch(batch, [0], None, {}, {}, None, None, SimpleNamespace(submit=submit))
    assert engine.batch_split_count == 0
    assert engine.fallback_count == 1
    assert len(jobs) == 1
    assert jobs[0][1] is paragraph


def test_stage_seconds_add_up_on_the_parent_monitor():
    parent = ProgressMonitor([("Parse Page Layout", 1.0)])
    child = parent.create_part_monitor(0, 1)
    with child.stage_start("Parse Page Layout", 1):
        time.sleep(0.01)
    assert child.stage_seconds["Parse Page Layout"] >= 0.01
    assert parent.stage_seconds["Parse Page Layout"] >= 0.01


def test_backend_ledger_keeps_missing_token_usage_blank():
    ledger = backend_ledger(
        requests=4,
        local_cache_hits=2,
        prompt_tokens=None,
        completion_tokens=None,
        provider_cache_hit_prompt_tokens=None,
        token_usage_reported=False,
        single_paragraph_retries=1,
        batch_splits=2,
        stage_seconds={
            "Parse PDF and Create Intermediate Representation": 1.2,
            "Parse Page Layout": 3,
            "Parse Paragraphs": 0.4,
            "Translate Paragraphs": 20,
            "Typesetting": 1,
            "Save PDF": 0.5,
        },
        model_wait_seconds=11.2567,
    )
    assert ledger["requests"] == 4
    assert ledger["local_cache_hits"] == 2
    assert ledger["prompt_tokens"] is None
    assert ledger["token_usage_reported"] is False
    assert ledger["seconds"]["read_pdf"] == 1.2
    assert ledger["seconds"]["layout"] == 3
    assert ledger["seconds"]["prepare"] == 0.4
    assert ledger["seconds"]["translate_stage"] == 20
    assert ledger["seconds"]["model_wait"] == 11.257
    assert ledger["seconds"]["typeset"] == 1.5
    assert "quality_check" not in ledger["seconds"]


def test_collect_reads_reported_usage_and_cache_hits():
    config = SimpleNamespace(
        translator=SimpleNamespace(
            model_request_count=2,
            translate_cache_call_count=5,
            model_wait_seconds=4,
            usage_reported_count=2,
            prompt_token_count=_Atomic(80),
            completion_token_count=_Atomic(30),
            cache_hit_prompt_token_count=_Atomic(15),
        ),
        progress_monitor=SimpleNamespace(stage_seconds={}),
        shared_context_cross_split_part=SimpleNamespace(
            double6_batch_stats={"single_paragraph_retries": 1, "batch_splits": 2}
        ),
    )
    ledger = collect_from_babeldoc_config(config)
    assert ledger["requests"] == 2
    assert ledger["local_cache_hits"] == 5
    assert ledger["prompt_tokens"] == 80
    assert ledger["completion_tokens"] == 30
    assert ledger["provider_cache_hit_prompt_tokens"] == 15
    assert ledger["single_paragraph_retries"] == 1
    assert ledger["batch_splits"] == 2


def test_unreported_usage_is_not_stored_as_zero():
    config = SimpleNamespace(
        translator=SimpleNamespace(
            model_request_count=3,
            translate_cache_call_count=0,
            model_wait_seconds=1,
            usage_reported_count=0,
            prompt_token_count=_Atomic(0),
            completion_token_count=_Atomic(0),
            cache_hit_prompt_token_count=_Atomic(0),
        ),
        progress_monitor=SimpleNamespace(stage_seconds={}),
        shared_context_cross_split_part=SimpleNamespace(),
    )
    ledger = collect_from_babeldoc_config(config)
    assert ledger["requests"] == 3
    assert ledger["prompt_tokens"] is None
    assert ledger["token_usage_reported"] is False


def test_document_total_adds_chunk_ledgers_and_stops_when_one_is_missing():
    one = add_quality_seconds(backend_ledger(
        requests=2, local_cache_hits=1, prompt_tokens=10, completion_tokens=4,
        provider_cache_hit_prompt_tokens=3, token_usage_reported=True,
        single_paragraph_retries=0, batch_splits=1, stage_seconds={}, model_wait_seconds=2,
    ), 1.25)
    two = add_quality_seconds(backend_ledger(
        requests=3, local_cache_hits=0, prompt_tokens=12, completion_tokens=5,
        provider_cache_hit_prompt_tokens=1, token_usage_reported=True,
        single_paragraph_retries=2, batch_splits=0, stage_seconds={}, model_wait_seconds=3,
    ), 0.75)
    total = sum_ledgers([one, two])
    assert total["available"] is True
    assert total["scope"] == "document"
    assert total["requests"] == 5
    assert total["prompt_tokens"] == 22
    assert total["completion_tokens"] == 9
    assert total["provider_cache_hit_prompt_tokens"] == 4
    assert total["single_paragraph_retries"] == 2
    assert total["batch_splits"] == 1
    assert total["seconds"]["model_wait"] == 5
    assert total["seconds"]["quality_check"] == 2
    missing = sum_ledgers([one, {"protocol": "translation_cost_ledger_v1", "available": False}])
    assert missing["available"] is False
    assert missing["reason"] == "chunk_ledger_incomplete"
    assert "requests" not in missing


def test_quality_check_time_is_folded_into_the_render_manifest(tmp_path: Path):
    manifest = {"status": "ok", "cost_ledger": backend_ledger(
        requests=1, local_cache_hits=0, prompt_tokens=8, completion_tokens=3,
        provider_cache_hit_prompt_tokens=0, token_usage_reported=True,
        single_paragraph_retries=0, batch_splits=0, stage_seconds={}, model_wait_seconds=1,
    )}
    (tmp_path / "render_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
    ledger = fold_quality_check(tmp_path, extra_seconds=0.5, input_pdf=tmp_path / "paper.pdf")
    saved = __import__("json").loads((tmp_path / "render_manifest.json").read_text(encoding="utf-8"))
    assert ledger["seconds"]["quality_check"] == 0.5
    assert saved["cost_ledger"]["seconds"]["quality_check"] == 0.5
    assert (tmp_path / "translation_cost_ledger.json").is_file()


def test_candidate_receipt_copies_the_cost_ledger(tmp_path: Path):
    ledger = backend_ledger(
        requests=1, local_cache_hits=0, prompt_tokens=8, completion_tokens=3,
        provider_cache_hit_prompt_tokens=0, token_usage_reported=True,
        single_paragraph_retries=0, batch_splits=0, stage_seconds={}, model_wait_seconds=1,
    )
    verdict = quality_verdict(tmp_path, manifest={"quality_status": "pass", "cost_ledger": ledger})
    assert verdict["quality_status"] == "pass"
    assert verdict["cost_ledger"]["requests"] == 1
    assert verdict["cost_ledger"]["prompt_tokens"] == 8
