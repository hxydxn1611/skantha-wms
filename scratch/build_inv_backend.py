import os

# 1. Update app.py
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

inv_endpoints = """
@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = db.get_db()
    cursor = conn.cursor()
    items = cursor.execute('''
        SELECT i.*, s.name as sku_name, s.category, b.zone
        FROM inventory i
        LEFT JOIN skus s ON i.sku_id = s.sku_id
        LEFT JOIN bins b ON i.bin_id = b.bin_id
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in items])

@app.route('/api/inventory/<int:inv_id>', methods=['PUT'])
def update_inventory(inv_id):
    data = request.json
    new_qty = data.get('quantity')
    conn = db.get_db()
    cursor = conn.cursor()
    inv = cursor.execute("SELECT * FROM inventory WHERE id = ?", (inv_id,)).fetchone()
    if not inv:
        return jsonify({"success": False, "message": "Inventory record not found"})
        
    cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, inv_id))
    
    # Recalculate bin capacity
    bin_id = inv['bin_id']
    invs = cursor.execute("SELECT sku_id, quantity FROM inventory WHERE bin_id = ?", (bin_id,)).fetchall()
    total_vol = 0
    total_wt = 0
    for item in invs:
        sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (item['sku_id'],)).fetchone()
        if sku:
            total_vol += sku['unit_volume'] * item['quantity']
            total_wt += sku['unit_weight'] * item['quantity']
            
    cursor.execute("UPDATE bins SET current_volume = ?, current_weight = ? WHERE bin_id = ?", (total_vol, total_wt, bin_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Inventory updated and bin capacity recalculated"})
"""

if 'def get_inventory()' not in app_py:
    app_py = app_py.replace("if __name__ == '__main__':", inv_endpoints + "\nif __name__ == '__main__':")
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)
