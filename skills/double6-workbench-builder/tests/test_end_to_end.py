"""全领域端到端：16 个领域（及其细分档案）都必须能走完六步流程并通过静态验收。

只用标准库；浏览器验收在 Playwright + Chromium 可用时自动执行（CI 的 browser job 会安装）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_helpers import SKILL_ROOT, browser_ready, cli, route_catalog, run_to_candidate  # noqa: E402

SNAKE = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")


def _cases(catalog: list[dict]) -> list[tuple[str, str, str | None, str]]:
    cases = []
    for option in catalog:
        label, domain = option["label"], option["domain_id"]
        cases.append((f"{domain}", domain, None, f"帮我做一个{label}工作台，{option['description']}"))
        for profile in option.get("profiles", []):
            cases.append((f"{domain}--{profile['profile_id']}", domain, profile["profile_id"], f"帮我做一个{label}工作台：{profile['label']}，{profile['description']}"))
    return cases


class EndToEndAllDomainsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.catalog = route_catalog(cls.tmp)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_catalog_has_16_domains(self) -> None:
        self.assertEqual(len(self.catalog), 16)

    def test_every_domain_builds_and_passes_static_scan(self) -> None:
        renderers = {}
        for case_id, domain, profile, request in _cases(self.catalog):
            with self.subTest(case=case_id):
                label = next(row["label"] for row in self.catalog if row["domain_id"] == domain)
                route = {"primary_domain": domain, "auxiliary_domains": [], "evidence_spans": [label]}
                if profile:
                    route["profile_id"] = profile
                run, built = run_to_candidate(self.tmp, case_id, request, route, f"{label}工作台")
                renderers[case_id] = built["renderer_id"]
                result = cli("evaluate", "--run", str(run), "--skip-browser", ok_codes=(0, 1))
                self.assertEqual(result["status"], "static_precheck_passed", result)
                html = (run / "candidate" / "index.html").read_text(encoding="utf-8")
                self._assert_candidate_quality(case_id, run, html)
        # 两个新增/重做的场景必须命中专属 renderer
        self.assertEqual(renderers["research-knowledge"], "research_reading_dashboard")
        self.assertEqual(renderers["content-operations"], "creator_production_dashboard")

    def _assert_candidate_quality(self, case_id: str, run: Path, html: str) -> None:
        self.assertIn("http-equiv='Content-Security-Policy'", html, case_id)
        self.assertIn("connect-src 'none'", html, case_id)
        labels = re.findall(r"<span class='nav-label'>(.*?)</span>", html)
        half = labels[: len(labels) // 2]
        self.assertEqual(len(half), len(set(half)), f"{case_id} 导航重名：{half}")
        product = json.loads((run / "product.json").read_text(encoding="utf-8"))
        module_names = {row["recommendation_module_id"]: row["name"] for row in product["capabilities"] if row["mode"] == "in_page"}
        for name in module_names.values():
            # 导航不截断：要么完整名称，要么来自登记短标签（≤ 完整名称且为其子串之一）
            self.assertTrue(any(label == name or (len(label) <= 4 and label in name) or label in {"数据", "计划", "训练", "奖励", "日志"} for label in half), f"{case_id} 模块 {name} 导航被截断：{half}")
        for module_id in module_names:
            self.assertIn(f"data-dashboard-module-link='{module_id}'", html.split("data-double6-module-id=", 1)[0], f"{case_id} 首页缺 {module_id}")
        for capability in product["capabilities"]:
            for item in (capability.get("starter") or {}).get("starter_items", []):
                for key in ("title", "body", "result"):
                    self.assertFalse(SNAKE.findall(str(item.get(key, ""))), f"{case_id} starter 泄漏机器标记：{item.get(key)}")
        if not any(module_id.startswith(("education-", "exam-")) for module_id in module_names):
            self.assertNotIn("老师布置", html, f"{case_id} 非学习场景出现教育话术")
            self.assertNotIn("错题或安排", html, case_id)

    def test_content_ops_examples_fit_solo_creator(self) -> None:
        route = {"primary_domain": "content-operations", "auxiliary_domains": [], "evidence_spans": ["小红书和公众号"]}
        run, built = run_to_candidate(self.tmp, "solo-creator", "我一个人做小红书和公众号，想管好素材、选题、排期和数据复盘。", route, "一人内容工作室")
        self.assertEqual(built["renderer_id"], "creator_production_dashboard")
        html = (run / "candidate" / "index.html").read_text(encoding="utf-8")
        for marker in ("选题打分卡", "一鱼多吃", "互动率", "一周发布节奏", "小红书"):
            self.assertIn(marker, html)
        self.assertNotIn("装修", html)
        self.assertNotIn("synthetic_demo", html)

    def test_utf8_bom_and_utf16_request_files(self) -> None:
        for encoding, prefix in (("utf-8-sig", "bom"), ("utf-16", "u16")):
            with self.subTest(encoding=encoding):
                request = self.tmp / f"{prefix}-request.txt"
                request.write_text("做一个研究阅读追踪器", encoding=encoding)
                route = self.tmp / f"{prefix}-route.json"
                route.write_text(json.dumps({"primary_domain": "research-knowledge", "auxiliary_domains": [], "evidence_spans": ["研究阅读追踪器"]}, ensure_ascii=False), encoding=encoding)
                started = cli("start", "--run", str(self.tmp / f"{prefix}-run"), "--request-file", str(request), "--route-file", str(route))
                self.assertEqual(started["status"], "ready_to_propose")

    def test_stale_sha_error_names_the_field(self) -> None:
        route = {"primary_domain": "research-knowledge", "auxiliary_domains": [], "evidence_spans": ["读书"]}
        request = self.tmp / "sha-request.txt"
        request.write_text("我想记录读书笔记", encoding="utf-8")
        route_file = self.tmp / "sha-route.json"
        route_file.write_text(json.dumps(route, ensure_ascii=False), encoding="utf-8")
        run = self.tmp / "sha-run"
        cli("start", "--run", str(run), "--request-file", str(request), "--route-file", str(route_file))
        from e2e_helpers import product_from_snapshot  # noqa: PLC0415
        product_file = self.tmp / "sha-product.json"
        product_file.write_text(json.dumps(product_from_snapshot(run, "sha-run", "读书"), ensure_ascii=False), encoding="utf-8")
        cli("propose", "--run", str(run), "--product-file", str(product_file))
        event = self.tmp / "sha-event.json"
        event.write_text(json.dumps({"event_id": "x", "turn_index": 2, "raw_text": "确认", "intent": "approve_product", "presented_content_sha256": "0" * 64}), encoding="utf-8")
        error = cli("respond", "--run", str(run), "--event-file", str(event), ok_codes=(2,))
        self.assertIn("presented_content_sha256", error["error"])

    @unittest.skipUnless(os.environ.get("DOUBLE6_E2E_BROWSER") == "1" or browser_ready(), "Playwright + Chromium 不可用，跳过浏览器验收")
    def test_browser_evaluation_delivers(self) -> None:
        cases = [
            ("browser-content", "content-operations", "我一个人做小红书和公众号的内容运营", "小红书和公众号"),
            ("browser-research", "research-knowledge", "帮我做一个个人研究阅读追踪器", "研究阅读追踪器"),
            ("browser-fitness", "fitness-nutrition", "帮我安排一周训练冲刺和饮食记录", "一周训练冲刺"),
        ]
        for name, domain, request, span in cases:
            with self.subTest(case=name):
                route = {"primary_domain": domain, "auxiliary_domains": [], "evidence_spans": [span]}
                run, _ = run_to_candidate(self.tmp, name, request, route, request[:12])
                result = cli("evaluate", "--run", str(run), ok_codes=(0, 1))
                self.assertEqual(result["status"], "pass", result)
                self.assertEqual(result["state"], "local_delivered")


if __name__ == "__main__":
    unittest.main()
