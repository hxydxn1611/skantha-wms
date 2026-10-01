"""
Automated Backend Test Suite for Part 7 — Object Identity & Recognition Foundation.
Tests all 20 requirements including Barcode/QR, OCR, track enrichment, conflict handling,
repeated read stability, camera isolation, reset, and regression for Parts 1-6.
"""

import os
import sys
import time
import unittest
import numpy as np
import cv2

# Set path to webapp
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'webapp'))

import db
from detection_service import get_detection_engine
from tracking_service import get_tracking_service
from identity_service import (
    get_identity_service,
    BarcodeQRDecoder,
    OCRAdapter,
    TrackIdentityState,
    CameraIdentitySession
)
from app import app


class TestPart7ObjectIdentity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.detection_engine = get_detection_engine()
        cls.tracking_service = get_tracking_service()
        cls.identity_service = get_identity_service()
        cls.client = app.test_client()

        cls.sc_dir = os.path.join(os.path.dirname(__file__), '..', 'webapp', 'static', 'test_scenes')

    def setUp(self):
        self.identity_service.reset_all()

    # 1. Tracker & Identity module imports and initializes successfully
    def test_01_initialization(self):
        status = self.identity_service.get_status()
        self.assertTrue(status['success'])
        self.assertIn('Part 7', status['engine'])
        self.assertTrue(status['decoders']['barcode_qr']['available'])
        self.assertTrue(status['decoders']['ocr']['available'])

    # 2. QR code decode success (payload "B104")
    def test_02_qr_decode_success(self):
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        self.assertTrue(os.path.exists(qr_path), f"Missing {qr_path}")
        res = self.identity_service.process_frame(qr_path, camera_id="CAM-TEST-QR")
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        t = res['tracks'][0]
        ident = t['identity']
        self.assertEqual(ident['status'], 'IDENTIFIED')
        self.assertEqual(ident['value'], 'B104')
        self.assertIn(ident['source'], ('QR', 'BARCODE'))
        self.assertGreaterEqual(ident['confidence'], 0.85)

    # 3. Barcode decode success (payload "B105", Code 128)
    def test_03_barcode_decode_success(self):
        bc_path = os.path.join(self.sc_dir, 'identity_barcode_b105.jpg')
        self.assertTrue(os.path.exists(bc_path), f"Missing {bc_path}")
        res = self.identity_service.process_frame(bc_path, camera_id="CAM-TEST-BC")
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        t = res['tracks'][0]
        ident = t['identity']
        self.assertEqual(ident['status'], 'IDENTIFIED')
        self.assertEqual(ident['value'], 'B105')
        self.assertEqual(ident['source'], 'BARCODE')
        self.assertGreaterEqual(ident['confidence'], 0.85)

    # 4. OCR text recognition success (payload "B106")
    def test_04_ocr_text_success(self):
        ocr_path = os.path.join(self.sc_dir, 'identity_ocr_b106.jpg')
        self.assertTrue(os.path.exists(ocr_path), f"Missing {ocr_path}")
        res = self.identity_service.process_frame(ocr_path, camera_id="CAM-TEST-OCR")
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        t = res['tracks'][0]
        ident = t['identity']
        self.assertEqual(ident['status'], 'IDENTIFIED')
        self.assertEqual(ident['value'], 'B106')
        self.assertEqual(ident['source'], 'OCR')
        self.assertGreaterEqual(ident['confidence'], 0.50)

    # 5. Image with no identifier returns UNIDENTIFIED (never invent an identity)
    def test_05_unidentified_object(self):
        plain_path = os.path.join(self.sc_dir, 'identity_unidentified.jpg')
        self.assertTrue(os.path.exists(plain_path), f"Missing {plain_path}")
        res = self.identity_service.process_frame(plain_path, camera_id="CAM-TEST-UN")
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        t = res['tracks'][0]
        ident = t['identity']
        self.assertEqual(ident['status'], 'UNIDENTIFIED')
        self.assertIsNone(ident['value'])
        self.assertIsNone(ident['source'])
        self.assertEqual(ident['confidence'], 0.0)

    # 6. Image with conflicting identifiers detects conflict and populates candidates
    def test_06_conflicting_identifiers(self):
        conf_path = os.path.join(self.sc_dir, 'identity_conflict.jpg')
        self.assertTrue(os.path.exists(conf_path), f"Missing {conf_path}")
        res = self.identity_service.process_frame(conf_path, camera_id="CAM-TEST-CONF")
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        t = res['tracks'][0]
        ident = t['identity']
        self.assertEqual(ident['status'], 'CONFLICT')
        self.assertIsNone(ident['value'])
        self.assertGreaterEqual(len(ident['candidates']), 2)
        cand_vals = [c['value'] for c in ident['candidates']]
        self.assertIn('B104', cand_vals)
        self.assertIn('B109', cand_vals)

    # 7. Repeated same identifier stability across frames
    def test_07_repeated_read_stability(self):
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        cam_id = "CAM-REPEAT-TEST"

        for frame_idx in range(1, 4):
            res = self.identity_service.process_frame(qr_path, camera_id=cam_id)
            self.assertTrue(res['success'])
            t = res['tracks'][0]
            ident = t['identity']
            self.assertEqual(ident['status'], 'IDENTIFIED')
            self.assertEqual(ident['value'], 'B104')
            self.assertEqual(ident['read_count'], frame_idx)

    # 8. Contradictory observation in subsequent frame marks CONFLICT without silent overwrite
    def test_08_subsequent_frame_conflict(self):
        cam_id = "CAM-DRIFT-TEST"
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        ocr_path = os.path.join(self.sc_dir, 'identity_ocr_b106.jpg')

        # Frame 1: B104 confirmed
        r1 = self.identity_service.process_frame(qr_path, camera_id=cam_id)
        t1 = r1['tracks'][0]
        self.assertEqual(t1['identity']['status'], 'IDENTIFIED')
        self.assertEqual(t1['identity']['value'], 'B104')

        # Frame 2: Same track presented with contradictory identifier B106
        r2 = self.identity_service.process_frame(ocr_path, camera_id=cam_id)
        t2 = r2['tracks'][0]
        self.assertEqual(t2['identity']['status'], 'CONFLICT')
        self.assertIsNone(t2['identity']['value'])
        self.assertGreaterEqual(len(t2['identity']['candidates']), 2)

    # 9. Camera-specific identity isolation (CAM-001 vs CAM-002)
    def test_09_camera_isolation(self):
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        bc_path = os.path.join(self.sc_dir, 'identity_barcode_b105.jpg')

        # Process CAM-A with B104
        r_a = self.identity_service.process_frame(qr_path, camera_id="CAM-A")
        t_a = r_a['tracks'][0]
        self.assertEqual(t_a['track_id'], 1)
        self.assertEqual(t_a['identity']['value'], 'B104')

        # Process CAM-B with B105
        r_b = self.identity_service.process_frame(bc_path, camera_id="CAM-B")
        t_b = r_b['tracks'][0]
        self.assertEqual(t_b['track_id'], 1)
        self.assertEqual(t_b['identity']['value'], 'B105')

        # Verify CAM-A state is still B104 and completely isolated
        sess_a = self.identity_service.get_session("CAM-A")
        ident_a = sess_a.get_track_identity(1)
        self.assertEqual(ident_a.value, 'B104')

        sess_b = self.identity_service.get_session("CAM-B")
        ident_b = sess_b.get_track_identity(1)
        self.assertEqual(ident_b.value, 'B105')

    # 10. Identity reset clears in-memory state
    def test_10_reset_behavior(self):
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        cam_id = "CAM-RESET-TEST"

        self.identity_service.process_frame(qr_path, camera_id=cam_id)
        sess = self.identity_service.get_session(cam_id)
        self.assertGreaterEqual(len(sess.tracks_identity), 1)

        # Reset camera
        self.identity_service.reset_session(cam_id)
        self.assertEqual(len(sess.tracks_identity), 0)

    # 11. Empty or zero-size image handled gracefully
    def test_11_empty_image_handling(self):
        empty_img = np.zeros((0, 0, 3), dtype=np.uint8)
        res = self.identity_service.process_frame(empty_img, camera_id="CAM-EMPTY")
        self.assertFalse(res['success'])
        self.assertIn("error", res)

    # 12. Invalid base64 or image buffer handled gracefully
    def test_12_invalid_image_handling(self):
        res = self.identity_service.process_frame("NOT_A_VALID_IMAGE_BYTES_OR_PATH", camera_id="CAM-INV")
        self.assertFalse(res['success'])
        self.assertIn("error", res)

    # 13. Sequence motion test maintains Track ID and Identity across movement
    def test_13_sequence_motion_persistence(self):
        cam_id = "CAM-SEQ-TEST"
        self.identity_service.reset_session(cam_id)
        res = self.identity_service.run_sequence(
            camera_id=cam_id,
            num_frames=5,
            sample_scene='identity_qr_b104.jpg',
            conf_threshold=0.25
        )
        self.assertTrue(res['success'])
        self.assertEqual(res['num_frames'], 5)
        self.assertEqual(len(res['step_results']), 5)
        last_step = res['step_results'][-1]
        self.assertGreaterEqual(last_step['active_track_count'], 1)
        self.assertGreaterEqual(last_step['identified_count'], 1)
        last_track = last_step['tracks'][0]
        self.assertEqual(last_track['track_id'], 1)
        self.assertEqual(last_track['identity']['value'], 'B104')
        self.assertEqual(last_track['identity']['status'], 'IDENTIFIED')

    # 14. Performance measurement reporting
    def test_14_performance_metrics(self):
        qr_path = os.path.join(self.sc_dir, 'identity_qr_b104.jpg')
        res = self.identity_service.process_frame(qr_path, camera_id="CAM-PERF")
        self.assertTrue(res['success'])
        perf = res['performance']
        self.assertIn('detection_ms', perf)
        self.assertIn('tracking_ms', perf)
        self.assertIn('barcode_qr_ms', perf)
        self.assertIn('ocr_ms', perf)
        self.assertIn('identity_ms', perf)
        self.assertIn('total_ms', perf)
        self.assertGreater(perf['total_ms'], 0.0)

    # 15. REST API endpoints testing
    def test_15_rest_api_endpoints(self):
        # GET /api/vision/identity/status
        r_status = self.client.get('/api/vision/identity/status')
        self.assertEqual(r_status.status_code, 200)
        self.assertTrue(r_status.json['success'])

        # POST /api/vision/identity/test
        r_test = self.client.post('/api/vision/identity/test', json={
            'camera_id': 'CAM-001',
            'sample_scene': 'identity_barcode_b105.jpg'
        })
        self.assertEqual(r_test.status_code, 200)
        self.assertTrue(r_test.json['success'])
        self.assertGreaterEqual(len(r_test.json['tracks']), 1)
        self.assertEqual(r_test.json['tracks'][0]['identity']['value'], 'B105')

        # POST /api/vision/identity/sequence
        r_seq = self.client.post('/api/vision/identity/sequence', json={
            'camera_id': 'CAM-001',
            'num_frames': 3,
            'sample_scene': 'identity_qr_b104.jpg'
        })
        self.assertEqual(r_seq.status_code, 200)
        self.assertTrue(r_seq.json['success'])

        # POST /api/vision/identity/reset
        r_reset = self.client.post('/api/vision/identity/reset', json={'camera_id': 'CAM-001'})
        self.assertEqual(r_reset.status_code, 200)
        self.assertTrue(r_reset.json['success'])

    # 16. Regression: Part 5 Detection Engine still works
    def test_16_regression_detection_engine(self):
        img_path = os.path.join(self.sc_dir, 'warehouse_carrier.jpg')
        res = self.detection_engine.detect(img_path)
        self.assertTrue(res['success'])
        self.assertGreater(len(res['detections']), 0)

    # 17. Regression: Part 6 Tracking Engine still works
    def test_17_regression_tracking_engine(self):
        res = self.tracking_service.run_sequence(camera_id="CAM-REG-TRACK", num_frames=3)
        self.assertTrue(res['success'])
        self.assertEqual(res['frames_processed'], 3)

    # 18. Regression: Object Classes Master still works
    def test_18_regression_object_classes(self):
        classes = db.get_all_object_classes()
        self.assertGreaterEqual(len(classes), 6)
        codes = [c['code'] for c in classes]
        self.assertIn('BOX', codes)
        self.assertIn('TRUCK', codes)
        self.assertIn('WORKER', codes)

    # 19. Regression: Camera Sources & Warehouse Zones still work
    def test_19_regression_cameras_and_zones(self):
        cams = db.get_all_cameras()
        self.assertGreaterEqual(len(cams), 1)
        zones = db.get_all_vision_zones()
        self.assertGreaterEqual(len(zones), 1)

    # 20. Database schema is completely unchanged (no identity master tables)
    def test_20_zero_database_changes(self):
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Confirm no permanent identity tables were added
        prohibited = ['box_identity', 'truck_identity', 'worker_identity', 'pallet_identity', 'tracking_history']
        for p in prohibited:
            self.assertNotIn(p, tables, f"Prohibited table '{p}' found in database!")


if __name__ == '__main__':
    unittest.main()
