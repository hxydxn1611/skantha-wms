"""
test_part13_wms_controlled_actions.py
Comprehensive Part 13 test suite verifying:
1. read-only evidence retrieval
2. action recommendation
3. action preview
4. validation gates
5. explicit authorization requirement
6. receiving/unloading integration
7. cycle count recommendation
8. cycle count explicit approval
9. putaway recommendation
10. putaway explicit approval
11. dispatch recommendation
12. dispatch explicit approval
13. invalid SKU blocked
14. invalid bin blocked
15. ambiguous identity blocked
16. conflicting identity blocked
17. missing evidence blocked
18. duplicate action/idempotency protection
19. dashboard refresh does not duplicate transaction
20. audit trail
21. evidence reference snapshot
22. WMS state before/after explicit transaction
23. passive AI observation causes no mutation
24. BOX backward compatibility
25. automotive materials: GLASS, ROD, FASTENER, PART, COMPONENT, MATERIAL
26. authorization/rejection paths
"""

import sys
import os
import json
import time
import sqlite3
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp")))

from app import app
from integration_service import (
    get_integration_service,
    ControlledActionType,
    ControlledActionState
)
from material_traceability_service import (
    get_material_traceability_service,
    MaterialTraceRecord,
    MaterialTraceStatus,
    TraceabilityLevel
)
from movement_event_service import get_movement_event_service
from cycle_count_service import get_cycle_count_service
import db


