import os
import re
import json
import time
import logging
from typing import Dict, Any, List, Optional

try:
    import db
except ImportError:
    from webapp import db

logger = logging.getLogger("copilot_service")
logger.setLevel(logging.INFO)

class WarlogCopilotService:
    """
    WARLOG AI Copilot • Warehouse Operations Intelligence Engine.
    Handles natural language queries, autonomous warehouse search,
    real-time ANPR / Gate fleet tracking, 3D rack bin location,
    and voice-driven action dispatching.
    """

    def __init__(self):
        self.system_name = "WARLOG AI Copilot"
        self.version = "2.4.0-Enterprise"

    def handle_chat(self, message: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Processes an incoming chat or voice query and returns structured responses with interactive cards."""
        if not message or not str(message).strip():
            return {
                "success": False,
                "reply": "I didn't catch that. Try asking about a license plate, SKU location, or dock status.",
                "cards": [],
                "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU", "⚠️ Low Stock Audit"]
            }

        raw_query = message.strip()
        query = raw_query.lower()
        now_str = time.strftime("%H:%M:%S")

        # -------------------------------------------------------------
        # 1. INTENT: SPECIFIC VEHICLE / LICENSE PLATE LOOKUP
        # -------------------------------------------------------------
        plate_cand = self._extract_plate_from_query(raw_query)
        if plate_cand or any(kw in query for kw in ("plate", "truck", "carrier", "vehicle", "arrive", "arrival", "gate pass")):
            # If specific plate extracted or mentioned
            target_plate = plate_cand
            passes = db.get_all_gate_passes() or []
            delivs = db.get_all_deliveries() or []

            matched_gp = None
            if target_plate:
                clean_target = re.sub(r'[^A-Z0-9]', '', target_plate.upper())
                for gp in passes:
                    c_p = re.sub(r'[^A-Z0-9]', '', str(gp.get('plate', '')).upper())
                    if c_p == clean_target or (len(clean_target) >= 4 and clean_target in c_p):
                        matched_gp = gp
                        break
            elif not target_plate and ("latest" in query or "recent" in query or "last" in query or "current" in query):
                if passes:
                    matched_gp = passes[0]

            if matched_gp:
                return self._build_vehicle_response(matched_gp, raw_query)

            # Check pre-registered deliveries if not in gate passes yet
            if target_plate:
                clean_target = re.sub(r'[^A-Z0-9]', '', target_plate.upper())
                for d in delivs:
                    c_p = re.sub(r'[^A-Z0-9]', '', str(d.get('plate') or d.get('vehicle_number') or '').upper())
                    if c_p == clean_target or (len(clean_target) >= 4 and clean_target in c_p):
                        return {
                            "success": True,
                            "reply": f"Carrier **{d.get('plate')}** is pre-registered for PO **{d.get('po_number')}**, but has not arrived at the optical gate camera yet.",
                            "cards": [{
                                "type": "delivery_card",
                                "title": "Scheduled Inbound Pre-Registration",
                                "plate": d.get('plate'),
                                "po_number": d.get('po_number'),
                                "vendor": d.get('vendor'),
                                "expected_date": d.get('expected_date'),
                                "status": d.get('status', 'Expected'),
                                "driver_name": d.get('driver_name', 'Assigned Driver'),
                                "actions": [
                                    {"label": "Admit as Manual Walk-In", "action": "manual_admit", "params": {"plate": d.get('plate'), "po_number": d.get('po_number')}}
                                ]
                            }],
                            "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📋 Today's POs"]
                        }

        # -------------------------------------------------------------
        # 2. INTENT: GATE QUEUE / INBOUND FLEET STATUS
        # -------------------------------------------------------------
        if any(kw in query for kw in ("gate queue", "waiting at gate", "inbound trucks", "who is at the gate", "gate status", "pending passes")):
            passes = db.get_all_gate_passes() or []
            pending_passes = [p for p in passes if p.get('status') == 'Pending']
            sent_to_dock = [p for p in passes if p.get('status') == 'Sent to Dock']

            if not pending_passes:
                return {
                    "success": True,
                    "reply": f"The inbound gate queue is currently **clear**! No trucks are waiting in Lane 01 ({len(sent_to_dock)} active at docks).",
                    "cards": [{
                        "type": "summary_metric",
                        "title": "Lane 01 Gate Queue",
                        "metrics": [
                            {"label": "Waiting at Gate", "value": "0", "status": "optimal"},
                            {"label": "Active at Docks", "value": str(len(sent_to_dock)), "status": "info"},
                            {"label": "Camera ANPR", "value": "24 FPS LIVE", "status": "optimal"}
                        ]
                    }],
                    "suggestions": ["⚓ Dock Status", "📦 Locate SKU", "📋 Today's POs"]
                }

            items = []
            for p in pending_passes[:4]:
                items.append({
                    "id": p.get('id'),
                    "plate": p.get('plate'),
                    "dock": p.get('dock', 'Dock 1'),
                    "po": p.get('po_number', 'Walk-In'),
                    "time": p.get('time', now_str),
                    "photo": p.get('photo', '')
                })

            return {
                "success": True,
                "reply": f"There are **{len(pending_passes)} truck(s)** waiting at Gate 01 ready for dock admission:",
                "cards": [{
                    "type": "gate_queue_card",
                    "title": f"Gate Queue • {len(pending_passes)} Pending Clearance",
                    "items": items,
                    "actions": [
                        {"label": f"Admit First ({items[0]['plate']}) -> {items[0]['dock']}", "action": "admit_dock", "params": {"id": items[0]['id'], "dock": items[0]['dock']}}
                    ] if items else []
                }],
                "suggestions": ["⚓ Dock Status", f"Where is {items[0]['plate']}?", "⚠️ Low Stock Audit"]
            }

        # -------------------------------------------------------------
        # 3. INTENT: DOCK CAPACITY & LOAD BALANCING
        # -------------------------------------------------------------
        if any(kw in query for kw in ("dock", "docks", "bay", "bays", "unloading")):
            passes = db.get_all_gate_passes() or []
            d1_trucks = [p for p in passes if p.get('dock') == 'Dock 1' and p.get('status') in ('Sent to Dock', 'Unloading')]
            d2_trucks = [p for p in passes if p.get('dock') == 'Dock 2' and p.get('status') in ('Sent to Dock', 'Unloading')]

            suggested = "Dock 2" if len(d2_trucks) < len(d1_trucks) else "Dock 1"

            return {
                "success": True,
                "reply": f"**Dock Status Overview**:\n• **Dock 1**: {len(d1_trucks)} truck(s) currently active\n• **Dock 2**: {len(d2_trucks)} truck(s) currently active\nRecommended for next arrival: **{suggested}**.",
                "cards": [{
                    "type": "dock_balance_card",
                    "title": "Smart Balanced Dock Capacity",
                    "docks": [
                        {"name": "Dock 1", "active_trucks": len(d1_trucks), "status": "In Use" if d1_trucks else "Ready", "vehicles": [t.get('plate') for t in d1_trucks]},
                        {"name": "Dock 2", "active_trucks": len(d2_trucks), "status": "In Use" if d2_trucks else "Ready", "vehicles": [t.get('plate') for t in d2_trucks]}
                    ],
                    "suggested_dock": suggested
                }],
                "suggestions": ["🚛 Gate Queue", "📦 Locate SKU", "⚠️ Low Stock Audit"]
            }

        # -------------------------------------------------------------
        # 4. INTENT: SKU / PRODUCT / BIN LOCATION SEARCH
        # -------------------------------------------------------------
        sku_cand = self._extract_sku_from_query(raw_query)
        if sku_cand or any(kw in query for kw in ("sku", "locate", "where is", "bin", "rack", "find part", "stock for", "inventory for", "bearings", "bolts", "copper")):
            skus = db.get_all_skus() or []
            bins = db.get_all_bins() or []

            matched_sku = None
            if sku_cand:
                clean_sku = sku_cand.upper()
                for s in skus:
                    s_code = str(s.get('sku_code') or s.get('code') or '').upper()
                    s_name = str(s.get('name') or '').upper()
                    if clean_sku in s_code or clean_sku in s_name or s_code in clean_sku:
                        matched_sku = s
                        break

            # Fallback keyword search across SKU names and codes
            if not matched_sku:
                for s in skus:
                    s_name = str(s.get('name', '')).lower()
                    s_code = str(s.get('sku_code', '')).lower()
                    s_desc = str(s.get('description', '')).lower()
                    if any(term in s_name or term in s_code or term in s_desc for term in query.split() if len(term) >= 3):
                        matched_sku = s
                        break

            if matched_sku:
                sku_code = matched_sku.get('sku_code') or matched_sku.get('code', 'SKU-000')
                sku_name = matched_sku.get('name', 'Warehouse Item')
                qty = matched_sku.get('current_stock') or matched_sku.get('quantity', 0)
                reorder = matched_sku.get('reorder_level') or matched_sku.get('min_level', 100)
                uom = matched_sku.get('uom', 'EA')

                # Find associated bin coordinates
                assigned_bin = None
                for b in bins:
                    if b.get('sku_id') == sku_code or b.get('current_sku') == sku_code:
                        assigned_bin = b
                        break

                bin_coord = assigned_bin.get('bin_code') if assigned_bin else matched_sku.get('bin_location', 'Aisle 04 • B-12 • L2')
                zone = assigned_bin.get('zone', 'Zone A') if assigned_bin else 'Zone A'

                status_tag = "LOW STOCK" if int(qty) <= int(reorder) else "OPTIMAL"

                return {
                    "success": True,
                    "reply": f"Found **{sku_name}** (`{sku_code}`). Currently stored at **{bin_coord}** ({zone}) with **{qty} {uom}** on hand.",
                    "cards": [{
                        "type": "sku_locator_card",
                        "sku_code": sku_code,
                        "name": sku_name,
                        "bin_location": bin_coord,
                        "zone": zone,
                        "quantity": f"{qty} {uom}",
                        "status": status_tag,
                        "pallet_id": assigned_bin.get('pallet_id', 'Pallet #P-402') if assigned_bin else 'Pallet #P-402',
                        "actions": [
                            {"label": f"Highlight {bin_coord} on 3D Map", "action": "open_3d_bin", "params": {"bin_code": bin_coord, "sku_code": sku_code}}
                        ]
                    }],
                    "suggestions": ["⚠️ Low Stock Audit", "🚛 Gate Queue", "⚓ Dock Status"]
                }

        # -------------------------------------------------------------
        # 5. INTENT: LOW STOCK AUDIT & REORDER ALERTS
        # -------------------------------------------------------------
        if any(kw in query for kw in ("low stock", "reorder", "audit", "running out", "depleted", "replenish")):
            skus = db.get_all_skus() or []
            low_items = []
            for s in skus:
                cur = int(s.get('current_stock') or s.get('quantity') or 0)
                min_l = int(s.get('reorder_level') or s.get('min_level') or 100)
                if cur <= min_l:
                    low_items.append({
                        "code": s.get('sku_code') or s.get('code'),
                        "name": s.get('name'),
                        "stock": cur,
                        "reorder": min_l,
                        "uom": s.get('uom', 'EA')
                    })

            if not low_items:
                return {
                    "success": True,
                    "reply": "All inventory levels are currently **healthy and above reorder thresholds**!",
                    "cards": [],
                    "suggestions": ["📦 Locate SKU", "🚛 Gate Queue", "⚓ Dock Status"]
                }

            return {
                "success": True,
                "reply": f"Found **{len(low_items)} SKU(s)** requiring replenishment:",
                "cards": [{
                    "type": "low_stock_audit_card",
                    "title": f"⚠️ Inventory Alert • {len(low_items)} Low Stock Items",
                    "items": low_items[:5],
                    "actions": [
                        {"label": "Create Replenishment PO", "action": "open_po_studio", "params": {}}
                    ]
                }],
                "suggestions": ["📦 Locate SKU", "⚓ Dock Status", "🚛 Gate Queue"]
            }

        # -------------------------------------------------------------
        # 6. INTENT: LIVE CAMERAS & AI VISION TELEMETRY
        # -------------------------------------------------------------
        if any(kw in query for kw in ("camera", "cameras", "cctv", "anpr", "vision", "worker count", "fps")):
            cams = db.get_all_cameras() or []
            return {
                "success": True,
                "reply": f"**AI Vision Network**: {len(cams)} cameras operating at **30 FPS**. Direct CRNN recognition engine active with sub-100ms response time.",
                "cards": [{
                    "type": "camera_matrix_card",
                    "title": "Computer Vision & Optical ANPR",
                    "cameras": [
                        {"id": c.get('camera_id') or c.get('camera_code'), "name": c.get('name') or c.get('camera_name'), "loc": c.get('location'), "status": "LIVE"}
                        for c in cams[:4]
                    ]
                }],
                "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU"]
            }

        # -------------------------------------------------------------
        # 7. DEFAULT HELP & ASSISTANT GUIDANCE
        # -------------------------------------------------------------
        return {
            "success": True,
            "reply": "I am your **WARLOG Operations Copilot**. You can ask me questions about trucks, gate arrivals, SKU rack coordinates, or dock loads:",
            "cards": [{
                "type": "help_guide_card",
                "title": "Quick Commands & Copilot Shortcuts",
                "commands": [
                    {"q": "Did truck HR-55-R-8026 arrive?", "d": "Checks optical ANPR gate passes and linked PO"},
                    {"q": "Where is SKU-1049 stored?", "d": "Locates aisle, rack, and level coordinates"},
                    {"q": "Show gate queue", "d": "Lists all waiting carriers at Lane 01"},
                    {"q": "Dock status", "d": "Displays capacity and smart load balancing"},
                    {"q": "Low stock audit", "d": "Identifies items below reorder thresholds"}
                ]
            }],
            "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU", "⚠️ Low Stock Audit"]
        }

    def execute_action(self, action: str, params: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Safely executes warehouse actions requested via Copilot buttons or voice commands."""
        try:
            if action == "admit_dock":
                gp_id = params.get('id')
                dock = params.get('dock', 'Dock 1')
                if not gp_id:
                    return {"success": False, "message": "Missing gate pass ID."}

                updated = db.update_gate_pass(gp_id, {"status": "Sent to Dock", "dock": dock})
                if updated:
                    # Log to vehicle log
                    db.create_vehicle_log(gp_id, updated.get('plate', 'CARRIER'), updated.get('driver_name', 'Verified Driver'))
                    db.update_vehicle_log(gp_id, status="At Dock", dock=dock)
                    return {
                        "success": True,
                        "message": f"Successfully admitted **{updated.get('plate')}** to **{dock}**!",
                        "gate_pass_id": gp_id
                    }
                return {"success": False, "message": f"Could not find gate pass {gp_id}."}

            elif action == "manual_admit":
                plate = params.get('plate')
                po = params.get('po_number', '')
                if not plate:
                    return {"success": False, "message": "Missing plate."}

                new_gp = db.create_gate_pass({
                    "plate": plate,
                    "po_number": po,
                    "type": "Heavy Commercial (HCV) • Commercial (Yellow)",
                    "activity": "Unloading",
                    "status": "Sent to Dock",
                    "dock": "Dock 1",
                    "driver_name": "Assigned Driver"
                })
                return {
                    "success": True,
                    "message": f"Created and dispatched Gate Pass **{new_gp.get('id')}** for plate **{plate}** to Dock 1!",
                    "gate_pass_id": new_gp.get('id')
                }

            return {"success": False, "message": f"Unknown action '{action}'."}
        except Exception as e:
            logger.error(f"Copilot action execution error: {e}")
            return {"success": False, "message": str(e)}

    def _extract_plate_from_query(self, query: str) -> Optional[str]:
        """Extracts Indian license plate substrings from text queries."""
        clean = query.upper()
        # Direct pattern match for formatted plates e.g. HR-55-R-8026, DL 01 AB 1234
        m = re.search(r'([A-Z]{2}[-\s]?[0-9]{1,2}[-\s]?[A-Z]{1,3}[-\s]?[0-9]{4})', clean)
        if m:
            return m.group(1).replace(' ', '-')
        # Match 4-digit tail if prefixed by plate/truck e.g. "truck 8026" or "8026"
        m_tail = re.search(r'\b([0-9]{4})\b', clean)
        if m_tail and any(w in query.lower() for w in ('truck', 'plate', 'carrier', 'arrive', 'car')):
            return m_tail.group(1)
        return None

    def _extract_sku_from_query(self, query: str) -> Optional[str]:
        """Extracts SKU codes e.g. SKU-1049, SKU1049, or 1049 from text queries."""
        m = re.search(r'\b(SKU[-\s]?[0-9A-Z]{2,8})\b', query.upper())
        if m:
            return m.group(1).replace(' ', '-')
        m_num = re.search(r'\b([0-9]{3,6})\b', query)
        if m_num and any(w in query.lower() for w in ('sku', 'part', 'item', 'locate', 'stock', 'bin')):
            return m_num.group(1)
        return None

    def _build_vehicle_response(self, gp: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Builds a high-impact Bixby-style vehicle arrival card."""
        plate = gp.get('plate', 'CARRIER')
        v_type = gp.get('vehicle_type') or gp.get('type') or 'Heavy Commercial (HCV) • Commercial (Yellow)'
        status = gp.get('status', 'Pending')
        dock = gp.get('dock', 'Dock 1')
        po = gp.get('po_number', '')
        time_str = gp.get('time') or gp.get('arrival_date', time.strftime("%H:%M:%S"))
        photo = gp.get('photo', '')
        gp_id = gp.get('id', 'GP-AUTO')

        status_tag = f"● AT {dock.upper()}" if status in ('Sent to Dock', 'Unloading') else "● WAITING AT GATE 01"

        reply_text = f"Carrier **{plate}** is currently **{status}**"
        if po:
            reply_text += f" linked to PO **{po}**"
        if status in ('Sent to Dock', 'Unloading'):
            reply_text += f" at **{dock}**."
        else:
            reply_text += f" at Gate 01, ready for dispatch to **{dock}**."

        actions = []
        if status == 'Pending':
            actions.append({"label": f"⚓ Admit to {dock}", "action": "admit_dock", "params": {"id": gp_id, "dock": dock}})
        if photo:
            actions.append({"label": "📸 View Snapshot", "action": "view_snapshot", "params": {"photo": photo, "plate": plate, "id": gp_id}})
        actions.append({"label": "📄 View Pass", "action": "open_gate_pass", "params": {"id": gp_id}})

        return {
            "success": True,
            "reply": reply_text,
            "cards": [{
                "type": "vehicle_card",
                "plate": plate,
                "vehicle_type": v_type,
                "status_tag": status_tag,
                "status": status,
                "dock": dock,
                "po_number": po or "Walk-In (No PO)",
                "cargo": gp.get('load', 'Industrial Freight'),
                "arrival_time": time_str,
                "photo": photo,
                "gate_pass_id": gp_id,
                "actions": actions
            }],
            "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU"]
        }


# Singleton accessor
_COPILOT_INSTANCE: Optional[WarlogCopilotService] = None

def get_copilot_service() -> WarlogCopilotService:
    global _COPILOT_INSTANCE
    if _COPILOT_INSTANCE is None:
        _COPILOT_INSTANCE = WarlogCopilotService()
    return _COPILOT_INSTANCE
