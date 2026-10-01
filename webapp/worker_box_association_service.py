"""
AI Vision & Tracking Master - Worker <-> Box Association Foundation
Part 10: Controlled, Evidence-Based Association between Tracked Workers and Boxes.

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

Track vs Real-World Identity:
  - Track-level association: Worker Track #W <-> Box Track #B
  - Real-world association: Worker Maddy <-> Box VLV-900
  Real-world identity association is derived ONLY when BOTH underlying tracks
  have been successfully IDENTIFIED and VALIDATED by Part 8 master-data binding.

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
class WorkerBoxAssociationConfig:
    """
    Explicit, documented configuration parameters for Worker <-> Box Association.
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

    # Ambiguity delta threshold: if two competing workers have scores within this delta, flag as AMBIGUOUS
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
    """Standardized lifecycle states for Worker <-> Box associations."""
    CANDIDATE = "CANDIDATE"      # Evidence accumulating or ambiguous, confirmation threshold not yet reached
    CONFIRMED = "CONFIRMED"      # Satisfied consecutive frames, score, distance, and same-zone requirements
    REJECTED = "REJECTED"        # Disqualified (e.g. mismatched zones, excessive distance, or invalid evidence)
    EXPIRED = "EXPIRED"          # One or both objects departed frame, or association timed out


# ============================================================================
# 2. EVIDENCE & ASSOCIATION DATA STRUCTURES
# ============================================================================
@dataclass
class WorkerBoxAssociationEvidence:
    """
    Structured, fully transparent, explainable evidence record for an association pair.
    Explicitly NOT presented as a black-box probability.
    """
    same_camera: bool
    same_zone: bool
    worker_zone: Optional[str]
    box_zone: Optional[str]
    temporal_overlap: bool
    spatial_proximity: bool
    consecutive_frames: int
    missed_frames: int
    normalized_distance: float
    max_allowed_distance: float
    spatial_proximity_score: float
    zone_score: float
    temporal_persistence_score: float
    is_ambiguous: bool
    competing_worker_ids: List[int] = field(default_factory=list)
    ambiguity_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "same_camera": self.same_camera,
            "same_zone": self.same_zone,
            "worker_zone": self.worker_zone,
            "box_zone": self.box_zone,
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
            "competing_worker_ids": self.competing_worker_ids,
            "ambiguity_reason": self.ambiguity_reason
        }


class WorkerBoxAssociation:
    """
    Represents an active or historical pairwise association between a Worker Track and a Box Track.
    """
    def __init__(
        self,
        camera_id: str,
        worker_track_id: int,
        box_track_id: int,
        initial_frame: int
    ):
        self.camera_id = camera_id
        self.worker_track_id = worker_track_id
        self.box_track_id = box_track_id
        self.first_seen_frame = initial_frame
        self.last_seen_frame = initial_frame
        self.consecutive_frames = 1
        self.missed_frames = 0
        self.status = AssociationState.CANDIDATE
        self.association_score = 0.0
        self.evidence: Optional[WorkerBoxAssociationEvidence] = None

        # Track metadata cache
        self.worker_identity: Dict[str, Any] = {"value": None, "validation_status": "NOT_APPLICABLE"}
        self.box_identity: Dict[str, Any] = {"value": None, "validation_status": "NOT_APPLICABLE"}
        self.real_world_association: Optional[Dict[str, Any]] = None

        # Coordinates for visualization
        self.worker_center: Tuple[float, float] = (0.0, 0.0)
        self.box_center: Tuple[float, float] = (0.0, 0.0)
        self.worker_bbox: Dict[str, int] = {}
        self.box_bbox: Dict[str, int] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_track_id": self.worker_track_id,
            "box_track_id": self.box_track_id,
            "status": self.status,
            "association_score": round(self.association_score, 4),
            "worker_identity": self.worker_identity,
            "box_identity": self.box_identity,
            "real_world_association": self.real_world_association,
            "evidence": self.evidence.to_dict() if self.evidence else {},
            "first_seen_frame": self.first_seen_frame,
            "last_seen_frame": self.last_seen_frame,
            "worker_center": [round(c, 4) for c in self.worker_center],
            "box_center": [round(c, 4) for c in self.box_center]
        }


