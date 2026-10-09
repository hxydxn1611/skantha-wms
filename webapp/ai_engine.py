import os
import cv2
import threading
import time
import copy
import numpy as np
from ultralytics import YOLO
import easyocr
from identity_service import get_identity_service

class SmartCamera:
    def __init__(self, camera_id, name, url, location, cam_type="IP Camera", vendor="Unknown"):
        self.camera_id = camera_id
        self.name = name
        self.url = url
        self.location = location
        self.cam_type = cam_type
        self.vendor = vendor
        self.is_running = False
        self.events = []
        self.visible_packages = 0
        self.visible_boxes = 0
        self.visible_car_parts = 0
        self.last_package_count = 0
        self.consecutive_zeros = 0
        self.seen_package_ids = set()
        self.total_unloaded = 0
        self.tripwire_y = 240  # Legacy attribute preserved for compatibility
        self.tracked_centroids = {}
        
        # Thread-safe frame passing
        self.raw_frame = None
        self.latest_boxes = []
        self.lock = threading.Lock()
        
        if not hasattr(SmartCamera, 'vehicle_model'):
            print("Loading YOLOv8 (Attempting YOLO-World for Zero-Shot)...")
            try:
                SmartCamera.vehicle_model = YOLO('yolov8s-world.pt')
                SmartCamera.vehicle_model.set_classes([
                    "box", "bundle", "pallet", "car part", "engine block", 
                    "windshield", "bumper", "screw box", "steering wheel", 
                    "tire bundle", "hood", "truck", "forklift", "person", "license plate"
                ])
            except Exception as e:
                print("Falling back to yolov8n.pt due to error:", e)
                SmartCamera.vehicle_model = YOLO('yolov8n.pt')
            if os.environ.get("WARLOG_TEST_MODE") == "1":
                SmartCamera.ocr_reader = None
            else:
                print("Loading EasyOCR...")
                SmartCamera.ocr_reader = easyocr.Reader(['en'], gpu=False)

    def start(self):
        self.is_running = True
        
        # Thread 1: ONLY captures video from network/local device if not client-pushed
        if self.cam_type != "Device Camera":
            self.capture_thread = threading.Thread(target=self._capture_loop)
            self.capture_thread.daemon = True
            self.capture_thread.start()
        
        # Thread 2: ONLY runs AI in the background, doesn't block video
        self.ai_thread = threading.Thread(target=self._ai_loop)
        self.ai_thread.daemon = True
        self.ai_thread.start()

    def push_frame(self, frame):
        """Thread-safe injection of client frames (e.g. from laptop/phone device cameras)."""
        if frame is not None:
            if frame.shape[1] != 640 or frame.shape[0] != 480:
                frame = cv2.resize(frame, (640, 480))
            with self.lock:
                self.raw_frame = frame
            # Part 6: Publish to SharedFrameBus
            try:
                from vision_runtime_service import get_shared_frame_bus
                get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="PUSH_DEVICE")
            except Exception:
                pass

    def stop(self):
        self.is_running = False
        try:
            from vision_runtime_service import get_shared_frame_bus
            get_shared_frame_bus().mark_disconnected(self.camera_id, reason="Camera stopped")
        except Exception:
            pass

    def _capture_loop(self):
        # Support integer source for USB webcams (e.g. "0")
        cap_source = self.url
        is_usb = False
        if isinstance(cap_source, str) and cap_source.strip().isdigit():
            cap_source = int(cap_source.strip())
            is_usb = True
        elif isinstance(cap_source, str) and (cap_source.startswith("rtsp://") or cap_source.startswith("http://")):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;2000000"
            
        if is_usb and os.name == 'nt':
            # Attempt to grab the external USB webcam (index 1) first
            cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(cap_source)
            
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Reduce video lag by minimizing buffer
        while self.is_running:
            read_res = cap.read()
            if not isinstance(read_res, tuple) or len(read_res) != 2:
                time.sleep(1)
                continue
            ret, frame = read_res
            if not ret or frame is None:
                time.sleep(1)
                if is_usb and os.name == 'nt':
                    cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap.release()
                        cap = cv2.VideoCapture(cap_source, cv2.CAP_DSHOW)
                else:
                    cap = cv2.VideoCapture(cap_source)
                continue
            
            frame = cv2.resize(frame, (640, 480))
            
            # Save the latest raw frame safely
            with self.lock:
                self.raw_frame = frame

            # Part 6: Publish to SharedFrameBus
            try:
                from vision_runtime_service import get_shared_frame_bus
                get_shared_frame_bus().publish_frame(self.camera_id, frame, source_type="CAMERA_JUNCTION_CAPTURE")
            except Exception:
                pass
        cap.release()

    def _ai_loop(self):
        ocr_counter = 0
        self.tripwire_y = 240 # Middle of the 480p frame
        self.tracked_centroids = {}
        self.active_audits = {} # { track_id: (x, y) }
        
        while self.is_running:
            with self.lock:
                if self.raw_frame is None:
                    ai_frame = None
                else:
                    ai_frame = self.raw_frame.copy()
            
            if ai_frame is None:
                time.sleep(0.016)
                continue
            
            try:
                results = SmartCamera.vehicle_model.track(ai_frame, persist=True, conf=0.1, iou=0.4, verbose=False)
            except Exception:
                results = SmartCamera.vehicle_model(ai_frame, conf=0.1, iou=0.4, verbose=False)
                
            new_boxes = []
            box_count = 0
            car_part_count = 0
            
            for result in results:
                if result.boxes.id is not None:
                    track_ids = result.boxes.id.int().cpu().tolist()
                else:
                    track_ids = [None] * len(result.boxes)
                    
                for i, box in enumerate(result.boxes):
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    class_id = int(box.cls[0])
                    track_id = track_ids[i]
                    raw_type = SmartCamera.vehicle_model.names[class_id]
                    
                    if raw_type in ["bus", "truck"]:
                        vehicle_type = "Heavy Commercial (HCV)"
                    elif raw_type == "car":
                        vehicle_type = "Light Vehicle (LMV)"

                    # If it's a vehicle at the gate, try OCR occasionally
                    if self.location == 'Gate' and raw_type in ["bus", "truck", "car"]:
                        ocr_counter += 1
                        if ocr_counter % 15 == 0:
                            def run_ocr(frame, cam_id, cam_name, v_type, events):
                                try:
                                    id_svc = get_identity_service()
                                    res = id_svc.process_frame(frame, cam_id)
                                    for track in res.get('tracks', []):
                                        ident = track.get('identity', {})
                                        if ident.get('status') in ['IDENTIFIED', 'UNIDENTIFIED'] and ident.get('source') == 'OCR':
                                            plate_text = ident.get('value')
                                            if plate_text and len(plate_text) >= 4:
                                                if not any(e.get('plate') == plate_text for e in events):
                                                    event = {
                                                        "time": time.strftime("%H:%M:%S"),
                                                        "type": v_type,
                                                        "plate": plate_text,
                                                        "camera": cam_name
                                                    }
                                                    events.insert(0, event)
                                except Exception:
                                    pass
                            
                            threading.Thread(target=run_ocr, args=(ai_frame.copy(), self.camera_id, self.name, vehicle_type, self.events)).start()
                    elif raw_type == "person":
                        vehicle_type = "Worker"
                    elif raw_type in ["suitcase", "backpack", "handbag", "box", "carton", "bundle", "laptop", "book", "tv", "microwave", "oven", "refrigerator"]:
                        vehicle_type = "Box/Bundle"
                        box_count += 1
                    else:
                        vehicle_type = "Car Part"
                        car_part_count += 1
                        
                        # Part 5: Legacy tripwire / SmartCamera package counting is RETIRED.
                        # W.A.R.L.O.G. BOX_UNLOADED_AT_DOCK is the sole authoritative perception source.
                        # Centroids tracked only for visual preview if needed; no unload events or counters mutated.
                        if track_id is not None:
                            cx = int((x1 + x2) / 2)
                            cy = int((y1 + y2) / 2)
                            self.tracked_centroids[track_id] = (cx, cy)
                        
                    label = vehicle_type if track_id is None else f"{vehicle_type} #{track_id}"
                    new_boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "type": label, "is_package": vehicle_type in ["Car Part", "Box/Bundle"], "track_id": track_id})

            with self.lock:
                self.latest_boxes = new_boxes
                self.visible_boxes = box_count
                self.visible_car_parts = car_part_count
                self.visible_packages = box_count + car_part_count

            time.sleep(0.016) # Faster loop for 60 FPS capabilities

    def get_frame(self):
        with self.lock:
            if self.raw_frame is None:
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Awaiting Camera Feed...", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                ret, buf = cv2.imencode('.jpg', placeholder)
                return buf.tobytes() if ret else None
            display_frame = self.raw_frame.copy()
            boxes_to_draw = copy.deepcopy(self.latest_boxes)
            
        # Draw the Virtual Tripwire Line

        for box in boxes_to_draw:
            color = (255, 150, 0) if box.get('is_package') else (0, 255, 150)
            x1, y1, x2, y2 = box['x1'], box['y1'], box['x2'], box['y2']
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, box['type'], (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # Draw centroid point
            if box.get('is_package'):
                cx, cy = int((x1 + x2)/2), int((y1 + y2)/2)
                cv2.circle(display_frame, (cx, cy), 4, (0, 255, 255), -1)

        if self.location == "Dock":
            # High-tech HUD info
            cv2.putText(display_frame, f"BOXES: {self.visible_boxes} | CAR PARTS: {self.visible_car_parts} | W.A.R.L.O.G. ACTIVE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 150), 2)

        ret, buffer = cv2.imencode('.jpg', display_frame)
        return buffer.tobytes()
