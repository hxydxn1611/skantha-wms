import cv2
import time
import os

def test_rtsp_paths():
    print("--- Trueview Camera Connection Tester ---")
    ip = input("Enter Camera IP Address (e.g. 192.168.1.100): ").strip()
    port = input("Enter RTSP Port (default 554): ").strip() or "554"
    user = input("Enter Username: ").strip()
    pwd = input("Enter Password: ").strip()
    
    # Common RTSP paths for Trueview and related OEM cameras
    paths_to_test = [
        "/stream1",
        "/cam/realmonitor?channel=1&subtype=0",
        "/11",
        "/ch01/0",
        "/live/ch00_0",
        "/video1",
        "/"
    ]
    
    print("\nTesting connections. This may take a moment...")
    
    # Fast timeout settings for OpenCV so it doesn't hang forever
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;2000000"
    
    for path in paths_to_test:
        url = f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
        print(f"Trying path '{path}'...")
        
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f"\n✅ SUCCESS! Connected successfully.")
                print("==================================================")
                print(f"The correct Stream URL is:\n{url}")
                print("==================================================")
                print("Please copy this EXACT URL into the web app.")
                cap.release()
                return
        cap.release()
        
    print("\n❌ Failed to connect using common Trueview paths.")
    print("Please check the following:")
    print("1. Are the IP, Port, Username, and Password 100% correct?")
    print("2. Is your PC on the exact same Wi-Fi network as the camera?")
    print("3. Does the camera have ONVIF or RTSP enabled in its settings?")

if __name__ == "__main__":
    test_rtsp_paths()
