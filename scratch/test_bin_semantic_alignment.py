"""
Test Suite: Part B - Bin <-> Vision Zone Semantic Alignment
Verifies authoritative boundary between WMS physical storage bins and AI spatial vision zones.

Mandatory Checkpoints (Task 8):
1. Valid physical bin_id -> VALIDATED
2. Unknown bin_id -> UNREGISTERED
3. Vision zone code that does NOT correspond to a physical bin -> must NOT falsely validate as a Bin
4. Valid vision zone context + valid WMS bin -> preserves correct spatial + physical distinction
5. Wrong object class -> rejected
6. Ambiguous identity -> existing ambiguity behavior preserved
7. Existing validation APIs continue to work (GET status, POST /api/vision/validate, POST /api/vision/validation/test)
8. Box <-> Bin association still works
9. Material traceability still works
10. No inventory mutation (inventory count == 0)
11. No schema mutation (17 tables unchanged, schema DDL unchanged)
"""

import os
import sys
import unittest
import sqlite3
import json

# Ensure webapp directory is in path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(BASE_DIR, 'webapp')
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import db
from validation_service import (
    WarehouseMasterValidator,
    MasterDataRegistry,
    get_validation_service
)
from box_bin_association_service import (
    get_box_bin_association_service,
    CameraBoxBinAssociationSession
)
from material_traceability_service import (
    get_material_traceability_service,
    EventType,
    MaterialTraceStatus
)
import app as flask_app_module


