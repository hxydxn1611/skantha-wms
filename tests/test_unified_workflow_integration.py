import os
import sys
import unittest
import uuid
import numpy as np
import cv2

# Add project root and webapp to path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, 'webapp'))

import db
from webapp.app import app
from webapp.pallet_vision_counting_service import get_pallet_vision_counting_service


class TestUnifiedWorkflowIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.service = get_pallet_vision_counting_service()
        cls.client = app.test_client()

    def test_01_strategy_resolution_mismatch_detection(self):
        """Test strategy resolution accurately detects visual mismatches between image and selected SKU/material."""
        # 1. Metallic grey image with glass SKU -> Mismatch
        steel_img = np.full((250, 250, 3), 130, dtype=np.uint8) # grey
        res_steel = self.service.resolve_counting_strategy(
            image_bgr=steel_img,
            counting_mode="individual_pieces",
            sku_id="GLS-FIR-BORO"
        )
        self.assertTrue(res_steel["is_mismatch"])
        self.assertIn("steel_profiles", res_steel["resolved_strategy"])
        self.assertIsNotNone(res_steel["mismatch_warning"])
        self.assertEqual(res_steel["recommended_counting_mode"], "individual_pieces")

        # 2. Cyan glass image with steel SKU -> Mismatch
        glass_img = np.zeros((250, 250, 3), dtype=np.uint8)
        glass_img[:, :] = (205, 185, 45) # cyan / aqua
        res_glass = self.service.resolve_counting_strategy(
            image_bgr=glass_img,
            counting_mode="individual_pieces",
            sku_id="STL-SEC-200"
        )
        self.assertTrue(res_glass["is_mismatch"])
        self.assertEqual(res_glass["resolved_strategy"], "glass_sheets")
        self.assertIsNotNone(res_glass["mismatch_warning"])

        # 3. Wood timber image with timber bundles mode -> Match
        wood_img = np.zeros((250, 250, 3), dtype=np.uint8)
        wood_img[:, :] = (35, 95, 160) # warm wood brown
        res_wood = self.service.resolve_counting_strategy(
            image_bgr=wood_img,
            counting_mode="bundles",
            material_type="timber_bundles"
        )
        self.assertFalse(res_wood["is_mismatch"])
        self.assertEqual(res_wood["resolved_strategy"], "timber_bundles")

    def test_02_resolve_strategy_api_endpoint(self):
        """Test POST /api/pallets/resolve-strategy HTTP endpoint."""
        resp = self.client.post('/api/pallets/resolve-strategy', json={
            'counting_mode': 'bundles',
            'material_type': 'timber_bundles',
            'sku_id': 'TMB-PN-001'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["resolved_strategy"], "timber_bundles")

    def test_03_single_view_session_registration(self):
        """Test single-view counting creates an active session with session_id and standardized fields."""
        steel_img = np.full((200, 200, 3), 125, dtype=np.uint8)
        res = self.service.count_individual_pieces(steel_img, counting_mode="individual_pieces")
        self.assertIn("session_id", res)
        sess_id = res["session_id"]
        self.assertTrue(sess_id.startswith("SES-COUNT-"))

        # Check caching in active sessions
        self.assertIn(sess_id, self.service._active_multiview_sessions)
        cached = self.service._active_multiview_sessions[sess_id]
        self.assertIn("fused_objects", cached)
        self.assertIn("confirmed_count", cached)
        self.assertIn("uncertain_count", cached)
        self.assertIn("review_status", cached)

    def test_04_operator_review_actions(self):
        """Test full suite of Stage 6 Operator Review actions."""
        sess_id = f"SES-TEST-REVIEW-{uuid.uuid4().hex[:8]}"
        self.service._active_multiview_sessions[sess_id] = {
            "session_id": sess_id,
            "sku_id": "STL-SEC-100",
            "material_type": "steel_profiles",
            "primary_count": 2,
            "confirmed_count": 2,
            "uncertain_count": 1,
            "review_status": "AUTO_PROPOSED",
            "fused_objects": [
                {
                    "object_id": "OBJ-001",
                    "status": "CONFIRMED",
                    "is_uncertain": False,
                    "contributing_views": ["front", "angled"],
                    "norm_x": 0.2, "norm_y": 0.3, "norm_w": 0.1, "norm_h": 0.1, "confidence": 0.95
                },
                {
                    "object_id": "OBJ-002",
                    "status": "UNCERTAIN",
                    "is_uncertain": True,
                    "contributing_views": ["front"],
                    "norm_x": 0.5, "norm_y": 0.5, "norm_w": 0.1, "norm_h": 0.1, "confidence": 0.60
                }
            ],
            "ambiguous_candidates": [
                {
                    "candidate_obj_id": "AMB-001",
                    "view_label": "side",
                    "confidence": 0.70,
                    "best_score": 0.72
                }
            ],
            "quantity_breakdown": {
                "directly_detected_count": 2,
                "total_units": 2,
                "total_pieces": 2,
                "units_per_bundle": 1
            }
        }

        # 1. Action: confirm_object (confirm uncertain OBJ-002)
        rev1 = self.service.review_multiview_session(sess_id, action="confirm_object", object_id="OBJ-002")
        self.assertEqual(rev1["confirmed_count"], 2)
        obj2 = next(o for o in rev1["fused_objects"] if o["object_id"] == "OBJ-002")
        self.assertFalse(obj2["is_uncertain"])
        self.assertEqual(obj2["status"], "CONFIRMED")

        # 2. Action: separate_object (split multi-view OBJ-001 into distinct objects)
        rev2 = self.service.review_multiview_session(sess_id, action="separate_object", object_id="OBJ-001")
        self.assertEqual(len(rev2["fused_objects"]), 3)
        self.assertEqual(rev2["confirmed_count"], 3)

        # 3. Action: reject_object (reject one object as false positive)
        rev3 = self.service.review_multiview_session(sess_id, action="reject_object", object_id="OBJ-002")
        obj2_rej = next(o for o in rev3["fused_objects"] if o["object_id"] == "OBJ-002")
        self.assertEqual(obj2_rej["status"], "REJECTED")
        self.assertEqual(rev3["confirmed_count"], 2) # Excluded from confirmed count

        # 4. Action: confirm_ambiguous (accept candidate AMB-001)
        rev4 = self.service.review_multiview_session(sess_id, action="confirm_ambiguous", object_id="AMB-001")
        self.assertEqual(len(rev4["ambiguous_candidates"]), 0) # Removed from ambiguous
        self.assertEqual(rev4["confirmed_count"], 3) # Added to confirmed

        # 5. Action: recalculate
        rev5 = self.service.review_multiview_session(sess_id, action="recalculate")
        self.assertEqual(rev5["confirmed_count"], 3)

        # 6. Action: approve_session
        rev6 = self.service.review_multiview_session(sess_id, action="approve_session", notes="Supervisor final approval")
        self.assertEqual(rev6["review_status"], "APPROVED")
        self.assertTrue(rev6.get("is_approved"))

    def test_05_inventory_transfer_workflow(self):
        """Test inventory transfer endpoint enforces approval, updates inventory, and prevents duplicates."""
        sess_id = f"SES-INV-TEST-{uuid.uuid4().hex[:8]}"
        self.service._active_multiview_sessions[sess_id] = {
            "session_id": sess_id,
            "sku_id": "PIP-RND-100",
            "material_type": "steel_profiles",
            "inferred_material": "steel_profiles",
            "counting_mode": "individual_pieces",
            "primary_count": 48,
            "confirmed_count": 48,
            "uncertain_count": 0,
            "physical_bundles_count": 0,
            "units_per_bundle": 1,
            "total_pieces": 48,
            "uom": "PIPES",
            "review_status": "AUTO_PROPOSED", # Not yet approved!
            "fused_objects": [],
            "source_images": ["/static/uploads/test_pipe.jpg"]
        }

        # 1. Attempt transfer without approval -> Should fail with 400
        res_fail = self.client.post('/api/pallets/transfer-inventory', json={
            "session_id": sess_id,
            "target_type": "bin",
            "bin_id": "BIN-STEEL-01"
        })
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn("unapproved_session", res_fail.get_json()["error_code"])

        # 2. Operator reviews and approves session
        self.service.review_multiview_session(sess_id, action="approve_session")

        # 3. Transfer approved session -> Should succeed with 200
        res_ok = self.client.post('/api/pallets/transfer-inventory', json={
            "session_id": sess_id,
            "target_type": "bin",
            "bin_id": "BIN-STEEL-01",
            "operator_id": "OP-LEAD",
            "notes": "Verified steel batch delivery"
        })
        self.assertEqual(res_ok.status_code, 200)
        ok_data = res_ok.get_json()
        self.assertTrue(ok_data["success"])
        self.assertEqual(ok_data["receipt"]["total_pieces"], 48)
        self.assertEqual(ok_data["receipt"]["uom"], "PIPES")

        # Check ledger record
        sub_record = db.get_vision_counting_submission(sess_id)
        self.assertIsNotNone(sub_record)
        self.assertEqual(sub_record["total_pieces"], 48)
        self.assertEqual(sub_record["bin_id"], "BIN-STEEL-01")

        # 4. Attempt duplicate transfer with same session -> Should fail with 409 Conflict
        res_dup = self.client.post('/api/pallets/transfer-inventory', json={
            "session_id": sess_id,
            "target_type": "bin",
            "bin_id": "BIN-STEEL-01"
        })
        self.assertEqual(res_dup.status_code, 409)
        self.assertEqual(res_dup.get_json()["error_code"], "duplicate_transfer")


if __name__ == '__main__':
    unittest.main()
