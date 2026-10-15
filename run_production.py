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
import socket
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

def get_lan_ip_addresses():
    """Detect all non-loopback IPv4 addresses on the host system."""
    ip_list = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ip_list.append(ip)
    except Exception:
        pass

    # Fallback method using UDP socket to determine default routing interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        default_ip = s.getsockname()[0]
        s.close()
        if default_ip and default_ip not in ip_list:
            ip_list.insert(0, default_ip)
    except Exception:
        pass

    return ip_list or ["127.0.0.1"]

def print_banner(host, port, lan_ips):
    banner = "=" * 70
    print("\n" + banner)
    print(" 🚀 SKANTHA WMS & W.A.R.L.O.G. — ENTERPRISE PRODUCTION SERVER")
    print(" Model: YOLO11s (Flagship) | WSGI: Waitress Multi-Threaded Engine")
    print(banner)
    print(f" • Local Access:    http://localhost:{port}")
    for ip in lan_ips:
        print(f" • LAN / Wi-Fi:     http://{ip}:{port}")
    print(banner)
    print(" 📱 MOBILE PHONE ACCESS INSTRUCTIONS:")
    print(f" 1. Connect your phone to the same Wi-Fi network as this PC.")
    print(f" 2. Open phone browser and enter: http://{lan_ips[0]}:{port}")
    print(f"    Or scan the QR code below using your mobile phone camera:")
    print(banner + "\n")

    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        target_url = f"http://{lan_ips[0]}:{port}"
        qr.add_data(target_url)
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f" (Install 'qrcode' library to see interactive terminal QR code: {e})")

    print("\n" + banner)
    print(" Server is actively listening on all interfaces (0.0.0.0). Press CTRL+C to stop.")
    print(banner + "\n")

def main():
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    threads = int(os.environ.get("THREADS", 8))

    # Import Flask app
    import app as flask_app_module

    lan_ips = get_lan_ip_addresses()
    print_banner(host, port, lan_ips)

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
