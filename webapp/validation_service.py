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
  - NO DUPLICATE TABLES: Reuse existing WMS tables (gate_passes, expected_deliveries, users, bins, vision_zones).
  - NO SCHEMA CHANGES: Zero database schema modifications.
  - OBJECT-CLASS AWARE: A truck plate must never match a box; a box SKU must never match a truck.
  - PRESERVE PART 7: Never mutate or overwrite identity.value, source, confidence, status, or candidates.
  - SQL INJECTION SAFE: All queries use parameterized statements (?).
"""

import re
import time
import json
import logging
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
            "tables": ["expected_deliveries", "gate_passes", "skus"],
            "fields": ["unloading_sheet (sku)", "po_number", "sku_id"],
            "description": "Inbound consignment item lines, packaging cartons, and bill-of-lading SKUs"
        },
        "MATERIAL": {
            "available": True,
            "tables": ["skus", "expected_deliveries", "gate_passes"],
            "fields": ["sku_id", "name", "category"],
            "description": "Authoritative WMS material and SKU master catalog"
        },
        "GLASS": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "Automotive glass, windshields, side/rear windows in SKU master"
        },
        "ROD": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "High-tensile rods, steering tubes, structural shafts in SKU master"
        },
        "PART": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "Automotive mechanical and electrical parts in SKU master"
        },
        "COMPONENT": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "Sub-assemblies and modular automotive components in SKU master"
        },
        "FASTENER": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "Grade 10.9 flange bolts, fasteners, hardware in SKU master"
        },
        "SKU": {
            "available": True,
            "tables": ["skus"],
            "fields": ["sku_id", "name", "category"],
            "description": "Authoritative SKU master entities"
        },
        "WORKER": {
            "available": True,
            "tables": ["users"],
            "fields": ["username", "id"],
            "description": "Authorized warehouse personnel and system operators (passwords omitted)"
        },
        "BIN": {
            "available": True,
            "tables": ["bins"],
            "fields": ["bin_id", "zone"],
            "description": "Authoritative WMS physical storage bins and rack locations (Master Hub: Bin Master)"
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

            # 4. Check authoritative SKU Master table directly (Material-agnostic: glass, rods, parts, etc.)
            sku_row = conn.execute("""
                SELECT sku_id, name, description, category, unit_weight, unit_volume FROM skus WHERE UPPER(sku_id) = ?
            """, (raw_val.upper(),)).fetchone()
            if sku_row:
                return {
                    "status": "VALIDATED",
                    "master_type": "SKU",
                    "master_id": sku_row["sku_id"],
                    "display_name": f"Material SKU: {sku_row['sku_id']} ({sku_row['name']})",
                    "matched_field": "sku_id",
                    "message": f"Identity matched authoritative SKU master '{sku_row['sku_id']}'.",
                    "master_record": dict(sku_row)
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

    def validate_material(self, identity_val: str, object_class: str = "MATERIAL") -> Dict[str, Any]:
        """
        Validate automotive material / SKU visual identity against authoritative WMS SKU master (skus table)
        and consignment deliveries.
        Supports classes: MATERIAL, GLASS, ROD, PART, COMPONENT, FASTENER, SKU.
        Distinguishes: VALIDATED, UNREGISTERED, AMBIGUOUS.
        Never guesses SKU from visual appearance alone.
        """
        raw_val = self._safe_str(identity_val)
        if not raw_val:
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": "Visual identity value is missing or empty.",
                "master_record": None
            }

        conn = get_db()
        try:
            # 1. Exact match on sku_id
            sku_rows = conn.execute("""
                SELECT sku_id, name, description, category, unit_weight, unit_volume
                FROM skus
                WHERE UPPER(sku_id) = ?
            """, (raw_val.upper(),)).fetchall()

            # 2. If no exact match on sku_id, check if exact name match
            if not sku_rows:
                sku_rows = conn.execute("""
                    SELECT sku_id, name, description, category, unit_weight, unit_volume
                    FROM skus
                    WHERE UPPER(name) = ?
                """, (raw_val.upper(),)).fetchall()

            # 3. Check for ambiguous pattern (e.g. wildcard or partial matching multiple SKUs)
            if not sku_rows and ('%' in raw_val or '*' in raw_val):
                wildcard = raw_val.replace('*', '%')
                like_rows = conn.execute("""
                    SELECT sku_id, name, description, category, unit_weight, unit_volume
                    FROM skus
                    WHERE UPPER(sku_id) LIKE ? OR UPPER(name) LIKE ?
                """, (f"{wildcard.upper()}%", f"{wildcard.upper()}%")).fetchall()
                if len(like_rows) > 1:
                    return {
                        "status": "AMBIGUOUS",
                        "master_type": "SKU",
                        "master_id": None,
                        "display_name": None,
                        "matched_field": "sku_id",
                        "message": f"Multiple authoritative SKUs ({len(like_rows)}) matched ambiguous identifier '{raw_val}'.",
                        "master_record": None
                    }
                elif len(like_rows) == 1:
                    sku_rows = like_rows

            if len(sku_rows) > 1:
                return {
                    "status": "AMBIGUOUS",
                    "master_type": "SKU",
                    "master_id": None,
                    "display_name": None,
                    "matched_field": "sku_id",
                    "message": f"Multiple authoritative SKUs ({len(sku_rows)}) matched identifier '{raw_val}'.",
                    "master_record": None
                }

            if sku_rows:
                r = dict(sku_rows[0])
                cls_display = object_class.capitalize() if object_class else "Material"
                return {
                    "status": "VALIDATED",
                    "master_type": "SKU",
                    "master_id": r["sku_id"],
                    "display_name": f"{cls_display} SKU: {r['sku_id']} ({r['name']})",
                    "matched_field": "sku_id" if r["sku_id"].upper() == raw_val.upper() else "name",
                    "message": f"Identity matched authoritative WMS SKU master '{r['sku_id']}'.",
                    "master_record": r
                }

            # 4. Fallback check: Inbound consignment unloading sheet SKUs in expected deliveries or gate passes
            rows_gp = conn.execute("""
                SELECT id, po_number, vendor, unloading_sheet, status
                FROM gate_passes
                WHERE unloading_sheet IS NOT NULL AND unloading_sheet != ''
            """).fetchall()

            matched_consignments = []
            for gp in rows_gp:
                try:
                    sheet = json.loads(gp['unloading_sheet'] or '[]')
                    for item in sheet:
                        sku = str(item.get('sku', '')).strip()
                        if sku.upper() == raw_val.upper():
                            matched_consignments.append({
                                "sku": sku,
                                "name": item.get('description', f'{object_class} Item'),
                                "description": item.get('description', ''),
                                "category": object_class,
                                "source": "gate_passes",
                                "source_id": gp['id'],
                                "po_number": gp['po_number']
                            })
                except Exception:
                    pass

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
                            matched_consignments.append({
                                "sku": sku,
                                "name": item.get('description', f'{object_class} Item'),
                                "description": item.get('description', ''),
                                "category": object_class,
                                "source": "expected_deliveries",
                                "source_id": ed['po_number'],
                                "po_number": ed['po_number']
                            })
                except Exception:
                    pass

            if len(matched_consignments) > 1:
                first_sku = matched_consignments[0]["sku"]
                if all(m["sku"].upper() == first_sku.upper() for m in matched_consignments):
                    m = matched_consignments[0]
                    return {
                        "status": "VALIDATED",
                        "master_type": "SKU",
                        "master_id": m["sku"],
                        "display_name": f"{object_class} SKU: {m['sku']} ({m['name']})",
                        "matched_field": "sku",
                        "message": f"Identity matched consignment shipment SKU '{m['sku']}'.",
                        "master_record": m
                    }
                else:
                    return {
                        "status": "AMBIGUOUS",
                        "master_type": "SKU",
                        "master_id": None,
                        "display_name": None,
                        "matched_field": "sku",
                        "message": f"Multiple consignment records matched identifier '{raw_val}'.",
                        "master_record": None
                    }

            if matched_consignments:
                m = matched_consignments[0]
                return {
                    "status": "VALIDATED",
                    "master_type": "SKU",
                    "master_id": m["sku"],
                    "display_name": f"{object_class} SKU: {m['sku']} ({m['name']})",
                    "matched_field": "sku",
                    "message": f"Identity matched consignment shipment SKU '{m['sku']}'.",
                    "master_record": m
                }

            # 5. Not found in SKU master or consignment shipments
            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching WMS record was found in SKU master or shipments for class '{object_class}'.",
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
        Validate BIN visual identity against authoritative WMS bins table.
        Matches by physical bin identifier (bin_id).
        Resolves spatial context if the bin's zone corresponds to a registered vision zone.
        """
        raw_val = self._safe_str(identity_val)
        if not raw_val:
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": "Visual identity value is missing or empty.",
                "master_record": None
            }

        conn = get_db()
        try:
            # Parameterized query against authoritative physical storage locations (bins table)
            row = conn.execute("""
                SELECT bin_id, zone, max_volume, current_volume, max_weight, current_weight, status, last_updated
                FROM bins
                WHERE UPPER(bin_id) = ?
            """, (raw_val.upper(),)).fetchone()

            if row:
                # Spatial context from vision_zones via bin.zone mapping (if configured)
                zone_ref = row['zone']
                vz_row = None
                if zone_ref:
                    vz_row = conn.execute("""
                        SELECT id, zone_code, zone_name, zone_type, warehouse
                        FROM vision_zones
                        WHERE UPPER(zone_code) = ? OR UPPER(zone_name) = ?
                    """, (zone_ref.upper(), zone_ref.upper())).fetchone()

                spatial_context = {
                    "zone_code": vz_row['zone_code'],
                    "zone_name": vz_row['zone_name'],
                    "zone_type": vz_row['zone_type'],
                    "warehouse": vz_row['warehouse']
                } if vz_row else None

                zone_disp = vz_row['zone_name'] if vz_row else (row['zone'] or 'General')

                return {
                    "status": "VALIDATED",
                    "master_type": "BIN",
                    "master_id": row['bin_id'],
                    "display_name": f"Bin {row['bin_id']} (Zone: {zone_disp})",
                    "matched_field": "bin_id",
                    "message": f"Identity matched registered WMS physical storage bin '{row['bin_id']}'.",
                    "master_record": {
                        "bin_id": row['bin_id'],
                        "zone": row['zone'],
                        "max_volume": row['max_volume'],
                        "current_volume": row['current_volume'],
                        "max_weight": row['max_weight'],
                        "current_weight": row['current_weight'],
                        "status": row['status'],
                        "spatial_context": spatial_context
                    }
                }

            return {
                "status": "UNREGISTERED",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Visual identity '{raw_val}' was recognized but no matching physical storage bin was found in WMS Bin Master.",
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

        # 2. Conflict & Ambiguity Handling
        if identity_status in ("CONFLICT", "AMBIGUOUS"):
            return {
                "status": "NOT_APPLICABLE",
                "master_type": None,
                "master_id": None,
                "display_name": None,
                "matched_field": None,
                "message": f"Identity {identity_status.lower()} must be resolved before master-data validation.",
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
        elif norm_class in ("MATERIAL", "GLASS", "ROD", "PART", "COMPONENT", "FASTENER", "SKU"):
            return self.validate_material(identity_value, norm_class)
        elif norm_class in ("BOX", "CARTON", "PACKAGE"):
            return self.validate_box(identity_value)
        elif norm_class in ("WORKER", "PERSONNEL", "USER"):
            return self.validate_worker(identity_value)
        elif norm_class in ("BIN", "LOCATION", "TOTE", "RACK"):
            return self.validate_bin(identity_value)
        else:
            return self.validate_material(identity_value, norm_class)


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

    def validate_object(self, class_code: str, identity_value: Any) -> Dict[str, Any]:
        """Convenience method to validate an individual object."""
        return self.validator.validate_identity(
            class_code=class_code,
            identity_value=identity_value,
            identity_status="IDENTIFIED"
        )

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
        ambiguous_cnt = sum(1 for t in validated_tracks if t.get("validation", {}).get("status") == "AMBIGUOUS" or t.get("identity", {}).get("status") == "AMBIGUOUS")
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
            "ambiguous_count": ambiguous_cnt,
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
            "AMBIGUOUS": (0, 165, 255),         # Vivid Orange (#ff8000)
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

            color = STATUS_COLORS.get(val_status, (139, 116, 100))

            # 1. Bounding box
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)

            # 2. Header: Track #ID | Class (Conf%)
            header_txt = f"Track #{track_id} | {class_code} ({int(confidence * 100)}%)"

            # 3. Sub-header: Visual Identity & Source
            if id_status == "IDENTIFIED":
                sub_txt = f"VISUAL: {id_val} [{id_source}]"
            elif id_status == "CONFLICT":
                sub_txt = "VISUAL: CONFLICT (competing reads)"
            else:
                sub_txt = "VISUAL: UNIDENTIFIED"

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
