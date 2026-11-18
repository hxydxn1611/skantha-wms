"""
Hardening round after the RBAC rollout (project review, 2026-11-18).

  * page HTML: user-typed fields are escaped (__h / __js), checked across every script
  * gate OTP: 5 wrong tries, then void; constant-time compare; cleared once verified
  * no third-party texting service; the log never carries phone numbers or codes
  * SKU codes can't carry path pieces or markup
  * error answers don't leak internal exception text
  * cameras without a stream show a "no video signal" card, not a simulated scene
  * startup file and pinned requirements
"""
import os
import re
import unittest

from tests.test_rbac_phase7 import Phase7Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "webapp", "static", "js")


class TestEscaping(unittest.TestCase):
    def test_no_unescaped_user_fields_in_page_templates(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("esc", os.path.join(ROOT, "scripts", "escape_check.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        leftovers = mod.find_unescaped(JS)
        self.assertEqual(leftovers, [], "\n".join(leftovers[:10]))
        sec = open(os.path.join(JS, "security.js"), encoding="utf-8").read()
        self.assertIn("window.__h", sec)
        self.assertIn("window.__js", sec)


class TestGateOtp(Phase7Base):
    def test_wrong_tries_are_limited_and_code_is_cleared(self):
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "POST", "/api/gate_passes", {"plate": "TN38HD0001", "driver_name": "Otp Test", "driver_phone": "9000000001"})
        body = r.get_json()
        gp = body.get("gate_pass", body).get("id") or body.get("id")
        code = self.sql("SELECT otp FROM gate_passes WHERE id = ?", (gp,))[0][0]
        self.assertRegex(code, r"^\d{4}$")
        wrong = "0000" if code != "0000" else "1111"
        for i in range(5):
            r = self.send(d, "POST", "/api/gate/verify_otp", {"gp_id": gp, "otp": wrong})
            self.assertFalse(r.get_json()["success"])
        r = self.send(d, "POST", "/api/gate/verify_otp", {"gp_id": gp, "otp": code})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (429, "otp_locked"))
        self.assertTrue(self.sql("SELECT 1 FROM audit_logs WHERE action = 'gate.otp_failed' AND resource_id = ?", (gp,)))
        # a new code resets the count; the right code verifies and is then cleared
        import db
        db.update_gate_pass(gp, {"otp": "4321"})
        r = self.send(d, "POST", "/api/gate/verify_otp", {"gp_id": gp, "otp": "4321"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.sql("SELECT otp, otp_verified FROM gate_passes WHERE id = ?", (gp,))[0], ("", 1))


class TestNoThirdPartyTexting(unittest.TestCase):
    def test_no_textbelt_and_no_phone_in_logs(self):
        app_src = open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8").read()
        self.assertNotIn("textbelt", app_src)
        self.assertNotIn("[MOCK SMS]", app_src)
        self.assertIsNone(re.search(r"(print|logger\.\w+)\(.*driver_phone", app_src))


class TestCodesAndErrors(Phase7Base):
    def test_sku_codes_cannot_carry_paths_or_markup(self):
        import db
        for bad in ("../etc/x", "A/B", "x\\y", "<b>x", 'q"x'):
            self.assertIsNotNone(db.code_problem(bad), bad)
            r = self.send(self.client("david"), "POST", "/api/skus", {"sku_id": bad, "name": "bad"})
            self.assertFalse(r.get_json().get("success"), bad)
            self.assertFalse(self.sql("SELECT 1 FROM skus WHERE sku_id = ?", (bad.upper(),)), bad)
        self.assertIsNone(db.code_problem("GLS-FLT-04MM"))

    def test_internal_errors_are_not_sent_to_the_browser(self):
        import sqlite3
        app = self.app_module
        with app.app.test_request_context("/api/x"):
            self.assertEqual(app._public_error(ValueError("Quantity must be a number")), "Quantity must be a number")
            self.assertIn("Missing field", app._public_error(KeyError("sku_id")))
            msg = app._public_error(sqlite3.OperationalError("no such table: secret_internal"))
            self.assertNotIn("secret_internal", msg)
            self.assertIn("reference", msg)
        src = open(os.path.join(ROOT, "webapp", "app.py"), encoding="utf-8").read()
        self.assertIsNone(re.search(r"jsonify\(.*str\(e\)", src))


class TestCameraPlaceholder(unittest.TestCase):
    def test_no_simulated_scene_outside_tests(self):
        import vision_runtime_service as vrs
        saved = os.environ.pop("WARLOG_TEST_MODE", None)
        try:
            src = vrs.TestSyntheticFrameSource("CAM-TEST-PH", "Gate 01")
            frame = src.read_frame()
            self.assertEqual(frame.shape, (720, 1280, 3))
            self.assertEqual(src._no_signal_cache["CAM-TEST-PH"][1] is frame, True)
        finally:
            if saved is not None:
                os.environ["WARLOG_TEST_MODE"] = saved


class TestOperations(unittest.TestCase):
    def test_startup_file_and_pinned_requirements(self):
        bat = open(os.path.join(ROOT, "start_production.bat"), encoding="utf-8").read()
        self.assertIn("py -3.14", bat)
        self.assertNotIn("3.12", bat)
        for line in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("gunicorn"):
                self.assertIn("==", line, line)


if __name__ == "__main__":
    unittest.main()
