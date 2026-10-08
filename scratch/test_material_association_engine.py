"""
Comprehensive Verification Suite for Part 9: Material Association Engine.
Tests all 15 required core behaviors, boundary conditions, automotive materials,
cross-camera physical continuity, and zero-inventory-mutation guarantees.
"""

import os
import sys
import unittest
import copy
import hashlib

# Add webapp directory to path
webapp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webapp")
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

from material_association_service import (
    AssociationType,
    AssociationState,
    MaterialAssociationConfig,
    MaterialAssociationEvidence,
    MaterialAssociation,
    CameraMaterialAssociationSession,
    MultiObjectMaterialAssociationService,
    get_material_association_service
)
from association_service import get_association_service
from worker_box_association_service import get_worker_box_association_service
from box_bin_association_service import get_box_bin_association_service
from db import get_db


class TestMaterialAssociationEngine(unittest.TestCase):

    def setUp(self):
        self.service = MultiObjectMaterialAssociationService()
        self.service.reset_all()

    def _create_track(
        self,
        track_id: int,
        class_code: str,
        cx: float,
        cy: float,
        zone: str = "DOCK-01",
        ident_val: Optional[str] = None,
        ident_status: str = "IDENTIFIED",
        val_status: str = "VALIDATED",
        master_type: str = "MATERIAL"
    ):
        return {
            "track_id": track_id,
            "class_code": class_code,
            "confidence": 0.95,
            "bbox": {
                "x1": int((cx - 0.05) * 1280),
                "y1": int((cy - 0.05) * 720),
                "x2": int((cx + 0.05) * 1280),
                "y2": int((cy + 0.05) * 720)
            },
            "bbox_normalized": {
                "x1": cx - 0.05,
                "y1": cy - 0.05,
                "x2": cx + 0.05,
                "y2": cy + 0.05
            },
            "center_normalized": [cx, cy],
            "roi": {"inside": True, "zone_code": zone},
            "roi_zone_code": zone,
            "identity": {
                "status": ident_status,
                "value": ident_val,
                "source": "BARCODE" if class_code != "TRUCK" else "QR"
            },
            "validation": {
                "status": val_status,
                "master_type": master_type,
                "master_id": ident_val,
                "display_name": f"{class_code} {ident_val}" if ident_val else None
            }
        }

    # -------------------------------------------------------------------------
    # TEST 1: Material ↔ Truck Confirmed
    # -------------------------------------------------------------------------
    def test_01_material_truck_confirmed(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass = self._create_track(20, "GLASS", 0.35, 0.45, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        # Frame 1: Candidate
        assocs = session.update([truck, glass])
        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL]
        self.assertEqual(len(t_mat), 1)
        self.assertEqual(t_mat[0].status, AssociationState.CANDIDATE)

        # Frame 2: Candidate
        session.update([truck, glass])

        # Frame 3: Confirmed
        assocs = session.update([truck, glass])
        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL]
        self.assertEqual(t_mat[0].status, AssociationState.CONFIRMED)
        self.assertIsNotNone(t_mat[0].real_world_association)
        self.assertEqual(t_mat[0].real_world_association["truck_id"], "GP-1000")
        self.assertEqual(t_mat[0].real_world_association["material_sku"], "AUTO-GLASS-01")

    # -------------------------------------------------------------------------
    # TEST 2: Material ↔ Worker Confirmed
    # -------------------------------------------------------------------------
    def test_02_material_worker_confirmed(self):
        session = CameraMaterialAssociationSession("CAM-001")
        worker = self._create_track(5, "WORKER", 0.25, 0.35, zone="AISLE-01", ident_val="admin", master_type="WORKER")
        rod = self._create_track(21, "ROD", 0.30, 0.40, zone="AISLE-01", ident_val="AUTO-ROD-01", master_type="MATERIAL")

        # 3 consecutive frames
        session.update([worker, rod])
        session.update([worker, rod])
        assocs = session.update([worker, rod])

        w_mat = [a for a in assocs if a.association_type == AssociationType.WORKER_MATERIAL]
        self.assertEqual(len(w_mat), 1)
        self.assertEqual(w_mat[0].status, AssociationState.CONFIRMED)
        self.assertEqual(w_mat[0].real_world_association["worker_id"], "admin")
        self.assertEqual(w_mat[0].real_world_association["material_sku"], "AUTO-ROD-01")

    # -------------------------------------------------------------------------
    # TEST 3: Material ↔ Bin Confirmed
    # -------------------------------------------------------------------------
    def test_03_material_bin_confirmed(self):
        session = CameraMaterialAssociationSession("CAM-001")
        fastener = self._create_track(22, "FASTENER", 0.40, 0.50, zone="STORAGE-01", ident_val="AUTO-BOLT-01", master_type="MATERIAL")
        bin_slot = self._create_track(40, "BIN", 0.42, 0.52, zone="STORAGE-01", ident_val="BIN-01", master_type="BIN")

        for _ in range(3):
            assocs = session.update([fastener, bin_slot])

        m_bin = [a for a in assocs if a.association_type == AssociationType.MATERIAL_BIN]
        self.assertEqual(len(m_bin), 1)
        self.assertEqual(m_bin[0].status, AssociationState.CONFIRMED)
        self.assertEqual(m_bin[0].real_world_association["material_sku"], "AUTO-BOLT-01")
        self.assertEqual(m_bin[0].real_world_association["bin_id"], "BIN-01")

    # -------------------------------------------------------------------------
    # TEST 4: Container ↔ Material Distinction
    # -------------------------------------------------------------------------
    def test_04_container_material_distinction(self):
        session = CameraMaterialAssociationSession("CAM-001")
        container = self._create_track(15, "CONTAINER", 0.40, 0.40, zone="DOCK-01", ident_val="BOX-101", master_type="CONTAINER")
        part = self._create_track(23, "PART", 0.41, 0.41, zone="DOCK-01", ident_val="SKU-001", master_type="MATERIAL")

        for _ in range(3):
            assocs = session.update([container, part])

        c_mat = [a for a in assocs if a.association_type == AssociationType.MATERIAL_CONTAINER]
        self.assertEqual(len(c_mat), 1)
        self.assertEqual(c_mat[0].status, AssociationState.CONFIRMED)
        rwa = c_mat[0].real_world_association
        self.assertIsNotNone(rwa)

        # CRITICAL: Container identity is NOT equated to SKU, and SKU is NOT equated to container ID
        self.assertEqual(rwa["container_id"], "BOX-101")
        self.assertEqual(rwa["material_sku"], "SKU-001")
        self.assertNotEqual(rwa["container_id"], rwa["material_sku"])
        self.assertEqual(c_mat[0].primary_identity["value"], "BOX-101")
        self.assertEqual(c_mat[0].secondary_identity["value"], "SKU-001")

    # -------------------------------------------------------------------------
    # TEST 5: Sustained Proximity vs Single-Frame Proximity
    # -------------------------------------------------------------------------
    def test_05_sustained_proximity_vs_single_frame(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass = self._create_track(20, "GLASS", 0.30, 0.40, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        # Frame 1: Perfect spatial distance = 0.0, but consecutive_frames = 1 < 3
        assocs_f1 = session.update([truck, glass])
        t_mat_f1 = [a for a in assocs_f1 if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        self.assertEqual(t_mat_f1.status, AssociationState.CANDIDATE, "Single frame MUST remain CANDIDATE even with 0 distance")
        self.assertIn("below confirmation threshold", t_mat_f1.evidence.explanation)

        # Frame 2: consecutive_frames = 2 < 3
        assocs_f2 = session.update([truck, glass])
        t_mat_f2 = [a for a in assocs_f2 if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        self.assertEqual(t_mat_f2.status, AssociationState.CANDIDATE)

        # Frame 3: consecutive_frames = 3 >= 3 -> CONFIRMED
        assocs_f3 = session.update([truck, glass])
        t_mat_f3 = [a for a in assocs_f3 if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        self.assertEqual(t_mat_f3.status, AssociationState.CONFIRMED)

    # -------------------------------------------------------------------------
    # TEST 6: Temporal Overlap Requirement
    # -------------------------------------------------------------------------
    def test_06_temporal_overlap_requirement(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass = self._create_track(20, "GLASS", 0.35, 0.45, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        # Frame 1: Only truck present
        assocs = session.update([truck])
        self.assertEqual(len(assocs), 0, "No candidate pair when only truck is visible")

        # Frame 2: Both present
        assocs = session.update([truck, glass])
        self.assertEqual(len(assocs), 1)
        self.assertTrue(assocs[0].evidence.temporal_overlap)

    # -------------------------------------------------------------------------
    # TEST 7: Zone Mismatch Rejection
    # -------------------------------------------------------------------------
    def test_07_zone_mismatch_rejected(self):
        session = CameraMaterialAssociationSession("CAM-001")
        # Truck in DOCK-01, Material in STORAGE-01
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass = self._create_track(20, "GLASS", 0.35, 0.45, zone="STORAGE-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        assocs = session.update([truck, glass])
        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        self.assertEqual(t_mat.status, AssociationState.REJECTED)
        self.assertFalse(t_mat.evidence.same_zone)
        self.assertIn("Zone mismatch", t_mat.evidence.explanation)

    # -------------------------------------------------------------------------
    # TEST 8: Ambiguous Competing Association
    # -------------------------------------------------------------------------
    def test_08_ambiguous_competing_association(self):
        session = CameraMaterialAssociationSession("CAM-001")
        # Two trucks equidistant from one component
        truck1 = self._create_track(11, "TRUCK", 0.25, 0.50, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        truck2 = self._create_track(12, "TRUCK", 0.35, 0.50, zone="DOCK-01", ident_val="GP-2000", master_type="TRUCK")
        component = self._create_track(30, "COMPONENT", 0.30, 0.50, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        # Run 3 frames
        for _ in range(3):
            assocs = session.update([truck1, truck2, component])

        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL]
        self.assertEqual(len(t_mat), 2)
        # Both must be flagged as ambiguous and held in CANDIDATE
        for a in t_mat:
            self.assertTrue(a.evidence.is_ambiguous)
            self.assertEqual(a.status, AssociationState.CANDIDATE)
            self.assertIn("competing candidates", a.evidence.ambiguity_reason.lower() if a.evidence.ambiguity_reason else "")

    # -------------------------------------------------------------------------
    # TEST 9: Association Expiry
    # -------------------------------------------------------------------------
    def test_09_association_expiry(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass = self._create_track(20, "GLASS", 0.35, 0.45, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")

        # Create active association
        session.update([truck, glass])
        pair_key = (AssociationType.TRUCK_MATERIAL, 10, 20)
        self.assertIn(pair_key, session.associations)

        # Track departs frame: missed frames 1, 2, 3
        for _ in range(3):
            session.update([])
            self.assertNotEqual(session.associations[pair_key].status, AssociationState.EXPIRED)

        # Missed frame 4 (timeout=4) -> EXPIRED
        session.update([])
        self.assertEqual(session.associations[pair_key].status, AssociationState.EXPIRED)
        self.assertFalse(session.associations[pair_key].evidence.temporal_overlap)

    # -------------------------------------------------------------------------
    # TEST 10: Unidentified Material
    # -------------------------------------------------------------------------
    def test_10_unidentified_material_candidate_only(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        # Material is UNIDENTIFIED
        mat = self._create_track(25, "MATERIAL", 0.35, 0.45, zone="DOCK-01", ident_val=None, ident_status="UNIDENTIFIED", val_status="NOT_APPLICABLE")

        for _ in range(3):
            assocs = session.update([truck, mat])

        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        # Track-level perception may be confirmed, BUT real_world_association MUST be None
        self.assertIsNone(t_mat.real_world_association, "Unidentified material MUST NEVER be promoted to real-world association")

    # -------------------------------------------------------------------------
    # TEST 11: Conflicting Identity
    # -------------------------------------------------------------------------
    def test_11_conflicting_identity_no_real_world_association(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        # Material has CONFLICT identity
        mat = self._create_track(26, "MATERIAL", 0.35, 0.45, zone="DOCK-01", ident_val="AUTO-GLASS-01", ident_status="CONFLICT", val_status="NOT_APPLICABLE")

        for _ in range(3):
            assocs = session.update([truck, mat])

        t_mat = [a for a in assocs if a.association_type == AssociationType.TRUCK_MATERIAL][0]
        self.assertIsNone(t_mat.real_world_association, "Conflicted identity MUST NEVER be promoted to real-world association")

    # -------------------------------------------------------------------------
    # TEST 12: Cross-Camera Identity Using Physical Barcode/QR/OCR Only
    # -------------------------------------------------------------------------
    def test_12_cross_camera_identity_physical_only(self):
        # CAM-001: Observes Truck GP-1000 ↔ Material AUTO-GLASS-01 at Dock
        session1 = self.service.get_session("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        glass1 = self._create_track(20, "GLASS", 0.35, 0.45, zone="DOCK-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")
        for _ in range(3):
            session1.update([truck, glass1])

        # CAM-002: Observes Material AUTO-GLASS-01 ↔ Bin BIN-01 in Storage
        session2 = self.service.get_session("CAM-002")
        glass2 = self._create_track(99, "GLASS", 0.50, 0.50, zone="STORAGE-01", ident_val="AUTO-GLASS-01", master_type="MATERIAL")
        bin_box = self._create_track(88, "BIN", 0.52, 0.52, zone="STORAGE-01", ident_val="BIN-01", master_type="BIN")
        for _ in range(3):
            session2.update([glass2, bin_box])

        # Query associations across cameras by validated physical SKU
        cross_res = self.service.get_associations_for_material("AUTO-GLASS-01")
        self.assertEqual(cross_res["total_associations_found"], 2)
        cams_found = {a["camera_id"] for a in cross_res["associations"]}
        self.assertIn("CAM-001", cams_found)
        self.assertIn("CAM-002", cams_found)
        self.assertEqual(cross_res["cross_camera_continuity_method"], "PHYSICAL_IDENTITY_ONLY (No visual Re-ID)")

    # -------------------------------------------------------------------------
    # TEST 13: Existing BOX Association Regression
    # -------------------------------------------------------------------------
    def test_13_existing_box_association_regression(self):
        # Verify existing association services still function with BOX tracks
        truck_box_svc = get_association_service()
        truck_box_svc.reset_all()
        worker_box_svc = get_worker_box_association_service()
        worker_box_svc.reset_all()
        box_bin_svc = get_box_bin_association_service()
        box_bin_svc.reset_all()

        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")
        box = self._create_track(20, "BOX", 0.35, 0.45, zone="DOCK-01", ident_val="VLV-900", master_type="BOX")

        # Truck-Box service
        tb_assocs, _ = truck_box_svc.process_tracks([truck, box], camera_id="TEST-TB", frame_index=1)
        self.assertGreaterEqual(len(tb_assocs), 1)

        # Worker-Box service
        worker = self._create_track(5, "WORKER", 0.30, 0.40, zone="DOCK-01", ident_val="admin", master_type="WORKER")
        wb_assocs, _ = worker_box_svc.process_tracks([worker, box], camera_id="TEST-WB", frame_index=1)
        self.assertGreaterEqual(len(wb_assocs), 1)

        # Box-Bin service
        bin_slot = self._create_track(40, "BIN", 0.35, 0.45, zone="DOCK-01", ident_val="BIN-01", master_type="BIN")
        bb_assocs, _ = box_bin_svc.process_tracks([box, bin_slot], camera_id="TEST-BB", frame_index=1)
        self.assertGreaterEqual(len(bb_assocs), 1)

    # -------------------------------------------------------------------------
    # TEST 14: Automotive GLASS, ROD, FASTENER, PART, COMPONENT Cases
    # -------------------------------------------------------------------------
    def test_14_automotive_material_classes_handled(self):
        session = CameraMaterialAssociationSession("CAM-001")
        truck = self._create_track(10, "TRUCK", 0.30, 0.40, zone="DOCK-01", ident_val="GP-1000", master_type="TRUCK")

        classes_to_test = ["GLASS", "ROD", "FASTENER", "PART", "COMPONENT", "MATERIAL"]
        for idx, cls_code in enumerate(classes_to_test):
            mat_track = self._create_track(100 + idx, cls_code, 0.32, 0.42, zone="DOCK-01", ident_val=f"SKU-{cls_code}", master_type="MATERIAL")
            for _ in range(3):
                assocs = session.update([truck, mat_track])

            matched = [a for a in assocs if a.primary_track_id == 10 and a.secondary_track_id == (100 + idx)]
            self.assertEqual(len(matched), 1, f"Failed to associate {cls_code} with truck")
            self.assertEqual(matched[0].secondary_class, cls_code)

    # -------------------------------------------------------------------------
    # TEST 15: Verify Inventory Remains Unchanged
    # -------------------------------------------------------------------------
    def test_15_verify_inventory_remains_unchanged(self):
        db_conn = get_db()
        cursor = db_conn.cursor()

        # Check total inventory row count is exactly 0
        cursor.execute("SELECT COUNT(*) FROM inventory")
        inv_count = cursor.fetchone()[0]
        self.assertEqual(inv_count, 0, f"Inventory was mutated! Expected 0 rows, got {inv_count}")

        # Check sqlite master table count is exactly 17
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_count = cursor.fetchone()[0]
        self.assertEqual(table_count, 17, f"Schema was changed! Expected 17 tables, got {table_count}")


if __name__ == "__main__":
    unittest.main()
