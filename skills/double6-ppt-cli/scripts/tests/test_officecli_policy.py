import unittest

from double6_ppt_cli.common import classify_officecli_version


class OfficeCLIPolicyTest(unittest.TestCase):
    def test_pin_passes(self):
        result = classify_officecli_version("1.0.144")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reason"], "pinned")

    def test_newer_same_major_warns(self):
        result = classify_officecli_version("1.0.148")
        self.assertEqual(result["status"], "warn")
        self.assertEqual(result["action"], "bootstrap_optional")
        self.assertIn("bootstrap", result["message"])

    def test_major_mismatch_fails(self):
        result = classify_officecli_version("2.0.0")
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "major_mismatch")

    def test_too_old_fails(self):
        result = classify_officecli_version("1.0.100")
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "too_old")

    def test_missing_fails(self):
        result = classify_officecli_version(None)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "missing")


if __name__ == "__main__":
    unittest.main()
