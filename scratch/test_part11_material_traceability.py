"""
Part 11 — Material Traceability Enhancement Test Suite
Validates all 18 target requirements for automotive warehouse material traceability:
1. Identified automotive material traceability (GLASS, ROD, PART, FASTENER)
2. Unidentified material (camera-scoped track isolation)
3. Ambiguous identity (preserved & quarantined, never merged)
4. Conflicting identity (preserved & quarantined)
5. Barcode/QR physical identity across cameras
6. Same SKU but different physical materials (not merged)
7. Material vs container distinction
8. Material transfer between containers
9. Complete Truck -> Dock -> Sorting -> Staging -> Bin flow
10. Source / destination resolution
11. Repeated observations and event deduplication
12. Zone re-entry
13. Missing / temporary tracking
14. Quantity / UoM not falsely inferred from visual detection count
15. BOX backward compatibility
16. Zero visual Re-ID
17. Bounded memory
18. WMS inventory remains unchanged (17 tables, 0 inventory writes)
"""

import os
import sys
import unittest
import copy
import time
import sqlite3

# Ensure local webapp imports work
webapp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

from material_traceability_service import (
    MaterialTraceabilityService,
    TraceabilityConfig,
    TraceabilityLevel,
    MaterialTraceStatus,
    MaterialTraceEvent,
    get_material_traceability_service
)
from movement_event_service import EventType, EventState
from db import get_db


