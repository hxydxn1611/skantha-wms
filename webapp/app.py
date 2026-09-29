from flask import Flask, render_template, Response, request, jsonify
from ai_engine import SmartCamera
import time
import uuid
import cv2
import numpy as np
import os

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
            
    # Auto-matches against pre-registered deliveries (by plate or po_number)
    # and connects both collections inside db.create_gate_pass
    new_gp = db.create_gate_pass(data)
    return jsonify({"success": True, "gate_pass": new_gp})

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
    gp = db.update_gate_pass(gp_id, data)
    if gp:
        return jsonify({"success": True, "gate_pass": gp})
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
