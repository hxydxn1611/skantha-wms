"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 14 — System Integration & Orchestration Backend Verification Suite

Comprehensive deterministic test suite covering:
1. Integration service initialization & singleton access
2. Dock to Vision Zone code normalization
3. Dock to authoritative vision zone resolution
4. Zone to physical camera resolution
5. Inbound Delivery Cross-Module Context resolution (PO -> GP -> Truck -> Dock -> Zone -> Cameras -> Materials)
6. Delivery Context error handling (non-existent PO)
7. Gate Pass Cross-Module Context resolution (GP -> PO -> Vehicle -> Dock -> Zone -> Cameras -> Materials)
8. Gate Pass Context error handling (non-existent GP)
9. Dock Operational Context resolution
10. Bin Context & Putaway Evidence (Read-only observation evidence)
11. Bin Context error handling (non-existent Bin)
12. Camera Cross-Module Context (Hardware master + AI Config + Assigned Zones + ROIs)
13. Camera Context error handling (non-existent Camera)
14. Enriched Material Traceability Dossier with WMS Master references (SKU, PO, GP, Truck, Worker, Bin)
15. Incomplete material dossier handling (honest None / UNKNOWN representation, no fabrication)
16. Non-existent material dossier error handling
17. Unified Dashboard Overview (WMS KPIs + Vision Telemetry + Inbound Stream)
18. End-to-End deterministic synthetic scenario (10 audit steps all PASS)
19. REST API GET /api/integration/overview
20. REST API GET /api/integration/delivery/<po_number> (200 & 404)
21. REST API GET /api/integration/gate_pass/<gp_id> (200 & 404)
22. REST API GET /api/integration/material/<material_id> (200 & 404)
23. REST API GET /api/integration/dock/<dock_name> (200)
24. REST API GET /api/integration/bin/<bin_id> (200 & 404)
25. REST API GET /api/integration/camera/<camera_id> (200 & 404)
26. REST API POST /api/integration/e2e/test_scenario (200)
27. Strict Inventory Governance: ZERO database mutations to inventory ledger
"""

import os
import sys
import json
import sqlite3
import unittest

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(WORKSPACE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import app as flask_app_module
from integration_service import (
    WmsVisionIntegrationService,
    get_integration_service
)
from material_traceability_service import (
    get_material_traceability_service,
    TraceabilityLevel,
    MaterialTraceStatus
)

DB_PATH = os.path.join(WEBAPP_DIR, "skandha_wms.db")


class TestSystemIntegrationBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = flask_app_module.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.integration_svc = get_integration_service()
        cls.traceability_svc = get_material_traceability_service()

        # Seed synthetic traceability data for testing
        cls.traceability_svc.run_synthetic_sequence("e2e_integration_scenario")

    def get_inventory_count(self):
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()
        return count

    # ------------------------------------------------------------------------
    # 1. Service Init & Singleton
    # ------------------------------------------------------------------------
    def test_01_service_init_and_singleton(self):
        svc = get_integration_service()
        self.assertIsNotNone(svc)
        self.assertIsInstance(svc, WmsVisionIntegrationService)
        svc2 = get_integration_service()
        self.assertIs(svc, svc2)

    # ------------------------------------------------------------------------
    # 2. Dock Zone Code Normalization
    # ------------------------------------------------------------------------
    def test_02_normalize_dock_zone_code(self):
        norm = WmsVisionIntegrationService.normalize_dock_zone_code
        self.assertEqual(norm("Dock 1"), "DOCK-01")
        self.assertEqual(norm("dock 1"), "DOCK-01")
        self.assertEqual(norm("DOCK-1"), "DOCK-01")
        self.assertEqual(norm("DOCK1"), "DOCK-01")
        self.assertEqual(norm("Dock 2"), "DOCK-02")
        self.assertEqual(norm("Dock 3"), "DOCK-03")
        self.assertIsNone(norm(None))
        self.assertIsNone(norm(""))

    # ------------------------------------------------------------------------
    # 3. Resolve Zone for Dock
    # ------------------------------------------------------------------------
    def test_03_resolve_zone_for_dock(self):
        zone1 = self.integration_svc.resolve_zone_for_dock("Dock 1")
        self.assertIsNotNone(zone1)
        self.assertEqual(zone1.get("zone_code"), "DOCK-01")

        zone2 = self.integration_svc.resolve_zone_for_dock("Dock 2")
        self.assertIsNotNone(zone2)
        self.assertEqual(zone2.get("zone_code"), "DOCK-02")

        invalid_zone = self.integration_svc.resolve_zone_for_dock("Dock 999")
        self.assertIsNone(invalid_zone)

        unassigned = self.integration_svc.resolve_zone_for_dock("Not Assigned")
        self.assertIsNone(unassigned)

    # ------------------------------------------------------------------------
    # 4. Get Cameras for Zone
    # ------------------------------------------------------------------------
    def test_04_get_cameras_for_zone(self):
        zone1 = self.integration_svc.resolve_zone_for_dock("Dock 1")
        self.assertIsNotNone(zone1)
        cams = self.integration_svc.get_cameras_for_zone(zone1["id"])
        self.assertIsInstance(cams, list)
        self.assertGreaterEqual(len(cams), 1)
        cam_ids = [c["camera_id"] for c in cams]
        self.assertTrue("CAM-001" in cam_ids or "CAM-002" in cam_ids)

    # ------------------------------------------------------------------------
    # 5. Delivery Cross-Module Context
    # ------------------------------------------------------------------------
    def test_05_delivery_context(self):
        ctx = self.integration_svc.get_delivery_context("PO-8821")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["po_number"], "PO-8821")
        self.assertEqual(ctx["vendor"], "Acme Logistics")
        self.assertIsNotNone(ctx["gate_pass"])
        self.assertEqual(ctx["gate_pass"]["id"], "GP-1000")
        self.assertEqual(ctx["assigned_dock"], "Dock 1")
        self.assertIsNotNone(ctx["vision_zone"])
        self.assertEqual(ctx["vision_zone"]["zone_code"], "DOCK-01")
        self.assertGreaterEqual(len(ctx["monitoring_cameras"]), 1)
        self.assertIsInstance(ctx["items"], list)
        self.assertGreaterEqual(len(ctx["items"]), 1)

    # ------------------------------------------------------------------------
    # 6. Delivery Context Not Found
    # ------------------------------------------------------------------------
    def test_06_delivery_context_not_found(self):
        ctx = self.integration_svc.get_delivery_context("PO-NONEXISTENT-999")
        self.assertIsNone(ctx)

    # ------------------------------------------------------------------------
    # 7. Gate Pass Cross-Module Context
    # ------------------------------------------------------------------------
    def test_07_gate_pass_context(self):
        ctx = self.integration_svc.get_gate_pass_context("GP-1000")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["gate_pass"]["id"], "GP-1000")
        self.assertEqual(ctx["gate_pass"]["po_number"], "PO-8821")
        self.assertEqual(ctx["gate_pass"]["plate"], "MH-12-AB-1234")
        self.assertIsNotNone(ctx["delivery"])
        self.assertEqual(ctx["assigned_dock"], "Dock 1")
        self.assertIsNotNone(ctx["vision_zone"])
        self.assertEqual(ctx["vision_zone"]["zone_code"], "DOCK-01")
        self.assertGreaterEqual(len(ctx["monitoring_cameras"]), 1)

    # ------------------------------------------------------------------------
    # 8. Gate Pass Context Not Found
    # ------------------------------------------------------------------------
    def test_08_gate_pass_context_not_found(self):
        ctx = self.integration_svc.get_gate_pass_context("GP-UNKNOWN-999")
        self.assertIsNone(ctx)

    # ------------------------------------------------------------------------
    # 9. Dock Operational Context
    # ------------------------------------------------------------------------
    def test_09_dock_context(self):
        ctx = self.integration_svc.get_dock_context("Dock 1")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["dock_name"], "Dock 1")
        self.assertIsNotNone(ctx["vision_zone"])
        self.assertEqual(ctx["vision_zone"]["zone_code"], "DOCK-01")
        self.assertGreaterEqual(len(ctx["cameras"]), 1)
        self.assertIsInstance(ctx["assigned_passes"], list)

    # ------------------------------------------------------------------------
    # 10. Bin Context & Putaway Evidence
    # ------------------------------------------------------------------------
    def test_10_bin_context(self):
        ctx = self.integration_svc.get_bin_context("BIN-A101")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["bin"]["bin_id"], "BIN-A101")
        self.assertIsInstance(ctx["inventory"], list)
        self.assertIsInstance(ctx["observed_materials"], list)

    # ------------------------------------------------------------------------
    # 11. Bin Context Not Found
    # ------------------------------------------------------------------------
    def test_11_bin_context_not_found(self):
        ctx = self.integration_svc.get_bin_context("BIN-NONEXISTENT")
        self.assertIsNone(ctx)

    # ------------------------------------------------------------------------
    # 12. Camera Cross-Module Context
    # ------------------------------------------------------------------------
    def test_12_camera_context(self):
        ctx = self.integration_svc.get_camera_context("CAM-002")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["camera"]["camera_id"], "CAM-002")
        self.assertIsNotNone(ctx["ai_config"])
        self.assertIsInstance(ctx["assigned_zones"], list)
        self.assertIsInstance(ctx["rois"], list)

    # ------------------------------------------------------------------------
    # 13. Camera Context Not Found
    # ------------------------------------------------------------------------
    def test_13_camera_context_not_found(self):
        ctx = self.integration_svc.get_camera_context("CAM-NONEXISTENT-999")
        self.assertIsNone(ctx)

    # ------------------------------------------------------------------------
    # 14. Enriched Material Dossier with WMS References
    # ------------------------------------------------------------------------
    def test_14_enriched_material_dossier(self):
        dossier = self.integration_svc.get_enriched_material_dossier("B104")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["material_id"], "B104")
        self.assertIn("wms_references", dossier)
        refs = dossier["wms_references"]

        # Check WMS bindings
        self.assertIsNotNone(refs.get("gate_pass"))
        self.assertEqual(refs["gate_pass"]["id"], "GP-1000")
        self.assertEqual(refs["truck_plate"], "MH-12-AB-1234")
        self.assertIsNotNone(refs.get("worker"))
        self.assertIsNotNone(refs.get("bin"))
        self.assertEqual(refs["bin"]["bin_id"], "BIN-A101")
        self.assertIsNotNone(refs.get("putaway_evidence"))
        self.assertIn(refs["putaway_evidence"]["status"], ("OBSERVED_AT_BIN", "IN_TRANSIT", "AT_INTERMEDIATE_ZONE", "UNVERIFIED"))
        self.assertEqual(refs["putaway_evidence"]["evidence_state"], "OBSERVED_NOT_COMMITTED")

    # ------------------------------------------------------------------------
    # 15. Incomplete Material Dossier Handling
    # ------------------------------------------------------------------------
    def test_15_incomplete_material_dossier(self):
        # Ingest an incomplete material with only track level info
        self.traceability_svc.ingest_movement_event({
            "event_id": "EVT-TEST-INCOMPLETE-999",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "primary_object": {"track_id": 999, "class_code": "BOX", "identity_id": None, "identity_status": "UNIDENTIFIED"},
            "zone": {"zone_id": 1, "zone_code": "GENERAL", "zone_name": "General Area"},
            "confidence": 0.8
        })
        dossier = self.integration_svc.get_enriched_material_dossier("TRACK_CAM-001_999")
        self.assertIsNotNone(dossier)
        refs = dossier["wms_references"]
        # Honest representation: missing references should be None, not fabricated
        self.assertIsNone(refs.get("gate_pass"))
        self.assertIsNone(refs.get("delivery"))
        self.assertEqual(refs["putaway_evidence"]["status"], "AT_INTERMEDIATE_ZONE")
        self.assertIsNone(refs["putaway_evidence"]["observed_bin"])

    # ------------------------------------------------------------------------
    # 16. Non-Existent Material Dossier
    # ------------------------------------------------------------------------
    def test_16_nonexistent_material_dossier(self):
        dossier = self.integration_svc.get_enriched_material_dossier("NON-EXISTENT-XYZ")
        self.assertIsNone(dossier)

    # ------------------------------------------------------------------------
    # 17. Unified Dashboard Overview
    # ------------------------------------------------------------------------
    def test_17_unified_overview(self):
        overview = self.integration_svc.get_unified_overview()
        self.assertIn("wms_kpis", overview)
        self.assertIn("vision_kpis", overview)
        self.assertIn("inbound_stream", overview)

        wms = overview["wms_kpis"]
        self.assertIn("total_expected", wms)
        self.assertIn("total_arrived", wms)
        self.assertIn("pending_dock", wms)
        self.assertIn("at_dock", wms)

        vis = overview["vision_kpis"]
        self.assertGreaterEqual(vis["total_cameras"], 1)
        self.assertGreaterEqual(vis["traceability_records"], 1)

        stream = overview["inbound_stream"]
        self.assertIsInstance(stream, list)

    # ------------------------------------------------------------------------
    # 18. End-to-End Synthetic Scenario
    # ------------------------------------------------------------------------
    def test_18_e2e_synthetic_scenario(self):
        inv_before = self.get_inventory_count()
        res = self.integration_svc.run_e2e_integration_scenario("PO-8821")
        inv_after = self.get_inventory_count()

        self.assertTrue(res["success"])
        self.assertEqual(len(res["steps"]), 10)
        for step in res["steps"]:
            self.assertEqual(step["status"], "PASS")

        gov = res["inventory_governance"]
        self.assertTrue(gov["compliant"])
        self.assertEqual(gov["inventory_mutations"], 0)
        self.assertEqual(inv_before, inv_after)

    # ------------------------------------------------------------------------
    # 19. REST API: GET /api/integration/overview
    # ------------------------------------------------------------------------
    def test_19_api_overview(self):
        resp = self.client.get("/api/integration/overview")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIn("data", data)
        self.assertIn("wms_kpis", data["data"])

    # ------------------------------------------------------------------------
    # 20. REST API: GET /api/integration/delivery/<po_number>
    # ------------------------------------------------------------------------
    def test_20_api_delivery(self):
        resp = self.client.get("/api/integration/delivery/PO-8821")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["po_number"], "PO-8821")

        resp_404 = self.client.get("/api/integration/delivery/PO-FAKE-999")
        self.assertEqual(resp_404.status_code, 404)

    # ------------------------------------------------------------------------
    # 21. REST API: GET /api/integration/gate_pass/<gp_id>
    # ------------------------------------------------------------------------
    def test_21_api_gate_pass(self):
        resp = self.client.get("/api/integration/gate_pass/GP-1000")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["gate_pass"]["id"], "GP-1000")

        resp_404 = self.client.get("/api/integration/gate_pass/GP-FAKE-999")
        self.assertEqual(resp_404.status_code, 404)

    # ------------------------------------------------------------------------
    # 22. REST API: GET /api/integration/material/<material_id>
    # ------------------------------------------------------------------------
    def test_22_api_material(self):
        resp = self.client.get("/api/integration/material/B104")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["material_id"], "B104")

        resp_404 = self.client.get("/api/integration/material/MATERIAL-FAKE-999")
        self.assertEqual(resp_404.status_code, 404)

    # ------------------------------------------------------------------------
    # 23. REST API: GET /api/integration/dock/<dock_name>
    # ------------------------------------------------------------------------
    def test_23_api_dock(self):
        resp = self.client.get("/api/integration/dock/Dock%201")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["dock_name"], "Dock 1")

    # ------------------------------------------------------------------------
    # 24. REST API: GET /api/integration/bin/<bin_id>
    # ------------------------------------------------------------------------
    def test_24_api_bin(self):
        resp = self.client.get("/api/integration/bin/BIN-A101")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["bin"]["bin_id"], "BIN-A101")

        resp_404 = self.client.get("/api/integration/bin/BIN-FAKE-999")
        self.assertEqual(resp_404.status_code, 404)

    # ------------------------------------------------------------------------
    # 25. REST API: GET /api/integration/camera/<camera_id>
    # ------------------------------------------------------------------------
    def test_25_api_camera(self):
        resp = self.client.get("/api/integration/camera/CAM-002")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["camera"]["camera_id"], "CAM-002")

        resp_404 = self.client.get("/api/integration/camera/CAM-FAKE-999")
        self.assertEqual(resp_404.status_code, 404)

    # ------------------------------------------------------------------------
    # 26. REST API: POST /api/integration/e2e/test_scenario
    # ------------------------------------------------------------------------
    def test_26_api_e2e_scenario(self):
        resp = self.client.post("/api/integration/e2e/test_scenario", json={"po_number": "PO-8821"})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertIn("steps", data)
        self.assertEqual(len(data["steps"]), 10)

    # ------------------------------------------------------------------------
    # 27. Strict Inventory Governance: 0 mutations
    # ------------------------------------------------------------------------
    def test_27_strict_inventory_governance(self):
        conn = sqlite3.connect(DB_PATH)
        inv_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        # Call multiple integration methods that query or correlate data
        self.integration_svc.get_unified_overview()
        self.integration_svc.get_delivery_context("PO-8821")
        self.integration_svc.get_gate_pass_context("GP-1000")
        self.integration_svc.get_enriched_material_dossier("B104")
        self.integration_svc.get_bin_context("BIN-A101")
        self.integration_svc.run_e2e_integration_scenario("PO-8821")

        conn = sqlite3.connect(DB_PATH)
        inv_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()

        self.assertEqual(inv_before, inv_after, "Inventory count MUST remain strictly untouched!")
        self.assertEqual(inv_after, 0, "Inventory table must remain at 0 rows")


if __name__ == "__main__":
    unittest.main()
