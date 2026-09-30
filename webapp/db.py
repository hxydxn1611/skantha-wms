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
        CREATE TABLE IF NOT EXISTS gate_passes (
            id TEXT PRIMARY KEY,
            po_number TEXT,
            plate TEXT NOT NULL,
            vehicle_type TEXT DEFAULT 'Unknown',
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

        -- Attempt to add columns for existing databases
        -- SQLite will error if they already exist, which is fine in exec script if we catch it, but execscript aborts on error.
        -- Better to do it via python try-except.
        
        CREATE INDEX IF NOT EXISTS idx_deliveries_plate ON expected_deliveries(plate);
        CREATE INDEX IF NOT EXISTS idx_deliveries_status ON expected_deliveries(status);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_po ON gate_passes(po_number);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_plate ON gate_passes(plate);
        CREATE INDEX IF NOT EXISTS idx_gate_passes_status ON gate_passes(status);
        """)
        
        # Alter existing tables if needed
        columns_expected = ['vendor_email', 'driver_phone']
        for col in columns_expected:
            try:
                conn.execute(f"ALTER TABLE expected_deliveries ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
                
        columns_gp = ['driver_phone', 'vendor_email', 'otp', 'exit_time']
        for col in columns_gp:
            try:
                conn.execute(f"ALTER TABLE gate_passes ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE gate_passes ADD COLUMN otp_verified INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    conn.close()

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
        "vendor": d.get("vendor") or "Unknown",
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
        "vehicle_type": d.get("vehicle_type") or "Unknown",
        "driver_name": d.get("driver_name") or "Awaiting Input",
        "driver_phone": d.get("driver_phone") or "",
        "vendor": d.get("vendor") or "Unknown",
        "vendor_email": d.get("vendor_email") or "",
        "load": d.get("load_description") or "Awaiting Input",
        "activity": d.get("activity") or "Loading",
        "expected_date": d.get("expected_date") or "",
        "arrival_date": d.get("arrival_date") or "",
        "time": d.get("arrival_time") or "",
        "status": d.get("status") or "Pending",
        "dock": d.get("dock") or "Not Assigned",
        "photo": d.get("photo") or "",
        "unloaded_qty": d.get("unloaded_qty") or 0,
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
        load_desc = data.get("load") or ""
        vendor = data.get("vendor") or ""
        activity = data.get("activity") or "Unloading"
        sheet = data.get("unloading_sheet") or []
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
        vehicle_type = data.get('type') or 'Unknown'
        photo = data.get('photo') or ''
        driver_name = data.get('driver_name') or 'Awaiting Input'
        driver_phone = data.get('driver_phone') or ''
        load_info = data.get('load') or 'Awaiting Input'
        vendor = data.get('vendor') or 'Unknown'
        vendor_email = data.get('vendor_email') or ''
        expected_date = data.get('expected_date') or ''
        po_number = (data.get('po_number') or '').strip()
        activity = data.get('activity') or 'Loading'
        unloading_sheet = data.get('unloading_sheet') or []
        otp = data.get('otp') or ''

        # CONNECTION LOGIC:
        # 1. Match by Plate if plate is available
        matched_deliv = None
        if plate and plate != "MANUAL-ENTRY":
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
            if driver_name == 'Awaiting Input' and matched_deliv['driver_name']:
                driver_name = matched_deliv['driver_name']
            if not driver_phone and matched_deliv['driver_phone']:
                driver_phone = matched_deliv['driver_phone']
            if load_info == 'Awaiting Input' and matched_deliv['load_description']:
                load_info = matched_deliv['load_description']
            if not expected_date and matched_deliv['expected_date']:
                expected_date = matched_deliv['expected_date']
            if vendor == 'Unknown' and matched_deliv['vendor']:
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

        conn.execute("""
            INSERT INTO gate_passes
            (id, po_number, plate, vehicle_type, driver_name, driver_phone, vendor, vendor_email, load_description,
             activity, expected_date, arrival_date, arrival_time, status, dock, photo,
             unloaded_qty, bin_allocation, unloading_sheet, otp, otp_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, po_number or None, plate, vehicle_type, driver_name, driver_phone, vendor, vendor_email, load_info,
              activity, expected_date, arrival_date, arrival_time, 'Pending', 'Not Assigned', photo,
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
                unloaded_qty = ?, activity = ?, bin_allocation = ?, photo = ?,
                unloading_sheet = ?
            WHERE id = ?
        """, (plate, driver_name, load_desc, vendor, status, dock, expected_date,
              po_number or None, unloaded_qty, activity, bin_allocation, photo, sheet_str, gp_id))
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
