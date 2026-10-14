"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 15 — Unified W.A.R.L.O.G. Vision Runtime & Processing Orchestrator

Connects physical and simulated camera feeds to the canonical Parts 5–14 perception pipeline:
Detection -> Tracking -> Identity Recognition -> Master-Data Validation ->
Spatial-Temporal Associations -> Movement Events -> Material Traceability.

Key Principles:
1. Canonical AI Pipeline: Reuses Parts 5–14 singletons. No duplicate inference pipelines.
2. Legacy ai_engine.py Subordination: Frame capture responsibilities are unified under the runtime.
   Uncoordinated YOLO-World / tripwire logic is cleanly bypassed.
3. Isolated Camera Sessions: Each camera operates independently. Failure in CAM-001 never stops CAM-002.
4. Thread-Safe Bounded Queues: Drop-oldest policy prevents memory leaks and ensures processing freshness.
5. Controlled Processing FPS: Respects vision_camera_configs.processing_fps (no unbounded spinning).
6. Zero Database Writes: Runtime state remains 100% in-memory. Database ledger remains untouched.
"""

import os
import sys
import time
import queue
import logging
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Union
from datetime import datetime

import cv2
import numpy as np

# Ensure local imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_all_vision_cameras, get_camera_rois
from detection_service import get_detection_engine, ObjectDetectionEngine
from tracking_service import get_tracking_service, MultiObjectTrackingService
from identity_service import get_identity_service, MultiObjectIdentityService
from validation_service import get_validation_service, MultiObjectValidationService
from association_service import get_association_service, MultiObjectAssociationService
from worker_box_association_service import get_worker_box_association_service, MultiObjectWorkerBoxAssociationService
from box_bin_association_service import get_box_bin_association_service, MultiObjectBoxBinAssociationService
from material_association_service import get_material_association_service, MultiObjectMaterialAssociationService
from movement_event_service import get_movement_event_service, MultiObjectMovementEventService
from material_traceability_service import get_material_traceability_service, MaterialTraceabilityService

logger = logging.getLogger("vision_runtime_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s][%(name)s][%(levelname)s] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# ============================================================================
# 1. ENUMS AND DATA MODELS
# ============================================================================

class RuntimeState(str, Enum):
    """Controlled lifecycle states for Camera Runtime Sessions."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    STOPPING = "STOPPING"


class SourceType(str, Enum):
    """Supported Frame Source Types."""
    RTSP_STREAM = "RTSP_STREAM"
    USB_WEBCAM = "USB_WEBCAM"
    PUSH_DEVICE = "PUSH_DEVICE"
    TEST_SYNTHETIC = "TEST_SYNTHETIC"
    SHARED_BUS = "SHARED_BUS"


# ============================================================================
# 2. BOUNDED FRAME QUEUE
# ============================================================================

