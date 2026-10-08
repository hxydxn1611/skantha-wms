from ultralytics import YOLO

def compress_model():
    print("=======================================================")
    print("WARLOG Model Compressor & Optimizer")
    print("=======================================================\n")
    print("Loading heavy PyTorch model (yolov8s-world.pt)...")
    
    # Load the base model
    model = YOLO("yolov8s-world.pt")
    
    # Define our exact warehouse classes so they are baked into the model
    # This makes it "highly intelligent" without needing text encoding at runtime
    custom_classes = [
        "box", "bundle", "pallet", "engine block", 
        "windshield", "bumper", "screw box", "steering wheel", 
        "tire bundle", "hood", "truck", "forklift", "person", "license plate"
    ]
    model.set_classes(custom_classes)
    
    print(f"Baking {len(custom_classes)} custom warehouse classes directly into the neural network graph...")
    
    # Export to ONNX format with FP16 Half-precision quantization
    # This massively shrinks the file size and boosts speed
    print("Compressing model to TorchScript (FP16 Precision)... this may take a minute.")
    exported_path = model.export(
        format="torchscript",
        half=True,       # FP16 quantization
        imgsz=640
    )
    
    print(f"\n✅ Model successfully compressed and optimized!")
    print(f"Your new highly-intelligent micro-model is located at: {exported_path}")
    print("\nTo use it, just update identity_service.py to load 'yolov8s-world.onnx'!")

if __name__ == "__main__":
    compress_model()
