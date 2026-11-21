"""
Inventory section (menu: Inventory; also Master Data Hub > Inventory Master).

  * every stock change writes a history line (database triggers), whoever made it
  * adjust: needs a reason, never negative, named person + reason in the history
  * transfer: never more than is there, same location only, out/in pair with one reference
  * minimum levels drive the "below minimum" alert
  * the all-locations view is read-only; another company's stock is never visible or changeable
  * permissions are checked in the handlers in every RBAC mode
  * Inventory Master and the Inventory section show the same live numbers
"""
import os
import sqlite3
import unittest

from tests.test_rbac_phase7 import Phase7Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InvBase(Phase7Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        conn = sqlite3.connect(cls.db_path)
        with conn:
            wh, co = cls.glass_wh
            for b, z in (("INV-T-A1", "A"), ("INV-T-B1", "B")):
                conn.execute("INSERT OR IGNORE INTO bins (bin_id, zone, max_volume, max_weight, company_id, warehouse_id) "
                             "VALUES (?, ?, 100, 1000, ?, ?)", (b, z, co, wh))
            cur = conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, batch_number, vendor, company_id, warehouse_id) "
                               "VALUES ('INV-T-A1', 'GLS-FLT-04MM', 50, 'INV-BATCH', 'Test vendor', ?, ?)", (co, wh))
            cls.line = cur.lastrowid
        conn.close()

    def qty(self, inv_id):
        rows = self.sql("SELECT quantity FROM inventory WHERE id = ?", (inv_id,))
        return rows[0][0] if rows else None

    def overview(self, c):
        r = self.get(c, "/api/stock/overview")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()


