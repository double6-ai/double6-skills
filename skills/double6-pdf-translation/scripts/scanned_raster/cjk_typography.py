"""按实际字体宽度换行；中文可逐字断行，短变量/比较式保持连续。"""
from __future__ import annotations

import re
from typing import Callable


NO_START = set("，。！？；：、）》】」』”’…％%.,!?;:)]}")
NO_END = set("（《【「『“‘([{“")
LATIN_ATOM = r"[A-Za-z\u00c0-\u024f\u0300-\u036fα-ωΑ-Ω0-9_.'’′″/+-]+"
DATE_ATOM = r"(?<!\d)\d{4}年(?:\d{1,2}月(?:\d{1,2}日)?)?"
TOKEN = re.compile(rf"{DATE_ATOM}|{LATIN_ATOM}(?:[ \t]*[=±≠≤≥<>][ \t]*{LATIN_ATOM})*|[^\n]", re.UNICODE)


def wrap_mixed_text(text: str, width: float, measure: Callable[[str], float]) -> str:
    result: list[str] = []
    for paragraph in text.split("\n"):
        tokens = TOKEN.findall(paragraph)
        line: list[str] = []
        for token in tokens:
            if line and measure("".join(line) + token) > width:
                # 移动行尾开标点；闭标点则与前一文字单元一同移到下一行。
                carry: list[str] = []
                if token[:1] in NO_START:
                    while line:
                        previous = line.pop()
                        carry.insert(0, previous)
                        if previous not in NO_START and previous not in {" ", "\t"}:
                            break
                while line and line[-1] in NO_END:
                    carry.insert(0, line.pop())
                if line:
                    result.append("".join(line).rstrip(" \t"))
                    line = carry
                else:
                    line = carry
            if token in {" ", "\t"} and not line:
                continue
            line.append(token)
        result.append("".join(line).rstrip(" \t"))
    return "\n".join(result)
