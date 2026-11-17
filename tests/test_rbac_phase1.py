"""
RBAC Phase 1 exit tests: identity schema, password hashing, forced reset, lockout,
signup guard, last-admin protection and recovery.

Runs the real migration on a fresh copy of the live data. Existing plain-text passwords
are read from that copy BEFORE migration and kept in memory only to prove every
account still signs in; they are never printed or written anywhere.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, WEBAPP)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import rbac_snapshot  # noqa: E402


def _copy(src, dst):
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _is_pre_migration(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return "password_hash" not in [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    finally:
        conn.close()


def pre_migration_source():
    """The live DB while it is unmigrated; afterwards the automatic pre-migration backup
    (backups/pre_rbac_v1_*.db) that still holds the original data."""
    import glob
    live = os.path.join(WEBAPP, "skandha_wms.db")
    if _is_pre_migration(live):
        return live
    for path in sorted(glob.glob(os.path.join(ROOT, "backups", "pre_rbac_v1_*.db"))):
        if _is_pre_migration(path):
            return path
    return None


class Phase1Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import db
        import app as app_module
        import auth_service
        import rbac_migration
        import rbac_catalog
        cls.db, cls.app_module, cls.auth, cls.mig, cls.catalog = db, app_module, auth_service, rbac_migration, rbac_catalog
        cls._tmp = tempfile.mkdtemp(prefix="warlog_phase1_")
        cls.db_path = os.path.join(cls._tmp, "phase1.db")
        source = pre_migration_source()
        if source is None:
            raise unittest.SkipTest("no pre-migration database available (live DB migrated, no backup)")
        _copy(source, cls.db_path)
        conn = sqlite3.connect(cls.db_path)
        try:
            cls.plain = {u: p for u, p in conn.execute("SELECT username, password FROM users")}
        finally:
            conn.close()
        cls._saved = (db.DB_PATH, os.environ.get("WARLOG_DB_PATH"))
        db.DB_PATH = cls.db_path
        os.environ["WARLOG_DB_PATH"] = cls.db_path
        cls.first_run = rbac_migration.migrate(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_saved"):
            cls.db.DB_PATH, env = cls._saved
            if env is None:
                os.environ.pop("WARLOG_DB_PATH", None)
            else:
                os.environ["WARLOG_DB_PATH"] = env
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.sql("DELETE FROM login_attempts")

    def sql(self, query, params=(), one=False):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                cur = conn.execute(query, params)
                return cur.fetchone() if one else cur.fetchall()
        finally:
            conn.close()

    def login(self, username, password, client=None):
        c = client or self.app_module.app.test_client()
        r = c.post("/api/login", json={"username": username, "password": password})
        return c, r


class TestMigration(Phase1Base):
    def test_migration_applies_all_steps_and_second_run_changes_nothing(self):
        self.assertEqual(self.first_run["applied"], [name for name, _ in self.mig.STEPS])
        before = rbac_snapshot.table_fingerprints(self.db_path)
        again = self.mig.migrate(self.db_path)
        self.assertEqual(again["applied"], [])
        self.assertEqual(before, rbac_snapshot.table_fingerprints(self.db_path))

    def test_companies_warehouses_roles_and_catalogue(self):
        companies = {r[0]: r[1] for r in self.sql("SELECT name_key, is_platform_owner FROM companies")}
        expected = {self.mig.company_key(n) for (n,) in self.sql(
            "SELECT company_name FROM warehouses UNION SELECT company_name FROM users")}
        self.assertEqual(set(companies), expected)
        owner = self.sql("SELECT company_name FROM users WHERE LOWER(username)='admin'", one=True)[0]
        self.assertEqual([k for k, v in companies.items() if v], [self.mig.company_key(owner)])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM warehouses WHERE company_id IS NULL", one=True)[0], 0)
        self.assertEqual(sorted(r[0] for r in self.sql("SELECT builtin_code FROM roles WHERE is_builtin=1")),
                         ["company_admin", "platform_admin", "user"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM permissions WHERE retired=0", one=True)[0],
                         len(self.catalog.PERMISSION_CATALOG))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE is_platform_admin=1", one=True)[0], 1)

    def test_every_existing_user_keeps_access_and_admin_rights(self):
        for username in self.plain:
            uid = self.sql("SELECT id FROM users WHERE username=?", (username,), one=True)[0]
            n = self.sql("""SELECT COUNT(*) FROM user_warehouse_access a JOIN roles r ON r.id=a.role_id
                            WHERE a.user_id=? AND r.builtin_code='company_admin' AND a.status='Active'
                              AND a.warehouse_id IS NULL""", (uid,), one=True)[0]
            self.assertEqual(n, 1, f"{username} should be Company Admin of its company")

    def test_passwords_are_hashed_and_still_work(self):
        for username, plain in self.plain.items():
            stored, phash, must = self.sql(
                "SELECT password, password_hash, must_reset_password FROM users WHERE username=?", (username,), one=True)
            self.assertEqual(stored, "", "plain-text password must be blanked")
            self.assertTrue(phash and phash != plain)
            self.assertIsNotNone(self.db.get_user(username, plain), f"{username} must still sign in")
            self.assertEqual(bool(must), self.mig.must_reset_for(username, plain))
            _, r = self.login(username, plain)
            self.assertEqual(r.status_code, 200, f"{username}: {r.get_json()}")
            self.assertEqual(r.get_json()["must_reset_password"], bool(must))

    def test_plain_text_otps_are_purged(self):
        self.assertEqual(self.sql("SELECT COUNT(*) FROM email_otps", one=True)[0], 0)

    def test_no_default_admin_on_a_fresh_install(self):
        fresh = os.path.join(self._tmp, "fresh.db")
        saved = self.db.DB_PATH
        try:
            self.db.DB_PATH = fresh
            self.db.init_db()
        finally:
            self.db.DB_PATH = saved
        conn = sqlite3.connect(fresh)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        finally:
            conn.close()


class TestLoginSecurity(Phase1Base):
    def _admin_plain(self):
        return self.plain["admin"]

    def test_forced_reset_flow(self):
        self.sql("UPDATE users SET must_reset_password=1 WHERE username='admin'")
        other, r0 = self.login("admin", self._admin_plain())  # a second device
        c, r = self.login("admin", self._admin_plain())
        data = r.get_json()
        self.assertTrue(data["must_reset_password"])
        self.assertEqual(data["redirect"], "/account/reset-password")
        blocked = c.get("/api/stats")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.get_json()["error_code"], "password_reset_required")
        page = c.get("/")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/account/reset-password", page.headers["Location"])
        self.assertEqual(c.get("/account/reset-password").status_code, 200)
        weak = c.post("/api/auth/force_reset_password", json={"new_password": "short", "confirm_password": "short"})
        self.assertEqual(weak.status_code, 400)
        mismatch = c.post("/api/auth/force_reset_password",
                          json={"new_password": "Warlog-Reset-2026", "confirm_password": "Warlog-Reset-2027"})
        self.assertEqual(mismatch.status_code, 400)
        ok = c.post("/api/auth/force_reset_password",
                    json={"new_password": "Warlog-Reset-2026", "confirm_password": "Warlog-Reset-2026"})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(c.get("/api/stats").status_code, 200)
        self.assertEqual(other.get("/api/stats").status_code, 401, "other sessions must be signed out")
        self.assertIsNone(self.db.get_user("admin", self._admin_plain()))
        self.assertEqual(self.login("admin", "Warlog-Reset-2026")[1].status_code, 200)
        actions = [r[0] for r in self.sql("SELECT action FROM audit_logs WHERE actor_username='admin'")]
        self.assertIn("auth.password_reset_forced", actions)
        # put the original password back for the other tests
        self.auth.set_password(self.sql("SELECT id FROM users WHERE username='admin'", one=True)[0],
                               self._admin_plain())

    def test_lockout_after_five_failures_and_uniform_errors(self):
        msgs = set()
        for _ in range(5):
            _, r = self.login("admin", "definitely-wrong")
            self.assertEqual(r.status_code, 401)
            msgs.add(r.get_json()["message"])
        _, unknown = self.login("no-such-user-xyz", "whatever")
        msgs.add(unknown.get_json()["message"])
        self.assertEqual(msgs, {self.auth.GENERIC_LOGIN_ERROR}, "unknown user and wrong password look the same")
        _, r = self.login("admin", self._admin_plain())
        self.assertEqual(r.status_code, 429, "correct password is refused while locked")
        self.assertEqual(r.get_json()["error_code"], "too_many_attempts")
        self.assertIn("auth.locked", [a for (a,) in self.sql("SELECT action FROM audit_logs")])

    def test_unknown_usernames_lock_the_same_way(self):
        for _ in range(5):
            self.login("ghost-account", "nope")
        self.assertEqual(self.login("ghost-account", "nope")[1].status_code, 429)

    def test_ip_limit(self):
        for i in range(20):
            self.login(f"spray-{i}", "nope")
        self.assertEqual(self.login("admin", self._admin_plain())[1].status_code, 429)

    def test_legacy_and_tampered_sessions_are_rejected(self):
        c = self.app_module.app.test_client()
        with c.session_transaction() as s:
            s["user"] = {"username": "admin", "company_name": "x", "role": "Admin"}  # pre-Phase-1 cookie
        self.assertEqual(c.get("/api/stats").status_code, 401)
        uid, sv = self.sql("SELECT id, session_version FROM users WHERE username='admin'", one=True)
        with c.session_transaction() as s:
            s["user"] = {"username": "admin", "uid": uid, "sv": sv + 7}
        self.assertEqual(c.get("/api/stats").status_code, 401)

    def test_deactivated_user_is_signed_out(self):
        c, r = self.login("Puma", self.plain["Puma"])
        self.sql("UPDATE users SET must_reset_password=0 WHERE username='Puma'")
        self.assertEqual(r.status_code, 200)
        # Puma is its company's only admin: the database refuses to deactivate it
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("UPDATE users SET is_active=0 WHERE username='Puma'")
        # give Puma a second admin, then deactivation works and ends the session
        self.sql("INSERT INTO users (username, password, company_name, role) VALUES ('puma2', '', 'Puma', 'Admin')")
        uid2 = self.sql("SELECT id FROM users WHERE username='puma2'", one=True)[0]
        cid = self.sql("SELECT id FROM companies WHERE name_key='puma'", one=True)[0]
        conn = sqlite3.connect(self.db_path)
        with conn:
            self.mig.assign_company_admin(conn, uid2, cid)
        conn.close()
        self.sql("UPDATE users SET is_active=0 WHERE username='Puma'")
        self.assertEqual(c.get("/api/stats").status_code, 401)
        self.assertEqual(self.login("Puma", self.plain["Puma"])[1].status_code, 401)
        self.sql("UPDATE users SET is_active=1 WHERE username='Puma'")

    def test_last_platform_admin_cannot_be_removed(self):
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.sql("UPDATE users SET is_platform_admin=0 WHERE username='admin'")
        self.assertIn("last_platform_admin", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("DELETE FROM users WHERE username='admin'")

    def test_last_company_admin_assignment_cannot_be_revoked(self):
        uid = self.sql("SELECT id FROM users WHERE username='Mangalesh'", one=True)[0]
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.sql("UPDATE user_warehouse_access SET status='Revoked' WHERE user_id=?", (uid,))
        self.assertIn("last_company_admin", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("DELETE FROM user_warehouse_access WHERE user_id=?", (uid,))

    def test_session_lifetime_is_12_hours(self):
        self.assertEqual(self.app_module.app.permanent_session_lifetime.total_seconds(), 12 * 3600)


class TestSignup(Phase1Base):
    def test_unverified_register_route_is_gone(self):
        c, _ = self.login("Mangalesh", self.plain["Mangalesh"])
        self.sql("UPDATE users SET must_reset_password=0 WHERE username='Mangalesh'")
        self.assertEqual(c.post("/api/register", json={"username": "x", "password": "y"}).status_code, 404)
        anon = self.app_module.app.test_client().post("/api/register", json={"username": "x", "password": "y"})
        self.assertIn(anon.status_code, (401, 404))
        self.assertIsNone(self.db.get_user_id_by_username("x"))

    def test_existing_company_needs_an_invite(self):
        self.db.store_email_otp("intruder@example.com", "111222")
        r = self.app_module.app.test_client().post("/api/auth/verify_otp_and_register", json={
            "email": "intruder@example.com", "otp_code": "111222", "username": "intruder",
            "password": "Intruder-Pass-2026", "company_name": "  LION "})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], "company_exists_invite_required")
        self.assertIsNone(self.db.get_user_id_by_username("intruder"))
        r = self.app_module.app.test_client().post("/api/auth/send_otp", json={
            "email": "intruder2@example.com", "username": "intruder2", "company_name": "Puma"})
        self.assertEqual(r.status_code, 409)

    def test_blank_company_and_weak_password_are_refused(self):
        self.db.store_email_otp("blank@example.com", "333444")
        c = self.app_module.app.test_client()
        r = c.post("/api/auth/verify_otp_and_register", json={
            "email": "blank@example.com", "otp_code": "333444", "username": "blankco",
            "password": "Blank-Company-2026", "company_name": ""})
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/auth/verify_otp_and_register", json={
            "email": "blank@example.com", "otp_code": "333444", "username": "blankco",
            "password": "short", "company_name": "Blank Co"})
        self.assertEqual(r.status_code, 400)

    def test_new_company_signup_creates_company_admin(self):
        self.db.store_email_otp("founder@example.com", "555666")
        c = self.app_module.app.test_client()
        r = c.post("/api/auth/verify_otp_and_register", json={
            "email": "founder@example.com", "otp_code": "555666", "username": "founder",
            "password": "Founder-Pass-2026", "company_name": "Brand New Timberworks",
            "city": "Hubli", "environment_blueprint": "wood"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(c.get("/api/stats").status_code, 200, "new user is signed in")
        uid = self.db.get_user_id_by_username("founder")
        row = self.sql("""SELECT c.name FROM user_warehouse_access a JOIN roles r ON r.id=a.role_id
                          JOIN companies c ON c.id=a.company_id
                          WHERE a.user_id=? AND r.builtin_code='company_admin'""", (uid,), one=True)
        self.assertEqual(row[0], "Brand New Timberworks")
        wh = self.sql("SELECT company_id FROM warehouses WHERE company_name='Brand New Timberworks'", one=True)
        self.assertIsNotNone(wh[0])

    def test_otps_are_hashed_single_use_and_limited(self):
        self.db.store_email_otp("otp@example.com", "987654")
        stored = self.sql("SELECT otp_code FROM email_otps WHERE email='otp@example.com' AND verified=0", one=True)[0]
        self.assertTrue(stored.startswith("h$"))
        self.assertNotIn("987654", stored)
        for _ in range(5):
            self.assertFalse(self.db.verify_email_otp("otp@example.com", "000000")[0])
        self.assertFalse(self.db.verify_email_otp("otp@example.com", "987654")[0], "voided after 5 wrong tries")
        c = self.app_module.app.test_client()
        codes = [c.post("/api/auth/send_otp", json={"email": "limit@example.com"}).status_code for _ in range(4)]
        self.assertEqual(codes[-1], 429)


class TestRecovery(Phase1Base):
    def test_console_recovery_issues_a_temporary_password(self):
        env = dict(os.environ, WARLOG_DB_PATH=self.db_path, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "rbac_recover.py"),
                               "reset", "--username", "testuser", "--temporary"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        temp = proc.stdout.split("Temporary password for testuser: ", 1)[1].split()[0]
        _, r = self.login("testuser", temp)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["must_reset_password"])
        self.assertIn("auth.recovery", [a for (a,) in self.sql("SELECT action FROM audit_logs")])


class TestFrontendGuards(unittest.TestCase):
    def test_login_page_never_redirects_off_site(self):
        with open(os.path.join(WEBAPP, "templates", "login.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("rawNext.startsWith('/') && !rawNext.startsWith('//')", html)


if __name__ == "__main__":
    unittest.main()
