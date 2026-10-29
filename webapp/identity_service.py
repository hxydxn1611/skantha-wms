"""
AI Vision & Tracking Master - Object Identity & Recognition Foundation
Part 7: Modular Identity Recognition Layer for Tracked Objects.

Consumes temporary tracked objects from Part 6 (ByteTrack) and attempts to
identify them using visible warehouse identifiers:
  1. QR Code (OpenCV QRCodeDetector & ZXing-cpp)
  2. 1D Barcodes: Code 128, Code 39, EAN, UPC (ZXing-cpp)
  3. OCR / Printed Label Text (EasyOCR)

Core Architectural Principles:
  - Track ID != Real-World Identity:
      track_id: Temporary visual continuity ID within current camera session (e.g. 17).
      identity.value: Genuine warehouse identifier detected from visual evidence (e.g. "B104").
  - Statuses:
      IDENTIFIED: Valid identifier recognized.
      UNIDENTIFIED: No valid identifier found (NEVER invent an identity).
      CONFLICT: Multiple or inconsistent identifiers detected (exposed in candidates).
  - Repeated-Read Stability: Confirmed identities remain stable across frames.
    Conflicting observations are flagged rather than silently overwriting.
  - Camera Isolation: CAM-001 tracks & identities are strictly isolated from CAM-002.
  - Zero DB Schema Changes: Identity state remains in-memory per camera session.
  - Non-Goals: NO cross-camera matching, Re-ID, face/ANPR, events, or WMS updates.
"""

import os
import time
import uuid
import base64
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

import cv2
import numpy as np

# Import detection and tracking services from Parts 5 & 6
from detection_service import (
    get_detection_engine,
    is_point_in_polygon,
    FALLBACK_CLASS_NAMES
)
from tracking_service import (
    get_tracking_service,
    MultiObjectTrackingService
)

logger = logging.getLogger(__name__)

# Check optional dependencies for decoders
try:
    import zxingcpp
    ZXING_AVAILABLE = True
except ImportError:
    zxingcpp = None
    ZXING_AVAILABLE = False
    logger.warning("zxingcpp library not installed. 1D barcode decoding limited.")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    easyocr = None
    EASYOCR_AVAILABLE = False
    logger.warning("easyocr library not installed. OCR text recognition limited.")

try:
    import torch
    TORCH_CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    TORCH_CUDA_AVAILABLE = False