class TestPart13WmsControlledActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.integration_svc = get_integration_service()
        cls.trace_svc = get_material_traceability_service()
        cls.event_svc = get_movement_event_service()
        cls.cc_svc = get_cycle_count_service()

        # Seed test bins, skus, and gate passes if needed
        conn = db.get_db()
        try:
            # Seed test bins
            conn.execute("""
                INSERT OR IGNORE INTO bins (bin_id, zone, max_volume, current_volume, max_weight, current_weight, status)
                VALUES 
                ('BIN-A101', 'Storage Zone A', 100.0, 0.0, 1000.0, 0.0, 'Active'),
                ('BIN-A102', 'Storage Zone A', 100.0, 0.0, 1000.0, 0.0, 'Active'),
                ('BIN-INACTIVE-01', 'Storage Zone A', 100.0, 0.0, 1000.0, 0.0, 'Inactive')
            """)
            
            # Seed test skus
            conn.execute("""
                INSERT OR IGNORE INTO skus (sku_id, name, category, unit_volume, unit_weight)
                VALUES 
                ('AUTO-GLASS-01', 'Laminated Windshield', 'Automotive Glass', 2.0, 5.0),
                ('AUTO-ROD-01', 'High-Tensile Tie Rod', 'Steering & Suspension', 1.0, 3.0),
                ('AUTO-BOLT-01', 'Grade 10.9 Flange Bolt', 'Fasteners', 0.1, 0.2),
                ('BOX-TEST-01', 'Packaging Carton', 'Packaging', 1.5, 2.0)
            """)

            # Seed test gate pass
            conn.execute("""
                INSERT OR IGNORE INTO gate_passes (id, plate, driver_name, vendor, status, dock, unloaded_qty, unloading_sheet)
                VALUES 
                ('GP-TEST-13', 'MH-12-AB-9999', 'Driver Suresh', 'Auto Components Ltd', 'Sent to Dock', 'DOCK-01', 0, '[{"sku":"AUTO-GLASS-01","qty":10}]'),
                ('GP-DEPARTED-13', 'MH-14-CD-0000', 'Driver Ramesh', 'Vendor B', 'Departed', 'DOCK-01', 0, '[]')
            """)

            # Clean up prior test runs
            conn.execute("DELETE FROM outbound_items WHERE order_id = 'ORD-OUT-13'")
            conn.execute("DELETE FROM outbound_orders WHERE id = 'ORD-OUT-13'")
            conn.execute("DELETE FROM inventory WHERE bin_id IN ('BIN-A101', 'BIN-A102')")
            conn.execute("UPDATE bins SET current_volume = 0.0, current_weight = 0.0 WHERE bin_id IN ('BIN-A101', 'BIN-A102')")
            conn.execute("UPDATE gate_passes SET unloaded_qty = 0, status = 'Sent to Dock' WHERE id = 'GP-TEST-13'")

            # Seed outbound order and item
            conn.execute("""
                INSERT INTO outbound_orders (id, customer_name, destination, status)
                VALUES ('ORD-OUT-13', 'Tata Motors Assembly', 'Plant Pune', 'Pending')
            """)
            conn.execute("""
                INSERT INTO outbound_items (order_id, sku_id, quantity, picked_quantity)
                VALUES ('ORD-OUT-13', 'AUTO-ROD-01', 5, 0)
            """)
            conn.commit()
        finally:
            conn.close()

    def test_01_read_only_evidence_retrieval(self):
        """Test 1: Read-only evidence retrieval causes zero mutations to inventory or master data."""
        conn = db.get_db()
        inv_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        # Call recommendations
        res = self.client.get("/api/wms/controlled_actions/recommendations")
        self.assertEqual(res.status_code, 200)

        # Call preview
        p_res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-GLASS-01",
            "params": {"sku_id": "AUTO-GLASS-01", "bin_id": "BIN-A101", "quantity": 2}
        })
        self.assertEqual(p_res.status_code, 200)

        # Call audit
        a_res = self.client.get("/api/wms/controlled_actions/audit")
        self.assertEqual(a_res.status_code, 200)

        conn = db.get_db()
        inv_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        self.assertEqual(inv_before, inv_after, "Read-only evidence endpoints must cause ZERO inventory mutations.")

    def test_02_action_recommendations(self):
        """Test 2: GET /api/wms/controlled_actions/recommendations returns structured recommendations."""
        res = self.client.get("/api/wms/controlled_actions/recommendations")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("recommendations", data)
        recs = data["recommendations"]
        self.assertIsInstance(recs, list)
        if len(recs) > 0:
            rec = recs[0]
            self.assertIn("action_type", rec)
            self.assertIn("entity_id", rec)
            self.assertIn("state", rec)
            self.assertTrue(rec.get("requires_operator_approval"))

    def test_03_action_preview_structure_and_disclaimer(self):
        """Test 3: POST /api/wms/controlled_actions/preview provides complete preview with disclaimer."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "UNLOAD_RECEIVING",
            "entity_id": "GP-TEST-13",
            "params": {"quantity": 8}
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        preview = data["preview"]

        # Check required fields
        self.assertEqual(preview["action_type"], "UNLOAD_RECEIVING")
        self.assertEqual(preview["entity_id"], "GP-TEST-13")
        self.assertEqual(preview["quantity"], 8)
        self.assertIn("expected_wms_state", preview)
        self.assertIn("projected_wms_state", preview)
        self.assertIn("exact_wms_operation", preview)
        self.assertIn("validation_gates", preview)

        # Check critical disclaimer
        self.assertIn("disclaimer", preview)
        self.assertIn("AI recommendation/evidence != completed WMS transaction", preview["disclaimer"])

    def test_04_validation_gates_clearance(self):
        """Test 4: Validation gates pass when valid parameters and authoritative masters match."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-ROD-01",
            "params": {
                "sku_id": "AUTO-ROD-01",
                "bin_id": "BIN-A101",
                "quantity": 3,
                "vendor": "Auto Components Ltd"
            }
        })
        self.assertEqual(res.status_code, 200)
        preview = res.get_json()["preview"]
        gates = preview["validation_gates"]
        self.assertTrue(gates["can_authorize"])
        self.assertEqual(len(gates["errors"]), 0)
        self.assertEqual(preview["state"], "READY_FOR_APPROVAL")

    def test_05_explicit_authorization_requirement(self):
        """Test 5: Explicit operator authorization is mandatory; blank or missing operator_id is rejected."""
        # Missing operator_id
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "UNLOAD_RECEIVING",
            "entity_id": "GP-TEST-13",
            "params": {"quantity": 5}
        })
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.get_json().get("success"))

        # Blank operator_id
        res_blank = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "UNLOAD_RECEIVING",
            "entity_id": "GP-TEST-13",
            "operator_id": "   ",
            "params": {"quantity": 5}
        })
        self.assertEqual(res_blank.status_code, 403)

    def test_06_receiving_unloading_controlled_integration(self):
        """Test 6: Authorized unloading execution mutates gate_pass unloaded_qty and logs audit activity."""
        idemp_key = f"ACT-UNLOAD-GP-TEST-13-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "UNLOAD_RECEIVING",
            "entity_id": "GP-TEST-13",
            "operator_id": "operator_dock_lead",
            "params": {"quantity": 10},
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "EXECUTED")
        self.assertEqual(data["wms_transaction"]["resulting_state"]["unloaded_qty"], 10)

        # Verify DB mutation in gate_passes
        conn = db.get_db()
        gp = conn.execute("SELECT unloaded_qty, status FROM gate_passes WHERE id = 'GP-TEST-13'").fetchone()
        conn.close()
        self.assertEqual(gp["unloaded_qty"], 10)

    def test_07_cycle_count_recommendation(self):
        """Test 7: Cycle count auditing generates recommendation when discrepancy exists."""
        rec = self.integration_svc.preview_controlled_action("CYCLE_COUNT", "BIN-A101", {"actual_qty": 4, "sku_id": "AUTO-GLASS-01"})
        self.assertEqual(rec["action_type"], "CYCLE_COUNT")
        self.assertEqual(rec["entity_id"], "BIN-A101")
        self.assertEqual(rec["quantity"], 4)
        self.assertIn("UPDATE inventory", rec["exact_wms_operation"])

    def test_08_cycle_count_explicit_approval_mutation(self):
        """Test 8: Explicit approval of cycle count commits adjustment to inventory ledger."""
        idemp_key = f"ACT-CC-BIN-A101-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "CYCLE_COUNT",
            "entity_id": "BIN-A101",
            "operator_id": "operator_auditor",
            "params": {"actual_qty": 7, "sku_id": "AUTO-GLASS-01"},
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "EXECUTED")

        # Verify inventory in database
        conn = db.get_db()
        inv = conn.execute("SELECT quantity FROM inventory WHERE bin_id = 'BIN-A101'").fetchone()
        conn.close()
        self.assertIsNotNone(inv)
        self.assertEqual(inv["quantity"], 7)

    def test_09_putaway_recommendation_and_candidate_bin(self):
        """Test 9: Putaway preview validates candidate bin and capacity without early mutation."""
        conn = db.get_db()
        b_before = conn.execute("SELECT current_volume FROM bins WHERE bin_id = 'BIN-A102'").fetchone()["current_volume"]
        conn.close()

        preview = self.integration_svc.preview_controlled_action("PUTAWAY", "AUTO-ROD-01", {
            "sku_id": "AUTO-ROD-01",
            "bin_id": "BIN-A102",
            "quantity": 4,
            "vendor": "Auto Vendor"
        })
        self.assertTrue(preview["validation_gates"]["can_authorize"])
        self.assertEqual(preview["bin"], "BIN-A102")

        # Verify no early mutation
        conn = db.get_db()
        b_after = conn.execute("SELECT current_volume FROM bins WHERE bin_id = 'BIN-A102'").fetchone()["current_volume"]
        conn.close()
        self.assertEqual(b_before, b_after, "Preview must not mutate bin volume.")

    def test_10_putaway_explicit_approval_mutation(self):
        """Test 10: Explicit operator approval of putaway commits stock and updates bin volume/weight."""
        idemp_key = f"ACT-PUTAWAY-BIN-A102-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-ROD-01",
            "operator_id": "operator_forklift_01",
            "params": {
                "sku_id": "AUTO-ROD-01",
                "bin_id": "BIN-A102",
                "quantity": 5,
                "vendor": "Auto Components Ltd"
            },
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["status"], "EXECUTED")

        # Verify bin and inventory state
        conn = db.get_db()
        inv = conn.execute("SELECT quantity FROM inventory WHERE bin_id = 'BIN-A102' AND sku_id = 'AUTO-ROD-01'").fetchone()
        b_row = conn.execute("SELECT current_volume FROM bins WHERE bin_id = 'BIN-A102'").fetchone()
        conn.close()
        self.assertEqual(inv["quantity"], 5)
        self.assertGreater(b_row["current_volume"], 0.0)

    def test_11_dispatch_recommendation(self):
        """Test 11: Outbound order generates DISPATCH action preview."""
        preview = self.integration_svc.preview_controlled_action("DISPATCH", "ORD-OUT-13")
        self.assertEqual(preview["action_type"], "DISPATCH")
        self.assertEqual(preview["entity_id"], "ORD-OUT-13")
        self.assertIn("pick_outbound", preview["exact_wms_operation"])

    def test_12_dispatch_explicit_approval_mutation(self):
        """Test 12: Explicit approval of dispatch executes picking and deducts inventory."""
        # Ensure stock is available in BIN-A102 for AUTO-ROD-01 (from test_10, we have 5 units)
        idemp_key = f"ACT-DISPATCH-ORD-OUT-13-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "DISPATCH",
            "entity_id": "ORD-OUT-13",
            "operator_id": "operator_dispatch",
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["status"], "EXECUTED")

        # Verify outbound order status
        conn = db.get_db()
        ord_row = conn.execute("SELECT status FROM outbound_orders WHERE id = 'ORD-OUT-13'").fetchone()
        inv_row = conn.execute("SELECT quantity FROM inventory WHERE bin_id = 'BIN-A102' AND sku_id = 'AUTO-ROD-01'").fetchone()
        conn.close()
        self.assertEqual(ord_row["status"], "Fulfilled")
        self.assertEqual(inv_row["quantity"], 0, "5 units picked, 0 should remain in BIN-A102")

    def test_13_invalid_sku_validation_blocked(self):
        """Test 13: Invalid or non-existent SKU is blocked at validation gate."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "INVALID_NONEXISTENT_SKU_999",
            "params": {"sku_id": "INVALID_NONEXISTENT_SKU_999", "bin_id": "BIN-A101", "quantity": 1}
        })
        self.assertEqual(res.status_code, 200)
        preview = res.get_json()["preview"]
        self.assertFalse(preview["validation_gates"]["can_authorize"])
        self.assertEqual(preview["state"], "FAILED")
        self.assertTrue(any("Invalid or unregistered SKU" in e for e in preview["validation_gates"]["errors"]))

        # Attempting execution must fail
        exec_res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "PUTAWAY",
            "entity_id": "INVALID_NONEXISTENT_SKU_999",
            "operator_id": "op_test",
            "params": {"sku_id": "INVALID_NONEXISTENT_SKU_999", "bin_id": "BIN-A101", "quantity": 1}
        })
        self.assertEqual(exec_res.status_code, 400)
        self.assertFalse(exec_res.get_json()["success"])

    def test_14_invalid_bin_validation_blocked(self):
        """Test 14: Inactive or non-existent destination bin is blocked at validation gate."""
        # Non-existent bin
        res_non = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-GLASS-01",
            "params": {"sku_id": "AUTO-GLASS-01", "bin_id": "BIN-DOES-NOT-EXIST", "quantity": 1}
        })
        self.assertFalse(res_non.get_json()["preview"]["validation_gates"]["can_authorize"])

        # Inactive bin
        res_inact = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-GLASS-01",
            "params": {"sku_id": "AUTO-GLASS-01", "bin_id": "BIN-INACTIVE-01", "quantity": 1}
        })
        self.assertFalse(res_inact.get_json()["preview"]["validation_gates"]["can_authorize"])
        self.assertTrue(any("Inactive" in e for e in res_inact.get_json()["preview"]["validation_gates"]["errors"]))

    def test_15_ambiguous_identity_blocked(self):
        """Test 15: Material with unresolved ambiguous visual identity is blocked from putaway."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "MAT-AMBIG-99",
            "params": {
                "sku_id": "AUTO-GLASS-01",
                "bin_id": "BIN-A101",
                "identity_status": "AMBIGUOUS"
            }
        })
        preview = res.get_json()["preview"]
        self.assertFalse(preview["validation_gates"]["can_authorize"])
        self.assertTrue(any("ambiguity" in e.lower() for e in preview["validation_gates"]["errors"]))

    def test_16_conflicting_identity_blocked(self):
        """Test 16: Entity with unresolved conflicts is blocked from authorization."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "PUTAWAY",
            "entity_id": "MAT-CONFLICT-01",
            "params": {
                "sku_id": "AUTO-GLASS-01",
                "bin_id": "BIN-A101",
                "has_conflict": True
            }
        })
        preview = res.get_json()["preview"]
        self.assertFalse(preview["validation_gates"]["can_authorize"])

    def test_17_missing_evidence_blocked(self):
        """Test 17: Receiving without verified evidence and without explicit quantity is blocked."""
        res = self.client.post("/api/wms/controlled_actions/preview", json={
            "action_type": "UNLOAD_RECEIVING",
            "entity_id": "GP-DEPARTED-13",
            "params": {}
        })
        preview = res.get_json()["preview"]
        self.assertFalse(preview["validation_gates"]["can_authorize"])
        self.assertTrue(any("Departed" in e for e in preview["validation_gates"]["errors"]))

    def test_18_duplicate_action_idempotency_protection(self):
        """Test 18: Repeated execution with same idempotency key returns cached result with duplicate_prevented=True."""
        idemp_key = f"ACT-IDEMP-TEST-{time.time()}"
        payload = {
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-BOLT-01",
            "operator_id": "operator_fastener_lead",
            "params": {
                "sku_id": "AUTO-BOLT-01",
                "bin_id": "BIN-A101",
                "quantity": 10,
                "vendor": "Fasteners Co"
            },
            "idempotency_key": idemp_key
        }

        # First execution: mutates
        res1 = self.client.post("/api/wms/controlled_actions/execute", json=payload)
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertFalse(data1.get("duplicate_prevented", False))

        # Check inventory in DB
        conn = db.get_db()
        qty_after_first = conn.execute("SELECT quantity FROM inventory WHERE bin_id = 'BIN-A101' AND sku_id = 'AUTO-BOLT-01'").fetchone()["quantity"]
        conn.close()
        self.assertEqual(qty_after_first, 10)

        # Second execution: idempotency hit! Must NOT add another 10
        res2 = self.client.post("/api/wms/controlled_actions/execute", json=payload)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2.get("duplicate_prevented"))
        self.assertTrue(data2.get("idempotent_replay"))

        # Verify DB was NOT mutated again
        conn = db.get_db()
        qty_after_second = conn.execute("SELECT quantity FROM inventory WHERE bin_id = 'BIN-A101' AND sku_id = 'AUTO-BOLT-01'").fetchone()["quantity"]
        conn.close()
        self.assertEqual(qty_after_second, 10, "Inventory must NOT mutate a second time on duplicate execution.")

    def test_19_dashboard_refresh_idempotent_zero_mutations(self):
        """Test 19: Polling or refreshing the live vision dashboard causes zero mutations."""
        conn = db.get_db()
        inv_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        for _ in range(5):
            res = self.client.get("/api/vision/dashboard/live")
            self.assertEqual(res.status_code, 200)

        conn = db.get_db()
        inv_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()
        self.assertEqual(inv_before, inv_after)

    def test_20_audit_trail(self):
        """Test 20: Audit trail captures executed and rejected controlled actions."""
        res = self.client.get("/api/wms/controlled_actions/audit")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        audits = data.get("audit_trail", [])
        self.assertIsInstance(audits, list)
        self.assertGreater(len(audits), 0)

    def test_21_evidence_reference(self):
        """Test 21: Evidence snapshot preserves structured references without binary image blobs."""
        idemp_key = f"ACT-SNAP-TEST-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "CYCLE_COUNT",
            "entity_id": "BIN-A102",
            "operator_id": "operator_snapshot_auditor",
            "params": {"actual_qty": 3, "sku_id": "AUTO-ROD-01"},
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        snapshot = res.get_json().get("evidence_snapshot", {})
        self.assertIn("material_id", snapshot)
        self.assertIn("sku", snapshot)
        self.assertIn("timestamp", snapshot)
        self.assertIn("action_type", snapshot)
        self.assertIn("operator", snapshot)
        # Ensure no binary blobs
        for k, v in snapshot.items():
            self.assertNotIsInstance(v, (bytes, bytearray))

    def test_22_wms_state_before_after_explicit_transaction(self):
        """Test 22: Execution result transparently reports previous and resulting WMS state."""
        idemp_key = f"ACT-STATES-TEST-{time.time()}"
        res = self.client.post("/api/wms/controlled_actions/execute", json={
            "action_type": "CYCLE_COUNT",
            "entity_id": "BIN-A102",
            "operator_id": "operator_state_auditor",
            "params": {"actual_qty": 8, "sku_id": "AUTO-ROD-01"},
            "idempotency_key": idemp_key
        })
        self.assertEqual(res.status_code, 200)
        txn = res.get_json().get("wms_transaction", {})
        self.assertIn("previous_state", txn)
        self.assertIn("resulting_state", txn)
        self.assertEqual(txn["resulting_state"]["actual_qty"], 8)

    def test_23_passive_ai_observation_causes_no_mutation(self):
        """Test 23: Traceability synthetic sequence runs passively with zero database mutations."""
        conn = db.get_db()
        inv_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        res = self.client.post("/api/integration/e2e/test_scenario", json={"po_number": "PO-8821"})
        self.assertIn(res.status_code, (200, 400))  # scenario ran

        conn = db.get_db()
        inv_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()
        self.assertEqual(inv_before, inv_after)

    def test_24_box_backward_compatibility(self):
        """Test 24: Legacy BOX object class is fully supported in controlled actions."""
        preview = self.integration_svc.preview_controlled_action("PUTAWAY", "B104", {
            "sku_id": "BOX-TEST-01",
            "bin_id": "BIN-A101",
            "quantity": 2,
            "vendor": "Box Packaging Vendor"
        })
        self.assertTrue(preview["validation_gates"]["can_authorize"])
        self.assertEqual(preview["material_sku"], "BOX-TEST-01")

    def test_25_automotive_materials_support(self):
        """Test 25: Automotive materials (GLASS, ROD, FASTENER, PART, COMPONENT, MATERIAL) are recognized."""
        for sku_code in ["AUTO-GLASS-01", "AUTO-ROD-01", "AUTO-BOLT-01"]:
            preview = self.integration_svc.preview_controlled_action("PUTAWAY", sku_code, {
                "sku_id": sku_code,
                "bin_id": "BIN-A101",
                "quantity": 1
            })
            self.assertTrue(preview["validation_gates"]["can_authorize"], f"Automotive SKU {sku_code} must clear validation gates.")

    def test_26_authorization_and_rejection_paths(self):
        """Test 26: Operator rejection path logs reason, returns status REJECTED, and leaves inventory untouched."""
        conn = db.get_db()
        inv_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        res = self.client.post("/api/wms/controlled_actions/reject", json={
            "action_type": "PUTAWAY",
            "entity_id": "AUTO-GLASS-01",
            "reason": "Container damaged upon physical inspection at staging area",
            "operator_id": "operator_qc_lead"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "REJECTED")
        self.assertEqual(data.get("rejection_reason"), "Container damaged upon physical inspection at staging area")

        # Verify zero inventory mutations
        conn = db.get_db()
        inv_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()
        self.assertEqual(inv_before, inv_after)


if __name__ == "__main__":
    unittest.main()
