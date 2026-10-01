import sqlite3
import json
import re

def get_db():
    conn = sqlite3.connect('webapp/skandha_wms.db')
    conn.row_factory = sqlite3.Row
    return conn

def normalize_plate(plate_str):
    if not plate_str:
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(plate_str).upper())

def validate_truck(identity_val):
    raw_val = str(identity_val).strip()
    norm_val = normalize_plate(raw_val)
    conn = get_db()
    
    # 1. Check gate_passes by plate, id (GP-xxxx), or po_number
    rows = conn.execute("""
        SELECT id, po_number, plate, vehicle_type, driver_name, vendor, dock, status, created_at
        FROM gate_passes
        WHERE UPPER(id) = ? OR UPPER(po_number) = ? OR UPPER(plate) = ?
    """, (raw_val.upper(), raw_val.upper(), raw_val.upper())).fetchall()

    if not rows and norm_val:
        # Check normalized plate match
        all_gp = conn.execute("SELECT id, po_number, plate, vehicle_type, driver_name, vendor, dock, status, created_at FROM gate_passes").fetchall()
        matched = [r for r in all_gp if normalize_plate(r['plate']) == norm_val]
        if matched:
            rows = matched

    if not rows:
        # 2. Check expected_deliveries
        rows_ed = conn.execute("""
            SELECT po_number, plate, vendor, driver_name, status, created_at
            FROM expected_deliveries
            WHERE UPPER(po_number) = ? OR UPPER(plate) = ?
        """, (raw_val.upper(), raw_val.upper())).fetchall()
        
        if not rows_ed and norm_val:
            all_ed = conn.execute("SELECT po_number, plate, vendor, driver_name, status, created_at FROM expected_deliveries").fetchall()
            matched_ed = [r for r in all_ed if normalize_plate(r['plate']) == norm_val]
            if matched_ed:
                rows_ed = matched_ed

        if rows_ed:
            r = rows_ed[0]
            conn.close()
            return {
                "status": "VALIDATED",
                "master_type": "EXPECTED_DELIVERY",
                "master_id": r['po_number'],
                "display_name": f"PO {r['po_number']} [Plate: {r['plate']}] ({r['vendor'] or 'Carrier'})",
                "matched_field": "plate" if normalize_plate(r['plate']) == norm_val or r['plate'].upper() == raw_val.upper() else "po_number",
                "message": f"Identity matched expected inbound delivery {r['po_number']}.",
                "master_record": {
                    "po_number": r['po_number'],
                    "plate": r['plate'],
                    "vendor": r['vendor'],
                    "driver_name": r['driver_name'],
                    "status": r['status']
                }
            }

    conn.close()

    if rows:
        r = rows[0]
        matched_field = "id" if r['id'].upper() == raw_val.upper() else ("po_number" if r['po_number'].upper() == raw_val.upper() else "plate")
        return {
            "status": "VALIDATED",
            "master_type": "TRUCK",
            "master_id": r['id'],
            "display_name": f"Gate Pass {r['id']} [Plate: {r['plate']}] ({r['vendor'] or 'Carrier'})",
            "matched_field": matched_field,
            "message": f"Identity matched active truck gate pass {r['id']}.",
            "master_record": {
                "id": r['id'],
                "po_number": r['po_number'],
                "plate": r['plate'],
                "driver_name": r['driver_name'],
                "dock": r['dock'],
                "vendor": r['vendor'],
                "status": r['status']
            }
        }

    return {
        "status": "UNREGISTERED",
        "master_type": None,
        "master_id": None,
        "display_name": None,
        "matched_field": None,
        "message": f"Visual identity '{raw_val}' was recognized but no matching WMS truck master record was found."
    }

