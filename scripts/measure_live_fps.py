"""
Live-feed FPS on the RUNNING server (read-only): frames per second from /video_feed/<camera>.

  py -3.14 scripts/measure_live_fps.py [camera_id] [seconds] [base_url]

Signs a session for `admin` locally with FLASK_SECRET_KEY from .env (nothing leaves this
machine) and reads the database only to get admin's user id and session version.
"""
import os
import sqlite3
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
camera = sys.argv[1] if len(sys.argv) > 1 else "CAM-001"
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
base = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:5000"

secret = None
with open(os.path.join(ROOT, ".env"), encoding="utf-8") as fh:
    for line in fh:
        if line.strip().startswith("FLASK_SECRET_KEY="):
            secret = line.split("=", 1)[1].strip().strip('"').strip("'")
conn = sqlite3.connect(f"file:{os.path.join(ROOT, 'webapp', 'skandha_wms.db')}?mode=ro", uri=True)
uid, sv = conn.execute("SELECT id, session_version FROM users WHERE LOWER(username) = 'admin'").fetchone()
conn.close()

from flask import Flask  # noqa: E402
from flask.sessions import SecureCookieSessionInterface  # noqa: E402

app = Flask("fps")
app.secret_key = secret
cookie = SecureCookieSessionInterface().get_signing_serializer(app).dumps(
    {"user": {"username": "admin", "uid": uid, "sv": sv, "must_reset_password": False}, "csrf": "fps"})

req = urllib.request.Request(f"{base}/video_feed/{camera}", headers={"Cookie": f"session={cookie}"})
resp = urllib.request.urlopen(req, timeout=30)
frames, start = 0, None
warm_until = time.time() + 3
while True:
    chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
    if not chunk:
        break
    now = time.time()
    if now < warm_until:
        continue
    if start is None:
        start = now
    frames += chunk.count(b"--frame")
    if now - start >= seconds:
        break
elapsed = time.time() - start
resp.close()
print(f"FPS {camera}: {frames / elapsed:.2f}  ({frames} frames in {elapsed:.1f}s)")
