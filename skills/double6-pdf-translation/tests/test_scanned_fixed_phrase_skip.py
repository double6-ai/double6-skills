# SPDX-License-Identifier: AGPL-3.0-only
"""固定短句和栏位在问模型之前查表。"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / "scripts")]

from scanned_raster.pipeline_translation import (  # noqa: E402
    _normalize_structured_field_translation,
    _translate_regions,
)


def _body(text: str, region_id: str = "r1", **extra):
    region = {
        "region_id": region_id,
        "ocr_text": text,
        "layout_role": "text",
        "bbox": [10, 10, 80, 22],
    }
    region.update(extra)
    return region


def test_fixed_phrase_and_field_skip_the_model():
    calls = []

    def translator(text, _args):
        calls.append(text)
        return "不应出现"

    phrase = _body(" Therefore ")
    field = _body("Applicant: unknown", "r2")
    combined = _body("Examiner: Ann Group Art Unit: 1234", "r3")
    failures = _translate_regions([phrase, field, combined], object(), translator)
    assert failures == []
    assert calls == []
    assert phrase["status"] == "translated"
    assert phrase["translation"] == "因此"
    assert phrase["translation_source"] == "fixed_phrase"
    assert field["translation"] == "申请人：未知"
    assert combined["translation"] == "审查员：Ann　技术组：1234"


def test_ordinary_prose_still_calls_the_model():
    calls = []

    def translator(text, _args):
        calls.append(text)
        return "方法因此仍然有效。"

    region = _body("The method therefore still works.")
    failures = _translate_regions([region], object(), translator)
    assert failures == []
    assert calls == ["The method therefore still works."]
    assert region["translation"] == "方法因此仍然有效。"
    assert "translation_source" not in region


def test_table_fixed_phrase_skips_the_search_layer_call():
    calls = []

    def translator(text, _args):
        calls.append(text)
        return "模型译文"

    fixed = _body("hence", "t1", layout_role="table")
    prose = _body("Measured values for the control group.", "t2", layout_role="table")
    failures = _translate_regions([fixed, prose], object(), translator)
    assert failures == []
    assert calls == ["Measured values for the control group."]
    assert fixed["status"] == "protected"
    assert fixed["translation"] is None
    assert fixed["search_layer_translation"] == "因此"
    assert fixed["search_layer_source"] == "fixed_phrase"
    assert prose["search_layer_translation"] == "模型译文"
    assert "search_layer_source" not in prose


def test_unmatched_field_keeps_the_model_translation():
    assert _normalize_structured_field_translation("Not a field.", "不是栏位。") == "不是栏位。"
