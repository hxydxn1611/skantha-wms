"""
AI Vision & Tracking Master - Warehouse Identity Validation & Master-Data Binding Foundation
Part 8: Modular Master-Data Validation Layer for Tracked & Identified Objects.

Consumes visual identity recognition results from Part 7 and validates whether
the detected visual identifier corresponds to an authoritative WMS master-data entity.

Key Architectural Distinction:
  - VISUAL IDENTITY = What the camera actually read from visual evidence (e.g. Barcode, QR, OCR)
  - MASTER-DATA IDENTITY = What the WMS database knows about that identifier

Core Validation Statuses:
  - VALIDATED: Visual identity matched a known, active WMS master record for the detected object class.
  - UNREGISTERED: Visual identity was successfully recognized, but no matching WMS record exists.
  - AMBIGUOUS: Multiple conflicting master records matched the query.
  - MASTER_DATA_UNAVAILABLE: No suitable master table exists in the current WMS schema for the object class.
  - NOT_APPLICABLE: Visual identity is UNIDENTIFIED or in a CONFLICT state (never validate conflicting reads).

Strict Behavioral Rules:
  - READ-ONLY: Never perform INSERT, UPDATE, DELETE, or modify inventory / gate passes.
  - NO DUPLICATE TABLES: Reuse existing WMS tables (gate_passes, expected_deliveries, users, vision_zones).
  - NO SCHEMA CHANGES: Zero database schema modifications.
  - OBJECT-CLASS AWARE: A truck plate must never match a box; a box SKU must never match a truck.
  - PRESERVE PART 7: Never mutate or overwrite identity.value, source, confidence, status, or candidates.
  - SQL INJECTION SAFE: All queries use parameterized statements (?).
"""

import os
import re
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

import cv2
import numpy as np

# Import Part 7 MultiObjectIdentityService
from identity_service import (
    get_identity_service,
    MultiObjectIdentityService
)
from db import get_db

logger = logging.getLogger(__name__)


# ============================================================================
# 1. WMS MASTER DATA REGISTRY & DIAGNOSTIC INSPECTOR
# ============================================================================
class MasterDataRegistry:
    """
    Authoritative catalog of existing WMS master-data sources mapped to object classes.
    Documents existing tables and schema gaps without creating redundant tables.
    """

    SUPPORTED_CLASSES = {
        "TRUCK": {
            "available": True,
            "tables": ["gate_passes", "expected_deliveries"],
            "fields": ["plate", "id", "po_number"],
            "description": "Active inbound trucks, registered gate passes, and expected delivery vehicles"
        },
        "BOX": {
            "available": True,
            "tables": ["expected_deliveries", "gate_passes"],
            "fields": ["unloading_sheet (sku)", "po_number"],
            "description": "Inbound consignment item lines, packaging cartons, and bill-of-lading SKUs"
        },
        "WORKER": {
            "available": True,
            "tables": ["users"],
            "fields": ["username", "id"],
            "description": "Authorized warehouse personnel and system operators (passwords omitted)"
        },
        "BIN": {
            "available": True,
            "tables": ["vision_zones"],
            "fields": ["zone_code"],
            "description": "Configured warehouse storage bins, staging areas, and dock bays"
        },
        "FORKLIFT": {
            "available": False,
            "tables": None,
            "fields": [],
            "description": "No dedicated equipment/forklift master table in current WMS schema (gap documented)"
        },
        "PALLET": {
            "available": False,
            "tables": None,
            "fields": [],
            "description": "No dedicated pallet asset master table in current WMS schema (gap documented)"
        }
    }

    @classmethod
    def get_supported_classes_info(cls) -> Dict[str, Any]:
        """Return diagnostic dictionary of master-data availability across all object classes."""
        return cls.SUPPORTED_CLASSES


