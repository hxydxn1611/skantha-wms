import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

# Add manifest generation endpoints
manifest_routes = """
@app.route('/api/gate/<gp_id>/manifest', methods=['GET'])
def get_gate_manifest(gp_id):
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return "Gate pass not found", 404
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Skandha WMS - Gate Pass Manifest", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Gate Pass ID: {gp_id}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Vehicle Plate: {gp.get('plate')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Driver Name: {gp.get('driver_name', 'N/A')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Vendor: {gp.get('vendor', 'N/A')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Status: {gp.get('status')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Total Unloaded: {gp.get('unloaded_qty', 0)}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Allocated Bin: {gp.get('bin_allocation', 'N/A')}", ln=1, align='L')
    
    pdf_filename = f"manifest_gate_{gp_id}.pdf"
    pdf_dir = os.path.join(os.path.dirname(__file__), "static", "manifests")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    pdf.output(pdf_path)
    
    return jsonify({"success": True, "url": f"/static/manifests/{pdf_filename}"})

@app.route('/api/outbound/<order_id>/manifest', methods=['GET'])
def get_outbound_manifest(order_id):
    conn = db.get_db()
    order = conn.execute("SELECT * FROM outbound_orders WHERE id = ?", (order_id,)).fetchone()
    items = conn.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    conn.close()
    
    if not order:
        return "Order not found", 404
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Skandha WMS - Outbound Manifest", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order ID: {order['id']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Customer: {order['customer_name']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Destination: {order['destination']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Status: {order['status']}", ln=1, align='L')
    pdf.cell(200, 10, txt="", ln=1, align='L')
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(60, 10, txt="SKU", border=1)
    pdf.cell(40, 10, txt="Required", border=1)
    pdf.cell(40, 10, txt="Picked", border=1)
    pdf.cell(40, 10, txt="Status", border=1, ln=1)
    
    pdf.set_font("Arial", size=12)
    for item in items:
        status = "FULFILLED" if item['picked_quantity'] >= item['quantity'] else "PENDING"
        pdf.cell(60, 10, txt=str(item['sku_id']), border=1)
        pdf.cell(40, 10, txt=str(item['quantity']), border=1)
        pdf.cell(40, 10, txt=str(item['picked_quantity']), border=1)
        pdf.cell(40, 10, txt=status, border=1, ln=1)
        
    pdf_filename = f"manifest_outbound_{order_id}.pdf"
    pdf_dir = os.path.join(os.path.dirname(__file__), "static", "manifests")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    pdf.output(pdf_path)
    
    return jsonify({"success": True, "url": f"/static/manifests/{pdf_filename}"})
"""

if '@app.route(\'/api/outbound/<order_id>/manifest\'' not in app_py:
    app_py += "\n" + manifest_routes
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)
        
print("Manifest endpoints injected in backend.")