class BoundedFrameQueue:
    """
    Thread-safe, bounded FIFO frame queue with a drop-oldest policy.
    Guarantees fixed memory consumption and prioritizes frame freshness.
    """

    def __init__(self, maxsize: int = 5):
        self.maxsize = max(1, maxsize)
        self.queue: queue.Queue = queue.Queue(maxsize=self.maxsize)
        self.lock = threading.Lock()
        self.total_received = 0
        self.total_dropped = 0
        self.total_dequeued = 0

    def put_frame(self, frame: np.ndarray) -> bool:
        """
        Put a frame into the queue. If full, drops the oldest frame.
        """
        if frame is None or frame.size == 0:
            return False

        with self.lock:
            self.total_received += 1
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                    self.total_dropped += 1
                except queue.Empty:
                    pass
            try:
                self.queue.put_nowait(frame)
                return True
            except queue.Full:
                self.total_dropped += 1
                return False

    def get_frame(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """Retrieve the next frame with optional timeout."""
        try:
            frame = self.queue.get(timeout=timeout)
            with self.lock:
                self.total_dequeued += 1
            return frame
        except queue.Empty:
            return None

    def clear(self):
        """Purge all frames from queue."""
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

    @property
    def depth(self) -> int:
        return self.queue.qsize()


# ============================================================================
# 3. FRAME SOURCE ABSTRACTIONS
# ============================================================================

class BaseFrameSource(ABC):
    """Abstract base class for camera frame acquisition."""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.is_connected = False
        self.source_type = SourceType.TEST_SYNTHETIC
        self.last_capture_time = 0.0

    @abstractmethod
    def read_frame(self) -> Optional[np.ndarray]:
        """Acquire a single frame (BGR format) or None if unavailable."""
        pass

    @abstractmethod
    def close(self):
        """Release underlying system or network resources."""
        pass


class OpenCVStreamFrameSource(BaseFrameSource):
    """
    Acquires frames via OpenCV VideoCapture (RTSP, HTTP, or USB video).
    Includes reconnect logic and buffer-size minimization.
    """

    def __init__(self, camera_id: str, stream_url: str):
        super().__init__(camera_id)
        self.stream_url = stream_url.strip() if stream_url else ""
        self.cap: Optional[cv2.VideoCapture] = None
        self.lock = threading.Lock()
        
        # Determine source type
        if self.stream_url.isdigit():
            self.source_type = SourceType.USB_WEBCAM
            self.device_id: Union[int, str] = int(self.stream_url)
        elif self.stream_url:
            self.source_type = SourceType.RTSP_STREAM
            self.device_id = self.stream_url
        else:
            self.source_type = SourceType.TEST_SYNTHETIC
            self.device_id = ""

        self._connect()

    def _connect(self):
        if not self.stream_url:
            self.is_connected = False
            return

        with self.lock:
            try:
                if self.cap is not None:
                    self.cap.release()
                if isinstance(self.device_id, str) and (self.device_id.startswith("rtsp://") or self.device_id.startswith("http://")):
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;2000000"
                self.cap = cv2.VideoCapture(self.device_id)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.is_connected = self.cap.isOpened()
                if self.is_connected:
                    logger.info(f"[{self.camera_id}] OpenCV stream connected: {self.stream_url}")
                else:
                    logger.warning(f"[{self.camera_id}] Could not open stream: {self.stream_url}")
            except Exception as e:
                logger.error(f"[{self.camera_id}] Connection error: {e}")
                self.is_connected = False

    def read_frame(self) -> Optional[np.ndarray]:
        if not self.is_connected or self.cap is None:
            return None

        with self.lock:
            try:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    self.is_connected = False
                    return None
                self.last_capture_time = time.time()
                # Normalize frame to 640x480 standard resolution
                if frame.shape[1] != 640 or frame.shape[0] != 480:
                    frame = cv2.resize(frame, (640, 480))
                return frame
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Frame read exception: {e}")
                self.is_connected = False
                return None

    def close(self):
        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.is_connected = False


class PushedFrameSource(BaseFrameSource):
    """
    Accepts external client frames pushed via HTTP POST (e.g. mobile/laptop webcam).
    """

    def __init__(self, camera_id: str):
        super().__init__(camera_id)
        self.source_type = SourceType.PUSH_DEVICE
        self.latest_pushed_frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self.is_connected = True

    def push(self, frame: np.ndarray):
        if frame is not None:
            if frame.shape[1] != 640 or frame.shape[0] != 480:
                frame = cv2.resize(frame, (640, 480))
            with self.lock:
                self.latest_pushed_frame = frame
                self.last_capture_time = time.time()
                self.is_connected = True

    def read_frame(self) -> Optional[np.ndarray]:
        with self.lock:
            frame = self.latest_pushed_frame
            self.latest_pushed_frame = None  # Consume frame
            return frame

    def close(self):
        with self.lock:
            self.latest_pushed_frame = None
            self.is_connected = False


class TestSyntheticFrameSource(BaseFrameSource):
    """
    Deterministic, realistic warehouse CCTV frame generator for test mode
    without physical cameras. Cycles moving boxes, workers, and trucks.
    """

    def __init__(self, camera_id: str, location: str = "Dock"):
        super().__init__(camera_id)
        self.source_type = SourceType.TEST_SYNTHETIC
        self.location = location
        self.frame_idx = 0
        self.is_connected = True
        self.detection_engine = get_detection_engine()

    def read_frame(self) -> np.ndarray:
        self.frame_idx += 1
        self.last_capture_time = time.time()
        
        # Synthesize frame using detection engine's warehouse perspective generator
        base_frame = self.detection_engine.create_synthetic_warehouse_frame(scene_type="dock")
        frame = base_frame.copy()

        # Add moving box to simulate continuous movement in video stream
        x_shift = int((self.frame_idx * 15) % 300)
        box_x1 = 600 + x_shift
        box_y1 = 480
        cv2.rectangle(frame, (box_x1, box_y1), (box_x1 + 120, box_y1 + 90), (45, 110, 185), -1)
        cv2.rectangle(frame, (box_x1, box_y1), (box_x1 + 120, box_y1 + 90), (30, 80, 140), 2)
        cv2.putText(frame, f"BOX-{100 + (self.frame_idx % 8)}", (box_x1 + 8, box_y1 + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)

        # Add live camera HUD timestamp
        cv2.putText(
            frame,
            f"LIVE TEST [{self.camera_id}] {datetime.now().strftime('%H:%M:%S.%f')[:-4]}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 220, 255),
            2
        )
        return frame

    def close(self):
        self.is_connected = False


# ============================================================================
# 3b. UNIFIED SHARED FRAME BUS (PART 6)
# ============================================================================

class SharedFrameBus:
    """
    Part 6: Unified Shared Frame Bus coordinating physical camera frame acquisition.
    Ensures exactly ONE capture source per physical camera feeds:
      1) Camera Junction live preview / MJPEG stream / snapshots
      2) W.A.R.L.O.G. Vision Runtime pipeline (Detection -> Tracking -> Identity -> Events)
    Thread-safe, decoupled FPS, stale-frame detection, and non-blocking multi-consumer access.
    """
    _instance: Optional["SharedFrameBus"] = None
    _global_lock = threading.Lock()

    def __init__(self):
        self._buffers: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, threading.Lock] = {}

    @classmethod
    def get_instance(cls) -> "SharedFrameBus":
        with cls._global_lock:
            if cls._instance is None:
                cls._instance = SharedFrameBus()
            return cls._instance

    def _get_lock(self, camera_id: str) -> threading.Lock:
        with self._global_lock:
            if camera_id not in self._locks:
                self._locks[camera_id] = threading.Lock()
            return self._locks[camera_id]

    def publish_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        source_type: str = "STREAM",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Thread-safe publication of newly acquired physical frame to the bus.
        Called by the single physical capture loop or push endpoint.
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return False

        if frame.shape[1] != 640 or frame.shape[0] != 480:
            frame = cv2.resize(frame, (640, 480))

        lock = self._get_lock(camera_id)
        now = time.time()
        with lock:
            buf = self._buffers.get(camera_id)
            if buf is None:
                buf = {
                    "camera_id": camera_id,
                    "frame_index": 0,
                    "latest_frame": None,
                    "last_timestamp": 0.0,
                    "is_connected": True,
                    "source_type": source_type,
                    "metadata": {}
                }
                self._buffers[camera_id] = buf

            buf["frame_index"] += 1
            buf["latest_frame"] = frame
            buf["last_timestamp"] = now
            buf["is_connected"] = True
            buf["source_type"] = source_type
            if metadata:
                buf["metadata"].update(metadata)
        return True

    def get_latest_frame(
        self,
        camera_id: str,
        copy: bool = True,
        max_age_seconds: float = 5.0
    ) -> Optional[np.ndarray]:
        """
        Thread-safe retrieval of latest frame by any consumer.
        Non-blocking: Returns None if no frame or frame is stale.
        """
        lock = self._get_lock(camera_id)
        with lock:
            buf = self._buffers.get(camera_id)
            if not buf:
                return None

            if max_age_seconds > 0 and (time.time() - buf["last_timestamp"]) > max_age_seconds:
                buf["is_connected"] = False
                return None

            frame = buf.get("latest_frame")
            if frame is None:
                return None
            return frame.copy() if copy else frame

    def mark_disconnected(self, camera_id: str, reason: str = ""):
        """Flags camera feed as disconnected without clearing metadata."""
        lock = self._get_lock(camera_id)
        with lock:
            if camera_id in self._buffers:
                self._buffers[camera_id]["is_connected"] = False
                self._buffers[camera_id]["latest_frame"] = None

    def get_buffer_status(self, camera_id: str) -> Dict[str, Any]:
        """Returns diagnostic health of the shared frame buffer for a camera."""
        lock = self._get_lock(camera_id)
        with lock:
            buf = self._buffers.get(camera_id)
            if not buf:
                return {
                    "camera_id": camera_id,
                    "has_frame": False,
                    "is_connected": False,
                    "frame_index": 0,
                    "age_seconds": None,
                    "source_type": "NONE"
                }
            now = time.time()
            age = round(now - buf["last_timestamp"], 3) if buf["last_timestamp"] > 0 else None
            is_fresh = age is not None and age <= 5.0
            return {
                "camera_id": camera_id,
                "has_frame": buf["latest_frame"] is not None and is_fresh,
                "is_connected": buf["is_connected"] and is_fresh,
                "frame_index": buf["frame_index"],
                "age_seconds": age,
                "source_type": buf["source_type"]
            }

    def clear(self, camera_id: Optional[str] = None):
        """Clears buffer state for a camera or all cameras."""
        with self._global_lock:
            if camera_id:
                if camera_id in self._buffers:
                    del self._buffers[camera_id]
            else:
                self._buffers.clear()


def get_shared_frame_bus() -> SharedFrameBus:
    """Global accessor for the unified SharedFrameBus."""
    return SharedFrameBus.get_instance()


class SharedBusFrameSource(BaseFrameSource):
    """
    Part 6: Frame source connecting VisionRuntimeSession to the SharedFrameBus.
    Avoids opening duplicate OpenCV/RTSP captures when camera capture already exists.
    """
    def __init__(self, camera_id: str, fallback_source: Optional[BaseFrameSource] = None):
        super().__init__(camera_id)
        self.source_type = SourceType.SHARED_BUS
        self.bus = get_shared_frame_bus()
        self.fallback_source = fallback_source
        self.is_connected = True

    def read_frame(self) -> Optional[np.ndarray]:
        # 1. Primary: Read from SharedFrameBus
        frame = self.bus.get_latest_frame(self.camera_id, copy=True, max_age_seconds=5.0)
        if frame is not None:
            self.last_capture_time = time.time()
            self.is_connected = True
            return frame

        # 2. Check active_cameras (Camera Junction SmartCamera in-memory registry)
        try:
            from app import active_cameras
            cam = active_cameras.get(self.camera_id)
            if cam and getattr(cam, "raw_frame", None) is not None:
                raw = cam.raw_frame
                self.bus.publish_frame(self.camera_id, raw, source_type="SMART_CAMERA")
                self.last_capture_time = time.time()
                self.is_connected = True
                return raw.copy()
        except Exception:
            pass

        # 3. Fallback source if configured
        if self.fallback_source:
            fb_frame = self.fallback_source.read_frame()
            if fb_frame is not None:
                self.bus.publish_frame(self.camera_id, fb_frame, source_type="FALLBACK_STREAM")
                self.last_capture_time = time.time()
                self.is_connected = True
                return fb_frame

        self.is_connected = False
        return None

    def close(self):
        if self.fallback_source:
            try:
                self.fallback_source.close()
            except Exception:
                pass
            self.fallback_source = None
        self.is_connected = False


# ============================================================================
# 4. CANONICAL W.A.R.L.O.G. PIPELINE EXECUTOR
# ============================================================================

class VisionPipelineExecutor:
    """
    Executes the canonical Parts 5–14 perception pipeline on a single frame.
    Thread-safe, explainable, and zero-mutation.
    """

    def __init__(self):
        self.detection_engine: ObjectDetectionEngine = get_detection_engine()
        self.tracking_service: MultiObjectTrackingService = get_tracking_service()
        self.identity_service: MultiObjectIdentityService = get_identity_service()
        self.validation_service: MultiObjectValidationService = get_validation_service()
        self.truck_box_service: MultiObjectAssociationService = get_association_service()
        self.worker_box_service: MultiObjectWorkerBoxAssociationService = get_worker_box_association_service()
        self.box_bin_service: MultiObjectBoxBinAssociationService = get_box_bin_association_service()
        self.material_assoc_service: MultiObjectMaterialAssociationService = get_material_association_service()
        self.movement_event_service: MultiObjectMovementEventService = get_movement_event_service()
        self.traceability_service: MaterialTraceabilityService = get_material_traceability_service()

    def execute_pipeline(
        self,
        raw_frame: np.ndarray,
        camera_id: str,
        camera_meta: Optional[Dict[str, Any]] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None,
        primary_roi: Optional[List[Dict[str, float]]] = None,
        primary_zone_code: Optional[str] = None,
        conf_threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Executes Parts 5–14 sequentially on the acquired frame.
        Returns execution metrics, detections, tracks, associations, events, and annotated frame.
        """
        camera_meta = camera_meta or {}
        camera_zones = camera_zones or []
        t0 = time.perf_counter()
        timing: Dict[str, float] = {}

        # 1. Detection (Part 5)
        t_step = time.perf_counter()
        det_result = self.detection_engine.detect(
            image_input=raw_frame,
            camera_id=camera_id,
            conf_threshold=conf_threshold or 0.25,
            roi_polygon=primary_roi
        )
        detections = det_result.get("detections", [])
        timing["detection_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 2. Tracking (Part 6)
        t_step = time.perf_counter()
        track_session = self.tracking_service.get_session(camera_id)
        tracks = track_session.update(
            detections=detections,
            frame_width=raw_frame.shape[1],
            frame_height=raw_frame.shape[0],
            roi_polygon=primary_roi,
            roi_zone_code=primary_zone_code
        )
        timing["tracking_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 3. Identity Recognition (Part 7)
        t_step = time.perf_counter()
        enriched_tracks, bc_ms, ocr_ms = self.identity_service.identify_tracks(
            frame_bgr=raw_frame,
            tracks=tracks,
            camera_id=camera_id,
            frame_index=track_session.frame_index
        )
        timing["identity_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 4. Master-Data Validation (Part 8)
        t_step = time.perf_counter()
        validated_tracks, val_ms = self.validation_service.validate_tracks(enriched_tracks)
        timing["validation_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 5. Associations (Parts 9, 10, 11)
        t_step = time.perf_counter()
        tb_assocs, _ = self.truck_box_service.process_tracks(
            validated_tracks, camera_id=camera_id, frame_index=track_session.frame_index, camera_zones=camera_zones
        )
        wb_assocs, _ = self.worker_box_service.process_tracks(
            validated_tracks, camera_id=camera_id, frame_index=track_session.frame_index, camera_zones=camera_zones
        )
        bb_assocs, _ = self.box_bin_service.process_tracks(
            validated_tracks, camera_id=camera_id, frame_index=track_session.frame_index, camera_zones=camera_zones
        )
        mat_assocs, _ = self.material_assoc_service.process_tracks(
            validated_tracks, camera_id=camera_id, frame_index=track_session.frame_index, camera_zones=camera_zones
        )
        timing["association_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 6. Movement Event Detection (Part 12)
        t_step = time.perf_counter()
        events_result, _ = self.movement_event_service.process_events(
            tracks=validated_tracks,
            truck_box_assocs=tb_assocs,
            worker_box_assocs=wb_assocs,
            box_bin_assocs=bb_assocs,
            material_assocs=mat_assocs,
            camera_id=camera_id,
            frame_index=track_session.frame_index,
            camera_zones=camera_zones
        )
        # process_events() returns 'current_events' (no 'events' key); traceability dedups by event_id.
        events = events_result.get("events") or events_result.get("current_events", [])
        timing["events_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        # 7. Material Traceability Ingestion (Part 13)
        t_step = time.perf_counter()
        if events:
            self.traceability_service.ingest_events(events)
        timing["traceability_ms"] = round((time.perf_counter() - t_step) * 1000, 2)

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        timing["total_ms"] = total_ms

        # 8. Render Visual Annotation
        annotated_bgr = self._render_annotation(
            frame=raw_frame.copy(),
            tracks=validated_tracks,
            camera_id=camera_id,
            timing=timing,
            events=events,
            primary_roi=primary_roi
        )

        # Encode to JPEG buffer
        ret, jpeg_buf = cv2.imencode('.jpg', annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        annotated_jpeg = jpeg_buf.tobytes() if ret else None

        return {
            "success": True,
            "camera_id": camera_id,
            "frame_index": track_session.frame_index,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "detections_count": len(detections),
            "tracks_count": len(validated_tracks),
            "events_count": len(events),
            "truck_box_assocs_count": len(tb_assocs),
            "worker_box_assocs_count": len(wb_assocs),
            "box_bin_assocs_count": len(bb_assocs),
            "material_assocs_count": sum(len(v) for v in mat_assocs.values()) if isinstance(mat_assocs, dict) else len(mat_assocs),
            "timing": timing,
            "tracks": validated_tracks,
            "events": events,
            "annotated_jpeg": annotated_jpeg
        }

    def _render_annotation(
        self,
        frame: np.ndarray,
        tracks: List[Dict[str, Any]],
        camera_id: str,
        timing: Dict[str, float],
        events: List[Dict[str, Any]],
        primary_roi: Optional[List[Dict[str, float]]] = None
    ) -> np.ndarray:
        """Draws bounding boxes, track IDs, validation badges, ROI polygon, and HUD metrics."""
        h, w = frame.shape[:2]

        # Draw ROI boundary (polygon or tripwire line) if configured
        if primary_roi:
            if len(primary_roi) >= 3:
                pts = np.array([[int(p['x'] * w), int(p['y'] * h)] for p in primary_roi], np.int32)
                cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 255), thickness=2)
            elif len(primary_roi) == 2:
                p1 = (int(primary_roi[0]['x'] * w), int(primary_roi[0]['y'] * h))
                p2 = (int(primary_roi[1]['x'] * w), int(primary_roi[1]['y'] * h))
                cv2.line(frame, p1, p2, color=(0, 220, 255), thickness=2)
                cv2.circle(frame, p1, 4, (0, 255, 255), -1)
                cv2.circle(frame, p2, 4, (0, 255, 255), -1)

        # Draw tracks
        for t in tracks:
            bbox = t.get("bbox", {})
            x1 = max(0, int(bbox.get("x1", 0)))
            y1 = max(0, int(bbox.get("y1", 0)))
            x2 = min(w, int(bbox.get("x2", w)))
            y2 = min(h, int(bbox.get("y2", h)))

            cls_code = t.get("class_code", "BOX")
            track_id = t.get("track_id", "?")
            val_status = t.get("validation", {}).get("status", "UNVALIDATED")

            # Determine box color
            if cls_code == "WORKER":
                color = (255, 120, 0)
            elif cls_code == "TRUCK":
                color = (0, 165, 255)
            elif val_status == "VALIDATED":
                color = (0, 220, 0)
            else:
                color = (0, 200, 255)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Label banner
            ident_val = t.get("identity", {}).get("value") or ""
            ident_str = f" [{ident_val}]" if ident_val else ""
            label = f"#{track_id} {cls_code}{ident_str}"
            cv2.putText(frame, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Draw HUD Panel
        cv2.rectangle(frame, (8, 8), (380, 52), (15, 15, 15), -1)
        cv2.rectangle(frame, (8, 8), (380, 52), (60, 60, 60), 1)
        hud_text = f"{camera_id} | Tracks: {len(tracks)} | Evts: {len(events)} | {timing.get('total_ms', 0)}ms"
        cv2.putText(frame, hud_text, (18, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 180), 2)

        return frame


# ============================================================================
# 5. PER-CAMERA RUNTIME SESSION
# ============================================================================

class CameraRuntimeSession:
    """
    Manages the lifecycle, frame acquisition thread, bounded frame queue,
    and pipeline worker thread for a single physical or simulated camera.
    """

    def __init__(
        self,
        camera_id: str,
        camera_code: str,
        name: str,
        location: str,
        stream_url: str = "",
        configured_fps: int = 5,
        test_mode: bool = False
    ):
        self.camera_id = camera_id
        self.camera_code = camera_code
        self.name = name
        self.location = location
        self.stream_url = stream_url.strip() if stream_url else ""
        self.configured_fps = max(1, min(30, configured_fps))
        self.test_mode = test_mode

        # State management
        self.runtime_state: RuntimeState = RuntimeState.STOPPED
        self.source_state: str = "INITIALIZED"
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        # Threads and Queues
        self.frame_queue = BoundedFrameQueue(maxsize=5)
        self.capture_thread: Optional[threading.Thread] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.frame_source: Optional[BaseFrameSource] = None
        self.pipeline_executor = VisionPipelineExecutor()

        # Telemetry & Performance
        self.start_time: Optional[float] = None
        self.frames_received = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.actual_processing_fps = 0.0
        self.last_frame_timestamp: Optional[str] = None
        self.last_processing_timestamp: Optional[str] = None
        self.last_inference_ms = 0.0
        self.last_error: Optional[str] = None
        self.consecutive_failures = 0

        # Memory storage for latest outputs
        self.latest_raw_frame: Optional[np.ndarray] = None
        self.latest_annotated_jpeg: Optional[bytes] = None
        self.last_context: Dict[str, Any] = {}
        self.last_frame_time: Optional[float] = None
        self.need_roi_refresh = False

    def refresh_configuration(self):
        """Forces worker thread to immediately reload database zone and ROI configuration."""
        self.need_roi_refresh = True

    @property
    def is_running(self) -> bool:
        return self.runtime_state == RuntimeState.RUNNING

    @is_running.setter
    def is_running(self, val: bool):
        self.runtime_state = RuntimeState.RUNNING if val else RuntimeState.STOPPED

    def _init_source(self):
        """
        Part 6: Initializes single shared frame source to eliminate duplicate physical capture.
        Connects to SharedFrameBus / existing SmartCamera capture without duplicate VideoCapture.
        """
        if self.test_mode or not self.stream_url:
            self.frame_source = TestSyntheticFrameSource(self.camera_id, self.location)
            self.source_state = "TEST_SYNTHETIC"
        elif self.stream_url.lower().startswith("push") or self.stream_url == "client":
            self.frame_source = SharedBusFrameSource(self.camera_id)
            self.source_state = "SHARED_BUS_PUSH"
        else:
            # Check if Camera Junction active_cameras already captures this physical camera
            has_active_cam = False
            try:
                from app import active_cameras
                has_active_cam = self.camera_id in active_cameras
            except Exception:
                pass

            if has_active_cam:
                # Reuse existing physical capture via SharedBusFrameSource - NO SECOND VideoCapture!
                self.frame_source = SharedBusFrameSource(self.camera_id)
                self.source_state = "SHARED_BUS_REUSED"
            else:
                # If Camera Junction has not opened this stream, initialize single OpenCVStreamFrameSource
                # and attach to SharedBusFrameSource so Camera Junction can also read from it
                stream_src = OpenCVStreamFrameSource(self.camera_id, self.stream_url)
                self.frame_source = SharedBusFrameSource(self.camera_id, fallback_source=stream_src)
                self.source_state = "SHARED_BUS_STREAM" if stream_src.is_connected else "RECONNECTING"

    def start(self) -> bool:
        """Starts acquisition and processing worker threads."""
        with self.lock:
            if self.runtime_state in (RuntimeState.RUNNING, RuntimeState.STARTING):
                logger.warning(f"[{self.camera_id}] Session is already running.")
                return False

            self.runtime_state = RuntimeState.STARTING
            self.stop_event.clear()
            self.start_time = time.time()
            self._init_source()

            # Start acquisition thread (unless push mode)
            if self.frame_source.source_type != SourceType.PUSH_DEVICE:
                self.capture_thread = threading.Thread(target=self._capture_loop, name=f"capture_{self.camera_id}")
                self.capture_thread.daemon = True
                self.capture_thread.start()

            # Start processing worker thread
            self.worker_thread = threading.Thread(target=self._worker_loop, name=f"worker_{self.camera_id}")
            self.worker_thread.daemon = True
            self.worker_thread.start()

            self.runtime_state = RuntimeState.RUNNING
            logger.info(f"[{self.camera_id}] Runtime session started at {self.configured_fps} FPS.")
            return True

    def stop(self, timeout: float = 2.0) -> bool:
        """Gracefully halts threads and releases resources."""
        with self.lock:
            if self.runtime_state == RuntimeState.STOPPED:
                return True
            self.runtime_state = RuntimeState.STOPPING

        self.stop_event.set()

        # Join capture thread
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=timeout)
        self.capture_thread = None

        # Join worker thread
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=timeout)
        self.worker_thread = None

        # Release source
        if self.frame_source:
            self.frame_source.close()
            self.frame_source = None

        self.frame_queue.clear()
        with self.lock:
            self.runtime_state = RuntimeState.STOPPED
            self.source_state = "STOPPED"
        logger.info(f"[{self.camera_id}] Runtime session gracefully stopped.")
        return True

    def restart(self) -> bool:
        """Stops and restarts the session cleanly."""
        self.stop()
        time.sleep(0.1)
        return self.start()

    def push_frame(self, frame: np.ndarray) -> bool:
        """Injects external frame into SharedFrameBus and bounded queue."""
        if self.runtime_state != RuntimeState.RUNNING:
            return False
        get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="PUSH_DEVICE")
        if isinstance(self.frame_source, PushedFrameSource):
            self.frame_source.push(frame)
        return self.frame_queue.put_frame(frame)

    def _capture_loop(self):
        """Producer loop: captures frames and enqueues into bounded queue."""
        sleep_interval = 1.0 / max(10, self.configured_fps * 2)
        while not self.stop_event.is_set():
            if self.frame_source is None:
                break
            try:
                frame = self.frame_source.read_frame()
                if frame is not None:
                    self.frames_received += 1
                    self.last_frame_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with self.lock:
                        self.latest_raw_frame = frame
                    self.frame_queue.put_frame(frame)
                else:
                    time.sleep(0.05)
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Capture exception: {e}")
                time.sleep(0.2)
            time.sleep(sleep_interval)

    def _worker_loop(self):
        """Consumer loop: executes canonical W.A.R.L.O.G. pipeline at target FPS."""
        frame_interval = 1.0 / self.configured_fps
        last_process_time = 0.0
        fps_tracker_times: List[float] = []

        # Resolve camera zone and ROI metadata (with dynamic database refresh)
        primary_roi = None
        primary_zone_code = None
        camera_zones = []
        last_roi_refresh_time = 0.0

        def _reload_rois():
            nonlocal primary_roi, primary_zone_code, camera_zones, last_roi_refresh_time
            try:
                rois = get_camera_rois(self.camera_id)
                if rois:
                    primary_roi = rois[0].get("coordinates")
                    primary_zone_code = rois[0].get("zone_code")
                    camera_zones = rois
                else:
                    primary_roi = None
                    primary_zone_code = None
                    camera_zones = []
            except Exception:
                pass
            last_roi_refresh_time = time.time()
            self.need_roi_refresh = False

        _reload_rois()

        while not self.stop_event.is_set():
            now = time.time()
            # Periodic or signaled refresh of database ROI configuration
            if self.need_roi_refresh or (now - last_roi_refresh_time) > 3.0:
                _reload_rois()

            elapsed_since_last = now - last_process_time

            # Rate limit to configured processing FPS
            if elapsed_since_last < frame_interval:
                time.sleep(max(0.005, frame_interval - elapsed_since_last))
                continue

            frame = self.frame_queue.get_frame(timeout=0.1)
            if frame is None:
                continue

            # Process frame through canonical pipeline
            try:
                result = self.pipeline_executor.execute_pipeline(
                    raw_frame=frame,
                    camera_id=self.camera_id,
                    camera_meta={"code": self.camera_code, "name": self.name, "location": self.location},
                    camera_zones=camera_zones,
                    primary_roi=primary_roi,
                    primary_zone_code=primary_zone_code
                )
                last_process_time = time.time()

                with self.lock:
                    self.frames_processed += 1
                    self.last_inference_ms = result.get("timing", {}).get("total_ms", 0.0)
                    self.last_processing_timestamp = result.get("timestamp")
                    self.latest_annotated_jpeg = result.get("annotated_jpeg")
                    self.last_context = {
                        "frame_index": result.get("frame_index"),
                        "timestamp": result.get("timestamp"),
                        "detections_count": result.get("detections_count"),
                        "tracks_count": result.get("tracks_count"),
                        "events_count": result.get("events_count"),
                        "truck_box_assocs": result.get("truck_box_assocs_count"),
                        "worker_box_assocs": result.get("worker_box_assocs_count"),
                        "box_bin_assocs": result.get("box_bin_assocs_count"),
                        "material_assocs": result.get("material_assocs_count"),
                        "timing": result.get("timing"),
                        "tracks": [
                            {
                                "track_id": t.get("track_id"),
                                "class_code": t.get("class_code"),
                                "confidence": round(float(t.get("confidence", 0.0)), 2),
                                "bbox": t.get("bbox"),
                                "identity": t.get("identity"),
                                "validation": t.get("validation"),
                                "zone": t.get("zone"),
                                "material_id": (t.get("identity") or {}).get("value")
                            }
                            for t in (result.get("tracks") or [])[:20]
                        ]
                    }
                    self.consecutive_failures = 0
                    if self.runtime_state == RuntimeState.DEGRADED:
                        self.runtime_state = RuntimeState.RUNNING

                # Rolling FPS calculation over last 10 frames
                fps_tracker_times.append(last_process_time)
                if len(fps_tracker_times) > 10:
                    fps_tracker_times.pop(0)
                if len(fps_tracker_times) >= 2:
                    delta = fps_tracker_times[-1] - fps_tracker_times[0]
                    if delta > 0:
                        self.actual_processing_fps = round((len(fps_tracker_times) - 1) / delta, 1)

            except Exception as e:
                with self.lock:
                    self.last_error = str(e)
                    self.consecutive_failures += 1
                    if self.consecutive_failures >= 5:
                        self.runtime_state = RuntimeState.DEGRADED
                logger.error(f"[{self.camera_id}] Pipeline execution error: {e}")
                time.sleep(0.1)

    def get_latest_jpeg(self) -> Optional[bytes]:
        """Returns the latest annotated JPEG frame bytes for live MJPEG streaming."""
        with self.lock:
            if self.latest_annotated_jpeg:
                return self.latest_annotated_jpeg
            elif self.latest_raw_frame is not None:
                ret, buf = cv2.imencode('.jpg', self.latest_raw_frame)
                return buf.tobytes() if ret else None
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Telemetry representation conforming to Section 12."""
        uptime = round(time.time() - self.start_time, 1) if (self.start_time and self.runtime_state == RuntimeState.RUNNING) else 0.0
        return {
            "camera_id": self.camera_id,
            "camera_code": self.camera_code,
            "camera_name": self.name,
            "location": self.location,
            "stream_url": self.stream_url,
            "test_mode": self.test_mode,
            "runtime_state": self.runtime_state.value,
            "source_state": self.source_state,
            "configured_fps": self.configured_fps,
            "actual_fps": self.actual_processing_fps,
            "queue_depth": self.frame_queue.depth,
            "queue_max": self.frame_queue.maxsize,
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frame_queue.total_dropped,
            "uptime_seconds": uptime,
            "last_frame_timestamp": self.last_frame_timestamp,
            "last_processing_timestamp": self.last_processing_timestamp,
            "last_inference_ms": self.last_inference_ms,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "last_context": self.last_context
        }


# ============================================================================
# 6. VISION RUNTIME MANAGER (SINGLETON)
# ============================================================================

class VisionRuntimeManager:
    """
    Central orchestration authority managing all per-camera runtime sessions.
    Provides start, stop, restart, error isolation, and aggregate telemetry.
    """

    def __init__(self):
        self.sessions: Dict[str, CameraRuntimeSession] = {}
        self.lock = threading.Lock()
        self.is_initialized = False
        self._load_from_db()

    def _load_from_db(self):
        """Discovers cameras from authoritative WMS tables and initializes sessions."""
        with self.lock:
            try:
                cams = get_all_vision_cameras()
                valid_cids = set()
                for c in cams:
                    cid = c.get("camera_id") or c.get("camera_code")
                    if not cid:
                        continue
                    valid_cids.add(cid)
                    fps = c.get("ai_config", {}).get("processing_fps", 5) if c.get("ai_config") else 5
                    stream_url = c.get("stream_url", "")
                    is_test = (os.environ.get("WARLOG_TEST_MODE", "").lower() in ("1", "true") or not bool(stream_url))
                    if cid not in self.sessions:
                        sess = CameraRuntimeSession(
                            camera_id=cid,
                            camera_code=c.get("camera_code", cid),
                            name=c.get("camera_name", f"Camera {cid}"),
                            location=c.get("location", "General"),
                            stream_url=stream_url,
                            configured_fps=fps,
                            test_mode=is_test
                        )
                        self.sessions[cid] = sess
                    else:
                        existing = self.sessions[cid]
                        existing.stream_url = stream_url
                        existing.configured_fps = fps
                        existing.test_mode = is_test
                        existing.location = c.get("location", "General")
                        existing.name = c.get("camera_name", f"Camera {cid}")
                
                # Prune sessions for cameras deleted from authoritative DB
                for stale_cid in list(self.sessions.keys()):
                    if stale_cid not in valid_cids:
                        stale_sess = self.sessions.pop(stale_cid)
                        stale_sess.stop()

                self.is_initialized = True
                logger.info(f"VisionRuntimeManager initialized with {len(self.sessions)} camera sessions.")
            except Exception as e:
                logger.error(f"Error loading camera sessions from database: {e}")

    def refresh_cameras(self):
        """Reloads camera registry from SQLite."""
        self._load_from_db()

    def get_session(self, camera_id: str) -> Optional[CameraRuntimeSession]:
        with self.lock:
            return self.sessions.get(camera_id)

    def has_session(self, camera_id: str) -> bool:
        with self.lock:
            return camera_id in self.sessions

    def start_camera(self, camera_id: str) -> Tuple[bool, str]:
        """Starts a specific camera session."""
        sess = self.get_session(camera_id)
        if not sess:
            # Attempt refresh in case newly added
            self.refresh_cameras()
            sess = self.get_session(camera_id)

        if not sess:
            return False, f"Camera '{camera_id}' not found in registry."

        ok = sess.start()
        if ok:
            return True, f"Camera '{camera_id}' started successfully."
        return False, f"Camera '{camera_id}' is already running."

    def stop_camera(self, camera_id: str) -> Tuple[bool, str]:
        """Stops a specific camera session."""
        sess = self.get_session(camera_id)
        if not sess:
            return False, f"Camera '{camera_id}' not found."

        sess.stop()
        return True, f"Camera '{camera_id}' stopped."

    def restart_camera(self, camera_id: str) -> Tuple[bool, str]:
        """Restarts a specific camera session."""
        sess = self.get_session(camera_id)
        if not sess:
            return False, f"Camera '{camera_id}' not found."

        sess.restart()
        return True, f"Camera '{camera_id}' restarted."

    def start_all(self) -> Dict[str, Any]:
        """Starts all configured camera sessions."""
        results = {}
        for cid, sess in self.sessions.items():
            results[cid] = sess.start()
        return results

    def stop_all(self) -> Dict[str, Any]:
        """Stops all running camera sessions."""
        results = {}
        for cid, sess in self.sessions.items():
            results[cid] = sess.stop()
        return results

    def push_frame(self, camera_id: str, frame: np.ndarray) -> bool:
        """Dispatches external frame to specific camera session."""
        sess = self.get_session(camera_id)
        if sess:
            return sess.push_frame(frame)
        return False

    def get_telemetry(self) -> Dict[str, Any]:
        """Aggregates lightweight system-wide runtime telemetry (Section 12)."""
        with self.lock:
            sessions_list = [s.to_dict() for s in self.sessions.values()]

        running = sum(1 for s in sessions_list if s["runtime_state"] == RuntimeState.RUNNING.value)
        stopped = sum(1 for s in sessions_list if s["runtime_state"] == RuntimeState.STOPPED.value)
        degraded = sum(1 for s in sessions_list if s["runtime_state"] == RuntimeState.DEGRADED.value)
        error = sum(1 for s in sessions_list if s["runtime_state"] == RuntimeState.ERROR.value)
        
        tot_recv = sum(s["frames_received"] for s in sessions_list)
        tot_proc = sum(s["frames_processed"] for s in sessions_list)
        tot_drop = sum(s["frames_dropped"] for s in sessions_list)
        
        active_fps = [s["actual_fps"] for s in sessions_list if s["actual_fps"] > 0]
        avg_fps = round(sum(active_fps) / len(active_fps), 1) if active_fps else 0.0

        return {
            "summary": {
                "total_cameras": len(sessions_list),
                "running_cameras": running,
                "stopped_cameras": stopped,
                "degraded_cameras": degraded,
                "error_cameras": error,
                "total_frames_received": tot_recv,
                "total_frames_processed": tot_proc,
                "total_frames_dropped": tot_drop,
                "average_processing_fps": avg_fps
            },
            "cameras": sessions_list
        }


# Global Singleton Instance
_RUNTIME_MANAGER_INSTANCE: Optional[VisionRuntimeManager] = None
_RUNTIME_LOCK = threading.Lock()

def get_vision_runtime_manager() -> VisionRuntimeManager:
    """Thread-safe accessor for the VisionRuntimeManager singleton."""
    global _RUNTIME_MANAGER_INSTANCE
    with _RUNTIME_LOCK:
        if _RUNTIME_MANAGER_INSTANCE is None:
            _RUNTIME_MANAGER_INSTANCE = VisionRuntimeManager()
    return _RUNTIME_MANAGER_INSTANCE

# Module-level convenience aliases
vision_runtime_manager = get_vision_runtime_manager

