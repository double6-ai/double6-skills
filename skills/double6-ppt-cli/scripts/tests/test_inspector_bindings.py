import unittest
from pathlib import Path
import tempfile
import json

from double6_ppt_cli.inspector import inspect_run
from double6_ppt_cli.common import D6PPTError, write_json


class InspectReadJsonBindingTest(unittest.TestCase):
    def test_missing_object_map_does_not_raise_unbound_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("input", "authoring", "artifacts", "evidence", "logs", "review", "delivery", "patches", "plans"):
                (run / name).mkdir()
            # No PPTX: expect clean domain error, not UnboundLocalError
            write_json(run / "run_manifest.json", {
                "schema_version": "2.0",
                "mode": "generate",
                "artifacts": {"current_pptx": None},
            })
            with self.assertRaises(D6PPTError) as ctx:
                inspect_run(run)
            self.assertEqual(ctx.exception.code, "pptx_missing")


if __name__ == "__main__":
    unittest.main()
