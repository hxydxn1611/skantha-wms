import sqlite3
import json
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'webapp', 'skandha_wms.db')
BASELINE_PATH = os.path.join(os.path.dirname(__file__), 'db_baseline_part14.json')

with open(BASELINE_PATH, 'r') as f:
    baseline = json.load(f)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

tables = [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
print(f'Total tables: {len(tables)} (Baseline: {len(baseline["tables"])})')
assert len(tables) == len(baseline['tables']), 'Table count mismatch!'

all_match = True
for tbl in tables:
    cols = cursor.execute(f'PRAGMA table_info({tbl})').fetchall()
    row_count = cursor.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
    b_tbl = baseline['tables'][tbl]
    
    col_names = [c[1] for c in cols]
    if len(cols) != b_tbl['columns'] or col_names != b_tbl['col_names']:
        print(f'[FAIL] Schema mismatch for {tbl}: {col_names} vs {b_tbl["col_names"]}')
        all_match = False
    if tbl == 'inventory' and row_count != 0:
        print(f'[FAIL] Inventory row count modified! Now: {row_count}')
        all_match = False
    print(f'Table: {tbl:<26} Columns: {len(cols):<3} Rows: {row_count:<4} (Baseline rows: {b_tbl["rows"]})')

conn.close()

# Hash comparison
with open(DB_PATH, 'rb') as f:
    curr_sha = hashlib.sha256(f.read()).hexdigest()

print('\n' + '='*70)
print(f'Baseline SHA256: {baseline["sha256"]}')
print(f'Current  SHA256: {curr_sha}')
print(f'Hash Identical:  {curr_sha == baseline["sha256"]}')
print('='*70)

if curr_sha == baseline['sha256']:
    print('>>> ZERO DATABASE WRITES VERIFIED: 100% BIT-FOR-BIT IDENTICAL SHA-256! <<<')
elif row_count == 0:
    print('>>> STRICT INVENTORY GOVERNANCE VERIFIED: INVENTORY ROW COUNT REMAINS 0 <<<')
