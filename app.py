"""
Skantha WMS & W.A.R.L.O.G. - Hugging Face Spaces Entrypoint (Gradio SDK / ASGI)
Mounts the entire Flask WMS application onto FastAPI/Uvicorn on port 7860.
Provides 16 GB RAM and 2 vCPUs on Hugging Face Spaces for 100% Free!
"""

import os
import sys

# Configure webapp path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import uvicorn
from fastapi import FastAPI
from a2wsgi import WSGIMiddleware
def ensure_model_weights():
    target = os.path.join(WEBAPP_DIR, "yolo11s.pt")
    if not os.path.exists(target):
        print("📥 Downloading flagship YOLO11 weights (yolo11s.pt) into container...")
        try:
            import urllib.request
            url = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt"
            urllib.request.urlretrieve(url, target)
            print("✅ Flagship YOLO11 weights successfully initialized.")
        except Exception as e:
            print(f"⚠️ Model pre-download notice: {e} (Fallback yolo11n.pt active).")

ensure_model_weights()

import app as flask_app_module

# Wrap the existing Flask application inside ASGI
app = FastAPI(title="Skantha WMS & W.A.R.L.O.G. AI Vision")
app.mount("/", WSGIMiddleware(flask_app_module.app))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"🚀 Starting Skantha WMS on port {port} (Hugging Face Spaces)...")
    uvicorn.run(app, host="0.0.0.0", port=port)
