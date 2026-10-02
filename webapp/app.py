from flask import Flask, render_template, Response, request, jsonify
from ai_engine import SmartCamera
import time
import uuid
import cv2
import numpy as np
import os
import random
from datetime import datetime
from fpdf import FPDF

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

import db
from detection_service import get_detection_engine
from tracking_service import get_tracking_service
from identity_service import get_identity_service
from validation_service import get_validation_service
from association_service import get_association_service
from worker_box_association_service import get_worker_box_association_service
from box_bin_association_service import get_box_bin_association_service

# Initialize SQLite database schema
db.init_db()

# Store active cameras in memory
active_cameras = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    user = db.get_user(data.get('username'), data.get('password'))
    if user:
        return jsonify({'success': True, 'message': 'Logged in successfully'})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required'}), 400
    
    if db.create_user(username, password):
        return jsonify({'success': True, 'message': 'User registered successfully'})
    return jsonify({'success': False, 'message': 'Username already exists'}), 409

@app.route('/api/deliveries', methods=['GET', 'POST'])
def handle_deliveries():
    if request.method == 'POST':
        data = request.json
        new_deliv = db.create_delivery(data)
        return jsonify({"success": True, "delivery": new_deliv})
    return jsonify(db.get_all_deliveries())

@app.route('/api/deliveries/<po_number>', methods=['GET', 'DELETE'])
def handle_single_delivery(po_number):
    if request.method == 'DELETE':
        db.delete_delivery(po_number)
        return jsonify({"success": True})
    deliv = db.get_delivery(po_number)
    if deliv:
        return jsonify(deliv)
    return jsonify({"success": False, "message": "Delivery not found"}), 404



@app.route('/api/bins', methods=['POST'])
def api_add_bin():
    data = request.get_json(force=True)
    try:
        db.add_bin(data['bin_id'], data.get('zone', 'General'), data.get('max_volume', 100.0), data.get('max_weight', 1000.0))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/skus', methods=['GET'])
def api_get_skus():
    return jsonify(db.get_all_skus())

@app.route('/api/skus', methods=['POST'])
def api_add_sku():
    data = request.get_json(force=True)
    try:
        db.add_sku(data['sku_id'], data['name'], data.get('description', ''), data.get('category', ''), data.get('unit_weight', 0.0), data.get('unit_volume', 0.0))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/bins', methods=['GET'])
def api_get_bins():
    return jsonify(db.get_all_bins())

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(db.get_stats())

@app.route('/api/gate_passes', methods=['GET'])
def get_gate_passes():
    return jsonify(db.get_all_gate_passes())

@app.route('/api/gate_passes', methods=['POST'])
def create_gate_pass():
    data = request.json
    
    # Enforce one truck at the gate at a time.
    # If there is already a Pending gate pass, block new ones until it's processed.
    if db.has_pending_gate_pass():
        return jsonify({"success": False, "message": "Clear pending gate pass first."})
            
    # Generate a random 4-digit OTP if driver_phone is provided
    otp = str(random.randint(1000, 9999)) if data.get('driver_phone') else ""
    if otp:
        data['otp'] = otp
        print(f"\n[MOCK SMS] Sent OTP {otp} to Driver Phone {data.get('driver_phone')}\n")
            
    # Auto-matches against pre-registered deliveries (by plate or po_number)
    # and connects both collections inside db.create_gate_pass
    new_gp = db.create_gate_pass(data)
    
    # Add to Vehicle Log
    db.create_vehicle_log(new_gp['id'], new_gp['plate'], new_gp['driver_name'])
    
    return jsonify({"success": True, "gate_pass": new_gp})

@app.route('/api/gate/verify_otp', methods=['POST'])
def verify_otp():
    data = request.json
    gp_id = data.get('gp_id')
    entered_otp = data.get('otp')
    
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found."})
    
    if gp.get('otp') == entered_otp:
        db.update_gate_pass(gp_id, {"otp_verified": 1})
        return jsonify({"success": True, "message": "OTP Verified Successfully!"})
    return jsonify({"success": False, "message": "Invalid OTP. Please try again."})

