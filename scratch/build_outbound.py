import os
import re

# 1. Update db.py to add Outbound Tables
with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

outbound_sql = """
        -- Outbound Orders
        CREATE TABLE IF NOT EXISTS outbound_orders (
            id TEXT PRIMARY KEY,
            customer_name TEXT,
            destination TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Outbound Items
        CREATE TABLE IF NOT EXISTS outbound_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            sku_id TEXT,
            quantity INTEGER DEFAULT 0,
            picked_quantity INTEGER DEFAULT 0,
            FOREIGN KEY(order_id) REFERENCES outbound_orders(id),
            FOREIGN KEY(sku_id) REFERENCES skus(sku_id)
        );
"""
if 'outbound_orders' not in db_py:
    # Inject right before the try block for alter tables
    db_py = db_py.replace('-- Attempt to add columns for existing databases', outbound_sql + '\n        -- Attempt to add columns for existing databases')
    with open('webapp/db.py', 'w', encoding='utf-8') as f:
        f.write(db_py)

# 2. Update app.py to add Outbound API routes
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

outbound_api = """
# ==========================================
# OUTBOUND FLOW LOGIC
# ==========================================
import uuid

@app.route('/api/outbound', methods=['GET', 'POST'])
def handle_outbound():
    conn = db.get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        order_id = "OUT-" + str(uuid.uuid4())[:8].upper()
        customer = data.get('customer_name', 'Unknown')
        destination = data.get('destination', 'Unknown')
        items = data.get('items', []) # [{"sku_id": "SKU-1", "quantity": 10}]
        
        cursor.execute("INSERT INTO outbound_orders (id, customer_name, destination) VALUES (?, ?, ?)",
                       (order_id, customer, destination))
        
        for item in items:
            cursor.execute("INSERT INTO outbound_items (order_id, sku_id, quantity) VALUES (?, ?, ?)",
                           (order_id, item['sku_id'], int(item['quantity'])))
        
        conn.commit()
        conn.close()
        return jsonify({"success": True, "order_id": order_id})
        
    else:
        orders = cursor.execute("SELECT * FROM outbound_orders ORDER BY created_at DESC").fetchall()
        result = []
        for o in orders:
            items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (o['id'],)).fetchall()
            order_dict = dict(o)
            order_dict['items'] = [dict(i) for i in items]
            result.append(order_dict)
        conn.close()
        return jsonify(result)

@app.route('/api/outbound/<order_id>/pick', methods=['POST'])
def pick_outbound(order_id):
    conn = db.get_db()
    cursor = conn.cursor()
    
    order = cursor.execute("SELECT * FROM outbound_orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order['status'] == 'Fulfilled':
        return jsonify({"success": False, "error": "Invalid or fulfilled order"})
        
    items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    
    # Simple picking logic: just find any bin with the SKU and deduct
    for item in items:
        needed = item['quantity'] - item['picked_quantity']
        if needed <= 0:
            continue
            
        invs = cursor.execute("SELECT * FROM inventory WHERE sku_id = ? AND quantity > 0", (item['sku_id'],)).fetchall()
        for inv in invs:
            if needed <= 0:
                break
            
            take = min(inv['quantity'], needed)
            # Update inventory
            cursor.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (take, inv['id']))
            # Update Bin capacities
            sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (item['sku_id'],)).fetchone()
            vol_red = sku['unit_volume'] * take
            wt_red = sku['unit_weight'] * take
            cursor.execute("UPDATE bins SET current_volume = MAX(0, current_volume - ?), current_weight = MAX(0, current_weight - ?) WHERE bin_id = ?", (vol_red, wt_red, inv['bin_id']))
            
            needed -= take
            
        cursor.execute("UPDATE outbound_items SET picked_quantity = ? WHERE id = ?", (item['quantity'] - needed, item['id']))
    
    # Check if fully picked
    all_picked = True
    rem_items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    for i in rem_items:
        if i['picked_quantity'] < i['quantity']:
            all_picked = False
            
    if all_picked:
        cursor.execute("UPDATE outbound_orders SET status = 'Fulfilled' WHERE id = ?", (order_id,))
    else:
        cursor.execute("UPDATE outbound_orders SET status = 'Partially Picked' WHERE id = ?", (order_id,))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True, "status": "Fulfilled" if all_picked else "Partially Picked"})

"""
if '/api/outbound' not in app_py:
    app_py = app_py.replace("if __name__ == '__main__':", outbound_api + "\nif __name__ == '__main__':")
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)


# 3. Update index.html safely
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add Outbound Tab
tab_html = '<button class="tab-btn" onclick="switchTab(\'outbound\')">Outbound Flow</button>'
if 'switchTab(\'outbound\')' not in html:
    html = html.replace("<!-- AI Vision Master Hidden -->", tab_html + "\n                <!-- AI Vision Master Hidden -->")

# Add Outbound View
outbound_view = """
        <!-- OUTBOUND VIEW -->
        <div id="outbound-view" class="view-section">
            <div style="display:flex; gap:2rem;">
                <aside class="glass-panel" style="flex:0 0 400px; height:fit-content;">
                    <h3>Create Outbound Order</h3>
                    <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;">Generate a new picking requirement.</p>
                    <form id="formAddOutbound" onsubmit="event.preventDefault(); submitAddOutbound();">
                        <div style="margin-bottom:1rem;">
                            <label>Customer Name *</label>
                            <input type="text" id="outboundCustomer" required style="width:100%; margin-bottom:0;">
                        </div>
                        <div style="margin-bottom:1rem;">
                            <label>Destination *</label>
                            <input type="text" id="outboundDest" required style="width:100%; margin-bottom:0;">
                        </div>
                        <div style="margin-bottom:1rem;">
                            <label>Select SKU *</label>
                            <select id="outboundSku" required style="width:100%; margin-bottom:0;"></select>
                        </div>
                        <div style="margin-bottom:1.5rem;">
                            <label>Quantity to Pick *</label>
                            <input type="number" id="outboundQty" required min="1" style="width:100%; margin-bottom:0;">
                        </div>
                        <button type="submit" class="btn-primary" style="width:100%;">Create Order</button>
                    </form>
                </aside>
                <div class="glass-panel" style="flex:1;">
                    <h3>Active Outbound Orders</h3>
                    <table style="width:100%; margin-top:1rem;">
                        <thead>
                            <tr>
                                <th>Order ID</th>
                                <th>Customer</th>
                                <th>Destination</th>
                                <th>Items</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="outboundTableBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
"""
if 'id="outbound-view"' not in html:
    html = html.replace('<!-- PRE-REGISTRATION (EXPECTED DELIVERIES) VIEW -->', outbound_view + '\n        <!-- PRE-REGISTRATION (EXPECTED DELIVERIES) VIEW -->')

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Backend and Frontend injected successfully.")
