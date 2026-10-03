import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

# I will cleanly replace the whole update_bin_stock function.
import re

old_func = re.search(r'def update_bin_stock.*?conn\.close\(\)', db_py, re.DOTALL).group(0)

new_func = """def update_bin_stock(bin_id, vendor, count, sku_id='UNKNOWN-SKU'):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO bins (bin_id, status, last_updated)
            VALUES (?, 'Active', CURRENT_TIMESTAMP)
            ON CONFLICT(bin_id) DO NOTHING
        ''', (bin_id,))
        
        conn.execute('''
            INSERT INTO skus (sku_id, name, description, units_per_bundle)
            VALUES (?, ?, 'Auto-generated SKU', 1)
            ON CONFLICT(sku_id) DO NOTHING
        ''', (sku_id, f"Item {sku_id}"))

        # Look up SKU sizes and bundle info dynamically
        sku = conn.execute("SELECT unit_volume, unit_weight, units_per_bundle FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
        vol_per_unit = sku['unit_volume'] if sku else 1.5
        wt_per_unit = sku['unit_weight'] if sku else 2.0
        
        # Determine the bundle multiplier. 
        # If the SKU has units_per_bundle, multiply the visual "bundle" count by it.
        bundle_multiplier = 1
        if sku and 'units_per_bundle' in sku.keys() and sku['units_per_bundle'] is not None:
            bundle_multiplier = sku['units_per_bundle']
            
        actual_count = count * bundle_multiplier

        conn.execute('''
            INSERT INTO inventory (bin_id, sku_id, quantity, vendor, received_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (bin_id, sku_id, actual_count, vendor))

        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (actual_count * vol_per_unit, actual_count * wt_per_unit, bin_id))
    conn.close()"""

db_py = db_py.replace(old_func, new_func)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("update_bin_stock correctly rewritten.")
