"""
Fixes found in the full workflow test in the browser (2026-11-21):

  1. a pre-registered delivery list (saved as sku_id/expected) is read by the dock put-away and
     the receipt dialog (they looked for "sku" and found nothing)
  2. Palletization "Save count to pallet" saves on the server; a SEALED pallet can be put into stock
     in its bin, once (it never reached stock before; the Seal button called a missing function)
  3. gate pass numbers of deleted passes are not handed out again (their history would attach)
  4. a photo count keeps the stack in front and leaves out other stacks in the background and
     pieces found twice (47 -> 26 on the test photo of 28 steel channels)
"""
import json
import sqlite3
import unittest

from tests.test_stock_flows import FlowBase


class TestManifestKeys(FlowBase):
    def test_normalize_sheet_accepts_both_spellings(self):
        import db
        out = db.normalize_sheet('[{"sku_id": "A-1", "expected": "28"}, {"sku": "B-2", "expected_qty": 5, "desc": "x"}, "junk"]')
        self.assertEqual([(l["sku"], l["sku_id"], l["expected"], l["expected_qty"]) for l in out],
                         [("A-1", "A-1", 28, 28), ("B-2", "B-2", 5, 5)])
        self.assertEqual(out[1]["description"], "x")
        self.assertEqual(db.normalize_sheet("not json"), [])

    def test_dock_completed_puts_away_a_preregistered_sheet(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d, "TN38E2E001", sheet=[{"sku_id": "GLS-FLT-06MM", "vendor": "V", "expected": 12}])
        body = self.send(d, "GET", f"/api/gate_passes/{gp}").get_json()
        sheet = body.get("gate_pass", body)["unloading_sheet"]
        self.assertEqual((sheet[0]["sku"], sheet[0]["expected"]), ("GLS-FLT-06MM", 12))
        before = self.qty_in("FLOW-B", "GLS-FLT-06MM")
        for st in ("Sent to Dock", "Unloading"):
            self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": st})
        r = self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": "Completed", "bin_allocation": "FLOW-B", "unloaded_qty": 12})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        # the dock counts packs: 12 bundles x the product's pieces per bundle
        upb = self.sql("SELECT COALESCE(units_per_bundle, 1) FROM skus WHERE sku_id = 'GLS-FLT-06MM'")[0][0] or 1
        self.assertEqual(self.qty_in("FLOW-B", "GLS-FLT-06MM"), before + 12 * upb)


class TestPalletToStock(FlowBase):
    def pallet(self, d, bin_id="FLOW-A"):
        r = self.send(d, "POST", "/api/pallets", {"sku_id": "GLS-FLT-06MM", "units_per_bundle": 10, "target_bundles": 0,
                                                  "assigned_bin_id": bin_id})
        body = r.get_json()
        return (body.get("pallet") or {}).get("pallet_id") or body.get("pallet_id")

    def test_count_seal_put_away_once(self):
        d = self.client("david", self.glass_wh[0])
        pid = self.pallet(d)
        # individual pieces: 28 counted, 1 per "bundle" (the pallet was created with 10 per bundle)
        r = self.send(d, "POST", f"/api/pallets/{pid}/count", {"counted_bundles": 28, "units_per_bundle": 1})
        self.assertEqual(r.get_json()["pallet"]["total_units"], 28)
        r = self.send(d, "POST", f"/api/pallets/{pid}/putaway", {})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Seal the pallet first", r.get_json()["error"])
        self.assertTrue(self.send(d, "POST", f"/api/pallets/{pid}/seal", {}).get_json()["success"])
        before = self.qty_in("FLOW-A", "GLS-FLT-06MM")
        r = self.send(d, "POST", f"/api/pallets/{pid}/putaway", {})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.qty_in("FLOW-A", "GLS-FLT-06MM"), before + 28)
        self.assertEqual(self.sql("SELECT movement_type, delta, actor FROM stock_movements WHERE ref = ?", (f"PALLET-{pid}",)),
                         [("receive", 28, "david")])
        r = self.send(d, "POST", f"/api/pallets/{pid}/putaway", {})              # only once
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.qty_in("FLOW-A", "GLS-FLT-06MM"), before + 28)

    def test_empty_pallet_is_not_put_away(self):
        d = self.client("david", self.glass_wh[0])
        pid = self.pallet(d)
        self.send(d, "POST", f"/api/pallets/{pid}/seal", {})
        r = self.send(d, "POST", f"/api/pallets/{pid}/putaway", {})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no counted pieces", r.get_json()["error"])

    def test_put_away_needs_the_transfer_permission(self):
        d = self.client("david", self.glass_wh[0])
        pid = self.pallet(d)
        self.send(d, "POST", f"/api/pallets/{pid}/count", {"counted_bundles": 3, "units_per_bundle": 1})
        self.send(d, "POST", f"/api/pallets/{pid}/seal", {})
        self.cfg.RBAC_MODE = "enforce"
        ex = self.role_user("executive", "palexec")
        self.assertEqual(self.send(ex, "POST", f"/api/pallets/{pid}/putaway", {}).status_code, 403)


class TestGatePassNumbers(FlowBase):
    def test_deleted_number_is_not_reused(self):
        d = self.client("david", self.glass_wh[0])
        gp = self.new_pass(d, "TN38E2E002")
        self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": "Approved"})     # leaves history
        r = self.send(d, "DELETE", f"/api/gate_passes/{gp}", {"reason": "test delete"})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))
        gp2 = self.new_pass(d, "TN38E2E003")
        self.assertNotEqual(gp2, gp)
        self.assertGreater(int(gp2.split("-")[1]), int(gp.split("-")[1]))


class TestStackFocus(unittest.TestCase):
    @staticmethod
    def box(x, y, w, h):
        return {"bbox": [x, y, x + w, y + h], "x": x + w // 2, "y": y + h // 2}

    def test_keeps_the_front_stack_only(self):
        import stack_focus
        stack = [self.box(150 + c * 115, 190 + r * 62, 100, 58) for r in range(7) for c in range(4)]   # 28, touching
        far = [self.box(120, 50, 43, 26), self.box(200, 100, 50, 30), self.box(720, 300, 70, 60),     # other stacks
               self.box(10, 420, 60, 36), self.box(60, 470, 55, 34)]
        dups = [self.box(170, 200, 50, 25), self.box(400, 330, 45, 24)]                                # inside real ones
        kept, stats = stack_focus.main_stack(stack + far + dups)
        self.assertEqual(len(kept), 28)
        self.assertEqual(stats, {"kept": 28, "background": 5, "duplicates": 2})

    def test_small_or_clean_counts_are_left_alone(self):
        import stack_focus
        three = [self.box(0, 0, 10, 10), self.box(500, 500, 10, 10), self.box(900, 0, 10, 10)]
        self.assertEqual(len(stack_focus.main_stack(three)[0]), 3)
        grid = [self.box(c * 52, r * 52, 50, 50) for r in range(3) for c in range(3)]
        kept, stats = stack_focus.main_stack(grid)
        self.assertEqual((len(kept), stats["background"], stats["duplicates"]), (9, 0, 0))


if __name__ == "__main__":
    unittest.main()
