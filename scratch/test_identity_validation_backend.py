"""
Part 8 Validation Test Suite: Warehouse Identity Validation & Master-Data Binding Foundation
Automated unit, integration, and regression test harness covering all 20 mandatory test cases.
"""

import unittest
import os
import sys
import json
import sqlite3
import cv2
import numpy as np

os.environ["WARLOG_TEST_MODE"] = "1"

# Ensure webapp directory is in python path
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'webapp')
sys.path.insert(0, WEBAPP_DIR)

from db import get_db, DB_PATH
from validation_service import get_validation_service, WarehouseMasterValidator, MasterDataRegistry
from identity_service import get_identity_service
from tracking_service import get_tracking_service
from detection_service import get_detection_engine
import app as flask_app_module


class TestIdentityValidationBackend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.val_service = get_validation_service()
        cls.validator = cls.val_service.validator
        cls.ident_service = get_identity_service()
        cls.sc_dir = os.path.join(WEBAPP_DIR, 'static', 'test_scenes')
        cls.app = flask_app_module.app.test_client()

        # Capture database row counts to verify zero database writes
        cls.initial_counts = cls._get_all_table_counts()

    @classmethod
    def _get_all_table_counts(cls):
        conn = get_db()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        counts = {}
        for t in tables:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.close()
        return counts

    def setUp(self):
        # Reset camera sessions before each test
        self.val_service.reset_all()

    # ------------------------------------------------------------------------
    # Test 1: Known Identifier (TRUCK GP-1000)
    # ------------------------------------------------------------------------
    def test_01_known_identifier_truck_gate_pass(self):
        res = self.validator.validate_identity('TRUCK', 'GP-1000', 'IDENTIFIED', 'QR_CODE')
        self.assertEqual(res['status'], 'VALIDATED')
        self.assertEqual(res['master_type'], 'TRUCK')
        self.assertEqual(res['master_id'], 'GP-1000')
        self.assertEqual(res['matched_field'], 'id')
        self.assertIn('MH-12-AB-1234', res['display_name'])

    # ------------------------------------------------------------------------
    # Test 2: Known Identifier by License Plate (MH12AB1234)
    # ------------------------------------------------------------------------
    def test_02_known_identifier_truck_plate(self):
        res = self.validator.validate_identity('TRUCK', 'MH12AB1234', 'IDENTIFIED', 'BARCODE')
        self.assertEqual(res['status'], 'VALIDATED')
        self.assertEqual(res['master_type'], 'TRUCK')
        self.assertEqual(res['matched_field'], 'plate')

    # ------------------------------------------------------------------------
    # Test 3: Known Identifier (BOX SKU VLV-900)
    # ------------------------------------------------------------------------
    def test_03_known_identifier_box_sku(self):
        res = self.validator.validate_identity('BOX', 'VLV-900', 'IDENTIFIED', 'OCR')
        self.assertEqual(res['status'], 'VALIDATED')
        self.assertEqual(res['master_type'], 'BOX')
        self.assertEqual(res['master_id'], 'VLV-900')
        self.assertEqual(res['matched_field'], 'sku')

    # ------------------------------------------------------------------------
    # Test 4: Unknown Identifier (B999999)
    # ------------------------------------------------------------------------
    def test_04_unknown_identifier_unregistered(self):
        res = self.validator.validate_identity('TRUCK', 'B999999', 'IDENTIFIED', 'QR_CODE')
        self.assertEqual(res['status'], 'UNREGISTERED')
        self.assertIsNone(res['master_type'])
        self.assertIsNone(res['master_id'])
        self.assertIn("no matching WMS truck master record", res['message'])

    # ------------------------------------------------------------------------
    # Test 5: Wrong Object-Class Rejection (BOX presented with truck GP-1000)
    # ------------------------------------------------------------------------
    def test_05_wrong_class_box_with_truck_id(self):
        # GP-1000 is a valid truck gate pass, but detected class is BOX
        res = self.validator.validate_identity('BOX', 'GP-1000', 'IDENTIFIED', 'QR_CODE')
        self.assertEqual(res['status'], 'UNREGISTERED')
        self.assertIsNone(res['master_id'])

    # ------------------------------------------------------------------------
    # Test 6: Wrong Object-Class Rejection (TRUCK presented with box SKU VLV-900)
    # ------------------------------------------------------------------------
    def test_06_wrong_class_truck_with_box_sku(self):
        # VLV-900 is a valid box SKU, but detected class is TRUCK
        res = self.validator.validate_identity('TRUCK', 'VLV-900', 'IDENTIFIED', 'OCR')
        self.assertEqual(res['status'], 'UNREGISTERED')
        self.assertIsNone(res['master_id'])

    # ------------------------------------------------------------------------
    # Test 7: Unidentified Input Handling
    # ------------------------------------------------------------------------
    def test_07_unidentified_input(self):
        res = self.validator.validate_identity('TRUCK', None, 'UNIDENTIFIED', None)
        self.assertEqual(res['status'], 'NOT_APPLICABLE')
        self.assertIsNone(res['master_id'])
        self.assertIn("No visual identity was detected", res['message'])

    # ------------------------------------------------------------------------
    # Test 8: Conflict Input Handling
    # ------------------------------------------------------------------------
    def test_08_conflict_input(self):
        res = self.validator.validate_identity('TRUCK', None, 'CONFLICT', None)
        self.assertEqual(res['status'], 'NOT_APPLICABLE')
        self.assertIsNone(res['master_id'])
        self.assertIn("Identity conflict must be resolved", res['message'])

    # ------------------------------------------------------------------------
    # Test 9: Missing Master Data Source (FORKLIFT gap)
    # ------------------------------------------------------------------------
    def test_09_master_data_unavailable_forklift(self):
        res = self.validator.validate_identity('FORKLIFT', 'F05', 'IDENTIFIED', 'OCR')
        self.assertEqual(res['status'], 'MASTER_DATA_UNAVAILABLE')
        self.assertIsNone(res['master_type'])
        self.assertIn("No suitable WMS master-data source exists for object class 'FORKLIFT'", res['message'])

    # ------------------------------------------------------------------------
    # Test 10: Missing Master Data Source (PALLET gap)
    # ------------------------------------------------------------------------
    def test_10_master_data_unavailable_pallet(self):
        res = self.validator.validate_identity('PALLET', 'P100', 'IDENTIFIED', 'BARCODE')
        self.assertEqual(res['status'], 'MASTER_DATA_UNAVAILABLE')
        self.assertIsNone(res['master_type'])
        self.assertIn("No suitable WMS master-data source exists for object class 'PALLET'", res['message'])

    # ------------------------------------------------------------------------
    # Test 11: SQL Parameterization & Injection Safety
    # ------------------------------------------------------------------------
    def test_11_sql_injection_safety(self):
        malicious_inputs = [
            "'; DROP TABLE gate_passes; --",
            "' OR '1'='1",
            "\" OR \"\"=\"",
            "GP-1000' UNION SELECT 1,2,3,4,5,6,7,8,9--",
            "<script>alert(1)</script>"
        ]
        for bad_input in malicious_inputs:
            res = self.validator.validate_identity('TRUCK', bad_input, 'IDENTIFIED', 'OCR')
            self.assertIn(res['status'], ('UNREGISTERED', 'NOT_APPLICABLE'))
        
        # Verify gate_passes table is completely intact
        conn = get_db()
        cnt = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
        conn.close()
        self.assertGreater(cnt, 0)

    # ------------------------------------------------------------------------
    # Test 12: Multiple Camera Isolation
    # ------------------------------------------------------------------------
    def test_12_multiple_camera_isolation(self):
        self.val_service.reset_session('CAM-001')
        self.val_service.reset_session('CAM-002')

        frame = cv2.imread(os.path.join(self.sc_dir, 'validation_truck_gp1000.jpg'))
        res1 = self.val_service.process_frame(frame, camera_id='CAM-001')
        self.assertEqual(res1['camera_id'], 'CAM-001')

        # Reset CAM-001 only
        self.val_service.reset_session('CAM-001')
        sess1 = self.val_service.identity_service.get_session('CAM-001')
        self.assertEqual(len(sess1.tracks_identity), 0)

    # ------------------------------------------------------------------------
    # Test 13: End-to-End Pipeline with Known Gate Pass Scene
    # ------------------------------------------------------------------------
    def test_13_end_to_end_validated_scene(self):
        frame = cv2.imread(os.path.join(self.sc_dir, 'validation_truck_gp1000.jpg'))
        res = self.val_service.process_frame(frame, camera_id='CAM-001')
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        self.assertGreaterEqual(res['validated_count'], 1)
        
        t = res['tracks'][0]
        self.assertEqual(t['identity']['value'], 'GP-1000')
        self.assertEqual(t['validation']['status'], 'VALIDATED')
        self.assertEqual(t['validation']['master_id'], 'GP-1000')

    # ------------------------------------------------------------------------
    # Test 14: End-to-End Pipeline with Unregistered Scene
    # ------------------------------------------------------------------------
    def test_14_end_to_end_unregistered_scene(self):
        frame = cv2.imread(os.path.join(self.sc_dir, 'validation_unknown_b999.jpg'))
        res = self.val_service.process_frame(frame, camera_id='CAM-001')
        self.assertTrue(res['success'])
        self.assertGreaterEqual(res['active_track_count'], 1)
        self.assertEqual(res['validated_count'], 0)
        self.assertGreaterEqual(res['unregistered_count'], 1)

        t = res['tracks'][0]
        self.assertEqual(t['identity']['value'], 'B999999')
        self.assertEqual(t['validation']['status'], 'UNREGISTERED')

    # ------------------------------------------------------------------------
    # Test 15: API Status Endpoint (GET /api/vision/validation/status)
    # ------------------------------------------------------------------------
    def test_15_api_status_endpoint(self):
        resp = self.app.get('/api/vision/validation/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertEqual(data['database_access'], 'READ-ONLY')
        masters = data['available_masters']
        self.assertTrue(masters['TRUCK']['available'])
        self.assertTrue(masters['BOX']['available'])
        self.assertFalse(masters['FORKLIFT']['available'])
        self.assertFalse(masters['PALLET']['available'])

    # ------------------------------------------------------------------------
    # Test 16: API Validation Test Endpoint (POST /api/vision/validation/test)
    # ------------------------------------------------------------------------
    def test_16_api_validation_test_endpoint(self):
        resp = self.app.post('/api/vision/validation/test', json={
            'camera_id': 'CAM-001',
            'source_type': 'sample',
            'sample_scene': 'validation_truck_gp1000.jpg',
            'enable_barcode': True,
            'enable_ocr': True
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['validated_count'], 1)
        self.assertEqual(data['tracks'][0]['validation']['status'], 'VALIDATED')

    # ------------------------------------------------------------------------
    # Test 17: Part 7 Identity Regression
    # ------------------------------------------------------------------------
    def test_17_part7_identity_regression(self):
        resp = self.app.get('/api/vision/identity/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['decoders']['barcode_qr'])

    # ------------------------------------------------------------------------
    # Test 18: Part 6 Tracking Regression
    # ------------------------------------------------------------------------
    def test_18_part6_tracking_regression(self):
        tracking_service = get_tracking_service()
        res = tracking_service.run_sequence(camera_id="CAM-REG-VAL", num_frames=3)
        self.assertTrue(res['success'])
        self.assertEqual(res['frames_processed'], 3)

    # ------------------------------------------------------------------------
    # Test 19: Part 5 Detection Regression
    # ------------------------------------------------------------------------
    def test_19_part5_detection_regression(self):
        det_engine = get_detection_engine()
        img_path = os.path.join(self.sc_dir, 'warehouse_carrier.jpg')
        res = det_engine.detect(img_path)
        self.assertTrue(res['success'])
        self.assertGreater(len(res['detections']), 0)

    # ------------------------------------------------------------------------
    # Test 20: Zero Database Writes Verification & Read-Only Guarantee
    # ------------------------------------------------------------------------
    def test_20_zero_database_writes(self):
        final_counts = self._get_all_table_counts()
        for tbl, count in self.initial_counts.items():
            self.assertEqual(
                final_counts[tbl], count,
                f"Database write violation detected on table '{tbl}': initial {count}, final {final_counts[tbl]}"
            )
        
        # Verify no temporary tracking or identity tables were created in SQLite
        conn = get_db()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        conn.close()
        for forbidden in ['tracking_history', 'track_identities', 'validation_history', 'box_identity', 'truck_identity']:
            self.assertNotIn(forbidden, tables)


if __name__ == '__main__':
    unittest.main()
