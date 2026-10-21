"""
W.A.R.L.O.G. / Skantha WMS - Enterprise Production Server Runner
Powered by Waitress WSGI Server (Multi-Threaded Production Deployment)

Supports:
- High-concurrency production serving via Waitress (8 worker threads)
- Multi-device access across local warehouse Wi-Fi / LAN
- Mobile phone browser access with terminal QR code
- Zero development server warnings
"""

import os
import sys
import logging

# Ensure UTF-8 output on Windows for terminal QR code and Unicode logs
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure path so webapp modules import cleanly
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
)
logger = logging.getLogger("production_runner")

def get_local_ip():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_banner(host, port):
    local_ip = get_local_ip()
    banner = "=" * 70
    print("\n" + banner)
    print(" 🚀 SKANTHA WMS & W.A.R.L.O.G. — PRODUCTION SERVER")
    print(" Model: YOLO11s (Flagship) | WSGI: Waitress Multi-Threaded Engine")
    print(banner)
    print(f" • Local Access:   http://localhost:{port}")
    print(f" • Network Access: http://{local_ip}:{port}")
    print(banner)
    print(" Server is actively listening on all interfaces (0.0.0.0). Press CTRL+C to stop.\n")

def main():
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    threads = int(os.environ.get("THREADS", 32))

    # Import Flask app
    import app as flask_app_module

    print_banner(host, port)

    try:
        from waitress import serve
        serve(
            flask_app_module.app,
            host=host,
            port=port,
            threads=threads,
            channel_timeout=120,
            cleanup_interval=30
        )
    except ImportError:
        logger.warning("Waitress not installed. Falling back to native Flask server.")
        flask_app_module.app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == "__main__":
    main()
