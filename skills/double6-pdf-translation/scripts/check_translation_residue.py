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

# ---------- 参考文献区：只豁免有条目结构证据的文献条目（两个翻译方向共用） ----------
# 年份/DOI/出处本身不能证明一行是文献条目：普通正文同样会写“2024 年”“(2024)”或 DOI。
# 复用渲染残留检查（render_residue_check）已验证的逐条规则：先把参考文献标题之后的行按条目切块
# （编号/作者开头起新块，续行并入，空行/标题结束），strong 条目剔除，weak 只在编号连续等正面证据下剔除，
# 其余（含正文、未知块）照常计数。中文条目（GB/T 7714 风格）在同一框架下用等价的结构证据判定。
# 区域在附录类标题或 Markdown 标题处结束，之后的正文/附录照常计数。
import render_residue_check as _rrc

_GBT_TYPE_CODE = re.compile(r"\[(?:[JMCDRSNPZAGK]|EB|OL|DB|CP|J/OL|M/OL|C/OL|D/OL|EB/OL|DB/OL|CP/OL|N/OL|R/OL|S/OL|Z/OL)\]", re.I)
# 中文作者列表开头：2–4 个汉字（可含间隔号）的人名，逗号/顿号分隔，可选“等”，以“.”或“．”结束。
_ZH_AUTHOR_LEAD = re.compile(
    r"^\s*(?:\[\d{1,4}\]\s*|\d{1,3}\.\s*)?[\u4e00-\u9fff·]{2,6}(?:\s*[,，、]\s*[\u4e00-\u9fff·]{2,6}){0,9}"
    r"(?:\s*[,，]?\s*等)?\s*[.．]")
_ZH_FIRST_PERSON = re.compile(r"我们|本文|本研究|笔者")
_CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


def _heading_text(line: str) -> str:
    match = _MD_HEADING.match(line)
    return (match.group(1) if match else line).strip().strip("#").strip()


def is_reference_heading_line(line: str) -> bool:
    """References / 参考文献 等标题行（可带 Markdown # 与章节号），与渲染残留检查同一标题判定。"""
    return bool(_rrc.REFERENCE_HEADING.match(_heading_text(line)))


# 打开参考文献区的标题沿用各方向修复前的逐字集合（不扩大豁免范围）。
def _en_target_heading(line: str) -> bool:
    return line.strip().lower().strip("#:： ") in {"references", "参考文献", "bibliography"}


def _zh_target_heading(line: str) -> bool:
    return line.strip().lower().strip(":：") in {"references", "参考文献"}


def is_reference_region_end(line: str) -> bool:
    """参考文献区结束：附录类标题（Appendix、附录、补充材料…），或任一非参考文献的 Markdown 标题。"""
    text = _heading_text(line)
    if not text or is_reference_heading_line(line):
        return False
    if _rrc.APPENDIX_HEADING.match(text) and len(text) <= 80 and not _rrc.YEAR.search(text):
        return True
    return bool(_MD_HEADING.match(line))


def _starts_entry(line: str) -> bool:
    text = line.strip()
    return bool(_rrc.entry_lead(text) or _rrc.ENTRY_MARKER.match(text) or _ZH_AUTHOR_LEAD.match(text))


def zh_reference_entry_class(text: str) -> str:
    """含中文的条目：strong = 编号/作者开头 + 年份 + 出处（GB/T 7714 文献类型标识、出处/卷期页、DOI），
    weak = 开头证据 + 只有年份或出处之一；第一人称/叙述句一律 break。只有年份/DOI 不足以成为条目。"""
    value = " ".join(text.split())
    if _ZH_FIRST_PERSON.search(value) or _rrc.prose_veto(value):
        return "break"
    lead = bool(_rrc.ENTRY_MARKER.match(value) or _rrc.AUTHOR_LEAD.match(value) or _ZH_AUTHOR_LEAD.match(value))
    year = bool(_rrc.YEAR.search(value))
    source = bool(_GBT_TYPE_CODE.search(value) or _rrc.VENUE.search(value))
    if lead and year and source:
        return "strong"
    if lead and (year or source):
        return "weak"
    return "break"


