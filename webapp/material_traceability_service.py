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
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import cv2

# Ensure local imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from movement_event_service import (
    EventType,
    MovementEvent,
    get_movement_event_service
)
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
    max_container_history: int = 50
    max_previous_locations: int = 50
    max_conflicts: int = 50

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_materials": self.max_materials,
            "max_timeline_entries": self.max_timeline_entries,
            "max_events_per_material": self.max_events_per_material,
            "max_camera_observations": self.max_camera_observations,
            "max_zone_history": self.max_zone_history,
            "max_container_history": self.max_container_history,
            "max_previous_locations": self.max_previous_locations,
            "max_conflicts": self.max_conflicts
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

    # Part 11 additions for explainable timeline
    track_id: Optional[int] = None
    sku_id: Optional[str] = None
    physical_identifier: Optional[str] = None
    physical_identity_type: Optional[str] = None
    truck_id: Optional[str] = None
    worker_id: Optional[str] = None
    container_id: Optional[str] = None
    bin_id: Optional[str] = None

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
            "nature": self.nature,
            "track_id": self.track_id,
            "sku_id": self.sku_id,
            "physical_identifier": self.physical_identifier,
            "physical_identity_type": self.physical_identity_type,
            "truck_id": self.truck_id,
            "worker_id": self.worker_id,
            "container_id": self.container_id,
            "bin_id": self.bin_id
        }


