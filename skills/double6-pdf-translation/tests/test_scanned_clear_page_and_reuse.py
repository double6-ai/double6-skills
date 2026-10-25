# SPDX-License-Identifier: AGPL-3.0-only
"""清晰单栏不升级版面模型；同一份扫描再跑时复用识别和模型原文。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / "scripts")]

from scanned_raster.checkpoint import (  # noqa: E402
    ResponseCheckpoint,
    enable_default_scanned_reuse,
    execution_identity,
)
from scanned_raster.parser_policy import assess_rapidocr_page  # noqa: E402


def _line(text: str, y: float, confidence: float, x0: float = 40, x1: float = 700) -> dict:
    return {"ocr_text": text, "confidence": confidence, "bbox": [x0, y, x1, y + 12]}


def test_one_weak_line_on_a_clear_page_stays_on_rapidocr():
    regions = [
        _line(f"clear single column sentence number {index}", 40 + index * 20, confidence)
        for index, confidence in enumerate([0.99, 0.98, 0.97, 0.96, 0.55])
    ]
    assessment = assess_rapidocr_page(regions, page_width=800)
    assert assessment["escalate"] is False
    assert assessment["reasons"] == ["region_confidence_below_0.75"]
    assert assessment["escalation_reasons"] == []


def test_shaky_but_single_column_page_stays_on_rapidocr():
    regions = [_line(f"readable body line number {index} here", 40 + index * 20, 0.82) for index in range(4)]
    assessment = assess_rapidocr_page(regions, page_width=800)
    assert assessment["escalate"] is False
    assert "median_confidence_below_0.90" in assessment["reasons"]


def test_formula_columns_and_empty_pages_still_escalate():
    formula = assess_rapidocr_page([_line("E = mc squared today", 40, 0.99)], page_width=800)
    assert formula["escalate"] is True
    assert "formula_candidate" in formula["escalation_reasons"]

    columns = []
    for index in range(3):
        y = 80 + index * 20
        columns.append(_line("left column sentence one", y, 0.99, x0=40, x1=400))
        columns.append(_line("right column sentence two", y, 0.99, x0=560, x1=920))
    two_column = assess_rapidocr_page(columns, page_width=1000)
    assert two_column["escalate"] is True
    assert "multi_column_layout" in two_column["escalation_reasons"]

    empty = assess_rapidocr_page([], page_width=800, nonblank=True)
    assert empty["escalate"] is True
    assert empty["escalation_reasons"] == ["nonblank_page_without_ocr_text"]


def test_rerun_reuses_the_model_response_without_an_explicit_fingerprint():
    previous = os.environ.get("PAPER_TRANSLATION_WORKSPACE")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["PAPER_TRANSLATION_WORKSPACE"] = directory
        try:
            _assert_rerun_reuses_model_response()
        finally:
            if previous is None:
                os.environ.pop("PAPER_TRANSLATION_WORKSPACE", None)
            else:
                os.environ["PAPER_TRANSLATION_WORKSPACE"] = previous


def _assert_rerun_reuses_model_response():
    args = SimpleNamespace(
        model="demo-model",
        base_url="http://127.0.0.1:9/v1",
        custom_system_prompt="translate",
        system_prompt=None,
        target_language="zh",
        temperature=0,
        reasoning_effort=None,
        openai_reasoning_effort=None,
        scanned_parser="auto",
        mineru_tier="auto",
        mineru_runtime="local",
        ignore_translation_cache=False,
        scanned_checkpoint_dir=None,
        scanned_parse_checkpoint_dir=None,
        scanned_model_fingerprint=None,
        scanned_parser_fingerprint=None,
        api_key="secret",
    )
    enable_default_scanned_reuse(args)
    assert args.scanned_checkpoint_dir.endswith("/responses")
    assert args.scanned_parse_checkpoint_dir.endswith("/parse")
    assert len(args.scanned_model_fingerprint) == 64
    identity = execution_identity("a" * 64, args, "b" * 64)
    calls = []

    def translator(text, _args):
        calls.append(text)
        return "你好"

    with ResponseCheckpoint(Path(args.scanned_checkpoint_dir), identity) as checkpoint:
        assert checkpoint.translate("hello", args, translator) == "你好"
    with ResponseCheckpoint(Path(args.scanned_checkpoint_dir), identity) as checkpoint:
        assert checkpoint.translate("hello", args, translator) == "你好"
        report = checkpoint.report()
    assert calls == ["hello"]
    assert report["cache_hits"] == 1
    assert report["model_calls"] == 0


def test_ignore_cache_does_not_create_reuse_directories():
    args = SimpleNamespace(ignore_translation_cache=True, scanned_checkpoint_dir=None, scanned_parse_checkpoint_dir=None)
    enable_default_scanned_reuse(args)
    assert args.scanned_checkpoint_dir is None
    assert args.scanned_parse_checkpoint_dir is None
