#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_RESIDUE_TRANSLATIONS: dict[str, str] = {
    "overwhelmingly": "压倒性地",
    "consistently": "一贯地",
    "multilingual": "多语种",
    "geographic": "地理",
    "collaboration": "协作",
    "dimensions": "维度",
    "continuing": "持续",
    "Sub-corpus": "子语料库",
    "Number": "数量",
    "texts": "文本",
    "Tokens": "词数",
    "Mean": "平均",
    "length": "长度",
    "translation": "译文",
    "profile": "特征轮廓",
}

TERM_REPLACEMENT_HINTS: dict[str, list[tuple[str, str]]] = {
    "overwhelmingly": [("overwhelmingly", "压倒性地")],
    "Hong Kong Polytechnic University": [
        ("香港理工大学 中国香港大学", "香港理工大学，中国香港"),
        ("香港理工大学中国香港大学", "香港理工大学，中国香港"),
        ("中国香港某大学", "香港理工大学"),
        ("中国香港大学", "中国香港"),
        ("香港大学", "香港理工大学"),
    ],
    "Research and Development": [("研发", "研究与开发")],
    "textbase": [("文本基模", "文本库"), ("文本基础", "文本库")],
    "Parser agent": [("解析器代理", "解析器智能体"), ("Parser代理", "解析器智能体")],
    "Human-Centered AI": [("人类中心人工智能", "以人为本人工智能"), ("Human-Centered AI", "以人为本人工智能")],
    "Human-Centered Artificial Intelligence": [
        ("人类中心人工智能", "以人为本人工智能"),
        ("Human-Centered Artificial Intelligence", "以人为本人工智能"),
    ],
    "Stanford Institute for Human-Centered Artificial Intelligence": [
        ("斯坦福人类中心人工智能研究院", "斯坦福以人为本人工智能研究院"),
        ("斯坦福人类中心人工智能研究所", "斯坦福以人为本人工智能研究院"),
    ],
    "AI sovereignty": [("AI主权", "人工智能主权"), ("AI 主权", "人工智能主权")],
    "Responsible AI": [("负责任的人工智能", "负责任人工智能"), ("Responsible AI", "负责任人工智能")],
    "AI Index": [("AI指数", "人工智能指数"), ("AI 指数", "人工智能指数"), ("AI INDEX", "人工智能指数")],
    "Contents": [("Contents", "目录")],
    "Chapter Highlights": [("Chapter Highlights", "章节要点")],
    "Brookings": [("Brookings", "布鲁金斯学会")],
    "Stanford University": [("Stanford University", "斯坦福大学")],
    "Northeastern University": [("Northeastern University", "东北大学")],
    "SRI International": [("斯坦福研究院国际", "SRI International")],
    "UNSW Sydney": [("新南威尔士大学悉尼分校", "悉尼新南威尔士大学")],
    "University of Minnesota": [("University of Minnesota", "明尼苏达大学")],
    "University of Southern California": [("University of Southern California", "南加州大学")],
    "EU": [("EU", "欧盟")],
    "Google Translate": [("Google 翻译", "谷歌翻译"), ("Google翻译", "谷歌翻译")],
    "Yolanda Gil": [("Yolanda Gil", "约兰达·吉尔（Yolanda Gil）")],
    "Raymond Perrault": [("Raymond Perrault", "雷蒙德·佩罗（Raymond Perrault）")],
    "rapid globalized world": [("全球快速全球化的背景下", "全球化进程加速的当下")],
    "Sub-corpus": [("Sub-corpus", "子语料库")],
    "Number of texts": [("Number of texts", "文本数量")],
    "Tokens": [("Tokens", "词数")],
    "Mean length": [("Mean length", "平均长度")],
    "translation profile": [("translation profile", "译文特征轮廓")],
    "dimensions": [("dimensions", "维度")],
    "continuing": [("continuing", "持续")],
    "Competing interests": [("Competing interests", "竞争利益声明")],
}

PROTECTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("url", re.compile(r"https?://[^\s)>\]]+")),
    ("doi", re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+")),
    ("citation", re.compile(r"\[[0-9,\-\s]{1,30}\]")),
    ("inline_code", re.compile(r"`[^`\n]{1,200}`")),
    ("model_name", re.compile(r"\b(?:OpenAI-o1|ChatGPT-4o|GPT-4o|GPT-o1|LLM-o1|LLM-4o)\b")),
]


