import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

# Update db.update_gate_pass to execute putaway
old_update_gp = """        conn.execute(\"\"\"
            UPDATE gate_passes SET
                plate = ?, driver_name = ?, load_description = ?, vendor = ?,
                status = ?, dock = ?, expected_date = ?, po_number = ?,
                unloaded_qty = ?, activity = ?, bin_allocation = ?, photo = ?, driver_photo = ?,
                unloading_sheet = ?, driver_phone = ?, vendor_email = ?, otp = ?, otp_verified = ?, exit_time = ?
            WHERE id = ?
        \"\"\", (plate, driver_name, load_desc, vendor, status, dock, expected_date,
              po_number or None, unloaded_qty, activity, bin_allocation, photo, driver_photo, sheet_str, driver_phone, vendor_email, otp, otp_verified, exit_time, gp_id))
    conn.close()"""

new_update_gp = """        conn.execute(\"\"\"
            UPDATE gate_passes SET
                plate = ?, driver_name = ?, load_description = ?, vendor = ?,
                status = ?, dock = ?, expected_date = ?, po_number = ?,
                unloaded_qty = ?, activity = ?, bin_allocation = ?, photo = ?, driver_photo = ?,
                unloading_sheet = ?, driver_phone = ?, vendor_email = ?, otp = ?, otp_verified = ?, exit_time = ?
            WHERE id = ?
        \"\"\", (plate, driver_name, load_desc, vendor, status, dock, expected_date,
              po_number or None, unloaded_qty, activity, bin_allocation, photo, driver_photo, sheet_str, driver_phone, vendor_email, otp, otp_verified, exit_time, gp_id))
              
        # Execute putaway stock update when transitioning to Completed
        if status == 'Completed' and curr['status'] != 'Completed' and bin_allocation:
            vendor_name = vendor or 'UNKNOWN'
            sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
            # Look up SKU from unloading_sheet if available
            import json
            try:
                sheet = json.loads(sheet_str) if isinstance(sheet_str, str) else sheet_str
                if sheet and len(sheet) > 0 and 'sku' in sheet[0]:
                    sku_id = sheet[0]['sku']
            except: pass
            
            try:
                update_bin_stock(bin_allocation, vendor_name, unloaded_qty or 0, sku_id)
            except Exception as e:
                print("Failed to update bin stock automatically on completion:", e)
              
    conn.close()"""

if 'Execute putaway stock update when transitioning' not in db_py:
    db_py = db_py.replace(old_update_gp, new_update_gp)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("db.update_gate_pass updated to perform putaway.")
