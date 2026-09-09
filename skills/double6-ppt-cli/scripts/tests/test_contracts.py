from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from double6_ppt_cli.common import D6PPTError, SCHEMA_VERSION, sha256_file, write_json
from double6_ppt_cli.routing import route_finding
from double6_ppt_cli.runs import init_run
from double6_ppt_cli.schemas import validate_patch_spec, validate_semantic_manifest


class ContractTests(unittest.TestCase):
    def semantic(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "objects": [{
                "source_id": "slide-001-title", "slide": 1, "role": "title",
                "editable": True, "postflight_sensitive": True,
                "preferred_structure": "placeholder",
                "source_selector": {"file": "svg_output/01.svg", "id": "title"},
                "match": {"text": "Title", "ordinal": 1},
            }],
        }

    def test_semantic_contract_accepts_stable_identity(self):
        validate_semantic_manifest(self.semantic())

    def test_text_alone_is_rejected(self):
        data = self.semantic()
        data["objects"][0]["match"] = {"text": "Title"}
        with self.assertRaises(D6PPTError) as ctx:
            validate_semantic_manifest(data)
        self.assertEqual(ctx.exception.code, "ambiguous_text_identity")

    def test_duplicate_source_id_is_rejected(self):
        data = self.semantic()
        data["objects"].append(dict(data["objects"][0]))
        with self.assertRaises(D6PPTError):
            validate_semantic_manifest(data)

    def test_patch_whitelist(self):
        patch = {
            "source_id": "x", "officecli_path": "/slide[1]/shape[@id=2]",
            "operation": "set_property", "property": "text", "value": "ok",
            "finding_id": "f-1", "source_template_object_id": "s01:shape:2",
            "reason": "exact sample text replacement",
            "expected_fingerprint": {"drawingml_id": 2, "object_type": "shape", "text": "old"},
        }
        validate_patch_spec({"schema_version": SCHEMA_VERSION, "patches": [patch]})
        with self.assertRaises(D6PPTError):
            validate_patch_spec({"schema_version": SCHEMA_VERSION, "patches": [{**patch, "property": "raw_xml", "value": "bad"}]})

    def test_remove_leaf_rejects_group_and_master_paths(self):
        base = {
            "source_id": "x", "operation": "remove_leaf", "finding_id": "f-1",
            "source_template_object_id": "s01:shape:2", "reason": "known sample leaf",
            "expected_fingerprint": {"drawingml_id": 2, "object_type": "shape"},
        }
        for address in ("/slide[1]/group[@id=2]", "/master[1]/shape[@id=2]"):
            with self.assertRaises(D6PPTError) as caught:
                validate_patch_spec({"schema_version": SCHEMA_VERSION, "patches": [{**base, "officecli_path": address}]})
            self.assertEqual(caught.exception.code, "unsafe_patch_target")

    def test_picture_removal_requires_confirmation(self):
        patch = {
            "source_id": "x", "officecli_path": "/slide[1]/picture[@id=4]",
            "operation": "remove_leaf", "finding_id": "f-picture",
            "source_template_object_id": "s01:picture:4", "reason": "template media residue",
            "expected_fingerprint": {"drawingml_id": 4, "object_type": "picture"},
        }
        with self.assertRaises(D6PPTError) as caught:
            validate_patch_spec({"schema_version": SCHEMA_VERSION, "patches": [patch]})
        self.assertEqual(caught.exception.code, "semantic_picture_confirmation_required")

    def test_generate_route_prefers_source(self):
        decision = route_finding({"finding_id": "f1", "category": "layout", "object": {"officecli_path": "/slide[1]/shape[1]"}}, mode="generate", has_source_map=True)
        self.assertEqual(decision["route"], "source_repair")

    def test_postflight_without_map_requires_manual_review(self):
        decision = route_finding({"finding_id": "f1", "category": "visual", "suggested_property": "text", "object": {"officecli_path": "/slide[1]/shape[1]"}}, mode="postflight", has_source_map=False)
        self.assertEqual(decision["route"], "manual_review")

    def test_init_never_overwrites_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.md"
            source.write_text("hello", encoding="utf-8")
            run = root / "run"
            init_run("generate", source, run)
            with self.assertRaises(D6PPTError) as ctx:
                init_run("generate", source, run)
            self.assertEqual(ctx.exception.code, "run_exists")


if __name__ == "__main__":
    unittest.main()
