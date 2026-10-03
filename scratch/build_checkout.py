import os

# 1. Update app.py
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

checkout_endpoint = """
@app.route('/api/gate/checkout/<gp_id>', methods=['POST'])
def checkout_gate_pass(gp_id):
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE gate_passes SET status = 'Exited', exit_time = CURRENT_TIMESTAMP WHERE id = ?", (gp_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Vehicle {gp_id} successfully checked out and exited."})
"""
if 'def checkout_gate_pass' not in app_py:
    app_py = app_py.replace("if __name__ == '__main__':", checkout_endpoint + "\nif __name__ == '__main__':")

with open('webapp/app.py', 'w', encoding='utf-8') as f:
    f.write(app_py)

# 2. Update index.html
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add a "Check Out" button to the gate passes if status == 'Completed'
# Need to find how gate passes are rendered in JS (app_logic.js)
