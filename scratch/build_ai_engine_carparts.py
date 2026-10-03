import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace YOLO classes
code = code.replace(
    'SmartCamera.vehicle_model.set_classes(["cardboard box", "bundle", "person", "truck", "car"])',
    'SmartCamera.vehicle_model.set_classes(["car engine", "car bumper", "person", "truck", "car"])'
)

# Replace "Package" with "Car Part"
code = code.replace(
    'vehicle_type = "Package"',
    'vehicle_type = "Car Part"'
)

# Replace is_package check
code = code.replace(
    'vehicle_type=="Package"',
    'vehicle_type=="Car Part"'
)

# Replace "Package_Counted" event type
code = code.replace(
    '"type": "Package_Counted"',
    '"type": "Part_Counted"'
)

with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("ai_engine.py patched for Car Parts.")
