"""
Fixes found while testing the test_house warehouse in the live app (2026-11-21):

  1. AI Vision "Transfer to WMS" onto a pallet never worked (it wrote a column pallets does not have);
     it now fills the pallet, refuses missing / sealed / other-product pallets and a count with no product,
     and records the signed-in user instead of "OP-VISION"
  2. Counting Studio counts an item once when the model also drew a box around two items, or found the same
     item twice (28 channels were marked 37)
  3. the counting engine only cleans up the count pictures it made itself, never older files
"""
import os
import tempfile
import unittest

from tests.test_stock_flows import FlowBase

SKU = "GLS-FLT-06MM"


class TestVisionTransferToPallet(FlowBase):
    def setUp(self):
        from pallet_vision_counting_service import get_pallet_vision_counting_service
        self.sessions = get_pallet_vision_counting_service()._active_multiview_sessions
        self.d = self.client("david", self.glass_wh[0])

    def pallet(self, sku=SKU):
        body = self.send(self.d, "POST", "/api/pallets", {"sku_id": sku, "units_per_bundle": 1, "assigned_bin_id": "FLOW-A"}).get_json()
        return (body.get("pallet") or {}).get("pallet_id") or body.get("pallet_id")

    def approved(self, sid, sku=SKU, pieces=12):
        self.sessions[sid] = {"session_id": sid, "review_status": "APPROVED", "sku_id": sku, "counting_mode": "individual_pieces",
                              "total_pieces": pieces, "total_bundles": 0, "uom": "EA"}
        return sid

    def transfer(self, sid, **body):
        return self.send(self.d, "POST", "/api/pallets/transfer-inventory", dict(body, session_id=sid))

    def test_count_goes_onto_the_pallet_then_into_stock_once(self):
        pid = self.pallet()
        r = self.transfer(self.approved("SES-TH-1"), target_type="pallet", pallet_id=pid)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.sql("SELECT counted_bundles, units_per_bundle, total_units FROM pallets WHERE pallet_id = ?", (pid,)),
                         [(12, 1, 12)])
        self.assertEqual(self.sql("SELECT operator_id FROM vision_counting_submissions WHERE session_id = 'SES-TH-1'"), [("david",)])
        self.assertEqual(self.transfer("SES-TH-1", target_type="pallet", pallet_id=pid).status_code, 409)   # only once
        before = self.qty_in("FLOW-A", SKU)
        self.send(self.d, "POST", f"/api/pallets/{pid}/seal", {})
        self.assertTrue(self.send(self.d, "POST", f"/api/pallets/{pid}/putaway", {}).get_json()["success"])
        self.assertEqual(self.qty_in("FLOW-A", SKU), before + 12)

    def test_wrong_targets_are_refused_without_changing_anything(self):
        r = self.transfer(self.approved("SES-TH-2"), target_type="pallet", pallet_id="PAL-001")
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (404, "pallet_not_found"))
        sealed = self.pallet()
        self.send(self.d, "POST", f"/api/pallets/{sealed}/count", {"counted_bundles": 3, "units_per_bundle": 1})
        self.send(self.d, "POST", f"/api/pallets/{sealed}/seal", {})
        r = self.transfer(self.approved("SES-TH-3"), target_type="pallet", pallet_id=sealed)
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "pallet_sealed"))
        self.assertEqual(self.sql("SELECT total_units, status FROM pallets WHERE pallet_id = ?", (sealed,)), [(3, "SEALED")])
        other = self.pallet("GLS-FLT-04MM")
        r = self.transfer(self.approved("SES-TH-4"), target_type="pallet", pallet_id=other)
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "pallet_sku_mismatch"))
        r = self.transfer(self.approved("SES-TH-5", sku=None), target_type="bin", bin_id="FLOW-A")
        self.assertEqual((r.status_code, r.get_json()["error_code"]), (400, "missing_sku"))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM vision_counting_submissions WHERE session_id IN "
                                  "('SES-TH-2', 'SES-TH-3', 'SES-TH-4', 'SES-TH-5')"), [(0,)])


class TestPalletNumbers(FlowBase):
    def test_a_deleted_pallets_number_is_not_given_out_again(self):
        d = self.client("david", self.glass_wh[0])
        body = self.send(d, "POST", "/api/pallets", {"sku_id": SKU, "units_per_bundle": 1, "assigned_bin_id": "FLOW-B"}).get_json()
        pid = (body.get("pallet") or {}).get("pallet_id") or body.get("pallet_id")
        self.send(d, "POST", f"/api/pallets/{pid}/count", {"counted_bundles": 2, "units_per_bundle": 1})
        self.send(d, "POST", f"/api/pallets/{pid}/seal", {})
        self.assertTrue(self.send(d, "POST", f"/api/pallets/{pid}/putaway", {}).get_json()["success"])
        self.assertLess(self.send(d, "DELETE", f"/api/pallets/{pid}").status_code, 400)
        import db
        self.assertNotEqual(db.generate_pallet_id(), pid)       # its stock history still says PALLET-<pid>


class TestStudioCountsEachItemOnce(unittest.TestCase):
    @staticmethod
    def box(x1, y1, x2, y2, conf):
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "conf": conf}

    def test_group_boxes_and_repeats_go_neighbours_stay(self):
        from counting_studio_service import _drop_repeats
        grid = [self.box(100 + c * 110, 100 + r * 60, 205 + c * 110, 158 + r * 60, 0.8) for r in range(4) for c in range(3)]
        group = [self.box(100, 100, 205, 218, 0.2), self.box(210, 220, 315, 338, 0.15)]       # around 2 channels each
        again = [self.box(103, 102, 204, 156, 0.4)]                                             # first channel again
        kept = _drop_repeats(grid + group + again)
        self.assertEqual(len(kept), 12)
        self.assertTrue(all(k["conf"] == 0.8 for k in kept))

    def test_a_double_box_with_one_single_inside_is_kept(self):
        from counting_studio_service import _drop_repeats
        # carton stack: the model boxed cartons 1+2 together and found carton 1 alone - carton 2 has no other box
        kept = _drop_repeats([self.box(48, 25, 189, 109, 0.83), self.box(48, 36, 110, 109, 0.27), self.box(190, 25, 255, 108, 0.6)])
        self.assertEqual(len(kept), 3)


class TestCountPictureCleanup(unittest.TestCase):
    def test_only_pictures_made_by_this_run_are_removed(self):
        import pallet_vision_counting_service as svc
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "piece_count_old.jpg")
            open(old, "wb").close()
            saved, svc._RECENT_OUTPUTS[:] = list(svc._RECENT_OUTPUTS), []
            try:
                made = []
                for i in range(svc._KEEP_OUTPUTS + 3):
                    p = os.path.join(tmp, f"piece_count_{i}.jpg")
                    open(p, "wb").close()
                    svc._keep_recent_outputs(p)
                    made.append(p)
                self.assertTrue(os.path.exists(old))                                  # never ours to delete
                self.assertEqual([os.path.exists(p) for p in made], [False] * 3 + [True] * svc._KEEP_OUTPUTS)
            finally:
                svc._RECENT_OUTPUTS[:] = saved


if __name__ == "__main__":
    unittest.main()
