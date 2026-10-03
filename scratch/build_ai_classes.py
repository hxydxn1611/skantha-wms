import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace(
    'SmartCamera.vehicle_model.set_classes(["car engine", "car bumper", "person", "truck", "car"])',
    'SmartCamera.vehicle_model.set_classes(["car engine", "car bumper", "person", "truck", "car", "windshield", "hood", "screw box", "tire bundle"])'
)

with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("ai_engine.py YOLO classes updated.")
