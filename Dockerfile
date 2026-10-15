# Multi-Platform Production Dockerfile for Skantha WMS & W.A.R.L.O.G.
# Supports NVIDIA CUDA GPU acceleration and CPU fallback
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=5000 \
    VISION_MODEL_NAME=yolo11s.pt \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

# Install OS libraries required by OpenCV, PyTorch, and video capture
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install PyTorch
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir waitress gunicorn psutil qrcode

# Copy application source code
COPY webapp /app/webapp
COPY run_production.py /app/
COPY ml_pipeline /app/ml_pipeline

# Ensure YOLO11 models are baked into the image
RUN python3 -c "import os; from ultralytics import YOLO; [YOLO(m) for m in ['yolo11s.pt', 'yolo11n.pt'] if not os.path.exists(f'/app/webapp/{m}')]" && \
    mv -f yolo11*.pt /app/webapp/ 2>/dev/null || true

# Create persistent storage directories
RUN mkdir -p /app/webapp/static/uploads/sku_images && \
    mkdir -p /app/webapp/models

EXPOSE 5000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/api/cameras || exit 1

# Production WSGI server execution
CMD ["python", "run_production.py"]
