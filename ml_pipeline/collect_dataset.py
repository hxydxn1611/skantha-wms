import cv2
import os
import time
import argparse

def collect_data(source=0, output_dir="images/train", interval=1.0, max_frames=50):
    """
    Collects frames from a webcam or video file at a set interval.
    Useful for rapidly building a dataset for WARLOG.
    """
    # Create the necessary directories for the YOLO dataset structure
    os.makedirs(output_dir, exist_ok=True)
    labels_dir = output_dir.replace('images', 'labels')
    os.makedirs(labels_dir, exist_ok=True)
    
    # Handle Windows camera backend issue if source is a webcam
    if isinstance(source, int) and os.name == 'nt':
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(source)
        
    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return
        
    print("\n=======================================================")
    print(f"Starting Data Collection from source: {source}")
    print(f"Saving a frame every {interval} seconds to '{output_dir}'.")
    print(f"Target: {max_frames} frames.")
    print("Move your parts around the camera so it captures different angles!")
    print("Press 'q' to stop early.")
    print("=======================================================\n")
    
    frame_count = 0
    last_capture_time = time.time()
    
    while frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            print("End of stream or cannot grab frame.")
            break
            
        # Display the live feed with instructions
        display_frame = frame.copy()
        cv2.putText(display_frame, f"Collected: {frame_count}/{max_frames}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(display_frame, "Move object & press 'q' to exit", (20, 80), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        cv2.imshow("WARLOG Data Collection", display_frame)
        
        current_time = time.time()
        # Save a frame every 'interval' seconds
        if current_time - last_capture_time >= interval:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = os.path.join(output_dir, f"warlog_{timestamp}_{frame_count}.jpg")
            
            # Save the clean frame (without text overlay)
            cv2.imwrite(filename, frame)
            
            # Create an empty txt file for labels (required by YOLO)
            label_filename = os.path.join(labels_dir, f"warlog_{timestamp}_{frame_count}.txt")
            with open(label_filename, 'w') as f:
                pass 
                
            print(f"Saved: {filename} ({frame_count+1}/{max_frames})")
            
            last_capture_time = current_time
            frame_count += 1
            
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Collection stopped by user.")
            break
            
    cap.release()
    cv2.destroyAllWindows()
    print(f"\nDone! Collected {frame_count} images.")
    print(f"Your dataset images are located in: {os.path.abspath(output_dir)}")
    print("Next step: Upload these to Roboflow, CVAT, or Label Studio to draw bounding boxes!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WARLOG Dataset Collector")
    parser.add_argument('--source', default=0, help="Video source: 0 for webcam, or path to .mp4")
    parser.add_argument('--out', default='images/train', help="Output directory")
    parser.add_argument('--interval', type=float, default=1.5, help="Seconds between frames")
    parser.add_argument('--max', type=int, default=50, help="Maximum number of frames to collect")
    
    args = parser.parse_args()
    
    # Handle int for webcam vs string for video file
    source = int(args.source) if str(args.source).isdigit() else args.source
    
    collect_data(source=source, output_dir=args.out, interval=args.interval, max_frames=args.max)
