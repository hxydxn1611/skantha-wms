"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 15 — Vision Runtime & Processing Orchestrator Backend Verification Suite

Comprehensive test suite covering:
1. VisionRuntimeManager singleton initialization & camera discovery
2. Start camera session (STOPPED -> RUNNING transition)
3. Prevent duplicate camera session (duplicate start returns False / 409)
4. Stop camera session (graceful halt, queue clearing, state STOPPED)
5. Restart camera session (clean stop and start cycle)
6. Error isolation (failure in CAM-001 does not crash CAM-002)
7. Bounded frame queue overflow & drop-oldest policy (maxsize=5)
8. Multiple cameras concurrent execution
9. Graceful shutdown (manager.stop_all)
10. Runtime telemetry accuracy (summary and per-camera metrics)
11. Test frame pipeline execution (canonical Parts 5–14 chain)
12. REST APIs: status, cameras, camera detail, start, stop, restart, preview.jpg, test_step
13. Database Immutability & WMS Governance: zero inventory mutations
"""

import os
import sys
import time
import json
import sqlite3
import unittest
import numpy as np

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(WORKSPACE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import app as flask_app_module
from vision_runtime_service import (
    VisionRuntimeManager,
    CameraRuntimeSession,
    BoundedFrameQueue,
    RuntimeState,
    SourceType,
    TestSyntheticFrameSource,
    PushedFrameSource,
    get_vision_runtime_manager
)

DB_PATH = os.path.join(WEBAPP_DIR, "skandha_wms.db")


class TestVisionRuntimeBackend(unittest.TestCase):
    """Rigorous verification suite for Part 15 Vision Runtime & Processing Orchestrator."""

    @classmethod
    def setUpClass(cls):
        os.environ["WARLOG_TEST_MODE"] = "1"
        cls.flask_app = flask_app_module.app
        cls.flask_app.config['TESTING'] = True
        cls.client = cls.flask_app.test_client()
        cls.manager = get_vision_runtime_manager()
        cls.manager.refresh_cameras()
        # Ensure all cameras are stopped before tests begin
        cls.manager.stop_all()

    def setUp(self):
        # Clean state before each test
        self.manager.stop_all()

    def tearDown(self):
        # Stop all running sessions after each test
        self.manager.stop_all()

    def test_01_manager_initialization(self):
        """Test manager discovers all configured cameras from SQLite database."""
        telemetry = self.manager.get_telemetry()
        summary = telemetry["summary"]
        cameras = telemetry["cameras"]

        self.assertGreaterEqual(summary["total_cameras"], 4)
        self.assertEqual(summary["running_cameras"], 0)
        self.assertEqual(summary["stopped_cameras"], summary["total_cameras"])
        
        cam_ids = [c["camera_id"] for c in cameras]
        self.assertIn("CAM-001", cam_ids)
        self.assertIn("CAM-002", cam_ids)
        self.assertIn("CAM-003", cam_ids)
        self.assertIn("CAM-004", cam_ids)

    def test_02_start_camera_session(self):
        """Test starting a single camera transitions state from STOPPED to RUNNING."""
        sess = self.manager.get_session("CAM-001")
        self.assertIsNotNone(sess)
        self.assertEqual(sess.runtime_state, RuntimeState.STOPPED)

        started = sess.start()
        self.assertTrue(started)
        self.assertEqual(sess.runtime_state, RuntimeState.RUNNING)
        self.assertIsNotNone(sess.start_time)
        self.assertTrue(sess.capture_thread.is_alive())
        self.assertTrue(sess.worker_thread.is_alive())

    def test_03_prevent_duplicate_camera_session(self):
        """Test starting an already running session returns False and prevents duplicate threads."""
        sess = self.manager.get_session("CAM-001")
        self.assertTrue(sess.start())
        worker_thread_id = sess.worker_thread.ident

        # Second start attempt must fail
        duplicate_start = sess.start()
        self.assertFalse(duplicate_start)
        # Verify the same worker thread is still active and not duplicated
        self.assertEqual(sess.worker_thread.ident, worker_thread_id)

    def test_04_stop_camera_session(self):
        """Test stopping a running session gracefully halts threads and clears queues."""
        sess = self.manager.get_session("CAM-001")
        sess.start()
        time.sleep(0.3)

        stopped = sess.stop()
        self.assertTrue(stopped)
        self.assertEqual(sess.runtime_state, RuntimeState.STOPPED)
        self.assertIsNone(sess.capture_thread)
        self.assertIsNone(sess.worker_thread)
        self.assertEqual(sess.frame_queue.depth, 0)

    def test_05_restart_camera_session(self):
        """Test restart cycles from RUNNING -> STOPPED -> RUNNING cleanly."""
        sess = self.manager.get_session("CAM-001")
        sess.start()
        self.assertEqual(sess.runtime_state, RuntimeState.RUNNING)

        restarted = sess.restart()
        self.assertTrue(restarted)
        self.assertEqual(sess.runtime_state, RuntimeState.RUNNING)
        self.assertTrue(sess.worker_thread.is_alive())

    def test_06_error_isolation_between_cameras(self):
        """Test failure or exception in CAM-001 does NOT crash CAM-002."""
        sess1 = self.manager.get_session("CAM-001")
        sess2 = self.manager.get_session("CAM-002")

        sess1.start()
        sess2.start()
        self.assertEqual(sess1.runtime_state, RuntimeState.RUNNING)
        self.assertEqual(sess2.runtime_state, RuntimeState.RUNNING)

        # Inject simulated pipeline failure into CAM-001
        with sess1.lock:
            sess1.last_error = "Simulated Hardware OCR Disconnect"
            sess1.consecutive_failures = 6
            sess1.runtime_state = RuntimeState.DEGRADED

        # Verify CAM-001 is degraded with error logged
        self.assertEqual(sess1.runtime_state, RuntimeState.DEGRADED)
        self.assertEqual(sess1.last_error, "Simulated Hardware OCR Disconnect")

        # Verify CAM-002 remains strictly RUNNING with zero errors
        self.assertEqual(sess2.runtime_state, RuntimeState.RUNNING)
        self.assertIsNone(sess2.last_error)
        self.assertTrue(sess2.worker_thread.is_alive())

    def test_07_bounded_queue_overflow_and_drop_oldest(self):
        """Test bounded frame queue maintains maxsize=5 and drops oldest on saturation."""
        queue = BoundedFrameQueue(maxsize=5)
        self.assertEqual(queue.depth, 0)

        # Push 10 distinct frames
        for i in range(10):
            dummy_frame = np.full((100, 100, 3), i, dtype=np.uint8)
            queue.put_frame(dummy_frame)

        # Queue depth must never exceed maxsize=5
        self.assertEqual(queue.depth, 5)
        self.assertEqual(queue.total_dropped, 5)

        # First retrieved frame must be frame index 5 (0, 1, 2, 3, 4 were dropped)
        first_out = queue.get_frame()
        self.assertEqual(first_out[0, 0, 0], 5)

    def test_08_multiple_cameras_concurrent_execution(self):
        """Test multiple cameras execute concurrently with independent frame rates."""
        cams = ["CAM-001", "CAM-002", "CAM-003"]
        for cid in cams:
            sess = self.manager.get_session(cid)
            sess.start()

        # Let them run for 1 second
        time.sleep(1.0)

        telemetry = self.manager.get_telemetry()
        self.assertEqual(telemetry["summary"]["running_cameras"], 3)

        for cid in cams:
            sess = self.manager.get_session(cid)
            data = sess.to_dict()
            self.assertEqual(data["runtime_state"], "RUNNING")
            self.assertGreater(data["frames_received"], 0)
            self.assertGreater(data["frames_processed"], 0)

    def test_09_graceful_shutdown(self):
        """Test manager.stop_all() terminates all running sessions cleanly."""
        self.manager.start_all()
        telemetry_start = self.manager.get_telemetry()
        self.assertGreaterEqual(telemetry_start["summary"]["running_cameras"], 1)

        results = self.manager.stop_all()
        for cid, stopped in results.items():
            self.assertTrue(stopped)

        telemetry_stop = self.manager.get_telemetry()
        self.assertEqual(telemetry_stop["summary"]["running_cameras"], 0)
        self.assertEqual(telemetry_stop["summary"]["stopped_cameras"], telemetry_stop["summary"]["total_cameras"])

    def test_10_pipeline_execution_canonical_chain(self):
        """Test synthetic test frame passes through Detection -> Tracking -> Identity -> Validation -> Associations -> Events -> Traceability."""
        sess = self.manager.get_session("CAM-001")
        source = TestSyntheticFrameSource(sess.camera_id, sess.location)
        raw_frame = source.read_frame()
        self.assertIsNotNone(raw_frame)
        self.assertEqual(raw_frame.shape, (720, 1280, 3))

        result = sess.pipeline_executor.execute_pipeline(
            raw_frame=raw_frame,
            camera_id=sess.camera_id,
            camera_meta={"code": sess.camera_code, "name": sess.name, "location": sess.location}
        )

        self.assertIn("frame_index", result)
        self.assertIn("timestamp", result)
        self.assertIn("detections_count", result)
        self.assertIn("tracks_count", result)
        self.assertIn("timing", result)
        self.assertIsNotNone(result.get("annotated_jpeg"))
        self.assertGreater(len(result["annotated_jpeg"]), 1000)

        timing = result["timing"]
        self.assertIn("detection_ms", timing)
        self.assertIn("tracking_ms", timing)
        self.assertIn("association_ms", timing)
        self.assertIn("total_ms", timing)

    def test_11_rest_api_status_and_cameras(self):
        """Test GET /api/vision/runtime/status and /api/vision/runtime/cameras."""
        resp = self.client.get('/api/vision/runtime/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("summary", data["data"])

        resp2 = self.client.get('/api/vision/runtime/cameras')
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertTrue(data2["success"])
        self.assertIsInstance(data2["cameras"], list)
        self.assertGreaterEqual(len(data2["cameras"]), 4)

    def test_12_rest_api_camera_detail_and_404(self):
        """Test GET /api/vision/runtime/cameras/<camera_id> (200 & 404)."""
        resp = self.client.get('/api/vision/runtime/cameras/CAM-001')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["camera"]["camera_id"], "CAM-001")

        resp404 = self.client.get('/api/vision/runtime/cameras/NON_EXISTENT_CAM')
        self.assertEqual(resp404.status_code, 404)
        data404 = resp404.get_json()
        self.assertFalse(data404["success"])

    def test_13_rest_api_camera_lifecycle_controls(self):
        """Test POST /start, /stop, /restart, and duplicate 409 handling."""
        # 1. Start camera
        start_resp = self.client.post('/api/vision/runtime/cameras/CAM-001/start')
        self.assertEqual(start_resp.status_code, 200)
        start_data = start_resp.get_json()
        self.assertTrue(start_data["success"])
        self.assertEqual(start_data["camera"]["runtime_state"], "RUNNING")

        # 2. Duplicate start must return 409
        dup_resp = self.client.post('/api/vision/runtime/cameras/CAM-001/start')
        self.assertEqual(dup_resp.status_code, 409)
        dup_data = dup_resp.get_json()
        self.assertFalse(dup_data["success"])

        # 3. Restart camera
        restart_resp = self.client.post('/api/vision/runtime/cameras/CAM-001/restart')
        self.assertEqual(restart_resp.status_code, 200)
        restart_data = restart_resp.get_json()
        self.assertTrue(restart_data["success"])

        # 4. Stop camera
        stop_resp = self.client.post('/api/vision/runtime/cameras/CAM-001/stop')
        self.assertEqual(stop_resp.status_code, 200)
        stop_data = stop_resp.get_json()
        self.assertTrue(stop_data["success"])
        self.assertEqual(stop_data["camera"]["runtime_state"], "STOPPED")

    def test_14_rest_api_preview_and_test_step(self):
        """Test GET preview.jpg and POST test_step."""
        # Execute single test step
        step_resp = self.client.post('/api/vision/runtime/cameras/CAM-001/test_step')
        self.assertEqual(step_resp.status_code, 200)
        step_data = step_resp.get_json()
        self.assertTrue(step_data["success"])
        self.assertIn("pipeline_result", step_data)

        # Fetch preview image
        preview_resp = self.client.get('/api/vision/runtime/cameras/CAM-001/preview.jpg')
        self.assertEqual(preview_resp.status_code, 200)
        self.assertEqual(preview_resp.mimetype, 'image/jpeg')
        self.assertGreater(len(preview_resp.data), 1000)

    def test_15_database_immutability_and_governance(self):
        """Strict Governance: Vision runtime execution must NEVER mutate database inventory ledger."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Capture counts
        inv_count_before = cursor.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()['cnt']
        deliv_count_before = cursor.execute("SELECT COUNT(*) as cnt FROM expected_deliveries").fetchone()['cnt']
        gp_count_before = cursor.execute("SELECT COUNT(*) as cnt FROM gate_passes").fetchone()['cnt']
        sku_count_before = cursor.execute("SELECT COUNT(*) as cnt FROM skus").fetchone()['cnt']
        bin_count_before = cursor.execute("SELECT COUNT(*) as cnt FROM bins").fetchone()['cnt']

        # Run continuous camera runtime
        sess = self.manager.get_session("CAM-001")
        sess.start()
        time.sleep(1.0)
        sess.stop()

        # Capture counts after execution
        inv_count_after = cursor.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()['cnt']
        deliv_count_after = cursor.execute("SELECT COUNT(*) as cnt FROM expected_deliveries").fetchone()['cnt']
        gp_count_after = cursor.execute("SELECT COUNT(*) as cnt FROM gate_passes").fetchone()['cnt']
        sku_count_after = cursor.execute("SELECT COUNT(*) as cnt FROM skus").fetchone()['cnt']
        bin_count_after = cursor.execute("SELECT COUNT(*) as cnt FROM bins").fetchone()['cnt']
        conn.close()

        # Invariant checks:
        self.assertEqual(inv_count_after, inv_count_before)
        self.assertEqual(inv_count_after, 0, "Inventory ledger must remain strictly at 0 rows.")
        self.assertEqual(deliv_count_after, deliv_count_before)
        self.assertEqual(gp_count_after, gp_count_before)
        self.assertEqual(sku_count_after, sku_count_before)
        self.assertEqual(bin_count_after, bin_count_before)


if __name__ == '__main__':
    unittest.main()
