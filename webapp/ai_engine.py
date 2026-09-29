import cv2
import threading
import time
import re
import copy
import numpy as np
from ultralytics import YOLO
import easyocr

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
        self.last_package_count = 0
        self.consecutive_zeros = 0
        
        # Thread-safe frame passing
        self.raw_frame = None
        self.latest_boxes = []
        self.lock = threading.Lock()
        
        if not hasattr(SmartCamera, 'vehicle_model'):
            print("Loading YOLOv8...")
            SmartCamera.vehicle_model = YOLO('yolov8n.pt')
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

    def stop(self):
        self.is_running = False

    def _capture_loop(self):
        # Support integer source for USB webcams (e.g. "0")
        cap_source = self.url
        if isinstance(cap_source, str) and cap_source.strip().isdigit():
            cap_source = int(cap_source.strip())
        cap = cv2.VideoCapture(cap_source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Reduce video lag by minimizing buffer
        while self.is_running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                cap = cv2.VideoCapture(cap_source)
                continue
            
            frame = cv2.resize(frame, (640, 480))
            
            # Save the latest raw frame safely
            with self.lock:
                self.raw_frame = frame
        cap.release()

    def _ai_loop(self):
        # This thread analyzes the latest frame in the background
        ocr_counter = 0
        while self.is_running:
            # Grab a copy of the latest frame safely
            with self.lock:
                if self.raw_frame is None:
                    ai_frame = None
                else:
                    ai_frame = self.raw_frame.copy()
            
            if ai_frame is None:
                time.sleep(0.05)
                continue
            
            # --- HEAVY AI PROCESSING ---
            # Classes: Vehicles (2,5,7), Packages (39=bottle, 41=cup, 47=apple, 64=mouse, 65=remote, 67=cell phone, 73=book)
            results = SmartCamera.vehicle_model(ai_frame, classes=[2, 5, 7, 39, 41, 47, 64, 65, 67, 73], verbose=False)
            new_boxes = []
            package_count = 0
            
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    class_id = int(box.cls[0])
                    raw_type = SmartCamera.vehicle_model.names[class_id]
                    
                    # Normalize YOLO classifications to professional Warehouse types
                    if raw_type in ["bus", "truck"]:
                        vehicle_type = "Heavy Commercial (HCV)"
                    elif raw_type == "car":
                        vehicle_type = "Light Vehicle (LMV)"
                    elif raw_type in ["bottle", "cup", "apple", "mouse", "remote", "cell phone", "book"]:
                        vehicle_type = "Package"
                        package_count += 1
                    else:
                        vehicle_type = raw_type.title()
                        
                    # Color coding: Packages get blue box, Vehicles get green box
                    new_boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "type": vehicle_type})
                    
                    ocr_counter += 1
                    ocr_counter += 1
                    # Run OCR aggressively for PoC, ONLY on vehicles
                    if vehicle_type != "Package" and self.location == "Gate":
                        vehicle_crop = ai_frame[max(0, y1):y2, max(0, x1):x2]
                        if vehicle_crop.size > 0:
                            ocr_results = SmartCamera.ocr_reader.readtext(vehicle_crop)
                            for (_, text, prob) in ocr_results:
                                clean_text = "".join(e for e in text if e.isalnum()).upper()
                                # Relaxed OCR: Let any 4+ character string through to Gate Pass for manual correction
                                if len(clean_text) >= 4 and prob > 0.1:
                                    event = {
                                        "time": time.strftime("%H:%M:%S"),
                                        "type": vehicle_type,
                                        "plate": clean_text,
                                        "camera": self.name
                                    }
                                    self.events.insert(0, event)
                                    self.events = self.events[:10]
                                    break # found a plate, move on
            
            # Edge-triggered automatic counting (debounced)
            if package_count > 0:
                if self.last_package_count == 0:
                    # We transitioned from seeing 0 boxes to >0 boxes!
                    if self.location == "Dock":
                        event = {
                            "time": time.strftime("%H:%M:%S"),
                            "type": "Package_Auto_Count",
                            "count": package_count,
                            "camera": self.name
                        }
                        self.events.insert(0, event)
                        self.events = self.events[:20]
                self.last_package_count = package_count
                self.consecutive_zeros = 0
            else:
                self.consecutive_zeros += 1
                if self.consecutive_zeros > 15: # Increased debounce to 15 frames to prevent flicker double-counting
                    self.last_package_count = 0

            # Update boxes safely so the video thread can draw them
            with self.lock:
                self.latest_boxes = new_boxes
                self.visible_packages = package_count

            time.sleep(0.05) # Prevent AI from hogging 100% CPU

    def get_frame(self):
        # The web server calls this constantly. We just draw boxes on the latest frame!
        with self.lock:
            if self.raw_frame is None:
                # Sleek placeholder frame while stream initiates
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, "Awaiting Camera Feed...", (150, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                ret, buf = cv2.imencode('.jpg', placeholder)
                return buf.tobytes() if ret else None
            display_frame = self.raw_frame.copy()
            boxes_to_draw = copy.deepcopy(self.latest_boxes)

        # Draw boxes
        for box in boxes_to_draw:
            color = (255, 150, 0) if box['type'] == 'Package' else (0, 255, 150)
            cv2.rectangle(display_frame, (box['x1'], box['y1']), (box['x2'], box['y2']), color, 2)
            cv2.putText(display_frame, box['type'], (box['x1'], box['y1'] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
        # Draw Live Count Overlay if Dock Camera
        if self.location == "Dock":
            cv2.putText(display_frame, f"LIVE BOX COUNT: {self.visible_packages}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 150, 0), 3)

        ret, buffer = cv2.imencode('.jpg', display_frame)
        return buffer.tobytes()
