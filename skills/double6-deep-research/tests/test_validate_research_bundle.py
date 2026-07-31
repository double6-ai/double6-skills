from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_research_bundle.py"
)
sys.path.insert(0, str(SCRIPT_PATH.parent))
SKILL_PATH = SCRIPT_PATH.parents[1] / "SKILL.md"
REPORT_QUALITY_PATH = (
    SCRIPT_PATH.parents[1] / "references" / "report-quality.md"
)
PRIVACY_PATH = (
    SCRIPT_PATH.parents[1]
    / "references"
    / "privacy-and-fail-closed.md"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_research_bundle",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def complete_report(
    *,
    source_id: str = "A1",
    headings: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    section_headings = headings or {
        "executive_summary": "## 执行摘要",
        "scope_and_method": "## 范围与方法",
        "answer": "## Q1：结论",
        "limitations": "## 限制与未知事项",
        "sources": "## 来源",
    }
    report = f"""# 研究报告

{section_headings["executive_summary"]}

综合现有资料，目标方案适用于当前问题，但仍需根据实际负载和地域条件做最终决策。关键判断均在主体章节给出证据和适用边界。

{section_headings["scope_and_method"]}

本报告覆盖用户指定的问题、当前公开资料、覆盖缺口检查和对抗性饱和检查，事实截止日与访问日期记录在研究记录中。

{section_headings["answer"]}

目标方案目前满足核心要求，并且现有官方材料能够直接支持这一关键结论 [{source_id}]。这一判断只适用于记录的时间点和公开配置，不外推到未测试环境。

{section_headings["limitations"]}

公开材料无法覆盖每种本地部署组合，实际性能仍取决于工作负载、地域、并发和用户自己的运行环境。

{section_headings["sources"]}

- [{source_id}] 示例官方正文，访问日和发布者见 research_record.json。
"""
    return report, section_headings


def complete_record(
    *,
    source_id: str = "A1",
    headings: dict[str, str] | None = None,
) -> dict[str, Any]:
    _, section_headings = complete_report(
        source_id=source_id,
        headings=headings,
    )
    return {
        "schema_version": 2,
        "research_status": "complete",
        "research_as_of": "2026-07-26T18:00:00+08:00",
        "report_sections": {
            "executive_summary": section_headings["executive_summary"],
            "scope_and_method": section_headings["scope_and_method"],
            "limitations": section_headings["limitations"],
            "sources": section_headings["sources"],
        },
        "questions": [
            {
                "question_id": "Q1",
                "question": "目标方案是否满足核心要求？",
                "status": "answered",
                "answer_section": section_headings["answer"],
                "coverage_requirements": {
                    "required_source_kinds": ["official_document"],
                    "independent_evidence_required": False,
                    "required_checks": ["counterevidence"],
                    "required_objects": [],
                    "required_dimensions": [],
                },
            }
        ],
        "sources": [
            {
                "source_id": source_id,
                "title": "示例官方正文",
                "publisher": "Example",
                "url": "https://example.com/body",
                "published_at": "2026-07-20",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "official_document",
                "stakeholder_relation": "first_party",
                "question_ids": ["Q1"],
            }
        ],
        "key_claims": [
            {
                "claim_id": "K1",
                "claim_type": "current_fact",
                "claim": "目标方案目前满足核心要求",
                "question_ids": ["Q1"],
                "source_ids": [source_id],
                "evidence_locator": "Q1 主体段落",
            }
        ],
        "research_rounds": [
            {
                "round_id": "R1",
                "round_type": "main_research",
                "focus": "主体研究",
                "target_question_ids": ["Q1"],
                "strategy_types": {"Q1": ["primary_sources"]},
                "checks_completed": {"Q1": []},
                    "objects_checked": {"Q1": []},
                    "dimensions_checked": {"Q1": []},
                "conclusion_impact": {"Q1": "changed"},
                "material_findings": ["形成初步答案"],
            },
            {
                "round_id": "R2",
                "round_type": "coverage_gap_check",
                "focus": "反证与更新",
                "target_question_ids": ["Q1"],
                "strategy_types": {"Q1": ["counterevidence"]},
                "checks_completed": {"Q1": ["counterevidence"]},
                    "objects_checked": {"Q1": []},
                    "dimensions_checked": {"Q1": []},
                "conclusion_impact": {"Q1": "strengthened"},
                "material_findings": ["未发现改变结论的反证"],
            },
            {
                "round_id": "R3",
                "round_type": "adversarial_saturation_check",
                "focus": "使用不同策略检查遗漏和结论稳定性",
                "target_question_ids": ["Q1"],
                "strategy_types": {
                    "Q1": ["counterevidence", "omission_scan"]
                },
                "checks_completed": {"Q1": ["counterevidence"]},
                    "objects_checked": {"Q1": []},
                    "dimensions_checked": {"Q1": []},
                "conclusion_impact": {"Q1": "none"},
                "material_findings": [],
            },
        ],
        "stop_decision": {
            "status": "complete",
            "coverage_complete": True,
            "missing_required_source_kinds": {},
            "missing_independent_evidence": [],
            "unchecked_required_checks": {},
            "unchecked_objects": {},
            "unchecked_dimensions": {},
            "unresolved_high_priority_conflicts": [],
            "premature_stop_checks": {
                "tool_result_limit_used": False,
                "preset_source_count_used": False,
                "time_limit_used": False,
                "fixed_round_count_used": False,
            },
            "remaining_high_priority_gaps": [],
            "adequacy_rationale": "问题、来源角色和反证均已检查。",
            "why_more_search_unlikely_to_change_conclusions": (
                "最后一轮没有发现会改变主要结论的新证据。"
            ),
        },
    }


def partial_record() -> dict[str, Any]:
    record = complete_record()
    record["research_status"] = "partial"
    record["questions"][0].update(
        {
            "status": "partially_answered",
            "current_evidence": "官方正文支持基本能力，但缺少地域实测。",
            "next_step": "取得目标地域的本地测量结果。",
        }
    )
    record["stop_decision"] = {
        "status": "partial",
        "coverage_complete": True,
        "missing_required_source_kinds": {},
        "missing_independent_evidence": [],
        "unchecked_required_checks": {},
        "unchecked_objects": {},
        "unchecked_dimensions": {},
        "unresolved_high_priority_conflicts": [],
        "premature_stop_checks": {
            "tool_result_limit_used": False,
            "preset_source_count_used": False,
            "time_limit_used": False,
            "fixed_round_count_used": False,
        },
        "remaining_high_priority_gaps": [
            {
                "question_id": "Q1",
                "gap_type": "other",
                "missing_items": ["target_region_measurement"],
                "gap": "缺少目标地域的实测数据",
                "current_evidence": "已有官方能力说明",
                "next_step": "运行目标地域基准测试",
            }
        ],
    }
    return record


def blocked_record() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "research_status": "blocked",
        "research_as_of": "2026-07-26",
        "report_sections": {
            "executive_summary": "## 当前结论",
            "scope_and_method": "## 范围与方法",
            "limitations": "## 阻塞与限制",
            "sources": "## 来源状态",
        },
        "questions": [
            {
                "question_id": "Q1",
                "question": "需要回答的问题",
                "status": "unanswered",
                "answer_section": "",
                "coverage_requirements": {
                    "required_source_kinds": ["official_document"],
                    "independent_evidence_required": False,
                    "required_checks": ["counterevidence"],
                    "required_objects": [],
                    "required_dimensions": [],
                },
            }
        ],
        "sources": [],
        "key_claims": [],
        "research_rounds": [],
        "stop_decision": {
            "status": "blocked",
            "coverage_complete": False,
            "missing_required_source_kinds": {
                "Q1": ["official_document"]
            },
            "missing_independent_evidence": [],
            "unchecked_required_checks": {"Q1": ["counterevidence"]},
            "unchecked_objects": {},
            "unchecked_dimensions": {},
            "unresolved_high_priority_conflicts": [],
            "premature_stop_checks": {
                "tool_result_limit_used": False,
                "preset_source_count_used": False,
                "time_limit_used": False,
                "fixed_round_count_used": False,
            },
            "remaining_high_priority_gaps": [],
            "blocking_conditions": "宿主没有获准的网页读取能力。",
            "unblock_requirements": "提供获准的搜索或网页读取能力。",
        },
    }


