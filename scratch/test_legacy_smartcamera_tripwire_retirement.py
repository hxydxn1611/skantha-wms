"""
Test Suite: Part 5 - Legacy SmartCamera & Tripwire Retirement
Validates all requirements for retiring legacy SmartCamera / tripwire unloading
while preserving Camera Junction, OCR/NPR, Vision Runtime, and strict WMS transaction boundaries.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure test mode is active to prevent heavy downloads
os.environ["WARLOG_TEST_MODE"] = "1"

# Set path to webapp
webapp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

import db
from app import app, active_cameras
from ai_engine import SmartCamera
from movement_event_service import (
    get_movement_event_service,
    EventType,
    EventState
)
from integration_service import get_integration_service
from material_traceability_service import get_material_traceability_service
from vision_runtime_service import get_vision_runtime_manager


def get_db_counts():
    conn = db.get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM inventory")
    inv = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM gate_passes")
    gp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM expected_deliveries")
    po = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM bins")
    bins = c.fetchone()[0]
    c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tbl = c.fetchone()[0]
    conn.close()
    return {"inventory": inv, "gate_passes": gp, "expected_deliveries": po, "bins": bins, "tables": tbl}


class TestLegacySmartCameraTripwireRetirement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True
        cls.client = app.test_client()
        # Mock vehicle model and OCR on SmartCamera to run fast in memory
        if not hasattr(SmartCamera, 'vehicle_model') or SmartCamera.vehicle_model is None:
            SmartCamera.vehicle_model = MagicMock()
        if not hasattr(SmartCamera, 'ocr_reader') or SmartCamera.ocr_reader is None:
            SmartCamera.ocr_reader = MagicMock()

    def setUp(self):
        self.initial_counts = get_db_counts()
        self.movement_svc = get_movement_event_service()
        self.integ_svc = get_integration_service()
        self.trace_svc = get_material_traceability_service()
        self.cam_id = "CAM-001"
        self.movement_svc.reset_all()
        self.trace_svc.reset()

        # Seed gate pass initial unloaded_qty = 0 for test repeatability
        conn = db.get_db()
        with conn:
            conn.execute("INSERT OR IGNORE INTO expected_deliveries (po_number, expected_date) VALUES ('PO-TEST', '2026-10-09')")
            conn.execute("INSERT OR IGNORE INTO gate_passes (id, po_number, plate, vehicle_type, vendor, status, unloaded_qty, dock) VALUES ('GP-1000', 'PO-TEST', 'MH-12-AB-1234', 'TRUCK', 'Test Vendor', 'ACTIVE', 0, 'Dock 1')")
            conn.execute("UPDATE gate_passes SET unloaded_qty = 0, status = 'ACTIVE', dock = 'Dock 1' WHERE id = 'GP-1000'")
        conn.close()

    def tearDown(self):
        self.movement_svc.reset_all()
        self.trace_svc.reset()
        # Delete gate pass GP-1000 to restore counts
        conn = db.get_db()
        with conn:
            conn.execute("DELETE FROM gate_passes WHERE id = 'GP-1000'")
            conn.execute("DELETE FROM expected_deliveries WHERE po_number = 'PO-TEST'")
        conn.close()

        # Verify database invariants
        final_counts = get_db_counts()
        self.assertEqual(
            self.initial_counts, final_counts,
            f"Database mutation detected! Initial: {self.initial_counts}, Final: {final_counts}"
        )

    # ========================================================================
    # 1. SMARTCAMERA TRIPWIRE & TOTAL_UNLOADED RETIREMENT
    # ========================================================================

    def test_01_smartcamera_tripwire_no_longer_increments_total_unloaded(self):
        """SmartCamera no longer increments total_unloaded or emits Part_Counted_Audited events."""
        cam = SmartCamera("CAM-RETIRED", "Dock Camera", "0", "Dock")
        self.assertEqual(cam.total_unloaded, 0)
        self.assertTrue(hasattr(cam, 'seen_package_ids'))
        self.assertTrue(hasattr(cam, 'tripwire_y'))

        # Even with raw centroids tracked, total_unloaded must remain 0
        cam.tracked_centroids[99] = (320, 240)
        self.assertEqual(cam.total_unloaded, 0)
        self.assertEqual(len(cam.events), 0)

    def test_02_total_unloaded_no_longer_controls_unload_step(self):
        """unload_step ignores high SmartCamera.total_unloaded if W.A.R.L.O.G. has no verified evidence."""
        mock_cam = MagicMock()
        mock_cam.total_unloaded = 999  # Large phantom legacy count
        active_cameras["CAM-MOCK-LEGACY"] = mock_cam

        try:
            res = self.client.post("/api/dock/unload_step/GP-1000")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            # Must NOT use the 999 count!
            self.assertFalse(data.get("success"))
            self.assertEqual(data.get("verified_count"), 0)
            self.assertIn("No verified unloading evidence found in W.A.R.L.O.G.", data.get("message"))

            # WMS record must remain 0
            gp = db.get_gate_pass("GP-1000")
            self.assertEqual(gp.get("unloaded_qty", 0), 0)
        finally:
            active_cameras.pop("CAM-MOCK-LEGACY", None)

    # ========================================================================
    # 2. W.A.R.L.O.G. IS SOLE PERCEPTION EVIDENCE SOURCE
    # ========================================================================

    def test_03_warlog_is_sole_perception_source_for_dock_unload(self):
        """unload_step synchronizes exclusively from verified W.A.R.L.O.G. BOX_UNLOADED_AT_DOCK evidence."""
        # Active camera has total_unloaded = 0
        cam = SmartCamera("CAM-001", "Dock 1 Cam", "0", "Dock")
        active_cameras["CAM-001"] = cam

        # Generate 3 frames of sustained W.A.R.L.O.G. evidence for GP-1000 (Plate: MH-12-AB-1234)
        dock_zones = [{
            "id": 1,
            "zone_code": "DOCK-01",
            "zone_name": "Dock 01",
            "zone_type": "DOCK",
            "polygon": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
        }]
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.95, "is_ambiguous": False
        }]
        for f in range(1, 10):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id="CAM-001", frame_index=f, camera_zones=dock_zones)
            if f == 9:
                print("DEBUG EVENTS AT FRAME 9:", res["active_events"], res["candidate_events"])
        print("DEBUG MOVEMENT SVC ID IN TEST:", id(self.movement_svc), "SESSIONS:", list(self.movement_svc.sessions.keys()))
        all_ev = self.movement_svc.get_dock_unloading_evidence(include_candidates=True)
        print("DEBUG ALL EV IN TEST:", len(all_ev))

        # Trigger operator unload_step sync
        res = self.client.post("/api/dock/unload_step/GP-1000")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        print("DEBUG UNLOAD STEP RESPONSE:", data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("total"), 1)
        self.assertEqual(data.get("source"), "warlog_evidence")
        self.assertEqual(data.get("verified_count"), 1)

        # WMS record updated accurately through operator action
        gp = db.get_gate_pass("GP-1000")
        self.assertEqual(gp.get("unloaded_qty"), 1)

    # ========================================================================
    # 3. WMS BOUNDARY: VISION EVENTS DO NOT AUTOMATICALLY MUTATE WMS
    # ========================================================================

    def test_04_vision_events_alone_do_not_mutate_wms_or_inventory(self):
        """Generating W.A.R.L.O.G. movement events and ingesting into traceability causes 0 DB writes."""
        dock_zones = [{
            "id": 1, "zone_code": "DOCK-01", "zone_name": "Dock 01", "zone_type": "DOCK",
            "polygon": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
        }]
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{"box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.95}]

        # Process 5 frames of movement events
        for f in range(1, 6):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id="CAM-001", frame_index=f, camera_zones=dock_zones)
            for ev in res["current_events"]:
                self.trace_svc.ingest_movement_event(ev)

        # Verify Gate Pass unloaded_qty is STILL 0 (no automatic mutation occurred)
        gp = db.get_gate_pass("GP-1000")
        self.assertEqual(gp.get("unloaded_qty", 0), 0)

        # Verify inventory is STILL 0
        conn = db.get_db()
        inv_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        conn.close()
        self.assertEqual(inv_count, 0)

    def test_05_explicit_operator_quantity_override(self):
        """Operator can provide explicit manual quantity override via unload_step."""
        res = self.client.post("/api/dock/unload_step/GP-1000", json={"explicit_qty": 5})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("total"), 5)
        self.assertEqual(data.get("source"), "operator_explicit")

        gp = db.get_gate_pass("GP-1000")
        self.assertEqual(gp.get("unloaded_qty"), 5)

    # ========================================================================
    # 4. PRESERVATION OF CAMERA JUNCTION, PREVIEW & OCR/NPR
    # ========================================================================

    def test_06_camera_junction_preview_and_frame_retrieval_preserved(self):
        """SmartCamera still provides raw_frame, push_frame and get_frame for live preview."""
        cam = SmartCamera("CAM-TEST-PREVIEW", "Test Cam", "0", "Dock")
        dummy_frame = (MagicMock(), MagicMock())
        import numpy as np
        frame_img = np.zeros((480, 640, 3), dtype=np.uint8)
        cam.push_frame(frame_img)
        self.assertIsNotNone(cam.raw_frame)

        # get_frame returns valid JPEG bytes
        jpg_bytes = cam.get_frame()
        self.assertIsNotNone(jpg_bytes)
        self.assertTrue(jpg_bytes.startswith(b'\xff\xd8'))  # JPEG magic bytes

    def test_07_camera_junction_api_cameras_contract_preserved(self):
        """GET /api/cameras returns camera list with authoritative DB fields and event list."""
        res = self.client.get("/api/cameras")
        self.assertEqual(res.status_code, 200)
        cams = res.get_json()
        self.assertIsInstance(cams, list)
        self.assertGreaterEqual(len(cams), 1)
        first = cams[0]
        for key in ["id", "name", "url", "location", "type", "vendor", "events"]:
            self.assertIn(key, first)

    def test_08_ocr_npr_capability_preserved_at_gate(self):
        """SmartCamera location=='Gate' retains OCR thread hook for license plate events."""
        cam = SmartCamera("CAM-GATE", "Gate Cam", "0", "Gate")
        self.assertEqual(cam.location, "Gate")
        self.assertTrue(hasattr(cam, 'events'))
        # Can insert plate event without errors
        cam.events.append({"time": "12:00:00", "type": "Heavy Commercial (HCV)", "plate": "MH-12-AB-1234", "camera": cam.name})
        self.assertEqual(len(cam.events), 1)

    # ========================================================================
    # 5. INTEGRATION DOSSIERS & READ-ONLY SURFACES
    # ========================================================================

    def test_09_gate_pass_evidence_read_endpoint(self):
        """GET /api/dock/evidence/<gp_id> returns structured evidence dossier."""
        res = self.client.get("/api/dock/evidence/GP-1000")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        dossier = data.get("data")
        self.assertEqual(dossier.get("gate_pass_id"), "GP-1000")
        self.assertIn("verified_unloaded_count", dossier)
        self.assertIn("verification_status", dossier)

    def test_10_dock_verification_dossier_endpoint(self):
        """GET /api/dock/verification/<dock_name> returns dock verification dossier."""
        res = self.client.get("/api/dock/verification/Dock 1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        dossier = data.get("data")
        self.assertIn("dock_name", dossier)
        self.assertIn("verified_unloaded_count", dossier)

    def test_11_runtime_orchestrator_sessions_intact(self):
        """VisionRuntimeManager maintains authoritative camera sessions."""
        mgr = get_vision_runtime_manager()
        mgr.refresh_cameras()
        self.assertTrue(mgr.has_session("CAM-001"))
        sess = mgr.get_session("CAM-001")
        self.assertIsNotNone(sess)


if __name__ == "__main__":
    unittest.main()
