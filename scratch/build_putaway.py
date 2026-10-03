import os

# 1. Update webapp/db.py to add intelligent_putaway
with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

intelligent_putaway_func = """
def intelligent_putaway(total_unloaded, vendor_name, sku_id='UNKNOWN-SKU'):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Ensure SKU exists and get its unit metrics
    sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
    if not sku:
        cursor.execute("INSERT INTO skus (sku_id, name, unit_volume, unit_weight) VALUES (?, ?, 1.5, 2.0)", (sku_id, f"Item {sku_id}"))
        conn.commit()
        vol_per_unit = 1.5
        wt_per_unit = 2.0
    else:
        vol_per_unit = sku['unit_volume']
        wt_per_unit = sku['unit_weight']
        
    req_vol = total_unloaded * vol_per_unit
    req_wt = total_unloaded * wt_per_unit
    
    # 2. Find the best bin
    # Criteria: Has enough space (vol and weight). Order by least free space first (to fill bins up).
    best_bin = cursor.execute('''
        SELECT bin_id 
        FROM bins 
        WHERE status = 'Active' 
          AND (max_volume - current_volume) >= ?
          AND (max_weight - current_weight) >= ?
        ORDER BY (max_volume - current_volume) ASC
        LIMIT 1
    ''', (req_vol, req_wt)).fetchone()
    
    if best_bin:
        chosen_bin = best_bin['bin_id']
    else:
        # Fallback: Create a new Overflow bin
        import uuid
        chosen_bin = "BIN-OVERFLOW-" + str(uuid.uuid4())[:4].upper()
        cursor.execute('''
            INSERT INTO bins (bin_id, zone, max_volume, max_weight) 
            VALUES (?, 'Overflow', 500.0, 5000.0)
        ''', (chosen_bin,))
        conn.commit()
        
    conn.close()
    
    # 3. Perform the stock update using the chosen bin
    update_bin_stock(chosen_bin, vendor_name, total_unloaded, sku_id)
    return chosen_bin
"""

if 'def intelligent_putaway' not in db_py:
    db_py += "\n" + intelligent_putaway_func
    with open('webapp/db.py', 'w', encoding='utf-8') as f:
        f.write(db_py)

# 2. Update webapp/app.py in unload_step
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

old_unload = """    gp = db.set_unload_qty(gp_id, total_unloaded)
    if gp:
        # Auto-update Bin Master with Vendor Stock
        vendor_name = gp.get('vendor', 'UNKNOWN')
        bin_id = f"BIN-{vendor_name[:3].upper()}-100" if vendor_name else "BIN-GEN-100"
        try:
            db.update_bin_stock(bin_id, vendor_name, total_unloaded)
        except Exception as e:
            print("Failed to update bin stock:", e)
        return jsonify({"success": True, "total": gp['unloaded_qty']})"""

new_unload = """    gp = db.set_unload_qty(gp_id, total_unloaded)
    if gp:
        # Intelligent Putaway Engine
        vendor_name = gp.get('vendor', 'UNKNOWN')
        sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
        try:
            chosen_bin = db.intelligent_putaway(total_unloaded, vendor_name, sku_id)
            db.update_gate_pass(gp_id, {"bin_allocation": chosen_bin})
        except Exception as e:
            print("Failed to execute intelligent putaway:", e)
            chosen_bin = "ERROR"
            
        return jsonify({"success": True, "total": gp['unloaded_qty'], "allocated_bin": chosen_bin})"""

if 'db.intelligent_putaway(' not in app_py:
    app_py = app_py.replace(old_unload, new_unload)
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)

print("Intelligent Putaway Engine injected.")
