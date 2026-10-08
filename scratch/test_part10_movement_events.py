"""
Test Suite for Part 10: Movement & Event Tracking Enhancement.

Verifies all 16 required verification scenarios:
  1. Material enters dock (MATERIAL_ENTERED_ZONE)
  2. Material leaves dock (MATERIAL_EXITED_ZONE)
  3. Material becomes associated with truck (MATERIAL_ASSOCIATED_WITH_TRUCK)
  4. Material moves from unloading to sorting (MATERIAL_MOVED_TO_SORTING)
  5. Material enters staging (MATERIAL_ENTERED_STAGING)
  6. Material enters storage/bin zone (MATERIAL_STORED_IN_BIN)
  7. Material exits bin/storage zone (MATERIAL_EXITED_ZONE)
  8. Material becomes associated with worker (MATERIAL_ASSOCIATED_WITH_WORKER)
  9. Material/container relationship changes & custody handoff
  10. Dispatch movement (MATERIAL_DISPATCHED)
  11. Repeated frames do not duplicate events
  12. Insufficient evidence does not create confirmed events (single frame is CANDIDATE)
  13. Ambiguous / conflicting identity does not create false traceability
  14. Cross-camera continuity using explicit physical identity (no visual Re-ID)
  15. Existing legacy BOX and BOX_UNLOADED_AT_DOCK regression
  16. Inventory remains unchanged (17 tables, 0 inventory records)
"""

import os
import sys
import unittest
import copy

# Add webapp directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))

from movement_event_service import (
    EventType,
    MovementEvent,
    MultiObjectMovementEventService,
    get_movement_event_service,
    CameraMovementEventSession
)
from material_traceability_service import (
    get_material_traceability_service,
    TraceabilityLevel,
    MaterialTraceStatus
)
import sqlite3