def passing_review(candidate_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "reviewed_at": "2026-07-26T20:00:00+08:00",
        "independence_basis": "isolated_agent",
        "verdict": "pass",
        "counts": {"blocker": 0, "major": 0, "minor": 0},
        "question_coverage": [
            {
                "question_id": "Q1",
                "status": "complete",
                "notes": "问题已实质回答。",
            }
        ],
        "critical_claim_checks": [
            {
                "claim_id": "K1",
                "status": "verified",
                "notes": "已打开正文核验。",
            }
        ],
        "sampled_fact_checks": [],
        "no_sampleable_facts_reason": "测试夹具没有额外普通事实。",
        "depth_assessment": "adequate",
        "coverage_requirements_adequate": True,
        "premature_stop": False,
        "missing_source_roles": [],
        "omitted_objects": [],
        "omitted_dimensions": [],
        "saturation_check_credible": True,
        "findings": [],
        "candidate_files_modified": False,
        "candidate_file_sha256": candidate_hashes,
    }


class Bundle:
    def __init__(
        self,
        root: Path,
        report: str,
        record: dict[str, Any],
    ) -> None:
        self.root = root
        self.write_text(
            "request_snapshot.md",
            "# 请求\n\n请深入研究目标方案是否满足当前核心要求，并给出证据和限制。",
        )
        self.write_text("final_report.md", report)
        self.write_json("research_record.json", record)

    def write_text(self, name: str, value: str) -> None:
        (self.root / name).write_text(value, encoding="utf-8")

    def write_json(self, name: str, value: dict[str, Any]) -> None:
        self.write_text(
            name,
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )

    def result(self) -> dict[str, Any]:
        return VALIDATOR.validate_bundle(self.root)


class ValidateResearchBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_execution_material_has_no_source_count_anchors(self) -> None:
        execution_material = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL_PATH, REPORT_QUALITY_PATH, PRIVACY_PATH)
        )

        for forbidden in (
            "7 条",
            "13 条",
            "50 条",
            "12+3",
            "12 + 3",
            "new_useful_sources",
        ):
            self.assertNotIn(forbidden, execution_material)

    def test_complete_bundle_is_valid_draft(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["research_status"], "complete")
        self.assertEqual(result["review_status"], "not_reviewed")
        self.assertEqual(result["delivery_status"], "complete_draft")
        self.assertEqual(
            result["checks"]["question_coverage"][0]["missing_source_kinds"],
            [],
        )
        self.assertEqual(
            result["checks"]["question_coverage"][0][
                "last_saturation_impact"
            ],
            "none",
        )

    def test_broad_comparison_with_only_first_party_source_is_rejected(
        self,
    ) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["key_claims"][0]["claim_type"] = "comparative"
        record["stop_decision"].update(
            {
                "coverage_complete": False,
                "missing_required_source_kinds": {
                    "Q1": ["independent_evaluation"]
                },
                "missing_independent_evidence": ["Q1"],
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_source_kinds_not_covered:Q1:independent_evaluation",
            result["errors"],
        )
        self.assertIn(
            "question_independent_evidence_missing:Q1",
            result["errors"],
        )
        self.assertIn(
            "key_claim_independent_evidence_missing:K1",
            result["errors"],
        )

    def test_independent_source_closes_comparison_coverage(self) -> None:
        report, _ = complete_report()
        report = report.replace(
            "这一关键结论 [A1]",
            "这一关键结论 [A1] [B1]",
        ).replace(
            "- [A1] 示例官方正文",
            "- [A1] 示例官方正文\n- [B1] 独立评测正文",
        )
        record = complete_record()
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["sources"].append(
            {
                "source_id": "B1",
                "title": "独立评测正文",
                "publisher": "Independent Lab",
                "url": "https://example.net/evaluation",
                "published_at": "2026-07-21",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": "independent",
                "question_ids": ["Q1"],
            }
        )
        record["key_claims"][0].update(
            {
                "claim_type": "comparative",
                "source_ids": ["A1", "B1"],
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(
            result["checks"]["question_coverage"][0][
                "independent_source_ids"
            ],
            ["B1"],
        )

    def test_unreferenced_independent_source_does_not_close_coverage(
        self,
    ) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["sources"].append(
            {
                "source_id": "B1",
                "title": "未用于答案的独立评测",
                "publisher": "Independent Lab",
                "url": "https://example.net/unused-evaluation",
                "published_at": "2026-07-21",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": "independent",
                "question_ids": ["Q1"],
            }
        )
        record["stop_decision"].update(
            {
                "coverage_complete": False,
                "missing_required_source_kinds": {
                    "Q1": ["independent_evaluation"]
                },
                "missing_independent_evidence": ["Q1"],
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_source_kinds_not_covered:Q1:independent_evaluation",
            result["errors"],
        )
        self.assertIn(
            "question_independent_evidence_missing:Q1",
            result["errors"],
        )

    def test_top_level_heading_cannot_expand_answer_citation_scope(
        self,
    ) -> None:
        report, _ = complete_report()
        report = report.replace(
            "- [A1] 示例官方正文",
            "- [A1] 示例官方正文\n- [B1] 独立评测来源",
        )
        record = complete_record()
        record["questions"][0]["answer_section"] = "# 研究报告"
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["sources"].append(
            {
                "source_id": "B1",
                "title": "独立评测来源",
                "publisher": "Independent Lab",
                "url": "https://example.net/evaluation",
                "published_at": "2026-07-21",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": "independent",
                "question_ids": ["Q1"],
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_answer_section_invalid:Q1",
            result["errors"],
        )
        self.assertIn(
            "question_independent_evidence_missing:Q1",
            result["errors"],
        )

    def test_bibliography_text_cannot_masquerade_as_key_claim(self) -> None:
        report, _ = complete_report()
        report = report.replace(
            "- [A1] 示例官方正文",
            "- [A1] 示例官方正文\n- [B1] 独立评测来源",
        )
        record = complete_record()
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["sources"].append(
            {
                "source_id": "B1",
                "title": "独立评测来源",
                "publisher": "Independent Lab",
                "url": "https://example.net/evaluation",
                "published_at": "2026-07-21",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": "independent",
                "question_ids": ["Q1"],
            }
        )
        record["key_claims"].append(
            {
                "claim_id": "K2",
                "claim_type": "current_fact",
                "claim": "独立评测来源",
                "question_ids": ["Q1"],
                "source_ids": ["B1"],
                "evidence_locator": "来源列表",
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "key_claim_source_not_cited_in_answer:K2:B1:Q1",
            result["errors"],
        )
        self.assertIn(
            "question_independent_evidence_missing:Q1",
            result["errors"],
        )

    def test_duplicate_canonical_url_cannot_fake_source_roles(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["sources"].append(
            {
                "source_id": "B1",
                "title": "同一正文的另一个登记项",
                "publisher": "Mirror Label",
                "url": "https://EXAMPLE.com/body/?utm_source=test#section",
                "published_at": "2026-07-20",
                "accessed_at": "2026-07-26",
                "access_status": "full_text",
                "content_origin": "host_opened_page",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": "independent",
                "question_ids": ["Q1"],
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn("duplicate_source_url:A1:B1", result["errors"])

    def test_missing_required_check_is_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["questions"][0]["coverage_requirements"][
            "required_checks"
        ] = ["counterevidence", "freshness"]
        record["stop_decision"].update(
            {
                "coverage_complete": False,
                "unchecked_required_checks": {"Q1": ["freshness"]},
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_checks_not_completed:Q1:freshness",
            result["errors"],
        )

    def test_missing_required_object_and_dimension_are_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        requirements = record["questions"][0]["coverage_requirements"]
        requirements["required_objects"] = ["Object-A", "Object-B"]
        requirements["required_dimensions"] = ["cost", "latency"]
        record["research_rounds"][1]["objects_checked"] = {
            "Q1": ["Object-A"]
        }
        record["research_rounds"][1]["dimensions_checked"] = {
            "Q1": ["cost"]
        }
        record["stop_decision"].update(
            {
                "coverage_complete": False,
                "unchecked_objects": {"Q1": ["Object-B"]},
                "unchecked_dimensions": {"Q1": ["latency"]},
            }
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_objects_not_checked:Q1:Object-B",
            result["errors"],
        )
        self.assertIn(
            "question_dimensions_not_checked:Q1:latency",
            result["errors"],
        )

    def test_missing_saturation_round_is_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_rounds"] = record["research_rounds"][:-1]
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "research_round_type_missing:adversarial_saturation_check",
            result["errors"],
        )
        self.assertIn("question_not_saturated:Q1:missing", result["errors"])

    def test_research_round_order_is_enforced(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_rounds"] = [
            record["research_rounds"][1],
            record["research_rounds"][0],
            record["research_rounds"][2],
        ]
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn("research_round_order_invalid:Q1", result["errors"])

    def test_saturation_strategy_must_be_adversarial_and_distinct(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_rounds"][-1]["strategy_types"] = {
            "Q1": ["primary_sources"]
        }
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_saturation_strategy_not_adversarial:Q1",
            result["errors"],
        )
        self.assertIn(
            "question_saturation_strategy_not_distinct:Q1",
            result["errors"],
        )

    def test_round_maps_must_cover_every_target_question(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_rounds"][0]["target_question_ids"].append("Q2")
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "research_round_unknown_question:R1:Q2",
            result["errors"],
        )
        self.assertIn(
            "research_round_strategy_types_missing_question:R1:Q2",
            result["errors"],
        )
        self.assertIn(
            "research_round_impact_missing_question:R1:Q2",
            result["errors"],
        )

    def test_changed_last_saturation_round_requires_more_research(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_rounds"][-1]["conclusion_impact"]["Q1"] = "changed"
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn("question_not_saturated:Q1:changed", result["errors"])

    def test_material_change_after_saturation_requires_new_saturation(
        self,
    ) -> None:
        report, _ = complete_report()
        record = complete_record()
        later_round = copy.deepcopy(record["research_rounds"][0])
        later_round.update(
            {
                "round_id": "R4",
                "round_type": "coverage_gap_check",
                "conclusion_impact": {"Q1": "narrowed"},
            }
        )
        record["research_rounds"].append(later_round)
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "question_changed_after_saturation:Q1",
            result["errors"],
        )

    def test_premature_stop_conditions_cannot_complete_research(self) -> None:
        report, _ = complete_report()
        for stop_key in (
            "tool_result_limit_used",
            "preset_source_count_used",
            "time_limit_used",
            "fixed_round_count_used",
        ):
            with self.subTest(stop_key=stop_key):
                record = complete_record()
                record["stop_decision"]["premature_stop_checks"][
                    stop_key
                ] = True
                bundle = Bundle(self.root, report, record)

                result = bundle.result()

                self.assertIn(
                    f"complete_premature_stop:{stop_key}",
                    result["errors"],
                )

    def test_partial_with_honest_pending_language_is_valid(self) -> None:
        report, _ = complete_report()
        report = report.replace(
            "目标方案目前满足核心要求",
            "目标方案部分满足核心要求，Q1 证据待补充",
        )
        record = partial_record()
        record["key_claims"][0]["claim"] = "目标方案部分满足核心要求"
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["delivery_status"], "partial")

    def test_partial_records_derived_coverage_gaps(self) -> None:
        report, _ = complete_report()
        report = report.replace(
            "目标方案目前满足核心要求",
            "目标方案部分满足核心要求，独立证据待补充",
        )
        record = partial_record()
        record["key_claims"][0]["claim"] = "目标方案部分满足核心要求"
        record["questions"][0]["coverage_requirements"].update(
            {
                "required_source_kinds": [
                    "official_document",
                    "independent_evaluation",
                ],
                "independent_evidence_required": True,
            }
        )
        record["stop_decision"].update(
            {
                "coverage_complete": False,
                "missing_required_source_kinds": {
                    "Q1": ["independent_evaluation"]
                },
                "missing_independent_evidence": ["Q1"],
            }
        )
        record["stop_decision"]["remaining_high_priority_gaps"].extend(
            [
                {
                    "question_id": "Q1",
                    "gap_type": "missing_source_kind",
                    "missing_items": ["independent_evaluation"],
                    "gap": "缺少独立评测类型来源",
                    "current_evidence": "目前只有官方正文",
                    "next_step": "寻找并核验独立评测",
                },
                {
                    "question_id": "Q1",
                    "gap_type": "missing_independent_evidence",
                    "missing_items": ["independent"],
                    "gap": "缺少利益关系独立的证据",
                    "current_evidence": "目前只有第一方材料",
                    "next_step": "寻找无利益关系的独立来源",
                },
            ]
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        coverage = result["checks"]["question_coverage"][0]
        self.assertEqual(
            coverage["missing_source_kinds"],
            ["independent_evaluation"],
        )
        self.assertTrue(coverage["independent_evidence_missing"])

    def test_partial_requires_a_gap_for_every_open_question(self) -> None:
        report, headings = complete_report()
        q2_heading = "## Q2：补充结论"
        report = report.replace(
            headings["limitations"],
            (
                f"{q2_heading}\n\n"
                "现有官方正文仅支持初步判断 [A1]，仍需补充实测。\n\n"
                f"{headings['limitations']}"
            ),
        )
        record = partial_record()
        q2 = copy.deepcopy(record["questions"][0])
        q2.update(
            {
                "question_id": "Q2",
                "question": "补充场景是否满足要求？",
                "answer_section": q2_heading,
                "current_evidence": "官方正文只支持初步判断。",
                "next_step": "补充目标场景实测。",
            }
        )
        record["questions"].append(q2)
        record["sources"][0]["question_ids"].append("Q2")
        for research_round in record["research_rounds"]:
            research_round["target_question_ids"].append("Q2")
            for field in (
                "strategy_types",
                "checks_completed",
                "objects_checked",
                "dimensions_checked",
                "conclusion_impact",
            ):
                research_round[field]["Q2"] = copy.deepcopy(
                    research_round[field]["Q1"]
                )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "partial_open_question_gap_missing:Q2",
            result["errors"],
        )

    def test_partial_cli_returns_success(self) -> None:
        report, _ = complete_report()
        report = report.replace(
            "目标方案目前满足核心要求",
            "目标方案部分满足核心要求，Q1 证据待补充",
        )
        record = partial_record()
        record["key_claims"][0]["claim"] = "目标方案部分满足核心要求"
        Bundle(self.root, report, record)

        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(self.root)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        receipt = json.loads(
            (self.root / "validation_receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["delivery_status"], "partial")

    def test_blocked_bundle_without_sources_is_valid(self) -> None:
        report = """# 研究状态报告

## 当前结论

当前无法开始外部证据核验，因此不能形成事实结论。以下内容只说明已知范围、阻塞条件和解除办法，不声称已经完成研究。

## 范围与方法

计划覆盖用户提出的核心问题，并在取得获准工具后执行主体研究、缺口检查和独立复核。

## 阻塞与限制

宿主没有获准的网页读取能力，任何外部事实都无法核验，因此本次按失败关闭原则停止。

## 来源状态

目前没有已读取且可用于支撑关键结论的来源。解除条件是提供获准的搜索或网页读取能力。
"""
        bundle = Bundle(self.root, report, blocked_record())

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["delivery_status"], "blocked")

    def test_explicit_todo_is_rejected(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(
            self.root,
            report + "\nTODO: fill this section\n",
            complete_record(),
        )

        result = bundle.result()

        self.assertIn("report_contains_explicit_placeholder", result["errors"])

    def test_non_chinese_headings_are_language_independent(self) -> None:
        headings = {
            "executive_summary": "## 要約",
            "scope_and_method": "## 範囲と方法",
            "answer": "## Q1：結論",
            "limitations": "## 制約と不確実性",
            "sources": "## 情報源",
        }
        report, _ = complete_report(headings=headings)
        bundle = Bundle(
            self.root,
            report,
            complete_record(headings=headings),
        )

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])

    def test_non_s_source_id_is_supported(self) -> None:
        report, _ = complete_report(source_id="RUNPOD_1")
        bundle = Bundle(
            self.root,
            report,
            complete_record(source_id="RUNPOD_1"),
        )

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["checks"]["cited_source_count"], 1)

    def test_impossible_as_of_date_is_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["research_as_of"] = "2026-02-30"
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn("research_as_of_invalid", result["errors"])

    def test_table_citation_on_different_row_does_not_support_claim(self) -> None:
        report, _ = complete_report()
        old_paragraph = (
            "目标方案目前满足核心要求，并且现有官方材料能够直接支持这一关键结论 "
            "[A1]。这一判断只适用于记录的时间点和公开配置，不外推到未测试环境。"
        )
        table = (
            "下面的表格逐行给出结论与证据，不能跨行借用引用来支撑另一项结论。\n\n"
            "| 结论 | 来源 |\n"
            "|---|---|\n"
            "| 目标方案目前满足核心要求 | 无 |\n"
            "| 另一项背景事实 | [A1] |"
        )
        report = report.replace(old_paragraph, table)
        bundle = Bundle(self.root, report, complete_record())

        result = bundle.result()

        self.assertIn(
            "key_claim_source_not_cited_with_claim:K1:A1",
            result["errors"],
        )

    def test_review_pass_requires_consistent_counts_and_hashes(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = bundle.result()["checks"]["candidate_file_sha256"]
        bundle.write_json(
            "independent_review.json",
            {
                "reviewed_at": "2026-07-26T20:00:00+08:00",
                "independence_basis": "isolated_agent",
                "verdict": "pass",
                "counts": {"blocker": 0, "major": 0, "minor": 0},
                "question_coverage": [
                    {
                        "question_id": "Q1",
                        "status": "complete",
                        "notes": "问题已实质回答。",
                    }
                ],
                "critical_claim_checks": [
                    {
                        "claim_id": "K1",
                        "status": "verified",
                        "notes": "已打开正文核验。",
                    }
                ],
                "sampled_fact_checks": [],
                "no_sampleable_facts_reason": "测试夹具没有额外普通事实。",
                "depth_assessment": "adequate",
                "coverage_requirements_adequate": True,
                "premature_stop": False,
                "missing_source_roles": [],
                "omitted_objects": [],
                "omitted_dimensions": [],
                "saturation_check_credible": True,
                "findings": [],
                "candidate_files_modified": False,
                "candidate_file_sha256": hashes,
            },
        )

        result = bundle.result()

        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["review_status"], "pass")
        self.assertEqual(result["delivery_status"], "reviewed_pass")

    def test_review_depth_insufficient_cannot_pass(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = bundle.result()["checks"]["candidate_file_sha256"]
        review = passing_review(hashes)
        review.update(
            {
                "depth_assessment": "insufficient",
                "coverage_requirements_adequate": False,
                "premature_stop": True,
                "missing_source_roles": ["independent_evaluation"],
                "omitted_objects": ["Object-B"],
                "omitted_dimensions": ["latency"],
                "saturation_check_credible": False,
            }
        )
        bundle.write_json("independent_review.json", review)

        result = bundle.result()

        for expected in (
            "review_pass_depth_insufficient",
            "review_pass_coverage_requirements_inadequate",
            "review_pass_premature_stop",
            "review_pass_saturation_not_credible",
            "review_pass_missing_source_roles",
            "review_pass_omitted_objects",
            "review_pass_omitted_dimensions",
        ):
            self.assertIn(expected, result["errors"])
        self.assertEqual(result["delivery_status"], "invalid")

    def test_review_pass_requires_substantive_review_notes(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = bundle.result()["checks"]["candidate_file_sha256"]
        review = passing_review(hashes)
        review["question_coverage"][0]["notes"] = ""
        review["critical_claim_checks"][0]["notes"] = ""
        review["no_sampleable_facts_reason"] = ""
        bundle.write_json("independent_review.json", review)

        result = bundle.result()

        self.assertIn(
            "review_question_notes_missing:Q1",
            result["errors"],
        )
        self.assertIn(
            "review_claim_notes_missing:K1",
            result["errors"],
        )
        self.assertIn(
            "review_sampled_fact_checks_or_reason_missing",
            result["errors"],
        )
        self.assertEqual(result["delivery_status"], "invalid")

    def test_malformed_review_arrays_fail_closed_without_crashing(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = bundle.result()["checks"]["candidate_file_sha256"]

        for field, expected in (
            (
                "question_coverage",
                "review_question_coverage_not_object:0",
            ),
            (
                "critical_claim_checks",
                "review_claim_check_not_object:0",
            ),
        ):
            with self.subTest(field=field):
                review = passing_review(hashes)
                review[field] = ["bad"]
                bundle.write_json("independent_review.json", review)

                result = bundle.result()

                self.assertEqual(result["status"], "error")
                self.assertIn(expected, result["errors"])
                self.assertEqual(result["delivery_status"], "invalid")

    def test_review_count_mismatch_is_rejected(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = bundle.result()["checks"]["candidate_file_sha256"]
        bundle.write_json(
            "independent_review.json",
            {
                "reviewed_at": "2026-07-26T20:00:00+08:00",
                "independence_basis": "isolated_agent",
                "verdict": "pass",
                "counts": {"blocker": 0, "major": 1, "minor": 0},
                "question_coverage": [
                    {"question_id": "Q1", "status": "complete", "notes": ""}
                ],
                "critical_claim_checks": [
                    {"claim_id": "K1", "status": "verified", "notes": ""}
                ],
                "sampled_fact_checks": [],
                "no_sampleable_facts_reason": "测试夹具没有额外普通事实。",
                "depth_assessment": "adequate",
                "coverage_requirements_adequate": True,
                "premature_stop": False,
                "missing_source_roles": [],
                "omitted_objects": [],
                "omitted_dimensions": [],
                "saturation_check_credible": True,
                "findings": [],
                "candidate_files_modified": False,
                "candidate_file_sha256": hashes,
            },
        )

        result = bundle.result()

        self.assertIn("review_count_mismatch:major", result["errors"])
        self.assertIn("review_pass_has_blocker_or_major", result["errors"])
        self.assertEqual(result["delivery_status"], "invalid")

    def test_review_detects_candidate_modification(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        hashes = copy.deepcopy(
            bundle.result()["checks"]["candidate_file_sha256"]
        )
        bundle.write_text("final_report.md", report + "\n候选文件随后被改动。\n")
        bundle.write_json(
            "independent_review.json",
            {
                "reviewed_at": "2026-07-26T20:00:00+08:00",
                "independence_basis": "isolated_agent",
                "verdict": "pass",
                "counts": {"blocker": 0, "major": 0, "minor": 0},
                "question_coverage": [
                    {"question_id": "Q1", "status": "complete", "notes": ""}
                ],
                "critical_claim_checks": [
                    {"claim_id": "K1", "status": "verified", "notes": ""}
                ],
                "sampled_fact_checks": [],
                "no_sampleable_facts_reason": "测试夹具没有额外普通事实。",
                "depth_assessment": "adequate",
                "coverage_requirements_adequate": True,
                "premature_stop": False,
                "missing_source_roles": [],
                "omitted_objects": [],
                "omitted_dimensions": [],
                "saturation_check_credible": True,
                "findings": [],
                "candidate_files_modified": False,
                "candidate_file_sha256": hashes,
            },
        )

        result = bundle.result()

        self.assertIn(
            "review_candidate_hash_mismatch:final_report.md",
            result["errors"],
        )

    def test_snapshot_parent_traversal_is_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["sources"][0]["snapshot_path"] = "../outside.md"
        record["sources"][0]["snapshot_sha256"] = hashlib.sha256(
            b"outside"
        ).hexdigest()
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "source_snapshot_outside_bundle:A1",
            result["errors"],
        )

    def test_snapshot_absolute_path_is_rejected(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["sources"][0]["snapshot_path"] = str(
            self.root.parent / "outside.md"
        )
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "source_snapshot_outside_bundle:A1",
            result["errors"],
        )

    def test_snapshot_symlink_escape_is_rejected(self) -> None:
        report, _ = complete_report()
        outside = self.root.parent / f"{self.root.name}-outside.md"
        outside.write_text("outside", encoding="utf-8")
        snapshots = self.root / "snapshots"
        snapshots.mkdir()
        link = snapshots / "A1.md"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        record = complete_record()
        record["sources"][0]["snapshot_path"] = "snapshots/A1.md"
        record["sources"][0]["snapshot_sha256"] = hashlib.sha256(
            b"outside"
        ).hexdigest()
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertIn(
            "source_snapshot_outside_bundle:A1",
            result["errors"],
        )
        outside.unlink(missing_ok=True)

    def test_invalid_utf8_becomes_validation_error(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        (self.root / "final_report.md").write_bytes(b"\xff\xfe")

        result = bundle.result()

        self.assertTrue(
            any(
                error.startswith("invalid_text:final_report.md:")
                for error in result["errors"]
            )
        )

    def test_malformed_depth_fields_return_errors_without_crashing(self) -> None:
        report, _ = complete_report()
        record = complete_record()
        record["questions"][0]["coverage_requirements"][
            "required_source_kinds"
        ] = None
        record["questions"][0]["coverage_requirements"][
            "required_checks"
        ] = "counterevidence"
        record["sources"][0]["question_ids"] = None
        record["research_rounds"][0]["target_question_ids"] = None
        record["research_rounds"][1]["objects_checked"] = {"Q1": None}
        bundle = Bundle(self.root, report, record)

        result = bundle.result()

        self.assertEqual(result["status"], "error")
        self.assertIn(
            "question_required_source_kinds:Q1",
            result["errors"],
        )
        self.assertIn("source_question_ids_missing:A1", result["errors"])
        self.assertIn(
            "research_round_target_questions:R1",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
