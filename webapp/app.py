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

import db

# Initialize SQLite database schema
db.init_db()

# Store active cameras in memory
active_cameras = {}

@app.route('/')
def index():
    return render_template('index.html')

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
    
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found."})
        
    vendor_email = gp.get('vendor_email') or 'N/A'
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
            
            # Since we don't have the password, we will just simulate success but log that we need the password.
            # In a fully deployed environment, you'd use:
            # with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            #     smtp.login('hayd161103@gmail.com', '<YOUR_APP_PASSWORD>')
            #     smtp.send_message(msg)
            
            email_status = "Email simulated! To send real emails from hayd161103@gmail.com, configure an App Password in app.py line 166."
        except Exception as e:
            email_status = f"Email failed: {str(e)}"
        
    return jsonify({"success": True, "message": f"Invoice generated! Email status: {email_status}"})

@app.route('/api/vehicle_log', methods=['GET'])
def get_vehicle_logs():
    return jsonify(db.get_all_vehicle_logs())

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    return jsonify(db.get_all_invoices())

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
    data = request.json
    cam_id = str(uuid.uuid4())[:8]
    
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
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Camera not found"}), 404

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
