import unittest
from pathlib import Path
import tempfile
import shutil

from double6_ppt_cli.common import write_json, sha256_file
from double6_ppt_cli.render_evidence import record_render_manifest, load_current_render_manifest
from double6_ppt_cli.verifier import _portable_render


class PortableRenderReuseTest(unittest.TestCase):
    def test_reuses_complete_portable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp).resolve()
            for name in ("evidence", "review", "logs", "artifacts"):
                (run / name).mkdir()
            pptx = run / "artifacts" / "deck.pptx"
            pptx.write_bytes(b"dummy-pptx-bytes")
            pdf = run / "evidence" / "portable_render" / "deck.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(b"%PDF-1.4 dummy")
            page = run / "evidence" / "portable_render" / "slide-1.png"
            page.write_bytes(b"png")
            contact = run / "review" / "contact_sheet-portable.png"
            contact.write_bytes(b"png")
            record_render_manifest(
                run, pptx,
                verification_tier="portable",
                renderer="LibreOffice",
                fact_source="libreoffice_portable",
                pdf=pdf,
                pages=[page],
                contact_sheet=contact,
            )
            result = _portable_render(run, pptx)
            self.assertEqual(result["status"], "pass")
            self.assertTrue(result.get("reused_existing_manifest"))
            # ensure manifest still loads after reuse path
            payload = load_current_render_manifest(run, sha256_file(pptx), expected_tier="portable")
            self.assertEqual(payload["verification_tier"], "portable")


if __name__ == "__main__":
    unittest.main()
