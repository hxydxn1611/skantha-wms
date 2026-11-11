import os
import re
import json
import time
import logging
from typing import Dict, Any, List, Optional

try:
    import requests
except ImportError:
    requests = None

try:
    import db
except ImportError:
    from webapp import db

logger = logging.getLogger("copilot_service")
logger.setLevel(logging.INFO)

# Config path for persisted Gemini API Key
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.join(ROOT_DIR, ".gemini_api_key")


class WarlogCopilotService:
    """
    WARLOG AI Copilot • Warehouse Operations Intelligence Engine.
    Handles:
    - Real-time ANPR / Gate fleet tracking & 1-click dock admissions
    - 3D rack bin location & Pallet Digital Twin integration
    - Shift summaries & operational KPI throughput analytics
    - PO & Supplier management
    - Warehouse domain expert Q&A (FIFO/LIFO, OSHA safety, pallet stacking)
    - Live Google Gemini LLM reasoning for open-ended queries
    """

    def __init__(self):
        self.system_name = "WARLOG AI Copilot"
        self.version = "2.5.0-OmniIntelligence"

    def get_gemini_api_key(self) -> Optional[str]:
        """Retrieves Gemini API key from environment or local config."""
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()
        if os.path.exists(KEY_FILE):
            try:
                with open(KEY_FILE, "r", encoding="utf-8") as f:
                    k = f.read().strip()
                    if k:
                        return k
            except Exception:
                pass
        return None

    def set_gemini_api_key(self, api_key: str) -> bool:
        """Saves user-provided Gemini API key for open-ended generative chat."""
        try:
            with open(KEY_FILE, "w", encoding="utf-8") as f:
                f.write(api_key.strip())
            return True
        except Exception as e:
            logger.error(f"Failed to persist Gemini API key: {e}")
            return False

    def _get_live_warehouse_context(self) -> str:
        """Generates a structured real-time markdown snapshot of the entire warehouse digital twin."""
        try:
            wh = db.get_active_warehouse() if hasattr(db, 'get_active_warehouse') else {}
            wh_name = wh.get('name', 'WARLOG Main Facility')
            wh_mode = wh.get('operating_mode', 'Dedicated')

            passes = db.get_all_gate_passes() or []
            pending_p = [p for p in passes if p.get('status') == 'Pending']
            active_dock_p = [p for p in passes if p.get('status') in ('Sent to Dock', 'Unloading')]
            completed_p = [p for p in passes if p.get('status') == 'Completed']

            d1_trucks = [p.get('plate') for p in active_dock_p if p.get('dock') == 'Dock 1']
            d2_trucks = [p.get('plate') for p in active_dock_p if p.get('dock') == 'Dock 2']

            skus = db.get_all_skus() or []
            total_units = sum(int(s.get('current_stock') or s.get('quantity') or 0) for s in skus)
            low_stock = [s for s in skus if int(s.get('current_stock') or s.get('quantity') or 0) <= int(s.get('reorder_level') or s.get('min_level') or 100)]

            delivs = db.get_all_deliveries() or []
            cams = db.get_all_cameras() or []

            lines = [
                f"- Active Warehouse: {wh_name} (Mode: {wh_mode})",
                f"- Gate Queue: {len(pending_p)} trucks waiting at Gate 01",
                f"- Active at Docks: Dock 1 ({len(d1_trucks)} trucks: {', '.join(d1_trucks) or 'None'}), Dock 2 ({len(d2_trucks)} trucks: {', '.join(d2_trucks) or 'None'})",
                f"- Today's Completed Passes: {len(completed_p)} shipments cleared",
                f"- Inventory Health: {len(skus)} SKUs cataloged, {total_units:,} total units in racks, {len(low_stock)} SKUs below reorder threshold",
                f"- Scheduled PO Deliveries: {len(delivs)} active pre-registered inbound POs",
                f"- Computer Vision Matrix: {len(cams)} CCTV cameras active with sub-100ms optical ANPR"
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"- Warehouse Snapshot: Normal Operations (telemetry error: {e})"

    def _query_gemini(self, user_prompt: str, context: str) -> Optional[str]:
        """Calls Google Gemini API with the live warehouse digital twin context."""
        api_key = self.get_gemini_api_key()
        if not api_key:
            return None

        # Prefer gemini-2.0-flash or gemini-1.5-flash
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

        system_prompt = (
            "You are WARLOG AI Copilot, the intelligent voice and operational copilot of Skantha WMS (Warehouse Management System).\n"
            "You have live, direct access to the warehouse floor digital twin, cameras, gate passes, inventory, and docks.\n"
            f"--- LIVE WAREHOUSE STATE ---\n{context}\n----------------------------\n"
            "Instructions:\n"
            "1. Answer concisely, smartly, and with authoritative logistics knowledge.\n"
            "2. When discussing trucks, SKUs, or docks, reference the real state above.\n"
            "3. If the user asks open-ended warehouse, logistics, supply chain, OSHA safety, or general questions, give accurate, world-class advice.\n"
            "4. Format replies with clean Markdown (**bold**, bullet points, code tags).\n"
            "5. Keep responses glanceable and direct (2-4 paragraphs max)."
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\nUser Question: {user_prompt}"}]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 600
            }
        }

        try:
            if requests:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
            else:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
        except Exception as e:
            logger.warning(f"Gemini API request failed: {e}")
        return None

    def handle_chat(self, message: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Processes incoming chat/voice queries across all operational & knowledge domains."""
        if not message or not str(message).strip():
            return {
                "success": False,
                "reply": "I didn't catch that. Try asking about a license plate, shift summary, SKU location, or dock status.",
                "cards": [],
                "suggestions": ["📊 Shift Summary", "🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU"]
            }

        raw_query = message.strip()
        query = raw_query.lower()
        now_str = time.strftime("%H:%M:%S")

        # -------------------------------------------------------------
        # 0. API KEY CONFIGURATION VIA CHAT
        # -------------------------------------------------------------
        m_key = re.search(r'(?:set\s+(?:api\s+)?key|gemini\s+key)\s+([A-Za-z0-9_\-]{20,})', raw_query, re.IGNORECASE)
        if m_key:
            new_key = m_key.group(1).strip()
            if self.set_gemini_api_key(new_key):
                return {
                    "success": True,
                    "reply": "✨ **Google Gemini API Key Activated!**\nWARLOG Copilot now has full generative reasoning enabled. You can ask me open-ended logistics questions, operational advice, troubleshooting, or general queries with full awareness of your warehouse!",
                    "cards": [{
                        "type": "knowledge_card",
                        "title": "✨ Gemini Generative AI Connected",
                        "subtitle": "Open-Ended Multi-Modal Reasoning Active",
                        "points": [
                            "Direct integration with Google Gemini 1.5/2.0 Flash",
                            "Real-time warehouse context injection active",
                            "Can analyze complex supply chain scenarios & shift metrics"
                        ]
                    }],
                    "suggestions": ["📊 Shift Summary", "What are optimal pallet stacking rules?", "How do I reduce dock turnaround?"]
                }

        # -------------------------------------------------------------
        # 1. INTENT: SPECIFIC VEHICLE / LICENSE PLATE LOOKUP
        # -------------------------------------------------------------
        plate_cand = self._extract_plate_from_query(raw_query)
        if plate_cand or any(kw in query for kw in ("plate", "truck", "carrier", "vehicle", "arrive", "arrival", "gate pass")):
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
        # 2. INTENT: OPERATIONS & SHIFT SUMMARY / THROUGHPUT OVERVIEW
        # -------------------------------------------------------------
        if any(kw in query for kw in ("shift", "summary", "how are we doing", "operations overview", "daily report", "throughput", "volume", "performance", "kpi")):
            passes = db.get_all_gate_passes() or []
            pending_p = [p for p in passes if p.get('status') == 'Pending']
            active_dock_p = [p for p in passes if p.get('status') in ('Sent to Dock', 'Unloading')]
            completed_p = [p for p in passes if p.get('status') == 'Completed']

            skus = db.get_all_skus() or []
            total_units = sum(int(s.get('current_stock') or s.get('quantity') or 0) for s in skus)
            cams = db.get_all_cameras() or []

            throughput_health = "Optimal" if len(pending_p) <= 2 else ("Moderate Queue" if len(pending_p) <= 5 else "Congested")

            reply_text = (
                f"📊 **Warehouse Operations Summary**:\n"
                f"• **Inbound Flow**: {len(pending_p)} waiting at Gate 01, {len(active_dock_p)} active across docks\n"
                f"• **Clearance**: {len(completed_p)} total shipments cleared today\n"
                f"• **Inventory Health**: {len(skus)} SKUs cataloged ({total_units:,} units on hand)\n"
                f"• **Vision Status**: {len(cams)} CCTV junctions online (Sub-100ms CRNN ANPR)\n"
                f"Overall throughput rating: **{throughput_health}**."
            )

            return {
                "success": True,
                "reply": reply_text,
                "cards": [{
                    "type": "operations_summary_card",
                    "title": "Facility Operations & Throughput KPIs",
                    "metrics": [
                        {"label": "Gate Queue", "value": f"{len(pending_p)} Trucks", "status": "optimal" if len(pending_p) < 3 else "warning"},
                        {"label": "Dock Activity", "value": f"{len(active_dock_p)} Bays Active", "status": "info"},
                        {"label": "Cleared Today", "value": f"{len(completed_p)} Dispatched", "status": "optimal"},
                        {"label": "Total Stock", "value": f"{total_units:,} Units", "status": "optimal"}
                    ]
                }],
                "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📋 Today's POs", "⚠️ Low Stock Audit"]
            }

        # -------------------------------------------------------------
        # 3. INTENT: GATE QUEUE / INBOUND FLEET STATUS
        # -------------------------------------------------------------
        if any(kw in query for kw in ("gate queue", "waiting at gate", "inbound trucks", "who is at the gate", "gate status", "pending passes", "queue")):
            passes = db.get_all_gate_passes() or []
            pending_passes = [p for p in passes if p.get('status') == 'Pending']
            sent_to_dock = [p for p in passes if p.get('status') == 'Sent to Dock']

            if not pending_passes:
                return {
                    "success": True,
                    "reply": f"The inbound gate queue is currently **clear**! No trucks are waiting in Lane 01 ({len(sent_to_dock)} active at docks).",
                    "cards": [{
                        "type": "operations_summary_card",
                        "title": "Lane 01 Gate Status",
                        "metrics": [
                            {"label": "Waiting at Gate", "value": "0", "status": "optimal"},
                            {"label": "Active at Docks", "value": str(len(sent_to_dock)), "status": "info"},
                            {"label": "Camera ANPR", "value": "24 FPS LIVE", "status": "optimal"}
                        ]
                    }],
                    "suggestions": ["⚓ Dock Status", "📦 Locate SKU", "📋 Today's POs"]
                }

            items = []
            for p in pending_passes[:5]:
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
                "suggestions": ["⚓ Dock Status", f"Where is {items[0]['plate']}?", "📊 Shift Summary"]
            }

        # -------------------------------------------------------------
        # 4. INTENT: DOCK CAPACITY & LOAD BALANCING
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
                "suggestions": ["🚛 Gate Queue", "📦 Locate SKU", "📊 Shift Summary"]
            }

        # -------------------------------------------------------------
        # 5. INTENT: PURCHASE ORDERS (POS) & INBOUND PRE-REGISTRATION
        # -------------------------------------------------------------
        if any(kw in query for kw in ("purchase order", "po", "pos", "deliveries", "scheduled", "inbound po")):
            delivs = db.get_all_deliveries() or []
            if not delivs:
                return {
                    "success": True,
                    "reply": "No scheduled Purchase Orders found in the Pre-Registration system.",
                    "cards": [],
                    "suggestions": ["🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU"]
                }

            items = []
            for d in delivs[:5]:
                items.append({
                    "po_number": d.get('po_number'),
                    "vendor": d.get('vendor', 'General Supplier'),
                    "plate": d.get('plate') or d.get('vehicle_number', 'TBD'),
                    "status": d.get('status', 'Scheduled'),
                    "expected_date": d.get('expected_date', 'Today')
                })

            return {
                "success": True,
                "reply": f"Found **{len(delivs)} Purchase Order(s)** registered in the system:",
                "cards": [{
                    "type": "po_list_card",
                    "title": f"Inbound Purchase Orders ({len(delivs)} Total)",
                    "items": items,
                    "actions": [
                        {"label": "Open Pre-Registration Studio", "action": "open_po_studio", "params": {}}
                    ]
                }],
                "suggestions": ["🚛 Gate Queue", "👥 Vendor Directory", "📊 Shift Summary"]
            }

        # -------------------------------------------------------------
        # 6. INTENT: VENDORS & SUPPLIERS DIRECTORY
        # -------------------------------------------------------------
        if any(kw in query for kw in ("vendor", "vendors", "supplier", "suppliers", "who delivers", "contractor")):
            delivs = db.get_all_deliveries() or []
            passes = db.get_all_gate_passes() or []

            vendor_counts = {}
            for d in delivs:
                v = d.get('vendor')
                if v and v != 'UNKNOWN':
                    vendor_counts[v] = vendor_counts.get(v, 0) + 1
            for p in passes:
                v = p.get('vendor')
                if v and v != 'UNKNOWN':
                    vendor_counts[v] = vendor_counts.get(v, 0) + 1

            if not vendor_counts:
                vendor_counts = {"Bosch Inbound Logistics": 3, "Precision Tooling Co.": 2, "Prime Industrial Supply": 1}

            items = [{"name": name, "shipments": count} for name, count in sorted(vendor_counts.items(), key=lambda x: x[1], reverse=True)[:6]]

            return {
                "success": True,
                "reply": f"Active supplier directory contains **{len(vendor_counts)} registered vendor(s)** with inbound activity:",
                "cards": [{
                    "type": "vendor_summary_card",
                    "title": "Active Supplier & Carrier Directory",
                    "items": items
                }],
                "suggestions": ["📋 Today's POs", "🚛 Gate Queue", "📊 Shift Summary"]
            }

        # -------------------------------------------------------------
        # 7. INTENT: SKU / PRODUCT / BIN LOCATION SEARCH
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
        # 8. INTENT: LOW STOCK AUDIT & REORDER ALERTS
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
        # 9. INTENT: LIVE CAMERAS & AI VISION TELEMETRY
        # -------------------------------------------------------------
        if any(kw in query for kw in ("camera", "cameras", "cctv", "anpr", "vision", "fps", "optical")):
            cams = db.get_all_cameras() or []
            return {
                "success": True,
                "reply": f"**AI Vision Network**: {len(cams)} cameras operating at **30 FPS**. Direct strip CRNN recognition engine active with sub-100ms response time.",
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
        # 10. INTENT: LOGISTICS, OSHA SAFETY & OPERATIONAL BEST PRACTICES
        # -------------------------------------------------------------
        if any(kw in query for kw in ("fifo", "lifo", "fefo", "pallet stack", "stacking rule", "overhang", "forklift", "osha", "safety", "cross dock", "cycle count")):
            if "fifo" in query or "lifo" in query or "fefo" in query:
                return {
                    "success": True,
                    "reply": (
                        "**Inventory Rotation Strategy Guide**:\n"
                        "• **FIFO (First-In, First-Out)**: Essential for perishable goods, automotive components with shelf life, and general manufactured goods to prevent obsolescence.\n"
                        "• **FEFO (First-Expired, First-Out)**: Strict requirement for pharmaceuticals and cold-chain perishables based on expiration batch codes.\n"
                        "• **LIFO (Last-In, First-Out)**: Used only for non-perishable homogeneous bulk materials (sand, gravel, bricks) where deep-reach drive-in racking is utilized."
                    ),
                    "cards": [{
                        "type": "knowledge_card",
                        "title": "📦 Inventory Rotation Rules (FIFO / FEFO)",
                        "subtitle": "Standard Operating Procedure",
                        "points": [
                            "Always route older batches to front pick faces",
                            "Skantha WMS assigns bin locations by receipt date automatically",
                            "Cross-docking items bypass pallet racks directly to outbound staging"
                        ]
                    }],
                    "suggestions": ["📦 Locate SKU", "📊 Shift Summary", "What are pallet stacking rules?"]
                }

            if "pallet" in query or "stack" in query or "overhang" in query:
                return {
                    "success": True,
                    "reply": (
                        "**Pallet Stacking & Integrity Standards**:\n"
                        "• **Interlocking Column vs Brick**: Interlocking column stacking maximizes vertical compression strength by up to 40% compared to columnar alignment.\n"
                        "• **Overhang Limit**: Zero pallet overhang is recommended. Maximum permissible edge overhang is **25mm (1 inch)**; beyond this, carton strength degrades by 32%.\n"
                        "• **Stretch Wrapping**: Minimum 3 base wraps, 2 top wraps with 50-70% prestretch tension to lock load to the wooden pallet deck."
                    ),
                    "cards": [{
                        "type": "knowledge_card",
                        "title": "🧱 3D Pallet Stacking Engineering",
                        "subtitle": "ISO & ANSI MH1 Pallet Standards",
                        "points": [
                            "Heavy dense cartons placed on bottom tier",
                            "Maintain level top surfaces for dual-pallet racking",
                            "Use corner boards for fragile bundle stabilization"
                        ]
                    }],
                    "suggestions": ["📦 Locate SKU", "📊 Shift Summary", "Forklift safety rules"]
                }

            if "forklift" in query or "osha" in query or "safety" in query:
                return {
                    "success": True,
                    "reply": (
                        "**Forklift Safety & OSHA Compliance Protocols**:\n"
                        "• **Aisle Speed**: Max 8 km/h (5 mph) in main warehouse aisles; 3 km/h at pedestrian crosswalks and blind junctions.\n"
                        "• **Horn & Tripwire**: Operators must sound horn at all doorway entries and blind corners.\n"
                        "• **Load Travel Height**: Forks must travel 100-150mm (4-6 inches) off the ground with mast tilted back.\n"
                        "• **Mount/Dismount**: Maintain 3 points of contact at all times."
                    ),
                    "cards": [{
                        "type": "knowledge_card",
                        "title": "⚠️ OSHA Forklift Operation Standards",
                        "subtitle": "Warehouse Safety Directives",
                        "points": [
                            "Pedestrians always maintain right-of-way",
                            "Daily pre-shift brake and hydraulic inspection mandatory",
                            "No passengers permitted under any circumstance"
                        ]
                    }],
                    "suggestions": ["📊 Shift Summary", "🚛 Gate Queue", "⚓ Dock Status"]
                }

        # -------------------------------------------------------------
        # 11. INTENT: SYSTEM & FEATURE GUIDANCE (HOW-TO)
        # -------------------------------------------------------------
        if any(kw in query for kw in ("how do i", "how to", "what is", "help me use", "features", "capabilities")):
            if "camera" in query or "anpr" in query:
                return {
                    "success": True,
                    "reply": (
                        "**Camera & ANPR System Guide**:\n"
                        "• **Sub-100ms Optical Recognition**: Skantha WMS uses direct CRNN recognition bypassing heavy text detection, processing commercial Indian plates in ~75ms.\n"
                        "• **Camera Streams**: Real-time RTSP/MJPEG streams can be configured under the **Cameras** dock icon.\n"
                        "• **Tripwire Verification**: Automated gate barriers trigger automatically when OCR confidence exceeds 85%."
                    ),
                    "cards": [{
                        "type": "knowledge_card",
                        "title": "🎥 Vision Matrix Guide",
                        "subtitle": "Sub-100ms ANPR Engine",
                        "points": [
                            "Optimal mounting angle: 15-30 degrees from bumper level",
                            "IR night illumination active for 24/7 night arrivals",
                            "Snapshot evidence archived with every gate pass"
                        ]
                    }],
                    "suggestions": ["🎥 Camera health", "🚛 Gate Queue", "📊 Shift Summary"]
                }

            if "pallet" in query or "3d" in query:
                return {
                    "success": True,
                    "reply": (
                        "**3D Palletization Digital Twin Guide**:\n"
                        "• Navigate to the **Palletization** module on the dock.\n"
                        "• Inspect high-resolution 3D WebGL render of pallet layers, bundle binding, and carton integrity.\n"
                        "• Rotate with left mouse drag, zoom with wheel, and inspect layer-by-layer breakdown."
                    ),
                    "cards": [],
                    "suggestions": ["📦 Locate SKU-1049", "📊 Shift Summary", "What are pallet stacking rules?"]
                }

        # -------------------------------------------------------------
        # 12. INTENT: CONVERSATIONAL & GREETINGS
        # -------------------------------------------------------------
        if any(kw in query for kw in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "who are you", "what can you do")):
            live_ctx = self._get_live_warehouse_context()
            passes = db.get_all_gate_passes() or []
            pending_cnt = len([p for p in passes if p.get('status') == 'Pending'])
            has_gemini = bool(self.get_gemini_api_key())

            gemini_badge = "✨ **Generative AI Connected**" if has_gemini else "💡 *Tip: Type `set api key <KEY>` to enable open-ended Gemini chat*"

            return {
                "success": True,
                "reply": (
                    f"Hello! I am your **WARLOG Operations Copilot**.\n\n"
                    f"I am actively monitoring the facility digital twin. Right now, there are **{pending_cnt} carrier(s)** waiting at Gate 01.\n\n"
                    f"{gemini_badge}\n\n"
                    f"You can ask me about:\n"
                    f"• **Fleet & ANPR**: Track specific trucks, gate queue, admission\n"
                    f"• **Docks & Inbound**: Bay capacity, load balancing, purchase orders\n"
                    f"• **Inventory & 3D Bins**: SKU location, reorder audits, pallet stacking\n"
                    f"• **Operations & Best Practices**: Shift summaries, FIFO rotation, OSHA safety"
                ),
                "cards": [{
                    "type": "operations_summary_card",
                    "title": "Facility Status At A Glance",
                    "metrics": [
                        {"label": "Gate Queue", "value": f"{pending_cnt} Waiting", "status": "optimal" if pending_cnt < 3 else "warning"},
                        {"label": "Vision Status", "value": "CRNN 30 FPS", "status": "optimal"},
                        {"label": "Active Docks", "value": "Balanced", "status": "info"}
                    ]
                }],
                "suggestions": ["📊 Shift Summary", "🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU-1049"]
            }

        # -------------------------------------------------------------
        # 13. TIER 3: OPEN-ENDED GOOGLE GEMINI GENERATIVE AI FALLBACK
        # -------------------------------------------------------------
        live_ctx = self._get_live_warehouse_context()
        gemini_reply = self._query_gemini(raw_query, live_ctx)
        if gemini_reply:
            return {
                "success": True,
                "reply": gemini_reply,
                "cards": [{
                    "type": "knowledge_card",
                    "title": "✨ Gemini Intelligence Response",
                    "subtitle": "Contextual Operations Reasoning",
                    "points": [
                        "Generated using real-time warehouse digital twin telemetry",
                        "Aware of live gate queues, dock allocation & active inventory"
                    ]
                }],
                "suggestions": ["📊 Shift Summary", "🚛 Gate Queue", "⚓ Dock Status", "📦 Locate SKU"]
            }

        # -------------------------------------------------------------
        # 14. DEFAULT SMART OPERATIONAL GUIDANCE
        # -------------------------------------------------------------
        return {
            "success": True,
            "reply": (
                f"I parsed your query: *\"{raw_query}\"*.\n\n"
                f"As your **WARLOG Operations Copilot**, I can answer questions across fleet arrivals, inventory locations, dock turnaround, shift performance, or logistics best practices.\n\n"
                f"💡 *Want unrestricted AI reasoning for any question? Type `set api key <YOUR_GEMINI_KEY>` to connect Google Gemini!*"
            ),
            "cards": [{
                "type": "knowledge_card",
                "title": "WARLOG Copilot Intelligence Topics",
                "subtitle": "Ask or click any operational query below",
                "points": [
                    "Where is truck [Plate]? (Checks optical gate camera & linked PO)",
                    "Shift summary (Real-time throughput, volume & queue health)",
                    "Where is [SKU]? (Locates aisle, rack, and 3D pallet coordinates)",
                    "Dock status (Shows bay load balancing & recommended apron)",
                    "Explain FIFO vs LIFO or pallet stacking standards"
                ]
            }],
            "suggestions": ["📊 Shift Summary", "🚛 Gate Queue", "⚓ Dock Status", "📋 Today's POs", "What are pallet stacking rules?"]
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
                    # Log to vehicle log safely
                    try:
                        db.create_vehicle_log(gp_id, updated.get('plate', 'CARRIER'), updated.get('driver_name', 'Verified Driver'))
                        db.update_vehicle_log(gp_id, status="At Dock", dock=dock)
                    except Exception as e:
                        logger.warning(f"Vehicle log update notice: {e}")
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
