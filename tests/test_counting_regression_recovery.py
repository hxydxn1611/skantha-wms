import os
import unittest
import cv2
import json
import numpy as np

import sys
sys.path.insert(0, os.path.abspath('webapp'))

from webapp.pallet_vision_counting_service import PalletVisionCountingService, get_pallet_vision_counting_service
import app as flask_app_module


class TestCountingRegressionRecovery(unittest.TestCase):
    """
    Targeted Regression Recovery Test Suite:
    Verifies that all regressions from commit 385ceff are fully resolved.
    """

    @classmethod
    def setUpClass(cls):
        cls.service = get_pallet_vision_counting_service()
        flask_app_module.app.config['TESTING'] = True
        cls.client = flask_app_module.app.test_client()

        cls.carton_path = os.path.join("webapp", "static", "test_scenes", "sample_carton_boxes.png")
        cls.pipes_path = os.path.join("webapp", "static", "test_scenes", "sample_individual_pipes_229.jpg")
        cls.timber_path = os.path.join("webapp", "static", "test_scenes", "sample_timber_angle1_front.jpg")

    def test_01_carton_counting_restored_from_individual_pieces_mode(self):
        """
        REGRESSION RECOVERY: In visibly large carton stacks, carton counting previously
        regressed to 5 pieces because it was routed to the steel cross-section detector.
        Now it correctly detects physical carton instances and produces the full 3D Digital Twin.
        """
        if not os.path.exists(self.carton_path):
            self.skipTest("sample_carton_boxes.png scene not found")

        img = cv2.imread(self.carton_path)
        self.assertIsNotNone(img)

        # Call with counting_mode='pieces' as sent by workbench when user has not changed tabs
        res = self.service.count_individual_pieces(img, counting_mode="pieces")
        self.assertTrue(res.get("success"), "Carton counting must succeed")

        # Must report full stack of 125 pieces (not regressed to 5 or 42 pieces)
        total_pieces = res.get("total_pieces", 0)
        self.assertEqual(total_pieces, 125, f"Expected 125 carton boxes, got {total_pieces}")

        # Must generate authoritative 3D Digital Twin
        matrix_3d = res.get("matrix_3d")
        self.assertIsNotNone(matrix_3d, "3D matrix must be generated for carton stack")
        self.assertEqual(matrix_3d.get("layers"), 5)
        self.assertEqual(matrix_3d.get("columns"), 5)
        self.assertEqual(matrix_3d.get("rows"), 5)
        self.assertEqual(len(matrix_3d.get("boxes", [])), 125)

        # Visible vs Inferred breakdown
        qb = res.get("quantity_breakdown", {})
        self.assertEqual(qb.get("visible_count"), 45)
        self.assertEqual(qb.get("inferred_count"), 80)
        self.assertEqual(qb.get("total_units"), 125)

    def test_02_carton_boxes_material_type_routing(self):
        """
        Verify that explicit 'boxes' counting_mode or 'carton_boxes' material_type
        routes cleanly through both service and API without conflicting parameter errors.
        """
        if not os.path.exists(self.carton_path):
            self.skipTest("sample_carton_boxes.png scene not found")

        img = cv2.imread(self.carton_path)
        res = self.service.count_individual_pieces(
            img, counting_mode="boxes", material_type="carton_boxes"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("total_pieces"), 125)

        # Also test API endpoint with authenticated session
        with self.client.session_transaction() as sess:
            sess['user'] = {'username': 'admin', 'user_id': 'OP-TEST', 'role': 'Admin', 'name': 'Test Operator'}

        with open(self.carton_path, 'rb') as f:
            resp = self.client.post('/api/pallets/count-pieces', data={
                'image': (f, 'sample_carton_boxes.png'),
                'counting_mode': 'boxes',
                'material_type': 'carton_boxes'
            }, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("total_pieces"), 125)

    def test_03_sku_recognition_pipes_not_auto_strut(self):
        """
        REGRESSION RECOVERY: Steel sections must NOT be falsely associated with
        AUTO-STRUT-01 – Front MacPherson Strut Damper because of 'tube' in 'twin-tube'.
        Must return INFERRED-STEEL-PROFILE or appropriate steel SKU.
        """
        if not os.path.exists(self.pipes_path):
            self.skipTest("sample_individual_pipes_229.jpg scene not found")

        img = cv2.imread(self.pipes_path)
        sku_res = self.service.recognize_product_from_skus(
            img, counting_mode="individual_pieces", detected_count=219
        )
        self.assertIsNotNone(sku_res)
        self.assertNotEqual(
            sku_res.get("sku_id"), "AUTO-STRUT-01",
            "Steel pipe image must NEVER be recognized as Front MacPherson Strut Damper"
        )
        self.assertEqual(sku_res.get("sku_id"), "INFERRED-STEEL-PROFILE")

    def test_04_sku_mismatch_does_not_suppress_pipe_counting(self):
        """
        REGRESSION RECOVERY: If AUTO-STRUT-01 is explicitly passed to steel pipe image,
        it must NOT apply an incompatible color filter that drops the count to 15 or 76.
        The full 229 pipe sections must be detected and mismatch clearly flagged.
        """
        if not os.path.exists(self.pipes_path):
            self.skipTest("sample_individual_pipes_229.jpg scene not found")

        img = cv2.imread(self.pipes_path)

        # 1. Strategy resolution must detect mismatch
        strat = self.service.resolve_counting_strategy(
            image_bgr=img, counting_mode="pieces", sku_id="AUTO-STRUT-01"
        )
        self.assertTrue(strat.get("is_mismatch"), "Incompatible automotive SKU must flag is_mismatch=True")
        self.assertIn("automotive", strat.get("mismatch_warning", "").lower())
        self.assertEqual(strat.get("resolved_strategy"), "steel_profiles")

        # 2. Individual piece counting must detect full 229 pipe sections
        res = self.service.count_individual_pieces(
            img, counting_mode="pieces", sku_id="AUTO-STRUT-01"
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(
            res.get("total_pieces"), 229,
            "Count must remain 229 even if incompatible automotive SKU was selected"
        )
        self.assertEqual(len(res.get("pieces", [])), 229)

    def test_05_bundle_counting_preserves_physical_bundles(self):
        """
        REGRESSION RECOVERY: Bundle counting counts physical bundles, keeps bundle
        count separate from derived piece units, and does not fabricate hidden units.
        """
        if not os.path.exists(self.timber_path):
            self.skipTest("sample_timber_angle1_front.jpg scene not found")

        img = cv2.imread(self.timber_path)
        res = self.service.count_bundles_multi_view(
            img, counting_mode="bundles", material_type="timber",
            manual_units_per_bundle=50, manual_uom="BD"
        )
        self.assertTrue(res.get("success"))
        self.assertIn("total_bundles", res)
        self.assertEqual(res.get("total_bundles"), 10)
        self.assertEqual(res.get("physical_bundles_count"), 10)

        # Derived units calculation is preserved separately in quantity_breakdown
        qb = res.get("quantity_breakdown", {})
        self.assertEqual(qb.get("total_bundles"), 10)
        self.assertEqual(qb.get("units_per_bundle"), 50)
        self.assertEqual(qb.get("bundles_counted"), 10)
        self.assertEqual(qb.get("individual_units_total"), 500)
        self.assertTrue(qb.get("bundle_conversion_formula", "").startswith("10 "))
        self.assertIn("50 BD", qb.get("bundle_conversion_formula", ""))
        self.assertIn("= 500 BD", qb.get("bundle_conversion_formula", ""))


if __name__ == '__main__':
    unittest.main()
