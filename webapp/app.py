from flask import Flask, render_template, Response, request, jsonify
from ai_engine import SmartCamera
import time
import uuid
import cv2
import numpy as np
import os

app = Flask(__name__)

# Store active cameras in memory
active_cameras = {}
# Store gate passes in memory
gate_passes = []
# Expected Deliveries (Pre-registered stock)
expected_deliveries = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/deliveries', methods=['GET', 'POST'])
def handle_deliveries():
    if request.method == 'POST':
        data = request.json
        expected_deliveries.append({
            "po_number": data.get("po_number", f"PO-{len(expected_deliveries)+1000}"),
            "expected_date": data.get("expected_date", time.strftime("%Y-%m-%d")),
            "plate": data.get("plate", "").upper(),
            "driver_name": data.get("driver_name", ""),
            "load": data.get("load", ""),
            "vendor": data.get("vendor", ""),
            "activity": data.get("activity", "Loading")
        })
        return jsonify({"success": True})
    return jsonify(expected_deliveries)

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify({
        "total_expected": len(expected_deliveries),
        "total_arrived": len(gate_passes),
        "pending_dock": len([g for g in gate_passes if g['status'] == 'Pending']),
        "at_dock": len([g for g in gate_passes if g['status'] == 'Sent to Dock'])
    })

@app.route('/api/gate_passes', methods=['GET'])
def get_gate_passes():
    return jsonify(gate_passes)

@app.route('/api/gate_passes', methods=['POST'])
def create_gate_pass():
    data = request.json
    plate = data.get('plate')
    
    # Enforce one truck at the gate at a time.
    # If there is already a Pending gate pass, block new ones until it's processed.
    if any(gp['status'] == 'Pending' for gp in gate_passes):
        return jsonify({"success": False, "message": "Clear pending gate pass first."})
            
    # Auto-fill from expected deliveries if available!
    driver_name = data.get('driver_name', 'Awaiting Input')
    load_info = data.get('load', 'Awaiting Input')
    expected_date = data.get('expected_date', '')
    po_number = data.get('po_number', '')
    vendor = data.get('vendor', 'Unknown')
    activity = data.get('activity', 'Loading')
    photo = data.get('photo', '')
    
    for ed in expected_deliveries:
        if ed['plate'] == plate:
            driver_name = ed.get('driver_name', driver_name)
            load_info = ed.get('load', load_info)
            expected_date = ed.get('expected_date', expected_date)
            po_number = ed.get('po_number', po_number)
            vendor = ed.get('vendor', vendor)
            activity = ed.get('activity', activity)
            break
            
    new_gp = {
        "id": f"GP-{len(gate_passes)+1000}",
        "plate": plate,
        "vehicle_type": data.get('type', 'Unknown'),
        "driver_name": driver_name,
        "load": load_info,
        "vendor": vendor,
        "expected_date": expected_date,
        "po_number": po_number,
        "activity": activity,
        "photo": photo,
        "status": "Pending",
        "dock": "Not Assigned",
        "arrival_date": time.strftime("%Y-%m-%d"),
        "time": time.strftime("%H:%M:%S"),
        "unloaded_qty": 0,
        "bin_allocation": ""
    }
    gate_passes.insert(0, new_gp)
    return jsonify({"success": True, "gate_pass": new_gp})

@app.route('/api/gate_passes/<gp_id>', methods=['PUT', 'DELETE'])
def update_gate_pass(gp_id):
    global gate_passes
    if request.method == 'DELETE':
        gate_passes = [gp for gp in gate_passes if gp['id'] != gp_id]
        return jsonify({"success": True})
        
    data = request.json
    for gp in gate_passes:
        if gp['id'] == gp_id:
            if 'plate' in data: gp['plate'] = data['plate']
            if 'driver_name' in data: gp['driver_name'] = data['driver_name']
            if 'load' in data: gp['load'] = data['load']
            if 'vendor' in data: gp['vendor'] = data['vendor']
            if 'status' in data: gp['status'] = data['status']
            if 'dock' in data: gp['dock'] = data['dock']
            if 'expected_date' in data: gp['expected_date'] = data['expected_date']
            if 'po_number' in data: gp['po_number'] = data['po_number']
            if 'unloaded_qty' in data: gp['unloaded_qty'] = data['unloaded_qty']
            if 'activity' in data: gp['activity'] = data['activity']
            if 'bin_allocation' in data: gp['bin_allocation'] = data['bin_allocation']
            if 'photo' in data: gp['photo'] = data['photo']
            return jsonify({"success": True, "gate_pass": gp})
    return jsonify({"success": False})

@app.route('/api/dock/unload_step/<gp_id>', methods=['POST'])
def unload_step(gp_id):
    # Get total visible packages across all cameras
    visible_packages = 0
    for cam in active_cameras.values():
        visible_packages += cam.visible_packages
        
    if visible_packages == 0:
         return jsonify({"success": False, "message": "No packages detected by AI."})
         
    for gp in gate_passes:
        if gp['id'] == gp_id:
            gp['unloaded_qty'] = gp.get('unloaded_qty', 0) + visible_packages
            return jsonify({"success": True, "added": visible_packages, "total": gp['unloaded_qty']})
    return jsonify({"success": False, "message": "Gate pass not found."})

@app.route('/api/dock/auto_add/<gp_id>', methods=['POST'])
def auto_add_step(gp_id):
    data = request.json
    count = data.get('count', 0)
    for gp in gate_passes:
        if gp['id'] == gp_id:
            gp['unloaded_qty'] = gp.get('unloaded_qty', 0) + count
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
