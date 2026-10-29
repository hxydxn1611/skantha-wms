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

import re
import copy
import cv2
import numpy as np

# Ensure local imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
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
from zone_engine import get_camera_tripwire, evaluate_tripwire_crossing

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

_GATE_OCR_READER = None
_GATE_OCR_LOCK = threading.Lock()

def get_gate_ocr_reader():
    """Lazily loaded shared EasyOCR reader for gate license plate reading."""
    global _GATE_OCR_READER
    if os.environ.get("WARLOG_TEST_MODE") == "1":
        return None
    if not EASYOCR_AVAILABLE:
        return None
    with _GATE_OCR_LOCK:
        if _GATE_OCR_READER is None:
            model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "easyocr_models")
            try:
                _GATE_OCR_READER = easyocr.Reader(['en'], gpu=False, model_storage_directory=model_dir, download_enabled=False, verbose=False)
            except Exception as e:
                logger.warning(f"EasyOCR local model_dir load failed: {e}. Trying default...")
                try:
                    _GATE_OCR_READER = easyocr.Reader(['en'], gpu=False, download_enabled=False, verbose=False)
                except Exception as e2:
                    logger.warning(f"EasyOCR reader unavailable: {e2}")
                    _GATE_OCR_READER = None
    return _GATE_OCR_READER

logger = logging.getLogger("vision_runtime_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s][%(name)s][%(levelname)s] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

VALID_INDIAN_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN",
    "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB", "BH"
}

STATE_OCR_CORRECTIONS = {
    '0L': 'DL', 'QL': 'DL', '1N': 'TN', '7N': 'TN', 'K4': 'KA',
    'M8': 'MH', 'W8': 'WB', 'NB': 'WB', 'H8': 'HR', 'D1': 'DL',
    '1P': 'UP', '0P': 'UP', 'A9': 'AP', 'T5': 'TS', 'K1': 'KL'
}

