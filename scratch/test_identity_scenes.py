import cv2
import sys
sys.path.append('webapp')
from identity_service import get_identity_service

ident = get_identity_service()
scenes = [
    'validation_truck_gp1000.jpg',
    'validation_plate_mh12.jpg',
    'validation_unknown_b999.jpg',
    'identity_qr_b104.jpg',
    'identity_unidentified.jpg',
    'identity_conflict.jpg'
]

for s in scenes:
    ident.reset_session('CAM-001')
    img = cv2.imread(f'webapp/static/test_scenes/{s}')
    res = ident.process_frame(img, camera_id='CAM-001')
    t = res['tracks'][0] if res['tracks'] else {}
    id_info = t.get('identity', {})
    tid = t.get('track_id')
    cls = t.get('class_code')
    val = id_info.get('value')
    stat = id_info.get('status')
    print(f"{s:<30} -> Track: {tid} | Class: {cls} | Identity: {val} | Status: {stat}")
