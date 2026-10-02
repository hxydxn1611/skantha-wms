import re

# 1. Update app.py
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_content = f.read()

new_endpoints = """
@app.route('/api/bins', methods=['POST'])
def api_add_bin():
    data = request.json
    try:
        db.add_bin(data['bin_id'], data.get('zone', 'General'), data.get('max_volume', 100.0), data.get('max_weight', 1000.0))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/skus', methods=['GET'])
def api_get_skus():
    return jsonify(db.get_all_skus())

@app.route('/api/skus', methods=['POST'])
def api_add_sku():
    data = request.json
    try:
        db.add_sku(data['sku_id'], data['name'], data.get('description', ''), data.get('category', ''), data.get('unit_weight', 0.0), data.get('unit_volume', 0.0))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/bins', methods=['GET'])"""

if "@app.route('/api/bins', methods=['GET'])" in app_content and "def api_add_bin():" not in app_content:
    app_content = app_content.replace("@app.route('/api/bins', methods=['GET'])", new_endpoints)
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_content)
    print("Updated app.py")


# 2. Update db.py
with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_content = f.read()

db_funcs = """def get_all_bins():
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
    return bins

def add_bin(bin_id, zone, max_volume, max_weight):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO bins (bin_id, zone, max_volume, max_weight, status, last_updated)
            VALUES (?, ?, ?, ?, 'Active', CURRENT_TIMESTAMP)
        ''', (bin_id, zone, max_volume, max_weight))
    conn.close()

def get_all_skus():
    conn = get_db()
    cursor = conn.execute("SELECT * FROM skus ORDER BY sku_id ASC")
    skus = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return skus

def add_sku(sku_id, name, description, category, unit_weight, unit_volume):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO skus (sku_id, name, description, category, unit_weight, unit_volume, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (sku_id, name, description, category, unit_weight, unit_volume))
    conn.close()"""

if "def add_bin" not in db_content:
    old_get_bins = r"def get_all_bins\(\):.*?return bins"
    db_content = re.sub(old_get_bins, db_funcs, db_content, flags=re.DOTALL)
    with open('webapp/db.py', 'w', encoding='utf-8') as f:
        f.write(db_content)
    print("Updated db.py")
