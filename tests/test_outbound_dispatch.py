"""
Outbound truck through the gate (mirrors inbound):

  order -> pick -> assign truck (gate pass, activity Loading, linked to the order)
        -> gate (Approved) -> loading dock -> Loading -> Loaded -> checkout -> Dispatched

  * the order's status follows its truck; Dispatched records the time
  * no truck before the order is fully picked; one truck at a time; a rejected truck can be replaced
  * a truck can't leave while its order isn't fully picked
  * an outbound pass never takes over another truck's pass or a pre-registered PO, and loading
    never adds stock (the inbound put-away only runs for receiving trucks)
"""
import sqlite3

from tests.test_rbac_phase7 import Phase7Base


class OutBase(Phase7Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        wh, co = cls.glass_wh
        conn = sqlite3.connect(cls.db_path)
        with conn:
            conn.execute("INSERT OR IGNORE INTO bins (bin_id, zone, max_volume, max_weight, company_id, warehouse_id) "
                         "VALUES ('OUT-BIN', 'O', 1000, 100000, ?, ?)", (co, wh))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, company_id, warehouse_id) "
                         "VALUES ('OUT-BIN', 'GLS-FLT-06MM', 500, ?, ?)", (co, wh))
        conn.close()

    def order(self, d, qty=5):
        r = self.send(d, "POST", "/api/outbound", {"customer_name": "Out Co", "destination": "Madurai",
                                                     "items": [{"sku_id": "GLS-FLT-06MM", "quantity": qty}]})
        return r.get_json()["order_id"]

    def status(self, order_id):
        return self.sql("SELECT status FROM outbound_orders WHERE id = ?", (order_id,))[0][0]

    def move(self, d, gp, status):
        r = self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": status})
        self.assertLess(r.status_code, 400, r.get_data(as_text=True))