# ============================================================================
# 2. OBJECT-CLASS-AWARE MASTER VALIDATOR (READ-ONLY)
# ============================================================================
class WarehouseMasterValidator:
    """
    Executes parameterized, read-only SQL lookups against authoritative WMS tables
    strictly constrained by the detected object class.
    """

    @staticmethod
    def _normalize_alphanumeric(text: Optional[str]) -> str:
        """Strip delimiters, hyphens, and whitespace for canonical alphanumeric matching."""
        if not text:
            return ""
        return re.sub(r'[^A-Z0-9]', '', str(text).upper())

    @staticmethod
    def _safe_str(val: Any) -> str:
        return str(val).strip() if val is not None else ""

    def validate_truck(self, identity_val: str) -> Dict[str, Any]:
        """
        Validate TRUCK visual identity against gate_passes and expected_deliveries.
        Matches by Gate Pass ID (GP-xxxx), License Plate, or PO Number.
        """
        raw_val = self._safe_str(identity_val)
        norm_val = self._normalize_alphanumeric(raw_val)

        conn = get_db()
        try:
            # 1. Exact match on gate_passes ID, PO Number, or Plate
            rows_gp = conn.execute("""
                SELECT id, po_number, plate, vehicle_type, driver_name, vendor, dock, status, created_at
                FROM gate_passes
                WHERE UPPER(id) = ? OR UPPER(po_number) = ? OR UPPER(plate) = ?
            """, (raw_val.upper(), raw_val.upper(), raw_val.upper())).fetchall()

            # If no direct match, check canonical normalized license plate (e.g. MH-12-AB-1234 -> MH12AB1234)
            if not rows_gp and norm_val:
                all_gp = conn.execute("""
                    SELECT id, po_number, plate, vehicle_type, driver_name, vendor, dock, status, created_at
                    FROM gate_passes
                """).fetchall()
                rows_gp = [r for r in all_gp if self._normalize_alphanumeric(r['plate']) == norm_val]

            if len(rows_gp) > 1:
                return {
                    "status": "AMBIGUOUS",
                    "master_type": "TRUCK",
                    "master_id": None,
                    "display_name": None,
                    "matched_field": "plate",
                    "message": f"Multiple active gate passes ({len(rows_gp)}) matched plate '{raw_val}'.",
                    "master_record": None
                }

            if rows_gp:
                r = rows_gp[0]
                matched_field = "id" if r['id'].upper() == raw_val.upper() else (
                    "po_number" if r['po_number'] and r['po_number'].upper() == raw_val.upper() else "plate"
                )
                vendor_txt = f" - {r['vendor']}" if r['vendor'] else ""
                dock_txt = f" @ {r['dock']}" if r['dock'] else ""
                return {
                    "status": "VALIDATED",
                    "master_type": "TRUCK",
                    "master_id": r['id'],
                    "display_name": f"Gate Pass {r['id']} [Plate: {r['plate']}]{vendor_txt}{dock_txt}",
                    "matched_field": matched_field,
                    "message": f"Identity matched active truck gate pass '{r['id']}'.",
                    "master_record": {
                        "id": r['id'],
                        "po_number": r['po_number'],
                        "plate": r['plate'],
                        "driver_name": r['driver_name'],
                        "vendor": r['vendor'],
                        "dock": r['dock'],
                        "status": r['status'],
                        "created_at": r['created_at']
                    }
                }

            # 2. Check expected_deliveries pre-registration table
            rows_ed = conn.execute("""
                SELECT po_number, plate, vendor, driver_name, status, expected_date, created_at
                FROM expected_deliveries
                WHERE UPPER(po_number) = ? OR UPPER(plate) = ?
            """, (raw_val.upper(), raw_val.upper())).fetchall()

            if not rows_ed and norm_val:
                all_ed = conn.execute("""
                    SELECT po_number, plate, vendor, driver_name, status, expected_date, created_at
                    FROM expected_deliveries
                """).fetchall()
                rows_ed = [r for r in all_ed if self._normalize_alphanumeric(r['plate']) == norm_val]

            if len(rows_ed) > 1:
                return {
                    "status": "AMBIGUOUS",
                    "master_type": "EXPECTED_DELIVERY",
                    "master_id": None,
                    "display_name": None,
                    "matched_field": "plate",
                    "message": f"Multiple pre-registered deliveries ({len(rows_ed)}) matched '{raw_val}'.",
                    "master_record": None
                }

            if rows_ed:
                r = rows_ed[0]
                matched_field = "po_number" if r['po_number'].upper() == raw_val.upper() else "plate"
                vendor_txt = f" - {r['vendor']}" if r['vendor'] else ""
                return {
                    "status": "VALIDATED",
                    "master_type": "EXPECTED_DELIVERY",
                    "master_id": r['po_number'],
                    "display_name": f"Expected Delivery {r['po_number']} [Plate: {r['plate']}]{vendor_txt}",
                    "matched_field": matched_field,
                    "message": f"Identity matched pre-registered inbound delivery '{r['po_number']}'.",
                    "master_record": {
                        "po_number": r['po_number'],
                        "plate": r['plate'],
                        "vendor": r['vendor'],
                        "driver_name": r['driver_name'],
                        "status": r['status'],
                        "expected_date": r['expected_date']
                    }
                }

            # Not found in truck master
            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching WMS truck master record was found.",
                "master_record": None
            }
        finally:
            conn.close()

    def validate_box(self, identity_val: str) -> Dict[str, Any]:
        """
        Validate BOX visual identity against gate_passes and expected_deliveries unloading sheets and POs.
        Matches by SKU code or PO Number.
        """
        raw_val = self._safe_str(identity_val)
        conn = get_db()
        try:
            # 1. Look for matching SKU in active gate passes unloading_sheet JSON
            rows_gp = conn.execute("""
                SELECT id, po_number, vendor, unloading_sheet, status
                FROM gate_passes
                WHERE unloading_sheet IS NOT NULL AND unloading_sheet != ''
            """).fetchall()

            matched_skus = []
            for gp in rows_gp:
                try:
                    sheet = json.loads(gp['unloading_sheet'] or '[]')
                    for item in sheet:
                        sku = str(item.get('sku', '')).strip()
                        if sku.upper() == raw_val.upper():
                            matched_skus.append({
                                "sku": sku,
                                "description": item.get('description', 'Box / Package'),
                                "uom": item.get('uom', 'Boxes'),
                                "expected_qty": item.get('expected', 0),
                                "source": "gate_passes",
                                "source_id": gp['id'],
                                "po_number": gp['po_number'],
                                "vendor": gp['vendor']
                            })
                except Exception:
                    pass

            # 2. Look for matching SKU in expected_deliveries unloading_sheet JSON
            rows_ed = conn.execute("""
                SELECT po_number, vendor, unloading_sheet, status
                FROM expected_deliveries
                WHERE unloading_sheet IS NOT NULL AND unloading_sheet != ''
            """).fetchall()

            for ed in rows_ed:
                try:
                    sheet = json.loads(ed['unloading_sheet'] or '[]')
                    for item in sheet:
                        sku = str(item.get('sku', '')).strip()
                        if sku.upper() == raw_val.upper():
                            matched_skus.append({
                                "sku": sku,
                                "description": item.get('description', 'Box / Package'),
                                "uom": item.get('uom', 'Boxes'),
                                "expected_qty": item.get('expected', 0),
                                "source": "expected_deliveries",
                                "source_id": ed['po_number'],
                                "po_number": ed['po_number'],
                                "vendor": ed['vendor']
                            })
                except Exception:
                    pass

            if len(matched_skus) > 1:
                # Multiple shipments reference this SKU - return valid with primary match
                m = matched_skus[0]
                return {
                    "status": "VALIDATED",
                    "master_type": "BOX",
                    "master_id": m["sku"],
                    "display_name": f"Box SKU: {m['sku']} ({m['description']})",
                    "matched_field": "sku",
                    "message": f"Identity matched active shipment SKU '{m['sku']}' across {len(matched_skus)} shipments.",
                    "master_record": m
                }

            if matched_skus:
                m = matched_skus[0]
                return {
                    "status": "VALIDATED",
                    "master_type": "BOX",
                    "master_id": m["sku"],
                    "display_name": f"Box SKU: {m['sku']} ({m['description']})",
                    "matched_field": "sku",
                    "message": f"Identity matched shipment box SKU '{m['sku']}' from PO {m['po_number']}.",
                    "master_record": m
                }

            # 3. Check if box barcode matches a consignment PO number directly
            po_row = conn.execute("""
                SELECT po_number, vendor, status FROM expected_deliveries WHERE UPPER(po_number) = ?
            """, (raw_val.upper(),)).fetchone()

            if po_row:
                return {
                    "status": "VALIDATED",
                    "master_type": "BOX",
                    "master_id": po_row['po_number'],
                    "display_name": f"Consignment Box Batch [PO: {po_row['po_number']}] ({po_row['vendor'] or 'Carrier'})",
                    "matched_field": "po_number",
                    "message": f"Identity matched consignment purchase order '{po_row['po_number']}'.",
                    "master_record": {
                        "po_number": po_row['po_number'],
                        "vendor": po_row['vendor'],
                        "status": po_row['status']
                    }
                }

            # Not found in box / SKU catalog
            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching WMS master record was found in Box / SKU catalog.",
                "master_record": None
            }
        finally:
            conn.close()

    def validate_worker(self, identity_val: str) -> Dict[str, Any]:
        """
        Validate WORKER visual identity against users table.
        Security Note: Sensitive credential fields (passwords) are strictly omitted.
        """
        raw_val = self._safe_str(identity_val)
        conn = get_db()
        try:
            row = conn.execute("""
                SELECT id, username FROM users
                WHERE UPPER(username) = ? OR CAST(id AS TEXT) = ?
            """, (raw_val.upper(), raw_val)).fetchone()

            if row:
                return {
                    "status": "VALIDATED",
                    "master_type": "WORKER",
                    "master_id": str(row['id']),
                    "display_name": f"Authorized Personnel (Username: {row['username']})",
                    "matched_field": "username" if row['username'].upper() == raw_val.upper() else "id",
                    "message": f"Identity matched registered warehouse personnel '{row['username']}'.",
                    "master_record": {
                        "id": row['id'],
                        "username": row['username']
                    }
                }

            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching personnel/user was found.",
                "master_record": None
            }
        finally:
            conn.close()

    def validate_bin(self, identity_val: str) -> Dict[str, Any]:
        """
        Validate BIN visual identity against vision_zones master table.
        Matches by zone_code (e.g. BIN-A, DOCK-01, TB-01).
        """
        raw_val = self._safe_str(identity_val)
        conn = get_db()
        try:
            row = conn.execute("""
                SELECT id, zone_code, zone_name, zone_type, warehouse FROM vision_zones
                WHERE UPPER(zone_code) = ?
            """, (raw_val.upper(),)).fetchone()

            if row:
                return {
                    "status": "VALIDATED",
                    "master_type": "BIN",
                    "master_id": row['zone_code'],
                    "display_name": f"{row['zone_name']} [{row['zone_code']}]",
                    "matched_field": "zone_code",
                    "message": f"Identity matched registered warehouse zone/bin '{row['zone_code']}'.",
                    "master_record": {
                        "zone_id": row['id'],
                        "zone_code": row['zone_code'],
                        "zone_name": row['zone_name'],
                        "zone_type": row['zone_type'],
                        "warehouse": row['warehouse']
                    }
                }

            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching warehouse zone/bin was found.",
                "master_record": None
            }
        finally:
            conn.close()

    def validate_identity(
        self,
        class_code: str,
        identity_value: Optional[str],
        identity_status: str,
        identity_source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for object-class-aware master data validation.
        Enforces strict precedence and boundary conditions:
          - If identity_status == "UNIDENTIFIED" -> NOT_APPLICABLE
          - If identity_status == "CONFLICT" -> NOT_APPLICABLE
          - If identity_value is empty -> NOT_APPLICABLE
          - If class has no master table (FORKLIFT, PALLET) -> MASTER_DATA_UNAVAILABLE
          - Dispatches to class-specific validator.
        """
        # 1. Unidentified Handling
        if identity_status == "UNIDENTIFIED":
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": "No visual identity was detected on the tracked object.",
                "master_record": None
            }

        # 2. Conflict Handling
        if identity_status == "CONFLICT":
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": "Identity conflict must be resolved before master-data validation.",
                "master_record": None
            }

        # 3. Empty or null value check
        if not identity_value or not str(identity_value).strip():
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": "Visual identity value is missing or empty.",
                "master_record": None
            }

        norm_class = str(class_code).strip().upper() if class_code else "UNKNOWN"

        # 4. Classes without WMS master tables (document gaps)
        if norm_class in ("FORKLIFT", "PALLET"):
            return {
                "status": "MASTER_DATA_UNAVAILABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"No suitable WMS master-data source exists for object class '{norm_class}'.",
                "master_record": None
            }

        # 5. Object-class-aware routing
        if norm_class in ("TRUCK", "CARRIER", "VEHICLE", "LICENSE_PLATE", "LICENSE PLATE"):
            return self.validate_truck(identity_value)
        elif norm_class in ("BOX", "CARTON", "PACKAGE"):
            return self.validate_box(identity_value)
        elif norm_class in ("WORKER", "PERSONNEL", "USER"):
            return self.validate_worker(identity_value)
        elif norm_class in ("BIN", "LOCATION", "TOTE", "RACK"):
            return self.validate_bin(identity_value)
        else:
            return {
                "status": "MASTER_DATA_UNAVAILABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Object class '{norm_class}' is not mapped to any known WMS master data source.",
                "master_record": None
            }


# ============================================================================
# 3. MULTI-OBJECT VALIDATION SERVICE (PERCEPTION COORDINATOR)
# ============================================================================
class MultiObjectValidationService:
    """
    Coordinates Part 5 Detection -> Part 6 ByteTrack -> Part 7 Identity -> Part 8 Master Validation.
    Preserves camera session isolation and renders visual validation overlays.
    """

    def __init__(self):
        self.identity_service: MultiObjectIdentityService = get_identity_service()
        self.validator = WarehouseMasterValidator()
        self.registry = MasterDataRegistry()
        logger.info("MultiObjectValidationService initialized successfully.")

    def get_status(self) -> Dict[str, Any]:
        """Diagnostic status reporting master data availability and identity service health."""
        ident_status = self.identity_service.get_status()
        return {
            "status": "healthy",
            "service": "Warehouse Identity Validation & Master-Data Binding Foundation (Part 8)",
            "database_access": "READ-ONLY",
            "available_masters": self.registry.get_supported_classes_info(),
            "identity_engine": ident_status
        }

    def reset_session(self, camera_id: str) -> bool:
        """Reset in-memory identity and tracking state for a camera."""
        return self.identity_service.reset_session(camera_id)

    def reset_all(self):
        """Reset all camera tracking and identity sessions."""
        self.identity_service.reset_all()

    def validate_tracks(
        self,
        tracks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Enrich Part 7 tracks with Part 8 master-data validation records.
        Preserves all Part 7 identity fields without mutation.
        Returns: (validated_tracks, validation_latency_ms)
        """
        if not tracks:
            return [], 0.0

        t_val_start = time.perf_counter()

        for t in tracks:
            class_code = t.get("class_code", "UNKNOWN")
            identity_info = t.get("identity", {})
            identity_status = identity_info.get("status", "UNIDENTIFIED")
            identity_value = identity_info.get("value")
            identity_source = identity_info.get("source")

            # Execute object-class-aware validation
            val_res = self.validator.validate_identity(
                class_code=class_code,
                identity_value=identity_value,
                identity_status=identity_status,
                identity_source=identity_source
            )

            # Attach validation structure to track
            t["validation"] = val_res

        val_ms = (time.perf_counter() - t_val_start) * 1000
        return tracks, round(val_ms, 2)

    def process_frame(
        self,
        frame_input: Union[np.ndarray, str, bytes],
        camera_id: str = "CAM-001",
        conf_threshold: Optional[float] = None,
        roi_polygon: Optional[List[Dict[str, float]]] = None,
        roi_zone_code: Optional[str] = None,
        enable_barcode_qr: bool = True,
        enable_ocr: bool = True,
        crop_padding: float = 0.05
    ) -> Dict[str, Any]:
        """
        End-to-End Pipeline:
        Frame -> Part 5 Detection -> Part 6 ByteTrack -> Part 7 Identity -> Part 8 Master Validation -> Visual Overlay.
        """
        t_total_start = time.perf_counter()

        # Step 1-3: Run Part 5 Detection, Part 6 Tracking, and Part 7 Identity Recognition
        ident_res = self.identity_service.process_frame(
            frame_input=frame_input,
            camera_id=camera_id,
            conf_threshold=conf_threshold,
            roi_polygon=roi_polygon,
            roi_zone_code=roi_zone_code,
            enable_barcode_qr=enable_barcode_qr,
            enable_ocr=enable_ocr,
            crop_padding=crop_padding
        )

        if not ident_res.get("success", False):
            return ident_res

        tracks = ident_res.get("tracks", [])

        # Step 4: Run Part 8 Master-Data Validation
        validated_tracks, val_ms = self.validate_tracks(tracks)

        # Parse raw image for validation annotation overlay
        raw_frame, _ = self.identity_service.detection_engine._parse_image(frame_input)
        annotated_b64 = None
        if raw_frame is not None:
            annotated_frame = self.annotate_validation(raw_frame, validated_tracks)
            ok, buf = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if ok:
                annotated_b64 = f"data:image/jpeg;base64,{import_base64_b64encode(buf.tobytes())}"

        # KPI Counters
        active_cnt = len(validated_tracks)
        validated_cnt = sum(1 for t in validated_tracks if t.get("validation", {}).get("status") == "VALIDATED")
        unregistered_cnt = sum(1 for t in validated_tracks if t.get("validation", {}).get("status") == "UNREGISTERED")
        conflict_cnt = sum(1 for t in validated_tracks if t.get("identity", {}).get("status") == "CONFLICT")
        not_applicable_cnt = sum(1 for t in validated_tracks if t.get("validation", {}).get("status") == "NOT_APPLICABLE")

        # Performance breakdown
        perf = ident_res.get("performance", {})
        det_ms = float(perf.get("detection_ms", 0.0))
        track_ms = float(perf.get("tracking_ms", 0.0))
        bc_ms = float(perf.get("barcode_ms", 0.0))
        ocr_ms = float(perf.get("ocr_ms", 0.0))
        ident_ms = float(perf.get("identity_ms", 0.0))
        total_ms = round((time.perf_counter() - t_total_start) * 1000, 2)

        return {
            "success": True,
            "camera_id": camera_id,
            "session_id": ident_res.get("session_id"),
            "frame_index": ident_res.get("frame_index", 1),
            "timestamp": ident_res.get("timestamp"),
            "frame_width": ident_res.get("frame_width", 0),
            "frame_height": ident_res.get("frame_height", 0),
            "active_track_count": active_cnt,
            "detection_count": ident_res.get("detection_count", 0),
            "identified_count": ident_res.get("identified_count", 0),
            "validated_count": validated_cnt,
            "unregistered_count": unregistered_cnt,
            "conflict_count": conflict_cnt,
            "not_applicable_count": not_applicable_cnt,
            "performance": {
                "detection_ms": det_ms,
                "tracking_ms": track_ms,
                "barcode_ms": bc_ms,
                "ocr_ms": ocr_ms,
                "identity_ms": ident_ms,
                "validation_ms": val_ms,
                "total_ms": total_ms
            },
            "tracks": validated_tracks,
            "annotated_image_url": annotated_b64
        }

    def annotate_validation(
        self,
        frame_bgr: np.ndarray,
        tracks: List[Dict[str, Any]]
    ) -> np.ndarray:
        """
        Render visual overlays displaying bounding box, track ID, object class,
        visual identity, and master-data validation status pill badge.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return frame_bgr

        overlay = frame_bgr.copy()
        h, w = overlay.shape[:2]

        # Status color schemes (BGR)
        STATUS_COLORS = {
            "VALIDATED": (129, 185, 16),        # Emerald green (#10b981)
            "UNREGISTERED": (11, 158, 245),     # Amber/Orange (#f59e0b)
            "CONFLICT": (68, 68, 239),          # Bright red (#ef4444)
            "NOT_APPLICABLE": (139, 116, 100),  # Slate grey (#64748b)
            "MASTER_DATA_UNAVAILABLE": (246, 92, 139) # Violet (#8b5cf6)
        }

        for t in tracks:
            bbox = t.get("bbox", {})
            x1 = max(0, int(bbox.get("x1", 0)))
            y1 = max(0, int(bbox.get("y1", 0)))
            x2 = min(w, int(bbox.get("x2", w)))
            y2 = min(h, int(bbox.get("y2", h)))

            track_id = t.get("track_id", "?")
            class_code = t.get("class_code", "UNKNOWN")
            confidence = t.get("confidence", 0.0)

            ident = t.get("identity", {})
            id_val = ident.get("value")
            id_source = ident.get("source") or "NONE"
            id_status = ident.get("status", "UNIDENTIFIED")

            val = t.get("validation", {})
            val_status = val.get("status", "NOT_APPLICABLE")
            val_display = val.get("display_name")
            matched_field = val.get("matched_field")

            color = STATUS_COLORS.get(val_status, (139, 116, 100))

            # 1. Bounding box
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)

            # 2. Header: Track #ID | Class (Conf%)
            header_txt = f"Track #{track_id} | {class_code} ({int(confidence * 100)}%)"

            # 3. Sub-header: Visual Identity & Source
            if id_status == "IDENTIFIED":
                sub_txt = f"VISUAL: {id_val} [{id_source}]"
            elif id_status == "CONFLICT":
                sub_txt = f"VISUAL: CONFLICT (competing reads)"
            else:
                sub_txt = f"VISUAL: UNIDENTIFIED"

            # 4. Validation Badge text
            badge_txt = f"[{val_status}]"
            if val_display:
                badge_txt += f" {val_display}"

            # Calculate box height for multi-line badge
            font = cv2.FONT_HERSHEY_SIMPLEX
            f_scale = 0.42
            f_thick = 1
            line_height = 16

            box_w = max(
                cv2.getTextSize(header_txt, font, f_scale, f_thick)[0][0],
                cv2.getTextSize(sub_txt, font, f_scale, f_thick)[0][0],
                cv2.getTextSize(badge_txt, font, f_scale, f_thick)[0][0]
            ) + 16

            box_h = (line_height * 3) + 10
            by1 = max(0, y1 - box_h - 4)
            by2 = by1 + box_h
            bx2 = min(w, x1 + box_w)

            # Draw background placard
            cv2.rectangle(overlay, (x1, by1), (bx2, by2), (20, 24, 33), -1)
            cv2.rectangle(overlay, (x1, by1), (bx2, by2), color, 1)

            # Render text lines
            cv2.putText(overlay, header_txt, (x1 + 6, by1 + 14), font, f_scale, (255, 255, 255), f_thick, cv2.LINE_AA)
            cv2.putText(overlay, sub_txt, (x1 + 6, by1 + 14 + line_height), font, f_scale, (200, 210, 225), f_thick, cv2.LINE_AA)
            cv2.putText(overlay, badge_txt, (x1 + 6, by1 + 14 + (line_height * 2)), font, f_scale, color, f_thick, cv2.LINE_AA)

        return overlay


def import_base64_b64encode(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode('utf-8')


# Singleton instance accessor
_validation_service_instance: Optional[MultiObjectValidationService] = None

def get_validation_service() -> MultiObjectValidationService:
    global _validation_service_instance
    if _validation_service_instance is None:
        _validation_service_instance = MultiObjectValidationService()
    return _validation_service_instance
