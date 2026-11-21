"""
2026-11-21 (after the test_house walk-through):

  1. Dashboard: /api/dashboard/live is built from real records only (stock movements, trucks in, pallets
     sealed, newest events, a health score from checks that can fail) and follows the location
  2. Products per location: a location can take a product out of its own lists (product list, dropdowns,
     photo recognition); the company's other locations keep it; adding it there again brings it back
"""
import sqlite3

from tests.test_stock_flows import FlowBase


class TestDashboardLive(FlowBase):
    def test_numbers_come_from_real_records_of_this_location(self):
        d = self.client("david", self.glass_wh[0])
        before = self.get(d, "/api/dashboard/live?range=24h").get_json()
        self.assertTrue(before["success"])
        self.assertEqual(len(before["labels"]), 12)
        self.assertEqual(set(before["series"]), {"stock_movements", "trucks_in", "pallets_sealed"})
        # a pallet counted, sealed and put away: one pallet sealed and one stock movement
        body = self.send(d, "POST", "/api/pallets", {"sku_id": "GLS-FLT-06MM", "units_per_bundle": 1, "assigned_bin_id": "FLOW-A"}).get_json()
        pid = (body.get("pallet") or {}).get("pallet_id") or body.get("pallet_id")
        self.send(d, "POST", f"/api/pallets/{pid}/count", {"counted_bundles": 3, "units_per_bundle": 1})
        self.send(d, "POST", f"/api/pallets/{pid}/seal", {})
        self.assertTrue(self.send(d, "POST", f"/api/pallets/{pid}/putaway", {}).get_json()["success"])
        after = self.get(d, "/api/dashboard/live?range=24h").get_json()
        self.assertEqual(after["today"]["stock_movements"], before["today"]["stock_movements"] + 1)
        self.assertEqual(after["today"]["pallets_sealed"], before["today"]["pallets_sealed"] + 1)
        self.assertEqual(sum(after["series"]["stock_movements"]), sum(before["series"]["stock_movements"]) + 1)
        self.assertTrue(any(pid in f["title"] or "GLS-FLT-06MM" in f["title"] for f in after["feed"][:2]), after["feed"][:2])
        for rng, n in (("7d", 7), ("30d", 30)):
            self.assertEqual(len(self.get(d, f"/api/dashboard/live?range={rng}").get_json()["labels"]), n)
        names = [c["name"] for c in after["checks"]]
        self.assertEqual(names, ["Database", "Cameras online", "AI counting models", "Stock records"])
        self.assertTrue(0 <= after["health"] <= 100)

    def test_another_location_does_not_see_these_movements(self):
        other = self.sql("SELECT id FROM warehouses WHERE company_id = ? AND id <> ? LIMIT 1", (self.glass_wh[1], self.glass_wh[0]))
        if not other:
            self.skipTest("the company has one location")
        mine = self.sql("SELECT COUNT(*) FROM stock_movements WHERE warehouse_id = ?", (other[0][0],))[0][0]
        body = self.get(self.client("david", other[0][0]), "/api/dashboard/live?range=30d").get_json()
        self.assertLessEqual(sum(body["series"]["stock_movements"]), mine)


class TestProductsPerLocation(FlowBase):
    def other_location(self):
        rows = self.sql("SELECT id FROM warehouses WHERE company_id = ? AND id <> ? ORDER BY id LIMIT 1", (self.glass_wh[1], self.glass_wh[0]))
        if not rows:
            self.skipTest("the company has one location")
        return rows[0][0]

    def sku_ids(self, c, path):
        body = self.get(c, path).get_json()
        items = (body.get("data") or {}).get("items") if isinstance(body, dict) and "data" in body else body
        return {i["sku_id"] for i in (items or [])}

    def test_removed_here_only_and_back_when_added_again(self):
        other = self.other_location()
        here, there = self.client("david", other), self.client("david", self.glass_wh[0])
        # a product no location has taken out of its lists (live data may hide some)
        rows = self.sql("SELECT sku_id FROM skus WHERE company_id = ? AND sku_id LIKE 'GLS-%' AND sku_id NOT IN "
                        "(SELECT sku_id FROM warehouse_hidden_skus WHERE warehouse_id IN (?, ?)) AND sku_id NOT IN "
                        "(SELECT sku_id FROM inventory WHERE quantity > 0 AND warehouse_id = ?) "
                        "ORDER BY sku_id LIMIT 1", (self.glass_wh[1], other, self.glass_wh[0], other))
        if not rows:
            self.skipTest("no free product to test with")
        sku = rows[0][0]
        qty_here = self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE sku_id = ? AND warehouse_id = ?", (sku, other))[0][0]
        if qty_here:
            self.skipTest("that product has stock in the other location")
        r = self.send(here, "DELETE", f"/api/sku_master/{sku}?where=here")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertNotIn(sku, self.sku_ids(here, "/api/sku_master?limit=100&page=1"))
        self.assertNotIn(sku, self.sku_ids(here, "/api/skus"))
        self.assertIn(sku, self.sku_ids(there, "/api/sku_master?limit=100&page=1"))      # other location keeps it
        self.assertEqual(self.sql("SELECT COUNT(*) FROM skus WHERE sku_id = ?", (sku,)), [(1,)])  # nothing deleted
        row = self.sql("SELECT name, category FROM skus WHERE sku_id = ?", (sku,))[0]
        r = self.send(here, "POST", "/api/sku_master", {"sku_id": sku, "name": row[0], "category": row[1]})
        self.assertLess(r.status_code, 400, r.get_json())
        self.assertIn(sku, self.sku_ids(here, "/api/sku_master?limit=100&page=1"))

    def test_refused_while_this_location_holds_stock(self):
        d = self.client("david", self.glass_wh[0])
        held = self.sql("SELECT sku_id FROM inventory WHERE warehouse_id = ? AND quantity > 0 LIMIT 1", (self.glass_wh[0],))
        if not held:
            self.skipTest("no stock in this location")
        r = self.send(d, "DELETE", f"/api/sku_master/{held[0][0]}?where=here")
        self.assertEqual(r.status_code, 400)
        self.assertIn("still holds", r.get_json()["message"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM warehouse_hidden_skus WHERE sku_id = ? AND warehouse_id = ?",
                                  (held[0][0], self.glass_wh[0])), [(0,)])
