import sqlite3
import json
import time
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skandha_wms.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the database schema with connected collections/tables."""
    conn = get_db()
    with conn:
        conn.executescript("""
        -- Pre-Registration Collection (Expected Deliveries)
        CREATE TABLE IF NOT EXISTS expected_deliveries (
            po_number TEXT PRIMARY KEY,
            expected_date TEXT NOT NULL,
            activity TEXT DEFAULT 'Unloading',
            vendor TEXT,
            vendor_email TEXT,
            load_description TEXT,
            plate TEXT,
            driver_name TEXT,
            driver_phone TEXT,
            unloading_sheet TEXT,
            status TEXT DEFAULT 'Expected',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Generated Gate Passes Collection
        
        -- SKU Master
        CREATE TABLE IF NOT EXISTS skus (
            sku_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            unit_weight REAL DEFAULT 0.0,
            unit_volume REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Bin Master (Upgraded for Capacity and Slotting)
        CREATE TABLE IF NOT EXISTS bins (
            bin_id TEXT PRIMARY KEY,
            zone TEXT DEFAULT 'General',
            max_volume REAL DEFAULT 100.0,
            current_volume REAL DEFAULT 0.0,
            max_weight REAL DEFAULT 1000.0,
            current_weight REAL DEFAULT 0.0,
            status TEXT DEFAULT 'Active',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Inventory (Granular SKU tracking per Bin)
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bin_id TEXT,
            sku_id TEXT,
            quantity INTEGER DEFAULT 0,
            batch_number TEXT,
            expiry_date TEXT,
            vendor TEXT,
            received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bin_id) REFERENCES bins(bin_id),
            FOREIGN KEY(sku_id) REFERENCES skus(sku_id)
        );

        CREATE TABLE IF NOT EXISTS gate_passes (
            id TEXT PRIMARY KEY,
            po_number TEXT,
            plate TEXT NOT NULL,
            vehicle_type TEXT DEFAULT '',
            driver_name TEXT,
            driver_phone TEXT,
            vendor TEXT,
            vendor_email TEXT,
            load_description TEXT,
            activity TEXT DEFAULT 'Loading',
            expected_date TEXT,
            arrival_date TEXT,
            arrival_time TEXT,
            status TEXT DEFAULT 'Pending',
            dock TEXT DEFAULT 'Not Assigned',
            photo TEXT,
            unloaded_qty INTEGER DEFAULT 0,
            bin_allocation TEXT,
            unloading_sheet TEXT,
            otp TEXT,
            otp_verified INTEGER DEFAULT 0,
            exit_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (po_number) REFERENCES expected_deliveries (po_number)
                ON UPDATE CASCADE ON DELETE SET NULL
        );

        
        -- Outbound Orders
        CREATE TABLE IF NOT EXISTS outbound_orders (
            id TEXT PRIMARY KEY,
            customer_name TEXT,
            destination TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Outbound Items
        CREATE TABLE IF NOT EXISTS outbound_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            sku_id TEXT,
            quantity INTEGER DEFAULT 0,
            picked_quantity INTEGER DEFAULT 0,
            FOREIGN KEY(order_id) REFERENCES outbound_orders(id),
            FOREIGN KEY(sku_id) REFERENCES skus(sku_id)
        );

        -- Attempt to add columns for existing databases
        -- SQLite will error if they already exist, which is fine in exec script if we catch it, but execscript aborts on error.
        -- Better to do it via python try-except.
        
        -- Vehicle Log Collection
        CREATE TABLE IF NOT EXISTS vehicle_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gp_id TEXT,
            plate TEXT NOT NULL,
            driver_name TEXT,
            entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            exit_time TIMESTAMP,
            status TEXT DEFAULT 'Inside',
            FOREIGN KEY (gp_id) REFERENCES gate_passes(id)
        );

        -- Invoices Master Collection
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gp_id TEXT,
            po_number TEXT,
            vendor TEXT,
            vendor_email TEXT,
            pdf_path TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (gp_id) REFERENCES gate_passes(id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        );

        CREATE TABLE IF NOT EXISTS object_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Camera Master Collection (Authoritative source of camera information)
        CREATE TABLE IF NOT EXISTS cameras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT UNIQUE NOT NULL,
            camera_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            warehouse TEXT DEFAULT 'Warehouse A',
            location TEXT NOT NULL,
            bin_id TEXT,
            camera_type TEXT DEFAULT 'IP Camera',
            vendor TEXT DEFAULT 'Hikvision',
            stream_url TEXT,
            status TEXT DEFAULT 'Online',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- AI-Specific Camera Configurations
        CREATE TABLE IF NOT EXISTS vision_camera_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT UNIQUE NOT NULL,
            ai_enabled INTEGER DEFAULT 1,
            detection_enabled INTEGER DEFAULT 1,
            tracking_enabled INTEGER DEFAULT 0,
            processing_fps INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
        );

        -- AI Camera Enabled Object Classes (Many-to-Many)
        CREATE TABLE IF NOT EXISTS vision_camera_object_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT NOT NULL,
            class_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(camera_id, class_code),
            FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE,
            FOREIGN KEY (class_code) REFERENCES object_classes(code) ON UPDATE CASCADE ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_deliveries_plate ON expected_deliveries(plate);
        CREATE INDEX IF NOT EXISTS idx_deliveries_status ON expected_deliveries(status);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_po ON gate_passes(po_number);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_plate ON gate_passes(plate);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_status ON gate_passes(status);
        CREATE INDEX IF NOT EXISTS idx_object_classes_code ON object_classes(code);
        CREATE INDEX IF NOT EXISTS idx_object_classes_status ON object_classes(status);
        CREATE INDEX IF NOT EXISTS idx_cameras_id ON cameras(camera_id);
        CREATE INDEX IF NOT EXISTS idx_cameras_code ON cameras(camera_code);
        CREATE INDEX IF NOT EXISTS idx_vision_cam_cfg_cam ON vision_camera_configs(camera_id);
        CREATE INDEX IF NOT EXISTS idx_vision_cam_obj_cam ON vision_camera_object_classes(camera_id);

        -- Warehouse Zone Master Collection
        CREATE TABLE IF NOT EXISTS vision_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_code TEXT UNIQUE NOT NULL,
            zone_name TEXT NOT NULL,
            zone_type TEXT NOT NULL,
            warehouse TEXT NOT NULL DEFAULT 'Warehouse A',
            description TEXT,
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Warehouse Zone to Camera Association (Many-to-Many)
        CREATE TABLE IF NOT EXISTS vision_zone_cameras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            camera_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(zone_id, camera_id),
            FOREIGN KEY (zone_id) REFERENCES vision_zones(id) ON DELETE CASCADE,
            FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_vision_zones_code ON vision_zones(zone_code);
        CREATE INDEX IF NOT EXISTS idx_vision_zones_type ON vision_zones(zone_type);
        CREATE INDEX IF NOT EXISTS idx_vision_zones_warehouse ON vision_zones(warehouse);
        CREATE INDEX IF NOT EXISTS idx_vision_zones_status ON vision_zones(status);
        CREATE INDEX IF NOT EXISTS idx_vision_zone_cams_zone ON vision_zone_cameras(zone_id);
        CREATE INDEX IF NOT EXISTS idx_vision_zone_cams_cam ON vision_zone_cameras(camera_id);

        -- Warehouse Zone Camera Region of Interest (ROI) Boundaries
        CREATE TABLE IF NOT EXISTS vision_zone_camera_rois (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_id INTEGER NOT NULL,
            camera_id TEXT NOT NULL,
            shape_type TEXT NOT NULL DEFAULT 'POLYGON',
            coordinates TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(zone_id, camera_id),
            FOREIGN KEY (zone_id) REFERENCES vision_zones(id) ON DELETE CASCADE,
            FOREIGN KEY (camera_id) REFERENCES cameras(camera_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_vision_rois_zone ON vision_zone_camera_rois(zone_id);
        CREATE INDEX IF NOT EXISTS idx_vision_rois_cam ON vision_zone_camera_rois(camera_id);
        """)
        
        # Alter existing tables if needed
        columns_expected = ['vendor_email', 'driver_phone']
        for col in columns_expected:
            try:
                conn.execute(f"ALTER TABLE expected_deliveries ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
                
        columns_gp = ['driver_phone', 'vendor_email', 'otp', 'exit_time', 'driver_photo']
        for col in columns_gp:
            try:
                conn.execute(f"ALTER TABLE gate_passes ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE gate_passes ADD COLUMN otp_verified INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE object_classes ADD COLUMN updated_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("UPDATE object_classes SET updated_at = created_at WHERE updated_at IS NULL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE cameras ADD COLUMN bin_id TEXT")
        except sqlite3.OperationalError:
            pass
        
        conn.execute("INSERT OR IGNORE INTO users (username, password) VALUES ('admin', 'admin')")

        # Seed initial object classes for AI Vision & Tracking Master if empty
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM object_classes")
        if cur.fetchone()[0] == 0:
            initial_classes = [
                ('BOX', 'Box / Carton', 'Standard secondary cardboard packaging and bundles', 'Active'),
                ('WORKER', 'Worker / Personnel', 'Warehouse staff, dock loaders, and forklift operators', 'Active'),
                ('TRUCK', 'Truck / Carrier', 'Incoming and outgoing transport trailers, lorries, and containers', 'Active'),
                ('PALLET', 'Storage Pallet', 'Wooden and plastic pallets for unit load handling', 'Active'),
                ('FORKLIFT', 'Forklift / Vehicle', 'Internal combustion and electric reach trucks and forklifts', 'Active'),
                ('BIN', 'Storage Bin / Tote', 'Blue totes, picking bins, and rack storage locations', 'Active')
            ]
            cur.executemany("INSERT INTO object_classes (code, name, description, status) VALUES (?, ?, ?, ?)", initial_classes)

        # Seed initial cameras for Camera Master if empty
        cur.execute("SELECT COUNT(*) FROM cameras")
        if cur.fetchone()[0] == 0:
            initial_cameras = [
                ('CAM-001', 'CAM-001', 'Gate Camera 01', 'Warehouse A', 'Gate 01', 'IP Camera', 'Hikvision', 'rtsp://192.168.1.101:554/ch0', 'Online'),
                ('CAM-002', 'CAM-002', 'Dock Camera 01', 'Warehouse A', 'Dock 01', 'IP Camera', 'Hikvision', 'rtsp://192.168.1.102:554/ch0', 'Online'),
                ('CAM-003', 'CAM-003', 'Dock Camera 02', 'Warehouse A', 'Dock 02', 'IP Camera', 'Dahua', 'rtsp://192.168.1.103:554/ch0', 'Online'),
                ('CAM-004', 'CAM-004', 'Yard Overview Camera', 'Warehouse A', 'Yard Area', 'IP Camera', 'CP Plus', 'rtsp://192.168.1.104:554/ch0', 'Offline')
            ]
            cur.executemany(
                "INSERT INTO cameras (camera_id, camera_code, name, warehouse, location, camera_type, vendor, stream_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                initial_cameras
            )

        # Seed initial AI camera configs if empty
        cur.execute("SELECT COUNT(*) FROM vision_camera_configs")
        if cur.fetchone()[0] == 0:
            initial_configs = [
                ('CAM-001', 1, 1, 0, 5),
                ('CAM-002', 1, 1, 1, 10),
                ('CAM-003', 1, 1, 0, 5),
                ('CAM-004', 0, 0, 0, 2)
            ]
            cur.executemany(
                "INSERT INTO vision_camera_configs (camera_id, ai_enabled, detection_enabled, tracking_enabled, processing_fps) VALUES (?, ?, ?, ?, ?)",
                initial_configs
            )

            initial_cam_classes = [
                ('CAM-001', 'BOX'), ('CAM-001', 'WORKER'), ('CAM-001', 'TRUCK'),
                ('CAM-002', 'BOX'), ('CAM-002', 'WORKER'), ('CAM-002', 'PALLET'), ('CAM-002', 'FORKLIFT'),
                ('CAM-003', 'BOX'), ('CAM-003', 'BIN'),
                ('CAM-004', 'TRUCK')
            ]
            cur.executemany(
                "INSERT INTO vision_camera_object_classes (camera_id, class_code) VALUES (?, ?)",
                initial_cam_classes
            )

        # Seed initial warehouse zones if empty
        cur.execute("SELECT COUNT(*) FROM vision_zones")
        if cur.fetchone()[0] == 0:
            initial_zones = [
                ('TB-01', 'Truck Bay Gate 01', 'TRUCK_BAY', 'Warehouse A', 'Main inbound security gate & truck check-in bay', 'Active'),
                ('DOCK-01', 'Dock 01', 'DOCK', 'Warehouse A', 'Main inbound unloading dock 01', 'Active'),
                ('DOCK-02', 'Dock 02', 'DOCK', 'Warehouse A', 'Secondary inbound unloading dock 02', 'Active'),
                ('UNLOAD-01', 'Unloading Bay 01', 'UNLOADING', 'Warehouse A', 'Pallet drop and primary offloading zone', 'Active'),
                ('SORT-01', 'Primary Sorting Area', 'SORTING', 'Warehouse A', 'Automated conveyor and pallet breakdown sorting hub', 'Active'),
                ('STG-01', 'Inbound Staging Floor', 'STAGING', 'Warehouse A', 'Temporary staging area prior to rack putaway', 'Active'),
                ('BIN-A', 'High Density Bin Area A', 'BIN_AREA', 'Warehouse A', 'Shelving bin racks A1 through A40 for small part cartons', 'Active')
            ]
            cur.executemany(
                "INSERT INTO vision_zones (zone_code, zone_name, zone_type, warehouse, description, status) VALUES (?, ?, ?, ?, ?, ?)",
                initial_zones
            )

            # Map initial zone cameras
            zone_cam_mappings = [
                ('TB-01', 'CAM-001'), ('TB-01', 'CAM-004'),
                ('DOCK-01', 'CAM-001'), ('DOCK-01', 'CAM-002'),
                ('DOCK-02', 'CAM-003'),
                ('UNLOAD-01', 'CAM-002'),
                ('SORT-01', 'CAM-002'),
                ('STG-01', 'CAM-002'), ('STG-01', 'CAM-003'),
                ('BIN-A', 'CAM-003')
            ]
            for z_code, cam_id in zone_cam_mappings:
                cur.execute("SELECT id FROM vision_zones WHERE zone_code = ?", (z_code,))
                z_row = cur.fetchone()
                if z_row:
                    cur.execute(
                        "INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id) VALUES (?, ?)",
                        (z_row[0], cam_id)
                    )

        # Seed initial sample ROIs if empty
        cur.execute("SELECT COUNT(*) FROM vision_zone_camera_rois")
        if cur.fetchone()[0] == 0:
            import json
            # Sample ROI for DOCK-01 on CAM-002 (Inbound Dock area)
            cur.execute("SELECT id FROM vision_zones WHERE zone_code = 'DOCK-01'")
            d1 = cur.fetchone()
            if d1:
                poly_dock = [
                    {"x": 0.15, "y": 0.25},
                    {"x": 0.85, "y": 0.25},
                    {"x": 0.85, "y": 0.85},
                    {"x": 0.15, "y": 0.85}
                ]
                cur.execute("""
                    INSERT OR IGNORE INTO vision_zone_camera_rois (zone_id, camera_id, shape_type, coordinates)
                    VALUES (?, ?, ?, ?)
                """, (d1[0], 'CAM-002', 'POLYGON', json.dumps(poly_dock)))

            # Sample ROI for TB-01 on CAM-001 (Gate check-in bay)
            cur.execute("SELECT id FROM vision_zones WHERE zone_code = 'TB-01'")
            tb1 = cur.fetchone()
            if tb1:
                poly_tb = [
                    {"x": 0.12, "y": 0.22},
                    {"x": 0.88, "y": 0.22},
                    {"x": 0.92, "y": 0.82},
                    {"x": 0.08, "y": 0.82}
                ]
                cur.execute("""
                    INSERT OR IGNORE INTO vision_zone_camera_rois (zone_id, camera_id, shape_type, coordinates)
                    VALUES (?, ?, ?, ?)
                """, (tb1[0], 'CAM-001', 'POLYGON', json.dumps(poly_tb)))

    conn.close()

def get_user(username, password):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = cur.fetchone()
    conn.close()
    return user

def create_user(username, password):
    conn = get_db()
    try:
        with conn:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        return True
    except sqlite3.IntegrityError:
        return False

def _clean_plate(plate):
    if not plate:
        return ""
    return "".join(c for c in plate if c.isalnum()).upper()

def _row_to_delivery(row):
    if not row:
        return None
    d = dict(row)
    try:
        sheet = json.loads(d.get('unloading_sheet') or '[]')
    except Exception:
        sheet = []
    return {
        "po_number": d.get("po_number"),
        "expected_date": d.get("expected_date") or "",
        "activity": d.get("activity") or "Unloading",
        "vendor": d.get("vendor") or "",
        "vendor_email": d.get("vendor_email") or "",
        "load": d.get("load_description") or "",
        "plate": d.get("plate") or "",
        "driver_name": d.get("driver_name") or "",
        "driver_phone": d.get("driver_phone") or "",
        "unloading_sheet": sheet,
        "status": d.get("status") or "Expected",
        "linked_gate_pass_id": d.get("linked_gate_pass_id"),
        "created_at": d.get("created_at")
    }

def _row_to_gate_pass(row):
    if not row:
        return None
    d = dict(row)
    try:
        sheet = json.loads(d.get('unloading_sheet') or '[]')
    except Exception:
        sheet = []
    return {
        "id": d.get("id"),
        "po_number": d.get("po_number") or "",
        "plate": d.get("plate") or "",
        "vehicle_type": d.get("vehicle_type") or "",
        "driver_name": d.get("driver_name") or "",
        "driver_phone": d.get("driver_phone") or "",
        "vendor": d.get("vendor") or "",
        "vendor_email": d.get("vendor_email") or "",
        "load": d.get("load_description") or "",
        "activity": d.get("activity") or "Loading",
        "expected_date": d.get("expected_date") or "",
        "arrival_date": d.get("arrival_date") or "",
        "time": d.get("arrival_time") or "",
        "status": d.get("status") or "Pending",
        "dock": d.get("dock") or "Not Assigned",
        "photo": d.get("photo") or "",
        "driver_photo": d.get("driver_photo") or "",
        "unloaded_qty": d.get("unloaded_qty") or 0,
        "bin_allocation": d.get("bin_allocation") or "",
        "otp_verified": d.get("otp_verified") or 0,
        "exit_time": d.get("exit_time") or "",
        "bin_allocation": d.get("bin_allocation") or "",
        "unloading_sheet": sheet,
        "otp": d.get("otp") or "",
        "otp_verified": d.get("otp_verified") or 0,
        "exit_time": d.get("exit_time") or "",
        "created_at": d.get("created_at")
    }

# ----------------- Pre-Registration Operations -----------------

def get_all_deliveries():
    """Retrieve all expected deliveries along with any linked Gate Pass ID."""
    conn = get_db()
    cursor = conn.execute("""
        SELECT ed.*, gp.id AS linked_gate_pass_id
        FROM expected_deliveries ed
        LEFT JOIN gate_passes gp ON gp.po_number = ed.po_number
        ORDER BY ed.created_at DESC
    """)
    rows = cursor.fetchall()
    deliveries = [_row_to_delivery(r) for r in rows]
    conn.close()
    return deliveries

def get_delivery(po_number):
    conn = get_db()
    cursor = conn.execute("""
        SELECT ed.*, gp.id AS linked_gate_pass_id
        FROM expected_deliveries ed
        LEFT JOIN gate_passes gp ON gp.po_number = ed.po_number
        WHERE ed.po_number = ?
    """, (po_number,))
    row = cursor.fetchone()
    conn.close()
    return _row_to_delivery(row)

def create_delivery(data):
    """Store pre-registration input in the database."""
    conn = get_db()
    with conn:
        po_number = (data.get("po_number") or "").strip()
        if not po_number:
            count = conn.execute("SELECT COUNT(*) FROM expected_deliveries").fetchone()[0]
            po_number = f"PO-{count + 1000}"

        expected_date = data.get("expected_date") or time.strftime("%Y-%m-%d")
        plate = (data.get("plate") or "").strip().upper()
        driver_name = data.get("driver_name") or ""
        activity = data.get("activity") or "Unloading"
        sheet = data.get("unloading_sheet") or []
        
        # Aggregate manifest data if empty
        load_desc = data.get("load") or ""
        vendor = data.get("vendor") or ""
        if not load_desc and isinstance(sheet, list):
            load_desc = ", ".join(list(set([str(item.get('sku_id', '')) for item in sheet if isinstance(item, dict)])))
        if not vendor and isinstance(sheet, list):
            vendor = ", ".join(list(set([str(item.get('vendor', '')) for item in sheet if isinstance(item, dict)])))
            
        sheet_json = json.dumps(sheet) if isinstance(sheet, (list, dict)) else str(sheet)
        status = "Expected"

        vendor_email = data.get("vendor_email") or ""
        driver_phone = data.get("driver_phone") or ""

        conn.execute("""
            INSERT INTO expected_deliveries 
            (po_number, expected_date, activity, vendor, vendor_email, load_description, plate, driver_name, driver_phone, unloading_sheet, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(po_number) DO UPDATE SET
                expected_date = excluded.expected_date,
                activity = excluded.activity,
                vendor = excluded.vendor,
                vendor_email = excluded.vendor_email,
                load_description = excluded.load_description,
                plate = excluded.plate,
                driver_name = excluded.driver_name,
                driver_phone = excluded.driver_phone,
                unloading_sheet = excluded.unloading_sheet
        """, (po_number, expected_date, activity, vendor, vendor_email, load_desc, plate, driver_name, driver_phone, sheet_json, status))
    conn.close()
    return get_delivery(po_number)

def delete_delivery(po_number):
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM expected_deliveries WHERE po_number = ?", (po_number,))
    conn.close()
    return True

# ----------------- Gate Pass Operations -----------------

def has_pending_gate_pass():
    conn = get_db()
    row = conn.execute("SELECT 1 FROM gate_passes WHERE status = 'Pending' LIMIT 1").fetchone()
    conn.close()
    return row is not None

def get_all_gate_passes():
    """Retrieve all gate passes ordered chronologically (newest first)."""
    conn = get_db()
    cursor = conn.execute("SELECT * FROM gate_passes ORDER BY created_at DESC")
    passes = [_row_to_gate_pass(r) for r in cursor.fetchall()]
    conn.close()
    return passes

def get_gate_pass(gp_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM gate_passes WHERE id = ?", (gp_id,)).fetchone()
    conn.close()
    return _row_to_gate_pass(row)

def create_gate_pass(data):
    """
    Generate and save a Gate Pass, connecting it to a Pre-Registration entry
    via plate matching or pre-specified PO number.
    """
    conn = get_db()
    with conn:
        # Atomic calculation of next Gate Pass ID
        cursor = conn.execute("SELECT id FROM gate_passes")
        max_num = 999
        for row in cursor.fetchall():
            gid = str(row['id'])
            if gid.startswith("GP-"):
                try:
                    num = int(gid.split("-")[1])
                    if num > max_num:
                        max_num = num
                except Exception:
                    pass
        new_id = f"GP-{max_num + 1}"

        plate = (data.get('plate') or '').strip().upper()
        vehicle_type = data.get('type') or ''
        photo = data.get('photo') or ''
        driver_name = data.get('driver_name') or ''
        driver_phone = data.get('driver_phone') or ''
        load_info = data.get('load') or ''
        vendor = data.get('vendor') or ''
        vendor_email = data.get('vendor_email') or ''
        expected_date = data.get('expected_date') or ''
        po_number = (data.get('po_number') or '').strip()
        activity = data.get('activity') or 'Loading'
        unloading_sheet = data.get('unloading_sheet') or []
        otp = data.get('otp') or ''

        # CONNECTION LOGIC:
        # 1. Match by Plate if plate is available
        matched_deliv = None
        if plate and plate != "":
            clean_search = _clean_plate(plate)
            # Find in expected deliveries
            all_delivs = conn.execute("SELECT * FROM expected_deliveries ORDER BY created_at DESC").fetchall()
            for d_row in all_delivs:
                if d_row['plate'] and _clean_plate(d_row['plate']) == clean_search:
                    matched_deliv = d_row
                    break

        # 2. Or match by PO Number if provided
        if not matched_deliv and po_number:
            matched_deliv = conn.execute("SELECT * FROM expected_deliveries WHERE po_number = ?", (po_number,)).fetchone()

        # If matched, auto-populate from pre-registration and connect them!
        if matched_deliv:
            po_number = matched_deliv['po_number']
            if driver_name == '' and matched_deliv['driver_name']:
                driver_name = matched_deliv['driver_name']
            if not driver_phone and matched_deliv['driver_phone']:
                driver_phone = matched_deliv['driver_phone']
            if load_info == '' and matched_deliv['load_description']:
                load_info = matched_deliv['load_description']
            if not expected_date and matched_deliv['expected_date']:
                expected_date = matched_deliv['expected_date']
            if vendor == '' and matched_deliv['vendor']:
                vendor = matched_deliv['vendor']
            if not vendor_email and matched_deliv['vendor_email']:
                vendor_email = matched_deliv['vendor_email']
            if matched_deliv['activity']:
                activity = matched_deliv['activity']
            if not unloading_sheet and matched_deliv['unloading_sheet']:
                try:
                    unloading_sheet = json.loads(matched_deliv['unloading_sheet'])
                except Exception:
                    pass

            # Update pre-registration status to indicate truck arrival
            conn.execute("UPDATE expected_deliveries SET status = 'Arrived' WHERE po_number = ?", (po_number,))

        sheet_json = json.dumps(unloading_sheet) if isinstance(unloading_sheet, (list, dict)) else str(unloading_sheet)
        arrival_date = time.strftime("%Y-%m-%d")
        arrival_time = time.strftime("%H:%M:%S")

        driver_photo = data.get('driver_photo') or ''

        conn.execute("""
            INSERT INTO gate_passes
            (id, po_number, plate, vehicle_type, driver_name, driver_phone, vendor, vendor_email, load_description,
             activity, expected_date, arrival_date, arrival_time, status, dock, photo, driver_photo,
             unloaded_qty, bin_allocation, unloading_sheet, otp, otp_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, po_number or None, plate, vehicle_type, driver_name, driver_phone, vendor, vendor_email, load_info,
              activity, expected_date, arrival_date, arrival_time, 'Pending', 'Not Assigned', photo, driver_photo,
              0, '', sheet_json, otp, 0))
    conn.close()
    return get_gate_pass(new_id)

def update_gate_pass(gp_id, data):
    """Update gate pass details and propagate connection updates to pre-registration."""
    conn = get_db()
    with conn:
        curr = conn.execute("SELECT * FROM gate_passes WHERE id = ?", (gp_id,)).fetchone()
        if not curr:
            conn.close()
            return None

        plate = data.get('plate', curr['plate'])
        driver_name = data.get('driver_name', curr['driver_name'])
        load_desc = data.get('load', curr['load_description'])
        vendor = data.get('vendor', curr['vendor'])
        status = data.get('status', curr['status'])
        dock = data.get('dock', curr['dock'])
        expected_date = data.get('expected_date', curr['expected_date'])
        po_number = data.get('po_number', curr['po_number'])
        unloaded_qty = data.get('unloaded_qty', curr['unloaded_qty'])
        activity = data.get('activity', curr['activity'])
        bin_allocation = data.get('bin_allocation', curr['bin_allocation'])
        photo = data.get('photo', curr['photo'])
        driver_photo = data.get('driver_photo', curr['driver_photo'])
        driver_phone = data.get('driver_phone', curr['driver_phone'])
        vendor_email = data.get('vendor_email', curr['vendor_email'])
        otp = data.get('otp', curr['otp'])
        otp_verified = data.get('otp_verified', curr['otp_verified'])
        exit_time = data.get('exit_time', curr['exit_time'])

        sheet_str = curr['unloading_sheet']

        # Synchronize connection with Pre-Registration collection
        if po_number:
            deliv = conn.execute("SELECT * FROM expected_deliveries WHERE po_number = ?", (po_number,)).fetchone()
            if deliv:
                # Synchronize delivery status
                new_deliv_status = 'Sent to Dock' if status == 'Sent to Dock' else ('Completed' if status == 'Completed' else 'Arrived')
                conn.execute("UPDATE expected_deliveries SET status = ? WHERE po_number = ?", (new_deliv_status, po_number))
                # Inherit unloading sheet if pass currently has none
                if (not sheet_str or sheet_str == '[]') and deliv['unloading_sheet']:
                    sheet_str = deliv['unloading_sheet']

        conn.execute("""
            UPDATE gate_passes SET
                plate = ?, driver_name = ?, load_description = ?, vendor = ?,
                status = ?, dock = ?, expected_date = ?, po_number = ?,
                unloaded_qty = ?, activity = ?, bin_allocation = ?, photo = ?, driver_photo = ?,
                unloading_sheet = ?, driver_phone = ?, vendor_email = ?, otp = ?, otp_verified = ?, exit_time = ?
            WHERE id = ?
        """, (plate, driver_name, load_desc, vendor, status, dock, expected_date,
              po_number or None, unloaded_qty, activity, bin_allocation, photo, driver_photo, sheet_str, driver_phone, vendor_email, otp, otp_verified, exit_time, gp_id))
              
        # Execute putaway stock update when transitioning to Completed
        if status == 'Completed' and curr['status'] != 'Completed' and bin_allocation:
            vendor_name = vendor or 'UNKNOWN'
            sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
            # Look up SKU from unloading_sheet if available
            import json
            try:
                sheet = json.loads(sheet_str) if isinstance(sheet_str, str) else sheet_str
                if sheet and len(sheet) > 0 and 'sku' in sheet[0]:
                    sku_id = sheet[0]['sku']
            except: pass
            
            try:
                update_bin_stock(bin_allocation, vendor_name, unloaded_qty or 0, sku_id)
            except Exception as e:
                print("Failed to update bin stock automatically on completion:", e)
              
    conn.close()
    return get_gate_pass(gp_id)

def delete_gate_pass(gp_id):
    """Delete a gate pass and revert the linked pre-registration status if appropriate."""
    conn = get_db()
    with conn:
        curr = conn.execute("SELECT po_number FROM gate_passes WHERE id = ?", (gp_id,)).fetchone()
        if curr and curr['po_number']:
            # Check if any other gate pass links to this PO
            other = conn.execute("SELECT 1 FROM gate_passes WHERE po_number = ? AND id != ? LIMIT 1", (curr['po_number'], gp_id)).fetchone()
            if not other:
                conn.execute("UPDATE expected_deliveries SET status = 'Expected' WHERE po_number = ?", (curr['po_number'],))
        
        # Delete dependent rows to avoid FOREIGN KEY constraint failures
        conn.execute("DELETE FROM vehicle_log WHERE gp_id = ?", (gp_id,))
        conn.execute("DELETE FROM invoices WHERE gp_id = ?", (gp_id,))
        conn.execute("DELETE FROM gate_passes WHERE id = ?", (gp_id,))
    conn.close()
    return True

def set_unload_qty(gp_id, qty):
    conn = get_db()
    with conn:
        conn.execute("UPDATE gate_passes SET unloaded_qty = ? WHERE id = ?", (qty, gp_id))
    conn.close()
    return get_gate_pass(gp_id)

def add_unload_qty(gp_id, add_count):
    conn = get_db()
    with conn:
        conn.execute("UPDATE gate_passes SET unloaded_qty = COALESCE(unloaded_qty, 0) + ? WHERE id = ?", (add_count, gp_id))
    conn.close()
    return get_gate_pass(gp_id)

# ----------------- Statistics -----------------

def get_stats():
    conn = get_db()
    total_expected = conn.execute("SELECT COUNT(*) FROM expected_deliveries").fetchone()[0]
    total_arrived = conn.execute("SELECT COUNT(*) FROM gate_passes").fetchone()[0]
    pending_dock = conn.execute("SELECT COUNT(*) FROM gate_passes WHERE status = 'Pending'").fetchone()[0]
    at_dock = conn.execute("SELECT COUNT(*) FROM gate_passes WHERE status IN ('Sent to Dock', 'Unloading')").fetchone()[0]
    conn.close()
    return {
        "total_expected": total_expected,
        "total_arrived": total_arrived,
        "pending_dock": pending_dock,
        "at_dock": at_dock
    }

# ----------------- Vehicle Log & Invoices -----------------

def get_all_vehicle_logs():
    conn = get_db()
    logs = conn.execute("SELECT * FROM vehicle_log ORDER BY entry_time DESC").fetchall()
    conn.close()
    return [dict(r) for r in logs]

def create_vehicle_log(gp_id, plate, driver_name):
    conn = get_db()
    conn.execute("INSERT INTO vehicle_log (gp_id, plate, driver_name, status) VALUES (?, ?, ?, 'Inside')",
                 (gp_id, plate, driver_name))
    conn.commit()
    conn.close()

def checkout_vehicle_log(gp_id):
    conn = get_db()
    # Using python datetime to match other timestamps
    from datetime import datetime
    exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE vehicle_log SET exit_time = ?, status = 'Departed' WHERE gp_id = ?", (exit_time, gp_id))
    conn.commit()
    conn.close()

def get_all_invoices():
    conn = get_db()
    invs = conn.execute("SELECT * FROM invoices ORDER BY generated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in invs]

def create_invoice(gp_id, po_number, vendor, vendor_email, pdf_path):
    conn = get_db()
    conn.execute("INSERT INTO invoices (gp_id, po_number, vendor, vendor_email, pdf_path) VALUES (?, ?, ?, ?, ?)",
                 (gp_id, po_number, vendor, vendor_email, pdf_path))
    conn.commit()
    conn.close()

# ----------------- AI Vision & Tracking Master: Object Classes -----------------

def get_all_object_classes(search_term=None, status=None):
    conn = get_db()
    query = "SELECT * FROM object_classes WHERE 1=1"
    params = []
    
    if status and status.upper() != 'ALL':
        query += " AND status = ?"
        params.append(status)
        
    if search_term and search_term.strip():
        term = f"%{search_term.strip()}%"
        query += " AND (code LIKE ? OR name LIKE ? OR description LIKE ?)"
        params.extend([term, term, term])
        
    query += " ORDER BY id ASC"
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_object_class(identifier):
    conn = get_db()
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        row = conn.execute("SELECT * FROM object_classes WHERE id = ? OR code = ?", (identifier, str(identifier))).fetchone()
    else:
        row = conn.execute("SELECT * FROM object_classes WHERE code = ?", (str(identifier).upper(),)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_object_class(data):
    from datetime import datetime
    code = data.get('code', '').upper().strip()
    name = data.get('name', '').strip()
    desc = data.get('description', '').strip()
    status = data.get('status', 'Active')
    
    if not code or not name:
        return None, "Class Code and Class Name are required."
        
    conn = get_db()
    existing = conn.execute("SELECT id FROM object_classes WHERE code = ?", (code,)).fetchone()
    if existing:
        conn.close()
        return None, f"Class Code '{code}' already exists."
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO object_classes (code, name, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (code, name, desc, status, now, now)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return get_object_class(new_id), None

def update_object_class(identifier, data):
    from datetime import datetime
    existing = get_object_class(identifier)
    if not existing:
        return None, "Object class not found."
        
    target_id = existing['id']
    code = data.get('code', existing['code']).upper().strip()
    name = data.get('name', existing['name']).strip()
    desc = data.get('description', existing.get('description', '')).strip()
    status = data.get('status', existing.get('status', 'Active'))
    
    conn = get_db()
    if code != existing['code']:
        duplicate = conn.execute("SELECT id FROM object_classes WHERE code = ? AND id != ?", (code, target_id)).fetchone()
        if duplicate:
            conn.close()
            return None, f"Class Code '{code}' is already used by another class."
            
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE object_classes SET code = ?, name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
        (code, name, desc, status, now, target_id)
    )
    conn.commit()
    conn.close()
    return get_object_class(target_id), None

def delete_object_class(identifier):
    existing = get_object_class(identifier)
    if not existing:
        return False, "Object class not found."
    conn = get_db()
    conn.execute("DELETE FROM object_classes WHERE id = ?", (existing['id'],))
    conn.commit()
    conn.close()
    return True, None

# ----------------- Camera Master & AI Vision Camera Sources -----------------

def get_all_cameras():
    conn = get_db()
    rows = conn.execute("SELECT * FROM cameras ORDER BY camera_code ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_camera(identifier):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM cameras WHERE camera_id = ? OR camera_code = ? OR id = ?",
        (str(identifier), str(identifier), str(identifier))
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def create_or_update_camera(data):
    camera_id = str(data.get('camera_id') or data.get('id') or '').strip()
    camera_code = str(data.get('camera_code') or data.get('code') or camera_id).strip().upper()
    name = str(data.get('name') or camera_code).strip()
    warehouse = str(data.get('warehouse') or 'Warehouse A').strip()
    location = str(data.get('location') or 'Gate 01').strip()
    bin_id = str(data.get('bin_id') or '').strip() or None
    camera_type = str(data.get('camera_type') or data.get('type') or 'IP Camera').strip()
    vendor = str(data.get('vendor') or 'Hikvision').strip()
    stream_url = str(data.get('stream_url') or data.get('url') or '').strip()
    status = str(data.get('status') or 'Online').strip()
    
    if not camera_id:
        import uuid
        camera_id = f"CAM-{str(uuid.uuid4())[:6].upper()}"
        if not camera_code:
            camera_code = camera_id

    conn = get_db()
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute("""
            INSERT INTO cameras (camera_id, camera_code, name, warehouse, location, bin_id, camera_type, vendor, stream_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(camera_id) DO UPDATE SET
                camera_code = excluded.camera_code,
                name = excluded.name,
                warehouse = excluded.warehouse,
                location = excluded.location,
                bin_id = excluded.bin_id,
                camera_type = excluded.camera_type,
                vendor = excluded.vendor,
                stream_url = excluded.stream_url,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (camera_id, camera_code, name, warehouse, location, bin_id, camera_type, vendor, stream_url, status, now, now))
    conn.close()
    return get_camera(camera_id)

def get_all_vision_cameras(search_term=None, ai_status=None, cam_status=None):
    """
    Returns list of cameras from Camera Master combined with their AI-specific configuration
    and enabled object classes. Sensitive stream credentials are excluded.
    """
    conn = get_db()
    query = """
        SELECT 
            c.id, c.camera_id, c.camera_code, c.name AS camera_name, c.warehouse, c.location, c.bin_id,
            c.camera_type, c.vendor, c.status AS camera_status, c.created_at AS camera_created_at,
            cfg.id AS config_id, cfg.ai_enabled, cfg.detection_enabled, cfg.tracking_enabled,
            cfg.processing_fps, cfg.created_at AS config_created_at, cfg.updated_at AS config_updated_at
        FROM cameras c
        LEFT JOIN vision_camera_configs cfg ON c.camera_id = cfg.camera_id
        WHERE 1=1
    """
    params = []
    if cam_status and cam_status.upper() != 'ALL':
        query += " AND c.status = ?"
        params.append(cam_status)

    if ai_status and ai_status.upper() != 'ALL':
        if ai_status.upper() in ('ENABLED', 'ACTIVE', '1'):
            query += " AND COALESCE(cfg.ai_enabled, 1) = 1"
        else:
            query += " AND COALESCE(cfg.ai_enabled, 1) = 0"

    if search_term and search_term.strip():
        term = f"%{search_term.strip()}%"
        query += " AND (c.camera_code LIKE ? OR c.name LIKE ? OR c.warehouse LIKE ? OR c.location LIKE ? OR c.camera_type LIKE ?)"
        params.extend([term, term, term, term, term])

    query += " ORDER BY c.camera_code ASC"
    rows = conn.execute(query, tuple(params)).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        cam_id = d['camera_id']

        obj_rows = conn.execute(
            "SELECT class_code FROM vision_camera_object_classes WHERE camera_id = ? ORDER BY class_code ASC",
            (cam_id,)
        ).fetchall()
        classes = [row['class_code'] for row in obj_rows]

        ai_enabled = bool(d['ai_enabled']) if d['config_id'] is not None else True
        detection_enabled = bool(d['detection_enabled']) if d['config_id'] is not None else True
        tracking_enabled = bool(d['tracking_enabled']) if d['config_id'] is not None else False
        fps = int(d['processing_fps']) if d['config_id'] is not None and d['processing_fps'] else 5

        results.append({
            "camera_id": d['camera_id'],
            "camera_code": d['camera_code'],
            "camera_name": d['camera_name'],
            "warehouse": d['warehouse'] or 'Warehouse A',
            "location": d['location'],
            "bin_id": d.get('bin_id'),
            "camera_type": d['camera_type'],
            "vendor": d['vendor'],
            "camera_status": d['camera_status'],
            "ai_config": {
                "ai_enabled": ai_enabled,
                "detection_enabled": detection_enabled,
                "tracking_enabled": tracking_enabled,
                "processing_fps": fps,
                "object_classes": classes,
                "created_at": d['config_created_at'],
                "updated_at": d['config_updated_at']
            }
        })
    conn.close()
    return results

def get_vision_camera(identifier):
    conn = get_db()
    row = conn.execute("""
        SELECT 
            c.id, c.camera_id, c.camera_code, c.name AS camera_name, c.warehouse, c.location, c.bin_id,
            c.camera_type, c.vendor, c.status AS camera_status, c.created_at AS camera_created_at,
            cfg.id AS config_id, cfg.ai_enabled, cfg.detection_enabled, cfg.tracking_enabled,
            cfg.processing_fps, cfg.created_at AS config_created_at, cfg.updated_at AS config_updated_at
        FROM cameras c
        LEFT JOIN vision_camera_configs cfg ON c.camera_id = cfg.camera_id
        WHERE c.camera_id = ? OR c.camera_code = ? OR c.id = ?
    """, (str(identifier), str(identifier), str(identifier))).fetchone()

    if not row:
        conn.close()
        return None

    d = dict(row)
    cam_id = d['camera_id']
    obj_rows = conn.execute(
        "SELECT class_code FROM vision_camera_object_classes WHERE camera_id = ? ORDER BY class_code ASC",
        (cam_id,)
    ).fetchall()
    classes = [r['class_code'] for r in obj_rows]
    conn.close()

    ai_enabled = bool(d['ai_enabled']) if d['config_id'] is not None else True
    detection_enabled = bool(d['detection_enabled']) if d['config_id'] is not None else True
    tracking_enabled = bool(d['tracking_enabled']) if d['config_id'] is not None else False
    fps = int(d['processing_fps']) if d['config_id'] is not None and d['processing_fps'] else 5

    return {
        "camera_id": d['camera_id'],
        "camera_code": d['camera_code'],
        "camera_name": d['camera_name'],
        "warehouse": d['warehouse'] or 'Warehouse A',
        "location": d['location'],
        "bin_id": d.get('bin_id'),
        "camera_type": d['camera_type'],
        "vendor": d['vendor'],
        "camera_status": d['camera_status'],
        "ai_config": {
            "ai_enabled": ai_enabled,
            "detection_enabled": detection_enabled,
            "tracking_enabled": tracking_enabled,
            "processing_fps": fps,
            "object_classes": classes,
            "created_at": d['config_created_at'],
            "updated_at": d['config_updated_at']
        }
    }

def save_vision_camera_config(identifier, data):
    from datetime import datetime
    cam = get_camera(identifier)
    if not cam:
        return None, f"Camera '{identifier}' not found in Camera Master."

    camera_id = cam['camera_id']
    
    # Validation: processing_fps
    try:
        raw_fps = data.get('processing_fps', 5)
        fps = int(raw_fps)
        if fps <= 0 or fps > 60:
            return None, "Processing FPS must be a positive integer between 1 and 60."
    except (ValueError, TypeError):
        return None, "Processing FPS must be a valid numeric integer."

    ai_enabled = 1 if data.get('ai_enabled') in (True, 1, '1', 'true', 'True', 'Enabled') else 0
    detection_enabled = 1 if data.get('detection_enabled') in (True, 1, '1', 'true', 'True', 'Enabled') else 0
    tracking_enabled = 1 if data.get('tracking_enabled') in (True, 1, '1', 'true', 'True', 'Enabled') else 0
    
    # Validation: Object classes
    raw_classes = data.get('object_classes', [])
    if not isinstance(raw_classes, list):
        return None, "Object classes must be provided as a list."

    cleaned_classes = [str(c).strip().upper() for c in raw_classes if str(c).strip()]

    # If AI Processing is enabled, at least one Object Class should be selected.
    if ai_enabled and len(cleaned_classes) == 0:
        return None, "At least one Object Class must be selected when AI Processing is enabled."

    conn = get_db()
    # Verify that the selected classes exist in Object Classes Master
    if cleaned_classes:
        placeholders = ','.join(['?'] * len(cleaned_classes))
        existing_classes = conn.execute(
            f"SELECT code FROM object_classes WHERE code IN ({placeholders})",
            tuple(cleaned_classes)
        ).fetchall()
        existing_codes = set(r['code'] for r in existing_classes)
        invalid_codes = set(cleaned_classes) - existing_codes
        if invalid_codes:
            conn.close()
            return None, f"Unknown object class code(s): {', '.join(sorted(invalid_codes))}."

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        if 'bin_id' in data:
            conn.execute("UPDATE cameras SET bin_id = ? WHERE camera_id = ?", (data.get('bin_id'), camera_id))
            
        conn.execute("""
            INSERT INTO vision_camera_configs (camera_id, ai_enabled, detection_enabled, tracking_enabled, processing_fps, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(camera_id) DO UPDATE SET
                ai_enabled = excluded.ai_enabled,
                detection_enabled = excluded.detection_enabled,
                tracking_enabled = excluded.tracking_enabled,
                processing_fps = excluded.processing_fps,
                updated_at = excluded.updated_at
        """, (camera_id, ai_enabled, detection_enabled, tracking_enabled, fps, now, now))

        conn.execute("DELETE FROM vision_camera_object_classes WHERE camera_id = ?", (camera_id,))
        if cleaned_classes:
            insert_tuples = [(camera_id, code, now) for code in cleaned_classes]
            conn.executemany(
                "INSERT INTO vision_camera_object_classes (camera_id, class_code, created_at) VALUES (?, ?, ?)",
                insert_tuples
            )
    conn.close()
    return get_vision_camera(camera_id), None

# ==========================================
# WAREHOUSE ZONE MASTER HELPERS
# ==========================================
ZONE_TYPES = {
    'TRUCK_BAY': 'Truck Bay',
    'DOCK': 'Dock',
    'UNLOADING': 'Unloading',
    'SORTING': 'Sorting',
    'CONVEYOR': 'Conveyor',
    'STAGING': 'Staging',
    'STORAGE': 'Storage',
    'BIN_AREA': 'Bin Area',
    'DISPATCH': 'Dispatch'
}

def get_zone_types():
    return [{"code": k, "name": v} for k, v in ZONE_TYPES.items()]

def get_all_vision_zones(search_term=None, zone_type=None, warehouse=None, status=None):
    conn = get_db()
    query = """
        SELECT 
            z.id, z.zone_code, z.zone_name, z.zone_type, z.warehouse,
            z.description, z.status, z.created_at, z.updated_at
        FROM vision_zones z
        WHERE 1=1
    """
    params = []

    if status and status.upper() != 'ALL':
        query += " AND UPPER(z.status) = ?"
        params.append(status.strip().upper())

    if zone_type and zone_type.upper() != 'ALL':
        query += " AND UPPER(z.zone_type) = ?"
        params.append(zone_type.strip().upper())

    if warehouse and warehouse.upper() != 'ALL':
        query += " AND UPPER(z.warehouse) = ?"
        params.append(warehouse.strip().upper())

    if search_term and search_term.strip():
        term = f"%{search_term.strip()}%"
        query += " AND (z.zone_code LIKE ? OR z.zone_name LIKE ? OR z.description LIKE ? OR z.warehouse LIKE ?)"
        params.extend([term, term, term, term])

    query += " ORDER BY z.zone_code ASC"
    rows = conn.execute(query, tuple(params)).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        zone_id = d['id']

        cam_rows = conn.execute("""
            SELECT c.camera_id, c.camera_code, c.name, c.warehouse, c.location, c.camera_type, c.status,
                   vzcr.id as roi_id, vzcr.shape_type, vzcr.coordinates, vzcr.updated_at as roi_updated_at
            FROM vision_zone_cameras vzc
            JOIN cameras c ON vzc.camera_id = c.camera_id
            LEFT JOIN vision_zone_camera_rois vzcr ON vzcr.zone_id = vzc.zone_id AND vzcr.camera_id = vzc.camera_id
            WHERE vzc.zone_id = ?
            ORDER BY c.camera_code ASC
        """, (zone_id,)).fetchall()

        cameras = []
        for crow in cam_rows:
            roi_obj = None
            if crow['roi_id'] is not None:
                import json
                try:
                    coords = json.loads(crow['coordinates'])
                except Exception:
                    coords = []
                roi_obj = {
                    "id": crow['roi_id'],
                    "shape_type": crow['shape_type'],
                    "coordinates": coords,
                    "updated_at": crow['roi_updated_at']
                }

            cameras.append({
                "camera_id": crow['camera_id'],
                "camera_code": crow['camera_code'],
                "name": crow['name'],
                "location": crow['location'],
                "status": crow['status'],
                "roi_configured": crow['roi_id'] is not None,
                "roi_shape_type": crow['shape_type'] if crow['roi_id'] is not None else None,
                "roi": roi_obj
            })

        results.append({
            "id": d['id'],
            "zone_code": d['zone_code'],
            "zone_name": d['zone_name'],
            "zone_type": d['zone_type'],
            "zone_type_label": ZONE_TYPES.get(d['zone_type'], d['zone_type']),
            "warehouse": d['warehouse'],
            "description": d['description'] or '',
            "status": d['status'],
            "cameras": cameras,
            "camera_ids": [c['camera_id'] for c in cameras],
            "camera_codes": [c['camera_code'] for c in cameras],
            "camera_count": len(cameras),
            "created_at": d['created_at'],
            "updated_at": d['updated_at']
        })
    conn.close()
    return results

def get_vision_zone(identifier):
    conn = get_db()
    row = conn.execute("""
        SELECT * FROM vision_zones
        WHERE id = ? OR zone_code = ?
    """, (str(identifier), str(identifier))).fetchone()

    if not row:
        conn.close()
        return None

    d = dict(row)
    zone_id = d['id']

    cam_rows = conn.execute("""
        SELECT c.camera_id, c.camera_code, c.name, c.warehouse, c.location, c.camera_type, c.status,
               vzcr.id as roi_id, vzcr.shape_type, vzcr.coordinates, vzcr.updated_at as roi_updated_at
        FROM vision_zone_cameras vzc
        JOIN cameras c ON vzc.camera_id = c.camera_id
        LEFT JOIN vision_zone_camera_rois vzcr ON vzcr.zone_id = vzc.zone_id AND vzcr.camera_id = vzc.camera_id
        WHERE vzc.zone_id = ?
        ORDER BY c.camera_code ASC
    """, (zone_id,)).fetchall()

    cameras = []
    for crow in cam_rows:
        roi_obj = None
        if crow['roi_id'] is not None:
            import json
            try:
                coords = json.loads(crow['coordinates'])
            except Exception:
                coords = []
            roi_obj = {
                "id": crow['roi_id'],
                "shape_type": crow['shape_type'],
                "coordinates": coords,
                "updated_at": crow['roi_updated_at']
            }

        cameras.append({
            "camera_id": crow['camera_id'],
            "camera_code": crow['camera_code'],
            "name": crow['name'],
            "location": crow['location'],
            "status": crow['status'],
            "roi_configured": crow['roi_id'] is not None,
            "roi_shape_type": crow['shape_type'] if crow['roi_id'] is not None else None,
            "roi": roi_obj
        })
    conn.close()

    return {
        "id": d['id'],
        "zone_code": d['zone_code'],
        "zone_name": d['zone_name'],
        "zone_type": d['zone_type'],
        "zone_type_label": ZONE_TYPES.get(d['zone_type'], d['zone_type']),
        "warehouse": d['warehouse'],
        "description": d['description'] or '',
        "status": d['status'],
        "cameras": cameras,
        "camera_ids": [c['camera_id'] for c in cameras],
        "camera_codes": [c['camera_code'] for c in cameras],
        "camera_count": len(cameras),
        "created_at": d['created_at'],
        "updated_at": d['updated_at']
    }

def create_vision_zone(data):
    from datetime import datetime
    zone_code = str(data.get('zone_code', '')).strip().upper()
    zone_name = str(data.get('zone_name', '')).strip()
    zone_type = str(data.get('zone_type', '')).strip().upper()
    warehouse = str(data.get('warehouse', 'Warehouse A')).strip() or 'Warehouse A'
    description = str(data.get('description', '')).strip()
    status = str(data.get('status', 'Active')).strip()
    if status.capitalize() in ('Active', 'Disabled'):
        status = status.capitalize()
    else:
        status = 'Active'

    if not zone_code:
        return None, "Zone Code is required."
    if not zone_name:
        return None, "Zone Name is required."
    if not zone_type:
        return None, "Zone Type is required."
    if zone_type not in ZONE_TYPES:
        return None, f"Invalid Zone Type '{zone_type}'. Valid types are: {', '.join(ZONE_TYPES.keys())}."

    conn = get_db()
    existing = conn.execute("SELECT id FROM vision_zones WHERE zone_code = ?", (zone_code,)).fetchone()
    if existing:
        conn.close()
        return None, f"Zone with code '{zone_code}' already exists."

    raw_cameras = data.get('cameras', [])
    clean_camera_ids = []
    if raw_cameras:
        if not isinstance(raw_cameras, list):
            conn.close()
            return None, "Cameras must be provided as a list."
        for item in raw_cameras:
            cid = str(item).strip()
            if cid and cid not in clean_camera_ids:
                clean_camera_ids.append(cid)

        if clean_camera_ids:
            placeholders = ','.join(['?'] * len(clean_camera_ids))
            cam_matches = conn.execute(
                f"SELECT camera_id FROM cameras WHERE camera_id IN ({placeholders}) OR camera_code IN ({placeholders})",
                tuple(clean_camera_ids) + tuple(clean_camera_ids)
            ).fetchall()
            matched_ids = set(r['camera_id'] for r in cam_matches)
            clean_camera_ids = list(matched_ids)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        cursor = conn.execute("""
            INSERT INTO vision_zones (zone_code, zone_name, zone_type, warehouse, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (zone_code, zone_name, zone_type, warehouse, description, status, now, now))
        new_zone_id = cursor.lastrowid

        if clean_camera_ids:
            insert_tuples = [(new_zone_id, cid, now) for cid in clean_camera_ids]
            conn.executemany("""
                INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id, created_at)
                VALUES (?, ?, ?)
            """, insert_tuples)
    conn.close()
    return get_vision_zone(new_zone_id), None

def update_vision_zone(identifier, data):
    from datetime import datetime
    zone = get_vision_zone(identifier)
    if not zone:
        return None, f"Zone '{identifier}' not found."

    zone_id = zone['id']
    zone_code = str(data.get('zone_code', zone['zone_code'])).strip().upper()
    zone_name = str(data.get('zone_name', zone['zone_name'])).strip()
    zone_type = str(data.get('zone_type', zone['zone_type'])).strip().upper()
    warehouse = str(data.get('warehouse', zone['warehouse'])).strip() or 'Warehouse A'
    description = str(data.get('description', zone['description'])).strip()
    status = str(data.get('status', zone['status'])).strip()
    if status.capitalize() in ('Active', 'Disabled'):
        status = status.capitalize()
    else:
        status = zone['status']

    if not zone_code:
        return None, "Zone Code cannot be empty."
    if not zone_name:
        return None, "Zone Name cannot be empty."
    if not zone_type:
        return None, "Zone Type cannot be empty."
    if zone_type not in ZONE_TYPES:
        return None, f"Invalid Zone Type '{zone_type}'. Valid types are: {', '.join(ZONE_TYPES.keys())}."

    conn = get_db()
    duplicate = conn.execute("SELECT id FROM vision_zones WHERE zone_code = ? AND id != ?", (zone_code, zone_id)).fetchone()
    if duplicate:
        conn.close()
        return None, f"Zone code '{zone_code}' is already in use by another zone."

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute("""
            UPDATE vision_zones
            SET zone_code = ?, zone_name = ?, zone_type = ?, warehouse = ?, description = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (zone_code, zone_name, zone_type, warehouse, description, status, now, zone_id))

        if 'cameras' in data:
            raw_cameras = data.get('cameras', [])
            clean_camera_ids = []
            if isinstance(raw_cameras, list):
                for item in raw_cameras:
                    cid = str(item).strip()
                    if cid and cid not in clean_camera_ids:
                        clean_camera_ids.append(cid)

            conn.execute("DELETE FROM vision_zone_cameras WHERE zone_id = ?", (zone_id,))
            if clean_camera_ids:
                placeholders = ','.join(['?'] * len(clean_camera_ids))
                cam_matches = conn.execute(
                    f"SELECT camera_id FROM cameras WHERE camera_id IN ({placeholders}) OR camera_code IN ({placeholders})",
                    tuple(clean_camera_ids) + tuple(clean_camera_ids)
                ).fetchall()
                matched_ids = [r['camera_id'] for r in cam_matches]

                insert_tuples = [(zone_id, cid, now) for cid in set(matched_ids)]
                conn.executemany("""
                    INSERT OR IGNORE INTO vision_zone_cameras (zone_id, camera_id, created_at)
                    VALUES (?, ?, ?)
                """, insert_tuples)

    conn.close()
    return get_vision_zone(zone_id), None

def delete_vision_zone(identifier):
    zone = get_vision_zone(identifier)
    if not zone:
        return False, f"Zone '{identifier}' not found."
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM vision_zone_camera_rois WHERE zone_id = ?", (zone['id'],))
        conn.execute("DELETE FROM vision_zone_cameras WHERE zone_id = ?", (zone['id'],))
        conn.execute("DELETE FROM vision_zones WHERE id = ?", (zone['id'],))
    conn.close()
    return True, None

def get_zone_cameras(identifier):
    zone = get_vision_zone(identifier)
    if not zone:
        return None, f"Zone '{identifier}' not found."
    return zone['cameras'], None

def update_zone_cameras(identifier, camera_ids):
    zone = get_vision_zone(identifier)
    if not zone:
        return None, f"Zone '{identifier}' not found."
    return update_vision_zone(identifier, {'cameras': camera_ids})

# ==========================================
# VISUAL ZONE / ROI EDITOR HELPERS
# ==========================================
def get_zone_camera_roi(zone_identifier, camera_identifier):
    import json
    zone = get_vision_zone(zone_identifier)
    if not zone:
        return None, f"Zone '{zone_identifier}' not found."

    conn = get_db()
    cam_row = conn.execute(
        "SELECT camera_id, camera_code, name, warehouse, location FROM cameras WHERE camera_id = ? OR camera_code = ?",
        (str(camera_identifier), str(camera_identifier))
    ).fetchone()
    if not cam_row:
        conn.close()
        return None, f"Camera '{camera_identifier}' not found in Camera Master."

    camera_id = cam_row['camera_id']
    camera_code = cam_row['camera_code']

    assoc = conn.execute(
        "SELECT id FROM vision_zone_cameras WHERE zone_id = ? AND camera_id = ?",
        (zone['id'], camera_id)
    ).fetchone()
    if not assoc:
        conn.close()
        return None, f"Camera '{camera_code}' is not associated with zone '{zone['zone_code']}'."

    roi_row = conn.execute("""
        SELECT * FROM vision_zone_camera_rois
        WHERE zone_id = ? AND camera_id = ?
    """, (zone['id'], camera_id)).fetchone()
    conn.close()

    if not roi_row:
        return {
            "configured": False,
            "roi_configured": False,
            "shape_type": None,
            "coordinates": [],
            "zone_id": zone['id'],
            "zone_code": zone['zone_code'],
            "zone_name": zone['zone_name'],
            "zone_type": zone['zone_type'],
            "zone_type_label": zone['zone_type_label'],
            "warehouse": zone['warehouse'],
            "camera_id": camera_id,
            "camera_code": camera_code,
            "camera_name": cam_row['name'],
            "camera_location": cam_row['location'],
            "roi": None
        }, None

    d = dict(roi_row)
    try:
        coords = json.loads(d['coordinates'])
    except Exception:
        coords = []

    return {
        "configured": True,
        "roi_configured": True,
        "shape_type": d['shape_type'],
        "coordinates": coords,
        "zone_id": zone['id'],
        "zone_code": zone['zone_code'],
        "zone_name": zone['zone_name'],
        "zone_type": zone['zone_type'],
        "zone_type_label": zone['zone_type_label'],
        "warehouse": zone['warehouse'],
        "camera_id": camera_id,
        "camera_code": camera_code,
        "camera_name": cam_row['name'],
        "camera_location": cam_row['location'],
        "roi": {
            "id": d['id'],
            "shape_type": d['shape_type'],
            "coordinates": coords,
            "point_count": len(coords),
            "created_at": d['created_at'],
            "updated_at": d['updated_at']
        }
    }, None

def save_zone_camera_roi(zone_identifier, camera_identifier, data):
    from datetime import datetime
    import json

    zone = get_vision_zone(zone_identifier)
    if not zone:
        return None, f"Zone '{zone_identifier}' not found."

    conn = get_db()
    cam_row = conn.execute(
        "SELECT camera_id, camera_code, name FROM cameras WHERE camera_id = ? OR camera_code = ?",
        (str(camera_identifier), str(camera_identifier))
    ).fetchone()
    if not cam_row:
        conn.close()
        return None, f"Camera '{camera_identifier}' not found in Camera Master."

    camera_id = cam_row['camera_id']
    camera_code = cam_row['camera_code']

    assoc = conn.execute(
        "SELECT id FROM vision_zone_cameras WHERE zone_id = ? AND camera_id = ?",
        (zone['id'], camera_id)
    ).fetchone()
    if not assoc:
        conn.close()
        return None, f"Camera '{camera_code}' is not associated with zone '{zone['zone_code']}'."

    shape_type = str(data.get('shape_type', 'POLYGON')).strip().upper()
    if shape_type not in ('POLYGON', 'RECTANGLE'):
        shape_type = 'POLYGON'

    raw_coords = data.get('coordinates', [])
    if not isinstance(raw_coords, list):
        conn.close()
        return None, "Coordinates must be provided as a list of points."

    min_pts = 4 if shape_type == 'RECTANGLE' else 3
    if len(raw_coords) < min_pts:
        conn.close()
        return None, f"At least {min_pts} points are required for a {shape_type.lower()}."

    clean_coords = []
    for idx, pt in enumerate(raw_coords):
        if not isinstance(pt, dict) or 'x' not in pt or 'y' not in pt:
            conn.close()
            return None, f"Point at index {idx} must be an object with 'x' and 'y' properties."
        try:
            x = float(pt['x'])
            y = float(pt['y'])
        except (ValueError, TypeError):
            conn.close()
            return None, f"Point at index {idx} contains non-numeric coordinates."

        # Coordinates must remain normalized between 0.0 and 1.0
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            conn.close()
            return None, f"Point at index {idx} has out-of-range coordinates ({x}, {y}). Coordinates must be normalized between 0.0 and 1.0."

        clean_coords.append({
            "x": round(x, 4),
            "y": round(y, 4)
        })

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coords_json = json.dumps(clean_coords)

    with conn:
        conn.execute("""
            INSERT INTO vision_zone_camera_rois (zone_id, camera_id, shape_type, coordinates, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(zone_id, camera_id) DO UPDATE SET
                shape_type = excluded.shape_type,
                coordinates = excluded.coordinates,
                updated_at = excluded.updated_at
        """, (zone['id'], camera_id, shape_type, coords_json, now, now))
    conn.close()

    res, _ = get_zone_camera_roi(zone['id'], camera_id)
    return res, None

def delete_zone_camera_roi(zone_identifier, camera_identifier):
    zone = get_vision_zone(zone_identifier)
    if not zone:
        return False, f"Zone '{zone_identifier}' not found."

    conn = get_db()
    cam_row = conn.execute(
        "SELECT camera_id FROM cameras WHERE camera_id = ? OR camera_code = ?",
        (str(camera_identifier), str(camera_identifier))
    ).fetchone()
    if not cam_row:
        conn.close()
        return False, f"Camera '{camera_identifier}' not found."

    with conn:
        conn.execute(
            "DELETE FROM vision_zone_camera_rois WHERE zone_id = ? AND camera_id = ?",
            (zone['id'], cam_row['camera_id'])
        )
    conn.close()
    return True, None

def get_camera_rois(camera_identifier):
    """
    Retrieve all configured zone ROIs for a given camera across all zones.
    """
    import json
    conn = get_db()
    cam_row = conn.execute(
        "SELECT camera_id, camera_code FROM cameras WHERE camera_id = ? OR camera_code = ?",
        (str(camera_identifier), str(camera_identifier))
    ).fetchone()
    if not cam_row:
        conn.close()
        return []

    camera_id = cam_row['camera_id']
    rows = conn.execute("""
        SELECT r.*, z.zone_code, z.zone_name, z.zone_type, z.warehouse
        FROM vision_zone_camera_rois r
        JOIN vision_zones z ON z.id = r.zone_id
        WHERE r.camera_id = ?
    """, (camera_id,)).fetchall()
    conn.close()

    rois = []
    for row in rows:
        d = dict(row)
        try:
            coords = json.loads(d['coordinates'])
        except Exception:
            coords = []
        rois.append({
            "id": d['id'],
            "zone_id": d['zone_id'],
            "zone_code": d['zone_code'],
            "zone_name": d['zone_name'],
            "zone_type": d['zone_type'],
            "warehouse": d['warehouse'],
            "shape_type": d['shape_type'],
            "coordinates": coords
        })
    return rois

def get_zone_rois(zone_identifier):
    zone = get_vision_zone(zone_identifier)
    if not zone:
        return None, f"Zone '{zone_identifier}' not found."

    rois = []
    for c in zone.get('cameras', []):
        roi_data, _ = get_zone_camera_roi(zone['id'], c['camera_id'])
        if roi_data and roi_data.get('configured'):
            rois.append(roi_data)
    return rois, None



def get_all_bins():
    conn = get_db()
    cursor = conn.execute('''
        SELECT b.bin_id, b.zone, b.max_volume, b.current_volume, b.max_weight, b.current_weight, b.status, 
               COALESCE(SUM(i.quantity), 0) as stock_count,
               GROUP_CONCAT(DISTINCT i.vendor) as vendor
        FROM bins b
        LEFT JOIN inventory i ON b.bin_id = i.bin_id
        GROUP BY b.bin_id
        ORDER BY b.bin_id ASC
    ''')
    bins = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return bins


def get_bin_inventory(bin_id):
    conn = get_db()
    cursor = conn.execute('''
        SELECT i.id, i.bin_id, i.sku_id, i.quantity, i.batch_number, i.expiry_date, i.vendor, i.received_date,
               s.name as sku_name, s.category, s.unit_volume, s.unit_weight
        FROM inventory i
        LEFT JOIN skus s ON i.sku_id = s.sku_id
        WHERE i.bin_id = ?
        ORDER BY i.received_date DESC
    ''', (bin_id,))
    inventory = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return inventory

def add_bin(bin_id, zone, max_volume, max_weight):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO bins (bin_id, zone, max_volume, max_weight, status, last_updated)
            VALUES (?, ?, ?, ?, 'Active', CURRENT_TIMESTAMP)
        ''', (bin_id, zone, max_volume, max_weight))
    conn.close()

def get_all_skus():
    conn = get_db()
    cursor = conn.execute("SELECT * FROM skus ORDER BY sku_id ASC")
    skus = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return skus

def add_sku(sku_id, name, description, category, unit_weight, unit_volume):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO skus (sku_id, name, description, category, unit_weight, unit_volume, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (sku_id, name, description, category, unit_weight, unit_volume))
    conn.close()

def update_bin_stock(bin_id, vendor, count, sku_id='UNKNOWN-SKU'):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO bins (bin_id, status, last_updated)
            VALUES (?, 'Active', CURRENT_TIMESTAMP)
            ON CONFLICT(bin_id) DO NOTHING
        ''', (bin_id,))
        
        conn.execute('''
            INSERT INTO skus (sku_id, name, description)
            VALUES (?, ?, 'Auto-generated SKU')
            ON CONFLICT(sku_id) DO NOTHING
        ''', (sku_id, f"Item {sku_id}"))

        conn.execute('''
            INSERT INTO inventory (bin_id, sku_id, quantity, vendor, received_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (bin_id, sku_id, count, vendor))
        
        # Look up SKU sizes dynamically
        sku = conn.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
        vol_per_unit = sku['unit_volume'] if sku else 1.5
        wt_per_unit = sku['unit_weight'] if sku else 2.0

        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (count * vol_per_unit, count * wt_per_unit, bin_id))
    conn.close()


def intelligent_putaway(total_unloaded, vendor_name, sku_id='UNKNOWN-SKU'):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Ensure SKU exists and get its unit metrics
    sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
    if not sku:
        cursor.execute("INSERT INTO skus (sku_id, name, unit_volume, unit_weight) VALUES (?, ?, 1.5, 2.0)", (sku_id, f"Item {sku_id}"))
        conn.commit()
        vol_per_unit = 1.5
        wt_per_unit = 2.0
    else:
        vol_per_unit = sku['unit_volume']
        wt_per_unit = sku['unit_weight']
        
    req_vol = total_unloaded * vol_per_unit
    req_wt = total_unloaded * wt_per_unit
    
    # 2. Find the best bin
    # Criteria: Has enough space (vol and weight). Order by least free space first (to fill bins up).
    best_bin = cursor.execute('''
        SELECT bin_id 
        FROM bins 
        WHERE status = 'Active' 
          AND (max_volume - current_volume) >= ?
          AND (max_weight - current_weight) >= ?
        ORDER BY (max_volume - current_volume) ASC
        LIMIT 1
    ''', (req_vol, req_wt)).fetchone()
    
    if best_bin:
        chosen_bin = best_bin['bin_id']
    else:
        # Fallback: Create a new Overflow bin
        import uuid
        chosen_bin = "BIN-OVERFLOW-" + str(uuid.uuid4())[:4].upper()
        cursor.execute('''
            INSERT INTO bins (bin_id, zone, max_volume, max_weight) 
            VALUES (?, 'Overflow', 500.0, 5000.0)
        ''', (chosen_bin,))
        conn.commit()
        
    conn.close()
    
    # 3. Perform the stock update using the chosen bin
    update_bin_stock(chosen_bin, vendor_name, total_unloaded, sku_id)
    return chosen_bin
