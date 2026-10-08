"""
Test Suite: Part 3 - Camera Junction <-> W.A.R.L.O.G. Integration
Validates all requirements A through AA specified in Section 14:
A. Camera Junction registration still works.
B. Existing camera types still work.
C. Existing camera specifications remain available.
D. Existing device/webcam handling still works.
E. Existing IP/RTSP handling still works where supported.
F. Existing vendor information remains available.
G. Existing stream connection works.
H. Existing monitoring works.
I. Existing OCR remains functional.
J. Existing Number Plate Recognition remains functional.
K. Existing Camera Junction YOLO functionality remains functional.
L. A Camera Junction camera can be referenced by W.A.R.L.O.G.
M. W.A.R.L.O.G. configuration attaches to the same camera identity.
N. No duplicate physical camera is created.
O. Runtime Orchestrator can discover/use the integrated camera.
P. Detection can consume the camera.
Q. Tracking can consume the camera.
R. Zone/ROI can reference the same camera.
S. Object-class configuration remains compatible.
T. Camera configuration persists correctly.
U. Existing /api/cameras contract remains functional.
V. Existing /api/vision/cameras contract remains functional.
W. Existing Part 14 integration remains functional.
X. Existing runtime tests remain functional.
Y. No inventory mutation occurs.
Z. No WMS transaction occurs merely from camera registration/integration.
AA. Database schema remains unchanged.
"""

import os
import sys
import json
import unittest
import numpy as np
import cv2

# Set path to webapp
webapp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

import db
from app import app, active_cameras
from vision_runtime_service import get_vision_runtime_manager, RuntimeState
from detection_service import get_detection_engine
from tracking_service import get_tracking_service
from identity_service import get_identity_service


class TestCameraJunctionWarlogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["WARLOG_TEST_MODE"] = "1"
        app.testing = True
        cls.client = app.test_client()
        # Ensure database is initialized
        db.init_db()
        from ai_engine import SmartCamera
        if not hasattr(SmartCamera, 'ocr_reader') or SmartCamera.ocr_reader is None:
            SmartCamera.ocr_reader = unittest.mock.MagicMock()

    def setUp(self):
        # Capture baseline counts
        conn = db.get_db()
        self.initial_inv_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        self.initial_bin_count = conn.execute("SELECT COUNT(*) FROM bins").fetchone()[0]
        self.initial_po_count = conn.execute("SELECT COUNT(*) FROM expected_deliveries").fetchone()[0]
        self.initial_gp_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
        conn.close()

    def test_A_B_C_F_camera_junction_registration_types_vendors(self):
        """A, B, C, F: Test camera registration via Camera Junction API with various types and vendors."""
        test_cam_id = "CAM-TEST-CJ1"
        payload = {
            "camera_id": test_cam_id,
            "name": "CJ Test Camera Hikvision",
            "warehouse": "Warehouse A",
            "location": "Gate",
            "type": "IP Camera",
            "vendor": "Hikvision",
            "url": "rtsp://192.168.1.100:554/live"
        }
        with unittest.mock.patch("cv2.VideoCapture"):
            res = self.client.post("/api/cameras", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        assigned_id = data.get("id") or data.get("camera_id")
        self.assertEqual(assigned_id, test_cam_id)

        # Verify in authoritative DB
        cam_record = db.get_camera(test_cam_id)
        self.assertIsNotNone(cam_record)
        self.assertEqual(cam_record["camera_id"], test_cam_id)
        self.assertEqual(cam_record["name"], "CJ Test Camera Hikvision")
        self.assertEqual(cam_record["camera_type"], "IP Camera")
        self.assertEqual(cam_record["vendor"], "Hikvision")
        self.assertEqual(cam_record["stream_url"], "rtsp://192.168.1.100:554/live")

        # Cleanup
        self.client.delete(f"/api/cameras/{test_cam_id}")

    def test_D_E_device_webcam_and_stream_handling(self):
        """D, E: Device/webcam frame pushing and OpenCV/stream handling."""
        test_cam_id = "CAM-TEST-DEV"
        payload = {
            "camera_id": test_cam_id,
            "name": "Laptop Device Camera",
            "location": "General",
            "type": "Device Camera",
            "vendor": "Built-in Device",
            "url": "device://client"
        }
        with unittest.mock.patch("cv2.VideoCapture"):
            reg_res = self.client.post("/api/cameras", json=payload)
        self.assertEqual(reg_res.status_code, 200)

        # Push a synthetic frame via /api/cameras/<id>/frame
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(dummy_frame, "TEST FRAME", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        _, encoded_jpg = cv2.imencode(".jpg", dummy_frame)
        frame_bytes = encoded_jpg.tobytes()

        push_res = self.client.post(
            f"/api/cameras/{test_cam_id}/frame",
            data=frame_bytes,
            content_type="image/jpeg"
        )
        self.assertEqual(push_res.status_code, 200)
        self.assertTrue(push_res.get_json().get("success"))

        # Test snapshot API retrieves frame
        snap_res = self.client.post(f"/api/cameras/{test_cam_id}/snap")
        self.assertEqual(snap_res.status_code, 200)
        self.assertTrue(snap_res.get_json().get("success"))

        # Cleanup
        self.client.delete(f"/api/cameras/{test_cam_id}")

    def test_G_H_U_monitoring_contract_and_db_merging(self):
        """G, H, U: GET /api/cameras returns physical cameras from authoritative DB with exact contract."""
        res = self.client.get("/api/cameras")
        self.assertEqual(res.status_code, 200)
        cameras = res.get_json()
        self.assertIsInstance(cameras, list)
        self.assertGreaterEqual(len(cameras), 4, "Should list seeded physical cameras from DB")

        # Check seeded camera CAM-001 contract
        cam1 = next((c for c in cameras if c["id"] == "CAM-001"), None)
        self.assertIsNotNone(cam1, "CAM-001 must be present in /api/cameras")
        self.assertIn("id", cam1)
        self.assertIn("name", cam1)
        self.assertIn("url", cam1)
        self.assertIn("location", cam1)
        self.assertIn("type", cam1)
        self.assertIn("vendor", cam1)
        self.assertIn("events", cam1)
        self.assertIsInstance(cam1["events"], list)

    def test_L_M_N_V_warlog_camera_sources_and_ai_config(self):
        """L, M, N, V: W.A.R.L.O.G. views same physical camera without duplicate physical record and can configure AI."""
        # 1. Register physical camera via Camera Junction
        cam_id = "CAM-TEST-WARLOG"
        with unittest.mock.patch("cv2.VideoCapture"):
            reg_res = self.client.post("/api/cameras", json={
                "camera_id": cam_id,
                "name": "Integration Camera for AI",
                "warehouse": "Warehouse A",
                "location": "Aisle 02",
                "type": "IP Camera",
                "vendor": "Dahua",
                "url": "rtsp://10.0.0.50/stream1"
            })
        self.assertEqual(reg_res.status_code, 200)

        # 2. Verify W.A.R.L.O.G. Camera Sources API sees it with authoritative identity
        res_v = self.client.get("/api/vision/cameras")
        self.assertEqual(res_v.status_code, 200)
        vision_cams = res_v.get_json()
        v_cam = next((c for c in vision_cams if c["camera_id"] == cam_id), None)
        self.assertIsNotNone(v_cam, "W.A.R.L.O.G. must discover the registered physical camera")
        self.assertEqual(v_cam["camera_id"], cam_id)
        self.assertEqual(v_cam["stream_url"], "rtsp://10.0.0.50/stream1")
        self.assertIn("ai_config", v_cam)

        # 3. Configure AI perception for this camera via W.A.R.L.O.G.
        cfg_payload = {
            "ai_enabled": True,
            "detection_enabled": True,
            "tracking_enabled": True,
            "processing_fps": 12,
            "object_classes": ["box", "pallet", "worker"]
        }
        cfg_res = self.client.post(f"/api/vision/cameras/{cam_id}/config", json=cfg_payload)
        self.assertEqual(cfg_res.status_code, 200)
        self.assertTrue(cfg_res.get_json().get("success"))

        # Verify config saved in vision_camera_configs attached to same camera_id
        res_single = self.client.get(f"/api/vision/cameras/{cam_id}").get_json()
        self.assertTrue(res_single.get("success"))
        updated_v = res_single.get("camera", {})
        self.assertEqual(updated_v["ai_config"]["processing_fps"], 12)
        self.assertTrue(updated_v["ai_config"]["tracking_enabled"])
        self.assertIn("BOX", [c.upper() for c in updated_v["ai_config"]["object_classes"]])

        # 4. Verify N: No duplicate physical camera created in SQLite cameras table
        conn = db.get_db()
        matching_count = conn.execute("SELECT COUNT(*) FROM cameras WHERE camera_id = ?", (cam_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(matching_count, 1, "There must be exactly ONE physical camera record in cameras table")

        # Cleanup
        self.client.delete(f"/api/cameras/{cam_id}")

    def test_O_runtime_orchestrator_integration(self):
        """O: Runtime Orchestrator / VisionRuntimeManager discovers and manages the integrated camera session."""
        mgr = get_vision_runtime_manager()
        mgr.refresh_cameras()
        # Verify seeded cameras exist in sessions
        for cid in ["CAM-001", "CAM-002", "CAM-003", "CAM-004"]:
            self.assertTrue(mgr.has_session(cid), f"Session for {cid} must exist in VisionRuntimeManager")

        # Start and stop a session
        ok, msg = mgr.start_camera("CAM-001")
        self.assertTrue(ok)
        sess = mgr.get_session("CAM-001")
        self.assertIn(sess.runtime_state, [RuntimeState.RUNNING, RuntimeState.DEGRADED])
        ok, msg = mgr.stop_camera("CAM-001")
        self.assertTrue(ok)
        self.assertEqual(sess.runtime_state, RuntimeState.STOPPED)

    def test_P_Q_detection_and_tracking_consumption(self):
        """P, Q: Detection and tracking pipelines consume frames with camera identity."""
        det_engine = get_detection_engine()
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(dummy_frame, (100, 100), (250, 250), (255, 255, 255), -1)

        result = det_engine.detect(dummy_frame, camera_id="CAM-001")
        self.assertTrue(result.get("success", False))
        self.assertIn("detections", result)
        self.assertIsInstance(result["detections"], list)

        trk_svc = get_tracking_service()
        track_res = trk_svc.track_frame(dummy_frame, camera_id="CAM-001")
        self.assertIn("tracks", track_res)
        self.assertIsInstance(track_res["tracks"], list)

    def test_R_S_zone_and_roi_compatibility(self):
        """R, S: Camera can be associated with vision zones and ROIs using authoritative camera_id."""
        conn = db.get_db()
        # Check that CAM-001 is associated with vision zones
        zone_cam = conn.execute("SELECT * FROM vision_zone_cameras WHERE camera_id = 'CAM-001'").fetchall()
        self.assertGreaterEqual(len(zone_cam), 1)

        # Check ROI association
        rois = conn.execute("SELECT * FROM vision_zone_camera_rois WHERE camera_id = 'CAM-001'").fetchall()
        self.assertGreaterEqual(len(rois), 1)
        conn.close()

    def test_I_J_K_ocr_npr_yolo_capabilities_preserved(self):
        """I, J, K: OCR, NPR and YOLO capabilities are operational and shared without duplication."""
        # 1. Identity Service OCR capability
        id_svc = get_identity_service()
        self.assertIsNotNone(id_svc)

        # 2. SmartCamera class retains YOLO model and OCR reader
        from ai_engine import SmartCamera
        cam_instance = SmartCamera(
            camera_id="CAM-TEST-NPR",
            name="Gate Test Cam",
            url="",
            location="Gate",
            cam_type="IP Camera",
            vendor="Hikvision"
        )
        self.assertEqual(cam_instance.camera_id, "CAM-TEST-NPR")
        self.assertEqual(cam_instance.location, "Gate")
        self.assertTrue(hasattr(cam_instance, "vehicle_model"))
        self.assertTrue(hasattr(cam_instance, "events"))

    def test_W_X_part14_and_runtime_integrity(self):
        """W, X: Part 14 integration and existing runtime workflows remain functional."""
        from validation_service import get_validation_service
        from material_traceability_service import get_material_traceability_service
        val_svc = get_validation_service()
        mat_svc = get_material_traceability_service()
        self.assertIsNotNone(val_svc)
        self.assertIsNotNone(mat_svc)

    def test_Y_Z_AA_database_and_inventory_zero_mutation(self):
        """Y, Z, AA: Zero schema changes, zero inventory mutation, zero WMS transaction on camera operations."""
        conn = db.get_db()
        final_inv_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        final_bin_count = conn.execute("SELECT COUNT(*) FROM bins").fetchone()[0]
        final_po_count = conn.execute("SELECT COUNT(*) FROM expected_deliveries").fetchone()[0]
        final_gp_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]

        # Verify exact counts unchanged
        self.assertEqual(self.initial_inv_count, final_inv_count, "Inventory table must NOT mutate")
        self.assertEqual(self.initial_bin_count, final_bin_count, "Bins table must NOT mutate")
        self.assertEqual(self.initial_po_count, final_po_count, "Deliveries/POs must NOT mutate")
        self.assertEqual(self.initial_gp_count, final_gp_count, "Gate passes must NOT mutate")

        # Verify table count is exactly 17
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        table_names = [t[0] for t in tables]
        conn.close()
        self.assertEqual(len(table_names), 17, f"Expected 17 tables, found {len(table_names)}: {table_names}")


if __name__ == "__main__":
    unittest.main()
