"""
AI Vision & Tracking Master - Object Detection Engine Service
Part 5: Local YOLO-based object detection service.

Provides modular inference, device selection (CUDA/CPU fallback),
normalized bounding box calculations, class taxonomy mapping to
existing Object Classes Master, and optional ROI containment context.

Strict Scope: Detection ONLY. No tracking IDs, Re-ID, OCR, or event engine.
"""

import os
import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
import numpy as np
import cv2

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default mapping from pretrained YOLO / COCO class labels to Skandha Object Class Codes
DEFAULT_CLASS_MAPPING = {
    # Core Warehouse Logistics Classes
    "bundle": "BUNDLE",
    "pallet": "PALLET",
    "box": "BOX",
    "carton": "BOX",
    "crate": "BOX",
    "package": "BOX",
    "metal frame": "BUNDLE",
    "steel bar bundle": "BUNDLE",
    "steel bar": "BUNDLE",
    "forklift": "FORKLIFT",
    "worker": "WORKER",
    "person": "WORKER",
    "truck": "TRUCK",
    "car": "TRUCK",
    "bus": "TRUCK",
    "license plate": "LICENSE_PLATE",

    # Intelligent COCO proxies for warehouse scenes
    "surfboard": "BUNDLE",   # Long metal frame / profile / rebar proxy in COCO
    "bench": "BUNDLE",       # Frame stack / heavy bundle proxy in COCO
    "skis": "BUNDLE",        # Long metal profile / rod proxy in COCO
    "snowboard": "BUNDLE",   # Wide structural panel / frame bundle proxy in COCO
    "baseball bat": "BUNDLE",# Bar / pipe / profile proxy in COCO
    "bed": "PALLET",         # Pallet base / palletized unit load proxy in COCO
    "dining table": "PALLET",# Pallet platform / staging base proxy in COCO
    "suitcase": "BOX",       # Packaging / carton proxy in COCO
    "backpack": "BOX",       # Package proxy in COCO
    "handbag": "BOX",        # Small parcel proxy in COCO
    "book": "BOX",           # Small flat package proxy in COCO
    "refrigerator": "BOX",   # Large industrial crate proxy in COCO
    "tv": "BOX",             # Large flat box proxy in COCO

    # Automotive & Industrial Components + Multi-Industry (Glass, Wood/Timber, Construction, Chemicals, Textiles)
    "engine block": "ENGINE_BLOCK",
    "windshield": "WINDSHIELD",
    "bumper": "BUMPER",
    "screw box": "SCREW_BOX",
    "steering wheel": "STEERING_WHEEL",
    "tire bundle": "TIRE_BUNDLE",
    "hood": "HOOD",
    "bin": "BIN",
    "material": "MATERIAL",
    "glass": "GLASS_SHEET_STACK",
    "glass sheet": "GLASS_SHEET_STACK",
    "glass stack": "GLASS_SHEET_STACK",
    "glass crate": "WOODEN_GLASS_CRATE",
    "a-frame": "GLASS_A_FRAME",
    "plywood": "PLYWOOD_STACK",
    "plywood stack": "PLYWOOD_STACK",
    "timber": "TIMBER_PLANK_BUNDLE",
    "timber plank": "TIMBER_PLANK_BUNDLE",
    "lumber": "TIMBER_PLANK_BUNDLE",
    "wood plank": "TIMBER_PLANK_BUNDLE",
    "mdf": "MDF_BOARD_PALLET",
    "ibc tote": "IBC_TOTE",
    "drum": "DRUM_PALLET",
    "fabric roll": "FABRIC_ROLL",
    "cotton bale": "COTTON_BALE",
    "reach truck": "FORKLIFT",
    "pallet jack": "FORKLIFT",
    "motorcycle": "FORKLIFT",
    "rod": "ROD",
    "pipe": "BUNDLE",
    "wooden plank": "TIMBER_PLANK_BUNDLE",
    "container": "BOX",
    "bottle": "BOX",
    "bag": "BOX",
    "tote": "BIN",
    "finished goods carton": "BOX",
    "material / tube bundle": "BUNDLE",
    "storage pallet": "PALLET",
    "parts tote": "BIN",
    "plant personnel": "WORKER",
    "transport trailer": "TRUCK",
    "part": "PART",
    "component": "COMPONENT",
    "fastener": "FASTENER",
    "sku": "SKU"
}

