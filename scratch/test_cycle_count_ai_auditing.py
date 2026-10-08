"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 7 — Cycle Count AI & Bin Discrepancy Auditing Test Suite

Tests:
1. Matching inventory (observed == expected)
2. Shortage (observed < expected)
3. Excess (observed > expected)
4. Empty bin (expected > 0 with observed == 0, and expected == 0 with observed == 0)
5. Unidentified & ambiguous material
6. Multiple materials (mixed/co-mingled SKUs)
7. No vision evidence (no camera / tracks)
8. Explicit Cycle Count inventory update & activities ledger logging
9. Passive AI processing leaves inventory strictly unchanged (zero-mutation invariant)
10. Material-agnostic automotive component support (glass, rods, fasteners, cartons)
"""

import os
import sys
import json
import sqlite3
import unittest
from datetime import datetime

# Set test environment flag
os.environ["WARLOG_TEST_MODE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))

import db
from app import app
from cycle_count_service import (
    get_cycle_count_service,
    DiscrepancyType,
    CycleCountRecommendation,
    ObservedMaterial
)
from validation_service import get_validation_service


class TestCycleCountAIAuditing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.service = get_cycle_count_service()
        cls.validator = get_validation_service()
        cls.client = app.test_client()

    def setUp(self):
        # Clean test records from database before each test
        conn = db.get_db()
        with conn:
            conn.execute("DELETE FROM inventory WHERE bin_id LIKE 'TEST-BIN-%'")
            conn.execute("DELETE FROM bins WHERE bin_id LIKE 'TEST-BIN-%'")
            conn.execute("DELETE FROM skus WHERE sku_id LIKE 'TEST-SKU-%'")
        conn.close()

    def tearDown(self):
        # Clean test records
        conn = db.get_db()
        with conn:
            conn.execute("DELETE FROM inventory WHERE bin_id LIKE 'TEST-BIN-%'")
            conn.execute("DELETE FROM bins WHERE bin_id LIKE 'TEST-BIN-%'")
            conn.execute("DELETE FROM skus WHERE sku_id LIKE 'TEST-SKU-%'")
        conn.close()

    # ========================================================================
    # 1. MATCHING INVENTORY
    # ========================================================================
    def test_01_matching_inventory(self):
        """Physical observation matches WMS inventory count perfectly."""
        bin_id = "TEST-BIN-MATCH"
        sku_id = "TEST-SKU-GLASS"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-A', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Windshield Glass', 'Automotive Glass')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 10, 'Pilkington')", (bin_id, sku_id))
        conn.close()

        # Observation has exactly 10 validated units
        obs = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-A"],
            "observed_materials": [
                {
                    "observed_id": sku_id,
                    "sku_id": sku_id,
                    "name": "Windshield Glass",
                    "material_type": "Automotive Glass",
                    "quantity": 10,
                    "identity_status": "VALIDATED",
                    "confidence": 0.98
                }
            ]
        }

        res = self.service.evaluate_bin(bin_id, observation_override=obs)
        self.assertTrue(res["success"])
        self.assertEqual(res["wms_inventory"]["total_quantity"], 10)
        self.assertEqual(res["vision_evidence"]["total_observed_qty"], 10)
        self.assertEqual(res["discrepancy"]["type"], DiscrepancyType.MATCH.value)
        self.assertEqual(res["discrepancy"]["delta"], 0)
        self.assertEqual(res["discrepancy"]["recommendation"], CycleCountRecommendation.NO_ACTION_REQUIRED.value)
        self.assertFalse(res["discrepancy"]["is_action_required"])

    # ========================================================================
    # 2. SHORTAGE
    # ========================================================================
    def test_02_shortage(self):
        """Vision observes fewer units than recorded in WMS inventory."""
        bin_id = "TEST-BIN-SHORT"
        sku_id = "TEST-SKU-ROD"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-B', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Suspension Tie Rod', 'Steering & Suspension')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 20, 'ThyssenKrupp')", (bin_id, sku_id))
        conn.close()

        # Vision observes only 14 units
        obs = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-B"],
            "observed_materials": [
                {
                    "sku_id": sku_id,
                    "material_type": "Steering & Suspension",
                    "quantity": 14,
                    "identity_status": "VALIDATED",
                    "confidence": 0.94
                }
            ]
        }

        res = self.service.evaluate_bin(bin_id, observation_override=obs)
        self.assertTrue(res["success"])
        self.assertEqual(res["wms_inventory"]["total_quantity"], 20)
        self.assertEqual(res["vision_evidence"]["total_observed_qty"], 14)
        self.assertEqual(res["discrepancy"]["type"], DiscrepancyType.SHORTAGE.value)
        self.assertEqual(res["discrepancy"]["delta"], -6)
        self.assertEqual(res["discrepancy"]["recommendation"], CycleCountRecommendation.ADJUST_INVENTORY_SHORTAGE.value)
        self.assertTrue(res["discrepancy"]["is_action_required"])
        self.assertEqual(res["discrepancy"]["suggested_cycle_count_qty"], 14)

    # ========================================================================
    # 3. EXCESS
    # ========================================================================
    def test_03_excess(self):
        """Vision observes more units than recorded in WMS inventory."""
        bin_id = "TEST-BIN-EXCESS"
        sku_id = "TEST-SKU-FASTENER"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-C', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'M12 Wheel Bolt Pack', 'Fasteners')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 15, 'Würth')", (bin_id, sku_id))
        conn.close()

        # Vision observes 22 units
        obs = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-C"],
            "observed_materials": [
                {
                    "sku_id": sku_id,
                    "material_type": "Fasteners",
                    "quantity": 22,
                    "identity_status": "VALIDATED",
                    "confidence": 0.96
                }
            ]
        }

        res = self.service.evaluate_bin(bin_id, observation_override=obs)
        self.assertTrue(res["success"])
        self.assertEqual(res["wms_inventory"]["total_quantity"], 15)
        self.assertEqual(res["vision_evidence"]["total_observed_qty"], 22)
        self.assertEqual(res["discrepancy"]["type"], DiscrepancyType.EXCESS.value)
        self.assertEqual(res["discrepancy"]["delta"], 7)
        self.assertEqual(res["discrepancy"]["recommendation"], CycleCountRecommendation.ADJUST_INVENTORY_EXCESS.value)
        self.assertTrue(res["discrepancy"]["is_action_required"])
        self.assertEqual(res["discrepancy"]["suggested_cycle_count_qty"], 22)

    # ========================================================================
    # 4. EMPTY BIN
    # ========================================================================
    def test_04_empty_bin(self):
        """Empty bin scenarios: missing stock vs confirmed empty bin."""
        # Scenario 4A: WMS expects 8 units, but physical bin is observed empty
        bin_id_a = "TEST-BIN-EMPTY-A"
        sku_id = "TEST-SKU-BRAKE"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-D', 'Active')", (bin_id_a,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Brake Caliper Assembly', 'Braking')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 8, 'Brembo')", (bin_id_a, sku_id))
        conn.close()

        obs_empty = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-D"],
            "observed_materials": []  # 0 items observed
        }

        res_a = self.service.evaluate_bin(bin_id_a, observation_override=obs_empty)
        self.assertEqual(res_a["wms_inventory"]["total_quantity"], 8)
        self.assertEqual(res_a["vision_evidence"]["total_observed_qty"], 0)
        self.assertEqual(res_a["discrepancy"]["type"], DiscrepancyType.EMPTY_BIN.value)
        self.assertEqual(res_a["discrepancy"]["recommendation"], CycleCountRecommendation.INVESTIGATE_MISSING_STOCK.value)
        self.assertTrue(res_a["discrepancy"]["is_action_required"])
        self.assertEqual(res_a["discrepancy"]["suggested_cycle_count_qty"], 0)

        # Scenario 4B: WMS expects 0 units, and physical bin is observed empty
        bin_id_b = "TEST-BIN-EMPTY-B"
        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-D', 'Active')", (bin_id_b,))
        conn.close()

        res_b = self.service.evaluate_bin(bin_id_b, observation_override=obs_empty)
        self.assertEqual(res_b["wms_inventory"]["total_quantity"], 0)
        self.assertEqual(res_b["vision_evidence"]["total_observed_qty"], 0)
        self.assertEqual(res_b["discrepancy"]["type"], DiscrepancyType.MATCH.value)
        self.assertEqual(res_b["discrepancy"]["recommendation"], CycleCountRecommendation.CONFIRM_EMPTY_BIN.value)
        self.assertFalse(res_b["discrepancy"]["is_action_required"])

    # ========================================================================
    # 5. UNIDENTIFIED & AMBIGUOUS MATERIAL
    # ========================================================================
    def test_05_unidentified_and_ambiguous_material(self):
        """Items detected but lacking valid barcode or having ambiguous identity."""
        bin_id = "TEST-BIN-AMBIG"
        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-E', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES ('SKU-001', 'Test SKU 001', 'General') ON CONFLICT(sku_id) DO NOTHING")
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, 'SKU-001', 5, 'Vendor')", (bin_id,))
        conn.close()

        # Case 5A: Unidentified materials (no barcode resolved)
        obs_unidentified = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-E"],
            "observed_materials": [
                {
                    "observed_id": "TRACK_CAM-001_101",
                    "material_type": "Packaged Component",
                    "quantity": 5,
                    "identity_status": "UNIDENTIFIED"
                }
            ]
        }
        res_unident = self.service.evaluate_bin(bin_id, observation_override=obs_unidentified)
        self.assertEqual(res_unident["discrepancy"]["type"], DiscrepancyType.UNIDENTIFIED_MATERIAL.value)
        self.assertEqual(res_unident["discrepancy"]["recommendation"], CycleCountRecommendation.SCAN_BARCODE_OR_MANUAL_AUDIT.value)
        self.assertTrue(res_unident["discrepancy"]["is_action_required"])

        # Case 5B: Ambiguous identity (conflicting candidate reads)
        obs_ambiguous = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-E"],
            "observed_materials": [
                {
                    "observed_id": "AMBIG_READ",
                    "material_type": "Carton",
                    "quantity": 5,
                    "identity_status": "AMBIGUOUS",
                    "is_ambiguous": True
                }
            ]
        }
        res_ambig = self.service.evaluate_bin(bin_id, observation_override=obs_ambiguous)
        self.assertEqual(res_ambig["discrepancy"]["type"], DiscrepancyType.AMBIGUOUS_IDENTITY.value)
        self.assertEqual(res_ambig["discrepancy"]["recommendation"], CycleCountRecommendation.MANUAL_VERIFICATION_REQUIRED.value)
        self.assertTrue(res_ambig["discrepancy"]["is_action_required"])

    # ========================================================================
    # 6. MULTIPLE MATERIALS (MIXED SKUS)
    # ========================================================================
    def test_06_multiple_materials(self):
        """Bin contains items belonging to multiple distinct SKUs."""
        bin_id = "TEST-BIN-MIXED"
        sku_1 = "TEST-SKU-GLASS-1"
        sku_2 = "TEST-SKU-ROD-2"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-F', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Rear Windshield', 'Automotive Glass')", (sku_1,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Connecting Rod', 'Engine Parts')", (sku_2,))
            # WMS expects single SKU-1
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 10, 'Pilkington')", (bin_id, sku_1))
        conn.close()

        # Physical observation contains both SKU-1 and SKU-2
        obs_mixed = {
            "has_vision_evidence": True,
            "monitoring_cameras": ["CAM-ZONE-F"],
            "observed_materials": [
                {
                    "sku_id": sku_1,
                    "material_type": "Automotive Glass",
                    "quantity": 6,
                    "identity_status": "VALIDATED"
                },
                {
                    "sku_id": sku_2,
                    "material_type": "Engine Parts",
                    "quantity": 4,
                    "identity_status": "VALIDATED"
                }
            ]
        }

        res = self.service.evaluate_bin(bin_id, observation_override=obs_mixed)
        self.assertEqual(res["discrepancy"]["type"], DiscrepancyType.MULTIPLE_MATERIALS.value)
        self.assertEqual(res["discrepancy"]["recommendation"], CycleCountRecommendation.SEGREGATE_MIXED_STOCK.value)
        self.assertTrue(res["discrepancy"]["is_action_required"])
        self.assertIn(sku_1, res["vision_evidence"]["validated_skus"])
        self.assertIn(sku_2, res["vision_evidence"]["validated_skus"])

    # ========================================================================
    # 7. NO VISION EVIDENCE
    # ========================================================================
    def test_07_no_vision_evidence(self):
        """Bin without cameras, active frames, or tracked material traces."""
        bin_id = "TEST-BIN-NO-CAM"
        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-Dark', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES ('SKU-DARK', 'Dark Component', 'General') ON CONFLICT(sku_id) DO NOTHING")
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, 'SKU-DARK', 12, 'Vendor')", (bin_id,))
        conn.close()

        obs_none = {
            "has_vision_evidence": False,
            "monitoring_cameras": [],
            "observed_materials": []
        }

        res = self.service.evaluate_bin(bin_id, observation_override=obs_none)
        self.assertEqual(res["discrepancy"]["type"], DiscrepancyType.NO_VISION_EVIDENCE.value)
        self.assertEqual(res["discrepancy"]["recommendation"], CycleCountRecommendation.MANUAL_COUNT_REQUIRED.value)
        self.assertTrue(res["discrepancy"]["is_action_required"])
        self.assertIsNone(res["discrepancy"]["observed_qty"])

    # ========================================================================
    # 8. EXPLICIT CYCLE COUNT INVENTORY UPDATE & ACTIVITIES DEFECT FIX
    # ========================================================================
    def test_08_explicit_cycle_count_inventory_update(self):
        """Operator explicitly commits a cycle count adjustment, creating an activities log."""
        bin_id = "TEST-BIN-ADJUST"
        sku_id = "TEST-SKU-AXLE"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-G', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Drive Axle', 'Drivetrain')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 10, 'GKN')", (bin_id, sku_id))
        conn.close()

        # Post explicit cycle count adjustment (audited count is 8, discrepancy is -2)
        response = self.client.post("/api/cycle_count", json={
            "bin_id": bin_id,
            "actual_qty": 8,
            "notes": "Physical audit confirmed shortage of 2 units"
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("discrepancy"), -2)
        self.assertEqual(data.get("actual_qty"), 8)

        # Verify activities log recorded the audit record (fixing the activities usage defect)
        conn = db.get_db()
        row = conn.execute("SELECT quantity FROM inventory WHERE bin_id = ?", (bin_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["quantity"], 8)

        acts = db.get_activities(limit=10)
        matching_acts = [a for a in acts if a.get("target") == bin_id]
        self.assertTrue(len(matching_acts) > 0)
        self.assertEqual(matching_acts[0]["action"], "CYCLE_COUNT_AUDIT")
        self.assertIn("-2", matching_acts[0]["details"])

    # ========================================================================
    # 9. PASSIVE AI PROCESSING NEVER MUTATES INVENTORY
    # ========================================================================
    def test_09_passive_ai_processing_never_changes_inventory(self):
        """Evaluating AI discrepancies via audit API never alters inventory or activities."""
        bin_id = "TEST-BIN-PASSIVE"
        sku_id = "TEST-SKU-INVARIANT"

        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO bins (bin_id, zone, status) VALUES (?, 'Zone-H', 'Active')", (bin_id,))
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES (?, 'Headlight Unit', 'Lighting')", (sku_id,))
            conn.execute("INSERT INTO inventory (bin_id, sku_id, quantity, vendor) VALUES (?, ?, 25, 'Valeo')", (bin_id, sku_id))
        conn.close()

        # Capture initial database state
        conn = db.get_db()
        inv_before = conn.execute("SELECT id, bin_id, sku_id, quantity FROM inventory WHERE bin_id = ?", (bin_id,)).fetchall()
        conn.close()
        acts_before = len([a for a in db.get_activities(limit=100) if a.get("target") == bin_id])

        # Run multiple passive evaluation cycles with conflicting physical counts
        for simulated_qty in [5, 50, 0, 100]:
            resp = self.client.post(f"/api/cycle_count/audit/{bin_id}/simulate", json={
                "has_vision_evidence": True,
                "observed_materials": [
                    {
                        "sku_id": sku_id,
                        "material_type": "Lighting",
                        "quantity": simulated_qty,
                        "identity_status": "VALIDATED"
                    }
                ]
            })
            self.assertEqual(resp.status_code, 200)

        # Verify database state is 100% identical
        conn = db.get_db()
        inv_after = conn.execute("SELECT id, bin_id, sku_id, quantity FROM inventory WHERE bin_id = ?", (bin_id,)).fetchall()
        conn.close()
        acts_after = len([a for a in db.get_activities(limit=100) if a.get("target") == bin_id])

        self.assertEqual(len(inv_before), len(inv_after))
        self.assertEqual(inv_before[0]["quantity"], 25)
        self.assertEqual(inv_after[0]["quantity"], 25)
        self.assertEqual(acts_before, acts_after)

    # ========================================================================
    # 10. MATERIAL-AGNOSTIC AUTOMOTIVE COMPONENT SUPPORT
    # ========================================================================
    def test_10_material_agnostic_automotive_support(self):
        """Validates automotive material types (glass, rods, fasteners) against SKU master."""
        conn = db.get_db()
        with conn:
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES ('AUTO-GLASS-01', 'Laminated Windshield', 'Automotive Glass') ON CONFLICT(sku_id) DO NOTHING")
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES ('AUTO-ROD-01', 'High-Tensile Tie Rod', 'Steering & Suspension') ON CONFLICT(sku_id) DO NOTHING")
            conn.execute("INSERT INTO skus (sku_id, name, category) VALUES ('AUTO-BOLT-01', 'Grade 10.9 Flange Bolt', 'Fasteners') ON CONFLICT(sku_id) DO NOTHING")
        conn.close()

        # Test validation for non-box object classes
        val_glass = self.validator.validate_object(class_code="GLASS", identity_value="AUTO-GLASS-01")
        self.assertEqual(val_glass["status"], "VALIDATED")
        self.assertEqual(val_glass["master_record"]["category"], "Automotive Glass")

        val_rod = self.validator.validate_object(class_code="ROD", identity_value="AUTO-ROD-01")
        self.assertEqual(val_rod["status"], "VALIDATED")
        self.assertEqual(val_rod["master_record"]["category"], "Steering & Suspension")

        val_bolt = self.validator.validate_object(class_code="FASTENER", identity_value="AUTO-BOLT-01")
        self.assertEqual(val_bolt["status"], "VALIDATED")
        self.assertEqual(val_bolt["master_record"]["category"], "Fasteners")


if __name__ == "__main__":
    unittest.main()
