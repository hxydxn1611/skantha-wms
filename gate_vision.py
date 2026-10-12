import os
import sys
import time
import json
import urllib.request
import cv2
from ultralytics import YOLO
import easyocr
import numpy as np

def main():
    print("Loading AI Models... This might take a moment on the first run.")
    
    # 1. Load YOLOv8 for Vehicle Detection (Downloads the small 'nano' model automatically)
    # CO
    #CO dataset classes: 2=car, 3=motorcycle, 5=bus, 7=truck
    try:
        vehicle_model = YOLO('yolo11s.pt') 
    except Exception as e:
        print(f"Error loading YOLO11, falling back to yolov8n: {e}")
        try:
            vehicle_model = YOLO('yolov8n.pt')
        except Exception:
            return

    # 2. Load EasyOCR for reading license plates
    # Using 'en' for English characters
    try:
        ocr_reader = easyocr.Reader(['en'], gpu=False) # Set gpu=True if you have an NVIDIA GPU setup
    except Exception as e:
        print(f"Error loading EasyOCR: {e}")
        return

    print("\nModels loaded successfully!")

    # --- SETUP YOUR IP WEBCAM HERE ---
    # Open your IP Webcam App on your phone and copy the URL. 
    # Usually it looks like http://192.168.x.x:8080/video
    IP_WEBCAM_URL = "http://YOUR_PHONE_IP_HERE:8080/video" 
    
    # NOTE: If you want to test with a local webcam first, change the line below to:
    # cap = cv2.VideoCapture(0)
    print(f"Attempting to connect to video stream at: {IP_WEBCAM_URL}")
    cap = cv2.VideoCapture(IP_WEBCAM_URL)

    if not cap.isOpened():
        print("Error: Could not open video stream. Please check the IP address and make sure the app is running.")
        print("If you want to test with your laptop webcam instead, change IP_WEBCAM_URL to 0.")
        return

    # To keep the video smooth, we won't run heavy OCR on every single frame.
    frame_count = 0
    process_every_n_frames = 15 # Run OCR every 15 frames (~0.5 seconds)
    last_detected_plate = None
    last_gate_pass_id = None
    last_gate_pass_time = 0.0

    print("\nStarting video stream. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame. Stream might have disconnected.")
            break

        frame_count += 1
        
        # Resize frame for faster processing (optional, adjust as needed)
        frame = cv2.resize(frame, (800, 600))

        # --- STEP 1: Detect Vehicles ---
        # Run YOLO on the frame, only looking for cars(2), buses(5), and trucks(7)
        results = vehicle_model(frame, classes=[2, 5, 7], verbose=False)

        for result in results:
            boxes = result.boxes
            for box in boxes:
                # Get bounding box coordinates for the vehicle
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                confidence = float(box.conf[0])
                class_id = int(box.cls[0])
                
                # Get vehicle type name
                vehicle_type = vehicle_model.names[class_id]

                # Draw a box around the vehicle
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                # --- STEP 2: Read License Plate (OCR) ---
                # Only do this occasionally to prevent the video from lagging
                plate_text = ""
                if frame_count % process_every_n_frames == 0:
                    # Crop the image to just the vehicle
                    vehicle_crop = frame[y1:y2, x1:x2]
                    
                    if vehicle_crop.size > 0:
                        # --- ADVANCED OCR PIPELINE ---
                        # 1. Pre-process to increase accuracy
                        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
                        h, w = gray.shape
                        # License plates are generally in the lower half of the vehicle
                        gray_bottom = gray[int(h*0.4):, :]
                        
                        # Enhance contrast and reduce noise using Bilateral Filter
                        gray_bottom = cv2.bilateralFilter(gray_bottom, 11, 17, 17)
                        
                        # Scale up image for EasyOCR which struggles on small text
                        gray_bottom = cv2.resize(gray_bottom, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        
                        # 2. Run OCR on processed image
                        ocr_results = ocr_reader.readtext(gray_bottom)
                        
                        best_plate = ""
                        best_prob = 0
                        parts = []
                        
                        # Filter out garbage OCR results
                        for (bbox, text, prob) in ocr_results:
                            # Basic cleanup: remove spaces and special characters
                            clean_text = "".join(e for e in text if e.isalnum()).upper()
                            
                            if len(clean_text) >= 2 and prob > 0.2:
                                parts.append(clean_text)
                                
                            # Heuristic: plates usually have numbers and letters, length 4-12
                            if 4 <= len(clean_text) <= 12 and prob > 0.2: 
                                has_digit = any(c.isdigit() for c in clean_text)
                                has_alpha = any(c.isalpha() for c in clean_text)
                                if has_digit and has_alpha:
                                    if prob > best_prob:
                                        best_prob = prob
                                        best_plate = clean_text
                                        
                        # Fallback: if split across lines, try combining
                        if best_plate == "" and len(parts) > 0:
                            combined = "".join(parts)
                            if 4 <= len(combined) <= 12:
                                has_digit = any(c.isdigit() for c in combined)
                                has_alpha = any(c.isalpha() for c in combined)
                                if has_digit and has_alpha:
                                    best_plate = combined
                                    best_prob = 0.5 # Estimated fallback confidence
                                    
                        if best_plate != "":
                            plate_text = best_plate
                            now_t = time.time()
                            print(f"[ANPR] Detected {vehicle_type.upper()} with Plate: {plate_text} (Confidence: {best_prob:.2f})")

                            # Automatically create or link Gate Pass in WMS
                            if best_plate != last_detected_plate or (now_t - last_gate_pass_time) > 12.0:
                                try:
                                    payload = json.dumps({
                                        'plate': best_plate,
                                        'type': vehicle_type,
                                        'activity': 'Unloading',
                                        'status': 'Arrived at Gate',
                                        'driver_name': 'Gate Verified Driver',
                                        'dock': 'Dock 1'
                                    }).encode('utf-8')
                                    req = urllib.request.Request(
                                        'http://localhost:5000/api/gate_passes',
                                        data=payload,
                                        headers={'Content-Type': 'application/json'}
                                    )
                                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                                        res_data = json.loads(resp.read().decode('utf-8'))
                                        if res_data.get('success'):
                                            last_gate_pass_id = res_data.get('gate_pass', {}).get('id', 'GP-AUTO')
                                            last_detected_plate = best_plate
                                            last_gate_pass_time = now_t
                                            print(f"[GATE PASS ISSUED] Created: {last_gate_pass_id} (Plate: {best_plate})")
                                except Exception:
                                    # Fallback to local DB if web server is offline
                                    try:
                                        sys.path.append(os.path.join(os.path.dirname(__file__), 'webapp'))
                                        import db
                                        new_gp = db.create_gate_pass({
                                            'plate': best_plate,
                                            'type': vehicle_type,
                                            'activity': 'Unloading',
                                            'status': 'Arrived at Gate'
                                        })
                                        last_gate_pass_id = new_gp.get('id', 'GP-AUTO')
                                        last_detected_plate = best_plate
                                        last_gate_pass_time = now_t
                                        print(f"[LOCAL DB GATE PASS ISSUED] Created: {last_gate_pass_id} (Plate: {best_plate})")
                                    except Exception:
                                        pass
                            break

                # Display the vehicle info on screen
                label = f"{vehicle_type} {plate_text}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 128), 2)
                cv2.putText(frame, label, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 128), 2)

        # Draw Top HUD Banner (Explicitly: ANPR & Gate Pass only, NO stock counting)
        cv2.rectangle(frame, (0, 0), (800, 38), (20, 24, 32), -1)
        cv2.putText(frame, "GATE ACCESS CONTROL | ANPR & GATE PASS CREATION ONLY (ZERO STOCK COUNTING)", (15, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 2)

        # Draw Plate Card in Bottom-Left
        cv2.rectangle(frame, (15, 490), (420, 585), (15, 18, 24), -1)
        cv2.rectangle(frame, (15, 490), (420, 585), (0, 220, 255), 1)

        if last_detected_plate:
            # Realistic License Plate Badge
            cv2.rectangle(frame, (25, 500), (250, 538), (245, 230, 60), -1)
            cv2.rectangle(frame, (25, 500), (250, 538), (10, 10, 10), 2)
            cv2.rectangle(frame, (25, 500), (52, 538), (180, 50, 0), -1)
            cv2.putText(frame, "IND", (27, 524), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
            cv2.putText(frame, last_detected_plate, (60, 528), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (10, 10, 10), 2)

            pass_label = f"GATE PASS: {last_gate_pass_id or 'GENERATING...'}"
            cv2.putText(frame, pass_label, (25, 560), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 128), 2)
            cv2.putText(frame, "STATUS: ARRIVED AT GATE (AUTOMATED)", (25, 576), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1)
        else:
            cv2.putText(frame, "ANPR ENGINE ACTIVE", (25, 524), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 220, 255), 2)
            cv2.putText(frame, "Scanning for vehicles and license plates...", (25, 555), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

        # Show the video window
        cv2.imshow('Smart Gate Camera (ANPR & Access Control)', frame)

        # Press 'q' to quit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
