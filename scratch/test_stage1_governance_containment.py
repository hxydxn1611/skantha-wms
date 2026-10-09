"""
test_stage1_governance_containment.py
W.A.R.L.O.G. Stage 1 Verification Suite: Contain Unauthorized Vision-to-WMS Writes.

Strict Boundaries Enforced:
1. Valid-looking OCR plate does NOT create a gate pass.
2. Invalid or ambiguous OCR result does NOT create a gate pass.
3. Repeated OCR results do NOT create duplicate gate passes.
4. Existing authorized manual gate-pass creation still works.
5. The vision pipeline can return OCR evidence without committing WMS transactions.
6. Absolute isolation: All test mutations use an isolated temporary SQLite database.
   The operational database (webapp/skandha_wms.db) is verified unchanged before and after.
"""

import sys
import os
import shutil
import tempfile
import sqlite3
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Add webapp directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp")))

import db
from vision_runtime_service import VisionPipelineExecutor
from validation_service import WarehouseMasterValidator, get_validation_service


OPERATIONAL_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp", "skandha_wms.db"))


def get_db_fingerprint(db_path: str):
    """Returns row counts and primary records from the operational database to verify immutability."""
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        table_counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        gp_rows = cur.execute("SELECT id, plate, status, po_number FROM gate_passes ORDER BY id").fetchall()
        return {
            "table_counts": table_counts,
            "gate_passes": gp_rows,
            "mtime": os.path.getmtime(db_path)
        }
    finally:
        conn.close()


