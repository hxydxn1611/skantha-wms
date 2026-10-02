"""
W.A.R.L.O.G. / Skandha WMS AI Vision & Tracking Master
Part 13 — Material Traceability Foundation Service

Provides an explainable, machine-readable, material-centric movement history layer
built on top of Parts 1–12 (Detection, Tracking, Identity, Master-Data Validation,
Zones/ROIs, Truck/Worker/Bin Associations, and Movement Events).

Answers the core traceability question:
"Where did this material come from, what did it interact with, where was it observed, and where did it go?"
Example: BOX B104 -> TRUCK GP-1000 -> DOCK-01 -> WORKER W07 -> BIN-A101

CRITICAL ARCHITECTURAL DISTINCTION:
Traceability != Inventory Transaction
This layer records and reconstructs observed material movement history strictly in memory.
It does NOT post goods receipt, issue inventory, perform putaway, or alter any database table.
ZERO database writes. Strictly in-memory.
"""

import os
import sys
import copy
import math
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import cv2

# Ensure local imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from movement_event_service import (
    EventType,
    EventState,
    MovementEvent,
    get_movement_event_service,
    MultiObjectMovementEventService
)
from detection_service import is_point_in_polygon
from validation_service import get_validation_service

logger = logging.getLogger("material_traceability_service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s][%(name)s][%(levelname)s] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)


# ============================================================================
# 1. ENUMS AND CONFIGURATION
# ============================================================================

class TraceabilityLevel(str, Enum):
    """
    Explicit Traceability Levels conforming to Section 6 specification.
    Never upgraded automatically without supporting evidence.
    """
    TRACK_LEVEL = "TRACK_LEVEL"                   # Visually observed, real-world identity not established
    IDENTIFIED = "IDENTIFIED"                     # Identity captured (barcode/QR/OCR), master-data validation pending
    VALIDATED_REAL_WORLD = "VALIDATED_REAL_WORLD" # Identity verified against warehouse master data


class MaterialTraceStatus(str, Enum):
    """
    AI Material Traceability States (Section 16).
    NOTE: These are AI observation states, NOT WMS inventory transaction statuses.
    """
    UNSEEN = "UNSEEN"                             # Not yet visually acquired
    OBSERVED = "OBSERVED"                         # Visually detected in field of view
    IDENTIFIED = "IDENTIFIED"                     # Identity extracted
    VALIDATED = "VALIDATED"                       # Master data verified
    IN_TRANSIT = "IN_TRANSIT"                     # In motion / between zones
    AT_ZONE = "AT_ZONE"                           # Resident inside a warehouse zone / ROI
    ASSOCIATED = "ASSOCIATED"                     # Actively associated with truck or worker
    DESTINATION_OBSERVED = "DESTINATION_OBSERVED" # Associated with target bin
    COMPLETED = "COMPLETED"                       # Trace completed (exited scene or confirmed stored)


@dataclass
class TraceabilityConfig:
    """
    Bounded memory configuration to prevent memory leaks (Section 39).
    """
    max_materials: int = 500
    max_timeline_entries: int = 100
    max_events_per_material: int = 200
    max_camera_observations: int = 100
    max_zone_history: int = 50

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_materials": self.max_materials,
            "max_timeline_entries": self.max_timeline_entries,
            "max_events_per_material": self.max_events_per_material,
            "max_camera_observations": self.max_camera_observations,
            "max_zone_history": self.max_zone_history
        }


# ============================================================================
# 2. DATA MODELS
# ============================================================================

@dataclass
class MaterialTraceEvent:
    """
    Chronological timeline history record for a material (Section 4).
    Reuses Movement Event evidence without fabrication.
    """
    trace_id: str
    material_id: str
    event_id: str
    event_type: str
    timestamp: str
    camera_id: str
    zone: Optional[Dict[str, Any]] = None
    related_entity: Optional[Dict[str, Any]] = None
    event_state: str = "ACTIVE"
    evidence: Dict[str, Any] = field(default_factory=dict)
    trace_level: str = TraceabilityLevel.TRACK_LEVEL
    nature: str = "OBSERVED"  # OBSERVED, VALIDATED, or INFERRED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "material_id": self.material_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "zone": self.zone,
            "related_entity": self.related_entity,
            "event_state": self.event_state,
            "evidence": self.evidence,
            "trace_level": self.trace_level,
            "nature": self.nature
        }


