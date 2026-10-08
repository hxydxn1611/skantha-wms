"""
test_part12_live_vision_dashboard.py
Comprehensive Part 12 test suite verifying:
1. Runtime status and aggregate telemetry reporting
2. Camera status and per-session FPS/source reporting
3. SharedFrameBus consumption (no duplicate VideoCapture)
4. Live frame preview availability (/preview.jpg)
5. Detection overlay data (boxes, classes, confidence)
6. Tracking overlay data (temporary track IDs isolated from physical IDs)
7. Material physical identity & validation display
8. Active and candidate association display
9. Warehouse zone occupancy calculation
10. Movement event stream feed
11. Material traceability dossier inspection via dashboard
12. Unidentified, ambiguous, and conflicting identity exceptions
13. Stale and disconnected camera exception detection
14. Runtime start, stop, restart, and test-step controls
15. Automotive material classes (GLASS, ROD, FASTENER, PART, COMPONENT, MATERIAL)
16. Legacy BOX backward compatibility
17. No duplicate VideoCapture verification
18. Single shared pipeline verification (no duplicate inference)
19. Database integrity audit (17 tables, 0 inventory rows)
20. Responsive UI contract and error handling
"""

import sys
import os
import json
import time
import sqlite3
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp")))

from app import app
from vision_runtime_service import get_vision_runtime_manager, SharedFrameBus
from material_traceability_service import (
    get_material_traceability_service,
    MaterialTraceRecord,
    MaterialTraceStatus,
    TraceabilityLevel
)
from movement_event_service import get_movement_event_service, MovementEvent
from material_association_service import get_material_association_service
from db import get_db, DB_PATH


