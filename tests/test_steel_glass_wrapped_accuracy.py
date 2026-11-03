import unittest
import os
import cv2
import numpy as np
from webapp.pallet_vision_counting_service import PalletVisionCountingService

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "webapp", "static", "uploads")


class TestSteelGlassWrappedAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = PalletVisionCountingService()

    def test_01_steel_structural_section_detection(self):
        """Test individual hollow structural section counting on raw_1793686608_4a8aca.jpg."""
        img_path = os.path.join(UPLOAD_DIR, "raw_1793686608_4a8aca.jpg")
        if not os.path.exists(img_path):
            self.skipTest(f"Test image not found at {img_path}")

        img = cv2.imread(img_path)
        self.assertIsNotNone(img)

        result = self.service.count_individual_pieces(
            img,
            material_type="steel_profiles",
            counting_mode="individual_pieces"
        )
        self.assertTrue(result.get("success"), "Steel counting should succeed")
        self.assertEqual(result.get("material_type"), "steel_profiles")

        detected = result.get("detected_instances", [])
        self.assertGreater(len(detected), 20, "Should detect structural steel sections")
        self.assertLess(len(detected), 80, "Should not produce spurious 170+ noisy detections")

        # Verify markers are strictly on the steel stack and not on the pallet runner/floor (Y > 550)
        h, w = img.shape[:2]
        for inst in detected:
            cy = inst["y"] if "y" in inst else inst["center"][1]
            self.assertLess(cy, 600, f"Marker at y={cy} is on wooden pallet runner or floor (must be < 600)")

    def test_02_glass_sheet_detection(self):
        """Test individual glass sheet edge counting on raw_1793686707_d45736.jpg."""
        img_path = os.path.join(UPLOAD_DIR, "raw_1793686707_d45736.jpg")
        if not os.path.exists(img_path):
            self.skipTest(f"Test image not found at {img_path}")

        img = cv2.imread(img_path)
        self.assertIsNotNone(img)

        # Verify scene recognition
        is_glass = self.service._is_glass_sheet_scene(img)
        self.assertTrue(is_glass, "Image should be recognized as a glass sheet scene")

        result = self.service.count_individual_pieces(
            img,
            sku_id="GLS-FLT-04MM",
            material_type="glass_sheets",
            counting_mode="individual_pieces"
        )
        self.assertTrue(result.get("success"), "Glass counting should succeed")
        self.assertEqual(result.get("material_type"), "glass_sheets")

        # Distinct physical edge rims along rim (should be around 3-6 confirmed sheets, not 43 steel pipes)
        detected = result.get("detected_instances", [])
        self.assertGreaterEqual(len(detected), 2, "Should identify visible sheet edge instances")
        self.assertLess(len(detected), 15, "Should not detect internal reflections as dozens of pipes")

    def test_03_steel_pipe_bundles_multi_view(self):
        """Test physical steel pipe bundle grouping on raw_metal_bundle_1793686731_b9ae76.jpg."""
        img_path = os.path.join(UPLOAD_DIR, "raw_metal_bundle_1793686731_b9ae76.jpg")
        if not os.path.exists(img_path):
            self.skipTest(f"Test image not found at {img_path}")

        img = cv2.imread(img_path)
        self.assertIsNotNone(img)

        result = self.service.count_bundles_multi_view(
            angle1_bgr=img,
            material_type="steel_pipe_bundles",
            counting_mode="bundles"
        )
        self.assertTrue(result.get("success"), "Metal bundle counting should succeed")
        self.assertEqual(result.get("geometry_type"), "steel_pipe_bundle")

        detected = result.get("detected_instances", [])
        self.assertGreaterEqual(len(detected), 1, "Should detect at least 1 bundle")
        for inst in detected:
            self.assertIn("layer", inst, "Each bundle must have an elevation tier layer assigned")
            self.assertEqual(inst.get("geometry_type"), "steel_pipe_bundle")

    def test_04_wrapped_pallet_bundles_and_mismatch(self):
        """Test wrapped pallet bundle counting and SKU mismatch handling on raw_1793686878_a4475a.jpg."""
        img_path = os.path.join(UPLOAD_DIR, "raw_1793686878_a4475a.jpg")
        if not os.path.exists(img_path):
            self.skipTest(f"Test image not found at {img_path}")

        img = cv2.imread(img_path)
        self.assertIsNotNone(img)

        # 1. Direct wrapped bundle counting
        result = self.service.count_wrapped_bundles(
            angle1_bgr=img,
            counting_mode="bundles"
        )
        self.assertTrue(result.get("success"), "Wrapped bundle counting should succeed")
        self.assertEqual(result.get("geometry_type"), "wrapped_bundle")
        self.assertIsNotNone(result.get("pallet_base_meta"), "Should detect pallet base runner tare")

        detected = result.get("detected_instances", [])
        self.assertGreaterEqual(len(detected), 4, "Should segment wrapped packs")
        for inst in detected:
            self.assertIn("layer", inst, "Each wrapped pack must have an elevation layer")

        # 2. Strategy resolution with mismatched glass SKU
        strat = self.service.resolve_counting_strategy(
            image_bgr=img,
            counting_mode="bundles",
            sku_id="GLS-FLT-08MM"
        )
        self.assertTrue(strat.get("success"))
        self.assertTrue(strat.get("is_mismatch"), "Should flag mismatch when glass SKU is selected for wrapped pallet")
        self.assertIn("wrapped", strat.get("resolved_strategy"))

    def test_05_carton_counting_preservation(self):
        """Test that carton counting remains completely intact and unaffected."""
        img_path = os.path.join(UPLOAD_DIR, "sample_carton_boxes.png")
        if not os.path.exists(img_path):
            img_path = os.path.join(os.path.dirname(__file__), "..", "webapp", "static", "test_scenes", "sample_carton_boxes.png")
        if not os.path.exists(img_path):
            self.skipTest("sample_carton_boxes.png not found")

        img = cv2.imread(img_path)
        self.assertIsNotNone(img)

        result = self.service.count_bundles_multi_view(
            angle1_bgr=img,
            counting_mode="boxes",
            material_type="carton_boxes"
        )
        self.assertTrue(result.get("success"), "Carton counting must succeed")
        self.assertEqual(result.get("total_pieces", 0), 125, "Carton count must remain 125")
        self.assertEqual(result.get("material_type"), "carton_boxes")
        self.assertIsNotNone(result.get("matrix_3d"), "Carton 3D matrix must be preserved")


if __name__ == "__main__":
    unittest.main()
