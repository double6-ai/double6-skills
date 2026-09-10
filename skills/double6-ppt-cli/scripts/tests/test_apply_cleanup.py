import unittest
from pathlib import Path
import hashlib
import tempfile
from unittest import mock

from double6_ppt_cli.common import D6PPTError, write_json
from double6_ppt_cli import template_workflow as tw


class ApplyCleanupTest(unittest.TestCase):
    def test_failed_post_vendor_steps_remove_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp).resolve()
            for name in ("input", "authoring", "artifacts", "evidence", "logs", "review", "delivery", "patches", "plans"):
                (run / name).mkdir()
            template = run / "input" / "template.pptx"
            template.write_bytes(b"dummy-template")
            write_json(run / "run_manifest.json", {
                "schema_version": "2.0",
                "mode": "template-fill",
                "template": {
                    "copied_path": "input/template.pptx",
                    "sha256": hashlib.sha256(b"dummy-template").hexdigest(),
                },
                "content_contract": None,
                "artifacts": {"current_pptx": None},
            })
            write_json(run / "plans" / "plan.json", {"status": "confirmed"})
            write_json(run / "artifacts" / "template_profile.json", {"objects": []})
            fake_report = {
                "summary": {"error": 0, "warn": 0, "ok": 1},
                "validated_navigation_links": [],
                "validated_image_edits": [],
            }

            def fake_vendor_apply(vendor_template, plan, output, **kwargs):
                Path(output).write_bytes(b"vendor-out")

            def boom(*args, **kwargs):
                raise D6PPTError("Navigation style has no explicit fill", "navigation_style_ambiguous")

            with mock.patch.object(tw, "check_template_plan", return_value=fake_report), \
                 mock.patch.object(tw, "_vendor_modules", return_value=(None, fake_vendor_apply, None, None)), \
                 mock.patch.object(tw, "_strip_confirmed_navigation_links", return_value=([], {})), \
                 mock.patch.object(tw, "_inject_confirmed_navigation_links", side_effect=boom):
                with self.assertRaises(D6PPTError) as ctx:
                    tw.apply_template_plan(run, run / "plans" / "plan.json")
            self.assertEqual(ctx.exception.code, "navigation_style_ambiguous")
            self.assertFalse((run / "artifacts" / "template-filled.pptx").exists())


if __name__ == "__main__":
    unittest.main()
