# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation core：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def load_glossary(path: Path | None) -> list[dict[str, str]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))

def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

def load_translation_blocks(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records

def contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    text = normalize_quality_text(text)
    term = normalize_quality_text(term)
    if re.fullmatch(r"[A-Za-z0-9+-]+", term):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text))
    return term in text

def normalize_quality_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "")

def should_use_document_translation(record: dict[str, Any]) -> bool:
    status = " ".join(
        str(record.get(key) or "")
        for key in ["status", "alignment_status", "translation_note"]
    )
    return "external_pdf_text_unaligned" in status or "repaired_full_text_unaligned" in status

def block_translation_or_document(record: dict[str, Any], document_translation: str) -> str:
    block_translation = str(record.get("translation") or "")
    if not block_translation and should_use_document_translation(record):
        return document_translation
    return block_translation

def policy_source_present(text: str, policy: dict[str, Any]) -> bool:
    terms = [str(policy.get("source_term") or "")]
    aliases = policy.get("aliases")
    if isinstance(aliases, list):
        terms.extend(str(item) for item in aliases)
    return any(contains_term(text, term) for term in terms if term)

def policy_translation_ok(translation: str, expected: str) -> bool:
    return any(item and contains_term(translation, item) for item in expected_translation_alternatives(expected))

def manifest_source_text(manifest: dict[str, Any]) -> str:
    parts: list[str] = []
    blocks = manifest.get("blocks")
    if isinstance(blocks, list):
        parts.extend(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
    metadata_blocks = manifest.get("metadata_blocks")
    if isinstance(metadata_blocks, list):
        parts.extend(str(block.get("text") or "") for block in metadata_blocks if isinstance(block, dict))
    return "\n".join(item for item in parts if item)

def metadata_source_text(manifest: dict[str, Any]) -> str:
    metadata_blocks = manifest.get("metadata_blocks")
    if not isinstance(metadata_blocks, list):
        return ""
    return "\n".join(str(block.get("text") or "") for block in metadata_blocks if isinstance(block, dict))

def policy_source_location(manifest: dict[str, Any], policy: dict[str, Any]) -> str:
    body_text = "\n".join(
        str(block.get("text") or "")
        for block in manifest.get("blocks", [])
        if isinstance(block, dict)
    )
    metadata_text = metadata_source_text(manifest)
    if policy_source_present(body_text, policy):
        return "body"
    if policy_source_present(metadata_text, policy):
        return "metadata"
    return "absent"

def first_seen_block_for_policy(policy: dict[str, Any], manifest: dict[str, Any]) -> str:
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return ""
    terms = [str(policy.get("source_term") or "")]
    aliases = policy.get("aliases")
    if isinstance(aliases, list):
        terms.extend(str(item) for item in aliases)
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "")
        if any(contains_term(text, term) for term in terms if term):
            return str(block.get("block_id") or "")
    metadata_blocks = manifest.get("metadata_blocks")
    if isinstance(metadata_blocks, list):
        for block in metadata_blocks:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            if any(contains_term(text, term) for term in terms if term):
                return str(block.get("metadata_id") or "metadata")
    return ""

def expected_translation_alternatives(expected: str) -> list[str]:
    alternatives = [expected]
    paren_match = re.search(r"[（(]([^）)]+)[）)]", expected)
    if paren_match:
        alternatives.append(paren_match.group(1).strip())
        alternatives.append(expected[: paren_match.start()].strip())
    return [item for item in alternatives if item]

def excerpt(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"

def block_page_map(manifest: dict[str, Any]) -> dict[str, str]:
    blocks = manifest.get("blocks")
    if not isinstance(blocks, list):
        return {}
    pages: dict[str, str] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        page = block.get("page")
        if block_id and page is not None:
            pages[block_id] = str(page)
    return pages

def enrich_issue_locations(issues: list[Issue], manifest: dict[str, Any]) -> list[Issue]:
    pages = block_page_map(manifest)
    for issue in issues:
        if issue.block_id and not issue.page:
            issue.page = pages.get(issue.block_id, "")
        if issue.severity in {"high", "medium"}:
            if not issue.block_id:
                issue.block_id = "document"
            if not issue.page:
                issue.page = "global"
    return issues

def normalize_percent(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("％", "%")

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
