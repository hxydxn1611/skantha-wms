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
        """Finds camera IDs registered in the system that should receive this RTMP feed."""
        target_ids = []
        try:
            from db import get_db
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT camera_id, camera_code, camera_type, vendor, stream_url FROM cameras WHERE status != 'Inactive'")
            rows = cur.fetchall()
            conn.close()

            # First priority: cameras explicitly set to Wi-Fi Camera, Trueview, or rtmp URL
            for r in rows:
                cid, ccode, ctype, vendor, surl = r[0], r[1], r[2], r[3], (r[4] or "")
                if "rtmp" in surl.lower() or vendor == "Trueview" or ctype == "Wi-Fi Camera":
                    target_ids.append(cid)
                    if ccode and ccode not in target_ids:
                        target_ids.append(ccode)

            # Fallback priority: if no specific Wi-Fi camera, take all active camera IDs
            if not target_ids:
                for r in rows:
                    target_ids.append(r[0])
                    if r[1] and r[1] not in target_ids:
                        target_ids.append(r[1])
        except Exception as e:
            logger.warning(f"Error querying target cameras for RTMP: {e}")

        # Always include active_cameras keys if any
        try:
            from app import active_cameras
            for k in active_cameras.keys():
                if k not in target_ids:
                    target_ids.append(k)
        except Exception:
            pass

        return target_ids

    def _loop(self):
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            logger.warning("ffmpeg is not installed or not found in system PATH. RTMP Ingest Service disabled.")
            self.is_running = False
            return

        cmd = [
            ffmpeg_bin,
            "-loglevel", "warning",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-listen", "1",
            "-timeout", "15000000",
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
                    bufsize=10**7
                )

                while self.is_running and self.proc.poll() is None:
                    raw_bytes = self.proc.stdout.read(frame_size)
                    if len(raw_bytes) != frame_size:
                        break

                    frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((480, 640, 3))
                    self.last_frame_time = time.time()
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
                                active_cameras[cid].push_frame(frame)
                        except Exception:
                            pass

                    if self.frame_count % 150 == 0:
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

            time.sleep(1)

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
