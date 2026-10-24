# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""check translation residue：从原入口拆出的同一实现。"""
from __future__ import annotations
from check_translation_context import *

def protected_values(protected_spans: dict[str, Any] | None) -> set[str]:
    spans = (protected_spans or {}).get("spans")
    values: set[str] = set()
    if isinstance(spans, list):
        for item in spans:
            if isinstance(item, dict) and item.get("value"):
                values.add(str(item["value"]))
    return values

def term_policy_terms(term_policy: dict[str, Any] | None) -> set[str]:
    terms: set[str] = set()
    items = (term_policy or {}).get("terms")
    if not isinstance(items, list):
        return terms
    for item in items:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term") or "")
        if source_term:
            terms.add(source_term.lower())
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            terms.update(str(alias).lower() for alias in aliases if alias)
    return terms

def entity_policy_terms(entity_map: dict[str, Any] | None) -> set[str]:
    terms: set[str] = set()
    items = (entity_map or {}).get("entities")
    if not isinstance(items, list):
        return terms
    for item in items:
        if not isinstance(item, dict):
            continue
        source_term = str(item.get("source_term") or "")
        if source_term:
            terms.add(source_term.lower())
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            terms.update(str(alias).lower() for alias in aliases if alias)
    return terms

def is_allowed_technical_residue(translation: str, start: int, end: int) -> bool:
    """识别邮箱用户名、URL 路径和代码仓库 owner 这类应保留的英文片段。"""
    window = translation[max(0, start - 48) : min(len(translation), end + 48)].lower()
    before = translation[max(0, start - 16) : start]
    after = translation[end : min(len(translation), end + 32)]
    at_after = after.find("@")
    at_before = before.rfind("@")
    if at_after != -1 and not re.search(r"[\u4e00-\u9fff]", after[:at_after]):
        return True
    if at_before != -1 and not re.search(r"[\u4e00-\u9fff]", before[at_before + 1 :]):
        return True
    if re.search(r"https?://|www\.|github\.com|gitlab\.com|doi\.org", window):
        return True
    if re.search(r"\b[a-z0-9]+-[a-z0-9-]+\b", translation[start:end], re.I) and re.search(
        r"github\.com|gitlab\.com|bitbucket\.org",
        window,
    ):
        return True
    return False

