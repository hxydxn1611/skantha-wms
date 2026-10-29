from ultralytics import YOLO
import argparse
import os

def train_warlog_model(model_weights='yolo11s.pt', data_yaml='data.yaml', epochs=50, imgsz=640):
    """
    Fine-tunes the flagship YOLO11 model for the WARLOG automotive parts dataset.
    Uses a small learning rate and freezes backbone layers to prevent catastrophic forgetting.
    """
    print(f"Loading pretrained weights from {model_weights}...")
    model = YOLO(model_weights)

    # Freeze the first 10 layers (backbone) to retain general object detection capabilities
    freeze = [f'model.{x}.' for x in range(10)]

    print("Starting fine-tuning...")
    # Train the model
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=16,
        lr0=0.001, 
        freeze=freeze,
        project='warlog_vision',
        name='automotive_finetune',
        exist_ok=True
    )
    
    best_pt_path = os.path.join('warlog_vision', 'automotive_finetune', 'weights', 'best.pt')
    print(f"Training complete! Model saved to {best_pt_path}")
    
    # Auto-deploy to webapp directory so live vision immediately loads it
    try:
        import shutil
        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        webapp_dest = os.path.join(proj_root, 'webapp', 'best.pt')
        if os.path.isfile(best_pt_path):
            shutil.copy2(best_pt_path, webapp_dest)
            print(f"-> Automatically deployed custom model weights to webapp: {webapp_dest}")
    except Exception as e:
        print(f"Note: Manual copy needed to webapp: {e}")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train WARLOG YOLO Model")
    parser.add_argument('--weights', type=str, default='yolo11s.pt', help='Pretrained weights (e.g. yolo11s.pt, yolo11m.pt)')
    parser.add_argument('--data', type=str, default='data.yaml', help='Path to data.yaml')
    parser.add_argument('--epochs', type=int, default=50, help='Number of epochs')
    
    args = parser.parse_args()
    train_warlog_model(model_weights=args.weights, data_yaml=args.data, epochs=args.epochs)