class TestStage1VisionGovernanceContainment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Capture operational DB baseline fingerprint
        cls.operational_baseline = get_db_fingerprint(OPERATIONAL_DB_PATH)
        assert cls.operational_baseline is not None, "Operational database must exist to verify zero mutations"

        # 2. Create isolated temporary test database
        cls.temp_dir = tempfile.mkdtemp(prefix="warlog_stage1_test_")
        cls.test_db_path = os.path.join(cls.temp_dir, "test_isolated.db")
        
        # Save original db.DB_PATH
        cls.orig_db_path = db.DB_PATH
        
        # Point db.DB_PATH to isolated test DB
        db.DB_PATH = cls.test_db_path
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        # Restore db.DB_PATH
        db.DB_PATH = cls.orig_db_path
        
        # Clean up temporary test database directory
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

        # 3. Verify operational database was NEVER mutated
        operational_post = get_db_fingerprint(OPERATIONAL_DB_PATH)
        assert cls.operational_baseline["table_counts"] == operational_post["table_counts"], (
            f"MUTATION DETECTED in operational database!\n"
            f"Before: {cls.operational_baseline['table_counts']}\n"
            f"After: {operational_post['table_counts']}"
        )
        assert cls.operational_baseline["gate_passes"] == operational_post["gate_passes"], (
            f"MUTATION DETECTED in operational database gate_passes!\n"
            f"Before: {cls.operational_baseline['gate_passes']}\n"
            f"After: {operational_post['gate_passes']}"
        )

    def setUp(self):
        # Clean up gate_passes in isolated test database before each test
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM gate_passes")
            conn.execute("DELETE FROM expected_deliveries")
            conn.commit()
        finally:
            conn.close()

    def test_01_valid_ocr_plate_does_not_create_gate_pass(self):
        """A valid-looking OCR plate does NOT create a gate pass and is treated as unverified evidence."""
        executor = VisionPipelineExecutor()
        
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        plate_val = "MH12AB1234"
        
        mock_track = {
            "track_id": 101,
            "class_code": "TRUCK",
            "class_name": "Truck",
            "bbox": {"x1": 100.0, "y1": 100.0, "x2": 300.0, "y2": 250.0},
            "confidence": 0.92,
            "zone_code": "GATE_01"
        }
        
        mock_enriched_track = dict(mock_track)
        mock_enriched_track["identity"] = {
            "status": "IDENTIFIED",
            "type": "OCR_LICENSE_PLATE",
            "value": plate_val,
            "confidence": 0.94,
            "source_camera": "CAM-GATE-01",
            "timestamp": "2026-10-09T14:30:00Z"
        }

        # Mock detection, tracking, identity recognition to return the truck track with recognized plate
        with patch.object(executor.detection_engine, 'detect', return_value={"detections": [mock_track]}):
            with patch.object(executor.tracking_service, 'get_session') as mock_get_session:
                mock_session = MagicMock()
                mock_session.frame_index = 1
                mock_session.update.return_value = [mock_track]
                mock_get_session.return_value = mock_session
                
                with patch.object(executor.identity_service, 'identify_tracks', return_value=([mock_enriched_track], 5.0, 15.0)):
                    # Execute pipeline
                    result = executor.execute_pipeline(
                        raw_frame=dummy_frame,
                        camera_id="CAM-GATE-01"
                    )

        # 1. Assert NO gate pass was created in database
        conn = db.get_db()
        try:
            gp_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
            self.assertEqual(gp_count, 0, f"Expected 0 gate passes, but found {gp_count} auto-created!")
        finally:
            conn.close()

        # 2. Assert track validation status is UNREGISTERED
        tracks = result.get("tracks", [])
        self.assertEqual(len(tracks), 1)
        trk = tracks[0]
        self.assertEqual(trk["validation"]["status"], "UNREGISTERED")
        
        # 3. Assert OCR evidence is fully preserved
        self.assertEqual(trk["identity"]["value"], plate_val)
        self.assertEqual(trk["identity"]["confidence"], 0.94)
        self.assertEqual(trk["identity"]["source_camera"], "CAM-GATE-01")
        self.assertEqual(trk["identity"]["status"], "IDENTIFIED")

    def test_02_invalid_or_ambiguous_ocr_does_not_create_gate_pass(self):
        """Invalid or ambiguous OCR results (e.g. 'AL?', '??') do NOT create gate passes."""
        executor = VisionPipelineExecutor()
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        ambiguous_plates = ["AL?", "??", "13276", ""]
        for idx, amb_plate in enumerate(ambiguous_plates):
            mock_track = {
                "track_id": 200 + idx,
                "class_code": "TRUCK",
                "class_name": "Truck",
                "bbox": {"x1": 50.0, "y1": 50.0, "x2": 200.0, "y2": 200.0},
                "confidence": 0.70,
                "zone_code": "GATE_01"
            }
            mock_enriched = dict(mock_track)
            mock_enriched["identity"] = {
                "status": "IDENTIFIED" if amb_plate else "UNIDENTIFIED",
                "type": "OCR_LICENSE_PLATE",
                "value": amb_plate,
                "confidence": 0.45,
                "source_camera": "CAM-GATE-01",
                "timestamp": "2026-10-09T14:30:00Z"
            }

            with patch.object(executor.detection_engine, 'detect', return_value={"detections": [mock_track]}):
                with patch.object(executor.tracking_service, 'get_session') as mock_get_session:
                    mock_session = MagicMock()
                    mock_session.frame_index = idx + 1
                    mock_session.update.return_value = [mock_track]
                    mock_get_session.return_value = mock_session
                    
                    with patch.object(executor.identity_service, 'identify_tracks', return_value=([mock_enriched], 4.0, 10.0)):
                        result = executor.execute_pipeline(
                            raw_frame=dummy_frame,
                            camera_id="CAM-GATE-01"
                        )

            # Assert database has zero gate passes
            conn = db.get_db()
            try:
                gp_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
                self.assertEqual(gp_count, 0, f"Ambiguous plate '{amb_plate}' created a gate pass!")
            finally:
                conn.close()

            trk = result["tracks"][0]
            # Should not be validated
            self.assertIn(trk["validation"]["status"], ("UNREGISTERED", "NOT_APPLICABLE"))

    def test_03_repeated_ocr_results_do_not_create_duplicate_gate_passes(self):
        """Repeated OCR results across consecutive frames never create duplicate gate passes."""
        executor = VisionPipelineExecutor()
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        plate_val = "KA05MN9999"

        for frame_num in range(1, 10):
            mock_track = {
                "track_id": 301,
                "class_code": "TRUCK",
                "class_name": "Truck",
                "bbox": {"x1": 120.0, "y1": 120.0, "x2": 320.0, "y2": 270.0},
                "confidence": 0.88,
                "zone_code": "GATE_01"
            }
            mock_enriched = dict(mock_track)
            mock_enriched["identity"] = {
                "status": "IDENTIFIED",
                "type": "OCR_LICENSE_PLATE",
                "value": plate_val,
                "confidence": 0.91,
                "source_camera": "CAM-GATE-01",
                "timestamp": f"2026-10-09T14:30:0{frame_num}Z"
            }

            with patch.object(executor.detection_engine, 'detect', return_value={"detections": [mock_track]}):
                with patch.object(executor.tracking_service, 'get_session') as mock_get_session:
                    mock_session = MagicMock()
                    mock_session.frame_index = frame_num
                    mock_session.update.return_value = [mock_track]
                    mock_get_session.return_value = mock_session
                    
                    with patch.object(executor.identity_service, 'identify_tracks', return_value=([mock_enriched], 3.0, 8.0)):
                        result = executor.execute_pipeline(
                            raw_frame=dummy_frame,
                            camera_id="CAM-GATE-01"
                        )

            # After each repeated frame, gate_passes must remain 0
            conn = db.get_db()
            try:
                gp_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
                self.assertEqual(gp_count, 0, f"Frame {frame_num} created gate pass for repeated plate {plate_val}!")
            finally:
                conn.close()

    def test_04_authorized_manual_gate_pass_creation_still_works(self):
        """Existing authorized manual gate-pass creation functions properly without regression."""
        # 1. Authoritative creation via db.create_gate_pass without PO (unlinked direct gate pass)
        gp_data = {
            "po_number": "",
            "plate": "MH-12-MANUAL-1",
            "vehicle_type": "Trailer",
            "driver_name": "Rajesh Kumar",
            "vendor": "Authorized Logistics Ltd",
            "dock": "DOCK-01"
        }
        
        created_gp = db.create_gate_pass(gp_data)
        self.assertIsNotNone(created_gp)
        self.assertTrue(created_gp["id"].startswith("GP-"))
        self.assertEqual(created_gp["plate"], "MH-12-MANUAL-1")
        self.assertEqual(created_gp["status"], "Pending")

        # 2. Check persistence in isolated database
        conn = db.get_db()
        try:
            row = conn.execute("SELECT * FROM gate_passes WHERE id = ?", (created_gp["id"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["plate"], "MH-12-MANUAL-1")
            self.assertEqual(row["vendor"], "Authorized Logistics Ltd")
        finally:
            conn.close()

        # 3. Verify that once manually created, validation correctly identifies it as VALIDATED
        validator = WarehouseMasterValidator()
        val_res = validator.validate_truck("MH-12-MANUAL-1")
        self.assertEqual(val_res["status"], "VALIDATED")
        self.assertEqual(val_res["master_type"], "TRUCK")
        self.assertEqual(val_res["master_id"], created_gp["id"])

        # 4. Also test pre-registered expected delivery creation + gate pass link
        conn = db.get_db()
        try:
            conn.execute("""
                INSERT INTO expected_deliveries (po_number, expected_date, vendor, plate, status)
                VALUES ('PO-PRE-99', '2026-10-10', 'Tata Autocomp', 'MH-14-TA-5555', 'Expected')
            """)
            conn.commit()
        finally:
            conn.close()

        gp_linked_data = {
            "po_number": "PO-PRE-99",
            "plate": "MH-14-TA-5555",
            "vehicle_type": "Truck",
            "driver_name": "Anil Sharma",
            "vendor": "Tata Autocomp",
            "dock": "DOCK-02"
        }
        created_linked_gp = db.create_gate_pass(gp_linked_data)
        self.assertIsNotNone(created_linked_gp)
        self.assertEqual(created_linked_gp["po_number"], "PO-PRE-99")

    def test_05_vision_pipeline_returns_evidence_without_committing_wms_transactions(self):
        """The vision pipeline successfully returns OCR evidence without committing any WMS database transaction."""
        executor = VisionPipelineExecutor()
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Verify initial gate passes count is 0
        conn = db.get_db()
        try:
            initial_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
            self.assertEqual(initial_count, 0)
        finally:
            conn.close()

        mock_track = {
            "track_id": 501,
            "class_code": "LICENSE_PLATE",
            "class_name": "License Plate",
            "bbox": {"x1": 200.0, "y1": 200.0, "x2": 350.0, "y2": 280.0},
            "confidence": 0.89,
            "zone_code": "GATE_01"
        }
        mock_enriched = dict(mock_track)
        mock_enriched["identity"] = {
            "status": "IDENTIFIED",
            "type": "OCR_LICENSE_PLATE",
            "value": "DL01XY9876",
            "confidence": 0.96,
            "source_camera": "CAM-GATE-INBOUND",
            "timestamp": "2026-10-09T14:35:00Z"
        }

        with patch.object(executor.detection_engine, 'detect', return_value={"detections": [mock_track]}):
            with patch.object(executor.tracking_service, 'get_session') as mock_get_session:
                mock_session = MagicMock()
                mock_session.frame_index = 1
                mock_session.update.return_value = [mock_track]
                mock_get_session.return_value = mock_session
                
                with patch.object(executor.identity_service, 'identify_tracks', return_value=([mock_enriched], 2.0, 12.0)):
                    pipeline_output = executor.execute_pipeline(
                        raw_frame=dummy_frame,
                        camera_id="CAM-GATE-INBOUND"
                    )

        # Pipeline returns complete diagnostic and tracking output
        self.assertIn("tracks", pipeline_output)
        self.assertIn("timing", pipeline_output)
        self.assertEqual(len(pipeline_output["tracks"]), 1)
        
        track = pipeline_output["tracks"][0]
        self.assertEqual(track["identity"]["value"], "DL01XY9876")
        self.assertEqual(track["validation"]["status"], "UNREGISTERED")

        # Database remains completely unmodified
        conn = db.get_db()
        try:
            final_count = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
            self.assertEqual(final_count, 0, "Vision pipeline mutated WMS gate_passes!")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
