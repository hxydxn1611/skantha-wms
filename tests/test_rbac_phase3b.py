"""
RBAC Phase 3B: per-company template copies, per-company AI classes, per-warehouse zones,
template preview, opt-in sample data, and clear "code already in use" answers.

Runs on a private copy of the live database (never the live file). Template images are
written to a temporary folder, never into webapp/static.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from tests.test_rbac_phase3a import MARK, Phase3ABase

GLASS_SKU = "GLS-FLT-04MM"


def _table_digest(db_path, table, where="1=1", params=()):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY rowid", params).fetchall()
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest(), len(rows)


class Phase3BBase(Phase3ABase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import industry_blueprint_service as bps
        cls.bps = bps
        cls._img_tmp = tempfile.mkdtemp(prefix="warlog_phase3b_img_")
        cls._saved_upload = bps.UPLOAD_DIR
        bps.UPLOAD_DIR = cls._img_tmp

    @classmethod
    def tearDownClass(cls):
        cls.bps.UPLOAD_DIR = cls._saved_upload
        shutil.rmtree(cls._img_tmp, ignore_errors=True)
        super().tearDownClass()

    def glass_company_digest(self):
        cid = self.glass_wh[1]
        return {t: _table_digest(self.db_path, t, "company_id = ?", (cid,))
                for t in ("skus", "sku_images", "object_classes", "vision_zones", "expected_deliveries")}

    def apply(self, user, body, wh=None):
        # Phase 7: applying a template is an exceptional action and needs a reason
        return self.send(self.client(user, wh), "POST", "/api/industry_blueprints/apply", {"reason": "test", **body})


class TestSchema(Phase3BBase):
    def test_step_008_applied_and_codes_are_per_company(self):
        self.assertTrue(self.sql("SELECT 1 FROM schema_migrations WHERE step = '008_per_company_codes'"))
        ddl = self.sql("SELECT sql FROM sqlite_master WHERE name = 'object_classes'")[0][0]
        self.assertIn("UNIQUE(company_id, code)", ddl.replace(" ", "").replace("UNIQUE(company_id,code)", "UNIQUE(company_id, code)"))
        ddl = self.sql("SELECT sql FROM sqlite_master WHERE name = 'vision_zones'")[0][0]
        self.assertIn("UNIQUE(warehouse_id, zone_code)", ddl)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()

    def test_class_rename_only_moves_that_companys_camera_links(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("INSERT INTO object_classes (code, name, company_id) VALUES ('RENAME_ME', 'x', ?)", (self.leak_company,))
                conn.execute("INSERT INTO object_classes (code, name, company_id) VALUES ('RENAME_ME', 'x', ?)", (self.glass_wh[1],))
                conn.execute("INSERT INTO vision_camera_object_classes (camera_id, class_code) VALUES ('CAM-001', 'RENAME_ME')")
                conn.execute("UPDATE object_classes SET code = 'RENAMED' WHERE code = 'RENAME_ME' AND company_id = ?", (self.leak_company,))
            self.assertEqual(conn.execute("SELECT class_code FROM vision_camera_object_classes WHERE camera_id = 'CAM-001' "
                                          "AND class_code IN ('RENAME_ME', 'RENAMED')").fetchall(), [("RENAME_ME",)])
            with conn:
                conn.execute("DELETE FROM object_classes WHERE code = 'RENAME_ME' AND company_id = ?", (self.glass_wh[1],))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM vision_camera_object_classes WHERE class_code = 'RENAME_ME'").fetchone()[0], 0)
        finally:
            conn.close()


class TestTemplates(Phase3BBase):
    def test_preview_changes_nothing(self):
        before = {t: _table_digest(self.db_path, t) for t in ("skus", "sku_images", "object_classes", "vision_zones",
                                                                "expected_deliveries", "warehouses", "inventory", "pallets")}
        r = self.apply("leakadmin", {"blueprint_key": "glass", "warehouse_code": "CURRENT", "preview": True,
                                     "include_samples": True})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertTrue(data["preview"])
        self.assertEqual(data["skus_created"], 22)
        self.assertEqual(data["warehouse"]["code"], "WH-LEAKTEST")
        after = {t: _table_digest(self.db_path, t) for t in before}
        self.assertEqual(before, after)
        self.assertEqual(os.listdir(self._img_tmp), [])

    def test_second_company_gets_its_own_copy_and_glass_is_untouched(self):
        glass_before = self.glass_company_digest()
        r = self.apply("leakadmin", {"blueprint_key": "glass", "warehouse_code": "CURRENT"})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        self.assertEqual(data["skus_created"], 22)
        self.assertEqual(data["codes_renamed"][GLASS_SKU], f"{GLASS_SKU}-LEAKT")
        self.assertEqual(data["deliveries_created"], 0, "sample data must be opt-in")
        self.assertEqual(self.glass_company_digest(), glass_before)

        cid, wid = self.leak_company, self.leak_wh
        self.assertEqual(self.sql("SELECT company_id FROM skus WHERE sku_id = ?", (f"{GLASS_SKU}-LEAKT",)), [(cid,)])
        img = self.sql("SELECT file_path, company_id FROM sku_images WHERE sku_id = ?", (f"{GLASS_SKU}-LEAKT",))[0]
        self.assertEqual(img, (f"/static/uploads/sku_images/c{cid}/{GLASS_SKU}-LEAKT.png", cid))
        self.assertTrue(os.path.exists(os.path.join(self._img_tmp, f"c{cid}", f"{GLASS_SKU}-LEAKT.png")))
        # the detector's own class codes, now per company
        self.assertEqual(self.sql("SELECT COUNT(*) FROM object_classes WHERE code = 'BOX'")[0][0], 2)
        self.assertEqual(self.sql("SELECT company_id FROM object_classes WHERE code = 'GLASS_A_FRAME' ORDER BY company_id"),
                         sorted([(self.glass_wh[1],), (cid,)]))
        self.assertEqual(self.sql("SELECT warehouse_id FROM vision_zones WHERE zone_code = 'TB-GLS' ORDER BY warehouse_id"),
                         sorted([(self.glass_wh[0],), (wid,)]))
        # classes linked only to the target warehouse's camera
        self.assertTrue(self.sql("SELECT 1 FROM vision_camera_object_classes WHERE camera_id = ? AND class_code = 'GLASS_A_FRAME'",
                                 (f"{MARK}-CAM",)))

        # each company sees exactly its own copy
        leak_skus = {s["sku_id"] for s in self.get(self.client("leakadmin"), "/api/skus").get_json()}
        glass_skus = {s["sku_id"] for s in self.get(self.client("david"), "/api/skus").get_json()}
        self.assertIn(f"{GLASS_SKU}-LEAKT", leak_skus)
        self.assertNotIn(GLASS_SKU, leak_skus)
        self.assertIn(GLASS_SKU, glass_skus)
        self.assertNotIn(f"{GLASS_SKU}-LEAKT", glass_skus)
        leak_classes = [c["code"] for c in self.get(self.client("leakadmin"), "/api/object_classes").get_json()["classes"]] \
            if isinstance(self.get(self.client("leakadmin"), "/api/object_classes").get_json(), dict) else []
        if leak_classes:
            self.assertEqual(leak_classes.count("BOX"), 1)

        # applying again adds nothing
        again = self.apply("leakadmin", {"blueprint_key": "glass", "warehouse_code": "CURRENT"}).get_json()
        self.assertEqual((again["skus_created"], again["classes_created"], again["zones_created"]), (0, 0, 0))

    def test_sample_data_only_when_ticked_and_in_the_right_warehouse(self):
        r = self.apply("david", {"blueprint_key": "glass", "warehouse_code": "WH-GLASS-COI", "include_samples": True})
        data = r.get_json()
        self.assertTrue(data["success"], data)
        for d in data["deliveries"]:
            self.assertEqual(self.sql("SELECT warehouse_id, is_demo FROM expected_deliveries WHERE po_number = ?",
                                      (d["po_number"],)), [(self.glass_wh[0], 1)])
        # the original glass deliveries stay live (kept with --keep-live)
        self.assertEqual(self.sql("SELECT is_demo FROM expected_deliveries WHERE po_number = 'PO-SGG-4011'"), [(0,)])

    def test_template_cannot_target_another_companys_warehouse(self):
        before = self.glass_company_digest()
        r = self.apply("leakadmin", {"blueprint_key": "glass", "warehouse_code": "WH-GLASS-COI"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.glass_company_digest(), before)

class TestAutoSetup(Phase3BBase):
    def test_auto_setup_for_a_company_user_never_creates_a_company(self):
        companies = self.sql("SELECT COUNT(*) FROM companies")[0][0]
        users = self.sql("SELECT username, company_name, assigned_warehouse_code FROM users ORDER BY id")
        r = self.send(self.client("leakadmin"), "POST", "/api/company/auto_setup",
                      {"company_name": "Totally New Glass Co", "username": "david"})
        data = r.get_json()
        if r.status_code == 403:  # enforce mode: platform-only action
            return
        self.assertTrue(data.get("success"), data)
        self.assertEqual(data["warehouse"]["code"], "WH-LEAKTEST")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM companies")[0][0], companies)
        self.assertEqual(self.sql("SELECT username, company_name, assigned_warehouse_code FROM users ORDER BY id"), users)


class TestCodesInUse(Phase3BBase):
    def test_creating_a_code_another_company_uses_is_refused_clearly(self):
        before = self.glass_company_digest()
        leak = self.client("leakadmin")
        r = self.send(leak, "POST", "/api/skus", {"sku_id": GLASS_SKU, "name": "hijack"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], "code_in_use")
        self.assertNotIn("glass", r.get_data(as_text=True).lower().replace(GLASS_SKU.lower(), ""))
        self.assertEqual(self.send(leak, "POST", "/api/bins", {"bin_id": self.sql(
            "SELECT bin_id FROM bins WHERE warehouse_id = ? LIMIT 1", (self.glass_wh[0],))[0][0]}).status_code, 409)
        self.assertEqual(self.send(leak, "POST", "/api/deliveries", {"po_number": "PO-SGG-4011"}).status_code, 409)
        self.assertEqual(self.send(leak, "POST", "/api/cameras", {"camera_id": "CAM-001", "name": "x"}).status_code, 409)
        self.assertEqual(self.glass_company_digest(), before)
        self.assertEqual(self.sql("SELECT name FROM cameras WHERE camera_id = 'CAM-001'"), [("Gate 01 ANPR & Security Bay",)])

    def test_own_codes_still_update_as_before(self):
        r = self.send(self.client("david"), "POST", "/api/skus",
                      {"sku_id": "P3B-OWN-SKU", "name": "first"})
        self.assertTrue(r.get_json()["success"])
        r = self.send(self.client("david"), "POST", "/api/skus",
                      {"sku_id": "P3B-OWN-SKU", "name": "second"})
        self.assertTrue(r.get_json()["success"])
        self.assertEqual(self.sql("SELECT name, company_id FROM skus WHERE sku_id = 'P3B-OWN-SKU'"),
                         [("second", self.glass_wh[1])])

    def test_two_companies_can_have_the_same_class_and_zone_codes(self):
        leak = self.client("leakadmin")
        r = self.send(leak, "POST", "/api/object_classes", {"code": "GLASS_SHEET_STACK", "name": "Leak sheets"})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM object_classes WHERE code = 'GLASS_SHEET_STACK'")[0][0], 2)
        zone = self.sql("SELECT zone_code FROM vision_zones WHERE warehouse_id = ? LIMIT 1", (self.glass_wh[0],))[0][0]
        r = self.send(leak, "POST", "/api/vision/zones", {"zone_code": zone, "zone_name": "Leak zone", "zone_type": "STORAGE"})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM vision_zones WHERE zone_code = ?", (zone,))[0][0], 2)
        # and each still finds its own by code
        g = self.get(self.client("david"), f"/api/object_classes/GLASS_SHEET_STACK").get_json()
        self.assertNotIn("Leak sheets", json.dumps(g))


if __name__ == "__main__":
    unittest.main()
