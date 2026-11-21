"""
RBAC Phase 6: frontend gating support on the server.

The browser part (every screen per role in headless Chrome, enforce mode) is
scripts/rbac_ui_pass.py; these tests cover what the page relies on:
  * the page and /api/auth/me tell the browser what the person may do
  * shared lookup reads accept any one of several permissions ('a|b')
  * the read-only "All locations" view refuses writes with a clear 403 (not a 500)
  * every permission named in the gating script exists in the catalogue
"""
import os
import re
import unittest

from tests.test_rbac_phase5 import Phase5Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAccessForThePage(Phase5Base):
    def test_page_and_me_describe_access(self):
        html = self.get(self.client("david"), "/").get_data(as_text=True)
        self.assertIn("window.WARLOG_ACCESS", html)
        self.assertIn("js/permissions.js", html)
        me = self.get(self.client("david"), "/api/auth/me").get_json()["access"]
        self.assertTrue(me["all"])
        self.assertTrue(me["company_wide"])
        admin = self.get(self.client("admin"), "/api/auth/me").get_json()["access"]
        self.assertTrue(admin["all"] and admin["is_platform_admin"])

        rid = self.sql("SELECT id FROM roles WHERE company_id = ? AND template_key = 'gate_security'",
                       (self.glass_wh[1],))[0][0]
        self.invite_with_role("david", "p6.gate@example.com", "p6gate", rid, self.glass_wh[0])
        acc = self.get(self.user_client("p6gate"), "/api/auth/me").get_json()["access"]
        self.assertFalse(acc["all"])
        self.assertFalse(acc["company_wide"])
        self.assertIn("gate.otp.verify", acc["permissions"])
        self.assertNotIn("users.view", acc["permissions"])


class TestSharedLookupReads(Phase5Base):
    def test_any_of_permissions_open_lookup_reads_in_enforce_mode(self):
        rid = self.make_role("david", "Inbound Only", ["inbound.view"])
        self.invite_with_role("david", "p6.in@example.com", "p6in", rid, self.glass_wh[0])
        nobody = self.make_role("david", "Reports Only", ["reports.view"])
        self.invite_with_role("david", "p6.rep@example.com", "p6rep", nobody, self.glass_wh[0])
        self.cfg.RBAC_MODE = "enforce"
        try:
            c = self.user_client("p6in")
            for path in ("/api/deliveries", "/api/gate_passes", "/api/bins", "/api/skus", "/api/staging/status"):
                self.assertEqual(self.get(c, path).status_code, 200, path)
            self.assertEqual(self.get(c, "/api/iam/overview").status_code, 403)
            r = self.get(self.user_client("p6rep"), "/api/deliveries")
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.get_json()["error_code"], "permission_denied")
        finally:
            self.cfg.RBAC_MODE = "audit"


class TestReadOnlyAllLocations(Phase5Base):
    def test_writes_in_all_locations_view_get_a_clear_403(self):
        c = self.client("david", "all")
        self.assertEqual(self.get(c, "/api/deliveries").status_code, 200)
        before = self.sql("SELECT COUNT(*) FROM expected_deliveries")
        r = self.send(c, "POST", "/api/deliveries", {"po_number": "PO-P6-RO", "expected_date": "2026-12-01"})
        self.assertEqual(r.status_code, 403, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["error_code"], "read_only_view")
        self.assertEqual(before, self.sql("SELECT COUNT(*) FROM expected_deliveries"))
        self.assertEqual(self.get(c, "/api/auth/me").get_json()["access"]["scope"], "company_all")


class TestGatingScript(unittest.TestCase):
    def test_every_permission_in_the_gating_script_exists(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "webapp"))
        import rbac_catalog
        js = open(os.path.join(ROOT, "webapp", "static", "js", "permissions.js"), encoding="utf-8").read()
        found = set()
        for literal in re.findall(r"'([a-z_]+\.[a-z_.]+(?:\|[a-z_]+\.[a-z_.]+)*)'", js):
            found.update(literal.split("|"))
        found = {k for k in found if not k.startswith(("window.", "e.", "el."))}
        self.assertGreater(len(found), 40)
        unknown = sorted(k for k in found if k not in rbac_catalog.PERMISSIONS_BY_KEY)
        self.assertEqual(unknown, [], "permissions.js names permissions that don't exist")


if __name__ == "__main__":
    unittest.main()
