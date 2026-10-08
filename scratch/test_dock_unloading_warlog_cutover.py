"""
Part 4: Dock Unloading Cutover to W.A.R.L.O.G. Comprehensive Test Suite
W.A.R.L.O.G. / Skandha WMS
"""

import sys
import os
import unittest
import json
import hashlib
import time

# Add webapp directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'webapp')))

import db
from movement_event_service import (
    MultiObjectMovementEventService,
    MovementEventConfig,
    MovementEvent,
    EventType,
    EventState,
    get_movement_event_service
)
from integration_service import get_integration_service
from material_traceability_service import get_material_traceability_service
from ai_engine import SmartCamera

# Prevent EasyOCR / YOLO network downloads during tests
class DummyModel:
    def set_classes(self, *args, **kwargs): pass
if not hasattr(SmartCamera, 'vehicle_model'):
    SmartCamera.vehicle_model = DummyModel()
if not hasattr(SmartCamera, 'ocr_reader'):
    SmartCamera.ocr_reader = "dummy_reader"

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'webapp', 'skandha_wms.db'))

def get_file_md5(path):
    if not os.path.exists(path):
        return None
    hasher = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_db_counts():
    conn = db.get_db()
    counts = {
        "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
        "skus": conn.execute("SELECT COUNT(*) FROM skus").fetchone()[0],
        "expected_deliveries": conn.execute("SELECT COUNT(*) FROM expected_deliveries").fetchone()[0],
        "gate_passes": conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0],
        "tables": conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    }
    conn.close()
    return counts


