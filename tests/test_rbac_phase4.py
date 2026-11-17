"""
RBAC Phase 4: users, invitations, passwords and companies.

Plan acceptance: an invite works once and expires; a reset link works once; deactivating
a user ends their session on the next request; soft delete only (H24). Plus: company
isolation of every admin action, no self-changes, last-admin protection, uniform
forgot-password answers, and Platform-Admin-only company management.
Runs on a private copy of the live database; email is not configured in tests, so links
come back in the response exactly as an admin would see them.
"""
import os
import re
import sqlite3
import unittest

from tests import session_for
from tests.test_rbac_phase3a import Phase3ABase

PW = "Strong-Pass-2026!"


class Phase4Base(Phase3ABase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for k in ("SMTP_USER", "SMTP_PASSWORD"):
            os.environ.pop(k, None)
        import auth_service
        import iam_service
        cls.auth, cls.iam = auth_service, iam_service

    def overview(self, user, company_id=None):
        q = f"?company_id={company_id}" if company_id else ""
        return self.get(self.client(user), "/api/iam/overview" + q)

    def role_id(self, code):
        return self.sql("SELECT id FROM roles WHERE builtin_code = ?", (code,))[0][0]

    def invite(self, by, email, role="user", warehouse_id=None, company_id=None):
        body = {"email": email, "role_id": self.role_id(role), "warehouse_id": warehouse_id}
        if company_id:
            body["company_id"] = company_id
        return self.send(self.client(by), "POST", "/api/iam/invitations", body)

    @staticmethod
    def token_from(link):
        return re.search(r"token=([^&]+)", link).group(1)

    def anon(self):
        return self.app_module.app.test_client()

    def accept(self, token, username, password=PW):
        return self.anon().post("/api/auth/accept_invite", json={
            "token": token, "username": username, "password": password, "confirm_password": password})

    def make_user(self, username, email, by="david", role="user", warehouse_id=None):
        r = self.invite(by, email, role, warehouse_id)
        self.assertTrue(r.get_json()["success"], r.get_json())
        a = self.accept(self.token_from(r.get_json()["invite_link"]), username)
        self.assertTrue(a.get_json()["success"], a.get_json())
        return self.sql("SELECT id FROM users WHERE username = ?", (username,))[0][0]

    def user_client(self, username):
        c = self.app_module.app.test_client()
        with c.session_transaction() as s:
            s["user"] = session_for(username, self.db_path)
            s["csrf"] = "t"
        c.wh = None
        return c


class TestInvitations(Phase4Base):
    def test_invite_works_once_and_creates_the_right_access(self):
        wid = self.glass_wh[0]
        r = self.invite("david", "p4.one@example.com", "user", wid)
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertFalse(data["email_sent"])
        token = self.token_from(data["invite_link"])
        # stored only as a hash
        self.assertFalse(self.sql("SELECT 1 FROM invitations WHERE token_hash = ?", (token,)))
        info = self.anon().get(f"/api/auth/invite_info?token={token}").get_json()
        self.assertEqual(info["invitation"]["company_name"], "glass and brass")
        self.assertEqual(self.accept(token, "p4one").status_code, 200)
        self.assertEqual(self.accept(token, "p4one-again").status_code, 400)          # works once
        uid = self.sql("SELECT id FROM users WHERE username = 'p4one'")[0][0]
        self.assertEqual(self.sql("SELECT company_id, warehouse_id, status FROM user_warehouse_access WHERE user_id = ?", (uid,)),
                         [(self.glass_wh[1], wid, "Active")])
        status, user = self.auth.authenticate("p4one", PW)
        self.assertEqual(status, "ok")
        self.assertTrue(self.sql("SELECT 1 FROM audit_logs WHERE action = 'iam.invitation.accepted' AND resource_id = ?", (str(uid),)))

    def test_expired_and_revoked_invites_fail(self):
        t1 = self.token_from(self.invite("david", "p4.exp@example.com").get_json()["invite_link"])
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("UPDATE invitations SET expires_at = '2000-01-01 00:00:00' WHERE email = 'p4.exp@example.com'")
        conn.close()
        self.assertEqual(self.accept(t1, "p4exp").status_code, 400)
        r = self.invite("david", "p4.rev@example.com").get_json()
        t2 = self.token_from(r["invite_link"])
        self.assertTrue(self.send(self.client("david"), "POST", f"/api/iam/invitations/{r['id']}/revoke").get_json()["success"])
        self.assertEqual(self.accept(t2, "p4rev").status_code, 400)

    def test_no_escalation_through_invitations(self):
        self.assertEqual(self.invite("david", "p4.pa@example.com", "platform_admin").status_code, 403)
        self.assertEqual(self.invite("david", "p4.ca@example.com", "company_admin", self.glass_wh[0]).status_code, 400)
        self.assertEqual(self.invite("david", "p4.x@example.com", "user", self.leak_wh).status_code, 400)
        self.assertEqual(self.invite("david", "p4.y@example.com", "user", None, self.leak_company).status_code, 404)

    def test_weak_password_and_taken_username_refused(self):
        token = self.token_from(self.invite("david", "p4.weak@example.com").get_json()["invite_link"])
        self.assertEqual(self.accept(token, "p4weak", "short").status_code, 400)
        self.assertEqual(self.accept(token, "david").status_code, 409)
        self.assertEqual(self.accept(token, "p4weak").status_code, 200)


class TestUsersAndAccess(Phase4Base):
    def test_company_admins_see_only_their_own_people(self):
        david = {u["username"] for u in self.overview("david").get_json()["users"]}
        leak = {u["username"] for u in self.overview("leakadmin").get_json()["users"]}
        self.assertIn("david", david)
        self.assertNotIn("leakadmin", david)
        self.assertEqual(leak, {"leakadmin"})
        self.assertEqual(self.overview("leakadmin", self.glass_wh[1]).status_code, 404)
        self.assertEqual(self.overview("admin", self.glass_wh[1]).status_code, 200)

    def test_plain_users_are_refused_in_every_mode(self):
        self.make_user("p4plain", "p4.plain@example.com")
        c = self.user_client("p4plain")
        self.assertEqual(self.get(c, "/api/iam/overview").status_code, 403)
        r = self.send(c, "POST", "/api/iam/invitations", {"email": "z@example.com", "role_id": self.role_id("user")})
        self.assertEqual(r.status_code, 403)

    def test_deactivation_needs_a_reason_and_ends_the_session(self):
        uid = self.make_user("p4gone", "p4.gone@example.com")
        victim = self.user_client("p4gone")
        self.assertEqual(self.get(victim, "/api/skus").status_code, 200)
        d = self.client("david")
        self.assertEqual(self.send(d, "POST", f"/api/iam/users/{uid}/deactivate", {}).status_code, 400)
        self.assertTrue(self.send(d, "POST", f"/api/iam/users/{uid}/deactivate", {"reason": "left"}).get_json()["success"])
        self.assertEqual(self.get(victim, "/api/skus").status_code, 401)            # next request
        self.assertEqual(self.auth.authenticate("p4gone", PW)[0], "invalid")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE id = ?", (uid,))[0][0], 1)  # soft delete
        self.assertTrue(self.send(d, "POST", f"/api/iam/users/{uid}/activate", {}).get_json()["success"])
        self.assertEqual(self.auth.authenticate("p4gone", PW)[0], "ok")

    def test_assignments_grant_and_revoke(self):
        uid = self.make_user("p4multi", "p4.multi@example.com", warehouse_id=self.glass_wh[0])
        d = self.client("david")
        other = self.sql("SELECT id FROM warehouses WHERE company_id = ? AND id != ? LIMIT 1",
                         (self.glass_wh[1], self.glass_wh[0]))
        target_wh = other[0][0] if other else None
        r = self.send(d, "POST", f"/api/iam/users/{uid}/assignments", {"role_id": self.role_id("user"), "warehouse_id": target_wh})
        self.assertTrue(r.get_json()["success"], r.get_json())
        aid = r.get_json()["id"]
        self.assertEqual(self.send(d, "POST", f"/api/iam/users/{uid}/assignments",
                                   {"role_id": self.role_id("user"), "warehouse_id": target_wh}).status_code, 409)
        self.assertEqual(self.send(d, "POST", f"/api/iam/users/{uid}/assignments",
                                   {"role_id": self.role_id("user"), "warehouse_id": self.leak_wh}).status_code, 400)
        self.assertTrue(self.send(d, "POST", f"/api/iam/assignments/{aid}/revoke", {}).get_json()["success"])
        self.assertEqual(self.sql("SELECT status FROM user_warehouse_access WHERE id = ?", (aid,)), [("Revoked",)])
        # a second Company Admin makes the first one removable
        self.assertTrue(self.send(d, "POST", f"/api/iam/users/{uid}/assignments",
                                  {"role_id": self.role_id("company_admin")}).get_json()["success"])


class TestLastAdmin(Phase4Base):
    def test_no_self_changes_and_last_admin_protected(self):
        david_id = self.sql("SELECT id FROM users WHERE username = 'david'")[0][0]
        r = self.send(self.client("david"), "POST", f"/api/iam/users/{david_id}/deactivate", {"reason": "x"})
        self.assertEqual(r.status_code, 403)
        r = self.send(self.client("admin"), "POST", f"/api/iam/users/{david_id}/deactivate",
                      {"reason": "x", "company_id": self.glass_wh[1]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], "last_company_admin")
        admin_id = self.sql("SELECT id FROM users WHERE username = 'admin'")[0][0]
        r = self.send(self.client("david"), "POST", f"/api/iam/users/{admin_id}/deactivate", {"reason": "x"})
        self.assertEqual(r.status_code, 404)


class TestPasswords(Phase4Base):
    def test_forgot_password_is_uniform_and_reset_link_works_once(self):
        uid = self.make_user("p4reset", "p4.reset@example.com")
        a = self.anon().post("/api/auth/forgot_password", json={"identifier": "p4reset"}).get_json()
        b = self.anon().post("/api/auth/forgot_password", json={"identifier": "nobody-here"}).get_json()
        self.assertEqual(a, b)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = ?", (uid,))[0][0], 1)
        # an admin-issued link (shown once, as with no email server) works exactly once
        out = self.send(self.client("david"), "POST", f"/api/iam/users/{uid}/reset_link", {}).get_json()
        token = self.token_from(out["reset_link"])
        old_session = self.user_client("p4reset")
        new_pw = "Another-Strong-2026"
        self.assertTrue(self.anon().post("/api/auth/reset_password", json={"token": token, "password": new_pw}).get_json()["success"])
        self.assertEqual(self.anon().post("/api/auth/reset_password", json={"token": token, "password": new_pw + "x"}).status_code, 400)
        self.assertEqual(self.auth.authenticate("p4reset", PW)[0], "invalid")
        self.assertEqual(self.auth.authenticate("p4reset", new_pw)[0], "ok")
        self.assertEqual(self.get(old_session, "/api/skus").status_code, 401)

    def test_change_password_keeps_this_session_and_ends_others(self):
        self.make_user("p4change", "p4.change@example.com")
        here, elsewhere = self.user_client("p4change"), self.user_client("p4change")
        bad = self.send(here, "POST", "/api/auth/change_password", {"current_password": "wrong", "new_password": "Brand-New-Pass-1"})
        self.assertEqual(bad.status_code, 400)
        ok = self.send(here, "POST", "/api/auth/change_password", {"current_password": PW, "new_password": "Brand-New-Pass-1"})
        self.assertTrue(ok.get_json()["success"], ok.get_json())
        self.assertEqual(self.get(here, "/api/skus").status_code, 200)
        self.assertEqual(self.get(elsewhere, "/api/skus").status_code, 401)

    def test_public_pages_open_without_signing_in(self):
        for path in ("/forgot-password", "/accept-invite?token=x", "/reset-password?token=x"):
            self.assertEqual(self.anon().get(path).status_code, 200, path)
        self.assertIn("/forgot-password", self.anon().get("/login").get_data(as_text=True))


class TestCompanies(Phase4Base):
    def test_platform_admin_creates_and_suspends_companies(self):
        self.assertEqual(self.send(self.client("david"), "POST", "/api/platform/companies",
                                   {"name": "Nope Co", "owner_email": "n@example.com"}).status_code, 403)
        r = self.send(self.client("admin"), "POST", "/api/platform/companies",
                      {"name": "Phase Four Traders", "owner_email": "owner@p4traders.example", "city": "Madurai"})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        cid = data["company_id"]
        self.assertEqual(self.sql("SELECT COUNT(*) FROM warehouses WHERE company_id = ?", (cid,))[0][0], 1)
        token = self.token_from(data["invitation"]["invite_link"])
        self.assertEqual(self.accept(token, "p4owner").status_code, 200)
        self.assertEqual(self.auth.role_label(self.sql("SELECT id FROM users WHERE username = 'p4owner'")[0][0]), "Company Admin")
        owner = self.user_client("p4owner")
        self.assertEqual(self.get(owner, "/api/skus").status_code, 200)
        a = self.client("admin")
        self.assertEqual(self.send(a, "POST", f"/api/platform/companies/{cid}/suspend", {}).status_code, 400)
        self.assertTrue(self.send(a, "POST", f"/api/platform/companies/{cid}/suspend", {"reason": "test"}).get_json()["success"])
        self.assertEqual(self.get(owner, "/api/skus").status_code, 401)
        self.assertEqual(self.auth.authenticate("p4owner", PW)[0], "invalid")
        self.assertTrue(self.send(a, "POST", f"/api/platform/companies/{cid}/activate", {}).get_json()["success"])
        self.assertEqual(self.auth.authenticate("p4owner", PW)[0], "ok")
        owner_company = self.sql("SELECT id FROM companies WHERE is_platform_owner = 1")[0][0]
        self.assertEqual(self.send(a, "POST", f"/api/platform/companies/{owner_company}/suspend", {"reason": "x"}).status_code, 409)
        self.assertEqual(self.send(a, "POST", "/api/platform/companies",
                                   {"name": "glass and brass", "owner_email": "dup@example.com"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
