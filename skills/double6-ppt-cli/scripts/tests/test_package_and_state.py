from __future__ import annotations

import sys
import tempfile
import os
import sys
import unittest
import zipfile
import stat
from pathlib import Path
from unittest.mock import patch

from double6_ppt_cli.common import D6PPTError, SCHEMA_VERSION, load_run, read_json, save_run, sha256_file, write_json
from double6_ppt_cli.package_diff import compare_parts
from double6_ppt_cli.package_hygiene import clean_orphan_slides
from double6_ppt_cli.inspector import _package_hygiene_findings
from double6_ppt_cli.patcher import _package_invariants, _set_numeric_headline_size, _set_text_preserving_runs
from double6_ppt_cli.runs import init_run
from double6_ppt_cli.render_evidence import record_render_manifest
from double6_ppt_cli.verifier import _reusable_powerpoint_receipt, _snapshot
from double6_ppt_cli.schemas import validate_object_map


class PackageAndStateTests(unittest.TestCase):
    def _zip(self, path: Path, value: bytes):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a.xml", value)

    @unittest.skipUnless(sys.platform == "darwin", "macOS /private/tmp guard")
    def test_macos_private_tmp_run_is_rejected_before_powerpoint_access(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.pptx"
            self._zip(source, b"a")
            forbidden = Path("/private/tmp") / f"double6-ppt-test-{Path(temp).name}"
            with patch("double6_ppt_cli.runs.sys.platform", "darwin"):
                with self.assertRaises(D6PPTError) as caught:
                    init_run("postflight", source, forbidden)
            self.assertEqual(caught.exception.code, "powerpoint_inaccessible_workdir")

    def test_package_diff_reports_only_changed_parts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before, after = root / "before.pptx", root / "after.pptx"
            self._zip(before, b"a"); self._zip(after, b"b")
            self.assertEqual(compare_parts(before, after)["changed"], ["a.xml"])

    def _orphan_slide_fixture(self, path: Path, *, live_link_to_orphan: bool = False) -> bytes:
        click = '<a:hlinkClick r:id="rIdOld" action="ppaction://hlinksldjump"/>' if live_link_to_orphan else ''
        parts = {
            "[Content_Types].xml": (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/ppt/presentation.xml" ContentType="application/xml"/>'
                '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/xml"/>'
                '<Override PartName="/ppt/slides/slide2.xml" ContentType="application/xml"/>'
                '</Types>'
            ).encode(),
            "_rels/.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
                '</Relationships>'
            ).encode(),
            "ppt/presentation.xml": (
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>'
            ).encode(),
            "ppt/_rels/presentation.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>'
                '</Relationships>'
            ).encode(),
            "ppt/slides/slide1.xml": (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr>'
                f'<p:cNvPr id="2" name="live">{click}</p:cNvPr><p:cNvSpPr/><p:nvPr/>'
                '</p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Live</a:t></a:r></a:p></p:txBody>'
                '</p:sp></p:spTree></p:cSld></p:sld>'
            ).encode(),
            "ppt/slides/_rels/slide1.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                '<Relationship Id="rIdOld" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide2.xml"/>'
                '</Relationships>'
            ).encode(),
            "ppt/slides/slide2.xml": (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
                '<p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="sample"/>'
                '<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:txBody><a:p><a:r><a:t>【本章标题】</a:t></a:r></a:p></p:txBody>'
                '</p:sp></p:spTree></p:cSld></p:sld>'
            ).encode(),
            "ppt/slides/_rels/slide2.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                '</Relationships>'
            ).encode(),
            "ppt/slideLayouts/slideLayout1.xml": b'<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        return parts["ppt/slides/slide1.xml"]

    def test_package_cleanup_removes_only_unreachable_slides_and_stale_slide_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"
            live_xml = self._orphan_slide_fixture(source)
            before_findings = _package_hygiene_findings(source, [r"【[^】]+】"])
            self.assertEqual(before_findings[0]["severity"], "error")
            self.assertEqual(before_findings[0]["suggested_route"], "package_clean")
            run = root / "run"
            init_run("postflight", source, run)
            receipt = clean_orphan_slides(run)
            self.assertEqual(receipt["result"], "cleaned")
            self.assertEqual(receipt["removed_orphan_slide_parts"], ["ppt/slides/slide2.xml"])
            current = run / "artifacts" / "package-cleaned.pptx"
            with zipfile.ZipFile(current) as archive:
                names = set(archive.namelist())
                self.assertNotIn("ppt/slides/slide2.xml", names)
                self.assertNotIn("ppt/slides/_rels/slide2.xml.rels", names)
                self.assertEqual(archive.read("ppt/slides/slide1.xml"), live_xml)
                self.assertNotIn(b"rIdOld", archive.read("ppt/slides/_rels/slide1.xml.rels"))
                self.assertNotIn(b"rId2", archive.read("ppt/_rels/presentation.xml.rels"))
                self.assertNotIn(b"/ppt/slides/slide2.xml", archive.read("[Content_Types].xml"))
            self.assertEqual(_package_hygiene_findings(current), [])
            manifest = load_run(run)
            self.assertEqual(manifest["artifacts"]["current_pptx"], "artifacts/package-cleaned.pptx")
            self.assertEqual(manifest["powerpoint_status"], "unverified")

    def test_package_cleanup_retains_nonlogical_slide_with_live_jump(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"
            self._orphan_slide_fixture(source, live_link_to_orphan=True)
            run = root / "run"
            init_run("postflight", source, run)
            receipt = clean_orphan_slides(run)
            self.assertEqual(receipt["removed_orphan_slide_parts"], [])
            self.assertEqual(receipt["retained_nonlogical_slides"][0]["slide_part"], "ppt/slides/slide2.xml")
            with zipfile.ZipFile(run / "artifacts" / "package-cleaned.pptx") as archive:
                self.assertIn("ppt/slides/slide2.xml", archive.namelist())
                self.assertIn(b"rIdOld", archive.read("ppt/slides/_rels/slide1.xml.rels"))

    def test_stale_object_map_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pptx = root / "x.pptx"
            self._zip(pptx, b"a")
            mapping = {
                "schema_version": SCHEMA_VERSION, "pptx_sha256": "0" * 64,
                "objects": [{"source_id": "x", "officecli_path": "/slide[1]/shape[@id=1]"}],
            }
            with self.assertRaises(D6PPTError) as ctx:
                validate_object_map(mapping, pptx)
            self.assertEqual(ctx.exception.code, "stale_object_map")

    def test_ambiguous_object_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pptx = root / "x.pptx"
            self._zip(pptx, b"a")
            mapping = {
                "schema_version": SCHEMA_VERSION, "pptx_sha256": sha256_file(pptx),
                "objects": [
                    {"source_id": "x", "officecli_path": "/slide[1]/shape[@id=1]"},
                    {"source_id": "y", "officecli_path": "/slide[1]/shape[@id=1]"},
                ],
            }
            with self.assertRaises(D6PPTError) as ctx:
                validate_object_map(mapping, pptx)
            self.assertEqual(ctx.exception.code, "ambiguous_object_map")

    def test_v1_manifest_is_readable_but_never_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            write_json(run / "run_manifest.json", {
                "schema_version": "1.0", "run_id": "legacy", "mode": "postflight",
                "status": "initialized", "artifacts": {},
            })
            migrated = load_run(run)
            self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)
            self.assertTrue(migrated["_legacy_read_only"])
            with self.assertRaises(D6PPTError) as caught:
                save_run(run, migrated)
            self.assertEqual(caught.exception.code, "legacy_run_read_only")
            self.assertEqual(read_json(run / "run_manifest.json")["schema_version"], "1.0")

    def test_postflight_working_copy_is_writable_when_frozen_input_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "frozen.pptx"
            self._zip(source, b"a")
            source.chmod(0o444)
            run = root / "run"
            init_run("postflight", source, run)
            current = run / "artifacts" / "current.pptx"
            self.assertTrue(current.stat().st_mode & stat.S_IWUSR)
            self.assertEqual(source.stat().st_mode & stat.S_IWUSR, 0)

    def test_scope_invariants_follow_logical_slide_order_not_part_number(self):
        with tempfile.TemporaryDirectory() as temp:
            pptx = Path(temp) / "reordered.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
                archive.writestr(
                    "ppt/presentation.xml",
                    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<p:sldIdLst><p:sldId id="1" r:id="rId5"/><p:sldId id="2" r:id="rId2"/></p:sldIdLst>'
                    '</p:presentation>',
                )
                archive.writestr(
                    "ppt/_rels/presentation.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId2" Target="slides/slide2.xml"/>'
                    '<Relationship Id="rId5" Target="slides/slide5.xml"/>'
                    '</Relationships>',
                )
                archive.writestr(
                    "ppt/slides/slide2.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    '<p:cNvPr id="22" name="logical-two-object"/><a:t>logical two</a:t></p:sld>',
                )
                archive.writestr(
                    "ppt/slides/slide5.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    '<p:cNvPr id="55" name="logical-one-object"/><a:t>logical one</a:t></p:sld>',
                )
            invariants = _package_invariants(pptx)
            expected_first = __import__("hashlib").sha256(b"logical one").hexdigest()
            expected_second = __import__("hashlib").sha256(b"logical two").hexdigest()
            self.assertEqual(invariants["slide_text_sha256"], {1: expected_first, 2: expected_second})
            snapshot = _snapshot(pptx)
            self.assertEqual(
                snapshot["identities"],
                ["slide:1:id:55:name:logical-one-object", "slide:2:id:22:name:logical-two-object"],
            )

    def test_powerpoint_receipt_is_reused_only_for_same_sha_and_complete_render(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            evidence = run / "evidence" / "powerpoint_roundtrip"
            render = run / "evidence" / "powerpoint_render"
            review = run / "review"
            evidence.mkdir(parents=True); render.mkdir(parents=True); review.mkdir()
            roundtrip = evidence / "roundtrip-edit-probe.pptx"
            pdf = render / "powerpoint-render.pdf"
            page = render / "slide-01.png"
            contact = review / "contact_sheet-native.png"
            current = run / "artifacts" / "current.pptx"
            current.parent.mkdir(parents=True)
            for path in (roundtrip, pdf, page, contact, current):
                path.write_bytes(b"evidence")
            source_sha = sha256_file(current)
            record_render_manifest(
                run, current, verification_tier="native", renderer="Microsoft PowerPoint",
                fact_source="powerpoint", pdf=pdf, pages=[page], contact_sheet=contact,
            )
            write_json(evidence / "receipt.json", {
                "status": "pass",
                "source_pptx_sha256": source_sha,
                "roundtrip_pptx": "evidence/powerpoint_roundtrip/roundtrip-edit-probe.pptx",
                "render": {
                    "pdf": str(pdf),
                    "pages": [str(page)],
                    "contact_sheet": str(contact),
                },
            })
            reused = _reusable_powerpoint_receipt(run, source_sha)
            self.assertTrue(reused and reused["reused_for_same_pptx_sha"])
            self.assertIsNone(_reusable_powerpoint_receipt(run, "b" * 64))
            page.unlink()
            self.assertIsNone(_reusable_powerpoint_receipt(run, source_sha))

    def test_ooxml_text_and_numeric_size_repairs_preserve_secondary_run_style(self):
        with tempfile.TemporaryDirectory() as temp:
            pptx = Path(temp) / "rich.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
                archive.writestr(
                    "ppt/presentation.xml",
                    '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<p:sldIdLst><p:sldId id="1" r:id="rId1"/></p:sldIdLst></p:presentation>',
                )
                archive.writestr(
                    "ppt/_rels/presentation.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="slides/slide9.xml"/></Relationships>',
                )
                archive.writestr(
                    "ppt/slides/slide9.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:sp>'
                    '<p:nvSpPr><p:cNvPr id="7" name="metric"/></p:nvSpPr><p:txBody><a:bodyPr/><a:lstStyle/>'
                    '<a:p><a:r><a:rPr sz="4000" b="1"/><a:t>87pp</a:t></a:r></a:p>'
                    '<a:p><a:r><a:rPr sz="1100" b="0"/><a:t>说明文字</a:t></a:r></a:p>'
                    '</p:txBody></p:sp></p:sld>',
                )
            path = "/slide[1]/shape[@id=7]"
            _set_text_preserving_runs(pptx, path, "87pp\n说明文字", "87 个百分点\n说明文字")
            _set_numeric_headline_size(pptx, path, "32pt", "d6-numeric-display-capacity-test")
            with zipfile.ZipFile(pptx) as archive:
                root = __import__("lxml.etree", fromlist=["etree"]).fromstring(archive.read("ppt/slides/slide9.xml"))
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                texts = root.xpath(".//a:t/text()", namespaces=ns)
                sizes = root.xpath(".//a:rPr/@sz", namespaces=ns)
                bold = root.xpath(".//a:rPr/@b", namespaces=ns)
            self.assertEqual(texts, ["87 个百分点", "说明文字"])
            self.assertEqual(sizes, ["3200", "1100"])
            self.assertEqual(bold, ["1", "0"])


if __name__ == "__main__":
    unittest.main()
