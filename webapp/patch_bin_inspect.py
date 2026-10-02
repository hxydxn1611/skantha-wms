import re

with open('webapp/db.py', 'r') as f:
    db_code = f.read()

get_bin_inventory_code = """
def get_bin_inventory(bin_id):
    conn = get_db()
    cursor = conn.execute('''
        SELECT i.id, i.bin_id, i.sku_id, i.quantity, i.batch_number, i.expiry_date, i.vendor, i.received_date,
               s.name as sku_name, s.category, s.unit_volume, s.unit_weight
        FROM inventory i
        LEFT JOIN sku_master s ON i.sku_id = s.sku_id
        WHERE i.bin_id = ?
        ORDER BY i.received_date DESC
    ''', (bin_id,))
    inventory = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return inventory

"""

if "def get_bin_inventory(" not in db_code:
    db_code = db_code.replace("def add_bin(", get_bin_inventory_code + "def add_bin(")
    with open('webapp/db.py', 'w') as f:
        f.write(db_code)
    print("Added get_bin_inventory to db.py")

with open('webapp/app.py', 'r') as f:
    app_code = f.read()

api_route_code = """
@app.route('/api/bins/<bin_id>/inventory', methods=['GET'])
def api_get_bin_inventory(bin_id):
    try:
        inventory = db.get_bin_inventory(bin_id)
        return jsonify(inventory)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

"""

if "def api_get_bin_inventory(" not in app_code:
    app_code = app_code.replace("@app.route('/api/skus', methods=['GET', 'POST'])", api_route_code + "@app.route('/api/skus', methods=['GET', 'POST'])")
    with open('webapp/app.py', 'w') as f:
        f.write(app_code)
    print("Added api_get_bin_inventory to app.py")
