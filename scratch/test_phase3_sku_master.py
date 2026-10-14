"""
Test Suite for Phase 3: AI Vision SKU Master Data & Product Image Mapping
Verifies:
1. SKU Master schema & database operations (CRUD, pagination, filtering).
2. Excel template generation (.xlsx).
3. Excel preview and row-level validation (missing fields, duplicate codes, invalid numbers).
4. Transactional Excel batch import with duplicate policies ('skip' vs 'update').
5. Separation of concerns: SKU upload must NOT mutate inventory or bin balances.
6. Filename-based bulk image matching logic.
7. Product image upload, mapping persistence, primary designation, and safe cleanup.
8. API endpoints via Flask test client.
"""

import os
import sys
import io
import unittest
import openpyxl

# Fast test mode
os.environ["WARLOG_TEST_MODE"] = "1"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import db
import sku_master_service
from app import app


class Phase3SkuMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()
        db.init_db()

    def setUp(self):
        # Clean up any test SKUs created during tests
        conn = db.get_db()
        conn.execute("DELETE FROM sku_images WHERE sku_id LIKE 'TEST-SKU%'")
        conn.execute("DELETE FROM skus WHERE sku_id LIKE 'TEST-SKU%'")
        conn.commit()
        conn.close()

    def test_01_sku_crud_operations(self):
        """Verify creating, retrieving, updating, and deleting an SKU master record."""
        # Create
        sku_payload = {
            "sku_id": "TEST-SKU-001",
            "name": "Industrial Test Optical Sensor",
            "description": "High precision photoelectric sensor 24V",
            "category": "Electronics",
            "uom": "EA",
            "unit_weight": 0.35,
            "unit_volume": 0.002,
            "status": "Active"
        }
        saved, err = db.save_sku_master_record(sku_payload)
        self.assertIsNone(err, f"Save SKU failed: {err}")
        self.assertIsNotNone(saved)
        self.assertEqual(saved['sku_id'], "TEST-SKU-001")
        self.assertEqual(saved['name'], "Industrial Test Optical Sensor")
        self.assertEqual(saved['uom'], "EA")

        # Read
        retrieved = db.get_sku_by_id("TEST-SKU-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['category'], "Electronics")

        # Update
        sku_payload['name'] = "Industrial Optical Sensor Pro v2"
        updated, err = db.save_sku_master_record(sku_payload)
        self.assertIsNone(err)
        self.assertEqual(updated['name'], "Industrial Optical Sensor Pro v2")

        # Delete
        deleted, err = db.delete_sku_master_record("TEST-SKU-001")
        self.assertTrue(deleted)
        self.assertIsNone(db.get_sku_by_id("TEST-SKU-001"))

    def test_02_excel_template_generation(self):
        """Verify the downloadable .xlsx template contains the required header columns."""
        excel_bytes = sku_master_service.generate_sku_excel_template()
        self.assertIsInstance(excel_bytes, bytes)
        self.assertTrue(len(excel_bytes) > 1000)

        # Inspect workbook contents
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        self.assertIn("SKU Code *", headers)
        self.assertIn("Product Name *", headers)
        self.assertIn("Category", headers)
        self.assertIn("UOM", headers)

    def test_03_excel_preview_and_validation(self):
        """Verify preview parsing, required field checks, duplicate checks, and action assignment."""
        # Create a test in-memory workbook with 4 rows:
        # Row 1: Valid new SKU
        # Row 2: Missing name (Invalid)
        # Row 3: Duplicate within file (Invalid)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["SKU Code *", "Product Name *", "Description", "Category", "UOM", "Unit Weight (kg)", "Unit Volume (m3)", "Status"])
        ws.append(["TEST-SKU-A", "Component Alpha", "First test part", "Electronics", "EA", 1.2, 0.05, "Active"])
        ws.append(["TEST-SKU-B", "", "Missing name item", "Hardware", "BOX", 2.0, 0.10, "Active"])
        ws.append(["TEST-SKU-A", "Duplicate Alpha", "Duplicate row", "Electronics", "EA", 1.2, 0.05, "Active"])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        preview = sku_master_service.parse_and_validate_sku_excel(buf.getvalue(), duplicate_policy="skip")
        self.assertTrue(preview['success'])
        self.assertEqual(preview['total_rows'], 3)
        self.assertEqual(preview['valid_new_count'], 1)
        self.assertEqual(preview['invalid_count'], 2)

        # Row 1 is INSERT
        self.assertEqual(preview['rows'][0]['action'], "INSERT")
        self.assertEqual(preview['rows'][0]['sku_id'], "TEST-SKU-A")

        # Row 2 is REJECT (missing name)
        self.assertEqual(preview['rows'][1]['action'], "REJECT")
        self.assertIn("Product Name is required", preview['rows'][1]['error'])

        # Row 3 is REJECT (duplicate code in file)
        self.assertEqual(preview['rows'][2]['action'], "REJECT")
        self.assertIn("Duplicate SKU", preview['rows'][2]['error'])

    def test_04_batch_import_and_duplicate_policy(self):
        """Verify transactional batch import and duplicate policies ('skip' vs 'update')."""
        rows = [
            {"row_num": 2, "sku_id": "TEST-SKU-100", "name": "Item Original", "category": "Parts", "uom": "EA", "unit_weight": 1.0, "unit_volume": 0.01, "status": "Active"},
            {"row_num": 3, "sku_id": "TEST-SKU-200", "name": "Item Beta", "category": "Parts", "uom": "BOX", "unit_weight": 2.5, "unit_volume": 0.05, "status": "Active"}
        ]

        # 1. Initial import with 'skip'
        res1 = db.batch_import_sku_records(rows, duplicate_policy="skip")
        self.assertTrue(res1['success'])
        self.assertEqual(res1['inserted'], 2)
        self.assertEqual(res1['skipped'], 0)

        # 2. Re-import with 'skip' -> both skipped
        res2 = db.batch_import_sku_records(rows, duplicate_policy="skip")
        self.assertEqual(res2['inserted'], 0)
        self.assertEqual(res2['skipped'], 2)

        # 3. Re-import with 'update' -> updates attributes
        rows[0]['name'] = "Item Updated Name"
        res3 = db.batch_import_sku_records(rows, duplicate_policy="update")
        self.assertEqual(res3['updated'], 2)
        sku_updated = db.get_sku_by_id("TEST-SKU-100")
        self.assertEqual(sku_updated['name'], "Item Updated Name")

    def test_05_sku_import_does_not_mutate_inventory(self):
        """Verify that importing an SKU master record NEVER creates inventory stock or bin balances."""
        conn = db.get_db()
        inv_count_before = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        bin_count_before = conn.execute("SELECT COUNT(*) FROM bins").fetchone()[0]
        conn.close()

        # Import new test SKU
        db.save_sku_master_record({
            "sku_id": "TEST-SKU-NO-INV",
            "name": "Non Inventory Mutating SKU",
            "category": "Test"
        })

        conn = db.get_db()
        inv_count_after = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        bin_count_after = conn.execute("SELECT COUNT(*) FROM bins").fetchone()[0]
        conn.close()

        self.assertEqual(inv_count_before, inv_count_after, "SKU master import must NEVER alter inventory balances")
        self.assertEqual(bin_count_before, bin_count_after, "SKU master import must NEVER alter bin records")

    def test_06_filename_based_image_matching(self):
        """Verify automatic matching of filenames like 'TEST-SKU-MATCH.jpg' to SKU 'TEST-SKU-MATCH'."""
        db.save_sku_master_record({"sku_id": "TEST-SKU-MATCH", "name": "Target Match Part"})

        filenames = [
            "TEST-SKU-MATCH.jpg",
            "TEST-SKU-MATCH_front.png",
            "UNKNOWN-PART.webp",
            "document.pdf"
        ]

        matches = sku_master_service.match_bulk_images_to_skus(filenames)
        self.assertEqual(len(matches), 4)

        # 1. Exact match
        self.assertEqual(matches[0]['status'], "MATCHED")
        self.assertEqual(matches[0]['matched_sku_id'], "TEST-SKU-MATCH")

        # 2. Prefix match before underscore
        self.assertEqual(matches[1]['status'], "MATCHED")
        self.assertEqual(matches[1]['matched_sku_id'], "TEST-SKU-MATCH")

        # 3. Unknown SKU
        self.assertEqual(matches[2]['status'], "UNMATCHED")

        # 4. Invalid file type
        self.assertEqual(matches[3]['status'], "INVALID_TYPE")

    def test_07_sku_image_upload_and_primary_flag(self):
        """Verify adding, designating primary, and deleting SKU reference images."""
        db.save_sku_master_record({"sku_id": "TEST-SKU-IMG", "name": "Image Target Part"})

        # Add image 1 (automatically becomes primary)
        img1, err = db.add_sku_image("TEST-SKU-IMG", "test1.jpg", "test1.jpg", "/static/uploads/sku_images/test1.jpg", 1024)
        self.assertIsNone(err)
        self.assertTrue(img1['is_primary'])

        # Add image 2 (secondary)
        img2, err = db.add_sku_image("TEST-SKU-IMG", "test2.jpg", "test2.jpg", "/static/uploads/sku_images/test2.jpg", 2048, is_primary=0)
        self.assertIsNone(err)
        self.assertFalse(img2['is_primary'])

        # Switch primary to image 2
        ok, err = db.set_sku_primary_image("TEST-SKU-IMG", img2['id'])
        self.assertTrue(ok)
        sku_data = db.get_sku_by_id("TEST-SKU-IMG")
        self.assertEqual(sku_data['primary_image']['id'], img2['id'])

        # Delete image
        del_rec, err = db.delete_sku_image(img1['id'])
        self.assertIsNone(err)
        self.assertEqual(len(db.get_sku_images("TEST-SKU-IMG")), 1)

    def test_08_flask_api_endpoints(self):
        """Verify HTTP endpoints for SKU master listing, search, and detail."""
        db.save_sku_master_record({"sku_id": "TEST-SKU-API", "name": "API Verification Product", "category": "Sensors"})

        # List
        res = self.client.get('/api/sku_master?search=API%20Verification')
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data['success'])
        self.assertTrue(any(s['sku_id'] == "TEST-SKU-API" for s in json_data['data']['items']))

        # Detail
        res_detail = self.client.get('/api/sku_master/TEST-SKU-API')
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.get_json()['data']['sku_id'], "TEST-SKU-API")


if __name__ == "__main__":
    unittest.main()
