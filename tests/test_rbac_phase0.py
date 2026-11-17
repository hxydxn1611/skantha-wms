"""
RBAC Phase 0 exit tests: nothing that already exists can be wiped or taken over.

Every test runs against its own private copy of the database (never the live one)
and a private SKU-image folder, so generated thumbnails never land in webapp/static.
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from tests import copy_live_db, prepare_test_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, WEBAPP)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import rbac_snapshot  # noqa: E402

ADMIN = {"username": "admin", "company_name": "Skantha Industrial Solutions",
         "assigned_warehouse_code": "WH-MAIN", "role": "Admin"}
# Columns that legitimately change on a warehouse switch or template apply.
VOLATILE = {"warehouses": ("is_active", "updated_at")}


def rows_by_table(db_path):
    """{table: set(row tuples)} using each table's current columns."""
    conn = sqlite3.connect(db_path)
    out = {}
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')
                    if r[1] not in VOLATILE.get(t, ())]
            col_sql = ", ".join(f'"{c}"' for c in cols)
            out[t] = (cols, set(conn.execute(f'SELECT rowid, {col_sql} FROM "{t}"').fetchall()))
    finally:
        conn.close()
    return out


class Phase0Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import db
        import industry_blueprint_service as ibs
        import app as app_module
        cls.db, cls.ibs, cls.app_module = db, ibs, app_module
        cls._tmp = tempfile.mkdtemp(prefix="warlog_phase0_")
        cls.db_path = copy_live_db(os.path.join(cls._tmp, "phase0.db"))
        cls._saved = (db.DB_PATH, os.environ.get("WARLOG_DB_PATH"), ibs.UPLOAD_DIR)
        db.DB_PATH = cls.db_path
        os.environ["WARLOG_DB_PATH"] = cls.db_path
        ibs.UPLOAD_DIR = os.path.join(cls._tmp, "sku_images")
        os.makedirs(ibs.UPLOAD_DIR, exist_ok=True)
        db.init_db()
        prepare_test_db(cls.db_path)
        conn = sqlite3.connect(cls.db_path)
        with conn:  # fixture: these tests act as already-onboarded users
            conn.execute("UPDATE users SET must_reset_password = 0")
        conn.close()

    @classmethod
    def tearDownClass(cls):
        db_path, env_path, upload_dir = cls._saved
        cls.db.DB_PATH = db_path
        if env_path is None:
            os.environ.pop("WARLOG_DB_PATH", None)
        else:
            os.environ["WARLOG_DB_PATH"] = env_path
        cls.ibs.UPLOAD_DIR = upload_dir
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def client(self, user=None):
        """Test client with a valid Phase 1 session (uid + session_version) for `user`."""
        user = dict(user or ADMIN)
        conn = sqlite3.connect(self.db_path)
        try:
            uid, sv = conn.execute("SELECT id, session_version FROM users WHERE LOWER(username) = LOWER(?)",
                                   (user["username"],)).fetchone()
        finally:
            conn.close()
        user.update({"uid": uid, "sv": sv, "must_reset_password": False})
        c = self.app_module.app.test_client()
        with c.session_transaction() as s:
            s["user"] = user
        return c

    def fingerprint(self):
        return rbac_snapshot.table_fingerprints(self.db_path, ignore_columns=VOLATILE)

    def assert_only_added(self, before, after):
        """Every row that existed before still exists, unchanged."""
        for table, (cols, rows) in before.items():
            self.assertIn(table, after, f"table {table} disappeared")
            after_cols, after_rows = after[table]
            idx = [after_cols.index(c) for c in cols]
            projected = {(r[0],) + tuple(r[1 + i] for i in idx) for r in after_rows}
            missing = rows - projected
            self.assertFalse(missing, f"{table}: {len(missing)} existing row(s) changed or deleted")