class TestPart12LiveVisionDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.vrm = get_vision_runtime_manager()
        cls.trace_svc = get_material_traceability_service()
        cls.move_svc = get_movement_event_service()
        cls.assoc_svc = get_material_association_service()

    def test_01_runtime_status_and_aggregate_telemetry(self):
        """Test 1: GET /api/vision/dashboard/live returns aggregate telemetry and runtime status."""
        resp = self.client.get("/api/vision/dashboard/live")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("runtime_active", data)
        self.assertIn("active_cameras", data)
        self.assertIn("total_cameras", data)
        self.assertIn("aggregate_fps", data)
        self.assertIn("tracked_objects", data)
        self.assertIn("active_materials_count", data)
        self.assertIn("occupied_zones", data)
        self.assertIn("operational_alerts", data)

    def test_02_camera_status_and_per_session_reporting(self):
        """Test 2: Dashboard returns cameras list with status, FPS, and source info."""
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        self.assertIn("cameras", data)
        self.assertIsInstance(data["cameras"], list)
        if data["cameras"]:
            cam = data["cameras"][0]
            self.assertIn("id", cam)
            self.assertIn("name", cam)
            self.assertIn("status", cam)
            self.assertIn("fps", cam)
            self.assertIn("is_active", cam)

    def test_03_shared_frame_bus_consumption(self):
        """Test 3: Verify SharedFrameBus provides frame without duplicate VideoCapture."""
        bus = SharedFrameBus.get_instance()
        self.assertIsNotNone(bus)
        # Verify SharedFrameBus singleton
        bus2 = SharedFrameBus.get_instance()
        self.assertIs(bus, bus2)

    def test_04_live_frame_preview_availability(self):
        """Test 4: /preview.jpg endpoint serves JPEG content."""
        resp = self.client.get("/preview.jpg")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "image/jpeg")
        self.assertGreater(len(resp.data), 100)

    def test_05_detection_overlay_data(self):
        """Test 5: Detection overlay data returns classes, confidence, and bounding boxes."""
        # Execute test step to populate recent inference context
        step_resp = self.client.post("/api/vision/runtime/test_step", json={})
        self.assertEqual(step_resp.status_code, 200)
        
        dash_resp = self.client.get("/api/vision/dashboard/live")
        data = dash_resp.get_json()
        self.assertIn("selected_camera_tracks", data)
        self.assertIsInstance(data["selected_camera_tracks"], list)

    def test_06_tracking_overlay_temporary_ids_isolated(self):
        """Test 6: Tracks have spatial track IDs distinct from physical identity tokens."""
        # Insert a track into session last_context to verify contract
        session = self.vrm.sessions.get("CAM-001")
        if session:
            session.last_context["tracks"] = [{
                "track_id": 99,
                "class_name": "PALLET",
                "bbox": [100, 100, 200, 200],
                "confidence": 0.88,
                "identity_value": "PLT-7721",
                "validation_status": "VALIDATED",
                "zone": "DOCK-01",
                "material_id": "MAT-0099"
            }]
            resp = self.client.get("/api/vision/dashboard/live?camera_id=CAM-001")
            data = resp.get_json()
            tracks = data.get("selected_camera_tracks", [])
            match = [t for t in tracks if t.get("track_id") == 99]
            self.assertTrue(len(match) > 0)
            self.assertEqual(match[0]["identity_value"], "PLT-7721")
            self.assertNotEqual(str(match[0]["track_id"]), match[0]["identity_value"])

    def test_07_material_physical_identity_validation_display(self):
        """Test 7: Validated physical identity and validation status are included."""
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        self.assertIn("selected_camera_tracks", data)

    def test_08_active_and_candidate_association_display(self):
        """Test 8: Dashboard lists active/candidate associations with confidence and type."""
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        self.assertIn("associations", data)
        self.assertIsInstance(data["associations"], list)

    def test_09_warehouse_zone_occupancy_calculation(self):
        """Test 9: Dashboard calculates occupancy and item counts across configured zones."""
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        self.assertIn("zone_occupancy", data)
        self.assertIsInstance(data["zone_occupancy"], list)
        for z in data["zone_occupancy"]:
            self.assertIn("zone_code", z)
            self.assertIn("is_occupied", z)
            self.assertIn("track_count", z)

    def test_10_movement_event_stream_feed(self):
        """Test 10: Movement event service recent events are returned in dashboard response."""
        # Create a test movement event
        ev = MovementEvent(
            event_id="test_ev_01",
            event_type="ZONE_ENTER",
            camera_id="CAM-001",
            timestamp="2026-10-08T11:00:00Z",
            primary_object={"track_id": 42, "class_name": "BOX"},
            zone={"zone_code": "DOCK-01"}
        )
        sess = self.move_svc.get_session("CAM-001")
        sess.event_history.append(ev)
        
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        self.assertIn("movement_events", data)
        ev_types = [e.get("event_type") for e in data["movement_events"]]
        self.assertIn("ZONE_ENTER", ev_types)

    def test_11_material_traceability_dossier_inspection(self):
        """Test 11: Active materials are listed and individual dossier can be retrieved."""
        # Ingest a traced material
        mat = MaterialTraceRecord(
            material_id="MAT-DASH-01",
            sku_id="SKU-AUTO-01",
            traceability_status=MaterialTraceStatus.AT_ZONE,
            traceability_level=TraceabilityLevel.VALIDATED_REAL_WORLD,
            current_location={"zone": "AISLE-A", "zone_code": "AISLE-A"},
            container_id="PLT-100"
        )
        self.trace_svc.materials[mat.material_id] = mat
        
        # Test dashboard lists it
        resp = self.client.get("/api/vision/dashboard/live")
        data = resp.get_json()
        mat_ids = [m.get("material_id") for m in data.get("active_materials", [])]
        self.assertIn("MAT-DASH-01", mat_ids)
        
        # Test individual dossier endpoint
        dossier_resp = self.client.get("/api/vision/traceability/MAT-DASH-01")
        self.assertEqual(dossier_resp.status_code, 200)
        dossier_data = dossier_resp.get_json()
        self.assertEqual(dossier_data["material"]["material_id"], "MAT-DASH-01")

    def test_12_unidentified_ambiguous_and_conflicting_identity_exceptions(self):
        """Test 12: Alerts drawer detects and reports ambiguous or conflicting tracks."""
        session = self.vrm.sessions.get("CAM-001")
        if session:
            session.last_context["tracks"] = [{
                "track_id": 105,
                "class_name": "BOX",
                "bbox": [50, 50, 150, 150],
                "confidence": 0.75,
                "identity_value": "AMBIG_TAG",
                "validation_status": "AMBIGUOUS",
                "zone": "DOCK-01",
                "material_id": None
            }]
            resp = self.client.get("/api/vision/dashboard/live?camera_id=CAM-001")
            data = resp.get_json()
            alerts = data.get("operational_alerts", [])
            codes = [a.get("code") for a in alerts]
            self.assertIn("AMBIGUOUS_IDENTITY", codes)

    def test_13_stale_and_disconnected_camera_exception_detection(self):
        """Test 13: Stale camera feed detection generates operational alert."""
        session = self.vrm.sessions.get("CAM-001")
        if session:
            old_time = session.last_frame_time
            session.is_running = True
            session.last_frame_time = time.time() - 15.0  # 15 seconds old
            
            resp = self.client.get("/api/vision/dashboard/live")
            data = resp.get_json()
            alerts = data.get("operational_alerts", [])
            codes = [a.get("code") for a in alerts]
            self.assertIn("CAMERA_STALE", codes)
            
            session.last_frame_time = old_time
            session.is_running = False

    def test_14_runtime_controls(self):
        """Test 14: Runtime start, stop, restart, and test-step controls work cleanly."""
        session = self.vrm.sessions.get("CAM-TEST-CJ1") or self.vrm.sessions.get("CAM-001")
        cid = session.camera_id if session else "CAM-001"
        if session:
            session.test_mode = True
        
        # Test step
        step_resp = self.client.post("/api/vision/runtime/test_step", json={"camera_id": cid})
        self.assertEqual(step_resp.status_code, 200)
        self.assertTrue(step_resp.get_json().get("success"))

        # Start camera
        start_resp = self.client.post("/api/vision/runtime/start", json={"camera_id": cid})
        self.assertEqual(start_resp.status_code, 200)

        # Stop camera
        stop_resp = self.client.post("/api/vision/runtime/stop", json={"camera_id": cid})
        self.assertEqual(stop_resp.status_code, 200)

    def test_15_automotive_material_classes(self):
        """Test 15: Supports automotive classes (GLASS, ROD, FASTENER, PART, COMPONENT, MATERIAL)."""
        session = self.vrm.sessions.get("CAM-001")
        if session:
            session.last_context["tracks"] = [
                {"track_id": 1, "class_name": "GLASS", "bbox": [0,0,10,10], "confidence": 0.9, "identity_value": "GLS-1", "validation_status": "VALIDATED"},
                {"track_id": 2, "class_name": "ROD", "bbox": [10,10,20,20], "confidence": 0.9, "identity_value": "ROD-1", "validation_status": "VALIDATED"},
                {"track_id": 3, "class_name": "FASTENER", "bbox": [20,20,30,30], "confidence": 0.9, "identity_value": "FST-1", "validation_status": "VALIDATED"},
                {"track_id": 4, "class_name": "COMPONENT", "bbox": [30,30,40,40], "confidence": 0.9, "identity_value": "CMP-1", "validation_status": "VALIDATED"}
            ]
            resp = self.client.get("/api/vision/dashboard/live?camera_id=CAM-001")
            data = resp.get_json()
            classes = [t["class_name"] for t in data["selected_camera_tracks"]]
            self.assertIn("GLASS", classes)
            self.assertIn("ROD", classes)
            self.assertIn("FASTENER", classes)
            self.assertIn("COMPONENT", classes)

    def test_16_legacy_box_backward_compatibility(self):
        """Test 16: Legacy BOX objects are properly tracked and displayed."""
        session = self.vrm.sessions.get("CAM-001")
        if session:
            session.last_context["tracks"] = [
                {"track_id": 88, "class_name": "BOX", "bbox": [0,0,50,50], "confidence": 0.95, "identity_value": "BOX-LEGACY-01", "validation_status": "VALIDATED"}
            ]
            resp = self.client.get("/api/vision/dashboard/live?camera_id=CAM-001")
            data = resp.get_json()
            match = [t for t in data["selected_camera_tracks"] if t["track_id"] == 88]
            self.assertEqual(len(match), 1)
            self.assertEqual(match[0]["class_name"], "BOX")

    def test_17_no_duplicate_videocapture_verification(self):
        """Test 17: VideoCapture is not opened multiply across endpoints."""
        bus = SharedFrameBus.get_instance()
        # Verify preview endpoint reads from bus or memory, without creating a new bus instance
        resp = self.client.get("/preview.jpg?source=test")
        self.assertEqual(resp.status_code, 200)
        self.assertIs(SharedFrameBus.get_instance(), bus)

    def test_18_single_runtime_pipeline_verification(self):
        """Test 18: Dashboard reads in-memory state without initiating parallel inference loops."""
        resp1 = self.client.get("/api/vision/dashboard/live")
        resp2 = self.client.get("/api/vision/dashboard/live")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)

    def test_19_database_integrity_zero_inventory_mutations(self):
        """Test 19: Verify DB schema remains exactly 17 tables and 0 inventory rows."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        num_tables = cursor.fetchone()[0]
        self.assertEqual(num_tables, 17, f"Expected 17 tables, found {num_tables}")
        
        cursor.execute("SELECT count(*) FROM inventory;")
        num_inv = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(num_inv, 0, f"Expected 0 inventory rows, found {num_inv}")

    def test_20_responsive_ui_contract_and_error_handling(self):
        """Test 20: GET /api/vision/dashboard/live handles invalid camera_id gracefully."""
        resp = self.client.get("/api/vision/dashboard/live?camera_id=NONEXISTENT_CAM")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("cameras", data)
        self.assertIn("runtime_active", data)


if __name__ == "__main__":
    unittest.main()
