"""
Comprehensive Performance and Concurrency Benchmark for Skantha WMS / W.A.R.L.O.G.
Collects empirical latency distributions (p50, p95, p99), throughput (FPS),
resource utilization (CPU, RAM, GPU VRAM), and concurrency metrics.
"""

import os
import sys
import time
import json
import psutil
import threading
import numpy as np
import cv2

# Add webapp directory to sys.path
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEBAPP_DIR = os.path.join(WORKSPACE_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

import torch
from model_loader import get_shared_detector, resolve_model_path, DEFAULT_VERIFIED_MODEL
from detection_service import get_detection_engine
from tracking_service import get_tracking_service
from identity_service import get_identity_service
from vision_runtime_service import BoundedFrameQueue, get_shared_frame_bus
import app as flask_app_module

def calc_stats(latencies_ms):
    if not latencies_ms:
        return {}
    arr = np.array(latencies_ms)
    return {
        "count": len(arr),
        "min_ms": round(float(np.min(arr)), 2),
        "mean_ms": round(float(np.mean(arr)), 2),
        "p50_ms": round(float(np.percentile(arr, 50)), 2),
        "p95_ms": round(float(np.percentile(arr, 95)), 2),
        "p99_ms": round(float(np.percentile(arr, 99)), 2),
        "max_ms": round(float(np.max(arr)), 2),
        "std_ms": round(float(np.std(arr)), 2),
        "fps": round(1000.0 / float(np.mean(arr)), 2) if np.mean(arr) > 0 else 0.0
    }

def run_benchmark():
    results = {}
    proc = psutil.Process()
    ram_start_mb = proc.memory_info().rss / (1024 * 1024)
    results["system"] = {
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None",
        "initial_rss_mb": round(ram_start_mb, 2)
    }

    # 1. Model Loading Benchmark
    t0 = time.time()
    detector = get_detection_engine()
    model, model_name, err = get_shared_detector("yolo11n.pt")
    t_load = (time.time() - t0) * 1000.0
    results["model_loading"] = {
        "model_name": model_name,
        "load_time_ms": round(t_load, 2),
        "model_error": err
    }

    # 2. Synthetic Test Frame
    test_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    cv2.rectangle(test_frame, (100, 100), (300, 400), (0, 0, 255), -1) # simulated object
    cv2.putText(test_frame, "TEST BOX", (120, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    # 3. GPU YOLO Inference Latency
    if torch.cuda.is_available():
        gpu_times = []
        # Warmup
        for _ in range(5):
            _ = model(test_frame, device="cuda:0", verbose=False)
        torch.cuda.synchronize()

        for _ in range(50):
            t_start = time.perf_counter()
            _ = model(test_frame, device="cuda:0", verbose=False)
            torch.cuda.synchronize()
            gpu_times.append((time.perf_counter() - t_start) * 1000.0)

        results["yolo_gpu_inference"] = calc_stats(gpu_times)
        results["yolo_gpu_inference"]["vram_allocated_mb"] = round(torch.cuda.memory_allocated() / (1024 * 1024), 2)
        results["yolo_gpu_inference"]["vram_reserved_mb"] = round(torch.cuda.memory_reserved() / (1024 * 1024), 2)

    # 4. CPU YOLO Inference Latency
    cpu_times = []
    # Warmup
    for _ in range(2):
        _ = model(test_frame, device="cpu", verbose=False)

    for _ in range(20):
        t_start = time.perf_counter()
        _ = model(test_frame, device="cpu", verbose=False)
        cpu_times.append((time.perf_counter() - t_start) * 1000.0)

    results["yolo_cpu_inference"] = calc_stats(cpu_times)

    # 5. ByteTrack Multi-Object Tracking Latency
    tracker_service = get_tracking_service()
    tracker_times = []
    for f_idx in range(30):
        # Shift synthetic box slightly to simulate motion
        dyn_frame = test_frame.copy()
        cv2.rectangle(dyn_frame, (100 + f_idx * 2, 100), (300 + f_idx * 2, 400), (0, 255, 0), -1)
        t_start = time.perf_counter()
        _ = tracker_service.track_frame("BENCH_CAM", dyn_frame)
        tracker_times.append((time.perf_counter() - t_start) * 1000.0)

    results["detection_and_bytetrack"] = calc_stats(tracker_times)

    # 6. Barcode & QR Code Decoding Latency (ZXing + OpenCV)
    from identity_service import BarcodeQRDecoder
    barcode_decoder = BarcodeQRDecoder()
    qr_frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    qr_times = []
    for _ in range(30):
        t_start = time.perf_counter()
        _ = barcode_decoder.decode(qr_frame)
        qr_times.append((time.perf_counter() - t_start) * 1000.0)
    results["qr_and_barcode_decode_latency"] = calc_stats(qr_times)

    # 7. EasyOCR Inference Latency (Plate/Label OCR)
    try:
        import easyocr
        ocr_reader = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
        # Test crop: 80x250 image with text
        ocr_crop = np.full((80, 250, 3), 255, dtype=np.uint8)
        cv2.putText(ocr_crop, "MH12DE1432", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        ocr_times = []
        for _ in range(10):
            t_start = time.perf_counter()
            _ = ocr_reader.readtext(ocr_crop)
            ocr_times.append((time.perf_counter() - t_start) * 1000.0)
        results["easyocr_crop_inference"] = calc_stats(ocr_times)
    except Exception as e:
        results["easyocr_crop_inference"] = {"error": str(e)}

    # 8. Bounded Frame Queue Drop-Oldest Benchmark
    bfq = BoundedFrameQueue(maxsize=5)
    # Fast producer: push 25 frames
    for i in range(25):
        bfq.put_frame(test_frame)
    results["bounded_queue_test"] = {
        "maxsize": 5,
        "pushed": 25,
        "queue_current_depth": bfq.depth,
        "total_dropped": bfq.total_dropped,
        "total_received": bfq.total_received,
        "drop_policy_verified": bfq.total_dropped == 20
    }

    # 9. Flask API Response Latency (Baseline Idle)
    client = flask_app_module.app.test_client()
    endpoints = [
        "/api/skus",
        "/api/cameras",
        "/api/vision/zones",
        "/api/vision/object_classes"
    ]
    api_idle_times = []
    for _ in range(15):
        for ep in endpoints:
            t_start = time.perf_counter()
            resp = client.get(ep)
            api_idle_times.append((time.perf_counter() - t_start) * 1000.0)
    results["api_latency_idle"] = calc_stats(api_idle_times)

    # 10. Flask API Response Latency Under Concurrent AI Inference
    ai_stop = threading.Event()
    def background_inference_worker():
        while not ai_stop.is_set():
            _ = tracker_service.track_frame("BENCH_CAM", test_frame)
            time.sleep(0.01)

    ai_worker = threading.Thread(target=background_inference_worker, daemon=True)
    ai_worker.start()
    time.sleep(0.1) # let worker spin up

    api_loaded_times = []
    for _ in range(15):
        for ep in endpoints:
            t_start = time.perf_counter()
            resp = client.get(ep)
            api_loaded_times.append((time.perf_counter() - t_start) * 1000.0)

    ai_stop.set()
    ai_worker.join(timeout=2.0)
    results["api_latency_under_ai_load"] = calc_stats(api_loaded_times)

    # Final Resource Utilization
    ram_end_mb = proc.memory_info().rss / (1024 * 1024)
    results["resources"] = {
        "ram_start_mb": round(ram_start_mb, 2),
        "ram_end_mb": round(ram_end_mb, 2),
        "ram_growth_mb": round(ram_end_mb - ram_start_mb, 2),
        "cpu_percent": psutil.cpu_percent(interval=0.2)
    }

    print("\n" + "="*70)
    print("BENCHMARK RESULTS JSON:")
    print("="*70)
    print(json.dumps(results, indent=2))
    
    with open("scratch/benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_benchmark()