def _reference_line_groups(lines: list[str], opens_region) -> tuple[list[dict[str, Any]], list[int]]:
    """按条目切块：参考文献标题之后、区域结束之前的非空行；编号/作者开头起新块；续行（上一行未以句号结束，
    或相对条目首行悬挂缩进）并入，块不超过渲染检查的条目行数上限；空行结束当前块。"""
    groups: list[dict[str, Any]] = []
    region_heading_lines: list[int] = []
    in_region = False
    current: dict[str, Any] | None = None
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if opens_region(line):
            in_region, current = True, None
            region_heading_lines.append(index)
            continue
        if in_region and is_reference_region_end(line):
            in_region, current = False, None
            continue
        if not in_region or not line:
            current = None
            continue
        indent = len(raw_line.expandtabs()) - len(raw_line.expandtabs().lstrip())
        # 续行：上一块未以句号结束，或本行相对条目首行悬挂缩进（pdftotext -layout 的条目续行）。
        continues = (current is not None and not _starts_entry(line)
                     and len(current["lines"]) < _rrc.MAX_ENTRY_LINES
                     and (not current["text"].rstrip().endswith((".", "．", "。")) or indent > current["indent"]))
        if not continues:
            current = {"lines": [], "text": "", "indent": indent}
            groups.append(current)
        current["lines"].append(index)
        current["text"] = (current["text"] + " " + line).strip()
    return groups, region_heading_lines


def reference_entry_lines(text: str, *, target_language: str = "en") -> set[int]:
    """返回应作为文献条目豁免的行号。逐块判定复用渲染检查的 _decide_entries（strong 剔除；weak 需编号连续
    等正面证据；break/未知计数）。中文块用 zh_reference_entry_class，其余用 headingless_entry_class(region=True)。"""
    lines = str(text or "").splitlines()
    groups, _ = _reference_line_groups(lines, _en_target_heading if target_language == "en" else _zh_target_heading)
    seq: list[dict[str, Any]] = []
    for group in groups:
        g = {"text": group["text"], "rows": [{"text": lines[i], "col": "text"} for i in group["lines"]],
             "x0": 0.0, "page": 0, "exclude": None, "_lines": group["lines"]}
        if _CJK_CHAR.search(group["text"]):
            g["_class"] = zh_reference_entry_class(group["text"])
        else:
            g["_class"] = _rrc.headingless_entry_class(g, region=True)
        seq.append(g)
    _rrc._decide_entries(seq, "reference_section")
    excluded: set[int] = set()
    for g in seq:
        if g.get("exclude"):
            excluded.update(g["_lines"])
    return excluded


# 历史逐行标记（年份/DOI/et al. 等）：只是必要条件，单独不足以剔除；剔除还须该行属于有结构证据的条目块。
# 两者取交集，豁免范围只会比修复前更窄，不会新增豁免。
_EN_REFERENCE_MARKER = re.compile(r"\(\d{4}\)|\bdoi\.org/|\b10\.\d{4,9}/|et al\.", re.I)
_ZH_REFERENCE_MARKER = re.compile(r"\[(?:[JMCDRSNPZA]|EB|OL|J/OL|EB/OL|DB)\]|\(\d{4}\)|\b(?:19|20)\d{2}\b|doi\.org/|\b10\.\d{4,9}/|et al\.|等\.", re.I)


def strip_role_passthrough_lines(text: str) -> str:
    """剔除按版式角色允许保留英文的 References 条目（文献标记 + 条目结构证据）和 Example 对照行。"""
    lines = str(text or "").splitlines()
    entries = reference_entry_lines(text, target_language="zh")
    kept: list[str] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if index in entries and _EN_REFERENCE_MARKER.search(line):
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
def strip_zh_reference_lines(text: str) -> str:
    """英文目标：剔除参考文献标题之后、带文献标记且属于有条目结构证据的文献条目块的行（中文文献条目允许保留原文）。
    只含年份/DOI 的普通中文正文不剔除，照常计入中文残留。"""
    lines = str(text or "").splitlines()
    entries = reference_entry_lines(text, target_language="en")
    return "\n".join(line for index, line in enumerate(lines)
                     if not (index in entries and _ZH_REFERENCE_MARKER.search(line.strip())))

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
