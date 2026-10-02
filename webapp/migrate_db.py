import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skandha_wms.db')

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

try:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS inventory")
    conn.execute("DROP TABLE IF EXISTS skus")
    conn.execute("DROP TABLE IF EXISTS bins")
    conn.executescript(new_schema)
    conn.commit()
    conn.close()
    print("Database migrated successfully.")
except Exception as e:
    print(f"Migration error: {e}")
