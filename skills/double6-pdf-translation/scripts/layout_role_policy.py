#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import policy_utils

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by translation and layout QA CLI scripts for role-specific terminology and formatting policy."

STYLE_TAG_RE = re.compile(r"</?style\b[^>]*>", re.I)

SECTION_HEADING_TRANSLATIONS: dict[str, str] = {
    "abstract": "摘要",
    "contents": "目录",
    "introduction": "引言",
    "literature review": "文献综述",
    "methods": "方法",
    "results": "结果",
    "discussion": "讨论",
    "conclusion": "结论",
    "conclusions": "结论",
    "references": "参考文献",
    "chapter highlights": "章节要点",
    "message from the co-chairs": "联合主席致辞",
    "steering committee": "指导委员会",
    "top takeaways": "核心要点",
    "contributors": "贡献者",
    "overview": "概览",
    "research and development": "研究与开发",
    "technical performance": "技术性能",
    "responsible ai": "负责任人工智能",
    "economy": "经济",
    "science": "科学",
    "medicine": "医学",
    "education": "教育",
    "publications": "出版物",
    "patents": "专利",
    "notable ai models": "值得关注的人工智能模型",
    "by sector and organization": "按部门与组织划分",
    "by national affiliation": "按国家/地区归属划分",
    "how to cite this report": "如何引用本报告",
    "ai index report": "人工智能指数报告（AI Index Report）",
    "acknowledgements": "致谢",
    "acknowledgments": "致谢",
    "author contributions": "作者贡献",
    "competing interests": "利益冲突",
    "ethics approval": "伦理批准",
    "informed consent": "知情同意",
    "additional information": "附加信息",
    "supplementary information": "补充信息",
    "publisher's note": "出版方声明",
    "publisher’s note": "出版方声明",
}

BACKMATTER_SECTION_MARKERS = (
    "acknowledgements",
    "acknowledgments",
    "author contributions",
    "competing interests",
    "ethics approval",
    "informed consent",
    "additional information",
    "supplementary information",
    "correspondence and requests for materials",
    "reprints and permission information",
    "publisher's note",
    "publisher’s note",
    "this research was supported",
    "the authors declare no competing interests",
    "did not require ethical approval",
    "informed consent was therefore not required",
)

REPORT_LABEL_TRANSLATIONS: dict[str, str] = {
    "chair": "主席",
    "co-chair": "联合主席",
    "cochair": "联合主席",
    "members": "成员",
    "organizations": "机构",
    "co-chairs": "联合主席",
    "cochairs": "联合主席",
    "organization": "机构",
}

REPORT_ORG_HEADING_JOINERS = re.compile(r"\s*(?:,|/|\||;|\band\b)\s*", re.I)