@dataclass
class MaterialTraceRecord:
    """
    Material-centric history dossier (Section 3).
    Maintains complete observable lifecycle for a specific material or track.
    Distinguishes:
    1. Physical material instance
    2. Container/package/box/pallet holding material
    3. SKU/material master identity
    4. Temporary camera track ID
    5. Physical identity evidence such as barcode/QR/OCR
    """
    material_id: str
    material_class: str = "BOX"
    identity_status: str = "UNIDENTIFIED"  # UNIDENTIFIED, UNREGISTERED, VALIDATED, AMBIGUOUS, CONFLICT
    traceability_status: str = MaterialTraceStatus.OBSERVED
    traceability_level: str = TraceabilityLevel.TRACK_LEVEL

    first_seen: str = ""
    last_seen: str = ""

    current_location: Optional[Dict[str, Any]] = None
    last_verified_location: Optional[Dict[str, Any]] = None
    previous_locations: List[Dict[str, Any]] = field(default_factory=list)
    location_confidence: float = 0.0
    unresolved_destination: bool = True

    source: Optional[Dict[str, Any]] = None        # Established from confirmed truck/dock association
    destination: Optional[Dict[str, Any]] = None   # Established from confirmed bin association

    # Part 11: Container/Package/Pallet Distinction
    container_id: Optional[str] = None
    container_history: List[Dict[str, Any]] = field(default_factory=list)
    contained_materials: List[str] = field(default_factory=list)
    is_container: bool = False

    # Part 11: SKU & Physical Identity Evidence Distinction
    sku_id: Optional[str] = None
    sku_name: Optional[str] = None
    physical_identifier: Optional[str] = None
    physical_identity_type: Optional[str] = None  # BARCODE, QR, OCR

    # Quantity & UOM (Strictly explicit/manifest only; NEVER detection counts)
    quantity: Optional[float] = None
    uom: Optional[str] = None

    # Conflict preservation lists (Section 19 & Part 11)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    is_ambiguous: bool = False
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
        dossier_summary = {
            "material_id": self.material_id,
            "material_class": self.material_class,
            "is_container": self.is_container,
            "sku_id": self.sku_id,
            "sku_name": self.sku_name,
            "identification_method": self.physical_identity_type or ("TRACK_ONLY" if not self.physical_identifier else "OPTICAL_ID"),
            "physical_identifier": self.physical_identifier,
            "identity_status": self.identity_status,
            "origin_source": self.source.get("identity_id") if self.source else None,
            "associated_truck": (self.source.get("truck_id") or self.source.get("identity_id")) if self.source else (self.associated_trucks[0].get("identity_id") if self.associated_trucks else None),
            "gate_pass_id": self.source.get("gate_pass_id") if self.source else None,
            "po_number": self.source.get("po_number") if self.source else None,
            "dock_unloading_event": self.source.get("dock_event_id") if self.source else None,
            "zones_traversed": [z.get("zone_code") for z in self.zone_history if z.get("zone_code")],
            "current_container": self.container_id,
            "contained_materials": list(self.contained_materials),
            "associated_workers": [w.get("identity_id") for w in self.associated_workers if w.get("identity_id")],
            "stored_bin": self.destination.get("identity_id") if self.destination else None,
            "current_location": self.current_location,
            "last_verified_location": self.last_verified_location,
            "total_movement_events": len(self.timeline),
            "has_conflicts": len(self.conflicts) > 0 or len(self.candidate_sources) > 1 or len(self.candidate_destinations) > 1 or self.identity_status in ("AMBIGUOUS", "CONFLICT"),
            "conflicts": self.conflicts,
            "traceability_level": self.traceability_level,
            "traceability_status": self.traceability_status,
            "quantity": self.quantity,
            "uom": self.uom
        }

        # Build wms_references for UI compatibility
        wms_delivery = self.source.get("expected_delivery") if self.source else None
        if not wms_delivery and self.source and self.source.get("po_number"):
            wms_delivery = {"po_number": self.source.get("po_number"), "vendor": self.source.get("vendor")}

        wms_gp = None
        if self.source and self.source.get("gate_pass_id"):
            wms_gp = {
                "id": self.source.get("gate_pass_id"),
                "plate": self.source.get("truck_plate") or self.source.get("identity_id"),
                "dock": self.source.get("assigned_dock")
            }

        wms_refs = {
            "sku": {"sku_id": self.sku_id or self.material_id, "name": self.sku_name or self.material_id},
            "delivery": wms_delivery,
            "gate_pass": wms_gp,
            "truck_plate": self.source.get("truck_plate") if self.source else None,
            "worker": self.associated_workers[0] if self.associated_workers else None,
            "bin": {"bin_id": self.destination.get("identity_id")} if self.destination else None,
            "putaway_evidence": {
                "status": "OBSERVED_AT_BIN" if self.destination else ("IN_TRANSIT" if self.traceability_status == MaterialTraceStatus.IN_TRANSIT else "AT_ZONE"),
                "confidence": self.location_confidence
            }
        }

        return {
            "material_id": self.material_id,
            "material_class": self.material_class,
            "is_container": self.is_container,
            "identity_status": self.identity_status,
            "traceability_status": self.traceability_status,
            "traceability_level": self.traceability_level,
            "sku_id": self.sku_id,
            "sku_name": self.sku_name,
            "physical_identifier": self.physical_identifier,
            "physical_identity_type": self.physical_identity_type,
            "container_id": self.container_id,
            "container_history": self.container_history,
            "contained_materials": self.contained_materials,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "current_location": self.current_location,
            "last_verified_location": self.last_verified_location,
            "previous_locations": self.previous_locations,
            "location_confidence": self.location_confidence,
            "unresolved_destination": self.unresolved_destination,
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
            "camera_tracks": self.camera_tracks,
            "conflicts": self.conflicts,
            "is_ambiguous": self.is_ambiguous,
            "quantity": self.quantity,
            "uom": self.uom,
            "dossier_summary": dossier_summary,
            "wms_references": wms_refs
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
        1. If explicit physical material identifier is provided (material_id, material_instance_id), uses that.
        2. If identity status is AMBIGUOUS or CONFLICT, generates a quarantined track key to prevent
           unifying or corrupting verified tracks across cameras.
        3. If optical physical identity (barcode/QR/OCR) is validated/identified, uses that physical identifier.
        4. If only generic SKU is provided (without physical barcode) or object is unidentified,
           generates camera-scoped track key (e.g. 'TRACK_CAM-001_17') to ensure strict track isolation
           and prevent merging separate physical materials merely because their SKU is identical.
        """
        mat_id = primary_obj.get("material_id") or primary_obj.get("material_instance_id")
        if mat_id:
            return str(mat_id)

        identity_id = primary_obj.get("identity_id")
        identity_status = primary_obj.get("identity_status", "UNIDENTIFIED")
        identity_type = str(primary_obj.get("identity_type") or primary_obj.get("source") or "").upper()
        track_id = primary_obj.get("track_id")
        is_sku_only = primary_obj.get("is_sku_only", False)

        # 2. Conflicting or ambiguous identities: Quarantine per camera track to prevent false merges
        if identity_status in ("AMBIGUOUS", "CONFLICT"):
            return f"{identity_status}_{camera_id}_{track_id}"

        # 3. Explicit physical identifier (barcode, QR, serial tag, or legacy Box ID like B104)
        if identity_id and identity_status in ("VALIDATED", "UNREGISTERED", "IDENTIFIED"):
            if not is_sku_only:
                return str(identity_id)

        # 4. Fallback to isolated track key
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
        identity_id = primary_obj.get("identity_id") or primary_obj.get("material_id")
        identity_status = primary_obj.get("identity_status", "UNIDENTIFIED")
        identity_type = primary_obj.get("identity_type") or primary_obj.get("source")
        physical_id = primary_obj.get("physical_identifier") or primary_obj.get("barcode") or primary_obj.get("qr_code")
        if not physical_id and str(identity_type).upper() in ("BARCODE", "QR", "OCR"):
            physical_id = identity_id
        if not identity_id:
            identity_id = physical_id

        sku = primary_obj.get("sku") or primary_obj.get("sku_id")
        sku_name = primary_obj.get("sku_name") or primary_obj.get("name")
        qty = primary_obj.get("quantity") or primary_obj.get("qty")
        uom = primary_obj.get("uom")
        container_id = primary_obj.get("container_id")
        cls_code = primary_obj.get("class_code", "BOX")
        is_container = cls_code in ("CONTAINER", "PALLET", "CRATE", "TRAY")

        if material_key in self.materials:
            record = self.materials[material_key]
            record.last_seen = timestamp
            if (identity_id or physical_id) and identity_status == "VALIDATED":
                record.identity_status = "VALIDATED"
                record.traceability_level = TraceabilityLevel.VALIDATED_REAL_WORLD
                if record.traceability_status == MaterialTraceStatus.OBSERVED:
                    record.traceability_status = MaterialTraceStatus.VALIDATED
            elif (identity_id or physical_id) and record.identity_status in ("UNIDENTIFIED", "OBSERVED"):
                record.identity_status = identity_status
                if record.traceability_level == TraceabilityLevel.TRACK_LEVEL:
                    record.traceability_level = TraceabilityLevel.IDENTIFIED

            if identity_status in ("AMBIGUOUS", "CONFLICT"):
                record.identity_status = identity_status
                record.is_ambiguous = True
                conflict_entry = {
                    "type": f"IDENTITY_{identity_status}",
                    "details": primary_obj,
                    "timestamp": timestamp,
                    "camera_id": camera_id
                }
                if not any(c.get("timestamp") == timestamp for c in record.conflicts):
                    record.conflicts.append(conflict_entry)
                    if len(record.conflicts) > self.config.max_conflicts:
                        record.conflicts.pop(0)

            if cls_code:
                record.material_class = cls_code
                if is_container:
                    record.is_container = True
            if sku and not record.sku_id:
                record.sku_id = str(sku)
            if sku_name and not record.sku_name:
                record.sku_name = str(sku_name)
            if physical_id and not record.physical_identifier:
                record.physical_identifier = str(physical_id)
            if identity_type and not record.physical_identity_type:
                record.physical_identity_type = str(identity_type).upper()
            if qty is not None and record.quantity is None:
                record.quantity = float(qty)
            if uom and record.uom is None:
                record.uom = str(uom)
            if container_id and not record.container_id:
                record.container_id = str(container_id)

            return record

        # Bounded memory: If exceeding max_materials, evict oldest material
        if len(self.materials) >= self.config.max_materials:
            oldest_key = min(self.materials.keys(), key=lambda k: self.materials[k].last_seen or "")
            del self.materials[oldest_key]
            # Clean up track mappings
            self.track_to_material = {k: v for k, v in self.track_to_material.items() if v != oldest_key}
            logger.info("Evicted oldest material trace '%s' due to memory bounding.", oldest_key)

        # Determine level and validation status
        if (identity_id or physical_id) and identity_status == "VALIDATED":
            t_level = TraceabilityLevel.VALIDATED_REAL_WORLD
            t_status = MaterialTraceStatus.VALIDATED
            mat_id = str(primary_obj.get("material_id") or identity_id or material_key)
        elif (identity_id or physical_id) and identity_status not in ("AMBIGUOUS", "CONFLICT", "UNIDENTIFIED"):
            t_level = TraceabilityLevel.IDENTIFIED
            t_status = MaterialTraceStatus.IDENTIFIED
            mat_id = str(primary_obj.get("material_id") or identity_id or material_key)
        else:
            t_level = TraceabilityLevel.TRACK_LEVEL
            t_status = MaterialTraceStatus.OBSERVED
            mat_id = str(primary_obj.get("material_id") or material_key)

        record = MaterialTraceRecord(
            material_id=mat_id,
            material_class=cls_code,
            is_container=is_container,
            identity_status=identity_status,
            traceability_status=t_status,
            traceability_level=t_level,
            sku_id=str(sku) if sku else None,
            sku_name=str(sku_name) if sku_name else None,
            physical_identifier=str(physical_id) if physical_id else (str(identity_id) if str(identity_type).upper() in ("BARCODE", "QR", "OCR") else None),
            physical_identity_type=str(identity_type).upper() if identity_type else None,
            container_id=str(container_id) if container_id else None,
            quantity=float(qty) if qty is not None else None,
            uom=str(uom) if uom else None,
            first_seen=timestamp,
            last_seen=timestamp
        )

        if identity_status in ("AMBIGUOUS", "CONFLICT"):
            record.is_ambiguous = True
            record.conflicts.append({
                "type": f"IDENTITY_{identity_status}",
                "details": primary_obj,
                "timestamp": timestamp,
                "camera_id": camera_id
            })

        track_id = primary_obj.get("track_id")
        if track_id is not None:
            record.camera_tracks[camera_id] = track_id
            self.track_to_material[f"{camera_id}_{track_id}"] = mat_id

        self.materials[mat_id] = record
        return record

    def ingest_movement_event(self, event: Union[MovementEvent, Dict[str, Any]]) -> Optional[MaterialTraceEvent]:
        """
        Core ingestion pipeline (Section 13 & Part 11).
        Consumes Movement Events, performs deduplication,
        updates material state and relationships, maintains container and verified locations,
        and appends a chronological timeline record.
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

        if not event_id or not event_type or not primary_obj:
            logger.warning("Rejected malformed movement event payload: %s", evt_dict)
            return None

        # Dock-unloading evidence is recorded in timeline only once sustained (ACTIVE/COMPLETED).
        # CANDIDATE evidence must not consume the event_id dedup slot.
        if event_type in ("BOX_UNLOADED_AT_DOCK", "MATERIAL_UNLOADED_AT_DOCK") and event_state == "CANDIDATE":
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
        if record.identity_status == "VALIDATED" or evt_dict.get("event_level") == "VALIDATED_REAL_WORLD":
            trace_level = TraceabilityLevel.VALIDATED_REAL_WORLD
            record.traceability_level = TraceabilityLevel.VALIDATED_REAL_WORLD
            nature = "VALIDATED"
        elif record.identity_status in ("IDENTIFIED", "UNREGISTERED"):
            trace_level = TraceabilityLevel.IDENTIFIED
            if record.traceability_level == TraceabilityLevel.TRACK_LEVEL:
                record.traceability_level = TraceabilityLevel.IDENTIFIED
            nature = "OBSERVED"
        else:
            trace_level = record.traceability_level or TraceabilityLevel.TRACK_LEVEL
            nature = "OBSERVED"

        # Construct MaterialTraceEvent with Part 11 enrichments
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
            nature=nature,
            track_id=track_id,
            sku_id=record.sku_id,
            physical_identifier=record.physical_identifier,
            physical_identity_type=record.physical_identity_type
        )

        # --------------------------------------------------------------------
        # PROCESS BY EVENT TYPE
        # --------------------------------------------------------------------

        # 1. ZONE ENTRY & STAGE MILESTONES
        if event_type in (
            EventType.BOX_ENTERED_ZONE, "BOX_ENTERED_ZONE",
            EventType.MATERIAL_ENTERED_ZONE, "MATERIAL_ENTERED_ZONE",
            EventType.MATERIAL_MOVED_TO_SORTING, "MATERIAL_MOVED_TO_SORTING",
            EventType.MATERIAL_ENTERED_STAGING, "MATERIAL_ENTERED_STAGING",
            EventType.MATERIAL_DISPATCHED, "MATERIAL_DISPATCHED"
        ):
            if zone:
                # Track previous locations
                if record.current_location and record.current_location.get("zone_code") != zone.get("zone_code"):
                    prev_loc = dict(record.current_location)
                    prev_loc["exit_timestamp"] = timestamp
                    record.previous_locations.append(prev_loc)
                    if len(record.previous_locations) > self.config.max_previous_locations:
                        record.previous_locations.pop(0)

                record.current_location = {
                    "camera_id": camera_id,
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "zone_id": zone.get("zone_id"),
                    "entry_timestamp": timestamp
                }
                record.location_confidence = max(record.location_confidence, confidence)

                # Check for zone re-entry
                is_re_entry = any(zh.get("zone_code") == zone.get("zone_code") for zh in record.zone_history)
                zone_entry = {
                    "transition": "RE_ENTER" if is_re_entry else "ENTER",
                    "stage": evt_dict.get("stage") or evt_dict.get("warehouse_stage"),
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "camera_id": camera_id,
                    "timestamp": timestamp,
                    "event_id": event_id
                }
                record.zone_history.append(zone_entry)
                if len(record.zone_history) > self.config.max_zone_history:
                    record.zone_history.pop(0)

                # Update verified location if identity is validated
                if record.identity_status in ("VALIDATED", "IDENTIFIED") and record.physical_identifier:
                    record.last_verified_location = {
                        "camera_id": camera_id,
                        "zone_code": zone.get("zone_code"),
                        "timestamp": timestamp,
                        "verification_method": record.physical_identity_type or "OPTICAL_IDENTITY",
                        "evidence": record.physical_identifier,
                        "confidence": confidence or 0.95
                    }

                if event_type in (EventType.MATERIAL_DISPATCHED, "MATERIAL_DISPATCHED"):
                    record.traceability_status = MaterialTraceStatus.COMPLETED
                else:
                    record.traceability_status = MaterialTraceStatus.AT_ZONE

        # 2. ZONE EXIT
        elif event_type in (
            EventType.BOX_EXITED_ZONE, "BOX_EXITED_ZONE",
            EventType.MATERIAL_EXITED_ZONE, "MATERIAL_EXITED_ZONE"
        ):
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
        elif event_type in (
            EventType.BOX_ASSOCIATED_WITH_TRUCK, "BOX_ASSOCIATED_WITH_TRUCK",
            EventType.MATERIAL_ASSOCIATED_WITH_TRUCK, "MATERIAL_ASSOCIATED_WITH_TRUCK"
        ):
            truck_identity = secondary_obj.get("identity_id") if secondary_obj else None
            truck_info = {
                "type": "TRUCK",
                "identity_id": truck_identity,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }
            trace_evt.truck_id = str(truck_identity) if truck_identity else None

            # Enrich source information using read-only lookup from DB (Gate Pass / PO)
            if truck_identity:
                try:
                    from db import get_db
                    conn = get_db()
                    try:
                        gp = conn.execute("SELECT * FROM gate_passes WHERE UPPER(id) = ? OR UPPER(plate) = ?",
                                          (str(truck_identity).upper(), str(truck_identity).upper())).fetchone()
                        if gp:
                            truck_info["gate_pass_id"] = gp["id"]
                            truck_info["truck_plate"] = gp["plate"]
                            truck_info["po_number"] = gp.get("po_number")
                            truck_info["vendor"] = gp.get("vendor")
                            truck_info["assigned_dock"] = gp.get("dock")
                            if gp.get("po_number"):
                                ed = conn.execute("SELECT * FROM expected_deliveries WHERE po_number = ?", (gp["po_number"],)).fetchone()
                                if ed:
                                    truck_info["expected_delivery"] = {
                                        "po_number": ed["po_number"],
                                        "expected_date": ed.get("expected_date"),
                                        "vendor": ed.get("vendor")
                                    }
                    finally:
                        conn.close()
                except Exception as e:
                    logger.debug("Read-only truck lookup ignored: %s", e)

            # Avoid duplicate association entries
            if not any(t.get("event_id") == event_id for t in record.associated_trucks):
                record.associated_trucks.append(truck_info)

            # SOURCE DERIVATION & CONFLICT PRESERVATION (Sections 7 & 19)
            if record.source is None:
                record.source = truck_info
                record.candidate_sources.append(truck_info)
            else:
                existing_id = record.source.get("identity_id") or record.source.get("track_id")
                new_id = truck_info.get("identity_id") or truck_info.get("track_id")
                if existing_id != new_id:
                    if not any(c.get("identity_id") == new_id for c in record.candidate_sources):
                        record.candidate_sources.append(truck_info)
                    conflict_rec = {
                        "type": "SOURCE_CONFLICT",
                        "existing_source": existing_id,
                        "conflicting_source": new_id,
                        "timestamp": timestamp,
                        "event_id": event_id
                    }
                    record.conflicts.append(conflict_rec)
                    if len(record.conflicts) > self.config.max_conflicts:
                        record.conflicts.pop(0)
                    logger.info("Preserved conflicting candidate truck source for material '%s': %s", record.material_id, new_id)

            record.traceability_status = MaterialTraceStatus.ASSOCIATED

        # 4. WORKER ASSOCIATION
        elif event_type in (
            EventType.BOX_ASSOCIATED_WITH_WORKER, "BOX_ASSOCIATED_WITH_WORKER",
            EventType.MATERIAL_ASSOCIATED_WITH_WORKER, "MATERIAL_ASSOCIATED_WITH_WORKER"
        ):
            worker_id_val = secondary_obj.get("identity_id") if secondary_obj else None
            worker_info = {
                "type": "WORKER",
                "identity_id": worker_id_val,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }
            trace_evt.worker_id = str(worker_id_val) if worker_id_val else None

            if not any(w.get("event_id") == event_id for w in record.associated_workers):
                record.associated_workers.append(worker_info)

            record.traceability_status = MaterialTraceStatus.ASSOCIATED

        # 5. BIN ASSOCIATION & STORAGE (DESTINATION DERIVATION)
        elif event_type in (
            EventType.BOX_ASSOCIATED_WITH_BIN, "BOX_ASSOCIATED_WITH_BIN",
            EventType.MATERIAL_ASSOCIATED_WITH_BIN, "MATERIAL_ASSOCIATED_WITH_BIN",
            EventType.MATERIAL_STORED_IN_BIN, "MATERIAL_STORED_IN_BIN"
        ) or (secondary_obj and secondary_obj.get("class_code") == "BIN"):
            if zone:
                if record.current_location and record.current_location.get("zone_code") != zone.get("zone_code"):
                    prev_loc = dict(record.current_location)
                    prev_loc["exit_timestamp"] = timestamp
                    record.previous_locations.append(prev_loc)
                    if len(record.previous_locations) > self.config.max_previous_locations:
                        record.previous_locations.pop(0)

                record.current_location = {
                    "camera_id": camera_id,
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "zone_id": zone.get("zone_id"),
                    "entry_timestamp": timestamp
                }
                record.location_confidence = max(record.location_confidence, confidence)

                is_re_entry = any(zh.get("zone_code") == zone.get("zone_code") for zh in record.zone_history)
                zone_entry = {
                    "transition": "RE_ENTER" if is_re_entry else "ENTER",
                    "stage": evt_dict.get("stage") or evt_dict.get("warehouse_stage"),
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "camera_id": camera_id,
                    "timestamp": timestamp,
                    "event_id": event_id
                }
                record.zone_history.append(zone_entry)
                if len(record.zone_history) > self.config.max_zone_history:
                    record.zone_history.pop(0)

            bin_id_val = secondary_obj.get("identity_id") if secondary_obj else None
            bin_info = {
                "type": "BIN",
                "identity_id": bin_id_val,
                "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED") if secondary_obj else "UNIDENTIFIED",
                "track_id": secondary_obj.get("track_id") if secondary_obj else None,
                "event_id": event_id,
                "score": confidence,
                "timestamp": timestamp,
                "zone": zone.get("zone_code") if zone else None
            }
            trace_evt.bin_id = str(bin_id_val) if bin_id_val else None

            if not any(b.get("event_id") == event_id for b in record.associated_bins):
                record.associated_bins.append(bin_info)

            # DESTINATION DERIVATION & CONFLICT PRESERVATION (Sections 8 & 19)
            if record.destination is None:
                record.destination = bin_info
                record.candidate_destinations.append(bin_info)
                record.unresolved_destination = False
            else:
                existing_bin = record.destination.get("identity_id") or record.destination.get("track_id")
                new_bin = bin_info.get("identity_id") or bin_info.get("track_id")
                if existing_bin != new_bin:
                    if not any(c.get("identity_id") == new_bin for c in record.candidate_destinations):
                        record.candidate_destinations.append(bin_info)
                    conflict_rec = {
                        "type": "DESTINATION_CONFLICT",
                        "existing_destination": existing_bin,
                        "conflicting_destination": new_bin,
                        "timestamp": timestamp,
                        "event_id": event_id
                    }
                    record.conflicts.append(conflict_rec)
                    if len(record.conflicts) > self.config.max_conflicts:
                        record.conflicts.pop(0)
                    logger.info("Preserved conflicting candidate bin destination for material '%s': %s", record.material_id, new_bin)

            # Update verified location for storage
            record.last_verified_location = {
                "camera_id": camera_id,
                "zone_code": zone.get("zone_code") if zone else "BIN-AREA",
                "bin_id": bin_id_val,
                "timestamp": timestamp,
                "verification_method": "BIN_ASSOCIATION",
                "confidence": confidence
            }

            record.traceability_status = MaterialTraceStatus.DESTINATION_OBSERVED

        # 6. CONTAINER ASSOCIATION (Part 11)
        elif event_type in (
            EventType.MATERIAL_ASSOCIATED_WITH_CONTAINER, "MATERIAL_ASSOCIATED_WITH_CONTAINER"
        ):
            container_id_val = secondary_obj.get("identity_id") if secondary_obj else (
                f"CONT_{camera_id}_{secondary_obj.get('track_id')}" if (secondary_obj and secondary_obj.get("track_id") is not None) else None
            )
            trace_evt.container_id = str(container_id_val) if container_id_val else None

            if container_id_val:
                cid_str = str(container_id_val)
                # Check for container transfer vs new assignment
                if record.container_id and record.container_id != cid_str:
                    transfer_info = {
                        "transition": "TRANSFER",
                        "from_container": record.container_id,
                        "to_container": cid_str,
                        "timestamp": timestamp,
                        "event_id": event_id,
                        "confidence": confidence,
                        "zone": zone.get("zone_code") if zone else None
                    }
                    record.container_history.append(transfer_info)
                    if len(record.container_history) > self.config.max_container_history:
                        record.container_history.pop(0)

                    # Update former container record if tracked in memory
                    if record.container_id in self.materials:
                        prev_cont = self.materials[record.container_id]
                        if record.material_id in prev_cont.contained_materials:
                            prev_cont.contained_materials.remove(record.material_id)
                else:
                    assign_info = {
                        "transition": "ASSIGN",
                        "container_id": cid_str,
                        "timestamp": timestamp,
                        "event_id": event_id,
                        "confidence": confidence,
                        "zone": zone.get("zone_code") if zone else None
                    }
                    record.container_history.append(assign_info)
                    if len(record.container_history) > self.config.max_container_history:
                        record.container_history.pop(0)

                record.container_id = cid_str

                # Update target container record if tracked in memory
                if cid_str in self.materials:
                    target_cont = self.materials[cid_str]
                    target_cont.is_container = True
                    if record.material_id not in target_cont.contained_materials:
                        target_cont.contained_materials.append(record.material_id)

            record.traceability_status = MaterialTraceStatus.ASSOCIATED

        # 7. OBSERVATION EVENTS (BOX_NEAR_* / MATERIAL_NEAR_*)
        elif event_type in (
            EventType.BOX_NEAR_TRUCK, EventType.BOX_NEAR_WORKER, EventType.BOX_NEAR_BIN,
            "BOX_NEAR_TRUCK", "BOX_NEAR_WORKER", "BOX_NEAR_BIN",
            EventType.MATERIAL_NEAR_TRUCK, EventType.MATERIAL_NEAR_WORKER,
            EventType.MATERIAL_NEAR_BIN, EventType.MATERIAL_NEAR_CONTAINER,
            "MATERIAL_NEAR_TRUCK", "MATERIAL_NEAR_WORKER", "MATERIAL_NEAR_BIN", "MATERIAL_NEAR_CONTAINER"
        ):
            trace_evt.nature = "OBSERVED"
            # Does not force confirmed source/destination

        # 8. DOCK UNLOADING EVIDENCE (Part 4)
        elif event_type in (
            EventType.BOX_UNLOADED_AT_DOCK, "BOX_UNLOADED_AT_DOCK",
            EventType.MATERIAL_UNLOADED_AT_DOCK, "MATERIAL_UNLOADED_AT_DOCK"
        ):
            trace_evt.nature = "UNLOADING_EVIDENCE"
            if secondary_obj:
                truck_info = {
                    "type": "TRUCK",
                    "identity_id": secondary_obj.get("identity_id"),
                    "validation_status": secondary_obj.get("identity_status", "UNIDENTIFIED"),
                    "track_id": secondary_obj.get("track_id"),
                    "event_id": event_id,
                    "score": confidence,
                    "timestamp": timestamp,
                    "zone": zone.get("zone_code") if zone else None
                }
                trace_evt.truck_id = str(secondary_obj.get("identity_id")) if secondary_obj.get("identity_id") else None

                if not any(t.get("event_id") == event_id for t in record.associated_trucks):
                    record.associated_trucks.append(truck_info)
                if record.source is None:
                    record.source = truck_info
                    record.candidate_sources.append(truck_info)

            # Record unloading milestone in source
            if record.source:
                record.source["dock_event_id"] = event_id
                record.source["dock_zone"] = zone.get("zone_code") if zone else None
                record.source["dock_timestamp"] = timestamp

            if zone:
                record.current_location = {
                    "camera_id": camera_id,
                    "zone_code": zone.get("zone_code"),
                    "zone_name": zone.get("zone_name"),
                    "zone_id": zone.get("zone_id")
                }
            record.traceability_status = MaterialTraceStatus.AT_ZONE

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
                "is_container": rec.is_container,
                "identity_status": rec.identity_status,
                "traceability_status": rec.traceability_status,
                "traceability_level": rec.traceability_level,
                "sku_id": rec.sku_id,
                "container_id": rec.container_id,
                "physical_identifier": rec.physical_identifier,
                "first_seen": rec.first_seen,
                "last_seen": rec.last_seen,
                "source": rec.source.get("identity_id") if rec.source else None,
                "current_zone": rec.current_location.get("zone_code") if rec.current_location else None,
                "destination": rec.destination.get("identity_id") if rec.destination else None,
                "last_verified_location": rec.last_verified_location.get("zone_code") if rec.last_verified_location else None,
                "has_conflicts": len(rec.conflicts) > 0 or rec.identity_status in ("AMBIGUOUS", "CONFLICT"),
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
        Executes deterministic synthetic scenarios (Section 27 & Part 11).
        Supports:
        - 'complete_trace': Legacy 7-frame box sequence (B104)
        - 'automotive_traceability_flow': 8-frame automotive material sequence with container transfer and verified bin
        """
        self.reset()
        t0 = time.perf_counter()

        camera_id = "CAM-001"

        if sequence_name in ("automotive_traceability_flow", "automotive_trace"):
            target_id = "MAT-AUTO-GL-01"
            timestamps = [
                "2026-10-02T10:02:10Z",
                "2026-10-02T10:02:15Z",
                "2026-10-02T10:02:22Z",
                "2026-10-02T10:02:30Z",
                "2026-10-02T10:02:45Z",
                "2026-10-02T10:03:30Z",
                "2026-10-02T10:04:15Z",
                "2026-10-02T10:05:00Z"
            ]
            frames_data = [
                # Frame 1: Yard observation outside dock
                {
                    "event_id": "EVT-AUTO-001",
                    "event_type": "MATERIAL_ENTERED_ZONE",
                    "camera_id": camera_id,
                    "timestamp": timestamps[0],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "zone": {"zone_id": 1, "zone_code": "YARD-01", "zone_name": "Inbound Yard"},
                    "confidence": 0.88,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 2: Enters Dock 01
                {
                    "event_id": "EVT-AUTO-002",
                    "event_type": "MATERIAL_ENTERED_ZONE",
                    "camera_id": camera_id,
                    "timestamp": timestamps[1],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.95,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 3: Associated with Truck GP-1000 (Source established)
                {
                    "event_id": "EVT-AUTO-003",
                    "event_type": "MATERIAL_ASSOCIATED_WITH_TRUCK",
                    "camera_id": camera_id,
                    "timestamp": timestamps[2],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.94,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 4: Unloaded at Dock
                {
                    "event_id": "EVT-AUTO-004",
                    "event_type": "MATERIAL_UNLOADED_AT_DOCK",
                    "camera_id": camera_id,
                    "timestamp": timestamps[3],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "secondary_object": {"track_id": 4, "class_code": "TRUCK", "identity_id": "GP-1000", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.95,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 5: Associated with Container CONT-01
                {
                    "event_id": "EVT-AUTO-005",
                    "event_type": "MATERIAL_ASSOCIATED_WITH_CONTAINER",
                    "camera_id": camera_id,
                    "timestamp": timestamps[4],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "secondary_object": {"track_id": 50, "class_code": "CONTAINER", "identity_id": "CONT-01", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 3, "zone_code": "DOCK-01", "zone_name": "Dock 01"},
                    "confidence": 0.92,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 6: Moved to Sorting
                {
                    "event_id": "EVT-AUTO-006",
                    "event_type": "MATERIAL_MOVED_TO_SORTING",
                    "camera_id": camera_id,
                    "timestamp": timestamps[5],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "zone": {"zone_id": 5, "zone_code": "SORT-01", "zone_name": "Sorting Conveyor 1"},
                    "confidence": 0.93,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 7: Transferred to Pallet PALLET-05 (Container Transfer)
                {
                    "event_id": "EVT-AUTO-007",
                    "event_type": "MATERIAL_ASSOCIATED_WITH_CONTAINER",
                    "camera_id": camera_id,
                    "timestamp": timestamps[6],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "secondary_object": {"track_id": 55, "class_code": "PALLET", "identity_id": "PALLET-05", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 6, "zone_code": "STG-01", "zone_name": "Staging Buffer A"},
                    "confidence": 0.96,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                },
                # Frame 8: Stored in Bin BIN-A101
                {
                    "event_id": "EVT-AUTO-008",
                    "event_type": "MATERIAL_STORED_IN_BIN",
                    "camera_id": camera_id,
                    "timestamp": timestamps[7],
                    "primary_object": {
                        "track_id": 201,
                        "class_code": "GLASS",
                        "material_id": target_id,
                        "sku": "AUTO-GLASS-01",
                        "physical_identifier": "BC-GL-8801",
                        "identity_type": "BARCODE",
                        "identity_status": "VALIDATED"
                    },
                    "secondary_object": {"track_id": 99, "class_code": "BIN", "identity_id": "BIN-A101", "identity_status": "VALIDATED"},
                    "zone": {"zone_id": 8, "zone_code": "BIN-AREA", "zone_name": "Storage Bin Area A"},
                    "confidence": 0.97,
                    "status": "ACTIVE",
                    "event_level": "VALIDATED_REAL_WORLD"
                }
            ]
        else:
            # Default sequence: B104 legacy 7-frame trace
            target_id = "B104"
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

        material_dossier = self.get_material(target_id)

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
        bounding boxes, zones, and traceability badges (Section 37 & Part 11).
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

            # Box/Container rect
            bw, bh = 140, 80
            x1, y1 = cx - bw // 2, cy - bh // 2
            x2, y2 = cx + bw // 2, cy + bh // 2

            if rec.identity_status in ("CONFLICT", "AMBIGUOUS") or rec.is_ambiguous:
                color = (0, 140, 255)
            elif rec.traceability_level == TraceabilityLevel.VALIDATED_REAL_WORLD:
                color = (0, 255, 120)
            else:
                color = (0, 200, 255)

            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            cv2.rectangle(canvas, (x1, y1 - 24), (x2, y1), color, -1)

            lbl_prefix = "CONT" if rec.is_container else rec.material_class
            cv2.putText(canvas, f"{lbl_prefix}: {mat_id}", (x1 + 6, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(canvas, f"STATUS: {rec.traceability_status}", (x1 + 6, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 230, 240), 1, cv2.LINE_AA)

            if rec.container_id:
                cv2.putText(canvas, f"IN: {rec.container_id}", (x1 + 6, y1 + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 220, 255), 1, cv2.LINE_AA)
                src_dst_y = 54
            else:
                src_dst_y = 40

            src_str = f"SRC: {rec.source.get('identity_id')}" if rec.source else "SRC: UNKNOWN"
            cv2.putText(canvas, src_str, (x1 + 6, y1 + src_dst_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (180, 190, 200), 1, cv2.LINE_AA)

            dst_str = f"DST: {rec.destination.get('identity_id')}" if rec.destination else "DST: UNKNOWN"
            cv2.putText(canvas, dst_str, (x1 + 6, y1 + src_dst_y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (180, 190, 200), 1, cv2.LINE_AA)

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
