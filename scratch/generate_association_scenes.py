import os
import cv2
import numpy as np
import qrcode

SCENE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webapp", "static", "test_scenes")
os.makedirs(SCENE_DIR, exist_ok=True)

base_path = os.path.join(SCENE_DIR, "identity_unidentified.jpg")
base_img = cv2.imread(base_path)
h, w = base_img.shape[:2]

def make_qr_patch(text, size=70):
    qr = qrcode.QRCode(box_size=3, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    q_np = cv2.cvtColor(np.array(qr.make_image(fill_color="black", back_color="white").convert('RGB')), cv2.COLOR_RGB2BGR)
    return cv2.resize(q_np, (size, size), interpolation=cv2.INTER_AREA)

# 1. Scene 1: Truck GP-1000 + Box VLV-900 at Dock 1 (Close proximity, same zone)
s1 = base_img.copy()
# Truck QR code (GP-1000) at [240:310, 265:335]
s1[240:310, 265:335] = make_qr_patch("GP-1000", 70)

# Add a cardboard box cargo adjacent to the truck (at x: 420..500, y: 320..420)
# Cardboard brown texture with black border
cv2.rectangle(s1, (420, 320), (510, 420), (140, 180, 210), -1)
cv2.rectangle(s1, (420, 320), (510, 420), (80, 120, 150), 2)
# Box QR code (VLV-900) on the box
s1[335:395, 435:495] = make_qr_patch("VLV-900", 60)
cv2.putText(s1, "VLV-900", (430, 412), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (20, 40, 60), 1, cv2.LINE_AA)

out1 = os.path.join(SCENE_DIR, "association_truck_box_dock1.jpg")
cv2.imwrite(out1, s1)
print("Created:", out1)

# 2. Scene 2: Truck GP-1000 in Dock 1 + Box in different zone (far away at top-left x: 60..130, y: 80..150)
s2 = base_img.copy()
s2[240:310, 265:335] = make_qr_patch("GP-1000", 70)
# Far box
cv2.rectangle(s2, (60, 80), (140, 160), (140, 180, 210), -1)
cv2.rectangle(s2, (60, 80), (140, 160), (80, 120, 150), 2)
s2[90:140, 75:125] = make_qr_patch("VLV-900", 50)
out2 = os.path.join(SCENE_DIR, "association_truck_box_diff_zones.jpg")
cv2.imwrite(out2, s2)
print("Created:", out2)

# 3. Scene 3: Two Trucks + Two Boxes
s3 = base_img.copy()
# Truck 1 (left) with GP-1000
s3[240:310, 265:335] = make_qr_patch("GP-1000", 70)
# Box 1 near Truck 1
cv2.rectangle(s3, (410, 330), (490, 420), (140, 180, 210), -1)
cv2.rectangle(s3, (410, 330), (490, 420), (80, 120, 150), 2)
s3[340:390, 425:475] = make_qr_patch("VLV-900", 50)

# Truck 2 simulated vehicle on right side (x: 520..630)
cv2.rectangle(s3, (510, 180), (630, 430), (70, 75, 80), -1)
cv2.rectangle(s3, (510, 180), (630, 430), (30, 30, 30), 2)
s3[240:300, 530:590] = make_qr_patch("GP-1001", 60)
# Box 2 near Truck 2 (x: 520..590, y: 350..420)
cv2.rectangle(s3, (520, 350), (600, 420), (130, 170, 200), -1)
s3[360:400, 535:575] = make_qr_patch("BOX-GENERIC", 40)

out3 = os.path.join(SCENE_DIR, "association_two_trucks_boxes.jpg")
cv2.imwrite(out3, s3)
print("Created:", out3)

# 4. Scene 4: Ambiguous Two Trucks near one Box (Box positioned midway between both)
s4 = base_img.copy()
s4[240:310, 200:270] = make_qr_patch("GP-1000", 70)
# Second truck on right
cv2.rectangle(s4, (450, 180), (600, 430), (70, 75, 80), -1)
s4[240:300, 470:530] = make_qr_patch("GP-1001", 60)
# Box in exact middle (x: 325..395)
cv2.rectangle(s4, (325, 320), (395, 400), (140, 180, 210), -1)
s4[335:385, 335:385] = make_qr_patch("VLV-900", 50)

out4 = os.path.join(SCENE_DIR, "association_ambiguous_two_trucks.jpg")
cv2.imwrite(out4, s4)
print("Created:", out4)

print("All association test scenes created successfully!")
