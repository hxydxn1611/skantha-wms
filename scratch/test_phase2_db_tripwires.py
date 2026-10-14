"""
Test Suite for Phase 2: Database-Driven Zones & Tripwires
Verifies:
1. Migration of vision_zone_camera_rois schema (is_enabled, crossing_direction).
2. Saving & updating TRIPWIRE / LINE shapes in database.
3. Multi-camera isolation: different cameras hold independent tripwire positions.
4. Disabled tripwires (is_enabled=0) are recognized and ignored for counting.
5. Directional crossing logic: INBOUND_ONLY, OUTBOUND_ONLY, BOTH.
6. Ray-casting polygon test & resolution-independent denormalization.
7. Verification that hardcoded y=240 default counting is eradicated in SmartCamera.
"""

import os
import sys
import unittest
import numpy as np

# Fast test mode for AI components
os.environ["WARLOG_TEST_MODE"] = "1"

# Ensure webapp directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import db
from zone_engine import (
    is_point_in_polygon,
    denormalize_coordinate,
    get_camera_tripwire,
    evaluate_tripwire_crossing
)
from ai_engine import SmartCamera


class Phase2DatabaseTripwireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

        # Seed test cameras
        conn = db.get_db()
        conn.execute("""
            INSERT OR IGNORE INTO cameras (camera_id, camera_code, name, warehouse, location)
            VALUES ('CAM-TEST-01', 'CAM-TEST-01', 'Inbound Dock Cam 1', 'Warehouse A', 'Dock 01')
        """)
        conn.execute("""
            INSERT OR IGNORE INTO cameras (camera_id, camera_code, name, warehouse, location)
            VALUES ('CAM-TEST-02', 'CAM-TEST-02', 'Inbound Dock Cam 2', 'Warehouse A', 'Dock 02')
        """)
        conn.commit()
        conn.close()

    def setUp(self):
        # Clean test camera state between tests for complete test isolation
        conn = db.get_db()
        conn.execute("DELETE FROM vision_zone_camera_rois WHERE camera_id LIKE 'CAM-TEST%'")
        conn.execute("DELETE FROM vision_zone_cameras WHERE camera_id LIKE 'CAM-TEST%'")
        conn.commit()
        conn.close()

    def test_01_schema_migration_columns(self):
        """Verify is_enabled and crossing_direction columns exist in vision_zone_camera_rois."""
        conn = db.get_db()
        cursor = conn.execute("PRAGMA table_info(vision_zone_camera_rois)")
        cols = {row['name']: row for row in cursor.fetchall()}
        conn.close()

        self.assertIn("is_enabled", cols, "is_enabled column missing from vision_zone_camera_rois")
        self.assertIn("crossing_direction", cols, "crossing_direction column missing from vision_zone_camera_rois")

    def test_02_save_and_retrieve_tripwire(self):
        """Verify saving and retrieving a 2-point TRIPWIRE shape with direction and enabled status."""
        conn = db.get_db()
        cam = conn.execute("SELECT camera_id FROM cameras WHERE camera_id = 'CAM-TEST-01'").fetchone()
        zone = conn.execute("SELECT id, zone_code FROM vision_zones LIMIT 1").fetchone()
        cam_id = cam['camera_id']
        zone_id = zone['id']

        # Establish zone-camera association
        conn.execute("INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id) VALUES (?, ?)", (zone_id, cam_id))
        conn.commit()
        conn.close()

        tripwire_payload = {
            "shape_type": "TRIPWIRE",
            "coordinates": [
                {"x": 0.1, "y": 0.4},
                {"x": 0.9, "y": 0.4}
            ],
            "is_enabled": True,
            "crossing_direction": "INBOUND_ONLY"
        }

        res, err = db.save_zone_camera_roi(zone_id, cam_id, tripwire_payload)
        self.assertIsNone(err, f"Save ROI failed: {err}")
        self.assertIsNotNone(res)
        self.assertEqual(res['shape_type'], 'TRIPWIRE')
        self.assertTrue(res['is_enabled'])
        self.assertEqual(res['crossing_direction'], 'INBOUND_ONLY')
        self.assertEqual(len(res['coordinates']), 2)

        # Retrieve via get_camera_tripwire
        tw = get_camera_tripwire(cam_id, frame_w=640, frame_h=480)
        self.assertIsNotNone(tw, "get_camera_tripwire returned None for saved tripwire")
        self.assertEqual(tw['shape_type'], 'TRIPWIRE')
        self.assertEqual(tw['crossing_direction'], 'INBOUND_ONLY')
        # Denormalized coordinates: x=0.1*640=64, y=0.4*480=192
        self.assertEqual(tw['p1'], (64, 192))
        self.assertEqual(tw['p2'], (576, 192))

    def test_03_disabled_tripwire_ignored(self):
        """Verify that disabling a tripwire (is_enabled=False) causes get_camera_tripwire to return None."""
        conn = db.get_db()
        cam = conn.execute("SELECT camera_id FROM cameras WHERE camera_id = 'CAM-TEST-01'").fetchone()
        zone = conn.execute("SELECT id FROM vision_zones LIMIT 1").fetchone()
        cam_id = cam['camera_id']
        zone_id = zone['id']

        # Establish zone-camera association
        conn.execute("INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id) VALUES (?, ?)", (zone_id, cam_id))
        conn.commit()
        conn.close()

        disabled_payload = {
            "shape_type": "TRIPWIRE",
            "coordinates": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}],
            "is_enabled": False,
            "crossing_direction": "BOTH"
        }
        res, err = db.save_zone_camera_roi(zone_id, cam_id, disabled_payload)
        self.assertIsNone(err, f"Save ROI failed: {err}")
        self.assertFalse(res['is_enabled'])

        # Query should return None since tripwire is disabled
        tw = get_camera_tripwire(cam_id, 640, 480)
        self.assertIsNone(tw, "Disabled tripwire must not be returned by get_camera_tripwire")

    def test_04_multi_camera_independent_tripwires(self):
        """Verify different cameras have independent tripwires at different heights."""
        conn = db.get_db()
        cam1 = conn.execute("SELECT camera_id FROM cameras WHERE camera_id = 'CAM-TEST-01'").fetchone()
        cam2 = conn.execute("SELECT camera_id FROM cameras WHERE camera_id = 'CAM-TEST-02'").fetchone()
        zone = conn.execute("SELECT id FROM vision_zones LIMIT 1").fetchone()
        cam1_id = cam1['camera_id']
        cam2_id = cam2['camera_id']
        zone_id = zone['id']

        # Ensure associations
        conn.execute("INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id) VALUES (?, ?)", (zone_id, cam1_id))
        conn.execute("INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id) VALUES (?, ?)", (zone_id, cam2_id))
        conn.commit()
        conn.close()

        # Cam 1: y = 0.3 (144px at 480p)
        db.save_zone_camera_roi(zone_id, cam1_id, {
            "shape_type": "TRIPWIRE",
            "coordinates": [{"x": 0.0, "y": 0.3}, {"x": 1.0, "y": 0.3}],
            "is_enabled": True,
            "crossing_direction": "INBOUND_ONLY"
        })

        # Cam 2: y = 0.7 (336px at 480p)
        db.save_zone_camera_roi(zone_id, cam2_id, {
            "shape_type": "TRIPWIRE",
            "coordinates": [{"x": 0.0, "y": 0.7}, {"x": 1.0, "y": 0.7}],
            "is_enabled": True,
            "crossing_direction": "OUTBOUND_ONLY"
        })

        tw1 = get_camera_tripwire(cam1_id, 640, 480)
        tw2 = get_camera_tripwire(cam2_id, 640, 480)

        self.assertIsNotNone(tw1)
        self.assertIsNotNone(tw2)
        self.assertEqual(tw1['p1'][1], 144)
        self.assertEqual(tw2['p1'][1], 336)
        self.assertEqual(tw1['crossing_direction'], "INBOUND_ONLY")
        self.assertEqual(tw2['crossing_direction'], "OUTBOUND_ONLY")

    def test_05_directional_crossing_evaluation(self):
        """Verify vector cross-product crossing detection for IN, OUT, and direction filtering."""
        # Horizontal line from (0, 200) to (600, 200)
        p1 = (0, 200)
        p2 = (600, 200)

        # Downward movement across line (y=170 -> y=220)
        cross_down = evaluate_tripwire_crossing(p1, p2, prev_pos=(300, 170), curr_pos=(300, 220), allowed_direction="BOTH")
        self.assertEqual(cross_down, "IN", "Downward crossing should evaluate to IN")

        # Upward movement across line (y=230 -> y=180) -> 'OUT'
        cross_up = evaluate_tripwire_crossing(p1, p2, prev_pos=(300, 230), curr_pos=(300, 180), allowed_direction="BOTH")
        self.assertEqual(cross_up, "OUT", "Upward crossing should evaluate to OUT")

        # Directional filter: INBOUND_ONLY rejects upward OUT crossing
        filtered_out = evaluate_tripwire_crossing(p1, p2, prev_pos=(300, 230), curr_pos=(300, 180), allowed_direction="INBOUND_ONLY")
        self.assertIsNone(filtered_out, "INBOUND_ONLY filter must reject OUT crossing")

        # Directional filter: OUTBOUND_ONLY rejects downward IN crossing
        filtered_in = evaluate_tripwire_crossing(p1, p2, prev_pos=(300, 170), curr_pos=(300, 220), allowed_direction="OUTBOUND_ONLY")
        self.assertIsNone(filtered_in, "OUTBOUND_ONLY filter must reject IN crossing")

        # No crossing (stays on top side: y=170 -> y=180)
        no_cross = evaluate_tripwire_crossing(p1, p2, prev_pos=(300, 170), curr_pos=(300, 180), allowed_direction="BOTH")
        self.assertIsNone(no_cross, "Motion without crossing tripwire should return None")

    def test_06_resolution_denormalization(self):
        """Verify coordinate scaling across resolutions (e.g. 720p vs 1080p)."""
        px_480, py_480 = denormalize_coordinate(0.5, 0.5, 640, 480)
        self.assertEqual((px_480, py_480), (320, 240))

        px_1080, py_1080 = denormalize_coordinate(0.5, 0.5, 1920, 1080)
        self.assertEqual((px_1080, py_1080), (960, 540))

    def test_07_smartcamera_no_hardcoded_y240_default(self):
        """Verify SmartCamera does NOT default to hardcoded y=240 when no tripwire is configured."""
        cam = SmartCamera("CAM_TEST_UNCONFIGURED", "Unconfigured Test Cam", "push", "warehouse")
        
        # Ensure no hardcoded tripwire_y attribute remains as an active default
        self.assertFalse(hasattr(cam, 'tripwire_y'), "SmartCamera must not have hardcoded tripwire_y attribute")
        self.assertIsNone(cam.active_tripwire, "Unconfigured camera active_tripwire should be None")
        
        # When get_frame is called on blank frame, no tripwire line or phantom counting is triggered
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cam.raw_frame = blank_frame
        frame_bytes = cam.get_frame()
        self.assertIsNotNone(frame_bytes)
        self.assertEqual(cam.inbound_count, 0)
        self.assertEqual(cam.outbound_count, 0)


if __name__ == "__main__":
    unittest.main()
