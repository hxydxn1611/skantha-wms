import sqlite3
import json

conn = sqlite3.connect('webapp/skandha_wms.db')
conn.row_factory = sqlite3.Row

print("=== REAL EXISTING WMS IDENTIFIERS ===")

print("\n1. GATE PASSES (Truck / Vehicle Master):")
for r in conn.execute("SELECT id, po_number, plate, driver_name, dock, vehicle_type, vendor FROM gate_passes"):
    print(f"  - Gate Pass ID: {r['id']}, Plate: {r['plate']}, PO: {r['po_number']}, Driver: {r['driver_name']}, Dock: {r['dock']}, Vendor: {r['vendor']}")

print("\n2. EXPECTED DELIVERIES (Inbound Shipment Pre-Registration):")
for r in conn.execute("SELECT po_number, plate, driver_name, vendor, unloading_sheet FROM expected_deliveries"):
    print(f"  - PO: {r['po_number']}, Plate: {r['plate']}, Driver: {r['driver_name']}")
    try:
        items = json.loads(r['unloading_sheet'] or '[]')
        for item in items:
            print(f"    * SKU: {item.get('sku')}, UOM: {item.get('uom')}, Desc: {item.get('description')}, Expected: {item.get('expected')}")
    except:
        pass

print("\n3. USERS (Personnel / Worker Master):")
for r in conn.execute("SELECT id, username FROM users"):
    print(f"  - User ID: {r['id']}, Username: {r['username']}")

print("\n4. VISION ZONES (Bin / Location Master):")
for r in conn.execute("SELECT id, zone_code, zone_name, zone_type FROM vision_zones"):
    print(f"  - Zone Code: {r['zone_code']}, Name: {r['zone_name']}, Type: {r['zone_type']}")

print("\n5. CAMERAS (Camera Master):")
for r in conn.execute("SELECT camera_id, camera_code, name, location FROM cameras"):
    print(f"  - Camera ID: {r['camera_id']}, Code: {r['camera_code']}, Name: {r['name']}")

print("\n6. OBJECT CLASSES (Object Class Master):")
for r in conn.execute("SELECT code, name FROM object_classes"):
    print(f"  - Code: {r['code']}, Name: {r['name']}")
