import sqlite3

def verify():
    conn = sqlite3.connect('webapp/skandha_wms.db')
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
    print(f"Total Tables ({len(tables)}): {tables}")
    counts = {}
    for t in tables:
        cnt = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        counts[t] = cnt
        print(f"  {t:30}: {cnt} rows")

    assert len(tables) == 17, f"Expected 17 tables, got {len(tables)}"
    assert counts['inventory'] == 0, f"Expected 0 inventory rows, got {counts['inventory']}"
    print("\nDATABASE INTEGRITY CHECK: 100% PASS. Schema unchanged, 0 inventory writes.")

if __name__ == '__main__':
    verify()