# Fallback human-readable class names if database is not queried
FALLBACK_CLASS_NAMES = {
    "BOX": "Box / Carton",
    "WORKER": "Worker / Personnel",
    "TRUCK": "Truck / Carrier",
    "PALLET": "Storage Pallet",
    "FORKLIFT": "Forklift / MHE Vehicle",
    "BIN": "Storage Bin / Tote",
    "BUNDLE": "Stock Bundle",
    "GLASS_A_FRAME": "Glass A-Frame Stillage",
    "GLASS_SHEET_STACK": "Float Glass Sheet Stack",
    "WOODEN_GLASS_CRATE": "Wooden Glass Crate",
    "PLYWOOD_STACK": "Plywood Sheet Stack",
    "TIMBER_PLANK_BUNDLE": "Timber Plank Bundle",
    "MDF_BOARD_PALLET": "MDF / Particle Board Pallet",
    "IBC_TOTE": "Chemical IBC Tote",
    "DRUM_PALLET": "Industrial Drum Pallet",
    "FABRIC_ROLL": "Textile Fabric Roll",
    "COTTON_BALE": "Compressed Cotton Bale",
    "ENGINE_BLOCK": "Engine Block",
    "WINDSHIELD": "Windshield",
    "BUMPER": "Bumper",
    "SCREW_BOX": "Screw Box",
    "STEERING_WHEEL": "Steering Wheel",
    "TIRE_BUNDLE": "Tire Bundle",
    "HOOD": "Hood",
    "LICENSE_PLATE": "License Plate",
    "MATERIAL": "Industrial Material",
    "GLASS": "Glass Sheet / Panel",
    "ROD": "Rod / Tube / Shaft",
    "PART": "Industrial Part",
    "COMPONENT": "Component / Assembly",
    "FASTENER": "Fastener / Hardware",
    "SKU": "Material SKU"
}

# Model limitations documentation for report and UI notice
MODEL_LIMITATIONS = {
    "pretrained_model": "yolo11s.pt (Ultralytics YOLO11)",
    "natively_supported_classes": ["WORKER (via 'person')", "TRUCK (via 'truck', 'car', 'bus')"],
    "proxy_classes": ["BOX (via 'suitcase', 'backpack')"],
    "unsupported_in_coco": [
        "PALLET (Wooden/plastic storage pallets require custom warehouse weights)",
        "FORKLIFT (Reach trucks and forklifts require custom warehouse weights)",
        "BIN (Shelving totes and small-part bins require custom warehouse weights)"
    ],
    "notes": "Ultralytics YOLO11 provides enhanced feature representation and higher mAP inference. Custom-trained warehouse dataset can replace yolo11s.pt seamlessly."
}


def is_point_in_polygon(point: Dict[str, float], polygon: List[Dict[str, float]]) -> bool:
    """
    Ray-casting algorithm to test whether a normalized point {x, y}
    lies inside a normalized polygon/rectangle boundary [{x, y}, ...].
    """
    if not polygon or len(polygon) < 3:
        return False

    x = float(point.get('x', 0.0))
    y = float(point.get('y', 0.0))
    n = len(polygon)
    inside = False

    p1x = float(polygon[0].get('x', 0.0))
    p1y = float(polygon[0].get('y', 0.0))

    for i in range(1, n + 1):
        p2 = polygon[i % n]
        p2x = float(p2.get('x', 0.0))
        p2y = float(p2.get('y', 0.0))

        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    else:
                        xinters = p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


from model_loader import (
    resolve_model_path,
    load_yolo_model,
    get_shared_detector,
    DEFAULT_VERIFIED_MODEL,
    CONFIGURED_MODEL_PREFERENCE,
    MODEL_CAPABILITIES
)

