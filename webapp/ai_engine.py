import cv2
import threading
import time
import re
from ultralytics import YOLO
import easyocr
import copy

class SmartCamera:
    def __init__(self, camera_id, name, url, location):
        self.camera_id = camera_id
        self.name = name
        self.url = url
        self.location = location
        self.is_running = False
        self.events = []
        
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
        
        # Thread 1: ONLY captures video from the network as fast as possible
        self.capture_thread = threading.Thread(target=self._capture_loop)
        self.capture_thread.daemon = True
        self.capture_thread.start()
        
        # Thread 2: ONLY runs AI in the background, doesn't block video
        self.ai_thread = threading.Thread(target=self._ai_loop)
        self.ai_thread.daemon = True
        self.ai_thread.start()

    def stop(self):
        self.is_running = False

    def _capture_loop(self):
        # This thread just grabs frames from the camera network stream
        cap = cv2.VideoCapture(self.url)
        while self.is_running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                cap = cv2.VideoCapture(self.url)
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
                    continue
                ai_frame = self.raw_frame.copy()
            
            # --- HEAVY AI PROCESSING ---
            results = SmartCamera.vehicle_model(ai_frame, classes=[2, 5, 7], verbose=False)
            new_boxes = []
            
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
                    else:
                        vehicle_type = raw_type.title()
                        
                    new_boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "type": vehicle_type})
                    
                    ocr_counter += 1
                    # Run OCR aggressively for PoC
                    if self.location == "Gate":
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
            
            # Update boxes safely so the video thread can draw them
            with self.lock:
                self.latest_boxes = new_boxes

            time.sleep(0.05) # Prevent AI from hogging 100% CPU

    def get_frame(self):
        # The web server calls this constantly. We just draw boxes on the latest frame!
        with self.lock:
            if self.raw_frame is None:
                return None
            display_frame = self.raw_frame.copy()
            boxes_to_draw = copy.deepcopy(self.latest_boxes)

        # Draw boxes
        for box in boxes_to_draw:
            cv2.rectangle(display_frame, (box['x1'], box['y1']), (box['x2'], box['y2']), (0, 255, 150), 2)
            cv2.putText(display_frame, box['type'], (box['x1'], box['y1'] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 150), 2)
            
        ret, buffer = cv2.imencode('.jpg', display_frame)
        return buffer.tobytes()
