"""有界文本对的事实保真检查。结果是待裁决线索，不构成语义验收。"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import re
import unicodedata
from scanned_raster.scientific_integrity import canonical_math


NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
NUMBER_RE = re.compile(r"(?<![A-Za-zα-ωΑ-Ω0-9_.])" + NUMBER + r"(?![A-Za-zα-ωΑ-Ω0-9_]|\.\d)")
# 仅声明的 SI/时间单位可做等价换算；大小写有物理含义，不能统一 lower()。
UNITS = {
    "kg": ("mass", "1000"), "千克": ("mass", "1000"), "公斤": ("mass", "1000"),
    "g": ("mass", "1"), "克": ("mass", "1"),
    "mg": ("mass", ".001"), "毫克": ("mass", ".001"),
    "μg": ("mass", ".000001"), "µg": ("mass", ".000001"), "微克": ("mass", ".000001"),
    "L": ("volume", "1"), "升": ("volume", "1"),
    "mL": ("volume", ".001"), "ml": ("volume", ".001"), "毫升": ("volume", ".001"),
    "μL": ("volume", ".000001"), "µL": ("volume", ".000001"), "微升": ("volume", ".000001"),
    "s": ("time", "1"), "seconds": ("time", "1"), "second": ("time", "1"), "秒": ("time", "1"),
    "min": ("time", "60"), "minutes": ("time", "60"), "minute": ("time", "60"), "分钟": ("time", "60"),
    "h": ("time", "3600"), "hours": ("time", "3600"), "hour": ("time", "3600"), "小时": ("time", "3600"),
    "°C": ("temperature_c", "1"), "摄氏度": ("temperature_c", "1"),
}
UNIT_RE = re.compile(r"(?<![A-Za-z0-9_.])(?P<number>" + NUMBER + r")\s*(?P<unit>" +
                     "|".join(re.escape(x) for x in sorted(UNITS, key=len, reverse=True)) + r")(?![A-Za-z])")

# 只识别具名 A/B 模型的简单比较；同义改写、主客体交换或复杂否定仍交人工审校。
COMPARISON_METRICS = {
    "recall": ("召回率", "召回"), "precision": ("精确率", "查准率"),
    "accuracy": ("准确率", "准确度"), "error": ("误差", "错误率"),
    "latency": ("延迟", "时延"), "throughput": ("吞吐量", "吞吐率"),
    "sensitivity": ("灵敏度", "敏感度"), "specificity": ("特异度", "特异性"),
}


def comparison_direction_conflicts(source: str, target: str) -> list[str]:
    """相同具名主客体顺序下的指标方向冲突；不作一般关系推理。"""
    kind = r"(?:method|model|system|group|algorithm)"
    pattern = (r"\b" + kind + r"\s+([A-Za-z][A-Za-z0-9_-]{0,30})\s+"
               r"(?:has|had|achieved|shows|showed)\s+([^.!?;]+?)\s+than\s+"
               + kind + r"\s+([A-Za-z][A-Za-z0-9_-]{0,30})\b")
    conflicts = []
    for match in re.finditer(pattern, source, re.I):
        subject, body, comparator = match.groups()
        prefix_start = max(source.rfind(mark, 0, match.start()) for mark in ".!?;") + 1
        if re.search(r"\b(?:not|no|never|false|untrue|whether)\b", source[prefix_start:match.start()], re.I):
            continue
        if subject == comparator or re.search(r"\b(?:not|no|never)\b", body, re.I):
            continue
        position = lambda name: re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", target)
        a, b = position(subject), position(comparator)
        if not a or not b or a.start() >= b.start():
            continue
        if re.search(r"[。！？;；]", target[a.end():b.start()]):
            continue
        # 多句译文中的关系可能有别的主语；不把其它句子中的方向归给当前比较。
        sentence_start = max(target.rfind(mark, 0, a.start()) for mark in "。！？;；") + 1
        sentence_end = min([p for mark in "。！？;；" if (p := target.find(mark, b.end())) >= 0] or [len(target)])
        sentence = target[sentence_start:sentence_end]
        for direction, metric in re.findall(r"\b(higher|lower|greater|smaller|larger|less)\s+(" + "|".join(COMPARISON_METRICS) + r")\b", body, re.I):
            signs = []
            names = "|".join(re.escape(x) for x in COMPARISON_METRICS[metric.lower()])
            for found in re.finditer(names, sentence):
                tail = sentence[found.end():found.end()+24]
                tail = re.split(r"[，,。;；！？]", tail, maxsplit=1)[0]
                marker = re.search(r"(?:更|较|均|都)?(?:高于|低于|更高|更低|较高|较低|大于|小于)", tail)
                if marker:
                    prefix = tail[:marker.start()]
                    if re.search(r"不|未|无|没|非", prefix):
                        continue
                    signs.append(1 if re.search(r"高|大", marker.group()) else -1)
            expected = 1 if direction.lower() in {"higher", "greater", "larger"} else -1
            if signs and set(signs) == {-expected}:
                conflicts.append(f"{subject}/{comparator}: {direction} {metric}")
    return conflicts



def causal_possibility_missing(source: str, target: str) -> bool:
    """限定范围的审校线索：可能因果在短译句中缺少对应限定。

    只处理具名因果谓词，不将一般能力 can、月份 May 或不均匀等
    描述认作限定。含等价限定或否定的译句交完整语义审校；本函数
    不证明限定的作用域，也不自动改写或拒绝译文。
    """
    if not re.search(r"[\u3400-\u9fff]", target):
        return False
    pattern = re.compile(
        r"\b(?:can|could|may|might)\s+"
        r"(?:(?:potentially|possibly|sometimes|also|even|directly|indirectly)\s+){0,2}"
        r"(?:result\s+in|lead\s+to|cause|trigger|induce|bring\s+about)\b", re.I)
    causal = False
    for match in pattern.finditer(source):
        start = max(source.rfind(mark, 0, match.start()) for mark in ".!?;\n") + 1
        prefix = source[start:match.start()]
        if re.search(r"\b(?:not|never|whether|deny|denies|denied|false|untrue)\b", prefix, re.I):
            continue
        causal = True
        break
    if not causal:
        return False
    # 有其它主张的长译文或存在作用域疑点时，保留给人工逐句对齐。
    if len(target) > 400:
        return False
    retained = re.search(
        r"可能|或许|也许|大概|不排除|未必|不一定|有可能|有时|偶尔|"
        r"(?:可以|能够|能|可)(?:会)?(?:导致|引发|诱发|造成|触发)|"
        r"推测|推断|假[说设]|\b(?:can|could|may|might)\b", target, re.I)
    if retained:
        return False
    for match in re.finditer(r"导致|引发|诱发|造成|触发", target):
        prefix = target[max(0, match.start()-6):match.start()]
        if not re.search(r"(?:不|未|无|没|难以|避免|防止)(?:会|能|可|曾)?$", prefix):
            return True
    return False

def condition_logic_hints(source: str, target: str) -> tuple[bool, bool]:
    """only 条件限定和两个相同数字条件之间的 and/or 线索。"""
    if not re.search(r"[\u3400-\u9fff]", target):
        return False, False
    match = re.search(r"\bonly\s+(?:at|when|if|under|in)\b(.+)", source, re.I)
    if not match or re.search(r"\bnot\s*$", source[:match.start()], re.I):
        return False, False
    conditions = re.split(r"[;!?]|\.(?=\s|$)", match.group(1), maxsplit=1)[0]
    missing_only = not bool(re.search(r"仅|只|唯|必须|必需|须.{0,20}才|才(?:会|能|发生|出现|成立)", target))
    numbers = list(NUMBER_RE.finditer(conditions))
    changed_join = False
    for left, right in zip(numbers, numbers[1:]):
        if not re.search(r"\band\b", conditions[left.end():right.start()], re.I):
            continue
        if decimal(left.group()) == decimal(right.group()):
            continue
        target_numbers = list(NUMBER_RE.finditer(target))
        left_matches = [m for m in target_numbers if decimal(m.group()) == decimal(left.group())]
        right_matches = [m for m in target_numbers if decimal(m.group()) == decimal(right.group())]
        if len(left_matches) != 1 or len(right_matches) != 1:
            continue
        first, second = sorted([left_matches[0], right_matches[0]], key=lambda m:m.start())
        between = target[first.end():second.start()]
        if re.search(r"或|任一|二者之一", between) and not re.search(r"[。;；！？]", between):
            changed_join = True
    return missing_only, changed_join


def decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def normalized(text: str) -> str:
    text = canonical_math(unicodedata.normalize("NFKC", text).replace("−", "-"))
    months = ["Jan(?:uary)?", "Feb(?:ruary)?", "Mar(?:ch)?", "Apr(?:il)?", "May", "Jun(?:e)?", "Jul(?:y)?", "Aug(?:ust)?", "Sep(?:t(?:ember)?)?", "Oct(?:ober)?", "Nov(?:ember)?", "Dec(?:ember)?"]
    for number, month in enumerate(months, 1):
        # 只处理后面跟日期/年份的英文月份，避免把情态动词 may 当数字。
        text = re.sub(r"\b" + month + r"\.?\s*,?\s*(?=\d)", f" {number} ", text, flags=re.I)
    text = re.sub(r"\bP\.\s*(?=\d)", " ", text)
    # 文末/词尾上标引用常被 OCR 粘到普通单词；单字母变量仍由科学符号检查负责。
    text = re.sub(r"(?<!\\)\b([A-Za-z]{2,})(\d+)(?![A-Za-z0-9])", r"\1 \2", text)
    # 引用标识由 protected-span 检查负责，避免 DOI/URL 被当成实验数字。
    return re.sub(r"https?://\S+|\b10\.\d{4,9}/\S+|\\(?:cite\w*|ref|eqref)\{[^}]*\}", " ", text)


def quantities_and_remainder(text: str) -> tuple[Counter, str]:
    quantities: Counter = Counter()
    def remove(match: re.Match) -> str:
        dimension, factor = UNITS[match['unit']]
        quantities[(dimension, decimal(match['number']) * Decimal(factor))] += 1
        return " "
    return quantities, UNIT_RE.sub(remove, text)


def numeric_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.count("|") < 2:
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if any(re.fullmatch(NUMBER, x) for x in cells):
            rows.append(cells)
    return rows


def invariant_findings(source: str, translation: str) -> list[dict]:
    """英文到中文的线索；超过 4000 字符需由调用者先提供对齐 block。"""
    if not source.strip() or not translation.strip() or max(len(source), len(translation)) > 4000:
        return []
    source, translation = normalized(source), normalized(translation)
    findings = []
    def add(rule: str, title: str, detail: str, severity: str = "medium") -> None:
        findings.append({"rule": rule, "severity": severity, "title": title, "detail": detail,
                         "source_evidence": source[:500], "translation_evidence": translation[:500],
                         "suggestion": "核对对应原文、译文及最终 PDF；等价表达可凭具体证据裁决，不自动改写译文。"})

    if causal_possibility_missing(source, translation):
        add("causal_possibility_missing", "可能因果的限定可能遗漏", "原文 can/could/may/might 与 result in/lead to/cause/trigger/induce 等因果谓词相连，短译文出现因果谓词但未见等价限定；须独立核对完整句子及限定作用域。")

    source_q, source_rest = quantities_and_remainder(source)
    target_q, target_rest = quantities_and_remainder(translation)
    # 集合而非出现次数：自然翻译可将同一数值再叙述一次。
    if set(source_q) != set(target_q) and source_q:
        add("quantity_unit_drift", "数值与单位组合不一致", "声明支持的质量、体积、时间或温度单位经等价换算后仍不一致。", "high")
    # 上下标身份和公式应由科学符号层审校，避免把指数误当正文实验数值。
    source_rest = re.sub(r"\^\s*\{\s*\d+\s*\}", "", source_rest)
    target_rest = re.sub(r"\^\s*\{\s*\d+\s*\}", "", target_rest)
    source_numbers = {decimal(m.group()) for m in NUMBER_RE.finditer(source_rest)}
    target_numbers = {decimal(m.group()) for m in NUMBER_RE.finditer(target_rest)}
    if source_numbers != target_numbers and source_numbers:
        add("numeric_value_drift", "数字事实需要核对", "对齐文本中的独立数字值不一致；中文数词、范围压缩、未声明单位或格式转换需要人工裁决。")

    source_rows, target_rows = numeric_table(source), numeric_table(translation)
    if source_rows and target_rows:
        numeric_positions = lambda rows: [[decimal(cell) if re.fullmatch(NUMBER, cell) else None for cell in row] for row in rows]
        if numeric_positions(source_rows) != numeric_positions(target_rows):
            add("table_numeric_cell_drift", "表格数字的行列位置改变", "按原表行列顺序比较单元格，检测到数字移动、替换或行列缺失；有意重排必须另行提供映射。", "high")

    # 只在整个短文本没有任何否定对应时提示；不声称已验证否定的作用域。
    negative_source = re.sub(r"\bnot\s+(?:only|just|merely)\b", "", source, flags=re.I)
    has_negative = re.search(r"\b(?:not|cannot|can't|isn't|aren't|doesn't|don't|didn't|won't|never|impossible|untested|unproven)\b", negative_source, re.I)
    negative_target = re.search(r"不|未|无|非|没|否|难以|缺乏|尚待|有待|尚需|尚须|禁止|拒绝|避免|失败|不可能|负值|负数", translation)
    if has_negative and re.search(r"[\u3400-\u9fff]", translation) and not negative_target:
        add("negative_meaning_missing", "源文否定或未验证状态可能遗漏", "源文存在否定、不可成立或尚未验证的表达，短译文中未找到对应线索；须核对具体谓词和否定作用域。")
    conflicts = comparison_direction_conflicts(source, translation)
    if conflicts:
        add("comparison_direction_conflict", "具名对象的指标比较方向可能颠倒", "同一主客体顺序下识别到相反方向：" + "; ".join(conflicts) + "；须复核省略主语、作用域及等价倒装。")
    missing_only, changed_join = condition_logic_hints(source, translation)
    if missing_only:
        add("exclusive_condition_missing", "条件的排他限定可能遗漏", "原文 only at/when/if/under/in 条件在译文中缺少对应限定线索；须复核必要条件与充分条件，不自动补词。")
    if changed_join:
        add("condition_conjunction_changed", "共同条件可能被改成任选条件", "原文两个数字条件之间的 and，在译文对应数字之间出现或/任一；须核对条件边界与作用域。")
    return findings
