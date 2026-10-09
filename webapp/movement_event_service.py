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
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Union, Set

import cv2
import numpy as np

# Upstream Service Singletons
from validation_service import get_validation_service
from association_service import get_association_service
from worker_box_association_service import get_worker_box_association_service
from box_bin_association_service import get_box_bin_association_service
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
    """Strictly constrained Part 10 & 12 Event Types."""
    # Legacy Box Zone Events (Preserved for 100% backward compatibility)
    BOX_ENTERED_ZONE = "BOX_ENTERED_ZONE"
    BOX_EXITED_ZONE = "BOX_EXITED_ZONE"

    # Legacy Box Association Observation Events
    BOX_NEAR_TRUCK = "BOX_NEAR_TRUCK"
    BOX_NEAR_WORKER = "BOX_NEAR_WORKER"
    BOX_NEAR_BIN = "BOX_NEAR_BIN"

    # Legacy Box Confirmed Association Events
    BOX_ASSOCIATED_WITH_TRUCK = "BOX_ASSOCIATED_WITH_TRUCK"
    BOX_ASSOCIATED_WITH_WORKER = "BOX_ASSOCIATED_WITH_WORKER"
    BOX_ASSOCIATED_WITH_BIN = "BOX_ASSOCIATED_WITH_BIN"

    # Legacy Box Derived Dock Evidence Event
    BOX_UNLOADED_AT_DOCK = "BOX_UNLOADED_AT_DOCK"

    # Material-Agnostic Movement Events (Part 10 Enhancement)
    MATERIAL_ENTERED_ZONE = "MATERIAL_ENTERED_ZONE"
    MATERIAL_EXITED_ZONE = "MATERIAL_EXITED_ZONE"

    # Material Proximity / Observation Events
    MATERIAL_NEAR_TRUCK = "MATERIAL_NEAR_TRUCK"
    MATERIAL_NEAR_WORKER = "MATERIAL_NEAR_WORKER"
    MATERIAL_NEAR_BIN = "MATERIAL_NEAR_BIN"
    MATERIAL_NEAR_CONTAINER = "MATERIAL_NEAR_CONTAINER"

    # Material Confirmed Association Events
    MATERIAL_ASSOCIATED_WITH_TRUCK = "MATERIAL_ASSOCIATED_WITH_TRUCK"
    MATERIAL_ASSOCIATED_WITH_WORKER = "MATERIAL_ASSOCIATED_WITH_WORKER"
    MATERIAL_ASSOCIATED_WITH_BIN = "MATERIAL_ASSOCIATED_WITH_BIN"
    MATERIAL_ASSOCIATED_WITH_CONTAINER = "MATERIAL_ASSOCIATED_WITH_CONTAINER"

    # Material Derived Dock Evidence Event
    MATERIAL_UNLOADED_AT_DOCK = "MATERIAL_UNLOADED_AT_DOCK"

    # Warehouse Stage Milestone Events
    MATERIAL_MOVED_TO_SORTING = "MATERIAL_MOVED_TO_SORTING"
    MATERIAL_ENTERED_STAGING = "MATERIAL_ENTERED_STAGING"
    MATERIAL_STORED_IN_BIN = "MATERIAL_STORED_IN_BIN"
    MATERIAL_DISPATCHED = "MATERIAL_DISPATCHED"


# Object classes eligible for movement & association tracking
BOX_CLASS_CODES = ("BOX", "CARTON", "PACKAGE", "CARDBOARD BOX")
CONTAINER_CLASS_CODES = ("CONTAINER", "PALLET", "TRAY", "CRATE")
AUTOMOTIVE_MATERIAL_CLASS_CODES = ("MATERIAL", "GLASS", "ROD", "PART", "COMPONENT", "FASTENER", "SKU")
ALL_MATERIAL_FAMILY_CODES = tuple(set(BOX_CLASS_CODES) | set(CONTAINER_CLASS_CODES) | set(AUTOMOTIVE_MATERIAL_CLASS_CODES))

TRUCK_CLASS_CODES = ("TRUCK", "CARRIER", "VEHICLE")
WORKER_CLASS_CODES = ("WORKER", "PERSON", "OPERATOR")
BIN_CLASS_CODES = ("BIN", "STORAGE_BIN", "TOTE", "BAY", "SLOT", "LOCATION", "STORAGE BIN / TOTE")

