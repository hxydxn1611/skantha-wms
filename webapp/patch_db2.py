import re

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_content = f.read()

# Replace get_all_bins
old_get_all_bins = r"""def get_all_bins\(\):.*?return bins"""
new_get_all_bins = """def get_all_bins():
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
    return bins"""

db_content = re.sub(old_get_all_bins, new_get_all_bins, db_content, flags=re.DOTALL)

# Replace old update_bin_stock
old_update_bin_stock = r"""def update_bin_stock\(bin_id, vendor, count\):.*?conn\.close\(\)"""
new_update_bin_stock = """def update_bin_stock(bin_id, vendor, count, sku_id='UNKNOWN-SKU'):
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
        
        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (count * 1.5, count * 2.0, bin_id))
    conn.close()"""

db_content = re.sub(old_update_bin_stock, new_update_bin_stock, db_content, flags=re.DOTALL)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_content)
print("Updated db.py functions successfully")
