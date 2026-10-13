from ultralytics import YOLO
import sys

def compress_model(weights_path="yolo11s.pt"):
    print("=======================================================")
    print("WARLOG YOLO11 Model Compressor & Optimizer")
    print("=======================================================\n")
    print(f"Loading YOLO11 PyTorch model ({weights_path})...")
    
    # Load the base model
    model = YOLO(weights_path)
    
    # Export to TorchScript format with FP16 Half-precision quantization
    # This massively shrinks the file size and boosts speed
    print("Compressing model to TorchScript (FP16 Precision)... this may take a minute.")
    exported_path = model.export(
        format="torchscript",
        half=True,       # FP16 quantization
        imgsz=640
    )
    
    print(f"\n✅ YOLO11 Model successfully compressed and optimized!")
    print(f"Your new micro-model is located at: {exported_path}")
    print(f"\nTo use it in production, update detection_service.py to load '{exported_path}'!")

if __name__ == "__main__":
    weights = sys.argv[1] if len(sys.argv) > 1 else "yolo11s.pt"
    compress_model(weights)