class TestPart11MaterialTraceability(unittest.TestCase):

    def setUp(self):
        self.service = MaterialTraceabilityService()
        self.service.reset()

    def tearDown(self):
        self.service.reset()

    # ------------------------------------------------------------------------
    # 1. Identified Automotive Material Traceability
    # ------------------------------------------------------------------------
    def test_01_identified_automotive_material_traceability(self):
        """Validates automotive material (GLASS) with validated physical identity."""
        evt = {
            "event_id": "EVT-M01-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 101,
                "class_code": "GLASS",
                "material_id": "MAT-GL-901",
                "sku": "AUTO-GLASS-01",
                "sku_name": "Windshield Glass Panel",
                "physical_identifier": "BC-GL-901",
                "identity_type": "BARCODE",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
            "confidence": 0.96,
            "status": "ACTIVE",
            "event_level": "VALIDATED_REAL_WORLD"
        }
        res = self.service.ingest_movement_event(evt)
        self.assertIsNotNone(res)

        dossier = self.service.get_material("MAT-GL-901")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["material_class"], "GLASS")
        self.assertEqual(dossier["sku_id"], "AUTO-GLASS-01")
        self.assertEqual(dossier["physical_identifier"], "BC-GL-901")
        self.assertEqual(dossier["physical_identity_type"], "BARCODE")
        self.assertEqual(dossier["identity_status"], "VALIDATED")
        self.assertEqual(dossier["traceability_level"], TraceabilityLevel.VALIDATED_REAL_WORLD)
        self.assertEqual(dossier["current_location"]["zone_code"], "DOCK-01")

        summary = dossier["dossier_summary"]
        self.assertEqual(summary["material_id"], "MAT-GL-901")
        self.assertEqual(summary["identification_method"], "BARCODE")

    # ------------------------------------------------------------------------
    # 2. Unidentified Material (Camera-Scoped Track Isolation)
    # ------------------------------------------------------------------------
    def test_02_unidentified_material_track_isolation(self):
        """Unidentified visual detections remain isolated per camera track."""
        evt1 = {
            "event_id": "EVT-U01-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 42, "class_code": "PART"},
            "zone": {"zone_id": 1, "zone_code": "YARD-01"},
            "confidence": 0.85,
            "status": "ACTIVE"
        }
        evt2 = {
            "event_id": "EVT-U02-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-002",
            "timestamp": "2026-10-02T10:00:05Z",
            "primary_object": {"track_id": 42, "class_code": "PART"},
            "zone": {"zone_id": 2, "zone_code": "YARD-02"},
            "confidence": 0.85,
            "status": "ACTIVE"
        }
        self.service.ingest_movement_event(evt1)
        self.service.ingest_movement_event(evt2)

        # Both cameras had track_id 42, but since unidentified, MUST remain separate records
        self.assertIn("TRACK_CAM-001_42", self.service.materials)
        self.assertIn("TRACK_CAM-002_42", self.service.materials)
        self.assertEqual(len(self.service.materials), 2)
        rec1 = self.service.get_material("TRACK_CAM-001_42")
        self.assertEqual(rec1["traceability_level"], TraceabilityLevel.TRACK_LEVEL)

    # ------------------------------------------------------------------------
    # 3. Ambiguous Identity (Preserved & Quarantined, Never Merged)
    # ------------------------------------------------------------------------
    def test_03_ambiguous_identity_preserved(self):
        """Ambiguous identity candidate does not merge and is flagged in conflicts."""
        evt = {
            "event_id": "EVT-AMB-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 77,
                "class_code": "ROD",
                "identity_id": "ROD-AMB-01",
                "identity_status": "AMBIGUOUS"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.50,
            "status": "ACTIVE"
        }
        self.service.ingest_movement_event(evt)

        mat_key = "AMBIGUOUS_CAM-001_77"
        dossier = self.service.get_material(mat_key)
        self.assertIsNotNone(dossier)
        self.assertTrue(dossier["is_ambiguous"])
        self.assertEqual(dossier["identity_status"], "AMBIGUOUS")
        self.assertTrue(len(dossier["conflicts"]) > 0)
        self.assertEqual(dossier["conflicts"][0]["type"], "IDENTITY_AMBIGUOUS")

    # ------------------------------------------------------------------------
    # 4. Conflicting Identity (Preserved & Quarantined)
    # ------------------------------------------------------------------------
    def test_04_conflicting_identity_quarantined(self):
        """Conflicting identity observations are quarantined and preserved."""
        evt = {
            "event_id": "EVT-CONF-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 88,
                "class_code": "FASTENER",
                "identity_id": "FST-CONF",
                "identity_status": "CONFLICT"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.45,
            "status": "ACTIVE"
        }
        self.service.ingest_movement_event(evt)

        mat_key = "CONFLICT_CAM-001_88"
        dossier = self.service.get_material(mat_key)
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["identity_status"], "CONFLICT")
        self.assertTrue(dossier["dossier_summary"]["has_conflicts"])

    # ------------------------------------------------------------------------
    # 5. Barcode/QR Physical Identity Across Cameras
    # ------------------------------------------------------------------------
    def test_05_barcode_physical_identity_across_cameras(self):
        """Explicit barcode token unifies observation history across CAM-001 and CAM-002."""
        evt_cam1 = {
            "event_id": "EVT-BC-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 11,
                "class_code": "COMPONENT",
                "identity_id": "BC-ENG-5500",
                "physical_identifier": "BC-ENG-5500",
                "identity_type": "BARCODE",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.96,
            "status": "ACTIVE"
        }
        evt_cam2 = {
            "event_id": "EVT-BC-02",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-002",
            "timestamp": "2026-10-02T10:04:00Z",
            "primary_object": {
                "track_id": 22,
                "class_code": "COMPONENT",
                "identity_id": "BC-ENG-5500",
                "physical_identifier": "BC-ENG-5500",
                "identity_type": "BARCODE",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 5, "zone_code": "SORT-01"},
            "confidence": 0.95,
            "status": "ACTIVE"
        }

        self.service.ingest_movement_event(evt_cam1)
        self.service.ingest_movement_event(evt_cam2)

        # Single unified material record indexed by physical barcode
        self.assertEqual(len(self.service.materials), 1)
        dossier = self.service.get_material("BC-ENG-5500")
        self.assertIsNotNone(dossier)
        self.assertEqual(len(dossier["timeline"]), 2)
        # Both camera tracks recorded
        self.assertIn("CAM-001", dossier["camera_tracks"])
        self.assertIn("CAM-002", dossier["camera_tracks"])
        self.assertEqual(dossier["current_location"]["zone_code"], "SORT-01")

    # ------------------------------------------------------------------------
    # 6. Same SKU But Different Physical Materials (Not Merged)
    # ------------------------------------------------------------------------
    def test_06_same_sku_different_physical_materials_not_merged(self):
        """Two separate physical components with identical SKU master code are NOT merged."""
        evt_unit1 = {
            "event_id": "EVT-SKU-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 10,
                "material_id": "UNIT-ROD-001",
                "sku": "SKU-STEEL-ROD",
                "class_code": "ROD",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.95,
            "status": "ACTIVE"
        }
        evt_unit2 = {
            "event_id": "EVT-SKU-02",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:10Z",
            "primary_object": {
                "track_id": 20,
                "material_id": "UNIT-ROD-002",
                "sku": "SKU-STEEL-ROD",
                "class_code": "ROD",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.95,
            "status": "ACTIVE"
        }

        self.service.ingest_movement_event(evt_unit1)
        self.service.ingest_movement_event(evt_unit2)

        # Must produce TWO distinct material records
        self.assertIn("UNIT-ROD-001", self.service.materials)
        self.assertIn("UNIT-ROD-002", self.service.materials)
        self.assertEqual(len(self.service.materials), 2)
        self.assertEqual(self.service.materials["UNIT-ROD-001"].sku_id, "SKU-STEEL-ROD")
        self.assertEqual(self.service.materials["UNIT-ROD-002"].sku_id, "SKU-STEEL-ROD")

    # ------------------------------------------------------------------------
    # 7. Material vs Container Distinction
    # ------------------------------------------------------------------------
    def test_07_material_vs_container_distinction(self):
        """Material inside a container maintains clear distinction from container entity."""
        # 1. Register container PALLET-01
        self.service.ingest_movement_event({
            "event_id": "EVT-CONT-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 5, "material_id": "PALLET-01", "class_code": "PALLET"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.92,
            "status": "ACTIVE"
        })

        # 2. Material associated with that container
        self.service.ingest_movement_event({
            "event_id": "EVT-MAT-01",
            "event_type": "MATERIAL_ASSOCIATED_WITH_CONTAINER",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:01:00Z",
            "primary_object": {"track_id": 12, "material_id": "MAT-FASTENER-99", "class_code": "FASTENER"},
            "secondary_object": {"track_id": 5, "class_code": "PALLET", "identity_id": "PALLET-01"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.94,
            "status": "ACTIVE"
        })

        mat = self.service.get_material("MAT-FASTENER-99")
        cont = self.service.get_material("PALLET-01")

        self.assertFalse(mat["is_container"])
        self.assertEqual(mat["container_id"], "PALLET-01")
        self.assertTrue(cont["is_container"])
        self.assertIn("MAT-FASTENER-99", cont["contained_materials"])

    # ------------------------------------------------------------------------
    # 8. Material Transfer Between Containers
    # ------------------------------------------------------------------------
    def test_08_material_transfer_between_containers(self):
        """Transfer from box BOX-10 to pallet PALLET-90 logs transfer history."""
        # Create container 1
        self.service.ingest_movement_event({
            "event_id": "EVT-C1",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 1, "material_id": "BOX-10", "class_code": "BOX"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        # Create container 2
        self.service.ingest_movement_event({
            "event_id": "EVT-C2",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 2, "material_id": "PALLET-90", "class_code": "PALLET"},
            "zone": {"zone_id": 5, "zone_code": "SORT-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })

        # Material in BOX-10
        self.service.ingest_movement_event({
            "event_id": "EVT-TR-01",
            "event_type": "MATERIAL_ASSOCIATED_WITH_CONTAINER",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:01:00Z",
            "primary_object": {"track_id": 7, "material_id": "MAT-SENSOR-01", "class_code": "COMPONENT"},
            "secondary_object": {"identity_id": "BOX-10", "class_code": "BOX"},
            "confidence": 0.91,
            "status": "ACTIVE"
        })
        mat = self.service.get_material("MAT-SENSOR-01")
        self.assertEqual(mat["container_id"], "BOX-10")
        self.assertEqual(len(mat["container_history"]), 1)
        self.assertEqual(mat["container_history"][0]["transition"], "ASSIGN")

        # Transfer to PALLET-90
        self.service.ingest_movement_event({
            "event_id": "EVT-TR-02",
            "event_type": "MATERIAL_ASSOCIATED_WITH_CONTAINER",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:03:00Z",
            "primary_object": {"track_id": 7, "material_id": "MAT-SENSOR-01", "class_code": "COMPONENT"},
            "secondary_object": {"identity_id": "PALLET-90", "class_code": "PALLET"},
            "confidence": 0.95,
            "status": "ACTIVE"
        })
        mat_after = self.service.get_material("MAT-SENSOR-01")
        self.assertEqual(mat_after["container_id"], "PALLET-90")
        self.assertEqual(len(mat_after["container_history"]), 2)
        transfer_entry = mat_after["container_history"][1]
        self.assertEqual(transfer_entry["transition"], "TRANSFER")
        self.assertEqual(transfer_entry["from_container"], "BOX-10")
        self.assertEqual(transfer_entry["to_container"], "PALLET-90")

        # Container lists updated
        self.assertNotIn("MAT-SENSOR-01", self.service.materials["BOX-10"].contained_materials)
        self.assertIn("MAT-SENSOR-01", self.service.materials["PALLET-90"].contained_materials)

    # ------------------------------------------------------------------------
    # 9. Full Truck -> Dock -> Sorting -> Staging -> Bin Flow
    # ------------------------------------------------------------------------
    def test_09_full_lifecycle_flow(self):
        """Executes full 8-frame automotive lifecycle flow."""
        res = self.service.run_synthetic_sequence("automotive_traceability_flow")
        self.assertTrue(res["success"])
        self.assertEqual(res["total_frames_executed"], 8)
        self.assertEqual(res["events_ingested"], 8)

        dossier = res["material_dossier"]
        self.assertEqual(dossier["material_id"], "MAT-AUTO-GL-01")
        self.assertEqual(dossier["material_class"], "GLASS")
        self.assertEqual(dossier["sku_id"], "AUTO-GLASS-01")
        self.assertEqual(dossier["source"]["identity_id"], "GP-1000")
        self.assertEqual(dossier["destination"]["identity_id"], "BIN-A101")
        self.assertEqual(dossier["container_id"], "PALLET-05")
        self.assertEqual(len(dossier["timeline"]), 8)

    # ------------------------------------------------------------------------
    # 10. Source / Destination Resolution
    # ------------------------------------------------------------------------
    def test_10_source_destination_resolution(self):
        """Unresolved destination is clearly marked until confirmed bin association."""
        self.service.ingest_movement_event({
            "event_id": "EVT-SD-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-UNRESOLVED", "class_code": "PART"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        mat = self.service.get_material("MAT-UNRESOLVED")
        self.assertIsNone(mat["destination"])
        self.assertTrue(mat["unresolved_destination"])

        # Associate bin
        self.service.ingest_movement_event({
            "event_id": "EVT-SD-02",
            "event_type": "MATERIAL_ASSOCIATED_WITH_BIN",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:05:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-UNRESOLVED", "class_code": "PART"},
            "secondary_object": {"identity_id": "BIN-C303", "class_code": "BIN"},
            "confidence": 0.93,
            "status": "ACTIVE"
        })
        mat_resolved = self.service.get_material("MAT-UNRESOLVED")
        self.assertIsNotNone(mat_resolved["destination"])
        self.assertEqual(mat_resolved["destination"]["identity_id"], "BIN-C303")
        self.assertFalse(mat_resolved["unresolved_destination"])

    # ------------------------------------------------------------------------
    # 11. Repeated Observations and Event Deduplication
    # ------------------------------------------------------------------------
    def test_11_event_deduplication(self):
        """Ingesting the same event ID repeatedly does not duplicate timeline history."""
        evt = {
            "event_id": "EVT-DUP-TEST",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-DEDUP", "class_code": "PART"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        }
        res1 = self.service.ingest_movement_event(evt)
        self.assertIsNotNone(res1)
        res2 = self.service.ingest_movement_event(evt)
        self.assertIsNone(res2)

        mat = self.service.get_material("MAT-DEDUP")
        self.assertEqual(len(mat["timeline"]), 1)

    # ------------------------------------------------------------------------
    # 12. Zone Re-Entry
    # ------------------------------------------------------------------------
    def test_12_zone_re_entry(self):
        """Material leaving and re-entering DOCK-01 creates RE_ENTER milestone without losing prior entry."""
        # Enter DOCK-01
        self.service.ingest_movement_event({
            "event_id": "EVT-ZR-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-REENTER", "class_code": "PART"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        # Exit DOCK-01
        self.service.ingest_movement_event({
            "event_id": "EVT-ZR-02",
            "event_type": "MATERIAL_EXITED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:02:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-REENTER", "class_code": "PART"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "COMPLETED"
        })
        # Enter STAGING
        self.service.ingest_movement_event({
            "event_id": "EVT-ZR-03",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:03:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-REENTER", "class_code": "PART"},
            "zone": {"zone_id": 6, "zone_code": "STG-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        # Re-enter DOCK-01
        self.service.ingest_movement_event({
            "event_id": "EVT-ZR-04",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:06:00Z",
            "primary_object": {"track_id": 1, "material_id": "MAT-REENTER", "class_code": "PART"},
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })

        mat = self.service.get_material("MAT-REENTER")
        zh = mat["zone_history"]
        self.assertEqual(len(zh), 4)
        self.assertEqual(zh[0]["transition"], "ENTER")
        self.assertEqual(zh[0]["zone_code"], "DOCK-01")
        self.assertEqual(zh[1]["transition"], "EXIT")
        self.assertEqual(zh[2]["transition"], "ENTER")
        self.assertEqual(zh[2]["zone_code"], "STG-01")
        self.assertEqual(zh[3]["transition"], "RE_ENTER")
        self.assertEqual(zh[3]["zone_code"], "DOCK-01")
        self.assertTrue(len(mat["previous_locations"]) >= 1)

    # ------------------------------------------------------------------------
    # 13. Missing / Temporary Tracking (Re-Acquisition)
    # ------------------------------------------------------------------------
    def test_13_missing_temporary_tracking(self):
        """Re-acquiring a material with new track ID via physical ID preserves continuity."""
        # Initial track 15
        self.service.ingest_movement_event({
            "event_id": "EVT-MISS-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {
                "track_id": 15,
                "material_id": "MAT-REACQ",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        # Later re-acquired as track 99 on same camera
        self.service.ingest_movement_event({
            "event_id": "EVT-MISS-02",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:08:00Z",
            "primary_object": {
                "track_id": 99,
                "material_id": "MAT-REACQ",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 5, "zone_code": "SORT-01"},
            "confidence": 0.92,
            "status": "ACTIVE"
        })

        mat = self.service.get_material("MAT-REACQ")
        self.assertIsNotNone(mat)
        self.assertEqual(mat["camera_tracks"]["CAM-001"], 99)
        self.assertEqual(len(mat["timeline"]), 2)

    # ------------------------------------------------------------------------
    # 14. Quantity / UoM Not Falsely Inferred From Detection Counts
    # ------------------------------------------------------------------------
    def test_14_quantity_not_inferred_from_detection_counts(self):
        """Visual detection counts do not fabricate or alter explicit inventory quantity."""
        # Multiple frames / events for the same material
        for i in range(5):
            self.service.ingest_movement_event({
                "event_id": f"EVT-QTY-{i}",
                "event_type": "MATERIAL_ENTERED_ZONE",
                "camera_id": "CAM-001",
                "timestamp": f"2026-10-02T10:0{i}:00Z",
                "primary_object": {
                    "track_id": 1,
                    "material_id": "MAT-NOQTY",
                    "class_code": "ROD"
                    # No explicit quantity provided
                },
                "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
                "confidence": 0.9,
                "status": "ACTIVE"
            })
        mat = self.service.get_material("MAT-NOQTY")
        # Must NOT be 5! Must be None because no explicit quantity was specified.
        self.assertIsNone(mat["quantity"])

        # When explicit manifest quantity is given, it is preserved
        self.service.ingest_movement_event({
            "event_id": "EVT-QTY-EXPL",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:10:00Z",
            "primary_object": {
                "track_id": 2,
                "material_id": "MAT-WITHQTY",
                "class_code": "FASTENER",
                "quantity": 100.0,
                "uom": "PCS"
            },
            "zone": {"zone_id": 3, "zone_code": "DOCK-01"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        mat_expl = self.service.get_material("MAT-WITHQTY")
        self.assertEqual(mat_expl["quantity"], 100.0)
        self.assertEqual(mat_expl["uom"], "PCS")

    # ------------------------------------------------------------------------
    # 15. BOX Backward Compatibility
    # ------------------------------------------------------------------------
    def test_15_box_backward_compatibility(self):
        """Legacy BOX events and complete_trace sequence function with 100% compatibility."""
        res = self.service.run_synthetic_sequence("complete_trace")
        self.assertTrue(res["success"])
        self.assertEqual(res["total_frames_executed"], 7)

        dossier = res["material_dossier"]
        self.assertEqual(dossier["material_id"], "B104")
        self.assertEqual(dossier["material_class"], "BOX")
        self.assertEqual(dossier["source"]["identity_id"], "GP-1000")
        self.assertEqual(dossier["destination"]["identity_id"], "BIN-A101")
        self.assertEqual(len(dossier["associated_workers"]), 1)
        self.assertEqual(dossier["associated_workers"][0]["identity_id"], "W07")

    # ------------------------------------------------------------------------
    # 16. No Visual Re-ID
    # ------------------------------------------------------------------------
    def test_16_no_visual_reid(self):
        """Two camera tracks with similar appearance are NEVER merged without physical barcode."""
        evt1 = {
            "event_id": "EVT-REID-01",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:00:00Z",
            "primary_object": {"track_id": 50, "class_code": "GLASS"},
            "zone": {"zone_id": 1, "zone_code": "YARD-01"},
            "confidence": 0.88,
            "status": "ACTIVE"
        }
        evt2 = {
            "event_id": "EVT-REID-02",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-002",
            "timestamp": "2026-10-02T10:00:05Z",
            "primary_object": {"track_id": 51, "class_code": "GLASS"},
            "zone": {"zone_id": 2, "zone_code": "DOCK-01"},
            "confidence": 0.89,
            "status": "ACTIVE"
        }
        self.service.ingest_movement_event(evt1)
        self.service.ingest_movement_event(evt2)

        # Strictly 2 distinct track records
        self.assertEqual(len(self.service.materials), 2)
        self.assertIn("TRACK_CAM-001_50", self.service.materials)
        self.assertIn("TRACK_CAM-002_51", self.service.materials)

    # ------------------------------------------------------------------------
    # 17. Bounded Memory
    # ------------------------------------------------------------------------
    def test_17_bounded_memory(self):
        """Bounded memory clamps timeline, zone history, and evicts oldest records."""
        cfg = TraceabilityConfig(max_materials=3, max_timeline_entries=4, max_zone_history=3)
        svc = MaterialTraceabilityService(config=cfg)

        # Fill max_materials
        for m in ("M1", "M2", "M3"):
            svc.ingest_movement_event({
                "event_id": f"EVT-INIT-{m}",
                "event_type": "MATERIAL_ENTERED_ZONE",
                "camera_id": "CAM-001",
                "timestamp": "2026-10-02T10:00:00Z",
                "primary_object": {"material_id": m, "track_id": 1},
                "zone": {"zone_id": 1, "zone_code": "Z1"},
                "confidence": 0.9,
                "status": "ACTIVE"
            })
        self.assertEqual(len(svc.materials), 3)

        # Ingest 4th material -> oldest evicted
        svc.ingest_movement_event({
            "event_id": "EVT-INIT-M4",
            "event_type": "MATERIAL_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-02T10:05:00Z",
            "primary_object": {"material_id": "M4", "track_id": 1},
            "zone": {"zone_id": 1, "zone_code": "Z1"},
            "confidence": 0.9,
            "status": "ACTIVE"
        })
        self.assertEqual(len(svc.materials), 3)
        self.assertIn("M4", svc.materials)

        # Timeline clamping
        for i in range(10):
            svc.ingest_movement_event({
                "event_id": f"EVT-CLAMP-{i}",
                "event_type": "MATERIAL_ENTERED_ZONE",
                "camera_id": "CAM-001",
                "timestamp": f"2026-10-02T10:{10+i:02d}:00Z",
                "primary_object": {"material_id": "M4", "track_id": 1},
                "zone": {"zone_id": 1, "zone_code": f"Z{i}"},
                "confidence": 0.9,
                "status": "ACTIVE"
            })
        self.assertLessEqual(len(svc.materials["M4"].timeline), cfg.max_timeline_entries)
        self.assertLessEqual(len(svc.materials["M4"].zone_history), cfg.max_zone_history)

    # ------------------------------------------------------------------------
    # 18. WMS Inventory Remains Unchanged
    # ------------------------------------------------------------------------
    def test_18_wms_inventory_unchanged(self):
        """Verifies that traceability operations perform zero database writes or inventory mutations."""
        conn = get_db()
        try:
            cur = conn.cursor()
            inv_count_before = cur.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            tables_before = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]

            # Execute full synthetic sequence
            self.service.run_synthetic_sequence("automotive_traceability_flow")

            inv_count_after = cur.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            tables_after = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]

            self.assertEqual(inv_count_before, 0)
            self.assertEqual(inv_count_after, 0)
            self.assertEqual(len(tables_before), 17)
            self.assertEqual(len(tables_after), 17)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
