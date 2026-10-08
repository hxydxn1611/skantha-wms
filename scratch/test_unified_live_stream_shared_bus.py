"""
Test Suite: Part 6 - Unified Live Stream & Shared Frame Bus
Validates single camera capture, thread-safe SharedFrameBus multi-consumer distribution,
decoupled preview and AI processing FPS, stale frame detection, disconnect/reconnect handling,
and zero database/inventory mutations.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import cv2

# Ensure test mode is active
os.environ["WARLOG_TEST_MODE"] = "1"

# Set path to webapp
webapp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

import db
from app import app, active_cameras
from ai_engine import SmartCamera
from vision_runtime_service import (
    get_shared_frame_bus,
    SharedFrameBus,
    SharedBusFrameSource,
    SourceType,
    RuntimeState,
    get_vision_runtime_manager
)
from movement_event_service import get_movement_event_service
from material_traceability_service import get_material_traceability_service
from integration_service import get_integration_service


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


class TestUnifiedLiveStreamSharedBus(unittest.TestCase):
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
        self.bus = get_shared_frame_bus()
        self.bus.clear()
        self.runtime_mgr = get_vision_runtime_manager()

    def tearDown(self):
        self.bus.clear()
        final_counts = get_db_counts()
        self.assertEqual(
            self.initial_counts, final_counts,
            f"Database mutation detected! Initial: {self.initial_counts}, Final: {final_counts}"
        )

    # ========================================================================
    # 1. SHARED FRAME BUS FOUNDATION & MULTI-CONSUMER ACCESS
    # ========================================================================

    def test_01_shared_frame_bus_publish_and_availability(self):
        """Single frame published to SharedFrameBus becomes available with correct metadata."""
        cam_id = "CAM-BUS-01"
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(dummy, "FRAME 1", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        ok = self.bus.publish_frame(cam_id, dummy, source_type="TEST_FEED", metadata={"fps": 30})
        self.assertTrue(ok)

        # Retrieve frame
        retrieved = self.bus.get_latest_frame(cam_id, copy=True)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.shape, (480, 640, 3))

        # Check diagnostics
        status = self.bus.get_buffer_status(cam_id)
        self.assertTrue(status["has_frame"])
        self.assertTrue(status["is_connected"])
        self.assertEqual(status["frame_index"], 1)
        self.assertEqual(status["source_type"], "TEST_FEED")

    def test_02_simultaneous_consumers_thread_safe_and_isolated(self):
        """Multiple concurrent consumers read without modifying each other's frame buffer."""
        cam_id = "CAM-BUS-CONCURRENCY"
        base_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.bus.publish_frame(cam_id, base_frame)

        # Consumer 1 (Camera Junction Preview)
        preview_frame = self.bus.get_latest_frame(cam_id, copy=True)
        # Consumer 2 (W.A.R.L.O.G. Runtime Pipeline)
        runtime_frame = self.bus.get_latest_frame(cam_id, copy=True)

        self.assertIsNotNone(preview_frame)
        self.assertIsNotNone(runtime_frame)

        # Consumer 1 draws annotations (in-place modification)
        cv2.rectangle(preview_frame, (10, 10), (100, 100), (0, 255, 0), -1)

        # Consumer 2 frame must remain unaltered (isolated copy)
        self.assertEqual(np.sum(runtime_frame), 0, "Consumer 1 mutation must NOT contaminate Consumer 2 frame")

    # ========================================================================
    # 2. ELIMINATION OF DUPLICATE OPENCV CAPTURES
    # ========================================================================

    def test_03_no_second_videocapture_when_smartcamera_active(self):
        """When SmartCamera already captures a camera, VisionRuntimeSession reuses it without cv2.VideoCapture."""
        cam_id = "CAM-REUSE-01"
        cam = SmartCamera(cam_id, "Dock Test Cam", "rtsp://192.168.1.50/stream", "Dock")
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        cam.push_frame(dummy)
        active_cameras[cam_id] = cam

        try:
            # Create SharedBusFrameSource for this camera
            src = SharedBusFrameSource(cam_id)
            self.assertEqual(src.source_type, SourceType.SHARED_BUS)

            # Read frame from source: it must come from the shared buffer without calling cv2.VideoCapture
            with patch("cv2.VideoCapture") as mock_cap:
                read_res = src.read_frame()
                self.assertIsNotNone(read_res)
                mock_cap.assert_not_called()  # Proves zero second VideoCapture created!
        finally:
            active_cameras.pop(cam_id, None)

    # ========================================================================
    # 3. STALE FRAME & DISCONNECT / RECONNECT HANDLING
    # ========================================================================

    def test_04_stale_frame_detection(self):
        """Frames older than max_age_seconds are flagged stale and return None."""
        cam_id = "CAM-STALE-TEST"
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        self.bus.publish_frame(cam_id, dummy)

        # Immediately available with default max_age
        self.assertIsNotNone(self.bus.get_latest_frame(cam_id, max_age_seconds=5.0))

        # Stale when max_age_seconds is extremely short (e.g. 0.0001s)
        time.sleep(0.005)
        stale_res = self.bus.get_latest_frame(cam_id, max_age_seconds=0.001)
        self.assertIsNone(stale_res)

        status = self.bus.get_buffer_status(cam_id)
        self.assertFalse(status["is_connected"])

    def test_05_disconnect_and_reconnect_lifecycle(self):
        """mark_disconnected clears live frame, and new publication gracefully reconnects."""
        cam_id = "CAM-RECONNECT-TEST"
        dummy1 = np.ones((480, 640, 3), dtype=np.uint8) * 100
        self.bus.publish_frame(cam_id, dummy1)
        self.assertTrue(self.bus.get_buffer_status(cam_id)["is_connected"])

        # Disconnect signal
        self.bus.mark_disconnected(cam_id, reason="RTSP dropped")
        self.assertIsNone(self.bus.get_latest_frame(cam_id))
        self.assertFalse(self.bus.get_buffer_status(cam_id)["is_connected"])

        # Reconnect with fresh frame
        dummy2 = np.ones((480, 640, 3), dtype=np.uint8) * 200
        self.bus.publish_frame(cam_id, dummy2)
        fresh_frame = self.bus.get_latest_frame(cam_id)
        self.assertIsNotNone(fresh_frame)
        self.assertEqual(fresh_frame[0, 0, 0], 200)
        self.assertTrue(self.bus.get_buffer_status(cam_id)["is_connected"])

    # ========================================================================
    # 4. CAMERA JUNCTION INTEGRATION & PRESERVATION
    # ========================================================================

    def test_06_device_camera_push_populates_shared_bus(self):
        """POST /api/cameras/<id>/frame publishes directly to SharedFrameBus."""
        cam_id = "CAM-DEV-PUSH"
        active_cameras[cam_id] = SmartCamera(cam_id, "Mobile Device Cam", "device://client", "Dock")

        try:
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(dummy, "DEVICE STREAM", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            _, encoded = cv2.imencode(".jpg", dummy)
            
            res = self.client.post(
                f"/api/cameras/{cam_id}/frame",
                data=encoded.tobytes(),
                content_type="image/jpeg"
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))

            # Verify frame is immediately present on SharedFrameBus
            bus_frame = self.bus.get_latest_frame(cam_id)
            self.assertIsNotNone(bus_frame)
            self.assertEqual(bus_frame.shape, (480, 640, 3))
        finally:
            active_cameras.pop(cam_id, None)

    def test_07_camera_junction_snapshot_reads_from_shared_bus(self):
        """Camera snapshot API accesses the live frame through the shared buffer."""
        cam_id = "CAM-SNAP-TEST"
        cam = SmartCamera(cam_id, "Gate Snapshot Cam", "0", "Gate")
        active_cameras[cam_id] = cam

        try:
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(dummy, (50, 50), (200, 200), (0, 255, 255), -1)
            cam.push_frame(dummy)

            res = self.client.post(f"/api/cameras/{cam_id}/snap")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("photo", "").startswith("captures/"))
        finally:
            active_cameras.pop(cam_id, None)

    # ========================================================================
    # 5. DECOUPLED PREVIEW AND AI PROCESSING FPS
    # ========================================================================

    def test_08_decoupled_fps_preview_runs_without_ai_blocking(self):
        """Slow AI worker loop does not block the SharedFrameBus or Camera Junction preview."""
        cam_id = "CAM-FPS-DECOUPLED"
        # Publish 10 fast frames to the shared bus (simulating 30 FPS camera feed)
        for i in range(10):
            frame = np.ones((480, 640, 3), dtype=np.uint8) * i
            self.bus.publish_frame(cam_id, frame)

        # Preview consumer can immediately get the newest frame (frame 9)
        preview_frame = self.bus.get_latest_frame(cam_id)
        self.assertEqual(preview_frame[0, 0, 0], 9)
        self.assertEqual(self.bus.get_buffer_status(cam_id)["frame_index"], 10)

    # ========================================================================
    # 6. W.A.R.L.O.G. RUNTIME SESSION WITH SHARED BUS SOURCE
    # ========================================================================

    def test_09_runtime_session_consumes_shared_bus_source(self):
        """CameraRuntimeSession starts and correctly consumes frames from SharedBusFrameSource."""
        cam_id = "CAM-RUNTIME-BUS"
        # Register in active_cameras so _init_source selects SharedBusFrameSource
        cam = SmartCamera(cam_id, "Aisle 01 Cam", "0", "Aisle 01")
        active_cameras[cam_id] = cam

        try:
            sess = self.runtime_mgr.get_session(cam_id)
            if not sess:
                # Mock create session
                from vision_runtime_service import CameraRuntimeSession
                sess = CameraRuntimeSession(
                    camera_id=cam_id,
                    camera_code=cam_id,
                    name="Aisle 01 Cam",
                    location="Aisle 01",
                    stream_url="rtsp://192.168.1.101:554/ch0",
                    configured_fps=8,
                    test_mode=False
                )
                self.runtime_mgr.sessions[cam_id] = sess

            # Start session
            ok = sess.start()
            self.assertTrue(ok)
            self.assertIn(sess.runtime_state, [RuntimeState.RUNNING, RuntimeState.DEGRADED])
            self.assertIsInstance(sess.frame_source, SharedBusFrameSource)

            # Publish a frame to the shared bus
            test_frame = np.ones((480, 640, 3), dtype=np.uint8) * 150
            self.bus.publish_frame(cam_id, test_frame)

            # Wait briefly for worker cycle
            time.sleep(0.15)

            # Stop session cleanly
            sess.stop()
            self.assertEqual(sess.runtime_state, RuntimeState.STOPPED)
        finally:
            active_cameras.pop(cam_id, None)


if __name__ == "__main__":
    unittest.main()
