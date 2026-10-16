"""核验普通澄清上限与必要授权独立计数，不启动浏览器。"""
from pathlib import Path
import tempfile
import unittest

from double6_runtime.core import ContractError, read_json, write_json
from double6_runtime.routing import BOUNDARY_DECISION_IDS
from double6_runtime.workflow import start_run, respond


class ClarificationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"
        request = "给孩子做学习台，家里使用真实学生名单，指定教材并自动发送通知"
        start_run(self.run, request, {"primary_domain": "education-learning", "evidence_spans": ["学习台"]})

    def answer(self, decision, turn=1, **extra):
        return respond(self.run, {"event_id": f"answer-{turn}", "turn_index": turn,
            "raw_text": "按推荐", "intent": "answer", "decision_id": decision,
            "normalized_value": "按推荐", **extra})

    def exhausted(self):
        requirements = read_json(self.run / "requirements.json")
        requirements["question_count"] = 5
        requirements["scene_session"]["question_count"] = 5
        write_json(self.run / "requirements.json", requirements)

    def test_mixed_answers_can_exceed_five_total(self):
        self.run = Path(self.tmp.name) / "with-discovery"
        request = "给孩子做学习台，家里使用真实学生名单，指定教材并自动发送通知"
        start_run(self.run, request)
        respond(self.run, {"event_id": "discovery", "turn_index": 1, "intent": "answer",
            "decision_id": "scene-discovery", "raw_text": request,
            "normalized_value": {"request": request, "route": {
                "primary_domain": "education-learning", "evidence_spans": ["学习台"]}}})
        turns = 1
        while True:
            requirements = read_json(self.run / "requirements.json")
            missing = [x for x in requirements["critical_decisions"] if x["status"] == "missing"]
            if not missing:
                break
            turns += 1
            self.answer(missing[0]["decision_id"], turns)
        self.assertGreater(turns, 5)
        session = read_json(self.run / "requirements.json")["scene_session"]
        self.assertEqual(turns, session["question_count"] + session["authorization_question_count"])
        self.assertLessEqual(session["question_count"], 5)
        self.assertEqual(read_json(self.run / "run.json")["state"], "intake")

    def test_authorization_after_five_remains_available(self):
        self.exhausted()
        self.answer("privacy-boundary")
        requirements = read_json(self.run / "requirements.json")
        self.assertEqual(requirements["scene_session"]["question_count"], 5)
        self.assertEqual(requirements["scene_session"]["authorization_question_count"], 1)
        self.assertTrue(any(x["status"] == "missing" for x in requirements["critical_decisions"] if x["decision_id"] in BOUNDARY_DECISION_IDS))

    def test_sixth_preference_cannot_claim_to_be_authorization(self):
        self.exhausted()
        before = (self.run / "events.json").read_bytes()
        with self.assertRaises(ContractError):
            self.answer("learning-priority", question_kind="authorization")
        self.assertEqual(before, (self.run / "events.json").read_bytes())

    def test_declining_authorization_does_not_confirm_it(self):
        self.exhausted()
        self.answer("privacy-boundary", resolution_status="blocked")
        requirements = read_json(self.run / "requirements.json")
        privacy = next(x for x in requirements["critical_decisions"] if x["decision_id"] == "privacy-boundary")
        self.assertEqual(privacy["status"], "blocked")
        self.assertNotEqual(read_json(self.run / "run.json")["state"], "ready_to_build")

    def test_switch_resets_both_counters(self):
        self.answer("privacy-boundary")
        old = read_json(self.run / "requirements.json")["scene_session"]
        respond(self.run, {"event_id": "switch", "turn_index": 2, "intent": "switch_scene", "raw_text": "换一个场景"})
        new = read_json(self.run / "requirements.json")["scene_session"]
        self.assertNotEqual(old["session_id"], new["session_id"])
        self.assertEqual(new["question_count"], 0)
        self.assertEqual(new["authorization_question_count"], 0)


if __name__ == "__main__":
    unittest.main()