class TestNoDestructiveTemplates(Phase0Base):
    def test_switching_warehouse_ten_times_changes_no_data(self):
        codes = [w["code"] for w in self.db.get_all_warehouses(company_name="all")]
        self.assertGreaterEqual(len(codes), 2)
        before = self.fingerprint()
        c = self.client()
        for i in range(10):
            r = c.post("/api/warehouses/switch", json={"code": codes[i % len(codes)]})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertTrue(r.get_json()["success"])
        self.assertEqual(before, self.fingerprint())

    def test_reapplying_the_glass_template_is_a_no_op(self):
        before = self.fingerprint()
        r = self.client().post("/api/industry_blueprints/apply",
                               json={"blueprint_key": "glass", "warehouse_code": "WH-GLASS-COI"})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertEqual(data["skus_created"], 0)
        self.assertEqual(data["mode"], "add_only")
        self.assertEqual(before, self.fingerprint())

    def test_another_template_only_adds_and_marks_samples(self):
        before = rows_by_table(self.db_path)
        active_before = self.db.get_active_warehouse(company_name="all")
        res = self.ibs.apply_industry_blueprint("automotive", warehouse_code="WH-MAIN",
                                                custom_company_name="Skantha Industrial Solutions",
                                                db_path=self.db_path)
        self.assertTrue(res["success"], res)
        self.assertGreater(res["skus_created"], 0)
        after = rows_by_table(self.db_path)
        self.assert_only_added(before, after)
        self.assertEqual(active_before.get("code"), self.db.get_active_warehouse(company_name="all").get("code"))
        wh = self.db.get_warehouse_by_code("WH-MAIN")
        self.assertEqual(wh["company_name"], "Skantha Industrial Solutions")
        conn = sqlite3.connect(self.db_path)
        try:
            for po in [d["po_number"] for d in res["deliveries"]]:
                self.assertEqual(conn.execute("SELECT is_demo FROM expected_deliveries WHERE po_number=?",
                                              (po,)).fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventory WHERE is_demo=0").fetchone()[0],
                             len(before["inventory"][1]))
        finally:
            conn.close()
        # Re-applying the same template is now a no-op
        again = self.ibs.apply_industry_blueprint("automotive", warehouse_code="WH-MAIN",
                                                  custom_company_name="Skantha Industrial Solutions",
                                                  db_path=self.db_path)
        self.assertEqual(again["skus_created"], 0)
        self.assertEqual(after.keys(), rows_by_table(self.db_path).keys())

    def test_template_never_moves_a_warehouse_to_another_company(self):
        self.ibs.apply_industry_blueprint("glass", warehouse_code="WH-LION-COI",
                                          custom_company_name="Puma", db_path=self.db_path)
        self.assertEqual(self.db.get_warehouse_by_code("WH-LION-COI")["company_name"], "Lion")
        # A generated code that belongs to another company gets a suffix instead
        res = self.ibs.apply_industry_blueprint("glass", warehouse_code="",
                                                custom_company_name="Lion Imposter Ltd",
                                                db_path=self.db_path)
        self.assertTrue(res["success"], res)
        self.assertNotEqual(res["warehouse"]["code"], "WH-LION-COI")


