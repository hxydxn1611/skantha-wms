"""
RBAC Phase 3A exit tests: data isolation between companies and warehouses.

A second company ("Leak Test Co", warehouse WH-LEAKTEST, admin "leakadmin") is created on a
private copy of the live data, and its rows are written through the normal db functions
inside its scope, each carrying the marker LEAKMARK. Then every GET endpoint is called as
david (glass and brass): no response may contain LEAKMARK, and leakadmin's responses may
not contain glass and brass data. Single records, writes, read-only views, per-tab
warehouses, camera background work, per-warehouse settings and protected files are covered.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from tests import copy_live_db, prepare_test_db, session_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(ROOT, "webapp")
sys.path.insert(0, WEBAPP)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import rbac_snapshot  # noqa: E402

MARK = "LEAKMARK"
GLASS_SKU = "GLS-FLT-04MM"


class Phase3ABase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import db
        import app as app_module
        import rbac_config
        import rbac_scope
        import rbac_migration
        cls.db, cls.app_module, cls.cfg, cls.scope = db, app_module, rbac_config, rbac_scope
        cls._tmp = tempfile.mkdtemp(prefix="warlog_phase3a_")
        cls.db_path = prepare_test_db(copy_live_db(os.path.join(cls._tmp, "phase3a.db")))
        cls._saved = (db.DB_PATH, os.environ.get("WARLOG_DB_PATH"), rbac_config.RBAC_MODE)
        db.DB_PATH = cls.db_path
        os.environ["WARLOG_DB_PATH"] = cls.db_path
        rbac_config.RBAC_MODE = "audit"
        rbac_scope.reset_isolation_cache()

        conn = sqlite3.connect(cls.db_path)
        with conn:
            conn.execute("UPDATE users SET must_reset_password = 0")
            cid = rbac_migration.ensure_company(conn, "Leak Test Co")
            conn.execute("""INSERT INTO warehouses (code, name, city, operating_mode, industry, status, is_active, company_name, company_id)
                            VALUES ('WH-LEAKTEST', 'Leak Test Hub', 'Mysuru', 'DEDICATED', 'General', 'Active', 0, 'Leak Test Co', ?)""", (cid,))
            wid = conn.execute("SELECT id FROM warehouses WHERE code = 'WH-LEAKTEST'").fetchone()[0]
            conn.execute("""INSERT INTO users (username, password, password_hash, company_name, assigned_warehouse_code, role)
                            VALUES ('leakadmin', '', ?, 'Leak Test Co', 'WH-LEAKTEST', 'Admin')""",
                         (generate_password_hash("Leak-Admin-2026"),))
            uid = conn.execute("SELECT id FROM users WHERE username = 'leakadmin'").fetchone()[0]
            rbac_migration.assign_company_admin(conn, uid, cid)
            cls.glass_wh = conn.execute("SELECT id, company_id FROM warehouses WHERE code = 'WH-GLASS-COI'").fetchone()
            cls.main_wh = conn.execute("SELECT id FROM warehouses WHERE code = 'WH-MAIN'").fetchone()[0]
        conn.close()
        cls.leak_scope = rbac_scope.Scope.warehouse(cid, wid)
        cls.leak_company, cls.leak_wh = cid, wid

        with rbac_scope.using(cls.leak_scope):
            db.add_sku(f"{MARK}-SKU", f"{MARK} sku", "", "Test")
            db.create_delivery({"po_number": f"PO-{MARK}", "plate": f"{MARK}01", "vendor": f"{MARK} vendor",
                                "expected_date": "2026-11-20"})
            cls.leak_gp = db.create_gate_pass({"plate": f"{MARK}02", "driver_name": f"{MARK} driver"})["id"]
            db.add_bin(f"{MARK}-BIN", "General", 100.0, 1000.0)
            db.update_bin_stock(f"{MARK}-BIN", f"{MARK} vendor", 5, f"{MARK}-SKU")
            pallet, err = db.create_pallet(f"{MARK}-SKU", name=f"{MARK} pallet")
            cls.leak_pallet = pallet["pallet_id"] if pallet else None
            db.log_violation("TEST", f"{MARK} violation")
            db.create_object_class({"code": f"{MARK}_CLASS", "name": f"{MARK} class"})
            db.create_vision_zone({"zone_code": f"{MARK}-ZONE", "zone_name": f"{MARK} zone", "zone_type": "STORAGE"})
            db.create_or_update_camera({"camera_id": f"{MARK}-CAM", "camera_code": f"{MARK}-CAM", "name": f"{MARK} camera"})
            db.create_vehicle_log(cls.leak_gp, f"{MARK}02", f"{MARK} driver")
        # the in-memory camera registry must know the new camera too (runtime endpoints list it)
        from vision_runtime_service import get_vision_runtime_manager
        get_vision_runtime_manager().refresh_cameras()

    @classmethod
    def tearDownClass(cls):
        cls.db.DB_PATH, env, cls.cfg.RBAC_MODE = cls._saved
        if env is None:
            os.environ.pop("WARLOG_DB_PATH", None)
        else:
            os.environ["WARLOG_DB_PATH"] = env
        cls.scope.reset_isolation_cache()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.cfg.RBAC_MODE = "audit"

    def client(self, username, warehouse=None):
        c = self.app_module.app.test_client()
        with c.session_transaction() as s:
            s["user"] = session_for(username, self.db_path)
            s["csrf"] = "t"
        c.wh = warehouse
        return c

    def get(self, c, path):
        headers = {"X-Warehouse-Id": str(c.wh)} if c.wh is not None else {}
        return c.get(path, headers=headers)

    def send(self, c, method, path, body=None):
        headers = {"X-CSRF-Token": "t"}
        if c.wh is not None:
            headers["X-Warehouse-Id"] = str(c.wh)
        return c.open(path, method=method, json=body or {}, headers=headers)

    def sql(self, q, params=()):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(q, params).fetchall()
        finally:
            conn.close()

    def list_endpoints(self):
        paths = set(rbac_snapshot.API_ENDPOINTS)
        for rule in self.app_module.app.url_map.iter_rules():
            if "GET" in rule.methods and not rule.arguments and rule.rule.startswith("/api/") \
                    and not rule.rule.endswith((".mjpg", ".jpg", "/template")) and rule.rule != "/api/logout":
                paths.add(rule.rule)
        return sorted(paths)


class TestOwnershipAndStamping(Phase3ABase):
    def test_new_rows_are_stamped_with_their_scope(self):
        checks = {
            "skus": ("sku_id", f"{MARK}-SKU", "company"), "object_classes": ("code", f"{MARK}_CLASS", "company"),
            "expected_deliveries": ("po_number", f"PO-{MARK}", "warehouse"), "gate_passes": ("id", self.leak_gp, "warehouse"),
            "bins": ("bin_id", f"{MARK}-BIN", "warehouse"), "inventory": ("bin_id", f"{MARK}-BIN", "warehouse"),
            "violations_log": ("title", f"{MARK} violation", "warehouse"), "vision_zones": ("zone_code", f"{MARK}-ZONE", "warehouse"),
            "cameras": ("camera_id", f"{MARK}-CAM", "warehouse"), "vehicle_log": ("gp_id", self.leak_gp, "warehouse"),
            "pallets": ("pallet_id", self.leak_pallet, "warehouse"),
        }
        for table, (col, val, level) in checks.items():
            rows = self.sql(f"SELECT company_id{', warehouse_id' if level == 'warehouse' else ''} FROM {table} WHERE {col} = ?", (val,))
            self.assertTrue(rows, f"{table}: test row not created")
            expected = (self.leak_company, self.leak_wh) if level == "warehouse" else (self.leak_company,)
            self.assertEqual(rows[0], expected, table)

    def test_existing_data_got_its_approved_owner(self):
        wid, cid = self.glass_wh
        self.assertEqual(self.sql("SELECT DISTINCT company_id FROM skus WHERE sku_id LIKE 'GLS-%'"), [(cid,)])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM gate_passes WHERE legacy_test = 1 AND warehouse_id = ?",
                                  (self.main_wh,))[0][0] >= 1, True)


class TestNoLeaks(Phase3ABase):
    def test_company_admin_sees_no_other_company_data_on_any_list(self):
        c = self.client("david")
        leaks = []
        for path in self.list_endpoints():
            r = self.get(c, path)
            if MARK in r.get_data(as_text=True):
                leaks.append(path)
        self.assertEqual(leaks, [], "other company's data visible on these endpoints")

    def test_other_company_sees_none_of_glass_and_brass(self):
        c = self.client("leakadmin")
        leaks = [p for p in self.list_endpoints() if GLASS_SKU in self.get(c, p).get_data(as_text=True)]
        self.assertEqual(leaks, [])
        for path in ("/api/skus", "/api/deliveries", "/api/gate_passes", "/api/bins", "/api/cameras"):
            self.assertIn(MARK, self.get(c, path).get_data(as_text=True), f"own data missing on {path}")

    def test_single_records_of_another_company_are_404(self):
        c = self.client("david")
        for path in (f"/api/gate_passes/{self.leak_gp}", f"/api/deliveries/PO-{MARK}", f"/api/pallets/{self.leak_pallet}",
                     f"/api/bins/{MARK}-BIN/inventory", f"/api/vision/zones/{MARK}-ZONE", f"/video_feed/{MARK}-CAM",
                     f"/api/sku_master/{MARK}-SKU", f"/api/integration/gate_pass/{self.leak_gp}"):
            self.assertEqual(self.get(c, path).status_code, 404, path)

    def test_writes_cannot_reach_another_company(self):
        c = self.client("david")
        self.assertEqual(self.send(c, "POST", "/api/gate/verify_otp", {"gp_id": self.leak_gp, "otp": "1"}).status_code, 404)
        self.assertEqual(self.send(c, "PUT", f"/api/deliveries/PO-{MARK}", {"vendor": "hijacked"}).status_code, 404)
        self.assertEqual(self.send(c, "DELETE", f"/api/pallets/{self.leak_pallet}").status_code, 404)
        self.assertEqual(self.sql("SELECT vendor FROM expected_deliveries WHERE po_number = ?", (f"PO-{MARK}",)),
                         [(f"{MARK} vendor",)])
        # the database fence also holds when code forgets to check (david's own warehouse scope)
        wid, cid = self.glass_wh
        with self.scope.using(self.scope.Scope.warehouse(cid, wid)):
            conn = self.db.get_db()
            try:
                n = conn.execute("UPDATE skus SET name = 'x' WHERE sku_id = ?", (f"{MARK}-SKU",)).rowcount
                conn.commit()
                self.assertEqual(n, 0)
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("INSERT INTO skus (sku_id, name, company_id) VALUES ('X-1', 'x', ?)", (self.leak_company,))
            finally:
                conn.close()


class TestScopesAndTabs(Phase3ABase):
    def test_warehouse_lists_are_per_user(self):
        def codes(user):
            return sorted(w["code"] for w in self.get(self.client(user), "/api/warehouses").get_json()["warehouses"])
        def company_codes(company_id):
            return sorted(r[0] for r in self.sql("SELECT code FROM warehouses WHERE company_id = ?", (company_id,)))
        self.assertEqual(codes("david"), company_codes(self.glass_wh[1]))
        self.assertIn("WH-GLASS-COI", codes("david"))
        self.assertEqual(codes("leakadmin"), company_codes(self.leak_company))
        self.assertIn("WH-GLASS-COI", codes("admin"))
        self.assertIn("WH-LEAKTEST", codes("admin"))

    def test_tabs_work_in_different_warehouses(self):
        wid, _ = self.glass_wh
        glass_tab, main_tab = self.client("admin", wid), self.client("admin", self.main_wh)
        self.assertTrue(any(s["sku_id"] == GLASS_SKU for s in self.get(glass_tab, "/api/skus").get_json()))
        self.assertFalse(any(s["sku_id"] == GLASS_SKU for s in self.get(main_tab, "/api/skus").get_json()))
        self.assertEqual(self.get(main_tab, "/api/warehouses/active").get_json()["active_warehouse"]["code"], "WH-MAIN")
        self.assertEqual(self.get(glass_tab, "/api/warehouses/active").get_json()["active_warehouse"]["code"], "WH-GLASS-COI")

    def test_switch_is_per_session_and_global_flag_untouched(self):
        before = self.sql("SELECT code, is_active FROM warehouses ORDER BY id")
        a, b = self.client("admin"), self.client("admin")
        self.assertEqual(self.send(a, "POST", "/api/warehouses/switch", {"code": "WH-GLASS-COI"}).status_code, 200)
        self.assertEqual(self.get(a, "/api/warehouses/active").get_json()["active_warehouse"]["code"], "WH-GLASS-COI")
        self.assertNotEqual(self.get(b, "/api/warehouses/active").get_json()["active_warehouse"]["code"], "WH-GLASS-COI")
        self.assertEqual(before, self.sql("SELECT code, is_active FROM warehouses ORDER BY id"))
        self.assertEqual(self.send(self.client("david"), "POST", "/api/warehouses/switch", {"code": "WH-MAIN"}).status_code, 404)

    def test_header_for_a_foreign_warehouse_is_refused(self):
        r = self.get(self.client("david", self.main_wh), "/api/skus")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error_code"], "warehouse_scope_invalid")
        self.assertEqual(self.get(self.client("david", "*"), "/api/skus").status_code, 403)

    def test_all_warehouse_views_are_read_only(self):
        for user, wh in (("david", "all"), ("admin", "*")):
            c = self.client(user, wh)
            self.assertEqual(self.get(c, "/api/skus").status_code, 200)
            before = self.sql("SELECT COUNT(*) FROM expected_deliveries")
            r = self.send(c, "POST", "/api/deliveries", {"po_number": f"PO-RO-{user}", "expected_date": "2026-12-01"})
            self.assertGreaterEqual(r.status_code, 400, f"{user}/{wh} write must fail")
            self.assertEqual(before, self.sql("SELECT COUNT(*) FROM expected_deliveries"))

    def test_company_admin_creates_warehouses_only_for_own_company(self):
        r = self.send(self.client("david"), "POST", "/api/warehouses/create",
                      {"name": "Sneaky Hub", "company_name": "Lion", "set_active": False})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(r.get_json()["warehouse"]["company_name"], "glass and brass")


class TestBackgroundAndSettings(Phase3ABase):
    def test_camera_threads_write_into_the_cameras_warehouse(self):
        self.scope.refresh_camera_map()
        with self.scope.camera_scope(f"{MARK}-CAM"):
            gp = self.db.create_gate_pass({"plate": f"{MARK}03", "driver_name": "anpr"})
        self.assertEqual(self.sql("SELECT company_id, warehouse_id FROM gate_passes WHERE id = ?", (gp["id"],)),
                         [(self.leak_company, self.leak_wh)])
        self.assertIsNone(self.scope.scope_for_camera("NO-SUCH-CAMERA"))

    def test_gate_auto_dispatch_is_per_warehouse(self):
        import vision_runtime_service as vrs
        wid, cid = self.glass_wh
        vrs.set_gate_auto_dispatch(True, warehouse_id=wid)
        self.assertTrue(vrs.get_gate_auto_dispatch(warehouse_id=wid))
        self.assertFalse(vrs.get_gate_auto_dispatch(warehouse_id=self.leak_wh))
        vrs.set_gate_auto_dispatch(False, warehouse_id=wid)

    def test_staging_service_is_per_warehouse(self):
        import staging_perception_service as sps
        self.assertIsNot(sps.get_staging_service(self.glass_wh[0]), sps.get_staging_service(self.leak_wh))

    def test_uploaded_files_need_a_login_and_the_right_scope(self):
        path = self.sql("SELECT file_path FROM sku_images WHERE sku_id = ?", (GLASS_SKU,))[0][0]
        if not os.path.exists(os.path.join(WEBAPP, path.lstrip("/"))):
            self.skipTest("SKU image file not present on this machine")
        self.assertEqual(self.app_module.app.test_client().get(path).status_code, 302)
        self.assertEqual(self.get(self.client("david"), path).status_code, 200)
        self.assertEqual(self.get(self.client("leakadmin"), path).status_code, 404)
        self.assertEqual(self.app_module.app.test_client().get("/static/js/security.js").status_code, 200)

    def test_rbac_off_switches_isolation_off(self):
        self.cfg.RBAC_MODE = "off"
        try:
            self.assertIn(MARK, self.get(self.client("david"), "/api/skus").get_data(as_text=True))
        finally:
            self.cfg.RBAC_MODE = "audit"


if __name__ == "__main__":
    unittest.main()
