import sqlite3

# 1. Update the schema in db.py
with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_content = f.read()

old_bins_schema = """        CREATE TABLE IF NOT EXISTS bins (
            bin_id TEXT PRIMARY KEY,
            stock_count INTEGER DEFAULT 0,
            vendor TEXT,
            status TEXT DEFAULT 'Active',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );"""

new_schema = """        -- SKU Master
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
        );"""

if old_bins_schema in db_content:
    db_content = db_content.replace(old_bins_schema, new_schema)
    with open('webapp/db.py', 'w', encoding='utf-8') as f:
        f.write(db_content)
    print("Schema updated in db.py")
else:
    print("Could not find bins schema in db.py")

# 2. Update the update_bin_stock logic
old_update_bin = """def update_bin_stock(bin_id, quantity, vendor='Unknown'):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO bins (bin_id, vendor, stock_count, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(bin_id) DO UPDATE SET 
                stock_count = stock_count + ?, 
                vendor = excluded.vendor,
                last_updated = CURRENT_TIMESTAMP
        ''', (bin_id, vendor, quantity, quantity))
    conn.close()"""

new_update_bin = """def update_bin_stock(bin_id, quantity, vendor='Unknown', sku_id='UNKNOWN-SKU'):
    conn = get_db()
    with conn:
        # First ensure the bin exists
        conn.execute('''
            INSERT INTO bins (bin_id, status, last_updated)
            VALUES (?, 'Active', CURRENT_TIMESTAMP)
            ON CONFLICT(bin_id) DO NOTHING
        ''', (bin_id,))
        
        # Ensure SKU exists (fallback)
        conn.execute('''
            INSERT INTO skus (sku_id, name, description)
            VALUES (?, ?, 'Auto-generated SKU')
            ON CONFLICT(sku_id) DO NOTHING
        ''', (sku_id, f"Item {sku_id}"))

        # Add to inventory
        conn.execute('''
            INSERT INTO inventory (bin_id, sku_id, quantity, vendor, received_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (bin_id, sku_id, quantity, vendor))
        
        # Update bin capacity heuristics (simplified for now)
        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (quantity * 1.5, quantity * 2.0, bin_id))
    conn.close()"""

if old_update_bin in db_content:
    with open('webapp/db.py', 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace(old_update_bin, new_update_bin)
    with open('webapp/db.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print("update_bin_stock updated in db.py")
else:
    print("Could not find update_bin_stock logic")


# 3. Migrate the sqlite database directly
try:
    conn = sqlite3.connect('instance/app.db')
    conn.execute("DROP TABLE IF EXISTS inventory")
    conn.execute("DROP TABLE IF EXISTS skus")
    conn.execute("DROP TABLE IF EXISTS bins")
    conn.executescript(new_schema)
    conn.commit()
    conn.close()
    print("Database migrated successfully.")
except Exception as e:
    print(f"Migration error: {e}")