CHART_LABEL_TRANSLATIONS: dict[str, str] = {
    "notable ai models (% of total)": "值得关注的人工智能模型（占总数百分比）",
    "notable ai models (% of total) by sector, 2003–25": "2003–25年按部门划分的值得关注的人工智能模型（占总数百分比）",
    "notable ai models (% of total) by sector, 2003-25": "2003-25年按部门划分的值得关注的人工智能模型（占总数百分比）",
    "number of notable ai models": "值得关注的人工智能模型数量",
    "number of notable ai models by select geographic areas, 2025": "2025年按选定地理区域划分的值得关注的人工智能模型数量",
    "number of notable ai models by geographic area, 2003–25 (sum)": "2003–25年按地理区域划分的值得关注的人工智能模型数量（总和）",
    "number of notable ai models by geographic area, 2003-25 (sum)": "2003-25年按地理区域划分的值得关注的人工智能模型数量（总和）",
    "number of notable ai models by geographic area, 2003–25 (sum) s": "2003–25年按地理区域划分的值得关注的人工智能模型数量（总和）",
    "number of notable ai models by geographic area, 2003-25 (sum) s": "2003-25年按地理区域划分的值得关注的人工智能模型数量（总和）",
    "number of notable ai models by organization, 2025": "2025年按组织划分的值得关注的人工智能模型数量",
    "by national affiliation": "按国家/地区归属划分",
    "by organization": "按组织划分",
    "by sector": "按部门划分",
    "by sector and organization": "按部门与组织划分",
    "by topic": "按主题划分",
    "by venue": "按发表渠道划分",
    "model release": "模型发布",
    "parameter and compute trends": "参数与计算趋势",
    "model and dataset ecosystem": "模型与数据集生态系统",
    "total number of ai publications": "人工智能出版物总数",
    "conference attendance": "会议参会情况",
    "top 100 publications": "前100篇出版物",
    "number of ai publications (in thousands)": "AI出版物数量（千）",
    "number of ai publications by select top topics, 2013–24": "2013–24年按热门主题划分的AI出版物数量",
    "number of ai publications by select top topics, 2013-24": "2013-24年按热门主题划分的AI出版物数量",
    "number of highly cited publications in top 100": "前100篇高被引出版物数量",
    "number of highly cited publications in top 100 by select geographic areas, 2021–24": "2021–24年按选定地理区域划分的前100篇高被引出版物数量",
    "number of highly cited publications in top 100 by select geographic areas, 2021-24": "2021-24年按选定地理区域划分的前100篇高被引出版物数量",
    "stars": "星标数",
    "number": "数量",
    "number of texts": "文本数量",
    "tokens": "词数",
    "mean length": "平均长度",
    "sub-corpus": "子语料库",
    "highlight: will models run out of data?": "专题：模型会耗尽数据吗？",
    "will models run out of data?": "模型会耗尽数据吗？",
    "academia": "学术界",
    "industry": "产业界",
    "nonprofit": "非营利",
    "government": "政府",
    "ai publications in cs (% of total) by sector and geographic area, 2024": "2024年按部门和地理区域划分的CS领域AI出版物占比",
    "ai publications in cs (% of total) by sector, 2013–24": "2013–24年按部门划分的CS领域AI出版物占比",
    "ai publications in cs (% of total) by sector, 2013-24": "2013-24年按部门划分的CS领域AI出版物占比",
    "global trends": "全球趋势",
    "speed of knowledge diffusion": "知识扩散速度",
    "forward citations flow": "前向引用流向",
    "citing country": "引用方国家/地区",
    "cited country": "被引用方国家/地区",
    "number of ai patents granted (in thousands)": "授权AI专利数量（千）",
    "granted ai patents (% of world total)": "授权AI专利占全球总量比例",
    "granted ai patents (% of world total) by select geographic areas, 2010–24": "2010–24年按选定地理区域划分的授权AI专利占全球总量比例",
    "granted ai patents (% of world total) by select geographic areas, 2010-24": "2010-24年按选定地理区域划分的授权AI专利占全球总量比例",
    "global distribution of forward citations to ai patents by geographic area, 2010–24": "2010–24年按地理区域划分的AI专利前向引用全球分布",
    "global distribution of forward citations to ai patents by geographic area, 2010-24": "2010-24年按地理区域划分的AI专利前向引用全球分布",
    "technological proximity": "技术接近度",
    "years since publication": "发表后年数",
    "survival probability (no citation yet)": "生存概率（尚未被引用）",
    "proximity to the united states": "与美国的技术接近度",
    "proximity to china": "与中国的技术接近度",
    "ai patent portfolios’ technological proximity to the united states and china, 2010–24": "2010–24年AI专利组合与美国和中国的技术接近度",
    "ai patent portfolios' technological proximity to the united states and china, 2010-24": "2010-24年AI专利组合与美国和中国的技术接近度",
    "ai patent examples": "AI专利示例",
    "top ai authors and inventors per 100,000 inhabitants by country, 2025": "2025年按国家划分的每10万人口顶级AI作者与发明者数量",
    "top ai authors and inventors (per 100,000 inhabitants)": "每10万人口中的顶级AI作者与发明者数量",
    "number of top ai authors and inventors (in thousands)": "顶级AI作者与发明者数量（千）",
    "by education level": "按教育水平划分",
    "by gender": "按性别划分",
    "by specialization": "按专业领域划分",
    "mobility": "流动性",
    "geographic distribution": "地理分布",
    "% of ai authors and inventors by education level": "按教育水平划分的AI作者与发明者占比",
    "percentage of top ai authors and inventors by education level and country, 2010–25": "2010–25年按教育水平和国家划分的顶级AI作者与发明者占比",
    "percentage of top ai authors and inventors by education level and country, 2010-25": "2010-25年按教育水平和国家划分的顶级AI作者与发明者占比",
    "top ai authors and inventors (% of total)": "顶级AI作者与发明者占比",
    "top ai authors and inventors (% of total) by gender, 2010–25": "2010–25年按性别划分的顶级AI作者与发明者占比",
    "top ai authors and inventors (% of total) by gender, 2010-25": "2010-25年按性别划分的顶级AI作者与发明者占比",
    "within-country distribution of top ai authors and inventors across specialization areas": "各国顶级AI作者与发明者在专业领域中的分布",
    "area of specialization": "专业领域",
    "net ǈow top ai authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
    "net flow top ai authors and inventors (12-month rolling avg.)": "顶级AI作者与发明者净流动（12个月滚动平均）",
    "net ǈow of top ai authors and inventors by country, 2010–25": "2010–25年按国家划分的顶级AI作者与发明者净流动",
    "net flow of top ai authors and inventors by country, 2010-25": "2010-25年按国家划分的顶级AI作者与发明者净流动",
}

COUNTRY_LABEL_TRANSLATIONS: dict[str, str] = {
    "China": "中国",
    "Hong Kong": "中国香港",
    "United States": "美国",
    "France": "法国",
    "United Kingdom": "英国",
    "Canada": "加拿大",
    "Germany": "德国",
    "Israel": "以色列",
    "Singapore": "新加坡",
    "South Korea": "韩国",
    "Japan": "日本",
    "Europe": "欧洲",
    "Rest of the world": "世界其他地区",
    "Denmark": "丹麦",
    "Greece": "希腊",
    "Sweden": "瑞典",
    "Luxembourg": "卢森堡",
    "Switzerland": "瑞士",
    "Australia": "澳大利亚",
    "Finland": "芬兰",
    "Netherlands": "荷兰",
    "Russia": "俄罗斯",
    "Taiwan": "中国台湾",
    "Malaysia": "马来西亚",
    "Spain": "西班牙",
    "South Africa": "南非",
    "United Arab Emirates": "阿联酋",
    "Saudi Arabia": "沙特阿拉伯",
    "India": "印度",
    "Italy": "意大利",
    "Brazil": "巴西",
    "India*": "印度*",
    "United States*": "美国*",
}

