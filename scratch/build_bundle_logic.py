import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

old_stock = """        # Look up SKU sizes dynamically
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
        
new_stock = """        # Look up SKU sizes and bundle info dynamically
        sku = conn.execute("SELECT unit_volume, unit_weight, units_per_bundle FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
        vol_per_unit = sku['unit_volume'] if sku else 1.5
        wt_per_unit = sku['unit_weight'] if sku else 2.0
        bundle_multiplier = sku['units_per_bundle'] if (sku and 'units_per_bundle' in sku.keys()) else 1
        
        # We count bundles visually. Exact items = bundles * multiplier
        actual_count = count * bundle_multiplier

        conn.execute('''
            UPDATE inventory SET quantity = ? WHERE bin_id = ? AND sku_id = ? AND quantity = ?
        ''', (actual_count, bin_id, sku_id, count))

        conn.execute('''
            UPDATE bins 
            SET current_volume = current_volume + ?,
                current_weight = current_weight + ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE bin_id = ?
        ''', (actual_count * vol_per_unit, actual_count * wt_per_unit, bin_id))"""

if 'bundle_multiplier' not in db_py:
    db_py = db_py.replace(old_stock, new_stock)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("db.py update_bin_stock updated with bundle_multiplier.")
