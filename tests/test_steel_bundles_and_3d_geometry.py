import unittest
import numpy as np
import cv2
import os
import sys

sys.path.insert(0, os.path.abspath('webapp'))
from pallet_vision_counting_service import PalletVisionCountingService, get_pallet_vision_counting_service


class TestSteelBundlesAnd3DGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = get_pallet_vision_counting_service()
        cls.pipes_scene = "webapp/static/test_scenes/sample_individual_pipes_229.jpg"
        cls.timber_scene = "webapp/static/test_scenes/sample_timber_angle1_front.jpg"
        cls.carton_scene = "webapp/static/test_scenes/sample_carton_boxes.png"

    def test_01_steel_cross_section_envelope_and_deduplication(self):
        """
        PART 1: Verify that individual steel piece detection establishes physical stack
        envelope, suppresses inner/outer duplicates, rejects floor/background noise,
        and accurately identifies hollow steel sections.
        """
        if not os.path.exists(self.pipes_scene):
            self.skipTest("sample_individual_pipes_229.jpg not found")

        img = cv2.imread(self.pipes_scene)
        res = self.service.count_individual_pieces(img, counting_mode="individual_pieces")
        self.assertTrue(res.get("success"))
        pieces = res.get("pieces", [])
        total = res.get("total_pieces", 0)

        # 1. Total count must match physical inventory sections (229)
        self.assertEqual(total, 229)
        self.assertEqual(len(pieces), 229)

        # 2. Strict floor rejection: no piece should be placed on pallet runner or floor (y > 700)
        ys = [p["y"] for p in pieces]
        xs = [p["x"] for p in pieces]
        self.assertLess(max(ys), 695, "No pieces should be detected on floor / pallet runners below stack")
        self.assertGreater(min(ys), 25, "No pieces should be detected above stack in ceiling rafters")

        # 3. Inner/outer duplicate suppression: min distance between any two distinct pieces > 12px
        coords = np.array([[p["x"], p["y"]] for p in pieces], dtype=np.float32)
        dists = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=-1)
        np.fill_diagonal(dists, np.inf)
        min_dist = float(np.min(dists))
        self.assertGreaterEqual(
            min_dist, 13.0,
            "Inner void and outer rim of same pipe must not produce duplicate detections"
        )

    def test_02_physical_bundle_operator_review_5_bundles(self):
        """
        PART 2: Steel pipe bundle counting and Stage 6 operator review.
        Starting with a multi-view session containing 2 automated bundles (Layer 1, Layer 3),
        the operator adds 3 bundles across layers. The system must recalculate to exactly
        5 physical bundles, preserve operator corrections, and approve 5 bundles.
        """
        # Create an active multi-view bundle session
        sess_id = "SES-TEST-STEEL-BUNDLES-5"
        dummy_session = {
            "session_id": sess_id,
            "material_type": "steel_pipe_bundles",
            "counting_mode": "bundles",
            "views": ["front"],
            "primary_count": 2,
            "confirmed_count": 2,
            "uncertain_count": 0,
            "fused_objects": [
                {
                    "object_id": "MB-01",
                    "detection_id": "MB-01",
                    "bundle_id": "MB-01",
                    "primary_view": "front",
                    "contributing_views": ["front"],
                    "tier_index": 0,
                    "layer": 0,
                    "norm_x": 0.35,
                    "norm_y": 0.70,
                    "norm_w": 0.25,
                    "norm_h": 0.20,
                    "confidence": 0.95,
                    "status": "CONFIRMED",
                    "is_uncertain": False,
                    "is_bundle": True,
                    "review_state": "AUTO_PROPOSED"
                },
                {
                    "object_id": "MB-02",
                    "detection_id": "MB-02",
                    "bundle_id": "MB-02",
                    "primary_view": "front",
                    "contributing_views": ["front"],
                    "tier_index": 2,
                    "layer": 2,
                    "norm_x": 0.50,
                    "norm_y": 0.25,
                    "norm_w": 0.25,
                    "norm_h": 0.20,
                    "confidence": 0.94,
                    "status": "CONFIRMED",
                    "is_uncertain": False,
                    "is_bundle": True,
                    "review_state": "AUTO_PROPOSED"
                }
            ],
            "ambiguous_candidates": [],
            "quantity_breakdown": {
                "total_bundles": 2,
                "units_per_bundle": 50,
                "bundle_name": "Pipe Bundle",
                "uom": "EA",
                "individual_units_total": 100
            }
        }
        self.service._active_multiview_sessions[sess_id] = dummy_session

        # Operator adds 3 physical bundles (1 to Layer 1, 2 to Layer 2)
        # Bundle 3: Layer 1 (bottom tier, second position)
        self.service.review_multiview_session(
            session_id=sess_id,
            action="add_bundle",
            layer=0,
            norm_x=0.65,
            norm_y=0.70,
            notes="Operator added second bundle in Layer 1"
        )
        # Bundle 4: Layer 2 (middle tier, left)
        self.service.review_multiview_session(
            session_id=sess_id,
            action="add_bundle",
            layer=1,
            norm_x=0.35,
            norm_y=0.48,
            notes="Operator added left bundle in Layer 2"
        )
        # Bundle 5: Layer 2 (middle tier, right)
        updated = self.service.review_multiview_session(
            session_id=sess_id,
            action="add_bundle",
            layer=1,
            norm_x=0.65,
            norm_y=0.48,
            notes="Operator added right bundle in Layer 2"
        )

        # 1. Total physical bundles must be exactly 5
        self.assertEqual(updated["primary_count"], 5)
        self.assertEqual(updated["total_bundles"], 5)
        self.assertEqual(updated["physical_bundles_count"], 5)

        # 2. Recalculate must preserve all 5 bundles (must NOT discard operator added objects)
        recalc = self.service.review_multiview_session(session_id=sess_id, action="recalculate")
        self.assertEqual(recalc["primary_count"], 5)
        self.assertEqual(recalc["total_bundles"], 5)
        self.assertEqual(len(recalc["pieces"]), 5)

        # 3. Derived individual pieces calculation must be 5 * 50 = 250 EA
        qb = recalc.get("quantity_breakdown", {})
        self.assertEqual(qb.get("total_bundles"), 5)
        self.assertEqual(qb.get("units_per_bundle"), 50)
        self.assertEqual(qb.get("individual_units_total"), 250)

        # 4. Formally approve session
        approved = self.service.review_multiview_session(session_id=sess_id, action="approve_session")
        self.assertEqual(approved["review_status"], "APPROVED")
        self.assertTrue(approved["is_approved"])
        self.assertEqual(approved["primary_count"], 5)

    def test_03_dedicated_steel_pipe_bundle_3d_geometry(self):
        """
        PART 3 & PART 4: 3D Digital Twin must generate dedicated steel pipe bundle
        geometry with cylindrical assembly attributes, NOT cardboard boxes.
        """
        sess_id = "SES-TEST-STEEL-BUNDLES-5"
        session = self.service._active_multiview_sessions.get(sess_id)
        self.assertIsNotNone(session)

        m3d = session.get("matrix_3d", {})
        self.assertIsNotNone(m3d)
        self.assertEqual(m3d.get("geometry_type"), "steel_pipe_bundle")
        self.assertEqual(m3d.get("material_type"), "steel_pipe_bundles")
        self.assertEqual(m3d.get("total_units"), 5)

        boxes = m3d.get("boxes", [])
        self.assertEqual(len(boxes), 5, "Must render exactly 5 physical 3D bundle objects for the 5 confirmed bundles")

        # Verify each 3D object has steel pipe bundle geometry and layer placement
        for b in boxes:
            self.assertEqual(b.get("geometry_type"), "steel_pipe_bundle")
            self.assertEqual(b.get("material_type"), "steel_pipe_bundles")
            self.assertTrue(b.get("is_bundle"))
            self.assertIn(b.get("layer"), (0, 1, 2), "Layer must be 0, 1, or 2 (Layers 1-3)")

    def test_04_material_specific_3d_routing(self):
        """
        PART 4: Verify material-specific 3D geometry routing for carton, timber, and glass.
        Carton geometry must never be used as a universal fallback for non-carton materials.
        """
        # 1. Timber session produces timber_bundle geometry
        timber_sess_id = "SES-TEST-TIMBER-1"
        self.service._active_multiview_sessions[timber_sess_id] = {
            "session_id": timber_sess_id,
            "material_type": "timber",
            "counting_mode": "bundles",
            "primary_count": 10,
            "confirmed_count": 10,
            "fused_objects": [{"object_id": f"TMB-{i}", "status": "CONFIRMED", "tier_index": i % 3, "norm_x": 0.5, "norm_y": 0.5} for i in range(10)],
            "quantity_breakdown": {"total_bundles": 10}
        }
        tmb_res = self.service.review_multiview_session(timber_sess_id, action="recalculate")
        self.assertEqual(tmb_res["matrix_3d"]["geometry_type"], "timber_bundle")

        # 2. Glass session produces glass_sheet geometry
        glass_sess_id = "SES-TEST-GLASS-1"
        self.service._active_multiview_sessions[glass_sess_id] = {
            "session_id": glass_sess_id,
            "material_type": "glass_sheets",
            "counting_mode": "individual_pieces",
            "primary_count": 6,
            "confirmed_count": 6,
            "fused_objects": [{"object_id": f"GLS-{i}", "status": "CONFIRMED", "norm_x": 0.5, "norm_y": 0.5} for i in range(6)],
            "quantity_breakdown": {"total_pieces": 6}
        }
        gls_res = self.service.review_multiview_session(glass_sess_id, action="recalculate")
        self.assertEqual(gls_res["matrix_3d"]["geometry_type"], "glass_sheet")


if __name__ == '__main__':
    unittest.main()

