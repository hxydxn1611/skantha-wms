"""
Generate Test Scenes for Part 11: Box <-> Bin Association Foundation
Scenes:
1. association_box_bin_dock1.jpg: Box VLV-900 + Bin BIN-A in close proximity (Same Zone)
2. association_box_bin_diff_zones.jpg: Box in Dock 1 + Bin in far zone
3. association_two_boxes_bins.jpg: Two independent pairs (Box 1 + Bin 1 on left, Box 2 + Bin 2 on right)
4. association_ambiguous_two_bins.jpg: One Box positioned midway between Two competing Bins
"""

import os
import cv2
import numpy as np
import qrcode

SCENE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webapp", "static", "test_scenes")
os.makedirs(SCENE_DIR, exist_ok=True)

def make_qr_patch(text, size=60):
    qr = qrcode.QRCode(box_size=3, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    q_np = cv2.cvtColor(np.array(qr.make_image(fill_color="black", back_color="white").convert('RGB')), cv2.COLOR_RGB2BGR)
    return cv2.resize(q_np, (size, size), interpolation=cv2.INTER_AREA)

def create_warehouse_bg(width=640, height=480):
    bg = np.full((height, width, 3), (230, 230, 235), dtype=np.uint8)
    # Floor gradient (lower half)
    for y in range(int(height * 0.45), height):
        factor = (y - height * 0.45) / (height * 0.55)
        color = (int(170 - 25 * factor), int(175 - 25 * factor), int(180 - 25 * factor))
        cv2.line(bg, (0, y), (width, y), color, 1)
    # Floor lines & yellow hazard lines
    cv2.line(bg, (0, int(height * 0.45)), (width, int(height * 0.45)), (110, 110, 120), 2)
    cv2.line(bg, (0, int(height * 0.48)), (width, int(height * 0.48)), (0, 200, 240), 4)
    # Wall pillars
    for px in [120, 320, 520]:
        cv2.rectangle(bg, (px - 15, 0), (px + 15, int(height * 0.45)), (190, 195, 200), -1)
        cv2.rectangle(bg, (px - 15, 0), (px + 15, int(height * 0.45)), (140, 145, 150), 1)
    return bg

def draw_box(img, x, y, w, h, label="VLV-900", qr_text=None):
    """Draw a cardboard shipping carton with seams, label, and QR code."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (135, 175, 210), -1) # Cardboard brown
    cv2.rectangle(img, (x, y), (x + w, y + h), (75, 115, 150), 2)
    # Tape seam across middle
    cv2.line(img, (x + w // 2, y), (x + w // 2, y + h), (110, 150, 185), 4)
    if qr_text:
        qr_size = min(w - 16, h - 30, 60)
        if qr_size > 20:
            qr_p = make_qr_patch(qr_text, qr_size)
            qx = x + (w - qr_size) // 2
            qy = y + 8
            img[qy:qy+qr_size, qx:qx+qr_size] = qr_p
            cv2.putText(img, label, (x + 8, y + h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 40, 60), 1, cv2.LINE_AA)

def draw_bin(img, x, y, w, h, label="BIN-A", qr_text=None, tote_color=(190, 95, 25)):
    """Draw an industrial blue storage tote / warehouse bin with rack shelf."""
    # Shelf / Rack beam below bin
    cv2.rectangle(img, (x - 10, y + h), (x + w + 10, y + h + 16), (80, 85, 95), -1)
    cv2.rectangle(img, (x - 10, y + h), (x + w + 10, y + h + 16), (40, 45, 50), 2)

    # Main Bin body (Deep Industrial Blue/Teal)
    pts = np.array([
        [x, y + 15],
        [x + w, y + 15],
        [x + int(w * 0.92), y + h],
        [x + int(w * 0.08), y + h]
    ], np.int32)
    cv2.fillPoly(img, [pts], tote_color)
    cv2.polylines(img, [pts], True, (130, 50, 10), 2)

    # Bin top reinforced rim
    cv2.rectangle(img, (x - 4, y), (x + w + 4, y + 16), (220, 120, 40), -1)
    cv2.rectangle(img, (x - 4, y), (x + w + 4, y + 16), (130, 50, 10), 2)

    # Ribbed structure lines on front
    for rx in range(x + 25, x + w - 20, 20):
        cv2.line(img, (rx, y + 25), (rx, y + h - 10), (160, 75, 15), 2)

    # Placard / White label for QR / Barcode
    if qr_text:
        qr_size = min(w - 24, h - 35, 55)
        if qr_size > 20:
            qr_p = make_qr_patch(qr_text, qr_size)
            qx = x + (w - qr_size) // 2
            qy = y + 24
            img[qy:qy+qr_size, qx:qx+qr_size] = qr_p
            cv2.putText(img, label, (x + 8, y + h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)
    else:
        cv2.putText(img, label, (x + 12, y + h // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

# 1. Scene 1: Box VLV-900 right next to Bin BIN-A (Close proximity, same zone)
s1 = create_warehouse_bg()
# Bin BIN-A at x: 180, y: 220, w: 140, h: 180
draw_bin(s1, 180, 220, 140, 180, label="BIN-A", qr_text="BIN-A")
# Box VLV-900 right next to bin at x: 350, y: 260, w: 120, h: 140
draw_box(s1, 350, 260, 120, 140, label="VLV-900", qr_text="VLV-900")
out1 = os.path.join(SCENE_DIR, "association_box_bin_dock1.jpg")
cv2.imwrite(out1, s1)
print("Created:", out1)

# 2. Scene 2: Box in Dock 1 + Bin in far zone (Separated distance > 0.40)
s2 = create_warehouse_bg()
# Bin far away in top-left storage shelf at x: 40, y: 70, w: 100, h: 120
draw_bin(s2, 40, 70, 100, 120, label="BIN-A", qr_text="BIN-A")
# Box on right side at x: 440, y: 260, w: 120, h: 140
draw_box(s2, 440, 260, 120, 140, label="VLV-900", qr_text="VLV-900")
out2 = os.path.join(SCENE_DIR, "association_box_bin_diff_zones.jpg")
cv2.imwrite(out2, s2)
print("Created:", out2)

# 3. Scene 3: Two Boxes + Two Bins (Independent Pairs)
s3 = create_warehouse_bg()
# Pair 1: Bin 1 (BIN-A) + Box 1 (VLV-900) on left side (x: 50..260)
draw_bin(s3, 50, 220, 110, 160, label="BIN-A", qr_text="BIN-A")
draw_box(s3, 175, 240, 95, 140, label="VLV-900", qr_text="VLV-900")

# Pair 2: Bin 2 (TB-01) + Box 2 (B104) on right side (x: 370..590)
draw_bin(s3, 370, 220, 110, 160, label="TB-01", qr_text="TB-01", tote_color=(40, 140, 50)) # Green tote
draw_box(s3, 495, 240, 95, 140, label="B104", qr_text="B104")
out3 = os.path.join(SCENE_DIR, "association_two_boxes_bins.jpg")
cv2.imwrite(out3, s3)
print("Created:", out3)

# 4. Scene 4: Ambiguous Two Bins near One Box (Box positioned midway between both)
s4 = create_warehouse_bg()
# Bin 1 on left (x: 100)
draw_bin(s4, 100, 220, 120, 160, label="BIN-A", qr_text="BIN-A")
# Bin 2 on right (x: 420)
draw_bin(s4, 420, 220, 120, 160, label="TB-01", qr_text="TB-01", tote_color=(40, 140, 50))
# Box in exact middle (x: 260..360)
draw_box(s4, 265, 250, 110, 130, label="VLV-900", qr_text="VLV-900")
out4 = os.path.join(SCENE_DIR, "association_ambiguous_two_bins.jpg")
cv2.imwrite(out4, s4)
print("Created:", out4)

print("All Box <-> Bin association test scenes generated successfully!")