class TestOutboundJourney(OutBase):
    def test_order_follows_its_truck_until_dispatched(self):
        d = self.client("david", self.glass_wh[0])
        oid = self.order(d)
        r = self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT001"})
        self.assertEqual(r.status_code, 400)                                    # not picked yet
        self.assertIn("Pick the whole order first", r.get_json()["message"])
        self.assertEqual(self.send(d, "POST", f"/api/outbound/{oid}/pick", {}).get_json()["status"], "Fulfilled")

        r = self.send(d, "POST", f"/api/outbound/{oid}/truck",
                      {"plate": "tn38out001", "driver_name": "Out Driver", "driver_phone": "9000000099", "transporter": "Fast Haul"})
        body = r.get_json()
        self.assertTrue(body["success"], body)
        gp = body["gate_pass"]["id"]
        row = self.sql("SELECT activity, outbound_order_id, plate, status, otp != '' FROM gate_passes WHERE id = ?", (gp,))[0]
        self.assertEqual(row, ("Loading", oid, "TN38OUT001", "Pending", 1))
        self.assertEqual(self.sql("SELECT status, gate_pass_id, vehicle_plate, transporter FROM outbound_orders WHERE id = ?", (oid,))[0],
                         ("Truck assigned", gp, "TN38OUT001", "Fast Haul"))
        # one truck at a time
        self.assertEqual(self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT009"}).status_code, 400)

        stock = self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE sku_id = 'GLS-FLT-06MM' AND warehouse_id = ?",
                         (self.glass_wh[0],))[0][0]
        for gate_status, order_status in (("Approved", "Truck at gate"), ("Sent to Dock", "At loading dock"),
                                          ("Unloading", "Loading"), ("Completed", "Loaded")):
            if gate_status == "Completed":   # loading must never run the inbound put-away
                self.send(d, "PUT", f"/api/gate_passes/{gp}", {"bin_allocation": "OUT-BIN", "unloaded_qty": 5})
            self.move(d, gp, gate_status)
            self.assertEqual(self.status(oid), order_status, gate_status)
        self.assertEqual(self.sql("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE sku_id = 'GLS-FLT-06MM' AND warehouse_id = ?",
                                  (self.glass_wh[0],))[0][0], stock)
        r = self.send(d, "POST", f"/api/gate/checkout/{gp}", {})
        self.assertTrue(r.get_json()["success"], r.get_json())
        st, sent = self.sql("SELECT status, dispatched_at FROM outbound_orders WHERE id = ?", (oid,))[0]
        self.assertEqual(st, "Dispatched")
        self.assertTrue(sent)
        events = [r[0] for r in self.sql("SELECT to_status FROM gate_pass_events WHERE gp_id = ? ORDER BY id", (gp,))]
        self.assertEqual(events[-1], "Exited")                                  # checkout now goes through history
        self.assertTrue(self.audit_rows("outbound.truck_assigned"))

    def test_truck_cant_leave_while_order_not_fully_picked(self):
        d = self.client("david", self.glass_wh[0])
        oid = self.order(d, qty=3)
        self.send(d, "POST", f"/api/outbound/{oid}/pick", {})
        gp = self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT002"}).get_json()["gate_pass"]["id"]
        conn = sqlite3.connect(self.db_path)
        with conn:   # the order grew after the truck was assigned
            conn.execute("UPDATE outbound_items SET quantity = quantity + 2 WHERE order_id = ?", (oid,))
        conn.close()
        for attempt in (lambda: self.send(d, "POST", f"/api/gate/checkout/{gp}", {}),
                        lambda: self.send(d, "PUT", f"/api/gate_passes/{gp}", {"status": "Departed"}),
                        lambda: self.send(d, "POST", "/api/gate/checkout", {"plate": "TN38OUT002"})):
            r = attempt()
            self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
            self.assertEqual(r.get_json()["error_code"], "outbound_not_ready")
        self.assertNotEqual(self.status(oid), "Dispatched")

    def test_rejected_truck_can_be_replaced(self):
        d = self.client("david", self.glass_wh[0])
        oid = self.order(d, qty=2)
        self.send(d, "POST", f"/api/outbound/{oid}/pick", {})
        gp = self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT003"}).get_json()["gate_pass"]["id"]
        self.move(d, gp, "Rejected")
        self.assertEqual(self.status(oid), "Truck rejected")
        r = self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT004"})
        self.assertTrue(r.get_json()["success"], r.get_json())
        self.assertEqual(self.status(oid), "Truck assigned")

    def test_outbound_pass_never_takes_over_another_truck_or_po(self):
        d = self.client("david", self.glass_wh[0])
        # an inbound truck with the same plate is already waiting, and a PO is pre-registered for it
        self.send(d, "POST", "/api/deliveries", {"po_number": "PO-OUT-CLASH", "plate": "TN38OUT005", "vendor": "Clash Vendor",
                                                 "expected_date": "2026-11-30"})
        inbound = self.send(d, "POST", "/api/gate_passes", {"plate": "TN38OUT005", "driver_name": "Inbound"}).get_json()
        inbound_id = inbound.get("gate_pass", inbound).get("id")
        oid = self.order(d, qty=1)
        self.send(d, "POST", f"/api/outbound/{oid}/pick", {})
        gp = self.send(d, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT005"}).get_json()["gate_pass"]
        self.assertNotEqual(gp["id"], inbound_id)
        po, activity, linked = self.sql("SELECT po_number, activity, outbound_order_id FROM gate_passes WHERE id = ?", (gp["id"],))[0]
        self.assertEqual((po, activity, linked), (None, "Loading", oid))
        self.assertIsNone(self.sql("SELECT outbound_order_id FROM gate_passes WHERE id = ?", (inbound_id,))[0][0])

    def test_needs_the_dispatch_permission(self):
        d = self.client("david", self.glass_wh[0])
        oid = self.order(d, qty=1)
        self.send(d, "POST", f"/api/outbound/{oid}/pick", {})
        self.cfg.RBAC_MODE = "enforce"
        ex = self.role_user("executive", "obexec")
        r = self.send(ex, "POST", f"/api/outbound/{oid}/truck", {"plate": "TN38OUT006"})
        self.assertEqual(r.status_code, 403)