def validate_box(identity_val):
    raw_val = str(identity_val).strip()
    conn = get_db()

    # Look in gate_passes and expected_deliveries unloading_sheet
    deliveries = conn.execute("SELECT po_number, vendor, unloading_sheet FROM expected_deliveries").fetchall()
    gate_passes = conn.execute("SELECT id, po_number, vendor, unloading_sheet FROM gate_passes").fetchall()
    conn.close()

    # 1. Match SKU in unloading_sheet
    for gp in gate_passes:
        try:
            items = json.loads(gp['unloading_sheet'] or '[]')
            for item in items:
                sku = str(item.get('sku', '')).strip()
                if sku.upper() == raw_val.upper():
                    return {
                        "status": "VALIDATED",
                        "master_type": "BOX",
                        "master_id": sku,
                        "display_name": f"SKU: {sku} - {item.get('description', 'Box Package')} (GP: {gp['id']})",
                        "matched_field": "sku",
                        "message": f"Identity matched active shipment box SKU {sku}.",
                        "master_record": {
                            "sku": sku,
                            "description": item.get('description'),
                            "uom": item.get('uom'),
                            "expected_qty": item.get('expected'),
                            "gate_pass_id": gp['id'],
                            "po_number": gp['po_number']
                        }
                    }
        except Exception:
            pass

    for d in deliveries:
        try:
            items = json.loads(d['unloading_sheet'] or '[]')
            for item in items:
                sku = str(item.get('sku', '')).strip()
                if sku.upper() == raw_val.upper():
                    return {
                        "status": "VALIDATED",
                        "master_type": "BOX",
                        "master_id": sku,
                        "display_name": f"SKU: {sku} - {item.get('description', 'Box Package')} (PO: {d['po_number']})",
                        "matched_field": "sku",
                        "message": f"Identity matched inbound shipment box SKU {sku}.",
                        "master_record": {
                            "sku": sku,
                            "description": item.get('description'),
                            "uom": item.get('uom'),
                            "expected_qty": item.get('expected'),
                            "po_number": d['po_number']
                        }
                    }
        except Exception:
            pass

    # 2. Check if identity matches PO Number
    for gp in gate_passes:
        if gp['po_number'] and gp['po_number'].upper() == raw_val.upper():
            return {
                "status": "VALIDATED",
                "master_type": "BOX",
                "master_id": gp['po_number'],
                "display_name": f"Consignment Box Batch (PO: {gp['po_number']})",
                "matched_field": "po_number",
                "message": f"Identity matched shipment purchase order {gp['po_number']}.",
                "master_record": {
                    "po_number": gp['po_number'],
                    "gate_pass_id": gp['id'],
                    "vendor": gp['vendor']
                }
            }

    return {
        "status": "UNREGISTERED",
        "master_type": None,
        "master_id": None,
        "display_name": None,
        "matched_field": None,
        "message": f"Visual identity '{raw_val}' was recognized but no matching WMS master record was found in Box / SKU catalog."
    }

def validate_worker(identity_val):
    raw_val = str(identity_val).strip()
    conn = get_db()
    row = conn.execute("""
        SELECT id, username FROM users
        WHERE UPPER(username) = ? OR CAST(id AS TEXT) = ?
    """, (raw_val.upper(), raw_val)).fetchone()
    conn.close()

    if row:
        return {
            "status": "VALIDATED",
            "master_type": "WORKER",
            "master_id": str(row['id']),
            "display_name": f"Authorized Personnel ({row['username']})",
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
        "message": f"Visual identity '{raw_val}' was recognized but no matching user/worker was found."
    }

def validate_bin(identity_val):
    raw_val = str(identity_val).strip()
    conn = get_db()
    row = conn.execute("""
        SELECT id, zone_code, zone_name, zone_type, warehouse FROM vision_zones
        WHERE UPPER(zone_code) = ?
    """, (raw_val.upper(),)).fetchone()
    conn.close()

    if row:
        return {
            "status": "VALIDATED",
            "master_type": "BIN",
            "master_id": row['zone_code'],
            "display_name": f"{row['zone_name']} ({row['zone_code']})",
            "matched_field": "zone_code",
            "message": f"Identity matched warehouse zone/bin '{row['zone_code']}'.",
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
        "message": f"Visual identity '{raw_val}' was recognized but no matching warehouse zone/bin was found."
    }

# Run tests
print("Testing TRUCK 'GP-1000':", validate_truck('GP-1000')['status'])
print("Testing TRUCK 'MH12AB1234':", validate_truck('MH12AB1234')['status'])
print("Testing TRUCK 'KA-05-MN-9999':", validate_truck('KA-05-MN-9999')['status'])
print("Testing TRUCK 'B104' (Unknown truck):", validate_truck('B104')['status'])
print("Testing BOX 'VLV-900':", validate_box('VLV-900')['status'])
print("Testing BOX 'B104' (Unregistered box):", validate_box('B104')['status'])
print("Testing WORKER 'Maddy':", validate_worker('Maddy')['status'])
print("Testing WORKER 'admin':", validate_worker('admin')['status'])
print("Testing WORKER 'W07' (Unregistered worker):", validate_worker('W07')['status'])
print("Testing BIN 'BIN-A':", validate_bin('BIN-A')['status'])
print("Testing BIN 'DOCK-01':", validate_bin('DOCK-01')['status'])
print("Testing BIN 'UNKNOWN-BIN':", validate_bin('UNKNOWN-BIN')['status'])