INSTITUTION_TRANSLATIONS: dict[str, str] = {
    "Stanford University": "斯坦福大学",
    "Northeastern University": "东北大学",
    "University of Minnesota": "明尼苏达大学",
    "University of Southern California": "南加州大学",
    "SRI International": "斯坦福研究院国际",
    "UNSW Sydney": "新南威尔士大学悉尼分校",
    "JPMorgan Chase & Co.": "摩根大通",
    "Schmidt Sciences": "施密特科学",
    "Brookings": "布鲁金斯学会",
    "Oxford University": "牛津大学",
    "University of Southern California": "南加州大学",
    "USC Information Sciences Institute": "南加州大学信息科学研究所",
    "Information Sciences Institute": "信息科学研究所",
    "Umeå University": "于默奥大学",
    "Umea University": "于默奥大学",
    "Google": "谷歌",
    "Salesforce": "Salesforce",
    "Anthropic": "Anthropic",
    "OECD": "经合组织（OECD）",
    "WIPO": "世界知识产权组织（WIPO）",
    "European Patent Office": "欧洲专利局",
    "European Patent Oǅce": "欧洲专利局",
}

KNOWN_LATIN_PERSON_NAMES: dict[str, tuple[str, ...]] = {
    "Yingqi Huang": ("黄颖琪", "黄颖琦"),
    "Andrew Kay Fan": ("张安德瑞", "安德瑞", "安德鲁·凯·范", "安德鲁凯范"),
}


