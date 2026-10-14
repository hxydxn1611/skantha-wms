"""
AI Vision & Tracking Master - Database-Driven Zone & Tripwire Engine
Phase 2: Dynamic persistent zone and tripwire evaluation, resolution-independent
coordinates, directional crossing detection, and deduplication.
"""

import math
import logging
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


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


def denormalize_coordinate(x: float, y: float, frame_w: int, frame_h: int) -> Tuple[int, int]:
    """
    Converts normalized (0.0 - 1.0) or absolute pixel coordinates to frame pixel coordinates.
    Handles resolution changes consistently without corrupting stored database values.
    """
    # If coordinate is already in pixel space (> 1.5)
    px = int(round(x)) if x > 1.5 else int(round(x * frame_w))
    py = int(round(y)) if y > 1.5 else int(round(y * frame_h))
    
    # Clamp within frame bounds
    px = max(0, min(frame_w, px))
    py = max(0, min(frame_h, py))
    return px, py


def get_camera_tripwire(camera_id: str, frame_w: int = 640, frame_h: int = 480) -> Optional[Dict[str, Any]]:
    """
    Queries the database for active tripwire configurations for a specific camera.
    Returns None if no tripwire is configured or if the tripwire is disabled.
    """
    if not camera_id:
        return None

    try:
        from db import get_camera_rois
        rois = get_camera_rois(camera_id)
        if not rois:
            return None

        for r in rois:
            shape_type = str(r.get("shape_type", "")).strip().upper()
            is_enabled = bool(r.get("is_enabled", True))
            
            # Check for LINE or TRIPWIRE shapes that are enabled
            if shape_type in ("TRIPWIRE", "LINE") and is_enabled:
                coords = r.get("coordinates", [])
                if isinstance(coords, list) and len(coords) >= 2:
                    p1_raw = coords[0]
                    p2_raw = coords[1]
                    
                    p1_px = denormalize_coordinate(float(p1_raw.get("x", 0.0)), float(p1_raw.get("y", 0.0)), frame_w, frame_h)
                    p2_px = denormalize_coordinate(float(p2_raw.get("x", 1.0)), float(p2_raw.get("y", 1.0)), frame_w, frame_h)
                    
                    return {
                        "id": r.get("id"),
                        "zone_id": r.get("zone_id"),
                        "zone_code": r.get("zone_code", "TRIPWIRE"),
                        "zone_name": r.get("zone_name", "Tripwire Counting Line"),
                        "shape_type": shape_type,
                        "raw_coordinates": coords,
                        "p1": p1_px,
                        "p2": p2_px,
                        "is_enabled": True,
                        "crossing_direction": str(r.get("crossing_direction", "BOTH")).strip().upper()
                    }
    except Exception as e:
        logger.warning(f"Error querying tripwire for camera '{camera_id}': {e}")

    return None


def evaluate_tripwire_crossing(
    p1: Tuple[int, int],
    p2: Tuple[int, int],
    prev_pos: Tuple[int, int],
    curr_pos: Tuple[int, int],
    deadband: float = 8.0,
    allowed_direction: str = "BOTH"
) -> Optional[str]:
    """
    Evaluates whether a track vector (prev_pos -> curr_pos) crossed the tripwire line segment (p1 -> p2).
    Uses 2D vector cross-product signed distances for resolution-independent orientation testing.
    
    Returns:
        'IN' (crossed in Inbound direction / Stock Added)
        'OUT' (crossed in Outbound direction / Stock Subtracted)
        None (no crossing detected or disallowed direction)
    """
    vx = p2[0] - p1[0]
    vy = p2[1] - p1[1]
    seg_len = math.hypot(vx, vy)
    if seg_len < 1.0:
        return None

    # Calculate signed perpendicular distance from line to previous and current positions
    # Positive side vs negative side determined by line orientation vector
    cross_prev = (vx * (prev_pos[1] - p1[1]) - vy * (prev_pos[0] - p1[0])) / seg_len
    cross_curr = (vx * (curr_pos[1] - p1[1]) - vy * (curr_pos[0] - p1[0])) / seg_len

    detected_direction = None

    # Crossing from negative side to positive side (Inbound crossing)
    if cross_prev < -deadband and cross_curr >= (deadband * 0.4):
        detected_direction = "IN"

    # Crossing from positive side to negative side (Outbound crossing)
    elif cross_prev > deadband and cross_curr <= -(deadband * 0.4):
        detected_direction = "OUT"

    if not detected_direction:
        return None

    # Directional filter check
    allowed = str(allowed_direction).strip().upper()
    if allowed == "INBOUND_ONLY" and detected_direction != "IN":
        return None
    if allowed == "OUTBOUND_ONLY" and detected_direction != "OUT":
        return None

    return detected_direction