# ============================================================================
# 1. BARCODE & QR CODE DECODER ADAPTER
# ============================================================================
class BarcodeQRDecoder:
    """
    Modular decoder for 1D barcodes and 2D QR codes using ZXing-cpp and
    OpenCV QRCodeDetector. Performs genuine pattern decoding without mock data.
    """

    def __init__(self):
        self.opencv_qr = cv2.QRCodeDetector()
        self.has_zxing = ZXING_AVAILABLE
        logger.info(f"BarcodeQRDecoder initialized. ZXing: {self.has_zxing}, OpenCV QR: True")

    def decode(self, crop_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """
        Scan a cropped image region for barcodes and QR codes.
        Returns a list of candidate dictionaries.
        """
        if crop_bgr is None or crop_bgr.size == 0 or crop_bgr.shape[0] < 10 or crop_bgr.shape[1] < 10:
            return []

        candidates: List[Dict[str, Any]] = []
        seen_values = set()

        # 1. Primary decoder: ZXing-cpp (handles both 1D Barcodes and 2D QR/DataMatrix)
        if self.has_zxing and zxingcpp is not None:
            try:
                # Convert BGR to RGB for ZXing
                crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                results = zxingcpp.read_barcodes(crop_rgb)
                for res in results:
                    text_val = (res.text or "").strip()
                    if text_val and text_val not in seen_values:
                        fmt_str = str(res.format).replace("BarcodeFormat.", "")
                        is_qr = "QR" in fmt_str.upper()
                        source_type = "QR" if is_qr else "BARCODE"
                        
                        # Barcodes/QRs have built-in checksum verification (Reed-Solomon / mod-103)
                        confidence = 0.98 if getattr(res, "valid", True) else 0.85
                        candidates.append({
                            "value": text_val,
                            "source": source_type,
                            "format": fmt_str,
                            "confidence": round(confidence, 4)
                        })
                        seen_values.add(text_val)
            except Exception as e:
                logger.debug(f"ZXing decode error on crop: {e}")

        # 2. Secondary fallback: OpenCV QRCodeDetector (if no QR was decoded yet)
        if not any(c.get("source") == "QR" for c in candidates):
            try:
                val, points, _ = self.opencv_qr.detectAndDecode(crop_bgr)
                val_clean = (val or "").strip()
                if val_clean and val_clean not in seen_values:
                    candidates.append({
                        "value": val_clean,
                        "source": "QR",
                        "format": "QR Code",
                        "confidence": 0.96
                    })
                    seen_values.add(val_clean)
            except Exception as e:
                logger.debug(f"OpenCV QR decode error: {e}")

        return candidates


# ============================================================================
# 2. OCR TEXT RECOGNITION ADAPTER
# ============================================================================
class OCRAdapter:
    """
    Modular OCR adapter wrapping EasyOCR for visible printed text and label tags.
    Extracts text bounding boxes and confidence scores locally on CPU or GPU.
    """

    def __init__(self, use_gpu: Optional[bool] = None):
        self._reader = None
        self.use_gpu = TORCH_CUDA_AVAILABLE if use_gpu is None else use_gpu
        self.is_available = EASYOCR_AVAILABLE

    def _get_reader(self):
        """Lazy initialization of EasyOCR reader to optimize cold-start latency."""
        if self._reader is None and self.is_available and easyocr is not None:
            try:
                logger.info(f"Initializing EasyOCR reader (GPU={self.use_gpu})...")
                self._reader = easyocr.Reader(['en'], gpu=self.use_gpu, download_enabled=False, verbose=False)
            except Exception as e:
                logger.error(f"Failed to initialize EasyOCR on GPU={self.use_gpu}: {e}. Retrying CPU...")
                try:
                    self._reader = easyocr.Reader(['en'], gpu=False, download_enabled=False, verbose=False)
                except Exception as e2:
                    logger.error(f"EasyOCR CPU initialization failed: {e2}")
                    self.is_available = False
        return self._reader

    def recognize(self, crop_bgr: np.ndarray, min_confidence: float = 0.40) -> List[Dict[str, Any]]:
        """
        Execute OCR text recognition on cropped object region.
        Applies filtering for warehouse identifier candidate formats.
        """
        if not self.is_available or crop_bgr is None or crop_bgr.size == 0:
            return []

        reader = self._get_reader()
        if reader is None:
            return []

        candidates: List[Dict[str, Any]] = []
        try:
            # Run text detection and recognition on image array
            results = reader.readtext(crop_bgr)

            for bbox_pts, text_raw, conf in results:
                conf_val = float(conf)
                if conf_val < min_confidence:
                    continue

                text_clean = str(text_raw).strip()

                # Filter out single-character background noise; warehouse IDs have >= 2 chars
                if len(text_clean) < 2:
                    continue

                # Must contain alphanumeric characters (avoid pure punctuation symbols)
                if not any(c.isalnum() for c in text_clean):
                    continue

                # Reject short pure lowercase words (e.g. 'the', 'in') unless alphanumeric
                if text_clean.islower() and len(text_clean) < 3 and not any(c.isdigit() for c in text_clean):
                    continue

                candidates.append({
                    "value": text_clean,
                    "source": "OCR",
                    "format": "Printed Label",
                    "confidence": round(conf_val, 4)
                })
        except Exception as e:
            logger.debug(f"OCR recognition error on crop: {e}")

        return candidates


# ============================================================================
# 3. TRACK-LEVEL IDENTITY STATE & REPEATED-READ STABILITY
# ============================================================================
class TrackIdentityState:
    """
    In-memory identity state for a specific Track ID within a camera session.
    Maintains repeated-read stability, prevents silent overwrites, and tracks
    candidate conflicts across consecutive video frames.
    """

    def __init__(self, track_id: int):
        self.track_id = track_id
        self.status = "UNIDENTIFIED"  # "IDENTIFIED", "UNIDENTIFIED", "AMBIGUOUS", "CONFLICT"
        self.value: Optional[str] = None
        self.source: Optional[str] = None
        self.format: Optional[str] = None
        self.confidence: float = 0.0
        self.read_count: int = 0
        self.first_identified_frame: Optional[int] = None
        self.last_identified_frame: Optional[int] = None
        self.candidates: List[Dict[str, Any]] = []
        self.raw_evidence: Dict[str, Any] = {
            "barcode_or_qr": None,
            "barcode_format": None,
            "ocr_text": None,
            "source_camera": None,
            "timestamp": None,
            "confidence": 0.0,
            "status": "UNIDENTIFIED",
            "candidates": []
        }

    def _update_raw_evidence(
        self,
        candidates: List[Dict[str, Any]],
        camera_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ):
        bc_qrs = [c for c in candidates if c.get("source") in ("QR", "BARCODE")]
        ocrs = [c for c in candidates if c.get("source") == "OCR"]
        
        bc_val = bc_qrs[0]["value"] if bc_qrs else None
        bc_fmt = bc_qrs[0].get("format") if bc_qrs else None
        ocr_vals = [c["value"] for c in ocrs] if ocrs else None

        self.raw_evidence = {
            "barcode_or_qr": bc_val,
            "barcode_format": bc_fmt,
            "ocr_text": ocr_vals,
            "source_camera": camera_id or self.raw_evidence.get("source_camera") or "CAM-001",
            "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "confidence": round(float(self.confidence), 4),
            "status": self.status,
            "candidates": [dict(c) for c in candidates]
        }

    def _filter_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter raw candidate detections to distinguish genuine identifiers from low-confidence noise."""
        if not candidates:
            return []

        # 1. Look for high-confidence Barcodes / QRs (validated optical symbologies)
        bc_qrs = [c for c in candidates if c.get("source") in ("QR", "BARCODE") and c.get("confidence", 0) >= 0.80]
        # 2. Look for strong OCR candidates (conf >= 0.70)
        strong_ocrs = [c for c in candidates if c.get("source") == "OCR" and c.get("confidence", 0) >= 0.70]

        if bc_qrs:
            # If a high-confidence OCR directly contradicts the Barcode/QR (e.g. B104 vs B109)
            conflicts = [c for c in strong_ocrs if c["value"] != bc_qrs[0]["value"]]
            if conflicts:
                return bc_qrs + conflicts
            # Otherwise Barcode/QR takes precedence over background OCR text
            return bc_qrs

        if strong_ocrs:
            max_c = max(c["confidence"] for c in strong_ocrs)
            # Retain OCR candidates close to the maximum confidence score
            top_ocrs = [c for c in strong_ocrs if c["confidence"] >= max_c - 0.15]
            return top_ocrs

        # Fallback to top-scoring candidate if no strong candidate
        top_cand = max(candidates, key=lambda c: c.get("confidence", 0))
        return [top_cand] if top_cand.get("confidence", 0) >= 0.50 else []

    def update(
        self,
        new_candidates: List[Dict[str, Any]],
        frame_index: int,
        camera_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ):
        """
        Update identity state based on newly recognized visual candidates in current frame.
        Distinguishes: IDENTIFIED, UNIDENTIFIED, AMBIGUOUS, CONFLICT.
        Never guesses a SKU from visual appearance alone.
        Preserves raw evidence for traceability and auditing.
        """
        # 0. Check for explicitly ambiguous candidates
        if any(c.get("status") == "AMBIGUOUS" or c.get("is_ambiguous") for c in new_candidates):
            self.status = "AMBIGUOUS"
            self.value = None
            self.source = None
            self.format = None
            self.confidence = 0.0
            self.candidates = new_candidates
            self.last_identified_frame = frame_index
            self._update_raw_evidence(new_candidates, camera_id, timestamp)
            return

        filtered_candidates = self._filter_candidates(new_candidates)

        if not filtered_candidates:
            # If no identifier found in current frame, but track was previously confirmed
            # as IDENTIFIED, retain its stable identity (handles momentary blur or angle changes).
            if self.status == "IDENTIFIED" and self.value:
                self._update_raw_evidence(new_candidates, camera_id, timestamp)
                return
            if self.status not in ("CONFLICT", "AMBIGUOUS"):
                self.status = "UNIDENTIFIED"
                self.value = None
                self.source = None
                self.format = None
                self.confidence = 0.0
            self._update_raw_evidence(new_candidates, camera_id, timestamp)
            return

        # 1. Separate Barcode/QR vs OCR candidates
        bc_qrs = [c for c in filtered_candidates if c.get("source") in ("QR", "BARCODE")]
        ocr_cands = [c for c in filtered_candidates if c.get("source") == "OCR"]

        # Check internal barcode conflict
        if bc_qrs:
            unique_bc_vals = {c["value"] for c in bc_qrs}
            if len(unique_bc_vals) > 1:
                self.status = "CONFLICT"
                self.value = None
                self.source = None
                self.format = None
                self.confidence = 0.0
                self.candidates = filtered_candidates
                self.last_identified_frame = frame_index
                self._update_raw_evidence(new_candidates, camera_id, timestamp)
                return

            # Check if strong OCR directly contradicts Barcode/QR
            top_bc = max(bc_qrs, key=lambda c: c.get("confidence", 0))
            contradicting_ocr = [c for c in ocr_cands if c.get("confidence", 0) >= 0.70 and c["value"] != top_bc["value"]]
            if contradicting_ocr:
                self.status = "CONFLICT"
                self.value = None
                self.source = None
                self.format = None
                self.confidence = 0.0
                self.candidates = [top_bc] + contradicting_ocr
                self.last_identified_frame = frame_index
                self._update_raw_evidence(new_candidates, camera_id, timestamp)
                return

            # Barcode/QR wins and OCR supports
            cand = top_bc
            if any(c["value"] == top_bc["value"] for c in ocr_cands):
                cand["confidence"] = max(cand["confidence"], 0.99)
        elif ocr_cands:
            # Only OCR candidates present: check for ambiguity among competing candidates
            distinct_ocrs = []
            seen = set()
            for oc in sorted(ocr_cands, key=lambda c: c.get("confidence", 0), reverse=True):
                if oc["value"] not in seen:
                    seen.add(oc["value"])
                    distinct_ocrs.append(oc)

            if len(distinct_ocrs) >= 2:
                # If top two candidates have close confidence scores (< 0.15 delta)
                if abs(distinct_ocrs[0]["confidence"] - distinct_ocrs[1]["confidence"]) < 0.15:
                    self.status = "AMBIGUOUS"
                    self.value = None
                    self.source = "OCR"
                    self.format = distinct_ocrs[0].get("format")
                    self.confidence = 0.0
                    self.candidates = distinct_ocrs
                    self.last_identified_frame = frame_index
                    self._update_raw_evidence(new_candidates, camera_id, timestamp)
                    return

            cand = distinct_ocrs[0]
        else:
            cand = filtered_candidates[0]

        cand_val = cand["value"]

        # 3. Check stability against previous frames
        if self.status == "IDENTIFIED" and self.value:
            if self.value == cand_val:
                # Confirmed repeated read of same identity -> Stabilize
                self.read_count += 1
                self.confidence = max(self.confidence, cand["confidence"])
                self.last_identified_frame = frame_index
            else:
                # Contradicting observation in later frame: DO NOT silently overwrite!
                self.status = "CONFLICT"
                self.candidates = [
                    {
                        "value": self.value,
                        "source": self.source,
                        "format": self.format,
                        "confidence": self.confidence,
                        "note": "Previously confirmed identity"
                    },
                    {
                        "value": cand_val,
                        "source": cand["source"],
                        "format": cand.get("format"),
                        "confidence": cand["confidence"],
                        "note": "New contradictory observation"
                    }
                ]
                self.value = None
                self.source = None
                self.format = None
                self.confidence = 0.0
                self.last_identified_frame = frame_index
            self._update_raw_evidence(new_candidates, camera_id, timestamp)
            return

        if self.status == "CONFLICT":
            # If already in conflict, record candidate
            if not any(c.get("value") == cand_val for c in self.candidates):
                self.candidates.append(cand)
            self._update_raw_evidence(new_candidates, camera_id, timestamp)
            return

        # 4. First successful identification
        self.status = "IDENTIFIED"
        self.value = cand_val
        self.source = cand["source"]
        self.format = cand.get("format")
        self.confidence = cand["confidence"]
        self.read_count = 1
        self.first_identified_frame = frame_index
        self.last_identified_frame = frame_index
        self.candidates = []
        self._update_raw_evidence(new_candidates, camera_id, timestamp)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize identity state to JSON-compatible dictionary."""
        return {
            "status": self.status,
            "value": self.value,
            "source": self.source,
            "format": self.format,
            "confidence": round(float(self.confidence), 4),
            "read_count": self.read_count,
            "first_identified_frame": self.first_identified_frame,
            "last_identified_frame": self.last_identified_frame,
            "candidates": self.candidates,
            "raw_evidence": self.raw_evidence
        }


# ============================================================================
# 3.5 SPATIAL LOGISTICS ANALYZER (WARLOG ENGINE LAYER)
# ============================================================================
class SpatialAnalyzer:
    """
    Analyzes spatial relationships between tracked objects to determine logistics state.
    E.g., Parts inside Boxes, Parts on Pallets, Bundles.
    """
    @staticmethod
    def calculate_intersection_area(box1: Dict[str, float], box2: Dict[str, float]) -> float:
        ix1 = max(box1.get('x1', 0), box2.get('x1', 0))
        iy1 = max(box1.get('y1', 0), box2.get('y1', 0))
        ix2 = min(box1.get('x2', 0), box2.get('x2', 0))
        iy2 = min(box1.get('y2', 0), box2.get('y2', 0))
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        return iw * ih

    @staticmethod
    def calculate_area(box: Dict[str, float]) -> float:
        return max(0, box.get('x2', 0) - box.get('x1', 0)) * max(0, box.get('y2', 0) - box.get('y1', 0))

    @staticmethod
    def analyze_storage_state(tracks: List[Dict[str, Any]]) -> None:
        """
        Enhances track dictionaries in-place with a 'storage_state' attribute based on spatial overlap.
        """
        logistics_classes = {"PALLET", "BOX", "CRATE", "TOTE"}
        containers = [t for t in tracks if t.get("class_code", "").upper() in logistics_classes]
        parts = [t for t in tracks if t.get("class_code", "").upper() not in logistics_classes]

        for part in parts:
            part_bbox = part.get("bbox", {})
            part_area = SpatialAnalyzer.calculate_area(part_bbox)
            if part_area == 0:
                part["storage_state"] = "INDIVIDUAL"
                continue

            best_state = "INDIVIDUAL"
            best_container = None
            max_coverage = 0.0

            for container in containers:
                container_bbox = container.get("bbox", {})
                inter_area = SpatialAnalyzer.calculate_intersection_area(part_bbox, container_bbox)
                coverage = inter_area / part_area

                if coverage > 0.5 and coverage > max_coverage:
                    max_coverage = coverage
                    ctype = container.get("class_code", "").upper()
                    if ctype == "PALLET":
                        best_state = "PALLETIZED"
                    else:
                        best_state = f"IN_{ctype}"
                    best_container = container.get("track_id")

            part["storage_state"] = best_state
            part["storage_container_id"] = best_container
            
            if best_state == "INDIVIDUAL":
                bundle_count = sum(1 for p in parts if p != part and p.get("class_code") == part.get("class_code") and 
                                   (SpatialAnalyzer.calculate_intersection_area(part_bbox, p.get("bbox", {})) / part_area) > 0.1)
                if bundle_count > 0:
                    part["storage_state"] = "BUNDLE"

        for container in containers:
            container["storage_state"] = "CONTAINER"


# ============================================================================
# 4. CAMERA-SPECIFIC IDENTITY SESSION
# ============================================================================
class CameraIdentitySession:
    """
    Per-camera identity session ensuring complete isolation between camera nodes
    (e.g. CAM-001 track identities are strictly separated from CAM-002).
    """

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.session_id = f"ident_{camera_id}_{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.tracks_identity: Dict[int, TrackIdentityState] = {}

    def get_track_identity(self, track_id: int) -> TrackIdentityState:
        """Get or initialize in-memory identity state for a specific Track ID."""
        if track_id not in self.tracks_identity:
            self.tracks_identity[track_id] = TrackIdentityState(track_id=track_id)
        return self.tracks_identity[track_id]

    def reset(self):
        """Reset camera identity session and clear all temporary track identities."""
        self.session_id = f"ident_{self.camera_id}_{uuid.uuid4().hex[:8]}"
        self.tracks_identity.clear()
        logger.info(f"Identity session for camera '{self.camera_id}' reset.")


# ============================================================================
# 5. MULTI-OBJECT IDENTITY SERVICE (SINGLETON ENGINE)
# ============================================================================
class MultiObjectIdentityService:
    """
    Core Part 7 Service:
    Coordinates YOLO Object Detection (Part 5), ByteTrack Multi-Object Tracking (Part 6),
    and Barcode/QR/OCR Identity Recognition into an enriched perception pipeline.
    """

    def __init__(self):
        self.tracking_service: MultiObjectTrackingService = get_tracking_service()
        self.detection_engine = get_detection_engine()
        self.barcode_decoder = BarcodeQRDecoder()
        self.ocr_adapter = OCRAdapter()
        self.camera_sessions: Dict[str, CameraIdentitySession] = {}
        logger.info("MultiObjectIdentityService initialized successfully.")

    def get_session(self, camera_id: str) -> CameraIdentitySession:
        """Retrieve or create an isolated identity session for a camera."""
        cam_key = str(camera_id).strip().upper() if camera_id else "DEFAULT"
        if cam_key not in self.camera_sessions:
            self.camera_sessions[cam_key] = CameraIdentitySession(camera_id=cam_key)
        return self.camera_sessions[cam_key]

    def reset_session(self, camera_id: str) -> bool:
        """Reset identity state for a single camera."""
        cam_key = str(camera_id).strip().upper() if camera_id else "DEFAULT"
        if cam_key in self.camera_sessions:
            self.camera_sessions[cam_key].reset()
            # Also reset corresponding tracking session to restart track IDs cleanly
            self.tracking_service.reset_session(cam_key)
            return True
        return False

    def reset_all(self):
        """Reset all camera identity sessions."""
        for session in self.camera_sessions.values():
            session.reset()
        self.tracking_service.reset_all()

    def get_status(self) -> Dict[str, Any]:
        """Return operational status of identity recognition components and sessions."""
        sessions_summary = []
        total_identified = 0
        total_conflicts = 0
        total_tracks = 0

        for cam_id, sess in self.camera_sessions.items():
            identified = sum(1 for t in sess.tracks_identity.values() if t.status == "IDENTIFIED")
            conflicts = sum(1 for t in sess.tracks_identity.values() if t.status == "CONFLICT")
            total = len(sess.tracks_identity)
            total_identified += identified
            total_conflicts += conflicts
            total_tracks += total

            sessions_summary.append({
                "camera_id": cam_id,
                "session_id": sess.session_id,
                "tracks_count": total,
                "identified_count": identified,
                "conflict_count": conflicts,
                "created_at": sess.created_at
            })

        return {
            "success": True,
            "engine": "Part 7 - Object Identity & Recognition Foundation",
            "decoders": {
                "barcode_qr": {
                    "available": True,
                    "zxing_cpp": self.barcode_decoder.has_zxing,
                    "opencv_qr": True
                },
                "ocr": {
                    "available": self.ocr_adapter.is_available,
                    "engine": "EasyOCR 1.7.2",
                    "device": "cuda:0" if self.ocr_adapter.use_gpu else "cpu"
                }
            },
            "stats": {
                "active_sessions": len(self.camera_sessions),
                "total_tracks": total_tracks,
                "total_identified": total_identified,
                "total_conflicts": total_conflicts
            },
            "sessions": sessions_summary
        }

    def identify_tracks(
        self,
        frame_bgr: np.ndarray,
        tracks: List[Dict[str, Any]],
        camera_id: str = "CAM-001",
        frame_index: int = 1,
        enable_barcode_qr: bool = True,
        enable_ocr: bool = True,
        crop_padding: float = 0.05,
        enable_throttling: bool = False
    ) -> Tuple[List[Dict[str, Any]], float, float]:
        """
        Enrich a list of Part 6 tracked objects with visual identity recognition results.
        Returns: (enriched_tracks, barcode_qr_ms, ocr_ms)
        """
        if not tracks or frame_bgr is None or frame_bgr.size == 0:
            return [], 0.0, 0.0

        session = self.get_session(camera_id)
        h, w = frame_bgr.shape[:2]

        total_bc_ms = 0.0
        total_ocr_ms = 0.0

        for t in tracks:
            track_id = int(t.get("track_id", 0))
            bbox = t.get("bbox", {})
            x1 = max(0, int(bbox.get("x1", 0)))
            y1 = max(0, int(bbox.get("y1", 0)))
            x2 = min(w, int(bbox.get("x2", w)))
            y2 = min(h, int(bbox.get("y2", h)))

            # Apply configurable crop padding
            box_w = max(1, x2 - x1)
            box_h = max(1, y2 - y1)
            pad_x = int(round(box_w * crop_padding))
            pad_y = int(round(box_h * crop_padding))

            crop_x1 = max(0, x1 - pad_x)
            crop_y1 = max(0, y1 - pad_y)
            crop_x2 = min(w, x2 + pad_x)
            crop_y2 = min(h, y2 + pad_y)

            crop = frame_bgr[crop_y1:crop_y2, crop_x1:crop_x2]

            cls_code = t.get("class_code", "").upper()
            enable_bc_local = enable_barcode_qr
            enable_ocr_local = enable_ocr
            
            if cls_code in ["WORKER", "PERSON"]:
                enable_bc_local = False
                enable_ocr_local = False
            elif cls_code == "LICENSE_PLATE":
                enable_bc_local = False

            track_identity = session.get_track_identity(track_id)
            candidates: List[Dict[str, Any]] = []

            # 1. Barcode & QR code scanning (Throttle to improve speed if enabled)
            throttle_bc = (not enable_throttling) or ((frame_index % 3 == 0) if not track_identity.value else (frame_index % 10 == 0))
            if enable_bc_local and crop.size > 0 and throttle_bc:
                t_bc_start = time.perf_counter()
                bc_results = self.barcode_decoder.decode(crop)
                total_bc_ms += (time.perf_counter() - t_bc_start) * 1000
                candidates.extend(bc_results)

            # 2. OCR text recognition (Throttle heavily if enabled)
            throttle_ocr = (not enable_throttling) or ((frame_index % 5 == 0) if not track_identity.value else (frame_index % 15 == 0))
            if cls_code == "LICENSE_PLATE" and enable_throttling:
                throttle_ocr = (frame_index % 2 == 0)
                
            if enable_ocr_local and crop.size > 0 and throttle_ocr:
                t_ocr_start = time.perf_counter()
                ocr_results = self.ocr_adapter.recognize(crop, min_confidence=0.40)
                total_ocr_ms += (time.perf_counter() - t_ocr_start) * 1000
                candidates.extend(ocr_results)

            # 3. Update track-level in-memory identity state
            track_identity.update(
                new_candidates=candidates,
                frame_index=frame_index,
                camera_id=camera_id,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            # 4. Attach identity structure to track output
            t["identity"] = track_identity.to_dict()

        return tracks, round(total_bc_ms, 2), round(total_ocr_ms, 2)

    def process_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        enable_barcode_qr: bool = True,
        enable_ocr: bool = True,
        crop_padding: float = 0.05,
        enable_throttling: bool = False
    ) -> Dict[str, Any]:
        """
        End-to-End Part 7 Pipeline:
        Frame -> Part 5 Detection -> Part 6 ByteTrack -> Part 7 Identity Recognition -> Visual Annotation.
        """
        t_total_start = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Parse raw image input
        raw_frame, parse_err = self.detection_engine._parse_image(frame_input)
        if parse_err or raw_frame is None:
            return {
                "success": False,
                "error": parse_err or "Invalid frame input.",
                "camera_id": camera_id,
                "tracks": [],
                "active_track_count": 0
            }

        w = int(raw_frame.shape[1])
        h = int(raw_frame.shape[0])

        # Step 1: Part 5 Object Detection
        det_result = self.detection_engine.detect(
            image_input=raw_frame,
            camera_id=camera_id,
            conf_threshold=conf_threshold,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )
        if not det_result.get("success"):
            return {
                "success": False,
                "error": det_result.get("error", "Detection engine failure"),
                "camera_id": camera_id,
                "tracks": [],
                "active_track_count": 0
            }

        detections = det_result.get("detections", [])
        det_ms = det_result.get("performance", {}).get("inference_ms", 0.0)

        # Step 2: Part 6 ByteTrack Multi-Object Tracking
        tracking_session = self.tracking_service.get_session(camera_id)
        t_track_start = time.perf_counter()
        tracks = tracking_session.update(
            detections=detections,
            frame_width=w,
            frame_height=h,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )
        track_ms = round((time.perf_counter() - t_track_start) * 1000, 2)

        # Step 3: Part 7 Identity Recognition
        enriched_tracks, bc_ms, ocr_ms = self.identify_tracks(
            frame_bgr=raw_frame,
            tracks=tracks,
            camera_id=camera_id,
            frame_index=tracking_session.frame_index,
            enable_barcode_qr=enable_barcode_qr,
            enable_ocr=enable_ocr,
            crop_padding=crop_padding,
            enable_throttling=enable_throttling
        )
        ident_ms = round(bc_ms + ocr_ms, 2)
        
        # Step 3.5: Spatial Storage Analysis (WARLOG Engine)
        SpatialAnalyzer.analyze_storage_state(enriched_tracks)
        
        total_ms = round((time.perf_counter() - t_total_start) * 1000, 2)

        # Step 4: Render Visual Annotation with Identity Overlay
        annotated_bgr = self.annotate_identities(
            frame_bgr=raw_frame,
            tracks=enriched_tracks,
            camera_id=camera_id,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )

        _, buf = cv2.imencode('.jpg', annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": tracking_session.session_id,
            "frame_index": tracking_session.frame_index,
            "timestamp": timestamp_str,
            "frame_width": w,
            "frame_height": h,
            "active_track_count": len(enriched_tracks),
            "detection_count": len(detections),
            "identified_count": sum(1 for t in enriched_tracks if t.get("identity", {}).get("status") == "IDENTIFIED"),
            "conflict_count": sum(1 for t in enriched_tracks if t.get("identity", {}).get("status") == "CONFLICT"),
            "performance": {
                "detection_ms": det_ms,
                "tracking_ms": track_ms,
                "barcode_qr_ms": bc_ms,
                "ocr_ms": ocr_ms,
                "identity_ms": ident_ms,
                "total_ms": total_ms
            },
            "detections": detections,
            "tracks": enriched_tracks,
            "annotated_image_url": annotated_b64
        }

    def run_sequence(
        self,
        camera_id: str = "CAM-001",
        num_frames: int = 5,
        sample_scene: str = "identity_qr_b104.jpg",
        conf_threshold: float = 0.25,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a controlled multi-frame sequence to verify track & identity persistence
        across motion without background RTSP streaming.
        """
        scene_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", sample_scene)
        base = cv2.imread(scene_path)
        if base is None:
            # Fallback to test scene generator
            base = cv2.imread(os.path.join(os.path.dirname(__file__), "static", "test_scenes", "warehouse_carrier.jpg"))

        if base is None:
            return {"success": False, "error": f"Base sample scene '{sample_scene}' unavailable."}

        step_results = []
        last_frame_annotated_b64 = None

        for step in range(num_frames):
            # Apply smooth horizontal movement for realistic motion tracking
            dx = int(round(step * 15))
            frame = np.roll(base, dx, axis=1)
            if dx > 0:
                frame[:, :dx] = base[:, :1]

            res = self.process_frame(
                frame_input=frame,
                camera_id=camera_id,
                conf_threshold=conf_threshold,
                roi_polygon=roi_polygon,
                roi_zone_code=roi_zone_code
            )
            step_results.append({
                "step": step + 1,
                "frame_index": res.get("frame_index"),
                "active_track_count": res.get("active_track_count"),
                "identified_count": res.get("identified_count"),
                "performance": res.get("performance"),
                "tracks": res.get("tracks", [])
            })
            last_frame_annotated_b64 = res.get("annotated_image_url")

        tracking_sess = self.tracking_service.get_session(camera_id)
        latest_tracks = step_results[-1]["tracks"] if step_results else []

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": tracking_sess.session_id,
            "num_frames": num_frames,
            "step_results": step_results,
            "active_tracks": latest_tracks,
            "final_annotated_image_url": last_frame_annotated_b64
        }

    def annotate_identities(
        self,
        frame_bgr: np.ndarray,
        tracks: List[Dict[str, Any]],
        camera_id: str = "CAM-001",
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> np.ndarray:
        """
        Render visual bounding boxes, Track IDs, and real-world warehouse identity tags.
        Color Coding:
          - Emerald Green: IDENTIFIED
          - Gray / Blue: UNIDENTIFIED
          - Amber / Orange: CONFLICT
        """
        annotated = frame_bgr.copy()
        h, w = annotated.shape[:2]

        # 1. Draw ROI polygon boundary if configured
        if roi_polygon and len(roi_polygon) >= 3:
            pts = np.array([[int(p.get('x', 0) * w), int(p.get('y', 0) * h)] for p in roi_polygon], np.int32)
            cv2.polylines(annotated, [pts], isClosed=True, color=(147, 51, 234), thickness=2, lineType=cv2.LINE_AA)
            if pts.shape[0] > 0:
                cv2.putText(annotated, f"ROI: {roi_zone_code or 'ZONE'}", (pts[0][0], max(20, pts[0][1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (147, 51, 234), 1, cv2.LINE_AA)

        # 2. Draw tracks and identity tags
        for t in tracks:
            tid = t.get("track_id", 0)
            cls_code = t.get("class_code", "BOX")
            bbox = t.get("bbox", {})
            x1, y1 = int(bbox.get("x1", 0)), int(bbox.get("y1", 0))
            x2, y2 = int(bbox.get("x2", 0)), int(bbox.get("y2", 0))

            ident = t.get("identity", {})
            status = ident.get("status", "UNIDENTIFIED")
            val = ident.get("value")
            source = ident.get("source")
            conf = ident.get("confidence", 0.0)

            # Determine color by identity status
            if status == "IDENTIFIED":
                box_color = (34, 197, 94)      # Emerald Green
                status_label = f"ID: {val} [{source}] {int(conf * 100)}%"
            elif status == "AMBIGUOUS":
                box_color = (0, 165, 255)      # Orange
                status_label = f"ID: AMBIGUOUS ({len(ident.get('candidates', []))} reads)"
            elif status == "CONFLICT":
                box_color = (68, 68, 239)      # Bright Red
                status_label = f"ID: CONFLICT ({len(ident.get('candidates', []))} candidates)"
            else:
                box_color = (180, 180, 180)    # Neutral Gray / Blue
                status_label = "ID: UNIDENTIFIED"

            # Draw bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2, cv2.LINE_AA)

            # Draw center point
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            cv2.circle(annotated, (cx, cy), 4, box_color, -1)

            # Build multi-line pill header:
            # Line 1: Track #17 | TRUCK (TEMPORARY VISUAL TRACK)
            # Line 2: ID: B104 [BARCODE] 98% (REAL-WORLD IDENTIFIER)
            storage = t.get("storage_state", "")
            storage_str = f" [{storage}]" if storage and storage not in ["CONTAINER", "INDIVIDUAL"] else ""
            line1 = f"Track #{tid} | {cls_code}{storage_str}"
            line2 = status_label

            font = cv2.FONT_HERSHEY_SIMPLEX
            f_scale = 0.44
            thickness = 1

            (w1, h1), _ = cv2.getTextSize(line1, font, f_scale, thickness)
            (w2, h2), _ = cv2.getTextSize(line2, font, f_scale, thickness)
            pill_w = max(w1, w2) + 14
            pill_h = h1 + h2 + 16

            badge_y1 = max(0, y1 - pill_h - 4)
            badge_y2 = y1
            badge_x1 = x1
            badge_x2 = min(w, x1 + pill_w)

            # Draw pill background
            cv2.rectangle(annotated, (badge_x1, badge_y1), (badge_x2, badge_y2), (15, 23, 42), -1)
            cv2.rectangle(annotated, (badge_x1, badge_y1), (badge_x2, badge_y2), box_color, 1)

            # Draw Line 1 (Track ID & Class)
            cv2.putText(annotated, line1, (badge_x1 + 6, badge_y1 + h1 + 4),
                        font, f_scale, (255, 255, 255), thickness, cv2.LINE_AA)
            # Draw Line 2 (Real Identity)
            cv2.putText(annotated, line2, (badge_x1 + 6, badge_y1 + h1 + h2 + 10),
                        font, f_scale, box_color, thickness, cv2.LINE_AA)

        # 3. Telemetry footer strip
        cv2.rectangle(annotated, (0, h - 28), (w, h), (15, 23, 42), -1)
        tracking_sess = self.tracking_service.get_session(camera_id)
        stat_text = (
            f"{camera_id} | Session: {tracking_sess.session_id[-8:]} | "
            f"Frame #{tracking_sess.frame_index} | Tracks: {len(tracks)} | "
            f"Identified: {sum(1 for t in tracks if t.get('identity', {}).get('status') == 'IDENTIFIED')}"
        )
        cv2.putText(annotated, stat_text, (10, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 210, 220), 1, cv2.LINE_AA)

        return annotated


# Global Singleton Service
_global_identity_service: Optional[MultiObjectIdentityService] = None


def get_identity_service() -> MultiObjectIdentityService:
    """Retrieve or lazily initialize the singleton MultiObjectIdentityService."""
    global _global_identity_service
    if _global_identity_service is None:
        _global_identity_service = MultiObjectIdentityService()
    return _global_identity_service
