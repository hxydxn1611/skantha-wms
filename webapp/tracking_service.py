"""
AI Vision & Tracking Master - Multi-Object Tracking Engine
Part 6: ByteTrack-based Multi-Object Tracking Service.

Converts frame-by-frame object detections from Part 5 into persistent
temporary object tracks (Track IDs) across consecutive frames.

Key Principles:
- Reuses Part 5 Object Detection output (no duplicated YOLO inference).
- Track IDs are TEMPORARY session identifiers (NOT permanent asset/material IDs).
- Complete camera isolation: CAM-001 tracks are independent of CAM-002 tracks.
- Maintains in-memory recent center trajectories for visual motion verification.
- Integrates Part 4 Zone ROI containment context without generating events.
- Zero frame-by-frame persistence to the database.
"""

import os
import time
import uuid
import base64
import logging
from collections import deque
from datetime import datetime
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Tuple, Union

import cv2
import numpy as np

# Import detection engine and utilities from Part 5
from detection_service import (
    ObjectDetectionEngine,
    get_detection_engine,
    is_point_in_polygon,
    DEFAULT_CLASS_MAPPING,
    FALLBACK_CLASS_NAMES
)

try:
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.trackers.basetrack import TrackState
    BYTETRACKER_AVAILABLE = True
except ImportError:
    BYTETRACKER_AVAILABLE = False
    TrackState = None

logger = logging.getLogger(__name__)

# Class taxonomy integer mapping for tracker internal indexing
CLASS_CODE_TO_ID = {
    "BOX": 0,
    "WORKER": 1,
    "TRUCK": 2,
    "PALLET": 3,
    "FORKLIFT": 4,
    "BIN": 5
}
ID_TO_CLASS_CODE = {v: k for k, v in CLASS_CODE_TO_ID.items()}


class SimpleDetections:
    """
    Lightweight adapter wrapping detection bounding boxes, confidence scores,
    and class indices to conform with ByteTrack's required input interface.
    """
    def __init__(self, xywh: np.ndarray, conf: np.ndarray, cls: np.ndarray):
        self.xywh = np.asarray(xywh, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32).reshape(-1)
        self.cls = np.asarray(cls, dtype=np.float32).reshape(-1)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask: Any) -> 'SimpleDetections':
        return SimpleDetections(self.xywh[mask], self.conf[mask], self.cls[mask])