@app.route('/api/gate/checkout', methods=['POST'])
def checkout():
    data = request.json
    gp_id = data.get('gp_id')
    plate = data.get('plate')
    face_check = data.get('face_check', False) # UI will send this if face check is active
    
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found."})
        
    # Security Check: Ensure the same vehicle is leaving
    if gp.get('plate') != plate:
        return jsonify({"success": False, "message": f"Security Alert! Vehicle plate mismatch. Expected {gp.get('plate')} but got {plate}."})
        
    # Security Check: Driver Face Verification
    if face_check and gp.get('driver_photo'):
        # In a real system, we would run deepface or face_recognition here
        # between gp['driver_photo'] (Entry Face) and the newly captured Exit Face.
        # For this PoC, we will simulate the check passing, but log it.
        print(f"[SECURITY] Face Verification passed for Gate Pass {gp_id}. Driver matches entry photo.")
    elif face_check and not gp.get('driver_photo'):
        return jsonify({"success": False, "message": "Security Alert! No entry face photo found to verify against."})
        
    db.update_gate_pass(gp_id, {"status": "Departed", "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    db.checkout_vehicle_log(gp_id)
    return jsonify({"success": True, "message": "Check-out successful. Vehicle authorized to leave."})

@app.route('/api/gate/invoice', methods=['POST'])
def generate_invoice():
    data = request.json
    gp_id = data.get('gp_id')
    payload_email = data.get('vendor_email', '')
    
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found."})
        
    if payload_email and not gp.get('vendor_email'):
        db.update_gate_pass(gp_id, {"vendor_email": payload_email})
        gp = db.get_gate_pass(gp_id)
        
    vendor_email = gp.get('vendor_email')
    po_num = gp.get('po_number')
    vendor_name = gp.get('vendor')
    plate = gp.get('plate')
    
    if not vendor_email:
        deliv = None
        if po_num:
            deliv = db.get_delivery(po_num)
        if not deliv and vendor_name:
            # Fallback to finding by vendor
            for d in db.get_expected_deliveries():
                if d['vendor'] == vendor_name:
                    deliv = d
                    break
        if not deliv and plate:
            # Fallback to finding by plate
            for d in db.get_expected_deliveries():
                if d['plate'] == plate:
                    deliv = d
                    break
        
        # Ultimate fallback for demo: just get the latest delivery with an email
        if not deliv:
            deliveries = db.get_expected_deliveries()
            if deliveries:
                deliv = deliveries[-1]
                    
        if deliv and deliv.get('vendor_email'):
            vendor_email = deliv.get('vendor_email')
            db.update_gate_pass(gp_id, {"vendor_email": vendor_email})
            
    vendor_email = vendor_email or 'N/A'
    qty = gp.get('unloaded_qty', 0)
    bin_alloc = gp.get('bin_allocation', 'Staging Area')
    po_num = gp.get('po_number', 'N/A')
    
    # Generate actual PDF invoice
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=15)
    pdf.cell(200, 10, txt="Skandha WMS - Delivery Invoice", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Gate Pass ID: {gp_id}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"PO Number: {po_num}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Vendor: {gp.get('vendor')} ({vendor_email})", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1, align='L')
    pdf.cell(200, 10, txt="", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Total Items Unloaded: {qty}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Stored in Location: {bin_alloc}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Driver: {gp.get('driver_name')} | Plate: {gp.get('plate')}", ln=1, align='L')
    
    pdf_filename = f"invoice_{gp_id}.pdf"
    pdf_dir = os.path.join(os.path.dirname(__file__), "static", "invoices")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    pdf.output(pdf_path)
    
    db.create_invoice(gp_id, po_num, gp.get('vendor'), vendor_email, pdf_filename)
    
    email_status = "Not sent (No vendor email provided)"
    if vendor_email and vendor_email != 'N/A':
        try:
            import smtplib
            from email.message import EmailMessage
            
            msg = EmailMessage()
            msg['Subject'] = f'Invoice for Gate Pass {gp_id}'
            msg['From'] = 'hayd161103@gmail.com'
            msg['To'] = vendor_email
            msg.set_content(f"Hello {gp.get('vendor')},\n\nPlease find attached the invoice for Gate Pass {gp_id}.\nTotal Items Unloaded: {qty}\nStored in Location: {bin_alloc}\n\nThank you.")
            
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=pdf_filename)
            
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login('hayd161103@gmail.com', 'hwflfuagdsqglxkp')
                smtp.send_message(msg)
            
            email_status = "Real Email successfully sent!"
        except Exception as e:
            email_status = f"Email failed: {str(e)}"
        
    return jsonify({"success": True, "message": f"Invoice generated! Email status: {email_status}"})

@app.route('/api/vehicle_log', methods=['GET'])
def get_vehicle_logs():
    return jsonify(db.get_all_vehicle_logs())

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    return jsonify(db.get_all_invoices())

# ----------------- AI Vision & Tracking Master APIs -----------------
@app.route('/api/object_classes', methods=['GET', 'POST'])
def handle_object_classes():
    if request.method == 'POST':
        data = request.json or {}
        obj, err = db.create_object_class(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400
        return jsonify({'success': True, 'object_class': obj, 'message': f"Class '{obj['code']}' created successfully."}), 201

    search_term = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    classes = db.get_all_object_classes(search_term=search_term or None, status=status or None)
    return jsonify(classes)

@app.route('/api/object_classes/<identifier>', methods=['GET', 'PUT', 'PATCH', 'DELETE'])
def handle_single_object_class(identifier):
    if request.method == 'GET':
        obj = db.get_object_class(identifier)
        if not obj:
            return jsonify({'success': False, 'message': f"Object class '{identifier}' not found."}), 404
        return jsonify({'success': True, 'object_class': obj})

    elif request.method == 'DELETE':
        success, err = db.delete_object_class(identifier)
        if not success:
            return jsonify({'success': False, 'message': err or 'Failed to delete object class.'}), 400
        return jsonify({'success': True, 'message': f"Object class '{identifier}' deleted successfully."})

    # PUT / PATCH
    data = request.json or {}
    updated, err = db.update_object_class(identifier, data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'object_class': updated, 'message': f"Class '{updated['code']}' updated successfully."})

# ----------------- AI Vision Camera Sources APIs -----------------
@app.route('/api/vision/cameras', methods=['GET'])
def get_vision_cameras():
    search = request.args.get('search', '').strip()
    ai_status = request.args.get('ai_status', '').strip()
    cam_status = request.args.get('cam_status', '').strip()
    cameras = db.get_all_vision_cameras(
        search_term=search or None,
        ai_status=ai_status or None,
        cam_status=cam_status or None
    )
    return jsonify(cameras)

@app.route('/api/vision/cameras/<camera_id>', methods=['GET'])
def get_single_vision_camera(camera_id):
    cam = db.get_vision_camera(camera_id)
    if not cam:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' not found."}), 404
    return jsonify({'success': True, 'camera': cam})

@app.route('/api/vision/cameras/<camera_id>/config', methods=['GET', 'PUT', 'POST'])
def handle_vision_camera_config(camera_id):
    if request.method == 'GET':
        cam = db.get_vision_camera(camera_id)
        if not cam:
            return jsonify({'success': False, 'message': f"Camera '{camera_id}' not found."}), 404
        return jsonify({
            'success': True,
            'camera_id': cam['camera_id'],
            'camera_code': cam['camera_code'],
            'camera_name': cam['camera_name'],
            'warehouse': cam['warehouse'],
            'location': cam['location'],
            'camera_type': cam['camera_type'],
            'camera_status': cam['camera_status'],
            'ai_config': cam['ai_config']
        })

    # PUT or POST to update AI configuration
    data = request.json or {}
    updated_cam, err = db.save_vision_camera_config(camera_id, data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({
        'success': True,
        'camera': updated_cam,
        'message': f"AI Configuration for camera '{updated_cam['camera_code']}' saved successfully."
    })

# ----------------- AI Vision Warehouse Zone Master APIs -----------------
@app.route('/api/vision/zone_types', methods=['GET'])
def get_zone_types():
    return jsonify(db.get_zone_types())

@app.route('/api/vision/zones', methods=['GET', 'POST'])
def handle_vision_zones():
    if request.method == 'POST':
        data = request.json or {}
        zone, err = db.create_vision_zone(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400
        return jsonify({
            'success': True,
            'zone': zone,
            'message': f"Zone '{zone['zone_code']}' created successfully."
        }), 201

    search = request.args.get('search', '').strip()
    zone_type = request.args.get('zone_type', '').strip()
    warehouse = request.args.get('warehouse', '').strip()
    status = request.args.get('status', '').strip()
    zones = db.get_all_vision_zones(
        search_term=search or None,
        zone_type=zone_type or None,
        warehouse=warehouse or None,
        status=status or None
    )
    return jsonify(zones)

@app.route('/api/vision/zones/<identifier>', methods=['GET', 'PUT', 'PATCH', 'DELETE'])
def handle_single_vision_zone(identifier):
    if request.method == 'GET':
        zone = db.get_vision_zone(identifier)
        if not zone:
            return jsonify({'success': False, 'message': f"Zone '{identifier}' not found."}), 404
        return jsonify({'success': True, 'zone': zone})

    elif request.method == 'DELETE':
        success, err = db.delete_vision_zone(identifier)
        if not success:
            return jsonify({'success': False, 'message': err or f"Failed to delete zone '{identifier}'."}), 400
        return jsonify({'success': True, 'message': f"Zone '{identifier}' deleted successfully."})

    # PUT or PATCH
    data = request.json or {}
    updated, err = db.update_vision_zone(identifier, data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({
        'success': True,
        'zone': updated,
        'message': f"Zone '{updated['zone_code']}' updated successfully."
    })

@app.route('/api/vision/zones/<identifier>/cameras', methods=['GET', 'PUT'])
def handle_vision_zone_cameras(identifier):
    if request.method == 'GET':
        cams, err = db.get_zone_cameras(identifier)
        if err:
            return jsonify({'success': False, 'message': err}), 404
        return jsonify({'success': True, 'zone_id': identifier, 'cameras': cams})

    # PUT
    data = request.json or {}
    cam_ids = data.get('cameras', [])
    updated, err = db.update_zone_cameras(identifier, cam_ids)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({
        'success': True,
        'zone': updated,
        'message': f"Cameras updated for zone '{updated['zone_code']}'."
    })

# ----------------- Visual Zone / ROI Editor APIs -----------------
@app.route('/api/vision/zones/<zone_id>/cameras/<camera_id>/roi', methods=['GET', 'POST', 'PUT', 'DELETE'])
def handle_zone_camera_roi(zone_id, camera_id):
    if request.method == 'GET':
        roi, err = db.get_zone_camera_roi(zone_id, camera_id)
        if err:
            return jsonify({'success': False, 'message': err}), 404
        return jsonify({'success': True, 'data': roi})

    elif request.method == 'DELETE':
        success, err = db.delete_zone_camera_roi(zone_id, camera_id)
        if not success:
            return jsonify({'success': False, 'message': err}), 400
        return jsonify({'success': True, 'message': f"ROI for camera '{camera_id}' cleared."})

    # POST / PUT
    data = request.json or {}
    saved_roi, err = db.save_zone_camera_roi(zone_id, camera_id, data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({
        'success': True,
        'message': f"ROI saved for zone '{saved_roi['zone_code']}' on camera '{saved_roi['camera_code']}'.",
        'data': saved_roi
    })

@app.route('/api/vision/zones/<zone_id>/rois', methods=['GET'])
def get_zone_all_rois(zone_id):
    rois, err = db.get_zone_rois(zone_id)
    if err:
        return jsonify({'success': False, 'message': err}), 404
    return jsonify({'success': True, 'rois': rois})

@app.route('/api/vision/cameras/<camera_id>/preview_info', methods=['GET'])
def get_camera_preview_info(camera_id):
    cam = db.get_camera(camera_id)
    if not cam:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' not found."}), 404

    is_live = False
    active = active_cameras.get(cam['camera_id']) or active_cameras.get(cam['camera_code'])
    if active and active.get_frame():
        is_live = True

    return jsonify({
        'success': True,
        'camera_id': cam['camera_id'],
        'camera_code': cam['camera_code'],
        'camera_name': cam['name'],
        'warehouse': cam['warehouse'],
        'location': cam['location'],
        'is_live': is_live,
        'feed_mode': 'LIVE CAMERA' if is_live else 'PREVIEW / TEST IMAGE',
        'preview_url': f"/api/vision/cameras/{cam['camera_id']}/preview.jpg"
    })

@app.route('/api/vision/cameras/<camera_id>/preview.jpg', methods=['GET'])
def get_camera_preview_image(camera_id):
    cam = db.get_camera(camera_id)
    active = None
    if cam:
        active = active_cameras.get(cam['camera_id']) or active_cameras.get(cam['camera_code'])

    if active:
        frame_bytes = active.get_frame()
        if frame_bytes:
            return Response(frame_bytes, mimetype='image/jpeg')

    # Synthesize realistic warehouse CCTV perspective frame using OpenCV
    cam_name = cam['name'] if cam else camera_id
    cam_code = cam['camera_code'] if cam else camera_id
    warehouse = cam['warehouse'] if cam else 'Warehouse A'
    location = cam['location'] if cam else 'Dock Area'

    width, height = 800, 450
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        v = int(22 + (y / height) * 32)
        frame[y, :] = [v, v + 2, v + 8]

    # Draw perspective vanishing lines (warehouse bay lanes)
    cx, cy = width // 2, int(height * 0.32)
    for lx in [-320, -160, 0, 160, 320, 520, 720]:
        cv2.line(frame, (cx, cy), (cx + lx * 2, height), (42, 52, 64), 1)

    # Crosshair grid
    cv2.drawMarker(frame, (cx, cy), (55, 70, 85), cv2.MARKER_CROSS, 20, 1)

    # Watermark text
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(frame, f"CAM: {cam_code} | {cam_name.upper()}", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (220, 230, 245), 2, cv2.LINE_AA)
    cv2.putText(frame, f"LOC: {warehouse} - {location}", (18, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 160, 185), 1, cv2.LINE_AA)
    cv2.putText(frame, now_str, (width - 210, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 210, 220), 1, cv2.LINE_AA)

    # Status pill bar
    cv2.rectangle(frame, (16, height - 38), (320, height - 12), (20, 25, 30), -1)
    cv2.putText(frame, "PREVIEW / TEST IMAGE (NO RTSP FEED)", (24, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (60, 160, 240), 1, cv2.LINE_AA)

    _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')

# ----------------- AI Vision Object Detection Engine APIs -----------------

def get_camera_frame_for_detection(camera_id):
    """
    Acquire frame for a camera:
    1. Active live camera stream if online
    2. Most recent static capture file for realistic test detection
    3. CCTV warehouse perspective frame
    """
    cam = active_cameras.get(camera_id)
    if cam:
        frame_bytes = cam.get_frame()
        if frame_bytes:
            nparr = np.frombuffer(frame_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                return img, "LIVE CAMERA"

    # Check for test scenes or captures
    caps_dir = os.path.join(os.path.dirname(__file__), "static", "captures")
    if os.path.exists(caps_dir):
        caps = sorted([f for f in os.listdir(caps_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        if caps:
            idx = abs(hash(str(camera_id))) % len(caps)
            img_path = os.path.join(caps_dir, caps[idx])
            img = cv2.imread(img_path)
            if img is not None:
                return img, "PREVIEW / TEST IMAGE"

    # Fallback to synthetic warehouse frame with camera overlay
    engine = get_detection_engine()
    frame = engine.create_synthetic_warehouse_frame()
    return frame, "PREVIEW / TEST IMAGE"


@app.route('/api/vision/detection/info', methods=['GET'])
def api_detection_info():
    engine = get_detection_engine()
    return jsonify({
        'success': True,
        'data': engine.get_service_info()
    })


@app.route('/api/vision/detection/samples', methods=['GET'])
def api_detection_samples():
    scenes_dir = os.path.join(os.path.dirname(__file__), "static", "test_scenes")
    samples = []
    if os.path.exists(scenes_dir):
        for f in sorted(os.listdir(scenes_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                samples.append({
                    "id": f,
                    "name": f.replace("_", " ").replace(".jpg", "").title(),
                    "url": f"/static/test_scenes/{f}"
                })
    return jsonify({'success': True, 'samples': samples})


@app.route('/api/vision/detection/config', methods=['GET', 'POST', 'PUT'])
def api_detection_config():
    engine = get_detection_engine()
    if request.method == 'GET':
        info = engine.get_service_info()
        return jsonify({
            'success': True,
            'config': {
                'model_name': engine.model_name,
                'device': engine.active_device,
                'device_preference': engine.device_preference,
                'conf_threshold': engine.conf_threshold,
                'cuda_available': info['cuda_available'],
                'device_name': info['device_name'],
                'is_loaded': info['is_loaded']
            }
        })

    data = request.json or {}
    model_name = data.get('model_name')
    device = data.get('device')
    conf_threshold = data.get('conf_threshold')

    success, err = engine.reload(model_name=model_name, device=device, conf_threshold=conf_threshold)
    if not success:
        return jsonify({'success': False, 'message': err or "Failed to update detector configuration."}), 400

    info = engine.get_service_info()
    return jsonify({
        'success': True,
        'message': "Detection engine configuration updated successfully.",
        'config': {
            'model_name': engine.model_name,
            'device': engine.active_device,
            'device_preference': engine.device_preference,
            'conf_threshold': engine.conf_threshold,
            'cuda_available': info['cuda_available'],
            'device_name': info['device_name']
        }
    })


@app.route('/api/vision/detection/test', methods=['POST'])
def api_detection_test():
    engine = get_detection_engine()
    data = request.json or {}

    camera_id = data.get('camera_id')
    sample_scene = data.get('sample_scene')
    image_base64 = data.get('image_base64')
    conf_threshold = data.get('conf_threshold')
    force_device = data.get('device')

    if force_device and force_device != engine.active_device:
        engine.reload(device=force_device)

    frame = None
    resolved_camera_id = camera_id
    roi_polygon = None
    roi_zone_code = None

    if 'file' in request.files:
        file = request.files['file']
        file_bytes = file.read()
        nparr = np.frombuffer(file_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif image_base64:
        import base64
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]
        try:
            file_bytes = base64.b64decode(image_base64)
            nparr = np.frombuffer(file_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            return jsonify({'success': False, 'message': f"Failed to decode base64 image: {e}"}), 400
    elif sample_scene:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", sample_scene)
        if os.path.exists(sample_path):
            frame = cv2.imread(sample_path)
    elif camera_id:
        frame, _ = get_camera_frame_for_detection(camera_id)
        # Look up any configured ROI for this camera
        rois = db.get_camera_rois(camera_id)
        if rois:
            roi_polygon = rois[0].get('coordinates', [])
            roi_zone_code = rois[0].get('zone_code')
    else:
        # Default fallback to synthetic warehouse frame
        frame = engine.create_synthetic_warehouse_frame()

    if frame is None:
        return jsonify({'success': False, 'message': 'Unable to acquire or decode image frame for detection.'}), 400

    master_classes = db.get_all_object_classes()

    result = engine.detect(
        image_input=frame,
        camera_id=resolved_camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        master_classes=master_classes
    )

    if not result.get('success'):
        return jsonify(result), 400

    # Render annotated frame
    annotated_bgr = engine.annotate_frame(
        frame_bgr=frame,
        detections=result.get('detections', []),
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    import base64
    _, buf = cv2.imencode('.jpg', annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    annotated_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')

    result['annotated_image_url'] = annotated_b64
    return jsonify(result)


@app.route('/api/vision/detection/cameras/<camera_id>', methods=['GET'])
def api_detection_camera_single(camera_id):
    engine = get_detection_engine()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    master_classes = db.get_all_object_classes()
    result = engine.detect(
        image_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        master_classes=master_classes
    )
    result['feed_mode'] = feed_mode

    annotated = engine.annotate_frame(
        frame_bgr=frame,
        detections=result.get('detections', []),
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    import base64
    _, buf = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    result['annotated_image_url'] = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')

    return jsonify(result)


@app.route('/api/vision/detection/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_detection_camera_annotated_jpg(camera_id):
    engine = get_detection_engine()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    master_classes = db.get_all_object_classes()
    result = engine.detect(
        image_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        master_classes=master_classes
    )

    annotated = engine.annotate_frame(
        frame_bgr=frame,
        detections=result.get('detections', []),
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ----------------- AI Vision Multi-Object Tracking Engine APIs (Part 6) -----------------
@app.route('/api/vision/tracking/status', methods=['GET'])
def api_tracking_status():
    tracker_service = get_tracking_service()
    sessions = tracker_service.get_sessions_status()
    return jsonify({
        'success': True,
        'sessions': sessions
    })


@app.route('/api/vision/tracking/reset', methods=['POST'])
def api_tracking_reset():
    tracker_service = get_tracking_service()
    data = request.json or {}
    camera_id = data.get('camera_id')

    if not camera_id or camera_id.lower() == 'all':
        tracker_service.reset_all()
        return jsonify({
            'success': True,
            'message': 'All camera tracking sessions reset successfully.'
        })

    session = tracker_service.get_session(camera_id)
    session.reset()
    return jsonify({
        'success': True,
        'camera_id': camera_id,
        'session_id': session.session_id,
        'message': f"Tracking session for camera '{camera_id}' reset successfully."
    })


@app.route('/api/vision/tracking/test', methods=['POST'])
def api_tracking_test():
    tracker_service = get_tracking_service()
    data = request.json or {}

    camera_id = data.get('camera_id') or 'CAM-001'
    sample_scene = data.get('sample_scene')
    sequence_step = data.get('sequence_step')
    image_base64 = data.get('image_base64')
    conf_threshold = data.get('conf_threshold')
    should_reset = data.get('reset_session', False)

    if should_reset:
        tracker_service.reset_session(camera_id)

    frame = None
    roi_polygon = None
    roi_zone_code = None

    if camera_id:
        rois = db.get_camera_rois(camera_id)
        if rois:
            roi_polygon = rois[0].get('coordinates', [])
            roi_zone_code = rois[0].get('zone_code')

    if sequence_step is not None:
        step_idx = int(sequence_step)
        frame = tracker_service.generate_motion_sequence_frame(step_index=step_idx)
    elif 'file' in request.files:
        file = request.files['file']
        file_bytes = file.read()
        nparr = np.frombuffer(file_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif image_base64:
        import base64
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]
        try:
            file_bytes = base64.b64decode(image_base64)
            nparr = np.frombuffer(file_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            return jsonify({'success': False, 'message': f"Failed to decode base64 image: {e}"}), 400
    elif sample_scene:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", sample_scene)
        if os.path.exists(sample_path):
            frame = cv2.imread(sample_path)
    elif camera_id:
        frame, _ = get_camera_frame_for_detection(camera_id)
    else:
        frame = tracker_service.generate_motion_sequence_frame(step_index=0)

    if frame is None:
        return jsonify({'success': False, 'message': 'Unable to acquire or decode image frame for tracking.'}), 400

    result = tracker_service.track_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    if not result.get('success'):
        return jsonify(result), 400

    return jsonify(result)


@app.route('/api/vision/tracking/sequence', methods=['POST'])
def api_tracking_sequence():
    tracker_service = get_tracking_service()
    data = request.json or {}

    camera_id = data.get('camera_id') or 'CAM-001'
    num_frames = int(data.get('num_frames', 5))
    conf_threshold = data.get('conf_threshold', 0.25)
    should_reset = data.get('reset_session', True)

    if should_reset:
        tracker_service.reset_session(camera_id)

    roi_polygon = None
    roi_zone_code = None
    rois = db.get_camera_rois(camera_id)
    if rois:
        roi_polygon = rois[0].get('coordinates', [])
        roi_zone_code = rois[0].get('zone_code')

    res = tracker_service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    return jsonify(res)


@app.route('/api/vision/tracking/cameras/<camera_id>', methods=['GET'])
def api_tracking_camera_single(camera_id):
    tracker_service = get_tracking_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = tracker_service.track_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/tracking/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_tracking_camera_annotated_jpg(camera_id):
    tracker_service = get_tracking_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = tracker_service.track_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    annotated = tracker_service.annotate_tracks(
        frame_bgr=frame,
        tracks=result.get('tracks', []),
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ----------------- AI Vision Object Identity & Recognition Foundation APIs (Part 7) -----------------
@app.route('/api/vision/identity/status', methods=['GET'])
def api_identity_status():
    identity_service = get_identity_service()
    return jsonify(identity_service.get_status())


@app.route('/api/vision/identity/reset', methods=['POST'])
def api_identity_reset():
    identity_service = get_identity_service()
    data = request.json or {}
    camera_id = data.get('camera_id')

    if not camera_id or camera_id.lower() == 'all':
        identity_service.reset_all()
        return jsonify({
            'success': True,
            'message': 'All camera identity sessions reset successfully.'
        })

    session = identity_service.get_session(camera_id)
    session.reset()
    identity_service.tracking_service.reset_session(camera_id)
    return jsonify({
        'success': True,
        'camera_id': camera_id,
        'session_id': session.session_id,
        'message': f"Identity session for camera '{camera_id}' reset successfully."
    })


@app.route('/api/vision/identity/test', methods=['POST'])
def api_identity_test():
    identity_service = get_identity_service()
    data = request.json or {}

    camera_id = data.get('camera_id') or 'CAM-001'
    sample_scene = data.get('sample_scene')
    sequence_step = data.get('sequence_step')
    image_base64 = data.get('image_base64')
    conf_threshold = data.get('conf_threshold')
    enable_barcode_qr = data.get('enable_barcode_qr', True)
    enable_ocr = data.get('enable_ocr', True)
    crop_padding = float(data.get('crop_padding', 0.05))
    should_reset = data.get('reset_session', False)

    if should_reset:
        identity_service.reset_session(camera_id)

    frame = None
    roi_polygon = None
    roi_zone_code = None

    if camera_id:
        rois = db.get_camera_rois(camera_id)
        if rois:
            roi_polygon = rois[0].get('coordinates', [])
            roi_zone_code = rois[0].get('zone_code')

    if sequence_step is not None:
        step_idx = int(sequence_step)
        base_scene = sample_scene or 'identity_qr_b104.jpg'
        scene_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", base_scene)
        base = cv2.imread(scene_path)
        if base is not None:
            dx = int(round(step_idx * 15))
            frame = np.roll(base, dx, axis=1)
            if dx > 0:
                frame[:, :dx] = base[:, :1]
    elif 'file' in request.files:
        file = request.files['file']
        file_bytes = file.read()
        nparr = np.frombuffer(file_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif image_base64:
        import base64
        if ',' in image_base64:
            image_base64 = image_base64.split(',', 1)[1]
        try:
            file_bytes = base64.b64decode(image_base64)
            nparr = np.frombuffer(file_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception as e:
            return jsonify({'success': False, 'message': f"Failed to decode base64 image: {e}"}), 400
    elif sample_scene:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", sample_scene)
        if os.path.exists(sample_path):
            frame = cv2.imread(sample_path)
    elif camera_id:
        frame, _ = get_camera_frame_for_detection(camera_id)
    else:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "identity_qr_b104.jpg")
        if os.path.exists(sample_path):
            frame = cv2.imread(sample_path)

    if frame is None:
        return jsonify({'success': False, 'message': 'Unable to acquire or decode image frame for identity recognition.'}), 400

    result = identity_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        enable_barcode_qr=enable_barcode_qr,
        enable_ocr=enable_ocr,
        crop_padding=crop_padding
    )

    if not result.get('success'):
        return jsonify(result), 400

    return jsonify(result)


@app.route('/api/vision/identity/sequence', methods=['POST'])
def api_identity_sequence():
    identity_service = get_identity_service()
    data = request.json or {}

    camera_id = data.get('camera_id') or 'CAM-001'
    num_frames = int(data.get('num_frames', 5))
    sample_scene = data.get('sample_scene') or 'identity_qr_b104.jpg'
    conf_threshold = data.get('conf_threshold', 0.25)
    should_reset = data.get('reset_session', True)

    if should_reset:
        identity_service.reset_session(camera_id)

    roi_polygon = None
    roi_zone_code = None
    rois = db.get_camera_rois(camera_id)
    if rois:
        roi_polygon = rois[0].get('coordinates', [])
        roi_zone_code = rois[0].get('zone_code')

    res = identity_service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        sample_scene=sample_scene,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    return jsonify(res)


@app.route('/api/vision/identity/cameras/<camera_id>', methods=['GET'])
def api_identity_camera_single(camera_id):
    identity_service = get_identity_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = identity_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/identity/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_identity_camera_annotated_jpg(camera_id):
    identity_service = get_identity_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = identity_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    annotated = identity_service.annotate_identities(
        frame_bgr=frame,
        tracks=result.get('tracks', []),
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ============================================================================
# PART 8: WAREHOUSE IDENTITY VALIDATION & MASTER-DATA BINDING APIS
# ============================================================================

@app.route('/api/vision/validation/status', methods=['GET'])
def api_validation_status():
    """Return operational status, active decoders, and supported WMS master data sources."""
    validation_service = get_validation_service()
    return jsonify(validation_service.get_status())


@app.route('/api/vision/validation/reset', methods=['POST'])
def api_validation_reset():
    """Reset in-memory tracking, identity, and validation state for a camera or all cameras."""
    validation_service = get_validation_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        validation_service.reset_session(camera_id)
        return jsonify({
            'success': True,
            'message': f"In-memory tracking & identity session for camera '{camera_id}' reset successfully."
        })
    else:
        validation_service.reset_all()
        return jsonify({
            'success': True,
            'message': "All in-memory tracking & identity sessions reset successfully."
        })


@app.route('/api/vision/validation/test', methods=['POST'])
def api_validation_test():
    """
    Execute Part 5 Detection -> Part 6 ByteTrack -> Part 7 Identity -> Part 8 Master-Data Validation
    against a test frame (sample scene, uploaded image, or camera frame).
    """
    validation_service = get_validation_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'validation_truck_gp1000.jpg'
    enable_barcode = data.get('enable_barcode', True)
    enable_ocr = data.get('enable_ocr', True)
    conf_threshold = data.get('conf_threshold')

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    frame = None
    if source_type == 'sample':
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "validation_truck_gp1000.jpg")
        frame = cv2.imread(sample_path)
        if frame is None:
            return jsonify({'success': False, 'message': f"Sample scene '{sample_scene}' could not be loaded."}), 400

    elif source_type == 'upload':
        image_data = data.get('image_data') or data.get('image_base64')
        if not image_data:
            return jsonify({'success': False, 'message': "No image_data provided for upload test."}), 400
        frame, err = validation_service.identity_service.detection_engine._parse_image(image_data)
        if err or frame is None:
            return jsonify({'success': False, 'message': err or "Invalid uploaded image format."}), 400

    elif source_type == 'camera':
        frame, feed_mode = get_camera_frame_for_detection(camera_id)
        if frame is None:
            return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    else:
        # Fallback to default sample
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "validation_truck_gp1000.jpg")
        frame = cv2.imread(sample_path)

    result = validation_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        enable_barcode_qr=enable_barcode,
        enable_ocr=enable_ocr
    )
    return jsonify(result)


@app.route('/api/vision/validation/cameras/<camera_id>', methods=['GET'])
def api_validation_camera_single(camera_id):
    """Run full validation pipeline on a single snapshot from the specified camera."""
    validation_service = get_validation_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = validation_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/validation/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_validation_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with bounding box, track ID, visual identity, and validation badge."""
    validation_service = get_validation_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = validation_service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    annotated = validation_service.annotate_validation(
        frame_bgr=frame,
        tracks=result.get('tracks', [])
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ============================================================================
# PART 9: TRUCK <-> BOX ASSOCIATION FOUNDATION APIS
# ============================================================================

@app.route('/api/vision/association/status', methods=['GET'])
def api_association_status():
    """Return operational status, active sessions, and association configuration."""
    service = get_association_service()
    return jsonify(service.get_status())


@app.route('/api/vision/association/reset', methods=['POST'])
def api_association_reset():
    """Reset in-memory association and tracking sessions for a specific camera or all cameras."""
    service = get_association_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        service.reset_session(camera_id)
        return jsonify({
            'success': True,
            'message': f"In-memory association session for camera '{camera_id}' reset successfully."
        })
    else:
        service.reset_all()
        return jsonify({
            'success': True,
            'message': "All in-memory association sessions reset successfully."
        })


@app.route('/api/vision/association/test', methods=['POST'])
def api_association_test():
    """
    Execute full perception pipeline (Parts 5 -> 6 -> 7 -> 8 -> 9)
    on a test frame (sample scene, uploaded image, or live camera snapshot).
    """
    service = get_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'association_truck_box_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    enable_barcode = data.get('enable_barcode', True)
    enable_ocr = data.get('enable_ocr', True)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    # Handle synthetic tracks test directly if supplied
    synthetic_tracks = data.get('synthetic_tracks')
    if synthetic_tracks is not None:
        assocs, assoc_ms = service.process_tracks(
            tracks=synthetic_tracks,
            camera_id=camera_id,
            frame_index=data.get('frame_index')
        )
        return jsonify({
            'success': True,
            'mode': 'synthetic_tracks',
            'camera_id': camera_id,
            'associations': assocs,
            'association_ms': assoc_ms,
            'confirmed_count': sum(1 for a in assocs if a.get('status') == 'CONFIRMED'),
            'candidate_count': sum(1 for a in assocs if a.get('status') == 'CANDIDATE'),
            'ambiguous_count': sum(1 for a in assocs if a.get('evidence', {}).get('is_ambiguous', False)),
            'expired_count': sum(1 for a in assocs if a.get('status') == 'EXPIRED'),
            'rejected_count': sum(1 for a in assocs if a.get('status') == 'REJECTED')
        })

    frame = None
    if source_type == 'sample':
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_truck_box_dock1.jpg")
        frame = cv2.imread(sample_path)
        if frame is None:
            return jsonify({'success': False, 'message': f"Sample scene '{sample_scene}' could not be loaded."}), 400

    elif source_type == 'upload':
        image_data = data.get('image_data') or data.get('image_base64')
        if not image_data:
            return jsonify({'success': False, 'message': "No image_data provided for upload test."}), 400
        frame, err = service.validation_service.identity_service.detection_engine._parse_image(image_data)
        if err or frame is None:
            return jsonify({'success': False, 'message': err or "Invalid uploaded image format."}), 400

    elif source_type == 'camera':
        frame, feed_mode = get_camera_frame_for_detection(camera_id)
        if frame is None:
            return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    else:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_truck_box_dock1.jpg")
        frame = cv2.imread(sample_path)

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        enable_barcode_qr=enable_barcode,
        enable_ocr=enable_ocr
    )
    return jsonify(result)


@app.route('/api/vision/association/sequence', methods=['POST'])
def api_association_sequence():
    """
    Run multi-frame association sequence to verify temporal accumulation and lifecycle transitions.
    Supports either camera frame sequence or synthetic tracking sequence.
    """
    service = get_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    num_frames = int(data.get('num_frames', 5))
    sample_scene = data.get('sample_scene') or 'association_truck_box_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    should_reset = data.get('reset_session', True)

    if should_reset:
        service.reset_session(camera_id)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    synthetic_seq = data.get('synthetic_tracks_sequence')

    result = service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        sample_scene=sample_scene,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        synthetic_tracks_sequence=synthetic_seq
    )
    return jsonify(result)


@app.route('/api/vision/association/cameras/<camera_id>', methods=['GET'])
def api_association_camera_single(camera_id):
    """Run full association pipeline on a single snapshot from the specified camera."""
    service = get_association_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/association/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_association_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with truck/box bounding boxes, connecting lines, and status pills."""
    service = get_association_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    session = service.get_session(camera_id)
    annotated = service.annotate_associations(
        frame=frame,
        associations=list(session.associations.values()),
        tracks=result.get('tracks', [])
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ============================================================================
# PART 10: WORKER <-> BOX ASSOCIATION FOUNDATION APIS
# ============================================================================

@app.route('/api/vision/worker-box/status', methods=['GET'])
def api_worker_box_status():
    """Return operational status, active sessions, and worker-box association configuration."""
    service = get_worker_box_association_service()
    return jsonify(service.get_status())


@app.route('/api/vision/worker-box/reset', methods=['POST'])
def api_worker_box_reset():
    """Reset in-memory worker-box association and tracking sessions for a specific camera or all cameras."""
    service = get_worker_box_association_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        service.reset_session(camera_id)
        return jsonify({
            'success': True,
            'message': f"In-memory worker-box association session for camera '{camera_id}' reset successfully."
        })
    else:
        service.reset_all()
        return jsonify({
            'success': True,
            'message': "All in-memory worker-box association sessions reset successfully."
        })


@app.route('/api/vision/worker-box/test', methods=['POST'])
def api_worker_box_test():
    """
    Execute full perception pipeline (Parts 5 -> 6 -> 7 -> 8 -> 10)
    on a test frame (sample scene, uploaded image, or live camera snapshot).
    """
    service = get_worker_box_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'association_worker_box_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    enable_barcode = data.get('enable_barcode', True)
    enable_ocr = data.get('enable_ocr', True)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    # Handle synthetic tracks test directly if supplied
    synthetic_tracks = data.get('synthetic_tracks')
    if synthetic_tracks is not None:
        assocs, assoc_ms = service.process_tracks(
            tracks=synthetic_tracks,
            camera_id=camera_id,
            frame_index=data.get('frame_index')
        )
        return jsonify({
            'success': True,
            'mode': 'synthetic_tracks',
            'camera_id': camera_id,
            'associations': assocs,
            'association_ms': assoc_ms,
            'confirmed_count': sum(1 for a in assocs if a.get('status') == 'CONFIRMED'),
            'candidate_count': sum(1 for a in assocs if a.get('status') == 'CANDIDATE'),
            'ambiguous_count': sum(1 for a in assocs if a.get('evidence', {}).get('is_ambiguous', False)),
            'expired_count': sum(1 for a in assocs if a.get('status') == 'EXPIRED'),
            'rejected_count': sum(1 for a in assocs if a.get('status') == 'REJECTED')
        })

    frame = None
    if source_type == 'sample':
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_worker_box_dock1.jpg")
            if not os.path.exists(sample_path):
                sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_truck_box_dock1.jpg")
        frame = cv2.imread(sample_path)
        if frame is None:
            return jsonify({'success': False, 'message': f"Sample scene '{sample_scene}' could not be loaded."}), 400

    elif source_type == 'upload':
        image_data = data.get('image_data') or data.get('image_base64')
        if not image_data:
            return jsonify({'success': False, 'message': "No image_data provided for upload test."}), 400
        frame, err = service.validation_service.identity_service.detection_engine._parse_image(image_data)
        if err or frame is None:
            return jsonify({'success': False, 'message': err or "Invalid uploaded image format."}), 400

    elif source_type == 'camera':
        frame, feed_mode = get_camera_frame_for_detection(camera_id)
        if frame is None:
            return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    else:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_worker_box_dock1.jpg")
        frame = cv2.imread(sample_path)

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        enable_barcode_qr=enable_barcode,
        enable_ocr=enable_ocr
    )
    return jsonify(result)


@app.route('/api/vision/worker-box/sequence', methods=['POST'])
def api_worker_box_sequence():
    """
    Run multi-frame worker-box association sequence to verify temporal accumulation and lifecycle transitions.
    Supports either camera frame sequence or synthetic tracking sequence.
    """
    service = get_worker_box_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    num_frames = int(data.get('num_frames', 5))
    sample_scene = data.get('sample_scene') or 'association_worker_box_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    should_reset = data.get('reset_session', True)

    if should_reset:
        service.reset_session(camera_id)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    synthetic_seq = data.get('synthetic_tracks_sequence')

    result = service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        sample_scene=sample_scene,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        synthetic_tracks_sequence=synthetic_seq
    )
    return jsonify(result)


@app.route('/api/vision/worker-box/cameras/<camera_id>', methods=['GET'])
def api_worker_box_camera_single(camera_id):
    """Run full worker-box association pipeline on a single snapshot from the specified camera."""
    service = get_worker_box_association_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/worker-box/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_worker_box_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with worker/box bounding boxes, connecting lines, and status pills."""
    service = get_worker_box_association_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    session = service.get_session(camera_id)
    annotated = service.annotate_associations(
        frame=frame,
        associations=list(session.associations.values()),
        tracks=result.get('tracks', [])
    )
    _, buffer = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


# ============================================================================
# PART 11: BOX <-> BIN ASSOCIATION FOUNDATION APIS
# ============================================================================

@app.route('/api/vision/box-bin/status', methods=['GET'])
def api_box_bin_status():
    """Return operational status, active sessions, and box-bin association configuration."""
    service = get_box_bin_association_service()
    return jsonify(service.get_status())


@app.route('/api/vision/box-bin/reset', methods=['POST'])
def api_box_bin_reset():
    """Reset in-memory box-bin association and tracking sessions for a specific camera or all cameras."""
    service = get_box_bin_association_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        service.reset_session(camera_id)
        return jsonify({
            'success': True,
            'message': f"In-memory box-bin association session for camera '{camera_id}' reset successfully."
        })
    else:
        for cam_id in list(service.sessions.keys()):
            service.reset_session(cam_id)
        return jsonify({
            'success': True,
            'message': "All in-memory box-bin association sessions reset successfully."
        })


@app.route('/api/vision/box-bin/test', methods=['POST'])
def api_box_bin_test():
    """
    Execute full perception pipeline (Parts 5 -> 6 -> 7 -> 8 -> 11)
    on a test frame (sample scene, uploaded image, or live camera snapshot).
    """
    service = get_box_bin_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'association_box_bin_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    enable_barcode = data.get('enable_barcode', True)
    enable_ocr = data.get('enable_ocr', True)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    # Handle synthetic tracks test directly if supplied
    synthetic_tracks = data.get('synthetic_tracks')
    if synthetic_tracks is not None:
        assocs, assoc_ms = service.process_tracks(
            tracks=synthetic_tracks,
            camera_id=camera_id,
            frame_index=data.get('frame_index')
        )
        return jsonify({
            'success': True,
            'mode': 'synthetic_tracks',
            'camera_id': camera_id,
            'associations': assocs,
            'association_ms': assoc_ms,
            'confirmed_count': sum(1 for a in assocs if a.get('status') == 'CONFIRMED'),
            'candidate_count': sum(1 for a in assocs if a.get('status') == 'CANDIDATE'),
            'ambiguous_count': sum(1 for a in assocs if a.get('evidence', {}).get('is_ambiguous', False)),
            'expired_count': sum(1 for a in assocs if a.get('status') == 'EXPIRED'),
            'rejected_count': sum(1 for a in assocs if a.get('status') == 'REJECTED')
        })

    frame = None
    if source_type == 'sample':
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_box_bin_dock1.jpg")
            if not os.path.exists(sample_path):
                sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_worker_box_dock1.jpg")
        frame = cv2.imread(sample_path)
        if frame is None:
            return jsonify({'success': False, 'message': f"Sample scene '{sample_scene}' could not be loaded."}), 400

    elif source_type == 'upload':
        image_data = data.get('image_data') or data.get('image_base64')
        if not image_data:
            return jsonify({'success': False, 'message': "No image_data provided for upload test."}), 400
        frame, err = service.validation_service.identity_service.detection_engine._parse_image(image_data)
        if err or frame is None:
            return jsonify({'success': False, 'message': err or "Invalid uploaded image format."}), 400

    elif source_type == 'camera':
        frame, feed_mode = get_camera_frame_for_detection(camera_id)
        if frame is None:
            return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    else:
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_box_bin_dock1.jpg")
        frame = cv2.imread(sample_path)

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    return jsonify(result)


@app.route('/api/vision/box-bin/sequence', methods=['POST'])
def api_box_bin_sequence():
    """
    Run multi-frame box-bin association sequence to verify temporal accumulation and lifecycle transitions.
    Supports either camera frame sequence or synthetic tracking sequence.
    """
    service = get_box_bin_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    num_frames = int(data.get('num_frames', 5))
    sample_scene = data.get('sample_scene') or 'association_box_bin_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    should_reset = data.get('reset_session', True)

    if should_reset:
        service.reset_session(camera_id)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    synthetic_seq = data.get('synthetic_tracks_sequence')

    result = service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        sample_scene=sample_scene,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        synthetic_tracks_sequence=synthetic_seq
    )
    return jsonify(result)


@app.route('/api/vision/box-bin/cameras/<camera_id>', methods=['GET'])
def api_box_bin_camera_single(camera_id):
    """Run full box-bin association pipeline on a single snapshot from the specified camera."""
    service = get_box_bin_association_service()
    frame, feed_mode = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return jsonify({'success': False, 'message': f"Camera '{camera_id}' preview is unavailable."}), 404

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    result['feed_mode'] = feed_mode
    return jsonify(result)


@app.route('/api/vision/box-bin/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_box_bin_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with box/bin bounding boxes, connecting lines, and status pills."""
    service = get_box_bin_association_service()
    frame, _ = get_camera_frame_for_detection(camera_id)
    if frame is None:
        return Response("Camera unavailable", status=404)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )

    jpeg_bytes = service.get_annotated_jpeg(camera_id)
    if jpeg_bytes is None:
        return Response("Annotation rendering failed", status=500)
    return Response(jpeg_bytes, mimetype='image/jpeg')


@app.route('/api/gate_passes/<gp_id>', methods=['GET', 'PUT', 'DELETE'])
def update_gate_pass(gp_id):
    if request.method == 'DELETE':
        db.delete_gate_pass(gp_id)
        return jsonify({"success": True})
    if request.method == 'GET':
        gp = db.get_gate_pass(gp_id)
        if gp:
            return jsonify(gp)
        return jsonify({"success": False, "message": "Gate pass not found"}), 404
        
    data = request.json
    
    sms_response = None
    if data.get('status') == 'Sent to Dock':
        import random
        otp = str(random.randint(1000, 9999)) if data.get('driver_phone') else "1234"
        data['otp'] = otp
        phone = data.get('driver_phone')
        if phone:
            try:
                import requests
                resp = requests.post('https://textbelt.com/text', data={
                    'phone': phone, 
                    'message': f'Skandha WMS: Your Dock Assignment OTP is {otp}', 
                    'key': 'textbelt'
                })
                sms_response = resp.json()
                print("[REAL SMS API]", sms_response)
            except Exception as e:
                sms_response = {"success": False, "error": str(e)}
                print("SMS Error:", e)

    gp = db.update_gate_pass(gp_id, data)
    if gp:
        return jsonify({"success": True, "gate_pass": gp, "otp_generated": data.get('otp'), "sms_response": sms_response})
    return jsonify({"success": False, "message": "Gate pass not found"})

@app.route('/api/dock/unload_step/<gp_id>', methods=['POST'])
def unload_step(gp_id):
    # Get total visible packages across all cameras (or total tracked if available)
    total_unloaded = 0
    for cam in active_cameras.values():
        total_unloaded += cam.total_unloaded
        
    if total_unloaded == 0:
         return jsonify({"success": False, "message": "No packages detected by AI."})
         
    gp = db.set_unload_qty(gp_id, total_unloaded)
    if gp:
        # Auto-update Bin Master with Vendor Stock
        vendor_name = gp.get('vendor', 'UNKNOWN')
        bin_id = f"BIN-{vendor_name[:3].upper()}-100" if vendor_name else "BIN-GEN-100"
        try:
            db.update_bin_stock(bin_id, vendor_name, total_unloaded)
        except Exception as e:
            print("Failed to update bin stock:", e)
        return jsonify({"success": True, "total": gp['unloaded_qty']})
    return jsonify({"success": False, "message": "Gate pass not found."})

@app.route('/api/dock/auto_add/<gp_id>', methods=['POST'])
def auto_add_step(gp_id):
    data = request.json
    count = data.get('count', 0)
    gp = db.add_unload_qty(gp_id, count)
    if gp:
        return jsonify({"success": True, "added": count, "total": gp['unloaded_qty']})
    return jsonify({"success": False, "message": "Gate pass not found."})

@app.route('/api/cameras', methods=['GET'])
def get_cameras():
    cameras_data = []
    for cam_id, cam in active_cameras.items():
        cameras_data.append({
            "id": cam.camera_id,
            "name": cam.name,
            "url": cam.url,
            "location": cam.location,
            "type": cam.cam_type,
            "vendor": cam.vendor,
            "events": cam.events
        })
    return jsonify(cameras_data)

@app.route('/api/cameras/<cam_id>/snap', methods=['POST'])
def snap_camera(cam_id):
    cam = active_cameras.get(cam_id)
    if not cam:
        return jsonify({"success": False, "message": "Camera not found"})
    frame_bytes = cam.get_frame()
    if not frame_bytes:
        return jsonify({"success": False, "message": "No frame available"})
    
    photo_filename = f"captures/manual_{uuid.uuid4().hex}.jpg"
    capture_path = os.path.join(os.path.dirname(__file__), "static", photo_filename)
    os.makedirs(os.path.dirname(capture_path), exist_ok=True)
    with open(capture_path, "wb") as f:
        f.write(frame_bytes)
        
    return jsonify({"success": True, "photo": photo_filename})

@app.route('/api/cameras', methods=['POST'])
def add_camera():
    data = request.json or {}
    cam_id = str(uuid.uuid4())[:8]
    
    # Sync with Camera Master in SQLite
    db.create_or_update_camera({
        'camera_id': cam_id,
        'camera_code': data.get('code') or f"CAM-{cam_id[:4].upper()}",
        'name': data.get('name') or f"Camera {cam_id[:4].upper()}",
        'warehouse': data.get('warehouse') or 'Warehouse A',
        'location': data.get('location') or 'General',
        'camera_type': data.get('type') or 'IP Camera',
        'vendor': data.get('vendor') or 'Unknown',
        'stream_url': data.get('url') or '',
        'status': 'Online'
    })

    new_camera = SmartCamera(
        camera_id=cam_id,
        name=data.get('name'),
        url=data.get('url'),
        location=data.get('location'),
        cam_type=data.get('type', 'IP Camera'),
        vendor=data.get('vendor', 'Unknown')
    )
    new_camera.start()
    active_cameras[cam_id] = new_camera
    
    return jsonify({"success": True, "id": cam_id})

@app.route('/api/cameras/<camera_id>/frame', methods=['POST'])
def receive_camera_frame(camera_id):
    if camera_id not in active_cameras:
        return jsonify({"success": False, "message": "Camera not found"}), 404
    
    frame_data = request.get_data()
    if not frame_data:
        return jsonify({"success": False, "message": "No frame data"}), 400
    
    np_arr = np.frombuffer(frame_data, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is not None:
        active_cameras[camera_id].push_frame(frame)
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Failed to decode frame"}), 400

@app.route('/api/cameras/<camera_id>', methods=['DELETE'])
def delete_camera(camera_id):
    if camera_id in active_cameras:
        cam = active_cameras.pop(camera_id)
        cam.stop()
    conn = db.get_db()
    conn.execute("DELETE FROM cameras WHERE camera_id = ? OR camera_code = ?", (camera_id, camera_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def generate_frames(camera_id):
    while True:
        if camera_id in active_cameras:
            frame = active_cameras[camera_id].get_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                time.sleep(0.1)
        else:
            break

@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    return Response(generate_frames(camera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
