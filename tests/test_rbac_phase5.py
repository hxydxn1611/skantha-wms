"""
RBAC Phase 5: role builder.

Plan acceptance: a custom role grants exactly what is ticked; revoking a permission takes
effect on the next request; nobody can grant what they don't hold or change their own
access (H12); built-in roles are read-only; platform permissions are never grantable here.
Runs on a private copy of the live database.
"""
import unittest

from tests.test_rbac_phase4 import Phase4Base

GATE_KEYS = ["gate.dashboard.view", "gate.pass.view"]
HR_KEYS = ["users.view", "users.invite", "assignments.manage", "roles.view", "roles.manage"]


class Phase5Base(Phase4Base):
    def make_role(self, by, name, keys, expect=200):
        r = self.send(self.client(by), "POST", "/api/iam/roles", {"name": name, "permissions": keys})
        self.assertEqual(r.status_code, expect, r.get_json())
        return r.get_json().get("id")

    def me_perms(self, client):
        return set(self.get(client, "/api/auth/me").get_json()["permissions"])

    def invite_with_role(self, by, email, username, role_id, warehouse_id=None):
        r = self.send(self.client(by), "POST", "/api/iam/invitations",
                      {"email": email, "role_id": role_id, "warehouse_id": warehouse_id})
        self.assertTrue(r.get_json()["success"], r.get_json())
        a = self.accept(self.token_from(r.get_json()["invite_link"]), username)
        self.assertTrue(a.get_json()["success"], a.get_json())
        return self.sql("SELECT id FROM users WHERE username = ?", (username,))[0][0]


class TestRoleGrants(Phase5Base):
    def test_custom_role_grants_exactly_what_is_ticked_and_changes_apply_next_request(self):
        rid = self.make_role("david", "Gate Operator", GATE_KEYS)
        self.invite_with_role("david", "p5.gate@example.com", "p5gate", rid, self.glass_wh[0])
        c = self.user_client("p5gate")
        self.assertEqual(self.me_perms(c), set(GATE_KEYS))
        self.assertEqual(self.auth.role_label(self.sql("SELECT id FROM users WHERE username='p5gate'")[0][0]), "Gate Operator")

        # preview says who is affected and what changes, and writes nothing
        pv = self.send(self.client("david"), "POST", f"/api/iam/roles/{rid}/preview",
                       {"permissions": ["gate.pass.view"]}).get_json()
        self.assertEqual([u["username"] for u in pv["users"]], ["p5gate"])
        self.assertEqual(len(pv["removed"]), 1)
        self.assertEqual(self.me_perms(c), set(GATE_KEYS))

        r = self.send(self.client("david"), "PUT", f"/api/iam/roles/{rid}", {"permissions": ["gate.pass.view"]})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.me_perms(c), {"gate.pass.view"})                 # next request

        d = self.client("david")
        self.assertEqual(self.send(d, "POST", f"/api/iam/roles/{rid}/deactivate", {}).status_code, 400)
        self.assertTrue(self.send(d, "POST", f"/api/iam/roles/{rid}/deactivate", {"reason": "test"}).get_json()["success"])
        self.assertEqual(self.me_perms(c), set())
        self.assertTrue(self.send(d, "POST", f"/api/iam/roles/{rid}/activate", {}).get_json()["success"])
        self.assertEqual(self.me_perms(c), {"gate.pass.view"})
        self.assertTrue(self.sql("SELECT 1 FROM audit_logs WHERE action = 'iam.role.updated' AND resource_id = ?", (str(rid),)))

    def test_enforce_mode_follows_the_role(self):
        rid = self.make_role("david", "Gate Viewer", GATE_KEYS)
        self.invite_with_role("david", "p5.view@example.com", "p5view", rid, self.glass_wh[0])
        c = self.user_client("p5view")
        self.cfg.RBAC_MODE = "enforce"
        try:
            self.assertEqual(self.get(c, "/api/gate_passes").status_code, 200)
            self.assertEqual(self.get(c, "/api/iam/overview").status_code, 403)
            r = self.send(c, "POST", "/api/skus", {"sku_id": "P5-NOPE", "name": "x"})
            self.assertEqual(r.status_code, 403)
        finally:
            self.cfg.RBAC_MODE = "audit"


