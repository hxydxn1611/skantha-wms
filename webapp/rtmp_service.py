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

        # Also ensure any Gate / Inbound camera receives the RTMP video feed
        try:
            from db import get_db
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT camera_id, camera_code FROM cameras WHERE (location = 'Gate' OR location = 'Dock' OR name LIKE '%gate%') AND status != 'Inactive'")
            for r in cur.fetchall():
                if r[0] and r[0] not in target_ids:
                    target_ids.append(r[0])
                if r[1] and r[1] not in target_ids:
                    target_ids.append(r[1])
            conn.close()
        except Exception:
            pass

        if "cam_inbound_01" not in target_ids:
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
                # Reset per-connection frame timer so watchdog only monitors active stream silence
                conn_last_frame = [0.0]
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

                def _watchdog(p, timer_ref):
                    while self.is_running and p.poll() is None:
                        time.sleep(1.0)
                        if timer_ref[0] > 0 and (time.time() - timer_ref[0]) > 8.0:
                            logger.info("RTMP Watchdog: Camera feed silent > 8s. Recycling port 1935 listener for instant reconnect.")
                            try:
                                p.kill()
                            except Exception:
                                pass
                            break
                watchdog_thread = threading.Thread(
                    target=_watchdog,
                    args=(self.proc, conn_last_frame),
                    daemon=True,
                    name="RTMP-Watchdog"
                )
                watchdog_thread.start()

                while self.is_running and self.proc.poll() is None:
                    raw_bytes = self.proc.stdout.read(frame_size)
                    if len(raw_bytes) != frame_size:
                        break

                    frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((480, 640, 3)).copy()
                    now_f = time.time()
                    self.last_frame_time = now_f
                    conn_last_frame[0] = now_f
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

                    # Also broadcast live feed directly to any active Gate cameras
                    try:
                        from app import active_cameras
                        for ac_id, ac_cam in list(active_cameras.items()):
                            if getattr(ac_cam, 'is_gate_camera', False) or ac_cam.location == 'Gate':
                                ac_cam.raw_frame = frame
                                ac_cam.push_frame(frame)
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
