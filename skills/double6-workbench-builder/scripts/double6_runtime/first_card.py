"""机器版「第一张卡像不像这个人的活」（good-workbench.md 判定问题 7）。

两路信号：
1. 第一张卡（开箱种子 + 主模块第一条开箱内容）不得写成制作器自己的设计理由；
2. 内容运营里用户点名了平台时，页面平台必须恰好是这些平台。
"""

from __future__ import annotations

import re
from typing import Any

from .platforms import requested_platforms, request_text

# 制作器在讲自己怎么设计，而不是使用者今晚的活。
BUILDER_RATIONALE_PATTERNS = (
    re.compile(r"工作台(?:不能|不该|应该|必须)"),
    re.compile(r"先(?:让人)?填表"),
    re.compile(r"先填来源箱"),
    re.compile(r"首页(?:能|要|必须|不能)"),
    re.compile(r"(?:制作器|验收标准|开箱卡|记录表单|残留表单)"),
    re.compile(r"打开工具先被要求"),
    re.compile(r"总在记选题"),
)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def first_card_texts(product: dict[str, Any]) -> list[str]:
    pack = ((product.get("recommendation_plan") or {}).get("composition_contract") or {}).get("pack") or {}
    texts: list[str] = []
    for seed in pack.get("tonight_seeds") or []:
        values = dict(seed.get("values") or {})
        values.pop("notes", None)
        texts.extend(_strings(values))
    primary_id = (product.get("design_brief") or {}).get("primary_capability_id")
    for capability in product.get("capabilities", []):
        if capability.get("capability_id") != primary_id:
            continue
        items = ((capability.get("starter") or {}).get("starter_items") or [])[:1]
        for item in items:
            texts.extend(_strings({key: item.get(key) for key in ("title", "body")}))
    return texts


def check_first_card(product: dict[str, Any], html: str) -> list[str]:
    errors: list[str] = []
    hits = sorted({match.group(0) for text in first_card_texts(product) for pattern in BUILDER_RATIONALE_PATTERNS for match in pattern.finditer(text)})
    if hits:
        errors.append(f"第一张卡写成了制作器的设计理由，不像使用者自己的活：{hits[:5]}")
    pack = ((product.get("recommendation_plan") or {}).get("composition_contract") or {}).get("pack") or {}
    if pack.get("domain_id") == "content-operations" or "data-content-tonight-board" in html:
        wanted = [name for _, name, _ in requested_platforms(request_text(product))]
        row = re.search(r"data-creator-platforms='([a-z]+)'>(.*?)</div>", html, re.S)
        if wanted:
            shown = re.findall(r"</i>([^<]+)</span>", row.group(2)) if row else []
            if not row or row.group(1) != "request" or shown != wanted:
                errors.append(f"内容运营平台没有跟随用户原话：要 {wanted}，页面是 {shown}")
    return errors
