import os
import cv2
import numpy as np
import qrcode
import barcode
from barcode.writer import ImageWriter

SCENE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "webapp", "static", "test_scenes")
base_img = cv2.imread(os.path.join(SCENE_DIR, "identity_unidentified.jpg"))

# 1. Validation Scene 1: Known Gate Pass GP-1000 (QR Code)
s1 = base_img.copy()
qr1 = qrcode.QRCode(box_size=3, border=1)
qr1.add_data("GP-1000")
qr1.make(fit=True)
q1_np = cv2.cvtColor(np.array(qr1.make_image(fill_color="black", back_color="white").convert('RGB')), cv2.COLOR_RGB2BGR)
q1_resized = cv2.resize(q1_np, (70, 70), interpolation=cv2.INTER_AREA)
s1[240:310, 265:335] = q1_resized
cv2.imwrite(os.path.join(SCENE_DIR, "validation_truck_gp1000.jpg"), s1)

# 2. Validation Scene 2: Known Plate MH12AB1234 (Code 128 Barcode)
s2 = base_img.copy()
CODE128 = barcode.get_barcode_class('code128')
writer = ImageWriter()
writer.format = 'PNG'
bc = CODE128("MH12AB1234", writer=writer)
bc_temp = os.path.join(SCENE_DIR, "_temp_bc.png")
bc.save(bc_temp[:-4])
bc_np = cv2.imread(bc_temp)
if os.path.exists(bc_temp):
    os.remove(bc_temp)
bc_resized = cv2.resize(bc_np, (90, 45), interpolation=cv2.INTER_AREA)
s2[250:295, 255:345] = bc_resized
cv2.imwrite(os.path.join(SCENE_DIR, "validation_plate_mh12.jpg"), s2)

# 3. Validation Scene 3: Unknown Identifier B999999 (QR Code)
s3 = base_img.copy()
qr3 = qrcode.QRCode(box_size=3, border=1)
qr3.add_data("B999999")
qr3.make(fit=True)
q3_np = cv2.cvtColor(np.array(qr3.make_image(fill_color="black", back_color="white").convert('RGB')), cv2.COLOR_RGB2BGR)
q3_resized = cv2.resize(q3_np, (70, 70), interpolation=cv2.INTER_AREA)
s3[240:310, 265:335] = q3_resized
cv2.imwrite(os.path.join(SCENE_DIR, "validation_unknown_b999.jpg"), s3)

print("Generated clean validation scenes from identity_unidentified.jpg.")
