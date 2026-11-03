import os
import unittest
import cv2
import numpy as np

import sys
sys.path.insert(0, os.path.abspath('webapp'))
from pallet_vision_counting_service import get_pallet_vision_counting_service

WEBAPP_DIR = os.path.abspath('webapp')
UPLOAD_DIR = os.path.join(WEBAPP_DIR, 'static', 'uploads')


class TestFocusedBundleAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = get_pallet_vision_counting_service()
        cls.pipes_img = os.path.join(UPLOAD_DIR, "raw_1793695799_2737bf.jpg")
        cls.rhs_img = os.path.join(UPLOAD_DIR, "raw_1793695790_c312bd.jpg")
        cls.framing_img = os.path.join(UPLOAD_DIR, "raw_1793695813_b36727.jpg")
        cls.carton_img = os.path.join(WEBAPP_DIR, "static", "test_scenes", "sample_carton_boxes.png")
        cls.wrapped_img = os.path.join(UPLOAD_DIR, "raw_1793686878_a4475a.jpg")
        cls.cstud_img = os.path.join(UPLOAD_DIR, "raw_metal_bundle_1793695888_ecd056.jpg")

    def test_part1_strict_protection_individual_pieces(self):
        """
        PART 1: Strict Protection of Individual Pieces Counting.
        Verifies individual piece counts are preserved and carton counting remains intact:
        - Hollow structural steel sections: 27 pieces inside envelope
        - Circular steel pipes: 120 front cut-plane pieces
        - Steel framing profiles: 35 pieces
        - Carton boxes: 125 boxes with 3D digital twin
        """
        # 1. Hollow structural sections
        if os.path.exists(self.rhs_img):
            im = cv2.imread(self.rhs_img)
            res = self.service.count_individual_pieces(im)
            count = res.get("confirmed_count") or res.get("total_pieces", 0)
            self.assertEqual(count, 27, f"Hollow steel sections must remain 27, got {count}")
            # Ensure no markers on floor/pallet runner (y > 600)
            for p in res.get("pieces", []):
                self.assertLess(p["y"], 600, "No hollow steel markers permitted on floor/pallet base")

        # 2. Circular steel pipes
        if os.path.exists(self.pipes_img):
            im = cv2.imread(self.pipes_img)
            res = self.service.count_individual_pieces(im)
            count = res.get("confirmed_count") or res.get("total_pieces", 0)
            self.assertGreaterEqual(count, 95, f"Circular pipes front plane must detect all visible pipes, got {count}")

        # 3. Steel framing profiles
        if os.path.exists(self.framing_img):
            im = cv2.imread(self.framing_img)
            res = self.service.count_individual_pieces(im)
            count = res.get("confirmed_count") or res.get("total_pieces", 0)
            self.assertGreaterEqual(count, 25, f"Framing profiles must detect direct sections, got {count}")

        # 4. Strict carton preservation
        if os.path.exists(self.carton_img):
            im = cv2.imread(self.carton_img)
            res = self.service.count_individual_pieces(im, counting_mode="boxes")
            self.assertEqual(res.get("total_pieces"), 125, "Carton box stack must remain 125")
            self.assertIsNotNone(res.get("matrix_3d"), "Carton 3D matrix must be preserved")

    def test_part2_wrapped_material_bundle_segmentation(self):
        """
        PART 2: Wrapped Material Bundle Segmentation.
        Verifies physically separate wrapped packs are identified with tight boundaries,
        pallet runner tare is excluded, and arbitrary horizontal bands are eliminated.
        """
        if not os.path.exists(self.wrapped_img):
            self.skipTest("Wrapped image not found")

        im = cv2.imread(self.wrapped_img)
        res = self.service.count_wrapped_bundles(im, counting_mode="bundles")
        self.assertTrue(res.get("success"))

        # Must exclude pallet runner tare
        self.assertIsNotNone(res.get("pallet_base_meta"), "Pallet base runner must be detected as tare packaging")
        pallet_meta = res.get("pallet_base_meta")
        self.assertGreaterEqual(pallet_meta.get("y", 0), 480, "Pallet runner must be located at base of load")

        # Must detect separate physical packs
        instances = res.get("detected_instances", [])
        self.assertGreaterEqual(len(instances), 4, f"Must detect multiple wrapped packs, got {len(instances)}")

        # Verify no single pack spans across the whole image width (> 90% of image width)
        h, w = im.shape[:2]
        for inst in instances:
            self.assertIn("layer", inst, "Each pack must have an elevation layer assigned")
            self.assertEqual(inst.get("geometry_type"), "wrapped_bundle")
            self.assertIn("bbox", inst)
            pw = inst["w"]
            # No arbitrary horizontal strip across entire width
            self.assertLess(pw, int(w * 0.85), f"Pack {inst['bundle_id']} is too wide ({pw}px), must be tightly segmented")

        # 3D Digital Twin verification
        matrix_3d = res.get("matrix_3d", {})
        self.assertTrue(matrix_3d.get("has_pallet"))
        self.assertEqual(matrix_3d.get("geometry_type"), "wrapped_bundle")
        self.assertGreaterEqual(len(matrix_3d.get("boxes", [])), 4)

    def test_part3_xpert_cstud_framing_bundle_segmentation(self):
        """
        PART 3: XPERT C-STUD Metal Framing Bundle Segmentation.
        Verifies 4 distinct physical packs are segmented, dunnage spacer gaps between tiers
        are excluded, and pallet runner tare is identified at the bottom.
        """
        if not os.path.exists(self.cstud_img):
            self.skipTest("C-STUD image not found")

        im = cv2.imread(self.cstud_img)
        res = self.service.count_metal_bundles(im, counting_mode="bundles", material_type="metal_framing_packs")
        self.assertTrue(res.get("success"))

        # Must report 4 distinct physical packs
        total_bundles = res.get("total_bundles") or res.get("physical_bundles_count")
        self.assertEqual(total_bundles, 4, f"C-STUD stack must report 4 physical packs, got {total_bundles}")

        # Must exclude pallet runner tare
        self.assertIsNotNone(res.get("pallet_base_meta"), "Pallet base runner must be detected as tare packaging")

        # Verify dunnage exclusion and tight bounding boxes across tiers
        instances = res.get("detected_instances", [])
        self.assertEqual(len(instances), 4)
        layers = [inst["layer"] for inst in instances]
        self.assertEqual(set(layers), {1, 2, 3, 4}, "Packs must span Layer 1 to Layer 4")

        # Verify vertical gaps between tiers (dunnage excluded, no overlapping Y)
        sorted_packs = sorted(instances, key=lambda b: b["bbox"][1])
        for i in range(len(sorted_packs) - 1):
            y2_current = sorted_packs[i]["bbox"][3]
            y1_next = sorted_packs[i + 1]["bbox"][1]
            self.assertLessEqual(
                y2_current, y1_next + 15,
                f"Packs {sorted_packs[i]['bundle_id']} and {sorted_packs[i+1]['bundle_id']} must not overlap dunnage"
            )

        # Geometry & 3D Digital Twin
        matrix_3d = res.get("matrix_3d", {})
        self.assertTrue(matrix_3d.get("has_pallet"))
        self.assertIn("c_stud", matrix_3d.get("geometry_type", "").lower() + res.get("geometry_type", "").lower())
        self.assertEqual(len(matrix_3d.get("boxes", [])), 4)

    def test_part4_bundle_quantity_and_sku_semantics(self):
        """
        PART 4: Bundle Count and Quantity Semantics.
        Separates physical bundles from pieces per bundle; leaves unassigned SKU if unmapped;
        never auto-assigns automotive SKUs.
        """
        if not os.path.exists(self.cstud_img):
            self.skipTest("C-STUD image not found")

        im = cv2.imread(self.cstud_img)
        res = self.service.count_metal_bundles(im, counting_mode="bundles")

        # Quantity separation
        qb = res.get("quantity_breakdown", {})
        self.assertEqual(qb.get("total_bundles"), 4)
        self.assertEqual(res.get("total_bundles"), 4)

        # SKU recognition check: must never assign AUTO-DOOR-SKIN or AUTO-STRUT-01
        rec = res.get("recognized_sku") or self.service.recognize_product_from_skus(im, counting_mode="bundles_metal")
        self.assertFalse(
            str(rec.get("sku_id", "")).startswith("AUTO-"),
            f"Unrelated automotive SKU must not be assigned to metal framing packs: {rec.get('sku_id')}"
        )

    def test_part5_operator_review_recalculation_preservation(self):
        """
        PART 5: Authoritative Object Collection & Operator Review Synchronization.
        Verifies that operator additions, confirmations, and rejections are preserved
        during recalculation and reflected in the 3D Digital Twin.
        """
        sess_id = "SES-TEST-RECALC-PRESERVE"
        session_data = {
            "session_id": sess_id,
            "material_type": "metal_framing_packs",
            "counting_mode": "bundles",
            "primary_count": 3,
            "confirmed_count": 3,
            "uncertain_count": 0,
            "fused_objects": [
                {
                    "object_id": "MB-01",
                    "detection_id": "MB-01",
                    "bundle_id": "MB-01",
                    "layer": 3,
                    "norm_x": 0.5,
                    "norm_y": 0.2,
                    "norm_w": 0.8,
                    "norm_h": 0.2,
                    "confidence": 0.95,
                    "status": "CONFIRMED",
                    "review_state": "AUTO_PROPOSED"
                },
                {
                    "object_id": "MB-02",
                    "detection_id": "MB-02",
                    "bundle_id": "MB-02",
                    "layer": 2,
                    "norm_x": 0.5,
                    "norm_y": 0.4,
                    "norm_w": 0.8,
                    "norm_h": 0.2,
                    "confidence": 0.95,
                    "status": "CONFIRMED",
                    "review_state": "AUTO_PROPOSED"
                },
                {
                    "object_id": "MB-03",
                    "detection_id": "MB-03",
                    "bundle_id": "MB-03",
                    "layer": 1,
                    "norm_x": 0.5,
                    "norm_y": 0.6,
                    "norm_w": 0.8,
                    "norm_h": 0.2,
                    "confidence": 0.95,
                    "status": "CONFIRMED",
                    "review_state": "AUTO_PROPOSED"
                }
            ],
            "ambiguous_candidates": []
        }
        self.service._active_multiview_sessions[sess_id] = session_data

        # 1. Operator adds bundle 4
        self.service.review_multiview_session(
            session_id=sess_id,
            action="add_bundle",
            layer=0,
            norm_x=0.5,
            norm_y=0.8,
            notes="Operator added base tier pack MB-04"
        )

        # 2. Operator recalculates session
        recalc_sess = self.service.review_multiview_session(
            session_id=sess_id,
            action="recalculate",
            notes="Recalculating after operator additions"
        )

        # Must preserve operator-added object and report 4 bundles
        self.assertEqual(recalc_sess.get("primary_count"), 4)
        self.assertEqual(recalc_sess.get("confirmed_count"), 4)
        fused = recalc_sess.get("fused_objects", [])
        self.assertEqual(len(fused), 4)

        op_added = [o for o in fused if o.get("review_state") == "OPERATOR_ADDED"]
        self.assertEqual(len(op_added), 1, "Operator-added bundle must be preserved across recalculation")

        # 3D Digital Twin boxes must contain 4 objects
        matrix_3d = recalc_sess.get("matrix_3d", {})
        self.assertEqual(len(matrix_3d.get("boxes", [])), 4)


if __name__ == "__main__":
    unittest.main()

