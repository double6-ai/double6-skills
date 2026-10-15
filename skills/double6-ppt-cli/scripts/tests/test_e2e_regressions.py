"""Regressions found by the clean-environment end-to-end runs (0.3.0)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lxml import etree

from double6_ppt_cli.cli import build_parser
from double6_ppt_cli.common import D6PPTError, resolve_run_path
from double6_ppt_cli.compiler import _vendor_conversion_warnings
from double6_ppt_cli.inspector import _compiler_warning_findings, _declared_role
from double6_ppt_cli.semantic import NS, _pad_nowrap_text_frame
from double6_ppt_cli.source_adapter import SVG_NS, _unwrap_single_line_tspans
from double6_ppt_cli.template_workflow import _classify

PAD = {"cjk": 0.12, "latin": 0.04}


def _shape(text: str, *, wrap: str = "none", algn: str = "l", x: int = 1000000, cx: int = 2000000) -> etree._Element:
    xml = (
        f'<p:sp xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:spPr><a:xfrm><a:off x="{x}" y="0"/>'
        f'<a:ext cx="{cx}" cy="400000"/></a:xfrm></p:spPr><p:txBody><a:bodyPr wrap="{wrap}"/>'
        f'<a:p><a:pPr algn="{algn}"/><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    )
    return etree.fromstring(xml)


class RegressionTests(unittest.TestCase):
    def test_single_line_tspan_unwrapped_keeps_shape_id(self) -> None:
        root = etree.fromstring(
            f'<svg xmlns="{SVG_NS}"><text x="10" y="20" data-pptx-shape-id="7">'
            '<tspan x="10">第 7 天</tspan></text>'
            '<text x="10" y="40" data-pptx-shape-id="8"><tspan x="10" dy="0">a</tspan><tspan x="10" dy="20">b</tspan></text></svg>'
        )
        changed = _unwrap_single_line_tspans(root)
        self.assertEqual(len(changed), 1)
        first = root.find(f"{{{SVG_NS}}}text")
        self.assertEqual(first.get("data-pptx-shape-id"), "7")
        self.assertEqual(first.text, "第 7 天")
        self.assertEqual(len(first), 0)
        self.assertEqual(len(root.findall(f"{{{SVG_NS}}}text")[1]), 2)

    def test_nowrap_padding_cjk_centered(self) -> None:
        shape = _shape("第 7 天全量运行", algn="ctr")
        added = _pad_nowrap_text_frame(shape, 12192000, PAD)
        self.assertEqual(added, 240000)
        off = shape.find("p:spPr/a:xfrm/a:off", NS)
        self.assertEqual(off.get("x"), str(1000000 - 120000))

    def test_nowrap_padding_skips_wrapped_and_latin_ratio(self) -> None:
        self.assertEqual(_pad_nowrap_text_frame(_shape("x", wrap="square"), 12192000, PAD), 0)
        self.assertEqual(_pad_nowrap_text_frame(_shape("Revenue"), 12192000, PAD), 80000)

    def test_resolve_run_path_without_pptx_is_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(D6PPTError) as ctx:
                resolve_run_path(Path(tmp), None)
            self.assertEqual(ctx.exception.code, "current_pptx_missing")

    def test_global_runtime_dir_not_overwritten_by_subcommand(self) -> None:
        args = build_parser().parse_args(["--runtime-dir", "/tmp/rt", "doctor"])
        self.assertEqual(Path(args.runtime_dir), Path("/tmp/rt"))

    def test_vendor_warnings_collected_and_surfaced(self) -> None:
        out = "ok\nWarning: chart legend omitted: no visible series names\nWarning: chart legend omitted: no visible series names\n"
        warnings = _vendor_conversion_warnings(out)
        self.assertEqual(len(warnings), 2)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "evidence").mkdir()
            (run / "evidence" / "compiler_warnings.json").write_text(json.dumps({"warnings": warnings}), encoding="utf-8")
            findings = _compiler_warning_findings(run)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["evidence"]["occurrences"], 2)
        self.assertEqual(findings[0]["suggested_route"], "manual_review")

    def test_declared_role_from_descr(self) -> None:
        self.assertEqual(_declared_role({"format": {"alt": "source_id=s1-foot;role=footnote"}}), "footnote")
        self.assertIsNone(_declared_role({"format": {}}))

    def test_decorative_template_shape_is_design(self) -> None:
        self.assertEqual(_classify("", "shape", None, decorative_shape=True), "design_system")
        self.assertEqual(_classify("", "shape", None), "content_slot")
        self.assertEqual(_classify("", "shape", "body", decorative_shape=True), "content_slot")


if __name__ == "__main__":
    unittest.main()
