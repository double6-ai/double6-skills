from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lxml import etree

from double6_ppt_cli.common import D6PPTError, sha256_file
from double6_ppt_cli.source_adapter import prepare_ppt_master_project


class SourceAdapterTests(unittest.TestCase):
    def _fixture(self, svg: str) -> tuple[tempfile.TemporaryDirectory, Path, Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        project = root / "source"
        (project / "svg_output").mkdir(parents=True)
        source_svg = project / "svg_output" / "01.svg"
        source_svg.write_text(svg, encoding="utf-8")
        semantic = root / "semantic.json"
        semantic.write_text(json.dumps({
            "schema_version": "1.0",
            "source_files": [{"path": "svg_output/01.svg", "sha256": sha256_file(source_svg)}],
            "objects": [{
                "source_id": "slide-001-title",
                "slide": 1,
                "role": "title",
                "editable": True,
                "postflight_sensitive": True,
                "preferred_structure": "placeholder",
                "placeholder": "title",
                "source_selector": {"file": "svg_output/01.svg", "id": "title"},
                "match": {"text": "Title", "ordinal": 1},
            }],
        }), encoding="utf-8")
        return temp, project, semantic, root / "build"

    def test_safe_root_group_is_flattened_without_mutating_source(self) -> None:
        temp, project, semantic, build = self._fixture(
            '<svg xmlns="http://www.w3.org/2000/svg"><g id="title" data-pptx-bounds="0 0 10 10"><text>Title</text></g></svg>'
        )
        self.addCleanup(temp.cleanup)
        before = sha256_file(project / "svg_output" / "01.svg")
        receipt = prepare_ppt_master_project(project, semantic, build, Path(temp.name) / "receipt.json")
        self.assertEqual(before, sha256_file(project / "svg_output" / "01.svg"))
        tree = etree.parse(str(build / "svg_output" / "01.svg"))
        self.assertFalse(tree.xpath("//*[@id='title']"))
        self.assertEqual(receipt["changes"][0]["action"], "flatten_group")

    def test_transform_group_fails_closed(self) -> None:
        temp, project, semantic, build = self._fixture(
            '<svg xmlns="http://www.w3.org/2000/svg"><g id="title" transform="translate(1 1)"><text>Title</text></g></svg>'
        )
        self.addCleanup(temp.cleanup)
        with self.assertRaises(D6PPTError) as caught:
            prepare_ppt_master_project(project, semantic, build, Path(temp.name) / "receipt.json")
        self.assertEqual(caught.exception.code, "unsafe_source_flatten")


if __name__ == "__main__":
    unittest.main()
