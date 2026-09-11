from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from double6_ppt_cli.common import D6PPTError, SCHEMA_VERSION, sha256_file, write_json
from double6_ppt_cli.doctor import CLAW_HUB_OMITTED_VENDOR_FILES, _vendor_integrity, doctor
from double6_ppt_cli.patcher import apply_patch as apply_bounded_patch
from double6_ppt_cli.semantic import _find
from double6_ppt_cli.verifier import _snapshot


class NegativeBoundaryTests(unittest.TestCase):
    def test_vendor_integrity_distinguishes_clawhub_omission_from_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vendor = root / "vendor" / "ppt-master-core"
            vendor.mkdir(parents=True)
            kept = vendor / "LICENSE"; kept.write_bytes(b"license")
            omitted = sorted(CLAW_HUB_OMITTED_VENDOR_FILES)[0]
            write_json(vendor / "BOM.json", {
                "file_count": 2,
                "files": [
                    {"path": "LICENSE", "sha256": sha256_file(kept)},
                    {"path": omitted, "sha256": "0" * 64},
                ],
            })
            partial = _vendor_integrity(root)
            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial["expected_clawhub_omissions"], [omitted])
            kept.write_bytes(b"tampered")
            failed = _vendor_integrity(root)
            self.assertEqual(failed["status"], "fail")
            self.assertEqual(failed["sha256_mismatches"], ["LICENSE"])

    def test_wrong_officecli_fails_but_missing_libreoffice_is_optional(self) -> None:
        fake = Path("/tmp/officecli-wrong-version")
        with patch("double6_ppt_cli.doctor.find_officecli", return_value=fake), \
             patch("double6_ppt_cli.doctor._version", return_value="2.0.0"), \
             patch("double6_ppt_cli.doctor.find_soffice", return_value=None), \
             patch("double6_ppt_cli.doctor.find_powerpoint", return_value=Path("/Applications/Microsoft PowerPoint.app")), \
             patch("double6_ppt_cli.doctor.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name in {"pdftoppm", "osascript"} else None):
            result = doctor(Path("/tmp/d6ppt-runtime"))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["officecli"]["status"], "fail")
        self.assertEqual(result["checks"]["libreoffice"]["status"], "unavailable")
        self.assertFalse(result["checks"]["libreoffice"]["required"])

    def test_newer_officecli_1x_warns_but_remains_usable(self) -> None:
        fake = Path("/tmp/officecli-newer")
        with patch("double6_ppt_cli.doctor.find_officecli", return_value=fake), \
             patch("double6_ppt_cli.doctor._version", return_value="1.0.999"), \
             patch("double6_ppt_cli.doctor.find_soffice", return_value=Path("/usr/bin/soffice")), \
             patch("double6_ppt_cli.doctor.find_powerpoint", return_value=None), \
             patch("double6_ppt_cli.doctor.shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "pdftoppm" else None):
            result = doctor(Path("/tmp/d6ppt-runtime"), verify_tier="portable", mode="postflight")
        self.assertEqual(result["checks"]["officecli"]["status"], "warn")
        self.assertTrue(result["capabilities"]["portable_ready"])

    def test_corrupt_pptx_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pptx = Path(temp) / "broken.pptx"
            with zipfile.ZipFile(pptx, "w") as archive:
                archive.writestr("ppt/presentation.xml", b"<broken")
            with self.assertRaises(D6PPTError) as caught:
                _snapshot(pptx)
            self.assertEqual(caught.exception.code, "corrupt_pptx")

    def test_grouped_sensitive_shape_is_rejected(self) -> None:
        xml = """
        <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
               xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <p:cSld><p:spTree>
            <p:grpSp><p:nvGrpSpPr><p:cNvPr id="2" name="g"/></p:nvGrpSpPr>
              <p:sp><p:nvSpPr><p:cNvPr id="3" name="s"/></p:nvSpPr>
                <p:txBody><a:p><a:r><a:t>Sensitive</a:t></a:r></a:p></p:txBody>
              </p:sp>
            </p:grpSp>
          </p:spTree></p:cSld>
        </p:sld>
        """
        root = etree.fromstring(xml.encode("utf-8"))
        obj = {
            "source_id": "grouped-sensitive", "preferred_structure": "top_level",
            "match": {"text": "Sensitive", "kind": "shape", "ordinal": 1},
        }
        with self.assertRaises(D6PPTError) as caught:
            _find(root, obj)
        self.assertEqual(caught.exception.code, "structure_contract_violation")

    def test_patch_refuses_original_source_even_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            (run / "artifacts").mkdir(parents=True)
            (run / "patches").mkdir()
            (run / "evidence").mkdir()
            current = run / "artifacts" / "current.pptx"
            with zipfile.ZipFile(current, "w") as archive:
                archive.writestr("[Content_Types].xml", b"<Types/>")
            manifest = {
                "schema_version": "1.0", "run_id": "negative", "mode": "postflight",
                "status": "inspected", "input": {"original_path": str(current)},
                "artifacts": {"current_pptx": "artifacts/current.pptx"},
            }
            (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            spec = run / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": "1.0", "pptx_sha256": sha256_file(current),
                "user_confirmed": True,
                "patches": [{"officecli_path": "/slide[1]/shape[@id=1]", "property": "text", "value": "x"}],
            }), encoding="utf-8")
            with self.assertRaises(D6PPTError) as caught:
                apply_bounded_patch(run, spec)
            self.assertEqual(caught.exception.code, "source_overwrite_forbidden")

    def test_patch_rejects_old_pptx_sha_before_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            for name in ("artifacts", "patches", "evidence"):
                (run / name).mkdir(parents=True, exist_ok=True)
            current = run / "artifacts" / "current.pptx"
            with zipfile.ZipFile(current, "w") as archive:
                archive.writestr("[Content_Types].xml", b"<Types/>")
            manifest = {
                "schema_version": SCHEMA_VERSION, "run_id": "stale", "mode": "postflight",
                "status": "inspected", "input": {"original_path": str(Path(temp) / "source.pptx")},
                "artifacts": {"current_pptx": "artifacts/current.pptx"},
            }
            (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            spec = run / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION, "pptx_sha256": "0" * 64,
                "patches": [{
                    "source_id": "x", "officecli_path": "/slide[1]/shape[@id=2]",
                    "operation": "set_property", "property": "text", "value": "new",
                    "finding_id": "f", "source_template_object_id": "s01:shape:2",
                    "reason": "test", "expected_fingerprint": {"drawingml_id": 2, "object_type": "shape"},
                }],
            }), encoding="utf-8")
            with self.assertRaises(D6PPTError) as caught:
                apply_bounded_patch(run, spec)
            self.assertEqual(caught.exception.code, "stale_patch_precondition")


if __name__ == "__main__":
    unittest.main()
