import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

# Fix update_bin_stock to use dynamic SKU sizes instead of hardcoded 1.5 and 2.0
old_update_bin_stock = """        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (count * 1.5, count * 2.0, bin_id))"""
        
new_update_bin_stock = """        # Look up SKU sizes dynamically
        sku = conn.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
        vol_per_unit = sku['unit_volume'] if sku else 1.5
        wt_per_unit = sku['unit_weight'] if sku else 2.0

        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (count * vol_per_unit, count * wt_per_unit, bin_id))"""

if 'Look up SKU sizes dynamically' not in db_py:
    db_py = db_py.replace(old_update_bin_stock, new_update_bin_stock)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("update_bin_stock modified.")