class TestBinSemanticAlignment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.validator = WarehouseMasterValidator()
        cls.val_service = get_validation_service()
        cls.client = flask_app_module.app.test_client()
        cls.db_path = os.path.join(WEBAPP_DIR, 'skandha_wms.db')

        # Snapshot baseline DB metrics
        cls.initial_counts = cls._get_table_counts()
        cls.initial_schema = cls._get_table_schemas()

    @classmethod
    def _get_table_counts(cls):
        conn = sqlite3.connect(cls.db_path)
        cur = conn.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        conn.close()
        return counts

    @classmethod
    def _get_table_schemas(cls):
        conn = sqlite3.connect(cls.db_path)
        cur = conn.cursor()
        schemas = {r[0]: r[1] for r in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        conn.close()
        return schemas

    # -------------------------------------------------------------------------
    # CHECKPOINT 1: Valid physical bin_id -> VALIDATED
    # -------------------------------------------------------------------------
    def test_01_valid_physical_bin_validated(self):
        """A valid physical bin registered in WMS bins table must return VALIDATED."""
        # Use isolated in-memory DB containing physical bin BIN-01
        mem_conn = sqlite3.connect(':memory:')
        mem_conn.row_factory = sqlite3.Row
        mem_conn.execute("""
            CREATE TABLE bins (
                bin_id TEXT PRIMARY KEY,
                zone TEXT DEFAULT 'General',
                max_volume REAL DEFAULT 100.0,
                current_volume REAL DEFAULT 0.0,
                max_weight REAL DEFAULT 1000.0,
                current_weight REAL DEFAULT 0.0,
                status TEXT DEFAULT 'Active',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        mem_conn.execute("""
            CREATE TABLE vision_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_code TEXT UNIQUE NOT NULL,
                zone_name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                warehouse TEXT NOT NULL DEFAULT 'Warehouse A',
                description TEXT,
                status TEXT DEFAULT 'Active'
            )
        """)
        mem_conn.execute("INSERT INTO vision_zones (zone_code, zone_name, zone_type) VALUES ('BIN-A', 'High Density Bin Area A', 'BIN_AREA')")
        mem_conn.execute("INSERT INTO bins (bin_id, zone, max_volume, max_weight) VALUES ('BIN-01', 'BIN-A', 500.0, 2000.0)")
        mem_conn.commit()

        # Monkeypatch get_db temporarily for this isolated lookup
        orig_get_db = db.get_db
        try:
            import validation_service
            validation_service.get_db = lambda: mem_conn
            res = self.validator.validate_bin('BIN-01')

            self.assertEqual(res['status'], 'VALIDATED')
            self.assertEqual(res['master_type'], 'BIN')
            self.assertEqual(res['master_id'], 'BIN-01')
            self.assertEqual(res['matched_field'], 'bin_id')
            self.assertEqual(res['master_record']['bin_id'], 'BIN-01')
            self.assertEqual(res['master_record']['zone'], 'BIN-A')
            self.assertIn('BIN-01', res['display_name'])
        finally:
            import validation_service
            validation_service.get_db = orig_get_db
            mem_conn.close()

    # -------------------------------------------------------------------------
    # CHECKPOINT 2: Unknown bin_id -> UNREGISTERED
    # -------------------------------------------------------------------------
    def test_02_unknown_bin_unregistered(self):
        """An unknown physical bin ID must return UNREGISTERED."""
        res = self.validator.validate_bin('NON-EXISTENT-BIN-999')
        self.assertEqual(res['status'], 'UNREGISTERED')
        self.assertIsNone(res['master_type'])
        self.assertIsNone(res['master_id'])
        self.assertIsNone(res['display_name'])
        self.assertIn('no matching physical storage bin was found in WMS Bin Master', res['message'])

    # -------------------------------------------------------------------------
    # CHECKPOINT 3: Vision zone code does NOT falsely validate as a physical Bin
    # -------------------------------------------------------------------------
    def test_03_vision_zone_does_not_falsely_validate_as_bin(self):
        """
        Vision zones (BIN-A, DOCK-01, TB-01, SORT-01) exist in vision_zones table,
        but do NOT exist in bins table. They MUST NOT falsely validate as physical storage bins.
        """
        # Test existing vision zones in skandha_wms.db
        for vz_code in ['BIN-A', 'DOCK-01', 'DOCK-02', 'TB-01', 'SORT-01', 'STG-01', 'UNLOAD-01']:
            res = self.validator.validate_bin(vz_code)
            self.assertEqual(
                res['status'], 'UNREGISTERED',
                f"Defect: Vision Zone '{vz_code}' falsely validated as a physical storage bin!"
            )
            self.assertIsNone(res['master_id'])

    # -------------------------------------------------------------------------
    # CHECKPOINT 4: Valid vision zone context + valid WMS bin
    # -------------------------------------------------------------------------
    def test_04_spatial_context_and_physical_bin_distinction(self):
        """
        Preserves clean separation between:
          - Physical storage bin: bin_id, zone, capacity, weight
          - Spatial vision zone: zone_code, zone_name, zone_type, warehouse
        """
        mem_conn = sqlite3.connect(':memory:')
        mem_conn.row_factory = sqlite3.Row
        mem_conn.execute("""
            CREATE TABLE bins (
                bin_id TEXT PRIMARY KEY,
                zone TEXT DEFAULT 'General',
                max_volume REAL DEFAULT 100.0,
                current_volume REAL DEFAULT 0.0,
                max_weight REAL DEFAULT 1000.0,
                current_weight REAL DEFAULT 0.0,
                status TEXT DEFAULT 'Active',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        mem_conn.execute("""
            CREATE TABLE vision_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_code TEXT UNIQUE NOT NULL,
                zone_name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                warehouse TEXT NOT NULL DEFAULT 'Warehouse A',
                description TEXT,
                status TEXT DEFAULT 'Active'
            )
        """)
        mem_conn.execute("INSERT INTO vision_zones (zone_code, zone_name, zone_type, warehouse) VALUES ('BIN-A', 'High Density Bin Area A', 'BIN_AREA', 'Warehouse A')")
        mem_conn.execute("INSERT INTO bins (bin_id, zone, max_volume, current_volume, max_weight, current_weight) VALUES ('BIN-RACK-01', 'BIN-A', 100.0, 25.0, 500.0, 120.0)")
        mem_conn.commit()

        orig_get_db = db.get_db
        try:
            import validation_service
            validation_service.get_db = lambda: mem_conn
            res = self.validator.validate_bin('BIN-RACK-01')

            self.assertEqual(res['status'], 'VALIDATED')
            # Physical attributes
            rec = res['master_record']
            self.assertEqual(rec['bin_id'], 'BIN-RACK-01')
            self.assertEqual(rec['zone'], 'BIN-A')
            self.assertEqual(rec['max_volume'], 100.0)
            self.assertEqual(rec['current_volume'], 25.0)

            # Spatial context resolved from vision zone
            spatial = rec.get('spatial_context')
            self.assertIsNotNone(spatial, "Spatial context must be populated when bin.zone maps to vision_zones")
            self.assertEqual(spatial['zone_code'], 'BIN-A')
            self.assertEqual(spatial['zone_name'], 'High Density Bin Area A')
            self.assertEqual(spatial['zone_type'], 'BIN_AREA')
            self.assertEqual(spatial['warehouse'], 'Warehouse A')

            # Display name reflects both
            self.assertIn('BIN-RACK-01', res['display_name'])
            self.assertIn('High Density Bin Area A', res['display_name'])
        finally:
            import validation_service
            validation_service.get_db = orig_get_db
            mem_conn.close()

    # -------------------------------------------------------------------------
    # CHECKPOINT 5: Wrong object class -> rejected
    # -------------------------------------------------------------------------
    def test_05_wrong_object_class_rejected(self):
        """
        Object-class awareness must reject identity lookups against inappropriate master tables:
          - A detected TRUCK presented with a bin ID must NOT validate as a truck
          - A detected BOX presented with a bin ID must NOT validate as a box
        """
        res_truck = self.validator.validate_identity('TRUCK', 'BIN-01', 'IDENTIFIED')
        self.assertEqual(res_truck['status'], 'UNREGISTERED')

        res_box = self.validator.validate_identity('BOX', 'BIN-01', 'IDENTIFIED')
        self.assertEqual(res_box['status'], 'UNREGISTERED')

    # -------------------------------------------------------------------------
    # CHECKPOINT 6: Ambiguous / Conflict identity handling preserved
    # -------------------------------------------------------------------------
    def test_06_ambiguous_and_conflict_identities_rejected(self):
        """Unidentified or conflicting visual identities must NOT validate."""
        # Unidentified
        res_unid = self.validator.validate_identity('BIN', None, 'UNIDENTIFIED')
        self.assertEqual(res_unid['status'], 'NOT_APPLICABLE')

        # Conflict
        res_conflict = self.validator.validate_identity('BIN', 'BIN-01', 'CONFLICT')
        self.assertEqual(res_conflict['status'], 'NOT_APPLICABLE')
        self.assertIn('conflict', res_conflict['message'].lower())

        # Ambiguous
        res_ambig = self.validator.validate_identity('BIN', 'BIN-01', 'AMBIGUOUS')
        self.assertEqual(res_ambig['status'], 'NOT_APPLICABLE')
        self.assertIn('ambiguous', res_ambig['message'].lower())

        # Empty string
        res_empty = self.validator.validate_identity('BIN', '   ', 'IDENTIFIED')
        self.assertEqual(res_empty['status'], 'NOT_APPLICABLE')

    # -------------------------------------------------------------------------
    # CHECKPOINT 7: Validation API Compatibility
    # -------------------------------------------------------------------------
    def test_07_validation_apis_contract_preserved(self):
        """
        Verify:
          - GET /api/vision/validation/status (exposes 'bins' for BIN class)
          - POST /api/vision/validate (supports direct validation contract)
          - POST /api/vision/validation/test (pipeline test endpoint)
        """
        # 1. GET /api/vision/validation/status
        status_resp = self.client.get('/api/vision/validation/status')
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.get_json()
        self.assertEqual(status_data['status'], 'healthy')
        bin_meta = status_data['available_masters']['BIN']
        self.assertTrue(bin_meta['available'])
        self.assertEqual(bin_meta['tables'], ['bins'])
        self.assertIn('bin_id', bin_meta['fields'])

        # 2. POST /api/vision/validate
        # Test unknown bin via endpoint
        val_resp = self.client.post('/api/vision/validate', json={
            'class_code': 'BIN',
            'identity_value': 'UNKNOWN-BIN-123'
        })
        self.assertEqual(val_resp.status_code, 200)
        val_data = val_resp.get_json()
        self.assertEqual(val_data['status'], 'UNREGISTERED')

        # Test vision zone code via endpoint
        val_vz_resp = self.client.post('/api/vision/validate', json={
            'class_code': 'BIN',
            'identity_value': 'BIN-A'
        })
        self.assertEqual(val_vz_resp.status_code, 200)
        self.assertEqual(val_vz_resp.get_json()['status'], 'UNREGISTERED')

        # Test valid TRUCK gate pass via endpoint to verify contract
        val_truck_resp = self.client.post('/api/vision/validate', json={
            'class_code': 'TRUCK',
            'identity_value': 'GP-1000'
        })
        self.assertEqual(val_truck_resp.status_code, 200)
        self.assertEqual(val_truck_resp.get_json()['status'], 'VALIDATED')

    # -------------------------------------------------------------------------
    # CHECKPOINT 8: Box <-> Bin Association Compatibility
    # -------------------------------------------------------------------------
    def test_08_box_bin_association_compatibility(self):
        """
        Verify that box-bin association continues to function seamlessly with
        the physical bin identity model, without performing inventory putaway.
        """
        session = CameraBoxBinAssociationSession(camera_id="CAM-TEST-BIN")
        camera_zones = [{"zone_code": "STORAGE-01", "zone_name": "Storage Area 1", "zone_type": "STORAGE"}]

        # Create tracks for Box and Bin with valid spatial proximity and zone
        tracks = [
            {
                "track_id": 1,
                "class_code": "BOX",
                "zone": "STORAGE-01",
                "bbox": {"x": 100, "y": 100, "w": 50, "h": 50},
                "center": [0.45, 0.50],
                "identity": {"value": "VLV-900", "status": "IDENTIFIED"},
                "validation": {"status": "VALIDATED", "master_type": "BOX", "master_id": "VLV-900"}
            },
            {
                "track_id": 2,
                "class_code": "BIN",
                "zone": "STORAGE-01",
                "bbox": {"x": 110, "y": 100, "w": 60, "h": 60},
                "center": [0.47, 0.50],
                "identity": {"value": "BIN-01", "status": "IDENTIFIED"},
                "validation": {"status": "VALIDATED", "master_type": "BIN", "master_id": "BIN-01"}
            }
        ]

        # Process 3 consecutive frames to confirm association
        assocs = []
        for f in range(1, 4):
            assocs = session.update(tracks, camera_zones, frame_index=f)

        self.assertEqual(len(assocs), 1)
        assoc = assocs[0]
        self.assertEqual(str(assoc.status), "CONFIRMED")
        self.assertIsNotNone(assoc.real_world_association)
        self.assertEqual(assoc.real_world_association["bin_id"], "BIN-01")
        self.assertEqual(assoc.real_world_association["box_id"], "VLV-900")
        self.assertEqual(assoc.real_world_association["status"], "VALIDATED")

    # -------------------------------------------------------------------------
    # CHECKPOINT 9: Material Traceability Compatibility
    # -------------------------------------------------------------------------
    def test_09_material_traceability_compatibility(self):
        """
        Verify that material traceability records bin destination from vision events
        without mutating WMS inventory or creating putaway transactions.
        """
        trace_svc = get_material_traceability_service()
        trace_svc.reset()

        evt = {
            "event_id": "EVT-TEST-BIN-01",
            "event_type": EventType.BOX_ASSOCIATED_WITH_BIN,
            "timestamp": "2026-10-03T21:00:00",
            "camera_id": "CAM-001",
            "confidence": 0.95,
            "zone": {"zone_code": "BIN-A"},
            "primary_object": {
                "track_id": 1,
                "class_code": "BOX",
                "identity_id": "VLV-900",
                "identity_status": "IDENTIFIED"
            },
            "secondary_object": {
                "track_id": 2,
                "class_code": "BIN",
                "identity_id": "BIN-01",
                "identity_status": "VALIDATED"
            }
        }

        trace_evt = trace_svc.ingest_movement_event(evt)
        self.assertIsNotNone(trace_evt)

        # Retrieve authoritative material trace record (dictionary)
        record = trace_svc.get_material("VLV-900")
        self.assertIsNotNone(record)
        self.assertEqual(record["material_id"], "VLV-900")
        self.assertEqual(record["traceability_status"], MaterialTraceStatus.DESTINATION_OBSERVED)
        self.assertEqual(record["destination"]["identity_id"], "BIN-01")
        self.assertEqual(len(record["associated_bins"]), 1)

    # -------------------------------------------------------------------------
    # CHECKPOINT 10: Zero Inventory Mutation Verification
    # -------------------------------------------------------------------------
    def test_10_no_inventory_mutation(self):
        """Verify that inventory row count remains strictly 0 (no putaway transactions)."""
        counts = self._get_table_counts()
        self.assertEqual(counts.get('inventory', 0), 0, "Inventory count must remain 0!")
        self.assertEqual(counts.get('inventory', 0), self.initial_counts.get('inventory', 0))

    # -------------------------------------------------------------------------
    # CHECKPOINT 11: Database Schema Integrity Verification
    # -------------------------------------------------------------------------
    def test_11_database_schema_integrity(self):
        """Verify that database schema and table counts are completely unchanged."""
        counts = self._get_table_counts()
        schemas = self._get_table_schemas()

        # Table count check
        self.assertEqual(len(counts), 17, "Table count must remain exactly 17!")
        self.assertEqual(counts['bins'], 0, "Bins row count in skandha_wms.db must remain 0!")

        # All table counts match baseline
        for tbl, c in self.initial_counts.items():
            self.assertEqual(counts[tbl], c, f"Row count for table '{tbl}' mutated: initial {c}, current {counts[tbl]}")

        # All schemas match baseline
        for tbl, ddl in self.initial_schema.items():
            self.assertEqual(schemas[tbl], ddl, f"Schema DDL for table '{tbl}' was modified!")


if __name__ == '__main__':
    unittest.main()
