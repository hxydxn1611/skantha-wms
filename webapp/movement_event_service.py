"""
AI Vision & Tracking Master - Warehouse Movement Event Detection Foundation
Part 12: Controlled, Explainable Event Layer for Warehouse Movements & Associations.

Core Principles:
  1. ASSOCIATION != EVENT != INVENTORY TRANSACTION.
     - An association means: "Object A has sufficient visual evidence of relationship with Object B."
     - An event means: "A meaningful state transition or observed relationship occurred over time."
     - An inventory transaction means: "The business system has accepted and recorded a business operation."
     Part 12 implements ONLY the event layer. It does NOT modify inventory or WMS business transactions.
  2. REUSE EXISTING PIPELINE:
     - Leverages Parts 5-11 outputs (Detection, Tracking, Identity, Validation, Truck/Worker/Bin Associations, Zones).
     - Does NOT recreate duplicate detection, tracking, or association algorithms.
  3. DEDUPLICATION:
     - Continuous presence inside a zone generates exactly ONE BOX_ENTERED_ZONE event while active.
     - Continuous confirmed association generates exactly ONE active event instance over time.
  4. TIMEOUT & REACTIVATION:
     - When an object or relationship departs/disappears, it transitions to EXPIRED after timeout frames.
     - When the relationship reoccurs later, a brand NEW event instance with a NEW event_id is created.
  5. TRACK VS REAL-WORLD IDENTITY:
     - Distinguishes TRACK_LEVEL from VALIDATED_REAL_WORLD events based on Part 8 validation status.
  6. ZERO DATABASE WRITES:
     - All event state is strictly maintained in-memory per camera session.
     - The SQLite database remains 100% untouched.
"""

import os
import time
import math
import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Union

import cv2
import numpy as np

# Upstream Service Singletons
from validation_service import get_validation_service, MultiObjectValidationService
from association_service import get_association_service, MultiObjectAssociationService
from worker_box_association_service import get_worker_box_association_service, MultiObjectWorkerBoxAssociationService
from box_bin_association_service import get_box_bin_association_service, MultiObjectBoxBinAssociationService
from detection_service import is_point_in_polygon

logger = logging.getLogger(__name__)


# ============================================================================
# 1. EVENT CONFIGURATION & CONSTANTS
# ============================================================================
@dataclass
class MovementEventConfig:
    """
    Documented configuration parameters for Warehouse Movement Event Detection.
    No unexplained magic numbers.
    """
    # Number of missing frames before an active event transitions to EXPIRED
    event_timeout_frames: int = 4

    # Minimum consecutive frames before a candidate association event becomes ACTIVE
    min_consecutive_frames: int = 3

    # Enable event deduplication (prevents spamming events on every frame)
    enable_deduplication: bool = True

    # Maximum events retained in in-memory session history
    max_history_events: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_timeout_frames": self.event_timeout_frames,
            "min_consecutive_frames": self.min_consecutive_frames,
            "enable_deduplication": self.enable_deduplication,
            "max_history_events": self.max_history_events
        }


class EventState(str, Enum):
    """Controlled lifecycle states for Warehouse Movement Events (Section 5)."""
    CANDIDATE = "CANDIDATE"      # Evidence accumulating, confirmation threshold not yet satisfied
    ACTIVE = "ACTIVE"            # Established and currently valid observation or state transition
    COMPLETED = "COMPLETED"      # Event lifecycle concluded normally (e.g. zone presence finished)
    EXPIRED = "EXPIRED"          # Evidence disappeared or timed out without normal completion
    CANCELLED = "CANCELLED"      # Invalidated by contradictory evidence (e.g. spatial rejection, ambiguity)


class EventType(str, Enum):
    """Strictly constrained Part 12 Event Types (Section 4)."""
    # Zone Events
    BOX_ENTERED_ZONE = "BOX_ENTERED_ZONE"
    BOX_EXITED_ZONE = "BOX_EXITED_ZONE"

    # Association Observation Events (Candidate / Proximity)
    BOX_NEAR_TRUCK = "BOX_NEAR_TRUCK"
    BOX_NEAR_WORKER = "BOX_NEAR_WORKER"
    BOX_NEAR_BIN = "BOX_NEAR_BIN"

    # Confirmed Association Events
    BOX_ASSOCIATED_WITH_TRUCK = "BOX_ASSOCIATED_WITH_TRUCK"
    BOX_ASSOCIATED_WITH_WORKER = "BOX_ASSOCIATED_WITH_WORKER"
    BOX_ASSOCIATED_WITH_BIN = "BOX_ASSOCIATED_WITH_BIN"


# ============================================================================
# 2. EVENT DATA MODEL
# ============================================================================
@dataclass
class MovementEvent:
    """
    Explainable, machine-readable Movement Event conforming to Section 3 specification.
    """
    event_id: str
    event_type: str
    camera_id: str
    timestamp: str
    primary_object: Dict[str, Any]
    secondary_object: Optional[Dict[str, Any]] = None
    zone: Optional[Dict[str, Any]] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    status: str = EventState.CANDIDATE
    event_level: str = "TRACK_LEVEL"  # "TRACK_LEVEL" or "VALIDATED_REAL_WORLD"
    created_frame: int = 1
    last_seen_frame: int = 1
    missed_frames: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "primary_object": self.primary_object,
            "secondary_object": self.secondary_object,
            "zone": self.zone,
            "evidence": self.evidence,
            "confidence": round(float(self.confidence), 4),
            "status": self.status,
            "event_level": self.event_level,
            "metrics": {
                "created_frame": self.created_frame,
                "last_seen_frame": self.last_seen_frame,
                "missed_frames": self.missed_frames
            }
        }


