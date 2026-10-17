"""1.2.1 用户决策回归：减脂不预填、平台跟随原话、自用健康不问授权、第一张卡机器检查。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from double6_runtime import routing  # noqa: E402
from double6_runtime.first_card import check_first_card  # noqa: E402
from double6_runtime.platforms import creator_platforms, requested_platforms  # noqa: E402

PACKS = json.loads((SKILL_ROOT / "references" / "workbench-composition-packs.json").read_text(encoding="utf-8"))


def _pack(composition_id: str) -> dict:
    return next(row for row in PACKS["packs"] if row.get("composition_id") == composition_id)


def _product(text: str, pack: dict, first_item: dict | None = None) -> dict:
    capability = {"capability_id": "cap-1", "starter": {"starter_items": [first_item] if first_item else []}}
    return {
        "facts": [{"text": text}],
        "design_brief": {"primary_capability_id": "cap-1"},
        "capabilities": [capability],
        "recommendation_plan": {"composition_contract": {"pack": pack}},
    }


def _platform_html(kind: str, names: list[str]) -> str:
    chips = "".join(f"<span class='platform-chip'><i aria-hidden='true'>x</i>{name}</span>" for name in names)
    return f"<div data-content-tonight-board></div><div class='platform-row' data-creator-platforms='{kind}'>{chips}</div>"


class FitnessSeedTests(unittest.TestCase):
    def test_fitness_pack_has_no_prefilled_records(self) -> None:
        for pack in PACKS["packs"]:
            if pack.get("domain_id") == "fitness-nutrition" or "fitness" in str(pack.get("composition_id")):
                self.assertFalse([s for s in pack.get("tonight_seeds") or [] if str(s.get("module_id", "")).startswith("fitness-")])


class PlatformTests(unittest.TestCase):
    def test_request_platforms_exact_and_ordered(self) -> None:
        names = [name for _, name, _ in requested_platforms("我一个人做小红书和B站的科技测评账号")]
        self.assertEqual(names, ["小红书", "B站"])
        chips, week, from_request = creator_platforms({"facts": [{"text": "做小红书和B站"}]})
        self.assertTrue(from_request)
        self.assertEqual([name for _, name in chips], ["小红书", "B站"])
        self.assertTrue({where for _, _, where in week[:4]} <= {"小红书", "B站"})

    def test_default_only_when_none_named(self) -> None:
        chips, _, from_request = creator_platforms({"facts": [{"text": "做个自媒体内容工作台"}]})
        self.assertFalse(from_request)
        self.assertGreater(len(chips), 2)


class SelfUseHealthTests(unittest.TestCase):
    def _route(self, text: str) -> dict:
        return routing.route_request(text, {"primary_domain": "fitness-nutrition", "profile_id": "fitness-fat-loss", "evidence_spans": ["减脂"]})

    def test_self_use_fat_loss_skips_privacy_question(self) -> None:
        text = "我在减脂，想每天记体重、三餐吃了什么和有没有运动，做个自己用的小工具。"
        route = self._route(text)
        self.assertNotIn("privacy-boundary", [row["decision_id"] for row in routing.critical_decisions(text, route)])
        default = next(row for row in routing.safe_defaults(text, route) if row["decision_id"] == "privacy-boundary")
        self.assertEqual(default["value"], "self_owned_local_only")

    def test_other_people_keep_existing_rules(self) -> None:
        text = "我是健身教练，要给会员减脂，每天记他们的体重。"
        route = self._route(text)
        self.assertFalse(routing.is_self_use_health(text, route))
        default = next(row for row in routing.safe_defaults(text, route) if row["decision_id"] == "privacy-boundary")
        self.assertEqual(default["value"], "synthetic_or_redacted")


class FirstCardCheckTests(unittest.TestCase):
    def test_shipped_content_pack_passes(self) -> None:
        pack = _pack("composition.content.idea-to-publish-v1") if any(p.get("composition_id") == "composition.content.idea-to-publish-v1" for p in PACKS["packs"]) else next(p for p in PACKS["packs"] if p.get("domain_id") == "content-operations")
        product = _product("我做小红书和B站", pack)
        self.assertEqual(check_first_card(product, _platform_html("request", ["小红书", "B站"])), [])

    def test_planted_builder_rationale_is_caught(self) -> None:
        pack = {"domain_id": "content-operations", "tonight_seeds": [{"module_id": "content-topics", "values": {"title": "为什么工作台不能先让人填表"}}]}
        errors = check_first_card(_product("做个内容台", pack), _platform_html("default", ["小红书"]))
        self.assertTrue(any("设计理由" in row for row in errors))

    def test_planted_wrong_platforms_are_caught(self) -> None:
        pack = {"domain_id": "content-operations"}
        errors = check_first_card(_product("我做小红书和B站", pack), _platform_html("default", ["小红书", "公众号"]))
        self.assertTrue(any("平台没有跟随" in row for row in errors))


if __name__ == "__main__":
    unittest.main()
