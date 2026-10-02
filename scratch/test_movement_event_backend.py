"""
Unit and Integration Test Suite for Warehouse Movement Event Detection Foundation (Part 12)
W.A.R.L.O.G. / Skandha WMS
"""

import sys
import os
import unittest
import json
import hashlib
import time
import urllib.request
import urllib.parse

# Add webapp directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'webapp')))

from movement_event_service import (
    MultiObjectMovementEventService,
    MovementEventConfig,
    MovementEvent,
    EventType,
    EventState,
    get_movement_event_service
)

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'webapp', 'skandha_wms.db'))
BASE_URL = "http://127.0.0.1:5000"

def get_file_md5(path):
    if not os.path.exists(path):
        return None
    hasher = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

class TestMovementEventFoundation(unittest.TestCase):

    def setUp(self):
        self.service = MultiObjectMovementEventService()
        self.cam_id = "CAM-TEST-001"
        self.service.reset(self.cam_id)
        self.initial_db_md5 = get_file_md5(DB_PATH)

    def tearDown(self):
        self.service.reset(self.cam_id)
        current_md5 = get_file_md5(DB_PATH)
        self.assertEqual(
            self.initial_db_md5, current_md5,
            "CRITICAL ERROR: Database checksum changed during test execution! Part 12 must be strictly zero-write in-memory."
        )

    # 1. Service Initialization and Configuration
    def test_01_service_initialization(self):
        cfg = self.service.config
        self.assertEqual(cfg.event_timeout_frames, 4)
        self.assertEqual(cfg.min_consecutive_frames, 3)
        self.assertTrue(cfg.enable_deduplication)
        self.assertEqual(cfg.max_history_events, 500)
        session = self.service.get_session(self.cam_id)
        self.assertIsNotNone(session)
        self.assertEqual(len(session.active_events), 0)

    # 2. Box Enter Zone Event Generation
    def test_02_box_enter_zone_event(self):
        # Frame 1: Box outside Dock 1
        f1_tracks = [{
            "track_id": 101, "class_code": "BOX", "center": [0.10, 0.10], "bbox": [0.05, 0.05, 0.15, 0.15],
            "identity_id": "B101", "identity_status": "VALIDATED", "validation_status": "VALIDATED"
        }]
        res1 = self.service.process_frame(self.cam_id, f1_tracks, frame_index=1)
        self.assertEqual(len(res1["active_events"]), 0)

        # Frame 2: Box enters Dock 1 (Dock 1 ROI is [0.45, 0.10, 0.95, 0.85])
        f2_tracks = [{
            "track_id": 101, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55],
            "identity_id": "B101", "identity_status": "VALIDATED", "validation_status": "VALIDATED"
        }]
        res2 = self.service.process_frame(self.cam_id, f2_tracks, frame_index=2)
        enter_events = [e for e in res2["active_events"] if e["event_type"] == EventType.BOX_ENTERED_ZONE.value]
        self.assertEqual(len(enter_events), 1)
        evt = enter_events[0]
        self.assertEqual(evt["status"], EventState.ACTIVE.value)
        self.assertEqual(evt["primary_object"]["track_id"], 101)
        self.assertEqual(evt["primary_object"]["identity_id"], "B101")
        self.assertEqual(evt["zone"]["zone_code"], "DOCK-01")
        self.assertTrue(evt["evidence"]["same_camera"])
        self.assertTrue(evt["evidence"]["same_zone"])

    # 3. Box Exit Zone Event Generation
    def test_03_box_exit_zone_event(self):
        # Start inside Dock 1
        inside_tracks = [{
            "track_id": 102, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55],
            "identity_id": "B102", "identity_status": "VALIDATED", "validation_status": "VALIDATED"
        }]
        self.service.process_frame(self.cam_id, inside_tracks, frame_index=1)

        # Move outside Dock 1
        outside_tracks = [{
            "track_id": 102, "class_code": "BOX", "center": [0.10, 0.10], "bbox": [0.05, 0.05, 0.15, 0.15],
            "identity_id": "B102", "identity_status": "VALIDATED", "validation_status": "VALIDATED"
        }]
        res = self.service.process_frame(self.cam_id, outside_tracks, frame_index=2)
        exit_events = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_EXITED_ZONE.value]
        self.assertEqual(len(exit_events), 1)
        self.assertEqual(exit_events[0]["primary_object"]["track_id"], 102)
        self.assertEqual(exit_events[0]["zone"]["zone_code"], "DOCK-01")

    # 4. Zone Entry Deduplication (10+ frames inside produces exactly 1 enter event)
    def test_04_zone_enter_deduplication(self):
        # Frame 1: outside
        self.service.process_frame(self.cam_id, [{
            "track_id": 103, "class_code": "BOX", "center": [0.10, 0.10], "bbox": [0.05, 0.05, 0.15, 0.15]
        }], frame_index=1)

        # Frames 2 to 15: inside Dock 1
        for f in range(2, 16):
            res = self.service.process_frame(self.cam_id, [{
                "track_id": 103, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55]
            }], frame_index=f)
            enter_events = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ENTERED_ZONE.value]
            self.assertEqual(len(enter_events), 1, f"Frame {f} generated {len(enter_events)} enter events instead of 1")

        session = self.service.get_session(self.cam_id)
        # Check that there is only 1 unique BOX_ENTERED_ZONE event generated for this track
        all_enter_evts = [e for e in session.history_events if e.event_type == EventType.BOX_ENTERED_ZONE.value]
        self.assertEqual(len(all_enter_evts), 1)

    # 5. Truck Association Event Generation
    def test_05_truck_association_event(self):
        tracks = [
            {"track_id": 10, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60], "identity_id": "GP-1000", "validation_status": "VALIDATED"},
            {"track_id": 20, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50], "identity_id": "B104", "validation_status": "VALIDATED"}
        ]
        associations = {
            "truck_associations": [{
                "truck_track_id": 10,
                "box_track_id": 20,
                "truck_identity": "GP-1000",
                "box_identity": "B104",
                "association_state": "CONFIRMED",
                "association_score": 0.91,
                "is_ambiguous": False,
                "evidence": {"same_zone": True, "sustained_frames": 4}
            }]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        truck_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
        self.assertEqual(len(truck_evts), 1)
        evt = truck_evts[0]
        self.assertEqual(evt["status"], EventState.ACTIVE.value)
        self.assertEqual(evt["primary_object"]["track_id"], 20)
        self.assertEqual(evt["secondary_object"]["track_id"], 10)
        self.assertEqual(evt["confidence"], 0.91)
        self.assertEqual(evt["event_level"], "VALIDATED_REAL_WORLD")

    # 6. Worker Association Event Generation
    def test_06_worker_association_event(self):
        tracks = [
            {"track_id": 5, "class_code": "WORKER", "center": [0.30, 0.40], "bbox": [0.25, 0.25, 0.35, 0.55], "identity_id": "W-RAJESH", "validation_status": "VALIDATED"},
            {"track_id": 25, "class_code": "BOX", "center": [0.32, 0.42], "bbox": [0.28, 0.38, 0.36, 0.46], "identity_id": "B105", "validation_status": "VALIDATED"}
        ]
        associations = {
            "worker_associations": [{
                "worker_track_id": 5,
                "box_track_id": 25,
                "worker_identity": "W-RAJESH",
                "box_identity": "B105",
                "association_state": "CONFIRMED",
                "association_score": 0.88,
                "is_ambiguous": False,
                "evidence": {"same_zone": True, "sustained_frames": 3}
            }]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        worker_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_WORKER.value]
        self.assertEqual(len(worker_evts), 1)
        evt = worker_evts[0]
        self.assertEqual(evt["primary_object"]["track_id"], 25)
        self.assertEqual(evt["secondary_object"]["track_id"], 5)
        self.assertEqual(evt["confidence"], 0.88)

    # 7. Bin Association Event Generation
    def test_07_bin_association_event(self):
        tracks = [
            {"track_id": 8, "class_code": "BIN", "center": [0.70, 0.70], "bbox": [0.60, 0.60, 0.80, 0.80], "identity_id": "BIN-A-01", "validation_status": "VALIDATED"},
            {"track_id": 28, "class_code": "BOX", "center": [0.71, 0.68], "bbox": [0.65, 0.62, 0.77, 0.74], "identity_id": "B106", "validation_status": "VALIDATED"}
        ]
        associations = {
            "bin_associations": [{
                "bin_track_id": 8,
                "box_track_id": 28,
                "bin_identity": "BIN-A-01",
                "box_identity": "B106",
                "association_state": "CONFIRMED",
                "association_score": 0.94,
                "is_ambiguous": False,
                "evidence": {"same_zone": True, "containment": True}
            }]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        bin_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_BIN.value]
        self.assertEqual(len(bin_evts), 1)
        evt = bin_evts[0]
        self.assertEqual(evt["primary_object"]["track_id"], 28)
        self.assertEqual(evt["secondary_object"]["track_id"], 8)
        self.assertEqual(evt["confidence"], 0.94)

    # 8. Candidate / Proximity Observation Events
    def test_08_candidate_observation_events(self):
        tracks = [
            {"track_id": 11, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 21, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]}
        ]
        associations = {
            "truck_associations": [{
                "truck_track_id": 11,
                "box_track_id": 21,
                "association_state": "CANDIDATE",
                "association_score": 0.45,
                "is_ambiguous": False,
                "evidence": {"same_zone": True}
            }]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        near_evts = [e for e in res["candidate_events"] if e["event_type"] == EventType.BOX_NEAR_TRUCK.value]
        self.assertEqual(len(near_evts), 1)
        self.assertEqual(near_evts[0]["status"], EventState.CANDIDATE.value)

    # 9. Event State Transitions (CANDIDATE -> ACTIVE -> COMPLETED)
    def test_09_state_transitions(self):
        # Candidate frame
        tracks = [
            {"track_id": 12, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 22, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]}
        ]
        assoc_candidate = {
            "truck_associations": [{
                "truck_track_id": 12, "box_track_id": 22, "association_state": "CANDIDATE",
                "association_score": 0.50, "is_ambiguous": False
            }]
        }
        r1 = self.service.process_frame(self.cam_id, tracks, associations=assoc_candidate, frame_index=1)
        self.assertEqual(len(r1["candidate_events"]), 1)
        self.assertEqual(r1["candidate_events"][0]["status"], EventState.CANDIDATE.value)

        # Confirmed frame -> Promoted to ACTIVE
        assoc_confirmed = {
            "truck_associations": [{
                "truck_track_id": 12, "box_track_id": 22, "association_state": "CONFIRMED",
                "association_score": 0.90, "is_ambiguous": False
            }]
        }
        r2 = self.service.process_frame(self.cam_id, tracks, associations=assoc_confirmed, frame_index=2)
        active_evts = [e for e in r2["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
        self.assertEqual(len(active_evts), 1)
        self.assertEqual(active_evts[0]["status"], EventState.ACTIVE.value)

    # 10. Event Timeout Handling (Grace period of 4 frames)
    def test_10_timeout_handling(self):
        tracks = [
            {"track_id": 14, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 24, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]}
        ]
        assoc = {
            "truck_associations": [{
                "truck_track_id": 14, "box_track_id": 24, "association_state": "CONFIRMED",
                "association_score": 0.85, "is_ambiguous": False
            }]
        }
        # Frame 1: established
        self.service.process_frame(self.cam_id, tracks, associations=assoc, frame_index=1)

        # Missing association for 3 frames (<= 4 frames timeout)
        for f in range(2, 5):
            res = self.service.process_frame(self.cam_id, tracks, associations={}, frame_index=f)
            # Event should still remain ACTIVE under grace period
            active = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
            self.assertEqual(len(active), 1, f"Event prematurely expired at missing frame count {f-1}")

    # 11. Event Expiration (ACTIVE -> EXPIRED after > 4 missing frames)
    def test_11_event_expiration(self):
        tracks = [
            {"track_id": 15, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 25, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]}
        ]
        assoc = {
            "truck_associations": [{
                "truck_track_id": 15, "box_track_id": 25, "association_state": "CONFIRMED",
                "association_score": 0.85, "is_ambiguous": False
            }]
        }
        self.service.process_frame(self.cam_id, tracks, associations=assoc, frame_index=1)

        # Missing for 5 consecutive frames (timeout is 4)
        for f in range(2, 7):
            res = self.service.process_frame(self.cam_id, tracks, associations={}, frame_index=f)

        # Now event must have transitioned to EXPIRED in history
        session = self.service.get_session(self.cam_id)
        expired_evts = [e for e in session.history_events if e.status == EventState.EXPIRED.value and e.event_type == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
        self.assertGreaterEqual(len(expired_evts), 1)
        # Association event must have expired and no longer be active
        active_assoc = [e for e in session.active_events.values() if e.event_type == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
        self.assertEqual(len(active_assoc), 0)

    # 12. Event Reactivation with a Brand New Event ID
    def test_12_reactivation_new_id(self):
        tracks = [
            {"track_id": 16, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 26, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]}
        ]
        assoc = {
            "truck_associations": [{
                "truck_track_id": 16, "box_track_id": 26, "association_state": "CONFIRMED",
                "association_score": 0.85, "is_ambiguous": False
            }]
        }
        # First active period
        r1 = self.service.process_frame(self.cam_id, tracks, associations=assoc, frame_index=1)
        evt_a = [e for e in r1["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value][0]
        id_a = evt_a["event_id"]

        # Expire it (missing for 5 frames)
        for f in range(2, 7):
            self.service.process_frame(self.cam_id, tracks, associations={}, frame_index=f)

        # Re-establish association
        r2 = self.service.process_frame(self.cam_id, tracks, associations=assoc, frame_index=7)
        evt_b = [e for e in r2["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value][0]
        id_b = evt_b["event_id"]

        self.assertNotEqual(id_a, id_b, f"Reactivated event must generate a new unique ID! Found {id_a} == {id_b}")

    # 13. Multiple Simultaneous Events and Multi-Object Support
    def test_13_multi_object_support(self):
        # 2 trucks, 4 boxes, 2 workers, 2 bins
        tracks = [
            {"track_id": 1, "class_code": "TRUCK", "center": [0.55, 0.30], "bbox": [0.45, 0.20, 0.65, 0.40], "identity_id": "T1"},
            {"track_id": 2, "class_code": "TRUCK", "center": [0.75, 0.30], "bbox": [0.65, 0.20, 0.85, 0.40], "identity_id": "T2"},
            {"track_id": 10, "class_code": "BOX", "center": [0.56, 0.32], "bbox": [0.52, 0.28, 0.60, 0.36], "identity_id": "B1"},
            {"track_id": 20, "class_code": "BOX", "center": [0.57, 0.34], "bbox": [0.53, 0.30, 0.61, 0.38], "identity_id": "B2"},
            {"track_id": 30, "class_code": "BOX", "center": [0.76, 0.32], "bbox": [0.72, 0.28, 0.80, 0.36], "identity_id": "B3"},
            {"track_id": 40, "class_code": "BOX", "center": [0.77, 0.34], "bbox": [0.73, 0.30, 0.81, 0.38], "identity_id": "B4"},
            {"track_id": 100, "class_code": "WORKER", "center": [0.20, 0.40], "bbox": [0.15, 0.30, 0.25, 0.50], "identity_id": "W1"},
            {"track_id": 200, "class_code": "WORKER", "center": [0.35, 0.40], "bbox": [0.30, 0.30, 0.40, 0.50], "identity_id": "W2"},
            {"track_id": 500, "class_code": "BIN", "center": [0.20, 0.70], "bbox": [0.15, 0.65, 0.25, 0.75], "identity_id": "BIN1"},
            {"track_id": 600, "class_code": "BIN", "center": [0.35, 0.70], "bbox": [0.30, 0.65, 0.40, 0.75], "identity_id": "BIN2"}
        ]
        associations = {
            "truck_associations": [
                {"truck_track_id": 1, "box_track_id": 10, "association_state": "CONFIRMED", "association_score": 0.88, "is_ambiguous": False},
                {"truck_track_id": 1, "box_track_id": 20, "association_state": "CONFIRMED", "association_score": 0.85, "is_ambiguous": False},
                {"truck_track_id": 2, "box_track_id": 30, "association_state": "CONFIRMED", "association_score": 0.87, "is_ambiguous": False},
                {"truck_track_id": 2, "box_track_id": 40, "association_state": "CONFIRMED", "association_score": 0.89, "is_ambiguous": False}
            ],
            "worker_associations": [
                {"worker_track_id": 100, "box_track_id": 10, "association_state": "CONFIRMED", "association_score": 0.82, "is_ambiguous": False},
                {"worker_track_id": 200, "box_track_id": 20, "association_state": "CONFIRMED", "association_score": 0.84, "is_ambiguous": False}
            ],
            "bin_associations": [
                {"bin_track_id": 500, "box_track_id": 30, "association_state": "CONFIRMED", "association_score": 0.90, "is_ambiguous": False},
                {"bin_track_id": 600, "box_track_id": 40, "association_state": "CONFIRMED", "association_score": 0.91, "is_ambiguous": False}
            ]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        active = res["active_events"]
        # Total association events: 4 truck + 2 worker + 2 bin = 8
        assoc_events = [e for e in active if "ASSOCIATED" in e["event_type"]]
        self.assertEqual(len(assoc_events), 8)

    # 14. Ambiguity Preservation (Competing associations must NOT produce false confirmed event)
    def test_14_ambiguity_preservation(self):
        tracks = [
            {"track_id": 1, "class_code": "TRUCK", "center": [0.55, 0.40], "bbox": [0.45, 0.30, 0.65, 0.50]},
            {"track_id": 2, "class_code": "TRUCK", "center": [0.65, 0.40], "bbox": [0.55, 0.30, 0.75, 0.50]},
            {"track_id": 99, "class_code": "BOX", "center": [0.60, 0.40], "bbox": [0.58, 0.38, 0.62, 0.42]}
        ]
        associations = {
            "truck_associations": [
                {"truck_track_id": 1, "box_track_id": 99, "association_state": "CANDIDATE", "association_score": 0.65, "is_ambiguous": True},
                {"truck_track_id": 2, "box_track_id": 99, "association_state": "CANDIDATE", "association_score": 0.64, "is_ambiguous": True}
            ]
        }
        res = self.service.process_frame(self.cam_id, tracks, associations=associations, frame_index=1)
        confirmed_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ASSOCIATED_WITH_TRUCK.value]
        self.assertEqual(len(confirmed_evts), 0, "Ambiguous candidates must NEVER be promoted to CONFIRMED active events!")
        candidate_evts = [e for e in res["candidate_events"] if e["event_type"] == EventType.BOX_NEAR_TRUCK.value]
        self.assertGreaterEqual(len(candidate_evts), 1)

    # 15. Camera Session Isolation
    def test_15_camera_session_isolation(self):
        cam_a = "CAM-ISOLATE-A"
        cam_b = "CAM-ISOLATE-B"
        tracks_a = [{"track_id": 1, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55]}]
        tracks_b = [{"track_id": 1, "class_code": "BOX", "center": [0.10, 0.10], "bbox": [0.05, 0.05, 0.15, 0.15]}]

        self.service.process_frame(cam_a, tracks_a, frame_index=1)
        self.service.process_frame(cam_b, tracks_b, frame_index=1)

        sess_a = self.service.get_session(cam_a)
        sess_b = self.service.get_session(cam_b)

        # Track 1 on cam_a is inside Dock 1 -> generates BOX_ENTERED_ZONE
        enter_a = [e for e in sess_a.active_events.values() if e.event_type == EventType.BOX_ENTERED_ZONE.value]
        # Track 1 on cam_b is outside Dock 1 -> generates NO enter event
        enter_b = [e for e in sess_b.active_events.values() if e.event_type == EventType.BOX_ENTERED_ZONE.value]

        self.assertEqual(len(enter_a), 1)
        self.assertEqual(len(enter_b), 0)

    # 16. Track ID vs Real Identity Separation
    def test_16_track_vs_identity_separation(self):
        # Track without identity
        tracks = [
            {"track_id": 77, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55]}
        ]
        res = self.service.process_frame(self.cam_id, tracks, frame_index=1)
        enter_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ENTERED_ZONE.value]
        self.assertEqual(len(enter_evts), 1)
        evt = enter_evts[0]
        self.assertEqual(evt["primary_object"]["track_id"], 77)
        self.assertIsNone(evt["primary_object"]["identity_id"])
        self.assertEqual(evt["primary_object"]["identity_status"], "UNIDENTIFIED")
        self.assertEqual(evt["event_level"], "TRACK_LEVEL")

    # 17. Validation Status Preservation
    def test_17_validation_status_preservation(self):
        # Unregistered identity
        tracks = [
            {"track_id": 88, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55],
             "identity_id": "B-UNKNOWN-99", "identity_status": "SCANNED", "validation_status": "UNREGISTERED"}
        ]
        res = self.service.process_frame(self.cam_id, tracks, frame_index=1)
        enter_evts = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_ENTERED_ZONE.value]
        self.assertEqual(len(enter_evts), 1)
        evt = enter_evts[0]
        self.assertEqual(evt["primary_object"]["identity_id"], "B-UNKNOWN-99")
        self.assertEqual(evt["primary_object"]["validation_status"], "UNREGISTERED")
        self.assertEqual(evt["event_level"], "TRACK_LEVEL")

    # 18. Session Reset Clears State
    def test_18_session_reset(self):
        tracks = [{"track_id": 99, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55]}]
        self.service.process_frame(self.cam_id, tracks, frame_index=1)
        session = self.service.get_session(self.cam_id)
        self.assertGreater(len(session.active_events), 0)

        # Reset
        self.service.reset(self.cam_id)
        session = self.service.get_session(self.cam_id)
        self.assertEqual(len(session.active_events), 0)
        self.assertEqual(len(session.candidate_events), 0)
        self.assertEqual(len(session.history_events), 0)
        self.assertEqual(len(session.box_zone_state), 0)

    # 19. Malformed Input Resilience
    def test_19_malformed_input(self):
        try:
            res1 = self.service.process_frame(self.cam_id, None, frame_index=1)
            self.assertIn("active_events", res1)
            res2 = self.service.process_frame(self.cam_id, [{}], associations="invalid", frame_index=2)
            self.assertIn("active_events", res2)
        except Exception as e:
            self.fail(f"Service crashed on malformed input: {e}")

    # 20. Deterministic 8-Frame Synthetic Sequence
    def test_20_deterministic_sequence(self):
        seq_res = self.service.run_synthetic_sequence(self.cam_id, "dock_loading")
        self.assertEqual(seq_res["sequence_name"], "dock_loading")
        self.assertEqual(seq_res["total_frames"], 8)
        generated_types = seq_res["summary"]["generated_event_types"]

        # Must generate all 5 specified events across the sequence
        expected = [
            "BOX_ENTERED_ZONE",
            "BOX_ASSOCIATED_WITH_TRUCK",
            "BOX_ASSOCIATED_WITH_WORKER",
            "BOX_ASSOCIATED_WITH_BIN",
            "BOX_EXITED_ZONE"
        ]
        for exp in expected:
            self.assertIn(exp, generated_types, f"Sequence failed to generate expected event type {exp}")

    # 21. REST API Endpoints Verification
    def test_21_rest_api_endpoints(self):
        # 1. GET /api/vision/events/status
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/status")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(data["status"], "healthy")
            self.assertIn("BOX_ENTERED_ZONE", data["supported_event_types"])

        # 2. POST /api/vision/events/test
        test_payload = json.dumps({"camera_id": "CAM-REST-TEST", "scenario": "box_enter"}).encode('utf-8')
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/test", data=test_payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(data["success"])
            self.assertEqual(data["synthetic"], True)

        # 3. POST /api/vision/events/sequence
        seq_payload = json.dumps({"camera_id": "CAM-REST-TEST", "sequence_name": "dock_loading"}).encode('utf-8')
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/sequence", data=seq_payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(data["success"])
            self.assertEqual(data["total_frames"], 8)

        # 4. GET /api/vision/events/cameras/CAM-REST-TEST
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/cameras/CAM-REST-TEST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(data["camera_id"], "CAM-REST-TEST")

        # 5. GET /api/vision/events/cameras/CAM-REST-TEST/annotated.jpg
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/cameras/CAM-REST-TEST/annotated.jpg")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get_content_type(), "image/jpeg")

        # 6. POST /api/vision/events/reset
        reset_payload = json.dumps({"camera_id": "CAM-REST-TEST"}).encode('utf-8')
        req = urllib.request.Request(f"{BASE_URL}/api/vision/events/reset", data=reset_payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(data["success"])

    # 22. Performance Overhead Measurement (<15ms per frame)
    def test_22_performance_measurement(self):
        tracks = [
            {"track_id": 1, "class_code": "TRUCK", "center": [0.60, 0.40], "bbox": [0.45, 0.20, 0.75, 0.60]},
            {"track_id": 2, "class_code": "BOX", "center": [0.62, 0.45], "bbox": [0.58, 0.40, 0.66, 0.50]},
            {"track_id": 3, "class_code": "WORKER", "center": [0.30, 0.40], "bbox": [0.25, 0.25, 0.35, 0.55]},
            {"track_id": 4, "class_code": "BIN", "center": [0.70, 0.70], "bbox": [0.60, 0.60, 0.80, 0.80]}
        ]
        times = []
        for f in range(50):
            t0 = time.perf_counter()
            self.service.process_frame(self.cam_id, tracks, frame_index=f)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        print(f"\n[PERFORMANCE] Movement Event Layer Processing: Avg={avg_ms:.3f}ms, Max={max_ms:.3f}ms over 50 iterations.")
        self.assertLess(avg_ms, 15.0, f"Average event processing time {avg_ms:.3f}ms exceeded 15ms target!")

if __name__ == '__main__':
    unittest.main()
