"""
Stock flows (fixes after the workflow review, 2026-11-21):

  1. receiving ADDS to a bin's stock (it used to replace it); the same truck is received once
  2. one receiving path: a real product is required (no invented SKU codes); the dock
     "Completed" put-away no longer deadlocks (it waited 15 s on its own open transaction)
  3. picking takes stock only from the current location, earliest expiry / oldest first,
     and an order line counts as picked only for what was really deducted
"""
import json
import sqlite3
import time
import unittest

from tests.test_rbac_phase7 import Phase7Base


class FlowBase(Phase7Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        wh, co = cls.glass_wh
        conn = sqlite3.connect(cls.db_path)
        with conn:
            for b in ("FLOW-A", "FLOW-B"):
                conn.execute("INSERT OR IGNORE INTO bins (bin_id, zone, max_volume, max_weight, company_id, warehouse_id) "
                             "VALUES (?, 'F', 1000, 100000, ?, ?)", (b, co, wh))
            cls.leak_bin = conn.execute("SELECT bin_id FROM bins WHERE warehouse_id = ? LIMIT 1", (cls.leak_wh,)).fetchone()[0]
        conn.close()

    def qty_in(self, bin_id, sku):
        return self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE bin_id = ? AND sku_id = ?", (bin_id, sku))[0][0]

    def new_pass(self, d, plate, sheet=None):
        body = {"plate": plate, "driver_name": "Flow Driver", "vendor": "Flow Vendor"}
        if sheet is not None:
            body["unloading_sheet"] = json.dumps(sheet)
        r = self.send(d, "POST", "/api/gate_passes", body)
        b = r.get_json()
        return b.get("gate_pass", b).get("id") or b.get("id")


class TestReceiving(FlowBase):
    def test_receipt_adds_to_existing_stock_and_only_once(self):
        d = self.client("david", self.glass_wh[0])
        gp1 = self.new_pass(d, "TN38FLOW01")
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp1, "bin_id": "FLOW-A", "sku_id": "GLS-FLT-06MM", "quantity": 50})
        self.assertTrue(r.get_json()["success"], r.get_json())
        gp2 = self.new_pass(d, "TN38FLOW02")
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp2, "bin_id": "FLOW-A", "sku_id": "GLS-FLT-06MM", "quantity": 30})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.qty_in("FLOW-A", "GLS-FLT-06MM"), 80)              # 50 + 30, not 30
        # the same truck again: refused, stock unchanged
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp2, "bin_id": "FLOW-A", "sku_id": "GLS-FLT-06MM", "quantity": 30})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already been received", r.get_json()["message"])
        self.assertEqual(self.qty_in("FLOW-A", "GLS-FLT-06MM"), 80)
        mv = self.sql("SELECT movement_type, actor, delta FROM stock_movements WHERE ref = ?", (f"GRN-{gp2}",))
        self.assertEqual(mv, [("receive", "david", 30)])
        self.assertEqual(self.sql("SELECT status FROM gate_passes WHERE id = ?", (gp2,))[0][0], "Completed")

    def test_unknown_product_or_foreign_bin_is_refused(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d, "TN38FLOW03")
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp, "bin_id": "FLOW-A", "sku_id": "SKU-INBOUND-01", "quantity": 5})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not in the product list", r.get_json()["message"])
        self.assertFalse(self.sql("SELECT 1 FROM skus WHERE sku_id = 'SKU-INBOUND-01'"))   # nothing invented
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp, "bin_id": self.leak_bin, "sku_id": "GLS-FLT-06MM", "quantity": 5})
        self.assertIn(r.status_code, (400, 404))
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp, "bin_id": "FLOW-A", "sku_id": "GLS-FLT-06MM", "quantity": 0})
        self.assertEqual(r.status_code, 400)

    def test_dock_completed_books_the_sheet_product_fast_and_once(self):
        import db
        d = self.client("david", self.glass_wh[0])
        upb = self.sql("SELECT units_per_bundle FROM skus WHERE sku_id = 'GLS-FLT-08MM'")[0][0] or 1
        gp = self.new_pass(d, "TN38FLOW04", sheet=[{"sku": "GLS-FLT-08MM", "expected": 4}])
        before = self.qty_in("FLOW-B", "GLS-FLT-08MM")
        with self.scope.using(self.scope.Scope.warehouse(self.glass_wh[1], self.glass_wh[0])):
            t0 = time.time()
            db.update_gate_pass(gp, {"status": "Completed", "bin_allocation": "FLOW-B", "unloaded_qty": 4})
            took = time.time() - t0
        self.assertLess(took, 5, "dock completion must not wait on its own open transaction")
        self.assertEqual(self.qty_in("FLOW-B", "GLS-FLT-08MM"), before + 4 * max(1, int(upb)))
        # Inbound can't book the same truck again
        r = self.send(d, "POST", "/api/inbound/complete_receipt", {"gp_id": gp, "bin_id": "FLOW-B", "sku_id": "GLS-FLT-08MM", "quantity": 4})
        self.assertEqual(r.status_code, 400)

    def test_dock_completed_without_a_product_books_nothing(self):
        import db
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d, "TN38FLOW05")
        skus_before = self.sql("SELECT COUNT(*) FROM skus")[0][0]
        stock_before = self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE bin_id = 'FLOW-B'")[0][0]
        with self.scope.using(self.scope.Scope.warehouse(self.glass_wh[1], self.glass_wh[0])):
            db.update_gate_pass(gp, {"status": "Completed", "bin_allocation": "FLOW-B", "unloaded_qty": 7})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM skus")[0][0], skus_before)          # no "SKU-FLO01" invented
        self.assertEqual(self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE bin_id = 'FLOW-B'")[0][0], stock_before)


class TestPicking(FlowBase):
    def test_picks_here_only_and_earliest_expiry_first(self):
        wh, co = self.glass_wh
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("DELETE FROM inventory WHERE sku_id = 'GLS-FLT-10MM'")
            mk = lambda b, q, exp, rec, w, c: conn.execute(
                "INSERT INTO inventory (bin_id, sku_id, quantity, expiry_date, received_date, company_id, warehouse_id) "
                "VALUES (?, 'GLS-FLT-10MM', ?, ?, ?, ?, ?)", (b, q, exp, rec, c, w)).lastrowid
            late = mk("FLOW-A", 10, "2027-12-01", "2026-01-01", wh, co)
            early = mk("FLOW-B", 10, "2027-01-01", "2026-06-01", wh, co)
            other = mk(self.leak_bin, 100, "2026-12-01", "2025-01-01", self.leak_wh, self.leak_company)   # another company
        conn.close()
        d = self.client("david", wh)
        r = self.send(d, "POST", "/api/outbound", {"customer_name": "Flow Co", "destination": "Chennai",
                                                     "items": [{"sku_id": "GLS-FLT-10MM", "quantity": 15}]})
        order = r.get_json()["order_id"]
        r = self.send(d, "POST", f"/api/outbound/{order}/pick", {})
        body = r.get_json()
        self.assertEqual(body["status"], "Fulfilled", body)
        q = dict(self.sql("SELECT id, quantity FROM inventory WHERE id IN (?, ?, ?)", (late, early, other)))
        self.assertEqual((q[early], q[late], q[other]), (0, 5, 100))   # earliest expiry first; other company untouched
        self.assertEqual(self.sql("SELECT picked_quantity FROM outbound_items WHERE order_id = ?", (order,))[0][0], 15)
        self.assertTrue(self.sql("SELECT 1 FROM stock_movements WHERE ref = ? AND movement_type = 'pick'", (order,)))

    def test_short_stock_is_reported_not_faked(self):
        wh, _ = self.glass_wh
        d = self.client("david", wh)
        have = self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE sku_id = 'GLS-FLT-12MM' AND warehouse_id = ?", (wh,))[0][0]
        r = self.send(d, "POST", "/api/outbound", {"customer_name": "Flow Co", "destination": "Chennai",
                                                     "items": [{"sku_id": "GLS-FLT-12MM", "quantity": have + 7}]})
        order = r.get_json()["order_id"]
        body = self.send(d, "POST", f"/api/outbound/{order}/pick", {}).get_json()
        self.assertEqual(body["status"], "Partially Picked")
        self.assertIn("7 short", body["message"])
        self.assertEqual(self.sql("SELECT picked_quantity FROM outbound_items WHERE order_id = ?", (order,))[0][0], have)


if __name__ == "__main__":
    unittest.main()