class TestRoleRules(Phase5Base):
    def test_validation_builtins_and_platform_keys(self):
        self.make_role("david", "Company Admin", GATE_KEYS, expect=409)
        self.make_role("david", "Stock Clerk", ["platform.companies.manage"], expect=400)
        self.make_role("david", "Stock Clerk", ["no.such.permission"], expect=400)
        self.make_role("david", "Stock Clerk", [], expect=400)
        self.make_role("david", "Stock Clerk", GATE_KEYS)
        self.make_role("david", "stock clerk", GATE_KEYS, expect=409)
        ca = self.role_id("company_admin")
        r = self.send(self.client("david"), "PUT", f"/api/iam/roles/{ca}", {"permissions": GATE_KEYS})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error_code"], "builtin_read_only")

    def test_roles_are_per_company(self):
        rid = self.make_role("david", "Glass Checker", GATE_KEYS)
        names = [r["name"] for r in self.get(self.client("leakadmin"), "/api/iam/roles").get_json()["roles"]]
        self.assertNotIn("Glass Checker", names)
        self.assertEqual(self.send(self.client("leakadmin"), "PUT", f"/api/iam/roles/{rid}",
                                   {"permissions": GATE_KEYS}).status_code, 404)
        # and another company's role can't be handed out
        r = self.send(self.client("leakadmin"), "POST", "/api/iam/invitations",
                      {"email": "p5.cross@example.com", "role_id": rid})
        self.assertEqual(r.status_code, 400)


class TestNoEscalation(Phase5Base):
    def test_nobody_grants_what_they_dont_hold(self):
        hr = self.make_role("david", "HR", HR_KEYS)
        gate = self.make_role("david", "Gate Staff", GATE_KEYS)
        self.invite_with_role("david", "p5.hr@example.com", "p5hr", hr)
        c = self.user_client("p5hr")

        # can't invite a Company Admin, nor hand out a role with permissions HR lacks
        r = self.send(c, "POST", "/api/iam/invitations", {"email": "p5.boss@example.com",
                                                           "role_id": self.role_id("company_admin")})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "escalation_blocked"))
        r = self.send(c, "POST", "/api/iam/invitations", {"email": "p5.gs@example.com", "role_id": gate})
        self.assertEqual(r.status_code, 403)
        # can't build a role with permissions HR lacks; can with ones it holds
        self.assertEqual(self.send(c, "POST", "/api/iam/roles", {"name": "Sneaky", "permissions": GATE_KEYS}).status_code, 403)
        self.assertEqual(self.send(c, "POST", "/api/iam/roles", {"name": "Junior HR", "permissions": ["users.view"]}).status_code, 200)
        # can't change a role it holds itself (that would change its own access)
        r = self.send(c, "PUT", f"/api/iam/roles/{hr}", {"permissions": HR_KEYS + GATE_KEYS})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "self_change_forbidden"))
        # the catalogue marks what it may grant
        cat = self.get(c, "/api/iam/roles").get_json()["catalog"]
        grantable = {p["key"] for g in cat for p in g["permissions"] if p["grantable"]}
        self.assertEqual(grantable, set(HR_KEYS))
        self.assertFalse(any(p["key"].startswith("platform.") for g in cat for p in g["permissions"]))

    def test_company_admin_may_remove_but_platform_keys_never_appear(self):
        rid = self.make_role("david", "Temp Role", GATE_KEYS + ["users.view"])
        r = self.send(self.client("david"), "PUT", f"/api/iam/roles/{rid}", {"permissions": ["users.view"]})
        self.assertTrue(r.get_json()["success"])
        cat = self.get(self.client("admin"), "/api/iam/roles").get_json()["catalog"]
        self.assertFalse(any(p["key"].startswith("platform.") for g in cat for p in g["permissions"]))


if __name__ == "__main__":
    unittest.main()
