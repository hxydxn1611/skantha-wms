import cv2
from ultralytics import YOLO
import easyocr
import numpy as np

def main():
    print("Loading AI Models... This might take a moment on the first run.")
    
    # 1. Load YOLOv8 for Vehicle Detection (Downloads the small 'nano' model automatically)
    # COCO dataset classes: 2=car, 3=motorcycle, 5=bus, 7=truck
    try:
        vehicle_model = YOLO('yolov8n.pt') 
    except Exception as e:
        print(f"Error loading YOLO: {e}")
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
                        # Run OCR on the cropped vehicle image
                        # (In a production system, you'd use a 2nd YOLO model specifically to find the plate first, 
                        # but searching the whole vehicle works for a basic PoC)
                        ocr_results = ocr_reader.readtext(vehicle_crop)
                        
                        # Filter out garbage OCR results (keep strings longer than 4 chars)
                        for (bbox, text, prob) in ocr_results:
                            # Basic cleanup: remove spaces and special characters
                            clean_text = "".join(e for e in text if e.isalnum()).upper()
                            if len(clean_text) > 4 and prob > 0.3: 
                                plate_text = clean_text
                                print(f"Detected {vehicle_type.upper()} with Plate: {plate_text} (Confidence: {prob:.2f})")
                                # Here is where you would send an API request to your iWMS backend!
                                # e.g., requests.post('http://localhost:3000/api/gate-pass', json={'plate': plate_text, 'type': vehicle_type})
                                break

                # Display the info on the screen
                label = f"{vehicle_type} {plate_text}"
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Show the video window
        cv2.imshow('Smart Gate Camera (PoC)', frame)

        # Press 'q' to quit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