def classify_english_residue(
    translation: str,
    *,
    protected_spans: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    allowed = {
        "abstract",
        "references",
        "doi",
        "url",
        "http",
        "https",
        "et",
        "al",
        "openai",
        "latextrans",
    }
    technical_policy_needed = {
        "caption",
        "captions",
        "environment",
        "environments",
        "eqnarray",
        "gpt-academic",
        "pdflatex",
        "pylatexenc",
        "subsection",
        "textbf",
    }
    protected = protected_values(protected_spans)
    term_terms = term_policy_terms(term_policy)
    entity_terms = entity_policy_terms(entity_map)
    must_translate_tokens = {
        "sub-corpus",
        "number",
        "texts",
        "tokens",
        "mean",
        "length",
        "translation",
        "profile",
        "dimensions",
        "continuing",
    }
    buckets: dict[str, list[str]] = {"must_translate": [], "allowed_keep": [], "needs_term_policy": []}
    for match in re.finditer(r"\b[A-Za-z][A-Za-z-]{2,}\b", translation):
        token = match.group(0)
        lower = token.lower()
        if lower in must_translate_tokens:
            bucket = "must_translate"
        elif token in protected or lower in allowed or is_allowed_technical_residue(translation, match.start(), match.end()):
            bucket = "allowed_keep"
        elif lower in technical_policy_needed:
            bucket = "needs_term_policy"
        elif lower in term_terms or lower in entity_terms or any(lower in term for term in term_terms | entity_terms):
            bucket = "needs_term_policy"
        elif token[:1].isupper() or token.isupper():
            bucket = "allowed_keep"
        elif len(token) >= 8:
            bucket = "must_translate"
        else:
            continue
        if token not in buckets[bucket]:
            buckets[bucket].append(token)
    return buckets

def is_likely_allowed_english_phrase(snippet: str) -> bool:
    """识别机构/委员名单等英文串，避免误判成普通 prose 漏译。"""
    words = re.findall(r"[A-Za-z][A-Za-z-]*", snippet)
    if len(words) < 4:
        return False
    role_markers = {
        "MEMBERS",
        "CO-CHAIR",
        "CHAIR",
        "LEAD",
        "EDITOR",
        "EDITOR-IN-CHIEF",
        "RESEARCH",
        "MANAGER",
        "UNDERGRADUATE",
        "GRADUATE",
        "AFFILIATED",
        "RESEARCHERS",
    }
    if any(marker in snippet for marker in role_markers):
        return True
    proper_like = sum(1 for word in words if word[:1].isupper() or word.isupper())
    lowercase_function_words = {
        word.lower()
        for word in words
        if word.islower() and word.lower() in {"of", "and", "for", "in", "on", "to", "the"}
    }
    content_lowercase = [word for word in words if word.islower() and word.lower() not in lowercase_function_words]
    return proper_like >= max(3, len(words) - 2) and len(content_lowercase) <= 1

def strip_role_passthrough_lines(text: str) -> str:
    """剔除按版式角色允许保留英文的 References 条目和 Example 对照行。"""
    kept: list[str] = []
    in_references = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower().strip(":：")
        if lowered in {"references", "参考文献"}:
            in_references = True
            kept.append(raw_line)
            continue
        if in_references and re.search(r"\(\d{4}\)|\bdoi\.org/|\b10\.\d{4,9}/|et al\.", line, re.I):
            continue
        if re.match(r"^(?:Example\s+\d+|ST|TT|HT|NMT-GT|LLM-[A-Za-z0-9-]+)\s*[:：]", line, re.I):
            continue
        kept.append(raw_line)
    return "\n".join(kept)

def check_untranslated_english(
    translation: str,
    *,
    protected_spans: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    scan_text = strip_role_passthrough_lines(translation)
    candidates = []
    for match in re.finditer(r"\b[A-Za-z][A-Za-z-]+(?:\s+[A-Za-z][A-Za-z-]+){4,}\b", scan_text):
        snippet = " ".join(match.group(0).split())
        if (
            len(snippet) > 40
            and not re.search(r"https?://|doi\.org|et al|References", snippet, re.IGNORECASE)
            and not is_likely_allowed_english_phrase(snippet)
        ):
            candidates.append(snippet[:160])
    buckets = classify_english_residue(
        scan_text,
        protected_spans=protected_spans,
        entity_map=entity_map,
        term_policy=term_policy,
    )
    must_translate = buckets["must_translate"]
    needs_term_policy = buckets["needs_term_policy"]
    if candidates:
        issues.append(
            Issue(
                "medium",
                "疑似大段英文未翻译",
                "发现可能未翻译的英文片段：" + "；".join(candidates[:5]),
                category="omission",
                translation_evidence="；".join(candidates[:3]),
                suggestion="回看对应段落，确认是否为必须保留的原文；否则补译。",
            )
        )
    if must_translate:
        issues.append(
            Issue(
                "medium",
                "疑似英文单词残留（must_translate）",
                "译文中发现可能应翻译的英文单词：" + "；".join(must_translate[:8]),
                category="omission",
                translation_evidence="；".join(must_translate[:5]),
                suggestion="检查这些词是否为术语、代码或专名；若不是，应补译并重新抽取译文 PDF 文本。",
            )
        )
    if needs_term_policy:
        issues.append(
            Issue(
                "low",
                "英文残留待术语策略确认（needs_term_policy）",
                "这些英文片段命中术语/实体策略，需确认是保留英文还是补充中文定译：" + "；".join(needs_term_policy[:8]),
                category="terminology",
                translation_evidence="；".join(needs_term_policy[:5]),
                suggestion="补全 term_policy/entity_map 的保留、首次双语或中文化策略。",
            )
        )
    return issues

# 中译英文字 QA：英文目标译文里成段保留的中文才是“未译”；正常英文不是残留。
# 与英译中的英文残留检查对称：同样跳过参考文献条目和保护值（URL、公式、代码等）。
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff0c\uff1a\uff1b\uff08\uff09\u3001\s]*")
_ZH_REFERENCE_LINE = re.compile(r"\[(?:[JMCDRSNPZA]|EB|OL|J/OL|EB/OL|DB)\]|\(\d{4}\)|\b(?:19|20)\d{2}\b|doi\.org/|\b10\.\d{4,9}/|et al\.|等\.", re.I)

def strip_zh_reference_lines(text: str) -> str:
    """英文目标：剔除参考文献标题之后的文献条目（中文文献条目允许保留原文）。"""
    kept: list[str] = []
    in_references = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.lower().strip("#:： ") in {"references", "参考文献", "bibliography"}:
            in_references = True
            kept.append(raw_line)
            continue
        if in_references and _ZH_REFERENCE_LINE.search(line):
            continue
        kept.append(raw_line)
    return "\n".join(kept)

def check_untranslated_chinese(
    translation: str,
    *,
    protected_spans: dict[str, Any] | None = None,
    entity_map: dict[str, Any] | None = None,
    term_policy: dict[str, Any] | None = None,
) -> list[Issue]:
    """英文目标译文的中文残留：成段（≥6 个汉字）为 medium，较短片段为 low 待术语策略确认。"""
    protected = [value for value in protected_values(protected_spans) if re.search(r"[\u3400-\u9fff]", value)]
    allowed = {term for term in term_policy_terms(term_policy) | entity_policy_terms(entity_map) if re.search(r"[\u3400-\u9fff]", term)}
    scan_text = strip_zh_reference_lines(translation)
    for value in protected:
        scan_text = scan_text.replace(value, " ")
    long_runs: list[str] = []
    short_runs: list[str] = []
    for match in _CJK_RUN.finditer(scan_text):
        snippet = " ".join(match.group(0).split()).strip("，：；（）、 ")
        han = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", snippet))
        if not han or snippet.lower() in allowed:
            continue
        bucket = long_runs if han >= 6 else short_runs
        if snippet not in bucket:
            bucket.append(snippet[:160])
    issues: list[Issue] = []
    if long_runs:
        issues.append(
            Issue(
                "medium",
                "疑似大段中文未翻译",
                "英文译文中发现可能未翻译的中文片段：" + "；".join(long_runs[:5]),
                category="omission",
                rule="untranslated_chinese_in_english_target",
                translation_evidence="；".join(long_runs[:3]),
                suggestion="回看对应段落，确认是否为必须保留的原文（专名、引文）；否则补译为英文。",
            )
        )
    if short_runs:
        issues.append(
            Issue(
                "low",
                "中文残留待术语策略确认（needs_term_policy）",
                "英文译文中的短中文片段需确认是保留原文还是给出英文译名：" + "；".join(short_runs[:8]),
                category="terminology",
                rule="chinese_residue_in_english_target",
                translation_evidence="；".join(short_runs[:5]),
                suggestion="补全 term_policy/entity_map 的保留或英文译名策略。",
            )
        )
    return issues

def check_translation_metadata_leak(source: str, translation: str) -> list[Issue]:
    """只提示源文没有的显式译文元字段；普通注释/代码不自动删除。"""
    from check_translation_core import excerpt
    pattern = re.compile(r"\|\s*(note|translation_note|translator_note)\s*[:：]", re.I)
    def fields(text: str) -> list[re.Match[str]]:
        matches = list(pattern.finditer(text))
        # pdftotext -layout 可能在同栏的 | 和 note 之间插入另一栏的行。
        # 仅容许一个换行、400 字符内的前置管道及显式列间空白，不泛化到普通 Note。
        for match in re.finditer(r"[ \t]{2,}(note|translation_note|translator_note)\s*[:：]", text, re.I):
            prefix = text[max(0, match.start()-400):match.start()]
            pipe = prefix.rfind('|')
            if pipe >= 0 and prefix[pipe:].count('\n') <= 1 and not any(m.end() == match.end() for m in matches):
                matches.append(match)
        return matches
    source_keys = {match.group(1).lower() for match in fields(source)}
    findings = []
    for match in fields(translation):
        if match.group(1).lower() in source_keys:
            continue
        findings.append(Issue(
            "medium", "疑似翻译元说明混入正文",
            "译文出现源文没有的显式 note 元字段，可能将模型说明写入了最终正文。",
            category="addition", block_id="document", rule="translation_metadata_leak",
            translation_evidence=excerpt(translation[match.start():match.start()+160]),
            suggestion="对照源文确认该字段是否属于正文；确认是额外说明后定向返修并重建最终 PDF。"))
    return findings


def check_sections(source: str, translation: str) -> list[Issue]:
    issues: list[Issue] = []
    source_headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", source)
    translation_headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", translation)
    if len(source_headings) >= 3 and len(translation_headings) < max(1, len(source_headings) // 2):
        issues.append(
            Issue(
                "medium",
                "章节结构可能缺失",
                f"源文有 {len(source_headings)} 个 Markdown 标题，译文只有 {len(translation_headings)} 个。",
                category="structure",
                source_evidence=", ".join(source_headings[:5]),
                translation_evidence=", ".join(translation_headings[:5]),
                suggestion="保留源文主要标题层级，或在译文中提供对应章节锚点。",
            )
        )
    if re.search(r"(?im)^#+\s*Abstract\b|^Abstract\b", source) and not re.search(r"摘要|Abstract", translation):
        issues.append(
            Issue(
                "low",
                "摘要标题缺失",
                "源文包含 Abstract，但译文中未找到“摘要”或 Abstract 标题。",
                category="structure",
                source_evidence="Abstract",
                suggestion="补充“摘要”标题或保留 Abstract 锚点。",
            )
        )
    return issues

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
