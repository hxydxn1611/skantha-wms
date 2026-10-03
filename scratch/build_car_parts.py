import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

# Replace SKU seeding to be automotive parts
old_sku_seed = """    # 2) SEED SKUs IF EMPTY
    cursor = conn.execute("SELECT COUNT(*) FROM skus")
    if cursor.fetchone()[0] == 0:
        add_sku('SKU-001', 'Widget A', 'Standard widget', 'Electronics', 1.0, 0.5)
        add_sku('SKU-002', 'Widget B', 'Large widget', 'Electronics', 2.0, 1.0)
        add_sku('SKU-003', 'Box A', 'Small box', 'Packaging', 0.5, 2.0)
        add_sku('SKU-004', 'Box B', 'Large box', 'Packaging', 1.0, 4.0)"""
        
new_sku_seed = """    # 2) SEED SKUs IF EMPTY
    cursor = conn.execute("SELECT COUNT(*) FROM skus")
    if cursor.fetchone()[0] == 0:
        add_sku('SKU-ENG-01', 'V6 Engine Block', 'Assembled V6 Engine', 'Powertrain', 150.0, 2.5)
        add_sku('SKU-TRN-01', 'Automatic Transmission', '6-Speed Auto', 'Powertrain', 80.0, 1.2)
        add_sku('SKU-BPM-01', 'Front Bumper', 'Polyurethane painted', 'Body', 15.0, 3.0)
        add_sku('SKU-CHSS-01', 'Chassis Frame', 'Steel Base Frame', 'Body', 350.0, 6.0)
        add_sku('SKU-WHL-01', 'Alloy Wheel', '18-inch Rim + Tire', 'Suspension', 22.0, 0.4)
        add_sku('SKU-STR-01', 'Steering Wheel', 'Leather wrapped', 'Interior', 3.5, 0.1)"""
        
db_py = db_py.replace(old_sku_seed, new_sku_seed)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("db.py SKU seed updated.")