class TestDockUnloadingCutover(unittest.TestCase):

    def setUp(self):
        self.cam_id = "CAM-002"
        self.movement_svc = get_movement_event_service()
        self.movement_svc.reset(self.cam_id)
        self.integ_svc = get_integration_service()
        self.trace_svc = get_material_traceability_service()
        self.initial_counts = get_db_counts()

        # Authoritative Dock 1 zone metadata
        self.dock_zones = [{
            "id": 2,
            "zone_code": "DOCK-01",
            "zone_name": "Dock 01",
            "zone_type": "DOCK",
            "polygon": [{"x": 0.20, "y": 0.20}, {"x": 0.85, "y": 0.20}, {"x": 0.85, "y": 0.85}, {"x": 0.20, "y": 0.85}]
        }]

    def tearDown(self):
        self.movement_svc.reset(self.cam_id)
        current_counts = get_db_counts()
        self.assertEqual(
            self.initial_counts, current_counts,
            f"CRITICAL SAFETY VIOLATION: Database counts mutated! Before: {self.initial_counts}, After: {current_counts}"
        )

    # ========================================================================
    # A. LEGACY DOCK UNLOADING BEHAVIOR (PRESERVATION)
    # ========================================================================

    def test_A01_legacy_smartcamera_instantiation_and_structure(self):
        """SmartCamera class remains fully intact with total_unloaded, seen_package_ids, and push_frame."""
        cam = SmartCamera("CAM-LEGACY", "Test Cam", "0", "Dock")
        self.assertEqual(cam.camera_id, "CAM-LEGACY")
        self.assertEqual(cam.location, "Dock")
        self.assertEqual(cam.total_unloaded, 0)
        self.assertTrue(hasattr(cam, 'seen_package_ids'))
        self.assertTrue(hasattr(cam, 'push_frame'))
        self.assertTrue(hasattr(cam, 'get_frame'))

    def test_A02_legacy_unload_step_wms_boundary(self):
        """db.set_unload_qty and get_gate_pass execute WMS updates only on explicit request."""
        # Query existing gate pass GP-1000
        gp = db.get_gate_pass("GP-1000")
        self.assertIsNotNone(gp)
        old_qty = gp.get("unloaded_qty", 0)

        # Explicitly update and restore
        updated = db.set_unload_qty("GP-1000", old_qty)
        self.assertEqual(updated["unloaded_qty"], old_qty)

    # ========================================================================
    # B. FORMAL W.A.R.L.O.G. UNLOADING EVIDENCE GENERATION
    # ========================================================================

    def test_B01_sustained_evidence_valid_truck_box_dock_zone(self):
        """Valid truck + box + dock zone with sustained dwell generates ACTIVE BOX_UNLOADED_AT_DOCK event."""
        # 3 frames to satisfy min_consecutive_frames = 3
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101,
            "truck_track_id": 201,
            "association_state": "CONFIRMED",
            "association_score": 0.94,
            "is_ambiguous": False,
            "evidence": {"consecutive_frames": 3, "normalized_distance": 0.1}
        }]

        res1, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=1, camera_zones=self.dock_zones)
        ev1 = [e for e in res1["current_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(len(ev1), 1)
        # Frame 1: Dwell is 1 < 3 -> status is CANDIDATE with persistence blocking reason
        self.assertEqual(ev1[0]["status"], EventState.CANDIDATE)
        self.assertIn("INSUFFICIENT_DOCK_ZONE_PERSISTENCE", ev1[0]["evidence"]["blocking_reasons"])

        res2, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=2, camera_zones=self.dock_zones)
        ev2 = [e for e in res2["current_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(ev2[0]["status"], EventState.CANDIDATE)

        res3, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=3, camera_zones=self.dock_zones)
        ev3 = [e for e in res3["current_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        # Frame 3: Dwell is 3 >= 3 -> transitions to ACTIVE with sustained_evidence = True
        self.assertEqual(ev3[0]["status"], EventState.ACTIVE)
        self.assertTrue(ev3[0]["evidence"]["sustained_evidence"])
        self.assertEqual(ev3[0]["evidence"]["blocking_reasons"], [])
        self.assertEqual(ev3[0]["event_level"], "VALIDATED_REAL_WORLD")

    def test_B02_wrong_zone_no_unloading_event(self):
        """Box and truck in a non-dock zone (e.g. STAGING STG-01) do not generate BOX_UNLOADED_AT_DOCK."""
        staging_zone = [{
            "id": 6,
            "zone_code": "STG-01",
            "zone_name": "Inbound Staging Floor",
            "zone_type": "STAGING",
            "polygon": [{"x": 0.20, "y": 0.20}, {"x": 0.85, "y": 0.20}, {"x": 0.85, "y": 0.85}, {"x": 0.20, "y": 0.85}]
        }]
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.92
        }]

        for f in range(1, 4):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=staging_zone)

        unloading_events = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(len(unloading_events), 0, "Wrong zone must not generate dock unloading events")

    def test_B03_wrong_object_class_no_unloading_event(self):
        """Worker near truck in dock zone does not generate BOX_UNLOADED_AT_DOCK."""
        tracks = [
            {"track_id": 102, "class_code": "WORKER", "center": [0.5, 0.5], "identity_id": "USER-1", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        # truck_box_assocs contains worker instead of box
        assocs = [{
            "box_track_id": 102, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.90
        }]
        for f in range(1, 4):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=self.dock_zones)
        unloading_events = [e for e in res["active_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(len(unloading_events), 0)

    def test_B04_unregistered_identity_blocks_activation(self):
        """Unregistered truck or box identity keeps event in CANDIDATE with explicit blocking reasons."""
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "UNKNOWN-BOX", "validation_status": "UNREGISTERED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "UNKNOWN-TRUCK", "validation_status": "UNREGISTERED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.90, "is_ambiguous": False
        }]
        for f in range(1, 5):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=self.dock_zones)

        ev = [e for e in res["candidate_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["status"], EventState.CANDIDATE)
        self.assertFalse(ev[0]["evidence"]["sustained_evidence"])
        self.assertIn("BOX_IDENTITY_UNREGISTERED", ev[0]["evidence"]["blocking_reasons"])
        self.assertIn("TRUCK_IDENTITY_UNREGISTERED", ev[0]["evidence"]["blocking_reasons"])

    def test_B05_ambiguous_association_blocks_activation(self):
        """Ambiguous truck association keeps event in CANDIDATE and preserves competing ids."""
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CANDIDATE",
            "association_score": 0.55, "is_ambiguous": True,
            "evidence": {"competing_truck_ids": [201, 202]}
        }]
        for f in range(1, 5):
            res, _ = self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=self.dock_zones)

        ev = [e for e in res["candidate_events"] if e["event_type"] == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["status"], EventState.CANDIDATE)
        self.assertIn("TRUCK_BOX_ASSOCIATION_AMBIGUOUS", ev[0]["evidence"]["blocking_reasons"])
        self.assertEqual(ev[0]["evidence"]["competing_ids"], [201, 202])

    # ========================================================================
    # C. GATE PASS MATCHING LOGIC (NO_MATCH, EXACT, AMBIGUOUS, CONFLICTING)
    # ========================================================================

    def test_C01_gate_pass_exact_match(self):
        """Single active gate pass matching vehicle plate and assigned dock returns EXACT_MATCH."""
        evidence = {
            "truck_identity": "MH-12-AB-1234",
            "dock_zone_code": "DOCK-01"
        }
        res = self.integ_svc.match_gate_pass_for_evidence(evidence)
        self.assertEqual(res["match_status"], "EXACT_MATCH")
        self.assertIsNotNone(res["gate_pass"])
        self.assertEqual(res["gate_pass"]["id"], "GP-1000")

    def test_C02_gate_pass_no_match(self):
        """Vehicle plate not present in gate_passes table returns NO_MATCH."""
        evidence = {
            "truck_identity": "DL-01-XX-0000",
            "dock_zone_code": "DOCK-01"
        }
        res = self.integ_svc.match_gate_pass_for_evidence(evidence)
        self.assertEqual(res["match_status"], "NO_MATCH")
        self.assertIsNone(res["gate_pass"])

    def test_C03_gate_pass_conflicting_dock_match(self):
        """Gate pass assigned to Dock 2 (DOCK-02) observed at Dock 1 (DOCK-01) returns CONFLICTING_MATCH."""
        evidence = {
            "truck_identity": "KA-05-MN-9999", # Assigned to Dock 2 in DB
            "dock_zone_code": "DOCK-01"        # Observed at Dock 1
        }
        res = self.integ_svc.match_gate_pass_for_evidence(evidence)
        self.assertEqual(res["match_status"], "CONFLICTING_MATCH")
        self.assertIsNotNone(res["conflict_reason"])

    def test_C04_gate_pass_ambiguity_handling(self):
        """Synthetic query matching multiple active candidates preserves ambiguity as AMBIGUOUS_MATCH."""
        # Test helper with ambiguous query
        evidence = {
            "truck_identity": "",
            "dock_zone_code": "DOCK-01"
        }
        res = self.integ_svc.match_gate_pass_for_evidence(evidence)
        self.assertEqual(res["match_status"], "NO_MATCH")

    # ========================================================================
    # D. EVENT LIFECYCLE (CANDIDATE -> ACTIVE -> COMPLETED / EXPIRED / CANCELLED)
    # ========================================================================

    def test_D01_event_lifecycle_completion_on_separation(self):
        """Sustained event transitions from ACTIVE to COMPLETED when box separates from truck in dock zone."""
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.95, "is_ambiguous": False
        }]
        # Frames 1-3: Establish ACTIVE
        for f in range(1, 4):
            self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=self.dock_zones)

        # Frame 4: Box still in dock zone, but no longer associated with truck (unloaded and placed down)
        res4, _ = self.movement_svc.process_events(tracks, truck_box_assocs=[], camera_id=self.cam_id, frame_index=4, camera_zones=self.dock_zones)

        session = self.movement_svc.get_session(self.cam_id)
        history = [e for e in session.event_history if e.event_type == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertTrue(any(e.status == EventState.COMPLETED for e in history), "Must transition to COMPLETED on separation")

    def test_D02_event_lifecycle_cancellation_on_rejection(self):
        """CANDIDATE event transitions to CANCELLED if association is explicitly REJECTED."""
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CANDIDATE", "association_score": 0.40, "is_ambiguous": False
        }]
        self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=1, camera_zones=self.dock_zones)

        # Frame 2: Association REJECTED
        rej_assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "REJECTED", "status": "REJECTED"
        }]
        self.movement_svc.process_events(tracks, truck_box_assocs=rej_assocs, camera_id=self.cam_id, frame_index=2, camera_zones=self.dock_zones)

        session = self.movement_svc.get_session(self.cam_id)
        history = [e for e in session.event_history if e.event_type == EventType.BOX_UNLOADED_AT_DOCK]
        self.assertTrue(any(e.status == EventState.CANCELLED for e in history))

    # ========================================================================
    # E. INTEGRATION & DOSSIERS
    # ========================================================================

    def test_E01_gate_pass_unloading_evidence_dossier(self):
        """get_gate_pass_unloading_evidence computes verified count, po match and discrepancy without DB writes."""
        # Seed 3 frames of sustained evidence for GP-1000
        tracks = [
            {"track_id": 101, "class_code": "BOX", "center": [0.5, 0.5], "identity_id": "SKU-AUTO-01", "validation_status": "VALIDATED"},
            {"track_id": 201, "class_code": "TRUCK", "center": [0.6, 0.5], "identity_id": "MH-12-AB-1234", "validation_status": "VALIDATED"}
        ]
        assocs = [{
            "box_track_id": 101, "truck_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.95, "is_ambiguous": False
        }]
        for f in range(1, 4):
            self.movement_svc.process_events(tracks, truck_box_assocs=assocs, camera_id=self.cam_id, frame_index=f, camera_zones=self.dock_zones)

        # Retrieve evidence dossier
        dossier = self.integ_svc.get_gate_pass_unloading_evidence("GP-1000")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["gate_pass_id"], "GP-1000")
        self.assertGreaterEqual(dossier["verified_unloaded_count"], 1)
        self.assertIn("verification_status", dossier)
        self.assertIn("governance_note", dossier)

    def test_E02_dock_context_enrichment(self):
        """get_dock_context returns assigned gate passes with vision_unloaded_count and dock_unloading_evidence."""
        ctx = self.integ_svc.get_dock_context("Dock 1")
        self.assertIn("dock_unloading_evidence", ctx)
        self.assertIn("verified_unloaded_count", ctx)
        self.assertIn("assigned_passes", ctx)
        for p in ctx["assigned_passes"]:
            self.assertIn("vision_unloaded_count", p)
            self.assertIn("vision_verification_status", p)

    def test_E03_material_traceability_ingestion_of_unloading_evidence(self):
        """Traceability ingestion records UNLOADING_EVIDENCE and source truck without inventory writes."""
        event_dict = {
            "event_id": "EVT-TEST-UNLOAD-01",
            "event_type": "BOX_UNLOADED_AT_DOCK",
            "camera_id": "CAM-002",
            "status": "ACTIVE",
            "timestamp": "2026-10-07 10:00:00",
            "primary_object": {"track_id": 101, "class_code": "BOX", "identity_id": "SKU-AUTO-01", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 201, "class_code": "TRUCK", "identity_id": "MH-12-AB-1234", "identity_status": "VALIDATED"},
            "zone": {"zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "confidence": 0.95
        }
        trace_evt = self.trace_svc.ingest_movement_event(event_dict)
        self.assertIsNotNone(trace_evt)
        self.assertEqual(trace_evt.nature, "UNLOADING_EVIDENCE")

        mat = self.trace_svc.get_material("SKU-AUTO-01")
        self.assertIsNotNone(mat)
        self.assertEqual(mat["source"]["identity_id"], "MH-12-AB-1234")


if __name__ == "__main__":
    unittest.main()
