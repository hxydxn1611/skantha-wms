import os
import sys
import unittest
import cv2
import numpy as np

# Ensure webapp directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from webapp.pallet_vision_counting_service import get_pallet_vision_counting_service


class TestPriorityVisionCorrection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = get_pallet_vision_counting_service()
        cls.img_rhs_path = os.path.join(WEBAPP_DIR, "static", "uploads", "raw_1793695790_c312bd.jpg")
        cls.img_pipe_path = os.path.join(WEBAPP_DIR, "static", "uploads", "raw_1793695799_2737bf.jpg")
        cls.img_framing_path = os.path.join(WEBAPP_DIR, "static", "uploads", "raw_1793695813_b36727.jpg")
        cls.img_pack_path = os.path.join(WEBAPP_DIR, "static", "uploads", "raw_metal_bundle_1793695888_ecd056.jpg")

    def test_01_hollow_steel_sections_envelope_and_sku(self):
        """Image 1: Structural steel sections strictly inside envelope with 0 rafter/floor markers."""
        if not os.path.exists(self.img_rhs_path):
            self.skipTest("RHS image not found")
        im = cv2.imread(self.img_rhs_path)
        self.assertIsNotNone(im)

        # SKU recognition check: must NEVER assign AUTO-DOOR-SKIN
        rec = self.service.recognize_product_from_skus(im, counting_mode="individual_pieces")
        self.assertNotEqual(rec.get("sku_id"), "AUTO-DOOR-SKIN")
        self.assertIn("STEEL", str(rec.get("sku_id", "")))

        # Explicit SKU mismatch check
        rec_mismatch = self.service.recognize_product_from_skus(
            im, explicit_sku_id="AUTO-DOOR-SKIN", counting_mode="individual_pieces"
        )
        self.assertEqual(rec_mismatch.get("sku_id"), "AUTO-DOOR-SKIN")
        self.assertTrue(rec_mismatch.get("is_mismatch"))
        self.assertTrue(rec_mismatch.get("requires_operator_confirmation"))
        self.assertLessEqual(rec_mismatch.get("confidence", 1.0), 0.35)

        # Counting and envelope verification
        res = self.service.count_individual_pieces(im)
        count = res.get("confirmed_count") or res.get("total_pieces")
        self.assertGreaterEqual(count, 18)
        self.assertLessEqual(count, 35)

        pieces = res.get("pieces", [])
        self.assertGreater(len(pieces), 0)
        # All markers must be strictly in the physical stack region (Y between 150 and 650)
        for p in pieces:
            self.assertGreaterEqual(p["y"], 150, f"Ceiling/rafter false detection at Y={p['y']}")
            self.assertLessEqual(p["y"], 650, f"Floor false detection at Y={p['y']}")

    def test_02_circular_pipes_localization_and_not_glass(self):
        """Image 2: Circular steel pipes identified without false glass routing or synthetic grids."""
        if not os.path.exists(self.img_pipe_path):
            self.skipTest("Pipe image not found")
        im = cv2.imread(self.img_pipe_path)
        self.assertIsNotNone(im)

        # Must not be falsely classified as glass
        is_glass = self.service._is_glass_sheet_scene(im)
        self.assertFalse(is_glass, "Circular pipes on grey floor was misclassified as glass sheets")

        # Must not match automotive SKUs
        rec = self.service.recognize_product_from_skus(im, counting_mode="individual_pieces")
        self.assertFalse(str(rec.get("sku_id", "")).startswith("AUTO-"))

        # Counting: 100+ circular pipes
        res = self.service.count_individual_pieces(im)
        count = res.get("confirmed_count") or res.get("total_pieces")
        self.assertGreaterEqual(count, 80)
        pieces = res.get("pieces", [])
        self.assertGreaterEqual(len(pieces), 80)

        # Verify markers have diverse X coordinates (not a single artificial vertical column)
        xs = [p["x"] for p in pieces]
        x_spread = max(xs) - min(xs)
        self.assertGreater(x_spread, 600, "Markers must be distributed across the full physical stack")

    def test_03_framing_profiles_cross_sections(self):
        """Image 3: Framing profiles (C-studs) detected with 0 automotive SKU assignments."""
        if not os.path.exists(self.img_framing_path):
            self.skipTest("Framing image not found")
        im = cv2.imread(self.img_framing_path)
        self.assertIsNotNone(im)

        rec = self.service.recognize_product_from_skus(im, counting_mode="individual_pieces")
        self.assertNotEqual(rec.get("sku_id"), "AUTO-DOOR-SKIN")

        res = self.service.count_individual_pieces(im)
        count = res.get("confirmed_count") or res.get("total_pieces")
        self.assertGreaterEqual(count, 15)

    def test_04_metal_framing_bundle_packs_and_tare_exclusion(self):
        """Image 4: Metal framing strapped packs segmented across tiers with pallet tare excluded."""
        if not os.path.exists(self.img_pack_path):
            self.skipTest("Metal bundle image not found")
        im = cv2.imread(self.img_pack_path)
        self.assertIsNotNone(im)

        # SKU check: must not match AUTO-STRUT-01 or AUTO-ROD-01
        rec = self.service.recognize_product_from_skus(im, counting_mode="bundles_metal")
        self.assertFalse(str(rec.get("sku_id", "")).startswith("AUTO-"))

        res = self.service.count_metal_bundles(im)
        bundles_count = res.get("total_bundles") or res.get("confirmed_count")
        self.assertGreaterEqual(bundles_count, 3, "Multiple strapped packs must be detected on pallet")

        # Pallet base tare packaging must be detected
        matrix = res.get("matrix_3d", {})
        self.assertTrue(matrix.get("pallet_base_detected") or matrix.get("has_pallet"))

    def test_05_carton_counting_preserved(self):
        """Strict Carton Counting Protection: Verifies carton box detection pipeline is preserved."""
        carton_img = os.path.join(WEBAPP_DIR, "static", "test_scenes", "sample_carton_boxes.png")
        if not os.path.exists(carton_img):
            self.skipTest("Carton image not found")
        im = cv2.imread(carton_img)
        self.assertIsNotNone(im)

        res = self.service.count_individual_pieces(im, counting_mode="boxes")
        total = res.get("total_pieces", 0)
        self.assertEqual(total, 125, f"Expected 125 carton boxes, got {total}")
        matrix_boxes = res.get("matrix_3d", {}).get("boxes", [])
        self.assertEqual(len(matrix_boxes), 125, f"Expected 125 3D digital twin boxes, got {len(matrix_boxes)}")


if __name__ == "__main__":
    unittest.main()
