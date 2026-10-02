"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 13 — Material Traceability Backend Verification Suite

Comprehensive deterministic test suite covering:
1. Service initialization & configuration
2. Material trace record instantiation
3. Event ingestion & nature classification (OBSERVED, VALIDATED)
4. Zone history tracking (ENTER and EXIT transitions)
5. Truck association relationship tracking
6. Worker association relationship tracking
7. Bin association relationship tracking
8. Source derivation from confirmed truck association
9. Destination derivation from confirmed bin association
10. Incomplete trace handling (honest representation of missing data)
11. Validated identity handling (VALIDATED_REAL_WORLD)
12. Unidentified track-level trace handling (TRACK_LEVEL)
13. Event deduplication by event_id (single event processed twice)
14. Chronological ordering (out-of-order timestamp ingestion)
15. Multi-material isolation (B104, B105, B106, B107 independent)
16. Conflict preservation (T1 then T2 candidate sources)
17. Cross-camera identity-based trace unification (CAM-001 & CAM-003)
18. Cross-camera track isolation (unidentified tracks remain separate)
19. Session reset behavior & clean memory recovery
20. Malformed event input resilience
21. REST API endpoints verification
22. Complete 7-frame deterministic end-to-end trace sequence
23. Bounded memory behavior (max materials, max timeline entries)
24. Zero database writes & schema integrity verification (MD5 Checksum)
"""

import os
import sys
import copy
import json
import time
import hashlib
import unittest
from datetime import datetime, timezone

# Ensure webapp directory is in python path
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(WORKSPACE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import app as flask_app_module
from material_traceability_service import (
    MaterialTraceabilityService,
    get_material_traceability_service,
    TraceabilityLevel,
    MaterialTraceStatus,
    TraceabilityConfig,
    MaterialTraceRecord,
    MaterialTraceEvent
)
from movement_event_service import EventType, EventState

DB_PATH = os.path.join(WEBAPP_DIR, "skandha_wms.db")


def get_db_md5() -> str:
    """Calculate MD5 checksum of the SQLite database."""
    if not os.path.exists(DB_PATH):
        return ""
    with open(DB_PATH, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class TestMaterialTraceabilityBackend(unittest.TestCase):
    """Exhaustive test suite for Part 13 Material Traceability Foundation."""

    @classmethod
    def setUpClass(cls):
        cls.db_md5_initial = get_db_md5()
        cls.client = flask_app_module.app.test_client()
        cls.service = get_material_traceability_service()

    def setUp(self):
        self.service.reset()

    def tearDown(self):
        self.service.reset()

    @classmethod
    def tearDownClass(cls):
        final_md5 = get_db_md5()
        assert cls.db_md5_initial == final_md5, f"DATABASE WRITE DETECTED! Initial: {cls.db_md5_initial}, Final: {final_md5}"

    # ------------------------------------------------------------------------
    # Test 01: Service Initialization & Configuration
    # ------------------------------------------------------------------------
    def test_01_service_initialization(self):
        status = self.service.get_status()
        self.assertEqual(status["service"], "MaterialTraceabilityService")
        self.assertEqual(status["version"], "1.0.0-part13")
        self.assertIn("STRICTLY_IN_MEMORY", status["storage"])
        self.assertEqual(status["total_materials_tracked"], 0)
        self.assertEqual(status["total_timeline_events"], 0)
        self.assertEqual(self.service.config.max_materials, 500)
        self.assertEqual(self.service.config.max_timeline_entries, 100)

    # ------------------------------------------------------------------------
    # Test 02: Material Trace Creation
    # ------------------------------------------------------------------------
    def test_02_material_trace_creation(self):
        evt = {
            "event_id": "EVT-TEST-001",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 104,
                "class_code": "BOX",
                "identity_id": "B104",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "confidence": 0.95,
            "status": "ACTIVE",
            "event_level": "VALIDATED_REAL_WORLD"
        }
        res = self.service.ingest_movement_event(evt)
        self.assertIsNotNone(res)
        self.assertEqual(res.material_id, "B104")
        self.assertEqual(res.trace_level, TraceabilityLevel.VALIDATED_REAL_WORLD)
        self.assertEqual(res.nature, "VALIDATED")

        dossier = self.service.get_material("B104")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["material_id"], "B104")
        self.assertEqual(dossier["identity_status"], "VALIDATED")
        self.assertEqual(dossier["traceability_status"], MaterialTraceStatus.AT_ZONE)

    # ------------------------------------------------------------------------
    # Test 03: Event Ingestion & Nature Classification
    # ------------------------------------------------------------------------
    def test_03_event_ingestion_and_nature(self):
        # 1. Validated event
        e1 = {
            "event_id": "EVT-V01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:01Z",
            "primary_object": {"track_id": 1, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 1, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        }
        res1 = self.service.ingest_movement_event(e1)
        self.assertEqual(res1.nature, "VALIDATED")

        # 2. Identified but unregistered event
        e2 = {
            "event_id": "EVT-U01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:02Z",
            "primary_object": {"track_id": 2, "class_code": "BOX", "identity_id": "UNKNOWN_BOX", "identity_status": "UNREGISTERED"},
            "zone": {"zone_id": 1, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        }
        res2 = self.service.ingest_movement_event(e2)
        self.assertEqual(res2.nature, "OBSERVED")
        self.assertEqual(res2.trace_level, TraceabilityLevel.IDENTIFIED)

    # ------------------------------------------------------------------------
    # Test 04: Box Zone History (Enter & Exit)
    # ------------------------------------------------------------------------
    def test_04_box_zone_history(self):
        # Enter Dock 01
        self.service.ingest_movement_event({
            "event_id": "EVT-Z01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:14Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        })

        # Exit Dock 01
        self.service.ingest_movement_event({
            "event_id": "EVT-Z02",
            "event_type": "BOX_EXITED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:04:12Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "COMPLETED"
        })

        dossier = self.service.get_material("B104")
        zh = dossier["zone_history"]
        self.assertEqual(len(zh), 2)
        self.assertEqual(zh[0]["transition"], "ENTER")
        self.assertEqual(zh[0]["zone_code"], "DOCK-01")
        self.assertEqual(zh[1]["transition"], "EXIT")
        self.assertEqual(zh[1]["zone_code"], "DOCK-01")
        self.assertEqual(dossier["traceability_status"], MaterialTraceStatus.IN_TRANSIT)

    # ------------------------------------------------------------------------
    # Test 05: Truck Association Relationship
    # ------------------------------------------------------------------------
    def test_05_truck_relationship(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-TRK-01",
            "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:25Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "confidence": 0.92,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertEqual(len(dossier["associated_trucks"]), 1)
        trk = dossier["associated_trucks"][0]
        self.assertEqual(trk["identity_id"], "GP-1000")
        self.assertEqual(trk["score"], 0.92)

    # ------------------------------------------------------------------------
    # Test 06: Worker Association Relationship
    # ------------------------------------------------------------------------
    def test_06_worker_relationship(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-WRK-01",
            "event_type": "BOX_ASSOCIATED_WITH_WORKER",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:35Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 7, "class_code": "WORKER", "identity_id": "W07", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "confidence": 0.89,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertEqual(len(dossier["associated_workers"]), 1)
        w = dossier["associated_workers"][0]
        self.assertEqual(w["identity_id"], "W07")
        self.assertEqual(w["score"], 0.89)

    # ------------------------------------------------------------------------
    # Test 07: Bin Association Relationship
    # ------------------------------------------------------------------------
    def test_07_bin_relationship(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-BIN-01",
            "event_type": "BOX_ASSOCIATED_WITH_BIN",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:05:30Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 99, "class_code": "BIN", "identity_id": "BIN-A101", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 8, "zone_code": "BIN-AREA", "zone_name": "Storage Bin Area A"},
            "confidence": 0.96,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertEqual(len(dossier["associated_bins"]), 1)
        b = dossier["associated_bins"][0]
        self.assertEqual(b["identity_id"], "BIN-A101")
        self.assertEqual(b["score"], 0.96)

    # ------------------------------------------------------------------------
    # Test 08: Source Derivation from Confirmed Truck Association
    # ------------------------------------------------------------------------
    def test_08_source_derivation(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-SRC-01",
            "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:25Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
            "confidence": 0.92,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertIsNotNone(dossier["source"])
        self.assertEqual(dossier["source"]["identity_id"], "GP-1000")
        self.assertEqual(dossier["source"]["type"], "TRUCK")
        self.assertEqual(dossier["source"]["validation_status"], "VALIDATED")

    # ------------------------------------------------------------------------
    # Test 09: Destination Derivation from Confirmed Bin Association
    # ------------------------------------------------------------------------
    def test_09_destination_derivation(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-DST-01",
            "event_type": "BOX_ASSOCIATED_WITH_BIN",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:05:30Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 99, "class_code": "BIN", "identity_id": "BIN-A101", "identity_status": "VALIDATED"},
            "confidence": 0.96,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertIsNotNone(dossier["destination"])
        self.assertEqual(dossier["destination"]["identity_id"], "BIN-A101")
        self.assertEqual(dossier["destination"]["type"], "BIN")
        self.assertEqual(dossier["traceability_status"], MaterialTraceStatus.DESTINATION_OBSERVED)

    # ------------------------------------------------------------------------
    # Test 10: Incomplete Trace Handling (No Forced Source/Destination)
    # ------------------------------------------------------------------------
    def test_10_incomplete_trace(self):
        # Material B200: Identified but no truck association
        self.service.ingest_movement_event({
            "event_id": "EVT-INC-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:10:00Z",
            "primary_object": {"track_id": 200, "class_code": "BOX", "identity_id": "B200", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B200")
        self.assertIsNone(dossier["source"])
        self.assertIsNone(dossier["destination"])
        self.assertEqual(len(dossier["associated_trucks"]), 0)
        self.assertEqual(len(dossier["associated_bins"]), 0)
        self.assertEqual(dossier["current_location"]["zone_code"], "DOCK-01")

    # ------------------------------------------------------------------------
    # Test 11: Validated Real-World Level
    # ------------------------------------------------------------------------
    def test_11_validated_identity(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-VAL-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:12:00Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertEqual(dossier["traceability_level"], TraceabilityLevel.VALIDATED_REAL_WORLD)
        self.assertEqual(dossier["identity_status"], "VALIDATED")

    # ------------------------------------------------------------------------
    # Test 12: Unidentified Track-Level Trace
    # ------------------------------------------------------------------------
    def test_12_unidentified_track_level_trace(self):
        self.service.ingest_movement_event({
            "event_id": "EVT-TRK-LVL-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:15:00Z",
            "primary_object": {"track_id": 88, "class_code": "BOX", "identity_id": None, "identity_status": "UNIDENTIFIED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        })

        track_key = "TRACK_CAM-001_88"
        dossier = self.service.get_material(track_key)
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["traceability_level"], TraceabilityLevel.TRACK_LEVEL)
        self.assertEqual(dossier["identity_status"], "UNIDENTIFIED")

    # ------------------------------------------------------------------------
    # Test 13: Event Deduplication by event_id
    # ------------------------------------------------------------------------
    def test_13_event_deduplication(self):
        evt = {
            "event_id": "EVT-DEDUP-001",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:20:00Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        }

        res1 = self.service.ingest_movement_event(evt)
        self.assertIsNotNone(res1)

        # Ingest exact same event second time
        res2 = self.service.ingest_movement_event(evt)
        self.assertIsNone(res2)  # Strictly skipped duplicate

        dossier = self.service.get_material("B104")
        self.assertEqual(len(dossier["timeline"]), 1)
        self.assertEqual(dossier["event_ids"], ["EVT-DEDUP-001"])

    # ------------------------------------------------------------------------
    # Test 14: Chronological Ordering (Out-of-Order Timestamps)
    # ------------------------------------------------------------------------
    def test_14_chronological_ordering(self):
        # Ingest events in non-chronological order: 10:05, 10:02, 10:04
        e_1005 = {
            "event_id": "EVT-ORD-03",
            "event_type": "BOX_ASSOCIATED_WITH_BIN",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:05:00Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "status": "ACTIVE"
        }
        e_1002 = {
            "event_id": "EVT-ORD-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:00Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "status": "ACTIVE"
        }
        e_1004 = {
            "event_id": "EVT-ORD-02",
            "event_type": "BOX_EXITED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:04:00Z",
            "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "status": "ACTIVE"
        }

        self.service.ingest_movement_event(e_1005)
        self.service.ingest_movement_event(e_1002)
        self.service.ingest_movement_event(e_1004)

        timeline = self.service.get_timeline("B104")
        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["timestamp"], "2026-10-02T10:02:00Z")
        self.assertEqual(timeline[1]["timestamp"], "2026-10-02T10:04:00Z")
        self.assertEqual(timeline[2]["timestamp"], "2026-10-02T10:05:00Z")

    # ------------------------------------------------------------------------
    # Test 15: Multi-Material Isolation
    # ------------------------------------------------------------------------
    def test_15_multi_material_isolation(self):
        materials = ["B104", "B105", "B106", "B107"]
        for idx, mat in enumerate(materials):
            self.service.ingest_movement_event({
                "event_id": f"EVT-MULTI-{idx}",
                "event_type": "BOX_ENTERED_ZONE",
                "camera_id": "CAM-001",
                "timestamp": f"2026-10-02T10:30:{idx:02d}Z",
                "primary_object": {"track_id": 100 + idx, "class_code": "BOX", "identity_id": mat, "identity_status": "VALIDATED"},
                "zone": {"zone_id": idx + 1, "zone_code": f"ZONE-0{idx+1}", "zone_name": f"Zone {idx+1}"},
                "status": "ACTIVE"
            })

        self.assertEqual(len(self.service.materials), 4)
        for idx, mat in enumerate(materials):
            d = self.service.get_material(mat)
            self.assertEqual(d["material_id"], mat)
            self.assertEqual(d["current_location"]["zone_code"], f"ZONE-0{idx+1}")
            self.assertEqual(len(d["timeline"]), 1)

    # ------------------------------------------------------------------------
    # Test 16: Conflict Preservation (Candidate Sources T1 & T2)
    # ------------------------------------------------------------------------
    def test_16_conflict_preservation(self):
        # Event 1: Box B300 associated with Truck T1
        self.service.ingest_movement_event({
            "event_id": "EVT-CONF-01",
            "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:40:00Z",
            "primary_object": {"track_id": 300, "class_code": "BOX", "identity_id": "B300", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 10, "class_code": "TRUCK", "identity_id": "T1", "identity_status": "VALIDATED"},
            "confidence": 0.90,
            "status": "ACTIVE"
        })

        # Event 2: Later associated with Truck T2 (Conflict!)
        self.service.ingest_movement_event({
            "event_id": "EVT-CONF-02",
            "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:41:00Z",
            "primary_object": {"track_id": 300, "class_code": "BOX", "identity_id": "B300", "identity_status": "VALIDATED"},
            "secondary_object": {"track_id": 11, "class_code": "TRUCK", "identity_id": "T2", "identity_status": "VALIDATED"},
            "confidence": 0.88,
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B300")
        self.assertEqual(len(dossier["candidate_sources"]), 2)
        c_ids = [c["identity_id"] for c in dossier["candidate_sources"]]
        self.assertIn("T1", c_ids)
        self.assertIn("T2", c_ids)

    # ------------------------------------------------------------------------
    # Test 17: Cross-Camera Identity-Based Trace Unification
    # ------------------------------------------------------------------------
    def test_17_cross_camera_identity_trace(self):
        # Sighted on CAM-001 with barcode B104
        self.service.ingest_movement_event({
            "event_id": "EVT-CAM1-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:14Z",
            "primary_object": {"track_id": 17, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "status": "ACTIVE"
        })

        # Sighted on CAM-003 with barcode B104 (diff track_id 42)
        self.service.ingest_movement_event({
            "event_id": "EVT-CAM3-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-003",
            "timestamp": "2026-10-02T10:05:41Z",
            "primary_object": {"track_id": 42, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
            "zone": {"zone_id": 8, "zone_code": "STAGING-02", "zone_name": "Staging 02"},
            "status": "ACTIVE"
        })

        dossier = self.service.get_material("B104")
        self.assertEqual(len(dossier["camera_observations"]), 2)
        self.assertEqual(dossier["camera_tracks"]["CAM-001"], 17)
        self.assertEqual(dossier["camera_tracks"]["CAM-003"], 42)
        self.assertEqual(len(dossier["timeline"]), 2)

    # ------------------------------------------------------------------------
    # Test 18: Cross-Camera Track Isolation (Unidentified Tracks Separate)
    # ------------------------------------------------------------------------
    def test_18_cross_camera_track_isolation(self):
        # CAM-001 track 17 without identity
        self.service.ingest_movement_event({
            "event_id": "EVT-ISO-01",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:14Z",
            "primary_object": {"track_id": 17, "class_code": "BOX", "identity_id": None, "identity_status": "UNIDENTIFIED"},
            "status": "ACTIVE"
        })

        # CAM-003 track 42 without identity
        self.service.ingest_movement_event({
            "event_id": "EVT-ISO-02",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-003",
            "timestamp": "2026-10-02T10:05:41Z",
            "primary_object": {"track_id": 42, "class_code": "BOX", "identity_id": None, "identity_status": "UNIDENTIFIED"},
            "status": "ACTIVE"
        })

        # Must remain 2 separate isolated material records
        self.assertEqual(len(self.service.materials), 2)
        self.assertIn("TRACK_CAM-001_17", self.service.materials)
        self.assertIn("TRACK_CAM-003_42", self.service.materials)

    # ------------------------------------------------------------------------
    # Test 19: Session Reset Behavior
    # ------------------------------------------------------------------------
    def test_19_reset_behavior(self):
        self.service.run_synthetic_sequence()
        self.assertGreater(len(self.service.materials), 0)

        res = self.service.reset()
        self.assertTrue(res["success"])
        self.assertEqual(len(self.service.materials), 0)
        self.assertEqual(len(self.service.track_to_material), 0)
        self.assertEqual(self.service.trace_counter, 0)

    # ------------------------------------------------------------------------
    # Test 20: Malformed Input Handling
    # ------------------------------------------------------------------------
    def test_20_malformed_input(self):
        # Missing event_id
        res1 = self.service.ingest_movement_event({"event_type": "BOX_ENTERED_ZONE", "primary_object": {"track_id": 1}})
        self.assertIsNone(res1)

        # Missing primary_object
        res2 = self.service.ingest_movement_event({"event_id": "EVT-ERR", "event_type": "BOX_ENTERED_ZONE"})
        self.assertIsNone(res2)

        # None input
        res3 = self.service.ingest_movement_event({})
        self.assertIsNone(res3)

    # ------------------------------------------------------------------------
    # Test 21: REST API Endpoints Verification
    # ------------------------------------------------------------------------
    def test_21_api_endpoints(self):
        # 1. GET /status
        r = self.client.get('/api/vision/traceability/status')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["service"], "MaterialTraceabilityService")

        # 2. POST /sequence
        r_seq = self.client.post('/api/vision/traceability/sequence', json={"sequence_name": "complete_trace"})
        self.assertEqual(r_seq.status_code, 200)
        seq_data = r_seq.get_json()
        self.assertTrue(seq_data["success"])
        self.assertEqual(seq_data["events_ingested"], 7)

        # 3. GET /materials
        r_mats = self.client.get('/api/vision/traceability/materials')
        self.assertEqual(r_mats.status_code, 200)
        mats_data = r_mats.get_json()
        self.assertGreater(mats_data["total"], 0)

        # 4. GET /materials/B104
        r_b104 = self.client.get('/api/vision/traceability/materials/B104')
        self.assertEqual(r_b104.status_code, 200)
        b104_data = r_b104.get_json()
        self.assertEqual(b104_data["material"]["material_id"], "B104")

        # 5. GET /materials/B104/timeline
        r_tl = self.client.get('/api/vision/traceability/materials/B104/timeline')
        self.assertEqual(r_tl.status_code, 200)
        tl_data = r_tl.get_json()
        self.assertEqual(tl_data["total_events"], 7)

        # 6. GET /cameras/CAM-001
        r_cam = self.client.get('/api/vision/traceability/cameras/CAM-001')
        self.assertEqual(r_cam.status_code, 200)
        cam_data = r_cam.get_json()
        self.assertEqual(cam_data["camera_id"], "CAM-001")

        # 7. GET /cameras/CAM-001/annotated.jpg
        r_jpg = self.client.get('/api/vision/traceability/cameras/CAM-001/annotated.jpg')
        self.assertEqual(r_jpg.status_code, 200)
        self.assertEqual(r_jpg.mimetype, 'image/jpeg')
        self.assertGreater(len(r_jpg.data), 1000)

        # 8. POST /test
        r_test = self.client.post('/api/vision/traceability/test', json={"scenario": "box_truck_association"})
        self.assertEqual(r_test.status_code, 200)
        self.assertTrue(r_test.get_json()["success"])

        # 9. POST /reset
        r_rst = self.client.post('/api/vision/traceability/reset')
        self.assertEqual(r_rst.status_code, 200)
        self.assertTrue(r_rst.get_json()["success"])

    # ------------------------------------------------------------------------
    # Test 22: Complete 7-Frame End-to-End Trace Sequence (Section 27)
    # ------------------------------------------------------------------------
    def test_22_complete_trace_sequence(self):
        res = self.service.run_synthetic_sequence("complete_trace")
        self.assertTrue(res["success"])
        self.assertEqual(res["total_frames_executed"], 7)
        self.assertEqual(res["events_ingested"], 7)

        dossier = self.service.get_material("B104")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["material_id"], "B104")
        self.assertEqual(dossier["source"]["identity_id"], "GP-1000")
        self.assertEqual(dossier["destination"]["identity_id"], "BIN-A101")
        self.assertEqual(dossier["associated_workers"][0]["identity_id"], "W07")
        self.assertEqual(dossier["traceability_status"], MaterialTraceStatus.DESTINATION_OBSERVED)
        self.assertEqual(dossier["traceability_level"], TraceabilityLevel.VALIDATED_REAL_WORLD)

        # Validate originating event_id preservation in every timeline entry
        timeline = dossier["timeline"]
        self.assertEqual(len(timeline), 7)
        for idx, entry in enumerate(timeline, start=1):
            expected_evt_id = f"EVT-00000{idx}"
            self.assertEqual(entry["event_id"], expected_evt_id)
            self.assertTrue(entry["trace_id"].startswith("TRACE-"))

    # ------------------------------------------------------------------------
    # Test 23: Bounded Memory Behavior (Sections 39)
    # ------------------------------------------------------------------------
    def test_23_bounded_memory_behavior(self):
        # Configure small test config
        small_cfg = TraceabilityConfig(max_materials=3, max_timeline_entries=4)
        bounded_service = MaterialTraceabilityService(small_cfg)

        # 1. Timeline bounding (max 4 entries)
        for i in range(10):
            bounded_service.ingest_movement_event({
                "event_id": f"EVT-BOUND-{i}",
                "event_type": "BOX_ENTERED_ZONE",
                "camera_id": "CAM-001",
                "timestamp": f"2026-10-02T10:00:{i:02d}Z",
                "primary_object": {"track_id": 1, "class_code": "BOX", "identity_id": "BOUND_BOX", "identity_status": "VALIDATED"},
                "status": "ACTIVE"
            })

        tl = bounded_service.get_timeline("BOUND_BOX")
        self.assertEqual(len(tl), 4)  # Bounded to max 4 entries
        # Oldest evicted, newest retained
        self.assertEqual(tl[-1]["event_id"], "EVT-BOUND-9")

        # 2. Material count bounding (max 3 materials)
        bounded_service.ingest_movement_event({
            "event_id": "EVT-M1", "event_type": "BOX_ENTERED_ZONE", "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:01:00Z", "primary_object": {"track_id": 10, "class_code": "BOX", "identity_id": "M1", "identity_status": "VALIDATED"}
        })
        bounded_service.ingest_movement_event({
            "event_id": "EVT-M2", "event_type": "BOX_ENTERED_ZONE", "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:00Z", "primary_object": {"track_id": 20, "class_code": "BOX", "identity_id": "M2", "identity_status": "VALIDATED"}
        })
        bounded_service.ingest_movement_event({
            "event_id": "EVT-M3", "event_type": "BOX_ENTERED_ZONE", "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:03:00Z", "primary_object": {"track_id": 30, "class_code": "BOX", "identity_id": "M3", "identity_status": "VALIDATED"}
        })

        # Materials count must not exceed max_materials (3)
        self.assertLessEqual(len(bounded_service.materials), 3)

    # ------------------------------------------------------------------------
    # Test 24: Zero Database Writes & Integrity
    # ------------------------------------------------------------------------
    def test_24_zero_database_writes(self):
        current_md5 = get_db_md5()
        self.assertEqual(self.db_md5_initial, current_md5, "Database MD5 changed during test run!")


if __name__ == '__main__':
    # Benchmark performance
    bench_service = get_material_traceability_service()
    bench_service.reset()

    times = []
    for _ in range(50):
        t_start = time.perf_counter()
        bench_service.run_synthetic_sequence()
        times.append((time.perf_counter() - t_start) * 1000.0)

    avg_time = sum(times) / len(times)
    max_time = max(times)
    print(f"\n[PERFORMANCE] Material Traceability Processing: Avg={avg_time:.3f}ms, Max={max_time:.3f}ms over 50 iterations.")

    unittest.main()