def visible_text(text: str) -> str:
    value = str(text or "")
    value = STYLE_TAG_RE.sub(" ", value)
    value = re.sub(r"\{v\d+\}", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def strip_rich_text_tags(text: str) -> str:
    value = STYLE_TAG_RE.sub("", str(text or ""))
    value = re.sub(r"\{v\d+\}", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _looks_like_long_prose(text: str) -> bool:
    value = visible_text(text)
    if len(value) < 90:
        return False
    return bool(
        re.search(
            r"\b(?:the|this|that|these|those|chapter|report|focus(?:es)?|review(?:s)?|welcomes?|feedback|contact|models?)\b",
            value,
            flags=re.I,
        )
    )


def normalized_heading(text: str) -> str:
    value = visible_text(text)
    value = re.sub(r"\bAr\s+tificial\b", "Artificial", value, flags=re.I)
    value = re.sub(r"\b2\s+0\s+2\s+6\b", "2026", value)
    value = re.sub(r"\bRepor\s+t\b", "Report", value, flags=re.I)
    value = re.sub(r"^[\d.]+\s+", "", value)
    value = value.strip("：: .\t\r\n")
    value = re.sub(r"\b(By National Affiliation|By Organization|By Sector|By Topic|By Venue)(?:\d{1,2})\b", r"\1", value, flags=re.I)
    value = re.sub(r"\s+(?:[A-Z]|\d{1,2})$", "", value) if re.search(r"\b(?:sum|2025|area|areas|models)\b", value, flags=re.I) else value
    return re.sub(r"\s+", " ", value).lower()


def heading_number_prefix(text: str) -> str:
    match = re.match(r"^\s*((?:\d+\.)+\d*|\d+)\s+", visible_text(text))
    return match.group(1).rstrip(".") if match else ""


def report_heading_direct_output(source: str) -> str | None:
    visible = visible_text(source)
    if _looks_like_long_prose(visible):
        return None
    visible = re.sub(r"\bAr\s+tificial\b", "Artificial", visible, flags=re.I)
    visible = re.sub(r"\b2\s+0\s+2\s+6\b", "2026", visible)
    normalized = normalized_heading(source)
    if normalized == "artificial":
        return ""
    if normalized == "intelligence index report":
        return "人工智能指数报告"
    if normalized == "artificial intelligence":
        return "人工智能指数报告"
    year_match = re.fullmatch(r"(?i)ai index report\s+(20\d{2})", normalized)
    if year_match:
        return f"人工智能指数报告 {year_match.group(1)}"
    cover_match = re.search(r"(?i)\bartificial\s+intelligence\s+index\s+report\b", visible)
    cover_year = re.search(r"\b20\d{2}\b", visible)
    if cover_match:
        return f"人工智能指数报告 {cover_year.group(0)}" if cover_year else "人工智能指数报告"
    if normalized in SECTION_HEADING_TRANSLATIONS:
        prefix = heading_number_prefix(source)
        return f"{prefix} {SECTION_HEADING_TRANSLATIONS[normalized]}".strip() if prefix else SECTION_HEADING_TRANSLATIONS[normalized]
    if normalized in REPORT_LABEL_TRANSLATIONS:
        return REPORT_LABEL_TRANSLATIONS[normalized]
    parts = [
        visible_text(part).strip(" :;|,")
        for part in re.split(r"\{v\d+\}|\||\n|,", str(source or ""))
        if visible_text(part).strip(" :;|,")
    ]
    if len(parts) <= 1:
        return None
    translated_parts: list[str] = []
    changed = False
    for part in parts:
        key = normalized_heading(part)
        if key in SECTION_HEADING_TRANSLATIONS:
            prefix = heading_number_prefix(part)
            translated = SECTION_HEADING_TRANSLATIONS[key]
            translated_parts.append(f"{prefix} {translated}".strip() if prefix else translated)
            changed = True
            continue
        if key in REPORT_LABEL_TRANSLATIONS:
            translated_parts.append(REPORT_LABEL_TRANSLATIONS[key])
            changed = True
            continue
        if re.fullmatch(r"(?i)ai index report\s+20\d{2}", key):
            year = re.search(r"20\d{2}", part)
            translated_parts.append(f"人工智能指数报告 {year.group(0)}".strip() if year else "人工智能指数报告")
            changed = True
            continue
        translated_parts.append(part)
    return " | ".join(translated_parts) if changed else None


def classify_babeldoc_item(item: dict[str, Any], *, references_mode: bool = False) -> str:
    source = str(item.get("input") or "")
    visible = visible_text(source)
    lowered = visible.lower()
    layout_label = str(item.get("layout_label") or "").lower()
    heading = normalized_heading(source)
    if is_backmatter_section(source):
        return "backmatter_section"
    if layout_label in {"email_footer", "affiliation_footer", "running_header", "running_footer", "doi_line", "open_badge", "author_line", "institution_line"}:
        return layout_label
    if layout_label in {"table_header", "table_cell", "table_caption"}:
        return layout_label
    if layout_label == "cover_year" or re.fullmatch(r"20\d{2}", heading):
        return "cover_year"
    if layout_label in {"toc_entry", "chapter_index_entry", "toc_page_number"}:
        return layout_label
    if layout_label in {"report_org_heading", "institution_label"}:
        return layout_label
    if references_mode and not is_open_access_license(source) and looks_like_reference_entry(source):
        return "references_entry"
    if is_doi_line(source):
        return "doi_line"
    if is_open_badge(source):
        return "open_badge"
    if is_email_footer(source):
        return "email_footer"
    if is_affiliation_footer(source):
        return "affiliation_footer"
    if is_running_header(source, layout_label):
        return "running_header"
    if is_report_org_heading(source):
        return "report_org_heading"
    has_report_heading_structure = bool(re.search(r"\{v\d+\}|\||,", source))
    report_direct_output = report_heading_direct_output(source)
    if report_direct_output is not None and (
        has_report_heading_structure or re.fullmatch(r"(?i)ai index report\s+20\d{2}", heading)
        or re.search(r"(?i)\b(?:artificial|ar\s+tificial)\s+intelligence\s+index\s+report\b", visible)
        or heading in {"artificial", "intelligence index report", "artificial intelligence"}
    ):
        if "references" in heading and heading.strip() == "references":
            return "references_heading"
        return "report_heading"
    if heading in {"sub-corpus", "number of texts", "tokens", "mean length"}:
        return "table_header"
    if heading in CHART_LABEL_TRANSLATIONS:
        return "chart_label"
    if heading in SECTION_HEADING_TRANSLATIONS:
        return "references_heading" if heading == "references" else "section_heading"
    if heading in REPORT_LABEL_TRANSLATIONS:
        return "report_org_heading"
    if is_chart_or_table_label(source, layout_label):
        return "chart_label"
    if is_example_block(source):
        return "example_block"
    if re.fullmatch(r"[A-Z]", visible) and layout_label in {"dropcap", "drop_cap", "formula", "abandon", "fallback_line", ""}:
        return "drop_cap"
    if is_institution_line(source):
        return "institution_label"
    if is_author_line(source):
        return "author_line"
    if is_numbered_question_list(source):
        return "numbered_question_list"
    if references_mode and not is_open_access_license(source):
        return "references_entry"
    if looks_like_reference_entry(source):
        return "references_entry"
    return "body_prose"


def is_doi_line(text: str) -> bool:
    value = visible_text(text)
    if not re.search(r"https?://doi\.org/\S+|\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", value, flags=re.I):
        return False
    if re.search(r"https?://doi\.org/|\b(?:HUMA|HUMANITIES|s41599)\b", value, flags=re.I) and len(value) <= 140:
        return True
    residue = re.sub(r"https?://doi\.org/\S+|\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", " ", value, flags=re.I)
    residue = re.sub(r"\bdoi\b|[():：,.;|\-\s]+", " ", residue, flags=re.I).strip()
    return not re.search(r"[A-Za-z]{3,}", residue)


def is_open_badge(text: str) -> bool:
    return visible_text(text).strip().upper() == "OPEN"


def is_running_header(text: str, layout_label: str = "") -> bool:
    value = visible_text(text)
    if len(value) > 100:
        return False
    lowered = value.lower()
    header_hit = any(
        needle in lowered
        for needle in [
            "humanities and social sciences communications",
            "humanities and social sciences",
            "nities and social sciences",
            "s41599",
        ]
    )
    return header_hit and layout_label in {"abandon", "fallback_line", "header", "footer", ""}


def is_chart_or_table_label(text: str, layout_label: str = "") -> bool:
    value = visible_text(text)
    normalized = normalized_heading(value)
    if normalized in CHART_LABEL_TRANSLATIONS:
        return True
    if len(value) > 90:
        return False
    if normalized in {"number", "notable ai models (% of total)"}:
        return True
    if any(normalized == country.lower() for country in COUNTRY_LABEL_TRANSLATIONS):
        return True
    if re.search(r"\b(?:notable ai models|number of notable ai models|models \(% of total\)|ai publications|conference attendance|ai patents|patents \(% of world total\)|forward citations|citing country|cited country|global trends|technological proximity|proximity to (?:the united states|china)|survival probability|years since publication|top ai authors and inventors|ai authors and inventors by education level|net (?:ǈow|flow).+ai authors and inventors)\b", value, flags=re.I):
        return True
    if re.search(r"\b(?:by national affiliation\d*|by organization|by sector|by topic|by venue|by education level|by gender|by specialization|mobility|select geographic areas|geographic distribution|model release|parameter and compute trends|figure\s+\d+(?:\.\d+)*)\b", value, flags=re.I):
        return True
    return layout_label in {"chart", "chart_label", "table", "table_header", "table_cell", "axis", "legend"} and bool(re.search(r"[A-Za-z]{3,}", value))


def is_backmatter_section(text: str) -> bool:
    value = visible_text(text)
    if not value:
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in BACKMATTER_SECTION_MARKERS):
        return True
    heading = normalized_heading(value)
    return heading in {
        "acknowledgements",
        "acknowledgments",
        "author contributions",
        "competing interests",
        "ethics approval",
        "informed consent",
        "additional information",
        "supplementary information",
        "publisher's note",
        "publisher’s note",
    }


def is_affiliation_footer(text: str) -> bool:
    lowered = visible_text(text).lower()
    return (
        "hong kong polytechnic" in lowered
        or "hong kong polyu" in lowered
        or "university, hong kong, china" in lowered
        or "andrew.cheung@" in lowered
    )


def is_institution_line(text: str) -> bool:
    value = visible_text(text)
    if len(value) > 180:
        return False
    if re.search(r"\b(?:the|report|cites|within|from|was|were|is|are|and its|offers)\b", value, flags=re.I):
        return False
    hits = sum(1 for source in INSTITUTION_TRANSLATIONS if source.lower() in value.lower())
    return hits >= 1 and bool(re.search(r"\b(?:University|International|Institute|Sciences|Brookings)\b", value))


def is_report_org_heading(text: str) -> bool:
    value = visible_text(text)
    if not value or len(value) > 120:
        return False
    if _looks_like_long_prose(value):
        return False
    parts = [part.strip(" .,:;") for part in REPORT_ORG_HEADING_JOINERS.split(value) if part.strip(" .,:;")]
    if not parts:
        return False
    normalized_parts = [normalized_heading(part).replace(" ", "-") for part in parts]
    return all(part in REPORT_LABEL_TRANSLATIONS for part in normalized_parts)


def is_email_footer(text: str) -> bool:
    value = visible_text(text)
    if is_plain_email_contact_prose(value):
        return False
    return bool(re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", value)) or bool(
        re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", value)
    )


def is_plain_email_contact_prose(text: str) -> bool:
    value = visible_text(text)
    if not re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", value):
        return False
    return bool(
        re.search(
            r"\b(?:welcomes?|feedback|contact\s+us|please|send|write|reach|questions?|comments?|ideas?)\b",
            value,
            flags=re.I,
        )
    )


def is_author_line(text: str) -> bool:
    value = visible_text(text)
    if any(name in value for name in KNOWN_LATIN_PERSON_NAMES):
        return True
    return bool(re.fullmatch(r"(?:[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3}\s*(?:[,;&]|and)?\s*){2,}", value))


def is_numbered_question_list(text: str) -> bool:
    value = visible_text(text)
    q_count = len(re.findall(r"\bQ[1-9]\s*[:：.]", value))
    num_count = len(re.findall(r"(?:^|\s)[1-9][.)]\s+\S+", value))
    return q_count >= 2 or num_count >= 3


def is_example_block(text: str) -> bool:
    value = visible_text(text)
    return bool(re.search(r"^\s*Example\s+\d+\s*[:：]?", value, flags=re.I)) or bool(
        re.search(r"(?:^|\n)\s*(?:ST|TT|HT|NMT-GT|LLM-[A-Za-z0-9-]+)\s*[:：]", value)
    )


def looks_like_reference_entry(text: str) -> bool:
    value = visible_text(text)
    if len(value) < 45:
        return False
    year_or_doi = bool(re.search(r"\(\d{4}\)|\b\d{4}\.\s+https?://doi\.org|\bdoi\.org/", value, flags=re.I))
    author_signal = bool(re.match(r"[A-Z][A-Za-z'’-]+,\s+[A-Z]", value)) or " et al" in value.lower()
    return year_or_doi and author_signal


def is_open_access_license(text: str) -> bool:
    return visible_text(text).lower().startswith("open access this article")


def direct_output_for_role(role: str, source: str) -> str | None:
    source_clean = strip_rich_text_tags(source)
    if role == "cover_year":
        visible = visible_text(source)
        visible = re.sub(r"\b2\s+0\s+2\s+6\b", "2026", visible)
        return visible if re.fullmatch(r"20\d{2}", visible.strip()) else None
    if role == "report_heading":
        return report_heading_direct_output(source)
    if role in {"table_header", "table_cell", "table_caption"}:
        return direct_output_for_role("chart_label", source)
    if role == "toc_page_number":
        visible = visible_text(source).strip()
        return visible if re.fullmatch(r"\d{1,3}", visible) else None
    if role in {"toc_entry", "chapter_index_entry"}:
        return structured_row_direct_output(role, source)
    if role == "references_heading":
        return "参考文献"
    if role == "section_heading":
        heading = normalized_heading(source)
        translated = SECTION_HEADING_TRANSLATIONS.get(heading)
        prefix = heading_number_prefix(source)
        return f"{prefix} {translated}".strip() if translated and prefix else translated
    if role == "backmatter_section":
        return normalize_backmatter_section(source)
    if role in {"report_label", "report_org_heading"}:
        heading = normalized_heading(source)
        if heading in REPORT_LABEL_TRANSLATIONS:
            return REPORT_LABEL_TRANSLATIONS.get(heading)
        parts = [part.strip(" .,:;") for part in REPORT_ORG_HEADING_JOINERS.split(visible_text(source)) if part.strip(" .,:;")]
        translated = []
        for part in parts:
            key = normalized_heading(part).replace(" ", "-")
            target = REPORT_LABEL_TRANSLATIONS.get(key)
            if not target:
                return None
            translated.append(target)
        return " | ".join(translated) if translated else None
    if role == "chart_label":
        heading = normalized_heading(source)
        if heading == "number of notable ai models":
            return "知名AI模型数"
        if heading in CHART_LABEL_TRANSLATIONS:
            return CHART_LABEL_TRANSLATIONS[heading]
        for source_country, target_country in COUNTRY_LABEL_TRANSLATIONS.items():
            if heading == source_country.lower():
                return target_country
        value = visible_text(source).replace("\x03", " ")
        value = re.sub(r"\bFigure\s+(\d+(?:\.\d+)*)\b", r"图 \1", value, flags=re.I)
        value = re.sub(r"\bNumber of notable AI models\b", "值得关注的人工智能模型数量", value, flags=re.I)
        value = re.sub(r"\bTraining dataset size of notable AI models\b", "值得关注的人工智能模型训练数据集规模", value, flags=re.I)
        value = re.sub(r"\bTraining dataset size\b", "训练数据集规模", value, flags=re.I)
        value = re.sub(r"\bTraining time of notable AI models\b", "值得关注的人工智能模型训练时间", value, flags=re.I)
        value = re.sub(r"\bTraining time\b", "训练时间", value, flags=re.I)
        value = re.sub(r"\bTraining compute of notable AI models\b", "值得关注的人工智能模型训练计算量", value, flags=re.I)
        value = re.sub(r"\bTraining compute\b", "训练计算量", value, flags=re.I)
        value = re.sub(r"\bNumber of parameters of notable AI models\b", "值得关注的人工智能模型参数数量", value, flags=re.I)
        value = re.sub(r"\bNumber of parameters\b", "参数数量", value, flags=re.I)
        value = re.sub(r"\bParameter counts?\b", "参数数量", value, flags=re.I)
        value = re.sub(r"\bby select geographic areas\b", "按选定地理区域划分", value, flags=re.I)
        value = re.sub(r"\bby select geographic\b", "按选定地理区域划分", value, flags=re.I)
        value = re.sub(r"\bby geographic area\b", "按地理区域划分", value, flags=re.I)
        value = re.sub(r"\bby geographic\b", "按地理区域划分", value, flags=re.I)
        value = re.sub(r"\bby organization\b", "按组织划分", value, flags=re.I)
        value = re.sub(r"\bby sector and organization\b", "按部门与组织划分", value, flags=re.I)
        value = re.sub(r"\bby sector\b", "按部门划分", value, flags=re.I)
        value = re.sub(r"\bby topic\b", "按主题划分", value, flags=re.I)
        value = re.sub(r"\bby venue\b", "按发表渠道划分", value, flags=re.I)
        value = re.sub(r"\bBy National Affiliation\b", "按国家/地区归属划分", value, flags=re.I)
        value = re.sub(r"\bModel Release\b", "模型发布", value, flags=re.I)
        value = re.sub(r"\bParameter and Compute Trends\b", "参数与计算趋势", value, flags=re.I)
        value = re.sub(r"\bCompute and Infrastructure\b", "计算与基础设施", value, flags=re.I)
        value = re.sub(r"\bPerformance and Efficiency\b", "性能与效率", value, flags=re.I)
        value = re.sub(r"\bHardware for Notable Models\b", "知名模型硬件", value, flags=re.I)
        value = re.sub(r"\bGlobal Computing Capacity\b", "全球计算能力", value, flags=re.I)
        value = re.sub(r"\bData Center Power Capacity\b", "数据中心供电能力", value, flags=re.I)
        value = re.sub(r"\bData Centers\b", "数据中心", value, flags=re.I)
        value = re.sub(r"\bAI Infrastructure Beyond GPUs\b", "GPU之外的AI基础设施", value, flags=re.I)
        value = re.sub(r"\bBy Education Level\b", "按教育水平划分", value, flags=re.I)
        value = re.sub(r"\bBy Gender\b", "按性别划分", value, flags=re.I)
        value = re.sub(r"\bBy Specialization\b", "按专业领域划分", value, flags=re.I)
        value = re.sub(r"\bMobility\b", "流动性", value, flags=re.I)
        value = re.sub(r"\bGeographic Distribution\b", "地理分布", value, flags=re.I)
        value = re.sub(r"\bEnergy and Environmental Impact\b", "能源与环境影响", value, flags=re.I)
        value = re.sub(r"\bTraining\b", "训练", value, flags=re.I)
        value = re.sub(r"\bInference\b", "推理", value, flags=re.I)
        value = re.sub(r"\bPublication date\b", "发布日期", value, flags=re.I)
        value = re.sub(r"\btokens?\b", "词元", value, flags=re.I)
        value = re.sub(r"\bdays?\b", "天", value, flags=re.I)
        value = re.sub(r"\blog scale\b", "对数刻度", value, flags=re.I)
        value = re.sub(r"\bnotable AI models\b", "值得关注的人工智能模型", value, flags=re.I)
        value = re.sub(r"\bAI models\b", "人工智能模型", value, flags=re.I)
        value = re.sub(r"\bmodels\b", "模型", value, flags=re.I)
        value = re.sub(r"\bData Center Usage\b", "数据中心使用", value, flags=re.I)
        value = re.sub(r"\bOpen-Source AI Software\b", "开源AI软件", value, flags=re.I)
        value = re.sub(r"\bAI Development Activity\b", "AI开发活动", value, flags=re.I)
        value = re.sub(r"\bPublications\b", "出版物", value, flags=re.I)
        value = re.sub(r"\bSource:\s*Epoch AI\b", "来源：Epoch AI", value, flags=re.I)
        value = re.sub(r"\bChart:\s*2026 AI Index report\b", "图表：2026年人工智能指数报告", value, flags=re.I)
        value = re.sub(r"\bHighlight:\s*Will Models Run Out of Data\??", "专题：模型会耗尽数据吗？", value, flags=re.I)
        value = re.sub(r"\bData\b", "数据", value, flags=re.I)
        value = re.sub(r"\bNotable AI models \(% of total\)\b", "值得关注的人工智能模型（占总数百分比）", value, flags=re.I)
        value = re.sub(r"\bNumber\b", "数量", value, flags=re.I)
        for source_country, target_country in COUNTRY_LABEL_TRANSLATIONS.items():
            value = re.sub(rf"\b{re.escape(source_country)}\b", target_country, value, flags=re.I)
        return value if value != visible_text(source) else None
    if role == "references_entry":
        return source_clean
    if role == "example_block":
        return strip_rich_text_tags(normalize_example_heading(source))
    if role == "doi_line":
        return source_clean
    if role == "open_badge":
        return "OPEN"
    if role == "running_header":
        return source_clean
    if role == "running_footer":
        return source_clean
    if role == "affiliation_footer":
        return source_clean
    if role in {"institution_line", "institution_label"}:
        return normalize_institution_line(source)
    if role == "email_footer":
        return source_clean
    if role == "author_line":
        return source_clean
    if role == "drop_cap":
        return ""
    return None


def normalize_backmatter_section(text: str) -> str | None:
    value = visible_text(text)
    if not value:
        return None
    lowered = value.lower()
    heading = normalized_heading(value)
    if heading in SECTION_HEADING_TRANSLATIONS:
        return SECTION_HEADING_TRANSLATIONS[heading]
    if "this research was supported" in lowered and "author contributions" in lowered:
        return "\n".join(
            [
                "致谢",
                "本研究得到香港理工大学语言科学与技术系支持（资助编号：P0050978）。",
                "作者贡献",
                "Yingqi Huang：概念化、数据整理、形式分析、调查、方法论、撰写--初稿；Andrew K.F. Cheung：概念化、监督、撰写--审阅与编辑、经费获取。",
                "利益冲突",
                "作者声明不存在利益冲突。",
                "伦理批准",
            ]
        )
    if "supplementary information" in lowered and "doi.org" in lowered:
        url_match = re.search(r"https?://doi\.org/\S+", value)
        url = url_match.group(0).rstrip(".。") if url_match else "https://doi.org/10.1057/s41599-026-06630-4"
        return f"补充信息：在线版本包含补充材料，见 {url}。"
    if "correspondence and requests for materials" in lowered:
        return "通讯及材料请求请联系 Andrew Kay Fan Cheung。"
    if "reprints and permission information" in lowered:
        url_match = re.search(r"https?://\S+", value)
        url = url_match.group(0).rstrip(".。") if url_match else "http://www.nature.com/reprints"
        return f"转载与授权相关信息可于下述网址获取：{url}"
    if "publisher" in lowered and "springer nature" in lowered:
        return "出版方声明：施普林格·自然出版社对于所发表地图中的管辖权归属声明以及机构隶属关系均保持中立立场。"
    if "did not require ethical approval" in lowered:
        return "本研究未涉及以人类为对象的实验，因此无需伦理审批。"
    if "informed consent was therefore not required" in lowered:
        return "本研究未涉及人类参与者，因此无需取得知情同意。"
    if "the authors declare no competing interests" in lowered:
        return "作者声明不存在利益冲突。"
    return None


def structured_row_direct_output(role: str, source: str) -> str | None:
    heading = visible_text(source)
    page_match = re.search(r"(\s+|\.+)(\d{1,3})\s*$", heading)
    page_no = page_match.group(2) if page_match else ""
    title = heading[: page_match.start()].strip() if page_match else heading.strip()
    prefix = heading_number_prefix(title)
    title_without_prefix = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", title).strip()
    normalized = normalized_heading(title_without_prefix or title)
    translated = SECTION_HEADING_TRANSLATIONS.get(normalized) or CHART_LABEL_TRANSLATIONS.get(normalized)
    if translated:
        title_out = f"{prefix} {translated}".strip() if prefix else translated
        return f"{title_out} {page_no}".strip() if page_no else title_out

    remaining = title_without_prefix or title
    fragment_hits: list[tuple[int, str]] = []
    for mapping in (SECTION_HEADING_TRANSLATIONS, CHART_LABEL_TRANSLATIONS):
        for key, target in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            match = re.search(rf"\b{re.escape(key)}\b", remaining, flags=re.I)
            if match:
                fragment_hits.append((match.start(), target))
                remaining = re.sub(rf"\b{re.escape(key)}\b", " ", remaining, flags=re.I)
    fragments = [target for _position, target in sorted(fragment_hits, key=lambda item: item[0])]
    if not fragments:
        fallback = direct_output_for_role("chart_label", title) or direct_output_for_role("section_heading", title)
        return f"{fallback} {page_no}".strip() if fallback and page_no else fallback
    separator = "\n" if role == "chapter_index_entry" and len(fragments) > 1 else " "
    title_out = separator.join(dict.fromkeys(fragments))
    if prefix:
        title_out = f"{prefix} {title_out}".strip()
    if page_no:
        title_out = f"{title_out} {page_no}".strip()
    return title_out


def normalize_example_heading(text: str) -> str:
    return re.sub(r"\bExample\s+(\d+)\s*[:：]?", r"示例 \1：", text, count=1, flags=re.I)


def normalize_running_header(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"HUMANITIES\s+AND\s+SOCIAL\s+SCIENCES\s+COMMUNICATIONS|HUMANITIES\s+AND\s+SOCIAL\s+SCIENCES|NITIES\s+AND\s+SOCIAL\s+SCIENCES(?:\s+COMMUNICATIONS)?|HUMA(?=\s|$)",
        "人文与社会科学通讯",
        value,
        flags=re.I,
    )
    value = re.sub(r"人文与社会科学通讯\s*通讯版块", "人文与社会科学通讯", value)
    return value


def normalize_affiliation_footer(text: str) -> str:
    emails = re.findall(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", text)
    if re.search(r"andrew\.cheung@\s*$|andrew\.cheung@\b", text, flags=re.I) and "andrew.cheung@polyu.edu.hk" not in emails:
        emails.append("andrew.cheung@polyu.edu.hk")
    suffix = ("；" + "；".join(emails)) if emails else ""
    return "香港理工大学，中国香港" + suffix


def normalize_institution_line(text: str) -> str:
    value = str(text or "")
    for source, target in INSTITUTION_TRANSLATIONS.items():
        value = re.sub(re.escape(source), target, value, flags=re.I)
    return value


def role_prompt(role: str) -> str:
    common = (
        "Layout-role policy: preserve Latin personal names; preserve URLs, DOI, emails, labels, and placeholders exactly. "
        "Do not translate bibliography entries or language-comparison examples unless only the heading is explicitly mapped."
    )
    if role == "author_line":
        return common + " This item is an author line: keep author names in the Latin alphabet."
    if role == "institution_line":
        return common + " This item is an institution line: translate known institution names consistently and do not translate personal names."
    if role == "numbered_question_list":
        return common + " This item is a numbered list: keep each numbered item as a separate line or paragraph."
    return common


def postprocess_translation_for_role(role: str, source: str, translated: str) -> str:
    value = strip_rich_text_tags(policy_utils.dedupe_nested_person_parentheses(translated))
    if role not in {"affiliation_footer", "institution_line", "references_entry", "running_header"}:
        value = normalize_institution_line(value)
    if role in {"author_line", "body_prose", "numbered_question_list"} or any(name in source for name in KNOWN_LATIN_PERSON_NAMES):
        value = restore_known_latin_person_names(source, value)
    if role == "numbered_question_list":
        value = split_numbered_items(value)
    return value


def restore_known_latin_person_names(source: str, translated: str) -> str:
    value = translated
    for latin_name, bad_values in KNOWN_LATIN_PERSON_NAMES.items():
        if latin_name not in source:
            continue
        if latin_name in value:
            continue
        for bad in bad_values:
            value = value.replace(bad, latin_name)
    return value


def split_numbered_items(text: str) -> str:
    value = re.sub(r"\s+(Q[2-9]\s*[:：.])", r"\n\1", text)
    value = re.sub(r"\s+([2-9][.)]\s+)", r"\n\1", value)
    return value.strip()
