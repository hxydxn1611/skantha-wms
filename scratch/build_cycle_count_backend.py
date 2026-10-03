import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

cycle_count_endpoint = """
@app.route('/api/cycle_count', methods=['POST'])
def run_cycle_count():
    data = request.json
    bin_id = data.get('bin_id')
    actual_qty = data.get('actual_qty')
    
    if bin_id is None or actual_qty is None:
        return jsonify({"success": False, "message": "Missing bin_id or actual_qty"})
        
    conn = db.get_db()
    with conn:
        # Get expected qty
        inv = conn.execute("SELECT quantity, sku_id, vendor FROM inventory WHERE bin_id = ?", (bin_id,)).fetchone()
        if not inv:
            return jsonify({"success": False, "message": f"No inventory found in bin {bin_id}"})
            
        expected_qty = inv['quantity']
        discrepancy = actual_qty - expected_qty
        
        if discrepancy == 0:
            msg = f"Audit complete. Count perfectly matches system (Qty: {actual_qty})."
        else:
            # Update the inventory to the actual audited count
            conn.execute("UPDATE inventory SET quantity = ? WHERE bin_id = ?", (actual_qty, bin_id))
            
            # Log the discrepancy in a hypothetical audit log
            conn.execute('''
                INSERT INTO activities (timestamp, action, target, details)
                VALUES (CURRENT_TIMESTAMP, 'CYCLE_COUNT_AUDIT', ?, ?)
            ''', (bin_id, f"Audited Qty: {actual_qty} (Discrepancy: {discrepancy})"))
            
            msg = f"Audit complete. Inventory adjusted. Discrepancy of {discrepancy} units recorded."
            
    conn.close()
    return jsonify({"success": True, "message": msg})
"""

if '@app.route(\'/api/cycle_count\'' not in app_py:
    app_py += "\n" + cycle_count_endpoint
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)
        
print("Cycle count backend injected.")