class TestWarehouseOwnership(Phase0Base):
    def test_db_refuses_to_take_over_another_companys_code(self):
        with self.assertRaises(self.db.WarehouseOwnershipError):
            self.db.create_or_update_warehouse(code="WH-LION-COI", name="Hijack", company_name="Puma")
        self.assertEqual(self.db.get_warehouse_by_code("WH-LION-COI")["name"], "Lion goods")
        self.assertEqual(self.db.unique_warehouse_code("WH-LION-COI", "Puma"), "WH-LION-COI-2")
        self.assertEqual(self.db.unique_warehouse_code("WH-LION-COI", "  lion "), "WH-LION-COI")

    def test_create_route_returns_409_for_another_companys_code(self):
        puma = dict(ADMIN, username="Puma", company_name="Puma")
        r = self.client(puma).post("/api/warehouses/create",
                                   json={"name": "Hijack", "code": "WH-LION-COI", "company_name": "Puma"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.db.get_warehouse_by_code("WH-LION-COI")["company_name"], "Lion")

    def test_create_route_records_industry_without_touching_catalogue(self):
        before = self.fingerprint()
        r = self.client().post("/api/warehouses/create", json={
            "name": "Phase0 Pharma Hub", "city": "Mysuru", "environment_blueprint": "pharma",
            "company_name": "Skantha Industrial Solutions", "set_active": False})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertIn("Pharma", data["warehouse"]["industry"])
        after = self.fingerprint()
        for table in ("skus", "sku_images", "inventory", "pallets", "expected_deliveries",
                      "object_classes", "vision_zones", "vision_camera_object_classes"):
            self.assertEqual(before[table], after[table], table)

    def test_registration_creates_warehouse_without_touching_catalogue(self):
        before = self.fingerprint()
        self.assertTrue(self.db.store_email_otp("p0@example.com", "424242"))
        r = self.app_module.app.test_client().post("/api/auth/verify_otp_and_register", json={
            "username": "phase0_signup", "password": "Phase0-Test-Pass", "email": "p0@example.com",
            "otp_code": "424242", "company_name": "Li On", "city": "Coimbatore",
            "environment_blueprint": "wood"})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        # 'Li On' slugs to WH-LION-COI, which belongs to Lion: it must get its own code
        self.assertNotEqual(data["assigned_warehouse_code"], "WH-LION-COI")
        self.assertEqual(self.db.get_warehouse_by_code("WH-LION-COI")["company_name"], "Lion")
        new_wh = self.db.get_warehouse_by_code(data["assigned_warehouse_code"])
        self.assertEqual(new_wh["company_name"], "Li On")
        after = self.fingerprint()
        for table in ("skus", "sku_images", "inventory", "pallets", "expected_deliveries",
                      "object_classes", "vision_zones"):
            self.assertEqual(before[table], after[table], table)


class TestGateFixes(Phase0Base):
    def test_demo_delivery_never_matches_a_real_plate(self):
        from vision_runtime_service import find_matching_delivery_for_plate
        demo = {"po_number": "PO-DEMO", "plate": "KA01AB1234", "status": "Expected", "is_demo": 1}
        real = {"po_number": "PO-REAL", "plate": "KA01AB1234", "status": "Expected", "is_demo": 0}
        self.assertIsNone(find_matching_delivery_for_plate("KA01AB1234", [demo]))
        self.assertEqual(find_matching_delivery_for_plate("KA-01-AB-1234", [demo, real])["po_number"], "PO-REAL")

    def test_single_checkout_route(self):
        rules = [r for r in self.app_module.app.url_map.iter_rules() if r.rule == "/api/gate/checkout"]
        self.assertEqual(len(rules), 1)

    def test_gate02_plate_checkout_works_and_never_picks_another_vehicle(self):
        gp = self.db.create_gate_pass({"plate": "TN38ZZ0042", "status": "Sent to Dock",
                                       "dock": "Dock 1", "driver_name": "Phase0 Driver"})
        other_before = {p["id"]: p["status"] for p in self.db.get_all_gate_passes()}
        c = self.client()
        r = c.post("/api/gate/checkout", json={"gate_id": "GATE-02", "plate": "NO-SUCH-PLATE"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(other_before, {p["id"]: p["status"] for p in self.db.get_all_gate_passes()})
        r = c.post("/api/gate/checkout", json={"gate_id": "GATE-02", "plate": "TN38ZZ0042"})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertEqual(self.db.get_gate_pass(gp["id"])["status"], "Completed")

    def test_form_checkout_still_checks_the_plate(self):
        gp = self.db.create_gate_pass({"plate": "TN38ZZ0043", "status": "Sent to Dock",
                                       "dock": "Dock 1", "driver_name": "Phase0 Driver"})
        c = self.client()
        r = c.post("/api/gate/checkout", json={"gp_id": gp["id"], "plate": "WRONG1"})
        self.assertFalse(r.get_json()["success"])
        self.assertIn("mismatch", r.get_json()["message"])
        r = c.post("/api/gate/checkout", json={"gp_id": gp["id"], "plate": "TN 38 ZZ 0043"})
        self.assertTrue(r.get_json()["success"])
        self.assertEqual(self.db.get_gate_pass(gp["id"])["status"], "Departed")


class TestSecrets(unittest.TestCase):
    def test_no_credentials_in_python_sources(self):
        bad = [
            re.compile(r"environ\.get\(\s*['\"]SMTP_(USER|PASSWORD)['\"]\s*,\s*['\"][^'\"]+['\"]"),
            re.compile(r"\.login\(\s*['\"]"),
            re.compile(r"secret_key\s*=\s*['\"]"),
            re.compile(r"environ\.get\(\s*['\"](FLASK_)?SECRET_KEY['\"]\s*,\s*['\"][^'\"]+['\"]"),
        ]
        offenders = []
        for name in os.listdir(WEBAPP):
            if name.endswith(".py"):
                with open(os.path.join(WEBAPP, name), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                offenders += [f"{name}: {p.pattern}" for p in bad if p.search(text)]
        self.assertEqual(offenders, [])

    def test_app_refuses_to_start_without_secret_key(self):
        env = {k: v for k, v in os.environ.items() if k not in ("FLASK_SECRET_KEY", "SECRET_KEY")}
        env["WARLOG_SKIP_DOTENV"] = "1"
        proc = subprocess.run([sys.executable, "-c", "import app"], cwd=WEBAPP, env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FLASK_SECRET_KEY", proc.stderr)

    def test_rbac_mode_defaults_to_off(self):
        import rbac_config
        self.assertIn(rbac_config.get_rbac_mode(), rbac_config.RBAC_MODES)
        if not os.environ.get("RBAC_MODE"):
            self.assertEqual(rbac_config.get_rbac_mode(), "off")


if __name__ == "__main__":
    unittest.main()
