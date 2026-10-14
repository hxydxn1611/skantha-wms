"""
Test Suite: Phase 1 — Verify and Consolidate AI Model Weights
Validates:
1. Successful loading of the verified local model (yolov8n.pt).
2. Deterministic path resolution from both root and webapp dirs.
3. Safe offline fallback when missing model (e.g. yolo11s.pt) is requested.
4. Clean error handling when an unknown model is requested with allow_fallback=False.
5. In-memory detector sharing (no duplicate model instances).
6. Integration with ObjectDetectionEngine and SmartCamera.
"""

import os
import sys
import unittest

# Ensure webapp is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
webapp_dir = os.path.join(project_root, "webapp")
if webapp_dir not in sys.path:
    sys.path.insert(0, webapp_dir)

import model_loader
from detection_service import get_detection_engine, ObjectDetectionEngine
from ai_engine import SmartCamera


class TestPhase1ModelConsolidation(unittest.TestCase):

    def test_01_available_models_discovery(self):
        """Verify that local available models are detected without scanning internet."""
        local_models = model_loader.get_available_local_models()
        self.assertGreater(len(local_models), 0, "At least one local model file must be present.")
        filenames = [m["filename"] for m in local_models]
        self.assertIn("yolov8n.pt", filenames, "yolov8n.pt should be available in local search paths.")
        
        # Verify file size and properties
        for m in local_models:
            self.assertTrue(os.path.isfile(m["path"]), f"Model path must be a valid file: {m['path']}")
            self.assertGreater(m["size_bytes"], 1000000, "Model weight file must be non-empty.")

    def test_02_deterministic_path_resolution(self):
        """Verify path resolution finds yolov8n.pt regardless of search origin."""
        resolved = model_loader.resolve_model_path("yolov8n.pt")
        self.assertIsNotNone(resolved, "yolov8n.pt must resolve to an absolute path.")
        self.assertTrue(os.path.isabs(resolved), "Resolved path must be absolute.")
        self.assertTrue(os.path.isfile(resolved), "Resolved path must exist on disk.")

        # Test non-existent model
        missing_res = model_loader.resolve_model_path("non_existent_fake_model.pt")
        self.assertIsNone(missing_res, "Non-existent model must return None, not trigger downloads.")

    def test_03_safe_fallback_behavior(self):
        """When yolo11s.pt is requested (missing), it must safely fall back to yolov8n.pt."""
        model, active_name, path, err = model_loader.load_yolo_model(
            requested_model="yolo11s.pt",
            fallback_model="yolov8n.pt",
            allow_fallback=True
        )
        self.assertIsNotNone(model, "Model must load via local fallback.")
        self.assertEqual(active_name, "yolov8n.pt", "Active model should be the fallback yolov8n.pt.")
        self.assertIsNone(err, "Error should be None when fallback succeeds.")
        self.assertIsNotNone(path, "Active model path must be populated.")

    def test_04_missing_model_without_fallback(self):
        """When a missing model is requested with allow_fallback=False, it must log error and return None."""
        model, active_name, path, err = model_loader.load_yolo_model(
            requested_model="completely_missing_weights.pt",
            allow_fallback=False
        )
        self.assertIsNone(model, "Model must be None when file is missing and fallback is disabled.")
        self.assertIsNotNone(err, "Error message must be returned describing the missing file.")
        self.assertIn("not found", err.lower(), "Error should explicitly mention not found.")

    def test_05_shared_detector_caching(self):
        """Verify that multiple requests for detector reuse the cached instance."""
        m1, name1, err1 = model_loader.get_shared_detector("yolov8n.pt")
        m2, name2, err2 = model_loader.get_shared_detector("yolov8n.pt")
        self.assertIs(m1, m2, "get_shared_detector must return the exact same in-memory singleton.")
        self.assertEqual(name1, name2)

    def test_06_detection_engine_integration(self):
        """Verify ObjectDetectionEngine initializes using consolidated model_loader."""
        engine = get_detection_engine()
        self.assertTrue(engine.is_loaded, "ObjectDetectionEngine must report is_loaded=True.")
        self.assertEqual(engine.model_name, "yolov8n.pt", "Active model should be resolved to yolov8n.pt.")
        self.assertIsNone(engine.last_load_error)
        
        info = engine.get_service_info()
        self.assertEqual(info["model_name"], "yolov8n.pt")
        self.assertTrue(info["is_loaded"])
        self.assertIn("limitations", info)

    def test_07_smart_camera_integration(self):
        """Verify SmartCamera class uses the consolidated model detector."""
        # Initialize a camera object with test mode to avoid EasyOCR download
        os.environ["WARLOG_TEST_MODE"] = "1"
        cam = SmartCamera(
            camera_id="TEST-CAM-MODEL",
            name="Model Verification Camera",
            url="0",
            location="Dock"
        )
        self.assertIsNotNone(SmartCamera.vehicle_model, "SmartCamera.vehicle_model must be loaded.")
        self.assertEqual(SmartCamera.active_model_name, "yolov8n.pt")


if __name__ == "__main__":
    unittest.main()
