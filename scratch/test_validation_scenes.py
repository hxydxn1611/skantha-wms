import sys
sys.path.append('webapp')
from validation_service import get_validation_service
import cv2

val_srv = get_validation_service()
scenes = [
    'validation_truck_gp1000.jpg',
    'validation_plate_mh12.jpg',
    'validation_unknown_b999.jpg',
    'identity_qr_b104.jpg',
    'identity_unidentified.jpg',
    'identity_conflict.jpg'
]

for s in scenes:
    val_srv.reset_session('CAM-001')
    frame = cv2.imread(f'webapp/static/test_scenes/{s}')
    res = val_srv.process_frame(frame, camera_id='CAM-001')
    t = res.get('tracks', [{}])[0]
    id_info = t.get('identity', {})
    val_info = t.get('validation', {})
    v_val = id_info.get('value')
    v_stat = id_info.get('status')
    val_stat = val_info.get('status')
    m_id = val_info.get('master_id')
    print(f"{s:<30} -> Visual: {v_val} [{v_stat}] -> Validation: {val_stat} | Master: {m_id}")