class TestLedgerTriggers(InvBase):
    def test_migration_created_tables_and_triggers(self):
        names = {r[0] for r in self.sql("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")}
        for n in ("stock_movements", "stock_min_levels", "stock_ledger_ins", "stock_ledger_upd", "stock_ledger_del"):
            self.assertIn(n, names)
        self.assertTrue(self.sql("SELECT 1 FROM schema_migrations WHERE step = '012_stock_ledger'"))

    def test_background_writers_are_recorded_as_system(self):
        # the setup's db.update_bin_stock ran with no request: a history line, no person
        rows = self.sql("SELECT actor, movement_type, qty_after, warehouse_id FROM stock_movements WHERE bin_id LIKE '%-BIN' "
                        "AND warehouse_id = ?", (self.leak_wh,))
        self.assertTrue(rows)
        self.assertEqual(rows[0][:2], (None, "created"))

    def test_existing_endpoint_gets_the_person_and_reason(self):
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "PUT", f"/api/inventory/{self.line}", {"quantity": 48, "reason": "old screen edit"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        row = self.sql("SELECT actor, movement_type, reason, qty_after FROM stock_movements WHERE inventory_id = ? "
                       "ORDER BY id DESC LIMIT 1", (self.line,))[0]
        self.assertEqual(row, ("david", "adjust", "old screen edit", 48))
        self.assertEqual(self.send(d, "PUT", f"/api/inventory/{self.line}", {"quantity": -3, "reason": "x"}).status_code, 400)
        self.assertEqual(self.send(d, "PUT", f"/api/inventory/{self.line}", {"quantity": "abc", "reason": "x"}).status_code, 400)


class TestAdjust(InvBase):
    def test_reason_is_required_and_quantity_never_negative(self):
        d = self.client("david", self.glass_wh[0])
        before = self.qty(self.line)
        r = self.send(d, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": 40})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error_code"], "reason_required")
        r = self.send(d, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": -1, "reason": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.qty(self.line), before)

    def test_adjust_is_recorded_with_person_and_reason(self):
        d = self.client("david", self.glass_wh[0])
        before = self.qty(self.line)
        r = self.send(d, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": before - 5,
                                                       "reason_code": "damaged", "reason": "Damaged / broken: 5 cracked"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.qty(self.line), before - 5)
        row = self.sql("SELECT actor, movement_type, reason, qty_before, qty_after, delta, warehouse_id FROM stock_movements "
                       "WHERE inventory_id = ? ORDER BY id DESC LIMIT 1", (self.line,))[0]
        self.assertEqual(row, ("david", "adjust", "Damaged / broken: 5 cracked", before, before - 5, -5, self.glass_wh[0]))
        self.assertTrue(self.audit_rows("inventory.adjusted", resource_id=str(self.line)))
        hist = self.get(d, f"/api/stock/movements?inventory_id={self.line}").get_json()["movements"]
        self.assertEqual(hist[0]["type_label"], "Adjustment")


class TestTransfer(InvBase):
    def test_transfer_moves_stock_and_writes_a_pair(self):
        d = self.client("david", self.glass_wh[0])
        have = self.qty(self.line)
        r = self.send(d, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": have + 1, "to_bin": "INV-T-B1"})
        self.assertEqual(r.get_json()["error_code"], "insufficient")
        r = self.send(d, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": 10, "to_bin": "INV-T-B1",
                                                         "reason": "rack swap"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertEqual(self.qty(self.line), have - 10)
        self.assertEqual(self.qty(body["to_inventory_id"]), 10)
        pair = self.sql("SELECT movement_type, delta, actor, ref FROM stock_movements WHERE ref = ? ORDER BY id", (body["ref"],))
        self.assertEqual(sorted((t, dl) for t, dl, _, _ in pair), [("transfer_in", 10), ("transfer_out", -10)])
        self.assertTrue(all(a == "david" for _, _, a, _ in pair))
        # moving it all back empties (removes) the target line
        r = self.send(d, "POST", "/api/stock/transfer", {"inventory_id": body["to_inventory_id"], "quantity": 10, "to_bin": "INV-T-A1"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertIsNone(self.qty(body["to_inventory_id"]))
        self.assertEqual(self.qty(self.line), have)

    def test_cannot_move_into_another_companys_bin(self):
        d = self.client("david", self.glass_wh[0])
        r = self.send(d, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": 1, "to_bin": "INV-LEAK-BIN"})
        self.assertIn(r.status_code, (404,))
        leak_bin = self.sql("SELECT bin_id FROM bins WHERE warehouse_id = ? LIMIT 1", (self.leak_wh,))[0][0]
        r = self.send(d, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": 1, "to_bin": leak_bin})
        self.assertEqual(r.status_code, 404)


class TestScopeAndPermissions(InvBase):
    def test_other_company_stock_is_invisible_and_untouchable(self):
        d = self.client("david", self.glass_wh[0])
        lines = self.overview(d)["lines"]
        self.assertFalse([l for l in lines if l["warehouse_id"] == self.leak_wh])
        leak_line = self.sql("SELECT id FROM inventory WHERE warehouse_id = ? LIMIT 1", (self.leak_wh,))[0][0]
        before = self.qty(leak_line)
        r = self.send(d, "POST", "/api/stock/adjust", {"inventory_id": leak_line, "quantity": 1, "reason": "x"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.qty(leak_line), before)
        hist = self.get(d, "/api/stock/movements").get_json()["movements"]
        self.assertFalse([m for m in hist if m["bin_id"] and m["bin_id"].endswith("-BIN") and "LEAK" in m["bin_id"].upper()])

    def test_all_locations_view_is_read_only(self):
        d = self.client("david", "all")
        self.assertTrue(self.overview(d)["read_only"])
        r = self.send(d, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": 1, "reason": "x"})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "read_only_scope"))

    def test_changes_need_the_permission_even_in_audit_mode(self):
        self.cfg.RBAC_MODE = "audit"
        ex = self.role_user("executive", "invexec")   # inventory.view only
        self.assertEqual(self.get(ex, "/api/stock/overview").status_code, 200)
        before = self.qty(self.line)
        r = self.send(ex, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": 1, "reason": "x"})
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (403, "permission_denied"))
        r = self.send(ex, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": 1, "to_bin": "INV-T-B1"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.get(ex, "/api/stock/export.csv").status_code, 403)
        self.assertEqual(self.qty(self.line), before)

    def test_inventory_controller_can_move_but_not_adjust(self):
        ic = self.role_user("inventory_controller", "invctl")
        r = self.send(ic, "POST", "/api/stock/adjust", {"inventory_id": self.line, "quantity": 1, "reason": "x"})
        self.assertEqual(r.status_code, 403)
        r = self.send(ic, "POST", "/api/stock/transfer", {"inventory_id": self.line, "quantity": 1, "to_bin": "INV-T-B1"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        back = r.get_json()["to_inventory_id"]
        self.send(ic, "POST", "/api/stock/transfer", {"inventory_id": back, "quantity": 1, "to_bin": "INV-T-A1"})
        r = self.send(ic, "PUT", "/api/stock/min-level", {"sku_id": "GLS-FLT-04MM", "min_qty": 5})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.get(ic, "/api/stock/export.csv").status_code, 200)


class TestMinLevelsAndMaster(InvBase):
    def test_min_level_drives_low_alert(self):
        d = self.client("david", self.glass_wh[0])
        total = sum(l["quantity"] for l in self.overview(d)["lines"] if l["sku_id"] == "GLS-FLT-04MM")
        r = self.send(d, "PUT", "/api/stock/min-level", {"sku_id": "GLS-FLT-04MM", "min_qty": total + 100})
        self.assertTrue(r.get_json()["success"], r.get_json())
        ov = self.overview(d)
        self.assertIn("GLS-FLT-04MM", [p["sku_id"] for p in ov["alerts"]["low"]])
        self.send(d, "PUT", "/api/stock/min-level", {"sku_id": "GLS-FLT-04MM", "min_qty": None})
        self.assertNotIn("GLS-FLT-04MM", [p["sku_id"] for p in self.overview(d)["alerts"]["low"]])
        self.assertEqual(self.sql("SELECT warehouse_id FROM stock_min_levels"), [])

    def test_master_and_section_show_the_same_numbers(self):
        d = self.client("david", self.glass_wh[0])
        legacy = {r["id"]: r["quantity"] for r in self.get(d, "/api/inventory").get_json()}
        section = {l["id"]: l["quantity"] for l in self.overview(d)["lines"]}
        self.assertEqual(legacy, section)

    def test_export_csv(self):
        d = self.client("david", self.glass_wh[0])
        r = self.get(d, "/api/stock/export.csv")
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertTrue(text.startswith("Location,SKU,Product"))
        self.assertIn("INV-T-A1", text)


class TestFrontendWiring(unittest.TestCase):
    def test_menu_view_and_master_are_linked(self):
        html = open(os.path.join(ROOT, "webapp", "templates", "index.html"), encoding="utf-8").read()
        self.assertIn('data-module="inventory"', html)
        self.assertIn('id="inventory-view"', html)
        self.assertIn("loadInventoryMaster", html)
        self.assertIn("js/inventory.js", html)
        perms = open(os.path.join(ROOT, "webapp", "static", "js", "permissions.js"), encoding="utf-8").read()
        self.assertIn("'inventory': 'inventory.view'", perms)


if __name__ == "__main__":
    unittest.main()
