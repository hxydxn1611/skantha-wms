import sqlite3
import hashlib
import json
import os

db_path = 'webapp/skandha_wms.db'
if os.path.exists(db_path):
    with open(db_path, 'rb') as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()
    print(f"DB SHA256: {sha256}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    tables = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    table_names = [t[0] for t in tables]
    print(f"Total user tables: {len(table_names)}")
    
    stats = {}
    for t in table_names:
        cols = c.execute(f"PRAGMA table_info({t})").fetchall()
        row_count = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        stats[t] = {
            "columns": len(cols),
            "col_names": [col[1] for col in cols],
            "rows": row_count
        }
    
    print(json.dumps(stats, indent=2))
    conn.close()
    
    # Save to a baseline file for exact post-comparison
    with open('scratch/db_baseline_part14.json', 'w') as bf:
        json.dump({"sha256": sha256, "tables": stats}, bf, indent=2)
    print("Baseline saved to scratch/db_baseline_part14.json")
else:
    print(f"Error: {db_path} not found")
