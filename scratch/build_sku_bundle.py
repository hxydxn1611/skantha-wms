import os

with open('webapp/db.py', 'r', encoding='utf-8') as f:
    db_py = f.read()

# Update add_sku signature and query
old_add_sku = """def add_sku(sku_id, name, description, category, unit_weight, unit_volume):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO skus (sku_id, name, description, category, unit_weight, unit_volume, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (sku_id, name, description, category, unit_weight, unit_volume))
    conn.close()"""
    
new_add_sku = """def add_sku(sku_id, name, description, category, unit_weight, unit_volume, units_per_bundle=1):
    conn = get_db()
    with conn:
        conn.execute('''
            INSERT INTO skus (sku_id, name, description, category, unit_weight, unit_volume, units_per_bundle, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (sku_id, name, description, category, unit_weight, unit_volume, units_per_bundle))
    conn.close()"""

db_py = db_py.replace(old_add_sku, new_add_sku)

# Update the seed logic
old_seed = """    cursor = conn.execute("SELECT COUNT(*) FROM skus")
    if cursor.fetchone()[0] == 0:
        add_sku('SKU-ENG-01', 'V6 Engine Block', 'Assembled V6 Engine', 'Powertrain', 150.0, 2.5)
        add_sku('SKU-TRN-01', 'Automatic Transmission', '6-Speed Auto', 'Powertrain', 80.0, 1.2)
        add_sku('SKU-BPM-01', 'Front Bumper', 'Polyurethane painted', 'Body', 15.0, 3.0)
        add_sku('SKU-CHSS-01', 'Chassis Frame', 'Steel Base Frame', 'Body', 350.0, 6.0)
        add_sku('SKU-WHL-01', 'Alloy Wheel', '18-inch Rim + Tire', 'Suspension', 22.0, 0.4)
        add_sku('SKU-STR-01', 'Steering Wheel', 'Leather wrapped', 'Interior', 3.5, 0.1)"""
        
new_seed = """    cursor = conn.execute("SELECT COUNT(*) FROM skus")
    if cursor.fetchone()[0] == 0:
        # Car Manufacturing Parts - Notice the units_per_bundle
        add_sku('SKU-ENG-01', 'V6 Engine Block', 'Assembled V6 Engine', 'Powertrain', 150.0, 2.5, 1)
        add_sku('SKU-TRN-01', 'Automatic Transmission', '6-Speed Auto', 'Powertrain', 80.0, 1.2, 1)
        add_sku('SKU-BPM-01', 'Front Bumper', 'Polyurethane painted', 'Body', 15.0, 3.0, 5) # Bundle of 5
        add_sku('SKU-CHSS-01', 'Chassis Frame', 'Steel Base Frame', 'Body', 350.0, 6.0, 1)
        add_sku('SKU-WHL-01', 'Alloy Wheel', '18-inch Rim + Tire', 'Suspension', 22.0, 0.4, 4) # Pallet of 4
        add_sku('SKU-STR-01', 'Steering Wheel', 'Leather wrapped', 'Interior', 3.5, 0.1, 10) # Bundle of 10
        add_sku('SKU-SCR-M8', 'M8 Screws Box', 'High-tensile M8 Screws', 'Hardware', 2.0, 0.05, 500) # 500 per box
        add_sku('SKU-WND-01', 'Windshield Glass', 'Laminated Front Glass', 'Body', 18.0, 0.8, 10) # Pallet of 10"""
        
db_py = db_py.replace(old_seed, new_seed)

with open('webapp/db.py', 'w', encoding='utf-8') as f:
    f.write(db_py)

print("db.py updated for units_per_bundle")