class ObjectDetectionEngine:
    """
    Modular Object Detection Engine wrapping Ultralytics YOLO.
    Maintains clean separation from HTTP routes and data persistence.
    """

    def __init__(self, model_name: Optional[str] = None, device: str = "auto", conf_threshold: float = 0.15):
        self.requested_model_name = model_name or CONFIGURED_MODEL_PREFERENCE
        self.model_name = self.requested_model_name
        self.device_preference = device
        self.conf_threshold = conf_threshold
        self.model = None
        self.active_device = "cpu"
        self.class_mapping = dict(DEFAULT_CLASS_MAPPING)
        self.is_loaded = False
        self.last_load_error = None
        self.resolved_model_path = None
        self._inference_lock = threading.RLock()

        self._select_device()
        self._load_model()

    def _select_device(self, force_device: Optional[str] = None):
        """
        Device selection logic:
        Automatically selects CUDA if available; cleanly falls back to CPU.
        """
        pref = (force_device or self.device_preference).lower()
        if pref == "cpu":
            self.active_device = "cpu"
        elif pref in ("cuda", "gpu"):
            if TORCH_AVAILABLE and torch.cuda.is_available():
                self.active_device = "cuda:0"
            else:
                logger.warning("CUDA requested but not available. Falling back to CPU.")
                self.active_device = "cpu"
        else:
            # Auto selection
            if TORCH_AVAILABLE and torch.cuda.is_available():
                self.active_device = "cuda:0"
            else:
                self.active_device = "cpu"

    def _load_model(self) -> bool:
        """
        Initialize and load the YOLO detector model using consolidated model_loader.
        Avoids duplicate memory allocations and prevents runtime internet downloads.
        """
        if not ULTRALYTICS_AVAILABLE:
            self.last_load_error = "Ultralytics package is not installed."
            self.is_loaded = False
            return False

        try:
            model, active_name, active_path, err = load_yolo_model(
                requested_model=self.requested_model_name,
                fallback_model=DEFAULT_VERIFIED_MODEL,
                allow_fallback=True,
                device=self.active_device
            )

            if model is None or err:
                self.is_loaded = False
                self.last_load_error = err or "Unknown model loading error"
                logger.error(f"Detector loading failed: {self.last_load_error}")
                return False

            self.model = model
            self.model_name = active_name
            self.resolved_model_path = active_path
            self.is_loaded = True
            self.last_load_error = None

            # If using YOLO-World, set zero-shot custom classes
            if 'world' in self.model_name.lower():
                custom_classes = [
                    "person", "worker", "forklift", "truck", "car",
                    "bundle", "pallet", "metal frame", "box", "carton", "crate",
                    "package", "steel bar bundle", "glass sheet", "wooden plank",
                    "timber", "plywood", "pipe", "container", "bottle", "bag",
                    "book", "bin", "tote", "license plate"
                ]
                try:
                    self.model.set_classes(custom_classes)
                    logger.info(f"YOLO-World zero-shot classes set: {custom_classes}")
                except Exception as e:
                    logger.warning(f"Could not set YOLO-World classes: {e}")

            logger.info(f"Loaded YOLO model '{self.model_name}' (path: {active_path}) on device '{self.active_device}'")
            return True
        except Exception as e:
            self.is_loaded = False
            self.last_load_error = str(e)
            logger.error(f"Failed to load YOLO model '{self.requested_model_name}': {e}")
            return False

    def update_zero_shot_classes(self, custom_names: List[str], vision_classes: Optional[List[ Any]] = None) -> bool:
        """Thread-safely updates YOLO-World zero-shot classes and registers their class_code mappings."""
        with self._inference_lock:
            if vision_classes:
                for vc in vision_classes:
                    if isinstance(vc, (list, tuple)) and len(vc) >= 2:
                        code_str = str(vc[0]).strip().upper()
                        label_str = str(vc[1]).strip().lower()
                        self.class_mapping[label_str] = code_str
                        FALLBACK_CLASS_NAMES[code_str] = str(vc[1]).strip()
            if self.model is not None and 'world' in str(self.model_name).lower():
                core_prompts = [
                    "person", "worker", "forklift", "truck", "car",
                    "bundle", "pallet", "box", "carton", "crate", "package",
                    "glass sheet", "wooden plank", "timber", "plywood", "pipe",
                    "container", "bottle", "bag", "book", "bin", "tote", "license plate"
                ]
                merged = list(dict.fromkeys(core_prompts + [str(n).strip().lower() for n in custom_names if n]))
                if hasattr(self.model, "predictor"):
                    self.model.predictor = None
                self.model.set_classes(merged)
                return True
        return False

    def reload(self, model_name: Optional[str] = None, device: Optional[str] = None, conf_threshold: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """
        Reload model with new parameters.
        """
        if model_name:
            self.requested_model_name = model_name
            self.model_name = model_name
        if device:
            self.device_preference = device
        if conf_threshold is not None:
            self.conf_threshold = max(0.01, min(0.99, float(conf_threshold)))

        self._select_device()
        success = self._load_model()
        return success, self.last_load_error

    def get_service_info(self) -> Dict[str, Any]:
        """
        Return comprehensive detector configuration and capability metadata.
        """
        cuda_avail = bool(TORCH_AVAILABLE and torch.cuda.is_available())
        device_name = "CPU"
        if cuda_avail and "cuda" in self.active_device:
            device_name = torch.cuda.get_device_name(0)

        return {
            "model_name": self.model_name,
            "is_loaded": self.is_loaded,
            "last_load_error": self.last_load_error,
            "device": self.active_device,
            "device_name": device_name,
            "cuda_available": cuda_avail,
            "confidence_threshold": self.conf_threshold,
            "class_mapping": self.class_mapping,
            "limitations": MODEL_LIMITATIONS
        }

    def _resolve_sku_for_detection(
        self,
        frame_bgr: np.ndarray,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        mapped_code: str
    ) -> Optional[Dict[str, Any]]:
        """
        Matches a detected stock/bundle/box/pallet crop to the active warehouse's SKU catalog
        and attaches its SKU code, product name, declared units_per_bundle, and practical UOM.
        """
        try:
            import db
            now = time.time()
            if not hasattr(self, "_cached_skus") or (now - getattr(self, "_cached_skus_time", 0.0)) > 3.0:
                self._cached_skus = db.get_all_skus() or []
                self._cached_skus_time = now
            skus = self._cached_skus
            if not skus:
                return None

            h, w = frame_bgr.shape[:2]
            cx1, cy1 = max(0, min(w - 2, x1)), max(0, min(h - 2, y1))
            cx2, cy2 = max(cx1 + 2, min(w, x2)), max(cy1 + 2, min(h, y2))
            crop = frame_bgr[cy1:cy2, cx1:cx2]

            best_sku = None
            best_score = -1.0
            code_l = str(mapped_code or "").lower()

            if not hasattr(self, "_shared_sku_matcher"):
                try:
                    from pallet_service import SkuVisualSignatureMatcher
                    self._shared_sku_matcher = SkuVisualSignatureMatcher()
                except Exception:
                    self._shared_sku_matcher = None
            matcher = self._shared_sku_matcher

            for s in skus:
                sid = s.get("sku_id", "")
                blob = f"{sid} {s.get('name', '')} {s.get('category', '')} {s.get('bundle_name', '')}".lower()
                sim = 0.45
                if matcher and crop.size > 0:
                    try:
                        sc = matcher.compute_similarity(crop, sid)
                        if sc > 0:
                            sim = float(sc)
                    except Exception:
                        pass
                if any(tok in blob for tok in code_l.split("_") if len(tok) >= 3):
                    sim += 0.25
                if sim > best_score:
                    best_score = sim
                    best_sku = s

            if not best_sku:
                best_sku = skus[0]

            upb = max(1, int(best_sku.get("units_per_bundle") or 1))
            uom = str(best_sku.get("uom") or "EA").upper()
            bname = best_sku.get("bundle_name") or "Bundle"
            return {
                "sku_id": best_sku["sku_id"],
                "sku_name": best_sku.get("name") or best_sku["sku_id"],
                "sku_category": best_sku.get("category") or "General",
                "uom": uom,
                "units_per_bundle": upb,
                "bundle_name": bname
            }
        except Exception:
            return None

    def detect(
        self,
        image_input: Union[np.ndarray, bytes, str],
        camera_id: Optional[str] = None,
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        master_classes: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Run object detection on an image input.
        Returns standardized, resolution-independent structured detection results.
        """
        t_start = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        threshold = float(conf_threshold if conf_threshold is not None else self.conf_threshold)

        # 1. Parse Image Input to OpenCV BGR array
        frame_bgr, parse_err = self._parse_image(image_input)
        if parse_err or frame_bgr is None:
            return {
                "success": False,
                "error": parse_err or "Invalid or unreadable image input.",
                "camera_id": camera_id,
                "timestamp": timestamp_str,
                "detections": []
            }

        height, width = frame_bgr.shape[:2]
        if height <= 0 or width <= 0:
            return {
                "success": False,
                "error": "Image has invalid dimensions.",
                "camera_id": camera_id,
                "timestamp": timestamp_str,
                "detections": []
            }

        # 2. Check model load status
        if not self.is_loaded or self.model is None:
            return {
                "success": False,
                "error": f"Detector model '{self.model_name}' is not loaded: {self.last_load_error}",
                "camera_id": camera_id,
                "timestamp": timestamp_str,
                "detections": []
            }

        # Build lookup table of active master classes
        active_class_names = dict(FALLBACK_CLASS_NAMES)
        if master_classes:
            for mc in master_classes:
                active_class_names[mc.get('code')] = mc.get('name', mc.get('code'))

        # 3. Execute Inference (thread-safe lock prevents collision with dynamic set_classes)
        t_pre = time.perf_counter()
        infer_imgsz = 480 if self.active_device == "cpu" else 640
        try:
            with self._inference_lock:
                results = self.model(
                    source=frame_bgr,
                    conf=threshold,
                    imgsz=infer_imgsz,
                    device=self.active_device,
                    verbose=False
                )
        except Exception as inf_err:
            logger.error(f"Inference execution failed on {self.active_device}: {inf_err}")
            # Try CPU fallback if CUDA failed
            if "cuda" in self.active_device:
                logger.info("Retrying inference on CPU fallback...")
                try:
                    self.active_device = "cpu"
                    results = self.model(
                        source=frame_bgr,
                        conf=threshold,
                        device="cpu",
                        verbose=False
                    )
                except Exception as cpu_err:
                    return {
                        "success": False,
                        "error": f"Inference failed on GPU and CPU fallback: {cpu_err}",
                        "camera_id": camera_id,
                        "timestamp": timestamp_str,
                        "detections": []
                    }
            else:
                return {
                    "success": False,
                    "error": f"Inference execution failed: {inf_err}",
                    "camera_id": camera_id,
                    "timestamp": timestamp_str,
                    "detections": []
                }

        t_post_start = time.perf_counter()

        # 4. Extract Structured Detections
        detections: List[Dict[str, Any]] = []

        if results and len(results) > 0:
            res = results[0]
            boxes = res.boxes

            # Model class name dictionary
            names_dict = res.names if hasattr(res, 'names') else (self.model.names if hasattr(self.model, 'names') else {})

            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, 'cpu') else np.array(boxes.xyxy)
                confs = boxes.conf.cpu().numpy() if hasattr(boxes.conf, 'cpu') else np.array(boxes.conf)
                classes = boxes.cls.cpu().numpy() if hasattr(boxes.cls, 'cpu') else np.array(boxes.cls)

                for i in range(len(xyxy)):
                    raw_cls_id = int(classes[i])
                    raw_class_name = names_dict.get(raw_cls_id, str(raw_cls_id)).lower()
                    confidence = float(confs[i])

                    # Map raw model class to Skandha Object Class Code
                    mapped_code = self.class_mapping.get(raw_class_name) or self.class_mapping.get(raw_class_name.lower())
                    if not mapped_code:
                        if getattr(self, "model_name", "") == "best.pt":
                            # Auto-adopt custom trained class names from fine-tuned weights
                            mapped_code = raw_class_name.upper().replace(' ', '_')
                        elif 'world' in str(getattr(self, "model_name", "")).lower():
                            if any(k in raw_class_name for k in ("person", "worker", "personnel", "operator", "inspector")):
                                mapped_code = "WORKER"
                            elif any(k in raw_class_name for k in ("forklift", "reach", "jack", "clamp")):
                                mapped_code = "FORKLIFT"
                            elif any(k in raw_class_name for k in ("truck", "trailer", "van", "tanker")):
                                mapped_code = "TRUCK"
                            elif any(k in raw_class_name for k in ("pallet", "stillage", "cradle")):
                                mapped_code = "PALLET"
                            elif any(k in raw_class_name for k in ("bundle", "stack", "roll", "bale", "plank", "sheet", "pipe")):
                                mapped_code = "BUNDLE"
                            else:
                                mapped_code = "BOX"
                        else:
                            # Drop non-warehouse classes (e.g. chair, couch, cell phone, remote, toilet, animal, etc.)
                            # This strictly prevents recognizing random background objects as warehouse items.
                            continue
                    if mapped_code not in active_class_names:
                        active_class_names[mapped_code] = raw_class_name.replace('_', ' ').title()

                    # Bounding box in integer display pixels
                    x1 = max(0, round(float(xyxy[i][0])))
                    y1 = max(0, round(float(xyxy[i][1])))
                    x2 = min(width, round(float(xyxy[i][2])))
                    y2 = min(height, round(float(xyxy[i][3])))

                    # Bounding box in normalized resolution-independent coordinates [0.0 - 1.0]
                    norm_x1 = round(float(x1) / width, 4)
                    norm_y1 = round(float(y1) / height, 4)
                    norm_x2 = round(float(x2) / width, 4)
                    norm_y2 = round(float(y2) / height, 4)

                    # Center points
                    center_x = round((x1 + x2) / 2.0)
                    center_y = round((y1 + y2) / 2.0)
                    norm_center_x = round(float(center_x) / width, 4)
                    norm_center_y = round(float(center_y) / height, 4)

                    # Spatial ROI context (Section 9)
                    roi_context = {
                        "configured": False,
                        "inside": False,
                        "zone_code": roi_zone_code or None
                    }

                    if roi_polygon and len(roi_polygon) >= 3:
                        roi_context["configured"] = True
                        roi_context["inside"] = is_point_in_polygon(
                            {"x": norm_center_x, "y": norm_center_y},
                            roi_polygon
                        )

                    det_record = {
                        "class_code": mapped_code,
                        "class_name": active_class_names.get(mapped_code, mapped_code),
                        "raw_model_class": raw_class_name,
                        "confidence": round(confidence, 4),
                        "bbox": {
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2
                        },
                        "bbox_normalized": {
                            "x1": norm_x1,
                            "y1": norm_y1,
                            "x2": norm_x2,
                            "y2": norm_y2
                        },
                        "center": {
                            "x": center_x,
                            "y": center_y
                        },
                        "center_normalized": {
                            "x": norm_center_x,
                            "y": norm_center_y
                        },
                        "roi": roi_context
                    }
                    # Attach active warehouse SKU recognition for stock/bundle/box/pallet items
                    if mapped_code not in ("WORKER", "FORKLIFT", "TRUCK", "LICENSE_PLATE"):
                        sku_meta = self._resolve_sku_for_detection(frame_bgr, x1, y1, x2, y2, mapped_code)
                        if sku_meta:
                            det_record.update(sku_meta)
                    detections.append(det_record)

        t_end = time.perf_counter()

        # Profiling breakdown in milliseconds
        speed_info = getattr(results[0], 'speed', {}) if results else {}
        inf_ms = round(speed_info.get('inference', (t_post_start - t_pre) * 1000), 2)
        pre_ms = round(speed_info.get('preprocess', 0.0), 2)
        post_ms = round(speed_info.get('postprocess', (t_end - t_post_start) * 1000), 2)
        total_ms = round((t_end - t_start) * 1000, 2)

        return {
            "success": True,
            "camera_id": camera_id,
            "timestamp": timestamp_str,
            "frame_width": width,
            "frame_height": height,
            "model_info": {
                "model_name": self.model_name,
                "device": self.active_device,
                "confidence_threshold": threshold
            },
            "performance": {
                "preprocess_ms": pre_ms,
                "inference_ms": inf_ms,
                "postprocess_ms": post_ms,
                "total_ms": total_ms
            },
            "detection_count": len(detections),
            "detections": detections
        }

    def annotate_frame(
        self,
        frame_bgr: np.ndarray,
        detections: List[Dict[str, Any]],
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> np.ndarray:
        """
        Draw bounding boxes, confidence badges, class labels, and ROI overlay
        on a copy of the input frame.
        """
        annotated = frame_bgr.copy()
        h, w = annotated.shape[:2]

        class_colors = {
            "WORKER": (40, 200, 70),     # Vibrant Green
            "TRUCK": (230, 140, 30),     # Amber / Orange
            "BOX": (20, 160, 240),       # Cyan / Sky
            "PALLET": (180, 80, 220),    # Violet
            "FORKLIFT": (50, 100, 230),  # Coral Red
            "BIN": (220, 190, 40)        # Gold / Yellow
        }

        # 1. Draw ROI boundary polygon if provided
        if roi_polygon and len(roi_polygon) >= 3:
            pts = np.array([[int(p['x'] * w), int(p['y'] * h)] for p in roi_polygon], np.int32)
            overlay = annotated.copy()
            cv2.fillPoly(overlay, [pts], (40, 120, 20))
            cv2.addWeighted(overlay, 0.20, annotated, 0.80, 0, annotated)
            cv2.polylines(annotated, [pts], True, (60, 220, 60), 2, cv2.LINE_AA)

            if roi_zone_code:
                rx, ry = pts[0][0], pts[0][1]
                cv2.putText(annotated, f"ROI: {roi_zone_code}", (rx + 6, ry - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 220, 60), 1, cv2.LINE_AA)

        # 2. Draw Each Detection
        for det in detections:
            bbox = det['bbox']
            x1, y1, x2, y2 = bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2']
            cls_code = det.get('class_code', 'OBJ')
            conf = det.get('confidence', 0.0)
            color = class_colors.get(cls_code, (0, 255, 255))

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            cx, cy = det['center']['x'], det['center']['y']
            cv2.circle(annotated, (cx, cy), 4, color, -1)
            cv2.circle(annotated, (cx, cy), 6, (0, 0, 0), 1)

            label_text = f"{cls_code} {conf:.2f}"
            roi_info = det.get('roi', {})
            if roi_info.get('configured'):
                if roi_info.get('inside'):
                    label_text += " [IN ROI]"
                else:
                    label_text += " [OUT]"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.50
            thickness = 1
            (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)

            badge_y1 = max(0, y1 - text_h - 8)
            badge_y2 = y1
            badge_x1 = x1
            badge_x2 = min(w, x1 + text_w + 10)

            cv2.rectangle(annotated, (badge_x1, badge_y1), (badge_x2, badge_y2), color, -1)
            cv2.putText(annotated, label_text, (badge_x1 + 5, badge_y2 - 4),
                        font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

        # 3. Add Telemetry Banner at bottom
        cv2.rectangle(annotated, (0, h - 28), (w, h), (15, 23, 42), -1)
        telemetry_txt = f"MODEL: {self.model_name} | DEVICE: {self.active_device} | DETECTIONS: {len(detections)}"
        cv2.putText(annotated, telemetry_txt, (14, h - 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 200, 220), 1, cv2.LINE_AA)

        return annotated

    def create_synthetic_warehouse_frame(self, scene_type: str = "dock") -> np.ndarray:
        """
        Generate a synthetic warehouse scene frame for testing detection
        when real RTSP camera feeds are offline.
        Includes identifiable shapes (person/worker, truck/vehicle, box/carrier).
        """
        w, h = 1280, 720
        frame = np.zeros((h, w, 3), dtype=np.uint8)

        # Floor and wall perspective
        cv2.rectangle(frame, (0, 0), (w, int(h * 0.45)), (32, 38, 48), -1)
        cv2.rectangle(frame, (0, int(h * 0.45)), (w, h), (45, 52, 64), -1)

        # Floor lane markers
        cv2.line(frame, (int(w * 0.15), h), (int(w * 0.40), int(h * 0.45)), (75, 85, 100), 2)
        cv2.line(frame, (int(w * 0.85), h), (int(w * 0.60), int(h * 0.45)), (75, 85, 100), 2)

        # Dock bay door
        cv2.rectangle(frame, (100, 80), (450, 480), (25, 30, 38), -1)
        cv2.rectangle(frame, (100, 80), (450, 480), (80, 95, 115), 3)

        # Simulated Truck at Dock Bay (left side)
        cv2.rectangle(frame, (130, 180), (420, 470), (55, 65, 80), -1)
        cv2.rectangle(frame, (150, 200), (400, 360), (35, 45, 60), -1)
        cv2.putText(frame, "CARRIER LOGISTICS", (180, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 190, 200), 2)

        # Simulated Worker (center-right)
        cv2.circle(frame, (720, 280), 22, (180, 150, 120), -1)
        cv2.ellipse(frame, (720, 272), (24, 14), 0, 180, 360, (40, 210, 250), -1)
        pts_torso = np.array([[690, 305], [750, 305], [760, 450], [680, 450]], np.int32)
        cv2.fillPoly(frame, [pts_torso], (30, 200, 240))
        cv2.line(frame, (695, 360), (745, 360), (240, 240, 240), 4)
        cv2.rectangle(frame, (690, 450), (715, 580), (60, 50, 40), -1)
        cv2.rectangle(frame, (725, 450), (750, 580), (60, 50, 40), -1)

        # Simulated Box / Pallet bundle (right)
        cv2.rectangle(frame, (860, 380), (1050, 550), (60, 90, 140), -1)
        cv2.rectangle(frame, (860, 380), (1050, 550), (40, 60, 90), 2)
        cv2.line(frame, (860, 465), (1050, 465), (40, 60, 90), 2)
        cv2.putText(frame, "SKANDHA WMS", (880, 430), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

        # Scene Watermark
        cv2.putText(frame, "SYNTHETIC WAREHOUSE TEST SCENE", (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 160, 185), 2)
        return frame

    def _parse_image(self, image_input: Union[np.ndarray, bytes, str]) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Normalize various image inputs (NumPy array, file path, raw bytes) into BGR array.
        """
        if isinstance(image_input, np.ndarray):
            return image_input, None

        if isinstance(image_input, bytes):
            nparr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return None, "Failed to decode image from byte buffer."
            return img, None

        if isinstance(image_input, str):
            if os.path.exists(image_input):
                img = cv2.imread(image_input)
                if img is None:
                    return None, f"Failed to read image from path '{image_input}'."
                return img, None
            else:
                return None, f"Image path '{image_input}' does not exist."

        return None, f"Unsupported image input type: {type(image_input)}"


# Global Singleton Instance
_global_engine: Optional[ObjectDetectionEngine] = None

def get_detection_engine() -> ObjectDetectionEngine:
    """
    Get or initialize the shared ObjectDetectionEngine singleton.
    """
    global _global_engine
    if _global_engine is None:
        _global_engine = ObjectDetectionEngine()
    return _global_engine
