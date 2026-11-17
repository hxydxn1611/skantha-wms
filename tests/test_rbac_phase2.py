"""
RBAC Phase 2 exit tests: route coverage, permission enforcement (audit and enforce),
CSRF, reasons for exceptional actions, Copilot actions, camera streams, OTP secrecy
and error-text hardening.

Runs on its own copy of the live database. RBAC_MODE is switched per test by patching
rbac_config.RBAC_MODE; the live server's setting is not involved.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

from tests import copy_live_db, prepare_test_db, session_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, WEBAPP)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import rbac_snapshot  # noqa: E402

COMPANY_ADMIN = "david"


class Phase2Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import db
        import app as app_module
        import rbac_config
        import rbac_routes
        import rbac_catalog
        import rbac_migration
        cls.db, cls.app_module, cls.cfg, cls.routes, cls.catalog = db, app_module, rbac_config, rbac_routes, rbac_catalog
        cls._tmp = tempfile.mkdtemp(prefix="warlog_phase2_")
        cls.db_path = prepare_test_db(copy_live_db(os.path.join(cls._tmp, "phase2.db")))
        cls._saved = (db.DB_PATH, os.environ.get("WARLOG_DB_PATH"), rbac_config.RBAC_MODE)
        db.DB_PATH = cls.db_path
        os.environ["WARLOG_DB_PATH"] = cls.db_path
        conn = sqlite3.connect(cls.db_path)
        with conn:
            conn.execute("UPDATE users SET must_reset_password = 0")
            # A user with one custom role: "Gate Viewer" (gate.pass.view only) at WH-GLASS-COI
            company_id, wh_id = conn.execute(
                "SELECT company_id, id FROM warehouses WHERE code = 'WH-GLASS-COI'").fetchone()
            conn.execute("INSERT INTO users (username, password, company_name, assigned_warehouse_code, role) "
                         "VALUES ('gateviewer', '', 'glass and brass', 'WH-GLASS-COI', 'User')")
            uid = conn.execute("SELECT id FROM users WHERE username = 'gateviewer'").fetchone()[0]
            role_id = conn.execute("INSERT INTO roles (company_id, name, description) VALUES (?, 'Gate Viewer', 'test')",
                                   (company_id,)).lastrowid
            conn.execute("INSERT INTO role_permissions (role_id, permission_key) VALUES (?, 'gate.pass.view')", (role_id,))
            conn.execute("INSERT INTO user_company_access (user_id, company_id) VALUES (?, ?)", (uid, company_id))
            conn.execute("INSERT INTO user_warehouse_access (user_id, company_id, warehouse_id, role_id) VALUES (?, ?, ?, ?)",
                         (uid, company_id, wh_id, role_id))
            # a gate pass with a driver OTP (in admin's warehouse) and one in the glass warehouse
            conn.execute("UPDATE gate_passes SET otp = '4321', otp_verified = 0 WHERE id = (SELECT id FROM gate_passes ORDER BY id LIMIT 1)")
            conn.execute("UPDATE gate_passes SET warehouse_id = ?, company_id = ? WHERE id = (SELECT id FROM gate_passes ORDER BY id DESC LIMIT 1)",
                         (wh_id, company_id))
        conn.close()
        cls.gp_id = sqlite3.connect(cls.db_path).execute("SELECT id FROM gate_passes WHERE otp = '4321'").fetchone()[0]
        cls.glass_gp_id = sqlite3.connect(cls.db_path).execute(
            "SELECT id FROM gate_passes ORDER BY id DESC LIMIT 1").fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.db.DB_PATH, env, cls.cfg.RBAC_MODE = cls._saved
        if env is None:
            os.environ.pop("WARLOG_DB_PATH", None)
        else:
            os.environ["WARLOG_DB_PATH"] = env
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.cfg.RBAC_MODE = "enforce"

    def client(self, username):
        c = self.app_module.app.test_client()
        with c.session_transaction() as s:
            s["user"] = session_for(username, self.db_path)
            s["csrf"] = "test-csrf-token"
        c.csrf = "test-csrf-token"
        return c

    def post(self, c, path, body=None, csrf=True, **headers):
        if csrf:
            headers["X-CSRF-Token"] = c.csrf
        return c.post(path, json=body or {}, headers=headers)

    def audit_actions(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return [r[0] for r in conn.execute("SELECT action FROM audit_logs ORDER BY id")]
        finally:
            conn.close()


class TestCoverage(Phase2Base):
    def test_every_route_is_mapped_and_every_key_exists(self):
        listed = set(self.routes.ROUTE_PERMISSIONS) | self.routes.PUBLIC_ENDPOINTS | self.routes.AUTHENTICATED_ENDPOINTS
        endpoints = {r.endpoint for r in self.app_module.app.url_map.iter_rules()}
        self.assertEqual(sorted(endpoints - listed), [], "routes without a permission")
        self.assertEqual(sorted(set(self.routes.ROUTE_PERMISSIONS) - endpoints), [], "map entries without a route")
        for rule in self.app_module.app.url_map.iter_rules():
            if rule.endpoint in self.routes.PUBLIC_ENDPOINTS | self.routes.AUTHENTICATED_ENDPOINTS:
                continue
            for m in rule.methods - {"HEAD", "OPTIONS"}:
                key = self.routes.permission_for(rule.endpoint, m)
                self.assertIn(key, self.catalog.PERMISSIONS_BY_KEY, f"{m} {rule.rule}")

    def test_route_map_document_is_current(self):
        import rbac_route_map
        expected = rbac_route_map.render_csv(rbac_route_map.build_rows(self.app_module.app.url_map))
        with open(os.path.join(ROOT, "docs", "rbac_route_map.csv"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), expected, "run: py -3.14 scripts/rbac_route_map.py")

    def test_platform_permissions_only_on_platform_routes(self):
        plat = {e for e, v in self.routes.ROUTE_PERMISSIONS.items()
                if any(k.startswith("platform.") for k in ([v] if isinstance(v, str) else v.values()))}
        self.assertEqual(plat, {"api_company_auto_setup"})


class TestEnforcement(Phase2Base):
    def test_admins_are_never_denied_on_existing_screens(self):
        for user in ("admin", COMPANY_ADMIN):
            c = self.client(user)
            for path in rbac_snapshot.API_ENDPOINTS:
                r = c.get(path)
                self.assertNotEqual(r.status_code, 403, f"{user} denied on {path}: {r.get_data(as_text=True)[:200]}")
        self.assertNotIn("access.denied", self.audit_actions())

    def test_custom_role_gets_exactly_its_permission(self):
        c = self.client("gateviewer")
        self.assertEqual(c.get("/api/gate_passes").status_code, 200)
        for path in ("/api/stats", "/api/skus", "/api/cameras", "/api/deliveries", f"/api/gate_passes/{self.gp_id}/otp"):
            r = c.get(path)
            self.assertEqual(r.status_code, 403, path)
            self.assertEqual(r.get_json()["error_code"], "permission_denied")
        for path in ("/api/gate/verify_otp", "/api/gate/approve_all_matched", "/api/gate/register_walkin_vehicle"):
            self.assertEqual(self.post(c, path, {"gp_id": self.gp_id, "otp": "4321", "reason": "x"}).status_code, 403, path)
        self.assertEqual(c.get("/video_feed/CAM-001").status_code, 403)
        self.assertIn("access.denied", self.audit_actions())

    def test_company_admin_cannot_use_platform_routes(self):
        c = self.client(COMPANY_ADMIN)
        r = self.post(c, "/api/company/auto_setup", {"company_name": "Takeover Inc", "reason": "x"})
        self.assertEqual(r.status_code, 403)

    def test_audit_mode_logs_but_does_not_block(self):
        self.cfg.RBAC_MODE = "audit"
        before = self.audit_actions().count("access.would_deny")
        c = self.client("gateviewer")
        self.assertEqual(c.get("/api/skus").status_code, 200)
        self.assertEqual(self.audit_actions().count("access.would_deny"), before + 1)

    def test_off_mode_checks_nothing(self):
        self.cfg.RBAC_MODE = "off"
        before = len(self.audit_actions())
        c = self.client("gateviewer")
        self.assertEqual(c.get("/api/skus").status_code, 200)
        self.assertEqual(c.post("/api/gate/verify_otp", json={"gp_id": "none", "otp": "1"}).status_code, 200)
        self.assertEqual(len(self.audit_actions()), before)

    def test_revoking_a_permission_takes_effect_on_the_next_request(self):
        c = self.client("gateviewer")
        self.assertEqual(c.get("/api/gate_passes").status_code, 200)
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("DELETE FROM role_permissions WHERE permission_key = 'gate.pass.view' "
                         "AND role_id = (SELECT id FROM roles WHERE name = 'Gate Viewer')")
        conn.close()
        self.assertEqual(c.get("/api/gate_passes").status_code, 403)
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("INSERT INTO role_permissions (role_id, permission_key) "
                         "SELECT id, 'gate.pass.view' FROM roles WHERE name = 'Gate Viewer'")
        conn.close()


class TestCsrfAndReasons(Phase2Base):
    def test_state_changes_need_the_csrf_token(self):
        c = self.client("admin")
        r = self.post(c, "/api/gate/verify_otp", {"gp_id": self.gp_id, "otp": "0000"}, csrf=False)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error_code"], "csrf_failed")
        r = self.post(c, "/api/gate/verify_otp", {"gp_id": self.gp_id, "otp": "0000"})
        self.assertEqual(r.status_code, 200)

    def test_csrf_cookie_is_issued_to_the_page(self):
        c = self.client("admin")
        r = c.get("/api/stats")
        self.assertIn("XSRF-TOKEN=test-csrf-token", r.headers.get("Set-Cookie", ""))

    def test_exceptional_actions_need_a_reason(self):
        c = self.client("admin")
        r = self.post(c, "/api/gate/approve_all_matched")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error_code"], "reason_required")
        r = self.post(c, "/api/gate/approve_all_matched", {"reason": "Morning batch, all OTPs checked by phone"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access.sensitive", self.audit_actions())

    def test_copilot_actions_need_the_underlying_permission(self):
        c = self.client("gateviewer")
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("INSERT INTO role_permissions (role_id, permission_key) "
                         "SELECT id, 'copilot.use' FROM roles WHERE name = 'Gate Viewer'")
        conn.close()
        r = self.post(c, "/api/copilot/action", {"action": "manual_admit", "params": {"plate": "KA01ZZ9999"}})
        self.assertEqual(r.status_code, 403)
        r = self.post(c, "/api/copilot/action", {"action": "admit_dock", "params": {"id": self.glass_gp_id}})
        self.assertEqual(r.status_code, 403)
        admin = self.client("admin")
        r = self.post(admin, "/api/copilot/action", {"action": "manual_admit", "params": {"plate": "KA01ZZ9999"}})
        self.assertEqual(r.status_code, 400, "manual admission needs a reason")


class TestStreamsOtpErrors(Phase2Base):
    def test_video_feed_needs_a_session(self):
        r = self.app_module.app.test_client().get("/video_feed/CAM-001")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_otp_never_appears_in_api_responses(self):
        c = self.client("admin")
        body = c.get("/api/gate_passes").get_data(as_text=True)
        self.assertNotIn('"otp"', body)
        self.assertIn('"otp_verified"', body)
        self.assertNotIn('"otp"', c.get(f"/api/gate_passes/{self.gp_id}").get_data(as_text=True))
        r = c.get(f"/api/gate_passes/{self.gp_id}/otp")
        self.assertEqual(r.get_json()["otp"], "4321")
        self.assertIn("gate.otp_viewed", self.audit_actions())

    def test_new_gate_pass_otp_is_random_and_hidden(self):
        c = self.client("admin")
        r = self.post(c, "/api/gate_passes", {"plate": "TN99XX1234", "driver_phone": "9000000000",
                                              "driver_name": "Phase2 Driver"})
        data = r.get_json()
        self.assertNotIn('"otp"', json.dumps(data))
        gp_id = data["gate_pass"]["id"]
        otp = sqlite3.connect(self.db_path).execute("SELECT otp FROM gate_passes WHERE id = ?", (gp_id,)).fetchone()[0]
        self.assertTrue(otp and otp.isdigit() and len(otp) == 4 and otp != "1234")

    def test_server_errors_hide_exception_text(self):
        app = self.app_module.app
        with app.test_request_context("/api/anything"):
            from flask import jsonify
            resp = jsonify({"success": False, "error": "sqlite3.OperationalError: no such table: secrets"})
            resp.status_code = 500
            out = self.app_module.rbac_after_request(resp)
            text = out.get_data(as_text=True)
        self.assertNotIn("sqlite3", text)
        self.assertIn("reference", text)

    def test_unknown_api_route_is_json_404(self):
        c = self.client("admin")
        r = c.get("/api/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
