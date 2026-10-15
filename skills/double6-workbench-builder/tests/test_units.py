"""针对审计问题的单元回归：导航标签、模块可达、机器标记扫描、编码、本地日期、浏览器发现。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from double6_runtime import builder, evaluation, scene_renderers  # noqa: E402
from double6_runtime.core import ContractError, read_user_text  # noqa: E402


class NavLabelTests(unittest.TestCase):
    def test_short_labels_kept_and_long_labels_not_truncated(self) -> None:
        self.assertEqual(scene_renderers._compact_nav_label("数据复盘"), "数据复盘")
        self.assertEqual(scene_renderers._compact_nav_label("实验与工作日志"), "日志")
        self.assertEqual(scene_renderers._compact_nav_label("写作与交付"), "写作")
        self.assertEqual(scene_renderers._compact_nav_label("一个很长的未知模块"), "一个很长的未知模块")

    def test_duplicate_short_labels_fall_back_to_full_names(self) -> None:
        items = [scene_renderers._nav_item("module-a", "训练计划表", "🏃"), scene_renderers._nav_item("module-b", "训练日志本", "📝"),
                 scene_renderers._nav_item("data-tools", "数据", "💾")]
        labels = [row["nav_label"] for row in scene_renderers._dedupe_nav(items)]
        self.assertEqual(labels, ["训练计划表", "训练日志本", "数据"])


class ReachabilityTests(unittest.TestCase):
    def test_missing_modules_are_appended_to_dashboard(self) -> None:
        caps = [{"recommendation_module_id": f"m{i}", "name": f"模块{i}", "description": "说明"} for i in range(5)]
        html = "<section id='dashboard'><a data-dashboard-module-link='m0'></a></section>"
        out = scene_renderers._ensure_all_modules_reachable(html, caps, ["1", "2", "3", "4", "5"])
        for i in range(5):
            self.assertIn(f"data-dashboard-module-link='m{i}'", out)
        self.assertTrue(out.endswith("</section>"))


class ScannerTests(unittest.TestCase):
    def test_snake_case_tokens_detected_in_starter_content(self) -> None:
        product = {"capabilities": [{"starter": {"summary": "ok", "starter_items": [{"title": "示例", "body": "来源状态：synthetic_demo"}]}}]}
        self.assertEqual(evaluation._starter_snake_tokens(product), ["synthetic_demo"])
        self.assertFalse(evaluation.SNAKE_CASE_TOKEN.findall("index.html 与 v0.42.0、APA 格式"))


class EncodingTests(unittest.TestCase):
    def test_bom_and_utf16_are_accepted_and_others_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.txt"
            for encoding in ("utf-8", "utf-8-sig", "utf-16"):
                path.write_text("个人工作台", encoding=encoding)
                self.assertEqual(read_user_text(path), "个人工作台")
            path.write_bytes("个人工作台".encode("gbk"))
            with self.assertRaises(ContractError):
                read_user_text(path)


class GeneratedScriptTests(unittest.TestCase):
    def test_no_utc_date_slicing_in_page_script(self) -> None:
        source = Path(builder.__file__).read_text(encoding="utf-8")
        self.assertNotIn("toISOString().slice(0,10)", source)
        self.assertIn("function dateKey(date)", source)

    def test_csp_blocks_network(self) -> None:
        self.assertIn("connect-src 'none'", builder.CSP_POLICY)
        self.assertIn("default-src 'none'", builder.CSP_POLICY)
        self.assertNotIn("http", builder.CSP_POLICY)


class BrowserDiscoveryTests(unittest.TestCase):
    def test_playwright_cache_layouts(self) -> None:
        layouts = [
            "chromium-1200/chrome-linux64/chrome",
            "chromium-1200/chrome-win64/chrome.exe",
            "chromium-1200/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ]
        for layout in layouts:
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / layout
                target.parent.mkdir(parents=True)
                target.write_text("")
                with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": temp}):
                    self.assertIn(target, evaluation._playwright_cache_browsers())


if __name__ == "__main__":
    unittest.main()
