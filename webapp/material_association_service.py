"""
AI Vision & Tracking Master - Material Association Engine
Part 9: Material-Agnostic, Evidence-Based Association Layer for Automotive Warehouses.

Core Principle: CO-VISIBILITY IS NOT ASSOCIATION.
Co-presence in the same image frame is strictly insufficient for association.
All associations must be established on explicit, explainable evidence:
  1. Same camera
  2. Same active session
  3. Same relevant warehouse zone / ROI
  4. Temporal overlap
  5. Spatial proximity between tracked objects (Euclidean distance on normalized coordinates)
  6. Sustained proximity across multiple consecutive frames (min 3 frames)
  7. Movement / direction consistency
  8. Validated physical identity (barcode/QR/OCR/WMS master-data)

Supported Association Types:
  - TRUCK <-> MATERIAL
  - TRUCK <-> CONTAINER/BOX
  - WORKER <-> MATERIAL
  - MATERIAL <-> BIN
  - MATERIAL <-> CONTAINER
while preserving existing BOX-based associations for full backward compatibility.

Track vs Real-World Identity:
  - Track-level association: Truck Track #T <-> Material Track #M
  - Real-world association: Truck GP-1000 <-> Material AUTO-GLASS-01
  Real-world identity association is derived ONLY when BOTH underlying tracks
  have been successfully IDENTIFIED and VALIDATED by Part 8 master-data binding,
  and identity is neither UNIDENTIFIED, AMBIGUOUS, nor CONFLICT.

Container vs Material Distinction:
  - A container/box may carry or contain automotive material (e.g. BOX-101 carrying AUTO-GLASS-01).
  - The container identity (BOX-101) is strictly distinct from the contained SKU (AUTO-GLASS-01).
  - The system never equates or merges the container identity with the contained SKU.

Cross-Camera Continuity:
  - NO visual cross-camera Re-ID or appearance embeddings.
  - Cross-camera continuity occurs strictly through validated physical identity
    (barcode / QR / OCR / WMS SKU master).

Zero Worker Productivity Inference:
  - Worker <-> Material association records physical co-location and handling evidence only.
  - Zero calculation of worker productivity, speed, performance, KPIs, or behavioral intent.

Zero Database Writes:
  - All association state is managed strictly in-memory per camera session.
  - Zero database schema modifications, zero SQL INSERT/UPDATE statements, zero inventory changes.
"""

import math
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set, Union

import cv2
import numpy as np

# Import Part 8 MultiObjectValidationService
from validation_service import (
    get_validation_service,
    MultiObjectValidationService
)
from detection_service import is_point_in_polygon
import db

logger = logging.getLogger(__name__)


# ============================================================================
# 1. CONSTANTS, ENUMS & CONFIGURATION
# ============================================================================

class AssociationType:
    """Explicit association types supported by the Material Association Engine."""
    TRUCK_MATERIAL = "TRUCK_MATERIAL"
    TRUCK_CONTAINER = "TRUCK_CONTAINER"
    WORKER_MATERIAL = "WORKER_MATERIAL"
    MATERIAL_BIN = "MATERIAL_BIN"
    MATERIAL_CONTAINER = "MATERIAL_CONTAINER"

    # Backward compatibility aliases
    TRUCK_BOX = "TRUCK_CONTAINER"
    WORKER_BOX = "WORKER_MATERIAL"
    BOX_BIN = "MATERIAL_BIN"


class AssociationState:
    """Standardized lifecycle states for material associations."""
    CANDIDATE = "CANDIDATE"      # Evidence accumulating or ambiguous, confirmation threshold not yet reached
    CONFIRMED = "CONFIRMED"      # Satisfied consecutive frames, score, distance, and same-zone requirements
    REJECTED = "REJECTED"        # Disqualified (e.g. mismatched zones, excessive distance, or invalid evidence)
    EXPIRED = "EXPIRED"          # One or both objects departed frame, or association timed out


# Object classification categories
TRUCK_CLASSES = {"TRUCK", "CARRIER", "VEHICLE"}
WORKER_CLASSES = {"WORKER", "PERSON", "OPERATOR"}
BIN_CLASSES = {"BIN", "STORAGE_BIN", "TOTE", "BAY", "SLOT", "LOCATION", "STORAGE BIN / TOTE"}
CONTAINER_CLASSES = {"CONTAINER", "PALLET", "TRAY", "CRATE"}
BOX_CLASSES = {"BOX", "CARTON", "PACKAGE", "CARDBOARD BOX"}
AUTOMOTIVE_MATERIAL_CLASSES = {"MATERIAL", "GLASS", "ROD", "PART", "COMPONENT", "FASTENER", "SKU"}


@dataclass
class MaterialAssociationConfig:
    """
    Explicit, documented configuration parameters for the Material Association Engine.
    No hard-coded unexplained magic numbers.
    """
    # Temporal persistence threshold: minimum consecutive frames to confirm association
    min_consecutive_frames: int = 3

    # Maximum normalized Euclidean center-to-center distance for spatial proximity [0.0 - 1.0]
    max_normalized_distance: float = 0.40

    # Minimum composite association score required for CONFIRMED status [0.0 - 1.0]
    min_association_score: float = 0.70

    # Timeout in frames before missing/departed track association transitions to EXPIRED
    association_timeout_frames: int = 4

    # Strict requirement: both objects must reside in the same warehouse zone/ROI for confirmation
    require_same_zone: bool = True

    # Ambiguity delta threshold: if competing candidates have scores within this delta, flag as AMBIGUOUS
    ambiguity_threshold_delta: float = 0.15

    # Evidence score component weights (must sum to 1.0)
    weight_spatial: float = 0.30
    weight_zone: float = 0.30
    weight_temporal: float = 0.25
    weight_movement: float = 0.15

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_consecutive_frames": self.min_consecutive_frames,
            "max_normalized_distance": self.max_normalized_distance,
            "min_association_score": self.min_association_score,
            "association_timeout_frames": self.association_timeout_frames,
            "require_same_zone": self.require_same_zone,
            "ambiguity_threshold_delta": self.ambiguity_threshold_delta,
            "weights": {
                "spatial": self.weight_spatial,
                "zone": self.weight_zone,
                "temporal": self.weight_temporal,
                "movement": self.weight_movement
            }
        }


# ============================================================================
# 2. EVIDENCE & ASSOCIATION DATA STRUCTURES
# ============================================================================

