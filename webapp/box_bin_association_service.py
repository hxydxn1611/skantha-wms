"""
AI Vision & Tracking Master - Box <-> Bin Association Foundation
Part 11: Controlled, Evidence-Based Association between Tracked Boxes and Storage Bins.

Core Principle: CO-VISIBILITY IS NOT ASSOCIATION.
Co-presence in the same image frame is strictly insufficient for association.
All associations must be established on explicit, explainable evidence:
  1. Same camera
  2. Same active session
  3. Same relevant warehouse zone / ROI
  4. Temporal overlap
  5. Spatial proximity between tracked objects (Euclidean distance on normalized coordinates)
  6. Sustained proximity across multiple consecutive frames
  7. Valid track continuity
  8. Bin identity / master-data validation where available

Important Bin Semantics:
  - Box = movable material / secondary container (BOX, PACKAGE, CARTON)
  - Bin = destination / storage location (BIN, LOCATION, TOTE, BAY, SLOT)
  - Association: Box Track #21 -> Bin Track #15
  - When validated: Box VLV-900 -> Bin BIN-A
  - A bin is NOT a generic box. Never invent a bin identity.

Track vs Real-World Identity:
  - Track-level association: Box Track #B <-> Bin Track #Bin
  - Real-world association: Box VLV-900 <-> Bin BIN-A
  Real-world identity association is derived ONLY when BOTH underlying tracks
  have been successfully IDENTIFIED and VALIDATED by Part 8 master-data binding.
  If the bin or box is not validated, real_world_association is null.

Zero Database Writes:
  - All association state is managed strictly in-memory per camera session.
  - Zero database schema modifications, zero SQL INSERT/UPDATE statements.
"""

import os
import math
import time
import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

import cv2
import numpy as np

# Import Part 8 MultiObjectValidationService
from validation_service import (
    get_validation_service,
    MultiObjectValidationService
)
from detection_service import is_point_in_polygon

logger = logging.getLogger(__name__)


