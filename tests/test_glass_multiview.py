import os
import unittest
import cv2
import numpy as np

from webapp.pallet_vision_counting_service import PalletVisionCountingService


class TestGlassMultiViewCounting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = PalletVisionCountingService()
        cls.front_glass_path = "webapp/static/uploads/raw_1793262430_ecded0.jpg"
        if not os.path.exists(cls.front_glass_path):
            raise unittest.SkipTest(f"Test image not found: {cls.front_glass_path}")
        cls.front_img = cv2.imread(cls.front_glass_path)
        cls.assertIsNotNone(cls.front_img, "Failed to load front glass test image")

    def test_01_single_front_view_physical_instances(self):
        """Single front view detects confirmed physical rim sheet instances and 1 uncertain compressed stack body."""
        res = self.service.count_individual_pieces(
            self.front_img,
            counting_mode="individual_pieces",
            material_type="glass_sheets",
            view_label="front"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("material_type"), "glass_sheets")
        confirmed_count = res.get("directly_detected_count", 0)
        uncertain_count = res.get("uncertain_count", 0)

        # Confirm 7 physical sheet instances delimited by rim boundary transitions
        self.assertEqual(confirmed_count, 7)
        self.assertEqual(uncertain_count, 1)

        # Confirm each sheet is a physical instance with non-zero thickness
        for p in res.get("pieces", []):
            self.assertEqual(p.get("detection_status"), "CONFIRMED_SHEET_EDGE")
            self.assertFalse(p.get("is_uncertain", False))
            self.assertGreater(p.get("h", 0), 2)
            self.assertGreater(p.get("w", 0), 100)

        # Compressed stack body must be transparently uncertain
        bnd_list = res.get("boundary_reviews", [])
        self.assertEqual(len(bnd_list), 1)
        self.assertEqual(bnd_list[0].get("detection_status"), "UNCERTAIN_COMPRESSED_STACK")
        self.assertTrue(bnd_list[0].get("is_uncertain"))

        # Requirements: is_estimate must be True, side view requested in views_needed
        qb = res.get("quantity_breakdown", {})
        self.assertTrue(qb.get("is_estimate"))
        self.assertIn("side", res.get("views_needed", []))
        self.assertIn("side", qb.get("views_needed", []))
        self.assertIsNotNone(res.get("operator_guidance"))

    def test_02_two_front_views_preserves_uncertainty(self):
        """Two front views deduplicate visible rim sheets but do NOT resolve the interior compressed stack."""
        h, w = self.front_img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0.5, 1.0)
        front_img2 = cv2.warpAffine(self.front_img, M, (w, h))

        views_front_only = [
            {"image_bgr": self.front_img, "view_label": "front", "is_reference": True},
            {"image_bgr": front_img2, "view_label": "front_angle", "is_reference": False}
        ]
        res = self.service.fuse_multi_view_counting(
            views=views_front_only,
            counting_mode="individual_pieces",
            material_type="glass_sheets"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("primary_count"), 7)
        self.assertEqual(res.get("confirmed_count"), 7)
        self.assertEqual(res.get("uncertain_count"), 1)
        self.assertEqual(res.get("fusion_status"), "partial")
        self.assertTrue(res.get("is_estimate"))
        self.assertIn("side", res.get("views_needed", []))
        self.assertGreater(res.get("duplicate_observations_removed", 0), 0)

    def test_03_front_and_side_view_fusion_resolves_stack(self):
        """Front view + Side view corroborates front rim sheets, complements interior sheets, and clears uncertainty."""
        # Create a synthetic side view showing 24 sheets across stillage arm depth
        side_img = np.full((600, 800, 3), 40, dtype=np.uint8)
        cv2.rectangle(side_img, (100, 100), (700, 500), (50, 150, 50), -1)
        for i in range(25):
            sx = 140 + i * 20
            cv2.line(side_img, (sx, 120), (sx, 480), (200, 240, 255), 2)
            cv2.line(side_img, (sx + 2, 120), (sx + 2, 480), (100, 120, 130), 1)

        views_front_side = [
            {"image_bgr": self.front_img, "view_label": "front", "is_reference": True},
            {"image_bgr": side_img, "view_label": "side", "is_reference": False}
        ]
        res = self.service.fuse_multi_view_counting(
            views=views_front_side,
            counting_mode="individual_pieces",
            material_type="glass_sheets",
            glass_profile={"thickness": 6.0, "unit": "mm", "pieces_per_bundle": 25}
        )
        self.assertTrue(res.get("success"))
        # Side view resolves all sheets across pack depth (24 sheets)
        self.assertEqual(res.get("primary_count"), 24)
        self.assertEqual(res.get("confirmed_count"), 24)
        # Compressed stack body is resolved by the side view
        self.assertEqual(res.get("uncertain_count"), 0)
        self.assertEqual(res.get("fusion_status"), "complete")
        self.assertFalse(res.get("is_estimate"))
        self.assertEqual(res.get("views_needed"), [])

        # Deduplication must NOT simply sum counts (7 + 24 = 31 would be wrong)
        self.assertNotEqual(res.get("primary_count"), 7 + 24)
        self.assertEqual(res.get("duplicate_observations_removed"), 7)

        # Verify source-view provenance
        pieces = res.get("pieces", [])
        self.assertEqual(len(pieces), 24)
        # First 7 sheets observed in both front and side
        for p in pieces[:7]:
            self.assertIn("front", p.get("contributing_views", []))
            self.assertIn("side", p.get("contributing_views", []))
        # Interior sheets (8 to 24) observed in side view
        for p in pieces[7:]:
            self.assertEqual(p.get("contributing_views"), ["side"])

    def test_04_preserves_steel_individual_pieces(self):
        """Ensures that steel-section counting remains accurate and does not trigger glass pipeline."""
        pipes_path = "webapp/static/test_scenes/sample_individual_pipes_229.jpg"
        if not os.path.exists(pipes_path):
            pipes_path = "webapp/static/uploads/sample_individual_pipes_229.jpg"
        if not os.path.exists(pipes_path):
            raise unittest.SkipTest(f"Pipes reference image not found: {pipes_path}")

        pipe_img = cv2.imread(pipes_path)
        res = self.service.count_individual_pieces(
            pipe_img,
            counting_mode="individual_pieces",
            material_type="individual_pieces"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("material_type"), "individual_pieces")
        total = res.get("total_pieces", 0)
        # Reference count is ~225-229
        self.assertGreaterEqual(total, 220)
        self.assertLessEqual(total, 232)
        self.assertFalse(res.get("quantity_breakdown", {}).get("is_estimate"))


if __name__ == "__main__":
    unittest.main()