def normalize_protected_value(value: str) -> str:
    """归一化 TeX/PDF 文本层常见转义，避免 URL/DOI 误报缺失。"""
    normalized = str(value or "")
    normalized = re.sub(r"\\href\{([^{}]*)\}\{([^{}]*)\}", r"\1", normalized)
    normalized = re.sub(r"\\url\{([^{}]*)\}", r"\1", normalized)
    replacements = {
        r"\\_": "_",
        r"\\%": "%",
        r"\\&": "&",
        r"\\#": "#",
        r"\\$": "$",
        r"\_": "_",
        r"\%": "%",
        r"\&": "&",
        r"\#": "#",
        r"\$": "$",
        r"\{": "{",
        r"\}": "}",
        r"\textunderscore{}": "_",
        r"\textunderscore": "_",
        r"\slash{}": "/",
        r"\slash": "/",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"(?i)\bdoi\s*:\s*", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip().rstrip(".,;:")


def protected_value_present(value: str, text: str) -> bool:
    target = normalize_protected_value(value)
    if not target:
        return True
    if value in text:
        return True
    normalized_text = normalize_protected_value(text)
    if target in normalized_text:
        return True
    if "_" in target:
        flexible_target = target.replace("_", "")
        if flexible_target and flexible_target in normalized_text.replace("_", ""):
            return True
    return False


def inline_code_command_tokens(value: str) -> list[str]:
    """抽取 PDF/TeX 文本层里畸形 inline code 仍可识别的命令 token。"""
    raw = str(value or "")
    tokens: list[str] = []
    for match in re.findall(r"\\([A-Za-z@]{2,})\*?", raw):
        if match not in tokens:
            tokens.append(match)
    for match in re.findall(r"[`'\"“”‘’]\s*\\?([A-Za-z@]{2,})\\{0,2}(?:''|[’”\"'])", raw):
        if match not in tokens:
            tokens.append(match)
    return tokens


def protected_inline_code_present(value: str, text: str) -> bool:
    r"""判断 inline code 是否在译文或 LaTeX direct 写回中保留。

    PDF 抽取常把 ``\textbf'' / ``\left'' 这类 TeX 片段抽成
    `` textbf\\''、` left'' 等不完整值。严格 gate 应确认命令仍在
    译文或 translated_tex 中，而不是要求保留抽取器制造出的坏引号。
    """
    if protected_value_present(value, text):
        return True
    normalized_text = normalize_protected_value(text).lower()
    raw_text = str(text or "")
    for token in inline_code_command_tokens(value):
        token_lower = token.lower()
        if re.search(rf"\\{re.escape(token)}\*?\b", raw_text):
            return True
        if token_lower in normalized_text:
            return True
    return False


def load_json(path: Path | str | None) -> dict[str, Any]:
    if not path:
        return {}
    value = Path(path)
    if not value.exists():
        return {}
    try:
        payload = json.loads(value.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_policy_context(path_value: str | Path | None) -> dict[str, Any]:
    data = load_json(path_value)
    if not data:
        return {}
    if any(key in data for key in ["term_policy", "entity_map", "coverage_gate"]):
        return data
    return {
        "term_policy": data.get("term_policy") if isinstance(data.get("term_policy"), dict) else data,
        "entity_map": data.get("entity_map") if isinstance(data.get("entity_map"), dict) else {},
        "coverage_gate": data.get("coverage_gate") if isinstance(data.get("coverage_gate"), dict) else {},
    }


def compact_policy_items(items: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for item in items[:limit]:
        source = str(item.get("source_term") or item.get("source") or item.get("value") or "")
        translation = str(item.get("translation") or item.get("target") or "")
        if not source:
            continue
        line = f"- {source}"
        if translation:
            line += f" => {translation}"
        forbidden = item.get("forbidden_translations")
        if isinstance(forbidden, list) and forbidden:
            line += "；禁用：" + "、".join(str(value) for value in forbidden if value)
        note = str(item.get("note") or "")
        if note:
            line += f"；{note[:120]}"
        lines.append(line[:260])
    return lines


def policy_item_is_active(item: dict[str, Any]) -> bool:
    """停用或原文缺席项不得进入模型上下文，包括已有译名的条目。"""
    if item.get("active") is False or item.get("enabled") is False:
        return False
    status = str(item.get("status") or item.get("claim_status") or "").lower()
    if status in {"inactive", "absent", "rejected", "disabled"}:
        return False
    absent = {"absent", "not_found", "inactive"}
    if str(item.get("source_location") or "").lower() in absent:
        return False
    locations = item.get("source_locations")
    return not (isinstance(locations, list) and locations and
                {str(value).lower() for value in locations} <= absent)


def source_matches_policy_item(source_text: str, item: dict[str, Any]) -> bool:
    candidates = [str(item.get("source_term") or item.get("source") or item.get("value") or "")]
    aliases = item.get("aliases")
    if isinstance(aliases, list):
        candidates.extend(str(alias) for alias in aliases if alias)
    def normalize(value: str) -> str:
        # BabelDOC 的样式边界和换行可把已激活机构名切成 Human- Centered。
        value = re.sub(r"</?style\b[^>]*>", "", value, flags=re.I)
        value = re.sub(r"(?<=[A-Za-z])-\s+(?=[A-Za-z])", "-", value)
        return re.sub(r"\s+", " ", value).strip().lower()

    source_lower = normalize(source_text)
    for candidate in candidates:
        if not candidate:
            continue
        # 短拉丁缩写不能命中另一个单词的子串，例如 EU / neutral。
        candidate = normalize(candidate)
        if not candidate:
            continue
        escaped = re.escape(candidate)
        prefix = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9_]", candidate, re.I) else ""
        suffix = r"(?![a-z0-9_])" if re.search(r"[a-z0-9_]$", candidate, re.I) else ""
        if re.search(prefix + escaped + suffix, source_lower):
            return True
    return False


def prioritize_policy_items(items: list[dict[str, Any]], source_text: str, *, limit: int) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not policy_item_is_active(item):
            continue
        if source_matches_policy_item(source_text, item):
            matched.append(item)
        else:
            rest.append(item)
    # 分段翻译只注入该段实际出现的策略；无分段输入时保留文档级有效策略。
    selected = matched if source_text.strip() else rest
    return selected[:limit]


# 中译英（--target-language en）默认系统提示词。Qwen CLI 适配器在未显式传 --target-language 时，
# 以“系统提示词等于此默认值”判定目标为英文；英译中默认提示词与行为保持不变。
DEFAULT_SYSTEM_PROMPT_EN = (
    "You are a professional, authentic machine translation engine. "
    "Translate Chinese academic PDFs into fluent, natural academic English while preserving "
    "formulas, citations, URLs, named entities, terminology, and layout-sensitive placeholders. "
    "Only output the translated result without additional explanation. "
    "Do not leave Chinese characters in the output: translate all Chinese prose, headings, captions and table text "
    "into English unless they are protected spans, code, URLs, emails, or approved names. "
    "Keep the English concise, because it must fit the space of the original Chinese layout."
)

_CJK_TEXT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def normalize_target_language(value: str | None) -> str:
    return "en" if str(value or "zh").strip().lower().startswith("en") else "zh"


def policy_item_matches_target(item: dict[str, Any], target_language: str = "zh") -> bool:
    """中译英时丢弃译名/禁用译名含中文的英译中策略项，避免把英文译文引回中文。"""
    if normalize_target_language(target_language) == "zh":
        return True
    values = [item.get("translation"), *(item.get("forbidden_translations") or [])]
    return not any(_CJK_TEXT.search(str(value)) for value in values if value)


def build_policy_context_prompt(context: dict[str, Any] | None, source_text: str = "", target_language: str = "zh") -> str:
    if not context:
        return ""
    target = normalize_target_language(target_language)
    term_policy = context.get("term_policy") if isinstance(context.get("term_policy"), dict) else {}
    entity_map = context.get("entity_map") if isinstance(context.get("entity_map"), dict) else {}
    coverage_gate = context.get("coverage_gate") if isinstance(context.get("coverage_gate"), dict) else {}
    terms = term_policy.get("terms") if isinstance(term_policy.get("terms"), list) else []
    entities = entity_map.get("entities") if isinstance(entity_map.get("entities"), list) else []
    if target != "zh":
        terms = [item for item in terms if isinstance(item, dict) and policy_item_matches_target(item, target)]
        entities = [item for item in entities if isinstance(item, dict) and policy_item_matches_target(item, target)]
    terms = prioritize_policy_items(terms, source_text, limit=16)
    entities = prioritize_policy_items(entities, source_text, limit=10)
    prose_line = (
        "Translate ordinary Chinese prose completely into English; keep only protected spans, code, URLs, emails, citations, model/system names, or explicitly approved terms unchanged."
        if target == "en" else
        "Translate ordinary English prose completely; keep only protected spans, code, URLs, emails, citations, model/system names, or explicitly approved terms in English."
    )
    lines = [
        "Paper-level terminology, entity, and protected-span constraints:",
        "Use listed translations consistently when the source segment contains the term. Do not output explanations.",
        prose_line,
        "Keep supplied formatting-placeholder identifiers and citation labels attached to the corresponding translated phrases. Do not add spaces to imitate alignment or paragraph indentation.",
    ]
    lines.extend(compact_policy_items(entities, limit=10))
    lines.extend(compact_policy_items(terms, limit=16))
    if isinstance(coverage_gate, dict) and coverage_gate.get("boundary") == "sample_boundary":
        lines.append("- This input may be a trimmed evaluation sample; translate only the provided text faithfully.")
    return "\n".join(lines).strip()



def policy_note_leaks(source_text: str, translated_text: str, context: dict[str, Any] | None) -> list[str]:
    """仅识别当前策略中被逐字印入译文且源文没有的长说明，不删除文本。"""
    if not context:
        return []
    source_prose = re.sub(r"<[^>]+>", "", str(source_text or ""))
    # 源文原本就在说明翻译操作时，中文说明可能是忠实译文，不能按逐字策略匹配拒绝。
    if re.search(r"\b(?:before|when)\s+translat(?:ing|ion)\b|\b(?:if|when)\s+(?:uncertain|unsure)\b|\b(?:translation|terminology)\s+(?:instructions?|guidelines?|policy)\b|翻译前|不确定时|译法说明|翻译指令", source_prose, re.I):
        return []
    compact = lambda value: re.sub(r"\s+", "", str(value or ""))
    source, target = compact(source_text), compact(translated_text)
    leaks = []
    for key, list_key in (("term_policy", "terms"), ("entity_map", "entities")):
        collection = context.get(key)
        if not isinstance(collection, dict):
            continue
        for item in collection.get(list_key, []):
            if not isinstance(item, dict) or not policy_item_is_active(item):
                continue
            if not source_matches_policy_item(source_text, item):
                continue
            note = str(item.get("note") or "").strip()
            normalized_note = compact(note)
            if len(normalized_note) >= 12 and normalized_note not in source and normalized_note in target and note not in leaks:
                leaks.append(note)
    return leaks

def protected_values(text: str) -> list[str]:
    values: list[str] = []
    for _kind, pattern in PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0).rstrip(".,;:")
            if value and value not in values:
                values.append(value)
    return values


def missing_protected_values(source_text: str, translated_text: str) -> list[str]:
    return [value for value in protected_values(source_text) if not protected_value_present(value, translated_text)]


def restore_missing_protected_values(source_text: str, translated_text: str) -> str:
    """将源 segment 中遗漏的 URL/DOI/代码等 protected span 保守回填到译文末尾。"""
    repaired = translated_text
    for value in missing_protected_values(source_text, repaired):
        separator = "" if repaired.endswith((" ", "\n", "。", "；", ";")) else " "
        repaired = f"{repaired}{separator}{value}"
    return repaired


def dedupe_nested_person_parentheses(text: str) -> str:
    """修复“中文名（中文名（Latin Name））”这类模型重复包裹。"""
    value = str(text or "")
    pattern = re.compile(r"([\u4e00-\u9fff·]{2,})（\1（([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)+)））")
    previous = None
    while previous != value:
        previous = value
        value = pattern.sub(r"\1（\2）", value)
    return value


def apply_source_aware_replacements(source_text: str, translated_text: str, target_language: str = "zh") -> str:
    # 这些是英译中的中文译名修补；中译英输出必须原样保留（例如 Stanford University 不得改回中文）。
    if normalize_target_language(target_language) != "zh":
        return translated_text
    source_lower = source_text.lower()
    repaired = dedupe_nested_person_parentheses(translated_text)
    if repaired.strip().lower() == "he":
        return ""
    for source_term, replacements in TERM_REPLACEMENT_HINTS.items():
        match_terms = [source_term]
        if source_term == "Human-Centered AI":
            match_terms.append("Human-Centered Artificial Intelligence")
        if source_term == "Stanford Institute for Human-Centered Artificial Intelligence":
            match_terms.append("Stanford Institute for Human-Centered AI")
        if not any(term.lower() in source_lower for term in match_terms):
            continue
        for old, new in replacements:
            repaired = repaired.replace(old, new)
    for old, new in [
        ("中国香港大学", "中国香港"),
        ("he\n在全球快速全球化的背景下", "在全球化进程加速的当下"),
        ("he 在全球快速全球化的背景下", "在全球化进程加速的当下"),
    ]:
        repaired = repaired.replace(old, new)
    repaired = re.sub(r"(?m)(^|\n)he\s*\n(?=在)", r"\1", repaired)
    return repaired


def policy_literal_repairs(source_text: str, translated_text: str) -> list[dict[str, str]]:
    source_lower = source_text.lower()
    repairs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_term, replacements in TERM_REPLACEMENT_HINTS.items():
        match_terms = [source_term]
        if source_term == "Human-Centered AI":
            match_terms.append("Human-Centered Artificial Intelligence")
        if source_term == "Stanford Institute for Human-Centered Artificial Intelligence":
            match_terms.append("Stanford Institute for Human-Centered AI")
        if not any(term.lower() in source_lower for term in match_terms):
            continue
        for old, new in replacements:
            if old not in translated_text:
                continue
            key = (source_term, old, new)
            if key in seen:
                continue
            seen.add(key)
            repairs.append({"policy_source": source_term, "source": old, "target": new})
    return repairs


def enforce_protected_values(source_text: str, translated_text: str) -> str:
    missing = missing_protected_values(source_text, translated_text)
    if not missing:
        return translated_text
    raise RuntimeError("translation omitted protected spans: " + "; ".join(missing[:8]))
