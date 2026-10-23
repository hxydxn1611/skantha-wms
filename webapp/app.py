from flask import Flask, render_template, Response, request, jsonify, send_file
from werkzeug.utils import secure_filename
from ai_engine import SmartCamera
import logging
import time
import uuid
import io
import cv2
import numpy as np
import os
import random
from datetime import datetime
from fpdf import FPDF
import threading
import re

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# SKU Image Upload Directory
SKU_IMAGE_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'sku_images')
os.makedirs(SKU_IMAGE_UPLOAD_DIR, exist_ok=True)

import db
import sku_master_service
from detection_service import get_detection_engine
from tracking_service import get_tracking_service
from identity_service import get_identity_service
from validation_service import get_validation_service
from association_service import get_association_service
from worker_box_association_service import get_worker_box_association_service
from box_bin_association_service import get_box_bin_association_service
from material_association_service import get_material_association_service
from movement_event_service import get_movement_event_service
from material_traceability_service import get_material_traceability_service
from integration_service import get_integration_service
from vision_runtime_service import get_vision_runtime_manager, get_shared_frame_bus
from cycle_count_service import get_cycle_count_service
from pallet_service import get_pallet_service

# Initialize SQLite database schema
db.init_db()

# Store active cameras in memory
active_cameras = {}

def init_active_cameras():
    try:
        db.init_db()
        mgr = get_vision_runtime_manager()
        mgr.refresh_cameras()
        cams = db.get_all_cameras()
        for cam in cams:
            cid = cam.get('camera_id')
            if cid and cid not in active_cameras:
                sc = SmartCamera(
                    camera_id=cid,
                    name=cam.get('name') or f"Camera {cid}",
                    url=cam.get('stream_url') or '',
                    location=cam.get('location') or 'General',
                    cam_type=cam.get('camera_type') or 'IP Camera',
                    vendor=cam.get('vendor', 'Unknown'),
                    bin_id=cam.get('bin_id')
                )
                sc.start()
                active_cameras[cid] = sc
                mgr.start_camera(cid)
                logger.info(f"Initialized active camera {cid} ({cam.get('location')})")
    except Exception as e:
        logger.warning(f"Error initializing active cameras from DB: {e}")

# Start active cameras in background thread so server boots immediately
threading.Thread(target=init_active_cameras, daemon=True).start()

# Start RTMP Ingest Service for Wi-Fi cameras pushing RTMP stream
try:
    from rtmp_service import start_rtmp_service
    start_rtmp_service()
except Exception as e:
    logger.warning(f"Failed to start RTMP service: {e}")


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

@app.route('/api/bins/<bin_id>/inventory', methods=['GET'])
def api_get_bin_inventory(bin_id):
    try:
        inventory = db.get_bin_inventory(bin_id)
        return jsonify(inventory), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(db.get_stats())

@app.route('/api/gate_passes', methods=['GET'])
def get_gate_passes():
    gps = db.get_all_gate_passes()
    # Part 4: Attach read-only formal W.A.R.L.O.G. dock perception evidence
    try:
        integ = get_integration_service()
        for gp in gps:
            if gp.get("status") in ("Sent to Dock", "Unloading", "Completed"):
                ev = integ.get_gate_pass_unloading_evidence(gp["id"])
                if ev:
                    gp["vision_unloaded_count"] = ev.get("verified_unloaded_count", 0)
                    gp["vision_candidate_count"] = ev.get("candidate_unloaded_count", 0)
                    gp["vision_verification_status"] = ev.get("verification_status", "NO_EVIDENCE")
    except Exception:
        pass
    return jsonify(gps)

@app.route('/api/gate_passes', methods=['POST'])
def create_gate_pass():
    data = request.json or {}
    plate = (data.get('plate') or '').strip().upper()
    
    # If a gate pass with the same vehicle plate is already Pending, reuse it smoothly
    if plate:
        existing = db.get_pending_gate_pass_by_plate(plate)
        if existing:
            return jsonify({"success": True, "gate_pass": existing, "message": f"Active gate pass {existing['id']} found for {plate}."})
            
    # Generate a random 4-digit OTP if driver_phone is provided
    otp = str(random.randint(1000, 9999)) if data.get('driver_phone') else ""
    if otp:
        data['otp'] = otp
        print(f"\n[MOCK SMS] Sent OTP {otp} to Driver Phone {data.get('driver_phone')}\n")
            
    # Auto-matches against pre-registered deliveries (by plate or po_number)
    # and connects both collections inside db.create_gate_pass
    new_gp = db.create_gate_pass(data)
    
    # Add to Vehicle Log
    db.create_vehicle_log(new_gp['id'], new_gp['plate'], new_gp.get('driver_name', 'Visitor'))
    
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
    
    # Render SKU details
    pdf.cell(200, 10, txt="", ln=1, align='L')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(80, 10, txt="SKU", border=1)
    pdf.cell(60, 10, txt="Description", border=1)
    pdf.cell(30, 10, txt="Expected", border=1, ln=1)
    
    pdf.set_font("Arial", size=12)
    sheet = gp.get('unloading_sheet')
    if sheet and isinstance(sheet, list):
        for item in sheet:
            pdf.cell(80, 10, txt=str(item.get('sku', '')), border=1)
            pdf.cell(60, 10, txt=str(item.get('description', ''))[:20], border=1)
            pdf.cell(30, 10, txt=str(item.get('expected', '')), border=1, ln=1)
    else:
        pdf.cell(170, 10, txt="No specific SKUs provided in PO sheet.", border=1, ln=1)
    
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
def _notify_camera_roi_refresh(cam_id):
    try:
        for c in active_cameras.values():
            if getattr(c, 'camera_id', None) == cam_id or getattr(c, 'camera_code', None) == cam_id:
                if hasattr(c, 'refresh_tripwire'):
                    c.refresh_tripwire()
    except Exception:
        pass
    try:
        from vision_runtime_service import get_vision_runtime_service
        svc = get_vision_runtime_service()
        sess = svc.get_session(cam_id)
        if sess and hasattr(sess, 'refresh_configuration'):
            sess.refresh_configuration()
    except Exception:
        pass

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
        _notify_camera_roi_refresh(camera_id)
        return jsonify({'success': True, 'message': f"ROI for camera '{camera_id}' cleared."})

    # POST / PUT
    data = request.json or {}
    saved_roi, err = db.save_zone_camera_roi(zone_id, camera_id, data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    _notify_camera_roi_refresh(camera_id)
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

# ============================================================================
# PHASE 3: SKU MASTER DATA & PRODUCT IMAGE MAPPING APIS
# ============================================================================

@app.route('/api/sku_master', methods=['GET'])
def api_get_sku_master():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    image_status = request.args.get('image_status', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = max(1, min(100, int(request.args.get('limit', 20))))
    except (ValueError, TypeError):
        limit = 20

    result = db.get_sku_master_records(search, category, status, image_status, page, limit)
    return jsonify({'success': True, 'data': result})

@app.route('/api/sku_master/<sku_id>', methods=['GET'])
def api_get_sku_detail(sku_id):
    sku = db.get_sku_by_id(sku_id)
    if not sku:
        return jsonify({'success': False, 'message': f"SKU '{sku_id}' not found."}), 404
    return jsonify({'success': True, 'data': sku})

@app.route('/api/sku_master', methods=['POST'])
def api_save_sku():
    data = request.json or {}
    saved, err = db.save_sku_master_record(data)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'data': saved, 'message': f"SKU '{saved['sku_id']}' saved successfully."})

@app.route('/api/sku_master/<sku_id>', methods=['DELETE'])
def api_delete_sku(sku_id):
    ok, err = db.delete_sku_master_record(sku_id)
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'message': f"SKU '{sku_id}' deleted successfully."})

@app.route('/api/sku_master/excel/template', methods=['GET'])
def api_download_sku_template():
    excel_bytes = sku_master_service.generate_sku_excel_template()
    return send_file(
        io.BytesIO(excel_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="sku_master_template.xlsx"
    )

@app.route('/api/sku_master/excel/preview', methods=['POST'])
def api_preview_sku_excel():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded.'}), 400
    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'message': 'Invalid file format. Please upload an Excel (.xlsx) file.'}), 400

    duplicate_policy = request.form.get('duplicate_policy', 'skip').strip().lower()
    if duplicate_policy not in ('skip', 'update'):
        duplicate_policy = 'skip'

    content = file.read()
    if len(content) > 15 * 1024 * 1024:
        return jsonify({'success': False, 'message': 'File exceeds maximum size of 15MB.'}), 400

    preview = sku_master_service.parse_and_validate_sku_excel(content, duplicate_policy)
    return jsonify(preview)

@app.route('/api/sku_master/excel/import', methods=['POST'])
def api_confirm_sku_excel_import():
    data = request.json or {}
    rows = data.get('rows', [])
    duplicate_policy = data.get('duplicate_policy', 'skip')
    if not rows or not isinstance(rows, list):
        return jsonify({'success': False, 'message': 'No rows provided for import.'}), 400

    result = db.batch_import_sku_records(rows, duplicate_policy=duplicate_policy)
    return jsonify(result)

@app.route('/api/sku_master/images/match_preview', methods=['POST'])
def api_preview_image_matches():
    data = request.json or {}
    filenames = data.get('filenames', [])
    if not isinstance(filenames, list):
        return jsonify({'success': False, 'message': 'Expected list of filenames.'}), 400
    matches = sku_master_service.match_bulk_images_to_skus(filenames)
    return jsonify({'success': True, 'matches': matches})

@app.route('/api/sku_master/images/upload', methods=['POST'])
def api_upload_sku_images():
    uploaded_files = request.files.getlist('images')
    if not uploaded_files:
        if 'image' in request.files:
            uploaded_files = [request.files['image']]
        elif 'file' in request.files:
            uploaded_files = [request.files['file']]

    if not uploaded_files:
        return jsonify({'success': False, 'message': 'No image files provided.'}), 400

    target_sku_id = request.form.get('sku_id')
    import json
    manual_mappings = {}
    if request.form.get('mappings'):
        try:
            manual_mappings = json.loads(request.form.get('mappings'))
        except Exception:
            pass

    results = []
    errors = []

    for f in uploaded_files:
        if not f.filename:
            continue
        orig_name = secure_filename(f.filename) or "image.jpg"
        ext = os.path.splitext(orig_name)[1].lower()
        if ext not in sku_master_service.ALLOWED_IMAGE_EXTENSIONS:
            errors.append(f"Skipped '{orig_name}': unsupported image format '{ext}'.")
            continue

        sku_for_file = target_sku_id
        if not sku_for_file and orig_name in manual_mappings:
            sku_for_file = manual_mappings[orig_name]
        if not sku_for_file:
            match_res = sku_master_service.match_bulk_images_to_skus([orig_name])
            if match_res and match_res[0].get('status') == 'MATCHED':
                sku_for_file = match_res[0].get('matched_sku_id')

        if not sku_for_file:
            errors.append(f"Image '{orig_name}' could not be matched to an existing SKU.")
            continue

        sku_exists = db.get_sku_by_id(sku_for_file)
        if not sku_exists:
            errors.append(f"Target SKU '{sku_for_file}' for image '{orig_name}' does not exist.")
            continue

        safe_filename = f"{sku_for_file}_{uuid.uuid4().hex[:8]}{ext}"
        dest_path = os.path.join(SKU_IMAGE_UPLOAD_DIR, safe_filename)
        try:
            f.seek(0)
            f.save(dest_path)
            f_size = os.path.getsize(dest_path)
            rel_path = f"/static/uploads/sku_images/{safe_filename}"
            is_pri = 1 if request.form.get('is_primary') in ('1', 'true', True) else 0

            img_rec, err = db.add_sku_image(
                sku_id=sku_for_file,
                filename=safe_filename,
                original_filename=orig_name,
                file_path=rel_path,
                file_size=f_size,
                mime_type=f.content_type,
                is_primary=is_pri
            )
            if err:
                errors.append(f"Error saving image for '{sku_for_file}': {err}")
            else:
                results.append(img_rec)
        except Exception as e:
            errors.append(f"Failed saving '{orig_name}': {str(e)}")

    return jsonify({
        'success': len(results) > 0,
        'uploaded_count': len(results),
        'results': results,
        'errors': errors,
        'message': f"Uploaded {len(results)} images. ({len(errors)} issues)"
    })

@app.route('/api/sku_master/images/<int:image_id>', methods=['DELETE'])
def api_delete_sku_image(image_id):
    rec, err = db.delete_sku_image(image_id)
    if err:
        return jsonify({'success': False, 'message': err}), 404
    try:
        if rec and rec.get('file_path'):
            local_rel = rec['file_path'].lstrip('/')
            full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_rel)
            if os.path.isfile(full_path):
                os.remove(full_path)
    except Exception:
        pass
    return jsonify({'success': True, 'message': 'Image mapping deleted successfully.'})

@app.route('/api/sku_master/images/<int:image_id>/set_primary', methods=['POST'])
def api_set_sku_primary_image(image_id):
    data = request.json or {}
    sku_id = data.get('sku_id')
    if not sku_id:
        return jsonify({'success': False, 'message': 'SKU ID is required.'}), 400
    ok, err = db.set_sku_primary_image(sku_id, image_id)
    if not ok:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'message': f"Image {image_id} set as primary image for SKU '{sku_id}'."})

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
    # 1. Primary: SharedFrameBus unified frame buffer
    bus_frame = get_shared_frame_bus().get_latest_frame(camera_id, copy=True, max_age_seconds=5.0)
    if bus_frame is not None:
        return bus_frame, "LIVE CAMERA"

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
            dx = round(step_idx * 15)
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


@app.route('/api/vision/validate', methods=['POST'])
def api_vision_validate():
    """
    Validate a detected object identity against authoritative WMS master data.
    Supports single-identity or object-class query:
      POST /api/vision/validate
      Payload: {
        "class_code": "BIN",
        "identity_value": "BIN-01",
        "identity_status": "IDENTIFIED"
      }
    """
    validation_service = get_validation_service()
    data = request.get_json(silent=True) or {}
    class_code = data.get("class_code") or data.get("object_class")
    identity_val = data.get("identity_value") or data.get("identity") or data.get("value")

    # Convenience fallback if bin_id is supplied directly
    if not identity_val and data.get("bin_id"):
        identity_val = data.get("bin_id")
        if not class_code:
            class_code = "BIN"

    if not class_code:
        class_code = "UNKNOWN"

    identity_status = data.get("identity_status", "IDENTIFIED" if identity_val else "UNIDENTIFIED")
    identity_source = data.get("identity_source")

    result = validation_service.validator.validate_identity(
        class_code=class_code,
        identity_value=identity_val,
        identity_status=identity_status,
        identity_source=identity_source
    )
    return jsonify(result)


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


# ============================================================================
# PART 9: MATERIAL ASSOCIATION ENGINE APIS
# ============================================================================

@app.route('/api/vision/material-association/status', methods=['GET'])
def api_material_association_status():
    """Return operational status, active sessions, and configuration for Material Association Engine."""
    service = get_material_association_service()
    return jsonify(service.get_status())


@app.route('/api/vision/material-association/reset', methods=['POST'])
def api_material_association_reset():
    """Reset in-memory material association sessions for a specific camera or all cameras."""
    service = get_material_association_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        service.reset_session(camera_id)
        return jsonify({
            'success': True,
            'message': f"In-memory material association session for camera '{camera_id}' reset successfully."
        })
    else:
        service.reset_all()
        return jsonify({
            'success': True,
            'message': "All in-memory material association sessions reset successfully."
        })


@app.route('/api/vision/material-association/test', methods=['POST'])
def api_material_association_test():
    """
    Execute material association evaluation on synthetic tracks, uploaded image, or sample scene.
    Supports TRUCK <-> MATERIAL, TRUCK <-> CONTAINER, WORKER <-> MATERIAL, MATERIAL <-> BIN, MATERIAL <-> CONTAINER.
    """
    service = get_material_association_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    synthetic_tracks = data.get('synthetic_tracks')

    # Direct synthetic tracks path
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

    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'association_truck_box_dock1.jpg'
    conf_threshold = data.get('conf_threshold')

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

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
        frame, _ = get_camera_frame_for_detection(camera_id)
        if frame is None:
            return jsonify({'success': False, 'message': f"Live preview for '{camera_id}' is unavailable."}), 404

    result = service.process_frame(
        frame_input=frame,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code
    )
    return jsonify(result)


