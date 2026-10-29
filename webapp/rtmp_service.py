import subprocess
import threading
import time
import os
import logging
import numpy as np
import cv2

logger = logging.getLogger("rtmp_service")
logger.setLevel(logging.INFO)

class RTMPIngestService:
    def __init__(self, port: int = 1935, stream_path: str = "/live/cam"):
        self.port = port
        self.stream_path = stream_path
        self.is_running = False
        self.thread = None
        self.proc = None
        self.last_frame_time = 0
        self.frame_count = 0
        self.latest_frame = None
        self._cached_targets = []
        self._last_targets_time = 0.0

    def invalidate_target_cache(self):
        self._last_targets_time = 0.0

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="RTMP-Ingest-Worker")
        self.thread.start()
        logger.info(f"RTMP Ingest Service started on rtmp://0.0.0.0:{self.port}{self.stream_path}")

    def stop(self):
        self.is_running = False
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    def _get_target_camera_ids(self):
        """Finds camera IDs registered in the system that should receive this RTMP feed (cached 1.5s)."""
        now = time.time()
        if self._cached_targets and (now - self._last_targets_time) < 1.5:
            return self._cached_targets

        target_ids = []
        try:
            from db import get_db
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT camera_id, camera_code, camera_type, vendor, stream_url FROM cameras WHERE status != 'Inactive'")
            rows = cur.fetchall()
            conn.close()

            # Strictly target cameras that are RTMP / Wi-Fi cameras
            # NEVER send RTMP frames to IP Cameras, RTSP streams, DVRs, NVRs, or device webcams!
            for r in rows:
                cid, ccode, ctype, vendor, surl = r[0], r[1], (r[2] or "").lower(), (r[3] or "").lower(), (r[4] or "").lower()
                if "http" in surl or "rtsp" in surl or "device:" in surl or ctype in ("ip camera", "dvr", "nvr", "device camera"):
                    continue
                if "rtmp" in surl or vendor == "trueview" or "wi-fi" in ctype or "wifi" in ctype or "1935" in surl:
                    target_ids.append(cid)
                    if ccode and ccode not in target_ids:
                        target_ids.append(ccode)

            # If no camera specifically matched, check if any camera has 1935 in URL
            if not target_ids:
                for r in rows:
                    cid, ccode, ctype, vendor, surl = r[0], r[1], (r[2] or "").lower(), (r[3] or "").lower(), (r[4] or "").lower()
                    if "1935" in surl:
                        target_ids.append(cid)
                        if ccode and ccode not in target_ids:
                            target_ids.append(ccode)
        except Exception as e:
            logger.warning(f"Error querying target cameras for RTMP: {e}")

        # If no explicit Wi-Fi camera registered yet, default to fallback
        if not target_ids:
            target_ids.append("cam_inbound_01")

        self._cached_targets = target_ids
        self._last_targets_time = now
        return target_ids

    @staticmethod
    def _drain_stderr(proc):
        """Continuously drains FFmpeg stderr so the OS pipe buffer never blocks, while logging connection info."""
        try:
            for raw_line in iter(proc.stderr.readline, b""):
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line:
                    logger.info(f"[FFmpeg RTMP] {line}")
        except Exception:
            pass

    def _loop(self):
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            logger.warning("ffmpeg is not installed or not found in system PATH. RTMP Ingest Service disabled.")
            self.is_running = False
            return

        # Clean up any orphaned ffmpeg processes holding port 1935 from prior server runs
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "ffmpeg.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3
                )
            except Exception:
                pass

        cmd = [
            ffmpeg_bin,
            "-loglevel", "info",
            "-probesize", "65536",
            "-analyzeduration", "500000",
            "-fflags", "nobuffer+flush_packets",
            "-flags", "low_delay",
            "-rw_timeout", "4000000",
            "-listen", "1",
            "-i", f"rtmp://0.0.0.0:{self.port}{self.stream_path}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", "640x480",
            "-an",
            "-"
        ]

        frame_size = 640 * 480 * 3

        while self.is_running:
            try:
                logger.info(f"Listening for camera RTMP push on rtmp://0.0.0.0:{self.port}{self.stream_path} ...")
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=frame_size * 2
                )
                stderr_thread = threading.Thread(
                    target=self._drain_stderr,
                    args=(self.proc,),
                    daemon=True,
                    name="RTMP-FFmpeg-Stderr"
                )
                stderr_thread.start()

                # Active Watchdog: Auto-detects camera disconnection or freeze
                # Force-restarts FFmpeg listener so camera can reconnect in < 1 second!
                def _watchdog(p):
                    while self.is_running and p.poll() is None:
                        time.sleep(0.5)
                        if self.last_frame_time > 0 and (time.time() - self.last_frame_time) > 3.0:
                            logger.info("RTMP Watchdog: Camera feed silent > 3s. Recycling port 1935 listener for instant reconnect.")
                            try:
                                p.kill()
                            except Exception:
                                pass
                            break
                watchdog_thread = threading.Thread(
                    target=_watchdog,
                    args=(self.proc,),
                    daemon=True,
                    name="RTMP-Watchdog"
                )
                watchdog_thread.start()

                while self.is_running and self.proc.poll() is None:
                    raw_bytes = self.proc.stdout.read(frame_size)
                    if len(raw_bytes) != frame_size:
                        break

                    frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((480, 640, 3)).copy()
                    self.last_frame_time = time.time()
                    self.latest_frame = frame
                    self.frame_count += 1

                    # Dispatch frame to WarLog systems
                    targets = self._get_target_camera_ids()
                    for cid in targets:
                        try:
                            from vision_runtime_service import get_shared_frame_bus, get_vision_runtime_manager
                            get_shared_frame_bus().publish_frame(cid, frame, source_type="PUSH_DEVICE")
                            get_vision_runtime_manager().push_frame(cid, frame)
                        except Exception:
                            pass

                        try:
                            from app import active_cameras
                            if cid in active_cameras:
                                active_cameras[cid].raw_frame = frame
                                active_cameras[cid].push_frame(frame)
                        except Exception:
                            pass

                    if self.frame_count == 1 or self.frame_count % 100 == 0:
                        logger.info(f"RTMP Ingest: streamed {self.frame_count} frames to {targets}")

                # If process exited, wait briefly and restart listener
                if self.proc:
                    try:
                        self.proc.terminate()
                        self.proc.wait(timeout=1)
                    except Exception:
                        pass
                    self.proc = None

            except Exception as e:
                logger.error(f"RTMP Ingest listener exception: {e}")

            time.sleep(0.2)

_instance = None

def get_rtmp_service() -> RTMPIngestService:
    global _instance
    if _instance is None:
        _instance = RTMPIngestService()
    return _instance

def start_rtmp_service():
    srv = get_rtmp_service()
    srv.start()
    return srv
