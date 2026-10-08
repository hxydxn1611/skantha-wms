with open('webapp/db.py', 'r') as f:
    db_code = f.read()

old_code = """        load_desc = data.get("load") or ""
        vendor = data.get("vendor") or ""
        activity = data.get("activity") or "Unloading"
        sheet = data.get("unloading_sheet") or []
        sheet_json = json.dumps(sheet) if isinstance(sheet, (list, dict)) else str(sheet)"""

new_code = """        activity = data.get("activity") or "Unloading"
        sheet = data.get("unloading_sheet") or []
        
        # Aggregate manifest data if empty
        load_desc = data.get("load") or ""
        vendor = data.get("vendor") or ""
        if not load_desc and isinstance(sheet, list):
            load_desc = ", ".join(list(set([str(item.get('sku_id', '')) for item in sheet if isinstance(item, dict)])))
        if not vendor and isinstance(sheet, list):
            vendor = ", ".join(list(set([str(item.get('vendor', '')) for item in sheet if isinstance(item, dict)])))
            
        sheet_json = json.dumps(sheet) if isinstance(sheet, (list, dict)) else str(sheet)"""

db_code = db_code.replace(old_code, new_code)

with open('webapp/db.py', 'w') as f:
    f.write(db_code)
print("Patched create_delivery in db.py")
