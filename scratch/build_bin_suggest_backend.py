import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

# 1. Add /api/dock/suggest_bin route
suggest_bin_route = """
@app.route('/api/dock/suggest_bin/<gp_id>', methods=['GET'])
def suggest_bin(gp_id):
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found"})
        
    vendor_name = gp.get('vendor', 'UNKNOWN')
    sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
    
    # We don't commit the putaway yet, we just simulate the selection
    conn = db.get_db()
    cursor = conn.cursor()
    
    sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
    vol_per_unit = sku['unit_volume'] if sku else 1.5
    wt_per_unit = sku['unit_weight'] if sku else 2.0
    
    req_vol = gp.get('unloaded_qty', 0) * vol_per_unit
    req_wt = gp.get('unloaded_qty', 0) * wt_per_unit
    
    best_bin = cursor.execute('''
        SELECT bin_id 
        FROM bins 
        WHERE status = 'Active' 
          AND (max_volume - current_volume) >= ?
          AND (max_weight - current_weight) >= ?
        ORDER BY (max_volume - current_volume) ASC
        LIMIT 1
    ''', (req_vol, req_wt)).fetchone()
    
    conn.close()
    
    chosen_bin = best_bin['bin_id'] if best_bin else "BIN-OVERFLOW-NEW"
    return jsonify({"success": True, "suggested_bin": chosen_bin})
"""

if '@app.route(\'/api/dock/suggest_bin' not in app_py:
    app_py += "\n" + suggest_bin_route


# 2. Modify unload_step to NOT do putaway automatically. We only update count.
old_unload_step = """    gp = db.set_unload_qty(gp_id, total_unloaded)
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

new_unload_step = """    gp = db.set_unload_qty(gp_id, total_unloaded)
    if gp:
        return jsonify({"success": True, "total": gp['unloaded_qty']})"""

app_py = app_py.replace(old_unload_step, new_unload_step)


# 3. Add SKU to Manifest and Invoice PDFs
old_manifest_logic = """    pdf.cell(200, 10, txt=f"Status: {gp.get('status')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Total Unloaded: {gp.get('unloaded_qty', 0)}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Allocated Bin: {gp.get('bin_allocation', 'N/A')}", ln=1, align='L')"""

new_manifest_logic = """    pdf.cell(200, 10, txt=f"Status: {gp.get('status')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Total Unloaded: {gp.get('unloaded_qty', 0)}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Allocated Bin: {gp.get('bin_allocation', 'N/A')}", ln=1, align='L')
    
    # Render SKU details from unloading_sheet
    pdf.cell(200, 10, txt="", ln=1, align='L')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(80, 10, txt="SKU", border=1)
    pdf.cell(60, 10, txt="Description", border=1)
    pdf.cell(30, 10, txt="Expected", border=1, ln=1)
    
    pdf.set_font("Arial", size=12)
    sheet = gp.get('unloading_sheet')
    if sheet and isinstance(sheet, list):
        for item in sheet:
            pdf.cell(80, 10, txt=str(item.get('sku', '')), border=1)
            pdf.cell(60, 10, txt=str(item.get('description', ''))[:20], border=1)
            pdf.cell(30, 10, txt=str(item.get('expected', '')), border=1, ln=1)
    else:
        pdf.cell(170, 10, txt="No specific SKUs provided in PO sheet.", border=1, ln=1)"""

if 'Render SKU details from unloading_sheet' not in app_py:
    app_py = app_py.replace(old_manifest_logic, new_manifest_logic)

with open('webapp/app.py', 'w', encoding='utf-8') as f:
    f.write(app_py)

print("Backend bin suggestion and manifest SKU updates completed.")
