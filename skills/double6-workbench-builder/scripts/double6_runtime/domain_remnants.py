"""跨场景领域残留与假提交语气扫描。

来源：build-professional-workbench 的教育词残留门和「不得把本地操作写成已外发」。
不复制对方词表；只拦本 Skill 已经炸过、或会把邻域壳套过来的说法。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
NEGATION = ("不是", "不会", "未", "没有", "待", "禁止", "不得", "别把", "也不", "不能", "先不", "仍不是", "还不是")

# 假外发/假上线：出现时，前文一小段必须有否定，否则算残留。
FAKE_SUBMIT_CLAIMS = (
    "学校审核中",
    "进入学校审核队列",
    "已提交到学校",
    "已发家长",
    "已发送到家长群",
    "已上报平台",
    "已同步到云",
    "已经上线",
    "已经安装",
    "数据永不丢失",
    "连接银行",
    "连接店铺",
    "自动报税",
    "自动发货",
    "自动退款",
)

# 只允许出现在对应域的运行时文件或该场景候选里。
FAMILY_OWN_TERMS: dict[str, tuple[str, ...]] = {
    "education-learning": ("今晚三站", "小卖部", "伙伴还在等", "光之勇士"),
    "teaching-classroom": ("今日班务", "待人工发"),
    "finance-tax-contract": ("不是银行余额", "待专业处理"),
    "ecommerce-operations": ("不是实时库存", "待在平台回"),
    "fitness-nutrition": ("保证瘦下来",),
}

# 其它域的运行时不得出现这些词。
FAMILY_FOREIGN_TERMS: dict[str, tuple[str, ...]] = {
    "education-learning": ("已申报", "连接银行", "已发货", "连接店铺"),
    "teaching-classroom": ("今晚三站", "小卖部", "小狗挨饿", "勾第 1 组", "保证上岸"),
    "finance-tax-contract": ("今晚三站", "小卖部", "已发货", "连接店铺", "自动报税", "永不丢失"),
    "ecommerce-operations": ("今晚三站", "小卖部", "连接银行", "自动退款", "实时库存"),
    "fitness-nutrition": ("今晚三站", "小卖部", "班务", "已申报"),
    "exam-preparation": ("今晚三站", "保证上岸", "真题"),
    "content-operations": ("今晚三站", "已发布到平台"),
    "sales-trade": ("今晚三站", "预测成交"),
    "household-collaboration": ("今晚三站", "已发送给对方"),
    "research-knowledge": ("今晚三站", "无来源已证实"),
    "personal-execution": ("今晚三站", "小卖部"),
}

FILE_FAMILY = {
    "child_playground.py": "education-learning",
    "teacher-class-runtime-v1.helpers.js": "teaching-classroom",
    "teacher-class-runtime-v1.listeners.js": "teaching-classroom",
    "finance-bookkeeping-runtime-v1.helpers.js": "finance-tax-contract",
    "finance-bookkeeping-runtime-v1.listeners.js": "finance-tax-contract",
    "commerce-order-runtime-v1.helpers.js": "ecommerce-operations",
    "commerce-order-runtime-v1.listeners.js": "ecommerce-operations",
    "fitness-daily-runtime-v1.helpers.js": "fitness-nutrition",
    "fitness-daily-runtime-v1.listeners.js": "fitness-nutrition",
    "exam-practice-runtime-v1.helpers.js": "exam-preparation",
    "exam-practice-runtime-v1.listeners.js": "exam-preparation",
    "content-pipeline-runtime-v1.helpers.js": "content-operations",
    "content-pipeline-runtime-v1.listeners.js": "content-operations",
    "sales-pipeline-runtime-v1.helpers.js": "sales-trade",
    "sales-pipeline-runtime-v1.listeners.js": "sales-trade",
    "household-handoff-runtime-v1.helpers.js": "household-collaboration",
    "household-handoff-runtime-v1.listeners.js": "household-collaboration",
    "research-evidence-runtime-v1.helpers.js": "research-knowledge",
    "research-evidence-runtime-v1.listeners.js": "research-knowledge",
    "personal-week-runtime-v1.helpers.js": "personal-execution",
    "personal-week-runtime-v1.listeners.js": "personal-execution",
}

SCENE_FAMILY_PREFIX = (
    ("scene.education-learning.", "education-learning"),
    ("scene.teaching-classroom.", "teaching-classroom"),
    ("scene.finance-tax-contract.", "finance-tax-contract"),
    ("scene.ecommerce-operations.", "ecommerce-operations"),
    ("scene.fitness-nutrition.", "fitness-nutrition"),
    ("scene.exam-preparation.", "exam-preparation"),
    ("scene.content-operations.", "content-operations"),
    ("scene.sales-trade.", "sales-trade"),
    ("scene.household-collaboration.", "household-collaboration"),
    ("scene.research-knowledge.", "research-knowledge"),
    ("scene.personal-execution.", "personal-execution"),
)


def family_for_scene(scene_id: str) -> str | None:
    text = str(scene_id or "")
    for prefix, family in SCENE_FAMILY_PREFIX:
        if text.startswith(prefix):
            return family
    return None


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - 24) : start]
    if any(token in window for token in NEGATION):
        return True
    return start > 0 and text[start - 1] == "不"


def find_fake_submit_claims(text: str) -> list[str]:
    hits: list[str] = []
    for claim in FAKE_SUBMIT_CLAIMS:
        start = 0
        while True:
            index = text.find(claim, start)
            if index < 0:
                break
            if not _negated(text, index):
                hits.append(claim)
                break
            start = index + len(claim)
    return hits


def find_foreign_terms(text: str, family: str | None) -> list[str]:
    if not family:
        return []
    forbidden = FAMILY_FOREIGN_TERMS.get(family, ())
    hits: list[str] = []
    for term in forbidden:
        index = text.find(term)
        if index < 0:
            continue
        if _negated(text, index):
            continue
        hits.append(term)
    return hits


def audit_text(text: str, *, family: str | None = None, origin: str = "") -> list[str]:
    errors: list[str] = []
    label = origin or "文本"
    for claim in find_fake_submit_claims(text):
        errors.append(f"{label} 把本地动作写成已经外发：{claim}")
    for term in find_foreign_terms(text, family):
        errors.append(f"{label} 泄漏邻域说法：{term}")
    return errors


def iter_runtime_sources(root: Path | None = None) -> Iterable[tuple[Path, str]]:
    skill = root or PACKAGE_ROOT
    yield skill / "scripts" / "double6_runtime" / "child_playground.py", "education-learning"
    runtime_dir = skill / "references" / "runtimes"
    for name, family in FILE_FAMILY.items():
        if name.endswith(".js"):
            path = runtime_dir / name
            if path.is_file():
                yield path, family


def audit_skill_sources(root: Path | None = None) -> list[str]:
    skill = root or PACKAGE_ROOT
    errors: list[str] = []
    for path, family in iter_runtime_sources(skill):
        text = path.read_text(encoding="utf-8")
        errors.extend(audit_text(text, family=family, origin=path.name))
    builder = skill / "scripts" / "double6_runtime" / "builder.py"
    if builder.is_file():
        errors.extend(audit_text(builder.read_text(encoding="utf-8"), family=None, origin="builder.py"))
    return errors


def audit_candidate_html(html: str, scene_id: str) -> list[str]:
    return audit_text(html, family=family_for_scene(scene_id), origin="候选页")