@dataclass
class MaterialAssociationEvidence:
    """
    Structured, fully transparent, explainable evidence record for an association pair.
    Explicitly NOT presented as a black-box probability.
    """
    association_type: str
    same_camera: bool
    same_zone: bool
    primary_zone: Optional[str]
    secondary_zone: Optional[str]
    temporal_overlap: bool
    spatial_proximity: bool
    consecutive_frames: int
    missed_frames: int
    normalized_distance: float
    max_allowed_distance: float
    spatial_proximity_score: float
    temporal_persistence_score: float
    zone_score: float
    movement_consistency_score: float
    validated_physical_identity: bool
    is_ambiguous: bool
    competing_track_ids: List[int] = field(default_factory=list)
    ambiguity_reason: Optional[str] = None
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "association_type": self.association_type,
            "same_camera": self.same_camera,
            "same_zone": self.same_zone,
            "primary_zone": self.primary_zone,
            "secondary_zone": self.secondary_zone,
            "temporal_overlap": self.temporal_overlap,
            "spatial_proximity": self.spatial_proximity,
            "consecutive_frames": self.consecutive_frames,
            "missed_frames": self.missed_frames,
            "normalized_distance": round(self.normalized_distance, 4),
            "max_allowed_distance": self.max_allowed_distance,
            "spatial_proximity_score": round(self.spatial_proximity_score, 4),
            "temporal_persistence_score": round(self.temporal_persistence_score, 4),
            "zone_score": round(self.zone_score, 4),
            "movement_consistency_score": round(self.movement_consistency_score, 4),
            "validated_physical_identity": self.validated_physical_identity,
            "is_ambiguous": self.is_ambiguous,
            "competing_track_ids": self.competing_track_ids,
            "ambiguity_reason": self.ambiguity_reason,
            "explanation": self.explanation
        }


class MaterialAssociation:
    """
    Represents an active or historical pairwise association between two tracked objects
    (Truck <-> Material, Truck <-> Container, Worker <-> Material, Material <-> Bin, Material <-> Container).
    """
    def __init__(
        self,
        camera_id: str,
        association_type: str,
        primary_track_id: int,
        secondary_track_id: int,
        primary_class: str,
        secondary_class: str,
        initial_frame: int
    ):
        self.camera_id = camera_id
        self.association_type = association_type
        self.primary_track_id = primary_track_id
        self.secondary_track_id = secondary_track_id
        self.primary_class = primary_class
        self.secondary_class = secondary_class
        self.first_seen_frame = initial_frame
        self.last_seen_frame = initial_frame
        self.consecutive_frames = 1
        self.missed_frames = 0
        self.status = AssociationState.CANDIDATE
        self.association_score = 0.0
        self.evidence: Optional[MaterialAssociationEvidence] = None

        # Track metadata cache
        self.primary_identity: Dict[str, Any] = {"value": None, "validation_status": "NOT_APPLICABLE"}
        self.secondary_identity: Dict[str, Any] = {"value": None, "validation_status": "NOT_APPLICABLE"}
        self.real_world_association: Optional[Dict[str, Any]] = None

        # Coordinates for visualization
        self.primary_center: Tuple[float, float] = (0.0, 0.0)
        self.secondary_center: Tuple[float, float] = (0.0, 0.0)
        self.primary_bbox: Dict[str, int] = {}
        self.secondary_bbox: Dict[str, int] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "association_type": self.association_type,
            "primary_track_id": self.primary_track_id,
            "secondary_track_id": self.secondary_track_id,
            "primary_class": self.primary_class,
            "secondary_class": self.secondary_class,
            "primary_identity": self.primary_identity,
            "secondary_identity": self.secondary_identity,
            "status": self.status,
            "association_score": round(self.association_score, 4),
            "evidence": self.evidence.to_dict() if self.evidence else {},
            "real_world_association": self.real_world_association,
            "first_seen_frame": self.first_seen_frame,
            "last_seen_frame": self.last_seen_frame,
            "consecutive_frames": self.consecutive_frames,
            "missed_frames": self.missed_frames,
            "primary_center": [round(c, 4) for c in self.primary_center],
            "secondary_center": [round(c, 4) for c in self.secondary_center]
        }


# ============================================================================
# 3. CAMERA MATERIAL ASSOCIATION SESSION (TEMPORAL STATE MANAGER)
# ============================================================================

