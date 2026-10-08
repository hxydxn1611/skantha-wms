import cv2
import sys
import os
import base64
import numpy as np

sys.path.append(os.path.join(os.path.dirname(__file__), 'webapp'))
from identity_service import get_identity_service

def test_autonomous():
    # Use the AI generated synthetic test image
    img_path = r"C:\Users\Admin\.gemini\antigravity-ide\brain\b58df6a9-b4f8-4d61-b70f-b109d32b7005\warehouse_pallet_1791453271741.jpg"
    frame = cv2.imread(img_path)
    
    if frame is None:
        print(f"Error: Could not load {img_path}")
        return
        
    print("Processing synthetic test image with WARLOG Engine...")
    service = get_identity_service()
    
    result = service.process_frame(
        frame_input=frame,
        camera_id="AUTO-TEST-01",
        conf_threshold=0.15,
        enable_barcode_qr=True,
        enable_ocr=True
    )
    
    if result.get("success"):
        b64_str = result.get("annotated_image_url", "").replace("data:image/jpeg;base64,", "")
        img_bytes = base64.b64decode(b64_str)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        annotated = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # Save output to brain folder so the AI can embed it in artifact
        out_path = r"C:\Users\Admin\.gemini\antigravity-ide\brain\b58df6a9-b4f8-4d61-b70f-b109d32b7005\warehouse_pallet_annotated.jpg"
        cv2.imwrite(out_path, annotated)
        print(f"Annotated image successfully saved to {out_path}")
        
        print("\n--- DETECTED TRACKS & SPATIAL STATES ---")
        for t in result.get("tracks", []):
            ident = t.get("identity", {})
            status = ident.get("status", "UNIDENTIFIED")
            val = ident.get("value", "")
            
            print(f"- {t.get('class_code')} | State: {t.get('storage_state')} | ID: {val if status == 'IDENTIFIED' else 'None'}")
    else:
        print(f"Error: {result.get('error')}")

if __name__ == "__main__":
    test_autonomous()
