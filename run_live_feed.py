import cv2
import base64
import numpy as np
import sys
import os

# Ensure webapp is in path so we can import the engine
sys.path.append(os.path.join(os.path.dirname(__file__), 'webapp'))

from identity_service import get_identity_service

def run_live_feed():
    print("Starting WARLOG Live Camera Feed...")
    print("Initializing YOLO Model and Engine... this may take a few seconds.")
    
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    
    # Try different indices if 0 doesn't work
    if not cap.isOpened():
        print("Camera 0 not found, trying Camera 1...")
        cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        
    if not cap.isOpened():
        print("Error: Could not open any webcam. Please ensure a camera is connected.")
        return

    # Initialize the identity service (loads YOLO, tracking, OCR, spatial analyzer)
    identity_service = get_identity_service()
    
    print("\n=======================================================")
    print("Webcam opened successfully. WARLOG Vision Engine is ACTIVE.")
    print("Point the camera at objects like BOXES, BUNDLES, or PALLETS.")
    print("Press 'q' in the video window to quit.")
    print("=======================================================\n")
    
    # Set lower resolution for faster processing and enforce 60 FPS hardware limit
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 60)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break
            
        # Process frame through WARLOG Engine
        # YOLO-World zero-shot classes in this build include "box", "bundle", "pallet", etc.
        result = identity_service.process_frame(
            frame_input=frame,
            camera_id="LIVE-CAM-01",
            conf_threshold=0.15,
            enable_barcode_qr=True,
            enable_ocr=True
        )
        
        if result.get("success"):
            b64_str = result.get("annotated_image_url", "").replace("data:image/jpeg;base64,", "")
            if b64_str:
                img_bytes = base64.b64decode(b64_str)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                annotated_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                cv2.imshow("WARLOG Vision - Live Feed", annotated_frame)
            else:
                cv2.imshow("WARLOG Vision - Live Feed", frame)
        else:
            print(f"Processing error: {result.get('error')}")
            cv2.imshow("WARLOG Vision - Live Feed", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Quitting...")
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_live_feed()
