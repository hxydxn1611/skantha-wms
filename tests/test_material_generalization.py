import os
import unittest
import cv2
import numpy as np

from webapp.pallet_vision_counting_service import PalletVisionCountingService


class TestMaterialGeneralization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = PalletVisionCountingService()
        cls.timber_front_path = os.path.join("webapp", "static", "test_scenes", "sample_timber_angle1_front.jpg")
        cls.timber_side_path = os.path.join("webapp", "static", "test_scenes", "sample_timber_angle2_side.jpg")
        cls.pipes_229_path = os.path.join("webapp", "static", "test_scenes", "sample_individual_pipes_229.jpg")
        cls.pipes_hires_path = os.path.join("webapp", "static", "uploads", "raw_1793259476_ea7877.jpg")

    def test_timber_bundle_detection(self):
        """Timber bundle detection identifies physical bundles, dunnage tiers, and tare pallet base."""
        if not os.path.exists(self.timber_front_path):
            self.skipTest("Timber test scene not found")
        img = cv2.imread(self.timber_front_path)
        self.assertIsNotNone(img)

        bundles, pallet_base, meta = self.service._detect_physical_timber_bundles(img)
        self.assertGreaterEqual(len(bundles), 4, "Should detect multiple physical bundles")
        self.assertLessEqual(len(bundles), 20, "Should not count individual constituent planks as bundles")
        self.assertIsNotNone(pallet_base, "Bottom pallet runner should be localized as tare packaging")
        self.assertIn("type", pallet_base)
        self.assertIn("bbox", pallet_base)
        self.assertTrue(meta.get("pallet_base_detected"))
        self.assertGreaterEqual(meta.get("tiers_count", 0), 2)

    def test_bundle_counting_mode_routing_and_no_piece_multiplication(self):
        """Bundles mode preserves physical bundle count as primary inventory count without piece multiplication."""
        if not os.path.exists(self.timber_front_path):
            self.skipTest("Timber test scene not found")
        img = cv2.imread(self.timber_front_path)

        res = self.service.count_individual_pieces(
            img,
            counting_mode="bundles",
            material_type="timber",
            manual_units_per_bundle=50,
            manual_uom="BD"
        )
        self.assertTrue(res.get("success"))
        self.assertIn("total_bundles", res)
        self.assertIn("physical_bundles_count", res)
        # Primary bundle count is the number of physical bundles (10), NOT 10 * 50
        self.assertEqual(res["total_bundles"], res["confirmed_count"])
        self.assertEqual(res["physical_bundles_count"], res["confirmed_count"])
        self.assertEqual(res["inferred_material"], "timber_bundles")
        # Derived individual units total is preserved separately
        self.assertEqual(res["individual_units_total"], res["confirmed_count"] * 50)
        self.assertFalse(res["is_estimate"])

    def test_multi_view_fusion_bundles_strategy(self):
        """Multi-view fusion handles 'bundles' strategy cleanly across multiple angles."""
        if not os.path.exists(self.timber_front_path) or not os.path.exists(self.timber_side_path):
            self.skipTest("Timber angle views not found")
        img_front = cv2.imread(self.timber_front_path)
        img_side = cv2.imread(self.timber_side_path)

        res = self.service.fuse_multi_view_counting(
            views=[
                {"view_label": "front", "image_bgr": img_front},
                {"view_label": "side", "image_bgr": img_side}
            ],
            counting_mode="bundles",
            material_type="timber"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("primary_count"), 10)
        self.assertEqual(res.get("confirmed_count"), 10)
        self.assertEqual(res.get("physical_bundles_count"), 10)
        self.assertEqual(res.get("inferred_material"), "timber_bundles")
        self.assertEqual(res.get("counting_method"), "MULTI_VIEW_CROSS_VIEW_FUSION")
        self.assertIn("quantity_breakdown", res)
        qb = res["quantity_breakdown"]
        self.assertEqual(qb.get("confirmed_count"), 10)
        self.assertIn("tare_packaging", qb)

    def test_steel_section_count_consistency_and_envelope(self):
        """Steel profile counting reliably extracts markers and respects envelope without floor artifacts."""
        if not os.path.exists(self.pipes_229_path):
            self.skipTest("229 pipes test scene not found")
        img = cv2.imread(self.pipes_229_path)
        res = self.service.count_individual_pieces(img, counting_mode="individual_pieces")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("total_pieces"), 229, "Reference 229 scene should resolve 229 markers")

        if os.path.exists(self.pipes_hires_path):
            img_hires = cv2.imread(self.pipes_hires_path)
            res_hires = self.service.count_individual_pieces(img_hires, counting_mode="individual_pieces")
            self.assertTrue(res_hires.get("success"))
            self.assertGreaterEqual(res_hires.get("total_pieces", 0), 225)
            self.assertLessEqual(res_hires.get("total_pieces", 0), 235)

    def test_standardized_transparency_fields_across_modes(self):
        """All material modes return standardized result transparency fields."""
        if not os.path.exists(self.timber_front_path):
            self.skipTest("Timber test scene not found")
        img = cv2.imread(self.timber_front_path)

        res = self.service.count_bundles_multi_view(img, counting_mode="bundles", material_type="timber")
        required_fields = [
            "confirmed_count",
            "uncertain_count",
            "is_estimate",
            "material_type",
            "selected_sku",
            "inferred_material",
            "counting_method",
            "confidence",
            "confidence_nature",
            "operator_guidance",
            "views_needed",
            "views_submitted",
            "review_status"
        ]
        for field in required_fields:
            self.assertIn(field, res, f"Field '{field}' must be present in result payload")
            if field != "selected_sku":
                self.assertIsNotNone(res[field], f"Field '{field}' should not be None")

        qb = res.get("quantity_breakdown", {})
        for qb_field in ["confirmed_count", "uncertain_count", "is_estimate", "views_needed", "views_submitted", "review_status"]:
            self.assertIn(qb_field, qb, f"Field '{qb_field}' must be present in quantity_breakdown")


if __name__ == "__main__":
    unittest.main()