# ============================================================================
# 3. CAMERA SESSION EVENT DETECTOR
# ============================================================================
class CameraMovementEventSession:
    """
    Camera-isolated in-memory event detection session.
    Tracks box zone transitions, association events, deduplication, timeouts, and reactivation.
    """

    def __init__(self, camera_id: str, config: Optional[MovementEventConfig] = None):
        self.camera_id = camera_id
        self.config = config or MovementEventConfig()
        self.frame_index: int = 0
        self.event_counter: int = 0

        # Active events currently ongoing: key -> MovementEvent
        # Keys:
        #   Zone: ("ZONE_ENTER", box_track_id, zone_code)
        #   Assoc: ("ASSOC", assoc_type, box_track_id, other_track_id)
        self.active_events: Dict[Tuple, MovementEvent] = {}

        # Chronological event history (contains all generated events: CANDIDATE, ACTIVE, COMPLETED, EXPIRED, CANCELLED)
        self.event_history: List[MovementEvent] = []

        # Previous zone tracking per box: box_track_id -> Optional[str]
        self.box_zone_history: Dict[int, Optional[str]] = {}

        # Last update timestamp
        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_event_id(self) -> str:
        """Sequential unique event ID generator: EVT-000001, EVT-000002..."""
        self.event_counter += 1
        return f"EVT-{self.event_counter:06d}"

    def reset(self):
        """Reset all in-memory events, zone history, and counters for this camera."""
        self.active_events.clear()
        self.event_history.clear()
        self.box_zone_history.clear()
        self.event_counter = 0
        self.frame_index = 0
        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def candidate_events(self) -> List[MovementEvent]:
        """All candidate/proximity observation events currently ongoing."""
        return [e for e in self.active_events.values() if e.status == EventState.CANDIDATE.value]

    @property
    def history_events(self) -> List[MovementEvent]:
        """Chronological event history."""
        return self.event_history

    @property
    def box_zone_state(self) -> Dict[int, Optional[str]]:
        """Current zone assignment per tracked box."""
        return self.box_zone_history

    @staticmethod
    def _format_object_desc(track: Dict[str, Any], default_class: str = "UNKNOWN") -> Dict[str, Any]:
        """Format an object track into the standardized primary/secondary event structure."""
        t_id = int(track.get("track_id", 0))
        cls_code = str(track.get("class_code", default_class)).upper()
        ident = track.get("identity") or {}
        val = track.get("validation") or {}

        ident_val = track.get("identity_id") or ident.get("value") or track.get("identity")
        if isinstance(ident_val, dict):
            ident_val = ident_val.get("value")

        ident_status = track.get("identity_status") or ident.get("status", "UNIDENTIFIED" if not ident_val else "IDENTIFIED")
        val_status = track.get("validation_status") or val.get("status", "NOT_APPLICABLE" if ident_status == "UNIDENTIFIED" else "UNREGISTERED")

        if val_status == "VALIDATED" and val.get("display_name"):
            disp = val["display_name"]
        elif ident_val:
            disp = f"{cls_code}: {ident_val}"
        else:
            disp = f"{cls_code} Track #{t_id}"

        return {
            "track_id": t_id,
            "class_code": cls_code,
            "identity_id": ident_val,
            "identity_status": ident_status,
            "validation_status": val_status,
            "display_name": disp
        }

    def _determine_event_level(self, primary: Dict[str, Any], secondary: Optional[Dict[str, Any]] = None) -> str:
        """Derive VALIDATED_REAL_WORLD vs TRACK_LEVEL based on Part 8 validation status."""
        p_val = primary.get("validation_status") == "VALIDATED"
        if secondary is None:
            return "VALIDATED_REAL_WORLD" if p_val else "TRACK_LEVEL"
        s_val = secondary.get("validation_status") == "VALIDATED"
        return "VALIDATED_REAL_WORLD" if (p_val and s_val) else "TRACK_LEVEL"

    def _resolve_zone_for_track(self, track: Dict[str, Any], camera_zones: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Determine spatial zone for a track using explicit roi_zone_code or polygon testing.
        Returns: (zone_code, zone_metadata_dict)
        """
        # If no camera zones are supplied, fallback to built-in Dock 01 definition
        effective_zones = camera_zones
        if not effective_zones:
            effective_zones = [
                {
                    "id": 18,
                    "zone_code": "DOCK-01",
                    "zone_name": "Dock 01",
                    "zone_type": "DOCK",
                    "polygon": [{"x": 0.20, "y": 0.20}, {"x": 0.85, "y": 0.20}, {"x": 0.85, "y": 0.85}, {"x": 0.20, "y": 0.85}]
                }
            ]

        # Explicit zone code if pre-assigned
        z_code = track.get("roi_zone_code") or track.get("zone")
        if z_code:
            z_code_str = str(z_code).strip()
            for cz in effective_zones:
                if str(cz.get("zone_code", "")).upper() == z_code_str.upper():
                    return cz.get("zone_code"), {
                        "zone_id": cz.get("id"),
                        "zone_code": cz.get("zone_code"),
                        "zone_name": cz.get("zone_name", cz.get("zone_code"))
                    }
            return z_code_str, {
                "zone_id": None,
                "zone_code": z_code_str,
                "zone_name": z_code_str
            }

        # Otherwise compute from normalized center and polygon
        cn = track.get("center_normalized") or track.get("center")
        if not cn:
            bn = track.get("bbox_normalized") or track.get("bbox")
            if isinstance(bn, dict) and "x1" in bn and "x2" in bn:
                cn = [(float(bn["x1"]) + float(bn["x2"])) / 2.0, (float(bn["y1"]) + float(bn["y2"])) / 2.0]
            elif isinstance(bn, (list, tuple)) and len(bn) == 4:
                cn = [(float(bn[0]) + float(bn[2])) / 2.0, (float(bn[1]) + float(bn[3])) / 2.0]

        if cn:
            center_dict = {"x": float(cn[0]), "y": float(cn[1])}
            for cz in effective_zones:
                poly = cz.get("polygon")
                if poly and len(poly) >= 3:
                    if is_point_in_polygon(center_dict, poly):
                        return cz.get("zone_code"), {
                            "zone_id": cz.get("id"),
                            "zone_code": cz.get("zone_code"),
                            "zone_name": cz.get("zone_name", cz.get("zone_code"))
                        }

        return None, None

    def update(
        self,
        tracks: List[Dict[str, Any]],
        truck_box_assocs: Optional[List[Dict[str, Any]]] = None,
        worker_box_assocs: Optional[List[Dict[str, Any]]] = None,
        box_bin_assocs: Optional[List[Dict[str, Any]]] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None,
        frame_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process a single video frame / tracking step and evaluate movement events.
        Produces explainable events, deduplicates ongoing states, and handles timeout/expiration.
        """
        if frame_index is not None:
            self.frame_index = frame_index
        else:
            self.frame_index += 1

        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        camera_zones = camera_zones or []
        truck_box_assocs = truck_box_assocs or []
        worker_box_assocs = worker_box_assocs or []
        box_bin_assocs = box_bin_assocs or []

        current_frame_events: List[MovementEvent] = []
        seen_event_keys = set()

        # Separate boxes from tracks
        boxes: List[Dict[str, Any]] = []
        all_tracks_by_id: Dict[int, Dict[str, Any]] = {}
        for t in tracks:
            t_id = int(t.get("track_id", 0))
            all_tracks_by_id[t_id] = t
            cls_code = str(t.get("class_code", "")).upper()
            if cls_code in ("BOX", "CARTON", "PACKAGE", "CONTAINER", "CARDBOARD BOX"):
                boxes.append(t)

        current_box_ids = {int(b.get("track_id", 0)) for b in boxes}

        # --------------------------------------------------------------------
        # STEP 1: ZONE TRANSITION EVENTS (BOX_ENTERED_ZONE, BOX_EXITED_ZONE)
        # --------------------------------------------------------------------
        for box in boxes:
            box_id = int(box.get("track_id", 0))
            current_zone_code, zone_meta = self._resolve_zone_for_track(box, camera_zones)
            prev_zone_code = self.box_zone_history.get(box_id)

            primary_desc = self._format_object_desc(box, "BOX")

            # Check for Zone Transition
            if current_zone_code != prev_zone_code:
                # 1. Exit Event for previous zone if box was inside one
                if prev_zone_code is not None:
                    exit_key = ("ZONE_EXIT", box_id, prev_zone_code, self.frame_index)
                    seen_event_keys.add(exit_key)

                    # Mark prior active enter event as COMPLETED
                    enter_key = ("ZONE_ENTER", box_id, prev_zone_code)
                    if enter_key in self.active_events:
                        prior_enter = self.active_events[enter_key]
                        prior_enter.status = EventState.COMPLETED
                        prior_enter.last_seen_frame = self.frame_index
                        del self.active_events[enter_key]

                    # Generate BOX_EXITED_ZONE event
                    exit_event = MovementEvent(
                        event_id=self.generate_event_id(),
                        event_type=EventType.BOX_EXITED_ZONE,
                        camera_id=self.camera_id,
                        timestamp=self.last_update_time,
                        primary_object=primary_desc,
                        secondary_object=None,
                        zone={"zone_code": prev_zone_code, "zone_name": prev_zone_code},
                        evidence={
                            "same_camera": True,
                            "same_zone": False,
                            "transition": "EXIT",
                            "previous_zone": prev_zone_code,
                            "new_zone": current_zone_code,
                            "track_continuity": True
                        },
                        confidence=1.0,
                        status=EventState.ACTIVE,
                        event_level=self._determine_event_level(primary_desc),
                        created_frame=self.frame_index,
                        last_seen_frame=self.frame_index
                    )
                    self.active_events[exit_key] = exit_event
                    self.event_history.append(exit_event)
                    current_frame_events.append(exit_event)

                # 2. Enter Event for current zone if box is now inside one
                if current_zone_code is not None:
                    enter_key = ("ZONE_ENTER", box_id, current_zone_code)
                    seen_event_keys.add(enter_key)

                    enter_event = MovementEvent(
                        event_id=self.generate_event_id(),
                        event_type=EventType.BOX_ENTERED_ZONE,
                        camera_id=self.camera_id,
                        timestamp=self.last_update_time,
                        primary_object=primary_desc,
                        secondary_object=None,
                        zone=zone_meta or {"zone_code": current_zone_code, "zone_name": current_zone_code},
                        evidence={
                            "same_camera": True,
                            "same_zone": True,
                            "transition": "ENTER",
                            "zone_code": current_zone_code,
                            "spatial_containment": True,
                            "consecutive_frames": 1
                        },
                        confidence=1.0,
                        status=EventState.ACTIVE,
                        event_level=self._determine_event_level(primary_desc),
                        created_frame=self.frame_index,
                        last_seen_frame=self.frame_index
                    )
                    self.active_events[enter_key] = enter_event
                    self.event_history.append(enter_event)
                    current_frame_events.append(enter_event)

                # Update zone history
                self.box_zone_history[box_id] = current_zone_code

            else:
                # Box remained in the same zone (Deduplication Check)
                if current_zone_code is not None:
                    enter_key = ("ZONE_ENTER", box_id, current_zone_code)
                    seen_event_keys.add(enter_key)

                    if enter_key in self.active_events:
                        # Existing active event: update in-place without generating a duplicate
                        active_ev = self.active_events[enter_key]
                        active_ev.last_seen_frame = self.frame_index
                        active_ev.missed_frames = 0
                        active_ev.evidence["consecutive_frames"] = active_ev.evidence.get("consecutive_frames", 1) + 1
                        current_frame_events.append(active_ev)
                    else:
                        # If not active (e.g. initial frame or re-entered), create it
                        enter_event = MovementEvent(
                            event_id=self.generate_event_id(),
                            event_type=EventType.BOX_ENTERED_ZONE,
                            camera_id=self.camera_id,
                            timestamp=self.last_update_time,
                            primary_object=primary_desc,
                            secondary_object=None,
                            zone=zone_meta or {"zone_code": current_zone_code, "zone_name": current_zone_code},
                            evidence={
                                "same_camera": True,
                                "same_zone": True,
                                "transition": "ENTER",
                                "zone_code": current_zone_code,
                                "spatial_containment": True,
                                "consecutive_frames": 1
                            },
                            confidence=1.0,
                            status=EventState.ACTIVE,
                            event_level=self._determine_event_level(primary_desc),
                            created_frame=self.frame_index,
                            last_seen_frame=self.frame_index
                        )
                        self.active_events[enter_key] = enter_event
                        self.event_history.append(enter_event)
                        current_frame_events.append(enter_event)

        # --------------------------------------------------------------------
        # STEP 2: ASSOCIATION EVENTS (TRUCK, WORKER, BIN)
        # --------------------------------------------------------------------
        association_sets = [
            ("TRUCK", truck_box_assocs, EventType.BOX_NEAR_TRUCK, EventType.BOX_ASSOCIATED_WITH_TRUCK, "truck_track_id"),
            ("WORKER", worker_box_assocs, EventType.BOX_NEAR_WORKER, EventType.BOX_ASSOCIATED_WITH_WORKER, "worker_track_id"),
            ("BIN", box_bin_assocs, EventType.BOX_NEAR_BIN, EventType.BOX_ASSOCIATED_WITH_BIN, "bin_track_id")
        ]

        for assoc_type, assocs_list, near_event_type, confirmed_event_type, other_id_key in association_sets:
            for assoc in assocs_list:
                box_id = int(assoc.get("box_track_id", 0))
                other_id = int(assoc.get(other_id_key, 0))
                status = str(assoc.get("status") or assoc.get("association_state", "")).upper()
                assoc_score = float(assoc.get("association_score", 0.0))
                ev_data = assoc.get("evidence") or {}
                is_ambiguous = bool(assoc.get("is_ambiguous", False) or ev_data.get("is_ambiguous", False))

                # Retrieve raw track metadata or build from association dict
                box_track = all_tracks_by_id.get(box_id) or {
                    "track_id": box_id,
                    "class_code": "BOX",
                    "identity": assoc.get("box_identity") or {}
                }
                other_track = all_tracks_by_id.get(other_id) or {
                    "track_id": other_id,
                    "class_code": assoc_type,
                    "identity": assoc.get(f"{assoc_type.lower()}_identity") or {}
                }

                primary_desc = self._format_object_desc(box_track, "BOX")
                secondary_desc = self._format_object_desc(other_track, assoc_type)
                event_level = self._determine_event_level(primary_desc, secondary_desc)

                zone_code = ev_data.get("box_zone") or ev_data.get("zone")
                zone_meta = {"zone_code": zone_code, "zone_name": zone_code} if zone_code else None

                pair_key = ("ASSOC", assoc_type, box_id, other_id)
                seen_event_keys.add(pair_key)

                # Case A: CONFIRMED Association Event
                if status == "CONFIRMED" and not is_ambiguous:
                    if pair_key in self.active_events:
                        active_ev = self.active_events[pair_key]
                        # If already confirmed, update in-place (DEDUPLICATION)
                        if active_ev.event_type == confirmed_event_type:
                            active_ev.last_seen_frame = self.frame_index
                            active_ev.missed_frames = 0
                            active_ev.confidence = assoc_score
                            active_ev.status = EventState.ACTIVE
                            active_ev.evidence.update({
                                "consecutive_frames": ev_data.get("consecutive_frames", active_ev.evidence.get("consecutive_frames", 1) + 1),
                                "normalized_distance": ev_data.get("normalized_distance"),
                                "association_state": "CONFIRMED"
                            })
                            current_frame_events.append(active_ev)
                        else:
                            # Transition from NEAR candidate to CONFIRMED
                            active_ev.status = EventState.COMPLETED
                            # Create new confirmed event instance
                            new_event = MovementEvent(
                                event_id=self.generate_event_id(),
                                event_type=confirmed_event_type,
                                camera_id=self.camera_id,
                                timestamp=self.last_update_time,
                                primary_object=primary_desc,
                                secondary_object=secondary_desc,
                                zone=zone_meta,
                                evidence={
                                    "same_camera": ev_data.get("same_camera", True),
                                    "same_zone": ev_data.get("same_zone", True),
                                    "temporal_overlap": ev_data.get("temporal_overlap", True),
                                    "spatial_proximity": ev_data.get("spatial_proximity", True),
                                    "sustained_observation": True,
                                    "association_state": "CONFIRMED",
                                    "consecutive_frames": ev_data.get("consecutive_frames", 3),
                                    "normalized_distance": ev_data.get("normalized_distance")
                                },
                                confidence=assoc_score,
                                status=EventState.ACTIVE,
                                event_level=event_level,
                                created_frame=self.frame_index,
                                last_seen_frame=self.frame_index
                            )
                            self.active_events[pair_key] = new_event
                            self.event_history.append(new_event)
                            current_frame_events.append(new_event)
                    else:
                        # First time confirmed event instance
                        new_event = MovementEvent(
                            event_id=self.generate_event_id(),
                            event_type=confirmed_event_type,
                            camera_id=self.camera_id,
                            timestamp=self.last_update_time,
                            primary_object=primary_desc,
                            secondary_object=secondary_desc,
                            zone=zone_meta,
                            evidence={
                                "same_camera": ev_data.get("same_camera", True),
                                "same_zone": ev_data.get("same_zone", True),
                                "temporal_overlap": ev_data.get("temporal_overlap", True),
                                "spatial_proximity": ev_data.get("spatial_proximity", True),
                                "sustained_observation": True,
                                "association_state": "CONFIRMED",
                                "consecutive_frames": ev_data.get("consecutive_frames", 3),
                                "normalized_distance": ev_data.get("normalized_distance")
                            },
                            confidence=assoc_score,
                            status=EventState.ACTIVE,
                            event_level=event_level,
                            created_frame=self.frame_index,
                            last_seen_frame=self.frame_index
                        )
                        self.active_events[pair_key] = new_event
                        self.event_history.append(new_event)
                        current_frame_events.append(new_event)

                # Case B: CANDIDATE / AMBIGUOUS Observation Event
                elif status == "CANDIDATE" or is_ambiguous:
                    if pair_key in self.active_events:
                        active_ev = self.active_events[pair_key]
                        active_ev.last_seen_frame = self.frame_index
                        active_ev.missed_frames = 0
                        active_ev.confidence = assoc_score
                        # If previously confirmed but now ambiguous or candidate, revert status
                        active_ev.status = EventState.CANDIDATE
                        active_ev.evidence.update({
                            "is_ambiguous": is_ambiguous,
                            "competing_ids": ev_data.get("competing_truck_ids") or ev_data.get("competing_worker_ids") or ev_data.get("competing_bin_ids") or [],
                            "ambiguity_reason": ev_data.get("ambiguity_reason"),
                            "association_state": "CANDIDATE"
                        })
                        current_frame_events.append(active_ev)
                    else:
                        cand_event = MovementEvent(
                            event_id=self.generate_event_id(),
                            event_type=near_event_type,
                            camera_id=self.camera_id,
                            timestamp=self.last_update_time,
                            primary_object=primary_desc,
                            secondary_object=secondary_desc,
                            zone=zone_meta,
                            evidence={
                                "same_camera": ev_data.get("same_camera", True),
                                "same_zone": ev_data.get("same_zone", False),
                                "temporal_overlap": ev_data.get("temporal_overlap", True),
                                "spatial_proximity": ev_data.get("spatial_proximity", True),
                                "sustained_observation": False,
                                "association_state": "CANDIDATE",
                                "is_ambiguous": is_ambiguous,
                                "competing_ids": ev_data.get("competing_truck_ids") or ev_data.get("competing_worker_ids") or ev_data.get("competing_bin_ids") or [],
                                "ambiguity_reason": ev_data.get("ambiguity_reason"),
                                "normalized_distance": ev_data.get("normalized_distance")
                            },
                            confidence=assoc_score,
                            status=EventState.CANDIDATE,
                            event_level=event_level,
                            created_frame=self.frame_index,
                            last_seen_frame=self.frame_index
                        )
                        self.active_events[pair_key] = cand_event
                        self.event_history.append(cand_event)
                        current_frame_events.append(cand_event)

                # Case C: REJECTED Association Event
                elif status == "REJECTED":
                    if pair_key in self.active_events:
                        active_ev = self.active_events[pair_key]
                        active_ev.status = EventState.CANCELLED
                        active_ev.last_seen_frame = self.frame_index
                        del self.active_events[pair_key]

        # --------------------------------------------------------------------
        # STEP 3: TIMEOUT, EXPIRATION & DEPARTURE MANAGEMENT
        # --------------------------------------------------------------------
        for key, event in list(self.active_events.items()):
            if key not in seen_event_keys:
                if event.event_type == EventType.BOX_EXITED_ZONE:
                    event.status = EventState.COMPLETED
                    del self.active_events[key]
                else:
                    event.missed_frames += 1
                    if event.missed_frames >= self.config.event_timeout_frames:
                        # Timeout exceeded -> Transition to EXPIRED
                        event.status = EventState.EXPIRED
                        del self.active_events[key]

        # Cap history list to max configured size
        if len(self.event_history) > self.config.max_history_events:
            self.event_history = self.event_history[-self.config.max_history_events:]

        active_list = [e.to_dict() for e in self.active_events.values() if e.status == EventState.ACTIVE.value]
        cand_list = [e.to_dict() for e in self.active_events.values() if e.status == EventState.CANDIDATE.value]

        return {
            "camera_id": self.camera_id,
            "frame_index": self.frame_index,
            "timestamp": self.last_update_time,
            "active_events_count": len(active_list),
            "candidate_events_count": len(cand_list),
            "total_events_generated": self.event_counter,
            "current_events": [e.to_dict() for e in current_frame_events],
            "active_events": active_list,
            "candidate_events": cand_list,
            "all_events": [e.to_dict() for e in self.active_events.values()]
        }


# ============================================================================
# 4. GLOBAL MULTI-OBJECT MOVEMENT EVENT SERVICE
# ============================================================================
class MultiObjectMovementEventService:
    """
    High-level Part 12 Service coordinating upstream pipelines (Parts 5-11),
    Camera Movement Event Sessions, Synthetic Sequences, and Visual Annotations.
    """

    def __init__(self, config: Optional[MovementEventConfig] = None):
        self.config = config or MovementEventConfig()
        self.sessions: Dict[str, CameraMovementEventSession] = {}
        self._annotated_frames: Dict[str, np.ndarray] = {}

        # Upstream service references
        self.validation_service = get_validation_service()
        self.truck_box_service = get_association_service()
        self.worker_box_service = get_worker_box_association_service()
        self.box_bin_service = get_box_bin_association_service()

        logger.info("MultiObjectMovementEventService initialized successfully.")

    def get_session(self, camera_id: str = "CAM-001") -> CameraMovementEventSession:
        """Retrieve or lazily instantiate an isolated in-memory session for a camera."""
        if camera_id not in self.sessions:
            self.sessions[camera_id] = CameraMovementEventSession(camera_id, self.config)
        return self.sessions[camera_id]

    def reset_session(self, camera_id: str = "CAM-001") -> Dict[str, Any]:
        """Reset event state for a specific camera."""
        if camera_id in self.sessions:
            self.sessions[camera_id].reset()
        if camera_id in self._annotated_frames:
            del self._annotated_frames[camera_id]
        return {
            "success": True,
            "camera_id": camera_id,
            "message": f"Movement event session for '{camera_id}' reset successfully."
        }

    def reset_all(self) -> Dict[str, Any]:
        """Reset event state across all cameras."""
        for cam_id in list(self.sessions.keys()):
            self.reset_session(cam_id)
        return {
            "success": True,
            "message": "All movement event sessions reset successfully."
        }

    def reset(self, camera_id: Optional[str] = "CAM-001") -> Dict[str, Any]:
        """Reset event session for a specific camera or all cameras."""
        if camera_id and camera_id.upper() != "ALL":
            return self.reset_session(camera_id)
        return self.reset_all()

    def get_status(self) -> Dict[str, Any]:
        """Diagnostic operational status reporting."""
        active_cams = {
            cam_id: {
                "frame_index": sess.frame_index,
                "active_events": len(sess.active_events),
                "total_events": sess.event_counter,
                "last_update": sess.last_update_time
            }
            for cam_id, sess in self.sessions.items()
        }
        return {
            "status": "healthy",
            "service": "Warehouse Movement Event Detection Foundation (Part 12)",
            "config": self.config.to_dict(),
            "database_access": "ZERO-WRITES (Strictly In-Memory)",
            "active_camera_sessions": active_cams,
            "supported_event_types": [
                EventType.BOX_ENTERED_ZONE,
                EventType.BOX_EXITED_ZONE,
                EventType.BOX_NEAR_TRUCK,
                EventType.BOX_NEAR_WORKER,
                EventType.BOX_NEAR_BIN,
                EventType.BOX_ASSOCIATED_WITH_TRUCK,
                EventType.BOX_ASSOCIATED_WITH_WORKER,
                EventType.BOX_ASSOCIATED_WITH_BIN
            ]
        }

    def _load_camera_zones(self, camera_id: str) -> List[Dict[str, Any]]:
        """Load configured visual zones/ROIs from database (read-only)."""
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

    def process_events(
        self,
        tracks: List[Dict[str, Any]],
        truck_box_assocs: Optional[List[Dict[str, Any]]] = None,
        worker_box_assocs: Optional[List[Dict[str, Any]]] = None,
        box_bin_assocs: Optional[List[Dict[str, Any]]] = None,
        camera_id: str = "CAM-001",
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Dict[str, Any], float]:
        """
        Directly evaluate movement events on pre-extracted tracks and associations (for tests/synthetic feeds).
        Returns: (result_dict, latency_ms)
        """
        t_start = time.perf_counter()
        session = self.get_session(camera_id)
        if camera_zones is None:
            camera_zones = self._load_camera_zones(camera_id)

        res = session.update(
            tracks=tracks,
            truck_box_assocs=truck_box_assocs,
            worker_box_assocs=worker_box_assocs,
            box_bin_assocs=box_bin_assocs,
            camera_zones=camera_zones,
            frame_index=frame_index
        )
        latency_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        res["event_latency_ms"] = latency_ms
        return res, latency_ms

    def process_frame(
        self,
        frame_input: Any = None,
        camera_id: Any = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        tracks: Optional[List[Dict[str, Any]]] = None,
        associations: Optional[Dict[str, Any]] = None,
        truck_box_assocs: Optional[List[Dict[str, Any]]] = None,
        worker_box_assocs: Optional[List[Dict[str, Any]]] = None,
        box_bin_assocs: Optional[List[Dict[str, Any]]] = None,
        frame_index: Optional[int] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Flexible entry point handling both programmatic tracks input and raw camera frames.
        """
        # Case 1: Programmatic / Synthetic tracks passed directly
        if isinstance(frame_input, str) and (camera_id is None or isinstance(camera_id, list) or tracks is not None or associations is not None or frame_input.startswith("CAM-")):
            actual_cam = frame_input
            actual_tracks = camera_id if isinstance(camera_id, list) else (tracks or [])
            if not isinstance(actual_tracks, list):
                actual_tracks = []
            tb = truck_box_assocs
            wb = worker_box_assocs
            bb = box_bin_assocs
            if associations and isinstance(associations, dict):
                tb = associations.get("truck_associations") or associations.get("truck_box_assocs") or tb
                wb = associations.get("worker_associations") or associations.get("worker_box_assocs") or wb
                bb = associations.get("bin_associations") or associations.get("box_bin_assocs") or bb

            session = self.get_session(actual_cam)
            if camera_zones is None:
                camera_zones = self._load_camera_zones(actual_cam)

            return session.update(
                tracks=actual_tracks,
                truck_box_assocs=tb,
                worker_box_assocs=wb,
                box_bin_assocs=bb,
                camera_zones=camera_zones,
                frame_index=frame_index
            )

        # Case 2: Full End-to-End Pipeline on video frame / image
        actual_cam = str(camera_id) if not isinstance(camera_id, list) else "CAM-001"
        t_total_start = time.perf_counter()

        # Step 1: Upstream Parts 5-8
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
                "events": [],
                "performance": val_res.get("performance", {})
            }

        tracks = val_res.get("tracks", [])
        camera_zones = self._load_camera_zones(camera_id)

        # Step 2: Part 9 Truck <-> Box
        tb_assocs, tb_ms = self.truck_box_service.process_tracks(
            tracks=tracks,
            camera_id=camera_id,
            camera_zones=camera_zones
        )

        # Step 3: Part 10 Worker <-> Box
        wb_assocs, wb_ms = self.worker_box_service.process_tracks(
            tracks=tracks,
            camera_id=camera_id,
            camera_zones=camera_zones
        )

        # Step 4: Part 11 Box <-> Bin
        bb_assocs, bb_ms = self.box_bin_service.process_tracks(
            tracks=tracks,
            camera_id=camera_id,
            camera_zones=camera_zones
        )

        # Step 5: Part 12 Movement Event Detection
        t_event_start = time.perf_counter()
        session = self.get_session(camera_id)
        event_res = session.update(
            tracks=tracks,
            truck_box_assocs=tb_assocs,
            worker_box_assocs=wb_assocs,
            box_bin_assocs=bb_assocs,
            camera_zones=camera_zones
        )
        event_ms = round((time.perf_counter() - t_event_start) * 1000.0, 2)
        total_ms = round((time.perf_counter() - t_total_start) * 1000.0, 2)

        upstream_perf = val_res.get("performance", {})

        # Render visual annotation
        annotated_bgr = self.render_annotated_frame(
            frame_input=frame_input,
            tracks=tracks,
            events=event_res.get("active_events", []),
            camera_zones=camera_zones
        )
        self._annotated_frames[camera_id] = annotated_bgr

        # Encode base64 annotated frame
        annotated_b64 = None
        if annotated_bgr is not None:
            _, buf = cv2.imencode(".jpg", annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            import base64
            annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf).decode('utf-8')}"

        return {
            "success": True,
            "camera_id": camera_id,
            "frame_index": session.frame_index,
            "timestamp": event_res.get("timestamp"),
            "active_events_count": event_res.get("active_events_count", 0),
            "events": event_res.get("active_events", []),
            "current_frame_events": event_res.get("current_events", []),
            "annotated_frame": annotated_b64,
            "performance": {
                "detection_ms": upstream_perf.get("detection_ms", 0.0),
                "tracking_ms": upstream_perf.get("tracking_ms", 0.0),
                "identity_ms": upstream_perf.get("identity_ms", 0.0),
                "validation_ms": upstream_perf.get("validation_ms", 0.0),
                "association_ms": round(tb_ms + wb_ms + bb_ms, 2),
                "event_ms": event_ms,
                "total_ms": total_ms
            }
        }

    def run_sequence(
        self,
        camera_id: str = "CAM-001",
        num_frames: int = 5,
        sample_scene: str = "association_box_bin_dock1.jpg",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        synthetic_sequence: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Controlled Multi-Frame Sequence Test.
        Executes frame sequence to demonstrate state transitions, deduplication, and expiration.
        """
        history = []
        session = self.get_session(camera_id)

        if synthetic_sequence:
            camera_zones = self._load_camera_zones(camera_id)
            if roi_polygon and roi_zone_code:
                camera_zones.insert(0, {
                    "zone_code": roi_zone_code,
                    "zone_name": roi_zone_code,
                    "polygon": roi_polygon
                })

            for idx, frame_data in enumerate(synthetic_sequence, start=1):
                tracks = frame_data.get("tracks", [])
                tb = frame_data.get("truck_box_assocs", [])
                wb = frame_data.get("worker_box_assocs", [])
                bb = frame_data.get("box_bin_assocs", [])

                res, ev_ms = self.process_events(
                    tracks=tracks,
                    truck_box_assocs=tb,
                    worker_box_assocs=wb,
                    box_bin_assocs=bb,
                    camera_id=camera_id,
                    frame_index=idx,
                    camera_zones=camera_zones
                )
                step = {
                    "frame_index": idx,
                    "active_events_count": res.get("active_events_count", 0),
                    "active_events": res.get("active_events", []),
                    "current_frame_events": res.get("current_events", []),
                    "event_latency_ms": ev_ms
                }
                history.append(step)

            return {
                "success": True,
                "mode": "synthetic_sequence",
                "camera_id": camera_id,
                "total_frames": len(synthetic_sequence),
                "history": history,
                "final_events": history[-1]["active_events"] if history else []
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
                "active_events_count": res.get("active_events_count", 0),
                "events": res.get("events", []),
                "performance": res.get("performance", {})
            })

        return {
            "success": True,
            "mode": "sample_scene_sequence",
            "camera_id": camera_id,
            "total_frames": num_frames,
            "history": history,
            "final_events": history[-1]["events"] if history else [],
            "annotated_frame": res.get("annotated_frame")
        }

    def run_synthetic_sequence(
        self,
        camera_id: str = "CAM-001",
        sequence_name: str = "dock_loading"
    ) -> Dict[str, Any]:
        """
        Execute deterministic synthetic sequence per Section 21 specification.
        8 frames demonstrating:
          Frame 1: Box outside Dock 1.
          Frame 2: Box approaching Dock 1.
          Frame 3: Box enters Dock 1 (BOX_ENTERED_ZONE).
          Frame 4: Box remains inside Dock 1 (Deduplicated).
          Frame 5: Box associated with Truck T1 (BOX_ASSOCIATED_WITH_TRUCK).
          Frame 6: Box associated with Worker W1 (BOX_ASSOCIATED_WITH_WORKER).
          Frame 7: Box associated with Bin B1 (BOX_ASSOCIATED_WITH_BIN).
          Frame 8: Box exits Dock 1 (BOX_EXITED_ZONE).
        """
        self.reset_session(camera_id)
        session = self.get_session(camera_id)
        dock_zone = [{
            "id": 18,
            "zone_code": "DOCK-01",
            "zone_name": "Dock 01",
            "polygon": [{"x": 0.20, "y": 0.20}, {"x": 0.85, "y": 0.20}, {"x": 0.85, "y": 0.85}, {"x": 0.20, "y": 0.85}]
        }]

        frames_data = [
            # Frame 1: Box outside Dock 1
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.05, 0.05], "bbox": [0.02, 0.02, 0.08, 0.08], "identity_id": "B104", "validation_status": "VALIDATED"}
                ],
                "assocs": {}
            },
            # Frame 2: Box approaching Dock 1
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.15, 0.15], "bbox": [0.12, 0.12, 0.18, 0.18], "identity_id": "B104", "validation_status": "VALIDATED"}
                ],
                "assocs": {}
            },
            # Frame 3: Box enters Dock 1 -> BOX_ENTERED_ZONE
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.50, 0.50], "bbox": [0.46, 0.46, 0.54, 0.54], "identity_id": "B104", "validation_status": "VALIDATED"}
                ],
                "assocs": {}
            },
            # Frame 4: Box remains inside Dock 1 -> Deduplicated
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.52, 0.50], "bbox": [0.48, 0.46, 0.56, 0.54], "identity_id": "B104", "validation_status": "VALIDATED"}
                ],
                "assocs": {}
            },
            # Frame 5: Box associated with Truck T1 -> BOX_ASSOCIATED_WITH_TRUCK
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.55, 0.50], "bbox": [0.50, 0.46, 0.60, 0.54], "identity_id": "B104", "validation_status": "VALIDATED"},
                    {"track_id": 4, "class_code": "TRUCK", "center": [0.60, 0.50], "bbox": [0.40, 0.30, 0.80, 0.70], "identity_id": "GP-1000", "validation_status": "VALIDATED"}
                ],
                "assocs": {
                    "truck_associations": [{
                        "truck_track_id": 4, "box_track_id": 104, "association_state": "CONFIRMED",
                        "association_score": 0.92, "is_ambiguous": False
                    }]
                }
            },
            # Frame 6: Box associated with Worker W1 -> BOX_ASSOCIATED_WITH_WORKER
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.55, 0.50], "bbox": [0.50, 0.46, 0.60, 0.54], "identity_id": "B104", "validation_status": "VALIDATED"},
                    {"track_id": 5, "class_code": "WORKER", "center": [0.53, 0.48], "bbox": [0.49, 0.35, 0.57, 0.60], "identity_id": "W-RAJESH", "validation_status": "VALIDATED"}
                ],
                "assocs": {
                    "worker_associations": [{
                        "worker_track_id": 5, "box_track_id": 104, "association_state": "CONFIRMED",
                        "association_score": 0.89, "is_ambiguous": False
                    }]
                }
            },
            # Frame 7: Box associated with Bin B1 -> BOX_ASSOCIATED_WITH_BIN
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.55, 0.50], "bbox": [0.50, 0.46, 0.60, 0.54], "identity_id": "B104", "validation_status": "VALIDATED"},
                    {"track_id": 8, "class_code": "BIN", "center": [0.56, 0.52], "bbox": [0.48, 0.44, 0.64, 0.60], "identity_id": "BIN-A-01", "validation_status": "VALIDATED"}
                ],
                "assocs": {
                    "bin_associations": [{
                        "bin_track_id": 8, "box_track_id": 104, "association_state": "CONFIRMED",
                        "association_score": 0.95, "is_ambiguous": False
                    }]
                }
            },
            # Frame 8: Box exits Dock 1 -> BOX_EXITED_ZONE
            {
                "tracks": [
                    {"track_id": 104, "class_code": "BOX", "center": [0.95, 0.95], "bbox": [0.90, 0.90, 0.99, 0.99], "identity_id": "B104", "validation_status": "VALIDATED"}
                ],
                "assocs": {}
            }
        ]

        frame_results = []
        all_generated_event_types = set()

        for idx, fd in enumerate(frames_data, start=1):
            assocs = fd.get("assocs", {})
            tb = assocs.get("truck_associations", [])
            wb = assocs.get("worker_associations", [])
            bb = assocs.get("bin_associations", [])
            res = session.update(
                tracks=fd.get("tracks", []),
                truck_box_assocs=tb,
                worker_box_assocs=wb,
                box_bin_assocs=bb,
                camera_zones=dock_zone,
                frame_index=idx
            )
            for ev in res.get("current_events", []):
                all_generated_event_types.add(ev.get("event_type"))
            frame_results.append({
                "frame_index": idx,
                "active_events": res.get("active_events", []),
                "current_events": res.get("current_events", [])
            })

        return {
            "success": True,
            "sequence_name": sequence_name,
            "camera_id": camera_id,
            "total_frames": len(frames_data),
            "frame_results": frame_results,
            "summary": {
                "generated_event_types": list(all_generated_event_types),
                "total_events_generated": session.event_counter,
                "final_active_events": [e.to_dict() for e in session.active_events.values()]
            }
        }

    def render_annotated_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        tracks: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        camera_zones: List[Dict[str, Any]]
    ) -> Optional[np.ndarray]:
        """
        Draw visual overlay with object bounding boxes, identities, zones, and movement event badges.
        """
        if isinstance(frame_input, np.ndarray):
            annotated = frame_input.copy()
        elif isinstance(frame_input, (str, bytes)):
            frame_arr, err = self.validation_service.identity_service.detection_engine._parse_image(frame_input)
            if err or frame_arr is None:
                return None
            annotated = frame_arr.copy()
        else:
            return None

        h, w = annotated.shape[:2]

        # Draw Camera Zones (ROIs)
        for z in camera_zones:
            poly = z.get("polygon")
            if poly and len(poly) >= 3:
                pts = np.array([[int(p.get("x", 0) * w), int(p.get("y", 0) * h)] for p in poly], dtype=np.int32)
                cv2.polylines(annotated, [pts], isClosed=True, color=(180, 180, 60), thickness=2)
                zc = z.get("zone_code", "")
                if len(pts) > 0:
                    cv2.putText(annotated, f"ZONE: {zc}", (pts[0][0] + 5, pts[0][1] + 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 100), 1, cv2.LINE_AA)

        # Draw Object Bounding Boxes
        for t in tracks:
            bbox = t.get("bbox") or {}
            x1 = max(0, int(bbox.get("x1", 0)))
            y1 = max(0, int(bbox.get("y1", 0)))
            x2 = min(w, int(bbox.get("x2", 0)))
            y2 = min(h, int(bbox.get("y2", 0)))

            cls_code = str(t.get("class_code", "")).upper()
            t_id = t.get("track_id", 0)
            ident = t.get("identity") or {}
            val = t.get("validation") or {}
            disp = val.get("display_name") or ident.get("value") or f"{cls_code} #{t_id}"

            color = (200, 120, 0) if cls_code == "BOX" else (0, 160, 240) if cls_code == "TRUCK" else (0, 200, 100) if cls_code == "WORKER" else (220, 80, 160)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(annotated, f"{cls_code} #{t_id}: {disp}", (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1, cv2.LINE_AA)

        # Draw Event Header Banner & Badges
        banner_y = 24
        cv2.rectangle(annotated, (0, 0), (w, min(h, 30 + len(events) * 22)), (15, 23, 42), -1)
        cv2.putText(annotated, f"PART 12 MOVEMENT EVENTS [{len(events)} Active]", (10, banner_y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

        for ev in events[:6]:  # Show top 6 events
            ev_id = ev.get("event_id", "")
            ev_type = ev.get("event_type", "")
            ev_status = ev.get("status", "")
            ev_level = ev.get("event_level", "")

            status_color = (0, 220, 0) if ev_status == "ACTIVE" else (0, 200, 255) if ev_status == "CANDIDATE" else (180, 180, 180)
            label = f"{ev_id} | {ev_type} [{ev_status}] - {ev_level}"
            banner_y += 20
            cv2.putText(annotated, label, (10, banner_y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, status_color, 1, cv2.LINE_AA)

        return annotated

    def get_annotated_jpeg(self, camera_id: str = "CAM-001") -> Optional[bytes]:
        """Retrieve binary JPEG bytes of the cached annotated frame."""
        frame = self._annotated_frames.get(camera_id)
        if frame is None:
            return None
        success, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if success else None


# ============================================================================
# 5. GLOBAL SINGLETON SERVICE
# ============================================================================
_movement_event_service_instance: Optional[MultiObjectMovementEventService] = None


def get_movement_event_service() -> MultiObjectMovementEventService:
    """Return global singleton instance of MultiObjectMovementEventService."""
    global _movement_event_service_instance
    if _movement_event_service_instance is None:
        _movement_event_service_instance = MultiObjectMovementEventService()
    return _movement_event_service_instance