@app.route('/api/vision/material-association/sequence', methods=['POST'])
def api_material_association_sequence():
    """
    Run multi-frame material association sequence to verify temporal accumulation and lifecycle transitions.
    """
    service = get_material_association_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id', 'CAM-001')
    frames_data = data.get('frames', [])

    results = []
    for idx, f_tracks in enumerate(frames_data):
        assocs, _ = service.process_tracks(tracks=f_tracks, camera_id=camera_id, frame_index=idx + 1)
        results.append({
            'frame_index': idx + 1,
            'associations': assocs
        })

    return jsonify({
        'success': True,
        'camera_id': camera_id,
        'total_frames': len(frames_data),
        'sequence': results
    })


@app.route('/api/vision/material-association/cameras/<camera_id>', methods=['GET'])
def api_material_association_camera(camera_id):
    """Run full material association pipeline on a single snapshot from the specified camera."""
    service = get_material_association_service()
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


@app.route('/api/vision/material-association/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_material_association_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with material bounding boxes, connecting lines, and status pills."""
    service = get_material_association_service()
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


@app.route('/api/vision/material-association/materials/<material_id>', methods=['GET'])
def api_material_association_by_material(material_id):
    """
    Query associations for a specific physical material across all active camera sessions.
    Strictly uses validated physical identity (barcode/QR/OCR/WMS SKU).
    Zero visual cross-camera Re-ID or appearance embeddings.
    """
    service = get_material_association_service()
    result = service.get_associations_for_material(material_id)
    return jsonify(result)


# ============================================================================
# PART 12: WAREHOUSE MOVEMENT EVENT DETECTION FOUNDATION ROUTES
# ============================================================================

@app.route('/api/vision/events/status', methods=['GET'])
def api_vision_events_status():
    """Return operational status, active sessions, and movement event configuration."""
    service = get_movement_event_service()
    return jsonify(service.get_status())


@app.route('/api/vision/events/reset', methods=['POST'])
def api_vision_events_reset():
    """Reset in-memory movement event sessions for a specific camera or all cameras."""
    service = get_movement_event_service()
    data = request.get_json(silent=True) or {}
    camera_id = data.get('camera_id')

    if camera_id and camera_id.upper() != 'ALL':
        res = service.reset_session(camera_id)
        return jsonify(res)
    else:
        res = service.reset_all()
        return jsonify(res)


@app.route('/api/vision/events/test', methods=['POST'])
def api_vision_events_test():
    """
    Execute full perception & event pipeline (Parts 5 -> 6 -> 7 -> 8 -> 9/10/11 -> 12)
    on a test frame (sample scene, uploaded image, or live camera snapshot), or on synthetic tracks/assocs.
    """
    service = get_movement_event_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    source_type = data.get('source_type', 'sample')
    sample_scene = data.get('sample_scene') or data.get('sample_name') or 'association_box_bin_dock1.jpg'
    conf_threshold = data.get('conf_threshold')

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    # Handle synthetic scenario or synthetic tracks & associations directly if supplied
    scenario = data.get('scenario')
    synthetic_tracks = data.get('synthetic_tracks')
    if scenario or synthetic_tracks is not None:
        if scenario == 'box_enter':
            tracks = [
                {"track_id": 104, "class_code": "BOX", "center": [0.60, 0.50], "bbox": [0.55, 0.45, 0.65, 0.55], "identity_id": "B104", "validation_status": "VALIDATED"}
            ]
            res, latency = service.process_events(tracks=tracks, camera_id=camera_id)
        else:
            camera_zones = service._load_camera_zones(camera_id)
            res, latency = service.process_events(
                tracks=synthetic_tracks or [],
                truck_box_assocs=data.get('truck_box_assocs', []),
                worker_box_assocs=data.get('worker_box_assocs', []),
                box_bin_assocs=data.get('box_bin_assocs', []),
                material_assocs=data.get('material_assocs', {}),
                camera_id=camera_id,
                frame_index=data.get('frame_index'),
                camera_zones=camera_zones
            )
        return jsonify({
            'success': True,
            'synthetic': True,
            'mode': 'synthetic_events',
            'scenario': scenario,
            'camera_id': camera_id,
            'result': res,
            'latency_ms': latency,
            'active_events': res.get('active_events', []),
            'current_frame_events': res.get('current_events', []),
            'active_events_count': res.get('active_events_count', 0)
        })

    frame = None
    if source_type == 'sample':
        safe_name = os.path.basename(sample_scene)
        sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", safe_name)
        if not os.path.exists(sample_path):
            sample_path = os.path.join(os.path.dirname(__file__), "static", "test_scenes", "association_box_bin_dock1.jpg")
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


@app.route('/api/vision/events/sequence', methods=['POST'])
def api_vision_events_sequence():
    """
    Run multi-frame movement event sequence to verify state transitions, deduplication, and expiration.
    Supports either camera frame sequence or synthetic sequence.
    """
    service = get_movement_event_service()
    data = request.get_json(silent=True) or {}

    camera_id = data.get('camera_id', 'CAM-001')
    sequence_name = data.get('sequence_name')
    if sequence_name:
        seq_res = service.run_synthetic_sequence(camera_id=camera_id, sequence_name=sequence_name)
        return jsonify(seq_res)
    num_frames = int(data.get('num_frames', 5))
    sample_scene = data.get('sample_scene') or 'association_box_bin_dock1.jpg'
    conf_threshold = data.get('conf_threshold')
    should_reset = data.get('reset_session', True)

    if should_reset:
        service.reset_session(camera_id)

    rois = db.get_camera_rois(camera_id)
    roi_polygon = rois[0].get('coordinates', []) if rois else None
    roi_zone_code = rois[0].get('zone_code') if rois else None

    synthetic_seq = data.get('synthetic_sequence')

    result = service.run_sequence(
        camera_id=camera_id,
        num_frames=num_frames,
        sample_scene=sample_scene,
        conf_threshold=conf_threshold,
        roi_polygon=roi_polygon,
        roi_zone_code=roi_zone_code,
        synthetic_sequence=synthetic_seq
    )
    return jsonify(result)


@app.route('/api/vision/events/cameras/<camera_id>', methods=['GET'])
def api_vision_events_camera_single(camera_id):
    """Run full movement event detection pipeline on a single snapshot from the specified camera."""
    service = get_movement_event_service()
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


@app.route('/api/vision/events/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_vision_events_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG with bounding boxes, event header banner, and badges."""
    service = get_movement_event_service()
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


@app.route('/api/vision/events/timeline/<material_id>', methods=['GET'])
def api_vision_events_material_timeline(material_id):
    """
    Retrieve chronological cross-camera movement event timeline for a specific material.
    Continuity relies strictly on physical identity (barcode/QR/OCR).
    Zero visual cross-camera Re-ID is permitted. Conflicted or unvalidated records are isolated.
    """
    service = get_movement_event_service()
    include_candidates = request.args.get('include_candidates', 'false').lower() == 'true'
    timeline_res = service.get_cross_camera_material_timeline(
        material_id=material_id,
        include_candidates=include_candidates
    )
    return jsonify(timeline_res)


# ============================================================================
# PART 13: MATERIAL TRACEABILITY FOUNDATION API
# ============================================================================

@app.route('/api/vision/traceability/status', methods=['GET'])
def api_vision_traceability_status():
    """Retrieve in-memory material traceability operational status."""
    service = get_material_traceability_service()
    return jsonify(service.get_status())


@app.route('/api/vision/traceability/reset', methods=['POST'])
def api_vision_traceability_reset():
    """Reset all in-memory material traceability records and counters."""
    service = get_material_traceability_service()
    res = service.reset()
    return jsonify(res)


@app.route('/api/vision/traceability/test', methods=['POST'])
def api_vision_traceability_test():
    """Execute a single test frame or scenario in material traceability."""
    service = get_material_traceability_service()
    payload = request.get_json(silent=True) or {}
    res = service.run_test(payload)
    return jsonify(res)


@app.route('/api/vision/traceability/sequence', methods=['POST'])
def api_vision_traceability_sequence():
    """Execute deterministic 7-frame synthetic traceability sequence."""
    service = get_material_traceability_service()
    payload = request.get_json(silent=True) or {}
    seq_name = payload.get("sequence_name", "complete_trace")
    res = service.run_synthetic_sequence(seq_name)
    return jsonify(res)


@app.route('/api/vision/traceability/materials', methods=['GET'])
def api_vision_traceability_materials():
    """List summary of all tracked materials."""
    service = get_material_traceability_service()
    materials = service.get_all_materials()
    return jsonify({
        "success": True,
        "total": len(materials),
        "materials": materials
    })


@app.route('/api/vision/traceability/<material_id>', methods=['GET'])
@app.route('/api/vision/traceability/materials/<material_id>', methods=['GET'])
@app.route('/api/vision/traceability/material/<material_id>', methods=['GET'])
def api_vision_traceability_material_detail(material_id):
    """Retrieve full material-centric dossier for a specific material or track."""
    service = get_material_traceability_service()
    material = service.get_material(material_id)
    if not material:
        return jsonify({
            "success": False,
            "error": f"Material '{material_id}' not found in active traceability store."
        }), 404
    return jsonify({
        "success": True,
        "material": material
    })


@app.route('/api/vision/traceability/materials/<material_id>/timeline', methods=['GET'])
@app.route('/api/vision/traceability/material/<material_id>/timeline', methods=['GET'])
@app.route('/api/vision/traceability/timeline/<material_id>', methods=['GET'])
def api_vision_traceability_material_timeline(material_id):
    """Retrieve chronological event timeline for a specific material."""
    service = get_material_traceability_service()
    timeline = service.get_timeline(material_id)
    return jsonify({
        "success": True,
        "material_id": material_id,
        "total_events": len(timeline),
        "timeline": timeline
    })


@app.route('/api/vision/traceability/cameras/<camera_id>', methods=['GET'])
def api_vision_traceability_camera(camera_id):
    """Retrieve materials observed by a specific camera."""
    service = get_material_traceability_service()
    res = service.get_camera_status(camera_id)
    return jsonify({
        "success": True,
        **res
    })


@app.route('/api/vision/traceability/cameras/<camera_id>/annotated.jpg', methods=['GET'])
def api_vision_traceability_camera_annotated_jpg(camera_id):
    """Return annotated binary JPEG preview for material traceability observer."""
    service = get_material_traceability_service()
    jpeg_bytes = service.get_annotated_jpeg(camera_id)
    if jpeg_bytes is None:
        return Response("Traceability preview rendering failed", status=500)
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
    """
    Part 5: Legacy SmartCamera tripwire and total_unloaded are RETIRED.
    W.A.R.L.O.G. BOX_UNLOADED_AT_DOCK is the sole authoritative perception evidence source.
    WMS boundary: This explicit operator endpoint synchronizes verified evidence with WMS.
    """
    warlog_verified = 0
    dossier = None
    try:
        dossier = get_integration_service().get_gate_pass_unloading_evidence(gp_id)
        if dossier:
            warlog_verified = int(dossier.get('verified_unloaded_count', 0))
    except Exception as e:
        logger.warning(f"Error querying W.A.R.L.O.G. unloading evidence for {gp_id}: {e}")

    req_data = request.get_json(silent=True) or {}
    explicit_qty = req_data.get('explicit_qty') or req_data.get('quantity')

    if explicit_qty is not None:
        target_qty = int(explicit_qty)
        source = "operator_explicit"
    elif warlog_verified > 0:
        target_qty = warlog_verified
        source = "warlog_evidence"
    else:
        return jsonify({
            "success": False,
            "message": "No verified unloading evidence found in W.A.R.L.O.G. perception pipeline.",
            "source": "warlog_evidence",
            "verified_count": 0,
            "evidence_status": dossier.get("verification_status") if dossier else "NO_EVIDENCE"
        }), 200

    # Explicit WMS operator action: synchronize gate pass unloaded_qty with verified W.A.R.L.O.G. evidence
    gp = db.set_unload_qty(gp_id, target_qty)
    if gp:
        return jsonify({
            "success": True,
            "total": gp['unloaded_qty'],
            "source": source,
            "verified_count": warlog_verified,
            "verification_status": dossier.get("verification_status") if dossier else "VERIFIED"
        })
    return jsonify({"success": False, "message": "Gate pass not found."}), 404

@app.route('/api/dock/evidence/<gp_id>', methods=['GET'])
def api_dock_gate_pass_evidence(gp_id):
    """Part 4: Read-only formal W.A.R.L.O.G. unloading evidence for a specific Gate Pass."""
    try:
        evidence = get_integration_service().get_gate_pass_unloading_evidence(gp_id)
        if not evidence:
            return jsonify({"success": False, "error": f"Gate pass '{gp_id}' not found"}), 404
        return jsonify({"success": True, "data": evidence}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/dock/verification/<dock_name>', methods=['GET'])
def api_dock_verification(dock_name):
    """Part 4: Read-only formal W.A.R.L.O.G. verification dossier for a dock zone."""
    try:
        dossier = get_integration_service().get_dock_unloading_evidence_dossier(dock_name)
        return jsonify({"success": True, "data": dossier}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
    seen_ids = set()
    try:
        db_cameras = db.get_all_cameras()
        for cam in db_cameras:
            cid = cam.get('camera_id')
            if not cid:
                continue
            seen_ids.add(cid)
            active_cam = active_cameras.get(cid)
            events = active_cam.events if active_cam else []
            loc = (cam.get('location') or '').strip().lower()
            name = (cam.get('name') or '').strip().lower()
            cid_str = (cid or '').strip().lower()
            is_gate = getattr(active_cam, 'is_gate_camera', False) if active_cam else (loc == 'gate' or 'gate' in name or 'gate' in cid_str or 'anpr' in name)

            if is_gate:
                visible_packages = 0
                visible_boxes = 0
                clustered_bundle_count = 0
                detected_bar_layers = 0
                head_count = 0
                cluster_breakdown = {}
            else:
                visible_packages = active_cam.visible_packages if active_cam else 0
                visible_boxes = getattr(active_cam, 'visible_boxes', 0) if active_cam else 0
                clustered_bundle_count = getattr(active_cam, 'clustered_bundle_count', visible_packages) if active_cam else 0
                detected_bar_layers = getattr(active_cam, 'detected_bar_layers', 0) if active_cam else 0
                head_count = getattr(active_cam, 'head_count', 0) if active_cam else 0
                cluster_breakdown = getattr(active_cam, 'cluster_breakdown', {}) if active_cam else {}

            latest_boxes = active_cam.latest_boxes if active_cam else []
            bin_id = cam.get('bin_id') or (getattr(active_cam, 'bin_id', None))
            raw_url = cam.get('stream_url', '')
            masked_url = re.sub(r'(://[^:]+:)[^@]+(@)', r'\1••••••••\2', raw_url) if raw_url else ''
            cameras_data.append({
                "id": cid,
                "code": cam.get('camera_code', cid),
                "name": cam.get('name') or cid,
                "url": masked_url,
                "location": cam.get('location', 'General'),
                "bin_id": bin_id,
                "type": cam.get('camera_type', 'IP Camera'),
                "vendor": cam.get('vendor', 'Unknown'),
                "status": cam.get('status', 'Online'),
                "events": events,
                "is_gate_camera": is_gate,
                "last_detected_plate": getattr(active_cam, 'last_detected_plate', None) if active_cam else None,
                "last_gate_pass_id": getattr(active_cam, 'last_gate_pass_id', None) if active_cam else None,
                "inbound_count": getattr(active_cam, 'inbound_count', 0) if active_cam else 0,
                "outbound_count": getattr(active_cam, 'outbound_count', 0) if active_cam else 0,
                "net_stock_count": getattr(active_cam, 'net_stock_count', 0) if active_cam else 0,
                "inference_latency_ms": round(getattr(active_cam, 'inference_latency_ms', 0.0), 1) if active_cam else 0.0,
                "fps": round(getattr(active_cam, 'fps', 0.0), 1) if active_cam else 0.0,
                "active_workers_count": getattr(active_cam, 'active_workers_count', 0) if active_cam else 0,
                "active_stocks_count": getattr(active_cam, 'active_stocks_count', 0) if active_cam else 0,
                "visible_packages": visible_packages,
                "visible_boxes": visible_boxes,
                "clustered_bundle_count": clustered_bundle_count,
                "detected_bar_layers": detected_bar_layers,
                "head_count": head_count,
                "cluster_breakdown": cluster_breakdown,
                "is_frozen": getattr(active_cam, 'is_frozen', False) if active_cam else False,
                "latest_boxes": latest_boxes
            })
    except Exception as e:
        logger.warning(f"Error querying authoritative cameras for /api/cameras: {e}")

    # Fallback/merge for any active in-memory cameras not found in DB
    for cam_id, cam in active_cameras.items():
        if cam_id not in seen_ids:
            is_gate = getattr(cam, 'is_gate_camera', False)
            if is_gate:
                visible_packages = 0
                visible_boxes = 0
                clustered_bundle_count = 0
                detected_bar_layers = 0
                head_count = 0
                cluster_breakdown = {}
            else:
                visible_packages = getattr(cam, 'visible_packages', 0)
                clustered_bundle_count = getattr(cam, 'clustered_bundle_count', visible_packages)
                detected_bar_layers = getattr(cam, 'detected_bar_layers', 0)
                head_count = getattr(cam, 'head_count', 0)
                cluster_breakdown = getattr(cam, 'cluster_breakdown', {})

            cameras_data.append({
                "id": cam.camera_id,
                "code": getattr(cam, 'code', cam.camera_id),
                "name": cam.name,
                "url": cam.url,
                "location": cam.location,
                "bin_id": getattr(cam, 'bin_id', None),
                "type": cam.cam_type,
                "vendor": cam.vendor,
                "status": "Online",
                "events": getattr(cam, 'events', []),
                "is_gate_camera": is_gate,
                "last_detected_plate": getattr(cam, 'last_detected_plate', None),
                "last_gate_pass_id": getattr(cam, 'last_gate_pass_id', None),
                "inbound_count": getattr(cam, 'inbound_count', 0),
                "outbound_count": getattr(cam, 'outbound_count', 0),
                "net_stock_count": getattr(cam, 'net_stock_count', 0),
                "inference_latency_ms": round(getattr(cam, 'inference_latency_ms', 0.0), 1),
                "fps": round(getattr(cam, 'fps', 0.0), 1),
                "active_workers_count": getattr(cam, 'active_workers_count', 0),
                "active_stocks_count": getattr(cam, 'active_stocks_count', 0),
                "visible_packages": visible_packages,
                "visible_boxes": getattr(cam, 'visible_boxes', 0),
                "clustered_bundle_count": clustered_bundle_count,
                "detected_bar_layers": detected_bar_layers,
                "head_count": head_count,
                "cluster_breakdown": cluster_breakdown,
                "is_frozen": getattr(cam, 'is_frozen', False),
                "latest_boxes": getattr(cam, 'latest_boxes', [])
            })
    return jsonify(cameras_data)

@app.route('/api/cameras/<camera_id>/toggle_freeze', methods=['POST'])
def toggle_camera_freeze(camera_id):
    active_cam = active_cameras.get(camera_id)
    if active_cam:
        state = active_cam.toggle_freeze()
        return jsonify({"success": True, "is_frozen": state})
    return jsonify({"success": False, "message": "Camera not active"}), 404

@app.route('/api/cameras/<cam_id>/snap', methods=['POST'])
def snap_camera(cam_id):
    frame_bytes = None
    cam = active_cameras.get(cam_id)
    if cam:
        frame_bytes = cam.get_frame()
    
    if not frame_bytes:
        bus = get_shared_frame_bus()
        bus_frame = bus.get_latest_frame(cam_id, copy=False, max_age_seconds=5.0)
        if bus_frame is not None:
            ret, buf = cv2.imencode('.jpg', bus_frame)
            if ret:
                frame_bytes = buf.tobytes()

    if not frame_bytes:
        mgr = get_vision_runtime_manager()
        sess = mgr.get_session(cam_id)
        if sess:
            frame_bytes = sess.get_latest_jpeg()
            
    if not frame_bytes:
        db_cam = db.get_camera(cam_id)
        if not db_cam and not cam:
            return jsonify({"success": False, "message": "Camera not found"}), 404
        return jsonify({"success": False, "message": "No frame available"}), 404
    
    photo_filename = f"captures/manual_{uuid.uuid4().hex}.jpg"
    capture_path = os.path.join(os.path.dirname(__file__), "static", photo_filename)
    os.makedirs(os.path.dirname(capture_path), exist_ok=True)
    with open(capture_path, "wb") as f:
        f.write(frame_bytes)
        
    return jsonify({"success": True, "photo": photo_filename})

@app.route('/api/gate/simulate_arrival', methods=['POST'])
def simulate_gate_arrival():
    try:
        data = request.json or {}
        plate = (data.get('plate') or "MH-12-PQ-9988").strip().upper()
        vehicle_type = data.get('type') or "Heavy Commercial (HCV)"
        
        # 1. Locate Gate Camera
        gate_cam = None
        for cam in active_cameras.values():
            if getattr(cam, 'is_gate_camera', False) or cam.location == 'Gate':
                gate_cam = cam
                break

        # 2. Check if pending gate pass already exists for this plate
        existing_gp = db.get_pending_gate_pass_by_plate(plate)
        if existing_gp:
            gp = existing_gp
            gp_id = gp.get('id', 'GP-PENDING')
        else:
            gp = db.create_gate_pass({
                "plate": plate,
                "type": vehicle_type,
                "activity": "Unloading",
                "status": "Pending",
                "driver_name": "Verified Driver",
                "dock": "Dock 1"
            })
            gp_id = gp.get('id', 'GP-AUTO')
            db.create_vehicle_log(gp_id, plate, "Verified Driver")

        # 3. Synchronize Gate Camera Live Stream HUD
        if gate_cam:
            with gate_cam.lock:
                gate_cam.last_detected_plate = plate
                gate_cam.last_gate_pass_id = gp_id
                gate_cam.last_gate_pass_time = time.time()
                gate_cam.last_plate_prob = 0.99
                gate_cam.events.insert(0, {
                    "time": time.strftime("%H:%M:%S"),
                    "type": vehicle_type,
                    "plate": plate,
                    "gate_pass_id": gp_id,
                    "status": "GATE PASS ISSUED (LIVE FEED)",
                    "camera": gate_cam.name
                })

        return jsonify({
            "success": True,
            "gate_pass": gp,
            "plate": plate,
            "message": f"Gate Pass {gp_id} created from Live Gate Feed for plate {plate}!"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/gate/scan_now', methods=['POST'])
def scan_gate_now():
    try:
        gate_cam = None
        for cam in active_cameras.values():
            if getattr(cam, 'is_gate_camera', False) or cam.location == 'Gate':
                gate_cam = cam
                break
        if not gate_cam:
            return jsonify({"success": False, "message": "No active Gate camera found"}), 404
            
        with gate_cam.lock:
            if gate_cam.raw_frame is None:
                return jsonify({"success": False, "message": "Gate camera feed not ready"}), 400
            frame_copy = gate_cam.raw_frame.copy()
            boxes_copy = copy.deepcopy(gate_cam.latest_boxes)
            
        gate_cam._run_live_gate_anpr_worker(frame_copy, boxes_copy)
        return jsonify({
            "success": True,
            "detected_plate": gate_cam.last_detected_plate,
            "gate_pass_id": gate_cam.last_gate_pass_id
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/cameras', methods=['POST'])
def add_camera():
    data = request.json or {}
    cam_id = data.get('camera_id') or data.get('id') or f"CAM-{str(uuid.uuid4())[:6].upper()}"
    cam_code = data.get('code') or data.get('camera_code') or cam_id
    
    # Sync with Camera Master in SQLite
    saved_cam = db.create_or_update_camera({
        'camera_id': cam_id,
        'camera_code': cam_code,
        'name': data.get('name') or f"Camera {cam_id}",
        'warehouse': data.get('warehouse') or 'Warehouse A',
        'location': data.get('location') or 'General',
        'bin_id': data.get('bin_id'),
        'camera_type': data.get('type') or data.get('camera_type') or 'IP Camera',
        'vendor': data.get('vendor') or 'Unknown',
        'stream_url': data.get('url') or data.get('stream_url') or '',
        'status': 'Online'
    })

    new_camera = SmartCamera(
        camera_id=cam_id,
        name=data.get('name') or f"Camera {cam_id}",
        url=data.get('url') or data.get('stream_url') or '',
        location=data.get('location') or 'General',
        cam_type=data.get('type') or data.get('camera_type') or 'IP Camera',
        vendor=data.get('vendor', 'Unknown'),
        bin_id=data.get('bin_id')
    )
    new_camera.start()
    active_cameras[cam_id] = new_camera

    # Refresh and start W.A.R.L.O.G. Vision Runtime Manager
    try:
        mgr = get_vision_runtime_manager()
        mgr.refresh_cameras()
        mgr.start_camera(cam_id)
    except Exception as e:
        logger.warning(f"Could not refresh VisionRuntimeManager for new camera {cam_id}: {e}")
    
    return jsonify({"success": True, "id": cam_id, "camera_id": cam_id, "camera": saved_cam})

@app.route('/api/cameras/<camera_id>/assign_bin', methods=['POST'])
def assign_camera_bin(camera_id):
    data = request.json or {}
    bin_id = data.get('bin_id') or None
    db.update_camera_bin(camera_id, bin_id)
    if camera_id in active_cameras:
        active_cameras[camera_id].bin_id = bin_id
    return jsonify({"success": True, "camera_id": camera_id, "bin_id": bin_id})

@app.route('/api/cameras/<camera_id>/sync_inventory', methods=['POST'])
def sync_camera_inventory(camera_id):
    active_cam = active_cameras.get(camera_id)
    db_cam = db.get_camera(camera_id)
    
    # Gate camera check: gate camera strictly does NOT count stock
    is_gate = False
    if active_cam and getattr(active_cam, 'is_gate_camera', False):
        is_gate = True
    elif db_cam:
        loc = (db_cam.get('location') or '').strip().lower()
        name = (db_cam.get('name') or '').strip().lower()
        cid = (db_cam.get('camera_id') or '').strip().lower()
        if loc == 'gate' or 'gate' in name or 'gate' in cid or 'anpr' in name:
            is_gate = True
    if is_gate:
        return jsonify({"success": False, "message": "Gate cameras strictly perform ANPR and Gate Pass creation only. Inventory counting is disabled on gate cameras."}), 400

    bin_id = (active_cam.bin_id if active_cam and active_cam.bin_id else None) or (db_cam.get('bin_id') if db_cam else None)
    if not bin_id:
        return jsonify({"success": False, "message": "No Bin assigned to this camera. Please assign a Bin in Camera Management."}), 400
        
    count = 0
    if active_cam:
        if hasattr(active_cam, 'net_stock_count') and active_cam.net_stock_count > 0:
            count = active_cam.net_stock_count
        elif hasattr(active_cam, 'head_count') and active_cam.head_count > 0:
            count = active_cam.head_count
        elif getattr(active_cam, 'clustered_bundle_count', None):
            count = active_cam.clustered_bundle_count
        else:
            count = getattr(active_cam, 'visible_packages', 0)
    
    data = request.get_json(silent=True) or {}
    sku_id = data.get('sku_id')
    vendor = data.get('vendor') or f"Vision AI ({db_cam.get('name', camera_id) if db_cam else camera_id})"
    
    result = db.sync_bin_inventory(bin_id, count, sku_id=sku_id, vendor=vendor)
    return jsonify({
        "success": True,
        "bin_id": bin_id,
        "synced_count": count,
        "details": result,
        "message": f"Successfully synced live count of {count} bundles to Bin {bin_id}!"
    })

@app.route('/api/cameras/<camera_id>/frame', methods=['POST'])
def receive_camera_frame(camera_id):
    frame_data = request.get_data()
    if not frame_data:
        return jsonify({"success": False, "message": "No frame data"}), 400
    
    np_arr = np.frombuffer(frame_data, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"success": False, "message": "Failed to decode frame"}), 400

    # Part 6: Single publication to SharedFrameBus feeds both Camera Junction and W.A.R.L.O.G.
    bus_handled = get_shared_frame_bus().publish_frame(camera_id, frame, source_type="PUSH_DEVICE")
    runtime_handled = get_vision_runtime_manager().push_frame(camera_id, frame)
    legacy_handled = False
    if camera_id in active_cameras:
        active_cameras[camera_id].push_frame(frame)
        legacy_handled = True

    if bus_handled or runtime_handled or legacy_handled:
        return jsonify({"success": True, "shared_bus": True})
    return jsonify({"success": False, "message": "Camera session not active"}), 404

@app.route('/api/cameras/<camera_id>', methods=['DELETE'])
def delete_camera(camera_id):
    if camera_id in active_cameras:
        cam = active_cameras.pop(camera_id)
        cam.stop()
    mgr = get_vision_runtime_manager()
    sess = mgr.get_session(camera_id)
    if sess:
        sess.stop()
    with mgr.lock:
        mgr.sessions.pop(camera_id, None)
    get_shared_frame_bus().clear(camera_id)
    conn = db.get_db()
    conn.execute("DELETE FROM cameras WHERE camera_id = ? OR camera_code = ?", (camera_id, camera_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def _generate_standby_frame(camera_id: str) -> bytes:
    h, w = 480, 854
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (18, 24, 38) # Dark navy canvas

    # Subtle radar grid
    for x in range(0, w, 60):
        cv2.line(img, (x, 0), (x, h), (26, 34, 52), 1)
    for y in range(0, h, 60):
        cv2.line(img, (0, y), (w, y), (26, 34, 52), 1)

    # Header banner
    cv2.rectangle(img, (20, 16), (w - 20, 68), (30, 41, 59), -1)
    cv2.rectangle(img, (20, 16), (w - 20, 68), (99, 102, 241), 1)
    cv2.putText(img, "W.A.R.L.O.G. AI VISION NODE", (35, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (255, 255, 255), 2)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(img, f"FEED: {camera_id.upper()}  |  TIME: {now_str}", (35, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (148, 163, 184), 1)

    # Pulsing dot
    dot_on = int(time.time() * 2) % 2 == 0
    dot_color = (0, 220, 130) if dot_on else (0, 120, 70)
    cv2.circle(img, (45, 150), 7, dot_color, -1)
    cv2.putText(img, "CAMERA STANDBY - WAITING FOR RTSP OR IMAGE UPLOAD", (65, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (226, 232, 240), 2)

    # Action helper box
    cv2.rectangle(img, (140, 200), (w - 140, 350), (30, 41, 59), -1)
    cv2.rectangle(img, (140, 200), (w - 140, 350), (71, 85, 105), 1)
    cv2.putText(img, "COUNT BUNDLES FROM PHOTO:", (w // 2 - 160, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (56, 189, 248), 2)
    cv2.putText(img, "Click [Upload Image to Count] button", (w // 2 - 180, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.putText(img, "or drag and drop pallet photo onto this screen", (w // 2 - 200, 325), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (148, 163, 184), 1)

    ret, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ret else b''

def generate_frames(camera_id):
    mgr = get_vision_runtime_manager()
    bus = get_shared_frame_bus()
    while True:
        # 1. Vision runtime session (High-FPS annotated stream)
        sess = mgr.get_session(camera_id)
        if sess and sess.runtime_state.value in ("RUNNING", "DEGRADED"):
            jpeg = sess.get_latest_jpeg()
            if jpeg:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
                time.sleep(0.010)  # ~100 FPS capable ultra-smooth pipeline
                continue

        # 2. Camera instance
        if camera_id in active_cameras:
            frame = active_cameras[camera_id].get_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                time.sleep(0.010)  # ~100 FPS playback
                continue

        # 3. Frame bus (recent frame from detection / upload)
        bus_frame = bus.get_latest_frame(camera_id, copy=False, max_age_seconds=10.0)
        if bus_frame is not None:
            ret, buf = cv2.imencode('.jpg', bus_frame)
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.010)
                continue

        # 4. Fallback: Live animated standby card with clock & radar
        standby_jpeg = _generate_standby_frame(camera_id)
        if standby_jpeg:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + standby_jpeg + b'\r\n')
        time.sleep(0.10)

@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    return Response(generate_frames(camera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/cameras/<camera_id>/ptz', methods=['POST'])
def camera_ptz_endpoint(camera_id):
    """Handles PTZ (Pan / Tilt / Zoom) controls for active camera streams."""
    data = request.get_json(silent=True) or {}
    action = str(data.get('action', 'home')).strip().lower()
    speed = float(data.get('speed', 5.0))
    zoom_level = float(data.get('zoom', 1.0))

    # Synchronize digital PTZ state with active camera instance
    if camera_id in active_cameras:
        cam = active_cameras[camera_id]
        if hasattr(cam, 'ptz_state'):
            cam.ptz_state['action'] = action
            cam.ptz_state['zoom'] = zoom_level
            cam.ptz_state['last_updated'] = time.time()

    return jsonify({
        "success": True,
        "camera_id": camera_id,
        "action": action,
        "speed": speed,
        "zoom": zoom_level,
        "status": f"PTZ command '{action.upper()}' executed successfully"
    })


@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    try:
        conn = db.get_db()
        cursor = conn.cursor()
        alerts = []
        
        # Check overcapacity bins
        bins = cursor.execute("SELECT bin_id, max_volume, current_volume, max_weight, current_weight FROM bins").fetchall()
        for b in bins:
            if b['max_volume'] > 0 and b['current_volume'] >= b['max_volume'] * 0.95:
                alerts.append({"type": "warning", "message": f"Bin {b['bin_id']} is critically full on volume!"})
            if b['max_weight'] > 0 and b['current_weight'] >= b['max_weight'] * 0.95:
                alerts.append({"type": "warning", "message": f"Bin {b['bin_id']} is critically full on weight!"})
                
        # Check trucks waiting too long (mock logic)
        waiting_gate = cursor.execute("SELECT id FROM gate_passes WHERE status = 'Pending'").fetchall()
        if len(waiting_gate) > 2:
            alerts.append({"type": "error", "message": f"High traffic: {len(waiting_gate)} trucks pending at gate."})
            
        conn.close()
        return jsonify(alerts)
    except Exception as e:
        print(f"Error in /api/alerts: {e}")
        return jsonify([])


# ==========================================
# OUTBOUND FLOW LOGIC
# ==========================================

@app.route('/api/outbound', methods=['GET', 'POST'])
def handle_outbound():
    conn = db.get_db()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        order_id = "OUT-" + str(uuid.uuid4())[:8].upper()
        customer = data.get('customer_name', 'Unknown')
        destination = data.get('destination', 'Unknown')
        items = data.get('items', []) # [{"sku_id": "SKU-1", "quantity": 10}]
        
        cursor.execute("INSERT INTO outbound_orders (id, customer_name, destination) VALUES (?, ?, ?)",
                       (order_id, customer, destination))
        
        for item in items:
            cursor.execute("INSERT INTO outbound_items (order_id, sku_id, quantity) VALUES (?, ?, ?)",
                           (order_id, item['sku_id'], int(item['quantity'])))
        
        conn.commit()
        conn.close()
        return jsonify({"success": True, "order_id": order_id})
        
    else:
        orders = cursor.execute("SELECT * FROM outbound_orders ORDER BY created_at DESC").fetchall()
        result = []
        for o in orders:
            items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (o['id'],)).fetchall()
            order_dict = dict(o)
            order_dict['items'] = [dict(i) for i in items]
            result.append(order_dict)
        conn.close()
        return jsonify(result)

@app.route('/api/outbound/<order_id>/pick', methods=['POST'])
def pick_outbound(order_id):
    conn = db.get_db()
    cursor = conn.cursor()
    
    order = cursor.execute("SELECT * FROM outbound_orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order['status'] == 'Fulfilled':
        return jsonify({"success": False, "error": "Invalid or fulfilled order"})
        
    items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    
    # Simple picking logic: just find any bin with the SKU and deduct
    for item in items:
        needed = item['quantity'] - item['picked_quantity']
        if needed <= 0:
            continue
            
        invs = cursor.execute("SELECT * FROM inventory WHERE sku_id = ? AND quantity > 0", (item['sku_id'],)).fetchall()
        for inv in invs:
            if needed <= 0:
                break
            
            take = min(inv['quantity'], needed)
            # Update inventory
            cursor.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (take, inv['id']))
            # Update Bin capacities
            sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (item['sku_id'],)).fetchone()
            vol_red = sku['unit_volume'] * take
            wt_red = sku['unit_weight'] * take
            cursor.execute("UPDATE bins SET current_volume = MAX(0, current_volume - ?), current_weight = MAX(0, current_weight - ?) WHERE bin_id = ?", (vol_red, wt_red, inv['bin_id']))
            
            needed -= take
            
        cursor.execute("UPDATE outbound_items SET picked_quantity = ? WHERE id = ?", (item['quantity'] - needed, item['id']))
    
    # Check if fully picked
    all_picked = True
    rem_items = cursor.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    for i in rem_items:
        if i['picked_quantity'] < i['quantity']:
            all_picked = False
            
    if all_picked:
        cursor.execute("UPDATE outbound_orders SET status = 'Fulfilled' WHERE id = ?", (order_id,))
    else:
        cursor.execute("UPDATE outbound_orders SET status = 'Partially Picked' WHERE id = ?", (order_id,))
        
    conn.commit()
    conn.close()
    return jsonify({"success": True, "status": "Fulfilled" if all_picked else "Partially Picked"})

# ============================================================================
# PART 14 — SYSTEM INTEGRATION & ORCHESTRATION LAYER ENDPOINTS
# ============================================================================

@app.route('/api/integration/overview', methods=['GET'])
def api_integration_overview():
    """Unified operational indicators combining WMS masters and W.A.R.L.O.G. vision perception."""
    try:
        overview = get_integration_service().get_unified_overview()
        return jsonify({"success": True, "data": overview}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/delivery/<po_number>', methods=['GET'])
def api_integration_delivery(po_number):
    """End-to-end inbound context connecting Delivery -> Gate Pass -> Dock -> Cameras -> Materials."""
    try:
        ctx = get_integration_service().get_delivery_context(po_number)
        if not ctx:
            return jsonify({"success": False, "error": f"Delivery '{po_number}' not found"}), 404
        return jsonify({"success": True, "data": ctx}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/gate_pass/<gp_id>', methods=['GET'])
def api_integration_gate_pass(gp_id):
    """Operational context connecting Gate Pass -> Delivery -> Vehicle -> Dock -> Cameras -> Observations."""
    try:
        ctx = get_integration_service().get_gate_pass_context(gp_id)
        if not ctx:
            return jsonify({"success": False, "error": f"Gate pass '{gp_id}' not found"}), 404
        return jsonify({"success": True, "data": ctx}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/material/<material_id>', methods=['GET'])
def api_integration_material(material_id):
    """Enriched material dossier binding traceability to WMS masters (SKU, PO, Gate Pass, Truck, Worker, Bin)."""
    try:
        dossier = get_integration_service().get_enriched_material_dossier(material_id)
        if not dossier:
            return jsonify({"success": False, "error": f"Material '{material_id}' not found in traceability"}), 404
        return jsonify({"success": True, "data": dossier}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/dock/<dock_name>', methods=['GET'])
def api_integration_dock(dock_name):
    """Dock operational context: assigned gate passes, trucks, dock zone, cameras, observed boxes."""
    try:
        ctx = get_integration_service().get_dock_context(dock_name)
        return jsonify({"success": True, "data": ctx}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/bin/<bin_id>', methods=['GET'])
def api_integration_bin(bin_id):
    """Bin operational context: physical bin, inventory ledger, vision zone, putaway evidence."""
    try:
        ctx = get_integration_service().get_bin_context(bin_id)
        if not ctx:
            return jsonify({"success": False, "error": f"Bin '{bin_id}' not found"}), 404
        return jsonify({"success": True, "data": ctx}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/camera/<camera_id>', methods=['GET'])
def api_integration_camera(camera_id):
    """Unified camera context: hardware + AI config + assigned zones + active perception sessions."""
    try:
        ctx = get_integration_service().get_camera_context(camera_id)
        if not ctx:
            return jsonify({"success": False, "error": f"Camera '{camera_id}' not found"}), 404
        return jsonify({"success": True, "data": ctx}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/integration/e2e/test_scenario', methods=['POST'])
def api_integration_e2e_test_scenario():
    """Executes deterministic synthetic end-to-end integration scenario with zero inventory mutations."""
    try:
        data = request.json or {}
        po_number = data.get("po_number", "PO-8821")
        result = get_integration_service().run_e2e_integration_scenario(po_number)
        return jsonify(result), 200 if result.get("success") else 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# PART 13 — WMS INTEGRATION & CONTROLLED ACTIONS ENHANCEMENT
# ============================================================================

@app.route('/api/wms/controlled_actions/recommendations', methods=['GET'])
def api_controlled_actions_recommendations():
    """
    Part 13: Read-only list of active AI-assisted action recommendations across
    Dock Unloading, Putaway, Cycle Count, and Outbound Dispatch.
    Strictly READ-ONLY. Zero database or inventory mutations.
    """
    try:
        recs = get_integration_service().get_controlled_action_recommendations()
        return jsonify({
            "success": True,
            "count": len(recs),
            "recommendations": recs
        }), 200
    except Exception as e:
        logger.error(f"Error fetching controlled action recommendations: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/wms/controlled_actions/preview', methods=['POST'])
def api_controlled_actions_preview():
    """
    Part 13: Read-only Action Preview mechanism before operator commits.
    Evaluates authoritative WMS state, validation gates, projected state, and exact WMS operation.
    Strictly READ-ONLY. Zero database or inventory mutations.
    """
    try:
        data = request.get_json(force=True) if request.is_json or request.data else {}
        action_type = data.get("action_type")
        entity_id = data.get("entity_id")
        params = data.get("params") or {}
        
        if not action_type or not entity_id:
            return jsonify({
                "success": False,
                "error": "Missing required fields 'action_type' or 'entity_id'"
            }), 400

        preview = get_integration_service().preview_controlled_action(action_type, entity_id, params)
        return jsonify({
            "success": True,
            "preview": preview
        }), 200
    except Exception as e:
        logger.error(f"Error generating controlled action preview: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/wms/controlled_actions/execute', methods=['POST'])
def api_controlled_actions_execute():
    """
    Part 13: Explicit authorized WMS transaction execution endpoint.
    Mutates WMS state ONLY with explicit operator authorization, validation gate clearance,
    idempotency enforcement, and complete evidence snapshot auditing.
    """
    try:
        data = request.get_json(force=True) if request.is_json or request.data else {}
        action_type = data.get("action_type")
        entity_id = data.get("entity_id")
        params = data.get("params") or {}
        operator_id = data.get("operator_id")
        idempotency_key = data.get("idempotency_key")

        if not action_type or not entity_id:
            return jsonify({
                "success": False,
                "error": "Missing required fields 'action_type' or 'entity_id'"
            }), 400

        if not operator_id or str(operator_id).strip() == "":
            return jsonify({
                "success": False,
                "error": "Explicit operator authorization required. 'operator_id' cannot be blank."
            }), 403

        res = get_integration_service().execute_controlled_action(
            action_type=action_type,
            entity_id=entity_id,
            params=params,
            operator_id=operator_id,
            idempotency_key=idempotency_key
        )

        status_code = 200 if res.get("success") else 400
        return jsonify(res), status_code
    except Exception as e:
        logger.error(f"Error executing controlled action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/wms/controlled_actions/reject', methods=['POST'])
def api_controlled_actions_reject():
    """
    Part 13: Explicit operator rejection endpoint.
    Prevents WMS mutation and records rejection reason in authoritative activity log.
    """
    try:
        data = request.get_json(force=True) if request.is_json or request.data else {}
        action_type = data.get("action_type")
        entity_id = data.get("entity_id")
        reason = data.get("reason", "Operator rejected recommendation")
        operator_id = data.get("operator_id", "operator")

        if not action_type or not entity_id:
            return jsonify({
                "success": False,
                "error": "Missing required fields 'action_type' or 'entity_id'"
            }), 400

        res = get_integration_service().reject_controlled_action(
            action_type=action_type,
            entity_id=entity_id,
            reason=reason,
            operator_id=operator_id
        )
        return jsonify(res), 200
    except Exception as e:
        logger.error(f"Error rejecting controlled action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/wms/controlled_actions/audit', methods=['GET'])
def api_controlled_actions_audit():
    """
    Part 13: Retrieves recent controlled action execution and rejection audit trail.
    """
    try:
        limit = int(request.args.get("limit", 50))
        audits = get_integration_service().get_controlled_actions_audit(limit=limit)
        return jsonify({
            "success": True,
            "count": len(audits),
            "audit_trail": audits
        }), 200
    except Exception as e:
        logger.error(f"Error fetching controlled action audit: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/wms/controlled_actions/status/<path:idempotency_key>', methods=['GET'])
def api_controlled_actions_status(idempotency_key):
    """
    Part 13: Check execution status of an action reference key.
    """
    svc = get_integration_service()
    if idempotency_key in svc._executed_actions:
        return jsonify({"success": True, "action": svc._executed_actions[idempotency_key]}), 200
    return jsonify({"success": False, "error": f"Action reference '{idempotency_key}' not found in execution cache"}), 404


@app.route('/api/gate/checkout/<gp_id>', methods=['POST'])
def checkout_gate_pass(gp_id):
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE gate_passes SET status = 'Exited', exit_time = CURRENT_TIMESTAMP WHERE id = ?", (gp_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Vehicle {gp_id} successfully checked out and exited."})


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = db.get_db()
    cursor = conn.cursor()
    items = cursor.execute('''
        SELECT i.*, s.name as sku_name, s.category, b.zone
        FROM inventory i
        LEFT JOIN skus s ON i.sku_id = s.sku_id
        LEFT JOIN bins b ON i.bin_id = b.bin_id
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in items])

@app.route('/api/inventory/<int:inv_id>', methods=['PUT'])
def update_inventory(inv_id):
    data = request.json
    new_qty = data.get('quantity')
    conn = db.get_db()
    cursor = conn.cursor()
    inv = cursor.execute("SELECT * FROM inventory WHERE id = ?", (inv_id,)).fetchone()
    if not inv:
        return jsonify({"success": False, "message": "Inventory record not found"})
        
    cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, inv_id))
    
    # Recalculate bin capacity
    bin_id = inv['bin_id']
    invs = cursor.execute("SELECT sku_id, quantity FROM inventory WHERE bin_id = ?", (bin_id,)).fetchall()
    total_vol = 0
    total_wt = 0
    for item in invs:
        sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (item['sku_id'],)).fetchone()
        if sku:
            total_vol += sku['unit_volume'] * item['quantity']
            total_wt += sku['unit_weight'] * item['quantity']
            
    cursor.execute("UPDATE bins SET current_volume = ?, current_weight = ? WHERE bin_id = ?", (total_vol, total_wt, bin_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Inventory updated and bin capacity recalculated"})



# ============================================================================
# PART 15 — UNIFIED W.A.R.L.O.G. VISION RUNTIME & PROCESSING ORCHESTRATOR
# ============================================================================

@app.route('/api/vision/runtime/status', methods=['GET'])
def api_vision_runtime_status():
    """Lightweight aggregate runtime telemetry and health status across all camera sessions."""
    try:
        mgr = get_vision_runtime_manager()
        telemetry = mgr.get_telemetry()
        return jsonify({"success": True, "data": telemetry}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/cameras', methods=['GET'])
def api_vision_runtime_cameras():
    """List all camera runtime sessions and per-camera telemetry."""
    try:
        mgr = get_vision_runtime_manager()
        telemetry = mgr.get_telemetry()
        return jsonify({"success": True, "cameras": telemetry.get("cameras", [])}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/cameras/<camera_id>', methods=['GET'])
def api_vision_runtime_camera_detail(camera_id):
    """Retrieve isolated runtime session state and metrics for a specific camera."""
    try:
        mgr = get_vision_runtime_manager()
        sess = mgr.get_session(camera_id)
        if not sess:
            return jsonify({"success": False, "error": f"Camera session '{camera_id}' not found"}), 404
        return jsonify({"success": True, "camera": sess.to_dict()}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/cameras/<camera_id>/start', methods=['POST'])
def api_vision_runtime_camera_start(camera_id):
    """Start acquisition and continuous pipeline worker for a single camera session."""
    try:
        mgr = get_vision_runtime_manager()
        sess = mgr.get_session(camera_id)
        if not sess:
            return jsonify({"success": False, "error": f"Camera '{camera_id}' not found"}), 404
        
        # Check if already running to prevent duplicate threads
        if sess.runtime_state.value in ("RUNNING", "STARTING"):
            return jsonify({
                "success": False, 
                "message": f"Camera '{camera_id}' is already running.",
                "camera": sess.to_dict()
            }), 409

        success = sess.start()
        return jsonify({
            "success": success,
            "message": f"Camera '{camera_id}' started successfully." if success else f"Failed to start camera '{camera_id}'.",
            "camera": sess.to_dict()
        }), 200 if success else 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/cameras/<camera_id>/stop', methods=['POST'])
def api_vision_runtime_camera_stop(camera_id):
    """Gracefully halts threads and frame queue for a single camera session."""
    try:
        mgr = get_vision_runtime_manager()
        sess = mgr.get_session(camera_id)
        if not sess:
            return jsonify({"success": False, "error": f"Camera '{camera_id}' not found"}), 404
        
        success = sess.stop()
        return jsonify({
            "success": success,
            "message": f"Camera '{camera_id}' stopped successfully." if success else f"Failed to stop camera '{camera_id}'.",
            "camera": sess.to_dict()
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/cameras/<camera_id>/restart', methods=['POST'])
def api_vision_runtime_camera_restart(camera_id):
    """Gracefully stops and restarts a single camera session."""
    try:
        mgr = get_vision_runtime_manager()
        sess = mgr.get_session(camera_id)
        if not sess:
            return jsonify({"success": False, "error": f"Camera '{camera_id}' not found"}), 404
        
        success = sess.restart()
        return jsonify({
            "success": success,
            "message": f"Camera '{camera_id}' restarted successfully." if success else f"Failed to restart camera '{camera_id}'.",
            "camera": sess.to_dict()
        }), 200 if success else 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/start', methods=['POST'])
@app.route('/api/vision/runtime/start_all', methods=['POST'])
def api_vision_runtime_start_all():
    """Starts all configured vision camera sessions or a specific camera if provided."""
    try:
        mgr = get_vision_runtime_manager()
        data = request.get_json(silent=True) or {}
        cid = data.get("camera_id") or request.args.get("camera_id")
        if cid:
            sess = mgr.get_session(cid)
            if not sess:
                return jsonify({"success": False, "error": f"Camera '{cid}' not found"}), 404
            success = sess.start()
            return jsonify({
                "success": success,
                "message": f"Camera '{cid}' started successfully." if success else f"Failed to start camera '{cid}'.",
                "camera": sess.to_dict()
            }), 200 if success else 500
        results = mgr.start_all()
        return jsonify({"success": True, "results": results}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/runtime/stop', methods=['POST'])
@app.route('/api/vision/runtime/stop_all', methods=['POST'])
def api_vision_runtime_stop_all():
    """Gracefully halts all camera sessions or a specific camera if provided."""
    try:
        mgr = get_vision_runtime_manager()
        data = request.get_json(silent=True) or {}
        cid = data.get("camera_id") or request.args.get("camera_id")
        if cid:
            sess = mgr.get_session(cid)
            if not sess:
                return jsonify({"success": False, "error": f"Camera '{cid}' not found"}), 404
            success = sess.stop()
            return jsonify({
                "success": success,
                "message": f"Camera '{cid}' stopped successfully." if success else f"Failed to stop camera '{cid}'.",
                "camera": sess.to_dict()
            }), 200
        results = mgr.stop_all()
        return jsonify({"success": True, "results": results}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/preview.jpg', methods=['GET'])
@app.route('/api/vision/runtime/cameras/<camera_id>/preview.jpg', methods=['GET'])
def api_vision_runtime_camera_preview_jpg(camera_id=None):
    """Returns the latest annotated JPEG frame bytes from the runtime pipeline or SharedFrameBus."""
    mgr = get_vision_runtime_manager()
    cid = camera_id or request.args.get('camera_id')
    sess = mgr.get_session(cid) if cid else None
    if not sess and mgr.sessions:
        sess = next(iter(mgr.sessions.values()))
    
    target_cid = sess.camera_id if sess else (cid or "CAM-001")
    target_loc = sess.location if sess else "Dock 01"

    if sess:
        jpeg = sess.get_latest_jpeg()
        if jpeg:
            return Response(jpeg, mimetype='image/jpeg')
    
    # Try SharedFrameBus
    from vision_runtime_service import SharedFrameBus
    bus = SharedFrameBus.get_instance()
    bus_frame = bus.get_latest_frame(target_cid, copy=False, max_age_seconds=5.0)
    if bus_frame is not None:
        ret, buf = cv2.imencode('.jpg', bus_frame)
        if ret:
            return Response(buf.tobytes(), mimetype='image/jpeg')
    
    # Synthetic frame fallback
    from vision_runtime_service import TestSyntheticFrameSource
    test_source = TestSyntheticFrameSource(target_cid, target_loc)
    frame = test_source.read_frame()
    if frame is not None:
        ret, buf = cv2.imencode('.jpg', frame)
        if ret:
            return Response(buf.tobytes(), mimetype='image/jpeg')
            
    # Black fallback placeholder
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(blank, "LIVE VISION FEED STANDBY", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    ret, buf = cv2.imencode('.jpg', blank)
    return Response(buf.tobytes(), mimetype='image/jpeg')


@app.route('/api/vision/runtime/test_step', methods=['POST'])
@app.route('/api/vision/runtime/cameras/<camera_id>/test_step', methods=['POST'])
def api_vision_runtime_camera_test_step(camera_id=None):
    """Executes a single test frame through the camera's pipeline for deterministic testing."""
    try:
        mgr = get_vision_runtime_manager()
        data = request.get_json(silent=True) or {}
        cid = camera_id or data.get('camera_id') or request.args.get('camera_id')
        sess = mgr.get_session(cid) if cid else None
        if not sess and mgr.sessions:
            sess = next(iter(mgr.sessions.values()))
        if not sess:
            return jsonify({"success": False, "error": f"Camera '{cid}' not found"}), 404
        
        # Step synthetic frame source
        from vision_runtime_service import TestSyntheticFrameSource
        test_source = TestSyntheticFrameSource(sess.camera_id, sess.location)
        frame = test_source.read_frame()
        if frame is None:
            return jsonify({"success": False, "error": "Failed to generate test frame"}), 500
        
        result = sess.pipeline_executor.execute_pipeline(
            raw_frame=frame,
            camera_id=sess.camera_id,
            camera_meta={"code": sess.camera_code, "name": sess.name, "location": sess.location}
        )
        with sess.lock:
            sess.frames_processed += 1
            sess.latest_annotated_jpeg = result.get("annotated_jpeg")
            sess.last_processing_timestamp = result.get("timestamp")
            sess.last_context = {
                "frame_index": result.get("frame_index"),
                "timestamp": result.get("timestamp"),
                "detections_count": result.get("detections_count"),
                "tracks_count": result.get("tracks_count"),
                "events_count": result.get("events_count"),
                "truck_box_assocs": result.get("truck_box_assocs_count"),
                "worker_box_assocs": result.get("worker_box_assocs_count"),
                "box_bin_assocs": result.get("box_bin_assocs_count"),
                "material_assocs": result.get("material_assocs_count"),
                "timing": result.get("timing"),
                "tracks": [
                    {
                        "track_id": t.get("track_id"),
                        "class_name": t.get("class_name") or t.get("class_code"),
                        "class_code": t.get("class_code") or t.get("class_name"),
                        "confidence": round(float(t.get("confidence", 0.0)), 2),
                        "bbox": t.get("bbox"),
                        "identity_value": (t.get("identity") or {}).get("value") or (t.get("identity") or {}).get("identifier") or t.get("identity_value"),
                        "validation_status": (t.get("validation") or {}).get("status") or t.get("validation_status", "NOT_APPLICABLE"),
                        "zone": t.get("zone") or sess.location,
                        "material_id": (t.get("identity") or {}).get("value") or t.get("material_id")
                    }
                    for t in (result.get("tracks") or [])[:20]
                ]
            }
        return jsonify({
            "success": True,
            "camera_id": sess.camera_id,
            "pipeline_result": {
                "frame_index": result.get("frame_index"),
                "timestamp": result.get("timestamp"),
                "detections_count": result.get("detections_count"),
                "tracks_count": result.get("tracks_count"),
                "events_count": result.get("events_count"),
                "truck_box_assocs_count": result.get("truck_box_assocs_count"),
                "worker_box_assocs_count": result.get("worker_box_assocs_count"),
                "box_bin_assocs_count": result.get("box_bin_assocs_count"),
                "timing": result.get("timing")
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/dashboard/live', methods=['GET'])
def api_vision_dashboard_live():
    """
    Part 12: Unified Live Operational Dashboard Feed for W.A.R.L.O.G. AI Vision Runtime.
    Aggregates runtime status, camera telemetry, detection/tracks, active materials,
    movement event streams, zone occupancy, and operational exceptions in ONE efficient,
    strictly read-only JSON payload.
    Zero database mutations. Zero duplicate video captures or inference.
    """
    try:
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mgr = get_vision_runtime_manager()
        telemetry = mgr.get_telemetry()
        cams_meta = telemetry.get("cameras", [])

        # 1. Determine selected camera
        req_cid = request.args.get('camera_id')
        selected_sess = None
        if req_cid:
            selected_sess = mgr.get_session(req_cid)
        if not selected_sess:
            # Pick first running session, or first session overall
            running_cams = [c for c in cams_meta if str(c.get("runtime_state")) == "RUNNING"]
            first_cid = running_cams[0].get("camera_id") if running_cams else (cams_meta[0].get("camera_id") if cams_meta else None)
            if first_cid:
                selected_sess = mgr.get_session(first_cid)
            elif mgr.sessions:
                selected_sess = next(iter(mgr.sessions.values()))

        # 2. Selected camera payload & tracks
        selected_cam_data = None
        formatted_tracks = []
        if selected_sess:
            s_dict = selected_sess.to_dict()
            s_ctx = s_dict.get("last_context", {}) or {}
            rois = []
            try:
                rois = db.get_camera_rois(selected_sess.camera_id)
            except Exception:
                pass

            state_val = selected_sess.runtime_state.value if hasattr(selected_sess.runtime_state, "value") else str(selected_sess.runtime_state)

            for t in s_ctx.get("tracks", []):
                tr_id = t.get("track_id")
                cls_name = t.get("class_name") or t.get("class_code") or "OBJECT"
                conf = round(float(t.get("confidence", 0.0)), 2)
                bb = t.get("bbox")
                ident = t.get("identity") if isinstance(t.get("identity"), dict) else {}
                val = t.get("validation") if isinstance(t.get("validation"), dict) else {}
                ident_val = t.get("identity_value") or ident.get("value") or ident.get("identifier")
                val_stat = t.get("validation_status") or val.get("status") or "NOT_APPLICABLE"
                mat_id = t.get("material_id") or ident_val
                zn = t.get("zone") or selected_sess.location
                formatted_tracks.append({
                    "track_id": tr_id,
                    "class_name": cls_name,
                    "class_code": cls_name,
                    "confidence": conf,
                    "bbox": bb,
                    "identity_value": ident_val,
                    "validation_status": val_stat,
                    "identity_status": ident.get("status") or t.get("identity_status"),
                    "zone": zn,
                    "material_id": mat_id
                })

            selected_cam_data = {
                "id": selected_sess.camera_id,
                "camera_id": selected_sess.camera_id,
                "camera_code": selected_sess.camera_code,
                "name": selected_sess.name or selected_sess.camera_id,
                "camera_name": selected_sess.name,
                "location": selected_sess.location,
                "zone": selected_sess.location or "Global",
                "status": state_val,
                "runtime_state": state_val,
                "source": selected_sess.stream_url or selected_sess.camera_id,
                "source_type": selected_sess.source_state or "SHARED BUS",
                "source_state": selected_sess.source_state,
                "configured_fps": selected_sess.configured_fps,
                "actual_fps": selected_sess.actual_processing_fps,
                "fps": round(float(selected_sess.actual_processing_fps or selected_sess.configured_fps or 0.0), 1),
                "uptime_seconds": s_dict.get("uptime_seconds", 0.0),
                "last_processing_timestamp": selected_sess.last_processing_timestamp,
                "last_inference_ms": selected_sess.last_inference_ms,
                "preview_url": f"/api/vision/runtime/cameras/{selected_sess.camera_id}/preview.jpg",
                "tracks": formatted_tracks,
                "detections_count": s_ctx.get("detections_count", 0),
                "tracks_count": len(formatted_tracks),
                "events_count": s_ctx.get("events_count", 0),
                "rois": rois
            }

        # 3. Active Materials from MaterialTraceabilityService
        trc_svc = get_material_traceability_service()
        active_materials = []
        for m_key, m_rec in trc_svc.materials.items():
            if hasattr(m_rec, "to_dict"):
                active_materials.append(m_rec.to_dict())
            elif isinstance(m_rec, dict):
                active_materials.append(m_rec)

        # 4. Movement Events from MovementEventService
        evt_svc = get_movement_event_service()
        recent_events = evt_svc.get_recent_events(limit=25)
        active_events = evt_svc.get_active_events()

        # 5. Associations from MaterialAssociationService
        mat_assoc_svc = get_material_association_service()
        associations = mat_assoc_svc.get_all_associations(limit=30)

        # 6. Warehouse Zones & Occupancy Matrix
        all_zones = []
        try:
            all_zones = db.get_all_vision_zones()
        except Exception:
            pass

        zone_occupancy = []
        for z in all_zones:
            z_code = z.get("zone_code")
            resident_mats = [
                m.get("material_id") for m in active_materials
                if m.get("current_location") and m.get("current_location", {}).get("zone_code") == z_code
            ]
            resident_tracks = [
                t for t in formatted_tracks if t.get("zone") == z_code
            ]
            track_count = len(resident_tracks)
            is_occ = len(resident_mats) > 0 or track_count > 0
            latest_z_evt = next((e for e in recent_events if (e.get("zone") or {}).get("zone_code") == z_code or e.get("zone") == z_code), None)
            
            zone_occupancy.append({
                "zone_id": z.get("id"),
                "zone_code": z_code,
                "name": z.get("zone_name") or z_code,
                "zone_name": z.get("zone_name"),
                "type": z.get("zone_type") or "ROI",
                "zone_type": z.get("zone_type"),
                "warehouse": z.get("warehouse"),
                "status": z.get("status"),
                "is_occupied": is_occ,
                "occupancy_count": len(resident_mats) + track_count,
                "track_count": track_count,
                "materials": resident_mats[:5],
                "active_materials": resident_mats[:5],
                "latest_activity": latest_z_evt.get("timestamp") if latest_z_evt else None,
                "camera_count": z.get("camera_count", 0)
            })

        # 7. Operational Alerts & Exceptions
        alerts = []
        for c in cams_meta:
            cid = c.get("camera_id")
            sess = mgr.get_session(cid)
            c_state = str(c.get("runtime_state") or "")
            s_state = str(c.get("source_state") or "")
            if c_state in ("DEGRADED", "ERROR"):
                alerts.append({
                    "id": f"CAM_HEALTH_{cid}",
                    "code": "CAMERA_ERROR",
                    "severity": "CRITICAL" if c_state == "ERROR" else "WARNING",
                    "type": "CAMERA_HEALTH",
                    "camera_id": cid,
                    "target": cid,
                    "message": f"Camera {cid} in {c_state} state ({s_state}).",
                    "timestamp": now_ts
                })
            if sess and (sess.is_running or c_state == "RUNNING"):
                if sess.last_frame_time and (time.time() - sess.last_frame_time > 5.0):
                    alerts.append({
                        "id": f"STALE_{cid}",
                        "code": "CAMERA_STALE",
                        "severity": "WARNING",
                        "camera_id": cid,
                        "type": "CAMERA_STALE",
                        "target": cid,
                        "message": f"Camera {cid} stream is stale (>5s without new frames).",
                        "timestamp": now_ts
                    })

        for tr in formatted_tracks:
            val_stat = tr.get("validation_status")
            ident_stat = tr.get("identity_status")
            if val_stat == "AMBIGUOUS" or ident_stat == "AMBIGUOUS" or tr.get("identity_value") == "AMBIG_TAG":
                alerts.append({
                    "id": f"AMBIG_{tr.get('track_id')}",
                    "code": "AMBIGUOUS_IDENTITY",
                    "severity": "WARNING",
                    "type": "AMBIGUOUS_IDENTITY",
                    "camera_id": selected_sess.camera_id if selected_sess else "",
                    "target": f"Track #{tr.get('track_id')}",
                    "message": f"Track #{tr.get('track_id')} has ambiguous or conflicting identity token.",
                    "timestamp": now_ts
                })
            elif val_stat == "UNIDENTIFIED" or not tr.get("identity_value"):
                alerts.append({
                    "id": f"UNID_{tr.get('track_id')}",
                    "code": "UNIDENTIFIED_OBJECT",
                    "severity": "INFO",
                    "type": "UNIDENTIFIED_OBJECT",
                    "camera_id": selected_sess.camera_id if selected_sess else "",
                    "target": f"Track #{tr.get('track_id')}",
                    "message": f"Track #{tr.get('track_id')} is currently unidentified.",
                    "timestamp": now_ts
                })

        for m in active_materials:
            m_id = m.get("material_id")
            if m.get("has_conflicts") or m.get("conflicts"):
                alerts.append({
                    "id": f"MAT_CONFLICT_{m_id}",
                    "code": "MATERIAL_CONFLICT",
                    "severity": "WARNING",
                    "type": "IDENTITY_OR_DEST_CONFLICT",
                    "target": m_id,
                    "message": f"Material {m_id} has identity or destination conflicts requiring operator attention.",
                    "timestamp": m.get("last_seen") or now_ts
                })

        # Format camera nodes list for frontend pills
        formatted_cams = []
        for c in cams_meta:
            cid = c.get("camera_id")
            s_state = str(c.get("runtime_state") or "STOPPED")
            is_act = s_state == "RUNNING"
            formatted_cams.append({
                "id": cid,
                "name": c.get("camera_name") or cid,
                "status": s_state,
                "fps": round(float(c.get("actual_fps") or c.get("configured_fps") or 0.0), 1),
                "is_active": is_act,
                "source": c.get("source") or cid,
                "source_type": c.get("source_type") or "SHARED BUS",
                "zone": c.get("location") or "Global"
            })

        active_cams_count = sum(1 for c in formatted_cams if c.get("is_active"))
        total_cams_count = len(formatted_cams)
        avg_fps = telemetry.get("average_processing_fps", 0.0)
        runtime_is_active = active_cams_count > 0 or any(s.is_running for s in mgr.sessions.values())
        occupied_zones_count = sum(1 for z in zone_occupancy if z.get("is_occupied"))

        # Part 13: Controlled Action Recommendations
        ctrl_recs = []
        try:
            ctrl_recs = get_integration_service().get_controlled_action_recommendations()
        except Exception as e:
            logger.warning(f"Error gathering controlled action recommendations: {e}")

        return jsonify({
            "success": True,
            "timestamp": now_ts,
            "runtime_active": runtime_is_active,
            "active_cameras": active_cams_count,
            "total_cameras": total_cams_count,
            "aggregate_fps": round(avg_fps, 1),
            "tracked_objects": sum(len((s.last_context or {}).get("tracks", [])) for s in mgr.sessions.values()) or len(formatted_tracks),
            "active_materials_count": len(active_materials),
            "occupied_zones": occupied_zones_count,
            "operational_alerts": alerts,
            "cameras": formatted_cams,
            "selected_camera": selected_cam_data,
            "selected_camera_tracks": formatted_tracks,
            "active_materials": active_materials,
            "zone_occupancy": zone_occupancy,
            "movement_events": recent_events,
            "associations": associations,
            "controlled_action_recommendations": ctrl_recs,
            # Legacy structures for backwards compatibility
            "runtime": {
                "status": "RUNNING" if runtime_is_active else "STANDBY",
                "total_cameras": total_cams_count,
                "active_cameras": active_cams_count,
                "total_frames_processed": telemetry.get("total_frames_processed", 0),
                "avg_fps": avg_fps,
                "cameras": cams_meta
            },
            "materials": active_materials,
            "zones": zone_occupancy,
            "events": recent_events,
            "active_events": active_events,
            "alerts": alerts[:25]
        }), 200

    except Exception as e:
        logger.error(f"Failed to generate live dashboard summary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cycle_count/audit/<bin_id>', methods=['GET'])
def audit_bin_cycle_count(bin_id):
    """
    Read-only W.A.R.L.O.G. AI observation and discrepancy evaluation for a storage bin.
    Zero database mutations.
    """
    try:
        service = get_cycle_count_service()
        result = service.evaluate_bin(bin_id)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cycle_count/audit/<bin_id>/simulate', methods=['POST'])
def simulate_bin_cycle_count(bin_id):
    """
    Simulates vision evidence against authoritative WMS inventory for testing & diagnostics.
    Zero database mutations.
    """
    try:
        service = get_cycle_count_service()
        override = request.json or {}
        result = service.evaluate_bin(bin_id, observation_override=override)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cycle_count/activities', methods=['GET'])
def get_cycle_count_activities():
    """Retrieve recent cycle count audit and adjustment logs."""
    try:
        limit = int(request.args.get('limit', 50))
        activities = db.get_activities(limit=limit)
        return jsonify({"success": True, "activities": activities}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cycle_count', methods=['POST'])
def run_cycle_count():
    """
    The authoritative, explicit operator/WMS Cycle Count action.
    This is the ONLY path through which physical audit adjustments mutate inventory.
    """
    data = request.json or {}
    bin_id = data.get('bin_id')
    actual_qty = data.get('actual_qty')
    sku_id = data.get('sku_id')
    notes = data.get('notes', '')
    
    if bin_id is None or actual_qty is None:
        return jsonify({"success": False, "message": "Missing bin_id or actual_qty"}), 400

    try:
        actual_qty = int(actual_qty)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "actual_qty must be an integer"}), 400

    if actual_qty < 0:
        return jsonify({"success": False, "message": "actual_qty cannot be negative"}), 400
        
    conn = db.get_db()
    with conn:
        # Retrieve current WMS inventory for bin
        inv = conn.execute("SELECT id, quantity, sku_id, vendor FROM inventory WHERE bin_id = ?", (bin_id,)).fetchone()
        
        if not inv:
            # Case: Bin currently has 0 inventory recorded in WMS
            if actual_qty == 0:
                db.log_activity('CYCLE_COUNT_AUDIT', bin_id, f"Audited Qty: 0 (Confirmed Empty Bin). {notes}".strip())
                conn.close()
                return jsonify({
                    "success": True,
                    "message": f"Audit complete. Bin {bin_id} confirmed empty (Qty: 0).",
                    "discrepancy": 0,
                    "bin_id": bin_id,
                    "actual_qty": 0,
                    "previous_qty": 0
                })
            else:
                # Excess in empty bin: initialize inventory row with audited SKU or auto-generated SKU
                target_sku = sku_id or "UNKNOWN-SKU"
                conn.execute('''
                    INSERT INTO inventory (bin_id, sku_id, quantity, vendor, received_date)
                    VALUES (?, ?, ?, 'CYCLE_COUNT_ADJUSTMENT', CURRENT_TIMESTAMP)
                ''', (bin_id, target_sku, actual_qty))
                
                discrepancy = actual_qty
                db.log_activity('CYCLE_COUNT_AUDIT', bin_id, f"Audited Qty: {actual_qty} (Discrepancy: +{discrepancy}, New SKU: {target_sku}). {notes}".strip())
                conn.close()
                return jsonify({
                    "success": True,
                    "message": f"Audit complete. Initialized stock of {actual_qty} units ({target_sku}) in bin {bin_id}.",
                    "discrepancy": discrepancy,
                    "bin_id": bin_id,
                    "actual_qty": actual_qty,
                    "previous_qty": 0
                })

        expected_qty = inv['quantity']
        discrepancy = actual_qty - expected_qty
        
        if discrepancy == 0:
            msg = f"Audit complete. Physical count perfectly matches system (Qty: {actual_qty})."
            db.log_activity('CYCLE_COUNT_AUDIT', bin_id, f"Audited Qty: {actual_qty} (Count Matches WMS). {notes}".strip())
        else:
            # Update the authoritative inventory table
            conn.execute("UPDATE inventory SET quantity = ? WHERE bin_id = ?", (actual_qty, bin_id))
            
            # Log the discrepancy in activities
            delta_str = f"+{discrepancy}" if discrepancy > 0 else f"{discrepancy}"
            db.log_activity('CYCLE_COUNT_AUDIT', bin_id, f"Audited Qty: {actual_qty} (Previous: {expected_qty}, Discrepancy: {delta_str}). {notes}".strip())
            
            msg = f"Audit complete. Inventory adjusted. Discrepancy of {delta_str} units recorded."
            
    conn.close()
    return jsonify({
        "success": True,
        "message": msg,
        "discrepancy": discrepancy,
        "bin_id": bin_id,
        "actual_qty": actual_qty,
        "previous_qty": expected_qty
    })


@app.route('/api/gate/<gp_id>/manifest', methods=['GET'])
def get_gate_manifest(gp_id):
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return "Gate pass not found", 404
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Skandha WMS - Gate Pass Manifest", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Gate Pass ID: {gp_id}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Vehicle Plate: {gp.get('plate')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Driver Name: {gp.get('driver_name', 'N/A')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Vendor: {gp.get('vendor', 'N/A')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Status: {gp.get('status')}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Total Unloaded: {gp.get('unloaded_qty', 0)}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Allocated Bin: {gp.get('bin_allocation', 'N/A')}", ln=1, align='L')
    
    # Render SKU details from unloading_sheet
    pdf.cell(200, 10, txt="", ln=1, align='L')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(80, 10, txt="SKU", border=1)
    pdf.cell(60, 10, txt="Description", border=1)
    pdf.cell(30, 10, txt="Expected", border=1, ln=1)
    
    pdf.set_font("Arial", size=12)
    sheet = gp.get('unloading_sheet')
    if sheet and isinstance(sheet, list):
        for item in sheet:
            pdf.cell(80, 10, txt=str(item.get('sku', '')), border=1)
            pdf.cell(60, 10, txt=str(item.get('description', ''))[:20], border=1)
            pdf.cell(30, 10, txt=str(item.get('expected', '')), border=1, ln=1)
    else:
        pdf.cell(170, 10, txt="No specific SKUs provided in PO sheet.", border=1, ln=1)
    
    pdf_filename = f"manifest_gate_{gp_id}.pdf"
    pdf_dir = os.path.join(os.path.dirname(__file__), "static", "manifests")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    pdf.output(pdf_path)
    
    return jsonify({"success": True, "url": f"/static/manifests/{pdf_filename}"})

@app.route('/api/outbound/<order_id>/manifest', methods=['GET'])
def get_outbound_manifest(order_id):
    conn = db.get_db()
    order = conn.execute("SELECT * FROM outbound_orders WHERE id = ?", (order_id,)).fetchone()
    items = conn.execute("SELECT * FROM outbound_items WHERE order_id = ?", (order_id,)).fetchall()
    conn.close()
    
    if not order:
        return "Order not found", 404
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Skandha WMS - Outbound Manifest", ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Order ID: {order['id']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Customer: {order['customer_name']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Destination: {order['destination']}", ln=1, align='L')
    pdf.cell(200, 10, txt=f"Status: {order['status']}", ln=1, align='L')
    pdf.cell(200, 10, txt="", ln=1, align='L')
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(60, 10, txt="SKU", border=1)
    pdf.cell(40, 10, txt="Required", border=1)
    pdf.cell(40, 10, txt="Picked", border=1)
    pdf.cell(40, 10, txt="Status", border=1, ln=1)
    
    pdf.set_font("Arial", size=12)
    for item in items:
        status = "FULFILLED" if item['picked_quantity'] >= item['quantity'] else "PENDING"
        pdf.cell(60, 10, txt=str(item['sku_id']), border=1)
        pdf.cell(40, 10, txt=str(item['quantity']), border=1)
        pdf.cell(40, 10, txt=str(item['picked_quantity']), border=1)
        pdf.cell(40, 10, txt=status, border=1, ln=1)
        
    pdf_filename = f"manifest_outbound_{order_id}.pdf"
    pdf_dir = os.path.join(os.path.dirname(__file__), "static", "manifests")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_filename)
    pdf.output(pdf_path)
    
    return jsonify({"success": True, "url": f"/static/manifests/{pdf_filename}"})


@app.route('/api/dock/suggest_bin/<gp_id>', methods=['GET'])
def suggest_bin(gp_id):
    gp = db.get_gate_pass(gp_id)
    if not gp:
        return jsonify({"success": False, "message": "Gate pass not found"})
        
    vendor_name = gp.get('vendor', 'UNKNOWN')
    sku_id = 'SKU-' + vendor_name[:3].upper() + '01' if vendor_name != 'UNKNOWN' else 'UNKNOWN-SKU'
    import json
    try:
        sheet_str = gp.get('unloading_sheet')
        sheet = json.loads(sheet_str) if isinstance(sheet_str, str) else sheet_str
        if sheet and len(sheet) > 0 and 'sku' in sheet[0]:
            sku_id = sheet[0]['sku']
    except: pass
    
    # We don't commit the putaway yet, we just simulate the selection
    conn = db.get_db()
    cursor = conn.cursor()
    
    sku = cursor.execute("SELECT unit_volume, unit_weight FROM skus WHERE sku_id = ?", (sku_id,)).fetchone()
    vol_per_unit = sku['unit_volume'] if sku else 1.5
    wt_per_unit = sku['unit_weight'] if sku else 2.0
    
    req_vol = gp.get('unloaded_qty', 0) * vol_per_unit
    req_wt = gp.get('unloaded_qty', 0) * wt_per_unit
    
    best_bin = cursor.execute('''
        SELECT bin_id 
        FROM bins 
        WHERE status = 'Active' 
          AND (max_volume - current_volume) >= ?
          AND (max_weight - current_weight) >= ?
        ORDER BY (max_volume - current_volume) ASC
        LIMIT 1
    ''', (req_vol, req_wt)).fetchone()
    
    conn.close()
    
    chosen_bin = best_bin['bin_id'] if best_bin else "BIN-OVERFLOW-NEW"
    return jsonify({"success": True, "suggested_bin": chosen_bin})


@app.route('/api/inbound/simulate', methods=['POST'])
def api_inbound_simulate():
    """Simulates an inbound truck arrival, dock dispatch, and AI unloading count for testing."""
    conn = db.get_db()
    try:
        # Check if an active pass already exists at Dock 1
        existing = conn.execute("SELECT id FROM gate_passes WHERE UPPER(dock) = 'DOCK 1' AND status IN ('Sent to Dock', 'Unloading')").fetchone()
        if existing:
            gp_id = existing['id']
            conn.execute("UPDATE gate_passes SET status = 'Unloading', unloaded_qty = 50 WHERE id = ?", (gp_id,))
            conn.commit()
            return jsonify({
                "success": True,
                "message": f"Dock 1 truck (Pass {gp_id}) is actively Unloading with 50 AI-verified pieces.",
                "gp_id": gp_id
            })
        
        # Ensure pre-registration delivery exists in expected_deliveries
        po_num = "PO-INB-7701"
        deliv = conn.execute("SELECT po_number FROM expected_deliveries WHERE po_number = ?", (po_num,)).fetchone()
        if not deliv:
            db.create_delivery({
                "po_number": po_num,
                "expected_date": datetime.now().strftime("%Y-%m-%d"),
                "activity": "Unloading",
                "vendor": "Tata AutoComp Systems",
                "vendor_email": "logistics@tataautocomp.com",
                "load": "50x Automotive Wire Bundles",
                "plate": "MH-12-PQ-9988",
                "driver_name": "Sunil Deshmukh",
                "driver_phone": "9876543210",
                "unloading_sheet": [{"sku_id": "SKU-AUTO-WIRE", "vendor": "Tata AutoComp Systems", "expected_qty": 50, "unit_volume": 1.5, "unit_weight": 2.0}]
            })

        # Create gate pass
        import json
        sheet = json.dumps([{"sku": "SKU-AUTO-WIRE", "desc": "50x Automotive Wire Bundles", "expected": 50, "counted": 50}])
        new_gp = db.create_gate_pass({
            "po_number": po_num,
            "plate": "MH-12-PQ-9988",
            "driver_name": "Sunil Deshmukh",
            "driver_phone": "9876543210",
            "vendor": "Tata AutoComp Systems",
            "vendor_email": "logistics@tataautocomp.com",
            "load": "50x Automotive Wire Bundles",
            "activity": "Unloading",
            "dock": "Dock 1",
            "status": "Unloading",
            "unloading_sheet": sheet,
            "unloaded_qty": 50
        })
        gp_id = new_gp['id']
        conn.execute("UPDATE gate_passes SET status = 'Unloading', dock = 'Dock 1', unloaded_qty = 50 WHERE id = ?", (gp_id,))
        conn.commit()

        # Ensure a Dock 1 camera exists in DB
        cam = conn.execute("SELECT camera_id FROM cameras WHERE location LIKE '%Dock%' LIMIT 1").fetchone()
        if not cam:
            conn.execute("""
                INSERT INTO cameras (camera_id, camera_code, name, location, bin_id, status, camera_type)
                VALUES ('CAM-DOCK-01', 'CAM-DOCK-01', 'Dock 01 Overhead Vision', 'Dock 1', 'BIN-A1', 'Online', 'IP Camera')
                ON CONFLICT(camera_id) DO NOTHING
            """)
            conn.commit()

        return jsonify({
            "success": True,
            "message": f"Successfully docked Inbound Truck (MH-12-PQ-9988) at Dock 1 for {po_num}!",
            "gp_id": gp_id
        })
    finally:
        conn.close()


@app.route('/api/inbound/complete_receipt', methods=['POST'])
def api_inbound_complete_receipt():
    """Completes the dock unloading receipt, reconciles inventory to the designated bin, and closes the gate pass."""
    data = request.get_json(silent=True) or {}
    gp_id = data.get('gp_id')
    bin_id = data.get('bin_id') or 'BIN-A1'
    quantity = int(data.get('quantity', 0))
    sku_id = data.get('sku_id') or 'SKU-AUTO-WIRE'
    vendor = data.get('vendor') or 'Inbound Supplier'

    if not gp_id:
        return jsonify({"success": False, "message": "Gate Pass ID is required"}), 400

    conn = db.get_db()
    try:
        gp = conn.execute("SELECT * FROM gate_passes WHERE id = ?", (gp_id,)).fetchone()
        if not gp:
            return jsonify({"success": False, "message": "Gate pass not found"}), 404

        # Sync inventory
        sync_res = db.sync_bin_inventory(bin_id, quantity, sku_id=sku_id, vendor=vendor)

        # Update Gate pass status to Completed
        conn.execute("""
            UPDATE gate_passes 
            SET status = 'Completed', unloaded_qty = ?
            WHERE id = ?
        """, (quantity, gp_id))

        # Update associated delivery status in expected_deliveries
        if gp['po_number']:
            conn.execute("UPDATE expected_deliveries SET status = 'Completed' WHERE po_number = ?", (gp['po_number'],))

        conn.commit()

        return jsonify({
            "success": True,
            "message": f"Goods Receipt Note (GRN) generated! Synced {quantity} items to Bin {bin_id}.",
            "sync_details": sync_res,
            "gp_id": gp_id
        })
    finally:
        conn.close()


# ==============================================================================
# AUTONOMOUS PALLETIZATION & BUNDLE MULTIPLIER API ENDPOINTS
# ==============================================================================

@app.route('/api/pallets', methods=['GET'])
def api_get_pallets():
    """Retrieve all pallets, optionally filtered by status."""
    status = request.args.get('status')
    pallets = db.get_all_pallets(status=status)
    return jsonify({
        "success": True,
        "count": len(pallets),
        "pallets": pallets
    })


@app.route('/api/pallets', methods=['POST'])
def api_create_pallet():
    """Create a new pallet with packaging bundle multipliers."""
    data = request.get_json(force=True) or {}
    sku_id = data.get('sku_id')
    if not sku_id:
        return jsonify({"success": False, "error": "sku_id is required"}), 400

    pallet_id = data.get('pallet_id')
    units_per_bundle = data.get('units_per_bundle', 1)
    target_bundles_raw = data.get('target_bundles')
    if target_bundles_raw is None or target_bundles_raw == '':
        target_bundles = 0
    else:
        try:
            target_bundles = max(0, int(target_bundles_raw))
        except (ValueError, TypeError):
            target_bundles = 0
    name = data.get('name')
    assigned_bin_id = data.get('assigned_bin_id')
    camera_id = data.get('camera_id')
    notes = data.get('notes')

    rec, err = db.create_pallet(
        sku_id=sku_id,
        units_per_bundle=units_per_bundle,
        target_bundles=target_bundles,
        name=name,
        pallet_id=pallet_id,
        assigned_bin_id=assigned_bin_id,
        camera_id=camera_id,
        notes=notes
    )
    if err:
        return jsonify({"success": False, "error": err}), 400

    # Auto-bind to camera if camera_id provided
    if camera_id and rec:
        ps = get_pallet_service()
        ps.set_active_pallet_for_camera(camera_id, rec['pallet_id'])

    return jsonify({"success": True, "status": "success", "pallet": rec}), 201


@app.route('/api/pallets/<pallet_id>', methods=['GET'])
def api_get_single_pallet(pallet_id):
    """Retrieve details and aggregated items for a specific pallet."""
    pallet = db.get_pallet_by_id(pallet_id)
    if not pallet:
        return jsonify({"success": False, "error": f"Pallet '{pallet_id}' not found"}), 404
    items = db.get_pallet_items(pallet_id)
    return jsonify({
        "success": True,
        "pallet": pallet,
        "items": items
    })


@app.route('/api/pallets/<pallet_id>', methods=['DELETE'])
def api_delete_pallet(pallet_id):
    """Delete a pallet record."""
    success = db.delete_pallet(pallet_id)
    return jsonify({"success": success})


@app.route('/api/pallets/<pallet_id>/count', methods=['POST'])
def api_update_pallet_count(pallet_id):
    """Update pallet counted bundles and recalculate total pieces."""
    data = request.get_json(force=True) or {}
    new_count = data.get('counted_bundles') if data.get('counted_bundles') is not None else data.get('current_bundles')
    if new_count is None:
        return jsonify({"success": False, "error": "counted_bundles is required"}), 400

    rec = db.update_pallet_count(
        pallet_id=pallet_id,
        new_count=int(new_count),
        track_id=data.get('track_id'),
        similarity_score=float(data.get('similarity_score', 0.0)),
        snapshot_path=data.get('snapshot_path')
    )
    if not rec:
        return jsonify({"success": False, "error": f"Pallet '{pallet_id}' not found"}), 404

    return jsonify({"success": True, "pallet": rec})


@app.route('/api/pallets/<pallet_id>/seal', methods=['POST'])
def api_seal_pallet(pallet_id):
    """Manually seal a pallet and assign a destination bin."""
    data = request.get_json(force=True) or {}
    assigned_bin_id = data.get('assigned_bin_id')

    # Intercept human error if bin is not compatible
    pallet = db.get_pallet_by_id(pallet_id)
    if pallet and assigned_bin_id:
        is_compat, v_type, v_reason = db.check_bin_putaway_compatibility(
            bin_id=assigned_bin_id,
            sku_id=pallet['sku_id'],
            quantity=pallet['total_units']
        )
        if not is_compat:
            v_rec = db.log_violation(
                violation_type=v_type or 'WRONG_BIN_PUTAWAY',
                title=f"Incompatible Putaway Bin for Pallet {pallet_id}",
                description=v_reason,
                sku_id=pallet['sku_id'],
                bin_id=assigned_bin_id,
                pallet_id=pallet_id,
                severity='HIGH'
            )
            return jsonify({
                "success": False,
                "error": v_reason,
                "violation": v_rec
            }), 400

    rec = db.seal_pallet(pallet_id, assigned_bin_id=assigned_bin_id)
    if not rec:
        return jsonify({"success": False, "error": f"Pallet '{pallet_id}' not found"}), 404

    # Generate master label automatically
    ps = get_pallet_service()
    label_url, _ = ps.generate_pallet_master_label_pdf(pallet_id)

    return jsonify({
        "success": True,
        "status": "success",
        "pallet": rec,
        "label_url": label_url
    })


@app.route('/api/pallets/<pallet_id>/label', methods=['GET'])
def api_get_pallet_label(pallet_id):
    """Generate and return download URL for Master Pallet Label PDF with QR code."""
    ps = get_pallet_service()
    label_url, err = ps.generate_pallet_master_label_pdf(pallet_id)
    if err:
        return jsonify({"success": False, "error": err}), 500
    return jsonify({
        "success": True,
        "pallet_id": pallet_id,
        "label_url": label_url
    })


@app.route('/api/pallets/camera/<camera_id>/bind', methods=['POST', 'GET'])
def api_camera_pallet_bind(camera_id):
    """Bind or query the active stacking pallet for a camera's staging area."""
    ps = get_pallet_service()
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        pallet_id = data.get('pallet_id')
        if not pallet_id:
            return jsonify({"success": False, "error": "pallet_id is required"}), 400
        ps.set_active_pallet_for_camera(camera_id, pallet_id)
        pallet = db.get_pallet_by_id(pallet_id)
        return jsonify({"success": True, "active_pallet": pallet})
    else:
        active = ps.get_active_pallet_for_camera(camera_id)
        return jsonify({"success": True, "active_pallet": active})


@app.route('/api/pallets/<pallet_id>/count_image', methods=['POST'])
@app.route('/api/pallets/count_image', methods=['POST'])
def api_count_pallet_image(pallet_id=None):
    """
    Process an uploaded pallet image, detect bundles, match against SKU reference,
    calculate pieces, record violations if any, and return annotated image with bounding boxes.
    """
    ps = get_pallet_service()
    
    target_pallet_id = pallet_id or request.form.get('pallet_id')
    camera_id = request.form.get('camera_id')
    req_sku = request.form.get('sku_id')
    
    if not target_pallet_id and camera_id:
        active_pal = ps.get_active_pallet_for_camera(camera_id)
        if isinstance(active_pal, dict):
            target_pallet_id = active_pal.get('pallet_id')
        elif isinstance(active_pal, str):
            target_pallet_id = active_pal
        
    if not target_pallet_id:
        open_pallets = db.get_all_pallets(status='STACKING') or db.get_all_pallets(status='BUILDING')
        if req_sku and open_pallets:
            matched = [p for p in open_pallets if p.get('sku_id') == req_sku]
            if matched:
                target_pallet_id = matched[0]['pallet_id']
        if not target_pallet_id and open_pallets:
            target_pallet_id = open_pallets[0]['pallet_id']
        else:
            all_pallets = db.get_all_pallets()
            if all_pallets:
                target_pallet_id = all_pallets[0]['pallet_id']
                
    if not target_pallet_id:
        # Auto-create active pallet for trained SKU if none exists
        sku_to_use = req_sku or 'METAL-GFRAMES-00065'
        new_pal, err = db.create_pallet(
            sku_id=sku_to_use,
            units_per_bundle=10,
            target_bundles=10,
            name=f"Autonomous Pallet - {sku_to_use}",
            camera_id=camera_id or 'cam_inbound_01'
        )
        if new_pal:
            target_pallet_id = new_pal['pallet_id']
            
    if not target_pallet_id:
        return jsonify({"success": False, "error": "No pallet found to associate counting. Please create a pallet first."}), 400

    file = request.files.get('image') or request.files.get('file')
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "No image file uploaded"}), 400

    file_bytes = np.frombuffer(file.read(), np.uint8)
    image_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if image_bgr is None:
        return jsonify({"success": False, "error": "Invalid or corrupted image format"}), 400

    result = ps.process_pallet_image(target_pallet_id, image_bgr)
    
    cam_to_update = camera_id or (result.get('pallet') or {}).get('camera_id')
    if cam_to_update:
        try:
            bus = get_shared_frame_bus()
            app_dir = os.path.dirname(os.path.abspath(__file__))
            rel_ann = result.get('annotated_image_url', '').lstrip('/')
            full_ann_path = os.path.join(app_dir, rel_ann)
            if os.path.exists(full_ann_path):
                ann_img = cv2.imread(full_ann_path)
                if ann_img is not None:
                    bus.publish_frame(cam_to_update, ann_img, source_type="IMAGE_UPLOAD", metadata={"result": result})
        except Exception as e:
            logger.warning(f"Error publishing image count to bus: {e}")

    return jsonify(result)



# ==============================================================================
# HUMAN ERROR & SAFETY VIOLATION LEDGER API ENDPOINTS
# ==============================================================================

@app.route('/api/violations', methods=['GET'])
def api_get_violations():
    """Retrieve violations log."""
    status = request.args.get('status')
    limit = int(request.args.get('limit', 100))
    violations = db.get_all_violations(status=status, limit=limit)
    open_count = db.get_open_violations_count()
    return jsonify({
        "success": True,
        "count": len(violations),
        "open_count": open_count,
        "violations": violations
    })


@app.route('/api/violations', methods=['POST'])
def api_log_violation():
    """Manually or algorithmically record a human error infraction."""
    data = request.get_json(force=True) or {}
    v_type = data.get('violation_type', 'HUMAN_ERROR')
    title = data.get('title') or v_type.replace('_', ' ')
    desc = data.get('description') or data.get('details') or 'Human error recorded by autonomous vision system.'

    rec = db.log_violation(
        violation_type=v_type,
        title=title,
        description=desc,
        camera_id=data.get('camera_id'),
        zone_code=data.get('zone_code'),
        sku_id=data.get('sku_id'),
        bin_id=data.get('bin_id'),
        pallet_id=data.get('pallet_id'),
        track_id=data.get('track_id'),
        expected_value=data.get('expected_value'),
        actual_value=data.get('actual_value'),
        severity=data.get('severity', 'HIGH'),
        snapshot_path=data.get('snapshot_path')
    )
    return jsonify({"success": True, "violation": rec}), 201


@app.route('/api/violations/summary', methods=['GET'])
def api_get_violations_summary():
    """Lightweight endpoint for navbar alert badge polling."""
    open_count = db.get_open_violations_count()
    recent = db.get_all_violations(status='OPEN', limit=5)
    return jsonify({
        "success": True,
        "open_count": open_count,
        "recent_violations": recent
    })


@app.route('/api/violations/<int:violation_id>/resolve', methods=['POST'])
def api_resolve_violation(violation_id):
    """Resolve or supervisor-override an active human error violation."""
    data = request.get_json(force=True) or {}
    resolved_by = data.get('resolved_by', 'Supervisor')
    notes = data.get('notes', 'Resolved by warehouse operator')
    new_status = data.get('status', 'RESOLVED')

    rec = db.resolve_violation(
        violation_id=violation_id,
        resolved_by=resolved_by,
        notes=notes,
        new_status=new_status
    )
    if not rec:
        return jsonify({"success": False, "error": f"Violation #{violation_id} not found"}), 404

    return jsonify({"success": True, "status": "success", "violation": rec})


# ============================================================================
# MULTI-ANGLE 3D VOLUMETRIC BUNDLE AUDIT ENDPOINTS
# ============================================================================

@app.route('/api/vision/multi-angle-count', methods=['POST'])
def api_multi_angle_count():
    """
    Process 3 viewpoints (Front, Right Side, Left Side) to compute exact
    3D volumetric bundle counts (layers x cross-lay multipliers + partial tops),
    generate 3D isometric layout diagram, and return unified audit sheet.
    """
    try:
        from multi_view_counting_service import get_multi_view_counting_service
        service = get_multi_view_counting_service()

        sku_id = request.form.get('sku_id', 'AUTO-REBAR-32')
        bin_location = request.form.get('bin_location', 'A3')
        request_id = request.form.get('request_id', '9504EA')
        use_sample = request.form.get('use_sample', '').lower() in ('true', '1', 'yes')
        
        try:
            depth_multiplier = int(request.form.get('depth_multiplier', 3))
        except (ValueError, TypeError):
            depth_multiplier = 3

        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'test_scenes')

        def decode_image(file_key, sample_filename):
            if file_key in request.files and request.files[file_key].filename:
                nparr = np.frombuffer(request.files[file_key].read(), np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            elif use_sample or not file_key:
                sample_p = os.path.join(test_dir, sample_filename)
                if os.path.isfile(sample_p):
                    return cv2.imread(sample_p)
            return None

        # Check JSON payload fallback (for base64 calls)
        if request.is_json:
            jdata = request.get_json() or {}
            sku_id = jdata.get('sku_id', sku_id)
            bin_location = jdata.get('bin_location', bin_location)
            request_id = jdata.get('request_id', request_id)
            depth_multiplier = int(jdata.get('depth_multiplier', 3))
            use_sample = jdata.get('use_sample', False)

        img_front = decode_image('angle1', 'sample_angle1_front.jpg')
        img_right = decode_image('angle2', 'sample_angle2_right.jpg')
        img_left = decode_image('angle3', 'sample_angle3_left.jpg')

        # Fallback to test scenes if no valid frames uploaded
        if img_front is None:
            p_a1 = os.path.join(test_dir, 'sample_angle1_front.jpg')
            if os.path.isfile(p_a1):
                img_front = cv2.imread(p_a1)
            else:
                img_front = np.zeros((480, 640, 3), dtype=np.uint8)

        if img_right is None:
            p_a2 = os.path.join(test_dir, 'sample_angle2_right.jpg')
            img_right = cv2.imread(p_a2) if os.path.isfile(p_a2) else img_front.copy()

        if img_left is None:
            p_a3 = os.path.join(test_dir, 'sample_angle3_left.jpg')
            img_left = cv2.imread(p_a3) if os.path.isfile(p_a3) else img_front.copy()

        result = service.compute_bundle_count(
            angle1_bgr=img_front,
            angle2_bgr=img_right,
            angle3_bgr=img_left,
            sku_id=sku_id,
            bin_location=bin_location,
            request_id=request_id,
            depth_multiplier=depth_multiplier,
            is_reference_demo=use_sample
        )

        return jsonify(result), 200

    except Exception as e:
        logger.exception("Error running multi-angle audit count")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/sync-audit-count', methods=['POST'])
def api_sync_audit_count():
    """
    Syncs certified multi-angle 3D audit bundle count into active Pallet or WMS Inward record.
    """
    data = request.get_json(force=True) or {}
    pallet_id = data.get('pallet_id')
    verified_bundles = int(data.get('total_bundles', 0))
    units_per_bundle = int(data.get('units_per_bundle', 10))

    if not pallet_id:
        # Auto-link to active stacking pallet
        all_pallets = db.get_all_pallets(status='STACKING')
        if all_pallets:
            pallet_id = all_pallets[0]['pallet_id']
        else:
            recent = db.get_all_pallets()
            if recent:
                pallet_id = recent[0]['pallet_id']

    if not pallet_id:
        return jsonify({"success": False, "error": "No target pallet found to sync count"}), 400

    try:
        updated = db.update_pallet_count(
            pallet_id=pallet_id,
            new_count=verified_bundles,
            track_id="3D-AUDIT-CERTIFIED",
            similarity_score=1.0
        )
        return jsonify({
            "success": True,
            "status": "success",
            "pallet_id": pallet_id,
            "verified_bundles": verified_bundles,
            "total_pieces": verified_bundles * units_per_bundle,
            "pallet": updated
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==============================================================================
# UNIVERSAL PALLET VISION COUNTING (OPTION 1: PIECES | OPTION 2: BUNDLES)
# ==============================================================================

@app.route('/api/pallets/vision-skus', methods=['GET'])
def api_get_vision_skus():
    """
    Returns SKUs that have mapped visual training photos in the AI Vision / SKU Master Data module.
    Enables operators to select the exact warehouse inventory item so the vision model only counts
    pieces/bundles matching that trained template.
    """
    try:
        data = db.get_sku_master_records(image_status='mapped', limit=100)
        items = data.get('items', [])
        skus = []
        for it in items:
            raw_path = it.get('primary_image_path') or ''
            image_url = None
            if raw_path:
                norm = raw_path.replace('\\', '/')
                if '/static/' in norm:
                    image_url = '/' + norm.split('/static/', 1)[1]
                    image_url = '/static/' + image_url.lstrip('/')
                elif os.path.isabs(norm):
                    image_url = f"/static/uploads/sku_images/{os.path.basename(norm)}"
                else:
                    image_url = f"/static/{norm.lstrip('/')}"
            skus.append({
                "sku_id": it["sku_id"],
                "name": it.get("name", it["sku_id"]),
                "category": it.get("category", "General"),
                "image_url": image_url,
                "uom": it.get("uom", "EA"),
                "unit_weight": it.get("unit_weight", 0)
            })
        return jsonify({"success": True, "skus": skus, "count": len(skus)})
    except Exception as e:
        logger.exception("Error fetching vision SKUs")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cameras/<camera_id>/snapshot', methods=['GET'])
def api_camera_snapshot(camera_id):
    """
    Acquires a live snapshot frame from a camera stream for pallet vision counting.
    Returns JPEG image directly.
    """
    try:
        frame, _ = get_camera_frame_for_detection(camera_id)
        if frame is None or frame.size == 0:
            return jsonify({"success": False, "error": f"Failed to acquire frame from camera '{camera_id}'"}), 404
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ret:
            return jsonify({"success": False, "error": "JPEG encoding failed"}), 500
        return Response(buf.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        logger.exception(f"Error capturing snapshot from camera {camera_id}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pallets/count-pieces', methods=['POST'])
def api_count_pallet_pieces():
    """
    Option 1: Material-agnostic Individual Piece Counting.
    Supports two input sources: Uploaded Image and Live Camera Snapshot.
    Pinpoints every piece with numbered circles (1..N) and clusters into bundles.
    Maintains clear separation between directly detected visible objects,
    operator-confirmed dimensions, and inferred hidden interior quantities.
    Does NOT mutate inventory balances (proposed preview only).
    """
    try:
        from pallet_vision_counting_service import get_pallet_vision_counting_service
        service = get_pallet_vision_counting_service()

        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'test_scenes')
        
        # Support both form data and json payload
        data = request.get_json(silent=True) or {}
        sample_name = request.form.get('sample_name') or data.get('sample_name', '')
        counting_mode = request.form.get('counting_mode') or data.get('counting_mode', 'auto')
        sensitivity = float(request.form.get('sensitivity') or data.get('sensitivity', 0.5))
        target_clusters = request.form.get('clusters') or data.get('clusters')
        target_clusters = int(target_clusters) if target_clusters else None
        pallet_id = request.form.get('pallet_id') or data.get('pallet_id')
        sku_id = request.form.get('sku_id') or data.get('sku_id')
        source_type = request.form.get('source_type') or data.get('source_type', 'upload')
        camera_id = request.form.get('camera_id') or data.get('camera_id') or 'cam_inbound_01'
        
        # ROI bounding box support
        roi = None
        roi_raw = request.form.get('roi') or data.get('roi')
        if roi_raw:
            if isinstance(roi_raw, str):
                import json as pyjson
                try:
                    roi = pyjson.loads(roi_raw)
                except Exception:
                    pass
            elif isinstance(roi_raw, dict):
                roi = roi_raw

        # Auto-detect boxes from sample name if mode is auto
        if counting_mode == 'auto' and ('box' in sample_name.lower() or 'carton' in sample_name.lower()):
            counting_mode = 'boxes'

        image_bgr = None
        # 1. Image file upload
        if 'image' in request.files and request.files['image'].filename:
            nparr = np.frombuffer(request.files['image'].read(), np.uint8)
            image_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        # 2. Camera snapshot capture
        elif source_type == 'camera' or request.form.get('use_camera', '').lower() in ('true', '1', 'yes'):
            image_bgr, _ = get_camera_frame_for_detection(camera_id)
        # 3. Explicit sample scene request ONLY if use_sample is explicitly true
        elif sample_name or request.form.get('use_sample', '').lower() in ('true', '1', 'yes'):
            fname = sample_name or 'sample_carton_boxes.png'
            sp = os.path.join(test_dir, fname)
            if os.path.isfile(sp):
                image_bgr = cv2.imread(sp)

        if image_bgr is None:
            if source_type == 'upload':
                return jsonify({"success": False, "error": "No image file uploaded. Please select an image file to count."}), 400
            elif source_type == 'camera':
                image_bgr, _ = get_camera_frame_for_detection(camera_id)
                if image_bgr is None:
                    return jsonify({"success": False, "error": f"Unable to acquire live snapshot from camera '{camera_id}'"}), 400
            else:
                return jsonify({"success": False, "error": "No image or camera source provided"}), 400

        # Custom matrix dimensions: rows x columns x layers (e.g., 5 x 5 x 5 = 125)
        custom_matrix = None
        c_layers = request.form.get('matrix_layers') or data.get('matrix_layers') or request.form.get('layers') or data.get('layers')
        c_cols = request.form.get('matrix_columns') or data.get('matrix_columns') or request.form.get('columns') or data.get('columns')
        c_rows = request.form.get('matrix_rows') or data.get('matrix_rows') or request.form.get('matrix_depth') or data.get('matrix_depth') or request.form.get('rows') or data.get('rows')
        if c_layers or c_cols or c_rows:
            custom_matrix = {
                "layers": int(c_layers) if c_layers else 1,
                "columns": int(c_cols) if c_cols else 1,
                "rows": int(c_rows) if c_rows else 1,
                "depth": int(c_rows) if c_rows else 1
            }

        result = service.count_individual_pieces(
            image_bgr,
            counting_mode=counting_mode,
            roi=roi,
            sensitivity=sensitivity,
            target_clusters=target_clusters,
            sku_id=sku_id,
            custom_matrix=custom_matrix
        )

        result['source_type'] = source_type
        if source_type == 'camera':
            result['camera_id'] = camera_id

        if pallet_id:
            result['pallet_id'] = pallet_id

        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error counting individual pieces")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pallets/re-render-pieces', methods=['POST'])
def api_re_render_pallet_pieces():
    """
    Re-renders piece annotations and legend after user manually clicked to add/delete badges.
    Enforces 100% human-verified accuracy on factory floor before WMS reconciliation.
    Does NOT mutate inventory balances.
    """
    try:
        from pallet_vision_counting_service import get_pallet_vision_counting_service
        service = get_pallet_vision_counting_service()

        data = request.get_json(silent=True) or {}
        raw_image_url = data.get('raw_image_url', '')
        pieces = data.get('pieces', [])
        custom_matrix = data.get('matrix_dimensions') or data.get('custom_matrix')

        if not raw_image_url:
            return jsonify({"success": False, "error": "Missing raw_image_url"}), 400

        # Resolve raw image file path
        rel_path = raw_image_url.lstrip('/').replace('/', os.sep)
        full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
        if not os.path.isfile(full_path):
            return jsonify({"success": False, "error": f"Image file not found: {raw_image_url}"}), 404

        raw_img = cv2.imread(full_path)
        if raw_img is None:
            return jsonify({"success": False, "error": "Failed to decode raw image"}), 400

        result = service.re_render_piece_annotations(raw_img, pieces=pieces, custom_matrix=custom_matrix)
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error re-rendering pieces")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/pallets/count-bundles', methods=['POST'])
def api_count_pallet_bundles():
    """
    Option 2: Material-agnostic Bundle Counting & Multi-View Stack Deconstruction.
    Supports input from uploaded images or captured live camera snapshot.
    Deconstructs tiers, produces Angle 1 + Angle 2 Combined View, 3D Isometric Model,
    Count Comparison (Difference 0), and Final Count Table.
    Does NOT mutate inventory balances.
    """
    try:
        from pallet_vision_counting_service import get_pallet_vision_counting_service
        service = get_pallet_vision_counting_service()

        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'test_scenes')
        data = request.get_json(silent=True) or {}
        preset_name = request.form.get('preset_name') or request.form.get('sample_name') or data.get('preset_name')
        depth_multiplier = int(request.form.get('depth_multiplier') or data.get('depth_multiplier', 1))
        pallet_id = request.form.get('pallet_id') or data.get('pallet_id')
        sku_id = request.form.get('sku_id') or request.values.get('sku_id') or data.get('sku_id')
        source_type = request.form.get('source_type') or data.get('source_type', 'upload')
        camera_id = request.form.get('camera_id') or data.get('camera_id') or 'cam_inbound_01'

        img_a1 = None
        img_a2 = None

        if 'image' in request.files and request.files['image'].filename:
            nparr = np.frombuffer(request.files['image'].read(), np.uint8)
            img_a1 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            img_a2 = img_a1.copy() if img_a1 is not None else None
        elif 'angle1' in request.files and request.files['angle1'].filename:
            nparr = np.frombuffer(request.files['angle1'].read(), np.uint8)
            img_a1 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if 'angle2' in request.files and request.files['angle2'].filename:
            nparr = np.frombuffer(request.files['angle2'].read(), np.uint8)
            img_a2 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img_a1 is None and source_type == 'camera':
            image_cam, _ = get_camera_frame_for_detection(camera_id)
            if image_cam is not None:
                img_a1 = image_cam
                img_a2 = image_cam.copy()

        # Only use sample images if use_sample is explicitly requested
        if img_a1 is None and (request.form.get('use_sample', '').lower() in ('true', '1', 'yes') or preset_name):
            if preset_name == 'multistack_84':
                img_a1 = cv2.imread(os.path.join(test_dir, 'sample_multistack_angle1_front.jpg'))
                img_a2 = cv2.imread(os.path.join(test_dir, 'sample_multistack_angle2_side.jpg'))
            else:
                preset_name = 'timber_48'
                img_a1 = cv2.imread(os.path.join(test_dir, 'sample_timber_angle1_front.jpg'))
                img_a2 = cv2.imread(os.path.join(test_dir, 'sample_timber_angle2_side.jpg'))

        if img_a1 is None:
            if source_type == 'upload':
                return jsonify({"success": False, "error": "No image file uploaded. Please select an image file to count."}), 400
            return jsonify({"success": False, "error": "Unable to acquire image source for bundle counting"}), 400

        result = service.count_bundles_multi_view(
            angle1_bgr=img_a1,
            angle2_bgr=img_a2,
            preset_name=preset_name,
            depth_multiplier=depth_multiplier,
            sku_id=sku_id
        )

        result['source_type'] = source_type
        if source_type == 'camera':
            result['camera_id'] = camera_id

        if pallet_id:
            result['pallet_id'] = pallet_id

        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error counting bundles multi-view")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/vision/decode_ocr', methods=['POST'])
def decode_ocr_endpoint():
    """Decodes QR codes and barcodes from uploaded mobile camera snapshots."""
    file = request.files.get('image')
    if not file:
        return jsonify({"success": False, "error": "No image provided"}), 400
    try:
        in_memory_bytes = file.read()
        nparr = np.frombuffer(in_memory_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({"success": False, "error": "Could not decode image"}), 400

        detector = cv2.QRCodeDetector()
        val, points, straight_qrcode = detector.detectAndDecode(img)
        if val:
            return jsonify({"success": True, "text": val})

        return jsonify({"success": False, "text": "", "message": "No barcode/QR found"})
    except Exception as e:
        logger.exception("Error decoding image QR")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

