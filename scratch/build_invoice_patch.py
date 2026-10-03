import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

# Update /api/gate/invoice
old_invoice_logic = """    pdf.cell(200, 10, txt=f"Total Items Unloaded: {qty}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Stored in Location: {bin_alloc}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Driver: {gp.get('driver_name')} | Plate: {gp.get('plate')}", ln=1, align='L')
    
    pdf_filename = f"invoice_{gp_id}.pdf\""""

new_invoice_logic = """    pdf.cell(200, 10, txt=f"Total Items Unloaded: {qty}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Stored in Location: {bin_alloc}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Driver: {gp.get('driver_name')} | Plate: {gp.get('plate')}", ln=1, align='L')
    
    # Render SKU details
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
        pdf.cell(170, 10, txt="No specific SKUs provided in PO sheet.", border=1, ln=1)
    
    pdf_filename = f"invoice_{gp_id}.pdf\""""

if 'Render SKU details' not in old_invoice_logic and 'pdf_filename = f"invoice_{gp_id}.pdf"' in app_py:
    # Let's be careful, I might replace the wrong thing. I'll just use the exact string.
    app_py = app_py.replace(old_invoice_logic, new_invoice_logic)

with open('webapp/app.py', 'w', encoding='utf-8') as f:
    f.write(app_py)

print("Invoice PDF logic updated.")