class CameraMaterialAssociationSession:
    """
    Manages in-memory temporal state, pairwise tracking, and association lifecycle
    for a single camera source. Fully isolated from other cameras.
    """
    def __init__(self, camera_id: str, config: Optional[MaterialAssociationConfig] = None):
        self.camera_id = camera_id
        self.config = config or MaterialAssociationConfig()
        self.frame_index = 0
        # Active associations keyed by (association_type, primary_track_id, secondary_track_id)
        self.associations: Dict[Tuple[str, int, int], MaterialAssociation] = {}
        # Track velocity / center history for movement consistency
        self.track_prev_centers: Dict[int, Tuple[float, float]] = {}
        self.last_update_time = time.time()

    def reset(self):
        """Reset temporal state for this camera session."""
        self.frame_index = 0
        self.associations.clear()
        self.track_prev_centers.clear()
        self.last_update_time = time.time()
        logger.info(f"Material association session for camera '{self.camera_id}' reset.")

    def _resolve_zone_for_track(
        self,
        track: Dict[str, Any],
        camera_zones: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Determine warehouse zone/ROI for a track."""
        roi_info = track.get("roi", {})
        if roi_info.get("inside") and roi_info.get("zone_code"):
            return str(roi_info["zone_code"]).strip()
        if track.get("roi_zone_code"):
            return str(track.get("roi_zone_code")).strip()

        center = self._get_normalized_center(track)
        center_dict = {"x": center[0], "y": center[1]}
        for zone in camera_zones:
            coords = zone.get("coordinates", [])
            zone_code = zone.get("zone_code")
            if coords and zone_code and is_point_in_polygon(center_dict, coords):
                return str(zone_code).strip()

        return None

    def _get_normalized_center(self, track: Dict[str, Any]) -> Tuple[float, float]:
        """Get normalized (cx, cy) center coordinate."""
        if "center_normalized" in track and track["center_normalized"]:
            cn = track["center_normalized"]
            return float(cn[0]), float(cn[1])

        norm_bbox = track.get("bbox_normalized", {})
        if norm_bbox and "x1" in norm_bbox and "y2" in norm_bbox:
            cx = (float(norm_bbox.get("x1", 0.0)) + float(norm_bbox.get("x2", 0.0))) / 2.0
            cy = (float(norm_bbox.get("y1", 0.0)) + float(norm_bbox.get("y2", 0.0))) / 2.0
            return cx, cy

        bbox = track.get("bbox", {})
        if bbox:
            x1 = float(bbox.get("x1", 0))
            y1 = float(bbox.get("y1", 0))
            x2 = float(bbox.get("x2", 0))
            y2 = float(bbox.get("y2", 0))
            fw = float(track.get("frame_width", 1280) or 1280)
            fh = float(track.get("frame_height", 720) or 720)
            return ((x1 + x2) / 2.0) / max(1.0, fw), ((y1 + y2) / 2.0) / max(1.0, fh)

        return (0.5, 0.5)

    def _calculate_euclidean_distance(
        self,
        c1: Tuple[float, float],
        c2: Tuple[float, float]
    ) -> float:
        """Calculate Euclidean distance between two normalized coordinate points [0.0 - 1.414]."""
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        return math.sqrt(dx * dx + dy * dy)

    def _calculate_movement_consistency(
        self,
        t1_id: int,
        t1_center: Tuple[float, float],
        t2_id: int,
        t2_center: Tuple[float, float]
    ) -> float:
        """
        Evaluate movement direction and velocity consistency between two objects.
        If both static, returns 1.0. If moving together, returns cosine similarity alignment.
        """
        if t1_id not in self.track_prev_centers or t2_id not in self.track_prev_centers:
            return 1.0  # Initial frame default

        prev1 = self.track_prev_centers[t1_id]
        prev2 = self.track_prev_centers[t2_id]

        v1 = (t1_center[0] - prev1[0], t1_center[1] - prev1[1])
        v2 = (t2_center[0] - prev2[0], t2_center[1] - prev2[1])

        speed1 = math.hypot(v1[0], v1[1])
        speed2 = math.hypot(v2[0], v2[1])

        # If both are essentially stationary (< 0.005 displacement), consistency is high
        if speed1 < 0.005 and speed2 < 0.005:
            return 1.0

        # If one moves fast and the other is static, lower consistency
        if (speed1 > 0.03 and speed2 < 0.005) or (speed2 > 0.03 and speed1 < 0.005):
            return 0.50

        # Both moving: check dot product alignment
        mag = speed1 * speed2
        if mag > 0:
            cos_sim = (v1[0] * v2[0] + v1[1] * v2[1]) / mag
            # Normalize [-1, 1] to [0, 1]
            return max(0.0, min(1.0, (cos_sim + 1.0) / 2.0))

        return 0.80

    def update(
        self,
        tracks: List[Dict[str, Any]],
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> List[MaterialAssociation]:
        """
        Update temporal association states for all tracked objects in current frame.
        Evaluates evidence, detects ambiguity, arbitrates exclusivity, and updates states.
        """
        self.frame_index += 1
        self.last_update_time = time.time()
        camera_zones = camera_zones or []

        # 1. Categorize tracks into distinct object classes
        truck_tracks: List[Dict[str, Any]] = []
        worker_tracks: List[Dict[str, Any]] = []
        bin_tracks: List[Dict[str, Any]] = []
        container_tracks: List[Dict[str, Any]] = []
        material_tracks: List[Dict[str, Any]] = []
        box_tracks: List[Dict[str, Any]] = []

        for t in tracks:
            cls_code = str(t.get("class_code", "")).upper()
            t["_norm_center"] = self._get_normalized_center(t)
            t["_resolved_zone"] = self._resolve_zone_for_track(t, camera_zones)

            if cls_code in TRUCK_CLASSES:
                truck_tracks.append(t)
            elif cls_code in WORKER_CLASSES:
                worker_tracks.append(t)
            elif cls_code in BIN_CLASSES:
                bin_tracks.append(t)
            elif cls_code in CONTAINER_CLASSES:
                container_tracks.append(t)
            elif cls_code in AUTOMOTIVE_MATERIAL_CLASSES:
                material_tracks.append(t)
            elif cls_code in BOX_CLASSES:
                box_tracks.append(t)

        # 2. Form candidate pairs across supported association types
        # Candidate pairs list: (assoc_type, primary_track, secondary_track, primary_cls, secondary_cls)
        candidate_pairs_to_evaluate: List[Tuple[str, Dict[str, Any], Dict[str, Any], str, str]] = []

        # TRUCK <-> MATERIAL
        for trk in truck_tracks:
            for mat in material_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.TRUCK_MATERIAL, trk, mat,
                    str(trk.get("class_code", "TRUCK")).upper(),
                    str(mat.get("class_code", "MATERIAL")).upper()
                ))
            # Backward compatibility: Truck <-> Box
            for box in box_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.TRUCK_CONTAINER, trk, box,
                    str(trk.get("class_code", "TRUCK")).upper(),
                    str(box.get("class_code", "BOX")).upper()
                ))
            # Truck <-> Container
            for cont in container_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.TRUCK_CONTAINER, trk, cont,
                    str(trk.get("class_code", "TRUCK")).upper(),
                    str(cont.get("class_code", "CONTAINER")).upper()
                ))

        # WORKER <-> MATERIAL
        for wrk in worker_tracks:
            for mat in material_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.WORKER_MATERIAL, wrk, mat,
                    str(wrk.get("class_code", "WORKER")).upper(),
                    str(mat.get("class_code", "MATERIAL")).upper()
                ))
            # Backward compatibility: Worker <-> Box
            for box in box_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.WORKER_MATERIAL, wrk, box,
                    str(wrk.get("class_code", "WORKER")).upper(),
                    str(box.get("class_code", "BOX")).upper()
                ))
            # Worker <-> Container
            for cont in container_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.WORKER_MATERIAL, wrk, cont,
                    str(wrk.get("class_code", "WORKER")).upper(),
                    str(cont.get("class_code", "CONTAINER")).upper()
                ))

        # MATERIAL <-> BIN
        for bn in bin_tracks:
            for mat in material_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.MATERIAL_BIN, mat, bn,
                    str(mat.get("class_code", "MATERIAL")).upper(),
                    str(bn.get("class_code", "BIN")).upper()
                ))
            # Backward compatibility: Box <-> Bin
            for box in box_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.MATERIAL_BIN, box, bn,
                    str(box.get("class_code", "BOX")).upper(),
                    str(bn.get("class_code", "BIN")).upper()
                ))
            # Container <-> Bin
            for cont in container_tracks:
                candidate_pairs_to_evaluate.append((
                    AssociationType.MATERIAL_BIN, cont, bn,
                    str(cont.get("class_code", "CONTAINER")).upper(),
                    str(bn.get("class_code", "BIN")).upper()
                ))

        # MATERIAL <-> CONTAINER (Container contains/carries material)
        for cont in (container_tracks + box_tracks):
            for mat in material_tracks:
                # Ensure we don't associate a track with itself
                if int(cont.get("track_id", -1)) != int(mat.get("track_id", -2)):
                    candidate_pairs_to_evaluate.append((
                        AssociationType.MATERIAL_CONTAINER, cont, mat,
                        str(cont.get("class_code", "CONTAINER")).upper(),
                        str(mat.get("class_code", "MATERIAL")).upper()
                    ))

        # 3. Compute independent pairwise evidence for ALL active candidate combinations
        current_pair_keys: Set[Tuple[str, int, int]] = set()
        active_candidates: Dict[Tuple[str, int, int], Dict[str, Any]] = {}

        for assoc_type, p_track, s_track, p_cls, s_cls in candidate_pairs_to_evaluate:
            p_id = int(p_track.get("track_id", 0))
            s_id = int(s_track.get("track_id", 0))
            pair_key = (assoc_type, p_id, s_id)
            current_pair_keys.add(pair_key)

            p_center = p_track["_norm_center"]
            s_center = s_track["_norm_center"]
            p_zone = p_track["_resolved_zone"]
            s_zone = s_track["_resolved_zone"]

            # Spatial distance
            norm_dist = self._calculate_euclidean_distance(p_center, s_center)
            in_proximity = norm_dist <= self.config.max_normalized_distance

            # Zone match
            same_zone = (p_zone is not None and s_zone is not None and p_zone == s_zone)

            # Movement consistency
            mov_score = self._calculate_movement_consistency(p_id, p_center, s_id, s_center)

            # Existing association object lookup for continuity
            existing = self.associations.get(pair_key)
            if existing and existing.status != AssociationState.EXPIRED:
                consecutive_frames = existing.consecutive_frames + 1
                first_seen = existing.first_seen_frame
            else:
                consecutive_frames = 1
                first_seen = self.frame_index

            # Signal Scores:
            # Spatial Proximity Score [0.0 - 1.0]: 1.0 at distance 0, 0.0 at max_normalized_distance
            if norm_dist <= self.config.max_normalized_distance:
                spatial_score = 1.0 - (norm_dist / max(0.001, self.config.max_normalized_distance))
            else:
                spatial_score = 0.0

            # Zone Score: 1.0 if identical zone, 0.0 otherwise
            zone_score = 1.0 if same_zone else 0.0

            # Temporal Persistence Score: ramps up over min_consecutive_frames
            temporal_score = min(1.0, consecutive_frames / float(max(1, self.config.min_consecutive_frames)))

            # Composite Score
            raw_score = (
                (self.config.weight_spatial * spatial_score) +
                (self.config.weight_zone * zone_score) +
                (self.config.weight_temporal * temporal_score) +
                (self.config.weight_movement * mov_score)
            )
            score = round(min(1.0, max(0.0, raw_score)), 4)

            # Check validated physical identity
            p_val = p_track.get("validation", {}).get("status") == "VALIDATED"
            s_val = s_track.get("validation", {}).get("status") == "VALIDATED"
            val_phys_id = (p_val and s_val)

            active_candidates[pair_key] = {
                "assoc_type": assoc_type,
                "primary": p_track,
                "secondary": s_track,
                "primary_id": p_id,
                "secondary_id": s_id,
                "primary_cls": p_cls,
                "secondary_cls": s_cls,
                "primary_center": p_center,
                "secondary_center": s_center,
                "primary_zone": p_zone,
                "secondary_zone": s_zone,
                "same_zone": same_zone,
                "in_proximity": in_proximity,
                "norm_dist": norm_dist,
                "spatial_score": spatial_score,
                "zone_score": zone_score,
                "temporal_score": temporal_score,
                "movement_score": mov_score,
                "consecutive_frames": consecutive_frames,
                "first_seen": first_seen,
                "score": score,
                "validated_physical_identity": val_phys_id
            }

        # 4. Ambiguity Detection (Competing candidates for same target)
        # Secondary object competing for multiple primaries of the same type (e.g. 2 trucks for 1 material)
        secondary_competing: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for pair_key, cand in active_candidates.items():
            assoc_type, p_id, s_id = pair_key
            if cand["in_proximity"]:
                secondary_competing.setdefault((assoc_type, s_id), []).append(cand)

        ambiguous_secondary_keys: Dict[Tuple[str, int], Tuple[List[int], str]] = {}
        for (assoc_type, s_id), cands in secondary_competing.items():
            if len(cands) > 1:
                cands.sort(key=lambda x: x["score"], reverse=True)
                top_score = cands[0]["score"]
                second_score = cands[1]["score"]
                if abs(top_score - second_score) <= self.config.ambiguity_threshold_delta:
                    competing_ids = [c["primary_id"] for c in cands]
                    reason = (
                        f"Object Track #{s_id} is simultaneously in proximity to multiple competing candidates "
                        f"({', '.join(f'Track #{cid}' for cid in competing_ids)}) with score difference "
                        f"{abs(top_score - second_score):.3f} <= threshold delta {self.config.ambiguity_threshold_delta}."
                    )
                    ambiguous_secondary_keys[(assoc_type, s_id)] = (competing_ids, reason)

        # Primary object competing for multiple secondaries of same type (e.g. 2 bins for 1 material)
        primary_competing: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for pair_key, cand in active_candidates.items():
            assoc_type, p_id, s_id = pair_key
            if cand["in_proximity"]:
                primary_competing.setdefault((assoc_type, p_id), []).append(cand)

        ambiguous_primary_keys: Dict[Tuple[str, int], Tuple[List[int], str]] = {}
        for (assoc_type, p_id), cands in primary_competing.items():
            if len(cands) > 1:
                cands.sort(key=lambda x: x["score"], reverse=True)
                top_score = cands[0]["score"]
                second_score = cands[1]["score"]
                if abs(top_score - second_score) <= self.config.ambiguity_threshold_delta:
                    competing_ids = [c["secondary_id"] for c in cands]
                    reason = (
                        f"Object Track #{p_id} has multiple competing candidates "
                        f"({', '.join(f'Track #{cid}' for cid in competing_ids)}) with score difference "
                        f"{abs(top_score - second_score):.3f} <= threshold delta {self.config.ambiguity_threshold_delta}."
                    )
                    ambiguous_primary_keys[(assoc_type, p_id)] = (competing_ids, reason)

        # 5. Build/Update Association objects and evaluate State
        updated_associations: List[MaterialAssociation] = []

        for pair_key, cand in active_candidates.items():
            assoc_type, p_id, s_id = pair_key
            assoc = self.associations.get(pair_key)
            if not assoc:
                assoc = MaterialAssociation(
                    camera_id=self.camera_id,
                    association_type=assoc_type,
                    primary_track_id=p_id,
                    secondary_track_id=s_id,
                    primary_class=cand["primary_cls"],
                    secondary_class=cand["secondary_cls"],
                    initial_frame=cand["first_seen"]
                )
                self.associations[pair_key] = assoc

            assoc.last_seen_frame = self.frame_index
            assoc.consecutive_frames = cand["consecutive_frames"]
            assoc.missed_frames = 0
            assoc.association_score = cand["score"]
            assoc.primary_center = cand["primary_center"]
            assoc.secondary_center = cand["secondary_center"]

            p_track = cand["primary"]
            s_track = cand["secondary"]
            assoc.primary_bbox = p_track.get("bbox", {})
            assoc.secondary_bbox = s_track.get("bbox", {})

            # Identity details from Part 7 / Part 8
            p_ident = p_track.get("identity", {})
            p_val = p_track.get("validation", {})
            assoc.primary_identity = {
                "value": p_ident.get("value"),
                "source": p_ident.get("source"),
                "status": p_ident.get("status", "UNIDENTIFIED"),
                "validation_status": p_val.get("status", "NOT_APPLICABLE"),
                "master_type": p_val.get("master_type"),
                "master_id": p_val.get("master_id"),
                "display_name": p_val.get("display_name")
            }

            s_ident = s_track.get("identity", {})
            s_val = s_track.get("validation", {})
            assoc.secondary_identity = {
                "value": s_ident.get("value"),
                "source": s_ident.get("source"),
                "status": s_ident.get("status", "UNIDENTIFIED"),
                "validation_status": s_val.get("status", "NOT_APPLICABLE"),
                "master_type": s_val.get("master_type"),
                "master_id": s_val.get("master_id"),
                "display_name": s_val.get("display_name")
            }

            # Check ambiguity flags
            is_ambiguous = False
            competing_ids = []
            ambiguity_reason = None
            if (assoc_type, s_id) in ambiguous_secondary_keys:
                is_ambiguous = True
                competing_ids, ambiguity_reason = ambiguous_secondary_keys[(assoc_type, s_id)]
            elif (assoc_type, p_id) in ambiguous_primary_keys:
                is_ambiguous = True
                competing_ids, ambiguity_reason = ambiguous_primary_keys[(assoc_type, p_id)]

            # Construct explainable evidence
            explanation = ""
            if self.config.require_same_zone and not cand["same_zone"]:
                if cand["primary_zone"] and cand["secondary_zone"] and cand["primary_zone"] != cand["secondary_zone"]:
                    status = AssociationState.REJECTED
                    explanation = f"Rejected: Zone mismatch between {cand['primary_zone']} and {cand['secondary_zone']}."
                else:
                    status = AssociationState.CANDIDATE
                    explanation = "Candidate: Warehouse zone/ROI unassigned for one or both objects."
            elif not cand["in_proximity"]:
                status = AssociationState.REJECTED
                explanation = f"Rejected: Normalized distance {cand['norm_dist']:.3f} exceeds maximum allowed {self.config.max_normalized_distance:.3f}."
            elif is_ambiguous:
                status = AssociationState.CANDIDATE
                explanation = f"Candidate (Ambiguous): {ambiguity_reason}"
            elif assoc.consecutive_frames < self.config.min_consecutive_frames:
                status = AssociationState.CANDIDATE
                explanation = (
                    f"Candidate: Frame persistence ({assoc.consecutive_frames}/{self.config.min_consecutive_frames}) "
                    f"below confirmation threshold. Co-presence in a single frame does not confirm association."
                )
            elif assoc.association_score < self.config.min_association_score:
                status = AssociationState.CANDIDATE
                explanation = (
                    f"Candidate: Score {assoc.association_score:.3f} below confirmation threshold "
                    f"{self.config.min_association_score:.3f}."
                )
            else:
                status = AssociationState.CONFIRMED
                explanation = (
                    f"Confirmed: Sustained proximity ({assoc.consecutive_frames} frames >= {self.config.min_consecutive_frames}), "
                    f"matching zone '{cand['primary_zone']}', score {assoc.association_score:.3f} >= {self.config.min_association_score:.3f}."
                )

            evidence = MaterialAssociationEvidence(
                association_type=assoc_type,
                same_camera=True,
                same_zone=cand["same_zone"],
                primary_zone=cand["primary_zone"],
                secondary_zone=cand["secondary_zone"],
                temporal_overlap=True,
                spatial_proximity=cand["in_proximity"],
                consecutive_frames=assoc.consecutive_frames,
                missed_frames=0,
                normalized_distance=cand["norm_dist"],
                max_allowed_distance=self.config.max_normalized_distance,
                spatial_proximity_score=cand["spatial_score"],
                temporal_persistence_score=cand["temporal_score"],
                zone_score=cand["zone_score"],
                movement_consistency_score=cand["movement_score"],
                validated_physical_identity=cand["validated_physical_identity"],
                is_ambiguous=is_ambiguous,
                competing_track_ids=competing_ids,
                ambiguity_reason=ambiguity_reason,
                explanation=explanation
            )
            assoc.evidence = evidence
            assoc.status = status

            # Derive Real-World Identity Association (Part 8 master-data binding)
            # Rule: Both identities must be VALIDATED in Part 8.
            # If identity status is UNIDENTIFIED, AMBIGUOUS, or CONFLICT, real-world association MUST be None.
            p_ident_status = assoc.primary_identity.get("status")
            s_ident_status = assoc.secondary_identity.get("status")
            p_val_status = assoc.primary_identity.get("validation_status")
            s_val_status = assoc.secondary_identity.get("validation_status")

            has_valid_identities = (
                p_val_status == "VALIDATED" and
                s_val_status == "VALIDATED" and
                p_ident_status not in ("UNIDENTIFIED", "AMBIGUOUS", "CONFLICT") and
                s_ident_status not in ("UNIDENTIFIED", "AMBIGUOUS", "CONFLICT") and
                assoc.primary_identity.get("value") is not None and
                assoc.secondary_identity.get("value") is not None
            )

            if has_valid_identities:
                if assoc_type == AssociationType.TRUCK_MATERIAL:
                    assoc.real_world_association = {
                        "association_type": assoc_type,
                        "truck_id": assoc.primary_identity["value"],
                        "truck_display": assoc.primary_identity.get("display_name"),
                        "material_sku": assoc.secondary_identity["value"],
                        "material_name": assoc.secondary_identity.get("display_name"),
                        "material_class": assoc.secondary_class,
                        "status": "VALIDATED"
                    }
                elif assoc_type == AssociationType.TRUCK_CONTAINER:
                    assoc.real_world_association = {
                        "association_type": assoc_type,
                        "truck_id": assoc.primary_identity["value"],
                        "truck_display": assoc.primary_identity.get("display_name"),
                        "container_id": assoc.secondary_identity["value"],
                        "container_display": assoc.secondary_identity.get("display_name"),
                        "status": "VALIDATED"
                    }
                elif assoc_type == AssociationType.WORKER_MATERIAL:
                    assoc.real_world_association = {
                        "association_type": assoc_type,
                        "worker_id": assoc.primary_identity["value"],
                        "worker_display": assoc.primary_identity.get("display_name"),
                        "material_sku": assoc.secondary_identity["value"],
                        "material_name": assoc.secondary_identity.get("display_name"),
                        "material_class": assoc.secondary_class,
                        "status": "VALIDATED"
                    }
                elif assoc_type == AssociationType.MATERIAL_BIN:
                    assoc.real_world_association = {
                        "association_type": assoc_type,
                        "material_sku": assoc.primary_identity["value"],
                        "material_name": assoc.primary_identity.get("display_name"),
                        "material_class": assoc.primary_class,
                        "bin_id": assoc.secondary_identity["value"],
                        "bin_display": assoc.secondary_identity.get("display_name"),
                        "status": "VALIDATED"
                    }
                elif assoc_type == AssociationType.MATERIAL_CONTAINER:
                    # Explicit container vs contained material distinction
                    assoc.real_world_association = {
                        "association_type": assoc_type,
                        "container_id": assoc.primary_identity["value"],
                        "container_display": assoc.primary_identity.get("display_name"),
                        "material_sku": assoc.secondary_identity["value"],
                        "material_name": assoc.secondary_identity.get("display_name"),
                        "material_class": assoc.secondary_class,
                        "status": "VALIDATED"
                    }
            else:
                assoc.real_world_association = None

            updated_associations.append(assoc)

        # 6. Exclusivity & Incompatibility Arbitration
        # Prevent one material from being simultaneously confirmed against incompatible entities:
        # e.g., A material cannot be confirmed against 2 different trucks, 2 different bins, or Truck AND Bin.
        self._arbitrate_incompatible_confirmations(updated_associations)

        # 7. Check for Missing / Departed Tracks (Timeout & Expiry Handling)
        for pair_key, assoc in list(self.associations.items()):
            if pair_key not in current_pair_keys:
                if assoc.status != AssociationState.EXPIRED:
                    assoc.missed_frames += 1
                    if assoc.evidence:
                        assoc.evidence.temporal_overlap = False
                        assoc.evidence.missed_frames = assoc.missed_frames
                    if assoc.missed_frames >= self.config.association_timeout_frames:
                        assoc.status = AssociationState.EXPIRED
                        if assoc.evidence:
                            assoc.evidence.explanation = (
                                f"Expired: Objects missing from camera view for {assoc.missed_frames} "
                                f"consecutive frames (timeout={self.config.association_timeout_frames})."
                            )

        # 8. Update track previous centers for velocity calculation in next frame
        for t in tracks:
            t_id = int(t.get("track_id", 0))
            self.track_prev_centers[t_id] = t["_norm_center"]

        return list(self.associations.values())

    def _arbitrate_incompatible_confirmations(self, associations: List[MaterialAssociation]):
        """
        Enforce mutual exclusivity on confirmed associations.
        A material track cannot be simultaneously CONFIRMED against:
          - Multiple trucks
          - Multiple bins
          - Multiple workers
          - Incompatible locations (Truck AND Bin simultaneously)
        If multiple meet confirmation criteria, the highest scoring unambiguous one wins;
        the other is downgraded to CANDIDATE.
        """
        # Group confirmed associations by secondary material track id
        material_confirmed: Dict[int, List[MaterialAssociation]] = {}
        for a in associations:
            if a.status == AssociationState.CONFIRMED:
                # Target material is secondary in TRUCK_MATERIAL, WORKER_MATERIAL, MATERIAL_CONTAINER
                # and primary in MATERIAL_BIN
                mat_id = a.primary_track_id if a.association_type == AssociationType.MATERIAL_BIN else a.secondary_track_id
                material_confirmed.setdefault(mat_id, []).append(a)

        for mat_id, c_list in material_confirmed.items():
            if len(c_list) > 1:
                # Check for incompatible pairs (e.g. 2 trucks, or Truck + Bin)
                truck_assocs = [a for a in c_list if a.association_type in (AssociationType.TRUCK_MATERIAL, AssociationType.TRUCK_CONTAINER)]
                bin_assocs = [a for a in c_list if a.association_type == AssociationType.MATERIAL_BIN]
                worker_assocs = [a for a in c_list if a.association_type == AssociationType.WORKER_MATERIAL]

                # If multiple trucks confirmed for same material, keep highest score
                if len(truck_assocs) > 1:
                    truck_assocs.sort(key=lambda x: x.association_score, reverse=True)
                    for demoted in truck_assocs[1:]:
                        demoted.status = AssociationState.CANDIDATE
                        if demoted.evidence:
                            demoted.evidence.explanation = (
                                f"Candidate: Competing with higher-scoring truck (Track #{truck_assocs[0].primary_track_id}). "
                                "Material cannot be simultaneously confirmed to multiple trucks."
                            )

                # If multiple bins confirmed for same material, keep highest score
                if len(bin_assocs) > 1:
                    bin_assocs.sort(key=lambda x: x.association_score, reverse=True)
                    for demoted in bin_assocs[1:]:
                        demoted.status = AssociationState.CANDIDATE
                        if demoted.evidence:
                            demoted.evidence.explanation = (
                                f"Candidate: Competing with higher-scoring bin (Track #{bin_assocs[0].secondary_track_id}). "
                                "Material cannot be simultaneously confirmed to multiple bins."
                            )

                # If multiple workers confirmed for same material, keep highest score
                if len(worker_assocs) > 1:
                    worker_assocs.sort(key=lambda x: x.association_score, reverse=True)
                    for demoted in worker_assocs[1:]:
                        demoted.status = AssociationState.CANDIDATE
                        if demoted.evidence:
                            demoted.evidence.explanation = (
                                f"Candidate: Competing with higher-scoring worker (Track #{worker_assocs[0].primary_track_id}). "
                                "Material cannot be simultaneously confirmed to multiple workers."
                            )

                # If both Truck and Bin are confirmed (incompatible physical locations: dock truck vs warehouse bin)
                active_trucks = [a for a in truck_assocs if a.status == AssociationState.CONFIRMED]
                active_bins = [a for a in bin_assocs if a.status == AssociationState.CONFIRMED]
                if active_trucks and active_bins:
                    top_truck = active_trucks[0]
                    top_bin = active_bins[0]
                    if top_truck.association_score >= top_bin.association_score:
                        top_bin.status = AssociationState.CANDIDATE
                        if top_bin.evidence:
                            top_bin.evidence.explanation = "Candidate: Incompatible with active confirmed truck association."
                    else:
                        top_truck.status = AssociationState.CANDIDATE
                        if top_truck.evidence:
                            top_truck.evidence.explanation = "Candidate: Incompatible with active confirmed bin association."


# ============================================================================
# 4. MULTI-OBJECT MATERIAL ASSOCIATION SERVICE
# ============================================================================

class MultiObjectMaterialAssociationService:
    """
    Unified, material-agnostic service coordinating association sessions across all camera nodes.
    Integrates upstream detection, tracking, identity recognition, and master-data validation.
    """
    def __init__(self, config: Optional[MaterialAssociationConfig] = None):
        self.config = config or MaterialAssociationConfig()
        self.sessions: Dict[str, CameraMaterialAssociationSession] = {}
        self.validation_service: MultiObjectValidationService = get_validation_service()
        logger.info("MultiObjectMaterialAssociationService initialized.")

    def get_session(self, camera_id: str) -> CameraMaterialAssociationSession:
        """Get or lazily create a camera-specific association session."""
        if camera_id not in self.sessions:
            self.sessions[camera_id] = CameraMaterialAssociationSession(
                camera_id=camera_id,
                config=self.config
            )
        return self.sessions[camera_id]

    def reset_session(self, camera_id: str):
        """Reset association session for a specific camera."""
        if camera_id in self.sessions:
            self.sessions[camera_id].reset()

    def reset_all(self):
        """Reset association sessions for all cameras."""
        for session in self.sessions.values():
            session.reset()
        logger.info("All camera material association sessions reset.")

    def process_tracks(
        self,
        tracks: List[Dict[str, Any]],
        camera_id: str = "CAM-001",
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Process pre-validated tracks through the Material Association Engine.
        Returns list of serialized associations and execution time in milliseconds.
        """
        t0 = time.perf_counter()
        session = self.get_session(camera_id)

        # Resolve warehouse zones for this camera if not passed
        if camera_zones is None:
            try:
                camera_zones = db.get_camera_rois(camera_id)
            except Exception as e:
                logger.warning(f"Failed to fetch camera ROIs for '{camera_id}': {e}")
                camera_zones = []

        raw_assocs = session.update(tracks=tracks, camera_zones=camera_zones)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        return [a.to_dict() for a in raw_assocs], elapsed_ms

    def process_frame(
        self,
        frame_input: Union[str, np.ndarray],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        End-to-End single-frame perception and material association pipeline
        (Detection -> ByteTrack -> Identity Recognition -> Master Validation -> Material Association).
        """
        t0 = time.perf_counter()

        # Step 1-4: Execute upstream validation pipeline
        val_result = self.validation_service.process_frame(
            frame_input=frame_input,
            camera_id=camera_id,
            conf_threshold=conf_threshold,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )

        tracks = val_result.get("tracks", [])

        # Fetch camera zones
        camera_zones = db.get_camera_rois(camera_id)

        # Step 5: Material Association Engine
        session = self.get_session(camera_id)
        raw_assocs = session.update(tracks=tracks, camera_zones=camera_zones)

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        associations_dict = [a.to_dict() for a in raw_assocs]

        confirmed_count = sum(1 for a in raw_assocs if a.status == AssociationState.CONFIRMED)
        candidate_count = sum(1 for a in raw_assocs if a.status == AssociationState.CANDIDATE)
        rejected_count = sum(1 for a in raw_assocs if a.status == AssociationState.REJECTED)
        expired_count = sum(1 for a in raw_assocs if a.status == AssociationState.EXPIRED)
        ambiguous_count = sum(1 for a in raw_assocs if a.evidence and a.evidence.is_ambiguous)

        return {
            "success": True,
            "camera_id": camera_id,
            "frame_index": session.frame_index,
            "tracks": tracks,
            "associations": associations_dict,
            "counts": {
                "total_associations": len(raw_assocs),
                "confirmed": confirmed_count,
                "candidate": candidate_count,
                "rejected": rejected_count,
                "expired": expired_count,
                "ambiguous": ambiguous_count
            },
            "performance": {
                "association_ms": round((time.perf_counter() - t0) * 1000, 2),
                "total_pipeline_ms": total_ms
            }
        }

    def get_associations_for_material(self, material_id: str) -> Dict[str, Any]:
        """
        Query associations for a specific physical material across all active camera sessions.
        Strictly uses validated physical identity (barcode/QR/OCR/WMS SKU).
        Zero visual cross-camera Re-ID or appearance embeddings.
        """
        results: List[Dict[str, Any]] = []

        for cam_id, session in self.sessions.items():
            for assoc in session.associations.values():
                # Check if real-world association matches material_id
                rwa = assoc.real_world_association
                if rwa:
                    mat_sku = rwa.get("material_sku")
                    if mat_sku and str(mat_sku).strip().upper() == str(material_id).strip().upper():
                        results.append(assoc.to_dict())
                        continue

                # Also check secondary or primary identity value directly
                s_val = assoc.secondary_identity.get("value")
                p_val = assoc.primary_identity.get("value")
                if (s_val and str(s_val).strip().upper() == str(material_id).strip().upper()) or \
                   (p_val and str(p_val).strip().upper() == str(material_id).strip().upper()):
                    results.append(assoc.to_dict())

        return {
            "material_id": material_id,
            "total_associations_found": len(results),
            "cross_camera_continuity_method": "PHYSICAL_IDENTITY_ONLY (No visual Re-ID)",
            "associations": results
        }

    def get_all_associations(
        self,
        camera_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Part 12: Aggregates active, candidate, and recent material associations across sessions.
        Strictly in-memory and read-only.
        """
        results: List[Dict[str, Any]] = []
        for cam_id, session in list(self.sessions.items()):
            if camera_id and cam_id != camera_id:
                continue
            for assoc in session.associations.values():
                results.append(assoc.to_dict())
        # Sort confirmed first, then candidate
        state_order = {
            AssociationState.CONFIRMED: 0,
            AssociationState.CANDIDATE: 1,
            AssociationState.EXPIRED: 2,
            AssociationState.REJECTED: 3
        }
        results.sort(key=lambda a: state_order.get(a.get("status"), 99))
        return results[:limit]

    def get_status(self) -> Dict[str, Any]:
        """Return operational status and diagnostic configuration."""
        active_sessions = {}
        for cam_id, sess in self.sessions.items():
            active_sessions[cam_id] = {
                "frame_index": sess.frame_index,
                "total_associations": len(sess.associations),
                "confirmed": sum(1 for a in sess.associations.values() if a.status == AssociationState.CONFIRMED),
                "candidates": sum(1 for a in sess.associations.values() if a.status == AssociationState.CANDIDATE),
                "rejected": sum(1 for a in sess.associations.values() if a.status == AssociationState.REJECTED),
                "expired": sum(1 for a in sess.associations.values() if a.status == AssociationState.EXPIRED),
                "last_update": sess.last_update_time
            }

        return {
            "service": "MaterialAssociationEngine",
            "status": "OPERATIONAL",
            "architecture": "Detection -> Track -> Identity -> WMS Validation -> Association Evidence -> Association State",
            "principles": {
                "co_visibility_is_not_association": True,
                "authoritative_wms_masters": True,
                "zero_db_schema_modifications": True,
                "zero_inventory_modifications": True,
                "no_visual_reid": True,
                "no_worker_productivity_inference": True
            },
            "config": self.config.to_dict(),
            "supported_associations": [
                AssociationType.TRUCK_MATERIAL,
                AssociationType.TRUCK_CONTAINER,
                AssociationType.WORKER_MATERIAL,
                AssociationType.MATERIAL_BIN,
                AssociationType.MATERIAL_CONTAINER
            ],
            "sessions": active_sessions
        }

    def annotate_associations(
        self,
        frame: np.ndarray,
        associations: List[MaterialAssociation],
        tracks: Optional[List[Dict[str, Any]]] = None
    ) -> np.ndarray:
        """
        Render clean, explainable visual overlays:
        - Bounding boxes for Trucks, Workers, Bins, Containers, and Materials with distinct colors
        - Dynamic connecting status lines (CONFIRMED=Solid Green, CANDIDATE=Amber, AMBIGUOUS=Orange, REJECTED=Red)
        - Pair score pills with association state badges
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        COLOR_TRUCK = (255, 140, 0)       # Cyan/Blue
        COLOR_WORKER = (220, 50, 180)     # Magenta/Purple
        COLOR_BIN = (50, 205, 50)         # Bright Green
        COLOR_CONTAINER = (0, 165, 255)   # Warm Orange
        COLOR_GLASS = (235, 206, 135)     # Sky Blue
        COLOR_ROD = (180, 105, 255)       # Pink-Purple
        COLOR_FASTENER = (0, 215, 255)    # Gold
        COLOR_MATERIAL = (0, 200, 255)    # Bright Yellow-Orange

        def get_class_color(cls: str) -> Tuple[int, int, int]:
            cls_upper = str(cls).upper()
            if cls_upper in TRUCK_CLASSES: return COLOR_TRUCK
            if cls_upper in WORKER_CLASSES: return COLOR_WORKER
            if cls_upper in BIN_CLASSES: return COLOR_BIN
            if cls_upper in ("GLASS",): return COLOR_GLASS
            if cls_upper in ("ROD",): return COLOR_ROD
            if cls_upper in ("FASTENER",): return COLOR_FASTENER
            if cls_upper in AUTOMOTIVE_MATERIAL_CLASSES: return COLOR_MATERIAL
            return COLOR_CONTAINER

        # 1. Draw track bounding boxes
        drawn_tracks: Set[int] = set()
        for a in associations:
            for is_primary in (True, False):
                t_id = a.primary_track_id if is_primary else a.secondary_track_id
                t_cls = a.primary_class if is_primary else a.secondary_class
                t_bbox = a.primary_bbox if is_primary else a.secondary_bbox
                t_ident = a.primary_identity if is_primary else a.secondary_identity

                if t_id not in drawn_tracks and t_bbox:
                    drawn_tracks.add(t_id)
                    x1 = int(t_bbox.get("x1", 0))
                    y1 = int(t_bbox.get("y1", 0))
                    x2 = int(t_bbox.get("x2", 0))
                    y2 = int(t_bbox.get("y2", 0))
                    if x2 > x1 and y2 > y1:
                        c_color = get_class_color(t_cls)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), c_color, 2)
                        lbl = f"{t_cls} #{t_id}"
                        if t_ident.get("value"):
                            lbl += f" [{t_ident['value']}]"
                        cv2.rectangle(annotated, (x1, max(0, y1 - 18)), (x1 + len(lbl) * 8 + 8, y1), c_color, -1)
                        cv2.putText(annotated, lbl, (x1 + 4, max(12, y1 - 4)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)

        # 2. Draw connecting lines and status pills between associated pairs
        for a in associations:
            if a.status == AssociationState.EXPIRED:
                continue

            # Compute pixel centers
            p_cx = int(a.primary_center[0] * w)
            p_cy = int(a.primary_center[1] * h)
            s_cx = int(a.secondary_center[0] * w)
            s_cy = int(a.secondary_center[1] * h)

            if a.status == AssociationState.CONFIRMED:
                line_color = (40, 167, 69)  # Green
                line_thick = 2
            elif a.evidence and a.evidence.is_ambiguous:
                line_color = (0, 140, 255)  # Orange (Ambiguous)
                line_thick = 1
            elif a.status == AssociationState.CANDIDATE:
                line_color = (0, 215, 255)  # Amber (Candidate)
                line_thick = 1
            else:
                line_color = (0, 0, 220)    # Red (Rejected)
                line_thick = 1

            cv2.line(annotated, (p_cx, p_cy), (s_cx, s_cy), line_color, line_thick, cv2.LINE_AA)

            # Draw center pill on line
            mid_x = (p_cx + s_cx) // 2
            mid_y = (p_cy + s_cy) // 2
            pill_text = f"{a.status} {a.association_score:.2f}"
            cv2.rectangle(annotated, (mid_x - 40, mid_y - 10), (mid_x + 40, mid_y + 10), (20, 20, 20), -1)
            cv2.rectangle(annotated, (mid_x - 40, mid_y - 10), (mid_x + 40, mid_y + 10), line_color, 1)
            cv2.putText(annotated, pill_text, (mid_x - 36, mid_y + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)

        return annotated


# Global Singleton
_material_association_service_instance: Optional[MultiObjectMaterialAssociationService] = None

def get_material_association_service() -> MultiObjectMaterialAssociationService:
    """Singleton provider for MultiObjectMaterialAssociationService."""
    global _material_association_service_instance
    if _material_association_service_instance is None:
        _material_association_service_instance = MultiObjectMaterialAssociationService()
    return _material_association_service_instance