class TestPart10MovementEvents(unittest.TestCase):
    def setUp(self):
        self.service = MultiObjectMovementEventService()
        self.service.reset_all()
        self.trace_service = get_material_traceability_service()
        self.trace_service.reset()

        self.zones = [
            {
                "id": 1,
                "zone_code": "DOCK-01",
                "zone_name": "Dock 01",
                "zone_type": "DOCK",
                "polygon": [{"x": 0.05, "y": 0.05}, {"x": 0.35, "y": 0.05}, {"x": 0.35, "y": 0.40}, {"x": 0.05, "y": 0.40}]
            },
            {
                "id": 2,
                "zone_code": "SORT-01",
                "zone_name": "Sorting Area",
                "zone_type": "SORTING",
                "polygon": [{"x": 0.40, "y": 0.05}, {"x": 0.70, "y": 0.05}, {"x": 0.70, "y": 0.40}, {"x": 0.40, "y": 0.40}]
            },
            {
                "id": 3,
                "zone_code": "STAGE-01",
                "zone_name": "Staging Area",
                "zone_type": "STAGING",
                "polygon": [{"x": 0.75, "y": 0.05}, {"x": 0.95, "y": 0.05}, {"x": 0.95, "y": 0.40}, {"x": 0.75, "y": 0.40}]
            },
            {
                "id": 4,
                "zone_code": "BIN-A-01",
                "zone_name": "Storage Bin A01",
                "zone_type": "STORAGE",
                "polygon": [{"x": 0.40, "y": 0.50}, {"x": 0.70, "y": 0.50}, {"x": 0.70, "y": 0.90}, {"x": 0.40, "y": 0.90}]
            },
            {
                "id": 5,
                "zone_code": "DISP-01",
                "zone_name": "Dispatch Area",
                "zone_type": "DISPATCH",
                "polygon": [{"x": 0.75, "y": 0.50}, {"x": 0.95, "y": 0.50}, {"x": 0.95, "y": 0.90}, {"x": 0.75, "y": 0.90}]
            }
        ]

    # ------------------------------------------------------------------------
    # Scenario 1: Material enters dock (MATERIAL_ENTERED_ZONE)
    # ------------------------------------------------------------------------
    def test_01_material_enters_dock(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}

        # Dwell 1, 2: should be candidate
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=1, camera_zones=self.zones)
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=2, camera_zones=self.zones)
        # Dwell 3: confirmed!
        res, _ = self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=3, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        entry_events = [e for e in current_events if e.get("event_type") == "MATERIAL_ENTERED_ZONE" and e.get("status") == "ACTIVE"]
        self.assertTrue(len(entry_events) >= 1, f"Expected confirmed MATERIAL_ENTERED_ZONE, got: {current_events}")
        ev = entry_events[0]
        self.assertEqual(ev["zone"]["zone_code"], "DOCK-01")
        self.assertEqual(ev["stage"], "DOCK")

    # ------------------------------------------------------------------------
    # Scenario 2: Material leaves dock (MATERIAL_EXITED_ZONE)
    # ------------------------------------------------------------------------
    def test_02_material_leaves_dock(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "GLASS", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "GLS-WND-001", "validation_status": "VALIDATED"}

        # Enter dock (frames 1, 2, 3)
        for f in range(1, 4):
            self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)

        # Move outside dock to unassigned space (center [0.02, 0.02])
        mat_track_outside = copy.deepcopy(mat_track)
        mat_track_outside["center"] = [0.02, 0.02]
        res, _ = self.service.process_events(tracks=[mat_track_outside], camera_id=cam, frame_index=4, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        exit_events = [e for e in current_events if e.get("event_type") == "MATERIAL_EXITED_ZONE"]
        self.assertTrue(len(exit_events) >= 1, f"Expected MATERIAL_EXITED_ZONE event, got: {current_events}")
        self.assertEqual(exit_events[0]["zone"]["zone_code"], "DOCK-01")

    # ------------------------------------------------------------------------
    # Scenario 3: Material becomes associated with truck & dock unloading
    # ------------------------------------------------------------------------
    def test_03_material_associated_with_truck(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "PART", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "PRT-ENG-099", "validation_status": "VALIDATED"}
        truck_track = {"track_id": 10, "class_code": "TRUCK", "center": [0.22, 0.22], "bbox": [0.05, 0.05, 0.35, 0.40], "identity_id": "TRK-MH12-8821", "validation_status": "VALIDATED"}

        # Enter dock (frames 1-3)
        for f in range(1, 4):
            self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)

        # Frame 4: Truck material association
        material_assocs = {
            "truck_material_associations": [{
                "truck_track_id": 10, "material_track_id": 101, "association_state": "CONFIRMED",
                "association_score": 0.94, "is_ambiguous": False
            }]
        }
        res, _ = self.service.process_events(
            tracks=[mat_track, truck_track],
            material_assocs=material_assocs,
            camera_id=cam,
            frame_index=4,
            camera_zones=self.zones
        )

        current_events = res.get("current_events", [])
        truck_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_ASSOCIATED_WITH_TRUCK"]
        self.assertTrue(len(truck_evs) >= 1, f"Expected MATERIAL_ASSOCIATED_WITH_TRUCK, got: {current_events}")
        self.assertEqual(truck_evs[0]["secondary_object"]["identity_id"], "TRK-MH12-8821")

        # Dock unloading event should also be triggered because material is inside DOCK-01 and associated with truck
        unload_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_UNLOADED_AT_DOCK"]
        self.assertTrue(len(unload_evs) >= 1, f"Expected MATERIAL_UNLOADED_AT_DOCK, got: {current_events}")

    # ------------------------------------------------------------------------
    # Scenario 4: Material moves from unloading to sorting
    # ------------------------------------------------------------------------
    def test_04_material_moves_to_sorting(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "COMPONENT", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "CMP-AXL-001", "validation_status": "VALIDATED"}

        # DOCK entry
        for f in range(1, 4):
            self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)

        # Move to SORTING (center [0.55, 0.20])
        sort_mat = copy.deepcopy(mat_track)
        sort_mat["center"] = [0.55, 0.20]

        # Frames 4, 5 (dwell 1, 2)
        self.service.process_events(tracks=[sort_mat], camera_id=cam, frame_index=4, camera_zones=self.zones)
        self.service.process_events(tracks=[sort_mat], camera_id=cam, frame_index=5, camera_zones=self.zones)
        # Frame 6 (dwell 3 -> confirmed milestone!)
        res, _ = self.service.process_events(tracks=[sort_mat], camera_id=cam, frame_index=6, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        sort_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_MOVED_TO_SORTING"]
        self.assertTrue(len(sort_evs) >= 1, f"Expected MATERIAL_MOVED_TO_SORTING, got: {current_events}")
        self.assertEqual(sort_evs[0]["stage"], "SORTING")

    # ------------------------------------------------------------------------
    # Scenario 5: Material enters staging
    # ------------------------------------------------------------------------
    def test_05_material_enters_staging(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.85, 0.20], "bbox": [0.80, 0.15, 0.90, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}

        # Dwell 1, 2, 3 in STAGE-01
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=1, camera_zones=self.zones)
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=2, camera_zones=self.zones)
        res, _ = self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=3, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        stage_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_ENTERED_STAGING"]
        self.assertTrue(len(stage_evs) >= 1, f"Expected MATERIAL_ENTERED_STAGING, got: {current_events}")
        self.assertEqual(stage_evs[0]["stage"], "STAGING")

    # ------------------------------------------------------------------------
    # Scenario 6: Material enters storage/bin zone
    # ------------------------------------------------------------------------
    def test_06_material_enters_storage_bin(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "FASTENER", "center": [0.55, 0.70], "bbox": [0.50, 0.65, 0.60, 0.75], "identity_id": "FST-M12-BOLT", "validation_status": "VALIDATED"}
        bin_track = {"track_id": 50, "class_code": "BIN", "center": [0.55, 0.70], "bbox": [0.45, 0.60, 0.65, 0.80], "identity_id": "BIN-A-01", "validation_status": "VALIDATED"}

        material_assocs = {
            "material_bin_associations": [{
                "bin_track_id": 50, "material_track_id": 101, "association_state": "CONFIRMED",
                "association_score": 0.96, "is_ambiguous": False
            }]
        }

        self.service.process_events(tracks=[mat_track, bin_track], material_assocs=material_assocs, camera_id=cam, frame_index=1, camera_zones=self.zones)
        self.service.process_events(tracks=[mat_track, bin_track], material_assocs=material_assocs, camera_id=cam, frame_index=2, camera_zones=self.zones)
        res, _ = self.service.process_events(tracks=[mat_track, bin_track], material_assocs=material_assocs, camera_id=cam, frame_index=3, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        stored_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_STORED_IN_BIN"]
        self.assertTrue(len(stored_evs) >= 1, f"Expected MATERIAL_STORED_IN_BIN, got: {current_events}")
        self.assertEqual(stored_evs[0]["stage"], "STORAGE")

    # ------------------------------------------------------------------------
    # Scenario 7: Material exits bin/storage zone
    # ------------------------------------------------------------------------
    def test_07_material_exits_storage_bin(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "FASTENER", "center": [0.55, 0.70], "bbox": [0.50, 0.65, 0.60, 0.75], "identity_id": "FST-M12-BOLT", "validation_status": "VALIDATED"}

        # Dwell in BIN-A-01
        for f in range(1, 4):
            self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)

        # Move to corridor outside all zones (center [0.72, 0.45])
        mat_track_outside = copy.deepcopy(mat_track)
        mat_track_outside["center"] = [0.72, 0.45]
        res, _ = self.service.process_events(tracks=[mat_track_outside], camera_id=cam, frame_index=4, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        exit_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_EXITED_ZONE"]
        self.assertTrue(len(exit_evs) >= 1, f"Expected MATERIAL_EXITED_ZONE, got: {current_events}")
        self.assertEqual(exit_evs[0]["zone"]["zone_code"], "BIN-A-01")

    # ------------------------------------------------------------------------
    # Scenario 8: Material becomes associated with worker
    # ------------------------------------------------------------------------
    def test_08_material_associated_with_worker(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}
        worker_track = {"track_id": 30, "class_code": "WORKER", "center": [0.22, 0.20], "bbox": [0.18, 0.15, 0.26, 0.30], "identity_id": "W-VIKRAM", "validation_status": "VALIDATED"}

        material_assocs = {
            "worker_material_associations": [{
                "worker_track_id": 30, "material_track_id": 101, "association_state": "CONFIRMED",
                "association_score": 0.91, "is_ambiguous": False
            }]
        }
        res, _ = self.service.process_events(
            tracks=[mat_track, worker_track],
            material_assocs=material_assocs,
            camera_id=cam,
            frame_index=1,
            camera_zones=self.zones
        )

        current_events = res.get("current_events", [])
        worker_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_ASSOCIATED_WITH_WORKER"]
        self.assertTrue(len(worker_evs) >= 1, f"Expected MATERIAL_ASSOCIATED_WITH_WORKER, got: {current_events}")
        self.assertEqual(worker_evs[0]["secondary_object"]["identity_id"], "W-VIKRAM")

    # ------------------------------------------------------------------------
    # Scenario 9: Material/container relationship changes & custody handoff
    # ------------------------------------------------------------------------
    def test_09_material_custody_handoff_and_container(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}
        truck_track = {"track_id": 10, "class_code": "TRUCK", "center": [0.22, 0.22], "identity_id": "TRK-01", "validation_status": "VALIDATED"}
        worker_track = {"track_id": 30, "class_code": "WORKER", "center": [0.21, 0.20], "identity_id": "W-01", "validation_status": "VALIDATED"}

        # Step 1: Associated with Truck
        assoc_truck = {
            "truck_material_associations": [{
                "truck_track_id": 10, "material_track_id": 101, "association_state": "CONFIRMED",
                "association_score": 0.93, "is_ambiguous": False
            }]
        }
        res1, _ = self.service.process_events(tracks=[mat_track, truck_track], material_assocs=assoc_truck, camera_id=cam, frame_index=1, camera_zones=self.zones)
        session = self.service.get_session(cam)
        truck_pair_key = ("ASSOC", "TRUCK", 101, 10)
        self.assertIn(truck_pair_key, session.active_events)
        self.assertEqual(session.active_events[truck_pair_key].status, "ACTIVE")

        # Step 2: Custody transfers to Worker
        assoc_worker = {
            "worker_material_associations": [{
                "worker_track_id": 30, "material_track_id": 101, "association_state": "CONFIRMED",
                "association_score": 0.92, "is_ambiguous": False
            }]
        }
        res2, _ = self.service.process_events(tracks=[mat_track, worker_track], material_assocs=assoc_worker, camera_id=cam, frame_index=2, camera_zones=self.zones)

        # Prior truck association should be COMPLETED with conclusion_reason CUSTODY_HANDOFF_TO_WORKER
        truck_hist = [e for e in session.event_history if e.event_type == EventType.MATERIAL_ASSOCIATED_WITH_TRUCK]
        self.assertTrue(len(truck_hist) >= 1)
        self.assertEqual(truck_hist[-1].status, "COMPLETED")
        self.assertIn("CUSTODY_HANDOFF", truck_hist[-1].evidence.get("conclusion_reason", ""))

        # Worker association is now active
        worker_pair_key = ("ASSOC", "WORKER", 101, 30)
        self.assertIn(worker_pair_key, session.active_events)

    # ------------------------------------------------------------------------
    # Scenario 10: Dispatch movement
    # ------------------------------------------------------------------------
    def test_10_dispatch_movement(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "COMPONENT", "center": [0.85, 0.70], "bbox": [0.80, 0.65, 0.90, 0.75], "identity_id": "CMP-AXL-001", "validation_status": "VALIDATED"}

        # Dwell 1, 2, 3 in DISP-01
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=1, camera_zones=self.zones)
        self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=2, camera_zones=self.zones)
        res, _ = self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=3, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        disp_evs = [e for e in current_events if e.get("event_type") == "MATERIAL_DISPATCHED"]
        self.assertTrue(len(disp_evs) >= 1, f"Expected MATERIAL_DISPATCHED, got: {current_events}")
        self.assertEqual(disp_evs[0]["stage"], "DISPATCH")

    # ------------------------------------------------------------------------
    # Scenario 11: Repeated frames do not duplicate events
    # ------------------------------------------------------------------------
    def test_11_repeated_frames_deduplication(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}

        # Frames 1-3 enter DOCK
        for f in range(1, 4):
            self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)

        session = self.service.get_session(cam)
        history_count_at_frame_3 = len(session.event_history)

        # Frames 4-10 keep same material in same zone
        for f in range(4, 11):
            res, _ = self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=f, camera_zones=self.zones)
            # Event history should NOT grow (no duplicate events created)
            self.assertEqual(len(session.event_history), history_count_at_frame_3, f"Duplicate event added to history on frame {f}")
            # Active events should have exactly 1 entry for this zone
            active_entries = [e for e in res.get("active_events", []) if e.get("event_type") == "MATERIAL_ENTERED_ZONE"]
            self.assertEqual(len(active_entries), 1)

    # ------------------------------------------------------------------------
    # Scenario 12: Insufficient evidence does not create confirmed events (single frame is CANDIDATE)
    # ------------------------------------------------------------------------
    def test_12_single_frame_is_candidate_only(self):
        cam = "CAM-01"
        mat_track = {"track_id": 101, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}

        # Single frame entry
        res, _ = self.service.process_events(tracks=[mat_track], camera_id=cam, frame_index=1, camera_zones=self.zones)

        current_events = res.get("current_events", [])
        # In current_events, if present, it must be CANDIDATE, never ACTIVE
        for e in current_events:
            if e.get("event_type") == "MATERIAL_ENTERED_ZONE":
                self.assertEqual(e.get("status"), "CANDIDATE")
                self.assertTrue(len(e.get("blocking_reasons", [])) > 0)

        # Active events must NOT contain confirmed MATERIAL_ENTERED_ZONE
        session = self.service.get_session(cam)
        confirmed_entry = [e for e in session.active_events.values() if e.event_type == EventType.MATERIAL_ENTERED_ZONE and e.status == "ACTIVE"]
        self.assertEqual(len(confirmed_entry), 0, "Single frame should never produce ACTIVE event")

    # ------------------------------------------------------------------------
    # Scenario 13: Ambiguous/conflicting identity does not create false traceability
    # ------------------------------------------------------------------------
    def test_13_ambiguous_and_conflicting_identity_isolated(self):
        # Create events across cameras:
        # Camera 1 has VALIDATED identity ROD-4140
        # Camera 2 has CONFLICT / AMBIGUOUS identity ROD-4140
        cam1 = "CAM-01"
        cam2 = "CAM-02"

        session1 = self.service.get_session(cam1)
        session2 = self.service.get_session(cam2)

        # Validated event in CAM-01
        ev1 = MovementEvent(
            event_id="EV-1",
            event_type=EventType.MATERIAL_ENTERED_ZONE,
            camera_id=cam1,
            created_frame=1,
            last_seen_frame=1,
            timestamp="2026-10-07T10:00:00Z",
            primary_object={"track_id": 1, "class_code": "ROD", "identity_id": "ROD-4140", "validation_status": "VALIDATED", "identity_status": "VALIDATED"},
            status="ACTIVE"
        )
        session1.event_history.append(ev1)

        # Conflicted event in CAM-02 (ambiguous identity)
        ev2_conflict = MovementEvent(
            event_id="EV-2",
            event_type=EventType.MATERIAL_ENTERED_ZONE,
            camera_id=cam2,
            created_frame=1,
            last_seen_frame=1,
            timestamp="2026-10-07T10:01:00Z",
            primary_object={"track_id": 2, "class_code": "ROD", "identity_id": "ROD-4140", "validation_status": "CONFLICT", "identity_status": "CONFLICT"},
            evidence={"blocking_reasons": ["IDENTITY_CONFLICT_DETECTED"]},
            status="ACTIVE"
        )
        session2.event_history.append(ev2_conflict)

        # Query cross camera timeline
        timeline_res = self.service.get_cross_camera_material_timeline("ROD-4140")
        self.assertTrue(timeline_res["success"])
        # Timeline must only have validated EV-1
        event_ids = [e["event_id"] for e in timeline_res["timeline"]]
        self.assertIn("EV-1", event_ids)
        self.assertNotIn("EV-2", event_ids)
        # Conflicted event must be quarantined in isolated list
        conflicts = timeline_res["conflicting_events_isolated"]
        self.assertTrue(len(conflicts) >= 1)
        self.assertEqual(conflicts[0]["event_id"], "EV-2")

    # ------------------------------------------------------------------------
    # Scenario 14: Cross-camera continuity using explicit barcode/QR/OCR identity
    # ------------------------------------------------------------------------
    def test_14_cross_camera_continuity_via_physical_id(self):
        cam1 = "CAM-DOCK-01"
        cam2 = "CAM-SORT-01"

        session1 = self.service.get_session(cam1)
        session2 = self.service.get_session(cam2)

        # Dock entry at CAM-DOCK-01
        ev_dock = MovementEvent(
            event_id="EV-DOCK-01",
            event_type=EventType.MATERIAL_ENTERED_ZONE,
            camera_id=cam1,
            created_frame=10,
            last_seen_frame=10,
            timestamp="2026-10-07T10:00:00Z",
            primary_object={"track_id": 101, "class_code": "GLASS", "identity_id": "GLS-WND-88", "validation_status": "VALIDATED"},
            zone={"zone_code": "DOCK-01", "zone_name": "Dock 01"},
            stage="DOCK",
            status="ACTIVE"
        )
        session1.event_history.append(ev_dock)

        # Sorting arrival at CAM-SORT-01 (different camera, different track_id 505, identical physical identity)
        ev_sort = MovementEvent(
            event_id="EV-SORT-01",
            event_type=EventType.MATERIAL_MOVED_TO_SORTING,
            camera_id=cam2,
            created_frame=50,
            last_seen_frame=50,
            timestamp="2026-10-07T10:05:00Z",
            primary_object={"track_id": 505, "class_code": "GLASS", "identity_id": "GLS-WND-88", "validation_status": "VALIDATED"},
            zone={"zone_code": "SORT-01", "zone_name": "Sorting 01"},
            stage="SORTING",
            status="ACTIVE"
        )
        session2.event_history.append(ev_sort)

        timeline_res = self.service.get_cross_camera_material_timeline("GLS-WND-88")
        self.assertTrue(timeline_res["success"])
        self.assertEqual(len(timeline_res["timeline"]), 2)
        self.assertEqual(timeline_res["cameras_visited"], ["CAM-DOCK-01", "CAM-SORT-01"])
        self.assertEqual(timeline_res["timeline"][0]["camera_id"], "CAM-DOCK-01")
        self.assertEqual(timeline_res["timeline"][1]["camera_id"], "CAM-SORT-01")

    # ------------------------------------------------------------------------
    # Scenario 15: Existing BOX and BOX_UNLOADED_AT_DOCK regression
    # ------------------------------------------------------------------------
    def test_15_legacy_box_and_unloading_regression(self):
        # Run legacy dock_loading synthetic sequence
        res = self.service.run_synthetic_sequence(camera_id="CAM-LEGACY", sequence_name="dock_loading")
        self.assertTrue(res["success"])
        self.assertEqual(res["total_frames"], 8)
        gen_types = res["summary"]["generated_event_types"]

        # Ensure legacy event types are produced
        self.assertIn("BOX_ENTERED_ZONE", gen_types)
        self.assertIn("BOX_ASSOCIATED_WITH_TRUCK", gen_types)
        self.assertIn("BOX_ASSOCIATED_WITH_WORKER", gen_types)
        self.assertIn("BOX_ASSOCIATED_WITH_BIN", gen_types)
        self.assertIn("BOX_EXITED_ZONE", gen_types)

        # Verify synthetic sequence automotive_warehouse_flow
        res_auto = self.service.run_synthetic_sequence(camera_id="CAM-AUTO", sequence_name="automotive_warehouse_flow")
        self.assertTrue(res_auto["success"])
        auto_types = res_auto["summary"]["generated_event_types"]
        self.assertIn("MATERIAL_ENTERED_ZONE", auto_types)
        self.assertIn("MATERIAL_ASSOCIATED_WITH_TRUCK", auto_types)
        self.assertIn("MATERIAL_UNLOADED_AT_DOCK", auto_types)
        self.assertIn("MATERIAL_ASSOCIATED_WITH_WORKER", auto_types)
        self.assertIn("MATERIAL_MOVED_TO_SORTING", auto_types)
        self.assertIn("MATERIAL_ENTERED_STAGING", auto_types)
        self.assertIn("MATERIAL_STORED_IN_BIN", auto_types)
        self.assertIn("MATERIAL_EXITED_ZONE", auto_types)
        self.assertIn("MATERIAL_DISPATCHED", auto_types)

    # ------------------------------------------------------------------------
    # Scenario 16: Inventory remains unchanged (17 tables, 0 inventory writes)
    # ------------------------------------------------------------------------
    def test_16_inventory_remains_unchanged(self):
        db_path = os.path.join(os.path.dirname(__file__), "..", "webapp", "skandha_wms.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check table count is exactly 17
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        self.assertEqual(len(tables), 17, f"Database table count altered! Expected 17, found {len(tables)}: {tables}")

        # Check inventory rows is 0
        cur.execute("SELECT COUNT(*) FROM inventory")
        inv_count = cur.fetchone()[0]
        self.assertEqual(inv_count, 0, f"Inventory records found! Expected 0, found {inv_count}")

        conn.close()


if __name__ == "__main__":
    unittest.main()
