from flask import Flask, render_template, Response, request, jsonify
from ai_engine import SmartCamera
import time
import uuid

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
            "load": data.get("load", "")
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
    driver_name = 'Awaiting Input'
    load_info = 'Awaiting Input'
    expected_date = ''
    po_number = ''
    for ed in expected_deliveries:
        if ed['plate'] == plate:
            driver_name = ed['driver_name']
            load_info = ed['load']
            expected_date = ed.get('expected_date', '')
            po_number = ed.get('po_number', '')
            break
            
    new_gp = {
        "id": f"GP-{len(gate_passes)+1000}",
        "plate": plate,
        "vehicle_type": data.get('type', 'Unknown'),
        "driver_name": driver_name,
        "load": load_info,
        "expected_date": expected_date,
        "po_number": po_number,
        "status": "Pending",
        "dock": "Not Assigned",
        "arrival_date": time.strftime("%Y-%m-%d"),
        "time": time.strftime("%H:%M:%S")
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
            if 'status' in data: gp['status'] = data['status']
            if 'dock' in data: gp['dock'] = data['dock']
            if 'expected_date' in data: gp['expected_date'] = data['expected_date']
            if 'po_number' in data: gp['po_number'] = data['po_number']
            return jsonify({"success": True, "gate_pass": gp})
    return jsonify({"success": False})

@app.route('/api/cameras', methods=['GET'])
def get_cameras():
    cameras_data = []
    for cam_id, cam in active_cameras.items():
        cameras_data.append({
            "id": cam.camera_id,
            "name": cam.name,
            "url": cam.url,
            "location": cam.location,
            "events": cam.events
        })
    return jsonify(cameras_data)

@app.route('/api/cameras', methods=['POST'])
def add_camera():
    data = request.json
    cam_id = str(uuid.uuid4())[:8]
    
    new_camera = SmartCamera(
        camera_id=cam_id,
        name=data.get('name'),
        url=data.get('url'),
        location=data.get('location')
    )
    new_camera.start()
    active_cameras[cam_id] = new_camera
    
    return jsonify({"success": True, "id": cam_id})

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