# Vision zone types (vision_zones.zone_type) for warehouse operational stages
DOCK_ZONE_TYPES = ("DOCK", "UNLOADING")
SORTING_ZONE_TYPES = ("SORTING", "SORT")
STAGING_ZONE_TYPES = ("STAGING", "STAGE", "STG")
STORAGE_ZONE_TYPES = ("STORAGE", "BIN", "RACK")
DISPATCH_ZONE_TYPES = ("DISPATCH", "OUTBOUND", "GATE")


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
    stage: Optional[str] = None       # DOCK, UNLOADING, SORTING, STAGING, STORAGE, DISPATCH
    created_frame: int = 1
    last_seen_frame: int = 1
    missed_frames: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if hasattr(self.event_type, 'value') else self.event_type,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "primary_object": self.primary_object,
            "secondary_object": self.secondary_object,
            "zone": self.zone,
            "evidence": self.evidence,
            "confidence": round(float(self.confidence), 4),
            "status": self.status.value if hasattr(self.status, 'value') else self.status,
            "event_level": self.event_level,
            "stage": self.stage,
            "blocking_reasons": self.evidence.get("blocking_reasons", []),
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
        #   Stage: ("STAGE", stage_event_type, mat_track_id, zone_code)
        #   Unload: ("UNLOAD", mat_track_id, truck_track_id, zone_code)
        self.active_events: Dict[Tuple, MovementEvent] = {}

        # Chronological event history (contains all generated events: CANDIDATE, ACTIVE, COMPLETED, EXPIRED, CANCELLED)
        self.event_history: List[MovementEvent] = []

        # Previous zone tracking per material/box: mat_track_id -> Optional[str]
        self.box_zone_history: Dict[int, Optional[str]] = {}

        # Current zone metadata per material/box (includes zone_type, used for dock-unloading evidence)
        self.box_zone_meta: Dict[int, Optional[Dict[str, Any]]] = {}

        # Material-specific dwell persistence: mat_track_id -> consecutive frames resident in current zone
        self.material_dwell_frames: Dict[int, int] = {}

        # Active custody tracking per material track ID: mat_track_id -> {entity_type: active_pair_key}
        self.material_active_custody: Dict[int, Dict[str, Tuple]] = {}

        # Last seen frame per track for bounded cleanup: track_id -> frame_index
        self.last_seen_track_frame: Dict[int, int] = {}

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
        self.box_zone_meta.clear()
        self.material_dwell_frames.clear()
        self.material_active_custody.clear()
        self.last_seen_track_frame.clear()
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
                        "zone_id": cz.get("zone_id") or cz.get("id"),
                        "zone_code": cz.get("zone_code"),
                        "zone_name": cz.get("zone_name", cz.get("zone_code")),
                        "zone_type": cz.get("zone_type")
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
                # Runtime ROIs (db.get_camera_rois) carry 'coordinates'; synthetic zones carry 'polygon'
                poly = cz.get("polygon") or cz.get("coordinates")
                if poly and len(poly) >= 3:
                    if is_point_in_polygon(center_dict, poly):
                        return cz.get("zone_code"), {
                            "zone_id": cz.get("zone_id") or cz.get("id"),
                            "zone_code": cz.get("zone_code"),
                            "zone_name": cz.get("zone_name", cz.get("zone_code")),
                            "zone_type": cz.get("zone_type")
                        }

        return None, None

    # ------------------------------------------------------------------------
    # PART 10: WAREHOUSE STAGE & DOCK-UNLOADING EVIDENCE HELPERS
    # ------------------------------------------------------------------------
    @staticmethod
    def _classify_warehouse_stage(zone_code: Optional[str], zone_meta: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Classifies a zone into standard warehouse operational movement stages:
        DOCK, UNLOADING, SORTING, STAGING, STORAGE, DISPATCH.
        """
        if not zone_code and not zone_meta:
            return None
        z_type = str((zone_meta or {}).get("zone_type") or "").upper()
        z_code = str(zone_code or "").upper()

        if z_type in DOCK_ZONE_TYPES or any(z_code.startswith(p) for p in ("DOCK", "UNLOAD")):
            return "UNLOADING" if "UNLOAD" in (z_type or z_code) else "DOCK"
        if z_type in SORTING_ZONE_TYPES or any(z_code.startswith(p) for p in ("SORT", "SRT")):
            return "SORTING"
        if z_type in STAGING_ZONE_TYPES or any(z_code.startswith(p) for p in ("STAG", "STG")):
            return "STAGING"
        if z_type in STORAGE_ZONE_TYPES or any(z_code.startswith(p) for p in ("BIN", "STOR", "RCK", "RACK")):
            return "STORAGE"
        if z_type in DISPATCH_ZONE_TYPES or any(z_code.startswith(p) for p in ("DISP", "OUTBOUND", "GATE_OUT")):
            return "DISPATCH"
        return z_type or "ZONE"

    @staticmethod
    def _is_dock_zone(zone_code: Optional[str], zone_meta: Optional[Dict[str, Any]]) -> bool:
        """
        A zone is a dock/unloading zone when its configured vision_zones.zone_type is DOCK or UNLOADING.
        If zone_type is unknown, falls back to zone-code convention (DOCK-xx / UNLOAD-xx).
        """
        if not zone_code:
            return False
        z_type = str((zone_meta or {}).get("zone_type") or "").upper()
        if z_type:
            return z_type in DOCK_ZONE_TYPES
        code = str(zone_code).upper()
        return code.startswith("DOCK") or code.startswith("UNLOAD")

    @staticmethod
    def _validation_of(track: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract Part 8 validation (status, master_id, master_type) from a validated track."""
        val = track.get("validation") or {}
        status = track.get("validation_status") or val.get("status")
        master_id = val.get("master_id") or track.get("validated_master_id")
        master_type = val.get("master_type") or track.get("validated_master_type")
        return status, master_id, master_type

    def _finalize_unloading_events(self, mat_id: int, zone_code: Optional[str], reason: str) -> None:
        """
        Conclude dock-unloading evidence for a material/box leaving the dock zone.
        ACTIVE (sustained) -> COMPLETED. CANDIDATE (never sustained) -> CANCELLED.
        """
        for key, ev in list(self.active_events.items()):
            if key[0] == "UNLOAD" and key[1] == mat_id and key[3] == zone_code:
                if ev.status == EventState.ACTIVE:
                    ev.status = EventState.COMPLETED
                    ev.evidence["conclusion_reason"] = reason
                else:
                    ev.status = EventState.CANCELLED
                    ev.evidence["conclusion_reason"] = f"{reason}_BEFORE_SUSTAINED_EVIDENCE"
                ev.last_seen_frame = self.frame_index
                del self.active_events[key]

    def _finalize_stage_events(self, mat_id: int, zone_code: Optional[str], reason: str) -> None:
        """
        Conclude active warehouse stage milestone events for a material leaving a zone.
        """
        for key, ev in list(self.active_events.items()):
            if key[0] == "STAGE" and key[2] == mat_id and key[3] == zone_code:
                if ev.status == EventState.ACTIVE:
                    ev.status = EventState.COMPLETED
                    ev.evidence["conclusion_reason"] = reason
                else:
                    ev.status = EventState.CANCELLED
                    ev.evidence["conclusion_reason"] = f"{reason}_BEFORE_CONFIRMATION"
                ev.last_seen_frame = self.frame_index
                del self.active_events[key]

    def get_unloading_events(self) -> List[Dict[str, Any]]:
        """All dock unloading events for this camera (any lifecycle state), chronological."""
        return [e.to_dict() for e in self.event_history if e.event_type in (EventType.BOX_UNLOADED_AT_DOCK, EventType.MATERIAL_UNLOADED_AT_DOCK)]

    def update(
        self,
        tracks: List[Dict[str, Any]],
        truck_box_assocs: Optional[List[Dict[str, Any]]] = None,
        worker_box_assocs: Optional[List[Dict[str, Any]]] = None,
        box_bin_assocs: Optional[List[Dict[str, Any]]] = None,
        material_assocs: Optional[List[Dict[str, Any]]] = None,
        camera_zones: Optional[List[Dict[str, Any]]] = None,
        frame_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process a single video frame / tracking step and evaluate movement events.
        Produces explainable events, deduplicates ongoing states, and handles timeout/expiration.
        Supports material-agnostic movement (GLASS, ROD, PART, FASTENER, BOX, CONTAINER, PALLET).
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
        material_assocs = material_assocs or []

        current_frame_events: List[MovementEvent] = []
        seen_event_keys = set()

        # Separate materials from tracks
        materials: List[Dict[str, Any]] = []
        all_tracks_by_id: Dict[int, Dict[str, Any]] = {}
        for t in tracks:
            t_id = int(t.get("track_id", 0))
            all_tracks_by_id[t_id] = t
            self.last_seen_track_frame[t_id] = self.frame_index
            cls_code = str(t.get("class_code", "")).upper()
            if cls_code in ALL_MATERIAL_FAMILY_CODES:
                materials.append(t)

        current_mat_ids = {int(m.get("track_id", 0)) for m in materials}

        # --------------------------------------------------------------------
        # STEP 1: ZONE TRANSITIONS & WAREHOUSE STAGE MILESTONES
        # --------------------------------------------------------------------
        for mat in materials:
            mat_id = int(mat.get("track_id", 0))
            cls_code = str(mat.get("class_code", "BOX")).upper()
            is_legacy_box = cls_code in BOX_CLASS_CODES

            current_zone_code, zone_meta = self._resolve_zone_for_track(mat, camera_zones)
            prev_zone_code = self.box_zone_history.get(mat_id)
            current_stage = self._classify_warehouse_stage(current_zone_code, zone_meta)

            primary_desc = self._format_object_desc(mat, cls_code)

            # Check for Zone Transition
            if current_zone_code != prev_zone_code:
                # 1. Exit Event for previous zone if material was inside one
                if prev_zone_code is not None:
                    exit_key = ("ZONE_EXIT", mat_id, prev_zone_code, self.frame_index)
                    seen_event_keys.add(exit_key)

                    # Conclude dock-unloading and stage evidence for leaving zone
                    self._finalize_unloading_events(mat_id, prev_zone_code, f"{cls_code}_EXITED_DOCK_ZONE")
                    self._finalize_stage_events(mat_id, prev_zone_code, f"{cls_code}_EXITED_STAGE_ZONE")

                    # Mark prior active enter event as COMPLETED
                    enter_key = ("ZONE_ENTER", mat_id, prev_zone_code)
                    if enter_key in self.active_events:
                        prior_enter = self.active_events[enter_key]
                        prior_enter.status = EventState.COMPLETED
                        prior_enter.last_seen_frame = self.frame_index
                        del self.active_events[enter_key]

                    # Generate exit event
                    exit_evt_type = EventType.BOX_EXITED_ZONE if is_legacy_box else EventType.MATERIAL_EXITED_ZONE
                    exit_event = MovementEvent(
                        event_id=self.generate_event_id(),
                        event_type=exit_evt_type,
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

                # 2. Enter Event for current zone if material is now inside one
                if current_zone_code is not None:
                    enter_key = ("ZONE_ENTER", mat_id, current_zone_code)
                    seen_event_keys.add(enter_key)
                    self.material_dwell_frames[mat_id] = 1

                    enter_evt_type = EventType.BOX_ENTERED_ZONE if is_legacy_box else EventType.MATERIAL_ENTERED_ZONE
                    # Legacy BOX events start ACTIVE for backward compatibility
                    # Enhanced generic materials: require dwell persistence (>= min_consecutive_frames) for confirmed ACTIVE, else CANDIDATE
                    dwell = self.material_dwell_frames[mat_id]
                    is_sustained = dwell >= self.config.min_consecutive_frames
                    enter_status = EventState.ACTIVE if is_legacy_box else (EventState.ACTIVE if is_sustained else EventState.CANDIDATE)

                    blocking = []
                    if not is_legacy_box and not is_sustained:
                        blocking.append(f"INSUFFICIENT_ZONE_PERSISTENCE_{dwell}_OF_{self.config.min_consecutive_frames}")

                    enter_event = MovementEvent(
                        event_id=self.generate_event_id(),
                        event_type=enter_evt_type,
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
                            "consecutive_frames": dwell,
                            "blocking_reasons": blocking
                        },
                        confidence=1.0 if (is_legacy_box or is_sustained) else 0.5,
                        status=enter_status,
                        event_level=self._determine_event_level(primary_desc),
                        stage=current_stage,
                        created_frame=self.frame_index,
                        last_seen_frame=self.frame_index
                    )
                    self.active_events[enter_key] = enter_event
                    self.event_history.append(enter_event)
                    current_frame_events.append(enter_event)

                # Update zone history
                self.box_zone_history[mat_id] = current_zone_code
                self.box_zone_meta[mat_id] = zone_meta

            else:
                # Material remained in the same zone (Deduplication Check)
                if current_zone_code is not None:
                    enter_key = ("ZONE_ENTER", mat_id, current_zone_code)
                    seen_event_keys.add(enter_key)
                    dwell = self.material_dwell_frames.get(mat_id, 0) + 1
                    self.material_dwell_frames[mat_id] = dwell
                    is_sustained = dwell >= self.config.min_consecutive_frames

                    if enter_key in self.active_events:
                        # Existing active event: update in-place without generating a duplicate
                        active_ev = self.active_events[enter_key]
                        active_ev.last_seen_frame = self.frame_index
                        active_ev.missed_frames = 0
                        active_ev.evidence["consecutive_frames"] = dwell
                        if active_ev.status == EventState.CANDIDATE and is_sustained:
                            active_ev.status = EventState.ACTIVE
                            active_ev.confidence = 1.0
                            active_ev.evidence.pop("blocking_reasons", None)
                        current_frame_events.append(active_ev)
                    else:
                        enter_evt_type = EventType.BOX_ENTERED_ZONE if is_legacy_box else EventType.MATERIAL_ENTERED_ZONE
                        enter_status = EventState.ACTIVE if is_legacy_box else (EventState.ACTIVE if is_sustained else EventState.CANDIDATE)
                        blocking = []
                        if not is_legacy_box and not is_sustained:
                            blocking.append(f"INSUFFICIENT_ZONE_PERSISTENCE_{dwell}_OF_{self.config.min_consecutive_frames}")

                        enter_event = MovementEvent(
                            event_id=self.generate_event_id(),
                            event_type=enter_evt_type,
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
                                "consecutive_frames": dwell,
                                "blocking_reasons": blocking
                            },
                            confidence=1.0 if (is_legacy_box or is_sustained) else 0.5,
                            status=enter_status,
                            event_level=self._determine_event_level(primary_desc),
                            stage=current_stage,
                            created_frame=self.frame_index,
                            last_seen_frame=self.frame_index
                        )
                        self.active_events[enter_key] = enter_event
                        self.event_history.append(enter_event)
                        current_frame_events.append(enter_event)

            # Warehouse Stage Milestone Events (SORTING, STAGING, STORAGE, DISPATCH)
            if current_zone_code is not None and current_stage in ("SORTING", "STAGING", "STORAGE", "DISPATCH"):
                stage_event_type = None
                if current_stage == "SORTING":
                    stage_event_type = EventType.MATERIAL_MOVED_TO_SORTING
                elif current_stage == "STAGING":
                    stage_event_type = EventType.MATERIAL_ENTERED_STAGING
                elif current_stage == "STORAGE":
                    stage_event_type = EventType.MATERIAL_STORED_IN_BIN
                elif current_stage == "DISPATCH":
                    stage_event_type = EventType.MATERIAL_DISPATCHED

                if stage_event_type is not None:
                    stage_key = ("STAGE", stage_event_type, mat_id, current_zone_code)
                    seen_event_keys.add(stage_key)
                    dwell = self.material_dwell_frames.get(mat_id, 1)
                    min_frames = self.config.min_consecutive_frames
                    is_sustained = dwell >= min_frames

                    blocking = []
                    if not is_sustained:
                        blocking.append(f"INSUFFICIENT_PERSISTENCE_FRAMES_{dwell}_OF_{min_frames}")

                    stage_status = EventState.ACTIVE if is_sustained else EventState.CANDIDATE
                    stage_ev_data = {
                        "warehouse_stage": current_stage,
                        "zone_code": current_zone_code,
                        "zone_type": (zone_meta or {}).get("zone_type"),
                        "consecutive_dwell_frames": dwell,
                        "required_frames": min_frames,
                        "sustained_evidence": is_sustained,
                        "blocking_reasons": blocking
                    }

                    if stage_key in self.active_events:
                        sev = self.active_events[stage_key]
                        sev.last_seen_frame = self.frame_index
                        sev.status = stage_status
                        sev.confidence = 1.0 if is_sustained else 0.5
                        sev.evidence.update(stage_ev_data)
                        current_frame_events.append(sev)
                    else:
                        sev = MovementEvent(
                            event_id=self.generate_event_id(),
                            event_type=stage_event_type,
                            camera_id=self.camera_id,
                            timestamp=self.last_update_time,
                            primary_object=primary_desc,
                            secondary_object=None,
                            zone=zone_meta or {"zone_code": current_zone_code, "zone_name": current_zone_code},
                            evidence=stage_ev_data,
                            confidence=1.0 if is_sustained else 0.5,
                            status=stage_status,
                            event_level=self._determine_event_level(primary_desc),
                            stage=current_stage,
                            created_frame=self.frame_index,
                            last_seen_frame=self.frame_index
                        )
                        self.active_events[stage_key] = sev
                        self.event_history.append(sev)
                        current_frame_events.append(sev)

        # --------------------------------------------------------------------
        # STEP 2: ASSOCIATION EVENTS (TRUCK, WORKER, BIN, CONTAINER)
        # --------------------------------------------------------------------
        # Consolidate Part 9 material associations into association sets
        unified_truck_assocs = list(truck_box_assocs)
        unified_worker_assocs = list(worker_box_assocs)
        unified_bin_assocs = list(box_bin_assocs)
        unified_container_assocs = []

        flat_material_assocs = []
        if isinstance(material_assocs, dict):
            for k, v in material_assocs.items():
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            it = dict(item)
                            if "association_type" not in it:
                                if "truck" in k.lower():
                                    it["association_type"] = "TRUCK_MATERIAL"
                                elif "worker" in k.lower():
                                    it["association_type"] = "WORKER_MATERIAL"
                                elif "bin" in k.lower():
                                    it["association_type"] = "MATERIAL_BIN"
                                elif "container" in k.lower():
                                    it["association_type"] = "MATERIAL_CONTAINER"
                            flat_material_assocs.append(it)
                elif isinstance(v, dict):
                    flat_material_assocs.append(dict(v))
        elif isinstance(material_assocs, list):
            flat_material_assocs = [m for m in material_assocs if isinstance(m, dict)]

        for ma in flat_material_assocs:
            a_type = str(ma.get("association_type", "")).upper()
            p_id = int(ma.get("primary_track_id") or ma.get("truck_track_id") or ma.get("worker_track_id") or ma.get("bin_track_id") or ma.get("container_track_id") or 0)
            s_id = int(ma.get("secondary_track_id") or ma.get("material_track_id") or ma.get("box_track_id") or 0)
            p_cls = str(ma.get("primary_class", "")).upper()
            s_cls = str(ma.get("secondary_class", "")).upper()
            status_val = str(ma.get("status") or ma.get("association_state", "")).upper()

            if a_type in ("TRUCK_MATERIAL", "TRUCK_CONTAINER") or "TRUCK" in a_type:
                t_id = p_id if p_cls in TRUCK_CLASS_CODES or ma.get("truck_track_id") else s_id
                m_id = s_id if p_cls in TRUCK_CLASS_CODES or ma.get("truck_track_id") else p_id
                unified_truck_assocs.append({
                    "truck_track_id": t_id,
                    "box_track_id": m_id,
                    "association_state": status_val,
                    "association_score": ma.get("association_score", 0.0),
                    "is_ambiguous": (ma.get("evidence") or {}).get("is_ambiguous", ma.get("is_ambiguous", False)),
                    "evidence": ma.get("evidence") or {},
                    "material_track_id": m_id
                })
            elif a_type == "WORKER_MATERIAL" or "WORKER" in a_type:
                w_id = p_id if p_cls in WORKER_CLASS_CODES or ma.get("worker_track_id") else s_id
                m_id = s_id if p_cls in WORKER_CLASS_CODES or ma.get("worker_track_id") else p_id
                unified_worker_assocs.append({
                    "worker_track_id": w_id,
                    "box_track_id": m_id,
                    "association_state": status_val,
                    "association_score": ma.get("association_score", 0.0),
                    "is_ambiguous": (ma.get("evidence") or {}).get("is_ambiguous", ma.get("is_ambiguous", False)),
                    "evidence": ma.get("evidence") or {},
                    "material_track_id": m_id
                })
            elif a_type == "MATERIAL_BIN" or "BIN" in a_type:
                b_id = s_id if s_cls in BIN_CLASS_CODES or ma.get("bin_track_id") else p_id
                m_id = p_id if s_cls in BIN_CLASS_CODES or ma.get("bin_track_id") else s_id
                unified_bin_assocs.append({
                    "bin_track_id": b_id,
                    "box_track_id": m_id,
                    "association_state": status_val,
                    "association_score": ma.get("association_score", 0.0),
                    "is_ambiguous": (ma.get("evidence") or {}).get("is_ambiguous", ma.get("is_ambiguous", False)),
                    "evidence": ma.get("evidence") or {},
                    "material_track_id": m_id
                })
            elif a_type == "MATERIAL_CONTAINER" or "CONTAINER" in a_type:
                c_id = p_id if p_cls in CONTAINER_CLASS_CODES or ma.get("container_track_id") else s_id
                m_id = s_id if p_cls in CONTAINER_CLASS_CODES or ma.get("container_track_id") else p_id
                unified_container_assocs.append({
                    "container_track_id": c_id,
                    "box_track_id": m_id,
                    "association_state": status_val,
                    "association_score": ma.get("association_score", 0.0),
                    "is_ambiguous": (ma.get("evidence") or {}).get("is_ambiguous", ma.get("is_ambiguous", False)),
                    "evidence": ma.get("evidence") or {},
                    "material_track_id": m_id
                })

        association_sets = [
            ("TRUCK", unified_truck_assocs, "truck_track_id"),
            ("WORKER", unified_worker_assocs, "worker_track_id"),
            ("BIN", unified_bin_assocs, "bin_track_id"),
            ("CONTAINER", unified_container_assocs, "container_track_id")
        ]

        current_frame_assoc_keys = set()
        for a_type, a_list, oid_key in association_sets:
            for a in a_list:
                m_id = int(a.get("box_track_id") or a.get("material_track_id", 0))
                o_id = int(a.get(oid_key, 0))
                current_frame_assoc_keys.add(("ASSOC", a_type, m_id, o_id))

        for assoc_type, assocs_list, other_id_key in association_sets:
            for assoc in assocs_list:
                mat_id = int(assoc.get("box_track_id") or assoc.get("material_track_id", 0))
                other_id = int(assoc.get(other_id_key, 0))
                status = str(assoc.get("status") or assoc.get("association_state", "")).upper()
                assoc_score = float(assoc.get("association_score", 0.0))
                ev_data = assoc.get("evidence") or {}
                is_ambiguous = bool(assoc.get("is_ambiguous", False) or ev_data.get("is_ambiguous", False))

                # Retrieve raw track metadata or build from association dict
                mat_track = all_tracks_by_id.get(mat_id) or {
                    "track_id": mat_id,
                    "class_code": "MATERIAL",
                    "identity": assoc.get("box_identity") or assoc.get("material_identity") or {}
                }
                other_track = all_tracks_by_id.get(other_id) or {
                    "track_id": other_id,
                    "class_code": assoc_type,
                    "identity": assoc.get(f"{assoc_type.lower()}_identity") or {}
                }

                mat_cls = str(mat_track.get("class_code", "BOX")).upper()
                is_box = mat_cls in BOX_CLASS_CODES

                # Determine Event Types (preserve BOX_* when material is a box)
                if assoc_type == "TRUCK":
                    near_event_type = EventType.BOX_NEAR_TRUCK if is_box else EventType.MATERIAL_NEAR_TRUCK
                    confirmed_event_type = EventType.BOX_ASSOCIATED_WITH_TRUCK if is_box else EventType.MATERIAL_ASSOCIATED_WITH_TRUCK
                elif assoc_type == "WORKER":
                    near_event_type = EventType.BOX_NEAR_WORKER if is_box else EventType.MATERIAL_NEAR_WORKER
                    confirmed_event_type = EventType.BOX_ASSOCIATED_WITH_WORKER if is_box else EventType.MATERIAL_ASSOCIATED_WITH_WORKER
                elif assoc_type == "BIN":
                    near_event_type = EventType.BOX_NEAR_BIN if is_box else EventType.MATERIAL_NEAR_BIN
                    confirmed_event_type = EventType.BOX_ASSOCIATED_WITH_BIN if is_box else EventType.MATERIAL_ASSOCIATED_WITH_BIN
                elif assoc_type == "CONTAINER":
                    near_event_type = EventType.MATERIAL_NEAR_CONTAINER
                    confirmed_event_type = EventType.MATERIAL_ASSOCIATED_WITH_CONTAINER
                else:
                    continue

                primary_desc = self._format_object_desc(mat_track, mat_cls)
                secondary_desc = self._format_object_desc(other_track, assoc_type)
                event_level = self._determine_event_level(primary_desc, secondary_desc)

                zone_code = ev_data.get("box_zone") or ev_data.get("zone")
                zone_meta = {"zone_code": zone_code, "zone_name": zone_code} if zone_code else None

                pair_key = ("ASSOC", assoc_type, mat_id, other_id)
                seen_event_keys.add(pair_key)

                # Case A: CONFIRMED Association Event
                if status == "CONFIRMED" and not is_ambiguous:
                    # Custody Handoff (Requirement 12): Material custody transfers to new entity when prior entity is absent
                    if mat_id not in self.material_active_custody:
                        self.material_active_custody[mat_id] = {}

                    for prior_type, prior_key in list(self.material_active_custody[mat_id].items()):
                        if prior_type != assoc_type and prior_key in self.active_events:
                            if prior_key not in current_frame_assoc_keys:
                                prior_ev = self.active_events[prior_key]
                                if prior_ev.status == EventState.ACTIVE:
                                    prior_ev.status = EventState.COMPLETED
                                    prior_ev.evidence["conclusion_reason"] = f"CUSTODY_HANDOFF_TO_{assoc_type}"
                                    prior_ev.evidence["handoff_to_track_id"] = other_id
                                    prior_ev.evidence["handoff_to_type"] = assoc_type
                                    prior_ev.last_seen_frame = self.frame_index
                                    del self.active_events[prior_key]
                                    del self.material_active_custody[mat_id][prior_type]

                    self.material_active_custody[mat_id][assoc_type] = pair_key

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
        # STEP 2b: DERIVED DOCK-UNLOADING EVIDENCE (BOX / MATERIAL)
        # --------------------------------------------------------------------
        min_frames = self.config.min_consecutive_frames
        for assoc in unified_truck_assocs:
            mat_id = int(assoc.get("box_track_id") or assoc.get("material_track_id", 0))
            truck_id = int(assoc.get("truck_track_id", 0))
            mat_track = all_tracks_by_id.get(mat_id)
            truck_track = all_tracks_by_id.get(truck_id)

            if not mat_track or not truck_track:
                continue

            mat_cls = str(mat_track.get("class_code", "")).upper()
            if mat_cls not in ALL_MATERIAL_FAMILY_CODES:
                continue
            if str(truck_track.get("class_code", "")).upper() not in TRUCK_CLASS_CODES:
                continue

            zone_code = self.box_zone_history.get(mat_id)
            zone_meta = self.box_zone_meta.get(mat_id)
            if not self._is_dock_zone(zone_code, zone_meta):
                continue

            is_legacy_box = mat_cls in BOX_CLASS_CODES
            unload_event_type = EventType.BOX_UNLOADED_AT_DOCK if is_legacy_box else EventType.MATERIAL_UNLOADED_AT_DOCK

            a_status = str(assoc.get("status") or assoc.get("association_state", "")).upper()
            a_ev = assoc.get("evidence") or {}
            a_ambiguous = bool(assoc.get("is_ambiguous", False) or a_ev.get("is_ambiguous", False))
            a_score = float(assoc.get("association_score", 0.0))
            unload_key = ("UNLOAD", mat_id, truck_id, zone_code)

            if a_status == "REJECTED":
                if unload_key in self.active_events:
                    rej = self.active_events.pop(unload_key)
                    rej.status = EventState.CANCELLED
                    rej.last_seen_frame = self.frame_index
                    rej.evidence["conclusion_reason"] = "TRUCK_MATERIAL_ASSOCIATION_REJECTED"
                continue
            if a_status not in ("CONFIRMED", "CANDIDATE") and not a_ambiguous:
                continue

            has_identity = bool(
                mat_track.get("identity_id") or mat_track.get("identity") or mat_track.get("validation_status") or
                truck_track.get("identity_id") or truck_track.get("identity") or truck_track.get("validation_status")
            )
            if a_status != "CONFIRMED" and not a_ambiguous and not has_identity:
                continue

            seen_event_keys.add(unload_key)

            zone_ev = self.active_events.get(("ZONE_ENTER", mat_id, zone_code))
            dock_dwell = int(zone_ev.evidence.get("consecutive_frames", 1)) if zone_ev else self.material_dwell_frames.get(mat_id, 0)
            assoc_ev = self.active_events.get(("ASSOC", "TRUCK", mat_id, truck_id))
            assoc_frames = a_ev.get("consecutive_frames")
            if assoc_frames is None and assoc_ev is not None:
                assoc_frames = self.frame_index - assoc_ev.created_frame + 1

            mat_vs, mat_mid, _ = self._validation_of(mat_track)
            trk_vs, trk_mid, trk_mtype = self._validation_of(truck_track)
            primary_desc = self._format_object_desc(mat_track, mat_cls)
            secondary_desc = self._format_object_desc(truck_track, "TRUCK")
            mat_vs = mat_vs or primary_desc.get("validation_status")
            trk_vs = trk_vs or secondary_desc.get("validation_status")

            blocking = []
            if a_status != "CONFIRMED":
                blocking.append("TRUCK_MATERIAL_ASSOCIATION_NOT_CONFIRMED")
            if a_ambiguous:
                blocking.append("TRUCK_MATERIAL_ASSOCIATION_AMBIGUOUS")
            if dock_dwell < min_frames:
                blocking.append("INSUFFICIENT_DOCK_ZONE_PERSISTENCE")
            if mat_vs != "VALIDATED":
                blocking.append(f"MATERIAL_IDENTITY_{(mat_vs or 'UNVALIDATED').upper()}")
            if trk_vs != "VALIDATED":
                blocking.append(f"TRUCK_IDENTITY_{(trk_vs or 'UNVALIDATED').upper()}")

            sustained = len(blocking) == 0
            new_state = EventState.ACTIVE if sustained else EventState.CANDIDATE
            unload_evidence = {
                "derived_from": ["ZONE_ENTER", "TRUCK_ASSOCIATION"],
                "zone_event_id": zone_ev.event_id if zone_ev else None,
                "association_event_id": assoc_ev.event_id if assoc_ev else None,
                "dock_zone_code": zone_code,
                "dock_zone_type": (zone_meta or {}).get("zone_type"),
                "association_state": a_status,
                "association_score": round(a_score, 4),
                "is_ambiguous": a_ambiguous,
                "competing_ids": a_ev.get("competing_truck_ids") or [],
                "association_consecutive_frames": assoc_frames,
                "dock_zone_dwell_frames": dock_dwell,
                "required_persistence_frames": min_frames,
                "material_validation_status": mat_vs,
                "material_master_id": mat_mid,
                "truck_validation_status": trk_vs,
                "truck_master_id": trk_mid,
                "truck_master_type": trk_mtype,
                "truck_identity": secondary_desc.get("identity_id"),
                "sustained_evidence": sustained,
                "blocking_reasons": blocking,
                "wms_transaction": "NONE",
                "governance_note": "Perception evidence only. Does not alter inventory, SKU, PO or Gate Pass records."
            }

            if unload_key in self.active_events:
                u_ev = self.active_events[unload_key]
                u_ev.status = new_state
                u_ev.confidence = a_score
                u_ev.last_seen_frame = self.frame_index
                u_ev.missed_frames = 0
                u_ev.primary_object = primary_desc
                u_ev.secondary_object = secondary_desc
                u_ev.event_level = self._determine_event_level(primary_desc, secondary_desc)
                u_ev.evidence.update(unload_evidence)
            else:
                u_ev = MovementEvent(
                    event_id=self.generate_event_id(),
                    event_type=unload_event_type,
                    camera_id=self.camera_id,
                    timestamp=self.last_update_time,
                    primary_object=primary_desc,
                    secondary_object=secondary_desc,
                    zone=zone_meta or {"zone_code": zone_code, "zone_name": zone_code},
                    evidence=unload_evidence,
                    confidence=a_score,
                    status=new_state,
                    event_level=self._determine_event_level(primary_desc, secondary_desc),
                    stage="UNLOADING",
                    created_frame=self.frame_index,
                    last_seen_frame=self.frame_index
                )
                self.active_events[unload_key] = u_ev
                self.event_history.append(u_ev)
            if sustained and "activated_frame" not in u_ev.evidence:
                u_ev.evidence["activated_frame"] = self.frame_index
            current_frame_events.append(u_ev)

        # --------------------------------------------------------------------
        # STEP 3: TIMEOUT, EXPIRATION & DEPARTURE MANAGEMENT
        # --------------------------------------------------------------------
        for key, event in list(self.active_events.items()):
            if key not in seen_event_keys:
                if event.event_type in (EventType.BOX_EXITED_ZONE, EventType.MATERIAL_EXITED_ZONE):
                    event.status = EventState.COMPLETED
                    del self.active_events[key]
                elif (key[0] == "UNLOAD" and event.status == EventState.ACTIVE
                      and key[1] in current_mat_ids and self.box_zone_history.get(key[1]) == key[3]):
                    # Sustained unloading evidence and the material is still visible in dock zone
                    # but no longer associated with the truck -> separated from truck: COMPLETED.
                    event.status = EventState.COMPLETED
                    event.last_seen_frame = self.frame_index
                    event.evidence["conclusion_reason"] = "MATERIAL_SEPARATED_FROM_TRUCK_IN_DOCK_ZONE"
                    del self.active_events[key]
                else:
                    event.missed_frames += 1
                    if event.missed_frames >= self.config.event_timeout_frames:
                        # Timeout exceeded -> Transition to EXPIRED
                        event.status = EventState.EXPIRED
                        del self.active_events[key]

        # Bounded Memory Cleanup for departed tracks (Requirement 18)
        stale_threshold = self.config.event_timeout_frames * 2
        for tid in list(self.last_seen_track_frame.keys()):
            if (self.frame_index - self.last_seen_track_frame[tid]) > stale_threshold:
                self.box_zone_history.pop(tid, None)
                self.box_zone_meta.pop(tid, None)
                self.material_dwell_frames.pop(tid, None)
                self.material_active_custody.pop(tid, None)
                self.last_seen_track_frame.pop(tid, None)

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
        try:
            from material_association_service import get_material_association_service
            self.material_assoc_service = get_material_association_service()
        except ImportError:
            self.material_assoc_service = None

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
            "service": "Warehouse Movement Event Detection Foundation (Part 10 & 12)",
            "config": self.config.to_dict(),
            "database_access": "ZERO-WRITES (Strictly In-Memory)",
            "active_camera_sessions": active_cams,
            "supported_event_types": [e.value for e in EventType]
        }

    def get_dock_unloading_evidence(
        self,
        camera_ids: Optional[List[str]] = None,
        zone_code: Optional[str] = None,
        include_candidates: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Part 4: Read-only aggregation of dock-unloading evidence across camera sessions.
        Optionally filtered by camera ids and dock zone code. Never writes to any store.
        """
        results: List[Dict[str, Any]] = []
        target_zone = str(zone_code).upper() if zone_code else None
        for cam_id, sess in list(self.sessions.items()):
            if camera_ids is not None and cam_id not in camera_ids:
                continue
            for ev in sess.get_unloading_events():
                ev_zone = str((ev.get("zone") or {}).get("zone_code") or "").upper()
                if target_zone and ev_zone != target_zone:
                    continue
                if not include_candidates and ev.get("status") == EventState.CANDIDATE.value:
                    continue
                results.append(ev)
        return results

    def get_recent_events(
        self,
        limit: int = 50,
        camera_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Part 12: Read-only aggregation of recent movement events across all active camera sessions.
        Ordered chronologically descending. Strictly in-memory and bounded. Zero database writes.
        """
        all_events: List[Dict[str, Any]] = []
        for cid, sess in list(self.sessions.items()):
            if camera_id and cid != camera_id:
                continue
            for ev in sess.event_history:
                all_events.append(ev.to_dict())
        all_events.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
        return all_events[:limit]

    def get_active_events(
        self,
        camera_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Part 12: Returns currently ongoing active events across camera sessions.
        """
        active_list: List[Dict[str, Any]] = []
        for cid, sess in list(self.sessions.items()):
            if camera_id and cid != camera_id:
                continue
            for ev in sess.active_events.values():
                active_list.append(ev.to_dict())
        return active_list

    def get_cross_camera_material_timeline(
        self,
        material_id: str,
        include_candidates: bool = False
    ) -> Dict[str, Any]:
        """
        Cross-camera continuity query conforming to Requirements 8, 9, 10, 11:
        1. NO visual cross-camera Re-ID (Strictly explicit physical identity).
        2. Aggregates explainable events across camera sessions strictly by validated identity.
        3. Identifies and isolates ambiguous/conflicting identities.
        """
        target_id = str(material_id).strip().upper()
        matched_events: List[Dict[str, Any]] = []
        observed_cameras: Set[str] = set()
        conflicts: List[Dict[str, Any]] = []

        for cam_id, session in self.sessions.items():
            for ev in session.event_history:
                primary = ev.primary_object or {}
                ident_id = str(primary.get("identity_id") or primary.get("validated_master_id") or "").strip().upper()
                if ident_id != target_id:
                    continue

                ident_status = str(primary.get("identity_status") or "").upper()
                val_status = str(primary.get("validation_status") or "").upper()
                is_ambig = bool(ev.evidence.get("is_ambiguous", False) or ident_status in ("AMBIGUOUS", "CONFLICT"))

                # Strict Requirement 11: Do not create false material movement history on ambiguous/conflicting identity
                if is_ambig:
                    conflicts.append({
                        "event_id": ev.event_id,
                        "camera_id": cam_id,
                        "timestamp": ev.timestamp,
                        "event_type": ev.event_type,
                        "identity_status": ident_status,
                        "reason": ev.evidence.get("ambiguity_reason", "AMBIGUOUS_OR_CONFLICTING_IDENTITY")
                    })
                    continue

                # Filter out candidates if not requested
                if not include_candidates and ev.status == EventState.CANDIDATE.value:
                    continue

                observed_cameras.add(cam_id)
                matched_events.append(ev.to_dict())

        # Sort chronologically by timestamp / created_frame
        matched_events.sort(key=lambda x: (x.get("timestamp", ""), x.get("metrics", {}).get("created_frame", 0)))

        return {
            "success": True,
            "material_id": material_id,
            "cross_camera_continuity_method": "EXPLICIT_PHYSICAL_IDENTITY",
            "visual_reid_used": False,
            "governance_note": "Cross-camera continuity strictly relies on validated barcode/QR/OCR identity without visual Re-ID embeddings.",
            "total_events": len(matched_events),
            "observed_cameras": sorted(list(observed_cameras)),
            "cameras_visited": sorted(list(observed_cameras)),
            "has_conflicts": len(conflicts) > 0,
            "conflicting_events_isolated": conflicts,
            "timeline": matched_events
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
        material_assocs: Optional[List[Dict[str, Any]]] = None,
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
            material_assocs=material_assocs,
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
            ma = kwargs.get("material_assocs")
            if associations and isinstance(associations, dict):
                tb = associations.get("truck_associations") or associations.get("truck_box_assocs") or tb
                wb = associations.get("worker_associations") or associations.get("worker_box_assocs") or wb
                bb = associations.get("bin_associations") or associations.get("box_bin_assocs") or bb
                ma = associations.get("material_associations") or associations.get("material_assocs") or ma

            session = self.get_session(actual_cam)
            if camera_zones is None:
                camera_zones = self._load_camera_zones(actual_cam)

            return session.update(
                tracks=actual_tracks,
                truck_box_assocs=tb,
                worker_box_assocs=wb,
                box_bin_assocs=bb,
                material_assocs=ma,
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

        # Step 4b: Part 9 Material-Agnostic Associations
        ma_assocs = []
        ma_ms = 0.0
        if self.material_assoc_service:
            ma_assocs, ma_ms = self.material_assoc_service.process_tracks(
                tracks=tracks,
                camera_id=camera_id,
                camera_zones=camera_zones
            )

        # Step 5: Movement Event Detection
        t_event_start = time.perf_counter()
        session = self.get_session(camera_id)
        event_res = session.update(
            tracks=tracks,
            truck_box_assocs=tb_assocs,
            worker_box_assocs=wb_assocs,
            box_bin_assocs=bb_assocs,
            material_assocs=ma_assocs,
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
                "association_ms": round(tb_ms + wb_ms + bb_ms + ma_ms, 2),
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
        self.get_session(camera_id)

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
                ma = frame_data.get("material_assocs", [])

                res, ev_ms = self.process_events(
                    tracks=tracks,
                    truck_box_assocs=tb,
                    worker_box_assocs=wb,
                    box_bin_assocs=bb,
                    material_assocs=ma,
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

        if sequence_name == "automotive_warehouse_flow":
            zones_to_use = [
                {
                    "id": 1,
                    "zone_code": "DOCK-01",
                    "zone_name": "Dock 01",
                    "zone_type": "DOCK",
                    "polygon": [{"x": 0.05, "y": 0.05}, {"x": 0.35, "y": 0.05}, {"x": 0.35, "y": 0.40}, {"x": 0.05, "y": 0.40}]
                },
                {
                    "id": 2,
                    "zone_code": "SORT-01",
                    "zone_name": "Sorting Area",
                    "zone_type": "SORTING",
                    "polygon": [{"x": 0.40, "y": 0.05}, {"x": 0.70, "y": 0.05}, {"x": 0.70, "y": 0.40}, {"x": 0.40, "y": 0.40}]
                },
                {
                    "id": 3,
                    "zone_code": "STAGE-01",
                    "zone_name": "Staging Area",
                    "zone_type": "STAGING",
                    "polygon": [{"x": 0.75, "y": 0.05}, {"x": 0.95, "y": 0.05}, {"x": 0.95, "y": 0.40}, {"x": 0.75, "y": 0.40}]
                },
                {
                    "id": 4,
                    "zone_code": "BIN-A-01",
                    "zone_name": "Storage Bin A01",
                    "zone_type": "STORAGE",
                    "polygon": [{"x": 0.40, "y": 0.50}, {"x": 0.70, "y": 0.50}, {"x": 0.70, "y": 0.90}, {"x": 0.40, "y": 0.90}]
                },
                {
                    "id": 5,
                    "zone_code": "DISP-01",
                    "zone_name": "Dispatch Area",
                    "zone_type": "DISPATCH",
                    "polygon": [{"x": 0.75, "y": 0.50}, {"x": 0.95, "y": 0.50}, {"x": 0.95, "y": 0.90}, {"x": 0.75, "y": 0.90}]
                }
            ]

            mat_track = {"track_id": 201, "class_code": "ROD", "center": [0.20, 0.20], "bbox": [0.15, 0.15, 0.25, 0.25], "identity_id": "ROD-STEEL-4140-A", "validation_status": "VALIDATED"}
            truck_track = {"track_id": 10, "class_code": "TRUCK", "center": [0.22, 0.22], "bbox": [0.05, 0.05, 0.35, 0.40], "identity_id": "TRK-MH12-8821", "validation_status": "VALIDATED"}
            worker_track = {"track_id": 30, "class_code": "WORKER", "center": [0.23, 0.21], "bbox": [0.18, 0.15, 0.28, 0.30], "identity_id": "W-VIKRAM", "validation_status": "VALIDATED"}
            bin_track = {"track_id": 50, "class_code": "BIN", "center": [0.55, 0.70], "bbox": [0.45, 0.60, 0.65, 0.80], "identity_id": "BIN-A-01", "validation_status": "VALIDATED"}

            frames_data = [
                # Frame 1: Rod inside DOCK-01 (dwell 1 - CANDIDATE)
                {"tracks": [dict(mat_track, center=[0.20, 0.20])], "assocs": {}, "material_assocs": {}},
                # Frame 2: Rod inside DOCK-01 (dwell 2 - CANDIDATE)
                {"tracks": [dict(mat_track, center=[0.21, 0.20])], "assocs": {}, "material_assocs": {}},
                # Frame 3: Rod inside DOCK-01 (dwell 3 - MATERIAL_ENTERED_ZONE)
                {"tracks": [dict(mat_track, center=[0.22, 0.20])], "assocs": {}, "material_assocs": {}},
                # Frame 4: Truck arrives + associated with Rod (MATERIAL_ASSOCIATED_WITH_TRUCK + MATERIAL_UNLOADED_AT_DOCK)
                {
                    "tracks": [dict(mat_track, center=[0.22, 0.20]), truck_track],
                    "assocs": {},
                    "material_assocs": {
                        "truck_material_associations": [{
                            "truck_track_id": 10, "material_track_id": 201, "association_state": "CONFIRMED",
                            "association_score": 0.94, "is_ambiguous": False
                        }]
                    }
                },
                # Frame 5: Worker takes custody (Custody handoff! MATERIAL_ASSOCIATED_WITH_WORKER + TRUCK finishes)
                {
                    "tracks": [dict(mat_track, center=[0.22, 0.20]), worker_track],
                    "assocs": {},
                    "material_assocs": {
                        "worker_material_associations": [{
                            "worker_track_id": 30, "material_track_id": 201, "association_state": "CONFIRMED",
                            "association_score": 0.91, "is_ambiguous": False
                        }]
                    }
                },
                # Frames 6-8: Moves to SORT-01 (dwell 1, 2, 3 -> MATERIAL_MOVED_TO_SORTING)
                {"tracks": [dict(mat_track, center=[0.50, 0.20])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.52, 0.20])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.55, 0.20])], "assocs": {}, "material_assocs": {}},
                # Frames 9-11: Moves to STAGE-01 (dwell 1, 2, 3 -> MATERIAL_ENTERED_STAGING)
                {"tracks": [dict(mat_track, center=[0.80, 0.20])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.82, 0.20])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.85, 0.20])], "assocs": {}, "material_assocs": {}},
                # Frames 12-14: Stored in BIN-A-01 (dwell 1, 2, 3 + bin assoc -> MATERIAL_STORED_IN_BIN)
                {"tracks": [dict(mat_track, center=[0.55, 0.70]), bin_track], "assocs": {}, "material_assocs": {"material_bin_associations": [{"bin_track_id": 50, "material_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.96, "is_ambiguous": False}]}},
                {"tracks": [dict(mat_track, center=[0.55, 0.70]), bin_track], "assocs": {}, "material_assocs": {"material_bin_associations": [{"bin_track_id": 50, "material_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.96, "is_ambiguous": False}]}},
                {"tracks": [dict(mat_track, center=[0.55, 0.70]), bin_track], "assocs": {}, "material_assocs": {"material_bin_associations": [{"bin_track_id": 50, "material_track_id": 201, "association_state": "CONFIRMED", "association_score": 0.96, "is_ambiguous": False}]}},
                # Frame 15: Exits BIN-A-01 into transit hallway (center [0.72, 0.45]) -> MATERIAL_EXITED_ZONE
                {"tracks": [dict(mat_track, center=[0.72, 0.45])], "assocs": {}, "material_assocs": {}},
                # Frames 16-18: Dispatched at DISP-01 (dwell 1, 2, 3 -> MATERIAL_DISPATCHED)
                {"tracks": [dict(mat_track, center=[0.80, 0.70])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.82, 0.70])], "assocs": {}, "material_assocs": {}},
                {"tracks": [dict(mat_track, center=[0.85, 0.70])], "assocs": {}, "material_assocs": {}}
            ]
        else:
            zones_to_use = [{
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
            mat_assocs = fd.get("material_assocs", {})
            res = session.update(
                tracks=fd.get("tracks", []),
                truck_box_assocs=tb,
                worker_box_assocs=wb,
                box_bin_assocs=bb,
                material_assocs=mat_assocs,
                camera_zones=zones_to_use,
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
