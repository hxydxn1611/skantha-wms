"""
2026-11-21: how a product is counted (AI Vision product form -> Palletization mode)

  * migration 017 gives every product a counting type from what it already says
  * the product form saves the type and, for cartons, what is inside; older callers keep it as it is
  * a count no longer writes the workbench's pieces-per-pack back into the product
  * Palletization's product list carries the type, so the workbench can switch to it
"""
from tests.test_stock_flows import FlowBase


class TestCountAs(FlowBase):
    def test_existing_products_got_a_type_from_what_they_say(self):
        rows = dict(self.sql("SELECT sku_id, count_as FROM skus WHERE company_id = ?", (self.glass_wh[1],)))
        self.assertTrue(rows and all(v in ("pieces", "bundles", "cartons") for v in rows.values()), rows)
        for sku, upb, uom, ca in self.sql("SELECT sku_id, units_per_bundle, uom, count_as FROM skus WHERE company_id = ?", (self.glass_wh[1],)):
            if str(uom).upper() not in ("BOX", "BOXES", "CARTON", "CARTONS", "CASE", "CASES") and (upb or 1) > 1 and not sku.startswith("TH-"):
                self.assertEqual(ca, "bundles", sku)

    def test_form_saves_type_and_carton_contents(self):
        d = self.client("david", self.glass_wh[0])
        body = {"sku_id": "CA-MUG-12", "name": "Carton of mugs", "category": "Packed Goods", "uom": "EA",
                "units_per_bundle": 12, "bundle_name": "Carton", "count_as": "cartons", "pack_contents": ""}
        r = self.send(d, "POST", "/api/sku_master", body)
        self.assertEqual(r.status_code, 400)
        self.assertIn("inside each carton", r.get_json()["message"])
        r = self.send(d, "POST", "/api/sku_master", dict(body, pack_contents="Ceramic mug 350ml"))
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.sql("SELECT count_as, pack_contents, units_per_bundle FROM skus WHERE sku_id = 'CA-MUG-12'"),
                         [("cartons", "Ceramic mug 350ml", 12)])
        # a caller that does not send the type (older screens, Excel) keeps it
        self.send(d, "POST", "/api/sku_master", {"sku_id": "CA-MUG-12", "name": "Carton of mugs (renamed)", "units_per_bundle": 12})
        self.assertEqual(self.sql("SELECT count_as, pack_contents FROM skus WHERE sku_id = 'CA-MUG-12'"), [("cartons", "Ceramic mug 350ml")])
        r = self.send(d, "POST", "/api/sku_master", dict(body, count_as="loose"))
        self.assertEqual(r.status_code, 400)
        # individual pieces always mean 1 per pack
        self.send(d, "POST", "/api/sku_master", dict(body, sku_id="CA-PIPE-1", name="Pipe", count_as="pieces", units_per_bundle=7))
        self.assertEqual(self.sql("SELECT count_as, units_per_bundle FROM skus WHERE sku_id = 'CA-PIPE-1'"), [("pieces", 1)])
        listed = {s["sku_id"]: s for s in self.get(d, "/api/pallets/vision-skus").get_json()["skus"]}
        self.assertEqual((listed["CA-MUG-12"]["count_as"], listed["CA-MUG-12"]["pack_contents"]), ("cartons", "Ceramic mug 350ml"))

    def test_a_count_does_not_change_the_products_pack_size(self):
        import io
        import numpy as np
        import cv2
        d = self.client("david", self.glass_wh[0])
        before = self.sql("SELECT units_per_bundle, uom, bundle_name FROM skus WHERE sku_id = 'GLS-FLT-06MM'")
        ok, png = cv2.imencode(".png", np.full((120, 160, 3), 200, np.uint8))
        r = d.post("/api/pallets/count-pieces", headers={"X-CSRF-Token": "t", "X-Warehouse-Id": str(self.glass_wh[0])},
                   data={"sku_id": "GLS-FLT-06MM", "units_per_bundle": "1", "uom": "PCS", "bundle_name": "Piece",
                         "image": (io.BytesIO(png.tobytes()), "x.png")}, content_type="multipart/form-data")
        self.assertLess(r.status_code, 500)
        self.assertEqual(self.sql("SELECT units_per_bundle, uom, bundle_name FROM skus WHERE sku_id = 'GLS-FLT-06MM'"), before)