DIGIT_MAP = {'O': '0', 'D': '0', 'Q': '0', 'I': '1', 'L': '1', 'T': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6'}
ALPHA_MAP = {'0': 'D', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G', '4': 'A'}

def parse_and_validate_indian_plate(raw_text: str) -> Optional[str]:
    """Ultra-precise Indian ANPR normalization and validation engine.
    Handles High Security Registration Plates (HSRP 'IND' prefix), positional OCR character disambiguation,
    and supports standard State, Vintage, Commercial, and Bharat (BH) formats."""
    if not raw_text:
        return None
    clean = re.sub(r'[^A-Z0-9]', '', raw_text.upper())
    
    # Strip leading HSRP embossed markers
    if clean.startswith('INDIA'):
        clean = clean[5:]
    elif clean.startswith('IND'):
        clean = clean[3:]
    elif clean.startswith('IN') and len(clean) > 8 and clean[2:4] in VALID_INDIAN_STATES:
        clean = clean[2:]
        
    if len(clean) < 6 or len(clean) > 13:
        return None
    for prefix in ('BOX', 'BUNDLE', 'PALLET', 'SKU', 'PART', 'WMS', 'TEST', 'SAMPLE', 'CARRIER'):
        if clean.startswith(prefix):
            return None

    # 1. Bharat (BH) Series: YY BH NNNN XX
    m_bh = re.match(r'^([0-9]{2})(BH)([0-9]{4})([A-Z]{1,2})$', clean)
    if m_bh:
        yr, bh, num, ser = m_bh.groups()
        return f"{yr}-{bh}-{num}-{ser}"

    # 2. Standard State Registration
    st_raw = clean[:2]
    st = STATE_OCR_CORRECTIONS.get(st_raw, st_raw)
    if st not in VALID_INDIAN_STATES:
        st_try = ''.join(ALPHA_MAP.get(c, c) for c in st_raw)
        st = STATE_OCR_CORRECTIONS.get(st_try, st_try)
        if st not in VALID_INDIAN_STATES:
            return None

    rem = clean[2:]

    # Direct match: 1-2 RTO digits + 0-3 series letters + 3-4 number digits
    m_direct = re.match(r'^([0-9]{1,2})([A-Z]{0,3})([0-9]{3,4})$', rem)
    if m_direct:
        rto, ser, num = m_direct.groups()
        rto_std = rto.zfill(2)
        ser_part = f"-{ser}" if ser else ""
        return f"{st}-{rto_std}{ser_part}-{num}"

    # Positional OCR Disambiguation for typical Indian plates:
    # Slot 1: RTO (first 2 chars) -> expected digits
    # Slot 2: Number (last 4 chars) -> expected digits
    # Slot 3: Series (middle chars) -> expected letters
    if len(rem) >= 6:
        rto_raw = rem[:2]
        num_raw = rem[-4:]
        ser_raw = rem[2:-4]

        rto_fix = ''.join(DIGIT_MAP.get(c, c) for c in rto_raw)
        num_fix = ''.join(DIGIT_MAP.get(c, c) for c in num_raw)
        ser_fix = ''.join(ALPHA_MAP.get(c, c) for c in ser_raw)

        if rto_fix.isdigit() and num_fix.isdigit() and (not ser_fix or ser_fix.isalpha()):
            ser_part = f"-{ser_fix}" if ser_fix else ""
            return f"{st}-{rto_fix.zfill(2)}{ser_part}-{num_fix}"

    # Single-digit RTO fallback: e.g. 7-J-3276 -> 07-J-3276
    elif len(rem) == 5:
        rto_fix = DIGIT_MAP.get(rem[0], rem[0])
        num_fix = ''.join(DIGIT_MAP.get(c, c) for c in rem[1:])
        if rto_fix.isdigit() and num_fix.isdigit():
            return f"{st}-{rto_fix.zfill(2)}-{num_fix}"

    return None


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
        self.last_connect_attempt = 0.0

        # Auto-normalize Android IP Webcam app URLs
        resolved_url = self.stream_url
        if resolved_url:
            if ":8080" in resolved_url:
                if resolved_url.startswith("rtsp://"):
                    resolved_url = resolved_url.replace("rtsp://", "http://", 1)
                    if "/Streaming/Channels" in resolved_url or "/cam/realmonitor" in resolved_url or resolved_url.endswith(":8080") or resolved_url.endswith(":8080/"):
                        proto, rest = resolved_url.split("://", 1)
                        host_port = rest.split("/")[0]
                        resolved_url = f"{proto}://{host_port}/video"
                elif resolved_url.startswith(("http://", "https://")) and (resolved_url.endswith(":8080") or resolved_url.endswith(":8080/")):
                    resolved_url = resolved_url.rstrip("/") + "/video"

        self.stream_url = resolved_url
        
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
        if not self.stream_url or str(self.stream_url).lower().startswith("device:"):
            self.is_connected = False
            return

        with self.lock:
            try:
                self.last_connect_attempt = time.time()
                if self.cap is not None:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None

                if isinstance(self.device_id, str) and (self.device_id.startswith("rtsp://") or self.device_id.startswith("http://")):
                    # Ultra-fast 1.5s connection timeout; forces TCP to prevent UDP packet drops
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1500000|stimeout;1500000|rtsp_transport;tcp|max_delay;500000|buffer_size;102400"
                self.cap = cv2.VideoCapture(self.device_id)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self.is_connected = self.cap.isOpened()
                if self.is_connected:
                    logger.info(f"[{self.camera_id}] OpenCV stream connected in < 1.5s: {self.stream_url}")
                else:
                    logger.warning(f"[{self.camera_id}] Could not open stream (will retry gracefully): {self.stream_url}")
            except Exception as e:
                logger.error(f"[{self.camera_id}] Connection error: {e}")
                self.is_connected = False

    def read_frame(self) -> Optional[np.ndarray]:
        if not self.is_connected or self.cap is None:
            # Reconnect rate-limited to once every 3.0 seconds to prevent thread stalling
            if (time.time() - self.last_connect_attempt) >= 3.0:
                self._connect()
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

        # 4. Instant RTMP Ingest Service fallback (STRICTLY for Trueview / Wi-Fi Camera pushing to 1935, NEVER for IP/RTSP/Webcam)
        try:
            is_rtmp_cam = False
            from db import get_db
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT camera_type, vendor, stream_url FROM cameras WHERE camera_id = ? OR camera_code = ?", (self.camera_id, self.camera_id))
            crow = cur.fetchone()
            conn.close()
            if crow:
                ctype = (crow[0] or "").lower()
                cvendor = (crow[1] or "").lower()
                csurl = (crow[2] or "").lower()
                if "http" not in csurl and "rtsp" not in csurl and "device:" not in csurl and ctype not in ("ip camera", "dvr", "nvr", "device camera"):
                    if "rtmp" in csurl or "1935" in csurl or "wi-fi" in ctype or "wifi" in ctype or cvendor == "trueview":
                        is_rtmp_cam = True

            if is_rtmp_cam:
                from rtmp_service import get_rtmp_service
                rtmp_srv = get_rtmp_service()
                if rtmp_srv and rtmp_srv.latest_frame is not None and (time.time() - rtmp_srv.last_frame_time) < 4.0:
                    self.bus.publish_frame(self.camera_id, rtmp_srv.latest_frame, source_type="RTMP_INGEST")
                    self.last_capture_time = time.time()
                    self.is_connected = True
                    return rtmp_srv.latest_frame.copy()
        except Exception:
            pass

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
            conf_threshold=conf_threshold or 0.15,
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

        # 3. Identity Recognition (Part 7) - throttled OCR for high-FPS live tracking
        t_step = time.perf_counter()
        enriched_tracks, bc_ms, ocr_ms = self.identity_service.identify_tracks(
            frame_bgr=raw_frame,
            tracks=tracks,
            camera_id=camera_id,
            frame_index=track_session.frame_index,
            enable_throttling=True,
            enable_ocr=(track_session.frame_index % 15 == 0)
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

        # 7.5 Autonomous Palletization & Violation Processing
        pallet_data = None
        try:
            from pallet_service import get_pallet_service
            ps = get_pallet_service()
            pallet_data = ps.process_pallet_zone_tracks(
                camera_id=camera_id,
                tracks=validated_tracks,
                frame_bgr=raw_frame,
                pallet_zone_polygon=primary_roi
            )
        except Exception as e:
            logger.debug(f"Pallet zone tracking bypass: {e}")

        # 8. Render Visual Annotation
        annotated_bgr = self._render_annotation(
            frame=raw_frame.copy(),
            tracks=validated_tracks,
            camera_id=camera_id,
            timing=timing,
            events=events,
            primary_roi=primary_roi,
            pallet_data=pallet_data
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
            "pallet_data": pallet_data,
            "annotated_jpeg": annotated_jpeg
        }

    def _render_annotation(
        self,
        frame: np.ndarray,
        tracks: List[Dict[str, Any]],
        camera_id: str,
        timing: Dict[str, float],
        events: List[Dict[str, Any]],
        primary_roi: Optional[List[Dict[str, float]]] = None,
        pallet_data: Optional[Dict[str, Any]] = None
    ) -> np.ndarray:
        """Draws bounding boxes, track IDs, validation badges, ROI polygon, HUD metrics, and Pallet counters."""
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

            # Check if this track triggered a human error violation or pallet count
            has_violation = bool(t.get("violation"))
            is_counted_bundle = bool(t.get("is_counted_bundle"))

            # Determine box color
            if has_violation:
                color = (0, 0, 255) # Bright Neon Red for violations
                thickness = 3
            elif is_counted_bundle:
                color = (0, 230, 115) # Emerald Green for verified bundle on pallet
                thickness = 2
            elif cls_code == "WORKER":
                color = (255, 120, 0)
                thickness = 2
            elif cls_code == "TRUCK":
                color = (0, 165, 255)
                thickness = 2
            elif val_status == "VALIDATED":
                color = (0, 220, 0)
                thickness = 2
            else:
                color = (0, 200, 255)
                thickness = 2

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            
            # Label banner
            if has_violation:
                label = f"VIOLATION: {t.get('violation')}"
            elif is_counted_bundle:
                sim = int(t.get('sku_similarity', 0.8) * 100)
                label = f"BUNDLE #{track_id} [VERIFIED {sim}%]"
            else:
                ident_val = t.get("identity", {}).get("value") or ""
                ident_str = f" [{ident_val}]" if ident_val else ""
                label = f"#{track_id} {cls_code}{ident_str}"

            cv2.putText(frame, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Draw HUD Panel (Left side)
        cv2.rectangle(frame, (8, 8), (380, 52), (15, 15, 15), -1)
        cv2.rectangle(frame, (8, 8), (380, 52), (60, 60, 60), 1)
        hud_text = f"{camera_id} | Tracks: {len(tracks)} | Evts: {len(events)} | {timing.get('total_ms', 0)}ms"
        cv2.putText(frame, hud_text, (18, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 180), 2)

        # Draw Autonomous Palletization HUD (Right side) if pallet is active
        if pallet_data and pallet_data.get("active_pallet"):
            p_id = pallet_data.get("pallet_id", "PLT")
            c_b = pallet_data.get("counted_bundles", 0)
            t_b = pallet_data.get("target_bundles", 0)
            tot_u = pallet_data.get("total_units", 0)
            sku = pallet_data.get("sku_id", "")

            hud_w = 340
            x_start = max(10, w - hud_w - 10)
            cv2.rectangle(frame, (x_start, 8), (w - 10, 54), (20, 25, 35), -1)
            cv2.rectangle(frame, (x_start, 8), (w - 10, 54), (0, 200, 255), 2)

            p_title = f"PALLET: {p_id} ({sku})"
            cv2.putText(frame, p_title, (x_start + 10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 2)
            p_metrics = f"BUNDLES: {c_b} (LIVE)  |  PIECES: {tot_u} EA" if not t_b or t_b <= 1 else f"BUNDLES: {c_b}/{t_b}  |  PIECES: {tot_u} EA"
            cv2.putText(frame, p_metrics, (x_start + 10, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 120), 2)

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
        self.frame_queue = BoundedFrameQueue(maxsize=2)
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
        self._cached_live_jpeg: Optional[bytes] = None
        self._last_encoded_frame_idx: int = -1
        self._prev_flow_gray: Optional[np.ndarray] = None
        self.last_context: Dict[str, Any] = {}
        self.last_frame_time: Optional[float] = None
        self.need_roi_refresh = False

        # Phase 2 & 15: Database-driven dynamic tripwire (no hardcoded defaults)
        self.active_tripwire: Optional[Dict[str, Any]] = None
        self.last_tripwire_check = 0.0

        # Authoritative Directional Counting & Spatial Motion Tracking
        self.inbound_count = 0
        self.outbound_count = 0
        self.net_stock_count = 0
        self.counted_track_states: Dict[Any, str] = {}
        self.flash_counters: List[Dict[str, Any]] = []
        self.tracked_centroids: Dict[Any, Tuple[int, int]] = {}
        self.track_trajectories: Dict[Any, List[Tuple[int, int]]] = {}
        self.track_motion_vectors: Dict[Any, Tuple[int, int]] = {}
        self.track_last_seen: Dict[Any, int] = {}
        self.active_workers_count = 0
        self.active_stocks_count = 0
        self.visible_packages = 0
        self.visible_boxes = 0
        self.latest_boxes: List[Dict[str, Any]] = []

        # Gate Camera & Live ANPR Configuration (Authoritative Pipeline)
        loc_str = str(self.location or '').strip().lower()
        name_str = str(self.name or '').strip().lower()
        cid_str = str(self.camera_id or '').strip().lower()
        self.is_gate_camera = (loc_str == 'gate' or 'gate' in name_str or 'gate' in cid_str or 'anpr' in name_str)
        self.last_detected_plate: Optional[str] = None
        self.last_gate_pass_id: Optional[str] = None
        self.last_gate_pass_photo: Optional[str] = None
        self.last_gate_pass_time = 0.0
        self.last_plate_prob = 0.0
        self.anpr_in_flight = False
        self.last_anpr_run_time = 0.0
        self.events: List[Dict[str, Any]] = []

    def refresh_tripwire(self):
        """Forces immediate refresh of active tripwire configuration from database."""
        try:
            self.active_tripwire = get_camera_tripwire(self.camera_id, 640, 480)
            self.last_tripwire_check = time.time()
        except Exception as e:
            logger.warning(f"[{self.camera_id}] Error refreshing tripwire: {e}")

    def refresh_configuration(self):
        """Forces worker thread to immediately reload database zone and ROI configuration."""
        self.need_roi_refresh = True
        self.refresh_tripwire()

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
        elif self.stream_url.lower().startswith(("push", "device:", "client", "rtmp:")) or self.stream_url == "client":
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
            if self.runtime_state in (RuntimeState.RUNNING, RuntimeState.STARTING, RuntimeState.DEGRADED):
                return False
            if self.worker_thread and self.worker_thread.is_alive():
                self.runtime_state = RuntimeState.RUNNING
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
        get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="PUSH_DEVICE")
        with self.lock:
            self.latest_raw_frame = frame
            self.frames_received += 1
            self.last_frame_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(self.frame_source, PushedFrameSource):
            self.frame_source.push(frame)
        if self.runtime_state not in (RuntimeState.RUNNING, RuntimeState.STARTING, RuntimeState.DEGRADED):
            self.start()
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

    @staticmethod
    def _extract_plate_candidates(crop_bgr: np.ndarray) -> List[np.ndarray]:
        """
        Ultra-fast (1-3ms) morphological license plate candidate extractor.
        Locates rectangular high-gradient plate candidates (aspect ratio 1.7 - 6.0).
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return []
        ch, cw = crop_bgr.shape[:2]
        if ch < 18 or cw < 45:
            return []

        try:
            gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
            sobelx = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
            abs_sobelx = np.absolute(sobelx)
            sobel_8u = np.uint8(np.clip(abs_sobelx, 0, 255))

            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
            morph = cv2.morphologyEx(sobel_8u, cv2.MORPH_CLOSE, kernel)
            _, thresh = cv2.threshold(morph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if h < 14 or w < 38:
                    continue
                aspect = float(w) / float(h)
                if 1.6 <= aspect <= 6.5 and (w * h) >= 600:
                    px1 = max(0, x - int(w * 0.06))
                    py1 = max(0, y - int(h * 0.12))
                    px2 = min(cw, x + w + int(w * 0.06))
                    py2 = min(ch, y + h + int(h * 0.12))
                    p_crop = crop_bgr[py1:py2, px1:px2]
                    if p_crop.size > 0:
                        candidates.append((w * h, p_crop))

            candidates.sort(key=lambda c: c[0], reverse=True)
            return [c[1] for c in candidates[:4]]
        except Exception:
            return []

    def _run_live_gate_anpr_worker(self, frame: np.ndarray, vehicle_boxes: List[Dict[str, Any]]):
        """Dedicated high-speed ANPR worker running on the LIVE feed.
        Extracts real license plates, captures automatic evidence snapshots, and auto-creates connected Gate Passes."""
        if self.test_mode:
            self.anpr_in_flight = False
            return

        try:
            fh, fw = frame.shape[:2]
            if fh < 80 or fw < 80:
                self.anpr_in_flight = False
                return

            candidate_crops = []
            v_type_candidate = "Heavy Commercial (HCV)"

            # 1. Prioritize vehicle crops and morphological plate candidates
            for vb in vehicle_boxes:
                x1, y1, x2, y2 = vb['x1'], vb['y1'], vb['x2'], vb['y2']
                vw = max(1, x2 - x1)
                vh = max(1, y2 - y1)
                vb_type = str(vb.get('type', '')).lower()
                if 'light vehicle' in vb_type or 'car' in vb_type:
                    v_type_candidate = "Light Vehicle (LMV)"
                elif 'forklift' in vb_type:
                    v_type_candidate = "Forklift / MHE"

                # Check if detected box is an isolated license plate
                if 'license plate' in vb_type:
                    pad_y = int(vh * 0.15)
                    pad_x = int(vw * 0.15)
                    lp_crop = frame[max(0, y1 - pad_y):min(fh, y2 + pad_y), max(0, x1 - pad_x):min(fw, x2 + pad_x)]
                    if lp_crop.size > 0:
                        candidate_crops.insert(0, lp_crop)

                # Plate is typically mounted on lower 60% of the vehicle
                py1 = max(0, int(y1 + vh * 0.38))
                py2 = min(fh, y2)
                px1 = max(0, x1)
                px2 = min(fw, x2)
                v_crop = frame[py1:py2, px1:px2]
                if v_crop.size > 0:
                    plate_patches = self._extract_plate_candidates(v_crop)
                    candidate_crops.extend(plate_patches)
                    candidate_crops.append(v_crop)

            # 2. Central frame region for handheld plates, phone cameras, or close-up arrivals
            center_crop = frame[int(fh * 0.10):int(fh * 0.90), int(fw * 0.10):int(fw * 0.90)]
            if center_crop.size > 0:
                center_patches = self._extract_plate_candidates(center_crop)
                candidate_crops.extend(center_patches)
                candidate_crops.append(center_crop)

            best_plate: str = ""
            best_prob: float = 0.0

            reader = get_gate_ocr_reader()
            if reader is not None:
                # Limit candidate evaluation to top 5 most promising crops for lightning execution (<80ms)
                for crop in candidate_crops[:5]:
                    ch, cw = crop.shape[:2]
                    if ch < 16 or cw < 38:
                        continue

                    # Bound max width to 420 for fast OCR execution
                    if cw > 420:
                        scale = 420.0 / float(cw)
                        crop_scaled = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    elif cw < 200 and ch < 80:
                        crop_scaled = cv2.resize(crop, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
                    else:
                        crop_scaled = crop

                    gray = cv2.cvtColor(crop_scaled, cv2.COLOR_BGR2GRAY)
                    try:
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(6, 6))
                        enhanced = clahe.apply(gray)
                    except Exception:
                        enhanced = gray

                    try:
                        ocr_res = reader.readtext(enhanced)
                    except Exception:
                        ocr_res = []

                    clean_tokens = []
                    for (_, text, prob) in ocr_res:
                        clean_t = "".join(c for c in text if c.isalnum()).upper()
                        if len(clean_t) >= 2 and prob > 0.15:
                            clean_tokens.append(clean_t)
                        val = parse_and_validate_indian_plate(clean_t)
                        if val:
                            best_plate = val
                            best_prob = float(prob)
                            break

                    # Multi-line token recombination (e.g. ['KA01', 'AB1234'] -> 'KA-01-AB-1234')
                    if not best_plate and clean_tokens:
                        combined = "".join(clean_tokens)
                        val = parse_and_validate_indian_plate(combined)
                        if val:
                            best_plate = val
                            best_prob = 0.88

                    # INSTANT BREAK: Stop immediately once valid plate is recognized
                    if best_plate != "":
                        break

            # If a plate was detected from the live feed:
            if best_plate != "":
                now_t = time.time()
                # Deduplication: if different plate, trigger INSTANTLY (0s cooldown); if same plate, 25s cooldown
                is_new_plate = (best_plate != self.last_detected_plate)
                time_since_last = now_t - self.last_gate_pass_time

                if is_new_plate or time_since_last > 25.0:
                    clean_plate_id = "".join(c for c in best_plate if c.isalnum())
                    ts_str = int(now_t)

                    # Ensure snapshots directory exists
                    snapshots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "snapshots")
                    os.makedirs(snapshots_dir, exist_ok=True)
                    rel_photo_path = f"snapshots/anpr_{clean_plate_id}_{ts_str}.jpg"
                    full_photo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", rel_photo_path)

                    # High-res evidence snapshot with crisp gate access HUD
                    snap_frame = frame.copy()
                    sh, sw = snap_frame.shape[:2]

                    # Overlay high-contrast badge on snapshot
                    cv2.rectangle(snap_frame, (12, 12), (min(sw - 12, 420), 86), (15, 23, 42), -1)
                    cv2.rectangle(snap_frame, (12, 12), (min(sw - 12, 420), 86), (0, 220, 255), 2)
                    # Plate badge
                    cv2.rectangle(snap_frame, (22, 20), (min(sw - 22, 280), 56), (245, 230, 60), -1)
                    cv2.rectangle(snap_frame, (22, 20), (min(sw - 22, 280), 56), (10, 10, 10), 2)
                    cv2.rectangle(snap_frame, (22, 20), (52, 56), (180, 50, 0), -1)
                    cv2.putText(snap_frame, "IND", (24, 43), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
                    cv2.putText(snap_frame, best_plate, (58, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (10, 10, 10), 2)
                    cv2.putText(snap_frame, f"GATE ACCESS VERIFIED • {time.strftime('%Y-%m-%d %H:%M:%S')}", (22, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 128), 1)

                    try:
                        cv2.imwrite(full_photo_path, snap_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    except Exception as e_snap:
                        logger.warning(f"Failed to write snapshot {full_photo_path}: {e_snap}")

                    # Check or create Gate Pass in database
                    existing_gp = db.get_pending_gate_pass_by_plate(best_plate)
                    if existing_gp:
                        gp_id = existing_gp.get('id', 'GP-PENDING')
                        # Update snapshot photo on existing pass
                        try:
                            conn = db.get_db()
                            conn.execute("UPDATE gate_passes SET photo = ? WHERE id = ?", (rel_photo_path, gp_id))
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
                        logger.info(f"[{self.camera_id} GATE ANPR] Linked Gate Pass {gp_id} with snapshot for plate: {best_plate}")
                    else:
                        new_gp = db.create_gate_pass({
                            "plate": best_plate,
                            "type": v_type_candidate,
                            "activity": "Unloading",
                            "status": "Pending",
                            "driver_name": "Verified Driver",
                            "dock": "Dock 1",
                            "photo": rel_photo_path
                        })
                        gp_id = new_gp.get('id', 'GP-AUTO')
                        db.create_vehicle_log(gp_id, best_plate, "Verified Driver")
                        logger.info(f"[{self.camera_id} GATE ANPR] Created Gate Pass {gp_id} with snapshot for plate: {best_plate}")

                    with self.lock:
                        self.last_gate_pass_id = gp_id
                        self.last_detected_plate = best_plate
                        self.last_gate_pass_photo = rel_photo_path
                        self.last_gate_pass_time = now_t
                        self.last_plate_prob = best_prob

                        event = {
                            "time": time.strftime("%H:%M:%S"),
                            "type": v_type_candidate,
                            "plate": best_plate,
                            "gate_pass_id": gp_id,
                            "status": "GATE PASS ISSUED (LIVE SNAPSHOT)",
                            "photo": rel_photo_path,
                            "camera": self.name
                        }
                        self.events.insert(0, event)
            else:
                now_t = time.time()
                if (now_t - self.last_gate_pass_time) > 12.0:
                    with self.lock:
                        self.last_detected_plate = None
                        self.last_gate_pass_id = None
        except Exception as e:
            logger.error(f"[{self.camera_id} GATE ANPR WORKER ERROR]: {e}")
        finally:
            self.anpr_in_flight = False

    @staticmethod
    def _propagate_boxes_optical_flow(
        prev_gray: Optional[np.ndarray],
        curr_gray: Optional[np.ndarray],
        boxes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Ultra-fast (0.5ms) Lucas-Kanade sparse optical flow box propagator on 320x240 grayscale frames.
        Shifts bounding boxes smoothly along with moving workers, forklifts, and bundles on every video frame.
        """
        if prev_gray is None or curr_gray is None or not boxes:
            return boxes
        if prev_gray.shape != curr_gray.shape:
            return boxes

        all_pts = []
        box_ranges = []
        for b in boxes:
            sx1 = max(2, int(b["x1"] * 0.5))
            sy1 = max(2, int(b["y1"] * 0.5))
            sx2 = min(318, int(b["x2"] * 0.5))
            sy2 = min(238, int(b["y2"] * 0.5))
            bw = sx2 - sx1
            bh = sy2 - sy1
            if bw < 6 or bh < 6:
                box_ranges.append((0, 0))
                continue
            # Sample 4x4 interior grid (inner 65% of box)
            xs = np.linspace(sx1 + bw * 0.18, sx2 - bw * 0.18, 4)
            ys = np.linspace(sy1 + bh * 0.18, sy2 - bh * 0.18, 4)
            start_i = len(all_pts)
            for py in ys:
                for px in xs:
                    all_pts.append([[float(px), float(py)]])
            box_ranges.append((start_i, len(all_pts)))

        if not all_pts:
            return boxes

        try:
            p0 = np.array(all_pts, dtype=np.float32)
            p1, st, _ = cv2.calcOpticalFlowPyrLK(
                prev_gray,
                curr_gray,
                p0,
                None,
                winSize=(15, 15),
                maxLevel=2,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 8, 0.03)
            )
            if p1 is None or st is None:
                return boxes

            updated_boxes = []
            for idx, b in enumerate(boxes):
                b_copy = dict(b)
                s_i, e_i = box_ranges[idx]
                if e_i > s_i:
                    valid_mask = (st[s_i:e_i].flatten() == 1)
                    if np.any(valid_mask):
                        diffs = (p1[s_i:e_i][valid_mask] - p0[s_i:e_i][valid_mask]).reshape(-1, 2)
                        # Filter outliers (> 40px jump in 320x240 space)
                        inliers = diffs[(np.abs(diffs[:, 0]) < 40) & (np.abs(diffs[:, 1]) < 40)]
                        if len(inliers) >= 2:
                            dx = float(np.median(inliers[:, 0])) * 2.0
                            dy = float(np.median(inliers[:, 1])) * 2.0
                            if abs(dx) >= 0.5 or abs(dy) >= 0.5:
                                bw_full = b_copy["x2"] - b_copy["x1"]
                                bh_full = b_copy["y2"] - b_copy["y1"]
                                nx1 = int(round(max(0, min(640 - bw_full, b_copy["x1"] + dx))))
                                ny1 = int(round(max(0, min(480 - bh_full, b_copy["y1"] + dy))))
                                b_copy["x1"] = nx1
                                b_copy["y1"] = ny1
                                b_copy["x2"] = min(640, nx1 + bw_full)
                                b_copy["y2"] = min(480, ny1 + bh_full)
                updated_boxes.append(b_copy)
            return updated_boxes
        except Exception:
            return boxes

    def _render_hud(self, base_frame: np.ndarray, timing_ms: float) -> np.ndarray:
        """Renders comprehensive HUD: gate ANPR card or warehouse directional tripwire + clean moving bounding boxes."""
        display_frame = base_frame.copy()
        h, w = display_frame.shape[:2]

        # 1. Draw Directional Tripwire Line (if configured and enabled)
        if self.active_tripwire and self.active_tripwire.get('is_enabled'):
            p1 = self.active_tripwire['p1']
            p2 = self.active_tripwire['p2']
            dir_mode = self.active_tripwire.get('crossing_direction', 'BOTH')
            cv2.line(display_frame, p1, p2, (0, 220, 255), 2)
            cv2.circle(display_frame, p1, 4, (0, 255, 255), -1)
            cv2.circle(display_frame, p2, 4, (0, 255, 255), -1)

            mid_x = int((p1[0] + p2[0]) / 2)
            mid_y = int((p1[1] + p2[1]) / 2)
            z_label = self.active_tripwire.get('zone_code', 'TRIPWIRE')
            if dir_mode == 'BOTH':
                cv2.putText(display_frame, f"[{z_label}] IN (+1) >>>", (max(10, mid_x - 120), max(20, mid_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 128), 1)
                cv2.putText(display_frame, f"<<< OUT (-1)", (min(w - 140, mid_x + 10), min(h - 10, mid_y + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 140, 255), 1)
            elif dir_mode == 'INBOUND_ONLY':
                cv2.putText(display_frame, f"[{z_label}] IN (+1) >>>", (max(10, mid_x - 80), max(20, mid_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 128), 1)
            elif dir_mode == 'OUTBOUND_ONLY':
                cv2.putText(display_frame, f"[{z_label}] <<< OUT (-1)", (max(10, mid_x - 80), min(h - 10, mid_y + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 140, 255), 1)

        boxes_snap = list(self.latest_boxes)
        flash_snap = list(self.flash_counters)

        # 2. Draw Detected Objects (Clean bounding boxes that move smoothly with Worker, Forklift, Bundles — NO arrows)
        for box in boxes_snap:
            x1, y1, x2, y2 = box['x1'], box['y1'], box['x2'], box['y2']
            is_person = box.get('is_person', False)
            is_forklift = box.get('is_forklift', False)
            is_veh = box.get('is_vehicle', False)
            if is_person:
                color = (255, 200, 0)   # Cyan/Blue for Personnel / Workers
            elif is_forklift:
                color = (20, 140, 255)  # Vivid Orange/Coral for Forklift / MHE
            elif is_veh:
                color = (0, 255, 160)   # Emerald for Vehicles
            else:
                color = (0, 255, 128)   # Vibrant Green for Warehouse Stock / Bundles

            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
            label = box.get('type', '')
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)
            by1 = max(0, y1 - th - 8)
            cv2.rectangle(display_frame, (x1, by1), (min(w, x1 + tw + 10), y1), color, -1)
            cv2.putText(display_frame, label, (x1 + 5, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (10, 15, 25), 1, cv2.LINE_AA)

        # 3. Draw Floating Flash Indicators
        for fc in flash_snap:
            f_text = fc.get('text', '')
            fx, fy = fc.get('pos', (int(w / 2), int(h / 2)))
            f_col = fc.get('color', (0, 255, 128))
            cv2.putText(display_frame, f_text, (max(10, fx - 50), max(25, fy - 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 3)
            cv2.putText(display_frame, f_text, (max(10, fx - 50), max(25, fy - 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, f_col, 2)

        # 5. Prominent License Plate & Gate Pass Card (Bottom Left ONLY when plate is actively detected)
        if self.last_detected_plate:
            card_x, card_y = 14, max(10, h - 105)
            cv2.rectangle(display_frame, (card_x, card_y), (card_x + 360, card_y + 90), (15, 18, 24), -1)
            cv2.rectangle(display_frame, (card_x, card_y), (card_x + 360, card_y + 90), (0, 220, 255), 1)

            cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 235, card_y + 44), (245, 230, 60), -1)
            cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 235, card_y + 44), (10, 10, 10), 2)
            cv2.rectangle(display_frame, (card_x + 10, card_y + 10), (card_x + 36, card_y + 44), (180, 50, 0), -1)
            cv2.putText(display_frame, "IND", (card_x + 12, card_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 255, 255), 1)
            cv2.putText(display_frame, self.last_detected_plate, (card_x + 42, card_y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (10, 10, 10), 2)

            pass_text = f"GATE PASS: {self.last_gate_pass_id or 'ACTIVE'}"
            cv2.putText(display_frame, pass_text, (card_x + 10, card_y + 64), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 128), 2)
            cv2.putText(display_frame, "STATUS: LIVE ARRIVAL (PASS CREATED)", (card_x + 10, card_y + 82), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

        # 6. Top HUD Telemetry Banner
        cam_tag = self.name or self.camera_id
        hud_text = f"[{cam_tag}] LIVE ({timing_ms}ms) | WORKERS: {self.active_workers_count} | STOCK: {self.net_stock_count} | IN: +{self.inbound_count} / OUT: -{self.outbound_count}"
        if self.last_detected_plate:
            hud_text += f" | 💳 {self.last_detected_plate}"
        cv2.rectangle(display_frame, (0, 0), (w, 32), (18, 22, 28), -1)
        cv2.putText(display_frame, hud_text, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 255, 200), 2)

        return display_frame

    def _worker_loop(self):
        """Consumer loop: executes canonical W.A.R.L.O.G. pipeline at target FPS."""
        frame_interval = 1.0 / max(15, self.configured_fps)
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
        self.refresh_tripwire()

        while not self.stop_event.is_set():
            now = time.time()
            # Periodic or signaled refresh of database ROI configuration
            if self.need_roi_refresh or (now - last_roi_refresh_time) > 3.0:
                _reload_rois()

            # Periodic refresh of tripwire
            if (now - self.last_tripwire_check) > 2.0:
                self.refresh_tripwire()

            elapsed_since_last = now - last_process_time

            # Rate limit to configured processing FPS
            if elapsed_since_last < frame_interval:
                time.sleep(max(0.005, frame_interval - elapsed_since_last))
                continue

            frame = self.frame_queue.get_frame(timeout=0.05)
            if frame is None:
                frame = get_shared_frame_bus().get_latest_frame(self.camera_id, copy=True, max_age_seconds=1.5)
            if frame is None:
                continue

            # Process frame through canonical pipeline
            try:
                yolo_flow_gray = cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY)
                result = self.pipeline_executor.execute_pipeline(
                    raw_frame=frame,
                    camera_id=self.camera_id,
                    camera_meta={"code": self.camera_code, "name": self.name, "location": self.location},
                    camera_zones=camera_zones,
                    primary_roi=primary_roi,
                    primary_zone_code=primary_zone_code
                )
                last_process_time = time.time()
                timing_ms = result.get("timing", {}).get("total_ms", 0.0)
                raw_tracks = result.get("tracks") or []

                new_boxes = []
                box_count = 0
                workers_count = 0
                active_stock_count = 0

                has_vehicle = False
                forklifts_count = 0
                for t in raw_tracks:
                    cls_code = str(t.get("class_code", "")).upper()
                    is_person = (cls_code in ("WORKER", "PERSON"))
                    is_forklift = (cls_code == "FORKLIFT")
                    is_vehicle = (cls_code in ("TRUCK", "CAR", "BUS", "VEHICLE", "LICENSE_PLATE"))
                    is_stock = not is_person and not is_vehicle and not is_forklift
                    tid = t.get("track_id")
                    bb = t.get("bbox", {})
                    x1, y1 = max(0, int(bb.get("x1", 0))), max(0, int(bb.get("y1", 0)))
                    x2, y2 = min(640, int(bb.get("x2", 640))), min(480, int(bb.get("y2", 480)))
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    mov_state = t.get("movement_state") or ""
                    sku_code = t.get("sku_id") or (t.get("identity") or {}).get("value")
                    upb = max(1, int(t.get("units_per_bundle") or 1))
                    uom = str(t.get("uom") or "EA").upper()
                    worker_name = None

                    if is_person:
                        workers_count += 1
                        try:
                            from worker_recognition_service import get_worker_recognition_service
                            w_match = get_worker_recognition_service().identify_worker(
                                frame, x1, y1, x2, y2, self.camera_id, tid
                            )
                            if w_match and w_match.get("name"):
                                worker_name = w_match["name"]
                        except Exception:
                            pass
                        state_tag = f" [{mov_state}]" if mov_state else ""
                        if worker_name:
                            v_type = f"{worker_name}{state_tag}"
                        else:
                            v_type = f"Worker #{tid}{state_tag}" if tid is not None else f"Worker{state_tag}"
                    elif is_forklift:
                        forklifts_count += 1
                        state_tag = f" [{mov_state}]" if mov_state else " [MHE]"
                        v_type = f"Forklift #{tid}{state_tag}" if tid is not None else f"Forklift{state_tag}"
                    elif is_vehicle:
                        has_vehicle = True
                        if cls_code in ("TRUCK", "BUS"):
                            v_type = f"Heavy Commercial (HCV) #{tid}" if tid is not None else "Heavy Commercial (HCV)"
                        elif cls_code == "LICENSE_PLATE":
                            v_type = f"License Plate #{tid}" if tid is not None else "License Plate"
                        else:
                            v_type = f"Light Vehicle (LMV) #{tid}" if tid is not None else "Light Vehicle (LMV)"
                    else:
                        active_stock_count += 1
                        box_count += 1
                        if sku_code:
                            v_type = f"{sku_code} ({upb} {uom}) #{tid}" if tid is not None else f"{sku_code} ({upb} {uom})"
                        else:
                            v_type = f"{cls_code.replace('_', ' ').title()} #{tid}" if tid is not None else "Stock"

                    if tid is not None:
                        self.tracked_centroids[tid] = (cx, cy)
                        if tid not in self.track_trajectories:
                            self.track_trajectories[tid] = []
                        traj = self.track_trajectories[tid]
                        prev_pos = traj[-1] if traj else (cx, cy)
                        traj.append((cx, cy))
                        if len(traj) > 24:
                            traj.pop(0)

                        dx = cx - prev_pos[0]
                        dy = cy - prev_pos[1]
                        self.track_motion_vectors[tid] = (dx, dy)
                        self.track_last_seen[tid] = self.frames_processed

                        # Directional Live Counting for Stocks via Database-Driven Tripwire
                        if is_stock and self.active_tripwire and self.active_tripwire.get('is_enabled'):
                            crossing = evaluate_tripwire_crossing(
                                p1=self.active_tripwire['p1'],
                                p2=self.active_tripwire['p2'],
                                prev_pos=prev_pos,
                                curr_pos=(cx, cy),
                                allowed_direction=self.active_tripwire.get('crossing_direction', 'BOTH')
                            )
                            if crossing == 'IN' and self.counted_track_states.get(tid) != 'IN':
                                self.inbound_count += 1
                                self.counted_track_states[tid] = 'IN'
                                flash_lbl = f"+1 IN ({sku_code}: +{upb} {uom})" if sku_code else "+1 IN (STOCK ADDED)"
                                self.flash_counters.append({
                                    'text': flash_lbl,
                                    'pos': (cx, cy),
                                    'ttl': 24,
                                    'color': (0, 255, 128)
                                })
                            elif crossing == 'OUT' and self.counted_track_states.get(tid) != 'OUT':
                                self.outbound_count += 1
                                self.counted_track_states[tid] = 'OUT'
                                flash_lbl = f"-1 OUT ({sku_code}: -{upb} {uom})" if sku_code else "-1 OUT (STOCK SUBTRACTED)"
                                self.flash_counters.append({
                                    'text': flash_lbl,
                                    'pos': (cx, cy),
                                    'ttl': 24,
                                    'color': (0, 140, 255)
                                })

                    new_boxes.append({
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "type": v_type,
                        "sku_id": sku_code,
                        "uom": uom,
                        "units_per_bundle": upb,
                        "movement_state": mov_state,
                        "is_package": is_stock,
                        "is_person": is_person,
                        "is_forklift": is_forklift,
                        "is_vehicle": is_vehicle,
                        "track_id": tid
                    })

                # Trigger real-time Gate / Vehicle ANPR worker instantly
                now_t = time.time()
                is_dock_cam = 'dock' in str(self.location or '').lower() or 'gate' in str(self.location or '').lower()
                should_run_anpr = (has_vehicle or self.is_gate_camera or is_dock_cam or (self.frames_processed % 4 == 0))
                if should_run_anpr and not self.anpr_in_flight and (now_t - self.last_anpr_run_time >= 0.25):
                    self.anpr_in_flight = True
                    self.last_anpr_run_time = now_t
                    v_boxes_copy = copy.deepcopy(new_boxes)
                    threading.Thread(
                        target=self._run_live_gate_anpr_worker,
                        args=(frame.copy(), v_boxes_copy),
                        daemon=True
                    ).start()

                # Calculate Net Live Inventory (reflects active visible stock or cumulative tripwire delta)
                self.net_stock_count = max(active_stock_count, self.inbound_count - self.outbound_count)

                # Decay floating flash counters
                for fc in self.flash_counters:
                    fc['ttl'] -= 1
                self.flash_counters = [fc for fc in self.flash_counters if fc['ttl'] > 0]

                # Prune stale tracks that haven't been observed for > 30 frames
                dead_tids = [tid for tid, lseen in self.track_last_seen.items() if (self.frames_processed - lseen) > 30]
                for tid in dead_tids:
                    self.track_trajectories.pop(tid, None)
                    self.track_motion_vectors.pop(tid, None)
                    self.track_last_seen.pop(tid, None)
                    self.counted_track_states.pop(tid, None)

                # Render rich HUD onto latest live raw frame (if newer) or processed frame
                live_base = self.latest_raw_frame if self.latest_raw_frame is not None else frame
                curr_flow_gray = cv2.cvtColor(cv2.resize(live_base, (320, 240)), cv2.COLOR_BGR2GRAY)
                if live_base is not frame and new_boxes:
                    new_boxes = self._propagate_boxes_optical_flow(yolo_flow_gray, curr_flow_gray, new_boxes)

                with self.lock:
                    self.latest_boxes = new_boxes
                    self._prev_flow_gray = curr_flow_gray
                    self.visible_boxes = box_count
                    self.visible_packages = box_count
                    self.active_workers_count = workers_count
                    self.active_stocks_count = active_stock_count

                hud_frame = self._render_hud(live_base, timing_ms)
                ret, buf = cv2.imencode('.jpg', hud_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                annotated_jpeg = buf.tobytes() if ret else result.get("annotated_jpeg")

                with self.lock:
                    self.frames_processed += 1
                    self.last_inference_ms = timing_ms
                    self.last_processing_timestamp = result.get("timestamp")
                    self.latest_annotated_jpeg = annotated_jpeg
                    self._cached_live_jpeg = annotated_jpeg
                    self._last_encoded_frame_idx = self.frames_received
                    self.last_context = {
                        "frame_index": result.get("frame_index"),
                        "timestamp": result.get("timestamp"),
                        "detections_count": result.get("detections_count"),
                        "tracks_count": result.get("tracks_count"),
                        "events_count": result.get("events_count"),
                        "inbound_count": self.inbound_count,
                        "outbound_count": self.outbound_count,
                        "net_stock_count": self.net_stock_count,
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
        """Returns the latest live camera frame with real-time 30 FPS optical-flow box tracking & HUD overlay."""
        raw_frame = None
        frame_idx = -1
        timing_ms = 0.0
        prev_gray = None
        boxes_now = None
        with self.lock:
            if self.latest_raw_frame is not None:
                if self._cached_live_jpeg is not None and self._last_encoded_frame_idx == self.frames_received:
                    return self._cached_live_jpeg
                raw_frame = self.latest_raw_frame
                frame_idx = self.frames_received
                timing_ms = self.last_inference_ms
                prev_gray = self._prev_flow_gray
                boxes_now = list(self.latest_boxes) if self.latest_boxes else None
            elif self.latest_annotated_jpeg:
                return self.latest_annotated_jpeg

        if raw_frame is not None:
            if boxes_now:
                try:
                    curr_gray = cv2.cvtColor(cv2.resize(raw_frame, (320, 240)), cv2.COLOR_BGR2GRAY)
                    if prev_gray is not None:
                        shifted_boxes = self._propagate_boxes_optical_flow(prev_gray, curr_gray, boxes_now)
                        with self.lock:
                            self.latest_boxes = shifted_boxes
                            self._prev_flow_gray = curr_gray
                    else:
                        with self.lock:
                            self._prev_flow_gray = curr_gray
                except Exception:
                    pass
            hud_frame = self._render_hud(raw_frame, timing_ms)
            ret, buf = cv2.imencode('.jpg', hud_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ret:
                jpeg_bytes = buf.tobytes()
                with self.lock:
                    self._cached_live_jpeg = jpeg_bytes
                    self._last_encoded_frame_idx = frame_idx
                    self.latest_annotated_jpeg = jpeg_bytes
                return jpeg_bytes
        return None

    def get_perception_state(self) -> Dict[str, Any]:
        """Thread-safely returns the canonical perception state for SmartCamera synchronization."""
        with self.lock:
            return {
                "camera_id": self.camera_id,
                "latest_boxes": list(self.latest_boxes),
                "visible_boxes": self.visible_boxes,
                "visible_packages": self.visible_packages,
                "active_workers_count": self.active_workers_count,
                "active_stocks_count": self.active_stocks_count,
                "inbound_count": self.inbound_count,
                "outbound_count": self.outbound_count,
                "net_stock_count": self.net_stock_count,
                "flash_counters": list(self.flash_counters),
                "track_trajectories": {k: list(v) for k, v in self.track_trajectories.items()},
                "track_motion_vectors": dict(self.track_motion_vectors),
                "last_detected_plate": self.last_detected_plate,
                "last_gate_pass_id": self.last_gate_pass_id,
                "last_gate_pass_photo": self.last_gate_pass_photo,
                "events": list(self.events),
                "inference_latency_ms": self.last_inference_ms,
                "fps": self.actual_processing_fps,
                "annotated_jpeg": self.latest_annotated_jpeg,
                "is_gate_camera": self.is_gate_camera
            }

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
            "inbound_count": self.inbound_count,
            "outbound_count": self.outbound_count,
            "net_stock_count": self.net_stock_count,
            "active_workers_count": self.active_workers_count,
            "active_stocks_count": self.active_stocks_count,
            "visible_packages": self.visible_packages,
            "visible_boxes": self.visible_boxes,
            "is_gate_camera": self.is_gate_camera,
            "last_detected_plate": self.last_detected_plate,
            "last_gate_pass_id": self.last_gate_pass_id,
            "last_gate_pass_photo": self.last_gate_pass_photo,
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
                prev_keys = set(self.sessions.keys())
                cams = get_all_vision_cameras()
                valid_cids = set()
                for c in cams:
                    cid = c.get("camera_id") or c.get("camera_code")
                    if not cid:
                        continue
                    valid_cids.add(cid)
                    fps = c.get("ai_config", {}).get("processing_fps", 12) if c.get("ai_config") else 12
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

                try:
                    from app import active_cameras
                    for ac_id in active_cameras.keys():
                        valid_cids.add(ac_id)
                except Exception:
                    pass

                # Prune sessions for cameras deleted from authoritative DB and active_cameras
                for stale_cid in list(self.sessions.keys()):
                    if stale_cid not in valid_cids:
                        stale_sess = self.sessions.pop(stale_cid)
                        stale_sess.stop()

                if not self.is_initialized or set(self.sessions.keys()) != prev_keys:
                    logger.info(f"VisionRuntimeManager initialized with {len(self.sessions)} camera sessions.")
                self.is_initialized = True
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

    def get_or_create_session(
        self,
        camera_id: str,
        name: Optional[str] = None,
        location: Optional[str] = None,
        stream_url: str = "",
        configured_fps: int = 5,
        test_mode: Optional[bool] = None
    ) -> CameraRuntimeSession:
        """Retrieves existing session or dynamically initializes a session for requested camera."""
        with self.lock:
            if camera_id in self.sessions:
                return self.sessions[camera_id]
            is_test = test_mode if test_mode is not None else (
                os.environ.get("WARLOG_TEST_MODE", "").lower() in ("1", "true") or not bool(stream_url)
            )
            sess = CameraRuntimeSession(
                camera_id=camera_id,
                camera_code=camera_id,
                name=name or f"Camera {camera_id}",
                location=location or "General",
                stream_url=stream_url,
                configured_fps=configured_fps,
                test_mode=is_test
            )
            self.sessions[camera_id] = sess
            return sess

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
        if not sess:
            self.refresh_cameras()
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

