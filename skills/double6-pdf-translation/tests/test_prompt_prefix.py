# SPDX-License-Identifier: AGPL-3.0-only
"""一批请求的固定说明保持同一段开头，标题和本批术语表放在后面。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(SKILL / "scripts"),
    str(SKILL / "vendor" / "babeldoc"),
    str(SKILL / "vendor" / "pdfmathtranslate_next"),
]

from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (  # noqa: E402
    ILTranslatorLLMOnly,
)
from pdf2zh_next.translator.translator_impl.openai import llm_messages  # noqa: E402


class _Glossary:
    def __init__(self, name: str, entries: list[tuple[str, str]]) -> None:
        self.name = name
        self.entries = entries

    def get_active_entries_for_text(self, text: str) -> list[tuple[str, str]]:
        return [item for item in self.entries if item[0] in text]


def _translator(glossaries: list[_Glossary]) -> ILTranslatorLLMOnly:
    translator = ILTranslatorLLMOnly.__new__(ILTranslatorLLMOnly)
    translator.translation_config = SimpleNamespace(
        lang_out="zh",
        custom_system_prompt="Translate carefully.\nFollow all rules strictly.",
    )
    translator._cached_glossaries = glossaries
    return translator


def _title(text: str, debug_id: str) -> SimpleNamespace:
    return SimpleNamespace(unicode=text, debug_id=debug_id)


def test_stable_prefix_ignores_titles_and_which_terms_match() -> None:
    glossary = _Glossary("doc", [("ChatGPT", "ChatGPT"), ("Cobham", "科巴姆")])
    translator = _translator([glossary])
    with_term, prefix = translator._build_llm_prompt(
        json_input_str='[{"id": 0, "input": "ChatGPT studies attention."}]',
        title_paragraph=_title("Attention Is All You Need", "global"),
        local_title_paragraph=_title("Model Architecture", "local"),
        batch_text_for_glossary_matching="ChatGPT studies attention.",
    )
    without_term, other_prefix = translator._build_llm_prompt(
        json_input_str='[{"id": 0, "input": "A short ordinary sentence."}]',
        title_paragraph=_title("A Different Paper", "other"),
        local_title_paragraph=None,
        batch_text_for_glossary_matching="A short ordinary sentence.",
    )
    no_glossary, bare_prefix = _translator([])._build_llm_prompt(
        json_input_str='[{"id": 0, "input": "Nothing special."}]',
        title_paragraph=None,
        local_title_paragraph=None,
        batch_text_for_glossary_matching="Nothing special.",
    )
    assert prefix == other_prefix == bare_prefix
    assert with_term.startswith(prefix) and without_term.startswith(prefix)
    assert no_glossary.startswith(prefix)
    assert "Structure Rules" in prefix and "Here is the input" not in prefix
    assert "Always use the exact target term." in prefix
    assert "Attention Is All You Need" not in prefix
    assert "A Different Paper" not in prefix
    assert "ChatGPT" not in prefix and "科巴姆" not in prefix
    assert "| ChatGPT | ChatGPT |" in with_term[len(prefix):]
    assert "Glossary Tables" not in without_term[len(prefix):]
    assert "Model Architecture" in with_term[len(prefix):]
    assert "A short ordinary sentence." in without_term[len(prefix):]


def test_openai_request_puts_the_stable_part_in_the_system_message() -> None:
    translator = _translator([_Glossary("doc", [("ChatGPT", "ChatGPT")])])
    full, prefix = translator._build_llm_prompt(
        json_input_str='[{"id": 0, "input": "ChatGPT studies attention."}]',
        title_paragraph=_title("Attention Is All You Need", "global"),
        local_title_paragraph=None,
        batch_text_for_glossary_matching="ChatGPT studies attention.",
    )
    messages = llm_messages(full, {"prompt_prefix": prefix, "request_json_mode": True})
    assert [item["role"] for item in messages] == ["system", "user"]
    assert messages[0]["content"] == prefix
    assert "Here is the input" in messages[1]["content"]
    assert "ChatGPT studies attention." in messages[1]["content"]
    assert "Structure Rules" not in messages[1]["content"]
    assert llm_messages(full, None) == [{"role": "user", "content": full}]
    assert llm_messages("plain text", {"prompt_prefix": "not-a-prefix"}) == [
        {"role": "user", "content": "plain text"}
    ]
