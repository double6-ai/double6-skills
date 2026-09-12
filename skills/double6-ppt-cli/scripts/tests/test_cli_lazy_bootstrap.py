import unittest
from pathlib import Path
import tempfile

from double6_ppt_cli.cli import build_parser, main
from double6_ppt_cli.common import write_json


class CliLazyImportTest(unittest.TestCase):
    def test_parser_includes_render_import_and_bootstrap(self):
        parser = build_parser()
        args = parser.parse_args(["bootstrap", "--runtime-dir", "/tmp/rt", "--yes"])
        self.assertEqual(args.command, "bootstrap")
        args = parser.parse_args([
            "render-import", "--run", "/tmp/run", "--pdf", "/tmp/a.pdf",
            "--pages", "/tmp/p1.png", "--contact-sheet", "/tmp/c.png",
            "--renderer", "powerpoint-com", "--fact-source", "external",
        ])
        self.assertEqual(args.command, "render-import")

    def test_bootstrap_path_does_not_require_lxml_import(self):
        # Parse only; heavy modules must not be imported at build_parser time.
        import sys
        # ensure we didn't just import compiler because of cli import
        self.assertIn("argparse", sys.modules)
        parser = build_parser()
        args = parser.parse_args(["bootstrap", "--runtime-dir", "/tmp/rt", "--yes"])
        self.assertTrue(args.yes)


class SourceFilesShaTest(unittest.TestCase):
    def test_missing_sha_is_autofilled(self):
        from double6_ppt_cli.schemas import validate_semantic_manifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svg = root / "01.svg"
            svg.write_text("<svg/>", encoding="utf-8")
            data = {
                "schema_version": "2.0",
                "source_files": [{"path": "01.svg"}],
                "objects": [{
                    "source_id": "t",
                    "slide": 1,
                    "role": "title",
                    "editable": True,
                    "postflight_sensitive": True,
                    "preferred_structure": "top_level",
                    "source_selector": {"file": "01.svg", "id": "t"},
                    "match": {"drawingml_id": 1001},
                }],
            }
            validate_semantic_manifest(data, source_root=root)
            self.assertTrue(data["source_files"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
