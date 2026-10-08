"""
Part 8 Verification Test Suite: Automotive Material Identity & SKU Recognition Enhancement
Comprehensive deterministic test suite covering all 10 mandatory requirements:
  1. Valid barcode -> SKU (Fasteners / Hardware)
  2. Valid QR -> SKU (Automotive Glass)
  3. OCR/label -> SKU (Steering Rods / Tubes)
  4. Unknown identifier (Unregistered tag)
  5. Ambiguous identifier (Competing OCR reads & Ambiguous master patterns)
  6. Conflicting barcode/OCR evidence (Direct contradictory optical vs text reads)
  7. Automotive material examples: GLASS, ROD, FASTENER, PART, COMPONENT
  8. Existing BOX, TRUCK, WORKER, BIN identity regression
  9. Traceability integration (Resolution to authoritative WMS SKU with VALIDATED_REAL_WORLD)
 10. Inventory unchanged invariant (Zero automatic inventory mutations, 17 tables intact)
"""

import os
import sys
import json
import sqlite3
import unittest

os.environ["WARLOG_TEST_MODE"] = "1"

# Ensure webapp directory is in python path
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(WORKSPACE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

from db import get_db, DB_PATH
from identity_service import get_identity_service, TrackIdentityState, MultiObjectIdentityService
from validation_service import get_validation_service, WarehouseMasterValidator, MasterDataRegistry
from material_traceability_service import (
    get_material_traceability_service,
    TraceabilityLevel,
    MaterialTraceStatus
)
from detection_service import DEFAULT_CLASS_MAPPING, FALLBACK_CLASS_NAMES


class TestAutomotiveMaterialIdentity(unittest.TestCase):
    """Exhaustive test suite for Part 8 Automotive Material Identity & SKU Recognition."""

    @classmethod
    def setUpClass(cls):
        cls.ident_service = get_identity_service()
        cls.val_service = get_validation_service()
        cls.validator = cls.val_service.validator
        cls.trace_service = get_material_traceability_service()

        # Capture database row counts to verify zero database mutations
        cls.initial_counts = cls._get_all_table_counts()

    @classmethod
    def _get_all_table_counts(cls):
        conn = get_db()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        counts = {}
        for t in tables:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        conn.close()
        return counts

    def setUp(self):
        self.ident_service.reset_all()
        self.val_service.reset_all()
        self.trace_service.reset()

    # ------------------------------------------------------------------------
    # Test 1: Valid Barcode -> SKU
    # ------------------------------------------------------------------------
    def test_01_valid_barcode_to_sku(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(101)

        # Feed 1D barcode candidate for Grade 10.9 Flange Bolt
        candidates = [
            {
                "value": "AUTO-BOLT-01",
                "source": "BARCODE",
                "format": "CODE_128",
                "confidence": 0.98
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001", timestamp="2026-10-07 10:00:00")

        # Identity checks
        self.assertEqual(track_state.status, "IDENTIFIED")
        self.assertEqual(track_state.value, "AUTO-BOLT-01")
        self.assertEqual(track_state.source, "BARCODE")
        self.assertEqual(track_state.format, "CODE_128")
        self.assertGreaterEqual(track_state.confidence, 0.95)

        # Raw evidence checks
        raw = track_state.raw_evidence
        self.assertIsNotNone(raw)
        self.assertEqual(raw["barcode_or_qr"], "AUTO-BOLT-01")
        self.assertEqual(raw["barcode_format"], "CODE_128")
        self.assertEqual(raw["source_camera"], "CAM-001")
        self.assertEqual(raw["status"], "IDENTIFIED")

        # Master data validation check
        val_res = self.validator.validate_identity("FASTENER", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "VALIDATED")
        self.assertEqual(val_res["master_type"], "SKU")
        self.assertEqual(val_res["master_id"], "AUTO-BOLT-01")
        self.assertIn("Grade 10.9 Flange Bolt", val_res["display_name"])

    # ------------------------------------------------------------------------
    # Test 2: Valid QR -> SKU
    # ------------------------------------------------------------------------
    def test_02_valid_qr_to_sku(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(102)

        # Feed 2D QR Code candidate for Automotive Glass
        candidates = [
            {
                "value": "AUTO-GLASS-01",
                "source": "QR",
                "format": "QR Code",
                "confidence": 0.98
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001", timestamp="2026-10-07 10:01:00")

        self.assertEqual(track_state.status, "IDENTIFIED")
        self.assertEqual(track_state.value, "AUTO-GLASS-01")
        self.assertEqual(track_state.source, "QR")

        # Validation check
        val_res = self.validator.validate_identity("GLASS", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "VALIDATED")
        self.assertEqual(val_res["master_id"], "AUTO-GLASS-01")
        self.assertIn("Laminated Windshield", val_res["display_name"])

    # ------------------------------------------------------------------------
    # Test 3: OCR/label -> SKU
    # ------------------------------------------------------------------------
    def test_03_ocr_label_to_sku(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(103)

        # Feed OCR candidate for High-Tensile Tie Rod
        candidates = [
            {
                "value": "AUTO-ROD-01",
                "source": "OCR",
                "format": "Printed Label",
                "confidence": 0.88
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001", timestamp="2026-10-07 10:02:00")

        self.assertEqual(track_state.status, "IDENTIFIED")
        self.assertEqual(track_state.value, "AUTO-ROD-01")
        self.assertEqual(track_state.source, "OCR")

        # Raw evidence check
        raw = track_state.raw_evidence
        self.assertEqual(raw["ocr_text"], ["AUTO-ROD-01"])

        # Validation check
        val_res = self.validator.validate_identity("ROD", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "VALIDATED")
        self.assertEqual(val_res["master_id"], "AUTO-ROD-01")
        self.assertIn("High-Tensile Tie Rod", val_res["display_name"])

    # ------------------------------------------------------------------------
    # Test 4: Unknown Identifier
    # ------------------------------------------------------------------------
    def test_04_unknown_identifier(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(104)

        # Barcode recognized visually, but not registered in WMS SKU master
        candidates = [
            {
                "value": "UNKNOWN-AUTO-999",
                "source": "BARCODE",
                "format": "CODE_128",
                "confidence": 0.95
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001")

        self.assertEqual(track_state.status, "IDENTIFIED")
        self.assertEqual(track_state.value, "UNKNOWN-AUTO-999")

        # Master data validation check -> UNREGISTERED
        val_res = self.validator.validate_identity("PART", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "UNREGISTERED")
        self.assertIsNone(val_res["master_id"])
        self.assertIn("no matching WMS record was found in SKU master", val_res["message"])

    # ------------------------------------------------------------------------
    # Test 5: Ambiguous Identifier
    # ------------------------------------------------------------------------
    def test_05_ambiguous_identifier(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(105)

        # 5a. Visual perception ambiguity: Competing OCR candidates with close confidence (delta < 0.15)
        candidates = [
            {
                "value": "SKU-001",
                "source": "OCR",
                "format": "Printed Label",
                "confidence": 0.82
            },
            {
                "value": "SKU-DARK",
                "source": "OCR",
                "format": "Printed Label",
                "confidence": 0.80
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001")

        self.assertEqual(track_state.status, "AMBIGUOUS")
        self.assertIsNone(track_state.value)
        self.assertEqual(len(track_state.candidates), 2)

        # Validation rejects ambiguous visual state with NOT_APPLICABLE
        val_res = self.validator.validate_identity("MATERIAL", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "NOT_APPLICABLE")
        self.assertIn("Identity ambiguous must be resolved", val_res["message"])

        # 5b. Master-data query ambiguity: Wildcard or ambiguous pattern matching multiple SKUs
        val_pattern = self.validator.validate_material("AUTO-%", object_class="MATERIAL")
        self.assertEqual(val_pattern["status"], "AMBIGUOUS")
        self.assertIsNone(val_pattern["master_id"])
        self.assertIn("Multiple authoritative SKUs", val_pattern["message"])

    # ------------------------------------------------------------------------
    # Test 6: Conflicting Barcode/OCR Evidence
    # ------------------------------------------------------------------------
    def test_06_conflicting_barcode_ocr_evidence(self):
        sess = self.ident_service.get_session("CAM-001")
        track_state = sess.get_track_identity(106)

        # Barcode indicates AUTO-GLASS-01, but printed OCR label clearly says AUTO-ROD-01
        candidates = [
            {
                "value": "AUTO-GLASS-01",
                "source": "QR",
                "format": "QR Code",
                "confidence": 0.98
            },
            {
                "value": "AUTO-ROD-01",
                "source": "OCR",
                "format": "Printed Label",
                "confidence": 0.85
            }
        ]
        track_state.update(candidates, frame_index=1, camera_id="CAM-001")

        # Distinguishes CONFLICT
        self.assertEqual(track_state.status, "CONFLICT")
        self.assertIsNone(track_state.value)
        self.assertEqual(len(track_state.candidates), 2)

        # Raw evidence preserves both conflicting sources
        raw = track_state.raw_evidence
        self.assertEqual(raw["barcode_or_qr"], "AUTO-GLASS-01")
        self.assertIn("AUTO-ROD-01", raw["ocr_text"])
        self.assertEqual(raw["status"], "CONFLICT")

        # Master data validation safely blocks conflicting reads
        val_res = self.validator.validate_identity("MATERIAL", track_state.value, track_state.status, track_state.source)
        self.assertEqual(val_res["status"], "NOT_APPLICABLE")
        self.assertIn("Identity conflict must be resolved", val_res["message"])

    # ------------------------------------------------------------------------
    # Test 7: Automotive Material Examples: GLASS, ROD, FASTENER, PART, COMPONENT
    # ------------------------------------------------------------------------
    def test_07_automotive_material_examples(self):
        # 7a. GLASS
        r_glass = self.validator.validate_identity("GLASS", "AUTO-GLASS-01", "IDENTIFIED", "QR")
        self.assertEqual(r_glass["status"], "VALIDATED")
        self.assertEqual(r_glass["master_id"], "AUTO-GLASS-01")
        self.assertIn("Glass SKU: AUTO-GLASS-01", r_glass["display_name"])

        # 7b. ROD
        r_rod = self.validator.validate_identity("ROD", "AUTO-ROD-01", "IDENTIFIED", "OCR")
        self.assertEqual(r_rod["status"], "VALIDATED")
        self.assertEqual(r_rod["master_id"], "AUTO-ROD-01")
        self.assertIn("Rod SKU: AUTO-ROD-01", r_rod["display_name"])

        # 7c. FASTENER
        r_fastener = self.validator.validate_identity("FASTENER", "AUTO-BOLT-01", "IDENTIFIED", "BARCODE")
        self.assertEqual(r_fastener["status"], "VALIDATED")
        self.assertEqual(r_fastener["master_id"], "AUTO-BOLT-01")
        self.assertIn("Fastener SKU: AUTO-BOLT-01", r_fastener["display_name"])

        # 7d. PART
        r_part = self.validator.validate_identity("PART", "SKU-001", "IDENTIFIED", "BARCODE")
        self.assertEqual(r_part["status"], "VALIDATED")
        self.assertEqual(r_part["master_id"], "SKU-001")
        self.assertIn("Part SKU: SKU-001", r_part["display_name"])

        # 7e. COMPONENT
        r_comp = self.validator.validate_identity("COMPONENT", "SKU-DARK", "IDENTIFIED", "OCR")
        self.assertEqual(r_comp["status"], "VALIDATED")
        self.assertEqual(r_comp["master_id"], "SKU-DARK")
        self.assertIn("Component SKU: SKU-DARK", r_comp["display_name"])

        # Verify taxonomy mappings in detection_service
        self.assertIn("GLASS", FALLBACK_CLASS_NAMES)
        self.assertIn("ROD", FALLBACK_CLASS_NAMES)
        self.assertIn("FASTENER", FALLBACK_CLASS_NAMES)
        self.assertIn("MATERIAL", FALLBACK_CLASS_NAMES)
        self.assertEqual(DEFAULT_CLASS_MAPPING["glass"], "GLASS")
        self.assertEqual(DEFAULT_CLASS_MAPPING["rod"], "ROD")
        self.assertEqual(DEFAULT_CLASS_MAPPING["fastener"], "FASTENER")

    # ------------------------------------------------------------------------
    # Test 8: Existing BOX, TRUCK, WORKER, BIN Identity Regression
    # ------------------------------------------------------------------------
    def test_08_existing_box_and_entity_regression(self):
        # 8a. BOX with consignment SKU VLV-900
        r_box = self.validator.validate_identity("BOX", "VLV-900", "IDENTIFIED", "OCR")
        self.assertEqual(r_box["status"], "VALIDATED")
        self.assertEqual(r_box["master_type"], "BOX")
        self.assertEqual(r_box["master_id"], "VLV-900")

        # 8b. BOX with authoritative SKU AUTO-GLASS-01
        r_box_sku = self.validator.validate_identity("BOX", "AUTO-GLASS-01", "IDENTIFIED", "BARCODE")
        self.assertEqual(r_box_sku["status"], "VALIDATED")
        self.assertEqual(r_box_sku["master_id"], "AUTO-GLASS-01")

        # 8c. TRUCK with Gate Pass GP-1000
        r_truck = self.validator.validate_identity("TRUCK", "GP-1000", "IDENTIFIED", "QR")
        self.assertEqual(r_truck["status"], "VALIDATED")
        self.assertEqual(r_truck["master_type"], "TRUCK")

        # 8d. WORKER with admin user
        r_worker = self.validator.validate_identity("WORKER", "admin", "IDENTIFIED", "OCR")
        self.assertEqual(r_worker["status"], "VALIDATED")
        self.assertEqual(r_worker["master_type"], "WORKER")

        # 8e. BIN with BIN-01 (bins table has 0 rows in baseline DB -> UNREGISTERED)
        r_bin = self.validator.validate_identity("BIN", "BIN-01", "IDENTIFIED", "BARCODE")
        self.assertEqual(r_bin["status"], "UNREGISTERED")
        self.assertIn("no matching physical storage bin was found", r_bin["message"])

    # ------------------------------------------------------------------------
    # Test 9: Traceability Integration
    # ------------------------------------------------------------------------
    def test_09_traceability_integration(self):
        # Ingest movement event for automotive glass material
        evt = {
            "event_id": "EVT-GLASS-001",
            "event_type": "BOX_ENTERED_ZONE",
            "camera_id": "CAM-001",
            "timestamp": "2026-10-07T12:00:00Z",
            "primary_object": {
                "track_id": 77,
                "class_code": "GLASS",
                "identity_id": "AUTO-GLASS-01",
                "identity_status": "VALIDATED"
            },
            "zone": {"zone_id": 2, "zone_code": "STAGING-01", "zone_name": "Staging Area 1"},
            "confidence": 0.96,
            "status": "ACTIVE"
        }
        res = self.trace_service.ingest_movement_event(evt)
        self.assertIsNotNone(res)
        self.assertEqual(res.material_id, "AUTO-GLASS-01")
        self.assertEqual(res.trace_level, TraceabilityLevel.VALIDATED_REAL_WORLD)
        self.assertEqual(res.nature, "VALIDATED")

        # Check dossier
        dossier = self.trace_service.get_material("AUTO-GLASS-01")
        self.assertIsNotNone(dossier)
        self.assertEqual(dossier["material_id"], "AUTO-GLASS-01")
        self.assertEqual(dossier["material_class"], "GLASS")
        self.assertEqual(dossier["identity_status"], "VALIDATED")
        self.assertEqual(dossier["traceability_level"], TraceabilityLevel.VALIDATED_REAL_WORLD)
        self.assertEqual(dossier["traceability_status"], MaterialTraceStatus.AT_ZONE)

    # ------------------------------------------------------------------------
    # Test 10: Inventory Unchanged Invariant
    # ------------------------------------------------------------------------
    def test_10_inventory_unchanged_invariant(self):
        # Verify inventory table is completely intact with 0 mutations
        conn = get_db()
        inv_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        self.assertEqual(inv_count, 0, f"INVENTORY MUTATION DETECTED! Expected 0 rows, got {inv_count}")

        # Verify all table counts remain strictly invariant
        final_counts = self._get_all_table_counts()
        for tbl, count in self.initial_counts.items():
            self.assertEqual(
                final_counts[tbl], count,
                f"Database write violation detected on table '{tbl}': initial {count}, final {final_counts[tbl]}"
            )

        # Verify table count is strictly 17
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        conn.close()
        self.assertEqual(len(tables), 17, f"Schema modification detected: {len(tables)} tables")


if __name__ == '__main__':
    unittest.main()