@dataclass
class MaterialTraceRecord:
    """
    Material-centric history dossier (Section 3).
    Maintains complete observable lifecycle for a specific material or track.
    """
    material_id: str
    material_class: str = "BOX"
    identity_status: str = "UNIDENTIFIED"  # UNIDENTIFIED, UNREGISTERED, VALIDATED
    traceability_status: str = MaterialTraceStatus.OBSERVED
    traceability_level: str = TraceabilityLevel.TRACK_LEVEL

    first_seen: str = ""
    last_seen: str = ""

    current_location: Optional[Dict[str, Any]] = None
    source: Optional[Dict[str, Any]] = None        # Established from confirmed truck association
    destination: Optional[Dict[str, Any]] = None   # Established from confirmed bin association

    # Conflict preservation lists (Section 19)
    candidate_sources: List[Dict[str, Any]] = field(default_factory=list)
    candidate_destinations: List[Dict[str, Any]] = field(default_factory=list)

    # Active and historical associations
    associated_trucks: List[Dict[str, Any]] = field(default_factory=list)
    associated_workers: List[Dict[str, Any]] = field(default_factory=list)
    associated_bins: List[Dict[str, Any]] = field(default_factory=list)

    # Historical streams
    camera_observations: List[Dict[str, Any]] = field(default_factory=list)
    zone_history: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[MaterialTraceEvent] = field(default_factory=list)

    # Ingested event ID set for strict deduplication (Section 14)
    event_ids: List[str] = field(default_factory=list)

    # Visual tracking references per camera {camera_id: last_track_id}
    camera_tracks: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_id": self.material_id,
            "material_class": self.material_class,
            "identity_status": self.identity_status,
            "traceability_status": self.traceability_status,
            "traceability_level": self.traceability_level,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "current_location": self.current_location,
            "source": self.source,
            "destination": self.destination,
            "candidate_sources": self.candidate_sources,
            "candidate_destinations": self.candidate_destinations,
            "associated_trucks": self.associated_trucks,
            "associated_workers": self.associated_workers,
            "associated_bins": self.associated_bins,
            "camera_observations": self.camera_observations,
            "zone_history": self.zone_history,
            "timeline": [e.to_dict() for e in self.timeline],
            "event_ids": self.event_ids,
            "camera_tracks": self.camera_tracks
        }


# ============================================================================
# 3. MATERIAL TRACEABILITY SERVICE
# ============================================================================

