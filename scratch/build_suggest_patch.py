import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

# Fix suggest_bin to read SKU from unloading sheet
old_suggest = """    vendor_name = gp.get('vendor', 'UNKNOWN')
    sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
    
    # We don't commit the putaway yet, we just simulate the selection
    conn = db.get_db()
    cursor = conn.cursor()"""
    
new_suggest = """    vendor_name = gp.get('vendor', 'UNKNOWN')
    sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
    import json
    try:
        sheet_str = gp.get('unloading_sheet')
        sheet = json.loads(sheet_str) if isinstance(sheet_str, str) else sheet_str
        if sheet and len(sheet) > 0 and 'sku' in sheet[0]:
            sku_id = sheet[0]['sku']
    except: pass
    
    # We don't commit the putaway yet, we just simulate the selection
    conn = db.get_db()
    cursor = conn.cursor()"""

if 'import json' not in old_suggest and 'sheet_str = gp.get(\'unloading_sheet\')' not in app_py:
    app_py = app_py.replace(old_suggest, new_suggest)

with open('webapp/app.py', 'w', encoding='utf-8') as f:
    f.write(app_py)
    
print("suggest_bin SKU lookup fixed.")
