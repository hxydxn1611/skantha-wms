"""
W.A.R.L.O.G. / Skantha WMS - Mobile & Remote HTTPS Access Runner
Starts Waitress WSGI Server and binds an encrypted public HTTPS tunnel.

Mobile browsers (Safari/iOS & Chrome/Android) strictly enforce HTTPS
for device camera streaming (navigator.mediaDevices.getUserMedia).
This runner creates a trusted HTTPS endpoint and terminal QR code.
"""

import os
import sys
import time
import socket
import logging
import threading
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(ROOT_DIR, "webapp")
if WEBAPP_DIR not in sys.path:
    sys.path.insert(0, WEBAPP_DIR)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s][%(name)s] %(message)s")
logger = logging.getLogger("mobile_access")

def get_public_ip():
    """Fetch external IP for tunnel verification password."""
    try:
        import urllib.request
        return urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode().strip()
    except Exception:
        return "Check ipify.org"

def start_waitress(host="0.0.0.0", port=5000, threads=8):
    import app as flask_app_module
    from waitress import serve
    serve(
        flask_app_module.app,
        host=host,
        port=port,
        threads=threads,
        channel_timeout=120,
        cleanup_interval=30
    )

def print_mobile_banner(tunnel_url, public_ip, local_port):
    banner = "=" * 70
    print("\n" + banner)
    print(" 📱 SKANTHA WMS & W.A.R.L.O.G. — SECURE MOBILE & REMOTE DEPLOYMENT")
    print(" Active Detector: YOLO11s | Protocol: Valid Public HTTPS (SSL/TLS)")
    print(banner)
    print(f" • Secure Mobile HTTPS URL:  {tunnel_url}")
    print(f" • One-Time Tunnel Password: {public_ip}")
    print(f" • Local Backend Port:       http://localhost:{local_port}")
    print(banner)
    print(" 📲 HOW TO ACCESS FROM YOUR PHONE:")
    print(" 1. Point your phone camera at the QR code below or open the HTTPS URL.")
    print(f" 2. On first visit, localtunnel asks for 'Endpoint IP' — enter: {public_ip}")
    print(" 3. Log into WMS (admin / admin123).")
    print(" 4. Go to Camera Junction -> Add Camera -> Select 'Device Camera' (Front/Back).")
    print("    Full live AI perception with YOLO11 runs directly from your phone camera!")
    print(banner + "\n")

    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(tunnel_url)
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f" (QR code rendering skipped: {e})")

    print("\n" + banner)
    print(" Press CTRL+C in this terminal window to stop the server and tunnel.")
    print(banner + "\n")

def main():
    port = int(os.environ.get("PORT", 5000))

    # 1. Start Waitress in background thread
    server_thread = threading.Thread(target=start_waitress, kwargs={"port": port}, daemon=True)
    server_thread.start()
    logger.info("Waitress production server started on port %s", port)
    time.sleep(2)

    # 2. Get public IP password
    public_ip = get_public_ip()

    # 3. Start localtunnel process
    logger.info("Establishing secure public HTTPS tunnel for mobile devices...")
    try:
        cmd = ["npx.cmd" if sys.platform == "win32" else "npx", "-y", "localtunnel", "--port", str(port)]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1
        )

        tunnel_url = None
        for line in proc.stdout:
            clean = line.strip()
            if "your url is:" in clean:
                tunnel_url = clean.split("your url is:")[1].strip()
                print_mobile_banner(tunnel_url, public_ip, port)
                break

        # Keep alive
        proc.wait()
    except KeyboardInterrupt:
        logger.info("Shutting down mobile access tunnel and server.")
    except Exception as e:
        logger.error("Tunnel failed: %s", e)

if __name__ == "__main__":
    main()