class MaterialTraceabilityService:
    """
    In-memory material traceability coordinator.
    Ingests Part 12 movement events, synthesizes material-centric traces,
    preserves conflicts, orders timelines chronologically, and manages bounded memory.
    """

    def __init__(self, config: Optional[TraceabilityConfig] = None):
        self.config = config or TraceabilityConfig()
        self.materials: Dict[str, MaterialTraceRecord] = {}
        self.track_to_material: Dict[str, str] = {}  # "{camera_id}_{track_id}" -> material_id
        self.trace_counter: int = 0
        self._annotated_frames: Dict[str, np.ndarray] = {}

        # Upstream service references
        self.movement_event_service = get_movement_event_service()
        self.validation_service = get_validation_service()

        logger.info("MaterialTraceabilityService initialized successfully.")

    def reset(self) -> Dict[str, Any]:
        """Clear all in-memory traceability records and reset counters (Section 34)."""
        self.materials.clear()
        self.track_to_material.clear()
        self.trace_counter = 0
        self._annotated_frames.clear()
        logger.info("MaterialTraceabilityService reset cleanly.")
        return {
            "success": True,
            "message": "Material traceability in-memory state reset successfully."
        }

    def _generate_trace_id(self) -> str:
        self.trace_counter += 1
        return f"TRACE-{self.trace_counter:06d}"

    def get_status(self) -> Dict[str, Any]:
        """Operational diagnostic status reporting (Section 23)."""
        total_materials = len(self.materials)
        total_events = sum(len(m.timeline) for m in self.materials.values())
        validated_materials = sum(1 for m in self.materials.values() if m.traceability_level == TraceabilityLevel.VALIDATED_REAL_WORLD)
        in_transit = sum(1 for m in self.materials.values() if m.traceability_status == MaterialTraceStatus.IN_TRANSIT)

        return {
            "service": "MaterialTraceabilityService",
            "version": "1.0.0-part13",
            "storage": "STRICTLY_IN_MEMORY (Zero Database Writes)",
            "config": self.config.to_dict(),
            "total_materials_tracked": total_materials,
            "total_timeline_events": total_events,
            "validated_materials": validated_materials,
            "in_transit_materials": in_transit,
            "materials_list": list(self.materials.keys())
        }

    def _resolve_material_key(self, camera_id: str, primary_obj: Dict[str, Any]) -> str:
        """
        Determines the unique material identifier.
        If real-world identity is established (e.g. 'B104'), uses identity_id.
        If unidentified, generates a camera-scoped track key (e.g. 'TRACK_CAM-001_17')
        to ensure strict track isolation (Section 12).
        """
        identity_id = primary_obj.get("identity_id")
        identity_status = primary_obj.get("identity_status", "UNIDENTIFIED")
        track_id = primary_obj.get("track_id")

        if identity_id and identity_status in ("VALIDATED", "UNREGISTERED", "IDENTIFIED"):
            return str(identity_id)

        # Fallback to isolated track key
        track_key = f"TRACK_{camera_id}_{track_id}"
        return track_key

    def _get_or_create_material(
        self,
        material_key: str,
        camera_id: str,
        primary_obj: Dict[str, Any],
        timestamp: str
    ) -> MaterialTraceRecord:
        """
        Retrieves an existing material record or instantiates a new one.
        Handles bounded memory eviction if maximum material threshold is exceeded.
        """
        if material_key in self.materials:
            record = self.materials[material_key]
            record.last_seen = timestamp
            return record

        # Bounded memory: If exceeding max_materials, evict oldest material
        if len(self.materials) >= self.config.max_materials:
            oldest_key = min(self.materials.keys(), key=lambda k: self.materials[k].last_seen or "")
            del self.materials[oldest_key]
            # Clean up track mappings
            self.track_to_material = {k: v for k, v in self.track_to_material.items() if v != oldest_key}
            logger.info("Evicted oldest material trace '%s' due to memory bounding.", oldest_key)

        # Determine level and validation status
        identity_id = primary_obj.get("identity_id")
        identity_status = primary_obj.get("identity_status", "UNIDENTIFIED")

        if identity_id and identity_status == "VALIDATED":
            t_level = TraceabilityLevel.VALIDATED_REAL_WORLD
            t_status = MaterialTraceStatus.VALIDATED
            mat_id = str(identity_id)
        elif identity_id:
            t_level = TraceabilityLevel.IDENTIFIED
            t_status = MaterialTraceStatus.IDENTIFIED
            mat_id = str(identity_id)
        else:
            t_level = TraceabilityLevel.TRACK_LEVEL
            t_status = MaterialTraceStatus.OBSERVED
            mat_id = material_key

        record = MaterialTraceRecord(
            material_id=mat_id,
            material_class=primary_obj.get("class_code", "BOX"),
            identity_status=identity_status,
            traceability_status=t_status,
            traceability_level=t_level,
            first_seen=timestamp,
            last_seen=timestamp
        )

        track_id = primary_obj.get("track_id")
        if track_id is not None:
            record.camera_tracks[camera_id] = track_id
            self.track_to_material[f"{camera_id}_{track_id}"] = mat_id

        self.materials[mat_id] = record
        return record

    def ingest_movement_event(self, event: Union[MovementEvent, Dict[str, Any]]) -> Optional[MaterialTraceEvent]:
        """
        Core ingestion pipeline (Section 13).
        Consumes Movement Events from Part 12, performs deduplication,
        updates material state and relationships, and appends a chronological timeline record.
        """
        # Normalize event dict
        evt_dict = event.to_dict() if isinstance(event, MovementEvent) else copy.deepcopy(event)

        event_id = evt_dict.get("event_id")
        event_type = evt_dict.get("event_type")
        camera_id = evt_dict.get("camera_id", "CAM-001")
        timestamp = evt_dict.get("timestamp", datetime.now(timezone.utc).isoformat())
        primary_obj = evt_dict.get("primary_object", {})
        secondary_obj = evt_dict.get("secondary_object")
        zone = evt_dict.get("zone")
        evidence = evt_dict.get("evidence", {})
        confidence = float(evt_dict.get("confidence", 0.0))
        event_state = evt_dict.get("status", "ACTIVE")
        event_level = evt_dict.get("event_level", "TRACK_LEVEL")

        if not event_id or not event_type or not primary_obj:
            logger.warning("Rejected malformed movement event payload: %s", evt_dict)
            return None

        # Resolve material key
        material_key = self._resolve_material_key(camera_id, primary_obj)
        record = self._get_or_create_material(material_key, camera_id, primary_obj, timestamp)

        # STRICT DEDUPLICATION (Section 14)
        if event_id in record.event_ids:
            logger.debug("Event '%s' already ingested for material '%s'. Skipping duplicate.", event_id, material_key)
            return None

        record.event_ids.append(event_id)
        record.last_seen = timestamp

        # Update track mapping if track_id is provided
        track_id = primary_obj.get("track_id")
        if track_id is not None:
            record.camera_tracks[camera_id] = track_id
            self.track_to_material[f"{camera_id}_{track_id}"] = record.material_id

        # Determine nature and trace level
        if record.identity_status == "VALIDATED":
            trace_level = TraceabilityLevel.VALIDATED_REAL_WORLD
            nature = "VALIDATED"
        elif record.identity_status in ("IDENTIFIED", "UNREGISTERED"):
            trace_level = TraceabilityLevel.IDENTIFIED
            nature = "OBSERVED"
        else:
            trace_level = TraceabilityLevel.TRACK_LEVEL
            nature = "OBSERVED"

        # Construct MaterialTraceEvent
        trace_id = self._generate_trace_id()
        trace_evt = MaterialTraceEvent(
            trace_id=trace_id,
            material_id=record.material_id,
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            camera_id=camera_id,
            zone=zone,
            related_entity=secondary_obj,
            event_state=event_state,
            evidence=evidence,
            trace_level=trace_level,
            nature=nature
        )

        # --------------------------------------------------------------------
        # PROCESS BY EVENT TYPE
        # --------------------------------------------------------------------

        # 1. ZONE ENTRY
        if event_type == EventType.BOX_ENTERED_ZONE or event_type == "BOX_ENTERED_ZONE":
            if zone:
                record.current_location = {
                    "camera_id": camera_id,
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "zone_id": zone.get("zone_id")
                }
                zone_entry = {
                    "transition": "ENTER",
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "camera_id": camera_id,
                    "timestamp": timestamp,
                    "event_id": event_id
                }
                record.zone_history.append(zone_entry)
                if len(record.zone_history) > self.config.max_zone_history:
                    record.zone_history.pop(0)

                record.traceability_status = MaterialTraceStatus.AT_ZONE

        # 2. ZONE EXIT
        elif event_type == EventType.BOX_EXITED_ZONE or event_type == "BOX_EXITED_ZONE":
            if zone:
                zone_exit = {
                    "transition": "EXIT",
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "camera_id": camera_id,
                    "timestamp": timestamp,
                    "event_id": event_id
                }
                record.zone_history.append(zone_exit)
                if len(record.zone_history) > self.config.max_zone_history:
                    record.zone_history.pop(0)

            # In transit between zones
            record.traceability_status = MaterialTraceStatus.IN_TRANSIT
            if record.current_location and zone and record.current_location.get("zone_code") == zone.get("zone_code"):
                record.current_location["status"] = "EXITED"

        # 3. TRUCK ASSOCIATION (SOURCE DERIVATION)
        elif event_type == EventType.BOX_ASSOCIATED_WITH_TRUCK or event_type == "BOX_ASSOCIATED_WITH_TRUCK":
            truck_info = {
                "type": "TRUCK",
                "identity_id": secondary_obj.get("identity_id") if secondary_obj else None,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }

            # Avoid duplicate association entries
            if not any(t.get("event_id") == event_id for t in record.associated_trucks):
                record.associated_trucks.append(truck_info)

            # SOURCE DERIVATION & CONFLICT PRESERVATION (Sections 7 & 19)
            if record.source is None:
                record.source = truck_info
                record.candidate_sources.append(truck_info)
            else:
                # Check for conflict: different truck identity or track
                existing_id = record.source.get("identity_id") or record.source.get("track_id")
                new_id = truck_info.get("identity_id") or truck_info.get("track_id")
                if existing_id != new_id:
                    if not any(c.get("identity_id") == new_id for c in record.candidate_sources):
                        record.candidate_sources.append(truck_info)
                    logger.info("Preserved conflicting candidate truck source for material '%s': %s", record.material_id, new_id)

            record.traceability_status = MaterialTraceStatus.ASSOCIATED

        # 4. WORKER ASSOCIATION
        elif event_type == EventType.BOX_ASSOCIATED_WITH_WORKER or event_type == "BOX_ASSOCIATED_WITH_WORKER":
            worker_info = {
                "type": "WORKER",
                "identity_id": secondary_obj.get("identity_id") if secondary_obj else None,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }
            if not any(w.get("event_id") == event_id for w in record.associated_workers):
                record.associated_workers.append(worker_info)

            record.traceability_status = MaterialTraceStatus.ASSOCIATED

        # 5. BIN ASSOCIATION (DESTINATION DERIVATION)
        elif event_type == EventType.BOX_ASSOCIATED_WITH_BIN or event_type == "BOX_ASSOCIATED_WITH_BIN":
            bin_info = {
                "type": "BIN",
                "identity_id": secondary_obj.get("identity_id") if secondary_obj else None,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }
            if not any(b.get("event_id") == event_id for b in record.associated_bins):
                record.associated_bins.append(bin_info)

            # DESTINATION DERIVATION & CONFLICT PRESERVATION (Sections 8 & 19)
            if record.destination is None:
                record.destination = bin_info
                record.candidate_destinations.append(bin_info)
            else:
                existing_bin = record.destination.get("identity_id") or record.destination.get("track_id")
                new_bin = bin_info.get("identity_id") or bin_info.get("track_id")
                if existing_bin != new_bin:
                    if not any(c.get("identity_id") == new_bin for c in record.candidate_destinations):
                        record.candidate_destinations.append(bin_info)
                    logger.info("Preserved conflicting candidate bin destination for material '%s': %s", record.material_id, new_bin)

            record.traceability_status = MaterialTraceStatus.DESTINATION_OBSERVED

        # 6. OBSERVATION EVENTS (BOX_NEAR_*)
        elif event_type in (EventType.BOX_NEAR_TRUCK, EventType.BOX_NEAR_WORKER, EventType.BOX_NEAR_BIN,
                            "BOX_NEAR_TRUCK", "BOX_NEAR_WORKER", "BOX_NEAR_BIN"):
            trace_evt.nature = "OBSERVED"
            # Does not force confirmed source/destination

        # CAMERA OBSERVATIONS (Section 11)
        cam_obs = {
            "camera_id": camera_id,
            "timestamp": timestamp,
            "zone": zone.get("zone_code") if zone else None,
            "event_id": event_id
        }
        record.camera_observations.append(cam_obs)
        if len(record.camera_observations) > self.config.max_camera_observations:
            record.camera_observations.pop(0)

        # APPEND TO TIMELINE WITH BOUNDED MEMORY & CHRONOLOGICAL SORTING (Sections 15 & 39)
        record.timeline.append(trace_evt)

        # Deterministic chronological sort: Primary by timestamp, secondary by trace_id (Section 15 & 33)
        record.timeline.sort(key=lambda x: (x.timestamp, x.trace_id))

        # Enforce memory bounding on timeline entries
        if len(record.timeline) > self.config.max_timeline_entries:
            record.timeline.pop(0)

        return trace_evt

    def ingest_events(self, events: List[Union[MovementEvent, Dict[str, Any]]]) -> List[MaterialTraceEvent]:
        """Ingest a batch of movement events."""
        results = []
        for evt in events:
            res = self.ingest_movement_event(evt)
            if res:
                results.append(res)
        return results

    def get_material(self, material_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve complete material trace dossier (Section 24)."""
        record = self.materials.get(material_id)
        if not record:
            # Check track-to-material mappings
            for track_key, mapped_id in self.track_to_material.items():
                if mapped_id == material_id or track_key == material_id:
                    record = self.materials.get(mapped_id)
                    break

        return record.to_dict() if record else None

    def get_timeline(self, material_id: str) -> List[Dict[str, Any]]:
        """Retrieve chronological event timeline for a material (Section 25)."""
        mat = self.get_material(material_id)
        if not mat:
            return []
        return mat.get("timeline", [])

    def get_all_materials(self) -> List[Dict[str, Any]]:
        """List summary of all tracked materials."""
        summaries = []
        for mat_id, rec in self.materials.items():
            summaries.append({
                "material_id": rec.material_id,
                "material_class": rec.material_class,
                "identity_status": rec.identity_status,
                "traceability_status": rec.traceability_status,
                "traceability_level": rec.traceability_level,
                "first_seen": rec.first_seen,
                "last_seen": rec.last_seen,
                "source": rec.source.get("identity_id") if rec.source else None,
                "current_zone": rec.current_location.get("zone_code") if rec.current_location else None,
                "destination": rec.destination.get("identity_id") if rec.destination else None,
                "timeline_count": len(rec.timeline)
            })
        return summaries

    def get_camera_status(self, camera_id: str = "CAM-001") -> Dict[str, Any]:
        """Returns materials currently or historically observed at this camera."""
        obs_materials = []
        for mat_id, rec in self.materials.items():
            if any(obs.get("camera_id") == camera_id for obs in rec.camera_observations) or camera_id in rec.camera_tracks:
                obs_materials.append({
                    "material_id": rec.material_id,
                    "class_code": rec.material_class,
                    "status": rec.traceability_status,
                    "level": rec.traceability_level,
                    "current_location": rec.current_location,
                    "last_seen": rec.last_seen
                })
        return {
            "camera_id": camera_id,
            "total_observed_materials": len(obs_materials),
            "materials": obs_materials
        }

    def run_test(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Processes a single test frame or event payload (Section 23).
        Supports synthetic scenarios, custom event ingestion, or movement event service integration.
        """
        payload = payload or {}
        scenario = payload.get("scenario", "box_enter_dock")
        camera_id = payload.get("camera_id", "CAM-001")
        t0 = time.perf_counter()

        events_to_ingest = []
        if "events" in payload and isinstance(payload["events"], list):
            events_to_ingest = payload["events"]
        elif "event" in payload and isinstance(payload["event"], dict):
            events_to_ingest = [payload["event"]]
        else:
            ts = datetime.now(timezone.utc).isoformat()
            if scenario == "box_enter_dock":
                events_to_ingest.append({
                    "event_id": f"EVT-TEST-{int(time.time()*1000)%1000000:06d}",
                    "event_type": "BOX_ENTERED_ZONE",
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.95,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD",
                    "evidence": {"same_camera": True, "same_zone": True, "spatial_proximity": True}
                })
            elif scenario == "box_truck_association":
                events_to_ingest.append({
                    "event_id": f"EVT-TEST-{int(time.time()*1000)%1000000:06d}",
                    "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                    "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.92,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD",
                    "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True}
                })
            elif scenario == "box_worker_association":
                events_to_ingest.append({
                    "event_id": f"EVT-TEST-{int(time.time()*1000)%1000000:06d}",
                    "event_type": "BOX_ASSOCIATED_WITH_WORKER",
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                    "secondary_object": {"track_id": 7, "class_code": "WORKER", "identity_id": "W07", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.89,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD",
                    "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True}
                })
            elif scenario == "box_bin_association":
                events_to_ingest.append({
                    "event_id": f"EVT-TEST-{int(time.time()*1000)%1000000:06d}",
                    "event_type": "BOX_ASSOCIATED_WITH_BIN",
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                    "secondary_object": {"track_id": 99, "class_code": "BIN", "identity_id": "BIN-A101", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 8, "zone_code": "BIN-AREA", "zone_name": "Storage Bin Area A"},
                    "confidence": 0.96,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD",
                    "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True}
                })
            else:
                events_to_ingest.append({
                    "event_id": f"EVT-TEST-{int(time.time()*1000)%1000000:06d}",
                    "event_type": "BOX_ENTERED_ZONE",
                    "camera_id": camera_id,
                    "timestamp": ts,
                    "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.90,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD",
                    "evidence": {"same_camera": True, "same_zone": True}
                })

        ingested = self.ingest_events(events_to_ingest)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        target_mat = "B104" if "B104" in self.materials else (list(self.materials.keys())[0] if self.materials else None)
        dossier = self.get_material(target_mat) if target_mat else None

        return {
            "success": True,
            "synthetic": True,
            "scenario": scenario,
            "events_ingested": len(ingested),
            "processing_time_ms": round(elapsed_ms, 3),
            "materials_count": len(self.materials),
            "material_dossier": dossier,
            "timeline": dossier.get("timeline", []) if dossier else []
        }


    # 4. DETERMINISTIC SYNTHETIC SEQUENCES
    # ========================================================================

    def run_synthetic_sequence(self, sequence_name: str = "complete_trace") -> Dict[str, Any]:
        """
        Executes deterministic synthetic scenarios (Section 27).
        Sequence:
          Frame 1: B104 outside Dock 1.
          Frame 2: B104 enters Dock 1.
          Frame 3: B104 associated with Truck GP-1000.
          Frame 4: B104 associated with Worker W07.
          Frame 5: B104 exits Dock 1.
          Frame 6: B104 enters BIN-AREA.
          Frame 7: B104 associated with Bin BIN-A101.
        """
        self.reset()
        t0 = time.perf_counter()

        camera_id = "CAM-001"
        timestamps = [
            "2026-10-02T10:02:14Z",
            "2026-10-02T10:02:18Z",
            "2026-10-02T10:02:25Z",
            "2026-10-02T10:02:35Z",
            "2026-10-02T10:04:12Z",
            "2026-10-02T10:05:00Z",
            "2026-10-02T10:05:30Z"
        ]

        frames_data = [
            # Frame 1: B104 observed outside Dock 1 (Candidate near Dock)
            {
                "event_id": "EVT-000001",
                "event_type": "BOX_ENTERED_ZONE",
                "camera_id": camera_id,
                "timestamp": timestamps[0],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 1, "zone_code": "YARD-01", "zone_name": "Inbound Yard"},
                "confidence": 0.85,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "spatial_proximity": True}
            },
            # Frame 2: B104 enters Dock 1
            {
                "event_id": "EVT-000002",
                "event_type": "BOX_ENTERED_ZONE",
                "camera_id": camera_id,
                "timestamp": timestamps[1],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                "confidence": 0.95,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "spatial_proximity": True, "transition": "OUTSIDE_TO_INSIDE"}
            },
            # Frame 3: B104 associated with Truck GP-1000
            {
                "event_id": "EVT-000003",
                "event_type": "BOX_ASSOCIATED_WITH_TRUCK",
                "camera_id": camera_id,
                "timestamp": timestamps[2],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                "confidence": 0.92,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True, "temporal_overlap": True, "spatial_proximity": True}
            },
            # Frame 4: B104 associated with Worker W07
            {
                "event_id": "EVT-000004",
                "event_type": "BOX_ASSOCIATED_WITH_WORKER",
                "camera_id": camera_id,
                "timestamp": timestamps[3],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "secondary_object": {"track_id": 7, "class_code": "WORKER", "identity_id": "W07", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                "confidence": 0.89,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True, "interaction_distance": 0.22}
            },
            # Frame 5: B104 exits Dock 1
            {
                "event_id": "EVT-000005",
                "event_type": "BOX_EXITED_ZONE",
                "camera_id": camera_id,
                "timestamp": timestamps[4],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                "confidence": 0.95,
                "status": "COMPLETED",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "transition": "INSIDE_TO_OUTSIDE"}
            },
            # Frame 6: B104 enters BIN-AREA
            {
                "event_id": "EVT-000006",
                "event_type": "BOX_ENTERED_ZONE",
                "camera_id": camera_id,
                "timestamp": timestamps[5],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 8, "zone_code": "BIN-AREA", "zone_name": "Storage Bin Area A"},
                "confidence": 0.93,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "transition": "OUTSIDE_TO_INSIDE"}
            },
            # Frame 7: B104 associated with Bin BIN-A101
            {
                "event_id": "EVT-000007",
                "event_type": "BOX_ASSOCIATED_WITH_BIN",
                "camera_id": camera_id,
                "timestamp": timestamps[6],
                "primary_object": {"track_id": 104, "class_code": "BOX", "identity_id": "B104", "identity_status": "VALIDATED"},
                "secondary_object": {"track_id": 99, "class_code": "BIN", "identity_id": "BIN-A101", "identity_status": "VALIDATED"},
                "zone": {"zone_id": 8, "zone_code": "BIN-AREA", "zone_name": "Storage Bin Area A"},
                "confidence": 0.96,
                "status": "ACTIVE",
                "event_level": "VALIDATED_REAL_WORLD",
                "evidence": {"same_camera": True, "same_zone": True, "sustained_observation": True, "distance": 0.12}
            }
        ]

        ingested_traces = []
        for f in frames_data:
            t = self.ingest_movement_event(f)
            if t:
                ingested_traces.append(t.to_dict())

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        material_dossier = self.get_material("B104")

        return {
            "success": True,
            "synthetic": True,
            "sequence_name": sequence_name,
            "total_frames_executed": len(frames_data),
            "events_ingested": len(ingested_traces),
            "processing_time_ms": round(elapsed_ms, 2),
            "material_dossier": material_dossier,
            "timeline": material_dossier.get("timeline", []) if material_dossier else []
        }

    # ========================================================================
    # 5. VISUAL RENDERING AND ANNOTATION
    # ========================================================================

    def render_annotated_frame(self, camera_id: str = "CAM-001") -> np.ndarray:
        """
        Renders an explainable visual observation preview showing active materials,
        bounding boxes, zones, and traceability badges (Section 37).
        """
        width, height = 960, 540
        canvas = np.zeros((height, width, 3), dtype=np.uint8)

        # Background gradient representing warehouse floor
        for y in range(height):
            c = int(22 + (y / height) * 18)
            canvas[y, :] = (c, c + 2, c + 6)

        # Grid lines
        for x in range(0, width, 80):
            cv2.line(canvas, (x, 0), (x, height), (35, 38, 45), 1)
        for y in range(0, height, 60):
            cv2.line(canvas, (0, y), (width, y), (35, 38, 45), 1)

        # Header banner
        cv2.rectangle(canvas, (0, 0), (width, 42), (20, 24, 30), -1)
        cv2.putText(
            canvas,
            f"W.A.R.L.O.G. TRACEABILITY OBSERVER - NODE [{camera_id}]",
            (16, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (0, 220, 255),
            2,
            cv2.LINE_AA
        )

        status_text = f"TRACKED MATERIALS: {len(self.materials)}"
        cv2.putText(canvas, status_text, (width - 240, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 210, 220), 1, cv2.LINE_AA)

        # Draw simulated warehouse zones
        dock_pts = np.array([[80, 80], [380, 80], [380, 480], [80, 480]], np.int32)
        cv2.polylines(canvas, [dock_pts], True, (0, 165, 255), 2)
        cv2.putText(canvas, "ZONE: DOCK-01", (90, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 165, 255), 1, cv2.LINE_AA)

        bin_pts = np.array([[560, 80], [880, 80], [880, 480], [560, 480]], np.int32)
        cv2.polylines(canvas, [bin_pts], True, (180, 120, 0), 2)
        cv2.putText(canvas, "ZONE: BIN-AREA", (570, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (180, 120, 0), 1, cv2.LINE_AA)

        # Draw materials
        y_offset = 140
        for mat_id, rec in self.materials.items():
            # Choose location based on current location
            if rec.current_location and rec.current_location.get("zone_code") == "DOCK-01":
                cx, cy = 230, min(y_offset, 420)
            elif rec.current_location and rec.current_location.get("zone_code") == "BIN-AREA":
                cx, cy = 720, min(y_offset, 420)
            else:
                cx, cy = 470, min(y_offset, 420)

            # Box rect
            bw, bh = 140, 80
            x1, y1 = cx - bw // 2, cy - bh // 2
            x2, y2 = cx + bw // 2, cy + bh // 2

            color = (0, 255, 120) if rec.traceability_level == TraceabilityLevel.VALIDATED_REAL_WORLD else (0, 200, 255)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            cv2.rectangle(canvas, (x1, y1 - 24), (x2, y1), color, -1)

            cv2.putText(canvas, f"BOX: {mat_id}", (x1 + 6, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(canvas, f"STATUS: {rec.traceability_status}", (x1 + 6, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 230, 240), 1, cv2.LINE_AA)

            src_str = f"SRC: {rec.source.get('identity_id')}" if rec.source else "SRC: UNKNOWN"
            cv2.putText(canvas, src_str, (x1 + 6, y1 + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 190, 200), 1, cv2.LINE_AA)

            dst_str = f"DST: {rec.destination.get('identity_id')}" if rec.destination else "DST: UNKNOWN"
            cv2.putText(canvas, dst_str, (x1 + 6, y1 + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 190, 200), 1, cv2.LINE_AA)

            y_offset += 110

        self._annotated_frames[camera_id] = canvas
        return canvas

    def get_annotated_jpeg(self, camera_id: str = "CAM-001") -> bytes:
        """Returns compressed JPEG bytes of the rendered annotated frame."""
        frame = self.render_annotated_frame(camera_id)
        success, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            raise RuntimeError("Failed to encode JPEG for material traceability preview.")
        return encoded.tobytes()


# Global Singleton instance
_material_traceability_service_instance: Optional[MaterialTraceabilityService] = None

def get_material_traceability_service() -> MaterialTraceabilityService:
    """Retrieve the singleton MaterialTraceabilityService instance."""
    global _material_traceability_service_instance
    if _material_traceability_service_instance is None:
        _material_traceability_service_instance = MaterialTraceabilityService()
    return _material_traceability_service_instance
