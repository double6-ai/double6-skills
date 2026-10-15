from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any

from test_validate_research_bundle import (
    Bundle,
    complete_record,
    complete_report,
)


def landscape_bundle_parts() -> tuple[str, dict[str, Any]]:
    report, _ = complete_report()
    report = report.replace(
        "这一判断只适用于记录的时间点和公开配置，不外推到未测试环境。",
        "独立评测同样确认甲公司和乙项目处于领先位置 [B2]。"
        "这一判断只适用于记录的时间点和公开配置，不外推到未测试环境。",
    )
    report = report.replace(
        "## 限制与未知事项",
        "## 覆盖表\n\n"
        "| 分段 | 主要实体 | 证据 | 仍未知 |\n"
        "| --- | --- | --- | --- |\n"
        "| 整机厂商 | 甲公司 | [A1][B2] | 出货口径 |\n"
        "| 开源项目 | 乙项目 | [B2] | 采用数据 |\n\n"
        "## 限制与未知事项",
    )
    report = report.replace(
        "- [A1] 示例官方正文",
        "- [B2] 独立评测正文\n- [C3] 饱和检查读到的新正文\n"
        "- [D4] 饱和检查读到的另一篇新正文\n- [A1] 示例官方正文",
    )
    record = complete_record()
    record["task_type"] = "open_landscape"
    base = record["sources"][0]
    for source_id, relation in (
        ("B2", "independent"),
        ("C3", "independent"),
        ("D4", "independent"),
    ):
        extra = copy.deepcopy(base)
        extra.update(
            {
                "source_id": source_id,
                "title": f"{source_id} 正文",
                "publisher": f"Publisher {source_id}",
                "url": f"https://example.org/{source_id}",
                "source_kind": "independent_evaluation",
                "stakeholder_relation": relation,
            }
        )
        record["sources"].append(extra)
    record["landscape"] = {
        "coverage_table_section": "## 覆盖表",
        "segments": [
            {"segment": "整机厂商", "question_ids": ["Q1"]},
            {"segment": "开源项目", "question_ids": ["Q1"]},
        ],
        "entities": [
            {"name": "甲公司", "segment": "整机厂商", "source_ids": ["A1"]},
            {"name": "乙项目", "segment": "开源项目", "source_ids": ["B2"]},
        ],
    }
    rounds = record["research_rounds"]
    rounds[0]["queries"] = [
        {"query": "目标领域 全景", "facet": "core_terms"},
        {"query": "target field landscape", "facet": "synonym_or_language"},
        {"query": "目标领域 论文 综述", "facet": "source_type"},
    ]
    rounds[0]["new_source_ids"] = ["A1"]
    rounds[0]["new_material_findings_count"] = 4
    rounds[1]["queries"] = [
        {"query": "评测报告引用的原始数据", "facet": "citation_snowball"},
    ]
    rounds[1]["new_source_ids"] = ["B2"]
    rounds[1]["new_material_findings_count"] = 1
    rounds[2]["queries"] = [
        {"query": "目标领域 失败 质疑", "facet": "adversarial"},
        {"query": "欧洲 目标领域 新进入者", "facet": "region_or_market"},
    ]
    rounds[2]["new_source_ids"] = ["C3", "D4"]
    rounds[2]["new_material_findings_count"] = 0
    return report, record


class OpenLandscapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_bundle(self, report: str, record: dict[str, Any]) -> dict[str, Any]:
        return Bundle(self.root, report, record).result()

    def test_full_landscape_bundle_passes(self) -> None:
        report, record = landscape_bundle_parts()
        result = self.run_bundle(report, record)
        self.assertEqual(result["status"], "ok", result["errors"])
        metrics = result["checks"]["depth_metrics"]
        self.assertEqual(metrics["task_type"], "open_landscape")
        self.assertEqual(metrics["segment_count"], 2)
        self.assertEqual(metrics["per_question"]["Q1"]["opened_sources_used"], 2)
        self.assertEqual(metrics["round_novelty"][2]["new_opened_sources"], 2)

    def test_legacy_record_without_task_type_still_passes(self) -> None:
        report, _ = complete_report()
        result = self.run_bundle(report, complete_record())
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertIsNone(result["checks"]["depth_metrics"]["task_type"])

    def test_landscape_request_without_task_type_warns(self) -> None:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        bundle.write_text("request_snapshot.md", "# 请求\n\n请做一份行业全景调研。")
        result = bundle.result()
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertIn(
            "task_type_not_recorded:looks_like_open_landscape",
            result["warnings"],
        )

    def test_shallow_landscape_single_source_fails_depth_floor(self) -> None:
        report, record = landscape_bundle_parts()
        report = report.replace("独立评测同样确认甲公司和乙项目处于领先位置 [B2]。", "")
        report = report.replace("| 开源项目 | 乙项目 | [B2] |", "| 开源项目 | 乙项目 | 见上 |")
        report = report.replace("| [A1][B2] |", "| [A1] |")
        result = self.run_bundle(report, record)
        self.assertIn("landscape_question_depth_floor:Q1", result["errors"])

    def test_landscape_requires_map_and_coverage_table(self) -> None:
        report, record = landscape_bundle_parts()
        del record["landscape"]
        result = self.run_bundle(report, record)
        self.assertIn("landscape_missing", result["errors"])
        report, record = landscape_bundle_parts()
        record["landscape"]["coverage_table_section"] = "## 不存在"
        result = self.run_bundle(report, record)
        self.assertIn("landscape_coverage_table_missing", result["errors"])

    def test_entity_must_be_sourced_and_in_report(self) -> None:
        report, record = landscape_bundle_parts()
        record["landscape"]["entities"].append(
            {"name": "丙机构", "segment": "开源项目", "source_ids": []}
        )
        result = self.run_bundle(report, record)
        self.assertIn("landscape_entity_unsourced:丙机构", result["errors"])
        self.assertIn("landscape_entity_not_in_report:丙机构", result["errors"])

    def test_segment_needs_entity_and_table_row(self) -> None:
        report, record = landscape_bundle_parts()
        record["landscape"]["segments"].append(
            {"segment": "政策监管", "question_ids": ["Q1"]}
        )
        result = self.run_bundle(report, record)
        self.assertIn("landscape_segment_without_entities:政策监管", result["errors"])
        self.assertIn(
            "landscape_segment_not_in_coverage_table:政策监管", result["errors"]
        )

    def test_query_ledger_diversity_and_snowball_required(self) -> None:
        report, record = landscape_bundle_parts()
        for round_item in record["research_rounds"]:
            round_item["queries"] = [{"query": "同一关键词", "facet": "core_terms"}]
        result = self.run_bundle(report, record)
        self.assertIn("landscape_query_facets_too_narrow:core_terms", result["errors"])
        self.assertIn("landscape_citation_snowball_missing", result["errors"])
        self.assertIn("landscape_saturation_queries_not_diversified", result["errors"])

    def test_query_facet_must_be_known(self) -> None:
        report, record = landscape_bundle_parts()
        record["research_rounds"][0]["queries"].append({"query": "x", "facet": "random"})
        result = self.run_bundle(report, record)
        self.assertTrue(
            any(item.startswith("round_query_facet_invalid:R1") for item in result["errors"])
        )

    def test_saturation_must_read_new_sources_without_new_findings(self) -> None:
        report, record = landscape_bundle_parts()
        record["research_rounds"][2]["new_source_ids"] = []
        record["research_rounds"][2]["new_material_findings_count"] = 2
        result = self.run_bundle(report, record)
        self.assertIn("landscape_saturation_without_new_reading", result["errors"])
        self.assertIn("landscape_saturation_found_new_material", result["errors"])
        report, record = landscape_bundle_parts()
        del record["research_rounds"][2]["new_material_findings_count"]
        result = self.run_bundle(report, record)
        self.assertIn("landscape_saturation_novelty_missing", result["errors"])

    def test_unknown_new_source_id_is_rejected(self) -> None:
        report, record = landscape_bundle_parts()
        record["research_rounds"][2]["new_source_ids"].append("ZZ9")
        result = self.run_bundle(report, record)
        self.assertIn("round_new_source_unknown:R3:ZZ9", result["errors"])

    def test_bibliography_only_sources_warn_as_padding(self) -> None:
        report, record = landscape_bundle_parts()
        result = self.run_bundle(report, record)
        self.assertIn("sources_not_used_in_report_body:C3,D4", result["warnings"])

    def test_partial_landscape_is_not_held_to_complete_floors(self) -> None:
        report, record = landscape_bundle_parts()
        del record["landscape"]
        for round_item in record["research_rounds"]:
            round_item.pop("queries", None)
        record["research_status"] = "partial"
        record.pop("stop_decision", None)
        result = self.run_bundle(report, record)
        landscape_errors = [e for e in result["errors"] if e.startswith("landscape_")]
        self.assertEqual(landscape_errors, [])

    def test_invalid_task_type_is_rejected(self) -> None:
        report, record = landscape_bundle_parts()
        record["task_type"] = "everything"
        result = self.run_bundle(report, record)
        self.assertTrue(
            any(item.startswith("task_type_invalid:everything") for item in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
