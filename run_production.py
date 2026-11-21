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


# ---------------------------------------------------------------------------- server log file
# Everything the server prints (and logs) also goes to logs/server.log, so if the server ever
# stops we can see why: clean stop, Ctrl+C, console window closed, Windows shutdown, a Python
# error, or a hard crash inside a native library. A heartbeat line every 10 minutes shows
# roughly when it was last alive. The file rotates at 20 MB (5 old files kept).
LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "server.log")
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_KEEP = 5


def _setup_server_log():
    import atexit
    import datetime as _dt
    import faulthandler
    import threading
    import traceback

    os.makedirs(LOG_DIR, exist_ok=True)
    lock = threading.RLock()

    def rotate():
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) >= LOG_MAX_BYTES:
            for i in range(LOG_KEEP - 1, 0, -1):
                src, dst = f"{LOG_FILE}.{i}", f"{LOG_FILE}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(LOG_FILE, f"{LOG_FILE}.1")

    rotate()
    state = {"fh": open(LOG_FILE, "a", encoding="utf-8", buffering=1), "writes": 0}

    def write(text):
        with lock:
            try:
                state["fh"].write(text)
                state["writes"] += 1
                if state["writes"] % 500 == 0 and state["fh"].tell() >= LOG_MAX_BYTES:
                    state["fh"].close()
                    rotate()
                    state["fh"] = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
                    faulthandler.enable(file=state["fh"], all_threads=True)
            except Exception:
                pass

    def mark(msg):
        write(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] ===== {msg} =====\n")
        try:
            state["fh"].flush()
        except Exception:
            pass

    class _Tee:
        """Console output still shows in the window and is also kept in the log file."""
        def __init__(self, stream):
            self.stream = stream
        def write(self, s):
            try:
                self.stream.write(s)
            except Exception:
                pass
            write(s)
            return len(s)
        def flush(self):
            try:
                self.stream.flush()
            except Exception:
                pass
        def __getattr__(self, name):
            return getattr(self.stream, name)

    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)
    # logging.basicConfig's handler holds the old stderr: point it at the tee as well
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) in (sys.stdout.stream, sys.stderr.stream):
            h.setStream(sys.stderr)

    # hard crashes inside native code (torch / OpenCV / drivers) write a traceback here
    faulthandler.enable(file=state["fh"], all_threads=True)

    def on_uncaught(exc_type, exc, tb):
        mark(f"UNCAUGHT ERROR - server stopping: {exc_type.__name__}: {exc}")
        write("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.excepthook = on_uncaught

    def on_thread_error(args):
        write(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] [thread {getattr(args.thread, 'name', '?')}] uncaught error: "
              f"{args.exc_type.__name__}: {args.exc_value}\n")
        write("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = on_thread_error

    atexit.register(lambda: mark("SERVER STOPPED (normal exit)"))

    # Windows: closing the console window, logging off or shutting down
    if sys.platform == "win32":
        try:
            import ctypes
            names = {0: "Ctrl+C pressed", 1: "Ctrl+Break pressed", 2: "console window closed",
                     5: "Windows user logged off", 6: "Windows shutting down"}
            HANDLER = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

            def on_console_event(event):
                mark(f"SERVER STOPPING: {names.get(event, f'console event {event}')}")
                return 0   # let Windows continue with the normal stop
            state["console_handler"] = HANDLER(on_console_event)   # keep a reference alive
            ctypes.windll.kernel32.SetConsoleCtrlHandler(state["console_handler"], True)
        except Exception as e:
            write(f"(console stop events not recorded: {e})\n")

    def heartbeat():
        import time
        while True:
            time.sleep(600)
            mem = ""
            try:
                import psutil
                mem = f" | memory {psutil.Process().memory_info().rss / 1024 / 1024:.0f} MB"
            except Exception:
                pass
            write(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] heartbeat: server alive{mem} | threads {threading.active_count()}\n")
    threading.Thread(target=heartbeat, name="log-heartbeat", daemon=True).start()

    mark(f"SERVER START pid={os.getpid()} python={sys.version.split()[0]}")
    return mark


_log_mark = _setup_server_log()

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
    except Exception as e:
        logger.warning(f"Waitress notice: {e}. Running on threaded Flask engine.")
        flask_app_module.app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log_mark("SERVER STOPPED (Ctrl+C)")