class CameraTrackingSession:
    """
    Per-camera tracking session maintaining isolated tracker instances,
    local Track ID namespaces, frame sequences, and in-memory trajectory history.
    """

    def __init__(
        self,
        camera_id: str,
        track_high_thresh: float = 0.25,
        track_low_thresh: float = 0.10,
        new_track_thresh: float = 0.25,
        track_buffer: int = 30,
        match_thresh: float = 0.80
    ):
        self.camera_id = camera_id
        self.session_id = f"sess_{camera_id}_{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.frame_index = 0
        self.total_tracks_spawned = 0

        # Tracker configuration arguments
        self.args = SimpleNamespace(
            track_high_thresh=float(track_high_thresh),
            track_low_thresh=float(track_low_thresh),
            new_track_thresh=float(new_track_thresh),
            track_buffer=int(track_buffer),
            match_thresh=float(match_thresh),
            fuse_score=True
        )

        # ByteTrack instance
        if BYTETRACKER_AVAILABLE:
            self.tracker = BYTETracker(self.args)
        else:
            self.tracker = None
            logger.error("BYTETracker from ultralytics is unavailable.")

        # Local Track ID mapping (ensures Camera-specific ID isolation & clean resets)
        self._raw_to_local_id: Dict[int, int] = {}
        self._next_local_id: int = 1

        # In-memory trajectory centers (max 25 recent points per track)
        self.trajectories: Dict[int, deque] = {}

        # Cache of latest active track records
        self.latest_tracks: List[Dict[str, Any]] = []

    def get_local_track_id(self, raw_id: int) -> int:
        """Map tracker internal global ID to camera-isolated local track ID starting at 1."""
        if raw_id not in self._raw_to_local_id:
            self._raw_to_local_id[raw_id] = self._next_local_id
            self._next_local_id += 1
            self.total_tracks_spawned += 1
        return self._raw_to_local_id[raw_id]

    def reset(self):
        """Reset the camera's tracking session and start track numbering fresh."""
        self.session_id = f"sess_{self.camera_id}_{uuid.uuid4().hex[:8]}"
        self.frame_index = 0
        self.total_tracks_spawned = 0
        self._raw_to_local_id.clear()
        self._next_local_id = 1
        self.trajectories.clear()
        self.latest_tracks.clear()
        if BYTETRACKER_AVAILABLE:
            self.tracker = BYTETracker(self.args)

    def update(
        self,
        detections: List[Dict[str, Any]],
        frame_width: int,
        frame_height: int,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Feed structured detection records into ByteTrack and compute persistent tracks.
        """
        self.frame_index += 1

        if self.tracker is None:
            return []

        # 1. Prepare SimpleDetections payload from Part 5 detection objects
        xywh_list = []
        conf_list = []
        cls_list = []

        for d in detections:
            bbox = d.get('bbox', {})
            x1 = float(bbox.get('x1', 0))
            y1 = float(bbox.get('y1', 0))
            x2 = float(bbox.get('x2', 0))
            y2 = float(bbox.get('y2', 0))
            w = max(1.0, x2 - x1)
            h = max(1.0, y2 - y1)
            xc = x1 + w / 2.0
            yc = y1 + h / 2.0

            cls_code = d.get('class_code', 'BOX')
            cls_idx = CLASS_CODE_TO_ID.get(cls_code, 0)
            conf = float(d.get('confidence', 0.5))

            xywh_list.append([xc, yc, w, h])
            conf_list.append(conf)
            cls_list.append(cls_idx)

        if len(xywh_list) > 0:
            det_input = SimpleDetections(
                xywh=np.array(xywh_list, dtype=np.float32),
                conf=np.array(conf_list, dtype=np.float32),
                cls=np.array(cls_list, dtype=np.float32)
            )
        else:
            det_input = SimpleDetections(
                xywh=np.empty((0, 4), dtype=np.float32),
                conf=np.empty(0, dtype=np.float32),
                cls=np.empty(0, dtype=np.float32)
            )

        # 2. Execute ByteTrack association
        try:
            self.tracker.update(det_input)
        except Exception as e:
            logger.error(f"ByteTrack update failed on frame {self.frame_index}: {e}")
            return []

        # 3. Extract Active Tracks
        current_tracks: List[Dict[str, Any]] = []

        for strack in self.tracker.tracked_stracks:
            # Check activation or tracked state
            is_active = getattr(strack, 'is_activated', False)
            state_val = getattr(strack, 'state', None)
            if not is_active and (TrackState and state_val != TrackState.Tracked):
                continue

            # Bounding box coordinates from ByteTrack top-left-width-height [tl_x, tl_y, w, h]
            tlwh = strack.tlwh
            x1 = int(round(max(0, float(tlwh[0]))))
            y1 = int(round(max(0, float(tlwh[1]))))
            x2 = int(round(min(frame_width, float(tlwh[0] + tlwh[2]))))
            y2 = int(round(min(frame_height, float(tlwh[1] + tlwh[3]))))

            # Ensure valid box dimensions
            if x2 <= x1:
                x2 = min(frame_width, x1 + 10)
            if y2 <= y1:
                y2 = min(frame_height, y1 + 10)

            # Normalized bounding box [0.0 - 1.0]
            norm_x1 = round(float(x1) / max(1, frame_width), 4)
            norm_y1 = round(float(y1) / max(1, frame_height), 4)
            norm_x2 = round(float(x2) / max(1, frame_width), 4)
            norm_y2 = round(float(y2) / max(1, frame_height), 4)

            # Center point
            cx = int(round((x1 + x2) / 2.0))
            cy = int(round((y1 + y2) / 2.0))
            norm_cx = round(float(cx) / max(1, frame_width), 4)
            norm_cy = round(float(cy) / max(1, frame_height), 4)

            # Map raw track ID to camera-isolated local Track ID
            local_id = self.get_local_track_id(int(strack.track_id))

            # Class code & name
            cls_idx = int(round(float(strack.cls))) if hasattr(strack, 'cls') else 0
            cls_code = ID_TO_CLASS_CODE.get(cls_idx, "BOX")
            cls_name = FALLBACK_CLASS_NAMES.get(cls_code, cls_code)

            # Append to recent center trajectory
            if local_id not in self.trajectories:
                self.trajectories[local_id] = deque(maxlen=25)
            self.trajectories[local_id].append({
                "x": norm_cx,
                "y": norm_cy,
                "px": cx,
                "py": cy,
                "frame": self.frame_index
            })

            # Check spatial ROI containment (Part 4 / Section 13)
            roi_info = {
                "configured": False,
                "inside": False,
                "zone_code": roi_zone_code or None
            }
            if roi_polygon and len(roi_polygon) >= 3:
                roi_info["configured"] = True
                roi_info["inside"] = is_point_in_polygon(
                    {"x": norm_cx, "y": norm_cy},
                    roi_polygon
                )

            track_record = {
                "track_id": local_id,
                "class_code": cls_code,
                "class_name": cls_name,
                "confidence": round(float(strack.score), 4),
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
                    "x": cx,
                    "y": cy
                },
                "center_normalized": {
                    "x": norm_cx,
                    "y": norm_cy
                },
                "roi": roi_info,
                "hits": int(strack.tracklet_len),
                "age": int(self.frame_index - strack.start_frame + 1),
                "first_seen_frame": int(strack.start_frame),
                "last_seen_frame": int(self.frame_index),
                "state": "Active",
                "trajectory_length": len(self.trajectories[local_id])
            }
            current_tracks.append(track_record)

        self.latest_tracks = current_tracks
        return current_tracks


class MultiObjectTrackingService:
    """
    Singleton service managing multi-camera tracking sessions, bridging Part 5
    detections to ByteTrack, generating synthetic test sequences, and rendering
    visual trajectories with bounding boxes.
    """

    def __init__(self):
        self.detection_engine = get_detection_engine()
        self.sessions: Dict[str, CameraTrackingSession] = {}
        logger.info("MultiObjectTrackingService initialized.")

    def get_session(self, camera_id: str) -> CameraTrackingSession:
        """Retrieve or create an isolated tracking session for a specific camera."""
        cam_key = str(camera_id).strip().upper() if camera_id else "DEFAULT"
        if cam_key not in self.sessions:
            self.sessions[cam_key] = CameraTrackingSession(camera_id=cam_key)
        return self.sessions[cam_key]

    def reset_session(self, camera_id: str) -> bool:
        """Reset tracking session for a specific camera."""
        cam_key = str(camera_id).strip().upper() if camera_id else "DEFAULT"
        if cam_key in self.sessions:
            self.sessions[cam_key].reset()
            return True
        return False

    def reset_all(self):
        """Reset all camera tracking sessions."""
        for session in self.sessions.values():
            session.reset()

    def get_sessions_status(self) -> List[Dict[str, Any]]:
        """Return operational status summary across all camera sessions."""
        status_list = []
        for cam_id, sess in self.sessions.items():
            status_list.append({
                "camera_id": cam_id,
                "session_id": sess.session_id,
                "frame_count": sess.frame_index,
                "active_tracks_count": len(sess.latest_tracks),
                "total_tracks_spawned": sess.total_tracks_spawned,
                "created_at": sess.created_at
            })
        return status_list

    def track_detections(
        self,
        detections: List[Dict[str, Any]],
        frame_width: int = 640,
        frame_height: int = 480,
        camera_id: str = "CAM-001",
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Feed pre-computed or mock detection objects directly into ByteTrack.
        """
        t_start = time.perf_counter()
        session = self.get_session(camera_id)
        tracks = session.update(
            detections=detections,
            frame_width=frame_width,
            frame_height=frame_height,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )
        tracking_ms = round((time.perf_counter() - t_start) * 1000, 2)

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": session.session_id,
            "frame_index": session.frame_index,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "active_track_count": len(tracks),
            "detection_count": len(detections),
            "performance": {
                "detection_ms": 0.0,
                "tracking_ms": tracking_ms,
                "total_ms": tracking_ms
            },
            "detections": detections,
            "tracks": tracks
        }

    def track_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        End-to-end tracking pipeline:
        Frame -> Part 5 Detection -> ByteTrack -> Persistent Track Records -> Visual Annotation.
        """
        t_total_start = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Parse image array for visualization
        raw_frame, parse_err = self.detection_engine._parse_image(frame_input)
        if parse_err or raw_frame is None:
            return {
                "success": False,
                "error": parse_err or "Invalid image input.",
                "camera_id": camera_id,
                "tracks": [],
                "active_track_count": 0
            }

        # 1. Execute Object Detection (Part 5)
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
                "error": det_result.get("error", "Detection failed"),
                "camera_id": camera_id,
                "tracks": [],
                "active_track_count": 0
            }

        detections = det_result.get("detections", [])
        w = det_result.get("frame_width", raw_frame.shape[1])
        h = det_result.get("frame_height", raw_frame.shape[0])
        det_timings = det_result.get("performance", {})
        det_ms = det_timings.get("inference_ms", 0.0)

        # 2. Get / create isolated session for camera
        session = self.get_session(camera_id)

        # 3. Update ByteTrack
        t_track_start = time.perf_counter()
        tracks = session.update(
            detections=detections,
            frame_width=w,
            frame_height=h,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )
        t_track_end = time.perf_counter()
        track_ms = round((t_track_end - t_track_start) * 1000, 2)
        total_ms = round((time.perf_counter() - t_total_start) * 1000, 2)

        # 4. Generate Visual Annotated Frame with Bounding Boxes & Trajectory Trails
        annotated_bgr = self.annotate_tracks(
            frame_bgr=raw_frame,
            tracks=tracks,
            camera_id=camera_id,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )

        _, buf = cv2.imencode('.jpg', annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": session.session_id,
            "frame_index": session.frame_index,
            "timestamp": timestamp_str,
            "frame_width": w,
            "frame_height": h,
            "active_track_count": len(tracks),
            "detection_count": len(detections),
            "performance": {
                "detection_ms": det_ms,
                "tracking_ms": track_ms,
                "total_ms": total_ms
            },
            "detections": detections,
            "tracks": tracks,
            "annotated_image_url": annotated_b64
        }

    def generate_motion_sequence_frame(
        self,
        step_index: int = 0,
        total_steps: int = 10
    ) -> np.ndarray:
        """
        Generate a photorealistic warehouse frame with controlled horizontal pan
        to guarantee reliable YOLO detection and smooth ByteTrack motion verification.
        """
        base_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "warehouse_carrier.jpg")
        if os.path.exists(base_path):
            base = cv2.imread(base_path)
            h, w = base.shape[:2]
            # Smooth subtle horizontal shift across frames without border distortion
            dx = int(round(np.sin(step_index * 0.45) * 6))
            dy = int(round(np.cos(step_index * 0.45) * 2))
            shifted = np.roll(base, dx, axis=1)
            shifted = np.roll(shifted, dy, axis=0)
            return shifted

        # Fallback to synthetic warehouse dock
        return self.detection_engine.create_synthetic_warehouse_frame()

    def run_sequence(
        self,
        camera_id: str = "CAM-001",
        num_frames: int = 5,
        conf_threshold: Optional[float] = 0.25,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a multi-frame sequential run to demonstrate persistent tracking across time.
        """
        session = self.get_session(camera_id)
        step_results = []
        final_annotated_url = ""

        for step in range(num_frames):
            frame = self.generate_motion_sequence_frame(step_index=step, total_steps=num_frames)
            res = self.track_frame(
                frame_input=frame,
                camera_id=camera_id,
                conf_threshold=conf_threshold,
                roi_polygon=roi_polygon,
                roi_zone_code=roi_zone_code
            )
            step_summary = {
                "frame_index": res.get("frame_index"),
                "detection_count": res.get("detection_count"),
                "active_track_count": res.get("active_track_count"),
                "track_ids": [t["track_id"] for t in res.get("tracks", [])],
                "performance": res.get("performance")
            }
            step_results.append(step_summary)
            final_annotated_url = res.get("annotated_image_url", "")

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": session.session_id,
            "frames_processed": num_frames,
            "step_results": step_results,
            "active_tracks": session.latest_tracks,
            "final_annotated_image_url": final_annotated_url
        }

    def annotate_tracks(
        self,
        frame_bgr: np.ndarray,
        tracks: List[Dict[str, Any]],
        camera_id: str = "CAM-001",
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> np.ndarray:
        """
        Render tracking visualization:
        - Bounding boxes labeled "CLASS | ID <track_id> | <conf>"
        - Colorful trajectory motion trails showing recent center points
        - ROI polygon overlay with spatial context tags
        - Telemetry strip at bottom
        """
        annotated = frame_bgr.copy()
        h, w = annotated.shape[:2]
        session = self.get_session(camera_id)

        class_colors = {
            "WORKER": (40, 200, 70),     # Vibrant Green
            "TRUCK": (230, 140, 30),     # Amber / Orange
            "BOX": (20, 160, 240),       # Sky Blue
            "PALLET": (180, 80, 220),    # Violet
            "FORKLIFT": (50, 100, 230),  # Coral Red
            "BIN": (220, 190, 40)        # Gold
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

        # 2. Draw Trajectory Motion Trails for Active Tracks
        for track in tracks:
            tid = track["track_id"]
            history = session.trajectories.get(tid, [])
            cls_code = track.get("class_code", "OBJ")
            color = class_colors.get(cls_code, (0, 255, 255))

            if len(history) >= 2:
                pts_list = [(p["px"], p["py"]) for p in history]
                for i in range(1, len(pts_list)):
                    thickness = max(1, int(1 + (i / len(pts_list)) * 2))
                    cv2.line(annotated, pts_list[i - 1], pts_list[i], color, thickness, cv2.LINE_AA)

                # Draw trajectory point dots
                for p in pts_list:
                    cv2.circle(annotated, (p[0], p[1]), 2, (255, 255, 255), -1)

        # 3. Draw Bounding Boxes, Temporary Track ID Badges, and Center Dots
        for track in tracks:
            bbox = track["bbox"]
            x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
            cls_code = track.get("class_code", "OBJ")
            conf = track.get("confidence", 0.0)
            tid = track["track_id"]
            color = class_colors.get(cls_code, (0, 255, 255))

            # Bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Center tracking dot
            cx, cy = track["center"]["x"], track["center"]["y"]
            cv2.circle(annotated, (cx, cy), 5, color, -1)
            cv2.circle(annotated, (cx, cy), 7, (0, 0, 0), 1)

            # Label text adhering to Section 11 specifications:
            # "CLASS | ID <track_id> | <conf>"
            label_text = f"{cls_code} | ID {tid} | {conf:.2f}"
            roi_info = track.get("roi", {})
            if roi_info.get("configured"):
                label_text += " [IN ROI]" if roi_info.get("inside") else " [OUT]"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.48
            thickness = 1
            (text_w, text_h), _ = cv2.getTextSize(label_text, font, font_scale, thickness)

            badge_y1 = max(0, y1 - text_h - 8)
            badge_y2 = y1
            badge_x1 = x1
            badge_x2 = min(w, x1 + text_w + 10)

            # Colored header pill
            cv2.rectangle(annotated, (badge_x1, badge_y1), (badge_x2, badge_y2), color, -1)
            cv2.putText(annotated, label_text, (badge_x1 + 5, badge_y2 - 4),
                        font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

        # 4. Telemetry status strip at bottom
        cv2.rectangle(annotated, (0, h - 28), (w, h), (15, 23, 42), -1)
        stat_text = (
            f"{camera_id} | Session: {session.session_id[-8:]} | "
            f"Frame #{session.frame_index} | Active Tracks: {len(tracks)}"
        )
        cv2.putText(annotated, stat_text, (10, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 210, 220), 1, cv2.LINE_AA)

        return annotated


# Global Singleton Service
_global_tracking_service: Optional[MultiObjectTrackingService] = None


def get_tracking_service() -> MultiObjectTrackingService:
    """Retrieve or lazily initialize the singleton MultiObjectTrackingService."""
    global _global_tracking_service
    if _global_tracking_service is None:
        _global_tracking_service = MultiObjectTrackingService()
    return _global_tracking_service