# ============================================================================
# 1. CONFIGURATION & CONSTANTS
# ============================================================================
@dataclass
class BoxBinAssociationConfig:
    """
    Explicit, documented configuration parameters for Box <-> Bin Association.
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

    # Ambiguity delta threshold: if two competing bins have scores within this delta, flag as AMBIGUOUS
    ambiguity_threshold_delta: float = 0.15

    # Evidence score component weights (must sum to 1.0)
    weight_spatial: float = 0.35
    weight_zone: float = 0.35
    weight_temporal: float = 0.30

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
                "temporal": self.weight_temporal
            }
        }


class AssociationState:
    """Standardized lifecycle states for Box <-> Bin associations."""
    CANDIDATE = "CANDIDATE"      # Evidence accumulating or ambiguous, confirmation threshold not yet reached
    CONFIRMED = "CONFIRMED"      # Satisfied consecutive frames, score, distance, and same-zone requirements
    REJECTED = "REJECTED"        # Explicitly contradicted by evidence (distance > max or different zones)
    EXPIRED = "EXPIRED"          # One or both tracks departed/disappeared for timeout frames


# ============================================================================
# 2. EVIDENCE & ASSOCIATION DATA MODELS
# ============================================================================
@dataclass
class BoxBinAssociationEvidence:
    """
    Transparent, explainable evidence model backing every evaluated Box <-> Bin candidate pair.
    """
    same_camera: bool = True
    same_zone: bool = False
    box_zone: Optional[str] = None
    bin_zone: Optional[str] = None
    temporal_overlap: bool = True
    spatial_proximity: bool = False
    consecutive_frames: int = 1
    missed_frames: int = 0
    normalized_distance: float = 1.0
    max_allowed_distance: float = 0.40
    spatial_proximity_score: float = 0.0
    zone_score: float = 0.0
    temporal_persistence_score: float = 0.0
    is_ambiguous: bool = False
    competing_bin_ids: List[int] = field(default_factory=list)
    ambiguity_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "same_camera": self.same_camera,
            "same_zone": self.same_zone,
            "box_zone": self.box_zone,
            "bin_zone": self.bin_zone,
            "temporal_overlap": self.temporal_overlap,
            "spatial_proximity": self.spatial_proximity,
            "consecutive_frames": self.consecutive_frames,
            "missed_frames": self.missed_frames,
            "normalized_distance": round(self.normalized_distance, 4),
            "max_allowed_distance": self.max_allowed_distance,
            "spatial_proximity_score": round(self.spatial_proximity_score, 4),
            "zone_score": round(self.zone_score, 4),
            "temporal_persistence_score": round(self.temporal_persistence_score, 4),
            "is_ambiguous": self.is_ambiguous,
            "competing_bin_ids": self.competing_bin_ids,
            "ambiguity_reason": self.ambiguity_reason
        }


@dataclass
class BoxBinAssociation:
    """
    Represents an ongoing spatial-temporal association between a tracked Box and Bin.
    """
    camera_id: str
    box_track_id: int
    bin_track_id: int
    status: str = AssociationState.CANDIDATE
    association_score: float = 0.0
    box_identity: Dict[str, Any] = field(default_factory=dict)
    bin_identity: Dict[str, Any] = field(default_factory=dict)
    real_world_association: Optional[Dict[str, Any]] = None
    evidence: BoxBinAssociationEvidence = field(default_factory=BoxBinAssociationEvidence)
    first_seen_frame: int = 1
    last_seen_frame: int = 1
    consecutive_frames: int = 1
    missed_frames: int = 0
    box_center: Tuple[float, float] = (0.0, 0.0)
    bin_center: Tuple[float, float] = (0.0, 0.0)
    box_bbox: Dict[str, int] = field(default_factory=dict)
    bin_bbox: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "box_track_id": self.box_track_id,
            "bin_track_id": self.bin_track_id,
            "status": self.status,
            "association_score": round(self.association_score, 4),
            "box_identity": self.box_identity,
            "bin_identity": self.bin_identity,
            "real_world_association": self.real_world_association,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "metrics": {
                "first_seen_frame": self.first_seen_frame,
                "last_seen_frame": self.last_seen_frame,
                "consecutive_frames": self.consecutive_frames,
                "missed_frames": self.missed_frames,
                "box_center": [round(c, 4) for c in self.box_center],
                "bin_center": [round(c, 4) for c in self.bin_center]
            }
        }


# ============================================================================
# 3. CAMERA SESSION ASSOCIATION ENGINE
# ============================================================================
class CameraBoxBinAssociationSession:
    """
    Camera-isolated in-memory association tracking session for Box <-> Bin pairs.
    Manages temporal persistence, distance calculation, ambiguity detection, and lifecycle states.
    """

    def __init__(self, camera_id: str, config: Optional[BoxBinAssociationConfig] = None):
        self.camera_id = camera_id
        self.config = config or BoxBinAssociationConfig()
        # Key: (box_track_id, bin_track_id) -> BoxBinAssociation
        self.associations: Dict[Tuple[int, int], BoxBinAssociation] = {}
        self.frame_index = 0
        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def reset(self):
        """Reset all in-memory associations and frame counter for this camera."""
        self.associations.clear()
        self.frame_index = 0
        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _calculate_euclidean_distance(self, pt1: Tuple[float, float], pt2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance between two normalized coordinate points [0.0 - 1.0]."""
        return math.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)

    def _get_normalized_center(self, track: Dict[str, Any]) -> Tuple[float, float]:
        """Extract or compute normalized center (cx, cy) from track bounding box or explicit fields."""
        if "center_normalized" in track and track["center_normalized"]:
            cn = track["center_normalized"]
            return float(cn[0]), float(cn[1])

        bbox_norm = track.get("bbox_normalized", {})
        if bbox_norm and "x1" in bbox_norm and "x2" in bbox_norm:
            cx = (float(bbox_norm.get("x1", 0.0)) + float(bbox_norm.get("x2", 1.0))) / 2.0
            cy = (float(bbox_norm.get("y1", 0.0)) + float(bbox_norm.get("y2", 1.0))) / 2.0
            return cx, cy

        bbox = track.get("bbox", {})
        if bbox and "x1" in bbox and "x2" in bbox:
            w = max(1, track.get("image_width", 640))
            h = max(1, track.get("image_height", 480))
            cx = (float(bbox.get("x1", 0)) + float(bbox.get("x2", 0))) / (2.0 * w)
            cy = (float(bbox.get("y1", 0)) + float(bbox.get("y2", 0))) / (2.0 * h)
            return cx, cy

        return 0.5, 0.5

    def _resolve_zone_for_track(self, track: Dict[str, Any], camera_zones: List[Dict[str, Any]]) -> Optional[str]:
        """
        Determine spatial zone/ROI for a track.
        Uses pre-assigned roi_zone_code or tests normalized center against polygon vertices.
        """
        if track.get("roi_zone_code"):
            return str(track["roi_zone_code"]).strip()
        if track.get("zone"):
            return str(track["zone"]).strip()

        cx, cy = self._get_normalized_center(track)
        center_dict = {"x": cx, "y": cy}

        for zone in camera_zones:
            poly = zone.get("polygon")
            if poly and len(poly) >= 3:
                if is_point_in_polygon(center_dict, poly):
                    return zone.get("zone_code")

        return None

    def update(
        self,
        tracks: List[Dict[str, Any]],
        camera_zones_or_frame: Any = None,
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> List[BoxBinAssociation]:
        """
        Execute core Part 11 Box <-> Bin Association logic for the current frame.
        Evaluates pairwise evidence for all (Box, Bin) combinations, tracks temporal persistence,
        flags ambiguity, and produces explainable states.
        """
        if isinstance(camera_zones_or_frame, int):
            frame_index = camera_zones_or_frame
            camera_zones = camera_zones or []
        elif isinstance(camera_zones_or_frame, list):
            camera_zones = camera_zones_or_frame
        else:
            camera_zones = camera_zones or []

        if frame_index is not None:
            self.frame_index = frame_index
        else:
            self.frame_index += 1

        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Separate tracks into Boxes and Bins
        boxes: List[Dict[str, Any]] = []
        bins: List[Dict[str, Any]] = []

        for t in tracks:
            cls_code = str(t.get("class_code", "")).upper()
            if cls_code in ("BOX", "CARTON", "PACKAGE", "CONTAINER", "CARDBOARD BOX"):
                boxes.append(t)
            elif cls_code in ("BIN", "STORAGE_BIN", "TOTE", "BAY", "SLOT", "LOCATION", "STORAGE BIN / TOTE"):
                bins.append(t)

        # 2. Enrich tracks with resolved warehouse zones and normalized centers
        for b in boxes:
            b["_resolved_zone"] = self._resolve_zone_for_track(b, camera_zones)
            b["_norm_center"] = self._get_normalized_center(b)

        for bn in bins:
            bn["_resolved_zone"] = self._resolve_zone_for_track(bn, camera_zones)
            bn["_norm_center"] = self._get_normalized_center(bn)

        # 3. Calculate independent pairwise evidence for ALL active (Box, Bin) combinations
        current_pair_keys = set()
        active_candidates: Dict[Tuple[int, int], Dict[str, Any]] = {}

        for b in boxes:
            b_id = int(b.get("track_id", 0))
            b_center = b["_norm_center"]
            b_zone = b["_resolved_zone"]

            for bn in bins:
                bn_id = int(bn.get("track_id", 0))
                bn_center = bn["_norm_center"]
                bn_zone = bn["_resolved_zone"]

                pair_key = (b_id, bn_id)
                current_pair_keys.add(pair_key)

                # Spatial distance
                norm_dist = self._calculate_euclidean_distance(b_center, bn_center)
                in_proximity = norm_dist <= self.config.max_normalized_distance

                # Proximity score S_spatial = max(0, 1 - d / max_d)
                if in_proximity and self.config.max_normalized_distance > 0:
                    spatial_score = max(0.0, 1.0 - (norm_dist / self.config.max_normalized_distance))
                else:
                    spatial_score = 0.0

                # Same Zone logic:
                # Both objects must have a non-empty resolved zone and they must match
                same_zone = (b_zone is not None and bn_zone is not None and str(b_zone).upper() == str(bn_zone).upper())
                zone_score = 1.0 if same_zone else 0.0

                # Temporal continuity
                existing = self.associations.get(pair_key)
                if existing and existing.status != AssociationState.EXPIRED:
                    consecutive_frames = existing.consecutive_frames + 1
                    first_seen = existing.first_seen_frame
                else:
                    consecutive_frames = 1
                    first_seen = self.frame_index

                temporal_score = min(1.0, consecutive_frames / max(1, self.config.min_consecutive_frames))

                # Transparent explainable score calculation:
                # association_score = w_spatial * spatial_score + w_zone * zone_score + w_temporal * temporal_score
                raw_score = (
                    self.config.weight_spatial * spatial_score +
                    self.config.weight_zone * zone_score +
                    self.config.weight_temporal * temporal_score
                )
                score = round(min(1.0, max(0.0, raw_score)), 4)

                active_candidates[pair_key] = {
                    "box": b,
                    "bin": bn,
                    "box_id": b_id,
                    "bin_id": bn_id,
                    "box_center": b_center,
                    "bin_center": bn_center,
                    "box_zone": b_zone,
                    "bin_zone": bn_zone,
                    "same_zone": same_zone,
                    "in_proximity": in_proximity,
                    "norm_dist": norm_dist,
                    "spatial_score": spatial_score,
                    "zone_score": zone_score,
                    "temporal_score": temporal_score,
                    "consecutive_frames": consecutive_frames,
                    "first_seen": first_seen,
                    "score": score
                }

        # 4. Ambiguity Detection (Box Competing for Multiple Bins)
        # Check every box: if multiple bins have scores within ambiguity_threshold_delta
        box_bin_candidates: Dict[int, List[Dict[str, Any]]] = {}
        for pair_key, cand in active_candidates.items():
            b_id = cand["box_id"]
            if cand["in_proximity"]:
                box_bin_candidates.setdefault(b_id, []).append(cand)

        ambiguous_boxes: Dict[int, Tuple[List[int], str]] = {}
        for b_id, cands in box_bin_candidates.items():
            if len(cands) > 1:
                # Sort by score descending
                cands.sort(key=lambda x: x["score"], reverse=True)
                top_score = cands[0]["score"]
                second_score = cands[1]["score"]
                # If difference between top two candidates is less than or equal to ambiguity threshold delta
                if abs(top_score - second_score) <= self.config.ambiguity_threshold_delta:
                    competing_ids = [c["bin_id"] for c in cands]
                    reason = (
                        f"Box Track #{b_id} is simultaneously close to multiple bins "
                        f"({', '.join(f'Bin #{bid}' for bid in competing_ids)}) with score diff "
                        f"{abs(top_score - second_score):.3f} <= threshold delta {self.config.ambiguity_threshold_delta}."
                    )
                    ambiguous_boxes[b_id] = (competing_ids, reason)

        # 5. Update or Create Association Objects
        updated_associations: List[BoxBinAssociation] = []

        for pair_key, cand in active_candidates.items():
            b_id, bn_id = pair_key
            assoc = self.associations.get(pair_key)
            if not assoc:
                assoc = BoxBinAssociation(
                    camera_id=self.camera_id,
                    box_track_id=b_id,
                    bin_track_id=bn_id,
                    first_seen_frame=cand["first_seen"]
                )
                self.associations[pair_key] = assoc

            assoc.last_seen_frame = self.frame_index
            assoc.consecutive_frames = cand["consecutive_frames"]
            assoc.missed_frames = 0
            assoc.association_score = cand["score"]
            assoc.box_center = cand["box_center"]
            assoc.bin_center = cand["bin_center"]

            # Bounding boxes for visual rendering
            b_track = cand["box"]
            bn_track = cand["bin"]
            assoc.box_bbox = b_track.get("bbox", {})
            assoc.bin_bbox = bn_track.get("bbox", {})

            # Identity details from Part 7 / Part 8
            b_ident = b_track.get("identity", {})
            b_val = b_track.get("validation", {})
            assoc.box_identity = {
                "value": b_ident.get("value"),
                "status": b_ident.get("status", "UNIDENTIFIED"),
                "validation_status": b_val.get("status", "NOT_APPLICABLE"),
                "source": b_ident.get("source"),
                "master_type": b_val.get("master_type"),
                "master_id": b_val.get("master_id"),
                "display_name": b_val.get("display_name")
            }

            bn_ident = bn_track.get("identity", {})
            bn_val = bn_track.get("validation", {})
            assoc.bin_identity = {
                "value": bn_ident.get("value"),
                "status": bn_ident.get("status", "UNIDENTIFIED"),
                "validation_status": bn_val.get("status", "NOT_APPLICABLE"),
                "source": bn_ident.get("source"),
                "master_type": bn_val.get("master_type"),
                "master_id": bn_val.get("master_id"),
                "display_name": bn_val.get("display_name")
            }

            # Check ambiguity for this box
            is_ambiguous = False
            competing_ids = []
            ambiguity_reason = None
            if b_id in ambiguous_boxes:
                is_ambiguous = True
                competing_ids, ambiguity_reason = ambiguous_boxes[b_id]

            # Evidence construction
            evidence = BoxBinAssociationEvidence(
                same_camera=True,
                same_zone=cand["same_zone"],
                box_zone=cand["box_zone"],
                bin_zone=cand["bin_zone"],
                temporal_overlap=True,
                spatial_proximity=cand["in_proximity"],
                consecutive_frames=assoc.consecutive_frames,
                missed_frames=0,
                normalized_distance=cand["norm_dist"],
                max_allowed_distance=self.config.max_normalized_distance,
                spatial_proximity_score=cand["spatial_score"],
                temporal_persistence_score=cand["temporal_score"],
                zone_score=cand["zone_score"],
                is_ambiguous=is_ambiguous,
                competing_bin_ids=competing_ids,
                ambiguity_reason=ambiguity_reason
            )
            assoc.evidence = evidence

            # Determine Association State:
            # 1. Spatial distance rejection
            if not cand["in_proximity"]:
                assoc.status = AssociationState.REJECTED
            # 2. Zone mismatch rejection (if require_same_zone and both have known distinct zones)
            elif (self.config.require_same_zone and
                  cand["box_zone"] is not None and
                  cand["bin_zone"] is not None and
                  str(cand["box_zone"]).upper() != str(cand["bin_zone"]).upper()):
                assoc.status = AssociationState.REJECTED
            # 3. Ambiguity prevents confirmation
            elif is_ambiguous:
                assoc.status = AssociationState.CANDIDATE
            # 4. Confirmation criteria satisfied:
            #    - Consecutive frames >= min_consecutive_frames (default 3)
            #    - Association score >= min_association_score (default 0.70)
            #    - Same zone == True (both have resolved matching zone)
            elif (assoc.consecutive_frames >= self.config.min_consecutive_frames and
                  assoc.association_score >= self.config.min_association_score and
                  cand["same_zone"]):
                assoc.status = AssociationState.CONFIRMED
            else:
                # Remains CANDIDATE (evidence accumulating or zone missing)
                assoc.status = AssociationState.CANDIDATE

            # Real-World Master Identity Binding (Section 16)
            # Derive ONLY if BOTH Box and Bin have VALIDATED master data identities
            b_val_status = assoc.box_identity.get("validation_status")
            bn_val_status = assoc.bin_identity.get("validation_status")
            b_val_id = assoc.box_identity.get("value")
            bn_val_id = assoc.bin_identity.get("value")

            if (b_val_status == "VALIDATED" and
                bn_val_status == "VALIDATED" and
                b_val_id and
                bn_val_id):
                assoc.real_world_association = {
                    "box_id": b_val_id,
                    "box_display": f"Box SKU: {b_val_id}",
                    "bin_id": bn_val_id,
                    "bin_display": f"Bin {bn_val_id}",
                    "status": "VALIDATED"
                }
            else:
                assoc.real_world_association = None

            updated_associations.append(assoc)

        # 6. Lifecycle Management for Departed / Missing Tracks
        # If a pair was previously tracked but one or both objects are not in the current frame
        for pair_key, assoc in list(self.associations.items()):
            if pair_key not in current_pair_keys:
                assoc.missed_frames += 1
                if assoc.evidence:
                    assoc.evidence.missed_frames = assoc.missed_frames
                    assoc.evidence.temporal_overlap = False

                if assoc.missed_frames >= self.config.association_timeout_frames:
                    assoc.status = AssociationState.EXPIRED
                    assoc.consecutive_frames = 0
                else:
                    # Still in timeout window, preserve status or mark CANDIDATE
                    if assoc.status == AssociationState.CONFIRMED:
                        assoc.status = AssociationState.CONFIRMED
                    else:
                        assoc.status = AssociationState.CANDIDATE

                updated_associations.append(assoc)

        return updated_associations


# ============================================================================
# 4. GLOBAL MULTI-OBJECT BOX <-> BIN ASSOCIATION SERVICE
# ============================================================================
class MultiObjectBoxBinAssociationService:
    """
    High-level Part 11 Service coordinating Camera Sessions, Part 8 Validation Layer,
    Synthetic/Real inference pipelines, and Visual Annotation Rendering.
    """

    def __init__(self, config: Optional[BoxBinAssociationConfig] = None):
        self.config = config or BoxBinAssociationConfig()
        self.validation_service = get_validation_service()
        # In-memory camera sessions: camera_id -> CameraBoxBinAssociationSession
        self.sessions: Dict[str, CameraBoxBinAssociationSession] = {}
        # Cached annotated frames for rendering/debugging: camera_id -> BGR ndarray
        self._annotated_frames: Dict[str, np.ndarray] = {}
        logger.info("MultiObjectBoxBinAssociationService initialized successfully.")

    def get_session(self, camera_id: str = "CAM-001") -> CameraBoxBinAssociationSession:
        """Retrieve or lazily instantiate an isolated in-memory session for the given camera."""
        if camera_id not in self.sessions:
            self.sessions[camera_id] = CameraBoxBinAssociationSession(camera_id, self.config)
        return self.sessions[camera_id]

    def reset_session(self, camera_id: str = "CAM-001") -> Dict[str, Any]:
        """Reset association tracking state for a specific camera."""
        if camera_id in self.sessions:
            self.sessions[camera_id].reset()
        if camera_id in self._annotated_frames:
            del self._annotated_frames[camera_id]
        return {
            "success": True,
            "camera_id": camera_id,
            "message": f"Box <-> Bin association session for '{camera_id}' has been reset."
        }

    def get_status(self) -> Dict[str, Any]:
        """Diagnostic operational status reporting."""
        val_status = self.validation_service.get_status()
        active_sessions = {
            cam_id: {
                "frame_index": sess.frame_index,
                "associations_tracked": len(sess.associations),
                "confirmed_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.CONFIRMED),
                "candidate_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.CANDIDATE),
                "rejected_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.REJECTED),
                "expired_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.EXPIRED),
                "last_update": sess.last_update_time
            }
            for cam_id, sess in self.sessions.items()
        }
        return {
            "status": "healthy",
            "service": "Box <-> Bin Association Foundation (Part 11)",
            "config": self.config.to_dict(),
            "database_access": "ZERO-WRITES (Strictly In-Memory)",
            "active_camera_sessions": active_sessions,
            "upstream_validation": val_status
        }

    def _load_camera_zones(self, camera_id: str) -> List[Dict[str, Any]]:
        """
        Load configured visual zones/ROIs from database for spatial containment.
        Read-only query via db.get_camera_rois.
        """
        import db
        zones = []
        try:
            rois = db.get_camera_rois(camera_id)
            for r in rois:
                poly = r.get("coordinates")
                if poly and len(poly) >= 3:
                    zones.append({
                        "id": r.get("id"),
                        "zone_code": r.get("zone_code"),
                        "zone_name": r.get("zone_name"),
                        "zone_type": r.get("zone_type"),
                        "polygon": poly
                    })
        except Exception as e:
            logger.warning(f"Error reading camera zones for '{camera_id}': {e}")
        return zones

    def process_tracks(
        self,
        tracks: List[Dict[str, Any]],
        camera_id: str = "CAM-001",
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Directly execute association logic on pre-extracted tracks (supports Part 8 or synthetic sequences).
        Returns: (associations_list, association_latency_ms)
        """
        t_start = time.perf_counter()
        session = self.get_session(camera_id)
        if camera_zones is None:
            camera_zones = self._load_camera_zones(camera_id)

        # Enrich tracks with validation if missing
        missing_val = [t for t in tracks if "validation" not in t]
        if missing_val and hasattr(self.validation_service, "validator"):
            for t in missing_val:
                cls_code = str(t.get("class_code", "")).upper()
                ident = t.get("identity", {})
                ident_val = ident.get("value")
                ident_status = ident.get("status", "UNIDENTIFIED")
                ident_src = ident.get("source")
                t["validation"] = self.validation_service.validator.validate_identity(
                    class_code=cls_code,
                    identity_value=ident_val,
                    identity_status=ident_status,
                    identity_source=ident_src
                )

        updated_assocs = session.update(tracks, camera_zones, frame_index=frame_index)
        assoc_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        return [a.to_dict() for a in updated_assocs], assoc_ms

    def process_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Full End-to-End Pipeline:
        Frame -> Part 5 YOLO -> Part 6 ByteTrack -> Part 7 Identity -> Part 8 Validation -> Part 11 Box <-> Bin Association.
        """
        t_total_start = time.perf_counter()

        # Step 1-4: Execute upstream validation pipeline
        val_res = self.validation_service.process_frame(
            frame_input=frame_input,
            camera_id=camera_id,
            conf_threshold=conf_threshold,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code
        )

        if not val_res.get("success"):
            return {
                "success": False,
                "error": val_res.get("error", "Upstream validation pipeline failure"),
                "camera_id": camera_id,
                "associations": [],
                "performance": val_res.get("performance", {})
            }

        tracks = val_res.get("tracks", [])
        upstream_perf = val_res.get("performance", {})

        # Step 5: Execute Part 11 Box <-> Bin Association
        camera_zones = self._load_camera_zones(camera_id)
        session = self.get_session(camera_id)

        t_assoc_start = time.perf_counter()
        updated_assocs = session.update(tracks, camera_zones)
        assoc_ms = round((time.perf_counter() - t_assoc_start) * 1000.0, 2)

        # Generate annotated frame
        annotated_b64 = None
        raw_bgr, _ = self.validation_service.identity_service.detection_engine._parse_image(frame_input)
        if raw_bgr is not None:
            annotated = self.render_annotated_frame(raw_bgr, updated_assocs, camera_id)
            self._annotated_frames[camera_id] = annotated
            _, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if _ and buf is not None:
                annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")

        total_ms = round((time.perf_counter() - t_total_start) * 1000.0, 2)

        perf = {
            "detection_ms": upstream_perf.get("detection_ms", 0.0),
            "tracking_ms": upstream_perf.get("tracking_ms", 0.0),
            "identity_ms": upstream_perf.get("identity_ms", 0.0),
            "validation_ms": upstream_perf.get("validation_ms", 0.0),
            "association_ms": assoc_ms,
            "total_ms": total_ms
        }

        # Count active tracks
        active_boxes = sum(1 for t in tracks if str(t.get("class_code", "")).upper() in ("BOX", "CARTON", "PACKAGE", "CONTAINER"))
        active_bins = sum(1 for t in tracks if str(t.get("class_code", "")).upper() in ("BIN", "STORAGE_BIN", "TOTE", "BAY", "SLOT", "LOCATION"))

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": f"sess_box_bin_{camera_id}_{session.frame_index}",
            "frame_index": session.frame_index,
            "active_boxes": active_boxes,
            "active_bins": active_bins,
            "tracks": tracks,
            "associations": [a.to_dict() for a in updated_assocs],
            "confirmed_count": sum(1 for a in updated_assocs if a.status == AssociationState.CONFIRMED),
            "candidate_count": sum(1 for a in updated_assocs if a.status == AssociationState.CANDIDATE),
            "rejected_count": sum(1 for a in updated_assocs if a.status == AssociationState.REJECTED),
            "expired_count": sum(1 for a in updated_assocs if a.status == AssociationState.EXPIRED),
            "ambiguous_count": sum(1 for a in updated_assocs if a.evidence and a.evidence.is_ambiguous),
            "performance": perf,
            "annotated_frame": annotated_b64
        }

    def run_sequence(
        self,
        camera_id: str = "CAM-001",
        num_frames: int = 5,
        sample_scene: str = "association_box_bin_dock1.jpg",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        synthetic_tracks_sequence: Optional[List[List[Dict[str, Any]]]] = None
    ) -> Dict[str, Any]:
        """
        Controlled Multi-Frame Sequence Test.
        Runs consecutive frames to verify temporal association accumulation:
        Frame 1 -> CANDIDATE
        Frame 2 -> CANDIDATE
        Frame 3 -> CONFIRMED
        """
        history = []
        if synthetic_tracks_sequence:
            camera_zones = self._load_camera_zones(camera_id)
            if roi_polygon and roi_zone_code:
                camera_zones.insert(0, {
                    "zone_code": roi_zone_code,
                    "zone_name": roi_zone_code,
                    "polygon": roi_polygon
                })

            for idx, frame_tracks in enumerate(synthetic_tracks_sequence, start=1):
                assocs, assoc_ms = self.process_tracks(
                    tracks=frame_tracks,
                    camera_id=camera_id,
                    frame_index=idx,
                    camera_zones=camera_zones
                )
                step = {
                    "frame_index": idx,
                    "active_tracks": len(frame_tracks),
                    "associations_count": len(assocs),
                    "confirmed_count": sum(1 for a in assocs if a.get("status") == AssociationState.CONFIRMED),
                    "candidate_count": sum(1 for a in assocs if a.get("status") == AssociationState.CANDIDATE),
                    "ambiguous_count": sum(1 for a in assocs if a.get("evidence", {}).get("is_ambiguous", False)),
                    "associations": assocs,
                    "association_ms": assoc_ms
                }
                history.append(step)

            return {
                "success": True,
                "mode": "synthetic_sequence",
                "camera_id": camera_id,
                "total_frames": len(synthetic_tracks_sequence),
                "history": history,
                "final_associations": history[-1]["associations"] if history else []
            }

        # Real frame / sample scene sequence
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_box_bin_dock1.jpg")

        frame = cv2.imread(sample_path)
        if frame is None:
            return {"success": False, "message": f"Sample scene '{sample_scene}' could not be loaded."}

        for idx in range(1, num_frames + 1):
            res = self.process_frame(
                frame_input=frame,
                camera_id=camera_id,
                conf_threshold=conf_threshold,
                roi_polygon=roi_polygon,
                roi_zone_code=roi_zone_code
            )
            history.append({
                "frame_index": idx,
                "confirmed_count": res.get("confirmed_count", 0),
                "candidate_count": res.get("candidate_count", 0),
                "associations": res.get("associations", [])
            })

        return {
            "success": True,
            "mode": "image_sequence",
            "camera_id": camera_id,
            "total_frames": num_frames,
            "history": history,
            "final_associations": history[-1]["associations"] if history else []
        }

    def process_sequence(
        self,
        sequence: List[Any],
        camera_id: str = "CAM-001"
    ) -> Dict[str, Any]:
        """
        Execute controlled multi-frame sequence (real frames or synthetic track arrays).
        Used for verification of temporal accumulation (CANDIDATE -> CONFIRMED -> EXPIRED).
        """
        t_seq_start = time.perf_counter()
        session = self.get_session(camera_id)
        camera_zones = self._load_camera_zones(camera_id)
        results = []

        is_synthetic = False

        for f_idx, item in enumerate(sequence, start=1):
            if isinstance(item, list):
                # Synthetic pre-extracted tracks mode
                is_synthetic = True
                assocs, a_ms = self.process_tracks(
                    tracks=item,
                    camera_id=camera_id,
                    frame_index=f_idx,
                    camera_zones=camera_zones
                )
                results.append({
                    "frame_index": f_idx,
                    "associations": assocs,
                    "confirmed": sum(1 for a in assocs if a["status"] == AssociationState.CONFIRMED),
                    "candidates": sum(1 for a in assocs if a["status"] == AssociationState.CANDIDATE),
                    "rejected": sum(1 for a in assocs if a["status"] == AssociationState.REJECTED),
                    "expired": sum(1 for a in assocs if a["status"] == AssociationState.EXPIRED),
                    "ambiguous": sum(1 for a in assocs if a["evidence"] and a["evidence"]["is_ambiguous"])
                })
            else:
                # Real image frame mode
                frame_res = self.process_frame(item, camera_id=camera_id)
                results.append(frame_res)

        total_ms = round((time.perf_counter() - t_seq_start) * 1000.0, 2)
        last_assocs = results[-1].get("associations", []) if results else []

        return {
            "success": True,
            "camera_id": camera_id,
            "is_synthetic": is_synthetic,
            "total_frames": len(sequence),
            "frame_results": results,
            "final_associations": last_assocs,
            "total_sequence_ms": total_ms
        }

    def render_annotated_frame(
        self,
        frame_bgr: np.ndarray,
        associations: List[BoxBinAssociation],
        camera_id: str = "CAM-001"
    ) -> np.ndarray:
        """
        Render clean, explainable visual overlays:
        - Bounding boxes for Boxes and Bins with distinct color codes
        - Connecting dynamic status lines (CONFIRMED=Green, CANDIDATE=Amber, REJECTED=Red, EXPIRED=Gray)
        - Pair score pills with association state badges
        - Telemetry footer strip
        """
        annotated = frame_bgr.copy()
        h, w = annotated.shape[:2]

        # Status styling colors (BGR)
        COLOR_CONFIRMED = (46, 204, 113)   # Bright green
        COLOR_CANDIDATE = (241, 196, 15)   # Amber / Gold
        COLOR_REJECTED = (52, 73, 235)     # Coral / Red
        COLOR_EXPIRED = (120, 120, 120)    # Gray
        COLOR_BOX = (220, 150, 40)         # Amber / Brown (Box)
        COLOR_BIN = (235, 140, 20)         # Deep cyan / Blue (Bin)

        def get_status_color(status: str) -> Tuple[int, int, int]:
            if status == AssociationState.CONFIRMED:
                return COLOR_CONFIRMED
            if status == AssociationState.CANDIDATE:
                return COLOR_CANDIDATE
            if status == AssociationState.REJECTED:
                return COLOR_REJECTED
            return COLOR_EXPIRED

        # 1. Draw object bounding boxes
        drawn_tracks = set()
        for a in associations:
            # Draw Box
            if a.box_track_id not in drawn_tracks and a.box_bbox:
                drawn_tracks.add(a.box_track_id)
                bx1 = a.box_bbox.get("x1", 0)
                by1 = a.box_bbox.get("y1", 0)
                bx2 = a.box_bbox.get("x2", 0)
                by2 = a.box_bbox.get("y2", 0)
                cv2.rectangle(annotated, (bx1, by1), (bx2, by2), COLOR_BOX, 2)
                b_lbl = f"Box #{a.box_track_id}"
                if a.box_identity.get("value"):
                    b_lbl += f" [{a.box_identity['value']}]"
                cv2.rectangle(annotated, (bx1, max(0, by1 - 18)), (bx1 + len(b_lbl) * 8 + 10, by1), COLOR_BOX, -1)
                cv2.putText(annotated, b_lbl, (bx1 + 4, max(12, by1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

            # Draw Bin
            if a.bin_track_id not in drawn_tracks and a.bin_bbox:
                drawn_tracks.add(a.bin_track_id)
                bnx1 = a.bin_bbox.get("x1", 0)
                bny1 = a.bin_bbox.get("y1", 0)
                bnx2 = a.bin_bbox.get("x2", 0)
                bny2 = a.bin_bbox.get("y2", 0)
                cv2.rectangle(annotated, (bnx1, bny1), (bnx2, bny2), COLOR_BIN, 2)
                bn_lbl = f"Bin #{a.bin_track_id}"
                if a.bin_identity.get("value"):
                    bn_lbl += f" [{a.bin_identity['value']}]"
                cv2.rectangle(annotated, (bnx1, max(0, bny1 - 18)), (bnx1 + len(bn_lbl) * 8 + 10, bny1), COLOR_BIN, -1)
                cv2.putText(annotated, bn_lbl, (bnx1 + 4, max(12, bny1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)

        # 2. Draw connecting association lines and badge pills
        for a in associations:
            if a.status == AssociationState.EXPIRED:
                continue

            color = get_status_color(a.status)
            bx = int(a.box_center[0] * w)
            by = int(a.box_center[1] * h)
            bnx = int(a.bin_center[0] * w)
            bny = int(a.bin_center[1] * h)

            # Draw connecting line
            thickness = 2 if a.status == AssociationState.CONFIRMED else 1
            cv2.line(annotated, (bx, by), (bnx, bny), color, thickness, cv2.LINE_AA)

            # Draw center point markers
            cv2.circle(annotated, (bx, by), 4, COLOR_BOX, -1)
            cv2.circle(annotated, (bnx, bny), 4, COLOR_BIN, -1)

            # Midpoint pill badge
            mid_x = (bx + bnx) // 2
            mid_y = (by + bny) // 2

            score_pct = int(a.association_score * 100)
            badge_text = f"{a.status} {score_pct}% [F:{a.consecutive_frames}]"
            if a.evidence and a.evidence.is_ambiguous:
                badge_text = f"AMBIGUOUS {score_pct}%"

            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.40
            (tw, th), _ = cv2.getTextSize(badge_text, font, scale, 1)

            x1_bg = mid_x - tw // 2 - 6
            y1_bg = mid_y - th // 2 - 4
            x2_bg = mid_x + tw // 2 + 6
            y2_bg = mid_y + th // 2 + 4

            cv2.rectangle(annotated, (x1_bg, y1_bg), (x2_bg, y2_bg), (20, 25, 35), -1)
            cv2.rectangle(annotated, (x1_bg, y1_bg), (x2_bg, y2_bg), color, 1)
            cv2.putText(annotated, badge_text, (x1_bg + 6, y2_bg - 4),
                        font, scale, color, 1, cv2.LINE_AA)

        # 3. Telemetry footer strip
        cv2.rectangle(annotated, (0, h - 28), (w, h), (15, 23, 42), -1)
        confirmed_cnt = sum(1 for a in associations if a.status == AssociationState.CONFIRMED)
        cand_cnt = sum(1 for a in associations if a.status == AssociationState.CANDIDATE)
        stat_text = (
            f"{camera_id} | Box <-> Bin | Frame #{self.get_session(camera_id).frame_index} | "
            f"Confirmed: {confirmed_cnt} | Candidates: {cand_cnt} | Total Pairs: {len(associations)}"
        )
        cv2.putText(annotated, stat_text, (10, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 215, 230), 1, cv2.LINE_AA)

        return annotated

    def get_annotated_jpeg(self, camera_id: str = "CAM-001") -> Optional[bytes]:
        """Encode the latest annotated frame as JPEG bytes."""
        frame = self._annotated_frames.get(camera_id)
        if frame is None:
            return None
        success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not success:
            return None
        return buf.tobytes()


# Global Singleton Instance
_box_bin_association_service: Optional[MultiObjectBoxBinAssociationService] = None


def get_box_bin_association_service() -> MultiObjectBoxBinAssociationService:
    """Retrieve or lazily initialize the singleton MultiObjectBoxBinAssociationService."""
    global _box_bin_association_service
    if _box_bin_association_service is None:
        _box_bin_association_service = MultiObjectBoxBinAssociationService()
    return _box_bin_association_service
