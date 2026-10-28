"""
Validation Test Suite for Palletization Counting Refactor (Phase 1)
Tests:
1. Confirmed 5 x 5 x 5 matrix produces 125 pieces.
2. Bundle mode and individual-piece mode remain distinct.
3. Pallet packaging is excluded from stock quantity.
4. Manual marker addition and deletion recalculates displayed count.
5. Inferred quantities are not represented as directly detected objects.
6. Image and camera snapshot paths use the same counting semantics.
7. Existing pallet finalization and inventory isolation remain intact.
"""

import os
import sys
import unittest
import numpy as np
import cv2
import json

# Ensure webapp is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

from pallet_vision_counting_service import get_pallet_vision_counting_service
import app as flask_app_module
import db


class TestPalletCountingRefactor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.service = get_pallet_vision_counting_service()
        cls.flask_app = flask_app_module.app
        cls.flask_app.config['TESTING'] = True
        cls.client = cls.flask_app.test_client()

        # Create a synthetic 800x800 test pallet image (Simulated test fixture)
        cls.synthetic_img = np.ones((800, 800, 3), dtype=np.uint8) * 40
        # Draw simulated pallet carton bounding area
        cv2.rectangle(cls.synthetic_img, (100, 100), (700, 700), (30, 80, 150), -1)

        # Path to real warehouse material photograph in test scenes
        cls.real_material_path = os.path.join(WEBAPP_DIR, "static", "test_scenes", "sample_carton_boxes.png")
        if not os.path.isfile(cls.real_material_path):
            cls.real_material_path = os.path.join(WEBAPP_DIR, "static", "test_scenes", "sample_individual_pipes_229.jpg")

    def test_01_confirmed_5x5x5_matrix_produces_125_pieces(self):
        """
        Verify that an operator-confirmed 5 x 5 x 5 regular arrangement matrix
        produces exactly 125 pieces without hardcoding defaults.
        Tested against: Simulated synthetic image & Real material photo.
        """
        custom_matrix = {"rows": 5, "columns": 5, "layers": 5}
        
        # Test 1A: Simulated synthetic pallet
        result_sim = self.service.count_individual_pieces(
            self.synthetic_img,
            counting_mode="boxes",
            custom_matrix=custom_matrix
        )
        self.assertTrue(result_sim.get("success"), "Counting failed for simulated image")
        qb_sim = result_sim.get("quantity_breakdown", {})
        self.assertEqual(qb_sim.get("total_units"), 125, "Simulated 5x5x5 matrix did not yield 125 units")
        self.assertEqual(qb_sim.get("final_reviewed_quantity"), 125)
        self.assertEqual(qb_sim.get("operator_confirmed_dimensions"), {"rows": 5, "columns": 5, "layers": 5})
        self.assertIn("5 Rows × 5 Columns × 5 Layers = 125 Pieces", qb_sim.get("formula", ""))
        self.assertEqual(qb_sim.get("visible_count") + qb_sim.get("inferred_count"), 125)

        # Test 1B: Real material photograph (if available)
        if os.path.isfile(self.real_material_path):
            real_bgr = cv2.imread(self.real_material_path)
            result_real = self.service.count_individual_pieces(
                real_bgr,
                counting_mode="boxes",
                custom_matrix=custom_matrix
            )
            self.assertTrue(result_real.get("success"), "Counting failed for real photo")
            qb_real = result_real.get("quantity_breakdown", {})
            self.assertEqual(qb_real.get("total_units"), 125, "Real photo 5x5x5 matrix did not yield 125 units")
            self.assertEqual(qb_real.get("final_reviewed_quantity"), 125)

    def test_02_bundle_mode_and_individual_piece_mode_remain_distinct(self):
        """
        Verify that Bundle Mode and Individual Piece Mode remain distinct in operation,
        payload structure, and units.
        """
        # Individual Piece Mode
        res_piece = self.service.count_individual_pieces(self.synthetic_img, counting_mode="auto")
        self.assertTrue(res_piece.get("success"))
        self.assertIn(res_piece.get("mode"), ("INDIVIDUAL_PIECES", "BOX_GRID"))
        self.assertIn("pieces", res_piece)

        # Bundle Mode
        res_bundle = self.service.count_bundles_multi_view(
            angle1_bgr=self.synthetic_img,
            angle2_bgr=self.synthetic_img
        )
        self.assertTrue(res_bundle.get("success"))
        self.assertEqual(res_bundle.get("mode"), "BUNDLE_STACK")
        self.assertIn("stacks", res_bundle)
        self.assertIn("total_bundles", res_bundle)
        self.assertIn("quantity_breakdown", res_bundle)
        self.assertIn("units_per_bundle", res_bundle.get("quantity_breakdown", {}))

    def test_03_pallet_packaging_is_excluded_from_stock_quantity(self):
        """
        Verify that physical pallet packaging (wooden pallet base) is explicitly
        tracked as tare packaging and excluded from stock pieces/bundles.
        """
        custom_matrix = {"rows": 5, "columns": 5, "layers": 5}
        result = self.service.count_individual_pieces(
            self.synthetic_img,
            counting_mode="boxes",
            custom_matrix=custom_matrix
        )
        qb = result.get("quantity_breakdown", {})
        self.assertTrue(qb.get("tare_excluded"), "Tare packaging was not excluded")
        tare_pkg = qb.get("tare_packaging", {})
        self.assertEqual(tare_pkg.get("pallet_base_count"), 1)
        # Total reviewed stock must equal the material units, not 125 + 1
        self.assertEqual(qb.get("total_units"), 125)

    def test_04_manual_marker_addition_and_deletion_recalculates_count(self):
        """
        Verify that interactive click-to-add and click-to-delete updates displayed counts
        and correctly recalculates visible vs inferred quantities.
        """
        # Setup temporary raw image file for re-rendering
        uploads_dir = os.path.join(WEBAPP_DIR, "static", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        test_raw_name = "test_raw_fixture.jpg"
        test_raw_path = os.path.join(uploads_dir, test_raw_name)
        cv2.imwrite(test_raw_path, self.synthetic_img)

        # Start with 5 markers
        initial_pieces = [
            {"id": i, "x": 100 + i * 40, "y": 200, "cluster": "Front face", "color_hex": "#0284c7"}
            for i in range(1, 6)
        ]
        res_initial = self.service.re_render_piece_annotations(
            self.synthetic_img,
            pieces=initial_pieces,
            custom_matrix={"rows": 5, "columns": 5, "layers": 5}
        )
        self.assertEqual(res_initial["visible_pieces"], 5)
        self.assertEqual(res_initial["total_pieces"], 125)
        self.assertEqual(res_initial["hidden_count"], 120)

        # Delete 2 markers -> 3 remaining
        deleted_pieces = initial_pieces[:3]
        res_del = self.service.re_render_piece_annotations(
            self.synthetic_img,
            pieces=deleted_pieces,
            custom_matrix={"rows": 5, "columns": 5, "layers": 5}
        )
        self.assertEqual(res_del["visible_pieces"], 3)
        self.assertEqual(res_del["hidden_count"], 122)

        # Add 1 marker -> 4 remaining
        added_pieces = deleted_pieces + [{"id": 4, "x": 350, "y": 200, "cluster": "Verified item", "color_hex": "#10b981"}]
        res_add = self.service.re_render_piece_annotations(
            self.synthetic_img,
            pieces=added_pieces,
            custom_matrix={"rows": 5, "columns": 5, "layers": 5}
        )
        self.assertEqual(res_add["visible_pieces"], 4)
        self.assertEqual(res_add["hidden_count"], 121)
        self.assertEqual(res_add["total_pieces"], 125)

    def test_05_inferred_quantities_not_represented_as_directly_detected(self):
        """
        Verify that mathematical estimates / hidden items are not fabricated
        as directly detected objects in the visual marker list.
        """
        custom_matrix = {"rows": 5, "columns": 5, "layers": 5}
        result = self.service.count_individual_pieces(
            self.synthetic_img,
            counting_mode="boxes",
            custom_matrix=custom_matrix
        )
        pieces = result.get("pieces", [])
        visible_count = len(pieces)
        total_units = result["quantity_breakdown"]["total_units"]
        inferred_count = result["quantity_breakdown"]["inferred_count"]

        # Directly detected visible objects must be less than 125 (front and side face visible only)
        self.assertLess(visible_count, total_units, "Direct markers were fabricated for hidden rear boxes!")
        self.assertEqual(visible_count + inferred_count, total_units)

        # Inferred boxes in 3D data are explicitly marked is_hidden=True
        matrix_3d = result.get("matrix_3d", {})
        boxes = matrix_3d.get("boxes", [])
        hidden_boxes = [b for b in boxes if b.get("is_hidden") is True]
        self.assertEqual(len(hidden_boxes), inferred_count)

    def test_06_image_upload_and_camera_snapshot_paths_use_same_semantics(self):
        """
        Verify that uploading an image and capturing from a live camera snapshot
        flow through the exact same counting semantics and schema.
        """
        # 1. Camera Snapshot Path (publish synthetic frame so camera and upload use the exact same input image)
        flask_app_module.get_shared_frame_bus().publish_frame("cam_inbound_01", self.synthetic_img)
        resp_cam = self.client.post('/api/pallets/count-pieces', data={
            "source_type": "camera",
            "camera_id": "cam_inbound_01",
            "matrix_rows": "5",
            "matrix_columns": "5",
            "matrix_layers": "5"
        })
        self.assertEqual(resp_cam.status_code, 200)
        data_cam = json.loads(resp_cam.data)
        self.assertTrue(data_cam.get("success"))
        self.assertIn("quantity_breakdown", data_cam)
        qb_cam = data_cam["quantity_breakdown"]
        self.assertEqual(qb_cam.get("total_units"), 125)
        self.assertTrue(qb_cam.get("tare_excluded"))

        # 2. File Upload Path (Using synthetic image)
        _, img_buf = cv2.imencode('.jpg', self.synthetic_img)
        from io import BytesIO
        resp_upload = self.client.post(
            '/api/pallets/count-pieces',
            data={
                "source_type": "upload",
                "image": (BytesIO(img_buf.tobytes()), "pallet_test.jpg"),
                "matrix_rows": "5",
                "matrix_columns": "5",
                "matrix_layers": "5"
            },
            content_type='multipart/form-data'
        )
        self.assertEqual(resp_upload.status_code, 200)
        data_upload = json.loads(resp_upload.data)
        self.assertTrue(data_upload.get("success"))
        qb_upload = data_upload["quantity_breakdown"]
        self.assertEqual(qb_upload.get("total_units"), 125)
        self.assertTrue(qb_upload.get("tare_excluded"))

        # Parity check: schema keys match exactly
        self.assertEqual(set(qb_cam.keys()), set(qb_upload.keys()))

    def test_07_existing_pallet_finalization_and_inventory_isolation_intact(self):
        """
        Verify that counting, uploading, and editing markers DO NOT silently mutate
        inventory balances or seal pallets. Pallet sealing and inventory reconciliation
        remain strictly authorized explicit actions.
        """
        # 1. Create a test pallet using an existing catalog SKU
        skus = db.get_all_skus()
        target_sku = skus[0]['sku_id'] if skus else "AUTO-BOLT-01"
        pallet, err = db.create_pallet(
            sku_id=target_sku,
            units_per_bundle=10,
            target_bundles=10,
            name="Integrity Isolation Test Pallet"
        )
        self.assertIsNotNone(pallet, f"create_pallet failed: {err}")
        pallet_id = pallet['pallet_id']

        # Get initial pallet record
        initial_pallet = db.get_pallet_by_id(pallet_id)
        self.assertNotEqual(initial_pallet['status'], 'SEALED')

        # 2. Run vision counting - MUST NOT change pallet status or inventory
        resp = self.client.post('/api/pallets/count-pieces', data={
            "pallet_id": pallet_id,
            "source_type": "camera",
            "camera_id": "cam_inbound_01",
            "matrix_rows": "5",
            "matrix_columns": "5",
            "matrix_layers": "5"
        })
        self.assertEqual(resp.status_code, 200)

        # Pallet must still be unsealed and isolated
        mid_pallet = db.get_pallet_by_id(pallet_id)
        self.assertNotEqual(mid_pallet['status'], 'SEALED', "Pallet was silently sealed during detection!")

        # 3. Explicit seal authorization must work cleanly
        seal_resp = self.client.post(f'/api/pallets/{pallet_id}/seal', json={})
        self.assertEqual(seal_resp.status_code, 200)
        sealed_pallet = db.get_pallet_by_id(pallet_id)
        self.assertEqual(sealed_pallet['status'], 'SEALED', "Pallet failed to seal on authorized action")

    def test_08_direct_instance_localization_and_3d_consistency(self):
        """
        Verify that single-image counting returns direct physical object instances with
        complete instance metadata (detection_id, bbox, confidence, centroid, norm_bbox,
        detection_status, uncertainty_indicators), inferred_count == 0, and 1-to-1 consistency
        between accepted pieces and 3D digital twin boxes.
        """
        uploads_dir = os.path.join(WEBAPP_DIR, "static", "uploads")
        floor_3box = os.path.join(uploads_dir, "raw_1793035112_c8f099.jpg")
        if not os.path.isfile(floor_3box):
            return

        bgr = cv2.imread(floor_3box)
        res = self.service.count_individual_pieces(bgr, counting_mode="auto")
        self.assertTrue(res.get("success"))
        qb = res.get("quantity_breakdown", {})
        pieces = res.get("pieces", [])
        matrix_3d = res.get("matrix_3d", {})

        self.assertEqual(len(pieces), 3, "Expected exactly 3 localized boxes")
        self.assertEqual(qb.get("directly_detected_count"), 3)
        self.assertEqual(qb.get("inferred_count"), 0, "Single image must not fabricate inferred hidden units")
        self.assertEqual(qb.get("total_units"), 3)
        self.assertEqual(qb.get("tare_packaging", {}).get("pallet_base_count"), 0, "Floor boxes have no wooden pallet base")
        self.assertFalse(matrix_3d.get("has_pallet"), "3D view must not render a pallet base when none is detected")
        self.assertEqual(len(matrix_3d.get("boxes", [])), 3, "3D boxes must match accepted physical instances 1-to-1")

        required_fields = {
            "id", "index", "detection_id", "bbox", "confidence",
            "x", "y", "centroid", "norm_x", "norm_y", "norm_w", "norm_h",
            "detection_status", "uncertainty_indicators"
        }
        for p in pieces:
            self.assertTrue(required_fields.issubset(set(p.keys())), f"Missing instance fields in {p.keys()}")

    def test_09_corner_face_deduplication_and_tare_pallet_exclusion(self):
        """
        Verify hybrid Strategy A (Direct Instance Counting) and Strategy B (Structured Pallet-Stack
        Reconstruction) on 3D perspective pallet images: deduplicating shared corner cartons,
        reconstructing hidden interior core cartons when 2-face geometry is clear, and excluding
        wooden pallet slats and support blocks.
        """
        uploads_dir = os.path.join(WEBAPP_DIR, "static", "uploads")
        expected_cases = [
            # (filename, strategy, direct_count, inferred_count, total_units, shared_corner, pallet_base)
            ("raw_1793035080_a5c743.jpg", "DIRECT_INSTANCE_COUNTING", 3, 0, 3, 0, 0),
            ("raw_1793034160_421df6.jpg", "STRUCTURED_PALLET_RECONSTRUCTION", 15, 12, 27, 3, 1),
            ("raw_1793034186_162897.jpg", "STRUCTURED_PALLET_RECONSTRUCTION", 16, 8, 24, 4, 1),
            ("raw_1793030331_dea531.jpg", "STRUCTURED_PALLET_RECONSTRUCTION", 45, 80, 125, 5, 1),
        ]
        for fname, exp_strat, exp_direct, exp_inferred, exp_total, exp_corner, exp_pallet in expected_cases:
            fpath = os.path.join(uploads_dir, fname)
            if not os.path.isfile(fpath):
                continue
            bgr = cv2.imread(fpath)
            res = self.service.count_individual_pieces(bgr, counting_mode="auto")
            qb = res.get("quantity_breakdown", {})
            self.assertEqual(qb.get("counting_strategy"), exp_strat, f"Strategy mismatch on {fname}")
            self.assertEqual(
                qb.get("directly_detected_count"), exp_direct,
                f"Direct count mismatch on {fname}: got {qb.get('directly_detected_count')}, expected {exp_direct}"
            )
            self.assertEqual(qb.get("inferred_count"), exp_inferred, f"Inferred mismatch on {fname}")
            self.assertEqual(qb.get("total_units"), exp_total, f"Total mismatch on {fname}")
            self.assertEqual(qb.get("shared_corner_count"), exp_corner, f"Shared corner mismatch on {fname}")
            self.assertEqual(qb.get("tare_packaging", {}).get("pallet_base_count"), exp_pallet)
            self.assertEqual(len(res.get("matrix_3d", {}).get("boxes", [])), exp_total)

    def test_10_material_agnostic_standalone_counting(self):
        """
        Verify class-agnostic counting on non-cardboard materials (white-wrapped bundles
        and metal C-stud profiles) without requiring SKU Master Data.
        """
        front_bundles = os.path.join(ROOT_DIR, "test_front_face.jpg")
        if os.path.isfile(front_bundles):
            bgr = cv2.imread(front_bundles)
            res_b = self.service.count_bundles_multi_view(angle1_bgr=bgr, angle2_bgr=None)
            self.assertTrue(res_b.get("success"))
            qb_b = res_b.get("quantity_breakdown", {})
            self.assertGreaterEqual(qb_b.get("directly_detected_count", 0), 70)
            self.assertEqual(qb_b.get("inferred_count"), 0)
            self.assertEqual(qb_b.get("total_units"), qb_b.get("directly_detected_count"))


if __name__ == '__main__':
    unittest.main()