# ============================================================================
# 3. CAMERA WORKER-BOX ASSOCIATION SESSION (TEMPORAL STATE MANAGER)
# ============================================================================
class CameraWorkerBoxAssociationSession:
    """
    Manages in-memory temporal state, pairwise tracking, and association lifecycle
    for a single camera source. Fully isolated from other cameras.
    """
    def __init__(self, camera_id: str, config: Optional[WorkerBoxAssociationConfig] = None):
        self.camera_id = camera_id
        self.config = config or WorkerBoxAssociationConfig()
        self.frame_index = 0
        # Active associations keyed by (worker_track_id, box_track_id)
        self.associations: Dict[Tuple[int, int], WorkerBoxAssociation] = {}
        self.last_update_time = time.time()

    def reset(self):
        """Reset temporal state for this camera session."""
        self.frame_index = 0
        self.associations.clear()
        self.last_update_time = time.time()
        logger.info(f"Worker-Box Association session for camera '{self.camera_id}' reset.")

    def _resolve_zone_for_track(
        self,
        track: Dict[str, Any],
        camera_zones: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Determine warehouse zone/ROI for a track:
        1. Check direct 'roi' dictionary on track
        2. Check top-level 'roi_zone_code'
        3. Test normalized center point against registered camera zones from database
        """
        # 1. Direct roi dictionary
        roi_info = track.get("roi", {})
        if roi_info.get("inside") and roi_info.get("zone_code"):
            return str(roi_info["zone_code"]).strip()
        if track.get("roi_zone_code"):
            return str(track["roi_zone_code"]).strip()

        # 2. Test center point against camera zones
        cx, cy = self._get_normalized_center(track)
        for z in camera_zones:
            poly = z.get("polygon")
            if poly and len(poly) >= 3:
                if is_point_in_polygon({"x": cx, "y": cy}, poly):
                    return z.get("zone_code")
        return None

    @staticmethod
    def _get_normalized_center(track: Dict[str, Any]) -> Tuple[float, float]:
        """Extract or compute normalized center (cx, cy) in [0.0, 1.0]."""
        if "center_normalized" in track and track["center_normalized"]:
            cn = track["center_normalized"]
            if isinstance(cn, (list, tuple)) and len(cn) >= 2:
                return float(cn[0]), float(cn[1])
            elif isinstance(cn, dict):
                return float(cn.get("x", 0.0)), float(cn.get("y", 0.0))

        # Check bbox_normalized
        bn = track.get("bbox_normalized")
        if bn:
            if isinstance(bn, dict):
                cx = (float(bn.get("x1", 0.0)) + float(bn.get("x2", 0.0))) / 2.0
                cy = (float(bn.get("y1", 0.0)) + float(bn.get("y2", 0.0))) / 2.0
                return cx, cy
            elif isinstance(bn, (list, tuple)) and len(bn) >= 4:
                return (float(bn[0]) + float(bn[2])) / 2.0, (float(bn[1]) + float(bn[3])) / 2.0

        return 0.0, 0.0

    @staticmethod
    def _calculate_euclidean_distance(c1: Tuple[float, float], c2: Tuple[float, float]) -> float:
        """
        Compute normalized Euclidean distance between two center points:
        d = sqrt((cx1 - cx2)^2 + (cy1 - cy2)^2)
        """
        dx = c1[0] - c2[0]
        dy = c1[1] - c2[1]
        return math.sqrt(dx * dx + dy * dy)

    def update(
        self,
        tracks: List[Dict[str, Any]],
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> List[WorkerBoxAssociation]:
        """
        Process a single frame of multi-object tracks and update pairwise associations.
        """
        if frame_index is not None:
            self.frame_index = frame_index
        else:
            self.frame_index += 1

        self.last_update_time = time.time()
        camera_zones = camera_zones or []

        # 1. Separate tracks into Workers and Boxes
        workers: List[Dict[str, Any]] = []
        boxes: List[Dict[str, Any]] = []

        for t in tracks:
            cls_code = str(t.get("class_code", "")).upper()
            if cls_code in ("WORKER", "PERSON", "OPERATOR"):
                workers.append(t)
            elif cls_code in ("BOX", "CARTON", "PACKAGE"):
                boxes.append(t)

        # 2. Enrich tracks with resolved warehouse zones
        for w in workers:
            w["_resolved_zone"] = self._resolve_zone_for_track(w, camera_zones)
            w["_norm_center"] = self._get_normalized_center(w)

        for b in boxes:
            b["_resolved_zone"] = self._resolve_zone_for_track(b, camera_zones)
            b["_norm_center"] = self._get_normalized_center(b)

        # 3. Calculate independent pairwise evidence for ALL active (Worker, Box) combinations
        current_pair_keys = set()
        active_candidates: Dict[Tuple[int, int], Dict[str, Any]] = {}

        for w in workers:
            w_id = int(w.get("track_id", 0))
            w_center = w["_norm_center"]
            w_zone = w["_resolved_zone"]

            for b in boxes:
                b_id = int(b.get("track_id", 0))
                b_center = b["_norm_center"]
                b_zone = b["_resolved_zone"]

                pair_key = (w_id, b_id)
                current_pair_keys.add(pair_key)

                # Spatial distance
                norm_dist = self._calculate_euclidean_distance(w_center, b_center)
                in_proximity = norm_dist <= self.config.max_normalized_distance

                # Proximity score S_spatial = max(0, 1 - d / max_d)
                if in_proximity and self.config.max_normalized_distance > 0:
                    spatial_score = max(0.0, 1.0 - (norm_dist / self.config.max_normalized_distance))
                else:
                    spatial_score = 0.0

                # Same Zone logic:
                # Both objects must have a non-empty resolved zone and they must match
                same_zone = (w_zone is not None and b_zone is not None and str(w_zone).upper() == str(b_zone).upper())
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
                    "worker": w,
                    "box": b,
                    "worker_id": w_id,
                    "box_id": b_id,
                    "worker_center": w_center,
                    "box_center": b_center,
                    "worker_zone": w_zone,
                    "box_zone": b_zone,
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

        # 4. Ambiguity Detection (Box Competing for Multiple Workers)
        # Check every box: if multiple workers have high scores or scores within ambiguity_threshold_delta
        box_worker_candidates: Dict[int, List[Dict[str, Any]]] = {}
        for pair_key, cand in active_candidates.items():
            b_id = cand["box_id"]
            if cand["in_proximity"]:
                box_worker_candidates.setdefault(b_id, []).append(cand)

        ambiguous_boxes: Dict[int, Tuple[List[int], str]] = {}
        for b_id, cands in box_worker_candidates.items():
            if len(cands) > 1:
                # Sort by score descending
                cands.sort(key=lambda x: x["score"], reverse=True)
                top_score = cands[0]["score"]
                second_score = cands[1]["score"]
                # If difference between top two candidates is less than ambiguity threshold delta
                if abs(top_score - second_score) <= self.config.ambiguity_threshold_delta:
                    competing_ids = [c["worker_id"] for c in cands]
                    reason = (
                        f"Box Track #{b_id} is simultaneously close to multiple workers "
                        f"({', '.join(f'Worker #{wid}' for wid in competing_ids)}) with score diff "
                        f"{abs(top_score - second_score):.3f} <= threshold delta {self.config.ambiguity_threshold_delta}."
                    )
                    ambiguous_boxes[b_id] = (competing_ids, reason)

        # 5. Update or Create Association Objects
        updated_associations: List[WorkerBoxAssociation] = []

        for pair_key, cand in active_candidates.items():
            w_id, b_id = pair_key
            assoc = self.associations.get(pair_key)
            if not assoc:
                assoc = WorkerBoxAssociation(
                    camera_id=self.camera_id,
                    worker_track_id=w_id,
                    box_track_id=b_id,
                    initial_frame=cand["first_seen"]
                )
                self.associations[pair_key] = assoc

            assoc.last_seen_frame = self.frame_index
            assoc.consecutive_frames = cand["consecutive_frames"]
            assoc.missed_frames = 0
            assoc.association_score = cand["score"]
            assoc.worker_center = cand["worker_center"]
            assoc.box_center = cand["box_center"]

            # Bounding boxes for visual rendering
            w_track = cand["worker"]
            b_track = cand["box"]
            assoc.worker_bbox = w_track.get("bbox", {})
            assoc.box_bbox = b_track.get("bbox", {})

            # Identity details from Part 7 / Part 8
            w_ident = w_track.get("identity", {})
            w_val = w_track.get("validation", {})
            assoc.worker_identity = {
                "value": w_ident.get("value"),
                "source": w_ident.get("source"),
                "status": w_ident.get("status", "UNIDENTIFIED"),
                "validation_status": w_val.get("status", "NOT_APPLICABLE"),
                "master_type": w_val.get("master_type"),
                "master_id": w_val.get("master_id"),
                "display_name": w_val.get("display_name")
            }

            b_ident = b_track.get("identity", {})
            b_val = b_track.get("validation", {})
            assoc.box_identity = {
                "value": b_ident.get("value"),
                "source": b_ident.get("source"),
                "status": b_ident.get("status", "UNIDENTIFIED"),
                "validation_status": b_val.get("status", "NOT_APPLICABLE"),
                "master_type": b_val.get("master_type"),
                "master_id": b_val.get("master_id"),
                "display_name": b_val.get("display_name")
            }

            # Check ambiguity for this box
            is_ambiguous = False
            competing_ids = []
            ambiguity_reason = None
            if b_id in ambiguous_boxes:
                is_ambiguous = True
                competing_ids, ambiguity_reason = ambiguous_boxes[b_id]

            # Evidence construction
            evidence = WorkerBoxAssociationEvidence(
                same_camera=True,
                same_zone=cand["same_zone"],
                worker_zone=cand["worker_zone"],
                box_zone=cand["box_zone"],
                temporal_overlap=True,
                spatial_proximity=cand["in_proximity"],
                consecutive_frames=assoc.consecutive_frames,
                missed_frames=0,
                normalized_distance=cand["norm_dist"],
                max_allowed_distance=self.config.max_normalized_distance,
                spatial_proximity_score=cand["spatial_score"],
                zone_score=cand["zone_score"],
                temporal_persistence_score=cand["temporal_score"],
                is_ambiguous=is_ambiguous,
                competing_worker_ids=competing_ids,
                ambiguity_reason=ambiguity_reason
            )
            assoc.evidence = evidence

            # Determine Association State:
            # Rule A: Zone requirement - if different zones and required -> REJECTED
            if self.config.require_same_zone and not cand["same_zone"]:
                if cand["worker_zone"] and cand["box_zone"] and cand["worker_zone"] != cand["box_zone"]:
                    assoc.status = AssociationState.REJECTED
                else:
                    # One or both zones missing -> cannot confirm, remain CANDIDATE
                    assoc.status = AssociationState.CANDIDATE

            # Rule B: Ambiguity - conflicting workers close to same box -> CANDIDATE
            elif is_ambiguous:
                assoc.status = AssociationState.CANDIDATE

            # Rule C: Confirmed requirement - multi-frame sustained proximity in same zone above score threshold
            elif (
                cand["in_proximity"] and
                cand["same_zone"] and
                assoc.consecutive_frames >= self.config.min_consecutive_frames and
                assoc.association_score >= self.config.min_association_score
            ):
                assoc.status = AssociationState.CONFIRMED

            # Rule D: In proximity but not yet reached consecutive frame / score threshold
            elif cand["in_proximity"]:
                assoc.status = AssociationState.CANDIDATE

            # Rule E: Outside allowed distance
            else:
                assoc.status = AssociationState.REJECTED

            # Derive Real-World Identity Association (Part 8 master-data binding)
            # Both identities must be VALIDATED in Part 8 to claim real-world association
            if (
                assoc.worker_identity.get("validation_status") == "VALIDATED" and
                assoc.box_identity.get("validation_status") == "VALIDATED" and
                assoc.worker_identity.get("value") and
                assoc.box_identity.get("value")
            ):
                assoc.real_world_association = {
                    "worker_id": assoc.worker_identity["value"],
                    "worker_display": assoc.worker_identity.get("display_name") or assoc.worker_identity["value"],
                    "box_id": assoc.box_identity["value"],
                    "box_display": assoc.box_identity.get("display_name") or assoc.box_identity["value"],
                    "status": "VALIDATED"
                }
            else:
                assoc.real_world_association = None

            updated_associations.append(assoc)

        # 6. Check for Missing / Departed Tracks (Timeout & Expiry Handling)
        for pair_key, assoc in list(self.associations.items()):
            if pair_key not in current_pair_keys:
                if assoc.status != AssociationState.EXPIRED:
                    assoc.missed_frames += 1
                    if assoc.evidence:
                        assoc.evidence.temporal_overlap = False
                        assoc.evidence.missed_frames = assoc.missed_frames

                    if assoc.missed_frames >= self.config.association_timeout_frames:
                        assoc.status = AssociationState.EXPIRED

                updated_associations.append(assoc)

        return updated_associations


# ============================================================================
# 4. MULTI-OBJECT WORKER-BOX ASSOCIATION SERVICE (PIPELINE COORDINATOR)
# ============================================================================
class MultiObjectWorkerBoxAssociationService:
    """
    Coordinates Part 5 Detection -> Part 6 Tracking -> Part 7 Identity ->
    Part 8 Master Validation -> Part 10 Worker <-> Box Association.
    Strictly in-memory with zero database writes.
    """
    def __init__(self, config: Optional[WorkerBoxAssociationConfig] = None):
        self.validation_service: MultiObjectValidationService = get_validation_service()
        self.config = config or WorkerBoxAssociationConfig()
        self.sessions: Dict[str, CameraWorkerBoxAssociationSession] = {}
        logger.info("MultiObjectWorkerBoxAssociationService initialized.")

    def get_session(self, camera_id: str) -> CameraWorkerBoxAssociationSession:
        """Get or create camera-specific temporal association session."""
        if camera_id not in self.sessions:
            self.sessions[camera_id] = CameraWorkerBoxAssociationSession(camera_id=camera_id, config=self.config)
        return self.sessions[camera_id]

    def reset_session(self, camera_id: str) -> bool:
        """Reset association and tracking session for a single camera."""
        if camera_id in self.sessions:
            self.sessions[camera_id].reset()
        self.validation_service.reset_session(camera_id)
        return True

    def reset_all(self):
        """Reset association and tracking sessions across all cameras."""
        for sess in self.sessions.values():
            sess.reset()
        self.validation_service.reset_all()

    def get_status(self) -> Dict[str, Any]:
        """Diagnostic operational status reporting."""
        val_status = self.validation_service.get_status()
        active_sessions = {
            cam_id: {
                "frame_index": sess.frame_index,
                "associations_tracked": len(sess.associations),
                "confirmed_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.CONFIRMED),
                "candidate_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.CANDIDATE),
                "expired_count": sum(1 for a in sess.associations.values() if a.status == AssociationState.EXPIRED),
                "last_update": sess.last_update_time
            }
            for cam_id, sess in self.sessions.items()
        }
        return {
            "status": "healthy",
            "service": "Worker <-> Box Association Foundation (Part 10)",
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

        assocs = session.update(tracks=tracks, frame_index=frame_index, camera_zones=camera_zones)
        assoc_dicts = [a.to_dict() for a in assocs]
        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return assoc_dicts, round(latency_ms, 2)

    def process_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        enable_barcode_qr: bool = True,
        enable_ocr: bool = True
    ) -> Dict[str, Any]:
        """
        End-to-End Pipeline Execution:
        Part 5 YOLO -> Part 6 ByteTrack -> Part 7 Identity -> Part 8 Master Validation -> Part 10 Worker <-> Box Association.
        """
        t_total_start = time.perf_counter()

        # 1. Execute upstream Part 8 Validation (which coordinates Parts 5, 6, 7, 8)
        val_res = self.validation_service.process_frame(
            frame_input=frame_input,
            camera_id=camera_id,
            conf_threshold=conf_threshold,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code,
            enable_barcode_qr=enable_barcode_qr,
            enable_ocr=enable_ocr
        )

        if not val_res.get("success", False):
            return val_res

        tracks = val_res.get("tracks", [])
        camera_zones = self._load_camera_zones(camera_id)

        # If explicit roi_polygon and roi_zone_code provided in request, inject it into camera_zones
        if roi_polygon and roi_zone_code:
            camera_zones.insert(0, {
                "zone_code": roi_zone_code,
                "zone_name": roi_zone_code,
                "polygon": roi_polygon
            })

        # 2. Execute Part 10 Association
        associations, assoc_ms = self.process_tracks(
            tracks=tracks,
            camera_id=camera_id,
            frame_index=val_res.get("frame_index"),
            camera_zones=camera_zones
        )

        # 3. Generate Visual Annotation with Connecting Lines and Association Badges
        raw_frame, _ = self.validation_service.identity_service.detection_engine._parse_image(frame_input)
        annotated_b64 = None
        if raw_frame is not None:
            session = self.get_session(camera_id)
            current_assocs = list(session.associations.values())
            annotated_frame = self.annotate_associations(raw_frame, current_assocs, tracks)
            ok, buf = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if ok:
                annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf.tobytes()).decode('utf-8')}"

        # 4. Association Statistics / KPIs
        confirmed_count = sum(1 for a in associations if a.get("status") == AssociationState.CONFIRMED)
        candidate_count = sum(1 for a in associations if a.get("status") == AssociationState.CANDIDATE)
        rejected_count = sum(1 for a in associations if a.get("status") == AssociationState.REJECTED)
        expired_count = sum(1 for a in associations if a.get("status") == AssociationState.EXPIRED)
        ambiguous_count = sum(1 for a in associations if a.get("evidence", {}).get("is_ambiguous", False))
        real_world_confirmed_count = sum(
            1 for a in associations
            if a.get("status") == AssociationState.CONFIRMED and a.get("real_world_association") is not None
        )

        # Performance Breakdown
        upstream_perf = val_res.get("performance", {})
        det_ms = upstream_perf.get("detection_ms", 0.0)
        track_ms = upstream_perf.get("tracking_ms", 0.0)
        ident_ms = upstream_perf.get("identity_ms", 0.0)
        val_ms = upstream_perf.get("validation_ms", 0.0)
        total_ms = round((time.perf_counter() - t_total_start) * 1000.0, 2)

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": val_res.get("session_id"),
            "frame_index": val_res.get("frame_index", 1),
            "timestamp": datetime.now().isoformat(),
            "frame_width": val_res.get("frame_width", 0),
            "frame_height": val_res.get("frame_height", 0),
            "active_worker_count": sum(1 for t in tracks if str(t.get("class_code")).upper() in ("WORKER", "PERSON", "OPERATOR")),
            "active_box_count": sum(1 for t in tracks if str(t.get("class_code")).upper() in ("BOX", "CARTON", "PACKAGE")),
            "total_associations": len(associations),
            "confirmed_count": confirmed_count,
            "candidate_count": candidate_count,
            "ambiguous_count": ambiguous_count,
            "rejected_count": rejected_count,
            "expired_count": expired_count,
            "real_world_confirmed_count": real_world_confirmed_count,
            "performance": {
                "detection_ms": det_ms,
                "tracking_ms": track_ms,
                "identity_ms": ident_ms,
                "validation_ms": val_ms,
                "association_ms": assoc_ms,
                "total_ms": total_ms
            },
            "tracks": tracks,
            "associations": associations,
            "annotated_frame": annotated_b64
        }

    def run_sequence(
        self,
        camera_id: str = "CAM-001",
        num_frames: int = 5,
        sample_scene: str = "association_worker_box_dock1.jpg",
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
        final_result = None

        if synthetic_tracks_sequence:
            # Synthetic tracking sequence test (testing pure association temporal accumulation)
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

            final_result = {
                "success": True,
                "mode": "synthetic_sequence",
                "camera_id": camera_id,
                "total_frames": len(synthetic_tracks_sequence),
                "history": history,
                "final_associations": history[-1]["associations"] if history else []
            }
            return final_result

        # Camera frame / sample scene sequence
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_worker_box_dock1.jpg")
            if not os.path.exists(sample_path):
                sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_truck_box_dock1.jpg")

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
            step = {
                "frame_index": idx,
                "total_associations": res.get("total_associations", 0),
                "confirmed_count": res.get("confirmed_count", 0),
                "candidate_count": res.get("candidate_count", 0),
                "ambiguous_count": res.get("ambiguous_count", 0),
                "associations": res.get("associations", []),
                "performance": res.get("performance", {})
            }
            history.append(step)
            final_result = res

        if final_result is not None:
            final_result["sequence_history"] = history
            final_result["total_frames_executed"] = num_frames
        return final_result or {"success": False, "message": "No frames executed."}

    def annotate_associations(
        self,
        frame: np.ndarray,
        associations: List[WorkerBoxAssociation],
        tracks: List[Dict[str, Any]]
    ) -> np.ndarray:
        """
        Render clean visual overlay:
          - Bounding boxes for Workers (Purple/Magenta) and Boxes (Orange/Amber)
          - Visual Track IDs and Validated Master-Data Badges
          - Connecting Lines between associated Worker and Box centers
          - Association Badge showing Status and Explainable Score
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        # Draw Tracks
        track_map = {int(t.get("track_id", 0)): t for t in tracks}

        # 1. Draw Object Bounding Boxes
        for t_id, track in track_map.items():
            cls_code = str(track.get("class_code", "")).upper()
            bbox = track.get("bbox", {})
            x1 = int(bbox.get("x1", 0))
            y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", 0))
            y2 = int(bbox.get("y2", 0))

            if x2 <= x1 or y2 <= y1:
                continue

            # Color scheme: WORKER = Purple/Magenta, BOX = Warm Amber/Orange
            if cls_code in ("WORKER", "PERSON", "OPERATOR"):
                box_color = (220, 50, 180) # BGR: Magenta / Purple
                label_prefix = f"WORKER #{t_id}"
            elif cls_code in ("BOX", "CARTON", "PACKAGE"):
                box_color = (0, 165, 255) # BGR: Warm Orange
                label_prefix = f"BOX #{t_id}"
            elif cls_code in ("TRUCK", "CARRIER"):
                box_color = (255, 140, 0)
                label_prefix = f"TRUCK #{t_id}"
            else:
                box_color = (180, 180, 180)
                label_prefix = f"{cls_code} #{t_id}"

            # Box outline
            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)

            # Identification and Validation label
            ident_val = track.get("identity", {}).get("value")
            val_status = track.get("validation", {}).get("status", "NOT_APPLICABLE")

            if val_status == "VALIDATED" and ident_val:
                badge_text = f"{label_prefix} [{ident_val}]"
                badge_bg = (40, 167, 69) # Green
            elif val_status == "UNREGISTERED" and ident_val:
                badge_text = f"{label_prefix} [{ident_val}]"
                badge_bg = (0, 140, 255) # Orange
            else:
                badge_text = label_prefix
                badge_bg = box_color

            # Draw label pill
            (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(annotated, (x1, max(0, y1 - 20)), (x1 + tw + 8, y1), badge_bg, -1)
            cv2.putText(
                annotated,
                badge_text,
                (x1 + 4, max(12, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA
            )

        # 2. Draw Association Connecting Lines and Status Pills
        for assoc in associations:
            if assoc.status == AssociationState.EXPIRED:
                continue

            w_track = track_map.get(assoc.worker_track_id)
            b_track = track_map.get(assoc.box_track_id)

            # Determine pixel centers
            if w_track and b_track:
                w_bbox = w_track.get("bbox", {})
                b_bbox = b_track.get("bbox", {})
                pt_worker = (
                    int((w_bbox.get("x1", 0) + w_bbox.get("x2", 0)) / 2),
                    int((w_bbox.get("y1", 0) + w_bbox.get("y2", 0)) / 2)
                )
                pt_box = (
                    int((b_bbox.get("x1", 0) + b_bbox.get("x2", 0)) / 2),
                    int((b_bbox.get("y1", 0) + b_bbox.get("y2", 0)) / 2)
                )
            else:
                pt_worker = (int(assoc.worker_center[0] * w), int(assoc.worker_center[1] * h))
                pt_box = (int(assoc.box_center[0] * w), int(assoc.box_center[1] * h))

            if pt_worker[0] <= 0 and pt_worker[1] <= 0:
                continue

            # Determine Line Style & Color based on state
            if assoc.status == AssociationState.CONFIRMED:
                line_color = (0, 220, 0)      # Solid Vibrant Green
                line_thickness = 2
                status_txt = f"CONFIRMED ({assoc.association_score:.2f})"
                status_bg = (0, 160, 0)
            elif assoc.evidence and assoc.evidence.is_ambiguous:
                line_color = (0, 140, 255)    # Orange for Ambiguity
                line_thickness = 2
                status_txt = f"AMBIGUOUS ({assoc.association_score:.2f})"
                status_bg = (0, 120, 220)
            elif assoc.status == AssociationState.CANDIDATE:
                line_color = (0, 220, 255)    # Yellow for Candidate
                line_thickness = 1
                status_txt = f"CANDIDATE ({assoc.association_score:.2f})"
                status_bg = (30, 160, 200)
            elif assoc.status == AssociationState.REJECTED:
                line_color = (60, 60, 220)    # Red for Rejected
                line_thickness = 1
                status_txt = "REJECTED (ZONE/DIST)"
                status_bg = (40, 40, 180)
            else:
                continue

            # Draw Connecting Line
            cv2.line(annotated, pt_worker, pt_box, line_color, line_thickness, cv2.LINE_AA)

            # Draw Association Badge at Midpoint
            mid_x = int((pt_worker[0] + pt_box[0]) / 2)
            mid_y = int((pt_worker[1] + pt_box[1]) / 2)

            (sw, sh), _ = cv2.getTextSize(status_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)
            rx1 = max(0, mid_x - int(sw / 2) - 4)
            ry1 = max(0, mid_y - int(sh / 2) - 4)
            rx2 = min(w - 1, rx1 + sw + 8)
            ry2 = min(h - 1, ry1 + sh + 8)

            cv2.rectangle(annotated, (rx1, ry1), (rx2, ry2), status_bg, -1)
            cv2.putText(
                annotated,
                status_txt,
                (rx1 + 4, ry1 + sh + 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                (255, 255, 255),
                1,
                cv2.LINE_AA
            )

        return annotated


# Global Singleton Service
_worker_box_association_service_instance: Optional[MultiObjectWorkerBoxAssociationService] = None


def get_worker_box_association_service() -> MultiObjectWorkerBoxAssociationService:
    """Singleton provider for MultiObjectWorkerBoxAssociationService."""
    global _worker_box_association_service_instance
    if _worker_box_association_service_instance is None:
        _worker_box_association_service_instance = MultiObjectWorkerBoxAssociationService()
    return _worker_box_association_service_instance
