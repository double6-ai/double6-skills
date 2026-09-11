import unittest


def _libreoffice_status(text_ok, notes_ok, identities_ok, visual_ok, edit_status):
    core_ok = text_ok and notes_ok and visual_ok
    edit_ok = edit_status in {"pass", "not_automated"}
    if core_ok and edit_ok and identities_ok:
        return "pass"
    if core_ok and edit_ok:
        return "pass_with_warnings"
    return "fail"


class LibreOfficeGatePolicyTest(unittest.TestCase):
    def test_identity_drift_is_warning_not_fail(self):
        self.assertEqual(_libreoffice_status(True, True, False, True, "pass"), "pass_with_warnings")

    def test_full_pass(self):
        self.assertEqual(_libreoffice_status(True, True, True, True, "pass"), "pass")

    def test_text_loss_fails(self):
        self.assertEqual(_libreoffice_status(False, True, True, True, "pass"), "fail")


if __name__ == "__main__":
    unittest.main()
