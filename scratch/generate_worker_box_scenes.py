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

def draw_worker_silhouette(img, x, y, w, h, vest_color=(30, 200, 240)):
    """Draw a warehouse worker silhouette with high-vis safety vest and QR badge."""
    # Head (hard hat)
    head_cx = x + w // 2
    head_cy = y + int(h * 0.18)
    head_r = int(w * 0.22)
    cv2.circle(img, (head_cx, head_cy), head_r, (40, 180, 255), -1) # Yellow hard hat
    cv2.circle(img, (head_cx, head_cy), head_r, (20, 100, 200), 2)
    # Brim
    cv2.ellipse(img, (head_cx, head_cy + int(head_r * 0.4)), (head_r + 4, 4), 0, 0, 360, (20, 100, 200), -1)

    # Body (Torso with high-vis vest)
    torso_top = head_cy + head_r
    torso_bot = y + int(h * 0.65)
    torso_pts = np.array([
        [x + int(w * 0.15), torso_top],
        [x + int(w * 0.85), torso_top],
        [x + int(w * 0.75), torso_bot],
        [x + int(w * 0.25), torso_bot]
    ], np.int32)
    cv2.fillPoly(img, [torso_pts], vest_color)
    cv2.polylines(img, [torso_pts], True, (20, 120, 150), 2)

    # Reflective silver stripes on vest
    cv2.line(img, (x + int(w * 0.28), torso_top + 10), (x + int(w * 0.32), torso_bot - 10), (220, 220, 220), 4)
    cv2.line(img, (x + int(w * 0.72), torso_top + 10), (x + int(w * 0.68), torso_bot - 10), (220, 220, 220), 4)
    cv2.line(img, (x + int(w * 0.22), torso_top + int((torso_bot - torso_top) * 0.5)),
                  (x + int(w * 0.78), torso_top + int((torso_bot - torso_top) * 0.5)), (220, 220, 220), 4)

    # Legs (navy work trousers)
    leg_w = int(w * 0.22)
    leg_bot = y + h
    # Left leg
    cv2.rectangle(img, (x + int(w * 0.22), torso_bot), (x + int(w * 0.22) + leg_w, leg_bot), (120, 60, 40), -1)
    # Right leg
    cv2.rectangle(img, (x + int(w * 0.56), torso_bot), (x + int(w * 0.56) + leg_w, leg_bot), (120, 60, 40), -1)

    # Arms
    cv2.line(img, (x + int(w * 0.18), torso_top + 5), (x + 2, torso_bot), (80, 50, 40), 10)
    cv2.line(img, (x + int(w * 0.82), torso_top + 5), (x + w - 2, torso_bot), (80, 50, 40), 10)

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

# Base background: warehouse interior
def create_warehouse_bg(width=640, height=480):
    bg = np.full((height, width, 3), (230, 230, 235), dtype=np.uint8)
    # Floor gradient (lower half)
    for y in range(int(height * 0.45), height):
        factor = (y - height * 0.45) / (height * 0.55)
        color = (int(170 - 25 * factor), int(175 - 25 * factor), int(180 - 25 * factor))
        cv2.line(bg, (0, y), (width, y), color, 1)
    # Dock bay lines & yellow hazard lines
    cv2.line(bg, (0, int(height * 0.45)), (width, int(height * 0.45)), (110, 110, 120), 2)
    cv2.line(bg, (0, int(height * 0.48)), (width, int(height * 0.48)), (0, 200, 240), 4)
    # Wall pillars
    for px in [120, 320, 520]:
        cv2.rectangle(bg, (px - 15, 0), (px + 15, int(height * 0.45)), (190, 195, 200), -1)
        cv2.rectangle(bg, (px - 15, 0), (px + 15, int(height * 0.45)), (140, 145, 150), 1)
    return bg

# 1. Scene 1: Worker Maddy + Box VLV-900 at Dock 1 (Close proximity, same zone)
s1 = create_warehouse_bg()
# Worker Maddy at x: 220, y: 160, w: 100, h: 250
draw_worker_silhouette(s1, 220, 160, 100, 250)
# Worker badge QR for 'Maddy' on chest
s1[225:275, 245:295] = make_qr_patch("Maddy", 50)
cv2.putText(s1, "MADDY", (245, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (10, 10, 10), 1)

# Box VLV-900 right next to worker at x: 350, y: 260, w: 120, h: 140
draw_box(s1, 350, 260, 120, 140, label="VLV-900", qr_text="VLV-900")
out1 = os.path.join(SCENE_DIR, "association_worker_box_dock1.jpg")
cv2.imwrite(out1, s1)
print("Created:", out1)

# 2. Scene 2: Worker in Dock 1 + Box in different zone (far away at top-left x: 40, y: 70)
s2 = create_warehouse_bg()
draw_worker_silhouette(s2, 420, 160, 100, 250)
s2[225:275, 445:495] = make_qr_patch("Maddy", 50)
# Box far away in storage zone (x: 40..130, y: 70..160)
draw_box(s2, 40, 70, 90, 90, label="VLV-900", qr_text="VLV-900")
out2 = os.path.join(SCENE_DIR, "association_worker_box_diff_zones.jpg")
cv2.imwrite(out2, s2)
print("Created:", out2)

# 3. Scene 3: Two Workers + Two Boxes (Independent Pairs)
s3 = create_warehouse_bg()
# Pair 1: Worker 1 (Maddy) + Box 1 (VLV-900) on left side (x: 80..260)
draw_worker_silhouette(s3, 80, 160, 90, 240)
s3[225:265, 105:145] = make_qr_patch("Maddy", 40)
draw_box(s3, 190, 260, 90, 130, label="VLV-900", qr_text="VLV-900")

# Pair 2: Worker 2 (admin) + Box 2 (B104) on right side (x: 370..570)
draw_worker_silhouette(s3, 370, 160, 90, 240, vest_color=(40, 160, 60)) # Green vest
s3[225:265, 395:435] = make_qr_patch("admin", 40)
draw_box(s3, 480, 260, 90, 130, label="B104", qr_text="B104")
out3 = os.path.join(SCENE_DIR, "association_two_workers_boxes.jpg")
cv2.imwrite(out3, s3)
print("Created:", out3)

# 4. Scene 4: Ambiguous Two Workers near one Box (Box positioned midway between both)
s4 = create_warehouse_bg()
# Worker 1 on left (x: 120)
draw_worker_silhouette(s4, 120, 160, 90, 240)
s4[225:265, 145:185] = make_qr_patch("Maddy", 40)
# Worker 2 on right (x: 430)
draw_worker_silhouette(s4, 430, 160, 90, 240, vest_color=(40, 160, 60))
s4[225:265, 455:495] = make_qr_patch("admin", 40)
# Box in exact middle (x: 275..365)
draw_box(s4, 275, 270, 90, 120, label="VLV-900", qr_text="VLV-900")
out4 = os.path.join(SCENE_DIR, "association_ambiguous_two_workers.jpg")
cv2.imwrite(out4, s4)
print("Created:", out4)

print("All Worker <-> Box association test scenes generated successfully!")
