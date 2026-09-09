from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from double6_ppt_cli.common import D6PPTError, sha256_file, write_json
from double6_ppt_cli.finalizer import finalize_run
from double6_ppt_cli.powerpoint import detect_powerpoint_capability, is_portable_fallback_error
from double6_ppt_cli.runs import init_run
from double6_ppt_cli.verifier import _resolve_verify_tier, verify_run


def _minimal_pptx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/xml"/>'
            "</Types>",
        )
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>'
            "<p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"d6:slide-001-title\"/>"
            "<p:cNvSpPr/><p:nvPr><p:ph type=\"title\"/></p:nvPr></p:nvSpPr>"
            "<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Hello</a:t></a:r></a:p></p:txBody></p:sp>"
            "</p:spTree></p:cSld></p:sld>",
        )


class VerifyTierTests(unittest.TestCase):
    def test_auto_selects_portable_when_powerpoint_missing(self):
        capability = {"available": False, "reason": "PowerPoint.app is not installed"}
        self.assertEqual(_resolve_verify_tier("auto", capability, None), "portable")
        self.assertEqual(_resolve_verify_tier("native", capability, None), "native")
        self.assertEqual(_resolve_verify_tier("portable", {"available": True}, None), "portable")
        self.assertEqual(_resolve_verify_tier("auto", {"available": True}, None), "native")
        # reusable native receipt keeps native even if current capability is false
        self.assertEqual(_resolve_verify_tier("auto", capability, {"status": "pass"}), "native")
        self.assertEqual(_resolve_verify_tier("portable", {"available": True}, {"status": "pass"}), "portable")

    def test_accessibility_denied_is_portable_fallback(self):
        exc = D6PPTError("osascript 不允许辅助访问", "powerpoint_roundtrip_failed")
        self.assertTrue(is_portable_fallback_error(exc))
        denied = D6PPTError("denied", "powerpoint_accessibility_denied")
        self.assertTrue(is_portable_fallback_error(denied))
        busy = D6PPTError("another presentation open", "powerpoint_busy")
        self.assertFalse(is_portable_fallback_error(busy))

    def test_detect_powerpoint_capability_reports_missing_app(self):
        with patch("double6_ppt_cli.powerpoint.find_powerpoint", return_value=None), \
             patch("double6_ppt_cli.powerpoint.shutil.which", return_value="/usr/bin/osascript"):
            capability = detect_powerpoint_capability()
        self.assertFalse(capability["available"])
        self.assertIn("PowerPoint.app", capability["reason"])

    def test_portable_verify_and_finalize_do_not_require_powerpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"
            _minimal_pptx(source)
            run = root / "run"
            init_run("postflight", source, run)
            current = run / "artifacts" / "current.pptx"
            sha = sha256_file(current)
            write_json(
                run / "evidence" / "findings.json",
                {"pptx_sha256": sha, "finding_count": 0, "blocking_count": 0, "warning_count": 0, "findings": []},
            )
            write_json(
                run / "artifacts" / "object_path_map.json",
                {
                    "schema_version": "2.0",
                    "pptx_sha256": sha,
                    "semantic_manifest_sha256": sha,
                    "objects": [{
                        "source_id": "slide-001-title",
                        "slide": 1,
                        "role": "title",
                        "editable": True,
                        "postflight_sensitive": True,
                        "placeholder": "title",
                        "drawingml_id": 2,
                        "drawingml_type": "shape",
                        "drawingml_name": "d6:slide-001-title",
                        "officecli_path": "/slide[1]/shape[@id=2]",
                    }],
                },
            )
            client = MagicMock()
            client.validate.return_value = {"success": True, "ok": True}
            client.run.side_effect = lambda args: {
                "data": {
                    "results": [{
                        "path": "/slide[1]/shape[@id=2]",
                        "type": "title",
                        "text": "Hello",
                        "format": {"name": "d6:slide-001-title", "x": "10pt"},
                    }]
                }
            }
            with patch("double6_ppt_cli.verifier.OfficeCLI", return_value=client), \
                 patch("double6_ppt_cli.verifier._portable_render", return_value={"status": "not_available"}), \
                 patch("double6_ppt_cli.verifier._portable_editability", return_value={"status": "pass"}), \
                 patch("double6_ppt_cli.verifier.resolve_visual_gate", return_value=("skipped_with_user_ack", {"status": "skipped_with_user_ack"})), \
                 patch("double6_ppt_cli.verifier.detect_powerpoint_capability", return_value={"available": False, "reason": "missing"}):
                receipt = verify_run(run, tier="portable")
            self.assertEqual(receipt["verification_tier"], "portable")
            self.assertEqual(receipt["powerpoint_status"], "skipped_portable_tier")
            self.assertEqual(receipt["status"], "pass_with_warnings")
            self.assertEqual(receipt["gates"]["powerpoint_roundtrip"], "skipped_portable_tier")
            delivery = finalize_run(run)
            self.assertEqual(delivery["status"], "delivered_with_warnings")
            self.assertEqual(delivery["verification_tier"], "portable")
            self.assertIn("未在本机 Microsoft PowerPoint", " ".join(delivery["warnings"]))
            self.assertIn("OfficeCLI", delivery["compatibility_statement"])

    def test_native_tier_still_blocks_when_powerpoint_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"
            _minimal_pptx(source)
            run = root / "run"
            init_run("postflight", source, run)
            current = run / "artifacts" / "current.pptx"
            sha = sha256_file(current)
            write_json(
                run / "evidence" / "findings.json",
                {"pptx_sha256": sha, "finding_count": 0, "blocking_count": 0, "warning_count": 0, "findings": []},
            )
            client = MagicMock()
            client.validate.return_value = {"success": True}
            with patch("double6_ppt_cli.verifier.OfficeCLI", return_value=client), \
                 patch("double6_ppt_cli.verifier.detect_powerpoint_capability", return_value={"available": False}), \
                 patch("double6_ppt_cli.verifier.verify_with_powerpoint", side_effect=D6PPTError("PowerPoint is required", "powerpoint_missing")):
                with self.assertRaises(D6PPTError) as caught:
                    verify_run(run, tier="native")
            self.assertEqual(caught.exception.code, "powerpoint_missing")

    def test_portable_render_finds_pdf_in_nested_dir(self):
        from double6_ppt_cli.verifier import _portable_render

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "run"
            (run / "review").mkdir(parents=True)
            pptx = run / "artifacts" / "current.pptx"
            pptx.parent.mkdir(parents=True)
            _minimal_pptx(pptx)

            def fake_render(_pptx: Path, out: Path, _soffice: Path) -> list[Path]:
                out.mkdir(parents=True, exist_ok=True)
                (out / "pdf").mkdir(exist_ok=True)
                (out / "pdf" / "current.pdf").write_bytes(b"pdf")
                page = out / "slide-1.png"
                page.write_bytes(b"png")
                return [page]

            with patch("double6_ppt_cli.verifier.find_soffice", return_value=Path("/usr/bin/soffice")), \
                 patch("double6_ppt_cli.verifier.shutil.which", return_value="/usr/bin/pdftoppm"), \
                 patch("double6_ppt_cli.verifier._render_libreoffice", side_effect=fake_render), \
                 patch("double6_ppt_cli.verifier._contact_sheet", side_effect=lambda _pages, path: path.write_bytes(b"sheet")):
                receipt = _portable_render(run, pptx)
            self.assertEqual(receipt["status"], "pass")
            self.assertEqual(receipt["pdf"], "evidence/portable_render/pdf/current.pdf")


if __name__ == "__main__":
    unittest.main()
