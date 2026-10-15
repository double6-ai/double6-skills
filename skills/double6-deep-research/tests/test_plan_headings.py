from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_validate_research_bundle import (
    Bundle,
    complete_record,
    complete_report,
    research_plan_for,
)


class PlanQuestionHeadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_plan(self, plan: str) -> dict:
        report, _ = complete_report()
        bundle = Bundle(self.root, report, complete_record())
        bundle.write_text("research_plan.md", plan)
        return bundle.result()

    def test_discovery_heading_mentioning_questions_does_not_misfire(self) -> None:
        plan = research_plan_for(complete_record()).replace(
            "## 要回答的问题",
            "## Discovery (before freezing questions)\n\n先做发现检索。\n\n## 要回答的问题",
            1,
        )
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_chinese_heading_mentioning_wenti_does_not_misfire(self) -> None:
        plan = research_plan_for(complete_record()).replace(
            "## 要回答的问题",
            "## 发现轮（冻结问题之前）\n\n先做发现检索。\n\n## 要回答的问题",
            1,
        )
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_questions_listed_later_under_generic_heading_are_found(self) -> None:
        plan = research_plan_for(complete_record()).replace(
            "## 要回答的问题",
            "## Research questions: background notes\n\n无。\n\n## Questions",
            1,
        )
        result = self.run_plan(plan)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_missing_question_still_reported(self) -> None:
        record = complete_record()
        plan = research_plan_for(record)
        question = record["questions"][0]["question"]
        plan = plan.replace(f"- {question}", "- 其他内容")
        plan = plan.replace(
            "## 要回答的问题",
            "## Discovery (before freezing questions)\n\n先做发现检索。\n\n## 要回答的问题",
            1,
        )
        result = self.run_plan(plan)
        self.assertIn(
            f"research_plan_question_missing:{record['questions'][0]['question_id']}",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
